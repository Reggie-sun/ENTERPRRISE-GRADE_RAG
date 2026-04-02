"""对外资源引用脱敏工具。"""

from __future__ import annotations

import re

_SAFE_PREFIXES = (
    "asset://",
    "preview://",
    "downloads/",
    "document://",
    "document-preview://",
    "/api/",
)
_WINDOWS_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")


def build_document_resource_ref(document_id: str, *, resource: str = "source") -> str:
    normalized_document_id = (document_id or "unknown").strip() or "unknown"
    normalized_resource = (resource or "source").strip() or "source"
    return f"document://{normalized_document_id}/{normalized_resource}"


def sanitize_source_path(*, document_id: str, source_path: str | None, resource: str = "source") -> str:
    normalized = (source_path or "").strip()
    if normalized.startswith(_SAFE_PREFIXES):
        return normalized
    if normalized.startswith("/") or normalized.startswith("\\") or _WINDOWS_PATH_PATTERN.match(normalized):
        return build_document_resource_ref(document_id, resource=resource)
    if not normalized:
        return build_document_resource_ref(document_id, resource=resource)
    return normalized
