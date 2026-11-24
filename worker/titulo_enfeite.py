"""Enfeite curto do título. O nome do item fica; a frase e o emoji são o extra."""

from __future__ import annotations

import re
from collections import OrderedDict

import httpx

from core.settings import settings
from worker.filters import _tokens_titulo
from worker.logger import logger

_MODELO = "gpt-4.1-nano"
_URL = "https://api.openai.com/v1/chat/completions"
_CACHE: OrderedDict[str, str] = OrderedDict()
_CACHE_MAX = 300
_PEDIDO = (
    "Enfeite o título para uma oferta de WhatsApp. "
    "Mantenha marca, modelo e medidas exatamente como vieram. "
    "Acrescente dois pontos, uma frase de no máximo seis palavras e um ou dois emojis. "
    "Não descreva o produto, não invente preço, cupom ou loja. "
    "Responda só a linha final.\n"
    "Philco Psa3250 2100w Íons Tourmaline: Cabelos incríveis! ✨🖤\n"
    "Micro-ondas ME36S Efficient: praticidade e sabor inox! 🚀✨"
)


def enfeitar_titulo(titulo: str) -> str:
    """Devolve o título enfeitado, ou o original se a chave faltar ou a linha não servir."""
    base = " ".join((titulo or "").split())
    if len(base) < 8 or not settings.openai_api_key:
        return titulo
    chave = base.casefold()
    guardado = _CACHE.get(chave)
    if guardado is not None:
        return guardado
    linha = _pedir(base)
    if not _linha_serve(base, linha):
        logger.info("[espelho] enfeite recusado; título da página permanece")
        return titulo
    _guardar(chave, linha)
    return linha


def _pedir(titulo: str) -> str | None:
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                _URL,
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": _MODELO,
                    "temperature": 0.4,
                    "max_tokens": 80,
                    "messages": [
                        {"role": "system", "content": _PEDIDO},
                        {"role": "user", "content": titulo},
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
    linha = str(texto or "").strip().splitlines()[0].strip().strip('"').strip()
    return linha[:160] or None


def _linha_serve(titulo: str, linha: str | None) -> bool:
    if not linha or "\n" in linha:
        return False
    if not re.search(r":\s*\S", linha):
        return False
    nossos = {p for p in _tokens_titulo(titulo) if len(p) >= 4}
    if not nossos:
        return False
    deles = _tokens_titulo(linha)
    return nossos <= deles


def _guardar(chave: str, linha: str) -> None:
    _CACHE[chave] = linha
    _CACHE.move_to_end(chave)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
