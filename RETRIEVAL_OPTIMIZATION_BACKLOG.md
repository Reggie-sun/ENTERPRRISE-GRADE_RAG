# Retrieval Optimization Backlog

> 基于 [RETRIEVAL_OPTIMIZATION_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_PLAN.md) 的执行清单。  
> 这份 backlog 只记录"符合当前仓库现实、遵守主契约、可以直接落地"的检索优化工作。
>
> **一句话原则：没有样本基线，不进入下一阶段；没有回滚预案，不改 chunk。**

---

## 0. Guardrails

### 0.1 主契约约束

- 以 [MAIN_CONTRACT_MATRIX.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/MAIN_CONTRACT_MATRIX.md) 为硬约束。
- 不新增 `retrieval/search`、`chat/ask`、`system-config` 的稳定 public 字段。
- 不改变现有稳定字段语义。
- 检索优化优先走内部实现、诊断字段、脚本、测试和运行时配置真源。

### 0.2 链路一致性

- `retrieval / chat / SOP` 必须继续共用同一套 supplemental 判定逻辑。
- 不允许为了某个 endpoint 的效果临时分叉规则。

### 0.3 优先级顺序

1. 先做在线召回收口与样本校准。
2. 再决定 chunk 问题是否已成为主瓶颈。
3. 进入 chunk 阶段前，先补重建与回滚预案。
4. 再做现有 SOPStructuredChunker 校准与通用参数扫描。
5. 然后再调 query router / hybrid 权重。
6. 最后再做 rerank 默认路由决策。

---

## 1. 当前状态快照

### 已完成

- [x] Supplemental 质量阈值已进入内部真源，而不是扩公开 `system-config` 主契约。
- [x] `RetrievalService` 已从内部检索配置读取 supplemental 阈值。
- [x] `retrieval / chat / SOP` 继续共用同一条 supplemental 判定逻辑。
- [x] 主契约测试与检索专项回归已恢复通过。
- [x] 认证基线已收紧，检索相关业务接口默认要求登录。

### 当前最值得做

- [ ] 建立真实 query 样本集。
- [ ] 建立可重复运行的 retrieval 评估脚本。
- [ ] 用固定样本对内部阈值做校准，而不是靠感觉调。
- [ ] 用样本结果判断 chunk 是否已经值得进入下一阶段。

### 相关现有实现

- 内部检索配置真源：
  - [system_config_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/system_config_service.py)
  - [system_config.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/schemas/system_config.py)
- Supplemental 判定主逻辑：
  - [retrieval_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_service.py)
- Query router 现有评估脚本：
  - [eval_hybrid_query_router.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/scripts/eval_hybrid_query_router.py)
  - [hybrid_query_router_samples.jsonl](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/fixtures/hybrid_query_router_samples.jsonl)
- 通用和结构化 chunk 实现：
  - [text_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/text_chunker.py)
  - [structured_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/structured_chunker.py)
  - [ingestion_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/ingestion_service.py)

---

## 2. Phase 1: 补充召回与阈值校准

> 这是当前第一优先级。目标不是扩新策略，而是把现有策略校准稳定。

### 2.1 建立 retrieval 样本集

**优先级：P0**

#### 目标

- 建立一批可重复复跑的真实 query 样本。
- 每条样本都能回答这几个问题：
  - 期望命中的主文档是谁
  - 期望 top chunk 是什么类型
  - 是否应该触发 supplemental
  - 是否依赖部门外补充召回

#### 建议文件

- [eval/retrieval_samples.yaml](/home/reggie/vscode_folder/Enterprise-grade_RAG/eval/retrieval_samples.yaml)
- [eval/README.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/eval/README.md)

#### 样本分类

- [ ] `exact / code-like`
- [ ] `fine-grained clause`
- [ ] `semantic explanation`
- [ ] `broad summary`
- [ ] `cross-dept supplemental expected`

#### 最低规模

- [ ] 第一轮至少 40 条
- [ ] 最好尽快扩到 60 条以上
- [ ] 每类至少 8 条

#### 样本字段建议

