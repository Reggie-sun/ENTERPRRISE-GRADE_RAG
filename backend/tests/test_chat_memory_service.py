from pathlib import Path

from backend.app.core.config import Settings, ensure_data_directories
from backend.app.schemas.auth import AuthContext, DepartmentRecord, RoleDefinition, UserRecord
from backend.app.schemas.chat import ChatRequest
from backend.app.schemas.retrieval import RetrievalRequest, RetrievalResponse, RetrievedChunk
from backend.app.services.chat_memory_service import ChatMemoryService
from backend.app.services.chat_service import ChatService


def _build_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        _env_file=None,
        app_env="test",
        debug=True,
        data_dir=data_dir,
        upload_dir=data_dir / "uploads",
        parsed_dir=data_dir / "parsed",
        chunk_dir=data_dir / "chunks",
        document_dir=data_dir / "documents",
        job_dir=data_dir / "jobs",
        event_log_dir=data_dir / "event_logs",
        request_trace_dir=data_dir / "request_traces",
        request_snapshot_dir=data_dir / "request_snapshots",
        chat_memory_dir=data_dir / "chat_memory",
        system_config_path=data_dir / "system_config.json",
        llm_provider="mock",
        embedding_provider="mock",
        reranker_provider="heuristic",
        chat_memory_max_turns=3,
        chat_memory_question_max_chars=40,
        chat_memory_answer_max_chars=60,
        chat_memory_max_prompt_tokens=120,
    )


def _build_auth_context(*, user_id: str = "user_001", username: str = "digitalization.real.08") -> AuthContext:
    department = DepartmentRecord(
        department_id="dept_digitalization",
        tenant_id="wl",
        department_name="数字化部",
    )
    role = RoleDefinition(
        role_id="employee",
        name="employee",
        description="employee",
        data_scope="department",
        is_admin=False,
    )
    user = UserRecord(
        user_id=user_id,
        tenant_id="wl",
        username=username,
        display_name="Digitalization User",
        department_id=department.department_id,
        role_id="employee",
    )
    return AuthContext.model_construct(
        user=user,
        role=role,
        department=department,
        accessible_department_ids=[department.department_id],
        token_id="token_test",
        issued_at=None,
        expires_at=None,
    )


class _FakeRetrievalService:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, request: RetrievalRequest, *, auth_context: AuthContext | None = None) -> RetrievalResponse:
        self.queries.append(request.query)
        return RetrievalResponse(
            query=request.query,
            top_k=request.top_k or 5,
            mode="hybrid",
            results=[
                RetrievedChunk(
                    chunk_id="chunk_001",
                    document_id=request.document_id or "doc_global",
                    document_name="巡检手册.docx",
                    text="巡检时先确认设备停机，再读取报警记录。",
                    score=0.91,
                    source_path="asset://doc_global",
                    retrieval_strategy="hybrid",
                    vector_score=0.88,
                    lexical_score=1.8,
                    fused_score=0.91,
                )
            ],
        )

    def search_candidates(
        self,
        request: RetrievalRequest,
        *,
        auth_context: AuthContext | None = None,
        profile=None,
        truncate_to_top_k: bool = True,
    ):
        response = self.search(request, auth_context=auth_context)
        limit = request.top_k if truncate_to_top_k else (request.candidate_top_k or len(response.results))
        return response.results[:limit], response.mode, profile


