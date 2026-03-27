import importlib.util  # 导入 importlib，便于做 OCR 依赖可用性探测而不强制导入大包。
from dataclasses import dataclass, field  # 导入 dataclass，用于封装 OCR 结果。
from pathlib import Path  # 导入 Path，方便处理 sidecar 和临时图片文件。
from tempfile import TemporaryDirectory  # 导入临时目录，给 PDF 渲染页落地用。
from typing import Any  # 导入 Any，兼容第三方 OCR 客户端的动态返回类型。

from ...core.config import Settings, get_settings  # 导入统一配置对象，避免 OCR 自己再维护一套 env 解析。
from ..parsers.document_parser import OCR_IMAGE_SUFFIXES  # 复用解析层定义的 OCR-only 图片后缀集合。


class OCRUnavailableError(RuntimeError):  # OCR provider 未配置或依赖缺失时统一走这个异常类型。
    pass


@dataclass(slots=True)  # OCR 片段统一收口，便于后续保存 artifact 和做 OCR 质量分析。
class OCRTextSegment:
    text: str  # 当前 OCR 片段文本。
    page_no: int | None = None  # 当前片段所在页码；图片统一视为第 1 页。
    line_no: int | None = None  # 当前页内的行号，便于排查 OCR 乱序或丢字。
    confidence: float | None = None  # OCR 置信度，供后续人工复核或质量评估复用。


@dataclass(slots=True)  # OCR 结果统一收口，给入库服务决定是 completed 还是 partial_failed。
class OCRExtractionResult:
    parser_name: str  # 本次 OCR 使用的解析器名称。
    text: str  # 抽出的文本结果。
    warning_message: str | None = None  # 非致命告警，例如 PDF 个别页 OCR 失败。
    segments: list[OCRTextSegment] = field(default_factory=list)  # OCR 中间片段，单独落盘后可供排障和质量分析。


