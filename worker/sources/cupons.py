"""Cupons resgatáveis com link afiliado (Shopee voucher; ML via /cupons → _Container_)."""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone

import httpx

from core.http_headers import MELI_HTML_HEADERS
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

CUPONS_ML_URL = "https://www.mercadolivre.com.br/cupons?source_page=mperfil"
CUPONS_ML_TTL_SEGUNDOS = 30 * 60
_MAX_MELI = 8
# Cache compartilhado entre ciclos: (monotonic_ts, ofertas).
_cache_cupons_ml: tuple[float, list[OfertaCapturada]] | None = None

_RE_CAMPAIGN_ID = re.compile(
    r"(?:coupon_campaign_id[=:\\\"'\s]+|_Container_|\"(?:coupon_)?campaign_id\"\s*:\s*\"?)(\d{5,})",
    re.IGNORECASE,
)
_RE_PCT = re.compile(r"(\d{1,2})\s*%\s*(?:OFF|off|de desconto)?", re.IGNORECASE)
_RE_LIMITE = re.compile(
    r"(?:limite|até|ate)\s*R\$?\s*([\d.,]+)|R\$\s*([\d.,]+)\s*(?:OFF|off)",
    re.IGNORECASE,
)
_RE_MIN = re.compile(
    r"(?:acima de|a partir de|mínimo|minimo|compras? (?:de|acima))\s*R\$?\s*([\d.,]+)",
    re.IGNORECASE,
)
_RE_CODIGO = re.compile(r"\b([A-Z0-9]{4,16})\b")


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


def url_container_meli(campaign_id: str) -> str:
    cid = str(campaign_id).strip()
    return f"https://lista.mercadolivre.com.br/_Container_{cid}?coupon_campaign_id={cid}"


def _numero_br(raw: str) -> int | None:
    try:
        return int(float(raw.replace(".", "").replace(",", ".")))
    except ValueError:
        return None


def _beneficio_perto(html: str, campaign_id: str) -> str | None:
    idx = html.find(campaign_id)
    if idx < 0:
        return None
    trecho = html[max(0, idx - 400) : idx + 400]
    pct = _RE_PCT.search(trecho)
    if not pct:
        return None
    beneficio = f"{pct.group(1)}% OFF"
    min_m = _RE_MIN.search(trecho)
    if min_m:
        valor = _numero_br(min_m.group(1))
        if valor is not None:
            beneficio += f" acima de R${valor}"
    lim = _RE_LIMITE.search(trecho)
    if lim:
        valor = _numero_br(lim.group(1) or lim.group(2) or "")
        if valor is not None:
            beneficio += f", limite R${valor}"
    return beneficio

def _codigo_perto(html: str, campaign_id: str) -> str | None:
    idx = html.find(campaign_id)
    if idx < 0:
        return None
    trecho = html[max(0, idx - 200) : idx + 200].upper()
    invalidos = {"HTTP", "HTTPS", "MLB", "JSON", "TYPE", "CUPOM", "OFF", "CONTAINER"}
    for achado in _RE_CODIGO.findall(trecho):
        if achado in invalidos or achado == campaign_id:
            continue
        if any(ch.isdigit() for ch in achado) and any(ch.isalpha() for ch in achado):
            return achado
    return None


def parse_cupons_meli_html(html: str) -> list[dict]:
    """Extrai campaign_ids e benefício aproximado do HTML de /cupons."""
    ids: list[str] = []
    vistos: set[str] = set()
    for match in _RE_CAMPAIGN_ID.finditer(html or ""):
        cid = match.group(1)
        if cid in vistos:
            continue
        vistos.add(cid)
        ids.append(cid)
    out: list[dict] = []
    for cid in ids:
        out.append(
            {
                "campaign_id": cid,
                "beneficio": _beneficio_perto(html, cid) or "Cupom Mercado Livre",
                "codigo": _codigo_perto(html, cid),
            }
        )
    return out


def _html_bloqueado(url: str, status: int, html: str) -> str | None:
    lowered_url = str(url).lower()
    if any(x in lowered_url for x in ("captcha", "account-verification", "login")):
        return f"redirecionou para {url}"
    if status != 200:
        return f"HTTP {status}"
    low = (html or "")[:2000].lower()
    if "captcha" in low or "account-verification" in low:
        return "captcha/verificação no HTML"
    return None


