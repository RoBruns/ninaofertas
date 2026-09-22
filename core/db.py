"""Engine, fábrica de sessões e inicialização do banco."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models import Base, Envio, Oferta
from core.settings import settings


def normalize_database_url(url: str) -> str:
    """Normaliza a URL do Postgres para o driver psycopg 3."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _url_do_banco() -> str:
    return normalize_database_url(settings.database_url)


_engine = create_engine(_url_do_banco(), echo=False, future=True)
_SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def init_db() -> None:
    """Cria somente o schema legado necessário ao worker."""
    Base.metadata.create_all(_engine, tables=[Oferta.__table__, Envio.__table__])


@contextmanager
def get_session() -> Session:
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
