import shutil
from pathlib import Path

DEFAULT_BINARY_PATH = shutil.which("adguardvpn-cli") or "/usr/local/bin/adguardvpn-cli"

TIMEOUT_STATUS_S = 10
TIMEOUT_LICENSE_S = 10
TIMEOUT_CONFIG_S = 10
TIMEOUT_LOCATIONS_S = 15
TIMEOUT_CONNECT_S = 45
TIMEOUT_DISCONNECT_S = 30
TIMEOUT_UPDATE_S = 120
TIMEOUT_EXCLUSIONS_APPLY_S = 30  # includes the CLI re-applying settings to a live tunnel

# A disconnect is only trusted once `status` confirms the VPN is down.
DISCONNECT_VERIFY_ATTEMPTS = 5
DISCONNECT_VERIFY_DELAY_S = 1

# Disconnect-on-quit must never hang shutdown (systemd SIGKILLs a stuck unit at logout).
# Worst case: wait for workers + status + disconnect + 2 verify statuses + 1 delay ≈ 20 s.
TIMEOUT_QUIT_STATUS_S = 3
TIMEOUT_QUIT_DISCONNECT_S = 8
QUIT_DISCONNECT_VERIFY_ATTEMPTS = 2
QUIT_WAIT_FOR_WORKERS_MS = 2000
SIGNAL_CHECK_INTERVAL_MS = 500

POLL_INTERVAL_S = 6
LICENSE_POLL_EVERY_N_TICKS = 6
FORCE_REPOLL_MIN_MS = 1500
FORCE_REPOLL_MAX_MS = 2500
OPTIMISTIC_STATE_TIMEOUT_S = 15

LOCATIONS_CACHE_TTL_S = 300

LOGIN_TIMEOUT_S = 20 * 60

AUTO_RECONNECT_MAX_ATTEMPTS = 3
AUTO_RECONNECT_RETRY_DELAY_MS = 4000

IP_VERIFY_SETTLE_DELAY_MS = 3000
IP_VERIFY_MAX_ATTEMPTS = 4

GAME_SCAN_INTERVAL_S = 5

APP_CONFIG_DIR ="adguardvpn-tray"
AUTOSTART_DESKTOP_FILENAME = "adguardvpn-tray.desktop"

ICONS_DIR = Path(__file__).resolve().parent / "resources" / "icons"
# The AdGuard shield - used for the app launcher and autostart entries.
APP_ICON_PATH = ICONS_DIR / "connected.png"

UPDATE_CHECK_INTERVAL_S = 24 * 60 * 60
