"""Shared process lock for all adapters using the single SYNTX browser."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path


@contextmanager
def browser_lease(state=None):
    root = Path(state or os.environ.get('APP_STATE', '/state'))
    with (root / 'browser.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
