"""Contrato Haiku, isolamento dos provedores e falha aberta, sem rede."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import anthropic
import httpx2
import pytest

from core import relevancia


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-teste")
    monkeypatch.setenv("TYPESAFE_API_KEY", "chave-teste")
    monkeypatch.setattr(relevancia, "_cliente", None)
    monkeypatch.setattr(relevancia, "_cache", relevancia.OrderedDict())
    monkeypatch.setattr(relevancia, "_avisos_sem_chave", set())
    monkeypatch.setattr(relevancia.httpx, "Client", Mock(side_effect=AssertionError("rede proibida")))
    monkeypatch.setattr(anthropic, "Anthropic", Mock(side_effect=AssertionError("rede proibida")))


def cliente_mock(monkeypatch, texto='{"probabilidade":87}', stop_reason="end_turn"):
    cliente = Mock()
    cliente.messages.create.return_value = SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=texto)]
    )
    fabrica = Mock(return_value=cliente)
    monkeypatch.setattr(anthropic, "Anthropic", fabrica)
    return cliente, fabrica


def avaliar(nome="Pótes Herméticos"):
    return relevancia.avaliar_publico(nome, "Shopee", 49.9, "mulheres", "haiku")


def test_contrato_haiku_cliente_sob_demanda_e_cache(monkeypatch):
    cliente, fabrica = cliente_mock(monkeypatch)
    fabrica.assert_not_called()
    assert avaliar() == 0.87
    assert avaliar("  POTES   hermeticos ") == 0.87
    fabrica.assert_called_once_with(timeout=5.0, max_retries=1)
    cliente.messages.create.assert_called_once_with(
        model="claude-haiku-5-5", max_tokens=256, thinking={"type": "disabled"},
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": {
            "type": "object", "properties": {"probabilidade": {"type": "integer"}},
            "required": ["probabilidade"], "additionalProperties": False,
        }}},
        system=relevancia.SISTEMA,
        messages=[{"role": "user", "content": json.dumps({
            "publico": "mulheres", "produto": "Pótes Herméticos", "loja": "Shopee",
            "preco": "R$ 49,90",
        }, ensure_ascii=False)}],
    )
    assert "profissional, comercial, automotivo, técnico ou de obra" in relevancia.SISTEMA
    assert avaliar("Panela") == 0.87
    assert fabrica.call_count == 1


@pytest.mark.parametrize(("valor", "esperado"), [(-10, 0), (0, 0), (87, 0.87), (100, 1), (150, 1)])
def test_conversao_e_clamp(monkeypatch, valor, esperado):
    cliente_mock(monkeypatch, json.dumps({"probabilidade": valor}))
    assert avaliar() == esperado


def test_refusal_antes_de_ler_content(monkeypatch):
    cliente, _ = cliente_mock(monkeypatch, stop_reason="refusal")
    cliente.messages.create.return_value = SimpleNamespace(stop_reason="refusal")
    assert avaliar() is None
    assert not relevancia._cache


@pytest.mark.parametrize("texto", ["invalid", "{}", '{"probabilidade":"invalid"}', "null"])
def test_parse_invalido(monkeypatch, texto):
    cliente_mock(monkeypatch, texto)
    assert avaliar() is None
    assert not relevancia._cache


def test_sem_bloco_texto(monkeypatch):
    cliente, _ = cliente_mock(monkeypatch)
    cliente.messages.create.return_value.content = [SimpleNamespace(type="thinking")]
    assert avaliar() is None


@pytest.mark.parametrize("tipo", [
    anthropic.RateLimitError, anthropic.APIStatusError,
    anthropic.APIConnectionError, anthropic.APITimeoutError,
])
def test_excecoes_tipadas_e_none_nao_cacheado(monkeypatch, tipo):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    if issubclass(tipo, anthropic.APIStatusError):
        erro = tipo("segredo-nao-logar", response=httpx2.Response(429, request=request), body=None)
    else:
        erro = tipo(request=request)
    cliente, _ = cliente_mock(monkeypatch)
    cliente.messages.create.side_effect = erro
    logs = Mock()
    monkeypatch.setattr(relevancia.logger, "warning", logs)
    assert avaliar() is None
    assert not relevancia._cache
    logs.assert_not_called()
    cliente.messages.create.side_effect = None
    assert avaliar() == 0.87
    assert cliente.messages.create.call_count == 2


def test_sem_chave_sem_cliente_e_aviso_por_provedor(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("TYPESAFE_API_KEY")
    logs = Mock()
    monkeypatch.setattr(relevancia.logger, "warning", logs)
    for _ in range(2):
        assert avaliar() is None
        assert relevancia.avaliar_publico("Panela", "Shopee", 10, "mulheres") is None
    anthropic.Anthropic.assert_not_called()
    relevancia.httpx.Client.assert_not_called()
    assert logs.call_count == 2
    assert "ANTHROPIC_API_KEY" in logs.call_args_list[0].args[0]
    assert "TYPESAFE_API_KEY" in logs.call_args_list[1].args[0]


def test_cache_separado_por_classificador(monkeypatch):
    cliente, _ = cliente_mock(monkeypatch)
    jev = Mock(return_value=0.12)
    monkeypatch.setattr(relevancia, "_avaliar_jev", jev)
    for _ in range(2):
        assert relevancia.avaliar_publico("Panela", "Shopee", 10, "mulheres") == 0.12
        assert avaliar("Panela") == 0.87
    jev.assert_called_once()
    cliente.messages.create.assert_called_once()
    assert set(relevancia._cache) == {("jev", "mulheres", "panela"), ("haiku", "mulheres", "panela")}
