"""向量嵌入客户端，支持 mock 和真实 embedding provider。"""
import hashlib  # 导入哈希库，用于 mock embedding 的伪随机向量生成。
import math  # 导入数学库，用于向量归一化。

import httpx  # 导入 httpx，用于调用远程 embedding 服务。

from ...core.config import Settings  # 导入配置对象。


class EmbeddingClient:  # 封装 embedding 请求逻辑，支持多种 provider。
    def __init__(self, settings: Settings) -> None:  # 初始化 embedding 客户端。
        self.settings = settings  # 保存配置对象，后续按配置决定请求方式。

    def embed_texts(self, texts: list[str]) -> list[list[float]]:  # 为一批文本生成向量。
        if not texts:  # 如果输入为空。
            return []  # 直接返回空向量列表。

        provider = self.settings.embedding_provider.lower()  # 读取并标准化 provider 名称。
        batches = self._batch(texts, batch_size=self.settings.embedding_batch_size)  # 按配置分批，避免单次请求过大。
        embeddings: list[list[float]] = []  # 初始化最终向量结果列表。

        for batch in batches:  # 依次处理每一批文本。
            if provider == "mock":  # 如果当前配置是 mock 模式。
                embeddings.extend(self._embed_with_mock(batch))  # 用本地伪向量填充结果。
            elif provider == "ollama":  # 如果当前配置是 Ollama 风格接口。
                embeddings.extend(self._embed_with_ollama(batch))  # 调用 Ollama embedding 接口。
            elif provider == "openai":  # 如果当前配置是 OpenAI 兼容接口。
                embeddings.extend(self._embed_with_openai(batch))  # 调用 OpenAI 兼容 embedding 接口。
            else:  # 如果 provider 不在支持列表里。
                raise RuntimeError(f"Unsupported embedding provider: {self.settings.embedding_provider}")  # 抛出错误提醒配置不合法。

        return embeddings  # 返回所有批次合并后的向量结果。

    @staticmethod  # 这个函数不依赖实例状态，因此声明成静态方法。
    def _batch(items: list[str], batch_size: int) -> list[list[str]]:  # 把文本列表按批大小切成多批。
        return [items[index : index + batch_size] for index in range(0, len(items), max(1, batch_size))]  # 返回切分后的二维列表。

    def _embed_with_ollama(self, texts: list[str]) -> list[list[float]]:  # 调用 Ollama 风格的 embedding 接口。
        base_url = (self.settings.embedding_base_url or self.settings.ollama_base_url).rstrip("/")  # 优先使用独立 embedding 地址，否则复用 LLM 地址。
        url = f"{base_url}/api/embed"  # 拼出 Ollama embedding 接口地址。
        payload = {"model": self.settings.embedding_model, "input": texts}  # 组织请求体。

        try:  # 尝试发送 HTTP 请求到远程服务。
            response = httpx.post(  # 发起 POST 请求。
                url,  # 目标地址。
                json=payload,  # 请求体。
                timeout=self.settings.embedding_timeout_seconds,  # 超时时间。
                trust_env=False,  # 忽略系统代理配置，避免本地代理环境影响服务互调。
            )
            response.raise_for_status()  # 如果 HTTP 状态码不是 2xx，就抛异常。
        except Exception as exc:  # 捕获网络、代理配置等异常。
            raise RuntimeError(f"Embedding request to Ollama failed: {exc}") from exc  # 转成更统一的运行时错误。

        data = response.json()  # 解析返回的 JSON 数据。
        if isinstance(data.get("embeddings"), list):  # 如果返回的是批量 embeddings 字段。
            return [self._to_float_list(item) for item in data["embeddings"]]  # 转换成 float 列表后返回。
        if isinstance(data.get("embedding"), list):  # 如果返回的是单条 embedding 字段。
            return [self._to_float_list(data["embedding"])]  # 也统一包装成二维列表返回。

        raise RuntimeError("Unexpected Ollama embedding response format.")  # 如果返回结构不符合预期，就抛错。

    def _embed_with_openai(self, texts: list[str]) -> list[list[float]]:  # 调用 OpenAI 兼容格式的 embedding 接口。
        base_url = (self.settings.embedding_base_url or self.settings.ollama_base_url).rstrip("/")  # 优先使用独立 embedding 地址。
        url = base_url if base_url.endswith("/embeddings") else f"{base_url}/embeddings"  # 自动兼容是否已带 /embeddings 后缀。
        headers = {"Content-Type": "application/json"}  # 设置基础请求头。

        if self.settings.embedding_api_key:  # 如果配置了 API Key。
            headers["Authorization"] = f"Bearer {self.settings.embedding_api_key}"  # 就加上 Bearer 鉴权头。

        payload = {"model": self.settings.embedding_model, "input": texts}  # 组织 OpenAI 兼容格式的请求体。

        try:  # 尝试调用远程 embedding 服务。
            response = httpx.post(  # 发起 POST 请求。
                url,  # 目标地址。
                json=payload,  # 请求体内容。
                headers=headers,  # 请求头。
                timeout=self.settings.embedding_timeout_seconds,  # 超时时间。
                trust_env=False,  # 忽略系统代理配置，避免本地代理环境影响服务互调。
            )
            response.raise_for_status()  # 检查是否是成功状态码。
        except Exception as exc:  # 捕获网络、代理配置等异常。
            raise RuntimeError(f"Embedding request to OpenAI-compatible server failed: {exc}") from exc  # 转换成统一错误。

        data = response.json()  # 解析返回 JSON。
        vectors = data.get("data")  # 读取 OpenAI 格式中的 data 字段。
        if not isinstance(vectors, list):  # 如果 data 不是列表。
            raise RuntimeError("Unexpected OpenAI-compatible embedding response format.")  # 抛出格式错误。

        return [self._to_float_list(item["embedding"]) for item in vectors]  # 提取每条结果里的 embedding 数组并返回。

    def _embed_with_mock(self, texts: list[str]) -> list[list[float]]:  # 使用本地 mock 逻辑生成向量。
        return [self._mock_embedding(text) for text in texts]  # 为每条文本生成一条确定性的伪向量。

    def _mock_embedding(self, text: str) -> list[float]:  # 生成一条确定性的 mock 向量，便于本地开发和测试。
        seed = text.encode("utf-8")  # 把文本编码成字节，作为哈希输入种子。
        digest = hashlib.sha256(seed).digest()  # 对输入做一次 sha256 哈希。
        vector: list[float] = []  # 初始化向量数组。

        while len(vector) < self.settings.embedding_mock_vector_size:  # 持续填充，直到达到目标维度。
            for byte in digest:  # 遍历当前哈希结果里的每个字节。
                vector.append(byte / 127.5 - 1.0)  # 把 0~255 映射到大致 -1~1 区间。
                if len(vector) >= self.settings.embedding_mock_vector_size:  # 如果维度已经够了。
                    break  # 退出当前循环。
            digest = hashlib.sha256(digest + seed).digest()  # 继续对上轮结果和原始种子做哈希，生成下一段伪随机字节。

        norm = math.sqrt(sum(value * value for value in vector)) or 1.0  # 计算向量的 L2 范数，避免除以 0。
        return [value / norm for value in vector]  # 把向量归一化后返回。

    @staticmethod  # 这是一个纯工具函数，不依赖实例状态。
    def _to_float_list(values: list[float]) -> list[float]:  # 把返回值统一转换成 float 列表。
        return [float(value) for value in values]  # 确保所有元素都是 Python float。
