import random

from PySide6.QtCore import QObject, QTimer, Signal

from adguardvpn_tray import constants
from adguardvpn_tray.adapters.cli_adapter import CliAdapter
from adguardvpn_tray.parsers.license_parser import parse_license
from adguardvpn_tray.parsers.status_parser import parse_status
from adguardvpn_tray.services.command_runner import CommandRunner


class Poller(QObject):
    status_updated = Signal(object)  # ConnectionStatus
    license_updated = Signal(object)  # LicenseInfo
    cli_missing = Signal()

    def __init__(self, cli: CliAdapter, runner: CommandRunner, interval_s: int):
        super().__init__()
        self._cli = cli
        self._runner = runner
        self._tick_count = 0

        self._timer = QTimer(self)
        self._timer.setInterval(interval_s * 1000)
        self._timer.timeout.connect(self._tick)

    def set_interval(self, interval_s: int) -> None:
        self._timer.setInterval(interval_s * 1000)

    def start(self) -> None:
        self._tick()
        self._poll_license()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def poll_license_now(self) -> None:
        self._poll_license()

    def force_repoll(self) -> None:
        delay_ms = random.randint(constants.FORCE_REPOLL_MIN_MS, constants.FORCE_REPOLL_MAX_MS)
        QTimer.singleShot(delay_ms, self._poll_status)

    def _tick(self) -> None:
        self._poll_status()
        self._tick_count += 1
        if self._tick_count % constants.LICENSE_POLL_EVERY_N_TICKS == 0:
            self._poll_license()

    def _poll_status(self) -> None:
        self._runner.submit(self._cli.status, on_finished=self._on_status_result)

    def _on_status_result(self, result) -> None:
        if result.binary_missing:
            self.cli_missing.emit()
            return
        status = parse_status(result.stdout, result.returncode)
        self.status_updated.emit(status)

    def _poll_license(self) -> None:
        self._runner.submit(self._cli.license, on_finished=self._on_license_result)

    def _on_license_result(self, result) -> None:
        if result.binary_missing:
            self.cli_missing.emit()
            return
        info = parse_license(result.stdout)
        self.license_updated.emit(info)
