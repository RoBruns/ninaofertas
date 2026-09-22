"""Queries sobre ofertas e envios."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.models import Envio, Oferta


def upsert_oferta(session: Session, dados: dict) -> Oferta:
    """Cria ou atualiza a oferta. Prefere SKU+loja (estável); fallback pela URL."""
    oferta = None
    sku = dados.get("sku")
    loja = dados.get("loja")
    if sku:
        oferta = (
            session.query(Oferta)
            .filter_by(sku=sku, loja=loja)
            .order_by(Oferta.id.desc())
            .first()
        )
    if oferta is None:
        oferta = session.query(Oferta).filter_by(url=dados["url"]).one_or_none()

    if oferta is None:
        oferta = Oferta(**dados)
        session.add(oferta)
    else:
        if oferta.preco != dados["preco"]:
            oferta.preco_anterior = oferta.preco
        oferta.nome = dados["nome"]
        oferta.preco = dados["preco"]
        oferta.desconto = dados.get("desconto")
        oferta.loja = dados.get("loja")
        oferta.categoria = dados.get("categoria")
        if oferta.url != dados["url"]:
            conflito = session.query(Oferta).filter_by(url=dados["url"]).first()
            if conflito is None or conflito.id == oferta.id:
                oferta.url = dados["url"]
        oferta.imagem = dados.get("imagem")
        oferta.sku = dados.get("sku") or oferta.sku
        oferta.capturado_em = datetime.now()
    session.flush()
    return oferta


def ultimo_envio(session: Session, oferta_id: int, grupo: str | None = None) -> Envio | None:
    """Último envio com sucesso no WhatsApp (falha de rede não bloqueia retry)."""
    q = session.query(Envio).filter_by(oferta_id=oferta_id, status="sucesso")
    if grupo:
        q = q.filter_by(grupo=grupo)
    return q.order_by(Envio.enviado_em.desc()).first()


def ja_conhecida(session: Session, oferta_id: int, grupo: str | None = None) -> bool:
    """True se a oferta já foi vista no baseline ou enviada com sucesso neste grupo."""
    q = session.query(Envio.id).filter(
        Envio.oferta_id == oferta_id,
        Envio.status.in_(("sucesso", "visto")),
    )
    if grupo:
        q = q.filter(Envio.grupo == grupo)
    return q.first() is not None


def registrar_visto(session: Session, oferta_id: int, preco: float, grupo: str = "") -> Envio:
    """Marca a oferta como já existente na partida do bot (sem WhatsApp)."""
    return registrar_envio(
        session,
        oferta_id=oferta_id,
        grupo=grupo,
        mensagem="",
        preco=preco,
        status="visto",
    )


def registrar_envio(
    session: Session,
    oferta_id: int,
    grupo: str,
    mensagem: str,
    preco: float,
    status: str,
) -> Envio:
    envio = Envio(
        oferta_id=oferta_id,
        grupo=grupo,
        mensagem=mensagem,
        preco_enviado=preco,
        status=status,
    )
    session.add(envio)
    session.flush()
    return envio


def contar_envios_desde(session: Session, desde: datetime, grupo: str | None = None) -> int:
    q = session.query(func.count(Envio.id)).filter(
        Envio.enviado_em >= desde, Envio.status == "sucesso"
    )
    if grupo:
        q = q.filter(Envio.grupo == grupo)
    return q.scalar() or 0


def contar_envios_ultima_hora(session: Session, grupo: str | None = None) -> int:
    return contar_envios_desde(session, datetime.now() - timedelta(hours=1), grupo=grupo)


def contar_envios_hoje(session: Session, grupo: str | None = None) -> int:
    inicio_do_dia = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return contar_envios_desde(session, inicio_do_dia, grupo=grupo)


def minutos_desde_ultimo_envio(session: Session, grupo: str | None = None) -> float | None:
    """Minutos desde o último envio com sucesso. None se nunca enviou."""
    q = session.query(Envio.enviado_em).filter(Envio.status == "sucesso")
    if grupo:
        q = q.filter(Envio.grupo == grupo)
    ultimo = q.order_by(Envio.enviado_em.desc()).first()
    if not ultimo or not ultimo[0]:
        return None
    return (datetime.now() - ultimo[0]).total_seconds() / 60.0


def contar_cupons_hoje(session: Session, grupo: str | None = None) -> int:
    inicio_do_dia = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    q = (
        session.query(func.count(Envio.id))
        .join(Oferta, Oferta.id == Envio.oferta_id)
        .filter(
            Envio.enviado_em >= inicio_do_dia,
            Envio.status == "sucesso",
            Oferta.categoria == "cupom",
        )
    )
    if grupo:
        q = q.filter(Envio.grupo == grupo)
    return q.scalar() or 0


def minutos_desde_ultimo_sku(
    session: Session, sku: str, grupo: str | None = None
) -> float | None:
    q = (
        session.query(Envio.enviado_em)
        .join(Oferta, Oferta.id == Envio.oferta_id)
        .filter(Envio.status == "sucesso", Oferta.sku == sku)
    )
    if grupo:
        q = q.filter(Envio.grupo == grupo)
    ultimo = q.order_by(Envio.enviado_em.desc()).first()
    if not ultimo or not ultimo[0]:
        return None
    return (datetime.now() - ultimo[0]).total_seconds() / 60.0


def sku_ja_enviado(
    session: Session,
    sku: str,
    loja: str | None = None,
    exceto_oferta_id: int | None = None,
    grupo: str | None = None,
) -> bool:
    """True se algum envio com sucesso já usou este SKU (mesmo produto, outra URL)."""
    q = (
        session.query(Envio.id)
        .join(Oferta, Oferta.id == Envio.oferta_id)
        .filter(Envio.status == "sucesso", Oferta.sku == sku)
    )
    if loja:
        q = q.filter(Oferta.loja == loja)
    if grupo:
        q = q.filter(Envio.grupo == grupo)
    if exceto_oferta_id is not None:
        q = q.filter(Oferta.id != exceto_oferta_id)
    return q.first() is not None


def nomes_precos_enviados_recentes(
    session: Session, dias: int = 30, grupo: str | None = None
) -> list[tuple[str, float]]:
    """Nome + preço das ofertas já enviadas com sucesso no período."""
    desde = datetime.now() - timedelta(days=dias)
    q = (
        session.query(Oferta.nome, Envio.preco_enviado)
        .join(Envio, Envio.oferta_id == Oferta.id)
        .filter(Envio.status == "sucesso", Envio.enviado_em >= desde)
    )
    if grupo:
        q = q.filter(Envio.grupo == grupo)
    rows = q.all()
    return [(n or "", float(p) if p is not None else 0.0) for n, p in rows]
