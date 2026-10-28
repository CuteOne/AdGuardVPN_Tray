# AdGuard VPN Tray

A KDE Plasma system tray application for managing [AdGuard VPN](https://adguard-vpn.com/) via the official `adguardvpn-cli` binary — connect/disconnect, browse locations, log in, and configure autostart, all from the tray icon.

> **Unofficial.** This is an independent community project. It is not affiliated with, endorsed by, or supported by AdGuard. "AdGuard" and the AdGuard logo are trademarks of their owner; the tray only drives the `adguardvpn-cli` you install yourself.

## One-time setup

### 1. Install dependencies

```bash
sudo pacman -S pyside6 python-pexpect
```

You also need AdGuard's own command-line client, `adguardvpn-cli`, installed from [AdGuard VPN](https://adguard-vpn.com/) (see their Linux CLI install instructions). The tray expects it at `/usr/local/bin/adguardvpn-cli`; a different path can be set in **Advanced settings**.

### 2. Grant VPN permissions

`adguardvpn-cli` requires real root privileges to create its TUN interface (a Linux capability grant alone is not enough — the binary explicitly checks for `EUID == 0`). **The app handles this for you**: on first launch, if it detects the permission isn't set up yet, it shows a dialog offering to configure it via a single native system authentication prompt (`pkexec`) — no manual file editing needed. You can also trigger this any time from **Settings → Set up VPN permissions…**.

Under the hood, this writes a sudoers drop-in that allows *only* the exact commands the tray runs as root, not `adguardvpn-cli` with any arguments. It's validated with `visudo -c` before being installed, so a malformed rule can never reach `/etc/sudoers.d/`:

```
Defaults:youruser env_keep += "HOME"
youruser ALL=(root) NOPASSWD: /usr/local/bin/adguardvpn-cli --version, \
    /usr/local/bin/adguardvpn-cli connect -y, \
    /usr/local/bin/adguardvpn-cli connect -y -f, \
    /usr/local/bin/adguardvpn-cli disconnect, \
    /usr/local/bin/adguardvpn-cli update -y, \
    /usr/local/bin/adguardvpn-cli ^connect -y -l [^ -][^ ]*( [^ -][^ ]*)*$
```

The last line allows connecting to a named location. No word of the location may start with `-`, so extra options (such as `--pid-file`, which writes a file as root) can't be appended. The `^…$` pattern needs sudo 1.9.10 or newer. The `env_keep` line is scoped to just `HOME` (so root sees your logged-in AdGuard session instead of its own separate one) rather than granting a blanket environment-preservation right.

If you set up an earlier version of the tray, it detects the older rule that allowed any arguments and offers to replace it.

**Before granting it, the tray checks that only root can modify the CLI binary**: the file, every directory above it, and the target of the `/usr/local/bin` symlink. If your user can replace the binary, a passwordless rule would be root for anything running as you, so setup refuses and shows the fix. AdGuard's installer can leave its install directory owned by your user; if so:

```bash
sudo chown root:root /opt/adguardvpn_cli
```

The tray re-checks at every start and warns if an AdGuard update changes the ownership back.

#### What this grant still allows

`adguardvpn-cli` itself requires root, so some trust is unavoidable. With this rule, any program running as your user can connect, disconnect or update the VPN without a password. And because root keeps your `HOME`, the root-run CLI reads its configuration from your home directory, which your user can edit. If that matters for your threat model, skip the automatic setup and run the VPN commands with `sudo` yourself.

<details>
<summary>Manual setup (if you'd rather not use pkexec, or are troubleshooting)</summary>

```bash
sudo visudo -f /etc/sudoers.d/adguardvpn-tray
```

Paste the rule shown above, replace `youruser` with your username (`echo $USER`), then save. `visudo` refuses to save a rule with a syntax error.

Verify it worked:

```bash
sudo -n /usr/local/bin/adguardvpn-cli --version
```

If that prints a version without asking for a password, you're set.
</details>

## Running

From a checkout of this repository:

```bash
PYTHONPATH=src python -m adguardvpn_tray
```

Or, after installing the package (`pip install -e .` in a venv, or via a future AUR package), run `adguardvpn-tray`.

**Right-click** the tray icon for the full menu (left-click is intentionally inert — a stray click can't accidentally drop your connection). Enable **Settings → Autostart on login** to launch automatically with your session (writes a standard `~/.config/autostart/adguardvpn-tray.desktop` entry — no systemd unit needed).

The first menu line is the current status, with the cause if there's an error. **Status details…** below it opens a live view of the connection, the last check, the last error, your public IP and account, with a **Copy** button for bug reports (it leaves out your account email). The full error history is in **Advanced settings → Diagnostics**.

**Settings** also includes:
- **Default connect target** — Fastest or Last selected; controls what clicking Connect does, and what auto-connect/auto-reconnect use.
- **Connect automatically when the tray starts** (off by default) — if the VPN is disconnected when the app starts, connect automatically. Combined with autostart, this connects at every login.
- **Disconnect VPN when quitting** (on by default) — quitting the tray (from the menu, or systemd stopping it at logout) disconnects the VPN and confirms it went down. If it can't, you're told instead of the tray silently disappearing.
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

- Only `connect`, `disconnect` and `update` run elevated (via the sudoers rule above); `status`, `license`, `list-locations`, and `config show` run as your normal user.
- `adguardvpn-cli` backgrounds its own tunnel process (as root) that is independent of the tray app's lifetime — that's why **Disconnect VPN when quitting** exists. If the tray starts and finds a connection left over from an earlier session, it shows it and offers to disconnect it rather than starting a second one.
- Disconnect is only reported as successful once `adguardvpn-cli status` confirms the VPN is down.
- Site-exclusion (split tunneling) management is not yet implemented — see the Advanced Settings dialog's placeholder tab.
- The in-app login flow drives `adguardvpn-cli login` through a pseudo-terminal and extracts the browser sign-in link automatically. It hasn't been exercised against a real logout/login cycle during development (doing so would have logged out the developer's real account) — if it doesn't behave as expected, the dialog always shows the raw sign-in link with a **Copy Link** button as a manual fallback.
