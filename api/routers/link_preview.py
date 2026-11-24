"""Página pública da prévia clicável. Sem auth: o WhatsApp e o grupo abrem o link."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from api.errors import APIError
from api.ratelimit import client_ip, limiter
from core.link_unfurl import eh_robo_previa, html_cartao, ler_token

router = APIRouter(tags=["link-preview"])


@router.get("/p/{token}")
def abrir_previa(token: str, request: Request) -> Response:
    if not limiter.hit("link-preview", client_ip(request), 600, 60):
        raise APIError(429, "RATE_LIMITED", "Limite de tentativas excedido")
    dados = ler_token(token)
    if dados is None:
        raise APIError(404, "NOT_FOUND", "Link não encontrado")
    destino, titulo, imagem = dados
    if eh_robo_previa(request.headers.get("user-agent")):
        pagina = HTMLResponse(html_cartao(titulo, imagem, destino))
        pagina.headers["Cache-Control"] = "private, no-store"
        pagina.headers["Vary"] = "User-Agent"
        return pagina
    destino_resposta = RedirectResponse(destino, status_code=302)
    destino_resposta.headers["Cache-Control"] = "private, no-store"
    destino_resposta.headers["Vary"] = "User-Agent"
    return destino_resposta
