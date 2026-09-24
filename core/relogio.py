"""Relogio operacional do worker, sempre ancorado no horario de Brasilia."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

BR = ZoneInfo("America/Sao_Paulo")
QUIET_HOURS_PADRAO = {"start": "00:00", "end": "08:00"}


def agora_br() -> datetime:
    return datetime.now(BR)


def agora_banco() -> datetime:
    """Retorna um datetime naive no fuso do processo, como as colunas legadas."""
    return agora_br().astimezone().replace(tzinfo=None)


def inicio_do_dia_banco() -> datetime:
    meia_noite = agora_br().replace(hour=0, minute=0, second=0, microsecond=0)
    return meia_noite.astimezone().replace(tzinfo=None)


def _em_brasilia(quando: datetime | None) -> datetime:
    if quando is None:
        return agora_br()
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return quando.astimezone(BR)


def formatar_hora(quando: datetime | None) -> str:
    return _em_brasilia(quando).strftime("%H:%M")


def _quiet_hours(quiet_hours: Any) -> tuple[str, str]:
    value = quiet_hours or QUIET_HOURS_PADRAO
    if isinstance(value, dict) and "quiet_hours" in value:
        value = value["quiet_hours"]
    if isinstance(value, dict):
        return str(value.get("start", "00:00")), str(value.get("end", "08:00"))
    return str(getattr(value, "start", "00:00")), str(getattr(value, "end", "08:00"))


def _hora(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def em_silencio(quiet_hours: Any, quando: datetime | None = None) -> bool:
    """Informa se `quando` cai na janela de silencio configurada para o bot."""
    start_text, end_text = _quiet_hours(quiet_hours)
    start, end = _hora(start_text), _hora(end_text)
    atual = _em_brasilia(quando).time().replace(tzinfo=None)
    if start == end:
        return False
    if start < end:
        return start <= atual < end
    return atual >= start or atual < end


def pode_enviar(quiet_hours: Any = None, quando: datetime | None = None) -> bool:
    return not em_silencio(quiet_hours, quando)


def fim_do_silencio(quiet_hours: Any, quando: datetime | None = None) -> datetime:
    """Retorna o proximo fim da janela de silencio, em Brasilia."""
    _start_text, end_text = _quiet_hours(quiet_hours)
    agora = _em_brasilia(quando)
    end = _hora(end_text)
    candidato = agora.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if candidato <= agora:
        candidato += timedelta(days=1)
    return candidato
