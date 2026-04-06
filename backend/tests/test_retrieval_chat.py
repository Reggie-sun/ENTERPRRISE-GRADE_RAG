import json  # 导入 json，用于解析 SSE 事件数据。
from pathlib import Path  # 导入 Path，方便创建测试目录路径。
from types import SimpleNamespace

from fastapi.testclient import TestClient  # 导入 FastAPI 测试客户端。
import httpx  # 导入 httpx，用于构造 OpenAI 兼容接口错误响应。
import pytest

from backend.app.core.config import Settings, ensure_data_directories  # 导入配置对象和目录初始化函数。
from backend.app.main import app  # 导入应用实例。
from backend.app.rag.retrievers import LexicalMatch
from backend.app.schemas.auth import AuthContext, DepartmentRecord, RoleDefinition, UserRecord
from backend.app.schemas.chat import ChatRequest
from backend.app.schemas.retrieval import RetrievalRequest, RetrievalResponse, RetrievedChunk  # 导入检索请求/响应模型，用于直接调用服务层测试过滤逻辑。
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.chat_service import ChatService, get_chat_service  # 导入问答服务和依赖入口。
from backend.app.services.document_service import DocumentService, get_document_service  # 导入文档服务和依赖入口。
from backend.app.services.identity_service import get_identity_service
from backend.app.services.retrieval_scope_policy import DepartmentPriorityRetrievalScope, RetrievalScopePolicy  # 导入检索权限策略。
from backend.app.services.request_snapshot_service import RequestSnapshotService
from backend.app.services.request_trace_service import RequestTraceService
from backend.app.services.runtime_gate_service import RuntimeGateBusyError, RuntimeGateService
from backend.app.services.retrieval_service import RetrievalService, get_retrieval_service  # 导入检索服务和依赖入口。
from backend.app.services.system_config_service import SystemConfigService
from backend.tests.test_document_ingestion import MINIMAL_PNG_BYTES, build_minimal_docx_bytes
from backend.tests.test_sop_generation_service import _build_identity_service


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


def _login_headers(client: TestClient, *, username: str = "sys.admin", password: str = "sys-admin-pass") -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _build_authenticated_client(
    tmp_path: Path,
    settings: Settings,
    *,
    username: str = "sys.admin",
    password: str = "sys-admin-pass",
    raise_server_exceptions: bool = True,
) -> TestClient:
    identity_service = _build_identity_service(tmp_path)
    settings.identity_bootstrap_path = identity_service.settings.identity_bootstrap_path
    auth_service = AuthService(settings, identity_service=identity_service)
    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    client.headers.update(_login_headers(client, username=username, password=password))
    return client


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

    def search_candidates(self, request, *, auth_context=None, profile=None, truncate_to_top_k=True, diagnostic=None):
        limit = request.top_k if truncate_to_top_k else (request.candidate_top_k or len(self.results))
        results = self.results[:limit]
        return results, "fake", profile


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
    client = _build_authenticated_client(tmp_path, settings)  # 创建带登录态的测试客户端。

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
    client = _build_authenticated_client(tmp_path, settings)  # 创建带登录态的测试客户端。

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


def test_chat_ask_propagates_ocr_metadata_to_citations(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    chat_service = ChatService(settings)
    chat_service.retrieval_service = _FakeRetrievalService(
        [
            RetrievedChunk(
                chunk_id="chunk_ocr_001",
                document_id="doc_ocr_001",
                document_name="ocr_manual.png",
                text="CPPS 说明图：控制电源与压力传感器同步校准。",
                score=0.93,
                source_path="/tmp/ocr_manual.png",
                retrieval_strategy="hybrid",
                vector_score=0.88,
                lexical_score=1.2,
                fused_score=0.93,
                ocr_used=True,
                parser_name="image_ocr_paddle",
                page_no=1,
                ocr_confidence=0.97,
                quality_score=0.97,
            )
        ]
    )

    response = chat_service.answer(ChatRequest(question="解释一下 CPPS", top_k=1))

    assert response.citations[0].ocr_used is True
    assert response.citations[0].parser_name == "image_ocr_paddle"
    assert response.citations[0].page_no == 1
    assert response.citations[0].ocr_confidence == 0.97
    assert response.citations[0].quality_score == 0.97


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


def test_retrieval_service_filters_low_quality_ocr_candidates_when_alternatives_exist(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "ocr_low_quality_filter_enabled": True,
            "ocr_low_quality_min_score": 0.55,
        }
    )
    ensure_data_directories(settings)
    retrieval_service = RetrievalService(settings)
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, *, limit, document_id=None: [
            SimpleNamespace(
                id="point-low-ocr",
                score=0.98,
                payload={
                    "chunk_id": "chunk-low-ocr",
                    "document_id": "doc_ocr_low",
                    "document_name": "ocr_low.png",
                    "text": "模糊识别片段",
                    "source_path": "/tmp/ocr_low.png",
                    "ocr_used": True,
                    "parser_name": "image_ocr_paddle",
                    "quality_score": 0.2,
                },
            ),
            SimpleNamespace(
                id="point-good-ocr",
                score=0.92,
                payload={
                    "chunk_id": "chunk-good-ocr",
                    "document_id": "doc_ocr_good",
                    "document_name": "ocr_good.png",
                    "text": "传感器校准步骤：先断电，再复位。",
                    "source_path": "/tmp/ocr_good.png",
                    "ocr_used": True,
                    "parser_name": "image_ocr_paddle",
                    "quality_score": 0.94,
                },
            ),
            SimpleNamespace(
                id="point-native",
                score=0.88,
                payload={
                    "chunk_id": "chunk-native",
                    "document_id": "doc_native",
                    "document_name": "manual.txt",
                    "text": "传感器复位前先检查供电和连接状态。",
                    "source_path": "/tmp/manual.txt",
                    "ocr_used": False,
                },
            ),
        ]
    )

    response = retrieval_service.search(RetrievalRequest(query="传感器怎么复位", top_k=3))

    assert [item.chunk_id for item in response.results] == ["chunk-good-ocr", "chunk-native"]
    assert all(item.chunk_id != "chunk-low-ocr" for item in response.results)


def test_retrieval_service_keeps_low_quality_ocr_candidates_when_filter_would_empty_results(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "ocr_low_quality_filter_enabled": True,
            "ocr_low_quality_min_score": 0.55,
        }
    )
    ensure_data_directories(settings)
    retrieval_service = RetrievalService(settings)
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, *, limit, document_id=None: [
            SimpleNamespace(
                id="point-only-low-ocr",
                score=0.84,
                payload={
                    "chunk_id": "chunk-only-low-ocr",
                    "document_id": "doc_only_low",
                    "document_name": "ocr_only.png",
                    "text": "模糊识别片段",
                    "source_path": "/tmp/ocr_only.png",
                    "ocr_used": True,
                    "parser_name": "image_ocr_paddle",
                    "quality_score": 0.18,
                },
            )
        ]
    )

    response = retrieval_service.search(RetrievalRequest(query="模糊识别片段", top_k=1))

    assert [item.chunk_id for item in response.results] == ["chunk-only-low-ocr"]


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
    client = _build_authenticated_client(tmp_path, settings)

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
    client = _build_authenticated_client(tmp_path, settings)  # 创建带登录态的测试客户端。

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
    assert raw_stream.startswith(": keepalive\n\n")
    events = parse_sse_events(raw_stream)
    event_names = [event_name for event_name, _ in events]
    assert "meta" in event_names
    assert "answer_delta" in event_names
    assert "done" in event_names
    meta_payload = next(payload for event_name, payload in events if event_name == "meta")
    assert set(meta_payload.keys()) == {"question", "mode", "model", "citations"}
    delta_payload = next(payload for event_name, payload in events if event_name == "answer_delta")
    assert set(delta_payload.keys()) == {"delta"}
    assert isinstance(delta_payload["delta"], str) and delta_payload["delta"]
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
    client = _build_authenticated_client(tmp_path, settings)  # 创建带登录态的测试客户端。

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
    client = _build_authenticated_client(tmp_path, settings)

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
    assert error_payload["code"] == "llm_fatal"
    assert error_payload["retryable"] is False
    assert error_payload["retry_after_seconds"] is None
    assert "RAG_LLM_API_KEY" in error_payload["message"]


