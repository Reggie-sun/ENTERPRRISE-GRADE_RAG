from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse

from ._response_headers import build_content_disposition
from ....schemas.auth import AuthContext
from ....schemas.sop import SopDetailResponse, SopDownloadFormat, SopListResponse, SopPreviewResponse, SopStatus
from ....schemas.sop_generation import (
    SopDraftExportRequest,
    SopGenerateByDocumentRequest,
    SopGenerateByScenarioRequest,
    SopGenerateByTopicRequest,
    SopGenerationDraftResponse,
)
from ....schemas.sop_version import (
    SopSaveRequest,
    SopSaveResponse,
    SopVersionDetailResponse,
    SopVersionListResponse,
)
from ....services.auth_service import get_current_auth_context, get_optional_auth_context
from ....services.sop_generation_service import SopGenerationService, get_sop_generation_service
from ....services.sop_service import SopService, get_sop_service
from ....services.sop_version_service import SopVersionService, get_sop_version_service

router = APIRouter(prefix="/sops", tags=["sops"])  # v0.4 起把 SOP 作为独立业务对象暴露，不再挂在 documents 下。


@router.get(
    "",
    response_model=SopListResponse,
    summary="List SOP assets",
    description="Returns SOP list data with department/process/scenario filters and department-scope permission filtering.",
)
def list_sops(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    department_id: str | None = Query(default=None),
    process_name: str | None = Query(default=None),
    scenario_name: str | None = Query(default=None),
    sop_status: SopStatus | None = Query(default=None, alias="status"),
    auth_context: AuthContext | None = Depends(get_optional_auth_context),
    sop_service: SopService = Depends(get_sop_service),
) -> SopListResponse:
    return sop_service.list_sops(
        page=page,
        page_size=page_size,
        department_id=department_id,
        process_name=process_name,
        scenario_name=scenario_name,
        sop_status=sop_status,
        auth_context=auth_context,
    )


@router.post(
    "/generate/document",
    response_model=SopGenerationDraftResponse,
    summary="Generate SOP draft by source document",
    description="Generates a draft SOP directly from a selected document by reusing retrieval, rerank and LLM generation within that document scope.",
)
def generate_sop_by_document(
    payload: SopGenerateByDocumentRequest,
    auth_context: AuthContext = Depends(get_current_auth_context),
    sop_generation_service: SopGenerationService = Depends(get_sop_generation_service),
) -> SopGenerationDraftResponse:
    return sop_generation_service.generate_from_document(payload, auth_context=auth_context)


@router.post(
    "/generate/document/stream",
    summary="Stream SOP draft by source document",
    description="Streams an SOP draft directly from a selected document via SSE while reusing retrieval, rerank and LLM generation within that document scope.",
)
def generate_sop_by_document_stream(
    payload: SopGenerateByDocumentRequest,
    auth_context: AuthContext = Depends(get_current_auth_context),
    sop_generation_service: SopGenerationService = Depends(get_sop_generation_service),
) -> StreamingResponse:
    return StreamingResponse(
        sop_generation_service.stream_generate_from_document_sse(payload, auth_context=auth_context),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/generate/scenario",
    response_model=SopGenerationDraftResponse,
    summary="Generate SOP draft by scenario",
    description="Generates a draft SOP for a scenario by reusing retrieval, rerank and LLM generation over accessible evidence.",
)
def generate_sop_by_scenario(
    payload: SopGenerateByScenarioRequest,
    auth_context: AuthContext = Depends(get_current_auth_context),
    sop_generation_service: SopGenerationService = Depends(get_sop_generation_service),
) -> SopGenerationDraftResponse:
    return sop_generation_service.generate_from_scenario(payload, auth_context=auth_context)


@router.post(
    "/generate/scenario/stream",
    summary="Stream SOP draft by scenario",
    description="Streams an SOP draft for a scenario via SSE while reusing retrieval, rerank and LLM generation over accessible evidence.",
)
def generate_sop_by_scenario_stream(
    payload: SopGenerateByScenarioRequest,
    auth_context: AuthContext = Depends(get_current_auth_context),
    sop_generation_service: SopGenerationService = Depends(get_sop_generation_service),
) -> StreamingResponse:
    return StreamingResponse(
        sop_generation_service.stream_generate_from_scenario_sse(payload, auth_context=auth_context),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/generate/topic",
    response_model=SopGenerationDraftResponse,
    summary="Generate SOP draft by topic",
    description="Generates a draft SOP for a custom topic by reusing retrieval, rerank and LLM generation over accessible evidence.",
)
def generate_sop_by_topic(
    payload: SopGenerateByTopicRequest,
    auth_context: AuthContext = Depends(get_current_auth_context),
    sop_generation_service: SopGenerationService = Depends(get_sop_generation_service),
) -> SopGenerationDraftResponse:
    return sop_generation_service.generate_from_topic(payload, auth_context=auth_context)


