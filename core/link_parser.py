"""Extrai e classifica links de oferta a partir de texto de WhatsApp."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

_URL_RE = re.compile(
    r"https?://[^\s<>\"'\)\]]+",
    re.IGNORECASE,
)

_HOST_LOJA: tuple[tuple[tuple[str, ...], str], ...] = (
    (("mercadolivre.com", "mercadolivre.com.br", "meli.la", "mercadolibre.com"), "mercado livre"),
    (("shopee.com.br", "shopee.com", "s.shopee.com.br", "shp.ee"), "shopee"),
    (("magazinevoce.com.br", "magazineluiza.com.br", "magalu.com.br"), "magalu"),
    (("amazon.com.br", "amzn.to"), "amazon"),
)


@dataclass(frozen=True)
class LinkOferta:
    url: str
    loja: str


def _limpar_url(raw: str) -> str:
    return raw.rstrip(".,;:!?)】》\"'")


def detectar_loja(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for hosts, loja in _HOST_LOJA:
        if any(host == h or host.endswith("." + h) for h in hosts):
            return loja
    return None


def extrair_links_oferta(texto: str) -> list[LinkOferta]:
    """URLs de marketplace no texto, na ordem de aparição, sem duplicar."""
    vistos: set[str] = set()
    out: list[LinkOferta] = []
    for match in _URL_RE.finditer(texto or ""):
        url = _limpar_url(match.group(0))
        if url in vistos:
            continue
        loja = detectar_loja(url)
        if not loja:
            continue
        vistos.add(url)
        out.append(LinkOferta(url=url, loja=loja))
    return out


_LOJA_PARA_SLUG = {
    "mercado livre": "mercadolivre",
    "shopee": "shopee",
    "amazon": "amazon",
    "magalu": "magalu",
}


def loja_para_platform_slug(loja: str) -> str | None:
    return _LOJA_PARA_SLUG.get((loja or "").lower())


def substituir_urls(texto: str, mapa: dict[str, str]) -> str:
    """Troca URLs no texto; chaves devem ser exatamente as extraídas."""
    if not mapa:
        return texto
    resultado = texto
    # Mais longas primeiro evita prefixos parciais.
    for origem in sorted(mapa.keys(), key=len, reverse=True):
        destino = mapa[origem]
        if origem and destino and origem != destino:
            resultado = resultado.replace(origem, destino)
    return resultado
