import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from backend.app.schemas.document import DocumentRecord
from backend.app.services.auth_service import AuthService

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


eval_retrieval = _load_module("eval_retrieval_script", PROJECT_ROOT / "scripts" / "eval_retrieval.py")
seed_acl = _load_module("seed_retrieval_eval_acl_script", PROJECT_ROOT / "scripts" / "seed_retrieval_eval_acl.py")


def test_eval_auth_profiles_cover_all_logical_sample_departments() -> None:
    samples = eval_retrieval.load_samples(PROJECT_ROOT / "eval" / "retrieval_samples.yaml")
    auth_profiles = eval_retrieval.load_auth_profiles(PROJECT_ROOT / "eval" / "retrieval_auth_profiles.yaml")

    eval_retrieval.ensure_auth_profile_coverage(samples, auth_profiles)

    assert auth_profiles["dept_after_sales"]["auth_department_id"] == "dept_installation_service"
    assert auth_profiles["dept_assembly"]["auth_department_id"] == "dept_production_technology"
    assert auth_profiles["dept_digitalization"]["auth_department_id"] == "dept_digitalization"


def test_eval_auth_profiles_map_to_real_bootstrap_users_and_passwords() -> None:
    auth_profiles = eval_retrieval.load_auth_profiles(PROJECT_ROOT / "eval" / "retrieval_auth_profiles.yaml")
    bootstrap = json.loads((PROJECT_ROOT / "backend" / "app" / "bootstrap" / "identity_bootstrap.json").read_text(encoding="utf-8"))
    bootstrap_users = {item["username"]: item for item in bootstrap["users"]}

    for logical_department_id, profile in auth_profiles.items():
        assert profile["username"] in bootstrap_users, logical_department_id
        bootstrap_user = bootstrap_users[profile["username"]]
        assert bootstrap_user["department_id"] == profile["auth_department_id"]
        assert AuthService.verify_password(profile["password"], bootstrap_user["password_hash"])


def test_acl_seed_covers_all_supplemental_expected_docs() -> None:
    samples = yaml.safe_load((PROJECT_ROOT / "eval" / "retrieval_samples.yaml").read_text(encoding="utf-8"))["samples"]
    supplemental_docs = {
        doc_id
        for sample in samples
        if sample.get("supplemental_expected")
        for doc_id in sample.get("expected_doc_ids", [])
    }
    acl_seed = seed_acl.load_acl_seed(PROJECT_ROOT / "eval" / "retrieval_document_acl_seed.yaml")

    assert supplemental_docs <= set(acl_seed)


def test_acl_seed_updates_existing_record_department_scope() -> None:
    acl_seed = seed_acl.load_acl_seed(PROJECT_ROOT / "eval" / "retrieval_document_acl_seed.yaml")
    seed_entry = acl_seed["doc_20260401085300_13d0ce46"]
    record = DocumentRecord(
        doc_id="doc_20260401085300_13d0ce46",
        tenant_id="wl",
        file_name="V1_PLAN.md",
        file_hash="hash_001",
        source_type="md",
        department_id=None,
        department_ids=[],
        retrieval_department_ids=[],
        role_ids=[],
        owner_id=None,
        visibility="private",
        classification="internal",
        tags=[],
        source_system="seed-test",
        status="active",
        current_version=1,
        latest_job_id="job_001",
        storage_path="/tmp/V1_PLAN.md",
        uploaded_by="seed-test",
        created_by="seed-test",
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )

    updated = seed_acl.apply_acl_to_record(record, seed_entry)

    assert updated.department_id == "dept_digitalization"
    assert updated.department_ids == ["dept_digitalization"]
    assert updated.retrieval_department_ids == ["dept_installation_service", "dept_production_technology"]
    assert updated.visibility == "private"
    assert updated.updated_at >= record.updated_at


def test_acl_seed_can_build_local_stub_from_upload_asset() -> None:
    acl_seed = seed_acl.load_acl_seed(PROJECT_ROOT / "eval" / "retrieval_document_acl_seed.yaml")
    seed_entry = acl_seed["doc_20260330055115_c20cfc5a"]

    record = seed_acl.build_local_stub_record(
        doc_id="doc_20260330055115_c20cfc5a",
        seed_entry=seed_entry,
        tenant_id="wl",
        upload_dir=PROJECT_ROOT / "data" / "uploads",
    )

    assert record.file_name == "WI-SJ-052_A0.docx"
    assert record.source_type == "docx"
    assert record.department_id == "dept_production_technology"
    assert record.retrieval_department_ids == ["dept_digitalization"]
    assert record.status == "active"
    assert record.storage_path.endswith("__WI-SJ-052_A0.docx")
