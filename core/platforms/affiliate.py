"""Conversão de URLs para links de afiliado, com atribuição best-effort."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from uuid import UUID

import httpx
from loguru import logger

from core.config_provider import bot_runtime_atual, registrar_evento_runtime
from core.credentials import mark_account_credentials_invalid, runtime_account_credentials
from core.http_headers import BROWSER_USER_AGENT
from core.log_safe import safe_log_text
from core.platforms.amazon import asin_amazon, normalizar_tag_amazon, url_afiliada_amazon
from core.platforms.magalu import normalizar_loja_magalu, url_afiliada_magalu
from core.platforms.shopee import shopee_app_credentials
from core.platforms.shopee_api import generate_short_link

ML_CREATE_LINK = "https://www.mercadolivre.com.br/affiliate-program/api/v2/affiliates/createLink"
ML_LINKBUILDER = "https://www.mercadolivre.com.br/afiliados/linkbuilder"
_ML_PRODUCT_RE = re.compile(
    r"https://(?:www\.)?mercadolivre\.com\.br/[^\s\"'<>]+?/p/MLB\d+",
    re.IGNORECASE,
)
_ML_KEEP_QUERY = frozenset({"pdp_filters", "wid"})
_aviso_createlink_neste_ciclo = False
_plataformas_bloqueadas_ciclo: set[str] = set()
_cache_links_ciclo: dict[tuple[str, str], AffiliateLink] = {}
_cache_produto_ml: dict[str, str | None] = {}


def reset_aviso_ciclo() -> None:
    """Limpa aviso, bloqueio e cache de links no início de cada ciclo do bot."""
    global (
        _aviso_createlink_neste_ciclo,
        _plataformas_bloqueadas_ciclo,
        _cache_links_ciclo,
        _cache_produto_ml,
    )
    _aviso_createlink_neste_ciclo = False
    _plataformas_bloqueadas_ciclo = set()
    _cache_links_ciclo = {}
    _cache_produto_ml = {}


def plataforma_bloqueada_no_ciclo(slug: str) -> bool:
    """True após 401/403: o ciclo não tenta de novo createLink nessa plataforma."""
    return slug in _plataformas_bloqueadas_ciclo


def _bloquear_plataforma(slug: str) -> None:
    _plataformas_bloqueadas_ciclo.add(slug)


def _avisar_createlink(mensagem: str) -> None:
    global _aviso_createlink_neste_ciclo
    if not _aviso_createlink_neste_ciclo:
        _aviso_createlink_neste_ciclo = True
        logger.warning(mensagem)


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


def _host_ml(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _eh_url_produto_ml(url: str) -> bool:
    """PDP real (/p/MLB… ou produto.mercadolivre), não perfil /social/."""
    host = _host_ml(url)
    path = (urlparse(url).path or "").lower()
    if host == "produto.mercadolivre.com.br":
        return "mlb" in path
    if host not in {"mercadolivre.com.br", "mercadolibre.com", "mercadolibre.com.br"}:
        return False
    if "/social/" in path:
        return False
    return bool(re.search(r"/p/mlb\d+", path)) or bool(re.search(r"/mlb-?\d+", path))


def _precisa_expandir_ml(url: str) -> bool:
    """Link de afiliado de terceiros: curto, /sec/, ou landing /social/."""
    lowered = (url or "").lower()
    host = _host_ml(url)
    path = (urlparse(url).path or "").lower()
    if host in {"meli.la", "click1.mercadolivre.com.br"}:
        return True
    if "/sec/" in path:
        return True
    if host.endswith("mercadolivre.com.br") and "/social/" in path:
        return True
    if _eh_url_produto_ml(url) and any(
        marker in lowered for marker in ("matt_tool=", "matt_word=", "matt_tool_id=")
    ):
        # Já é PDP com tracking alheio — só limpar, sem fetch.
        return False
    return False


def _limpar_url_produto_ml(url: str) -> str:
    """Remove tracking de afiliado alheio; mantém wid/pdp_filters do item."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=False)
    kept = {key: vals[0] for key, vals in query.items() if key in _ML_KEEP_QUERY and vals}
    clean = parsed._replace(
        scheme="https",
        netloc=parsed.netloc or "www.mercadolivre.com.br",
        query=urlencode(kept) if kept else "",
        fragment="",
    )
    return urlunparse(clean)


def _extrair_produto_do_html_social(html: str) -> str | None:
    """No perfil /social/?ref=… o produto compartilhado vem primeiro no HTML."""
    match = _ML_PRODUCT_RE.search(html or "")
    if not match:
        return None
    return _limpar_url_produto_ml(match.group(0).replace("&amp;", "&"))


