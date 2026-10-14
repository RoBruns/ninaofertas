from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

pytest.importorskip("alembic", reason="Alembic não instalado")
pytest.importorskip("argon2", reason="argon2-cffi não instalado")

from alembic import command
from alembic.config import Config

from core.seed import run_seed
from core.settings import settings
from tests._db_guard import recusar_banco_de_producao

ORIGINAL_OFERTAS = [
    "id",
    "nome",
    "preco",
    "preco_anterior",
    "desconto",
    "loja",
    "categoria",
    "url",
    "imagem",
    "sku",
    "capturado_em",
]
ORIGINAL_ENVIOS = [
    "id",
    "oferta_id",
    "enviado_em",
    "grupo",
    "mensagem",
    "preco_enviado",
    "status",
]


@pytest.fixture
def postgres_schema() -> Iterator[tuple[str, object]]:
    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("TEST_DATABASE_URL ausente; migrations Postgres não executadas")
    base_url = make_url(raw_url.replace("postgres://", "postgresql+psycopg://", 1))
    if base_url.drivername == "postgresql":
        base_url = base_url.set(drivername="postgresql+psycopg")
    recusar_banco_de_producao(base_url.database)
    schema = f"phase2_{uuid.uuid4().hex}"
    admin_engine = create_engine(base_url)
    with admin_engine.begin() as connection:
        # O search_path inclui `public` (onde moram citext e pgcrypto). Se outro
        # teste deixou tabelas legadas lá, `to_regclass('envios')` as enxerga e a
        # migration cria FKs cruzando schemas — o downgrade então falha. Zerar o
        # `public` torna este teste independente da ordem da suíte.
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS citext SCHEMA public"))
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto SCHEMA public"))
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_url = base_url.update_query_dict({"options": f"-csearch_path={schema},public"})
    engine = create_engine(scoped_url)
    previous_url = settings.database_url
    settings.database_url = scoped_url.render_as_string(hide_password=False)
    try:
        yield schema, engine
    finally:
        engine.dispose()
        settings.database_url = previous_url
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def _config() -> Config:
    return Config("alembic.ini")


