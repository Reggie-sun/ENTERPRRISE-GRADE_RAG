"""检索权限策略模块。

负责检索专用权限判断和部门优先 scope 构造，
与 DocumentService 的 direct-read / manage 权限逻辑解耦。

核心类:
    RetrievalScopePolicy — 检索权限策略，提供 retrievability map 和 department priority scope。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..core.config import Settings
from ..schemas.auth import AuthContext
from ..schemas.document import DocumentRecord

if TYPE_CHECKING:
    from ..db.postgres_metadata_store import PostgresMetadataStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DepartmentPriorityRetrievalScope:
    """部门优先检索作用域。

    用于非全局角色用户的分阶段检索：
    - department_document_ids: 本部门文档 ID 列表（第一阶段检索范围）
    - global_document_ids: 补充池文档 ID 列表（第二阶段，仅本部门不足时检索）

    参见 RetrievalService._collect_department_priority_candidates() 中的分阶段召回逻辑。
    """

    department_document_ids: list[str]
    global_document_ids: list[str]


class _DocumentRecordProvider(Protocol):
    """最低限度的文档记录访问协议，供 RetrievalScopePolicy 消费。"""

    def load_document_record(self, doc_id: str) -> DocumentRecord: ...
    def list_document_records(self) -> list[DocumentRecord]: ...


class RetrievalScopePolicy:
    """检索权限策略。

    负责：
    1. 检索专用可读性判断（不做部门隔离，只检查租户边界 + role visibility）
    2. 批量 retrievability map
    3. 部门优先检索 scope 构造

    与 DocumentService._can_read_document 的区别：
    - _can_read_document 做部门隔离过滤（用于详情/预览/下载）
    - _can_retrieve_document 不做部门隔离（让同租户跨部门文档能进入检索补充池）
    """

    def __init__(
        self,
        settings: Settings,
        *,
        record_provider: _DocumentRecordProvider | None = None,
        metadata_store: PostgresMetadataStore | None = None,
    ) -> None:
        self.settings = settings
        self.metadata_store = metadata_store
        self._record_provider = record_provider

    # ===== 单文档检索可读性 =====

    def is_document_retrievable(self, doc_id: str, auth_context: AuthContext | None) -> bool:
        """检索专用可读性检查。

        与 direct-read 的区别：
        - 不做部门隔离过滤
        - 只检查租户边界 + role visibility
        目的是让同租户跨部门文档能进入检索补充池。
        """
        if auth_context is None:
            return True
        try:
            record = self._load_document_record(doc_id)
        except Exception:
            return False
        return self._can_retrieve_document(record, auth_context)

    # ===== 批量检索可读性 =====

    def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
        """批量检索专用可读性检查。"""
        normalized_doc_ids = [doc_id.strip() for doc_id in doc_ids if doc_id and doc_id.strip()]
        if not normalized_doc_ids:
            return {}
        if auth_context is None:
            return {doc_id: True for doc_id in normalized_doc_ids}

        if self.metadata_store is not None:
            records = self.metadata_store.load_documents(normalized_doc_ids)
            return {
                doc_id: self._can_retrieve_document(record, auth_context)
                for doc_id, record in records.items()
            }

        retrievability: dict[str, bool] = {}
        for doc_id in normalized_doc_ids:
            try:
                record = self._load_document_record(doc_id)
            except Exception:
                retrievability[doc_id] = False
                continue
            retrievability[doc_id] = self._can_retrieve_document(record, auth_context)
        return retrievability

    # ===== 部门优先检索 scope =====

    def build_department_priority_retrieval_scope(
        self,
        auth_context: AuthContext | None,
    ) -> DepartmentPriorityRetrievalScope | None:
        """构建部门优先检索作用域（供 retrieval_service 分阶段召回使用）。

        对非全局角色用户，将所有可检索文档分为两个池：
        - department_document_ids：本部门文档（第一阶段检索范围）
        - global_document_ids：补充池文档（第二阶段，仅本部门不足时检索）

        补充池条件（满足任一即可进入）：
        - department_query_isolation_enabled=False 时：所有同租户可检索文档
        - department_query_isolation_enabled=True 时：
          a) visibility="public" 的跨部门文档（兼容现有公共文档）
          b) 当前用户部门在该文档的 retrieval_department_ids 中的跨部门文档（定向授权）

        全局角色（sys_admin / data_scope=global）返回 None，不走部门优先逻辑。
        """
        if auth_context is None:
            return None
        if auth_context.role.data_scope == "global":
            return None

        current_department_id = auth_context.department.department_id
        department_document_ids: list[str] = []
        global_document_ids: list[str] = []

        for record in self._list_document_records():
            if record.status == "deleted":
                continue
            # 使用检索专用可读性检查（不做部门隔离过滤）
            if not self._can_retrieve_document(record, auth_context):
                continue

            record_departments = self._normalize_department_scope(record.department_ids, record.department_id)
            is_department_match = current_department_id in record_departments if record_departments else False

            if is_department_match:
                department_document_ids.append(record.doc_id)
            else:
                # 补充池：非本部门的同租户可检索文档
                if not self.settings.department_query_isolation_enabled:
                    global_document_ids.append(record.doc_id)
                elif record.visibility == "public":
                    # 兼容现有 public 文档
                    global_document_ids.append(record.doc_id)
                elif current_department_id in record.retrieval_department_ids:
                    # 定向跨部门授权：当前用户部门在文档的检索可见部门范围内
                    global_document_ids.append(record.doc_id)

        return DepartmentPriorityRetrievalScope(
            department_document_ids=department_document_ids,
            global_document_ids=global_document_ids,
        )

    # ===== 内部辅助 =====

    @staticmethod
    def _can_retrieve_document(record: DocumentRecord, auth_context: AuthContext) -> bool:
        """检索专用可读性检查。

        与 _can_read_document 的关键区别：
        - 不做部门隔离检查
        - 只检查租户边界 + role visibility
        目的：让同租户跨部门文档能进入检索补充池。

        直接访问接口（详情/下载/预览）继续使用 _can_read_document，
        保持部门隔离不受检索补充池影响。
        """
        if record.tenant_id != auth_context.user.tenant_id:
            return False
        if auth_context.role.data_scope == "global":
            return True
        if record.visibility == "role" and record.role_ids and auth_context.user.role_id not in record.role_ids:
            return False
        return True  # 注意：这里不做部门隔离检查

    @staticmethod
    def _normalize_department_scope(values: list[str] | None, primary_department_id: str | None) -> list[str]:
        """标准化部门范围：将 primary_department_id 放首位，去重。"""
        normalized: list[str] = []
        if primary_department_id and primary_department_id not in normalized:
            normalized.append(primary_department_id)
        for item in values or []:
            if item and item not in normalized:
                normalized.append(item)
        return normalized

    def _load_document_record(self, doc_id: str) -> DocumentRecord:
        """按 ID 加载文档记录。"""
        if self.metadata_store is not None:
            record = self.metadata_store.load_document(doc_id)
            if record is None:
                raise LookupError(f"Document not found: {doc_id}")
            return record
        if self._record_provider is not None:
            return self._record_provider.load_document_record(doc_id)
        raise RuntimeError("No record provider or metadata store configured for RetrievalScopePolicy")

    def _list_document_records(self) -> list[DocumentRecord]:
        """列出所有文档记录。"""
        if self.metadata_store is not None:
            return self.metadata_store.list_documents()
        if self._record_provider is not None:
            return self._record_provider.list_document_records()
        raise RuntimeError("No record provider or metadata store configured for RetrievalScopePolicy")
