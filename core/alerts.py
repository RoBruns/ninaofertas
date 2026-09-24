"""Deteccao de condicoes que realmente exigem acao humana."""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core import db
from core.bot_settings import BotSettings
from core.models import (
    Alert,
    AutomationRun,
    Bot,
    BotGroup,
    Envio,
    Event,
    Expense,
    ExpenseCategory,
    Group,
    Platform,
    PlatformAccount,
    PlatformCredential,
    Sale,
    User,
)
from core.settings import settings

logger = logging.getLogger(__name__)

OFFLINE_INTERVAL_MULTIPLIER = 3
CONSECUTIVE_FAILURE_THRESHOLD = 3
SEND_FAILURE_THRESHOLD = 3
RECURRING_ERROR_THRESHOLD = 10
SALES_STALE_HOURS = 36
TRAFFIC_RECENT_DAYS = 7
TRAFFIC_HISTORY_DAYS = 30
AUTH_EXPIRING_HOURS = 48
EVENT_ALERT_WINDOW_HOURS = 24
EVENT_RETENTION_DAYS = 30

ACTIVE_ALERT_STATUSES = ("open", "acknowledged")


@dataclass(frozen=True)
class AlertCondition:
    owner_id: UUID
    type: str
    severity: str
    dedup_key: str
    title: str
    entity_type: str | None = None
    entity_id: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class Detector:
    name: str
    alert_types: tuple[str, ...]
    function: Callable[[Session, datetime], list[AlertCondition]]


def _first_admin(session: Session) -> User | None:
    return session.scalar(
        select(User)
        .where(User.role == "admin", User.is_active.is_(True))
        .order_by(User.created_at, User.id)
        .limit(1)
    )


def _missing_owner_event(session: Session, detector: str, entity_id: str | None = None) -> None:
    session.add(
        Event(
            entity_type="alert_detector",
            entity_id=entity_id,
            level="error",
            type="alert_owner_missing",
            message="Alerta nao criado porque nao ha administrador ativo",
            detail={"detector": detector},
        )
    )


def detect_bot_offline(session: Session, now: datetime) -> list[AlertCondition]:
    conditions: list[AlertCondition] = []
    bots = list(session.scalars(select(Bot).where(Bot.status == "active")))
    for bot in bots:
        try:
            interval = BotSettings.model_validate(bot.settings).schedule.check_interval
        except Exception:
            interval = settings.check_interval
        latest = session.scalar(
            select(AutomationRun.started_at)
            .where(AutomationRun.bot_id == bot.id)
            .order_by(AutomationRun.started_at.desc())
            .limit(1)
        )
        reference = latest or bot.created_at
        if reference <= now - timedelta(seconds=interval * OFFLINE_INTERVAL_MULTIPLIER):
            conditions.append(
                AlertCondition(
                    bot.owner_id,
                    "bot_offline",
                    "critical",
                    f"bot_offline:{bot.id}",
                    f"Bot {bot.name} parou de rodar",
                    "bot",
                    str(bot.id),
                    f"Ultima execucao: {latest.isoformat() if latest else 'nunca'}",
                )
            )

    if not bots:
        latest_legacy = session.scalar(
            select(AutomationRun.started_at)
            .where(AutomationRun.bot_id.is_(None))
            .order_by(AutomationRun.started_at.desc())
            .limit(1)
        )
        if latest_legacy is not None and latest_legacy <= now - timedelta(
            seconds=settings.check_interval * OFFLINE_INTERVAL_MULTIPLIER
        ):
            admin = _first_admin(session)
            if admin is None:
                _missing_owner_event(session, "bot_offline", "legacy")
            else:
                conditions.append(
                    AlertCondition(
                        admin.id,
                        "bot_offline",
                        "critical",
                        "bot_offline:legacy",
                        "Bot legado parou de rodar",
                        "worker",
                        "legacy",
                        f"Ultima execucao: {latest_legacy.isoformat()}",
                    )
                )
    return conditions


