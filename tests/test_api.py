# ruff: noqa: E402

from __future__ import annotations

import json
import os
from collections.abc import Generator
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import jwt

fastapi = pytest.importorskip("fastapi", reason="dependencias da API nao instaladas")
pytest.importorskip("jwt", reason="dependencias da API nao instaladas")

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("JWT_SECRET", "segredo-exclusivo-da-suite-de-testes")

from api.audit import record_audit
from api.deps import get_current_user, get_db
from api.main import app
from api.security import REFRESH_COOKIE_NAME, create_access_token, hash_password
from core.db import normalize_database_url
from core.models import AuditLog, User


def _recriar_schema_com_migrations(url: str) -> None:
    """Zera o schema public e aplica `alembic upgrade head`."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine as _ce

    from sqlalchemy.engine import make_url

    from tests._db_guard import recusar_banco_de_producao

    recusar_banco_de_producao(make_url(normalize_database_url(url)).database)
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
    with TestClient(
        app, base_url="https://testserver", raise_server_exceptions=False
    ) as test_client:
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


def test_protecao_e_rbac(client: TestClient, session_factory: sessionmaker[Session]) -> None:
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

    expired = create_access_token(
        str(user.id),
        expires_delta=timedelta(seconds=-1),
        session_version=user.session_version,
    )
    assert_error(
        client.get("/api/auth/me", headers=auth_header(expired)),
        401,
        "UNAUTHORIZED",
    )


def test_logout_invalida_cookie_copiado_access_antigo_e_permite_novo_login(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    user = add_user(session_factory, email="viewer@example.com")
    login_response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "senha-segura"},
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]
    copied_refresh = login_response.cookies[REFRESH_COOKIE_NAME]

    logout_response = client.post(
        "/api/auth/logout",
        headers=auth_header(access_token),
    )
    assert logout_response.status_code == 204
    assert REFRESH_COOKIE_NAME not in client.cookies

    assert_error(
        client.post(
            "/api/auth/refresh",
            headers={"cookie": f"{REFRESH_COOKIE_NAME}={copied_refresh}"},
        ),
        401,
        "UNAUTHORIZED",
    )
    assert_error(
        client.get("/api/auth/me", headers=auth_header(access_token)),
        401,
        "UNAUTHORIZED",
    )

    new_login = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "senha-segura"},
    )
    assert new_login.status_code == 200
    assert (
        client.get(
            "/api/auth/me",
            headers=auth_header(new_login.json()["access_token"]),
        ).status_code
        == 200
    )


def test_logout_em_um_aparelho_invalida_tokens_do_outro(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    user = add_user(session_factory, email="viewer@example.com")
    first = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "senha-segura"},
    )
    second = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "senha-segura"},
    )
    first_access = first.json()["access_token"]
    second_access = second.json()["access_token"]
    second_refresh = second.cookies[REFRESH_COOKIE_NAME]

    assert (
        client.post(
            "/api/auth/logout",
            headers=auth_header(first_access),
        ).status_code
        == 204
    )
    assert_error(
        client.get("/api/auth/me", headers=auth_header(second_access)),
        401,
        "UNAUTHORIZED",
    )
    assert_error(
        client.post(
            "/api/auth/refresh",
            headers={"cookie": f"{REFRESH_COOKIE_NAME}={second_refresh}"},
        ),
        401,
        "UNAUTHORIZED",
    )


def test_token_sem_session_version_e_recusado(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    user = add_user(session_factory, email="viewer@example.com")
    token = create_access_token(str(user.id), session_version=user.session_version)
    claims = jwt.decode(token, options={"verify_signature": False})
    claims.pop("sv")
    legacy_token = jwt.encode(claims, os.environ["JWT_SECRET"], algorithm="HS256")

    assert_error(
        client.get("/api/auth/me", headers=auth_header(legacy_token)),
        401,
        "UNAUTHORIZED",
    )


def test_troca_de_senha_e_desativacao_invalidam_tokens(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    password_user = add_user(session_factory, email="password@example.com")
    inactive_user = add_user(session_factory, email="inactive@example.com")
    admin_token = str(login(client, admin.email)["access_token"])
    password_token = str(login(client, password_user.email)["access_token"])
    password_refresh = client.cookies[REFRESH_COOKIE_NAME]
    inactive_token = str(login(client, inactive_user.email)["access_token"])
    inactive_refresh = client.cookies[REFRESH_COOKIE_NAME]

    changed = client.patch(
        f"/api/users/{password_user.id}",
        headers=auth_header(admin_token),
        json={"password": "senha-nova-segura"},
    )
    assert changed.status_code == 200
    assert_error(
        client.get("/api/auth/me", headers=auth_header(password_token)),
        401,
        "UNAUTHORIZED",
    )
    assert_error(
        client.post(
            "/api/auth/refresh",
            headers={"cookie": f"{REFRESH_COOKIE_NAME}={password_refresh}"},
        ),
        401,
        "UNAUTHORIZED",
    )

    deactivated = client.delete(
        f"/api/users/{inactive_user.id}",
        headers=auth_header(admin_token),
    )
    assert deactivated.status_code == 204
    assert_error(
        client.get("/api/auth/me", headers=auth_header(inactive_token)),
        401,
        "UNAUTHORIZED",
    )
    assert_error(
        client.post(
            "/api/auth/refresh",
            headers={"cookie": f"{REFRESH_COOKIE_NAME}={inactive_refresh}"},
        ),
        401,
        "UNAUTHORIZED",
    )


def test_logout_sem_token_retorna_204_e_limpa_cookie(client: TestClient) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/auth/logout",
        headers={"cookie": f"{REFRESH_COOKIE_NAME}=token-invalido"},
    )

    assert response.status_code == 204
    set_cookie = response.headers["set-cookie"].lower()
    assert f"{REFRESH_COOKIE_NAME}=" in set_cookie
    assert "max-age=0" in set_cookie


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


def test_auditoria_identifica_autor_sistema_e_usuario_inativo(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    author = add_user(session_factory, email="author@example.com")
    inactive = add_user(session_factory, email="inactive-author@example.com")
    with session_factory.begin() as session:
        stored_inactive = session.get(User, inactive.id)
        assert stored_inactive is not None
        stored_inactive.name = "Autora Inativa"
        stored_inactive.is_active = False
        session.add_all(
            [
                AuditLog(
                    user_id=author.id,
                    entity_type="test",
                    entity_id="active-author",
                    action="update",
                    before=None,
                    after={"status": "ok"},
                    ip=None,
                ),
                AuditLog(
                    user_id=None,
                    entity_type="test",
                    entity_id="system",
                    action="sync",
                    before=None,
                    after=None,
                    ip=None,
                ),
                AuditLog(
                    user_id=inactive.id,
                    entity_type="test",
                    entity_id="inactive-author",
                    action="update",
                    before=None,
                    after=None,
                    ip=None,
                ),
            ]
        )

    token = str(login(client, admin.email)["access_token"])
    response = client.get("/api/audit-logs", headers=auth_header(token))
    assert response.status_code == 200, response.text
    items = {item["entity_id"]: item for item in response.json()["items"]}
    assert items["active-author"]["user_email"] == "author@example.com"
    assert items["active-author"]["user_name"] == "Usuario"
    assert items["system"]["user_id"] is None
    assert items["system"]["user_email"] is None
    assert items["system"]["user_name"] is None
    assert items["inactive-author"]["user_email"] == "inactive-author@example.com"
    assert items["inactive-author"]["user_name"] == "Autora Inativa"
    assert "password_hash" not in response.text


def test_listagem_de_auditoria_faz_numero_constante_de_consultas(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    author = add_user(session_factory, email="author@example.com")
    with session_factory.begin() as session:
        session.add_all(
            [
                AuditLog(
                    user_id=author.id,
                    entity_type="test",
                    entity_id=str(index),
                    action="update",
                    before=None,
                    after=None,
                    ip=None,
                )
                for index in range(20)
            ]
        )

    token = str(login(client, admin.email)["access_token"])
    queries = {"count": 0}

    def count_query(*_args: object, **_kwargs: object) -> None:
        queries["count"] += 1

    engine = session_factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", count_query)
    try:
        response = client.get(
            "/api/audit-logs",
            headers=auth_header(token),
            params={"entity_type": "test", "page_size": 100},
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_query)

    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 20
    assert queries["count"] == 3


def test_envelopes_de_erro(client: TestClient, session_factory: sessionmaker[Session]) -> None:
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
