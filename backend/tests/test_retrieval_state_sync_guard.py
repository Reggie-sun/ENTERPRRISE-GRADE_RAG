import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "check_retrieval_state_sync.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("retrieval_state_sync_guard", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_requires_state_update_when_threshold_or_baseline_inputs_change() -> None:
    guard = _load_module()

    changed_paths = {
        "data/system_config.json",
        "eval/results/eval_20260405_112755.json",
    }

    result = guard.evaluate_changed_paths(changed_paths)

    assert result.requires_state_update is True
    assert result.state_file_changed is False
    assert "data/system_config.json" in result.trigger_paths
    assert "eval/results/eval_20260405_112755.json" in result.trigger_paths


def test_passes_when_state_file_is_updated_alongside_trigger_paths() -> None:
    guard = _load_module()

    changed_paths = {
        "data/system_config.json",
        ".agent/context/retrieval-state.md",
    }

    result = guard.evaluate_changed_paths(changed_paths)

    assert result.requires_state_update is True
    assert result.state_file_changed is True
    assert result.is_ok() is True


def test_ignores_unrelated_file_changes() -> None:
    guard = _load_module()

    result = guard.evaluate_changed_paths({"README.md"})

    assert result.requires_state_update is False
    assert result.state_file_changed is False
    assert result.is_ok() is True
