"""Thread-safe in-memory beancount state — single ledger and multi-ledger registry."""

import logging
import threading
import time

from beancount import loader
from beancount.core import realization

logger = logging.getLogger(__name__)

_RELOAD_TIMEOUT = 120.0  # seconds a request will wait for a reload to finish


class BeancountState:
    def __init__(self, ledger_id: str = "default"):
        self.ledger_id = ledger_id
        self._lock = threading.RLock()

        # _ready is CLEAR while a load is in progress.
        # Any call to get() / get_real_root() blocks until it is SET.
        # Starts clear so the very first request waits for the initial load.
        self._ready = threading.Event()

        # Serializes concurrent load() calls (e.g. file watcher racing with /reload).
        self._reload_lock = threading.Lock()

        self._entries = []
        self._errors = []
        self._options_map = {}
        self._real_root = None
        self._loaded_at = None
        self._filename = None

    # ------------------------------------------------------------------
    # Write path (called from the watcher thread or explicit /reload)
    # ------------------------------------------------------------------

    def load(self, filename: str) -> None:
        with self._reload_lock:
            self._do_load(filename)

    def _do_load(self, filename: str) -> None:
        t0 = time.time()
        logger.info("[%s] Loading %s ...", self.ledger_id, filename)

        # Block new requests from receiving stale data while we reload.
        self._ready.clear()

        try:
            entries, errors, options_map = loader.load_file(filename)
            elapsed_load = time.time() - t0

            # Pre-compute the realization tree so the first balance/report
            # request after a reload does not pay this cost.
            t1 = time.time()
            real_root = realization.realize(entries)
            elapsed_realize = time.time() - t1

            with self._lock:
                self._entries = entries
                self._errors = errors
                self._options_map = options_map
                self._real_root = real_root
                self._loaded_at = time.time()
                self._filename = filename

            if errors:
                logger.warning(
                    "[%s] Loaded %s with %d error(s) in %.2fs (realize %.2fs)",
                    self.ledger_id, filename, len(errors), elapsed_load, elapsed_realize,
                )
            else:
                logger.info(
                    "[%s] Loaded %s (%d entries) in %.2fs (realize %.2fs)",
                    self.ledger_id, filename, len(entries), elapsed_load, elapsed_realize,
                )
        finally:
            # Always unblock waiting requests, even if load failed.
            self._ready.set()

    # ------------------------------------------------------------------
    # Read path (called from request handlers — blocks during reload)
    # ------------------------------------------------------------------

    def get(self):
        """Block until the ledger is ready, then return (entries, errors, options_map).

        Raises RuntimeError if the reload does not complete within the timeout.
        """
        if not self._ready.wait(timeout=_RELOAD_TIMEOUT):
            raise RuntimeError(
                f"[{self.ledger_id}] Timed out waiting for ledger reload "
                f"after {_RELOAD_TIMEOUT}s"
            )
        with self._lock:
            return self._entries, self._errors, self._options_map

    def get_real_root(self):
        """Block until the ledger is ready, then return the pre-computed realization tree."""
        if not self._ready.wait(timeout=_RELOAD_TIMEOUT):
            raise RuntimeError(
                f"[{self.ledger_id}] Timed out waiting for ledger reload "
                f"after {_RELOAD_TIMEOUT}s"
            )
        with self._lock:
            return self._real_root

    # ------------------------------------------------------------------
    # Status properties (non-blocking, safe to poll from /health)
    # ------------------------------------------------------------------

    @property
    def filename(self) -> str | None:
        with self._lock:
            return self._filename

    @property
    def is_loaded(self) -> bool:
        return self._ready.is_set()

    @property
    def is_reloading(self) -> bool:
        return not self._ready.is_set()

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
