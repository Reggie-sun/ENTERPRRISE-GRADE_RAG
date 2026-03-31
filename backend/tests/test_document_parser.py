import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from backend.app.rag.parsers.document_parser import DocumentParser, find_libreoffice_binary


def test_parse_falls_back_to_filename_suffix_when_storage_path_has_no_extension(tmp_path: Path) -> None:
    source_path = tmp_path / "doc_without_extension"
    source_path.write_text("Alarm E102 handling guide", encoding="utf-8")

    parser = DocumentParser()
    result = parser.parse(
        source_path=source_path,
        document_id="doc_001",
        filename="说明书.txt",
    )

    assert result.parser_name == "plain_text"
    assert "Alarm E102 handling guide" in result.text


def test_parse_raises_when_source_path_and_filename_both_missing_extension(tmp_path: Path) -> None:
    source_path = tmp_path / "doc_without_extension"
    source_path.write_text("content", encoding="utf-8")

    parser = DocumentParser()
    with pytest.raises(ValueError, match="Unsupported file type for parsing: unknown"):
        parser.parse(
            source_path=source_path,
            document_id="doc_001",
            filename="说明书",
        )


def test_parse_raises_for_image_suffix_until_ocr_takes_over(tmp_path: Path) -> None:
    source_path = tmp_path / "scan.png"
    source_path.write_bytes(b"fake-image-content")

    parser = DocumentParser()
    with pytest.raises(ValueError, match="OCR is required to parse image file type: \\.png"):
        parser.parse(
            source_path=source_path,
            document_id="doc_001",
            filename="scan.png",
        )


# ── CSV ───────────────────────────────────────────────────────────────────


def test_parse_csv_extracts_tab_separated_rows(tmp_path: Path) -> None:
    source_path = tmp_path / "data.csv"
    source_path.write_text("Name,Age,City\nAlice,30,Beijing\nBob,25,Shanghai\n", encoding="utf-8")

    parser = DocumentParser()
    result = parser.parse(source_path=source_path, document_id="doc_csv", filename="data.csv")

    assert result.parser_name == "csv_text"
    assert "Name\tAge\tCity" in result.text
    assert "Alice\t30\tBeijing" in result.text
    assert "Bob\t25\tShanghai" in result.text


def test_parse_csv_handles_utf8_bom(tmp_path: Path) -> None:
    source_path = tmp_path / "bom.csv"
    source_path.write_bytes(b"\xef\xbb\xbfHeader\nValue\n")

    parser = DocumentParser()
    result = parser.parse(source_path=source_path, document_id="doc_bom", filename="bom.csv")

    assert result.parser_name == "csv_text"
    assert "Header" in result.text
    assert "Value" in result.text


# ── HTML ──────────────────────────────────────────────────────────────────


def test_parse_html_extracts_visible_text(tmp_path: Path) -> None:
    source_path = tmp_path / "page.html"
    source_path.write_text(
        "<html><head><title>Test</title></head>"
        "<body><h1>Hello</h1><p>World</p></body></html>",
        encoding="utf-8",
    )

    parser = DocumentParser()
    result = parser.parse(source_path=source_path, document_id="doc_html", filename="page.html")

    assert result.parser_name == "html_text"
    assert "Hello" in result.text
    assert "World" in result.text


def test_parse_html_ignores_script_and_style(tmp_path: Path) -> None:
    source_path = tmp_path / "page2.html"
    source_path.write_text(
        "<html><head><style>.x{color:red}</style></head>"
        "<body><script>alert('xss')</script><p>Visible</p></body></html>",
        encoding="utf-8",
    )

    parser = DocumentParser()
    result = parser.parse(source_path=source_path, document_id="doc_html2", filename="page2.html")

    assert result.parser_name == "html_text"
    assert "Visible" in result.text
    assert "alert" not in result.text
    assert "color" not in result.text


