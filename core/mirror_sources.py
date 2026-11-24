"""Allowlist de origem do espelho — dono: plataforma (Nina 1)."""

from __future__ import annotations

import os

# Grupos/canais que a Nina 1 escuta para toda a base (ADR-036).
PLATFORM_SOURCE_GROUP_NAMES: tuple[str, ...] = (
    "Achadinho da Loe #236",
    "Achadinhos & Ofertas",
    "casa e decorações",
    "Economizei 430",
    "MELHORES OFERTAS",
    "Ofertas da Gio #147",
    "PROMO CASINHA #6",
    "Promos do Dia #259",
    "Criadores e Afiliados Shopee Brasil",
)


def platform_source_group_names() -> list[str]:
    """Lista efetiva: env `MIRROR_SOURCE_GROUPS` (um por linha) ou o padrão."""
    raw = (os.getenv("MIRROR_SOURCE_GROUPS") or "").strip()
    if not raw:
        return list(PLATFORM_SOURCE_GROUP_NAMES)
    names = [line.strip() for line in raw.splitlines() if line.strip()]
    return names or list(PLATFORM_SOURCE_GROUP_NAMES)


def allowlist_para_bot(bot_subset: list[str] | None) -> list[str]:
    """Interseção opcional: subset do bot ∩ allowlist da plataforma.

    Subset vazio = usa a lista da plataforma inteira.
    """
    plataforma = platform_source_group_names()
    if not bot_subset:
        return plataforma
    from core.mirror_match import normalizar_nome_grupo

    plat_norm = {normalizar_nome_grupo(n): n for n in plataforma}
    out: list[str] = []
    seen: set[str] = set()
    for name in bot_subset:
        key = normalizar_nome_grupo(name)
        if key in plat_norm and key not in seen:
            seen.add(key)
            out.append(plat_norm[key])
    return out
