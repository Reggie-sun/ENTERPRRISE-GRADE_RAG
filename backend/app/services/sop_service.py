import html
import json
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException, status

from ..core.config import PROJECT_ROOT
from ..core.config import Settings, get_settings
from ..schemas.auth import AuthContext
from ..schemas.sop import (
    SopBootstrapData,
    SopDetailResponse,
    SopDownloadFormat,
    SopListResponse,
    SopPreviewResponse,
    SopRecord,
    SopStatus,
    SopSummary,
)
from ..schemas.sop_generation import SopDraftExportRequest
from .identity_service import IdentityService, get_identity_service


def _normalize_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MEDIA_TYPE = "application/pdf"
HTML_MEDIA_TYPE = "text/html; charset=utf-8"


@dataclass
class SopFilePayload:
    filename: str
    media_type: str
    path: Path | None = None
    content: bytes | None = None


@dataclass
class SopRenderableDocument:
    title: str
    department_label: str
    process_name: str | None
    scenario_name: str | None
    version_label: str | None
    source_document_label: str | None
    body_text: str


class SopService:  # v0.4 SOP 主数据服务：先承接独立对象、权限过滤和字段归一，不侵入文档入库链路。
    def __init__(
        self,
        settings: Settings | None = None,
        identity_service: IdentityService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.identity_service = identity_service or get_identity_service()
        self.bootstrap = self._load_bootstrap()
        self._validate_department_references(self.bootstrap.sops)

    def get_bootstrap(self) -> SopBootstrapData:
        return self.bootstrap

    def get_current_record(self, sop_id: str, *, auth_context: AuthContext | None = None) -> SopRecord:
        return self._get_authorized_sop_record(sop_id, auth_context=auth_context)

    def get_bootstrap_record(self, sop_id: str) -> SopRecord | None:
        normalized_sop_id = sop_id.strip()
        for record in self.bootstrap.sops:
            if record.sop_id == normalized_sop_id:
                return record
        return None

    def list_sops(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        department_id: str | None = None,
        process_name: str | None = None,
        scenario_name: str | None = None,
        sop_status: SopStatus | None = None,
        auth_context: AuthContext | None = None,
    ) -> SopListResponse:
        normalized_department_id = _normalize_optional_str(department_id)
        normalized_process_name = self._normalize_filter_value(process_name)
        normalized_scenario_name = self._normalize_filter_value(scenario_name)

        if (
            auth_context is not None
            and normalized_department_id is not None
            and normalized_department_id not in auth_context.accessible_department_ids
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to the requested department.",
            )

        filtered: list[SopRecord] = []
        for record in self._load_all_records():
            if auth_context is not None and not self._can_read_sop(record, auth_context):
                continue
            if normalized_department_id is not None and normalized_department_id not in record.department_ids:
                continue
            if normalized_process_name is not None and self._normalize_filter_value(record.process_name) != normalized_process_name:
                continue
            if normalized_scenario_name is not None and self._normalize_filter_value(record.scenario_name) != normalized_scenario_name:
                continue
            if sop_status is not None and record.status != sop_status:
                continue
            filtered.append(record)

        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        items = [self._to_summary(record) for record in filtered[start:end]]
        return SopListResponse(total=total, page=page, page_size=page_size, items=items)

    def get_sop(self, sop_id: str, *, auth_context: AuthContext | None = None) -> SopDetailResponse:
        record = self._get_authorized_sop_record(sop_id, auth_context=auth_context)
        return self._to_detail(record)

    def get_sop_preview(self, sop_id: str, *, auth_context: AuthContext | None = None) -> SopPreviewResponse:
        record = self._get_authorized_sop_record(sop_id, auth_context=auth_context)
        if record.preview_resource_path is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"SOP preview not found: {sop_id}")

        preview_file_url = None
        text_content = None
        content_type = "text/plain; charset=utf-8"

        if record.preview_resource_type == "text":
            text_content = record.preview_text_content
        elif record.preview_resource_type == "html":
            content_type = HTML_MEDIA_TYPE
            preview_file_url = f"/api/v1/sops/{record.sop_id}/preview/file"
        elif record.preview_resource_type == "pdf":
            content_type = "application/pdf"
            preview_file_url = f"/api/v1/sops/{record.sop_id}/preview/file"

        if text_content is None and preview_file_url is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"SOP preview content not found: {sop_id}")

        return SopPreviewResponse(
            sop_id=record.sop_id,
            title=record.title,
            preview_type=record.preview_resource_type,
            content_type=content_type,
            text_content=text_content,
            preview_file_url=preview_file_url,
            updated_at=record.updated_at,
        )

    def get_sop_preview_file(self, sop_id: str, *, auth_context: AuthContext | None = None) -> SopFilePayload:
        record = self._get_authorized_sop_record(sop_id, auth_context=auth_context)
        if record.preview_resource_path is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"SOP preview not found: {sop_id}")
        if record.preview_resource_type == "text":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Text preview does not support preview file streaming.",
            )

        if record.preview_resource_path.startswith("preview://"):
            renderable = self._build_renderable_from_record(record)
            content = self._build_html_preview_bytes(renderable) if record.preview_resource_type == "html" else self._build_pdf_bytes(renderable)
            filename = f"{record.sop_id}.{record.preview_resource_type}"
            media_type = HTML_MEDIA_TYPE if record.preview_resource_type == "html" else PDF_MEDIA_TYPE
            return SopFilePayload(filename=filename, media_type=media_type, content=content)

        local_path = self._resolve_local_asset_path(record.preview_resource_path)
        if not local_path.exists() or not local_path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"SOP preview file not found: {sop_id}")
        return SopFilePayload(
            filename=local_path.name,
            media_type=HTML_MEDIA_TYPE if record.preview_resource_type == "html" else PDF_MEDIA_TYPE,
            path=local_path,
        )

    def get_sop_download(
        self,
        sop_id: str,
        *,
        download_format: SopDownloadFormat,
        auth_context: AuthContext | None = None,
    ) -> SopFilePayload:
        record = self._get_authorized_sop_record(sop_id, auth_context=auth_context)
        resource_path = self._get_download_resource_path(record, download_format)
        if resource_path is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SOP download resource not found: {sop_id} ({download_format})",
            )

        filename = f"{record.sop_id}.{download_format}"
        media_type = DOCX_MEDIA_TYPE if download_format == "docx" else PDF_MEDIA_TYPE

        if resource_path.startswith("asset://"):
            renderable = self._build_renderable_from_record(record)
            if download_format == "docx":
                content = self._build_docx_bytes(renderable)
            else:
                content = self._build_pdf_bytes(renderable)
            return SopFilePayload(filename=filename, media_type=media_type, content=content)

        local_path = self._resolve_local_asset_path(resource_path)
        if not local_path.exists() or not local_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SOP download file not found: {sop_id} ({download_format})",
        )
        return SopFilePayload(filename=filename, media_type=media_type, path=local_path)

    def export_sop_draft(
        self,
        payload: SopDraftExportRequest,
        *,
        auth_context: AuthContext,
    ) -> SopFilePayload:
        title = payload.title.strip()
        body_text = payload.content.strip()
        if not title:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="title must not be blank.")
        if not body_text:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="content must not be blank.")

        department_id = _normalize_optional_str(payload.department_id) or auth_context.department.department_id
        if department_id not in auth_context.accessible_department_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to the requested department.",
            )

        department = self.identity_service.get_department(department_id)
        renderable = SopRenderableDocument(
            title=title,
            department_label=department.department_name,
            process_name=_normalize_optional_str(payload.process_name),
            scenario_name=_normalize_optional_str(payload.scenario_name),
            version_label=None,
            source_document_label=_normalize_optional_str(payload.source_document_id),
            body_text=body_text,
        )
        filename = f"{self._sanitize_export_filename(title)}.{payload.format}"
        if payload.format == "docx":
            return SopFilePayload(
                filename=filename,
                media_type=DOCX_MEDIA_TYPE,
                content=self._build_docx_bytes(renderable),
            )
        if payload.format == "pdf":
            return SopFilePayload(
                filename=filename,
                media_type=PDF_MEDIA_TYPE,
                content=self._build_pdf_bytes(renderable),
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported SOP draft export format: {payload.format}",
        )

    def _get_authorized_sop_record(self, sop_id: str, *, auth_context: AuthContext | None = None) -> SopRecord:
        normalized_sop_id = sop_id.strip()
        for record in self._load_all_records():
            if record.sop_id != normalized_sop_id:
                continue
            if auth_context is not None and not self._can_read_sop(record, auth_context):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have access to the requested SOP.",
                )
            return record

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"SOP not found: {sop_id}")

    def _load_bootstrap(self) -> SopBootstrapData:
        path = self.settings.sop_bootstrap_path
        if not path.exists():
            return SopBootstrapData()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return SopBootstrapData.model_validate(payload)

    def _load_managed_records(self) -> list[SopRecord]:
        self.settings.sop_record_dir.mkdir(parents=True, exist_ok=True)
        records: list[SopRecord] = []
        for path in sorted(self.settings.sop_record_dir.glob("*.json")):
            if not path.is_file() or path.name.startswith("."):
                continue
            records.append(SopRecord.model_validate_json(path.read_text(encoding="utf-8")))
        self._validate_department_references(records)
        return records

    def _load_all_records(self) -> list[SopRecord]:
        merged: dict[str, SopRecord] = {record.sop_id: record for record in self.bootstrap.sops}
        for record in self._load_managed_records():
            merged[record.sop_id] = record
        return list(merged.values())

    def _validate_department_references(self, records: list[SopRecord]) -> None:
        known_departments = {
            item.department_id: item
            for item in self.identity_service.get_bootstrap().departments
        }
        for record in records:
            for department_id in record.department_ids:
                department = known_departments.get(department_id)
                if department is None:
                    raise ValueError(f"Unknown department_id for SOP {record.sop_id}: {department_id}")
                if department.tenant_id != record.tenant_id:
                    raise ValueError(
                        f"SOP {record.sop_id} tenant_id {record.tenant_id} does not match department tenant_id {department.tenant_id}."
                    )

    def _can_read_sop(self, record: SopRecord, auth_context: AuthContext) -> bool:
        if auth_context.user.tenant_id != record.tenant_id:
            return False
        accessible_departments = set(auth_context.accessible_department_ids)
        return any(item in accessible_departments for item in record.department_ids)

    def _to_summary(self, record: SopRecord) -> SopSummary:
        department = self.identity_service.get_department(record.department_id)
        return SopSummary(
            sop_id=record.sop_id,
            title=record.title,
            department_id=record.department_id,
            department_name=department.department_name,
            process_name=record.process_name,
            scenario_name=record.scenario_name,
            version=record.version,
            status=record.status,
            preview_available=record.preview_resource_path is not None,
            downloadable_formats=self._downloadable_formats(record),
            updated_at=record.updated_at,
        )

    def _to_detail(self, record: SopRecord) -> SopDetailResponse:
        department = self.identity_service.get_department(record.department_id)
        return SopDetailResponse(
            sop_id=record.sop_id,
            title=record.title,
            tenant_id=record.tenant_id,
            department_id=record.department_id,
            department_name=department.department_name,
            process_name=record.process_name,
            scenario_name=record.scenario_name,
            version=record.version,
            status=record.status,
            preview_resource_path=record.preview_resource_path,
            preview_resource_type=record.preview_resource_type,
            download_docx_available=record.download_docx_resource_path is not None,
            download_pdf_available=record.download_pdf_resource_path is not None,
            tags=record.tags,
            source_document_id=record.source_document_id,
            created_by=record.created_by,
            updated_by=record.updated_by,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _downloadable_formats(record: SopRecord) -> list[str]:
        formats: list[str] = []
        if record.download_docx_resource_path is not None:
            formats.append("docx")
        if record.download_pdf_resource_path is not None:
            formats.append("pdf")
        return formats

    @staticmethod
    def _normalize_filter_value(value: str | None) -> str | None:
        normalized = _normalize_optional_str(value)
        if normalized is None:
            return None
        return normalized.casefold()

    @staticmethod
    def _get_download_resource_path(record: SopRecord, download_format: SopDownloadFormat) -> str | None:
        if download_format == "docx":
            return record.download_docx_resource_path
        if download_format == "pdf":
            return record.download_pdf_resource_path
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unsupported SOP download format: {download_format}")

    def _resolve_local_asset_path(self, resource_path: str) -> Path:
        asset_root = self.settings.sop_asset_dir.resolve()
        candidate = Path(resource_path).expanduser()
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (asset_root / candidate).resolve()
        if resolved != asset_root and asset_root not in resolved.parents:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"SOP asset path is outside allowed root: {resource_path}",
            )
        return resolved

    def _build_renderable_from_record(self, record: SopRecord) -> SopRenderableDocument:
        department = self.identity_service.get_department(record.department_id)
        return SopRenderableDocument(
            title=record.title,
            department_label=department.department_name,
            process_name=record.process_name,
            scenario_name=record.scenario_name,
            version_label=f"v{record.version}",
            source_document_label=record.source_document_id,
            body_text=record.preview_text_content or "No preview text available.",
        )

    @staticmethod
    def _build_docx_bytes(renderable: SopRenderableDocument) -> bytes:
        text_lines = SopService._compose_download_lines(renderable)
        document_xml = SopService._build_docx_document_xml(text_lines)

        content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""
        rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""
        core_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{html.escape(renderable.title)}</dc:title>
  <dc:creator>Enterprise RAG</dc:creator>
