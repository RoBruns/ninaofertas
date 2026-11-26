"""Allowlist de origem do espelho — dono: plataforma (Nina 1)."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

# Grupos/canais que a Nina 1 escuta para toda a base (ADR-036).
# Catálogo padrão; a lista efetiva pode ser reduzida no dashboard (ADR-043).
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

# Teto operacional da allowlist ativa (fila curta; cupom não esgota na espera).
MAX_PLATFORM_SOURCE_GROUPS = 3
SETTING_KEY = "mirror_source_group_names"

_cache_lock = threading.Lock()
_cache: list[str] | None = None
_cache_at = 0.0
_CACHE_TTL = 30.0


def _limpar_nomes(raw: Any, *, limite: int | None = None) -> list[str]:
    from core.mirror_match import normalizar_nome_grupo

    out: list[str] = []
    seen: set[str] = set()
    if not isinstance(raw, list):
        return out
    for item in raw:
        name = " ".join(str(item or "").split()).strip()
        if not name or len(name) > 120:
            continue
        key = normalizar_nome_grupo(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(name)
        if limite is not None and len(out) >= limite:
            break
    return out


def _from_env_or_default() -> list[str]:
    raw = (os.getenv("MIRROR_SOURCE_GROUPS") or "").strip()
    if not raw:
        return list(PLATFORM_SOURCE_GROUP_NAMES)
    names = _limpar_nomes([line.strip() for line in raw.splitlines() if line.strip()])
    return names or list(PLATFORM_SOURCE_GROUP_NAMES)


def invalidate_platform_source_cache() -> None:
    global _cache, _cache_at
    with _cache_lock:
        _cache = None
        _cache_at = 0.0


def _ler_do_banco(session) -> list[str] | None:
    from core.models import PlatformSetting

    row = session.get(PlatformSetting, SETTING_KEY)
    if row is None:
        return None
    names = _limpar_nomes(row.value, limite=MAX_PLATFORM_SOURCE_GROUPS)
    return names or None


def salvar_platform_source_group_names(session, names: list[str]) -> list[str]:
    """Persiste a allowlist ativa (1..MAX). Invalida o cache."""
    from core.models import PlatformSetting
    from core import relogio

    limpos = _limpar_nomes(names, limite=MAX_PLATFORM_SOURCE_GROUPS)
    if not limpos:
        raise ValueError("Escolha ao menos um grupo de origem")
    if len(limpos) > MAX_PLATFORM_SOURCE_GROUPS:
        raise ValueError(f"No máximo {MAX_PLATFORM_SOURCE_GROUPS} grupos de origem")
    row = session.get(PlatformSetting, SETTING_KEY)
    if row is None:
        row = PlatformSetting(key=SETTING_KEY, value=limpos)
        session.add(row)
    else:
        row.value = limpos
        row.updated_at = relogio.agora_banco()
    session.flush()
    invalidate_platform_source_cache()
    with _cache_lock:
        global _cache, _cache_at
        _cache = list(limpos)
        _cache_at = time.monotonic()
    return limpos


def limpar_platform_source_override(session) -> None:
    """Remove override do banco; volta env/padrão. Invalida o cache."""
    from core.models import PlatformSetting

    row = session.get(PlatformSetting, SETTING_KEY)
    if row is not None:
        session.delete(row)
        session.flush()
    invalidate_platform_source_cache()


def platform_source_group_names(session=None) -> list[str]:
    """Lista efetiva: banco (dashboard) → env `MIRROR_SOURCE_GROUPS` → padrão."""
    global _cache, _cache_at
    agora = time.monotonic()
    with _cache_lock:
        if _cache is not None and agora - _cache_at < _CACHE_TTL:
            return list(_cache)

    nomes: list[str] | None = None
    if session is not None:
        nomes = _ler_do_banco(session)
    else:
        try:
            from core import db

            with db.get_session() as sess:
                nomes = _ler_do_banco(sess)
        except Exception:
            nomes = None

    if not nomes:
        nomes = _from_env_or_default()

    with _cache_lock:
        _cache = list(nomes)
        _cache_at = time.monotonic()
    return list(nomes)


def catalogo_candidatos(session) -> list[str]:
    """Catálogo para o picker: padrão + grupos sincronizados na Nina 1."""
    from core.models import Group, Phone
    from sqlalchemy import select

    base = list(PLATFORM_SOURCE_GROUP_NAMES)
    listen_ids = list(
        session.scalars(select(Phone.id).where(Phone.is_platform_listen.is_(True))).all()
    )
    extras: list[str] = []
    if listen_ids:
        extras = list(
            session.scalars(
                select(Group.name)
                .where(
                    Group.phone_id.in_(listen_ids),
                    Group.name.is_not(None),
                    Group.status == "active",
                )
                .order_by(Group.name.asc())
            ).all()
        )
    return _limpar_nomes([*base, *[n for n in extras if n]], limite=80)


def origem_efetiva(session) -> str:
    if _ler_do_banco(session) is not None:
        return "database"
    if (os.getenv("MIRROR_SOURCE_GROUPS") or "").strip():
        return "env"
    return "default"


def allowlist_para_bot(bot_subset: list[str] | None, session=None) -> list[str]:
    """Interseção opcional: subset do bot ∩ allowlist da plataforma.

    Subset vazio = usa a lista da plataforma inteira.
    """
    plataforma = platform_source_group_names(session)
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


def pular_pending_fora_da_allowlist(session, allow: list[str]) -> int:
    """Marca pending cuja origem não está na allowlist — esvazia a fila morta."""
    from core.mirror_match import nome_na_allowlist
    from core.models import MirrorInbox
    from sqlalchemy import select

    pending = list(
        session.scalars(select(MirrorInbox).where(MirrorInbox.status == "pending")).all()
    )
    n = 0
    for item in pending:
        nome = item.source_group_name or ""
        if nome_na_allowlist(nome, allow):
            continue
        item.status = "skipped"
        item.skip_reason = "origem_fora_allowlist"
        n += 1
    if n:
        session.flush()
    return n
