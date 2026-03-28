import json  # 导入 json，用来落盘 chunk 结果文件。
from dataclasses import asdict, dataclass  # 导入 dataclass 以及把 dataclass 转成字典的工具。
from pathlib import Path  # 导入 Path，方便处理文件路径。
from typing import Literal
from typing import Callable  # 导入 Callable，用于定义阶段回调类型。

from ..core.config import Settings, get_settings  # 导入配置对象和配置获取函数。
from ..rag.chunkers.text_chunker import TextChunk, TextChunker  # 导入文本切分器与 chunk 结构。
from ..rag.embeddings.client import EmbeddingClient  # 导入 embedding 客户端。
from ..rag.ocr.client import OCRClient, OCRExtractionResult  # 导入 OCR 客户端和结果结构，给扫描件和图片补最小可用链路。
from ..rag.parsers.document_parser import DocumentParser  # 导入文档解析器。
from ..rag.parsers.document_parser import ParsedDocument
from ..rag.vectorstores.qdrant_store import QdrantVectorStore  # 导入 Qdrant 向量写入器。


@dataclass(slots=True)  # 用 dataclass 定义一个轻量级结果对象，并开启 slots 节省内存。
class DocumentIngestionResult:  # 描述一次文档入库完成后的结果。
    parser_name: str  # 本次使用的解析器名称。
    parsed_path: str  # 解析后纯文本文件路径。
    chunk_path: str  # chunk JSON 文件路径。
    chunk_count: int  # 生成的 chunk 数量。
    vector_count: int  # 成功写入的向量数量。
    collection_name: str  # 写入的 Qdrant collection 名称。
    ocr_artifact_path: str | None = None  # OCR 中间产物路径；仅 OCR 参与时返回。
    ocr_used: bool = False  # 本次是否实际使用了 OCR。
    final_status: Literal["completed", "partial_failed"] = "completed"  # OCR fallback 有非致命告警时允许落 partial_failed。
    warning_message: str | None = None  # OCR fallback 告警，供 job/document 状态展示。


@dataclass(slots=True)
class _OCRSegmentSpan:  # OCR 片段在最终 parsed text 上的字符范围，供 chunk 级标注复用。
    start: int
    end: int
    page_no: int | None
    confidence: float | None


