import asyncio  # 导入 asyncio，便于在同步测试里调用异步读取函数。
from datetime import datetime, timedelta, timezone  # 导入时间工具，便于构造历史元数据测试记录和过期任务场景。
from io import BytesIO  # 导入 BytesIO，用于在测试里动态拼装最小 DOCX 文件。
import json  # 导入 json，用来读取 chunk 结果文件里的 JSON 内容。
from pathlib import Path  # 导入 Path，方便处理临时目录和文件路径。
import threading  # 导入 threading，用于并发测试客户端缓存是否存在线程竞态。
import time  # 导入 time，用于制造并发竞争窗口。
from zipfile import ZIP_DEFLATED, ZipFile  # 导入 ZipFile，用于构造测试 DOCX 字节流。

from fastapi import HTTPException  # 导入 HTTPException，用于断言上传大小校验异常。
from fastapi.testclient import TestClient  # 导入 FastAPI 的测试客户端，用来直接调用接口。
import pytest  # 导入 pytest，方便写参数化测试。

import backend.app.services.asset_store as asset_store_module  # 导入资产存储模块，便于在测试里替换 PostgreSQL 资产后端。
from backend.app.main import app  # 导入应用实例，测试时直接对这个 app 发请求。
from backend.app.core.config import Settings, ensure_data_directories  # 导入配置对象和目录初始化函数。
from backend.app.rag.vectorstores.qdrant_store import QdrantVectorStore  # 导入 Qdrant 存储，验证远程模式客户端参数。
from backend.app.schemas.document import DocumentRecord, IngestJobRecord  # 导入文档和任务元数据结构，用于 metadata store 测试桩。
from backend.app.services.document_service import (  # 导入上传服务、依赖注入函数和上传分块读取配置。
    DocumentService,
    UPLOAD_READ_CHUNK_SIZE_BYTES,
    get_document_service,
)
from backend.app.worker.celery_app import INGEST_TASK_NAME, get_celery_app  # 导入 Celery 任务入口，补非 eager worker 回归测试。


def build_minimal_docx_bytes(*paragraphs: str) -> bytes:  # 构造一个最小可解析 DOCX，避免为测试引入额外第三方依赖。
    buffer = BytesIO()
    document_paragraphs = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        for text in paragraphs
    ) or "<w:p><w:r><w:t>empty</w:t></w:r></w:p>"
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{document_paragraphs}</w:body>"
        "</w:document>"
    )
    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", rels_xml)
        archive.writestr("word/document.xml", document_xml)

    return buffer.getvalue()


def build_minimal_pdf_bytes(*lines: str) -> bytes:  # 用 reportlab 构造一个最小可抽取文本的 PDF，便于测试 PDF OCR fallback。
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    y = 800
    for text in lines or ("empty",):
        pdf.drawString(72, y, text)
        y -= 20
    pdf.save()
    return buffer.getvalue()


class _FakePostgresAssetStore:
    def __init__(self, _dsn: str) -> None:
        self.assets: dict[str, tuple[bytes, str, str | None]] = {}

    def ping(self) -> None:
        return None

    def ensure_required_tables(self) -> None:
        return None

    def upsert_binary_asset(
        self,
        *,
        asset_key: str,
        relative_path: str,
        file_name: str,
        content: bytes,
        doc_id: str | None = None,
        job_id: str | None = None,
        mime_type: str | None = None,
        kind: str = "upload",
        metadata: dict[str, object] | None = None,
    ) -> str:
        del relative_path, doc_id, job_id, kind, metadata
        asset_uri = self.build_asset_uri(asset_key)
        self.assets[asset_uri] = (content, file_name, mime_type)
        return asset_uri

    def load_binary_asset(self, asset_uri: str) -> tuple[bytes, str, str | None, int]:
        content, file_name, mime_type = self.assets[asset_uri]
        return content, file_name, mime_type, len(content)

    def asset_exists(self, asset_uri: str) -> bool:
        return asset_uri in self.assets

    def get_asset_size(self, asset_uri: str) -> int:
        return len(self.assets[asset_uri][0]) if asset_uri in self.assets else 0

    @staticmethod
    def build_asset_uri(asset_key: str) -> str:
        return f"asset://{asset_key}"

    @staticmethod
    def is_asset_uri(storage_path: str) -> bool:
        return storage_path.startswith("asset://")


def build_test_settings(
    tmp_path: Path,
    *,
    task_always_eager: bool = False,
    asset_store_backend: str = "filesystem",
    database_url: str | None = None,
    ocr_provider: str = "disabled",
    ocr_pdf_native_text_min_chars: int = 80,
) -> Settings:  # 定义一个辅助函数，用来构造测试专用配置。
    data_dir = tmp_path / "data"  # 在 pytest 提供的临时目录下创建 data 根目录路径。
    return Settings(  # 返回一个只用于测试场景的 Settings 配置对象。
        app_name="Enterprise-grade RAG API Test",  # 设置测试环境里的应用名称。
        app_env="test",  # 设置当前运行环境为 test。
        debug=True,  # 打开调试模式，便于测试阶段排查问题。
        qdrant_url=":memory:",  # 让 Qdrant 使用内存模式，避免依赖外部服务。
        qdrant_collection="enterprise_rag_v1_test",  # 设置测试专用的 collection 名称。
        postgres_metadata_enabled=False,  # 测试默认固定走本地 JSON，避免受开发 .env 污染。
        postgres_metadata_dsn=None,  # 显式清空 PostgreSQL DSN。
        database_url=database_url,  # 需要验证 postgres 资产后端时传入占位 DATABASE_URL。
        celery_broker_url="memory://",  # Celery broker 使用内存模式，避免依赖真实 Redis。
        celery_result_backend="cache+memory://",  # Celery 结果后端也使用内存模式。
        celery_task_always_eager=task_always_eager,  # 按测试需要决定任务是否在当前进程内直接执行。
        celery_task_eager_propagates=True,  # eager 模式下让异常直接抛出，便于测试定位问题。
        ollama_base_url="http://embedding.test",  # 给 LLM 地址填一个测试占位值。
        embedding_provider="mock",  # embedding 提供方使用 mock，这样测试不需要真实模型服务。
        embedding_base_url="http://embedding.test",  # 给 embedding 地址填一个测试占位值。
        embedding_model="BAAI/bge-m3",  # 保持测试时的 embedding 模型名与项目配置一致。
        ocr_provider=ocr_provider,  # 按测试需要开启 mock OCR 或保持 disabled。
        ocr_pdf_native_text_min_chars=ocr_pdf_native_text_min_chars,  # 按测试需要控制 PDF OCR fallback 触发阈值。
        asset_store_backend=asset_store_backend,  # 按测试需要切换上传原文件后端。
        data_dir=data_dir,  # 指定 data 根目录。
        upload_dir=data_dir / "uploads",  # 指定上传文件落盘目录。
        parsed_dir=data_dir / "parsed",  # 指定解析文本落盘目录。
        chunk_dir=data_dir / "chunks",  # 指定 chunk 结果落盘目录。
        document_dir=data_dir / "documents",  # 指定 document 元数据目录。
        job_dir=data_dir / "jobs",  # 指定 ingest job 元数据目录。
    )


def test_create_document_returns_queued_job(tmp_path: Path) -> None:  # 测试新文档创建接口会立即返回 queued，并把元数据落盘。
    settings = build_test_settings(tmp_path)  # 先构造当前测试需要的配置。
    ensure_data_directories(settings)  # 根据测试配置创建 uploads / documents / jobs 等目录。
    service = DocumentService(settings)  # 用测试配置创建文档服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 用测试服务覆盖 FastAPI 的默认依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 用 try/finally 确保测试结束后一定清理依赖覆盖。
        response = client.post(  # 对新文档创建接口发起一次请求。
            "/api/v1/documents",  # 指定文档创建接口地址。
            data={  # 通过 multipart form 传入文档元信息。
                "tenant_id": "wl",  # 指定租户 ID。
                "department_ids": ["after_sales", "qa"],  # 指定部门范围。
                "role_ids": ["engineer"],  # 指定角色范围。
                "visibility": "department",  # 指定可见性策略。
                "classification": "internal",  # 指定文档密级。
                "tags": ["manual", "alarm"],  # 指定标签列表。
                "source_system": "dfms",  # 指定来源系统。
                "created_by": "u001",  # 指定上传人。
            },
            files={  # 通过 multipart/form-data 上传原始文件。
                "file": (  # 表单字段名必须和接口定义里的 file 一致。
                    "manual.txt",  # 上传文件名。
                    "Alarm E102 handling guide for after-sales engineers.".encode("utf-8"),  # 模拟上传文件内容。
                    "text/plain",  # 指定 MIME 类型。
                )
            },
        )
    finally:  # 无论请求成功或失败，最后都要清理依赖覆盖。
        app.dependency_overrides.clear()  # 清空依赖覆盖，避免影响其他测试。

    assert response.status_code == 201  # 断言创建成功时接口返回 201。
    payload = response.json()  # 把响应 JSON 转成 Python 字典。
    assert payload["status"] == "queued"  # 断言当前状态为 queued，而不是同步入库完成。
    assert payload["doc_id"].startswith("doc_")  # 断言文档 ID 使用业务前缀。
    assert payload["job_id"].startswith("job_")  # 断言任务 ID 使用业务前缀。

    document_path = settings.document_dir / f"{payload['doc_id']}.json"  # 计算 document 元数据文件路径。
    job_path = settings.job_dir / f"{payload['job_id']}.json"  # 计算 job 元数据文件路径。
    assert document_path.exists()  # 断言 document 元数据已经落盘。
    assert job_path.exists()  # 断言 job 元数据已经落盘。

    document_payload = json.loads(document_path.read_text(encoding="utf-8"))  # 读取 document JSON 内容。
    assert document_payload["tenant_id"] == "wl"  # 断言租户 ID 正确写入。
    assert document_payload["department_ids"] == ["after_sales", "qa"]  # 断言部门范围正确写入。
    assert document_payload["department_id"] == "after_sales"  # 断言主部门会从部门范围自动回填。
    assert document_payload["role_ids"] == ["engineer"]  # 断言角色范围正确写入。
    assert document_payload["visibility"] == "department"  # 断言可见性策略正确写入。
    assert document_payload["classification"] == "internal"  # 断言密级正确写入。
    assert document_payload["uploaded_by"] == "u001"  # 断言 uploaded_by 与 created_by 保持兼容同步。
    assert document_payload["latest_job_id"] == payload["job_id"]  # 断言文档记录里的 latest_job_id 正确回填。
    assert Path(document_payload["storage_path"]).exists()  # 断言原始文件已经落盘。

    job_payload = json.loads(job_path.read_text(encoding="utf-8"))  # 读取 job JSON 内容。
    assert job_payload["doc_id"] == payload["doc_id"]  # 断言 job 记录关联到了正确的文档。
    assert job_payload["status"] == "queued"  # 断言 job 状态为 queued。
    assert job_payload["stage"] == "queued"  # 断言 job 阶段为 queued。
    assert job_payload["progress"] == 0  # 断言初始进度为 0。

    app.dependency_overrides[get_document_service] = lambda: service  # 再次覆盖依赖，准备调用文档详情接口。
    client = TestClient(app)  # 创建新的测试客户端。
    try:  # 用 try/finally 确保详情接口测试结束后也能清理依赖。
        detail_response = client.get(f"/api/v1/documents/{payload['doc_id']}")  # 调用文档详情接口。
    finally:  # 无论详情接口是否成功，都清理依赖覆盖。
        app.dependency_overrides.clear()  # 清空依赖覆盖。

    assert detail_response.status_code == 200  # 断言详情接口返回 200。
    detail_payload = detail_response.json()  # 解析文档详情响应。
    assert detail_payload["doc_id"] == payload["doc_id"]  # 断言返回的是刚创建的文档。
    assert detail_payload["status"] == "queued"  # 断言文档详情状态仍是 queued。
    assert detail_payload["ingest_status"] == "queued"  # 断言 ingest 状态单独返回，避免和文档状态混用。
    assert detail_payload["department_id"] == "after_sales"  # 断言详情返回主部门。
    assert detail_payload["uploaded_by"] == "u001"  # 断言详情返回上传人。
    assert detail_payload["latest_job_id"] == payload["job_id"]  # 断言文档详情里的 latest_job_id 正确。


