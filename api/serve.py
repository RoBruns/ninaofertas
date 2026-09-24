"""Entrypoint da API com um unico socket dual-stack."""

from __future__ import annotations

import logging
import os
import socket

import uvicorn

logger = logging.getLogger(__name__)


def build_socket(port: int) -> socket.socket:
    """Cria e vincula um socket TCP, preferindo IPv6 dual-stack."""
    ipv6_socket: socket.socket | None = None
    try:
        ipv6_socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        ipv6_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ipv6_socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        ipv6_socket.bind(("::", port))
        return ipv6_socket
    except OSError:
        if ipv6_socket is not None:
            ipv6_socket.close()
        logger.warning("IPv6 indisponivel; iniciando a API somente em IPv4")

    ipv4_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        ipv4_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ipv4_socket.bind(("0.0.0.0", port))
        return ipv4_socket
    except OSError:
        ipv4_socket.close()
        raise


def main() -> None:
    """Inicia o Uvicorn usando o socket previamente configurado."""
    sock = build_socket(int(os.getenv("PORT", "8000")))
    config = uvicorn.Config(
        "api.main:app",
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
    try:
        uvicorn.Server(config).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
