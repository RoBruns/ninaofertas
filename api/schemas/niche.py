"""Schemas de nichos configuraveis."""

from pydantic import BaseModel, Field


class NicheCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)


class NicheUpdate(BaseModel):
    slug: str | None = Field(
        default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=100
    )
    name: str | None = Field(default=None, min_length=1, max_length=200)


class NicheResponse(BaseModel):
    id: int
    slug: str
    name: str
