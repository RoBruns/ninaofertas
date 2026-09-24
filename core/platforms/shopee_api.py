"""Cliente GraphQL da Shopee Afiliados (SHA256 + POST)."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Sequence

import httpx

API_URL = "https://open-api.affiliate.shopee.com.br/graphql"


def sign(app_id: str, secret: str, timestamp: int, payload: str) -> str:
    raw = f"{app_id}{timestamp}{payload}{secret}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def escape_graphql_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)[1:-1]


def graphql_request(
    client: httpx.Client,
    query: str,
    *,
    app_id: str,
    secret: str,
    raise_on_graphql_errors: bool = True,
) -> dict[str, Any]:
    payload = json.dumps({"query": query}, separators=(",", ":"), ensure_ascii=False)
    timestamp = int(time.time())
    signature = sign(app_id, secret, timestamp, payload)
    response = client.post(
        API_URL,
        content=payload.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": (
                f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}"
            ),
        },
    )
    response.raise_for_status()
    body = response.json()
    if raise_on_graphql_errors and body.get("errors"):
        messages = "; ".join(
            error.get("message")
            or error.get("extensions", {}).get("message")
            or str(error)
            for error in body["errors"]
        )
        raise RuntimeError(f"GraphQL Shopee: {messages}")
    return body.get("data") or {}


def generate_short_link(
    client: httpx.Client,
    origin_url: str,
    *,
    app_id: str,
    secret: str,
    sub_ids: Sequence[str] = (),
) -> str | None:
    sub_ids_arg = f", subIds: {json.dumps(list(sub_ids))}" if sub_ids else ""
    query = (
        "mutation {\n"
        f'  generateShortLink(input: {{ originUrl: "{escape_graphql_string(origin_url)}"'
        f"{sub_ids_arg} }}) {{\n"
        "    shortLink\n"
        "  }\n"
        "}"
    )
    data = graphql_request(client, query, app_id=app_id, secret=secret)
    return ((data.get("generateShortLink") or {}).get("shortLink")) or None
