import json  # 导入 json，用于解析 SSE 事件数据。
from pathlib import Path  # 导入 Path，方便创建测试目录路径。
from types import SimpleNamespace

from fastapi.testclient import TestClient  # 导入 FastAPI 测试客户端。
import httpx  # 导入 httpx，用于构造 OpenAI 兼容接口错误响应。
import pytest

from backend.app.core.config import Settings, ensure_data_directories  # 导入配置对象和目录初始化函数。
from backend.app.main import app  # 导入应用实例。
from backend.app.schemas.auth import AuthContext, DepartmentRecord, RoleDefinition, UserRecord
from backend.app.schemas.retrieval import RetrievalRequest, RetrievalResponse, RetrievedChunk  # 导入检索请求/响应模型，用于直接调用服务层测试过滤逻辑。
from backend.app.services.chat_service import ChatService, get_chat_service  # 导入问答服务和依赖入口。
from backend.app.services.document_service import DocumentService, get_document_service  # 导入文档服务和依赖入口。
from backend.app.services.runtime_gate_service import RuntimeGateBusyError, RuntimeGateService
from backend.app.services.retrieval_service import RetrievalService, get_retrieval_service  # 导入检索服务和依赖入口。
from backend.app.services.system_config_service import SystemConfigService
from backend.tests.test_document_ingestion import MINIMAL_PNG_BYTES, build_minimal_docx_bytes


def parse_sse_events(raw_stream: str) -> list[tuple[str, dict[str, object]]]:  # 解析 text/event-stream 文本为结构化事件列表。
    events: list[tuple[str, dict[str, object]]] = []
    for block in raw_stream.split("\n\n"):  # SSE 每个事件块以空行分隔。
        if not block.strip():
            continue
        event_name = ""
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            elif line.startswith("data: "):
                data_lines.append(line[len("data: ") :])
        if not event_name or not data_lines:
            continue
        events.append((event_name, json.loads("\n".join(data_lines))))
    return events


def build_test_settings(tmp_path: Path) -> Settings:  # 构造 retrieval/chat 集成测试专用配置。
    data_dir = tmp_path / "data"  # 定义测试数据根目录。
    return Settings(  # 返回测试配置对象。
        app_name="Enterprise-grade RAG API Test",  # 设置测试应用名。
        app_env="test",  # 指定测试环境。
        debug=True,  # 开启调试模式，便于排查失败原因。
        qdrant_url=str(tmp_path / "qdrant_db"),  # 使用本地路径模式，让不同服务实例共享同一份 Qdrant 数据。
        qdrant_collection="enterprise_rag_v1_test",  # 使用测试 collection。
        postgres_metadata_enabled=False,  # 测试中强制关闭 PostgreSQL 元数据，避免受本机 .env 污染导致外部连库。
        postgres_metadata_dsn=None,  # 显式清空 DSN，确保不会误连真实环境数据库。
        llm_provider="mock",  # 生成阶段使用 mock，避免依赖真实 LLM 服务。
        llm_base_url="http://llm.test/v1",  # OpenAI 兼容 LLM 地址占位。
        llm_model="Qwen/Qwen2.5-7B-Instruct",  # OpenAI 兼容模型名称占位。
        ollama_base_url="http://embedding.test",  # 生成服务地址占位。
        reranker_provider="heuristic",  # rerank 使用启发式 provider。
        embedding_provider="mock",  # 使用 mock embedding，避免外部依赖。
        embedding_base_url="http://embedding.test",  # embedding 地址占位。
        embedding_model="BAAI/bge-m3",  # embedding 模型占位。
        data_dir=data_dir,  # 配置数据根目录。
        upload_dir=data_dir / "uploads",  # 配置上传目录。
        parsed_dir=data_dir / "parsed",  # 配置解析文本目录。
        chunk_dir=data_dir / "chunks",  # 配置 chunk 目录。
        ocr_artifact_dir=data_dir / "ocr_artifacts",  # OCR artifact 目录隔离到测试目录，避免写到仓库根 data。
        document_dir=data_dir / "documents",  # 配置 document 元数据目录。
        job_dir=data_dir / "jobs",  # 配置 job 元数据目录。
        event_log_dir=data_dir / "event_logs",  # 事件日志目录隔离到测试目录，避免读取真实运行日志。
        request_trace_dir=data_dir / "request_traces",  # 请求 trace 目录隔离到测试目录，避免受仓库根 data 污染。
        request_snapshot_dir=data_dir / "request_snapshots",  # 请求快照目录隔离到测试目录。
        system_config_path=data_dir / "system_config.json",  # 系统配置真源隔离到测试目录，避免真实 model route 干扰测试。
    )


class _FakeRuntimeGateLease:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


class _FakeRuntimeGateService:
    def __init__(self, *, outcomes: dict[str, list[bool]]) -> None:
        self.outcomes = {channel: list(items) for channel, items in outcomes.items()}
        self.calls: list[tuple[str, int | None, str | None]] = []

    def acquire_with_reason(self, channel: str, *, timeout_ms: int | None = None, owner_key: str | None = None):
        self.calls.append((channel, timeout_ms, owner_key))
        items = self.outcomes.setdefault(channel, [True])
        allowed = items.pop(0) if items else True
        if not allowed:
            return None, "channel_limit"
        return _FakeRuntimeGateLease(), None

    def acquire(self, channel: str, *, timeout_ms: int | None = None):
        lease, _ = self.acquire_with_reason(channel, timeout_ms=timeout_ms)
        return lease


class _FakeRetrievalService:
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results

    def search(self, request, *, auth_context=None):
        return RetrievalResponse(query=request.query, top_k=request.top_k or 0, mode="fake", results=self.results)


def _build_auth_context(
    role_id: str = "department_admin",
    department_ids: list[str] | None = None,
    *,
    user_id: str = "user_test",
    username: str = "test.user",
) -> AuthContext:
    from datetime import datetime, timedelta, timezone

    effective_department_ids = department_ids or ["dept_digitalization"]
    department = DepartmentRecord(
        department_id=effective_department_ids[0],
        tenant_id="wl",
        department_name="数字化部",
    )
    role = RoleDefinition(
        role_id=role_id,  # type: ignore[arg-type]
        name=role_id,
        description=role_id,
        data_scope="global" if role_id == "sys_admin" else "department",
        is_admin=role_id != "employee",
    )
    user = UserRecord(
        user_id=user_id,
        tenant_id="wl",
        username=username,
        display_name="Test User",
        department_id=department.department_id,
        role_id=role_id,  # type: ignore[arg-type]
    )
    issued_at = datetime.now(timezone.utc)
    return AuthContext(
        user=user,
        role=role,
        department=department,
        accessible_department_ids=effective_department_ids,
        token_id="token-test",
        issued_at=issued_at,
        expires_at=issued_at + timedelta(hours=1),
    )


