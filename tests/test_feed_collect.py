"""Helpers de fontes sem rede."""

from xml.etree.ElementTree import fromstring

import pytest

from core.feed_catalog import DEFAULT_FEED_SOURCES
from core.feed_collect import CollectedOffer, _montar_body, _rss_image, _vale_no_catalogo
from core.link_parser import extrair_links_oferta
from tests.test_api import add_user


def test_catalogo_tem_promobit() -> None:
    slugs = {s.slug for s in DEFAULT_FEED_SOURCES}
    assert "promobit" in slugs
    assert any(s.kind == "rss" for s in DEFAULT_FEED_SOURCES)


def test_body_gera_link_marketplace() -> None:
    offer = CollectedOffer(
        external_id="1",
        title="Air fryer",
        url="https://www.mercadolivre.com.br/air/p/MLB123",
        price=199.9,
        price_old=299.0,
        coupon="SUPER",
        store_label="Loja X",
        sendable=True,
    )
    body = _montar_body(offer, "Promobit")
    assert "Cupom: SUPER" in body
    assert extrair_links_oferta(body)


def test_catalogo_exige_preco_e_imagem() -> None:
    assert not _vale_no_catalogo(
        CollectedOffer(external_id="1", title="Notícia", url="https://x.com/a", price=None)
    )
    assert not _vale_no_catalogo(
        CollectedOffer(
            external_id="1",
            title="Sem foto",
            url="https://x.com/a",
            price=49.9,
            image=None,
        )
    )
    assert _vale_no_catalogo(
        CollectedOffer(
            external_id="1",
            title="Ok",
            url="https://x.com/a",
            price=49.9,
            image="https://cdn.ex/a.jpg",
        )
    )


def test_rss_so_registra_cupom_com_link_de_loja(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core import feed_collect
    from core.models import CouponRadar, FeedSource

    admin = add_user(session_factory, email="rss-cupom@nina.test", role="admin")
    ofertas = [
        CollectedOffer(
            external_id="blog",
            title="Melhor placa de vídeo",
            url="https://www.adrenaline.com.br/hardware/rtx",
            coupon="RTX4060",
        ),
        CollectedOffer(
            external_id="loja",
            title="Fone na Shopee",
            url="https://shopee.com.br/product/1/2",
            coupon="SHOP25",
        ),
    ]
    monkeypatch.setattr(feed_collect, "coletar_rss", lambda _source: ofertas)
    with session_factory.begin() as session:
        fonte = FeedSource(
            owner_id=admin.tenant_id,
            slug="adrenaline",
            name="Adrenaline",
            kind="rss",
            url="https://www.adrenaline.com.br/feed/",
            enabled=True,
        )
        session.add(fonte)
        session.flush()
        feed_collect.coletar_fonte(session, fonte)
    with session_factory() as session:
        cupons = {c.code: c.store for c in session.query(CouponRadar).all()}
    assert cupons == {"SHOP25": "shopee"}


def test_rss_image_enclosure_e_img() -> None:
    item = fromstring(
        "<item><enclosure url='https://cdn.ex/a.jpg' type='image/jpeg'/>"
        "<description>&lt;img src=\"https://cdn.ex/b.png\" /&gt;</description></item>"
    )
    assert _rss_image(item, "") == "https://cdn.ex/a.jpg"
    item2 = fromstring("<item><description></description></item>")
    assert _rss_image(item2, '<p><img src="https://cdn.ex/c.webp"/></p>') == "https://cdn.ex/c.webp"
