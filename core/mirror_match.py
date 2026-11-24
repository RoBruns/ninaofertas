"""Matching de nomes de grupos/canais na allowlist do espelho."""

from __future__ import annotations

import re
import unicodedata

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U0001F1E0-\U0001F1FF"
    "]+",
    flags=re.UNICODE,
)


def normalizar_nome_grupo(nome: str) -> str:
    texto = unicodedata.normalize("NFKD", nome or "")
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = _EMOJI_RE.sub(" ", texto)
    texto = texto.casefold()
    texto = re.sub(r"[^\w\s&#+-]", " ", texto, flags=re.UNICODE)
    return " ".join(texto.split())


def nome_na_allowlist(nome: str | None, allowlist: list[str]) -> bool:
    if not nome or not allowlist:
        return False
    alvo = normalizar_nome_grupo(nome)
    if not alvo:
        return False
    for item in allowlist:
        padrao = normalizar_nome_grupo(item)
        if not padrao:
            continue
        if padrao == alvo or padrao in alvo or alvo in padrao:
            return True
    return False
