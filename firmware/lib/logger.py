"""
Minimal logging system for MicroPython (RP2040).

Memory-efficient design:
  - Log entries are tuples (timestamp, level_name, message) instead of dicts.
  - History is stored in a collections.deque with a fixed maxlen so pop(0) is
    O(1) and never allocates new list storage.
"""

import time

try:
    from collections import deque as _deque

    _HAS_DEQUE = True
except ImportError:
    _HAS_DEQUE = False


class Logger:
    """Lightweight logger for debugging and diagnostics on MicroPython."""

    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4

    _LEVEL_NAMES = {0: "DEBUG", 1: "INFO", 2: "WARN", 3: "ERROR", 4: "CRIT"}

    def __init__(self, name="App", level=INFO, enable_print=True, max_history=50):
        self.name = name
        self.level = level
        self.enable_print = enable_print
        self.max_history = max_history
        self._error_count = 0
        self._warning_count = 0

        # Use deque when available (O(1) append/pop), fall back to list
        if _HAS_DEQUE:
            self.history = _deque((), max_history)
        else:
            self.history = []

    def _log(self, level, message):
        if level < self.level:
            return
        ts = time.ticks_ms()
        level_name = self._LEVEL_NAMES.get(level, "UNK")
        entry = (ts, level_name, str(message))  # tuple, not dict

        if _HAS_DEQUE:
            self.history.append(entry)  # deque handles maxlen
        else:
            self.history.append(entry)
            if len(self.history) > self.max_history:
                self.history.pop(0)  # O(n) but only as fallback

        if level >= self.ERROR:
            self._error_count += 1
        elif level == self.WARNING:
            self._warning_count += 1

        if self.enable_print:
            print(f"[{level_name}] {self.name}: {message}")

    # ── Public API ────────────────────────────────────────────────────────────

    def debug(self, msg):
        self._log(self.DEBUG, msg)

    def info(self, msg):
        self._log(self.INFO, msg)

    def warning(self, msg):
        self._log(self.WARNING, msg)

    def error(self, msg):
        self._log(self.ERROR, msg)

    def critical(self, msg):
        self._log(self.CRITICAL, msg)

    def get_stats(self):
        """Return a dict with error/warning counts."""
        return {
            "total_logs": len(self.history),
            "errors": self._error_count,
            "warnings": self._warning_count,
        }

    def get_recent(self, count=10):
        """Return the last N log entries as a list of (ts, level, msg) tuples."""
        entries = list(self.history)
        return entries[-count:]

    def clear(self):
        """Clear history and reset counters."""
        if _HAS_DEQUE:
            # deque has no .clear() on all MicroPython versions — rebuild it
            self.history = _deque((), self.max_history)
        else:
            self.history.clear()
        self._error_count = 0
        self._warning_count = 0


# ── Module-level default instance ────────────────────────────────────────────

_default_logger = Logger("HVGen", level=Logger.INFO)


def get_logger(name=None):
    """Return the default logger, or a new WARNING-level logger for 'name'."""
    if name:
        return Logger(name, level=Logger.WARNING)
    return _default_logger