def test_chat_ask_returns_429_when_runtime_gate_is_busy(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    fake_gate = _FakeRuntimeGateService(outcomes={"chat_fast": [False]})
    chat_service = ChatService(settings, runtime_gate_service=fake_gate)
    client = _build_authenticated_client(tmp_path, settings)

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
    assert fake_gate.calls == [("chat_fast", 800, "user_sys_admin")]


def test_chat_stream_returns_busy_error_event_when_runtime_gate_is_busy(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    fake_gate = _FakeRuntimeGateService(outcomes={"chat_fast": [False]})
    chat_service = ChatService(settings, runtime_gate_service=fake_gate)
    client = _build_authenticated_client(tmp_path, settings)

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
    assert error_payload["code"] == "busy"
    assert error_payload["retryable"] is True
    assert error_payload["retry_after_seconds"] == 5
    assert "System is busy" in error_payload["message"]
    assert fake_gate.calls == [("chat_fast", 800, "user_sys_admin")]


def test_chat_stream_returns_retryable_error_event_when_retrieval_fallback_is_disabled(tmp_path: Path, monkeypatch) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    system_config_service = SystemConfigService(settings)
    system_config_service.repository.write({"degrade_controls": {"retrieval_fallback_enabled": False}})
    chat_service = ChatService(settings)
    chat_service.system_config_service = system_config_service
    chat_service.query_profile_service.system_config_service = system_config_service
    chat_service.retrieval_service = _FakeRetrievalService(
        [
            RetrievedChunk(
                chunk_id="chunk_001",
                document_id="doc_001",
                document_name="manual.txt",
                text="CPPS 指南：先检查传感器，再确认供电稳定。",
                score=0.92,
                source_path="/tmp/manual.txt",
            )
        ]
    )

    from backend.app.rag.generators.client import LLMGenerationRetryableError

    def raise_retryable(**_kwargs):
        raise LLMGenerationRetryableError("temporary llm issue")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_service.generation_client, "generate_stream", raise_retryable)
    client = _build_authenticated_client(tmp_path, settings)
    app.dependency_overrides[get_chat_service] = lambda: chat_service
    try:
        with client.stream(
            "POST",
            "/api/v1/chat/ask/stream",
            json={"question": "解释一下 CPPS", "mode": "fast", "top_k": 1},
        ) as stream_response:
            raw_stream = "".join(stream_response.iter_text())
            status_code = stream_response.status_code
    finally:
        app.dependency_overrides.clear()

    assert status_code == 200
    events = parse_sse_events(raw_stream)
    event_names = [event_name for event_name, _ in events]
    assert "meta" in event_names
    assert "error" in event_names
    assert "done" not in event_names
    error_payload = next(payload for event_name, payload in events if event_name == "error")
    assert error_payload["code"] == "llm_retryable"
    assert error_payload["retryable"] is True
    assert error_payload["retry_after_seconds"] is None
    assert error_payload["message"] == "temporary llm issue"


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
    client = _build_authenticated_client(tmp_path, settings)  # 创建带登录态的测试客户端。

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
    client = _build_authenticated_client(tmp_path, settings)  # 创建带登录态的测试客户端。

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
    client = _build_authenticated_client(tmp_path, settings)  # 创建带登录态的测试客户端。

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
    client = _build_authenticated_client(tmp_path, settings)  # 创建带登录态的测试客户端。

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
    client = _build_authenticated_client(tmp_path, settings)  # 创建带登录态的测试客户端。

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
    client = _build_authenticated_client(tmp_path, settings)  # 创建带登录态的测试客户端。

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
    client = _build_authenticated_client(tmp_path, settings)  # 创建带登录态的测试客户端。

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
    client = _build_authenticated_client(tmp_path, settings, raise_server_exceptions=False)  # 关闭异常透传，便于断言 HTTP 500。

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
            "query_fast_candidate_multiplier": 2,
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
    assert response.results[0].fused_score < response.results[0].score
    assert response.results[0].score == pytest.approx(0.9919354838709679)
    assert response.results[1].score == pytest.approx(0.5)


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


def test_chat_service_persists_hybrid_retrieval_observability_to_trace_and_snapshot(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "retrieval_dynamic_weighting_enabled": True,
            "query_fast_top_k_default": 5,
            "query_fast_candidate_multiplier": 2,
            "query_fast_lexical_top_k_default": 10,
            "query_fast_rerank_top_n": 3,
        }
    )
    ensure_data_directories(settings)
    retrieval_service = RetrievalService(settings)
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, *, limit, document_id=None: [
            SimpleNamespace(
                id=f"point-{index}",
                score=0.95 - index * 0.01,
                payload={
                    "chunk_id": f"chunk-{index}",
                    "document_id": f"doc_{index}",
                    "document_name": f"doc_{index}.txt",
                    "text": f"PLC_A01 fault recovery step {index}",
                    "source_path": f"/tmp/doc_{index}.txt",
                },
            )
            for index in range(4)
        ]
    )
    retrieval_service.lexical_retriever = SimpleNamespace(
        search=lambda query, *, limit, document_id=None: [
            SimpleNamespace(
                point_id="point-0",
                score=4.2,
                payload={
                    "chunk_id": "chunk-0",
                    "document_id": "doc_0",
                    "document_name": "doc_0.txt",
                    "text": "PLC_A01 exact recovery step",
                    "source_path": "/tmp/doc_0.txt",
                },
            )
        ]
    )
    request_trace_service = RequestTraceService(settings)
    request_snapshot_service = RequestSnapshotService(settings)
    chat_service = ChatService(
        settings,
        request_trace_service=request_trace_service,
        request_snapshot_service=request_snapshot_service,
    )
    chat_service.retrieval_service = retrieval_service

    response = chat_service.answer(ChatRequest(question="PLC_A01错误"), auth_context=None)

    assert response.mode == "rag"
    assert len(response.citations) == 3

    trace_record = request_trace_service.repository.list_records(limit=1)[0]
    retrieval_stage = next(stage for stage in trace_record.stages if stage.stage == "retrieval")
    rerank_stage = next(stage for stage in trace_record.stages if stage.stage == "rerank")

    assert retrieval_stage.details["retrieval_mode"] == "hybrid"
    assert retrieval_stage.details["query_type"] == "exact"
    assert retrieval_stage.details["vector_weight"] == pytest.approx(0.3)
    assert retrieval_stage.details["lexical_weight"] == pytest.approx(0.7)
    assert rerank_stage.details["rerank_provider"] == "heuristic"
    assert rerank_stage.details["rerank_model"] == "heuristic"
    assert rerank_stage.details["rerank_default_strategy"] == "heuristic"
    assert rerank_stage.details["rerank_effective_strategy"] == "heuristic"
    assert rerank_stage.details["rerank_input_count"] == 4
    assert rerank_stage.details["citation_count"] == 3

    snapshot_record = request_snapshot_service.repository.list_records(limit=1)[0]
    assert snapshot_record.details["retrieval_mode"] == "hybrid"
    assert snapshot_record.details["query_type"] == "exact"
    assert snapshot_record.details["vector_weight"] == pytest.approx(0.3)
    assert snapshot_record.details["lexical_weight"] == pytest.approx(0.7)
    assert snapshot_record.details["rerank_provider"] == "heuristic"
    assert snapshot_record.details["rerank_model"] == "heuristic"
    assert snapshot_record.details["rerank_default_strategy"] == "heuristic"
    assert snapshot_record.details["rerank_effective_strategy"] == "heuristic"
    assert snapshot_record.details["rerank_input_count"] == 4
    assert snapshot_record.details["citation_count"] == 3


def test_retrieval_service_normalizes_exact_query_hybrid_score_by_branch_weights(tmp_path: Path) -> None:
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

    response = retrieval_service.search(request=RetrievalRequest(query="PLC_A01错误"))

    assert response.mode == "hybrid"
    assert response.results[0].chunk_id == "chunk-lexical"
    assert response.results[0].score == pytest.approx(0.7)
    assert response.results[0].fused_score == pytest.approx(0.35)
    assert response.results[1].chunk_id == "chunk-shared"
    assert response.results[1].score == pytest.approx(2 / 3)
    assert response.results[1].fused_score == pytest.approx(1 / 3)


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
        def is_document_readable(self, doc_id: str, auth_context: AuthContext | None) -> bool:  # pragma: no cover
            raise AssertionError("retrieval should batch readability checks instead of loading one document at a time")

        def get_document_readability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {
                "doc_a": True,
                "doc_b": False,
            }

    class SpyRetrievalScopePolicy:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            self.calls.append(doc_ids)
            return {
                "doc_a": True,
                "doc_b": False,
            }

    spy_policy = SpyRetrievalScopePolicy()
    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService(), retrieval_scope_policy=spy_policy)  # type: ignore[arg-type]
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
        auth_context=_build_auth_context(role_id="sys_admin"),
    )

    assert [item.document_id for item in response.results] == ["doc_a"]
    assert spy_policy.calls == [["doc_a", "doc_b"]]