def test_create_and_ingest_document_with_postgres_asset_storage(tmp_path: Path, monkeypatch) -> None:  # PostgreSQL 资产后端应支持 create -> ingest -> preview/download 全链路。
    monkeypatch.setattr(asset_store_module, "PostgresAssetStore", _FakePostgresAssetStore)
    settings = build_test_settings(
        tmp_path,
        task_always_eager=False,
        asset_store_backend="postgres",
        database_url="postgresql://user:pass@localhost:5432/rag",
    )
    ensure_data_directories(settings)
    service = DocumentService(settings)

    app.dependency_overrides[get_document_service] = lambda: service
    client = TestClient(app)
    content = b"Digitalization team upload asset stored in postgres."

    try:
        create_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("asset_manual.txt", content, "text/plain")},
        )
        assert create_response.status_code == 201
        payload = create_response.json()
        document_payload = json.loads((settings.document_dir / f"{payload['doc_id']}.json").read_text(encoding="utf-8"))
        assert document_payload["storage_path"].startswith("asset://uploads/")

        ingest_status = service.run_ingest_job(payload["job_id"])
        preview_response = client.get(f"/api/v1/documents/{payload['doc_id']}/preview")
        download_response = client.get(f"/api/v1/documents/{payload['doc_id']}/file")
        list_response = client.get("/api/v1/documents")
    finally:
        app.dependency_overrides.clear()

    assert ingest_status.status == "completed"
    assert preview_response.status_code == 200
    assert "Digitalization team upload asset stored in postgres." in preview_response.json()["text_content"]
    assert download_response.status_code == 200
    assert download_response.content == content
    assert list_response.status_code == 200
    listed_item = next(item for item in list_response.json()["items"] if item["document_id"] == payload["doc_id"])
    assert listed_item["size_bytes"] == len(content)


def test_run_ingest_job_supports_mock_ocr_for_image_documents(tmp_path: Path) -> None:  # 图片文档应在 mock OCR 下进入 ocr_processing 并完成入库。
    settings = build_test_settings(tmp_path, ocr_provider="mock")
    ensure_data_directories(settings)
    service = DocumentService(settings)

    app.dependency_overrides[get_document_service] = lambda: service
    client = TestClient(app)

    try:
        create_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("scan.png", b"fake-image-binary", "image/png")},
        )
        assert create_response.status_code == 201
        payload = create_response.json()
        document_record = service._load_document_record(payload["doc_id"])
        sidecar_path = Path(f"{document_record.storage_path}.ocr.txt")
        sidecar_path.write_text("扫描件 OCR 提取文本", encoding="utf-8")

        ingest_status = service.run_ingest_job(payload["job_id"])
        detail_response = client.get(f"/api/v1/documents/{payload['doc_id']}")
    finally:
        app.dependency_overrides.clear()

    assert ingest_status.status == "completed"
    assert ingest_status.stage == "completed"
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "active"
    parsed_text = (settings.parsed_dir / f"{payload['doc_id']}.txt").read_text(encoding="utf-8")
    assert "扫描件 OCR 提取文本" in parsed_text


def test_run_ingest_job_marks_partial_failed_when_pdf_ocr_fallback_is_unavailable(tmp_path: Path) -> None:  # PDF 原生文本太少且 OCR 不可用时，应保留可用结果并标记 partial_failed。
    settings = build_test_settings(tmp_path, ocr_provider="disabled", ocr_pdf_native_text_min_chars=50)
    ensure_data_directories(settings)
    service = DocumentService(settings)

    app.dependency_overrides[get_document_service] = lambda: service
    client = TestClient(app)
    pdf_content = build_minimal_pdf_bytes("short note")

    try:
        create_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("scan_fallback.pdf", pdf_content, "application/pdf")},
        )
        assert create_response.status_code == 201
        payload = create_response.json()

        ingest_status = service.run_ingest_job(payload["job_id"])
        detail_response = client.get(f"/api/v1/documents/{payload['doc_id']}")
        job_response = client.get(f"/api/v1/ingest/jobs/{payload['job_id']}")
    finally:
        app.dependency_overrides.clear()

    assert ingest_status.status == "partial_failed"
    assert ingest_status.stage == "partial_failed"
    assert "OCR provider is disabled for PDF fallback." in (ingest_status.error_message or "")
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "partial_failed"
    assert detail_response.json()["ingest_status"] == "partial_failed"
    assert job_response.status_code == 200
    assert job_response.json()["manual_retry_allowed"] is True
    parsed_text = (settings.parsed_dir / f"{payload['doc_id']}.txt").read_text(encoding="utf-8")
    assert "short note" in parsed_text


def test_document_preview_supports_pdf_inline_stream_from_postgres_asset_storage(tmp_path: Path, monkeypatch) -> None:  # PDF 在线预览接口应支持从 PostgreSQL 二进制资产直接返回文件流。
    monkeypatch.setattr(asset_store_module, "PostgresAssetStore", _FakePostgresAssetStore)
    settings = build_test_settings(
        tmp_path,
        asset_store_backend="postgres",
        database_url="postgresql://user:pass@localhost:5432/rag",
    )
    ensure_data_directories(settings)
    service = DocumentService(settings)

    app.dependency_overrides[get_document_service] = lambda: service
    client = TestClient(app)
    fake_pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"

    try:
        create_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("preview.pdf", fake_pdf, "application/pdf")},
        )
        assert create_response.status_code == 201
        doc_id = create_response.json()["doc_id"]
        preview_response = client.get(f"/api/v1/documents/{doc_id}/preview")
        file_response = client.get(f"/api/v1/documents/{doc_id}/preview/file")
    finally:
        app.dependency_overrides.clear()

    assert preview_response.status_code == 200
    assert preview_response.json()["preview_file_url"] == f"/api/v1/documents/{doc_id}/preview/file"
    assert file_response.status_code == 200
    assert file_response.headers["content-type"].startswith("application/pdf")
    assert "inline" in file_response.headers["content-disposition"]
    assert file_response.content == fake_pdf


