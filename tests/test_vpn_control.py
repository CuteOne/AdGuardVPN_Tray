import os
import pathlib
import signal
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from adguardvpn_tray import constants
from adguardvpn_tray.adapters.cli_adapter import CliAdapter
from adguardvpn_tray.config.app_config import AppConfig
from adguardvpn_tray.models.types import CliResult, ConnectionState, ConnectionStatus
from adguardvpn_tray.services import shutdown, vpn_control
from adguardvpn_tray.services.vpn_control import StartupAction

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

CONNECTED = CliResult(stdout=(FIXTURES / "status_connected.txt").read_text(), stderr="", returncode=0)
DISCONNECTED = CliResult(stdout=(FIXTURES / "status_disconnected.txt").read_text(), stderr="", returncode=0)
OK = CliResult(stdout="", stderr="", returncode=0)


def make_cli(statuses=(), disconnect=OK) -> mock.MagicMock:
    # Autospec keeps the fake honest: a call the real CliAdapter wouldn't accept fails here too.
    cli = mock.create_autospec(CliAdapter, instance=True)
    cli.status.side_effect = list(statuses)
    cli.disconnect.return_value = disconnect
    return cli


class DisconnectAndVerifyTests(unittest.TestCase):
    def test_verified_when_status_reports_disconnected(self):
        cli = make_cli(statuses=[DISCONNECTED])
        outcome = vpn_control.disconnect_and_verify(cli, sleep=lambda _s: None)
        self.assertTrue(outcome.verified)
        self.assertEqual(outcome.status.state, ConnectionState.DISCONNECTED)
        cli.disconnect.assert_called_once()

    def test_exit_code_zero_but_still_connected_is_not_trusted(self):
        cli = make_cli(statuses=[CONNECTED] * constants.DISCONNECT_VERIFY_ATTEMPTS)
        outcome = vpn_control.disconnect_and_verify(cli, sleep=lambda _s: None)
        self.assertFalse(outcome.verified)
        self.assertEqual(outcome.status.state, ConnectionState.CONNECTED)
        self.assertIn("still connected to ATLANTA", outcome.message)
        self.assertEqual(cli.status.call_count, constants.DISCONNECT_VERIFY_ATTEMPTS)

    def test_waits_for_slow_teardown(self):
        sleeps = []
        cli = make_cli(statuses=[CONNECTED, CONNECTED, DISCONNECTED])
        outcome = vpn_control.disconnect_and_verify(cli, verify_delay_s=1, sleep=sleeps.append)
        self.assertTrue(outcome.verified)
        self.assertEqual(sleeps, [1, 1])

    def test_sudo_failure_is_reported_with_cli_error(self):
        failed = CliResult(stdout="", stderr="sudo: a password is required\n", returncode=1)
        cli = make_cli(statuses=[CONNECTED], disconnect=failed)
        outcome = vpn_control.disconnect_and_verify(cli, sleep=lambda _s: None)
        self.assertFalse(outcome.verified)
        self.assertIn("sudo: a password is required", outcome.message)
        # The disconnect failed outright, so there's no teardown worth waiting for.
        self.assertEqual(cli.status.call_count, 1)

    def test_non_zero_exit_but_actually_down_counts_as_verified(self):
        failed = CliResult(stdout="VPN is not connected", stderr="", returncode=1)
        cli = make_cli(statuses=[DISCONNECTED], disconnect=failed)
        outcome = vpn_control.disconnect_and_verify(cli, sleep=lambda _s: None)
        self.assertTrue(outcome.verified)

    def test_disconnect_timeout_with_unreadable_status(self):
        timed_out = CliResult(stdout="", stderr="", returncode=-1, timed_out=True)
        status_timeout = CliResult(stdout="", stderr="", returncode=-1, timed_out=True)
        cli = make_cli(statuses=[status_timeout, status_timeout], disconnect=timed_out)
        outcome = vpn_control.disconnect_and_verify(cli, verify_attempts=2, sleep=lambda _s: None)
        self.assertFalse(outcome.verified)
        self.assertEqual(outcome.status.state, ConnectionState.ERROR)
        self.assertIn("Couldn't confirm", outcome.message)
        self.assertIn("timed out", outcome.message)

    def test_binary_missing(self):
        missing = CliResult(stdout="", stderr="binary not found", returncode=127, binary_missing=True)
        cli = make_cli(disconnect=missing)
        outcome = vpn_control.disconnect_and_verify(cli, sleep=lambda _s: None)
        self.assertFalse(outcome.verified)
        cli.status.assert_not_called()


