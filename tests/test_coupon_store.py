import pytest

from core.coupon_store import loja_da_mensagem, normalizar_loja, resumo_da_mensagem


@pytest.mark.parametrize(
    ("texto", "loja"),
    [
        ("Cupom ABC10 https://shopee.com.br/product/1/2", "shopee"),
        ("CORRE novo Cupom Mercado Livre: MELI20", "mercadolivre"),
        ("Cupom no ML: VOLTA15 acima de 99", "mercadolivre"),
        ("Cupom Shopee SHOP25 só hoje", "shopee"),
        ("Cupom Amazon PRIME10", "amazon"),
        ("Cupom ALI10 olha ali embaixo", "outra"),
        ("Cupom RTX4060 na matéria", "outra"),
    ],
)
def test_loja_da_mensagem(texto: str, loja: str) -> None:
    assert loja_da_mensagem(texto) == loja


def test_resumo_tira_link_e_formatacao() -> None:
    assert resumo_da_mensagem("*Cupom* MELI20 https://meli.la/abc  agora") == "Cupom MELI20 agora"


def test_normalizar_loja_aliases() -> None:
    assert normalizar_loja("Mercado Livre") == "mercadolivre"
    assert normalizar_loja("Magalu") == "awin"
    assert normalizar_loja("Shopee BR") == "shopee"
    assert normalizar_loja(None) == "outra"
    assert normalizar_loja("Promobit") == "outra"
