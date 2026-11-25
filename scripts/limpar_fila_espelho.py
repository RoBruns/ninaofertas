"""Marca mirror_inbox pending como skipped (fila_limpa).

Uso em produção (sem imprimir segredo):

  railway run -s nina-worker -- python -m scripts.limpar_fila_espelho
"""

from __future__ import annotations

from worker.mirror import limpar_fila_pendente


def main() -> None:
    n = limpar_fila_pendente()
    print(f"fila_limpa={n}")


if __name__ == "__main__":
    main()