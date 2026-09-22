"""Registro de fontes de ofertas.

Foco do canal: Mercado Livre + Shopee (produtos, promoções e cupons),
sempre com link de afiliado quando possível.
"""
from core.platforms.base import OfertaCapturada, Scraper
from core.platforms.mercadolivre import MercadoLivreScraper
from core.platforms.shopee import ShopeeScraper
from worker.sources.cupons import CupomScraper

FONTES: list[Scraper] = [
    CupomScraper(),
    MercadoLivreScraper(),
    ShopeeScraper(),
]

__all__ = ["FONTES", "Scraper", "OfertaCapturada"]
