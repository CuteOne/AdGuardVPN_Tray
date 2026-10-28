import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QCoreApplication

from adguardvpn_tray.adapters.cli_adapter import CliAdapter
from adguardvpn_tray.models.types import CliResult, ConnectionState
from adguardvpn_tray.services import autostart, single_instance
from adguardvpn_tray.services.command_runner import CommandRunner
from adguardvpn_tray.services.poller import Poller
from adguardvpn_tray import constants

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def setUpModule():
    # Poller is a QObject with a QTimer, which want an application instance.
    global _app
    _app = QCoreApplication.instance() or QCoreApplication([])


class CliTimeoutTests(unittest.TestCase):
    def _run_with_timeout(self, stdout, stderr):
        cli = CliAdapter(binary_path=sys.executable)  # any real executable passes the lookup
        exc = subprocess.TimeoutExpired(cmd=["adguardvpn-cli", "license"], timeout=10, output=stdout, stderr=stderr)
        with mock.patch("subprocess.run", side_effect=exc):
            return cli.license()

    def test_partial_bytes_output_is_decoded(self):
        # subprocess hands back bytes on timeout even with text=True; the parsers
        # crashed with "cannot use a string pattern on a bytes-like object".
        result = self._run_with_timeout(b"Logged in as \xe2\x9c\x93", b"\xff")
        self.assertTrue(result.timed_out)
        self.assertEqual(result.stdout, "Logged in as ✓")
        self.assertEqual(result.stderr, "�")

    def test_missing_output_becomes_empty_string(self):
        result = self._run_with_timeout(None, None)
        self.assertEqual((result.stdout, result.stderr), ("", ""))


class LicensePollTests(unittest.TestCase):
    def setUp(self):
        self.poller = Poller(mock.create_autospec(CliAdapter, instance=True), mock.create_autospec(CommandRunner, instance=True), 6)
        self.updates = []
        self.poller.license_updated.connect(self.updates.append)

    def test_timed_out_check_keeps_last_known_license(self):
        self.poller._on_license_result(CliResult(stdout="partial", stderr="", returncode=-1, timed_out=True))
        self.assertEqual(self.updates, [])

    def test_completed_check_is_reported(self):
        stdout = (FIXTURES / "license_logged_in.txt").read_text()
        self.poller._on_license_result(CliResult(stdout=stdout, stderr="", returncode=0))
        self.assertEqual(len(self.updates), 1)
        self.assertTrue(self.updates[0].logged_in)


class StatusPollTests(unittest.TestCase):
    def test_timed_out_poll_reports_why(self):
        poller = Poller(mock.create_autospec(CliAdapter, instance=True), mock.create_autospec(CommandRunner, instance=True), 6)
        statuses = []
        poller.status_updated.connect(statuses.append)
        poller._on_status_result(CliResult(stdout="Conn", stderr="", returncode=-1, timed_out=True))
        self.assertEqual(statuses[0].state, ConnectionState.ERROR)
        self.assertEqual(statuses[0].raw_text, "Timed out reading VPN status")


class AutostartTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_entry_is_not_executable(self):
        autostart.enable()
        mode = stat.S_IMODE(autostart.autostart_path().stat().st_mode)
        self.assertEqual(mode, 0o644)

    def test_entry_uses_adguard_icon(self):
        autostart.enable()
        self.assertIn(f"Icon={constants.APP_ICON_PATH}\n", autostart.autostart_path().read_text())
        self.assertTrue(constants.APP_ICON_PATH.is_file())


class SingleInstanceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_second_instance_is_refused(self):
        first = single_instance.acquire()
        self.assertIsNotNone(first)
        self.addCleanup(first.unlock)
        self.assertIsNone(single_instance.acquire())

    def test_lock_is_free_again_after_release(self):
        single_instance.acquire().unlock()
        second = single_instance.acquire()
        self.assertIsNotNone(second)
        second.unlock()

    def test_lock_left_by_dead_process_is_taken_over(self):
        # QLockFile's format: pid, app name, hostname. A PID that can't exist is stale.
        single_instance.lock_path().write_text("2147483646\nadguardvpn-tray\n\n")
        lock = single_instance.acquire()
        self.assertIsNotNone(lock)
        lock.unlock()


if __name__ == "__main__":
    unittest.main()
