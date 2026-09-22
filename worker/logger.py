"""Configuração central de logs (loguru), console + arquivo rotativo."""
import sys

from loguru import logger

from core.settings import BASE_DIR, settings

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger.remove()
logger.add(
    sys.stdout,
    format="<green>[{time:HH:mm:ss}]</green> {message}",
    level=settings.log_level,
    colorize=True,
)
logger.add(
    LOG_DIR / "bot.log",
    format="[{time:HH:mm:ss}] {message}",
    level=settings.log_level,
    rotation="5 MB",
    retention=5,
    encoding="utf-8",
)

__all__ = ["logger"]
