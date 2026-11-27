"""Enfeite curto do título. O nome do item fica; a frase e o emoji são o extra."""

from __future__ import annotations

import re
from collections import OrderedDict

import httpx

from core.settings import settings
from worker.filters import _tokens_titulo
from worker.logger import logger

_MODELO = "gpt-5.6-luna"
_URL = "https://api.openai.com/v1/chat/completions"
_CACHE: OrderedDict[str, str] = OrderedDict()
_CACHE_MAX = 300
_PEDIDO = (
    "Enfeite o título para uma oferta de WhatsApp. "
    "Mantenha marca, modelo e medidas exatamente como vieram. "
    "A oferta é espelho de outro grupo: a linha final não pode ser igual ao título de lá. "
    "Acrescente dois pontos, uma frase de no máximo seis palavras e um ou dois emojis. "
    "Não descreva o produto, não invente preço, cupom ou loja. "
    "Responda só a linha final.\n"
    "Philco Psa3250 2100w Íons Tourmaline: Cabelos incríveis! ✨🖤\n"
    "Micro-ondas ME36S Efficient: praticidade e sabor inox! 🚀✨"
)


def enfeitar_titulo(titulo: str, titulo_grupo: str) -> str:
    """Enfeite diferente do título do grupo. Sem chave, devolve o título da página."""
    base = " ".join((titulo or "").split())
    if len(base) < 8 or not settings.openai_api_key:
        return titulo
    chave = base.casefold()
    guardado = _CACHE.get(chave)
    if guardado is not None and not titulo_igual(guardado, titulo_grupo):
        return guardado
    linha = _pedir(base, titulo_grupo)
    if not _linha_serve(base, linha, titulo_grupo):
        logger.info("[espelho] enfeite recusado; título da página permanece")
        return titulo
    _guardar(chave, linha or "")
    return linha or titulo


def titulo_igual(titulo: str, outro: str) -> bool:
    """Mesmo texto, sem diferença de maiúscula ou espaço."""
    return " ".join((titulo or "").casefold().split()) == " ".join((outro or "").casefold().split())


def _pedir(titulo: str, titulo_grupo: str) -> str | None:
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                _URL,
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": _MODELO,
                    "reasoning_effort": "none",
                    "max_completion_tokens": 80,
                    "messages": [
                        {"role": "system", "content": _PEDIDO},
                        {
                            "role": "user",
                            "content": (
                                f"Título do grupo de origem:\n{titulo_grupo}\n\n"
                                f"Nome do produto:\n{titulo}"
                            ),
                        },
                    ],
                },
            )
    except httpx.HTTPError:
        logger.info("[espelho] OpenAI indisponível; título da página permanece")
        return None
    if response.status_code >= 400:
        logger.info(f"[espelho] OpenAI recusou o enfeite ({response.status_code})")
        return None
    try:
        texto = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if isinstance(texto, list):
        texto = "".join(
            str(parte.get("text") or "") if isinstance(parte, dict) else str(parte)
            for parte in texto
        )
    linha = str(texto or "").strip().splitlines()[0].strip().strip('"').strip()
    # Não corta no meio: linha longa demais é recusada e fica o nome limpo.
    if not linha or len(linha) > 200:
        return None
    return linha


def _linha_serve(titulo: str, linha: str | None, titulo_grupo: str) -> bool:
    if not linha or "\n" in linha or titulo_igual(linha, titulo_grupo):
        return False
    if not re.search(r":\s*\S", linha):
        return False
    # Frase incompleta típica de max_tokens / corte ("todos os di").
    if re.search(r"[A-Za-zÀ-ÿ]$", linha):
        return False
    nossos = {p for p in _tokens_titulo(titulo) if len(p) >= 4}
    if not nossos:
        return False
    deles = _tokens_titulo(linha)
    # Modelo e medida (token com dígito) ficam sempre; o resto pode trocar a frase
    # de efeito que o grupo de origem já pôs no título ("Sua cozinha moderna com…").
    modelo = {p for p in nossos if any(c.isdigit() for c in p)}
    if not modelo <= deles:
        return False
    resto = nossos - modelo
    if not resto:
        return True
    return len(resto & deles) / len(resto) >= 0.6


def _guardar(chave: str, linha: str) -> None:
    _CACHE[chave] = linha
    _CACHE.move_to_end(chave)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
