# main.py
import sys
import os
from PyQt5 import QtWidgets, QtGui, QtCore
from vpn_tray import VpnTray
from settings_manager import load_setting
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app_debug.log", mode="w")
    ]
)

ICONS = os.path.join(os.path.abspath(os.getcwd()), r'resources/icons')
ICON_UNKNOWN = os.path.join(ICONS, r'Unknown.png')


def main():
    QtCore.QCoreApplication.setOrganizationName("AdGuard")
    QtCore.QCoreApplication.setApplicationName("VPNController")

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Ensure the app keeps running even if no windows are visible
    
    default_icon = QtGui.QIcon.fromTheme("network-vpn")
    if default_icon.isNull():
        default_icon = QtGui.QIcon(ICON_UNKNOWN)

    tray = VpnTray(default_icon)
    tray.show()
    tray.set_icon(ICON_UNKNOWN)
    app.aboutToQuit.connect(tray.cleanup)

    # Auto-connect if enabled
    if load_setting("auto_connect_on_launch", False):
        tray.connect_vpn()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
