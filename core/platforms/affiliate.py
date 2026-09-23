"""Conversão de URLs para links de afiliado.

- Shopee: productOfferV2 / shopeeOfferV2 já entregam `offerLink` com tracking.
  Se cair um link cru, tentamos `generateShortLink`.
- Mercado Livre: endpoint interno createLink (tag + cookie de sessão).
"""
from __future__ import annotations

import hashlib
import json
import time

import httpx
from loguru import logger

from core.config_provider import bot_runtime_atual
from core.credentials import mark_account_credentials_invalid, runtime_account_credentials
from core.settings import settings

ML_CREATE_LINK = "https://www.mercadolivre.com.br/affiliate-program/api/v2/affiliates/createLink"
ML_LINKBUILDER = "https://www.mercadolivre.com.br/afiliados/linkbuilder"
SHOPEE_API = "https://open-api.affiliate.shopee.com.br/graphql"


def _runtime_auth(platform_slug: str):
    runtime = bot_runtime_atual()
    try:
        if runtime is None or not runtime.account_ids:
            return runtime, None
        return runtime, runtime_account_credentials(runtime.account_ids, platform_slug)
    except Exception as exc:
        logger.error(f"[afiliado] Falha ao ler credencial da conta {platform_slug}: {exc}")
        return runtime, None


def _credential_value(values: dict[str, str], *names: str) -> str:
    return next((values[name] for name in names if values.get(name)), "")


def _cookie_value(cookie: str, name: str) -> str | None:
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith(f"{name}="):
            return part.split("=", 1)[1]
    return None


def _shopee_sign(app_id: str, secret: str, timestamp: int, payload: str) -> str:
    return hashlib.sha256(f"{app_id}{timestamp}{payload}{secret}".encode()).hexdigest()


def _ja_parece_afiliado_ml(url: str) -> bool:
    u = url.lower()
    return (
        "meli.la/" in u
        or "matt_tool=" in u
        or "matt_word=" in u
        or "/sec/" in u
        or "click1.mercadolivre" in u
    )


def _extrair_url_afiliada(data) -> str | None:
    """createLink devolve snake_case: urls[].short_url (ex.: https://meli.la/xxxx)."""
    chaves = (
        "short_url",
        "shortUrl",
        "affiliateLink",
        "affineLink",
        "url",
        "link",
    )
    if isinstance(data, dict):
        for key in chaves:
            val = data.get(key)
            if isinstance(val, str) and val.startswith("http") and key != "text":
                if "meli.la/" in val.lower() or key in ("short_url", "shortUrl", "affiliateLink"):
                    return val
        if isinstance(data.get("urls"), list) and data["urls"]:
            return _extrair_url_afiliada(data["urls"][0])
        # fallback: pega meli.la dentro do texto
        text = data.get("text")
        if isinstance(text, str) and "meli.la/" in text:
            for parte in text.split():
                if "meli.la/" in parte and parte.startswith("http"):
                    return parte.strip()
    return None


def _ja_parece_afiliado_shopee(url: str) -> bool:
    u = url.lower()
    return "s.shopee.com.br" in u or "shope.ee/" in u or "an_re=" in u or "utm_content=" in u


def converter_mercadolivre(url: str) -> str | None:
    runtime, account = _runtime_auth("mercadolivre")
    if runtime is not None and runtime.account_ids:
        if account is None:
            logger.warning("[afiliado] MELI sem conta/credencial vinculada")
            return None
        account_id, config, values = account
        tag = str(config.get("affiliate_tag") or config.get("tag") or "")
        cookie = _credential_value(values, "cookie", "affiliate_cookie")
    else:
        account_id = None
        tag = settings.mercadolivre_affiliate_tag
        cookie = settings.mercadolivre_affiliate_cookie
    if not tag or not cookie:
        logger.warning("[afiliado] MELI sem TAG/COOKIE no .env — mantendo URL original")
        return None
    if _ja_parece_afiliado_ml(url):
        return url

    csrf = _cookie_value(cookie, "_csrf") or _cookie_value(cookie, "csrf") or ""
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": "https://www.mercadolivre.com.br",
        "referer": "https://www.mercadolivre.com.br/afiliados/linkbuilder",
        "user-agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "cookie": cookie,
    }
    if csrf:
        headers["x-csrf-token"] = csrf

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            # refresca cookies de sessão do linkbuilder quando possível
            try:
                client.get(ML_LINKBUILDER, headers={"cookie": cookie, "user-agent": headers["user-agent"]})
            except httpx.HTTPError:
                pass

            resp = client.post(ML_CREATE_LINK, headers=headers, json={"urls": [url], "tag": tag})
            if resp.status_code >= 400:
                if resp.status_code in {401, 403} and account_id is not None:
                    mark_account_credentials_invalid(
                        account_id,
                        f"HTTP {resp.status_code}",
                        bot_id=runtime.id if runtime else None,
                    )
                logger.error(f"[afiliado] MELI createLink HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
    except Exception as e:
        logger.error(f"[afiliado] MELI createLink falhou: {e}")
        return None

    convertida = _extrair_url_afiliada(data)
    if convertida:
        logger.info(f"[afiliado] MELI convertida: {convertida}")
        return convertida
    logger.error(f"[afiliado] MELI createLink resposta inesperada: {str(data)[:240]}")
    return None


def converter_shopee(url: str) -> str | None:
    if _ja_parece_afiliado_shopee(url):
        return url
    runtime, account = _runtime_auth("shopee")
    if runtime is not None and runtime.account_ids:
        if account is None:
            return None
        account_id, config, values = account
        app_id = str(
            config.get("app_id")
            or config.get("affiliate_id")
            or config.get("external_id")
            or values.get("app_id")
            or values.get("api_key")
            or ""
        )
        secret = _credential_value(values, "app_secret", "secret")
    else:
        account_id = None
        app_id = settings.shopee_app_id
        secret = settings.shopee_app_secret
    if not app_id or not secret:
        return None

    query = (
        "mutation {\n"
        f'  generateShortLink(input: {{ originUrl: "{url}" }}) {{\n'
        "    shortLink\n"
        "  }\n"
        "}"
    )
    payload_obj = {"query": query}
    payload = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)
    ts = int(time.time())
    sig = _shopee_sign(app_id, secret, ts, payload)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={app_id}, Timestamp={ts}, Signature={sig}",
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(SHOPEE_API, content=payload.encode("utf-8"), headers=headers)
            if resp.status_code in {401, 403} and account_id is not None:
                mark_account_credentials_invalid(
                    account_id,
                    f"HTTP {resp.status_code}",
                    bot_id=runtime.id if runtime else None,
                )
            resp.raise_for_status()
            data = resp.json()
        if data.get("errors"):
            logger.error(f"[afiliado] Shopee shortLink: {data['errors']}")
            return None
        short = ((data.get("data") or {}).get("generateShortLink") or {}).get("shortLink")
        return short if short else None
    except Exception as e:
        logger.error(f"[afiliado] Shopee shortLink falhou: {e}")
        return None


def garantir_afiliado(oferta_loja: str, url: str) -> str:
    """Retorna URL afiliada quando possível; senão a original (com log)."""
    loja = (oferta_loja or "").lower()
    if "mercado" in loja:
        convertida = converter_mercadolivre(url)
        if convertida:
            return convertida
        logger.warning("[afiliado] MELI sem conversão — enviando URL original")
        return url
    if "shopee" in loja:
        convertida = converter_shopee(url)
        if convertida:
            return convertida
        # offerLink da API já costuma ser afiliado
        return url
    return url
