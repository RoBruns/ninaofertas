"""Conversão de URLs para links de afiliado, com atribuição best-effort."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from loguru import logger

from core.config_provider import bot_runtime_atual, registrar_evento_runtime
from core.credentials import mark_account_credentials_invalid, runtime_account_credentials
from core.http_headers import BROWSER_USER_AGENT
from core.log_safe import safe_log_text
from core.platforms.shopee import shopee_app_credentials
from core.platforms.shopee_api import generate_short_link

ML_CREATE_LINK = "https://www.mercadolivre.com.br/affiliate-program/api/v2/affiliates/createLink"
ML_LINKBUILDER = "https://www.mercadolivre.com.br/afiliados/linkbuilder"


class AffiliateLink(str):
    """String compatível com o contrato legado, acrescida do sub_id persistível."""

    sub_id: str | None

    def __new__(cls, value: str, sub_id: str | None = None):
        instance = super().__new__(cls, value)
        instance.sub_id = sub_id
        return instance


@dataclass(frozen=True)
class _MLAuth:
    account_id: UUID | None
    account_tag: str
    cookie: str


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


def _ja_parece_afiliado_ml(url: str) -> bool:
    lowered = url.lower()
    return any(
        marker in lowered
        for marker in ("meli.la/", "matt_tool=", "matt_word=", "/sec/", "click1.mercadolivre")
    )


def _extrair_url_afiliada(data: Any) -> str | None:
    """createLink devolve snake_case: urls[].short_url (ex.: https://meli.la/xxxx)."""
    keys = ("short_url", "shortUrl", "affiliateLink", "affineLink", "url", "link")
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.startswith("http") and key != "text":
                if "meli.la/" in value.lower() or key in (
                    "short_url",
                    "shortUrl",
                    "affiliateLink",
                ):
                    return value
        if isinstance(data.get("urls"), list) and data["urls"]:
            return _extrair_url_afiliada(data["urls"][0])
        text = data.get("text")
        if isinstance(text, str) and "meli.la/" in text:
            for part in text.split():
                if "meli.la/" in part and part.startswith("http"):
                    return part.strip()
    return None


def _ja_parece_afiliado_shopee(url: str) -> bool:
    lowered = url.lower()
    return any(
        marker in lowered
        for marker in ("s.shopee.com.br", "shope.ee/", "an_re=", "utm_content=")
    )


def _ml_auth() -> tuple[Any, _MLAuth]:
    """Tag e cookie da conta ML vinculada ao bot; nunca da env (ADR-020)."""
    runtime, account = _runtime_auth("mercadolivre")
    if account is None:
        logger.warning("[afiliado] MELI sem conta/credencial vinculada ao bot")
        return runtime, _MLAuth(None, "", "")
    account_id, config, values = account
    tag = str(config.get("affiliate_tag") or config.get("tag") or "")
    cookie = _credential_value(values, "cookie", "affiliate_cookie")
    return runtime, _MLAuth(account_id, tag, cookie)


def _converter_mercadolivre_com_tag(
    url: str, tag: str, auth: _MLAuth, runtime: Any
) -> str | None:
    if not tag or not auth.cookie:
        logger.warning("[afiliado] MELI sem TAG/COOKIE — mantendo URL original")
        return None
    if _ja_parece_afiliado_ml(url):
        return url

    csrf = _cookie_value(auth.cookie, "_csrf") or _cookie_value(auth.cookie, "csrf") or ""
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": "https://www.mercadolivre.com.br",
        "referer": ML_LINKBUILDER,
        "user-agent": BROWSER_USER_AGENT,
        "cookie": auth.cookie,
    }
    if csrf:
        headers["x-csrf-token"] = csrf

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            try:
                client.get(
                    ML_LINKBUILDER,
                    headers={"cookie": auth.cookie, "user-agent": BROWSER_USER_AGENT},
                )
            except httpx.HTTPError:
                pass
            response = client.post(
                ML_CREATE_LINK,
                headers=headers,
                json={"urls": [url], "tag": tag},
            )
            if response.status_code >= 400:
                if response.status_code in {401, 403} and auth.account_id is not None:
                    mark_account_credentials_invalid(
                        auth.account_id,
                        f"HTTP {response.status_code}",
                        bot_id=runtime.id if runtime else None,
                    )
                logger.error(
                    f"[afiliado] MELI createLink HTTP {response.status_code}: "
                    f"{safe_log_text(response.text, 200)}"
                )
                return None
            data = response.json()
    except Exception as exc:
        logger.error(f"[afiliado] MELI createLink falhou: {safe_log_text(exc)}")
        return None

    converted = _extrair_url_afiliada(data)
    if converted:
        logger.info(f"[afiliado] MELI convertida: {converted}")
        return converted
    logger.error(
        f"[afiliado] MELI createLink resposta inesperada: {safe_log_text(data, 240)}"
    )
    return None


