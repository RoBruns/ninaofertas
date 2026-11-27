from core.coupon_store import normalizar_loja


def test_normalizar_loja_aliases() -> None:
    assert normalizar_loja("Mercado Livre") == "mercadolivre"
    assert normalizar_loja("Magalu") == "awin"
    assert normalizar_loja("Shopee BR") == "shopee"
    assert normalizar_loja(None) == "outra"
    assert normalizar_loja("Promobit") == "outra"
