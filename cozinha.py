"""Cozinha é o DEV. Achadinhos é a produção e recebe a promoção já vista no Cozinha."""
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
    "bolas de natal",
    "enfeites de natal",
    "natalina",
    "natalino",
    "presépio",
    "presepio",
    "toalha de mesa natal",
    "jogo americano natal",
    "caminho de mesa natal",
    "luzes de natal",
    "adorno de natal",
)

# Árvores, enfeites e pisca-pisca na página de ofertas do Mercado Livre.
CATEGORIAS_NATAL_MELI = (
    "MLB117806",
    "MLB117801",
    "MLB189949",
)


def eh_cozinha(grupo: str | None) -> bool:
    return (grupo or "").strip() == GRUPO_COZINHA


def promocao_liberada(grupo: str | None) -> bool:
    """Mesma promoção nos dois grupos: Cozinha (teste) e Achadinhos (produção)."""
    return (grupo or "").strip() in {GRUPO_COZINHA, GRUPO_ACHADINHOS}
