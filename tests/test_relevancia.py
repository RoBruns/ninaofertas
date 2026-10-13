"""Contrato Jev e cache sem qualquer chamada à rede."""

from __future__ import annotations

import json
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from core import relevancia
from core.bot_settings import BotSettings
from core.seed import _settings_from_config

HTTPX_CLIENT = httpx.Client

@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "chave-teste")
    monkeypatch.setattr(relevancia, "_cache", relevancia.OrderedDict())
    monkeypatch.setattr(relevancia, "_avisos_sem_chave", set())


def _cliente(monkeypatch, respostas):
    requests = []

    def handler(request):
        requests.append(request)
        resposta = respostas[len(requests) - 1]
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    cliente = HTTPX_CLIENT(transport=httpx.MockTransport(handler), timeout=5.0)
    factory = Mock(return_value=cliente)
    monkeypatch.setattr(relevancia.httpx, "Client", factory)
    return requests, factory


def _resposta(p=0.93):
    return httpx.Response(200, json={"answers": {"publico": {"type": "noul", "noul": p}}})


def test_contrato_e_cache_normalizado(monkeypatch):
    requests, factory = _cliente(monkeypatch, [_resposta()])
    assert relevancia.avaliar_publico("Pótes Herméticos", "Shopee", 49.9, "mulheres") == 0.93
    assert relevancia.avaliar_publico("  POTES   hermeticos ", "Shopee", 50, "mulheres") == 0.93
    assert len(requests) == 1
    factory.assert_called_once_with(timeout=5.0)
    request = requests[0]
    assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Bearer chave-teste"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content) == {
        "model": "jev-1.13.0",
        "state": {"produto": "Pótes Herméticos", "loja": "Shopee", "preco": "R$ 49,90"},
        "questions": {"publico": {
            "type": "noul",
            "instructions": "Pessoas deste público comprariam este produto para si ou para a casa? "
            "Público: mulheres",
            "criteria": {
                "true": "Produto que esse público compra normalmente para si, para a casa "
                "ou para presentear alguém próximo",
                "false": "Produto típico de outro público ou de uso profissional, comercial, "
                "automotivo, técnico ou de obra",
            },
        }},
    }


def test_sem_chave_sem_http_aviso_unico(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY")
    cliente = Mock(side_effect=AssertionError("não deve chamar HTTP"))
    warning = Mock()
    monkeypatch.setattr(relevancia.httpx, "Client", cliente)
    monkeypatch.setattr(relevancia.logger, "warning", warning)
    for _ in range(2):
        assert relevancia.avaliar_publico("Panela", "Shopee", 49.9, "mulheres") is None
    cliente.assert_not_called()
    warning.assert_called_once()


@pytest.mark.parametrize("resposta", [
    httpx.TimeoutException("timeout"),
    httpx.ConnectError("offline"),
    httpx.Response(500),
    httpx.Response(200, content=b"invalid json"),
    httpx.Response(200, json={}),
    httpx.Response(200, json={"answers": {"publico": None}}),
    _resposta(-0.1), _resposta(1.1), _resposta("0.9"), _resposta(True), _resposta(None),
])
def test_falhas_abertas_e_none_nao_cacheado(monkeypatch, resposta):
    requests, _ = _cliente(monkeypatch, [resposta])
    assert relevancia.avaliar_publico("Panela", "Shopee", 49.9, "mulheres") is None
    assert not relevancia._cache
    requests, _ = _cliente(monkeypatch, [_resposta()])
    assert relevancia.avaliar_publico("Panela", "Shopee", 49.9, "mulheres") == 0.93
    assert len(requests) == 1


@pytest.mark.parametrize(("retry", "espera"), [("1.5", 1.5), ("30", 2), ("invalid", 0)])
@pytest.mark.parametrize("segundo_status", [200, 429])
def test_retry_429_uma_vez(monkeypatch, retry, espera, segundo_status):
    sleep = Mock()
    monkeypatch.setattr(relevancia.time, "sleep", sleep)
    respostas = [httpx.Response(429, headers={"retry-after": retry}),
                 _resposta() if segundo_status == 200 else httpx.Response(429)]
    requests, _ = _cliente(monkeypatch, respostas)
    assert relevancia.avaliar_publico("Panela", "Shopee", 49.9, "mulheres") == (
        0.93 if segundo_status == 200 else None
    )
    assert len(requests) == 2
    sleep.assert_called_once_with(espera)


def test_cache_ttl_lru_e_publicos_distintos(monkeypatch):
    agora = [0.0]
    monkeypatch.setattr(relevancia.time, "monotonic", lambda: agora[0])
    monkeypatch.setattr(relevancia, "CACHE_MAX", 2)
    _cliente(monkeypatch, [_resposta()])
    relevancia.avaliar_publico("Panela", "Shopee", 10, "mulheres")
    _cliente(monkeypatch, [_resposta(0.1)])
    assert relevancia.avaliar_publico("Panela", "Shopee", 10, "profissionais") == 0.1
    # Acesso move a entrada para o fim do LRU; não renova o TTL.
    assert relevancia.avaliar_publico("Panela", "Shopee", 10, "mulheres") == 0.93
    _cliente(monkeypatch, [_resposta()])
    relevancia.avaliar_publico("Pote", "Shopee", 10, "mulheres")
    assert ("jev", "profissionais", "panela") not in relevancia._cache
    assert len(relevancia._cache) == 2
    agora[0] = relevancia.CACHE_TTL
    requests, _ = _cliente(monkeypatch, [_resposta(0.8)])
    assert relevancia.avaliar_publico("Panela", "Shopee", 10, "mulheres") == 0.8
    assert len(requests) == 1


def test_settings_publico_padrao_limites_e_legado():
    filtros = BotSettings().filters
    assert filtros.publico_alvo == ""
    assert filtros.classificador_publico == "jev"
    assert BotSettings(filters={"classificador_publico": "haiku"}).filters.classificador_publico == "haiku"
    with pytest.raises(ValidationError):
        BotSettings(filters={"classificador_publico": "outro"})
    assert filtros.relevancia_minima == 0.6
    for limite in (0, 1):
        assert BotSettings(filters={"relevancia_minima": limite}).filters.relevancia_minima == limite
    for invalido in (-0.1, 1.1):
        with pytest.raises(ValidationError):
            BotSettings(filters={"relevancia_minima": invalido})
    with pytest.raises(ValidationError):
        BotSettings(filters={"publico_alvo": "a" * 501})
    assert len(BotSettings(filters={"publico_alvo": "a" * 500}).filters.publico_alvo) == 500
    legado = {"publico_alvo": "mulheres", "relevancia_minima": 0.75, "classificador_publico": "haiku"}
    assert BotSettings.model_validate(legado).model_dump() == legado
    assert _settings_from_config(legado)["filters"] == legado
