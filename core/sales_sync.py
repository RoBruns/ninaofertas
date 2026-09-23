"""Sincronizacao idempotente de vendas para contas de plataforma."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import db
from core.credentials import mark_account_credentials_invalid, read_account_credentials
from core.importers.base import SaleImportRow
from core.importers.mercadolivre import ExpiredDashboardSession, parse_dashboard
from core.importers.shopee import fetch_conversion_report
from core.models import Event, Platform, PlatformAccount, PlatformCredential, Sale

ML_DASHBOARD_URL = "https://www.mercadolivre.com.br/afiliados/dashboard"
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
MONEY = Decimal("0.01")


@dataclass(frozen=True)
class SyncResult:
    imported: int = 0
    skipped: int = 0
    auth_expired: bool = False


def _event(
    session: Session,
    account_id: UUID,
    event_type: str,
    message: str,
    detail: dict[str, object] | None = None,
) -> None:
    session.add(
        Event(
            entity_type="platform_account",
            entity_id=str(account_id),
            level="warning",
            type=event_type,
            message=message,
            detail=detail,
        )
    )


def _values(row: SaleImportRow, account: PlatformAccount, source: str) -> dict[str, object]:
    return {
        "owner_id": account.owner_id,
        "account_id": account.id,
        "platform_id": account.platform_id,
        "external_id": row.external_id,
        "sub_id": row.sub_id,
        "bot_id": row.bot_id,
        "group_id": row.group_id,
        "product_name": row.product_name,
        "quantity": row.quantity,
        "gross_amount": row.gross_amount,
        "commission": row.commission,
        "commission_rate": row.commission_rate,
        "status": row.status,
        "buyer_hash": row.buyer_hash,
        "ordered_at": row.ordered_at,
        "confirmed_at": row.confirmed_at,
        "source": source,
        "raw": row.raw,
    }


def _upsert(account_id: UUID, rows: list[SaleImportRow], source: str) -> SyncResult:
    imported = skipped = 0
    with db.get_session() as session:
        account = session.get(PlatformAccount, account_id)
        if account is None:
            raise ValueError("Conta de plataforma nao encontrada")
        now = datetime.now(timezone.utc)
        for row in rows:
            values = _values(row, account, source)
            sale = session.scalar(
                select(Sale).where(
                    Sale.platform_id == account.platform_id,
                    Sale.external_id == row.external_id,
                )
            )
            if sale is None:
                session.add(Sale(id=uuid4(), imported_at=now, **values))
                imported += 1
                continue
            if sale.owner_id != account.owner_id:
                raise ValueError("Venda ja pertence a outro usuario")
            changed = any(getattr(sale, field) != value for field, value in values.items())
            if not changed:
                skipped += 1
                continue
            for field, value in values.items():
                setattr(sale, field, value)
            sale.imported_at = now
            imported += 1
    return SyncResult(imported=imported, skipped=skipped)


def _load_account(account_id: UUID) -> tuple[str, dict, dict[str, str]]:
    with db.get_session() as session:
        account = session.get(PlatformAccount, account_id)
        if account is None or account.status != "active":
            raise ValueError("Conta de plataforma ativa nao encontrada")
        platform = session.get(Platform, account.platform_id)
        if platform is None:
            raise ValueError("Plataforma da conta nao encontrada")
        credentials, _ = read_account_credentials(session, account.id)
        config = dict(account.config or {})
        if account.external_id:
            config.setdefault("external_id", account.external_id)
        return platform.slug, config, credentials


def _mark_success(account_id: UUID, kind: str) -> None:
    with db.get_session() as session:
        credential = session.scalar(
            select(PlatformCredential).where(
                PlatformCredential.account_id == account_id,
                PlatformCredential.kind == kind,
            )
        )
        if credential is not None:
            credential.status = "valid"
            credential.last_success_at = datetime.now(timezone.utc)
            credential.last_error = None
            credential.last_error_at = None


def _sync_shopee(account_id: UUID, config: dict, credentials: dict[str, str]) -> SyncResult:
    app_id = str(
        config.get("app_id")
        or config.get("affiliate_id")
        or config.get("external_id")
        or credentials.get("app_id")
        or credentials.get("api_key")
        or ""
    )
    secret = next(
        (credentials[key] for key in ("app_secret", "secret") if credentials.get(key)), ""
    )
    if not app_id or not secret:
        raise ValueError("Credenciais da Shopee incompletas")
    end_at = datetime.now(timezone.utc)
    try:
        rows = fetch_conversion_report(app_id, secret, end_at - timedelta(days=14), end_at)
    except PermissionError:
        mark_account_credentials_invalid(account_id, "Shopee recusou a credencial")
        return SyncResult(auth_expired=True)
    result = _upsert(account_id, rows, "api")
    _mark_success(account_id, "app_secret")
    return result


def _day_range(day: date) -> str:
    start = datetime.combine(day, datetime_time.min, SAO_PAULO)
    end = start + timedelta(days=1)
    return f"{start.isoformat(timespec='milliseconds')}--{end.isoformat(timespec='milliseconds')}"


def _sync_ml(account_id: UUID, credentials: dict[str, str]) -> SyncResult:
    cookie = credentials.get("cookie") or ""
    if not cookie:
        raise ValueError("Cookie do Mercado Livre ausente")
    imported = skipped = 0
    yesterday = datetime.now(SAO_PAULO).date() - timedelta(days=1)
    with httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0"},
    ) as client:
        for offset in range(14):
            day = yesterday - timedelta(days=offset)
            try:
                response = client.get(
                    ML_DASHBOARD_URL,
                    params={"filter_time_range": _day_range(day)},
                )
            except httpx.HTTPError:
                raise RuntimeError("Falha ao consultar painel do Mercado Livre") from None
            if response.status_code in {401, 403}:
                mark_account_credentials_invalid(account_id, "Mercado Livre recusou a credencial")
                return SyncResult(imported, skipped, auth_expired=True)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                raise RuntimeError("Falha ao consultar painel do Mercado Livre") from None
            try:
                rows, meta = parse_dashboard(response.text)
            except ExpiredDashboardSession:
                mark_account_credentials_invalid(account_id, "Sessao do Mercado Livre expirada")
                return SyncResult(imported, skipped, auth_expired=True)
            result = _upsert(account_id, rows, "scrape")
            imported += result.imported
            skipped += result.skipped
            row_commission = sum((row.commission for row in rows), Decimal("0.00")).quantize(MONEY)
            row_sales = sum((row.gross_amount for row in rows), Decimal("0.00")).quantize(MONEY)
            expected_commission = meta["commission_total"]
            expected_sales = meta["sales_total"]
            with db.get_session() as session:
                if meta["total_results"] > len(rows):
                    _event(
                        session,
                        account_id,
                        "ml_sales_truncated",
                        "Painel do Mercado Livre excedeu o limite diario",
                        {
                            "date": day.isoformat(),
                            "total_results": meta["total_results"],
                            "items": len(rows),
                        },
                    )
                if (
                    expected_commission is not None
                    and expected_sales is not None
                    and (row_commission != expected_commission or row_sales != expected_sales)
                ):
                    _event(
                        session,
                        account_id,
                        "ml_reconciliation_mismatch",
                        "Totais do painel do Mercado Livre nao conferem com as vendas",
                        {
                            "date": day.isoformat(),
                            "commission_rows": str(row_commission),
                            "commission_kpi": str(expected_commission),
                            "sales_rows": str(row_sales),
                            "sales_kpi": str(expected_sales),
                        },
                    )
            if offset < 13:
                time.sleep(random.uniform(3.0, 5.0))
    _mark_success(account_id, "cookie")
    return SyncResult(imported=imported, skipped=skipped)


def sync_account(account_id: UUID) -> SyncResult:
    platform_slug, config, credentials = _load_account(account_id)
    if platform_slug == "shopee":
        return _sync_shopee(account_id, config, credentials)
    if platform_slug == "mercadolivre":
        return _sync_ml(account_id, credentials)
    raise ValueError("Plataforma sem sincronizacao de vendas")


def sync_all_active_accounts() -> None:
    """Sincroniza contas elegiveis isolando completamente a falha de cada uma."""
    try:
        with db.get_session() as session:
            accounts = session.execute(
                select(PlatformAccount.id, Platform.capabilities)
                .join(Platform, Platform.id == PlatformAccount.platform_id)
                .where(
                    PlatformAccount.status == "active",
                    Platform.is_active.is_(True),
                    Platform.slug.in_(("shopee", "mercadolivre")),
                )
            )
            account_ids = [
                account_id
                for account_id, capabilities in accounts
                if bool(
                    (capabilities or {}).get("commission_api")
                    or (capabilities or {}).get("commission_scrape")
                )
            ]
    except Exception:
        return
    for account_id in account_ids:
        try:
            sync_account(account_id)
        except Exception:
            try:
                with db.get_session() as session:
                    _event(
                        session,
                        account_id,
                        "commission_import_failed",
                        "Sincronizacao automatica de vendas falhou",
                    )
            except Exception:
                continue


__all__ = ["SyncResult", "sync_account", "sync_all_active_accounts"]
