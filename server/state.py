"""Thread-safe in-memory beancount state."""

import logging
import threading
import time

from beancount import loader

logger = logging.getLogger(__name__)


class BeancountState:
    def __init__(self):
        self._lock = threading.RLock()
        self._entries = []
        self._errors = []
        self._options_map = {}
        self._loaded_at = None
        self._filename = None

    def load(self, filename: str) -> None:
        t0 = time.time()
        logger.info("Loading %s ...", filename)
        entries, errors, options_map = loader.load_file(filename)
        elapsed = time.time() - t0
        with self._lock:
            self._entries = entries
            self._errors = errors
            self._options_map = options_map
            self._loaded_at = time.time()
            self._filename = filename
        if errors:
            logger.warning(
                "Loaded %s with %d error(s) in %.2fs", filename, len(errors), elapsed
            )
        else:
            logger.info(
                "Loaded %s (%d entries) in %.2fs", filename, len(entries), elapsed
            )

    def get(self):
        """Return (entries, errors, options_map). All are immutable; safe to read without copying."""
        with self._lock:
            return self._entries, self._errors, self._options_map

    @property
    def is_loaded(self) -> bool:
        with self._lock:
            return self._loaded_at is not None

    @property
    def loaded_at(self):
        with self._lock:
            return self._loaded_at

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def error_count(self) -> int:
        with self._lock:
            return len(self._errors)


state = BeancountState()
