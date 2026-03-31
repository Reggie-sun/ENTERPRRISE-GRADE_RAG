"""
检索查询路由器 —— 根据用户查询内容自动判断查询类型（精确/语义/混合），
并为混合检索分配 vector 与 lexical 的权重比例。

核心流程:
  1. classify()       — 对查询文本做 token 分析与信号打分，输出查询分类
  2. resolve_branch_weights() — 根据分类结果查表获取对应的向量/词法权重
  3. fixed_branch_weights()   — 当动态权重关闭时，返回固定权重兜底
"""

from dataclasses import dataclass
import re
from typing import Literal

from ..core.config import Settings, get_settings

# 查询类型枚举：fixed(固定权重) / exact(精确匹配优先) / semantic(语义优先) / mixed(混合)
HybridQueryType = Literal["fixed", "exact", "semantic", "mixed"]

# 匹配连续英数串（含常见技术符号）或连续中文字符，用于把查询拆成 token
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*|[\u4e00-\u9fff]+")
_CODE_LIKE_TOKEN_PATTERN = re.compile(
    r"(?ix)"
    r"(?:"
    r"(?=.*[a-z])(?=.*\d)[a-z0-9_.:/-]+"
    r"|"
    r"[a-z]+[-_/.:][a-z0-9_.:/-]+"
    r"|"
    r"v?\d+(?:\.\d+){1,3}[a-z0-9-]*"
    r")"
)
_QUESTION_MARK_PATTERN = re.compile(r"[?？]")
_SEMANTIC_CUE_TERMS = (
    "为什么",
    "怎么",
    "如何",
    "怎样",
    "原因",
    "分析",
    "解释",
    "总结",
    "经验",
    "排查",
    "处理",
    "解决",
    "频繁",
    "停机",
    "异常",
    "故障",
    "请问",
    "是否",
)


@dataclass(frozen=True)
class QueryClassification:
    query_type: Literal["exact", "semantic", "mixed"]
    exact_signals: int
    semantic_signals: int


@dataclass(frozen=True)
class HybridBranchWeights:
    query_type: HybridQueryType
    vector_weight: float
    lexical_weight: float
    dynamic_enabled: bool
    exact_signals: int = 0
    semantic_signals: int = 0


class RetrievalQueryRouter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def classify(self, query: str) -> QueryClassification:
        normalized_query = query.strip().lower()
        tokens = _TOKEN_PATTERN.findall(normalized_query)
        code_like_tokens = [token for token in tokens if self._is_code_like_token(token)]
        semantic_cue_hits = sum(1 for term in _SEMANTIC_CUE_TERMS if term in normalized_query)

        exact_signals = 0
        semantic_signals = 0

        if code_like_tokens:
            exact_signals += 2
        if len(code_like_tokens) >= 2:
            exact_signals += 1
        if code_like_tokens and len(tokens) <= 4:
            exact_signals += 1
        if any(any(separator in token for separator in "-_/.:") for token in code_like_tokens):
            exact_signals += 1

        if semantic_cue_hits > 0:
            semantic_signals += 2
        if _QUESTION_MARK_PATTERN.search(query):
            semantic_signals += 1
        if len(tokens) >= 4 or len(normalized_query) >= 12:
            semantic_signals += 1

        exact_threshold = self.settings.retrieval_query_classifier_exact_signal_threshold
        semantic_threshold = self.settings.retrieval_query_classifier_semantic_signal_threshold

        if exact_signals >= exact_threshold and semantic_signals >= semantic_threshold:
            query_type: Literal["exact", "semantic", "mixed"] = "mixed"
        elif exact_signals >= exact_threshold and exact_signals > semantic_signals:
            query_type = "exact"
        elif semantic_signals >= semantic_threshold and semantic_signals > exact_signals:
            query_type = "semantic"
        else:
            query_type = "mixed"

        return QueryClassification(
            query_type=query_type,
            exact_signals=exact_signals,
            semantic_signals=semantic_signals,
        )

    def resolve_branch_weights(self, query: str) -> HybridBranchWeights:
        if not self.settings.retrieval_dynamic_weighting_enabled:
            return self.fixed_branch_weights()

        classification = self.classify(query)
        if classification.query_type == "exact":
            vector_weight = self.settings.retrieval_hybrid_exact_vector_weight
            lexical_weight = self.settings.retrieval_hybrid_exact_lexical_weight
        elif classification.query_type == "semantic":
            vector_weight = self.settings.retrieval_hybrid_semantic_vector_weight
            lexical_weight = self.settings.retrieval_hybrid_semantic_lexical_weight
        else:
            vector_weight = self.settings.retrieval_hybrid_mixed_vector_weight
            lexical_weight = self.settings.retrieval_hybrid_mixed_lexical_weight

        if vector_weight <= 0 and lexical_weight <= 0:
            return self.fixed_branch_weights()

        return HybridBranchWeights(
            query_type=classification.query_type,
            vector_weight=vector_weight,
            lexical_weight=lexical_weight,
            dynamic_enabled=True,
            exact_signals=classification.exact_signals,
            semantic_signals=classification.semantic_signals,
        )

    def fixed_branch_weights(self) -> HybridBranchWeights:
        return HybridBranchWeights(
            query_type="fixed",
            vector_weight=self.settings.retrieval_hybrid_fixed_vector_weight,
            lexical_weight=self.settings.retrieval_hybrid_fixed_lexical_weight,
            dynamic_enabled=False,
        )

    @staticmethod
    def _is_code_like_token(token: str) -> bool:
        if not token or token.isdigit():
            return False
        if _CODE_LIKE_TOKEN_PATTERN.fullmatch(token):
            return True
        return any(separator in token for separator in "-_/.:") and any(char.isdigit() for char in token)
