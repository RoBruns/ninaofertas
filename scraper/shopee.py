"""Fonte: Shopee BR — API oficial de Afiliados (GraphQL + HMAC-SHA256).

Requer `SHOPEE_APP_ID` e `SHOPEE_APP_SECRET` no `.env` (Open API do painel
de afiliados). Sem credenciais, a fonte é pulada com aviso.

Busca ordenada por mais recentes (sortType=1), não por mais vendidos — assim
priorizamos oferta quente em vez de catálogo antigo com estoque parado.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from config import load_filtros, settings
from logger import logger
from scraper.base import OfertaCapturada, Scraper
from shopee_api import escape_graphql_string, graphql_request

# 1 = mais recentes | 2 = mais vendidos (catálogo antigo)
_SORT_MAIS_RECENTES = 1


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


class ShopeeScraper(Scraper):
    nome_fonte = "Shopee"
    _avisou_sem_credenciais = False

    def _termos_busca(self) -> list[str]:
        filtros = load_filtros()
        return (
            filtros.get("termos_busca")
            or filtros.get("palavras_chave")
            or filtros.get("categorias")
            or ["oferta"]
        )

    def buscar(self) -> list[OfertaCapturada]:
        if not settings.shopee_app_id or not settings.shopee_app_secret:
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
                keyword = escape_graphql_string(termo)
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
                    data = graphql_request(client, query)
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
            data = graphql_request(client, query)
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
            imagem=item.get("imageUrl"),
            sku=str(item["itemId"]) if item.get("itemId") is not None else None,
            vendas=vendas,
            oferta_desde=_ts_para_dt(item.get("periodStartTime")),
        )
