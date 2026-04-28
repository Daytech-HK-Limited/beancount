"""File change watcher — polls all registered ledger files and triggers hot reload."""

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)


class FileWatcher:
    POLL_INTERVAL = 2.0

    def __init__(self, registry, debounce_seconds: float = 3.0):
        self._registry = registry
        self._debounce = debounce_seconds
        self._last_reload: dict[str, float] = {}  # ledger_id → timestamp
        self._stop_event = threading.Event()
        self._thread = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="beancount-watcher"
        )
        self._thread.start()
        ids = self._registry.ledger_ids()
        logger.info("File watcher started for ledgers: %s", ids)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _snapshot(self, state) -> dict:
        """Return {filename: (mtime_ns, size)} for all files included by this ledger."""
        _, _, options_map = state.get()
        filenames = list(options_map.get("include", []))
        if state.filename and state.filename not in filenames:
            filenames.append(state.filename)
        result = {}
        for fname in filenames:
            try:
                st = os.stat(fname)
                result[fname] = (st.st_mtime_ns, st.st_size)
            except OSError:
                pass
        return result

    def _loop(self) -> None:
        last: dict[str, dict] = {}  # ledger_id → file snapshot

        while not self._stop_event.wait(timeout=self.POLL_INTERVAL):
            for ledger_id, state in self._registry.all().items():
                try:
                    current = self._snapshot(state)
                    prev = last.get(ledger_id, {})

                    if prev and current != prev:
                        now = time.time()
                        if now - self._last_reload.get(ledger_id, 0) >= self._debounce:
                            changed = [f for f in current if current.get(f) != prev.get(f)]
                            logger.info(
                                "[%s] Change detected in %s, reloading...",
                                ledger_id, changed,
                            )
                            self._last_reload[ledger_id] = now
                            filename = state.filename
                            threading.Thread(
                                target=state.load,
                                args=(filename,),
                                daemon=True,
                                name=f"beancount-reload-{ledger_id}",
                            ).start()

                    last[ledger_id] = current
                except Exception:
                    logger.exception("[%s] Error in file watcher loop", ledger_id)
