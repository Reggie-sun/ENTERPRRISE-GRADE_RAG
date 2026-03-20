from pathlib import Path  # 导入 Path，方便创建测试目录路径。

from fastapi.testclient import TestClient  # 导入 FastAPI 测试客户端。
import httpx  # 导入 httpx，用于构造 OpenAI 兼容接口错误响应。

from backend.app.core.config import Settings, ensure_data_directories  # 导入配置对象和目录初始化函数。
from backend.app.main import app  # 导入应用实例。
from backend.app.services.chat_service import ChatService, get_chat_service  # 导入问答服务和依赖入口。
from backend.app.services.document_service import DocumentService, get_document_service  # 导入文档服务和依赖入口。
from backend.app.services.retrieval_service import RetrievalService, get_retrieval_service  # 导入检索服务和依赖入口。


def build_test_settings(tmp_path: Path) -> Settings:  # 构造 retrieval/chat 集成测试专用配置。
    data_dir = tmp_path / "data"  # 定义测试数据根目录。
    return Settings(  # 返回测试配置对象。
        app_name="Enterprise-grade RAG API Test",  # 设置测试应用名。
        app_env="test",  # 指定测试环境。
        debug=True,  # 开启调试模式，便于排查失败原因。
        qdrant_url=str(tmp_path / "qdrant_db"),  # 使用本地路径模式，让不同服务实例共享同一份 Qdrant 数据。
        qdrant_collection="enterprise_rag_v1_test",  # 使用测试 collection。
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
        document_dir=data_dir / "documents",  # 配置 document 元数据目录。
        job_dir=data_dir / "jobs",  # 配置 job 元数据目录。
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
    assert payload["mode"] == "qdrant"  # 检索模式应是 qdrant。
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
