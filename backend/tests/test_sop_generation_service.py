import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app.core.config import Settings
from backend.app.rag.generators.client import LLMGenerationRetryableError
from backend.app.schemas.retrieval import RetrievalResponse, RetrievedChunk
from backend.app.schemas.sop_generation import (
    SopGenerateByDocumentRequest,
    SopGenerateByScenarioRequest,
    SopGenerateByTopicRequest,
)
from backend.app.schemas.system_config import SystemConfigUpdateRequest
from backend.app.services.auth_service import AuthService
from backend.app.services.identity_service import IdentityService
from backend.app.services.query_profile_service import QueryProfileService
from backend.app.services.sop_generation_service import SopGenerationService
from backend.app.services.system_config_service import SystemConfigService


def _write_identity_bootstrap(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "role_id": "employee",
                        "name": "Employee",
                        "description": "Department reader",
                        "data_scope": "department",
                        "is_admin": False,
                    },
                    {
                        "role_id": "department_admin",
                        "name": "Department Admin",
                        "description": "Department manager",
                        "data_scope": "department",
                        "is_admin": True,
                    },
                    {
                        "role_id": "sys_admin",
                        "name": "System Admin",
                        "description": "Global manager",
                        "data_scope": "global",
                        "is_admin": True,
                    },
                ],
                "departments": [
                    {
                        "department_id": "dept_digitalization",
                        "tenant_id": "wl",
                        "department_name": "数字化部",
                        "parent_department_id": None,
                        "is_active": True,
                    },
                    {
                        "department_id": "dept_assembly",
                        "tenant_id": "wl",
                        "department_name": "装配部",
                        "parent_department_id": None,
                        "is_active": True,
                    },
                ],
                "users": [
                    {
                        "user_id": "user_digitalization_employee",
                        "tenant_id": "wl",
                        "username": "digitalization.employee",
                        "display_name": "数字化员工",
                        "department_id": "dept_digitalization",
                        "role_id": "employee",
                        "is_active": True,
                        "password_hash": AuthService.hash_password(
                            "digitalization-employee-pass",
                            salt=bytes.fromhex("00112233445566778899aabbccddeeff"),
                        ),
                    },
                    {
                        "user_id": "user_digitalization_admin",
                        "tenant_id": "wl",
                        "username": "digitalization.admin",
                        "display_name": "数字化管理员",
                        "department_id": "dept_digitalization",
                        "role_id": "department_admin",
                        "is_active": True,
                        "password_hash": AuthService.hash_password(
                            "digitalization-admin-pass",
                            salt=bytes.fromhex("10112233445566778899aabbccddeeff"),
                        ),
                    },
                    {
                        "user_id": "user_sys_admin",
                        "tenant_id": "wl",
                        "username": "sys.admin",
                        "display_name": "系统管理员",
                        "department_id": "dept_digitalization",
                        "role_id": "sys_admin",
                        "is_active": True,
                        "password_hash": AuthService.hash_password(
                            "sys-admin-pass",
                            salt=bytes.fromhex("11223344556677889900aabbccddeeff"),
                        ),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _build_identity_service(tmp_path: Path) -> IdentityService:
    identity_bootstrap_path = tmp_path / "identity_bootstrap.json"
    _write_identity_bootstrap(identity_bootstrap_path)
    return IdentityService(Settings(_env_file=None, identity_bootstrap_path=identity_bootstrap_path))


def _build_auth_context(identity_service: IdentityService, *, username: str, password: str):
    settings = Settings(
        _env_file=None,
        identity_bootstrap_path=identity_service.settings.identity_bootstrap_path,
        auth_token_secret="test-auth-secret",
        auth_token_issuer="test-auth-issuer",
    )
    auth_service = AuthService(settings, identity_service=identity_service)
    token = auth_service.login(username, password).access_token
    return auth_service.build_auth_context(token)


class _FakeRetrievalService:
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.last_request = None

    def search(self, request, *, auth_context=None):
        self.last_request = request
        return RetrievalResponse(query=request.query, top_k=request.top_k, mode="fake", results=self.results)


class _FakeRerankerClient:
    def rerank(self, *, query: str, candidates: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:
        return candidates[:top_n]


class _FakeGenerationClient:
    def __init__(self, *, answer: str | None = None, retryable_error: bool = False) -> None:
        self.answer = answer or "生成的 SOP 草稿"
        self.retryable_error = retryable_error
        self.last_question = None
        self.last_timeout_seconds = None
        self.last_model_name = None

    def generate(
        self,
        *,
        question: str,
        contexts: list[str],
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:
        self.last_question = question
        self.last_timeout_seconds = timeout_seconds
        self.last_model_name = model_name
        if self.retryable_error:
            raise LLMGenerationRetryableError("temporary llm issue")
        return self.answer


class _FakeDocumentService:
    def __init__(
        self,
        department_map: dict[str, str],
        file_name_map: dict[str, str] | None = None,
        preview_text_map: dict[str, str] | None = None,
    ) -> None:
        self.department_map = department_map
        self.file_name_map = file_name_map or {}
        self.preview_text_map = preview_text_map or {}

    def get_document(self, doc_id: str, *, auth_context=None):
        return SimpleNamespace(
            doc_id=doc_id,
            department_id=self.department_map[doc_id],
            file_name=self.file_name_map.get(doc_id, f"{doc_id}.txt"),
        )

    def get_document_preview(self, doc_id: str, *, max_chars=12_000, auth_context=None):
        preview_text = self.preview_text_map.get(doc_id, "")
        return SimpleNamespace(
            doc_id=doc_id,
            file_name=self.file_name_map.get(doc_id, f"{doc_id}.txt"),
            preview_type="text",
            content_type="text/plain; charset=utf-8",
            text_content=preview_text[:max_chars] if preview_text else None,
            text_truncated=bool(preview_text and len(preview_text) > max_chars),
            preview_file_url=None,
        )


def test_sop_generation_service_generates_scenario_draft_for_department_admin(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.admin",
        password="digitalization-admin-pass",
    )
    retrieval_service = _FakeRetrievalService(
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
    )
    service = SopGenerationService(
        Settings(_env_file=None),
        identity_service=identity_service,
        retrieval_service=retrieval_service,
        document_service=_FakeDocumentService(
            {
                "doc_digitalization": "dept_digitalization",
                "doc_assembly": "dept_assembly",
            }
        ),
        reranker_client=_FakeRerankerClient(),
        generation_client=_FakeGenerationClient(answer="这是数字化部系统巡检 SOP 草稿。"),
    )

    response = service.generate_from_scenario(
        request=SopGenerateByScenarioRequest(
            scenario_name="日常运维",
            process_name="巡检",
            top_k=3,
        ),
        auth_context=auth_context,
    )

    assert response.request_mode == "scenario"
    assert response.generation_mode == "rag"
    assert response.department_id == "dept_digitalization"
    assert response.process_name == "巡检"
    assert response.scenario_name == "日常运维"
    assert response.content == "这是数字化部系统巡检 SOP 草稿。"
    assert [item.document_id for item in response.citations] == ["doc_digitalization"]
    assert "数字化部" in (retrieval_service.last_request.query or "")


def test_sop_generation_service_defaults_to_accurate_profile_when_request_omits_mode_and_top_k(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.admin",
        password="digitalization-admin-pass",
    )
    retrieval_service = _FakeRetrievalService(
        [
            RetrievedChunk(
                chunk_id=f"chunk_{index}",
                document_id="doc_digitalization",
                document_name="数字化巡检手册",
                text=f"巡检步骤 {index}：先检查任务调度服务、数据库连接和系统日志。",
                score=0.95 - index * 0.01,
                source_path="/tmp/digitalization.txt",
            )
            for index in range(8)
        ]
    )
    service = SopGenerationService(
        Settings(_env_file=None),
        identity_service=identity_service,
        retrieval_service=retrieval_service,
        document_service=_FakeDocumentService({"doc_digitalization": "dept_digitalization"}),
        reranker_client=_FakeRerankerClient(),
        generation_client=_FakeGenerationClient(answer="这是准确档 SOP 草稿。"),
    )

    response = service.generate_from_document(
        request=SopGenerateByDocumentRequest(document_id="doc_digitalization"),
        auth_context=auth_context,
    )

    assert retrieval_service.last_request.mode == "accurate"
    assert retrieval_service.last_request.top_k == 8
    assert retrieval_service.last_request.candidate_top_k == 32
    assert response.generation_mode == "rag"
    assert len(response.citations) == 5


def test_sop_generation_service_uses_fallback_when_llm_retryable(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.admin",
        password="digitalization-admin-pass",
    )
    service = SopGenerationService(
        Settings(_env_file=None),
        identity_service=identity_service,
        retrieval_service=_FakeRetrievalService(
            [
                RetrievedChunk(
                    chunk_id="chunk_1",
                    document_id="doc_digitalization",
                    document_name="数字化巡检手册",
                    text="交接前核对当班未闭环告警和待处理事项。",
                    score=0.91,
                    source_path="/tmp/digitalization.txt",
                )
            ]
        ),
        document_service=_FakeDocumentService({"doc_digitalization": "dept_digitalization"}),
        reranker_client=_FakeRerankerClient(),
        generation_client=_FakeGenerationClient(retryable_error=True),
    )

    response = service.generate_from_topic(
        request=SopGenerateByTopicRequest(
            topic="值班交接",
            process_name="交接",
            scenario_name="夜班交班",
        ),
        auth_context=auth_context,
    )

    assert response.request_mode == "topic"
    assert response.generation_mode == "retrieval_fallback"
    assert "证据摘要" in response.content
    assert "交接前核对当班未闭环告警" in response.content


def test_sop_generation_service_respects_retrieval_fallback_toggle(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.admin",
        password="digitalization-admin-pass",
    )
    settings = Settings(_env_file=None, system_config_path=tmp_path / "data" / "system_config.json")
    system_config_service = SystemConfigService(settings)
    admin_context = _build_auth_context(identity_service, username="sys.admin", password="sys-admin-pass")
    current_config = system_config_service.get_config(auth_context=admin_context)
    system_config_service.update_config(
        SystemConfigUpdateRequest(
            query_profiles=current_config.query_profiles,
            model_routing=current_config.model_routing,
            degrade_controls=current_config.degrade_controls.model_copy(
                update={"retrieval_fallback_enabled": False}
            ),
            retry_controls=current_config.retry_controls,
        ),
        auth_context=admin_context,
    )
    query_profile_service = QueryProfileService(settings, system_config_service=system_config_service)
    service = SopGenerationService(
        settings,
        identity_service=identity_service,
        retrieval_service=_FakeRetrievalService(
            [
                RetrievedChunk(
                    chunk_id="chunk_1",
                    document_id="doc_digitalization",
                    document_name="数字化巡检手册",
                    text="交接前核对当班未闭环告警和待处理事项。",
                    score=0.91,
                    source_path="/tmp/digitalization.txt",
                )
            ]
        ),
        document_service=_FakeDocumentService({"doc_digitalization": "dept_digitalization"}),
        reranker_client=_FakeRerankerClient(),
        generation_client=_FakeGenerationClient(retryable_error=True),
        query_profile_service=query_profile_service,
    )

    with pytest.raises(LLMGenerationRetryableError):
        service.generate_from_topic(
            request=SopGenerateByTopicRequest(topic="值班交接"),
            auth_context=auth_context,
        )


def test_sop_generation_service_generates_document_draft_for_selected_doc(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.admin",
        password="digitalization-admin-pass",
    )
    retrieval_service = _FakeRetrievalService(
        [
            RetrievedChunk(
                chunk_id="chunk_1",
                document_id="doc_digitalization",
                document_name="数字化巡检手册",
                text="先检查任务调度服务、数据库连接和告警队列。",
                score=0.94,
                source_path="/tmp/digitalization.txt",
            ),
        ]
    )
    generation_client = _FakeGenerationClient(answer="这是基于单文档生成的 SOP 草稿。")
    service = SopGenerationService(
        Settings(_env_file=None),
        identity_service=identity_service,
        retrieval_service=retrieval_service,
        document_service=_FakeDocumentService(
            {"doc_digitalization": "dept_digitalization"},
            {"doc_digitalization": "数字化巡检手册.pdf"},
        ),
        reranker_client=_FakeRerankerClient(),
        generation_client=generation_client,
    )

    response = service.generate_from_document(
        request=SopGenerateByDocumentRequest(document_id="doc_digitalization", top_k=4),
        auth_context=auth_context,
    )

    assert response.request_mode == "document"
    assert response.generation_mode == "rag"
    assert response.topic == "数字化巡检手册"
    assert response.content == "这是基于单文档生成的 SOP 草稿。"
    assert retrieval_service.last_request.document_id == "doc_digitalization"
    assert "数字化巡检手册" in (retrieval_service.last_request.query or "")
    assert generation_client.last_question is not None
    assert generation_client.last_model_name == "mock"
    assert "来源文档：数字化巡检手册.pdf" in generation_client.last_question


def test_sop_generation_service_uses_configured_sop_model_route(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.admin",
        password="digitalization-admin-pass",
    )
    settings = Settings(
        _env_file=None,
        llm_provider="openai",
        llm_model="Qwen/Shared-Default",
        system_config_path=tmp_path / "data" / "system_config.json",
    )
    system_config_service = SystemConfigService(settings)
    current_config = system_config_service.get_config(auth_context=_build_auth_context(identity_service, username="sys.admin", password="sys-admin-pass"))
    system_config_service.update_config(
        SystemConfigUpdateRequest(
            query_profiles=current_config.query_profiles,
            model_routing=current_config.model_routing.model_copy(
                update={"sop_generation_model": "Qwen/SOP-14B"}
            ),
            degrade_controls=current_config.degrade_controls,
            retry_controls=current_config.retry_controls,
        ),
        auth_context=_build_auth_context(identity_service, username="sys.admin", password="sys-admin-pass"),
    )
    query_profile_service = QueryProfileService(settings, system_config_service=system_config_service)
    generation_client = _FakeGenerationClient(answer="基于独立 SOP 模型生成的草稿。")
    service = SopGenerationService(
        settings,
        identity_service=identity_service,
        retrieval_service=_FakeRetrievalService(
            [
                RetrievedChunk(
                    chunk_id="chunk_1",
                    document_id="doc_digitalization",
                    document_name="数字化巡检手册",
                    text="根据文档执行巡检并记录异常。",
                    score=0.95,
                    source_path="/tmp/digitalization.txt",
                )
            ]
        ),
        document_service=_FakeDocumentService({"doc_digitalization": "dept_digitalization"}),
        reranker_client=_FakeRerankerClient(),
        generation_client=generation_client,
        query_profile_service=query_profile_service,
    )

    response = service.generate_from_document(
        request=SopGenerateByDocumentRequest(document_id="doc_digitalization"),
        auth_context=auth_context,
    )

    assert response.model == "Qwen/SOP-14B"
    assert generation_client.last_model_name == "Qwen/SOP-14B"


def test_sop_generation_service_allows_employee_generation_within_scope(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.employee",
        password="digitalization-employee-pass",
    )
    retrieval_service = _FakeRetrievalService(
        [
            RetrievedChunk(
                chunk_id="chunk_1",
                document_id="doc_digitalization",
                document_name="数字化值班手册",
                text="先检查值班记录、任务调度服务和数据库连接。",
                score=0.93,
                source_path="/tmp/digitalization_employee.txt",
            ),
        ]
    )
    service = SopGenerationService(
        Settings(_env_file=None),
        identity_service=identity_service,
        retrieval_service=retrieval_service,
        document_service=_FakeDocumentService({"doc_digitalization": "dept_digitalization"}),
        reranker_client=_FakeRerankerClient(),
        generation_client=_FakeGenerationClient(answer="员工可直接生成 SOP 草稿。"),
    )

    response = service.generate_from_scenario(
        request=SopGenerateByScenarioRequest(scenario_name="日常运维"),
        auth_context=auth_context,
    )

    assert response.request_mode == "scenario"
    assert response.department_id == "dept_digitalization"
    assert response.content == "员工可直接生成 SOP 草稿。"
    assert [item.document_id for item in response.citations] == ["doc_digitalization"]


def test_sop_generation_service_rejects_cross_department_request_for_department_admin(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.admin",
        password="digitalization-admin-pass",
    )
    service = SopGenerationService(
        Settings(_env_file=None),
        identity_service=identity_service,
        retrieval_service=_FakeRetrievalService([]),
        document_service=_FakeDocumentService({}),
        reranker_client=_FakeRerankerClient(),
        generation_client=_FakeGenerationClient(),
    )

    with pytest.raises(HTTPException) as exc_info:
        service.generate_from_topic(
            request=SopGenerateByTopicRequest(topic="装配报警处理", department_id="dept_assembly"),
            auth_context=auth_context,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Cannot generate SOP drafts outside your accessible departments."


def test_sop_generation_service_rejects_empty_evidence_after_department_filter(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="sys.admin",
        password="sys-admin-pass",
    )
    service = SopGenerationService(
        Settings(_env_file=None),
        identity_service=identity_service,
        retrieval_service=_FakeRetrievalService(
            [
                RetrievedChunk(
                    chunk_id="chunk_assembly",
                    document_id="doc_assembly",
                    document_name="装配报警手册",
                    text="装配设备报警时先检查急停与气源。",
                    score=0.88,
                    source_path="/tmp/assembly.txt",
                )
            ]
        ),
        document_service=_FakeDocumentService({"doc_assembly": "dept_assembly"}),
        reranker_client=_FakeRerankerClient(),
        generation_client=_FakeGenerationClient(),
    )

    with pytest.raises(HTTPException) as exc_info:
        service.generate_from_scenario(
            request=SopGenerateByScenarioRequest(
                scenario_name="日常运维",
                department_id="dept_digitalization",
            ),
            auth_context=auth_context,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "No relevant evidence was retrieved for SOP generation."


def test_sop_generation_service_uses_document_preview_fallback_when_retrieval_returns_empty(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.employee",
        password="digitalization-employee-pass",
    )
    service = SopGenerationService(
        Settings(_env_file=None),
        identity_service=identity_service,
        retrieval_service=_FakeRetrievalService([]),
        document_service=_FakeDocumentService(
            {"doc_digitalization": "dept_digitalization"},
            {"doc_digitalization": "数字化系统巡检手册.docx"},
            {
                "doc_digitalization": "巡检前检查监控面板和服务状态。\n\n发现异常后记录时间、现象和影响范围。\n\n完成处理后更新值班记录并通知相关同事。"
            },
        ),
        reranker_client=_FakeRerankerClient(),
        generation_client=_FakeGenerationClient(answer="这是基于文档预览回退生成的 SOP 草稿。"),
    )

    response = service.generate_from_document(
        request=SopGenerateByDocumentRequest(document_id="doc_digitalization"),
        auth_context=auth_context,
    )

    assert response.request_mode == "document"
    assert response.generation_mode == "rag"
    assert response.content == "这是基于文档预览回退生成的 SOP 草稿。"
    assert len(response.citations) == 3
    assert response.citations[0].chunk_id == "doc_digitalization-preview-0"
    assert "巡检前检查监控面板和服务状态" in response.citations[0].snippet


def test_sop_generation_service_still_rejects_document_generation_when_preview_is_empty(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.employee",
        password="digitalization-employee-pass",
    )
    service = SopGenerationService(
        Settings(_env_file=None),
        identity_service=identity_service,
        retrieval_service=_FakeRetrievalService([]),
        document_service=_FakeDocumentService(
            {"doc_digitalization": "dept_digitalization"},
            {"doc_digitalization": "数字化系统巡检手册.docx"},
            {"doc_digitalization": ""},
        ),
        reranker_client=_FakeRerankerClient(),
        generation_client=_FakeGenerationClient(),
    )

    with pytest.raises(HTTPException) as exc_info:
        service.generate_from_document(
            request=SopGenerateByDocumentRequest(document_id="doc_digitalization"),
            auth_context=auth_context,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "No relevant evidence was retrieved for SOP generation."