</cp:coreProperties>
"""
        app_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Enterprise RAG</Application>
</Properties>
"""

        buffer = BytesIO()
        with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types_xml)
            archive.writestr("_rels/.rels", rels_xml)
            archive.writestr("docProps/core.xml", core_xml)
            archive.writestr("docProps/app.xml", app_xml)
            archive.writestr("word/document.xml", document_xml)
        return buffer.getvalue()

    @staticmethod
    def _build_docx_document_xml(lines: list[str]) -> str:
        paragraphs = []
        for line in lines:
            safe_line = html.escape(line)
            paragraphs.append(
                f"<w:p><w:r><w:t xml:space=\"preserve\">{safe_line}</w:t></w:r></w:p>"
            )
        joined = "".join(paragraphs)
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:w10="urn:schemas-microsoft-com:office:word" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk" xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml" xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" mc:Ignorable="w14 wp14">
  <w:body>
    {joined}
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>
"""

    @staticmethod
    def _build_pdf_bytes(renderable: SopRenderableDocument) -> bytes:
        lines = [line.encode("ascii", errors="replace").decode("ascii") for line in SopService._compose_download_lines(renderable)]
        commands = ["BT", "/F1 12 Tf", "50 780 Td"]
        for index, line in enumerate(lines[:20]):
            escaped_line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            if index > 0:
                commands.append("0 -18 Td")
            commands.append(f"({escaped_line}) Tj")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1")

        objects = [
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            b"2 0 obj << /Type /Pages /Count 1 /Kids [3 0 R] >> endobj\n",
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
            b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
            f"5 0 obj << /Length {len(stream)} >> stream\n".encode("ascii") + stream + b"\nendstream endobj\n",
        ]

        buffer = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for payload in objects:
            offsets.append(len(buffer))
            buffer.extend(payload)
        xref_offset = len(buffer)
        buffer.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
        buffer.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            buffer.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        buffer.extend(
            (
                f"trailer << /Size {len(offsets)} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF"
            ).encode("ascii")
        )
        return bytes(buffer)

    @staticmethod
    def _build_html_preview_bytes(renderable: SopRenderableDocument) -> bytes:
        body_lines = []
        for line in SopService._compose_download_lines(renderable):
            body_lines.append(f"<p>{html.escape(line)}</p>")
        body = "\n".join(body_lines)
        payload = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <title>{html.escape(renderable.title)}</title>
    <style>
      body {{ font-family: 'Microsoft YaHei', sans-serif; margin: 32px; color: #17202a; line-height: 1.7; }}
      h1 {{ margin-bottom: 20px; }}
      p {{ margin: 0 0 12px; }}
    </style>
  </head>
  <body>
    <h1>{html.escape(renderable.title)}</h1>
    {body}
  </body>
</html>
"""
        return payload.encode("utf-8")

    @staticmethod
    def _compose_download_lines(renderable: SopRenderableDocument) -> list[str]:
        lines = [renderable.title]
        lines.append(f"Department: {renderable.department_label}")
        lines.append(f"Process: {renderable.process_name or '-'}")
        lines.append(f"Scenario: {renderable.scenario_name or '-'}")
        if renderable.version_label:
            lines.append(f"Version: {renderable.version_label}")
        if renderable.source_document_label:
            lines.append(f"Source Document: {renderable.source_document_label}")
        lines.append("")
        preview_lines = renderable.body_text.splitlines() or ["No preview text available."]
        return [*lines, *preview_lines]

    @staticmethod
    def _sanitize_export_filename(value: str) -> str:
        normalized = value.strip()
        safe = []
        for char in normalized:
            if char in '\\/:*?"<>|':
                safe.append("-")
            elif char.isspace():
                safe.append("_")
            else:
                safe.append(char)
        return "".join(safe).strip("._") or "sop_draft"


@lru_cache
def get_sop_service() -> SopService:
    return SopService()
