import re  # 导入正则工具，用于把文本拆成可比较的 token。
from collections import Counter  # 导入计数器，用于计算 query 和 chunk 的 token 重叠。

from ...core.config import Settings  # 导入配置对象，读取 rerank 相关参数。
from ...schemas.retrieval import RetrievedChunk  # 导入检索结果模型，作为 rerank 输入输出结构。

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+", flags=re.ASCII)  # 定义简单 token 规则，便于做轻量词项匹配。


class RerankerClient:  # 封装 rerank 逻辑，当前提供可离线运行的启发式重排。
    def __init__(self, settings: Settings) -> None:  # 初始化 reranker 客户端。
        self.settings = settings  # 保存配置对象。

    def rerank(self, *, query: str, candidates: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:  # 按 query 对候选 chunk 重排并截断。
        if not candidates or top_n <= 0:  # 没有候选结果或 top_n 非法时，直接返回空列表。
            return []

        provider = self.settings.reranker_provider.lower().strip()  # 读取并标准化 reranker provider。
        if provider != "heuristic":  # V1 先支持 heuristic，其他 provider 后续再接。
            raise RuntimeError(f"Unsupported reranker provider: {self.settings.reranker_provider}")  # 抛出明确错误，方便定位配置问题。

        return self._rerank_with_heuristic(query=query, candidates=candidates, top_n=top_n)  # 调用启发式重排实现。

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

    @staticmethod
    def _token_counter(text: str) -> Counter[str]:  # 把文本拆成 token 计数器。
        return Counter(token.lower() for token in TOKEN_PATTERN.findall(text))  # 统一转小写，减少大小写影响。
