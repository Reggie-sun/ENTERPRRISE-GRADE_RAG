import json  # 导入 json，用来读取 chunk 结果文件里的 JSON 内容。
from pathlib import Path  # 导入 Path，方便处理临时目录和文件路径。

from fastapi.testclient import TestClient  # 导入 FastAPI 的测试客户端，用来直接调用接口。
import pytest  # 导入 pytest，方便写参数化测试。

from backend.app.main import app  # 导入应用实例，测试时直接对这个 app 发请求。
from backend.app.core.config import Settings, ensure_data_directories  # 导入配置对象和目录初始化函数。
from backend.app.rag.vectorstores.qdrant_store import QdrantVectorStore  # 导入 Qdrant 存储，验证远程模式客户端参数。
from backend.app.services.document_service import DocumentService, get_document_service  # 导入上传服务和依赖注入函数。
from backend.app.worker.celery_app import INGEST_TASK_NAME, get_celery_app  # 导入 Celery 任务入口，补非 eager worker 回归测试。


def build_test_settings(tmp_path: Path, *, task_always_eager: bool = False) -> Settings:  # 定义一个辅助函数，用来构造测试专用配置。
    data_dir = tmp_path / "data"  # 在 pytest 提供的临时目录下创建 data 根目录路径。
    return Settings(  # 返回一个只用于测试场景的 Settings 配置对象。
        app_name="Enterprise-grade RAG API Test",  # 设置测试环境里的应用名称。
        app_env="test",  # 设置当前运行环境为 test。
        debug=True,  # 打开调试模式，便于测试阶段排查问题。
        qdrant_url=":memory:",  # 让 Qdrant 使用内存模式，避免依赖外部服务。
        qdrant_collection="enterprise_rag_v1_test",  # 设置测试专用的 collection 名称。
        celery_broker_url="memory://",  # Celery broker 使用内存模式，避免依赖真实 Redis。
        celery_result_backend="cache+memory://",  # Celery 结果后端也使用内存模式。
        celery_task_always_eager=task_always_eager,  # 按测试需要决定任务是否在当前进程内直接执行。
        celery_task_eager_propagates=True,  # eager 模式下让异常直接抛出，便于测试定位问题。
        ollama_base_url="http://embedding.test",  # 给 LLM 地址填一个测试占位值。
        embedding_provider="mock",  # embedding 提供方使用 mock，这样测试不需要真实模型服务。
        embedding_base_url="http://embedding.test",  # 给 embedding 地址填一个测试占位值。
        embedding_model="BAAI/bge-m3",  # 保持测试时的 embedding 模型名与项目配置一致。
        data_dir=data_dir,  # 指定 data 根目录。
        upload_dir=data_dir / "uploads",  # 指定上传文件落盘目录。
        parsed_dir=data_dir / "parsed",  # 指定解析文本落盘目录。
        chunk_dir=data_dir / "chunks",  # 指定 chunk 结果落盘目录。
        document_dir=data_dir / "documents",  # 指定 document 元数据目录。
        job_dir=data_dir / "jobs",  # 指定 ingest job 元数据目录。
    )


