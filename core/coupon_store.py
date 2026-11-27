"""Normalização de loja do radar (chaves iguais ao pega-oferta)."""

from __future__ import annotations

import re

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


def loja_da_mensagem(texto: str | None) -> str:
    """Loja do cupom: pelo link de marketplace e, sem link, pelo texto."""
    from core.link_parser import extrair_links_oferta

    links = extrair_links_oferta(texto or "")
    if links:
        return normalizar_loja(links[0].loja)
    t = (texto or "").lower()
    if "amazon" in t or "amzn" in t:
        return "amazon"
    if "mercado livre" in t or "mercadolivre" in t or "meli" in t or re.search(r"\bml\b", t):
        return "mercadolivre"
    if "shopee" in t or "shope.ee" in t:
        return "shopee"
    if "aliexpress" in t:
        return "aliexpress"
    if "magalu" in t or "magazine" in t:
        return "awin"
    return "outra"


def resumo_da_mensagem(texto: str | None, limite: int = 80) -> str:
    sem_urls = re.sub(r"https?://\S+", " ", texto or "")
    return " ".join(sem_urls.replace("*", " ").replace("~", " ").split())[:limite]
