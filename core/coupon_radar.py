"""Persistência de cupons no radar (Nina V3 / parity pega-oferta)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.coupon_store import normalizar_loja
from core.models import CouponRadar


def registrar_cupom(
    session: Session,
    *,
    owner_id: UUID,
    code: str,
    source_group_name: str | None = None,
    store: str | None = None,
    url: str | None = None,
    title: str | None = None,
    min_value: Decimal | float | int | None = None,
    validity: str | None = None,
) -> CouponRadar | None:
    """Cria/atualiza cupom ativo no radar. Retorna None se código vazio."""
    codigo = (code or "").strip().upper()
    if len(codigo) < 2:
        return None
    loja = normalizar_loja(store)
    existente = session.scalar(
        select(CouponRadar).where(
            CouponRadar.owner_id == owner_id,
            CouponRadar.code == codigo,
            CouponRadar.status == "ativo",
        )
    )
    agora = datetime.now(timezone.utc)
    if existente is not None:
        if source_group_name and not existente.source_group_name:
            existente.source_group_name = source_group_name
        if url and not existente.url:
            existente.url = url
        if title and not existente.title:
            existente.title = title
        if loja != "outra" and (not existente.store or existente.store == "outra"):
            existente.store = loja
        if validity and not existente.validity:
            existente.validity = validity
        existente.updated_at = agora
        return existente
    minimo = Decimal(str(min_value or 0))
    row = CouponRadar(
        id=uuid4(),
        owner_id=owner_id,
        code=codigo,
        store=loja,
        title=title,
        url=url,
        status="ativo",
        source_group_name=source_group_name,
        notes=None,
        min_value=minimo,
        validity=validity or "Até acabar a verba",
        report_count=0,
        created_at=agora,
        updated_at=agora,
    )
    session.add(row)
    return row
