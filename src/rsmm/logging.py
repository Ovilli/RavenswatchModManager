"""Centralized logging utilities for rsmm.

Provides a friendly `setup_logging()` helper that enables Rich if
available, and a small `Progress` context manager that uses Rich's
progress bars when present, or falls back to a simple textual
counter otherwise.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Optional


def _get_env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.lower() not in ("0", "false", "no", "off", "")


def setup_logging(level: int | None = None) -> None:
    """Configure root logging.

    Respects these environment variables:
      - RSMM_LOG_LEVEL: DEBUG/INFO/WARNING/ERROR
      - RSMM_LOG_FILE: path to write logs (rotating)
      - RSMM_LOG_JSON: if true, write JSON-formatted logs to file
      - RSMM_LOG_MAX_BYTES: rotation size (bytes, default 5MB)
      - RSMM_LOG_BACKUP_COUNT: rotation backups (default 3)

    Uses RichHandler for console output when available unless JSON
    console output is requested.
    """
    # Determine level
    env_level = os.environ.get("RSMM_LOG_LEVEL")
    if level is None:
        if env_level:
            try:
                level = getattr(logging, env_level.upper())
            except Exception:
                level = logging.INFO
        else:
            level = logging.INFO

    # Base logger
    root = logging.getLogger()
    root.setLevel(level)
    # Clear existing handlers to avoid duplicate logs on repeated init
    for h in list(root.handlers):
        root.removeHandler(h)

    # Console handler
    json_console = _get_env_bool("RSMM_LOG_JSON", False)
    if not json_console:
        try:
            from rich.logging import RichHandler  # type: ignore

            ch = RichHandler()
            ch.setLevel(level)
            ch.setFormatter(logging.Formatter("%(message)s"))
        except Exception:
            ch = logging.StreamHandler(sys.stderr)
            ch.setLevel(level)
            ch.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    else:
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(level)
        ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(ch)

    # File handler (optional)
    log_file = os.environ.get("RSMM_LOG_FILE")
    if log_file:
        try:
            max_bytes = int(os.environ.get("RSMM_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
        except Exception:
            max_bytes = 5 * 1024 * 1024
        try:
            backup = int(os.environ.get("RSMM_LOG_BACKUP_COUNT", "3"))
        except Exception:
            backup = 3
        fh = logging.handlers.RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup)
        fh.setLevel(level)
        if _get_env_bool("RSMM_LOG_JSON", False):
            # Try to use python-json-logger if available
            try:
                from pythonjsonlogger import jsonlogger  # type: ignore

                fmt = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
                fh.setFormatter(fmt)
            except Exception:
                fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        else:
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(fh)

    # Install exception hook to log uncaught exceptions
    def _excepthook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        root.exception("Uncaught exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = _excepthook


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def shorten(text: str, max_len: int = 88) -> str:
    """Return a compact representation of `text` suitable for logs.

    If `text` is longer than `max_len`, keep the trailing path segment
    and prefix with an ellipsis.
    """
    if not text or len(text) <= max_len:
        return text
    return "..." + text[-(max_len - 3):]


class Progress:
    """Simple progress helper.

    Usage:
      with Progress(total=n, description="Decoding") as p:
          for item in p.track(iterable):
              ...
    """
    def __init__(self, total: int | None = None, description: str = "") -> None:
        self.total = total
        self.description = description
        self._use_rich = False
        self._rich_progress = None
        self._task_id = None

    def __enter__(self):
        try:
            from rich.console import Console  # type: ignore
            from rich.progress import Progress as _RichProgress  # type: ignore

            self._use_rich = True
            self._rich_progress = _RichProgress()
            self._rich_progress.start()
            self._task_id = self._rich_progress.add_task(self.description, total=self.total or 0)
            return self
        except Exception:
            # no rich: fall back
            print(f"{self.description}...", file=sys.stderr)
            return self

    def __exit__(self, exc_type, exc, tb):
        if self._use_rich and self._rich_progress:
            try:
                self._rich_progress.stop()
            except Exception:
                pass

    def advance(self, n: int = 1) -> None:
        """Advance the progress by `n` steps.

        Safe no-op when Rich isn't available.
        """
        if self._use_rich and self._rich_progress and self._task_id is not None:
            try:
                self._rich_progress.advance(self._task_id, n)
            except Exception:
                pass

    def track(self, it: Iterable) -> Iterator:
        if self._use_rich and self._rich_progress and self._task_id is not None:
            for item in it:
                yield item
                try:
                    self._rich_progress.advance(self._task_id)
                except Exception:
                    pass
            return

        # Fallback: simple counter
        total = self.total
        i = 0
        for item in it:
            i += 1
            if total:
                if i % max(1, total // 20) == 0 or i == total:
                    print(f"{self.description}: {i}/{total}", file=sys.stderr)
            else:
                if i % 100 == 0:
                    print(f"{self.description}: {i}", file=sys.stderr)
            yield item
