# ruff: noqa: E402, F401, F811

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core import db
from core.bot_settings import BotSettings
from core.config_provider import usar_bot_runtime
from core.importers.shopee import parse_attribution_sub_ids, parse_conversion_report
from core.models import (
    Bot,
    Envio,
    Event,
    Group,
    Oferta,
    Platform,
    PlatformAccount,
    Sale,
)
from core.platforms import affiliate
from core.platforms.base import OfertaCapturada
from core.sales_sync import _upsert
from tests.test_api import add_user, auth_header, client, login, session_factory
from tests.test_bots_api import safe_settings
from worker import monitor


def _runtime(bot_id: UUID | None = None, ml_tag: str | None = None):
    settings = safe_settings()
    settings["attribution"] = {"ml_tag": ml_tag}
    return SimpleNamespace(
        id=bot_id or uuid4(),
        account_ids=(uuid4(),),
        settings=BotSettings.model_validate(settings),
    )


class AffiliateHTTPClient:
    calls: list[tuple[str, dict[str, object]]] = []
    responses: list[tuple[int, dict[str, object]]] = []

    def __init__(self, **_kwargs: object) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        type(self).calls.append(("GET", {"url": url, **kwargs}))
        return httpx.Response(200, request=httpx.Request("GET", url))

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        type(self).calls.append(("POST", {"url": url, **kwargs}))
        status, payload = type(self).responses.pop(0)
        return httpx.Response(status, json=payload, request=httpx.Request("POST", url))


def test_modo_legado_preserva_links_e_nao_encurta_offerlink_shopee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    AffiliateHTTPClient.calls = []
    AffiliateHTTPClient.responses = [(200, {"urls": [{"short_url": "https://meli.la/hoje"}]})]
    monkeypatch.setattr(affiliate.httpx, "Client", AffiliateHTTPClient)
    monkeypatch.setattr(affiliate, "_runtime_auth", lambda _slug: (None, None))
    monkeypatch.setattr(affiliate.settings, "mercadolivre_affiliate_tag", "tag-hoje")
    monkeypatch.setattr(affiliate.settings, "mercadolivre_affiliate_cookie", "cookie=hoje")

    shopee_today = "https://s.shopee.com.br/offer-link-atual"
    assert affiliate.garantir_afiliado("Shopee", shopee_today) == shopee_today
    assert AffiliateHTTPClient.calls == []

    ml = affiliate.garantir_afiliado("Mercado Livre", "https://produto.example/ml")
    assert ml == "https://meli.la/hoje"
    post = next(call for method, call in AffiliateHTTPClient.calls if method == "POST")
    assert post["json"] == {"urls": ["https://produto.example/ml"], "tag": "tag-hoje"}


def test_links_por_bot_usam_tag_ml_e_subids_shopee(monkeypatch: pytest.MonkeyPatch) -> None:
    bot_id = UUID("1a2b3c4d-0000-4000-8000-000000000001")
    group_id = UUID("5d6e7f80-0000-4000-8000-000000000002")
    runtime = _runtime(bot_id, "tag_bot")
    ml_account = (runtime.account_ids[0], {"affiliate_tag": "tag_conta"}, {"cookie": "x=1"})
    shopee_account = (
        runtime.account_ids[0],
        {"app_id": "app"},
        {"app_secret": "secret"},
    )
    AffiliateHTTPClient.calls = []
    AffiliateHTTPClient.responses = [
        (200, {"urls": [{"short_url": "https://meli.la/bot"}]}),
        (200, {"data": {"generateShortLink": {"shortLink": "https://s.shopee.com.br/bot"}}}),
    ]
    monkeypatch.setattr(affiliate.httpx, "Client", AffiliateHTTPClient)
    monkeypatch.setattr(
        affiliate,
        "_runtime_auth",
        lambda slug: (runtime, ml_account if slug == "mercadolivre" else shopee_account),
    )

    with usar_bot_runtime(runtime):
        ml = affiliate.garantir_afiliado("Mercado Livre", "https://produto.example/ml")
        shopee = affiliate.garantir_afiliado(
            "Shopee",
            "https://s.shopee.com.br/offer-atual",
            group_id=group_id,
            origin_url="https://shopee.com.br/produto-original",
        )

    assert ml.sub_id == "ml:tag_bot"
    assert shopee.sub_id == "shopee:b1a2b3c4d-g5d6e7f80"
    ml_post = [call for method, call in AffiliateHTTPClient.calls if method == "POST"][0]
    assert ml_post["json"]["tag"] == "tag_bot"
    shopee_payload = json.loads(
        [call for method, call in AffiliateHTTPClient.calls if method == "POST"][1]["content"]
    )
    assert 'originUrl: "https://shopee.com.br/produto-original"' in shopee_payload["query"]
    assert 'subIds: ["b1a2b3c4d", "g5d6e7f80"]' in shopee_payload["query"]


