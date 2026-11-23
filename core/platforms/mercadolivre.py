"""Fonte: Mercado Livre — ofertas do site (HTML), não a API de search.

`GET /sites/MLB/search?q=` está bloqueado (403 PolicyAgent) para apps comuns.
A busca por palavra na listagem também cai em captcha. O que funciona é a
página pública de ofertas por categoria:

    https://www.mercadolivre.com.br/ofertas?category=MLB1574

Mais vendidos vinham das páginas públicas de ranking. Desde 2026-11 o HTML
cai em account-verification mesmo com cookie válido; a fila manual
`content.produtos_meli` + createLink mantém o envio. A API oficial
`/highlights` continua 403 PolicyAgent para conta de afiliado (ADR-024/035).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote_plus

import httpx
from loguru import logger

from core.platforms.base import OfertaCapturada, Scraper
from core.config_provider import load_filtros_runtime as load_filtros
from core.http_headers import MELI_HTML_HEADERS
from core import relogio

HEADERS = MELI_HTML_HEADERS

OFERTAS_URL = "https://www.mercadolivre.com.br/ofertas"
MAIS_VENDIDOS_URL = "https://www.mercadolivre.com.br/mais-vendidos"
# O ranking muda devagar. Buscar a página a cada ciclo só aumentaria o risco de
# captcha no cookie da conta, então cada página bem-sucedida vale por 30 minutos.
MAIS_VENDIDOS_TTL_SEGUNDOS = 30 * 60
# Depois de account-verification, não martelar o cookie a cada ciclo.
BLOQUEIO_HTML_TTL_SEGUNDOS = 45 * 60
PRODUTOS_MELI_TTL_HORAS = 48
_cache_mais_vendidos: dict[str, tuple[float, dict[str, list[dict]]]] = {}
_bloqueio_html_ate: float | None = None
# Casa/móveis, eletro, beleza, moda, joias.
CATEGORIAS_CASA = (
    "MLB1574",
    "MLB5726",
    "MLB1246",
    "MLB1430",
    "MLB3937",
)

LISTA_URL = "https://lista.mercadolivre.com.br/"

_MLB_RE = re.compile(r"MLB-?(\d+)", re.IGNORECASE)


def limpar_cache_bloqueio_html() -> None:
    """Só para testes: zera a pausa pós-bloqueio."""
    global _bloqueio_html_ate
    _bloqueio_html_ate = None


def limpar_cache_mais_vendidos() -> None:
    _cache_mais_vendidos.clear()


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


def _extrair_mais_vendidos_json(html: str) -> dict[str, list[dict]]:
    blocos: dict[str, list[dict]] = {}
    marcadores = list(
        re.finditer(
            r'"best_sellers_configuration"\s*:\s*\{\s*"category"\s*:\s*"([^"]+)"', html
        )
    )
    decoder = json.JSONDecoder()
    for i, marcador in enumerate(marcadores):
        fim = marcadores[i + 1].start() if i + 1 < len(marcadores) else len(html)
        trecho = html[marcador.end():fim]
        array = re.search(r'"polycards"\s*:\s*', trecho)
        if array is None:
            continue
        try:
            cards, _ = decoder.raw_decode(trecho[array.end():].lstrip())
        except json.JSONDecodeError:
            continue
        if isinstance(cards, list):
            blocos[marcador.group(1)] = cards
    return blocos


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


_CODIGOS_CUPOM_INVALIDOS = {"HTTP", "HTTPS", "MLB", "JSON", "TYPE", "CUPOM", "OFF"}


def _beneficio_cupom(card: dict) -> str | None:
    """Retorna somente codigo digitavel; o selo de desconto nao e cupom."""
    blob = json.dumps(card, ensure_ascii=False)
    match = re.search(r'"(?:coupon_code|couponCode)"\s*:\s*"([A-Za-z0-9]{4,16})"', blob)
    if match is None:
        return None
    code = match.group(1).upper()
    return None if code in _CODIGOS_CUPOM_INVALIDOS else code


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
        codigo_cupom=_beneficio_cupom(card),
    )


def _mlb_de_url(url: str) -> str | None:
    match = _MLB_RE.search(url)
    if match is None:
        return None
    return f"MLB{match.group(1)}"


def _preco_decimal(valor: object) -> float | None:
    if valor is None or str(valor).strip() == "":
        return None
    try:
        return float(Decimal(str(valor).replace(",", ".")))
    except (InvalidOperation, ValueError):
        return None


def _parse_adicionado_em(raw: object) -> datetime | None:
    texto = str(raw or "").strip()
    if not texto:
        return None
    try:
        dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def produtos_manuais_de_filtros(filtros: dict | None = None) -> list[OfertaCapturada]:
    """Converte `content.produtos_meli` frescos em ofertas capturáveis."""
    dados = filtros if filtros is not None else load_filtros()
    itens = dados.get("produtos_meli") or []
    agora = relogio.agora_banco()
    limite = timedelta(hours=PRODUTOS_MELI_TTL_HORAS)
    out: list[OfertaCapturada] = []
    for raw in itens:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "").strip()
        mlb = _mlb_de_url(url)
        if not url or mlb is None or "mercadolivre.com.br" not in url.lower():
            continue
        adicionado = _parse_adicionado_em(raw.get("adicionado_em"))
        if adicionado is not None and agora - adicionado > limite:
            continue
        preco = _preco_decimal(raw.get("preco"))
        if preco is None:
            continue
        titulo = str(raw.get("titulo") or "").strip() or f"Produto {mlb}"
        anterior = _preco_decimal(raw.get("preco_anterior"))
        imagem = str(raw.get("imagem") or "").strip() or None
        out.append(
            OfertaCapturada(
                nome=titulo,
                preco=preco,
                preco_anterior=anterior,
                loja="Mercado Livre",
                url=url,
                imagem=imagem,
                sku=mlb,
                product_url=url,
                origem_categoria_meli=True,
            )
        )
    return out


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

    def _html_em_pausa(self) -> bool:
        return _bloqueio_html_ate is not None and time.monotonic() < _bloqueio_html_ate

    def _marcar_bloqueio_html(self) -> None:
        global _bloqueio_html_ate
        _bloqueio_html_ate = time.monotonic() + BLOQUEIO_HTML_TTL_SEGUNDOS

    def buscar(self) -> list[OfertaCapturada]:
        vistas: set[str] = set()
        ofertas: list[OfertaCapturada] = []
        for manual in produtos_manuais_de_filtros():
            chave = manual.sku or manual.url
            if chave in vistas:
                continue
            vistas.add(chave)
            ofertas.append(manual)

        if self._html_em_pausa():
            logger.info(
                "[Mercado Livre] HTML em pausa após bloqueio; "
                f"{len(ofertas)} oferta(s) da fila manual."
            )
            logger.info(f"[Mercado Livre] {len(ofertas)} ofertas capturadas.")
            return ofertas

        headers = dict(HEADERS)
        # Mesma credencial cifrada da conta vinculada ao bot (ADR-020).
        from core.platforms.affiliate import _ml_auth

        _, auth = _ml_auth()
        if auth.cookie:
            headers["cookie"] = auth.cookie
        self._bloqueio_avisado = False
        with httpx.Client(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            origem = load_filtros().get("origem_produtos", "novidades")
            if origem != "novidades":
                ofertas.extend(self._buscar_mais_vendidos(client, vistas))
            if origem != "mais_vendidos":
                ofertas.extend(self._buscar_ofertas_categoria(client, vistas))
                ofertas.extend(self._buscar_lista_termos(client, vistas))
        logger.info(f"[Mercado Livre] {len(ofertas)} ofertas capturadas.")
        return ofertas

    def _registrar_bloqueio(self, detalhe: str) -> None:
        """Um aviso por busca: com o ML bloqueando, cada categoria repetiria o mesmo."""
        if getattr(self, "_bloqueio_avisado", False):
            return
        self._bloqueio_avisado = True
        self._marcar_bloqueio_html()
        logger.warning(f"[Mercado Livre] página de ofertas bloqueada ({detalhe}).")

    def _buscar_mais_vendidos(self, client: httpx.Client, vistas: set[str]) -> list[OfertaCapturada]:
        def buscar_pagina(url: str) -> dict[str, list[dict]]:
            em_cache = _cache_mais_vendidos.get(url)
            if em_cache is not None and time.monotonic() - em_cache[0] < MAIS_VENDIDOS_TTL_SEGUNDOS:
                return em_cache[1]
            try:
                resp = client.get(url)
            except httpx.HTTPError as exc:
                logger.warning(f"[Mercado Livre] mais vendidos: {exc}")
                return {}
            blocos = _extrair_mais_vendidos_json(resp.text)
            if (
                resp.status_code != 200
                or any(x in str(resp.url).lower() for x in ("captcha", "account-verification"))
                or (not blocos and any(x in resp.text.lower() for x in ("captcha", "account-verification")))
            ):
                self._registrar_bloqueio(f"HTTP {resp.status_code} mais vendidos")
                return {}
            if blocos:
                _cache_mais_vendidos[url] = (time.monotonic(), blocos)
            return blocos

        raiz = buscar_pagina(MAIS_VENDIDOS_URL)
        out: list[OfertaCapturada] = []
        for categoria in self._categorias_meli():
            cards = raiz.get(categoria)
            if cards is None:
                cards = buscar_pagina(f"{MAIS_VENDIDOS_URL}/{categoria}").get(categoria, [])
            for posicao, card in enumerate(cards, 1):
                oferta = _parse_card(card)
                if oferta is None:
                    continue
                chave = oferta.sku or oferta.url
                if chave in vistas:
                    continue
                vistas.add(chave)
                oferta.origem_mais_vendidos = True
                oferta.origem_categoria_meli = True
                oferta.posicao_ranking = posicao
                out.append(oferta)
        return out

    def _buscar_ofertas_categoria(self, client: httpx.Client, vistas: set[str]) -> list[OfertaCapturada]:
        out: list[OfertaCapturada] = []
        for cat in self._categorias_meli():
            if self._html_em_pausa():
                break
            for page in range(1, 4):
                if self._html_em_pausa():
                    break
                params = {"category": cat}
                if page > 1:
                    params["page"] = page
                try:
                    resp = client.get(OFERTAS_URL, params=params)
                except httpx.HTTPError as e:
                    logger.warning(f"[Mercado Livre] ofertas cat={cat} page={page}: {e}")
                    break
                cards = _extrair_items_json(resp.text)
                bloqueada = (
                    resp.status_code != 200
                    or "captcha" in str(resp.url).lower()
                    or "account-verification" in str(resp.url).lower()
                    or (not cards and any(x in resp.text.lower() for x in ("captcha", "account-verification")))
                )
                if bloqueada:
                    self._registrar_bloqueio(f"HTTP {resp.status_code} cat={cat}")
                    break
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
                    oferta.origem_categoria_meli = True
                    out.append(oferta)
        return out

    def _buscar_lista_termos(self, client: httpx.Client, vistas: set[str]) -> list[OfertaCapturada]:
        """Tenta a listagem por termo. Se cair em captcha, só loga e segue."""
        out: list[OfertaCapturada] = []
        if self._html_em_pausa():
            return out
        for termo in self._termos_busca()[:8]:
            if self._html_em_pausa():
                break
            slug = quote_plus(termo).replace("+", "-")
            try:
                resp = client.get(LISTA_URL + slug)
            except httpx.HTTPError as e:
                logger.debug(f"[Mercado Livre] lista '{termo}': {e}")
                continue
            if "captcha" in str(resp.url) or "verification" in str(resp.url) or "suspicious" in str(resp.url):
                logger.debug(f"[Mercado Livre] lista '{termo}' bloqueada (captcha/verificação).")
                self._registrar_bloqueio(f"lista '{termo}'")
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
