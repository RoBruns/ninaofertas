"""Entrypoint: inicializa o banco e o agendador do monitoramento periódico."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from core import db
from core.settings import settings
from worker import monitor, promo_instagram
from worker.channels import canais_ativos, usar_canal
from worker.logger import logger


def _ciclo_achadinhos() -> None:
    with usar_canal("achadinhos"):
        monitor.ciclo()


def _ciclo_auto() -> None:
    with usar_canal("auto"):
        monitor.ciclo()


def main() -> None:
    db.init_db()
    ativos = canais_ativos()
    logger.info("Bot de Ofertas iniciado.")
    if "auto" in ativos:
        logger.info("Canais: Achadinhos da Nina (casa/feminino) + Nina Ofertas (automotivo)")
    else:
        logger.info("Canal ativo: Achadinhos da Nina (casa/feminino). Nina Ofertas (auto) está desligado.")
    logger.info(f"Verificando novas ofertas a cada {settings.check_interval}s.")
    from worker import whatsapp

    whatsapp.avisar_permissao_grupos()

    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    agora = datetime.now()
    if "achadinhos" in ativos:
        scheduler.add_job(
            _ciclo_achadinhos,
            "interval",
            seconds=settings.check_interval,
            next_run_time=agora,
            id="achadinhos",
            max_instances=1,
            coalesce=True,
        )
    if "auto" in ativos:
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
        promo_instagram.ciclo,
        "interval",
        hours=1,
        next_run_time=agora + timedelta(minutes=2),
        id="instagram",
        max_instances=1,
        coalesce=True,
    )
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