def _create_legacy(engine: object) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ofertas (
                  id SERIAL PRIMARY KEY, nome VARCHAR NOT NULL, preco DOUBLE PRECISION NOT NULL,
                  preco_anterior DOUBLE PRECISION, desconto DOUBLE PRECISION, loja VARCHAR,
                  categoria VARCHAR, url VARCHAR UNIQUE, imagem VARCHAR, sku VARCHAR,
                  capturado_em TIMESTAMP WITHOUT TIME ZONE
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE envios (
                  id SERIAL PRIMARY KEY, oferta_id INT REFERENCES ofertas(id),
                  enviado_em TIMESTAMP WITHOUT TIME ZONE, grupo VARCHAR, mensagem TEXT,
                  preco_enviado DOUBLE PRECISION, status VARCHAR
                )
                """
            )
        )
        connection.execute(
            text("INSERT INTO ofertas (nome, preco, url) VALUES ('existente', 10, 'u')")
        )
        connection.execute(text("INSERT INTO envios (oferta_id, status) VALUES (1, 'sucesso')"))


def test_upgrade_head_em_schema_vazio_e_downgrade_base(postgres_schema) -> None:
    _, engine = postgres_schema
    command.upgrade(_config(), "head")
    assert "users" in inspect(engine).get_table_names()
    assert "ofertas" not in inspect(engine).get_table_names()
    command.downgrade(_config(), "base")
    assert "users" not in inspect(engine).get_table_names()


def test_0009_billing_upgrade_downgrade_upgrade(postgres_schema) -> None:
    from sqlalchemy.exc import DBAPIError

    _, engine = postgres_schema
    config = _config()
    command.upgrade(config, "0008_phone_instance_token")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO tenants (name, is_internal) VALUES ('Interna', true), ('Externa', false)"))
    for _ in range(2):
        command.upgrade(config, "0009_billing")
        with engine.begin() as connection:
            assert connection.execute(text("SELECT code, name, price, currency, interval, limits, is_active FROM plans")).one() == ("beta", "Beta", 0, "BRL", "month", {}, True)
            assert connection.scalar(text("SELECT count(*) FROM subscriptions")) == 0
            connection.execute(text("INSERT INTO subscriptions (tenant_id, plan_id, status, price, interval, started_at, current_period_start) SELECT t.id, p.id, 'trialing', 0, 'month', now(), now() FROM tenants t CROSS JOIN plans p WHERE NOT t.is_internal"))
            connection.execute(text("INSERT INTO subscription_events (tenant_id, subscription_id, type, status_after, mrr_before, mrr_after, occurred_at) SELECT tenant_id, id, 'created', status, 0, 0, now() FROM subscriptions"))
        assert any(index["column_names"] == ["tenant_id", "occurred_at"] for index in inspect(engine).get_indexes("subscription_events"))
        for statement in ("UPDATE subscription_events SET note = 'alterado'", "DELETE FROM subscription_events"):
            with pytest.raises(DBAPIError), engine.begin() as connection:
                connection.execute(text(statement))
        command.downgrade(config, "0008_phone_instance_token")
        assert not {"plans", "subscriptions", "subscription_events"} & set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM tenants")) == 2
    command.upgrade(config, "head")


def test_0005_aplica_e_reverte_somente_em_users(postgres_schema) -> None:
    _, engine = postgres_schema
    config = _config()
    command.upgrade(config, "0004")
    inspector = inspect(engine)
    before = {
        table: [column["name"] for column in inspector.get_columns(table)]
        for table in inspector.get_table_names()
    }

    command.upgrade(config, "0005")
    inspector = inspect(engine)
    after = {
        table: [column["name"] for column in inspector.get_columns(table)]
        for table in inspector.get_table_names()
    }
    assert after["users"] == before["users"] + ["session_version"]
    assert {table: columns for table, columns in after.items() if table != "users"} == {
        table: columns for table, columns in before.items() if table != "users"
    }

    command.downgrade(config, "0004")
    inspector = inspect(engine)
    reverted = {
        table: [column["name"] for column in inspector.get_columns(table)]
        for table in inspector.get_table_names()
    }
    assert reverted == before


def test_revisions_legado_seed_e_preservacao(
    postgres_schema, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, engine = postgres_schema
    _create_legacy(engine)
    config = _config()

    command.upgrade(config, "0001")
    command.downgrade(config, "base")
    command.upgrade(config, "0002")
    command.downgrade(config, "0001")
    command.upgrade(config, "0003")

    db_inspector = inspect(engine)
    oferta_columns = [column["name"] for column in db_inspector.get_columns("ofertas")]
    envio_columns = [column["name"] for column in db_inspector.get_columns("envios")]
    assert oferta_columns == ORIGINAL_OFERTAS + ["platform_account_id"]
    assert envio_columns == ORIGINAL_ENVIOS + ["bot_id", "group_id", "sub_id"]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM ofertas")) == 1
        assert connection.scalar(text("SELECT count(*) FROM envios")) == 1

    # O seed usa os models atuais, então roda contra o schema completo — como no
    # deploy (migrations até head, depois seed). Fixar uma revision aqui quebra
    # a cada migration nova que mexa numa tabela usada pelo seed.
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM ofertas")) == 1
        assert connection.scalar(text("SELECT count(*) FROM envios")) == 1

    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-de-teste")
    run_seed()
    tables = ("platforms", "expense_categories", "niches", "users", "bots")
    with engine.connect() as connection:
        first = {
            table: connection.scalar(text(f"SELECT count(*) FROM {table}")) for table in tables
        }
        assert connection.execute(text("SELECT status FROM bots ORDER BY slug")).scalars().all() == [
            "paused",
            "paused",
        ]
        connection.execute(text("UPDATE bots SET status = 'active' WHERE slug = 'achadinhos'"))
        connection.commit()
    run_seed()
    with engine.connect() as connection:
        second = {
            table: connection.scalar(text(f"SELECT count(*) FROM {table}")) for table in tables
        }
        statuses = dict(connection.execute(text("SELECT slug, status FROM bots")).tuples().all())
        assert statuses == {"achadinhos": "active", "auto": "paused"}
    assert (
        first
        == second
        == {"platforms": 3, "expense_categories": 5, "niches": 2, "users": 1, "bots": 2}
    )

    command.downgrade(config, "0002")
    assert [column["name"] for column in inspect(engine).get_columns("ofertas")] == ORIGINAL_OFERTAS
    assert [column["name"] for column in inspect(engine).get_columns("envios")] == ORIGINAL_ENVIOS
    command.downgrade(config, "base")


def test_0006_test_bots_upgrade_downgrade(postgres_schema) -> None:
    _, engine = postgres_schema
    config = _config()
    command.upgrade(config, "0005")
    before = {column["name"] for column in inspect(engine).get_columns("bots")}
    command.upgrade(config, "0006")
    assert {column["name"] for column in inspect(engine).get_columns("bots")} == before | {
        "is_test", "archived_at", "test_source_bot_id"
    }
    assert "bot_config_backups" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        connection.execute(text("INSERT INTO users (email, password_hash, name) VALUES ('migration@test.com', 'x', 'Teste')"))
        connection.execute(text("INSERT INTO bots (owner_id, name, slug) SELECT id, 'Bot', 'bot' FROM users"))
        assert connection.execute(text("SELECT is_test, archived_at FROM bots")).one() == (False, None)
        connection.commit()
    command.downgrade(config, "0005")
    assert {column["name"] for column in inspect(engine).get_columns("bots")} == before
    assert "bot_config_backups" not in inspect(engine).get_table_names()


def test_0007_tenants_preserva_donos_e_reverte(postgres_schema) -> None:
    _, engine = postgres_schema
    config = _config()
    command.upgrade(config, "0006")
    user_id, bot_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, email, password_hash, role) VALUES (:id, 'tenant@test.com', 'x', 'admin')"), {"id": user_id})
        connection.execute(text("INSERT INTO bots (id, owner_id, name, slug, settings) VALUES (:id, :owner, 'Bot', 'bot', '{\"content\": {\"aceitar_cupons\": false}, \"filters\": {\"preco_minimo\": 42}}')"), {"id": bot_id, "owner": user_id})
        connection.execute(text("INSERT INTO events (bot_id, level, type, message) VALUES (:bot, 'info', 'teste', 'teste')"), {"bot": bot_id})
        connection.execute(text("INSERT INTO audit_logs (user_id, entity_type, entity_id, action) VALUES (:user, 'bot', :bot, 'create')"), {"user": user_id, "bot": str(bot_id)})
    previous_fks = {table: fk["name"] for table in inspect(engine).get_table_names() for fk in inspect(engine).get_foreign_keys(table) if fk["constrained_columns"] == ["owner_id"]}
    for _ in range(2):
        command.upgrade(config, "0007")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT id, name, is_internal, status FROM tenants")).one() == (user_id, "tenant@test.com", True, "active")
            assert connection.execute(text("SELECT tenant_id, is_platform_admin FROM users")).one() == (user_id, True)
            row = connection.execute(text("SELECT owner_id, settings FROM bots")).one()
            assert row[0] == user_id
            assert row[1] == {"content": {"aceitar_cupons": False, "recado_instagram": True}, "filters": {"preco_minimo": 42}}
            assert connection.scalar(text("SELECT tenant_id FROM events")) == user_id
            assert connection.scalar(text("SELECT tenant_id FROM audit_logs")) == user_id
        for table, name in previous_fks.items():
            fk = next(fk for fk in inspect(engine).get_foreign_keys(table) if fk["constrained_columns"] == ["owner_id"])
            assert fk["name"] == name and fk["referred_table"] == "tenants"
        command.downgrade(config, "0006")
        assert "tenants" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT owner_id FROM bots")) == user_id
            assert "recado_instagram" not in connection.scalar(text("SELECT settings FROM bots"))["content"]
    command.upgrade(config, "head")


def test_0007_settings_planos_revertem_sem_content_vazio(postgres_schema) -> None:
    import json

    from core.bot_settings import BotSettings

    _, engine = postgres_schema
    config = _config()
    command.upgrade(config, "0006")
    user_id = uuid.uuid4()
    original = {"preco_minimo": 77, "intervalo_minutos_entre_ofertas": 11}
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, email, password_hash) VALUES (:id, 'plano@test.com', 'x')"), {"id": user_id})
        connection.execute(text("INSERT INTO bots (owner_id, name, slug, settings) VALUES (:owner, 'Plano', 'plano', cast(:settings AS jsonb))"), {"owner": user_id, "settings": json.dumps(original)})
    command.upgrade(config, "0007")
    with engine.connect() as connection:
        settings = BotSettings.model_validate(connection.scalar(text("SELECT settings FROM bots")))
        assert settings.legacy_input and settings.content.recado_instagram
        assert settings.model_dump() == {**original, "recado_instagram": True}
    command.downgrade(config, "0006")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT settings FROM bots")) == original
    command.upgrade(config, "0007")


@pytest.mark.parametrize("admin_email", ["DONO@test.com", "sem-match@test.com", None])
def test_0007_promove_apenas_email_configurado_ou_admin_ativo_mais_antigo(postgres_schema, monkeypatch, admin_email):
    _, engine = postgres_schema
    config = _config()
    command.upgrade(config, "0006")
    if admin_email is None:
        monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    else:
        monkeypatch.setenv("ADMIN_EMAIL", admin_email)
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO users (email, password_hash, role, is_active, created_at) VALUES
            ('inativo@test.com', 'x', 'admin', false, '2020-01-01'),
            ('viewer@test.com', 'x', 'viewer', true, '2020-01-01'),
            ('antigo@test.com', 'x', 'admin', true, '2021-01-01'),
            ('dono@test.com', 'x', 'admin', true, '2022-01-01'),
            ('novo@test.com', 'x', 'admin', true, '2023-01-01')"""))
    for _ in range(2):
        command.upgrade(config, "0007")
        with engine.connect() as connection:
            promoted = connection.execute(text("SELECT email FROM users WHERE is_platform_admin")).scalars().all()
            assert promoted == (["dono@test.com"] if admin_email == "DONO@test.com" else ["antigo@test.com"])
        command.downgrade(config, "0006")


