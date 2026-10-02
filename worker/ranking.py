"""Pontuação de demanda e oferta, sem efeitos colaterais."""
from math import log10

from core.platforms.base import OfertaCapturada


def pontuar(oferta: OfertaCapturada) -> float:
    demanda = 0.0
    if oferta.loja.lower() == "shopee" and oferta.vendas is not None:
        demanda = min(log10(1 + max(oferta.vendas, 0)) / log10(20001), 1)
    elif oferta.loja.lower() == "mercado livre" and oferta.posicao_ranking is not None:
        demanda = max(0, min((21 - oferta.posicao_ranking) / 20, 1))
    desconto = max(0, min(oferta.desconto or 0, 70)) / 70
    nota = max(0, min((oferta.nota or 0) - 4, 1))
    comissao = max(0, min(oferta.comissao_pct or 0, 0.15)) / 0.15
    return 0.45 * demanda + 0.35 * desconto + 0.10 * nota + 0.10 * comissao
