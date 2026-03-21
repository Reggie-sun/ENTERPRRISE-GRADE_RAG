from datetime import datetime, timezone
from pathlib import Path

from backend.app.schemas.document import DocumentRecord, IngestJobRecord
from backend.app.tools.postgres_data_backfill import build_asset_rows, build_chunk_rows, build_document_version_rows


def _build_document(doc_id: str) -> DocumentRecord:
    now = datetime.now(timezone.utc)
    return DocumentRecord(
        doc_id=doc_id,
        tenant_id="wl",
        file_name=f"{doc_id}.txt",
        file_hash=f"hash-{doc_id}",
        source_type="txt",
        department_ids=[],
        role_ids=[],
        owner_id=None,
        visibility="private",
        classification="internal",
        tags=[],
        source_system=None,
        status="active",
        current_version=1,
        latest_job_id=f"job-{doc_id}",
        storage_path=f"/tmp/{doc_id}.txt",
        created_by="tester",
        created_at=now,
        updated_at=now,
    )


def _build_job(job_id: str, doc_id: str) -> IngestJobRecord:
    now = datetime.now(timezone.utc)
    return IngestJobRecord(
        job_id=job_id,
        doc_id=doc_id,
        version=1,
        file_name=f"{doc_id}.txt",
        status="completed",
        stage="completed",
        progress=100,
        retry_count=0,
        error_code=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def test_build_document_version_rows_counts_chunk_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "chunks").mkdir(parents=True, exist_ok=True)
    (data_dir / "parsed").mkdir(parents=True, exist_ok=True)
    (data_dir / "chunks" / "doc_001.json").write_text(
        '[{"chunk_id":"c1","document_id":"doc_001","chunk_index":0,"text":"hello"}]',
        encoding="utf-8",
    )
    (data_dir / "parsed" / "doc_001.txt").write_text("hello", encoding="utf-8")

    rows = build_document_version_rows(data_dir, [_build_document("doc_001")])

    assert len(rows) == 1
    assert rows[0]["chunk_count"] == 1
    assert rows[0]["vector_count"] == 0
    assert str(rows[0]["parsed_path"]).endswith("doc_001.txt")


def test_build_chunk_rows_uses_document_acl_fields(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "chunks").mkdir(parents=True, exist_ok=True)
    (data_dir / "parsed").mkdir(parents=True, exist_ok=True)
    (data_dir / "chunks" / "doc_001.json").write_text(
        '[{"chunk_id":"c1","document_id":"doc_001","chunk_index":3,"text":"hello","char_start":1,"char_end":5}]',
        encoding="utf-8",
    )

    document = _build_document("doc_001")
    rows = build_chunk_rows(data_dir, {"doc_001": document})

    assert len(rows) == 1
    assert rows[0]["doc_id"] == "doc_001"
    assert rows[0]["tenant_id"] == "wl"
    assert rows[0]["chunk_index"] == 3
    assert rows[0]["content"] == "hello"
    assert rows[0]["visibility"] == "private"


def test_build_asset_rows_covers_all_data_subdirs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    for child in ("documents", "jobs", "parsed", "chunks", "uploads"):
        (data_dir / child).mkdir(parents=True, exist_ok=True)

    document = _build_document("doc_001")
    job = _build_job("job_001", "doc_001")

    (data_dir / "documents" / "doc_001.json").write_text(document.model_dump_json(), encoding="utf-8")
    (data_dir / "jobs" / "job_001.json").write_text(job.model_dump_json(), encoding="utf-8")
    (data_dir / "parsed" / "doc_001.txt").write_text("parsed", encoding="utf-8")
    (data_dir / "chunks" / "doc_001.json").write_text(
        '[{"chunk_id":"c1","document_id":"doc_001","chunk_index":0,"text":"hello"}]',
        encoding="utf-8",
    )
    (data_dir / "uploads" / "doc_001__manual.txt").write_text("upload", encoding="utf-8")

    rows = build_asset_rows(data_dir, {"doc_001": document}, {"job_001": job})
    kinds = {row.kind for row in rows}

    assert len(rows) == 5
    assert kinds == {"document_json", "job_json", "parsed_text", "chunk_json", "upload_file"}
    upload_row = next(row for row in rows if row.kind == "upload_file")
    assert upload_row.doc_id == "doc_001"
    assert upload_row.binary_content == b"upload"
    assert upload_row.text_content == "upload"


def test_build_asset_rows_skips_binary_content_when_file_exceeds_limit(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)

    document = _build_document("doc_001")
    job = _build_job("job_001", "doc_001")
    (data_dir / "uploads" / "doc_001__manual.bin").write_bytes(b"x" * 32)

    rows = build_asset_rows(
        data_dir,
        {"doc_001": document},
        {"job_001": job},
        store_binary_enabled=True,
        binary_max_bytes=8,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.size_bytes == 32
    assert row.binary_content is None
    assert row.text_content is None
    assert row.metadata["binary_stored"] is False
    assert row.metadata["binary_skip_reason"] == "size_limit"
    assert row.metadata["text_stored"] is False
    assert row.metadata["text_skip_reason"] == "size_limit"


def test_build_asset_rows_skips_binary_when_disabled_but_keeps_small_text(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)

    document = _build_document("doc_001")
    job = _build_job("job_001", "doc_001")
    (data_dir / "uploads" / "doc_001__note.txt").write_text("small text", encoding="utf-8")

    rows = build_asset_rows(
        data_dir,
        {"doc_001": document},
        {"job_001": job},
        store_binary_enabled=False,
        binary_max_bytes=1024,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.binary_content is None
    assert row.text_content == "small text"
    assert row.metadata["binary_stored"] is False
    assert row.metadata["binary_skip_reason"] == "disabled"
    assert row.metadata["text_stored"] is True
    assert row.metadata["text_skip_reason"] is None
