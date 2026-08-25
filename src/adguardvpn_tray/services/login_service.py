import re

import pexpect
from PySide6.QtCore import QObject, QThread, Signal

from adguardvpn_tray import constants
from adguardvpn_tray.parsers.ansi import strip_ansi

_MENU_RE = re.compile(r"open link in browser", re.IGNORECASE)
_URL_RE = re.compile(r"https://\S+")
_SUCCESS_RE = re.compile(r"successfully logged in", re.IGNORECASE)
_FAILURE_RE = re.compile(r"failed to get auth link|authentication failed|login failed|error", re.IGNORECASE)


class LoginWorker(QObject):
    menu_ready = Signal()
    url_ready = Signal(str)
    succeeded = Signal()
    failed = Signal(str)
    timed_out = Signal()
    cancelled = Signal()
    finished = Signal()

    def __init__(self, binary_path: str):
        super().__init__()
        self.binary_path = binary_path
        self._child = None
        self._cancel_requested = False

    def run(self) -> None:
        try:
            self._child = pexpect.spawn(self.binary_path, ["login"], encoding="utf-8", timeout=20)
            self._do_login()
        except Exception as exc:  # noqa: BLE001 - surface any spawn/expect failure to the UI
            self.failed.emit(str(exc))
        finally:
            self._cleanup()
            self.finished.emit()

    def request_cancel(self) -> None:
        self._cancel_requested = True
        if self._child and self._child.isalive():
            self._child.terminate(force=True)

    def _do_login(self) -> None:
        child = self._child

        index = child.expect([_MENU_RE, pexpect.EOF, pexpect.TIMEOUT], timeout=20)
        if self._cancel_requested:
            self.cancelled.emit()
            return
        if index != 0:
            self._report_eof_or_timeout(index)
            return

        self.menu_ready.emit()
        child.sendline("b")

        url_index = child.expect([_URL_RE, pexpect.EOF, pexpect.TIMEOUT], timeout=15)
        if self._cancel_requested:
            self.cancelled.emit()
            return
        if url_index != 0:
            # menu may expect a bare keystroke rather than a line - retry without newline
            child.send("b")
            url_index = child.expect([_URL_RE, pexpect.EOF, pexpect.TIMEOUT], timeout=10)
        if url_index == 0:
            self.url_ready.emit(strip_ansi(child.after).strip())

        result_index = child.expect(
            [_SUCCESS_RE, _FAILURE_RE, pexpect.EOF, pexpect.TIMEOUT],
            timeout=constants.LOGIN_TIMEOUT_S,
        )
        if self._cancel_requested:
            self.cancelled.emit()
            return
        if result_index == 0:
            self.succeeded.emit()
        elif result_index == 1:
            self.failed.emit(strip_ansi(child.before + child.after))
        elif result_index == 2:
            self.failed.emit("adguardvpn-cli exited unexpectedly during login")
        else:
            self.timed_out.emit()

    def _report_eof_or_timeout(self, index: int) -> None:
        if index == 1:
            self.failed.emit("adguardvpn-cli exited unexpectedly during login")
        else:
            self.timed_out.emit()

    def _cleanup(self) -> None:
        if self._child and self._child.isalive():
            self._child.terminate(force=True)


class LoginService(QObject):
    menu_ready = Signal()
    url_ready = Signal(str)
    succeeded = Signal()
    failed = Signal(str)
    timed_out = Signal()
    cancelled = Signal()
    finished = Signal()

    _cancel_signal = Signal()

    def __init__(self, binary_path: str):
        super().__init__()
        self.binary_path = binary_path
        self._thread: QThread | None = None
        self._worker: LoginWorker | None = None

    def start(self) -> None:
        self._thread = QThread()
        self._worker = LoginWorker(self.binary_path)
        self._worker.moveToThread(self._thread)

        self._worker.menu_ready.connect(self.menu_ready)
        self._worker.url_ready.connect(self.url_ready)
        self._worker.succeeded.connect(self.succeeded)
        self._worker.failed.connect(self.failed)
        self._worker.timed_out.connect(self.timed_out)
        self._worker.cancelled.connect(self.cancelled)
        self._worker.finished.connect(self.finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._cancel_signal.connect(self._worker.request_cancel)

        self._thread.started.connect(self._worker.run)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_signal.emit()
