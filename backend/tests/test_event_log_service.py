from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.core.config import Settings, ensure_data_directories
from backend.app.main import app
from backend.app.schemas.retrieval import RetrievedChunk
from backend.app.schemas.sop_generation import SopGenerateByDocumentRequest
from backend.app.services.chat_service import ChatService, get_chat_service
from backend.app.services.document_service import DocumentService, get_document_service
from backend.app.services.event_log_service import EventLogService
from backend.app.services.retrieval_service import RetrievalService, get_retrieval_service
from backend.app.services.sop_generation_service import SopGenerationService
from backend.tests.test_sop_generation_service import (
    _FakeDocumentService,
    _FakeGenerationClient,
    _FakeRetrievalService,
    _FakeRerankerClient,
    _build_auth_context,
    _build_identity_service,
)


def _build_settings(tmp_path: Path, **overrides) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        _env_file=None,
        app_env="test",
        debug=True,
        qdrant_url=str(tmp_path / "qdrant_db"),
        qdrant_collection="enterprise_rag_v1_event_log_test",
        postgres_metadata_enabled=False,
        postgres_metadata_dsn=None,
        celery_broker_url="memory://",
        celery_result_backend="cache+memory://",
        llm_provider="mock",
        llm_base_url="http://llm.test/v1",
        llm_model="Qwen/Qwen2.5-7B-Instruct",
        embedding_provider="mock",
        embedding_base_url="http://embedding.test",
        embedding_model="BAAI/bge-m3",
        data_dir=data_dir,
        upload_dir=data_dir / "uploads",
        parsed_dir=data_dir / "parsed",
        chunk_dir=data_dir / "chunks",
        document_dir=data_dir / "documents",
        job_dir=data_dir / "jobs",
        event_log_dir=data_dir / "event_logs",
        **overrides,
    )


def test_event_log_service_appends_and_lists_recent(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    service = EventLogService(settings)

    service.record(
        category="document",
        action="create",
        outcome="success",
        target_type="document",
        target_id="doc_001",
        duration_ms=12,
        details={"file_name": "manual.txt"},
    )
    service.record(
        category="chat",
        action="answer",
        outcome="failed",
        duration_ms=34,
        details={"error_message": "forced"},
    )

    all_records = service.list_recent(limit=10)
    chat_records = service.list_recent(category="chat", limit=10)

    assert len(all_records) == 2
    assert all_records[0].event_id != all_records[1].event_id
    assert chat_records[0].category == "chat"
    assert chat_records[0].details["error_message"] == "forced"


def test_chat_ask_endpoint_writes_event_log(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    event_log_service = EventLogService(settings)
    document_service = DocumentService(settings, event_log_service=event_log_service)
    retrieval_service = RetrievalService(settings)
    chat_service = ChatService(settings, event_log_service=event_log_service)
    chat_service.retrieval_service = retrieval_service

    app.dependency_overrides[get_document_service] = lambda: document_service
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service
    app.dependency_overrides[get_chat_service] = lambda: chat_service
    client = TestClient(app)

    try:
        upload_response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("chat_log.txt", "Alarm E205 check fan speed sensor.".encode("utf-8"), "text/plain")},
        )
        chat_response = client.post(
            "/api/v1/chat/ask",
            json={"question": "How to handle alarm E205?", "mode": "fast", "top_k": 3},
        )
    finally:
        app.dependency_overrides.clear()

    assert upload_response.status_code == 201
    assert chat_response.status_code == 200
    records = event_log_service.list_recent(category="chat", limit=5)
    assert len(records) == 1
    assert records[0].action == "answer"
    assert records[0].outcome == "success"
    assert records[0].mode == "fast"
    assert records[0].details["response_mode"] == "rag"
    assert records[0].details["citation_count"] >= 1


def test_document_create_and_delete_write_event_logs(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    event_log_service = EventLogService(settings)
    document_service = DocumentService(settings, event_log_service=event_log_service)

    app.dependency_overrides[get_document_service] = lambda: document_service
    client = TestClient(app)

    try:
        create_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("event_log_doc.txt", "Document event logging content.".encode("utf-8"), "text/plain")},
        )
        assert create_response.status_code == 201
        doc_id = create_response.json()["doc_id"]

        delete_response = client.delete(f"/api/v1/documents/{doc_id}")
    finally:
        app.dependency_overrides.clear()

    assert delete_response.status_code == 200
    records = event_log_service.list_recent(category="document", limit=10)
    actions = [record.action for record in records]
    assert "create" in actions
    assert "delete" in actions
    delete_record = next(record for record in records if record.action == "delete")
    assert delete_record.target_id == doc_id
    assert delete_record.outcome == "success"


def test_sop_generation_logs_success_and_failure(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.employee",
        password="digitalization-employee-pass",
    )
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    event_log_service = EventLogService(settings)

    service = SopGenerationService(
        settings,
        identity_service=identity_service,
        retrieval_service=_FakeRetrievalService(
            [
                RetrievedChunk(
                    chunk_id="chunk_1",
                    document_id="doc_digitalization",
                    document_name="数字化巡检手册",
                    text="巡检前先检查任务调度服务和数据库连接。",
                    score=0.91,
                    source_path="/tmp/digitalization.txt",
                )
            ]
        ),
        document_service=_FakeDocumentService({"doc_digitalization": "dept_digitalization"}),
        reranker_client=_FakeRerankerClient(),
        generation_client=_FakeGenerationClient(answer="生成成功"),
        event_log_service=event_log_service,
    )

    response = service.generate_from_document(
        SopGenerateByDocumentRequest(document_id="doc_digitalization"),
        auth_context=auth_context,
    )
    assert response.content == "生成成功"

    failed_service = SopGenerationService(
        settings,
        identity_service=identity_service,
        retrieval_service=_FakeRetrievalService([]),
        document_service=_FakeDocumentService({"doc_digitalization": "dept_digitalization"}),
        reranker_client=_FakeRerankerClient(),
        generation_client=_FakeGenerationClient(answer="不会用到"),
        event_log_service=event_log_service,
    )

    with pytest.raises(HTTPException):
        failed_service.generate_from_document(
            SopGenerateByDocumentRequest(document_id="doc_digitalization"),
            auth_context=auth_context,
        )

    records = event_log_service.list_recent(category="sop_generation", limit=10)
    assert len(records) == 2
    assert records[0].outcome == "failed"
    assert records[1].outcome == "success"
    assert records[1].action == "generate_document"
