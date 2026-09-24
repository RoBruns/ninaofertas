# ruff: noqa: F401, F811

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.routers import health
from tests.test_api import client, session_factory  # noqa: F401


@pytest.fixture(autouse=True)
def clear_worker_heartbeat() -> Generator[None, None, None]:
    health._clear_worker_heartbeat()
    yield
    health._clear_worker_heartbeat()


def test_heartbeat_valido_atualiza_health(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_TOKEN", "segredo-de-teste")
    bot_id = uuid4()
    before = datetime.now(timezone.utc)

    response = client.post(
        "/api/internal/heartbeat",
        json={"worker_id": "worker-1", "bots_running": [str(bot_id)]},
        headers={"X-Worker-Token": "segredo-de-teste"},
    )
    after = datetime.now(timezone.utc)

    assert response.status_code == 204, response.text
    last_seen = datetime.fromisoformat(client.get("/api/health").json()["worker_last_seen"])
    assert before <= last_seen <= after
    stored = health.get_worker_heartbeat()
    assert stored is not None
    assert stored.worker_id == "worker-1"
    assert stored.bots_running == (bot_id,)


def test_heartbeat_invalido_nao_altera_health(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKER_TOKEN", "segredo-de-teste")
    valid = {"worker_id": "worker-valido", "bots_running": []}
    assert (
        client.post(
            "/api/internal/heartbeat",
            json=valid,
            headers={"X-Worker-Token": "segredo-de-teste"},
        ).status_code
        == 204
    )
    original = client.get("/api/health").json()["worker_last_seen"]

    invalid = client.post(
        "/api/internal/heartbeat",
        json={"worker_id": "worker-invalido", "bots_running": []},
        headers={"X-Worker-Token": "token-incorreto"},
    )

    assert invalid.status_code == 401
    assert client.get("/api/health").json()["worker_last_seen"] == original
    stored = health.get_worker_heartbeat()
    assert stored is not None
    assert stored.worker_id == "worker-valido"


def test_health_sem_heartbeat_e_sem_runs_retorna_null(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200, response.text
    assert response.json()["worker_last_seen"] is None
