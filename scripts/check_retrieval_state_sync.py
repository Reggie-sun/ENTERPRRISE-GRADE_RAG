#!/usr/bin/env python3

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ".agent/context/retrieval-state.md"

WATCHED_PATHS = {
    "data/system_config.json",
    "scripts/eval_retrieval.py",
    "eval/retrieval_samples.yaml",
    "eval/README.md",
    "RETRIEVAL_OPTIMIZATION_PLAN.md",
    "RETRIEVAL_OPTIMIZATION_BACKLOG.md",
}

WATCHED_PREFIXES = (
    "eval/results/",
    "eval/experiments/",
)


@dataclass(frozen=True)
class SyncCheckResult:
    requires_state_update: bool
    state_file_changed: bool
    trigger_paths: tuple[str, ...]

    def is_ok(self) -> bool:
        return (not self.requires_state_update) or self.state_file_changed


def _normalize_paths(paths: Iterable[str]) -> set[str]:
    normalized: set[str] = set()
    for raw in paths:
        path = raw.strip()
        if not path:
            continue
        normalized.add(path.replace("\\", "/"))
    return normalized


def _matches_watched_path(path: str) -> bool:
    if path in WATCHED_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in WATCHED_PREFIXES)


def evaluate_changed_paths(paths: Iterable[str]) -> SyncCheckResult:
    normalized = _normalize_paths(paths)
    trigger_paths = tuple(sorted(path for path in normalized if _matches_watched_path(path)))
    return SyncCheckResult(
        requires_state_update=bool(trigger_paths),
        state_file_changed=STATE_FILE in normalized,
        trigger_paths=trigger_paths,
    )


def get_changed_paths(repo_root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    changed: set[str] = set()
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.add(path)
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether retrieval-state.md was updated when baseline / threshold / phase inputs changed."
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        default=None,
        help="Optional explicit changed paths. If omitted, inspect current git status.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    changed_paths = set(args.paths) if args.paths is not None else get_changed_paths(PROJECT_ROOT)
    result = evaluate_changed_paths(changed_paths)

    if result.is_ok():
        if result.requires_state_update:
            print(f"OK: retrieval state changed together with trigger paths ({', '.join(result.trigger_paths)})")
        else:
            print("OK: no retrieval-state sync trigger detected")
        return 0

    print("ERROR: retrieval-state sync check failed")
    print(f"- Trigger paths: {', '.join(result.trigger_paths)}")
    print(f"- Missing update: {STATE_FILE}")
    print("- Fix: update retrieval-state.md before treating new baseline / thresholds / phase judgment as current truth")
    return 1


if __name__ == "__main__":
    sys.exit(main())
