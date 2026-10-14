"""Contrato e utilitários do backup lógico de public."""

from __future__ import annotations

from typing import TypedDict

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict


class ArchiveError(Exception):
    """Erro operacional cuja mensagem não contém credenciais nem dados de linhas."""


class Column(TypedDict):
    name: str
    type: str


class Table(TypedDict):
    columns: list[Column]
    row_count: int


class Manifest(TypedDict):
    format_version: int
    created_at: str
    server_version: str
    alembic_revision: str
    tables: dict[str, Table]


def database_target(url: str | None) -> tuple[str, str]:
    if not url or not url.startswith(("postgres://", "postgresql://")):
        raise ArchiveError(
            "Informe uma URL postgres:// ou postgresql:// por --url ou DATABASE_URL."
        )
    try:
        params = conninfo_to_dict(url)
    except psycopg.Error:
        raise ArchiveError("URL do Postgres inválida.") from None
    database = params.get("dbname")
    if not database:
        raise ArchiveError("A URL precisa informar o nome do banco.")
    return params.get("host", "local"), database


def public_tables(connection: psycopg.Connection) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
        )
    ]


def table_columns(connection: psycopg.Connection, table: str) -> list[Column]:
    return [
        {"name": name, "type": kind}
        for name, kind in connection.execute(
            "SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod) "
            "FROM pg_catalog.pg_attribute a "
            "WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped "
            "ORDER BY a.attnum",
            (sql.Identifier("public", table).as_string(connection),),
        )
    ]


def row_count(connection: psycopg.Connection, table: str) -> int:
    return connection.execute(
        sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("public", table))
    ).fetchone()[0]
