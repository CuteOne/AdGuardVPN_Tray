import getpass
import os
import re
import shutil
import stat
import subprocess
import tempfile
from enum import Enum, auto
from pathlib import Path

SUDOERS_PATH = Path("/etc/sudoers.d/adguardvpn-tray")

# The only argument lists the tray runs as root (see CliAdapter: connect, disconnect,
# update) plus --version, which _sudo_can_run uses to detect the rule. Granting the bare
# binary instead would let any program running as the user run *any* subcommand as
# root - e.g. `export-logs -o <path> -f` overwrites any file.
FIXED_ELEVATED_ARGS = (
    "--version",
    "connect -y",
    "connect -y -f",
    "disconnect",
    "update -y",
)
# `connect -y -l <location>`: no word of the location may start with "-", so options
# like --pid-file (which writes a file as root) can't be appended. Location names
# contain spaces, parentheses and non-ASCII letters ("São Paulo", "Mumbai (Virtual)"),
# so anything else is allowed. sudo >= 1.9.10 treats ^...$ arguments as a regex.
LOCATION_ARGS_REGEX = "^connect -y -l [^ -][^ ]*( [^ -][^ ]*)*$"


class SetupState(Enum):
    MISSING = auto()  # sudo -n can't run the binary - setup never ran
    BROAD = auto()  # an older rule grants the binary with any arguments
    UNSAFE_BINARY = auto()  # granted, but the user can replace the binary (see binary_path_problem)
    OK = auto()


def check_state(binary_path: str) -> SetupState:
    if not _sudo_can_run(binary_path):
        return SetupState.MISSING
    if binary_path_problem(binary_path):
        return SetupState.UNSAFE_BINARY
    listing = _run(["sudo", "-n", "-l"])
    if listing is not None and has_broad_rule(listing.stdout, binary_path):
        return SetupState.BROAD
    return SetupState.OK


def has_broad_rule(sudo_listing: str, binary_path: str) -> bool:
    """True if `sudo -l` lists the binary with no arguments, i.e. any arguments allowed."""
    # Commands in a listing are separated by ", "; a bare grant is the path followed by
    # a comma or the end of the line. Restricted grants have arguments after the path.
    pattern = re.compile(rf"(?:^|[\s:,]){re.escape(binary_path)}\s*(?:,|$)", re.MULTILINE)
    return bool(pattern.search(sudo_listing))


def binary_path_problem(binary_path: str) -> str | None:
    """Why the binary is unsafe to grant passwordless root, or None if it's fine.

    If the user (or anything running as them) can modify the binary or any directory
    on its path - including the target of a symlink - a NOPASSWD rule is root for them.
    """
    path = Path(binary_path)
    if not path.is_absolute():
        return f"{binary_path} is not an absolute path."
    if not path.is_file():
        return f"{binary_path} does not exist."
    resolved = path.resolve()
    # The file itself (following symlinks), and every directory on both the path as
    # given and the resolved path: replacing a symlink or a parent swaps the binary too.
    to_check = [resolved, *path.parents, *resolved.parents]
    for candidate in dict.fromkeys(to_check):
        info = os.stat(candidate)
        if info.st_uid != 0:
            return f"{candidate} is not owned by root. Fix: sudo chown root:root {candidate}"
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return f"{candidate} is writable by users other than root. Fix: sudo chmod go-w {candidate}"
    return None


def _sudoers_content(username: str, binary_path: str) -> str:
    commands = [f"{binary_path} {args}" for args in FIXED_ELEVATED_ARGS]
    commands.append(f"{binary_path} {LOCATION_ARGS_REGEX}")
    return (
        f'Defaults:{username} env_keep += "HOME"\n'
        f"{username} ALL=(root) NOPASSWD: " + ", \\\n    ".join(commands) + "\n"
    )


def run_setup(binary_path: str) -> tuple[bool, str]:
    problem = binary_path_problem(binary_path)
    if problem:
        return False, (
            f"Refusing to grant passwordless root to this CLI binary: {problem}\n\n"
            "Anything running as you could replace the binary and run it as root. Fix the "
            "ownership above, or point the CLI binary path (Advanced settings) at a root-owned install."
        )

    username = getpass.getuser()
    pkexec = shutil.which("pkexec")
    visudo = shutil.which("visudo")
    install = shutil.which("install")
    if not (pkexec and visudo and install):
        return False, "pkexec, visudo, or install not found on this system."

    content = _sudoers_content(username, binary_path)

    with tempfile.NamedTemporaryFile("w", suffix=".sudoers", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        check = subprocess.run([visudo, "-c", "-f", tmp_path], capture_output=True, text=True)
        if check.returncode != 0:
            return False, f"Generated sudoers content failed validation:\n{check.stderr or check.stdout}"

        result = subprocess.run(
            [pkexec, install, "-o", "root", "-g", "root", "-m", "0440", tmp_path, str(SUDOERS_PATH)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False, result.stderr.strip() or "Setup was cancelled."
        return True, "VPN permissions configured successfully."
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _sudo_can_run(binary_path: str) -> bool:
    # /etc/sudoers.d is typically 0750 root:root, so an unprivileged user can't even
    # stat a file inside it - Path.exists() silently returns False regardless of
    # whether the rule is actually there. Test functionally instead: does `sudo -n`
    # let us run the binary without a password?
    result = _run(["sudo", "-n", binary_path, "--version"])
    return result is not None and result.returncode == 0


def _run(cmd: list[str]) -> subprocess.CompletedProcess | None:
    env = {**os.environ, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5, env=env)
    except Exception:
        return None
