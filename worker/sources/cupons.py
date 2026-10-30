"""Cupons resgatáveis com link afiliado (Shopee voucher; ML só se cadastrado)."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

import httpx

from core.log_safe import safe_log_text
from core.platforms.base import OfertaCapturada, Scraper
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


def _codigo_digitavel(texto: str | None) -> str | None:
    code = (texto or "").strip().upper()
    if re.fullmatch(r"[A-Z0-9]{4,16}", code):
        return code
    return None


def _cupom_explicito(item: dict) -> bool:
    """Fallback de campanha só entra com código digitável ou desconto informado."""
    codigo = _codigo_digitavel(item.get("voucherCode"))
    if codigo and codigo not in {"HTTP", "HTTPS", "MLB", "JSON", "TYPE", "CUPOM", "OFF"}:
        return True
    nome = (item.get("offerName") or "").upper()
    for achado in re.findall(r"\b([A-Z0-9]{4,16})\b", nome):
        if any(ch.isdigit() for ch in achado):
            return True
    return any(
        item.get(campo) not in (None, "", 0)
        for campo in ("discountPercentage", "discountValue", "capAmount")
    )


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
            try:
                oferta = self._parse_shopee(item)
            except Exception as exc:
                logger.warning(f"[Cupons] voucher Shopee ignorado: {safe_log_text(exc)}")
                continue
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
              discountPercentage
              discountValue
              capAmount
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
            if _cupom_explicito(item):
                out.append(item)
        return out

    def _parse_shopee(self, item: dict) -> OfertaCapturada | None:
        # offerLink já vem com tracking de afiliado; sem ele o cupom não entra.
        url = (item.get("offerLink") or "").strip()
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
            nome=_linha_beneficio(beneficio, codigo),
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
        """Só cupons colados da Central de Afiliados. Lista vazia = conta sem liberação."""
        manuais = load_filtros().get("cupons_meli") or []
        if not manuais:
            logger.debug("[Cupons] nenhum cupom ML cadastrado.")
            return []
        out: list[OfertaCapturada] = []
        for item in manuais:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url or "mercadolivre.com.br/cupons" in url.lower().rstrip("/"):
                # Página genérica de cupons não é afiliada; createLink não salva.
                continue
            codigo = str(item.get("codigo") or "").strip().upper() or None
            titulo = str(
                item.get("titulo") or item.get("beneficio") or "Cupom Mercado Livre"
            ).strip()
            if not titulo:
                continue
            linha = _linha_beneficio(titulo, codigo)
            out.append(
                OfertaCapturada(
                    nome=linha,
                    preco=float(item.get("valor") or 0),
                    loja="Mercado Livre",
                    url=url,
                    categoria="cupom",
                    sku=_sku("meli", codigo or url, url),
                    codigo_cupom=codigo,
                    min_gasto=_preco_float(item.get("min_gasto")),
                    beneficio=titulo,
                    validade=str(item.get("validade") or "") or None,
                )
            )
        return out[:4]


def _fmt(valor: float) -> str:
    if abs(valor - round(valor)) < 0.001:
        return str(int(round(valor)))
    return f"{valor:.2f}".replace(".", ",")
