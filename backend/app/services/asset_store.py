from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterator

from ..core.config import Settings, get_postgres_metadata_dsn
from ..db.postgres_asset_store import PostgresAssetStore


@dataclass(frozen=True)
class MaterializedAsset:
    local_path: Path
    normalized_storage_path: str


class FilesystemAssetBackend:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def save_upload(self, *, target_name: str, content: bytes) -> str:
        target_path = self.settings.upload_dir / target_name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
        return str(target_path)

    @contextmanager
    def materialize_for_processing(self, storage_path: str) -> Iterator[MaterializedAsset]:
        resolved_path = self.resolve_storage_path(storage_path)
        if not resolved_path.exists():
            raise FileNotFoundError(f"Source file not found: {storage_path}")
        yield MaterializedAsset(local_path=resolved_path, normalized_storage_path=str(resolved_path))

    def resolve_storage_path(self, storage_path: str) -> Path:
        stored_path = Path(storage_path)
        if stored_path.exists():
            return stored_path
        fallback_path = self.settings.upload_dir / stored_path.name
        if fallback_path.exists():
            return fallback_path
        return stored_path

    def read_bytes(self, storage_path: str) -> bytes:
        resolved_path = self.resolve_storage_path(storage_path)
        if not resolved_path.exists():
            raise FileNotFoundError(f"Source file not found: {storage_path}")
        return resolved_path.read_bytes()

    def exists(self, storage_path: str) -> bool:
        return self.resolve_storage_path(storage_path).exists()

    def size_bytes(self, storage_path: str) -> int:
        resolved_path = self.resolve_storage_path(storage_path)
        if not resolved_path.exists():
            return 0
        return resolved_path.stat().st_size


class AssetStore:
    WRITE_BACKENDS = {"filesystem", "postgres"}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.filesystem = FilesystemAssetBackend(settings)
        self.write_backend = settings.asset_store_backend.strip().lower()
        if self.write_backend not in self.WRITE_BACKENDS:
            raise RuntimeError(
                f"Unsupported asset store backend: {settings.asset_store_backend}. "
                "Supported values: filesystem, postgres."
            )
        self._postgres_store: PostgresAssetStore | None = None
        if self.write_backend == "postgres":
            self._get_postgres_store()

    def save_upload(
        self,
        *,
        doc_id: str,
        target_name: str,
        file_name: str,
        content: bytes,
        mime_type: str | None = None,
        job_id: str | None = None,
    ) -> str:
        if self.write_backend == "postgres":
            postgres_store = self._get_postgres_store()
            asset_key = f"uploads/{target_name}"
            return postgres_store.upsert_binary_asset(
                asset_key=asset_key,
                relative_path=asset_key,
                file_name=file_name,
                content=content,
                doc_id=doc_id,
                job_id=job_id,
                mime_type=mime_type,
                kind="upload",
                metadata={"storage_backend": "postgres"},
            )
        return self.filesystem.save_upload(target_name=target_name, content=content)

    @contextmanager
    def materialize_for_processing(self, storage_path: str, *, file_name: str) -> Iterator[MaterializedAsset]:
        if PostgresAssetStore.is_asset_uri(storage_path):
            postgres_store = self._get_postgres_store()
            content, _, _, _ = postgres_store.load_binary_asset(storage_path)
            suffix = Path(file_name).suffix
            with NamedTemporaryFile(prefix="rag_asset_", suffix=suffix, delete=False) as temp_file:
                temp_file.write(content)
                temp_path = Path(temp_file.name)
            try:
                yield MaterializedAsset(local_path=temp_path, normalized_storage_path=storage_path)
            finally:
                temp_path.unlink(missing_ok=True)
            return

        with self.filesystem.materialize_for_processing(storage_path) as materialized:
            yield materialized

    def read_bytes(self, storage_path: str) -> bytes:
        if PostgresAssetStore.is_asset_uri(storage_path):
            postgres_store = self._get_postgres_store()
            content, _, _, _ = postgres_store.load_binary_asset(storage_path)
            return content
        return self.filesystem.read_bytes(storage_path)

    def exists(self, storage_path: str) -> bool:
        if PostgresAssetStore.is_asset_uri(storage_path):
            postgres_store = self._get_postgres_store()
            return postgres_store.asset_exists(storage_path)
        return self.filesystem.exists(storage_path)

    def size_bytes(self, storage_path: str) -> int:
        if PostgresAssetStore.is_asset_uri(storage_path):
            postgres_store = self._get_postgres_store()
            return postgres_store.get_asset_size(storage_path)
        return self.filesystem.size_bytes(storage_path)

    def can_serve_local_path(self, storage_path: str) -> bool:
        return not PostgresAssetStore.is_asset_uri(storage_path)

    def resolve_local_path(self, storage_path: str) -> Path:
        return self.filesystem.resolve_storage_path(storage_path)

    def _get_postgres_store(self) -> PostgresAssetStore:
        if self._postgres_store is not None:
            return self._postgres_store
        dsn = get_postgres_metadata_dsn(self.settings)
        if not dsn:
            raise RuntimeError("PostgreSQL asset storage requires DATABASE_URL or RAG_POSTGRES_METADATA_DSN.")
        store = PostgresAssetStore(dsn)
        store.ping()
        store.ensure_required_tables()
        self._postgres_store = store
        return store
