"""Bounded local diagnostics, independent of user analysis reports."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import time

from .resources import writable_app_root

MAX_LOG_BYTES = 2 * 1024 * 1024
LOG_BACKUPS = 2
RETENTION_DAYS = 30
_logger = None


def configure_logging(root=None, *, max_bytes=MAX_LOG_BYTES, backups=LOG_BACKUPS,
                      retention_days=RETENTION_DAYS):
    global _logger
    logger = logging.Logger('stereofine', level=logging.INFO)
    if _logger is not None:
        for handler in _logger.handlers:
            handler.close()
    try:
        folder = Path(root or writable_app_root()) / 'logs'
        folder.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - retention_days * 86400
        for name in ['stereofine.log', *(f'stereofine.log.{i}' for i in range(1, backups+1))]:
            path = folder / name
            if path.is_symlink():
                raise OSError('Diagnostic log is a symbolic link.')
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        handler = RotatingFileHandler(folder/'stereofine.log', maxBytes=max_bytes,
            backupCount=backups, encoding='utf-8', errors='backslashreplace')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
    _logger = logger
    return logger


def log_event(message):
    (_logger or configure_logging()).info(str(message)[:32768])


def log_failure(action, error, *, source=None, detail=''):
    (_logger or configure_logging()).error('%s | %s | %s\n%s', str(action)[:200],
        str(source or '')[:2048], str(error)[:8000], str(detail)[:32768])
