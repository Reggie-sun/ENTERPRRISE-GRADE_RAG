# V1 Plan

## 0. 当前状态

按当前冻结范围，V1 已满足验收标准，可以进入版本冻结。

当前验收依据：

- `POST /api/v1/documents` 已通过真实 Swagger MCP 上传测试
- `GET /api/v1/ingest/jobs/{job_id}` 已返回真实 job 状态与重试语义字段
- `POST /api/v1/ingest/jobs/{job_id}/run` 已完成真实接口测试
- 本地测试通过：`pytest -q -> 24 passed`

这里的“完成”指的是：**V1 最小闭环已经完成**，不是说企业级全部能力都做完了。

## 1. 项目目标

本项目的 V1 目标不是一次性做完整企业级 RAG 平台，而是先做出一个**单机可运行、接口可联调、链路可验证**的企业知识库问答后端。

V1 的核心目标只聚焦这条最小闭环：

- 文档上传
- 文档解析
- chunk 切分
- embedding 生成
- 向量入库
- 检索
- rerank
- 问答生成
- 返回引用

一句话：V1 先证明“从文档到答案”的后端链路已经跑通，再进入企业化增强阶段。

---

## 2. V1 范围冻结

当前 V1 只保留最小可交付范围，不继续扩张。

### 2.1 文档支持范围

V1 只支持下面几类文档：

- PDF
- Markdown
- `*.markdown`
- TXT

`Word / Excel / PPT / CAD / 扫描件 OCR` 不算当前 V1 必做范围。

### 2.2 入库链路范围

V1 入库保留两条路径：

- 同步验证链路：`POST /api/v1/documents/upload`
  用于本地开发和快速验证 parse -> chunk -> embedding -> Qdrant 是否跑通
- 异步入库链路：`POST /api/v1/documents` + `GET /api/v1/ingest/jobs/{job_id}`
  用于真实验证 `enqueue -> worker consume -> 状态流转`

当前代码阶段，异步链路已经有：

- 创建文档记录
- 创建 ingest job
- Celery 投递
- worker 消费
- 查询 job 状态
- 失败达到上限后进入 `dead_letter`
- 可配置自动重试参数：`ingest_failure_retry_limit` / `ingest_retry_delay_seconds`
- job 状态响应包含重试语义字段：`max_retry_limit` / `auto_retry_eligible` / `manual_retry_allowed`
- 手动重投递：`POST /api/v1/ingest/jobs/{job_id}/run`

这说明 V1 现在已经不是“只有异步接口骨架”，而是具备了**真实异步执行能力**。

### 2.3 检索与问答范围

V1 当前要求的是：

- 基于 Qdrant 的向量检索 top-k
- rerank
- 生成回答
- 返回 citations

这里的目标是**真实返回可检索内容和引用**，不是先追求复杂混合检索、复杂拒答和多模型编排。

---

## 3. 当前 V1 基线

结合当前代码，V1 已经完成或基本完成的内容如下：

- 文档上传接口
- 文档元数据落盘
- ingest job 元数据落盘
- 文档详情和 job 状态查询
- 手动执行 ingest job
- `dead_letter` 终态与重试上限控制
- job 状态响应重试语义字段（可直接给管理端 UI 用）
- 非 eager worker 回归测试（覆盖 `queued -> completed` 与 `queued -> dead_letter`）
- worker 运行手册（`backend/WORKER_RUNBOOK.md`）
- ingest 状态机与错误码文档（`backend/INGEST_STATE_MACHINE.md`）
- 文档解析与切块
- embedding 生成
- Qdrant 入库
- Qdrant 检索
- rerank 接口级链路
- chat 问答链路
- citations 返回
- 基础测试覆盖

也就是说，V1 已经不是“只有空架子”，而是已经进入**从最小闭环走向可用化**的阶段。

---

## 4. V1 还需要补的内容

如果按“当前真实 V1”收口，接下来优先级应当是：

1. 再决定是否进入 BM25、ACL 过滤和 OCR

这里要明确：**异步执行已经接上，下一步最合理的是把这条链路稳定下来，而不是继续扩 V1 功能面。**

---

## 5. V1 暂时不做

为了保证项目收敛，以下内容不算当前 V1 交付门槛：

- 完整多租户权限过滤
- 在线 ACL 检索过滤
- BM25 混合检索
- RRF 融合
- OCR
- 复杂 Office 深度解析
- PaddleOCR / PP-Structure
- 自动评估平台
- 高并发优化
- 精细化后台管理
- 多模态
- 语音输入
- 分布式调度

注意，这里说的是“当前 V1 不作为交付门槛”，不是说以后不做。

---

## 6. 技术栈冻结

为了避免技术路线反复切换，当前 V1 文档应和代码现实保持一致：

- 后端：FastAPI
- 向量库：Qdrant
- 队列：Celery + Redis
- Embedding：BGE-M3
- Rerank：当前先保证链路可用，生产目标仍是 `bge-reranker-v2-m3`
- LLM：当前开发链路允许 `mock / Ollama-compatible`，生产目标再切 `vLLM`
- 文档解析：PDF / Markdown / TXT
- 部署方式：本地开发 `conda + docker compose`，生产再收敛容器化

这一步的重点不是“最终生产方案已经完全落地”，而是**开发期和交付期的口径要统一**。

---

## 7. V1 成功标准

当前更合理的 V1 成功标准应调整为：

- 能上传一个 PDF 或 TXT 文档
- 能通过同步链路完成 parse、chunk、embedding 和向量入库
- 能通过 queued 接口创建文档与 ingest job
- 能查询 ingest job 状态（含 `max_retry_limit` / `auto_retry_eligible` / `manual_retry_allowed`）
- 能由 worker 自动消费 ingest job 并把文档状态推进到 `active`
- 失败次数达到阈值后，任务能进入 `dead_letter`
- 能通过 `/api/v1/ingest/jobs/{job_id}/run` 手动重投递失败/待处理任务
- 能基于用户问题完成检索、rerank 和回答生成
- 返回结果中带有真实引用片段
- 单机环境下接口和测试可以稳定跑通

一句话总结：

**V1 的交付标准是“后端最小闭环已经真实跑通”，不是“企业级全能力已经完成”。**

---

## 8. V1 后续建议

如果继续按 V1 推进，最合理的下一步不是再改大架构，而是：

1. 保留当前 `POST /api/v1/ingest/jobs/{job_id}/run` 作为手动重投递/重试入口
2. 固化 Celery worker 的启动方式、部署方式和失败恢复语义（见 `backend/WORKER_RUNBOOK.md`）
3. 保持现有 API 合同不变，并按 `backend/INGEST_STATE_MACHINE.md` 维护 `failed/dead_letter` 判定语义
4. 等异步链路稳定后，再进入 ACL 过滤和 BM25

这样做的原因很直接：

- 当前闭环已经有了
- 下一步最值钱的是把“真实异步执行”变成“稳定异步执行”
- 如果现在继续把 BM25、ACL、OCR 一起塞进 V1，范围会再次失控
