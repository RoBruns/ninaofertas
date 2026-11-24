"""Mídia do espelho: extrai base64 do webhook ou baixa via Evolution."""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from loguru import logger

from core.evolution import EvolutionClient, EvolutionUnavailable
from core.settings import BASE_DIR

_MIRROR_DIR = BASE_DIR / "data" / "mirror"
_DATA_URL_RE = re.compile(r"^data:image/[^;]+;base64,(.+)$", re.I | re.S)


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


def base64_da_mensagem(message: dict[str, Any] | None) -> str | None:
    """Base64 embutido quando o webhook Evolution manda `webhookBase64`."""
    msg = _unwrap_message(message)
    if not isinstance(msg, dict):
        return None
    image = msg.get("imageMessage")
    if isinstance(image, dict):
        for key in ("base64", "media"):
            raw = image.get(key)
            if isinstance(raw, str) and len(raw) > 64:
                return raw
    raw = msg.get("base64")
    if isinstance(raw, str) and len(raw) > 64:
        return raw
    return None


def _bytes_de_base64(raw: str) -> bytes | None:
    texto = (raw or "").strip()
    match = _DATA_URL_RE.match(texto)
    if match:
        texto = match.group(1)
    texto = "".join(texto.split())
    try:
        data = base64.b64decode(texto, validate=False)
    except Exception:
        return None
    return data if len(data) >= 64 else None


def _extensao(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:3] == b"GIF":
        return ".gif"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    return ".jpg"


def salvar_midia_base64(raw: str, stem: str) -> str | None:
    data = _bytes_de_base64(raw)
    if not data:
        return None
    try:
        _MIRROR_DIR.mkdir(parents=True, exist_ok=True)
        path = _MIRROR_DIR / f"{stem}{_extensao(data)}"
        path.write_bytes(data)
        return str(path)
    except OSError as exc:
        logger.warning(f"[espelho] falha ao gravar mídia: {exc}")
        return None


def partir_message_key(message_key: str) -> tuple[str, str] | None:
    remote, sep, msg_id = (message_key or "").rpartition(":")
    if not sep or not remote or not msg_id:
        return None
    return remote, msg_id


def baixar_midia_evolution(instance: str, message_key: str, stem: str) -> str | None:
    """Baixa a imagem original via Evolution e grava em data/mirror/."""
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
        logger.warning(f"[espelho] getBase64 midia falhou: {exc}")
        return None
    if not raw:
        return None
    return salvar_midia_base64(raw, stem)


def resolver_caminho_midia(
    *,
    media_path: str | None,
    has_media: bool,
    message_key: str,
    listen_instance: str | None,
    stem: str | UUID,
) -> str | None:
    if media_path and Path(media_path).is_file():
        return media_path
    if not has_media:
        return None
    if not listen_instance:
        return None
    return baixar_midia_evolution(listen_instance, message_key, str(stem))