def test_list_documents_supports_filters_and_pagination(tmp_path: Path) -> None:  # 验证文档列表支持按状态/主数据筛选与分页。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        first = client.post(  # 创建第一条文档记录。
            "/api/v1/documents",
            data={
                "tenant_id": "wl",
                "department_id": "after_sales",
                "category_id": "alarm",
                "uploaded_by": "alice",
            },
            files={"file": ("alarm_manual.txt", b"Alarm manual", "text/plain")},
        )
        second = client.post(  # 创建第二条文档记录。
            "/api/v1/documents",
            data={
                "tenant_id": "wl",
                "department_id": "after_sales",
                "category_id": "robot",
                "uploaded_by": "bob",
            },
            files={"file": ("robot_manual.txt", b"Robot manual", "text/plain")},
        )
        third = client.post(  # 创建第三条文档记录。
            "/api/v1/documents",
            data={
                "tenant_id": "wl",
                "department_id": "qa",
                "category_id": "process",
                "uploaded_by": "carol",
            },
            files={"file": ("qa_note.txt", b"QA note", "text/plain")},
        )

        assert first.status_code == 201
        assert second.status_code == 201
        assert third.status_code == 201

        second_doc_id = second.json()["doc_id"]  # 拿到第二条文档 ID。
        second_record = service._load_document_record(second_doc_id)  # 读取第二条文档记录并改成 active，构造状态筛选场景。
        second_record.status = "active"
        second_record.updated_at = datetime.now(timezone.utc)
        service._save_document_record(second_record)

        filtered = client.get(  # 同时按部门 + 状态筛选，验证 status 别名参数生效。
            "/api/v1/documents",
            params={
                "department_id": "after_sales",
                "status": "active",
                "page": 1,
                "page_size": 10,
            },
        )
        paged = client.get(  # 按关键字筛选并分页，验证分页字段和值。
            "/api/v1/documents",
            params={
                "keyword": "manual",
                "page": 2,
                "page_size": 1,
            },
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert filtered_payload["total"] == 1
    assert filtered_payload["page"] == 1
    assert filtered_payload["page_size"] == 10
    assert len(filtered_payload["items"]) == 1
    assert filtered_payload["items"][0]["document_id"] == second_doc_id
    assert filtered_payload["items"][0]["department_id"] == "after_sales"
    assert filtered_payload["items"][0]["status"] == "active"

    assert paged.status_code == 200
    paged_payload = paged.json()
    assert paged_payload["total"] == 2
    assert paged_payload["page"] == 2
    assert paged_payload["page_size"] == 1
    assert len(paged_payload["items"]) == 1


def test_batch_create_documents_returns_per_file_results_with_partial_failure(tmp_path: Path) -> None:  # 验证批量上传返回逐文件结果且单文件失败不会中断整批。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(
            "/api/v1/documents/batch",
            data={"tenant_id": "wl", "created_by": "batch-user"},
            files=[
                ("files", ("first.txt", b"first-content", "text/plain")),
                ("files", ("invalid.exe", b"binary", "application/octet-stream")),
                ("files", ("second.md", b"# second", "text/markdown")),
            ],
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 201
    payload = response.json()
    assert payload["total"] == 3
    assert payload["queued"] == 2
    assert payload["failed"] == 1
    assert len(payload["items"]) == 3

    queued_items = [item for item in payload["items"] if item["status"] == "queued"]
    failed_items = [item for item in payload["items"] if item["status"] == "failed"]
    assert len(queued_items) == 2
    assert len(failed_items) == 1

    failed_item = failed_items[0]
    assert failed_item["file_name"] == "invalid.exe"
    assert failed_item["http_status"] == 400
    assert "Unsupported file type" in failed_item["error_message"]

    for item in queued_items:
        assert item["doc_id"].startswith("doc_")
        assert item["job_id"].startswith("job_")
        assert item["error_message"] is None

        document_path = settings.document_dir / f"{item['doc_id']}.json"
        job_path = settings.job_dir / f"{item['job_id']}.json"
        assert document_path.exists()
        assert job_path.exists()

        document_payload = json.loads(document_path.read_text(encoding="utf-8"))
        assert document_payload["tenant_id"] == "wl"
        assert document_payload["uploaded_by"] == "batch-user"


def test_batch_create_documents_handles_duplicate_without_aborting(tmp_path: Path) -> None:  # 验证批量上传命中重复文档时只影响当前文件，不影响其他文件。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(
            "/api/v1/documents/batch",
            data={"tenant_id": "wl"},
            files=[
                ("files", ("dup_a.txt", b"same-content", "text/plain")),
                ("files", ("dup_b.txt", b"same-content", "text/plain")),
            ],
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 201
    payload = response.json()
    assert payload["total"] == 2
    assert payload["queued"] == 2
    assert payload["failed"] == 0

    queued_items = [item for item in payload["items"] if item["status"] == "queued"]
    assert len(queued_items) == 2
    assert queued_items[0]["doc_id"] == queued_items[1]["doc_id"]  # 同内容命中覆盖逻辑，应复用同一 doc_id。
    assert queued_items[0]["job_id"] == queued_items[1]["job_id"]  # 旧任务仍在进行中时应复用同一 job，避免并发重复入队。
    assert queued_items[0]["error_message"] is None
    assert queued_items[1]["error_message"] is None


def test_create_document_requeues_failed_duplicate_with_new_job(tmp_path: Path) -> None:  # 验证重复文档处于 failed/dead_letter 时，重新上传会自动补发新任务而不是卡 409。
    settings = build_test_settings(tmp_path, task_always_eager=False)  # 构造测试配置，便于观察 queued 状态和新 job 生成。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        first_create = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl", "created_by": "alice"},
            files={"file": ("origin.txt", b"same-hash-content", "text/plain")},
        )
        assert first_create.status_code == 201
        first_payload = first_create.json()
        doc_id = first_payload["doc_id"]
        old_job_id = first_payload["job_id"]

        failed_job_record = service._load_job_record(old_job_id)  # 模拟历史任务已死信。
        service._update_job_record(
            failed_job_record,
            status="dead_letter",
            stage="dead_letter",
            progress=100,
            error_code="INGEST_VALIDATION_ERROR_DEAD_LETTER",
            error_message="legacy failure",
            increase_retry=True,
        )
        failed_doc_record = service._load_document_record(doc_id)  # 文档状态也模拟为 failed。
        failed_doc_record.status = "failed"
        service._save_document_record(failed_doc_record)

        second_create = client.post(  # 用同内容重新上传，预期自动补发新 job。
            "/api/v1/documents",
            data={"tenant_id": "wl", "created_by": "bob"},
            files={"file": ("retry_named.txt", b"same-hash-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert second_create.status_code == 201
    second_payload = second_create.json()
    assert second_payload["status"] == "queued"
    assert second_payload["doc_id"] == doc_id  # 复用同一个 doc_id，仅生成新 job。
    assert second_payload["job_id"] != old_job_id

    refreshed_doc_record = service._load_document_record(doc_id)
    assert refreshed_doc_record.latest_job_id == second_payload["job_id"]
    assert refreshed_doc_record.status == "queued"
    assert refreshed_doc_record.file_name == "retry_named.txt"  # 重复上传会刷新文件名，避免沿用历史脏后缀。
    assert refreshed_doc_record.source_type == "txt"
    assert refreshed_doc_record.uploaded_by == "bob"


def test_create_document_requeues_stale_inflight_duplicate_with_new_job(tmp_path: Path) -> None:  # 卡在历史 queued/indexing 的旧任务超过阈值后，重复上传应补发新 job，而不是继续复用旧 job。
    settings = build_test_settings(tmp_path, task_always_eager=False).model_copy(update={"ingest_inflight_stale_seconds": 60})
    ensure_data_directories(settings)
    service = DocumentService(settings)

    app.dependency_overrides[get_document_service] = lambda: service
    client = TestClient(app)

    try:
        first_create = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl", "created_by": "alice"},
            files={"file": ("origin.txt", b"same-hash-content", "text/plain")},
        )
        assert first_create.status_code == 201
        first_payload = first_create.json()
        doc_id = first_payload["doc_id"]
        old_job_id = first_payload["job_id"]

        stale_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        stale_job_record = service._load_job_record(old_job_id)
        stale_job_record.status = "indexing"
        stale_job_record.stage = "indexing"
        stale_job_record.progress = 90
        stale_job_record.updated_at = stale_time
        service._save_job_record(stale_job_record)

        stale_doc_record = service._load_document_record(doc_id)
        stale_doc_record.status = "queued"
        stale_doc_record.updated_at = stale_time
        service._save_document_record(stale_doc_record)

        second_create = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl", "created_by": "bob"},
            files={"file": ("retry_named.txt", b"same-hash-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()

    assert second_create.status_code == 201
    second_payload = second_create.json()
    assert second_payload["status"] == "queued"
    assert second_payload["doc_id"] == doc_id
    assert second_payload["job_id"] != old_job_id  # 过期 in-flight job 不应再被复用。
    assert len(list(settings.job_dir.glob("*.json"))) == 2  # 应创建 follow-up job，供当前上传继续执行。

    refreshed_doc_record = service._load_document_record(doc_id)
    assert refreshed_doc_record.latest_job_id == second_payload["job_id"]
    assert refreshed_doc_record.file_name == "retry_named.txt"
    assert refreshed_doc_record.uploaded_by == "bob"


def test_document_preview_returns_text_preview_with_truncation(tmp_path: Path) -> None:  # 验证文本文档预览接口可返回截断后的文本内容。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        create_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("preview.txt", b"abcdefg1234567", "text/plain")},
        )
        assert create_response.status_code == 201
        doc_id = create_response.json()["doc_id"]
        preview_response = client.get(f"/api/v1/documents/{doc_id}/preview", params={"max_chars": 8})
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["doc_id"] == doc_id
    assert preview_payload["preview_type"] == "text"
    assert preview_payload["text_content"] == "abcdefg1"
    assert preview_payload["text_truncated"] is True
    assert preview_payload["preview_file_url"] is None


def test_document_preview_supports_pdf_inline_stream(tmp_path: Path) -> None:  # 验证 PDF 预览接口可返回在线预览元数据和文件流。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    fake_pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"  # 使用最小 PDF 字节流构造测试文件。

    try:  # 确保测试结束后清理依赖覆盖。
        create_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("preview.pdf", fake_pdf, "application/pdf")},
        )
        assert create_response.status_code == 201
        doc_id = create_response.json()["doc_id"]
        preview_response = client.get(f"/api/v1/documents/{doc_id}/preview")
        file_response = client.get(f"/api/v1/documents/{doc_id}/preview/file")
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["doc_id"] == doc_id
    assert preview_payload["preview_type"] == "pdf"
    assert preview_payload["preview_file_url"] == f"/api/v1/documents/{doc_id}/preview/file"

    assert file_response.status_code == 200
    assert file_response.headers["content-type"].startswith("application/pdf")
    assert "inline" in file_response.headers["content-disposition"]
    assert file_response.content == fake_pdf


def test_delete_document_marks_deleted_and_removes_vector_points(tmp_path: Path) -> None:  # 验证删除文档会先改主数据状态并清理向量副本。
    settings = build_test_settings(tmp_path, task_always_eager=False)  # 构造测试配置，手动执行入库任务。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        create_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("delete_me.txt", b"delete vector payload", "text/plain")},
        )
        assert create_response.status_code == 201
        payload = create_response.json()
        doc_id = payload["doc_id"]
        job_id = payload["job_id"]

        run_result = service.run_ingest_job(job_id)  # 手动执行一次入库，确保向量副本存在。
        assert run_result.status == "completed"
        assert service.ingestion_service.vector_store.has_document_points(doc_id) is True

        delete_response = client.delete(f"/api/v1/documents/{doc_id}")
        detail_response = client.get(f"/api/v1/documents/{doc_id}")
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert delete_response.status_code == 200
    delete_payload = delete_response.json()
    assert delete_payload["doc_id"] == doc_id
    assert delete_payload["status"] == "deleted"
    assert delete_payload["vector_points_removed"] >= 1
    assert service.ingestion_service.vector_store.has_document_points(doc_id) is False

    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "deleted"


def test_delete_document_is_idempotent(tmp_path: Path) -> None:  # 验证重复删除同一文档时接口行为幂等。
    settings = build_test_settings(tmp_path, task_always_eager=False)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        create_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("delete_idempotent.txt", b"delete idempotent payload", "text/plain")},
        )
        assert create_response.status_code == 201
        payload = create_response.json()
        doc_id = payload["doc_id"]
        job_id = payload["job_id"]

        run_result = service.run_ingest_job(job_id)  # 先写入向量副本。
        assert run_result.status == "completed"

        first_delete = client.delete(f"/api/v1/documents/{doc_id}")
        second_delete = client.delete(f"/api/v1/documents/{doc_id}")
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert first_delete.status_code == 200
    assert second_delete.status_code == 200
    assert first_delete.json()["status"] == "deleted"
    assert second_delete.json()["status"] == "deleted"
    assert second_delete.json()["vector_points_removed"] == 0  # 第二次删除时向量副本应已清理，返回 0。


