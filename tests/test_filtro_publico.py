# ruff: noqa: F401, F811
"""Filtro de público no ciclo real com Postgres, sem rede nem WhatsApp."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from core import config_provider, relevancia, repositories
from core.models import Envio, Oferta
from tests.test_api import session_factory
from tests.test_multigrupo import _oferta, _preparar
from worker import monitor
from worker.channels import usar_canal


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "chave-teste")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-teste")
    monkeypatch.setattr(monitor, "_avisos_publico", {})
    # Impede que um teste acidentalmente use a rede.
    monkeypatch.setattr(relevancia.httpx, "Client", Mock(side_effect=AssertionError("rede proibida")))


def test_rejeitada_vista_sem_freio_proxima_candidata_e_sem_reavaliacao(
    monkeypatch, session_factory
):
    runtime, enviados = _preparar(
        monkeypatch, session_factory, [_oferta("Rodas de aluminio"), _oferta("Panela")],
        {"publico_alvo": "mulheres", "relevancia_minima": 0.6},
    )
    avaliar = Mock(side_effect=[0.12, 0.87])
    freio_real = monitor._freio_anti_ban
    freio = Mock(wraps=freio_real)
    logs = Mock()
    monkeypatch.setattr(relevancia, "avaliar_publico", avaliar)
    monkeypatch.setattr(monitor, "_freio_anti_ban", freio)
    monkeypatch.setattr(monitor.logger, "info", logs)
    with config_provider.usar_bot_runtime(runtime):
        assert monitor._executar_ciclo() == (2, 2, False)
        # A rejeição persistida impede até a segunda chamada Python, não só HTTP/cache.
        monitor._executar_ciclo()
    assert avaliar.call_count == 2
    assert [call.args[0] for call in avaliar.call_args_list] == ["Rodas de aluminio", "Panela"]
    assert freio.call_count == 1
    assert freio.call_args.args[3].nome == "Panela"
    assert len(enviados) == 2
    assert any("Fora do público (p=0.12 jev): Rodas" in c.args[0] for c in logs.call_args_list)
    assert any("Oferta NOVA (p=0.87 jev): Panela" in c.args[0] for c in logs.call_args_list)
    with session_factory() as session:
        vistos = session.scalars(select(Envio).join(Oferta).where(
            Oferta.nome == "Rodas de aluminio", Envio.status == "visto"
        )).all()
        assert {v.grupo for v in vistos} == set(runtime.group_ids)
        assert all(v.bot_id == runtime.id and v.group_id and v.mensagem.startswith("publico:")
                   for v in vistos)


@pytest.mark.parametrize("p", [0.6, 0.93, None])
def test_probabilidade_alta_limite_e_falha_aberta_enviam(monkeypatch, session_factory, p):
    runtime, enviados = _preparar(
        monkeypatch, session_factory, [_oferta("Panela")], {"publico_alvo": "mulheres"}
    )
    avaliar = Mock(return_value=p)
    monkeypatch.setattr(relevancia, "avaliar_publico", avaliar)
    with config_provider.usar_bot_runtime(runtime):
        monitor._executar_ciclo()
    avaliar.assert_called_once()
    assert len(enviados) == 2


@pytest.mark.parametrize(("publico", "categoria"), [
    ("", "casa"), ("   ", "casa"), ("mulheres", "cupom"),
    ("mulheres", "campanha"), ("mulheres", "promocao"), ("mulheres", "promoção"),
])
def test_desligado_cupom_e_campanha_sem_avaliacao(monkeypatch, session_factory, publico, categoria):
    oferta = _oferta("Panela")
    oferta.categoria = categoria
    runtime, enviados = _preparar(
        monkeypatch, session_factory, [oferta], {"publico_alvo": publico}
    )
    avaliar = Mock(side_effect=AssertionError("não deve avaliar"))
    monkeypatch.setattr(relevancia, "avaliar_publico", avaliar)
    monkeypatch.setattr(monitor.cupom_card, "gerar_card", lambda _o: None)
    with config_provider.usar_bot_runtime(runtime):
        monitor._executar_ciclo()
    avaliar.assert_not_called()
    assert len(enviados) == 2


@pytest.mark.parametrize("p", [0.12, 0.87, None])
def test_fluxo_processar_oferta(monkeypatch, session_factory, p):
    oferta = _oferta("Panela")
    runtime, enviados = _preparar(monkeypatch, session_factory, [oferta])
    avaliar = Mock(return_value=p)
    freio = Mock(return_value=(True, ""))
    monkeypatch.setattr(relevancia, "avaliar_publico", avaliar)
    monkeypatch.setattr(monitor, "_freio_anti_ban", freio)
    with config_provider.usar_bot_runtime(runtime), usar_canal(
        f"db:{runtime.id}:{runtime.group_ids[0]}"
    ), session_factory.begin() as session:
        resultado = monitor._processar_oferta(session, oferta, {"publico_alvo": "mulheres"})
        assert resultado == ("pulou" if p == 0.12 else "enviou")
        if p == 0.12:
            assert repositories.ja_conhecida(session, monitor._salvar_oferta(session, oferta).id,
                                            grupo=runtime.group_ids[0])
            assert monitor._processar_oferta(session, oferta, {"publico_alvo": "mulheres"}) == "pulou"
    avaliar.assert_called_once()
    assert freio.call_count == (0 if p == 0.12 else 1)
    assert len(enviados) == (0 if p == 0.12 else 1)


def test_mudanca_publico_limiar_e_nome_permite_reavaliacao(monkeypatch, session_factory):
    oferta = _oferta("Panela")
    runtime, enviados = _preparar(
        monkeypatch, session_factory, [oferta], {"publico_alvo": "profissionais"}
    )
    avaliar = Mock(return_value=0.12)
    monkeypatch.setattr(relevancia, "avaliar_publico", avaliar)
    with config_provider.usar_bot_runtime(runtime):
        monitor._executar_ciclo()
    assert not enviados
    for alteracao in ({"publico_alvo": "mulheres"}, {"classificador_publico": "haiku"},
                      {"relevancia_minima": 0.1}):
        with config_provider.usar_bot_runtime(runtime):
            filtros = {**config_provider.load_filtros_runtime(), **alteracao}
        monkeypatch.setattr(monitor, "load_filtros", lambda: filtros)
        with config_provider.usar_bot_runtime(runtime):
            monitor._executar_ciclo()
    assert avaliar.call_count == 4
    assert len(enviados) == 2


def test_sem_chave_desliga_ate_rejeicao_anterior(monkeypatch, session_factory):
    runtime, enviados = _preparar(
        monkeypatch, session_factory, [_oferta("Panela")], {"publico_alvo": "mulheres"}
    )
    avaliar = Mock(return_value=0.12)
    monkeypatch.setattr(relevancia, "avaliar_publico", avaliar)
    with config_provider.usar_bot_runtime(runtime):
        monitor._executar_ciclo()
        monkeypatch.delenv("TYPESAFE_API_KEY")
        monitor._executar_ciclo()
    avaliar.assert_called_once()
    assert len(enviados) == 2


def test_filtros_dedup_e_baseline_antes_da_avaliacao(monkeypatch, session_factory):
    runtime, _ = _preparar(
        monkeypatch, session_factory, [_oferta("Panela")], {"publico_alvo": "mulheres"}
    )
    avaliar = Mock(side_effect=AssertionError("não deve avaliar"))
    monkeypatch.setattr(relevancia, "avaliar_publico", avaliar)
    monkeypatch.setattr(monitor, "passa_nos_filtros", lambda *_a: (False, "bloqueada"))
    with config_provider.usar_bot_runtime(runtime):
        monitor._executar_ciclo()
    monkeypatch.setattr(monitor, "passa_nos_filtros", lambda *_a: (True, ""))
    monkeypatch.setattr(monitor.dedup, "deve_enviar", lambda *_a, **_kw: (False, "já enviada"))
    with config_provider.usar_bot_runtime(runtime):
        monitor._executar_ciclo()
    monkeypatch.setattr(monitor, "load_filtros", lambda: {"baseline_ciclos": 1,
                                                         "publico_alvo": "mulheres"})
    with config_provider.usar_bot_runtime(runtime):
        assert monitor._executar_ciclo()[2] is True
    avaliar.assert_not_called()


def test_aviso_none_limitado_por_bot(monkeypatch, session_factory):
    runtime, _ = _preparar(
        monkeypatch, session_factory, [_oferta("Panela")], {"publico_alvo": "mulheres"}
    )
    monkeypatch.setattr(relevancia, "avaliar_publico", lambda *_a: None)
    agora = [0]
    monkeypatch.setattr(monitor.time, "monotonic", lambda: agora[0])
    warning = Mock()
    monkeypatch.setattr(monitor.logger, "warning", warning)
    with session_factory.begin() as session:
        oferta = _oferta("Panela")
        oferta_db = monitor._salvar_oferta(session, oferta)
        for bot, instante in [(runtime, 0), (runtime, 599), (runtime, 600),
                              (replace(runtime, id="outro-bot"), 600)]:
            agora[0] = instante
            with config_provider.usar_bot_runtime(bot):
                assert monitor._avaliar_publico(session, oferta_db, oferta,
                                               {"publico_alvo": "mulheres"}, ()) == (True, None)
    assert warning.call_count == 3


@pytest.mark.parametrize("classificador", ["jev", "haiku"])
def test_monitor_passa_classificador_configurado(monkeypatch, session_factory, classificador):
    oferta = _oferta("Panela")
    runtime, enviados = _preparar(
        monkeypatch, session_factory, [oferta],
        {"publico_alvo": "mulheres", "classificador_publico": classificador},
    )
    avaliar = Mock(return_value=0.87)
    monkeypatch.setattr(relevancia, "avaliar_publico", avaliar)
    with config_provider.usar_bot_runtime(runtime):
        monitor._executar_ciclo()
    avaliar.assert_called_once_with(
        oferta.nome, oferta.loja, oferta.preco, "mulheres", classificador
    )
    assert len(enviados) == 2


def test_haiku_sem_chave_nao_usa_jev(monkeypatch, session_factory):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    runtime, enviados = _preparar(
        monkeypatch, session_factory, [_oferta("Panela")],
        {"publico_alvo": "mulheres", "classificador_publico": "haiku"},
    )
    avaliar = Mock(side_effect=AssertionError("não deve avaliar"))
    monkeypatch.setattr(relevancia, "avaliar_publico", avaliar)
    with config_provider.usar_bot_runtime(runtime):
        monitor._executar_ciclo()
    avaliar.assert_not_called()
    assert len(enviados) == 2