def test_create_document_returns_queued_job(tmp_path: Path) -> None:  # 测试新文档创建接口会立即返回 queued，并把元数据落盘。
    settings = build_test_settings(tmp_path)  # 先构造当前测试需要的配置。
    ensure_data_directories(settings)  # 根据测试配置创建 uploads / documents / jobs 等目录。
    service = DocumentService(settings)  # 用测试配置创建文档服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 用测试服务覆盖 FastAPI 的默认依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 用 try/finally 确保测试结束后一定清理依赖覆盖。
        response = client.post(  # 对新文档创建接口发起一次请求。
            "/api/v1/documents",  # 指定文档创建接口地址。
            data={  # 通过 multipart form 传入文档元信息。
                "tenant_id": "wl",  # 指定租户 ID。
                "department_ids": ["after_sales", "qa"],  # 指定部门范围。
                "role_ids": ["engineer"],  # 指定角色范围。
                "visibility": "department",  # 指定可见性策略。
                "classification": "internal",  # 指定文档密级。
                "tags": ["manual", "alarm"],  # 指定标签列表。
                "source_system": "dfms",  # 指定来源系统。
                "created_by": "u001",  # 指定上传人。
            },
            files={  # 通过 multipart/form-data 上传原始文件。
                "file": (  # 表单字段名必须和接口定义里的 file 一致。
                    "manual.txt",  # 上传文件名。
                    "Alarm E102 handling guide for after-sales engineers.".encode("utf-8"),  # 模拟上传文件内容。
                    "text/plain",  # 指定 MIME 类型。
                )
            },
        )
    finally:  # 无论请求成功或失败，最后都要清理依赖覆盖。
        app.dependency_overrides.clear()  # 清空依赖覆盖，避免影响其他测试。

    assert response.status_code == 201  # 断言创建成功时接口返回 201。
    payload = response.json()  # 把响应 JSON 转成 Python 字典。
    assert payload["status"] == "queued"  # 断言当前状态为 queued，而不是同步入库完成。
    assert payload["doc_id"].startswith("doc_")  # 断言文档 ID 使用业务前缀。
    assert payload["job_id"].startswith("job_")  # 断言任务 ID 使用业务前缀。

    document_path = settings.document_dir / f"{payload['doc_id']}.json"  # 计算 document 元数据文件路径。
    job_path = settings.job_dir / f"{payload['job_id']}.json"  # 计算 job 元数据文件路径。
    assert document_path.exists()  # 断言 document 元数据已经落盘。
    assert job_path.exists()  # 断言 job 元数据已经落盘。

    document_payload = json.loads(document_path.read_text(encoding="utf-8"))  # 读取 document JSON 内容。
    assert document_payload["tenant_id"] == "wl"  # 断言租户 ID 正确写入。
    assert document_payload["department_ids"] == ["after_sales", "qa"]  # 断言部门范围正确写入。
    assert document_payload["role_ids"] == ["engineer"]  # 断言角色范围正确写入。
    assert document_payload["visibility"] == "department"  # 断言可见性策略正确写入。
    assert document_payload["classification"] == "internal"  # 断言密级正确写入。
    assert document_payload["latest_job_id"] == payload["job_id"]  # 断言文档记录里的 latest_job_id 正确回填。
    assert Path(document_payload["storage_path"]).exists()  # 断言原始文件已经落盘。

    job_payload = json.loads(job_path.read_text(encoding="utf-8"))  # 读取 job JSON 内容。
    assert job_payload["doc_id"] == payload["doc_id"]  # 断言 job 记录关联到了正确的文档。
    assert job_payload["status"] == "queued"  # 断言 job 状态为 queued。
    assert job_payload["stage"] == "queued"  # 断言 job 阶段为 queued。
    assert job_payload["progress"] == 0  # 断言初始进度为 0。

    app.dependency_overrides[get_document_service] = lambda: service  # 再次覆盖依赖，准备调用文档详情接口。
    client = TestClient(app)  # 创建新的测试客户端。
    try:  # 用 try/finally 确保详情接口测试结束后也能清理依赖。
        detail_response = client.get(f"/api/v1/documents/{payload['doc_id']}")  # 调用文档详情接口。
    finally:  # 无论详情接口是否成功，都清理依赖覆盖。
        app.dependency_overrides.clear()  # 清空依赖覆盖。

    assert detail_response.status_code == 200  # 断言详情接口返回 200。
    detail_payload = detail_response.json()  # 解析文档详情响应。
    assert detail_payload["doc_id"] == payload["doc_id"]  # 断言返回的是刚创建的文档。
    assert detail_payload["status"] == "queued"  # 断言文档详情状态仍是 queued。
    assert detail_payload["latest_job_id"] == payload["job_id"]  # 断言文档详情里的 latest_job_id 正确。


def test_create_document_normalizes_blank_metadata_values(tmp_path: Path) -> None:  # 测试队列化上传接口会清洗空白数组项和空白字符串。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(
            "/api/v1/documents",
            data={
                "tenant_id": "  wl  ",  # tenant_id 会被 strip 后再写入。
                "department_ids": ["", " after_sales ", "   "],  # 空白项应该被丢弃。
                "role_ids": ["", "engineer"],  # 空白项应该被丢弃。
                "owner_id": "   ",  # 空白字符串应转成 None。
                "tags": ["", "manual", "   "],  # 空白项应该被丢弃。
                "source_system": "   ",  # 空白字符串应转成 None。
                "created_by": "  reggie  ",  # 非空字符串会被 strip。
            },
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 201  # 清洗后仍应成功创建文档。
    payload = response.json()  # 解析创建响应。
    document_path = settings.document_dir / f"{payload['doc_id']}.json"  # 取到刚写入的 document 元数据文件。
    document_payload = json.loads(document_path.read_text(encoding="utf-8"))  # 读取并解析 document 元数据。

    assert document_payload["tenant_id"] == "wl"  # tenant_id 应被 strip。
    assert document_payload["department_ids"] == ["after_sales"]  # 空白部门值应被丢弃。
    assert document_payload["role_ids"] == ["engineer"]  # 空白角色值应被丢弃。
    assert document_payload["tags"] == ["manual"]  # 空白标签值应被丢弃。
    assert document_payload["owner_id"] is None  # 空白 owner_id 应转成 None。
    assert document_payload["source_system"] is None  # 空白 source_system 应转成 None。
    assert document_payload["created_by"] == "reggie"  # 非空 created_by 应被 strip。