def test_rebuild_document_vectors_creates_followup_job_and_cleans_previous_points(tmp_path: Path) -> None:  # 验证重建向量接口会复用 ingest job 机制并先清理旧向量。
    settings = build_test_settings(tmp_path, task_always_eager=False)  # 构造测试配置，便于观察 queued 状态。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        create_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("rebuild_me.txt", b"rebuild vector payload", "text/plain")},
        )
        assert create_response.status_code == 201
        created_payload = create_response.json()
        doc_id = created_payload["doc_id"]
        old_job_id = created_payload["job_id"]

        first_run = service.run_ingest_job(old_job_id)  # 先跑一次完整入库，让文档已有向量点位。
        assert first_run.status == "completed"
        assert service.ingestion_service.vector_store.has_document_points(doc_id) is True

        rebuild_response = client.post(f"/api/v1/documents/{doc_id}/rebuild")
        assert rebuild_response.status_code == 202
        rebuild_payload = rebuild_response.json()
        new_job_id = rebuild_payload["job_id"]

        rebuilt_record = service._load_document_record(doc_id)
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert rebuild_payload["doc_id"] == doc_id
    assert rebuild_payload["status"] == "queued"
    assert rebuild_payload["job_id"] != old_job_id
    assert rebuild_payload["previous_vector_points_removed"] >= 1
    assert rebuilt_record.status == "queued"  # 触发重建后文档状态应回到 queued，等待新任务执行。
    assert rebuilt_record.latest_job_id == new_job_id
    assert service.ingestion_service.vector_store.has_document_points(doc_id) is False  # 旧向量应先被清理。

    second_run = service.run_ingest_job(new_job_id)  # 新任务执行后应恢复可检索状态。
    assert second_run.status == "completed"
    assert service.ingestion_service.vector_store.has_document_points(doc_id) is True


def test_rebuild_document_vectors_ignores_stale_inflight_job(tmp_path: Path) -> None:  # 历史卡住的 in-flight 任务不应阻塞新的重建请求。
    settings = build_test_settings(tmp_path, task_always_eager=False).model_copy(update={"ingest_inflight_stale_seconds": 60})
    ensure_data_directories(settings)
    service = DocumentService(settings)

    app.dependency_overrides[get_document_service] = lambda: service
    client = TestClient(app)

    try:
        create_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("stale_rebuild.txt", b"stale rebuild payload", "text/plain")},
        )
        assert create_response.status_code == 201
        created_payload = create_response.json()
        doc_id = created_payload["doc_id"]
        old_job_id = created_payload["job_id"]

        stale_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        stale_job = service._load_job_record(old_job_id)
        stale_job.status = "indexing"
        stale_job.stage = "indexing"
        stale_job.progress = 90
        stale_job.updated_at = stale_time
        service._save_job_record(stale_job)

        stale_doc = service._load_document_record(doc_id)
        stale_doc.status = "queued"
        stale_doc.updated_at = stale_time
        service._save_document_record(stale_doc)

        rebuild_response = client.post(f"/api/v1/documents/{doc_id}/rebuild")
    finally:
        app.dependency_overrides.clear()

    assert rebuild_response.status_code == 202
    rebuild_payload = rebuild_response.json()
    assert rebuild_payload["doc_id"] == doc_id
    assert rebuild_payload["job_id"] != old_job_id
    assert rebuild_payload["status"] == "queued"

    rebuilt_record = service._load_document_record(doc_id)
    assert rebuilt_record.latest_job_id == rebuild_payload["job_id"]


def test_rebuild_document_vectors_rejects_deleted_document(tmp_path: Path) -> None:  # 验证已删除文档不能触发重建向量。
    settings = build_test_settings(tmp_path, task_always_eager=False)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        create_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("deleted_rebuild.txt", b"payload", "text/plain")},
        )
        assert create_response.status_code == 201
        doc_id = create_response.json()["doc_id"]

        delete_response = client.delete(f"/api/v1/documents/{doc_id}")  # 先删除文档，构造已删除场景。
        assert delete_response.status_code == 200

        rebuild_response = client.post(f"/api/v1/documents/{doc_id}/rebuild")
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert rebuild_response.status_code == 409
    assert "Deleted document cannot rebuild vectors" in rebuild_response.json()["detail"]


def test_create_document_normalizes_blank_metadata_values(tmp_path: Path) -> None:  # 测试队列化上传接口会清洗空白数组项和空白字符串。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(
            "/api/v1/documents",
            data={
                "tenant_id": "  wl  ",  # tenant_id 会被 strip 后再写入。
                "department_ids": ["", " after_sales ", "   "],  # 空白项应该被丢弃。
                "role_ids": ["", "engineer"],  # 空白项应该被丢弃。
                "owner_id": "   ",  # 空白字符串应转成 None。
                "tags": ["", "manual", "   "],  # 空白项应该被丢弃。
                "source_system": "   ",  # 空白字符串应转成 None。
                "created_by": "  reggie  ",  # 非空字符串会被 strip。
            },
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 201  # 清洗后仍应成功创建文档。
    payload = response.json()  # 解析创建响应。
    document_path = settings.document_dir / f"{payload['doc_id']}.json"  # 取到刚写入的 document 元数据文件。
    document_payload = json.loads(document_path.read_text(encoding="utf-8"))  # 读取并解析 document 元数据。

    assert document_payload["tenant_id"] == "wl"  # tenant_id 应被 strip。
    assert document_payload["department_ids"] == ["after_sales"]  # 空白部门值应被丢弃。
    assert document_payload["department_id"] == "after_sales"  # 主部门应自动回填为第一项部门。
    assert document_payload["role_ids"] == ["engineer"]  # 空白角色值应被丢弃。
    assert document_payload["tags"] == ["manual"]  # 空白标签值应被丢弃。
    assert document_payload["owner_id"] is None  # 空白 owner_id 应转成 None。
    assert document_payload["source_system"] is None  # 空白 source_system 应转成 None。
    assert document_payload["created_by"] == "reggie"  # 非空 created_by 应被 strip。
    assert document_payload["uploaded_by"] == "reggie"  # 新字段 uploaded_by 应和 created_by 同步。


def test_create_document_accepts_v2_master_metadata_fields(tmp_path: Path) -> None:  # 测试 v0.2 主数据字段（department_id/category_id/uploaded_by）可写入并兼容旧字段。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(
            "/api/v1/documents",
            data={
                "tenant_id": "wl",
                "department_id": "after_sales",  # 仅传主部门，不传 department_ids。
                "category_id": "robot_alarm",
                "uploaded_by": "operator-001",  # 使用新字段命名，不传 created_by。
            },
            files={"file": ("v2-master.txt", b"v2-master-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 201  # 创建应成功。
    payload = response.json()  # 解析创建响应。
    document_path = settings.document_dir / f"{payload['doc_id']}.json"  # 获取刚写入的 document 元数据文件。
    document_payload = json.loads(document_path.read_text(encoding="utf-8"))  # 读取 document 元数据。

    assert document_payload["department_id"] == "after_sales"  # 主部门应正确写入。
    assert document_payload["department_ids"] == ["after_sales"]  # 仅传主部门时，应自动补齐部门范围。
    assert document_payload["category_id"] == "robot_alarm"  # 分类应正确写入。
    assert document_payload["uploaded_by"] == "operator-001"  # 新字段上传人应正确写入。
    assert document_payload["created_by"] == "operator-001"  # 旧字段 created_by 应保持兼容同步。


def test_create_document_preserves_extension_after_sanitize(tmp_path: Path) -> None:  # 测试中文等文件名被清洗后仍保留扩展名，避免后续解析阶段识别为 unknown。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        content = f"报警处理手册-{time.time_ns()}".encode("utf-8")  # 使用纳秒时间戳生成唯一内容，避免哈希去重导致 409。
        response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("说明书.txt", content, "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 201  # 上传应成功进入 queued。
    payload = response.json()  # 解析响应。
    document_record = service._load_document_record(payload["doc_id"])  # 读取持久化记录（兼容 JSON/PG 两种模式）。
    storage_name = Path(document_record.storage_path).name  # 取落盘文件名。

    assert document_record.source_type == "txt"  # source_type 必须保持 txt。
    assert storage_name.endswith(".txt")  # 落盘文件名必须保留扩展名，供 parser 识别。


def test_create_document_rejects_file_larger_than_limit(tmp_path: Path) -> None:  # 测试上传文件超过大小限制时返回 413。
    settings = build_test_settings(tmp_path).model_copy(update={"upload_max_file_size_bytes": 8})  # 把上限调小，便于构造边界测试。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"123456789", "text/plain")},  # 9 字节，超过 8 字节上限。
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 413  # 超限时应返回 413。
    detail = response.json()["detail"]  # 提取错误详情。
    assert "Maximum allowed size is 8 bytes" in detail  # 错误信息应包含当前上限。


def test_get_ingest_job_status_after_create_document(tmp_path: Path) -> None:  # 测试创建文档后可通过 ingest job 接口查询任务状态。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        create_response = client.post(  # 先创建文档，拿到 job_id。
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
        create_payload = create_response.json()  # 解析创建响应。
        job_response = client.get(f"/api/v1/ingest/jobs/{create_payload['job_id']}")  # 调用 ingest job 状态接口。
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert create_response.status_code == 201  # 创建文档应成功。
    assert job_response.status_code == 200  # 已存在的 job_id 应返回 200。
    job_payload = job_response.json()  # 解析任务状态响应。
    assert job_payload["job_id"] == create_payload["job_id"]  # 断言返回的 job_id 与创建响应一致。
    assert job_payload["doc_id"] == create_payload["doc_id"]  # 断言返回的 doc_id 与创建响应一致。
    assert job_payload["status"] == "queued"  # 初始状态应为 queued。
    assert job_payload["stage"] == "queued"  # 初始阶段应为 queued。
    assert job_payload["progress"] == 0  # 初始进度应为 0。
    assert job_payload["max_retry_limit"] == settings.ingest_failure_retry_limit  # 状态响应应返回当前重试上限配置。
    assert job_payload["auto_retry_eligible"] is False  # queued 状态不应标记为自动重试。
    assert job_payload["manual_retry_allowed"] is True  # queued 状态允许管理端重投递。


def test_run_ingest_job_requeues_job_status(tmp_path: Path) -> None:  # 测试手动触发 run 接口后会把任务重新投递到异步队列。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        create_response = client.post(  # 先创建文档，拿到 doc_id 和 job_id。
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={
                "file": (
                    "manual.txt",
                    (
                        "Alarm E102 handling guide.\n"
                        "Step 1: Check voltage.\n"
                        "Step 2: Reset the device and inspect sensor."
                    ).encode("utf-8"),
                    "text/plain",
                )
            },
        )
        create_payload = create_response.json()  # 解析创建响应。
        run_response = client.post(f"/api/v1/ingest/jobs/{create_payload['job_id']}/run")  # 手动触发任务执行。
        detail_response = client.get(f"/api/v1/documents/{create_payload['doc_id']}")  # 查询文档详情确认状态。
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert create_response.status_code == 201  # 创建文档应成功。
    assert run_response.status_code == 200  # 触发执行接口应成功返回。
    run_payload = run_response.json()  # 解析执行响应。
    assert run_payload["job_id"] == create_payload["job_id"]  # 响应应对应刚创建的 job。
    assert run_payload["status"] == "queued"  # 异步模式下 run 接口应返回已重新入队状态。
    assert run_payload["stage"] == "queued"  # 当前阶段应保持 queued，等待 worker 消费。
    assert run_payload["progress"] == 0  # 重新入队后进度应重置为 0。
    assert run_payload["manual_retry_allowed"] is True  # queued 任务允许再次管理重投递。
    assert run_payload["auto_retry_eligible"] is False  # queued 状态不属于自动重试窗口。
    assert detail_response.status_code == 200  # 文档详情接口应可用。
    assert detail_response.json()["status"] == "queued"  # 文档状态应回到 queued，等待 worker 真正执行。
    assert service.ingestion_service.vector_store.count_points() == 0  # 仅重新入队时不应在当前进程直接写入向量。


def test_create_document_overwrites_duplicate_file_hash_within_same_tenant(tmp_path: Path) -> None:  # 测试同租户重复上传相同内容时会覆盖旧文档并补发新任务。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        first_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"same-content", "text/plain")},
        )
        second_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"same-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert first_response.status_code == 201  # 第一次上传应成功创建。
    assert second_response.status_code == 201  # 第二次同内容上传应走覆盖并补发新任务。
    first_payload = first_response.json()
    second_payload = second_response.json()
    assert second_payload["doc_id"] == first_payload["doc_id"]  # 复用历史文档 ID。
    assert second_payload["job_id"] == first_payload["job_id"]  # 旧任务仍在进行中时复用已有 job。
    assert len(list(settings.document_dir.glob("*.json"))) == 1  # documents 元数据目录里仍只有一份文档。
    assert len(list(settings.job_dir.glob("*.json"))) == 1  # 复用 in-flight 任务时不应额外创建 job。


def test_create_document_requeues_duplicate_when_completed_job_has_no_vectors(tmp_path: Path) -> None:  # 已完成旧任务对应的向量丢失时，应补发新 job，而不是继续返回旧 doc/job。
    settings = build_test_settings(tmp_path)  # 用非 eager 模式模拟“元数据已完成，但当前 collection 无向量”的线上场景。
    ensure_data_directories(settings)
    service = DocumentService(settings)

    app.dependency_overrides[get_document_service] = lambda: service
    client = TestClient(app)

    try:
        first_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"same-content", "text/plain")},
        )
        first_payload = first_response.json()
        first_job = service._load_job_record(first_payload["job_id"])  # 手工把旧 job 标成 completed，模拟历史 job 已完成。
        first_document = service._load_document_record(first_payload["doc_id"])
        service._update_job_record(
            first_job,
            status="completed",
            stage="completed",
            progress=100,
        )
        first_document.status = "active"
        service._save_document_record(first_document)
        second_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"same-content", "text/plain")},
        )
        second_payload = second_response.json()
    finally:
        app.dependency_overrides.clear()

    assert first_response.status_code == 201
    assert second_response.status_code == 201  # 向量已丢失时，应补发新 job，而不是返回 409。
    assert second_payload["doc_id"] == first_payload["doc_id"]  # 复用已有文档 ID。
    assert second_payload["job_id"] != first_payload["job_id"]  # 但要生成新的 job。
    latest_job_path = settings.job_dir / f"{second_payload['job_id']}.json"
    latest_document_path = settings.document_dir / f"{first_payload['doc_id']}.json"
    assert latest_job_path.exists()  # 新 job 元数据应已创建。
    assert json.loads(latest_document_path.read_text(encoding="utf-8"))["latest_job_id"] == second_payload["job_id"]
    assert json.loads(latest_job_path.read_text(encoding="utf-8"))["status"] == "queued"  # 非 eager 模式下补发任务应进入队列等待 worker 消费。


