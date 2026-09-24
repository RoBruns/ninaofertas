"""Recado periódico: segue a vó no Instagram (foto + link)."""
from __future__ import annotations

import time

import database
import relogio
import whatsapp
from config import BASE_DIR, canais_ativos, grupo_whatsapp, nome_canal, usar_canal
from logger import logger

SKU = "promo:instagram"
URL = "https://www.instagram.com/ninamegaofertas"
FOTO = BASE_DIR / "assets" / "vo.jpg"
INTERVALO_HORAS = 4

MENSAGEM = (
    "Já segue a vó no Instagram? 👵\n\n"
    "Lá você fica sempre em contato e pode pedir ofertas que eu acho pra você direto.\n\n"
    f"👉 {URL}"
)


def ciclo() -> None:
    if not relogio.pode_enviar():
        logger.info("[Instagram] Fora do horário (08h–00h, Brasília). Recado adiado.")
        return
    if not FOTO.is_file():
        logger.warning("[Instagram] foto da vó não encontrada em assets/vo.jpg")
        return

    for i, canal in enumerate(canais_ativos()):
        if i:
            time.sleep(12)
        with usar_canal(canal):
            _enviar_canal()


def _enviar_canal() -> None:
    grupo = grupo_whatsapp()
    if not grupo:
        return

    with database.get_session() as session:
        decorridos = database.minutos_desde_ultimo_sku(session, SKU, grupo=grupo)
        if decorridos is not None and decorridos < INTERVALO_HORAS * 60:
            falta = INTERVALO_HORAS * 60 - decorridos
            logger.debug(
                f"[{nome_canal()}] recado Instagram: ainda faltam ~{falta:.0f} min"
            )
            return

        desde_qualquer = database.minutos_desde_ultimo_envio(session)
        if desde_qualquer is not None and desde_qualquer < 3:
            logger.info(f"[{nome_canal()}] recado Instagram adiado: acabou de sair oferta")
            return

        oferta = database.upsert_oferta(
            session,
            {
                "nome": "Segue a vó no Instagram",
                "preco": 0.0,
                "loja": "Instagram",
                "categoria": "promo",
                "url": URL,
                "sku": SKU,
                "imagem": str(FOTO),
            },
        )

        logger.info(f"[{nome_canal()}] Enviando recado do Instagram...")
        ok = whatsapp.enviar_mensagem(MENSAGEM, imagem=str(FOTO), grupo=grupo)
        database.registrar_envio(
            session,
            oferta_id=oferta.id,
            grupo=grupo,
            mensagem=MENSAGEM,
            preco=0.0,
            status="sucesso" if ok else "falha",
        )
        if ok:
            logger.info(f"[{nome_canal()}] Recado do Instagram enviado.")
        else:
            logger.error(f"[{nome_canal()}] Falha ao enviar recado do Instagram.")
