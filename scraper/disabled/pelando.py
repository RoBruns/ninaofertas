"""Fonte: Pelando — scraping da página "Mais Quentes" (maior agregador de ofertas do BR).

Pelando não expõe API pública estável. O site usa CSS Modules com nomes de
classe parcialmente hasheados (ex: `_deal-card_1jdb6_25`), então em vez de
depender do hash inteiro, procuramos por classes que *contenham* o pedaço
estável (`deal-card`, `deal-card-store`, `deal-card-stamp`). Se a Pelando
mudar a estrutura, valide manualmente `https://www.pelando.com.br/mais-quentes`
e ajuste `_parse_card`.

Observação: a listagem não expõe o preço anterior/desconto (só o preço atual),
então `preco_anterior`/`desconto` ficam vazios para esta fonte — configure
`desconto_minimo: 0` se quiser que ofertas do Pelando passem pelo filtro.
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup, Tag

from logger import logger
from scraper.base import OfertaCapturada, Scraper

URL = "https://www.pelando.com.br/mais-quentes"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

PRECO_RE = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)")


def _preco_para_float(texto: str) -> float | None:
    match = PRECO_RE.search(texto)
    if not match:
        return None
    limpo = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return None


def _tem_classe_contendo(tag: Tag, pedaco: str) -> bool:
    return any(pedaco in c for c in tag.get("class", []))


class PelandoScraper(Scraper):
    nome_fonte = "Pelando"

    def buscar(self) -> list[OfertaCapturada]:
        with httpx.Client(timeout=self.timeout, headers=HEADERS, follow_redirects=True) as client:
            resp = client.get(URL)
            if resp.status_code != 200:
                logger.warning(f"[Pelando] retornou HTTP {resp.status_code} (bloqueio/anti-bot provável)")
                return []
            soup = BeautifulSoup(resp.text, "lxml")

        cards = soup.find_all("div", class_=lambda c: c and any("deal-card_" in x for x in c.split()))

        ofertas: list[OfertaCapturada] = []
        for card in cards:
            try:
                oferta = self._parse_card(card)
                if oferta:
                    ofertas.append(oferta)
            except Exception:
                continue
        return ofertas

    def _parse_card(self, card: Tag) -> OfertaCapturada | None:
        titulo_link = card.select_one("h3 a")
        if not titulo_link:
            return None

        preco_el = next(
            (el for el in card.find_all(["span", "div"]) if _tem_classe_contendo(el, "deal-card-stamp")),
            None,
        )
        if preco_el is None:
            return None
        preco = _preco_para_float(preco_el.get_text(" ", strip=True))
        if preco is None:
            return None

        loja_container = next(
            (el for el in card.find_all("div") if _tem_classe_contendo(el, "deal-card-store")),
            None,
        )
        loja_link = loja_container.find("a") if loja_container else None
        loja = loja_link.get_text(strip=True) if loja_link else "Pelando"

        imagem_el = card.find("img")
        href = titulo_link["href"]
        url = href if href.startswith("http") else f"https://www.pelando.com.br{href}"

        return OfertaCapturada(
            nome=titulo_link.get_text(strip=True),
            preco=preco,
            loja=loja,
            url=url,
            imagem=imagem_el.get("src") if imagem_el else None,
        )