def test_get_ingest_job_status_after_create_document(tmp_path: Path) -> None:  # 测试创建文档后可通过 ingest job 接口查询任务状态。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        create_response = client.post(  # 先创建文档，拿到 job_id。
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
        create_payload = create_response.json()  # 解析创建响应。
        job_response = client.get(f"/api/v1/ingest/jobs/{create_payload['job_id']}")  # 调用 ingest job 状态接口。
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert create_response.status_code == 201  # 创建文档应成功。
    assert job_response.status_code == 200  # 已存在的 job_id 应返回 200。
    job_payload = job_response.json()  # 解析任务状态响应。
    assert job_payload["job_id"] == create_payload["job_id"]  # 断言返回的 job_id 与创建响应一致。
    assert job_payload["doc_id"] == create_payload["doc_id"]  # 断言返回的 doc_id 与创建响应一致。
    assert job_payload["status"] == "queued"  # 初始状态应为 queued。
    assert job_payload["stage"] == "queued"  # 初始阶段应为 queued。
    assert job_payload["progress"] == 0  # 初始进度应为 0。
    assert job_payload["max_retry_limit"] == settings.ingest_failure_retry_limit  # 状态响应应返回当前重试上限配置。
    assert job_payload["auto_retry_eligible"] is False  # queued 状态不应标记为自动重试。
    assert job_payload["manual_retry_allowed"] is True  # queued 状态允许管理端重投递。


def test_run_ingest_job_requeues_job_status(tmp_path: Path) -> None:  # 测试手动触发 run 接口后会把任务重新投递到异步队列。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        create_response = client.post(  # 先创建文档，拿到 doc_id 和 job_id。
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={
                "file": (
                    "manual.txt",
                    (
                        "Alarm E102 handling guide.\n"
                        "Step 1: Check voltage.\n"
                        "Step 2: Reset the device and inspect sensor."
                    ).encode("utf-8"),
                    "text/plain",
                )
            },
        )
        create_payload = create_response.json()  # 解析创建响应。
        run_response = client.post(f"/api/v1/ingest/jobs/{create_payload['job_id']}/run")  # 手动触发任务执行。
        detail_response = client.get(f"/api/v1/documents/{create_payload['doc_id']}")  # 查询文档详情确认状态。
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert create_response.status_code == 201  # 创建文档应成功。
    assert run_response.status_code == 200  # 触发执行接口应成功返回。
    run_payload = run_response.json()  # 解析执行响应。
    assert run_payload["job_id"] == create_payload["job_id"]  # 响应应对应刚创建的 job。
    assert run_payload["status"] == "queued"  # 异步模式下 run 接口应返回已重新入队状态。
    assert run_payload["stage"] == "queued"  # 当前阶段应保持 queued，等待 worker 消费。
    assert run_payload["progress"] == 0  # 重新入队后进度应重置为 0。
    assert run_payload["manual_retry_allowed"] is True  # queued 任务允许再次管理重投递。
    assert run_payload["auto_retry_eligible"] is False  # queued 状态不属于自动重试窗口。
    assert detail_response.status_code == 200  # 文档详情接口应可用。
    assert detail_response.json()["status"] == "queued"  # 文档状态应回到 queued，等待 worker 真正执行。
    assert service.ingestion_service.vector_store.count_points() == 0  # 仅重新入队时不应在当前进程直接写入向量。


def test_run_ingest_job_eager_executes_to_completion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试 eager 模式下 run 接口会真正执行完整入库链路。
    settings = build_test_settings(tmp_path, task_always_eager=True)  # 构造 eager 测试配置，让 Celery 在当前进程直接执行任务。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        with monkeypatch.context() as patch_ctx:  # 先临时屏蔽 create_document 阶段的自动投递，避免创建接口直接跑完整个任务。
            patch_ctx.setattr(
                "backend.app.services.document_service.dispatch_ingest_job",
                lambda *args, **kwargs: None,
            )
            create_response = client.post(
                "/api/v1/documents",
                data={"tenant_id": "wl"},
                files={
                    "file": (
                        "manual.txt",
                        (
                            "Alarm E102 handling guide.\n"
                            "Step 1: Check voltage.\n"
                            "Step 2: Reset the device and inspect sensor."
                        ).encode("utf-8"),
                        "text/plain",
                    )
                },
            )
        create_payload = create_response.json()  # 解析创建响应。
        run_response = client.post(f"/api/v1/ingest/jobs/{create_payload['job_id']}/run")  # 在 eager 模式下重投递，同步拿到执行结果。
        detail_response = client.get(f"/api/v1/documents/{create_payload['doc_id']}")  # 查询文档详情确认状态。
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert create_response.status_code == 201  # 创建文档应成功。
    assert run_response.status_code == 200  # 触发执行接口应成功返回。
    run_payload = run_response.json()  # 解析执行响应。
    assert run_payload["job_id"] == create_payload["job_id"]  # 响应应对应刚创建的 job。
    assert run_payload["status"] == "completed"  # eager 模式下任务应执行完成。
    assert run_payload["stage"] == "completed"  # 最终阶段应是 completed。
    assert run_payload["progress"] == 100  # 完成后进度应为 100。
    assert run_payload["manual_retry_allowed"] is False  # completed 状态不允许再手动重投递。
    assert run_payload["auto_retry_eligible"] is False  # completed 状态不属于自动重试窗口。
    assert detail_response.status_code == 200  # 文档详情接口应可用。
    assert detail_response.json()["status"] == "active"  # 文档状态应更新为 active。
    assert (settings.parsed_dir / f"{create_payload['doc_id']}.txt").exists()  # eager 任务执行后应生成解析文本文件。
    assert (settings.chunk_dir / f"{create_payload['doc_id']}.json").exists()  # eager 任务执行后应生成 chunk 结果文件。


