"""Helpers de fontes sem rede."""

from xml.etree.ElementTree import fromstring

from core.feed_catalog import DEFAULT_FEED_SOURCES
from core.feed_collect import CollectedOffer, _montar_body, _rss_image, _vale_no_catalogo
from core.link_parser import extrair_links_oferta


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


def test_rss_image_enclosure_e_img() -> None:
    item = fromstring(
        "<item><enclosure url='https://cdn.ex/a.jpg' type='image/jpeg'/>"
        "<description>&lt;img src=\"https://cdn.ex/b.png\" /&gt;</description></item>"
    )
    assert _rss_image(item, "") == "https://cdn.ex/a.jpg"
    item2 = fromstring("<item><description></description></item>")
    assert _rss_image(item2, '<p><img src="https://cdn.ex/c.webp"/></p>') == "https://cdn.ex/c.webp"
