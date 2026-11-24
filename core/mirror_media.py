"""Foto do espelho: URL pública do produto (CDN), sem baixar/gravar mídia."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger

# Mesma família que worker.whatsapp._MEDIA_URL_PREFIXES — só HTTPS de loja/CDN.
_HOST_OK = (
    "http2.mlstatic.com",
    "http.mlstatic.com",
    "mlstatic.com",
    "cf.shopee.com.br",
    "down-br.img.susercontent.com",
    "susercontent.com",
    "shopee.com.br",
    "mercadolivre.com.br",
    "magazinevoce.com.br",
    "magazineluiza.com.br",
    "images-na.ssl-images-amazon.com",
    "m.media-amazon.com",
)

_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_IMAGE_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.IGNORECASE,
)
_JSON_IMAGE_RE = re.compile(
    r'"image"\s*:\s*"(https://[^"\\]+)"',
    re.IGNORECASE,
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}


def _host_permitido(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return any(host == h or host.endswith("." + h) for h in _HOST_OK)


def _abs_https(base: str, candidate: str) -> str | None:
    raw = (candidate or "").strip()
    if not raw:
        return None
    if raw.startswith("//"):
        raw = "https:" + raw
    if not raw.startswith("http"):
        raw = urljoin(base, raw)
    if not raw.startswith("https://"):
        return None
    return raw.split("#", 1)[0]


def _extrair_og_image(html: str, base_url: str) -> str | None:
    for regex in (_OG_IMAGE_RE, _OG_IMAGE_RE_ALT, _JSON_IMAGE_RE):
        match = regex.search(html or "")
        if not match:
            continue
        abs_url = _abs_https(base_url, match.group(1))
        if abs_url and _host_permitido(abs_url):
            return abs_url
    return None


def imagem_do_link_produto(url: str, loja: str | None = None) -> str | None:
    """Resolve a foto pública do anúncio (CDN). Não grava arquivo nem base64.

    A Evolution recebe só a URL HTTPS e busca a imagem na hora do envio.
    Se a loja bloquear o fetch (captcha/datacenter), devolve None e o espelho
    manda só o texto do template.
    """
    alvo = (url or "").strip()
    if not alvo.startswith("https://"):
        return None
    try:
        with httpx.Client(
            timeout=12.0,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            response = client.get(alvo)
    except httpx.HTTPError as exc:
        logger.info(f"[espelho] sem foto do produto ({loja or '?'}): {exc}")
        return None

    final = str(response.url)
    content_type = (response.headers.get("content-type") or "").lower()
    if content_type.startswith("image/") and _host_permitido(final):
        return final

    if response.status_code >= 400:
        logger.info(
            f"[espelho] sem foto do produto ({loja or '?'}): HTTP {response.status_code}"
        )
        return None

    # Páginas muito grandes: só o começo basta para og:image.
    html = response.text[:120_000]
    foto = _extrair_og_image(html, final)
    if foto:
        return foto
    logger.info(f"[espelho] produto sem og:image utilizável ({loja or '?'})")
    return None
