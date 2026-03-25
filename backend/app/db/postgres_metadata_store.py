from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from ..schemas.document import DocumentRecord, IngestJobRecord


class PostgresMetadataStore:
    """Persist document/job metadata into PostgreSQL tables created by Prisma."""

    REQUIRED_TABLES: tuple[str, ...] = ("rag_source_documents", "rag_ingest_jobs")

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.psycopg_dsn = self._normalize_psycopg_dsn(dsn)

    def ping(self) -> None:
        with psycopg.connect(self.psycopg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")

    def ensure_required_tables(self) -> None:
        missing: list[str] = []
        with psycopg.connect(self.psycopg_dsn) as conn:
            with conn.cursor() as cur:
                for table in self.REQUIRED_TABLES:
                    cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
                    result = cur.fetchone()
                    if result is None or result[0] is None:
                        missing.append(table)
        if missing:
            raise RuntimeError(
                "PostgreSQL metadata tables are missing: "
                f"{', '.join(missing)}. "
                "Run `npx prisma db push --schema prisma/schema.prisma` first."
            )

    def save_document(self, record: DocumentRecord) -> None:
        db_status = self._db_status_from_record(record.status)  # 数据库枚举暂不包含 deleted，写库前先做兼容映射。
        metadata_payload: dict[str, object] = {
            "department_id": record.department_id,
            "category_id": record.category_id,
            "uploaded_by": record.uploaded_by,
        }  # 新增主数据字段先落在 metadata JSON，避免强依赖库表结构变更。
        if record.status == "deleted":  # 仅删除状态写 deleted 标记，避免污染既有 metadata 断言与下游兼容逻辑。
            metadata_payload["deleted"] = True
        with psycopg.connect(self.psycopg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.rag_source_documents (
                        "id", "docId", "tenantId", "fileName", "fileHash", "sourceType",
                        "sourceSystem", "createdBy", "ownerId", "visibility", "classification",
                        "departmentIds", "roleIds", "tags", "namespace", "status",
                        "currentVersion", "latestJobId", "storagePath", "metadata",
                        "createdAt", "updatedAt"
                    ) VALUES (
                        %(id)s, %(doc_id)s, %(tenant_id)s, %(file_name)s, %(file_hash)s, %(source_type)s,
                        %(source_system)s, %(created_by)s, %(owner_id)s, %(visibility)s, %(classification)s,
                        %(department_ids)s, %(role_ids)s, %(tags)s, %(namespace)s, %(status)s,
                        %(current_version)s, %(latest_job_id)s, %(storage_path)s, %(metadata)s,
                        %(created_at)s, %(updated_at)s
                    )
                    ON CONFLICT ("docId") DO UPDATE SET
                        "tenantId" = EXCLUDED."tenantId",
                        "fileName" = EXCLUDED."fileName",
                        "fileHash" = EXCLUDED."fileHash",
                        "sourceType" = EXCLUDED."sourceType",
                        "sourceSystem" = EXCLUDED."sourceSystem",
                        "createdBy" = EXCLUDED."createdBy",
                        "ownerId" = EXCLUDED."ownerId",
                        "visibility" = EXCLUDED."visibility",
                        "classification" = EXCLUDED."classification",
                        "departmentIds" = EXCLUDED."departmentIds",
                        "roleIds" = EXCLUDED."roleIds",
                        "tags" = EXCLUDED."tags",
                        "namespace" = EXCLUDED."namespace",
                        "status" = EXCLUDED."status",
                        "currentVersion" = EXCLUDED."currentVersion",
                        "latestJobId" = EXCLUDED."latestJobId",
                        "storagePath" = EXCLUDED."storagePath",
                        "metadata" = EXCLUDED."metadata",
                        "updatedAt" = EXCLUDED."updatedAt"
                    """,
                    {
                        "id": self._stable_uuid("rag-source-document", record.doc_id),
                        "doc_id": record.doc_id,
                        "tenant_id": record.tenant_id,
                        "file_name": record.file_name,
                        "file_hash": record.file_hash,
                        "source_type": record.source_type,
                        "source_system": record.source_system,
                        "created_by": record.created_by,
                        "owner_id": record.owner_id,
                        "visibility": record.visibility,
                        "classification": record.classification,
                        "department_ids": record.department_ids,
                        "role_ids": record.role_ids,
                        "tags": record.tags,
                        "namespace": "default",
                        "status": db_status,
                        "current_version": record.current_version,
                        "latest_job_id": record.latest_job_id,
                        "storage_path": record.storage_path,
                        "metadata": Json(metadata_payload),
                        "created_at": record.created_at,
                        "updated_at": record.updated_at,
                    },
                )

    def save_job(self, record: IngestJobRecord) -> None:
        with psycopg.connect(self.psycopg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.rag_ingest_jobs (
                        "id", "jobId", "docId", "version", "fileName", "status", "stage",
                        "progress", "retryCount", "errorCode", "errorMessage", "metadata",
                        "createdAt", "updatedAt"
                    ) VALUES (
                        %(id)s, %(job_id)s, %(doc_id)s, %(version)s, %(file_name)s, %(status)s, %(stage)s,
                        %(progress)s, %(retry_count)s, %(error_code)s, %(error_message)s, %(metadata)s,
                        %(created_at)s, %(updated_at)s
                    )
                    ON CONFLICT ("jobId") DO UPDATE SET
                        "docId" = EXCLUDED."docId",
                        "version" = EXCLUDED."version",
                        "fileName" = EXCLUDED."fileName",
                        "status" = EXCLUDED."status",
                        "stage" = EXCLUDED."stage",
                        "progress" = EXCLUDED."progress",
                        "retryCount" = EXCLUDED."retryCount",
                        "errorCode" = EXCLUDED."errorCode",
                        "errorMessage" = EXCLUDED."errorMessage",
                        "metadata" = EXCLUDED."metadata",
                        "updatedAt" = EXCLUDED."updatedAt"
                    """,
                    {
                        "id": self._stable_uuid("rag-ingest-job", record.job_id),
                        "job_id": record.job_id,
                        "doc_id": record.doc_id,
                        "version": record.version,
                        "file_name": record.file_name,
                        "status": record.status,
                        "stage": record.stage,
                        "progress": record.progress,
                        "retry_count": record.retry_count,
                        "error_code": record.error_code,
                        "error_message": record.error_message,
                        "metadata": None,
                        "created_at": record.created_at,
                        "updated_at": record.updated_at,
                    },
                )

    def load_document(self, doc_id: str) -> DocumentRecord | None:
        rows = self._fetchall(
            """
            SELECT
                "docId", "tenantId", "fileName", "fileHash", "sourceType",
                "departmentIds", "roleIds", "ownerId", "visibility", "classification",
                "tags", "sourceSystem", "status", "currentVersion", "latestJobId",
                "storagePath", "createdBy", "metadata", "createdAt", "updatedAt"
            FROM public.rag_source_documents
            WHERE "docId" = %(doc_id)s
            LIMIT 1
            """,
            {"doc_id": doc_id},
        )
        if not rows:
            return None
        return self._row_to_document(rows[0])

    def load_job(self, job_id: str) -> IngestJobRecord | None:
        rows = self._fetchall(
            """
            SELECT
                "jobId", "docId", "version", "fileName", "status", "stage",
                "progress", "retryCount", "errorCode", "errorMessage",
                "createdAt", "updatedAt"
            FROM public.rag_ingest_jobs
            WHERE "jobId" = %(job_id)s
            LIMIT 1
            """,
            {"job_id": job_id},
        )
        if not rows:
            return None
        return self._row_to_job(rows[0])

    def load_job_statuses(self, job_ids: list[str]) -> dict[str, str]:
        normalized_job_ids = [job_id.strip() for job_id in job_ids if job_id and job_id.strip()]
        if not normalized_job_ids:
            return {}

        rows = self._fetchall(
            """
            SELECT
                "jobId", "status"
            FROM public.rag_ingest_jobs
            WHERE "jobId" = ANY(%(job_ids)s)
            """,
            {"job_ids": normalized_job_ids},
        )
        return {str(row["jobId"]): str(row["status"]) for row in rows}

    def list_documents(self) -> list[DocumentRecord]:
        rows = self._fetchall(
            """
            SELECT
                "docId", "tenantId", "fileName", "fileHash", "sourceType",
                "departmentIds", "roleIds", "ownerId", "visibility", "classification",
                "tags", "sourceSystem", "status", "currentVersion", "latestJobId",
                "storagePath", "createdBy", "metadata", "createdAt", "updatedAt"
            FROM public.rag_source_documents
            ORDER BY "updatedAt" DESC
            """
        )
        return [self._row_to_document(row) for row in rows]

    def find_document_by_file_hash(self, file_hash: str, *, tenant_id: str | None = None) -> DocumentRecord | None:
        if tenant_id is None:
            rows = self._fetchall(
                """
                SELECT
                    "docId", "tenantId", "fileName", "fileHash", "sourceType",
                    "departmentIds", "roleIds", "ownerId", "visibility", "classification",
                    "tags", "sourceSystem", "status", "currentVersion", "latestJobId",
                    "storagePath", "createdBy", "metadata", "createdAt", "updatedAt"
                FROM public.rag_source_documents
                WHERE "fileHash" = %(file_hash)s
                ORDER BY "updatedAt" DESC
                LIMIT 1
                """,
                {"file_hash": file_hash},
            )
        else:
            rows = self._fetchall(
                """
                SELECT
                    "docId", "tenantId", "fileName", "fileHash", "sourceType",
                    "departmentIds", "roleIds", "ownerId", "visibility", "classification",
                    "tags", "sourceSystem", "status", "currentVersion", "latestJobId",
                    "storagePath", "createdBy", "metadata", "createdAt", "updatedAt"
                FROM public.rag_source_documents
                WHERE "fileHash" = %(file_hash)s AND "tenantId" = %(tenant_id)s
                ORDER BY "updatedAt" DESC
                LIMIT 1
                """,
                {"file_hash": file_hash, "tenant_id": tenant_id},
            )
        if not rows:
            return None
        return self._row_to_document(rows[0])

    def _fetchall(self, sql: str, params: dict[str, object] | None = None) -> list[dict[str, object]]:
        with psycopg.connect(self.psycopg_dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                return list(cur.fetchall())

    @staticmethod
    def _normalize_psycopg_dsn(dsn: str) -> str:
        parsed = urlsplit(dsn)
        if not parsed.query or "schema=" not in parsed.query:
            return dsn

        query_items = parse_qsl(parsed.query, keep_blank_values=True)
        schema_values = [value for key, value in query_items if key == "schema" and value.strip()]
        remaining_items = [(key, value) for key, value in query_items if key != "schema"]
        if not schema_values:
            normalized_query = urlencode(remaining_items, doseq=True)
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, normalized_query, parsed.fragment))

        schema = schema_values[-1].strip()
        if schema != "public":
            options_value = f"-c search_path={schema}"
            appended = False
            rewritten_items: list[tuple[str, str]] = []
            for key, value in remaining_items:
                if key == "options":
                    combined = f"{value} {options_value}".strip()
                    rewritten_items.append((key, combined))
                    appended = True
                else:
                    rewritten_items.append((key, value))
            if not appended:
                rewritten_items.append(("options", options_value))
            remaining_items = rewritten_items

        normalized_query = urlencode(remaining_items, doseq=True)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, normalized_query, parsed.fragment))

    @staticmethod
    def _stable_uuid(namespace: str, business_id: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"{namespace}:{business_id}"))

    @staticmethod
    def _as_str_list(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, tuple):
            return [str(item) for item in value]
        return [str(value)]

    def _row_to_document(self, row: dict[str, object]) -> DocumentRecord:
        metadata = row.get("metadata")
        metadata_map = metadata if isinstance(metadata, dict) else {}
        department_id = metadata_map.get("department_id")
        category_id = metadata_map.get("category_id")
        uploaded_by = metadata_map.get("uploaded_by")
        deleted_flag = bool(metadata_map.get("deleted"))  # deleted 通过 metadata 标记回读，避免依赖数据库枚举扩展。
        record_status = "deleted" if deleted_flag else str(row["status"])
        return DocumentRecord(
            doc_id=str(row["docId"]),
            tenant_id=str(row["tenantId"]),
            file_name=str(row["fileName"]),
            file_hash=str(row["fileHash"]),
            source_type=str(row["sourceType"]),
            department_id=None if department_id is None else str(department_id),
            department_ids=self._as_str_list(row.get("departmentIds")),
            category_id=None if category_id is None else str(category_id),
            role_ids=self._as_str_list(row.get("roleIds")),
            owner_id=None if row.get("ownerId") is None else str(row["ownerId"]),
            visibility=str(row["visibility"]),  # type: ignore[arg-type]
            classification=str(row["classification"]),  # type: ignore[arg-type]
            tags=self._as_str_list(row.get("tags")),
            source_system=None if row.get("sourceSystem") is None else str(row["sourceSystem"]),
            status=record_status,  # type: ignore[arg-type]
            current_version=int(row["currentVersion"]),
            latest_job_id="" if row.get("latestJobId") is None else str(row["latestJobId"]),
            storage_path=str(row["storagePath"]),
            uploaded_by=None if uploaded_by is None else str(uploaded_by),
            created_by=None if row.get("createdBy") is None else str(row["createdBy"]),
            created_at=row["createdAt"],  # type: ignore[arg-type]
            updated_at=row["updatedAt"],  # type: ignore[arg-type]
        )

    @staticmethod
    def _db_status_from_record(status: str) -> str:  # 把应用层文档状态映射成数据库允许的枚举值。
        if status == "deleted":  # 当前 schema 未扩展 deleted，先以 failed 落库并借 metadata 标记墓碑语义。
            return "failed"
        return status

    def _row_to_job(self, row: dict[str, object]) -> IngestJobRecord:
        return IngestJobRecord(
            job_id=str(row["jobId"]),
            doc_id=str(row["docId"]),
            version=int(row["version"]),
            file_name=str(row["fileName"]),
            status=str(row["status"]),  # type: ignore[arg-type]
            stage=str(row["stage"]),
            progress=int(row["progress"]),
            retry_count=int(row["retryCount"]),
            error_code=None if row.get("errorCode") is None else str(row["errorCode"]),  # type: ignore[arg-type]
            error_message=None if row.get("errorMessage") is None else str(row["errorMessage"]),
            created_at=row["createdAt"],  # type: ignore[arg-type]
            updated_at=row["updatedAt"],  # type: ignore[arg-type]
        )
