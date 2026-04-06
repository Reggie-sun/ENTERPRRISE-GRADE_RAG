from datetime import UTC, datetime
from functools import lru_cache
from math import ceil
from typing import Callable
from urllib.parse import urlparse

from fastapi import HTTPException, status
from redis import Redis

from ..core.config import Settings, get_settings
from ..schemas.auth import AuthContext
from ..schemas.event_log import EventLogCategory, EventLogRecord
from ..schemas.ops import (
    OpsCategorySummary,
    OpsRerankDecisionSummary,
    OpsQueueSummary,
    OpsRecentWindowSummary,
    OpsRerankUsageSummary,
    OpsRetrievalSummary,
    OpsRuntimeChannelSummary,
    OpsRuntimeGateSummary,
    OpsSummaryResponse,
)
from .document_service import DocumentService
from .event_log_service import EventLogService
from .health_service import HealthService
from .request_snapshot_service import RequestSnapshotService
from .request_trace_service import RequestTraceService
from .rerank_canary_service import RerankCanaryService
from .runtime_gate_service import RuntimeGateService, get_runtime_gate_service
from .system_config_service import SystemConfigService


def _coerce_redis_queue_length(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value.strip())
    raise RuntimeError("Redis LLEN returned a non-integer response.")


class OpsService:
    RERANK_PROMOTION_MIN_PROVIDER_SAMPLES = 5

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        health_service: HealthService | None = None,
        event_log_service: EventLogService | None = None,
        request_trace_service: RequestTraceService | None = None,
        request_snapshot_service: RequestSnapshotService | None = None,
        rerank_canary_service: RerankCanaryService | None = None,
        system_config_service: SystemConfigService | None = None,
        runtime_gate_service: RuntimeGateService | None = None,
        document_service: DocumentService | None = None,
        queue_probe: Callable[[], OpsQueueSummary] | None = None,
        recent_window_size: int = 200,
    ) -> None:
        self.settings = settings or get_settings()
        self.health_service = health_service or HealthService(self.settings)
        self.event_log_service = event_log_service or EventLogService(self.settings)
        self.request_trace_service = request_trace_service or RequestTraceService(self.settings)
        self.request_snapshot_service = request_snapshot_service or RequestSnapshotService(self.settings)
        self.rerank_canary_service = rerank_canary_service or RerankCanaryService(self.settings)
        self.system_config_service = system_config_service or SystemConfigService(self.settings)
        self.document_service = document_service or DocumentService(self.settings, event_log_service=self.event_log_service)
        self.runtime_gate_service = runtime_gate_service or (
            RuntimeGateService(self.settings, system_config_service=self.system_config_service)
            if settings is not None
            else get_runtime_gate_service()
        )
        self.queue_probe = queue_probe or self._probe_queue
        self.recent_window_size = recent_window_size

    def get_summary(self, *, auth_context: AuthContext) -> OpsSummaryResponse:
        self._ensure_workspace_access(auth_context)
        records = self._filter_records_by_scope(
            records=self.event_log_service.list_recent(limit=self.recent_window_size),
            auth_context=auth_context,
        )
        health = self.health_service.get_snapshot()
        rerank_usage = self._build_rerank_usage(records)
        retrieval_summary = self._build_retrieval_summary(records)
        return OpsSummaryResponse(
            checked_at=datetime.now(UTC),
            health=health,
            queue=self.queue_probe(),
            runtime_gate=self._build_runtime_gate_summary(),
            recent_window=self._build_recent_window(records),
            rerank_usage=rerank_usage,
            rerank_decision=self._build_rerank_decision(
                health_reranker=health.reranker,
                usage=rerank_usage,
            ),
            rerank_canary=self.rerank_canary_service.summarize(auth_context=auth_context, limit=self.recent_window_size),
            retrieval=retrieval_summary,
            stuck_ingest_jobs=self.document_service.list_stuck_ingest_jobs(auth_context=auth_context, limit=5),
            categories=self._build_category_summaries(records),
            recent_failures=[record for record in records if record.outcome == "failed"][:5],
            recent_degraded=[record for record in records if record.downgraded_from][:5],
            recent_traces=self.request_trace_service.list_recent(auth_context=auth_context, limit=5),
            recent_snapshots=self.request_snapshot_service.list_recent(auth_context=auth_context, limit=5),
            config=self.system_config_service.get_effective_config(),
        )

    def _build_runtime_gate_summary(self) -> OpsRuntimeGateSummary:
        snapshot = self.runtime_gate_service.get_snapshot()
        return OpsRuntimeGateSummary(
            acquire_timeout_ms=snapshot.acquire_timeout_ms,
            busy_retry_after_seconds=snapshot.busy_retry_after_seconds,
            per_user_online_max_inflight=snapshot.per_user_online_max_inflight,
            active_users=snapshot.active_users,
            max_user_inflight=snapshot.max_user_inflight,
            channels=[
                OpsRuntimeChannelSummary(
                    channel=item.channel,
                    inflight=item.inflight,
                    limit=item.limit,
                    available_slots=item.available_slots,
                )
                for item in snapshot.channels
            ],
        )

    @staticmethod
    def _ensure_workspace_access(auth_context: AuthContext) -> None:
        if auth_context.user.role_id == "employee":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to runtime operations.",
            )

    @staticmethod
    def _filter_records_by_scope(
        *,
        records: list[EventLogRecord],
        auth_context: AuthContext,
    ) -> list[EventLogRecord]:
        if auth_context.role.data_scope == "global":
            return records
        allowed_departments = set(auth_context.accessible_department_ids)
        return [record for record in records if record.actor.department_id in allowed_departments]

    def _probe_queue(self) -> OpsQueueSummary:
        broker_url = self.settings.celery_broker_url
        parsed = urlparse(broker_url)
        if parsed.scheme not in {"redis", "rediss"}:
            return OpsQueueSummary(
                available=False,
                ingest_queue=self.settings.celery_ingest_queue,
                error="Only redis-backed queue backlog probing is supported.",
            )

        try:
            client = Redis.from_url(
                broker_url,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
                retry_on_timeout=False,
            )
            client.ping()
            backlog = _coerce_redis_queue_length(client.llen(self.settings.celery_ingest_queue))
            return OpsQueueSummary(
                available=True,
                ingest_queue=self.settings.celery_ingest_queue,
                backlog=backlog,
            )
        except Exception as exc:
            return OpsQueueSummary(
                available=False,
                ingest_queue=self.settings.celery_ingest_queue,
                error=str(exc),
            )

    @staticmethod
    def _build_recent_window(records: list[EventLogRecord]) -> OpsRecentWindowSummary:
        durations = sorted(record.duration_ms for record in records if record.duration_ms is not None)
        return OpsRecentWindowSummary(
            sample_size=len(records),
            failed_count=sum(1 for record in records if record.outcome == "failed"),
            timeout_count=sum(1 for record in records if record.timeout_flag),
            downgraded_count=sum(1 for record in records if record.downgraded_from),
            duration_count=len(durations),
            duration_p50_ms=OpsService._percentile(durations, 50),
            duration_p95_ms=OpsService._percentile(durations, 95),
            duration_p99_ms=OpsService._percentile(durations, 99),
        )

    @staticmethod
    def _build_rerank_usage(records: list[EventLogRecord]) -> OpsRerankUsageSummary:
        relevant_records = [record for record in records if record.category in {"chat", "sop_generation"}]
        provider_count = 0
        heuristic_count = 0
        skipped_count = 0
        document_preview_count = 0
        fallback_profile_count = 0
        unknown_count = 0
        other_count = 0

        for record in relevant_records:
            strategy = (record.rerank_strategy or "").strip().lower()
            if strategy == "provider":
                provider_count += 1
            elif strategy == "heuristic":
                heuristic_count += 1
            elif strategy == "skipped":
                skipped_count += 1
            elif strategy == "document_preview":
                document_preview_count += 1
            elif strategy == "fallback_profile":
                fallback_profile_count += 1
            elif not strategy:
                unknown_count += 1
            else:
                other_count += 1

        def _last_seen(target_strategy: str) -> datetime | None:
            return next(
                (
                    record.occurred_at
                    for record in relevant_records
                    if (record.rerank_strategy or "").strip().lower() == target_strategy
                ),
                None,
            )

        return OpsRerankUsageSummary(
            sample_size=len(relevant_records),
            provider_count=provider_count,
            heuristic_count=heuristic_count,
            skipped_count=skipped_count,
            document_preview_count=document_preview_count,
            fallback_profile_count=fallback_profile_count,
            unknown_count=unknown_count,
            other_count=other_count,
            last_provider_at=_last_seen("provider"),
            last_heuristic_at=_last_seen("heuristic"),
        )

    @classmethod
    def _build_rerank_decision(cls, *, health_reranker: object, usage: OpsRerankUsageSummary) -> OpsRerankDecisionSummary:
        provider = str(getattr(health_reranker, "provider", "") or "").strip().lower()
        default_strategy = str(getattr(health_reranker, "default_strategy", "") or "").strip().lower()
        effective_strategy = str(getattr(health_reranker, "effective_strategy", "") or "").strip().lower()
        ready = bool(getattr(health_reranker, "ready", False))
        lock_active = bool(getattr(health_reranker, "lock_active", False))
        lock_source = getattr(health_reranker, "lock_source", None)
        detail = str(getattr(health_reranker, "detail", "") or "").strip()
        min_provider_samples = cls.RERANK_PROMOTION_MIN_PROVIDER_SAMPLES

        if provider == "heuristic":
            return OpsRerankDecisionSummary(
                decision="not_applicable",
                message="当前未配置模型级 rerank provider，继续保持 heuristic 默认。",
                min_provider_samples=min_provider_samples,
                provider_sample_count=usage.provider_count,
                heuristic_sample_count=usage.heuristic_count,
            )

        if default_strategy == "provider":
            if lock_active or not ready or effective_strategy != "provider":
                suffix = f" 当前锁定来源：{lock_source}。" if lock_active and lock_source else ""
                return OpsRerankDecisionSummary(
                    decision="rollback_to_heuristic",
                    message=f"provider 已设为默认，但当前未稳定生效，建议先回滚到 heuristic。{detail}{suffix}".strip(),
                    min_provider_samples=min_provider_samples,
                    provider_sample_count=usage.provider_count,
                    heuristic_sample_count=usage.heuristic_count,
                    should_rollback_to_heuristic=True,
                )
            if usage.provider_count < min_provider_samples:
                return OpsRerankDecisionSummary(
                    decision="observe_provider",
                    message=f"provider 已作为默认主路径运行，但最近窗口只有 {usage.provider_count} 条 provider 样本，先继续观察稳定性。",
                    min_provider_samples=min_provider_samples,
                    provider_sample_count=usage.provider_count,
                    heuristic_sample_count=usage.heuristic_count,
                )
            return OpsRerankDecisionSummary(
                decision="keep_provider",
                message=f"provider 已稳定作为默认主路径运行，最近窗口已有 {usage.provider_count} 条 provider 样本，可继续保持。",
                min_provider_samples=min_provider_samples,
                provider_sample_count=usage.provider_count,
                heuristic_sample_count=usage.heuristic_count,
            )

        if lock_active or not ready:
            suffix = f" 当前锁定来源：{lock_source}。" if lock_active and lock_source else ""
            return OpsRerankDecisionSummary(
                decision="keep_heuristic",
                message=f"provider 当前未 ready 或处于锁定窗口，继续保持 heuristic 默认。{detail}{suffix}".strip(),
                min_provider_samples=min_provider_samples,
                provider_sample_count=usage.provider_count,
                heuristic_sample_count=usage.heuristic_count,
            )

        if usage.provider_count == 0:
            return OpsRerankDecisionSummary(
                decision="run_canary",
                message="provider 当前可用，但最近窗口还没有真实 provider 流量样本，先做 canary 验证，再决定是否提升为默认。",
                min_provider_samples=min_provider_samples,
                provider_sample_count=usage.provider_count,
                heuristic_sample_count=usage.heuristic_count,
            )

        if usage.provider_count < min_provider_samples:
            return OpsRerankDecisionSummary(
                decision="observe_canary",
                message=f"provider 当前可用，最近窗口已有 {usage.provider_count} 条 provider 样本，但还没达到 {min_provider_samples} 条样本阈值，继续观察。",
                min_provider_samples=min_provider_samples,
                provider_sample_count=usage.provider_count,
                heuristic_sample_count=usage.heuristic_count,
            )

        return OpsRerankDecisionSummary(
            decision="promote_to_provider",
            message=f"provider 当前可用且最近窗口已有 {usage.provider_count} 条 provider 样本，达到 {min_provider_samples} 条阈值，适合把 default_strategy 长期开到 provider。",
            min_provider_samples=min_provider_samples,
            provider_sample_count=usage.provider_count,
            heuristic_sample_count=usage.heuristic_count,
            should_promote_to_provider=True,
        )

    @staticmethod
    def _build_retrieval_summary(
        records: list[EventLogRecord],
    ) -> OpsRetrievalSummary:
        """聚合最近检索事件日志的统计维度。"""
        retrieval_records = [r for r in records if r.category == "retrieval"]
        if not retrieval_records:
            return OpsRetrievalSummary()

        qdrant_count = 0
        hybrid_count = 0
        supplemental_triggered_count = 0
        ocr_filtered_count = 0
        permission_filtered_count = 0
        candidate_counts: list[int] = []
        final_counts: list[int] = []
        query_type_counter: dict[str, int] = {}

        for record in retrieval_records:
            details = record.details or {}
            mode = str(details.get("retrieval_mode", ""))
            if mode == "hybrid":
                hybrid_count += 1
            else:
                qdrant_count += 1
            if details.get("supplemental_triggered"):
                supplemental_triggered_count += 1
            filters = details.get("filter_counts", details.get("filters", {}))
            if isinstance(filters, dict):
                ocr_filtered_count += int(filters.get("ocr_quality", 0))
                permission_filtered_count += int(filters.get("permission", 0))
            recall = details.get("recall_candidates")
            recall_counts = details.get("recall_counts", {})
            if recall is None and isinstance(recall_counts, dict):
                recall = recall_counts.get("total_candidates")
            if isinstance(recall, (int, float)):
                candidate_counts.append(int(recall))
            final = details.get("final_result_count", details.get("final_results"))
            if isinstance(final, (int, float)):
                final_counts.append(int(final))
            qt = details.get("query_type")
            if isinstance(qt, str) and qt:
                query_type_counter[qt] = query_type_counter.get(qt, 0) + 1

        sample_size = len(retrieval_records)
        sorted_qt = sorted(query_type_counter.items(), key=lambda item: item[1], reverse=True)
        return OpsRetrievalSummary(
            sample_size=sample_size,
            qdrant_count=qdrant_count,
            hybrid_count=hybrid_count,
            supplemental_triggered_count=supplemental_triggered_count,
            supplemental_trigger_rate=round(supplemental_triggered_count / sample_size, 3) if sample_size else 0.0,
            ocr_filtered_count=ocr_filtered_count,
            permission_filtered_count=permission_filtered_count,
            average_candidate_count=round(sum(candidate_counts) / len(candidate_counts), 1) if candidate_counts else 0.0,
            average_final_result_count=round(sum(final_counts) / len(final_counts), 1) if final_counts else 0.0,
            top_query_types=[qt for qt, _ in sorted_qt[:5]],
        )

    @staticmethod
    def _build_category_summaries(records: list[EventLogRecord]) -> list[OpsCategorySummary]:
        categories: tuple[EventLogCategory, ...] = ("chat", "document", "retrieval", "sop_generation")
        summaries: list[OpsCategorySummary] = []
        for category in categories:
            category_records = [record for record in records if record.category == category]
            failed_records = [record for record in category_records if record.outcome == "failed"]
            summaries.append(
                OpsCategorySummary(
                    category=category,
                    total=len(category_records),
                    failed_count=len(failed_records),
                    timeout_count=sum(1 for record in category_records if record.timeout_flag),
                    downgraded_count=sum(1 for record in category_records if record.downgraded_from),
                    last_event_at=category_records[0].occurred_at if category_records else None,
                    last_failed_at=failed_records[0].occurred_at if failed_records else None,
                )
            )
        return summaries

    @staticmethod
    def _percentile(values: list[int], percentile: int) -> int | None:
        if not values:
            return None
        rank = max(0, ceil((percentile / 100) * len(values)) - 1)
        return values[min(rank, len(values) - 1)]


@lru_cache
def get_ops_service() -> OpsService:
    return OpsService()
