"""Identidade estável do produto no espelho (não o link curto de cada grupo)."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

import httpx

from core.platforms.amazon import asin_amazon
from core.platforms.affiliate import resolver_url_produto_ml

_RE_NAO_ALNUM = re.compile(r"[^a-z0-9]+")

_MLB_RE = re.compile(r"MLB-?(\d+)", re.IGNORECASE)
_SHOPEE_PRODUCT_RE = re.compile(
    r"(?:/product/(\d+)/(\d+)|-i\.(\d+)\.(\d+))",
    re.IGNORECASE,
)
_MAGALU_RE = re.compile(r"/p/([a-z0-9]+)/?", re.IGNORECASE)
_CACHE_EXPAND: dict[str, str | None] = {}


def _expandir_url(url: str) -> str:
    alvo = (url or "").strip()
    if not alvo.startswith("http"):
        return alvo
    if alvo in _CACHE_EXPAND:
        return _CACHE_EXPAND[alvo] or alvo
    try:
        with httpx.Client(
            timeout=12.0,
            follow_redirects=True,
            headers={"user-agent": "WhatsApp/2.23.20.0 A"},
        ) as client:
            response = client.get(alvo)
        final = str(response.url)
    except httpx.HTTPError:
        _CACHE_EXPAND[alvo] = None
        return alvo
    _CACHE_EXPAND[alvo] = final
    return final


def _mlb(url: str) -> str | None:
    match = _MLB_RE.search(url or "")
    if match is None:
        return None
    return f"ml:MLB{match.group(1)}"


def _shopee(url: str) -> str | None:
    match = _SHOPEE_PRODUCT_RE.search(urlparse(url or "").path or "")
    if match is None:
        return None
    shop = match.group(1) or match.group(3)
    item = match.group(2) or match.group(4)
    if not shop or not item:
        return None
    return f"shopee:{shop}.{item}"


def _magalu(url: str) -> str | None:
    host = (urlparse(url or "").hostname or "").lower().removeprefix("www.")
    if not (
        host.endswith("magazineluiza.com.br")
        or host.endswith("magazinevoce.com.br")
    ):
        return None
    match = _MAGALU_RE.search(urlparse(url).path or "")
    if match is None:
        return None
    return f"magalu:{match.group(1).lower()}"


def _amazon(url: str) -> str | None:
    asin = asin_amazon(url)
    if asin:
        return f"amz:{asin}"
    host = (urlparse(url or "").hostname or "").lower()
    if "amzn.to" in host or host.endswith("amazon.com.br"):
        return None
    return None


def chave_produto(
    url: str,
    *,
    loja: str | None = None,
    titulo: str | None = None,
) -> str | None:
    """Chave canônica do item, ou fallback título+loja se a URL não resolver."""
    bruto = (url or "").strip()
    if not bruto:
        return _fallback(titulo, loja)

    loja_l = (loja or "").lower()
    candidatos = [bruto]
    host = (urlparse(bruto).hostname or "").lower()
    precisa = any(
        marca in host
        for marca in ("meli.la", "s.shopee", "shp.ee", "shope.ee", "amzn.to")
    )
    if precisa or "mercado" in loja_l:
        if "mercado" in loja_l or "meli.la" in host or "mercadolivre" in host:
            pdp = resolver_url_produto_ml(bruto)
            if pdp:
                candidatos.append(pdp)
        else:
            candidatos.append(_expandir_url(bruto))

    for candidato in candidatos:
        host_c = (urlparse(candidato).hostname or "").lower()
        if "mercado" in loja_l or "meli" in host_c or _MLB_RE.search(candidato):
            chave = _mlb(candidato)
            if chave:
                return chave
        if "shopee" in loja_l or "shopee" in host_c:
            chave = _shopee(candidato)
            if chave:
                return chave
        if "magalu" in loja_l or "magazine" in loja_l:
            chave = _magalu(candidato)
            if chave:
                return chave
        if "amazon" in loja_l or "amzn" in host_c:
            if "amzn.to" in host_c:
                expandido = _expandir_url(candidato)
            else:
                expandido = candidato
            chave = _amazon(expandido)
            if chave:
                return chave

        chave = (
            _mlb(candidato)
            or _shopee(candidato)
            or _magalu(candidato)
            or _amazon(candidato)
        )
        if chave:
            return chave

    return _fallback(titulo, loja)


def _nome_simples(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower().strip()
    return re.sub(r"\s+", " ", _RE_NAO_ALNUM.sub(" ", s)).strip()


def _fallback(titulo: str | None, loja: str | None) -> str | None:
    nome = _nome_simples(titulo or "")
    if len(nome) < 8:
        return None
    loja_n = _nome_simples(loja or "loja") or "loja"
    return f"nome:{loja_n}:{nome}"[:120]
