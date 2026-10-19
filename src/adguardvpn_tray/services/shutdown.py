import signal
from typing import Callable

# systemd stops the autostart unit with SIGTERM at logout; SIGINT/SIGHUP cover a
# terminal launch. All of them should end in a normal quit so cleanup runs.
QUIT_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)


def install_quit_signal_handlers(request_quit: Callable[[], None]) -> None:
    for sig in QUIT_SIGNALS:
        signal.signal(sig, lambda _signum, _frame: request_quit())
