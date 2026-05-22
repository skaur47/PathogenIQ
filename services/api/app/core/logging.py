import logging
import sys
import structlog
from app.config import get_settings


def configure_logging() -> None:
    """
    Set up structured logging with structlog.

    Why structured logging?
      - Plain text logs: "2024-01-15 ERROR Failed to fetch PubMed article"
      - Structured logs: {"event": "pubmed_fetch_failed", "pmid": "12345", "retry": 2}

    Structured logs are machine-readable. Tools like Grafana Loki, Datadog, and
    AWS CloudWatch can filter and aggregate by field — e.g., show all events
    where retry > 3, grouped by pathogen_id. This is essential in production.

    In development: logs render as colored, human-readable key=value lines.
    In production: logs render as JSON (one log entry per line), ready for
    ingestion into a log aggregation system.
    """
    settings = get_settings()

    shared_processors = [
        structlog.contextvars.merge_contextvars,       # add request-scoped context (e.g. request_id)
        structlog.stdlib.add_logger_name,              # adds logger name to every event
        structlog.stdlib.add_log_level,                # adds "level": "info" etc.
        structlog.processors.TimeStamper(fmt="iso"),   # ISO-8601 timestamps
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.is_production:
        # JSON output — one compact line per log event
        renderer = structlog.processors.JSONRenderer()
    else:
        # Colored, human-friendly output for local development
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.DEBUG if settings.debug else logging.INFO)

    # Silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.db_echo else logging.WARNING
    )