def test_non_eager_worker_consumes_queued_job_to_completion(tmp_path: Path) -> None:  # 测试非 eager 模式下，worker 任务入口可把 queued 任务推进到 completed。
    settings = build_test_settings(tmp_path, task_always_eager=False)  # 显式关闭 eager，模拟真实队列消费模式。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        create_response = client.post(  # 先创建文档和 ingest job。
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={
                "file": (
                    "manual.txt",
                    (
                        "Alarm E102 handling guide.\n"
                        "Step 1: Check voltage.\n"
                        "Step 2: Reset the device and inspect sensor."
                    ).encode("utf-8"),
                    "text/plain",
                )
            },
        )
        create_payload = create_response.json()  # 解析创建响应。

        before_job = client.get(f"/api/v1/ingest/jobs/{create_payload['job_id']}")  # worker 消费前先读取一次任务状态。
        assert before_job.status_code == 200  # 任务状态接口应可用。
        assert before_job.json()["status"] == "queued"  # 非 eager 场景下创建后应保持 queued。
        assert service.ingestion_service.vector_store.count_points() == 0  # 仅创建任务时不应直接写入向量库。

        celery_app = get_celery_app(settings)  # 取到当前测试配置对应的 Celery app。
        task_result = celery_app.tasks[INGEST_TASK_NAME].apply(args=[create_payload["job_id"]], throw=True)  # 直接调用任务入口，模拟 worker 消费。
        task_payload = task_result.result  # 读取任务执行返回结果。

        detail_response = client.get(f"/api/v1/documents/{create_payload['doc_id']}")  # 查询文档详情确认状态推进。
        job_response = client.get(f"/api/v1/ingest/jobs/{create_payload['job_id']}")  # 查询任务详情确认完成状态。
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert create_response.status_code == 201  # 创建文档应成功。
    assert task_payload["status"] == "completed"  # worker 消费后任务应完成。
    assert task_payload["stage"] == "completed"  # 最终阶段应为 completed。
    assert task_payload["progress"] == 100  # 完成后进度应为 100。
    assert detail_response.status_code == 200  # 文档详情接口应可用。
    assert detail_response.json()["status"] == "active"  # 文档应切到 active，可参与检索。
    assert job_response.status_code == 200  # job 状态接口应可用。
    assert job_response.json()["status"] == "completed"  # job 终态应为 completed。
    assert job_response.json()["manual_retry_allowed"] is False  # completed 任务不允许再手动重投递。
    assert (settings.parsed_dir / f"{create_payload['doc_id']}.txt").exists()  # 非 eager worker 消费后应生成解析文件。
    assert (settings.chunk_dir / f"{create_payload['doc_id']}.json").exists()  # 非 eager worker 消费后应生成 chunk 文件。


