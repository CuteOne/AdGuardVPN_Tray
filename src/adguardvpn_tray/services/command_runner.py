import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)


class Worker(QRunnable):
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self):
        try:
            result = self.fn()
        except Exception:
            self.signals.error.emit(traceback.format_exc())
            return
        self.signals.finished.emit(result)


class CommandRunner:
    def __init__(self):
        self.pool = QThreadPool.globalInstance()

    def submit(
        self,
        fn: Callable[[], Any],
        on_finished: Callable[[Any], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> Worker:
        worker = Worker(fn)
        if on_finished:
            worker.signals.finished.connect(on_finished)
        if on_error:
            worker.signals.error.connect(on_error)
        self.pool.start(worker)
        return worker
