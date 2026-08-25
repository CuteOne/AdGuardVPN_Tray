# AdGuard VPN Tray

A KDE Plasma system tray application for managing [AdGuard VPN](https://adguard-vpn.com/) via the official `adguardvpn-cli` binary — connect/disconnect, browse locations, log in, and configure autostart, all from the tray icon.

## One-time setup

### 1. Install dependencies

```bash
sudo pacman -S pyside6 python-pexpect
```

### 2. Grant VPN permissions

`adguardvpn-cli` requires real root privileges to create its TUN interface (a Linux capability grant alone is not enough — the binary explicitly checks for `EUID == 0`). **The app handles this for you**: on first launch, if it detects the permission isn't set up yet, it shows a dialog offering to configure it via a single native system authentication prompt (`pkexec`) — no manual file editing needed. You can also trigger this any time from **Settings → Set up VPN permissions…**.

Under the hood, this writes a sudoers drop-in scoped to *only* `/usr/local/bin/adguardvpn-cli` (validated with `visudo -c` before being installed, so a malformed rule can never reach `/etc/sudoers.d/`):

```
Defaults:youruser env_keep += "HOME"
youruser ALL=(root) NOPASSWD: /usr/local/bin/adguardvpn-cli
```

The `env_keep` line is scoped to just `HOME` (so root sees your logged-in AdGuard session instead of its own separate one) rather than granting a blanket environment-preservation right.

<details>
<summary>Manual setup (if you'd rather not use pkexec, or are troubleshooting)</summary>

```bash
printf 'Defaults:%s env_keep += "HOME"\n%s ALL=(root) NOPASSWD: /usr/local/bin/adguardvpn-cli\n' "$USER" "$USER" | sudo EDITOR='tee' visudo -f /etc/sudoers.d/adguardvpn-tray
sudo chmod 0440 /etc/sudoers.d/adguardvpn-tray
```

Verify it worked:

```bash
sudo -n /usr/local/bin/adguardvpn-cli status
```

If that prints a status line without asking for a password, you're set.
</details>

## Running

```bash
python -m adguardvpn_tray
```

Or, after installing the package (`pip install -e .` in a venv, or via a future AUR package), run `adguardvpn-tray`.

**Right-click** the tray icon for the full menu (left-click is intentionally inert — a stray click can't accidentally drop your connection). Enable **Settings → Autostart on login** to launch automatically with your session (writes a standard `~/.config/autostart/adguardvpn-tray.desktop` entry — no systemd unit needed).

**Settings** also includes:
- **Default connect target** — Fastest or Last selected; controls what clicking Connect does, and what auto-connect/auto-reconnect use.
- **Auto-connect on launch** (on by default) — if the VPN is disconnected when the app starts, connect automatically.
- **Auto-reconnect if dropped** (on by default) — if the connection drops unexpectedly (not from you clicking Disconnect), the app retries up to 3 times with a short delay before giving up and notifying you.
- **Verify IP after connecting** (on by default) — after connecting, confirms your public IP actually changed before trusting "Connected", retrying a few times to tolerate route-settling delay.
- **Advanced settings…** — refresh interval, CLI binary path override, a read-only CLI config viewer, and a **Diagnostics** tab showing a local error log (view/clear) for troubleshooting.

**Locations** supports **Manage Favorites…** — pin frequently-used cities to a **★ Favorites** section at the top of the list, above the continent groupings.

## Packaging (Arch / CachyOS)

A `PKGBUILD` is provided under [`packaging/`](packaging/). Once this repo has a real GitHub URL and a tagged release, update the `url`/`source` line in `packaging/PKGBUILD` accordingly, then:

```bash
cd packaging
makepkg -si
```

This builds and installs `adguardvpn-tray` as a proper package (binary on `PATH`, `.desktop` entry in your application launcher), pulling `pyside6` and `python-pexpect` in as real pacman dependencies.

## Notes

- Only `connect`/`disconnect` run elevated (via the sudoers rule above); `status`, `license`, `list-locations`, and `config show` run as your normal user.
- Quitting the tray app does **not** disconnect the VPN — `adguardvpn-cli` backgrounds its own tunnel process independent of the tray app's lifetime.
- Site-exclusion (split tunneling) management is not yet implemented — see the Advanced Settings dialog's placeholder tab.
- The in-app login flow drives `adguardvpn-cli login` through a pseudo-terminal and extracts the browser sign-in link automatically. It hasn't been exercised against a real logout/login cycle during development (doing so would have logged out the developer's real account) — if it doesn't behave as expected, the dialog always shows the raw sign-in link with a **Copy Link** button as a manual fallback.
