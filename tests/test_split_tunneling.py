import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from adguardvpn_tray.adapters.cli_adapter import CliAdapter
from adguardvpn_tray.models.types import CliResult, ConnectionState
from adguardvpn_tray.parsers.exclusions_parser import (
    entry_problem,
    parse_exclusion_mode,
    parse_exclusions,
    parse_skipped_entries,
    split_entries,
)
from adguardvpn_tray.services import exclusions, gaming_mode
from adguardvpn_tray.services.exclusions import ExclusionsState
from adguardvpn_tray.services.gaming_mode import GamingAction


def _ok(stdout: str = "") -> CliResult:
    return CliResult(stdout=stdout, stderr="", returncode=0)


class ExclusionsParserTests(unittest.TestCase):
    def test_show_output(self):
        stdout = "Exclusions for \x1b[1mSELECTIVE\x1b[0m mode:\n192.0.2.1\nexample.org\n"
        self.assertEqual(parse_exclusions(stdout), ["192.0.2.1", "example.org"])

    def test_empty_list(self):
        self.assertEqual(parse_exclusions("Exclusions for \x1b[1mGENERAL\x1b[0m mode:\n\n"), [])

    def test_mode(self):
        self.assertEqual(parse_exclusion_mode("Current exclusion mode is \x1b[1mGENERAL\x1b[0m\n"), "general")
        self.assertEqual(parse_exclusion_mode("Current exclusion mode is SELECTIVE"), "selective")
        self.assertIsNone(parse_exclusion_mode("something else"))

    def test_skipped_entries(self):
        stdout = "Skipped invalid exclusion: entry!!\nSuccessfully added 1 exclusions\n"
        self.assertEqual(parse_skipped_entries(stdout), ["entry!!"])

    def test_split_entries(self):
        self.assertEqual(split_entries(" a.com, b.com\n*.c.com "), ["a.com", "b.com", "*.c.com"])

    def test_entry_problems(self):
        self.assertIsNone(entry_problem("10.0.0.0/8"))
        self.assertIsNotNone(entry_problem("--pid-file"))
        self.assertIsNotNone(entry_problem("two words"))
        self.assertIsNotNone(entry_problem(""))


class ExclusionsCliTests(unittest.TestCase):
    def test_add_passes_entries_and_mode(self):
        cli = CliAdapter(binary_path=sys.executable)
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(stdout="", stderr="", returncode=0)
            cli.exclusions_add(["a.com", "b.com"], "selective")
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[1:], ["site-exclusions", "add", "a.com", "b.com", "--for-mode", "selective"])
        self.assertNotEqual(cmd[0], "sudo")  # exclusions live in the user's config


class FakeExclusionsCli:
    def __init__(self, mode="general", lists=None, add_stdout=""):
        self.mode = mode
        self.lists = lists or {"general": [], "selective": []}
        self.add_stdout = add_stdout
        self.calls = []

    def exclusion_mode(self):
        return _ok(f"Current exclusion mode is {self.mode.upper()}")

    def exclusions_show(self, mode):
        return _ok(f"Exclusions for {mode.upper()} mode:\n" + "\n".join(self.lists[mode]) + "\n")

    def exclusions_add(self, entries, mode):
        self.calls.append(("add", tuple(entries), mode))
        return _ok(self.add_stdout)

    def exclusions_remove(self, entries, mode):
        self.calls.append(("remove", tuple(entries), mode))
        return _ok()

    def set_exclusion_mode(self, mode):
        self.calls.append(("mode", mode))
        return _ok()


class ExclusionsServiceTests(unittest.TestCase):
    def test_load(self):
        cli = FakeExclusionsCli(mode="selective", lists={"general": ["a.com"], "selective": ["b.com"]})
        state = exclusions.load(cli)
        self.assertEqual(state, ExclusionsState("selective", {"general": ["a.com"], "selective": ["b.com"]}))

    def test_load_reports_failure(self):
        cli = FakeExclusionsCli()
        cli.exclusion_mode = lambda: CliResult(stdout="", stderr="boom", returncode=1)
        self.assertIn("boom", exclusions.load(cli))

    def test_apply_sends_only_the_difference_and_mode_last(self):
        cli = FakeExclusionsCli()
        before = ExclusionsState("general", {"general": ["a.com", "b.com"], "selective": []})
        after = ExclusionsState("selective", {"general": ["b.com"], "selective": ["c.com"]})
        self.assertEqual(exclusions.apply(cli, before, after), [])
        self.assertEqual(
            cli.calls,
            [("remove", ("a.com",), "general"), ("add", ("c.com",), "selective"), ("mode", "selective")],
        )

    def test_apply_reports_entries_the_cli_skipped(self):
        cli = FakeExclusionsCli(add_stdout="Skipped invalid exclusion: nope!\n")
        before = ExclusionsState("general", {"general": [], "selective": []})
        after = ExclusionsState("general", {"general": ["nope!"], "selective": []})
        self.assertEqual(exclusions.apply(cli, before, after), ["adguardvpn-cli rejected 'nope!'"])


