from pathlib import Path

from backend.app.core.config import Settings
from backend.app.services.runtime_gate_service import RuntimeGateService
from backend.app.services.system_config_service import SystemConfigService


def _build_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        system_config_path=tmp_path / "data" / "system_config.json",
    )


def test_runtime_gate_service_acquire_release_and_snapshot(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    system_config_service = SystemConfigService(settings)
    gate = RuntimeGateService(settings, system_config_service=system_config_service)

    system_config_service.repository.write(
        {
            "concurrency_controls": {
                "fast_max_inflight": 1,
                "accurate_max_inflight": 1,
                "sop_generation_max_inflight": 1,
                "per_user_online_max_inflight": 1,
                "acquire_timeout_ms": 0,
                "busy_retry_after_seconds": 7,
            }
        }
    )

    first_lease = gate.acquire("chat_fast", timeout_ms=0)
    second_lease = gate.acquire("chat_fast", timeout_ms=0)
    snapshot_while_busy = gate.get_snapshot()

    assert first_lease is not None
    assert second_lease is None
    assert snapshot_while_busy.acquire_timeout_ms == 0
    assert snapshot_while_busy.busy_retry_after_seconds == 7
    assert snapshot_while_busy.per_user_online_max_inflight == 1
    assert snapshot_while_busy.active_users == 0
    assert snapshot_while_busy.max_user_inflight == 0
    fast_state = next(item for item in snapshot_while_busy.channels if item.channel == "chat_fast")
    assert fast_state.inflight == 1
    assert fast_state.limit == 1
    assert fast_state.available_slots == 0

    first_lease.release()
    third_lease = gate.acquire("chat_fast", timeout_ms=0)
    snapshot_after_release = gate.get_snapshot()

    assert third_lease is not None
    fast_state_after_release = next(item for item in snapshot_after_release.channels if item.channel == "chat_fast")
    assert fast_state_after_release.inflight == 1
    assert fast_state_after_release.available_slots == 0

    third_lease.release()
    final_snapshot = gate.get_snapshot()
    final_fast_state = next(item for item in final_snapshot.channels if item.channel == "chat_fast")
    assert final_fast_state.inflight == 0
    assert final_fast_state.available_slots == 1


def test_runtime_gate_service_enforces_single_user_limit(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    system_config_service = SystemConfigService(settings)
    gate = RuntimeGateService(settings, system_config_service=system_config_service)

    system_config_service.repository.write(
        {
            "concurrency_controls": {
                "fast_max_inflight": 4,
                "accurate_max_inflight": 2,
                "sop_generation_max_inflight": 1,
                "per_user_online_max_inflight": 2,
                "acquire_timeout_ms": 0,
                "busy_retry_after_seconds": 5,
            }
        }
    )

    first_lease, first_reason = gate.acquire_with_reason("chat_fast", timeout_ms=0, owner_key="user_a")
    second_lease, second_reason = gate.acquire_with_reason("chat_accurate", timeout_ms=0, owner_key="user_a")
    third_lease, third_reason = gate.acquire_with_reason("sop_generation", timeout_ms=0, owner_key="user_a")
    other_user_lease, other_user_reason = gate.acquire_with_reason("chat_fast", timeout_ms=0, owner_key="user_b")
    snapshot_while_busy = gate.get_snapshot()

    assert first_lease is not None
    assert first_reason is None
    assert second_lease is not None
    assert second_reason is None
    assert third_lease is None
    assert third_reason == "user_limit"
    assert other_user_lease is not None
    assert other_user_reason is None
    assert snapshot_while_busy.per_user_online_max_inflight == 2
    assert snapshot_while_busy.active_users == 2
    assert snapshot_while_busy.max_user_inflight == 2

    first_lease.release()
    second_lease.release()
    other_user_lease.release()

    final_snapshot = gate.get_snapshot()
    assert final_snapshot.active_users == 0
    assert final_snapshot.max_user_inflight == 0
