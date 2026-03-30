from contextlib import asynccontextmanager  # 导入异步上下文管理器，用来注册应用启动和关闭逻辑。
from pathlib import Path  # 导入 Path，用于定位 demo 页面文件。

from fastapi import FastAPI, HTTPException, Request  # 导入 FastAPI 主应用类。
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse  # 导入文件响应，用于返回内置 demo 页面。
from fastapi.middleware.cors import CORSMiddleware  # 导入 CORS 中间件，允许前端跨域访问接口。

from .api.router import api_router  # 导入项目总路由，后面统一挂到 app 上。
from .core.config import ensure_data_directories, get_settings  # 导入配置读取和数据目录初始化函数。
from .schemas.errors import ErrorEnvelope, ErrorInfo

settings = get_settings()  # 读取当前项目配置，后续创建应用和中间件时直接复用。
DEMO_PAGE = Path(__file__).resolve().parent / "web" / "demo.html"  # 内置前端 demo 的静态页面路径。


def _http_error_code(status_code: int) -> str:
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
    resolved_code = code or _http_error_code(status_code)
    resolved_message = message
    if resolved_message is None:
        resolved_message = detail if isinstance(detail, str) else "Request validation failed."
    envelope = ErrorEnvelope(
        detail=detail,
        error=ErrorInfo(code=resolved_code, message=resolved_message, status_code=status_code),
    )
    return envelope.model_dump(mode="json")


@asynccontextmanager  # 把这个函数声明成 FastAPI 的生命周期管理器。
async def lifespan(_: FastAPI):  # 定义应用启动和关闭时执行的逻辑。
    ensure_data_directories(settings)  # 在应用启动时确保 data/uploads、data/parsed、data/chunks 已存在。
    yield  # 把控制权交给 FastAPI，应用开始正式运行。


app = FastAPI(  # 创建 FastAPI 应用实例。
    title=settings.app_name,  # 设置 Swagger 页面里显示的应用名称。
    version="0.1.0",  # 设置当前后端版本号。
    description="V1 skeleton for an enterprise-grade RAG system.",  # 设置接口文档描述信息。
    lifespan=lifespan,  # 把上面的生命周期函数注册给应用。
)

app.add_middleware(  # 给应用添加中间件。
    CORSMiddleware,  # 使用 CORS 中间件处理跨域请求。
    allow_origins=settings.cors_origins,  # 允许哪些来源访问接口，来自配置文件。
    allow_credentials=True,  # 允许浏览器在跨域请求里携带凭证。
    allow_methods=["*"],  # 允许所有 HTTP 方法。
    allow_headers=["*"],  # 允许所有请求头。
)

app.include_router(api_router)  # 把总路由挂到应用上，实际业务接口从这里生效。


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_build_error_envelope(status_code=exc.status_code, detail=exc.detail),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # 先沿用 FastAPI 默认的错误明细结构，再补稳定的 error envelope，避免打断现有前端和测试。
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


@app.get("/", tags=["system"])  # 声明根路径接口，通常用于快速探活或查看基础信息。
def root() -> dict[str, str]:  # 定义根接口函数，返回应用的基础元信息。
    return {
        "app": settings.app_name,  # 返回应用名称。
        "version": "0.1.0",  # 返回当前版本号。
        "api_prefix": settings.api_v1_prefix,  # 返回 API 前缀，便于调用方确认路径。
        "docs": "/docs",  # 返回 Swagger 文档地址。
        "demo": "/demo",  # 返回内置前端 demo 页面地址。
    }


@app.get("/demo", include_in_schema=False)  # 提供一个不进 Swagger 的内置前端 demo 页面。
def demo() -> FileResponse:  # 返回内置的 HTML 页面，便于直接验证前端交互效果。
    return FileResponse(DEMO_PAGE)