def detect_automation_failing(session: Session, _now: datetime) -> list[AlertCondition]:
    conditions = []
    for bot in session.scalars(select(Bot).where(Bot.status == "active")):
        statuses = list(
            session.scalars(
                select(AutomationRun.status)
                .where(AutomationRun.bot_id == bot.id)
                .order_by(AutomationRun.started_at.desc())
                .limit(CONSECUTIVE_FAILURE_THRESHOLD)
            )
        )
        if len(statuses) == CONSECUTIVE_FAILURE_THRESHOLD and all(
            status == "failed" for status in statuses
        ):
            conditions.append(
                AlertCondition(
                    bot.owner_id,
                    "automation_failing",
                    "critical",
                    f"automation_failing:{bot.id}",
                    f"Bot {bot.name} falhando em sequência",
                    "bot",
                    str(bot.id),
                )
            )
    return conditions


def _credential_conditions(
    session: Session, now: datetime, *, expiring: bool
) -> list[AlertCondition]:
    rows = session.execute(
        select(PlatformCredential, PlatformAccount)
        .join(PlatformAccount, PlatformAccount.id == PlatformCredential.account_id)
        .where(PlatformAccount.status == "active")
    )
    conditions = []
    for credential, account in rows:
        if expiring:
            matches = credential.status == "expiring" and (
                credential.expires_at is None
                or now < credential.expires_at <= now + timedelta(hours=AUTH_EXPIRING_HOURS)
            )
            alert_type, severity = "auth_expiring", "warning"
            title = f"Credencial de {account.label} expira em breve"
        else:
            matches = credential.status in {"invalid", "expired"}
            alert_type, severity = "auth_expired", "critical"
            title = f"Credencial de {account.label} expirada — renove em Contas"
        if matches:
            conditions.append(
                AlertCondition(
                    account.owner_id,
                    alert_type,
                    severity,
                    f"{alert_type}:{credential.id}",
                    title,
                    "platform_credential",
                    str(credential.id),
                    f"Status da credencial: {credential.status}",
                )
            )
    return conditions


def detect_auth_expired(session: Session, now: datetime) -> list[AlertCondition]:
    return _credential_conditions(session, now, expiring=False)


def detect_auth_expiring(session: Session, now: datetime) -> list[AlertCondition]:
    return _credential_conditions(session, now, expiring=True)


def detect_send_failed(session: Session, now: datetime) -> list[AlertCondition]:
    rows = session.execute(
        select(Group, func.count(Envio.id))
        .join(Envio, Envio.group_id == Group.id)
        .where(Envio.status == "falha", Envio.enviado_em >= now - timedelta(hours=1))
        .group_by(Group.id)
        .having(func.count(Envio.id) >= SEND_FAILURE_THRESHOLD)
    )
    return [
        AlertCondition(
            group.owner_id,
            "send_failed",
            "warning",
            f"send_failed:{group.id}",
            f"Falhas ao publicar no grupo {group.name or group.whatsapp_id}",
            "group",
            str(group.id),
            f"{count} falhas na ultima hora",
        )
        for group, count in rows
    ]


def detect_group_inaccessible(session: Session, _now: datetime) -> list[AlertCondition]:
    rows = session.execute(
        select(Group, Bot)
        .join(BotGroup, BotGroup.group_id == Group.id)
        .join(Bot, Bot.id == BotGroup.bot_id)
        .where(
            Bot.status == "active",
            BotGroup.is_active.is_(True),
            or_(
                Group.status == "inaccessible",
                Group.is_announce.is_(True) & Group.bot_is_admin.is_not(True),
            ),
        )
    )
    by_group: dict[UUID, tuple[Group, Bot]] = {group.id: (group, bot) for group, bot in rows}
    return [
        AlertCondition(
            group.owner_id,
            "group_inaccessible",
            "warning",
            f"group_inaccessible:{group.id}",
            f"Mensagens não chegam no grupo {group.name or group.whatsapp_id}",
            "group",
            str(group.id),
            f"Bot ativo: {bot.name}",
        )
        for group, bot in by_group.values()
    ]


def _event_owner(session: Session, event: Event) -> UUID | None:
    if event.bot_id is not None:
        return session.scalar(select(Bot.owner_id).where(Bot.id == event.bot_id))
    try:
        entity_uuid = UUID(event.entity_id or "")
    except ValueError:
        return None
    if event.entity_type in {"platform_account", "account"}:
        return session.scalar(
            select(PlatformAccount.owner_id).where(PlatformAccount.id == entity_uuid)
        )
    if event.entity_type == "group":
        return session.scalar(select(Group.owner_id).where(Group.id == entity_uuid))
    return None


