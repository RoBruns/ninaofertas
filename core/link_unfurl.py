"""Cartão clicável da Shopee.

A Evolution 2.3.7 monta a prévia com User-Agent googlebot. O link curto
responde 301 para outro host, o Baileys recusa o redirect e o cartão sai sem
foto. Com User-Agent de WhatsApp o mesmo link devolve og:title e og:image.
A página pública repete essas tags para o robô e manda a pessoa para o
link de afiliado.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from core.crypto import _read_key
from core.mirror_webhook import public_api_base_url

_UA_WHATSAPP = "WhatsApp/2.23.20.0 A"
_OG_TITLE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_TITLE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
    re.IGNORECASE,
)
_OG_IMAGE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_IMAGE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.IGNORECASE,
)
_TITLE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
_ROBOS = (
    "googlebot",
    "facebookexternalhit",
    "twitterbot",
    "slackbot",
    "telegrambot",
    "discordbot",
    "linkedinbot",
    "embedly",
    "iframely",
)


@dataclass(frozen=True)
class CartaoLink:
    mensagem: str
    imagem: str
    destino: str


def eh_shopee(loja: str | None) -> bool:
    return "shopee" in (loja or "").lower()


def eh_robo_previa(user_agent: str | None) -> bool:
    ua = (user_agent or "").strip().lower()
    if ua.startswith("whatsapp/"):
        return True
    return any(marca in ua for marca in _ROBOS)


def cartao_da_mensagem(mensagem: str, loja: str | None, url_afiliado: str) -> CartaoLink | None:
    """Troca o link de afiliado pelo cartão, se a Shopee entregou a foto."""
    if not eh_shopee(loja) or url_afiliado not in (mensagem or ""):
        return None
    if not public_api_base_url() or _chave() is None:
        return None
    previa = buscar_og_shopee(url_afiliado)
    if previa is None:
        return None
    titulo, imagem = previa
    publica = url_publica(url_afiliado, titulo, imagem)
    if not publica:
        return None
    return CartaoLink(mensagem.replace(url_afiliado, publica), imagem, url_afiliado)


def buscar_og_shopee(url: str) -> tuple[str, str] | None:
    if not destino_permitido(url):
        return None
    try:
        with httpx.Client(timeout=8.0, follow_redirects=False) as client:
            response = client.get(
                url,
                headers={"User-Agent": _UA_WHATSAPP, "Accept": "text/html"},
            )
    except httpx.HTTPError:
        return None
    if response.status_code >= 400 or response.is_redirect:
        return None
    return _og(response.text[:80_000])


def url_publica(destino: str, titulo: str, imagem: str) -> str | None:
    base = public_api_base_url()
    token = emitir_token(destino, titulo, imagem)
    if not base or not token:
        return None
    return f"{base}/p/{token}"


def emitir_token(destino: str, titulo: str, imagem: str) -> str | None:
    if not destino_permitido(destino) or not imagem_permitida(imagem):
        return None
    titulo_limpo = " ".join((titulo or "").split())[:140]
    if not titulo_limpo:
        return None
    corpo = _b64(
        json.dumps(
            {"u": destino, "t": titulo_limpo, "i": imagem},
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    )
    chave = _chave()
    if chave is None:
        return None
    assinatura = hmac.new(chave, corpo.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{corpo}.{assinatura}"


def ler_token(token: str) -> tuple[str, str, str] | None:
    corpo, ponto, assinatura = (token or "").partition(".")
    chave = _chave()
    if not ponto or not corpo or not assinatura or chave is None:
        return None
    esperada = hmac.new(chave, corpo.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(esperada, assinatura):
        return None
    try:
        dados = json.loads(_b64_decodificar(corpo))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(dados, dict):
        return None
    destino = dados.get("u")
    titulo = dados.get("t")
    imagem = dados.get("i")
    if not isinstance(destino, str) or not isinstance(titulo, str) or not isinstance(imagem, str):
        return None
    if not destino_permitido(destino) or not imagem_permitida(imagem) or not titulo.strip():
        return None
    return destino, titulo[:140], imagem


def html_cartao(titulo: str, imagem: str, destino: str) -> str:
    t = html.escape(titulo, quote=True)
    i = html.escape(imagem, quote=True)
    d = html.escape(destino, quote=True)
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{t}</title>"
        f'<meta property="og:title" content="{t}">'
        '<meta property="og:type" content="website">'
        f'<meta property="og:url" content="{d}">'
        f'<meta property="og:image" content="{i}">'
        f'</head><body><p><a href="{d}">{t}</a></p></body></html>'
    )


def destino_permitido(url: str) -> bool:
    if not url.startswith("https://") or _tem_controle(url) or len(url) > 2000:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host == "shope.ee" or host == "shopee.com.br" or host.endswith(".shopee.com.br")


def imagem_permitida(url: str) -> bool:
    if not url.startswith("https://") or _tem_controle(url) or len(url) > 500:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("susercontent.com") or host.endswith("shopee.com.br")


def _og(html_pagina: str) -> tuple[str, str] | None:
    titulo = _primeiro(_OG_TITLE, html_pagina) or _primeiro(_OG_TITLE_ALT, html_pagina)
    if not titulo:
        titulo = _primeiro(_TITLE, html_pagina)
    imagem = _primeiro(_OG_IMAGE, html_pagina) or _primeiro(_OG_IMAGE_ALT, html_pagina)
    if not titulo or not imagem:
        return None
    imagem = imagem.split("#", 1)[0]
    if not imagem_permitida(imagem):
        return None
    return titulo.strip(), imagem


def _primeiro(regex: re.Pattern[str], texto: str) -> str | None:
    match = regex.search(texto or "")
    if not match:
        return None
    return html.unescape(match.group(1)).strip() or None


def _tem_controle(url: str) -> bool:
    return any(ord(char) < 33 for char in url)


def _chave() -> bytes | None:
    try:
        return _read_key()
    except RuntimeError:
        return None


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode("ascii").rstrip("=")


def _b64_decodificar(dados: str) -> bytes:
    return base64.urlsafe_b64decode(dados + "=" * (-len(dados) % 4))