```yaml
samples:
  - id: exact-001
    query: "PLC_A01 故障代码 E003"
    query_type: exact
    expected_granularity: fine
    expected_doc_ids: ["doc-maint-001"]
    expected_chunk_type: clause
    expected_terms: ["E003", "故障"]
    supplemental_expected: false
    requester_department_id: "maintenance"

  - id: cross-001
    query: "全厂紧急疏散流程"
    query_type: semantic
    expected_granularity: coarse
    expected_doc_ids: ["doc-safety-001", "doc-admin-015"]
    expected_chunk_type: section_summary
    supplemental_expected: true
    requester_department_id: "maintenance"
```

#### 验收标准

- [ ] 样本能覆盖"应触发 supplemental"和"不应触发 supplemental"两类情况
- [ ] 样本包含 fine query 和 coarse query
- [ ] 样本格式文档化，后续能继续增量补充

#### 样本判分规则（必须明确）

后面评估最容易吵的是"命中算对"，必须在 [eval/README.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/eval/README.md) 明确：

| 指标 | 判定规则 |
|------|----------|
| `top1_accuracy` | top1 的 doc_id 必须在 `expected_doc_ids` 里才算对；如果 `expected_doc_ids[0]` 是首选，top1 必须是它才算全对，否则算半对。**半对单独记为 `top1_partial_hit`，不并入 `top1_accuracy`** |
| `topk_recall` | top-k 结果中至少有一个 doc_id 在 `expected_doc_ids` 里就算 recall 对 |
| `chunk_type 命中` | 如果 `expected_chunk_type=clause`，命中 `section_summary` 算半对；命中 `doc_summary` 算错 |
| `supplemental 判对` | `supplemental_expected=true` 且实际触发 → 对；`supplemental_expected=false` 且实际未触发 → 对；`supplemental_expected=false` 但实际触发时，默认记为"保守触发"，只有在未明显增加噪声且最终 top-k 质量未下降时，才不计为误判 |
| `多文档期望` | 如果 `expected_doc_ids` 有多个，top-k 命中任意一个即算 recall 对；同时单独记录 `expected_doc_hit_count` / `expected_doc_coverage` 反映多文档命中覆盖率 |

不补这个，后面实验结果会有很多口水仗。

---

### 2.2 建立 retrieval 评估脚本

**优先级：P0**

#### 目标

- 用同一批样本重复调用受保护的检索接口。
- 自动汇总 top1 命中、topk recall、chunk 命中质量、supplemental 触发准确率。

#### 建议文件

- [scripts/eval_retrieval.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/scripts/eval_retrieval.py)
- [Makefile](/home/reggie/vscode_folder/Enterprise-grade_RAG/Makefile)
- [eval/results/](/home/reggie/vscode_folder/Enterprise-grade_RAG/eval/results/)

#### 脚本要求

- [ ] 先登录，再带 `Bearer` 调用受保护接口
- [ ] 支持切换 API base url
- [ ] 支持指定样本文件路径
- [ ] 输出 JSON 报告
- [ ] 输出可读摘要，方便人快速判断

#### 建议输出指标

- [ ] `top1_accuracy`
- [ ] `topk_recall`
- [ ] `expected_doc_coverage`（多文档命中覆盖率）
- [ ] `supplemental_precision`
- [ ] `supplemental_recall`
- [ ] `conservative_trigger_count`（保守触发单独计数，不直接并入误判，除非明显增加噪声或拉低 top-k 质量）
- [ ] `by_query_type`
- [ ] `by_department`

#### Makefile 建议目标

- [ ] `make eval-retrieval`

#### 验收标准

- [ ] 能在本地 dev API 上复跑
- [ ] 同一批样本重复运行结果稳定
- [ ] 能直接产出可对比的前后实验报告

---

### 2.3 冻结 baseline 配置快照

**优先级：P0**

#### 目标

- 在跑 baseline 前，记录当前关键配置快照。
- 避免后面 rerun 时出现"同样脚本、同样样本，结果不一样"的配置漂移问题。

#### 必须记录的配置项

- [ ] Supplemental 4 个阈值：`top1_threshold` / `avg_top_n_threshold` / `fine_query_top1_threshold` / `fine_query_avg_top_n_threshold`
- [ ] Chunk 参数：`chunk_size_chars` / `chunk_overlap_chars` / `chunk_min_chars`
- [ ] Dynamic weighting 开关
- [ ] Rerank compare 开关
- [ ] `truncate_to_top_k` 相关配置
- [ ] 当前索引版本 / 数据集版本
- [ ] 当前 commit hash / branch 名称

#### 建议文件

