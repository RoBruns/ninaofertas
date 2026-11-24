"""Foto do espelho: preview/base64 do webhook, getBase64 Evolution, ou CDN."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger

from core.evolution import EvolutionClient, EvolutionUnavailable

_HOST_OK = (
    "http2.mlstatic.com",
    "http.mlstatic.com",
    "mlstatic.com",
    "cf.shopee.com.br",
    "down-br.img.susercontent.com",
    "down-bs.img.susercontent.com",
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
_DATA_URL_RE = re.compile(r"^data:image/[^;]+;base64,(.+)$", re.I | re.S)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}


def _unwrap_message(message: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return None
    for wrap_key in (
        "ephemeralMessage",
        "viewOnceMessage",
        "viewOnceMessageV2",
        "documentWithCaptionMessage",
    ):
        wrapped = message.get(wrap_key)
        if isinstance(wrapped, dict):
            inner = wrapped.get("message")
            if isinstance(inner, dict):
                return _unwrap_message(inner)
    return message


def mensagem_tem_imagem(message: dict[str, Any] | None) -> bool:
    msg = _unwrap_message(message)
    return isinstance(msg, dict) and isinstance(msg.get("imageMessage"), dict)


def _normalizar_base64(raw: str) -> str | None:
    texto = (raw or "").strip()
    match = _DATA_URL_RE.match(texto)
    if match:
        texto = match.group(1)
    # WhatsApp às vezes manda com prefixo "data:..." incompleto ou espaços.
    if "base64," in texto:
        texto = texto.split("base64,", 1)[1]
    texto = "".join(texto.split())
    if len(texto) < 32:
        return None
    return texto


def data_url_jpeg(raw: str) -> str | None:
    b64 = _normalizar_base64(raw)
    if not b64:
        return None
    return f"data:image/jpeg;base64,{b64}"


def midia_do_payload_webhook(message: dict[str, Any] | None) -> str | None:
    """Extrai foto do upsert: base64 completo (webhookBase64) ou jpegThumbnail.

    Devolve data-URL para guardar em `media_path` (texto na fila — sem arquivo).
    """
    msg = _unwrap_message(message)
    if not isinstance(msg, dict):
        return None
    image = msg.get("imageMessage")
    if not isinstance(image, dict):
        return None
    # Preferência: mídia completa quando a Evolution manda webhookBase64.
    for key in ("base64", "media"):
        raw = image.get(key)
        if isinstance(raw, str) and len(raw) > 64:
            url = data_url_jpeg(raw)
            if url:
                return url
    raw_msg = msg.get("base64")
    if isinstance(raw_msg, str) and len(raw_msg) > 64:
        url = data_url_jpeg(raw_msg)
        if url:
            return url
    # Sempre presente em imageMessage do Baileys — qualidade menor, mas funciona.
    thumb = image.get("jpegThumbnail")
    if isinstance(thumb, str) and len(thumb) > 32:
        return data_url_jpeg(thumb)
    return None


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
    """URL pública do anúncio (CDN). Último recurso."""
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
        logger.info(f"[espelho] sem foto CDN ({loja or '?'}): {exc}")
        return None

    final = str(response.url)
    content_type = (response.headers.get("content-type") or "").lower()
    if content_type.startswith("image/") and _host_permitido(final):
        return final
    if response.status_code >= 400:
        logger.info(f"[espelho] sem foto CDN ({loja or '?'}): HTTP {response.status_code}")
        return None
    foto = _extrair_og_image(response.text[:120_000], final)
    if foto:
        return foto
    logger.info(f"[espelho] produto sem og:image utilizável ({loja or '?'})")
    return None


def partir_message_key(message_key: str) -> tuple[str, str] | None:
    remote, sep, msg_id = (message_key or "").rpartition(":")
    if not sep or not remote or not msg_id:
        return None
    return remote, msg_id


def midia_whatsapp_em_memoria(instance: str, message_key: str) -> str | None:
    """Puxa a foto original na Nina 1 (getBase64) — sem gravar arquivo."""
    partes = partir_message_key(message_key)
    if not partes or not instance:
        return None
    remote, msg_id = partes
    try:
        raw = EvolutionClient().get_base64_from_media_message(
            instance,
            remote_jid=remote,
            message_id=msg_id,
        )
    except EvolutionUnavailable as exc:
        logger.warning(f"[espelho] getBase64 falhou ({instance}): {exc}")
        return None
    url = data_url_jpeg(raw or "")
    if not url:
        logger.warning(f"[espelho] getBase64 sem payload útil ({instance})")
    return url


def resolver_imagem_espelho(
    *,
    listen_instance: str | None,
    message_key: str,
    product_url: str,
    loja: str | None,
    media_path: str | None = None,
) -> str | None:
    """Ordem: mídia já na fila → getBase64 Nina 1 → CDN do produto."""
    if isinstance(media_path, str) and media_path.startswith("data:image/"):
        return media_path
    if isinstance(media_path, str) and media_path.startswith("https://"):
        return media_path
    if listen_instance:
        wa = midia_whatsapp_em_memoria(listen_instance, message_key)
        if wa:
            return wa
    return imagem_do_link_produto(product_url, loja)
