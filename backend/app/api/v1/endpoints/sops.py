from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import FileResponse

from ....schemas.auth import AuthContext
from ....schemas.sop import SopDetailResponse, SopDownloadFormat, SopListResponse, SopPreviewResponse, SopStatus
from ....services.auth_service import get_optional_auth_context
from ....services.sop_service import SopService, get_sop_service

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
            headers={"Content-Disposition": f'inline; filename="{payload.filename}"'},
        )
    return Response(
        content=payload.content or b"",
        media_type=payload.media_type,
        headers={"Content-Disposition": f'inline; filename="{payload.filename}"'},
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
            headers={"Content-Disposition": f'attachment; filename="{payload.filename}"'},
        )
    return Response(
        content=payload.content or b"",
        media_type=payload.media_type,
        headers={"Content-Disposition": f'attachment; filename="{payload.filename}"'},
    )
