import re

from adguardvpn_tray.models.types import Location
from adguardvpn_tray.parsers.ansi import strip_ansi

_SPLIT_RE = re.compile(r"\s{2,}")
_HEADER_TOKENS = {"ISO", "COUNTRY", "CITY", "PING", "ESTIMATE"}
_FUZZY_RE = re.compile(
    r"^(?P<iso>[A-Z]{2})\s+(?P<rest>.+?)\s+(?P<ping>\d+)\s*$"
)


def parse_locations(stdout: str) -> list[Location]:
    clean = strip_ansi(stdout)
    locations: list[Location] = []

    for line in clean.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue

        fields = [f for f in _SPLIT_RE.split(line.strip()) if f]
        if fields and set(f.upper() for f in fields) & _HEADER_TOKENS:
            continue

        location = _parse_split_fields(fields) or _parse_fuzzy(line)
        if location is not None:
            locations.append(location)

    return locations


def _parse_split_fields(fields: list[str]) -> Location | None:
    if len(fields) < 4:
        return None
    iso, country, city, ping_field = fields[0], fields[1], fields[2], fields[3]
    if len(iso) != 2 or not iso.isalpha():
        return None
    ping_match = re.search(r"\d+", ping_field)
    if not ping_match:
        return None
    return Location(iso=iso.upper(), country=country, city=city, ping_ms=int(ping_match.group()))


def _parse_fuzzy(line: str) -> Location | None:
    match = _FUZZY_RE.match(line.strip())
    if not match:
        return None
    rest = match.group("rest").strip()
    parts = re.split(r"\s{2,}|\t", rest)
    parts = [p for p in parts if p]
    country = parts[0] if parts else rest
    city = parts[1] if len(parts) > 1 else rest
    return Location(
        iso=match.group("iso"),
        country=country,
        city=city,
        ping_ms=int(match.group("ping")),
    )