- [eval/baseline_config_snapshot.yaml](/home/reggie/vscode_folder/Enterprise-grade_RAG/eval/baseline_config_snapshot.yaml)

#### 验收标准

- [ ] 每次实验前都有配置快照记录
- [ ] 配置快照与实验结果一一对应

---

### 2.4 用内部真源校准 supplemental 阈值

**优先级：P0**

#### 目标

- 校准这 4 个阈值，而不是改 public contract：
  - `top1_threshold`
  - `avg_top_n_threshold`
  - `fine_query_top1_threshold`
  - `fine_query_avg_top_n_threshold`

#### 相关现有文件

- [system_config_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/system_config_service.py)
- [system_config.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/schemas/system_config.py)
- [retrieval_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_service.py)
- [test_system_config_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_system_config_service.py)
- [test_system_config_endpoints.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_system_config_endpoints.py)
- [test_retrieval_chat.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_retrieval_chat.py)

#### 执行方式

- [ ] 基线跑一次当前默认阈值
- [ ] 设计至少 3 组阈值组合
- [ ] 对比 fine query 与普通 query 的触发差异
- [ ] 记录误触发和漏触发案例

#### 约束

- [ ] 不新增公开 `system-config` 字段
- [ ] 不把内部键 `_internal_retrieval_controls` 暴露到 public response
- [ ] 阈值实验失败时，仍要保留默认回退能力

#### 验收标准

- [ ] `department_sufficient` 不滥触发 supplemental
- [ ] `department_low_quality` 能稳定触发 supplemental
- [ ] `department_insufficient` 能稳定触发 supplemental
- [ ] `retrieval / chat / SOP` 在同一组阈值下行为一致

---

### 2.5 诊断字段与回归测试收口

**优先级：P0**

#### 目标

- 让诊断面能真实反映当前检索决策。
- 保证后续继续调阈值时，回归测试能及时发现偏移。

#### 重点字段

- [ ] `primary_threshold`
- [ ] `primary_top1_score`
- [ ] `primary_avg_top_n_score`
- [ ] `quality_top1_threshold`
- [ ] `quality_avg_threshold`
- [ ] `supplemental_triggered`
- [ ] `supplemental_trigger_basis`

#### 建议覆盖的测试

- [ ] 本部门结果充足且质量足够时，不触发 supplemental
- [ ] 本部门结果充足但质量低时，触发 supplemental
- [ ] 本部门结果不足时，触发 supplemental
- [ ] `truncate_to_top_k=True` 与 `False` 的阈值窗口逻辑不同
- [ ] fine query 使用更严格阈值

#### 相关测试文件

- [test_retrieval_chat.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_retrieval_chat.py)
- [test_main_contract_endpoints.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_main_contract_endpoints.py)
- [test_main_contract_errors.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_main_contract_errors.py)

#### 验收标准

- [ ] 主契约测试继续通过
- [ ] retrieval 专项回归继续通过
- [ ] 诊断字段与实际触发行为一致

---

## 3. Phase 2: Chunk 优化

> 只有在 Phase 1 样本评估和阈值校准稳定后再进入。
> 进入任何 chunk 改动前，必须先完成 3.0 重建与回滚预案。
>
> **原则：优先处理已确认收益更高的结构化文档问题，再处理 generic text 的面优化。**

### 3.0 重建索引与回滚预案（Phase 2 Gate）

**优先级：P1 | Gate | ✅ DONE**

#### 目标

- 在真正改 chunk 前，把重建与回滚路径写清楚。
- 这是进入 Phase 2 所有后续条目的前置条件。

#### 建议文件

- [OPS_CHUNK_REBUILD_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/OPS_CHUNK_REBUILD_RUNBOOK.md) ✅ NEW
- [Makefile](/home/reggie/vscode_folder/Enterprise-grade_RAG/Makefile) — 新增 targets
- [scripts/](/home/reggie/vscode_folder/Enterprise-grade_RAG/scripts/) — 新增脚本

#### 至少要明确

- [x] 改 chunk 是否需要全量重建 embedding
- [x] Qdrant / metadata / chunks 的重建顺序
- [x] snapshot 或备份方式
- [x] 回滚入口
- [x] 重建后怎么用样本集验证

#### 新增命令入口