def test_create_document_requeues_duplicate_with_fresh_upload_when_legacy_source_is_missing(tmp_path: Path) -> None:  # 老文档已完成但源文件丢失时，重新上传相同内容应刷新源文件并允许新 job 完成。
    settings = build_test_settings(tmp_path, task_always_eager=False)
    ensure_data_directories(settings)
    service = DocumentService(settings)

    app.dependency_overrides[get_document_service] = lambda: service
    client = TestClient(app)

    try:
        first_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"same-content", "text/plain")},
        )
        first_payload = first_response.json()
        first_job = service._load_job_record(first_payload["job_id"])
        first_document = service._load_document_record(first_payload["doc_id"])
        original_storage_path = Path(first_document.storage_path)
        original_storage_path.unlink()  # 删掉第一次上传落盘的文件，模拟线上历史源文件已经丢失。
        first_document.storage_path = f"/legacy/worktree/data/uploads/{original_storage_path.name}"  # 再把元数据改成宿主机旧绝对路径，模拟容器切换后的典型坏路径。
        first_document.status = "active"
        service._save_document_record(first_document)
        service._update_job_record(
            first_job,
            status="completed",
            stage="completed",
            progress=100,
        )
        second_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual-renamed.txt", b"same-content", "text/plain")},
        )
        second_payload = second_response.json()
    finally:
        app.dependency_overrides.clear()

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    refreshed_document = service._load_document_record(first_payload["doc_id"])
    refreshed_source_path = Path(refreshed_document.storage_path)
    assert refreshed_document.file_name == "manual-renamed.txt"  # 重复补发应刷新 file_name，避免沿用历史文件名。
    assert refreshed_document.source_type == "txt"
    assert refreshed_source_path == settings.upload_dir / f"{first_payload['doc_id']}__manual-renamed.txt"  # 重复补发应把源文件重建到当前 upload_dir，而不是继续引用坏掉的旧绝对路径。
    assert refreshed_source_path.read_bytes() == b"same-content"  # 本次重新上传的内容应已落盘，供后续 worker 读取。

    run_result = service.run_ingest_job(second_payload["job_id"])

    assert run_result.status == "completed"
    assert service.ingestion_service.vector_store.has_document_points(first_payload["doc_id"]) is True


