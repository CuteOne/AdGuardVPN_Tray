import getpass
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

SUDOERS_PATH = Path("/etc/sudoers.d/adguardvpn-tray")


def is_configured(binary_path: str) -> bool:
    # /etc/sudoers.d is typically 0750 root:root, so an unprivileged user can't even
    # stat a file inside it - Path.exists() silently returns False regardless of
    # whether the rule is actually there. Test functionally instead: does `sudo -n`
    # let us run the binary without a password?
    env = {**os.environ, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    try:
        result = subprocess.run(
            ["sudo", "-n", binary_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
    except Exception:
        return False
    return result.returncode == 0


def _sudoers_content(username: str, binary_path: str) -> str:
    return (
        f'Defaults:{username} env_keep += "HOME"\n'
        f"{username} ALL=(root) NOPASSWD: {binary_path}\n"
    )


def run_setup(binary_path: str) -> tuple[bool, str]:
    username = getpass.getuser()
    pkexec = shutil.which("pkexec")
    visudo = shutil.which("visudo")
    install = shutil.which("install")
    if not (pkexec and visudo and install):
        return False, "pkexec, visudo, or install not found on this system."

    content = _sudoers_content(username, binary_path)

    with tempfile.NamedTemporaryFile("w", suffix=".sudoers", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        check = subprocess.run([visudo, "-c", "-f", tmp_path], capture_output=True, text=True)
        if check.returncode != 0:
            return False, f"Generated sudoers content failed validation:\n{check.stderr or check.stdout}"

        result = subprocess.run(
            [pkexec, install, "-o", "root", "-g", "root", "-m", "0440", tmp_path, str(SUDOERS_PATH)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False, result.stderr.strip() or "Setup was cancelled."
        return True, "VPN permissions configured successfully."
    finally:
        Path(tmp_path).unlink(missing_ok=True)
