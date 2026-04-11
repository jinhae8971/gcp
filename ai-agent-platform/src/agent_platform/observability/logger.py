"""Structured logging configuration using structlog."""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Configure structured logging for the platform.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_output: If True, output JSON lines (for production/log aggregation)
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    if json_output:
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=log_level,
    )
