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


def _cupom_digitavel(codigo: str | None) -> str | None:
    from worker.filters import _cupom_espelho_ok

    return _cupom_espelho_ok(codigo)


def _preco_fmt(valor: float) -> str:
    if abs(valor - round(valor)) < 0.001:
        return str(int(round(valor)))
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _escape_template_field(valor: str) -> str:
    return (valor or "").replace("{", "{{").replace("}", "}}")


def _eh_campanha(oferta: OfertaCapturada) -> bool:
    return (oferta.categoria or "").lower() in {"campanha", "promocao", "promoção"}


def montar_mensagem(oferta: OfertaCapturada) -> str:
    if (oferta.categoria or "").lower() == "cupom":
        return _mensagem_cupom(oferta)
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


def _injetar_cupom_antes_do_link(corpo: str, oferta: OfertaCapturada) -> str:
    """Garante linha de cupom quando a origem trouxe código ou só a menção."""
    codigo = _cupom_digitavel(oferta.codigo_cupom)
    if codigo:
        if codigo in corpo.upper():
            return corpo
        aviso = f"🎟️ Use o cupom: *{codigo}*"
    elif (oferta.beneficio or "").lower() == "cupom_origem":
        if re.search(r"(?i)cupom", corpo):
            return corpo
        aviso = "🎟️ Oferta com cupom — use o código no checkout"
    else:
        return corpo
    url = oferta.url or ""
    if url and url in corpo:
        return corpo.replace(url, f"{aviso}\n\n{url}", 1)
    return f"{corpo}\n\n{aviso}".strip()


def _mensagem_curta(oferta: OfertaCapturada, template: str) -> str:
    """Substitui as variáveis; a linha cuja variável ficou vazia sai da mensagem."""
    codigo = _cupom_digitavel(oferta.codigo_cupom)
    # Aviso genérico preenche {cupom} quando a origem falou em cupom sem código.
    cupom_campo = codigo
    if not cupom_campo and (oferta.beneficio or "").lower() == "cupom_origem":
        cupom_campo = "código no checkout"
    valores = {
        # "*" e "~" no nome quebrariam o negrito do WhatsApp.
        "nome": (oferta.nome or "").replace("*", "").replace("~", "").strip(),
        "preco": _preco_fmt(oferta.preco) if oferta.preco and oferta.preco > 0 else "",
        "de_por": _de_por(oferta),
        "cupom": cupom_campo or "",
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
    return _injetar_cupom_antes_do_link(corpo, oferta)


def _mensagem_legada(oferta: OfertaCapturada, template: str) -> str:
    if (oferta.categoria or "").lower() == "cupom":
        return _mensagem_cupom_legada(oferta)
    preco_anterior = oferta.preco_anterior if oferta.preco_anterior else oferta.preco
    desconto = oferta.desconto if oferta.desconto is not None else 0
    corpo = template.format(
        nome=_escape_template_field(oferta.nome),
        preco=_preco_fmt(oferta.preco),
        preco_anterior=_preco_fmt(preco_anterior),
        desconto=round(desconto, 1),
        loja=_escape_template_field(oferta.loja or ""),
        url=_escape_template_field(oferta.url),
        hora=relogio.formatar_hora(oferta.capturado_em),
    )
    # Template legado não tem {cupom} — injeta quando a origem trouxe código/menção.
    return _injetar_cupom_antes_do_link(corpo, oferta)


def _mensagem_cupom(oferta: OfertaCapturada) -> str:
    """Cupom resgatável/aplicável com link afiliado, não o anúncio de um produto."""
    beneficio = (oferta.beneficio or oferta.nome or "Cupom").strip()
    codigo = _cupom_digitavel(oferta.codigo_cupom)
    if codigo and codigo not in beneficio.upper():
        beneficio = f"{beneficio}: {codigo}"
    validade = (oferta.validade or "").strip()
    loja = (oferta.loja or "").lower()
    if "mercado" in loja:
        linhas = [
            "🔥 Cupom Mercado Livre",
            "",
            f"🎟️ {beneficio}",
            "",
            "✅ Resgate aqui:",
            oferta.url or "",
        ]
        if validade:
            linhas.extend(["", validade])
        return "\n".join(linhas).strip()
    titulo = "🚨 RESGATE CUPOM SHOPEE LIBERADO!"
    if "shopee" not in loja and oferta.loja:
        titulo = f"🚨 RESGATE CUPOM {oferta.loja.upper()} LIBERADO!"
    linhas = [
        titulo,
        "",
        f"🎟️ {beneficio}",
        oferta.url or "",
    ]
    if validade:
        linhas.extend(["", validade])
    return "\n".join(linhas).strip()


def _mensagem_cupom_legada(oferta: OfertaCapturada) -> str:
    return _mensagem_cupom(oferta)
