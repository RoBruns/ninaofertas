"""Chave de produto estável entre links curtos diferentes."""

from __future__ import annotations

from core.product_key import chave_produto
from worker.mirror_dedup import pode_enviar_produto, vencedores_do_lote


def test_mlb_igual_em_dois_links():
    a = chave_produto(
        "https://www.mercadolivre.com.br/kit-principia/p/MLB53618239",
        loja="mercado livre",
    )
    b = chave_produto(
        "https://www.mercadolivre.com.br/outro-titulo/p/MLB53618239?matt_tool=x",
        loja="mercado livre",
    )
    assert a == "ml:MLB53618239"
    assert a == b


def test_shopee_shop_item():
    assert (
        chave_produto(
            "https://shopee.com.br/product/123456/789012",
            loja="shopee",
        )
        == "shopee:123456.789012"
    )
    assert (
        chave_produto(
            "https://shopee.com.br/Panela-Antiaderente-i.123456.789012",
            loja="shopee",
        )
        == "shopee:123456.789012"
    )


def test_amazon_asin():
    assert (
        chave_produto(
            "https://www.amazon.com.br/dp/B08N5WRWNW",
            loja="amazon",
        )
        == "amz:B08N5WRWNW"
    )


def test_lote_fica_com_menor_preco():
    vencedores = vencedores_do_lote(
        [
            ("a", "ml:MLB1", 100.0),
            ("b", "ml:MLB1", 80.0),
            ("c", "ml:MLB2", 50.0),
        ]
    )
    assert vencedores == {"b", "c"}


def test_dedup_bloqueia_sem_queda(monkeypatch):
    class _Envio:
        enviado_em = object()
        preco_enviado = 100.0

    monkeypatch.setattr(
        "worker.mirror_dedup.repositories.ultimo_envio_por_sku",
        lambda *_a, **_k: _Envio(),
    )
    monkeypatch.setattr(
        "worker.mirror_dedup.repositories._minutos_desde",
        lambda _quando: 30.0,
    )
    ok, motivo = pode_enviar_produto(
        session=None,  # type: ignore[arg-type]
        sku="ml:MLB1",
        loja="mercado livre",
        grupo="g@g.us",
        tenant_id=__import__("uuid").uuid4(),
        preco=95.0,
        dedup_horas=24,
        queda_minima_pct=15.0,
    )
    assert not ok
    assert motivo == "duplicado_produto"


def test_dedup_libera_com_queda(monkeypatch):
    class _Envio:
        enviado_em = object()
        preco_enviado = 100.0

    monkeypatch.setattr(
        "worker.mirror_dedup.repositories.ultimo_envio_por_sku",
        lambda *_a, **_k: _Envio(),
    )
    monkeypatch.setattr(
        "worker.mirror_dedup.repositories._minutos_desde",
        lambda _quando: 30.0,
    )
    ok, motivo = pode_enviar_produto(
        session=None,  # type: ignore[arg-type]
        sku="ml:MLB1",
        loja="mercado livre",
        grupo="g@g.us",
        tenant_id=__import__("uuid").uuid4(),
        preco=80.0,
        dedup_horas=24,
        queda_minima_pct=15.0,
    )
    assert ok
    assert "caiu" in motivo
