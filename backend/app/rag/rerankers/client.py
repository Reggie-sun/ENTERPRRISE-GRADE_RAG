import re  # 导入正则工具，用于把文本拆成可比较的 token。
from collections import Counter  # 导入计数器，用于计算 query 和 chunk 的 token 重叠。

import httpx  # 导入 httpx，用于调用远程 reranker 服务。

from ...core.config import Settings, get_reranker_base_url  # 导入配置对象，读取 rerank 相关参数。
from ...schemas.retrieval import RetrievedChunk  # 导入检索结果模型，作为 rerank 输入输出结构。

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+", flags=re.ASCII)  # 定义简单 token 规则，便于做轻量词项匹配。


class RerankerClient:  # 封装 rerank 逻辑，当前提供可离线运行的启发式重排。
    def __init__(self, settings: Settings) -> None:  # 初始化 reranker 客户端。
        self.settings = settings  # 保存配置对象。

    def rerank(self, *, query: str, candidates: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:  # 按 query 对候选 chunk 重排并截断。
        if not candidates or top_n <= 0:  # 没有候选结果或 top_n 非法时，直接返回空列表。
            return []

        provider = self.settings.reranker_provider.lower().strip()  # 读取并标准化 reranker provider。
        if provider == "heuristic":  # heuristic 继续保留为默认和降级路径。
            return self._rerank_with_heuristic(query=query, candidates=candidates, top_n=top_n)  # 调用启发式重排实现。
        if provider in {"openai", "openai-compatible", "openai_compatible"}:  # OpenAI-compatible rerank 接口统一复用一套实现。
            return self._rerank_with_openai(query=query, candidates=candidates, top_n=top_n)

        raise RuntimeError(f"Unsupported reranker provider: {self.settings.reranker_provider}")  # 抛出明确错误，方便定位配置问题。

    def rerank_heuristic(self, *, query: str, candidates: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:  # 显式暴露启发式重排，供降级路径统一复用。
        if not candidates or top_n <= 0:  # 没有候选结果或 top_n 非法时，直接返回空列表。
            return []
        return self._rerank_with_heuristic(query=query, candidates=candidates, top_n=top_n)  # 直接走启发式实现。

    def _rerank_with_heuristic(  # 基于 token 重叠和初始向量分数做线性融合重排。
        self, *, query: str, candidates: list[RetrievedChunk], top_n: int
    ) -> list[RetrievedChunk]:
        query_tokens = self._token_counter(query)  # 把 query 转成 token 计数器。
        if not query_tokens:  # query 没有有效 token 时，保留原始顺序并按 top_n 截断。
            return candidates[: min(top_n, len(candidates))]

        query_len = sum(query_tokens.values()) or 1  # 统计 query token 总数，避免除 0。
        scored: list[tuple[float, RetrievedChunk]] = []  # 初始化重排分数列表。

        for chunk in candidates:  # 遍历候选片段，计算每条的融合分数。
            chunk_tokens = self._token_counter(chunk.text)  # 把 chunk 文本转成 token 计数器。
            overlap = sum(min(query_tokens[token], chunk_tokens[token]) for token in query_tokens)  # 统计 query 与 chunk 的重叠 token 数。
            lexical_score = overlap / query_len  # 计算词项重叠得分，范围大致在 0~1。
            blended_score = 0.7 * float(chunk.score) + 0.3 * lexical_score  # 与向量检索分数做线性融合，保持语义召回优势。
            scored.append((blended_score, chunk))  # 记录融合分数和原始 chunk。

        scored.sort(key=lambda item: item[0], reverse=True)  # 按融合分数从高到低排序。
        limit = min(top_n, len(scored))  # 计算实际返回条数。
        return [chunk.model_copy(update={"score": score}) for score, chunk in scored[:limit]]  # 返回更新后分数的重排结果。

    def _rerank_with_openai(
        self,
        *,
        query: str,
        candidates: list[RetrievedChunk],
        top_n: int,
    ) -> list[RetrievedChunk]:  # 调用 OpenAI-compatible rerank 接口完成模型级重排。
        url = self._build_openai_rerank_url()  # 解析当前生效的 rerank 接口地址。
        headers = self._build_openai_headers()  # 统一构造请求头。
        payload = {
            "model": self.settings.reranker_model,
            "query": query,
            "documents": [candidate.text for candidate in candidates],
            "top_n": min(top_n, len(candidates)),
        }

        try:  # 请求远程 reranker 服务。
            response = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.settings.reranker_timeout_seconds,
                trust_env=False,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:  # 超时属于可降级故障。
            raise RuntimeError(f"Reranker request to OpenAI-compatible server timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:  # 服务端/客户端错误都走统一降级语义。
            raise RuntimeError(f"Reranker request to OpenAI-compatible server failed with HTTP error: {exc}") from exc
        except httpx.RequestError as exc:  # 网络错误也交给上层统一降级。
            raise RuntimeError(f"Reranker request to OpenAI-compatible server failed: {exc}") from exc

        return self._parse_openai_rerank_response(response.json(), candidates=candidates, top_n=top_n)

    @staticmethod
    def _token_counter(text: str) -> Counter[str]:  # 把文本拆成 token 计数器。
        return Counter(token.lower() for token in TOKEN_PATTERN.findall(text))  # 统一转小写，减少大小写影响。

    def _build_openai_rerank_url(self) -> str:  # 统一构造 OpenAI-compatible rerank URL。
        base_url = get_reranker_base_url(self.settings)
        return base_url if base_url.endswith("/rerank") else f"{base_url}/rerank"

    def _build_openai_headers(self) -> dict[str, str]:  # 统一构造 OpenAI-compatible rerank 请求头。
        headers = {"Content-Type": "application/json"}
        api_key = (self.settings.reranker_api_key or "").strip()
        if not api_key:  # 兼容本地无需鉴权的服务。
            return headers
        if not api_key.isascii():  # httpx 请求头默认按 ASCII 编码，尽早暴露配置问题。
            raise RuntimeError("Reranker API key contains non-ASCII characters. Check RAG_RERANKER_API_KEY.")
        headers["Authorization"] = f"Bearer {api_key}"
        return headers

    @staticmethod
    def _parse_openai_rerank_response(
        payload: dict[str, object],
        *,
        candidates: list[RetrievedChunk],
        top_n: int,
    ) -> list[RetrievedChunk]:  # 兼容常见 OpenAI-compatible rerank 返回结构。
        raw_items = payload.get("results")
        if not isinstance(raw_items, list):
            raw_items = payload.get("data")
        if not isinstance(raw_items, list):
            raise RuntimeError("Unexpected OpenAI-compatible rerank response format.")

        reranked: list[tuple[float, RetrievedChunk]] = []
        seen_indexes: set[int] = set()
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            score = item.get("relevance_score", item.get("score"))
            if not isinstance(index, int) or index < 0 or index >= len(candidates):
                continue
            if index in seen_indexes:
                continue
            try:
                numeric_score = float(score)
            except (TypeError, ValueError):
                continue
            seen_indexes.add(index)
            reranked.append((numeric_score, candidates[index]))

        if not reranked:
            raise RuntimeError("OpenAI-compatible rerank response did not contain any valid results.")

        reranked.sort(key=lambda item: item[0], reverse=True)
        limit = min(top_n, len(reranked))
        return [chunk.model_copy(update={"score": score}) for score, chunk in reranked[:limit]]
