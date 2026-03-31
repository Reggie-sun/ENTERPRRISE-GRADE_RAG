"""对话记忆数据仓库。管理会话上下文的持久化存储。"""
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from ..schemas.chat_memory import ChatMemorySession


class ChatMemoryRepository(ABC):
    @abstractmethod
    def get(self, session_id: str) -> ChatMemorySession | None:
        raise NotImplementedError

    @abstractmethod
    def upsert(self, session: ChatMemorySession) -> None:
        raise NotImplementedError


class FilesystemChatMemoryRepository(ChatMemoryRepository):
    def __init__(self, chat_memory_dir: Path) -> None:
        self.chat_memory_dir = chat_memory_dir
        self.chat_memory_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def get(self, session_id: str) -> ChatMemorySession | None:
        path = self.chat_memory_dir / f"{session_id}.json"
        if not path.exists():
            return None
        return ChatMemorySession.model_validate_json(path.read_text(encoding="utf-8"))

    def upsert(self, session: ChatMemorySession) -> None:
        path = self.chat_memory_dir / f"{session.session_id}.json"
        payload = session.model_dump_json(indent=2)
        with self._lock:
            path.write_text(payload, encoding="utf-8")
