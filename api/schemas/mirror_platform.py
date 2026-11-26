"""Schemas da allowlist de origem do espelho (plataforma)."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from core.mirror_sources import MAX_PLATFORM_SOURCE_GROUPS


class MirrorSourceGroupsResponse(BaseModel):
    """Allowlist ativa da Nina 1 + catálogo para o picker do dashboard."""

    selected: list[str]
    candidates: list[str]
    max_selected: int = MAX_PLATFORM_SOURCE_GROUPS
    source: str  # database | env | default
    pending_skipped: int = 0


class MirrorSourceGroupsUpdate(BaseModel):
    names: list[str] = Field(default_factory=list, max_length=MAX_PLATFORM_SOURCE_GROUPS)
    # True = limpa override do banco e volta ao env/padrão (pode passar de 3).
    reset_to_default: bool = False

    @field_validator("names")
    @classmethod
    def validate_names(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in value or []:
            name = " ".join(str(raw or "").split()).strip()
            if not name or len(name) > 120:
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(name)
        if len(out) > MAX_PLATFORM_SOURCE_GROUPS:
            raise ValueError(f"No máximo {MAX_PLATFORM_SOURCE_GROUPS} grupos")
        return out
