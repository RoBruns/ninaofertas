"""Caracterização dos filtros atuais de config.json."""
from __future__ import annotations

import pytest

from core.platforms.base import OfertaCapturada
from core.config_provider import usar_bot_runtime
from tests.runtime_helpers import runtime_do_config
from worker.channels import load_filtros
from worker.filters import _contem_alguma, passa_nos_filtros


@pytest.mark.parametrize(("termo", "texto", "esperado"), [
    ("unha", "Kit Unhas Gel", True),
    ("pote", "Potes Herméticos", True),
    ("natal", "Natalina", True),
    ("automot", "Automotivo", True),
    ("air fryer", "Fritadeira Air Fryer 4L", True),
    ("anel", "Canela em pó", False),
    ("colar", "Material Escolar", False),
    ("mesa", "Mesa de Cabeceira", True),
    ("p/ carro", "Suporte p/ carro", True),
    ("pisca-pisca", "Luz pisca-pisca natalina", True),
    ("[gel]", "Unhas [gel]", True),
    ("carro+", "Kit carro+", True),
    ("decoracao", "Kit DECORAÇÃO", True),
    ("mesa", "123mesa", False),
])
def test_termos_comecam_em_fronteira_de_palavra(termo, texto, esperado):
    assert bool(_contem_alguma(texto, [termo])) is esperado


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
