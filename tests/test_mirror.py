"""Espelho WhatsApp: parser, matching, captura de plataforma e fan-out."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from core.bot_settings import BotSettings, Mirror
from core.link_parser import detectar_loja, extrair_links_oferta, loja_para_platform_slug, substituir_urls
from core.mirror_match import nome_na_allowlist
from core.mirror_sources import allowlist_para_bot, platform_source_group_names
from core.models import Bot, Group, MirrorCapture, MirrorInbox, Phone, Tenant
from core.platforms.base import OfertaCapturada
from tests.test_api import add_user, client, session_factory
from core.mirror_media import imagem_do_link_produto, mensagem_tem_imagem, resolver_imagem_espelho
from worker import formatter
from worker.filters import (
    extrair_cupom_mensagem,
    extrair_precos_mensagem,
    passa_filtros_espelho,
    titulo_mensagem_espelho,
)
from worker.mirror import _oferta_template


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
    assert "MELHORES OFERTAS" in platform_source_group_names()
    assert nome_na_allowlist("🔥 Melhores Ofertas", platform_source_group_names())
    subset = allowlist_para_bot(["MELHORES OFERTAS", "Grupo Inventado"])
    assert subset == ["MELHORES OFERTAS"]
    assert allowlist_para_bot([]) == platform_source_group_names()


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


def test_imagem_do_link_produto_usa_og_image(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        "<html><head>"
        '<meta property="og:image" content="https://down-br.img.susercontent.com/foto.jpg">'
        "</head></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://shopee.com.br/")
        return httpx.Response(200, text=html)

    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    foto = imagem_do_link_produto("https://shopee.com.br/product/1/2", "shopee")
    assert foto == "https://down-br.img.susercontent.com/foto.jpg"


def test_mensagem_tem_imagem_e_resolver_prioriza_whatsapp(monkeypatch: pytest.MonkeyPatch) -> None:
    assert mensagem_tem_imagem({"imageMessage": {"caption": "oi"}})
    assert not mensagem_tem_imagem({"conversation": "só texto"})

    monkeypatch.setattr(
        "core.mirror_media.midia_whatsapp_em_memoria",
        lambda instance, key: "data:image/jpeg;base64," + ("A" * 80),
    )
    monkeypatch.setattr(
        "core.mirror_media.imagem_do_link_produto",
        lambda url, loja=None: "https://down-br.img.susercontent.com/nao-deve-usar.jpg",
    )
    foto = resolver_imagem_espelho(
        listen_instance="nina1",
        message_key="120@g.us:MSG1",
        product_url="https://s.shopee.com.br/x",
        loja="shopee",
    )
    assert foto is not None and foto.startswith("data:image/jpeg;base64,")
