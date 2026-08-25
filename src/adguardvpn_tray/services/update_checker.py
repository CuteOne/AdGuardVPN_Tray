from datetime import datetime, timezone

from PySide6.QtCore import QObject, QTimer, Signal

from adguardvpn_tray import constants
from adguardvpn_tray.adapters.cli_adapter import CliAdapter
from adguardvpn_tray.config.app_config import AppConfig
from adguardvpn_tray.services.command_runner import CommandRunner

_NO_UPDATE_MARKERS = ("no need to check", "up to date", "already up to date", "no updates")


class UpdateChecker(QObject):
    update_available = Signal(str)  # message
    check_finished = Signal(bool, str)  # available, message
    update_finished = Signal(bool, str)  # success, message

    def __init__(self, cli: CliAdapter, runner: CommandRunner, config: AppConfig):
        super().__init__()
        self._cli = cli
        self._runner = runner
        self._config = config

        self._timer = QTimer(self)
        self._timer.setInterval(60 * 60 * 1000)
        self._timer.timeout.connect(self._maybe_daily_check)

    def start(self) -> None:
        self._maybe_daily_check()
        self._timer.start()

    def _maybe_daily_check(self) -> None:
        now = datetime.now(timezone.utc)
        last = self._config.last_update_check_iso
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if (now - last_dt).total_seconds() < constants.UPDATE_CHECK_INTERVAL_S:
                    return
            except ValueError:
                pass
        self.check_now()

    def check_now(self) -> None:
        self._runner.submit(self._cli.check_update, on_finished=self._on_check_result)

    def _on_check_result(self, result) -> None:
        self._config.last_update_check_iso = datetime.now(timezone.utc).isoformat()
        self._config.save()

        text = (result.stdout + result.stderr).strip()
        lowered = text.lower()
        available = result.returncode == 0 and not any(marker in lowered for marker in _NO_UPDATE_MARKERS) and bool(text)
        self.check_finished.emit(available, text)
        if available:
            self.update_available.emit(text)

    def run_update(self) -> None:
        self._runner.submit(self._cli.update, on_finished=self._on_update_result)

    def _on_update_result(self, result) -> None:
        success = result.returncode == 0
        text = (result.stdout + result.stderr).strip()
        self.update_finished.emit(success, text)
