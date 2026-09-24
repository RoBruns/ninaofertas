"""Registry dos testes baratos de autenticacao por plataforma."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from core.platforms.affiliate import (
    ML_CREATE_LINK,
    _cookie_value,
    _extrair_url_afiliada,
)
from core.platforms.shopee import API_URL, _assinar

TEST_TIMEOUT_SECONDS = 5.0
# Produto real de catálogo: com um id inventado o ML responde 200 com
# "URL not allowed in affiliates program" e o teste reprovava cookie válido.
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
        payload = json.dumps({"query": query}, separators=(",", ":"), ensure_ascii=False)
        timestamp = int(time.time())
        signature = _assinar(app_id, secret, timestamp, payload)
        headers = {
            "Content-Type": "application/json",
            "Authorization": (
                f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}"
            ),
        }
        try:
            with httpx.Client(timeout=TEST_TIMEOUT_SECONDS) as client:
                response = client.post(
                    API_URL,
                    content=payload.encode("utf-8"),
                    headers=headers,
                )
        except (httpx.TimeoutException, httpx.NetworkError):
            return CredentialTestResult(
                False,
                "Nao foi possivel conectar a Shopee",
                network_error=True,
            )
        if response.status_code >= 400:
            return _http_failure(response, "GraphQL Shopee")
        try:
            body = response.json()
        except ValueError:
            return CredentialTestResult(False, "Resposta invalida da Shopee")
        if body.get("errors"):
            errors = json.dumps(body["errors"], ensure_ascii=False).casefold()
            invalid = any(term in errors for term in ("unauthor", "forbidden", "signature", "credential"))
            return CredentialTestResult(
                False,
                "Credencial recusada (GraphQL Shopee)" if invalid else "Consulta GraphQL recusada",
                invalid=invalid,
            )
        return CredentialTestResult(True, "Credencial Shopee valida")


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
            "user-agent": "Mozilla/5.0 NinaOfertas credential-check",
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
                "Nao foi possivel conectar ao Mercado Livre",
                network_error=True,
            )
        if response.status_code >= 400:
            return _http_failure(response, "createLink")
        try:
            data = response.json()
        except ValueError:
            data = None
        generated_url = _extrair_url_afiliada(data) if data is not None else None
        if generated_url is None:
            # Sessão recusada é 401/403 (tratado acima); aqui o ML aceitou o cookie
            # e recusou o link — repassa o motivo dele em vez de "resposta invalida".
            urls = data.get("urls") if isinstance(data, dict) else None
            motivos = [
                str(item["message"])
                for item in urls or []
                if isinstance(item, dict) and item.get("message")
            ]
            if motivos:
                return CredentialTestResult(
                    False, f"Sessao aceita, mas o ML recusou o link de teste: {motivos[0]}"
                )
            return CredentialTestResult(False, "createLink retornou uma resposta invalida")
        return CredentialTestResult(True, "Credencial Mercado Livre valida")


_CLIENTS: dict[str, PlatformClient] = {
    "shopee": ShopeeClient(),
    "mercadolivre": MercadoLivreClient(),
}


def resolve(slug: str) -> PlatformClient:
    if slug == "aliexpress":
        raise PlatformNotIntegratedError("Teste de credencial do AliExpress ainda nao integrado")
    client = _CLIENTS.get(slug)
    if client is None:
        raise PlatformNotIntegratedError(f"Teste de credencial de {slug} nao integrado")
    return client
