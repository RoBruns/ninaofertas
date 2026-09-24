"""Seed idempotente dos dados operacionais iniciais."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.channels import CANAIS
from core.db import normalize_database_url
from core.models import Bot, ExpenseCategory, Niche, Platform, User
from core.settings import settings

ROOT = Path(__file__).resolve().parent.parent

PLATFORMS = (
    (
        "shopee",
        "Shopee",
        {"offers": True, "affiliate_link": True, "coupons": True, "commission_api": True},
    ),
    (
        "mercadolivre",
        "Mercado Livre",
        {
            "offers": True,
            "affiliate_link": True,
            "coupons": False,
            "commission_api": False,
            "commission_scrape": True,
        },
    ),
    (
        "aliexpress",
        "AliExpress",
        {"offers": False, "affiliate_link": True, "coupons": False, "commission_api": False},
    ),
)
EXPENSE_CATEGORIES = (
    ("trafego", "Tráfego"),
    ("infra", "Infraestrutura"),
    ("chips", "Chips"),
    ("ferramentas", "Ferramentas"),
    ("outros", "Outros"),
)
NICHES = (("casa", "Casa"), ("automotivo", "Automotivo"))

FILTER_KEYS = (
    "preco_minimo",
    "preco_maximo",
    "desconto_minimo",
    "lojas",
    "categorias",
    "categorias_meli",
    "termos_busca",
    "palavras_chave",
    "produtos_especificos",
    "bloquear_produtos",
    "bloquear_termos",
    "excecoes_bloqueio",
    "max_vendas",
    "max_idade_oferta_horas",
)
PACING_KEYS = (
    "max_ofertas_por_ciclo",
    "intervalo_minutos_entre_ofertas",
    "max_ofertas_por_rajada",
    "janela_rajada_minutos",
    "pausa_entre_rajadas_minutos",
    "max_ofertas_por_hora",
    "max_ofertas_por_dia",
    "max_ofertas_globais_por_hora",
    "max_ofertas_globais_por_dia",
)
CONTENT_KEYS = (
    "aceitar_cupons",
    "aceitar_campanhas",
    "max_cupons_por_dia",
    "baseline_ciclos",
    "cupons_meli",
)


def _settings_from_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "filters": {key: config[key] for key in FILTER_KEYS if key in config},
        "pacing": {key: config[key] for key in PACING_KEYS if key in config},
        "content": {key: config[key] for key in CONTENT_KEYS if key in config},
        "schedule": {
            "check_interval": settings.check_interval,
            "quiet_hours": {"start": "23:00", "end": "07:00"},
        },
    }


def _upsert_platforms(session: Session) -> None:
    for slug, name, capabilities in PLATFORMS:
        statement = insert(Platform).values(slug=slug, name=name, capabilities=capabilities)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[Platform.slug],
                set_={
                    "name": statement.excluded.name,
                    "capabilities": statement.excluded.capabilities,
                },
            )
        )


def _admin(session: Session, email: str, password: str) -> User:
    from argon2 import PasswordHasher, Type

    user = session.scalar(select(User).where(User.email == email))
    if user is not None:
        return user
    password_hash = PasswordHasher(type=Type.ID).hash(password)
    user = User(email=email, password_hash=password_hash, name="Administrador", role="admin")
    session.add(user)
    session.flush()
    return user


def _upsert_owner_rows(session: Session, user: User) -> dict[str, Niche]:
    for slug, name in EXPENSE_CATEGORIES:
        statement = insert(ExpenseCategory).values(owner_id=user.id, slug=slug, name=name)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[ExpenseCategory.owner_id, ExpenseCategory.slug],
                set_={"name": statement.excluded.name},
            )
        )
    for slug, name in NICHES:
        statement = insert(Niche).values(owner_id=user.id, slug=slug, name=name)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[Niche.owner_id, Niche.slug], set_={"name": statement.excluded.name}
            )
        )
    session.flush()
    return {
        niche.slug: niche
        for niche in session.scalars(select(Niche).where(Niche.owner_id == user.id)).all()
    }


def _upsert_bots(session: Session, user: User, niches: dict[str, Niche]) -> None:
    for slug, channel in CANAIS.items():
        config = json.loads((ROOT / str(channel["arquivo"])).read_text(encoding="utf-8"))
        niche_slug = "automotivo" if config.get("nicho") == "auto" else str(config["nicho"])
        values = {
            "owner_id": user.id,
            "name": str(channel["nome"]),
            "slug": slug,
            "niche_id": niches[niche_slug].id,
            "status": "paused",
            "settings": _settings_from_config(config),
            "message_template": config.get("mensagem_template"),
        }
        statement = insert(Bot).values(**values)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[Bot.owner_id, Bot.slug],
                set_={
                    key: getattr(statement.excluded, key)
                    for key in values
                    if key not in {"owner_id", "status"}
                },
            )
        )


def run_seed() -> None:
    """Executa o seed; pode ser chamado repetidamente sem duplicar linhas."""
    engine = create_engine(normalize_database_url(settings.database_url))
    with Session(engine) as session, session.begin():
        _upsert_platforms(session)
        email = os.getenv("ADMIN_EMAIL")
        password = os.getenv("ADMIN_PASSWORD")
        if not email or not password:
            logger.warning(
                "ADMIN_EMAIL/ADMIN_PASSWORD ausentes; admin, categorias, nichos e bots não foram criados"
            )
            return
        admin = _admin(session, email, password)
        niches = _upsert_owner_rows(session, admin)
        _upsert_bots(session, admin, niches)
    logger.info("Seed concluído")


if __name__ == "__main__":
    run_seed()
