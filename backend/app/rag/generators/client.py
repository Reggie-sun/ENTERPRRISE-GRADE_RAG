import json  # 导入 json，用于解析流式响应片段。
from time import sleep
from typing import Iterator  # 导入 Iterator，用于声明流式输出迭代器类型。

import httpx  # 导入 httpx，用于调用远程 LLM 服务。

from ...core.config import Settings, get_llm_base_url, get_llm_model  # 导入配置对象和统一的 LLM 配置解析函数。
from ...services.system_config_service import SystemConfigService


class LLMGenerationError(RuntimeError):  # 生成阶段统一异常基类，便于上层按类型区分处理策略。
    pass


class LLMGenerationRetryableError(LLMGenerationError):  # 可降级故障：网络抖动、超时、远端 5xx。
    pass


class LLMGenerationFatalError(LLMGenerationError):  # 不可降级错误：配置错误、请求参数错误、返回格式异常。
    pass


class LLMGenerationClient:  # 封装问答生成逻辑，支持 mock / ollama / openai / deepseek 四种 provider。
    def __init__(
        self,
        settings: Settings,
        *,
        system_config_service: SystemConfigService | None = None,
    ) -> None:  # 初始化生成客户端。
        self.settings = settings  # 保存配置对象。
        self.system_config_service = system_config_service or SystemConfigService(settings)

    def generate(
        self,
        *,
        question: str,
        contexts: list[str],
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:  # 基于问题和上下文生成最终回答文本。
        return self._run_with_retry(
            lambda: self._generate_once(
                question=question,
                contexts=contexts,
                timeout_seconds=timeout_seconds,
                model_name=model_name,
            )
        )

    def _generate_once(
        self,
        *,
        question: str,
        contexts: list[str],
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:
        provider = self.settings.llm_provider.lower().strip()  # 读取并标准化 provider 名称。
        if provider == "mock":  # mock 模式用于本地开发和测试。
            return self._generate_with_mock(question=question, contexts=contexts)  # 返回确定性 mock 回答。
        if provider == "ollama":  # ollama 模式调用远程生成服务。
            return self._generate_with_ollama(
                question=question,
                contexts=contexts,
                timeout_seconds=timeout_seconds,
                model_name=model_name,
            )  # 返回模型生成结果。
        if provider in {"openai", "deepseek"}:  # openai/deepseek 模式统一调用 OpenAI 兼容的 chat completions 接口。
            return self._generate_with_openai(
                question=question,
                contexts=contexts,
                timeout_seconds=timeout_seconds,
                model_name=model_name,
            )  # 返回模型生成结果。
        raise LLMGenerationFatalError(f"Unsupported llm provider: {self.settings.llm_provider}")  # provider 非法时直接抛不可降级错误。

    def generate_stream(
        self,
        *,
        question: str,
        contexts: list[str],
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> Iterator[str]:  # 以流式片段形式返回回答内容。
        yield from self._stream_with_retry(
            question=question,
            contexts=contexts,
            timeout_seconds=timeout_seconds,
            model_name=model_name,
        )

    def _generate_stream_once(
        self,
        *,
        question: str,
        contexts: list[str],
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> Iterator[str]:
        provider = self.settings.llm_provider.lower().strip()  # 读取并标准化 provider 名称。
        if provider == "mock":  # mock 模式用固定文本切片模拟流式。
            answer = self._generate_with_mock(question=question, contexts=contexts)
            yield from self._chunk_text(answer)
            return
        if provider == "ollama":  # ollama 模式调用流式接口。
            yield from self._generate_with_ollama_stream(
                question=question,
                contexts=contexts,
                timeout_seconds=timeout_seconds,
                model_name=model_name,
            )
            return
        if provider in {"openai", "deepseek"}:  # openai/deepseek 兼容模式统一调用 SSE 流式接口。
            yield from self._generate_with_openai_stream(
                question=question,
                contexts=contexts,
                timeout_seconds=timeout_seconds,
                model_name=model_name,
            )
            return
        raise LLMGenerationFatalError(f"Unsupported llm provider: {self.settings.llm_provider}")  # provider 非法时直接抛不可降级错误。

    def _generate_with_mock(self, *, question: str, contexts: list[str]) -> str:  # 本地 mock 生成逻辑。
        if not contexts:  # 如果没有上下文，直接返回明确提示。
            return "No relevant context was retrieved for this question."
        top_context = contexts[0].strip()  # 取 top1 片段作为核心依据。
        if len(top_context) > 280:  # 避免 mock 回答过长。
            top_context = f"{top_context[:277]}..."
        return f"Mock answer for '{question}': {top_context}"  # 组合成可读回答。

    def _generate_with_ollama(
        self,
        *,
        question: str,
        contexts: list[str],
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:  # 调用 Ollama 风格接口生成回答。
        if not contexts:  # 如果没有上下文，直接给出简短提示。
            return "No relevant context was retrieved for this question."

        base_url = get_llm_base_url(self.settings)  # 读取当前生效的 LLM 服务地址。
        url = f"{base_url}/api/generate"  # 拼出 Ollama generate 接口地址。
        request_timeout = timeout_seconds or self.settings.llm_timeout_seconds  # 优先使用请求级预算，未显式传入时回退到全局默认。
        prompt = self._build_prompt(question=question, contexts=contexts)  # 先构造提示词。
        payload = {  # 组织请求体。
            "model": self._resolve_model_name(model_name),  # 指定模型名。
            "prompt": prompt,  # 传入 prompt。
            "stream": False,  # 关闭流式，便于一次性拿结果。
            "options": {"temperature": self.settings.llm_temperature},  # 传入温度等采样参数。
        }

        try:  # 尝试请求 Ollama 服务。
            response = httpx.post(  # 发起 POST 请求。
                url,  # 目标地址。
                json=payload,  # 请求体。
                timeout=request_timeout,  # 超时时间。
                trust_env=False,  # 忽略系统代理配置，避免本地代理环境影响服务互调。
            )
            response.raise_for_status()  # 检查 HTTP 状态码。
        except httpx.TimeoutException as exc:  # 超时属于暂时性故障，可降级。
            raise LLMGenerationRetryableError(f"LLM request to Ollama timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:  # 按状态码区分是否可降级。
            if exc.response.status_code >= 500:  # 远端 5xx 视为暂时性故障。
                raise LLMGenerationRetryableError(f"LLM request to Ollama failed with server error: {exc}") from exc
            raise LLMGenerationFatalError(f"LLM request to Ollama failed with client error: {exc}") from exc
        except httpx.RequestError as exc:  # 连接失败、网络错误属于可降级故障。
            raise LLMGenerationRetryableError(f"LLM request to Ollama failed: {exc}") from exc

        data = response.json()  # 解析 JSON 响应。
        text = data.get("response")  # Ollama 非流式响应正文在 response 字段。
        if not isinstance(text, str) or not text.strip():  # 返回内容为空或格式不对时抛错。
            raise LLMGenerationFatalError("Unexpected Ollama response format for generation.")  # 返回协议异常属于不可降级错误。
        return text.strip()  # 返回清理后的回答。

    def _generate_with_ollama_stream(
        self,
        *,
        question: str,
        contexts: list[str],
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> Iterator[str]:  # 调用 Ollama 流式生成接口。
        if not contexts:  # 无上下文时直接返回固定提示。
            yield from self._chunk_text("No relevant context was retrieved for this question.")
            return

        base_url = get_llm_base_url(self.settings)  # 读取当前生效的 LLM 服务地址。
        url = f"{base_url}/api/generate"  # 拼出 Ollama generate 接口地址。
        request_timeout = timeout_seconds or self.settings.llm_timeout_seconds  # 优先使用请求级预算。
        payload = {
            "model": self._resolve_model_name(model_name),
            "prompt": self._build_prompt(question=question, contexts=contexts),
            "stream": True,  # 打开流式输出。
            "options": {"temperature": self.settings.llm_temperature},
        }

        try:  # 尝试请求 Ollama 服务。
            with httpx.stream(  # 使用流式读取，边到达边输出。
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
                        continue  # 遇到非法片段时跳过，尽量保证主流程不中断。
                    token = frame.get("response")
                    if isinstance(token, str) and token:
                        yield token
        except httpx.TimeoutException as exc:  # 超时属于可降级故障。
            raise LLMGenerationRetryableError(f"LLM stream request to Ollama timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:  # 按状态码区分是否可降级。
            if exc.response.status_code >= 500:
                raise LLMGenerationRetryableError(f"LLM stream request to Ollama failed with server error: {exc}") from exc
            raise LLMGenerationFatalError(f"LLM stream request to Ollama failed with client error: {exc}") from exc
        except httpx.RequestError as exc:  # 连接失败、网络错误可降级。
            raise LLMGenerationRetryableError(f"LLM stream request to Ollama failed: {exc}") from exc

    def _generate_with_openai(
        self,
        *,
        question: str,
        contexts: list[str],
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:  # 调用 OpenAI 兼容的 chat completions 接口生成回答。
        if not contexts:  # 如果没有上下文，直接给出简短提示。
            return "No relevant context was retrieved for this question."

        base_url = get_llm_base_url(self.settings)  # 读取当前生效的 LLM 服务地址。
        url = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"  # 自动兼容 base_url 是否已带完整路径。
        request_timeout = timeout_seconds or self.settings.llm_timeout_seconds  # 优先使用请求级预算。
        headers = self._build_openai_headers()  # 统一构造请求头，并提前拦截非法 API Key。

        payload = {  # 组织 OpenAI 兼容 chat 请求体。
            "model": self._resolve_model_name(model_name),  # 指定模型名。
            "messages": [  # 使用固定 system 规则和单条 user 消息，兼容 vLLM 的 OpenAI 协议。
                {
                    "role": "system",
                    "content": "You are an enterprise assistant. Answer strictly based on the provided context.",
                },
                {
                    "role": "user",
                    "content": self._build_prompt(question=question, contexts=contexts),
                },
            ],
            "temperature": self.settings.llm_temperature,  # 传入采样温度。
            "stream": False,  # 关闭流式，便于同步接口直接取回答。
        }

        try:  # 尝试请求 OpenAI 兼容服务。
            response = httpx.post(  # 发起 POST 请求。
                url,  # 目标地址。
                json=payload,  # 请求体。
                headers=headers,  # 请求头。
                timeout=request_timeout,  # 超时时间。
                trust_env=False,  # 忽略系统代理配置，避免本地代理环境影响服务互调。
            )
            response.raise_for_status()  # 检查 HTTP 状态码。
        except httpx.TimeoutException as exc:  # 超时属于可降级故障。
            raise LLMGenerationRetryableError(f"LLM request to OpenAI-compatible server timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:  # 按状态码区分是否可降级。
            if exc.response.status_code >= 500:  # 远端 5xx 走降级。
                raise LLMGenerationRetryableError(
                    f"LLM request to OpenAI-compatible server failed with server error: {exc}"
                ) from exc
            raise LLMGenerationFatalError(
                f"LLM request to OpenAI-compatible server failed with client error: {exc}"
            ) from exc
        except httpx.RequestError as exc:  # 连接失败、网络错误可降级。
            raise LLMGenerationRetryableError(f"LLM request to OpenAI-compatible server failed: {exc}") from exc

        data = response.json()  # 解析 JSON 响应。
        choices = data.get("choices")  # OpenAI 兼容 chat 返回内容在 choices 字段。
        if not isinstance(choices, list) or not choices:  # 没有 choices 时直接报错。
            raise LLMGenerationFatalError("Unexpected OpenAI-compatible response format for generation.")  # 返回协议异常属于不可降级错误。

        message = choices[0].get("message") if isinstance(choices[0], dict) else None  # 取第一条选择的 message。
        content = message.get("content") if isinstance(message, dict) else None  # 读取 message 里的 content。
        if isinstance(content, list):  # 少数实现会返回 content block 数组，这里做一次兼容拼接。
            content = "".join(  # 只拼接文本块，忽略未知结构。
                item.get("text", "") for item in content if isinstance(item, dict)
            )
        if not isinstance(content, str) or not content.strip():  # 返回正文为空或格式不对时抛错。
            raise LLMGenerationFatalError("Unexpected OpenAI-compatible response content for generation.")  # 返回协议异常属于不可降级错误。
        return content.strip()  # 返回清理后的回答。

    def _generate_with_openai_stream(
        self,
        *,
        question: str,
        contexts: list[str],
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> Iterator[str]:  # 调用 OpenAI 兼容流式接口。
        if not contexts:  # 无上下文时直接返回固定提示。
            yield from self._chunk_text("No relevant context was retrieved for this question.")
            return

        base_url = get_llm_base_url(self.settings)  # 读取当前生效的 LLM 服务地址。
        url = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
        request_timeout = timeout_seconds or self.settings.llm_timeout_seconds  # 优先使用请求级预算。
        headers = self._build_openai_headers()  # 统一构造请求头，并提前拦截非法 API Key。

        payload = {
            "model": self._resolve_model_name(model_name),
            "messages": [
                {
                    "role": "system",
                    "content": "You are an enterprise assistant. Answer strictly based on the provided context.",
                },
                {
                    "role": "user",
                    "content": self._build_prompt(question=question, contexts=contexts),
                },
            ],
            "temperature": self.settings.llm_temperature,
            "stream": True,  # 打开流式输出。
        }

        try:  # 尝试请求 OpenAI 兼容服务。
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
                        continue  # 遇到非法片段时跳过，尽量保证主流程不中断。
                    token = self._extract_openai_delta_text(frame)
                    if token:
                        yield token
        except httpx.TimeoutException as exc:  # 超时属于可降级故障。
            raise LLMGenerationRetryableError(f"LLM stream request to OpenAI-compatible server timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:  # 按状态码区分是否可降级。
            if exc.response.status_code >= 500:
                raise LLMGenerationRetryableError(
                    f"LLM stream request to OpenAI-compatible server failed with server error: {exc}"
                ) from exc
            raise LLMGenerationFatalError(
                f"LLM stream request to OpenAI-compatible server failed with client error: {exc}"
            ) from exc
        except httpx.RequestError as exc:  # 连接失败、网络错误可降级。
            raise LLMGenerationRetryableError(f"LLM stream request to OpenAI-compatible server failed: {exc}") from exc

    def _build_openai_headers(self) -> dict[str, str]:  # 统一构造 OpenAI 兼容请求头，并尽早暴露配置问题。
        headers = {"Content-Type": "application/json"}
        api_key = (self.settings.llm_api_key or "").strip()
        if not api_key:  # 没配 key 时保持无鉴权头，兼容本地 vLLM 等无需 key 的服务。
            return headers
        if not api_key.isascii():  # httpx 请求头默认按 ASCII 编码，先把明显非法的占位值拦下来。
            raise LLMGenerationFatalError(
                "LLM API key contains non-ASCII characters. Check RAG_LLM_API_KEY."
            )
        headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _run_with_retry(self, operation):
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
        timeout_seconds: float | None,
        model_name: str | None,
    ) -> Iterator[str]:
        retry_controls = self.system_config_service.get_retry_controls()
        max_attempts = retry_controls.llm_retry_max_attempts if retry_controls.llm_retry_enabled else 1
        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            started_streaming = False
            try:
                for token in self._generate_stream_once(
                    question=question,
                    contexts=contexts,
                    timeout_seconds=timeout_seconds,
                    model_name=model_name,
                ):
                    started_streaming = True
                    yield token
                return
            except LLMGenerationRetryableError:
                if started_streaming or attempt >= max_attempts:
                    raise
                self._sleep_backoff(retry_controls.llm_retry_backoff_ms)

    def _resolve_model_name(self, override_model_name: str | None) -> str:
        resolved = (override_model_name or "").strip()
        if resolved:
            return resolved
        return get_llm_model(self.settings)

    @staticmethod
    def _sleep_backoff(backoff_ms: int) -> None:
        if backoff_ms <= 0:
            return
        sleep(backoff_ms / 1000)

    @staticmethod
    def _extract_openai_delta_text(frame: dict[str, object]) -> str:  # 提取单个 SSE 片段里的文本增量。
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
    def _chunk_text(text: str, chunk_size: int = 32) -> Iterator[str]:  # 把文本切成小片段，兼容不支持原生流式的模式。
        for start in range(0, len(text), max(1, chunk_size)):
            yield text[start : start + max(1, chunk_size)]

    @staticmethod
    def _build_prompt(*, question: str, contexts: list[str]) -> str:  # 组装一个简单稳妥的 RAG prompt。
        context_blocks = []  # 初始化上下文块列表。
        for index, chunk in enumerate(contexts, start=1):  # 给每段上下文编号，便于模型引用。
            context_blocks.append(f"[Context {index}]\n{chunk.strip()}")  # 写入编号和正文。

        joined_context = "\n\n".join(context_blocks)  # 把上下文块拼接成最终文本。
        return (
            "If the context does not contain the answer, say you cannot find enough evidence.\n\n"
            f"{joined_context}\n\n"
            f"Question: {question}\n"
            "Answer:"
        )  # 返回完整 prompt。
