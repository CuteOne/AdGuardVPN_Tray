from dataclasses import dataclass
from enum import Enum, auto


class ConnectionState(Enum):
    UNKNOWN = auto()
    CONNECTED = auto()
    WAITING_FOR_NETWORK = auto()  # tunnel is up but the network dropped; the CLI retries on its own
    CONNECTING = auto()
    DISCONNECTED = auto()
    DISCONNECTING = auto()
    ERROR = auto()
    NOT_LOGGED_IN = auto()


# States in which a tunnel exists, so Disconnect is the meaningful action and a new
# connect would stack on top of it.
TUNNEL_UP_STATES = frozenset({ConnectionState.CONNECTED, ConnectionState.WAITING_FOR_NETWORK})


@dataclass
class ConnectionStatus:
    state: ConnectionState
    location: str | None = None
    mode: str | None = None
    interface: str | None = None
    raw_text: str = ""


@dataclass
class Location:
    iso: str
    country: str
    city: str
    ping_ms: int


@dataclass
class LicenseInfo:
    logged_in: bool
    email: str | None = None
    tier: str | None = None
    device_limit: str | None = None
    renewal_date: str | None = None


@dataclass
class VpnConfig:
    values: dict[str, str]


@dataclass
class CliResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False
    binary_missing: bool = False
