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
        r"^(那|这)?两者呢[？?]?$",
        r"^(那|这)?两个呢[？?]?$",
        r"^(前面|上面|之前)两个(?:有(?:什么|啥)?不同|有什么区别)[？?]?$",
        r"^哪个更",
        r"^哪一个更",
        r"^哪种更",
        r"^哪类更",
        r"^有(?:什么|啥)?区别",
        r"^区别是什么",
        r"^有(?:什么|啥)?不同",
        r"^不同是什么",
        r"^(和|跟)(前面|上面|之前).+区别",
        r"^为什么",
        r"^什么原因",
        r"^是什么原因",
        r"^为啥",
        r"^怎么",
        r"^如何",
        r"^会怎么样",
        r"^会怎样",
        r"^不处理会怎么样",
        r"^不处理会怎样",
        r"^有(?:什么|啥)?影响",
        r"^有(?:什么|啥)?后果",
        r"^有(?:什么|啥)?风险",
    )
    SUBJECT_PATTERNS = (
        re.compile(r"^(?:请)?(?:解释|介绍|说明|说说|聊聊|总结|概述)(?:一下|下)?(?P<subject>.+?)[。？！!?]?$"),
        re.compile(r"^(?:什么是|啥是)(?P<subject>.+?)[。？！!?]?$"),
        re.compile(r"^(?:请)?(?:更详细地)?解释(?P<subject>.+?)[。？！!?]?$"),
        re.compile(r"^(?P<subject>.+?)(?:是什么|是什么意思|是什么内容|指什么|啥意思)[。？！!?]?$"),
        re.compile(r"^(?P<subject>.+?)(?:怎么处理|如何处理|怎么办|怎么做|如何做)[。？！!?]?$"),
    )
    MEANING_PATTERNS = {
        "什么意思",
        "是什么意思",
        "这个是什么意思",
        "那是什么意思",
        "这是什么意思",
        "这个词是什么意思",
        "这词是什么意思",
    }
    CAUSE_PATTERNS = {
        "什么原因",
        "是什么原因",
        "这是什么原因",
        "那是什么原因",
        "为啥会这样",
        "为啥这样",
    }
    PREVENT_PATTERNS = {
        "怎么预防",
        "如何预防",
        "怎么避免",
        "如何避免",
        "要怎么预防",
        "要如何预防",
        "要怎么避免",
        "要如何避免",
        "那要怎么预防",
        "那要如何预防",
        "那要怎么避免",
        "那要如何避免",
        "这要怎么预防",
        "这要如何预防",
        "这要怎么避免",
        "这要如何避免",
    }
    IMPACT_PATTERNS = {
        "会怎么样",
        "会怎样",
        "有什么影响",
        "有啥影响",
        "有什么后果",
        "有啥后果",
        "有什么风险",
        "有啥风险",
    }
    UNTREATED_IMPACT_PATTERNS = {
        "不处理会怎么样",
        "不处理会怎样",
    }
    COMPARE_PATTERNS = {
        "有什么区别",
        "有啥区别",
        "区别是什么",
        "有什么不同",
        "有啥不同",
        "不同是什么",
        "这有什么区别",
        "那有什么区别",
        "这个有什么区别",
        "前面两个有什么不同",
        "前面两个有什么区别",
        "上面两个有什么不同",
        "上面两个有什么区别",
        "之前两个有什么不同",
        "之前两个有什么区别",
        "和前面的区别是什么",
        "跟前面的区别是什么",
        "和上面的区别是什么",
        "跟上面的区别是什么",
        "和之前的区别是什么",
        "跟之前的区别是什么",
        "那两者呢",
        "这两者呢",
        "两者呢",
        "那两个呢",
        "这两个呢",
        "两个呢",
    }

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
            limit=max(1, self.settings.chat_memory_max_turns),
        )
        if not recent_turns:
            return QueryRewriteResult(
                status="skipped",
                original_question=normalized_question,
                details={"reason": "no_recent_turns"},
            )

        last_turn = recent_turns[-1]
        last_question = last_turn.question.strip()
        anchor_question = self._resolve_anchor_question(recent_turns)
        subject = self._extract_subject(anchor_question)
        rewritten_question = self._rewrite_with_last_turn(
            question=normalized_question,
            last_question=last_question,
            anchor_question=anchor_question,
            subject=subject,
        )
        if rewritten_question.strip() == normalized_question:
            return QueryRewriteResult(
                status="skipped",
                original_question=normalized_question,
                details={
                    "reason": "rewrite_not_needed",
                    "last_question": last_question,
                    "anchor_question": anchor_question,
                },
            )

        return QueryRewriteResult(
            status="applied",
            original_question=normalized_question,
            rewritten_question=rewritten_question,
            details={
                "reason": "short_follow_up_question",
                "last_question": last_question,
                "anchor_question": anchor_question,
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

    def _resolve_anchor_question(self, turns) -> str:
        for turn in reversed(turns):
            candidate = turn.question.strip()
            if not candidate:
                continue
            if self._extract_comparison_question(candidate):
                return candidate
            if self._extract_subject(candidate):
                return candidate
            if not self._looks_like_follow_up(candidate):
                return candidate
        return turns[-1].question.strip()

    @staticmethod
    def _infer_anchor_intent(anchor_question: str) -> str:
        normalized = re.sub(r"\s+", "", anchor_question).strip().rstrip("。？！!?")
        if QueryRewriteService._extract_comparison_question(normalized):
            return "compare"
        if re.search(r"(怎么处理|如何处理|怎么办|怎么做|如何做)$", normalized):
            return "process"
        if re.search(r"(是什么|是什么意思|是什么内容|指什么|啥意思)$", normalized):
            return "meaning"
        return "explain"

    def _rewrite_with_last_turn(
        self,
        *,
        question: str,
        last_question: str,
        anchor_question: str,
        subject: str | None,
    ) -> str:
        normalized = question.strip().rstrip("。？！!?")
        normalized_core = self._strip_follow_up_prefix(normalized)
        anchor_intent = self._infer_anchor_intent(anchor_question)
        comparison_question = self._extract_comparison_question(anchor_question)
        comparison_pair = self._extract_comparison_pair(anchor_question)
        if normalized in self.DETAIL_PATTERNS or normalized_core in self.DETAIL_PATTERNS:
            if subject:
                if anchor_intent == "process":
                    return f"请更详细地说明{subject}该怎么处理。"
                return f"请更详细地解释{subject}。"
            return f"基于上一轮问题“{anchor_question}”，请更详细地说明。"

        step_match = re.search(r"第([一二三四五六七八九十0-9]+)步", normalized_core)
        if step_match:
            step = step_match.group(1)
            if subject:
                return f"关于{subject}，第{step}步是什么？"
            return f"基于上一轮问题“{anchor_question}”，第{step}步是什么？"

        if normalized_core in {"然后呢", "接下来呢"}:
            if subject:
                return f"关于{subject}，接下来应该怎么做？"
            return f"基于上一轮问题“{anchor_question}”，接下来呢？"

        if normalized_core.startswith(("哪个更", "哪一个更", "哪种更", "哪类更")) and comparison_pair:
            left, right = comparison_pair
            return f"{left}和{right}{normalized_core}？"

        if normalized in self.COMPARE_PATTERNS or normalized_core in self.COMPARE_PATTERNS:
            if comparison_question:
                return comparison_question
            return f"基于上一轮问题“{anchor_question}”，{question.strip()}"

        if normalized in self.MEANING_PATTERNS or normalized_core in self.MEANING_PATTERNS:
            if subject:
                return f"{subject}是什么意思？"
            return f"基于上一轮问题“{anchor_question}”，{question.strip()}"

        if (
            normalized in self.CAUSE_PATTERNS
            or normalized_core in self.CAUSE_PATTERNS
            or normalized_core.endswith("是什么原因")
        ) and subject:
            return f"为什么会出现{subject}？"

        if normalized_core.startswith(("为什么", "为何")) and subject:
            return f"为什么会出现{subject}？"

        if normalized in self.PREVENT_PATTERNS or normalized_core in self.PREVENT_PATTERNS:
            if subject:
                if anchor_intent == "process":
                    return f"如何避免{subject}再次发生？"
                return f"如何预防{subject}？"
            return f"基于上一轮问题“{anchor_question}”，{question.strip()}"

        if normalized in self.UNTREATED_IMPACT_PATTERNS or normalized_core in self.UNTREATED_IMPACT_PATTERNS:
            if subject:
                return f"{subject}不处理会怎么样？"
            return f"基于上一轮问题“{anchor_question}”，{question.strip()}"

        if normalized in self.IMPACT_PATTERNS or normalized_core in self.IMPACT_PATTERNS:
            if subject:
                return f"{subject}{normalized_core}？"
            return f"基于上一轮问题“{anchor_question}”，{question.strip()}"

        if normalized_core.startswith(("怎么", "如何")) and subject:
            if anchor_intent == "process" or "处理" in normalized_core:
                return f"{subject}该怎么处理？"
            return f"关于{subject}，{normalized_core}？"

        return f"基于上一轮问题“{anchor_question}”，{question.strip()}"

    @staticmethod
    def _strip_follow_up_prefix(question: str) -> str:
        normalized = question.strip()
        return re.sub(r"^(那|这|这个|这个词|它|其)", "", normalized).strip()

    @staticmethod
    def _extract_comparison_question(question: str) -> str | None:
        pair = QueryRewriteService._extract_comparison_pair(question)
        if pair is None:
            return None
        left, right = pair
        return f"{left}和{right}有什么区别？"

    @staticmethod
    def _extract_comparison_pair(question: str) -> tuple[str, str] | None:
        normalized = question.strip().rstrip("。？！!?")
        match = re.match(
            r"^(?P<left>.+?)(?:和|跟|与)(?P<right>.+?)(?:有(?:什么|啥)?区别|区别是什么|有(?:什么|啥)?不同|不同是什么)$",
            normalized,
        )
        if not match:
            return None
        left = (match.group("left") or "").strip(" ：:，,。？！!?")
        right = (match.group("right") or "").strip(" ：:，,。？！!?")
        if not left or not right:
            return None
        return left, right


@lru_cache
def get_query_rewrite_service() -> QueryRewriteService:
    return QueryRewriteService()
