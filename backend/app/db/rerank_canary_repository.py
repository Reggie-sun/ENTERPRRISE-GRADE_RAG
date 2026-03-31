"""重排序金丝雀数据仓库。管理 rerank 对比样本的持久化存储。"""
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from ..schemas.rerank_canary import RerankCanarySampleRecord


class RerankCanaryRepository(ABC):
    @abstractmethod
    def append(self, record: RerankCanarySampleRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_records(self, *, limit: int | None = 100) -> list[RerankCanarySampleRecord]:
        raise NotImplementedError


class FilesystemRerankCanaryRepository(RerankCanaryRepository):
    def __init__(self, rerank_canary_dir: Path) -> None:
        self.rerank_canary_dir = rerank_canary_dir
        self.rerank_canary_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, record: RerankCanarySampleRecord) -> None:
        target_path = self.rerank_canary_dir / f"{record.sample_id}.json"
        payload = record.model_dump_json(indent=2)
        with self._lock:
            target_path.write_text(payload, encoding="utf-8")

    def list_records(self, *, limit: int | None = 100) -> list[RerankCanarySampleRecord]:
        safe_limit = None if limit is None else max(1, limit)
        records: list[RerankCanarySampleRecord] = []
        for path in sorted(self.rerank_canary_dir.glob("*.json"), reverse=True):
            records.append(RerankCanarySampleRecord.model_validate_json(path.read_text(encoding="utf-8")))
        records.sort(key=lambda item: item.occurred_at, reverse=True)
        if safe_limit is None:
            return records
        return records[:safe_limit]
