import os
import shutil
import subprocess

from adguardvpn_tray import constants
from adguardvpn_tray.models.types import CliResult

_LOCALE_ENV = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


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
            return CliResult(
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                returncode=-1,
                timed_out=True,
            )
        except FileNotFoundError:
            return CliResult(stdout="", stderr="binary not found", returncode=127, binary_missing=True)

        return CliResult(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)
