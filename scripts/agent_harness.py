#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterable

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = PROJECT_ROOT / ".agent" / "harness" / "policy.yaml"


@dataclass(frozen=True)
class TaskContract:
    task_type: str
    phase: str
    allowed_paths: tuple[str, ...]
    required_reads: tuple[str, ...]
    required_checks: tuple[str, ...]
    risk_notes: tuple[str, ...]
    expected_artifacts: tuple[str, ...]


@dataclass(frozen=True)
class InspectionResult:
    changed_paths: tuple[str, ...]
    ignored_paths: tuple[str, ...]
    categories: tuple[str, ...]
    matched_paths: dict[str, tuple[str, ...]]
    blocking_unknown_paths: tuple[str, ...]
    warning_unknown_paths: tuple[str, ...]
    task_contract_required: bool
    workflows: tuple[str, ...]
    suggested_plan: str | None
    mandatory_reads: tuple[str, ...]
    default_checks: tuple[str, ...]
    recommended_checks: tuple[str, ...]


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    categories: tuple[str, ...]
    missing_task: bool
    missing_required_reads: tuple[str, ...]
    paths_outside_scope: tuple[str, ...]
    blocking_unknown_paths: tuple[str, ...]
    warning_unknown_paths: tuple[str, ...]
    required_checks: tuple[str, ...]


@dataclass(frozen=True)
class CheckSpec:
    check_id: str
    description: str
    command: tuple[str, ...]
    cwd: str | None = None


@dataclass(frozen=True)
class CheckExecutionResult:
    check_id: str
    description: str
    command: tuple[str, ...]
    ok: bool
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    failed_check_ids: tuple[str, ...]
    checks: tuple[CheckExecutionResult, ...]


def _normalize_paths(paths: Iterable[str]) -> tuple[str, ...]:
    normalized = {path.strip().replace("\\", "/") for path in paths if path and path.strip()}
    return tuple(sorted(normalized))


