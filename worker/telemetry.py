"""Telemetria best-effort do worker; nenhuma falha daqui interrompe envios."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import func, select

from core import db
from core.models import AutomationRun, Event
from worker.logger import logger


def iniciar_ciclo(bot_id: UUID | None, group_id: UUID | None = None) -> tuple[int | None, float]:
    started = time.monotonic()
    try:
        with db.get_session() as session:
            run = AutomationRun(
                bot_id=bot_id,
                kind="cycle",
                status="running",
                detail={"group_id": str(group_id)} if group_id else None,
            )
            session.add(run)
            session.flush()
            return run.id, started
    except Exception as exc:
        logger.debug(f"Telemetria indisponivel ao iniciar ciclo: {exc}")
        return None, started


def finalizar_ciclo(
    run_id: int | None,
    started: float,
    *,
    status: str,
    offers_found: int,
    offers_sent: int,
    error: str | None = None,
    baseline: bool = False,
) -> None:
    if run_id is None:
        return
    try:
        with db.get_session() as session:
            run = session.get(AutomationRun, run_id)
            if run is None:
                return
            run.kind = "baseline" if baseline else "cycle"
            run.status = status
            run.finished_at = datetime.now(timezone.utc)
            run.duration_ms = round((time.monotonic() - started) * 1000)
            run.offers_found = offers_found
            run.offers_sent = offers_sent
            run.error = error
    except Exception as exc:
        logger.debug(f"Telemetria indisponivel ao finalizar ciclo: {exc}")


def registrar_evento(
    event_type: str,
    message: str,
    *,
    bot_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    detail: dict | None = None,
    level: str = "error",
) -> None:
    try:
        with db.get_session() as session:
            session.add(
                Event(
                    bot_id=bot_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    level=level,
                    type=event_type,
                    message=message,
                    detail=detail,
                )
            )
    except Exception as exc:
        logger.debug(f"Telemetria indisponivel ao gravar evento {event_type}: {exc}")


def baseline_concluida(bot_id: UUID, alvo: int, group_id: UUID | None = None) -> bool:
    """Usa ciclos de baseline concluidos como progresso persistente."""
    try:
        with db.get_session() as session:
            query = select(func.count(AutomationRun.id)).where(
                AutomationRun.bot_id == bot_id,
                AutomationRun.kind == "baseline",
                AutomationRun.status == "success",
            )
            if group_id is not None:
                query = query.where(AutomationRun.detail["group_id"].as_string() == str(group_id))
            feitos = session.scalar(query)
        return int(feitos or 0) >= alvo
    except Exception as exc:
        logger.debug(f"Nao foi possivel consultar baseline persistente: {exc}")
        return False


def quantidade_baselines(bot_id: UUID, group_id: UUID | None = None) -> int:
    try:
        with db.get_session() as session:
            query = select(func.count(AutomationRun.id)).where(
                AutomationRun.bot_id == bot_id,
                AutomationRun.kind == "baseline",
                AutomationRun.status == "success",
            )
            if group_id is not None:
                query = query.where(AutomationRun.detail["group_id"].as_string() == str(group_id))
            value = session.scalar(query)
        return int(value or 0)
    except Exception as exc:
        logger.debug(f"Nao foi possivel consultar baseline persistente: {exc}")
        return 0


def heartbeat(bot_ids: list[UUID]) -> None:
    api_url = os.getenv("API_URL")
    worker_token = os.getenv("WORKER_TOKEN")
    if not api_url or not worker_token:
        return
    try:
        with httpx.Client(timeout=5.0) as client:
            client.post(
                f"{api_url.rstrip('/')}/api/internal/heartbeat",
                json={
                    "worker_id": os.getenv("WORKER_ID", "ninaofertas"),
                    "bots_running": [str(i) for i in bot_ids],
                },
                headers={"X-Worker-Token": worker_token},
            ).raise_for_status()
    except Exception as exc:
        logger.debug(f"Heartbeat indisponivel: {exc}")


__all__ = [
    "baseline_concluida",
    "finalizar_ciclo",
    "heartbeat",
    "iniciar_ciclo",
    "quantidade_baselines",
    "registrar_evento",
]
