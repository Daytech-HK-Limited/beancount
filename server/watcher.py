"""File change watcher — polls .beancount file mtimes and triggers hot reload."""

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)


class FileWatcher:
    POLL_INTERVAL = 2.0

    def __init__(self, state, debounce_seconds: float = 3.0):
        self._state = state
        self._debounce = debounce_seconds
        self._last_reload = 0.0
        self._stop_event = threading.Event()
        self._thread = None
        self._filename = None

    def start(self, filename: str) -> None:
        self._filename = filename
        self._thread = threading.Thread(target=self._loop, daemon=True, name="beancount-watcher")
        self._thread.start()
        logger.info("File watcher started for %s", filename)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _snapshot(self) -> dict:
        _, _, options_map = self._state.get()
        filenames = list(options_map.get("include", [self._filename]))
        result = {}
        for fname in filenames:
            try:
                st = os.stat(fname)
                result[fname] = (st.st_mtime_ns, st.st_size)
            except OSError:
                pass
        return result

    def _loop(self) -> None:
        last = {}
        while not self._stop_event.wait(timeout=self.POLL_INTERVAL):
            try:
                current = self._snapshot()
                if last and current != last:
                    now = time.time()
                    if now - self._last_reload >= self._debounce:
                        changed = [f for f in current if current.get(f) != last.get(f)]
                        logger.info("Change detected in %s, reloading...", changed)
                        self._last_reload = now
                        threading.Thread(
                            target=self._state.load,
                            args=(self._filename,),
                            daemon=True,
                            name="beancount-reload",
                        ).start()
                last = current
            except Exception:
                logger.exception("Error in file watcher loop")
