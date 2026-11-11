"""Controle de duplicidade.

Evita reenviar a mesma oferta (mesmo SKU, ou nome praticamente igual).
Só reenvia se o preço caiu o suficiente desde o último envio com sucesso.
Cupom (categoria=cupom) reenvia após INTERVALO_CUPOM_MINUTOS; novo sai na hora.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy.orm import Session

from core import repositories
from core.cupom_cadencia import INTERVALO_CUPOM_MINUTOS
from core.models import Envio

# Sufixos tipo "--3601" que a Shopee cola no título.
_RE_SUFIXO_LOJA = re.compile(r"\s*--\d+\s*$")
_RE_NAO_ALNUM = re.compile(r"[^a-z0-9]+")


def normalizar_nome(nome: str) -> str:
    if not nome:
        return ""
    s = unicodedata.normalize("NFKD", nome)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().strip()
    s = _RE_SUFIXO_LOJA.sub("", s)
    s = _RE_NAO_ALNUM.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _nomes_parecidos(a: str, b: str, limiar: float = 0.92) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    # Um contém o outro (título truncado vs completo).
    if len(a) >= 20 and len(b) >= 20 and (a in b or b in a):
        return True
    return SequenceMatcher(None, a, b).ratio() >= limiar


def _precos_parecidos(p1: float | None, p2: float | None, tol_pct: float = 3.0) -> bool:
    if p1 is None or p2 is None or p1 <= 0 or p2 <= 0:
        return False
    return abs(p1 - p2) / max(p1, p2) * 100 <= tol_pct


def _deve_enviar_cupom(
    session: Session,
    oferta_id: int,
    envio_anterior: Envio | None,
    *,
    sku: str | None,
    loja: str | None,
    grupo: str | None,
    tenant_id: UUID,
) -> tuple[bool, str]:
    """Cupom novo sai na hora; o mesmo SKU só reenvia após INTERVALO_CUPOM_MINUTOS."""
    ultimo = envio_anterior
    if ultimo is None and sku:
        ultimo = repositories.ultimo_envio_por_sku(
            session,
            sku,
            loja=loja,
            exceto_oferta_id=oferta_id,
            grupo=grupo,
            tenant_id=tenant_id,
        )
    if ultimo is None:
        return True, "cupom novo"
    minutos = repositories._minutos_desde(ultimo.enviado_em) if ultimo.enviado_em else None
    if minutos is None:
        return True, "cupom novo"
    if minutos < INTERVALO_CUPOM_MINUTOS:
        falta = INTERVALO_CUPOM_MINUTOS - minutos
        return False, f"cupom já enviado; reenvio em {falta:.0f} min"
    return True, f"cupom: reenvio após {INTERVALO_CUPOM_MINUTOS} min"


def deve_enviar(
    session: Session,
    oferta_id: int,
    preco_atual: float,
    queda_minima_pct: float,
    *,
    tenant_id: UUID,
    nome: str = "",
    sku: str | None = None,
    loja: str | None = None,
    grupo: str | None = None,
    categoria: str | None = None,
) -> tuple[bool, str]:
    envio_anterior = repositories.ultimo_envio(session, oferta_id, grupo=grupo, tenant_id=tenant_id)

    if (categoria or "").lower() == "cupom":
        return _deve_enviar_cupom(
            session,
            oferta_id,
            envio_anterior,
            sku=sku,
            loja=loja,
            grupo=grupo,
            tenant_id=tenant_id,
        )

    if envio_anterior is None:
        # `visto` da baseline não pode travar envio (restart/Postgres vazio no Railway).
        # Só conta o que já foi blipado de verdade.

        # Mesmo SKU já foi enviado em outra linha de oferta.
        if sku and repositories.sku_ja_enviado(
            session, sku, loja, exceto_oferta_id=oferta_id, grupo=grupo, tenant_id=tenant_id
        ):
            return False, "SKU já enviado anteriormente (duplicata)"

        # Mesmo produto com título/preço quase iguais (SKU diferente).
        nome_norm = normalizar_nome(nome)
        if nome_norm:
            for outro_nome, outro_preco in repositories.nomes_precos_enviados_recentes(
                session, dias=30, grupo=grupo, tenant_id=tenant_id
            ):
                outro_norm = normalizar_nome(outro_nome)
                if _nomes_parecidos(nome_norm, outro_norm) and _precos_parecidos(
                    preco_atual, outro_preco
                ):
                    return False, "oferta igual/parecida já enviada"

        return True, "oferta nova (apareceu depois do baseline)"

    preco_anterior_envio = envio_anterior.preco_enviado
    if not preco_anterior_envio or preco_anterior_envio <= 0:
        return False, "já enviada anteriormente"

    if preco_atual >= preco_anterior_envio:
        return False, "já enviada anteriormente e preço não caiu"

    queda_pct = (1 - preco_atual / preco_anterior_envio) * 100
    if queda_pct >= queda_minima_pct:
        return True, (
            f"preço caiu {queda_pct:.1f}% desde o último envio "
            f"(R${preco_anterior_envio:.2f} -> R${preco_atual:.2f})"
        )

    return (
        False,
        f"já enviada e queda de {queda_pct:.1f}% é menor que o mínimo de {queda_minima_pct}%",
    )
