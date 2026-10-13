"""Comparação via CSV, métricas de rejeição e provedores opcionais sem rede."""

import csv
from decimal import Decimal
from unittest.mock import Mock

import pytest

from scripts import comparar_classificadores as script


def entrada(tmp_path):
    arquivo = tmp_path / "produtos.csv"
    arquivo.write_text(
        'nome,loja,preco,esperado\nPanela,Shopee,"49,90",sim\n'
        'Motor,ML,,nao\nBroca,ML,10,nao\nAnel,Shopee,20,sim\nPote,Shopee,,\n',
        encoding="utf-8",
    )
    return arquivo


def test_csv_metricas_latencias_e_discordancias(tmp_path, monkeypatch, capsys):
    arquivo = entrada(tmp_path)
    saida = tmp_path / "resultado.csv"
    monkeypatch.setenv("TYPESAFE_API_KEY", "teste")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "teste")
    valores = {"jev": iter([0.9, 0.1, 0.8, 0.2, None]),
               "haiku": iter([0.6, 0.7, 0.3, 0.9, 0.7])}
    avaliar = Mock(side_effect=lambda _nome, _loja, _preco, _publico, provedor: next(valores[provedor]))
    monkeypatch.setattr(script.relevancia, "avaliar_publico", avaliar)
    # Cinco durações de 1,2,3,4,5 ms para cada provedor.
    instantes = iter([t for _ in range(2) for ms in range(1, 6) for t in (0, ms / 1000)])
    monkeypatch.setattr(script.time, "perf_counter", lambda: next(instantes))
    assert script.main([str(arquivo), "--publico", "mulheres", "--saida", str(saida)]) == 0
    with saida.open(encoding="utf-8", newline="") as csv_saida:
        leitor = csv.DictReader(csv_saida)
        assert leitor.fieldnames == ["nome", "loja", "preco", "esperado", "p_jev", "p_haiku", "ms_jev", "ms_haiku"]
        linhas = list(leitor)
    assert linhas[0]["preco"] == "49,90"
    assert linhas[0]["p_jev"] == "0.9"
    assert linhas[0]["ms_jev"] == "1.000"
    assert linhas[4]["p_jev"] == ""
    assert linhas[4]["ms_jev"] == "5.000"
    assert avaliar.call_count == 10
    assert avaliar.call_args_list[0].args == ("Panela", "Shopee", Decimal("49.90"), "mulheres", "jev")
    assert avaliar.call_args_list[1].args[2] == Decimal(0)
    texto = capsys.readouterr().out
    assert "jev: avaliados=4, None=1, latência média=3.000 ms, p95=5.000 ms" in texto
    assert "acertos=2/4, precisão de nao=0.500, revocação de nao=0.500" in texto
    assert "haiku: avaliados=5, None=0" in texto
    assert "acertos=3/4, precisão de nao=1.000, revocação de nao=0.500" in texto
    assert "linha 4: Broca (esperado=nao, p=0.8)" in texto
    assert "linha 5: Anel (esperado=sim, p=0.2)" in texto
    assert "linha 3: Motor (jev=0.1, haiku=0.7)" in texto


def test_metricas_denominadores_vazios_e_none():
    assert script.metricas([{"esperado": "nao"}], [None], [7], 0.6) == {
        "avaliados": 0, "none": 1, "media_ms": 7, "p95_ms": 7, "rotulados": 0,
        "acertos": 0, "precisao_nao": None, "revocacao_nao": None,
    }
    resumo = script.metricas([{"esperado": "nao"}] * 20, [0.1] * 20, list(range(1, 21)), 0.6)
    assert resumo["p95_ms"] == 19
    assert resumo["precisao_nao"] == resumo["revocacao_nao"] == 1


@pytest.mark.parametrize("provedor", ["jev", "haiku"])
def test_provedor_sem_chave_pulado(tmp_path, monkeypatch, capsys, provedor):
    outro = "haiku" if provedor == "jev" else "jev"
    monkeypatch.delenv(script.relevancia.VARIAVEIS_CHAVE[provedor], raising=False)
    monkeypatch.setenv(script.relevancia.VARIAVEIS_CHAVE[outro], "teste")
    avaliar = Mock(return_value=0.8)
    monkeypatch.setattr(script.relevancia, "avaliar_publico", avaliar)
    arquivo = entrada(tmp_path)
    saida = tmp_path / "saida.csv"
    script.comparar(arquivo, "mulheres", 0.6, saida)
    assert avaliar.call_count == 5
    assert all(c.args[-1] == outro for c in avaliar.call_args_list)
    assert f"{provedor}: sem {script.relevancia.VARIAVEIS_CHAVE[provedor]}; pulado." in capsys.readouterr().out
    with saida.open(encoding="utf-8", newline="") as resultado:
        assert all(linha[f"p_{provedor}"] == linha[f"ms_{provedor}"] == ""
                   for linha in csv.DictReader(resultado))


def test_sem_chaves_sem_chamadas(tmp_path, monkeypatch, capsys):
    for variavel in script.relevancia.VARIAVEIS_CHAVE.values():
        monkeypatch.delenv(variavel, raising=False)
    avaliar = Mock(side_effect=AssertionError("rede proibida"))
    monkeypatch.setattr(script.relevancia, "avaliar_publico", avaliar)
    script.comparar(entrada(tmp_path), "mulheres", 0.6, tmp_path / "saida.csv")
    avaliar.assert_not_called()
    assert capsys.readouterr().out.count("pulado.") == 2


@pytest.mark.parametrize("limiar", ["-1", "1.1", "nan"])
def test_limiar_invalido_antes_de_consultar(tmp_path, limiar):
    with pytest.raises(SystemExit) as erro:
        script.main([str(entrada(tmp_path)), "--publico", "mulheres", "--limiar", limiar])
    assert erro.value.code == 2
