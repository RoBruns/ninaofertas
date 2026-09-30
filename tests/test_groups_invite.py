# ruff: noqa: F401, F811
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import func, select

from core.models import AuditLog, Group, Phone
from tests.test_api import add_user, auth_header, client, login, session_factory

CODE = "AbCdEfGhIjKlMnOpQrStUv"


@pytest.fixture
def invite_setup(client, session_factory):
    user = add_user(session_factory, email="invite@example.com", role="admin")
    headers = auth_header(str(login(client, user.email)["access_token"]))
    with session_factory.begin() as session:
        phone = Phone(owner_id=user.id, label="Principal", number="5511999999999", evolution_instance="nina")
        session.add(phone)
        session.flush()
        phone_id = str(phone.id)
    return headers, phone_id


def evolution_response(status=200, payload=None):
    return httpx.Response(status, json=payload or {"id": "123@g.us", "subject": "Promoções"},
                          request=httpx.Request("GET", "https://evolution.test"))


# O WhatsApp gera links com "?mode=..."; só o código segue para a Evolution.
@pytest.mark.parametrize("invite", [CODE, f"https://chat.whatsapp.com/{CODE}", f"https://chat.whatsapp.com/{CODE}?mode=ems_copy_t"])
def test_invite_creates_group(client, session_factory, invite_setup, invite):
    headers, phone_id = invite_setup
    with patch("core.evolution.httpx.Client.get", return_value=evolution_response()) as get:
        result = client.post("/api/groups/from-invite", headers=headers,
                             json={"phone_id": phone_id, "invite_link": invite})
    assert result.status_code == 201, result.text
    assert result.json()["whatsapp_id"] == "123@g.us"
    assert result.json()["name"] == "Promoções"
    assert result.json()["phone_id"] == phone_id
    assert get.call_args.args[0].endswith("/group/inviteInfo/nina")
    assert get.call_args.kwargs["params"] == {"inviteCode": CODE}
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_type == "group")) == 1


@pytest.mark.parametrize("invite", ["bad", "https://evil.test/" + CODE, "https://chat.whatsapp.com/"])
def test_invalid_invite(client, invite_setup, invite):
    headers, phone_id = invite_setup
    with patch("core.evolution.httpx.Client.get") as get:
        result = client.post("/api/groups/from-invite", headers=headers,
                             json={"phone_id": phone_id, "invite_link": invite})
    assert result.status_code == 422
    assert "Link de convite inválido" in result.json()["error"]["message"]
    assert "Link de convite inválido" in result.json()["error"]["fields"]["invite_link"]
    get.assert_not_called()


def test_existing_invite_is_idempotent(client, session_factory, invite_setup):
    headers, phone_id = invite_setup
    with patch("core.evolution.httpx.Client.get", return_value=evolution_response()):
        first = client.post("/api/groups/from-invite", headers=headers, json={"phone_id": phone_id, "invite_link": CODE})
        second = client.post("/api/groups/from-invite", headers=headers, json={"phone_id": phone_id, "invite_link": CODE})
    assert second.status_code == 200
    assert first.json() == second.json()
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Group)) == 1


def test_existing_group_for_owner_on_another_phone(client, session_factory, invite_setup):
    headers, phone_id = invite_setup
    with session_factory.begin() as session:
        from uuid import UUID
        phone = session.get(Phone, UUID(phone_id))
        other_phone = Phone(owner_id=phone.owner_id, label="Outro", number="5511888888888", evolution_instance="outro")
        session.add(other_phone)
        session.flush()
        group = Group(owner_id=phone.owner_id, phone_id=other_phone.id, whatsapp_id="123@g.us", name="Existente")
        session.add(group)
        session.flush()
        existing_id = str(group.id)
    with patch("core.evolution.httpx.Client.get", return_value=evolution_response()):
        result = client.post("/api/groups/from-invite", headers=headers, json={"phone_id": phone_id, "invite_link": CODE})
    assert result.status_code == 200
    assert result.json()["id"] == existing_id
    assert result.json()["name"] == "Existente"


@pytest.mark.parametrize("status,expected", [(500, 503), (403, 422), (400, 422)])
def test_evolution_errors(client, invite_setup, status, expected):
    headers, phone_id = invite_setup
    with patch("core.evolution.httpx.Client.get", return_value=evolution_response(status)):
        result = client.post("/api/groups/from-invite", headers=headers, json={"phone_id": phone_id, "invite_link": CODE})
    assert result.status_code == expected


def test_evolution_network_unavailable(client, invite_setup):
    headers, phone_id = invite_setup
    with patch("core.evolution.httpx.Client.get", side_effect=httpx.ConnectError("down")):
        result = client.post("/api/groups/from-invite", headers=headers, json={"phone_id": phone_id, "invite_link": CODE})
    assert result.status_code == 503


def test_non_member_not_created(client, invite_setup):
    headers, phone_id = invite_setup
    with patch("core.evolution.httpx.Client.get", return_value=evolution_response(payload={"id": "123@g.us", "isMember": False})):
        result = client.post("/api/groups/from-invite", headers=headers, json={"phone_id": phone_id, "invite_link": CODE})
    assert result.status_code == 422
    assert "membro" in result.json()["error"]["message"]
