"""Trava contra rodar a suíte no banco de produção.

Os fixtures de Postgres apagam o schema `public` inteiro (`DROP SCHEMA public
CASCADE`) para montar um banco limpo. Apontado para produção por engano, isso
destruiria `ofertas` e `envios` — o histórico do bot em operação.
"""

from __future__ import annotations

import pytest

# `railway` é o nome do banco de produção na instância Postgres da Railway.
BANCOS_PROTEGIDOS = frozenset({"railway"})


def recusar_banco_de_producao(database: str | None) -> None:
    nome = (database or "").strip().lower()
    if not nome or nome in BANCOS_PROTEGIDOS:
        pytest.fail(
            f"TEST_DATABASE_URL aponta para o banco '{database}'. Os testes apagam o "
            "schema public; use um banco descartável (ex.: api_test). Ver docs/DEPLOYMENT.md.",
            pytrace=False,
        )