def _ordered_unique(items: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return tuple(ordered)


def load_policy(path: Path | str = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy_path = Path(path)
    data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    if "categories" not in data or "checks" not in data:
        raise ValueError(f"Invalid harness policy: {policy_path}")
    return data


def load_task_contract(path: Path | str) -> TaskContract:
    task_path = Path(path)
    payload = yaml.safe_load(task_path.read_text(encoding="utf-8")) or {}
    return TaskContract(
        task_type=str(payload["task_type"]),
        phase=str(payload["phase"]),
        allowed_paths=_normalize_paths(payload.get("allowed_paths", [])),
        required_reads=_normalize_paths(payload.get("required_reads", [])),
        required_checks=_normalize_paths(payload.get("required_checks", [])),
        risk_notes=tuple(str(item) for item in payload.get("risk_notes", [])),
        expected_artifacts=_normalize_paths(payload.get("expected_artifacts", [])),
    )


def get_changed_paths(repo_root: Path = PROJECT_ROOT) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    changed: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.append(path)
    return _normalize_paths(changed)


def _path_matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch(path, pattern) for pattern in patterns)


def _is_ignored(path: str, policy: dict[str, Any]) -> bool:
    return any(path.startswith(prefix) for prefix in policy.get("ignored_prefixes", []))


def _classify_path(path: str, policy: dict[str, Any]) -> str | None:
    for category_name, category in policy["categories"].items():
        if _path_matches_any(path, category.get("patterns", [])):
            return category_name
    return None


def _is_blocking_unknown(path: str, policy: dict[str, Any]) -> bool:
    return any(path.startswith(prefix) for prefix in policy.get("high_risk_prefixes", []))


def inspect_changed_paths(paths: Iterable[str], policy: dict[str, Any]) -> InspectionResult:
    normalized_paths = _normalize_paths(paths)
    ignored_paths: list[str] = []
    matched_paths: dict[str, list[str]] = {name: [] for name in policy["categories"]}
    blocking_unknown_paths: list[str] = []
    warning_unknown_paths: list[str] = []

    for path in normalized_paths:
        if _is_ignored(path, policy):
            ignored_paths.append(path)
            continue
        category_name = _classify_path(path, policy)
        if category_name is not None:
            matched_paths[category_name].append(path)
            continue
        if _is_blocking_unknown(path, policy):
            blocking_unknown_paths.append(path)
        else:
            warning_unknown_paths.append(path)

    ordered_categories = tuple(name for name in policy["categories"] if matched_paths[name])
    workflows = _ordered_unique(
        workflow
        for category_name in ordered_categories
        for workflow in policy["categories"][category_name].get("workflows", [])
    )
    suggested_plan = next(
        (
            policy["categories"][category_name].get("suggested_plan")
            for category_name in ordered_categories
            if policy["categories"][category_name].get("suggested_plan")
        ),
        None,
    )
    mandatory_reads = _ordered_unique(
        item
        for category_name in ordered_categories
        for item in policy["categories"][category_name].get("mandatory_reads", [])
    )
    default_checks = _ordered_unique(
        item
        for category_name in ordered_categories
        for item in policy["categories"][category_name].get("default_checks", [])
    )
    recommended_checks = _ordered_unique(
        item
        for category_name in ordered_categories
        for item in policy["categories"][category_name].get("recommended_checks", [])
    )
    task_contract_required = bool(
        blocking_unknown_paths
        or any(policy["categories"][category_name].get("task_required") for category_name in ordered_categories)
    )

    filtered_matches = {
        category_name: tuple(paths_for_category)
        for category_name, paths_for_category in matched_paths.items()
        if paths_for_category
    }
    return InspectionResult(
        changed_paths=normalized_paths,
        ignored_paths=tuple(ignored_paths),
        categories=ordered_categories,
        matched_paths=filtered_matches,
        blocking_unknown_paths=tuple(blocking_unknown_paths),
        warning_unknown_paths=tuple(warning_unknown_paths),
        task_contract_required=task_contract_required,
        workflows=workflows,
        suggested_plan=suggested_plan,
        mandatory_reads=mandatory_reads,
        default_checks=default_checks,
        recommended_checks=recommended_checks,
    )


def resolve_required_checks(task: TaskContract, policy: dict[str, Any]) -> tuple[str, ...]:
    category_defaults = tuple(policy["categories"][task.task_type].get("default_checks", []))
    return _ordered_unique((*category_defaults, *task.required_checks))


def _path_allowed(path: str, allowed_paths: Iterable[str]) -> bool:
    return _path_matches_any(path, allowed_paths)


def preflight_task(task: TaskContract | None, changed_paths: Iterable[str], policy: dict[str, Any]) -> PreflightResult:
    inspection = inspect_changed_paths(changed_paths, policy)
    if task is None:
        missing_task = inspection.task_contract_required
        ok = not missing_task and not inspection.blocking_unknown_paths
        return PreflightResult(
            ok=ok,
            categories=inspection.categories,
            missing_task=missing_task,
            missing_required_reads=(),
            paths_outside_scope=(),
            blocking_unknown_paths=inspection.blocking_unknown_paths,
            warning_unknown_paths=inspection.warning_unknown_paths,
            required_checks=inspection.default_checks,
        )

    mandatory_reads = tuple(policy["categories"][task.task_type].get("mandatory_reads", []))
    missing_required_reads = tuple(item for item in mandatory_reads if item not in task.required_reads)
    paths_outside_scope = tuple(
        path
        for path in inspection.changed_paths
        if path not in inspection.ignored_paths and not _path_allowed(path, task.allowed_paths)
    )
    required_checks = resolve_required_checks(task, policy)
    ok = not missing_required_reads and not paths_outside_scope and not inspection.blocking_unknown_paths
    return PreflightResult(
        ok=ok,
        categories=inspection.categories or (task.task_type,),
        missing_task=False,
        missing_required_reads=missing_required_reads,
        paths_outside_scope=paths_outside_scope,
        blocking_unknown_paths=inspection.blocking_unknown_paths,
        warning_unknown_paths=inspection.warning_unknown_paths,
        required_checks=required_checks,
    )


def _resolve_check_specs(check_ids: Iterable[str], policy: dict[str, Any]) -> tuple[CheckSpec, ...]:
    specs: list[CheckSpec] = []
    for check_id in check_ids:
        payload = policy["checks"].get(check_id)
        if payload is None:
            raise KeyError(f"Unknown check id: {check_id}")
        specs.append(
            CheckSpec(
                check_id=check_id,
                description=str(payload["description"]),
                command=tuple(str(item) for item in payload["command"]),
                cwd=str(payload["cwd"]) if payload.get("cwd") else None,
            )
        )
    return tuple(specs)


def execute_check(check_spec: CheckSpec) -> CheckExecutionResult:
    cwd = PROJECT_ROOT / check_spec.cwd if check_spec.cwd else PROJECT_ROOT
    result = subprocess.run(
        list(check_spec.command),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    return CheckExecutionResult(
        check_id=check_spec.check_id,
        description=check_spec.description,
        command=check_spec.command,
        ok=result.returncode == 0,
        exit_code=result.returncode,
        stdout=result.stdout.strip(),
        stderr=result.stderr.strip(),
    )


def verify_task(
    task: TaskContract,
    changed_paths: Iterable[str],
    policy: dict[str, Any],
    runner=None,
) -> VerificationResult:
    del changed_paths
    check_specs = _resolve_check_specs(resolve_required_checks(task, policy), policy)
    run_check = runner or execute_check
    executions = tuple(run_check(check_spec) for check_spec in check_specs)
    failed_check_ids = tuple(execution.check_id for execution in executions if not execution.ok)
    return VerificationResult(
        ok=not failed_check_ids,
        failed_check_ids=failed_check_ids,
        checks=executions,
    )


def _task_template(inspection: InspectionResult, policy: dict[str, Any]) -> str:
    primary_category = inspection.categories[0] if inspection.categories else "lite"
    allowed_paths = inspection.matched_paths.get(primary_category, ())
    expected_artifacts = (".agent/context/retrieval-state.md",) if primary_category == "retrieval" else ()
    template = {
        "task_type": primary_category,
        "phase": "fill-me",
        "allowed_paths": list(allowed_paths),
        "required_reads": list(inspection.mandatory_reads),
        "required_checks": list(_ordered_unique((*inspection.default_checks, *inspection.recommended_checks))),
        "risk_notes": [
            "Replace with task-specific risks before implementation.",
        ],
        "expected_artifacts": list(expected_artifacts),
    }
    return yaml.safe_dump(template, sort_keys=False, allow_unicode=True)


def _render_inspection(inspection: InspectionResult, policy: dict[str, Any]) -> str:
    lines = [
        "Inspection",
        f"- Categories: {', '.join(inspection.categories) or 'none'}",
        f"- Workflows: {', '.join(inspection.workflows) or 'none'}",
        f"- Suggested plan: {inspection.suggested_plan or 'none'}",
        f"- Task contract required: {'yes' if inspection.task_contract_required else 'no'}",
    ]
    if inspection.ignored_paths:
        lines.append(f"- Ignored paths: {', '.join(inspection.ignored_paths)}")
    if inspection.blocking_unknown_paths:
        lines.append(f"- Blocking unknown paths: {', '.join(inspection.blocking_unknown_paths)}")
    if inspection.warning_unknown_paths:
        lines.append(f"- Warning unknown paths: {', '.join(inspection.warning_unknown_paths)}")
    if inspection.mandatory_reads:
        lines.append(f"- Mandatory reads: {', '.join(inspection.mandatory_reads)}")
    if inspection.default_checks:
        lines.append(f"- Default checks: {', '.join(inspection.default_checks)}")
    if inspection.recommended_checks:
        lines.append(f"- Recommended checks: {', '.join(inspection.recommended_checks)}")
    if inspection.task_contract_required:
        lines.extend(["", "Suggested task contract template:", _task_template(inspection, policy).rstrip()])
    return "\n".join(lines)


def _render_preflight(result: PreflightResult) -> str:
    lines = [
        "Preflight",
        f"- Status: {'ok' if result.ok else 'failed'}",
        f"- Categories: {', '.join(result.categories) or 'none'}",
        f"- Required checks: {', '.join(result.required_checks) or 'none'}",
    ]
    if result.missing_task:
        lines.append("- Missing task contract: yes")
    if result.missing_required_reads:
        lines.append(f"- Missing required reads: {', '.join(result.missing_required_reads)}")
    if result.paths_outside_scope:
        lines.append(f"- Paths outside allowed scope: {', '.join(result.paths_outside_scope)}")
    if result.blocking_unknown_paths:
        lines.append(f"- Blocking unknown paths: {', '.join(result.blocking_unknown_paths)}")
    if result.warning_unknown_paths:
        lines.append(f"- Warning unknown paths: {', '.join(result.warning_unknown_paths)}")
    return "\n".join(lines)


def _render_verification(result: VerificationResult) -> str:
    lines = [
        "Verification",
        f"- Status: {'ok' if result.ok else 'failed'}",
    ]
    for check in result.checks:
        lines.append(
            f"- {check.check_id}: {'ok' if check.ok else 'failed'} (exit={check.exit_code})"
        )
        if check.stderr:
            lines.append(f"  stderr: {check.stderr}")
    if result.failed_check_ids:
        lines.append(f"- Failed checks: {', '.join(result.failed_check_ids)}")
    return "\n".join(lines)


def _serialize(result: Any) -> str:
    return json.dumps(asdict(result), ensure_ascii=False, indent=2)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repository-local execution harness for agent workflow enforcement.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect changed paths and suggest workflow requirements.")
    inspect_parser.add_argument("--paths", nargs="*", default=None, help="Explicit changed paths. Defaults to git status.")
    inspect_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    preflight_parser = subparsers.add_parser("preflight", help="Validate changed paths against a task contract.")
    preflight_parser.add_argument("--task", default=None, help="Path to task contract YAML.")
    preflight_parser.add_argument("--paths", nargs="*", default=None, help="Explicit changed paths. Defaults to git status.")
    preflight_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    verify_parser = subparsers.add_parser("verify", help="Run verification checks from a task contract.")
    verify_parser.add_argument("--task", required=True, help="Path to task contract YAML.")
    verify_parser.add_argument("--paths", nargs="*", default=None, help="Explicit changed paths. Defaults to git status.")
    verify_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    return parser.parse_args()


def _paths_from_args(explicit_paths: list[str] | None) -> tuple[str, ...]:
    return _normalize_paths(explicit_paths) if explicit_paths is not None else get_changed_paths(PROJECT_ROOT)


def main() -> int:
    args = _parse_args()
    policy = load_policy(DEFAULT_POLICY_PATH)

    if args.command == "inspect":
        inspection = inspect_changed_paths(_paths_from_args(args.paths), policy)
        print(_serialize(inspection) if args.json else _render_inspection(inspection, policy))
        return 0

    if args.command == "preflight":
        task = load_task_contract(args.task) if args.task else None
        result = preflight_task(task=task, changed_paths=_paths_from_args(args.paths), policy=policy)
        print(_serialize(result) if args.json else _render_preflight(result))
        return 0 if result.ok else 1

    if args.command == "verify":
        task = load_task_contract(args.task)
        result = verify_task(task=task, changed_paths=_paths_from_args(args.paths), policy=policy)
        print(_serialize(result) if args.json else _render_verification(result))
        return 0 if result.ok else 1

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
