"""Redação de trechos sensíveis antes de gravar em log."""
from __future__ import annotations

import re

_REDACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(apikey|authorization|x-csrf-token)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)cookie\s*[:=]\s*[^;\s]+(?:;\s*[^;\s]+=[^;\s]+)*"), "cookie=[REDACTED]"),
    (re.compile(r"(?i)(signature|credential)\s*=\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)Bearer\s+\S+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)(access_token|refresh_token)[\"']?\s*[:=]\s*[\"']?[\w\-./]+"), r"\1=[REDACTED]"),
)


def safe_log_text(text: str, max_len: int = 300) -> str:
    if not text:
        return ""
    out = text
    for pattern, repl in _REDACT_PATTERNS:
        out = pattern.sub(repl, out)
    if len(out) > max_len:
        return out[:max_len] + "…"
    return out
