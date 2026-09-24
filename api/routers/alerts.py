"""Listagem e ciclo de vida manual dos alertas acionaveis."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from api.audit import record_audit
from api.deps import get_current_user, get_db, limit_authenticated_write, require_role
from api.errors import APIError
from api.ratelimit import client_ip
from api.schemas.alert import AlertResponse, AlertSeverity, AlertStatus
from api.schemas.common import PaginatedResponse
from core.models import Alert, User

router = APIRouter(prefix="/alerts", tags=["alerts"])
OperatorUser = Annotated[User, Depends(require_role("operator", "admin"))]
AdminUser = Annotated[User, Depends(require_role("admin"))]


def _response(alert: Alert) -> AlertResponse:
    return AlertResponse.model_validate(alert, from_attributes=True)


def _owned(session: Session, alert_id: UUID, owner_id: UUID) -> Alert:
    alert = session.scalar(select(Alert).where(Alert.id == alert_id, Alert.owner_id == owner_id))
    if alert is None:
        raise APIError(404, "NOT_FOUND", "Alerta nao encontrado")
    return alert


@router.get("", response_model=PaginatedResponse[AlertResponse])
def list_alerts(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    status: AlertStatus | None = None,
    severity: AlertSeverity | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PaginatedResponse[AlertResponse]:
    statement = select(Alert).where(Alert.owner_id == user.id)
    if status is None:
        statement = statement.where(Alert.status.in_(("open", "acknowledged")))
    else:
        statement = statement.where(Alert.status == status)
    if severity is not None:
        statement = statement.where(Alert.severity == severity)
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    severity_order = case((Alert.severity == "critical", 0), else_=1)
    items = list(
        session.scalars(
            statement.order_by(severity_order, Alert.last_seen_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return PaginatedResponse(
        items=[_response(item) for item in items],
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{alert_id}/acknowledge",
    response_model=AlertResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def acknowledge_alert(
    alert_id: UUID,
    _user: OperatorUser,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> AlertResponse:
    alert = _owned(session, alert_id, current_user.id)
    if alert.status == "resolved":
        raise APIError(409, "CONFLICT", "Alerta ja resolvido")
    alert.status = "acknowledged"
    session.commit()
    return _response(alert)


@router.post(
    "/{alert_id}/resolve",
    response_model=AlertResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def resolve_alert(
    alert_id: UUID,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> AlertResponse:
    from datetime import datetime, timezone

    alert = _owned(session, alert_id, admin.id)
    before = _response(alert).model_dump(mode="json")
    if alert.status != "resolved":
        alert.status = "resolved"
        alert.resolved_at = datetime.now(timezone.utc)
    response = _response(alert)
    record_audit(
        session,
        admin,
        "alert",
        str(alert.id),
        "resolve",
        before,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response
