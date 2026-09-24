"""Entrypoint: inicializa o banco e o agendador do monitoramento periódico."""

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

_database_mode = False


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


def _ciclo_achadinhos() -> None:
    global _database_mode
    ativos = canais_ativos()
    if any(canal.startswith("db:") for canal in ativos):
        _database_mode = True
        _ciclos_banco()
        return
    _database_mode = False
    if "achadinhos" not in ativos:
        return
    with usar_canal("achadinhos"):
        monitor.ciclo()


def _ciclo_auto() -> None:
    if _database_mode or any(canal.startswith("db:") for canal in canais_ativos()):
        return
    with usar_canal("auto"):
        monitor.ciclo()


def _ciclos_banco() -> None:
    """Um ciclo por grupo, mantendo monitor.ciclo() com o contrato historico."""
    global _database_mode
    ativos = canais_ativos()
    canais_banco = tuple(canal for canal in ativos if canal.startswith("db:"))
    if not canais_banco:
        _database_mode = False
        for canal in ativos:
            with usar_canal(canal):
                monitor.ciclo()
        return
    for canal in canais_banco:
        with usar_canal(canal):
            monitor.ciclo()


def _comandos_imediatos() -> None:
    commands.drenar_comandos()
    bot_ids = commands.consumir_run_now()
    if not bot_ids:
        return
    for canal in canais_ativos():
        if not canal.startswith("db:"):
            continue
        bot_id = canal.split(":", 2)[1]
        if any(str(wanted) == bot_id for wanted in bot_ids):
            with usar_canal(canal):
                monitor.ciclo()


def _registrar_jobs(
    scheduler: BackgroundScheduler,
    ativos: tuple[str, ...],
    agora: datetime,
) -> None:
    """Registra jobs para permitir validar a agenda sem iniciar o processo."""
    global _database_mode
    banco_ativo = any(canal.startswith("db:") for canal in ativos)
    _database_mode = banco_ativo
    if banco_ativo:
        scheduler.add_job(
            _ciclos_banco,
            "interval",
            seconds=settings.check_interval,
            next_run_time=agora,
            id="bots-db",
            max_instances=1,
            coalesce=True,
        )
    if not banco_ativo and "achadinhos" in ativos:
        scheduler.add_job(
            _ciclo_achadinhos,
            "interval",
            seconds=settings.check_interval,
            next_run_time=agora,
            id="achadinhos",
            max_instances=1,
            coalesce=True,
        )
    if not banco_ativo and "auto" in ativos:
        scheduler.add_job(
            _ciclo_auto,
            "interval",
            seconds=settings.check_interval,
            next_run_time=agora + timedelta(seconds=max(20, settings.check_interval // 2)),
            id="auto",
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
    global _database_mode
    db.init_db()
    ativos = canais_ativos()
    logger.info("Bot de Ofertas iniciado.")
    # Só no modo legado: bots do banco tiram grupo e instância do cadastro, não da env.
    modo_legado = not any(canal.startswith("db:") for canal in ativos)
    if modo_legado and (not settings.evolution_instance or not settings.whatsapp_group_id):
        logger.error(
            "WhatsApp incompleto: defina EVOLUTION_INSTANCE e WHATSAPP_GROUP_ID "
            "nas Variables da Railway. Sem isso o Achadinhos não blipa."
        )
    if "auto" in ativos:
        logger.info("Canais: Achadinhos da Nina (casa/feminino) + Nina Ofertas (automotivo)")
    else:
        logger.info(
            "Canal ativo: Achadinhos da Nina (casa/feminino). Nina Ofertas (auto) está desligado."
        )
    logger.info(f"Verificando novas ofertas a cada {settings.check_interval}s.")
    from worker import whatsapp

    whatsapp.avisar_permissao_grupos()

    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    agora = datetime.now()
    _registrar_jobs(scheduler, ativos, agora)
    logger.info("Recado do Instagram (foto da vó) a cada 4h no grupo ativo.")
    scheduler.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Encerrando bot...")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
