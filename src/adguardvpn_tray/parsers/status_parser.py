import re

from adguardvpn_tray.models.types import ConnectionState, ConnectionStatus
from adguardvpn_tray.parsers.ansi import strip_ansi

_CONNECTED_RE = re.compile(
    r"Connected to (?P<location>.+?) in (?P<mode>\S+) mode, running on (?P<interface>\S+)",
    re.IGNORECASE,
)
_DISCONNECTED_RE = re.compile(
    r"vpn is disconnected|vpn is not connected|not connected|no active connection",
    re.IGNORECASE,
)
_ACTIVE_UNAVAILABLE_RE = re.compile(r"vpn active, but status unavailable", re.IGNORECASE)
# Printed while the tunnel is up but the network is gone, e.g. during a Wi-Fi drop:
# "Network lost. Waiting to connect to ATLANTA in TUN mode, running on tun0"
_WAITING_FOR_NETWORK_RE = re.compile(
    r"Waiting to connect to (?P<location>.+?) in (?P<mode>\S+) mode, running on (?P<interface>\S+)",
    re.IGNORECASE,
)

STATUS_UNAVAILABLE_EXIT_CODE = 10


def parse_status(stdout: str, exit_code: int) -> ConnectionStatus:
    clean = strip_ansi(stdout)

    if exit_code == STATUS_UNAVAILABLE_EXIT_CODE or _ACTIVE_UNAVAILABLE_RE.search(clean):
        return ConnectionStatus(state=ConnectionState.CONNECTED, raw_text=clean)

    waiting_match = _WAITING_FOR_NETWORK_RE.search(clean)
    if waiting_match:
        return ConnectionStatus(
            state=ConnectionState.WAITING_FOR_NETWORK,
            location=waiting_match.group("location").strip(),
            mode=waiting_match.group("mode").strip(),
            interface=waiting_match.group("interface").strip(),
            raw_text=clean,
        )

    connected_match = _CONNECTED_RE.search(clean)
    if connected_match:
        return ConnectionStatus(
            state=ConnectionState.CONNECTED,
            location=connected_match.group("location").strip(),
            mode=connected_match.group("mode").strip(),
            interface=connected_match.group("interface").strip(),
            raw_text=clean,
        )

    if exit_code == 0 and _DISCONNECTED_RE.search(clean):
        return ConnectionStatus(state=ConnectionState.DISCONNECTED, raw_text=clean)

    return ConnectionStatus(state=ConnectionState.ERROR, raw_text=clean)
