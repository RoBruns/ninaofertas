"""Fixtures globais da suíte."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _liga_descoberta_por_scraper_nos_testes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Produção desliga o scraper (ADR-037); os testes do pipeline legado precisam dele."""
    monkeypatch.setenv("ENABLE_SCRAPER_DISCOVERY", "1")
