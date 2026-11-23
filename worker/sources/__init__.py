"""Registro de fontes de ofertas.

Foco do canal: Mercado Livre, Shopee, Magalu e Amazon,
sempre com link de afiliado.
"""
from core.platforms.amazon import AmazonScraper
from core.platforms.base import OfertaCapturada, Scraper
from core.platforms.magalu import MagaluScraper
from core.platforms.mercadolivre import MercadoLivreScraper
from core.platforms.shopee import ShopeeScraper
from worker.sources.cupons import CupomScraper

FONTES: list[Scraper] = [
    CupomScraper(),
    MercadoLivreScraper(),
    ShopeeScraper(),
    MagaluScraper(),
    AmazonScraper(),
]

__all__ = ["FONTES", "Scraper", "OfertaCapturada"]
