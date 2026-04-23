import logging
import sys

from app.config import settings


def setup_logger(name: str = "bot") -> logging.Logger:
    """Logger simples com formato estruturado pra debug do fluxo."""
    logger = logging.getLogger(name)
    logger.setLevel(settings.log_level)

    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


logger = setup_logger()
