"""Modelos SQLAlchemy 2.0 do schema da aplicação."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID as PythonUUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Variants apenas para os testes unitários legados em SQLite. No Postgres, os
# tipos nativos abaixo são emitidos sem alteração.
UUID_TYPE = UUID(as_uuid=True).with_variant(String(36), "sqlite")
JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")
CITEXT_TYPE = CITEXT().with_variant(String(), "sqlite")
INET_TYPE = INET().with_variant(String(45), "sqlite")
TIMESTAMPTZ = DateTime(timezone=True)
MONEY = Numeric(14, 2)
PERCENTAGE = Numeric(7, 4)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(CITEXT_TYPE, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, server_default=text("'admin'"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index(
            "ix_audit_logs_entity_created_at", "entity_type", "entity_id", text("created_at DESC")
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    ip: Mapped[str | None] = mapped_column(INET_TYPE)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))


class Platform(Base):
    __tablename__ = "platforms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE, server_default=text("'{}'::jsonb")
    )


class PlatformAccount(Base):
    __tablename__ = "platform_accounts"
    __table_args__ = (UniqueConstraint("owner_id", "platform_id", "label"),)
    id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[PythonUUID] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    platform_id: Mapped[int] = mapped_column(Integer, ForeignKey("platforms.id"))
    label: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    config: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, server_default=text("'{}'::jsonb"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))


class PlatformCredential(Base):
    __tablename__ = "platform_credentials"
    __table_args__ = (UniqueConstraint("account_id", "kind"),)
    id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    account_id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, ForeignKey("platform_accounts.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(Text)
    ciphertext: Mapped[bytes] = mapped_column()
    key_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    fingerprint: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'unknown'"))
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    last_rotated_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    last_success_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))


class Phone(Base):
    __tablename__ = "phones"
    __table_args__ = (UniqueConstraint("owner_id", "number"),)
    id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[PythonUUID] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    label: Mapped[str] = mapped_column(Text)
    number: Mapped[str] = mapped_column(Text)
    evolution_instance: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'unknown'"))
    last_seen_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))


class Niche(Base):
    __tablename__ = "niches"
    __table_args__ = (UniqueConstraint("owner_id", "slug"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[PythonUUID] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    slug: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)


class Bot(Base):
    __tablename__ = "bots"
    __table_args__ = (UniqueConstraint("owner_id", "slug"),)
    id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[PythonUUID] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text)
    niche_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("niches.id"))
    phone_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("phones.id"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'paused'"))
    settings: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, server_default=text("'{}'::jsonb"))
    message_template: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    last_success_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("phone_id", "whatsapp_id"),)
    id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[PythonUUID] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    phone_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("phones.id"))
    whatsapp_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    participants: Mapped[int | None] = mapped_column(Integer)
    is_announce: Mapped[bool | None] = mapped_column(Boolean)
    bot_is_admin: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    discovered_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    last_synced_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class BotGroup(Base):
    __tablename__ = "bot_groups"
    bot_id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class BotPlatformAccount(Base):
    __tablename__ = "bot_platform_accounts"
    bot_id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, ForeignKey("platform_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[PythonUUID] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    bot_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("bots.id"))
    niche_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("niches.id"))
    objective: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    started_at: Mapped[date | None] = mapped_column(Date)
    ended_at: Mapped[date | None] = mapped_column(Date)


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"
    __table_args__ = (UniqueConstraint("owner_id", "slug"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[PythonUUID] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    slug: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_expenses_amount_nonnegative"),
        UniqueConstraint("source", "external_id"),
        Index("ix_expenses_owner_incurred_on", "owner_id", text("incurred_on DESC")),
    )
    id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[PythonUUID] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    description: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(Text, server_default=text("'BRL'"))
    incurred_on: Mapped[date] = mapped_column(Date)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("expense_categories.id"))
    platform_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("platforms.id"))
    campaign_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("campaigns.id"))
    bot_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("bots.id"))
    niche_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("niches.id"))
    source: Mapped[str] = mapped_column(Text, server_default=text("'manual'"))
    external_id: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))


class Oferta(Base):
    """Tabela legada: tipos existentes são deliberadamente preservados."""

    __tablename__ = "ofertas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String, nullable=False)
    preco: Mapped[float] = mapped_column(Float, nullable=False)
    preco_anterior: Mapped[float | None] = mapped_column(Float)
    desconto: Mapped[float | None] = mapped_column(Float)
    loja: Mapped[str | None] = mapped_column(String)
    categoria: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String, unique=True, index=True)
    imagem: Mapped[str | None] = mapped_column(String)
    sku: Mapped[str | None] = mapped_column(String)
    capturado_em: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )
    platform_account_id: Mapped[PythonUUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("platform_accounts.id")
    )
    envios: Mapped[list[Envio]] = relationship(back_populates="oferta")


class Envio(Base):
    """Tabela legada: tipos existentes são deliberadamente preservados."""

    __tablename__ = "envios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    oferta_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ofertas.id"))
    enviado_em: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)
    grupo: Mapped[str | None] = mapped_column(String)
    mensagem: Mapped[str | None] = mapped_column(Text)
    preco_enviado: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(String)
    bot_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("bots.id"))
    group_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("groups.id"))
    sub_id: Mapped[str | None] = mapped_column(Text)
    oferta: Mapped[Oferta | None] = relationship(back_populates="envios")


class Click(Base):
    __tablename__ = "clicks"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sub_id: Mapped[str] = mapped_column(Text)
    bot_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("bots.id"))
    group_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("groups.id"))
    oferta_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ofertas.id"))
    clicked_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_hash: Mapped[str | None] = mapped_column(Text)


class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint("platform_id", "external_id"),
        Index("ix_sales_owner_ordered_at", "owner_id", text("ordered_at DESC")),
        Index("ix_sales_bot_ordered_at", "bot_id", text("ordered_at DESC")),
    )
    id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[PythonUUID] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    account_id: Mapped[PythonUUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("platform_accounts.id")
    )
    platform_id: Mapped[int] = mapped_column(Integer, ForeignKey("platforms.id"))
    external_id: Mapped[str] = mapped_column(Text)
    sub_id: Mapped[str | None] = mapped_column(Text)
    bot_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("bots.id"))
    group_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("groups.id"))
    oferta_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ofertas.id"))
    product_name: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    gross_amount: Mapped[Decimal] = mapped_column(MONEY)
    commission: Mapped[Decimal] = mapped_column(MONEY, server_default=text("0"))
    commission_rate: Mapped[Decimal | None] = mapped_column(PERCENTAGE)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    buyer_hash: Mapped[str | None] = mapped_column(Text)
    ordered_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    source: Mapped[str] = mapped_column(Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    imported_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))


class GroupJoin(Base):
    __tablename__ = "group_joins"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("groups.id"))
    bot_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("bots.id"))
    campaign_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("campaigns.id"))
    joined_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    member_hash: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)


class AutomationRun(Base):
    __tablename__ = "automation_runs"
    __table_args__ = (
        Index("ix_automation_runs_bot_started_at", "bot_id", text("started_at DESC")),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("bots.id"))
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    offers_found: Mapped[int | None] = mapped_column(Integer)
    offers_sent: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_level_created_at", "level", text("created_at DESC")),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("bots.id"))
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    level: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "dedup_key", "status", deferrable=True, name="uq_alerts_owner_dedup_status"
        ),
    )
    id: Mapped[PythonUUID] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[PythonUUID] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    first_seen_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))
    last_seen_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    dedup_key: Mapped[str] = mapped_column(Text)


class Command(Base):
    __tablename__ = "commands"
    __table_args__ = (
        Index(
            "ix_commands_pending",
            "status",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("bots.id"))
    type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    requested_by: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))
    picked_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    result: Mapped[str | None] = mapped_column(Text)


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "day", "bot_id", "group_id", "platform_id", "account_id", "campaign_id"
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[PythonUUID] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    day: Mapped[date] = mapped_column(Date)
    bot_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("bots.id"))
    group_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("groups.id"))
    platform_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("platforms.id"))
    account_id: Mapped[PythonUUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("platform_accounts.id")
    )
    campaign_id: Mapped[PythonUUID | None] = mapped_column(UUID_TYPE, ForeignKey("campaigns.id"))
    sends: Mapped[int | None] = mapped_column(Integer)
    clicks: Mapped[int | None] = mapped_column(Integer)
    orders: Mapped[int | None] = mapped_column(Integer)
    buyers: Mapped[int | None] = mapped_column(Integer)
    joins: Mapped[int | None] = mapped_column(Integer)
    revenue: Mapped[Decimal | None] = mapped_column(MONEY)
    commission: Mapped[Decimal | None] = mapped_column(MONEY)
    spend: Mapped[Decimal | None] = mapped_column(MONEY)
    computed_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))
