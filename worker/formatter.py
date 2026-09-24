"""Monta a mensagem do WhatsApp a partir do template configurado no bot."""

from __future__ import annotations

from core import relogio
from core.platforms.base import OfertaCapturada
from worker.channels import load_filtros

TEMPLATE_PADRAO = "🔥 {nome}\n\n✅ R$ {preco}\n\n{url}\n\n⏰ {hora}"

TEMPLATE_LEGADO = (
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
    if abs(valor - round(valor)) < 0.001:
        return str(int(round(valor)))
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _escape_template_field(valor: str) -> str:
    return (valor or "").replace("{", "{{").replace("}", "}}")


def _eh_campanha(oferta: OfertaCapturada) -> bool:
    return (oferta.categoria or "").lower() in {"campanha", "promocao", "promoção"}


def montar_mensagem(oferta: OfertaCapturada) -> str:
    filtros = load_filtros()
    if _eh_campanha(oferta):
        template = filtros.get(
            "mensagem_campanha_template",
            "🎫 CAMPANHA / CUPOM SHOPEE!\n\n📌 {nome}\n\n🏪 {loja}\n\n"
            "👉 ACESSAR:\n{url}\n\n⏰ {hora}",
        )
        return template.format(
            nome=_escape_template_field(oferta.nome),
            loja=_escape_template_field(oferta.loja or ""),
            url=_escape_template_field(oferta.url),
            hora=relogio.formatar_hora(oferta.capturado_em),
        )

    template = filtros.get("mensagem_template") or TEMPLATE_PADRAO
    if "{preco_anterior}" in template:
        return _mensagem_legada(oferta, template)
    return _mensagem_curta(oferta, template)


def _mensagem_curta(oferta: OfertaCapturada, template: str) -> str:
    nome = _escape_template_field(oferta.nome)
    url = _escape_template_field(oferta.url)
    preco = _preco_fmt(oferta.preco) if oferta.preco and oferta.preco > 0 else ""
    corpo = template.format(
        nome=nome,
        preco=preco,
        url=url,
        hora=relogio.formatar_hora(oferta.capturado_em),
    )
    if not preco:
        corpo = corpo.replace("✅ R$ \n\n", "").replace("✅ R$ \n", "")
    codigo = (oferta.codigo_cupom or "").strip()
    if codigo and f"Cupom: {codigo}" not in corpo:
        corpo = corpo.replace(f"\n\n{url}", f"\n🎟️ Cupom: {codigo}\n\n{url}", 1)
    return corpo


def _mensagem_legada(oferta: OfertaCapturada, template: str) -> str:
    if (oferta.categoria or "").lower() == "cupom":
        return _mensagem_cupom_legada(oferta)
    preco_anterior = oferta.preco_anterior if oferta.preco_anterior else oferta.preco
    desconto = oferta.desconto if oferta.desconto is not None else 0
    return template.format(
        nome=_escape_template_field(oferta.nome),
        preco=_preco_fmt(oferta.preco),
        preco_anterior=_preco_fmt(preco_anterior),
        desconto=round(desconto, 1),
        loja=_escape_template_field(oferta.loja or ""),
        url=_escape_template_field(oferta.url),
        hora=relogio.formatar_hora(oferta.capturado_em),
    )


def _mensagem_cupom_legada(oferta: OfertaCapturada) -> str:
    linha = oferta.nome
    if oferta.codigo_cupom and oferta.codigo_cupom not in linha:
        linha = f"{oferta.beneficio or linha}: {oferta.codigo_cupom}"
    loja = (oferta.loja or "").lower()
    if "shopee" in loja:
        texto = f"🎁 CUPOM SHOPEE 🎁\n\n🎫 {linha}\n\n✅ Resgate aqui:\n{oferta.url}"
        if oferta.url_carrinho:
            texto += f"\n\n🛒 Carrinho: {oferta.url_carrinho}"
        return texto
    return f"🔥 Cupom Mercado Livre\n\n🎫 {linha}\n\n✅ Resgate aqui:\n{oferta.url}"