def test_retrieval_search_returns_real_qdrant_chunks(tmp_path: Path) -> None:  # 验证检索接口返回真实 Qdrant 结果而不是占位文本。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    document_service = DocumentService(settings)  # 创建文档服务实例。
    retrieval_service = RetrievalService(settings)  # 创建检索服务实例。
    client = TestClient(app)  # 创建测试客户端。

    app.dependency_overrides[get_document_service] = lambda: document_service  # 覆盖文档服务依赖。
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service  # 覆盖检索服务依赖。
    try:  # 确保测试结束后清理依赖覆盖。
        upload_response = client.post(  # 先上传并同步入库一份文档，确保 Qdrant 里有数据。
            "/api/v1/documents/upload",
            files={
                "file": (
                    "manual.txt",
                    (
                        "Alarm E102 handling guide.\n\n"
                        "Step 1: Check voltage and reset device.\n"
                        "Step 2: If issue persists, contact after-sales engineer."
                    ).encode("utf-8"),
                    "text/plain",
                )
            },
        )
        search_response = client.post(  # 再调用检索接口。
            "/api/v1/retrieval/search",
            json={"query": "How to handle alarm E102?", "top_k": 3},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert upload_response.status_code == 201  # 上传入库应成功。
    assert search_response.status_code == 200  # 检索接口应返回 200。
    payload = search_response.json()  # 解析检索响应。
    assert payload["mode"] == "hybrid"  # 默认应启用 hybrid 检索，兼容向量召回 + 关键词召回融合。
    assert payload["results"]  # 至少应该返回一条命中结果。
    assert payload["results"][0]["text"]  # 结果文本不应为空。
    assert "Vector search, embeddings, and rerank are not wired yet." not in payload["results"][0]["text"]  # 不应再返回旧的占位文案。


def test_chat_ask_uses_real_retrieval_citations(tmp_path: Path) -> None:  # 验证问答接口会返回基于真实检索结果的引用。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    document_service = DocumentService(settings)  # 创建文档服务实例。
    retrieval_service = RetrievalService(settings)  # 创建检索服务实例。
    chat_service = ChatService(settings)  # 创建问答服务实例。
    client = TestClient(app)  # 创建测试客户端。

    app.dependency_overrides[get_document_service] = lambda: document_service  # 覆盖文档服务依赖。
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service  # 覆盖检索服务依赖。
    app.dependency_overrides[get_chat_service] = lambda: chat_service  # 覆盖问答服务依赖。
    try:  # 确保测试结束后清理依赖覆盖。
        upload_response = client.post(  # 先上传并同步入库一份文档。
            "/api/v1/documents/upload",
            files={
                "file": (
                    "manual.txt",
                    (
                        "Cooling fan troubleshooting guide.\n"
                        "If alarm E205 appears, inspect fan speed sensor and clean dust."
                    ).encode("utf-8"),
                    "text/plain",
                )
            },
        )
        chat_response = client.post(  # 再调用问答接口。
            "/api/v1/chat/ask",
            json={"question": "How to troubleshoot alarm E205?", "top_k": 3},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert upload_response.status_code == 201  # 上传入库应成功。
    assert chat_response.status_code == 200  # 问答接口应返回 200。
    payload = chat_response.json()  # 解析问答响应。
    assert payload["mode"] == "rag"  # mock provider 下应走完整 RAG 生成链路。
    assert payload["model"] == "mock"  # 当前测试配置使用 mock 生成模型。
    assert "retrieval-only placeholder answer" not in payload["answer"]  # 回答不应再是旧的 placeholder 文案。
    assert payload["citations"]  # 至少应该返回一条引用。
    assert payload["citations"][0]["snippet"]  # 引用片段文本不应为空。
    assert "Vector search, embeddings, and rerank are not wired yet." not in payload["citations"][0]["snippet"]  # 引用内容不应是旧占位文本。


def test_retrieval_search_returns_ocr_metadata_for_image_documents(tmp_path: Path) -> None:  # OCR 图片文档进入主链路后，检索结果也应带回 OCR metadata。
    settings = build_test_settings(tmp_path).model_copy(update={"ocr_provider": "mock"})
    ensure_data_directories(settings)
    document_service = DocumentService(settings)
    retrieval_service = RetrievalService(settings, document_service=document_service)

    source_path = settings.upload_dir / "inspection.png"
    source_path.write_bytes(b"fake-image-binary")
    Path(f"{source_path}.ocr.txt").write_text("产线巡检记录\n发现吸盘松动，需要重新紧固。", encoding="utf-8")

    document_service.ingestion_service.ingest_document(
        document_id="doc_ocr_search",
        filename="inspection.png",
        source_path=source_path,
    )

    response = retrieval_service.search(
        RetrievalRequest(query="吸盘松动怎么处理", top_k=1),
        auth_context=None,
    )

    assert response.results
    first = response.results[0]
    assert first.ocr_used is True
    assert first.parser_name == "image_ocr_mock"
    assert first.page_no == 1
    assert first.ocr_confidence is None
    assert first.quality_score is None


def test_retrieval_search_returns_ocr_metadata_for_docx_embedded_images(tmp_path: Path) -> None:  # DOCX 内嵌图片 OCR 入库后，检索结果也应能返回 OCR 元数据。
    settings = build_test_settings(tmp_path).model_copy(update={"ocr_provider": "mock"})
    ensure_data_directories(settings)
    document_service = DocumentService(settings)
    retrieval_service = RetrievalService(settings, document_service=document_service)

    source_path = settings.upload_dir / "embedded_guide.docx"
    source_path.write_bytes(
        build_minimal_docx_bytes(
            "正文：数字化系统巡检记录。",
            embedded_images=[("embedded_ocr.png", MINIMAL_PNG_BYTES)],
        )
    )
    Path(f"{source_path}.ocr.txt").write_text("截图步骤：检查传感器报警 E204。", encoding="utf-8")

    document_service.ingestion_service.ingest_document(
        document_id="doc_docx_embedded_ocr",
        filename="embedded_guide.docx",
        source_path=source_path,
    )

    response = retrieval_service.search(
        RetrievalRequest(query="E204 怎么处理", top_k=3),
        auth_context=None,
    )

    assert response.results
    assert any(item.ocr_used is True for item in response.results)
    ocr_item = next(item for item in response.results if item.ocr_used is True)
    assert ocr_item.parser_name == "docx_embedded_image_ocr_mock"
    assert "E204" in ocr_item.text


def test_chat_ask_endpoint_uses_openai_reranker_for_citation_order(tmp_path: Path, monkeypatch) -> None:
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "reranker_provider": "openai",
            "reranker_base_url": "http://127.0.0.1:8001/v1",
        }
    )
    ensure_data_directories(settings)
    chat_service = ChatService(settings)
    chat_service.retrieval_service = _FakeRetrievalService(
        [
            RetrievedChunk(
                chunk_id="chunk_1",
                document_id="doc_1",
                document_name="设备告警处理手册",
                text="alarm E201 发生后先检查温控模块和线缆连接。",
                score=0.91,
                source_path="/tmp/doc_1.txt",
            ),
            RetrievedChunk(
                chunk_id="chunk_2",
                document_id="doc_2",
                document_name="伺服维修指南",
                text="servo reset 前先确认急停释放，再重新上电。",
                score=0.86,
                source_path="/tmp/doc_2.txt",
            ),
            RetrievedChunk(
                chunk_id="chunk_3",
                document_id="doc_3",
                document_name="真空阀排障记录",
                text="vacuum valve 异常时检查阀体污染和供气压力。",
                score=0.82,
                source_path="/tmp/doc_3.txt",
            ),
        ]
    )
    client = TestClient(app)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "results": [
                    {"index": 1, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.88},
                    {"index": 2, "relevance_score": 0.72},
                ]
            }

    def fake_post(url: str, **kwargs):
        assert url == "http://127.0.0.1:8001/v1/rerank"
        assert kwargs["json"]["query"] == "servo reset"
        return FakeResponse()

    monkeypatch.setattr("backend.app.rag.rerankers.client.httpx.post", fake_post)
    app.dependency_overrides[get_chat_service] = lambda: chat_service
    try:
        response = client.post(
            "/api/v1/chat/ask",
            json={"question": "servo reset", "top_k": 3},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "rag"
    assert [item["chunk_id"] for item in payload["citations"]] == ["chunk_2", "chunk_1", "chunk_3"]


def test_chat_stream_returns_sse_events_and_done_payload(tmp_path: Path) -> None:  # 验证流式问答接口会返回 meta/delta/done 三类事件。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    document_service = DocumentService(settings)  # 创建文档服务实例。
    retrieval_service = RetrievalService(settings)  # 创建检索服务实例。
    chat_service = ChatService(settings)  # 创建问答服务实例。
    client = TestClient(app)  # 创建测试客户端。

    app.dependency_overrides[get_document_service] = lambda: document_service  # 覆盖文档服务依赖。
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service  # 覆盖检索服务依赖。
    app.dependency_overrides[get_chat_service] = lambda: chat_service  # 覆盖问答服务依赖。
    try:  # 确保测试结束后清理依赖覆盖。
        upload_response = client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "stream.txt",
                    "Stream answer should include this alarm guide context.".encode("utf-8"),
                    "text/plain",
                )
            },
        )
        with client.stream(  # 调用流式问答接口并收集 SSE 原始数据。
            "POST",
            "/api/v1/chat/ask/stream",
            json={"question": "What does this stream doc talk about?", "top_k": 3},
        ) as stream_response:
            raw_stream = "".join(stream_response.iter_text())
            status_code = stream_response.status_code
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert upload_response.status_code == 201
    assert status_code == 200
    events = parse_sse_events(raw_stream)
    event_names = [event_name for event_name, _ in events]
    assert "meta" in event_names
    assert "answer_delta" in event_names
    assert "done" in event_names
    done_payload = next(payload for event_name, payload in events if event_name == "done")
    assert done_payload["mode"] == "rag"
    assert done_payload["model"] == "mock"
    assert done_payload["answer"]
    assert done_payload["citations"]


