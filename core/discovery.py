"""Gate da descoberta por scraper/API — hoje o produto opera só no espelho."""

from __future__ import annotations

import os


def scraper_discovery_enabled() -> bool:
    """Scraper/API de ofertas só liga com ENABLE_SCRAPER_DISCOVERY=1.

    Padrão desligado (ADR-037): o worker publica só o que a Nina 1 espelha.
    Testes ligam a flag via conftest.
    """
    raw = (os.getenv("ENABLE_SCRAPER_DISCOVERY") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}
