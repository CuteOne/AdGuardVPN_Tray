import pathlib
import sys
import unittest
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from adguardvpn_tray.models.types import CliResult, ConnectionState, ConnectionStatus, LicenseInfo
from adguardvpn_tray.services import status_report, vpn_control
from adguardvpn_tray.services.status_report import ErrorRecord, StatusSnapshot

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
AT = datetime(2026, 10, 28, 9, 28, 41)
LICENSE = LicenseInfo(logged_in=True, email="user@example.com", tier="PREMIUM")


def snapshot(**overrides) -> StatusSnapshot:
    values = dict(
        summary="Connected: ATLANTA",
        status=ConnectionStatus(state=ConnectionState.CONNECTED, location="ATLANTA", mode="TUN", interface="tun0"),
        refresh_interval_s=6,
        binary_path="/usr/local/bin/adguardvpn-cli",
        last_check_at=AT,
        license=LICENSE,
    )
    values.update(overrides)
    return StatusSnapshot(**values)


class ShortReasonTests(unittest.TestCase):
    def test_first_non_empty_line(self):
        self.assertEqual(status_report.short_reason("\n  Timed out reading VPN status\nmore detail"), "Timed out reading VPN status")

    def test_ansi_is_stripped(self):
        self.assertEqual(status_report.short_reason("\x1b[31mConnection refused\x1b[0m"), "Connection refused")

    def test_long_reason_is_truncated_to_fit_a_menu(self):
        reason = status_report.short_reason("x" * 200)
        self.assertEqual(len(reason), status_report.SHORT_REASON_MAX_CHARS)
        self.assertTrue(reason.endswith("…"))

    def test_empty_text(self):
        self.assertEqual(status_report.short_reason(""), "unknown error")


class StatusFromResultTests(unittest.TestCase):
    def test_timeout_has_a_readable_reason(self):
        # Partial output on timeout must not become the error shown to the user.
        status = vpn_control.status_from_result(CliResult(stdout="Conn", stderr="", returncode=-1, timed_out=True))
        self.assertEqual(status.state, ConnectionState.ERROR)
        self.assertEqual(status.raw_text, "Timed out reading VPN status")

    def test_connected_output_is_parsed(self):
        stdout = (FIXTURES / "status_connected.txt").read_text()
        status = vpn_control.status_from_result(CliResult(stdout=stdout, stderr="", returncode=0))
        self.assertEqual(status.state, ConnectionState.CONNECTED)


class DetailRowsTests(unittest.TestCase):
    def test_connected_shows_connection_details(self):
        rows = dict(status_report.detail_rows(snapshot()))
        self.assertEqual(rows["Location"], "ATLANTA")
        self.assertEqual(rows["Mode"], "TUN")
        self.assertEqual(rows["Interface"], "tun0")
        self.assertEqual(rows["Last check"], "09:28:41 — OK (checks every 6 s)")
        self.assertEqual(rows["Last error"], "None since the tray started")
        self.assertEqual(rows["Account"], "user@example.com · PREMIUM tier")

    def test_error_state_shows_failed_check_and_full_error(self):
        error = ConnectionStatus(state=ConnectionState.ERROR, raw_text="Timed out reading VPN status")
        rows = dict(
            status_report.detail_rows(
                snapshot(
                    summary="Error: Timed out reading VPN status",
                    status=error,
                    last_error=ErrorRecord(AT, "status", "Timed out reading VPN status"),
                )
            )
        )
        self.assertNotIn("Location", rows)
        self.assertEqual(rows["Last check"], "09:28:41 — couldn't read status (checks every 6 s)")
        self.assertEqual(rows["Last error"], "09:28:41 — Timed out reading VPN status")

    def test_public_ip(self):
        self.assertEqual(dict(status_report.detail_rows(snapshot()))["Public IP"], "Not checked yet")
        rows = dict(status_report.detail_rows(snapshot(public_ip="203.0.113.7", public_ip_at=AT)))
        self.assertEqual(rows["Public IP"], "203.0.113.7 (checked 09:28:41)")
        rows = dict(status_report.detail_rows(snapshot(ip_checks_enabled=False)))
        self.assertEqual(rows["Public IP"], "IP checks are off")

    def test_account_while_license_unknown_or_logged_out(self):
        self.assertEqual(dict(status_report.detail_rows(snapshot(license=None)))["Account"], "Checking…")
        logged_out = snapshot(license=LicenseInfo(logged_in=False))
        self.assertEqual(dict(status_report.detail_rows(logged_out))["Account"], "Not logged in")

    def test_copied_text_leaves_out_the_email(self):
        # Copied details tend to be pasted into public bug reports.
        text = status_report.as_text(status_report.detail_rows(snapshot(), include_email=False))
        self.assertNotIn("user@example.com", text)
        self.assertIn("Account: PREMIUM tier", text)
        self.assertIn("Status: Connected: ATLANTA", text)


if __name__ == "__main__":
    unittest.main()