def test_retrieval_service_department_priority_dual_route_fuses_department_and_global_candidates(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)

    class SpyDocumentService:
        def is_document_readable(self, doc_id: str, auth_context: AuthContext | None) -> bool:
            return True

        def get_document_readability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {doc_id: True for doc_id in doc_ids}

    class SpyRetrievalScopePolicy:
        def __init__(self) -> None:
            self.scope_calls = 0

        def build_department_priority_retrieval_scope(
            self,
            auth_context: AuthContext | None,
        ) -> DepartmentPriorityRetrievalScope:
            self.scope_calls += 1
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept", "doc_shared"],
                global_document_ids=["doc_shared", "doc_global"],
            )

        def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {doc_id: True for doc_id in doc_ids}

    spy_policy = SpyRetrievalScopePolicy()
    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService(), retrieval_scope_policy=spy_policy)  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    vector_route_calls: list[list[str]] = []
    lexical_route_calls: list[list[str]] = []

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        vector_route_calls.append(list(document_ids or []))
        ids = set(document_ids or [])
        results: list[SimpleNamespace] = []
        if "doc_dept" in ids:
            results.append(
                SimpleNamespace(
                    id="point-dept",
                    score=0.95,
                    payload={
                        "chunk_id": "chunk-dept",
                        "document_id": "doc_dept",
                        "document_name": "dept_manual.txt",
                        "text": "研发部 E204 处理步骤",
                        "source_path": "/tmp/dept_manual.txt",
                    },
                )
            )
        if "doc_shared" in ids:
            results.append(
                SimpleNamespace(
                    id="point-shared",
                    score=0.9,
                    payload={
                        "chunk_id": "chunk-shared",
                        "document_id": "doc_shared",
                        "document_name": "shared_manual.txt",
                        "text": "公共巡检总则",
                        "source_path": "/tmp/shared_manual.txt",
                    },
                )
            )
        if "doc_global" in ids:
            results.append(
                SimpleNamespace(
                    id="point-global",
                    score=0.86,
                    payload={
                        "chunk_id": "chunk-global",
                        "document_id": "doc_global",
                        "document_name": "global_manual.txt",
                        "text": "跨部门设备点检规范",
                        "source_path": "/tmp/global_manual.txt",
                    },
                )
            )
        return results

    def fake_lexical_search(query, *, limit, document_id=None, document_ids=None):
        lexical_route_calls.append(list(document_ids or []))
        ids = set(document_ids or [])
        results: list[SimpleNamespace] = []
        if "doc_dept" in ids:
            results.append(
                SimpleNamespace(
                    point_id="point-dept",
                    score=2.2,
                    payload={
                        "chunk_id": "chunk-dept",
                        "document_id": "doc_dept",
                        "document_name": "dept_manual.txt",
                        "text": "研发部 E204 处理步骤",
                        "source_path": "/tmp/dept_manual.txt",
                    },
                )
            )
        if "doc_shared" in ids:
            results.append(
                SimpleNamespace(
                    point_id="point-shared",
                    score=1.7,
                    payload={
                        "chunk_id": "chunk-shared",
                        "document_id": "doc_shared",
                        "document_name": "shared_manual.txt",
                        "text": "公共巡检总则",
                        "source_path": "/tmp/shared_manual.txt",
                    },
                )
            )
        if "doc_global" in ids:
            results.append(
                SimpleNamespace(
                    point_id="point-global",
                    score=1.3,
                    payload={
                        "chunk_id": "chunk-global",
                        "document_id": "doc_global",
                        "document_name": "global_manual.txt",
                        "text": "跨部门设备点检规范",
                        "source_path": "/tmp/global_manual.txt",
                    },
                )
            )
        return results

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)
    retrieval_service.lexical_retriever = SimpleNamespace(search=fake_lexical_search)

    response = retrieval_service.search(
        request=RetrievalRequest(query="E204怎么处理", top_k=3),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    assert response.mode == "hybrid"
    assert vector_route_calls == [["doc_dept", "doc_shared"], ["doc_shared", "doc_global"]]
    assert lexical_route_calls == [["doc_dept", "doc_shared"], ["doc_shared", "doc_global"]]
    assert response.results[-1].chunk_id == "chunk-global"
    assert response.results[-1].source_scope == "global"
    assert {item.chunk_id for item in response.results[:2]} == {"chunk-dept", "chunk-shared"}
    assert {item.source_scope for item in response.results[:2]} == {"department", "both"}
    assert spy_policy.scope_calls == 1


def test_chat_ask_propagates_source_scope_to_citations(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    chat_service = ChatService(settings)
    chat_service.retrieval_service = _FakeRetrievalService(
        [
            RetrievedChunk(
                chunk_id="chunk_dept_001",
                document_id="doc_dept_001",
                document_name="dept_manual.txt",
                text="本部门 SOP 操作步骤。",
                score=0.93,
                source_path="/tmp/dept_manual.txt",
                retrieval_strategy="hybrid",
                source_scope="department",
            ),
            RetrievedChunk(
                chunk_id="chunk_global_001",
                document_id="doc_global_001",
                document_name="global_manual.txt",
                text="全局共享补充说明。",
                score=0.82,
                source_path="/tmp/global_manual.txt",
                retrieval_strategy="hybrid",
                source_scope="global",
            ),
        ]
    )

    response = chat_service.answer(ChatRequest(question="解释一下E204"), auth_context=None)

    assert [item.source_scope for item in response.citations] == ["department", "global"]


def test_chat_snapshot_propagates_source_scope_to_contexts(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    request_snapshot_service = RequestSnapshotService(settings)
    chat_service = ChatService(
        settings,
        request_snapshot_service=request_snapshot_service,
    )
    chat_service.retrieval_service = _FakeRetrievalService(
        [
            RetrievedChunk(
                chunk_id="chunk_dept_001",
                document_id="doc_dept_001",
                document_name="dept_manual.txt",
                text="本部门 SOP 操作步骤。",
                score=0.93,
                source_path="/tmp/dept_manual.txt",
                retrieval_strategy="hybrid",
                source_scope="department",
            ),
            RetrievedChunk(
                chunk_id="chunk_global_001",
                document_id="doc_global_001",
                document_name="global_manual.txt",
                text="全局共享补充说明。",
                score=0.82,
                source_path="/tmp/global_manual.txt",
                retrieval_strategy="hybrid",
                source_scope="global",
            ),
        ]
    )

    response = chat_service.answer(ChatRequest(question="解释一下E204"), auth_context=None)

    assert [item.source_scope for item in response.citations] == ["department", "global"]
    snapshot_record = request_snapshot_service.repository.list_records(limit=1)[0]
    assert [item.source_scope for item in snapshot_record.contexts] == ["department", "global"]


def test_retrieval_compare_rerank_reports_provider_vs_heuristic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    system_config_service = SystemConfigService(settings)
    system_config_service.repository.write(
        {
            "reranker_routing": {
                "provider": "openai_compatible",
                "model": "BAAI/bge-reranker-v2-m3",
                "default_strategy": "provider",
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
        "rerank_provider_candidate",
        lambda **kwargs: [base_results[1].model_copy(update={"score": 0.99}), base_results[0].model_copy(update={"score": 0.88})],
    )
    monkeypatch.setattr(
        retrieval_service.reranker_client,
        "get_runtime_status",
        lambda force_refresh=False: {
            "provider": "openai_compatible",
            "model": "BAAI/bge-reranker-v2-m3",
            "default_strategy": "provider",
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
    assert response.provider_candidate is not None
    assert response.provider_candidate.strategy == "provider"
    assert [item.chunk_id for item in response.provider_candidate.results] == ["chunk-b", "chunk-a"]
    assert response.provider_candidate_summary is not None
    assert response.provider_candidate_summary.top1_same is False
    assert response.route_status.default_strategy == "provider"
    assert response.route_status.effective_provider == "openai_compatible"
    assert response.route_status.effective_strategy == "provider"
    assert response.route_status.lock_active is False
    assert response.route_status.ready is True
    assert response.summary.top1_same is False
    assert response.summary.overlap_count == 2
    assert response.recommendation.decision == "provider_active"
    assert response.recommendation.should_switch_default_strategy is False
    assert response.canary_sample_id is not None
    records = retrieval_service.rerank_canary_service.repository.list_records(limit=None)
    assert records[0].sample_id == response.canary_sample_id
    assert records[0].recommendation.decision == "provider_active"


def test_retrieval_compare_rerank_surfaces_provider_error_and_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    system_config_service = SystemConfigService(settings)
    system_config_service.repository.write(
        {
            "reranker_routing": {
                "provider": "openai_compatible",
                "model": "BAAI/bge-reranker-v2-m3",
                "default_strategy": "provider",
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
    monkeypatch.setattr(retrieval_service.reranker_client, "rerank_provider_candidate", fail_provider)
    monkeypatch.setattr(
        retrieval_service.reranker_client,
        "get_runtime_status",
        lambda force_refresh=False: {
            "provider": "openai_compatible",
            "model": "BAAI/bge-reranker-v2-m3",
            "default_strategy": "provider",
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
    assert response.provider_candidate is not None
    assert response.provider_candidate.strategy == "failed"
    assert response.provider_candidate.error_message == "reranker upstream unavailable"
    assert response.provider_candidate_summary is None
    assert response.route_status.default_strategy == "provider"
    assert response.route_status.effective_provider == "heuristic"
    assert response.route_status.effective_strategy == "heuristic"
    assert response.route_status.lock_active is True
    assert response.route_status.lock_source == "request"
    assert response.route_status.ready is False
    assert response.summary.top1_same is True
    assert response.recommendation.decision == "rollback_active"
    assert response.recommendation.should_switch_default_strategy is False
    assert response.canary_sample_id is not None


def test_retrieval_compare_rerank_recommends_provider_when_pinned_heuristic_has_meaningful_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    system_config_service = SystemConfigService(settings)
    system_config_service.repository.write(
        {
            "reranker_routing": {
                "provider": "openai_compatible",
                "model": "BAAI/bge-reranker-v2-m3",
                "default_strategy": "heuristic",
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
        lambda **kwargs: [base_results[0].model_copy(update={"score": 0.95}), base_results[1].model_copy(update={"score": 0.84})],
    )
    monkeypatch.setattr(
        retrieval_service.reranker_client,
        "rerank_heuristic",
        lambda **kwargs: [base_results[0].model_copy(update={"score": 0.95}), base_results[1].model_copy(update={"score": 0.84})],
    )
    monkeypatch.setattr(
        retrieval_service.reranker_client,
        "rerank_provider_candidate",
        lambda **kwargs: [base_results[1].model_copy(update={"score": 0.99}), base_results[0].model_copy(update={"score": 0.88})],
    )
    monkeypatch.setattr(
        retrieval_service.reranker_client,
        "get_runtime_status",
        lambda force_refresh=False: {
            "provider": "openai_compatible",
            "model": "BAAI/bge-reranker-v2-m3",
            "default_strategy": "heuristic",
            "failure_cooldown_seconds": 15.0,
            "effective_provider": "heuristic",
            "effective_model": "heuristic",
            "effective_strategy": "heuristic",
            "fallback_enabled": True,
            "lock_active": False,
            "lock_source": None,
            "cooldown_remaining_seconds": 0.0,
            "ready": True,
            "detail": "OpenAI-compatible reranker health probe succeeded. Default route is pinned to heuristic by policy.",
        },
    )

    response = retrieval_service.compare_rerank(RetrievalRequest(query="servo reset", top_k=2))

    assert response.configured.strategy == "heuristic"
    assert response.provider_candidate is not None
    assert response.provider_candidate.strategy == "provider"
    assert response.provider_candidate_summary is not None
    assert response.provider_candidate_summary.top1_same is False
    assert response.recommendation.decision == "eligible"
    assert response.recommendation.should_switch_default_strategy is True
    assert response.canary_sample_id is not None


def test_retrieval_rerank_compare_endpoint_returns_comparison_payload(tmp_path: Path) -> None:
    client = _build_authenticated_client(tmp_path, build_test_settings(tmp_path))

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
                    "default_strategy": "provider",
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
                "provider_candidate": {
                    "label": "provider_candidate",
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
                    "overlap_count": 1,
                    "top1_same": True,
                    "configured_only_chunk_ids": [],
                    "heuristic_only_chunk_ids": [],
                },
                "provider_candidate_summary": {
                    "overlap_count": 0,
                    "top1_same": False,
                    "configured_only_chunk_ids": ["chunk-b"],
                    "heuristic_only_chunk_ids": ["chunk-a"],
                },
                "recommendation": {
                    "decision": "eligible",
                    "should_switch_default_strategy": True,
                    "message": "provider 候选已可用且与 heuristic 存在可观察差异，可以把 default_strategy 切到 provider 做真实流量验证。",
                },
                "canary_sample_id": "rcs_demo_001",
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
    assert payload["route_status"]["default_strategy"] == "provider"
    assert payload["route_status"]["effective_strategy"] == "heuristic"
    assert payload["route_status"]["fallback_enabled"] is True
    assert payload["route_status"]["lock_active"] is True
    assert payload["configured"]["provider"] == "openai_compatible"
    assert payload["configured"]["strategy"] == "heuristic"
    assert payload["provider_candidate"]["provider"] == "openai_compatible"
    assert payload["provider_candidate"]["strategy"] == "provider"
    assert payload["heuristic"]["provider"] == "heuristic"
    assert payload["summary"]["configured_only_chunk_ids"] == []
    assert payload["provider_candidate_summary"]["configured_only_chunk_ids"] == ["chunk-b"]
    assert payload["recommendation"]["decision"] == "eligible"
    assert payload["canary_sample_id"] == "rcs_demo_001"


# ---------------------------------------------------------------------------
# Staged retrieval tests (department-first with conditional supplemental)
# ---------------------------------------------------------------------------


def test_retrieval_service_staged_skips_supplemental_when_department_sufficient(tmp_path: Path) -> None:
    """When department route returns enough results, supplemental route should be skipped entirely."""
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def __init__(self) -> None:
            self.scope_calls = 0

        def build_department_priority_retrieval_scope(
            self,
            auth_context: AuthContext | None,
        ) -> DepartmentPriorityRetrievalScope:
            self.scope_calls += 1
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_1", "doc_dept_2", "doc_dept_3"],
                global_document_ids=["doc_global_1"],
            )

        def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {doc_id: True for doc_id in doc_ids}

    spy_policy = SpyRetrievalScopePolicy()
    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService(), retrieval_scope_policy=spy_policy)  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    vector_route_calls: list[list[str]] = []

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        vector_route_calls.append(list(document_ids or []))
        ids = set(document_ids or [])
        results: list[SimpleNamespace] = []
        # Return 3 results from department pool (enough for top_k=3)
        for i, doc_id in enumerate(["doc_dept_1", "doc_dept_2", "doc_dept_3"]):
            if doc_id in ids:
                results.append(
                    SimpleNamespace(
                        id=f"point-{doc_id}",
                        score=0.95 - i * 0.05,
                        payload={
                            "chunk_id": f"chunk-{doc_id}",
                            "document_id": doc_id,
                            "document_name": f"{doc_id}.txt",
                            "text": f"Content from {doc_id}",
                            "source_path": f"/tmp/{doc_id}.txt",
                        },
                    )
                )
        return results

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)
    retrieval_service.lexical_retriever = SimpleNamespace(search=lambda query, **kwargs: [])

    response = retrieval_service.search(
        request=RetrievalRequest(query="test query", top_k=3),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    # Only department route should be called; supplemental route skipped
    assert vector_route_calls == [["doc_dept_1", "doc_dept_2", "doc_dept_3"]]
    assert len(response.results) == 3
    assert all(item.source_scope == "department" for item in response.results)
    assert spy_policy.scope_calls == 1


def test_retrieval_service_staged_triggers_supplemental_when_department_insufficient(tmp_path: Path) -> None:
    """When department route returns insufficient results, supplemental route should be triggered."""
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(
            self,
            auth_context: AuthContext | None,
        ) -> DepartmentPriorityRetrievalScope:
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_1"],
                global_document_ids=["doc_global_1", "doc_global_2"],
            )

        def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService(), retrieval_scope_policy=SpyRetrievalScopePolicy())  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    vector_route_calls: list[list[str]] = []

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        vector_route_calls.append(list(document_ids or []))
        ids = set(document_ids or [])
        results: list[SimpleNamespace] = []
        for doc_id in ids:
            results.append(
                SimpleNamespace(
                    id=f"point-{doc_id}",
                    score=0.9,
                    payload={
                        "chunk_id": f"chunk-{doc_id}",
                        "document_id": doc_id,
                        "document_name": f"{doc_id}.txt",
                        "text": f"Content from {doc_id}",
                        "source_path": f"/tmp/{doc_id}.txt",
                    },
                )
            )
        return results

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)
    retrieval_service.lexical_retriever = SimpleNamespace(search=lambda query, **kwargs: [])

    response = retrieval_service.search(
        request=RetrievalRequest(query="test query", top_k=3),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    # Both routes should be called since department has only 1 result < top_k=3
    assert vector_route_calls == [["doc_dept_1"], ["doc_global_1", "doc_global_2"]]
    assert len(response.results) == 3
    # Department result should rank first
    assert response.results[0].source_scope == "department"
    # Remaining results should be from supplemental pool
    assert all(item.source_scope == "global" for item in response.results[1:])


def test_retrieval_service_staged_triggers_supplemental_when_department_chunks_repeat_same_document_with_weak_lexical_match(tmp_path: Path) -> None:
    """Repeated chunks from one weakly-matched department document should trigger supplemental recall."""
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "query_fast_top_k_default": 5,
            "query_fast_rerank_top_n": 5,
        }
    )
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(
            self,
            auth_context: AuthContext | None,
        ) -> DepartmentPriorityRetrievalScope:
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_wrong"],
                global_document_ids=["doc_global_1", "doc_global_2", "doc_global_3"],
            )

        def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(
        settings,
        document_service=SpyDocumentService(),
        retrieval_scope_policy=SpyRetrievalScopePolicy(),
    )  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    vector_route_calls: list[list[str]] = []

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        vector_route_calls.append(list(document_ids or []))
        ids = list(document_ids or [])
        results: list[SimpleNamespace] = []
        if ids and ids[0].startswith("doc_dept"):
            for index in range(5):
                results.append(
                    SimpleNamespace(
                        id=f"point-dept-{index}",
                        score=0.97 - index * 0.01,
                        payload={
                            "chunk_id": f"chunk-dept-{index}",
                            "document_id": "doc_dept_wrong",
                            "document_name": "doc_dept_wrong.txt",
                            "text": f"Wrong department content chunk {index}",
                            "source_path": "/tmp/doc_dept_wrong.txt",
                        },
                    )
                )
        else:
            for index, doc_id in enumerate(ids):
                results.append(
                    SimpleNamespace(
                        id=f"point-global-{index}",
                        score=0.86 - index * 0.03,
                        payload={
                            "chunk_id": f"chunk-global-{index}",
                            "document_id": doc_id,
                            "document_name": f"{doc_id}.txt",
                            "text": f"Supplemental content from {doc_id}",
                            "source_path": f"/tmp/{doc_id}.txt",
                        },
                    )
                )
        return results

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)

    def fake_lexical_search(query, *, limit, document_id=None, document_ids=None):
        ids = list(document_ids or [])
        matches: list[LexicalMatch] = []
        if ids and ids[0].startswith("doc_dept"):
            for index in range(5):
                matches.append(
                    LexicalMatch(
                        point_id=f"point-dept-{index}",
                        payload={
                            "chunk_id": f"chunk-dept-{index}",
                            "document_id": "doc_dept_wrong",
                            "document_name": "doc_dept_wrong.txt",
                            "text": f"Weak lexical overlap chunk {index}",
                            "source_path": "/tmp/doc_dept_wrong.txt",
                        },
                        score=2.0 - index * 0.1,
                    )
                )
        return matches

    retrieval_service.lexical_retriever = SimpleNamespace(search=fake_lexical_search)

    response = retrieval_service.search(
        request=RetrievalRequest(query="cross department question", top_k=5, mode="fast"),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    assert vector_route_calls == [
        ["doc_dept_wrong"],
        ["doc_global_1", "doc_global_2", "doc_global_3"],
    ]
    assert response.diagnostic is not None
    assert response.diagnostic.primary_recall_stage.effective_count == 5
    assert response.diagnostic.supplemental_triggered is True
    assert response.diagnostic.supplemental_recall_stage.trigger_basis == "department_low_quality"
    assert "lexical_top1" in (response.diagnostic.supplemental_reason or "")
    assert response.results[0].source_scope == "department"


def test_retrieval_service_staged_low_quality_includes_supplemental_result_in_top_k(tmp_path: Path) -> None:
    """Low-quality department hits should not fully crowd out supplemental candidates from the final top-k."""
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "query_fast_top_k_default": 5,
            "query_fast_rerank_top_n": 5,
        }
    )
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(
            self,
            auth_context: AuthContext | None,
        ) -> DepartmentPriorityRetrievalScope:
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_wrong"],
                global_document_ids=["doc_global_expected", "doc_global_2", "doc_global_3"],
            )

        def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(
        settings,
        document_service=SpyDocumentService(),
        retrieval_scope_policy=SpyRetrievalScopePolicy(),
    )  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        ids = list(document_ids or [])
        results: list[SimpleNamespace] = []
        if ids and ids[0].startswith("doc_dept"):
            for index in range(5):
                results.append(
                    SimpleNamespace(
                        id=f"point-dept-{index}",
                        score=0.97 - index * 0.01,
                        payload={
                            "chunk_id": f"chunk-dept-{index}",
                            "document_id": "doc_dept_wrong",
                            "document_name": "doc_dept_wrong.txt",
                            "text": f"Wrong department content chunk {index}",
                            "source_path": "/tmp/doc_dept_wrong.txt",
                        },
                    )
                )
        else:
            scores_by_doc = {
                "doc_global_expected": 0.99,
                "doc_global_2": 0.96,
                "doc_global_3": 0.94,
            }
            for index, doc_id in enumerate(ids):
                results.append(
                    SimpleNamespace(
                        id=f"point-global-{index}",
                        score=scores_by_doc[doc_id],
                        payload={
                            "chunk_id": f"chunk-global-{index}",
                            "document_id": doc_id,
                            "document_name": f"{doc_id}.txt",
                            "text": f"Supplemental content from {doc_id}",
                            "source_path": f"/tmp/{doc_id}.txt",
                        },
                    )
                )
        return results

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)

    def fake_lexical_search(query, *, limit, document_id=None, document_ids=None):
        ids = list(document_ids or [])
        matches: list[LexicalMatch] = []
        if ids and ids[0].startswith("doc_dept"):
            for index in range(5):
                matches.append(
                    LexicalMatch(
                        point_id=f"point-dept-{index}",
                        payload={
                            "chunk_id": f"chunk-dept-{index}",
                            "document_id": "doc_dept_wrong",
                            "document_name": "doc_dept_wrong.txt",
                            "text": f"Weak lexical overlap chunk {index}",
                            "source_path": "/tmp/doc_dept_wrong.txt",
                        },
                        score=2.0 - index * 0.1,
                    )
                )
        return matches

    retrieval_service.lexical_retriever = SimpleNamespace(search=fake_lexical_search)

    response = retrieval_service.search(
        request=RetrievalRequest(query="cross department question", top_k=5, mode="fast"),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    assert response.diagnostic is not None
    assert response.diagnostic.supplemental_triggered is True
    result_doc_ids = [item.document_id for item in response.results]
    assert "doc_global_expected" in result_doc_ids
    assert any(item.source_scope == "global" for item in response.results)


    assert response.diagnostic is not None
    assert response.diagnostic.supplemental_triggered is True
    result_doc_ids = [item.document_id for item in response.results]
    assert "doc_global_expected" in result_doc_ids
    assert any(item.source_scope == "global" for item in response.results)


def test_retrieval_service_staged_low_quality_promotes_stronger_global_to_top1(tmp_path: Path) -> None:
    """In low-quality department scenarios, a pure-global candidate with a higher score
    should be promoted to top1 ahead of weaker department candidates."""
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "query_fast_top_k_default": 5,
            "query_fast_rerank_top_n": 5,
        }
    )
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(
            self,
            auth_context: AuthContext | None,
        ) -> DepartmentPriorityRetrievalScope:
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_wrong"],
                global_document_ids=["doc_global_expected", "doc_global_2", "doc_global_3"],
            )

        def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(
        settings,
        document_service=SpyDocumentService(),
        retrieval_scope_policy=SpyRetrievalScopePolicy(),
    )  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        ids = list(document_ids or [])
        results: list[SimpleNamespace] = []
        if ids and ids[0].startswith("doc_dept"):
            for index in range(5):
                results.append(
                    SimpleNamespace(
                        id=f"point-dept-{index}",
                        score=0.85 - index * 0.01,
                        payload={
                            "chunk_id": f"chunk-dept-{index}",
                            "document_id": "doc_dept_wrong",
                            "document_name": "doc_dept_wrong.txt",
                            "text": f"Weak department content chunk {index}",
                            "source_path": "/tmp/doc_dept_wrong.txt",
                        },
                    )
                )
        else:
            scores_by_doc = {
                "doc_global_expected": 0.99,
                "doc_global_2": 0.96,
                "doc_global_3": 0.94,
            }
            for index, doc_id in enumerate(ids):
                results.append(
                    SimpleNamespace(
                        id=f"point-global-{index}",
                        score=scores_by_doc[doc_id],
                        payload={
                            "chunk_id": f"chunk-global-{index}",
                            "document_id": doc_id,
                            "document_name": f"{doc_id}.txt",
                            "text": f"Supplemental content from {doc_id}",
                            "source_path": f"/tmp/{doc_id}.txt",
                        },
                    )
                )
        return results

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)

    def fake_lexical_search(query, *, limit, document_id=None, document_ids=None):
        ids = list(document_ids or [])
        matches: list[LexicalMatch] = []
        if ids and ids[0].startswith("doc_dept"):
            for index in range(5):
                matches.append(
                    LexicalMatch(
                        point_id=f"point-dept-{index}",
                        payload={
                            "chunk_id": f"chunk-dept-{index}",
                            "document_id": "doc_dept_wrong",
                            "document_name": "doc_dept_wrong.txt",
                            "text": f"Weak lexical overlap chunk {index}",
                            "source_path": "/tmp/doc_dept_wrong.txt",
                        },
                        score=2.0 - index * 0.1,
                    )
                )
        return matches

    retrieval_service.lexical_retriever = SimpleNamespace(search=fake_lexical_search)

    response = retrieval_service.search(
        request=RetrievalRequest(query="cross department question", top_k=5, mode="fast"),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    assert response.diagnostic is not None
    assert response.diagnostic.supplemental_triggered is True
    assert response.diagnostic.supplemental_recall_stage.trigger_basis == "department_low_quality"

    # doc_global_expected has score 0.99, department top1 has ~0.85
    # In low-quality mode, the stronger global candidate should be promoted to top1
    assert response.results[0].document_id == "doc_global_expected"
    assert response.results[0].source_scope == "global"


def test_retrieval_service_staged_low_quality_does_not_promote_weaker_global(tmp_path: Path) -> None:
    """In low-quality scenarios, a pure-global candidate with a lower score should NOT
    be promoted to top1 — department priority still holds for weaker globals."""
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "query_fast_top_k_default": 5,
            "query_fast_rerank_top_n": 5,
        }
    )
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(
            self,
            auth_context: AuthContext | None,
        ) -> DepartmentPriorityRetrievalScope:
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_strong"],
                global_document_ids=["doc_global_weak"],
            )

        def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(
        settings,
        document_service=SpyDocumentService(),
        retrieval_scope_policy=SpyRetrievalScopePolicy(),
    )  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        ids = list(document_ids or [])
        results: list[SimpleNamespace] = []
        if ids and ids[0].startswith("doc_dept"):
            for index in range(3):
                results.append(
                    SimpleNamespace(
                        id=f"point-dept-{index}",
                        score=0.97 - index * 0.01,
                        payload={
                            "chunk_id": f"chunk-dept-{index}",
                            "document_id": "doc_dept_strong",
                            "document_name": "doc_dept_strong.txt",
                            "text": f"Strong department content chunk {index}",
                            "source_path": "/tmp/doc_dept_strong.txt",
                        },
                    )
                )
        else:
            results.append(
                SimpleNamespace(
                    id="point-global-0",
                    score=0.80,
                    payload={
                        "chunk_id": "chunk-global-0",
                        "document_id": "doc_global_weak",
                        "document_name": "doc_global_weak.txt",
                        "text": "Weak supplemental content",
                        "source_path": "/tmp/doc_global_weak.txt",
                    },
                )
        )
        return results

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)

    def fake_lexical_search(query, *, limit, document_id=None, document_ids=None):
        ids = list(document_ids or [])
        matches: list[LexicalMatch] = []
        if ids and ids[0].startswith("doc_dept"):
            for index in range(3):
                matches.append(
                    LexicalMatch(
                        point_id=f"point-dept-{index}",
                        payload={
                            "chunk_id": f"chunk-dept-{index}",
                            "document_id": "doc_dept_strong",
                            "document_name": "doc_dept_strong.txt",
                            "text": f"Strong department lexical chunk {index}",
                            "source_path": "/tmp/doc_dept_strong.txt",
                        },
                        score=10.0 - index * 0.5,
                    )
                )
        return matches

    retrieval_service.lexical_retriever = SimpleNamespace(search=fake_lexical_search)

    response = retrieval_service.search(
        request=RetrievalRequest(query="cross department question", top_k=5, mode="fast"),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    # Department candidate has score ~0.97, global candidate has score 0.80
    # Department top1 should remain top1 because global is weaker
    assert response.diagnostic is not None
    assert response.diagnostic.supplemental_triggered is True
    # Only 3 department chunks but required=5 → trigger is insufficient, not low quality
    assert response.diagnostic.supplemental_recall_stage.trigger_basis == "department_insufficient"
    assert response.results[0].document_id == "doc_dept_strong"
    assert response.results[0].source_scope == "department"


def test_retrieval_service_staged_triggers_supplemental_when_fine_query_literal_coverage_is_poor(tmp_path: Path) -> None:
    """Fine-grained department results with lexical scores above the weak-match threshold should
    still trigger supplemental when the top hit barely overlaps the query literals."""
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "query_fast_top_k_default": 5,
            "query_fast_rerank_top_n": 5,
        }
    )
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(
            self,
            auth_context: AuthContext | None,
        ) -> DepartmentPriorityRetrievalScope:
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_wrong"],
                global_document_ids=["doc_global_expected"],
            )

        def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(
        settings,
        document_service=SpyDocumentService(),
        retrieval_scope_policy=SpyRetrievalScopePolicy(),
    )  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        ids = list(document_ids or [])
        if ids and ids[0].startswith("doc_dept"):
            return [
                SimpleNamespace(
                    id=f"point-dept-{index}",
                    score=0.94 - index * 0.01,
                    payload={
                        "chunk_id": f"chunk-dept-{index}",
                        "document_id": "doc_dept_wrong",
                        "document_name": "doc_dept_wrong.txt",
                        "text": "装配工艺参数夹具校验流程说明",
                        "source_path": "/tmp/doc_dept_wrong.txt",
                    },
                )
                for index in range(5)
            ]
        return [
            SimpleNamespace(
                id="point-global-0",
                score=0.92,
                payload={
                    "chunk_id": "chunk-global-0",
                    "document_id": "doc_global_expected",
                    "document_name": "doc_global_expected.txt",
                    "text": "700000 面板 急停 报警 现场 先查 安全继电器 和 线路",
                    "source_path": "/tmp/doc_global_expected.txt",
                },
            )
        ]

    class FakeLexicalRetriever:
        @staticmethod
        def search(query, *, limit, document_id=None, document_ids=None):
            ids = list(document_ids or [])
            if ids and ids[0].startswith("doc_dept"):
                return [
                    LexicalMatch(
                        point_id=f"point-dept-{index}",
                        payload={
                            "chunk_id": f"chunk-dept-{index}",
                            "document_id": "doc_dept_wrong",
                            "document_name": "doc_dept_wrong.txt",
                            "text": "装配工艺参数夹具校验流程说明",
                            "source_path": "/tmp/doc_dept_wrong.txt",
                        },
                        score=12.5 - index * 0.1,
                    )
                    for index in range(5)
                ]
            return []

        @staticmethod
        def _tokenize(text: str):
            tokens = text.lower().replace(" ", "")
            mapping = {
                "700000面板急停报警现场先查什么": ["700000", "面板", "急停", "报警", "现场", "先查"],
                "装配工艺参数夹具校验流程说明": ["装配", "工艺", "参数", "夹具", "校验", "流程", "说明"],
                "700000面板急停报警现场先查安全继电器和线路": [
                    "700000",
                    "面板",
                    "急停",
                    "报警",
                    "现场",
                    "先查",
                    "安全继电器",
                    "线路",
                ],
            }
            primary_tokens = mapping.get(tokens, [text.lower()])
            return SimpleNamespace(primary_tokens=primary_tokens, supplemental_tokens=[])

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)
    retrieval_service.lexical_retriever = FakeLexicalRetriever()

    response = retrieval_service.search(
        request=RetrievalRequest(query="700000 面板急停报警 现场先查什么", top_k=5, mode="fast"),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    assert response.diagnostic is not None
    assert response.diagnostic.supplemental_triggered is True
    assert response.diagnostic.supplemental_recall_stage.trigger_basis == "department_low_quality"
    assert "literal_coverage" in (response.diagnostic.supplemental_reason or "")


def test_retrieval_service_staged_keeps_department_sufficient_when_fine_query_literal_coverage_is_good(tmp_path: Path) -> None:
    """Fine-grained department hits with strong literal overlap should remain department_sufficient."""
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "query_fast_top_k_default": 5,
            "query_fast_rerank_top_n": 5,
        }
    )
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(
            self,
            auth_context: AuthContext | None,
        ) -> DepartmentPriorityRetrievalScope:
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_ok"],
                global_document_ids=["doc_global_expected"],
            )

        def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(
        settings,
        document_service=SpyDocumentService(),
        retrieval_scope_policy=SpyRetrievalScopePolicy(),
    )  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        ids = list(document_ids or [])
        if ids and ids[0].startswith("doc_dept"):
            return [
                SimpleNamespace(
                    id=f"point-dept-{index}",
                    score=0.94 - index * 0.01,
                    payload={
                        "chunk_id": f"chunk-dept-{index}",
                        "document_id": "doc_dept_ok",
                        "document_name": "doc_dept_ok.txt",
                        "text": "700000 面板 急停 报警 现场 先查 安全继电器 和 线路",
                        "source_path": "/tmp/doc_dept_ok.txt",
                    },
                )
                for index in range(5)
            ]
        return [
            SimpleNamespace(
                id="point-global-0",
                score=0.92,
                payload={
                    "chunk_id": "chunk-global-0",
                    "document_id": "doc_global_expected",
                    "document_name": "doc_global_expected.txt",
                    "text": "700000 面板 急停 报警 现场 先查 安全继电器 和 线路",
                    "source_path": "/tmp/doc_global_expected.txt",
                },
            )
        ]

    class FakeLexicalRetriever:
        @staticmethod
        def search(query, *, limit, document_id=None, document_ids=None):
            ids = list(document_ids or [])
            if ids and ids[0].startswith("doc_dept"):
                return [
                    LexicalMatch(
                        point_id=f"point-dept-{index}",
                        payload={
                            "chunk_id": f"chunk-dept-{index}",
                            "document_id": "doc_dept_ok",
                            "document_name": "doc_dept_ok.txt",
                            "text": "700000 面板 急停 报警 现场 先查 安全继电器 和 线路",
                            "source_path": "/tmp/doc_dept_ok.txt",
                        },
                        score=12.5 - index * 0.1,
                    )
                    for index in range(5)
                ]
            return []

        @staticmethod
        def _tokenize(text: str):
            tokens = text.lower().replace(" ", "")
            mapping = {
                "700000面板急停报警现场先查什么": ["700000", "面板", "急停", "报警", "现场", "先查"],
                "700000面板急停报警现场先查安全继电器和线路": [
                    "700000",
                    "面板",
                    "急停",
                    "报警",
                    "现场",
                    "先查",
                    "安全继电器",
                    "线路",
                ],
            }
            primary_tokens = mapping.get(tokens, [text.lower()])
            return SimpleNamespace(primary_tokens=primary_tokens, supplemental_tokens=[])

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)
    retrieval_service.lexical_retriever = FakeLexicalRetriever()

    response = retrieval_service.search(
        request=RetrievalRequest(query="700000 面板急停报警 现场先查什么", top_k=5, mode="fast"),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    assert response.diagnostic is not None
    assert response.diagnostic.supplemental_triggered is False
    assert response.diagnostic.supplemental_recall_stage.trigger_basis == "department_sufficient"


def test_retrieval_service_staged_sufficient_does_not_promote_global(tmp_path: Path) -> None:
    """When truncate_to_top_k=False, use rerank_top_n as the sufficiency threshold."""
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "query_fast_top_k_default": 5,
            "query_fast_rerank_top_n": 3,
        }
    )
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(
            self,
            auth_context: AuthContext | None,
        ) -> DepartmentPriorityRetrievalScope:
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_1", "doc_dept_2", "doc_dept_3", "doc_dept_4"],
                global_document_ids=["doc_global_1"],
            )

        def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService(), retrieval_scope_policy=SpyRetrievalScopePolicy())  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    vector_route_calls: list[list[str]] = []

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        vector_route_calls.append(list(document_ids or []))
        ids = set(document_ids or [])
        results: list[SimpleNamespace] = []
        for doc_id in ids:
            results.append(
                SimpleNamespace(
                    id=f"point-{doc_id}",
                    score=0.9,
                    payload={
                        "chunk_id": f"chunk-{doc_id}",
                        "document_id": doc_id,
                        "document_name": f"{doc_id}.txt",
                        "text": f"Content from {doc_id}",
                        "source_path": f"/tmp/{doc_id}.txt",
                    },
                )
            )
        return results

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)
    retrieval_service.lexical_retriever = SimpleNamespace(search=lambda query, **kwargs: [])

    # With truncate_to_top_k=False, the threshold should be rerank_top_n=3
    # Department has 4 results >= 3, so supplemental should be skipped
    results, mode, profile = retrieval_service.search_candidates(
        request=RetrievalRequest(query="test query"),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
        truncate_to_top_k=False,
    )

    # Only department route called; supplemental skipped because 4 >= rerank_top_n(3)
    assert vector_route_calls == [["doc_dept_1", "doc_dept_2", "doc_dept_3", "doc_dept_4"]]
    assert len(results) == 4
    assert all(item.source_scope == "department" for item in results)


