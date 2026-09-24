"""Importacao CSV e sincronizacao via conversionReport da Shopee."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from core.importers.base import BaseCSVImporter, SaleImportRow
from core.platforms.shopee_api import graphql_request

logger = logging.getLogger(__name__)
MONEY = Decimal("0.01")
STATUS_MAP = {
    "COMPLETED": "confirmed",
    "CANCELLED": "cancelled",
    "PENDING": "pending",
    "UNPAID": "pending",
}
_BOT_SUB_ID = re.compile(r"^b([0-9a-fA-F]{8})$")
_GROUP_SUB_ID = re.compile(r"^g([0-9a-fA-F]{8})$")


def parse_attribution_sub_ids(utm_content: str | None) -> tuple[str | None, str | None]:
    """Extrai os prefixos UUID dos SubIds unidos por `-` no utmContent da Shopee.

    O Help Center da Shopee documenta o utm_content como os SubIds concatenados
    por hífen. O parse fica isolado para que uma mudança desse contrato não
    contamine a sincronização de vendas.
    """
    bot_prefix = group_prefix = None
    for token in (utm_content or "").removeprefix("shopee:").split("-"):
        bot_match = _BOT_SUB_ID.fullmatch(token)
        group_match = _GROUP_SUB_ID.fullmatch(token)
        if bot_match:
            bot_prefix = bot_match.group(1).lower()
        elif group_match:
            group_prefix = group_match.group(1).lower()
    return bot_prefix, group_prefix


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


def _status(value: object) -> str:
    raw = str(value or "").upper()
    mapped = STATUS_MAP.get(raw)
    if mapped is None:
        logger.warning("Status desconhecido da Shopee: %s; usando pending", raw)
        return "pending"
    return mapped


def _money(value: object) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY)


def parse_conversion_report(report: dict[str, Any]) -> list[SaleImportRow]:
    """Converte conversoes em uma linha por pedido, sem aritmetica em float."""
    rows: list[SaleImportRow] = []
    line = 1
    for conversion in report.get("nodes") or []:
        ordered_at = datetime.fromtimestamp(int(conversion["purchaseTime"]), tz=timezone.utc)
        for order in conversion.get("orders") or []:
            items = order.get("items") or []
            names = [str(item.get("itemName") or "").strip() for item in items]
            product_name = names[0] if names else None
            if product_name and len(items) > 1:
                product_name = f"{product_name} +{len(items) - 1}"
            quantity = sum(int(item.get("qty") or 0) for item in items)
            gross_amount = sum(
                (_money(item.get("itemPrice")) * int(item.get("qty") or 0) for item in items),
                Decimal("0.00"),
            ).quantize(MONEY)
            commission = sum(
                (_money(item.get("itemTotalCommission")) for item in items),
                Decimal("0.00"),
            ).quantize(MONEY)
            rows.append(
                SaleImportRow(
                    line=line,
                    external_id=str(order["orderId"]),
                    product_name=product_name,
                    quantity=quantity,
                    gross_amount=gross_amount,
                    commission=commission,
                    commission_rate=None,
                    status=_status(order.get("orderStatus")),
                    ordered_at=ordered_at,
                    confirmed_at=None,
                    sub_id=str(conversion["utmContent"])
                    if conversion.get("utmContent") is not None
                    else None,
                    bot_id=None,
                    group_id=None,
                    buyer_hash=None,
                    raw={
                        "conversionId": conversion.get("conversionId"),
                        "orderStatus": order.get("orderStatus"),
                    },
                )
            )
            line += 1
    return rows


def _query(start_ts: int, end_ts: int, scroll_id: str | None) -> str:
    scroll = f", scrollId: {json.dumps(scroll_id)}" if scroll_id else ""
    return (
        "{ conversionReport("
        f"purchaseTimeStart: {start_ts}, purchaseTimeEnd: {end_ts}, limit: 500{scroll}"
        ") { nodes { conversionId purchaseTime clickTime totalCommission netCommission "
        "buyerType utmContent orders { orderId orderStatus items { itemName itemPrice qty "
        "itemTotalCommission } } } pageInfo { hasNextPage scrollId } } }"
    )


def fetch_conversion_report(
    app_id: str,
    secret: str,
    start_at: datetime,
    end_at: datetime,
) -> list[SaleImportRow]:
    """Busca todas as paginas do conversionReport usando o scrollId oficial."""
    rows: list[SaleImportRow] = []
    scroll_id: str | None = None
    with httpx.Client(timeout=30.0) as client:
        while True:
            query = _query(int(start_at.timestamp()), int(end_at.timestamp()), scroll_id)
            try:
                data = graphql_request(client, query, app_id=app_id, secret=secret)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403}:
                    raise PermissionError(
                        f"Shopee recusou a credencial (HTTP {exc.response.status_code})"
                    ) from exc
                raise
            report = data.get("conversionReport") or {}
            rows.extend(parse_conversion_report(report))
            page_info = report.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            next_scroll = page_info.get("scrollId")
            if not next_scroll or next_scroll == scroll_id:
                raise RuntimeError("Shopee informou proxima pagina sem novo scrollId")
            scroll_id = str(next_scroll)
    return rows
