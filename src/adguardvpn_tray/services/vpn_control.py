import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable

from adguardvpn_tray import constants
from adguardvpn_tray.adapters.cli_adapter import CliAdapter
from adguardvpn_tray.config.app_config import AppConfig
from adguardvpn_tray.models.types import CliResult, ConnectionState, ConnectionStatus
from adguardvpn_tray.parsers.ansi import strip_ansi
from adguardvpn_tray.parsers.status_parser import parse_status

_CLI_MISSING = "adguardvpn-cli not found"


@dataclass
class DisconnectOutcome:
    verified: bool  # True only when `status` confirmed the VPN is down
    status: ConnectionStatus
    message: str = ""


class StartupAction(Enum):
    UNDECIDED = auto()  # status isn't conclusive yet - wait for the next poll
    NONE = auto()
    CONNECT = auto()
    ADOPT = auto()  # already connected and the user wants the VPN on at launch: keep it
    OFFER_DISCONNECT = auto()  # already connected, left over from an earlier session


def startup_action(status: ConnectionStatus, auto_connect_on_launch: bool) -> StartupAction:
    # Only a definite CONNECTED/DISCONNECTED settles it - an ERROR (e.g. a status
    # timeout) must not be read as "disconnected", or we'd stack a second connect
    # on top of a tunnel that is still up.
    if status.state == ConnectionState.CONNECTED:
        return StartupAction.ADOPT if auto_connect_on_launch else StartupAction.OFFER_DISCONNECT
    if status.state == ConnectionState.DISCONNECTED:
        return StartupAction.CONNECT if auto_connect_on_launch else StartupAction.NONE
    return StartupAction.UNDECIDED


def read_status(cli: CliAdapter, timeout_s: int) -> ConnectionStatus:
    return status_from_result(cli.status(timeout=timeout_s))


def status_from_result(result: CliResult) -> ConnectionStatus:
    if result.binary_missing:
        return ConnectionStatus(state=ConnectionState.ERROR, raw_text=_CLI_MISSING)
    if result.timed_out:
        return ConnectionStatus(state=ConnectionState.ERROR, raw_text="Timed out reading VPN status")
    return parse_status(result.stdout, result.returncode)


def disconnect_and_verify(
    cli: CliAdapter,
    *,
    disconnect_timeout_s: int = constants.TIMEOUT_DISCONNECT_S,
    status_timeout_s: int = constants.TIMEOUT_STATUS_S,
    verify_attempts: int = constants.DISCONNECT_VERIFY_ATTEMPTS,
    verify_delay_s: float = constants.DISCONNECT_VERIFY_DELAY_S,
    sleep: Callable[[float], None] = time.sleep,
) -> DisconnectOutcome:
    # The exit code alone isn't trusted: the tunnel is a separate root process that
    # outlives both this command and the tray, so only `status` can say it's gone.
    result = cli.disconnect(timeout=disconnect_timeout_s)
    if result.binary_missing:
        status = ConnectionStatus(state=ConnectionState.ERROR, raw_text=_CLI_MISSING)
        return DisconnectOutcome(verified=False, status=status, message=_CLI_MISSING)
    cli_error = _describe_failure(result)

    status = ConnectionStatus(state=ConnectionState.UNKNOWN)
    for attempt in range(verify_attempts):
        if attempt:
            sleep(verify_delay_s)
        status = read_status(cli, status_timeout_s)
        if status.state == ConnectionState.DISCONNECTED:
            return DisconnectOutcome(verified=True, status=status)
        if status.state == ConnectionState.CONNECTED and cli_error:
            break  # disconnect itself failed - waiting won't bring the tunnel down

    if status.state == ConnectionState.CONNECTED:
        message = f"The VPN is still connected to {status.location or 'a VPN location'}."
    else:
        message = "Couldn't confirm that the VPN disconnected."
    if cli_error:
        message += f" adguardvpn-cli disconnect: {cli_error}"
    return DisconnectOutcome(verified=False, status=status, message=message)


def disconnect_for_quit(
    cli: CliAdapter,
    config: AppConfig,
    sleep: Callable[[float], None] = time.sleep,
) -> DisconnectOutcome | None:
    """Short, time-bounded disconnect for app shutdown. None means nothing was done."""
    if not config.disconnect_on_quit:
        return None
    if read_status(cli, constants.TIMEOUT_QUIT_STATUS_S).state == ConnectionState.DISCONNECTED:
        return None
    # Anything else (connected, or status unreadable) gets a disconnect attempt -
    # leaving a tunnel up behind a closed tray is the failure we're guarding against.
    return disconnect_and_verify(
        cli,
        disconnect_timeout_s=constants.TIMEOUT_QUIT_DISCONNECT_S,
        status_timeout_s=constants.TIMEOUT_QUIT_STATUS_S,
        verify_attempts=constants.QUIT_DISCONNECT_VERIFY_ATTEMPTS,
        sleep=sleep,
    )


def _describe_failure(result: CliResult) -> str:
    if result.timed_out:
        return "timed out"  # partial output on timeout isn't reliably decoded - don't show it
    if result.returncode == 0:
        return ""
    detail = strip_ansi(result.stderr or result.stdout).strip()
    return detail or f"exit code {result.returncode}"
