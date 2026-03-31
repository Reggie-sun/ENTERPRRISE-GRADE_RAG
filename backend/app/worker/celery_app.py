"""Celery 异步任务配置与文档摄取任务定义。

负责创建和缓存 Celery 应用实例、注册 ingest 文档摄取任务，
以及提供任务投递入口供上层 DocumentService 调用。
"""
from typing import Any

from celery import Celery
from celery.app.task import Task

from ..core.config import Settings, get_settings

INGEST_TASK_NAME = "ingest.run_job"  # 摄取任务的唯一名称标识

_CELERY_APP_CACHE: dict[str, Celery] = {}  # 按序列化配置缓存的 Celery 实例字典，避免重复创建


def _celery_cache_key(settings: Settings) -> str:
    """根据 Settings 生成缓存键，确保配置变更时使用不同的 Celery 实例。"""
    return settings.model_dump_json()


def _register_tasks(celery_app: Celery, settings: Settings) -> None:
    """向 Celery 应用注册摄取任务，包含失败自动重试逻辑。

    先移除可能残留的同名旧任务，再根据配置的最大重试次数注册新任务。
    在 eager（同步测试）模式下不触发 Celery retry，避免测试环境抛异常。
    """
    celery_app.tasks.pop(INGEST_TASK_NAME, None)  # 移除已有同名任务，避免默认 app 闭包污染测试
    max_retries = max(0, settings.ingest_failure_retry_limit - 1)

    @celery_app.task(name=INGEST_TASK_NAME, bind=True, max_retries=max_retries)
    def run_ingest_job_task(self: Task, job_id: str) -> dict[str, Any]:
        """执行单个文档摄取任务：实例化 DocumentService 并调用 run_ingest_job。

        任务失败且未超过最大重试次数时，通过 self.retry 触发延时重试；
        eager 模式下跳过重试以保持测试稳定性。
        """
        from ..services.document_service import DocumentService

        service = DocumentService(settings)
        result = service.run_ingest_job(job_id)
        # eager 模式下不触发 Celery retry，避免测试环境抛 Retry 异常
        should_retry = (
            not settings.celery_task_always_eager
            and result.status == "failed"
            and self.request.retries < max_retries
        )
        if should_retry:
            raise self.retry(
                exc=RuntimeError(result.error_message or f"Ingest job failed: {job_id}"),
                countdown=settings.ingest_retry_delay_seconds,
            )
        return result.model_dump(mode="json")


def build_celery_app(settings: Settings | None = None) -> Celery:
    """根据配置构建一个新的 Celery 应用实例，注册任务并返回。

    包含 broker、序列化方式、队列名、时区等核心配置项。
    每次调用都会创建全新实例，一般通过 get_celery_app 使用缓存版本。
    """
    resolved_settings = settings or get_settings()
    celery_app = Celery("enterprise_rag")
    celery_app.conf.update(
        broker_url=resolved_settings.celery_broker_url,
        result_backend=resolved_settings.celery_result_backend,
        task_default_queue=resolved_settings.celery_ingest_queue,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_track_started=True,
        task_always_eager=resolved_settings.celery_task_always_eager,
        task_eager_propagates=resolved_settings.celery_task_eager_propagates,
        timezone="UTC",
        enable_utc=True,
    )
    _register_tasks(celery_app, resolved_settings)
    return celery_app


def get_celery_app(settings: Settings | None = None) -> Celery:
    """获取（或创建并缓存）Celery 应用实例。

    以序列化的 Settings 为缓存键，同一配置下复用同一个 Celery 实例，
    避免重复注册任务和连接。
    """
    resolved_settings = settings or get_settings()
    cache_key = _celery_cache_key(resolved_settings)
    celery_app = _CELERY_APP_CACHE.get(cache_key)
    if celery_app is None:
        celery_app = build_celery_app(resolved_settings)
        _CELERY_APP_CACHE[cache_key] = celery_app
    return celery_app


def dispatch_ingest_job(job_id: str, settings: Settings | None = None) -> Any:
    """将摄取任务异步投递到 Celery 队列。

    获取（或创建）Celery 实例后，通过 apply_async 发送任务消息，
    由 Worker 进程异步执行实际的文档摄取流程。
    """
    resolved_settings = settings or get_settings()
    celery_app = get_celery_app(resolved_settings)
    task = celery_app.tasks[INGEST_TASK_NAME]
    return task.apply_async(
        args=[job_id],
        queue=resolved_settings.celery_ingest_queue,
        ignore_result=False,
    )


celery_app = get_celery_app()  # 模块级单例：在 import 时即初始化 Celery 实例
