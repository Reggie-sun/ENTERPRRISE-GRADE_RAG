from pathlib import Path

import pytest

from backend.app.rag.parsers.document_parser import DocumentParser


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
