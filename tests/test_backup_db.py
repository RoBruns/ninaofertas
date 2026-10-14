"""Round trip real do arquivo lógico, inclusive tipos nativos e proteções."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
from sqlalchemy import create_engine

from core.crypto import decrypt, encrypt, fingerprint
from core.models import Base, Envio, Oferta
from scripts import backup_db
from scripts._db_archive import ArchiveError, public_tables
from scripts.restore_db import restore_database
from tests._db_guard import recusar_banco_de_producao

ROOT = Path(__file__).resolve().parents[1]
TEXT = 'Ação da Vó Nina, "promoção"\nSegunda linha: café ☕'
TOKEN = "token-apenas-do-teste"


def _migrate(url: str, revision: str = "head") -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
    )
    assert result.returncode == 0, "Falha no Alembic do banco de teste"


def _drop_schema(url: str) -> None:
    with psycopg.connect(url) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")


@pytest.fixture
def archive_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL ausente; backup requer Postgres real")
    recusar_banco_de_producao(conninfo_to_dict(url).get("dbname"))
    monkeypatch.setenv("CREDENTIALS_KEY", base64.b64encode(b"b" * 32).decode())
    _drop_schema(url)
    _migrate(url)
    engine = create_engine(
        url.replace("postgres://", "postgresql+psycopg://", 1).replace(
            "postgresql://", "postgresql+psycopg://", 1
        )
    )
    try:
        Base.metadata.create_all(engine, tables=[Oferta.__table__, Envio.__table__])
        yield url
    finally:
        engine.dispose()
        _drop_schema(url)


def _populate(url: str) -> None:
    with psycopg.connect(url) as c:
        tenant = c.execute(
            "INSERT INTO tenants (name) VALUES (%s) RETURNING id", (TEXT,)
        ).fetchone()[0]
        user = c.execute(
            "INSERT INTO users (tenant_id, email, password_hash, name) "
            "VALUES (%s, 'backup@example.test', 'hash-de-teste', %s) RETURNING id",
            (tenant, TEXT),
        ).fetchone()[0]
        c.execute("INSERT INTO platforms (id, slug, name) VALUES (17, 'shopee', 'Shopee')")
        account = c.execute(
            "INSERT INTO platform_accounts (owner_id, platform_id, label, notes) "
            "VALUES (%s, 17, %s, '') RETURNING id",
            (tenant, TEXT),
        ).fetchone()[0]
        c.execute(
            "INSERT INTO platform_credentials (account_id, kind, ciphertext, fingerprint) "
            "VALUES (%s, 'app_secret', %s, %s)",
            (account, encrypt(TOKEN), fingerprint(TOKEN)),
        )
        phone = c.execute(
            "INSERT INTO phones (owner_id, label, number, evolution_instance, "
            "instance_token_ciphertext, instance_token_fingerprint, instance_token_updated_at) "
            "VALUES (%s, %s, NULL, 'backup-teste', %s, %s, now()) RETURNING id",
            (tenant, TEXT, encrypt(TOKEN), fingerprint(TOKEN)),
        ).fetchone()[0]
        group = c.execute(
            "INSERT INTO groups (owner_id, phone_id, whatsapp_id, name) "
            "VALUES (%s, %s, 'backup@g.us', %s) RETURNING id",
            (tenant, phone, TEXT),
        ).fetchone()[0]
        bot = c.execute(
            "INSERT INTO bots (owner_id, name, slug, phone_id, settings, message_template) "
            "VALUES (%s, %s, 'backup', %s, %s, %s) RETURNING id",
            (tenant, TEXT, phone, Jsonb({"filters": {"nichos": [TEXT]}, "nulo": None}), TEXT),
        ).fetchone()[0]
        c.execute("INSERT INTO bot_groups (bot_id, group_id) VALUES (%s, %s)", (bot, group))
        c.execute(
            "INSERT INTO bot_platform_accounts (bot_id, account_id) VALUES (%s, %s)", (bot, account)
        )
        c.execute(
            "INSERT INTO ofertas (id, nome, preco, platform_account_id, capturado_em) "
            "VALUES (91, %s, 123.45, %s, '2026-10-14 12:34:56.123456')",
            (TEXT, account),
        )
        c.execute(
            "INSERT INTO envios (id, oferta_id, bot_id, group_id, grupo, mensagem, status) "
            "VALUES (87, 91, %s, %s, 'backup@g.us', %s, 'sucesso')",
            (bot, group, TEXT),
        )
        c.execute(
            "INSERT INTO sales (owner_id, account_id, platform_id, external_id, bot_id, "
            "group_id, oferta_id, product_name, gross_amount, commission, commission_rate, "
            "ordered_at, source, raw) VALUES (%s, %s, 17, 'venda-backup', %s, %s, 91, %s, "
            "999999999999.99, 123456789.01, 0.1234, '2026-10-14 09:34:56.123456-03', 'manual', %s)",
            (tenant, account, bot, group, TEXT, Jsonb({"texto": TEXT})),
        )
        # Acentos, aspas, vírgulas, multilinha, nulo e vazio exercitam o codec CSV.
        for event_id, message in ((71, TEXT), (75, "")):
            c.execute(
                "INSERT INTO events (id, tenant_id, bot_id, level, type, message, created_at) "
                "VALUES (%s, %s, %s, 'info', 'backup', %s, '2026-10-14 09:34:56.123456-03')",
                (event_id, tenant, bot, message),
            )
        c.execute(
            "INSERT INTO audit_logs (id, tenant_id, user_id, entity_type, entity_id, action, "
            "\"before\", \"after\", ip) VALUES (93, %s, %s, 'bot', %s, 'create', NULL, %s, '2001:db8::42')",
            (tenant, user, str(bot), Jsonb({"texto": TEXT})),
        )
        subscription = c.execute(
            "INSERT INTO subscriptions (tenant_id, plan_id, status, price, interval, started_at, "
            "current_period_start) SELECT %s, id, 'active', 129.90, 'month', now(), now() "
            "FROM plans WHERE code = 'beta' RETURNING id",
            (tenant,),
        ).fetchone()[0]
        c.execute(
            "INSERT INTO subscription_events (id, tenant_id, subscription_id, type, status_after, "
            "mrr_before, mrr_after, occurred_at, created_by, note) "
            "VALUES (57, %s, %s, 'created', 'active', 0, 129.90, now(), %s, %s)",
            (tenant, subscription, user, TEXT),
        )


def _snapshot(url: str) -> dict[str, list[tuple]]:
    with psycopg.connect(url) as c:
        return {
            table: c.execute(
                sql.SQL("SELECT t.* FROM {} t ORDER BY to_jsonb(t)::text").format(
                    sql.Identifier("public", table)
                )
            ).fetchall()
            for table in public_tables(c)
        }


def _cli(script: str, *args: str, url: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", **({"DATABASE_URL": url} if url else {})}
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@pytest.mark.parametrize("migrated_destination", [False, True])
def test_round_trip_todas_as_linhas_tipos_sequencias_e_gatilho(
    archive_db,
    tmp_path,
    migrated_destination,
) -> None:
    url = archive_db
    _populate(url)
    before = _snapshot(url)
    backup = tmp_path / "backup.zip"
    # Sem --url: DATABASE_URL; o alias postgres:// também precisa funcionar.
    result = _cli(
        "backup_db.py", "--out", str(backup), url=url.replace("postgresql://", "postgres://", 1)
    )
    assert result.returncode == 0, result.stderr
    assert "tabelas" in result.stderr and "linhas" in result.stderr and "bytes" in result.stderr
    assert url not in result.stderr and TOKEN not in result.stderr
    with ZipFile(backup) as z:
        manifest = json.loads(z.read("manifest.json"))
        assert set(manifest["tables"]) == set(before)
        assert datetime.fromisoformat(manifest["created_at"]).utcoffset() == timezone.utc.utcoffset(
            None
        )
        assert manifest["server_version"]
        for table, rows in before.items():
            assert manifest["tables"][table]["row_count"] == len(rows)
        assert {c["name"]: c["type"] for c in manifest["tables"]["sales"]["columns"]}[
            "gross_amount"
        ] == "numeric(14,2)"
    _drop_schema(url)
    if migrated_destination:
        _migrate(url)
        with psycopg.connect(url) as c:
            c.execute("INSERT INTO platforms (id, slug, name) VALUES (17, 'temporaria', 'Seed')")
    database = conninfo_to_dict(url)["dbname"]
    result = _cli("restore_db.py", "--url", url, "--backup", str(backup), "--confirmar", database)
    assert result.returncode == 0, result.stderr
    assert _snapshot(url) == before  # Todas as colunas/linhas, incluindo alembic_version.
    with psycopg.connect(url) as c:
        assert (
            decrypt(c.execute("SELECT instance_token_ciphertext FROM phones").fetchone()[0])
            == TOKEN
        )
        assert c.execute("SELECT gross_amount FROM sales").fetchone()[0] == Decimal(
            "999999999999.99"
        )
        sequences = c.execute(
            "SELECT table_name, column_name, pg_get_serial_sequence(format('%I.%I', table_schema, "
            "table_name), column_name) FROM information_schema.columns WHERE table_schema = 'public'"
        ).fetchall()
        for table, column, sequence in sequences:
            if sequence:
                maximum = c.execute(
                    sql.SQL("SELECT max({}) FROM {}").format(
                        sql.Identifier(column), sql.Identifier(table)
                    )
                ).fetchone()[0]
                assert c.execute("SELECT nextval(%s::regclass)", (sequence,)).fetchone()[0] == (
                    maximum + 1 if maximum is not None else 1
                )
        assert (
            c.execute(
                "INSERT INTO ofertas (nome, preco) VALUES ('nova', 10) RETURNING id"
            ).fetchone()[0]
            > 91
        )
        assert c.execute("SHOW session_replication_role").fetchone()[0] == "origin"
    with pytest.raises(psycopg.errors.RaiseException, match="somente inserção"):
        with psycopg.connect(url) as c:
            c.execute("UPDATE subscription_events SET note = 'proibido'")


def test_recusa_confirmacao_errada_e_destino_com_dados(archive_db, tmp_path) -> None:
    url = archive_db
    _populate(url)
    before = _snapshot(url)
    backup = tmp_path / "backup.zip"
    backup_db.backup_database(url, backup)
    for confirmation, expected in (
        ("errado", "--confirmar"),
        (conninfo_to_dict(url)["dbname"], "contém dados"),
    ):
        result = _cli(
            "restore_db.py", "--url", url, "--backup", str(backup), "--confirmar", confirmation
        )
        assert result.returncode != 0 and expected in result.stderr
        assert url not in result.stderr and TOKEN not in result.stderr
        assert _snapshot(url) == before


def test_snapshot_consistente_com_escrita_concorrente(archive_db, tmp_path, monkeypatch) -> None:
    url = archive_db
    _populate(url)
    original_count = backup_db.row_count
    changed = False

    def concurrent_count(connection: psycopg.Connection, table: str) -> int:
        nonlocal changed
        assert connection.execute("SHOW transaction_isolation").fetchone()[0] == "repeatable read"
        assert connection.execute("SHOW transaction_read_only").fetchone()[0] == "on"
        if not changed:
            with psycopg.connect(url) as writer:
                writer.execute("UPDATE events SET message = 'mudou depois da foto'")
            changed = True
        return original_count(connection, table)

    before = _snapshot(url)
    monkeypatch.setattr(backup_db, "row_count", concurrent_count)
    backup = tmp_path / "snapshot.zip"
    backup_db.backup_database(url, backup)
    assert changed and _snapshot(url) != before
    _drop_schema(url)
    restore_database(url, backup, conninfo_to_dict(url)["dbname"])
    assert _snapshot(url) == before


def test_contagem_divergente_reverte_carga_e_seeds(archive_db, tmp_path) -> None:
    url = archive_db
    _populate(url)
    backup = tmp_path / "backup.zip"
    backup_db.backup_database(url, backup)
    corrupted = tmp_path / "contagem-errada.zip"
    with ZipFile(backup) as source, ZipFile(corrupted, "w", compression=ZIP_DEFLATED) as out:
        for member in source.namelist():
            data = source.read(member)
            if member == "manifest.json":
                manifest = json.loads(data)
                manifest["tables"]["events"]["row_count"] += 1
                data = json.dumps(manifest).encode()
            out.writestr(member, data)
    _drop_schema(url)
    _migrate(url)
    before = _snapshot(url)
    with pytest.raises(ArchiveError, match="Contagem restaurada diverge"):
        restore_database(url, corrupted, conninfo_to_dict(url)["dbname"])
    after = _snapshot(url)
    # create_all pode adicionar ofertas/envios; a carga e a remoção do beta foram revertidas.
    assert {table: after[table] for table in before} == before
    assert after["ofertas"] == after["envios"] == []


def test_recusa_dados_em_tabela_fora_do_manifesto(archive_db, tmp_path) -> None:
    url = archive_db
    backup = tmp_path / "backup.zip"
    backup_db.backup_database(url, backup)
    with psycopg.connect(url) as c:
        c.execute("CREATE TABLE extra (value text)")
        c.execute("INSERT INTO extra VALUES ('preservar')")
    with pytest.raises(ArchiveError, match="public.extra"):
        restore_database(url, backup, conninfo_to_dict(url)["dbname"])


def test_backup_nao_sobrescreve_arquivo_e_nao_expoe_url(archive_db, tmp_path) -> None:
    path = tmp_path / "existente.zip"
    path.write_bytes(b"preservar")
    result = _cli("backup_db.py", "--url", archive_db, "--out", str(path))
    assert result.returncode != 0
    assert path.read_bytes() == b"preservar"
    # A senha do teste também não deve aparecer nos diagnósticos de conexão.
    bad_url = "postgresql://usuario:segredo-inconfundivel@127.0.0.1:1/banco?connect_timeout=1"
    result = _cli("backup_db.py", "--url", bad_url, "--out", str(tmp_path / "falhou.zip"))
    assert result.returncode != 0
    assert "segredo-inconfundivel" not in result.stderr and bad_url not in result.stderr
    assert not (tmp_path / "falhou.zip").exists()


def test_restaura_revisao_anterior_as_migrations_saas(archive_db, tmp_path) -> None:
    url = archive_db
    _drop_schema(url)
    _migrate(url, "0006")
    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
    try:
        Base.metadata.create_all(engine, tables=[Oferta.__table__, Envio.__table__])
    finally:
        engine.dispose()
    with psycopg.connect(url) as c:
        user = c.execute(
            "INSERT INTO users (email, password_hash) VALUES ('antigo@test.local', '!') RETURNING id"
        ).fetchone()[0]
        c.execute("INSERT INTO bots (owner_id, name, slug) VALUES (%s, %s, 'antigo')", (user, TEXT))
        c.execute("INSERT INTO ofertas (nome, preco) VALUES (%s, 10)", (TEXT,))
        c.execute("INSERT INTO envios (oferta_id, mensagem) SELECT id, %s FROM ofertas", (TEXT,))
    before = _snapshot(url)
    backup = tmp_path / "antes-saas.zip"
    manifest = backup_db.backup_database(url, backup)
    assert manifest["alembic_revision"] == "0006"
    _drop_schema(url)
    restore_database(url, backup, conninfo_to_dict(url)["dbname"])
    assert _snapshot(url) == before
    assert "tenants" not in before and "plans" not in before
