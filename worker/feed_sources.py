"""Job: coleta fontes habilitadas (Promobit/RSS) → mirror_inbox."""

from __future__ import annotations

from sqlalchemy import select

from core import db
from core.feed_collect import coletar_fonte, ensure_feed_sources
from core.models import FeedSource, Tenant
from worker.logger import logger


def ciclo() -> dict[str, int]:
    """Varre tenants com fonte ligada. Retorna totais."""
    lidas = novas = fontes = 0
    with db.get_session() as session:
        tenants = session.scalars(select(Tenant).where(Tenant.status == "active")).all()
        for tenant in tenants:
            ensure_feed_sources(session, tenant.id)
            rows = session.scalars(
                select(FeedSource).where(
                    FeedSource.owner_id == tenant.id,
                    FeedSource.enabled.is_(True),
                )
            ).all()
            for source in rows:
                fontes += 1
                result = coletar_fonte(session, source)
                lidas += int(result.get("lidas") or 0)
                novas += int(result.get("novas") or 0)
        if fontes:
            logger.info(
                f"[fontes] ciclo: {fontes} fonte(s), {lidas} lida(s), "
                f"{novas} item(ns) na esteira"
            )
    return {"fontes": fontes, "lidas": lidas, "novas": novas}