class DocumentIngestionService:  # 封装文档入库整条链路的业务逻辑。
    def __init__(self, settings: Settings | None = None) -> None:  # 初始化入库服务。
        self.settings = settings or get_settings()  # 优先使用传入配置，否则读取全局配置。
        self.parser = DocumentParser()  # 创建文档解析器。
        self.ocr_client = OCRClient(self.settings)  # 创建 OCR 客户端，按 provider 决定是否真正启用 OCR。
        self.chunker = TextChunker(  # 根据配置创建文本切分器。
            chunk_size=self.settings.chunk_size_chars,  # 设置 chunk 目标大小。
            chunk_overlap=self.settings.chunk_overlap_chars,  # 设置 chunk 重叠长度。
            chunk_min_chars=self.settings.chunk_min_chars,  # 设置 chunk 最小长度阈值。
        )
        self.embedding_client = EmbeddingClient(self.settings)  # 创建 embedding 客户端。
        self.vector_store = QdrantVectorStore(self.settings)  # 创建 Qdrant 写入器。

    def ingest_document(  # 执行完整文档入库流程。
        self,
        *,
        document_id: str,
        filename: str,
        source_path: Path,
        on_stage: Callable[[str, int], None] | None = None,
    ) -> DocumentIngestionResult:
        parsed_document, ocr_result, warning_message = self._build_parsed_document(  # 先把原始文件通过原生解析/OCR 统一变成纯文本。
            document_id=document_id,
            filename=filename,
            source_path=source_path,
            on_stage=on_stage,
        )
        ocr_artifact_path = self._write_ocr_artifact(  # OCR 真正命中时把中间产物独立落盘，便于后续排查和质量分析。
            document_id=document_id,
            filename=filename,
            source_path=source_path,
            ocr_result=ocr_result,
        )

        parsed_path = self.settings.parsed_dir / f"{document_id}.txt"  # 计算解析后文本的落盘路径。
        parsed_path.write_text(parsed_document.text, encoding="utf-8")  # 把纯文本内容写到 parsed 目录。

        if on_stage is not None:  # 解析完成后进入切块阶段。
            on_stage("chunking", 35)  # 更新阶段和进度。
        chunks = self.chunker.split(document_id=document_id, text=parsed_document.text)  # 按配置把纯文本切成多个 chunk。
        if not chunks:  # 如果没有切出任何 chunk，说明文本不可用。
            raise ValueError(f"No chunks generated from '{filename}'.")  # 抛出业务错误，停止入库。
        self._annotate_chunk_metadata(  # 把 OCR/parser 元数据真正带进 chunk，给后续检索与 rerank 复用。
            chunks=chunks,
            parsed_text=parsed_document.text,
            parser_name=parsed_document.parser_name,
            ocr_result=ocr_result,
        )

        chunk_path = self.settings.chunk_dir / f"{document_id}.json"  # 计算 chunk 结果 JSON 的落盘路径。
        chunk_payload = [asdict(chunk) for chunk in chunks]  # 把每个 chunk dataclass 转成字典，方便序列化。
        chunk_path.write_text(  # 把 chunk 结果写入磁盘，便于调试和后续追溯。
            json.dumps(chunk_payload, ensure_ascii=False, indent=2),  # 以易读的 JSON 格式保存，保留中文。
            encoding="utf-8",  # 使用 utf-8 编码写文件。
        )

        if on_stage is not None:  # 切块完成后进入 embedding 阶段。
            on_stage("embedding", 65)  # 更新阶段和进度。
        embeddings = self.embedding_client.embed_texts([chunk.text for chunk in chunks])  # 对所有 chunk 文本生成向量。
        if len(embeddings) != len(chunks):  # 如果向量数量和 chunk 数量不一致，说明依赖返回异常。
            raise RuntimeError("Embedding count does not match chunk count.")  # 抛出运行时错误。

        if on_stage is not None:  # embedding 完成后进入索引阶段。
            on_stage("indexing", 90)  # 更新阶段和进度。
        vector_count = self.vector_store.upsert_document(  # 把 chunk 和向量一起写入 Qdrant。
            chunks=chunks,  # 传入 chunk 列表。
            embeddings=embeddings,  # 传入对应的向量列表。
            document_name=filename,  # 传入原始文档名，写进 payload。
            source_path=str(source_path),  # 传入原始文件路径，写进 payload。
            parsed_path=str(parsed_path),  # 传入解析文本路径，写进 payload。
        )

        return DocumentIngestionResult(  # 把入库执行结果封装返回给调用方。
            parser_name=parsed_document.parser_name,  # 返回解析器名称。
            parsed_path=str(parsed_path),  # 返回纯文本路径。
            chunk_path=str(chunk_path),  # 返回 chunk JSON 路径。
            chunk_count=len(chunks),  # 返回生成的 chunk 数量。
            vector_count=vector_count,  # 返回实际写入的向量数量。
            collection_name=self.settings.qdrant_collection,  # 返回目标 collection 名称。
            ocr_artifact_path=ocr_artifact_path,  # 返回 OCR artifact 路径。
            ocr_used=ocr_result is not None,  # 返回是否使用了 OCR。
            final_status="partial_failed" if warning_message else "completed",  # 有 OCR 告警时落 partial_failed。
            warning_message=warning_message,
        )

    def _build_parsed_document(
        self,
        *,
        document_id: str,
        filename: str,
        source_path: Path,
        on_stage: Callable[[str, int], None] | None = None,
    ) -> tuple[ParsedDocument, OCRExtractionResult | None, str | None]:  # 把原生解析和 OCR fallback 收口在一起，避免外层自己拼流程。
        suffix = self.parser.resolve_suffix(source_path=source_path, filename=filename)
        if self.parser.is_ocr_image_suffix(suffix):  # 图片文档直接走 OCR-only 链路。
            if on_stage is not None:
                on_stage("ocr_processing", 20)
            ocr_result = self.ocr_client.extract_image_text(source_path=source_path, filename=filename)
            normalized_text = self.parser.normalize_text(ocr_result.text)
            if not normalized_text:
                raise ValueError(f"No extractable text found in '{filename}'.")
            return (
                ParsedDocument(
                    document_id=document_id,
                    filename=filename,
                    parser_name=ocr_result.parser_name,
                    text=normalized_text,
                ),
                ocr_result,
                ocr_result.warning_message,
            )

        if on_stage is not None:
            on_stage("parsing", 10)
        parsed_document = self.parser.parse(
            source_path=source_path,
            document_id=document_id,
            filename=filename,
            allow_empty=suffix == ".docx",
        )
        if suffix == ".docx":  # DOCX 允许正文为空，再补一轮嵌图 OCR。
            docx_image_paths = self.parser.list_docx_embedded_image_paths(source_path)
            if not docx_image_paths:
                if parsed_document.text:
                    return parsed_document, None, None
                raise ValueError(f"No extractable text found in '{filename}'.")

            if not self.ocr_client.is_enabled():
                if parsed_document.text:
                    return parsed_document, None, None
                raise ValueError(f"No extractable text found in '{filename}'.")

            if on_stage is not None:
                on_stage("ocr_processing", 20)
            try:
                ocr_result = self.ocr_client.extract_docx_embedded_image_text(
                    source_path=source_path,
                    filename=filename,
                    image_paths=docx_image_paths,
                )
            except RuntimeError as exc:
                if parsed_document.text:
                    return parsed_document, None, str(exc)
                raise

            if ocr_result is None:
                if parsed_document.text:
                    return parsed_document, None, None
                raise ValueError(f"No extractable text found in '{filename}'.")

            merged_text = self._merge_native_and_ocr_text(parsed_document.text, ocr_result.text)
            normalized_text = self.parser.normalize_text(merged_text)
            if not normalized_text:
                raise ValueError(f"No extractable text found in '{filename}'.")
            return (
                ParsedDocument(
                    document_id=document_id,
                    filename=filename,
                    parser_name=parsed_document.parser_name,
                    text=normalized_text,
                ),
                ocr_result,
                ocr_result.warning_message,
            )
        if suffix != ".pdf" or not self.parser.should_attempt_pdf_ocr(
            parsed_document.text,
            min_chars=self.settings.ocr_pdf_native_text_min_chars,
        ):
            return parsed_document, None, None

        if on_stage is not None:
            on_stage("ocr_processing", 20)
        try:
            ocr_result = self.ocr_client.extract_pdf_text(source_path=source_path, filename=filename)
        except RuntimeError as exc:
            if parsed_document.text:  # 原生文本仍然可用时，保留结果并标记 partial_failed。
                return parsed_document, None, str(exc)
            raise

        merged_text = self._merge_native_and_ocr_text(parsed_document.text, ocr_result.text)
        normalized_text = self.parser.normalize_text(merged_text)
        if not normalized_text:
            raise ValueError(f"No extractable text found in '{filename}'.")
        return (
            ParsedDocument(
                document_id=document_id,
                filename=filename,
                parser_name=ocr_result.parser_name,
                text=normalized_text,
            ),
            ocr_result,
            ocr_result.warning_message,
        )

    def _write_ocr_artifact(
        self,
        *,
        document_id: str,
        filename: str,
        source_path: Path,
        ocr_result: OCRExtractionResult | None,
    ) -> str | None:  # OCR 中间产物独立落盘，避免和最终 parsed text 混写。
        if ocr_result is None:
            return None
        artifact_path = self.settings.ocr_artifact_dir / f"{document_id}.json"
        page_numbers = {segment.page_no for segment in ocr_result.segments if segment.page_no is not None}
        payload = {
            "document_id": document_id,
            "file_name": filename,
            "source_path": str(source_path),
            "parser_name": ocr_result.parser_name,
            "warning_message": ocr_result.warning_message,
            "segment_count": len(ocr_result.segments),
            "page_count": len(page_numbers) if page_numbers else (1 if ocr_result.segments else 0),
            "normalized_text": self.parser.normalize_text(ocr_result.text),
            "segments": [asdict(segment) for segment in ocr_result.segments],
        }
        artifact_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(artifact_path)

    def _annotate_chunk_metadata(
        self,
        *,
        chunks: list[TextChunk],
        parsed_text: str,
        parser_name: str,
        ocr_result: OCRExtractionResult | None,
    ) -> None:  # 把解析来源和 OCR 质量信息补到 chunk，避免后续检索/生成回头读 artifact。
        for chunk in chunks:
            chunk.parser_name = parser_name

        if ocr_result is None:
            return

        overall_confidence = self._average_confidence(segment.confidence for segment in ocr_result.segments)
        single_page_hint = self._resolve_single_page_hint(ocr_result)
        segment_spans = self._build_ocr_segment_spans(parsed_text=parsed_text, ocr_result=ocr_result)

        if not segment_spans:  # 无法映射回原文时，回退到文档级 OCR 标注，避免 OCR 证据完全丢失。
            for chunk in chunks:
                chunk.ocr_used = True
                chunk.parser_name = ocr_result.parser_name
                chunk.ocr_confidence = overall_confidence
                chunk.quality_score = overall_confidence
                if single_page_hint is not None:
                    chunk.page_no = single_page_hint
            return

        for chunk in chunks:
            overlapping_spans = [
                span
                for span in segment_spans
                if min(chunk.char_end, span.end) > max(chunk.char_start, span.start)
            ]
            if not overlapping_spans:
                continue

            chunk.ocr_used = True
            chunk.parser_name = ocr_result.parser_name
            chunk.ocr_confidence = overall_confidence
            chunk.quality_score = overall_confidence
            if single_page_hint is not None:
                chunk.page_no = single_page_hint

            page_overlap: dict[int, int] = {}
            for span in overlapping_spans:
                overlap = min(chunk.char_end, span.end) - max(chunk.char_start, span.start)
                if overlap <= 0 or span.page_no is None:
                    continue
                page_overlap[span.page_no] = page_overlap.get(span.page_no, 0) + overlap
            if page_overlap:
                chunk.page_no = max(page_overlap.items(), key=lambda item: (item[1], -item[0]))[0]

            span_confidence = self._average_confidence(span.confidence for span in overlapping_spans)
            if span_confidence is not None:
                chunk.ocr_confidence = span_confidence
                chunk.quality_score = span_confidence

    def _build_ocr_segment_spans(
        self,
        *,
        parsed_text: str,
        ocr_result: OCRExtractionResult,
    ) -> list[_OCRSegmentSpan]:  # 尝试把 OCR 片段映射回最终 parsed text，为页码和置信度做 chunk 级归因。
        normalized_ocr_text = self.parser.normalize_text(ocr_result.text)
        if not normalized_ocr_text:
            return []

        ocr_base_offset = parsed_text.find(normalized_ocr_text)
        if ocr_base_offset < 0:
            return []

        spans: list[_OCRSegmentSpan] = []
        local_cursor = 0
        for segment in ocr_result.segments:
            normalized_segment_text = self.parser.normalize_text(segment.text)
            if not normalized_segment_text:
                continue
            local_index = normalized_ocr_text.find(normalized_segment_text, local_cursor)
            if local_index < 0:
                local_index = normalized_ocr_text.find(normalized_segment_text)
            if local_index < 0:
                continue
            span_start = ocr_base_offset + local_index
            span_end = span_start + len(normalized_segment_text)
            spans.append(
                _OCRSegmentSpan(
                    start=span_start,
                    end=span_end,
                    page_no=segment.page_no,
                    confidence=segment.confidence,
                )
            )
            local_cursor = local_index + len(normalized_segment_text)
        return spans

    @staticmethod
    def _average_confidence(values) -> float | None:  # 统一聚合 OCR 置信度，避免多处重复过滤 None。
        available = [float(value) for value in values if value is not None]
        if not available:
            return None
        return round(sum(available) / len(available), 4)

    @staticmethod
    def _resolve_single_page_hint(ocr_result: OCRExtractionResult) -> int | None:  # 单页 OCR 文档统一把 page_no 标成同一页。
        pages = {segment.page_no for segment in ocr_result.segments if segment.page_no is not None}
        if len(pages) != 1:
            return None
        return next(iter(pages))

    @staticmethod
    def _merge_native_and_ocr_text(native_text: str, ocr_text: str) -> str:  # 合并 PDF 原生文本和 OCR 文本，优先保留信息量更大的版本。
        normalized_native = native_text.strip()
        normalized_ocr = ocr_text.strip()
        if not normalized_native:
            return normalized_ocr
        if not normalized_ocr:
            return normalized_native
        if normalized_native in normalized_ocr:
            return normalized_ocr
        if normalized_ocr in normalized_native:
            return normalized_native
        return f"{normalized_native}\n\n{normalized_ocr}"


def get_document_ingestion_service() -> DocumentIngestionService:  # 提供 FastAPI 或其他调用方使用的依赖入口。
    return DocumentIngestionService()  # 返回一个文档入库服务实例。
