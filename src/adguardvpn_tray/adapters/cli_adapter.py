import os
import shutil
import subprocess

from adguardvpn_tray import constants
from adguardvpn_tray.models.types import CliResult

_LOCALE_ENV = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def _as_text(output: str | bytes | None) -> str:
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output or ""


class CliAdapter:
    """Thin wrapper around the adguardvpn-cli subprocess. No parsing here."""

    def __init__(self, binary_path: str | None = None):
        self.binary_path = binary_path or constants.DEFAULT_BINARY_PATH

    def status(self, timeout: int = constants.TIMEOUT_STATUS_S) -> CliResult:
        return self._run(["status"], timeout=timeout)

    def license(self) -> CliResult:
        return self._run(["license"], timeout=constants.TIMEOUT_LICENSE_S)

    def config_show(self) -> CliResult:
        return self._run(["config", "show"], timeout=constants.TIMEOUT_CONFIG_S)

    def list_locations(self, count: int | None = None) -> CliResult:
        args = ["list-locations"]
        if count is not None:
            args.append(str(count))
        return self._run(args, timeout=constants.TIMEOUT_LOCATIONS_S)

    def connect(self, location: str | None = None, fastest: bool = False) -> CliResult:
        args = ["connect", "-y"]
        if fastest:
            args.append("-f")
        elif location:
            args.extend(["-l", location])
        return self._run(args, timeout=constants.TIMEOUT_CONNECT_S, needs_root=True)

    def logout(self) -> CliResult:
        return self._run(["logout"], timeout=constants.TIMEOUT_LICENSE_S)

    def disconnect(self, timeout: int = constants.TIMEOUT_DISCONNECT_S) -> CliResult:
        return self._run(["disconnect"], timeout=timeout, needs_root=True)

    def check_update(self) -> CliResult:
        return self._run(["check-update"], timeout=constants.TIMEOUT_UPDATE_S)

    def update(self) -> CliResult:
        return self._run(["update", "-y"], timeout=constants.TIMEOUT_UPDATE_S, needs_root=True)

    # Exclusions live in the user's config and need no root; a change to the active
    # list is applied to a running tunnel straight away by the CLI itself.
    def exclusions_show(self, mode: str) -> CliResult:
        return self._run(["site-exclusions", "show", "--for-mode", mode], timeout=constants.TIMEOUT_CONFIG_S)

    def exclusions_add(self, entries: list[str], mode: str) -> CliResult:
        return self._run(
            ["site-exclusions", "add", *entries, "--for-mode", mode], timeout=constants.TIMEOUT_EXCLUSIONS_APPLY_S
        )

    def exclusions_remove(self, entries: list[str], mode: str) -> CliResult:
        return self._run(
            ["site-exclusions", "remove", *entries, "--for-mode", mode], timeout=constants.TIMEOUT_EXCLUSIONS_APPLY_S
        )

    def exclusion_mode(self) -> CliResult:
        return self._run(["site-exclusions", "mode"], timeout=constants.TIMEOUT_CONFIG_S)

    def set_exclusion_mode(self, mode: str) -> CliResult:
        return self._run(["site-exclusions", "mode", mode], timeout=constants.TIMEOUT_EXCLUSIONS_APPLY_S)

    def _run(self, args: list[str], *, timeout: int, needs_root: bool = False) -> CliResult:
        resolved = self.binary_path if os.sep in self.binary_path else shutil.which(self.binary_path)
        if not resolved or not os.access(resolved, os.X_OK):
            return CliResult(stdout="", stderr="binary not found", returncode=127, binary_missing=True)

        env = {**os.environ, **_LOCALE_ENV}
        if needs_root:
            # HOME reaches the elevated process via the sudoers "env_keep" Defaults
            # entry (see privilege_setup.py), not via -E, to avoid granting a blanket
            # SETENV right that would let a caller pass arbitrary env vars to root.
            cmd = ["sudo", "-n", self.binary_path, *args]
        else:
            cmd = [self.binary_path, *args]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            # TimeoutExpired carries partial output as bytes even with text=True.
            return CliResult(
                stdout=_as_text(exc.stdout),
                stderr=_as_text(exc.stderr),
                returncode=-1,
                timed_out=True,
            )
        except FileNotFoundError:
            return CliResult(stdout="", stderr="binary not found", returncode=127, binary_missing=True)

        return CliResult(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)
