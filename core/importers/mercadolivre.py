"""Mapeamento explicito do relatorio CSV do Mercado Livre."""

from core.importers.base import BaseCSVImporter


class MercadoLivreCSVImporter(BaseCSVImporter):
    COLUMN_ALIASES = {
        "external_id": ("order_id", "order id", "id da venda", "id_venda", "pedido"),
        "product_name": ("product_name", "titulo do anuncio", "produto", "item"),
        "quantity": ("quantity", "quantidade", "unidades"),
        "gross_amount": ("gross_amount", "sale_amount", "valor da venda", "valor_venda"),
        "commission": ("commission", "comissao", "receita", "valor da comissao"),
        "commission_rate": ("commission_rate", "percentual da comissao", "taxa de comissao"),
        "status": ("status", "status da venda", "status_venda"),
        "ordered_at": ("ordered_at", "sale_date", "data da venda", "data_venda"),
        "confirmed_at": ("confirmed_at", "data de confirmacao", "data_pagamento"),
        "sub_id": ("sub_id", "subid", "sub id"),
        "bot_id": ("bot_id",),
        "group_id": ("group_id",),
        "buyer_hash": ("buyer_hash",),
    }
    STATUS_MAP = {
        "pendente": "pending",
        "pending": "pending",
        "confirmada": "confirmed",
        "confirmado": "confirmed",
        "approved": "confirmed",
        "confirmed": "confirmed",
        "cancelada": "cancelled",
        "cancelado": "cancelled",
        "cancelled": "cancelled",
        "paga": "paid",
        "pago": "paid",
        "paid": "paid",
    }
