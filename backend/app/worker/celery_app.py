from typing import Any  # 导入任意类型，用于任务返回值的类型标注。

from celery import Celery  # 导入 Celery 框架，用于异步任务队列。
from celery.app.task import Task  # 导入 Task 类型，用于绑定任务实例。

from ..core.config import Settings, get_settings  # 导入配置对象和配置获取函数。

INGEST_TASK_NAME = "ingest.run_job"  # 统一的 ingest task 名称，API 和 worker 都通过它路由任务。

_CELERY_APP_CACHE: dict[str, Celery] = {}  # 按配置缓存 Celery app，避免每次投递都重复建 app。


def _celery_cache_key(settings: Settings) -> str:  # 计算 Celery app 的缓存 key。
    return settings.model_dump_json()  # 直接按完整配置做缓存键，确保不同测试配置互不污染。


def _register_tasks(celery_app: Celery, settings: Settings) -> None:  # 给当前 Celery app 注册任务。
    celery_app.tasks.pop(INGEST_TASK_NAME, None)  # 强制移除已有同名任务，避免默认 app 的闭包污染测试或多配置实例。
    max_retries = max(0, settings.ingest_failure_retry_limit - 1)  # Celery 重试次数不含首次执行，因此减 1。

    @celery_app.task(name=INGEST_TASK_NAME, bind=True, max_retries=max_retries)  # 注册 ingest 执行任务，worker 消费后走统一服务逻辑。
    def run_ingest_job_task(self: Task, job_id: str) -> dict[str, Any]:  # 异步执行 ingest job 的任务函数。
        from ..services.document_service import DocumentService  # 延迟导入，避免模块加载时出现循环依赖。

        service = DocumentService(settings)  # 使用当前 Celery app 对应的配置创建服务实例。
        result = service.run_ingest_job(job_id)  # 执行既有的 ingest job 流程。
        should_retry = (  # eager 模式下不触发 Celery retry，避免测试环境抛 Retry 异常干扰接口行为。
            not settings.celery_task_always_eager  # 非 eager 模式才允许重试。
            and result.status == "failed"  # 仅失败状态才重试。
            and self.request.retries < max_retries  # 未达到重试上限才允许继续。
        )
        if should_retry:  # 仅在可重试失败时触发 Celery 自动重试。
            raise self.retry(  # 通过 Celery 的 retry 机制重新入队，避免业务层手工循环投递。
                exc=RuntimeError(result.error_message or f"Ingest job failed: {job_id}"),  # 构造重试异常。
                countdown=settings.ingest_retry_delay_seconds,  # 设置重试间隔秒数。
            )
        return result.model_dump(mode="json")  # 返回标准 JSON 结果，便于调试 eager 模式。


def build_celery_app(settings: Settings | None = None) -> Celery:  # 构造一个 Celery app 实例。
    resolved_settings = settings or get_settings()  # 优先使用传入配置，否则退回全局配置。
    celery_app = Celery("enterprise_rag")  # 创建 Celery app，指定应用名称。
    celery_app.conf.update(  # 把 broker、backend 和序列化配置写进 Celery。
        broker_url=resolved_settings.celery_broker_url,  # 消息队列 broker 地址。
        result_backend=resolved_settings.celery_result_backend,  # 任务结果存储后端地址。
        task_default_queue=resolved_settings.celery_ingest_queue,  # 默认任务队列名称。
        task_serializer="json",  # 任务序列化格式使用 JSON。
        accept_content=["json"],  # 只接受 JSON 格式的消息内容。
        result_serializer="json",  # 结果序列化格式使用 JSON。
        task_track_started=True,  # 开启任务开始状态追踪。
        task_always_eager=resolved_settings.celery_task_always_eager,  # eager 模式下任务在当前进程直接执行。
        task_eager_propagates=resolved_settings.celery_task_eager_propagates,  # eager 模式下异常直接抛出。
        timezone="UTC",  # 时区设置为 UTC。
        enable_utc=True,  # 启用 UTC 时间。
    )
    _register_tasks(celery_app, resolved_settings)  # 注册当前 app 需要的 ingest 任务。
    return celery_app  # 返回配置完成后的 Celery app。


def get_celery_app(settings: Settings | None = None) -> Celery:  # 按配置获取可复用的 Celery app。
    resolved_settings = settings or get_settings()  # 先统一解析配置。
    cache_key = _celery_cache_key(resolved_settings)  # 计算缓存键。
    celery_app = _CELERY_APP_CACHE.get(cache_key)  # 先尝试从缓存读取。
    if celery_app is None:  # 缓存不存在时再构造。
        celery_app = build_celery_app(resolved_settings)  # 构造新的 Celery app。
        _CELERY_APP_CACHE[cache_key] = celery_app  # 写入缓存。
    return celery_app  # 返回 Celery app。


def dispatch_ingest_job(job_id: str, settings: Settings | None = None) -> Any:  # 投递 ingest job 到 Celery 队列。
    resolved_settings = settings or get_settings()  # 统一解析配置。
    celery_app = get_celery_app(resolved_settings)  # 获取和当前配置对应的 Celery app。
    task = celery_app.tasks[INGEST_TASK_NAME]  # 取出已经注册好的 ingest 任务。
    return task.apply_async(  # 按当前配置投递任务；eager 模式下会在当前进程直接执行。
        args=[job_id],  # 传入任务参数 job_id。
        queue=resolved_settings.celery_ingest_queue,  # 指定目标队列。
        ignore_result=False,  # 不忽略结果，需要拿到任务执行状态。
    )


celery_app = get_celery_app()  # 导出默认 Celery app，供 worker 进程直接加载。
