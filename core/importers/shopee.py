"""Mapeamento explicito do relatorio CSV da Shopee."""

from core.importers.base import BaseCSVImporter


class ShopeeCSVImporter(BaseCSVImporter):
    COLUMN_ALIASES = {
        "external_id": ("order_id", "order id", "id do pedido", "id_pedido"),
        "product_name": ("product_name", "product name", "nome do produto", "produto"),
        "quantity": ("quantity", "qty", "quantidade"),
        "gross_amount": ("gross_amount", "order_amount", "valor do pedido", "valor_pedido"),
        "commission": ("commission", "commission_amount", "comissao", "valor da comissao"),
        "commission_rate": ("commission_rate", "taxa de comissao", "percentual comissao"),
        "status": ("status", "order_status", "status do pedido"),
        "ordered_at": ("ordered_at", "order_time", "data do pedido", "data_pedido"),
        "confirmed_at": ("confirmed_at", "completed_time", "data de confirmacao"),
        "sub_id": ("sub_id", "subid", "sub id"),
        "bot_id": ("bot_id",),
        "group_id": ("group_id",),
        "buyer_hash": ("buyer_hash",),
    }
    STATUS_MAP = {
        "pendente": "pending",
        "pending": "pending",
        "confirmado": "confirmed",
        "confirmed": "confirmed",
        "concluido": "confirmed",
        "cancelado": "cancelled",
        "cancelled": "cancelled",
        "pago": "paid",
        "paid": "paid",
    }
