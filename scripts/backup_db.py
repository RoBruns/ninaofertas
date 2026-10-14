"""Backup lógico consistente, em streaming, sem depender de pg_dump."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._db_archive import (  # noqa: E402
    ArchiveError,
    Manifest,
    database_target,
    public_tables,
    row_count,
    table_columns,
)

logger = logging.getLogger(__name__)


def backup_database(url: str, out: Path) -> Manifest:
    host, database = database_target(url)
    logger.info("Origem: host=%s banco=%s", host, database)
    # Exclusivo: uma falha ou execução repetida nunca sobrescreve um backup anterior.
    with out.open("xb") as destination:
        try:
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cursor.execute("SET LOCAL TIME ZONE 'UTC'")
                cursor.execute("SET LOCAL DateStyle = 'ISO, YMD'")
                cursor.execute("SET LOCAL IntervalStyle = 'postgres'")
                cursor.execute("SET LOCAL client_encoding = 'UTF8'")
                tables = public_tables(connection)
                if "alembic_version" not in tables:
                    raise ArchiveError(
                        "Banco sem revisão Alembic; não é possível reconstruir o schema."
                    )
                revisions = cursor.execute(
                    "SELECT version_num FROM public.alembic_version"
                ).fetchall()
                if len(revisions) != 1:
                    raise ArchiveError("O backup exige exatamente uma revisão Alembic.")
                manifest: Manifest = {
                    "format_version": 1,
                    "created_at": cursor.execute("SELECT transaction_timestamp()")
                    .fetchone()[0]
                    .isoformat(),
                    "server_version": cursor.execute("SHOW server_version").fetchone()[0],
                    "alembic_revision": revisions[0][0],
                    "tables": {},
                }
                with ZipFile(
                    destination, "w", compression=ZIP_DEFLATED, allowZip64=True
                ) as archive:
                    for table in tables:
                        manifest["tables"][table] = {
                            "columns": table_columns(connection, table),
                            "row_count": row_count(connection, table),
                        }
                        statement = sql.SQL(
                            "COPY (SELECT * FROM {}) TO STDOUT WITH (FORMAT csv, HEADER)"
                        ).format(sql.Identifier("public", table))
                        with archive.open(f"tables/{table}.csv", "w", force_zip64=True) as output:
                            with cursor.copy(statement) as copy:
                                for block in copy:
                                    output.write(block)
                    archive.writestr(
                        "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
                    )
        except BaseException:
            destination.close()
            out.unlink(missing_ok=True)
            raise
    logger.info(
        "Backup concluído: %d tabelas, %d linhas, %d bytes.",
        len(manifest["tables"]),
        sum(table["row_count"] for table in manifest["tables"].values()),
        out.stat().st_size,
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        database_target(args.url)
        backup_database(args.url, args.out)
    except ArchiveError as exc:
        logger.error("Backup recusado: %s", exc)
        return 1
    except Exception as exc:
        # Erros do driver podem conter DSN, valores de linhas ou senha; não os exibir.
        logger.error(
            "Backup falhou (%s). Confira conexão, permissões e arquivo de saída.",
            type(exc).__name__,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
