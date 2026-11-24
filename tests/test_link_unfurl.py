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
    monkeypatch.setattr(channels, "grupo_whatsapp", lambda: "grupo@g.us")
    monkeypatch.setattr(channels, "instancia_evolution", lambda: "instancia")
    assert whatsapp.enviar_mensagem(
        f"oferta {_LINK}",
        imagem=_FOTO,
        grupo="grupo@g.us",
        previa_do_link=True,
    )
    url, payload = _Client.calls[0]
    assert url.endswith("/message/sendText/instancia")
    assert payload["linkPreview"] is True
    assert payload["text"] == f"oferta {_LINK}"
    assert "mediatype" not in payload
