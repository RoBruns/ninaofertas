"""Horário de Brasília. A VPS costuma estar em UTC; o dia e o silêncio noturno não."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BR = ZoneInfo("America/Sao_Paulo")

HORA_INICIO_PADRAO = 8
HORA_FIM_PADRAO = 0


def agora_br() -> datetime:
    return datetime.now(BR)


def agora_banco() -> datetime:
    """Naive no fuso do processo, igual ao que as colunas DateTime já gravam."""
    return agora_br().astimezone().replace(tzinfo=None)


def inicio_do_dia_banco() -> datetime:
    meia_noite = agora_br().replace(hour=0, minute=0, second=0, microsecond=0)
    return meia_noite.astimezone().replace(tzinfo=None)


def formatar_hora(quando: datetime | None) -> str:
    if quando is None:
        return agora_br().strftime("%H:%M")
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return quando.astimezone(BR).strftime("%H:%M")


def pode_enviar(filtros: dict | None = None, quando: datetime | None = None) -> bool:
    """Ligado das 08h até 00h. Entre meia-noite e 08h fica em silêncio."""
    filtros = filtros or {}
    inicio = int(filtros.get("envio_hora_inicio", HORA_INICIO_PADRAO))
    fim = int(filtros.get("envio_hora_fim", HORA_FIM_PADRAO))
    hora = (quando or agora_br()).hour
    if inicio == fim:
        return True
    if inicio < fim:
        return inicio <= hora < fim
    return hora >= inicio or hora < fim


def proximo_inicio(filtros: dict | None = None, quando: datetime | None = None) -> datetime:
    filtros = filtros or {}
    inicio = int(filtros.get("envio_hora_inicio", HORA_INICIO_PADRAO))
    agora = quando or agora_br()
    candidato = agora.replace(hour=inicio, minute=0, second=0, microsecond=0)
    if candidato <= agora:
        candidato += timedelta(days=1)
    return candidato
