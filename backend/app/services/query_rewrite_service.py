from __future__ import annotations

import re
from functools import lru_cache

from ..core.config import Settings, get_settings
from ..schemas.auth import AuthContext
from ..schemas.query_rewrite import QueryRewriteResult
from .chat_memory_service import ChatMemoryService, get_chat_memory_service


class QueryRewriteService:
    DETAIL_PATTERNS = {
        "更详细一点",
        "更详细点",
        "详细一点",
        "详细点",
        "再详细一点",
        "再详细点",
        "再展开一点",
        "展开一点",
        "继续说",
        "继续",
    }
    FOLLOW_UP_PATTERNS = (
        r"^(那|这|这个|这个词|它|其).+",
        r"^更详细",
        r"^详细",
        r"^再详细",
        r"^再展开",
        r"^继续",
        r"^然后呢[？?]?$",
        r"^接下来呢[？?]?$",
        r"^那第[一二三四五六七八九十0-9]+步呢[？?]?$",
        r"^第[一二三四五六七八九十0-9]+步呢[？?]?$",
        r"^更详细一点[？?]?$",
        r"^为什么",
        r"^怎么",
        r"^如何",
    )
    SUBJECT_PATTERNS = (
        re.compile(r"^(?:请)?(?:解释|介绍|说明|说说|聊聊|总结|概述)(?:一下|下)?(?P<subject>.+?)[。？！!?]?$"),
        re.compile(r"^(?:什么是|啥是)(?P<subject>.+?)[。？！!?]?$"),
        re.compile(r"^(?:请)?(?:更详细地)?解释(?P<subject>.+?)[。？！!?]?$"),
    )

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        chat_memory_service: ChatMemoryService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.chat_memory_service = chat_memory_service or (
            ChatMemoryService(self.settings) if settings is not None else get_chat_memory_service()
        )

    def rewrite_chat_question(
        self,
        *,
        question: str,
        session_id: str | None,
        auth_context: AuthContext | None,
        document_id: str | None,
    ) -> QueryRewriteResult:
        normalized_question = question.strip()
        if not normalized_question:
            return QueryRewriteResult(
                status="skipped",
                original_question=question,
                details={"reason": "empty_question"},
            )
        if not self.settings.query_rewrite_enabled:
            return QueryRewriteResult(
                status="skipped",
                original_question=normalized_question,
                details={"reason": "query_rewrite_disabled"},
            )
        if not session_id or auth_context is None:
            return QueryRewriteResult(
                status="skipped",
                original_question=normalized_question,
                details={"reason": "missing_session_or_auth"},
            )
        if not self._looks_like_follow_up(normalized_question):
            return QueryRewriteResult(
                status="skipped",
                original_question=normalized_question,
                details={"reason": "question_is_self_contained"},
            )

        recent_turns = self.chat_memory_service.get_recent_turns(
            session_id=session_id,
            auth_context=auth_context,
            document_id=document_id,
            limit=1,
        )
        if not recent_turns:
            return QueryRewriteResult(
                status="skipped",
                original_question=normalized_question,
                details={"reason": "no_recent_turns"},
            )

        last_turn = recent_turns[-1]
        last_question = last_turn.question.strip()
        subject = self._extract_subject(last_question)
        rewritten_question = self._rewrite_with_last_turn(
            question=normalized_question,
            last_question=last_question,
            subject=subject,
        )
        if rewritten_question.strip() == normalized_question:
            return QueryRewriteResult(
                status="skipped",
                original_question=normalized_question,
                details={"reason": "rewrite_not_needed", "last_question": last_question},
            )

        return QueryRewriteResult(
            status="applied",
            original_question=normalized_question,
            rewritten_question=rewritten_question,
            details={
                "reason": "short_follow_up_question",
                "last_question": last_question,
                "subject": subject,
            },
        )

    def _looks_like_follow_up(self, question: str) -> bool:
        condensed = re.sub(r"\s+", "", question).strip()
        if len(condensed) > self.settings.query_rewrite_short_question_max_chars:
            return False
        if condensed in self.DETAIL_PATTERNS:
            return True
        return any(re.match(pattern, condensed, re.IGNORECASE) for pattern in self.FOLLOW_UP_PATTERNS)

    def _extract_subject(self, last_question: str) -> str | None:
        normalized = last_question.strip()
        for pattern in self.SUBJECT_PATTERNS:
            match = pattern.match(normalized)
            if match:
                subject = (match.group("subject") or "").strip(" ：:，,。？！!?")
                if subject:
                    return subject
        return None

    def _rewrite_with_last_turn(self, *, question: str, last_question: str, subject: str | None) -> str:
        normalized = question.strip().rstrip("。？！!?")
        if normalized in self.DETAIL_PATTERNS:
            if subject:
                return f"请更详细地解释{subject}。"
            return f"基于上一轮问题“{last_question}”，请更详细地说明。"

        step_match = re.search(r"第([一二三四五六七八九十0-9]+)步", normalized)
        if step_match:
            step = step_match.group(1)
            if subject:
                return f"关于{subject}，第{step}步是什么？"
            return f"基于上一轮问题“{last_question}”，第{step}步是什么？"

        if normalized in {"然后呢", "接下来呢"}:
            if subject:
                return f"关于{subject}，接下来应该怎么做？"
            return f"基于上一轮问题“{last_question}”，接下来呢？"

        if normalized in {"什么意思", "这是什么意思", "那是什么意思", "这个是什么意思"}:
            if subject:
                return f"{subject}是什么意思？"
            return f"基于上一轮问题“{last_question}”，{question.strip()}"

        if normalized.startswith(("为什么", "为何")) and subject:
            return f"为什么会出现{subject}？"

        if normalized.startswith(("怎么", "如何")) and subject:
            return f"关于{subject}，{normalized}？"

        return f"基于上一轮问题“{last_question}”，{question.strip()}"


@lru_cache
def get_query_rewrite_service() -> QueryRewriteService:
    return QueryRewriteService()
