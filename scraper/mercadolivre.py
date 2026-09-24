"""Fonte: Mercado Livre — ofertas do site (HTML), não a API de search.

`GET /sites/MLB/search?q=` está bloqueado (403 PolicyAgent) para apps comuns.
A busca por palavra na listagem também cai em captcha. O que funciona é a
página pública de ofertas por categoria:

    https://www.mercadolivre.com.br/ofertas?category=MLB1574

O cookie/tag do .env continua sendo usado depois, no `affiliate.py`, pra
transformar o permalink em link afiliado.
"""
from __future__ import annotations

import json
from urllib.parse import quote_plus

import httpx

from config import load_filtros
from http_headers import MELI_HTML_HEADERS
from logger import logger
from scraper.base import OfertaCapturada, Scraper

HEADERS = MELI_HTML_HEADERS

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


def _parse_card(card: dict) -> OfertaCapturada | None:
    nome = _comp_titulo(card)
    preco, preco_anterior = _comp_precos(card)
    url = _url_item(card)
    sku = (card.get("metadata") or {}).get("id")
    if not nome or preco is None or not url:
        return None
    return OfertaCapturada(
        nome=nome,
        preco=preco,
        preco_anterior=preco_anterior,
        loja="Mercado Livre",
        url=url,
        imagem=_imagem(card),
        sku=str(sku) if sku else None,
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
        with httpx.Client(timeout=self.timeout, headers=HEADERS, follow_redirects=True) as client:
            ofertas.extend(self._buscar_ofertas_categoria(client, vistas))
            ofertas.extend(self._buscar_lista_termos(client, vistas))
        logger.info(f"[Mercado Livre] {len(ofertas)} ofertas capturadas.")
        return ofertas

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
                if resp.status_code != 200 or "captcha" in str(resp.url) or "account-verification" in str(resp.url):
                    logger.warning(
                        f"[Mercado Livre] ofertas cat={cat} page={page} "
                        f"HTTP {resp.status_code} url={resp.url}"
                    )
                    break
                cards = _extrair_items_json(resp.text)
                if not cards:
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
