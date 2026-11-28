"""Espelho WhatsApp: parser, matching, captura de plataforma e fan-out."""

from __future__ import annotations

import base64
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from core.bot_settings import BotSettings, Mirror
from core.link_parser import detectar_loja, extrair_links_oferta, loja_para_platform_slug, substituir_urls
from core.mirror_match import nome_na_allowlist
from core.mirror_sources import (
    allowlist_para_bot,
    invalidate_platform_source_cache,
    platform_source_group_names,
    pular_pending_fora_da_allowlist,
    salvar_platform_source_group_names,
)
from core.models import Bot, Group, MirrorCapture, MirrorInbox, Phone, Tenant
from core.platforms.base import OfertaCapturada
from tests.test_api import add_user
from core.mirror_media import (
    ProdutoSomenteVideo,
    base64_puro,
    escolher_imagem_galeria,
    imagem_do_link_produto,
    mensagem_tem_imagem,
    midia_do_payload_webhook,
    resolver_imagem_espelho,
)
from worker import formatter
from worker.whatsapp import _media_payload
from worker.filters import (
    extrair_cupom_mensagem,
    extrair_precos_mensagem,
    mensagem_eh_cupom_espelho,
    pagina_de_cupom,
    passa_filtros_espelho,
    titulo_bate_com_pagina,
    titulo_confirmado,
    titulo_de_vitrine,
    titulo_mensagem_espelho,
)
from worker.mirror import (
    _item_com_cupom,
    _lote_pendentes,
    _oferta_template,
    corte_fila_do_dia,
    expirar_cupons_velhos,
    expirar_pendentes,
)


def test_detectar_loja_por_host():
    assert detectar_loja("https://shopee.com.br/product/1/2") == "shopee"
    assert detectar_loja("https://meli.la/xyz") == "mercado livre"
    assert detectar_loja("https://www.amazon.com.br/dp/B0") == "amazon"
    assert loja_para_platform_slug("mercado livre") == "mercadolivre"
    assert loja_para_platform_slug("amazon") == "amazon"


def test_extrair_e_substituir_links():
    texto = "Olha: https://shopee.com.br/a/b e https://meli.la/zz fim."
    links = extrair_links_oferta(texto)
    assert [link.loja for link in links] == ["shopee", "mercado livre"]
    novo = substituir_urls(
        texto,
        {
            "https://shopee.com.br/a/b": "https://s.shopee.com.br/aff",
            "https://meli.la/zz": "https://meli.la/nina",
        },
    )
    assert "https://s.shopee.com.br/aff" in novo


def test_allowlist_plataforma_e_subset():
    invalidate_platform_source_cache()
    assert "MELHORES OFERTAS" in platform_source_group_names()
    assert nome_na_allowlist("🔥 Melhores Ofertas", platform_source_group_names())
    subset = allowlist_para_bot(["MELHORES OFERTAS", "Grupo Inventado"])
    assert subset == ["MELHORES OFERTAS"]
    assert allowlist_para_bot([]) == platform_source_group_names()


def test_salvar_allowlist_plataforma_e_pula_pending(session_factory) -> None:
    invalidate_platform_source_cache()
    admin = add_user(session_factory, email="mirror-src@nina.test", role="admin")
    with session_factory.begin() as session:
        phone = Phone(
            id=uuid4(),
            owner_id=admin.tenant_id,
            label="Nina 1",
            number="5511999000666",
            evolution_instance="nina-1-src",
            is_platform_listen=True,
        )
        session.add(phone)
        session.flush()
        bot = Bot(
            id=uuid4(),
            owner_id=admin.tenant_id,
            name="Bot src",
            slug="bot-src-allow",
            status="active",
            phone_id=phone.id,
            settings={},
        )
        session.add(bot)
        session.flush()
        session.add(
            MirrorInbox(
                owner_id=admin.tenant_id,
                bot_id=bot.id,
                listen_phone_id=phone.id,
                source_whatsapp_id="g-a@g.us",
                source_group_name="MELHORES OFERTAS",
                message_key="keep",
                body_text="ok",
                status="pending",
            )
        )
        session.add(
            MirrorInbox(
                owner_id=admin.tenant_id,
                bot_id=bot.id,
                listen_phone_id=phone.id,
                source_whatsapp_id="g-b@g.us",
                source_group_name="Achadinhos & Ofertas",
                message_key="drop",
                body_text="fora",
                status="pending",
            )
        )
        chosen = salvar_platform_source_group_names(session, ["MELHORES OFERTAS", "Ofertas da Gio #147"])
        assert chosen == ["MELHORES OFERTAS", "Ofertas da Gio #147"]
        skipped = pular_pending_fora_da_allowlist(session, chosen)
        assert skipped == 1
        assert platform_source_group_names(session) == chosen
    invalidate_platform_source_cache()


def test_passa_filtros_espelho_nicho_sem_preco():
    filtros = {"palavras_chave": ["panela", "cozinha"], "preco_minimo": 50}
    ok, _ = passa_filtros_espelho(
        OfertaCapturada(nome="Panela antiaderente 24cm", preco=0.0, loja="shopee", url="https://shopee.com.br/a"),
        filtros,
    )
    assert ok
    bad, motivo = passa_filtros_espelho(
        OfertaCapturada(nome="Pneu aro 15 esportivo", preco=0.0, loja="shopee", url="https://shopee.com.br/a"),
        filtros,
    )
    assert not bad
    assert "nicho" in motivo


def test_titulo_ignora_faixa_e_usa_o_nome_do_item():
    texto = (
        "COZINHA MAIS PRÁTICA 💎\n\n"
        "Micro-ondas Electrolux Efficient 34L Branco ME34B\n\n"
        "De: 759 | Por: R$485 💵\n"
        "Use o cupom: TECHHOME\n\n"
        "Pegar promoção ➡️ https://meli.la/2Vs7mtF\n"
    )
    assert titulo_mensagem_espelho(texto).startswith("Micro-ondas Electrolux")
    assert not titulo_bate_com_pagina(
        "COZINHA MAIS PRÁTICA",
        "Micro-ondas Electrolux Efficient 34L Branco",
    )
    assert titulo_bate_com_pagina(
        "Micro-ondas Electrolux Efficient 34L",
        "Micro-ondas Electrolux Efficient 34L | Mercado Livre",
    )


def test_vitrine_da_shopee_nao_substitui_o_nome():
    pagina = "Direto do estoque da Shopee | Shopee 2026"
    assert titulo_de_vitrine(pagina)
    assert not titulo_de_vitrine("Gocase Tote Mini")
    assert titulo_confirmado("Gocase Tote Mini", pagina) == "Gocase Tote Mini"
    assert titulo_confirmado(
        "Direto do estoque da Shopee",
        "Gocase Tote Mini | Shopee",
    ) == "Gocase Tote Mini"
    texto = (
        "Direto do estoque da Shopee\n"
        "Gocase Tote Mini\n"
        "https://shopee.com.br/product/1/2\n"
    )
    assert titulo_mensagem_espelho(texto) == "Gocase Tote Mini"


