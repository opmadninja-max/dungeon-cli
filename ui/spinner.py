"""Animated spinner for bridge calls."""

import sys
import threading
import time

from rich.console import Console

BRAILLE_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ASCII_CHARS = "|/-\\"


def _frames_for(stream) -> str:
    """Braille frames on UTF-8 streams, ASCII frames on legacy codepages (BUG-008)."""
    encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "").replace("_", "")
    return BRAILLE_CHARS if encoding == "utf8" else ASCII_CHARS


class Spinner:
    def __init__(self, message: str = "Thinking..."):
        self.message = message
        self._running = False
        self._thread: threading.Thread | None = None
        self._chars = _frames_for(sys.stdout)
        self._console = Console()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join()
        self._console.print(" " * (len(self.message) + 10), end="\r")

    def _animate(self) -> None:
        i = 0
        while self._running:
            try:
                self._console.print(f"{self._chars[i % len(self._chars)]} {self.message}", end="\r")
            except (UnicodeEncodeError, OSError):
                return
            time.sleep(0.1)
            i += 1

    def __enter__(self) -> "Spinner":
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.stop()
