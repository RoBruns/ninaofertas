"""Runtime de bot montado como o worker o monta a partir do seed.

O seed importa config.json/config.auto.json para settings de bot; o worker lê
esses settings (ADR-020). Os testes de filtro usam o mesmo caminho.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from core.bot_settings import BotSettings
from core.config_provider import BotRuntime
from core.seed import _settings_from_config

ROOT = Path(__file__).resolve().parents[1]


def runtime_do_config(arquivo: str, *, grupo: str = "grupo@g.us") -> BotRuntime:
    config = json.loads((ROOT / arquivo).read_text(encoding="utf-8"))
    return BotRuntime(
        id=uuid4(),
        slug=Path(arquivo).stem.replace(".", "-"),
        nome=arquivo,
        niche_slug=str(config.get("nicho")),
        phone_number="5511999990000",
        evolution_instance="instancia-teste",
        group_ids=(grupo,),
        settings=BotSettings.model_validate(_settings_from_config(config)),
        account_ids=(),
    )
