"""Fonte: Mercado Livre — ofertas do site (HTML), não a API de search.

`GET /sites/MLB/search?q=` está bloqueado (403 PolicyAgent) para apps comuns.
A busca por palavra na listagem também cai em captcha. O que funciona é a
página pública de ofertas por categoria:

    https://www.mercadolivre.com.br/ofertas?category=MLB1574

O cookie de afiliado vai neste GET (pra não cair em verificação) e de novo
no `affiliate.py`, pra transformar o permalink em link afiliado.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

import httpx

from config import grupo_whatsapp, load_filtros, settings
from cozinha import promocao_liberada
from http_headers import MELI_HTML_HEADERS
from logger import logger
from scraper.base import OfertaCapturada, Scraper

HEADERS = MELI_HTML_HEADERS


def _headers_html() -> dict[str, str]:
    headers = dict(MELI_HTML_HEADERS)
    cookie = settings.mercadolivre_affiliate_cookie
    if cookie:
        headers["Cookie"] = cookie
    return headers

OFERTAS_URL = "https://www.mercadolivre.com.br/ofertas"
# Casa/móveis, eletro, beleza, moda, joias.
CATEGORIAS_CASA = (
    "MLB1574",
    "MLB5726",
    "MLB1246",
    "MLB1430",
    "MLB3937",
)

LISTA_URL = "https://lista.mercadolivre.com.br/"


def _extrair_items_json(html: str) -> list[dict]:
    idx = html.find('"items":[{')
    if idx < 0:
        return []
    decoder = json.JSONDecoder()
    try:
        arr, _ = decoder.raw_decode(html[idx + len('"items":') :])
    except json.JSONDecodeError:
        return []
    return arr if isinstance(arr, list) else []


def _comp_titulo(card: dict) -> str:
    for comp in card.get("components") or []:
        if comp.get("type") == "title":
            return str(((comp.get("title") or {}).get("text")) or "").strip()
    return ""


def _comp_precos(card: dict) -> tuple[float | None, float | None]:
    atual = None
    anterior = None
    for comp in card.get("components") or []:
        if comp.get("type") != "price":
            continue
        price = comp.get("price") or {}
        cur = price.get("current_price") or {}
        if isinstance(cur.get("value"), (int, float)):
            atual = float(cur["value"])
        for label in price.get("price_labels") or []:
            for val in label.get("values") or []:
                p = val.get("price") or {}
                if p.get("previous") and isinstance(p.get("value"), (int, float)):
                    anterior = float(p["value"])
    meta_price = ((card.get("metadata") or {}).get("tracks") or {}).get("price") or {}
    if atual is None and isinstance(meta_price.get("price"), (int, float)):
        atual = float(meta_price["price"])
    return atual, anterior


def _imagem(card: dict) -> str | None:
    pics = ((card.get("pictures") or {}).get("pictures")) or []
    if not pics:
        return None
    pic_id = pics[0].get("id")
    if not pic_id:
        return None
    return f"https://http2.mlstatic.com/D_NQ_NP_{pic_id}-O.webp"


def _url_item(card: dict) -> str | None:
    raw = ((card.get("metadata") or {}).get("url") or "").strip()
    if not raw:
        return None
    if raw.startswith("http"):
        return raw
    return "https://" + raw.lstrip("/")


def _beneficio_cupom(card: dict) -> str | None:
    """Código real do card, ou o desconto escrito (R$ X OFF). Sem inventar código."""
    blob = json.dumps(card, ensure_ascii=False)
    m = re.search(r'"(?:coupon_code|couponCode)"\s*:\s*"([A-Za-z0-9]{4,16})"', blob)
    if m:
        code = m.group(1).upper()
        if code not in {"HTTP", "HTTPS", "MLB", "JSON", "TYPE", "CUPOM"}:
            return code
    for comp in card.get("components") or []:
        if comp.get("type") != "promotions":
            continue
        for promo in comp.get("promotions") or []:
            if promo.get("type") != "coupon":
                continue
            text = str(promo.get("text") or "")
            for val in promo.get("values") or []:
                if val.get("key") != "amount":
                    continue
                price = (val.get("price") or {}).get("value")
                if isinstance(price, (int, float)) and price > 0 and "OFF" in text.upper():
                    n = int(price) if abs(price - round(price)) < 0.001 else price
                    return f"R$ {n} OFF"
    return None


def _parse_card(card: dict) -> OfertaCapturada | None:
    nome = _comp_titulo(card)
    preco, preco_anterior = _comp_precos(card)
    url = _url_item(card)
    sku = (card.get("metadata") or {}).get("id")
    if not nome or preco is None or not url:
        return None
    codigo = _beneficio_cupom(card) if promocao_liberada(grupo_whatsapp()) else None
    return OfertaCapturada(
        nome=nome,
        preco=preco,
        preco_anterior=preco_anterior,
        loja="Mercado Livre",
        url=url,
        imagem=_imagem(card),
        sku=str(sku) if sku else None,
        codigo_cupom=codigo,
    )


class MercadoLivreScraper(Scraper):
    nome_fonte = "Mercado Livre"
    timeout = 25.0

    def _termos_busca(self) -> list[str]:
        filtros = load_filtros()
        return (
            filtros.get("termos_busca")
            or filtros.get("palavras_chave")
            or filtros.get("categorias")
            or []
        )

    def _categorias_meli(self) -> tuple[str, ...]:
        filtros = load_filtros()
        cats = filtros.get("categorias_meli") or CATEGORIAS_CASA
        return tuple(cats)

    def buscar(self) -> list[OfertaCapturada]:
        vistas: set[str] = set()
        ofertas: list[OfertaCapturada] = []
        self._bloqueio_avisado = False
        with httpx.Client(timeout=self.timeout, headers=_headers_html(), follow_redirects=True) as client:
            ofertas.extend(self._buscar_ofertas_categoria(client, vistas))
            ofertas.extend(self._buscar_lista_termos(client, vistas))
        logger.info(f"[Mercado Livre] {len(ofertas)} ofertas capturadas.")
        return ofertas

    def _registrar_bloqueio(self, detalhe: str) -> None:
        if self._bloqueio_avisado:
            return
        self._bloqueio_avisado = True
        logger.warning(f"[Mercado Livre] página de ofertas bloqueada ({detalhe}).")

    def _buscar_ofertas_categoria(self, client: httpx.Client, vistas: set[str]) -> list[OfertaCapturada]:
        out: list[OfertaCapturada] = []
        for cat in self._categorias_meli():
            for page in range(1, 4):
                params = {"category": cat}
                if page > 1:
                    params["page"] = page
                try:
                    resp = client.get(OFERTAS_URL, params=params)
                except httpx.HTTPError as e:
                    logger.warning(f"[Mercado Livre] ofertas cat={cat} page={page}: {e}")
                    break
                url = str(resp.url).lower()
                if (
                    resp.status_code != 200
                    or "captcha" in url
                    or "account-verification" in url
                ):
                    self._registrar_bloqueio(f"HTTP {resp.status_code} cat={cat}")
                    break
                cards = _extrair_items_json(resp.text)
                if not cards:
                    corpo = resp.text.lower()
                    if "captcha" in corpo or "account-verification" in corpo:
                        self._registrar_bloqueio(f"HTTP {resp.status_code} cat={cat} sem cards")
                    break
                for raw in cards:
                    card = raw.get("card") or raw
                    oferta = _parse_card(card)
                    if not oferta:
                        continue
                    chave = oferta.sku or oferta.url
                    if chave in vistas:
                        continue
                    vistas.add(chave)
                    oferta.categoria = "meli_nicho"
                    out.append(oferta)
        return out

    def _buscar_lista_termos(self, client: httpx.Client, vistas: set[str]) -> list[OfertaCapturada]:
        """Tenta a listagem por termo. Se cair em captcha, só loga e segue."""
        out: list[OfertaCapturada] = []
        for termo in self._termos_busca()[:8]:
            slug = quote_plus(termo).replace("+", "-")
            try:
                resp = client.get(LISTA_URL + slug)
            except httpx.HTTPError as e:
                logger.debug(f"[Mercado Livre] lista '{termo}': {e}")
                continue
            if "captcha" in str(resp.url) or "verification" in str(resp.url) or "suspicious" in str(resp.url):
                logger.debug(f"[Mercado Livre] lista '{termo}' bloqueada (captcha/verificação).")
                continue
            if resp.status_code != 200:
                continue
            for raw in _extrair_items_json(resp.text):
                oferta = _parse_card(raw.get("card") or raw)
                if not oferta:
                    continue
                chave = oferta.sku or oferta.url
                if chave in vistas:
                    continue
                vistas.add(chave)
                out.append(oferta)
        return out