def test_chat_stream_returns_no_context_done_when_empty_library(tmp_path: Path) -> None:  # 验证无文档时流式接口会返回 no_context 终态。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    retrieval_service = RetrievalService(settings)  # 创建检索服务实例。
    chat_service = ChatService(settings)  # 创建问答服务实例。
    client = TestClient(app)  # 创建测试客户端。

    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service  # 覆盖检索服务依赖。
    app.dependency_overrides[get_chat_service] = lambda: chat_service  # 覆盖问答服务依赖。
    try:  # 确保测试结束后清理依赖覆盖。
        with client.stream(
            "POST",
            "/api/v1/chat/ask/stream",
            json={"question": "Any knowledge available?", "top_k": 3},
        ) as stream_response:
            raw_stream = "".join(stream_response.iter_text())
            status_code = stream_response.status_code
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert status_code == 200
    events = parse_sse_events(raw_stream)
    event_names = [event_name for event_name, _ in events]
    assert "meta" in event_names
    assert "done" in event_names
    assert "answer_delta" not in event_names  # no_context 场景下不应产生 token 流片段。
    done_payload = next(payload for event_name, payload in events if event_name == "done")
    assert done_payload["mode"] == "no_context"
    assert done_payload["citations"] == []


def test_chat_stream_returns_error_event_when_llm_config_is_invalid_after_meta(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "llm_provider": "deepseek",
            "llm_base_url": "https://api.deepseek.com/v1",
            "llm_model": "deepseek-chat",
            "llm_api_key": "你的key",
        }
    )
    ensure_data_directories(settings)
    document_service = DocumentService(settings)
    retrieval_service = RetrievalService(settings)
    chat_service = ChatService(settings)
    client = TestClient(app)

    app.dependency_overrides[get_document_service] = lambda: document_service
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service
    app.dependency_overrides[get_chat_service] = lambda: chat_service
    try:
        upload_response = client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "stream.txt",
                    "Stream error should be emitted instead of breaking the connection.".encode("utf-8"),
                    "text/plain",
                )
            },
        )
        with client.stream(
            "POST",
            "/api/v1/chat/ask/stream",
            json={"question": "What does this stream doc talk about?", "top_k": 3},
        ) as stream_response:
            raw_stream = "".join(stream_response.iter_text())
            status_code = stream_response.status_code
    finally:
        app.dependency_overrides.clear()

    assert upload_response.status_code == 201
    assert status_code == 200
    events = parse_sse_events(raw_stream)
    event_names = [event_name for event_name, _ in events]
    assert "meta" in event_names
    assert "error" in event_names
    assert "done" not in event_names
    error_payload = next(payload for event_name, payload in events if event_name == "error")
    assert "RAG_LLM_API_KEY" in error_payload["message"]


