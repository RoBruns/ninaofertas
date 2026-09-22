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


def test_configs_dos_dois_canais_sao_lidos_da_raiz() -> None:
    from worker.channels import load_filtros, usar_canal

    with usar_canal("achadinhos"):
        assert load_filtros()["nicho"] == "casa"
    with usar_canal("auto"):
        assert load_filtros()["nicho"] == "auto"