def test_0007_backfill_entidades_auditoria_settings_malformados_e_constraints(postgres_schema, monkeypatch):
    import json

    _, engine = postgres_schema
    config = _config()
    command.upgrade(config, "0006")
    owner, phone, group, account = (uuid.uuid4() for _ in range(4))
    unknown = uuid.uuid4()
    malformed = [None, [], "texto", 42, False]
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, email, password_hash, role) VALUES (:id, 'dono@test.com', 'x', 'admin')"), {"id": owner})
        connection.execute(text("INSERT INTO platforms (slug, name) VALUES ('ml', 'ML')"))
        platform = connection.scalar(text("SELECT id FROM platforms"))
        connection.execute(text("INSERT INTO phones (id, owner_id, label, number) VALUES (:id, :owner, 'Telefone', '551100000000')"), {"id": phone, "owner": owner})
        connection.execute(text("INSERT INTO groups (id, owner_id, phone_id, whatsapp_id) VALUES (:id, :owner, :phone, 'grupo@g.us')"), {"id": group, "owner": owner, "phone": phone})
        connection.execute(text("INSERT INTO platform_accounts (id, owner_id, platform_id, label) VALUES (:id, :owner, :platform, 'Conta')"), {"id": account, "owner": owner, "platform": platform})
        for kind, entity_id in (("phone", phone), ("group", group), ("platform_account", account), ("account", account), ("group", unknown), ("phone", "inválido")):
            connection.execute(text("INSERT INTO events (entity_type, entity_id, level, type, message) VALUES (:kind, :id, 'info', 'teste', 'teste')"), {"kind": kind, "id": str(entity_id)})
        for value in (str(owner), str(unknown), "inválido"):
            connection.execute(text("INSERT INTO audit_logs (entity_type, entity_id, action, after) VALUES ('sale_import', 'teste', 'sync_success', cast(:after AS jsonb))"), {"after": json.dumps({"owner_id": value})})
        for index, content in enumerate(malformed):
            connection.execute(text("INSERT INTO bots (owner_id, name, slug, settings) VALUES (:owner, 'Bot', :slug, cast(:settings AS jsonb))"), {"owner": owner, "slug": f"bot-{index}", "settings": json.dumps({"content": content, "filters": {"preco_minimo": 77}})})
    command.upgrade(config, "0007")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT tenant_id FROM events ORDER BY id")).scalars().all() == [owner] * 4 + [None, None]
        assert connection.execute(text("SELECT tenant_id FROM audit_logs ORDER BY id")).scalars().all() == [owner, None, None]
        for row in connection.execute(text("SELECT settings FROM bots")).scalars():
            assert row == {"content": {"recado_instagram": True}, "filters": {"preco_minimo": 77}}
    for table, columns in (("expenses", ["owner_id", "source", "external_id"]), ("sales", ["owner_id", "platform_id", "external_id"])):
        unique = inspect(engine).get_unique_constraints(table)
        assert any(c["column_names"] == columns for c in unique)
    command.downgrade(config, "0006")
    for table, columns in (("expenses", ["source", "external_id"]), ("sales", ["platform_id", "external_id"])):
        assert any(c["column_names"] == columns for c in inspect(engine).get_unique_constraints(table))
    command.upgrade(config, "0007")


