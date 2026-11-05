# ruff: noqa: E402, F401, F811

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from core.models import Tenant
from tests.test_api import add_user, assert_error, auth_header, client, login, session_factory


def _headers(api: TestClient, email: str) -> dict[str, str]:
    return auth_header(str(login(api, email)["access_token"]))


def test_seed_board_no_primeiro_get(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    add_user(session_factory, email="tarefas@example.com", role="viewer")
    headers = _headers(client, "tarefas@example.com")
    listed = client.get("/api/task-boards", headers=headers)
    assert listed.status_code == 200
    boards = listed.json()
    assert len(boards) == 1
    assert boards[0]["name"] == "Meu quadro"

    detail = client.get(f"/api/task-boards/{boards[0]['id']}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert [item["name"] for item in body["lists"]] == ["A fazer", "Em andamento", "Feito"]
    assert all(item["cards"] == [] for item in body["lists"])

    again = client.get("/api/task-boards", headers=headers)
    assert len(again.json()) == 1


def test_isolamento_entre_usuarios_do_mesmo_tenant(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    tenant_id = uuid4()
    with session_factory.begin() as session:
        session.add(Tenant(id=tenant_id, name="Conta compartilhada", is_internal=True))
    add_user(
        session_factory,
        email="dono-a@example.com",
        role="admin",
        tenant_id=tenant_id,
        is_platform_admin=False,
    )
    add_user(
        session_factory,
        email="dono-b@example.com",
        role="operator",
        tenant_id=tenant_id,
        is_platform_admin=False,
    )
    headers_a = _headers(client, "dono-a@example.com")
    headers_b = _headers(client, "dono-b@example.com")

    board_a = client.get("/api/task-boards", headers=headers_a).json()[0]
    board_b = client.get("/api/task-boards", headers=headers_b).json()[0]
    assert board_a["id"] != board_b["id"]

    assert_error(
        client.get(f"/api/task-boards/{board_a['id']}", headers=headers_b),
        404,
        "NOT_FOUND",
    )
    assert_error(
        client.get(f"/api/task-boards/{board_b['id']}", headers=headers_a),
        404,
        "NOT_FOUND",
    )


def test_criar_mover_card_e_detalhe(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    add_user(session_factory, email="kanban@example.com", role="operator")
    headers = _headers(client, "kanban@example.com")
    board = client.get("/api/task-boards", headers=headers).json()[0]
    detail = client.get(f"/api/task-boards/{board['id']}", headers=headers).json()
    list_a, list_b = detail["lists"][0], detail["lists"][1]

    created = client.post(
        f"/api/task-boards/{board['id']}/cards",
        headers=headers,
        json={"list_id": list_a["id"], "title": "Publicar oferta", "priority": "high"},
    )
    assert created.status_code == 201
    card = created.json()
    assert card["title"] == "Publicar oferta"
    assert card["list_id"] == list_a["id"]
    assert card["priority"] == "high"

    moved = client.post(
        f"/api/task-boards/cards/{card['id']}/move",
        headers=headers,
        json={"list_id": list_b["id"], "position": 0},
    )
    assert moved.status_code == 200
    assert moved.json()["list_id"] == list_b["id"]
    assert moved.json()["position"] == 0

    label = client.post(
        f"/api/task-boards/{board['id']}/labels",
        headers=headers,
        json={"name": "Urgente", "color": "#ef4444"},
    )
    assert label.status_code == 201

    labeled = client.put(
        f"/api/task-boards/cards/{card['id']}/labels",
        headers=headers,
        json={"label_ids": [label.json()["id"]]},
    )
    assert labeled.status_code == 200
    assert labeled.json()["label_ids"] == [label.json()["id"]]

    comment = client.post(
        f"/api/task-boards/cards/{card['id']}/comments",
        headers=headers,
        json={"body": "Lembrar do freio anti-ban"},
    )
    assert comment.status_code == 201

    checklist = client.post(
        f"/api/task-boards/cards/{card['id']}/checklists",
        headers=headers,
        json={"title": "Passos"},
    )
    assert checklist.status_code == 201
    item = client.post(
        f"/api/task-boards/checklists/{checklist.json()['id']}/items",
        headers=headers,
        json={"title": "Revisar cookie ML"},
    )
    assert item.status_code == 201
    toggled = client.patch(
        f"/api/task-boards/checklist-items/{item.json()['id']}",
        headers=headers,
        json={"done": True},
    )
    assert toggled.status_code == 200
    assert toggled.json()["done"] is True

    full = client.get(f"/api/task-boards/cards/{card['id']}", headers=headers).json()
    assert full["comment_count"] == 1
    assert full["checklist_total"] == 1
    assert full["checklist_done"] == 1
    assert len(full["comments"]) == 1
    assert full["checklists"][0]["items"][0]["done"] is True


def test_reorder_lists(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    add_user(session_factory, email="ordem@example.com", role="admin")
    headers = _headers(client, "ordem@example.com")
    board = client.get("/api/task-boards", headers=headers).json()[0]
    detail = client.get(f"/api/task-boards/{board['id']}", headers=headers).json()
    lists = detail["lists"]
    reversed_items = [
        {"id": lists[2]["id"], "position": 0},
        {"id": lists[1]["id"], "position": 1},
        {"id": lists[0]["id"], "position": 2},
    ]
    reordered = client.post(
        "/api/task-boards/lists/reorder",
        headers=headers,
        json={"items": reversed_items},
    )
    assert reordered.status_code == 200
    assert [item["id"] for item in reordered.json()] == [
        lists[2]["id"],
        lists[1]["id"],
        lists[0]["id"],
    ]
