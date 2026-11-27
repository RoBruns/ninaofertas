"""API operacional Nina V3: decisões, esteira, ofertas, cupons, VIP, monitor."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db, limit_authenticated_write, require_role
from api.errors import APIError
from api.schemas.common import PaginatedResponse
from api.schemas.v3_ops import (
    CouponDestination,
    CouponDispatchRequest,
    CouponDispatchResponse,
    CouponRadarCreate,
    CouponRadarResponse,
    CouponRadarUpdate,
    DecisionItem,
    DecisionsResponse,
    DecisionsStats,
    FeedSourceCreate,
    FeedSourceResponse,
    FeedSourceUpdate,
    FeedSyncResponse,
    MirrorInboxItem,
    MirrorInboxPatch,
    MonitorCreate,
    MonitorResponse,
    MonitorUpdate,
    OfferCard,
    VipCreate,
    VipResponse,
    VipUpdate,
)
from core import relogio
from core.coupon_store import normalizar_loja
from core.crypto import decrypt
from core.feed_collect import coletar_fonte, ensure_feed_sources
from core.models import (
    Alert,
    Bot,
    BotGroup,
    CouponRadar,
    FeedSource,
    Group,
    MirrorInbox,
    Oferta,
    Phone,
    PlatformAccount,
    PlatformCredential,
    PriceMonitor,
    User,
    VipRequest,
)
from core.settings import settings

router = APIRouter(prefix="/v3", tags=["v3"])
Operator = Annotated[User, Depends(require_role("operator", "admin"))]


@router.get("/decisions", response_model=DecisionsResponse)
def decisions(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> DecisionsResponse:
    owner = user.tenant_id
    pending = int(
        session.scalar(
            select(func.count())
            .select_from(MirrorInbox)
            .where(MirrorInbox.owner_id == owner, MirrorInbox.status == "pending")
        )
        or 0
    )
    open_alerts = int(
        session.scalar(
            select(func.count())
            .select_from(Alert)
            .where(Alert.owner_id == owner, Alert.status.in_(("open", "acknowledged")))
        )
        or 0
    )
    cups = int(
        session.scalar(
            select(func.count())
            .select_from(CouponRadar)
            .where(CouponRadar.owner_id == owner, CouponRadar.status == "ativo")
        )
        or 0
    )
    vip_waiting = int(
        session.scalar(
            select(func.count())
            .select_from(VipRequest)
            .where(VipRequest.owner_id == owner, VipRequest.status == "waiting")
        )
        or 0
    )
    monitors_hit = int(
        session.scalar(
            select(func.count())
            .select_from(PriceMonitor)
            .where(PriceMonitor.owner_id == owner, PriceMonitor.status == "alvo_atingido")
        )
        or 0
    )

    items: list[DecisionItem] = []
    if pending:
        items.append(
            DecisionItem(
                id="mirror-pending",
                severity="urgent" if pending > 20 else "warn",
                title=f"{pending} oferta(s) na esteira do espelho",
                detail="Revise ou deixe o worker drenar a fila.",
                href="/esteira",
            )
        )
    if open_alerts:
        items.append(
            DecisionItem(
                id="alerts",
                severity="urgent",
                title=f"{open_alerts} alerta(s) abertos",
                detail="Credencial, telefone ou freio podem estar travando o envio.",
                href="/alertas",
            )
        )
    offline = session.scalars(
        select(Phone).where(
            Phone.owner_id == owner,
            Phone.status != "connected",
        )
    ).all()
    for phone in offline[:5]:
        items.append(
            DecisionItem(
                id=f"phone-{phone.id}",
                severity="urgent",
                title=f"Telefone {phone.label} offline",
                detail=f"Status: {phone.status}. Reconecte o QR na Evolution.",
                href="/telefones",
            )
        )
    bad_creds = session.scalars(
        select(PlatformCredential)
        .join(PlatformAccount, PlatformAccount.id == PlatformCredential.account_id)
        .where(
            PlatformAccount.owner_id == owner,
            PlatformCredential.status.in_(("invalid", "expired", "error")),
        )
    ).all()
    for cred in bad_creds[:5]:
        items.append(
            DecisionItem(
                id=f"cred-{cred.id}",
                severity="urgent",
                title="Credencial de afiliado com problema",
                detail=cred.last_error or f"Status {cred.status}",
                href="/contas",
            )
        )
    if vip_waiting:
        items.append(
            DecisionItem(
                id="vip",
                severity="info",
                title=f"{vip_waiting} pedido(s) VIP aguardando",
                detail="Batemos desejo × catálogo quando houver oferta na faixa.",
                href="/vip",
            )
        )
    if monitors_hit:
        items.append(
            DecisionItem(
                id="monitor",
                severity="warn",
                title=f"{monitors_hit} monitor(es) no preço-alvo",
                detail="Confira e dispare se ainda valer a pena.",
                href="/monitor",
            )
        )
    if not items:
        items.append(
            DecisionItem(
                id="ok",
                severity="info",
                title="Nada urgente agora",
                detail="Espelho, alertas e canais estão calmos.",
                href="/esteira",
            )
        )
    return DecisionsResponse(
        items=items,
        stats=DecisionsStats(
            mirror_pending=pending,
            open_alerts=open_alerts,
            cups_active=cups,
            vip_waiting=vip_waiting,
            monitors_hit=monitors_hit,
        ),
    )


@router.get("/mirror-inbox", response_model=PaginatedResponse[MirrorInboxItem])
def list_mirror_inbox(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    status: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 40,
) -> PaginatedResponse[MirrorInboxItem]:
    stmt = select(MirrorInbox).where(MirrorInbox.owner_id == user.tenant_id)
    if status:
        stmt = stmt.where(MirrorInbox.status == status)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(
        stmt.order_by(MirrorInbox.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return PaginatedResponse(
        items=[MirrorInboxItem.model_validate(r, from_attributes=True) for r in rows],
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/mirror-inbox/{item_id}",
    response_model=MirrorInboxItem,
    dependencies=[Depends(limit_authenticated_write)],
)
def patch_mirror_inbox(
    item_id: UUID,
    payload: MirrorInboxPatch,
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> MirrorInboxItem:
    item = session.scalar(
        select(MirrorInbox).where(MirrorInbox.id == item_id, MirrorInbox.owner_id == user.tenant_id)
    )
    if item is None:
        raise APIError(404, "NOT_FOUND", "Item da esteira não encontrado")
    item.status = payload.status
    item.skip_reason = payload.skip_reason or ("manual" if payload.status == "skipped" else None)
    if payload.status != "pending":
        item.processed_at = datetime.now(timezone.utc)
    else:
        item.processed_at = None
        item.skip_reason = None
    session.commit()
    session.refresh(item)
    return MirrorInboxItem.model_validate(item, from_attributes=True)


@router.get("/offers", response_model=PaginatedResponse[OfferCard])
def list_offers(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    q: str | None = None,
    loja: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
) -> PaginatedResponse[OfferCard]:
    # Ofertas legadas não têm owner_id — filtra por envios do tenant quando possível.
    from core.models import Bot, Envio

    bot_ids = select(Bot.id).where(Bot.owner_id == user.tenant_id)
    offer_ids = select(Envio.oferta_id).where(Envio.bot_id.in_(bot_ids)).distinct()
    stmt = select(Oferta).where(
        or_(
            Oferta.id.in_(offer_ids),
            Oferta.categoria == "espelho",
            # fontes: preço real + imagem (coleta antiga gravava R$ 0 / sem foto)
            and_(
                Oferta.categoria == "fonte",
                Oferta.preco >= 1,
                Oferta.imagem.is_not(None),
                Oferta.imagem != "",
            ),
        )
    )
    if q:
        stmt = stmt.where(Oferta.nome.ilike(f"%{q}%"))
    if loja:
        stmt = stmt.where(Oferta.loja.ilike(f"%{loja}%"))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(
        stmt.order_by(Oferta.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = [
        OfferCard(
            id=o.id,
            nome=o.nome,
            preco=Decimal(str(o.preco)) if o.preco is not None else None,
            preco_anterior=Decimal(str(o.preco_anterior)) if o.preco_anterior is not None else None,
            loja=o.loja,
            url=o.url,
            imagem=o.imagem,
            categoria=o.categoria,
            criado_em=o.capturado_em,
        )
        for o in rows
    ]
    return PaginatedResponse(items=items, total=int(total), page=page, page_size=page_size)


@router.get("/coupons", response_model=list[CouponRadarResponse])
def list_coupons(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    status: str | None = None,
) -> list[CouponRadarResponse]:
    stmt = select(CouponRadar).where(CouponRadar.owner_id == user.tenant_id)
    if status:
        stmt = stmt.where(CouponRadar.status == status)
    # ativo → acabando → expirado, depois mais novos
    ordem = case(
        (CouponRadar.status == "ativo", 1),
        (CouponRadar.status == "acabando", 2),
        else_=3,
    )
    rows = session.scalars(
        stmt.order_by(ordem, CouponRadar.created_at.desc()).limit(200)
    ).all()
    return [CouponRadarResponse.model_validate(r, from_attributes=True) for r in rows]


@router.get("/coupon-destinations", response_model=list[CouponDestination])
def list_coupon_destinations(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> list[CouponDestination]:
    """Grupos ligados a bots da conta — destinos do disparo com arte."""
    rows = session.execute(
        select(Group, Phone, Bot)
        .join(BotGroup, BotGroup.group_id == Group.id)
        .join(Bot, Bot.id == BotGroup.bot_id)
        .outerjoin(Phone, Phone.id == Bot.phone_id)
        .where(
            Bot.owner_id == user.tenant_id,
            Bot.archived_at.is_(None),
            BotGroup.is_active.is_(True),
            Group.status != "archived",
            Group.whatsapp_id.is_not(None),
        )
        .order_by(Group.name.asc().nulls_last())
    ).all()
    vistos: set[UUID] = set()
    out: list[CouponDestination] = []
    for group, phone, bot in rows:
        if group.id in vistos:
            continue
        vistos.add(group.id)
        out.append(
            CouponDestination(
                id=group.id,
                name=group.name or group.whatsapp_id or str(group.id),
                phone_label=phone.label if phone else None,
                bot_name=bot.name,
                whatsapp_id=group.whatsapp_id or "",
            )
        )
    return out


@router.post(
    "/coupons",
    response_model=CouponRadarResponse,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_coupon(
    payload: CouponRadarCreate,
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> CouponRadarResponse:
    data = payload.model_dump()
    data["store"] = normalizar_loja(data.get("store"))
    row = CouponRadar(id=uuid4(), owner_id=user.tenant_id, **data)
    session.add(row)
    session.commit()
    session.refresh(row)
    return CouponRadarResponse.model_validate(row, from_attributes=True)


@router.patch(
    "/coupons/{coupon_id}",
    response_model=CouponRadarResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def patch_coupon(
    coupon_id: UUID,
    payload: CouponRadarUpdate,
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> CouponRadarResponse:
    row = session.scalar(
        select(CouponRadar).where(
            CouponRadar.id == coupon_id, CouponRadar.owner_id == user.tenant_id
        )
    )
    if row is None:
        raise APIError(404, "NOT_FOUND", "Cupom não encontrado")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "store" and value is not None:
            value = normalizar_loja(value)
        if key == "status" and value == "ativo":
            row.report_count = 0
        setattr(row, key, value)
    row.updated_at = relogio.agora_banco()
    session.commit()
    session.refresh(row)
    return CouponRadarResponse.model_validate(row, from_attributes=True)


@router.delete(
    "/coupons/{coupon_id}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def delete_coupon(
    coupon_id: UUID,
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    row = session.scalar(
        select(CouponRadar).where(
            CouponRadar.id == coupon_id, CouponRadar.owner_id == user.tenant_id
        )
    )
    if row is None:
        raise APIError(404, "NOT_FOUND", "Cupom não encontrado")
    session.delete(row)
    session.commit()


def _evolution_send(
    *,
    instancia: str,
    token: str | None,
    destino: str,
    texto: str,
    imagem_b64: str | None,
) -> bool:
    import httpx

    headers = {
        "apikey": token or settings.evolution_api_key,
        "Content-Type": "application/json",
    }
    base = settings.evolution_api_url.rstrip("/")
    with httpx.Client(timeout=25.0) as client:
        if imagem_b64:
            media = imagem_b64
            if "base64," in media[:80]:
                media = media.split("base64,", 1)[1]
            url = f"{base}/message/sendMedia/{instancia}"
            payload: dict[str, object] = {
                "number": destino,
                "mediatype": "image",
                "media": media,
                "caption": texto,
                "mimetype": "image/png",
                "fileName": "cupom.png",
            }
        else:
            url = f"{base}/message/sendText/{instancia}"
            payload = {"number": destino, "text": texto}
        resp = client.post(url, json=payload, headers=headers)
        if resp.status_code == 401 and token:
            headers["apikey"] = settings.evolution_api_key
            resp = client.post(url, json=payload, headers=headers)
        return resp.status_code < 400


@router.post(
    "/coupons/{coupon_id}/dispatch",
    response_model=CouponDispatchResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def dispatch_coupon(
    coupon_id: UUID,
    payload: CouponDispatchRequest,
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> CouponDispatchResponse:
    """Dispara cupom com arte para grupos escolhidos (ação manual do operador)."""
    row = session.scalar(
        select(CouponRadar).where(
            CouponRadar.id == coupon_id, CouponRadar.owner_id == user.tenant_id
        )
    )
    if row is None:
        raise APIError(404, "NOT_FOUND", "Cupom não encontrado")
    if payload.link:
        row.url = payload.link.strip()[:500]
        row.updated_at = relogio.agora_banco()

    grupos = session.scalars(
        select(Group).where(
            Group.id.in_(payload.group_ids),
            Group.owner_id == user.tenant_id,
        )
    ).all()
    if not grupos:
        return CouponDispatchResponse(
            ok=False, enviados=0, total=0, erro="Nenhum grupo válido selecionado."
        )

    enviados = 0
    for group in grupos:
        if not group.whatsapp_id or not group.phone_id:
            continue
        phone = session.get(Phone, group.phone_id)
        if phone is None or not phone.evolution_instance:
            continue
        token = None
        if phone.instance_token_ciphertext:
            try:
                token = decrypt(phone.instance_token_ciphertext)
            except Exception:
                token = None
        ok = _evolution_send(
            instancia=phone.evolution_instance,
            token=token,
            destino=group.whatsapp_id,
            texto=payload.message,
            imagem_b64=payload.image_base64,
        )
        if ok:
            enviados += 1

    session.commit()
    total = len(grupos)
    return CouponDispatchResponse(
        ok=enviados > 0,
        enviados=enviados,
        total=total,
        erro=None if enviados else "Falha ao enviar — confira WhatsApp/Evolution e os grupos.",
    )


@router.get("/vip", response_model=list[VipResponse])
def list_vip(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    status: str | None = None,
) -> list[VipResponse]:
    stmt = select(VipRequest).where(VipRequest.owner_id == user.tenant_id)
    if status:
        stmt = stmt.where(VipRequest.status == status)
    rows = session.scalars(stmt.order_by(VipRequest.created_at.desc()).limit(200)).all()
    return [VipResponse.model_validate(r, from_attributes=True) for r in rows]


@router.post(
    "/vip",
    response_model=VipResponse,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_vip(
    payload: VipCreate,
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> VipResponse:
    row = VipRequest(id=uuid4(), owner_id=user.tenant_id, **payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return VipResponse.model_validate(row, from_attributes=True)


@router.patch(
    "/vip/{vip_id}",
    response_model=VipResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def patch_vip(
    vip_id: UUID,
    payload: VipUpdate,
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> VipResponse:
    row = session.scalar(
        select(VipRequest).where(VipRequest.id == vip_id, VipRequest.owner_id == user.tenant_id)
    )
    if row is None:
        raise APIError(404, "NOT_FOUND", "Pedido VIP não encontrado")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    row.updated_at = relogio.agora_banco()
    session.commit()
    session.refresh(row)
    return VipResponse.model_validate(row, from_attributes=True)


@router.post(
    "/vip/match",
    response_model=list[VipResponse],
    dependencies=[Depends(limit_authenticated_write)],
)
def match_vip(
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> list[VipResponse]:
    waiting = session.scalars(
        select(VipRequest).where(
            VipRequest.owner_id == user.tenant_id, VipRequest.status == "waiting"
        )
    ).all()
    recent = session.scalars(select(Oferta).order_by(Oferta.id.desc()).limit(400)).all()
    matched: list[VipRequest] = []
    for vip in waiting:
        needle = vip.wish_product.casefold()
        for offer in recent:
            nome = (offer.nome or "").casefold()
            if needle not in nome and not any(
                token and token in nome for token in needle.split() if len(token) > 3
            ):
                continue
            if offer.preco is None or Decimal(str(offer.preco)) > vip.max_price:
                continue
            vip.status = "matched"
            vip.matched_offer_id = offer.id
            vip.updated_at = relogio.agora_banco()
            matched.append(vip)
            break
    session.commit()
    return [VipResponse.model_validate(r, from_attributes=True) for r in matched]


@router.get("/monitors", response_model=list[MonitorResponse])
def list_monitors(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> list[MonitorResponse]:
    rows = session.scalars(
        select(PriceMonitor)
        .where(PriceMonitor.owner_id == user.tenant_id)
        .order_by(PriceMonitor.created_at.desc())
        .limit(200)
    ).all()
    return [MonitorResponse.model_validate(r, from_attributes=True) for r in rows]


@router.post(
    "/monitors",
    response_model=MonitorResponse,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_monitor(
    payload: MonitorCreate,
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> MonitorResponse:
    row = PriceMonitor(
        id=uuid4(),
        owner_id=user.tenant_id,
        url=payload.url.strip(),
        target_price=payload.target_price,
        title=payload.title,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return MonitorResponse.model_validate(row, from_attributes=True)


@router.patch(
    "/monitors/{monitor_id}",
    response_model=MonitorResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def patch_monitor(
    monitor_id: UUID,
    payload: MonitorUpdate,
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> MonitorResponse:
    row = session.scalar(
        select(PriceMonitor).where(
            PriceMonitor.id == monitor_id, PriceMonitor.owner_id == user.tenant_id
        )
    )
    if row is None:
        raise APIError(404, "NOT_FOUND", "Monitor não encontrado")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    row.updated_at = relogio.agora_banco()
    session.commit()
    session.refresh(row)
    return MonitorResponse.model_validate(row, from_attributes=True)


@router.post(
    "/monitors/{monitor_id}/check",
    response_model=MonitorResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def check_monitor(
    monitor_id: UUID,
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> MonitorResponse:
    """Checagem MVP: reutiliza o parser do job do worker."""
    row = session.scalar(
        select(PriceMonitor).where(
            PriceMonitor.id == monitor_id, PriceMonitor.owner_id == user.tenant_id
        )
    )
    if row is None:
        raise APIError(404, "NOT_FOUND", "Monitor não encontrado")
    from worker.price_monitors import checar_um

    checar_um(row)
    session.commit()
    session.refresh(row)
    return MonitorResponse.model_validate(row, from_attributes=True)


@router.delete(
    "/monitors/{monitor_id}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def delete_monitor(
    monitor_id: UUID,
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    row = session.scalar(
        select(PriceMonitor).where(
            PriceMonitor.id == monitor_id, PriceMonitor.owner_id == user.tenant_id
        )
    )
    if row is None:
        raise APIError(404, "NOT_FOUND", "Monitor não encontrado")
    session.delete(row)
    session.commit()


@router.get("/sources", response_model=list[FeedSourceResponse])
def list_sources(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> list[FeedSourceResponse]:
    ensure_feed_sources(session, user.tenant_id)
    session.commit()
    rows = session.scalars(
        select(FeedSource)
        .where(FeedSource.owner_id == user.tenant_id)
        .order_by(FeedSource.name)
    ).all()
    return [FeedSourceResponse.model_validate(r, from_attributes=True) for r in rows]


@router.post(
    "/sources",
    response_model=FeedSourceResponse,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_source(
    payload: FeedSourceCreate,
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> FeedSourceResponse:
    ensure_feed_sources(session, user.tenant_id)
    slug_base = "".join(ch if ch.isalnum() else "-" for ch in payload.name.casefold())
    slug = f"custom-{slug_base.strip('-')[:40] or uuid4().hex[:8]}"
    row = FeedSource(
        id=uuid4(),
        owner_id=user.tenant_id,
        slug=slug,
        name=payload.name.strip(),
        kind=payload.kind,
        url=payload.url.strip(),
        enabled=payload.enabled,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return FeedSourceResponse.model_validate(row, from_attributes=True)


@router.patch(
    "/sources/{source_id}",
    response_model=FeedSourceResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def patch_source(
    source_id: UUID,
    payload: FeedSourceUpdate,
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> FeedSourceResponse:
    row = session.scalar(
        select(FeedSource).where(
            FeedSource.id == source_id, FeedSource.owner_id == user.tenant_id
        )
    )
    if row is None:
        raise APIError(404, "NOT_FOUND", "Fonte não encontrada")
    if payload.enabled is not None:
        row.enabled = payload.enabled
    row.updated_at = relogio.agora_banco()
    session.commit()
    session.refresh(row)
    return FeedSourceResponse.model_validate(row, from_attributes=True)


@router.post(
    "/sources/sync",
    response_model=FeedSyncResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def sync_sources(
    user: Operator,
    session: Annotated[Session, Depends(get_db)],
) -> FeedSyncResponse:
    """Coleta agora as fontes ligadas e enfileira no mirror_inbox."""
    ensure_feed_sources(session, user.tenant_id)
    rows = session.scalars(
        select(FeedSource).where(
            FeedSource.owner_id == user.tenant_id, FeedSource.enabled.is_(True)
        )
    ).all()
    lidas = novas = 0
    detalhes: list[dict] = []
    for source in rows:
        result = coletar_fonte(session, source)
        lidas += int(result.get("lidas") or 0)
        novas += int(result.get("novas") or 0)
        detalhes.append({"slug": source.slug, **result})
    session.commit()
    return FeedSyncResponse(fontes=len(rows), lidas=lidas, novas=novas, detalhes=detalhes)
