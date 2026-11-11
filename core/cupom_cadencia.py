"""Cadência de cupom de venda indireta (intervalo configurável no dashboard)."""

from __future__ import annotations

from typing import Any, Mapping

# Padrão: a cada 1h30; cupom novo (nunca enviado) pode sair na hora.
INTERVALO_CUPOM_PADRAO_MINUTOS = 90
INTERVALO_CUPOM_MINIMO_MINUTOS = 15


def intervalo_cupom_minutos(filtros: Mapping[str, Any] | None = None) -> int:
    """Lê content.intervalo_cupom_minutos (achatado em load_filtros) ou o padrão."""
    raw = (filtros or {}).get("intervalo_cupom_minutos", INTERVALO_CUPOM_PADRAO_MINUTOS)
    try:
        valor = int(raw)
    except (TypeError, ValueError):
        return INTERVALO_CUPOM_PADRAO_MINUTOS
    return max(INTERVALO_CUPOM_MINIMO_MINUTOS, valor)


# Compatibilidade com imports antigos.
INTERVALO_CUPOM_MINUTOS = INTERVALO_CUPOM_PADRAO_MINUTOS