@router.post(
    "/generate/topic/stream",
    summary="Stream SOP draft by topic",
    description="Streams an SOP draft for a custom topic via SSE while reusing retrieval, rerank and LLM generation over accessible evidence.",
)
def generate_sop_by_topic_stream(
    payload: SopGenerateByTopicRequest,
    auth_context: AuthContext = Depends(get_current_auth_context),
    sop_generation_service: SopGenerationService = Depends(get_sop_generation_service),
) -> StreamingResponse:
    return StreamingResponse(
        sop_generation_service.stream_generate_from_topic_sse(payload, auth_context=auth_context),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/export",
    summary="Export current SOP draft",
    description="Exports the current unsaved SOP draft as docx/pdf without requiring a saved SOP record first.",
)
def export_sop_draft(
    payload: SopDraftExportRequest,
    auth_context: AuthContext = Depends(get_current_auth_context),
    sop_service: SopService = Depends(get_sop_service),
) -> Response:
    file_payload = sop_service.export_sop_draft(payload, auth_context=auth_context)
    return Response(
        content=file_payload.content or b"",
        media_type=file_payload.media_type,
        headers={"Content-Disposition": build_content_disposition(file_payload.filename, disposition_type="attachment")},
    )


@router.post(
    "/save",
    response_model=SopSaveResponse,
    summary="Save SOP draft as current version",
    description="Saves generated or manually edited SOP content as current version and writes a version record.",
)
def save_sop(
    payload: SopSaveRequest,
    auth_context: AuthContext = Depends(get_current_auth_context),
    sop_version_service: SopVersionService = Depends(get_sop_version_service),
) -> SopSaveResponse:
    return sop_version_service.save_sop(payload, auth_context=auth_context)


@router.get(
    "/{sop_id}",
    response_model=SopDetailResponse,
    summary="Get SOP detail",
    description="Returns SOP detail data after department-scope permission filtering.",
)
def get_sop(
    sop_id: str,
    auth_context: AuthContext | None = Depends(get_optional_auth_context),
    sop_service: SopService = Depends(get_sop_service),
) -> SopDetailResponse:
    return sop_service.get_sop(sop_id, auth_context=auth_context)


@router.get(
    "/{sop_id}/versions",
    response_model=SopVersionListResponse,
    summary="List SOP versions",
    description="Returns current and historical SOP versions after department-scope permission filtering.",
)
def list_sop_versions(
    sop_id: str,
    auth_context: AuthContext = Depends(get_current_auth_context),
    sop_version_service: SopVersionService = Depends(get_sop_version_service),
) -> SopVersionListResponse:
    return sop_version_service.list_versions(sop_id, auth_context=auth_context)


@router.get(
    "/{sop_id}/versions/{version}",
    response_model=SopVersionDetailResponse,
    summary="Get SOP version detail",
    description="Returns a single SOP version with content and source citations after department-scope permission filtering.",
)
def get_sop_version_detail(
    sop_id: str,
    version: int,
    auth_context: AuthContext = Depends(get_current_auth_context),
    sop_version_service: SopVersionService = Depends(get_sop_version_service),
) -> SopVersionDetailResponse:
    return sop_version_service.get_version_detail(sop_id, version, auth_context=auth_context)


@router.get(
    "/{sop_id}/preview",
    response_model=SopPreviewResponse,
    summary="Get SOP preview",
    description="Returns SOP preview content or preview file URL after department-scope permission filtering.",
)
def get_sop_preview(
    sop_id: str,
    auth_context: AuthContext | None = Depends(get_optional_auth_context),
    sop_service: SopService = Depends(get_sop_service),
) -> SopPreviewResponse:
    return sop_service.get_sop_preview(sop_id, auth_context=auth_context)


@router.get(
    "/{sop_id}/preview/file",
    summary="Get SOP preview file",
    description="Streams SOP HTML/PDF preview file after department-scope permission filtering.",
)
def get_sop_preview_file(
    sop_id: str,
    auth_context: AuthContext | None = Depends(get_optional_auth_context),
    sop_service: SopService = Depends(get_sop_service),
) -> Response:
    payload = sop_service.get_sop_preview_file(sop_id, auth_context=auth_context)
    if payload.path is not None:
        return FileResponse(
            path=payload.path,
            media_type=payload.media_type,
            filename=payload.filename,
            headers={"Content-Disposition": build_content_disposition(payload.filename, disposition_type="inline")},
        )
    return Response(
        content=payload.content or b"",
        media_type=payload.media_type,
        headers={"Content-Disposition": build_content_disposition(payload.filename, disposition_type="inline")},
    )


@router.get(
    "/{sop_id}/download",
    summary="Download SOP asset",
    description="Downloads SOP asset in docx/pdf format after department-scope permission filtering.",
)
def download_sop(
    sop_id: str,
    format: SopDownloadFormat = Query(...),
    auth_context: AuthContext | None = Depends(get_optional_auth_context),
    sop_service: SopService = Depends(get_sop_service),
) -> Response:
    payload = sop_service.get_sop_download(sop_id, download_format=format, auth_context=auth_context)
    if payload.path is not None:
        return FileResponse(
            path=payload.path,
            media_type=payload.media_type,
            filename=payload.filename,
            headers={"Content-Disposition": build_content_disposition(payload.filename, disposition_type="attachment")},
        )
    return Response(
        content=payload.content or b"",
        media_type=payload.media_type,
        headers={"Content-Disposition": build_content_disposition(payload.filename, disposition_type="attachment")},
    )