def test_non_eager_worker_moves_job_to_dead_letter_on_runtime_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试非 eager 模式下 worker 运行异常会进入 dead_letter。
    settings = build_test_settings(tmp_path, task_always_eager=False).model_copy(update={"ingest_failure_retry_limit": 1})  # 失败上限设为 1，首错即 dead_letter。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    def raise_runtime_error(self: object, *args: object, **kwargs: object) -> object:  # 构造全局失败桩，模拟 worker 执行依赖故障。
        raise RuntimeError("worker runtime error")

    monkeypatch.setattr(  # 给 DocumentIngestionService 打桩，确保 worker 新建服务实例也会命中该失败逻辑。
        "backend.app.services.ingestion_service.DocumentIngestionService.ingest_document",
        raise_runtime_error,
    )

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        create_response = client.post(  # 先创建文档和 ingest job。
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
        create_payload = create_response.json()  # 解析创建响应。

        celery_app = get_celery_app(settings)  # 取到当前测试配置对应的 Celery app。
        task_result = celery_app.tasks[INGEST_TASK_NAME].apply(args=[create_payload["job_id"]], throw=True)  # 调用 worker 任务入口，触发失败路径。
        task_payload = task_result.result  # 读取任务执行返回结果。

        detail_response = client.get(f"/api/v1/documents/{create_payload['doc_id']}")  # 查询文档状态。
        job_response = client.get(f"/api/v1/ingest/jobs/{create_payload['job_id']}")  # 查询任务状态。
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert create_response.status_code == 201  # 创建文档应成功。
    assert task_payload["status"] == "dead_letter"  # 失败达到上限后应进入 dead_letter。
    assert task_payload["stage"] == "dead_letter"  # 阶段应同步为 dead_letter。
    assert task_payload["retry_count"] == 1  # 首次失败即达到上限时重试计数应为 1。
    assert task_payload["error_code"] == "INGEST_RUNTIME_ERROR_DEAD_LETTER"  # 错误码应带 dead_letter 后缀。
    assert detail_response.status_code == 200  # 文档详情接口应可用。
    assert detail_response.json()["status"] == "failed"  # 文档状态应保持 failed，避免误判可检索。
    assert job_response.status_code == 200  # job 状态接口应可用。
    assert job_response.json()["status"] == "dead_letter"  # job 状态应落到 dead_letter。
    assert job_response.json()["auto_retry_eligible"] is False  # dead_letter 不应继续自动重试。
    assert job_response.json()["manual_retry_allowed"] is True  # dead_letter 允许管理端手动重投递。


def test_run_ingest_job_moves_to_dead_letter_after_retry_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试失败重试达到上限后任务会进入 dead_letter。
    settings = build_test_settings(tmp_path).model_copy(update={"ingest_failure_retry_limit": 2})  # 把失败上限收紧到 2，便于测试死信逻辑。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    def raise_runtime_error(*args: object, **kwargs: object) -> None:  # 构造固定失败函数，模拟运行期依赖故障。
        raise RuntimeError("qdrant down")

    try:  # 确保测试结束后清理依赖覆盖。
        with monkeypatch.context() as patch_ctx:  # 屏蔽创建接口内的自动投递，避免测试依赖真实 worker。
            patch_ctx.setattr(
                "backend.app.services.document_service.dispatch_ingest_job",
                lambda *args, **kwargs: None,
            )
            create_response = client.post(
                "/api/v1/documents",
                data={"tenant_id": "wl"},
                files={"file": ("manual.txt", b"valid-content", "text/plain")},
            )
        create_payload = create_response.json()  # 解析创建响应。
        monkeypatch.setattr(service.ingestion_service, "ingest_document", raise_runtime_error)  # 让入库执行固定抛错。

        first_attempt = service.run_ingest_job(create_payload["job_id"])  # 第一次失败，状态应是 failed。
        second_attempt = service.run_ingest_job(create_payload["job_id"])  # 第二次失败触达上限，状态应进 dead_letter。
        third_attempt = service.run_ingest_job(create_payload["job_id"])  # dead_letter 后再执行应直接返回，不再累加重试。
        detail_response = client.get(f"/api/v1/documents/{create_payload['doc_id']}")  # 查询文档状态确认同步失败。
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert create_response.status_code == 201  # 创建文档应成功。
    assert first_attempt.status == "failed"  # 第一次失败仍允许重试。
    assert first_attempt.retry_count == 1  # 第一次失败后重试次数应为 1。
    assert first_attempt.auto_retry_eligible is True  # 未达到上限前 failed 应允许自动重试。
    assert first_attempt.manual_retry_allowed is True  # failed 状态允许管理重投递。
    assert second_attempt.status == "dead_letter"  # 达到失败上限后应进入死信状态。
    assert second_attempt.stage == "dead_letter"  # 阶段也应同步为 dead_letter。
    assert second_attempt.retry_count == 2  # 死信时重试次数应达到设定上限。
    assert second_attempt.error_code == "INGEST_RUNTIME_ERROR_DEAD_LETTER"  # 死信应写入带后缀的错误码。
    assert second_attempt.auto_retry_eligible is False  # dead_letter 状态不应继续自动重试。
    assert second_attempt.manual_retry_allowed is True  # dead_letter 状态允许人工确认后重投递。
    assert third_attempt.status == "dead_letter"  # 再次执行死信任务应保持终态。
    assert third_attempt.retry_count == 2  # 死信终态下重试次数不应继续增加。
    assert detail_response.status_code == 200  # 文档详情接口应可用。
    assert detail_response.json()["status"] == "failed"  # 死信任务对应文档应保持 failed，避免误判可检索。


def test_queue_ingest_job_requeues_dead_letter_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试 dead_letter 任务仍可通过 run 接口作为管理重试入口重新入队。
    settings = build_test_settings(tmp_path).model_copy(update={"ingest_failure_retry_limit": 1})  # 把失败上限设为 1，快速进入 dead_letter。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    def raise_runtime_error(*args: object, **kwargs: object) -> None:  # 构造固定失败函数，模拟运行期依赖故障。
        raise RuntimeError("embedding timeout")

    try:  # 确保测试结束后清理依赖覆盖。
        with monkeypatch.context() as patch_ctx:  # 创建阶段先屏蔽自动投递，避免异步干扰。
            patch_ctx.setattr(
                "backend.app.services.document_service.dispatch_ingest_job",
                lambda *args, **kwargs: None,
            )
            create_response = client.post(
                "/api/v1/documents",
                data={"tenant_id": "wl"},
                files={"file": ("manual.txt", b"valid-content", "text/plain")},
            )
        create_payload = create_response.json()  # 解析创建响应。
        monkeypatch.setattr(service.ingestion_service, "ingest_document", raise_runtime_error)  # 强制入库失败。
        dead_letter_status = service.run_ingest_job(create_payload["job_id"])  # 一次失败后直接进 dead_letter。

        monkeypatch.setattr(  # 重新入队阶段改成成功投递，验证管理重试语义。
            "backend.app.services.document_service.dispatch_ingest_job",
            lambda *args, **kwargs: None,
        )
        requeued_status = service.queue_ingest_job(create_payload["job_id"])  # 通过管理接口重置为 queued。
        detail_response = client.get(f"/api/v1/documents/{create_payload['doc_id']}")  # 查询文档状态确认同步回 queued。
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert create_response.status_code == 201  # 创建文档应成功。
    assert dead_letter_status.status == "dead_letter"  # 任务应先进入 dead_letter。
    assert requeued_status.status == "queued"  # 管理重试后任务应回到 queued。
    assert requeued_status.stage == "queued"  # 阶段应同步重置为 queued。
    assert requeued_status.progress == 0  # 重新入队后进度应回到 0。
    assert requeued_status.retry_count == dead_letter_status.retry_count  # 重新入队不应重置历史重试计数。
    assert requeued_status.auto_retry_eligible is False  # queued 状态下自动重试判定应为 false。
    assert requeued_status.manual_retry_allowed is True  # queued 状态下允许管理重试。
    assert detail_response.status_code == 200  # 文档详情接口应可用。
    assert detail_response.json()["status"] == "queued"  # 文档状态应同步回 queued，等待下次 worker 消费。


def test_create_document_returns_502_when_dispatch_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试 broker 不可用时接口会返回 502 而不是假装 queued。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    monkeypatch.setattr(  # 把 Celery 投递函数替换成抛错版本，模拟 broker 不可用。
        "backend.app.services.document_service.dispatch_ingest_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("broker is down")),
    )

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 502  # Celery broker 不可用时应返回 502。
    assert "Failed to enqueue ingest job" in response.json()["detail"]  # 错误信息应明确指出是调度失败。

    job_files = sorted(settings.job_dir.glob("*.json"))  # 读取当前目录里唯一的 job 元数据文件。
    document_files = sorted(settings.document_dir.glob("*.json"))  # 读取当前目录里唯一的 document 元数据文件。
    assert len(job_files) == 1  # 当前测试只应生成一个 job 记录。
    assert len(document_files) == 1  # 当前测试只应生成一个 document 记录。

    job_payload = json.loads(job_files[0].read_text(encoding="utf-8"))  # 解析 job 元数据。
    document_payload = json.loads(document_files[0].read_text(encoding="utf-8"))  # 解析 document 元数据。
    assert job_payload["status"] == "failed"  # 调度失败后 job 状态应标为 failed。
    assert job_payload["error_code"] == "INGEST_DISPATCH_ERROR"  # 应写入明确的调度失败错误码。
    assert document_payload["status"] == "failed"  # 文档状态也应同步标记为 failed。


def test_create_document_dispatch_failure_moves_to_dead_letter_when_retry_limit_is_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试调度失败在上限为 1 时会直接进入 dead_letter。
    settings = build_test_settings(tmp_path).model_copy(update={"ingest_failure_retry_limit": 1})  # 把失败上限设为 1，覆盖死信边界。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    monkeypatch.setattr(  # 模拟 Celery 投递失败。
        "backend.app.services.document_service.dispatch_ingest_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("broker is down")),
    )

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 502  # 调度失败依旧返回 502。

    job_files = sorted(settings.job_dir.glob("*.json"))  # 读取任务元数据文件。
    document_files = sorted(settings.document_dir.glob("*.json"))  # 读取文档元数据文件。
    assert len(job_files) == 1  # 当前测试只应生成一个 job 记录。
    assert len(document_files) == 1  # 当前测试只应生成一个 document 记录。

    job_payload = json.loads(job_files[0].read_text(encoding="utf-8"))  # 解析 job 元数据。
    document_payload = json.loads(document_files[0].read_text(encoding="utf-8"))  # 解析 document 元数据。
    assert job_payload["status"] == "dead_letter"  # 达到失败上限后应进入 dead_letter。
    assert job_payload["stage"] == "dead_letter"  # 阶段也应同步为 dead_letter。
    assert job_payload["retry_count"] == 1  # 死信时重试计数应等于上限。
    assert job_payload["error_code"] == "INGEST_DISPATCH_ERROR_DEAD_LETTER"  # 调度失败死信应使用统一错误码。
    assert "moved to dead_letter" in (job_payload["error_message"] or "")  # 错误信息应明确标记进入死信。
    assert document_payload["status"] == "failed"  # 文档状态应保持 failed，避免误判可检索。


