"""Limites de dias locais, preservando filtros com instante completo."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def date_boundary(value: date | datetime, *, end: bool = False) -> datetime:
    if isinstance(value, datetime):
        return value
    day = value + timedelta(days=1) if end else value
    return datetime.combine(day, time.min, SAO_PAULO)
