import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from adguardvpn_tray import constants
from adguardvpn_tray.config.app_config import AppConfig
from adguardvpn_tray.models.types import ConnectionState
from adguardvpn_tray.services import shutdown, single_instance
from adguardvpn_tray.ui import icons
from adguardvpn_tray.ui.tray_icon import TrayIcon


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("AdGuard VPN")
    app.setApplicationDisplayName("AdGuard VPN")
    app.setDesktopFileName("adguardvpn-tray")
    app.setWindowIcon(icons.icon_for_state(ConnectionState.CONNECTED))

    instance_lock = single_instance.acquire()
    if instance_lock is None:
        QMessageBox.information(None, "Already running", "AdGuard VPN Tray is already running in the system tray.")
        return 0

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "No system tray", "No system tray is available on this desktop session.")
        return 1

    config = AppConfig.load()
    tray = TrayIcon(config)
    app.aboutToQuit.connect(tray.shutdown)

    shutdown.install_quit_signal_handlers(app.quit)
    # Python only runs signal handlers once Qt's C++ event loop hands control back,
    # so wake the interpreter periodically or a SIGTERM would sit unhandled.
    signal_wakeup = QTimer()
    signal_wakeup.timeout.connect(lambda: None)
    signal_wakeup.start(constants.SIGNAL_CHECK_INTERVAL_MS)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