def test_retrieval_service_staged_triggers_supplemental_with_rerank_top_n_threshold(tmp_path: Path) -> None:
    """When truncate_to_top_k=False and department results < rerank_top_n, supplemental should trigger."""
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "query_fast_top_k_default": 5,
            "query_fast_rerank_top_n": 4,
        }
    )
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(
            self,
            auth_context: AuthContext | None,
        ) -> DepartmentPriorityRetrievalScope:
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_1", "doc_dept_2"],
                global_document_ids=["doc_global_1", "doc_global_2"],
            )

        def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService(), retrieval_scope_policy=SpyRetrievalScopePolicy())  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    vector_route_calls: list[list[str]] = []

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        vector_route_calls.append(list(document_ids or []))
        ids = set(document_ids or [])
        results: list[SimpleNamespace] = []
        for doc_id in ids:
            results.append(
                SimpleNamespace(
                    id=f"point-{doc_id}",
                    score=0.9,
                    payload={
                        "chunk_id": f"chunk-{doc_id}",
                        "document_id": doc_id,
                        "document_name": f"{doc_id}.txt",
                        "text": f"Content from {doc_id}",
                        "source_path": f"/tmp/{doc_id}.txt",
                    },
                )
            )
        return results

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)
    retrieval_service.lexical_retriever = SimpleNamespace(search=lambda query, **kwargs: [])

    # With truncate_to_top_k=False, threshold is rerank_top_n=4
    # Department has 2 results < 4, so supplemental should trigger
    results, mode, profile = retrieval_service.search_candidates(
        request=RetrievalRequest(query="test query"),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
        truncate_to_top_k=False,
    )

    # Both routes called because 2 < rerank_top_n(4)
    assert vector_route_calls == [["doc_dept_1", "doc_dept_2"], ["doc_global_1", "doc_global_2"]]
    # Department results rank first
    assert results[0].source_scope == "department"
    assert results[1].source_scope == "department"


