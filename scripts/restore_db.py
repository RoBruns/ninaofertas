"""Restaura um backup lógico em um banco vazio, com confirmação pelo nome."""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import cast
from zipfile import ZipFile

import psycopg
from psycopg import sql
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._db_archive import (  # noqa: E402
    ArchiveError,
    Manifest,
    database_target,
    public_tables,
    row_count,
)

logger = logging.getLogger(__name__)
# As migrations inserem somente plans; platforms também pode vir do seed inicial.
# alembic_version é metadado gerenciado exclusivamente pelo Alembic.
SEED_TABLES = frozenset({"platforms", "plans"})


def _require_empty(connection: psycopg.Connection) -> None:
    for table in public_tables(connection):
        if table in SEED_TABLES or table == "alembic_version":
            continue
        if connection.execute(
            sql.SQL("SELECT EXISTS (SELECT 1 FROM {})").format(sql.Identifier("public", table))
        ).fetchone()[0]:
            raise ArchiveError(f"Destino contém dados em public.{table}; restauração recusada.")


def _read_manifest(archive: ZipFile) -> Manifest:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    manifest = json.loads(archive.read("manifest.json"))
    if manifest.get("format_version") != 1 or not isinstance(manifest.get("tables"), dict):
        raise ArchiveError("Formato de manifesto não suportado.")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    revision = manifest.get("alembic_revision")
    # Exige ID concreto: não aceita aliases como head nem expressões de revisão.
    if not isinstance(revision, str) or revision not in {
        r.revision for r in scripts.walk_revisions()
    }:
        raise ArchiveError("Revisão do manifesto não existe neste checkout.")
    if "alembic_version" not in manifest["tables"]:
        raise ArchiveError("Manifesto sem alembic_version.")
    for table, metadata in manifest["tables"].items():
        if not table or "/" in table or "\\" in table:
            raise ArchiveError("Nome de tabela inválido no manifesto.")
        if not isinstance(metadata.get("row_count"), int) or metadata["row_count"] < 0:
            raise ArchiveError("Contagem de linhas inválida no manifesto.")
        columns = metadata.get("columns", [])
        names = [column["name"] for column in columns]
        if not names or len(set(names)) != len(names):
            raise ArchiveError("Colunas inválidas no manifesto.")
        with archive.open(f"tables/{table}.csv") as source:
            with io.TextIOWrapper(source, encoding="utf-8", newline="") as text:
                if next(csv.reader(text), None) != names:
                    raise ArchiveError(f"Cabeçalho CSV diverge do manifesto em {table}.")
    return cast(Manifest, manifest)


def _create_schema(url: str, manifest: Manifest) -> None:
    # migrations/env.py lê o singleton settings, criado ao importar core.settings.
    # Um processo novo garante que DATABASE_URL prevaleça sobre settings já importado.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", manifest["alembic_revision"]],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
    )
    if result.returncode:
        raise ArchiveError("Falha ao criar schema com Alembic; confira banco e permissões.")

    from core.models import Base

    engine = create_engine(
        url.replace("postgres://", "postgresql+psycopg://", 1).replace(
            "postgresql://", "postgresql+psycopg://", 1
        )
    )
    try:
        Base.metadata.create_all(
            engine,
            tables=[
                Base.metadata.tables[name]
                for name in ("ofertas", "envios")
                if name in manifest["tables"]
            ],
        )
    finally:
        engine.dispose()


def _reset_sequences(connection: psycopg.Connection) -> None:
    sequences = connection.execute(
        "SELECT table_name, column_name, "
        "pg_get_serial_sequence(format('%I.%I', table_schema, table_name), column_name) "
        "FROM information_schema.columns WHERE table_schema = 'public'"
    ).fetchall()
    for table, column, sequence in sequences:
        if sequence is None:
            continue
        maximum = connection.execute(
            sql.SQL("SELECT max({}) FROM {}").format(
                sql.Identifier(column), sql.Identifier("public", table)
            )
        ).fetchone()[0]
        connection.execute(
            "SELECT setval(%s::regclass, %s, %s)",
            (sequence, maximum if maximum is not None else 1, maximum is not None),
        )


def restore_database(url: str, backup: Path, confirmar: str) -> Manifest:
    host, database = database_target(url)
    if confirmar != database:
        raise ArchiveError("--confirmar precisa ser igual ao nome do banco de destino.")
    logger.info("Destino: host=%s banco=%s", host, database)
    with ZipFile(backup) as archive:
        manifest = _read_manifest(archive)
        with psycopg.connect(url) as connection:
            _require_empty(connection)
        _create_schema(url, manifest)
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            tables = public_tables(connection)
            # Fecha a janela entre a checagem inicial e a carga: ninguém pode inserir
            # nas tabelas enquanto revalidamos, limpamos seeds e restauramos.
            cursor.execute(
                sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
                    sql.SQL(", ").join(sql.Identifier("public", table) for table in tables)
                )
            )
            _require_empty(connection)
            revisions = cursor.execute("SELECT version_num FROM public.alembic_version").fetchall()
            if revisions != [(manifest["alembic_revision"],)]:
                raise ArchiveError("Revisão do destino diverge do backup.")
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            cursor.execute("SET LOCAL DateStyle = 'ISO, YMD'")
            cursor.execute("SET LOCAL IntervalStyle = 'postgres'")
            cursor.execute("SET LOCAL client_encoding = 'UTF8'")
            previous_role = cursor.execute("SHOW session_replication_role").fetchone()[0]
            cursor.execute("SET LOCAL session_replication_role = replica")
            for table in sorted(SEED_TABLES.intersection(tables)):
                cursor.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier("public", table)))
            for table, metadata in manifest["tables"].items():
                if table == "alembic_version":
                    continue
                # Os nomes já foram conferidos contra o cabeçalho real do CSV.
                columns = sql.SQL(", ").join(sql.Identifier(c["name"]) for c in metadata["columns"])
                statement = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER)").format(
                    sql.Identifier("public", table),
                    columns,
                )
                with archive.open(f"tables/{table}.csv") as source, cursor.copy(statement) as copy:
                    while block := source.read(1024 * 1024):
                        copy.write(block)
            cursor.execute(
                sql.SQL("SET LOCAL session_replication_role = {}").format(
                    sql.Literal(previous_role)
                )
            )
            for table, metadata in manifest["tables"].items():
                if row_count(connection, table) != metadata["row_count"]:
                    raise ArchiveError(f"Contagem restaurada diverge do manifesto em {table}.")
            # setval não é transacional: só o executamos após validar toda a carga.
            _reset_sequences(connection)
    logger.info(
        "Restauração concluída e contagens conferidas: %d tabelas, %d linhas.",
        len(manifest["tables"]),
        sum(t["row_count"] for t in manifest["tables"].values()),
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--confirmar", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        database_target(args.url)
        restore_database(args.url, args.backup, args.confirmar)
    except ArchiveError as exc:
        logger.error("Restauração recusada: %s", exc)
        return 1
    except Exception as exc:
        logger.error(
            "Restauração falhou (%s). Confira backup, conexão e permissões.", type(exc).__name__
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
