import logging
import logging.handlers
from contextvars import ContextVar
from pathlib import Path

from app.core.config import settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Injects the current request's id (or "-" outside a request) into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


_configured = False


def setup_logging() -> None:
    """Configure the app's loggers and handlers. Safe to call more than once."""
    global _configured
    if _configured:
        return
    _configured = True

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
    request_id_filter = RequestIdFilter()

    root = logging.getLogger()
    root.setLevel(settings.log_level)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(request_id_filter)
    root.addHandler(console_handler)

    app_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log", maxBytes=10_000_000, backupCount=5, encoding="utf-8"
    )
    app_handler.setFormatter(formatter)
    app_handler.addFilter(request_id_filter)
    root.addHandler(app_handler)

    if settings.log_sql_queries:
        sql_handler = logging.handlers.RotatingFileHandler(
            log_dir / "sql.log", maxBytes=10_000_000, backupCount=5, encoding="utf-8"
        )
        sql_handler.setFormatter(formatter)
        sql_handler.addFilter(request_id_filter)
        sql_logger = logging.getLogger("app.db.queries")
        sql_logger.addHandler(sql_handler)
        sql_logger.propagate = False

    if settings.log_llm_interactions:
        llm_handler = logging.handlers.RotatingFileHandler(
            log_dir / "llm.jsonl", maxBytes=10_000_000, backupCount=5, encoding="utf-8"
        )
        llm_handler.setFormatter(logging.Formatter("%(message)s"))
        llm_logger = logging.getLogger("app.llm")
        llm_logger.addHandler(llm_handler)
        llm_logger.propagate = False

    # Quiet third-party loggers that are only noisy because the root logger is now at INFO:
    # watchfiles reports every change to backend/logs/ (written by our own handlers above), and
    # httpx logs each Ollama request, which app.llm already records in detail.
    for name in ("watchfiles.main", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
