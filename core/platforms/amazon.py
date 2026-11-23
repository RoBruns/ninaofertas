"""Amazon Brasil: a comissão é a etiqueta no link, não a Creators API.

A busca é o HTML público de /s. Datacenter costuma receber verificação de
robô; nesse caso o ciclo segue sem oferta. URL sem /dp/ASIN ou sem a etiqueta
da conta não é enviada.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from core.config_provider import load_filtros_runtime as load_filtros
from core.http_headers import BROWSER_USER_AGENT
from core.platforms.base import OfertaCapturada, Scraper

BASE_URL = "https://www.amazon.com.br"
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{1,30}-20$")
_ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:[/?]|$)", re.I)


def normalizar_tag_amazon(valor: str) -> str:
    """Aceita o ID da loja ou o ID de rastreamento (termina em -20)."""
    texto = (valor or "").strip()
    if not _TAG_RE.fullmatch(texto):
        raise ValueError("etiqueta da Amazon inválida")
    return texto


def asin_amazon(url: str) -> str | None:
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower().removeprefix("www.")
    if host != "amazon.com.br":
        return None
    achado = _ASIN_RE.search(parsed.path)
    if achado is None:
        return None
    return achado.group(1).upper()


def url_afiliada_amazon(url: str, tag: str) -> str | None:
    """Produto da amazon.com.br com a etiqueta da conta, sem parâmetros alheios."""
    asin = asin_amazon(url)
    if asin is None:
        return None
    return f"{BASE_URL}/dp/{asin}?tag={tag}"


class AmazonScraper(Scraper):
    nome_fonte = "Amazon"
    timeout = 20.0

    def buscar(self) -> list[OfertaCapturada]:
        filtros = load_filtros()
        termos = (
            filtros.get("termos_busca")
            or filtros.get("palavras_chave")
            or filtros.get("categorias")
            or []
        )
        ofertas: list[OfertaCapturada] = []
        avisou_bloqueio = False
        headers = {"user-agent": BROWSER_USER_AGENT, "accept-language": "pt-BR,pt;q=0.9"}
        with httpx.Client(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            for termo in termos:
                try:
                    resposta = client.get(f"{BASE_URL}/s", params={"k": termo})
                except httpx.HTTPError as exc:
                    logger.warning(f"[Amazon] busca por '{termo}' falhou: {exc}")
                    continue
                if _pagina_bloqueada(str(resposta.url), resposta.status_code, resposta.text):
                    if not avisou_bloqueio:
                        avisou_bloqueio = True
                        logger.warning(
                            f"[Amazon] busca bloqueada (HTTP {resposta.status_code}). "
                            "Sem oferta desta loja neste ciclo."
                        )
                    break
                ofertas.extend(self._extrair_produtos(resposta.text))
        logger.info(f"[Amazon] {len(ofertas)} ofertas capturadas.")
        return ofertas

    def _extrair_produtos(self, html: str) -> list[OfertaCapturada]:
        soup = BeautifulSoup(html, "lxml")
        resultado: list[OfertaCapturada] = []
        for card in soup.select('div[data-component-type="s-search-result"]'):
            oferta = _parse_card(card)
            if oferta is not None:
                resultado.append(oferta)
        return resultado


def _pagina_bloqueada(url: str, status: int, html: str) -> bool:
    if status != 200:
        return True
    baixo = f"{url}\n{(html or '')[:4000]}".lower()
    marcas = ("validatecaptcha", "opfcaptcha", "/errors/validatecaptcha")
    if any(marca in baixo for marca in marcas):
        return True
    return 'data-asin="' not in (html or "")


def _parse_card(card) -> OfertaCapturada | None:
    asin = str(card.get("data-asin") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{10}", asin):
        return None
    titulo_el = card.select_one("h2 span")
    preco_el = card.select_one("span.a-price > span.a-offscreen")
    if titulo_el is None or preco_el is None:
        return None
    preco = _preco_para_float(preco_el.get_text())
    if preco is None:
        return None
    antigo_el = card.select_one("span.a-price.a-text-price > span.a-offscreen")
    imagem_el = card.select_one("img.s-image")
    return OfertaCapturada(
        nome=titulo_el.get_text(strip=True) or "Produto Amazon",
        preco=preco,
        preco_anterior=_preco_para_float(antigo_el.get_text()) if antigo_el else None,
        loja="Amazon",
        url=f"{BASE_URL}/dp/{asin}",
        imagem=imagem_el.get("src") if imagem_el else None,
        sku=asin,
    )


def _preco_para_float(texto: str) -> float | None:
    limpo = re.sub(r"[^\d,]", "", texto or "").replace(",", ".")
    if not limpo:
        return None
    try:
        return float(limpo)
    except ValueError:
        return None