def test_remote_qdrant_client_ignores_proxy_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 测试远程 Qdrant 客户端会禁用系统代理。
    settings = build_test_settings(tmp_path).model_copy(update={"qdrant_url": "http://localhost:6333"})  # 使用远程 URL 模式触发对应客户端分支。
    captured_kwargs: dict[str, object] = {}  # 保存构造函数收到的关键字参数，后面用于断言。

    def fake_qdrant_client(*args: object, **kwargs: object) -> object:  # 构造一个假的 QdrantClient，避免测试真的连外部服务。
        captured_kwargs.update(kwargs)  # 记录调用参数。

        class DummyClient:  # 只需要一个占位对象供 store.client 返回。
            pass

        return DummyClient()

    QdrantVectorStore._CLIENT_CACHE.clear()  # 清空类级缓存，避免拿到之前构造过的真实客户端。
    monkeypatch.setattr("backend.app.rag.vectorstores.qdrant_store.QdrantClient", fake_qdrant_client)  # 把 QdrantClient 替换成测试桩。

    store = QdrantVectorStore(settings)  # 创建待测向量存储实例。
    _ = store.client  # 触发客户端构造。

    assert captured_kwargs["url"] == "http://localhost:6333"  # 远程模式应把 URL 原样传给客户端。
    assert captured_kwargs["trust_env"] is False  # 必须禁用系统代理，避免本机代理污染内网互调。