class DisconnectForQuitTests(unittest.TestCase):
    def test_disabled_setting_leaves_vpn_alone(self):
        cli = make_cli()
        outcome = vpn_control.disconnect_for_quit(cli, AppConfig(disconnect_on_quit=False))
        self.assertIsNone(outcome)
        cli.status.assert_not_called()
        cli.disconnect.assert_not_called()

    def test_already_disconnected_does_nothing(self):
        cli = make_cli(statuses=[DISCONNECTED])
        outcome = vpn_control.disconnect_for_quit(cli, AppConfig(disconnect_on_quit=True))
        self.assertIsNone(outcome)
        cli.disconnect.assert_not_called()

    def test_connected_is_disconnected_with_short_timeouts(self):
        cli = make_cli(statuses=[CONNECTED, DISCONNECTED])
        outcome = vpn_control.disconnect_for_quit(cli, AppConfig(disconnect_on_quit=True), sleep=lambda _s: None)
        self.assertTrue(outcome.verified)
        cli.disconnect.assert_called_once_with(timeout=constants.TIMEOUT_QUIT_DISCONNECT_S)
        for call in cli.status.call_args_list:
            self.assertEqual(call.kwargs["timeout"], constants.TIMEOUT_QUIT_STATUS_S)

    def test_unreadable_status_still_attempts_disconnect(self):
        unreadable = CliResult(stdout="garbage", stderr="", returncode=1)
        cli = make_cli(statuses=[unreadable, DISCONNECTED])
        outcome = vpn_control.disconnect_for_quit(cli, AppConfig(disconnect_on_quit=True), sleep=lambda _s: None)
        self.assertTrue(outcome.verified)
        cli.disconnect.assert_called_once()

    def test_bounded_number_of_cli_calls_when_vpn_stays_up(self):
        cli = make_cli(statuses=[CONNECTED] * 10)
        outcome = vpn_control.disconnect_for_quit(cli, AppConfig(disconnect_on_quit=True), sleep=lambda _s: None)
        self.assertFalse(outcome.verified)
        # 1 pre-check + QUIT_DISCONNECT_VERIFY_ATTEMPTS verifications, then give up.
        self.assertEqual(cli.status.call_count, 1 + constants.QUIT_DISCONNECT_VERIFY_ATTEMPTS)


class StartupActionTests(unittest.TestCase):
    def status(self, state):
        return ConnectionStatus(state=state, location="ATLANTA" if state == ConnectionState.CONNECTED else None)

    def test_existing_connection_is_offered_for_disconnect(self):
        action = vpn_control.startup_action(self.status(ConnectionState.CONNECTED), auto_connect_on_launch=False)
        self.assertEqual(action, StartupAction.OFFER_DISCONNECT)

    def test_existing_connection_is_adopted_when_auto_connect_is_on(self):
        # Never CONNECT here - that would start a second connection.
        action = vpn_control.startup_action(self.status(ConnectionState.CONNECTED), auto_connect_on_launch=True)
        self.assertEqual(action, StartupAction.ADOPT)

    def test_disconnected_with_auto_connect(self):
        action = vpn_control.startup_action(self.status(ConnectionState.DISCONNECTED), auto_connect_on_launch=True)
        self.assertEqual(action, StartupAction.CONNECT)

    def test_disconnected_without_auto_connect(self):
        action = vpn_control.startup_action(self.status(ConnectionState.DISCONNECTED), auto_connect_on_launch=False)
        self.assertEqual(action, StartupAction.NONE)

    def test_error_is_not_assumed_disconnected(self):
        for auto_connect in (True, False):
            action = vpn_control.startup_action(self.status(ConnectionState.ERROR), auto_connect)
            self.assertEqual(action, StartupAction.UNDECIDED)

    def test_status_unavailable_exit_code_counts_as_connected(self):
        result = CliResult(stdout="VPN active, but status unavailable", stderr="", returncode=10)
        status = vpn_control.read_status(make_cli(statuses=[result]), timeout_s=1)
        self.assertEqual(vpn_control.startup_action(status, auto_connect_on_launch=True), StartupAction.ADOPT)


class AppConfigDefaultsTests(unittest.TestCase):
    def test_defaults(self):
        config = AppConfig()
        self.assertFalse(config.auto_connect_on_launch)
        self.assertTrue(config.disconnect_on_quit)

    def test_old_config_file_gets_disconnect_on_quit(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
            path = pathlib.Path(tmp) / constants.APP_CONFIG_DIR / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"auto_connect_on_launch": true}')
            config = AppConfig.load()
        self.assertTrue(config.auto_connect_on_launch)  # an explicit saved choice is kept
        self.assertTrue(config.disconnect_on_quit)


class QuitSignalTests(unittest.TestCase):
    def setUp(self):
        self._saved = {sig: signal.getsignal(sig) for sig in shutdown.QUIT_SIGNALS}

    def tearDown(self):
        for sig, handler in self._saved.items():
            signal.signal(sig, handler)

    def test_sigterm_requests_quit(self):
        request_quit = mock.Mock()
        shutdown.install_quit_signal_handlers(request_quit)
        os.kill(os.getpid(), signal.SIGTERM)
        request_quit.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
