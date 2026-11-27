"""Catálogo padrão de fontes BR (estilo pega-oferta)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogSource:
    slug: str
    name: str
    kind: str  # promobit | rss
    url: str
    default_enabled: bool = False


# Ligar em 1 clique no painel; coleta alimenta mirror_inbox dos bots ativos.
DEFAULT_FEED_SOURCES: tuple[CatalogSource, ...] = (
    CatalogSource(
        slug="promobit",
        name="Promobit",
        kind="promobit",
        url="https://www.promobit.com.br/",
        # Em produção fica off até ligar no dash — evita enfileirar sozinho no deploy.
        default_enabled=False,
    ),
    CatalogSource(
        slug="canaltech",
        name="Canaltech",
        kind="rss",
        url="https://canaltech.com.br/rss/",
    ),
    CatalogSource(
        slug="adrenaline",
        name="Adrenaline",
        kind="rss",
        url="https://www.adrenaline.com.br/feed/",
    ),
    CatalogSource(
        slug="tecnoblog",
        name="Tecnoblog",
        kind="rss",
        url="https://tecnoblog.net/feed/",
    ),
    CatalogSource(
        slug="meiobit",
        name="Meio Bit",
        kind="rss",
        url="https://meiobit.com/feed/",
    ),
    CatalogSource(
        slug="hardware",
        name="Hardware.com.br",
        kind="rss",
        url="https://www.hardware.com.br/feed/",
    ),
    CatalogSource(
        slug="kabum-blog",
        name="KaBuM! Blog",
        kind="rss",
        url="https://www.kabum.com.br/blog/feed/",
    ),
)
