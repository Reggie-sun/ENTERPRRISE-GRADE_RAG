"""重排序客户端，支持启发式和模型级 rerank 策略。"""
import re  # 导入正则工具，用于把文本拆成可比较的 token。
from dataclasses import dataclass
from collections import Counter  # 导入计数器，用于计算 query 和 chunk 的 token 重叠。
from threading import Lock
from time import monotonic

import httpx  # 导入 httpx，用于调用远程 reranker 服务。

from ...core.config import Settings, get_reranker_base_url  # 导入配置对象，读取 rerank 相关参数。
from ...schemas.retrieval import RetrievedChunk  # 导入检索结果模型，作为 rerank 输入输出结构。
from ...services.system_config_service import SystemConfigService

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*|[\u4e00-\u9fff]+")  # 兼容代码样 token 与连续中文片段。


@dataclass(slots=True)
class _RerankerRouteHealthState:
    ready: bool
    detail: str
    checked_at: float
    source: str


class RerankerClient:  # 封装 rerank 逻辑，当前提供可离线运行的启发式重排。
    """重排序客户端：根据 query 对候选检索结果进行二次排序。

    当前支持两种策略：
    - heuristic：基于 token 重叠和向量分数的本地启发式重排，无需外部服务。
    - openai-compatible：调用远程 rerank 模型接口，返回模型级相关性评分。
    内置健康探测和故障降级机制，远端不可用时自动回退到启发式策略。
    """
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

    def rerank(self, *, query: str, candidates: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:
        """主重排入口：按系统配置的策略（heuristic / openai-compatible）对候选 chunk 重排并截断。"""
        if not candidates or top_n <= 0:  # 没有候选结果或 top_n 非法时，直接返回空列表。
            return []

        route = self.system_config_service.get_reranker_routing()
        provider = route.provider.lower().strip()  # 读取并标准化 reranker provider。
        if provider == "heuristic" or route.default_strategy == "heuristic":  # heuristic 继续保留为默认和降级路径；provider 配好但策略锁回 heuristic 时也不打远端。
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

    def rerank_provider_candidate(
        self,
        *,
        query: str,
        candidates: list[RetrievedChunk],
        top_n: int,
    ) -> list[RetrievedChunk]:
        """显式调用模型级 rerank provider，忽略 default_strategy 的 heuristic 固定策略。

        当 provider 未配置或为 heuristic 时直接抛出异常，用于需要强制使用远端模型的场景。
        """
        if not candidates or top_n <= 0:
            return []

        route = self.system_config_service.get_reranker_routing()
        provider = route.provider.lower().strip()
        if provider == "heuristic":
            raise RuntimeError("Model rerank provider is not configured.")
        if provider in {"openai", "openai-compatible", "openai_compatible"}:
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

        raise RuntimeError(f"Unsupported reranker provider: {route.provider}")

    def get_runtime_status(self, *, force_refresh: bool = False) -> dict[str, str | float | bool]:
        """返回当前 reranker 的运行状态字典，包含 provider、健康探测结果、降级信息等。"""
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
                "default_strategy": route.default_strategy,
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
                "default_strategy": route.default_strategy,
                "timeout_seconds": route.timeout_seconds,
                "failure_cooldown_seconds": cooldown_seconds,
                **self._resolve_effective_route(
                    route_provider=route.provider,
                    route_model=route.model,
                    default_strategy=route.default_strategy,
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
                "default_strategy": route.default_strategy,
                "timeout_seconds": route.timeout_seconds,
                "failure_cooldown_seconds": cooldown_seconds,
                **self._resolve_effective_route(
                    route_provider=route.provider,
                    route_model=route.model,
                    default_strategy=route.default_strategy,
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
                    "default_strategy": route.default_strategy,
                    "timeout_seconds": route.timeout_seconds,
                    "failure_cooldown_seconds": cooldown_seconds,
                    **self._resolve_effective_route(
                        route_provider=route.provider,
                        route_model=route.model,
                        default_strategy=route.default_strategy,
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
                detail = self._build_http_error_detail(
                    prefix="Reranker health probe",
                    exc=exc,
                )
                self._write_cached_route_health(cache_key, ready=False, detail=detail, source="probe")
                return {
                    "provider": route.provider,
                    "base_url": base_url,
                    "model": route.model,
                    "default_strategy": route.default_strategy,
                    "timeout_seconds": route.timeout_seconds,
                    "failure_cooldown_seconds": cooldown_seconds,
                    **self._resolve_effective_route(
                        route_provider=route.provider,
                        route_model=route.model,
                        default_strategy=route.default_strategy,
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
                    "default_strategy": route.default_strategy,
                    "timeout_seconds": route.timeout_seconds,
                    "failure_cooldown_seconds": cooldown_seconds,
                    **self._resolve_effective_route(
                        route_provider=route.provider,
                        route_model=route.model,
                        default_strategy=route.default_strategy,
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
            if route.default_strategy == "heuristic":
                detail = f"{detail} Default route is pinned to heuristic by policy."
            self._write_cached_route_health(cache_key, ready=True, detail=detail, source="probe")
            return {
                "provider": route.provider,
                "base_url": base_url,
                "model": route.model,
                "default_strategy": route.default_strategy,
                "timeout_seconds": route.timeout_seconds,
                "failure_cooldown_seconds": cooldown_seconds,
                **self._resolve_effective_route(
                    route_provider=route.provider,
                    route_model=route.model,
                    default_strategy=route.default_strategy,
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
            "default_strategy": route.default_strategy,
            "timeout_seconds": route.timeout_seconds,
            "failure_cooldown_seconds": cooldown_seconds,
            **self._resolve_effective_route(
                route_provider=route.provider,
                route_model=route.model,
                default_strategy=route.default_strategy,
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

    def rerank_heuristic(self, *, query: str, candidates: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:
        """显式暴露启发式重排接口，供降级路径和外部调用统一复用。"""
        if not candidates or top_n <= 0:  # 没有候选结果或 top_n 非法时，直接返回空列表。
            return []
        return self._rerank_with_heuristic(query=query, candidates=candidates, top_n=top_n)  # 直接走启发式实现。

    def _rerank_with_heuristic(  # 基于 token 重叠和初始向量分数做线性融合重排。
        self, *, query: str, candidates: list[RetrievedChunk], top_n: int
    ) -> list[RetrievedChunk]:
        """启发式重排：将 query 与候选 chunk 的词项重叠度和原始向量分数线性融合，得到综合得分。"""
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
    ) -> list[RetrievedChunk]:
        """调用 OpenAI-compatible /rerank 接口完成模型级重排，返回带新分数的候选列表。"""
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
            raise RuntimeError(
                self._build_http_error_detail(
                    prefix="Reranker request to OpenAI-compatible server",
                    exc=exc,
                )
            ) from exc
        except httpx.RequestError as exc:  # 网络错误也交给上层统一降级。
            raise RuntimeError(f"Reranker request to OpenAI-compatible server failed: {exc}") from exc

        return self._parse_openai_rerank_response(response.json(), candidates=candidates, top_n=top_n)

    @staticmethod
    def _token_counter(text: str) -> Counter[str]:  # 把文本拆成 token 计数器。
        tokens: list[str] = []
        for raw_token in TOKEN_PATTERN.findall(text):
            normalized = raw_token.lower()
            if re.search(r"[\u4e00-\u9fff]", normalized):
                if len(normalized) == 1:
                    tokens.append(normalized)
                    continue
                # 中文没有天然空格分词，fallback rerank 用 2-gram 让“真空阀异常”这类 query 也能产生稳定重叠信号。
                tokens.extend(normalized[index : index + 2] for index in range(len(normalized) - 1))
                continue
            tokens.append(normalized)
        return Counter(tokens)  # 统一转小写并对中文做轻量 2-gram，减少中文 fallback 时退化成原始顺序。

    @staticmethod
    def _quality_multiplier(chunk: RetrievedChunk) -> float:  # 仅对 OCR chunk 做轻量质量降权，避免低置信度文本压过高质量证据。
        if not chunk.ocr_used or chunk.quality_score is None:
            return 1.0
        clamped_quality = min(max(float(chunk.quality_score), 0.0), 1.0)
        return 0.85 + 0.15 * clamped_quality

    def _build_openai_rerank_url(self) -> str:
        """统一构造 OpenAI-compatible rerank URL，自动补齐 /rerank 后缀。"""
        base_url = get_reranker_base_url(self.settings)
        return base_url if base_url.endswith("/rerank") else f"{base_url}/rerank"

    @staticmethod
    def _build_openai_health_url(base_url: str) -> str:
        """从 rerank base_url 推导出 /health 探测地址，去掉 /rerank 和 /v1 后缀。"""
        normalized = base_url.rstrip("/")
        if normalized.endswith("/v1/rerank"):
            normalized = normalized[: -len("/v1/rerank")]
        elif normalized.endswith("/rerank"):
            normalized = normalized[: -len("/rerank")]
        elif normalized.endswith("/v1"):
            normalized = normalized[: -len("/v1")]
        return f"{normalized.rstrip('/')}/health"

    def _build_openai_headers(self) -> dict[str, str]:
        """构造 OpenAI-compatible rerank 请求头，包含 Content-Type 和可选的 Bearer 鉴权。"""
        headers = {"Content-Type": "application/json"}
        api_key = (self.settings.reranker_api_key or "").strip()
        if not api_key:  # 兼容本地无需鉴权的服务。
            return headers
        if not api_key.isascii():  # httpx 请求头默认按 ASCII 编码，尽早暴露配置问题。
            raise RuntimeError("Reranker API key contains non-ASCII characters. Check RAG_RERANKER_API_KEY.")
        headers["Authorization"] = f"Bearer {api_key}"
        return headers

    @staticmethod
    def _build_http_error_detail(*, prefix: str, exc: httpx.HTTPStatusError) -> str:
        """将 HTTP 错误转换为可读的错误详情字符串，对 429 限流做特殊处理。"""
        response = exc.response
        status_code = response.status_code
        reason = response.reason_phrase or "HTTP error"
        retry_after = response.headers.get("Retry-After")
        if status_code == 429:
            detail = f"{prefix} was rate limited (HTTP 429 {reason})"
            if retry_after:
                detail = f"{detail}. Retry-After: {retry_after}s."
            return detail
        return f"{prefix} failed with HTTP error: {status_code} {reason}"

    @staticmethod
    def _resolve_effective_route(
        *,
        route_provider: str,
        route_model: str,
        default_strategy: str,
        ready: bool,
        fallback_enabled: bool,
    ) -> dict[str, str]:
        """根据 provider 配置、健康状态和降级开关，解析当前实际生效的路由策略。"""
        if route_provider.lower().strip() == "heuristic" or default_strategy == "heuristic":
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
    ) -> list[RetrievedChunk]:
        """解析 OpenAI-compatible rerank 返回结构，兼容 results 和 data 两种字段名。

        结果不足时用原始候选顺序补满，避免上下文证据意外缩水。
        """
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
        ordered_results = [chunk.model_copy(update={"score": score}) for score, chunk in reranked]
        limit = min(top_n, len(candidates))
        if len(ordered_results) >= limit:
            return ordered_results[:limit]

        # 某些 OpenAI-compatible 服务在异常或兼容模式下可能只返回部分有效结果；
        # 这里用原始候选顺序补满，避免上下文证据包意外缩水。
        for index, candidate in enumerate(candidates):
            if index in seen_indexes:
                continue
            ordered_results.append(candidate)
            if len(ordered_results) >= limit:
                break
        return ordered_results

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
        """更新 rerank 路由的健康缓存，记录成功/失败状态和时间戳。"""
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