def converter_mercadolivre(url: str) -> str | None:
    runtime, auth = _ml_auth()
    bot_tag = runtime.settings.attribution.ml_tag if runtime is not None else None
    return _converter_mercadolivre_com_tag(url, bot_tag or auth.account_tag, auth, runtime)


def _tracking_ids(bot_id: UUID, group_id: UUID) -> tuple[str, str]:
    return f"b{bot_id.hex[:8]}", f"g{group_id.hex[:8]}"


def converter_shopee(
    url: str,
    *,
    group_id: UUID | None = None,
    origin_url: str | None = None,
) -> str | None:
    runtime = bot_runtime_atual()
    attributed = runtime is not None and group_id is not None
    if not attributed and _ja_parece_afiliado_shopee(url):
        return url

    runtime, account = _runtime_auth("shopee")
    if account is None:
        return None
    account_id, config, values = account
    app_id, secret = shopee_app_credentials(config, values)
    if not app_id or not secret:
        return None

    sub_ids = _tracking_ids(runtime.id, group_id) if attributed else ()
    try:
        with httpx.Client(timeout=20.0) as client:
            return generate_short_link(
                client,
                origin_url or url,
                app_id=app_id,
                secret=secret,
                sub_ids=sub_ids,
            )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {401, 403} and account_id is not None:
            mark_account_credentials_invalid(
                account_id,
                f"HTTP {exc.response.status_code}",
                bot_id=runtime.id if runtime else None,
            )
        logger.error(f"[afiliado] Shopee shortLink falhou: {safe_log_text(exc)}")
        return None
    except Exception as exc:
        logger.error(f"[afiliado] Shopee shortLink falhou: {safe_log_text(exc)}")
        return None


def garantir_afiliado(
    oferta_loja: str,
    url: str,
    *,
    group_id: UUID | None = None,
    origin_url: str | None = None,
) -> AffiliateLink:
    """Mantém o retorno string legado e anexa a atribuição quando ela foi aplicada."""
    loja = (oferta_loja or "").lower()
    if "mercado" in loja:
        runtime, auth = _ml_auth()
        account_tag = auth.account_tag
        bot_tag = runtime.settings.attribution.ml_tag if runtime is not None else None
        tag = bot_tag or account_tag
        converted = _converter_mercadolivre_com_tag(url, tag, auth, runtime)
        if converted:
            return AffiliateLink(converted, f"ml:{tag}")
        if bot_tag and bot_tag != account_tag:
            registrar_evento_runtime(
                "attribution_link_failed",
                "Falha ao gerar link atribuido do Mercado Livre; usando fallback afiliado",
                detail={"platform": "mercadolivre", "tag": bot_tag},
                level="warning",
            )
            fallback = _converter_mercadolivre_com_tag(url, account_tag, auth, runtime)
            if fallback:
                return AffiliateLink(fallback)
        logger.warning("[afiliado] MELI sem conversão — enviando URL original")
        return AffiliateLink(url)

    if "shopee" in loja:
        runtime = bot_runtime_atual()
        attributed = runtime is not None and group_id is not None
        converted = converter_shopee(url, group_id=group_id, origin_url=origin_url)
        if converted:
            sub_id = None
            if attributed:
                bot_sub, group_sub = _tracking_ids(runtime.id, group_id)
                sub_id = f"shopee:{bot_sub}-{group_sub}"
            return AffiliateLink(converted, sub_id)
        if attributed:
            bot_sub, group_sub = _tracking_ids(runtime.id, group_id)
            registrar_evento_runtime(
                "attribution_link_failed",
                "Falha ao gerar link atribuido da Shopee; usando offerLink afiliado",
                detail={"platform": "shopee", "sub_ids": [bot_sub, group_sub]},
                level="warning",
            )
            return AffiliateLink(url, f"shopee:{bot_sub}-{group_sub}")
        return AffiliateLink(url)
    return AffiliateLink(url)


__all__ = [
    "AffiliateLink",
    "converter_mercadolivre",
    "converter_shopee",
    "garantir_afiliado",
]
