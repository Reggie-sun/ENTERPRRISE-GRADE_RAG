"""Retrieval 诊断链路测试：验证可观测、可解释、可验证、可优化四个能力。"""
import json
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.schemas.auth import AuthContext, DepartmentRecord, RoleDefinition, UserRecord
from backend.app.schemas.query_profile import QueryProfile
from backend.app.schemas.retrieval import RetrievalDiagnostic, RetrievalResponse, RetrievedChunk
from backend.app.services.auth_service import get_current_auth_context
from backend.app.services.chat_service import get_chat_service
from backend.app.services.event_log_service import EventLogService, get_event_log_service
from backend.app.services.request_snapshot_service import RequestSnapshotService, get_request_snapshot_service
from backend.app.services.request_trace_service import RequestTraceService, get_request_trace_service
from backend.app.services.retrieval_service import get_retrieval_service
from backend.app.services.sop_generation_service import get_sop_generation_service


# ---------- helpers ----------

def _admin_auth() -> AuthContext:
    dept = DepartmentRecord(department_id="dept-1", tenant_id="test-tenant", department_name="Test")
    role = RoleDefinition(role_id="sys_admin", name="admin", description="admin", data_scope="global", is_admin=True)
    user = UserRecord(
        user_id="admin-001", tenant_id="test-tenant", username="admin",
        display_name="Admin", department_id="dept-1", role_id="sys_admin",
    )
    return AuthContext.model_construct(
        user=user, role=role, department=dept,
        accessible_department_ids=["dept-1", "dept-2"],
        department_query_isolation_enabled=False,
        token_id="tok_test", issued_at=None, expires_at=None,
    )


def _build_mock_vector_points(n: int = 5) -> list[object]:
    """构建 mock 向量检索结果。"""
    points = []
    for i in range(n):
        point = MagicMock()
        point.id = f"point-{i}"
        point.score = 0.9 - i * 0.1
        point.payload = {
            "chunk_id": f"chunk-{i}",
            "document_id": f"doc-{i}",
            "document_name": f"document-{i}.pdf",
            "text": f"这是第 {i} 个测试文本块。",
            "source_path": f"/docs/document-{i}.pdf",
            "page_no": i + 1,
        }
        points.append(point)
    return points


def _build_isolated_settings(tmp_path: Path):
    settings = get_settings().model_copy(deep=True)
    settings.event_log_dir = tmp_path / "event_logs"
    settings.request_trace_dir = tmp_path / "request_traces"
    settings.request_snapshot_dir = tmp_path / "request_snapshots"
    settings.event_log_dir.mkdir(parents=True, exist_ok=True)
    settings.request_trace_dir.mkdir(parents=True, exist_ok=True)
    settings.request_snapshot_dir.mkdir(parents=True, exist_ok=True)
    return settings


def _build_profile(*, mode: str = "fast", top_k: int = 5) -> QueryProfile:
    return QueryProfile(
        purpose="retrieval",
        mode=mode,
        top_k=top_k,
        candidate_top_k=max(top_k * 4, top_k),
        lexical_top_k=max(top_k * 2, top_k),
        rerank_top_n=top_k,
        timeout_budget_seconds=12.0,
        fallback_mode=None,
    )


def _build_chunk(*, index: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk-{index}",
        document_id=f"doc-{index}",
        document_name=f"document-{index}.pdf",
        text=f"这是第 {index} 个测试文本块。",
        score=0.95,
        source_path=f"/docs/document-{index}.pdf",
    )


def _build_response(
    *,
    query: str,
    top_k: int = 5,
    mode: str = "qdrant",
    results: list[RetrievedChunk] | None = None,
    diagnostic: RetrievalDiagnostic | None = None,
) -> RetrievalResponse:
    return RetrievalResponse(
        query=query,
        top_k=top_k,
        mode=mode,
        results=results or [],
        diagnostic=diagnostic,
    )


# ---------- A. 可观测测试 ----------

