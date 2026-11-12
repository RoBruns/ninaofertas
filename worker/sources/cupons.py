"""Cupons resgatáveis com link afiliado (Shopee voucher; ML via /cupons → _Container_)."""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any

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

CUPONS_ML_URLS = (
    # Lista completa (filtro) costuma trazer mais cards que a home de /cupons.
    "https://www.mercadolivre.com.br/cupons/filter?all=true&source_page=int_view_all",
    "https://www.mercadolivre.com.br/cupons?source_page=mperfil",
)
CUPONS_ML_TTL_SEGUNDOS = 30 * 60
_MAX_MELI = 8
_BENEFICIO_GENERICO = "Cupom Mercado Livre"
# Cache compartilhado entre ciclos: (monotonic_ts, ofertas).
_cache_cupons_ml: tuple[float, list[OfertaCapturada]] | None = None

_RE_CAMPAIGN_ID = re.compile(
    r"(?:coupon_campaign_id[=:\\\"'\s]+|_Container_|\"(?:coupon_)?campaign_id\"\s*:\s*\"?)(\d{5,})",
    re.IGNORECASE,
)
_RE_PCT_EM = re.compile(
    # "30% OFF em LIQUIDA" — não "em R$79" (mínimo de compra).
    r"(\d{1,2})\s*%\s*OFF\s+em\s+(?!R\$)([A-Za-zÀ-ÿ0-9][\wÀ-ÿ0-9 &'./\-]{1,48})",
    re.IGNORECASE,
)
_RE_PCT = re.compile(r"(\d{1,2})\s*%\s*(?:OFF|off|de desconto)?", re.IGNORECASE)
_RE_RS_OFF = re.compile(r"R\$\s*([\d.,]+)\s*OFF", re.IGNORECASE)
_RE_LIMITE = re.compile(
    r"(?:limite|até|ate|limitado a)\s*R\$?\s*([\d.,]+)",
    re.IGNORECASE,
)
_RE_MIN = re.compile(
    r"(?:acima de|a partir de|mínimo|minimo|compras? (?:de|acima)|OFF\s+em)\s*R\$\s*([\d.,]+)",
    re.IGNORECASE,
)
_RE_CODIGO = re.compile(r"\b([A-Z0-9]{4,16})\b")
_CAMPOS_TITULO_JSON = (
    "title",
    "subtitle",
    "label",
    "text",
    "headline",
    "description",
    "coupon_title",
    "discount_label",
    "discount",
    "name",
    "store_name",
    "brand_name",
    "merchant_name",
    "primary_text",
    "secondary_text",
    "value",
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


def url_container_meli(campaign_id: str) -> str:
    cid = str(campaign_id).strip()
    return f"https://lista.mercadolivre.com.br/_Container_{cid}?coupon_campaign_id={cid}"


def campaign_id_da_url(url: str) -> str | None:
    texto = url or ""
    m = re.search(r"coupon_campaign_id=(\d{5,})", texto, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"_Container_(\d{5,})", texto, re.IGNORECASE)
    return m.group(1) if m else None


def _numero_br(raw: str) -> int | None:
    try:
        return int(float(raw.replace(".", "").replace(",", ".")))
    except ValueError:
        return None


def _limpar_loja(raw: str) -> str:
    loja = (raw or "").strip()
    loja = re.split(r"\s*(?:[|•\n]|limit|acima|a partir|,)\s*", loja, maxsplit=1, flags=re.I)[
        0
    ].strip(" .,-:;\"'")
    return loja[:48]


def _beneficio_de_texto(blob: str) -> str | None:
    """Monta título no estilo da página: '30% OFF em LIQUIDA' / '25% OFF acima de R$79'."""
    texto = (blob or "").replace("\\u0026", "&").replace("\\/", "/")
    m_em = _RE_PCT_EM.search(texto)
    if m_em:
        loja = _limpar_loja(m_em.group(2))
        if loja and loja.upper() not in {"OFF", "EM", "DE", "NO", "NA", "R"}:
            return f"{m_em.group(1)}% OFF em {loja}"
    pct = _RE_PCT.search(texto)
    if pct:
        beneficio = f"{pct.group(1)}% OFF"
        min_m = _RE_MIN.search(texto)
        if min_m:
            valor = _numero_br(min_m.group(1))
            if valor is not None:
                beneficio += f" acima de R${valor}"
        lim = _RE_LIMITE.search(texto)
        if lim:
            valor = _numero_br(lim.group(1))
            if valor is not None and f"R${valor}" not in beneficio:
                beneficio += f", limite R${valor}"
        return beneficio
    rs = _RE_RS_OFF.search(texto)
    if rs:
        valor = _numero_br(rs.group(1))
        if valor is not None:
            beneficio = f"R${valor} OFF"
            min_m = _RE_MIN.search(texto)
            if min_m:
                minimo = _numero_br(min_m.group(1))
                if minimo is not None:
                    beneficio += f" acima de R${minimo}"
            return beneficio
    return None


def _textos_do_objeto(obj: dict[str, Any]) -> list[str]:
    textos: list[str] = []
    for chave in _CAMPOS_TITULO_JSON:
        valor = obj.get(chave)
        if isinstance(valor, str) and valor.strip():
            textos.append(valor.strip())
        elif isinstance(valor, dict):
            for sub in ("text", "label", "title", "value", "name"):
                interno = valor.get(sub)
                if isinstance(interno, str) and interno.strip():
                    textos.append(interno.strip())
        elif isinstance(valor, (int, float)) and chave in {"discount", "value"}:
            textos.append(f"{int(valor)}% OFF")
    return textos


def _campaign_id_do_objeto(obj: dict[str, Any]) -> str | None:
    for chave in ("coupon_campaign_id", "campaign_id", "id"):
        valor = obj.get(chave)
        if valor is None:
            continue
        texto = str(valor).strip()
        if texto.isdigit() and len(texto) >= 5:
            return texto
    return None


def _coleta_cupons_json(node: Any, out: dict[str, dict]) -> None:
    if isinstance(node, dict):
        cid = _campaign_id_do_objeto(node)
        if cid:
            textos = _textos_do_objeto(node)
            # title + subtitle costumam vir separados ("30% OFF" / "em LIQUIDA").
            beneficio = _beneficio_de_texto(" ".join(textos)) if textos else None
            if not beneficio:
                beneficio = _beneficio_de_texto(json.dumps(node, ensure_ascii=False)[:800])
            codigo = None
            for chave in ("coupon_code", "couponCode", "code", "voucherCode"):
                codigo = _codigo_digitavel(node.get(chave) if isinstance(node.get(chave), str) else None)
                if codigo:
                    break
            atual = out.get(cid)
            if atual is None or (
                atual.get("beneficio") in (None, _BENEFICIO_GENERICO)
                and beneficio
            ):
                out[cid] = {
                    "campaign_id": cid,
                    "beneficio": beneficio or _BENEFICIO_GENERICO,
                    "codigo": codigo or (atual or {}).get("codigo"),
                }
            elif codigo and not atual.get("codigo"):
                atual["codigo"] = codigo
        for valor in node.values():
            _coleta_cupons_json(valor, out)
    elif isinstance(node, list):
        for item in node:
            _coleta_cupons_json(item, out)


def _extrair_json_embutidos(html: str) -> dict[str, dict]:
    """Tenta decodificar blobs JSON próximos de campaign_id / coupons."""
    out: dict[str, dict] = {}
    texto = html or ""
    decoder = json.JSONDecoder()
    marcadores = (
        r'"coupons"\s*:\s*',
        r'"coupon_list"\s*:\s*',
        r'"available_coupons"\s*:\s*',
        r'"filtercoupons"\s*:\s*',
        r'"results"\s*:\s*',
        r'"polycards"\s*:\s*',
        r'"cards"\s*:\s*',
        r'"components"\s*:\s*',
    )
    for padrao in marcadores:
        for match in re.finditer(padrao, texto):
            try:
                node, _ = decoder.raw_decode(texto[match.end() :].lstrip())
            except json.JSONDecodeError:
                continue
            _coleta_cupons_json(node, out)
    # Objetos soltos com coupon_campaign_id.
    for match in re.finditer(r'\{\s*"[^"]*(?:campaign_id|coupon_campaign_id)"', texto):
        inicio = match.start()
        try:
            node, _ = decoder.raw_decode(texto[inicio:])
        except json.JSONDecodeError:
            continue
        if isinstance(node, dict):
            _coleta_cupons_json(node, out)
    return out


def _beneficio_perto(html: str, campaign_id: str) -> str | None:
    idx = html.find(campaign_id)
    if idx < 0:
        return None
    # Janela larga: título ("30% OFF em LIQUIDA") costuma ficar longe do id no JSON.
    trecho = html[max(0, idx - 1200) : idx + 1200]
    return _beneficio_de_texto(trecho)


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
    """Extrai campaign_ids e benefício (ex.: '30% OFF em LIQUIDA') do HTML de /cupons."""
    por_id = _extrair_json_embutidos(html or "")
    for match in _RE_CAMPAIGN_ID.finditer(html or ""):
        cid = match.group(1)
        if cid in por_id and por_id[cid].get("beneficio") not in (None, _BENEFICIO_GENERICO):
            continue
        beneficio = _beneficio_perto(html, cid) or _BENEFICIO_GENERICO
        codigo = _codigo_perto(html, cid)
        atual = por_id.get(cid)
        if atual is None:
            por_id[cid] = {
                "campaign_id": cid,
                "beneficio": beneficio,
                "codigo": codigo,
            }
        else:
            if atual.get("beneficio") in (None, _BENEFICIO_GENERICO) and beneficio:
                atual["beneficio"] = beneficio
            if codigo and not atual.get("codigo"):
                atual["codigo"] = codigo
    return list(por_id.values())


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
        por_cid = {
            campaign_id_da_url(o.url): o
            for o in scrapeados
            if campaign_id_da_url(o.url)
        }
        manuais = self._meli_manuais(por_cid)
        return _unir_por_sku([*scrapeados, *manuais])[:_MAX_MELI]

    def _meli_manuais(
        self, por_cid: dict[str, OfertaCapturada] | None = None
    ) -> list[OfertaCapturada]:
        manuais = load_filtros().get("cupons_meli") or []
        if not manuais:
            return []
        por_cid = por_cid or {}
        out: list[OfertaCapturada] = []
        for item in manuais:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url or "mercadolivre.com.br/cupons" in url.lower().rstrip("/"):
                # Página genérica de cupons não é afiliada; createLink não salva.
                continue
            codigo = str(item.get("codigo") or "").strip().upper() or None
            titulo = str(item.get("titulo") or item.get("beneficio") or "").strip()
            cid = campaign_id_da_url(url)
            scrape = por_cid.get(cid) if cid else None
            if not titulo or titulo == _BENEFICIO_GENERICO:
                if scrape and scrape.beneficio:
                    titulo = scrape.beneficio
                else:
                    titulo = _BENEFICIO_GENERICO
            if not codigo and scrape and scrape.codigo_cupom:
                codigo = scrape.codigo_cupom
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
        html_parts: list[str] = []
        try:
            with httpx.Client(
                timeout=self.timeout, headers=headers, follow_redirects=True
            ) as client:
                for url in CUPONS_ML_URLS:
                    try:
                        resp = client.get(url)
                    except httpx.HTTPError as exc:
                        logger.warning(
                            f"[Cupons] scrape ML {url} falhou: {safe_log_text(exc)}"
                        )
                        continue
                    bloqueio = _html_bloqueado(str(resp.url), resp.status_code, resp.text)
                    if bloqueio:
                        logger.warning(
                            f"[Cupons] scrape ML /cupons bloqueado ({bloqueio}) — "
                            "cookie intacto."
                        )
                        continue
                    html_parts.append(resp.text or "")
        except httpx.HTTPError as exc:
            logger.warning(f"[Cupons] scrape ML /cupons falhou: {safe_log_text(exc)}")
            return []

        if not html_parts:
            return []

        itens = parse_cupons_meli_html("\n".join(html_parts))
        if not itens:
            logger.warning(
                "[Cupons] /cupons sem campaign_id no HTML (cookie pode estar sem "
                "sessão /cupons — scrape não clica Aplicar)."
            )
            _cache_cupons_ml = (agora, [])
            return []

        out: list[OfertaCapturada] = []
        genericos = 0
        for item in itens:
            cid = str(item["campaign_id"])
            url = url_container_meli(cid)
            beneficio = str(item.get("beneficio") or _BENEFICIO_GENERICO)
            if beneficio == _BENEFICIO_GENERICO:
                genericos += 1
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
        logger.info(
            f"[Cupons] ML scrape: {len(out)} campanhas em /cupons "
            f"({genericos} sem título)."
        )
        _cache_cupons_ml = (agora, list(out))
        return out


def _unir_por_sku(ofertas: list[OfertaCapturada]) -> list[OfertaCapturada]:
    vistos: set[str] = set()
    out: list[OfertaCapturada] = []
    for oferta in ofertas:
        chaves = {oferta.sku or oferta.url}
        if oferta.url:
            chaves.add(oferta.url)
        cid = campaign_id_da_url(oferta.url or "")
        if cid:
            chaves.add(f"cid:{cid}")
        if chaves & vistos:
            continue
        vistos |= {c for c in chaves if c}
        out.append(oferta)
    return out


def _fmt(valor: float) -> str:
    if abs(valor - round(valor)) < 0.001:
        return str(int(round(valor)))
    return f"{valor:.2f}".replace(".", ",")
