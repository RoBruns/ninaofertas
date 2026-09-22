"""Schemas de credencial estritamente write-only."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CredentialState = Literal["valid", "expiring", "expired", "invalid", "unknown"]


class CredentialWrite(BaseModel):
    value: str = Field(min_length=1)


class CredentialStatus(BaseModel):
    kind: str
    status: CredentialState
    expires_at: datetime | None
    last_rotated_at: datetime | None
    last_used_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    needs_renewal: bool


class CredentialTestResponse(BaseModel):
    ok: bool
    checked_at: datetime
    message: str
