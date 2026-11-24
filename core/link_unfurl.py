"""Prévia nativa da Shopee e do Mercado Livre.

O link de afiliado (meli.la ou s.shopee.com.br) já traz a foto. A mensagem
sai em texto, com a prévia do WhatsApp ligada, e o toque na imagem abre a loja.

`/api/p/{token}` só atende links que já saíram com o endereço da prévia:
o robô ainda vê a foto e a pessoa cai no afiliado.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
from urllib.parse import urlparse

from core.crypto import _read_key

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


def eh_shopee(loja: str | None) -> bool:
    return "shopee" in (loja or "").lower()


def eh_mercado_livre(loja: str | None) -> bool:
    return "mercado" in (loja or "").lower()


def loja_com_cartao(loja: str | None) -> bool:
    return eh_shopee(loja) or eh_mercado_livre(loja)


def eh_robo_previa(user_agent: str | None) -> bool:
    ua = (user_agent or "").strip().lower()
    if ua.startswith("whatsapp/"):
        return True
    return any(marca in ua for marca in _ROBOS)


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
    if not _url_https(url) or len(url) > 2000:
        return False
    host = (urlparse(url).hostname or "").lower()
    return (
        host in {
            "shope.ee",
            "meli.la",
            "shopee.com.br",
            "mercadolivre.com.br",
            "mercadolibre.com",
            "mercadolibre.com.br",
        }
        or host.endswith(".shopee.com.br")
        or host.endswith(".meli.la")
        or host.endswith(".mercadolivre.com.br")
        or host.endswith(".mercadolibre.com")
        or host.endswith(".mercadolibre.com.br")
    )


def imagem_permitida(url: str) -> bool:
    if not _url_https(url) or len(url) > 1000:
        return False
    host = (urlparse(url).hostname or "").lower()
    return (
        host.endswith("susercontent.com")
        or host.endswith("shopee.com.br")
        or host.endswith("mlstatic.com")
    )


def _url_https(url: str) -> bool:
    return url.startswith("https://") and not any(ord(char) < 33 for char in url)


def _chave() -> bytes | None:
    try:
        return _read_key()
    except RuntimeError:
        return None


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode("ascii").rstrip("=")


def _b64_decodificar(dados: str) -> bytes:
    return base64.urlsafe_b64decode(dados + "=" * (-len(dados) % 4))