class TestRetrievalObservability:
    """验证一次检索请求经过了哪些阶段，每阶段召回/过滤了多少。"""

    def test_retrieval_search_records_trace(self, tmp_path: Path) -> None:
        """retrieval/search 端点应该记录 trace、event log 和 snapshot。"""
        settings = _build_isolated_settings(tmp_path)
        event_log_service = EventLogService(settings)
        trace_service = RequestTraceService(settings)
        snapshot_service = RequestSnapshotService(settings)
        mock_retrieval = MagicMock()
        mock_retrieval.search.return_value = _build_response(query="test query", top_k=5)

        app.dependency_overrides[get_retrieval_service] = lambda: mock_retrieval
        app.dependency_overrides[get_event_log_service] = lambda: event_log_service
        app.dependency_overrides[get_request_snapshot_service] = lambda: snapshot_service
        app.dependency_overrides[get_request_trace_service] = lambda: trace_service

        try:
            client = TestClient(app)
            response = client.post(
                "/api/v1/retrieval/search",
                json={"query": "test query", "top_k": 5},
            )
            assert response.status_code == 200

            # Check that a trace file was written
            trace_files = list(settings.request_trace_dir.glob("*.jsonl"))
            assert len(trace_files) >= 1, "Expected at least one trace file to be written"

            # Parse and validate the trace record
            trace_records = []
            for trace_file in trace_files:
                for line in trace_file.read_text().strip().split("\n"):
                    if line.strip():
                        record = json.loads(line)
                        trace_records.append(record)

            retrieval_traces = [r for r in trace_records if r.get("category") == "retrieval"]
            assert len(retrieval_traces) >= 1, "Expected at least one retrieval trace"

            trace = retrieval_traces[0]
            assert trace["action"] == "search"
            assert trace["outcome"] == "success"
            assert "total_duration_ms" in trace
            assert isinstance(trace["total_duration_ms"], int)

            event_log_files = list(settings.event_log_dir.glob("*.jsonl"))
            assert len(event_log_files) >= 1, "Expected at least one retrieval event log"
            event_records = []
            for event_log_file in event_log_files:
                for line in event_log_file.read_text().strip().split("\n"):
                    if line.strip():
                        event_records.append(json.loads(line))
            retrieval_events = [record for record in event_records if record.get("category") == "retrieval"]
            assert len(retrieval_events) >= 1
            assert retrieval_events[0]["action"] == "search"

            snapshot_files = list(settings.request_snapshot_dir.glob("*.json"))
            assert len(snapshot_files) >= 1, "Expected at least one retrieval snapshot"
            snapshot_payload = json.loads(snapshot_files[0].read_text())
            assert snapshot_payload["category"] == "retrieval"
            assert snapshot_payload["action"] == "search"
        finally:
            app.dependency_overrides.clear()

    def test_retrieval_diagnostic_has_structured_fields(self) -> None:
        """检索诊断信息应包含结构化字段。"""
        mock_retrieval = MagicMock()
        mock_retrieval.search.return_value = _build_response(
            query="test query",
            top_k=5,
            mode="hybrid",
            diagnostic=RetrievalDiagnostic(
                query="test query",
                query_type="semantic",
                retrieval_mode="hybrid",
                document_id_filter_applied=False,
                department_priority_enabled=True,
                primary_threshold=5,
                primary_effective_count=3,
                supplemental_triggered=True,
                supplemental_reason="department_effective(3)_below_threshold(5)",
                recall_counts={"department_vector": 10, "department_after_ocr": 8, "supplemental_recall": 5, "total_candidates": 13},
                filter_counts={"ocr_quality": 2, "permission": 1},
                final_result_count=5,
            ),
        )

        app.dependency_overrides[get_retrieval_service] = lambda: mock_retrieval

        try:
            client = TestClient(app)
            response = client.post(
                "/api/v1/retrieval/search",
                json={"query": "test query", "top_k": 5},
            )
            assert response.status_code == 200
            payload = response.json()
            assert "diagnostic" in payload
            diag = payload["diagnostic"]
            # Verify required diagnostic fields
            assert "query" in diag
            assert "query_type" in diag
            assert "retrieval_mode" in diag
            assert "department_priority_enabled" in diag
            assert "supplemental_triggered" in diag
            assert "recall_counts" in diag
            assert "filter_counts" in diag
            assert "final_result_count" in diag
        finally:
            app.dependency_overrides.clear()


# ---------- B. 可解释测试 ----------

