from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from uuid import uuid4

from ..core.config import Settings, get_settings
from ..db.chat_memory_repository import ChatMemoryRepository, FilesystemChatMemoryRepository
from ..schemas.auth import AuthContext
from ..schemas.chat_memory import ChatMemorySession, ChatMemoryTurn
from .token_budget_service import TokenBudgetService


class ChatMemoryService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        repository: ChatMemoryRepository | None = None,
        token_budget_service: TokenBudgetService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or FilesystemChatMemoryRepository(self.settings.chat_memory_dir)
        self.token_budget_service = token_budget_service or TokenBudgetService(self.settings)

    def build_memory_summary(
        self,
        *,
        session_id: str | None,
        auth_context: AuthContext | None,
        document_id: str | None,
    ) -> str | None:
        if not self.settings.chat_memory_enabled or not session_id or auth_context is None:
            return None
        session = self.repository.get(session_id)
        if session is None or session.user_id != auth_context.user.user_id:
            return None

        turns = self._filter_turns_for_document(session.turns, document_id=document_id)
        if not turns:
            return None

        selected_turns = turns[-self.settings.chat_memory_max_turns :]
        memory_budget = self.settings.chat_memory_max_prompt_tokens
        retained_turns_newest_first: list[ChatMemoryTurn] = []
        # When the prompt budget is tight, keep the latest contiguous turns first.
        for turn in reversed(selected_turns):
            candidate_turns_newest_first = retained_turns_newest_first + [turn]
            candidate_summary = self._render_memory_summary(
                list(reversed(candidate_turns_newest_first))
            )
            if self._estimate_token_count(candidate_summary) > memory_budget:
                break
            retained_turns_newest_first = candidate_turns_newest_first

        if not retained_turns_newest_first:
            return self._render_memory_summary([selected_turns[-1]])
        return self._render_memory_summary(list(reversed(retained_turns_newest_first)))

    def record_turn(
        self,
        *,
        session_id: str | None,
        auth_context: AuthContext | None,
        document_id: str | None,
        question: str,
        answer: str,
        response_mode: str,
        citation_count: int,
    ) -> None:
        if not self.settings.chat_memory_enabled or not session_id or auth_context is None:
            return
        normalized_question = question.strip()
        normalized_answer = answer.strip()
        if not normalized_question or not normalized_answer:
            return
        if response_mode == "failed":
            return

        session = self.repository.get(session_id)
        if session is None or session.user_id != auth_context.user.user_id:
            session = ChatMemorySession(
                session_id=session_id,
                user_id=auth_context.user.user_id,
                username=auth_context.user.username,
                department_id=auth_context.user.department_id,
                updated_at=datetime.now(timezone.utc),
                turns=[],
            )

        session.turns.append(
            ChatMemoryTurn(
                turn_id=f"turn_{uuid4().hex[:12]}",
                asked_at=datetime.now(timezone.utc),
                question=self._truncate_chars(normalized_question, self.settings.chat_memory_question_max_chars),
                answer=self._truncate_chars(normalized_answer, self.settings.chat_memory_answer_max_chars),
                response_mode=response_mode,
                document_id=document_id,
                citation_count=max(0, citation_count),
            )
        )
        session.turns = session.turns[-self.settings.chat_memory_max_turns :]
        session.updated_at = datetime.now(timezone.utc)
        self.repository.upsert(session)

    def get_recent_turns(
        self,
        *,
        session_id: str | None,
        auth_context: AuthContext | None,
        document_id: str | None,
        limit: int | None = None,
    ) -> list[ChatMemoryTurn]:
        if not self.settings.chat_memory_enabled or not session_id or auth_context is None:
            return []
        session = self.repository.get(session_id)
        if session is None or session.user_id != auth_context.user.user_id:
            return []
        turns = self._filter_turns_for_document(session.turns, document_id=document_id)
        if limit is None or limit <= 0:
            return turns
        return turns[-limit:]

    @staticmethod
    def _truncate_chars(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return f"{text[: max_chars - 3].rstrip()}..."

    def _estimate_token_count(self, text: str) -> int:
        return self.token_budget_service.estimate_token_count(text)

    def _render_memory_summary(self, turns: list[ChatMemoryTurn]) -> str:
        return "\n\n".join(
            self._build_memory_block(index=index, turn=turn)
            for index, turn in enumerate(turns, start=1)
        )

    def _build_memory_block(self, *, index: int, turn: ChatMemoryTurn) -> str:
        question = self._truncate_chars(turn.question, self.settings.chat_memory_question_max_chars)
        answer = self._truncate_chars(turn.answer, self.settings.chat_memory_answer_max_chars)
        return (
            f"[Recent Turn {index}]\n"
            f"User: {question}\n"
            f"Assistant: {answer}"
        )

    @staticmethod
    def _filter_turns_for_document(
        turns: list[ChatMemoryTurn],
        *,
        document_id: str | None,
    ) -> list[ChatMemoryTurn]:
        if document_id:
            return [turn for turn in turns if turn.document_id == document_id]
        return [turn for turn in turns if turn.document_id is None]


@lru_cache
def get_chat_memory_service() -> ChatMemoryService:
    return ChatMemoryService()
