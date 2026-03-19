from pathlib import Path  # 导入 Path，方便创建测试目录路径。

from fastapi.testclient import TestClient  # 导入 FastAPI 测试客户端。

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
