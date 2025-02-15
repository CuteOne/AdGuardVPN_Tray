# vpn_tray.py
import logging
import os
import re
import functools
from PyQt5 import QtGui, QtCore, QtWidgets

# Import helpers from our new modules
from cli_commands import run_command, SUDO_CMD, VPN_CLI_PATH
from settings_manager import load_setting, save_setting
from login_dialog import LoginDialog

# Configurable constants for icons, etc.
#ICONS = os.path.join(os.path.abspath(os.getcwd()), r'resources/icons')
#ICON_CONNECTED = os.path.join(ICONS, r'Connected.png')
#ICON_DISCONNECTED = os.path.join(ICONS, r'Disconnected.png')
#ICON_UNKNOWN = os.path.join(ICONS, r'Unknown.png')
ICON_CONNECTED = QtGui.QIcon(":/icons/Connected.png")
ICON_DISCONNECTED = QtGui.QIcon(":/icons/Disconnected.png")
ICON_UNKNOWN = QtGui.QIcon(":/icons/Unknown.png")

class VpnTray(QtWidgets.QSystemTrayIcon):
    def __init__(self, icon, parent=None):
        super(VpnTray, self).__init__(icon, parent)
        self.setToolTip("AdGuard VPN Controller")
        self.menu = QtWidgets.QMenu(parent)

        # Status display (non-clickable)
        self.status_action = self.menu.addAction("Status: Unknown")
        self.status_action.setEnabled(False)
        self.menu.addSeparator()

        # Auto Connect toggle option (checkable)
        self.auto_connect_action = self.create_checkable_action("Auto Connect on Launch", self, default_checked=False)
        self.menu.addAction(self.auto_connect_action)
        self.menu.addSeparator()

        # Location submenu, Connect and Disconnect actions
        self.locations_menu = QtWidgets.QMenu("Location")
        self.menu.addMenu(self.locations_menu)
        self.locations_menu.aboutToShow.connect(self.update_locations_menu)

        self.connect_action = self.menu.addAction("Connect VPN")
        self.connect_action.triggered.connect(self.connect_vpn)
        self.disconnect_action = self.menu.addAction("Disconnect VPN")
        self.disconnect_action.triggered.connect(self.disconnect_vpn)
        self.menu.addSeparator()

        # Login/Logout and Quit actions
        self.login_logout_action = self.menu.addAction("Login")
        self.login_logout_action.triggered.connect(self.login_logout)
        self.quit_action = self.menu.addAction("Quit")
        self.quit_action.triggered.connect(QtWidgets.qApp.quit)
        self.setContextMenu(self.menu)

        # Timer for status updates
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.check_vpn_status)
        self.timer.start(30000)

        self.auto_connect_action.toggled.connect(self.save_auto_connect_setting)

        # Initialize state
        self.logged_in_user = load_setting("logged_in_user", None)
        self.selected_location = load_setting("selected_location", "")
        self.check_vpn_status()

    @staticmethod
    def create_checkable_action(text, parent, default_checked=False):
        action = QtWidgets.QAction(text, parent)
        action.setCheckable(True)
        action.setChecked(default_checked)
        return action

    @staticmethod
    def save_auto_connect_setting(checked):
        save_setting("auto_connect_on_launch", checked)

    def update_locations_menu(self):
        self.locations_menu.clear()
        cmd = f"{SUDO_CMD} {VPN_CLI_PATH} list-locations"
        stdout, stderr, returncode = run_command(cmd, "Listing Locations")
        if returncode != 0 or not stdout:
            error_action = self.locations_menu.addAction("Error retrieving locations")
            error_action.setEnabled(False)
            return

        lines = stdout.splitlines()
        if len(lines) < 2:
            error_action = self.locations_menu.addAction("No locations available")
            error_action.setEnabled(False)
            return

        locations = []
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = re.split(r'\s{2,}', line.strip())
            if len(parts) < 3:
                continue
            country = parts[1]
            city = parts[2]
            display_location = f"{city}, {country}"
            locations.append(display_location)

        if not locations:
            error_action = self.locations_menu.addAction("No locations available")
            error_action.setEnabled(False)
            return

        for loc in locations:
            action = QtWidgets.QAction(loc, self)
            action.setCheckable(True)
            if loc == self.selected_location:
                action.setChecked(True)
            action.triggered.connect(functools.partial(self.location_selected, loc))
            self.locations_menu.addAction(action)

    def location_selected(self, location):
        if location == self.selected_location:
            return
        self.selected_location = location
        save_setting("selected_location", self.selected_location)
        self.disconnect_vpn()
        self.connect_vpn()

    def login_logout(self):
        try:
            if self.logged_in_user is None:
                dlg = LoginDialog()
                if dlg.exec_() == QtWidgets.QDialog.Accepted:
                    username = dlg.username
                    password = dlg.password
                    cmd = f"{SUDO_CMD} {VPN_CLI_PATH} login -u {username} -p {password}"
                    stdout, stderr, returncode = run_command(cmd, "Login")
                    if returncode != 0:
                        QtWidgets.QMessageBox.warning(None, "Login Failed", f"Login failed:\n{stderr}")
                    else:
                        self.logged_in_user = username
                        save_setting("logged_in_user", self.logged_in_user)
                        self.login_logout_action.setText(f"Logout {username}")
                        QtWidgets.QMessageBox.information(None, "Login", "Login successful.")
                        self.connect_action.setEnabled(True)
                        self.disconnect_action.setEnabled(True)
            else:
                cmd = f"{SUDO_CMD} {VPN_CLI_PATH} logout"
                stdout, stderr, returncode = run_command(cmd, "Logout")
                if returncode != 0:
                    QtWidgets.QMessageBox.warning(None, "Logout Failed", f"Logout failed:\n{stderr}")
                else:
                    QtWidgets.QMessageBox.information(None, "Logout", "Logout successful.")
                    save_setting("logged_in_user", None)
                    self.logged_in_user = None
                    self.login_logout_action.setText("Login")
                    self.connect_action.setEnabled(False)
                    self.disconnect_action.setEnabled(False)
        except Exception as e:
            logging.exception("Exception in login_logout: %s", e)
            QtWidgets.QMessageBox.critical(None, "Error", f"An unexpected error occurred: {e}")

    def connect_vpn(self):
        if self.logged_in_user is None:
            QtWidgets.QMessageBox.warning(None, "Not Logged In", "Please log in before connecting.")
            return
        if not self.selected_location:
            cmd = f"{SUDO_CMD} {VPN_CLI_PATH} connect -f"
            stdout, stderr, returncode = run_command(cmd, "Connect VPN (Best Location)")
            msg = (f"Connect failed:\n{stderr}" if returncode != 0
                   else "VPN connected using the best available location.")
            self.showMessage("AdGuard VPN", msg, self.icon(), 3000)
            self.check_vpn_status()
            return
        selected_city = self.selected_location.split(",")[0].strip()
        cmd = f"{SUDO_CMD} {VPN_CLI_PATH} connect -l {selected_city}"
        stdout, stderr, returncode = run_command(cmd, "Connect VPN")
        msg = (f"Connect failed:\n{stderr}" if returncode != 0
                   else f"VPN connected to {self.selected_location} successfully.")
        self.showMessage("AdGuard VPN", msg, self.icon(), 3000)
        self.check_vpn_status()

    def disconnect_vpn(self, hide_ui=False):
        cmd = f"{SUDO_CMD} {VPN_CLI_PATH} disconnect"
        stdout, stderr, returncode = run_command(cmd, "Disconnect VPN")
        msg = (f"Disconnect failed:\n{stderr}" if returncode != 0
                   else "VPN disconnected successfully.")
        if not hide_ui:
            self.showMessage("AdGuard VPN", msg, self.icon(), 3000)
        self.check_vpn_status()

    def check_vpn_status(self):
        cmd = f"{SUDO_CMD} {VPN_CLI_PATH} status"
        stdout, stderr, returncode = run_command(cmd, "Checking Status")
        if returncode != 0:
            normalized_status = "error"
        else:
            first_line = stdout.splitlines()[0] if stdout else "Unknown"
            if first_line.lower().startswith("vpn is"):
                first_line = first_line[6:].strip()
            lower_line = first_line.lower()
            if "disconnected" in lower_line:
                normalized_status = "disconnected"
            elif "connected" in lower_line:
                normalized_status = "connected"
            else:
                normalized_status = lower_line

        if "Before connecting" in stdout:
            self.logged_in_user = None
            self.login_logout_action.setText("Login")
            self.connect_action.setEnabled(False)
            self.disconnect_action.setEnabled(False)
            save_setting("logged_in_user", None)
        else:
            if self.logged_in_user:
                self.login_logout_action.setText(f"Logout {self.logged_in_user}")
                self.connect_action.setEnabled(True)
                self.disconnect_action.setEnabled(True)
        display_status = normalized_status.capitalize()
        self.setToolTip(f"VPN Status: {display_status}")
        self.status_action.setText(f"Status: {display_status}")
        if normalized_status == "connected":
            self.setIcon(ICON_CONNECTED)
        elif normalized_status == "disconnected":
            self.setIcon(ICON_DISCONNECTED)
        else:
            self.setIcon(ICON_UNKNOWN)
        self.show()

    def set_icon(self, resource_path):
        new_icon = QtGui.QIcon(resource_path)
        if new_icon.isNull():
            logging.error("Embedded icon not loaded: %s", resource_path)
        self.setIcon(new_icon)
        self.show()

    def cleanup(self):
        self.disconnect_vpn(hide_ui=True)
