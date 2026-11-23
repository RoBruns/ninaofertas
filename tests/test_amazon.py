"""Amazon: etiqueta no /dp/ASIN e busca que para na verificação."""

from __future__ import annotations

import pytest

from core.platforms import affiliate
from core.platforms.amazon import (
    AmazonScraper,
    normalizar_tag_amazon,
    url_afiliada_amazon,
)
from worker.monitor import _loja_unica_do_ciclo

_TAG = "rdreviews04-20"
_HTML = """
<div data-component-type="s-search-result" data-asin="B0AMAZON01">
  <h2><a href="/dp/B0AMAZON01/ref=sr_1_1"><span>Air Fryer</span></a></h2>
  <span class="a-price"><span class="a-offscreen">R$ 299,90</span></span>
  <span class="a-price a-text-price"><span class="a-offscreen">R$ 399,90</span></span>
</div>
"""


def _conta(rastreio: str = _TAG):
    return (
        None,
        {"store_id": "achadinh0bed1-20", "tracking_id": rastreio},
        {"tracking_id": rastreio},
    )


def test_tag_aceita_os_ids_da_conta_e_recusa_outra_forma() -> None:
    assert normalizar_tag_amazon(" achadinh0bed1-20 ") == "achadinh0bed1-20"
    assert normalizar_tag_amazon(_TAG) == _TAG
    with pytest.raises(ValueError):
        normalizar_tag_amazon("sem-sufixo")
    assert url_afiliada_amazon("https://www.amazon.com.br/s?k=air", _TAG) is None
    assert url_afiliada_amazon("https://amzn.to/abc", _TAG) is None


def test_troca_tag_alheia_e_recusa_link_cru(monkeypatch) -> None:
    monkeypatch.setattr(affiliate, "_runtime_auth", lambda _slug: (None, _conta()))
    cru = "https://www.amazon.com.br/Air-Fryer/dp/B0AMAZON01/ref=sr_1_1?tag=outra-20"
    link = affiliate.garantir_afiliado("Amazon", cru)
    assert link == f"https://www.amazon.com.br/dp/B0AMAZON01?tag={_TAG}"
    assert affiliate.link_rastreado("Amazon", str(link))
    assert not affiliate.link_rastreado("Amazon", cru)
    assert not affiliate.link_rastreado("Amazon", "https://www.amazon.com.br/dp/B0AMAZON01")


def test_sem_etiqueta_o_link_cru_nao_e_enviavel(monkeypatch) -> None:
    monkeypatch.setattr(affiliate, "_runtime_auth", lambda _slug: (None, None))
    cru = "https://www.amazon.com.br/dp/B0AMAZON01"
    assert affiliate.garantir_afiliado("Amazon", cru) == cru
    assert not affiliate.link_rastreado("Amazon", cru)


def test_extrai_produto_do_html() -> None:
    ofertas = AmazonScraper()._extrair_produtos(_HTML)
    assert len(ofertas) == 1
    assert ofertas[0].nome == "Air Fryer"
    assert ofertas[0].preco == 299.9
    assert ofertas[0].preco_anterior == 399.9
    assert ofertas[0].url == "https://www.amazon.com.br/dp/B0AMAZON01"
    assert ofertas[0].sku == "B0AMAZON01"


def test_verificacao_interrompe_os_termos(monkeypatch) -> None:
    chamadas: list[str] = []

    class _Resposta:
        status_code = 200
        url = "https://www.amazon.com.br/errors/validateCaptcha"
        text = "validateCaptcha"

    class _Cliente:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url: str, params: object | None = None):
            chamadas.append(url)
            return _Resposta()

    monkeypatch.setattr("core.platforms.amazon.httpx.Client", lambda *_a, **_k: _Cliente())
    monkeypatch.setattr(
        "core.platforms.amazon.load_filtros",
        lambda: {"termos_busca": ["air fryer", "jogo de cama"]},
    )
    assert AmazonScraper().buscar() == []
    assert chamadas == ["https://www.amazon.com.br/s"]


def test_uma_loja_inclui_amazon_na_quarta_volta() -> None:
    plataformas = {"shopee", "mercadolivre", "magalu", "amazon"}
    assert _loja_unica_do_ciclo(4, plataformas) == "Amazon"
    assert _loja_unica_do_ciclo(3, {"shopee", "mercadolivre", "magalu"}) == "Magalu"
