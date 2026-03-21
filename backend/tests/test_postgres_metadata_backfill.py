from datetime import datetime, timezone
from pathlib import Path

from backend.app.schemas.document import DocumentRecord, IngestJobRecord
from backend.app.tools.postgres_metadata_backfill import backfill_records, load_document_records, load_job_records


class _FakeMetadataStore:
    def __init__(self) -> None:
        self.saved_document_ids: list[str] = []
        self.saved_job_ids: list[str] = []

    def save_document(self, record: DocumentRecord) -> None:
        self.saved_document_ids.append(record.doc_id)

    def save_job(self, record: IngestJobRecord) -> None:
        self.saved_job_ids.append(record.job_id)


def _build_document_record(doc_id: str) -> DocumentRecord:
    now = datetime.now(timezone.utc)
    return DocumentRecord(
        doc_id=doc_id,
        tenant_id="wl",
        file_name=f"{doc_id}.txt",
        file_hash=f"hash_{doc_id}",
        source_type="txt",
        department_ids=["qa"],
        role_ids=["engineer"],
        owner_id="u001",
        visibility="department",
        classification="internal",
        tags=["manual"],
        source_system="dfms",
        status="queued",
        current_version=1,
        latest_job_id=f"job_{doc_id}",
        storage_path=f"/tmp/{doc_id}.txt",
        created_by="u001",
        created_at=now,
        updated_at=now,
    )


def _build_job_record(job_id: str, doc_id: str) -> IngestJobRecord:
    now = datetime.now(timezone.utc)
    return IngestJobRecord(
        job_id=job_id,
        doc_id=doc_id,
        version=1,
        file_name=f"{doc_id}.txt",
        status="queued",
        stage="queued",
        progress=0,
        retry_count=0,
        error_code=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def test_load_records_collects_invalid_json_files(tmp_path: Path) -> None:
    document_dir = tmp_path / "documents"
    job_dir = tmp_path / "jobs"
    document_dir.mkdir(parents=True, exist_ok=True)
    job_dir.mkdir(parents=True, exist_ok=True)

    valid_document = _build_document_record("doc_001")
    (document_dir / "doc_001.json").write_text(valid_document.model_dump_json(indent=2), encoding="utf-8")
    (document_dir / "broken_doc.json").write_text("{invalid-json", encoding="utf-8")

    valid_job = _build_job_record("job_001", "doc_001")
    (job_dir / "job_001.json").write_text(valid_job.model_dump_json(indent=2), encoding="utf-8")
    (job_dir / "broken_job.json").write_text("{}", encoding="utf-8")

    documents, document_failures = load_document_records(document_dir)
    jobs, job_failures = load_job_records(job_dir)

    assert len(documents) == 1
    assert len(document_failures) == 1
    assert document_failures[0].path.name == "broken_doc.json"

    assert len(jobs) == 1
    assert len(job_failures) == 1
    assert job_failures[0].path.name == "broken_job.json"


def test_backfill_records_skips_write_on_dry_run() -> None:
    store = _FakeMetadataStore()
    documents = [_build_document_record("doc_001"), _build_document_record("doc_002")]
    jobs = [_build_job_record("job_001", "doc_001")]

    report = backfill_records(store, documents, jobs, dry_run=True)

    assert report.dry_run is True
    assert report.document_total == 2
    assert report.job_total == 1
    assert report.document_saved == 0
    assert report.job_saved == 0
    assert store.saved_document_ids == []
    assert store.saved_job_ids == []


def test_backfill_records_writes_all_records() -> None:
    store = _FakeMetadataStore()
    documents = [_build_document_record("doc_001"), _build_document_record("doc_002")]
    jobs = [_build_job_record("job_001", "doc_001"), _build_job_record("job_002", "doc_002")]

    report = backfill_records(store, documents, jobs, dry_run=False)

    assert report.dry_run is False
    assert report.document_total == 2
    assert report.job_total == 2
    assert report.document_saved == 2
    assert report.job_saved == 2
    assert store.saved_document_ids == ["doc_001", "doc_002"]
    assert store.saved_job_ids == ["job_001", "job_002"]