def test_ml_sem_tag_do_bot_usa_tag_da_conta(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(ml_tag=None)
    account = (runtime.account_ids[0], {"affiliate_tag": "tag_conta"}, {"cookie": "x=1"})
    AffiliateHTTPClient.calls = []
    AffiliateHTTPClient.responses = [
        (200, {"urls": [{"short_url": "https://meli.la/conta"}]})
    ]
    monkeypatch.setattr(affiliate.httpx, "Client", AffiliateHTTPClient)
    monkeypatch.setattr(affiliate, "_runtime_auth", lambda _slug: (runtime, account))

    with usar_bot_runtime(runtime):
        link = affiliate.garantir_afiliado("Mercado Livre", "https://produto.example/ml")

    assert link.sub_id == "ml:tag_conta"
    post = next(call for method, call in AffiliateHTTPClient.calls if method == "POST")
    assert post["json"]["tag"] == "tag_conta"


def test_falha_shopee_mantem_offerlink_emite_evento_e_envio_continua(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(UUID("1a2b3c4d-0000-4000-8000-000000000001"))
    group_id = UUID("5d6e7f80-0000-4000-8000-000000000002")
    account = (runtime.account_ids[0], {"app_id": "app"}, {"app_secret": "secret"})
    events: list[str] = []
    AffiliateHTTPClient.calls = []
    AffiliateHTTPClient.responses = [(200, {"errors": [{"message": "indisponivel"}]})]
    monkeypatch.setattr(affiliate.httpx, "Client", AffiliateHTTPClient)
    monkeypatch.setattr(affiliate, "_runtime_auth", lambda _slug: (runtime, account))
    monkeypatch.setattr(
        affiliate,
        "registrar_evento_runtime",
        lambda event_type, *_args, **_kwargs: events.append(event_type),
    )

    offer_link = "https://s.shopee.com.br/offer-atual"
    with usar_bot_runtime(runtime):
        fallback = affiliate.garantir_afiliado(
            "Shopee", offer_link, group_id=group_id, origin_url="https://shopee.com.br/p"
        )
    assert fallback == offer_link
    assert fallback.sub_id == "shopee:b1a2b3c4d-g5d6e7f80"
    assert events == ["attribution_link_failed"]

    sent: list[str] = []
    stored: list[dict[str, object]] = []
    monkeypatch.setattr(monitor, "passa_nos_filtros", lambda *_args: (True, ""))
    monkeypatch.setattr(monitor, "_salvar_oferta", lambda *_args: SimpleNamespace(id=1))
    monkeypatch.setattr(monitor.dedup, "deve_enviar", lambda *_args, **_kwargs: (True, "nova"))
    monkeypatch.setattr(monitor, "_freio_anti_ban", lambda *_args: (True, ""))
    monkeypatch.setattr(monitor, "grupo_whatsapp", lambda: "grupo@g.us")
    monkeypatch.setattr(monitor, "grupo_db_id", lambda: group_id)
    monkeypatch.setattr(monitor, "bot_atual", lambda: runtime)
    monkeypatch.setattr(monitor.affiliate, "garantir_afiliado", lambda *_args, **_kwargs: fallback)
    monkeypatch.setattr(monitor.formatter, "montar_mensagem", lambda item: item.url)
    monkeypatch.setattr(
        monitor.whatsapp,
        "enviar_mensagem",
        lambda message, **_kwargs: sent.append(message) or True,
    )
    monkeypatch.setattr(
        monitor.repositories,
        "registrar_envio",
        lambda *_args, **kwargs: stored.append(kwargs),
    )
    result = monitor._processar_oferta(
        object(),
        OfertaCapturada(nome="Oferta", preco=10, loja="Shopee", url=offer_link),
        {},
    )
    assert result == "enviou"
    assert sent == [offer_link]
    assert stored[0]["sub_id"] == "shopee:b1a2b3c4d-g5d6e7f80"


def test_parser_utm_content_isolado() -> None:
    assert parse_attribution_sub_ids("b1A2b3C4d-g5D6e7F80") == ("1a2b3c4d", "5d6e7f80")
    assert parse_attribution_sub_ids("campanha-b1a2b3c4d-g5d6e7f80-extra") == (
        "1a2b3c4d",
        "5d6e7f80",
    )
    assert parse_attribution_sub_ids("sem-atribuicao") == (None, None)


def _patch_sessions(monkeypatch: pytest.MonkeyPatch, factory: sessionmaker[Session]) -> None:
    @contextmanager
    def get_test_session():
        with factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    monkeypatch.setattr(db, "get_session", get_test_session)


def test_shopee_importada_resolve_ids_e_aparece_em_metricas_por_bot(
    monkeypatch: pytest.MonkeyPatch,
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    owner = add_user(session_factory, email="attribution@example.com", role="admin")
    bot_id = UUID("1a2b3c4d-0000-4000-8000-000000000001")
    group_id = UUID("5d6e7f80-0000-4000-8000-000000000002")
    account_id = uuid4()
    _patch_sessions(monkeypatch, session_factory)
    with session_factory.begin() as session:
        Oferta.__table__.create(session.connection(), checkfirst=True)
        Envio.__table__.create(session.connection(), checkfirst=True)
        platform = Platform(slug="shopee", name="Shopee", is_active=True, capabilities={})
        session.add(platform)
        session.flush()
        session.add_all(
            [
                Bot(
                    id=bot_id,
                    owner_id=owner.id,
                    name="Bot Atribuido",
                    slug="atribuido",
                    status="active",
                    settings={},
                ),
                Group(
                    id=group_id,
                    owner_id=owner.id,
                    whatsapp_id="grupo@g.us",
                    name="Grupo Atribuido",
                    status="active",
                ),
                PlatformAccount(
                    id=account_id,
                    owner_id=owner.id,
                    platform_id=platform.id,
                    label="Shopee",
                    status="active",
                    config={},
                ),
            ]
        )
        session.flush()
        offer = Oferta(nome="Oferta", preco=100, url="https://example.test/oferta")
        session.add(offer)
        session.flush()
        session.add(
            Envio(
                oferta_id=offer.id,
                grupo="grupo@g.us",
                mensagem="m",
                status="sucesso",
                bot_id=bot_id,
                group_id=group_id,
                sub_id="shopee:b1a2b3c4d-g5d6e7f80",
            )
        )

    report = {
        "nodes": [
            {
                "conversionId": "conv-1",
                "purchaseTime": int(datetime(2026, 9, 24, 12, tzinfo=timezone.utc).timestamp()),
                "utmContent": "b1a2b3c4d-g5d6e7f80",
                "orders": [
                    {
                        "orderId": "pedido-1",
                        "orderStatus": "COMPLETED",
                        "items": [
                            {
                                "itemName": "Produto",
                                "itemPrice": "100.00",
                                "qty": 1,
                                "itemTotalCommission": "12.34",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    rows = parse_conversion_report(report)
    result = _upsert(account_id, rows, "api")
    assert result.imported == 1
    with session_factory() as session:
        sale = session.scalar(select(Sale))
        assert sale.bot_id == bot_id
        assert sale.group_id == group_id

    with session_factory.begin() as session:
        sale = session.scalar(select(Sale))
        sale.bot_id = None
        sale.group_id = None
    reimported = _upsert(account_id, rows, "api")
    assert reimported.imported == 1
    with session_factory() as session:
        sale = session.scalar(select(Sale))
        assert sale.bot_id == bot_id
        assert sale.group_id == group_id

    headers = auth_header(str(login(client, owner.email)["access_token"]))
    response = client.get(
        "/api/metrics/by-bot",
        headers=headers,
        params={"from": "2026-09-24", "to": "2026-09-24"},
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["id"] == str(bot_id)
    assert item["commission"] == "12.34"


def test_prefixo_ambiguo_deixa_bot_null_e_grava_evento(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    owner = add_user(session_factory, email="ambiguous@example.com", role="admin")
    account_id = uuid4()
    _patch_sessions(monkeypatch, session_factory)
    with session_factory.begin() as session:
        platform = Platform(slug="shopee", name="Shopee", is_active=True, capabilities={})
        session.add(platform)
        session.flush()
        session.add_all(
            [
                Bot(
                    id=UUID("aaaaaaaa-0000-4000-8000-000000000001"),
                    owner_id=owner.id,
                    name="A1",
                    slug="a1",
                    status="active",
                    settings={},
                ),
                Bot(
                    id=UUID("aaaaaaaa-0000-4000-8000-000000000002"),
                    owner_id=owner.id,
                    name="A2",
                    slug="a2",
                    status="active",
                    settings={},
                ),
                PlatformAccount(
                    id=account_id,
                    owner_id=owner.id,
                    platform_id=platform.id,
                    label="Shopee",
                    status="active",
                    config={},
                ),
            ]
        )
    report = {
        "nodes": [
            {
                "purchaseTime": 1_790_000_000,
                "utmContent": "baaaaaaaa",
                "orders": [
                    {
                        "orderId": "ambiguous-1",
                        "orderStatus": "COMPLETED",
                        "items": [],
                    }
                ],
            }
        ]
    }
    rows = parse_conversion_report(report)
    _upsert(account_id, rows, "api")
    _upsert(account_id, rows, "api")
    with session_factory() as session:
        assert session.scalar(select(Sale.bot_id)) is None
        events = list(
            session.scalars(select(Event).where(Event.type == "attribution_resolution_failed"))
        )
        assert len(events) == 1
        event = events[0]
        assert event.detail["failures"]["bot"] == "ambiguous"
