from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid5, NAMESPACE_URL
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from backend.app.schemas.auth import IdentityBootstrapData
from backend.app.services.auth_service import AuthService

COMPANY_PATH_PREFIXES = {"伟立机器人", "宁波伟立机器人科技股份有限公司"}
PRIMARY_COMPANY_PREFIX = "伟立机器人/宁波伟立机器人科技股份有限公司/"
REQUIRED_HEADERS = {"姓名", "帐号", "工号", "企业邮箱", "部门", "员工状态"}
XML_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch) - ord("A") + 1)
    return max(value - 1, 0)


def _read_xlsx_rows(path: Path, *, sheet_name: str = "员工数据") -> list[list[str]]:
    with ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", XML_NS):
                shared_strings.append("".join((node.text or "") for node in item.iterfind(".//a:t", XML_NS)))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        workbook_ns = {
            "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
            "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        }
        relationship_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}

        target_sheet_rel_id: str | None = None
        for sheet in workbook.findall("a:sheets/a:sheet", workbook_ns):
            if sheet.attrib.get("name") == sheet_name:
                target_sheet_rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                break
        if target_sheet_rel_id is None:
            raise RuntimeError(f"Sheet not found: {sheet_name}")

        sheet_target: str | None = None
        for rel in rels.findall("r:Relationship", relationship_ns):
            if rel.attrib.get("Id") == target_sheet_rel_id:
                sheet_target = rel.attrib.get("Target")
                break
        if sheet_target is None:
            raise RuntimeError(f"Workbook relationship not found for sheet: {sheet_name}")

        sheet_xml = ET.fromstring(archive.read(f"xl/{sheet_target.lstrip('/')}"))
        rows: list[list[str]] = []
        for row in sheet_xml.findall(".//a:sheetData/a:row", XML_NS):
            cells: dict[int, str] = {}
            max_index = -1
            for cell in row.findall("a:c", XML_NS):
                cell_ref = cell.attrib.get("r", "")
                column_index = _column_index(cell_ref)
                max_index = max(max_index, column_index)
                value_node = cell.find("a:v", XML_NS)
                if value_node is None:
                    cells[column_index] = ""
                    continue
                value = value_node.text or ""
                if cell.attrib.get("t") == "s":
                    value = shared_strings[int(value)]
                cells[column_index] = value
            if max_index < 0:
                continue
            rows.append([cells.get(index, "").strip() for index in range(max_index + 1)])
        return rows


