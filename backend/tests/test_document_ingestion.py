import json  # 导入 json，用来读取 chunk 结果文件里的 JSON 内容。
from pathlib import Path  # 导入 Path，方便处理临时目录和文件路径。

from fastapi.testclient import TestClient  # 导入 FastAPI 的测试客户端，用来直接调用接口。

from backend.app.main import app  # 导入应用实例，测试时直接对这个 app 发请求。
from backend.app.core.config import Settings, ensure_data_directories  # 导入配置对象和目录初始化函数。
from backend.app.services.document_service import DocumentService, get_document_service  # 导入上传服务和依赖注入函数。


def build_test_settings(tmp_path: Path) -> Settings:  # 定义一个辅助函数，用来构造测试专用配置。
    data_dir = tmp_path / "data"  # 在 pytest 提供的临时目录下创建 data 根目录路径。
    return Settings(  # 返回一个只用于测试场景的 Settings 配置对象。
        app_name="Enterprise-grade RAG API Test",  # 设置测试环境里的应用名称。
        app_env="test",  # 设置当前运行环境为 test。
        debug=True,  # 打开调试模式，便于测试阶段排查问题。
        qdrant_url=":memory:",  # 让 Qdrant 使用内存模式，避免依赖外部服务。
        qdrant_collection="enterprise_rag_v1_test",  # 设置测试专用的 collection 名称。
        ollama_base_url="http://embedding.test",  # 给 LLM 地址填一个测试占位值。
        embedding_provider="mock",  # embedding 提供方使用 mock，这样测试不需要真实模型服务。
        embedding_base_url="http://embedding.test",  # 给 embedding 地址填一个测试占位值。
        embedding_model="BAAI/bge-m3",  # 保持测试时的 embedding 模型名与项目配置一致。
        data_dir=data_dir,  # 指定 data 根目录。
        upload_dir=data_dir / "uploads",  # 指定上传文件落盘目录。
        parsed_dir=data_dir / "parsed",  # 指定解析文本落盘目录。
        chunk_dir=data_dir / "chunks",  # 指定 chunk 结果落盘目录。
    )


def test_upload_document_runs_ingestion_pipeline(tmp_path: Path) -> None:  # 测试上传接口能否完整跑通入库链路。
    settings = build_test_settings(tmp_path)  # 先构造当前测试需要的配置。
    ensure_data_directories(settings)  # 根据测试配置创建 uploads / parsed / chunks 等目录。
    service = DocumentService(settings)  # 用测试配置创建上传服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 用测试服务覆盖 FastAPI 的默认依赖注入。
    client = TestClient(app)  # 创建测试客户端，后续直接像调 HTTP 接口一样发请求。

    try:  # 用 try/finally 确保依赖覆盖在测试结束后一定会被清理掉。
        response = client.post(  # 向上传接口发送一个 POST 请求。
            "/api/v1/documents/upload",  # 指定上传接口的 URL。
            files={  # 通过 multipart/form-data 的方式上传文件。
                "file": (  # 表单字段名必须和接口定义里的 file 一致。
                    "manual.txt",  # 上传文件名。
                    (  # 下面这个括号包起来的是上传文件的二进制内容。
                        "RAG can help engineers search maintenance manuals quickly.\n\n"  # 第一段文本，用来模拟知识库文档内容。
                        "This document explains alarm handling steps, safety notes, and repair guides."  # 第二段文本，继续补充测试内容。
                    ).encode("utf-8"),  # 把字符串编码成 utf-8 字节流，模拟真实文件上传。
                    "text/plain",  # 指定当前上传文件的 MIME 类型。
                )  # 结束 file 这个 multipart 文件元组。
            },  # 结束 files 参数字典。
        )  # 完成这次 POST 调用，并拿到响应对象。
    finally:  # 无论上面的请求成功还是失败，都会执行这里的清理。
        app.dependency_overrides.clear()  # 清空依赖覆盖，避免影响别的测试。

    assert response.status_code == 201  # 断言上传成功时接口返回 201 Created。
    payload = response.json()  # 把响应 JSON 解析成 Python 字典，方便后续断言。
    assert payload["status"] == "ingested"  # 断言接口返回状态是 ingested，表示已经完成入库。
    assert payload["parse_supported"] is True  # 断言当前上传类型是系统支持解析的。
    assert payload["chunk_count"] >= 1  # 断言至少生成了 1 个 chunk。
    assert payload["vector_count"] == payload["chunk_count"]  # 断言写入的向量数和 chunk 数保持一致。
    assert Path(payload["storage_path"]).exists()  # 断言原始上传文件已经实际落盘。
    assert Path(payload["parsed_path"]).exists()  # 断言解析后的纯文本文件已经生成。
    assert Path(payload["chunk_path"]).exists()  # 断言 chunk 结果文件已经生成。
    assert service.ingestion_service.vector_store.count_points() == payload["vector_count"]  # 断言 Qdrant 里的点数量和返回的向量数量一致。

    chunk_payload = json.loads(Path(payload["chunk_path"]).read_text(encoding="utf-8"))  # 读取 chunk 文件并解析成 Python 对象。
    assert len(chunk_payload) == payload["chunk_count"]  # 断言 chunk 文件里的条目数量和接口返回一致。
    assert chunk_payload[0]["document_id"] == payload["document_id"]  # 断言第一个 chunk 里的 document_id 和上传响应一致。


def test_upload_rejects_unsupported_extension(tmp_path: Path) -> None:  # 测试系统会拒绝不支持的文件扩展名。
    settings = build_test_settings(tmp_path)  # 构造这次测试用到的配置。
    ensure_data_directories(settings)  # 提前创建测试需要的目录结构。
    service = DocumentService(settings)  # 用测试配置创建上传服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖默认依赖，让接口走测试服务。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 用 try/finally 确保测试结束后能恢复依赖状态。
        response = client.post(  # 对上传接口发起一次上传请求。
            "/api/v1/documents/upload",  # 指定上传接口地址。
            files={"file": ("manual.docx", b"fake-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},  # 上传一个当前系统不支持解析的 docx 文件。
        )  # 完成接口调用。
    finally:  # 不管接口是否报错，都执行清理逻辑。
        app.dependency_overrides.clear()  # 清空依赖覆盖，避免污染其他测试。

    assert response.status_code == 400  # 断言不支持的扩展名会返回 400 Bad Request。
    assert "Unsupported file type" in response.json()["detail"]  # 断言错误信息里明确说明了文件类型不被支持。
