from uuid import NAMESPACE_URL, uuid5  # 导入 uuid5，用来为 Qdrant point 生成稳定 UUID。

from qdrant_client import QdrantClient  # 导入 Qdrant 客户端。
from qdrant_client.http import models  # 导入 Qdrant HTTP 模型定义。

from ...core.config import Settings  # 导入配置对象。
from ..chunkers.text_chunker import TextChunk  # 导入 TextChunk 结构，用来描述待写入的文本片段。


class QdrantVectorStore:  # 封装 Qdrant 读写逻辑。
    def __init__(self, settings: Settings) -> None:  # 初始化 Qdrant 存储对象。
        self.settings = settings  # 保存配置对象。
        self._client: QdrantClient | None = None  # 先把客户端置空，等真正使用时再懒加载。

    @property  # 把 client 做成属性，调用方可以像访问字段一样使用。
    def client(self) -> QdrantClient:  # 惰性获取 Qdrant 客户端实例。
        if self._client is None:  # 如果客户端还没有创建。
            self._client = self._build_client()  # 就按当前配置创建一个新的客户端。
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
        result = self.client.count(  # 调用 Qdrant 计数接口。
            collection_name=self.settings.qdrant_collection,  # 指定目标 collection。
            exact=True,  # 要求精确计数。
        )
        return int(result.count)  # 把返回值转换成 Python int。

    def _ensure_collection(self, vector_size: int) -> None:  # 确保目标 collection 已创建。
        collection_names = {item.name for item in self.client.get_collections().collections}  # 读取当前所有 collection 名称。
        if self.settings.qdrant_collection in collection_names:  # 如果目标 collection 已存在。
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
            return QdrantClient(url=qdrant_url)  # 创建远程服务客户端。
        return QdrantClient(path=qdrant_url)  # 否则按本地磁盘路径模式创建客户端。