def test_titulo_produto_nao_troca_por_outro_da_pagina():
    """Caption e og:title de itens diferentes: fica o caption (foto costuma bater)."""
    assert (
        titulo_confirmado("Saco de lixo 100L com 50 unidades", "KIT PRINCIPIA Vitamina C")
        == "Saco de lixo 100L com 50 unidades"
    )
    # Anúncio fraco (faixa) ainda cede para o nome real da página.
    assert titulo_confirmado("COZINHA MAIS PRÁTICA", "Panela antiaderente 24cm") == (
        "Panela antiaderente 24cm"
    )


def test_oferta_espelho_nao_corta_titulo_enfeitado(monkeypatch) -> None:
    monkeypatch.setattr(
        "worker.formatter.load_filtros",
        lambda: {"mensagem_template": "🚨 *{nome}*\n\n✅ {de_por}\n\n🛒 {url}"},
    )
    titulo = (
        "Espelho Retangular Grande com LED para Banheiro Quarto Camarim "
        "Closet Varios Acabamentos: Reflexos incríveis todos os dias! ✨🪞"
    )
    assert len(titulo) > 120
    oferta = _oferta_template(
        titulo=titulo,
        loja="shopee",
        url_afiliado="https://s.shopee.com.br/nina-aff",
        url_origem="https://s.shopee.com.br/AAJ0vaUiSy",
        body_text=f"{titulo}\nPor R$ 344,29\nhttps://s.shopee.com.br/AAJ0vaUiSy",
        sku="mirror:espelho",
        imagem=None,
    )
    assert oferta.nome == titulo
    assert "todos os dias" in oferta.nome
    mensagem = formatter.montar_mensagem(oferta)
    assert "todos os dias" in mensagem
    assert not mensagem.rstrip().endswith("todos os di")


def test_titulo_mensagem_espelho_ignora_url():
    texto = "https://shopee.com.br/x\nPanela boa demais\n"
    assert titulo_mensagem_espelho(texto) == "Panela boa demais"


@pytest.fixture()
def webhook_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("EVOLUTION_WEBHOOK_SECRET", "segredo-teste-espelho")
    return "segredo-teste-espelho"


def test_webhook_recusa_sem_token(client, webhook_secret: str) -> None:
    response = client.post("/api/webhooks/evolution", json={"event": "messages.upsert"})
    assert response.status_code == 401


def _seed_platform_listen(session: Session, *, instance: str = "nina1-listen") -> Phone:
    tenant = Tenant(id=uuid4(), name="Plataforma Nina", is_internal=True)
    session.add(tenant)
    session.flush()
    phone = Phone(
        id=uuid4(),
        owner_id=tenant.id,
        label="Nina 1",
        number="5511888000001",
        evolution_instance=instance,
        is_platform_listen=True,
    )
    session.add(phone)
    session.flush()
    session.add(
        Group(
            id=uuid4(),
            owner_id=tenant.id,
            phone_id=phone.id,
            name="MELHORES OFERTAS",
            whatsapp_id="120363origem@g.us",
        )
    )
    return phone