def test_run_ingest_job_remaps_legacy_storage_path_to_current_upload_dir(tmp_path: Path) -> None:  # 历史元数据里的宿主机绝对路径在容器里失效时，应自动映射到当前 upload_dir。
    settings = build_test_settings(tmp_path, task_always_eager=False)
    ensure_data_directories(settings)
    service = DocumentService(settings)

    legacy_name = "doc_legacy__manual.txt"
    current_upload_path = settings.upload_dir / legacy_name
    current_upload_path.write_text("Alarm E102 handling guide.", encoding="utf-8")

    document_record = DocumentRecord(
        doc_id="doc_legacy",
        tenant_id="wl",
        file_name="manual.txt",
        file_hash="legacy-hash",
        source_type="txt",
        department_ids=[],
        role_ids=[],
        owner_id=None,
        visibility="private",
        classification="internal",
        tags=[],
        source_system=None,
        status="queued",
        current_version=1,
        latest_job_id="job_legacy",
        storage_path=f"/legacy/worktree/data/uploads/{legacy_name}",
        created_by="tester",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    job_record = IngestJobRecord(
        job_id="job_legacy",
        doc_id="doc_legacy",
        version=1,
        file_name="manual.txt",
        status="queued",
        stage="queued",
        progress=0,
        retry_count=0,
        error_code=None,
        error_message=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service._save_document_record(document_record)
    service._save_job_record(job_record)

    result = service.run_ingest_job("job_legacy")
    remapped_document = service._load_document_record("doc_legacy")

    assert result.status == "completed"
    assert remapped_document.storage_path == str(current_upload_path)  # 元数据应被修正成当前运行环境下真实可访问的路径。
    assert service.ingestion_service.vector_store.has_document_points("doc_legacy") is True


def test_run_ingest_job_marks_missing_storage_path_as_runtime_failure(tmp_path: Path) -> None:  # 文件真实缺失且无回退路径时，不应卡在 parsing。
    settings = build_test_settings(tmp_path).model_copy(update={"ingest_failure_retry_limit": 1})
    ensure_data_directories(settings)
    service = DocumentService(settings)

    missing_document = DocumentRecord(
        doc_id="doc_missing",
        tenant_id="wl",
        file_name="manual.txt",
        file_hash="missing-hash",
        source_type="txt",
        department_ids=[],
        role_ids=[],
        owner_id=None,
        visibility="private",
        classification="internal",
        tags=[],
        source_system=None,
        status="queued",
        current_version=1,
        latest_job_id="job_missing",
        storage_path="/definitely/missing/manual.txt",
        created_by="tester",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    missing_job = IngestJobRecord(
        job_id="job_missing",
        doc_id="doc_missing",
        version=1,
        file_name="manual.txt",
        status="queued",
        stage="queued",
        progress=0,
        retry_count=0,
        error_code=None,
        error_message=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service._save_document_record(missing_document)
    service._save_job_record(missing_job)

    result = service.run_ingest_job("job_missing")

    assert result.status == "dead_letter"
    assert result.error_code == "INGEST_RUNTIME_ERROR_DEAD_LETTER"
    assert "No such file or directory" in (result.error_message or "")


def test_create_document_allows_same_filename_with_different_content(tmp_path: Path) -> None:  # 测试仅按 file_hash 去重，不会误伤同名不同内容的文档。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        first_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"content-v1", "text/plain")},
        )
        second_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"content-v2", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert first_response.status_code == 201  # 首次上传应成功。
    assert second_response.status_code == 201  # 同名不同内容应允许创建新文档。
    assert first_response.json()["doc_id"] != second_response.json()["doc_id"]  # 两次上传应生成不同文档 ID。
    assert len(list(settings.document_dir.glob("*.json"))) == 2  # documents 元数据目录里应保留两条记录。


def test_run_ingest_job_eager_executes_to_completion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试 eager 模式下 run 接口会真正执行完整入库链路。
    settings = build_test_settings(tmp_path, task_always_eager=True)  # 构造 eager 测试配置，让 Celery 在当前进程直接执行任务。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        with monkeypatch.context() as patch_ctx:  # 先临时屏蔽 create_document 阶段的自动投递，避免创建接口直接跑完整个任务。
            patch_ctx.setattr(
                "backend.app.services.document_service.dispatch_ingest_job",
                lambda *args, **kwargs: None,
            )
            create_response = client.post(
                "/api/v1/documents",
                data={"tenant_id": "wl"},
                files={
                    "file": (
                        "manual.txt",
                        (
                            "Alarm E102 handling guide.\n"
                            "Step 1: Check voltage.\n"
                            "Step 2: Reset the device and inspect sensor."
                        ).encode("utf-8"),
                        "text/plain",
                    )
                },
            )
        create_payload = create_response.json()  # 解析创建响应。
        run_response = client.post(f"/api/v1/ingest/jobs/{create_payload['job_id']}/run")  # 在 eager 模式下重投递，同步拿到执行结果。
        detail_response = client.get(f"/api/v1/documents/{create_payload['doc_id']}")  # 查询文档详情确认状态。
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert create_response.status_code == 201  # 创建文档应成功。
    assert run_response.status_code == 200  # 触发执行接口应成功返回。
    run_payload = run_response.json()  # 解析执行响应。
    assert run_payload["job_id"] == create_payload["job_id"]  # 响应应对应刚创建的 job。
    assert run_payload["status"] == "completed"  # eager 模式下任务应执行完成。
    assert run_payload["stage"] == "completed"  # 最终阶段应是 completed。
    assert run_payload["progress"] == 100  # 完成后进度应为 100。
    assert run_payload["manual_retry_allowed"] is False  # completed 状态不允许再手动重投递。
    assert run_payload["auto_retry_eligible"] is False  # completed 状态不属于自动重试窗口。
    assert detail_response.status_code == 200  # 文档详情接口应可用。
    assert detail_response.json()["status"] == "active"  # 文档状态应更新为 active。
    assert (settings.parsed_dir / f"{create_payload['doc_id']}.txt").exists()  # eager 任务执行后应生成解析文本文件。
    assert (settings.chunk_dir / f"{create_payload['doc_id']}.json").exists()  # eager 任务执行后应生成 chunk 结果文件。


def test_non_eager_worker_consumes_queued_job_to_completion(tmp_path: Path) -> None:  # 测试非 eager 模式下，worker 任务入口可把 queued 任务推进到 completed。
    settings = build_test_settings(tmp_path, task_always_eager=False)  # 显式关闭 eager，模拟真实队列消费模式。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        create_response = client.post(  # 先创建文档和 ingest job。
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={
                "file": (
                    "manual.txt",
                    (
                        "Alarm E102 handling guide.\n"
                        "Step 1: Check voltage.\n"
                        "Step 2: Reset the device and inspect sensor."
                    ).encode("utf-8"),
                    "text/plain",
                )
            },
        )
        create_payload = create_response.json()  # 解析创建响应。

        before_job = client.get(f"/api/v1/ingest/jobs/{create_payload['job_id']}")  # worker 消费前先读取一次任务状态。
        assert before_job.status_code == 200  # 任务状态接口应可用。
        assert before_job.json()["status"] == "queued"  # 非 eager 场景下创建后应保持 queued。
        assert service.ingestion_service.vector_store.count_points() == 0  # 仅创建任务时不应直接写入向量库。

        celery_app = get_celery_app(settings)  # 取到当前测试配置对应的 Celery app。
        task_result = celery_app.tasks[INGEST_TASK_NAME].apply(args=[create_payload["job_id"]], throw=True)  # 直接调用任务入口，模拟 worker 消费。
        task_payload = task_result.result  # 读取任务执行返回结果。

        detail_response = client.get(f"/api/v1/documents/{create_payload['doc_id']}")  # 查询文档详情确认状态推进。
        job_response = client.get(f"/api/v1/ingest/jobs/{create_payload['job_id']}")  # 查询任务详情确认完成状态。
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert create_response.status_code == 201  # 创建文档应成功。
    assert task_payload["status"] == "completed"  # worker 消费后任务应完成。
    assert task_payload["stage"] == "completed"  # 最终阶段应为 completed。
    assert task_payload["progress"] == 100  # 完成后进度应为 100。
    assert detail_response.status_code == 200  # 文档详情接口应可用。
    assert detail_response.json()["status"] == "active"  # 文档应切到 active，可参与检索。
    assert job_response.status_code == 200  # job 状态接口应可用。
    assert job_response.json()["status"] == "completed"  # job 终态应为 completed。
    assert job_response.json()["manual_retry_allowed"] is False  # completed 任务不允许再手动重投递。
    assert (settings.parsed_dir / f"{create_payload['doc_id']}.txt").exists()  # 非 eager worker 消费后应生成解析文件。
    assert (settings.chunk_dir / f"{create_payload['doc_id']}.json").exists()  # 非 eager worker 消费后应生成 chunk 文件。


def test_non_eager_worker_moves_job_to_dead_letter_on_runtime_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试非 eager 模式下 worker 运行异常会进入 dead_letter。
    settings = build_test_settings(tmp_path, task_always_eager=False).model_copy(update={"ingest_failure_retry_limit": 1})  # 失败上限设为 1，首错即 dead_letter。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    def raise_runtime_error(self: object, *args: object, **kwargs: object) -> object:  # 构造全局失败桩，模拟 worker 执行依赖故障。
        raise RuntimeError("worker runtime error")

    monkeypatch.setattr(  # 给 DocumentIngestionService 打桩，确保 worker 新建服务实例也会命中该失败逻辑。
        "backend.app.services.ingestion_service.DocumentIngestionService.ingest_document",
        raise_runtime_error,
    )

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        create_response = client.post(  # 先创建文档和 ingest job。
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
        create_payload = create_response.json()  # 解析创建响应。

        celery_app = get_celery_app(settings)  # 取到当前测试配置对应的 Celery app。
        task_result = celery_app.tasks[INGEST_TASK_NAME].apply(args=[create_payload["job_id"]], throw=True)  # 调用 worker 任务入口，触发失败路径。
        task_payload = task_result.result  # 读取任务执行返回结果。

        detail_response = client.get(f"/api/v1/documents/{create_payload['doc_id']}")  # 查询文档状态。
        job_response = client.get(f"/api/v1/ingest/jobs/{create_payload['job_id']}")  # 查询任务状态。
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert create_response.status_code == 201  # 创建文档应成功。
    assert task_payload["status"] == "dead_letter"  # 失败达到上限后应进入 dead_letter。
    assert task_payload["stage"] == "dead_letter"  # 阶段应同步为 dead_letter。
    assert task_payload["retry_count"] == 1  # 首次失败即达到上限时重试计数应为 1。
    assert task_payload["error_code"] == "INGEST_RUNTIME_ERROR_DEAD_LETTER"  # 错误码应带 dead_letter 后缀。
    assert detail_response.status_code == 200  # 文档详情接口应可用。
    assert detail_response.json()["status"] == "failed"  # 文档状态应保持 failed，避免误判可检索。
    assert job_response.status_code == 200  # job 状态接口应可用。
    assert job_response.json()["status"] == "dead_letter"  # job 状态应落到 dead_letter。
    assert job_response.json()["auto_retry_eligible"] is False  # dead_letter 不应继续自动重试。
    assert job_response.json()["manual_retry_allowed"] is True  # dead_letter 允许管理端手动重投递。


def test_run_ingest_job_moves_to_dead_letter_after_retry_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试失败重试达到上限后任务会进入 dead_letter。
    settings = build_test_settings(tmp_path).model_copy(update={"ingest_failure_retry_limit": 2})  # 把失败上限收紧到 2，便于测试死信逻辑。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    def raise_runtime_error(*args: object, **kwargs: object) -> None:  # 构造固定失败函数，模拟运行期依赖故障。
        raise RuntimeError("qdrant down")

    try:  # 确保测试结束后清理依赖覆盖。
        with monkeypatch.context() as patch_ctx:  # 屏蔽创建接口内的自动投递，避免测试依赖真实 worker。
            patch_ctx.setattr(
                "backend.app.services.document_service.dispatch_ingest_job",
                lambda *args, **kwargs: None,
            )
            create_response = client.post(
                "/api/v1/documents",
                data={"tenant_id": "wl"},
                files={"file": ("manual.txt", b"valid-content", "text/plain")},
            )
        create_payload = create_response.json()  # 解析创建响应。
        monkeypatch.setattr(service.ingestion_service, "ingest_document", raise_runtime_error)  # 让入库执行固定抛错。

        first_attempt = service.run_ingest_job(create_payload["job_id"])  # 第一次失败，状态应是 failed。
        second_attempt = service.run_ingest_job(create_payload["job_id"])  # 第二次失败触达上限，状态应进 dead_letter。
        third_attempt = service.run_ingest_job(create_payload["job_id"])  # dead_letter 后再执行应直接返回，不再累加重试。
        detail_response = client.get(f"/api/v1/documents/{create_payload['doc_id']}")  # 查询文档状态确认同步失败。
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert create_response.status_code == 201  # 创建文档应成功。
    assert first_attempt.status == "failed"  # 第一次失败仍允许重试。
    assert first_attempt.retry_count == 1  # 第一次失败后重试次数应为 1。
    assert first_attempt.auto_retry_eligible is True  # 未达到上限前 failed 应允许自动重试。
    assert first_attempt.manual_retry_allowed is True  # failed 状态允许管理重投递。
    assert second_attempt.status == "dead_letter"  # 达到失败上限后应进入死信状态。
    assert second_attempt.stage == "dead_letter"  # 阶段也应同步为 dead_letter。
    assert second_attempt.retry_count == 2  # 死信时重试次数应达到设定上限。
    assert second_attempt.error_code == "INGEST_RUNTIME_ERROR_DEAD_LETTER"  # 死信应写入带后缀的错误码。
    assert second_attempt.auto_retry_eligible is False  # dead_letter 状态不应继续自动重试。
    assert second_attempt.manual_retry_allowed is True  # dead_letter 状态允许人工确认后重投递。
    assert third_attempt.status == "dead_letter"  # 再次执行死信任务应保持终态。
    assert third_attempt.retry_count == 2  # 死信终态下重试次数不应继续增加。
    assert detail_response.status_code == 200  # 文档详情接口应可用。
    assert detail_response.json()["status"] == "failed"  # 死信任务对应文档应保持 failed，避免误判可检索。


def test_queue_ingest_job_requeues_dead_letter_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试 dead_letter 任务仍可通过 run 接口作为管理重试入口重新入队。
    settings = build_test_settings(tmp_path).model_copy(update={"ingest_failure_retry_limit": 1})  # 把失败上限设为 1，快速进入 dead_letter。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    def raise_runtime_error(*args: object, **kwargs: object) -> None:  # 构造固定失败函数，模拟运行期依赖故障。
        raise RuntimeError("embedding timeout")

    try:  # 确保测试结束后清理依赖覆盖。
        with monkeypatch.context() as patch_ctx:  # 创建阶段先屏蔽自动投递，避免异步干扰。
            patch_ctx.setattr(
                "backend.app.services.document_service.dispatch_ingest_job",
                lambda *args, **kwargs: None,
            )
            create_response = client.post(
                "/api/v1/documents",
                data={"tenant_id": "wl"},
                files={"file": ("manual.txt", b"valid-content", "text/plain")},
            )
        create_payload = create_response.json()  # 解析创建响应。
        monkeypatch.setattr(service.ingestion_service, "ingest_document", raise_runtime_error)  # 强制入库失败。
        dead_letter_status = service.run_ingest_job(create_payload["job_id"])  # 一次失败后直接进 dead_letter。

        monkeypatch.setattr(  # 重新入队阶段改成成功投递，验证管理重试语义。
            "backend.app.services.document_service.dispatch_ingest_job",
            lambda *args, **kwargs: None,
        )
        requeued_status = service.queue_ingest_job(create_payload["job_id"])  # 通过管理接口重置为 queued。
        detail_response = client.get(f"/api/v1/documents/{create_payload['doc_id']}")  # 查询文档状态确认同步回 queued。
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert create_response.status_code == 201  # 创建文档应成功。
    assert dead_letter_status.status == "dead_letter"  # 任务应先进入 dead_letter。
    assert requeued_status.status == "queued"  # 管理重试后任务应回到 queued。
    assert requeued_status.stage == "queued"  # 阶段应同步重置为 queued。
    assert requeued_status.progress == 0  # 重新入队后进度应回到 0。
    assert requeued_status.retry_count == dead_letter_status.retry_count  # 重新入队不应重置历史重试计数。
    assert requeued_status.auto_retry_eligible is False  # queued 状态下自动重试判定应为 false。
    assert requeued_status.manual_retry_allowed is True  # queued 状态下允许管理重试。
    assert detail_response.status_code == 200  # 文档详情接口应可用。
    assert detail_response.json()["status"] == "queued"  # 文档状态应同步回 queued，等待下次 worker 消费。


def test_create_document_returns_502_when_dispatch_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试 broker 不可用时接口会返回 502 而不是假装 queued。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    monkeypatch.setattr(  # 把 Celery 投递函数替换成抛错版本，模拟 broker 不可用。
        "backend.app.services.document_service.dispatch_ingest_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("broker is down")),
    )

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 502  # Celery broker 不可用时应返回 502。
    assert "Failed to enqueue ingest job" in response.json()["detail"]  # 错误信息应明确指出是调度失败。

    job_files = sorted(settings.job_dir.glob("*.json"))  # 读取当前目录里唯一的 job 元数据文件。
    document_files = sorted(settings.document_dir.glob("*.json"))  # 读取当前目录里唯一的 document 元数据文件。
    assert len(job_files) == 1  # 当前测试只应生成一个 job 记录。
    assert len(document_files) == 1  # 当前测试只应生成一个 document 记录。

    job_payload = json.loads(job_files[0].read_text(encoding="utf-8"))  # 解析 job 元数据。
    document_payload = json.loads(document_files[0].read_text(encoding="utf-8"))  # 解析 document 元数据。
    assert job_payload["status"] == "failed"  # 调度失败后 job 状态应标为 failed。
    assert job_payload["error_code"] == "INGEST_DISPATCH_ERROR"  # 应写入明确的调度失败错误码。
    assert document_payload["status"] == "failed"  # 文档状态也应同步标记为 failed。


def test_create_document_dispatch_failure_moves_to_dead_letter_when_retry_limit_is_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试调度失败在上限为 1 时会直接进入 dead_letter。
    settings = build_test_settings(tmp_path).model_copy(update={"ingest_failure_retry_limit": 1})  # 把失败上限设为 1，覆盖死信边界。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    monkeypatch.setattr(  # 模拟 Celery 投递失败。
        "backend.app.services.document_service.dispatch_ingest_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("broker is down")),
    )

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 502  # 调度失败依旧返回 502。

    job_files = sorted(settings.job_dir.glob("*.json"))  # 读取任务元数据文件。
    document_files = sorted(settings.document_dir.glob("*.json"))  # 读取文档元数据文件。
    assert len(job_files) == 1  # 当前测试只应生成一个 job 记录。
    assert len(document_files) == 1  # 当前测试只应生成一个 document 记录。

    job_payload = json.loads(job_files[0].read_text(encoding="utf-8"))  # 解析 job 元数据。
    document_payload = json.loads(document_files[0].read_text(encoding="utf-8"))  # 解析 document 元数据。
    assert job_payload["status"] == "dead_letter"  # 达到失败上限后应进入 dead_letter。
    assert job_payload["stage"] == "dead_letter"  # 阶段也应同步为 dead_letter。
    assert job_payload["retry_count"] == 1  # 死信时重试计数应等于上限。
    assert job_payload["error_code"] == "INGEST_DISPATCH_ERROR_DEAD_LETTER"  # 调度失败死信应使用统一错误码。
    assert "moved to dead_letter" in (job_payload["error_message"] or "")  # 错误信息应明确标记进入死信。
    assert document_payload["status"] == "failed"  # 文档状态应保持 failed，避免误判可检索。


def test_remote_qdrant_client_ignores_proxy_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试远程 Qdrant 客户端会禁用系统代理。
    settings = build_test_settings(tmp_path).model_copy(update={"qdrant_url": "http://localhost:6333"})  # 使用远程 URL 模式触发对应客户端分支。
    captured_kwargs: dict[str, object] = {}  # 保存构造函数收到的关键字参数，后面用于断言。

    def fake_qdrant_client(*args: object, **kwargs: object) -> object:  # 构造一个假的 QdrantClient，避免测试真的连外部服务。
        captured_kwargs.update(kwargs)  # 记录调用参数。

        class DummyClient:  # 只需要一个占位对象供 store.client 返回。
            pass

        return DummyClient()

    QdrantVectorStore._CLIENT_CACHE.clear()  # 清空类级缓存，避免拿到之前构造过的真实客户端。
    monkeypatch.setattr("backend.app.rag.vectorstores.qdrant_store.QdrantClient", fake_qdrant_client)  # 把 QdrantClient 替换成测试桩。

    store = QdrantVectorStore(settings)  # 创建待测向量存储实例。
    _ = store.client  # 触发客户端构造。

    assert captured_kwargs["url"] == "http://localhost:6333"  # 远程模式应把 URL 原样传给客户端。
    assert captured_kwargs["trust_env"] is False  # 必须禁用系统代理，避免本机代理污染内网互调。


def test_qdrant_client_cache_is_thread_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试类级客户端缓存在并发下只会构建一次。
    settings = build_test_settings(tmp_path).model_copy(update={"qdrant_url": str(tmp_path / "qdrant_db")})  # 使用本地路径模式触发类级缓存分支。
    store = QdrantVectorStore(settings)  # 创建待测存储实例。
    sentinel_client = object()  # 定义一个哨兵对象，便于断言所有线程拿到的是同一实例。
    build_count = 0  # 统计 _build_client 实际被调用次数。
    counter_lock = threading.Lock()  # 保护 build_count 累计，避免测试自身出现数据竞争。

    def fake_build_client(self: QdrantVectorStore) -> object:  # 构造假客户端构建函数，制造并发竞争窗口。
        nonlocal build_count
        time.sleep(0.02)  # 人工拉长构建时间，放大并发竞态触发概率。
        with counter_lock:
            build_count += 1  # 记录构建次数。
        return sentinel_client  # 返回固定对象，便于后续判定是否复用。

    QdrantVectorStore._CLIENT_CACHE.clear()  # 清空全局缓存，避免被其他测试污染。
    monkeypatch.setattr(QdrantVectorStore, "_build_client", fake_build_client)  # 把客户端构建逻辑替换成测试桩。

    results: list[object] = []  # 存放每个线程拿到的客户端对象。
    errors: list[Exception] = []  # 记录线程内部异常，避免异常被吞掉。

    def _worker() -> None:  # 线程执行函数：并发获取客户端。
        try:
            results.append(store._get_or_build_client())
        except Exception as exc:  # pragma: no cover - 仅用于把线程异常回传主线程断言。
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(8)]  # 启动多个线程并发访问缓存。
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors  # 并发访问不应抛出异常。
    assert len(results) == 8  # 每个线程都应拿到一个结果。
    assert all(client is sentinel_client for client in results)  # 所有线程都应拿到同一客户端实例。
    assert build_count == 1  # 无论并发多少次，底层只允许构建一次客户端。


def test_read_upload_content_reads_in_chunks_and_fails_fast_on_limit(tmp_path: Path) -> None:  # 测试上传读取使用分块 read，并在超限时提前中断。
    settings = build_test_settings(tmp_path).model_copy(update={"upload_max_file_size_bytes": 8})  # 把上限降到 8 字节，便于构造超限场景。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建待测服务实例。

    class FakeChunkedUpload:  # 构造一个最小 UploadFile 桩对象。
        def __init__(self) -> None:
            self.filename = "manual.txt"  # 提供合法扩展名，保证测试焦点在读取逻辑而非格式校验。
            self._chunks = [b"1234", b"5678", b"9"]  # 分三段返回数据，第三段将触发超限。
            self.read_sizes: list[int] = []  # 记录每次 read(size) 的 size 参数。

        async def read(self, size: int = -1) -> bytes:
            self.read_sizes.append(size)  # 记录读取参数，后续断言是否用了分块读取。
            if size <= 0:  # 老逻辑调用 read() 不传 size 时会落到这里，测试应直接失败。
                raise AssertionError("upload.read() must be called with a positive chunk size.")
            if not self._chunks:  # 模拟 EOF。
                return b""
            return self._chunks.pop(0)  # 每次返回一段固定分块内容。

    upload = FakeChunkedUpload()  # 创建上传桩对象。
    with pytest.raises(HTTPException) as exc_info:  # 超限时应抛出 413。
        asyncio.run(service._read_upload_content(upload))

    assert exc_info.value.status_code == 413  # 超过限制应返回 413。
    assert upload.read_sizes[:2] == [UPLOAD_READ_CHUNK_SIZE_BYTES, UPLOAD_READ_CHUNK_SIZE_BYTES]  # 前两次读取应使用固定分块大小。


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


def test_create_document_supports_docx_ingestion_and_text_preview(tmp_path: Path) -> None:  # DOCX 队列化上传应能完成入库，并以文本方式预览正文。
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    service = DocumentService(settings)

    app.dependency_overrides[get_document_service] = lambda: service
    client = TestClient(app)
    docx_bytes = build_minimal_docx_bytes(
        "数字化部系统巡检标准作业程序",
        "步骤一：检查任务调度服务状态。",
        "步骤二：核对数据库与消息队列连接。",
    )

    try:
        response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={
                "file": (
                    "digitalization_sop.docx",
                    docx_bytes,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert response.status_code == 201
        payload = response.json()
        ingest_status = service.run_ingest_job(payload["job_id"])
        preview_response = client.get(f"/api/v1/documents/{payload['doc_id']}/preview")
    finally:
        app.dependency_overrides.clear()

    assert payload["status"] == "queued"
    assert payload["doc_id"].startswith("doc_")
    assert payload["job_id"].startswith("job_")
    assert ingest_status.status == "completed"
    parsed_path = settings.parsed_dir / f"{payload['doc_id']}.txt"
    chunk_path = settings.chunk_dir / f"{payload['doc_id']}.json"
    assert parsed_path.exists()
    assert chunk_path.exists()
    assert "步骤一：检查任务调度服务状态。" in parsed_path.read_text(encoding="utf-8")

    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["doc_id"] == payload["doc_id"]
    assert preview_payload["preview_type"] == "text"
    assert preview_payload["content_type"].startswith("text/plain")
    assert "数字化部系统巡检标准作业程序" in (preview_payload["text_content"] or "")
    assert "步骤二：核对数据库与消息队列连接。" in (preview_payload["text_content"] or "")


def test_upload_rejects_unsupported_extension(tmp_path: Path) -> None:  # 测试系统会拒绝不支持的文件扩展名。
    settings = build_test_settings(tmp_path)  # 构造这次测试用到的配置。
    ensure_data_directories(settings)  # 提前创建测试需要的目录结构。
    service = DocumentService(settings)  # 用测试配置创建上传服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖默认依赖，让接口走测试服务。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 用 try/finally 确保测试结束后能恢复依赖状态。
        response = client.post(  # 对上传接口发起一次上传请求。
            "/api/v1/documents/upload",  # 指定上传接口地址。
            files={"file": ("manual.exe", b"fake-binary", "application/octet-stream")},  # 上传一个当前系统不支持解析的文件类型。
        )  # 完成接口调用。
    finally:  # 不管接口是否报错，都执行清理逻辑。
        app.dependency_overrides.clear()  # 清空依赖覆盖，避免污染其他测试。

    assert response.status_code == 400  # 断言不支持的扩展名会返回 400 Bad Request。
    assert "Unsupported file type" in response.json()["detail"]  # 断言错误信息里明确说明了文件类型不被支持。


def test_create_document_rejects_unsupported_extension(tmp_path: Path) -> None:  # 测试队列化上传接口会拒绝不支持的扩展名。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(  # 调用队列化上传接口。
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={
                "file": (
                    "manual.exe",
                    b"fake-binary",
                    "application/octet-stream",
                )
            },
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 400  # 不支持的扩展名应返回 400。
    assert "Unsupported file type" in response.json()["detail"]  # 错误信息应明确指出文件类型不支持。


def test_create_document_rejects_empty_file(tmp_path: Path) -> None:  # 测试队列化上传接口会拒绝空文件。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(  # 调用队列化上传接口。
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 400  # 空文件应返回 400。
    assert response.json()["detail"] == "Uploaded file is empty."  # 错误信息应明确指出文件为空。


def test_create_document_requires_tenant_id(tmp_path: Path) -> None:  # 测试队列化上传接口缺少 tenant_id 时会返回 422。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(  # 调用队列化上传接口，但故意不传 tenant_id。
            "/api/v1/documents",
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 422  # 缺少必填字段应返回 422。
    assert any(error["loc"][-1] == "tenant_id" for error in response.json()["detail"])  # 返回的校验错误里应包含 tenant_id。


@pytest.mark.parametrize(  # 参数化测试非法枚举值，避免写两份重复逻辑。
    ("field_name", "field_value"),
    [
        ("visibility", "restricted"),
        ("classification", "top_secret"),
    ],
)
def test_create_document_rejects_invalid_enum_value(tmp_path: Path, field_name: str, field_value: str) -> None:  # 测试非法 ACL/密级值会被接口校验拒绝。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(  # 调用队列化上传接口，并传入非法枚举值。
            "/api/v1/documents",
            data={
                "tenant_id": "wl",
                field_name: field_value,
            },
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 422  # 非法枚举值应返回 422。
    assert any(error["loc"][-1] == field_name for error in response.json()["detail"])  # 校验错误里应指向对应字段。


class _FakeMetadataStore:  # 构造一个最小 metadata store 桩对象，验证 PostgreSQL 路径分支逻辑。
    def __init__(self) -> None:
        self.documents: dict[str, DocumentRecord] = {}
        self.jobs: dict[str, IngestJobRecord] = {}
        self.load_job_statuses_call_count = 0

    def save_document(self, record: DocumentRecord) -> None:
        self.documents[record.doc_id] = record

    def save_job(self, record: IngestJobRecord) -> None:
        self.jobs[record.job_id] = record

    def load_document(self, doc_id: str) -> DocumentRecord | None:
        return self.documents.get(doc_id)

    def load_job(self, job_id: str) -> IngestJobRecord | None:
        return self.jobs.get(job_id)

    def load_job_statuses(self, job_ids: list[str]) -> dict[str, str]:
        self.load_job_statuses_call_count += 1
        return {
            job_id: record.status
            for job_id in job_ids
            for record in ([self.jobs.get(job_id)] if job_id else [])
            if record is not None
        }

    def list_documents(self) -> list[DocumentRecord]:
        return list(self.documents.values())

    def find_document_by_file_hash(self, file_hash: str, *, tenant_id: str | None = None) -> DocumentRecord | None:
        for record in self.documents.values():
            if tenant_id is not None and record.tenant_id != tenant_id:
                continue
            if record.file_hash == file_hash:
                return record
        return None


def test_create_document_uses_metadata_store_instead_of_json_files(tmp_path: Path) -> None:  # 验证 metadata store 启用后，不再依赖本地 JSON 元数据文件。
    settings = build_test_settings(tmp_path)  # 构造测试配置，默认关闭 PostgreSQL 开关。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。
    fake_store = _FakeMetadataStore()  # 构造内存版 metadata store。
    service.metadata_store = fake_store  # 强制注入 store，模拟 PostgreSQL 存储分支。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。
    try:
        create_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
        payload = create_response.json()
        detail_response = client.get(f"/api/v1/documents/{payload['doc_id']}")
        job_response = client.get(f"/api/v1/ingest/jobs/{payload['job_id']}")
    finally:
        app.dependency_overrides.clear()

    assert create_response.status_code == 201  # 创建应成功。
    assert detail_response.status_code == 200  # 详情应可读。
    assert job_response.status_code == 200  # job 状态应可读。
    assert len(fake_store.documents) == 1  # document 记录应写入 metadata store。
    assert len(fake_store.jobs) == 1  # job 记录应写入 metadata store。
    assert not list(settings.document_dir.glob("*.json"))  # document 元数据目录不应写入 JSON。
    assert not list(settings.job_dir.glob("*.json"))  # job 元数据目录不应写入 JSON。


def test_duplicate_file_hash_detection_uses_metadata_store(tmp_path: Path) -> None:  # 验证重复内容查重在 metadata store 模式下依旧生效。
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    service = DocumentService(settings)
    service.metadata_store = _FakeMetadataStore()  # 模拟 PostgreSQL 元数据存储分支。

    app.dependency_overrides[get_document_service] = lambda: service
    client = TestClient(app)
    try:
        first_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"same-content", "text/plain")},
        )
        second_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"same-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()

    assert first_response.status_code == 201
    assert second_response.status_code == 201  # 第二次应走覆盖逻辑并补发新任务。
    first_payload = first_response.json()
    second_payload = second_response.json()
    assert second_payload["doc_id"] == first_payload["doc_id"]
    assert second_payload["job_id"] == first_payload["job_id"]  # in-flight 状态下复用已有 job。
    assert len(service.metadata_store.documents) == 1
    assert len(service.metadata_store.jobs) == 1


