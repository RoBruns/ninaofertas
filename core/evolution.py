"""Cliente pequeno e tolerante a falhas para a evolution-api."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from core.settings import settings


class EvolutionUnavailable(Exception):
    """A evolution-api nao respondeu de forma utilizavel."""


class EvolutionInvalidInvite(Exception):
    """Convite inválido ou sem acesso ao grupo."""


class EvolutionAlreadyConnected(Exception):
    """O WhatsApp já está conectado; não há QR para exibir."""


class EvolutionConflict(Exception):
    """O nome da instância já existe no provedor."""


class EvolutionRejected(Exception):
    """O provedor recusou a criação da instância."""


@dataclass(frozen=True)
class CreatedInstance:
    token: str = field(repr=False)
    qrcode_base64: str | None
    expires_at: datetime


def _token(payload: dict[str, Any]) -> str | None:
    instance = payload.get("instance") or {}
    if not isinstance(instance, dict):
        raise EvolutionUnavailable("Resposta de instância inválida da evolution-api")
    candidates = (payload.get("token"), payload.get("hash"), instance.get("apikey"))
    for value in candidates:
        if isinstance(value, dict):
            value = value.get("apikey")
        if isinstance(value, str) and value.strip():
            return value
    return None


class EvolutionClient:
    def invite_info(self, instance: str | None, code: str) -> dict[str, Any]:
        if not instance:
            raise EvolutionUnavailable("Telefone sem instância da evolution-api")
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(
                    f"{self.base_url}/group/inviteInfo/{instance}",
                    params={"inviteCode": code}, headers=self.headers,
                )
            if response.status_code in {400, 404, 410}:
                raise EvolutionInvalidInvite("Convite inválido ou expirado; confira o link do grupo")
            if response.status_code == 403:
                raise EvolutionInvalidInvite("O telefone precisa já ser membro do grupo")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("id"), str) or not payload["id"].endswith("@g.us"):
                raise EvolutionUnavailable("Resposta de grupo inválida da evolution-api")
            return payload
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise EvolutionUnavailable("evolution-api indisponível") from exc

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = (base_url or settings.evolution_api_url).rstrip("/")
        self.api_key = settings.evolution_api_key if api_key is None else api_key

    @property
    def headers(self) -> dict[str, str]:
        return {"apikey": self.api_key}

    def connection_status(self, instance: str | None, *, strict: bool = False) -> str:
        if not instance:
            return "unknown"
        try:
            with httpx.Client(timeout=3.0) as client:
                response = client.get(
                    f"{self.base_url}/instance/connectionState/{instance}",
                    headers=self.headers,
                )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            if strict:
                raise EvolutionUnavailable("evolution-api indisponível") from exc
            return "unknown"
        if not isinstance(payload, dict) or payload.get("error"):
            if strict:
                raise EvolutionUnavailable("evolution-api indisponível")
            return "unknown"
        instance_data = payload.get("instance") or {}
        if not isinstance(instance_data, dict):
            if strict:
                raise EvolutionUnavailable("Resposta de estado inválida da evolution-api")
            return "unknown"
        state = payload.get("state") or instance_data.get("state")
        normalized = str(state or "unknown").casefold()
        return {
            "open": "connected",
            "connected": "connected",
            "close": "disconnected",
            "disconnected": "disconnected",
            "connecting": "connecting",
            "banned": "banned",
        }.get(normalized, "unknown")

    def create_instance(self, instance: str, *, defer_qr: bool = False) -> CreatedInstance:
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    f"{self.base_url}/instance/create", headers=self.headers,
                    json={"instanceName": instance, "qrcode": True, "integration": "WHATSAPP-BAILEYS"},
                )
            if response.status_code == 403 and "already in use" in response.text:
                raise EvolutionConflict("Nome de instância já utilizado")
            if 400 <= response.status_code < 500:
                raise EvolutionRejected("A evolution-api recusou a criação da instância")
            response.raise_for_status()
            payload = response.json()
            token = _token(payload)
            if not token or payload.get("error"):
                raise EvolutionUnavailable("Resposta de criação inválida da evolution-api")
            code = (payload.get("qrcode") or {}).get("base64")
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
            if not code and not defer_qr:
                try:
                    code, expires_at = self.qrcode(instance)
                except (EvolutionUnavailable, EvolutionAlreadyConnected):
                    # Preserve o token retornado mesmo sem QR utilizável.
                    pass
            return CreatedInstance(token, str(code) if code else None, expires_at)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            raise EvolutionUnavailable("evolution-api indisponível") from exc

    def fetch_instance(self, instance: str) -> dict[str, Any] | None:
        """Consulta administrativa interna; contém segredo e nunca deve ser serializada."""
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(
                    f"{self.base_url}/instance/fetchInstances",
                    params={"instanceName": instance}, headers=self.headers,
                )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                payload = payload[0] if payload else None
            if payload is None:
                return None
            if not isinstance(payload, dict) or payload.get("error"):
                raise EvolutionUnavailable("Resposta de consulta inválida da evolution-api")
            return payload
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            raise EvolutionUnavailable("evolution-api indisponível") from exc

    def fetch_instance_token(self, instance: str) -> str | None:
        payload = self.fetch_instance(instance)
        return _token(payload) if payload else None

    def instance_number(self, instance: str) -> str | None:
        payload = self.fetch_instance(instance)
        if not payload:
            return None
        owner = payload.get("ownerJid") or (payload.get("instance") or {}).get("ownerJid")
        number = str(owner or "").split("@")[0]
        return number if number.isascii() and number.isdigit() and 8 <= len(number) <= 15 else None

    def qrcode(self, instance: str | None) -> tuple[str, datetime]:
        if not instance:
            raise EvolutionUnavailable("Telefone sem instância da evolution-api")
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(
                    f"{self.base_url}/instance/connect/{instance}", headers=self.headers
                )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            if payload.get("error"):
                raise EvolutionUnavailable("evolution-api indisponível")
            if (payload.get("instance") or {}).get("state") == "open":
                raise EvolutionAlreadyConnected("WhatsApp já conectado")
            code = payload.get("base64") or payload.get("qrcode", {}).get("base64")
            if not code:
                raise EvolutionUnavailable("QR code indisponível")
            expires = payload.get("expires_at") or payload.get("expiresAt")
            expires_at = (
                datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
                if expires
                else datetime.now(timezone.utc) + timedelta(seconds=60)
            )
            return str(code), expires_at
        except EvolutionUnavailable:
            raise
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            raise EvolutionUnavailable("evolution-api indisponível") from exc

    def get_base64_from_media_message(
        self,
        instance: str,
        *,
        remote_jid: str,
        message_id: str,
        from_me: bool = False,
    ) -> str | None:
        """Baixa mídia de uma mensagem já recebida (imagem do espelho)."""
        if not instance or not remote_jid or not message_id:
            raise EvolutionUnavailable("Parâmetros de mídia incompletos")
        body = {
            "message": {
                "key": {
                    "remoteJid": remote_jid,
                    "id": message_id,
                    "fromMe": from_me,
                }
            },
            "convertToMp4": False,
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{self.base_url}/chat/getBase64FromMediaMessage/{instance}",
                    headers=self.headers,
                    json=body,
                )
            if response.status_code >= 400:
                raise EvolutionUnavailable(
                    f"evolution-api recusou mídia ({response.status_code})"
                )
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise EvolutionUnavailable("evolution-api indisponível") from exc
        if isinstance(payload, str) and len(payload) > 64:
            return payload
        if not isinstance(payload, dict):
            return None
        for key in ("base64", "data"):
            raw = payload.get(key)
            if isinstance(raw, str) and len(raw) > 64:
                return raw
        nested = payload.get("message")
        if isinstance(nested, dict):
            for key in ("base64", "data"):
                raw = nested.get(key)
                if isinstance(raw, str) and len(raw) > 64:
                    return raw
        return None

    def set_webhook(self, instance: str, url: str, *, events: list[str] | None = None) -> None:
        """Registra webhook de mensagens na instância (Evolution v2)."""
        if not instance:
            raise EvolutionUnavailable("Telefone sem instância da evolution-api")
        event_list = events or ["MESSAGES_UPSERT"]
        # webhookBase64=True: a foto do espelho pode vir no próprio upsert.
        payloads = (
            {
                "webhook": {
                    "enabled": True,
                    "url": url,
                    "webhookByEvents": False,
                    "webhookBase64": True,
                    "events": event_list,
                }
            },
            {
                "enabled": True,
                "url": url,
                "webhookByEvents": False,
                "webhookBase64": True,
                "events": event_list,
            },
        )
        last_error: Exception | None = None
        try:
            with httpx.Client(timeout=10.0) as client:
                for body in payloads:
                    response = client.post(
                        f"{self.base_url}/webhook/set/{instance}",
                        headers=self.headers,
                        json=body,
                    )
                    if response.status_code < 400:
                        return
                    last_error = EvolutionUnavailable(
                        f"evolution-api recusou webhook ({response.status_code})"
                    )
            if last_error:
                raise last_error
            raise EvolutionUnavailable("evolution-api indisponível")
        except EvolutionUnavailable:
            raise
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            raise EvolutionUnavailable("evolution-api indisponível") from exc
