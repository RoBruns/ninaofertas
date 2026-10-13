"""Classificação opcional de produtos para o público do bot, com falha aberta."""

from __future__ import annotations

import json
import math
import os
import time
import unicodedata
from collections import OrderedDict
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime

import anthropic
import httpx
from loguru import logger

MODELO = "jev-1.13.0"
MODELO_HAIKU = "claude-haiku-5-5"
SISTEMA = (
    "Você é um classificador de produtos para um grupo de ofertas de WhatsApp. "
    "Recebe o público do grupo e um produto. Responda a probabilidade, de 0 a 100, "
    "de que pessoas desse público comprariam esse produto para si, para a casa ou "
    "para presentear alguém próximo. Produtos típicos de outro público, de uso "
    "profissional, comercial, automotivo, técnico ou de obra recebem probabilidade baixa. "
    "Títulos de marketplace são longos e cheios de palavras de busca; julgue o produto em si."
)
VARIAVEIS_CHAVE = {"jev": "TYPESAFE_API_KEY", "haiku": "ANTHROPIC_API_KEY"}
URL = "https://api.typesafe.ai/v1/systemone"
CACHE_TTL = 7 * 24 * 60 * 60
CACHE_MAX = 5000
_cache: OrderedDict[tuple[str, str, str], tuple[float, float]] = OrderedDict()
_avisos_sem_chave: set[str] = set()
_cliente: anthropic.Anthropic | None = None


def normalizar_nome(nome: str) -> str:
    texto = unicodedata.normalize("NFD", nome.lower())
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).split())


def chave_disponivel(classificador: str = "jev") -> bool:
    variavel = VARIAVEIS_CHAVE.get(classificador)
    if variavel is None:
        return False
    if os.getenv(variavel, "").strip():
        return True
    if classificador not in _avisos_sem_chave:
        logger.warning(f"{variavel} ausente; filtro de público {classificador} desligado neste processo.")
        _avisos_sem_chave.add(classificador)
    return False


def _espera_retry(valor: str) -> float:
    try:
        segundos = float(valor)
    except ValueError:
        try:
            segundos = (parsedate_to_datetime(valor) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            segundos = 0
    return min(2.0, max(0.0, segundos)) if math.isfinite(segundos) else 0.0


def avaliar_publico(
    nome: str, loja: str, preco: float | Decimal, publico_alvo: str, classificador: str = "jev"
) -> float | None:
    """Retorna a probabilidade de compra; indisponibilidade nunca bloqueia envios."""
    if not publico_alvo.strip() or not chave_disponivel(classificador):
        return None
    chave = (classificador, publico_alvo, normalizar_nome(nome))
    entrada = _cache.get(chave)
    if entrada is not None:
        probabilidade, criado = entrada
        if time.monotonic() - criado < CACHE_TTL:
            _cache.move_to_end(chave)
            logger.debug(f"Público (cache, p={probabilidade:.2f} {classificador}): {nome[:60]}")
            return probabilidade
        del _cache[chave]

    avaliar = _avaliar_haiku if classificador == "haiku" else _avaliar_jev
    probabilidade = avaliar(nome, loja, preco, publico_alvo)
    if probabilidade is not None:
        _cache[chave] = (probabilidade, time.monotonic())
        _cache.move_to_end(chave)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
        logger.debug(f"Público (p={probabilidade:.2f} {classificador}): {nome[:60]}")
    return probabilidade


def _avaliar_haiku(
    nome: str, loja: str, preco: float | Decimal, publico_alvo: str
) -> float | None:
    global _cliente
    estado = {
        "publico": publico_alvo,
        "produto": nome,
        "loja": loja,
        "preco": f"R$ {Decimal(str(preco)):.2f}".replace(".", ","),
    }
    try:
        if _cliente is None:
            _cliente = anthropic.Anthropic(timeout=5.0, max_retries=1)
        resposta = _cliente.messages.create(
            model=MODELO_HAIKU,
            max_tokens=256,
            thinking={"type": "disabled"},
            output_config={
                "effort": "low",
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {"probabilidade": {"type": "integer"}},
                        "required": ["probabilidade"],
                        "additionalProperties": False,
                    },
                },
            },
            system=SISTEMA,
            messages=[{"role": "user", "content": json.dumps(estado, ensure_ascii=False)}],
        )
        if resposta.stop_reason == "refusal":
            return None
        texto = next(b.text for b in resposta.content if b.type == "text")
        return max(0, min(100, int(json.loads(texto)["probabilidade"]))) / 100
    except (
        anthropic.RateLimitError, anthropic.APIStatusError,
        anthropic.APITimeoutError, anthropic.APIConnectionError,
        ValueError, KeyError, StopIteration, TypeError, OverflowError,
    ):
        # Não registrar exceções que possam carregar credenciais ou conteúdo da resposta.
        return None


def _avaliar_jev(
    nome: str, loja: str, preco: float | Decimal, publico_alvo: str
) -> float | None:
    corpo = {
        "model": MODELO,
        "state": {
            "produto": nome,
            "loja": loja,
            "preco": f"R$ {Decimal(str(preco)):.2f}".replace(".", ","),
        },
        "questions": {
            "publico": {
                "type": "noul",
                "instructions": (
                    "Pessoas deste público comprariam este produto para si ou para a casa? "
                    f"Público: {publico_alvo}"
                ),
                "criteria": {
                    "true": "Produto que esse público compra normalmente para si, para a casa "
                    "ou para presentear alguém próximo",
                    "false": "Produto típico de outro público ou de uso profissional, comercial, "
                    "automotivo, técnico ou de obra",
                },
            }
        },
    }
    try:
        with httpx.Client(timeout=5.0) as cliente:
            for tentativa in range(2):
                resposta = cliente.post(
                    URL,
                    headers={
                        "Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY'].strip()}",
                        "Content-Type": "application/json",
                    },
                    json=corpo,
                )
                if resposta.status_code == 429 and tentativa == 0:
                    time.sleep(_espera_retry(resposta.headers.get("retry-after", "0")))
                    continue
                resposta.raise_for_status()
                resposta_publico = resposta.json()["answers"]["publico"]
                if resposta_publico["type"] != "noul":
                    return None
                valor = resposta_publico["noul"]
                if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                    return None
                probabilidade = float(valor)
                if not math.isfinite(probabilidade) or not 0 <= probabilidade <= 1:
                    return None
                return probabilidade
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        # Não registrar corpo, headers nem exceções que possam carregar credenciais.
        return None
    return None
