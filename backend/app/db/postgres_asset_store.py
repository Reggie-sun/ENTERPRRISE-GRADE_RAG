"""PostgreSQL 资产存储实现。将二进制文件存储到数据库。"""
from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from .postgres_metadata_store import PostgresMetadataStore

ASSET_URI_PREFIX = "asset://"


class PostgresAssetStore:
    """Persist binary upload assets into PostgreSQL for cross-host access."""

    REQUIRED_TABLES: tuple[str, ...] = ("rag_data_assets",)

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.psycopg_dsn = PostgresMetadataStore._normalize_psycopg_dsn(dsn)

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
                "PostgreSQL asset tables are missing: "
                f"{', '.join(missing)}. "
                "Run `npx prisma db push --schema prisma/schema.prisma` first."
            )

    def upsert_binary_asset(
        self,
        *,
        asset_key: str,
        relative_path: str,
        file_name: str,
        content: bytes,
        doc_id: str | None = None,
        job_id: str | None = None,
        mime_type: str | None = None,
        kind: str = "upload",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        with psycopg.connect(self.psycopg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.rag_data_assets (
                        "id", "assetKey", "docId", "jobId", "kind", "relativePath", "fileName", "mimeType",
                        "sizeBytes", "sha256", "textContent", "binaryContent", "metadata", "createdAt", "updatedAt"
                    ) VALUES (
                        %(id)s, %(asset_key)s, %(doc_id)s, %(job_id)s, %(kind)s, %(relative_path)s, %(file_name)s, %(mime_type)s,
                        %(size_bytes)s, %(sha256)s, NULL, %(binary_content)s, %(metadata)s, NOW(), NOW()
                    )
                    ON CONFLICT ("assetKey") DO UPDATE SET
                        "docId" = EXCLUDED."docId",
                        "jobId" = EXCLUDED."jobId",
                        "kind" = EXCLUDED."kind",
                        "relativePath" = EXCLUDED."relativePath",
                        "fileName" = EXCLUDED."fileName",
                        "mimeType" = EXCLUDED."mimeType",
                        "sizeBytes" = EXCLUDED."sizeBytes",
                        "sha256" = EXCLUDED."sha256",
                        "binaryContent" = EXCLUDED."binaryContent",
                        "metadata" = EXCLUDED."metadata",
                        "updatedAt" = NOW()
                    """,
                    {
                        "id": PostgresMetadataStore._stable_uuid("rag-data-asset", asset_key),
                        "asset_key": asset_key,
                        "doc_id": doc_id,
                        "job_id": job_id,
                        "kind": kind,
                        "relative_path": relative_path,
                        "file_name": file_name,
                        "mime_type": mime_type,
                        "size_bytes": len(content),
                        "sha256": PostgresMetadataStore._sha256_hex(content),
                        "binary_content": content,
                        "metadata": Json(metadata or {}),
                    },
                )
            conn.commit()
        return self.build_asset_uri(asset_key)

    def load_binary_asset(self, asset_uri: str) -> tuple[bytes, str, str | None, int]:
        asset_key = self.parse_asset_uri(asset_uri)
        with psycopg.connect(self.psycopg_dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT "fileName", "mimeType", "sizeBytes", "binaryContent"
                    FROM public.rag_data_assets
                    WHERE "assetKey" = %s
                    """,
                    (asset_key,),
                )
                row = cur.fetchone()
        if row is None:
            raise FileNotFoundError(f"Asset not found: {asset_uri}")
        binary_content = row["binaryContent"]
        if binary_content is None:
            raise FileNotFoundError(f"Asset binary payload is missing: {asset_uri}")
        return bytes(binary_content), row["fileName"], row["mimeType"], int(row["sizeBytes"])

    def asset_exists(self, asset_uri: str) -> bool:
        asset_key = self.parse_asset_uri(asset_uri)
        with psycopg.connect(self.psycopg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT 1 FROM public.rag_data_assets WHERE "assetKey" = %s', (asset_key,))
                return cur.fetchone() is not None

    def get_asset_size(self, asset_uri: str) -> int:
        asset_key = self.parse_asset_uri(asset_uri)
        with psycopg.connect(self.psycopg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT "sizeBytes" FROM public.rag_data_assets WHERE "assetKey" = %s', (asset_key,))
                row = cur.fetchone()
        if row is None:
            return 0
        return int(row[0] or 0)

    @staticmethod
    def build_asset_uri(asset_key: str) -> str:
        return f"{ASSET_URI_PREFIX}{asset_key}"

    @staticmethod
    def is_asset_uri(storage_path: str) -> bool:
        return storage_path.startswith(ASSET_URI_PREFIX)

    @staticmethod
    def parse_asset_uri(asset_uri: str) -> str:
        if not PostgresAssetStore.is_asset_uri(asset_uri):
            raise ValueError(f"Unsupported asset uri: {asset_uri}")
        return asset_uri[len(ASSET_URI_PREFIX) :]
