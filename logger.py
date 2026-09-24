"""Configuração central de logs (loguru), console + arquivo rotativo."""
import sys
from pathlib import Path

from loguru import logger

from config import settings
from relogio import BR

LOG_DIR = Path(__file__).resolve().parent / "logs"
try:
    LOG_DIR.mkdir(exist_ok=True)
except OSError:
    LOG_DIR = Path("/tmp/ninaofertas-logs")
    LOG_DIR.mkdir(exist_ok=True)

def _hora_brasil(record: dict) -> None:
    record["time"] = record["time"].astimezone(BR)


logger.remove()
logger.configure(patcher=_hora_brasil)
logger.add(
    sys.stdout,
    format="<green>[{time:HH:mm:ss}]</green> {message}",
    level=settings.log_level,
    colorize=False,
)
try:
    logger.add(
        LOG_DIR / "bot.log",
        format="[{time:HH:mm:ss}] {message}",
        level=settings.log_level,
        rotation="5 MB",
        retention=5,
        encoding="utf-8",
    )
except OSError:
    pass

__all__ = ["logger"]
