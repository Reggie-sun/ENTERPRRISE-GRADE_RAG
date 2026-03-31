"""OCR 客户端，支持 PaddleOCR 引擎。

提供图片、PDF 和 DOCX 嵌入图片的 OCR 文字识别能力，
支持 mock（本地联调）和 paddleocr 两种 provider，
内置依赖探测、健康状态汇报和按页/按图选择性 OCR。
"""
import importlib.util  # 导入 importlib，便于做 OCR 依赖可用性探测而不强制导入大包。
import os  # 读取当前进程信息，并给 Paddle 运行时注入一次性环境变量。
from dataclasses import dataclass, field  # 导入 dataclass，用于封装 OCR 结果。
from pathlib import Path  # 导入 Path，方便处理 sidecar 和临时图片文件。
from tempfile import TemporaryDirectory  # 导入临时目录，给 PDF 渲染页落地用。
from typing import Any  # 导入 Any，兼容第三方 OCR 客户端的动态返回类型。
from zipfile import ZipFile  # 导入 ZipFile，给 DOCX 嵌图 OCR 提供最小 zip 读取能力。

from ...core.config import Settings, get_settings  # 导入统一配置对象，避免 OCR 自己再维护一套 env 解析。
from ..parsers.document_parser import DocumentParser, OCR_IMAGE_SUFFIXES  # 复用解析层定义的 OCR-only 图片后缀集合。


class OCRUnavailableError(RuntimeError):
    """OCR provider 未配置或依赖缺失时统一抛出的异常类型。"""
    pass


_PADDLE_OCR_SINGLETONS: dict[tuple[int, bool, str], Any] = {}  # PaddleX 运行时不支持同进程重复初始化，按进程+配置做单例缓存。


@dataclass(slots=True)  # OCR 片段统一收口，便于后续保存 artifact 和做 OCR 质量分析。
class OCRTextSegment:
    """单条 OCR 识别片段，包含文本、页码、行号和置信度。"""
    text: str  # 当前 OCR 片段文本。
    page_no: int | None = None  # 当前片段所在页码；图片统一视为第 1 页。
    line_no: int | None = None  # 当前页内的行号，便于排查 OCR 乱序或丢字。
    confidence: float | None = None  # OCR 置信度，供后续人工复核或质量评估复用。


@dataclass(slots=True)  # OCR 结果统一收口，给入库服务决定是 completed 还是 partial_failed。
class OCRExtractionResult:
    """OCR 提取结果，包含解析器名称、文本、告警和分段明细。"""
    parser_name: str  # 本次 OCR 使用的解析器名称。
    text: str  # 抽出的文本结果。
    warning_message: str | None = None  # 非致命告警，例如 PDF 个别页 OCR 失败。
    segments: list[OCRTextSegment] = field(default_factory=list)  # OCR 中间片段，单独落盘后可供排障和质量分析。


