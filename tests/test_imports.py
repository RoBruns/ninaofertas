"""Testes de importação e limites entre os pacotes."""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import core
import worker


def test_todos_os_modulos_importam_sem_ciclo() -> None:
    pacotes = (core, worker)
    modulos = {
        info.name
        for pacote in pacotes
        for info in pkgutil.walk_packages(pacote.__path__, f"{pacote.__name__}.")
    }

    for modulo in sorted(modulos):
        importlib.import_module(modulo)


def test_fontes_ativas_continuam_sendo_tres() -> None:
    from worker.sources import FONTES

    assert len(FONTES) == 3


def test_core_nao_importa_worker() -> None:
    raiz_core = Path(core.__file__).parent
    for arquivo in raiz_core.rglob("*.py"):
        conteudo = arquivo.read_text(encoding="utf-8")
        assert "from worker" not in conteudo
        assert "import worker" not in conteudo


def test_configs_dos_dois_canais_viram_settings_de_bot() -> None:
    # Os JSON da raiz só alimentam o seed; o worker lê os settings do bot.
    from core.config_provider import usar_bot_runtime
    from tests.runtime_helpers import runtime_do_config
    from worker.channels import load_filtros

    import json
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    for arquivo, nicho in (("config.json", "casa"), ("config.auto.json", "auto")):
        bruto = json.loads((raiz / arquivo).read_text(encoding="utf-8"))
        runtime = runtime_do_config(arquivo)
        with usar_bot_runtime(runtime):
            filtros = load_filtros()
        # nicho e mensagem_template viram campos do bot; o resto segue nos settings.
        assert runtime.niche_slug == nicho
        assert set(bruto) - set(filtros) == {"nicho", "mensagem_template"}
        assert filtros["termos_busca"] == bruto["termos_busca"]