def _find_header_row(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    for index, row in enumerate(rows):
        header_map = {value: position for position, value in enumerate(row) if value}
        if REQUIRED_HEADERS.issubset(header_map):
            return index, header_map
    raise RuntimeError(f"Could not find roster header row with columns: {sorted(REQUIRED_HEADERS)}")


def _normalize_username(account: str, employee_no: str, company_email: str) -> str:
    if account:
        return account
    if employee_no:
        return employee_no
    if company_email:
        return company_email.split("@", 1)[0]
    raise RuntimeError("Cannot derive username without 帐号/工号/企业邮箱")


def _derive_password_seed(username: str, employee_no: str) -> str:
    return employee_no or username


def _stable_salt(seed: str) -> bytes:
    return hashlib.sha256(seed.encode("utf-8")).digest()[:16]


def _sanitize_identifier(value: str) -> str:
    lowered = value.lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return normalized or hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def _generated_department_id(path_key: str) -> str:
    return f"dept_{uuid5(NAMESPACE_URL, f'wl:{path_key}').hex[:12]}"


def _strip_company_prefix(path_value: str) -> list[str]:
    parts = [part.strip() for part in path_value.split("/") if part.strip()]
    while parts and parts[0] in COMPANY_PATH_PREFIXES:
        parts.pop(0)
    return parts


def _extract_primary_department_name(path_value: str) -> str | None:
    if not path_value or not path_value.startswith(PRIMARY_COMPANY_PREFIX):
        return None
    remainder = path_value[len(PRIMARY_COMPANY_PREFIX) :]
    first_segment = next((part.strip() for part in remainder.split("/") if part.strip()), "")
    if not first_segment:
        return None
    department_name = first_segment.split(";", 1)[0].strip()
    return department_name or None


def _row_value(row: list[str], header: dict[str, int], name: str) -> str:
    index = header[name]
    return row[index].strip() if len(row) > index else ""


def _load_bootstrap(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_roster_usernames(roster_rows: list[list[str]], header_map: dict[str, int]) -> set[str]:
    usernames: set[str] = set()
    for row in roster_rows:
        name = _row_value(row, header_map, "姓名")
        department_path = _row_value(row, header_map, "部门")
        if not name or not department_path or name in {"姓名", "个人信息"}:
            continue
        account = _row_value(row, header_map, "帐号")
        employee_no = _row_value(row, header_map, "工号")
        company_email = _row_value(row, header_map, "企业邮箱")
        try:
            usernames.add(_normalize_username(account, employee_no, company_email))
        except RuntimeError:
            continue
    return usernames


def _merge_departments(
    bootstrap_payload: dict[str, Any],
    roster_rows: list[list[str]],
    header_map: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    desired_department_names: list[str] = []
    for row in roster_rows:
        department_name = _extract_primary_department_name(_row_value(row, header_map, "部门"))
        if department_name and department_name not in desired_department_names:
            desired_department_names.append(department_name)

    existing_top_levels = {
        item["department_name"]: dict(item)
        for item in bootstrap_payload["departments"]
        if not item.get("parent_department_id")
    }

    departments: list[dict[str, Any]] = []
    path_to_department_id: dict[str, str] = {}
    for row in roster_rows:
        department_name = _extract_primary_department_name(_row_value(row, header_map, "部门"))
        if not department_name:
            continue
        if department_name in path_to_department_id:
            continue
        existing = existing_top_levels.get(department_name)
        if existing is not None:
            department = existing
        else:
            department = {
                "department_id": _generated_department_id(department_name),
                "tenant_id": "wl",
                "department_name": department_name,
                "parent_department_id": None,
                "is_active": True,
            }
        departments.append(department)
        path_to_department_id[department_name] = department["department_id"]

    ordered = sorted(
        departments,
        key=lambda item: (
            desired_department_names.index(item["department_name"])
            if item["department_name"] in desired_department_names
            else len(desired_department_names),
            item["department_name"],
        ),
    )
    return ordered, path_to_department_id


def _merge_users(
    bootstrap_payload: dict[str, Any],
    roster_rows: list[list[str]],
    header_map: dict[str, int],
    path_to_department_id: dict[str, str],
) -> list[dict[str, Any]]:
    roster_usernames = _collect_roster_usernames(roster_rows, header_map)
    preserved_users = OrderedDict()
    for item in bootstrap_payload["users"]:
        if item["username"] not in roster_usernames:
            preserved_users[item["username"]] = dict(item)

    for row in roster_rows:
        name = _row_value(row, header_map, "姓名")
        department_path = _row_value(row, header_map, "部门")
        status = _row_value(row, header_map, "员工状态")
        if not name or not department_path or name in {"姓名", "个人信息"}:
            continue
        department_name = _extract_primary_department_name(department_path)
        if not department_name:
            continue
        department_id = path_to_department_id.get(department_name)
        if department_id is None:
            continue

        account = _row_value(row, header_map, "帐号")
        employee_no = _row_value(row, header_map, "工号")
        company_email = _row_value(row, header_map, "企业邮箱")
        username = _normalize_username(account, employee_no, company_email)
        password_seed = _derive_password_seed(username, employee_no)
        record = {
            "user_id": f"user_roster_{_sanitize_identifier(username)}",
            "tenant_id": "wl",
            "username": username,
            "display_name": name,
            "department_id": department_id,
            "role_id": "employee",
            "is_active": status != "待离职",
            "password_hash": AuthService.hash_password(
                f"Weili@{password_seed}",
                salt=_stable_salt(f"wl:{username}"),
            ),
        }
        preserved_users[username] = record
    return list(preserved_users.values())


def import_roster(*, bootstrap_path: Path, roster_path: Path, backup: bool = True) -> dict[str, int]:
    rows = _read_xlsx_rows(roster_path)
    header_row_index, header_map = _find_header_row(rows)
    roster_rows = [row for index, row in enumerate(rows) if index != header_row_index]

    bootstrap_payload = _load_bootstrap(bootstrap_path)
    if backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = bootstrap_path.with_name(f"{bootstrap_path.stem}.bak_{timestamp}{bootstrap_path.suffix}")
        backup_path.write_text(json.dumps(bootstrap_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    departments, path_to_department_id = _merge_departments(bootstrap_payload, roster_rows, header_map)
    users = _merge_users(bootstrap_payload, roster_rows, header_map, path_to_department_id)

    merged_payload = {
        "roles": bootstrap_payload["roles"],
        "departments": departments,
        "users": users,
    }
    IdentityBootstrapData.model_validate(merged_payload)
    bootstrap_path.write_text(json.dumps(merged_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    active_imported_users = 0
    imported_departments = 0
    skipped_department_scope_rows = 0
    for user in users:
        if user["user_id"].startswith("user_roster_") and user["is_active"]:
            active_imported_users += 1
    for department in departments:
        if department["department_id"] in path_to_department_id.values():
            imported_departments += 1
    for row in roster_rows:
        name = _row_value(row, header_map, "姓名")
        department_path = _row_value(row, header_map, "部门")
        if not name or not department_path or name in {"姓名", "个人信息"}:
            continue
        if _extract_primary_department_name(department_path) is None:
            skipped_department_scope_rows += 1

    return {
        "department_count": len(departments),
        "user_count": len(users),
        "active_imported_user_count": active_imported_users,
        "roster_department_count": len(set(path_to_department_id.values())),
        "skipped_department_scope_row_count": skipped_department_scope_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import roster XLSX into identity_bootstrap.json")
    parser.add_argument("roster_path", type=Path)
    parser.add_argument(
        "--bootstrap-path",
        type=Path,
        default=Path("backend/app/bootstrap/identity_bootstrap.json"),
    )
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    result = import_roster(
        bootstrap_path=args.bootstrap_path,
        roster_path=args.roster_path,
        backup=not args.no_backup,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
