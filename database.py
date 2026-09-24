"""Models SQLAlchemy e helpers de acesso ao banco (SQLite)."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

from config import settings
import relogio

Base = declarative_base()


class Oferta(Base):
    """Uma linha por produto (identificado pela URL). Atualizada a cada nova captura."""

    __tablename__ = "ofertas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String, nullable=False)
    preco = Column(Float, nullable=False)
    preco_anterior = Column(Float)
    desconto = Column(Float)
    loja = Column(String)
    categoria = Column(String)
    url = Column(String, unique=True, index=True)
    imagem = Column(String)
    sku = Column(String)
    capturado_em = Column(DateTime, default=relogio.agora_banco, onupdate=relogio.agora_banco)

    envios = relationship("Envio", back_populates="oferta")


class Envio(Base):
    """Registro de cada envio efetivo para o WhatsApp (permite mais de um por oferta)."""

    __tablename__ = "envios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    oferta_id = Column(Integer, ForeignKey("ofertas.id"))
    enviado_em = Column(DateTime, default=relogio.agora_banco)
    grupo = Column(String)
    mensagem = Column(Text)
    preco_enviado = Column(Float)
    status = Column(String)

    oferta = relationship("Oferta", back_populates="envios")


def _url_do_banco() -> str:
    """Normaliza a URL do Postgres para o driver psycopg 3 (o Railway entrega
    postgresql://, que o SQLAlchemy roteia para o psycopg2, que nao instalamos)."""
    url = settings.database_url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


_engine = create_engine(_url_do_banco(), echo=False, future=True)
_SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(_engine)


@contextmanager
def get_session() -> Session:
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def upsert_oferta(session: Session, dados: dict) -> Oferta:
    """Cria ou atualiza a oferta. Prefere SKU+loja (estável); fallback pela URL."""
    oferta = None
    sku = dados.get("sku")
    loja = dados.get("loja")
    if sku:
        # Pode haver duplicatas antigas no SQLite — pega a mais recente.
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
        # Só atualiza URL se não conflitar com outra linha (unique).
        if oferta.url != dados["url"]:
            conflito = session.query(Oferta).filter_by(url=dados["url"]).first()
            if conflito is None or conflito.id == oferta.id:
                oferta.url = dados["url"]
        oferta.imagem = dados.get("imagem")
        oferta.sku = dados.get("sku") or oferta.sku
        oferta.capturado_em = relogio.agora_banco()
    session.flush()
    return oferta


def ultimo_envio(session: Session, oferta_id: int, grupo: str | None = None) -> Envio | None:
    """Último envio com sucesso no WhatsApp (falha de rede não bloqueia retry)."""
    q = (
        session.query(Envio)
        .filter_by(oferta_id=oferta_id, status="sucesso")
    )
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


def registrar_envio(session: Session, oferta_id: int, grupo: str, mensagem: str, preco: float, status: str) -> Envio:
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


def grupo_ja_enviou(session: Session, grupo: str | None = None) -> bool:
    """True se este grupo já teve envio de verdade (não só baseline)."""
    q = session.query(Envio.id).filter(Envio.status == "sucesso")
    if grupo:
        q = q.filter(Envio.grupo == grupo)
    return q.first() is not None


def contar_envios_desde(session: Session, desde: datetime, grupo: str | None = None) -> int:
    q = session.query(func.count(Envio.id)).filter(
        Envio.enviado_em >= desde, Envio.status == "sucesso"
    )
    if grupo:
        q = q.filter(Envio.grupo == grupo)
    return q.scalar() or 0


def contar_envios_ultima_hora(session: Session, grupo: str | None = None) -> int:
    return contar_envios_desde(session, relogio.agora_banco() - timedelta(hours=1), grupo=grupo)


def contar_envios_hoje(session: Session, grupo: str | None = None) -> int:
    return contar_envios_desde(session, relogio.inicio_do_dia_banco(), grupo=grupo)


def _minutos_desde(quando: datetime | None) -> float | None:
    if quando is None:
        return None
    agora = relogio.agora_banco()
    if quando.tzinfo is not None:
        quando = quando.astimezone().replace(tzinfo=None)
    return (agora - quando).total_seconds() / 60.0


def minutos_desde_ultimo_envio(session: Session, grupo: str | None = None) -> float | None:
    """Minutos desde o último envio com sucesso. None se nunca enviou."""
    q = session.query(Envio.enviado_em).filter(Envio.status == "sucesso")
    if grupo:
        q = q.filter(Envio.grupo == grupo)
    ultimo = q.order_by(Envio.enviado_em.desc()).first()
    if not ultimo or not ultimo[0]:
        return None
    return _minutos_desde(ultimo[0])


def contar_cupons_hoje(session: Session, grupo: str | None = None) -> int:
    inicio_do_dia = relogio.inicio_do_dia_banco()
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


def minutos_desde_ultimo_sku(session: Session, sku: str, grupo: str | None = None) -> float | None:
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
    return _minutos_desde(ultimo[0])


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
    desde = relogio.agora_banco() - timedelta(days=dias)
    q = (
        session.query(Oferta.nome, Envio.preco_enviado)
        .join(Envio, Envio.oferta_id == Oferta.id)
        .filter(Envio.status == "sucesso", Envio.enviado_em >= desde)
    )
    if grupo:
        q = q.filter(Envio.grupo == grupo)
    rows = q.all()
    return [(n or "", float(p) if p is not None else 0.0) for n, p in rows]
