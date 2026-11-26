"""Gera openapi.json a partir do app FastAPI (uso local / CI)."""

from __future__ import annotations

import json
import os
from pathlib import Path

# Placeholders só para importar o app sem tocar produção.
os.environ.setdefault("JWT_SECRET", "local-openapi-dump")
os.environ.setdefault(
    "CREDENTIALS_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)

from api.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
target = ROOT / "openapi.json"
target.write_text(
    json.dumps(app.openapi(), ensure_ascii=False, indent=1),
    encoding="utf-8",
)
print(f"wrote {target}")
