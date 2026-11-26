# ruff: noqa: F401, F811
"""Allowlist de origem do espelho editável na plataforma."""

from __future__ import annotations

from api.ratelimit import limiter
from api.security import create_access_token
from core.mirror_sources import (
    MAX_PLATFORM_SOURCE_GROUPS,
    invalidate_platform_source_cache,
)
from tests.test_api import add_user, auth_header, client, session_factory


def test_platform_admin_define_ate_tres_origens(client, session_factory):
    limiter.clear()
    invalidate_platform_source_cache()
    admin = add_user(session_factory, email="mirror-allow@teste.com", role="admin")
    headers = auth_header(
        create_access_token(str(admin.id), session_version=admin.session_version)
    )
    listed = client.get("/api/platform/mirror/source-groups", headers=headers)
    assert listed.status_code == 200
    body = listed.json()
    assert body["max_selected"] == MAX_PLATFORM_SOURCE_GROUPS
    assert "MELHORES OFERTAS" in body["candidates"]
    assert len(body["selected"]) >= 1

    nomes = ["MELHORES OFERTAS", "Ofertas da Gio #147", "PROMO CASINHA #6"]
    saved = client.put(
        "/api/platform/mirror/source-groups",
        headers=headers,
        json={"names": nomes},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["selected"] == nomes
    assert saved.json()["source"] == "database"

    again = client.get("/api/platform/mirror/source-groups", headers=headers)
    assert again.json()["selected"] == nomes

    too_many = client.put(
        "/api/platform/mirror/source-groups",
        headers=headers,
        json={"names": [*nomes, "Economizei 430"]},
    )
    assert too_many.status_code == 422

    reset = client.put(
        "/api/platform/mirror/source-groups",
        headers=headers,
        json={"names": [], "reset_to_default": True},
    )
    assert reset.status_code == 200
    assert reset.json()["source"] in {"default", "env"}
    invalidate_platform_source_cache()


def test_cliente_nao_acessa_origens_do_espelho(client, session_factory):
    limiter.clear()
    user = add_user(
        session_factory,
        email="cliente-mirror@teste.com",
        role="admin",
        is_platform_admin=False,
    )
    headers = auth_header(
        create_access_token(str(user.id), session_version=user.session_version)
    )
    assert client.get("/api/platform/mirror/source-groups", headers=headers).status_code == 403
