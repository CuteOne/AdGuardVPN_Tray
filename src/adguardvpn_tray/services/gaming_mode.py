import fnmatch
import os
import re
from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from adguardvpn_tray import constants
from adguardvpn_tray.models.types import TUNNEL_UP_STATES, ConnectionState

_PATH_SEP_RE = re.compile(r"[/\\]")
_REWRITTEN_ARGS_RE = re.compile(r"\s+-")
# Wine's own helpers (services.exe, explorer.exe, ...) run alongside every Windows
# game; offering them in the picker would only invite a pattern that never stops.
_WINE_SYSTEM_PREFIX = "c:\\windows\\"


class GamingAction(Enum):
    NONE = auto()
    PAUSE = auto()  # disconnect because a game started
    RESUME = auto()  # reconnect because every game has closed


def decide(
    *,
    enabled: bool,
    games_running: bool,
    state: ConnectionState,
    paused: bool,
    override: bool,
    busy: bool,
) -> GamingAction:
    # `state` must be the effective state; `busy` covers a connect/disconnect in flight
    # and the startup check, either of which would race a pause or resume.
    if busy:
        return GamingAction.NONE
    if paused and state == ConnectionState.DISCONNECTED and not (enabled and games_running):
        return GamingAction.RESUME
    if enabled and games_running and not paused and not override and state in TUNNEL_UP_STATES:
        return GamingAction.PAUSE
    return GamingAction.NONE


def _process_names(pid_dir: Path) -> tuple[str, list[str], str] | None:
    """(display name, names to match, argv[0]) for one /proc entry, or None for kernel threads and gone processes."""
    try:
        argv = (pid_dir / "cmdline").read_bytes().split(b"\0")
        comm = (pid_dir / "comm").read_text().strip()
    except OSError:
        return None
    argv0 = argv[0].decode("utf-8", errors="replace") if argv and argv[0] else ""
    if not argv0:
        return None
    # Electron/Chromium rewrite their whole command line into argv[0]
    # ("heroic --type=renderer ..."); a path can contain spaces, so cut at the options.
    argv0 = _REWRITTEN_ARGS_RE.split(argv0, maxsplit=1)[0]
    # The kernel cuts comm to 15 characters, so the argv[0] basename is the reliable
    # full name - and for Wine it's the Windows path, e.g. "C:\Games\Wow.exe".
    basename = _PATH_SEP_RE.split(argv0)[-1]
    return basename or comm, [name for name in {comm, basename} if name], argv0


def _user_processes(proc_root: Path):
    uid = os.getuid()
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
        except OSError:
            continue
        names = _process_names(entry)
        if names is not None:
            yield names


def running_games(patterns: list[str], proc_root: Path = Path("/proc")) -> list[str]:
    """Display names of this user's processes that match any pattern, sorted and de-duplicated."""
    lowered = [p.casefold() for p in patterns if p.strip()]
    if not lowered:
        return []
    found = set()
    for display, names, _argv0 in _user_processes(proc_root):
        if any(fnmatch.fnmatchcase(name.casefold(), pattern) for name in names for pattern in lowered):
            found.add(display)
    return sorted(found)


def running_program_names(proc_root: Path = Path("/proc")) -> list[str]:
    """Names for the "add a running program" picker."""
    names = set()
    for display, _names, argv0 in _user_processes(proc_root):
        if not argv0.casefold().startswith(_WINE_SYSTEM_PREFIX):
            names.add(display)
    return sorted(names, key=str.casefold)


class GameWatcher(QObject):
    games_changed = Signal(list)  # display names of matching processes; [] once none are left

    def __init__(self, patterns_getter, parent=None):
        super().__init__(parent)
        self._patterns_getter = patterns_getter
        self._running: list[str] = []
        self._timer = QTimer(self)
        self._timer.setInterval(constants.GAME_SCAN_INTERVAL_S * 1000)
        self._timer.timeout.connect(self.scan_now)

    @property
    def running(self) -> list[str]:
        return list(self._running)

    def start(self) -> None:
        self.scan_now()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def scan_now(self) -> None:
        # A /proc sweep is a few milliseconds, so it stays on the GUI thread.
        found = running_games(self._patterns_getter())
        if found != self._running:
            self._running = found
            self.games_changed.emit(found)
