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

---

## 9. v0.1.2 版本定位

`v0.1.2` 不再扩功能面，定位为一个 **稳定化 / 可演示 / 可复现** 版本。

这一版的目标不是继续引入新组件，而是把当前已经打通的链路真正收口成一套别人可以按文档跑起来的开发基线。

当前基线链路如下：

- 前端：Vite + React（本地 `3000`）
- 后端：FastAPI（本地 `8020`）
- 向量库：Qdrant
- 队列：Celery + Redis
- Embedding：本地 OpenAI-compatible embedding 服务
- LLM：服务器 vLLM（远程 OpenAI-compatible）

一句话：

**v0.1.2 要解决的是“这套链路能不能稳定被别人拉起并重复验证”，不是“再做更多能力”。**

### 9.1 v0.1.2 必做项

`v0.1.2` 只收下面几类内容：

1. 启动与配置收口

- 前端代理地址、后端端口、模型地址统一
- `.env` / `.env.example` 的字段口径统一
- 前端支持通过 `VITE_API_TARGET` 显式指定后端地址
- 开发环境启动顺序写清楚：前端 / 后端 / worker / embedding / vLLM

2. 前端演示链路收口

- 上传、轮询、检索、问答四块联动
- 页面显示当前操作文档名称和 doc_id
- 每次上传新文档后自动清空旧检索结果和旧问答结果
- 检索和问答支持按当前 `document_id` 过滤，避免历史测试文档串结果
- 上传失败、检索失败、问答失败都要有清晰错误展示

3. 回归验证收口

- 后端测试至少覆盖：
  - 文档上传
  - ingest job 状态查询
  - 手动重投递
  - 检索
  - 问答
  - `document_id` 过滤
- 前端至少保证：
  - `npm run build` 可通过
  - 开发环境代理指向正确后端

4. 文档与 runbook 收口

- 当前实际启动方式要写进 runbook
- 本机与服务器的职责边界要写清楚
- 常见故障要有最小排查说明，例如：
  - Vite 代理端口错误
  - worker 未启动
  - embedding 服务未启动
  - vLLM 未 ready

### 9.2 PostgreSQL 边界与风险控制

当前代码已经接入了 PostgreSQL，但在 `v0.1.2` 必须明确它的角色边界，否则范围会失控。

`v0.1.2` 对 PostgreSQL 的冻结口径如下：

- 在线检索主链路仍然固定为 `Qdrant`
- PostgreSQL 当前允许承担 `document/job metadata` 真源角色
- PostgreSQL 中的 `versions/chunks/assets/pgvector` 允许继续作为 backfill / 分析 / 迁移支路存在
- `v0.1.2` 不做在线检索从 Qdrant 切到 pgvector
- `v0.1.2` 不做“双写后以 PostgreSQL 检索为准”的切库动作

这样定义的原因：

- 现在已经接入 PostgreSQL，直接回退这部分工作没有必要
- 但如果在 `v0.1.2` 继续推进在线检索切到 PostgreSQL，版本性质就会从“稳定化”变成“重构”
- 当前最稳的做法是：**保留 PostgreSQL 接入成果，但不改变在线主检索路径**

因此，`v0.1.2` 的风险控制原则固定为：

1. Qdrant 是当前在线检索真源
2. PostgreSQL 是当前 metadata 真源和数据沉淀支路
3. pgvector 是后续演进位，不是当前主链路

### 9.3 v0.1.2 优先级

按优先级执行时，建议顺序固定为：

1. 配置和启动方式收口
2. 前端联动与错误提示收口
3. `document_id` 过滤和状态隔离收口
4. 测试补齐
5. runbook / 发布说明收口

### 9.4 v0.1.2 验收标准

`v0.1.2` 完成时，至少要满足：

- 本机执行前端开发命令后，`3000` 页面可正常访问
- 前端通过代理访问本地 `8020` 后端，不再依赖错误的默认端口
- 上传一个 PDF / TXT 文档后，能看到真实 ingest job 状态流转
- 当前文档名称和 doc_id 在页面上可见
- 检索只返回当前文档的结果
- 问答引用只返回当前文档的片段
- `pytest backend/tests/test_retrieval_chat.py backend/tests/test_document_ingestion.py` 通过
- `frontend` 执行 `npm run build` 通过

并且新增一条架构验收约束：

- PostgreSQL 接入不改变当前 Qdrant 在线主检索链路

### 9.5 v0.1.2 明确不做

以下内容继续后置，不纳入 `v0.1.2`：

- 在线检索切到 PostgreSQL / pgvector
- 让 pgvector 替代当前 Qdrant 主检索链路
- ACL / RBAC 正式落地
- BM25 / RRF 混合检索
- OCR 与复杂 Office 解析
- 审核流
- Agent
- docker compose 全量生产化编排

说明：

- 这里不是说 PostgreSQL 相关工作不再继续，而是说 `v0.1.2` 不把“在线切库”作为交付目标
- PostgreSQL metadata、backfill、pgvector 补数能力可以保留，但不进入主检索路径切换

### 9.6 v0.1.2 建议输出物

这一版结束时，建议至少产出：

- 一份更新后的 `V1_PLAN.md`
- 一份更新后的 `V1_RELEASE.md`
- 一份可执行的本地运行说明
- 一份最小 smoke test 清单

这样做的意义是：

- 代码能跑
- 页面能演示
- 配置不靠猜
- 版本边界清楚