- [x] `make eval-baseline TAG=name` — 保存带标签的 eval baseline
- [x] `make show-chunk-config` — 显示当前 chunk 参数
- [x] `python scripts/rebuild_documents.py --document-list docs.txt` — 批量重建编排
- [x] `python scripts/compare_eval_results.py before.json after.json` — eval 结果对比

#### 验收标准

- [x] 有书面 runbook ([OPS_CHUNK_REBUILD_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/OPS_CHUNK_REBUILD_RUNBOOK.md))
- [x] 有可执行命令或脚本入口
- [x] 重建前后有同一批样本对比结果（已通过 `eval-baseline` 机制支持）

---

### 3.1 通用文本 chunk 参数扫描

**优先级：P1**

#### 目标

- 判断当前通用 chunk 参数是否导致"文档命中了，但 chunk 不准"。
- 在有限参数组合内找到更稳的默认值。

#### 相关文件

- [\_retrieval.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/core/_retrieval.py)
- [text_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/text_chunker.py)
- [ingestion_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/ingestion_service.py)
- [test_document_ingestion.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_document_ingestion.py)

#### 关注参数

- [ ] `chunk_size_chars`
- [ ] `chunk_overlap_chars`
- [ ] `chunk_min_chars`

#### 建议动作

- [ ] 准备代表性文档集
- [ ] 先扫描少量组合，不直接全量暴力搜索
- [ ] 用 Phase 1 的 query 样本复跑验证 top chunk 变化

#### 验收标准

- [ ] 文档命中不下降明显
- [ ] top chunk 更聚焦
- [ ] citation 更短更可读

---

### 3.2 现有 SOPStructuredChunker 校准与扩展

**优先级：P1**

#### 目标

- 校准现有 735 行 `structured_chunker.py`，而不是从零开始。
- 提升条款类、章节类、文号类 query 的命中精度。
- 解决 `doc_summary / section_summary` 抢走 clause 命中的问题。

#### 相关文件

- [structured_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/structured_chunker.py)
- [ingestion_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/ingestion_service.py)

#### 建议新增或修改测试

- [ ] [test_structured_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_structured_chunker.py)
- [ ] [test_document_ingestion.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_document_ingestion.py)

#### 优先观察点

- [ ] `retrieval_text` 是否包含足够的文号、章节号、关键词
- [ ] clause chunk 是否过短或信息不足
- [ ] section summary 是否过强，导致细粒度问句命不中 clause
- [ ] doc summary 是否太泛，导致 broad query 和 fine query 互相干扰

#### 验收标准

- [ ] 文号/条款号 query 更稳定命中 clause
- [ ] 结构化引用片段更接近最终答案所需证据
- [ ] 不明显增加误召回

---

### 3.3 文档类型路由最小版设计

**优先级：P1**

#### 目标

- 把 `ingestion_service.py` 从"单特判"升级为"可扩展路由"。
- 当前只有 `SOPStructuredChunker` 的 `should_use(text, filename)` 特判 + `TextChunker` fallback。
- 需要为后续 `manual / policy / faq` 等文档类型预留扩展点。

#### 相关文件

- [ingestion_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/ingestion_service.py)
- [structured_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/structured_chunker.py)
- [text_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/text_chunker.py)

#### 当前状态

- 现有 doc family：`sop_wi` / `generic_text` 二分法
- `SOPStructuredChunker` 已支持：metadata / doc_summary / section_summary / clause 四种粒度
- `TextChunker` 仅做字符切分

#### 建议动作

- [ ] 抽象 `ChunkStrategy` 接口
- [ ] 明确 doc family 枚举：`sop_wi / manual / policy / faq / generic`
- [ ] 不一定先做完整 UI 选择，但至少把路由逻辑从"单特判"改成"可扩展分发"
- [ ] 为 `manual / policy / faq` 预留 placeholder

#### 约束

- **第一阶段优先走 ingestion 内部路由，不要求先扩上传接口 public 字段。**
- 一写 "doc family 枚举"，后面很容易有人顺手就想在上传接口里加 `doc_type`。这未必错，但不一定该在这一阶段做。
- 保持与 guardrails 一致：优先内部实现，不碰主契约。

#### 验收标准

- [ ] 新增文档类型时，不需要改 ingestion 主流程
- [ ] 每种 doc family 有明确的 chunk 策略映射
- [ ] 现有 SOP/WI 行为不变

---

## 4. Phase 3: Query Router 与 Hybrid 权重校准

> 只有在 chunk 侧不再是主要问题后再做。

