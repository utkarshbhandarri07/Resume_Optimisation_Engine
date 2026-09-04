"""Safe, date-partitioned application logging for the production service."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class DailyDateFileHandler(logging.Handler):
    """Append records to one IST-dated file without logging sensitive payloads."""

    def __init__(self, log_dir: str) -> None:
        super().__init__()
        self.log_dir = Path(log_dir)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            day = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
            path = self.log_dir / f"resume-optimizer-{day}.log"
            with path.open("a", encoding="utf-8") as stream:
                stream.write(f"{self.format(record)}\n")
            path.chmod(0o640)
        except Exception:
            self.handleError(record)


def configure_application_logging(log_dir: str, level: str = "INFO") -> logging.Logger:
    """Configure the named application logger once per worker process."""
    logger = logging.getLogger("resume_optimizer")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    if any(isinstance(handler, DailyDateFileHandler) for handler in logger.handlers):
        return logger
    handler = DailyDateFileHandler(log_dir)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s pid=%(process)d %(name)s %(message)s"
    ))
    logger.addHandler(handler)
    return logger
