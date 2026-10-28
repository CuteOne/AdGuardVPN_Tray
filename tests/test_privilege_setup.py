import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from adguardvpn_tray.adapters.cli_adapter import CliAdapter
from adguardvpn_tray.services import privilege_setup

BINARY = "/usr/local/bin/adguardvpn-cli"


def elevated_args_run_by_tray() -> list[str]:
    """Argument strings CliAdapter actually passes through `sudo -n`."""
    cli = CliAdapter(binary_path=sys.executable)  # any real executable passes the lookup
    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with mock.patch("subprocess.run", side_effect=fake_run):
        cli.connect()
        cli.connect(fastest=True)
        cli.connect(location="São Paulo")
        cli.disconnect()
        cli.update()
    assert all(cmd[:2] == ["sudo", "-n"] for cmd in calls)
    return [" ".join(cmd[3:]) for cmd in calls]


def allowed_by_rule(args: str) -> bool:
    # The regex is plain POSIX ERE; Python's re reads this pattern the same way.
    return args in privilege_setup.FIXED_ELEVATED_ARGS or bool(re.fullmatch(privilege_setup.LOCATION_ARGS_REGEX, args))


class SudoersRuleTests(unittest.TestCase):
    def test_every_elevated_command_the_tray_runs_is_allowed(self):
        # Adding a root call to CliAdapter without widening the rule would make it fail
        # with "a password is required" for every user - catch that here instead.
        for args in elevated_args_run_by_tray():
            with self.subTest(args=args):
                self.assertTrue(allowed_by_rule(args))

    def test_real_location_names_are_allowed(self):
        for city in ("Atlanta", "New York", "São Paulo", "Chișinău", "Mumbai (Virtual)"):
            with self.subTest(city=city):
                self.assertTrue(allowed_by_rule(f"connect -y -l {city}"))

    def test_extra_options_cannot_be_smuggled_in(self):
        for args in (
            "connect -y -l Atlanta --pid-file /etc/passwd",
            "connect -y -l --pid-file /etc/passwd",
            "connect -y -l Atlanta -v",
            "connect -y -l ",
            "export-logs -o /etc/passwd -f",
            "config set-tun-routing-mode script",
            "connect -y --no-fork",
        ):
            with self.subTest(args=args):
                self.assertFalse(allowed_by_rule(args))

    def test_bare_binary_is_never_granted(self):
        content = privilege_setup._sudoers_content("someone", BINARY)
        self.assertFalse(privilege_setup.has_broad_rule(content.replace(", \\\n   ", ","), BINARY))

    @unittest.skipUnless(shutil.which("visudo"), "visudo not installed")
    def test_generated_rule_passes_visudo(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sudoers", delete=False) as tmp:
            tmp.write(privilege_setup._sudoers_content("someone", BINARY))
        self.addCleanup(os.unlink, tmp.name)
        check = subprocess.run(["visudo", "-c", "-f", tmp.name], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr or check.stdout)


class BroadRuleDetectionTests(unittest.TestCase):
    def test_old_unrestricted_rule(self):
        listing = "User ashley may run the following commands on host:\n    (ALL) ALL\n    (root) NOPASSWD: /usr/local/bin/adguardvpn-cli\n"
        self.assertTrue(privilege_setup.has_broad_rule(listing, BINARY))

    def test_unrestricted_rule_among_others(self):
        listing = "    (root) NOPASSWD: /usr/bin/true, /usr/local/bin/adguardvpn-cli, /usr/bin/false\n"
        self.assertTrue(privilege_setup.has_broad_rule(listing, BINARY))

    def test_restricted_rule(self):
        listing = (
            "    (root) NOPASSWD: /usr/local/bin/adguardvpn-cli --version, /usr/local/bin/adguardvpn-cli connect -y,\n"
            "        /usr/local/bin/adguardvpn-cli disconnect, /usr/local/bin/adguardvpn-cli update -y\n"
        )
        self.assertFalse(privilege_setup.has_broad_rule(listing, BINARY))


class BinaryPathTests(unittest.TestCase):
    def test_relative_path(self):
        self.assertIn("not an absolute path", privilege_setup.binary_path_problem("adguardvpn-cli"))

    def test_missing_file(self):
        self.assertIn("does not exist", privilege_setup.binary_path_problem("/nonexistent/adguardvpn-cli"))

    @unittest.skipIf(os.getuid() == 0, "files created by root are root-owned")
    def test_user_owned_binary_is_refused(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            pass
        self.addCleanup(os.unlink, tmp.name)
        self.assertIn("not owned by root", privilege_setup.binary_path_problem(tmp.name))

    @unittest.skipIf(os.getuid() == 0, "files created by root are root-owned")
    def test_symlink_in_user_owned_directory_is_refused(self):
        # Even when it points at a root-owned binary: whoever owns the directory can
        # swap the link. (The reverse - a root symlink into a user-owned directory,
        # as AdGuard's installer can leave /opt/adguardvpn_cli - is caught by checking
        # the resolved path's parents.)
        env = shutil.which("env")
        if env is None or os.stat(env).st_uid != 0:
            self.skipTest("no root-owned env binary")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        link = pathlib.Path(tmp.name) / "adguardvpn-cli"
        link.symlink_to(os.path.realpath(env))
        self.assertIn("not owned by root", privilege_setup.binary_path_problem(str(link)))

    def test_root_owned_system_binary_is_fine(self):
        env = shutil.which("env")
        if env is None or os.stat(env).st_uid != 0:
            self.skipTest("no root-owned env binary")
        self.assertIsNone(privilege_setup.binary_path_problem(os.path.realpath(env)))


class RunSetupTests(unittest.TestCase):
    def test_unsafe_binary_is_refused_before_any_prompt(self):
        with mock.patch("subprocess.run") as run:
            ok, message = privilege_setup.run_setup("adguardvpn-cli")
        self.assertFalse(ok)
        self.assertIn("Refusing", message)
        run.assert_not_called()  # no visudo, no pkexec prompt


if __name__ == "__main__":
    unittest.main()
