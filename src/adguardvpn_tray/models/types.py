from dataclasses import dataclass
from enum import Enum, auto


class ConnectionState(Enum):
    UNKNOWN = auto()
    CONNECTED = auto()
    CONNECTING = auto()
    DISCONNECTED = auto()
    DISCONNECTING = auto()
    ERROR = auto()
    NOT_LOGGED_IN = auto()


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
