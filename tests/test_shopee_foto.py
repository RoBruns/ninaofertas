"""Logo da Shopee na prévia não vira foto; a API acha a foto do anúncio certo."""

from __future__ import annotations

import base64
from io import BytesIO

import httpx
import pytest
from PIL import Image, ImageDraw

from core import mirror_media
from core.platforms import shopee_api


def _png_b64(img: Image.Image) -> str:
    saida = BytesIO()
    img.save(saida, format="PNG")
    return base64.b64encode(saida.getvalue()).decode("ascii")


def test_logo_laranja_da_shopee_e_detectado() -> None:
    logo = Image.new("RGB", (300, 300), (238, 77, 45))
    desenho = ImageDraw.Draw(logo)
    desenho.rectangle((100, 90, 200, 210), fill=(255, 255, 255))
    assert mirror_media.eh_logo_shopee(_png_b64(logo))


def test_foto_de_produto_nao_e_logo() -> None:
    produto = Image.new("RGB", (300, 300), (245, 245, 245))
    desenho = ImageDraw.Draw(produto)
    desenho.rectangle((60, 80, 240, 220), fill=(230, 230, 235))
    desenho.rectangle((80, 120, 220, 140), fill=(40, 40, 50))
    assert not mirror_media.eh_logo_shopee(_png_b64(produto))


def _client_com(nodes: list[dict[str, object]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"productOfferV2": {"nodes": nodes}}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_foto_por_titulo_escolhe_o_mesmo_modelo() -> None:
    nodes = [
        {
            "productName": "Ar Condicionado Split Gree 12000 BTUs",
            "imageUrl": "https://down-br.img.susercontent.com/file/outro",
            "priceMin": "1900",
        },
        {
            "productName": "Ar Condicionado Split HQ Hi Wall Inverter 12.000 BTU/h VIHT12CO3S2S713",
            "imageUrl": "https://down-br.img.susercontent.com/file/certo",
            "priceMin": "1965.21",
        },
    ]
    with _client_com(nodes) as client:
        url = shopee_api.foto_por_titulo(
            client,
            "Ar Condicionado Split HQ Hi Wall Inverter 12.000 BTU/h VIHT12CO3S2S713 220V: "
            "conforto na medida certa",
            app_id="app",
            secret="seg",
            preco=1965.21,
        )
    assert url == "https://down-br.img.susercontent.com/file/certo"


def test_foto_por_titulo_sem_produto_parecido_fica_sem_foto() -> None:
    nodes = [
        {
            "productName": "Capa de celular infantil",
            "imageUrl": "https://down-br.img.susercontent.com/file/capa",
            "priceMin": "19.90",
        }
    ]
    with _client_com(nodes) as client:
        assert (
            shopee_api.foto_por_titulo(
                client,
                "Ar Condicionado Split HQ VIHT12CO3S2S713",
                app_id="app",
                secret="seg",
                preco=1965.21,
            )
            is None
        )


def test_foto_por_titulo_preco_muito_diferente_e_recusado() -> None:
    nodes = [
        {
            "productName": "Ar Condicionado Split HQ VIHT12CO3S2S713",
            "imageUrl": "https://down-br.img.susercontent.com/file/peca",
            "priceMin": "89.90",
        }
    ]
    with _client_com(nodes) as client:
        assert (
            shopee_api.foto_por_titulo(
                client,
                "Ar Condicionado Split HQ VIHT12CO3S2S713",
                app_id="app",
                secret="seg",
                preco=1965.21,
            )
            is None
        )


def test_foto_shopee_tenta_de_novo_depois_do_system_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.platforms import shopee
    from worker import mirror

    chamadas: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(1)
        if len(chamadas) == 1:
            return httpx.Response(200, json={"errors": [{"message": "error [10000]: System Error"}]})
        nodes = [
            {
                "productName": "Electrolux ES5GB Inverter",
                "imageUrl": "https://down-br.img.susercontent.com/file/es5gb",
                "priceMin": "2500",
            }
        ]
        return httpx.Response(200, json={"data": {"productOfferV2": {"nodes": nodes}}})

    cliente_real = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **_kw: cliente_real(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(shopee, "credenciais_shopee_do_bot", lambda: (None, "app", "seg"))
    monkeypatch.setattr(mirror.time, "sleep", lambda _s: None)
    url = mirror._foto_shopee_api("Electrolux ES5GB: sua cozinha moderna!", 2500.0)
    assert url == "https://down-br.img.susercontent.com/file/es5gb"
    assert len(chamadas) == 2


@pytest.mark.parametrize("titulo", ["", "Ar"])
def test_foto_por_titulo_curto_nao_busca(titulo: str) -> None:
    with _client_com([]) as client:
        assert shopee_api.foto_por_titulo(client, titulo, app_id="a", secret="s") is None
