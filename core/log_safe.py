"""Redacao de trechos sensiveis antes de gravar em log."""

from __future__ import annotations

import re

_REDACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)(apikey|authorization|x-csrf-token)\s*[:=]\s*\S+"),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(r"(?i)cookie\s*[:=]\s*[^;\s]+(?:;\s*[^;\s]+=[^;\s]+)*"),
        "cookie=[REDACTED]",
    ),
    (re.compile(r"(?i)(signature|credential)\s*=\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)Bearer\s+\S+"), "Bearer [REDACTED]"),
    (
        re.compile(
            r"(?i)(access_token|refresh_token)[\"']?\s*[:=]\s*[\"']?[\w\-./]+"
        ),
        r"\1=[REDACTED]",
    ),
)


def safe_log_text(text: object, max_len: int = 300) -> str:
    if not text:
        return ""
    output = str(text).replace("\r", " ").replace("\n", " ")
    for pattern, replacement in _REDACT_PATTERNS:
        output = pattern.sub(replacement, output)
    if len(output) > max_len:
        return output[:max_len] + "…"
    return output