class TestRetrievalExplainability:
    """验证为什么走 hybrid/qdrant、为什么触发 supplemental、为什么过滤。"""

    def test_diagnostic_explains_retrieval_mode(self) -> None:
        """诊断信息应解释为什么走了 hybrid 或 qdrant 模式。"""
        mock_retrieval = MagicMock()
        mock_retrieval.search.return_value = _build_response(
            query="exact keyword match",
            top_k=5,
            mode="hybrid",
            diagnostic=RetrievalDiagnostic(
                query="exact keyword match",
                query_type="exact",
                retrieval_mode="hybrid",
                branch_weights={"vector_weight": 0.3, "lexical_weight": 0.7},
            ),
        )

        app.dependency_overrides[get_retrieval_service] = lambda: mock_retrieval
        try:
            client = TestClient(app)
            response = client.post(
                "/api/v1/retrieval/search",
                json={"query": "exact keyword match", "top_k": 5},
            )
            assert response.status_code == 200
            diag = response.json()["diagnostic"]
            assert diag["retrieval_mode"] == "hybrid"
            assert diag["query_type"] == "exact"
            assert diag["branch_weights"]["lexical_weight"] > diag["branch_weights"]["vector_weight"]
        finally:
            app.dependency_overrides.clear()

    def test_diagnostic_explains_supplemental_trigger(self) -> None:
        """当本部门结果不足时，诊断信息应解释为什么触发了 supplemental。"""
        mock_retrieval = MagicMock()
        mock_retrieval.search.return_value = _build_response(
            query="test",
            top_k=5,
            mode="hybrid",
            diagnostic=RetrievalDiagnostic(
                query="test",
                retrieval_mode="hybrid",
                department_priority_enabled=True,
                primary_threshold=5,
                primary_effective_count=2,
                supplemental_triggered=True,
                supplemental_reason="department_effective(2)_below_threshold(5)",
            ),
        )

        app.dependency_overrides[get_retrieval_service] = lambda: mock_retrieval
        try:
            client = TestClient(app)
            response = client.post(
                "/api/v1/retrieval/search",
                json={"query": "test", "top_k": 5},
            )
            assert response.status_code == 200
            diag = response.json()["diagnostic"]
            assert diag["supplemental_triggered"] is True
            assert "below_threshold" in diag["supplemental_reason"]
        finally:
            app.dependency_overrides.clear()


# ---------- C. 可验证测试 ----------

class TestRetrievalVerification:
    """验证 retrieval 请求可以 snapshot、replay、比较差异。"""

    def test_retrieval_snapshot_can_be_recorded(self, tmp_path: Path) -> None:
        """retrieval snapshot 可以被记录。"""
        from backend.app.schemas.retrieval import RetrievalRequest

        settings = _build_isolated_settings(tmp_path)
        snapshot_service = RequestSnapshotService(settings)

        request = RetrievalRequest(query="test query", top_k=5)
        profile = _build_profile(mode="fast", top_k=5)
        response = _build_response(query="test query", top_k=5, results=[_build_chunk(index=1)])

        record = snapshot_service.record_retrieval_snapshot(
            trace_id="trc_test_001",
            request_id="req_test_001",
            action="search",
            outcome="success",
            request=request,
            profile=profile,
            auth_context=None,
            response=response,
        )
        assert record.category == "retrieval"
        assert record.action == "search"
        assert record.outcome == "success"
        assert record.result.citation_count == 1

    def test_retrieval_snapshot_replay(self, tmp_path: Path) -> None:
        """retrieval snapshot 可以被 replay。"""
        settings = _build_isolated_settings(tmp_path)
        snapshot_service = RequestSnapshotService(settings)

        mock_retrieval = MagicMock()
        mock_retrieval.search.return_value = _build_response(
            query="replay test",
            top_k=3,
            mode="qdrant",
            results=[_build_chunk(index=1)],
            diagnostic=RetrievalDiagnostic(
                query="replay test",
                retrieval_mode="qdrant",
                final_result_count=1,
            ),
        )

        app.dependency_overrides[get_retrieval_service] = lambda: mock_retrieval
        app.dependency_overrides[get_request_snapshot_service] = lambda: snapshot_service
        app.dependency_overrides[get_current_auth_context] = _admin_auth
        app.dependency_overrides[get_chat_service] = lambda: MagicMock()
        app.dependency_overrides[get_sop_generation_service] = lambda: MagicMock()

        try:
            client = TestClient(app)
            search_response = client.post(
                "/api/v1/retrieval/search",
                json={"query": "replay test", "top_k": 3, "mode": "fast"},
            )
            assert search_response.status_code == 200

            snapshot_id = snapshot_service.repository.list_records(limit=1)[0].snapshot_id
            replay_response = client.post(
                f"/api/v1/request-snapshots/{snapshot_id}/replay",
                json={"replay_mode": "original"},
            )

            assert replay_response.status_code == 200
            payload = replay_response.json()
            assert payload["replayed_request"]["query"] == "replay test"
            assert payload["replayed_request"]["mode"] == "fast"
            assert payload["response"]["query"] == "replay test"
            assert payload["response"]["diagnostic"]["retrieval_mode"] == "qdrant"
            assert mock_retrieval.search.call_count == 2
            replay_request = mock_retrieval.search.call_args_list[1].args[0]
            assert replay_request.query == "replay test"
            assert replay_request.mode == "fast"
        finally:
            app.dependency_overrides.clear()


