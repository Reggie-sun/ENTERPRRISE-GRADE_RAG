import importlib.util
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "agent_harness.py"
POLICY_PATH = PROJECT_ROOT / ".agent" / "harness" / "policy.yaml"


def _load_module():
    spec = importlib.util.spec_from_file_location("agent_harness_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_task_contract(
    tmp_path: Path,
    *,
    task_type: str,
    allowed_paths: list[str],
    required_reads: list[str],
    required_checks: list[str],
    risk_notes: list[str] | None = None,
    expected_artifacts: list[str] | None = None,
) -> Path:
    task_path = tmp_path / f"{task_type}_task.yaml"
    payload = {
        "task_type": task_type,
        "phase": "phase-test",
        "allowed_paths": allowed_paths,
        "required_reads": required_reads,
        "required_checks": required_checks,
        "risk_notes": risk_notes or [],
        "expected_artifacts": expected_artifacts or [],
    }
    task_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return task_path


def test_inspect_classifies_retrieval_and_ignores_runtime_noise() -> None:
    harness = _load_module()
    policy = harness.load_policy(POLICY_PATH)

    result = harness.inspect_changed_paths(
        {
            "backend/app/services/retrieval_service.py",
            "data/request_snapshots/rsp_001.json",
        },
        policy,
    )

    assert result.categories == ("retrieval",)
    assert result.task_contract_required is True
    assert result.suggested_plan == "/retrieval-plan"
    assert "data/request_snapshots/rsp_001.json" in result.ignored_paths
    assert "retrieval_state_sync" in result.default_checks


def test_inspect_marks_frontend_page_change_as_lite() -> None:
    harness = _load_module()
    policy = harness.load_policy(POLICY_PATH)

    result = harness.inspect_changed_paths({"frontend/src/pages/LoginPage.tsx"}, policy)

    assert result.categories == ("lite",)
    assert result.task_contract_required is False
    assert result.suggested_plan is None


def test_preflight_requires_task_for_high_risk_changes() -> None:
    harness = _load_module()
    policy = harness.load_policy(POLICY_PATH)

    result = harness.preflight_task(
        task=None,
        changed_paths={"backend/app/services/retrieval_service.py"},
        policy=policy,
    )

    assert result.ok is False
    assert result.missing_task is True
    assert result.categories == ("retrieval",)


def test_preflight_rejects_paths_outside_allowed_scope(tmp_path: Path) -> None:
    harness = _load_module()
    policy = harness.load_policy(POLICY_PATH)
    task_path = _write_task_contract(
        tmp_path,
        task_type="retrieval",
        allowed_paths=["backend/app/services/retrieval_service.py"],
        required_reads=list(policy["categories"]["retrieval"]["mandatory_reads"]),
        required_checks=[],
    )
    task = harness.load_task_contract(task_path)

    result = harness.preflight_task(
        task=task,
        changed_paths={
            "backend/app/services/retrieval_service.py",
            "frontend/src/pages/LoginPage.tsx",
        },
        policy=policy,
    )

    assert result.ok is False
    assert "frontend/src/pages/LoginPage.tsx" in result.paths_outside_scope


def test_preflight_warns_for_non_blocking_unknown_path() -> None:
    harness = _load_module()
    policy = harness.load_policy(POLICY_PATH)

    result = harness.preflight_task(
        task=None,
        changed_paths={"notes/idea.md"},
        policy=policy,
    )

    assert result.ok is True
    assert result.blocking_unknown_paths == ()
    assert "notes/idea.md" in result.warning_unknown_paths


def test_preflight_requires_mandatory_reads_for_high_risk_task(tmp_path: Path) -> None:
    harness = _load_module()
    policy = harness.load_policy(POLICY_PATH)
    task_path = _write_task_contract(
        tmp_path,
        task_type="retrieval",
        allowed_paths=["backend/app/services/retrieval_service.py"],
        required_reads=["MAIN_CONTRACT_MATRIX.md"],
        required_checks=[],
    )
    task = harness.load_task_contract(task_path)

    result = harness.preflight_task(
        task=task,
        changed_paths={"backend/app/services/retrieval_service.py"},
        policy=policy,
    )

    assert result.ok is False
    assert "eval/README.md" in result.missing_required_reads


def test_resolve_required_checks_includes_retrieval_state_sync(tmp_path: Path) -> None:
    harness = _load_module()
    policy = harness.load_policy(POLICY_PATH)
    task_path = _write_task_contract(
        tmp_path,
        task_type="retrieval",
        allowed_paths=["backend/app/services/retrieval_service.py"],
        required_reads=list(policy["categories"]["retrieval"]["mandatory_reads"]),
        required_checks=[],
    )
    task = harness.load_task_contract(task_path)

    required_checks = harness.resolve_required_checks(task, policy)

    assert required_checks == ("retrieval_state_sync",)


def test_verify_reports_failed_check_names(tmp_path: Path) -> None:
    harness = _load_module()
    policy = harness.load_policy(POLICY_PATH)
    task_path = _write_task_contract(
        tmp_path,
        task_type="retrieval",
        allowed_paths=["backend/app/services/retrieval_service.py"],
        required_reads=list(policy["categories"]["retrieval"]["mandatory_reads"]),
        required_checks=[],
    )
    task = harness.load_task_contract(task_path)

    def _fake_runner(check_spec):
        return harness.CheckExecutionResult(
            check_id=check_spec.check_id,
            description=check_spec.description,
            command=check_spec.command,
            ok=False,
            exit_code=1,
            stdout="",
            stderr="retrieval state drift",
        )

    result = harness.verify_task(task=task, changed_paths={"backend/app/services/retrieval_service.py"}, policy=policy, runner=_fake_runner)

    assert result.ok is False
    assert result.failed_check_ids == ("retrieval_state_sync",)
    assert result.checks[0].stderr == "retrieval state drift"
