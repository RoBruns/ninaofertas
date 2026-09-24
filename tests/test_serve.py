"""Testes do socket dual-stack usado para servir a API."""

import socket

import pytest

from api.serve import build_socket


def _assert_accepts(family: socket.AddressFamily, host: str) -> None:
    server = build_socket(0)
    client: socket.socket | None = None
    connection: socket.socket | None = None
    try:
        server.listen()
        server.settimeout(1)
        port = server.getsockname()[1]

        client = socket.socket(family, socket.SOCK_STREAM)
        client.settimeout(1)
        client.connect((host, port))
        connection, _ = server.accept()
    finally:
        if connection is not None:
            connection.close()
        if client is not None:
            client.close()
        server.close()


def test_build_socket_desabilita_ipv6_only() -> None:
    if not socket.has_ipv6:
        pytest.skip("IPv6 nao esta disponivel neste sistema")

    server = build_socket(0)
    try:
        assert server.family == socket.AF_INET6
        assert server.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 0
    finally:
        server.close()


def test_socket_aceita_ipv4() -> None:
    _assert_accepts(socket.AF_INET, "127.0.0.1")


def test_socket_dual_stack_aceita_ipv6() -> None:
    if not socket.has_ipv6:
        pytest.skip("IPv6 nao esta disponivel neste sistema")

    _assert_accepts(socket.AF_INET6, "::1")
