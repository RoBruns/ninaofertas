# ruff: noqa: F401, F811
"""Contrato Evolution e segredos por telefone, sempre com HTTP simulado."""

import json
from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from core import config_provider, crypto
from core.evolution import (
    EvolutionAlreadyConnected, EvolutionClient, EvolutionConflict,
    EvolutionRejected, EvolutionUnavailable,
)
from core.models import AuditLog, Event, Phone
from core.settings import settings
from tests.runtime_helpers import runtime_do_config
from tests.test_api import add_user, client, session_factory
from tests.test_tenant_phones import headers
from tests.test_worker_config import _active_bot, _patch_sessions
from worker import whatsapp

TOKEN = "segredo-da-instancia-so-em-memoria"


@pytest.fixture(autouse=True)
def cipher_key(monkeypatch):
    monkeypatch.setenv("CREDENTIALS_KEY", "eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=")


def mock_http(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.parametrize("hash_value", [TOKEN, {"apikey": TOKEN}])
def test_creation_encrypts_token_without_exposing_it(client, session_factory, monkeypatch, hash_value):
    user = add_user(session_factory, email="token@teste.com", role="admin", is_platform_admin=False)
    created = client.post("/api/phones", headers=headers(user), json={"label": "Sem número"})
    assert created.status_code == 201 and created.json()["number"] is None
    phone_id = UUID(created.json()["id"])
    calls = []

    def handle(request):
        calls.append(request)
        assert request.headers["apikey"] == settings.evolution_api_key
        assert json.loads(request.content) == {
            "instanceName": f"nb-{str(user.tenant_id)[:8]}-{str(phone_id)[:8]}",
            "qrcode": True, "integration": "WHATSAPP-BAILEYS",
        }
        return httpx.Response(201, json={"hash": hash_value, "qrcode": {"base64": "QR"}})

    mock_http(monkeypatch, handle)
    response = client.post(f"/api/phones/{phone_id}/instance", headers=headers(user))
    assert response.status_code == 200 and TOKEN not in response.text
    with session_factory() as session:
        phone = session.get(Phone, phone_id)
        assert TOKEN.encode() not in phone.instance_token_ciphertext
        assert crypto.decrypt(phone.instance_token_ciphertext) == TOKEN
        assert phone.instance_token_fingerprint == crypto.fingerprint(TOKEN)
        assert phone.instance_token_updated_at is not None
        audits = list(session.scalars(select(AuditLog)))
        assert TOKEN not in repr([(a.before, a.after) for a in audits])
    monkeypatch.setattr(EvolutionClient, "connection_status", lambda *args: "connecting")
    listed = client.get("/api/phones", headers=headers(user))
    assert TOKEN not in listed.text
    assert listed.json()["items"][0]["has_instance_token"]
    assert listed.json()["items"][0]["status"] == "connecting"
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [
    [{"token": TOKEN}], {"instance": {"apikey": TOKEN}},
    {"hash": TOKEN}, {"hash": {"apikey": TOKEN}},
])
def test_fetch_formats(monkeypatch, payload):
    def handle(request):
        assert request.url.path == "/instance/fetchInstances"
        assert request.url.params["instanceName"] == "phone"
        assert request.headers["apikey"] == "management"
        return httpx.Response(200, json=payload)
    mock_http(monkeypatch, handle)
    assert EvolutionClient("https://evolution.test", "management").fetch_instance_token("phone") == TOKEN


def test_fetch_missing_instance(monkeypatch):
    mock_http(monkeypatch, lambda _: httpx.Response(404))
    assert EvolutionClient().fetch_instance_token("missing") is None


