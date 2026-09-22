"""Erros publicos e handlers que evitam vazamento de detalhes internos."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

STATUS_CODES = {
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL",
}


class APIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        fields: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields
        super().__init__(code)


def error_response(
    status_code: int,
    code: str,
    message: str,
    fields: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    detail: dict[str, Any] = {"code": code, "message": message}
    if fields is not None:
        detail["fields"] = fields
    return JSONResponse(status_code=status_code, content={"error": detail}, headers=headers)


def _validation_fields(exc: RequestValidationError) -> dict[str, str]:
    fields: dict[str, str] = {}
    for error in exc.errors():
        location = [str(item) for item in error.get("loc", ()) if item not in {"body", "query"}]
        field = ".".join(location) or "request"
        fields[field] = str(error.get("msg", "valor invalido"))
    return fields


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def api_error_handler(_request: Request, exc: APIError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.fields)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            422,
            "VALIDATION_ERROR",
            "Dados de entrada invalidos",
            _validation_fields(exc),
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(_request: Request, _exc: IntegrityError) -> JSONResponse:
        return error_response(409, "CONFLICT", "O recurso conflita com um registro existente")

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = STATUS_CODES.get(exc.status_code)
        if code is None:
            return error_response(500, "INTERNAL", "Erro interno do servidor")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # Nao registra a mensagem da excecao: ela pode conter SQL ou credenciais.
        logger.error(
            "Erro interno nao tratado: tipo=%s rota=%s",
            type(exc).__name__,
            request.url.path,
        )
        return error_response(500, "INTERNAL", "Erro interno do servidor")
