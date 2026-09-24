from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from worker import main as worker_main


def test_primeiro_ciclo_usa_instante_com_fuso_mesmo_se_relogio_local_for_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker_main.relogio,
        "agora_br",
        lambda: datetime.now(timezone.utc).astimezone(worker_main.relogio.BR),
    )
    scheduler = BackgroundScheduler(timezone=worker_main.relogio.BR)
    scheduler.start(paused=True)
    try:
        worker_main._registrar_jobs(scheduler)
        primeira_execucao = scheduler.get_job("bots-db").next_run_time
        diferenca = abs((primeira_execucao - datetime.now(timezone.utc)).total_seconds())
        assert diferenca < 5
    finally:
        scheduler.shutdown(wait=False)


def test_heartbeat_independente_roda_a_cada_60s_sem_bots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recebidos: list[list] = []
    monkeypatch.setattr(worker_main, "bots_ativos", lambda: [])
    monkeypatch.setattr(worker_main.telemetry, "heartbeat", lambda ids: recebidos.append(ids))
    scheduler = BackgroundScheduler(timezone=worker_main.relogio.BR)
    scheduler.start(paused=True)
    try:
        worker_main._registrar_jobs(scheduler)
        job = scheduler.get_job("heartbeat")
        assert job.trigger.interval.total_seconds() == 60
        assert abs((job.next_run_time - datetime.now(timezone.utc)).total_seconds()) < 5
        job.func()
    finally:
        scheduler.shutdown(wait=False)
    assert recebidos == [[]]


def test_heartbeat_envia_ids_dos_bots_rodaveis(monkeypatch: pytest.MonkeyPatch) -> None:
    bot_ids = [uuid4(), uuid4()]
    runtimes = [type("Runtime", (), {"id": bot_id})() for bot_id in bot_ids]
    recebidos: list[list] = []
    monkeypatch.setattr(worker_main, "bots_ativos", lambda: runtimes)
    monkeypatch.setattr(worker_main.telemetry, "heartbeat", lambda ids: recebidos.append(ids))

    worker_main._enviar_heartbeat()

    assert recebidos == [bot_ids]


def test_falha_no_heartbeat_nao_escapa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_main, "bots_ativos", lambda: [])
    monkeypatch.setattr(
        worker_main.telemetry,
        "heartbeat",
        lambda _ids: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    worker_main._enviar_heartbeat()