def test_creation_fetches_qr_when_provider_has_not_prepared_it(monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(201, json={"hash": TOKEN})
        return httpx.Response(200, json={"base64": "QR_PRONTO"})
    mock_http(monkeypatch, handle)
    created = EvolutionClient().create_instance("phone")
    assert created.token == TOKEN and created.qrcode_base64 == "QR_PRONTO"
    assert [r.url.path for r in calls] == ["/instance/create", "/instance/connect/phone"]


@pytest.mark.parametrize("status,payload,error", [
    (403, {"message": 'This name "phone" is already in use.'}, EvolutionConflict),
    (400, {"message": "integration inválida"}, EvolutionRejected),
    (500, {"message": TOKEN}, EvolutionUnavailable),
    (201, {"hash": {}}, EvolutionUnavailable),
])
def test_create_errors_do_not_include_response_body(monkeypatch, status, payload, error):
    mock_http(monkeypatch, lambda _: httpx.Response(status, json=payload))
    with pytest.raises(error) as caught:
        EvolutionClient().create_instance("phone")
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("payload,error", [
    ({"instance": {"state": "open"}}, EvolutionAlreadyConnected),
    ({"error": True, "message": TOKEN}, EvolutionUnavailable),
])
def test_connect_open_and_http_200_error(monkeypatch, payload, error):
    mock_http(monkeypatch, lambda _: httpx.Response(200, json=payload))
    with pytest.raises(error) as caught:
        EvolutionClient().qrcode("phone")
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("token,status,expected,success", [
    (TOKEN, 200, [TOKEN], True), (None, 200, ["management"], True),
    (None, 401, ["management"], False),
    (TOKEN, 401, [TOKEN, "management"], True),
    (TOKEN, 500, [TOKEN], False), (TOKEN, 404, [TOKEN], False),
])
@pytest.mark.parametrize("media", [False, True])
def test_send_token_retry_and_no_secret_in_logs_or_events(
    session_factory, monkeypatch, token, status, expected, success, media,
):
    _patch_sessions(monkeypatch, session_factory)
    bot, _ = _active_bot(session_factory)
    runtime = replace(runtime_do_config("config.json"), id=bot.id, owner_id=bot.owner_id,
                      instance_token=token, evolution_instance="phone")
    assert TOKEN not in repr(runtime)
    monkeypatch.setattr(settings, "evolution_api_key", "management")
    calls, logs = [], []
    sink = whatsapp.logger.add(lambda message: logs.append(str(message)))

    def handle(request):
        calls.append(request)
        # A evolution só pode ecoar a chave que recebeu; nenhuma das duas pode ir ao log.
        return httpx.Response(status if len(calls) == 1 else 200, text=request.headers["apikey"])

    mock_http(monkeypatch, handle)
    try:
        with config_provider.usar_bot_runtime(runtime):
            assert whatsapp.enviar_mensagem(
                "mensagem", grupo="g@g.us",
                imagem="https://http2.mlstatic.com/image.jpg" if media else None,
            ) is success
    finally:
        whatsapp.logger.remove(sink)
    assert "management" not in "".join(logs)
    assert [r.headers["apikey"] for r in calls] == expected
    assert all(("sendMedia" if media else "sendText") in r.url.path for r in calls)
    if len(calls) == 2:
        assert calls[0].content == calls[1].content
    with session_factory() as session:
        events = list(session.scalars(select(Event).where(Event.type == "evolution_instance_token_rejected")))
        assert len(events) == (1 if status == 401 and token else 0)
        for event in events:
            assert event.level == "warning" and event.tenant_id == bot.owner_id
            assert TOKEN not in repr((event.message, event.detail))
    assert TOKEN not in "".join(logs)


def test_send_error_logs_diagnostic_without_keys(session_factory, monkeypatch):
    _patch_sessions(monkeypatch, session_factory)
    bot, _ = _active_bot(session_factory)
    runtime = replace(runtime_do_config("config.json"), id=bot.id, owner_id=bot.owner_id,
                      instance_token=TOKEN, evolution_instance="phone")
    monkeypatch.setattr(settings, "evolution_api_key", "management-key")
    logs = []
    sink = whatsapp.logger.add(lambda message: logs.append(str(message)))
    body = f'{{"message": "number does not exist", "echo": "{TOKEN} management-key"}}'
    mock_http(monkeypatch, lambda request: httpx.Response(400, text=body))
    try:
        with config_provider.usar_bot_runtime(runtime):
            assert not whatsapp.enviar_mensagem("texto", grupo="g@g.us")
    finally:
        whatsapp.logger.remove(sink)
    texto = "".join(logs)
    assert "number does not exist" in texto
    assert TOKEN not in texto and "management-key" not in texto


def test_runtime_decrypts_phone_token(session_factory, monkeypatch):
    _patch_sessions(monkeypatch, session_factory)
    bot, catalog = _active_bot(session_factory)
    with session_factory.begin() as session:
        session.get(Phone, catalog["phone_id"]).instance_token_ciphertext = crypto.encrypt(TOKEN)
    runtime = config_provider._carregar()[0]
    assert runtime.id == bot.id and runtime.instance_token == TOKEN
    assert TOKEN not in repr(runtime)


def test_changing_instance_clears_previous_token(client, session_factory, monkeypatch):
    user = add_user(session_factory, email="change@teste.com", role="admin")
    phone_id = uuid4()
    with session_factory.begin() as session:
        session.add(Phone(id=phone_id, owner_id=user.tenant_id, label="Telefone", evolution_instance="old",
                          instance_token_ciphertext=crypto.encrypt(TOKEN), instance_token_fingerprint=crypto.fingerprint(TOKEN)))
    monkeypatch.setattr(EvolutionClient, "connection_status", lambda *args: "unknown")
    response = client.patch(f"/api/phones/{phone_id}", headers=headers(user), json={"evolution_instance": "new"})
    assert response.status_code == 200 and not response.json()["has_instance_token"]
    with session_factory() as session:
        phone = session.get(Phone, phone_id)
        assert phone.instance_token_ciphertext is None
        assert phone.instance_token_fingerprint is None and phone.instance_token_updated_at is None


def test_second_401_does_not_retry_again(session_factory, monkeypatch):
    _patch_sessions(monkeypatch, session_factory)
    bot, _ = _active_bot(session_factory)
    runtime = replace(runtime_do_config("config.json"), id=bot.id, owner_id=bot.owner_id,
                      instance_token=TOKEN, evolution_instance="phone")
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(401, text=TOKEN)
    mock_http(monkeypatch, handle)
    with config_provider.usar_bot_runtime(runtime):
        assert not whatsapp.enviar_mensagem("texto", grupo="g@g.us")
    assert len(calls) == 2


@pytest.mark.parametrize("existing,conflict", [(True, False), (False, True)])
def test_recovers_token_before_qr_and_already_connected(
    client, session_factory, monkeypatch, existing, conflict,
):
    user = add_user(session_factory, email="recover@teste.com", role="admin")
    phone_id = uuid4()
    name = f"nb-{str(user.tenant_id)[:8]}-{str(phone_id)[:8]}"
    with session_factory.begin() as session:
        session.add(Phone(id=phone_id, owner_id=user.tenant_id, label="Telefone",
                          evolution_instance=name if existing else None))
    calls = []

    def handle(request):
        calls.append(request)
        if request.method == "POST":
            assert conflict
            return httpx.Response(403, text=f'This name "{name}" is already in use.')
        if request.url.path.endswith("fetchInstances"):
            return httpx.Response(200, json=[{"token": TOKEN, "ownerJid": "5511999999999@s.whatsapp.net"}])
        return httpx.Response(200, json={"instance": {"state": "open"}})

    mock_http(monkeypatch, handle)
    response = client.post(f"/api/phones/{phone_id}/instance", headers=headers(user))
    assert response.status_code == 409 and response.json()["error"]["code"] == "ALREADY_CONNECTED"
    with session_factory() as session:
        phone = session.get(Phone, phone_id)
        assert crypto.decrypt(phone.instance_token_ciphertext) == TOKEN
        assert phone.number == "5511999999999" and phone.status == "connected"


def test_sync_rotates_token_and_audits_only_fingerprint(client, session_factory, monkeypatch):
    user = add_user(session_factory, email="sync@teste.com", role="admin")
    phone_id = uuid4()
    with session_factory.begin() as session:
        session.add(Phone(id=phone_id, owner_id=user.tenant_id, label="Telefone", evolution_instance="phone",
                          instance_token_ciphertext=crypto.encrypt("old"), instance_token_fingerprint=crypto.fingerprint("old")))
    mock_http(monkeypatch, lambda _: httpx.Response(200, json=[{"token": TOKEN}]))
    response = client.post(f"/api/phones/{phone_id}/instance/token/sync", headers=headers(user))
    assert response.status_code == 200 and TOKEN not in response.text
    assert response.json()["has_instance_token"]
    with session_factory() as session:
        phone = session.get(Phone, phone_id)
        assert crypto.decrypt(phone.instance_token_ciphertext) == TOKEN
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "sync_instance_token"))
        assert audit.after == {"fingerprint": crypto.fingerprint(TOKEN)}
        assert audit.before == {"fingerprint": crypto.fingerprint("old")}


