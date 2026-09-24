"""Fonte: Shopee BR — API oficial de Afiliados (GraphQL + HMAC-SHA256).

Requer `SHOPEE_APP_ID` e `SHOPEE_APP_SECRET` no `.env` (Open API do painel
de afiliados). Sem credenciais, a fonte é pulada com aviso.

Busca ordenada por mais recentes (sortType=1), não por mais vendidos — assim
priorizamos oferta quente em vez de catálogo antigo com estoque parado.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from uuid import UUID

import httpx
from loguru import logger

from core.config_provider import bot_runtime_atual, load_filtros_runtime as load_filtros
from core.credentials import mark_account_credentials_invalid, runtime_account_credentials
from core.platforms.base import OfertaCapturada, Scraper

API_URL = "https://open-api.affiliate.shopee.com.br/graphql"

# 1 = mais recentes | 2 = mais vendidos (catálogo antigo)
_SORT_MAIS_RECENTES = 1


def _assinar(app_id: str, secret: str, timestamp: int, payload: str) -> str:
    raw = f"{app_id}{timestamp}{payload}{secret}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _preco_float(valor) -> float | None:
    if valor is None:
        return None
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _desconto_pct(valor) -> float | None:
    d = _preco_float(valor)
    if d is None:
        return None
    if 0 < d <= 1:
        return round(d * 100, 1)
    return round(d, 1)


def _ts_para_dt(valor) -> datetime | None:
    if valor is None:
        return None
    try:
        ts = int(valor)
        if ts <= 0:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def shopee_app_credentials(config: dict, values: dict[str, str]) -> tuple[str, str]:
    """(app_id, app_secret) de uma conta Shopee: app_id em config, segredo cifrado."""
    app_id = str(
        config.get("app_id")
        or config.get("affiliate_id")
        or config.get("external_id")
        or values.get("app_id")
        or values.get("api_key")
        or ""
    )
    secret = next((values[key] for key in ("app_secret", "secret") if values.get(key)), "")
    return app_id, secret


def credenciais_shopee_do_bot() -> tuple[UUID | None, str, str]:
    """(conta, app_id, app_secret) da conta Shopee vinculada ao bot atual.

    Só o dashboard fornece credencial (ADR-020): sem bot ou sem conta Shopee
    ativa vinculada, devolve vazio e a Shopee fica de fora do ciclo.
    """
    runtime = bot_runtime_atual()
    if runtime is None or not runtime.account_ids:
        return None, "", ""
    account = runtime_account_credentials(runtime.account_ids, "shopee")
    if account is None:
        return None, "", ""
    account_id, config, values = account
    return (account_id, *shopee_app_credentials(config, values))


class ShopeeScraper(Scraper):
    nome_fonte = "Shopee"
    _avisou_sem_credenciais = False
    _runtime_account_id = None
    _runtime_app_id = ""
    _runtime_secret = ""

    def _load_auth(self) -> tuple[str, str]:
        self._runtime_account_id, app_id, secret = credenciais_shopee_do_bot()
        return app_id, secret

    def _termos_busca(self) -> list[str]:
        filtros = load_filtros()
        return (
            filtros.get("termos_busca")
            or filtros.get("palavras_chave")
            or filtros.get("categorias")
            or ["oferta"]
        )

    def _graphql(self, client: httpx.Client, query: str) -> dict:
        app_id = self._runtime_app_id
        secret = self._runtime_secret
        payload_obj = {"query": query}
        payload = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)
        timestamp = int(time.time())
        signature = _assinar(app_id, secret, timestamp, payload)
        headers = {
            "Content-Type": "application/json",
            "Authorization": (
                f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}"
            ),
        }
        resp = client.post(API_URL, content=payload.encode("utf-8"), headers=headers)
        if resp.status_code in {401, 403} and self._runtime_account_id is not None:
            runtime = bot_runtime_atual()
            mark_account_credentials_invalid(
                self._runtime_account_id,
                f"HTTP {resp.status_code}",
                bot_id=runtime.id if runtime else None,
            )
        resp.raise_for_status()
        dados = resp.json()
        if dados.get("errors"):
            msgs = "; ".join(
                e.get("message") or e.get("extensions", {}).get("message") or str(e)
                for e in dados["errors"]
            )
            raise RuntimeError(f"GraphQL Shopee: {msgs}")
        return dados.get("data") or {}

    def buscar(self) -> list[OfertaCapturada]:
        self._runtime_app_id, self._runtime_secret = self._load_auth()
        if not self._runtime_app_id or not self._runtime_secret:
            if not ShopeeScraper._avisou_sem_credenciais:
                logger.warning(
                    "[Shopee] SHOPEE_APP_ID/SECRET não configurados — fonte pulada. "
                    "Peça acesso Open API no painel de afiliados Shopee."
                )
                ShopeeScraper._avisou_sem_credenciais = True
            return []

        ofertas: list[OfertaCapturada] = []
        with httpx.Client(timeout=self.timeout) as client:
            if load_filtros().get("aceitar_campanhas", False):
                ofertas.extend(self._buscar_campanhas(client))
            for termo in self._termos_busca():
                keyword = termo.replace('"', '\\"')
                query = f"""
                {{
                  productOfferV2(
                    keyword: "{keyword}",
                    listType: 0,
                    sortType: {_SORT_MAIS_RECENTES},
                    page: 1,
                    limit: 20
                  ) {{
                    nodes {{
                      itemId
                      productName
                      productLink
                      offerLink
                      imageUrl
                      priceMin
                      priceMax
                      priceDiscountRate
                      shopName
                      sales
                      periodStartTime
                    }}
                  }}
                }}
                """
                try:
                    data = self._graphql(client, query)
                except Exception as e:
                    logger.warning(f"[Shopee] falha na busca '{termo}': {e}")
                    continue

                nodes = (data.get("productOfferV2") or {}).get("nodes") or []
                for item in nodes:
                    oferta = self._parse_item(item)
                    if oferta:
                        ofertas.append(oferta)
        logger.info(f"[Shopee] {len(ofertas)} ofertas capturadas.")
        return ofertas

    def _buscar_campanhas(self, client: httpx.Client) -> list[OfertaCapturada]:
        query = """
        {
          shopeeOfferV2(sortType: 1, page: 1, limit: 15) {
            nodes {
              offerName
              offerLink
              originalLink
              imageUrl
              commissionRate
              offerType
              periodStartTime
            }
          }
        }
        """
        try:
            data = self._graphql(client, query)
        except Exception as e:
            logger.warning(f"[Shopee] falha ao buscar campanhas: {e}")
            return []

        out: list[OfertaCapturada] = []
        for item in (data.get("shopeeOfferV2") or {}).get("nodes") or []:
            url = item.get("offerLink") or item.get("originalLink")
            nome = item.get("offerName")
            if not url or not nome:
                continue
            out.append(
                OfertaCapturada(
                    nome=f"[CAMPANHA] {nome}",
                    preco=0.0,
                    desconto=None,
                    loja="Shopee",
                    url=url,
                    imagem=item.get("imageUrl"),
                    categoria="campanha",
                    sku=f"campanha:{hash(url) & 0xFFFFFFFF:x}",
                    oferta_desde=_ts_para_dt(item.get("periodStartTime")),
                )
            )
        return out

    def _parse_item(self, item: dict) -> OfertaCapturada | None:
        preco = _preco_float(item.get("priceMin") if item.get("priceMin") is not None else item.get("priceMax"))
        if preco is None:
            return None

        url = item.get("offerLink") or item.get("productLink")
        if not url:
            return None

        desconto = _desconto_pct(item.get("priceDiscountRate"))
        preco_anterior = None
        if desconto and desconto > 0 and desconto < 100:
            preco_anterior = round(preco / (1 - desconto / 100), 2)

        vendas = None
        if item.get("sales") is not None:
            try:
                vendas = int(item["sales"])
            except (TypeError, ValueError):
                vendas = None

        return OfertaCapturada(
            nome=item.get("productName") or "",
            preco=preco,
            preco_anterior=preco_anterior,
            desconto=desconto,
            loja="Shopee",
            url=url,
            product_url=item.get("productLink"),
            imagem=item.get("imageUrl"),
            sku=str(item["itemId"]) if item.get("itemId") is not None else None,
            vendas=vendas,
            oferta_desde=_ts_para_dt(item.get("periodStartTime")),
        )
