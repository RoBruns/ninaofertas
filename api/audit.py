"""Auditoria com redacao defensiva de dados sensiveis."""

from __future__ import annotations

from ipaddress import ip_address
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import AuditLog, User

SENSITIVE_KEY_PARTS = (
    "password",
    "senha",
    "secret",
    "token",
    "cookie",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "ciphertext",
    "key",
)


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).casefold()
            if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
                redacted[key] = "***"
            else:
                redacted[key] = redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def _ip_valido(ip: str | None) -> str | None:
    """`audit_logs.ip` e INET: valor invalido faz o Postgres recusar o INSERT.

    A origem pode ser um proxy, um header forjado ou um cliente de teste, e
    auditoria nunca pode derrubar a operacao que ela registra — endereco
    irreconhecivel vira NULL.
    """
    if not ip:
        return None
    try:
        return str(ip_address(ip.strip()))
    except ValueError:
        return None


def record_audit(
    session: Session,
    user: User | None,
    entity_type: str,
    entity_id: str,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    ip: str | None,
) -> AuditLog:
    values: dict[str, Any] = {
        "user_id": user.id if user is not None else None,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "action": action,
        "before": redact_sensitive(before),
        "after": redact_sensitive(after),
        "ip": _ip_valido(ip),
    }
    if session.bind is not None and session.bind.dialect.name == "sqlite":
        # SQLite so autoincrementa PK declarada exatamente como INTEGER; o model
        # usa BIGINT para corresponder ao BIGSERIAL do Postgres.
        values["id"] = int(session.scalar(select(func.max(AuditLog.id))) or 0) + 1
    entry = AuditLog(**values)
    session.add(entry)
    session.flush()
    return entry