def test_upload_document_runs_ingestion_pipeline(tmp_path: Path) -> None:  # 测试上传接口能否完整跑通入库链路。
    settings = build_test_settings(tmp_path)  # 先构造当前测试需要的配置。
    ensure_data_directories(settings)  # 根据测试配置创建 uploads / parsed / chunks 等目录。
    service = DocumentService(settings)  # 用测试配置创建上传服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 用测试服务覆盖 FastAPI 的默认依赖注入。
    client = TestClient(app)  # 创建测试客户端，后续直接像调 HTTP 接口一样发请求。

    try:  # 用 try/finally 确保依赖覆盖在测试结束后一定会被清理掉。
        response = client.post(  # 向上传接口发送一个 POST 请求。
            "/api/v1/documents/upload",  # 指定上传接口的 URL。
            files={  # 通过 multipart/form-data 的方式上传文件。
                "file": (  # 表单字段名必须和接口定义里的 file 一致。
                    "manual.txt",  # 上传文件名。
                    (  # 下面这个括号包起来的是上传文件的二进制内容。
                        "RAG can help engineers search maintenance manuals quickly.\n\n"  # 第一段文本，用来模拟知识库文档内容。
                        "This document explains alarm handling steps, safety notes, and repair guides."  # 第二段文本，继续补充测试内容。
                    ).encode("utf-8"),  # 把字符串编码成 utf-8 字节流，模拟真实文件上传。
                    "text/plain",  # 指定当前上传文件的 MIME 类型。
                )  # 结束 file 这个 multipart 文件元组。
            },  # 结束 files 参数字典。
        )  # 完成这次 POST 调用，并拿到响应对象。
    finally:  # 无论上面的请求成功还是失败，都会执行这里的清理。
        app.dependency_overrides.clear()  # 清空依赖覆盖，避免影响别的测试。

    assert response.status_code == 201  # 断言上传成功时接口返回 201 Created。
    payload = response.json()  # 把响应 JSON 解析成 Python 字典，方便后续断言。
    assert payload["status"] == "ingested"  # 断言接口返回状态是 ingested，表示已经完成入库。
    assert payload["parse_supported"] is True  # 断言当前上传类型是系统支持解析的。
    assert payload["chunk_count"] >= 1  # 断言至少生成了 1 个 chunk。
    assert payload["vector_count"] == payload["chunk_count"]  # 断言写入的向量数和 chunk 数保持一致。
    assert Path(payload["storage_path"]).exists()  # 断言原始上传文件已经实际落盘。
    assert Path(payload["parsed_path"]).exists()  # 断言解析后的纯文本文件已经生成。
    assert Path(payload["chunk_path"]).exists()  # 断言 chunk 结果文件已经生成。
    assert service.ingestion_service.vector_store.count_points() == payload["vector_count"]  # 断言 Qdrant 里的点数量和返回的向量数量一致。

    chunk_payload = json.loads(Path(payload["chunk_path"]).read_text(encoding="utf-8"))  # 读取 chunk 文件并解析成 Python 对象。
    assert len(chunk_payload) == payload["chunk_count"]  # 断言 chunk 文件里的条目数量和接口返回一致。
    assert chunk_payload[0]["document_id"] == payload["document_id"]  # 断言第一个 chunk 里的 document_id 和上传响应一致。


