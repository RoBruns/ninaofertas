"""Nina Cozinha é o ambiente de DEV. Achadinhos continua produção."""
from __future__ import annotations

GRUPO_COZINHA = "120363432562048111@g.us"
GRUPO_ACHADINHOS = "120363412803208148@g.us"

TERMOS_NATAL = (
    "árvore de natal",
    "arvore de natal",
    "pinheiro",
    "pisca-pisca",
    "pisca pisca",
    "guirlanda",
    "enfeite de natal",
    "bola de natal",
    "presépio",
    "presepio",
    "toalha de mesa natal",
    "jogo americano natal",
    "caminho de mesa natal",
    "luzes de natal",
    "adorno de natal",
)


def eh_cozinha(grupo: str | None) -> bool:
    return (grupo or "").strip() == GRUPO_COZINHA
