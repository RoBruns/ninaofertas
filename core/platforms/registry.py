"""Registry dos testes baratos de autenticacao por plataforma."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from core.platforms.affiliate import (
    ML_CREATE_LINK,
    _cookie_value,
    _create_link_url_recusada,
    _extrair_url_afiliada,
)
from core.http_headers import BROWSER_USER_AGENT
from core.platforms.amazon import normalizar_tag_amazon
from core.platforms.shopee_api import graphql_request

TEST_TIMEOUT_SECONDS = 5.0
# Só provoca o createLink. O anúncio não precisa continuar existindo:
# recusa da URL (saiu do ar, fora do programa) ainda é sessão válida.
# 401/403 é o que marca o cookie inválido.
TEST_PRODUCT_URL = "https://www.mercadolivre.com.br/apple-iphone-15-128-gb-preto/p/MLB1027172669"


class PlatformNotIntegratedError(Exception):
    pass


class PlatformConfigurationError(Exception):
    pass


@dataclass(frozen=True)
class CredentialTestResult:
    ok: bool
    message: str
    invalid: bool = False
    network_error: bool = False


class PlatformClient(Protocol):
    def test_credentials(
        self,
        credentials: dict[str, str],
        config: dict[str, Any],
    ) -> CredentialTestResult: ...


def _http_failure(response: httpx.Response, operation: str) -> CredentialTestResult:
    if response.status_code in {401, 403}:
        return CredentialTestResult(False, f"Credencial recusada ({operation})", invalid=True)
    return CredentialTestResult(False, f"Plataforma respondeu HTTP {response.status_code}")


class ShopeeClient:
    def test_credentials(
        self,
        credentials: dict[str, str],
        config: dict[str, Any],
    ) -> CredentialTestResult:
        app_id = str(config.get("app_id") or credentials.get("app_id") or credentials.get("api_key") or "")
        secret = credentials.get("app_secret") or credentials.get("secret")
        if not app_id or not secret:
            raise PlatformConfigurationError(
                "Shopee requer app_id (config ou credencial) e app_secret"
            )
        query = "{ productOfferV2(keyword: \"teste\", page: 1, limit: 1) { nodes { itemId } } }"
        try:
            with httpx.Client(timeout=TEST_TIMEOUT_SECONDS) as client:
                graphql_request(
                    client,
                    query,
                    app_id=app_id,
                    secret=secret,
                )
        except (httpx.TimeoutException, httpx.NetworkError):
            return CredentialTestResult(
                False,
                "Não foi possível conectar a Shopee",
                network_error=True,
            )
        except httpx.HTTPStatusError as exc:
            return _http_failure(exc.response, "GraphQL Shopee")
        except (RuntimeError, ValueError) as exc:
            error = str(exc).casefold()
            invalid = any(
                term in error for term in ("unauthor", "forbidden", "signature", "credential")
            )
            return CredentialTestResult(
                False,
                "Credencial recusada (GraphQL Shopee)" if invalid else "Consulta GraphQL recusada",
                invalid=invalid,
            )
        return CredentialTestResult(True, "Credencial Shopee válida")


class MercadoLivreClient:
    def test_credentials(
        self,
        credentials: dict[str, str],
        config: dict[str, Any],
    ) -> CredentialTestResult:
        cookie = credentials.get("cookie")
        tag = str(config.get("affiliate_tag") or "")
        if not cookie or not tag:
            raise PlatformConfigurationError(
                "Mercado Livre requer cookie e config.affiliate_tag"
            )
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "origin": "https://www.mercadolivre.com.br",
            "referer": "https://www.mercadolivre.com.br/afiliados/linkbuilder",
            "user-agent": BROWSER_USER_AGENT,
            "cookie": cookie,
        }
        csrf = _cookie_value(cookie, "_csrf") or _cookie_value(cookie, "csrf")
        if csrf:
            headers["x-csrf-token"] = csrf
        try:
            with httpx.Client(timeout=TEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
                response = client.post(
                    ML_CREATE_LINK,
                    headers=headers,
                    json={"urls": [TEST_PRODUCT_URL], "tag": tag},
                )
        except (httpx.TimeoutException, httpx.NetworkError):
            return CredentialTestResult(
                False,
                "Não foi possível conectar ao Mercado Livre",
                network_error=True,
            )
        if response.status_code >= 400:
            return _http_failure(response, "createLink")
        try:
            data = response.json()
        except ValueError:
            data = None
        generated_url = _extrair_url_afiliada(data) if data is not None else None
        if generated_url is not None:
            return CredentialTestResult(True, "Credencial Mercado Livre válida")
        # HTTP 200: a sessão entrou. Recusa do anúncio (sumiu, condição, error 111)
        # não invalida o cookie — o produto de teste não é a credencial.
        if isinstance(data, dict) and _create_link_url_recusada(data):
            return CredentialTestResult(
                True,
                "Sessão aceita. O anúncio de teste não virou link; o cookie vale "
                "mesmo se esse produto saiu do ar.",
            )
        urls = data.get("urls") if isinstance(data, dict) else None
        motivos = [
            str(item["message"])
            for item in urls or []
            if isinstance(item, dict) and item.get("message")
        ]
        if motivos:
            return CredentialTestResult(
                False, f"Sessão aceita, mas o ML recusou o link de teste: {motivos[0]}"
            )
        return CredentialTestResult(False, "createLink retornou uma resposta inválida")


class AmazonClient:
    def test_credentials(
        self,
        credentials: dict[str, str],
        config: dict[str, Any],
    ) -> CredentialTestResult:
        rastreio = str(credentials.get("tracking_id") or config.get("tracking_id") or "")
        loja = str(config.get("store_id") or "")
        try:
            tag = normalizar_tag_amazon(rastreio)
            if loja:
                normalizar_tag_amazon(loja)
        except ValueError:
            return CredentialTestResult(
                False,
                "Use o ID da loja e o ID de rastreamento da Amazon. Os dois terminam em -20.",
                invalid=True,
            )
        return CredentialTestResult(
            True,
            f"Etiqueta aceita. Os links saem como amazon.com.br/dp/ASIN?tag={tag}",
        )


_CLIENTS: dict[str, PlatformClient] = {
    "shopee": ShopeeClient(),
    "mercadolivre": MercadoLivreClient(),
    "amazon": AmazonClient(),
}


def resolve(slug: str) -> PlatformClient:
    if slug == "aliexpress":
        raise PlatformNotIntegratedError("Teste de credencial do AliExpress ainda não integrado")
    client = _CLIENTS.get(slug)
    if client is None:
        raise PlatformNotIntegratedError(f"Teste de credencial de {slug} não integrado")
    return client