def test_chat_ask_returns_429_when_runtime_gate_is_busy(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    fake_gate = _FakeRuntimeGateService(outcomes={"chat_fast": [False]})
    chat_service = ChatService(settings, runtime_gate_service=fake_gate)
    client = TestClient(app)

    app.dependency_overrides[get_chat_service] = lambda: chat_service
    try:
        response = client.post(
            "/api/v1/chat/ask",
            json={"question": "系统忙的时候会返回什么？", "mode": "fast", "top_k": 3},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "5"
    assert "System is busy" in response.json()["detail"]
    assert fake_gate.calls == [("chat_fast", 800, None)]


def test_chat_stream_returns_busy_error_event_when_runtime_gate_is_busy(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    fake_gate = _FakeRuntimeGateService(outcomes={"chat_fast": [False]})
    chat_service = ChatService(settings, runtime_gate_service=fake_gate)
    client = TestClient(app)

    app.dependency_overrides[get_chat_service] = lambda: chat_service
    try:
        with client.stream(
            "POST",
            "/api/v1/chat/ask/stream",
            json={"question": "系统忙的时候流式会返回什么？", "mode": "fast", "top_k": 3},
        ) as stream_response:
            raw_stream = "".join(stream_response.iter_text())
            status_code = stream_response.status_code
    finally:
        app.dependency_overrides.clear()

    assert status_code == 200
    events = parse_sse_events(raw_stream)
    event_names = [event_name for event_name, _ in events]
    assert "error" in event_names
    error_payload = next(payload for event_name, payload in events if event_name == "error")
    assert error_payload["busy"] is True
    assert error_payload["retry_after_seconds"] == 5
    assert "System is busy" in error_payload["message"]
    assert fake_gate.calls == [("chat_fast", 800, None)]


def test_chat_runtime_gate_enforces_single_user_limit(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    system_config_service = SystemConfigService(settings)
    system_config_service.repository.write(
        {
            "concurrency_controls": {
                "fast_max_inflight": 4,
                "accurate_max_inflight": 2,
                "sop_generation_max_inflight": 1,
                "per_user_online_max_inflight": 1,
                "acquire_timeout_ms": 0,
                "busy_retry_after_seconds": 5,
            }
        }
    )
    runtime_gate_service = RuntimeGateService(settings, system_config_service=system_config_service)
    chat_service = ChatService(settings, runtime_gate_service=runtime_gate_service)
    profile = chat_service.query_profile_service.resolve(purpose="chat", requested_mode="fast")
    same_user_context = _build_auth_context(role_id="employee", user_id="user_employee_a", username="employee.a")
    other_user_context = _build_auth_context(role_id="employee", user_id="user_employee_b", username="employee.b")

    _, first_lease, _, first_details = chat_service._acquire_chat_runtime_slot(profile, auth_context=same_user_context)

    with pytest.raises(RuntimeGateBusyError) as exc_info:
        chat_service._acquire_chat_runtime_slot(profile, auth_context=same_user_context)

    _, other_user_lease, _, other_user_details = chat_service._acquire_chat_runtime_slot(profile, auth_context=other_user_context)

    assert first_details["runtime_owner_key"] == "user_employee_a"
    assert exc_info.value.reason == "user_limit"
    assert "concurrent request limit" in exc_info.value.detail
    assert other_user_details["runtime_owner_key"] == "user_employee_b"

    first_lease.release()
    other_user_lease.release()


def test_retrieval_search_can_filter_by_document_id(tmp_path: Path) -> None:  # 验证检索接口支持按 document_id 过滤。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    document_service = DocumentService(settings)  # 创建文档服务实例。
    retrieval_service = RetrievalService(settings)  # 创建检索服务实例。
    client = TestClient(app)  # 创建测试客户端。

    app.dependency_overrides[get_document_service] = lambda: document_service  # 覆盖文档服务依赖。
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service  # 覆盖检索服务依赖。
    try:  # 确保测试结束后清理依赖覆盖。
        upload_a = client.post(  # 上传第一份文档。
            "/api/v1/documents/upload",
            files={"file": ("a.txt", "Doc A alarm E101 cooling note.".encode("utf-8"), "text/plain")},
        )
        upload_b = client.post(  # 上传第二份文档。
            "/api/v1/documents/upload",
            files={"file": ("b.txt", "Doc B alarm E101 pressure note.".encode("utf-8"), "text/plain")},
        )
        search_response = client.post(  # 指定 document_id 仅检索文档 A。
            "/api/v1/retrieval/search",
            json={
                "query": "alarm E101",
                "top_k": 5,
                "document_id": upload_a.json()["document_id"],
            },
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert upload_a.status_code == 201
    assert upload_b.status_code == 201
    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["results"]  # 指定文档仍应有结果。
    assert all(item["document_id"] == upload_a.json()["document_id"] for item in payload["results"])  # 结果应全部属于文档 A。


def test_retrieval_search_accepts_doc_id_alias(tmp_path: Path) -> None:  # 验证检索接口兼容历史 doc_id 字段名。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    document_service = DocumentService(settings)  # 创建文档服务实例。
    retrieval_service = RetrievalService(settings)  # 创建检索服务实例。
    client = TestClient(app)  # 创建测试客户端。

    app.dependency_overrides[get_document_service] = lambda: document_service  # 覆盖文档服务依赖。
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service  # 覆盖检索服务依赖。
    try:  # 确保测试结束后清理依赖覆盖。
        upload_response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("alias.txt", "Alias doc E777 note.".encode("utf-8"), "text/plain")},
        )
        search_response = client.post(
            "/api/v1/retrieval/search",
            json={
                "query": "E777",
                "top_k": 5,
                "doc_id": upload_response.json()["document_id"],  # 用历史字段名触发兼容路径。
            },
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert upload_response.status_code == 201
    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["results"]
    assert all(item["document_id"] == upload_response.json()["document_id"] for item in payload["results"])


def test_chat_ask_can_filter_citations_by_document_id(tmp_path: Path) -> None:  # 验证问答接口支持按 document_id 过滤引用来源。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    document_service = DocumentService(settings)  # 创建文档服务实例。
    retrieval_service = RetrievalService(settings)  # 创建检索服务实例。
    chat_service = ChatService(settings)  # 创建问答服务实例。
    client = TestClient(app)  # 创建测试客户端。

    app.dependency_overrides[get_document_service] = lambda: document_service  # 覆盖文档服务依赖。
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service  # 覆盖检索服务依赖。
    app.dependency_overrides[get_chat_service] = lambda: chat_service  # 覆盖问答服务依赖。
    try:  # 确保测试结束后清理依赖覆盖。
        upload_a = client.post(  # 上传第一份文档。
            "/api/v1/documents/upload",
            files={"file": ("a.txt", "Doc A alarm E301 reset guide.".encode("utf-8"), "text/plain")},
        )
        upload_b = client.post(  # 上传第二份文档。
            "/api/v1/documents/upload",
            files={"file": ("b.txt", "Doc B alarm E301 valve guide.".encode("utf-8"), "text/plain")},
        )
        chat_response = client.post(  # 问答时只允许引用文档 B。
            "/api/v1/chat/ask",
            json={
                "question": "How to handle alarm E301?",
                "top_k": 5,
                "document_id": upload_b.json()["document_id"],
            },
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert upload_a.status_code == 201
    assert upload_b.status_code == 201
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["citations"]  # 指定文档应有引用。
    assert all(item["document_id"] == upload_b.json()["document_id"] for item in payload["citations"])  # 引用必须都来自文档 B。


def test_chat_ask_accepts_doc_id_alias(tmp_path: Path) -> None:  # 验证问答接口兼容历史 doc_id 字段名。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    document_service = DocumentService(settings)  # 创建文档服务实例。
    retrieval_service = RetrievalService(settings)  # 创建检索服务实例。
    chat_service = ChatService(settings)  # 创建问答服务实例。
    client = TestClient(app)  # 创建测试客户端。

    app.dependency_overrides[get_document_service] = lambda: document_service  # 覆盖文档服务依赖。
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service  # 覆盖检索服务依赖。
    app.dependency_overrides[get_chat_service] = lambda: chat_service  # 覆盖问答服务依赖。
    try:  # 确保测试结束后清理依赖覆盖。
        upload_response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("alias-chat.txt", "Alias chat E888 guide.".encode("utf-8"), "text/plain")},
        )
        chat_response = client.post(
            "/api/v1/chat/ask",
            json={
                "question": "How to handle E888?",
                "top_k": 5,
                "doc_id": upload_response.json()["document_id"],  # 用历史字段名触发兼容路径。
            },
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert upload_response.status_code == 201
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["citations"]
    assert all(item["document_id"] == upload_response.json()["document_id"] for item in payload["citations"])


def test_chat_ask_falls_back_when_ollama_unavailable(tmp_path: Path) -> None:  # 验证 Ollama 不可用时会返回检索兜底回答而不是 500。
    settings = build_test_settings(tmp_path).model_copy(  # 先拿基础配置，再覆盖成 ollama 模式。
        update={
            "llm_provider": "ollama",  # 强制走 ollama 生成逻辑。
            "ollama_base_url": "http://127.0.0.1:9",  # 使用几乎必定不可用的地址，触发降级路径。
            "llm_timeout_seconds": 0.2,  # 缩短超时，避免测试等待过久。
        }
    )
    ensure_data_directories(settings)  # 创建测试目录。
    document_service = DocumentService(settings)  # 创建文档服务实例。
    retrieval_service = RetrievalService(settings)  # 创建检索服务实例。
    chat_service = ChatService(settings)  # 创建问答服务实例。
    client = TestClient(app)  # 创建测试客户端。

    app.dependency_overrides[get_document_service] = lambda: document_service  # 覆盖文档服务依赖。
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service  # 覆盖检索服务依赖。
    app.dependency_overrides[get_chat_service] = lambda: chat_service  # 覆盖问答服务依赖。
    try:  # 确保测试结束后清理依赖覆盖。
        upload_response = client.post(  # 先上传并同步入库一份文档。
            "/api/v1/documents/upload",
            files={
                "file": (
                    "manual.txt",
                    "Power system diagnostics and recovery guide.".encode("utf-8"),
                    "text/plain",
                )
            },
        )
        chat_response = client.post(  # 再调用问答接口，触发 ollama 不可用降级流程。
            "/api/v1/chat/ask",
            json={"question": "How to recover power system?", "top_k": 3},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert upload_response.status_code == 201  # 上传入库应成功。
    assert chat_response.status_code == 200  # 降级后接口仍应返回 200。
    payload = chat_response.json()  # 解析问答响应。
    assert payload["mode"] == "retrieval_fallback"  # 断言返回检索兜底模式。
    assert payload["citations"]  # 降级回答也应带引用。
    assert "Generation model is unavailable" in payload["answer"]  # 断言回答正文包含降级提示。


def test_chat_ask_uses_openai_compatible_llm(tmp_path: Path, monkeypatch) -> None:  # 验证本地 vLLM 这类 OpenAI 兼容接口能走通问答链路。
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "llm_provider": "openai",
            "llm_base_url": "http://127.0.0.1:8000/v1",
            "llm_model": "Qwen/Qwen2.5-7B-Instruct",
        }
    )
    ensure_data_directories(settings)  # 创建测试目录。
    document_service = DocumentService(settings)  # 创建文档服务实例。
    retrieval_service = RetrievalService(settings)  # 创建检索服务实例。
    chat_service = ChatService(settings)  # 创建问答服务实例。
    client = TestClient(app)  # 创建测试客户端。

    class FakeResponse:  # 用于模拟 OpenAI 兼容接口响应。
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, object]:
            return {"choices": [{"message": {"content": "OpenAI-compatible answer from local vLLM."}}]}

    def fake_post(url: str, **kwargs):  # 模拟向本地 vLLM 发请求。
        assert url == "http://127.0.0.1:8000/v1/chat/completions"
        assert kwargs["json"]["model"] == "Qwen/Qwen2.5-7B-Instruct"
        return FakeResponse()

    monkeypatch.setattr("backend.app.rag.generators.client.httpx.post", fake_post)  # 截获生成请求，避免依赖真实 vLLM 进程。
    app.dependency_overrides[get_document_service] = lambda: document_service  # 覆盖文档服务依赖。
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service  # 覆盖检索服务依赖。
    app.dependency_overrides[get_chat_service] = lambda: chat_service  # 覆盖问答服务依赖。
    try:  # 确保测试结束后清理依赖覆盖。
        upload_response = client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "manual.txt",
                    "Alarm E901 requires checking the vacuum valve state.".encode("utf-8"),
                    "text/plain",
                )
            },
        )
        chat_response = client.post(
            "/api/v1/chat/ask",
            json={"question": "How to handle alarm E901?", "top_k": 3},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert upload_response.status_code == 201
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["mode"] == "rag"
    assert payload["model"] == "Qwen/Qwen2.5-7B-Instruct"
    assert payload["answer"] == "OpenAI-compatible answer from local vLLM."


def test_chat_ask_falls_back_when_openai_compatible_llm_unavailable(tmp_path: Path) -> None:  # 验证 OpenAI 兼容接口不可用时仍然返回检索兜底结果。
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "llm_provider": "openai",
            "llm_base_url": "http://127.0.0.1:9/v1",
            "llm_timeout_seconds": 0.2,
        }
    )
    ensure_data_directories(settings)  # 创建测试目录。
    document_service = DocumentService(settings)  # 创建文档服务实例。
    retrieval_service = RetrievalService(settings)  # 创建检索服务实例。
    chat_service = ChatService(settings)  # 创建问答服务实例。
    client = TestClient(app)  # 创建测试客户端。

    app.dependency_overrides[get_document_service] = lambda: document_service  # 覆盖文档服务依赖。
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service  # 覆盖检索服务依赖。
    app.dependency_overrides[get_chat_service] = lambda: chat_service  # 覆盖问答服务依赖。
    try:  # 确保测试结束后清理依赖覆盖。
        upload_response = client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "manual.txt",
                    "Servo reset guide for axis synchronization.".encode("utf-8"),
                    "text/plain",
                )
            },
        )
        chat_response = client.post(
            "/api/v1/chat/ask",
            json={"question": "How to reset servo axis?", "top_k": 3},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert upload_response.status_code == 201
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["mode"] == "retrieval_fallback"
    assert payload["citations"]
    assert "Generation model is unavailable" in payload["answer"]


def test_chat_ask_does_not_fallback_on_openai_compatible_client_error(tmp_path: Path, monkeypatch) -> None:  # 验证 OpenAI 兼容接口 4xx 不应静默降级为 retrieval_fallback。
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "llm_provider": "openai",
            "llm_base_url": "http://127.0.0.1:8000/v1",
            "llm_model": "Qwen/Qwen2.5-7B-Instruct",
        }
    )
    ensure_data_directories(settings)  # 创建测试目录。
    document_service = DocumentService(settings)  # 创建文档服务实例。
    retrieval_service = RetrievalService(settings)  # 创建检索服务实例。
    chat_service = ChatService(settings)  # 创建问答服务实例。
    client = TestClient(app, raise_server_exceptions=False)  # 关闭异常透传，便于断言 HTTP 500。

    def fake_post(url: str, **kwargs):  # 模拟 OpenAI 兼容服务返回 400。
        request = httpx.Request("POST", url)
        response = httpx.Response(400, request=request, json={"error": "bad request"})
        raise httpx.HTTPStatusError("400 Client Error", request=request, response=response)

    monkeypatch.setattr("backend.app.rag.generators.client.httpx.post", fake_post)  # 截获生成请求，构造客户端错误场景。
    app.dependency_overrides[get_document_service] = lambda: document_service  # 覆盖文档服务依赖。
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service  # 覆盖检索服务依赖。
    app.dependency_overrides[get_chat_service] = lambda: chat_service  # 覆盖问答服务依赖。
    try:  # 确保测试结束后清理依赖覆盖。
        upload_response = client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "manual.txt",
                    "Axis servo diagnostics guide.".encode("utf-8"),
                    "text/plain",
                )
            },
        )
        chat_response = client.post(
            "/api/v1/chat/ask",
            json={"question": "How to check axis servo?", "top_k": 3},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert upload_response.status_code == 201  # 文档入库应成功。
    assert chat_response.status_code == 500  # OpenAI 兼容接口 4xx 不应走 retrieval_fallback。


def test_retrieval_service_enforces_document_id_filter_even_when_store_returns_mixed_docs(  # 验证服务层会二次过滤 document_id，避免跨文档结果泄露。
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    retrieval_service = RetrievalService(settings)  # 创建检索服务实例。

    class FakePoint:  # 构造最小 Qdrant 点位桩对象。
        def __init__(self, chunk_id: str, document_id: str, score: float) -> None:
            self.id = chunk_id
            self.score = score
            self.payload = {
                "chunk_id": chunk_id,
                "document_id": document_id,
                "document_name": f"{document_id}.txt",
                "text": f"{document_id} content",
                "source_path": f"/tmp/{document_id}.txt",
            }

    def fake_embed_texts(texts: list[str]) -> list[list[float]]:  # 替换 embedding，避免依赖真实模型。
        return [[0.1, 0.2, 0.3] for _ in texts]

    def fake_search(query_vector: list[float], *, limit: int, document_id: str | None = None):  # 模拟向量库返回混合文档结果。
        assert document_id == "doc_target"  # 断言请求层确实传入了 document_id。
        return [
            FakePoint("chunk_target", "doc_target", 0.91),
            FakePoint("chunk_other", "doc_other", 0.97),
        ]

    monkeypatch.setattr(retrieval_service.embedding_client, "embed_texts", fake_embed_texts)  # 注入 fake embedding。
    monkeypatch.setattr(retrieval_service.vector_store, "search", fake_search)  # 注入 fake 向量检索。

    response = retrieval_service.search(  # 直接调用服务层，验证后置过滤行为。
        request=RetrievalRequest(query="E102", top_k=5, document_id="doc_target")
    )

    assert response.results  # 目标文档结果应被保留。
    assert all(item.document_id == "doc_target" for item in response.results)  # 结果里不能混入其他文档。


def test_retrieval_service_uses_hybrid_fusion_to_promote_keyword_hits(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "query_fast_top_k_default": 2,
            "query_fast_lexical_top_k_default": 3,
        }
    )
    ensure_data_directories(settings)
    retrieval_service = RetrievalService(settings)
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, *, limit, document_id=None: [
            SimpleNamespace(
                id="point-b",
                score=0.97,
                payload={
                    "chunk_id": "chunk-b",
                    "document_id": "doc_b",
                    "document_name": "doc_b.txt",
                    "text": "general troubleshooting context",
                    "source_path": "/tmp/doc_b.txt",
                },
            ),
            SimpleNamespace(
                id="point-a",
                score=0.84,
                payload={
                    "chunk_id": "chunk-a",
                    "document_id": "doc_a",
                    "document_name": "doc_a.txt",
                    "text": "ZX14 alarm reset guide",
                    "source_path": "/tmp/doc_a.txt",
                },
            ),
        ]
    )
    lexical_limits: list[int] = []

    def fake_lexical_search(query, *, limit, document_id=None):
        lexical_limits.append(limit)
        return [
            SimpleNamespace(
                point_id="point-a",
                score=2.4,
                payload={
                    "chunk_id": "chunk-a",
                    "document_id": "doc_a",
                    "document_name": "doc_a.txt",
                    "text": "ZX14 alarm reset guide",
                    "source_path": "/tmp/doc_a.txt",
                },
            )
        ]

    retrieval_service.lexical_retriever = SimpleNamespace(search=fake_lexical_search)

    response = retrieval_service.search(request=RetrievalRequest(query="ZX14"))

    assert response.mode == "hybrid"
    assert lexical_limits == [3]
    assert [item.chunk_id for item in response.results] == ["chunk-a", "chunk-b"]
    assert response.results[0].retrieval_strategy == "hybrid"
    assert response.results[0].vector_score == 0.84
    assert response.results[0].lexical_score == 2.4
    assert response.results[0].fused_score == response.results[0].score