def detect_recurring_error(session: Session, now: datetime) -> list[AlertCondition]:
    events = list(
        session.scalars(
            select(Event).where(
                Event.level.in_(("error", "critical")),
                Event.created_at >= now - timedelta(hours=1),
            )
        )
    )
    counts: Counter[tuple[UUID, str]] = Counter()
    for event in events:
        owner_id = _event_owner(session, event)
        if owner_id is None:
            admin = _first_admin(session)
            if admin is None:
                _missing_owner_event(session, "recurring_error", str(event.id))
                continue
            owner_id = admin.id
        counts[(owner_id, event.type)] += 1
    return [
        AlertCondition(
            owner_id,
            "recurring_error",
            "warning",
            f"recurring_error:{event_type}",
            f"Erro recorrente: {event_type}",
            "event_type",
            event_type,
            f"{count} ocorrencias na ultima hora",
        )
        for (owner_id, event_type), count in counts.items()
        if count >= RECURRING_ERROR_THRESHOLD
    ]


def detect_sales_sync_stale(session: Session, now: datetime) -> list[AlertCondition]:
    rows = session.execute(
        select(PlatformAccount, Platform)
        .join(Platform, Platform.id == PlatformAccount.platform_id)
        .where(PlatformAccount.status == "active", Platform.is_active.is_(True))
    )
    conditions = []
    for account, platform in rows:
        capabilities = platform.capabilities or {}
        if not (capabilities.get("commission_api") or capabilities.get("commission_scrape")):
            continue
        latest = session.scalar(
            select(func.max(Sale.imported_at)).where(Sale.account_id == account.id)
        )
        if latest is None or latest <= now - timedelta(hours=SALES_STALE_HOURS):
            conditions.append(
                AlertCondition(
                    account.owner_id,
                    "sales_sync_stale",
                    "warning",
                    f"sales_sync_stale:{account.id}",
                    f"Vendas de {account.label} desatualizadas",
                    "platform_account",
                    str(account.id),
                    f"Ultima importacao: {latest.isoformat() if latest else 'nunca'}",
                )
            )
    return conditions


def detect_traffic_spend_stale(session: Session, now: datetime) -> list[AlertCondition]:
    recent_cutoff = now.date() - timedelta(days=TRAFFIC_RECENT_DAYS)
    history_cutoff = recent_cutoff - timedelta(days=TRAFFIC_HISTORY_DAYS)
    rows = session.execute(
        select(Expense.owner_id, Expense.incurred_on)
        .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
        .where(
            ExpenseCategory.slug == "trafego",
            Expense.incurred_on >= history_cutoff,
        )
    )
    by_owner: dict[UUID, list[Any]] = {}
    for owner_id, incurred_on in rows:
        by_owner.setdefault(owner_id, []).append(incurred_on)
    return [
        AlertCondition(
            owner_id,
            "traffic_spend_stale",
            "warning",
            f"traffic_spend_stale:{owner_id}",
            "Lance os gastos de tráfego",
            "owner",
            str(owner_id),
        )
        for owner_id, dates in by_owner.items()
        if not any(day >= recent_cutoff for day in dates)
        and any(history_cutoff <= day < recent_cutoff for day in dates)
    ]


def _detect_recent_ml_event(
    session: Session, now: datetime, event_type: str, title_template: str
) -> list[AlertCondition]:
    events = list(
        session.scalars(
            select(Event)
            .where(
                Event.type == event_type,
                Event.created_at >= now - timedelta(hours=EVENT_ALERT_WINDOW_HOURS),
            )
            .order_by(Event.created_at.desc())
        )
    )
    conditions: dict[tuple[UUID, str], AlertCondition] = {}
    for event in events:
        owner_id = _event_owner(session, event)
        if owner_id is None:
            admin = _first_admin(session)
            if admin is None:
                _missing_owner_event(session, event_type, str(event.id))
                continue
            owner_id = admin.id
        date_value = (event.detail or {}).get("date")
        try:
            display_date = datetime.fromisoformat(str(date_value)).strftime("%d/%m")
        except ValueError:
            display_date = event.created_at.strftime("%d/%m")
        entity_key = event.entity_id or "global"
        conditions.setdefault(
            (owner_id, entity_key),
            AlertCondition(
                owner_id,
                event_type,
                "warning",
                f"{event_type}:{entity_key}",
                title_template.format(date=display_date),
                event.entity_type,
                event.entity_id,
                json.dumps(event.detail, ensure_ascii=False, default=str) if event.detail else None,
            ),
        )
    return list(conditions.values())