def test_0008_phone_token_upgrade_downgrade(postgres_schema) -> None:
    _, engine = postgres_schema
    config = _config()
    command.upgrade(config, "0007")
    phone_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO tenants (id, name) VALUES (:id, 'Teste')"), {"id": tenant_id})
        connection.execute(text("INSERT INTO phones (id, owner_id, label, number) VALUES (:id, :owner, 'Teste', '5511999999999')"), {"id": phone_id, "owner": tenant_id})
    for _ in range(2):
        command.upgrade(config, "0008_phone_instance_token")
        columns = {column["name"]: column for column in inspect(engine).get_columns("phones")}
        assert columns["instance_token_ciphertext"]["nullable"]
        assert columns["instance_token_fingerprint"]["nullable"]
        assert columns["instance_token_updated_at"]["type"].timezone
        assert columns["number"]["nullable"]
        with engine.connect() as connection:
            assert connection.execute(text("SELECT number, instance_token_ciphertext FROM phones WHERE id=:id"), {"id": phone_id}).one() == ("5511999999999", None)
        command.downgrade(config, "0007")
        columns = {column["name"]: column for column in inspect(engine).get_columns("phones")}
        assert "instance_token_ciphertext" not in columns and not columns["number"]["nullable"]
    command.upgrade(config, "head")

def test_0008_downgrade_preserva_telefone_sem_numero(postgres_schema) -> None:
    _, engine = postgres_schema
    config = _config()
    command.upgrade(config, "head")
    phone_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO tenants (id, name) VALUES (:id, 'Teste')"), {"id": tenant_id})
        connection.execute(text("INSERT INTO phones (id, owner_id, label) VALUES (:id, :owner, 'Aguardando QR')"), {"id": phone_id, "owner": tenant_id})
    command.downgrade(config, "0007")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT number FROM phones WHERE id=:id"), {"id": phone_id}) == f"pending-{phone_id}"
