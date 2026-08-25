import os
from datetime import datetime, timezone
from pathlib import Path

from adguardvpn_tray import constants

_MAX_ENTRIES = 200
_SEPARATOR = "-" * 40 + "\n"


def log_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / constants.APP_CONFIG_DIR / "errors.log"


def report_error(context: str, detail: str) -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    entry = f"{timestamp} [{context}]\n{detail.strip()}\n"

    blocks = []
    if path.exists():
        blocks = [b for b in path.read_text().split(_SEPARATOR) if b.strip()]
    blocks.append(entry)
    blocks = blocks[-_MAX_ENTRIES:]
    path.write_text(_SEPARATOR.join(blocks) + _SEPARATOR)


def read_log() -> str:
    path = log_path()
    return path.read_text() if path.exists() else ""


def clear_log() -> None:
    path = log_path()
    if path.exists():
        path.unlink()
