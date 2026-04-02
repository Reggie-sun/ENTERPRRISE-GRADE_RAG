"""
V1 主链路烟测 — 守住 MAIN_CONTRACT_MATRIX.md 中的关键契约面。

覆盖：
1. 上传文档 → 入库任务创建（document_id / doc_id / job_id / status 骨架稳定）
2. 检索接口返回结构稳定（query / top_k / mode / results 骨架）
3. 问答接口返回 answer + citations 等主骨架字段稳定
4. 权限回归：跨部门访问限制（检索 + 问答 403）
5. 流式问答 SSE 事件骨架稳定

原则：守住主契约，不追求全量覆盖。
"""

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend.app.core.config import Settings, ensure_data_directories
from backend.app.main import app
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.chat_service import ChatService, get_chat_service
from backend.app.services.document_service import DocumentService, get_document_service
from backend.app.services.identity_service import IdentityService, get_identity_service
from backend.app.services.retrieval_service import RetrievalService, get_retrieval_service
from backend.tests.test_document_ingestion import build_test_settings as build_document_settings
from backend.tests.test_retrieval_chat import build_test_settings as build_retrieval_settings
from backend.tests.test_retrieval_chat import parse_sse_events
from backend.tests.test_sop_generation_service import _build_identity_service as _build_default_identity_service


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _assert_contains_keys(payload: dict, required: set[str]) -> None:
    missing = required - set(payload.keys())
    assert not missing, f"Missing stable contract keys: {missing}"


def _login_headers(client: TestClient, *, username: str, password: str) -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _build_authenticated_client(
    tmp_path: Path,
    settings: Settings,
    *,
    username: str = "sys.admin",
    password: str = "sys-admin-pass",
) -> TestClient:
    identity_service = _build_default_identity_service(tmp_path)
    settings.identity_bootstrap_path = identity_service.settings.identity_bootstrap_path
    auth_service = AuthService(settings, identity_service=identity_service)
    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    client = TestClient(app)
    client.headers.update(_login_headers(client, username=username, password=password))
    return client


