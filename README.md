# AdGuard VPN Tray

A KDE Plasma system tray application for managing [AdGuard VPN](https://adguard-vpn.com/) via the official `adguardvpn-cli` binary — connect/disconnect, browse locations, log in, and configure autostart, all from the tray icon.

## One-time setup

### 1. Install dependencies

```bash
sudo pacman -S pyside6 python-pexpect
```

### 2. Allow the app to manage the VPN tunnel without a password prompt every time

`adguardvpn-cli` requires real root privileges to create its TUN interface (a Linux capability grant alone is not enough — the binary explicitly checks for `EUID == 0`). To let the tray app call `connect`/`disconnect` seamlessly, add a sudoers rule scoped to exactly this binary:

```bash
echo 'YOUR_USERNAME ALL=(root) NOPASSWD:SETENV: /usr/local/bin/adguardvpn-cli' | sudo EDITOR='tee -a' visudo -f /etc/sudoers.d/adguardvpn-tray
sudo chmod 0440 /etc/sudoers.d/adguardvpn-tray
```

This grants your user passwordless root execution of *only* `/usr/local/bin/adguardvpn-cli` (the `SETENV` tag is required so the app can preserve `HOME` when elevating — otherwise root sees its own separate, logged-out AdGuard session instead of yours). Verify it worked:

```bash
sudo -n -E /usr/local/bin/adguardvpn-cli status
```

If that prints a status line without asking for a password, you're set.

## Running

```bash
python -m adguardvpn_tray
```

Or, after installing the package (`pip install -e .` in a venv, or via a future AUR package), run `adguardvpn-tray`.

Enable **Settings → Autostart on login** from the tray menu to launch automatically with your session (writes a standard `~/.config/autostart/adguardvpn-tray.desktop` entry — no systemd unit needed).

**Settings** also includes:
- **Default connect target** — Fastest or Last selected; controls what clicking Connect does, and what auto-connect/auto-reconnect use.
- **Auto-connect on launch** (on by default) — if the VPN is disconnected when the app starts, connect automatically.
- **Auto-reconnect if dropped** (on by default) — if the connection drops unexpectedly (not from you clicking Disconnect), the app retries up to 3 times with a short delay before giving up and notifying you.

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
