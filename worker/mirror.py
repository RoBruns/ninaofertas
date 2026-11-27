"""Drena a fila do espelho: nicho + credencial + afiliado + template + foto."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from core import db, relogio, repositories
from core.config_provider import bots_ativos, load_filtros_runtime, usar_bot_runtime
from core.credentials import platforms_with_usable_credentials
from core.link_parser import extrair_links_oferta, loja_para_platform_slug
from core.mirror_media import (
    ProdutoSomenteVideo,
    eh_logo_shopee,
    eh_loja_shopee,
    resolver_imagem_espelho,
    titulo_pagina_visto,
)
from core.mirror_webhook import ensure_platform_listen_webhook
from core.models import MirrorInbox, Phone
from core.platforms import affiliate
from core.platforms.base import OfertaCapturada
from core.product_key import chave_produto
from worker import channels, filters, formatter, monitor, telemetry, whatsapp
from worker.mirror_dedup import pode_enviar_produto, vencedores_do_lote
from worker.titulo_enfeite import enfeitar_titulo, titulo_igual
from worker.logger import logger

_BATCH = 8
_ultimo_webhook_ts = 0.0
_WEBHOOK_TTL_S = 120.0
# Cupom esgota — pending antigo demais não publica código morto.
_CUPOM_MAX_IDADE = timedelta(minutes=60)
# Enfeite pode chegar a ~160; 120 cortava no meio da frase ("todos os di").
_NOME_MAX = 200


def _marcar(item: MirrorInbox, status: str, reason: str | None = None) -> None:
    item.status = status
    item.skip_reason = reason
    item.processed_at = datetime.now(timezone.utc)


def _token_canal(runtime, grupo_jid: str) -> str:
    return f"db:{runtime.id}:{grupo_jid}"


def _foto_shopee_api(titulo: str, preco: float | None) -> str | None:
    """Foto do anúncio pela API de afiliado da conta do bot (runtime ativo)."""
    import httpx

    from core.platforms.shopee import credenciais_shopee_do_bot
    from core.platforms.shopee_api import foto_por_titulo

    _conta, app_id, secret = credenciais_shopee_do_bot()
    if not app_id or not secret:
        return None
    try:
        with httpx.Client(timeout=12.0) as client:
            return foto_por_titulo(
                client, titulo, app_id=app_id, secret=secret, preco=preco or None
            )
    except Exception as exc:
        logger.info(f"[espelho] busca de foto na API Shopee falhou: {exc}")
        return None


def _oferta_template(
    *,
    titulo: str,
    loja: str,
    url_afiliado: str,
    url_origem: str,
    body_text: str,
    sku: str,
    imagem: str | None,
    pagina: str | None = None,
) -> OfertaCapturada:
    preco, preco_anterior = filters.extrair_precos_mensagem(body_text)
    # Cupom da origem: ainda envia, mas sem 'De x por' (preço não é de produto).
    if filters.mensagem_eh_cupom_espelho(titulo, pagina=pagina):
        preco, preco_anterior = 0.0, None
    codigo = filters.extrair_cupom_mensagem(body_text)
    # Sem código digitável, ainda marca se a origem falou em cupom — preço depende disso.
    beneficio = None
    if not codigo and filters.mensagem_menciona_cupom(body_text):
        beneficio = "cupom_origem"
    return OfertaCapturada(
        nome=titulo[:_NOME_MAX],
        preco=float(preco or 0.0),
        preco_anterior=preco_anterior,
        loja=loja,
        url=url_afiliado,
        product_url=url_origem,
        sku=sku[:120],
        categoria="espelho",
        codigo_cupom=codigo,
        beneficio=beneficio,
        imagem=imagem,
    )


def corte_fila_do_dia(quando: datetime | None = None) -> datetime:
    """Último 23:59 de Brasília que já chegou. Oferta anterior a isso não sai."""
    agora = relogio.agora_br() if quando is None else quando.astimezone(relogio.BR)
    corte = agora.replace(hour=23, minute=59, second=0, microsecond=0)
    if agora < corte:
        corte -= timedelta(days=1)
    return corte


def expirar_pendentes(quando: datetime | None = None) -> int:
    """Tira da fila o que chegou antes do último 23:59. Não apaga o registro."""
    corte = corte_fila_do_dia(quando)
    with db.get_session() as session:
        resultado = session.execute(
            update(MirrorInbox)
            .where(MirrorInbox.status == "pending", MirrorInbox.created_at < corte)
            .values(
                status="skipped",
                skip_reason="passou_o_dia",
                processed_at=datetime.now(timezone.utc),
            )
        )
        return int(resultado.rowcount or 0)


def limpar_fila_pendente(*, motivo: str = "fila_limpa") -> int:
    """Marca todo pending como skipped. Usado no deploy para não drenar cópia velha."""
    with db.get_session() as session:
        resultado = session.execute(
            update(MirrorInbox)
            .where(MirrorInbox.status == "pending")
            .values(
                status="skipped",
                skip_reason=motivo[:80],
                processed_at=datetime.now(timezone.utc),
            )
        )
        return int(resultado.rowcount or 0)


def _item_com_cupom(item: MirrorInbox) -> bool:
    return bool(filters.extrair_cupom_mensagem(item.body_text or ""))


def _escolher_lote(candidatos: list[MirrorInbox], limite: int) -> list[MirrorInbox]:
    """Um por bot (ordem dos candidatos), depois completa até o limite."""
    if limite <= 0 or not candidatos:
        return []
    lote: list[MirrorInbox] = []
    vistos: set = set()
    for item in candidatos:
        if item.bot_id in vistos:
            continue
        lote.append(item)
        vistos.add(item.bot_id)
        if len(lote) >= limite:
            return lote
    ids = {item.id for item in lote}
    for item in candidatos:
        if item.id in ids:
            continue
        lote.append(item)
        if len(lote) >= limite:
            break
    return lote


def _lote_pendentes(session) -> list[MirrorInbox]:
    """Até _BATCH pending: cupom em FIFO estrito; depois justo por bot.

    Cupom esgota — o mais antigo com código sai primeiro, sem round-robin.
    Sem cupom, um por bot para o freio de um não engolir a fila dos outros.
    """
    janela = list(
        session.scalars(
            select(MirrorInbox)
            .where(MirrorInbox.status == "pending")
            .order_by(MirrorInbox.created_at.asc())
            .limit(max(_BATCH * 20, 80))
        ).all()
    )
    if not janela:
        return []
    com_cupom = [item for item in janela if _item_com_cupom(item)]
    sem_cupom = [item for item in janela if not _item_com_cupom(item)]
    # FIFO puro no subconjunto com cupom (já ordenado por created_at).
    lote = com_cupom[:_BATCH]
    if len(lote) < _BATCH:
        ids = {item.id for item in lote}
        resto = [item for item in sem_cupom if item.id not in ids]
        lote.extend(_escolher_lote(resto, _BATCH - len(lote)))
    return lote


def expirar_cupons_velhos() -> int:
    """Pending com cupom digitável e idade > 60 min → skipped (código morto)."""
    limite = datetime.now(timezone.utc) - _CUPOM_MAX_IDADE
    with db.get_session() as session:
        pendentes = list(
            session.scalars(
                select(MirrorInbox).where(
                    MirrorInbox.status == "pending",
                    MirrorInbox.created_at < limite,
                )
            ).all()
        )
        n = 0
        for item in pendentes:
            if not _item_com_cupom(item):
                continue
            _marcar(item, "skipped", "cupom_velho")
            n += 1
        return n


def processar_pendentes() -> int:
    """Processa até _BATCH itens pending. Retorna quantos saíram de pending."""
    encerradas = expirar_pendentes()
    if encerradas:
        logger.info(f"[espelho] {encerradas} oferta(s) do dia anterior saíram da fila")
    velhos = expirar_cupons_velhos()
    if velhos:
        logger.info(f"[espelho] {velhos} cupom(ns) com mais de 60 min saíram da fila")
    processados = 0
    with db.get_session() as session:
        itens = _lote_pendentes(session)
        if not itens:
            return 0

        runtimes = {str(r.id): r for r in bots_ativos()}
        # Primeiro passo: resolve chave/preço e escolhe a cópia mais barata do lote.
        preparados: dict[object, dict] = {}
        lote_chaves: list[tuple[object, str, float]] = []
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
                        sku="mirror-probe",
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
                if not runtime.group_ids:
                    _marcar(item, "failed", "bot_sem_grupo")
                    processados += 1
                    continue
                preco, _ant = filters.extrair_precos_mensagem(item.body_text)
                sku = chave_produto(
                    link_nicho.url, loja=link_nicho.loja, titulo=titulo
                ) or f"mirror:{item.id}"
                lote_chaves.append((item.id, f"{item.bot_id}:{sku}", float(preco or 0.0)))
                preparados[item.id] = {
                    "runtime": runtime,
                    "filtros": filtros,
                    "titulo": titulo,
                    "link": link_nicho,
                    "sku": sku[:120],
                    "preco": float(preco or 0.0),
                }

        vencedores = vencedores_do_lote(lote_chaves) if lote_chaves else set()
        for item_id, chave, _preco in lote_chaves:
            if item_id in vencedores:
                continue
            item = next((i for i in itens if i.id == item_id), None)
            if item is None or item.status != "pending":
                continue
            logger.info(f"[espelho] cópia mais cara no lote; pulando {item_id} ({chave})")
            _marcar(item, "skipped", "duplicado_produto")
            processados += 1
            preparados.pop(item_id, None)

        for item in itens:
            if item.status != "pending":
                continue
            prep = preparados.get(item.id)
            if prep is None:
                continue
            runtime = prep["runtime"]
            filtros = prep["filtros"]
            titulo = prep["titulo"]
            titulo_grupo = titulo
            link_nicho = prep["link"]
            sku = prep["sku"]
            preco = prep["preco"]
            grupos = list(runtime.group_ids)
            dedup_horas = int(filtros.get("dedup_horas_produto") or 24)

            with usar_bot_runtime(runtime):
                # Dedup por produto antes do freio — não gasta vaga com cópia.
                bloqueados = 0
                for jid in grupos:
                    ok_prod, motivo_prod = pode_enviar_produto(
                        session,
                        sku=sku,
                        loja=link_nicho.loja,
                        grupo=jid,
                        tenant_id=runtime.owner_id,
                        preco=preco,
                        dedup_horas=dedup_horas,
                    )
                    if not ok_prod:
                        bloqueados += 1
                if bloqueados == len(grupos):
                    logger.info(f"[espelho] produto já enviado ({sku}) {item.id}")
                    _marcar(item, "skipped", "duplicado_produto")
                    processados += 1
                    continue

                oferta_probe = OfertaCapturada(
                    nome=titulo[:80],
                    preco=preco,
                    loja=link_nicho.loja,
                    url=link_nicho.url,
                    sku=sku,
                    categoria="espelho",
                    codigo_cupom=filters.extrair_cupom_mensagem(item.body_text),
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
                        return
                    if eh_loja_shopee(link_nicho.loja, link_nicho.url) and (
                        not imagem or eh_logo_shopee(imagem)
                    ):
                        achada = _foto_shopee_api(titulo, preco)
                        if achada:
                            logger.info("[espelho] foto Shopee pela API de afiliado")
                        elif imagem:
                            logger.info("[espelho] miniatura é o logo da Shopee; sem foto")
                        imagem = achada

                garantir_foto()
                pagina = titulo_pagina_visto(link_nicho.url)
                if pagina and filters.titulo_de_vitrine(pagina):
                    logger.info(
                        "[espelho] título da página é da vitrine; mantendo o nome do anúncio"
                    )
                elif pagina and filters.pagina_de_cupom(pagina):
                    logger.info(
                        "[espelho] página é landing de cupom; mantendo o nome do anúncio"
                    )
                confirmado = filters.titulo_confirmado(titulo, pagina)
                if confirmado != titulo:
                    logger.info(
                        f"[espelho] título não bate com o link; usando o nome da página "
                        f"({titulo[:40]!r})"
                    )
                    titulo = confirmado
                if filters.titulo_de_vitrine(titulo):
                    logger.info(f"[espelho] título sem nome de produto {item.id}")
                    _marcar(item, "skipped", "titulo_vitrine")
                    processados += 1
                    continue
                if somente_video or not imagem:
                    motivo = "somente_video" if somente_video else "sem_foto"
                    logger.info(f"[espelho] sem representação ({motivo}) {item.id}")
                    _marcar(item, "skipped", motivo)
                    processados += 1
                    continue
                titulo = enfeitar_titulo(titulo, titulo_grupo)
                if titulo_igual(titulo, titulo_grupo):
                    logger.info(
                        f"[espelho] título igual ao do grupo; oferta não enviada {item.id}"
                    )
                    _marcar(item, "skipped", "titulo_igual")
                    processados += 1
                    continue

                cartao = bool(filtros.get("cartao_so_foto"))
                enviou_algum = False
                falhou_total = True
                teve_foto = False
                for jid in grupos:
                    ok_prod, motivo_prod = pode_enviar_produto(
                        session,
                        sku=sku,
                        loja=link_nicho.loja,
                        grupo=jid,
                        tenant_id=runtime.owner_id,
                        preco=preco,
                        dedup_horas=dedup_horas,
                    )
                    if not ok_prod:
                        logger.info(
                            f"[espelho] produto já enviado no grupo "
                            f"({motivo_prod}) {item.id}"
                        )
                        continue
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
                            sku=sku,
                            imagem=imagem,
                            pagina=pagina,
                        )
                        mensagem = formatter.montar_mensagem(oferta)
                        imagem_envio = imagem
                        teve_foto = True
                        ok_envio = whatsapp.enviar_mensagem(
                            mensagem,
                            imagem=imagem,
                            grupo=jid,
                            previa_imagem=imagem if cartao else None,
                        )
                        oferta_db = monitor._salvar_oferta(  # noqa: SLF001
                            session,
                            OfertaCapturada(
                                nome=titulo[:_NOME_MAX],
                                preco=float(oferta.preco or 0.0),
                                preco_anterior=oferta.preco_anterior,
                                loja=link_nicho.loja,
                                url=url_afiliado,
                                sku=sku[:120],
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
                            "sku": sku,
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
