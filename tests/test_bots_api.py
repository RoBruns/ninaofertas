# ruff: noqa: E402, F401, F811

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.bot_settings import BotSettings
from core.models import (
    AuditLog,
    Bot,
    Command,
    Group,
    Niche,
    Phone,
    Platform,
    PlatformAccount,
    PlatformCredential,
)
from tests.test_api import (
    add_user,
    assert_error,
    auth_header,
    client,
    login,
    session_factory,
)

ROOT = Path(__file__).resolve().parents[1]


def safe_settings(**pacing_overrides: int) -> dict[str, object]:
    pacing = {
        "max_ofertas_por_ciclo": 1,
        "intervalo_minutos_entre_ofertas": 5,
        "max_ofertas_por_rajada": 3,
        "janela_rajada_minutos": 15,
        "pausa_entre_rajadas_minutos": 35,
        "max_ofertas_por_hora": 6,
        "max_ofertas_por_dia": 80,
        "max_ofertas_globais_por_hora": 8,
        "max_ofertas_globais_por_dia": 90,
    }
    pacing.update(pacing_overrides)
    return {
        "schema_version": 1,
        "filters": {"preco_minimo": 25, "desconto_minimo": 20},
        "pacing": pacing,
        "content": {"aceitar_cupons": True, "max_cupons_por_dia": 2},
        "schedule": {
            "check_interval": 60,
            "quiet_hours": {"start": "23:00", "end": "07:00"},
        },
    }


def add_catalog(
    factory: sessionmaker[Session], owner_id: object
) -> dict[str, object]:
    phone_id = uuid4()
    group_ids = [uuid4(), uuid4()]
    account_ids = [uuid4(), uuid4()]
    with factory.begin() as session:
        niche = Niche(owner_id=owner_id, slug="casa", name="Casa")
        session.add(niche)
        # platforms.slug é UNIQUE global (não por owner): um teste que chama
        # add_catalog duas vezes precisa reaproveitar a linha existente.
        platform = session.scalars(
            select(Platform).where(Platform.slug == "mercadolivre")
        ).first()
        if platform is None:
            platform = Platform(
                slug="mercadolivre",
                name="Mercado Livre",
                is_active=True,
                capabilities={"offers": True},
            )
            session.add(platform)
        session.flush()
        session.add(
            Phone(
                id=phone_id,
                owner_id=owner_id,
                label="WhatsApp principal",
                number="5511999990000",
                evolution_instance="nina-principal",
                status="unknown",
            )
        )
        # groups.phone_id tem FK para phones: sem este flush o SQLAlchemy pode
        # ordenar o INSERT dos grupos antes do telefone e violar a constraint.
        session.flush()
        session.add_all(
            [
                Group(
                    id=group_id,
                    owner_id=owner_id,
                    phone_id=phone_id,
                    whatsapp_id=f"grupo-{index}@g.us",
                    name=f"Grupo {index}",
                    participants=100,
                    is_announce=False,
                    bot_is_admin=True,
                    status="active",
                )
                for index, group_id in enumerate(group_ids, start=1)
            ]
        )
        session.add_all(
            [
                PlatformAccount(
                    id=account_id,
                    owner_id=owner_id,
                    platform_id=platform.id,
                    label=f"Conta {index}",
                    status="active",
                    config={},
                )
                for index, account_id in enumerate(account_ids, start=1)
            ]
        )
        session.flush()
        # Bot só ativa com conta que tenha credencial (ADR-020); o conteúdo
        # cifrado não importa para a API, que nunca o lê de volta.
        session.add_all(
            PlatformCredential(account_id=account_id, kind="cookie", ciphertext=b"x")
            for account_id in account_ids
        )
        niche_id = niche.id
    return {
        "niche_id": niche_id,
        "phone_id": phone_id,
        "group_ids": group_ids,
        "account_ids": account_ids,
    }


