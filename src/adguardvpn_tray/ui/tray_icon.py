import time
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QSystemTrayIcon

from adguardvpn_tray import __version__, constants
from adguardvpn_tray.adapters.cli_adapter import CliAdapter
from adguardvpn_tray.config.app_config import AppConfig
from adguardvpn_tray.models.types import TUNNEL_UP_STATES, ConnectionState, ConnectionStatus, LicenseInfo
from adguardvpn_tray.parsers.ansi import strip_ansi
from adguardvpn_tray.parsers.locations_parser import parse_locations
from adguardvpn_tray.services import (
    autostart,
    error_reporter,
    exclusions,
    gaming_mode,
    ip_checker,
    privilege_setup,
    status_report,
    vpn_control,
)
from adguardvpn_tray.services.command_runner import CommandRunner
from adguardvpn_tray.services.exclusions import ExclusionsState
from adguardvpn_tray.services.gaming_mode import GameWatcher, GamingAction
from adguardvpn_tray.services.notifier import Notifier
from adguardvpn_tray.services.poller import Poller
from adguardvpn_tray.services.privilege_setup import SetupState
from adguardvpn_tray.services.status_report import DETAILS_HINT, ErrorRecord, StatusSnapshot
from adguardvpn_tray.services.update_checker import UpdateChecker
from adguardvpn_tray.services.vpn_control import DisconnectOutcome, StartupAction
from adguardvpn_tray.ui import icons
from adguardvpn_tray.ui.exclusions_dialog import ExclusionsDialog
from adguardvpn_tray.ui.favorites_dialog import FavoritesDialog, location_key
from adguardvpn_tray.ui.gaming_mode_dialog import GamingModeDialog
from adguardvpn_tray.ui.login_dialog import LoginDialog
from adguardvpn_tray.ui.region_map import CONTINENT_ORDER, continent_for
from adguardvpn_tray.ui.settings_dialog import SettingsDialog
from adguardvpn_tray.ui.status_dialog import StatusDetailsDialog