class OCRClient:  # 封装 OCR provider 的最小统一入口。
    """OCR 客户端：封装图片/PDF/DOCX 嵌图的文字识别逻辑。

    支持 mock（本地联调）和 paddleocr（PaddleOCR 引擎）两种 provider，
    内置依赖探测和运行状态汇报，便于 ops 页面展示。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """初始化 OCR 客户端，settings 为空时自动获取全局配置。"""
        self.settings = settings or get_settings()

    def is_enabled(self) -> bool:
        """判断当前 OCR 是否已启用（provider 不是 disabled）。"""
        return self.settings.ocr_provider.lower().strip() != "disabled"

    @staticmethod
    def is_ocr_image_suffix(suffix: str) -> bool:
        """判断给定后缀是否属于 OCR 图片类型（复用解析层的后缀集合）。"""
        return suffix.lower() in OCR_IMAGE_SUFFIXES

    def extract_image_text(self, *, source_path: Path, filename: str) -> OCRExtractionResult:
        """对单张图片执行 OCR 文字识别。"""
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

    def extract_pdf_text(
        self,
        *,
        source_path: Path,
        filename: str,
        page_numbers: list[int] | None = None,
    ) -> OCRExtractionResult:
        """对 PDF 执行 OCR fallback，允许仅对指定页码做选择性 OCR。"""
        provider = self.settings.ocr_provider.lower().strip()
        if provider == "disabled":
            raise OCRUnavailableError("OCR provider is disabled for PDF fallback.")
        if provider == "mock":
            return self._extract_with_mock(source_path=source_path, filename=filename, parser_name="pdf_ocr_mock")
        if provider == "paddleocr":
            return self._extract_pdf_text_with_paddle(source_path, page_numbers=page_numbers)
        raise OCRUnavailableError(f"Unsupported OCR provider: {self.settings.ocr_provider}")

    def extract_docx_embedded_image_text(
        self,
        *,
        source_path: Path,
        filename: str,
        image_paths: list[str] | None = None,
    ) -> OCRExtractionResult | None:
        """对 DOCX 内嵌图片执行 OCR，返回独立 artifact 文本；无嵌图时返回 None。"""
        resolved_image_paths = image_paths or DocumentParser.list_docx_embedded_image_paths(source_path)
        if not resolved_image_paths:
            return None

        provider = self.settings.ocr_provider.lower().strip()
        if provider == "disabled":
            raise OCRUnavailableError("OCR provider is disabled for DOCX embedded images.")
        if provider == "mock":
            mock_result = self._extract_with_mock(
                source_path=source_path,
                filename=filename,
                parser_name="docx_embedded_image_ocr_mock",
            )
            return OCRExtractionResult(
                parser_name="docx_embedded_image_ocr_mock",
                text=mock_result.text,
                warning_message=mock_result.warning_message,
                segments=self._reindex_segments(mock_result.segments, page_no=None),
            )
        if provider == "paddleocr":
            return self._extract_docx_embedded_image_text_with_paddle(source_path, resolved_image_paths)
        raise OCRUnavailableError(f"Unsupported OCR provider: {self.settings.ocr_provider}")

    def get_runtime_status(self) -> dict[str, Any]:
        """返回当前 OCR provider 的最小运行状态，供 health/ops 页面直接展示。"""
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

    def _extract_with_mock(self, *, source_path: Path, filename: str, parser_name: str) -> OCRExtractionResult:
        """测试和联调阶段用 sidecar 文本文件模拟 OCR 输出。"""
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

    def _extract_image_segments_with_paddle(self, source_path: Path, *, page_no: int | None) -> list[OCRTextSegment]:
        """让 PaddleOCR 直接识别图片，返回带页码和行号的片段明细。"""
        ocr = self._get_paddle_ocr()
        results = list(ocr.predict(str(source_path)))
        return self._flatten_paddle_results(results, page_no=page_no)

    def _extract_pdf_text_with_paddle(
        self,
        source_path: Path,
        *,
        page_numbers: list[int] | None = None,
    ) -> OCRExtractionResult:
        """把 PDF 每页渲染成图片后交给 PaddleOCR；允许只处理指定页码。"""
        try:
            import fitz  # type: ignore[import-not-found]
        except ImportError as exc:
            raise OCRUnavailableError("PyMuPDF is required for PDF OCR fallback but is not installed.") from exc

        page_texts: list[str] = []
        segments: list[OCRTextSegment] = []
        failed_pages: list[int] = []
        target_pages = set(page_numbers or [])
        with TemporaryDirectory(prefix="ocr_pdf_") as temp_dir:
            with fitz.open(str(source_path)) as pdf:
                for page_index, page in enumerate(pdf, start=1):
                    if target_pages and page_index not in target_pages:
                        continue
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

    def _extract_docx_embedded_image_text_with_paddle(
        self,
        source_path: Path,
        image_paths: list[str],
    ) -> OCRExtractionResult:
        """把 DOCX 内嵌图片逐张抽出并交给 PaddleOCR 识别。"""
        image_texts: list[str] = []
        all_segments: list[OCRTextSegment] = []
        failed_images: list[str] = []
        next_line_no = 1
        with ZipFile(source_path) as archive, TemporaryDirectory(prefix="ocr_docx_") as temp_dir:
            for index, image_path in enumerate(image_paths, start=1):
                temp_path = Path(temp_dir) / f"embedded_{index}{Path(image_path).suffix.lower() or '.img'}"
                try:
                    temp_path.write_bytes(archive.read(image_path))
                    image_segments = self._extract_image_segments_with_paddle(temp_path, page_no=None)
                except Exception:
                    failed_images.append(Path(image_path).name)
                    continue

                reindexed_segments = self._reindex_segments(image_segments, start_line_no=next_line_no, page_no=None)
                next_line_no += len(reindexed_segments)
                image_text = self._segments_to_text(reindexed_segments).strip()
                if image_text:
                    image_texts.append(image_text)
                    all_segments.extend(reindexed_segments)

        if not image_texts:
            raise OCRUnavailableError(f"OCR did not extract any text from DOCX embedded images in '{source_path.name}'.")

        warning_message = None
        if failed_images:
            warning_message = (
                "OCR failed on DOCX embedded images: " + ", ".join(failed_images) + ". Continued with remaining images."
            )
        return OCRExtractionResult(
            parser_name="docx_embedded_image_ocr_paddle",
            text="\n\n".join(image_texts),
            warning_message=warning_message,
            segments=all_segments,
        )

    def _get_paddle_ocr(self) -> Any:
        """懒加载 PaddleOCR 引擎，按进程+配置做单例缓存，避免重复初始化。"""
        use_textline_orientation = (
            self.settings.ocr_paddle_use_textline_orientation or self.settings.ocr_paddle_use_angle_cls
        )
        cache_key = (
            os.getpid(),
            self.settings.ocr_paddle_use_doc_orientation_classify,
            self.settings.ocr_paddle_use_doc_unwarping,
            use_textline_orientation,
            self.settings.ocr_paddle_ocr_version,
            self.settings.ocr_paddle_text_detection_model_name,
            self.settings.ocr_paddle_text_recognition_model_name,
            self.settings.ocr_language,
        )
        cached = _PADDLE_OCR_SINGLETONS.get(cache_key)
        if cached is not None:
            return cached
        try:
            from paddleocr import PaddleOCR  # type: ignore[import-not-found]
        except ImportError as exc:
            raise OCRUnavailableError(
                "PaddleOCR import failed. Install requirements/ocr-*.txt and required system libraries. "
                f"Original import error: {exc}"
            ) from exc

        # 关闭 PaddleX 启动时的模型源连通性探测，避免本地 worker 每次首轮 OCR 额外卡在网络检查。
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        ocr = PaddleOCR(
            lang=self.settings.ocr_language,
            ocr_version=self.settings.ocr_paddle_ocr_version,
            use_doc_orientation_classify=self.settings.ocr_paddle_use_doc_orientation_classify,
            use_doc_unwarping=self.settings.ocr_paddle_use_doc_unwarping,
            use_textline_orientation=use_textline_orientation,
            text_detection_model_name=self.settings.ocr_paddle_text_detection_model_name,
            text_recognition_model_name=self.settings.ocr_paddle_text_recognition_model_name,
        )
        _PADDLE_OCR_SINGLETONS[cache_key] = ocr
        return ocr

    @staticmethod
    def _detect_paddle_dependencies() -> list[str]:
        """仅做依赖探测（paddleocr、fitz），不主动导入，返回缺失包名列表。"""
        missing: list[str] = []
        if importlib.util.find_spec("paddleocr") is None:
            missing.append("paddleocr")
        if importlib.util.find_spec("fitz") is None:
            missing.append("fitz")
        return missing

    @staticmethod
    def _flatten_paddle_results(results: Any, *, page_no: int | None) -> list[OCRTextSegment]:
        """把 PaddleOCR 嵌套输出拍平成统一的 OCRTextSegment 列表。"""
        segments: list[OCRTextSegment] = []
        line_no = 0
        for block in results or []:
            rec_texts = getattr(block, "rec_texts", None)
            rec_scores = getattr(block, "rec_scores", None)
            if isinstance(block, dict):
                rec_texts = rec_texts or block.get("rec_texts")
                rec_scores = rec_scores or block.get("rec_scores")
            if rec_texts:
                for index, text in enumerate(rec_texts, start=1):
                    normalized_text = str(text).strip()
                    if not normalized_text:
                        continue
                    confidence = None
                    if rec_scores and index - 1 < len(rec_scores):
                        try:
                            confidence = float(rec_scores[index - 1])
                        except (TypeError, ValueError):
                            confidence = None
                    line_no += 1
                    segments.append(
                        OCRTextSegment(
                            text=normalized_text,
                            page_no=page_no,
                            line_no=line_no,
                            confidence=confidence,
                        )
                    )
                continue
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
    def _segments_to_text(segments: list[OCRTextSegment]) -> str:
        """统一把 OCR 片段按行拼接成文本，过滤空白行。"""
        return "\n".join(segment.text for segment in segments if segment.text.strip()).strip()

    @staticmethod
    def _build_mock_segments(text: str) -> list[OCRTextSegment]:
        """mock OCR 也按行输出最小片段，保证 artifact 结构稳定。"""
        segments: list[OCRTextSegment] = []
        for line_no, line in enumerate((item.strip() for item in text.splitlines()), start=1):
            if not line:
                continue
            segments.append(OCRTextSegment(text=line, page_no=1, line_no=line_no, confidence=None))
        if not segments and text.strip():
            segments.append(OCRTextSegment(text=text.strip(), page_no=1, line_no=1, confidence=None))
        return segments

    @staticmethod
    def _reindex_segments(
        segments: list[OCRTextSegment],
        *,
        start_line_no: int = 1,
        page_no: int | None,
    ) -> list[OCRTextSegment]:
        """重排片段行号使其连续，并允许覆盖页码（DOCX 场景下统一去掉页码语义）。"""
        reindexed: list[OCRTextSegment] = []
        next_line_no = start_line_no
        for segment in segments:
            reindexed.append(
                OCRTextSegment(
                    text=segment.text,
                    page_no=page_no if page_no is not None else None,
                    line_no=next_line_no,
                    confidence=segment.confidence,
                )
            )
            next_line_no += 1
        return reindexed
