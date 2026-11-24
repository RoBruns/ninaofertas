"""Drena a fila do espelho: nicho + credencial + afiliado + template + foto."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import select

from core import db, relogio, repositories
from core.config_provider import bots_ativos, load_filtros_runtime, usar_bot_runtime
from core.credentials import platforms_with_usable_credentials
from core.link_parser import extrair_links_oferta, loja_para_platform_slug
from core.mirror_media import (
    ProdutoSomenteVideo,
    resolver_imagem_espelho,
    titulo_pagina_visto,
)
from core.mirror_webhook import ensure_platform_listen_webhook
from core.models import MirrorInbox, Phone
from core.platforms import affiliate
from core.platforms.base import OfertaCapturada
from worker import channels, filters, formatter, monitor, telemetry, whatsapp
from worker.titulo_enfeite import enfeitar_titulo, titulo_igual
from worker.logger import logger

_BATCH = 8
_ultimo_webhook_ts = 0.0
_WEBHOOK_TTL_S = 120.0


def _marcar(item: MirrorInbox, status: str, reason: str | None = None) -> None:
    item.status = status
    item.skip_reason = reason
    item.processed_at = datetime.now(timezone.utc)


def _token_canal(runtime, grupo_jid: str) -> str:
    return f"db:{runtime.id}:{grupo_jid}"


def _oferta_template(
    *,
    titulo: str,
    loja: str,
    url_afiliado: str,
    url_origem: str,
    body_text: str,
    sku: str,
    imagem: str | None,
) -> OfertaCapturada:
    preco, preco_anterior = filters.extrair_precos_mensagem(body_text)
    return OfertaCapturada(
        nome=titulo[:120],
        preco=float(preco or 0.0),
        preco_anterior=preco_anterior,
        loja=loja,
        url=url_afiliado,
        product_url=url_origem,
        sku=sku[:120],
        categoria="espelho",
        codigo_cupom=filters.extrair_cupom_mensagem(body_text),
        imagem=imagem,
    )


def processar_pendentes() -> int:
    """Processa até _BATCH itens pending. Retorna quantos saíram de pending."""
    processados = 0
    with db.get_session() as session:
        itens = session.scalars(
            select(MirrorInbox)
            .where(MirrorInbox.status == "pending")
            .order_by(MirrorInbox.created_at.asc())
            .limit(_BATCH)
        ).all()
        if not itens:
            return 0

        runtimes = {str(r.id): r for r in bots_ativos()}
        for item in itens:
            runtime = runtimes.get(str(item.bot_id))
            if runtime is None:
                _marcar(item, "skipped", "bot_inativo")
                processados += 1
                continue

            with usar_bot_runtime(runtime):
                filtros = load_filtros_runtime()
                if relogio.em_silencio(filtros.get("quiet_hours")):
                    continue

                links = extrair_links_oferta(item.body_text)
                if not links:
                    _marcar(item, "skipped", "sem_link_marketplace")
                    processados += 1
                    continue

                plataformas = platforms_with_usable_credentials(runtime.account_ids)
                links_ok = [
                    link
                    for link in links
                    if (slug := loja_para_platform_slug(link.loja)) and slug in plataformas
                ]
                if not links_ok:
                    _marcar(item, "skipped", "sem_conta_loja")
                    processados += 1
                    continue

                titulo = filters.titulo_mensagem_espelho(item.body_text)
                titulo_grupo = titulo
                nome_nicho = " ".join(filters.linhas_uteis_espelho(item.body_text)) or titulo
                passou_nicho = False
                motivo_nicho = "fora do nicho do grupo"
                link_nicho = links_ok[0]
                for link in links_ok:
                    oferta_nicho = OfertaCapturada(
                        nome=nome_nicho[:200],
                        preco=0.0,
                        loja=link.loja,
                        url=link.url,
                        sku=f"mirror:{item.id}"[:120],
                        categoria="espelho",
                    )
                    ok_nicho, motivo_nicho = filters.passa_filtros_espelho(
                        oferta_nicho, filtros
                    )
                    if ok_nicho:
                        passou_nicho = True
                        link_nicho = link
                        break
                if not passou_nicho:
                    _marcar(item, "skipped", f"nicho:{motivo_nicho}")
                    processados += 1
                    continue

                grupos = list(runtime.group_ids)
                if not grupos:
                    _marcar(item, "failed", "bot_sem_grupo")
                    processados += 1
                    continue

                oferta_probe = OfertaCapturada(
                    nome=titulo[:80],
                    preco=0.0,
                    loja=link_nicho.loja,
                    url=link_nicho.url,
                    sku=f"mirror:{item.id}"[:120],
                    categoria="espelho",
                )
                ok, motivo = monitor._freio_anti_ban(  # noqa: SLF001
                    session, filtros, grupos[0], oferta_probe
                )
                if not ok:
                    logger.info(f"[espelho] adiando {item.id}: {motivo}")
                    continue

                listen = session.get(Phone, item.listen_phone_id)
                imagem: str | None = None
                foto_resolvida = False
                somente_video = False

                def garantir_foto() -> None:
                    nonlocal imagem, foto_resolvida, somente_video
                    if foto_resolvida:
                        return
                    foto_resolvida = True
                    try:
                        imagem = resolver_imagem_espelho(
                            listen_instance=listen.evolution_instance if listen else None,
                            message_key=item.message_key,
                            product_url=link_nicho.url,
                            loja=link_nicho.loja,
                            media_path=item.media_path,
                        )
                    except ProdutoSomenteVideo:
                        somente_video = True

                garantir_foto()
                pagina = titulo_pagina_visto(link_nicho.url)
                if pagina and not filters.titulo_bate_com_pagina(titulo, pagina):
                    logger.info(
                        f"[espelho] título não bate com o link; usando o nome da página "
                        f"({titulo[:40]!r})"
                    )
                    titulo = filters.limpar_titulo_pagina(pagina)
                if somente_video or not imagem:
                    motivo = "somente_video" if somente_video else "sem_foto"
                    logger.info(f"[espelho] sem representação ({motivo}) {item.id}")
                    _marcar(item, "skipped", motivo)
                    processados += 1
                    continue
                titulo = enfeitar_titulo(titulo, titulo_grupo)
                if titulo_igual(titulo, titulo_grupo):
                    logger.info(f"[espelho] título igual ao do grupo; oferta não enviada {item.id}")
                    _marcar(item, "skipped", "titulo_igual")
                    processados += 1
                    continue

                enviou_algum = False
                falhou_total = True
                teve_foto = False
                for jid in grupos:
                    canal = _token_canal(runtime, jid)
                    with channels.usar_canal(canal):
                        group_id = channels.grupo_db_id()
                        convertido = affiliate.garantir_afiliado(
                            link_nicho.loja,
                            link_nicho.url,
                            group_id=group_id,
                            origin_url=link_nicho.url,
                        )
                        url_afiliado = str(convertido)
                        sub_id = getattr(convertido, "sub_id", None)
                        loja_l = (link_nicho.loja or "").lower()
                        # ML/Shopee: só envia se a conversão da CONTA do bot gerou sub_id.
                        # Link de afiliado de terceiro (meli.la alheio) não conta.
                        if (
                            ("mercado" in loja_l or "shopee" in loja_l)
                            and not sub_id
                        ):
                            logger.warning(
                                f"[espelho] sem afiliado da conta do bot para {item.id} "
                                f"(loja={link_nicho.loja})"
                            )
                            continue
                        if not affiliate.link_rastreado(link_nicho.loja, url_afiliado):
                            logger.warning(
                                f"[espelho] sem afiliado rastreado para {item.id}"
                            )
                            continue

                        oferta = _oferta_template(
                            titulo=titulo,
                            loja=link_nicho.loja,
                            url_afiliado=url_afiliado,
                            url_origem=link_nicho.url,
                            body_text=item.body_text,
                            sku=f"mirror:{item.id}",
                            imagem=imagem,
                        )
                        # Template do bot — sem citar o grupo de origem.
                        mensagem = formatter.montar_mensagem(oferta)
                        imagem_envio = imagem
                        teve_foto = True
                        ok_envio = whatsapp.enviar_mensagem(
                            mensagem, imagem=imagem, grupo=jid
                        )
                        oferta_db = monitor._salvar_oferta(  # noqa: SLF001
                            session,
                            OfertaCapturada(
                                nome=titulo[:120],
                                preco=float(oferta.preco or 0.0),
                                preco_anterior=oferta.preco_anterior,
                                loja=link_nicho.loja,
                                url=url_afiliado,
                                sku=f"mirror:{item.id}"[:120],
                                categoria="espelho",
                                imagem=imagem_envio,
                            ),
                        )
                        repositories.registrar_envio(
                            session,
                            oferta_id=oferta_db.id,
                            grupo=jid,
                            mensagem=mensagem[:2000],
                            preco=float(oferta.preco or 0.0),
                            status="sucesso" if ok_envio else "falha",
                            bot_id=runtime.id,
                            group_id=group_id,
                            sub_id=sub_id,
                        )
                        falhou_total = False
                        if ok_envio:
                            enviou_algum = True

                if enviou_algum:
                    _marcar(item, "done")
                    telemetry.registrar_evento(
                        "mirror_sent",
                        "Oferta espelhada enviada",
                        bot_id=runtime.id,
                        level="info",
                        detail={
                            "inbox_id": str(item.id),
                            "source": item.source_group_name,
                            "has_media": teve_foto,
                        },
                    )
                    processados += 1
                elif somente_video:
                    _marcar(item, "skipped", "somente_video")
                    processados += 1
                elif falhou_total:
                    _marcar(item, "failed", "envio_ou_afiliado")
                    processados += 1
                else:
                    _marcar(item, "failed", "envio_parcial_falhou")
                    processados += 1

        session.commit()
    return processados


def garantir_webhooks(*, forcar: bool = False) -> None:
    """Reaplica webhook na instância de escuta da plataforma (Nina 1)."""
    global _ultimo_webhook_ts
    agora = time.monotonic()
    if not forcar and (agora - _ultimo_webhook_ts) < _WEBHOOK_TTL_S:
        return
    with db.get_session() as session:
        status = ensure_platform_listen_webhook(session)
        logger.info(f"[espelho] webhook plataforma: {status}")
    _ultimo_webhook_ts = agora


def ciclo() -> None:
    try:
        # Garante webhookBase64=true (foto no upsert) sem martelar a Evolution.
        garantir_webhooks()
        n = processar_pendentes()
        if n:
            logger.info(f"[espelho] processados={n}")
    except Exception as exc:
        logger.exception(f"[espelho] ciclo falhou: {exc}")
