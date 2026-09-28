"""Monta a mensagem do WhatsApp a partir do template configurável em config.json."""
from __future__ import annotations

import re

import relogio
from config import load_filtros
from scraper.base import OfertaCapturada

TEMPLATE_PADRAO = "{nome}\n\n💰 De R$ {preco_anterior} por R$ {preco}\n\n🛒 {url}"

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
    """Evita que `{`/`}` no título do produto quebrem str.format do template."""
    return (valor or "").replace("{", "{{").replace("}", "}}")


def _eh_campanha(oferta: OfertaCapturada) -> bool:
    return (oferta.categoria or "").lower() in {"campanha", "promocao", "promoção"}


def montar_mensagem(oferta: OfertaCapturada) -> str:
    filtros = load_filtros()
    if _eh_campanha(oferta):
        template = filtros.get(
            "mensagem_campanha_template",
            "🎫 CAMPANHA / CUPOM SHOPEE!\n\n📌 {nome}\n\n🏪 {loja}\n\n👉 ACESSAR:\n{url}\n\n⏰ {hora}",
        )
        return template.format(
            nome=_escape_template_field(oferta.nome),
            loja=_escape_template_field(oferta.loja or ""),
            url=_escape_template_field(oferta.url),
            hora=relogio.formatar_hora(oferta.capturado_em),
        )

    template = filtros.get("mensagem_template", TEMPLATE_PADRAO)
    if "{loja}" in template or "{hora}" in template or "{desconto}" in template:
        return _mensagem_legada(oferta, template)
    return _mensagem_oferta(oferta)


def _mensagem_oferta(oferta: OfertaCapturada) -> str:
    """Legenda do Cozinha: nome, de/por numa linha, link com carrinho."""
    nome = _escape_template_field(oferta.nome)
    url = _escape_template_field(oferta.url)
    partes = [nome] if nome else []
    linha_preco = _linha_preco(oferta)
    if linha_preco:
        partes.append(linha_preco)
    codigo = _cupom_digitavel(oferta.codigo_cupom)
    if codigo:
        partes.append(f"🎟️ Cupom: {codigo}")
    if url:
        partes.append(f"🛒 {url}")
    return "\n\n".join(partes)


def _linha_preco(oferta: OfertaCapturada) -> str:
    if not oferta.preco or oferta.preco <= 0:
        return ""
    atual = _preco_fmt(oferta.preco)
    anterior = oferta.preco_anterior
    if anterior and anterior > oferta.preco:
        return f"💰 De R$ {_preco_fmt(anterior)} por R$ {atual}"
    return f"💰 R$ {atual}"


def _cupom_digitavel(codigo: str | None) -> str | None:
    """Código que a pessoa digita no checkout. 'R$ 100 OFF' não é código."""
    code = (codigo or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{4,16}", code):
        return None
    if code in {"HTTP", "HTTPS", "MLB", "JSON", "TYPE", "CUPOM", "OFF"}:
        return None
    return code


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
    codigo = _cupom_digitavel(oferta.codigo_cupom)
    if codigo and codigo not in linha:
        linha = f"{oferta.beneficio or linha}: {codigo}"
    loja = (oferta.loja or "").lower()
    if "shopee" in loja:
        texto = f"🎁 CUPOM SHOPEE 🎁\n\n🎫 {linha}\n\n✅ Resgate aqui:\n{oferta.url}"
        if oferta.url_carrinho:
            texto += f"\n\n🛒 Carrinho: {oferta.url_carrinho}"
        return texto
    return f"🔥 Cupom Mercado Livre\n\n🎫 {linha}\n\n✅ Resgate aqui:\n{oferta.url}"
