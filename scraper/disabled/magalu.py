"""Fonte: Magazine Luiza — scraping da página de busca (sem API pública gratuita).

O site é renderizado em Next.js e embute os dados dos produtos em um bloco
`<script id="__NEXT_DATA__">` como JSON. Se o Magalu mudar a estrutura desse
JSON, ajuste apenas `_extrair_produtos`; o resto do pipeline não muda.
"""
from __future__ import annotations

import json

import httpx
from bs4 import BeautifulSoup

from config import load_filtros
from logger import logger
from scraper.base import OfertaCapturada, Scraper

BASE_URL = "https://www.magazineluiza.com.br"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}


class MagaluScraper(Scraper):
    nome_fonte = "Magalu"

    def _termos_busca(self) -> list[str]:
        filtros = load_filtros()
        return filtros.get("palavras_chave") or filtros.get("categorias") or ["oferta"]

    def buscar(self) -> list[OfertaCapturada]:
        ofertas: list[OfertaCapturada] = []
        with httpx.Client(timeout=self.timeout, headers=HEADERS, follow_redirects=True) as client:
            for termo in self._termos_busca():
                resp = client.get(f"{BASE_URL}/busca/{termo}/")
                if resp.status_code != 200:
                    logger.warning(f"[Magalu] busca por '{termo}' retornou HTTP {resp.status_code} (bloqueio/anti-bot provável)")
                    continue
                ofertas.extend(self._extrair_produtos(resp.text))
        return ofertas

    def _extrair_produtos(self, html: str) -> list[OfertaCapturada]:
        soup = BeautifulSoup(html, "lxml")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            return []

        try:
            dados = json.loads(script.string)
        except json.JSONDecodeError:
            return []

        produtos = self._buscar_lista_produtos(dados)
        resultado = []
        for p in produtos:
            try:
                oferta = self._parse_produto(p)
                if oferta:
                    resultado.append(oferta)
            except Exception:
                continue
        return resultado

    @staticmethod
    def _buscar_lista_produtos(dados: dict) -> list[dict]:
        """Procura recursivamente por uma lista de produtos dentro do JSON do Next.js
        (a chave/caminho exato varia entre deploys do Magalu)."""
        encontrados: list[dict] = []

        def _percorrer(node):
            if isinstance(node, dict):
                if "price" in node and ("title" in node or "referenceId" in node):
                    encontrados.append(node)
                    return
                for v in node.values():
                    _percorrer(v)
            elif isinstance(node, list):
                for item in node:
                    _percorrer(item)

        _percorrer(dados)
        return encontrados

    def _parse_produto(self, p: dict) -> OfertaCapturada | None:
        price = p.get("price") or {}
        preco = price.get("bestPrice") or price.get("price") or p.get("price")
        if not isinstance(preco, (int, float)):
            return None
        preco_anterior = price.get("price") if isinstance(price, dict) else None
        if preco_anterior == preco:
            preco_anterior = None

        path = p.get("path") or p.get("url") or ""
        url = path if str(path).startswith("http") else f"{BASE_URL}/{str(path).lstrip('/')}"

        imagem = None
        imagens = p.get("image") or p.get("images")
        if isinstance(imagens, list) and imagens:
            imagem = imagens[0] if isinstance(imagens[0], str) else imagens[0].get("url")
        elif isinstance(imagens, str):
            imagem = imagens

        return OfertaCapturada(
            nome=p.get("title") or p.get("referenceId") or "Produto Magalu",
            preco=float(preco),
            preco_anterior=float(preco_anterior) if preco_anterior else None,
            loja="Magalu",
            url=url,
            imagem=imagem,
            sku=p.get("referenceId") or p.get("id"),
        )