class _FakeGenerationClient:
    def __init__(self) -> None:
        self.last_memory_text: str | None = None
        self.last_question: str | None = None

    def generate(
        self,
        *,
        question: str,
        contexts: list[str],
        memory_text: str | None = None,
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:
        self.last_question = question
        self.last_memory_text = memory_text
        return "根据当前资料，先停机再检查报警记录。"


def test_chat_memory_service_builds_summary_and_filters_document_scope(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    service = ChatMemoryService(settings)
    auth_context = _build_auth_context()

    service.record_turn(
        session_id="sess_portal_1",
        auth_context=auth_context,
        document_id=None,
        question="悖论放松法是什么？",
        answer="它是一种先承认矛盾感受，再逐步降低紧张的练习方式。",
        response_mode="rag",
        citation_count=2,
    )
    service.record_turn(
        session_id="sess_portal_1",
        auth_context=auth_context,
        document_id="doc_001",
        question="这份文档的第一步是什么？",
        answer="第一步是停机并确认报警编号。",
        response_mode="rag",
        citation_count=1,
    )

    global_summary = service.build_memory_summary(
        session_id="sess_portal_1",
        auth_context=auth_context,
        document_id=None,
    )
    document_summary = service.build_memory_summary(
        session_id="sess_portal_1",
        auth_context=auth_context,
        document_id="doc_001",
    )

    assert global_summary is not None
    assert "悖论放松法是什么" in global_summary
    assert "第一步是停机" not in global_summary
    assert document_summary is not None
    assert "第一步是停机" in document_summary
    assert "悖论放松法是什么" not in document_summary


def test_chat_service_uses_recent_memory_for_follow_up_question(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    chat_service = ChatService(settings, chat_memory_service=memory_service)
    fake_generation_client = _FakeGenerationClient()

    chat_service.retrieval_service = _FakeRetrievalService()
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    first_response = chat_service.answer(
        ChatRequest(question="悖论放松法是什么？", session_id="sess_portal_followup"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="那第二步呢？", session_id="sess_portal_followup"),
        auth_context=auth_context,
    )

    assert first_response.mode == "rag"
    assert second_response.mode == "rag"
    assert fake_generation_client.last_question == "关于悖论放松法，第二步是什么？"
    assert fake_generation_client.last_memory_text is not None
    assert "悖论放松法是什么" in fake_generation_client.last_memory_text


def test_chat_service_rewrites_short_follow_up_question_with_recent_topic(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    first_response = chat_service.answer(
        ChatRequest(question="解释一下CPPS", session_id="sess_portal_cpps"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="更详细一点", session_id="sess_portal_cpps"),
        auth_context=auth_context,
    )

    assert first_response.mode == "rag"
    assert second_response.mode == "rag"
    assert retrieval_service.queries[0] == "解释一下CPPS"
    assert retrieval_service.queries[1] == "请更详细地解释CPPS。"
    assert fake_generation_client.last_question == "请更详细地解释CPPS。"


def test_chat_service_uses_anchor_question_for_multi_turn_short_follow_up(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="解释一下CPPS", session_id="sess_portal_cpps_anchor"),
        auth_context=auth_context,
    )
    chat_service.answer(
        ChatRequest(question="更详细一点", session_id="sess_portal_cpps_anchor"),
        auth_context=auth_context,
    )
    third_response = chat_service.answer(
        ChatRequest(question="那第二步呢？", session_id="sess_portal_cpps_anchor"),
        auth_context=auth_context,
    )

    assert third_response.mode == "rag"
    assert retrieval_service.queries[2] == "关于CPPS，第二步是什么？"
    assert fake_generation_client.last_question == "关于CPPS，第二步是什么？"


def test_chat_service_rewrites_detail_follow_up_for_suffix_subject_question(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="CPPS是什么？", session_id="sess_portal_cpps_suffix"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="更详细一点", session_id="sess_portal_cpps_suffix"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "请更详细地解释CPPS。"
    assert fake_generation_client.last_question == "请更详细地解释CPPS。"


def test_chat_service_rewrites_detail_follow_up_for_process_question(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="E204怎么处理？", session_id="sess_portal_e204_process"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="更详细一点", session_id="sess_portal_e204_process"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "请更详细地说明E204该怎么处理。"
    assert fake_generation_client.last_question == "请更详细地说明E204该怎么处理。"


def test_chat_service_rewrites_meaning_follow_up_back_to_subject(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="CPPS是什么？", session_id="sess_portal_cpps_meaning"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="这个是什么意思", session_id="sess_portal_cpps_meaning"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "CPPS是什么意思？"
    assert fake_generation_client.last_question == "CPPS是什么意思？"


def test_chat_service_rewrites_why_follow_up_back_to_subject(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="CPPS是什么？", session_id="sess_portal_cpps_why"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="为什么会这样", session_id="sess_portal_cpps_why"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "为什么会出现CPPS？"
    assert fake_generation_client.last_question == "为什么会出现CPPS？"


def test_chat_service_rewrites_how_follow_up_back_to_process_subject(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="E204怎么处理？", session_id="sess_portal_e204_how"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="那怎么处理", session_id="sess_portal_e204_how"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "E204该怎么处理？"
    assert fake_generation_client.last_question == "E204该怎么处理？"


def test_chat_service_rewrites_cause_follow_up_back_to_subject(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="CPPS是什么？", session_id="sess_portal_cpps_cause"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="这是什么原因", session_id="sess_portal_cpps_cause"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "为什么会出现CPPS？"
    assert fake_generation_client.last_question == "为什么会出现CPPS？"


def test_chat_service_rewrites_prevent_follow_up_back_to_subject(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="CPPS是什么？", session_id="sess_portal_cpps_prevent"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="那要怎么预防", session_id="sess_portal_cpps_prevent"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "如何预防CPPS？"
    assert fake_generation_client.last_question == "如何预防CPPS？"


def test_chat_service_rewrites_prevent_follow_up_for_process_subject(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="E204怎么处理？", session_id="sess_portal_e204_prevent"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="那要怎么避免", session_id="sess_portal_e204_prevent"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "如何避免E204再次发生？"
    assert fake_generation_client.last_question == "如何避免E204再次发生？"


def test_chat_service_rewrites_impact_follow_up_back_to_subject(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="CPPS是什么？", session_id="sess_portal_cpps_impact"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="会怎么样", session_id="sess_portal_cpps_impact"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "CPPS会怎么样？"
    assert fake_generation_client.last_question == "CPPS会怎么样？"


def test_chat_service_rewrites_impact_detail_follow_up_back_to_subject(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="CPPS是什么？", session_id="sess_portal_cpps_impact_detail"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="有什么影响", session_id="sess_portal_cpps_impact_detail"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "CPPS有什么影响？"
    assert fake_generation_client.last_question == "CPPS有什么影响？"


def test_chat_service_rewrites_untreated_impact_follow_up_for_process_subject(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="E204怎么处理？", session_id="sess_portal_e204_impact"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="不处理会怎么样", session_id="sess_portal_e204_impact"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "E204不处理会怎么样？"
    assert fake_generation_client.last_question == "E204不处理会怎么样？"


def test_chat_service_rewrites_compare_follow_up_back_to_anchor_question(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="CPPS和PPS有什么区别？", session_id="sess_portal_cpps_compare"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="有什么区别", session_id="sess_portal_cpps_compare"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "CPPS和PPS有什么区别？"
    assert fake_generation_client.last_question == "CPPS和PPS有什么区别？"


def test_chat_service_rewrites_compare_follow_up_with_previous_reference(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="E204和E205有什么区别？", session_id="sess_portal_e204_compare"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="和前面的区别是什么", session_id="sess_portal_e204_compare"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "E204和E205有什么区别？"
    assert fake_generation_client.last_question == "E204和E205有什么区别？"


def test_chat_service_rewrites_compare_follow_up_for_pronoun_pair(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="CPPS和PPS有什么区别？", session_id="sess_portal_compare_pronoun"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="那两者呢", session_id="sess_portal_compare_pronoun"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "CPPS和PPS有什么区别？"
    assert fake_generation_client.last_question == "CPPS和PPS有什么区别？"


def test_chat_service_rewrites_compare_follow_up_for_more_specific_comparison(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="CPPS和PPS有什么区别？", session_id="sess_portal_compare_specific"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="哪个更常见", session_id="sess_portal_compare_specific"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "CPPS和PPS哪个更常见？"
    assert fake_generation_client.last_question == "CPPS和PPS哪个更常见？"


def test_chat_service_rewrites_compare_follow_up_for_two_items_pronoun(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="CPPS和PPS有什么区别？", session_id="sess_portal_compare_two_items"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="那两个呢", session_id="sess_portal_compare_two_items"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "CPPS和PPS有什么区别？"
    assert fake_generation_client.last_question == "CPPS和PPS有什么区别？"


def test_chat_service_rewrites_compare_follow_up_for_which_one_variant(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="CPPS和PPS有什么区别？", session_id="sess_portal_compare_which_one"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="哪一个更适合", session_id="sess_portal_compare_which_one"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "CPPS和PPS哪一个更适合？"
    assert fake_generation_client.last_question == "CPPS和PPS哪一个更适合？"


def test_chat_service_rewrites_compare_follow_up_for_which_kind_variant(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    auth_context = _build_auth_context()
    memory_service = ChatMemoryService(settings)
    retrieval_service = _FakeRetrievalService()
    fake_generation_client = _FakeGenerationClient()
    chat_service = ChatService(settings, chat_memory_service=memory_service)

    chat_service.retrieval_service = retrieval_service
    chat_service.generation_client = fake_generation_client  # type: ignore[assignment]

    chat_service.answer(
        ChatRequest(question="CPPS和PPS有什么区别？", session_id="sess_portal_compare_which_kind"),
        auth_context=auth_context,
    )
    second_response = chat_service.answer(
        ChatRequest(question="哪种更常见", session_id="sess_portal_compare_which_kind"),
        auth_context=auth_context,
    )

    assert second_response.mode == "rag"
    assert retrieval_service.queries[1] == "CPPS和PPS哪种更常见？"
    assert fake_generation_client.last_question == "CPPS和PPS哪种更常见？"
