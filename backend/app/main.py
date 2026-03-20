from contextlib import asynccontextmanager  # 导入异步上下文管理器，用来注册应用启动和关闭逻辑。
from pathlib import Path  # 导入 Path，用于定位 demo 页面文件。

from fastapi import FastAPI  # 导入 FastAPI 主应用类。
from fastapi.responses import FileResponse  # 导入文件响应，用于返回内置 demo 页面。
from fastapi.middleware.cors import CORSMiddleware  # 导入 CORS 中间件，允许前端跨域访问接口。

from .api.router import api_router  # 导入项目总路由，后面统一挂到 app 上。
from .core.config import ensure_data_directories, get_settings  # 导入配置读取和数据目录初始化函数。

settings = get_settings()  # 读取当前项目配置，后续创建应用和中间件时直接复用。
DEMO_PAGE = Path(__file__).resolve().parent / "web" / "demo.html"  # 内置前端 demo 的静态页面路径。


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
