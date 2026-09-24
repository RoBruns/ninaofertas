"""O dashboard nunca pede page_size acima do máximo que a API aceita.

Os testes do frontend simulam a API, então um page_size fora do limite só
aparecia rodando de verdade (422 em todas as listas de seleção).
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAMADA = re.compile(r"api\.GET\('(?P<path>[^']+)'(?P<resto>.{0,300}?)\)\s*[,\]);]", re.S)
PAGE_SIZE = re.compile(r"page_size:\s*(\d+)")


def _maximos() -> dict[str, int]:
    spec = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    maximos = {}
    for path, operacoes in spec["paths"].items():
        for parametro in operacoes.get("get", {}).get("parameters", []):
            if parametro["name"] == "page_size":
                maximos[path] = parametro["schema"]["maximum"]
    return maximos


def test_page_size_do_dashboard_cabe_no_limite_da_api() -> None:
    maximos = _maximos()
    usados = []
    for arquivo in (ROOT / "dashboard" / "src").rglob("*.tsx"):
        if arquivo.name.endswith(".test.tsx"):
            continue
        for chamada in CHAMADA.finditer(arquivo.read_text(encoding="utf-8")):
            tamanho = PAGE_SIZE.search(chamada["resto"])
            if tamanho:
                usados.append((arquivo.name, chamada["path"], int(tamanho[1])))

    assert usados, "nenhuma chamada paginada encontrada: o regex quebrou"
    excedentes = [
        f"{nome}: {path} page_size={valor} > {maximos[path]}"
        for nome, path, valor in usados
        if valor > maximos[path]
    ]
    assert not excedentes, excedentes
