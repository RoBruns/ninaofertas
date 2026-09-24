"""Canais do bot antigo, usados só pelo seed.

O seed importa config.json/config.auto.json como bots pausados no dashboard;
o worker nunca lê estes arquivos (ADR-020).
"""

from __future__ import annotations

CANAIS = {
    "achadinhos": {
        "arquivo": "config.json",
        "nome": "Achadinhos da Nina",
    },
    "auto": {
        "arquivo": "config.auto.json",
        "nome": "Nina Ofertas",
    },
}
