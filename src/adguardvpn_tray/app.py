import sys

from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from adguardvpn_tray.config.app_config import AppConfig
from adguardvpn_tray.models.types import ConnectionState
from adguardvpn_tray.ui import icons
from adguardvpn_tray.ui.tray_icon import TrayIcon


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("AdGuard VPN")
    app.setApplicationDisplayName("AdGuard VPN")
    app.setDesktopFileName("adguardvpn-tray")
    app.setWindowIcon(icons.icon_for_state(ConnectionState.CONNECTED))

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "AdGuard VPN Tray", "No system tray is available on this desktop session.")
        return 1

    config = AppConfig.load()
    tray = TrayIcon(config)  # noqa: F841 - keep a live reference for the app's lifetime

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
