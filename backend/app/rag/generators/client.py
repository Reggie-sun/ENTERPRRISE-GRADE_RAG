"""LLM 生成客户端，负责基于检索上下文生成最终回答。"""
import json
from dataclasses import dataclass
from time import sleep
from typing import Iterator

import httpx

from ...core.config import Settings, get_llm_base_url, get_llm_model
from ...schemas.system_config import PromptBudgetConfig
from ...services.system_config_service import SystemConfigService
from ...services.token_budget_service import TokenBudgetService


class LLMGenerationError(RuntimeError):
    """生成阶段统一异常基类，便于上层按类型区分处理策略。"""
    pass


class LLMGenerationRetryableError(LLMGenerationError):
    """可降级故障：网络抖动、超时、远端 5xx。"""
    pass


class LLMGenerationFatalError(LLMGenerationError):
    """不可降级错误：配置错误、请求参数错误、返回格式异常。"""
    pass


@dataclass(frozen=True)
class PreparedPrompt:
    """经过 token 预算裁剪后的最终 prompt 结构，携带上下文与记忆的完整统计信息。"""
    prompt: str
    prepared_contexts: list[str]
    prepared_memory: str | None
    original_context_count: int
    deduplicated_context_count: int
    pretrimmed_context_count: int
    prepared_context_count: int
    truncated_context_count: int
    context_token_estimate: int
    memory_token_estimate: int
    prompt_token_estimate: int


