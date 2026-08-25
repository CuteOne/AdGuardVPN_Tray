from pathlib import Path

from PySide6.QtGui import QIcon

from adguardvpn_tray.models.types import ConnectionState

_RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"

_STATE_TO_FILE = {
    ConnectionState.CONNECTED: "connected.png",
    ConnectionState.DISCONNECTED: "disconnected.png",
    ConnectionState.ERROR: "disconnected.png",
    ConnectionState.NOT_LOGGED_IN: "disconnected.png",
    ConnectionState.CONNECTING: "unknown.png",
    ConnectionState.DISCONNECTING: "unknown.png",
    ConnectionState.UNKNOWN: "unknown.png",
}

_cache: dict[str, QIcon] = {}


def icon_for_state(state: ConnectionState) -> QIcon:
    filename = _STATE_TO_FILE[state]
    if filename not in _cache:
        _cache[filename] = QIcon(str(_RESOURCES_DIR / filename))
    return _cache[filename]
