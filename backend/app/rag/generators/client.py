import httpx  # 导入 httpx，用于调用远程 LLM 服务。

from ...core.config import Settings  # 导入配置对象。


class LLMGenerationClient:  # 封装问答生成逻辑，支持 mock 和 ollama 两种 provider。
    def __init__(self, settings: Settings) -> None:  # 初始化生成客户端。
        self.settings = settings  # 保存配置对象。

    def generate(self, *, question: str, contexts: list[str]) -> str:  # 基于问题和上下文生成最终回答文本。
        provider = self.settings.llm_provider.lower().strip()  # 读取并标准化 provider 名称。
        if provider == "mock":  # mock 模式用于本地开发和测试。
            return self._generate_with_mock(question=question, contexts=contexts)  # 返回确定性 mock 回答。
        if provider == "ollama":  # ollama 模式调用远程生成服务。
            return self._generate_with_ollama(question=question, contexts=contexts)  # 返回模型生成结果。
        raise RuntimeError(f"Unsupported llm provider: {self.settings.llm_provider}")  # provider 非法时抛错。

    def _generate_with_mock(self, *, question: str, contexts: list[str]) -> str:  # 本地 mock 生成逻辑。
        if not contexts:  # 如果没有上下文，直接返回明确提示。
            return "No relevant context was retrieved for this question."
        top_context = contexts[0].strip()  # 取 top1 片段作为核心依据。
        if len(top_context) > 280:  # 避免 mock 回答过长。
            top_context = f"{top_context[:277]}..."
        return f"Mock answer for '{question}': {top_context}"  # 组合成可读回答。

    def _generate_with_ollama(self, *, question: str, contexts: list[str]) -> str:  # 调用 Ollama 风格接口生成回答。
        if not contexts:  # 如果没有上下文，直接给出简短提示。
            return "No relevant context was retrieved for this question."

        base_url = self.settings.ollama_base_url.rstrip("/")  # 读取 Ollama 服务地址。
        url = f"{base_url}/api/generate"  # 拼出 Ollama generate 接口地址。
        prompt = self._build_prompt(question=question, contexts=contexts)  # 先构造提示词。
        payload = {  # 组织请求体。
            "model": self.settings.ollama_model,  # 指定模型名。
            "prompt": prompt,  # 传入 prompt。
            "stream": False,  # 关闭流式，便于一次性拿结果。
            "options": {"temperature": self.settings.llm_temperature},  # 传入温度等采样参数。
        }

        try:  # 尝试请求 Ollama 服务。
            response = httpx.post(  # 发起 POST 请求。
                url,  # 目标地址。
                json=payload,  # 请求体。
                timeout=self.settings.llm_timeout_seconds,  # 超时时间。
                trust_env=False,  # 忽略系统代理配置，避免本地代理环境影响服务互调。
            )
            response.raise_for_status()  # 检查 HTTP 状态码。
        except Exception as exc:  # 捕获网络、代理配置等异常。
            raise RuntimeError(f"LLM request to Ollama failed: {exc}") from exc  # 转换成统一运行时错误。

        data = response.json()  # 解析 JSON 响应。
        text = data.get("response")  # Ollama 非流式响应正文在 response 字段。
        if not isinstance(text, str) or not text.strip():  # 返回内容为空或格式不对时抛错。
            raise RuntimeError("Unexpected Ollama response format for generation.")  # 抛出格式错误。
        return text.strip()  # 返回清理后的回答。

    @staticmethod
    def _build_prompt(*, question: str, contexts: list[str]) -> str:  # 组装一个简单稳妥的 RAG prompt。
        context_blocks = []  # 初始化上下文块列表。
        for index, chunk in enumerate(contexts, start=1):  # 给每段上下文编号，便于模型引用。
            context_blocks.append(f"[Context {index}]\n{chunk.strip()}")  # 写入编号和正文。

        joined_context = "\n\n".join(context_blocks)  # 把上下文块拼接成最终文本。
        return (
            "You are an enterprise assistant. Answer strictly based on the provided context.\n"
            "If the context does not contain the answer, say you cannot find enough evidence.\n\n"
            f"{joined_context}\n\n"
            f"Question: {question}\n"
            "Answer:"
        )  # 返回完整 prompt。