def test_list_documents_uses_batch_job_status_lookup_with_metadata_store(tmp_path: Path) -> None:  # 验证 PostgreSQL metadata store 模式下，列表接口批量读取 latest job 状态而不是逐条查 job。
    settings = build_test_settings(tmp_path)
    ensure_data_directories(settings)
    service = DocumentService(settings)
    fake_store = _FakeMetadataStore()
    service.metadata_store = fake_store

    now = datetime.now(timezone.utc)
    fake_store.save_document(
        DocumentRecord(
            doc_id="doc_1",
            tenant_id="wl",
            file_name="doc-1.txt",
            file_hash="hash-1",
            source_type="txt",
            department_id=None,
            department_ids=[],
            category_id=None,
            role_ids=[],
            owner_id=None,
            visibility="private",
            classification="internal",
            tags=[],
            source_system=None,
            status="active",
            current_version=1,
            latest_job_id="job_1",
            storage_path=str(settings.upload_dir / "doc_1__doc-1.txt"),
            uploaded_by="tester",
            created_by="tester",
            created_at=now,
            updated_at=now,
        )
    )
    fake_store.save_document(
        DocumentRecord(
            doc_id="doc_2",
            tenant_id="wl",
            file_name="doc-2.txt",
            file_hash="hash-2",
            source_type="txt",
            department_id=None,
            department_ids=[],
            category_id=None,
            role_ids=[],
            owner_id=None,
            visibility="private",
            classification="internal",
            tags=[],
            source_system=None,
            status="failed",
            current_version=1,
            latest_job_id="job_2",
            storage_path=str(settings.upload_dir / "doc_2__doc-2.txt"),
            uploaded_by="tester",
            created_by="tester",
            created_at=now,
            updated_at=now,
        )
    )
    fake_store.save_job(
        IngestJobRecord(
            job_id="job_1",
            doc_id="doc_1",
            version=1,
            file_name="doc-1.txt",
            status="completed",
            stage="completed",
            progress=100,
            retry_count=0,
            error_code=None,
            error_message=None,
            created_at=now,
            updated_at=now,
        )
    )
    fake_store.save_job(
        IngestJobRecord(
            job_id="job_2",
            doc_id="doc_2",
            version=1,
            file_name="doc-2.txt",
            status="dead_letter",
            stage="dead_letter",
            progress=100,
            retry_count=3,
            error_code="INGEST_RUNTIME_ERROR_DEAD_LETTER",
            error_message="timeout",
            created_at=now,
            updated_at=now,
        )
    )

    response = service.list_documents(page=1, page_size=10)

    assert fake_store.load_job_statuses_call_count == 1
    assert response.total == 2
    assert {item.document_id: item.ingest_status for item in response.items} == {
        "doc_1": "completed",
        "doc_2": "dead_letter",
    }
