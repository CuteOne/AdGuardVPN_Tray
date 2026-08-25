import re

from adguardvpn_tray.models.types import LicenseInfo
from adguardvpn_tray.parsers.ansi import strip_ansi

_EMAIL_RE = re.compile(r"Logged in as ([^\s]+)", re.IGNORECASE)
_TIER_RE = re.compile(r"using the (\S+) version", re.IGNORECASE)
_DEVICE_LIMIT_RE = re.compile(r"Up to (\d+ devices[^\n]*)", re.IGNORECASE)
_RENEWAL_RE = re.compile(r"renewed on (\d{4}-\d{2}-\d{2})", re.IGNORECASE)
_NOT_LOGGED_IN_RE = re.compile(r"not logged in", re.IGNORECASE)


def parse_license(stdout: str) -> LicenseInfo:
    clean = strip_ansi(stdout)

    email_match = _EMAIL_RE.search(clean)
    if not email_match or _NOT_LOGGED_IN_RE.search(clean):
        return LicenseInfo(logged_in=False)

    tier_match = _TIER_RE.search(clean)
    device_match = _DEVICE_LIMIT_RE.search(clean)
    renewal_match = _RENEWAL_RE.search(clean)

    return LicenseInfo(
        logged_in=True,
        email=email_match.group(1),
        tier=tier_match.group(1) if tier_match else None,
        device_limit=device_match.group(1) if device_match else None,
        renewal_date=renewal_match.group(1) if renewal_match else None,
    )
