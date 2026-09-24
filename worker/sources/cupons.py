"""Cupons de loja (Shopee voucher + alguns do MELI), não campanha aleatória."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

import httpx

from core.platforms.base import OfertaCapturada, Scraper
from core.log_safe import safe_log_text
from core.platforms.mercadolivre import HEADERS as ML_HEADERS
from core.platforms.mercadolivre import OFERTAS_URL
from core.platforms.shopee import (
    _preco_float,
    _ts_para_dt,
    credenciais_shopee_do_bot,
)
from core.platforms.shopee_api import graphql_request
from worker.channels import load_filtros
from worker.logger import logger

_SHOPEE_VOUCHER_QUERIES = (
    """
    {
      voucherOfferV2(page: 1, limit: 12) {
        nodes {
          voucherCode
          offerLink
          originalLink
          imageUrl
          minSpend
          discountValue
          discountPercentage
          capAmount
          periodEndTime
        }
      }
    }
    """,
    """
    {
      voucherOfferV2(page: 1, limit: 12) {
        nodes {
          voucherCode
          offerLink
          originalLink
          imageUrl
        }
      }
    }
    """,
)


def _sku(loja: str, codigo: str, url: str) -> str:
    raw = f"{loja}:{codigo}:{url}"
    return "cupom:" + hashlib.sha1(raw.encode()).hexdigest()[:16]


def _linha_beneficio(desc: str, codigo: str | None) -> str:
    desc = (desc or "Cupom").strip()
    if codigo:
        return f"{desc}: {codigo}"
    return desc


class CupomScraper(Scraper):
    nome_fonte = "Cupons"
    timeout = 20.0

    def buscar(self) -> list[OfertaCapturada]:
        if load_filtros().get("aceitar_cupons", True) is False:
            return []
        out: list[OfertaCapturada] = []
        out.extend(self._shopee())
        out.extend(self._meli())
        logger.info(f"[Cupons] {len(out)} cupons capturados.")
        return out

    def _shopee(self) -> list[OfertaCapturada]:
        _conta, app_id, secret = credenciais_shopee_do_bot()
        if not app_id or not secret:
            return []
        nodes = self._shopee_voucher_nodes()
        if not nodes:
            nodes = self._shopee_offer_como_cupom()
        out: list[OfertaCapturada] = []
        for item in nodes[:8]:
            oferta = self._parse_shopee(item)
            if oferta:
                out.append(oferta)
        return out

    def _graphql(self, client: httpx.Client, query: str) -> dict:
        _conta, app_id, secret = credenciais_shopee_do_bot()
        return graphql_request(client, query, app_id=app_id, secret=secret)

    def _shopee_voucher_nodes(self) -> list[dict]:
        with httpx.Client(timeout=self.timeout) as client:
            for query in _SHOPEE_VOUCHER_QUERIES:
                try:
                    data = self._graphql(client, query)
                except Exception as e:
                    logger.debug(
                        f"[Cupons] voucherOfferV2 indisponível: {safe_log_text(e)}"
                    )
                    continue
                nodes = (data.get("voucherOfferV2") or {}).get("nodes") or []
                if nodes:
                    return nodes
        return []

    def _shopee_offer_como_cupom(self) -> list[dict]:
        query = """
        {
          shopeeOfferV2(sortType: 1, page: 1, limit: 15) {
            nodes {
              offerName
              offerLink
              originalLink
              imageUrl
              periodEndTime
            }
          }
        }
        """
        try:
            with httpx.Client(timeout=self.timeout) as client:
                data = self._graphql(client, query)
        except Exception as e:
            logger.warning(f"[Cupons] shopeeOfferV2: {safe_log_text(e)}")
            return []
        out = []
        for item in (data.get("shopeeOfferV2") or {}).get("nodes") or []:
            nome = (item.get("offerName") or "").lower()
            if any(p in nome for p in ("cupom", "voucher", "off", "desconto", "r$")):
                out.append(item)
        return out

    def _parse_shopee(self, item: dict) -> OfertaCapturada | None:
        url = item.get("offerLink") or item.get("originalLink") or item.get("voucherLink")
        if not url:
            return None
        codigo = (item.get("voucherCode") or "").strip().upper() or None
        if not codigo:
            m = re.search(r"\b([A-Z0-9]{6,16})\b", item.get("offerName") or "")
            codigo = m.group(1) if m else None
        pct = _preco_float(item.get("discountPercentage"))
        valor = _preco_float(item.get("discountValue") or item.get("capAmount"))
        min_gasto = _preco_float(item.get("minSpend") or item.get("min_basket_price"))
        if pct and pct <= 1:
            pct *= 100
        if pct and pct >= 1:
            beneficio = f"{int(pct)}% OFF"
            if min_gasto:
                beneficio += f" em R${int(min_gasto)}"
            if valor:
                beneficio += f", limite R${int(valor)}"
        elif valor:
            beneficio = f"R${_fmt(valor)} OFF"
            if min_gasto:
                beneficio += f" em R${_fmt(min_gasto)}"
        else:
            beneficio = (item.get("offerName") or "Cupom Shopee").strip()
            beneficio = re.sub(r"^\[CAMPANHA\]\s*", "", beneficio)
        fim = _ts_para_dt(item.get("periodEndTime"))
        validade = None
        if fim:
            agora = datetime.now(timezone.utc)
            if fim.tzinfo is None:
                fim = fim.replace(tzinfo=timezone.utc)
            horas = max(0, int((fim - agora).total_seconds() // 3600))
            if horas < 48:
                validade = f"{max(horas, 1)} hora" if horas <= 1 else f"{horas} horas"
            else:
                validade = f"{horas // 24} dia" if horas // 24 <= 1 else f"{horas // 24} dias"
        if not codigo and not valor and not pct:
            return None
        return OfertaCapturada(
            nome=linha,
            preco=valor or 0.0,
            desconto=pct,
            loja="Shopee",
            url=url,
            url_carrinho="https://shopee.com.br/cart",
            imagem=item.get("imageUrl"),
            categoria="cupom",
            sku=_sku("shopee", codigo or url, url),
            codigo_cupom=codigo,
            min_gasto=min_gasto,
            beneficio=beneficio,
            validade=validade,
        )

    def _meli(self) -> list[OfertaCapturada]:
        manuais = load_filtros().get("cupons_meli") or []
        out: list[OfertaCapturada] = []
        for item in manuais:
            if not isinstance(item, dict):
                continue
            codigo = str(item.get("codigo") or "").strip().upper()
            url = item.get("url") or "https://www.mercadolivre.com.br/cupons"
            titulo = str(item.get("titulo") or item.get("beneficio") or "Cupom Mercado Livre")
            if not codigo and not titulo:
                continue
            linha = _linha_beneficio(titulo, codigo or None)
            out.append(
                OfertaCapturada(
                    nome=linha,
                    preco=float(item.get("valor") or 0),
                    loja="Mercado Livre",
                    url=url,
                    categoria="cupom",
                    sku=_sku("meli", codigo or url, url),
                    codigo_cupom=codigo or None,
                    min_gasto=_preco_float(item.get("min_gasto")),
                    beneficio=titulo,
                    validade=str(item.get("validade") or "") or None,
                )
            )
        if out:
            return out[:4]
        out.extend(self._meli_html())
        return out[:4]

    def _meli_html(self) -> list[OfertaCapturada]:
        """Página pública de ofertas às vezes traz código/texto de cupom no JSON."""
        try:
            with httpx.Client(timeout=self.timeout, headers=ML_HEADERS, follow_redirects=True) as c:
                resp = c.get(OFERTAS_URL)
        except httpx.HTTPError as e:
            logger.debug(f"[Cupons] MELI ofertas: {e}")
            return []
        if resp.status_code != 200:
            return []
        html = resp.text
        codigos = []
        for rx in (
            r'"coupon_code"\s*:\s*"([A-Z0-9]{4,20})"',
            r'"couponCode"\s*:\s*"([A-Z0-9]{4,20})"',
            r'"code"\s*:\s*"([A-Z]{3,}[A-Z0-9]{2,14})"',
        ):
            for m in re.finditer(rx, html, flags=re.I):
                code = m.group(1).upper()
                if code not in {"HTTP", "HTTPS", "MLB", "JSON", "TYPE"} and code not in codigos:
                    codigos.append(code)
            if codigos:
                break
        textos = re.findall(
            r'"text"\s*:\s*"([^"]{0,12}(?:Cupom|OFF|off)[^"]{0,40})"',
            html,
        )
        if not codigos:
            return []
        out: list[OfertaCapturada] = []
        for i, codigo in enumerate(codigos[:3]):
            titulo = textos[i] if i < len(textos) else "Cupom Mercado Livre"
            titulo = titulo.replace("{1} com Cupom", "Preço com cupom").strip()
            url = "https://www.mercadolivre.com.br/cupons"
            linha = _linha_beneficio(titulo, codigo)
            out.append(
                OfertaCapturada(
                    nome=linha,
                    preco=0.0,
                    loja="Mercado Livre",
                    url=url,
                    categoria="cupom",
                    sku=_sku("meli", codigo, url + codigo),
                    codigo_cupom=codigo,
                    beneficio=titulo,
                )
            )
        return out


def _fmt(valor: float) -> str:
    if abs(valor - round(valor)) < 0.001:
        return str(int(round(valor)))
    return f"{valor:.2f}".replace(".", ",")
