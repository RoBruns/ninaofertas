"""Aplicacao FastAPI da camada de gestao."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.errors import install_error_handlers
from api.ratelimit import limiter
from api.routers import (
    accounts,
    audit,
    auth,
    bots,
    campaigns,
    credentials,
    expenses,
    groups,
    health,
    niches,
    phones,
    platforms,
    sales,
    users,
)
from api.security import validate_security_config


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    validate_security_config()
    limiter.clear()
    yield


app = FastAPI(
    title="Nina Ofertas API",
    version="0.5.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
    lifespan=lifespan,
)

origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

install_error_handlers(app)
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(platforms.router, prefix="/api")
app.include_router(accounts.router, prefix="/api")
app.include_router(credentials.router, prefix="/api")
app.include_router(niches.router, prefix="/api")
app.include_router(phones.router, prefix="/api")
app.include_router(groups.router, prefix="/api")
app.include_router(bots.router, prefix="/api")
app.include_router(expenses.router, prefix="/api")
app.include_router(campaigns.router, prefix="/api")
app.include_router(sales.router, prefix="/api")
