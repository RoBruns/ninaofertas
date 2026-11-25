"""Cartão clicável: o link da loja traz a foto."""

from __future__ import annotations

import base64

import httpx
import pytest
from starlette.requests import Request

from api.errors import APIError
from api.ratelimit import limiter
from api.routers.link_preview import abrir_previa
from core.link_unfurl import eh_robo_previa, emitir_token, loja_com_cartao
from worker import channels, whatsapp

_CHAVE = base64.b64encode(b"k" * 32).decode()
_LINK = "https://meli.la/2C3T4JV"
_FOTO = "https://http2.mlstatic.com/D_NQ_NP_807397-MLA79770084007_102024-F.jpg"
_JPEG_B64 = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 64).decode()


def _stub_jpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cartão baixa a CDN e reencoda; nos testes devolvemos JPEG fixo."""
    monkeypatch.setattr(whatsapp, "_baixar_bytes_midia", lambda _url: b"raw-img")
    monkeypatch.setattr(whatsapp, "_jpeg_base64", lambda _raw: _JPEG_B64)


def _pedido(user_agent: str) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/api/p/x",
        "raw_path": b"/api/p/x",
        "query_string": b"",
        "headers": [(b"user-agent", user_agent.encode())],
        "client": ("203.0.113.8", 443),
        "server": ("test", 443),
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _chave_e_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDENTIALS_KEY", _CHAVE)
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "https://nina.example/api")
    limiter.clear()


def test_shopee_e_mercado_livre_usam_o_link_da_loja() -> None:
    assert loja_com_cartao("Shopee")
    assert loja_com_cartao("Mercado Livre")
    assert not loja_com_cartao("Amazon")
    assert not loja_com_cartao("Magalu")


def test_robo_ve_a_foto_e_pessoa_cai_no_afiliado() -> None:
    token = emitir_token(_LINK, "Fogão 4 bocas", _FOTO)
    assert token is not None
    robo = abrir_previa(token, _pedido("googlebot"))
    assert robo.status_code == 200
    assert _FOTO.encode() in robo.body
    assert b"Fog" in robo.body
    pessoa = abrir_previa(token, _pedido("Mozilla/5.0 (Linux; Android 14) Chrome WhatsApp/2.23"))
    assert pessoa.status_code == 302
    assert pessoa.headers["location"] == _LINK


def test_token_adulterado_nao_abre() -> None:
    token = emitir_token(_LINK, "Fogão", _FOTO)
    assert token is not None
    with pytest.raises(APIError) as erro:
        abrir_previa(token[:-1] + ("a" if token[-1] != "a" else "b"), _pedido("googlebot"))
    assert erro.value.status_code == 404


def test_nao_assina_destino_fora_da_shopee() -> None:
    assert emitir_token("https://evil.example/phish", "Oferta", _FOTO) is None


def test_user_agent_do_whatsapp_e_robo_e_o_navegador_nao() -> None:
    assert eh_robo_previa("WhatsApp/2.23.20.0 A")
    assert eh_robo_previa("Mozilla/5.0 (compatible; Googlebot/2.1)")
    assert not eh_robo_previa("Mozilla/5.0 (Linux; Android 14) Chrome WhatsApp/2.23")


class _Client:
    calls: list[tuple[str, dict[str, object]]] = []

    def __init__(self, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, *, json: dict[str, object], headers: dict[str, str]) -> httpx.Response:
        self.calls.append((url, json))
        return httpx.Response(200, json={"ok": True})


def test_envio_com_previa_nao_anexa_foto(monkeypatch: pytest.MonkeyPatch) -> None:
    _Client.calls = []
    monkeypatch.setattr(httpx, "Client", _Client)
    _stub_jpeg(monkeypatch)
    monkeypatch.setattr(channels, "grupo_whatsapp", lambda: "grupo@g.us")
    monkeypatch.setattr(channels, "instancia_evolution", lambda: "instancia")
    assert whatsapp.enviar_mensagem(
        f"oferta {_LINK}",
        imagem=_FOTO,
        grupo="grupo@g.us",
        previa_do_link=True,
        previa_imagem=_FOTO,
    )
    url, payload = _Client.calls[0]
    assert url.endswith("/message/sendText/instancia")
    cartao = payload["linkPreview"]
    assert isinstance(cartao, dict)
    assert "thumbnailUrl" not in cartao
    assert cartao["thumbnailBase64"] == _JPEG_B64
    assert cartao["canonicalUrl"] == _LINK
    assert "title" not in cartao
    assert "description" not in cartao
    assert payload["text"] == f"oferta {_LINK}"
    assert "mediatype" not in payload


@pytest.mark.parametrize("status_recusa", [400, 500])
def test_previa_recusada_anexa_a_foto(
    monkeypatch: pytest.MonkeyPatch, status_recusa: int
) -> None:
    class _Recusa:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> _Recusa:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(
            self, url: str, *, json: dict[str, object], headers: dict[str, str]
        ) -> httpx.Response:
            _Client.calls.append((url, json))
            status = status_recusa if len(_Client.calls) == 1 else 200
            return httpx.Response(status, text="VipsJpeg")

    _Client.calls = []
    monkeypatch.setattr(httpx, "Client", _Recusa)
    _stub_jpeg(monkeypatch)
    monkeypatch.setattr(channels, "grupo_whatsapp", lambda: "grupo@g.us")
    monkeypatch.setattr(channels, "instancia_evolution", lambda: "instancia")
    assert whatsapp.enviar_mensagem(
        f"oferta {_LINK}",
        imagem=_FOTO,
        grupo="grupo@g.us",
        previa_imagem=_FOTO,
    )
    assert isinstance(_Client.calls[0][1]["linkPreview"], dict)
    assert _Client.calls[1][0].endswith("/message/sendMedia/instancia")
    assert _Client.calls[1][1]["mediatype"] == "image"
    assert _Client.calls[1][1]["media"] == _JPEG_B64


def test_gif_de_aviso_do_ml_nao_vira_foto() -> None:
    assert whatsapp._placeholder_mercado_livre(_FOTO, "image/gif")
    assert not whatsapp._placeholder_mercado_livre(_FOTO, "image/jpeg")
    assert not whatsapp._placeholder_mercado_livre(
        "https://down-br.img.susercontent.com/file/x", "image/gif"
    )


def test_cdn_gif_vira_jpeg_no_cartao(monkeypatch: pytest.MonkeyPatch) -> None:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (2, 2), color=(20, 120, 200)).save(buf, format="GIF")
    monkeypatch.setattr(whatsapp, "_baixar_bytes_midia", lambda _url: buf.getvalue())
    cartao = whatsapp._cartao_so_foto(f"oferta {_LINK}", _FOTO)
    assert cartao is not None
    assert base64.b64decode(cartao["thumbnailBase64"])[:3] == b"\xff\xd8\xff"