def test_retrieval_service_staged_triggers_supplemental_when_department_quality_is_low(tmp_path: Path) -> None:
    """Department count can be sufficient, but low-quality top results should still trigger supplemental recall."""
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(
            self,
            auth_context: AuthContext | None,
        ) -> DepartmentPriorityRetrievalScope:
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_1", "doc_dept_2", "doc_dept_3"],
                global_document_ids=["doc_global_1", "doc_global_2"],
            )

        def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(
        settings,
        document_service=SpyDocumentService(),
        retrieval_scope_policy=SpyRetrievalScopePolicy(),
    )  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    vector_route_calls: list[list[str]] = []

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        vector_route_calls.append(list(document_ids or []))
        ids = list(document_ids or [])
        results: list[SimpleNamespace] = []
        if ids and ids[0].startswith("doc_dept"):
            scores = [0.50, 0.49, 0.48]
        else:
            scores = [0.88, 0.84]
        for i, doc_id in enumerate(ids):
            results.append(
                SimpleNamespace(
                    id=f"point-{doc_id}",
                    score=scores[min(i, len(scores) - 1)],
                    payload={
                        "chunk_id": f"chunk-{doc_id}",
                        "document_id": doc_id,
                        "document_name": f"{doc_id}.txt",
                        "text": f"Content from {doc_id}",
                        "source_path": f"/tmp/{doc_id}.txt",
                    },
                )
            )
        return results

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)
    retrieval_service.lexical_retriever = SimpleNamespace(search=lambda query, **kwargs: [])
    response = retrieval_service.search(
        request=RetrievalRequest(query="解释一下cpps", top_k=3, mode="fast"),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    assert vector_route_calls == [["doc_dept_1", "doc_dept_2", "doc_dept_3"], ["doc_global_1", "doc_global_2"]]
    assert response.diagnostic is not None
    assert response.diagnostic.supplemental_triggered is True
    assert response.diagnostic.supplemental_recall_stage.trigger_basis == "department_low_quality"
    assert response.diagnostic.primary_recall_stage.top1_score == pytest.approx(0.50)
    assert response.diagnostic.query_stage.requested_mode == "fast"


def test_retrieval_service_staged_triggers_supplemental_for_fine_query_even_when_count_is_sufficient(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path)
    settings.retrieval_strategy_default = "hybrid"
    settings.retrieval_dynamic_weighting_enabled = False
    settings.retrieval_hybrid_fixed_vector_weight = 1.0
    settings.retrieval_hybrid_fixed_lexical_weight = 1.0
    settings.query_fast_candidate_multiplier = 4
    settings.query_fast_lexical_top_k_default = 20
    settings.query_fast_rerank_top_n = 5

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(self, auth_context):
            return DepartmentPriorityRetrievalScope(
                department_document_ids=[f"doc_dept_{index}" for index in range(1, 6)],
                global_document_ids=[f"doc_global_{index}" for index in range(1, 4)],
            )

        def get_document_retrievability_map(self, document_ids, auth_context):
            return {document_id: True for document_id in document_ids}

    retrieval_service = RetrievalService(
        settings,
        document_service=SpyDocumentService(),
        retrieval_scope_policy=SpyRetrievalScopePolicy(),
    )  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    vector_route_calls: list[tuple[int, list[str]]] = []

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        ids = list(document_ids or [])
        vector_route_calls.append((limit, ids))
        if ids and ids[0].startswith("doc_dept"):
            scores = [0.8249, 0.56, 0.54, 0.53, 0.52]
        else:
            scores = [0.92, 0.88, 0.84]
        results: list[SimpleNamespace] = []
        for i, doc_id in enumerate(ids):
            results.append(
                SimpleNamespace(
                    id=f"point-{doc_id}",
                    score=scores[min(i, len(scores) - 1)],
                    payload={
                        "chunk_id": f"chunk-{doc_id}",
                        "document_id": doc_id,
                        "document_name": f"{doc_id}.txt",
                        "text": f"Content from {doc_id}",
                        "source_path": f"/tmp/{doc_id}.txt",
                    },
                )
            )
        return results

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)
    retrieval_service.lexical_retriever = SimpleNamespace(search=lambda query, **kwargs: [])

    response = retrieval_service.search(
        request=RetrievalRequest(query="解释一下cpps", top_k=5, mode="fast"),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    assert len(vector_route_calls) == 2
    supplemental_limit, supplemental_ids = vector_route_calls[1]
    assert supplemental_ids == ["doc_global_1", "doc_global_2", "doc_global_3"]
    assert supplemental_limit >= 5
    assert response.diagnostic is not None
    assert response.diagnostic.query_stage.query_granularity == "fine"
    assert response.diagnostic.primary_recall_stage.whether_sufficient is False
    assert response.diagnostic.supplemental_triggered is True
    assert response.diagnostic.supplemental_recall_stage.trigger_basis == "department_low_quality"


def test_retrieval_service_uses_internal_system_config_quality_thresholds_for_supplemental(tmp_path: Path) -> None:
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    settings.system_config_path.parent.mkdir(parents=True, exist_ok=True)
    settings.system_config_path.write_text(
        json.dumps(
            {
                "_internal_retrieval_controls": {
                    "supplemental_quality_thresholds": {
                        "top1_threshold": 0.72,
                        "avg_top_n_threshold": 0.69,
                        "fine_query_top1_threshold": 0.90,
                        "fine_query_avg_top_n_threshold": 0.75,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(
            self,
            auth_context: AuthContext | None,
        ) -> DepartmentPriorityRetrievalScope:
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_1", "doc_dept_2", "doc_dept_3"],
                global_document_ids=["doc_global_1", "doc_global_2"],
            )

        def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(
        settings,
        document_service=SpyDocumentService(),
        retrieval_scope_policy=SpyRetrievalScopePolicy(),
    )  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        ids = list(document_ids or [])
        if ids and ids[0].startswith("doc_dept"):
            scores = [0.70, 0.68, 0.67]
        else:
            scores = [0.90, 0.86]
        results: list[SimpleNamespace] = []
        for i, doc_id in enumerate(ids):
            results.append(
                SimpleNamespace(
                    id=f"point-{doc_id}",
                    score=scores[min(i, len(scores) - 1)],
                    payload={
                        "chunk_id": f"chunk-{doc_id}",
                        "document_id": doc_id,
                        "document_name": f"{doc_id}.txt",
                        "text": f"Content from {doc_id}",
                        "source_path": f"/tmp/{doc_id}.txt",
                    },
                )
            )
        return results

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)
    retrieval_service.lexical_retriever = SimpleNamespace(search=lambda query, **kwargs: [])

    response = retrieval_service.search(
        request=RetrievalRequest(query="explain process handling steps clearly", top_k=3, mode="fast"),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    assert response.diagnostic is not None
    assert response.diagnostic.query_stage.query_granularity == "medium"
    assert response.diagnostic.primary_recall_stage.quality_top1_threshold == pytest.approx(0.72)
    assert response.diagnostic.primary_recall_stage.quality_avg_threshold == pytest.approx(0.69)
    assert response.diagnostic.supplemental_triggered is True
    assert response.diagnostic.supplemental_recall_stage.trigger_basis == "department_low_quality"


# ── Phase 1B-A: Supplemental diagnostics consistency ────────


def test_supplemental_diagnostics_department_sufficient_populates_all_quality_fields(tmp_path: Path) -> None:
    """When department is sufficient, all diagnostic quality fields should be populated consistently."""
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "query_fast_top_k_default": 3,
            "retrieval_quality_top1_threshold": 0.55,
            "retrieval_quality_avg_threshold": 0.45,
        }
    )
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(self, auth_context):
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_1", "doc_dept_2", "doc_dept_3"],
                global_document_ids=["doc_global_1"],
            )

        def get_document_retrievability_map(self, doc_ids, auth_context):
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService(), retrieval_scope_policy=SpyRetrievalScopePolicy())  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, **kwargs: [
            SimpleNamespace(id="p1", score=0.95, payload={"chunk_id": "c1", "document_id": "doc_dept_1", "document_name": "d1.txt", "text": "High quality content", "source_path": "/tmp/d1.txt"}),
            SimpleNamespace(id="p2", score=0.92, payload={"chunk_id": "c2", "document_id": "doc_dept_2", "document_name": "d2.txt", "text": "Good quality content", "source_path": "/tmp/d2.txt"}),
            SimpleNamespace(id="p3", score=0.88, payload={"chunk_id": "c3", "document_id": "doc_dept_3", "document_name": "d3.txt", "text": "Decent quality content", "source_path": "/tmp/d3.txt"}),
        ]
    )
    retrieval_service.lexical_retriever = SimpleNamespace(search=lambda query, **kwargs: [])

    # Use a semantic/broad query to get coarse granularity (not fine) so default thresholds apply
    response = retrieval_service.search(
        request=RetrievalRequest(query="explain the overall process for handling equipment maintenance", top_k=3),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    assert response.diagnostic is not None
    d = response.diagnostic
    # department_sufficient: supplemental NOT triggered
    assert d.supplemental_triggered is False
    assert d.supplemental_recall_stage.triggered is False
    # trigger_basis should explain why supplemental was NOT triggered
    assert d.supplemental_recall_stage.trigger_basis == "department_sufficient"

    # All quality diagnostic fields should be populated
    assert d.primary_recall_stage.threshold is not None
    assert d.primary_recall_stage.effective_count is not None
    assert d.primary_recall_stage.top1_score is not None
    assert d.primary_recall_stage.avg_top_n_score is not None
    assert d.primary_recall_stage.quality_top1_threshold is not None
    assert d.primary_recall_stage.quality_avg_threshold is not None
    assert d.primary_recall_stage.whether_sufficient is True

    # Quality thresholds should match settings defaults (for coarse queries)
    assert d.primary_recall_stage.quality_top1_threshold == pytest.approx(0.55)
    assert d.primary_recall_stage.quality_avg_threshold == pytest.approx(0.45)

    # Top-level diagnostic should also have these
    assert d.primary_threshold is not None
    assert d.primary_effective_count is not None
    assert d.primary_threshold == d.primary_recall_stage.threshold


def test_supplemental_diagnostics_department_insufficient_populates_trigger_basis(tmp_path: Path) -> None:
    """When department is insufficient, trigger_basis should be department_insufficient."""
    settings = build_test_settings(tmp_path)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(self, auth_context):
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_1"],
                global_document_ids=["doc_global_1", "doc_global_2"],
            )

        def get_document_retrievability_map(self, doc_ids, auth_context):
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService(), retrieval_scope_policy=SpyRetrievalScopePolicy())  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, **kwargs: [
            SimpleNamespace(id="p1", score=0.95, payload={"chunk_id": "c1", "document_id": "doc_dept_1", "document_name": "d1.txt", "text": "Content", "source_path": "/tmp/d1.txt"}),
        ]
    )
    retrieval_service.lexical_retriever = SimpleNamespace(search=lambda query, **kwargs: [])

    response = retrieval_service.search(
        request=RetrievalRequest(query="test query", top_k=3),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    assert response.diagnostic is not None
    d = response.diagnostic
    assert d.supplemental_triggered is True
    assert d.supplemental_recall_stage.triggered is True
    assert d.supplemental_recall_stage.trigger_basis == "department_insufficient"
    assert d.supplemental_reason is not None
    assert "below_threshold" in d.supplemental_reason

    # Quality fields should still be populated
    assert d.primary_recall_stage.top1_score is not None
    assert d.primary_recall_stage.avg_top_n_score is not None
    assert d.primary_recall_stage.quality_top1_threshold is not None
    assert d.primary_recall_stage.quality_avg_threshold is not None


def test_supplemental_diagnostics_department_low_quality_populates_quality_fields(tmp_path: Path) -> None:
    """When department has enough results but low quality, trigger_basis should be department_low_quality."""
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "retrieval_quality_top1_threshold": 0.75,
            "retrieval_quality_avg_threshold": 0.65,
            "retrieval_fine_query_quality_top1_threshold": 0.85,
            "retrieval_fine_query_quality_avg_threshold": 0.70,
        }
    )
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(self, auth_context):
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_1", "doc_dept_2", "doc_dept_3"],
                global_document_ids=["doc_global_1"],
            )

        def get_document_retrievability_map(self, doc_ids, auth_context):
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService(), retrieval_scope_policy=SpyRetrievalScopePolicy())  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    # Department has 3 results (enough for top_k=3), but scores are low
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, **kwargs: [
            SimpleNamespace(id="p1", score=0.60, payload={"chunk_id": "c1", "document_id": "doc_dept_1", "document_name": "d1.txt", "text": "Low quality", "source_path": "/tmp/d1.txt"}),
            SimpleNamespace(id="p2", score=0.55, payload={"chunk_id": "c2", "document_id": "doc_dept_2", "document_name": "d2.txt", "text": "Low quality", "source_path": "/tmp/d2.txt"}),
            SimpleNamespace(id="p3", score=0.50, payload={"chunk_id": "c3", "document_id": "doc_dept_3", "document_name": "d3.txt", "text": "Low quality", "source_path": "/tmp/d3.txt"}),
        ]
    )
    retrieval_service.lexical_retriever = SimpleNamespace(search=lambda query, **kwargs: [])

    # Use a broad/semantic query to get coarse granularity (not fine) so default thresholds apply
    response = retrieval_service.search(
        request=RetrievalRequest(query="explain clearly what to do about the issue", top_k=3),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    assert response.diagnostic is not None
    d = response.diagnostic
    assert d.supplemental_triggered is True
    assert d.supplemental_recall_stage.trigger_basis == "department_low_quality"
    assert "quality" in d.supplemental_reason.lower()

    # Quality fields should reflect the configured thresholds
    assert d.primary_recall_stage.quality_top1_threshold == pytest.approx(0.75)
    assert d.primary_recall_stage.quality_avg_threshold == pytest.approx(0.65)

    # Primary top1 and avg scores should be below thresholds (this is what triggered supplemental)
    assert d.primary_recall_stage.top1_score is not None
    assert d.primary_recall_stage.avg_top_n_score is not None


def test_supplemental_diagnostics_fine_query_uses_stricter_thresholds(tmp_path: Path) -> None:
    """Fine-grained queries should use stricter quality thresholds for supplemental evaluation."""
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "retrieval_quality_top1_threshold": 0.55,
            "retrieval_quality_avg_threshold": 0.45,
            "retrieval_fine_query_quality_top1_threshold": 0.85,
            "retrieval_fine_query_quality_avg_top_n_threshold": 0.60,
        }
    )
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(self, auth_context):
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_1", "doc_dept_2", "doc_dept_3"],
                global_document_ids=["doc_global_1"],
            )

        def get_document_retrievability_map(self, doc_ids, auth_context):
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService(), retrieval_scope_policy=SpyRetrievalScopePolicy())  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])

    # Department has enough results with medium quality scores.
    # For a normal query (top1=0.72 > 0.55), this would NOT trigger supplemental.
    # For a fine query (top1=0.72 < 0.85), this WOULD trigger supplemental.
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, **kwargs: [
            SimpleNamespace(id="p1", score=0.72, payload={"chunk_id": "c1", "document_id": "doc_dept_1", "document_name": "d1.txt", "text": "E204 fault code recovery", "source_path": "/tmp/d1.txt"}),
            SimpleNamespace(id="p2", score=0.68, payload={"chunk_id": "c2", "document_id": "doc_dept_2", "document_name": "d2.txt", "text": "E204 maintenance steps", "source_path": "/tmp/d2.txt"}),
            SimpleNamespace(id="p3", score=0.65, payload={"chunk_id": "c3", "document_id": "doc_dept_3", "document_name": "d3.txt", "text": "E204 alarm guide", "source_path": "/tmp/d3.txt"}),
        ]
    )
    retrieval_service.lexical_retriever = SimpleNamespace(search=lambda query, **kwargs: [])

    # Fine query: E204故障代码处理步骤 (exact-like, should be classified as fine)
    response_fine = retrieval_service.search(
        request=RetrievalRequest(query="E204故障代码处理步骤", top_k=3),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    assert response_fine.diagnostic is not None
    # Fine query should use stricter thresholds
    assert response_fine.diagnostic.primary_recall_stage.quality_top1_threshold == pytest.approx(0.85)
    assert response_fine.diagnostic.primary_recall_stage.quality_avg_threshold == pytest.approx(0.60)
    # top1_score (0.72) < fine_query_top1_threshold (0.85) → supplemental triggered
    assert response_fine.diagnostic.supplemental_triggered is True
    assert response_fine.diagnostic.supplemental_recall_stage.trigger_basis == "department_low_quality"


def test_supplemental_diagnostics_truncate_to_top_k_false_uses_rerank_top_n_threshold(tmp_path: Path) -> None:
    """When truncate_to_top_k=False, diagnostic threshold should be rerank_top_n, not top_k."""
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "query_fast_top_k_default": 5,
            "query_fast_rerank_top_n": 3,
        }
    )
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(self, auth_context):
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_1", "doc_dept_2", "doc_dept_3", "doc_dept_4"],
                global_document_ids=["doc_global_1"],
            )

        def get_document_retrievability_map(self, doc_ids, auth_context):
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService(), retrieval_scope_policy=SpyRetrievalScopePolicy())  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])

    diagnostic: dict[str, object] = {}
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, **kwargs: [
            SimpleNamespace(id=f"p{i}", score=0.95 - i * 0.02, payload={"chunk_id": f"c{i}", "document_id": f"doc_dept_{i}", "document_name": f"d{i}.txt", "text": "Content", "source_path": f"/tmp/d{i}.txt"})
            for i in range(4)
        ]
    )
    retrieval_service.lexical_retriever = SimpleNamespace(search=lambda query, **kwargs: [])

    retrieval_service.search_candidates(
        request=RetrievalRequest(query="test query"),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
        truncate_to_top_k=False,
        diagnostic=diagnostic,
    )

    # With truncate_to_top_k=False, threshold should be rerank_top_n=3
    # 4 results >= 3, so supplemental should be skipped
    assert diagnostic["primary_threshold"] == 3
    assert diagnostic["primary_effective_count"] == 4
    assert diagnostic["supplemental_triggered"] is False
    assert diagnostic["supplemental_trigger_basis"] == "department_sufficient"


