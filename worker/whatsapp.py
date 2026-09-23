"""Envio de mensagens para o grupo do WhatsApp via evolution-api (self-hosted).

evolution-api expõe uma API REST simples sobre o protocolo do WhatsApp Web —
é gratuita, roda em Docker e suporta envio para grupos, o que a API oficial
(Meta Cloud API) NÃO suporta. Ver README.md para instruções de setup.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx

from core.settings import settings
from worker.logger import logger


class WhatsAppError(Exception):
    pass


# Fallback de producao: usado somente quando nao existe bot configurado no banco.
LEGACY_PHONE_NUMBER = "558531791835"


def enviar_mensagem(texto: str, imagem: str | None = None, grupo: str | None = None) -> bool:
    """Envia `texto` (com `imagem` opcional) para o grupo do canal atual.
    Retorna True em sucesso, False em falha (nunca lança para não parar o bot)."""

    from worker.channels import grupo_whatsapp

    destino = grupo or grupo_whatsapp()
    if not settings.evolution_instance or not destino:
        logger.error("WhatsApp não configurado: defina EVOLUTION_INSTANCE e o ID do grupo no .env")
        return False

    headers = {"apikey": settings.evolution_api_key, "Content-Type": "application/json"}

    try:
        with httpx.Client(timeout=25.0) as client:
            if imagem:
                url = f"{settings.evolution_api_url}/message/sendMedia/{settings.evolution_instance}"
                payload = {
                    "number": destino,
                    "mediatype": "image",
                    "media": _media_payload(imagem),
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
            else:
                url = f"{settings.evolution_api_url}/message/sendText/{settings.evolution_instance}"
                payload = {"number": destino, "text": texto}

            resp = client.post(url, json=payload, headers=headers)

        if resp.status_code >= 400:
            logger.error(f"evolution-api retornou erro {resp.status_code}: {resp.text[:300]}")
            return False

        return True

    except httpx.RequestError as e:
        logger.error(f"Falha ao conectar na evolution-api ({settings.evolution_api_url}): {e}")
        return False


def _media_payload(imagem: str) -> str:
    """Evolution aceita URL pública ou base64 de arquivo local (print do cupom)."""
    if imagem.startswith("http://") or imagem.startswith("https://"):
        return imagem
    path = Path(imagem)
    if path.is_file():
        return base64.b64encode(path.read_bytes()).decode("ascii")
    return imagem


def _participante_do_numero(part: dict, numero: str) -> bool:
    blob = json.dumps(part, ensure_ascii=False).lower()
    return numero.lower() in blob


def avisar_permissao_grupos() -> None:
    """Grupo 'somente admins' + número sem admin = API 200 e ninguém vê a msg."""
    from worker.channels import CANAIS, canais_ativos, grupo_whatsapp, usar_canal

    ativos = canais_ativos()
    if any(canal.startswith("db:") for canal in ativos):
        _avisar_permissao_banco(ativos)
        return

    headers = {"apikey": settings.evolution_api_key}
    url = f"{settings.evolution_api_url}/group/fetchAllGroups/{settings.evolution_instance}"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers=headers, params={"getParticipants": "true"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"Não deu pra checar permissão dos grupos: {e}")
        return

    grupos = data if isinstance(data, list) else (data.get("data") or data.get("groups") or [])
    por_id = {}
    for g in grupos:
        if isinstance(g, dict):
            por_id[str(g.get("id") or g.get("jid") or "")] = g

    for canal in ativos:
        with usar_canal(canal):
            gid = grupo_whatsapp()
            g = por_id.get(gid)
            if not g:
                logger.warning(f"[{CANAIS[canal]['nome']}] grupo {gid} não apareceu na lista da Evolution")
                continue
            announce = bool(g.get("announce"))
            parts = g.get("participants") or []
            eu = next((p for p in parts if _participante_do_numero(p, LEGACY_PHONE_NUMBER)), None)
            admin = (eu or {}).get("admin") if isinstance(eu, dict) else None
            if announce and not admin:
                logger.error(
                    f"[{CANAIS[canal]['nome']}] grupo está 'somente admins' e o número do bot "
                    f"NÃO é admin — o WhatsApp engole a mensagem. "
                    f"Promova {LEGACY_PHONE_NUMBER} a admin."
                )
            elif announce:
                logger.info(f"[{CANAIS[canal]['nome']}] grupo somente admins; bot é admin ({admin}).")


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
                logger.warning(f"Nao deu pra checar permissao dos grupos: {exc}")
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
                logger.warning(f"[{nome_canal()}] grupo {wanted} nao apareceu na Evolution")
                continue
            if not bool(group.get("announce")):
                continue
            number = telefone_bot() or LEGACY_PHONE_NUMBER
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
                    f"[{nome_canal()}] grupo somente admins e o bot nao e admin; "
                    f"promova {number} a admin."
                )
            else:
                logger.info(f"[{nome_canal()}] grupo somente admins; bot e admin ({admin}).")
