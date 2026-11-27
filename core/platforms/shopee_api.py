"""Cliente GraphQL da Shopee Afiliados (SHA256 + POST)."""

from __future__ import annotations

import hashlib
import json
import re
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


def _tokens_busca(texto: str) -> list[str]:
    limpo = re.sub(r"[^\w\s]", " ", (texto or "").lower(), flags=re.UNICODE)
    return [p for p in limpo.split() if len(p) >= 3]


def foto_por_titulo(
    client: httpx.Client,
    titulo: str,
    *,
    app_id: str,
    secret: str,
    preco: float | None = None,
) -> str | None:
    """imageUrl do anúncio cujo nome bate com o título (busca da API de afiliado).

    Com modelo no título (token com número), exige ao menos um igual e metade das
    palavras; sem modelo, 60%. Com preço, até 35% de diferença — melhor ficar sem
    foto do que mandar a de outro produto.
    """
    nome_produto = (titulo or "").split(":", 1)[0]
    tokens = _tokens_busca(nome_produto)[:10]
    if len(tokens) < 2:
        return None
    keyword = escape_graphql_string(" ".join(tokens[:8]))
    query = (
        "{ productOfferV2(keyword: \"" + keyword + "\", listType: 0, sortType: 1, "
        "page: 1, limit: 10) { nodes { productName imageUrl priceMin } } }"
    )
    data = graphql_request(client, query, app_id=app_id, secret=secret)
    nossos = set(tokens)
    modelo = {p for p in nossos if any(c.isdigit() for c in p)}
    minimo = 0.5 if modelo else 0.6
    melhor: tuple[float, str] | None = None
    for node in (data.get("productOfferV2") or {}).get("nodes") or []:
        url = node.get("imageUrl")
        nome = node.get("productName") or ""
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        deles = set(_tokens_busca(nome))
        if modelo and not (modelo & deles):
            continue
        score = len(nossos & deles) / len(nossos)
        if score < minimo:
            continue
        if preco:
            try:
                preco_api = float(node.get("priceMin"))
            except (TypeError, ValueError):
                preco_api = 0.0
            if preco_api and abs(preco_api - preco) / preco > 0.35:
                continue
        if melhor is None or score > melhor[0]:
            melhor = (score, url)
    return melhor[1] if melhor else None


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
