"""Drena a fila do espelho: nicho + credencial + afiliado + template + foto."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from core import db, relogio, repositories
from core.config_provider import bots_ativos, load_filtros_runtime, usar_bot_runtime
from core.credentials import platforms_with_usable_credentials
from core.link_parser import extrair_links_oferta, loja_para_platform_slug
from core.mirror_media import imagem_do_link_produto
from core.mirror_webhook import ensure_platform_listen_webhook
from core.models import MirrorInbox
from core.platforms import affiliate
from core.platforms.base import OfertaCapturada
from worker import channels, filters, formatter, monitor, telemetry, whatsapp
from worker.logger import logger

_BATCH = 8


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
                passou_nicho = False
                motivo_nicho = "fora do nicho do grupo"
                link_nicho = links_ok[0]
                for link in links_ok:
                    oferta_nicho = OfertaCapturada(
                        nome=titulo,
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

                # Foto = URL pública do anúncio (CDN). Sem baixar/gravar no nosso disco.
                imagem = imagem_do_link_produto(link_nicho.url, link_nicho.loja)

                enviou_algum = False
                falhou_total = True
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
                        if not affiliate.link_rastreado(link_nicho.loja, url_afiliado):
                            logger.warning(
                                f"[espelho] sem afiliado rastreado para {item.id}"
                            )
                            continue
                        sub_id = getattr(convertido, "sub_id", None)

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
                        ok_envio = whatsapp.enviar_mensagem(
                            mensagem, imagem=oferta.imagem, grupo=jid
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
                                imagem=imagem,
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
                            "has_media": bool(imagem),
                        },
                    )
                    processados += 1
                elif falhou_total:
                    _marcar(item, "failed", "envio_ou_afiliado")
                    processados += 1
                else:
                    _marcar(item, "failed", "envio_parcial_falhou")
                    processados += 1

        session.commit()
    return processados


def garantir_webhooks() -> None:
    """Reaplica webhook na instância de escuta da plataforma (Nina 1)."""
    with db.get_session() as session:
        status = ensure_platform_listen_webhook(session)
        logger.info(f"[espelho] webhook plataforma: {status}")


def ciclo() -> None:
    try:
        n = processar_pendentes()
        if n:
            logger.info(f"[espelho] processados={n}")
    except Exception as exc:
        logger.exception(f"[espelho] ciclo falhou: {exc}")
