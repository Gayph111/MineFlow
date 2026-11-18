from PySide6.QtCore import QThread, Signal

from services.task import Cancelled, Task


class Job(QThread):
    progress = Signal(int, str)
    done = Signal(object)
    failed = Signal(object)
    cancelled = Signal()

    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action
        self.task = Task(progress=self.progress.emit)

    def stop(self):
        self.task.cancel.set()

    def run(self):
        try:
            result = self.action(self.task)
        except Cancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(exc)
        else:
            self.done.emit(result)

