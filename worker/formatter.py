"""Monta a mensagem do WhatsApp a partir do template configurável em config.json."""
from __future__ import annotations

from core.platforms.base import OfertaCapturada
from worker.channels import load_filtros

TEMPLATE_PADRAO = (
    "🔥 OFERTA ENCONTRADA!\n\n"
    "🛒 {nome}\n\n"
    "💰 De: R$ {preco_anterior}\n"
    "🔥 Por: R$ {preco}\n"
    "📉 {desconto}% OFF\n\n"
    "🏪 {loja}\n\n"
    "👉 COMPRAR:\n{url}\n\n"
    "⏰ Oferta encontrada às {hora}"
)


def _preco_fmt(valor: float) -> str:
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _eh_cupom(oferta: OfertaCapturada) -> bool:
    return (oferta.categoria or "").lower() in {"cupom", "campanha", "promocao", "promoção"}


def montar_mensagem(oferta: OfertaCapturada) -> str:
    filtros = load_filtros()
    if _eh_cupom(oferta) and (oferta.categoria or "").lower() == "cupom":
        return _mensagem_cupom(oferta)

    if _eh_cupom(oferta):
        template = filtros.get(
            "mensagem_campanha_template",
            "🎫 CAMPANHA / CUPOM SHOPEE!\n\n📌 {nome}\n\n🏪 {loja}\n\n👉 ACESSAR:\n{url}\n\n⏰ {hora}",
        )
    else:
        template = filtros.get("mensagem_template", TEMPLATE_PADRAO)

    preco_anterior = oferta.preco_anterior if oferta.preco_anterior else oferta.preco
    desconto = oferta.desconto if oferta.desconto is not None else 0

    return template.format(
        nome=oferta.nome,
        preco=_preco_fmt(oferta.preco),
        preco_anterior=_preco_fmt(preco_anterior),
        desconto=round(desconto, 1),
        loja=oferta.loja,
        url=oferta.url,
        hora=oferta.capturado_em.strftime("%H:%M"),
    )


def _mensagem_cupom(oferta: OfertaCapturada) -> str:
    linha = oferta.nome
    if oferta.codigo_cupom and oferta.codigo_cupom not in linha:
        linha = f"{oferta.beneficio or linha}: {oferta.codigo_cupom}"
    loja = (oferta.loja or "").lower()
    if "shopee" in loja:
        texto = (
            "🎁 CUPOM SHOPEE 🎁\n\n"
            f"🎫 {linha}\n\n"
            f"✅ Resgate aqui:\n{oferta.url}"
        )
        if oferta.url_carrinho:
            texto += f"\n\n🛒 Carrinho: {oferta.url_carrinho}"
        return texto
    return (
        "🔥 Cupom Mercado Livre\n\n"
        f"🎫 {linha}\n\n"
        f"✅ Resgate aqui:\n{oferta.url}"
    )
