"""CRUD de nichos operacionais."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.audit import record_audit
from api.deps import get_current_user, get_db, limit_authenticated_write, require_role
from api.errors import APIError
from api.ratelimit import client_ip
from api.schemas.niche import NicheCreate, NicheResponse, NicheUpdate
from core.models import Bot, Niche, User

router = APIRouter(prefix="/niches", tags=["niches"])
AdminUser = Annotated[User, Depends(require_role("admin"))]


def _owned(session: Session, niche_id: int, owner_id: object) -> Niche:
    niche = session.scalar(select(Niche).where(Niche.id == niche_id, Niche.owner_id == owner_id))
    if niche is None:
        raise APIError(404, "NOT_FOUND", "Nicho nao encontrado")
    return niche


def _response(niche: Niche) -> NicheResponse:
    return NicheResponse(id=niche.id, slug=niche.slug, name=niche.name)


@router.get("", response_model=list[NicheResponse])
def list_niches(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> list[NicheResponse]:
    return [
        _response(item)
        for item in session.scalars(
            select(Niche).where(Niche.owner_id == user.id).order_by(Niche.name.asc())
        )
    ]


@router.post("", response_model=NicheResponse, status_code=201, dependencies=[Depends(limit_authenticated_write)])
def create_niche(
    payload: NicheCreate,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> NicheResponse:
    if session.scalar(select(Niche.id).where(Niche.owner_id == admin.id, Niche.slug == payload.slug)):
        raise APIError(409, "CONFLICT", "Ja existe um nicho com este slug")
    niche = Niche(owner_id=admin.id, slug=payload.slug, name=payload.name)
    session.add(niche)
    session.flush()
    response = _response(niche)
    record_audit(session, admin, "niche", str(niche.id), "create", None, response.model_dump(), client_ip(request))
    session.commit()
    return response


@router.patch("/{niche_id}", response_model=NicheResponse, dependencies=[Depends(limit_authenticated_write)])
def update_niche(
    niche_id: int,
    payload: NicheUpdate,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> NicheResponse:
    niche = _owned(session, niche_id, admin.id)
    before = _response(niche).model_dump()
    changes = payload.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise APIError(422, "VALIDATION_ERROR", "slug e name nao aceitam null")
    if "slug" in changes and session.scalar(
        select(Niche.id).where(Niche.owner_id == admin.id, Niche.slug == changes["slug"], Niche.id != niche.id)
    ):
        raise APIError(409, "CONFLICT", "Ja existe um nicho com este slug")
    for field, value in changes.items():
        setattr(niche, field, value)
    response = _response(niche)
    record_audit(session, admin, "niche", str(niche.id), "update", before, response.model_dump(), client_ip(request))
    session.commit()
    return response


@router.delete("/{niche_id}", status_code=204, dependencies=[Depends(limit_authenticated_write)])
def delete_niche(
    niche_id: int,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    niche = _owned(session, niche_id, admin.id)
    bots = list(session.scalars(select(Bot).where(Bot.niche_id == niche.id).order_by(Bot.name)))
    if bots:
        names = ", ".join(bot.name for bot in bots)
        raise APIError(409, "CONFLICT", f"Nicho vinculado aos bots: {names}", {"bots": names})
    before = _response(niche).model_dump()
    session.delete(niche)
    record_audit(session, admin, "niche", str(niche.id), "delete", before, None, client_ip(request))
    session.commit()
