import shutil
import subprocess

from PySide6.QtWidgets import QSystemTrayIcon


class Notifier:
    def __init__(self, tray_icon: QSystemTrayIcon, enabled_getter):
        self.tray_icon = tray_icon
        self._enabled_getter = enabled_getter
        self._notify_send = shutil.which("notify-send")

    def notify(self, title: str, message: str, icon=None, timeout_ms: int = 5000) -> None:
        if not self._enabled_getter():
            return

        shown = False
        if self.tray_icon.supportsMessages():
            try:
                self.tray_icon.showMessage(
                    title, message, icon or QSystemTrayIcon.MessageIcon.Information, timeout_ms
                )
                shown = True
            except Exception:
                shown = False

        if not shown and self._notify_send:
            subprocess.run(
                [self._notify_send, "--app-name=AdGuard VPN", title, message],
                check=False,
                capture_output=True,
            )