class OCRClient:  # 封装 OCR provider 的最小统一入口。
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._paddle_ocr: Any | None = None

    def is_enabled(self) -> bool:  # 判断当前是否显式启用了 OCR。
        return self.settings.ocr_provider.lower().strip() != "disabled"

    @staticmethod
    def is_ocr_image_suffix(suffix: str) -> bool:  # 暴露图片后缀判断，给外层流程直接复用。
        return suffix.lower() in OCR_IMAGE_SUFFIXES

    def extract_image_text(self, *, source_path: Path, filename: str) -> OCRExtractionResult:  # 对图片执行 OCR。
        provider = self.settings.ocr_provider.lower().strip()
        if provider == "disabled":
            raise OCRUnavailableError("OCR provider is disabled for image documents.")
        if provider == "mock":
            return self._extract_with_mock(source_path=source_path, filename=filename, parser_name="image_ocr_mock")
        if provider == "paddleocr":
            segments = self._extract_image_segments_with_paddle(source_path, page_no=1)
            return OCRExtractionResult(
                parser_name="image_ocr_paddle",
                text=self._segments_to_text(segments),
                segments=segments,
            )
        raise OCRUnavailableError(f"Unsupported OCR provider: {self.settings.ocr_provider}")

    def extract_pdf_text(self, *, source_path: Path, filename: str) -> OCRExtractionResult:  # 对 PDF 执行 OCR fallback。
        provider = self.settings.ocr_provider.lower().strip()
        if provider == "disabled":
            raise OCRUnavailableError("OCR provider is disabled for PDF fallback.")
        if provider == "mock":
            return self._extract_with_mock(source_path=source_path, filename=filename, parser_name="pdf_ocr_mock")
        if provider == "paddleocr":
            return self._extract_pdf_text_with_paddle(source_path)
        raise OCRUnavailableError(f"Unsupported OCR provider: {self.settings.ocr_provider}")

    def get_runtime_status(self) -> dict[str, Any]:  # 返回当前 OCR provider 的最小运行状态，供 health/ops 页面直接展示。
        provider = self.settings.ocr_provider.lower().strip()
        payload = {
            "provider": provider,
            "language": self.settings.ocr_language,
            "enabled": provider != "disabled",
            "ready": False,
            "pdf_native_text_min_chars": self.settings.ocr_pdf_native_text_min_chars,
            "angle_cls_enabled": self.settings.ocr_paddle_use_angle_cls,
            "detail": None,
        }
        if provider == "disabled":
            payload["detail"] = "OCR is disabled by configuration."
            return payload
        if provider == "mock":
            payload["ready"] = True
            payload["detail"] = "Mock OCR is enabled for local validation."
            return payload
        if provider == "paddleocr":
            missing_dependencies = self._detect_paddle_dependencies()
            if missing_dependencies:
                payload["detail"] = (
                    "PaddleOCR OCR provider is configured but dependencies are missing: "
                    + ", ".join(missing_dependencies)
                    + ". Install requirements/ocr-cpu.txt or requirements/ocr-gpu-cu130.txt."
                )
                return payload
            payload["ready"] = True
            payload["detail"] = "PaddleOCR runtime dependencies are available."
            return payload
        payload["detail"] = f"Unsupported OCR provider: {self.settings.ocr_provider}"
        return payload

    def _extract_with_mock(self, *, source_path: Path, filename: str, parser_name: str) -> OCRExtractionResult:  # 测试和联调阶段用 sidecar 文本模拟 OCR 输出。
        for candidate in (
            source_path.with_suffix(f"{source_path.suffix}.ocr.txt"),
            source_path.with_suffix(".ocr.txt"),
            source_path.with_suffix(".txt"),
        ):
            if candidate.exists():
                text = candidate.read_text(encoding="utf-8")
                return OCRExtractionResult(parser_name=parser_name, text=text, segments=self._build_mock_segments(text))
        text = f"Mock OCR text extracted from {filename}"
        return OCRExtractionResult(parser_name=parser_name, text=text, segments=self._build_mock_segments(text))

    def _extract_image_segments_with_paddle(self, source_path: Path, *, page_no: int | None) -> list[OCRTextSegment]:  # 让 PaddleOCR 直接识别图片，并保留页内片段明细。
        ocr = self._get_paddle_ocr()
        results = ocr.ocr(str(source_path), cls=self.settings.ocr_paddle_use_angle_cls)
        return self._flatten_paddle_results(results, page_no=page_no)

    def _extract_pdf_text_with_paddle(self, source_path: Path) -> OCRExtractionResult:  # 把 PDF 每页渲染成图片后交给 PaddleOCR。
        try:
            import fitz  # type: ignore[import-not-found]
        except ImportError as exc:
            raise OCRUnavailableError("PyMuPDF is required for PDF OCR fallback but is not installed.") from exc

        page_texts: list[str] = []
        segments: list[OCRTextSegment] = []
        failed_pages: list[int] = []
        with TemporaryDirectory(prefix="ocr_pdf_") as temp_dir:
            with fitz.open(str(source_path)) as pdf:
                for page_index, page in enumerate(pdf, start=1):
                    image_path = Path(temp_dir) / f"page_{page_index}.png"
                    try:
                        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                        pixmap.save(str(image_path))
                        page_segments = self._extract_image_segments_with_paddle(image_path, page_no=page_index)
                        page_text = self._segments_to_text(page_segments).strip()
                        if page_text:
                            page_texts.append(page_text)
                        segments.extend(page_segments)
                    except Exception:
                        failed_pages.append(page_index)

        if not page_texts:
            raise OCRUnavailableError(f"OCR did not extract any text from PDF '{source_path.name}'.")

        warning_message = None
        if failed_pages:
            pages = ", ".join(str(page_no) for page_no in failed_pages)
            warning_message = f"OCR failed on PDF pages: {pages}. Continued with remaining pages."
        return OCRExtractionResult(
            parser_name="pdf_ocr_paddle",
            text="\n\n".join(page_texts),
            warning_message=warning_message,
            segments=segments,
        )

    def _get_paddle_ocr(self) -> Any:  # 懒加载 PaddleOCR，避免默认开发环境启动即强依赖大包。
        if self._paddle_ocr is not None:
            return self._paddle_ocr
        try:
            from paddleocr import PaddleOCR  # type: ignore[import-not-found]
        except ImportError as exc:
            raise OCRUnavailableError("PaddleOCR is not installed. Use requirements/ocr-*.txt to enable OCR.") from exc

        self._paddle_ocr = PaddleOCR(use_angle_cls=self.settings.ocr_paddle_use_angle_cls, lang=self.settings.ocr_language)
        return self._paddle_ocr

    @staticmethod
    def _detect_paddle_dependencies() -> list[str]:  # 仅做依赖探测，不主动导入 PaddleOCR 或 PyMuPDF。
        missing: list[str] = []
        if importlib.util.find_spec("paddleocr") is None:
            missing.append("paddleocr")
        if importlib.util.find_spec("fitz") is None:
            missing.append("fitz")
        return missing

    @staticmethod
    def _flatten_paddle_results(results: Any, *, page_no: int | None) -> list[OCRTextSegment]:  # 把 PaddleOCR 嵌套输出拍平成统一片段。
        segments: list[OCRTextSegment] = []
        line_no = 0
        for block in results or []:
            for line in block or []:
                if not isinstance(line, (list, tuple)) or len(line) < 2:
                    continue
                score_block = line[1]
                if isinstance(score_block, (list, tuple)) and score_block:
                    text = str(score_block[0]).strip()
                    if text:
                        confidence = None
                        if len(score_block) >= 2:
                            try:
                                confidence = float(score_block[1])
                            except (TypeError, ValueError):
                                confidence = None
                        line_no += 1
                        segments.append(
                            OCRTextSegment(
                                text=text,
                                page_no=page_no,
                                line_no=line_no,
                                confidence=confidence,
                            )
                        )
        return segments

    @staticmethod
    def _segments_to_text(segments: list[OCRTextSegment]) -> str:  # 统一把 OCR 片段恢复成文本，避免多处重复 join。
        return "\n".join(segment.text for segment in segments if segment.text.strip()).strip()

    @staticmethod
    def _build_mock_segments(text: str) -> list[OCRTextSegment]:  # mock OCR 也按行输出最小片段，保证 artifact 结构稳定。
        segments: list[OCRTextSegment] = []
        for line_no, line in enumerate((item.strip() for item in text.splitlines()), start=1):
            if not line:
                continue
            segments.append(OCRTextSegment(text=line, page_no=1, line_no=line_no, confidence=None))
        if not segments and text.strip():
            segments.append(OCRTextSegment(text=text.strip(), page_no=1, line_no=1, confidence=None))
        return segments
