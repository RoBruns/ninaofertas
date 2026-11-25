"""Deduplicação do espelho por product_key (não por mensagem de origem)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from core import repositories
from core.settings import settings


def pode_enviar_produto(
    session: Session,
    *,
    sku: str,
    loja: str | None,
    grupo: str,
    tenant_id: UUID,
    preco: float,
    dedup_horas: int,
    queda_minima_pct: float | None = None,
) -> tuple[bool, str]:
    """False se o mesmo produto já saiu no grupo dentro da janela, sem queda suficiente."""
    ultimo = repositories.ultimo_envio_por_sku(
        session, sku, loja=loja, grupo=grupo, tenant_id=tenant_id
    )
    if ultimo is None or ultimo.enviado_em is None:
        return True, "produto novo"
    minutos = repositories._minutos_desde(ultimo.enviado_em)  # noqa: SLF001
    if minutos is None:
        return True, "produto novo"
    if minutos >= float(dedup_horas) * 60:
        return True, f"produto fora da janela de {dedup_horas}h"

    minimo = (
        settings.reenvio_queda_minima if queda_minima_pct is None else float(queda_minima_pct)
    )
    anterior = float(ultimo.preco_enviado or 0)
    if preco > 0 and anterior > 0 and preco < anterior:
        queda = (1 - preco / anterior) * 100
        if queda >= minimo:
            return True, f"preço caiu {queda:.1f}% desde o último envio"
    return False, "duplicado_produto"


def vencedores_do_lote(
    candidatos: list[tuple[object, str, float]],
) -> set[object]:
    """Entre cópias do mesmo product_key no lote, fica a de menor preço."""
    por_chave: dict[str, list[tuple[object, float]]] = {}
    for item_id, chave, preco in candidatos:
        por_chave.setdefault(chave, []).append((item_id, preco))
    vencedores: set[object] = set()
    for pares in por_chave.values():
        melhor = min(
            pares,
            key=lambda p: (p[1] if p[1] > 0 else float("inf"), str(p[0])),
        )
        vencedores.add(melhor[0])
    return vencedores
