from functools import lru_cache

from ..core.config import Settings, get_settings
from ..rag.rerankers.client import RerankerClient
from ..schemas.query_profile import QueryMode, QueryProfile, QueryPurpose
from ..schemas.retrieval import RetrievedChunk


class QueryProfileService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def resolve(
        self,
        *,
        purpose: QueryPurpose,
        requested_mode: QueryMode | None = None,
        requested_top_k: int | None = None,
    ) -> QueryProfile:
        resolved_mode = requested_mode or self._default_mode_for_purpose(purpose)
        default_top_k = self._mode_default_top_k(resolved_mode)
        top_k = requested_top_k or default_top_k
        rerank_top_n = min(top_k, self._mode_default_rerank_top_n(resolved_mode))
        candidate_multiplier = self._mode_candidate_multiplier(resolved_mode)
        candidate_top_k = min(max(top_k * candidate_multiplier, top_k), 200)
        fallback_mode: QueryMode | None = "fast" if resolved_mode == "accurate" else None
        return QueryProfile(
            purpose=purpose,
            mode=resolved_mode,
            top_k=top_k,
            candidate_top_k=candidate_top_k,
            rerank_top_n=max(1, rerank_top_n),
            timeout_budget_seconds=self._mode_timeout_budget_seconds(resolved_mode),
            fallback_mode=fallback_mode,
        )

    def build_fallback_profile(self, profile: QueryProfile) -> QueryProfile | None:
        if profile.fallback_mode is None:
            return None
        return self.resolve(
            purpose=profile.purpose,
            requested_mode=profile.fallback_mode,
            requested_top_k=profile.top_k,
        )

    def rerank_with_fallback(
        self,
        *,
        query: str,
        candidates: list[RetrievedChunk],
        profile: QueryProfile,
        reranker_client: RerankerClient,
    ) -> tuple[list[RetrievedChunk], str]:
        safe_top_n = min(profile.rerank_top_n, len(candidates))
        if safe_top_n <= 0:
            return [], "skipped"
        try:
            return reranker_client.rerank(query=query, candidates=candidates, top_n=safe_top_n), "provider"
        except RuntimeError:
            return reranker_client.rerank_heuristic(query=query, candidates=candidates, top_n=safe_top_n), "heuristic"

    @staticmethod
    def _default_mode_for_purpose(purpose: QueryPurpose) -> QueryMode:
        if purpose == "sop_generation":
            return "accurate"
        return "fast"

    def _mode_default_top_k(self, mode: QueryMode) -> int:
        if mode == "accurate":
            return self.settings.query_accurate_top_k_default
        return self.settings.query_fast_top_k_default

    def _mode_default_rerank_top_n(self, mode: QueryMode) -> int:
        if mode == "accurate":
            return self.settings.query_accurate_rerank_top_n
        return self.settings.query_fast_rerank_top_n

    def _mode_candidate_multiplier(self, mode: QueryMode) -> int:
        if mode == "accurate":
            return self.settings.query_accurate_candidate_multiplier
        return self.settings.query_fast_candidate_multiplier

    def _mode_timeout_budget_seconds(self, mode: QueryMode) -> float:
        if mode == "accurate":
            return self.settings.query_accurate_timeout_budget_seconds
        return self.settings.query_fast_timeout_budget_seconds


@lru_cache
def get_query_profile_service() -> QueryProfileService:
    return QueryProfileService()