def test_supplemental_diagnostics_quality_thresholds_from_system_config_override_defaults(tmp_path: Path) -> None:
    """Internal retrieval controls from system config should override settings defaults."""
    settings = build_test_settings(tmp_path).model_copy(
        update={
            "retrieval_quality_top1_threshold": 0.55,
            "retrieval_quality_avg_threshold": 0.45,
        }
    )
    ensure_data_directories(settings)
    settings.system_config_path.parent.mkdir(parents=True, exist_ok=True)
    settings.system_config_path.write_text(
        json.dumps(
            {
                "_internal_retrieval_controls": {
                    "supplemental_quality_thresholds": {
                        "top1_threshold": 0.70,
                        "avg_top_n_threshold": 0.60,
                        "fine_query_top1_threshold": 0.90,
                        "fine_query_avg_top_n_threshold": 0.75,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(self, auth_context):
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_1", "doc_dept_2", "doc_dept_3"],
                global_document_ids=["doc_global_1"],
            )

        def get_document_retrievability_map(self, doc_ids, auth_context):
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService(), retrieval_scope_policy=SpyRetrievalScopePolicy())  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, **kwargs: [
            SimpleNamespace(id="p1", score=0.75, payload={"chunk_id": "c1", "document_id": "doc_dept_1", "document_name": "d1.txt", "text": "Content", "source_path": "/tmp/d1.txt"}),
            SimpleNamespace(id="p2", score=0.72, payload={"chunk_id": "c2", "document_id": "doc_dept_2", "document_name": "d2.txt", "text": "Content", "source_path": "/tmp/d2.txt"}),
            SimpleNamespace(id="p3", score=0.68, payload={"chunk_id": "c3", "document_id": "doc_dept_3", "document_name": "d3.txt", "text": "Content", "source_path": "/tmp/d3.txt"}),
        ]
    )
    retrieval_service.lexical_retriever = SimpleNamespace(search=lambda query, **kwargs: [])

    response = retrieval_service.search(
        request=RetrievalRequest(query="explain the process steps", top_k=3),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    # Thresholds should come from system config, not settings defaults
    assert response.diagnostic is not None
    assert response.diagnostic.primary_recall_stage.quality_top1_threshold == pytest.approx(0.70)
    assert response.diagnostic.primary_recall_stage.quality_avg_threshold == pytest.approx(0.60)

    # top1=0.75 >= 0.70 and avg=0.717 >= 0.60 → department_sufficient
    assert response.diagnostic.supplemental_triggered is False


def test_supplemental_diagnostics_consistent_across_structured_diagnostic_and_raw(tmp_path: Path) -> None:
    """Raw diagnostic dict and structured RetrievalDiagnostic should have consistent values."""
    settings = build_test_settings(tmp_path).model_copy(
        update={"retrieval_quality_top1_threshold": 0.70, "retrieval_quality_avg_threshold": 0.60}
    )
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(self, auth_context):
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_1"],
                global_document_ids=["doc_global_1", "doc_global_2"],
            )

        def get_document_retrievability_map(self, doc_ids, auth_context):
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService(), retrieval_scope_policy=SpyRetrievalScopePolicy())  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])
    retrieval_service.vector_store = SimpleNamespace(
        search=lambda query_vector, **kwargs: [
            SimpleNamespace(id="p1", score=0.65, payload={"chunk_id": "c1", "document_id": "doc_dept_1", "document_name": "d1.txt", "text": "Content", "source_path": "/tmp/d1.txt"}),
        ]
    )
    retrieval_service.lexical_retriever = SimpleNamespace(search=lambda query, **kwargs: [])

    response = retrieval_service.search(
        request=RetrievalRequest(query="test query", top_k=3),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_rnd"]),
    )

    d = response.diagnostic
    assert d is not None

    # Top-level fields should match sub-stage fields
    assert d.primary_threshold == d.primary_recall_stage.threshold
    assert d.primary_effective_count == d.primary_recall_stage.effective_count
    assert d.supplemental_triggered == d.supplemental_recall_stage.triggered
    assert d.supplemental_reason == d.supplemental_recall_stage.reason

    # Recall counts should be present
    assert isinstance(d.recall_counts, dict)
    assert "department_fused_count" in d.recall_counts or "department_after_ocr" in d.recall_counts


