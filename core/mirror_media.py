"""Foto do espelho: captura no webhook (fresca) + reenvio em base64 cru."""

from __future__ import annotations

import base64
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
    if not isinstance(msg, dict):
        return False
    if isinstance(msg.get("imageMessage"), dict):
        return True
    # Evolution com webhookBase64: às vezes sobra só o base64 no envelope.
    raw = msg.get("base64")
    return isinstance(raw, str) and len(raw) > 64


def base64_puro(raw: str | None) -> str | None:
    """Normaliza qualquer forma → base64 cru (o que o sendMedia da Evolution quer)."""
    if not isinstance(raw, str):
        return None
    texto = raw.strip()
    match = _DATA_URL_RE.match(texto)
    if match:
        texto = match.group(1)
    if "base64," in texto:
        texto = texto.split("base64,", 1)[1]
    texto = "".join(texto.split())
    if len(texto) < 32:
        return None
    # Valida decodificação mínima.
    try:
        data = base64.b64decode(texto, validate=False)
    except Exception:
        return None
    return texto if len(data) >= 24 else None


def _thumb_para_base64(thumb: object) -> str | None:
    """jpegThumbnail pode vir string base64 ou Buffer JSON do Node."""
    if isinstance(thumb, str):
        return base64_puro(thumb)
    if isinstance(thumb, dict) and str(thumb.get("type") or "").lower() == "buffer":
        data = thumb.get("data")
        if isinstance(data, list) and data:
            try:
                return base64.b64encode(bytes(int(x) & 0xFF for x in data)).decode("ascii")
            except (TypeError, ValueError):
                return None
    if isinstance(thumb, list) and thumb:
        try:
            return base64.b64encode(bytes(int(x) & 0xFF for x in thumb)).decode("ascii")
        except (TypeError, ValueError):
            return None
    return None


def midia_do_payload_webhook(message: dict[str, Any] | None) -> str | None:
    """Extrai base64 cru do upsert (message.base64, image.base64 ou jpegThumbnail)."""
    msg = _unwrap_message(message)
    if not isinstance(msg, dict):
        return None
    # Evolution (webhookBase64): base64 no envelope da message.
    for key in ("base64", "media"):
        got = base64_puro(msg.get(key) if isinstance(msg.get(key), str) else None)
        if got:
            return got
    image = msg.get("imageMessage")
    if isinstance(image, dict):
        for key in ("base64", "media"):
            got = base64_puro(image.get(key) if isinstance(image.get(key), str) else None)
            if got:
                return got
        thumb = _thumb_para_base64(image.get("jpegThumbnail"))
        if thumb:
            return thumb
    # Link com prévia: a foto não é imageMessage, vem no extendedTextMessage.
    return midia_preview_do_link(msg)


def _nos_preview(message: dict[str, Any] | None) -> list[dict[str, Any]]:
    msg = _unwrap_message(message)
    if not isinstance(msg, dict):
        return []
    nos: list[dict[str, Any]] = []
    ext = msg.get("extendedTextMessage")
    if isinstance(ext, dict):
        nos.append(ext)
        ctx = ext.get("contextInfo")
        if isinstance(ctx, dict):
            anuncio = ctx.get("externalAdReply")
            if isinstance(anuncio, dict):
                nos.append(anuncio)
    return nos


def midia_preview_do_link(message: dict[str, Any] | None) -> str | None:
    """URL ou miniatura da prévia do link. Não usa a foto de uma mensagem citada.

    A URL do CDN vem antes do jpegThumbnail: a miniatura embutida é pequena.
    """
    nos = _nos_preview(message)
    for node in nos:
        for key in ("thumbnailUrl", "mediaUrl"):
            url = node.get(key)
            if isinstance(url, str) and url.startswith("https://") and _host_permitido(url):
                return url.split("#", 1)[0]
        thumb = node.get("thumbnail")
        if isinstance(thumb, str) and thumb.startswith("https://") and _host_permitido(thumb):
            return thumb.split("#", 1)[0]
    for node in nos:
        for key in ("jpegThumbnail", "thumbnail"):
            got = _thumb_para_base64(node.get(key))
            if got:
                return got
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


