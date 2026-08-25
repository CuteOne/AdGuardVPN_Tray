import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from adguardvpn_tray import constants
from adguardvpn_tray.adapters.cli_adapter import CliAdapter
from adguardvpn_tray.config.app_config import AppConfig
from adguardvpn_tray.models.types import ConnectionState, ConnectionStatus, LicenseInfo
from adguardvpn_tray.parsers.ansi import strip_ansi
from adguardvpn_tray.parsers.locations_parser import parse_locations
from adguardvpn_tray.services import autostart
from adguardvpn_tray.services.command_runner import CommandRunner
from adguardvpn_tray.services.notifier import Notifier
from adguardvpn_tray.services.poller import Poller
from adguardvpn_tray.services.update_checker import UpdateChecker
from adguardvpn_tray.ui import icons
from adguardvpn_tray.ui.login_dialog import LoginDialog
from adguardvpn_tray.ui.region_map import CONTINENT_ORDER, continent_for
from adguardvpn_tray.ui.settings_dialog import SettingsDialog


class TrayIcon(QSystemTrayIcon):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(icons.icon_for_state(ConnectionState.UNKNOWN), parent)
        self.config = config
        self.cli = CliAdapter(config.binary_path_override)
        self.runner = CommandRunner()
        self.poller = Poller(self.cli, self.runner, config.refresh_interval_s)
        self.update_checker = UpdateChecker(self.cli, self.runner, config)
        self.notifier = Notifier(self, lambda: self.config.show_notifications)

        self._status = ConnectionStatus(state=ConnectionState.UNKNOWN)
        self._license = LicenseInfo(logged_in=False)
        self._license_checked = False
        self._optimistic: ConnectionState | None = None
        self._locations = []
        self._locations_fetched_at = 0.0
        self._manual_update_check = False
        self._login_dialog = None
        self._startup_autoconnect_pending = True
        self._was_connected = False
        self._reconnect_attempts = 0
        self._pending_connect_reason = "manual"

        self._build_menu()
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

        self.poller.status_updated.connect(self._on_status_updated)
        self.poller.license_updated.connect(self._on_license_updated)
        self.poller.cli_missing.connect(self._on_cli_missing)
        self.update_checker.check_finished.connect(self._on_check_finished)
        self.update_checker.update_finished.connect(self._on_update_finished)

        self._refresh_ui()
        self.show()
        self.poller.start()
        self.update_checker.start()

    # -- menu construction -------------------------------------------------

    def _build_menu(self) -> None:
        menu = QMenu()

        self._status_action = menu.addAction("Checking status…")
        self._status_action.setEnabled(False)
        menu.addSeparator()

        self._primary_action = menu.addAction("Connect")
        self._primary_action.triggered.connect(self._on_primary_action)

        self._locations_menu = QMenu("Locations")
        self._locations_menu.aboutToShow.connect(self._on_locations_menu_about_to_show)
        menu.addMenu(self._locations_menu)

        self._account_menu = self._build_account_menu()
        menu.addMenu(self._account_menu)

        menu.addSeparator()
        settings_menu = self._build_settings_menu()
        menu.addMenu(settings_menu)

        menu.addSeparator()
        self._check_update_action = menu.addAction("Check for CLI updates…")
        self._check_update_action.triggered.connect(self._on_check_updates_clicked)

        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(QApplication.quit)

        self._menu = menu

    def _build_account_menu(self) -> QMenu:
        menu = QMenu("Account")
        self._account_email_action = menu.addAction("Not logged in")
        self._account_email_action.setEnabled(False)
        self._account_detail_action = menu.addAction("")
        self._account_detail_action.setEnabled(False)
        self._account_detail_action.setVisible(False)
        menu.addSeparator()
        self._login_action = menu.addAction("Log in…")
        self._login_action.triggered.connect(self._open_login_dialog)
        self._logout_action = menu.addAction("Log out")
        self._logout_action.triggered.connect(self._on_logout_clicked)
        self._logout_action.setVisible(False)
        return menu

    def _build_settings_menu(self) -> QMenu:
        menu = QMenu("Settings")

        target_group = QActionGroup(menu)
        target_group.setExclusive(True)
        self._target_fastest_action = menu.addAction("Default connect target: Fastest")
        self._target_fastest_action.setCheckable(True)
        self._target_fastest_action.triggered.connect(lambda: self._set_default_target("fastest"))
        target_group.addAction(self._target_fastest_action)

        self._target_last_action = menu.addAction("Default connect target: Last selected")
        self._target_last_action.setCheckable(True)
        self._target_last_action.triggered.connect(lambda: self._set_default_target("last"))
        target_group.addAction(self._target_last_action)

        if self.config.default_connect_target == "last":
            self._target_last_action.setChecked(True)
        else:
            self._target_fastest_action.setChecked(True)

        menu.addSeparator()

        self._autoconnect_launch_action = menu.addAction("Auto-connect on launch")
        self._autoconnect_launch_action.setCheckable(True)
        self._autoconnect_launch_action.setChecked(self.config.auto_connect_on_launch)
        self._autoconnect_launch_action.triggered.connect(self._on_autoconnect_launch_toggled)

        self._autoreconnect_drop_action = menu.addAction("Auto-reconnect if dropped")
        self._autoreconnect_drop_action.setCheckable(True)
        self._autoreconnect_drop_action.setChecked(self.config.auto_reconnect_on_drop)
        self._autoreconnect_drop_action.triggered.connect(self._on_autoreconnect_drop_toggled)

        self._autostart_action = menu.addAction("Autostart on login")
        self._autostart_action.setCheckable(True)
        self._autostart_action.setChecked(autostart.is_enabled())
        self._autostart_action.triggered.connect(self._on_autostart_toggled)

        self._notifications_action = menu.addAction("Show notifications")
        self._notifications_action.setCheckable(True)
        self._notifications_action.setChecked(self.config.show_notifications)
        self._notifications_action.triggered.connect(self._on_notifications_toggled)

        menu.addSeparator()
        advanced_action = menu.addAction("Advanced settings…")
        advanced_action.triggered.connect(self._open_settings_dialog)

        return menu

    # -- state -------------------------------------------------------------

    def _effective_state(self) -> ConnectionState:
        if self._license_checked and not self._license.logged_in:
            return ConnectionState.NOT_LOGGED_IN
        if self._optimistic is not None:
            return self._optimistic
        return self._status.state

    def _refresh_ui(self) -> None:
        state = self._effective_state()
        self.setIcon(icons.icon_for_state(state))

        text, tooltip = self._status_text(state)
        self._status_action.setText(text)
        self.setToolTip(tooltip)

        if state == ConnectionState.NOT_LOGGED_IN:
            self._primary_action.setText("Log in…")
            self._primary_action.setEnabled(True)
        elif state == ConnectionState.CONNECTED:
            self._primary_action.setText("Disconnect")
            self._primary_action.setEnabled(True)
        elif state in (ConnectionState.CONNECTING, ConnectionState.DISCONNECTING):
            self._primary_action.setText("Working…")
            self._primary_action.setEnabled(False)
        else:
            self._primary_action.setText("Connect")
            self._primary_action.setEnabled(True)

        self._refresh_account_menu()

    def _status_text(self, state: ConnectionState) -> tuple[str, str]:
        if state == ConnectionState.CONNECTED:
            location = self._status.location or "VPN"
            return f"Connected: {location}", f"AdGuard VPN — Connected to {location}"
        if state == ConnectionState.CONNECTING:
            return "Connecting…", "AdGuard VPN — Connecting…"
        if state == ConnectionState.DISCONNECTING:
            return "Disconnecting…", "AdGuard VPN — Disconnecting…"
        if state == ConnectionState.DISCONNECTED:
            return "Disconnected", "AdGuard VPN — Disconnected"
        if state == ConnectionState.NOT_LOGGED_IN:
            return "Not logged in", "AdGuard VPN — Not logged in"
        if state == ConnectionState.ERROR:
            return "Error — see status", "AdGuard VPN — Error"
        return "Checking status…", "AdGuard VPN — Checking status…"

    def _set_optimistic(self, state: ConnectionState) -> None:
        self._optimistic = state
        self._refresh_ui()
        QTimer.singleShot(constants.OPTIMISTIC_STATE_TIMEOUT_S * 1000, self._on_optimistic_timeout)

    def _on_optimistic_timeout(self) -> None:
        if self._optimistic is not None:
            self._optimistic = None
            self._status = ConnectionStatus(state=ConnectionState.ERROR, raw_text="Timed out waiting for status")
            self.notifier.notify("AdGuard VPN", "Timed out waiting for a status update.")
            self._refresh_ui()

    # -- poller callbacks ----------------------------------------------------

    def _on_status_updated(self, status: ConnectionStatus) -> None:
        previous_optimistic = self._optimistic
        was_connected = self._was_connected
        self._status = status

        if previous_optimistic == ConnectionState.CONNECTING and status.state == ConnectionState.CONNECTED:
            self._optimistic = None
            self.notifier.notify("AdGuard VPN", f"Connected to {status.location or 'VPN'}")
        elif previous_optimistic == ConnectionState.DISCONNECTING and status.state == ConnectionState.DISCONNECTED:
            self._optimistic = None
            self.notifier.notify("AdGuard VPN", "Disconnected")

        if status.state == ConnectionState.CONNECTED:
            self._was_connected = True
            self._reconnect_attempts = 0
        elif status.state == ConnectionState.DISCONNECTED:
            # No optimistic action in flight means WE didn't cause this transition
            # (not a user-initiated disconnect, not a location switch) - it's a real drop.
            unexpected_drop = was_connected and previous_optimistic is None
            self._was_connected = False
            if unexpected_drop:
                self._handle_unexpected_drop()

        self._refresh_ui()

        if self._startup_autoconnect_pending and status.state != ConnectionState.UNKNOWN:
            self._startup_autoconnect_pending = False
            if self.config.auto_connect_on_launch and status.state == ConnectionState.DISCONNECTED:
                fastest = self.config.default_connect_target == "fastest"
                self._do_connect(fastest=fastest)

    def _handle_unexpected_drop(self) -> None:
        if not self.config.auto_reconnect_on_drop:
            self.notifier.notify("AdGuard VPN", "Connection dropped.")
            return
        self._schedule_reconnect_retry()

    def _schedule_reconnect_retry(self) -> None:
        self._reconnect_attempts += 1
        self.notifier.notify(
            "AdGuard VPN",
            f"Connection dropped — reconnecting (attempt {self._reconnect_attempts}/"
            f"{constants.AUTO_RECONNECT_MAX_ATTEMPTS})…",
        )
        QTimer.singleShot(constants.AUTO_RECONNECT_RETRY_DELAY_MS, self._do_auto_reconnect_attempt)

    def _do_auto_reconnect_attempt(self) -> None:
        fastest = self.config.default_connect_target == "fastest"
        self._do_connect(fastest=fastest, reason="auto_reconnect")

    def _on_license_updated(self, info: LicenseInfo) -> None:
        self._license = info
        self._license_checked = True
        self._refresh_ui()

    def _on_cli_missing(self) -> None:
        self._status = ConnectionStatus(state=ConnectionState.ERROR, raw_text="adguardvpn-cli not found")
        self._status_action.setText("adguardvpn-cli not found on PATH")
        self.setIcon(icons.icon_for_state(ConnectionState.ERROR))
        self._primary_action.setEnabled(False)

    # -- connect / disconnect -------------------------------------------------

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._on_primary_action()

    def _on_primary_action(self) -> None:
        state = self._effective_state()
        if state == ConnectionState.NOT_LOGGED_IN:
            self._open_login_dialog()
        elif state == ConnectionState.CONNECTED:
            self._do_disconnect()
        elif state in (ConnectionState.DISCONNECTED, ConnectionState.ERROR, ConnectionState.UNKNOWN):
            fastest = self.config.default_connect_target == "fastest"
            self._do_connect(fastest=fastest)

    def _do_connect(self, location: str | None = None, fastest: bool = False, reason: str = "manual") -> None:
        self._pending_connect_reason = reason
        self._set_optimistic(ConnectionState.CONNECTING)
        self.runner.submit(
            lambda: self.cli.connect(location=location, fastest=fastest),
            on_finished=self._on_connect_result,
        )

    def _on_connect_result(self, result) -> None:
        reason = self._pending_connect_reason
        if result.binary_missing:
            self._on_cli_missing()
            return
        if result.returncode != 0:
            self._optimistic = None
            message = strip_ansi(result.stderr or result.stdout).strip()
            if reason == "auto_reconnect" and self._reconnect_attempts < constants.AUTO_RECONNECT_MAX_ATTEMPTS:
                self._schedule_reconnect_retry()
                return
            self._status = ConnectionStatus(state=ConnectionState.ERROR, raw_text=message)
            if reason == "auto_reconnect":
                self.notifier.notify("AdGuard VPN", "Auto-reconnect gave up after repeated failures.")
            else:
                self.notifier.notify("AdGuard VPN", f"Connect failed: {message[:200]}")
            self._refresh_ui()
        else:
            self.poller.force_repoll()

    def _do_disconnect(self) -> None:
        self._set_optimistic(ConnectionState.DISCONNECTING)
        self.runner.submit(self.cli.disconnect, on_finished=self._on_disconnect_result)

    def _on_disconnect_result(self, result) -> None:
        if result.binary_missing:
            self._on_cli_missing()
            return
        if result.returncode != 0:
            self._optimistic = None
            message = strip_ansi(result.stderr or result.stdout).strip()
            self._status = ConnectionStatus(state=ConnectionState.ERROR, raw_text=message)
            self.notifier.notify("AdGuard VPN", f"Disconnect failed: {message[:200]}")
            self._refresh_ui()
        else:
            self.poller.force_repoll()

    # -- locations -----------------------------------------------------------

    def _on_locations_menu_about_to_show(self) -> None:
        stale = time.monotonic() - self._locations_fetched_at > constants.LOCATIONS_CACHE_TTL_S
        if stale or not self._locations:
            self._fetch_locations()
        else:
            self._populate_locations_menu()

    def _fetch_locations(self) -> None:
        self._locations_menu.clear()
        loading = self._locations_menu.addAction("Loading…")
        loading.setEnabled(False)
        self.runner.submit(self.cli.list_locations, on_finished=self._on_locations_result)

    def _on_locations_result(self, result) -> None:
        if result.binary_missing:
            self._on_cli_missing()
            return
        self._locations = parse_locations(result.stdout)
        self._locations_fetched_at = time.monotonic()
        self._populate_locations_menu()

    def _populate_locations_menu(self) -> None:
        menu = self._locations_menu
        menu.clear()

        fastest_action = menu.addAction("Fastest (auto)")
        fastest_action.triggered.connect(lambda: self._do_connect(fastest=True))
        menu.addSeparator()

        if not self._locations:
            empty = menu.addAction("No locations available")
            empty.setEnabled(False)
            return

        by_continent: dict[str, list] = {}
        for loc in self._locations:
            by_continent.setdefault(continent_for(loc.iso), []).append(loc)

        for continent in CONTINENT_ORDER:
            locs = by_continent.get(continent)
            if not locs:
                continue
            submenu = menu.addMenu(continent)
            for loc in locs:
                label = f"{loc.city}, {loc.country} ({loc.iso}) — {loc.ping_ms} ms"
                action = submenu.addAction(label)
                action.triggered.connect(lambda checked=False, city=loc.city: self._do_connect(location=city))

        menu.addSeparator()
        refresh_action = menu.addAction("Refresh")
        refresh_action.triggered.connect(self._fetch_locations)

    # -- account -------------------------------------------------------------

    def _refresh_account_menu(self) -> None:
        info = self._license
        if info.logged_in:
            self._account_email_action.setText(info.email or "Logged in")
            details = [d for d in (info.tier and f"{info.tier} tier", info.device_limit, info.renewal_date and f"renews {info.renewal_date}") if d]
            if details:
                self._account_detail_action.setText(" · ".join(details))
                self._account_detail_action.setVisible(True)
            else:
                self._account_detail_action.setVisible(False)
            self._login_action.setVisible(False)
            self._logout_action.setVisible(True)
        else:
            self._account_email_action.setText("Not logged in")
            self._account_detail_action.setVisible(False)
            self._login_action.setVisible(True)
            self._logout_action.setVisible(False)

    def _open_login_dialog(self) -> None:
        if self._login_dialog is not None:
            self._login_dialog.raise_()
            self._login_dialog.activateWindow()
            return
        self._login_dialog = LoginDialog(self.cli.binary_path)
        self._login_dialog.finished.connect(self._on_login_dialog_finished)
        self._login_dialog.show()

    def _on_login_dialog_finished(self, _result) -> None:
        succeeded = self._login_dialog.succeeded if self._login_dialog else False
        self._login_dialog = None
        if succeeded:
            self.poller.poll_license_now()
            self.notifier.notify("AdGuard VPN", "Successfully logged in.")

    def _on_logout_clicked(self) -> None:
        reply = QMessageBox.question(
            None,
            "Log out",
            "Log out of AdGuard VPN? You'll need to log in again to connect.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.runner.submit(self.cli.logout, on_finished=self._on_logout_result)

    def _on_logout_result(self, _result) -> None:
        self.poller.poll_license_now()
        self.poller.force_repoll()

    # -- settings --------------------------------------------------------------

    def _set_default_target(self, target: str) -> None:
        self.config.default_connect_target = target
        self.config.save()

    def _on_autoconnect_launch_toggled(self, checked: bool) -> None:
        self.config.auto_connect_on_launch = checked
        self.config.save()

    def _on_autoreconnect_drop_toggled(self, checked: bool) -> None:
        self.config.auto_reconnect_on_drop = checked
        self.config.save()

    def _on_autostart_toggled(self, checked: bool) -> None:
        autostart.set_enabled(checked)
        self.config.autostart_enabled = checked
        self.config.save()

    def _on_notifications_toggled(self, checked: bool) -> None:
        self.config.show_notifications = checked
        self.config.save()

    def _open_settings_dialog(self) -> None:
        dialog = SettingsDialog(self.config, self.cli, on_refresh_interval_changed=self.poller.set_interval)
        dialog.exec()

    # -- updates -----------------------------------------------------------

    def _on_check_updates_clicked(self) -> None:
        self._manual_update_check = True
        self.update_checker.check_now()

    def _on_check_finished(self, available: bool, message: str) -> None:
        if self._manual_update_check:
            self._manual_update_check = False
            if available:
                reply = QMessageBox.question(
                    None,
                    "Update available",
                    f"{message}\n\nInstall the update now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self.update_checker.run_update()
            else:
                QMessageBox.information(None, "Up to date", message or "You're running the latest version.")
        elif available:
            self.notifier.notify("AdGuard VPN", "A CLI update is available. Open the tray menu to install it.")

    def _on_update_finished(self, success: bool, message: str) -> None:
        if success:
            self.notifier.notify("AdGuard VPN", "CLI updated successfully.")
        else:
            self.notifier.notify("AdGuard VPN", f"Update failed: {message[:200]}")
        self.poller.force_repoll()
