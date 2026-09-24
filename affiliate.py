"""Conversão de URLs para links de afiliado.

- Shopee: productOfferV2 / shopeeOfferV2 já entregam `offerLink` com tracking.
  Se cair um link cru, tentamos `generateShortLink`.
- Mercado Livre: endpoint interno createLink (tag + cookie de sessão).
"""
from __future__ import annotations

import httpx

from config import settings
from http_headers import BROWSER_USER_AGENT
from log_safe import safe_log_text
from logger import logger
from shopee_api import generate_short_link

ML_CREATE_LINK = "https://www.mercadolivre.com.br/affiliate-program/api/v2/affiliates/createLink"
ML_LINKBUILDER = "https://www.mercadolivre.com.br/afiliados/linkbuilder"


def _cookie_value(cookie: str, name: str) -> str | None:
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith(f"{name}="):
            return part.split("=", 1)[1]
    return None


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
        "user-agent": BROWSER_USER_AGENT,
        "cookie": cookie,
    }
    if csrf:
        headers["x-csrf-token"] = csrf

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            try:
                client.get(ML_LINKBUILDER, headers={"cookie": cookie, "user-agent": BROWSER_USER_AGENT})
            except httpx.HTTPError:
                pass

            resp = client.post(ML_CREATE_LINK, headers=headers, json={"urls": [url], "tag": tag})
            if resp.status_code >= 400:
                logger.error(
                    f"[afiliado] MELI createLink HTTP {resp.status_code}: "
                    f"{safe_log_text(resp.text, 200)}"
                )
                return None
            data = resp.json()
    except httpx.HTTPError as e:
        logger.error(f"[afiliado] MELI createLink falhou: {e}")
        return None
    except Exception as e:
        logger.error(f"[afiliado] MELI createLink falhou: {e}")
        return None

    convertida = _extrair_url_afiliada(data)
    if convertida:
        logger.info(f"[afiliado] MELI convertida: {convertida}")
        return convertida
    logger.error(f"[afiliado] MELI createLink resposta inesperada: {safe_log_text(str(data), 240)}")
    return None


def converter_shopee(url: str) -> str | None:
    if _ja_parece_afiliado_shopee(url):
        return url
    if not settings.shopee_app_id or not settings.shopee_app_secret:
        return None

    try:
        with httpx.Client(timeout=20.0) as client:
            return generate_short_link(client, url)
    except httpx.HTTPError as e:
        logger.error(f"[afiliado] Shopee shortLink falhou: {e}")
        return None
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
        return url
    return url
