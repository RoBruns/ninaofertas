"""Entrypoint: inicializa o banco e o agendador do monitoramento periódico.

Tudo que o worker publica vem dos bots ativos no dashboard (ADR-020): sem bot
ativo com telefone e grupo, ele fica ocioso e só avisa no log.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from core import db
from core.alerts import cleanup_events, detect_alerts
from core.sales_sync import sync_all_active_accounts
from core.settings import settings
from worker import commands, monitor, promo_instagram
from worker.channels import canais_ativos, usar_canal
from worker.logger import logger

_avisou_sem_bots = False


def _detectar_alertas() -> None:
    """Falhas de observabilidade nunca chegam ao ciclo de ofertas."""
    try:
        detect_alerts()
    except Exception as exc:
        logger.exception(f"Job de alertas falhou: {exc}")


def _limpar_eventos() -> None:
    try:
        removidos = cleanup_events()
        logger.info(f"Retencao de eventos removeu {removidos} registros antigos.")
    except Exception as exc:
        logger.exception(f"Job de retencao de eventos falhou: {exc}")


def _ciclos_banco() -> None:
    """Um ciclo por (bot ativo, grupo), mantendo monitor.ciclo() com o contrato historico."""
    global _avisou_sem_bots
    canais = canais_ativos()
    if not canais:
        if not _avisou_sem_bots:
            logger.warning(
                "Nenhum bot ativo no dashboard: nada a publicar. "
                "Ative um bot com telefone, grupo e conta de plataforma."
            )
            _avisou_sem_bots = True
        return
    _avisou_sem_bots = False
    for canal in canais:
        try:
            with usar_canal(canal):
                monitor.ciclo()
        except ValueError as exc:
            # O bot foi pausado entre a listagem e o ciclo (cache de 30 s).
            logger.info(f"Canal ignorado: {exc}")


def _comandos_imediatos() -> None:
    commands.drenar_comandos()
    bot_ids = commands.consumir_run_now()
    if not bot_ids:
        return
    for canal in canais_ativos():
        bot_id = canal.split(":", 2)[1]
        if any(str(wanted) == bot_id for wanted in bot_ids):
            with usar_canal(canal):
                monitor.ciclo()


def _registrar_jobs(scheduler: BackgroundScheduler, agora: datetime) -> None:
    """Registra jobs para permitir validar a agenda sem iniciar o processo."""
    scheduler.add_job(
        _ciclos_banco,
        "interval",
        seconds=settings.check_interval,
        next_run_time=agora,
        id="bots-db",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _comandos_imediatos,
        "interval",
        seconds=5,
        next_run_time=agora,
        id="commands",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        sync_all_active_accounts,
        "cron",
        hour=6,
        minute=0,
        id="sales-sync-daily",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _detectar_alertas,
        "interval",
        minutes=5,
        next_run_time=agora,
        id="alerts-detect",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _limpar_eventos,
        "cron",
        hour=3,
        minute=30,
        id="events-retention",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        promo_instagram.ciclo,
        "interval",
        hours=1,
        next_run_time=agora + timedelta(minutes=2),
        id="instagram",
        max_instances=1,
        coalesce=True,
    )


def main() -> None:
    db.init_db()
    ativos = canais_ativos()
    logger.info("Bot de Ofertas iniciado. Bots, grupos e contas vêm do dashboard.")
    if ativos:
        logger.info(f"{len(ativos)} canal(is) ativo(s) (bot x grupo).")
    logger.info(f"Verificando novas ofertas a cada {settings.check_interval}s.")
    from worker import whatsapp

    whatsapp.avisar_permissao_grupos()

    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    _registrar_jobs(scheduler, datetime.now())
    logger.info("Recado do Instagram (foto da vó) a cada 4h nos grupos dos bots ativos.")
    scheduler.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Encerrando bot...")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