def detect_ml_sales_truncated(session: Session, now: datetime) -> list[AlertCondition]:
    return _detect_recent_ml_event(
        session, now, "ml_sales_truncated", "Sincronização do ML incompleta em {date}"
    )


def detect_ml_reconciliation_mismatch(session: Session, now: datetime) -> list[AlertCondition]:
    return _detect_recent_ml_event(
        session, now, "ml_reconciliation_mismatch", "Vendas do ML nao batem com o painel"
    )


DETECTORS = (
    Detector("bot_offline", ("bot_offline",), detect_bot_offline),
    Detector("automation_failing", ("automation_failing",), detect_automation_failing),
    Detector("auth_expired", ("auth_expired",), detect_auth_expired),
    Detector("auth_expiring", ("auth_expiring",), detect_auth_expiring),
    Detector("send_failed", ("send_failed",), detect_send_failed),
    Detector("group_inaccessible", ("group_inaccessible",), detect_group_inaccessible),
    Detector("recurring_error", ("recurring_error",), detect_recurring_error),
    Detector("sales_sync_stale", ("sales_sync_stale",), detect_sales_sync_stale),
    Detector("traffic_spend_stale", ("traffic_spend_stale",), detect_traffic_spend_stale),
    Detector("ml_sales_truncated", ("ml_sales_truncated",), detect_ml_sales_truncated),
    Detector(
        "ml_reconciliation_mismatch",
        ("ml_reconciliation_mismatch",),
        detect_ml_reconciliation_mismatch,
    ),
)


def _upsert_conditions(
    session: Session,
    conditions: Iterable[AlertCondition],
    alert_types: tuple[str, ...],
    now: datetime,
) -> None:
    current_keys: set[tuple[UUID, str]] = set()
    for condition in conditions:
        current_keys.add((condition.owner_id, condition.dedup_key))
        statement = insert(Alert).values(
            owner_id=condition.owner_id,
            type=condition.type,
            severity=condition.severity,
            entity_type=condition.entity_type,
            entity_id=condition.entity_id,
            title=condition.title,
            detail=condition.detail,
            status="open",
            first_seen_at=now,
            last_seen_at=now,
            dedup_key=condition.dedup_key,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[Alert.owner_id, Alert.dedup_key],
            index_where=text("status IN ('open', 'acknowledged')"),
            set_={
                "severity": statement.excluded.severity,
                "title": statement.excluded.title,
                "detail": statement.excluded.detail,
                "last_seen_at": now,
            },
        )
        session.execute(statement)

    active = list(
        session.scalars(
            select(Alert).where(
                Alert.type.in_(alert_types), Alert.status.in_(ACTIVE_ALERT_STATUSES)
            )
        )
    )
    for alert in active:
        if (alert.owner_id, alert.dedup_key) not in current_keys:
            alert.status = "resolved"
            alert.resolved_at = now


def detect_alerts(
    *,
    now: datetime | None = None,
    detectors: Iterable[Detector] | None = None,
) -> None:
    """Executa e confirma cada detector em transacao independente."""
    detected_at = now or datetime.now(timezone.utc)
    for detector in detectors or DETECTORS:
        try:
            with db.get_session() as session:
                conditions = detector.function(session, detected_at)
                _upsert_conditions(session, conditions, detector.alert_types, detected_at)
        except Exception as exc:
            logger.exception(f"Detector de alertas {detector.name} falhou: {exc}")


def cleanup_events(*, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=EVENT_RETENTION_DAYS)
    with db.get_session() as session:
        result = session.execute(delete(Event).where(Event.created_at < cutoff))
        return int(result.rowcount or 0)


__all__ = [
    "ACTIVE_ALERT_STATUSES",
    "DETECTORS",
    "Detector",
    "cleanup_events",
    "detect_alerts",
]