@pytest.mark.parametrize(
    ("query", "expected_top_chunk"),
    [
        ("PLC_A01错误", "chunk-lexical"),
        ("为什么设备夜班频繁停机", "chunk-vector"),
        ("SOP-1024夜班停机原因", "chunk-shared"),
    ],
)
def test_retrieval_service_applies_dynamic_hybrid_weights_by_query_type(
    tmp_path: Path,
    query: str,
    expected_top_chunk: str,
) -> None:
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "retrieval_dynamic_weighting_enabled": True,
            "retrieval_hybrid_rrf_k": 1,
            "query_fast_top_k_default": 3,
            "query_fast_lexical_top_k_default": 3,
        }
    )
    ensure_data_directories(settings)
    retrieval_service = RetrievalService(settings)
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, *, limit, document_id=None: [
            SimpleNamespace(
                id="point-vector",
                score=0.98,
                payload={
                    "chunk_id": "chunk-vector",
                    "document_id": "doc_vector",
                    "document_name": "doc_vector.txt",
                    "text": "night shift troubleshooting summary",
                    "source_path": "/tmp/doc_vector.txt",
                },
            ),
            SimpleNamespace(
                id="point-shared",
                score=0.91,
                payload={
                    "chunk_id": "chunk-shared",
                    "document_id": "doc_shared",
                    "document_name": "doc_shared.txt",
                    "text": "SOP-1024 night shift downtime analysis",
                    "source_path": "/tmp/doc_shared.txt",
                },
            ),
        ]
    )
    retrieval_service.lexical_retriever = SimpleNamespace(
        search=lambda query, *, limit, document_id=None: [
            SimpleNamespace(
                point_id="point-lexical",
                score=4.2,
                payload={
                    "chunk_id": "chunk-lexical",
                    "document_id": "doc_lexical",
                    "document_name": "doc_lexical.txt",
                    "text": "PLC_A01 fault code recovery steps",
                    "source_path": "/tmp/doc_lexical.txt",
                },
            ),
            SimpleNamespace(
                point_id="point-shared",
                score=3.4,
                payload={
                    "chunk_id": "chunk-shared",
                    "document_id": "doc_shared",
                    "document_name": "doc_shared.txt",
                    "text": "SOP-1024 night shift downtime analysis",
                    "source_path": "/tmp/doc_shared.txt",
                },
            ),
        ]
    )

    response = retrieval_service.search(request=RetrievalRequest(query=query))

    assert response.mode == "hybrid"
    assert response.results[0].chunk_id == expected_top_chunk


