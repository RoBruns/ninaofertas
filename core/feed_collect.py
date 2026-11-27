"""Coleta Promobit/RSS → catálogo (ofertas) + esteira (mirror_inbox) se der."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from typing import Any
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.coupon_radar import registrar_cupom
from core.feed_catalog import DEFAULT_FEED_SOURCES
from core.link_parser import detectar_loja, extrair_links_oferta
from core.models import Bot, FeedSource, MirrorInbox, Oferta
from core import relogio
from worker import filters

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_MARKETPLACE_HINT = re.compile(
    r"https?://(?:\S+\.)?(?:mercadolivre|meli\.la|shopee|amazon|magalu|"
    r"magazinevoce|amzn\.to|shp\.ee)[^\s\"'<>]*",
    re.I,
)


@dataclass
class CollectedOffer:
    external_id: str
    title: str
    url: str
    price: float | None = None
    price_old: float | None = None
    coupon: str | None = None
    store_label: str | None = None
    image: str | None = None
    sendable: bool = False  # tem URL de marketplace → pode ir à esteira


def ensure_feed_sources(session: Session, owner_id: UUID) -> list[FeedSource]:
    """Garante o catálogo padrão no tenant (idempotente)."""
    existing = {
        row.slug: row
        for row in session.scalars(select(FeedSource).where(FeedSource.owner_id == owner_id)).all()
    }
    agora = datetime.now(timezone.utc)
    for item in DEFAULT_FEED_SOURCES:
        if item.slug in existing:
            continue
        row = FeedSource(
            id=uuid4(),
            owner_id=owner_id,
            slug=item.slug,
            name=item.name,
            kind=item.kind,
            url=item.url,
            enabled=item.default_enabled,
            created_at=agora,
            updated_at=agora,
        )
        session.add(row)
        existing[item.slug] = row
    session.flush()
    return list(existing.values())


def _montar_body(offer: CollectedOffer, origem: str) -> str:
    linhas = [offer.title.strip()[:200]]
    if offer.price_old and offer.price and offer.price_old > offer.price:
        linhas.append(f"De R$ {offer.price_old:.2f} por R$ {offer.price:.2f}".replace(".", ","))
    elif offer.price and offer.price >= 1:
        linhas.append(f"Por R$ {offer.price:.2f}".replace(".", ","))
    if offer.coupon:
        linhas.append(f"Cupom: {offer.coupon}")
    linhas.append(offer.url.strip())
    if offer.store_label:
        linhas.append(f"({origem} · {offer.store_label})")
    else:
        linhas.append(f"({origem})")
    return "\n".join(linhas)


def _vale_no_catalogo(offer: CollectedOffer) -> bool:
    """Preço real + imagem. Sem isso vira card lixo (R$ 0 / foto vazia)."""
    return bool(
        offer.price is not None
        and offer.price >= 1
        and offer.image
        and str(offer.image).startswith("http")
    )


def _persistir_oferta(session: Session, *, source: FeedSource, offer: CollectedOffer) -> bool:
    """Grava no catálogo. True se inseriu."""
    if not _vale_no_catalogo(offer):
        return False
    existente = session.scalar(select(Oferta.id).where(Oferta.url == offer.url).limit(1))
    if existente is not None:
        return False
    sku = f"feed:{source.slug}:{offer.external_id}"[:120]
    loja = detectar_loja(offer.url) or (offer.store_label or source.name)
    assert offer.price is not None
    session.add(
        Oferta(
            nome=offer.title[:200],
            preco=float(offer.price),
            preco_anterior=float(offer.price_old) if offer.price_old else None,
            desconto=None,
            loja=str(loja)[:80] if loja else source.name,
            categoria="fonte",
            url=offer.url[:500],
            imagem=(offer.image or None),
            sku=sku,
            capturado_em=relogio.agora_banco(),
        )
    )
    return True


def _bots_prontos(session: Session, owner_id: UUID) -> list[Bot]:
    return list(
        session.scalars(
            select(Bot).where(
                Bot.owner_id == owner_id,
                Bot.status == "active",
                Bot.archived_at.is_(None),
                Bot.phone_id.is_not(None),
            )
        ).all()
    )


def _enfileirar_para_bots(
    session: Session,
    *,
    owner_id: UUID,
    source: FeedSource,
    offer: CollectedOffer,
    bots: list[Bot],
) -> int:
    """Insere pending no mirror_inbox. Só com link de marketplace."""
    if not offer.sendable or not bots:
        return 0
    body = _montar_body(offer, source.name)
    if not extrair_links_oferta(body):
        return 0
    message_key = f"feed:{source.slug}:{offer.external_id}"[:400]
    source_wa = f"feed:{source.slug}"
    aceitos = 0
    agora = datetime.now(timezone.utc)
    for bot in bots:
        assert bot.phone_id is not None
        stmt = (
            insert(MirrorInbox)
            .values(
                id=uuid4(),
                owner_id=owner_id,
                bot_id=bot.id,
                capture_id=None,
                listen_phone_id=bot.phone_id,
                source_whatsapp_id=source_wa,
                source_group_name=source.name,
                message_key=message_key,
                body_text=body[:4000],
                has_media=False,
                media_path=None,
                status="pending",
                created_at=agora,
            )
            .on_conflict_do_nothing(constraint="uq_mirror_inbox_bot_key")
        )
        result = session.execute(stmt)
        if result.rowcount:
            aceitos += 1
    return aceitos


def _http_get(url: str, *, timeout: float = 12.0) -> str:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(
            url,
            headers={
                "User-Agent": _UA,
                "Accept-Language": "pt-BR,pt;q=0.9",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        resp.raise_for_status()
        return resp.text


def _resolver_link_marketplace(page_url: str, html: str | None = None) -> str | None:
    texto = html or ""
    if not texto and page_url:
        try:
            texto = _http_get(page_url, timeout=10.0)
        except Exception:
            return None
    links = extrair_links_oferta(texto)
    if links:
        return links[0].url
    match = _MARKETPLACE_HINT.search(texto)
    if not match:
        return None
    url = match.group(0).rstrip(".,;:!?)\"'")
    # evita lixo tipo https://link.amazon sem path
    if url.rstrip("/").endswith(("amazon", "amazon.com", "amazon.com.br", "link.amazon")):
        return None
    return url if detectar_loja(url) else None


def coletar_promobit(source: FeedSource) -> tuple[list[CollectedOffer], list[tuple[str, str]]]:
    """Retorna (ofertas, cupons_radar[(code, store)])."""
    html = _http_get(source.url or "https://www.promobit.com.br/")
    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    )
    if not match:
        raise RuntimeError("Promobit: __NEXT_DATA__ não encontrado")
    data = json.loads(match.group(1))
    pp = (data.get("props") or {}).get("pageProps") or {}
    brutas: list[dict[str, Any]] = []
    server = pp.get("serverOffers") or {}
    if isinstance(server, dict):
        brutas.extend(server.get("offers") or [])
    brutas.extend(pp.get("serverFeaturedOffers") or [])
    vistas: set[int] = set()
    out: list[CollectedOffer] = []
    for raw in brutas:
        oid = raw.get("offerId")
        title = (raw.get("offerTitle") or "").strip()
        if not oid or not title or oid in vistas:
            continue
        vistas.add(int(oid))
        slug = (raw.get("offerSlug") or "").strip()
        page = (
            f"https://www.promobit.com.br/oferta/{slug}/"
            if slug
            else "https://www.promobit.com.br/"
        )
        store_url = None
        try:
            # só tenta resolver páginas de produto (evita 16 GETs lentos em cupom)
            if (raw.get("offerPriceType") or "").upper() != "COUPON":
                store_url = _resolver_link_marketplace(page)
        except Exception:
            store_url = None
        cupom = (raw.get("offerCoupon") or "").strip().upper() or None
        if cupom and len(cupom) < 3:
            cupom = None
        price = float(raw["offerPrice"]) if raw.get("offerPrice") is not None else None
        old = float(raw["offerOldPrice"]) if raw.get("offerOldPrice") is not None else None
        photo = raw.get("offerPhoto") or ""
        image = (
            photo
            if isinstance(photo, str) and photo.startswith("http")
            else (f"https://i.promobit.com.br{photo}" if photo else None)
        )
        out.append(
            CollectedOffer(
                external_id=str(oid),
                title=title[:140],
                url=store_url or page,
                price=price if price and price >= 1 else None,
                price_old=old if old and price and old > price else None,
                coupon=cupom,
                store_label=(raw.get("storeName") or None),
                image=image,
                sendable=bool(store_url and detectar_loja(store_url)),
            )
        )
        if len(out) >= 20:
            break

    cupons: list[tuple[str, str]] = []
    for raw in (
        *(pp.get("serverCoupons") or []),
        *(pp.get("coupons") or []),
        *(pp.get("initialCoupons") or []),
    ):
        code = (raw.get("couponCode") or "").strip().upper()
        if len(code) < 3:
            continue
        store = (raw.get("storeName") or raw.get("storeDomain") or "Promobit").strip()
        cupons.append((code, store))
    return out, cupons


def _limpar_html(texto: str) -> str:
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    return unescape(re.sub(r"\s+", " ", texto)).strip()


_IMG_SRC_RE = re.compile(
    r'<img[^>]+src=["\'](https?://[^"\']+)["\']',
    re.I,
)


def _rss_image(item: ET.Element, desc_html: str) -> str | None:
    enc = item.find("enclosure")
    if enc is not None:
        url = (enc.get("url") or "").strip()
        tipo = (enc.get("type") or "").lower()
        if url.startswith("http") and (tipo.startswith("image") or url.lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp", ".gif")
        )):
            return url
    for child in item.iter():
        tag = child.tag.lower() if isinstance(child.tag, str) else ""
        if tag.endswith("content") or tag.endswith("thumbnail"):
            url = (child.get("url") or child.get("href") or "").strip()
            if url.startswith("http"):
                medium = (child.get("medium") or "").lower()
                tipo = (child.get("type") or "").lower()
                if medium in ("", "image") or tipo.startswith("image") or "thumbnail" in tag:
                    return url
    match = _IMG_SRC_RE.search(desc_html or "")
    if match:
        return match.group(1)
    return None


def coletar_rss(source: FeedSource) -> list[CollectedOffer]:
    xml = _http_get(source.url)
    xml = re.sub(r'xmlns="[^"]+"', "", xml)
    root = ET.fromstring(xml)
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    out: list[CollectedOffer] = []
    for item in items[:15]:
        title_el = item.find("title")
        title = _limpar_html(title_el.text if title_el is not None else "")
        link = ""
        link_el = item.find("link")
        if link_el is not None:
            link = (link_el.text or link_el.get("href") or "").strip()
        if not link:
            for child in item:
                if child.tag.endswith("link") and child.get("href"):
                    link = child.get("href", "").strip()
                    break
        desc_el = item.find("description")
        if desc_el is None:
            desc_el = item.find("summary")
        if desc_el is None:
            desc_el = item.find("content")
        desc_html = ""
        if desc_el is not None:
            desc_html = "".join(desc_el.itertext()) if list(desc_el) else (desc_el.text or "")
            if not desc_html and desc_el.text:
                desc_html = desc_el.text
        desc = _limpar_html(desc_html)
        if not title or not link:
            continue
        blob = f"{title}\n{desc}\n{link}"
        store = None
        links = extrair_links_oferta(blob)
        if links:
            store = links[0].url
        else:
            store = _resolver_link_marketplace(link)
        final_url = store or link
        preco, antigo = filters.extrair_precos_mensagem(blob)
        cupom = filters.extrair_cupom_mensagem(blob)
        image = _rss_image(item, desc_html)
        guid_el = item.find("guid")
        external = (guid_el.text if guid_el is not None and guid_el.text else final_url)[:180]
        out.append(
            CollectedOffer(
                external_id=external,
                title=title[:140],
                url=final_url,
                price=float(preco) if preco and preco >= 1 else None,
                price_old=float(antigo) if antigo and preco and antigo > preco else None,
                coupon=cupom,
                store_label=None,
                image=image,
                sendable=bool(store and detectar_loja(store)),
            )
        )
    return out


def coletar_fonte(session: Session, source: FeedSource) -> dict[str, int | str]:
    """Coleta, grava no catálogo e enfileira o que for enviável."""
    lidas = catalogadas = enfileiradas = cupons = 0
    try:
        cupom_lista: list[tuple[str, str]] = []
        if source.kind == "promobit":
            offers, cupom_lista = coletar_promobit(source)
        elif source.kind == "rss":
            offers = coletar_rss(source)
        else:
            raise RuntimeError(f"Tipo de fonte não suportado: {source.kind}")
        lidas = len(offers)
        bots = _bots_prontos(session, source.owner_id)
        for offer in offers:
            if _persistir_oferta(session, source=source, offer=offer):
                catalogadas += 1
            if offer.coupon:
                registrar_cupom(
                    session,
                    owner_id=source.owner_id,
                    code=offer.coupon,
                    source_group_name=source.name,
                    store=offer.store_label,
                    url=offer.url,
                    title=offer.title[:120],
                )
                cupons += 1
            enfileiradas += _enfileirar_para_bots(
                session,
                owner_id=source.owner_id,
                source=source,
                offer=offer,
                bots=bots,
            )
        for code, store in cupom_lista[:40]:
            registrar_cupom(
                session,
                owner_id=source.owner_id,
                code=code,
                source_group_name=source.name,
                store=store,
                title=f"Cupom {store}",
            )
            cupons += 1

        aviso = None
        if not bots:
            aviso = "sem bot ativo com telefone — catálogo atualizado, esteira vazia"
        elif enfileiradas == 0 and catalogadas:
            aviso = "ofertas no catálogo; nenhuma com link de loja resolvido para a esteira"
        source.last_error = aviso
        source.last_collected_at = datetime.now(timezone.utc)
        source.total_collected = int(source.total_collected or 0) + catalogadas
        source.updated_at = datetime.now(timezone.utc)
        result: dict[str, int | str] = {
            "lidas": lidas,
            "catalogadas": catalogadas,
            "enfileiradas": enfileiradas,
            "cupons": cupons,
            "novas": enfileiradas,  # compat toast antigo
        }
        if aviso:
            result["aviso"] = aviso
        return result
    except Exception as exc:
        source.last_error = str(exc)[:400]
        source.last_collected_at = datetime.now(timezone.utc)
        source.updated_at = datetime.now(timezone.utc)
        logger.warning(f"[fontes] {source.slug}: {exc}")
        return {"lidas": lidas, "catalogadas": 0, "enfileiradas": 0, "novas": 0, "erro": str(exc)[:200]}