def resolver_url_produto_ml(url: str) -> str | None:
    """meli.la / social → URL pura do produto; PDP com matt_* → limpa.

    Links de afiliado do ML caem em /social/{tag}?ref=…; o createLink só
    aceita bem a PDP (/p/MLB…). Sem reaproveitar meli.la de terceiros.
    """
    alvo = (url or "").strip()
    if not alvo.startswith("http"):
        return None
    if alvo in _cache_produto_ml:
        return _cache_produto_ml[alvo]
    if _eh_url_produto_ml(alvo):
        limpa = _limpar_url_produto_ml(alvo)
        _cache_produto_ml[alvo] = limpa
        return limpa
    if not _precisa_expandir_ml(alvo):
        _cache_produto_ml[alvo] = alvo
        return alvo

    produto: str | None = None
    try:
        with httpx.Client(
            timeout=20.0,
            follow_redirects=True,
            headers={
                "user-agent": BROWSER_USER_AGENT,
                "accept-language": "pt-BR,pt;q=0.9",
                "accept": "text/html,application/xhtml+xml",
            },
        ) as client:
            response = client.get(alvo)
    except httpx.HTTPError as exc:
        logger.info(f"[afiliado] MELI expandir link falhou: {safe_log_text(exc)}")
        _cache_produto_ml[alvo] = None
        return None

    final = str(response.url)
    if _eh_url_produto_ml(final):
        produto = _limpar_url_produto_ml(final)
    else:
        # /social/?ref=… (ou HTML pós-meli.la): o produto compartilhado vem primeiro.
        produto = _extrair_produto_do_html_social(response.text[:500_000])
        if not produto:
            path = (urlparse(final).path or "").lower()
            logger.info(
                f"[afiliado] MELI sem PDP após expandir "
                f"(final=…{path[-40:] if path else '?'})"
            )

    _cache_produto_ml[alvo] = produto
    if produto:
        logger.info(f"[afiliado] MELI produto resolvido: {produto}")
    return produto


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
        _avisar_createlink("[afiliado] MELI sem TAG/COOKIE — createLink não roda neste ciclo.")
        return None

    # Nunca reaproveitar meli.la/social de outro afiliado: resolve a PDP pura.
    produto = resolver_url_produto_ml(url)
    if not produto:
        _avisar_createlink(
            "[afiliado] MELI não achou URL de produto para converter (meli.la/social?)."
        )
        return None

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
                json={"urls": [produto], "tag": tag},
            )
            if response.status_code >= 400:
                if response.status_code in {401, 403} and auth.account_id is not None:
                    mark_account_credentials_invalid(
                        auth.account_id,
                        f"HTTP {response.status_code}",
                        bot_id=runtime.id if runtime else None,
                    )
                    _bloquear_plataforma("mercadolivre")
                    _avisar_createlink(
                        f"[afiliado] MELI createLink HTTP {response.status_code} — cookie da conta expirou; "
                        "renove no dashboard → Contas."
                    )
                else:
                    _avisar_createlink(f"[afiliado] MELI createLink HTTP {response.status_code}.")
                return None
            data = response.json()
    except Exception as exc:
        _avisar_createlink(f"[afiliado] MELI createLink falhou: {safe_log_text(exc)}")
        return None

    if _create_link_url_recusada(data):
        # error_code 111 = URL fora do programa; cookie continua válido.
        _avisar_createlink(
            "[afiliado] MELI createLink recusou URL (não afiliável / error 111)."
        )
        return None

    converted = _extrair_url_afiliada(data)
    if converted:
        logger.info(f"[afiliado] MELI convertida: {converted}")
        return converted
    _avisar_createlink(
        f"[afiliado] MELI createLink resposta inesperada: {safe_log_text(data, 240)}"
    )
    return None


