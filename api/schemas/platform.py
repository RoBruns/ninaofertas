"""Schemas publicos de plataformas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class PlatformResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    is_active: bool
    capabilities: dict[str, Any]


class PlatformSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
