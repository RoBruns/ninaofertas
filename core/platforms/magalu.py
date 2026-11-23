"""Magazine Luiza: a comissão mora na loja do Magazine Você, não numa API.

A busca pública do site costuma responder 403 para datacenter. O parser fica
pronto para o HTML com `__NEXT_DATA__`; se a página bloquear, o ciclo segue
sem oferta da Magalu e sem link de outra pessoa.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from core.config_provider import load_filtros_runtime as load_filtros
from core.http_headers import BROWSER_USER_AGENT
from core.platforms.base import OfertaCapturada, Scraper

BASE_URL = "https://www.magazineluiza.com.br"
_LOJA_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,80}")
_VOCE_RE = re.compile(r"magazinevoce\.com\.br/([A-Za-z0-9-]+)", re.IGNORECASE)
_HOSTS_PRODUTO = {"magazineluiza.com.br", "m.magazineluiza.com.br", "magalu.com"}


def normalizar_loja_magalu(valor: str) -> str:
    """Aceita o slug ou a URL da página (magazinevoce.com.br/suajoja)."""
    texto = (valor or "").strip()
    achado = _VOCE_RE.search(texto)
    if achado:
        texto = achado.group(1)
    else:
        texto = texto.strip("/").split("/")[0]
    texto = texto.lower()
    if not _LOJA_RE.fullmatch(texto):
        raise ValueError("loja do Magazine Você inválida")
    return texto


def url_afiliada_magalu(url: str, loja: str) -> str | None:
    """Troca o produto do site ou de outra loja pelo caminho da loja informada."""
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower().removeprefix("www.")
    partes = [parte for parte in parsed.path.split("/") if parte]
    if host == "magazinevoce.com.br":
        if len(partes) < 2:
            return None
        partes = partes[1:]
    elif host not in _HOSTS_PRODUTO:
        return None
    if "p" not in partes:
        return None
    caminho = "/".join(partes)
    return f"https://www.magazinevoce.com.br/{loja}/{caminho}"


class MagaluScraper(Scraper):
    nome_fonte = "Magalu"
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
                    resposta = client.get(f"{BASE_URL}/busca/{termo}/")
                except httpx.HTTPError as exc:
                    logger.warning(f"[Magalu] busca por '{termo}' falhou: {exc}")
                    continue
                if resposta.status_code != 200:
                    if not avisou_bloqueio:
                        avisou_bloqueio = True
                        logger.warning(
                            f"[Magalu] busca bloqueada (HTTP {resposta.status_code}). "
                            "Sem oferta desta loja neste ciclo."
                        )
                    if resposta.status_code in {403, 429}:
                        break
                    continue
                ofertas.extend(self._extrair_produtos(resposta.text))
        logger.info(f"[Magalu] {len(ofertas)} ofertas capturadas.")
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
        resultado: list[OfertaCapturada] = []
        for produto in _listar_produtos(dados):
            oferta = _parse_produto(produto)
            if oferta is not None:
                resultado.append(oferta)
        return resultado


def _listar_produtos(dados: object) -> list[dict]:
    encontrados: list[dict] = []

    def percorrer(node: object) -> None:
        if isinstance(node, dict):
            if "price" in node and ("title" in node or "referenceId" in node):
                encontrados.append(node)
                return
            for valor in node.values():
                percorrer(valor)
        elif isinstance(node, list):
            for item in node:
                percorrer(item)

    percorrer(dados)
    return encontrados


def _parse_produto(produto: dict) -> OfertaCapturada | None:
    price = produto.get("price") or {}
    preco = price.get("bestPrice") if isinstance(price, dict) else None
    if not isinstance(preco, (int, float)):
        preco = price.get("price") if isinstance(price, dict) else produto.get("price")
    if not isinstance(preco, (int, float)):
        return None
    preco_anterior = price.get("price") if isinstance(price, dict) else None
    if not isinstance(preco_anterior, (int, float)) or preco_anterior <= preco:
        preco_anterior = None
    caminho = str(produto.get("path") or produto.get("url") or "")
    if not caminho:
        return None
    url = caminho if caminho.startswith("http") else f"{BASE_URL}/{caminho.lstrip('/')}"
    imagem = None
    imagens = produto.get("image") or produto.get("images")
    if isinstance(imagens, list) and imagens:
        imagem = imagens[0] if isinstance(imagens[0], str) else imagens[0].get("url")
    elif isinstance(imagens, str):
        imagem = imagens
    return OfertaCapturada(
        nome=str(produto.get("title") or produto.get("referenceId") or "Produto Magalu"),
        preco=float(preco),
        preco_anterior=float(preco_anterior) if preco_anterior else None,
        loja="Magalu",
        url=url,
        imagem=imagem,
        sku=str(produto.get("referenceId") or produto.get("id") or "") or None,
    )