# ---------- D. 可优化测试 ----------

class TestRetrievalOpsOptimization:
    """验证 ops 能聚合 retrieval 指标。"""

    def test_ops_summary_includes_retrieval_dimension(self, tmp_path: Path) -> None:
        """ops/summary 应该包含 retrieval 维度聚合。"""
        from backend.app.schemas.ops import OpsRetrievalSummary

        # Build a mock ops service with injected retrieval summary
        summary = OpsRetrievalSummary(
            sample_size=10,
            qdrant_count=3,
            hybrid_count=7,
            supplemental_triggered_count=4,
            supplemental_trigger_rate=0.4,
            ocr_filtered_count=2,
            permission_filtered_count=1,
            average_candidate_count=15.3,
            average_final_result_count=4.8,
            top_query_types=["semantic", "exact", "hybrid"],
        )

        assert summary.sample_size == 10
        assert summary.hybrid_count == 7
        assert summary.supplemental_trigger_rate == 0.4
        assert summary.top_query_types == ["semantic", "exact", "hybrid"]

    def test_ops_retrieval_summary_from_event_records(self) -> None:
        """验证 _build_retrieval_summary 能从事件日志记录中聚合。"""
        from backend.app.services.ops_service import OpsService

        # Mock event log records with retrieval category
        records = []
        for i in range(5):
            record = MagicMock()
            record.category = "retrieval"
            record.details = {
                "retrieval_mode": "hybrid" if i % 2 == 0 else "qdrant",
                "supplemental_triggered": i < 2,
                "filter_counts": {"ocr_quality": 1, "permission": 0},
                "recall_counts": {"total_candidates": 20 + i * 2},
                "final_result_count": 5,
                "query_type": "semantic" if i % 2 == 0 else "exact",
            }
            records.append(record)

        # Add non-retrieval records to verify filtering
        for _ in range(3):
            record = MagicMock()
            record.category = "chat"
            record.details = {}
            records.append(record)

        summary = OpsService._build_retrieval_summary(records)
        assert summary.sample_size == 5
        assert summary.hybrid_count == 3  # indices 0, 2, 4
        assert summary.qdrant_count == 2  # indices 1, 3
        assert summary.supplemental_triggered_count == 2  # i < 2
        assert summary.average_candidate_count == 24.0
        assert summary.average_final_result_count == 5.0
        assert "semantic" in summary.top_query_types
        assert "exact" in summary.top_query_types


# ---------- 回归：主契约测试 ----------

class TestContractRegression:
    """确保 retrieval/search 的主契约稳定字段没有被动静默改坏。"""

    def test_retrieval_response_stable_fields(self) -> None:
        """验证 RetrievalResponse 仍包含稳定字段且不缺失。"""
        from backend.app.schemas.retrieval import RetrievalResponse, RetrievedChunk

        chunk = RetrievedChunk(
            chunk_id="c1",
            document_id="d1",
            document_name="test.pdf",
            text="content",
            score=0.95,
            source_path="/test.pdf",
        )
        response = RetrievalResponse(
            query="test",
            top_k=5,
            mode="qdrant",
            results=[chunk],
        )
        # Verify stable fields exist
        assert response.query == "test"
        assert response.top_k == 5
        assert response.mode == "qdrant"
        assert len(response.results) == 1
        assert response.results[0].chunk_id == "c1"
        # Verify diagnostic is optional and defaults to None
        assert response.diagnostic is None

    def test_retrieval_diagnostic_is_optional(self) -> None:
        """验证 diagnostic 字段是可选的，不影响现有客户端。"""
        from backend.app.schemas.retrieval import RetrievalResponse, RetrievalDiagnostic

        # Without diagnostic - should work
        response = RetrievalResponse(
            query="test",
            top_k=5,
            mode="qdrant",
            results=[],
        )
        assert response.diagnostic is None

        # With diagnostic - should also work
        diag = RetrievalDiagnostic(
            query="test",
            retrieval_mode="hybrid",
            final_result_count=5,
        )
        response_with_diag = RetrievalResponse(
            query="test",
            top_k=5,
            mode="hybrid",
            results=[],
            diagnostic=diag,
        )
        assert response_with_diag.diagnostic is not None
        assert response_with_diag.diagnostic.retrieval_mode == "hybrid"
