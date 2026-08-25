import re

from adguardvpn_tray.models.types import VpnConfig
from adguardvpn_tray.parsers.ansi import strip_ansi

_LINE_RE = re.compile(r"^\s*([^:\n]+):\s*(.*)$")
_DEFAULT_WRAP_RE = re.compile(r"^Default \((.*)\)$")


def unwrap_default(value: str) -> str:
    match = _DEFAULT_WRAP_RE.match(value.strip())
    if not match:
        return value.strip()
    inner = match.group(1).strip()
    return inner if inner and " " not in inner else ""


def parse_config_show(stdout: str) -> VpnConfig:
    clean = strip_ansi(stdout)
    values: dict[str, str] = {}

    for line in clean.splitlines():
        if ":" not in line or line.strip().endswith(":"):
            continue
        match = _LINE_RE.match(line)
        if not match:
            continue
        key, value = match.group(1).strip(), match.group(2).strip()
        values[key] = value

    return VpnConfig(values=values)
