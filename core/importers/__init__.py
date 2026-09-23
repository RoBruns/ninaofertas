"""Importadores de relatorios de comissao por plataforma."""

from core.importers.base import ImportValidationError, SaleImportRow
from core.importers.mercadolivre import MercadoLivreCSVImporter
from core.importers.shopee import ShopeeCSVImporter

IMPORTERS = {
    "shopee": ShopeeCSVImporter(),
    "mercadolivre": MercadoLivreCSVImporter(),
}

__all__ = ["IMPORTERS", "ImportValidationError", "SaleImportRow"]
