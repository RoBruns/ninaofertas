"""Magalu: loja do Magazine Você, link reescrito e busca que para no bloqueio."""

from __future__ import annotations

import pytest

from core.platforms import affiliate
from core.platforms.magalu import MagaluScraper, normalizar_loja_magalu, url_afiliada_magalu
from worker.monitor import _loja_unica_do_ciclo

_PRODUTO = "https://www.magazineluiza.com.br/air-fryer/p/99/ab/cd/?a=1#x"
_HTML = """
<html><script id="__NEXT_DATA__">
{"products":[{"title":"Air Fryer","referenceId":"abc",
"path":"/air-fryer/p/123/ab/cd/","price":{"bestPrice":199.9,"price":299.9}}]}
</script></html>
"""


def _conta(loja: str = "magazinecasa"):
    return (None, {"store_slug": loja}, {"store_tag": loja})


def test_normaliza_url_da_loja_e_recusa_slug_curto() -> None:
    assert normalizar_loja_magalu("https://www.magazinevoce.com.br/MagazineCasa/") == "magazinecasa"
    assert normalizar_loja_magalu("magazinevoce.com.br/minha-loja") == "minha-loja"
    with pytest.raises(ValueError):
        normalizar_loja_magalu("a")
    assert url_afiliada_magalu("https://www.magazineluiza.com.br/", "magazinecasa") is None


def test_reescreve_produto_cru_e_recusa_sem_marca(monkeypatch) -> None:
    monkeypatch.setattr(affiliate, "_runtime_auth", lambda _slug: (None, _conta()))
    link = affiliate.garantir_afiliado("Magalu", _PRODUTO)
    assert link == "https://www.magazinevoce.com.br/magazinecasa/air-fryer/p/99/ab/cd"
    assert affiliate.link_rastreado("Magalu", str(link))
    assert not affiliate.link_rastreado("Magalu", _PRODUTO)


def test_troca_loja_alheia_pela_da_conta(monkeypatch) -> None:
    monkeypatch.setattr(affiliate, "_runtime_auth", lambda _slug: (None, _conta("minhaloja")))
    alheia = "https://www.magazinevoce.com.br/outrapessoa/tv/p/1/ab/cd/"
    link = affiliate.garantir_afiliado("Magalu", alheia)
    assert link == "https://www.magazinevoce.com.br/minhaloja/tv/p/1/ab/cd"
    assert not affiliate.link_rastreado("Magalu", alheia)


def test_sem_loja_o_link_cru_nao_e_enviavel(monkeypatch) -> None:
    monkeypatch.setattr(affiliate, "_runtime_auth", lambda _slug: (None, None))
    cru = "https://www.magazineluiza.com.br/tv/p/1/ab/cd/"
    assert affiliate.garantir_afiliado("Magalu", cru) == cru
    assert not affiliate.link_rastreado("Magalu", cru)


def test_extrai_produto_do_html() -> None:
    ofertas = MagaluScraper()._extrair_produtos(_HTML)
    assert len(ofertas) == 1
    assert ofertas[0].nome == "Air Fryer"
    assert ofertas[0].preco == 199.9
    assert ofertas[0].loja == "Magalu"
    assert ofertas[0].url.endswith("/air-fryer/p/123/ab/cd/")


def test_busca_403_interrompe_os_termos(monkeypatch) -> None:
    chamadas: list[str] = []

    class _Resposta:
        status_code = 403
        text = ""

    class _Cliente:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url: str):
            chamadas.append(url)
            return _Resposta()

    monkeypatch.setattr("core.platforms.magalu.httpx.Client", lambda *_a, **_k: _Cliente())
    monkeypatch.setattr(
        "core.platforms.magalu.load_filtros",
        lambda: {"termos_busca": ["air fryer", "jogo de cama", "tapete"]},
    )
    assert MagaluScraper().buscar() == []
    assert len(chamadas) == 1


def test_uma_loja_inclui_magalu_na_terceira_volta() -> None:
    plataformas = {"shopee", "mercadolivre", "magalu"}
    assert _loja_unica_do_ciclo(1, plataformas) == "Shopee"
    assert _loja_unica_do_ciclo(2, plataformas) == "Mercado Livre"
    assert _loja_unica_do_ciclo(3, plataformas) == "Magalu"
    assert _loja_unica_do_ciclo(4, plataformas) == "Shopee"


def test_uma_loja_sem_magalu_continua_shopee_e_ml() -> None:
    plataformas = {"shopee", "mercadolivre"}
    assert _loja_unica_do_ciclo(1, plataformas) == "Shopee"
    assert _loja_unica_do_ciclo(2, plataformas) == "Mercado Livre"