def test_retrieval_service_logs_dynamic_weight_decision(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "retrieval_dynamic_weighting_enabled": True,
            "retrieval_hybrid_rrf_k": 1,
        }
    )
    ensure_data_directories(settings)
    retrieval_service = RetrievalService(settings)
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, *, limit, document_id=None: [
            SimpleNamespace(
                id="point-vector",
                score=0.98,
                payload={
                    "chunk_id": "chunk-vector",
                    "document_id": "doc_vector",
                    "document_name": "doc_vector.txt",
                    "text": "night shift troubleshooting summary",
                    "source_path": "/tmp/doc_vector.txt",
                },
            )
        ]
    )
    retrieval_service.lexical_retriever = SimpleNamespace(
        search=lambda query, *, limit, document_id=None: [
            SimpleNamespace(
                point_id="point-lexical",
                score=4.2,
                payload={
                    "chunk_id": "chunk-lexical",
                    "document_id": "doc_lexical",
                    "document_name": "doc_lexical.txt",
                    "text": "PLC_A01 fault code recovery steps",
                    "source_path": "/tmp/doc_lexical.txt",
                },
            )
        ]
    )

    with caplog.at_level("INFO", logger="backend.app.services.retrieval_service"):
        retrieval_service.search(request=RetrievalRequest(query="PLC_A01错误"))

    assert "query_type=exact" in caplog.text
    assert "vector_weight=0.300" in caplog.text
    assert "lexical_weight=0.700" in caplog.text


