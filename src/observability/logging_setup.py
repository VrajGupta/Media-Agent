from __future__ import annotations

from pathlib import Path

from loguru import logger


def setup_logging(logs_dir: str | Path) -> None:
    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        logs_dir / "agent.log",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name}:{function}:{line} | {message}",
    )
    logger.add(
        lambda m: print(m, end=""),
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}",
        colorize=True,
    )
