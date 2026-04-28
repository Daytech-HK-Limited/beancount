"""Thread-safe in-memory beancount state — single ledger and multi-ledger registry."""

import logging
import threading
import time

from beancount import loader

logger = logging.getLogger(__name__)


class BeancountState:
    def __init__(self, ledger_id: str = "default"):
        self.ledger_id = ledger_id
        self._lock = threading.RLock()
        self._entries = []
        self._errors = []
        self._options_map = {}
        self._loaded_at = None
        self._filename = None

    def load(self, filename: str) -> None:
        t0 = time.time()
        logger.info("[%s] Loading %s ...", self.ledger_id, filename)
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
                "[%s] Loaded %s with %d error(s) in %.2fs",
                self.ledger_id, filename, len(errors), elapsed,
            )
        else:
            logger.info(
                "[%s] Loaded %s (%d entries) in %.2fs",
                self.ledger_id, filename, len(entries), elapsed,
            )

    def get(self):
        """Return (entries, errors, options_map). Immutable NamedTuples; safe across threads."""
        with self._lock:
            return self._entries, self._errors, self._options_map

    @property
    def filename(self) -> str | None:
        with self._lock:
            return self._filename

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


class BeancountRegistry:
    """Holds multiple named BeancountState instances — one per ledger file."""

    def __init__(self):
        self._lock = threading.Lock()
        self._states: dict[str, BeancountState] = {}

    def register(self, ledger_id: str, filename: str) -> BeancountState:
        """Create a state for ledger_id and immediately load filename."""
        s = BeancountState(ledger_id=ledger_id)
        s.load(filename)
        with self._lock:
            self._states[ledger_id] = s
        return s

    def get(self, ledger_id: str) -> BeancountState | None:
        with self._lock:
            return self._states.get(ledger_id)

    def all(self) -> dict[str, BeancountState]:
        with self._lock:
            return dict(self._states)

    def ledger_ids(self) -> list[str]:
        with self._lock:
            return list(self._states.keys())


registry = BeancountRegistry()