def test_webhook_fanout_dois_tenants(
    client,
    session_factory: sessionmaker[Session],
    webhook_secret: str,
) -> None:
    admin_a = add_user(session_factory, email="mirror-a@nina.test", role="admin")
    admin_b = add_user(session_factory, email="mirror-b@nina.test", role="admin")
    send_a = uuid4()
    send_b = uuid4()
    bot_a = uuid4()
    bot_b = uuid4()
    with session_factory.begin() as session:
        listen = _seed_platform_listen(session)
        listen_id = listen.id
        session.add_all(
            [
                Phone(
                    id=send_a,
                    owner_id=admin_a.tenant_id,
                    label="Nina 2 A",
                    number="5511999000001",
                    evolution_instance="nina2-a",
                ),
                Phone(
                    id=send_b,
                    owner_id=admin_b.tenant_id,
                    label="Nina 2 B",
                    number="5511999000002",
                    evolution_instance="nina2-b",
                ),
            ]
        )
        session.add(
            Bot(
                id=bot_a,
                owner_id=admin_a.tenant_id,
                name="Casa A",
                slug="casa-a-mirror",
                status="active",
                phone_id=send_a,
                settings=BotSettings(mirror=Mirror(enabled=True)).model_dump(mode="json"),
            )
        )
        session.add(
            Bot(
                id=bot_b,
                owner_id=admin_b.tenant_id,
                name="Casa B",
                slug="casa-b-mirror",
                status="active",
                phone_id=send_b,
                settings=BotSettings(mirror=Mirror(enabled=True)).model_dump(mode="json"),
            )
        )

    response = client.post(
        f"/api/webhooks/evolution?token={webhook_secret}",
        json={
            "event": "messages.upsert",
            "instance": "nina1-listen",
            "data": {
                "key": {
                    "remoteJid": "120363origem@g.us",
                    "fromMe": False,
                    "id": "MSG-MULTI",
                },
                "message": {
                    "conversation": "Panela https://shopee.com.br/product/1/2",
                },
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accepted"] == 2
    assert body["captures"] == 1

    with session_factory() as session:
        assert session.query(MirrorCapture).count() == 1
        items = session.query(MirrorInbox).all()
        assert {str(i.bot_id) for i in items} == {str(bot_a), str(bot_b)}
        assert all(i.listen_phone_id == listen_id for i in items)
        assert all(i.status == "pending" for i in items)


def test_webhook_registra_cupom_com_a_loja_da_mensagem(
    client,
    session_factory: sessionmaker[Session],
    webhook_secret: str,
) -> None:
    from core.models import CouponRadar

    admin = add_user(session_factory, email="mirror-cupom@nina.test", role="admin")
    send = uuid4()
    with session_factory.begin() as session:
        _seed_platform_listen(session)
        session.add(
            Phone(
                id=send,
                owner_id=admin.tenant_id,
                label="Nina 2",
                number="5511999000077",
                evolution_instance="nina2-cupom",
            )
        )
        session.flush()
        session.add(
            Bot(
                id=uuid4(),
                owner_id=admin.tenant_id,
                name="Casa cupom",
                slug="casa-cupom",
                status="active",
                phone_id=send,
                settings=BotSettings(mirror=Mirror(enabled=True)).model_dump(mode="json"),
            )
        )

    texto = (
        "CORRE novo cupom Mercado Livre!\n"
        "Use o cupom MELI40 acima de R$ 199\n"
        "https://www.mercadolivre.com.br/cupons"
    )
    response = client.post(
        f"/api/webhooks/evolution?token={webhook_secret}",
        json={
            "event": "messages.upsert",
            "instance": "nina1-listen",
            "data": {
                "key": {"remoteJid": "120363origem@g.us", "fromMe": False, "id": "MSG-CUPOM"},
                "message": {"conversation": texto},
            },
        },
    )
    assert response.status_code == 200, response.text
    with session_factory() as session:
        cupom = session.query(CouponRadar).filter_by(code="MELI40").one()
        assert cupom.store == "mercadolivre"
        assert cupom.url == "https://www.mercadolivre.com.br/cupons"
        assert cupom.title and "MELI40" in cupom.title
        assert cupom.source_group_name == "MELHORES OFERTAS"


def test_webhook_guarda_miniatura_da_previa_do_link(
    client,
    session_factory: sessionmaker[Session],
    webhook_secret: str,
) -> None:
    admin = add_user(session_factory, email="mirror-previa@nina.test", role="admin")
    send = uuid4()
    bot_id = uuid4()
    with session_factory.begin() as session:
        _seed_platform_listen(session)
        session.add(
            Phone(
                id=send,
                owner_id=admin.tenant_id,
                label="Nina 2",
                number="5511999000099",
                evolution_instance="nina2-previa",
            )
        )
        session.add(
            Bot(
                id=bot_id,
                owner_id=admin.tenant_id,
                name="Casa prévia",
                slug="casa-previa",
                status="active",
                phone_id=send,
                settings=BotSettings(mirror=Mirror(enabled=True)).model_dump(mode="json"),
            )
        )

    thumb = {"type": "Buffer", "data": [255, 216, 255, 224] + [7] * 40}
    response = client.post(
        f"/api/webhooks/evolution?token={webhook_secret}",
        json={
            "event": "messages.upsert",
            "instance": "nina1-listen",
            "data": {
                "key": {
                    "remoteJid": "120363origem@g.us",
                    "fromMe": False,
                    "id": "MSG-PREVIA",
                },
                "message": {
                    "extendedTextMessage": {
                        "text": "Fogão https://s.shopee.com.br/AKcPabeH50",
                        "jpegThumbnail": thumb,
                    }
                },
            },
        },
    )
    assert response.status_code == 200, response.text
    esperado = base64.b64encode(bytes([255, 216, 255, 224] + [7] * 40)).decode("ascii")
    with session_factory() as session:
        captura = session.query(MirrorCapture).one()
        assert captura.has_media is True
        assert captura.media_path == esperado
        item = session.query(MirrorInbox).one()
        assert item.has_media is True
        assert item.media_path == esperado


def test_webhook_ignora_phone_sem_flag_plataforma(
    client,
    session_factory: sessionmaker[Session],
    webhook_secret: str,
) -> None:
    admin = add_user(session_factory, email="mirror-nofalg@nina.test", role="admin")
    with session_factory.begin() as session:
        session.add(
            Phone(
                id=uuid4(),
                owner_id=admin.tenant_id,
                label="Comum",
                number="5511999000099",
                evolution_instance="phone-comum",
                is_platform_listen=False,
            )
        )
        session.add(
            Bot(
                id=uuid4(),
                owner_id=admin.tenant_id,
                name="Bot",
                slug="bot-no-flag",
                status="active",
                settings=BotSettings(mirror=Mirror(enabled=True)).model_dump(mode="json"),
            )
        )

    response = client.post(
        f"/api/webhooks/evolution?token={webhook_secret}",
        json={
            "event": "messages.upsert",
            "instance": "phone-comum",
            "data": {
                "key": {"remoteJid": "120363x@g.us", "fromMe": False, "id": "1"},
                "message": {"conversation": "https://shopee.com.br/a/b"},
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["ignored"] == "not_platform_listen"


def test_sync_chumba_escuta_pelo_rotulo_nina1(session_factory: sessionmaker[Session]) -> None:
    from core.mirror_webhook import sync_platform_listen_flags

    admin = add_user(session_factory, email="mirror-sync@nina.test", role="admin")
    nina_id = uuid4()
    outro_id = uuid4()
    with session_factory.begin() as session:
        session.add(
            Phone(
                id=outro_id,
                owner_id=admin.tenant_id,
                label="Nina 2",
                number="5511999000088",
                evolution_instance="nina2-sync",
                is_platform_listen=True,  # flag errada: sync deve limpar
            )
        )
        session.add(
            Phone(
                id=nina_id,
                owner_id=admin.tenant_id,
                label="Nina 1",
                number="5511999000087",
                evolution_instance="nina1-sync",
                is_platform_listen=False,  # sync deve ligar pelo rótulo
            )
        )

    with session_factory.begin() as session:
        chosen = sync_platform_listen_flags(session)
        assert chosen is not None
        assert chosen.id == nina_id
        nina = session.get(Phone, nina_id)
        outro = session.get(Phone, outro_id)
        assert nina is not None and nina.is_platform_listen is True
        assert outro is not None and outro.is_platform_listen is False


def test_webhook_aceita_nina1_mesmo_sem_flag_previa(
    client,
    session_factory: sessionmaker[Session],
    webhook_secret: str,
) -> None:
    """Deploy antigo: Nina 1 sem flag ainda captura após sync pelo rótulo."""
    admin = add_user(session_factory, email="mirror-label@nina.test", role="admin")
    send_id = uuid4()
    with session_factory.begin() as session:
        listen = Phone(
            id=uuid4(),
            owner_id=admin.tenant_id,
            label="Nina 1",
            number="5511888000099",
            evolution_instance="nina1-label-only",
            is_platform_listen=False,
        )
        session.add(listen)
        session.add(
            Group(
                id=uuid4(),
                owner_id=admin.tenant_id,
                phone_id=listen.id,
                name="MELHORES OFERTAS",
                whatsapp_id="120363label@g.us",
            )
        )
        session.add(
            Phone(
                id=send_id,
                owner_id=admin.tenant_id,
                label="Nina 2",
                number="5511999000077",
                evolution_instance="send-label",
            )
        )
        session.add(
            Bot(
                id=uuid4(),
                owner_id=admin.tenant_id,
                name="Bot",
                slug="bot-label-listen",
                status="active",
                phone_id=send_id,
                settings=BotSettings(mirror=Mirror(enabled=True)).model_dump(mode="json"),
            )
        )

    response = client.post(
        f"/api/webhooks/evolution?token={webhook_secret}",
        json={
            "event": "messages.upsert",
            "instance": "nina1-label-only",
            "data": {
                "key": {
                    "remoteJid": "120363label@g.us",
                    "fromMe": False,
                    "id": "MSG-LABEL",
                },
                "pushName": "x",
                "message": {"conversation": "https://shopee.com.br/a/b oferta"},
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("ignored") != "not_platform_listen"
    assert body.get("accepted", 0) >= 1


def test_webhook_ignora_grupo_fora_da_allowlist(
    client,
    session_factory: sessionmaker[Session],
    webhook_secret: str,
) -> None:
    admin = add_user(session_factory, email="mirror-out@nina.test", role="admin")
    with session_factory.begin() as session:
        listen = _seed_platform_listen(session, instance="nina1-out")
        session.add(
            Group(
                id=uuid4(),
                owner_id=listen.owner_id,
                phone_id=listen.id,
                name="Grupo Qualquer",
                whatsapp_id="120363outro@g.us",
            )
        )
        send = Phone(
            id=uuid4(),
            owner_id=admin.tenant_id,
            label="Send",
            number="5511999000012",
            evolution_instance="send-out",
        )
        session.add(send)
        session.add(
            Bot(
                id=uuid4(),
                owner_id=admin.tenant_id,
                name="Bot",
                slug="bot-mirror-ignore",
                status="active",
                phone_id=send.id,
                settings=BotSettings(mirror=Mirror(enabled=True)).model_dump(mode="json"),
            )
        )

    response = client.post(
        f"/api/webhooks/evolution?token={webhook_secret}",
        json={
            "event": "messages.upsert",
            "instance": "nina1-out",
            "data": {
                "key": {
                    "remoteJid": "120363outro@g.us",
                    "fromMe": False,
                    "id": "MSG002",
                },
                "message": {"conversation": "https://shopee.com.br/a/b"},
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["accepted"] == 0


def test_extrair_precos_e_cupom_da_mensagem() -> None:
    texto = "De R$ 189,90 por R$ 129,90\nCupom: NINA10\nhttps://meli.la/x"
    preco, anterior = extrair_precos_mensagem(texto)
    assert preco == 129.9
    assert anterior == 189.9
    assert extrair_cupom_mensagem(texto) == "NINA10"


def test_extrair_cupom_formatos_da_origem() -> None:
    from worker.filters import mensagem_menciona_cupom

    assert extrair_cupom_mensagem("Cupom Shopee: CASA20\nhttps://s.shopee.com.br/a") == "CASA20"
    assert extrair_cupom_mensagem("Use o cupom 👇\nTECHVIP\nhttps://meli.la/a") == "TECHVIP"
    assert extrair_cupom_mensagem("De R$ 379 por R$ 179,50\n+ cupom *SUPER50*\nhttps://meli.la/b") == (
        "SUPER50"
    )
    assert extrair_cupom_mensagem("🎟️ MEGA50\nhttps://meli.la/c") == "MEGA50"
    assert extrair_cupom_mensagem("use cupom NINA-10\nhttps://meli.la/d") == "NINA10"
    assert extrair_cupom_mensagem("tem cupom liberado\nhttps://meli.la/e") is None
    assert mensagem_menciona_cupom("Por R$ 179,50 + cupom\nhttps://meli.la/f")
    assert not mensagem_menciona_cupom("Por R$ 179,50\nhttps://meli.la/g")


def test_modelos_reais_origem_preco_cupom_e_mensagem(monkeypatch) -> None:
    """Três formatos dos grupos de origem: preço + cupom na mensagem do espelho."""
    monkeypatch.setattr(
        "worker.formatter.load_filtros",
        lambda: {"mensagem_template": formatter.TEMPLATE_PADRAO},
    )
    loe = (
        "➡️ Jogo De Panelas Induçao Antiaderente Cerâmica 10 Peças Ppg Pfoa Free Grafite\n\n"
        "de: R$\u00a0683,00 por: R$\u00a0248,31 NO PIX com cupom\n"
        "🎟️ Use o cupom: L40FH139H90\n\n"
        "🛒 Compre aqui: https://meli.la/16HXAS4\n\n"
        "Os valores que postamos no grupo já são calculados com o cupom. "
        "Não se esqueçam de aplicar o cupom L40FH139H90 para chegar ao valor informado!\n"
    )
    gio = (
        "💥 Kit Jantar Colonial Clássico 6 cadeiras todo mel. Luxo e tradição! 🍽️🐝\n\n"
        "De: R$\u00a01.979,49 ❌\n"
        "💸 Por: R$\u00a01.389,60 🔥\n\n"
        "🎟️ Use o cupom: LIVREOFF\n\n"
        "🛒 Compre aqui: https://meli.la/1MExKjj\n\n"
        "😍 Ei, chame uma amiga pra participar do grupo da Gio: "
        "https://chat.whatsapp.com/GafsQMhlWUt4cXjJC0ScvK\n\n"
        "⚠️ Promoção sujeita a alteração a qualquer momento.\n"
    )
    tenis = (
        "SUPER CONFORTÁVEL  🤩\n\n"
        "Tênis adidas Acelera 2 Corrida Masculino\n\n"
        "Por apenas: R$208 no pix 💵\n"
        "Use o cupom: GARANTAJAHJ\n\n"
        "Pegar promoção ➡️https://meli.la/1W83Mmg\n"
    )
    casos = [
        (loe, 248.31, 683.0, "L40FH139H90"),
        (gio, 1389.60, 1979.49, "LIVREOFF"),
        (tenis, 208.0, None, "GARANTAJAHJ"),
    ]
    for texto, preco_ok, anterior_ok, cupom_ok in casos:
        preco, anterior = extrair_precos_mensagem(texto)
        assert preco == preco_ok, texto[:40]
        assert anterior == anterior_ok, texto[:40]
        assert extrair_cupom_mensagem(texto) == cupom_ok, texto[:40]
        oferta = _oferta_template(
            titulo=titulo_mensagem_espelho(texto),
            loja="Mercado Livre",
            url_afiliado="https://meli.la/aff",
            url_origem="https://meli.la/orig",
            body_text=texto,
            sku="t",
            imagem=None,
        )
        assert oferta.codigo_cupom == cupom_ok
        assert oferta.preco == preco_ok
        msg = formatter.montar_mensagem(oferta)
        assert cupom_ok in msg
        assert "meli.la/aff" in msg


def test_formatter_legado_e_mencao_repassam_cupom(monkeypatch) -> None:
    """Template antigo sem {cupom} e menção sem código ainda avisam o público."""
    from core.platforms.base import OfertaCapturada

    monkeypatch.setattr(
        "worker.formatter.load_filtros",
        lambda: {
            "mensagem_template": (
                "🔥 {nome}\n💰 De: R$ {preco_anterior}\nPor: R$ {preco}\n👉 {url}"
            )
        },
    )
    com_codigo = OfertaCapturada(
        nome="Árvore",
        preco=179.5,
        preco_anterior=379.0,
        url="https://meli.la/x",
        loja="Mercado Livre",
        categoria="espelho",
        codigo_cupom="NATAL10",
    )
    msg = formatter.montar_mensagem(com_codigo)
    assert "NATAL10" in msg
    assert "meli.la/x" in msg

    so_mencao = OfertaCapturada(
        nome="Árvore",
        preco=179.5,
        preco_anterior=379.0,
        url="https://meli.la/y",
        loja="Mercado Livre",
        categoria="espelho",
        beneficio="cupom_origem",
    )
    msg2 = formatter.montar_mensagem(so_mencao)
    assert "cupom" in msg2.lower()
    assert "meli.la/y" in msg2


def test_espelho_ignora_banner_desconto_e_le_de_sem_rs() -> None:
    """'R$1.000 DE DESCONTO' não é título nem preço; 'De: 2.309 | Por: R$1.017' vale."""
    texto = (
        "R$1.000 DE DESCONTO 🚨🏃‍♀️\n\n"
        "Fogão 4 Bocas Dako Magíster Style com Mesa de Vidro Preto/Espelhado\n\n"
        "De: 2.309 | Por: R$1.017 💵\n"
        "🎟️ Use o cupom: TECHVIP\n\n"
        "Pegar promoção ➡️ https://meli.la/1wrrkWG\n"
    )
    assert "Fogão 4 Bocas Dako" in titulo_mensagem_espelho(texto)
    assert "DESCONTO" not in titulo_mensagem_espelho(texto).upper()
    preco, anterior = extrair_precos_mensagem(texto)
    assert preco == 1017.0
    assert anterior == 2309.0
    assert extrair_cupom_mensagem(texto) == "TECHVIP"


def test_parse_mensagem_origem_com_ruido_e_cupom() -> None:
    """Origem típica: título + De/Por + PIX + compra + convite WhatsApp + aviso."""
    texto = (
        "💥 Kit 2 Mesas Laterais Douradas Tripé: elegância instantânea! ✨🏠\n\n"
        "De: R$\u00a0278,52 ❌\n"
        "💸 Por: R$\u00a0169,90 🔥\n\n"
        "⚠️ Pagamentos no pix tem + desconto\n\n"
        "🛒 Compre aqui: https://s.shopee.com.br/AUvpav5jpq\n\n"
        "Use o cupom: MESA10\n\n"
        "❤️Ei, Convide uma amiga para participar do grupo da Gio: "
        "https://chat.whatsapp.com/HH88hAlfNK86CUxd08GdYn\n\n"
        "⚠️ Promoção sujeita a alteração a qualquer momento.\n"
    )
    assert "Kit 2 Mesas Laterais Douradas" in titulo_mensagem_espelho(texto)
    preco, anterior = extrair_precos_mensagem(texto)
    assert preco == 169.9
    assert anterior == 278.52
    assert extrair_cupom_mensagem(texto) == "MESA10"
    links = extrair_links_oferta(texto)
    assert len(links) == 1
    assert links[0].loja == "shopee"
    assert "chat.whatsapp.com" not in links[0].url


def test_oferta_espelho_ignora_convite_e_repassa_cupom(monkeypatch) -> None:
    monkeypatch.setattr(
        "worker.formatter.load_filtros",
        lambda: {
            "mensagem_template": (
                "◼️ *{nome}*\n\n💰 {de_por}\n🎟️ Use o cupom: *{cupom}*\n\n🛒 {url}"
            ),
        },
    )
    body = (
        "Kit 2 Mesas\nDe: R$ 278,52\nPor: R$ 169,90\n"
        "Cupom: MESA10\nhttps://s.shopee.com.br/AUvpav5jpq\n"
        "https://chat.whatsapp.com/HH88hAlfNK86CUxd08GdYn"
    )
    oferta = _oferta_template(
        titulo=titulo_mensagem_espelho(body),
        loja="shopee",
        url_afiliado="https://s.shopee.com.br/nina-aff",
        url_origem="https://s.shopee.com.br/AUvpav5jpq",
        body_text=body,
        sku="mirror:2",
        imagem=None,
    )
    mensagem = formatter.montar_mensagem(oferta)
    assert "chat.whatsapp.com" not in mensagem
    assert "Convide" not in mensagem
    assert "sujeita a alteração" not in mensagem.lower()
    assert "MESA10" in mensagem
    assert "https://s.shopee.com.br/nina-aff" in mensagem
    assert "169,90" in mensagem or "169.90" in mensagem or "R$ 169" in mensagem


def test_oferta_espelho_usa_template_afiliado_sem_origem(monkeypatch) -> None:
    monkeypatch.setattr(
        "worker.formatter.load_filtros",
        lambda: {
            "mensagem_template": "◼️ *{nome}*\n\n💰 {de_por}\n\n🛒 {url}",
        },
    )
    oferta = _oferta_template(
        titulo="Jogo de cama",
        loja="mercado livre",
        url_afiliado="https://meli.la/nina-aff",
        url_origem="https://produto.mercadolivre.com.br/MLB-1",
        body_text="Jogo de cama\nDe R$ 200,00 por R$ 100,00\nhttps://produto.mercadolivre.com.br/MLB-1",
        sku="mirror:1",
        imagem=None,
    )
    mensagem = formatter.montar_mensagem(oferta)
    assert "Espelho ·" not in mensagem
    assert "PROMO CASINHA" not in mensagem
    assert "https://meli.la/nina-aff" in mensagem
    assert "Jogo de cama" in mensagem
    assert "R$ 100" in mensagem


def test_mensagem_eh_cupom_espelho_por_titulo_e_pagina() -> None:
    assert mensagem_eh_cupom_espelho(
        "🚨 Cupom de Desconto 2026: economia garantida hoje! 🎟️✨"
    )
    assert mensagem_eh_cupom_espelho("Cupons Diários Shopee")
    assert mensagem_eh_cupom_espelho(
        "Oferta da semana",
        pagina="Cupons Diários | Shopee",
    )
    assert pagina_de_cupom("Cupons Diários")
    # Produto real com código de cupom no texto não é cupom-como-oferta.
    assert not mensagem_eh_cupom_espelho("Kit 2 Mesas Laterais Douradas")
    assert titulo_confirmado(
        "Cupom de Desconto 2026",
        "Cupons Diários | Shopee",
    ) == "Cupom de Desconto 2026"


def test_oferta_espelho_cupom_envia_sem_de_por(monkeypatch) -> None:
    """Cupom da origem continua saindo; só some o De/Por ornamental."""
    monkeypatch.setattr(
        "worker.formatter.load_filtros",
        lambda: {
            "mensagem_template": (
                "🚨 *{nome}*\n\n✅ {de_por}\n\n🛒 {url}\n\n"
                "Siga a nossa página exclusiva de ofertas no instagram\n"
                "@ninamegaofertas"
            ),
        },
    )
    body = (
        "🚨 Cupom de Desconto 2026: economia garantida hoje! 🎟️✨\n\n"
        "✅ De R$ 1.403,37 por R$ 1169\n\n"
        "🛒 https://s.shopee.com.br/4qHUW0iHTO"
    )
    titulo = titulo_mensagem_espelho(body)
    oferta = _oferta_template(
        titulo=titulo,
        loja="shopee",
        url_afiliado="https://s.shopee.com.br/nina-cupom",
        url_origem="https://s.shopee.com.br/4qHUW0iHTO",
        body_text=body,
        sku="mirror:cupom",
        imagem="https://example.test/cupons.png",
        pagina="Cupons Diários",
    )
    assert oferta.preco == 0.0
    assert oferta.preco_anterior is None
    mensagem = formatter.montar_mensagem(oferta)
    assert "https://s.shopee.com.br/nina-cupom" in mensagem
    assert "Cupom de Desconto" in mensagem
    assert "1.403" not in mensagem
    assert "1169" not in mensagem
    assert "De " not in mensagem
    assert "@ninamegaofertas" in mensagem


def test_imagem_do_link_produto_usa_og_image(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        "<html><head>"
        '<meta property="og:image" content="https://down-br.img.susercontent.com/foto.jpg">'
        "</head></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://shopee.com.br/")
        assert request.headers["user-agent"].startswith("WhatsApp/")
        return httpx.Response(200, text=html)

    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    foto = imagem_do_link_produto("https://shopee.com.br/product/1/2", "shopee")
    assert foto == "https://down-br.img.susercontent.com/foto.jpg"


def _html_galeria(imagens: list[str], *, video: bool) -> str:
    lista = ",".join(f'"{item}"' for item in imagens)
    extra = '"video_info_list":[{"video_id":"abc"}],' if video else ""
    return f'<html><script>{{{extra}"images":[{lista}]}}</script></html>'


def test_shopee_sem_video_usa_a_primeira_foto(monkeypatch: pytest.MonkeyPatch) -> None:
    hashes = ["br-11134207-capa-foto-um", "br-11134207-foto-dois", "br-11134207-foto-tres"]
    html = _html_galeria(hashes, video=False)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    foto = imagem_do_link_produto("https://s.shopee.com.br/abc", "shopee")
    assert foto == "https://down-br.img.susercontent.com/file/br-11134207-capa-foto-um"


def test_shopee_com_video_usa_a_foto_seguinte(monkeypatch: pytest.MonkeyPatch) -> None:
    hashes = ["br-11134207-capa-video", "br-11134207-foto-dois", "br-11134207-foto-tres"]
    html = _html_galeria(hashes, video=True)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    foto = imagem_do_link_produto("https://s.shopee.com.br/abc", "shopee")
    assert foto == "https://down-br.img.susercontent.com/file/br-11134207-foto-dois"


def test_shopee_so_capa_de_video_nao_envia(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _html_galeria(["br-11134207-capa-video"], video=True)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(ProdutoSomenteVideo):
        imagem_do_link_produto("https://s.shopee.com.br/abc", "shopee")
    with pytest.raises(ProdutoSomenteVideo):
        resolver_imagem_espelho(
            listen_instance="nina1",
            message_key="120@g.us:MSG1",
            product_url="https://s.shopee.com.br/abc",
            loja="shopee",
            media_path="B" * 80,
        )


def test_carrossel_pula_videos_ate_a_primeira_foto() -> None:
    foto = escolher_imagem_galeria(
        [
            "https://down-br.img.susercontent.com/file/br-11134207-capa",
            "https://down-br.img.susercontent.com/file/segundo.mp4",
            "https://down-br.img.susercontent.com/file/br-11134207-foto-tres",
        ],
        tem_video=True,
    )
    assert foto == "https://down-br.img.susercontent.com/file/br-11134207-foto-tres"
    assert escolher_imagem_galeria(
        [
            "https://down-br.img.susercontent.com/file/capa.mp4",
            "https://down-br.img.susercontent.com/file/br-11134207-foto-dois",
        ],
        tem_video=False,
    ) == "https://down-br.img.susercontent.com/file/br-11134207-foto-dois"
    assert escolher_imagem_galeria(
        ["https://down-br.img.susercontent.com/file/so-video.mp4"],
        tem_video=True,
    ) is None


def test_midia_webhook_e_sendmedia_usam_base64_cru(monkeypatch: pytest.MonkeyPatch) -> None:
    assert mensagem_tem_imagem({"imageMessage": {"caption": "oi"}})
    assert mensagem_tem_imagem({"base64": "A" * 80})
    assert not mensagem_tem_imagem({"conversation": "só texto"})

    preview = midia_do_payload_webhook(
        {
            "extendedTextMessage": {
                "text": "Fogão https://s.shopee.com.br/AKcPabeH50",
                "jpegThumbnail": {"type": "Buffer", "data": [255, 216, 255, 224] + [1] * 40},
                "contextInfo": {
                    "quotedMessage": {
                        "imageMessage": {"jpegThumbnail": {"type": "Buffer", "data": [9] * 40}}
                    }
                },
            }
        }
    )
    assert preview and preview != base64.b64encode(bytes([9] * 40)).decode("ascii")

    url_preview = midia_do_payload_webhook(
        {
            "extendedTextMessage": {
                "text": "https://s.shopee.com.br/abc",
                "contextInfo": {
                    "externalAdReply": {
                        "thumbnailUrl": "https://down-br.img.susercontent.com/file/foto.jpg",
                        "sourceUrl": "https://s.shopee.com.br/abc",
                    }
                },
            }
        }
    )
    assert url_preview == "https://down-br.img.susercontent.com/file/foto.jpg"
    assert midia_do_payload_webhook({"conversation": "só o link https://s.shopee.com.br/abc"}) is None

    # Evolution com webhookBase64: base64 no envelope.
    env = midia_do_payload_webhook({"base64": "A" * 80, "imageMessage": {"caption": "x"}})
    assert env == "A" * 80

    # Thumbnail Buffer JSON (Node).
    thumb_buf = midia_do_payload_webhook(
        {
            "imageMessage": {
                "caption": "oi",
                "jpegThumbnail": {"type": "Buffer", "data": [255, 216, 255, 224] + [1] * 40},
            }
        }
    )
    assert thumb_buf and len(thumb_buf) >= 32

    data_url = "data:image/jpeg;base64," + ("C" * 80)
    assert base64_puro(data_url) == "C" * 80
    assert _media_payload(data_url) == "C" * 80

    monkeypatch.setattr(
        "core.mirror_media.midia_whatsapp_em_memoria",
        lambda instance, key: "B" * 80,
    )
    monkeypatch.setattr(
        "core.mirror_media.imagem_do_link_produto",
        lambda url, loja=None: None,
    )
    # Sem CDN: cai na mídia capturada no webhook (base64 cru).
    foto = resolver_imagem_espelho(
        listen_instance="nina1",
        message_key="120@g.us:MSG1",
        product_url="https://s.shopee.com.br/x",
        loja="shopee",
        media_path=env,
    )
    assert foto == env

    # Com CDN do produto: prioridade sobre a mídia do WhatsApp.
    monkeypatch.setattr(
        "core.mirror_media.imagem_do_link_produto",
        lambda url, loja=None: "https://down-br.img.susercontent.com/oficial.jpg",
    )
    foto_cdn = resolver_imagem_espelho(
        listen_instance="nina1",
        message_key="120@g.us:MSG1",
        product_url="https://s.shopee.com.br/x",
        loja="shopee",
        media_path=env,
    )
    assert foto_cdn == "https://down-br.img.susercontent.com/oficial.jpg"


def test_corte_da_fila_e_o_ultimo_2359() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    br = ZoneInfo("America/Sao_Paulo")
    assert corte_fila_do_dia(datetime(2026, 11, 24, 19, 26, tzinfo=br)) == datetime(
        2026, 11, 23, 23, 59, tzinfo=br
    )
    assert corte_fila_do_dia(datetime(2026, 11, 24, 23, 59, tzinfo=br)) == datetime(
        2026, 11, 24, 23, 59, tzinfo=br
    )
    assert corte_fila_do_dia(datetime(2026, 11, 25, 7, 0, tzinfo=br)) == datetime(
        2026, 11, 24, 23, 59, tzinfo=br
    )


def test_oferta_anterior_ao_2359_sai_da_fila(session_factory, monkeypatch) -> None:
    from contextlib import contextmanager
    from datetime import datetime
    from zoneinfo import ZoneInfo

    br = ZoneInfo("America/Sao_Paulo")
    admin = add_user(session_factory, email="fila-dia@nina.test", role="admin")
    with session_factory.begin() as session:
        phone = Phone(
            id=uuid4(),
            owner_id=admin.tenant_id,
            label="Nina 2 fila",
            number="5511999000777",
            evolution_instance="nina2-fila",
        )
        session.add(phone)
        session.flush()
        bot = Bot(
            id=uuid4(),
            owner_id=admin.tenant_id,
            name="Fila do dia",
            slug="fila-do-dia",
            status="active",
            phone_id=phone.id,
            settings={},
        )
        session.add(bot)
        session.flush()
        session.add_all(
            [
                MirrorInbox(
                    owner_id=admin.tenant_id,
                    bot_id=bot.id,
                    listen_phone_id=phone.id,
                    source_whatsapp_id="120363origem@g.us",
                    message_key="velha",
                    body_text="ontem",
                    status="pending",
                    created_at=datetime(2026, 11, 24, 18, 0, tzinfo=br),
                ),
                MirrorInbox(
                    owner_id=admin.tenant_id,
                    bot_id=bot.id,
                    listen_phone_id=phone.id,
                    source_whatsapp_id="120363origem@g.us",
                    message_key="noite",
                    body_text="madrugada",
                    status="pending",
                    created_at=datetime(2026, 11, 25, 0, 10, tzinfo=br),
                ),
                MirrorInbox(
                    owner_id=admin.tenant_id,
                    bot_id=bot.id,
                    listen_phone_id=phone.id,
                    source_whatsapp_id="120363origem@g.us",
                    message_key="enviada",
                    body_text="ja foi",
                    status="done",
                    created_at=datetime(2026, 11, 24, 12, 0, tzinfo=br),
                ),
            ]
        )

    @contextmanager
    def _sessao_do_teste():
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr("worker.mirror.db.get_session", _sessao_do_teste)
    assert expirar_pendentes(datetime(2026, 11, 25, 8, 0, tzinfo=br)) == 1
    with session_factory() as session:
        por_chave = {item.message_key: item for item in session.query(MirrorInbox).all()}
    assert por_chave["velha"].status == "skipped"
    assert por_chave["velha"].skip_reason == "passou_o_dia"
    assert por_chave["noite"].status == "pending"
    assert por_chave["enviada"].status == "done"


def test_lote_pendentes_prioriza_cupom_mesmo_mais_novo(session_factory) -> None:
    """Cupom digitável fura a fila FIFO — esgota se ficar parado."""
    from datetime import datetime, timedelta, timezone

    admin = add_user(session_factory, email="lote-cupom@nina.test", role="admin")
    with session_factory.begin() as session:
        phone = Phone(
            id=uuid4(),
            owner_id=admin.tenant_id,
            label="Nina cupom fila",
            number="5511999000777",
            evolution_instance="nina-cupom-fila",
        )
        session.add(phone)
        session.flush()
        bot = Bot(
            id=uuid4(),
            owner_id=admin.tenant_id,
            name="Bot cupom",
            slug="bot-cupom-fila",
            status="active",
            phone_id=phone.id,
            settings={},
        )
        session.add(bot)
        session.flush()
        agora = datetime.now(timezone.utc) - timedelta(hours=2)
        session.add(
            MirrorInbox(
                owner_id=admin.tenant_id,
                bot_id=bot.id,
                listen_phone_id=phone.id,
                source_whatsapp_id="120363origem@g.us",
                message_key="sem-cupom",
                body_text="Panela\nDe R$ 200 por R$ 100\nhttps://meli.la/a",
                status="pending",
                created_at=agora,
            )
        )
        session.add(
            MirrorInbox(
                owner_id=admin.tenant_id,
                bot_id=bot.id,
                listen_phone_id=phone.id,
                source_whatsapp_id="120363origem@g.us",
                message_key="com-cupom",
                body_text=(
                    "Conjunto de Panelas\nPor R$ 121\n"
                    "Use o cupom: SUPEROFERTA\nhttps://meli.la/b"
                ),
                status="pending",
                created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
            )
        )
        assert _item_com_cupom(
            MirrorInbox(body_text="Use o cupom: SUPEROFERTA\nhttps://x")
        )
        lote = _lote_pendentes(session)
        assert lote, "lote vazio"
        assert lote[0].message_key == "com-cupom"


def test_lote_cupom_mais_novo_primeiro_e_expira_com_mais_de_20_min(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dois cupons: o mais novo primeiro; >20 min → cupom_velho."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from core import db

    monkeypatch.setattr(db, "get_session", session_factory.begin)

    admin = add_user(session_factory, email="lote-fifo-cupom@nina.test", role="admin")
    with session_factory.begin() as session:
        phone = Phone(
            id=uuid4(),
            owner_id=admin.tenant_id,
            label="Nina fifo cupom",
            number="5511999000555",
            evolution_instance="nina-fifo-cupom",
        )
        session.add(phone)
        session.flush()
        bot_a = Bot(
            id=uuid4(),
            owner_id=admin.tenant_id,
            name="Bot A cupom",
            slug="bot-a-fifo-cupom",
            status="active",
            phone_id=phone.id,
            settings={},
        )
        bot_b = Bot(
            id=uuid4(),
            owner_id=admin.tenant_id,
            name="Bot B cupom",
            slug="bot-b-fifo-cupom",
            status="active",
            phone_id=phone.id,
            settings={},
        )
        session.add_all([bot_a, bot_b])
        session.flush()
        agora = datetime.now(timezone.utc) - timedelta(minutes=10)
        session.add(
            MirrorInbox(
                owner_id=admin.tenant_id,
                bot_id=bot_b.id,
                listen_phone_id=phone.id,
                source_whatsapp_id="g@g.us",
                message_key="cupom-novo",
                body_text="Use o cupom: NOVO10\nhttps://meli.la/n",
                status="pending",
                created_at=agora + timedelta(minutes=5),
            )
        )
        session.add(
            MirrorInbox(
                owner_id=admin.tenant_id,
                bot_id=bot_a.id,
                listen_phone_id=phone.id,
                source_whatsapp_id="g@g.us",
                message_key="cupom-antigo",
                body_text="Use o cupom: VELHO10\nhttps://meli.la/v",
                status="pending",
                created_at=agora,
            )
        )
        lote = _lote_pendentes(session)
        assert [i.message_key for i in lote[:2]] == ["cupom-novo", "cupom-antigo"]
        session.scalars(
            select(MirrorInbox).where(MirrorInbox.message_key == "cupom-antigo")
        ).one().created_at = datetime.now(timezone.utc) - timedelta(minutes=21)
    assert expirar_cupons_velhos() >= 1
    with session_factory() as session:
        item = session.scalars(
            select(MirrorInbox).where(MirrorInbox.message_key == "cupom-antigo")
        ).one()
        assert item.status == "skipped"
        assert item.skip_reason == "cupom_velho"


def test_cupom_novo_fura_fila_cheia_de_produto_antigo(session_factory) -> None:
    from datetime import datetime, timedelta, timezone

    admin = add_user(session_factory, email="fila-cheia-cupom@nina.test", role="admin")
    with session_factory.begin() as session:
        phone = Phone(
            id=uuid4(),
            owner_id=admin.tenant_id,
            label="Nina fila cheia",
            number="5511999000556",
            evolution_instance="nina-fila-cheia",
        )
        session.add(phone)
        session.flush()
        bot = Bot(
            id=uuid4(),
            owner_id=admin.tenant_id,
            name="Bot fila cheia",
            slug="bot-fila-cheia",
            status="active",
            phone_id=phone.id,
            settings={},
        )
        session.add(bot)
        session.flush()
        antes = datetime.now(timezone.utc) - timedelta(hours=3)
        session.add_all(
            [
                MirrorInbox(
                    owner_id=admin.tenant_id,
                    bot_id=bot.id,
                    listen_phone_id=phone.id,
                    source_whatsapp_id="g@g.us",
                    message_key=f"produto-{n}",
                    body_text=f"Panela {n}\nhttps://meli.la/p{n}",
                    status="pending",
                    created_at=antes + timedelta(seconds=n),
                )
                for n in range(200)
            ]
        )
        session.add(
            MirrorInbox(
                owner_id=admin.tenant_id,
                bot_id=bot.id,
                listen_phone_id=phone.id,
                source_whatsapp_id="g@g.us",
                message_key="cupom-agora",
                body_text="Use o cupom: AGORA20\nhttps://meli.la/c",
                status="pending",
                created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        session.flush()
        lote = _lote_pendentes(session)
        assert lote[0].message_key == "cupom-agora"


def test_produto_mais_novo_primeiro_e_velho_sai_da_fila(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timedelta, timezone

    from core import db
    from worker.mirror import expirar_produtos_velhos

    monkeypatch.setattr(db, "get_session", session_factory.begin)
    admin = add_user(session_factory, email="produto-novo@nina.test", role="admin")
    agora = datetime.now(timezone.utc)
    with session_factory.begin() as session:
        phone = Phone(
            id=uuid4(),
            owner_id=admin.tenant_id,
            label="Nina produto novo",
            number="5511999000557",
            evolution_instance="nina-produto-novo",
        )
        session.add(phone)
        session.flush()
        bot = Bot(
            id=uuid4(),
            owner_id=admin.tenant_id,
            name="Bot produto novo",
            slug="bot-produto-novo",
            status="active",
            phone_id=phone.id,
            settings={},
        )
        session.add(bot)
        session.flush()
        for chave, idade in (("velho", 150), ("meia-hora", 30), ("agora", 1)):
            session.add(
                MirrorInbox(
                    owner_id=admin.tenant_id,
                    bot_id=bot.id,
                    listen_phone_id=phone.id,
                    source_whatsapp_id="g@g.us",
                    message_key=chave,
                    body_text=f"Panela {chave}\nhttps://meli.la/{chave}",
                    status="pending",
                    created_at=agora - timedelta(minutes=idade),
                )
            )
        session.flush()
        assert [i.message_key for i in _lote_pendentes(session)] == [
            "agora",
            "meia-hora",
            "velho",
        ]
    assert expirar_produtos_velhos() == 1
    with session_factory() as session:
        estados = {i.message_key: (i.status, i.skip_reason) for i in session.query(MirrorInbox)}
    assert estados["velho"] == ("skipped", "produto_velho")
    assert estados["agora"] == ("pending", None)


def test_lote_pendentes_nao_deixa_um_bot_engolir_a_fila(session_factory) -> None:
    """Pending antigo de um bot não impede o mais antigo do outro entrar no lote."""
    from datetime import datetime, timezone

    admin = add_user(session_factory, email="lote-fair@nina.test", role="admin")
    with session_factory.begin() as session:
        phone = Phone(
            id=uuid4(),
            owner_id=admin.tenant_id,
            label="Nina lote",
            number="5511999000888",
            evolution_instance="nina-lote",
        )
        session.add(phone)
        session.flush()
        bot_a = Bot(
            id=uuid4(),
            owner_id=admin.tenant_id,
            name="Bot A",
            slug="bot-a-lote",
            status="active",
            phone_id=phone.id,
            settings={},
        )
        bot_b = Bot(
            id=uuid4(),
            owner_id=admin.tenant_id,
            name="Bot B",
            slug="bot-b-lote",
            status="active",
            phone_id=phone.id,
            settings={},
        )
        session.add_all([bot_a, bot_b])
        session.flush()
        agora = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
        for i in range(10):
            session.add(
                MirrorInbox(
                    owner_id=admin.tenant_id,
                    bot_id=bot_a.id,
                    listen_phone_id=phone.id,
                    source_whatsapp_id="120363origem@g.us",
                    message_key=f"a-{i}",
                    body_text="oferta a",
                    status="pending",
                    created_at=agora.replace(minute=i),
                )
            )
        session.add(
            MirrorInbox(
                owner_id=admin.tenant_id,
                bot_id=bot_b.id,
                listen_phone_id=phone.id,
                source_whatsapp_id="120363origem@g.us",
                message_key="b-0",
                body_text="oferta b",
                status="pending",
                created_at=agora.replace(hour=18),
            )
        )
        lote = _lote_pendentes(session)
        bots = {item.bot_id for item in lote}
        assert bot_a.id in bots
        assert bot_b.id in bots
        assert any(item.message_key == "b-0" for item in lote)
