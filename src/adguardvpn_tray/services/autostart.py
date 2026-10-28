import os
import sys
from pathlib import Path

from adguardvpn_tray import constants

_DESKTOP_ENTRY_TEMPLATE = """[Desktop Entry]
Type=Application
Name=AdGuard VPN Tray
Comment=System tray manager for AdGuard VPN
Exec={exec_cmd}
Icon={icon}
Terminal=false
X-GNOME-Autostart-enabled=true
Hidden=false
"""


def autostart_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart" / constants.AUTOSTART_DESKTOP_FILENAME


def _exec_command() -> str:
    src_dir = Path(__file__).resolve().parents[2]
    return f"env PYTHONPATH={src_dir} {sys.executable} -m adguardvpn_tray"


def is_enabled() -> bool:
    return autostart_path().exists()


def enable() -> None:
    path = autostart_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_DESKTOP_ENTRY_TEMPLATE.format(exec_cmd=_exec_command(), icon=constants.APP_ICON_PATH))
    # Not executable: systemd-xdg-autostart-generator warns about executable entries.
    path.chmod(0o644)


def disable() -> None:
    path = autostart_path()
    if path.exists():
        path.unlink()


def set_enabled(enabled: bool) -> None:
    enable() if enabled else disable()