def _create_link_url_recusada(data: Any) -> bool:
    """True quando o createLink HTTP 200 recusa a URL (ex.: error_code 111)."""
    if not isinstance(data, dict):
        return False
    urls = data.get("urls")
    if isinstance(urls, list):
        for item in urls:
            if not isinstance(item, dict):
                continue
            code = item.get("error_code")
            msg = str(item.get("message") or "").lower()
            if code == 111 or "not allowed" in msg or "condition is unknown" in msg:
                return True
    if data.get("error_code") == 111:
        return True
    if int(data.get("total_error") or 0) > 0 and int(data.get("total_success") or 0) == 0:
        return True
    return False


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
            _bloquear_plataforma("shopee")
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
        cache_key = ("mercadolivre", url)
        cached = _cache_links_ciclo.get(cache_key)
        if cached is not None:
            return cached
        if plataforma_bloqueada_no_ciclo("mercadolivre"):
            resultado = AffiliateLink(url)
            _cache_links_ciclo[cache_key] = resultado
            return resultado
        runtime, auth = _ml_auth()
        account_tag = auth.account_tag
        bot_tag = runtime.settings.attribution.ml_tag if runtime is not None else None
        tag = bot_tag or account_tag
        converted = _converter_mercadolivre_com_tag(url, tag, auth, runtime)
        if converted:
            resultado = AffiliateLink(converted, f"ml:{tag}")
            _cache_links_ciclo[cache_key] = resultado
            return resultado
        if bot_tag and bot_tag != account_tag and not plataforma_bloqueada_no_ciclo("mercadolivre"):
            registrar_evento_runtime(
                "attribution_link_failed",
                "Falha ao gerar link atribuido do Mercado Livre; usando fallback afiliado",
                detail={"platform": "mercadolivre", "tag": bot_tag},
                level="warning",
            )
            fallback = _converter_mercadolivre_com_tag(url, account_tag, auth, runtime)
            if fallback:
                resultado = AffiliateLink(fallback)
                _cache_links_ciclo[cache_key] = resultado
                return resultado
        resultado = AffiliateLink(url)
        _cache_links_ciclo[cache_key] = resultado
        return resultado

    if "shopee" in loja:
        if plataforma_bloqueada_no_ciclo("shopee"):
            return AffiliateLink(url)
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
                "Falha ao gerar link atribuido da Shopee; oferta pulada",
                detail={"platform": "shopee", "sub_ids": [bot_sub, group_sub]},
                level="warning",
            )
            # Sem shortLink nosso: não reenviar offerLink de terceiro como se fosse nosso.
            return AffiliateLink(url)
        return AffiliateLink(url)

    if "magalu" in loja or "magazine luiza" in loja:
        cache_key = ("magalu", url)
        cached = _cache_links_ciclo.get(cache_key)
        if cached is not None:
            return cached
        loja_slug = _loja_magalu()
        convertida = url_afiliada_magalu(url, loja_slug) if loja_slug else None
        resultado = AffiliateLink(convertida or url, f"magalu:{loja_slug}" if convertida else None)
        _cache_links_ciclo[cache_key] = resultado
        return resultado

    if "amazon" in loja:
        cache_key = ("amazon", url)
        cached = _cache_links_ciclo.get(cache_key)
        if cached is not None:
            return cached
        tag = _tag_amazon()
        convertida = url_afiliada_amazon(url, tag) if tag else None
        resultado = AffiliateLink(convertida or url, f"amazon:{tag}" if convertida else None)
        _cache_links_ciclo[cache_key] = resultado
        return resultado
    return AffiliateLink(url)


def _loja_magalu() -> str:
    """Slug da loja do Magazine Você da conta do bot, ou vazio se não houver."""
    _runtime, account = _runtime_auth("magalu")
    if account is None:
        return ""
    _account_id, config, values = account
    bruto = str(values.get("store_tag") or config.get("store_slug") or "")
    try:
        return normalizar_loja_magalu(bruto)
    except ValueError:
        return ""


def _tag_amazon() -> str:
    """ID de rastreamento da conta. Sem ele, o link da Amazon não sai."""
    _runtime, account = _runtime_auth("amazon")
    if account is None:
        return ""
    _account_id, config, values = account
    bruto = str(
        values.get("tracking_id")
        or config.get("tracking_id")
        or config.get("store_id")
        or ""
    )
    try:
        return normalizar_tag_amazon(bruto)
    except ValueError:
        return ""


def link_rastreado(loja: str, url: str) -> bool:
    """True quando a URL contem a marcacao de comissao da plataforma."""
    nome = (loja or "").lower()
    if "mercado" in nome:
        return _ja_parece_afiliado_ml(url)
    if "shopee" in nome:
        return _ja_parece_afiliado_shopee(url)
    if "magalu" in nome or "magazine luiza" in nome:
        return _magalu_da_loja(url, _loja_magalu())
    if "amazon" in nome:
        return _amazon_da_tag(url, _tag_amazon())
    return True


def _magalu_da_loja(url: str, loja: str) -> bool:
    if not loja:
        return False
    parsed = urlparse(url or "")
    host = parsed.netloc.lower().removeprefix("www.")
    partes = [parte for parte in parsed.path.split("/") if parte]
    return host == "magazinevoce.com.br" and bool(partes) and partes[0].lower() == loja


def _amazon_da_tag(url: str, tag: str) -> bool:
    if not tag:
        return False
    parsed = urlparse(url or "")
    host = parsed.netloc.lower().removeprefix("www.")
    if host != "amazon.com.br":
        return False
    if asin_amazon(url) is None:
        return False
    marcas = [item.lower() for item in parse_qs(parsed.query).get("tag", [])]
    return tag.lower() in marcas


__all__ = [
    "AffiliateLink",
    "converter_mercadolivre",
    "converter_shopee",
    "garantir_afiliado",
    "link_rastreado",
    "plataforma_bloqueada_no_ciclo",
    "resolver_url_produto_ml",
    "reset_aviso_ciclo",
]
