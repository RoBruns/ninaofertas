"""Monta a mensagem do WhatsApp a partir do template configurado no bot."""

from __future__ import annotations

import re

from core import relogio
from core.platforms.base import OfertaCapturada
from worker.channels import load_filtros

# Formato pedido pelo usuário (2026-09-24): nome em negrito, preço antigo riscado e
# preço novo em negrito (markdown do WhatsApp), linha do cupom só quando houver.
TEMPLATE_PADRAO = "◼️ *{nome}*\n\n💰 {de_por}\n🎟️ Use o cupom: *{cupom}*\n\n🛒 {url}"

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

_CAMPO = re.compile(r"\{(\w+)\}")


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


def _de_por(oferta: OfertaCapturada) -> str:
    """"De ~R$ 115~ por *R$ 92*"; sem preço antigo maior, só "Por *R$ 92*"."""
    if not oferta.preco or oferta.preco <= 0:
        return ""
    por = f"*R$ {_preco_fmt(oferta.preco)}*"
    anterior = oferta.preco_anterior
    if anterior and anterior - oferta.preco >= 0.01:
        return f"De ~R$ {_preco_fmt(anterior)}~ por {por}"
    return f"Por {por}"


def _mensagem_curta(oferta: OfertaCapturada, template: str) -> str:
    """Substitui as variáveis; a linha cuja variável ficou vazia sai da mensagem."""
    codigo = (oferta.codigo_cupom or "").strip()
    valores = {
        # "*" e "~" no nome quebrariam o negrito do WhatsApp.
        "nome": (oferta.nome or "").replace("*", "").replace("~", "").strip(),
        "preco": _preco_fmt(oferta.preco) if oferta.preco and oferta.preco > 0 else "",
        "de_por": _de_por(oferta),
        "cupom": codigo,
        "loja": oferta.loja or "",
        "url": oferta.url or "",
        "hora": relogio.formatar_hora(oferta.capturado_em),
    }
    linhas = []
    for linha in template.split("\n"):
        campos = _CAMPO.findall(linha)
        if any(campo in valores and not valores[campo] for campo in campos):
            continue
        linhas.append(_CAMPO.sub(lambda m: valores.get(m.group(1), m.group(0)), linha))
    corpo = re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip()
    url = valores["url"]
    if codigo and codigo not in corpo and url and url in corpo:
        # Template do bot sem {cupom}: o código entra antes do link.
        corpo = corpo.replace(url, f"🎟️ Cupom: *{codigo}*\n\n{url}", 1)
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
