# ruff: noqa: F401, F811
"""Instâncias controladas pela plataforma; Evolution sempre simulada."""

import json
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from api.security import create_access_token
from core.evolution import EvolutionClient
from core.models import Phone
from tests.test_api import add_user, auth_header, client, session_factory


def headers(user):
    return auth_header(create_access_token(str(user.id), session_version=user.session_version))


def test_cliente_nao_define_instancia_e_platform_nao_reutiliza(
    client, session_factory, monkeypatch
):
    monkeypatch.setattr(EvolutionClient, "connection_status", lambda *args: "unknown")
    a = add_user(session_factory, email="platform@teste.com", role="admin")
    b = add_user(session_factory, email="cliente@teste.com", role="admin", is_platform_admin=False)
    for value in ("nina", None):
        assert (
            client.post(
                "/api/phones",
                headers=headers(b),
                json={"label": "Cliente", "number": "551100000001", "evolution_instance": value},
            ).status_code
            == 403
        )
    created = client.post(
        "/api/phones", headers=headers(b), json={"label": "Cliente", "number": "551100000001"}
    )
    assert created.status_code == 201
    phone_id = created.json()["id"]
    assert (
        client.patch(
            f"/api/phones/{phone_id}", headers=headers(b), json={"evolution_instance": None}
        ).status_code
        == 403
    )
    nina = client.post(
        "/api/phones",
        headers=headers(a),
        json={"label": "Nina", "number": "551100000002", "evolution_instance": "nina"},
    )
    assert nina.status_code == 201
    duplicate = client.post(
        "/api/phones",
        headers=headers(a),
        json={"label": "Outro", "number": "551100000003", "evolution_instance": "nina"},
    )
    assert duplicate.status_code == 409
    second = client.post(
        "/api/phones", headers=headers(a), json={"label": "Outro", "number": "551100000003"}
    )
    assert (
        client.patch(
            f"/api/phones/{second.json()['id']}",
            headers=headers(a),
            json={"evolution_instance": "nina"},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("status", [201, 503])
def test_conectar_cria_v2_persiste_reusa_qr_e_trata_falha(
    client, session_factory, monkeypatch, status
):
    user = add_user(
        session_factory, email="cliente@teste.com", role="admin", is_platform_admin=False
    )
    phone_id = uuid4()
    with session_factory.begin() as session:
        session.add(
            Phone(id=phone_id, owner_id=user.tenant_id, label="Cliente", number="551100000001")
        )
    calls = []

    def handle(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(status, json={"qrcode": {"base64": "QR_TESTE"}})
        return httpx.Response(200, json={"base64": "QR_EXISTENTE"})

    original_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    endpoint = f"/api/phones/{phone_id}/instance"
    result = client.post(endpoint, headers=headers(user))
    instance = f"nb-{str(user.tenant_id)[:8]}-{str(phone_id)[:8]}"
    assert calls[0].url.path == "/instance/create"
    assert "apikey" in calls[0].headers
    assert json.loads(calls[0].content) == {
        "instanceName": instance,
        "qrcode": True,
        "integration": "WHATSAPP-BAILEYS",
    }
    with session_factory() as session:
        assert session.get(Phone, phone_id).evolution_instance == (
            instance if status == 201 else None
        )
    if status == 503:
        assert result.status_code == 503
        return
    assert result.status_code == 200 and result.json()["qrcode_base64"] == "QR_TESTE"
    assert "expires_at" in result.json()
    result = client.post(endpoint, headers=headers(user))
    assert result.status_code == 200 and result.json()["qrcode_base64"] == "QR_EXISTENTE"
    assert calls[-1].url.path == f"/instance/connect/{instance}" and len(calls) == 2
    # Remover telefone não remove a instância no provedor.
    assert client.delete(f"/api/phones/{phone_id}", headers=headers(user)).status_code == 204
    assert len(calls) == 2
    assert all(call.method != "DELETE" for call in calls)
    with session_factory() as session:
        assert session.scalar(select(Phone.id).where(Phone.id == UUID(str(phone_id)))) is None


def test_criacao_sem_qr_preserva_instancia_para_tentar_novamente(
    client, session_factory, monkeypatch
):
    user = add_user(
        session_factory, email="cliente@teste.com", role="admin", is_platform_admin=False
    )
    phone_id = uuid4()
    with session_factory.begin() as session:
        session.add(
            Phone(id=phone_id, owner_id=user.tenant_id, label="Cliente", number="551100000001")
        )
    calls = []

    def handle(request):
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(201, json={"instance": {"status": "created"}})
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"base64": "QR_PRONTO"})

    original_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    endpoint = f"/api/phones/{phone_id}/instance"
    assert client.post(endpoint, headers=headers(user)).status_code == 503
    with session_factory() as session:
        assert session.get(Phone, phone_id).evolution_instance is not None
    result = client.post(endpoint, headers=headers(user))
    assert result.status_code == 200 and result.json()["qrcode_base64"] == "QR_PRONTO"
    assert calls == ["POST", "GET", "GET"]
