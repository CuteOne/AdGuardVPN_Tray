import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from adguardvpn_tray import constants


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / constants.APP_CONFIG_DIR / "config.json"


@dataclass
class AppConfig:
    refresh_interval_s: int = constants.POLL_INTERVAL_S
    autostart_enabled: bool = False
    default_connect_target: str = "fastest"  # "fastest" | "last"
    auto_connect_on_launch: bool = True
    auto_reconnect_on_drop: bool = True
    verify_ip_on_connect: bool = True
    binary_path_override: str | None = None
    show_notifications: bool = True
    last_update_check_iso: str | None = None
    favorite_locations: list[str] = field(default_factory=list)

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls) -> "AppConfig":
        path = config_path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return cls()
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in raw.items() if k in known}
        return cls(**filtered)