def create_bot(
    test_client: object,
    headers: dict[str, str],
    *,
    name: str,
    slug: str,
    catalog: dict[str, object] | None = None,
    group_ids: list[object] | None = None,
    account_ids: list[object] | None = None,
    settings: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "slug": slug,
        "settings": settings or safe_settings(),
        "group_ids": [str(item) for item in (group_ids or [])],
        "account_ids": [str(item) for item in (account_ids or [])],
    }
    if catalog is not None:
        payload.update(
            niche_id=catalog["niche_id"],
            phone_id=str(catalog["phone_id"]),
            message_template="Oferta: {nome} - {url}",
        )
    response = test_client.post("/api/bots", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def admin_context(
    test_client: object, factory: sessionmaker[Session]
) -> tuple[object, dict[str, str], dict[str, object]]:
    admin = add_user(factory, email="admin@example.com", role="admin")
    token = str(login(test_client, admin.email)["access_token"])
    return admin, auth_header(token), add_catalog(factory, admin.id)


def test_cria_bot_completo_e_duplica_todos_os_vinculos(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    _admin, headers, catalog = admin_context(client, session_factory)
    source = create_bot(
        client,
        headers,
        name="Bot Casa",
        slug="bot-casa",
        catalog=catalog,
        group_ids=list(catalog["group_ids"]),
        account_ids=list(catalog["account_ids"]),
    )

    assert source["niche_id"] == catalog["niche_id"]
    assert source["phone_id"] == str(catalog["phone_id"])
    assert set(source["group_ids"]) == {str(item) for item in catalog["group_ids"]}
    assert set(source["account_ids"]) == {str(item) for item in catalog["account_ids"]}
    expected_settings = BotSettings.model_validate(safe_settings()).model_dump(mode="json")
    assert source["settings"] == expected_settings
    assert source["status"] == "paused"

    first = client.post(f"/api/bots/{source['id']}/duplicate", headers=headers)
    second = client.post(f"/api/bots/{source['id']}/duplicate", headers=headers)
    assert first.status_code == second.status_code == 201
    copies = [first.json(), second.json()]
    assert {copy["slug"] for copy in copies} == {"bot-casa-2", "bot-casa-3"}
    for copy in copies:
        assert copy["status"] == "paused"
        assert copy["settings"] == source["settings"]
        assert copy["group_ids"] == source["group_ids"]
        assert copy["account_ids"] == source["account_ids"]


def test_status_auditoria_run_now_e_health_desconhecida(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    _admin, headers, catalog = admin_context(client, session_factory)
    bot = create_bot(
        client,
        headers,
        name="Bot Operacional",
        slug="operacional",
        catalog=catalog,
        group_ids=[catalog["group_ids"][0]],
        account_ids=[catalog["account_ids"][0]],
    )

    for endpoint, expected in (
        ("activate", "active"),
        ("pause", "paused"),
        ("disable", "disabled"),
    ):
        response = client.post(f"/api/bots/{bot['id']}/{endpoint}", headers=headers)
        assert response.status_code == 200
        assert response.json()["status"] == expected

    queued = client.post(f"/api/bots/{bot['id']}/run-now", headers=headers)
    assert queued.status_code == 202
    health = client.get(f"/api/bots/{bot['id']}/health", headers=headers)
    assert health.status_code == 200
    assert health.json()["status"] == "unknown"
    assert health.json()["last_run_at"] is None

    with session_factory() as session:
        actions = set(
            session.scalars(
                select(AuditLog.action).where(AuditLog.entity_id == str(bot["id"]))
            )
        )
        command = session.get(Command, queued.json()["command_id"])
        assert command is not None
        assert (command.type, command.status, str(command.bot_id)) == (
            "run_now",
            "pending",
            bot["id"],
        )
    assert {"activate", "pause", "disable"} <= actions


def test_ativacao_exige_telefone_grupo_e_conta_e_preserva_bot_ativo(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    _admin, headers, catalog = admin_context(client, session_factory)
    bot = create_bot(client, headers, name="Bot Protegido", slug="protegido")
    without_phone = client.post(f"/api/bots/{bot['id']}/activate", headers=headers)
    assert_error(without_phone, 409, "CONFLICT")
    assert without_phone.json()["error"]["message"] == (
        "Para ativar o bot, falta: um telefone, ao menos um grupo, "
        "ao menos uma conta de plataforma com credencial"
    )

    linked_phone = client.patch(
        f"/api/bots/{bot['id']}",
        headers=headers,
        json={"phone_id": str(catalog["phone_id"])},
    )
    assert linked_phone.status_code == 200
    without_group = client.patch(
        f"/api/bots/{bot['id']}", headers=headers, json={"status": "active"}
    )
    assert_error(without_group, 409, "CONFLICT")

    linked_group = client.put(
        f"/api/bots/{bot['id']}/groups",
        headers=headers,
        json={"group_ids": [str(catalog["group_ids"][0])]},
    )
    assert linked_group.status_code == 200
    without_account = client.post(f"/api/bots/{bot['id']}/activate", headers=headers)
    assert_error(without_account, 409, "CONFLICT")
    assert without_account.json()["error"]["message"] == (
        "Para ativar o bot, falta: ao menos uma conta de plataforma com credencial"
    )

    linked_account = client.put(
        f"/api/bots/{bot['id']}/accounts",
        headers=headers,
        json={"account_ids": [str(catalog["account_ids"][0])]},
    )
    assert linked_account.status_code == 200
    activated = client.post(f"/api/bots/{bot['id']}/activate", headers=headers)
    assert activated.status_code == 200, activated.text

    remove_phone = client.patch(
        f"/api/bots/{bot['id']}", headers=headers, json={"phone_id": None}
    )
    remove_group = client.put(
        f"/api/bots/{bot['id']}/groups", headers=headers, json={"group_ids": []}
    )
    remove_accounts = client.put(
        f"/api/bots/{bot['id']}/accounts", headers=headers, json={"account_ids": []}
    )
    assert_error(remove_phone, 409, "CONFLICT")
    assert_error(remove_group, 409, "CONFLICT")
    assert_error(remove_accounts, 409, "CONFLICT")
    current = client.get(f"/api/bots/{bot['id']}", headers=headers)
    assert current.json()["status"] == "active"
    assert current.json()["phone_id"] == str(catalog["phone_id"])
    assert current.json()["group_ids"] == [str(catalog["group_ids"][0])]


def test_put_groups_e_accounts_substitui_os_vinculos(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    _admin, headers, catalog = admin_context(client, session_factory)
    groups = list(catalog["group_ids"])
    accounts = list(catalog["account_ids"])
    bot = create_bot(
        client,
        headers,
        name="Bot Vinculos",
        slug="vinculos",
        group_ids=[groups[0]],
        account_ids=[accounts[0]],
    )

    changed_groups = client.put(
        f"/api/bots/{bot['id']}/groups",
        headers=headers,
        json={"group_ids": [str(groups[1])]},
    )
    changed_accounts = client.put(
        f"/api/bots/{bot['id']}/accounts",
        headers=headers,
        json={"account_ids": [str(accounts[1])]},
    )
    assert changed_groups.status_code == changed_accounts.status_code == 200
    assert changed_groups.json()["group_ids"] == [str(groups[1])]
    assert changed_accounts.json()["account_ids"] == [str(accounts[1])]


def test_viewer_nao_cria_bot(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    viewer = add_user(session_factory, email="viewer@example.com", role="viewer")
    headers = auth_header(str(login(client, viewer.email)["access_token"]))
    response = client.post(
        "/api/bots",
        headers=headers,
        json={"name": "Negado", "slug": "negado", "settings": safe_settings()},
    )
    assert_error(response, 403, "FORBIDDEN")


@pytest.mark.parametrize(
    ("field", "limit", "unsafe"),
    [
        ("max_ofertas_por_hora", 15, 16),
        ("max_ofertas_por_dia", 120, 121),
        ("max_ofertas_globais_por_hora", 20, 21),
        ("max_ofertas_globais_por_dia", 150, 151),
        ("max_ofertas_por_ciclo", 3, 4),
        ("max_ofertas_por_rajada", 5, 6),
        ("intervalo_minutos_entre_ofertas", 2, 1),
    ],
)
def test_guarda_anti_ban_aceita_limite_e_recusa_um_passo_alem(
    client: object,
    session_factory: sessionmaker[Session],
    field: str,
    limit: int,
    unsafe: int,
) -> None:
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    headers = auth_header(str(login(client, admin.email)["access_token"]))

    accepted = client.post(
        "/api/bots",
        headers=headers,
        json={
            "name": f"Seguro {field}",
            "slug": "seguro",
            "settings": safe_settings(**{field: limit}),
        },
    )
    rejected = client.post(
        "/api/bots",
        headers=headers,
        json={
            "name": f"Perigoso {field}",
            "slug": "perigoso",
            "settings": safe_settings(**{field: unsafe}),
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert_error(rejected, 422, "VALIDATION_ERROR")
    message = rejected.json()["error"]["message"].casefold()
    assert "banimento" in message
    assert "chip" in message


@pytest.mark.parametrize("filename", ["config.json", "config.auto.json"])
def test_round_trip_dos_arquivos_reais_preserva_as_30_chaves(filename: str) -> None:
    source = json.loads((ROOT / filename).read_text(encoding="utf-8"))
    dumped = BotSettings.model_validate(source).model_dump(mode="json")
    flattened: dict[str, object] = {}
    for key, value in dumped.items():
        if key in {"filters", "pacing", "content", "schedule"}:
            flattened.update(value)
        elif key != "schema_version":
            flattened[key] = value

    assert len(source) == 30
    assert set(flattened) == set(source)
    assert flattened == source


def test_ml_tag_invalida_retorna_422_com_regra_clara(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    admin = add_user(session_factory, email="ml-tag@example.com", role="admin")
    headers = auth_header(str(login(client, admin.email)["access_token"]))
    bot_settings = safe_settings()
    bot_settings["attribution"] = {"ml_tag": "Tag com espaços"}

    response = client.post(
        "/api/bots",
        headers=headers,
        json={"name": "Tag invalida", "slug": "tag-invalida", "settings": bot_settings},
    )

    assert_error(response, 422, "VALIDATION_ERROR")
    serialized = json.dumps(response.json(), ensure_ascii=False)
    assert "3 a 40" in serialized
    assert "letras minusculas" in serialized


class OfflineHTTPClient:
    calls = 0

    def __init__(self, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> OfflineHTTPClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, url: str, **_kwargs: object) -> httpx.Response:
        type(self).calls += 1
        raise httpx.ConnectError("evolution offline", request=httpx.Request("GET", url))


def test_telefone_normaliza_duplica_sync_assincrono_e_tolera_evolution_offline(
    client: object,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = add_user(session_factory, email="admin@example.com", role="admin")
    headers = auth_header(str(login(client, admin.email)["access_token"]))
    monkeypatch.setattr("core.evolution.httpx.Client", OfflineHTTPClient)
    OfflineHTTPClient.calls = 0

    created = client.post(
        "/api/phones",
        headers=headers,
        json={
            "label": "Comercial",
            "number": "+55 (11) 99999-1234",
            "evolution_instance": "comercial",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["number"] == "5511999991234"
    duplicate = client.post(
        "/api/phones",
        headers=headers,
        json={"label": "Repetido", "number": "0055 11 99999-1234"},
    )
    assert_error(duplicate, 409, "CONFLICT")

    calls_before_sync = OfflineHTTPClient.calls
    queued = client.post(
        f"/api/phones/{created.json()['id']}/sync-groups", headers=headers
    )
    assert queued.status_code == 202
    assert OfflineHTTPClient.calls == calls_before_sync
    with session_factory() as session:
        command = session.get(Command, queued.json()["command_id"])
        assert command is not None
        assert command.type == "sync_groups"
        assert command.status == "pending"
        assert command.payload == {"phone_id": created.json()["id"]}

    listing = client.get("/api/phones", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["items"][0]["status"] == "unknown"
    assert OfflineHTTPClient.calls > calls_before_sync


def test_mesmo_telefone_pode_ser_usado_por_dois_bots(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    _admin, headers, catalog = admin_context(client, session_factory)
    first = create_bot(client, headers, name="Bot Um", slug="bot-um", catalog=catalog)
    second = create_bot(client, headers, name="Bot Dois", slug="bot-dois", catalog=catalog)
    assert first["phone_id"] == second["phone_id"] == str(catalog["phone_id"])


def test_warning_de_grupo_e_exclusoes_em_uso_nomeiam_bots(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    _admin, headers, catalog = admin_context(client, session_factory)
    group_id = list(catalog["group_ids"])[0]
    bot = create_bot(
        client,
        headers,
        name="Bot Protegido",
        slug="protegido",
        catalog=catalog,
        group_ids=[group_id],
    )
    updated = client.patch(
        f"/api/groups/{group_id}",
        headers=headers,
        json={"is_announce": True, "bot_is_admin": False},
    )
    assert updated.status_code == 200
    assert updated.json()["warning"]

    group_delete = client.delete(f"/api/groups/{group_id}", headers=headers)
    phone_delete = client.delete(
        f"/api/phones/{catalog['phone_id']}", headers=headers
    )
    assert_error(group_delete, 409, "CONFLICT")
    assert_error(phone_delete, 409, "CONFLICT")
    assert bot["name"] in group_delete.text
    assert bot["name"] in phone_delete.text