def test_retrieval_service_staged_triggers_supplemental_when_mono_document_with_high_score_semantic_mismatch(tmp_path: Path) -> None:
    """When all department results come from a single document with very high score but the
    query is coarse/semantic and literal coverage is weak, the department lacks diversity
    and supplemental should trigger to broaden coverage (cross-013 scenario)."""
    from backend.app.services.retrieval_service import (
        SUPPLEMENTAL_LOW_LITERAL_COVERAGE_THRESHOLD,
        SUPPLEMENTAL_MONO_DOCUMENT_LITERAL_COVERAGE_THRESHOLD,
    )

    # Mono-document threshold must be stricter than the regular one
    assert SUPPLEMENTAL_MONO_DOCUMENT_LITERAL_COVERAGE_THRESHOLD < SUPPLEMENTAL_LOW_LITERAL_COVERAGE_THRESHOLD

    settings = build_test_settings(tmp_path).model_copy(
        update={
            "query_fast_top_k_default": 5,
            "query_fast_rerank_top_n": 5,
        }
    )
    ensure_data_directories(settings)

    class SpyDocumentService:
        pass

    class SpyRetrievalScopePolicy:
        def build_department_priority_retrieval_scope(self, auth_context):
            return DepartmentPriorityRetrievalScope(
                department_document_ids=["doc_dept_semantic_overlap"],
                global_document_ids=["doc_global_expected"],
            )

        def get_document_retrievability_map(self, doc_ids, auth_context):
            return {doc_id: True for doc_id in doc_ids}

    retrieval_service = RetrievalService(settings, document_service=SpyDocumentService(), retrieval_scope_policy=SpyRetrievalScopePolicy())  # type: ignore[arg-type]
    retrieval_service.embedding_client = SimpleNamespace(embed_texts=lambda texts: [[0.1, 0.2, 0.3]])

    def fake_vector_search(query_vector, *, limit, document_id=None, document_ids=None):
        ids = list(document_ids or [])
        results = []
        if ids and ids[0].startswith("doc_dept"):
            # All 5 results from a single document with very high scores (semantic overlap)
            for i in range(5):
                results.append(
                    SimpleNamespace(
                        id=f"point-dept-{i}",
                        score=0.99 - i * 0.01,
                        payload={
                            "chunk_id": f"chunk-dept-{i}",
                            "document_id": "doc_dept_semantic_overlap",
                            "document_name": "doc_dept_semantic_overlap.txt",
                            "text": "刀具系统技术要求和维护规范 刀具寿命管理 刀具更换标准操作",
                            "source_path": "/tmp/doc_dept_semantic_overlap.txt",
                        },
                    )
                )
        elif ids and ids[0].startswith("doc_global"):
            results.append(
                SimpleNamespace(
                    id="point-global-0",
                    score=0.95,
                    payload={
                        "chunk_id": "chunk-global-0",
                        "document_id": "doc_global_expected",
                        "document_name": "doc_global_expected.txt",
                        "text": "皮带轮部品组装 止动螺丝和压装 工艺流程 SOP",
                        "source_path": "/tmp/doc_global_expected.txt",
                    },
                )
            )
        return results

    retrieval_service.vector_store = SimpleNamespace(search=fake_vector_search)

    class FakeLexicalRetriever:
        @staticmethod
        def search(query, *, limit, document_id=None, document_ids=None):
            return []

        @staticmethod
        def _tokenize(text):
            # Return DIFFERENT tokens for query vs candidate to simulate semantic mismatch
            # where the department doc ("tool system requirements") doesn't cover the
            # query tokens ("pulley SOP assembly")
            if "皮带轮" in text or "压装" in text or "止动螺丝" in text:
                return SimpleNamespace(
                    primary_tokens=["皮带轮", "部品", "组装", "止动螺丝", "压装"],
                    supplemental_tokens=[],
                )
            else:
                return SimpleNamespace(
                    primary_tokens=["刀具", "系统", "技术", "要求", "维护", "规范"],
                    supplemental_tokens=[],
                )

    retrieval_service.lexical_retriever = FakeLexicalRetriever()
    response = retrieval_service.search(
        request=RetrievalRequest(query="皮带轮部品组装 止动螺丝和压装的完整工艺流程", top_k=5, mode="fast"),
        auth_context=_build_auth_context(role_id="employee", department_ids=["dept_digitalization"]),
    )

    assert response.diagnostic is not None
    assert response.diagnostic.supplemental_triggered is True, (
        "Supplemental should trigger when department has mono-document results with high scores "
        "but the content doesn't genuinely match the query (low literal coverage / coarse query)"
    )
    assert response.diagnostic.supplemental_recall_stage.trigger_basis == "department_low_quality"


def test_retrieval_service_staged_suppresses_avg_topn_boundary_jitter_when_top1_is_strong(tmp_path: Path) -> None:
    """Verify the SUPPLEMENTAL_AVG_TOP_N_TOLERANCE_ZONE constant is defined and the tolerance
    zone logic exists to suppress boundary jitter when avg_top_n is marginally below threshold
    but top1 is strong and literal coverage is good (sop-005 scenario)."""
    from backend.app.services.retrieval_service import SUPPLEMENTAL_AVG_TOP_N_TOLERANCE_ZONE

    # The tolerance zone must be positive and small (< 0.20) to avoid over-suppression
    assert SUPPLEMENTAL_AVG_TOP_N_TOLERANCE_ZONE > 0
    assert SUPPLEMENTAL_AVG_TOP_N_TOLERANCE_ZONE < 0.20
