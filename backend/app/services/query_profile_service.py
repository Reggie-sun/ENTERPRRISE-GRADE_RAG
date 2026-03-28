from functools import lru_cache

from ..core.config import Settings, get_settings
from ..rag.rerankers.client import RerankerClient
from ..schemas.query_profile import QueryMode, QueryProfile, QueryPurpose
from ..schemas.retrieval import RetrievedChunk
from .system_config_service import SystemConfigService


class QueryProfileService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        system_config_service: SystemConfigService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.system_config_service = system_config_service or SystemConfigService(self.settings)

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
        lexical_top_k = min(max(self._mode_default_lexical_top_k(resolved_mode), top_k), 200)
        fallback_mode: QueryMode | None = "fast" if resolved_mode == "accurate" else None
        return QueryProfile(
            purpose=purpose,
            mode=resolved_mode,
            top_k=top_k,
            candidate_top_k=candidate_top_k,
            lexical_top_k=lexical_top_k,
            rerank_top_n=max(1, rerank_top_n),
            timeout_budget_seconds=self._mode_timeout_budget_seconds(resolved_mode),
            fallback_mode=fallback_mode,
        )

    def build_fallback_profile(self, profile: QueryProfile) -> QueryProfile | None:
        if not self.system_config_service.get_degrade_controls().accurate_to_fast_fallback_enabled:
            return None
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
        effective_strategy = self._resolve_effective_rerank_strategy(reranker_client)
        try:
            reranked = reranker_client.rerank(query=query, candidates=candidates, top_n=safe_top_n)
        except RuntimeError:
            if not self.system_config_service.get_degrade_controls().rerank_fallback_enabled:
                raise
            return reranker_client.rerank_heuristic(query=query, candidates=candidates, top_n=safe_top_n), "heuristic"
        return reranked, effective_strategy or "provider"

    @staticmethod
    def _default_mode_for_purpose(purpose: QueryPurpose) -> QueryMode:
        if purpose == "sop_generation":
            return "accurate"
        return "fast"

    def _mode_default_top_k(self, mode: QueryMode) -> int:
        return self.system_config_service.get_query_mode_settings(mode).top_k_default

    def _mode_default_rerank_top_n(self, mode: QueryMode) -> int:
        return self.system_config_service.get_query_mode_settings(mode).rerank_top_n

    def _mode_default_lexical_top_k(self, mode: QueryMode) -> int:
        return self.system_config_service.get_query_mode_settings(mode).lexical_top_k

    def _mode_candidate_multiplier(self, mode: QueryMode) -> int:
        return self.system_config_service.get_query_mode_settings(mode).candidate_multiplier

    def _mode_timeout_budget_seconds(self, mode: QueryMode) -> float:
        return self.system_config_service.get_query_mode_settings(mode).timeout_budget_seconds

    @staticmethod
    def _resolve_effective_rerank_strategy(reranker_client: RerankerClient) -> str | None:
        if not hasattr(reranker_client, "get_runtime_status"):
            return None
        try:
            status = reranker_client.get_runtime_status()
        except Exception:
            return None
        effective_strategy = str(status.get("effective_strategy") or "").strip().lower()
        if effective_strategy in {"provider", "heuristic"}:
            return effective_strategy
        return None


@lru_cache
def get_query_profile_service() -> QueryProfileService:
    return QueryProfileService()
