import re  # 导入正则工具，用于把文本拆成可比较的 token。
from dataclasses import dataclass
from collections import Counter  # 导入计数器，用于计算 query 和 chunk 的 token 重叠。
from threading import Lock
from time import monotonic

import httpx  # 导入 httpx，用于调用远程 reranker 服务。

from ...core.config import Settings, get_reranker_base_url  # 导入配置对象，读取 rerank 相关参数。
from ...schemas.retrieval import RetrievedChunk  # 导入检索结果模型，作为 rerank 输入输出结构。
from ...services.system_config_service import SystemConfigService

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+", flags=re.ASCII)  # 定义简单 token 规则，便于做轻量词项匹配。


@dataclass(slots=True)
class _RerankerRouteHealthState:
    ready: bool
    detail: str
    checked_at: float
    source: str


class RerankerClient:  # 封装 rerank 逻辑，当前提供可离线运行的启发式重排。
    _ROUTE_HEALTH_CACHE: dict[tuple[str, str, str], _RerankerRouteHealthState] = {}
    _ROUTE_HEALTH_LOCK = Lock()

    def __init__(
        self,
        settings: Settings,
        *,
        system_config_service: SystemConfigService | None = None,
    ) -> None:  # 初始化 reranker 客户端。
        self.settings = settings  # 保存配置对象。
        self.system_config_service = system_config_service or SystemConfigService(settings)

    def rerank(self, *, query: str, candidates: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:  # 按 query 对候选 chunk 重排并截断。
        if not candidates or top_n <= 0:  # 没有候选结果或 top_n 非法时，直接返回空列表。
            return []

        route = self.system_config_service.get_reranker_routing()
        provider = route.provider.lower().strip()  # 读取并标准化 reranker provider。
        if provider == "heuristic":  # heuristic 继续保留为默认和降级路径。
            return self._rerank_with_heuristic(query=query, candidates=candidates, top_n=top_n)  # 调用启发式重排实现。
        if provider in {"openai", "openai-compatible", "openai_compatible"}:  # OpenAI-compatible rerank 接口统一复用一套实现。
            status = self.get_runtime_status()
            if not status["ready"]:
                raise RuntimeError(str(status["detail"]))
            try:
                reranked = self._rerank_with_openai(
                    query=query,
                    candidates=candidates,
                    top_n=top_n,
                    model_name=route.model,
                    timeout_seconds=route.timeout_seconds,
                )
            except RuntimeError as exc:
                self._update_cached_route_health(route=route, ready=False, detail=str(exc), source="request")
                raise
            self._update_cached_route_health(
                route=route,
                ready=True,
                detail="OpenAI-compatible reranker requests are succeeding.",
                source="request",
            )
            return reranked

        raise RuntimeError(f"Unsupported reranker provider: {route.provider}")  # 抛出明确错误，方便定位配置问题。

    def get_runtime_status(self, *, force_refresh: bool = False) -> dict[str, str | float | bool]:
        route = self.system_config_service.get_reranker_routing()
        degrade_controls = self.system_config_service.get_degrade_controls()
        fallback_enabled = degrade_controls.rerank_fallback_enabled
        provider = route.provider.lower().strip()
        cooldown_seconds = float(route.failure_cooldown_seconds)
        if provider == "heuristic":
            return {
                "provider": route.provider,
                "base_url": "",
                "model": route.model,
                "timeout_seconds": route.timeout_seconds,
                "failure_cooldown_seconds": cooldown_seconds,
                "effective_provider": "heuristic",
                "effective_model": "heuristic",
                "effective_strategy": "heuristic",
                "fallback_enabled": fallback_enabled,
                "lock_active": False,
                "lock_source": None,
                "cooldown_remaining_seconds": 0.0,
                "ready": True,
                "detail": "Heuristic reranker is active.",
            }

        try:
            base_url = get_reranker_base_url(self.settings)
        except RuntimeError as exc:
            return {
                "provider": route.provider,
                "base_url": "",
                "model": route.model,
                "timeout_seconds": route.timeout_seconds,
                "failure_cooldown_seconds": cooldown_seconds,
                **self._resolve_effective_route(
                    route_provider=route.provider,
                    route_model=route.model,
                    ready=False,
                    fallback_enabled=fallback_enabled,
                ),
                "fallback_enabled": fallback_enabled,
                "lock_active": False,
                "lock_source": None,
                "cooldown_remaining_seconds": 0.0,
                "ready": False,
                "detail": str(exc),
            }

        cache_key = self._cache_key(route_provider=route.provider, base_url=base_url, model_name=route.model)
        cached = self._read_cached_route_health(cache_key, ttl_seconds=cooldown_seconds)
        if cached is not None and not force_refresh:
            remaining_seconds = max(0.0, cooldown_seconds - (monotonic() - cached.checked_at))
            return {
                "provider": route.provider,
                "base_url": base_url,
                "model": route.model,
                "timeout_seconds": route.timeout_seconds,
                "failure_cooldown_seconds": cooldown_seconds,
                **self._resolve_effective_route(
                    route_provider=route.provider,
                    route_model=route.model,
                    ready=cached.ready,
                    fallback_enabled=fallback_enabled,
                ),
                "fallback_enabled": fallback_enabled,
                "lock_active": (not cached.ready) and remaining_seconds > 0,
                "lock_source": cached.source if (not cached.ready) and remaining_seconds > 0 else None,
                "cooldown_remaining_seconds": remaining_seconds if (not cached.ready) and remaining_seconds > 0 else 0.0,
                "ready": cached.ready,
                "detail": cached.detail,
            }

        if provider in {"openai", "openai-compatible", "openai_compatible"}:
            health_url = self._build_openai_health_url(base_url)
            try:
                response = httpx.get(
                    health_url,
                    headers=self._build_openai_headers(),
                    timeout=min(2.0, max(route.timeout_seconds, 0.5)),
                    trust_env=False,
                )
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                detail = f"Reranker health probe timed out: {exc}"
                self._write_cached_route_health(cache_key, ready=False, detail=detail, source="probe")
                return {
                    "provider": route.provider,
                    "base_url": base_url,
                    "model": route.model,
                    "timeout_seconds": route.timeout_seconds,
                    "failure_cooldown_seconds": cooldown_seconds,
                    **self._resolve_effective_route(
                        route_provider=route.provider,
                        route_model=route.model,
                        ready=False,
                        fallback_enabled=fallback_enabled,
                    ),
                    "fallback_enabled": fallback_enabled,
                    "lock_active": True,
                    "lock_source": "probe",
                    "cooldown_remaining_seconds": cooldown_seconds,
                    "ready": False,
                    "detail": detail,
                }
            except httpx.HTTPStatusError as exc:
                detail = f"Reranker health probe failed with HTTP error: {exc}"
                self._write_cached_route_health(cache_key, ready=False, detail=detail, source="probe")
                return {
                    "provider": route.provider,
                    "base_url": base_url,
                    "model": route.model,
                    "timeout_seconds": route.timeout_seconds,
                    "failure_cooldown_seconds": cooldown_seconds,
                    **self._resolve_effective_route(
                        route_provider=route.provider,
                        route_model=route.model,
                        ready=False,
                        fallback_enabled=fallback_enabled,
                    ),
                    "fallback_enabled": fallback_enabled,
                    "lock_active": True,
                    "lock_source": "probe",
                    "cooldown_remaining_seconds": cooldown_seconds,
                    "ready": False,
                    "detail": detail,
                }
            except httpx.RequestError as exc:
                detail = f"Reranker health probe failed: {exc}"
                self._write_cached_route_health(cache_key, ready=False, detail=detail, source="probe")
                return {
                    "provider": route.provider,
                    "base_url": base_url,
                    "model": route.model,
                    "timeout_seconds": route.timeout_seconds,
                    "failure_cooldown_seconds": cooldown_seconds,
                    **self._resolve_effective_route(
                        route_provider=route.provider,
                        route_model=route.model,
                        ready=False,
                        fallback_enabled=fallback_enabled,
                    ),
                    "fallback_enabled": fallback_enabled,
                    "lock_active": True,
                    "lock_source": "probe",
                    "cooldown_remaining_seconds": cooldown_seconds,
                    "ready": False,
                    "detail": detail,
                }

            detail = "OpenAI-compatible reranker health probe succeeded."
            self._write_cached_route_health(cache_key, ready=True, detail=detail, source="probe")
            return {
                "provider": route.provider,
                "base_url": base_url,
                "model": route.model,
                "timeout_seconds": route.timeout_seconds,
                "failure_cooldown_seconds": cooldown_seconds,
                **self._resolve_effective_route(
                    route_provider=route.provider,
                    route_model=route.model,
                    ready=True,
                    fallback_enabled=fallback_enabled,
                ),
                "fallback_enabled": fallback_enabled,
                "lock_active": False,
                "lock_source": None,
                "cooldown_remaining_seconds": 0.0,
                "ready": True,
                "detail": detail,
            }

        detail = f"Unsupported reranker provider: {route.provider}"
        return {
            "provider": route.provider,
            "base_url": base_url,
            "model": route.model,
            "timeout_seconds": route.timeout_seconds,
            "failure_cooldown_seconds": cooldown_seconds,
            **self._resolve_effective_route(
                route_provider=route.provider,
                route_model=route.model,
                ready=False,
                fallback_enabled=fallback_enabled,
            ),
            "fallback_enabled": fallback_enabled,
            "lock_active": False,
            "lock_source": None,
            "cooldown_remaining_seconds": 0.0,
            "ready": False,
            "detail": detail,
        }

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
            blended_score *= self._quality_multiplier(chunk)  # OCR 质量较低时做轻微降权，但不改变主排序语义。
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
        model_name: str,
        timeout_seconds: float,
    ) -> list[RetrievedChunk]:  # 调用 OpenAI-compatible rerank 接口完成模型级重排。
        url = self._build_openai_rerank_url()  # 解析当前生效的 rerank 接口地址。
        headers = self._build_openai_headers()  # 统一构造请求头。
        payload = {
            "model": model_name,
            "query": query,
            "documents": [candidate.text for candidate in candidates],
            "top_n": min(top_n, len(candidates)),
        }

        try:  # 请求远程 reranker 服务。
            response = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=timeout_seconds,
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

    @staticmethod
    def _quality_multiplier(chunk: RetrievedChunk) -> float:  # 仅对 OCR chunk 做轻量质量降权，避免低置信度文本压过高质量证据。
        if not chunk.ocr_used or chunk.quality_score is None:
            return 1.0
        clamped_quality = min(max(float(chunk.quality_score), 0.0), 1.0)
        return 0.85 + 0.15 * clamped_quality

    def _build_openai_rerank_url(self) -> str:  # 统一构造 OpenAI-compatible rerank URL。
        base_url = get_reranker_base_url(self.settings)
        return base_url if base_url.endswith("/rerank") else f"{base_url}/rerank"

    @staticmethod
    def _build_openai_health_url(base_url: str) -> str:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/v1/rerank"):
            normalized = normalized[: -len("/v1/rerank")]
        elif normalized.endswith("/rerank"):
            normalized = normalized[: -len("/rerank")]
        elif normalized.endswith("/v1"):
            normalized = normalized[: -len("/v1")]
        return f"{normalized.rstrip('/')}/health"

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
    def _resolve_effective_route(
        *,
        route_provider: str,
        route_model: str,
        ready: bool,
        fallback_enabled: bool,
    ) -> dict[str, str]:
        if route_provider.lower().strip() == "heuristic":
            return {
                "effective_provider": "heuristic",
                "effective_model": "heuristic",
                "effective_strategy": "heuristic",
            }
        if ready:
            return {
                "effective_provider": route_provider,
                "effective_model": route_model,
                "effective_strategy": "provider",
            }
        if fallback_enabled:
            return {
                "effective_provider": "heuristic",
                "effective_model": "heuristic",
                "effective_strategy": "heuristic",
            }
        return {
            "effective_provider": route_provider,
            "effective_model": route_model,
            "effective_strategy": "failed",
        }

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

    @classmethod
    def _cache_key(cls, *, route_provider: str, base_url: str, model_name: str) -> tuple[str, str, str]:
        return (route_provider.lower().strip(), base_url.rstrip("/"), model_name.strip())

    @classmethod
    def _read_cached_route_health(
        cls,
        cache_key: tuple[str, str, str],
        *,
        ttl_seconds: float,
    ) -> _RerankerRouteHealthState | None:
        now = monotonic()
        with cls._ROUTE_HEALTH_LOCK:
            cached = cls._ROUTE_HEALTH_CACHE.get(cache_key)
            if cached is None:
                return None
            if now - cached.checked_at > ttl_seconds:
                cls._ROUTE_HEALTH_CACHE.pop(cache_key, None)
                return None
            return cached

    @classmethod
    def _write_cached_route_health(
        cls,
        cache_key: tuple[str, str, str],
        *,
        ready: bool,
        detail: str,
        source: str,
    ) -> None:
        with cls._ROUTE_HEALTH_LOCK:
            cls._ROUTE_HEALTH_CACHE[cache_key] = _RerankerRouteHealthState(
                ready=ready,
                detail=detail,
                checked_at=monotonic(),
                source=source,
            )

    def _update_cached_route_health(self, *, route, ready: bool, detail: str, source: str) -> None:
        try:
            base_url = get_reranker_base_url(self.settings)
        except RuntimeError:
            return
        self._write_cached_route_health(
            self._cache_key(route_provider=route.provider, base_url=base_url, model_name=route.model),
            ready=ready,
            detail=detail,
            source=source,
        )
