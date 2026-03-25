from fastapi import APIRouter, Depends  # 导入路由对象和依赖注入工具。
from fastapi.responses import StreamingResponse  # 导入流式响应类型。

from ....schemas.chat import ChatRequest, ChatResponse  # 导入问答接口的请求和响应模型。
from ....services.chat_service import ChatService, get_chat_service  # 导入问答服务和依赖工厂函数。

router = APIRouter(prefix="/chat", tags=["chat"])  # 创建 chat 路由分组，并统一加上 /chat 前缀。


@router.post("/ask", response_model=ChatResponse)  # 声明 POST /chat/ask 接口，并指定响应模型。
def ask_question(  # 定义问答接口函数。
    request: ChatRequest,  # 从请求体中接收用户问题和 top_k 参数。
    chat_service: ChatService = Depends(get_chat_service),  # 通过依赖注入获取问答服务实例。
) -> ChatResponse:
    return chat_service.answer(request)  # 调用服务层生成回答并直接返回。


@router.post("/ask/stream")  # 声明 POST /chat/ask/stream 接口，返回 SSE 流式问答结果。
def ask_question_stream(  # 定义流式问答接口函数。
    request: ChatRequest,  # 从请求体中接收用户问题和 top_k 参数。
    chat_service: ChatService = Depends(get_chat_service),  # 通过依赖注入获取问答服务实例。
) -> StreamingResponse:
    return StreamingResponse(  # 以 text/event-stream 返回 token 片段和最终结果。
        chat_service.stream_answer_sse(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
