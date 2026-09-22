"""Models SQLAlchemy do banco existente."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

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
    capturado_em = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    envios = relationship("Envio", back_populates="oferta")


class Envio(Base):
    """Registro de cada envio efetivo para o WhatsApp (permite mais de um por oferta)."""

    __tablename__ = "envios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    oferta_id = Column(Integer, ForeignKey("ofertas.id"))
    enviado_em = Column(DateTime, default=datetime.now)
    grupo = Column(String)
    mensagem = Column(Text)
    preco_enviado = Column(Float)
    status = Column(String)

    oferta = relationship("Oferta", back_populates="envios")
