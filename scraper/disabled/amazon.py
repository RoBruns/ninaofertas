"""Fonte: Amazon BR — scraping da página de busca (não há API pública gratuita).

Amazon muda o HTML com frequência e pode bloquear requisições automatizadas.
Os seletores abaixo refletem o layout usado no momento da escrita; se pararem
de funcionar, inspecione o HTML atual em `https://www.amazon.com.br/s?k=...`
e ajuste apenas os seletores — o resto do pipeline não muda.
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from config import load_filtros
from logger import logger
from scraper.base import OfertaCapturada, Scraper

BASE_URL = "https://www.amazon.com.br"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}


def _preco_para_float(texto: str) -> float | None:
    if not texto:
        return None
    limpo = re.sub(r"[^\d,]", "", texto).replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return None


class AmazonScraper(Scraper):
    nome_fonte = "Amazon"

    def _termos_busca(self) -> list[str]:
        """Prioridade: termos_busca (nicho) > palavras_chave > categorias."""
        filtros = load_filtros()
        return (
            filtros.get("termos_busca")
            or filtros.get("palavras_chave")
            or filtros.get("categorias")
            or ["oferta"]
        )

    def buscar(self) -> list[OfertaCapturada]:
        ofertas: list[OfertaCapturada] = []
        with httpx.Client(timeout=self.timeout, headers=HEADERS, follow_redirects=True) as client:
            for termo in self._termos_busca():
                resp = client.get(f"{BASE_URL}/s", params={"k": termo})
                if resp.status_code != 200:
                    logger.warning(f"[Amazon] busca por '{termo}' retornou HTTP {resp.status_code} (bloqueio/anti-bot provável)")
                    continue
                soup = BeautifulSoup(resp.text, "lxml")
                cards = soup.select('div[data-component-type="s-search-result"]')
                for card in cards:
                    try:
                        oferta = self._parse_card(card)
                        if oferta:
                            ofertas.append(oferta)
                    except Exception:
                        continue
        return ofertas

    def _parse_card(self, card) -> OfertaCapturada | None:
        titulo_el = card.select_one("h2 span")
        link_el = card.select_one("h2 a")
        preco_el = card.select_one("span.a-price > span.a-offscreen")
        preco_antigo_el = card.select_one("span.a-price.a-text-price > span.a-offscreen")
        imagem_el = card.select_one("img.s-image")

        if not (titulo_el and link_el and preco_el):
            return None

        preco = _preco_para_float(preco_el.get_text())
        if preco is None:
            return None

        href = link_el.get("href", "")
        url = href if href.startswith("http") else f"{BASE_URL}{href}"

        return OfertaCapturada(
            nome=titulo_el.get_text(strip=True),
            preco=preco,
            preco_anterior=_preco_para_float(preco_antigo_el.get_text()) if preco_antigo_el else None,
            loja="Amazon",
            url=url.split("/ref=")[0],
            imagem=imagem_el.get("src") if imagem_el else None,
            sku=card.get("data-asin"),
        )