# ── JSON ──────────────────────────────────────────────────────────────────


def test_parse_json_flattens_to_path_value(tmp_path: Path) -> None:
    source_path = tmp_path / "config.json"
    source_path.write_text(
        '{"name": "Alice", "address": {"city": "Beijing", "zip": "100000"}, "tags": ["a", "b"]}',
        encoding="utf-8",
    )

    parser = DocumentParser()
    result = parser.parse(source_path=source_path, document_id="doc_json", filename="config.json")

    assert result.parser_name == "json_flatten"
    assert "name: Alice" in result.text
    assert "address.city: Beijing" in result.text
    assert "address.zip: 100000" in result.text
    assert "tags[0]: a" in result.text
    assert "tags[1]: b" in result.text


# ── XLSX ──────────────────────────────────────────────────────────────────


def _build_minimal_xlsx_bytes() -> bytes:
    """构造一个最小可解析 xlsx，不依赖 openpyxl。"""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )
    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{ns}">'
        f'<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets>'
        '</workbook>'
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    # shared strings
    shared_strings_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="{ns}" count="4" uniqueCount="4">'
        f'<si><t>Name</t></si>'
        f'<si><t>Age</t></si>'
        f'<si><t>Alice</t></si>'
        f'<si><t>30</t></si>'
        f'</sst>'
    )
    # sheet data with shared string refs (t="s") and inline string
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{ns}">'
        f'<sheetData>'
        f'<row><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row>'
        f'<row><c t="s"><v>2</v></c><c t="s"><v>3</v></c></row>'
        f'<row><c><v>42</v></c><c><is><t>inline</t></is></c></row>'
        f'</sheetData>'
        f'</worksheet>'
    )

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", root_rels_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/sharedStrings.xml", shared_strings_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)

    return buffer.getvalue()


def test_parse_xlsx_extracts_shared_strings_and_inline(tmp_path: Path) -> None:
    source_path = tmp_path / "sheet.xlsx"
    source_path.write_bytes(_build_minimal_xlsx_bytes())

    parser = DocumentParser()
    result = parser.parse(source_path=source_path, document_id="doc_xlsx", filename="sheet.xlsx")

    assert result.parser_name == "xlsx_xml"
    assert "[Sheet] Sheet1" in result.text
    assert "Name\tAge" in result.text
    assert "Alice\t30" in result.text
    assert "42" in result.text
    assert "inline" in result.text


# ── PPTX ──────────────────────────────────────────────────────────────────


def _build_minimal_pptx_bytes() -> bytes:
    """构造一个最小可解析 pptx，不依赖 python-pptx。"""
    ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    ns_p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    ns_r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        '<Override PartName="/ppt/slides/slide2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        '</Types>'
    )
    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
        f'</Relationships>'
    )
    presentation_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:presentation xmlns:p="{ns_p}" xmlns:r="{ns_r}">'
        f'<p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId3"/></p:sldIdLst>'
        f'</p:presentation>'
    )
    presentation_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>'
        f'<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/>'
        f'</Relationships>'
    )
    slide1_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sld xmlns:p="{ns_p}" xmlns:a="{ns_a}">'
        f'<p:cSld><p:spTree><p:sp><p:txBody>'
        f'<a:p><a:r><a:t>Sales Report Q1</a:t></a:r></a:p>'
        f'<a:p><a:r><a:t>Revenue: 1M</a:t></a:r></a:p>'
        f'</p:txBody></p:sp></p:spTree></p:cSld>'
        f'</p:sld>'
    )
    slide2_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sld xmlns:p="{ns_p}" xmlns:a="{ns_a}">'
        f'<p:cSld><p:spTree><p:sp><p:txBody>'
        f'<a:p><a:r><a:t>Next Steps</a:t></a:r></a:p>'
        f'</p:txBody></p:sp></p:spTree></p:cSld>'
        f'</p:sld>'
    )

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", root_rels_xml)
        archive.writestr("ppt/presentation.xml", presentation_xml)
        archive.writestr("ppt/_rels/presentation.xml.rels", presentation_rels_xml)
        archive.writestr("ppt/slides/slide1.xml", slide1_xml)
        archive.writestr("ppt/slides/slide2.xml", slide2_xml)

    return buffer.getvalue()


