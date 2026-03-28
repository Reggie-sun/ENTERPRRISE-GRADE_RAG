import os
import sys
import types

import pytest

from backend.app.core.config import Settings
from backend.app.rag.ocr.client import OCRClient, OCRUnavailableError, _PADDLE_OCR_SINGLETONS


def test_get_paddle_ocr_reuses_process_singleton(monkeypatch) -> None:
    created: list[dict[str, object]] = []

    class FakePaddleOCR:
        def __init__(self, **kwargs) -> None:
            created.append(kwargs)

    _PADDLE_OCR_SINGLETONS.clear()
    monkeypatch.delenv("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", raising=False)
    monkeypatch.setitem(sys.modules, "paddleocr", types.SimpleNamespace(PaddleOCR=FakePaddleOCR))

    settings = Settings(
        _env_file=None,
        ocr_provider="paddleocr",
        ocr_language="ch",
        ocr_paddle_use_angle_cls=True,
    )

    first = OCRClient(settings)._get_paddle_ocr()
    second = OCRClient(settings)._get_paddle_ocr()

    assert first is second
    assert created == [
        {
            "lang": "ch",
            "ocr_version": "PP-OCRv5",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": True,
            "text_detection_model_name": "PP-OCRv5_mobile_det",
            "text_recognition_model_name": "PP-OCRv5_mobile_rec",
        }
    ]
    assert os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] == "True"

    _PADDLE_OCR_SINGLETONS.clear()
    sys.modules.pop("paddleocr", None)


def test_get_paddle_ocr_surfaces_import_error_detail(monkeypatch) -> None:
    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "paddleocr":
            raise ImportError("libGL.so.1: cannot open shared object file")
        return original_import(name, globals, locals, fromlist, level)

    _PADDLE_OCR_SINGLETONS.clear()
    monkeypatch.setattr("builtins.__import__", fake_import)

    settings = Settings(_env_file=None, ocr_provider="paddleocr")

    with pytest.raises(OCRUnavailableError, match="libGL.so.1"):
        OCRClient(settings)._get_paddle_ocr()


def test_flatten_paddle_results_supports_v3_ocr_result_shape() -> None:
    block = types.SimpleNamespace(
        rec_texts=["OCR真实验证", "STEP1CHECKPOWER67890"],
        rec_scores=[0.99, 0.87],
    )

    segments = OCRClient._flatten_paddle_results([block], page_no=1)

    assert [segment.text for segment in segments] == ["OCR真实验证", "STEP1CHECKPOWER67890"]
    assert [segment.confidence for segment in segments] == [0.99, 0.87]
    assert [segment.line_no for segment in segments] == [1, 2]
