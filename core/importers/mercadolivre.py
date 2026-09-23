"""Importacao CSV e leitura do painel de afiliados do Mercado Livre."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from core.importers.base import BaseCSVImporter, SaleImportRow

logger = logging.getLogger(__name__)
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
MONEY = Decimal("0.01")
RATE = Decimal("0.0001")
SCRIPT_MARKER = "_n.ctx.r="
STATUS_MAP = {
    "IN_REVIEW": "pending",
    "APPROVED": "confirmed",
    "PAID": "confirmed",
    "CANCELED": "cancelled",
    "CANCELLED": "cancelled",
    "REJECTED": "cancelled",
}


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


class ExpiredDashboardSession(ValueError):
    """O HTML recebido nao e o painel autenticado esperado."""


def _money(value: object) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY)


def _status(value: object) -> str:
    raw = str(value or "").upper()
    mapped = STATUS_MAP.get(raw)
    if mapped is None:
        logger.warning("Status desconhecido do Mercado Livre: %s; usando pending", raw)
        return "pending"
    return mapped


def extract_page_props(html: str) -> dict[str, Any]:
    marker_at = html.find(SCRIPT_MARKER)
    if marker_at < 0:
        raise ExpiredDashboardSession("Painel autenticado do Mercado Livre ausente")
    try:
        root, _ = json.JSONDecoder().raw_decode(html[marker_at + len(SCRIPT_MARKER) :])
    except (json.JSONDecodeError, TypeError):
        raise ExpiredDashboardSession("Painel autenticado do Mercado Livre invalido") from None
    page_props = (root.get("appProps") or {}).get("pageProps") or {}
    if not page_props.get("generalKpis"):
        raise ExpiredDashboardSession("Painel autenticado do Mercado Livre ausente")
    return page_props


def _kpi(items: object, wanted: str) -> Decimal | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("id") == wanted:
            return _money(item.get("current_amount"))
    return None


def parse_dashboard(html: str) -> tuple[list[SaleImportRow], dict[str, Any]]:
    """Extrai vendas e metadados de reconciliacao do JSON server-side."""
    page_props = extract_page_props(html)
    sales_block = page_props.get("sales") or {}
    raw_sales = sales_block.get("item_list") or []
    canceled_ids = {
        str(item.get("id"))
        for item in ((page_props.get("canceledOrders") or {}).get("item_list") or [])
        if isinstance(item, dict) and item.get("id") is not None
    }
    rows: list[SaleImportRow] = []
    for line, item in enumerate(raw_sales, start=1):
        external_id = str(item["id"])
        ordered_local = datetime.strptime(str(item["date"]), "%d/%m/%Y").replace(tzinfo=SAO_PAULO)
        status = "cancelled" if external_id in canceled_ids else _status(item.get("status"))
        percentage = Decimal(str(item.get("commissionPercentage") or 0))
        rows.append(
            SaleImportRow(
                line=line,
                external_id=external_id,
                product_name=str(item.get("productName") or "") or None,
                quantity=int(item.get("saleUnits") or 0),
                gross_amount=_money(item.get("saleValue")),
                commission=_money(item.get("commissionValue")),
                commission_rate=(percentage / Decimal("100")).quantize(RATE),
                status=status,
                ordered_at=ordered_local.astimezone(timezone.utc),
                confirmed_at=None,
                sub_id=None,
                bot_id=None,
                group_id=None,
                buyer_hash=None,
                raw={
                    key: item.get(key)
                    for key in (
                        "purchaseId",
                        "commissionPercentage",
                        "saleType",
                        "categoryName",
                        "storeName",
                    )
                    if item.get(key) is not None
                },
            )
        )
    general_kpis = page_props.get("generalKpis") or {}
    meta = {
        "total_results": int(sales_block.get("total_results") or 0),
        "commission_total": _kpi(general_kpis.get("commissions"), "summary"),
        "sales_total": _kpi(general_kpis.get("data"), "sales"),
    }
    return rows, meta
