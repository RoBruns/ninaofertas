"""Consulta das plataformas configuradas."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas.platform import PlatformResponse
from core.models import Platform, User

router = APIRouter(prefix="/platforms", tags=["platforms"])


@router.get("", response_model=list[PlatformResponse])
def list_platforms(
    _current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> list[Platform]:
    return list(session.scalars(select(Platform).order_by(Platform.name.asc())))
