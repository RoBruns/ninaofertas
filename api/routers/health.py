"""Health check publico e sem dados sensiveis."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.deps import get_db
from core.models import AutomationRun

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]
    worker_last_seen: datetime | None


@router.get("/health", response_model=HealthResponse)
def health(session: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
        worker_last_seen = session.scalar(select(func.max(AutomationRun.started_at)))
    except SQLAlchemyError:
        session.rollback()
        return HealthResponse(status="degraded", db="error", worker_last_seen=None)
    return HealthResponse(status="ok", db="ok", worker_last_seen=worker_last_seen)
