"""SOP 版本管理服务模块。处理 SOP 的版本创建、查询和回滚。"""
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status

from ..core.config import Settings, get_settings
from ..schemas.auth import AuthContext
from ..schemas.sop import SopRecord
from ..schemas.sop_generation import SopGenerationCitation
from ..schemas.sop_version import (
    SopSaveRequest,
    SopSaveResponse,
    SopVersionDetailResponse,
    SopVersionListResponse,
    SopVersionRecord,
    SopVersionSummary,
)
from .identity_service import IdentityService, get_identity_service
from .sop_service import SopService, get_sop_service


def _normalize_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


class SopVersionService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        identity_service: IdentityService | None = None,
        sop_service: SopService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.identity_service = identity_service or get_identity_service()
        self.sop_service = sop_service or get_sop_service()

    def save_sop(self, request: SopSaveRequest, *, auth_context: AuthContext) -> SopSaveResponse:
        if auth_context.user.role_id == "employee":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Current role cannot save SOPs.")

        existing_record = None
        normalized_sop_id = _normalize_optional_str(request.sop_id)
        if normalized_sop_id is not None:
            existing_record = self.sop_service.get_current_record(normalized_sop_id, auth_context=auth_context)

        target_department_id = _normalize_optional_str(request.department_id)
        if existing_record is not None:
            target_department_id = existing_record.department_id
            if request.department_id and request.department_id != existing_record.department_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="department_id cannot be changed when saving a new version of an existing SOP.",
                )
        elif target_department_id is None:
            target_department_id = auth_context.department.department_id

        if target_department_id not in auth_context.accessible_department_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot save SOPs outside your accessible departments.",
            )
        department = self.identity_service.get_department(target_department_id)

        sop_id = normalized_sop_id or self._generate_sop_id(target_department_id)
        version = (existing_record.version + 1) if existing_record is not None else 1
        now = datetime.now(timezone.utc)
        created_at = existing_record.created_at if existing_record is not None else now
        created_by = existing_record.created_by if existing_record is not None else auth_context.user.user_id
        process_name = _normalize_optional_str(request.process_name) or (existing_record.process_name if existing_record else None)
        scenario_name = _normalize_optional_str(request.scenario_name) or (existing_record.scenario_name if existing_record else None)
        tags = self._normalize_tags(request.tags or (existing_record.tags if existing_record else []))
        source_document_id = request.citations[0].document_id if request.citations else (existing_record.source_document_id if existing_record else None)

        current_record = SopRecord(
            sop_id=sop_id,
            tenant_id=auth_context.user.tenant_id,
            title=request.title.strip(),
            department_id=department.department_id,
            department_ids=[department.department_id],
            process_name=process_name,
            scenario_name=scenario_name,
            version=version,
            status=request.status,
            preview_resource_path=f"preview://saved/{sop_id}/v{version}",
            preview_resource_type="text",
            preview_text_content=request.content.strip(),
            download_docx_resource_path=f"asset://saved/{sop_id}/v{version}/docx",
            download_pdf_resource_path=f"asset://saved/{sop_id}/v{version}/pdf",
            tags=tags,
            source_document_id=source_document_id,
            created_by=created_by,
            updated_by=auth_context.user.user_id,
            created_at=created_at,
            updated_at=now,
        )
        version_record = SopVersionRecord(
            sop_id=sop_id,
            version=version,
            tenant_id=current_record.tenant_id,
            title=current_record.title,
            department_id=current_record.department_id,
            department_ids=current_record.department_ids,
            process_name=current_record.process_name,
            scenario_name=current_record.scenario_name,
            topic=_normalize_optional_str(request.topic),
            status=current_record.status,
            content=request.content.strip(),
            request_mode=request.request_mode,
            generation_mode=request.generation_mode.strip() or "manual",
            citations=request.citations,
            tags=tags,
            created_by=auth_context.user.user_id,
            updated_by=auth_context.user.user_id,
            created_at=now,
            updated_at=now,
        )

        self._write_json(self._record_path(sop_id), current_record)
        self._write_json(self._version_path(sop_id, version), version_record)
        return SopSaveResponse(
            sop_id=sop_id,
            version=version,
            status=current_record.status,
            title=current_record.title,
            saved_at=now,
        )

    def list_versions(self, sop_id: str, *, auth_context: AuthContext) -> SopVersionListResponse:
        current_record = self.sop_service.get_current_record(sop_id, auth_context=auth_context)
        versions = self._build_version_view(sop_id, current_record)
        return SopVersionListResponse(
            sop_id=current_record.sop_id,
            current_version=current_record.version,
            items=[
                SopVersionSummary(
                    sop_id=item.sop_id,
                    version=item.version,
                    title=item.title,
                    status=item.status,
                    generation_mode=item.generation_mode,
                    request_mode=item.request_mode,
                    citations_count=len(item.citations),
                    created_by=item.created_by,
                    updated_by=item.updated_by,
                    updated_at=item.updated_at,
                    is_current=item.version == current_record.version,
                )
                for item in versions
            ],
        )

    def get_version_detail(self, sop_id: str, version: int, *, auth_context: AuthContext) -> SopVersionDetailResponse:
        current_record = self.sop_service.get_current_record(sop_id, auth_context=auth_context)
        versions = self._build_version_view(sop_id, current_record)
        for item in versions:
            if item.version != version:
                continue
            return SopVersionDetailResponse(
                sop_id=item.sop_id,
                version=item.version,
                title=item.title,
                tenant_id=item.tenant_id,
                department_id=item.department_id,
                process_name=item.process_name,
                scenario_name=item.scenario_name,
                topic=item.topic,
                status=item.status,
                content=item.content,
                request_mode=item.request_mode,
                generation_mode=item.generation_mode,
                citations=item.citations,
                tags=item.tags,
                created_by=item.created_by,
                updated_by=item.updated_by,
                created_at=item.created_at,
                updated_at=item.updated_at,
                is_current=item.version == current_record.version,
            )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"SOP version not found: {sop_id} v{version}")

    def _build_version_view(self, sop_id: str, current_record: SopRecord) -> list[SopVersionRecord]:
        managed_versions = {item.version: item for item in self._load_managed_versions(sop_id)}
        bootstrap_record = self.sop_service.get_bootstrap_record(sop_id)

        if current_record.version not in managed_versions:
            managed_versions[current_record.version] = self._to_version_record(current_record, request_mode=None, generation_mode="saved_current")
        if bootstrap_record is not None and bootstrap_record.version not in managed_versions:
            managed_versions[bootstrap_record.version] = self._to_version_record(bootstrap_record, request_mode=None, generation_mode="bootstrap")

        return sorted(managed_versions.values(), key=lambda item: item.version, reverse=True)

    def _load_managed_versions(self, sop_id: str) -> list[SopVersionRecord]:
        self.settings.sop_version_dir.mkdir(parents=True, exist_ok=True)
        pattern = f"{sop_id}__v*.json"
        records: list[SopVersionRecord] = []
        for path in sorted(self.settings.sop_version_dir.glob(pattern)):
            if not path.is_file() or path.name.startswith("."):
                continue
            records.append(SopVersionRecord.model_validate_json(path.read_text(encoding="utf-8")))
        return records

    @staticmethod
    def _to_version_record(record: SopRecord, *, request_mode, generation_mode: str) -> SopVersionRecord:
        return SopVersionRecord(
            sop_id=record.sop_id,
            version=record.version,
            tenant_id=record.tenant_id,
            title=record.title,
            department_id=record.department_id,
            department_ids=record.department_ids,
            process_name=record.process_name,
            scenario_name=record.scenario_name,
            topic=None,
            status=record.status,
            content=record.preview_text_content or "",
            request_mode=request_mode,
            generation_mode=generation_mode,
            citations=[],
            tags=record.tags,
            created_by=record.created_by,
            updated_by=record.updated_by,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _normalize_tags(tags: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in tags:
            candidate = item.strip()
            if candidate and candidate not in normalized:
                normalized.append(candidate)
        return normalized

    @staticmethod
    def _generate_sop_id(department_id: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"sop_{department_id}_{timestamp}_{uuid4().hex[:8]}"

    def _record_path(self, sop_id: str) -> Path:
        return self.settings.sop_record_dir / f"{sop_id}.json"

    def _version_path(self, sop_id: str, version: int) -> Path:
        return self.settings.sop_version_dir / f"{sop_id}__v{version}.json"

    @staticmethod
    def _write_json(path: Path, model: SopRecord | SopVersionRecord) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(model.model_dump_json(indent=2), encoding="utf-8")


@lru_cache
def get_sop_version_service() -> SopVersionService:
    return SopVersionService()
