import json  # 导入 json，用来落盘 chunk 结果文件。
from dataclasses import asdict, dataclass  # 导入 dataclass 以及把 dataclass 转成字典的工具。
from pathlib import Path  # 导入 Path，方便处理文件路径。
from typing import Callable  # 导入 Callable，用于定义阶段回调类型。

from ..core.config import Settings, get_settings  # 导入配置对象和配置获取函数。
from ..rag.chunkers.text_chunker import TextChunker  # 导入文本切分器。
from ..rag.embeddings.client import EmbeddingClient  # 导入 embedding 客户端。
from ..rag.parsers.document_parser import DocumentParser  # 导入文档解析器。
from ..rag.vectorstores.qdrant_store import QdrantVectorStore  # 导入 Qdrant 向量写入器。


@dataclass(slots=True)  # 用 dataclass 定义一个轻量级结果对象，并开启 slots 节省内存。
class DocumentIngestionResult:  # 描述一次文档入库完成后的结果。
    parser_name: str  # 本次使用的解析器名称。
    parsed_path: str  # 解析后纯文本文件路径。
    chunk_path: str  # chunk JSON 文件路径。
    chunk_count: int  # 生成的 chunk 数量。
    vector_count: int  # 成功写入的向量数量。
    collection_name: str  # 写入的 Qdrant collection 名称。


class DocumentIngestionService:  # 封装文档入库整条链路的业务逻辑。
    def __init__(self, settings: Settings | None = None) -> None:  # 初始化入库服务。
        self.settings = settings or get_settings()  # 优先使用传入配置，否则读取全局配置。
        self.parser = DocumentParser()  # 创建文档解析器。
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
        if on_stage is not None:  # 如果调用方传了阶段回调，就先标记解析阶段。
            on_stage("parsing", 10)  # 进入解析阶段，进度先更新到 10%。
        parsed_document = self.parser.parse(source_path=source_path, document_id=document_id, filename=filename)  # 先把原始文件解析成纯文本。

        parsed_path = self.settings.parsed_dir / f"{document_id}.txt"  # 计算解析后文本的落盘路径。
        parsed_path.write_text(parsed_document.text, encoding="utf-8")  # 把纯文本内容写到 parsed 目录。

        if on_stage is not None:  # 解析完成后进入切块阶段。
            on_stage("chunking", 35)  # 更新阶段和进度。
        chunks = self.chunker.split(document_id=document_id, text=parsed_document.text)  # 按配置把纯文本切成多个 chunk。
        if not chunks:  # 如果没有切出任何 chunk，说明文本不可用。
            raise ValueError(f"No chunks generated from '{filename}'.")  # 抛出业务错误，停止入库。

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
        )


def get_document_ingestion_service() -> DocumentIngestionService:  # 提供 FastAPI 或其他调用方使用的依赖入口。
    return DocumentIngestionService()  # 返回一个文档入库服务实例。
