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
    assert titulo_enfeite.enfeitar_titulo(
        "Micro-ondas ME36S Efficient", "Micro-ondas ME36S Efficient"
    ) == "Micro-ondas ME36S Efficient"
    assert _Client.calls == []


def test_enfeite_conserva_o_nome(monkeypatch: pytest.MonkeyPatch) -> None:
    titulo_enfeite._CACHE.clear()
    _Client.calls = []
    monkeypatch.setattr(settings, "openai_api_key", "sk-teste")
    monkeypatch.setattr(httpx, "Client", _Client)
    saida = titulo_enfeite.enfeitar_titulo(
        "Micro-ondas ME36S Efficient", "Micro-ondas ME36S Efficient"
    )
    assert saida.startswith("Micro-ondas ME36S Efficient:")
    assert "sk-teste" not in saida
    assert _Client.calls[0]["headers"]["Authorization"] == "Bearer sk-teste"
    de_novo = titulo_enfeite.enfeitar_titulo(
        "Micro-ondas ME36S Efficient", "Micro-ondas ME36S Efficient"
    )
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
    assert titulo_enfeite.enfeitar_titulo(
        "Micro-ondas ME36S Efficient", "COZINHA MAIS PRÁTICA"
    ) == "Micro-ondas ME36S Efficient"


def test_copia_do_titulo_do_grupo_e_descartada(monkeypatch: pytest.MonkeyPatch) -> None:
    titulo_enfeite._CACHE.clear()

    class _Copia(_Client):
        def post(
            self, url: str, *, headers: dict[str, str], json: dict[str, object]
        ) -> httpx.Response:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "Micro-ondas ME36S Efficient"}}]},
            )

    monkeypatch.setattr(settings, "openai_api_key", "sk-teste")
    monkeypatch.setattr(httpx, "Client", _Copia)
    assert titulo_enfeite.enfeitar_titulo(
        "Micro-ondas ME36S Efficient", "Micro-ondas ME36S Efficient"
    ) == "Micro-ondas ME36S Efficient"


def test_titulo_ja_enfeitado_na_origem_aceita_frase_nova(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    titulo_enfeite._CACHE.clear()
    origem = "💥 Sua cozinha moderna com Electrolux IM8S Inox Look 590L! 🧊✨"

    class _Nova(_Client):
        def post(
            self, url: str, *, headers: dict[str, str], json: dict[str, object]
        ) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "Electrolux IM8S Inox Look 590L na cozinha: "
                                    "frescor sem esforço! ❄️"
                                )
                            }
                        }
                    ]
                },
            )

    monkeypatch.setattr(settings, "openai_api_key", "sk-teste")
    monkeypatch.setattr(httpx, "Client", _Nova)
    saida = titulo_enfeite.enfeitar_titulo(origem, origem)
    assert saida != origem
    assert "IM8S" in saida and "590L" in saida


def test_frase_do_grupo_nao_trava_o_enfeite(monkeypatch: pytest.MonkeyPatch) -> None:
    titulo_enfeite._CACHE.clear()
    grupo = "Cozinha 250cm Smart Madesa: modulada rústica e moderna! ✨🍽️"

    class _FraseNova(_Client):
        def post(
            self, url: str, *, headers: dict[str, str], json: dict[str, object]
        ) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "Cozinha 250cm Smart Madesa: tudo no lugar! 🏡"}}
                    ]
                },
            )

    monkeypatch.setattr(settings, "openai_api_key", "sk-teste")
    monkeypatch.setattr(httpx, "Client", _FraseNova)
    assert (
        titulo_enfeite.enfeitar_titulo(grupo, grupo)
        == "Cozinha 250cm Smart Madesa: tudo no lugar! 🏡"
    )


def test_enfeite_recusado_devolve_o_nome_sem_a_frase_do_grupo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    titulo_enfeite._CACHE.clear()
    grupo = "Cozinha 250cm Smart Madesa: modulada rústica e moderna! ✨🍽️"

    class _Ruim(_Client):
        def post(
            self, url: str, *, headers: dict[str, str], json: dict[str, object]
        ) -> httpx.Response:
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "Oferta boa demais! ✨"}}]}
            )

    monkeypatch.setattr(settings, "openai_api_key", "sk-teste")
    monkeypatch.setattr(httpx, "Client", _Ruim)
    saida = titulo_enfeite.enfeitar_titulo(grupo, grupo)
    assert saida == "Cozinha 250cm Smart Madesa"
    assert not titulo_enfeite.titulo_igual(saida, grupo)


def test_enfeite_sem_o_modelo_e_descartado(monkeypatch: pytest.MonkeyPatch) -> None:
    titulo_enfeite._CACHE.clear()

    class _SemModelo(_Client):
        def post(
            self, url: str, *, headers: dict[str, str], json: dict[str, object]
        ) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "Micro-ondas Efficient: praticidade total! ✨"}}
                    ]
                },
            )

    monkeypatch.setattr(settings, "openai_api_key", "sk-teste")
    monkeypatch.setattr(httpx, "Client", _SemModelo)
    base = "Micro-ondas ME36S Efficient"
    assert titulo_enfeite.enfeitar_titulo(base, base) == base


def test_enfeite_cortado_no_meio_e_descartado(monkeypatch: pytest.MonkeyPatch) -> None:
    titulo_enfeite._CACHE.clear()

    class _Cortado(_Client):
        def post(
            self, url: str, *, headers: dict[str, str], json: dict[str, object]
        ) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "Espelho Retangular Grande com LED: "
                                    "Reflexos incríveis todos os di"
                                )
                            }
                        }
                    ]
                },
            )

    monkeypatch.setattr(settings, "openai_api_key", "sk-teste")
    monkeypatch.setattr(httpx, "Client", _Cortado)
    base = "Espelho Retangular Grande com LED"
    assert titulo_enfeite.enfeitar_titulo(base, base) == base