def test_retrieval_service_falls_back_to_qdrant_when_lexical_retriever_errors(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    retrieval_service = RetrievalService(settings)
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, *, limit, document_id=None: [
            SimpleNamespace(
                id="point-b",
                score=0.97,
                payload={
                    "chunk_id": "chunk-b",
                    "document_id": "doc_b",
                    "document_name": "doc_b.txt",
                    "text": "general troubleshooting context",
                    "source_path": "/tmp/doc_b.txt",
                },
            )
        ]
    )

    class BrokenLexicalRetriever:
        def search(self, query, *, limit, document_id=None):
            raise RuntimeError("lexical branch unavailable")

    retrieval_service.lexical_retriever = BrokenLexicalRetriever()

    response = retrieval_service.search(request=RetrievalRequest(query="ZX14", top_k=2))

    assert response.mode == "qdrant"
    assert [item.chunk_id for item in response.results] == ["chunk-b"]


def test_retrieval_service_batches_document_readability_checks(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path)

    class SpyDocumentService:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def is_document_readable(self, doc_id: str, auth_context: AuthContext | None) -> bool:  # pragma: no cover
            raise AssertionError("retrieval should batch readability checks instead of loading one document at a time")

        def get_document_readability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            self.calls.append(doc_ids)
            return {
                "doc_a": True,
                "doc_b": False,
            }

    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService())
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, *, limit, document_id=None: [
            SimpleNamespace(
                id="point-a",
                score=0.99,
                payload={
                    "chunk_id": "chunk-a",
                    "document_id": "doc_a",
                    "document_name": "doc_a.txt",
                    "text": "alpha",
                    "source_path": "/tmp/doc_a.txt",
                },
            ),
            SimpleNamespace(
                id="point-b",
                score=0.98,
                payload={
                    "chunk_id": "chunk-b",
                    "document_id": "doc_b",
                    "document_name": "doc_b.txt",
                    "text": "beta",
                    "source_path": "/tmp/doc_b.txt",
                },
            ),
        ]
    )

    response = retrieval_service.search(
        request=RetrievalRequest(query="test", top_k=5),
        auth_context=_build_auth_context(),
    )

    assert [item.document_id for item in response.results] == ["doc_a"]
    assert retrieval_service.document_service.calls == [["doc_a", "doc_b"]]


def test_retrieval_compare_rerank_reports_provider_vs_heuristic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    system_config_service = SystemConfigService(settings)
    system_config_service.repository.write(
        {
            "reranker_routing": {
                "provider": "openai_compatible",
                "model": "BAAI/bge-reranker-v2-m3",
                "timeout_seconds": 9.0,
            }
        }
    )
    retrieval_service = RetrievalService(settings)
    base_results = [
        RetrievedChunk(
            chunk_id="chunk-a",
            document_id="doc_a",
            document_name="doc_a.txt",
            text="servo reset requires checking alarm signal first",
            score=0.91,
            source_path="/tmp/doc_a.txt",
            retrieval_strategy="hybrid",
        ),
        RetrievedChunk(
            chunk_id="chunk-b",
            document_id="doc_b",
            document_name="doc_b.txt",
            text="servo reset should release e-stop before reboot",
            score=0.87,
            source_path="/tmp/doc_b.txt",
            retrieval_strategy="hybrid",
        ),
    ]
    retrieval_service.search = lambda request, auth_context=None: RetrievalResponse(  # type: ignore[method-assign]
        query=request.query,
        top_k=request.top_k or 2,
        mode="hybrid",
        results=base_results,
    )
    monkeypatch.setattr(
        retrieval_service.reranker_client,
        "rerank",
        lambda **kwargs: [base_results[1].model_copy(update={"score": 0.99}), base_results[0].model_copy(update={"score": 0.88})],
    )
    monkeypatch.setattr(
        retrieval_service.reranker_client,
        "rerank_heuristic",
        lambda **kwargs: [base_results[0].model_copy(update={"score": 0.95}), base_results[1].model_copy(update={"score": 0.84})],
    )
    monkeypatch.setattr(
        retrieval_service.reranker_client,
        "get_runtime_status",
        lambda force_refresh=False: {
            "provider": "openai_compatible",
            "model": "BAAI/bge-reranker-v2-m3",
            "failure_cooldown_seconds": 15.0,
            "effective_provider": "openai_compatible",
            "effective_model": "BAAI/bge-reranker-v2-m3",
            "effective_strategy": "provider",
            "fallback_enabled": True,
            "lock_active": False,
            "lock_source": None,
            "cooldown_remaining_seconds": 0.0,
            "ready": True,
            "detail": "OpenAI-compatible reranker health probe succeeded.",
        },
    )

    response = retrieval_service.compare_rerank(RetrievalRequest(query="servo reset", top_k=2))

    assert response.mode == "hybrid"
    assert response.candidate_count == 2
    assert response.configured.provider == "openai_compatible"
    assert response.configured.model == "BAAI/bge-reranker-v2-m3"
    assert response.configured.strategy == "provider"
    assert [item.chunk_id for item in response.configured.results] == ["chunk-b", "chunk-a"]
    assert [item.chunk_id for item in response.heuristic.results] == ["chunk-a", "chunk-b"]
    assert response.route_status.effective_provider == "openai_compatible"
    assert response.route_status.effective_strategy == "provider"
    assert response.route_status.lock_active is False
    assert response.route_status.ready is True
    assert response.summary.top1_same is False
    assert response.summary.overlap_count == 2