class TrayIcon(QSystemTrayIcon):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(icons.icon_for_state(ConnectionState.UNKNOWN), parent)
        self.config = config
        self.cli = CliAdapter(config.binary_path_override)
        self.runner = CommandRunner()
        self.poller = Poller(self.cli, self.runner, config.refresh_interval_s)
        self.update_checker = UpdateChecker(self.cli, self.runner, config)
        self.notifier = Notifier(self, lambda: self.config.show_notifications)
        self.game_watcher = GameWatcher(
            lambda: self.config.gaming_programs if self.config.gaming_mode_enabled else [], self
        )

        self._status = ConnectionStatus(state=ConnectionState.UNKNOWN)
        self._license = LicenseInfo(logged_in=False)
        self._license_checked = False
        self._optimistic: ConnectionState | None = None
        self._optimistic_generation = 0
        self._locations = []
        self._locations_fetched_at = 0.0
        self._manual_update_check = False
        self._login_dialog = None
        self._startup_check_pending = True
        self._quit_cleanup_done = False
        self._was_connected = False
        self._reconnect_attempts = 0
        self._pending_connect_reason = "manual"
        self._baseline_ip: str | None = None
        self._ip_verify_attempts = 0
        self._last_status_at: datetime | None = None
        self._last_error: ErrorRecord | None = None
        self._public_ip: str | None = None
        self._public_ip_at: datetime | None = None
        self._status_dialog: StatusDetailsDialog | None = None
        self._pending_disconnect_reason = "manual"
        self._running_games: list[str] = []
        self._paused_for_game = False
        self._resume_location: str | None = None  # None resumes with the default connect target
        self._game_override = False  # connected by hand during a game - leave it until the games close
        self._exclusions_busy = False

        self._build_menu()
        self.setContextMenu(self._menu)

        self.poller.status_updated.connect(self._on_status_updated)
        self.poller.license_updated.connect(self._on_license_updated)
        self.poller.cli_missing.connect(self._on_cli_missing)
        self.update_checker.check_finished.connect(self._on_check_finished)
        self.update_checker.update_finished.connect(self._on_update_finished)
        self.game_watcher.games_changed.connect(self._on_games_changed)

        self._refresh_ui()
        self.show()
        self.poller.start()
        self.update_checker.start()
        self.game_watcher.start()
        self._check_privilege_setup()

    # -- menu construction -------------------------------------------------

    def _build_menu(self) -> None:
        menu = QMenu()

        self._status_action = menu.addAction("Checking status…")
        self._status_action.setEnabled(False)
        status_details_action = menu.addAction("Status details…")
        status_details_action.triggered.connect(self._open_status_details)
        menu.addSeparator()

        self._primary_action = menu.addAction("Connect")
        self._primary_action.triggered.connect(self._on_primary_action)

        self._locations_menu = QMenu("Locations")
        self._locations_menu.aboutToShow.connect(self._on_locations_menu_about_to_show)
        menu.addMenu(self._locations_menu)

        self._gaming_action = menu.addAction("Gaming mode")
        self._gaming_action.setCheckable(True)
        self._gaming_action.setChecked(self.config.gaming_mode_enabled)
        self._gaming_action.triggered.connect(self._on_gaming_mode_toggled)

        self._account_menu = self._build_account_menu()
        menu.addMenu(self._account_menu)

        menu.addSeparator()
        settings_menu = self._build_settings_menu()
        menu.addMenu(settings_menu)

        menu.addSeparator()
        self._check_update_action = menu.addAction("Check for CLI updates…")
        self._check_update_action.triggered.connect(self._on_check_updates_clicked)
        about_action = menu.addAction("About")
        about_action.triggered.connect(self._show_about)

        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._on_quit_clicked)

        self._menu = menu

    def _add_menu_header(self, menu: QMenu, text: str) -> None:
        # QMenu.addSection() doesn't reliably render its label under every Qt
        # style/theme (observed blank on Breeze/Plasma 6) - a disabled action does.
        menu.addSeparator()
        header = menu.addAction(text)
        header.setEnabled(False)

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
        menu.setToolTipsVisible(True)

        self._add_menu_header(menu, "Connection Behavior")

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

        self._autoconnect_launch_action = menu.addAction("Connect automatically when the tray starts")
        self._autoconnect_launch_action.setToolTip(
            "Off by default. With autostart enabled, this connects the VPN at every login."
        )
        self._autoconnect_launch_action.setCheckable(True)
        self._autoconnect_launch_action.setChecked(self.config.auto_connect_on_launch)
        self._autoconnect_launch_action.triggered.connect(self._on_autoconnect_launch_toggled)

        self._autoreconnect_drop_action = menu.addAction("Auto-reconnect if dropped")
        self._autoreconnect_drop_action.setCheckable(True)
        self._autoreconnect_drop_action.setChecked(self.config.auto_reconnect_on_drop)
        self._autoreconnect_drop_action.triggered.connect(self._on_autoreconnect_drop_toggled)

        self._verify_ip_action = menu.addAction("Verify IP after connecting")
        self._verify_ip_action.setCheckable(True)
        self._verify_ip_action.setChecked(self.config.verify_ip_on_connect)
        self._verify_ip_action.triggered.connect(self._on_verify_ip_toggled)

        self._add_menu_header(menu, "App Behavior")

        self._autostart_action = menu.addAction("Autostart on login")
        self._autostart_action.setCheckable(True)
        self._autostart_action.setChecked(autostart.is_enabled())
        self._autostart_action.triggered.connect(self._on_autostart_toggled)

        self._disconnect_on_quit_action = menu.addAction("Disconnect VPN when quitting")
        self._disconnect_on_quit_action.setToolTip(
            "The VPN runs independently of the tray. Turn this off to keep it connected after the tray closes."
        )
        self._disconnect_on_quit_action.setCheckable(True)
        self._disconnect_on_quit_action.setChecked(self.config.disconnect_on_quit)
        self._disconnect_on_quit_action.triggered.connect(self._on_disconnect_on_quit_toggled)

        self._notifications_action = menu.addAction("Show notifications")
        self._notifications_action.setCheckable(True)
        self._notifications_action.setChecked(self.config.show_notifications)
        self._notifications_action.triggered.connect(self._on_notifications_toggled)

        self._add_menu_header(menu, "Split Tunneling")

        exceptions_action = menu.addAction("Exceptions…")
        exceptions_action.setToolTip("Sites and IPs that skip the VPN, or the only ones that use it.")
        exceptions_action.triggered.connect(self._open_exclusions_dialog)
        gaming_programs_action = menu.addAction("Gaming mode programs…")
        gaming_programs_action.setToolTip("Programs that pause the VPN while they run.")
        gaming_programs_action.triggered.connect(self._open_gaming_mode_dialog)

        menu.addSeparator()
        setup_permissions_action = menu.addAction("Set up VPN permissions…")
        setup_permissions_action.triggered.connect(self._on_setup_permissions_clicked)
        advanced_action = menu.addAction("Advanced settings…")
        advanced_action.triggered.connect(lambda: self._open_settings_dialog())

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
        elif state in TUNNEL_UP_STATES:
            self._primary_action.setText("Disconnect")
            self._primary_action.setEnabled(True)
        elif state in (ConnectionState.CONNECTING, ConnectionState.DISCONNECTING):
            self._primary_action.setText("Working…")
            self._primary_action.setEnabled(False)
        else:
            self._primary_action.setText("Connect")
            self._primary_action.setEnabled(True)

        self._refresh_account_menu()
        self._update_status_dialog()

    def _status_text(self, state: ConnectionState) -> tuple[str, str]:
        if state == ConnectionState.CONNECTED:
            location = self._status.location or "VPN"
            return f"Connected: {location}", f"AdGuard VPN — Connected to {location}"
        if state == ConnectionState.WAITING_FOR_NETWORK:
            location = self._status.location or "VPN"
            return (
                f"Waiting for network: {location}",
                f"AdGuard VPN — Network lost, waiting to reconnect to {location}",
            )
        if state == ConnectionState.CONNECTING:
            return "Connecting…", "AdGuard VPN — Connecting…"
        if state == ConnectionState.DISCONNECTING:
            return "Disconnecting…", "AdGuard VPN — Disconnecting…"
        if state == ConnectionState.DISCONNECTED and self._paused_for_game:
            games = ", ".join(self._running_games) or "a game"
            return f"Paused for gaming: {games}", f"AdGuard VPN — Paused while {games} runs"
        if state == ConnectionState.DISCONNECTED:
            return "Disconnected", "AdGuard VPN — Disconnected"
        if state == ConnectionState.NOT_LOGGED_IN:
            return "Not logged in", "AdGuard VPN — Not logged in"
        if state == ConnectionState.ERROR:
            reason = status_report.short_reason(self._status.raw_text)
            return f"Error: {reason}", f"AdGuard VPN — Error: {reason}"
        return "Checking status…", "AdGuard VPN — Checking status…"

    def _set_optimistic(self, state: ConnectionState, with_timeout: bool = True) -> None:
        self._optimistic = state
        # Each optimistic state gets its own timeout - a stale timer from an earlier
        # connect must not clobber a later action that is still in flight.
        self._optimistic_generation += 1
        self._refresh_ui()
        if with_timeout:
            generation = self._optimistic_generation
            QTimer.singleShot(
                constants.OPTIMISTIC_STATE_TIMEOUT_S * 1000, lambda: self._on_optimistic_timeout(generation)
            )

    def _on_optimistic_timeout(self, generation: int) -> None:
        if self._optimistic is not None and generation == self._optimistic_generation:
            self._optimistic = None
            self._status = ConnectionStatus(state=ConnectionState.ERROR, raw_text="Timed out waiting for status")
            self.notifier.notify("AdGuard VPN", f"Timed out waiting for a status update. {DETAILS_HINT}")
            self._record_error("status_timeout", "Timed out waiting for a status update after connect/disconnect.")
            self._refresh_ui()

    # -- poller callbacks ----------------------------------------------------

    def _on_status_updated(self, status: ConnectionStatus) -> None:
        previous_optimistic = self._optimistic
        was_connected = self._was_connected
        self._status = status
        self._last_status_at = datetime.now()
        if status.state == ConnectionState.ERROR:
            # Not written to the error log: polls repeat every few seconds and would flood it.
            self._last_error = ErrorRecord(self._last_status_at, "status", status.raw_text or "Couldn't read VPN status")

        if previous_optimistic == ConnectionState.CONNECTING and status.state in TUNNEL_UP_STATES:
            # The connect went through even if the network dropped straight after;
            # keeping CONNECTING would end in a bogus "timed out" error.
            self._optimistic = None
            if status.state == ConnectionState.CONNECTED:
                self.notifier.notify("AdGuard VPN", f"Connected to {status.location or 'VPN'}")
                self._maybe_verify_post_connect_ip()
        # DISCONNECTING is resolved by _on_disconnect_result, which verifies the outcome.

        if status.state in TUNNEL_UP_STATES:
            self._was_connected = True
            if status.state == ConnectionState.CONNECTED:
                self._reconnect_attempts = 0
        elif status.state == ConnectionState.DISCONNECTED:
            # No optimistic action in flight means WE didn't cause this transition
            # (not a user-initiated disconnect, not a location switch) - it's a real drop.
            unexpected_drop = was_connected and previous_optimistic is None
            self._was_connected = False
            self._maybe_capture_baseline_ip()
            if unexpected_drop:
                self._handle_unexpected_drop()

        if self._paused_for_game and self._optimistic is None and status.state in TUNNEL_UP_STATES:
            # Connected from outside the tray (e.g. the CLI) while paused - treat it like a manual connect.
            self._paused_for_game = False
            self._game_override = bool(self._running_games)

        self._refresh_ui()

        if self._startup_check_pending:
            self._handle_startup_status(status)
        self._apply_gaming_mode()

    def _handle_startup_status(self, status: ConnectionStatus) -> None:
        action = vpn_control.startup_action(status, self.config.auto_connect_on_launch)
        if action == StartupAction.UNDECIDED:
            return
        self._startup_check_pending = False
        if action == StartupAction.CONNECT:
            fastest = self.config.default_connect_target == "fastest"
            self._do_connect(fastest=fastest)
        elif action == StartupAction.ADOPT:
            self.notifier.notify("AdGuard VPN", f"Already connected to {status.location or 'VPN'} — keeping that connection.")
        elif action == StartupAction.OFFER_DISCONNECT:
            self._offer_disconnect_existing(status)

    def _offer_disconnect_existing(self, status: ConnectionStatus) -> None:
        reply = QMessageBox.question(
            None,
            "VPN already connected",
            f"AdGuard VPN is already connected to {status.location or 'a VPN location'}.\n\n"
            "It was probably left running by an earlier session. Disconnect it now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        # The dialog is modal but polling continues - only act if it's still connected.
        if reply == QMessageBox.StandardButton.Yes and self._effective_state() in TUNNEL_UP_STATES:
            self._do_disconnect()

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

    def _maybe_capture_baseline_ip(self) -> None:
        if not self.config.verify_ip_on_connect:
            return
        self.runner.submit(ip_checker.get_public_ip, on_finished=self._on_baseline_ip_result)

    def _on_baseline_ip_result(self, ip: str | None) -> None:
        if ip:
            self._baseline_ip = ip
            self._note_public_ip(ip)

    def _note_public_ip(self, ip: str) -> None:
        self._public_ip = ip
        self._public_ip_at = datetime.now()
        self._update_status_dialog()

    def _maybe_verify_post_connect_ip(self) -> None:
        if not self.config.verify_ip_on_connect or not self._baseline_ip:
            return
        self._ip_verify_attempts = 0
        # Give the OS-level route/interface switch a moment to settle after the CLI
        # reports "Connected" - checking immediately can still observe the pre-VPN route.
        QTimer.singleShot(constants.IP_VERIFY_SETTLE_DELAY_MS, self._run_post_connect_ip_check)

    def _run_post_connect_ip_check(self) -> None:
        if self._status.state != ConnectionState.CONNECTED:
            return
        self.runner.submit(ip_checker.get_public_ip, on_finished=self._on_post_connect_ip_result)

    def _on_post_connect_ip_result(self, ip: str | None) -> None:
        if ip:
            self._note_public_ip(ip)
        if not ip or ip != self._baseline_ip:
            return  # changed (or check failed) - nothing to report either way

        self._ip_verify_attempts += 1
        if self._ip_verify_attempts < constants.IP_VERIFY_MAX_ATTEMPTS:
            # Route may still be settling - retry a few times before concluding anything.
            QTimer.singleShot(constants.IP_VERIFY_SETTLE_DELAY_MS, self._run_post_connect_ip_check)
            return

        message = f"Connected, but your public IP ({ip}) hasn't changed — traffic may not be routed through the VPN."
        self.notifier.notify("AdGuard VPN", f"{message} {DETAILS_HINT}")
        self._record_error("ip_verify_mismatch", message)

    def _on_license_updated(self, info: LicenseInfo) -> None:
        self._license = info
        self._license_checked = True
        self._refresh_ui()

    def _on_cli_missing(self) -> None:
        self._status = ConnectionStatus(state=ConnectionState.ERROR, raw_text="adguardvpn-cli not found")
        self._status_action.setText("adguardvpn-cli not found on PATH")
        self.setIcon(icons.icon_for_state(ConnectionState.ERROR))
        self._primary_action.setEnabled(False)
        self._record_error("cli_missing", "adguardvpn-cli not found on PATH")

    # -- connect / disconnect -------------------------------------------------
    # Note: left-click on the tray icon is intentionally not wired to any action -
    # a stray click shouldn't be able to silently drop an active VPN connection.
    # Right-click (Qt's own contextMenu handling via setContextMenu) is the way in.

    def _on_primary_action(self) -> None:
        state = self._effective_state()
        if state == ConnectionState.NOT_LOGGED_IN:
            self._open_login_dialog()
        elif state in TUNNEL_UP_STATES:
            self._do_disconnect()
        elif state in (ConnectionState.DISCONNECTED, ConnectionState.ERROR, ConnectionState.UNKNOWN):
            fastest = self.config.default_connect_target == "fastest"
            self._do_connect(fastest=fastest)

    def _do_connect(self, location: str | None = None, fastest: bool = False, reason: str = "manual") -> None:
        self._startup_check_pending = False
        if reason == "manual":
            self._paused_for_game = False
            self._game_override = bool(self._running_games)
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
                self.notifier.notify("AdGuard VPN", f"Auto-reconnect gave up after repeated failures. {DETAILS_HINT}")
                self._record_error("auto_reconnect_failed", message)
            else:
                self.notifier.notify("AdGuard VPN", f"Connect failed: {status_report.short_reason(message)} {DETAILS_HINT}")
                self._record_error("connect_failed", message)
            self._refresh_ui()
        else:
            self.poller.force_repoll()

    def _do_disconnect(self, reason: str = "manual") -> None:
        self._startup_check_pending = False
        self._pending_disconnect_reason = reason
        # No optimistic timeout: the worker is bounded and always reports back.
        self._set_optimistic(ConnectionState.DISCONNECTING, with_timeout=False)
        self.runner.submit(lambda: vpn_control.disconnect_and_verify(self.cli), on_finished=self._on_disconnect_result)

    def _on_disconnect_result(self, outcome: DisconnectOutcome) -> None:
        self._optimistic = None
        for_game = self._pending_disconnect_reason == "gaming"
        if outcome.verified:
            self._status = outcome.status
            # Clear before the next poll sees DISCONNECTED, or it's mistaken for a drop.
            self._was_connected = False
            if for_game:
                games = ", ".join(self._running_games) or "your game"
                self.notifier.notify("AdGuard VPN", f"VPN paused while {games} runs. It reconnects when you close it.")
            else:
                self.notifier.notify("AdGuard VPN", "Disconnected")
            self._refresh_ui()
            self._apply_gaming_mode()  # the game may have closed while the disconnect ran
            return

        if for_game:
            self._paused_for_game = False

        if outcome.status.state in TUNNEL_UP_STATES:
            self._status = outcome.status
        else:
            self._status = ConnectionStatus(state=ConnectionState.ERROR, raw_text=outcome.message)
        self._record_error("disconnect_failed", outcome.message)
        self._refresh_ui()
        # A dialog rather than a notification: notifications can be turned off, and a
        # silently-still-up VPN is exactly what this check exists to surface.
        QMessageBox.warning(None, "Disconnect failed", outcome.message)

    # -- quit ----------------------------------------------------------------

    def _on_quit_clicked(self) -> None:
        outcome = self._disconnect_for_quit()
        if outcome is not None and not outcome.verified:
            reply = QMessageBox.question(
                None,
                "VPN still connected",
                f"{outcome.message}\n\nQuit anyway? The VPN will stay connected after the tray closes.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._status = outcome.status
                self._refresh_ui()
                self.poller.start()
                return
        self._quit_cleanup_done = True
        QApplication.quit()

    def shutdown(self) -> None:
        """Connected to QApplication.aboutToQuit - covers quits that skip the menu (SIGTERM at logout)."""
        if self._quit_cleanup_done:
            return
        self._quit_cleanup_done = True
        outcome = self._disconnect_for_quit()
        if outcome is not None and not outcome.verified:
            self.notifier.notify("AdGuard VPN", f"Tray closed but the VPN may still be up: {outcome.message}")

    def _disconnect_for_quit(self) -> DisconnectOutcome | None:
        # Runs on the GUI thread on purpose: quit must not return before it's done.
        # Every step is time-bounded (see the TIMEOUT_QUIT_* constants).
        self.poller.stop()
        self.game_watcher.stop()
        self.runner.wait_for_idle(constants.QUIT_WAIT_FOR_WORKERS_MS)  # let an in-flight connect land first
        outcome = vpn_control.disconnect_for_quit(self.cli, self.config)
        if outcome is not None and not outcome.verified:
            self._record_error("quit_disconnect_failed", outcome.message)
        return outcome

    # -- gaming mode -----------------------------------------------------------

    def _on_games_changed(self, games: list[str]) -> None:
        self._running_games = games
        if not games:
            self._game_override = False
        self._refresh_ui()
        self._apply_gaming_mode()

    def _apply_gaming_mode(self) -> None:
        action = gaming_mode.decide(
            enabled=self.config.gaming_mode_enabled,
            games_running=bool(self._running_games),
            state=self._effective_state(),
            paused=self._paused_for_game,
            override=self._game_override,
            busy=self._optimistic is not None or self._startup_check_pending,
        )
        if action == GamingAction.PAUSE:
            self._paused_for_game = True
            self._resume_location = self._status.location
            self._do_disconnect(reason="gaming")
        elif action == GamingAction.RESUME:
            self._paused_for_game = False
            location = self._resume_location_name()
            self._do_connect(location=location, fastest=location is None, reason="gaming_resume")

    def _resume_location_name(self) -> str | None:
        # `status` prints the city in capitals ("NEW YORK"); connect with the
        # list-locations spelling when it's known.
        location = self._resume_location
        if not location:
            return None
        for loc in self._locations:
            if loc.city.casefold() == location.casefold():
                return loc.city
        return location

    def _on_gaming_mode_toggled(self, checked: bool) -> None:
        if checked and not self.config.gaming_programs:
            self._gaming_action.setChecked(False)
            self._open_gaming_mode_dialog(enable=True)
            return
        self._set_gaming_mode(checked, self.config.gaming_programs)

    def _open_gaming_mode_dialog(self, enable: bool = False) -> None:
        dialog = GamingModeDialog(enable or self.config.gaming_mode_enabled, self.config.gaming_programs)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_gaming_mode(dialog.is_enabled(), dialog.programs())

    def _set_gaming_mode(self, enabled: bool, programs: list[str]) -> None:
        self.config.gaming_mode_enabled = enabled
        self.config.gaming_programs = programs
        self.config.save()
        self._gaming_action.setChecked(enabled)
        self.game_watcher.scan_now()  # emits games_changed, which pauses or resumes as needed
        self._apply_gaming_mode()

    # -- exceptions ------------------------------------------------------------

    def _open_exclusions_dialog(self) -> None:
        if self._exclusions_busy:
            QMessageBox.information(None, "VPN Exceptions", "Still applying the last change — try again in a moment.")
            return
        self.runner.submit(lambda: exclusions.load(self.cli), on_finished=self._on_exclusions_loaded)

    def _on_exclusions_loaded(self, loaded: ExclusionsState | str) -> None:
        if isinstance(loaded, str):
            QMessageBox.warning(None, "VPN Exceptions", loaded)
            self._record_error("exclusions_load_failed", loaded)
            return
        dialog = ExclusionsDialog(loaded)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        wanted = dialog.result_state()
        if wanted == loaded:
            return
        self._exclusions_busy = True
        self.runner.submit(lambda: exclusions.apply(self.cli, loaded, wanted), on_finished=self._on_exclusions_applied)

    def _on_exclusions_applied(self, problems: list[str]) -> None:
        self._exclusions_busy = False
        if problems:
            message = "\n".join(problems)
            self._record_error("exclusions_apply_failed", message)
            QMessageBox.warning(None, "VPN Exceptions", f"Some changes didn't apply:\n\n{message}")
        else:
            self.notifier.notify("AdGuard VPN", "Exceptions updated.")
        self.poller.force_repoll()  # the CLI briefly re-applies settings to a live tunnel

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

        favorite_keys = set(self.config.favorite_locations)
        favorites = [loc for loc in self._locations if location_key(loc) in favorite_keys]
        if favorites:
            self._add_menu_header(menu, "★ Favorites")
            for loc in favorites:
                label = f"{loc.city}, {loc.country} ({loc.iso}) — {loc.ping_ms} ms"
                action = menu.addAction(label)
                action.triggered.connect(lambda checked=False, city=loc.city: self._do_connect(location=city))
            menu.addSeparator()

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
        manage_favorites_action = menu.addAction("Manage Favorites…")
        manage_favorites_action.triggered.connect(self._open_favorites_dialog)

    def _open_favorites_dialog(self) -> None:
        if not self._locations:
            QMessageBox.information(None, "Favorites", "Locations haven't loaded yet — open the Locations menu first.")
            return
        dialog = FavoritesDialog(self._locations, set(self.config.favorite_locations))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.config.favorite_locations = sorted(dialog.selected_keys())
            self.config.save()
            self._populate_locations_menu()

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

    def _on_disconnect_on_quit_toggled(self, checked: bool) -> None:
        self.config.disconnect_on_quit = checked
        self.config.save()

    def _on_autoreconnect_drop_toggled(self, checked: bool) -> None:
        self.config.auto_reconnect_on_drop = checked
        self.config.save()

    def _on_verify_ip_toggled(self, checked: bool) -> None:
        self.config.verify_ip_on_connect = checked
        self.config.save()

    def _on_autostart_toggled(self, checked: bool) -> None:
        autostart.set_enabled(checked)
        self.config.autostart_enabled = checked
        self.config.save()

    def _on_notifications_toggled(self, checked: bool) -> None:
        self.config.show_notifications = checked
        self.config.save()

    def _open_settings_dialog(self, show_diagnostics: bool = False) -> None:
        dialog = SettingsDialog(
            self.config,
            self.cli,
            on_refresh_interval_changed=self.poller.set_interval,
            show_diagnostics=show_diagnostics,
        )
        dialog.exec()

    # -- status details --------------------------------------------------------

    def _open_status_details(self) -> None:
        # Non-modal and refreshed on every poll, so it can stay open to watch a drop happen.
        if self._status_dialog is None:
            self._status_dialog = StatusDetailsDialog(on_open_diagnostics=lambda: self._open_settings_dialog(True))
            self._status_dialog.finished.connect(self._on_status_dialog_finished)
            self._update_status_dialog()
        self._status_dialog.show()
        self._status_dialog.raise_()
        self._status_dialog.activateWindow()

    def _on_status_dialog_finished(self, _result) -> None:
        self._status_dialog = None

    def _update_status_dialog(self) -> None:
        if self._status_dialog is not None:
            self._status_dialog.update_snapshot(self._status_snapshot())

    def _status_snapshot(self) -> StatusSnapshot:
        summary, _tooltip = self._status_text(self._effective_state())
        return StatusSnapshot(
            summary=summary,
            status=self._status,
            refresh_interval_s=self.config.refresh_interval_s,
            binary_path=self.cli.binary_path,
            last_check_at=self._last_status_at,
            last_error=self._last_error,
            public_ip=self._public_ip,
            public_ip_at=self._public_ip_at,
            ip_checks_enabled=self.config.verify_ip_on_connect,
            license=self._license if self._license_checked else None,
        )

    def _record_error(self, context: str, message: str) -> None:
        self._last_error = ErrorRecord(datetime.now(), context, message)
        error_reporter.report_error(context, message)

    # -- privilege setup -----------------------------------------------------

    def _check_privilege_setup(self) -> None:
        self.runner.submit(
            lambda: privilege_setup.check_state(self.cli.binary_path),
            on_finished=self._on_startup_privilege_check_result,
        )

    def _on_startup_privilege_check_result(self, state: SetupState) -> None:
        if state == SetupState.MISSING:
            reply = QMessageBox.question(
                None,
                "One-time setup needed",
                "AdGuard VPN Tray needs a one-time permission grant to connect/disconnect the VPN.\n\n"
                "This will show a system authentication prompt once — no manual file editing required.\n\n"
                "Set up now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
        elif state == SetupState.BROAD:
            reply = QMessageBox.question(
                None,
                "Tighten VPN permissions",
                "Your current VPN permission lets any program running as you run adguardvpn-cli "
                "as root with any options, without a password.\n\n"
                "Replace it with one limited to what the tray needs (connect, disconnect, update)? "
                "This shows a system authentication prompt once.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
        else:
            if state == SetupState.UNSAFE_BINARY:
                self._warn_unsafe_binary()
            return
        if reply == QMessageBox.StandardButton.Yes:
            self._run_privilege_setup()

    def _warn_unsafe_binary(self) -> None:
        problem = privilege_setup.binary_path_problem(self.cli.binary_path) or ""
        self._record_error("unsafe_cli_binary", problem)
        QMessageBox.warning(
            None,
            "VPN permissions are unsafe",
            "The tray can run adguardvpn-cli as root without a password, but your user account "
            "can replace that binary — so anything running as you could get root.\n\n"
            f"{problem}\n\n"
            "AdGuard's installer or updater may set this ownership; check again after updating.",
        )

    def _on_setup_permissions_clicked(self) -> None:
        self.runner.submit(
            lambda: privilege_setup.check_state(self.cli.binary_path),
            on_finished=self._on_manual_privilege_check_result,
        )

    def _on_manual_privilege_check_result(self, state: SetupState) -> None:
        if state == SetupState.OK:
            QMessageBox.information(None, "VPN Permissions", "Already configured.")
            return
        if state == SetupState.UNSAFE_BINARY:
            self._warn_unsafe_binary()
            return
        self._run_privilege_setup()

    def _run_privilege_setup(self) -> None:
        self.runner.submit(
            lambda: privilege_setup.run_setup(self.cli.binary_path),
            on_finished=self._on_privilege_setup_result,
        )

    def _on_privilege_setup_result(self, result: tuple[bool, str]) -> None:
        success, message = result
        if success:
            self.notifier.notify("AdGuard VPN", message)
        else:
            QMessageBox.warning(None, "Setup failed", message)
            self._record_error("privilege_setup_failed", message)

    def _show_about(self) -> None:
        QMessageBox.about(
            None,
            "About",
            f"<b>AdGuard VPN Tray</b> v{__version__}<br><br>"
            "A KDE Plasma system tray application for managing AdGuard VPN.<br><br>"
            "Unofficial: not affiliated with, endorsed by, or supported by AdGuard.<br><br>"
            "License: MIT",
        )

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
            self.notifier.notify("AdGuard VPN", f"Update failed: {status_report.short_reason(message)} {DETAILS_HINT}")
            self._record_error("update_failed", message)
        self.poller.force_repoll()
