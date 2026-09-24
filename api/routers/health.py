"""Health check publico e sem dados sensiveis."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
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


@dataclass(frozen=True)
class WorkerHeartbeat:
    received_at: datetime
    worker_id: str
    bots_running: tuple[UUID, ...]


# A API roda em processo unico; este estado nao e compartilhado entre processos.
_heartbeat_lock = Lock()
_worker_heartbeat: WorkerHeartbeat | None = None


def get_worker_heartbeat() -> WorkerHeartbeat | None:
    with _heartbeat_lock:
        return _worker_heartbeat


def _clear_worker_heartbeat() -> None:
    """Limpa o estado em memoria para manter os testes isolados."""
    global _worker_heartbeat
    with _heartbeat_lock:
        _worker_heartbeat = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]
    worker_last_seen: datetime | None


class HeartbeatRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=100)
    bots_running: list[UUID] = Field(default_factory=list, max_length=100)


@router.get("/health", response_model=HealthResponse)
def health(session: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    heartbeat_seen_at = (
        heartbeat.received_at if (heartbeat := get_worker_heartbeat()) is not None else None
    )
    try:
        session.execute(text("SELECT 1"))
        latest_run = session.scalar(select(func.max(AutomationRun.started_at)))
    except SQLAlchemyError:
        session.rollback()
        return HealthResponse(status="degraded", db="error", worker_last_seen=heartbeat_seen_at)
    worker_last_seen = max(
        (seen_at for seen_at in (heartbeat_seen_at, latest_run) if seen_at is not None),
        default=None,
    )
    return HealthResponse(status="ok", db="ok", worker_last_seen=worker_last_seen)


@router.post("/internal/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
def heartbeat(
    payload: HeartbeatRequest,
    worker_token: Annotated[str | None, Header(alias="X-Worker-Token")] = None,
) -> Response:
    global _worker_heartbeat
    expected = os.getenv("WORKER_TOKEN")
    if not expected or not worker_token or not secrets.compare_digest(worker_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker token invalido")
    received = WorkerHeartbeat(
        received_at=datetime.now(timezone.utc),
        worker_id=payload.worker_id,
        bots_running=tuple(payload.bots_running),
    )
    with _heartbeat_lock:
        _worker_heartbeat = received
    return Response(status_code=status.HTTP_204_NO_CONTENT)