def test_upload_rejects_unsupported_extension(tmp_path: Path) -> None:  # 测试系统会拒绝不支持的文件扩展名。
    settings = build_test_settings(tmp_path)  # 构造这次测试用到的配置。
    ensure_data_directories(settings)  # 提前创建测试需要的目录结构。
    service = DocumentService(settings)  # 用测试配置创建上传服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖默认依赖，让接口走测试服务。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 用 try/finally 确保测试结束后能恢复依赖状态。
        response = client.post(  # 对上传接口发起一次上传请求。
            "/api/v1/documents/upload",  # 指定上传接口地址。
            files={"file": ("manual.docx", b"fake-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},  # 上传一个当前系统不支持解析的 docx 文件。
        )  # 完成接口调用。
    finally:  # 不管接口是否报错，都执行清理逻辑。
        app.dependency_overrides.clear()  # 清空依赖覆盖，避免污染其他测试。

    assert response.status_code == 400  # 断言不支持的扩展名会返回 400 Bad Request。
    assert "Unsupported file type" in response.json()["detail"]  # 断言错误信息里明确说明了文件类型不被支持。


def test_create_document_rejects_unsupported_extension(tmp_path: Path) -> None:  # 测试队列化上传接口会拒绝不支持的扩展名。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(  # 调用队列化上传接口。
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={
                "file": (
                    "manual.docx",
                    b"fake-docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 400  # 不支持的扩展名应返回 400。
    assert "Unsupported file type" in response.json()["detail"]  # 错误信息应明确指出文件类型不支持。


def test_create_document_rejects_empty_file(tmp_path: Path) -> None:  # 测试队列化上传接口会拒绝空文件。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(  # 调用队列化上传接口。
            "/api/v1/documents",
            data={"tenant_id": "wl"},
            files={"file": ("manual.txt", b"", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 400  # 空文件应返回 400。
    assert response.json()["detail"] == "Uploaded file is empty."  # 错误信息应明确指出文件为空。


def test_create_document_requires_tenant_id(tmp_path: Path) -> None:  # 测试队列化上传接口缺少 tenant_id 时会返回 422。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(  # 调用队列化上传接口，但故意不传 tenant_id。
            "/api/v1/documents",
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 422  # 缺少必填字段应返回 422。
    assert any(error["loc"][-1] == "tenant_id" for error in response.json()["detail"])  # 返回的校验错误里应包含 tenant_id。


@pytest.mark.parametrize(  # 参数化测试非法枚举值，避免写两份重复逻辑。
    ("field_name", "field_value"),
    [
        ("visibility", "restricted"),
        ("classification", "top_secret"),
    ],
)
def test_create_document_rejects_invalid_enum_value(tmp_path: Path, field_name: str, field_value: str) -> None:  # 测试非法 ACL/密级值会被接口校验拒绝。
    settings = build_test_settings(tmp_path)  # 构造测试配置。
    ensure_data_directories(settings)  # 创建测试目录。
    service = DocumentService(settings)  # 创建测试服务实例。

    app.dependency_overrides[get_document_service] = lambda: service  # 覆盖依赖注入。
    client = TestClient(app)  # 创建测试客户端。

    try:  # 确保测试结束后清理依赖覆盖。
        response = client.post(  # 调用队列化上传接口，并传入非法枚举值。
            "/api/v1/documents",
            data={
                "tenant_id": "wl",
                field_name: field_value,
            },
            files={"file": ("manual.txt", b"valid-content", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()  # 清理依赖覆盖。

    assert response.status_code == 422  # 非法枚举值应返回 422。
    assert any(error["loc"][-1] == field_name for error in response.json()["detail"])  # 校验错误里应指向对应字段。
