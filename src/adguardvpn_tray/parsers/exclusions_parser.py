import re

from adguardvpn_tray.parsers.ansi import strip_ansi

EXCLUSION_MODES = ("general", "selective")

_MODE_RE = re.compile(r"mode is\s+(GENERAL|SELECTIVE)", re.IGNORECASE)
_INVALID_RE = re.compile(r"^Skipped invalid exclusion:\s*(?P<entry>.+)$")
_SPLIT_RE = re.compile(r"[\s,]+")


def parse_exclusions(stdout: str) -> list[str]:
    entries = []
    for line in strip_ansi(stdout).splitlines():
        line = line.strip()
        if not line or line.startswith("Exclusions for"):
            continue
        entries.append(line)
    return entries


def parse_exclusion_mode(stdout: str) -> str | None:
    match = _MODE_RE.search(strip_ansi(stdout))
    return match.group(1).lower() if match else None


def parse_skipped_entries(stdout: str) -> list[str]:
    skipped = []
    for line in strip_ansi(stdout).splitlines():
        match = _INVALID_RE.match(line.strip())
        if match:
            skipped.append(match.group("entry").strip())
    return skipped


def split_entries(text: str) -> list[str]:
    """Split user input on whitespace and commas, so a pasted list adds one entry per item."""
    return [part for part in _SPLIT_RE.split(text.strip()) if part]


def entry_problem(entry: str) -> str | None:
    # The CLI splits every argument on spaces itself and reads a leading "-" as an
    # option, so both have to be stopped here rather than left for it to reject.
    if not entry:
        return "empty entry"
    if any(ch.isspace() for ch in entry):
        return f"{entry!r} contains a space"
    if entry.startswith("-"):
        return f"{entry!r} can't start with '-'"
    return None