def limpar_cache_cupons_meli() -> None:
    global _cache_cupons_ml
    _cache_cupons_ml = None


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
        if not nodes:
            logger.warning(
                "[Cupons] Shopee com credencial, mas voucherOfferV2/shopeeOfferV2 "
                "não devolveram cupom utilizável."
            )
            return []
        out: list[OfertaCapturada] = []
        for item in nodes[:8]:
            try:
                oferta = self._parse_shopee(item)
            except Exception as exc:
                logger.warning(f"[Cupons] voucher Shopee ignorado: {safe_log_text(exc)}")
                continue
            if oferta:
                out.append(oferta)
        if not out:
            logger.warning(
                "[Cupons] Shopee devolveu nós, mas nenhum passou no parse "
                "(falta offerLink/código/desconto)."
            )
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
        """Scrape /cupons → URL _Container_ + cupons_meli manuais (união por SKU)."""
        scrapeados = self._scrape_cupons_meli()
        manuais = self._meli_manuais()
        return _unir_por_sku([*scrapeados, *manuais])[:_MAX_MELI]

    def _meli_manuais(self) -> list[OfertaCapturada]:
        manuais = load_filtros().get("cupons_meli") or []
        if not manuais:
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
        return out

    def _scrape_cupons_meli(self) -> list[OfertaCapturada]:
        global _cache_cupons_ml
        agora = time.monotonic()
        if (
            _cache_cupons_ml is not None
            and agora - _cache_cupons_ml[0] < CUPONS_ML_TTL_SEGUNDOS
        ):
            return list(_cache_cupons_ml[1])

        from core.platforms.affiliate import _ml_auth

        _, auth = _ml_auth()
        if not auth.cookie:
            logger.debug("[Cupons] ML sem cookie — scrape de /cupons pulado.")
            return []

        headers = dict(MELI_HTML_HEADERS)
        headers["cookie"] = auth.cookie
        try:
            with httpx.Client(
                timeout=self.timeout, headers=headers, follow_redirects=True
            ) as client:
                resp = client.get(CUPONS_ML_URL)
        except httpx.HTTPError as exc:
            logger.warning(f"[Cupons] scrape ML /cupons falhou: {safe_log_text(exc)}")
            return []

        bloqueio = _html_bloqueado(str(resp.url), resp.status_code, resp.text)
        if bloqueio:
            logger.warning(
                f"[Cupons] scrape ML /cupons bloqueado ({bloqueio}) — cookie intacto."
            )
            return []

        itens = parse_cupons_meli_html(resp.text)
        if not itens:
            logger.warning(
                "[Cupons] /cupons sem campaign_id no HTML (login/Aplicar pode ser "
                "necessário — scrape não clica Aplicar)."
            )
            _cache_cupons_ml = (agora, [])
            return []

        out: list[OfertaCapturada] = []
        for item in itens:
            cid = str(item["campaign_id"])
            url = url_container_meli(cid)
            beneficio = str(item.get("beneficio") or "Cupom Mercado Livre")
            codigo = _codigo_digitavel(item.get("codigo"))
            out.append(
                OfertaCapturada(
                    nome=_linha_beneficio(beneficio, codigo),
                    preco=0.0,
                    loja="Mercado Livre",
                    url=url,
                    categoria="cupom",
                    sku=_sku("meli", codigo or cid, url),
                    codigo_cupom=codigo,
                    beneficio=beneficio,
                )
            )
        logger.info(f"[Cupons] ML scrape: {len(out)} campanhas em /cupons.")
        _cache_cupons_ml = (agora, list(out))
        return out


def _unir_por_sku(ofertas: list[OfertaCapturada]) -> list[OfertaCapturada]:
    vistos: set[str] = set()
    out: list[OfertaCapturada] = []
    for oferta in ofertas:
        chave = oferta.sku or oferta.url
        if chave in vistos:
            continue
        vistos.add(chave)
        out.append(oferta)
    return out


def _fmt(valor: float) -> str:
    if abs(valor - round(valor)) < 0.001:
        return str(int(round(valor)))
    return f"{valor:.2f}".replace(".", ",")
