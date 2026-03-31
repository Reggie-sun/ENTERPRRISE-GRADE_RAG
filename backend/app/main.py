"""
FastAPI 应用入口模块。

职责：创建 FastAPI 应用实例，注册中间件（CORS）、异常处理器、路由，
管理应用生命周期（启动时创建数据目录）。
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .api.router import api_router
from .core.config import ensure_data_directories, get_settings
from .schemas.errors import ErrorEnvelope, ErrorInfo

# 全局配置单例
settings = get_settings()
# Demo 页面文件路径
DEMO_PAGE = Path(__file__).resolve().parent / "web" / "demo.html"


def _http_error_code(status_code: int) -> str:
    """将 HTTP 状态码映射为标准化的错误代码字符串。

    Args:
        status_code: HTTP 状态码。
    Returns:
        对应的错误代码字符串，未匹配时返回 "http_error"。
    """
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        413: "payload_too_large",
        422: "unprocessable_entity",
        429: "too_many_requests",
        500: "internal_server_error",
        502: "bad_gateway",
        503: "service_unavailable",
        504: "gateway_timeout",
    }.get(status_code, "http_error")


def _build_error_envelope(*, status_code: int, detail: object, code: str | None = None, message: str | None = None) -> dict[str, object]:
    """构建统一的错误响应信封（ErrorEnvelope），确保所有 API 错误返回格式一致。

    Args:
        status_code: HTTP 状态码。
        detail: 错误详情（可为字符串或结构化对象）。
        code: 自定义错误代码（不传则自动从状态码推导）。
        message: 错误消息（不传则使用 detail 或默认消息）。
    Returns:
        序列化后的错误信封字典。
    """
    resolved_code = code or _http_error_code(status_code)
    resolved_message = message
    if resolved_message is None:
        resolved_message = detail if isinstance(detail, str) else "Request validation failed."
    envelope = ErrorEnvelope(
        detail=detail,
        error=ErrorInfo(code=resolved_code, message=resolved_message, status_code=status_code),
    )
    return envelope.model_dump(mode="json")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用生命周期管理：启动时确保所有数据目录存在。"""
    ensure_data_directories(settings)
    yield


# ── 创建 FastAPI 应用实例 ──────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="V1 skeleton for an enterprise-grade RAG system.",
    lifespan=lifespan,
)

# 注册 CORS 中间件，允许配置的跨域来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册所有 API 路由
app.include_router(api_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    """全局 HTTP 异常处理器：将 HTTPException 转换为统一的错误信封格式。"""
    return JSONResponse(
        status_code=exc.status_code,
        content=_build_error_envelope(status_code=exc.status_code, detail=exc.detail),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """全局请求校验异常处理器：将 Pydantic 校验错误转为统一错误信封。"""
    # 沿用 FastAPI 默认错误明细，再补稳定的 error envelope
    default_response = await request_validation_exception_handler(request, exc)
    return JSONResponse(
        status_code=default_response.status_code,
        content=_build_error_envelope(
            status_code=default_response.status_code,
            detail=exc.errors(),
            code="validation_error",
            message="Request validation failed.",
        ),
        headers=default_response.headers,
    )


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    """系统根路由：返回应用基本信息和可用入口。"""
    return {
        "app": settings.app_name,
        "version": "0.1.0",
        "api_prefix": settings.api_v1_prefix,
        "docs": "/docs",
        "demo": "/demo",
    }


@app.get("/demo", include_in_schema=False)
def demo() -> FileResponse:
    """Demo 页面路由：返回静态 demo.html 文件。"""
    return FileResponse(DEMO_PAGE)
