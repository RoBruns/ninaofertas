"""O enfeite conserva o nome do item e não chama a OpenAI sem chave."""

from __future__ import annotations

import httpx
import pytest

from core.settings import settings
from worker import titulo_enfeite


class _Client:
    calls: list[dict[str, object]] = []

    def __init__(self, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
        _Client.calls.append({"url": url, "headers": headers, "json": json})
        texto = "Micro-ondas ME36S Efficient: praticidade e sabor inox! 🚀✨"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": texto}}]},
        )


def test_sem_chave_nao_chama(monkeypatch: pytest.MonkeyPatch) -> None:
    _Client.calls = []
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(httpx, "Client", _Client)
    assert titulo_enfeite.enfeitar_titulo("Micro-ondas ME36S Efficient") == (
        "Micro-ondas ME36S Efficient"
    )
    assert _Client.calls == []


def test_enfeite_conserva_o_nome(monkeypatch: pytest.MonkeyPatch) -> None:
    titulo_enfeite._CACHE.clear()
    _Client.calls = []
    monkeypatch.setattr(settings, "openai_api_key", "sk-teste")
    monkeypatch.setattr(httpx, "Client", _Client)
    saida = titulo_enfeite.enfeitar_titulo("Micro-ondas ME36S Efficient")
    assert saida.startswith("Micro-ondas ME36S Efficient:")
    assert "sk-teste" not in saida
    assert _Client.calls[0]["headers"]["Authorization"] == "Bearer sk-teste"
    de_novo = titulo_enfeite.enfeitar_titulo("Micro-ondas ME36S Efficient")
    assert de_novo == saida
    assert len(_Client.calls) == 1


def test_enfeite_que_troca_o_nome_e_descartado(monkeypatch: pytest.MonkeyPatch) -> None:
    titulo_enfeite._CACHE.clear()

    class _Troca(_Client):
        def post(
            self, url: str, *, headers: dict[str, str], json: dict[str, object]
        ) -> httpx.Response:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "Oferta imperdível na cozinha! ✨"}}]},
            )

    monkeypatch.setattr(settings, "openai_api_key", "sk-teste")
    monkeypatch.setattr(httpx, "Client", _Troca)
    assert titulo_enfeite.enfeitar_titulo("Micro-ondas ME36S Efficient") == (
        "Micro-ondas ME36S Efficient"
    )