def _decide(**overrides):
    args = dict(
        enabled=True,
        games_running=True,
        state=ConnectionState.CONNECTED,
        paused=False,
        override=False,
        busy=False,
    )
    args.update(overrides)
    return gaming_mode.decide(**args)


class GamingDecisionTests(unittest.TestCase):
    def test_pauses_when_a_game_starts_on_a_live_tunnel(self):
        self.assertEqual(_decide(), GamingAction.PAUSE)
        self.assertEqual(_decide(state=ConnectionState.WAITING_FOR_NETWORK), GamingAction.PAUSE)

    def test_leaves_a_manual_connect_alone(self):
        self.assertEqual(_decide(override=True), GamingAction.NONE)

    def test_does_nothing_while_busy(self):
        self.assertEqual(_decide(busy=True), GamingAction.NONE)
        self.assertEqual(
            _decide(busy=True, games_running=False, paused=True, state=ConnectionState.DISCONNECTED),
            GamingAction.NONE,
        )

    def test_does_not_pause_when_disabled_or_disconnected(self):
        self.assertEqual(_decide(enabled=False), GamingAction.NONE)
        self.assertEqual(_decide(state=ConnectionState.DISCONNECTED), GamingAction.NONE)

    def test_resumes_once_the_games_close(self):
        self.assertEqual(
            _decide(games_running=False, paused=True, state=ConnectionState.DISCONNECTED), GamingAction.RESUME
        )

    def test_resumes_when_turned_off_mid_game(self):
        self.assertEqual(_decide(enabled=False, paused=True, state=ConnectionState.DISCONNECTED), GamingAction.RESUME)

    def test_stays_paused_while_a_game_runs(self):
        self.assertEqual(_decide(paused=True, state=ConnectionState.DISCONNECTED), GamingAction.NONE)


class ProcessScanTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.proc = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _add(self, pid: int, comm: str, argv: list[str]):
        entry = self.proc / str(pid)
        entry.mkdir()
        (entry / "comm").write_text(comm + "\n")
        (entry / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + (b"\0" if argv else b""))

    def test_matches_wine_exe_by_windows_path(self):
        self._add(10, "WowClassic.exe", ["Z:\\home\\me\\WoW Stuff\\WowClassic.exe", "-launch"])
        self.assertEqual(gaming_mode.running_games(["wowclassic.exe"], self.proc), ["WowClassic.exe"])

    def test_glob_and_truncated_comm(self):
        # comm is cut to 15 characters; the argv[0] basename still has the full name.
        self._add(11, "SomeVeryLongGam", ["/opt/games/SomeVeryLongGameName"])
        self.assertEqual(gaming_mode.running_games(["*longgame*"], self.proc), ["SomeVeryLongGameName"])

    def test_rewritten_electron_title_is_cut_at_options(self):
        self._add(12, "heroic", ["heroic --type=renderer --lang=en-US"])
        self.assertEqual(gaming_mode.running_program_names(self.proc), ["heroic"])
        self.assertEqual(gaming_mode.running_games(["heroic"], self.proc), ["heroic"])

    def test_path_with_spaces_is_kept(self):
        self._add(13, "guile.exe", ["/home/me/WoW Stuff/Component/guile.exe"])
        self.assertEqual(gaming_mode.running_program_names(self.proc), ["guile.exe"])

    def test_skips_kernel_threads_and_wine_helpers(self):
        self._add(2, "kthreadd", [])
        self._add(14, "services.exe", ["C:\\windows\\system32\\services.exe"])
        self.assertEqual(gaming_mode.running_program_names(self.proc), [])

    def test_no_patterns_matches_nothing(self):
        self._add(15, "game", ["/usr/bin/game"])
        self.assertEqual(gaming_mode.running_games([], self.proc), [])


if __name__ == "__main__":
    unittest.main()
