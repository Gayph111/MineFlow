from collections.abc import Callable
from threading import Event

Progress = Callable[[int, str], None]


class Cancelled(Exception):
    pass


class Task:
    def __init__(self, cancel: Event | None = None, progress: Progress | None = None):
        self.cancel = cancel if cancel is not None else Event()
        self.progress = progress

    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled

    def report(self, percent: int, message: str) -> None:
        self.check()
        if self.progress:
            self.progress(percent, message)

