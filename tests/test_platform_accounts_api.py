# ruff: noqa: E402, F401, F811

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("CREDENTIALS_KEY", base64.b64encode(b"k" * 32).decode())

from core.models import (
    AuditLog,
    Bot,
    BotPlatformAccount,
    Platform,
    PlatformAccount,
    PlatformCredential,
)
from api.schemas.account import AccountResponse
from api.schemas.credential import CredentialStatus, CredentialTestResponse
from api.routers.accounts import credential_status
from core.platforms.registry import MercadoLivreClient, ShopeeClient
from tests.test_api import (
    add_user,
    assert_error,
    auth_header,
    client,
    login,
    session_factory,
)


def add_platform(
    factory: sessionmaker[Session],
    *,
    slug: str = "mercadolivre",
    name: str = "Mercado Livre",
) -> Platform:
    with factory.begin() as session:
        platform = Platform(
            slug=slug,
            name=name,
            is_active=True,
            capabilities={"offers": True, "affiliate_link": True},
        )
        session.add(platform)
        session.flush()
        platform_id = platform.id
    with factory() as session:
        return session.get(Platform, platform_id)


def create_account(
    test_client: object,
    token: str,
    platform_id: int,
    label: str = "Conta 01",
) -> dict[str, object]:
    response = test_client.post(
        "/api/accounts",
        headers=auth_header(token),
        json={
            "platform_id": platform_id,
            "label": label,
            "config": {"affiliate_tag": "nina01"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def assert_not_present_recursively(value: object, sentinel: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert sentinel not in str(key)
            assert_not_present_recursively(item, sentinel)
    elif isinstance(value, list):
        for item in value:
            assert_not_present_recursively(item, sentinel)
    elif isinstance(value, str):
        assert sentinel not in value


def test_schemas_de_resposta_nao_tem_valor_de_credencial() -> None:
    assert "value" not in CredentialStatus.model_fields
    assert "value" not in CredentialTestResponse.model_fields
    assert "value" not in AccountResponse.model_fields


def test_status_derivado_por_validade() -> None:
    now = datetime.now(timezone.utc)
    expiring = PlatformCredential(
        kind="cookie",
        ciphertext=b"cifrado",
        status="valid",
        expires_at=now + timedelta(hours=2),
    )
    expired = PlatformCredential(
        kind="cookie",
        ciphertext=b"cifrado",
        status="valid",
        expires_at=now - timedelta(seconds=1),
    )
    assert credential_status(expiring).status == "expiring"
    assert credential_status(expiring).needs_renewal is True
    assert credential_status(expired).status == "expired"
    assert credential_status(expired).needs_renewal is True


def test_multiplas_contas_da_mesma_plataforma_e_label_duplicado(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    platform = add_platform(session_factory)
    headers = auth_header(str(login(client, admin.email)["access_token"]))

    first = client.post(
        "/api/accounts",
        headers=headers,
        json={"platform_id": platform.id, "label": "Conta A"},
    )
    second = client.post(
        "/api/accounts",
        headers=headers,
        json={"platform_id": platform.id, "label": "Conta B"},
    )
    duplicate = client.post(
        "/api/accounts",
        headers=headers,
        json={"platform_id": platform.id, "label": "Conta A"},
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert_error(duplicate, 409, "CONFLICT")
    listing = client.get(f"/api/accounts?platform_id={platform.id}", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 2


def test_credencial_e_cifrada_sobrescrita_e_removida(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    platform = add_platform(session_factory)
    token = str(login(client, admin.email)["access_token"])
    headers = auth_header(token)
    account_id = create_account(client, token, platform.id)["id"]

    first_value = "COOKIE-PRIMEIRO-valor-improvavel"
    response = client.put(
        f"/api/accounts/{account_id}/credentials/cookie",
        headers=headers,
        json={"value": first_value},
    )
    assert response.status_code == 204
    with session_factory() as session:
        first = session.scalar(select(PlatformCredential))
        assert first is not None
        assert first.ciphertext != first_value.encode()
        assert first_value.encode() not in first.ciphertext
        old_fingerprint = first.fingerprint
        old_rotated_at = first.last_rotated_at

    second_value = "COOKIE-SEGUNDO-outro-valor"
    response = client.put(
        f"/api/accounts/{account_id}/credentials/cookie",
        headers=headers,
        json={"value": second_value},
    )
    assert response.status_code == 204
    with session_factory() as session:
        second = session.scalar(select(PlatformCredential))
        assert second is not None
        assert second.fingerprint != old_fingerprint
        assert second.last_rotated_at >= old_rotated_at
        assert second_value.encode() not in second.ciphertext

    metadata = client.get(f"/api/accounts/{account_id}/credentials", headers=headers)
    assert metadata.status_code == 200
    assert set(metadata.json()[0]) == {
        "kind",
        "status",
        "expires_at",
        "last_rotated_at",
        "last_used_at",
        "last_success_at",
        "last_error",
        "last_error_at",
        "needs_renewal",
    }
    deleted = client.delete(
        f"/api/accounts/{account_id}/credentials/cookie",
        headers=headers,
    )
    assert deleted.status_code == 204
    with session_factory() as session:
        assert session.scalar(select(PlatformCredential)) is None


def test_delete_conta_vinculada_nomeia_bots(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    platform = add_platform(session_factory)
    token = str(login(client, admin.email)["access_token"])
    headers = auth_header(token)
    account_id = create_account(client, token, platform.id)["id"]
    bot_id = uuid4()
    with session_factory.begin() as session:
        session.add(
            Bot(
                id=bot_id,
                owner_id=admin.id,
                name="Bot Casa Principal",
                slug="casa-principal",
                status="paused",
                settings={},
            )
        )
        session.add(BotPlatformAccount(bot_id=bot_id, account_id=account_id, is_active=True))

    response = client.delete(f"/api/accounts/{account_id}", headers=headers)
    assert_error(response, 409, "CONFLICT")
    assert "Bot Casa Principal" in response.text


def test_rbac_e_credencial_inexistente(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    viewer = add_user(session_factory, email="viewer@example.com", role="viewer")
    platform = add_platform(session_factory)
    account_id = uuid4()
    with session_factory.begin() as session:
        session.add(
            PlatformAccount(
                id=account_id,
                owner_id=viewer.id,
                platform_id=platform.id,
                label="Conta viewer",
                status="active",
                config={},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    headers = auth_header(str(login(client, viewer.email)["access_token"]))
    assert_error(
        client.put(
            f"/api/accounts/{account_id}/credentials/cookie",
            headers=headers,
            json={"value": "nao-pode"},
        ),
        403,
        "FORBIDDEN",
    )
    missing = client.delete(
        f"/api/accounts/{account_id}/credentials/cookie",
        headers=headers,
    )
    assert_error(missing, 403, "FORBIDDEN")

    admin = add_user(session_factory, email="admin@example.com", role="admin")
    admin_account = uuid4()
    with session_factory.begin() as session:
        session.add(
            PlatformAccount(
                id=admin_account,
                owner_id=admin.id,
                platform_id=platform.id,
                label="Conta admin",
                status="active",
                config={},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    admin_headers = auth_header(str(login(client, admin.email)["access_token"]))
    assert_error(
        client.delete(
            f"/api/accounts/{admin_account}/credentials/cookie",
            headers=admin_headers,
        ),
        404,
        "NOT_FOUND",
    )


class UnauthorizedHTTPClient:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> UnauthorizedHTTPClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, **_kwargs: object) -> httpx.Response:
        return httpx.Response(401, request=httpx.Request("POST", url))


class ShopeeSuccessHTTPClient(UnauthorizedHTTPClient):
    def post(self, url: str, **kwargs: object) -> httpx.Response:
        headers = kwargs["headers"]
        assert str(headers["Authorization"]).startswith("SHA256 Credential=app-1")
        assert b"productOfferV2" in kwargs["content"]
        return httpx.Response(
            200,
            json={"data": {"productOfferV2": {"nodes": []}}},
            request=httpx.Request("POST", url),
        )


class NetworkFailureHTTPClient(UnauthorizedHTTPClient):
    def post(self, url: str, **_kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("offline", request=httpx.Request("POST", url))


def test_clientes_de_plataforma_usam_http_mockado_e_distinguem_rede(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.platforms.registry.httpx.Client", ShopeeSuccessHTTPClient)
    shopee = ShopeeClient().test_credentials(
        {"app_secret": "secret"},
        {"app_id": "app-1"},
    )
    assert shopee.ok is True

    monkeypatch.setattr("core.platforms.registry.httpx.Client", NetworkFailureHTTPClient)
    mercado_livre = MercadoLivreClient().test_credentials(
        {"cookie": "session=abc"},
        {"affiliate_tag": "nina01"},
    )
    assert mercado_livre.ok is False
    assert mercado_livre.network_error is True
    assert mercado_livre.invalid is False


def test_credencial_ruim_marca_invalid_sem_vazar_na_auditoria(
    client: object,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    platform = add_platform(session_factory)
    token = str(login(client, admin.email)["access_token"])
    headers = auth_header(token)
    account_id = create_account(client, token, platform.id)["id"]
    secret = "SENTINELA-audit-cookie-secreto"
    assert (
        client.put(
            f"/api/accounts/{account_id}/credentials/cookie",
            headers=headers,
            json={"value": secret},
        ).status_code
        == 204
    )
    monkeypatch.setattr("core.platforms.registry.httpx.Client", UnauthorizedHTTPClient)
    tested = client.post(
        f"/api/accounts/{account_id}/credentials/cookie/test",
        headers=headers,
    )
    assert tested.status_code == 200
    assert tested.json()["ok"] is False
    with session_factory() as session:
        credential = session.scalar(select(PlatformCredential))
        assert credential is not None
        assert credential.status == "invalid"
        assert credential.last_error
        audit_payload = json.dumps(
            [
                {"before": entry.before, "after": entry.after}
                for entry in session.scalars(select(AuditLog))
            ],
            default=str,
        )
        assert secret not in audit_payload


def test_varredura_recursiva_anti_vazamento_em_todas_as_respostas(
    client: object,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "SENTINELA-Nq7x2-COOKIE-SECRETO"
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    platform = add_platform(session_factory)
    login_response = login(client, admin.email)
    token = str(login_response["access_token"])
    headers = auth_header(token)
    account_id = create_account(client, token, platform.id)["id"]
    put = client.put(
        f"/api/accounts/{account_id}/credentials/cookie",
        headers=headers,
        json={"value": sentinel},
    )
    assert put.status_code == 204

    monkeypatch.setattr("core.platforms.registry.httpx.Client", UnauthorizedHTTPClient)
    responses = [
        client.get("/api/platforms", headers=headers),
        client.get("/api/accounts", headers=headers),
        client.get(f"/api/accounts/{account_id}", headers=headers),
        client.patch(
            f"/api/accounts/{account_id}",
            headers=headers,
            json={"notes": "checagem"},
        ),
        client.post(f"/api/accounts/{account_id}/pause", headers=headers),
        client.post(f"/api/accounts/{account_id}/activate", headers=headers),
        client.get(f"/api/accounts/{account_id}/credentials", headers=headers),
        client.post(
            f"/api/accounts/{account_id}/credentials/cookie/test",
            headers=headers,
        ),
        client.get("/api/users", headers=headers),
        client.get("/api/auth/me", headers=headers),
        client.get("/api/audit-logs", headers=headers),
        client.get("/api/health"),
    ]
    payloads: list[object] = [login_response]
    for response in responses:
        assert response.status_code < 400, response.text
        payloads.append(response.json())
    for payload in payloads:
        assert_not_present_recursively(payload, sentinel)
        assert sentinel not in json.dumps(payload, default=str)

    with session_factory() as session:
        audit_rows = [
            {"before": row.before, "after": row.after}
            for row in session.scalars(select(AuditLog))
        ]
    assert_not_present_recursively(audit_rows, sentinel)
    assert sentinel not in json.dumps(audit_rows, default=str)


def test_aliexpress_retorna_501_claro(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    platform = add_platform(session_factory, slug="aliexpress", name="AliExpress")
    token = str(login(client, admin.email)["access_token"])
    headers = auth_header(token)
    account_id = create_account(client, token, platform.id)["id"]
    assert (
        client.put(
            f"/api/accounts/{account_id}/credentials/api_key",
            headers=headers,
            json={"value": "segredo"},
        ).status_code
        == 204
    )
    response = client.post(
        f"/api/accounts/{account_id}/credentials/api_key/test",
        headers=headers,
    )
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "NOT_IMPLEMENTED"
    assert "AliExpress" in response.json()["error"]["message"]


def test_cookie_aceita_json_exportado_pelo_navegador(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    from core.credentials import normalize_cookie, read_account_credentials

    exportado = json.dumps(
        [
            {"domain": ".mercadolivre.com.br", "name": "ssid", "value": "abc-123", "httpOnly": True},
            {"domain": "www.mercadolivre.com.br", "name": "_csrf", "value": "x=y"},
            {"domain": ".mercadolivre.com.br", "name": "orgnickp", "value": "MIDI"},
        ]
    )
    assert normalize_cookie(exportado) == "ssid=abc-123; _csrf=x=y; orgnickp=MIDI"
    assert normalize_cookie("  a=1; b=2 ") == "a=1; b=2"
    # A extensão decodifica valores; cabeçalho HTTP é ASCII (UnicodeEncodeError real).
    acentuado = json.dumps([{"name": "LAST_SEARCH", "value": "Luminárias%20Led"}])
    assert normalize_cookie(acentuado) == "LAST_SEARCH=Lumin%C3%A1rias%20Led"
    assert normalize_cookie(acentuado).isascii()
    with pytest.raises(ValueError):
        normalize_cookie("[{nao e json")

    admin = add_user(session_factory, email="admin@example.com", role="admin")
    platform = add_platform(session_factory)
    token = str(login(client, admin.email)["access_token"])
    headers = auth_header(token)
    account_id = create_account(client, token, platform.id)["id"]

    response = client.put(
        f"/api/accounts/{account_id}/credentials/cookie",
        headers=headers,
        json={"value": exportado},
    )
    assert response.status_code == 204, response.text
    with session_factory() as session:
        values, _ = read_account_credentials(session, account_id)
    assert values["cookie"] == "ssid=abc-123; _csrf=x=y; orgnickp=MIDI"

    invalido = client.put(
        f"/api/accounts/{account_id}/credentials/cookie",
        headers=headers,
        json={"value": "[]"},
    )
    assert_error(invalido, 422, "VALIDATION_ERROR")


def test_erro_inesperado_no_teste_de_credencial_nao_vira_500(
    client: object,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.routers import credentials as credentials_router

    class Quebra:
        def test_credentials(self, *_args: object) -> None:
            raise UnicodeEncodeError("ascii", "á", 0, 1, "ordinal not in range(128)")

    monkeypatch.setattr(credentials_router, "resolve", lambda _slug: Quebra())
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    platform = add_platform(session_factory)
    token = str(login(client, admin.email)["access_token"])
    headers = auth_header(token)
    account_id = create_account(client, token, platform.id)["id"]
    client.put(
        f"/api/accounts/{account_id}/credentials/cookie", headers=headers, json={"value": "a=1"}
    )

    response = client.post(f"/api/accounts/{account_id}/credentials/cookie/test", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is False
    assert "UnicodeEncodeError" in response.json()["message"]
    assert "a=1" not in response.text


class MLRejectsURLHTTPClient(UnauthorizedHTTPClient):
    # Resposta real do createLink para URL fora do programa (capturada em 2026-09-24).
    def post(self, url: str, **kwargs: object) -> httpx.Response:
        origin = kwargs["json"]["urls"][0]
        body = {
            "status": 200,
            "urls": [
                {
                    "origin_url": origin,
                    "message": "URL not allowed in affiliates program",
                    "error_code": 111,
                    "status": 200,
                }
            ],
            "total_items": 1,
            "total_success": 0,
            "total_error": 1,
        }
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))


class MLSuccessHTTPClient(UnauthorizedHTTPClient):
    def post(self, url: str, **kwargs: object) -> httpx.Response:
        body = {"urls": [{"short_url": "https://meli.la/teste"}], "total_success": 1}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))


def test_ml_testa_com_produto_real_e_repassa_motivo_da_recusa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.platforms import registry

    # Com o id inventado "MLB1" o ML reprovava todo cookie válido.
    assert "/p/MLB1027172669" in registry.TEST_PRODUCT_URL

    monkeypatch.setattr("core.platforms.registry.httpx.Client", MLSuccessHTTPClient)
    ok = MercadoLivreClient().test_credentials({"cookie": "ssid=a"}, {"affiliate_tag": "t"})
    assert ok.ok is True

    monkeypatch.setattr("core.platforms.registry.httpx.Client", MLRejectsURLHTTPClient)
    recusa = MercadoLivreClient().test_credentials({"cookie": "ssid=a"}, {"affiliate_tag": "t"})
    assert recusa.ok is False
    assert recusa.invalid is False
    assert "URL not allowed in affiliates program" in recusa.message
