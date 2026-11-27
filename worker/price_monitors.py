"""Job periódico: checa monitores de preço ativos (MVP HTML/og)."""

from __future__ import annotations

import re
from decimal import Decimal

import httpx
from sqlalchemy import select

from core import db, relogio
from core.models import PriceMonitor
from worker.logger import logger

_UA = "NinaBot-PriceMonitor/1.0"


def _parse_html(html: str) -> tuple[str | None, str | None, Decimal | None]:
    title = image = None
    price: Decimal | None = None
    if m := re.search(r'property="og:title"\s+content="([^"]+)"', html, re.I):
        title = m.group(1).strip()[:200]
    if m := re.search(r'property="og:image"\s+content="([^"]+)"', html, re.I):
        image = m.group(1).strip()[:500]
    if m := re.search(
        r'(?:R\$\s*|\"price\"\s*:\s*\"?)(\d{1,3}(?:\.\d{3})*,\d{2}|\d+(?:[.,]\d{2})?)',
        html,
    ):
        raw = m.group(1).replace(".", "").replace(",", ".")
        try:
            price = Decimal(raw)
        except Exception:
            price = None
    return title, image, price


def checar_um(row: PriceMonitor) -> None:
    title, image, price = row.title, row.image_url, row.last_price
    try:
        with httpx.Client(timeout=12.0, follow_redirects=True) as client:
            resp = client.get(row.url, headers={"User-Agent": _UA})
        t, i, p = _parse_html(resp.text[:400_000])
        title = t or title
        image = i or image
        if p is not None:
            price = p
    except Exception as exc:
        logger.debug(f"[monitor] falha ao checar {row.id}: {exc}")
    row.title = title
    row.image_url = image
    row.last_price = price
    row.last_checked_at = relogio.agora_banco()
    if price is not None and price <= row.target_price:
        row.status = "alvo_atingido"
    row.updated_at = relogio.agora_banco()


def ciclo() -> int:
    """Checa até 20 monitores em status monitorando. Retorna quantos rodou."""
    with db.get_session() as session:
        rows = session.scalars(
            select(PriceMonitor)
            .where(PriceMonitor.status == "monitorando")
            .order_by(PriceMonitor.last_checked_at.asc().nullsfirst())
            .limit(20)
        ).all()
        for row in rows:
            checar_um(row)
        n = len(rows)
        if n:
            logger.info(f"[monitor] checados {n} monitor(es) de preço")
        return n
