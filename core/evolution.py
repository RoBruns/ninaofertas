"""Cliente pequeno e tolerante a falhas para a evolution-api."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from core.settings import settings


class EvolutionUnavailable(Exception):
    """A evolution-api nao respondeu de forma utilizavel."""


class EvolutionClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = (base_url or settings.evolution_api_url).rstrip("/")
        self.api_key = settings.evolution_api_key if api_key is None else api_key

    @property
    def headers(self) -> dict[str, str]:
        return {"apikey": self.api_key}

    def connection_status(self, instance: str | None) -> str:
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
        except (httpx.HTTPError, ValueError, TypeError):
            return "unknown"
        state = payload.get("state") or (payload.get("instance") or {}).get("state")
        normalized = str(state or "unknown").casefold()
        return {
            "open": "connected",
            "connected": "connected",
            "close": "disconnected",
            "disconnected": "disconnected",
            "banned": "banned",
        }.get(normalized, "unknown")

    def qrcode(self, instance: str | None) -> tuple[str, datetime]:
        if not instance:
            raise EvolutionUnavailable("Telefone sem instancia da evolution-api")
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(
                    f"{self.base_url}/instance/connect/{instance}", headers=self.headers
                )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            code = payload.get("base64") or payload.get("qrcode", {}).get("base64")
            if not code:
                raise EvolutionUnavailable("QR code indisponivel")
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
            raise EvolutionUnavailable("evolution-api indisponivel") from exc