def _build_authz_env(tmp_path: Path):
    """构造带认证的测试环境，返回 (client, identity_service)。"""
    bootstrap_path = tmp_path / "identity_bootstrap.json"
    import json

    bootstrap_path.write_text(
        json.dumps(
            {
                "roles": [
                    {"role_id": "employee", "name": "Employee", "description": "Reader", "data_scope": "department", "is_admin": False},
                    {"role_id": "department_admin", "name": "DeptAdmin", "description": "Dept manager", "data_scope": "department", "is_admin": True},
                    {"role_id": "sys_admin", "name": "SysAdmin", "description": "Global", "data_scope": "global", "is_admin": True},
                ],
                "departments": [
                    {"department_id": "dept_after_sales", "tenant_id": "wl", "department_name": "After Sales", "parent_department_id": None, "is_active": True},
                    {"department_id": "dept_assembly", "tenant_id": "wl", "department_name": "Assembly", "parent_department_id": None, "is_active": True},
                ],
                "users": [
                    {
                        "user_id": "user_emp_aftersales",
                        "tenant_id": "wl",
                        "username": "emp.aftersales",
                        "display_name": "Employee AfterSales",
                        "department_id": "dept_after_sales",
                        "role_id": "employee",
                        "is_active": True,
                        "password_hash": AuthService.hash_password("emp-pass", salt=bytes.fromhex("aa112233445566778899aabbccddeeff")),
                    },
                    {
                        "user_id": "user_sysadmin",
                        "tenant_id": "wl",
                        "username": "sys.admin.smoke",
                        "display_name": "SysAdmin Smoke",
                        "department_id": "dept_after_sales",
                        "role_id": "sys_admin",
                        "is_active": True,
                        "password_hash": AuthService.hash_password("sysadmin-pass", salt=bytes.fromhex("bb112233445566778899aabbccddeeff")),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    identity_service = IdentityService(Settings(_env_file=None, identity_bootstrap_path=bootstrap_path))
    settings = Settings(
        _env_file=None,
        app_env="test",
        debug=True,
        identity_bootstrap_path=bootstrap_path,
        auth_token_secret="smoke-test-secret",
        auth_token_issuer="smoke-test-issuer",
        auth_token_expire_minutes=60,
        qdrant_url=":memory:",
        qdrant_collection="enterprise_rag_smoke_test",
        postgres_metadata_enabled=False,
        postgres_metadata_dsn=None,
        database_url=None,
        celery_broker_url="memory://",
        celery_result_backend="cache+memory://",
        celery_task_always_eager=True,
        celery_task_eager_propagates=True,
        llm_provider="mock",
        llm_base_url="http://llm.test/v1",
        llm_model="Qwen/Qwen2.5-7B-Instruct",
        reranker_provider="heuristic",
        embedding_provider="mock",
        embedding_base_url="http://embedding.test",
        embedding_model="BAAI/bge-m3",
        ollama_base_url="http://embedding.test",
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "data" / "uploads",
        parsed_dir=tmp_path / "data" / "parsed",
        chunk_dir=tmp_path / "data" / "chunks",
        document_dir=tmp_path / "data" / "documents",
        job_dir=tmp_path / "data" / "jobs",
        department_query_isolation_enabled=True,
    )
    ensure_data_directories(settings)

    auth_service = AuthService(settings, identity_service=identity_service)
    document_service = DocumentService(settings)
    retrieval_service = RetrievalService(settings, document_service=document_service)
    chat_service = ChatService(settings)
    chat_service.retrieval_service = retrieval_service

    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_document_service] = lambda: document_service
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service
    app.dependency_overrides[get_chat_service] = lambda: chat_service
    client = TestClient(app)

    return client


def _teardown():
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. 上传文档 → 入库任务创建
# ---------------------------------------------------------------------------

class TestUploadAndIngestContract:
    """POST /api/v1/documents 返回 document_id + doc_id + job_id + status 骨架稳定。"""

    def test_upload_returns_stable_contract_shape(self, tmp_path: Path) -> None:
        settings = build_document_settings(tmp_path)
        ensure_data_directories(settings)
        document_service = DocumentService(settings)
        app.dependency_overrides[get_document_service] = lambda: document_service
        client = _build_authenticated_client(tmp_path, settings)

        try:
            resp = client.post(
                "/api/v1/documents",
                data={"tenant_id": "wl", "created_by": "u_smoke"},
                files={"file": ("smoke_test.txt", b"Smoke test document for E102 alarm.", "text/plain")},
            )
        finally:
            _teardown()

        assert resp.status_code == 201
        payload = resp.json()
        # Matrix §2: POST /api/v1/documents 稳定字段
        _assert_contains_keys(payload, {"document_id", "doc_id", "job_id", "status"})
        # 过渡期双字段必须相等
        assert payload["document_id"] == payload["doc_id"]
        assert payload["status"] in ("queued", "completed")

    def test_ingest_job_returns_stable_contract_shape(self, tmp_path: Path) -> None:
        settings = build_document_settings(tmp_path)
        ensure_data_directories(settings)
        document_service = DocumentService(settings)
        app.dependency_overrides[get_document_service] = lambda: document_service
        client = _build_authenticated_client(tmp_path, settings)

        try:
            create_resp = client.post(
                "/api/v1/documents",
                data={"tenant_id": "wl", "created_by": "u_smoke"},
                files={"file": ("job_shape.txt", b"Job shape smoke test.", "text/plain")},
            )
            assert create_resp.status_code == 201
            job_id = create_resp.json()["job_id"]

            job_resp = client.get(f"/api/v1/ingest/jobs/{job_id}")
        finally:
            _teardown()

        assert job_resp.status_code == 200
        # Matrix §2: GET /api/v1/ingest/jobs/{job_id} 稳定字段
        _assert_contains_keys(
            job_resp.json(),
            {
                "job_id", "document_id", "doc_id", "status", "progress", "stage",
                "retry_count", "max_retry_limit", "auto_retry_eligible",
                "manual_retry_allowed", "error_code", "error_message",
                "created_at", "updated_at",
            },
        )


# ---------------------------------------------------------------------------
# 2. 检索接口返回结果结构稳定
# ---------------------------------------------------------------------------

class TestRetrievalContract:
    """POST /api/v1/retrieval/search 返回 query / top_k / mode / results 骨架稳定。"""

    def test_search_returns_stable_contract_shape(self, tmp_path: Path) -> None:
        settings = build_retrieval_settings(tmp_path)
        ensure_data_directories(settings)
        document_service = DocumentService(settings)
        retrieval_service = RetrievalService(settings)
        app.dependency_overrides[get_document_service] = lambda: document_service
        app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service
        client = _build_authenticated_client(tmp_path, settings)

        try:
            # 先上传文档确保有数据
            upload_resp = client.post(
                "/api/v1/documents/upload",
                files={"file": ("retrieval_smoke.txt", b"CPPS smoke retrieval test content.", "text/plain")},
            )
            assert upload_resp.status_code == 201

            search_resp = client.post(
                "/api/v1/retrieval/search",
                json={"query": "CPPS smoke", "top_k": 3},
            )
        finally:
            _teardown()

        assert search_resp.status_code == 200
        payload = search_resp.json()
        # Matrix §3: POST /api/v1/retrieval/search 稳定响应字段
        _assert_contains_keys(payload, {"query", "top_k", "mode", "results"})
        assert payload["results"], "检索结果不应为空"
        # Matrix §3: results[] 稳定字段
        _assert_contains_keys(
            payload["results"][0],
            {
                "chunk_id", "document_id", "document_name", "text",
                "score", "source_path", "retrieval_strategy",
                "ocr_used", "parser_name", "page_no",
            },
        )


# ---------------------------------------------------------------------------
# 3. 问答接口返回 answer + citations 等主骨架字段稳定
# ---------------------------------------------------------------------------

class TestChatContract:
    """POST /api/v1/chat/ask 返回 question / answer / mode / model / citations 骨架稳定。"""

    def test_ask_returns_stable_contract_shape(self, tmp_path: Path) -> None:
        settings = build_retrieval_settings(tmp_path)
        ensure_data_directories(settings)
        document_service = DocumentService(settings)
        retrieval_service = RetrievalService(settings)
        chat_service = ChatService(settings)
        app.dependency_overrides[get_document_service] = lambda: document_service
        app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service
        app.dependency_overrides[get_chat_service] = lambda: chat_service
        client = _build_authenticated_client(tmp_path, settings)

        try:
            upload_resp = client.post(
                "/api/v1/documents/upload",
                files={"file": ("chat_smoke.txt", b"Alarm E102 smoke test handling guide.", "text/plain")},
            )
            assert upload_resp.status_code == 201

            chat_resp = client.post(
                "/api/v1/chat/ask",
                json={"question": "How to handle alarm E102?", "top_k": 3},
            )
        finally:
            _teardown()

        assert chat_resp.status_code == 200
        payload = chat_resp.json()
        # Matrix §3: POST /api/v1/chat/ask 稳定响应字段
        _assert_contains_keys(payload, {"question", "answer", "mode", "model", "citations"})
        assert payload["answer"], "answer 不应为空"
        assert payload["citations"], "citations 不应为空"
        # Matrix §3: citations[] 稳定字段
        _assert_contains_keys(
            payload["citations"][0],
            {
                "chunk_id", "document_id", "document_name", "snippet",
                "score", "source_path", "retrieval_strategy",
                "ocr_used", "parser_name", "page_no",
            },
        )

    def test_stream_returns_stable_sse_events(self, tmp_path: Path) -> None:
        """POST /api/v1/chat/ask/stream SSE 事件骨架：meta / answer_delta / done 稳定。"""
        settings = build_retrieval_settings(tmp_path)
        ensure_data_directories(settings)
        document_service = DocumentService(settings)
        retrieval_service = RetrievalService(settings)
        chat_service = ChatService(settings)
        app.dependency_overrides[get_document_service] = lambda: document_service
        app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service
        app.dependency_overrides[get_chat_service] = lambda: chat_service
        client = _build_authenticated_client(tmp_path, settings)

        try:
            upload_resp = client.post(
                "/api/v1/documents/upload",
                files={"file": ("stream_smoke.txt", b"Stream smoke test alarm E303 handling.", "text/plain")},
            )
            assert upload_resp.status_code == 201

            with client.stream(
                "POST",
                "/api/v1/chat/ask/stream",
                json={"question": "How to handle E303?", "top_k": 3},
            ) as stream_resp:
                raw = "".join(stream_resp.iter_text())
                status_code = stream_resp.status_code
        finally:
            _teardown()

        assert status_code == 200
        events = parse_sse_events(raw)
        event_names = [name for name, _ in events]

        # Matrix §3: POST /api/v1/chat/ask/stream 稳定 SSE 事件
        assert "meta" in event_names, "缺少 meta 事件"
        assert "done" in event_names, "缺少 done 事件"

        meta_payload = next(p for n, p in events if n == "meta")
        _assert_contains_keys(meta_payload, {"question", "mode", "model", "citations"})

        done_payload = next(p for n, p in events if n == "done")
        _assert_contains_keys(done_payload, {"question", "answer", "mode", "model", "citations"})


# ---------------------------------------------------------------------------
# 4. 权限回归：跨部门访问限制
# ---------------------------------------------------------------------------

class TestAuthorizationSmoke:
    """验证跨部门文档访问限制（检索 + 问答返回 403）。"""

    def test_cross_department_document_rejected_for_retrieval_and_chat(self, tmp_path: Path) -> None:
        client = _build_authz_env(tmp_path)
        try:
            sys_admin_headers = _login_headers(client, username="sys.admin.smoke", password="sysadmin-pass")
            employee_headers = _login_headers(client, username="emp.aftersales", password="emp-pass")

            # sys_admin 在 dept_assembly 创建文档
            create_resp = client.post(
                "/api/v1/documents",
                data={"tenant_id": "wl", "department_id": "dept_assembly"},
                files={"file": ("assembly_secret.txt", b"Assembly-only E990 investigation.", "text/plain")},
                headers=sys_admin_headers,
            )
            assert create_resp.status_code == 201
            forbidden_doc_id = create_resp.json()["doc_id"]

            # 员工在 dept_after_sales 尝试检索 dept_assembly 的文档 → 403
            retrieval_resp = client.post(
                "/api/v1/retrieval/search",
                json={"query": "E990", "top_k": 3, "document_id": forbidden_doc_id},
                headers=employee_headers,
            )
            assert retrieval_resp.status_code == 403

            # 员工尝试对 dept_assembly 文档问答 → 403
            chat_resp = client.post(
                "/api/v1/chat/ask",
                json={"question": "What is E990?", "top_k": 3, "document_id": forbidden_doc_id},
                headers=employee_headers,
            )
            assert chat_resp.status_code == 403

            # 验证错误包络（Matrix §6: error.code + error.message + error.status_code）
            for resp in (retrieval_resp, chat_resp):
                error_payload = resp.json()
                assert error_payload["detail"], "兼容字段 detail 不应为空"
                assert "error" in error_payload
                _assert_contains_keys(
                    error_payload["error"],
                    {"code", "message", "status_code"},
                )
                assert error_payload["error"]["status_code"] == 403

        finally:
            _teardown()

    def test_document_list_filters_by_department(self, tmp_path: Path) -> None:
        """员工只能看到自己部门的文档。"""
        client = _build_authz_env(tmp_path)
        try:
            sys_admin_headers = _login_headers(client, username="sys.admin.smoke", password="sysadmin-pass")
            employee_headers = _login_headers(client, username="emp.aftersales", password="emp-pass")

            # 在两个部门各创建一个文档
            visible_resp = client.post(
                "/api/v1/documents",
                data={"tenant_id": "wl", "department_id": "dept_after_sales"},
                files={"file": ("visible.txt", b"Visible to employee.", "text/plain")},
                headers=sys_admin_headers,
            )
            assert visible_resp.status_code == 201
            visible_doc_id = visible_resp.json()["doc_id"]

            hidden_resp = client.post(
                "/api/v1/documents",
                data={"tenant_id": "wl", "department_id": "dept_assembly"},
                files={"file": ("hidden.txt", b"Hidden from employee.", "text/plain")},
                headers=sys_admin_headers,
            )
            assert hidden_resp.status_code == 201

            # 员工查看文档列表
            list_resp = client.get("/api/v1/documents?page=1&page_size=20", headers=employee_headers)
            assert list_resp.status_code == 200

            # Matrix §2: GET /api/v1/documents 分页骨架
            list_payload = list_resp.json()
            _assert_contains_keys(list_payload, {"total", "page", "page_size", "items"})

            # 只能看到 dept_after_sales 的文档
            doc_ids = {item["document_id"] for item in list_payload["items"]}
            assert visible_doc_id in doc_ids
            assert hidden_resp.json()["doc_id"] not in doc_ids
            assert list_payload["total"] == 1

        finally:
            _teardown()
