"""Gate ADR-037: sem ENABLE_SCRAPER_DISCOVERY o ciclo de scraper não roda."""

from __future__ import annotations

import pytest

from core.discovery import scraper_discovery_enabled
from worker import monitor


def test_scraper_discovery_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_SCRAPER_DISCOVERY", raising=False)
    assert scraper_discovery_enabled() is False
    monkeypatch.setenv("ENABLE_SCRAPER_DISCOVERY", "1")
    assert scraper_discovery_enabled() is True


def test_monitor_ciclo_noop_quando_descoberta_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_SCRAPER_DISCOVERY", "0")
    chamado = {"n": 0}

    def _boom(*_a, **_k):
        chamado["n"] += 1
        raise AssertionError("não deveria executar o pipeline de scraper")

    monkeypatch.setattr(monitor, "_executar_ciclo", _boom)
    monitor.ciclo()
    assert chamado["n"] == 0
