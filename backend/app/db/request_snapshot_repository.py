from datetime import date
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from ..schemas.event_log import EventLogCategory, EventLogOutcome
from ..schemas.request_snapshot import RequestSnapshotRecord


class RequestSnapshotRepository(ABC):
    @abstractmethod
    def append(self, record: RequestSnapshotRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, snapshot_id: str) -> RequestSnapshotRecord | None:
        raise NotImplementedError

    @abstractmethod
    def list_records(
        self,
        *,
        category: EventLogCategory | None = None,
        action: str | None = None,
        outcome: EventLogOutcome | None = None,
        username: str | None = None,
        user_id: str | None = None,
        department_id: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        snapshot_id: str | None = None,
        target_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = 100,
    ) -> list[RequestSnapshotRecord]:
        raise NotImplementedError


class FilesystemRequestSnapshotRepository(RequestSnapshotRepository):
    def __init__(self, request_snapshot_dir: Path) -> None:
        self.request_snapshot_dir = request_snapshot_dir
        self.request_snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, record: RequestSnapshotRecord) -> None:
        target_path = self.request_snapshot_dir / f"{record.snapshot_id}.json"
        payload = record.model_dump_json(indent=2)
        with self._lock:
            target_path.write_text(payload, encoding="utf-8")

    def get(self, snapshot_id: str) -> RequestSnapshotRecord | None:
        target_path = self.request_snapshot_dir / f"{snapshot_id}.json"
        if not target_path.exists():
            return None
        return RequestSnapshotRecord.model_validate_json(target_path.read_text(encoding="utf-8"))

    def list_records(
        self,
        *,
        category: EventLogCategory | None = None,
        action: str | None = None,
        outcome: EventLogOutcome | None = None,
        username: str | None = None,
        user_id: str | None = None,
        department_id: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        snapshot_id: str | None = None,
        target_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = 100,
    ) -> list[RequestSnapshotRecord]:
        safe_limit = None if limit is None else max(1, limit)
        records: list[RequestSnapshotRecord] = []
        for path in sorted(self.request_snapshot_dir.glob("*.json"), reverse=True):
            record = RequestSnapshotRecord.model_validate_json(path.read_text(encoding="utf-8"))
            if category is not None and record.category != category:
                continue
            if action is not None and record.action != action:
                continue
            if outcome is not None and record.outcome != outcome:
                continue
            if username is not None and record.actor.username != username:
                continue
            if user_id is not None and record.actor.user_id != user_id:
                continue
            if department_id is not None and record.actor.department_id != department_id:
                continue
            if trace_id is not None and record.trace_id != trace_id:
                continue
            if request_id is not None and record.request_id != request_id:
                continue
            if snapshot_id is not None and record.snapshot_id != snapshot_id:
                continue
            if target_id is not None and record.target_id != target_id:
                continue
            if date_from is not None and record.occurred_at.date() < date_from:
                continue
            if date_to is not None and record.occurred_at.date() > date_to:
                continue
            records.append(record)
        records.sort(key=lambda item: item.occurred_at, reverse=True)
        if safe_limit is None:
            return records
        return records[:safe_limit]