def test_retrieval_compare_rerank_surfaces_provider_error_and_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    system_config_service = SystemConfigService(settings)
    system_config_service.repository.write(
        {
            "reranker_routing": {
                "provider": "openai_compatible",
                "model": "BAAI/bge-reranker-v2-m3",
                "timeout_seconds": 9.0,
            },
            "degrade_controls": {
                "rerank_fallback_enabled": True,
                "accurate_to_fast_fallback_enabled": True,
                "retrieval_fallback_enabled": True,
            },
        }
    )
    retrieval_service = RetrievalService(settings)
    base_results = [
        RetrievedChunk(
            chunk_id="chunk-a",
            document_id="doc_a",
            document_name="doc_a.txt",
            text="servo reset requires checking alarm signal first",
            score=0.91,
            source_path="/tmp/doc_a.txt",
            retrieval_strategy="hybrid",
        ),
        RetrievedChunk(
            chunk_id="chunk-b",
            document_id="doc_b",
            document_name="doc_b.txt",
            text="servo reset should release e-stop before reboot",
            score=0.87,
            source_path="/tmp/doc_b.txt",
            retrieval_strategy="hybrid",
        ),
    ]
    heuristic_results = [base_results[0].model_copy(update={"score": 0.95}), base_results[1].model_copy(update={"score": 0.84})]
    retrieval_service.search = lambda request, auth_context=None: RetrievalResponse(  # type: ignore[method-assign]
        query=request.query,
        top_k=request.top_k or 2,
        mode="hybrid",
        results=base_results,
    )

    def fail_provider(**kwargs):
        raise RuntimeError("reranker upstream unavailable")

    monkeypatch.setattr(retrieval_service.reranker_client, "rerank", fail_provider)
    monkeypatch.setattr(retrieval_service.reranker_client, "rerank_heuristic", lambda **kwargs: heuristic_results)
    monkeypatch.setattr(
        retrieval_service.reranker_client,
        "get_runtime_status",
        lambda force_refresh=False: {
            "provider": "openai_compatible",
            "model": "BAAI/bge-reranker-v2-m3",
            "failure_cooldown_seconds": 15.0,
            "effective_provider": "heuristic",
            "effective_model": "heuristic",
            "effective_strategy": "heuristic",
            "fallback_enabled": True,
            "lock_active": True,
            "lock_source": "request",
            "cooldown_remaining_seconds": 12.4,
            "ready": False,
            "detail": "reranker upstream unavailable",
        },
    )

    response = retrieval_service.compare_rerank(RetrievalRequest(query="servo reset", top_k=2))

    assert response.configured.strategy == "heuristic"
    assert response.configured.error_message == "reranker upstream unavailable"
    assert [item.chunk_id for item in response.configured.results] == ["chunk-a", "chunk-b"]
    assert [item.chunk_id for item in response.heuristic.results] == ["chunk-a", "chunk-b"]
    assert response.route_status.effective_provider == "heuristic"
    assert response.route_status.effective_strategy == "heuristic"
    assert response.route_status.lock_active is True
    assert response.route_status.lock_source == "request"
    assert response.route_status.ready is False
    assert response.summary.top1_same is True


def test_retrieval_rerank_compare_endpoint_returns_comparison_payload(tmp_path: Path) -> None:
    client = TestClient(app)

    class FakeRetrievalService:
        def compare_rerank(self, request, *, auth_context=None):
            return {
                "query": request.query,
                "mode": "hybrid",
                "candidate_count": 2,
                "rerank_top_n": 2,
                "route_status": {
                    "provider": "openai_compatible",
                    "model": "BAAI/bge-reranker-v2-m3",
                    "failure_cooldown_seconds": 15.0,
                    "effective_provider": "heuristic",
                    "effective_model": "heuristic",
                    "effective_strategy": "heuristic",
                    "fallback_enabled": True,
                    "lock_active": True,
                    "lock_source": "probe",
                    "cooldown_remaining_seconds": 13.8,
                    "ready": False,
                    "detail": "Reranker health probe failed with HTTP error: 502 Bad Gateway",
                },
                "configured": {
                    "label": "configured",
                    "provider": "openai_compatible",
                    "model": "BAAI/bge-reranker-v2-m3",
                    "strategy": "provider",
                    "error_message": None,
                    "results": [
                        {
                            "chunk_id": "chunk-b",
                            "document_id": "doc_b",
                            "document_name": "doc_b.txt",
                            "text": "servo reset should release e-stop before reboot",
                            "score": 0.99,
                            "source_path": "/tmp/doc_b.txt",
                            "retrieval_strategy": "hybrid",
                            "vector_score": 0.87,
                            "lexical_score": 1.5,
                            "fused_score": 0.91,
                            "ocr_used": False,
                            "parser_name": None,
                            "page_no": None,
                            "ocr_confidence": None,
                            "quality_score": None,
                        }
                    ],
                },
                "heuristic": {
                    "label": "heuristic",
                    "provider": "heuristic",
                    "model": None,
                    "strategy": "heuristic",
                    "error_message": None,
                    "results": [
                        {
                            "chunk_id": "chunk-a",
                            "document_id": "doc_a",
                            "document_name": "doc_a.txt",
                            "text": "servo reset requires checking alarm signal first",
                            "score": 0.95,
                            "source_path": "/tmp/doc_a.txt",
                            "retrieval_strategy": "hybrid",
                            "vector_score": 0.91,
                            "lexical_score": 1.1,
                            "fused_score": 0.92,
                            "ocr_used": False,
                            "parser_name": None,
                            "page_no": None,
                            "ocr_confidence": None,
                            "quality_score": None,
                        }
                    ],
                },
                "summary": {
                    "overlap_count": 0,
                    "top1_same": False,
                    "configured_only_chunk_ids": ["chunk-b"],
                    "heuristic_only_chunk_ids": ["chunk-a"],
                },
            }

    app.dependency_overrides[get_retrieval_service] = lambda: FakeRetrievalService()
    try:
        response = client.post(
            "/api/v1/retrieval/rerank-compare",
            json={"query": "servo reset", "top_k": 2},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["route_status"]["provider"] == "openai_compatible"
    assert payload["route_status"]["effective_strategy"] == "heuristic"
    assert payload["route_status"]["fallback_enabled"] is True
    assert payload["route_status"]["lock_active"] is True
    assert payload["configured"]["provider"] == "openai_compatible"
    assert payload["configured"]["strategy"] == "provider"
    assert payload["heuristic"]["provider"] == "heuristic"
    assert payload["summary"]["configured_only_chunk_ids"] == ["chunk-b"]
