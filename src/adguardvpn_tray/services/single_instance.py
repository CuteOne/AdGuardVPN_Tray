import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QLockFile

from adguardvpn_tray import constants


def lock_path() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(base) / f"{constants.APP_CONFIG_DIR}-{os.getuid()}.lock"


def acquire() -> QLockFile | None:
    """Lock held for the app's lifetime; None means another tray is already running.

    Two trays would each poll and each auto-reconnect on a drop, stacking
    concurrent `connect` calls. QLockFile records the PID, so a lock left by a
    crashed instance is detected as stale and taken over.
    """
    lock = QLockFile(str(lock_path()))
    lock.setStaleLockTime(0)  # stale only when the owning PID is gone, never by age
    if not lock.tryLock(0):
        return None
    return lock