def test_status_connecting_then_open_populates_number(client, session_factory, monkeypatch):
    user = add_user(session_factory, email="status@teste.com", role="admin")
    phone_id = uuid4()
    with session_factory.begin() as session:
        session.add(Phone(id=phone_id, owner_id=user.tenant_id, label="Telefone", evolution_instance="phone"))
    state = "connecting"
    def handle(request):
        assert request.headers["apikey"] == settings.evolution_api_key
        if request.url.path.endswith("fetchInstances"):
            return httpx.Response(200, json=[{"token": TOKEN, "ownerJid": "5511999999999@s.whatsapp.net"}])
        return httpx.Response(200, json={"instance": {"state": state}})
    mock_http(monkeypatch, handle)
    endpoint = f"/api/phones/{phone_id}/status"
    assert client.get(endpoint, headers=headers(user)).json()["status"] == "connecting"
    state = "open"
    response = client.get(endpoint, headers=headers(user))
    assert response.json()["number"] == "5511999999999" and TOKEN not in response.text
    mock_http(monkeypatch, lambda _: httpx.Response(503))
    assert client.get(endpoint, headers=headers(user)).status_code == 503


@pytest.mark.parametrize("instance", ["../phone", "a/b", "a?b", "a b", "x" * 65, ""])
def test_platform_instance_name_is_validated(client, session_factory, monkeypatch, instance):
    user = add_user(session_factory, email="validate@teste.com", role="admin")
    response = client.post("/api/phones", headers=headers(user), json={"label": "Teste", "evolution_instance": instance})
    assert response.status_code == 422


def test_db_conflict_precedes_external_creation(client, session_factory, monkeypatch):
    user = add_user(session_factory, email="collision@teste.com", role="admin")
    phone_id, other_id = uuid4(), uuid4()
    name = f"nb-{str(user.tenant_id)[:8]}-{str(phone_id)[:8]}"
    with session_factory.begin() as session:
        session.add_all([Phone(id=phone_id, owner_id=user.tenant_id, label="Novo"),
                         Phone(id=other_id, owner_id=user.tenant_id, label="Outro", evolution_instance=name)])
    mock_http(monkeypatch, lambda _: pytest.fail("Criação externa antes da reserva no banco"))
    response = client.post(f"/api/phones/{phone_id}/instance", headers=headers(user))
    assert response.status_code == 409
    with session_factory() as session:
        assert session.get(Phone, phone_id).evolution_instance is None
