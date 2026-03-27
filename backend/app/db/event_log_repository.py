from datetime import date
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from ..schemas.event_log import EventLogCategory, EventLogOutcome, EventLogRecord


class EventLogRepository(ABC):
    @abstractmethod
    def append(self, record: EventLogRecord) -> None:
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
        target_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = 100,
    ) -> list[EventLogRecord]:
        raise NotImplementedError


class FilesystemEventLogRepository(EventLogRepository):
    def __init__(self, event_log_dir: Path) -> None:
        self.event_log_dir = event_log_dir
        self.event_log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, record: EventLogRecord) -> None:
        target_path = self.event_log_dir / f"{record.occurred_at.date().isoformat()}.jsonl"
        line = f"{record.model_dump_json()}\n"
        with self._lock:
            with target_path.open("a", encoding="utf-8") as handle:
                handle.write(line)

    def list_records(
        self,
        *,
        category: EventLogCategory | None = None,
        action: str | None = None,
        outcome: EventLogOutcome | None = None,
        username: str | None = None,
        user_id: str | None = None,
        department_id: str | None = None,
        target_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = 100,
    ) -> list[EventLogRecord]:
        safe_limit = None if limit is None else max(1, limit)
        records: list[EventLogRecord] = []
        for path in sorted(self.event_log_dir.glob("*.jsonl"), reverse=True):
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    normalized = line.strip()
                    if not normalized:
                        continue
                    record = EventLogRecord.model_validate_json(normalized)
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
