from dataclasses import dataclass
from datetime import datetime

from adguardvpn_tray.models.types import ConnectionState, ConnectionStatus, LicenseInfo
from adguardvpn_tray.parsers.ansi import strip_ansi

SHORT_REASON_MAX_CHARS = 60
DIAGNOSTICS_NOTE = (
    "This shows the current state. For a history of past errors, see the "
    "Diagnostics tab (Settings → Advanced settings… → Diagnostics)."
)
# Appended to error notifications so they point somewhere the user can look.
DETAILS_HINT = "Open Status details in the tray menu for more."


@dataclass
class ErrorRecord:
    at: datetime
    context: str
    message: str


@dataclass
class StatusSnapshot:
    summary: str  # the short status line shown in the menu
    status: ConnectionStatus
    refresh_interval_s: int
    binary_path: str
    last_check_at: datetime | None = None
    last_error: ErrorRecord | None = None
    public_ip: str | None = None
    public_ip_at: datetime | None = None
    ip_checks_enabled: bool = True
    license: LicenseInfo | None = None


def short_reason(text: str, max_chars: int = SHORT_REASON_MAX_CHARS) -> str:
    """First non-empty line of an error, trimmed to fit a menu item."""
    lines = [line.strip() for line in strip_ansi(text or "").splitlines()]
    reason = next((line for line in lines if line), "unknown error")
    if len(reason) > max_chars:
        reason = reason[: max_chars - 1].rstrip() + "…"
    return reason


def _clock(at: datetime) -> str:
    return at.strftime("%H:%M:%S")


def detail_rows(snapshot: StatusSnapshot, include_email: bool = True) -> list[tuple[str, str]]:
    # include_email=False for copied text, which tends to end up in public bug reports.
    status = snapshot.status
    rows = [("Status", snapshot.summary)]

    if status.state == ConnectionState.CONNECTED:
        rows.append(("Location", status.location or "Unknown"))
        rows.append(("Mode", status.mode or "Unknown"))
        rows.append(("Interface", status.interface or "Unknown"))

    if snapshot.last_check_at is None:
        last_check = "Not checked yet"
    else:
        outcome = "couldn't read status" if status.state == ConnectionState.ERROR else "OK"
        last_check = f"{_clock(snapshot.last_check_at)} — {outcome}"
    rows.append(("Last check", f"{last_check} (checks every {snapshot.refresh_interval_s} s)"))

    error = snapshot.last_error
    rows.append(("Last error", f"{_clock(error.at)} — {error.message.strip()}" if error else "None since the tray started"))

    if not snapshot.ip_checks_enabled:
        public_ip = "IP checks are off"
    elif snapshot.public_ip and snapshot.public_ip_at:
        public_ip = f"{snapshot.public_ip} (checked {_clock(snapshot.public_ip_at)})"
    else:
        public_ip = "Not checked yet"
    rows.append(("Public IP", public_ip))

    info = snapshot.license
    if info is None:
        account = "Checking…"
    elif info.logged_in:
        email = info.email if include_email else None
        account = " · ".join(part for part in (email, info.tier and f"{info.tier} tier") if part) or "Logged in"
    else:
        account = "Not logged in"
    rows.append(("Account", account))

    rows.append(("CLI", snapshot.binary_path))
    return rows


def as_text(rows: list[tuple[str, str]]) -> str:
    """Plain-text form for the Copy button - pasteable into a bug report."""
    return "AdGuard VPN Tray status\n" + "\n".join(f"{label}: {value}" for label, value in rows) + "\n"
