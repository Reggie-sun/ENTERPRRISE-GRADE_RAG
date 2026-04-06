"""重排序金丝雀服务模块。收集和查询 rerank 对比验证样本，用于策略决策复盘。"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from uuid import uuid4

from ..core.config import Settings, get_settings
from ..db.rerank_canary_repository import FilesystemRerankCanaryRepository, RerankCanaryRepository
from ..schemas.auth import AuthContext
from ..schemas.event_log import EventLogActor
from ..schemas.rerank_canary import RerankCanarySampleRecord, RerankCanarySummary
from ..schemas.retrieval import RetrievalRerankCompareResponse, RetrievedChunk


class RerankCanaryService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        repository: RerankCanaryRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        rerank_canary_dir = self.settings.rerank_canary_dir
        if rerank_canary_dir is None:
            raise RuntimeError("Rerank canary directory is not configured.")
        self.repository = repository or FilesystemRerankCanaryRepository(rerank_canary_dir)

    def record_compare_sample(
        self,
        *,
        query: str,
        mode: str,
        target_id: str | None,
        auth_context: AuthContext | None,
        response: RetrievalRerankCompareResponse,
    ) -> RerankCanarySampleRecord:
        record = RerankCanarySampleRecord(
            sample_id=f"rcs_{uuid4().hex[:16]}",
            occurred_at=datetime.now(timezone.utc),
            actor=self._build_actor(auth_context),
            query=query,
            mode=mode,
            target_id=target_id,
            candidate_count=response.candidate_count,
            rerank_top_n=response.rerank_top_n,
            route_status=response.route_status.model_copy(deep=True),
            configured_provider=response.configured.provider,
            configured_strategy=response.configured.strategy,
            configured_error_message=response.configured.error_message,
            heuristic_strategy=response.heuristic.strategy,
            provider_candidate_strategy=response.provider_candidate.strategy if response.provider_candidate else None,
            provider_candidate_error_message=response.provider_candidate.error_message if response.provider_candidate else None,
            summary=response.summary.model_copy(deep=True),
            provider_candidate_summary=response.provider_candidate_summary.model_copy(deep=True)
            if response.provider_candidate_summary
            else None,
            recommendation=response.recommendation.model_copy(deep=True),
            details={
                "configured_top_chunk_ids": self._chunk_ids(response.configured.results),
                "heuristic_top_chunk_ids": self._chunk_ids(response.heuristic.results),
                "provider_candidate_top_chunk_ids": self._chunk_ids(response.provider_candidate.results)
                if response.provider_candidate
                else [],
            },
        )
        try:
            self.repository.append(record)
        except Exception:
            return record
        return record

    def list_recent(
        self,
        *,
        auth_context: AuthContext,
        limit: int = 20,
        decision: str | None = None,
    ) -> list[RerankCanarySampleRecord]:
        records = self.repository.list_records(limit=limit)
        scoped_records = self._filter_records_by_scope(records=records, auth_context=auth_context)
        if decision is None:
            return scoped_records
        normalized_decision = decision.strip()
        if not normalized_decision:
            return scoped_records
        return [record for record in scoped_records if record.recommendation.decision == normalized_decision]

    def summarize(
        self,
        *,
        auth_context: AuthContext,
        limit: int = 100,
    ) -> RerankCanarySummary:
        records = self.list_recent(auth_context=auth_context, limit=limit)
        eligible_count = 0
        hold_count = 0
        provider_active_count = 0
        rollback_active_count = 0
        not_applicable_count = 0
        other_count = 0

        for record in records:
            decision = record.recommendation.decision
            if decision == "eligible":
                eligible_count += 1
            elif decision == "hold":
                hold_count += 1
            elif decision == "provider_active":
                provider_active_count += 1
            elif decision == "rollback_active":
                rollback_active_count += 1
            elif decision == "not_applicable":
                not_applicable_count += 1
            else:
                other_count += 1

        latest = records[0] if records else None
        last_eligible = next((item.occurred_at for item in records if item.recommendation.decision == "eligible"), None)
        return RerankCanarySummary(
            sample_size=len(records),
            eligible_count=eligible_count,
            hold_count=hold_count,
            provider_active_count=provider_active_count,
            rollback_active_count=rollback_active_count,
            not_applicable_count=not_applicable_count,
            other_count=other_count,
            latest_sample_id=latest.sample_id if latest else None,
            latest_decision=latest.recommendation.decision if latest else None,
            latest_message=latest.recommendation.message if latest else None,
            last_sample_at=latest.occurred_at if latest else None,
            last_eligible_at=last_eligible,
        )

    @staticmethod
    def _build_actor(auth_context: AuthContext | None) -> EventLogActor:
        user = getattr(auth_context, "user", None)
        if auth_context is None or user is None:
            return EventLogActor()
        return EventLogActor(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            username=user.username,
            role_id=user.role_id,
            department_id=user.department_id,
        )

    @staticmethod
    def _filter_records_by_scope(
        *,
        records: list[RerankCanarySampleRecord],
        auth_context: AuthContext,
    ) -> list[RerankCanarySampleRecord]:
        if auth_context.role.data_scope == "global":
            return records
        allowed_departments = set(auth_context.accessible_department_ids)
        return [record for record in records if record.actor.department_id in allowed_departments]

    @staticmethod
    def _chunk_ids(results: list[RetrievedChunk]) -> list[str]:
        return [item.chunk_id for item in results]


@lru_cache
def get_rerank_canary_service() -> RerankCanaryService:
    return RerankCanaryService()
