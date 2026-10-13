"""Compare Jev e Haiku sem enviar mensagens ou acessar o banco.

Uso: python scripts/comparar_classificadores.py ENTRADA.csv --publico "texto"
     [--limiar 0.6] [--saida resultado.csv]
CSV UTF-8: nome,loja,preco,esperado (sim/nao/vazio; preço vazio vale 0).
TYPESAFE_API_KEY e ANTHROPIC_API_KEY podem ficar no .env local. Sem chave,
o provedor é pulado. None não entra nas métricas de qualidade. Abaixo do
limiar significa "nao". p95 usa o percentil por posto mais próximo.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean

from dotenv import load_dotenv

# Permite executar diretamente a partir de qualquer diretório.
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from core import relevancia  # noqa: E402


def metricas(
    linhas: list[dict[str, str]], probabilidades: list[float | None],
    latencias: list[float], limiar: float,
) -> dict[str, int | float | None]:
    rotuladas = [
        (linha["esperado"].strip().lower(), p)
        for linha, p in zip(linhas, probabilidades, strict=True)
        if linha["esperado"].strip() and p is not None
    ]
    acertos = sum((p < limiar) == (esperado == "nao") for esperado, p in rotuladas)
    verdadeiros_nao = sum(p < limiar and esperado == "nao" for esperado, p in rotuladas)
    previstos_nao = sum(p < limiar for _, p in rotuladas)
    esperados_nao = sum(esperado == "nao" for esperado, _ in rotuladas)
    return {
        "avaliados": len(probabilidades) - probabilidades.count(None),
        "none": probabilidades.count(None),
        "media_ms": mean(latencias) if latencias else None,
        "p95_ms": sorted(latencias)[math.ceil(0.95 * len(latencias)) - 1] if latencias else None,
        "rotulados": len(rotuladas),
        "acertos": acertos,
        "precisao_nao": verdadeiros_nao / previstos_nao if previstos_nao else None,
        "revocacao_nao": verdadeiros_nao / esperados_nao if esperados_nao else None,
    }


def _numero(valor: int | float | None) -> str:
    return "n/d" if valor is None else f"{valor:.3f}"


def comparar(entrada: Path, publico: str, limiar: float, saida: Path) -> None:
    with entrada.open(encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.DictReader(arquivo)
        campos = list(leitor.fieldnames or [])
        if not {"nome", "loja", "preco", "esperado"} <= set(campos):
            raise ValueError("Entrada precisa das colunas nome, loja, preco, esperado.")
        linhas = list(leitor)
    precos: list[Decimal] = []
    for numero, linha in enumerate(linhas, 2):
        if any(linha.get(campo) is None for campo in campos) or None in linha:
            raise ValueError(f"Linha {numero}: quantidade de colunas inválida.")
        if linha["esperado"].strip().lower() not in {"sim", "nao", ""}:
            raise ValueError(f"Linha {numero}: esperado deve ser sim, nao ou vazio.")
        preco = Decimal(linha["preco"].strip().replace(",", ".") or "0")
        if not preco.is_finite() or preco < 0:
            raise ValueError(f"Linha {numero}: preço inválido.")
        precos.append(preco)

    resultados: dict[str, list[float | None]] = {}
    for provedor in relevancia.VARIAVEIS_CHAVE:
        for linha in linhas:
            linha[f"p_{provedor}"] = ""
            linha[f"ms_{provedor}"] = ""
        if not relevancia.chave_disponivel(provedor):
            sys.stdout.write(f"{provedor}: sem {relevancia.VARIAVEIS_CHAVE[provedor]}; pulado.\n")
            continue
        probabilidades: list[float | None] = []
        latencias: list[float] = []
        for linha, preco in zip(linhas, precos, strict=True):
            inicio = time.perf_counter()
            p = relevancia.avaliar_publico(linha["nome"], linha["loja"], preco, publico, provedor)
            ms = (time.perf_counter() - inicio) * 1000
            probabilidades.append(p)
            latencias.append(ms)
            linha[f"p_{provedor}"] = "" if p is None else str(p)
            linha[f"ms_{provedor}"] = f"{ms:.3f}"
        resultados[provedor] = probabilidades
        resumo = metricas(linhas, probabilidades, latencias, limiar)
        sys.stdout.write(
            f"{provedor}: avaliados={resumo['avaliados']}, None={resumo['none']}, "
            f"latência média={_numero(resumo['media_ms'])} ms, "
            f"p95={_numero(resumo['p95_ms'])} ms\n"
        )
        if any(linha["esperado"].strip() for linha in linhas):
            sys.stdout.write(
                f"  acertos={resumo['acertos']}/{resumo['rotulados']}, "
                f"precisão de nao={_numero(resumo['precisao_nao'])}, "
                f"revocação de nao={_numero(resumo['revocacao_nao'])} (limiar={limiar})\n"
            )
            sys.stdout.write("  Discordâncias com esperado:\n")
            for numero, (linha, p) in enumerate(zip(linhas, probabilidades, strict=True), 2):
                esperado = linha["esperado"].strip().lower()
                if esperado and p is not None and (p < limiar) != (esperado == "nao"):
                    sys.stdout.write(f"    linha {numero}: {linha['nome']} (esperado={esperado}, p={p})\n")
    if len(resultados) == 2:
        sys.stdout.write("Discordâncias entre Jev e Haiku:\n")
        for i, linha in enumerate(linhas):
            jev, haiku = resultados["jev"][i], resultados["haiku"][i]
            if jev is not None and haiku is not None and (jev < limiar) != (haiku < limiar):
                sys.stdout.write(f"  linha {i + 2}: {linha['nome']} (jev={jev}, haiku={haiku})\n")
    with saida.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos + ["p_jev", "p_haiku", "ms_jev", "ms_haiku"])
        escritor.writeheader()
        escritor.writerows(linhas)
    sys.stdout.write(f"Saída: {saida}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entrada", type=Path)
    parser.add_argument("--publico", required=True)
    parser.add_argument("--limiar", type=float, default=0.6)
    parser.add_argument("--saida", type=Path)
    args = parser.parse_args(argv)
    if not args.publico.strip() or not math.isfinite(args.limiar) or not 0 <= args.limiar <= 1:
        parser.error("Público precisa estar preenchido e limiar deve estar entre 0 e 1.")
    load_dotenv(RAIZ / ".env")
    saida = args.saida or args.entrada.with_name(f"{args.entrada.stem}_resultado.csv")
    if saida.resolve() == args.entrada.resolve():
        parser.error("Saída precisa ser diferente da entrada.")
    try:
        comparar(args.entrada, args.publico, args.limiar, saida)
    except (OSError, ValueError, InvalidOperation) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
