"""Entrypoint: inicializa o banco e o agendador do monitoramento periódico.

Tudo que o worker publica vem dos bots ativos no dashboard (ADR-020): sem bot
ativo com telefone e grupo, ele fica ocioso e só avisa no log.
"""

from __future__ import annotations

import time
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from core import db, relogio
from core.alerts import cleanup_events, detect_alerts
from core.config_provider import bots_ativos, usar_bot_runtime
from core.sales_sync import sync_all_active_accounts
from core.settings import settings
from worker import commands, mirror, monitor, promo_instagram, telemetry
from worker.channels import canais_ativos
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
    """Um ciclo por bot: uma varredura alimenta todos os seus grupos."""
    from core.discovery import scraper_discovery_enabled

    if not scraper_discovery_enabled():
        # ADR-037: sem scraper — o espelho (mirror.ciclo) é a única fonte.
        return
    global _avisou_sem_bots
    runtimes = bots_ativos()
    if not runtimes:
        if not _avisou_sem_bots:
            logger.warning(
                "Nenhum bot ativo no dashboard: nada a publicar. "
                "Ative um bot com telefone, grupo e conta de plataforma."
            )
            _avisou_sem_bots = True
        return
    _avisou_sem_bots = False
    for runtime in runtimes:
        try:
            with usar_bot_runtime(runtime):
                monitor.ciclo()
        except ValueError as exc:
            # O bot foi pausado entre a listagem e o ciclo (cache de 30 s).
            logger.info(f"Bot ignorado: {exc}")


def _comandos_imediatos() -> None:
    commands.drenar_comandos()
    from core.discovery import scraper_discovery_enabled

    if not scraper_discovery_enabled():
        return
    bot_ids = commands.consumir_run_now()
    if not bot_ids:
        return
    for runtime in bots_ativos():
        if any(str(wanted) == str(runtime.id) for wanted in bot_ids):
            with usar_bot_runtime(runtime):
                monitor.ciclo()


def _enviar_heartbeat() -> None:
    """Sinaliza o worker mesmo quando ainda nao ha bot pronto para executar."""
    try:
        telemetry.heartbeat([runtime.id for runtime in bots_ativos()])
    except Exception as exc:
        logger.exception(f"Job de heartbeat falhou: {exc}")


def _registrar_jobs(scheduler: BackgroundScheduler) -> None:
    """Registra jobs para permitir validar a agenda sem iniciar o processo."""
    agora = relogio.agora_br()
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
        _enviar_heartbeat,
        "interval",
        seconds=60,
        next_run_time=agora,
        id="heartbeat",
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
    scheduler.add_job(
        mirror.ciclo,
        "interval",
        seconds=15,
        next_run_time=agora + timedelta(seconds=20),
        id="mirror-inbox",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        mirror.garantir_webhooks,
        "interval",
        minutes=30,
        next_run_time=agora + timedelta(minutes=1),
        id="mirror-webhook",
        max_instances=1,
        coalesce=True,
    )


def main() -> None:
    db.init_db()
    ativos = canais_ativos()
    from core.discovery import scraper_discovery_enabled

    logger.info("Bot de Ofertas iniciado. Bots, grupos e contas vêm do dashboard.")
    logger.info(f"Horário de Brasília: {relogio.agora_br().strftime('%H:%M')}.")
    if ativos:
        logger.info(f"{len(ativos)} canal(is) ativo(s) (bot x grupo).")
    if scraper_discovery_enabled():
        logger.info(
            f"Descoberta por scraper/API ligada. Intervalo: {settings.check_interval}s."
        )
    else:
        logger.info(
            "Modo só espelho (ADR-037): sem scraper/API de produtos. "
            "Fontes = grupos que a Nina 1 escuta."
        )
    from worker import whatsapp

    whatsapp.avisar_permissao_grupos()

    scheduler = BackgroundScheduler(timezone=relogio.BR)
    _registrar_jobs(scheduler)
    logger.info("Recado do Instagram (foto da vó) a cada 4h nos grupos dos bots ativos.")
    logger.info("Espelho WhatsApp: drenando mirror_inbox a cada 15s.")
    scheduler.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Encerrando bot...")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
