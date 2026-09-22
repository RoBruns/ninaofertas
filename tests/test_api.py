# ruff: noqa: E402

from __future__ import annotations

import json
import os
from collections.abc import Generator
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

fastapi = pytest.importorskip("fastapi", reason="dependencias da API nao instaladas")
pytest.importorskip("jwt", reason="dependencias da API nao instaladas")

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("JWT_SECRET", "segredo-exclusivo-da-suite-de-testes")

from api.audit import record_audit
from api.deps import get_current_user, get_db
from api.main import app
from api.security import create_access_token, hash_password
from core.db import normalize_database_url
from core.models import AuditLog, User


def _recriar_schema_com_migrations(url: str) -> None:
    """Zera o schema public e aplica `alembic upgrade head`."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine as _ce

    # normaliza para o driver psycopg 3 — sem isso o SQLAlchemy tenta psycopg2
    engine = _ce(normalize_database_url(url), future=True)
    with engine.begin() as conexao:
        conexao.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conexao.execute(text("CREATE SCHEMA public"))
    engine.dispose()

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)

    # migrations/env.py lê `core.settings.settings.database_url`, resolvido no
    # import. Só exportar DATABASE_URL aqui chegaria tarde demais, então o valor
    # é trocado no objeto de settings durante o upgrade e restaurado depois.
    from core.settings import settings as _settings

    anterior_env = os.environ.get("DATABASE_URL")
    anterior_cfg = _settings.database_url
    os.environ["DATABASE_URL"] = url
    _settings.database_url = url
    try:
        command.upgrade(cfg, "head")
    finally:
        _settings.database_url = anterior_cfg
        if anterior_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = anterior_env


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    """Schema de teste montado pelas migrations reais, em Postgres.

    Exige `TEST_DATABASE_URL` apontando para um banco descartável; sem isso os
    testes são pulados com instrução de como rodar.

    SQLite não serve aqui: os models usam tipos e funções específicos do
    Postgres (CITEXT no email, INET no ip da auditoria, `now()` e
    `gen_random_uuid()` como server_default, JSONB). Emular isso deixaria o
    teste passando contra algo que não é o que roda em produção — foi
    exatamente por rodar em Postgres de verdade que apareceu o bug do INET na
    auditoria, que o SQLite escondia.
    """
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "TEST_DATABASE_URL ausente. Rode: railway connect Postgres "
            "--tunnel-only --port 55432 e aponte para um banco descartável "
            "(ver docs/DEPLOYMENT.md)."
        )

    # Monta o schema pelas migrations reais, e não com create() tabela a tabela:
    # há FKs entre elas (automation_runs -> bots) e as extensões vêm da 0001.
    _recriar_schema_com_migrations(url)
    engine = create_engine(normalize_database_url(url), future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    yield factory
    engine.dispose()


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    def override_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def add_user(
    session_factory: sessionmaker[Session],
    *,
    email: str,
    password: str = "senha-segura",
    role: str = "viewer",
) -> User:
    with session_factory.begin() as session:
        user = User(
            id=uuid4(),
            email=email,
            password_hash=hash_password(password),
            name="Usuario",
            role=role,
            is_active=True,
        )
        session.add(user)
    return user


def login(client: TestClient, email: str, password: str = "senha-segura") -> dict[str, object]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_error(response: object, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert set(body["error"]) <= {"code", "message", "fields"}


def contains_key(value: object, wanted: str) -> bool:
    if isinstance(value, dict):
        return wanted in value or any(contains_key(item, wanted) for item in value.values())
    if isinstance(value, list):
        return any(contains_key(item, wanted) for item in value)
    return False


def test_login_correto_e_senha_errada_nao_enumera_usuario(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    add_user(session_factory, email="viewer@example.com")
    success = client.post(
        "/api/auth/login",
        json={"email": "viewer@example.com", "password": "senha-segura"},
    )
    assert success.status_code == 200
    assert success.json()["access_token"]
    assert "refresh_token" in success.cookies

    wrong_password = client.post(
        "/api/auth/login",
        json={"email": "viewer@example.com", "password": "incorreta"},
    )
    unknown_email = client.post(
        "/api/auth/login",
        json={"email": "ausente@example.com", "password": "incorreta"},
    )
    assert_error(wrong_password, 401, "UNAUTHORIZED")
    assert wrong_password.json() == unknown_email.json()


def test_protecao_e_rbac(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    add_user(session_factory, email="viewer@example.com")
    assert_error(client.get("/api/auth/me"), 401, "UNAUTHORIZED")
    token = str(login(client, "viewer@example.com")["access_token"])
    assert_error(client.get("/api/users", headers=auth_header(token)), 403, "FORBIDDEN")


def test_refresh_renova_e_token_expirado_falha(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    user = add_user(session_factory, email="viewer@example.com")
    original = str(login(client, "viewer@example.com")["access_token"])
    refreshed = client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != original

    expired = create_access_token(str(user.id), expires_delta=timedelta(seconds=-1))
    assert_error(
        client.get("/api/auth/me", headers=auth_header(expired)),
        401,
        "UNAUTHORIZED",
    )


def test_password_hash_nunca_aparece_em_respostas(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    token = str(login(client, admin.email)["access_token"])
    responses = [
        client.get("/api/auth/me", headers=auth_header(token)),
        client.get("/api/users", headers=auth_header(token)),
        client.post(
            "/api/users",
            headers=auth_header(token),
            json={"email": "new@example.com", "password": "outra-senha", "role": "viewer"},
        ),
    ]
    with session_factory() as session:
        hashes = list(session.scalars(select(User.password_hash)))
    for response in responses:
        assert response.status_code < 400
        payload = response.json()
        assert not contains_key(payload, "password_hash")
        serialized = json.dumps(payload)
        assert all(password_hash not in serialized for password_hash in hashes)


def test_redacao_remove_segredo_da_linha_gravada(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        record_audit(
            session,
            None,
            "test",
            "1",
            "update",
            {"cookie": "abc123", "nome": "x", "nested": [{"ApiKey": "segredo"}]},
            None,
            "127.0.0.1",
        )
    with session_factory() as session:
        entry = session.scalar(select(AuditLog))
        assert entry is not None
        raw = json.dumps({"before": entry.before, "after": entry.after})
        assert "abc123" not in raw
        assert "segredo" not in raw
        assert entry.before == {
            "cookie": "***",
            "nome": "x",
            "nested": [{"ApiKey": "***"}],
        }


def test_envelopes_de_erro(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    viewer = add_user(session_factory, email="viewer@example.com")
    admin_token = str(login(client, admin.email)["access_token"])
    viewer_token = str(login(client, viewer.email)["access_token"])
    assert_error(client.get("/api/auth/me"), 401, "UNAUTHORIZED")
    assert_error(client.get("/api/users", headers=auth_header(viewer_token)), 403, "FORBIDDEN")
    assert_error(
        client.patch(
            f"/api/users/{uuid4()}",
            headers=auth_header(admin_token),
            json={"name": "x"},
        ),
        404,
        "NOT_FOUND",
    )
    assert_error(
        client.delete(f"/api/users/{admin.id}", headers=auth_header(admin_token)),
        409,
        "CONFLICT",
    )
    assert_error(
        client.post("/api/users", headers=auth_header(admin_token), json={"email": "invalido"}),
        422,
        "VALIDATION_ERROR",
    )


def test_rate_limit_login_no_sexto_request(client: TestClient) -> None:
    for _ in range(5):
        response = client.post(
            "/api/auth/login",
            json={"email": "ausente@example.com", "password": "qualquer"},
        )
        assert response.status_code == 401
    assert_error(
        client.post(
            "/api/auth/login",
            json={"email": "ausente@example.com", "password": "qualquer"},
        ),
        429,
        "RATE_LIMITED",
    )


def test_500_nao_vaza_stacktrace(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    user = add_user(session_factory, email="viewer@example.com")
    token = str(login(client, user.email)["access_token"])

    async def explode(_user: User = Depends(get_current_user)) -> None:
        raise RuntimeError("segredo-do-banco SELECT password_hash traceback")

    path = f"/api/test-internal-{uuid4()}"
    app.add_api_route(path, explode, methods=["GET"])
    response = client.get(path, headers=auth_header(token))
    assert_error(response, 500, "INTERNAL")
    serialized = response.text.lower()
    assert "segredo-do-banco" not in serialized
    assert "password_hash" not in serialized
    assert "traceback" not in serialized


def test_admin_nao_pode_se_auto_deletar_nem_rebaixar(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    token = str(login(client, admin.email)["access_token"])
    headers = auth_header(token)
    assert_error(client.delete(f"/api/users/{admin.id}", headers=headers), 409, "CONFLICT")
    assert_error(
        client.patch(f"/api/users/{admin.id}", headers=headers, json={"role": "viewer"}),
        409,
        "CONFLICT",
    )