class LLMGenerationClient:  # 封装问答生成逻辑，支持 mock / ollama / openai / deepseek 四种 provider。
    """LLM 生成客户端，负责将检索到的上下文和用户问题拼装成 prompt 并调用大模型生成回答。

    支持 mock（本地联调）、ollama（本地/远程 Ollama）、openai/deepseek（OpenAI 兼容接口）四种 provider，
    同时提供流式和非流式两种输出模式。内置 token 预算管理和重试机制。
    """
    def __init__(
        self,
        settings: Settings,
        *,
        system_config_service: SystemConfigService | None = None,
        token_budget_service: TokenBudgetService | None = None,
    ) -> None:
        self.settings = settings
        self.system_config_service = system_config_service or SystemConfigService(settings)
        self.token_budget_service = token_budget_service or TokenBudgetService(settings)

    def generate(
        self,
        *,
        question: str,
        contexts: list[str],
        memory_text: str | None = None,
        timeout_seconds: float | None = None,
        model_name: str | None = None,
        prepared_prompt: PreparedPrompt | None = None,
    ) -> str:
        """非流式生成入口：拼接 prompt 并调用 LLM 返回完整回答字符串。"""
        def operation() -> str:
            kwargs = dict(
                question=question,
                contexts=contexts,
                memory_text=memory_text,
                timeout_seconds=timeout_seconds,
                model_name=model_name,
            )
            if prepared_prompt is not None:
                kwargs["prepared_prompt"] = prepared_prompt
            return self._generate_once(**kwargs)

        return self._run_with_retry(operation)

    def _generate_once(
        self,
        *,
        question: str,
        contexts: list[str],
        memory_text: str | None = None,
        timeout_seconds: float | None = None,
        model_name: str | None = None,
        prepared_prompt: PreparedPrompt | None = None,
    ) -> str:
        """单次生成调用，根据 provider 分发到具体实现，不包含重试逻辑。"""
        provider = self.settings.llm_provider.lower().strip()
        resolved_prompt = prepared_prompt or self.prepare_prompt(
            question=question,
            contexts=contexts,
            memory_text=memory_text,
        )
        if provider == "mock":
            return self._generate_with_mock(question=question, contexts=resolved_prompt.prepared_contexts)
        if provider == "ollama":
            return self._generate_with_ollama(
                prepared_prompt=resolved_prompt,
                timeout_seconds=timeout_seconds,
                model_name=model_name,
            )
        if provider in {"openai", "deepseek"}:
            return self._generate_with_openai(
                prepared_prompt=resolved_prompt,
                timeout_seconds=timeout_seconds,
                model_name=model_name,
            )
        raise LLMGenerationFatalError(f"Unsupported llm provider: {self.settings.llm_provider}")

    def generate_stream(
        self,
        *,
        question: str,
        contexts: list[str],
        memory_text: str | None = None,
        timeout_seconds: float | None = None,
        model_name: str | None = None,
        prepared_prompt: PreparedPrompt | None = None,
    ) -> Iterator[str]:
        """流式生成入口：逐 token 返回 LLM 输出，适用于前端逐字渲染场景。"""
        yield from self._stream_with_retry(
            question=question,
            contexts=contexts,
            memory_text=memory_text,
            timeout_seconds=timeout_seconds,
            model_name=model_name,
            prepared_prompt=prepared_prompt,
        )

    def _generate_stream_once(
        self,
        *,
        question: str,
        contexts: list[str],
        memory_text: str | None = None,
        timeout_seconds: float | None = None,
        model_name: str | None = None,
        prepared_prompt: PreparedPrompt | None = None,
    ) -> Iterator[str]:
        """单次流式生成调用，不含重试；由 _stream_with_retry 统一管理重试。"""
        provider = self.settings.llm_provider.lower().strip()
        resolved_prompt = prepared_prompt or self.prepare_prompt(
            question=question,
            contexts=contexts,
            memory_text=memory_text,
        )
        if provider == "mock":
            answer = self._generate_with_mock(question=question, contexts=resolved_prompt.prepared_contexts)
            yield from self._chunk_text(answer)
            return
        if provider == "ollama":
            yield from self._generate_with_ollama_stream(
                prepared_prompt=resolved_prompt,
                timeout_seconds=timeout_seconds,
                model_name=model_name,
            )
            return
        if provider in {"openai", "deepseek"}:
            yield from self._generate_with_openai_stream(
                prepared_prompt=resolved_prompt,
                timeout_seconds=timeout_seconds,
                model_name=model_name,
            )
            return
        raise LLMGenerationFatalError(f"Unsupported llm provider: {self.settings.llm_provider}")

    def _generate_with_mock(self, *, question: str, contexts: list[str]) -> str:
        """mock 生成：返回固定格式的模拟回答，用于本地联调和测试。"""
        if not contexts:
            return "No relevant context was retrieved for this question."
        top_context = contexts[0].strip()
        if len(top_context) > 280:
            top_context = f"{top_context[:277]}..."
        return f"Mock answer for '{question}': {top_context}"

    def _generate_with_ollama(
        self,
        *,
        prepared_prompt: PreparedPrompt,
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:
        """调用 Ollama /api/generate 接口，非流式一次性返回完整回答。"""
        if not prepared_prompt.prepared_contexts:
            return "No relevant context was retrieved for this question."

        base_url = get_llm_base_url(self.settings)
        url = f"{base_url}/api/generate"
        request_timeout = timeout_seconds or self.settings.llm_timeout_seconds  # 优先使用请求级超时，未显式传入时回退到全局默认。
        payload = {
            "model": self._resolve_model_name(model_name),
            "prompt": prepared_prompt.prompt,
            "stream": False,  # 关闭流式，一次性返回完整结果。
            "options": {"temperature": self.settings.llm_temperature},
        }

        try:
            response = httpx.post(
                url,
                json=payload,
                timeout=request_timeout,
                trust_env=False,  # 忽略系统代理，避免本地代理环境影响服务互调。
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMGenerationRetryableError(f"LLM request to Ollama timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                raise LLMGenerationRetryableError(f"LLM request to Ollama failed with server error: {exc}") from exc
            raise LLMGenerationFatalError(f"LLM request to Ollama failed with client error: {exc}") from exc
        except httpx.RequestError as exc:
            raise LLMGenerationRetryableError(f"LLM request to Ollama failed: {exc}") from exc

        data = response.json()
        text = data.get("response")  # Ollama 非流式响应正文在 response 字段。
        if not isinstance(text, str) or not text.strip():
            raise LLMGenerationFatalError("Unexpected Ollama response format for generation.")
        return text.strip()

    def _generate_with_ollama_stream(
        self,
        *,
        prepared_prompt: PreparedPrompt,
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> Iterator[str]:
        """调用 Ollama /api/generate 接口（stream=True），逐 token 返回。"""
        if not prepared_prompt.prepared_contexts:
            yield from self._chunk_text("No relevant context was retrieved for this question.")
            return

        base_url = get_llm_base_url(self.settings)
        url = f"{base_url}/api/generate"
        request_timeout = timeout_seconds or self.settings.llm_timeout_seconds
        payload = {
            "model": self._resolve_model_name(model_name),
            "prompt": prepared_prompt.prompt,
            "stream": True,
            "options": {"temperature": self.settings.llm_temperature},
        }

        try:
            with httpx.stream(
                "POST",
                url,
                json=payload,
                timeout=request_timeout,
                trust_env=False,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        frame = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # 跳过非法片段，尽量保证主流程不中断。
                    token = frame.get("response")
                    if isinstance(token, str) and token:
                        yield token
        except httpx.TimeoutException as exc:
            raise LLMGenerationRetryableError(f"LLM stream request to Ollama timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                raise LLMGenerationRetryableError(f"LLM stream request to Ollama failed with server error: {exc}") from exc
            raise LLMGenerationFatalError(f"LLM stream request to Ollama failed with client error: {exc}") from exc
        except httpx.RequestError as exc:
            raise LLMGenerationRetryableError(f"LLM stream request to Ollama failed: {exc}") from exc

    def _generate_with_openai(
        self,
        *,
        prepared_prompt: PreparedPrompt,
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:
        """调用 OpenAI-compatible /chat/completions 接口，非流式一次性返回完整回答。"""
        if not prepared_prompt.prepared_contexts:
            return "No relevant context was retrieved for this question."

        base_url = get_llm_base_url(self.settings)
        url = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"  # 兼容 base_url 是否已带完整路径。
        request_timeout = timeout_seconds or self.settings.llm_timeout_seconds
        headers = self._build_openai_headers()

        payload = {
            "model": self._resolve_model_name(model_name),
            "messages": [  # 固定 system 规则 + 单条 user 消息，兼容 vLLM 的 OpenAI 协议。
                {
                    "role": "system",
                    "content": "You are an enterprise assistant. Answer strictly based on the provided context.",
                },
                {
                    "role": "user",
                    "content": prepared_prompt.prompt,
                },
            ],
            "temperature": self.settings.llm_temperature,
            "stream": False,
            "max_tokens": self._get_prompt_budget().reserved_completion_tokens,  # 显式给回答保留 token，避免大 prompt 挤占输出预算。
        }

        try:
            response = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=request_timeout,
                trust_env=False,  # 忽略系统代理，避免本地代理环境影响服务互调。
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMGenerationRetryableError(f"LLM request to OpenAI-compatible server timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                raise LLMGenerationRetryableError(
                    f"LLM request to OpenAI-compatible server failed with server error: {exc}"
                ) from exc
            raise LLMGenerationFatalError(
                f"LLM request to OpenAI-compatible server failed with client error: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise LLMGenerationRetryableError(f"LLM request to OpenAI-compatible server failed: {exc}") from exc

        data = response.json()
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMGenerationFatalError("Unexpected OpenAI-compatible response format for generation.")

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):  # 少数实现返回 content block 数组，做兼容拼接。
            content = "".join(
                item.get("text", "") for item in content if isinstance(item, dict)
            )
        if not isinstance(content, str) or not content.strip():
            raise LLMGenerationFatalError("Unexpected OpenAI-compatible response content for generation.")
        return content.strip()

    def _generate_with_openai_stream(
        self,
        *,
        prepared_prompt: PreparedPrompt,
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> Iterator[str]:
        """调用 OpenAI-compatible /chat/completions 接口（stream=True），逐 token 返回。"""
        if not prepared_prompt.prepared_contexts:
            yield from self._chunk_text("No relevant context was retrieved for this question.")
            return

        base_url = get_llm_base_url(self.settings)
        url = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
        request_timeout = timeout_seconds or self.settings.llm_timeout_seconds
        headers = self._build_openai_headers()

        payload = {
            "model": self._resolve_model_name(model_name),
            "messages": [
                {
                    "role": "system",
                    "content": "You are an enterprise assistant. Answer strictly based on the provided context.",
                },
                {
                    "role": "user",
                    "content": prepared_prompt.prompt,
                },
            ],
            "temperature": self.settings.llm_temperature,
            "stream": True,
            "max_tokens": self._get_prompt_budget().reserved_completion_tokens,  # 显式给流式回答保留 token，避免被 prompt 挤占完预算。
        }

        try:
            with httpx.stream(
                "POST",
                url,
                json=payload,
                headers=headers,
                timeout=request_timeout,
                trust_env=False,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    raw_data = line[len("data:") :].strip()
                    if not raw_data or raw_data == "[DONE]":
                        continue
                    try:
                        frame = json.loads(raw_data)
                    except json.JSONDecodeError:
                        continue  # 跳过非法片段，尽量保证主流程不中断。
                    token = self._extract_openai_delta_text(frame)
                    if token:
                        yield token
        except httpx.TimeoutException as exc:
            raise LLMGenerationRetryableError(f"LLM stream request to OpenAI-compatible server timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                raise LLMGenerationRetryableError(
                    f"LLM stream request to OpenAI-compatible server failed with server error: {exc}"
                ) from exc
            raise LLMGenerationFatalError(
                f"LLM stream request to OpenAI-compatible server failed with client error: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise LLMGenerationRetryableError(f"LLM stream request to OpenAI-compatible server failed: {exc}") from exc

    def _build_openai_headers(self) -> dict[str, str]:
        """构造 OpenAI-compatible 请求头，包含 Content-Type 和可选的 Bearer 鉴权。"""
        headers = {"Content-Type": "application/json"}
        api_key = (self.settings.llm_api_key or "").strip()
        if not api_key:  # 无 key 时保持无鉴权头，兼容本地 vLLM 等无需 key 的服务。
            return headers
        if not api_key.isascii():  # httpx 请求头默认 ASCII 编码，提前拦截非法占位值。
            raise LLMGenerationFatalError(
                "LLM API key contains non-ASCII characters. Check RAG_LLM_API_KEY."
            )
        headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _run_with_retry(self, operation):
        """带重试的生成执行器：对可降级错误进行指数退避重试，直到达到最大重试次数。"""
        retry_controls = self.system_config_service.get_retry_controls()
        max_attempts = retry_controls.llm_retry_max_attempts if retry_controls.llm_retry_enabled else 1
        attempt = 0
        last_error: LLMGenerationRetryableError | None = None
        while attempt < max_attempts:
            attempt += 1
            try:
                return operation()
            except LLMGenerationRetryableError as exc:
                last_error = exc
                if attempt >= max_attempts:
                    raise
                self._sleep_backoff(retry_controls.llm_retry_backoff_ms)
        if last_error is not None:
            raise last_error
        raise LLMGenerationRetryableError("LLM generation failed before a retryable error was captured.")

    def _stream_with_retry(
        self,
        *,
        question: str,
        contexts: list[str],
        memory_text: str | None,
        timeout_seconds: float | None,
        model_name: str | None,
        prepared_prompt: PreparedPrompt | None,
    ) -> Iterator[str]:
        """带重试的流式生成执行器：已开始输出后不再重试，避免重复内容。"""
        retry_controls = self.system_config_service.get_retry_controls()
        max_attempts = retry_controls.llm_retry_max_attempts if retry_controls.llm_retry_enabled else 1
        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            started_streaming = False
            try:
                kwargs = dict(
                    question=question,
                    contexts=contexts,
                    memory_text=memory_text,
                    timeout_seconds=timeout_seconds,
                    model_name=model_name,
                )
                if prepared_prompt is not None:
                    kwargs["prepared_prompt"] = prepared_prompt
                for token in self._generate_stream_once(**kwargs):
                    started_streaming = True
                    yield token
                return
            except LLMGenerationRetryableError:
                if started_streaming or attempt >= max_attempts:
                    raise
                self._sleep_backoff(retry_controls.llm_retry_backoff_ms)

    def _resolve_model_name(self, override_model_name: str | None) -> str:
        """解析最终使用的模型名：优先使用调用方显式传入的覆盖值，否则回退到全局配置。"""
        resolved = (override_model_name or "").strip()
        if resolved:
            return resolved
        return get_llm_model(self.settings)

    @staticmethod
    def _sleep_backoff(backoff_ms: int) -> None:
        """按毫秒级退避时间休眠，值为 0 或负数时跳过。"""
        if backoff_ms <= 0:
            return
        sleep(backoff_ms / 1000)

    @staticmethod
    def _extract_openai_delta_text(frame: dict[str, object]) -> str:
        """从 OpenAI-compatible 流式帧中提取 delta 文本片段。"""
        choices = frame.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        delta = first.get("delta")
        if not isinstance(delta, dict):
            return ""
        content = delta.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):  # 少数实现返回 content block 数组。
            return "".join(item.get("text", "") for item in content if isinstance(item, dict))
        return ""

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 32) -> Iterator[str]:
        """将文本按固定字符大小切分，用于 mock 流式输出。"""
        for start in range(0, len(text), max(1, chunk_size)):
            yield text[start : start + max(1, chunk_size)]

    def prepare_prompt(self, *, question: str, contexts: list[str], memory_text: str | None = None) -> PreparedPrompt:
        """根据 token 预算裁剪上下文和记忆，拼装最终 prompt 并返回完整的 PreparedPrompt 统计结构。"""
        prompt_budget = self._get_prompt_budget()
        prepared_memory = self._prepare_memory_for_prompt(memory_text, prompt_budget=prompt_budget)
        original_contexts = [chunk.strip() for chunk in contexts if isinstance(chunk, str) and chunk.strip()]
        pretrimmed_contexts, deduplicated_context_count, pretrimmed_context_count = self._pretrim_context_candidates(
            question=question,
            contexts=original_contexts,
            memory_text=prepared_memory,
            prompt_budget=prompt_budget,
        )
        prepared_contexts = self._prepare_contexts_for_prompt(
            question=question,
            contexts=pretrimmed_contexts,
            memory_text=prepared_memory,
            prompt_budget=prompt_budget,
        )
        context_blocks = []
        for index, chunk in enumerate(prepared_contexts, start=1):  # 给每段上下文编号，便于模型引用。
            context_blocks.append(f"[Context {index}]\n{chunk.strip()}")

        prompt_parts = [
            "If the context does not contain the answer, say you cannot find enough evidence.",
        ]
        if prepared_memory:
            prompt_parts.append(
                "[Recent Conversation]\n"
                "Use the recent conversation only to resolve follow-up references. Do not treat it as evidence over the retrieved context.\n"
                f"{prepared_memory}"
            )
        if context_blocks:
            prompt_parts.append("\n\n".join(context_blocks))
        prompt_parts.append(f"Question: {question}\nAnswer:")
        prompt = "\n\n".join(prompt_parts)
        original_context_count = len(original_contexts)
        prepared_context_count = len(prepared_contexts)
        truncated_context_count = sum(
            1
            for original, prepared in zip(
                pretrimmed_contexts,
                prepared_contexts,
            )
            if original != prepared
        )
        context_token_estimate = sum(self._estimate_token_count(chunk) for chunk in prepared_contexts)
        memory_token_estimate = self._estimate_token_count(prepared_memory) if prepared_memory else 0
        return PreparedPrompt(
            prompt=prompt,
            prepared_contexts=prepared_contexts,
            prepared_memory=prepared_memory,
            original_context_count=original_context_count,
            deduplicated_context_count=deduplicated_context_count,
            pretrimmed_context_count=pretrimmed_context_count,
            prepared_context_count=prepared_context_count,
            truncated_context_count=truncated_context_count,
            context_token_estimate=context_token_estimate,
            memory_token_estimate=memory_token_estimate,
            prompt_token_estimate=self._estimate_token_count(prompt),
        )

    def _build_prompt(self, *, question: str, contexts: list[str], memory_text: str | None = None) -> str:
        """简化版 prompt 构建：只返回 prompt 文本，不附带统计信息。"""
        return self.prepare_prompt(question=question, contexts=contexts, memory_text=memory_text).prompt

    def _prepare_contexts_for_prompt(
        self,
        *,
        question: str,
        contexts: list[str],
        memory_text: str | None = None,
        prompt_budget: PromptBudgetConfig,
    ) -> list[str]:
        """在 token 预算内逐条裁剪上下文片段，超出预算的条目会被截断或丢弃。"""
        normalized_contexts = [chunk.strip() for chunk in contexts if isinstance(chunk, str) and chunk.strip()]
        if not normalized_contexts:
            return []

        prompt_token_budget = max(256, prompt_budget.max_prompt_tokens)
        prompt_overhead_tokens = self._estimate_token_count(
            "If the context does not contain the answer, say you cannot find enough evidence.\n\n"
            + (
                "[Recent Conversation]\n"
                "Use the recent conversation only to resolve follow-up references. Do not treat it as evidence over the retrieved context.\n"
                f"{memory_text}\n\n"
                if memory_text
                else ""
            )
            + f"Question: {question}\n"
            + "Answer:"
        )
        remaining_budget = max(128, prompt_token_budget - prompt_overhead_tokens)
        prepared_contexts: list[str] = []

        for index, chunk in enumerate(normalized_contexts, start=1):
            remaining_items = len(normalized_contexts) - index + 1
            context_prefix = f"[Context {index}]\n"
            prefix_tokens = self._estimate_token_count(context_prefix)
            separator_tokens = 2
            available_tokens = remaining_budget - prefix_tokens - separator_tokens
            if available_tokens <= 0:
                break

            chunk_tokens = self._estimate_token_count(chunk)
            context_soft_budget = available_tokens if remaining_items <= 1 else min(
                available_tokens,
                max(48, available_tokens // remaining_items),
            )
            if chunk_tokens <= available_tokens and (
                remaining_items <= 1 or chunk_tokens <= context_soft_budget
            ):
                prepared_contexts.append(chunk)
                remaining_budget -= prefix_tokens + chunk_tokens + separator_tokens
                continue

            target_budget = available_tokens if remaining_items <= 1 else context_soft_budget
            truncated_chunk = self._truncate_text_to_token_budget(chunk, target_budget)
            if truncated_chunk:
                prepared_contexts.append(truncated_chunk)
                remaining_budget -= prefix_tokens + self._estimate_token_count(truncated_chunk) + separator_tokens
                continue
            break

        if prepared_contexts:
            return prepared_contexts
        return [self._truncate_text_to_token_budget(normalized_contexts[0], remaining_budget)]

    def _pretrim_context_candidates(
        self,
        *,
        question: str,
        contexts: list[str],
        memory_text: str | None,
        prompt_budget: PromptBudgetConfig,
    ) -> tuple[list[str], int, int]:
        """去重并预裁剪上下文候选列表，返回 (裁剪后列表, 去重后数量, 预裁剪数量)。"""
        if not contexts:
            return [], 0, 0

        unique_contexts: list[str] = []
        seen_fingerprints: set[str] = set()
        for chunk in contexts:
            fingerprint = " ".join(chunk.split())
            if not fingerprint or fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)
            unique_contexts.append(chunk)

        prompt_token_budget = max(256, prompt_budget.max_prompt_tokens)
        prompt_overhead_tokens = self._estimate_token_count(
            "If the context does not contain the answer, say you cannot find enough evidence.\n\n"
            + (
                "[Recent Conversation]\n"
                "Use the recent conversation only to resolve follow-up references. Do not treat it as evidence over the retrieved context.\n"
                f"{memory_text}\n\n"
                if memory_text
                else ""
            )
            + f"Question: {question}\n"
            + "Answer:"
        )
        available_context_budget = max(128, prompt_token_budget - prompt_overhead_tokens)
        context_slots = max(1, min(len(unique_contexts), 6))
        average_context_budget = max(64, available_context_budget // context_slots)
        pretrim_budget = min(available_context_budget, max(96, average_context_budget * 2))

        pretrimmed_contexts: list[str] = []
        pretrimmed_count = 0
        for chunk in unique_contexts:
            chunk_tokens = self._estimate_token_count(chunk)
            if chunk_tokens > pretrim_budget:
                pretrimmed_context = self._truncate_text_to_token_budget(chunk, pretrim_budget)
                pretrimmed_count += 1
            else:
                pretrimmed_context = chunk
            if pretrimmed_context:
                pretrimmed_contexts.append(pretrimmed_context)

        return pretrimmed_contexts, len(unique_contexts), pretrimmed_count

    def _prepare_memory_for_prompt(self, memory_text: str | None, *, prompt_budget: PromptBudgetConfig) -> str | None:
        """裁剪对话记忆文本到预算范围内，超出部分截断。"""
        normalized = (memory_text or "").strip()
        if not normalized:
            return None
        memory_budget = max(32, prompt_budget.memory_prompt_tokens)
        return self._truncate_text_to_token_budget(normalized, memory_budget)

    def _get_prompt_budget(self) -> PromptBudgetConfig:
        """从系统配置服务获取当前 prompt token 预算配置。"""
        return self.system_config_service.get_prompt_budget()

    def _estimate_token_count(self, text: str) -> int:
        """估算文本的 token 数量，委托给 TokenBudgetService。"""
        return self.token_budget_service.estimate_token_count(
            text,
            model_name=self._resolve_model_name(None),
        )

    def _truncate_text_to_token_budget(self, text: str, token_budget: int) -> str:
        """按 token 预算截断文本，委托给 TokenBudgetService。"""
        return self.token_budget_service.truncate_text_to_token_budget(
            text,
            token_budget,
            model_name=self._resolve_model_name(None),
        )
