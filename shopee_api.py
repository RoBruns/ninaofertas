"""Cliente GraphQL da Shopee Afiliados (HMAC-SHA256 + POST)."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import httpx

from config import settings

API_URL = "https://open-api.affiliate.shopee.com.br/graphql"


def sign(app_id: str, secret: str, timestamp: int, payload: str) -> str:
    raw = f"{app_id}{timestamp}{payload}{secret}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def escape_graphql_string(value: str) -> str:
    """Escapa valor para literal string dentro de query GraphQL."""
    return json.dumps(value, ensure_ascii=False)[1:-1]


def graphql_request(
    client: httpx.Client,
    query: str,
    *,
    app_id: str | None = None,
    secret: str | None = None,
    raise_on_graphql_errors: bool = True,
) -> dict[str, Any]:
    app_id = app_id or settings.shopee_app_id
    secret = secret or settings.shopee_app_secret
    payload_obj = {"query": query}
    payload = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)
    timestamp = int(time.time())
    signature = sign(app_id, secret, timestamp, payload)
    headers = {
        "Content-Type": "application/json",
        "Authorization": (
            f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}"
        ),
    }
    resp = client.post(API_URL, content=payload.encode("utf-8"), headers=headers)
    resp.raise_for_status()
    dados = resp.json()
    if raise_on_graphql_errors and dados.get("errors"):
        msgs = "; ".join(
            e.get("message") or e.get("extensions", {}).get("message") or str(e)
            for e in dados["errors"]
        )
        raise RuntimeError(f"GraphQL Shopee: {msgs}")
    return dados.get("data") or {}


def generate_short_link(client: httpx.Client, origin_url: str) -> str | None:
    safe_url = escape_graphql_string(origin_url)
    query = (
        "mutation {\n"
        f'  generateShortLink(input: {{ originUrl: "{safe_url}" }}) {{\n'
        "    shortLink\n"
        "  }\n"
        "}"
    )
    data = graphql_request(client, query)
    return ((data.get("generateShortLink") or {}).get("shortLink")) or None
