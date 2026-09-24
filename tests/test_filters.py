"""Caracterização dos filtros atuais de config.json."""
from __future__ import annotations

import pytest

from core.platforms.base import OfertaCapturada
from core.config_provider import usar_bot_runtime
from tests.runtime_helpers import runtime_do_config
from worker.channels import load_filtros
from worker.filters import passa_nos_filtros


def _oferta(**alteracoes) -> OfertaCapturada:
    dados = {
        "nome": "Air fryer para cozinha",
        "preco": 100.0,
        "preco_anterior": 150.0,
        "desconto": 33.3,
        "loja": "Shopee",
        "url": "https://example.test/oferta",
        "categoria": "casa",
    }
    dados.update(alteracoes)
    return OfertaCapturada(**dados)


@pytest.fixture
def filtros_reais() -> dict:
    # config.json chega ao worker importado pelo seed como settings do bot.
    with usar_bot_runtime(runtime_do_config("config.json")):
        return load_filtros()


@pytest.mark.parametrize(
    ("oferta", "esperado", "motivo"),
    [
        (_oferta(preco=5001.0), False, "acima do máximo"),
        (_oferta(desconto=14.9), False, "abaixo do mínimo"),
        (
            _oferta(nome="Amortecedor automotivo para carro"),
            False,
            "fora do foco",
        ),
        (_oferta(nome="Vestido infantil feminino"), False, "infantil"),
        (
            _oferta(nome="Boneco colecionador com vaso decorativo"),
            True,
            "",
        ),
        (
            _oferta(nome="Cupom de desconto", preco=0.0, desconto=None, categoria="cupom"),
            True,
            "",
        ),
        (
            _oferta(nome="Campanha de cozinha", categoria="campanha"),
            False,
            "campanhas desabilitadas",
        ),
        (_oferta(loja="Amazon"), False, "lista permitida"),
    ],
)
def test_passa_nos_filtros_reais(
    filtros_reais: dict,
    oferta: OfertaCapturada,
    esperado: bool,
    motivo: str,
) -> None:
    passou, explicacao = passa_nos_filtros(oferta, filtros_reais)

    assert passou is esperado
    assert motivo in explicacao
