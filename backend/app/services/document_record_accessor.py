"""文档记录访问适配层。

为检索侧提供稳定、窄接口的 DocumentRecord 读取能力，
避免 RetrievalScopePolicy 直接依赖 DocumentService 的私有方法。
"""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

from ..schemas.document import DocumentRecord

if TYPE_CHECKING:
    from .document_service import DocumentService


class DocumentRecordAccessor(Protocol):
    """检索侧消费的最小文档记录访问接口。"""

    def load_document_record(self, doc_id: str) -> DocumentRecord: ...

    def list_document_records(self) -> list[DocumentRecord]: ...


class DocumentServiceRecordAccessor:
    """基于 DocumentService 的窄接口适配器。"""

    def __init__(self, document_service: "DocumentService") -> None:
        self._document_service = document_service

    def load_document_record(self, doc_id: str) -> DocumentRecord:
        return self._document_service.load_document_record(doc_id)

    def list_document_records(self) -> list[DocumentRecord]:
        return self._document_service.list_document_records()
