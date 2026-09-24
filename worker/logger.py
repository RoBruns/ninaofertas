"""Configuração central de logs (loguru), console + arquivo rotativo."""
import sys
from pathlib import Path

from loguru import logger

from core.settings import BASE_DIR, settings

# BASE_DIR é a raiz do projeto — mesma pasta de logs que a produção usava.
LOG_DIR = BASE_DIR / "logs"
try:
    LOG_DIR.mkdir(exist_ok=True)
except OSError:
    LOG_DIR = Path("/tmp/ninaofertas-logs")
    LOG_DIR.mkdir(exist_ok=True)

logger.remove()
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
