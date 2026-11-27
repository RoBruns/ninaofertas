"""Normalização de loja do radar (chaves iguais ao pega-oferta)."""

from __future__ import annotations

STORE_KEYS = ("mercadolivre", "shopee", "amazon", "aliexpress", "awin", "outra")

_ALIASES: dict[str, str] = {
    "mercadolivre": "mercadolivre",
    "mercado livre": "mercadolivre",
    "mercado-livre": "mercadolivre",
    "ml": "mercadolivre",
    "meli": "mercadolivre",
    "shopee": "shopee",
    "amazon": "amazon",
    "aliexpress": "aliexpress",
    "ali express": "aliexpress",
    "magalu": "awin",
    "magazine luiza": "awin",
    "magazine você": "awin",
    "magazine voce": "awin",
    "awin": "awin",
    "promobit": "outra",
    "outra": "outra",
}


def normalizar_loja(valor: str | None) -> str:
    raw = (valor or "").strip().lower()
    if not raw:
        return "outra"
    if raw in _ALIASES:
        return _ALIASES[raw]
    for chave, destino in _ALIASES.items():
        if chave in raw:
            return destino
    return "outra"
