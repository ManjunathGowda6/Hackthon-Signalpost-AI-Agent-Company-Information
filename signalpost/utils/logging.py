"""Structured logging."""
import structlog
def setup_logging(level="INFO"):
    structlog.configure(
        processors=[structlog.contextvars.merge_contextvars, structlog.processors.add_log_level,
                     structlog.processors.TimeStamper(fmt="iso"), structlog.dev.ConsoleRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(structlog.get_level_from_name(level)),
        context_class=dict, logger_factory=structlog.PrintLoggerFactory(), cache_logger_on_first_use=True)