class ProdutoSomenteVideo(Exception):
    """A galeria do produto só tem vídeo, ou a única imagem é a capa dele."""


def _eh_video_url(url: str) -> bool:
    baixo = (url or "").lower()
    return any(marca in baixo for marca in (".mp4", ".m3u8", ".webm", "vod.susercontent"))


def _url_arquivo_shopee(token: str) -> str | None:
    bruto = (token or "").strip()
    if bruto.startswith("https://"):
        if not _host_permitido(bruto) or _eh_video_url(bruto):
            return None
        return bruto.split("#", 1)[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,}", bruto):
        return None
    return f"https://down-br.img.susercontent.com/file/{bruto}"


def _eh_shopee(loja: str | None, url: str) -> bool:
    nome = (loja or "").lower()
    host = (urlparse(url).hostname or "").lower()
    return "shopee" in nome or host.endswith("shopee.com.br") or host.endswith("shopee.com")


def escolher_imagem_galeria(imagens: list[str], *, tem_video: bool) -> str | None:
    """Primeira mídia do carrossel que não é vídeo.

    O vídeo, quando existe, ocupa o primeiro slide — a capa JPEG conta como vídeo.
    Se o slide seguinte também for vídeo, segue para o próximo. Só vídeo → None.
    """
    for indice, url in enumerate(imagens):
        if _eh_video_url(url) or (tem_video and indice == 0):
            continue
        return url
    return None


def _galeria_shopee(html: str) -> tuple[list[str], bool]:
    tem_video = bool(re.search(r'"video_info_list"\s*:\s*\[\s*\{', html))
    melhor: list[str] = []
    for match in re.finditer(r'"images"\s*:\s*\[(.*?)\]', html, re.S):
        urls: list[str] = []
        for token in re.findall(r'"([^"]+)"', match.group(1)[:8000]):
            if _eh_video_url(token):
                if token not in urls:
                    urls.append(token)
                continue
            url = _url_arquivo_shopee(token)
            if url and url not in urls:
                urls.append(url)
        if len(urls) > len(melhor):
            melhor = urls
    return melhor, tem_video


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
    html = response.text[:250_000]
    if _eh_shopee(loja, final):
        imagens, tem_video = _galeria_shopee(html)
        if imagens or tem_video:
            foto = escolher_imagem_galeria(imagens, tem_video=tem_video)
            if foto:
                return foto
            raise ProdutoSomenteVideo()
    foto = _extrair_og_image(html[:120_000], final)
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
    """getBase64 na Nina 1 → base64 cru."""
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
    got = base64_puro(raw)
    if not got:
        logger.warning(f"[espelho] getBase64 sem payload útil ({instance})")
    return got


def capturar_midia_no_webhook(
    message: dict[str, Any] | None,
    *,
    instance: str | None,
    message_key: str,
) -> str | None:
    """Melhor momento: payload → senão getBase64 imediato (mídia ainda fresca)."""
    local = midia_do_payload_webhook(message)
    if local:
        return local
    if not mensagem_tem_imagem(message):
        # Sem imageMessage explícita, ainda tenta getBase64 se houver key
        # (alguns payloads só trazem caption em extendedText + mídia à parte).
        pass
    if instance and message_key:
        return midia_whatsapp_em_memoria(instance, message_key)
    return None


def resolver_imagem_espelho(
    *,
    listen_instance: str | None,
    message_key: str,
    product_url: str,
    loja: str | None,
    media_path: str | None = None,
) -> str | None:
    """Ordem: foto do produto (galeria Shopee ou og:image) → mídia na fila → getBase64.

    Na Shopee o carrossel é percorrido na ordem: vídeo é pulado até achar uma
    foto. Se todos os slides forem vídeo, levanta ProdutoSomenteVideo e não
    cai na prévia do link.
    """
    cdn = imagem_do_link_produto(product_url, loja)
    if cdn:
        return cdn
    if isinstance(media_path, str) and media_path.startswith("https://"):
        return media_path
    if isinstance(media_path, str):
        got = base64_puro(media_path)
        if got:
            return got
    if listen_instance:
        return midia_whatsapp_em_memoria(listen_instance, message_key)
    return None
