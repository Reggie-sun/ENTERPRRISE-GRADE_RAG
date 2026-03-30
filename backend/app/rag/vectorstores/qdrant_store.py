from collections.abc import Iterator
from pathlib import Path  # 导入 Path，用于统一本地路径配置的缓存 key。
import threading  # 导入线程锁，避免多线程并发创建客户端时产生竞态。
from uuid import NAMESPACE_URL, uuid5  # 导入 uuid5，用来为 Qdrant point 生成稳定 UUID。

from qdrant_client import QdrantClient  # 导入 Qdrant 客户端。
from qdrant_client.http import models  # 导入 Qdrant HTTP 模型定义。

from ...core.config import Settings  # 导入配置对象。
from ..chunkers.text_chunker import TextChunk  # 导入 TextChunk 结构，用来描述待写入的文本片段。


class QdrantVectorStore:  # 封装 Qdrant 读写逻辑。
    _CLIENT_CACHE: dict[str, QdrantClient] = {}  # 复用同一配置下的客户端，避免本地路径模式重复加锁。
    _CLIENT_CACHE_LOCK = threading.Lock()  # 保护类级缓存，避免并发创建同一客户端。

    def __init__(self, settings: Settings) -> None:  # 初始化 Qdrant 存储对象。
        self.settings = settings  # 保存配置对象。
        self._client: QdrantClient | None = None  # 先把客户端置空，等真正使用时再懒加载。

    @property  # 把 client 做成属性，调用方可以像访问字段一样使用。
    def client(self) -> QdrantClient:  # 惰性获取 Qdrant 客户端实例。
        if self._client is None:  # 如果客户端还没有创建。
            self._client = self._get_or_build_client()  # 复用或创建客户端实例。
        return self._client  # 返回客户端实例。

    def upsert_document(  # 把一份文档的所有 chunk 和对应向量写入 Qdrant。
        self,  # 当前存储对象实例。
        chunks: list[TextChunk],  # 待写入的 chunk 列表。
        embeddings: list[list[float]],  # 与 chunk 一一对应的向量列表。
        *,  # 下面这些参数必须显式按关键字传入。
        document_name: str,  # 原始文档名。
        source_path: str,  # 原始文档路径。
        parsed_path: str,  # 解析后文本路径。
    ) -> int:
        if not chunks or not embeddings:  # 如果没有任何内容需要写入。
            return 0  # 直接返回 0。
        if len(chunks) != len(embeddings):  # 如果 chunk 数和向量数不一致。
            raise RuntimeError("Chunk count does not match embedding count.")  # 抛出错误，阻止写入错位数据。

        vector_size = len(embeddings[0])  # 从第一条向量推断当前向量维度。
        self._ensure_collection(vector_size)  # 确保目标 collection 已存在，并且维度已配置。

        points = [  # 把 chunk 和向量组装成 Qdrant PointStruct 列表。
            models.PointStruct(  # 创建一条点位结构。
                id=str(uuid5(NAMESPACE_URL, chunk.chunk_id)),  # 用稳定 UUID 作为 Qdrant point id。
                vector=embedding,  # 写入向量内容。
                payload={  # 同时写入 payload 元数据，方便检索后追溯。
                    "chunk_id": chunk.chunk_id,  # 保存 chunk 自己的业务 ID。
                    "document_id": chunk.document_id,  # 保存所属文档 ID。
                    "document_name": document_name,  # 保存文档名。
                    "chunk_index": chunk.chunk_index,  # 保存 chunk 序号。
                    "text": chunk.text,  # 保存 chunk 文本内容。
                    "source_path": source_path,  # 保存原始文件路径。
                    "parsed_path": parsed_path,  # 保存解析文本路径。
                    "char_start": chunk.char_start,  # 保存原文起始位置。
                    "char_end": chunk.char_end,  # 保存原文结束位置。
                    "ocr_used": chunk.ocr_used,  # 标记当前 chunk 是否来自 OCR 参与链路。
                    "parser_name": chunk.parser_name,  # 保存解析器名称，方便排查 chunk 来源。
                    "page_no": chunk.page_no,  # OCR 可可靠定位时保存页码。
                    "ocr_confidence": chunk.ocr_confidence,  # 保存 OCR 置信度摘要，供后续质量分析。
                    "quality_score": chunk.quality_score,  # 保存统一质量分，为后续排序增强预留。
                },
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)  # 严格按一一对应关系配对 chunk 和向量。
        ]

        self.client.upsert(  # 调用 Qdrant upsert 接口写入数据。
            collection_name=self.settings.qdrant_collection,  # 指定目标 collection。
            points=points,  # 传入本次要写入的全部点位。
            wait=True,  # 等待写入完成再返回。
        )
        return len(points)  # 返回本次成功提交的点位数量。

    def count_points(self) -> int:  # 统计当前 collection 里的点位数量。
        if not self._collection_exists(self.settings.qdrant_collection):  # collection 尚未创建时直接返回 0，避免把“没有数据”当异常。
            return 0
        result = self.client.count(  # 调用 Qdrant 计数接口。
            collection_name=self.settings.qdrant_collection,  # 指定目标 collection。
            exact=True,  # 要求精确计数。
        )
        return int(result.count)  # 把返回值转换成 Python int。

    def has_document_points(self, document_id: str) -> bool:  # 判断当前 collection 里是否存在指定文档的向量点位。
        normalized_document_id = document_id.strip()  # 统一清理空白，避免把空字符串当有效文档 ID。
        if not normalized_document_id:  # 空文档 ID 直接视为不存在。
            return False
        if not self._collection_exists(self.settings.qdrant_collection):  # collection 不存在时无需继续查询。
            return False

        result = self.client.count(  # 按 document_id 过滤当前 collection，判断是否至少存在一个 point。
            collection_name=self.settings.qdrant_collection,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=normalized_document_id),
                    )
                ]
            ),
            exact=True,
        )
        return int(result.count) > 0  # 只要有一个 point 就说明该文档已经入向量库。

    def delete_document_points(self, document_id: str) -> int:  # 按文档 ID 删除当前 collection 下的所有向量点位。
        normalized_document_id = document_id.strip()  # 统一清理空白，避免把空字符串当有效文档 ID。
        if not normalized_document_id:  # 空文档 ID 直接视为无需删除。
            return 0
        if not self._collection_exists(self.settings.qdrant_collection):  # collection 不存在时直接视为已清理。
            return 0

        pre_count = self.client.count(  # 删除前先统计该文档当前点位数量，便于返回删除计数。
            collection_name=self.settings.qdrant_collection,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=normalized_document_id),
                    )
                ]
            ),
            exact=True,
        )
        removed = int(pre_count.count)
        if removed <= 0:  # 没有命中点位时无需触发 delete 请求。
            return 0

        self.client.delete(  # 按 document_id 过滤删除整份文档的所有点位。
            collection_name=self.settings.qdrant_collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=normalized_document_id),
                        )
                    ]
                )
            ),
            wait=True,
        )
        return removed  # 返回删除前统计值，作为本次清理数量。

    def search(  # 按查询向量检索最相似的 chunk。
        self,
        query_vector: list[float],
        *,
        limit: int,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[models.ScoredPoint]:
        if not query_vector or limit <= 0:  # 空向量或非法 limit 不执行检索。
            return []  # 直接返回空结果。
        if not self._collection_exists(self.settings.qdrant_collection):  # 目标 collection 不存在时直接返回空结果。
            return []  # 让上层按“暂无数据”处理，而不是抛 500。

        query_filter = self._build_document_filter(document_id=document_id, document_ids=document_ids)  # 统一构造单文档或多文档过滤条件。

        response = self.client.query_points(  # 调用 Qdrant 向量检索接口。
            collection_name=self.settings.qdrant_collection,  # 指定检索的 collection。
            query=query_vector,  # 传入查询向量。
            query_filter=query_filter,  # 可选文档过滤条件。
            limit=limit,  # 限制返回条数。
            with_payload=True,  # 需要 payload 才能返回 chunk 文本和文档元信息。
            with_vectors=False,  # 响应里不回传向量，减少传输开销。
        )
        return list(response.points)  # 统一返回 ScoredPoint 列表。

    def scroll_records(  # 顺序遍历当前 collection 里的 payload 记录，供轻量 lexical retrieval 复用。
        self,
        *,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
        batch_size: int = 256,
    ) -> Iterator[models.Record]:
        if batch_size <= 0:  # 非法批大小直接视为空迭代，避免落到 Qdrant 参数错误。
            return
        if not self._collection_exists(self.settings.qdrant_collection):  # collection 不存在时直接返回空迭代。
            return

        scroll_filter = self._build_document_filter(document_id=document_id, document_ids=document_ids)  # 复用统一文档过滤条件，保证 vector / lexical 语义一致。
        offset: int | str | models.PointId | None = None
        while True:
            records, next_offset = self.client.scroll(
                collection_name=self.settings.qdrant_collection,
                scroll_filter=scroll_filter,
                offset=offset,
                limit=batch_size,
                with_payload=True,
                with_vectors=False,
            )
            if not records:
                break
            for record in records:
                yield record
            if next_offset is None:
                break
            offset = next_offset

    def _ensure_collection(self, vector_size: int) -> None:  # 确保目标 collection 已创建。
        if self._collection_exists(self.settings.qdrant_collection):  # 如果目标 collection 已存在。
            return  # 直接返回，不重复创建。

        self.client.create_collection(  # 创建新的 collection。
            collection_name=self.settings.qdrant_collection,  # 指定 collection 名称。
            vectors_config=models.VectorParams(  # 配置向量参数。
                size=vector_size,  # 设置向量维度。
                distance=models.Distance.COSINE,  # 设置相似度距离为余弦距离。
            ),
        )

    def _build_client(self) -> QdrantClient:  # 按配置创建 Qdrant 客户端。
        qdrant_url = self.settings.qdrant_url.strip()  # 读取并清理配置里的 Qdrant 地址。
        if qdrant_url == ":memory:":  # 如果配置成内存模式。
            return QdrantClient(":memory:")  # 创建内存版 Qdrant 客户端，适合本地测试。
        if qdrant_url.startswith(("http://", "https://")):  # 如果是 HTTP 或 HTTPS 地址。
            return QdrantClient(  # 创建远程服务客户端。
                url=qdrant_url,  # 显式传入远程 Qdrant 地址。
                trust_env=False,  # 忽略系统代理，避免 localhost/内网 Qdrant 被代理环境带偏。
            )
        return QdrantClient(path=qdrant_url)  # 否则按本地磁盘路径模式创建客户端。

    def _get_or_build_client(self) -> QdrantClient:  # 复用同配置客户端，避免本地存储重复加锁。
        cache_key = self._client_cache_key()  # 计算当前配置对应的缓存 key。
        if cache_key is None:  # 内存模式不做全局缓存，避免测试之间串数据。
            return self._build_client()  # 直接创建新客户端。
        with self._CLIENT_CACHE_LOCK:  # 并发场景下串行读取/写入缓存，避免重复构建同一客户端。
            client = self._CLIENT_CACHE.get(cache_key)  # 先从缓存拿客户端。
            if client is None:  # 缓存中不存在时再创建并写入缓存。
                client = self._build_client()
                self._CLIENT_CACHE[cache_key] = client
            return client  # 返回客户端实例。

    def _client_cache_key(self) -> str | None:  # 计算客户端缓存 key。
        qdrant_url = self.settings.qdrant_url.strip()  # 读取并清理配置。
        if qdrant_url == ":memory:":  # 内存模式不缓存，避免跨测试污染。
            return None
        if qdrant_url.startswith(("http://", "https://")):  # 远程模式按 URL 缓存。
            return qdrant_url
        return str(Path(qdrant_url).resolve())  # 本地路径模式按绝对路径缓存。

    def _collection_exists(self, collection_name: str) -> bool:  # 判断指定 collection 是否存在。
        collection_names = {item.name for item in self.client.get_collections().collections}  # 读取当前所有 collection 名称。
        return collection_name in collection_names  # 返回是否包含目标 collection。

    @staticmethod
    def _build_document_filter(  # 统一构造单文档或多文档 document_id 过滤条件。
        document_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> models.Filter | None:
        if document_id:
            return models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=document_id),
                    )
                ]
            )

        normalized_document_ids = [item.strip() for item in document_ids or [] if item and item.strip()]
        if not normalized_document_ids:
            return None
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=normalized_document_ids),
                )
            ]
        )
