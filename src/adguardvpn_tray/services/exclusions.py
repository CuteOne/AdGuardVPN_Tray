from dataclasses import dataclass, field

from adguardvpn_tray.adapters.cli_adapter import CliAdapter
from adguardvpn_tray.models.types import CliResult
from adguardvpn_tray.parsers.ansi import strip_ansi
from adguardvpn_tray.parsers.exclusions_parser import (
    EXCLUSION_MODES,
    parse_exclusion_mode,
    parse_exclusions,
    parse_skipped_entries,
)


@dataclass
class ExclusionsState:
    mode: str  # "general" (bypass the listed sites) | "selective" (tunnel only the listed sites)
    lists: dict[str, list[str]] = field(default_factory=dict)


def load(cli: CliAdapter) -> ExclusionsState | str:
    """The current mode and both lists, or a message saying why they couldn't be read."""
    mode_result = cli.exclusion_mode()
    problem = _failure(mode_result, "read the exclusion mode")
    if problem:
        return problem
    mode = parse_exclusion_mode(mode_result.stdout)
    if mode is None:
        return "Couldn't read the exclusion mode from adguardvpn-cli."

    lists = {}
    for list_mode in EXCLUSION_MODES:
        result = cli.exclusions_show(list_mode)
        problem = _failure(result, f"read the {list_mode} exclusions")
        if problem:
            return problem
        lists[list_mode] = parse_exclusions(result.stdout)
    return ExclusionsState(mode=mode, lists=lists)


def apply(cli: CliAdapter, before: ExclusionsState, after: ExclusionsState) -> list[str]:
    """Make the CLI match `after`. Returns one message per problem; empty means it all applied."""
    problems = []
    for list_mode in EXCLUSION_MODES:
        old = before.lists.get(list_mode, [])
        new = after.lists.get(list_mode, [])
        removed = [entry for entry in old if entry not in new]
        added = [entry for entry in new if entry not in old]
        if removed:
            problems += _check(cli.exclusions_remove(removed, list_mode), f"remove {list_mode} exclusions")
        if added:
            problems += _check(cli.exclusions_add(added, list_mode), f"add {list_mode} exclusions")
    # Mode last, so switching to a list never briefly applies it half-edited.
    if after.mode != before.mode:
        problems += _check(cli.set_exclusion_mode(after.mode), "change the exclusion mode")
    return problems


def _check(result: CliResult, action: str) -> list[str]:
    problem = _failure(result, action)
    if problem:
        return [problem]
    # The CLI skips entries it can't parse and still exits 0.
    return [f"adguardvpn-cli rejected {entry!r}" for entry in parse_skipped_entries(result.stdout)]


def _failure(result: CliResult, action: str) -> str | None:
    if result.binary_missing:
        return "adguardvpn-cli not found"
    if result.timed_out:
        return f"Timed out trying to {action}."
    if result.returncode != 0:
        detail = strip_ansi(result.stderr or result.stdout).strip() or f"exit code {result.returncode}"
        return f"Couldn't {action}: {detail}"
    return None
