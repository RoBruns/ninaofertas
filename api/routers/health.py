"""Health check publico e sem dados sensiveis."""

from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
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


class HeartbeatRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=100)
    bots_running: list[UUID] = Field(default_factory=list, max_length=100)


@router.get("/health", response_model=HealthResponse)
def health(session: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
        worker_last_seen = session.scalar(select(func.max(AutomationRun.started_at)))
    except SQLAlchemyError:
        session.rollback()
        return HealthResponse(status="degraded", db="error", worker_last_seen=None)
    return HealthResponse(status="ok", db="ok", worker_last_seen=worker_last_seen)


@router.post("/internal/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
def heartbeat(
    _payload: HeartbeatRequest,
    worker_token: Annotated[str | None, Header(alias="X-Worker-Token")] = None,
) -> Response:
    expected = os.getenv("WORKER_TOKEN")
    if not expected or not worker_token or not secrets.compare_digest(worker_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker token invalido")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
