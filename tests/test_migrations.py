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

    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-de-teste")
    run_seed()
    tables = ("platforms", "expense_categories", "niches", "users", "bots")
    with engine.connect() as connection:
        first = {
            table: connection.scalar(text(f"SELECT count(*) FROM {table}")) for table in tables
        }
    run_seed()
    with engine.connect() as connection:
        second = {
            table: connection.scalar(text(f"SELECT count(*) FROM {table}")) for table in tables
        }
    assert (
        first
        == second
        == {"platforms": 3, "expense_categories": 5, "niches": 2, "users": 1, "bots": 2}
    )

    command.downgrade(config, "0002")
    assert [column["name"] for column in inspect(engine).get_columns("ofertas")] == ORIGINAL_OFERTAS
    assert [column["name"] for column in inspect(engine).get_columns("envios")] == ORIGINAL_ENVIOS
    command.downgrade(config, "base")