def test_parse_pptx_extracts_text_by_slide(tmp_path: Path) -> None:
    source_path = tmp_path / "deck.pptx"
    source_path.write_bytes(_build_minimal_pptx_bytes())

    parser = DocumentParser()
    result = parser.parse(source_path=source_path, document_id="doc_pptx", filename="deck.pptx")

    assert result.parser_name == "pptx_xml"
    assert "[Slide 1]" in result.text
    assert "[Slide 2]" in result.text
    assert "Sales Report Q1" in result.text
    assert "Revenue: 1M" in result.text
    assert "Next Steps" in result.text


# ── XLS (xlrd) ────────────────────────────────────────────────────────────


def test_parse_xls_raises_clear_error_when_xlrd_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_path = tmp_path / "old.xls"
    source_path.write_bytes(b"fake-xls-content")

    # 模拟 xlrd 未安装：让 import xlrd 抛 ImportError
    monkeypatch.setitem(__builtins__, "__import__", lambda name, *a, **kw: (_ for _ in ()).throw(ImportError(name)) if name == "xlrd" else __import__(name, *a, **kw))

    parser = DocumentParser()
    with pytest.raises(ValueError, match="xlrd is required to parse .xls files but is not installed"):
        parser.parse(source_path=source_path, document_id="doc_xls", filename="old.xls")


def test_parse_xls_extracts_text_with_fake_xlrd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """用 fake xlrd module 测试 .xls 解析逻辑，不依赖真实 xlrd 安装。"""
    import types

    fake_xlrd = types.ModuleType("xlrd")

    class FakeSheet:
        name = "Summary"
        nrows = 2
        ncols = 2

        def cell_value(self, row, col):
            return [["Name", "Score"], ["Alice", 95]][row][col]

    class FakeWorkbook:
        def sheets(self):
            return [FakeSheet()]

    fake_xlrd.open_workbook = lambda path: FakeWorkbook()
    monkeypatch.setitem(sys.modules, "xlrd", fake_xlrd)

    source_path = tmp_path / "data.xls"
    source_path.write_bytes(b"fake-xls")

    parser = DocumentParser()
    result = parser.parse(source_path=source_path, document_id="doc_xls2", filename="data.xls")

    assert result.parser_name == "xls_xlrd"
    assert "[Sheet] Summary" in result.text
    assert "Name\tScore" in result.text
    assert "Alice\t95" in result.text


def test_find_libreoffice_binary_uses_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_binary = tmp_path / "custom-lowriter"
    fake_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_binary.chmod(0o755)

    monkeypatch.setenv("RAG_LIBREOFFICE_BINARY", str(fake_binary))

    assert find_libreoffice_binary() == str(fake_binary)


def test_find_libreoffice_binary_falls_back_to_lowriter_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_binary = tmp_path / "lowriter"
    fake_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_binary.chmod(0o755)

    monkeypatch.delenv("RAG_LIBREOFFICE_BINARY", raising=False)
    monkeypatch.delenv("LIBREOFFICE_BINARY", raising=False)
    monkeypatch.setattr("backend.app.rag.parsers.document_parser.get_configured_libreoffice_binary", lambda: None)
    monkeypatch.setattr("backend.app.rag.parsers.document_parser.LIBREOFFICE_BINARY_CANDIDATES", ())
    monkeypatch.setattr(
        "backend.app.rag.parsers.document_parser.shutil.which",
        lambda command: str(fake_binary) if command == "lowriter" else None,
    )

    assert find_libreoffice_binary() == str(fake_binary)
