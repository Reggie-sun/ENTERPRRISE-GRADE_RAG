from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.rag.generators.client import LLMGenerationRetryableError
from backend.app.schemas.retrieval import RetrievalResponse, RetrievedChunk
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.identity_service import get_identity_service
from backend.app.services.sop_generation_service import SopGenerationService, get_sop_generation_service
from backend.tests.test_sop_generation_service import _FakeDocumentService, _FakeRetrievalService, _build_identity_service


class _FakeRerankerClient:
    def rerank(self, *, query: str, candidates: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:
        return candidates[:top_n]


class _FakeGenerationClient:
    def __init__(self, *, answer: str | None = None, retryable_error: bool = False) -> None:
        self.answer = answer or "生成的 SOP 草稿"
        self.retryable_error = retryable_error

    def generate(
        self,
        *,
        question: str,
        contexts: list[str],
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:
        if self.retryable_error:
            raise LLMGenerationRetryableError("temporary llm issue")
        return self.answer


def _build_client(tmp_path: Path) -> TestClient:
    identity_service = _build_identity_service(tmp_path)
    auth_service = AuthService(identity_service=identity_service)
    sop_generation_service = SopGenerationService(
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
                ),
                RetrievedChunk(
                    chunk_id="chunk_2",
                    document_id="doc_assembly",
                    document_name="装配报警手册",
                    text="装配设备报警时先检查急停与气源。",
                    score=0.88,
                    source_path="/tmp/assembly.txt",
                ),
            ]
        ),
        document_service=_FakeDocumentService(
            {
                "doc_digitalization": "dept_digitalization",
                "doc_assembly": "dept_assembly",
            }
        ),
        reranker_client=_FakeRerankerClient(),
        generation_client=_FakeGenerationClient(answer="这是生成后的 SOP 草稿。"),
    )

    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_sop_generation_service] = lambda: sop_generation_service
    return TestClient(app)


def _login_headers(client: TestClient, *, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_generate_sop_by_scenario_endpoint_returns_draft_for_department_admin(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    try:
        headers = _login_headers(
            client,
            username="digitalization.admin",
            password="digitalization-admin-pass",
        )
        response = client.post(
            "/api/v1/sops/generate/scenario",
            json={"scenario_name": "日常运维", "process_name": "巡检", "top_k": 3},
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_mode"] == "scenario"
    assert payload["department_id"] == "dept_digitalization"
    assert payload["content"] == "这是生成后的 SOP 草稿。"
    assert [item["document_id"] for item in payload["citations"]] == ["doc_digitalization"]


def test_generate_sop_by_topic_endpoint_allows_employee_in_own_department(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    try:
        headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        response = client.post(
            "/api/v1/sops/generate/topic",
            json={"topic": "值班交接"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_mode"] == "topic"
    assert payload["department_id"] == "dept_digitalization"
    assert payload["content"] == "这是生成后的 SOP 草稿。"
    assert [item["document_id"] for item in payload["citations"]] == ["doc_digitalization"]


def test_generate_sop_by_document_endpoint_returns_draft_for_department_admin(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    try:
        headers = _login_headers(
            client,
            username="digitalization.admin",
            password="digitalization-admin-pass",
        )
        response = client.post(
            "/api/v1/sops/generate/document",
            json={"document_id": "doc_digitalization", "top_k": 4},
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_mode"] == "document"
    assert payload["department_id"] == "dept_digitalization"
    assert payload["content"] == "这是生成后的 SOP 草稿。"
    assert payload["topic"] == "doc_digitalization"
    assert [item["document_id"] for item in payload["citations"]] == ["doc_digitalization"]


def test_generate_sop_by_document_endpoint_uses_document_preview_fallback_when_retrieval_empty(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    auth_service = AuthService(identity_service=identity_service)
    sop_generation_service = SopGenerationService(
        identity_service=identity_service,
        retrieval_service=_FakeRetrievalService([]),
        document_service=_FakeDocumentService(
            {"doc_digitalization": "dept_digitalization"},
            {"doc_digitalization": "数字化巡检手册.docx"},
            {"doc_digitalization": "巡检前先检查任务调度服务。\n\n异常时记录时间和影响范围。"},
        ),
        reranker_client=_FakeRerankerClient(),
        generation_client=_FakeGenerationClient(answer="这是基于预览回退生成的 SOP 草稿。"),
    )

    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_sop_generation_service] = lambda: sop_generation_service
    client = TestClient(app)

    try:
        headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        response = client.post(
            "/api/v1/sops/generate/document",
            json={"document_id": "doc_digitalization"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["content"] == "这是基于预览回退生成的 SOP 草稿。"
    assert payload["citations"][0]["chunk_id"] == "doc_digitalization-preview-0"


def test_generate_sop_by_topic_endpoint_requires_authentication(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    try:
        response = client.post(
            "/api/v1/sops/generate/topic",
            json={"topic": "值班交接"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication credentials were not provided."
