"""Envio de mensagens para o grupo do WhatsApp via evolution-api (self-hosted).

evolution-api expõe uma API REST simples sobre o protocolo do WhatsApp Web —
é gratuita, roda em Docker e suporta envio para grupos, o que a API oficial
(Meta Cloud API) NÃO suporta. Ver README.md para instruções de setup.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx

from config import BASE_DIR, settings
from log_safe import safe_log_text
from logger import logger


class WhatsAppError(Exception):
    pass


_MEDIA_URL_PREFIXES = (
    "https://http2.mlstatic.com/",
    "https://http.mlstatic.com/",
    "https://cf.shopee.com.br/",
    "https://down-br.img.susercontent.com/",
    "https://scontent.",
)


def _path_local_permitido(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root_name in ("data", "assets"):
        root = (BASE_DIR / root_name).resolve()
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _url_midia_permitida(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return False
    if host.startswith("169.254.") or host.startswith("10.") or host.startswith("192.168."):
        return False
    prefix = f"{parsed.scheme}://{parsed.netloc}/"
    if any(url.startswith(p) for p in _MEDIA_URL_PREFIXES):
        return True
    return host.endswith("shopee.com.br") or host.endswith("mercadolivre.com.br") or host.endswith("mlstatic.com")


def enviar_mensagem(texto: str, imagem: str | None = None, grupo: str | None = None) -> bool:
    """Envia `texto` (com `imagem` opcional) para o grupo do canal atual.
    Retorna True em sucesso, False em falha (nunca lança para não parar o bot)."""

    from config import grupo_whatsapp

    destino = grupo or grupo_whatsapp()
    if not settings.evolution_instance or not destino:
        logger.error("WhatsApp não configurado: defina EVOLUTION_INSTANCE e o ID do grupo no .env")
        return False

    headers = {"apikey": settings.evolution_api_key, "Content-Type": "application/json"}

    try:
        with httpx.Client(timeout=25.0) as client:
            if imagem:
                media = _media_payload(imagem)
                if media:
                    url = f"{settings.evolution_api_url}/message/sendMedia/{settings.evolution_instance}"
                    payload = {
                        "number": destino,
                        "mediatype": "image",
                        "media": media,
                        "caption": texto,
                    }
                    if not str(imagem).startswith("http"):
                        sufixo = Path(imagem).suffix.lower()
                        if sufixo in {".jpg", ".jpeg"}:
                            payload["mimetype"] = "image/jpeg"
                            payload["fileName"] = "foto.jpg"
                        else:
                            payload["mimetype"] = "image/png"
                            payload["fileName"] = "cupom.png"
                    resp = client.post(url, json=payload, headers=headers)
                    if resp.status_code >= 400:
                        logger.error(
                            f"evolution-api retornou erro {resp.status_code}: "
                            f"{safe_log_text(resp.text, 300)}"
                        )
                        return False
                    return True
                logger.warning("Imagem rejeitada (URL/path não permitido); enviando só texto.")

            url = f"{settings.evolution_api_url}/message/sendText/{settings.evolution_instance}"
            payload = {"number": destino, "text": texto}
            resp = client.post(url, json=payload, headers=headers)

        if resp.status_code >= 400:
            logger.error(
                f"evolution-api retornou erro {resp.status_code}: {safe_log_text(resp.text, 300)}"
            )
            return False

        return True

    except httpx.RequestError as e:
        logger.error(f"Falha ao conectar na evolution-api ({settings.evolution_api_url}): {e}")
        return False


def _media_payload(imagem: str) -> str | None:
    """Evolution aceita URL pública (allowlist) ou base64 de arquivo local permitido."""
    if imagem.startswith("https://"):
        if not _url_midia_permitida(imagem):
            logger.warning(f"URL de mídia fora da allowlist: {imagem[:120]}")
            return None
        return imagem
    if imagem.startswith("http://"):
        logger.warning("URL http:// não permitida para mídia; use https ou arquivo local.")
        return None
    path = Path(imagem)
    if path.is_file():
        if not _path_local_permitido(path):
            logger.warning(f"Arquivo de mídia fora de data/ ou assets/: {imagem}")
            return None
        return base64.b64encode(path.read_bytes()).decode("ascii")
    return None


def _participante_do_numero(part: dict, numero: str) -> bool:
    blob = json.dumps(part, ensure_ascii=False).lower()
    return numero.lower() in blob


def _numero_bot() -> str:
    return (settings.evolution_bot_number or "").strip()


def avisar_permissao_grupos() -> None:
    """Grupo 'somente admins' + número sem admin = API 200 e ninguém vê a msg."""
    from config import CANAIS, canais_ativos, grupo_whatsapp, usar_canal

    numero = _numero_bot()
    if not numero:
        logger.debug("EVOLUTION_BOT_NUMBER não definido — pulando checagem de admin nos grupos.")
        return

    headers = {"apikey": settings.evolution_api_key}
    url = f"{settings.evolution_api_url}/group/fetchAllGroups/{settings.evolution_instance}"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers=headers, params={"getParticipants": "true"})
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        logger.warning(f"Não deu pra checar permissão dos grupos: {e}")
        return
    except Exception as e:
        logger.warning(f"Não deu pra checar permissão dos grupos: {e}")
        return

    grupos = data if isinstance(data, list) else (data.get("data") or data.get("groups") or [])
    por_id = {}
    for g in grupos:
        if isinstance(g, dict):
            por_id[str(g.get("id") or g.get("jid") or "")] = g

    for canal in canais_ativos():
        with usar_canal(canal):
            gid = grupo_whatsapp()
            g = por_id.get(gid)
            if not g:
                logger.warning(f"[{CANAIS[canal]['nome']}] grupo {gid} não apareceu na lista da Evolution")
                continue
            announce = bool(g.get("announce"))
            parts = g.get("participants") or []
            eu = next((p for p in parts if _participante_do_numero(p, numero)), None)
            admin = (eu or {}).get("admin") if isinstance(eu, dict) else None
            if announce and not admin:
                logger.error(
                    f"[{CANAIS[canal]['nome']}] grupo está 'somente admins' e o número do bot "
                    f"NÃO é admin — o WhatsApp engole a mensagem. Promova {numero} a admin."
                )
            elif announce:
                logger.info(f"[{CANAIS[canal]['nome']}] grupo somente admins; bot é admin ({admin}).")
