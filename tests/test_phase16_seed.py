import json
from pathlib import Path

from core.seed import _settings_from_config
from worker.formatter import TEMPLATE_PADRAO


def test_config_atual_vira_silencio_e_template_curto() -> None:
    config = json.loads(Path("config.json").read_text(encoding="utf-8"))
    settings = _settings_from_config(config)
    assert settings["schedule"]["quiet_hours"] == {"start": "00:00", "end": "08:00"}
    assert config["mensagem_template"] == TEMPLATE_PADRAO


def test_seed_aceita_quiet_hours_explicito_e_horas_iguais() -> None:
    explicit = _settings_from_config(
        {"quiet_hours": {"start": "12:00", "end": "12:00"}}
    )
    assert explicit["schedule"]["quiet_hours"] == {"start": "12:00", "end": "12:00"}
