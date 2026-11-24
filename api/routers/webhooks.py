"""Webhooks públicos autenticados por segredo (Evolution → captura → inbox)."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from api.deps import get_db
from api.errors import APIError
from core.bot_settings import BotSettings
from core.mirror_match import nome_na_allowlist
from core.mirror_media import base64_da_mensagem, mensagem_tem_imagem, salvar_midia_base64
from core.mirror_sources import allowlist_para_bot
from core.mirror_webhook import webhook_secret
from core.models import Bot, BotGroup, Group, MirrorCapture, MirrorInbox, Phone


def _renomear_midia(path: str | None, stem: str) -> str | None:
    if not path:
        return None
    origem = Path(path)
    if not origem.is_file():
        return path
    destino = origem.with_name(f"{stem}{origem.suffix}")
    if destino == origem:
        return path
    try:
        origem.replace(destino)
        return str(destino)
    except OSError:
        return path

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _texto_mensagem(message: dict[str, Any] | None) -> str:
    if not isinstance(message, dict):
        return ""
    if isinstance(message.get("conversation"), str):
        return message["conversation"]
    ext = message.get("extendedTextMessage")
    if isinstance(ext, dict) and isinstance(ext.get("text"), str):
        return ext["text"]
    image = message.get("imageMessage")
    if isinstance(image, dict) and isinstance(image.get("caption"), str):
        return image["caption"]
    video = message.get("videoMessage")
    if isinstance(video, dict) and isinstance(video.get("caption"), str):
        return video["caption"]
    buttons = message.get("buttonsMessage")
    if isinstance(buttons, dict) and isinstance(buttons.get("contentText"), str):
        return buttons["contentText"]
    template = message.get("templateMessage")
    if isinstance(template, dict):
        hydrated = template.get("hydratedTemplate") or template.get("fourRowTemplate") or {}
        if isinstance(hydrated, dict):
            for key in ("hydratedContentText", "contentText", "text"):
                if isinstance(hydrated.get(key), str):
                    return hydrated[key]
    for wrap_key in (
        "ephemeralMessage",
        "viewOnceMessage",
        "viewOnceMessageV2",
        "documentWithCaptionMessage",
    ):
        wrapped = message.get(wrap_key)
        if isinstance(wrapped, dict):
            inner = wrapped.get("message")
            texto = _texto_mensagem(inner if isinstance(inner, dict) else None)
            if texto:
                return texto
    return ""


def _itens_upsert(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        msgs = data.get("messages")
        if isinstance(msgs, list):
            return [item for item in msgs if isinstance(item, dict)]
        return [data]
    return []


def _auth_ok(request: Request, token: str | None) -> bool:
    expected = webhook_secret()
    if not expected:
        return False
    header = request.headers.get("x-webhook-token") or request.headers.get("apikey")
    candidates = [token, header]
    return any(
        isinstance(c, str) and c and secrets.compare_digest(c, expected) for c in candidates
    )


def _bots_inscritos(session: Session, listen_phone_id: UUID) -> list[tuple[Bot, BotSettings]]:
    """Todo bot ativo (qualquer tenant), menos o chip de escuta Nina 1.

    Sem toggle: a inscrição no espelho é automática (ADR-036).
    """
    bots = session.scalars(select(Bot).where(Bot.status == "active")).all()
    out: list[tuple[Bot, BotSettings]] = []
    for bot in bots:
        try:
            settings = BotSettings.model_validate(bot.settings or {})
        except Exception:
            continue
        if bot.phone_id and bot.phone_id == listen_phone_id:
            continue
        out.append((bot, settings))
    return out


@router.post("/evolution")
async def evolution_messages(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    token: str | None = Query(default=None),
) -> dict[str, Any]:
    if not _auth_ok(request, token):
        raise APIError(401, "UNAUTHORIZED", "Webhook não autorizado")

    try:
        payload = await request.json()
    except Exception:
        return {"accepted": 0, "ignored": "body"}
    if not isinstance(payload, dict):
        return {"accepted": 0}

    event = str(payload.get("event") or payload.get("type") or "").lower().replace("_", ".")
    if event and "upsert" not in event and payload.get("data") is None:
        return {"accepted": 0, "ignored": "event"}

    instance = str(payload.get("instance") or payload.get("instanceName") or "").strip()
    if not instance and isinstance(payload.get("data"), dict):
        instance = str(payload["data"].get("instance") or "").strip()
    if not instance:
        return {"accepted": 0, "ignored": "instance"}

    phone = session.scalar(select(Phone).where(Phone.evolution_instance == instance))
    if phone is None:
        return {"accepted": 0, "ignored": "phone"}
    from core.mirror_webhook import sync_platform_listen_flags

    sync_platform_listen_flags(session)
    session.refresh(phone)
    if not phone.is_platform_listen:
        return {"accepted": 0, "ignored": "not_platform_listen"}

    candidatos = _bots_inscritos(session, phone.id)
    if not candidatos:
        return {"accepted": 0, "ignored": "no_bot"}

    accepted = 0
    captures = 0
    for item in _itens_upsert(payload):
        key = item.get("key") if isinstance(item.get("key"), dict) else {}
        if key.get("fromMe") is True:
            continue
        remote = str(key.get("remoteJid") or key.get("remoteJidAlt") or "").strip()
        if not remote:
            continue
        if not (remote.endswith("@g.us") or remote.endswith("@newsletter")):
            continue
        msg_id = str(key.get("id") or "").strip()
        if not msg_id:
            continue
        message_key = f"{remote}:{msg_id}"
        message_obj = item.get("message") if isinstance(item.get("message"), dict) else None
        body = _texto_mensagem(message_obj).strip()
        if not body:
            continue
        if len(body) > 4000:
            body = body[:4000]
        has_media = mensagem_tem_imagem(message_obj)
        media_path: str | None = None
        if has_media:
            raw_b64 = base64_da_mensagem(message_obj)
            if raw_b64:
                # stem provisório até ter o id da captura
                media_path = salvar_midia_base64(raw_b64, f"tmp-{msg_id}")

        grupo = session.scalar(
            select(Group).where(Group.phone_id == phone.id, Group.whatsapp_id == remote)
        )
        nome_grupo = grupo.name if grupo else None
        if not nome_grupo:
            for field in ("pushName", "name", "subject"):
                raw = item.get(field)
                if isinstance(raw, str) and raw.strip():
                    nome_grupo = raw.strip()
                    break

        # Captura neutra (uma por mensagem na Nina 1).
        cap_stmt = (
            insert(MirrorCapture)
            .values(
                listen_phone_id=phone.id,
                source_whatsapp_id=remote,
                source_group_name=nome_grupo,
                message_key=message_key,
                body_text=body,
                has_media=has_media,
                media_path=media_path,
                status="routed",
                created_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(constraint="uq_mirror_captures_phone_key")
            .returning(MirrorCapture.id)
        )
        cap_row = session.execute(cap_stmt).first()
        if cap_row:
            capture_id = cap_row[0]
            captures += 1
            if media_path and capture_id:
                media_path = _renomear_midia(media_path, f"cap-{capture_id}")
                session.execute(
                    update(MirrorCapture)
                    .where(MirrorCapture.id == capture_id)
                    .values(media_path=media_path)
                )
        else:
            capture = session.scalar(
                select(MirrorCapture).where(
                    MirrorCapture.listen_phone_id == phone.id,
                    MirrorCapture.message_key == message_key,
                )
            )
            capture_id = capture.id if capture else None
            if capture is not None:
                has_media = bool(capture.has_media) or has_media
                media_path = capture.media_path or media_path

        for bot, settings in candidatos:
            dest_ids = set(
                session.scalars(
                    select(Group.whatsapp_id)
                    .join(BotGroup, BotGroup.group_id == Group.id)
                    .where(BotGroup.bot_id == bot.id)
                ).all()
            )
            if remote in dest_ids:
                continue
            allow = allowlist_para_bot(settings.mirror.source_group_names)
            if not nome_na_allowlist(nome_grupo, allow):
                continue
            inbox_stmt = (
                insert(MirrorInbox)
                .values(
                    owner_id=bot.owner_id,
                    bot_id=bot.id,
                    capture_id=capture_id,
                    listen_phone_id=phone.id,
                    source_whatsapp_id=remote,
                    source_group_name=nome_grupo,
                    message_key=message_key,
                    body_text=body,
                    has_media=has_media,
                    media_path=media_path,
                    status="pending",
                    created_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_nothing(constraint="uq_mirror_inbox_bot_key")
            )
            result = session.execute(inbox_stmt)
            if result.rowcount:
                accepted += 1

    session.commit()
    return {"accepted": accepted, "captures": captures}