### 4.1 Query router 样本扩充

**优先级：P2**

#### 相关现有文件

- [eval_hybrid_query_router.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/scripts/eval_hybrid_query_router.py)
- [hybrid_query_router_samples.jsonl](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/fixtures/hybrid_query_router_samples.jsonl)
- [retrieval_query_router.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_query_router.py)
- [test_hybrid_query_router_samples.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_hybrid_query_router_samples.py)
- [test_retrieval_query_router.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_retrieval_query_router.py)

#### 任务

- [ ] 扩充 exact / mixed / semantic 样本
- [ ] 增加缩写、文号、条款号、错误码样本
- [ ] 复跑现有 router 评估脚本

#### 验收标准

- [ ] 规则分类误判可解释
- [ ] fine-grained 样本不再频繁掉到 semantic broad 分支

---

### 4.2 Hybrid 权重调优

**优先级：P2**

#### 目标

- 针对不同 query 类型校准 `vector / lexical` 权重。

#### 相关文件

- [retrieval_query_router.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_query_router.py)
- [\_retrieval.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/core/_retrieval.py)
- [retrieval_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_service.py)

#### 任务

- [ ] 结合样本结果复盘 exact query 的 lexical 比重
- [ ] 复盘 semantic query 的 vector 比重
- [ ] 观察 mixed query 是否过于偏向某一路

#### 验收标准

- [ ] 编号/代码/缩写类 query 更稳
- [ ] broad semantic query 不因为 lexical 偏置掉召回

---

## 5. Phase 4: Rerank 默认路由决策

> 这是最后一刀，不在前面阶段没收稳之前提前做。

### 5.1 Canary 复盘

**优先级：P3**

#### 相关现有文件

- [rerank_canary_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/rerank_canary_service.py)
- [retrieval.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/api/v1/endpoints/retrieval.py)
- [test_rerank_canary_endpoints.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_rerank_canary_endpoints.py)
- [test_ops_endpoints.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_ops_endpoints.py)

#### 任务

- [ ] 收集更多真实 compare 样本
- [ ] 看 heuristic 和 provider 的 top1 一致率
- [ ] 看延迟、稳定性和成本

#### 验收标准

- [ ] 能给出"继续 heuristic / 观察 canary / 提升 provider"为主的明确建议

---

## 6. 近期执行顺序

### Now

- [x] 建 `eval/retrieval_samples.yaml`
- [x] 建 `scripts/eval_retrieval.py`
- [x] 在 [Makefile](/home/reggie/vscode_folder/Enterprise-grade_RAG/Makefile) 增加 `make eval-retrieval`
- [x] 用当前默认阈值跑第一版 baseline

### Next

- [ ] 做 3 组以上 supplemental 阈值实验
- [ ] 把实验结果写入 `eval/results/` 或 `eval/experiments/`
- [ ] 根据结果决定是否进入 chunk 阶段

### Later

- [x] ~~补重建与回滚预案（Phase 2 Gate）~~ → 已在 3.0 完成
- [ ] 做现有 SOPStructuredChunker 校准
- [ ] 做通用 chunk 参数扫描
- [ ] 设计文档类型路由最小版
- [ ] 再评估 query router / hybrid / rerank

---

## 7. Definition of Done

### Phase 1 完成

- [ ] 有可复跑样本集
- [ ] 有样本判分规则文档（eval/README.md）
- [ ] 有可复跑评估脚本
- [ ] 有 baseline 配置快照
- [ ] 有 baseline 报告
- [ ] 有阈值校准实验记录
- [ ] `retrieval / chat / SOP` supplemental 行为一致
- [ ] 主契约测试继续通过

### Phase 2 完成

- [x] 重建与回滚预案就位（Gate）
- [ ] chunk 调整后 top chunk 更准
- [ ] citation 更聚焦
- [ ] SOPStructuredChunker 校准完成，summary/clause 平衡改善
- [ ] 文档类型路由从"单特判"升级为"可扩展分发"
- [ ] 样本复跑结果优于调整前

### Phase 3 完成

- [ ] router 样本集更完整
- [ ] hybrid 权重调整有样本依据
- [ ] 质量提升可量化

### Phase 4 完成

- [ ] canary 样本规模足够
- [ ] 有默认 rerank 路由的明确决策
- [ ] 质量/延迟/成本平衡可解释
