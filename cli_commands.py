# cli_commands.py
import subprocess
import logging

SUDO_CMD = "/usr/bin/sudo"
VPN_CLI_PATH = "/var/opt/adguardvpn_cli/adguardvpn-cli"

def run_command(command: str, command_str: str) -> tuple[str, str, int]:
    """
    Run a shell command and return the output, error, and exit code.
    """
    try:
        logging.info("Running command: %s", command_str)
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        logging.debug("Return code: %d", result.returncode)
        if result.returncode != 0:
            logging.error("Command error: %s", result.stderr.strip())
        logging.debug("Command Result: %s", result.stdout.strip())
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        logging.exception("Exception while running command.")
        return "", str(e), 1

# You can also add helper functions that build specific command strings here.
