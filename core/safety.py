"""Limites imutaveis que protegem os numeros de WhatsApp contra banimento."""

from __future__ import annotations

from typing import Any

MAX_PACING: dict[str, int] = {
    "max_ofertas_por_hora": 15,
    "max_ofertas_por_dia": 120,
    "max_ofertas_globais_por_hora": 20,
    "max_ofertas_globais_por_dia": 150,
    "max_ofertas_por_ciclo": 3,
    "max_ofertas_por_rajada": 5,
}
MIN_PACING: dict[str, int] = {"intervalo_minutos_entre_ofertas": 2}
# Tetos diários que aceitam 0 como "desligado". Os de hora/intervalo/rajada, não.
OPTIONAL_DAILY_CAPS = frozenset({"max_ofertas_por_dia", "max_ofertas_globais_por_dia"})


def validate_safe_pacing(values: dict[str, Any]) -> dict[str, Any]:
    """Recusa configuracoes que podem queimar o chip e fazer perder os grupos."""
    for field, ceiling in MAX_PACING.items():
        value = values.get(field)
        # 0 desliga os tetos diários (ADR-018); só valor positivo é comparado ao teto.
        if field in OPTIONAL_DAILY_CAPS and value == 0:
            continue
        if value is not None and value > ceiling:
            raise ValueError(
                f"{field} deve ser <= {ceiling}: ultrapassar este teto aumenta o risco de "
                "banimento do WhatsApp e de perda do chip e dos grupos"
            )
    for field, floor in MIN_PACING.items():
        value = values.get(field)
        if value is not None and value < floor:
            raise ValueError(
                f"{field} deve ser >= {floor}: reduzir este intervalo aumenta o risco de "
                "banimento do WhatsApp e de perda do chip e dos grupos"
            )
    return values
