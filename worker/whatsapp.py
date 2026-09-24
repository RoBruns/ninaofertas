"""Envio de mensagens via evolution-api usando a instancia do telefone do bot."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx

from core.log_safe import safe_log_text
from core.settings import BASE_DIR, settings
from worker.logger import logger


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
        try:
            resolved.relative_to((BASE_DIR / root_name).resolve())
            return True
        except ValueError:
            continue
    return False


def _url_midia_permitida(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if any(url.startswith(prefix) for prefix in _MEDIA_URL_PREFIXES):
        return True
    return host.endswith(("shopee.com.br", "mercadolivre.com.br", "mlstatic.com"))


def enviar_mensagem(texto: str, imagem: str | None = None, grupo: str | None = None) -> bool:
    """Envia texto e, apenas quando permitida, uma imagem para o grupo atual."""
    from worker.channels import grupo_whatsapp, instancia_evolution

    destino = grupo or grupo_whatsapp()
    instancia = instancia_evolution()
    if not instancia or not destino:
        logger.error(
            "WhatsApp não configurado: o telefone do bot precisa de instância Evolution "
            "e o bot, de um grupo (dashboard)."
        )
        return False

    headers = {"apikey": settings.evolution_api_key, "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=25.0) as client:
            if imagem:
                media = _media_payload(imagem)
                if media:
                    url = f"{settings.evolution_api_url}/message/sendMedia/{instancia}"
                    payload = {
                        "number": destino,
                        "mediatype": "image",
                        "media": media,
                        "caption": texto,
                    }
                    if not str(imagem).startswith("http"):
                        if Path(imagem).suffix.lower() in {".jpg", ".jpeg"}:
                            payload["mimetype"] = "image/jpeg"
                            payload["fileName"] = "foto.jpg"
                        else:
                            payload["mimetype"] = "image/png"
                            payload["fileName"] = "cupom.png"
                    response = client.post(url, json=payload, headers=headers)
                    if response.status_code >= 400:
                        logger.error(
                            f"evolution-api retornou erro {response.status_code}: "
                            f"{safe_log_text(response.text, 300)}"
                        )
                        return False
                    return True
                logger.warning("Imagem rejeitada (URL/path não permitido); enviando só texto.")

            url = f"{settings.evolution_api_url}/message/sendText/{instancia}"
            response = client.post(
                url,
                json={"number": destino, "text": texto},
                headers=headers,
            )
        if response.status_code >= 400:
            logger.error(
                f"evolution-api retornou erro {response.status_code}: "
                f"{safe_log_text(response.text, 300)}"
            )
            return False
        return True
    except httpx.RequestError as exc:
        logger.error(
            f"Falha ao conectar na evolution-api ({settings.evolution_api_url}): "
            f"{safe_log_text(exc)}"
        )
        return False


def _media_payload(imagem: str) -> str | None:
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
    return numero.lower() in json.dumps(part, ensure_ascii=False).lower()


def avisar_permissao_grupos() -> None:
    from worker.channels import canais_ativos

    ativos = canais_ativos()
    if ativos:
        _avisar_permissao_banco(ativos)


def _avisar_permissao_banco(canais: tuple[str, ...]) -> None:
    from worker.channels import (
        grupo_whatsapp,
        instancia_evolution,
        nome_canal,
        telefone_bot,
        usar_canal,
    )

    headers = {"apikey": settings.evolution_api_key}
    for canal in canais:
        with usar_canal(canal):
            instance = instancia_evolution()
            url = f"{settings.evolution_api_url}/group/fetchAllGroups/{instance}"
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(
                        url, headers=headers, params={"getParticipants": "true"}
                    )
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                logger.warning(
                    f"Não deu para checar permissão dos grupos: {safe_log_text(exc)}"
                )
                continue
            groups = (
                data if isinstance(data, list) else data.get("data") or data.get("groups") or []
            )
            wanted = grupo_whatsapp()
            group = next(
                (
                    item
                    for item in groups
                    if isinstance(item, dict)
                    and str(item.get("id") or item.get("jid") or "") == wanted
                ),
                None,
            )
            if group is None:
                logger.warning(f"[{nome_canal()}] grupo {wanted} não apareceu na Evolution")
                continue
            if not bool(group.get("announce")):
                continue
            number = telefone_bot()
            if not number:
                logger.warning(
                    f"[{nome_canal()}] grupo somente admins; cadastre o número do telefone "
                    "no dashboard para conferir se o bot é admin."
                )
                continue
            participant = next(
                (
                    item
                    for item in group.get("participants") or []
                    if _participante_do_numero(item, number)
                ),
                None,
            )
            admin = participant.get("admin") if isinstance(participant, dict) else None
            if not admin:
                logger.error(
                    f"[{nome_canal()}] grupo somente admins e o bot não é admin; "
                    f"promova {number} a admin."
                )
            else:
                logger.info(f"[{nome_canal()}] grupo somente admins; bot é admin ({admin}).")
