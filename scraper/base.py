"""Classe base para todas as fontes de ofertas.

Cada scraper concreto só precisa implementar `buscar()`. `executar()` cuida de
timeout, retries e isolamento de erro — uma fonte instável nunca derruba o bot.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

from logger import logger


@dataclass
class OfertaCapturada:
    nome: str
    preco: float
    loja: str
    url: str
    preco_anterior: Optional[float] = None
    desconto: Optional[float] = None
    categoria: Optional[str] = None
    imagem: Optional[str] = None
    sku: Optional[str] = None
    capturado_em: Optional[datetime] = field(default_factory=datetime.now)
    # Proxies de "oferta quente" (quando a fonte informa).
    vendas: Optional[int] = None
    oferta_desde: Optional[datetime] = None
    codigo_cupom: Optional[str] = None
    min_gasto: Optional[float] = None
    url_carrinho: Optional[str] = None
    beneficio: Optional[str] = None
    validade: Optional[str] = None

    def __post_init__(self):
        if self.desconto is None and self.preco_anterior and self.preco_anterior > 0:
            self.desconto = round((1 - self.preco / self.preco_anterior) * 100, 1)


class Scraper:
    nome_fonte: str = "base"
    timeout: float = 10.0
    tentativas: int = 3

    def buscar(self) -> list[OfertaCapturada]:
        """Deve retornar a lista de ofertas encontradas nesta fonte. Sobrescrever."""
        raise NotImplementedError

    def executar(self) -> list[OfertaCapturada]:
        """Roda `buscar()` com retry e isolamento de exceções."""
        for tentativa in range(1, self.tentativas + 1):
            try:
                return self.buscar()
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                logger.warning(
                    f"[{self.nome_fonte}] falha de conexão (tentativa {tentativa}/{self.tentativas}): {e}"
                )
                time.sleep(1.5 * tentativa)
            except Exception as e:
                logger.error(f"[{self.nome_fonte}] erro inesperado: {e}")
                break
        logger.error(f"[{self.nome_fonte}] indisponível após {self.tentativas} tentativas. Seguindo sem esta fonte.")
        return []
