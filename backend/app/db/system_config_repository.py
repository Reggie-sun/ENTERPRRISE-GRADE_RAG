import json
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class SystemConfigRepository(ABC):
    @abstractmethod
    def read(self) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def write(self, payload: dict[str, Any]) -> None:
        raise NotImplementedError


class FilesystemSystemConfigRepository(SystemConfigRepository):
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def read(self) -> dict[str, Any] | None:
        if not self.config_path.exists():
            return None
        with self._lock:
            with self.config_path.open("r", encoding="utf-8") as handle:
                return json.load(handle)

    def write(self, payload: dict[str, Any]) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        with self._lock:
            with self.config_path.open("w", encoding="utf-8") as handle:
                handle.write(serialized)
