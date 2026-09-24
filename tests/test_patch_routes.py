# ruff: noqa: F401, F811
"""PATCH de cada recurso editável grava a mudança e preserva o resto.

O PATCH de bots dava 500 ao salvar settings e nenhum teste o chamava; o
mesmo valia para campanhas, despesas e nichos.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from core.bot_settings import BotSettings
from tests.test_api import client, session_factory
from tests.test_bots_api import admin_context, create_bot, safe_settings


def test_patch_de_bot_grava_settings_inteiro_e_preserva_o_resto(
    client: object, session_factory: sessionmaker[Session]
) -> None:
    _admin, headers, catalog = admin_context(client, session_factory)
    bot = create_bot(client, headers, name="Bot Casa", slug="bot-casa", catalog=catalog)

    novo = safe_settings(max_ofertas_por_hora=3)
    response = client.patch(f"/api/bots/{bot['id']}", headers=headers, json={"settings": novo})
    assert response.status_code == 200, response.text
    esperado = BotSettings.model_validate(novo).model_dump(mode="json")
    assert response.json()["settings"] == esperado
    assert response.json()["name"] == "Bot Casa"

    response = client.patch(f"/api/bots/{bot['id']}", headers=headers, json={"name": "Bot Cozinha"})
    assert response.status_code == 200, response.text
    lido = client.get(f"/api/bots/{bot['id']}", headers=headers).json()
    assert lido["name"] == "Bot Cozinha"
    assert lido["settings"] == esperado
    assert lido["phone_id"] == str(catalog["phone_id"])

    response = client.patch(f"/api/bots/{bot['id']}", headers=headers, json={"settings": None})
    assert response.status_code == 422, response.text


def test_patch_de_campanha_despesa_e_nicho(
    client: object, session_factory: sessionmaker[Session]
) -> None:
    _admin, headers, _catalog = admin_context(client, session_factory)

    niche = client.post("/api/niches", headers=headers, json={"slug": "pets", "name": "Pets"})
    assert niche.status_code == 201, niche.text
    response = client.patch(
        f"/api/niches/{niche.json()['id']}", headers=headers, json={"name": "Pet shop"}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {**niche.json(), "name": "Pet shop"}

    campaign = client.post(
        "/api/campaigns", headers=headers, json={"name": "Meta setembro", "channel": "meta"}
    )
    assert campaign.status_code == 201, campaign.text
    response = client.patch(
        f"/api/campaigns/{campaign.json()['id']}",
        headers=headers,
        json={"status": "paused", "started_at": "2026-09-01"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "paused"
    assert response.json()["started_at"] == "2026-09-01"
    assert response.json()["channel"] == "meta"

    expense = client.post(
        "/api/expenses",
        headers=headers,
        json={"description": "Anúncio", "amount": "10.50", "incurred_on": "2026-09-10"},
    )
    assert expense.status_code == 201, expense.text
    response = client.patch(
        f"/api/expenses/{expense.json()['id']}",
        headers=headers,
        json={"amount": "12.30", "campaign_id": campaign.json()["id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["amount"] == "12.30"
    assert response.json()["campaign_id"] == campaign.json()["id"]
    assert response.json()["description"] == "Anúncio"


def test_rotas_de_escrita_sem_cobertura_respondem_sem_500(
    client: object, session_factory: sessionmaker[Session], monkeypatch: object
) -> None:
    # Fluxo que o dashboard percorre; antes, nenhum teste chamava estas rotas.
    _admin, headers, catalog = admin_context(client, session_factory)
    phone_id = str(catalog["phone_id"])

    phone = client.patch(f"/api/phones/{phone_id}", headers=headers, json={"label": "Chip teste"})
    assert phone.status_code == 200, phone.text
    assert phone.json()["label"] == "Chip teste"

    group = client.post(
        "/api/groups",
        headers=headers,
        json={"phone_id": phone_id, "whatsapp_id": "120363000000000001@g.us", "name": "Dev"},
    )
    assert group.status_code == 201, group.text

    bot = create_bot(
        client, headers, name="Bot Dev", slug="bot-dev", catalog=catalog,
        group_ids=[group.json()["id"]], account_ids=[catalog["account_ids"][0]],
    )
    for acao, status in (("activate", "active"), ("pause", "paused"), ("disable", "disabled")):
        response = client.post(f"/api/bots/{bot['id']}/{acao}", headers=headers)
        assert response.status_code == 200, (acao, response.text)
        assert response.json()["status"] == status
    assert client.delete(f"/api/bots/{bot['id']}", headers=headers).status_code == 204

    category = client.post(
        "/api/expense-categories", headers=headers, json={"slug": "anuncios", "name": "Anúncios"}
    )
    assert category.status_code == 201, category.text
    csv = (
        "descricao;valor;data;categoria;external_id\n"
        f"Meta;15.90;2026-09-10;{category.json()['id']};ext-1\n"
    ).encode()
    for esperado in ({"imported": 1, "skipped": 0}, {"imported": 0, "skipped": 1}):
        response = client.post(
            "/api/expenses/import", headers=headers, files={"file": ("gastos.csv", csv, "text/csv")}
        )
        assert response.status_code == 200, response.text
        assert {k: response.json()[k] for k in esperado} == esperado

    expenses = client.get("/api/expenses", headers=headers).json()["items"]
    assert client.delete(f"/api/expenses/{expenses[0]['id']}", headers=headers).status_code == 204
    campaign = client.post("/api/campaigns", headers=headers, json={"name": "Apagar"})
    assert client.delete(f"/api/campaigns/{campaign.json()['id']}", headers=headers).status_code == 204
    niche = client.post("/api/niches", headers=headers, json={"slug": "apagar", "name": "Apagar"})
    assert client.delete(f"/api/niches/{niche.json()['id']}", headers=headers).status_code == 204

    monkeypatch.setenv("WORKER_TOKEN", "segredo-de-teste")
    beat = {"worker_id": "w1", "bots_running": []}
    assert client.post("/api/internal/heartbeat", json=beat).status_code == 401
    response = client.post(
        "/api/internal/heartbeat", json=beat, headers={"X-Worker-Token": "segredo-de-teste"}
    )
    assert response.status_code == 204, response.text
