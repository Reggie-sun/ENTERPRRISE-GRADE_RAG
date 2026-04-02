# Phase 2A Gate: Chunk 参数变更重建与回滚 Runbook

> **状态**：Phase 2A Gate Preparation — 文档与入口补齐
>
> **目标**：在真正修改 chunk 参数前，把"如何重建、如何验证、如何回滚"写清楚，并落成可执行入口。
>
> **约束**：本文档不修改 chunk 参数默认值，不启动真实重建，只建立 runbook 和命令入口。

---

## 1. 核心问题回答

### 1.1 改 chunk 是否需要全量重建 embedding？

**是的。** 修改 chunk 参数（`chunk_size_chars` / `chunk_overlap_chars` / `chunk_min_chars`）会改变：

1. **切块结果**：同一份文档的 chunk 数量、边界、内容都会变化
2. **Embedding 输入**：每个 chunk 的 `retrieval_text` 变化 → embedding 向量变化
3. **Qdrant point ID**：chunk_id 变化 → Qdrant point UUID 变化

因此，**任何 chunk 参数改动都需要对受影响文档执行全量重建**。

### 1.2 Qdrant / metadata / chunks 的重建顺序

**单文档重建顺序**（已有实现：`POST /api/v1/documents/{doc_id}/rebuild`）：

```
1. 删除 Qdrant 中该文档的所有向量点位
   └─ QdrantVectorStore.delete_document_points(doc_id)
2. 创建 follow-up 入库任务
   └─ _create_followup_ingest_job(record)
3. Celery worker 执行入库链路
   ├─ 解析文档（parser）
   ├─ 切块（chunker）← 使用当前 chunk 参数
   ├─ 向量化（embedding）
   └─ 写入 Qdrant（upsert）
4. 更新 chunk 文件
   └─ data/chunks/{document_id}.json
```

**批量重建顺序**（需手动编排）：

```
for each document_id in target_list:
    1. POST /api/v1/documents/{doc_id}/rebuild
    2. 轮询 GET /api/v1/ingest/jobs/{job_id} 直到 status in [completed, partial_failed, dead_letter]
    3. 记录结果
```

**关键点**：
- metadata（`data/documents/*.json`）不需要删除或修改
- 旧 chunk 文件会被新内容覆盖
- Qdrant 点位通过 `document_id` 过滤删除

### 1.3 当前没有自动 snapshot 机制

**现状**：
- chunk 结果文件：`data/chunks/{document_id}.json`（可手动备份）
- eval baseline 结果：`eval/results/eval_{timestamp}.json`（自动按时间戳保存）
- Qdrant 数据：无自动快照，依赖 Qdrant 自身的持久化配置

**建议的 baseline 保存方式**：

```bash
# 1. 记录当前 eval baseline
make eval-retrieval
# 结果自动保存到 eval/results/eval_{timestamp}.json

# 2. 备份当前 chunk 文件（可选但推荐）
tar -czvf data/chunks_backup_$(date +%Y%m%d_%H%M%S).tar.gz data/chunks/
```

### 1.4 回滚入口

**当前状态**：没有一键回滚机制。回滚需要手动操作。

**回滚步骤**（如果 chunk 参数改动后效果变差）：

```bash
# 1. 恢复 chunk 参数到旧值（修改 .env 或 config）
#    RAG_CHUNK_SIZE_CHARS=800
#    RAG_CHUNK_OVERLAP_CHARS=120
#    RAG_CHUNK_MIN_CHARS=200

# 2. 重启后端服务（让新参数生效）
#    make dev-api  # 或 systemctl restart rag-api

# 3. 对受影响文档执行重建
#    方式 A：使用批量重建脚本
python scripts/rebuild_documents.py --document-list doc_ids.txt
#    方式 B：逐个调用 API
for doc_id in $(cat doc_ids.txt); do
    curl -X POST "http://localhost:8020/api/v1/documents/$doc_id/rebuild" \
         -H "Authorization: Bearer $TOKEN"
done

# 4. 等待所有重建任务完成

# 5. 重新运行 eval 验证
make eval-retrieval

# 6. 对比 before/after 结果
python scripts/compare_eval_results.py \
    eval/results/eval_before.json \
    eval/results/eval_after.json
```

### 1.5 重建后如何用样本集验证

**标准验证流程**：

```bash
# 1. 重建前：运行 eval 并保存 baseline
make eval-retrieval
# 记录输出文件路径，如 eval/results/eval_20260402_100000.json

# 2. 执行 chunk 参数变更 + 文档重建
# ...（按上述流程操作）

# 3. 重建后：运行相同样本集的 eval
make eval-retrieval
# 新结果保存到 eval/results/eval_20260402_110000.json

# 4. 对比结果
# 手动对比：查看两个 JSON 文件的 summary.metrics
# 或使用对比脚本：
python scripts/compare_eval_results.py \
    eval/results/eval_20260402_100000.json \
    eval/results/eval_20260402_110000.json
```

**关键对比指标**：

| 指标 | 说明 | 期望变化 |
|------|------|---------|
| `top1_accuracy` | 首选文档命中率 | ≥ 之前 |
| `topk_recall` | top-k 召回率 | ≥ 之前 |
| `expected_doc_coverage_avg` | 多文档覆盖率 | ≥ 之前 |
| `heuristic_chunk_type_full_match_rate` | chunk 类型命中 | 观察变化 |
| `term_coverage_avg` | 关键词覆盖 | 观察变化 |

---

## 2. 可执行入口

### 2.1 已有入口

| 入口 | 命令 | 说明 |
|------|------|------|
| 单文档重建 | `POST /api/v1/documents/{doc_id}/rebuild` | API 端点，需认证 |
| 运行 eval | `make eval-retrieval` | Makefile 目标 |
| 运行 eval（自定义） | `python scripts/eval_retrieval.py --api-base http://localhost:8020` | 直接调用脚本 |

### 2.2 新增入口（Phase 2A 补齐）

| 入口 | 命令 | 说明 |
|------|------|------|
| 保存 eval baseline | `make eval-baseline TAG=before_chunk_change` | 保存带标签的 baseline |
| 批量重建文档 | `python scripts/rebuild_documents.py --document-list docs.txt` | 批量触发重建 |
| 对比 eval 结果 | `python scripts/compare_eval_results.py before.json after.json` | 生成对比报告 |
| 显示当前 chunk 配置 | `make show-chunk-config` | 显示当前 chunk 参数 |

---

## 3. 完整重建流程 Runbook

### 3.1 准备阶段

```bash
# 1. 确认后端服务运行中
curl http://localhost:8020/api/v1/health

# 2. 确认当前 chunk 参数
make show-chunk-config

# 3. 记录 eval baseline
make eval-baseline TAG=baseline_before_change
# 输出保存到 eval/results/baseline_baseline_before_change.json

# 4. （可选）备份 chunk 文件
tar -czvf data/chunks_backup_$(date +%Y%m%d_%H%M%S).tar.gz data/chunks/
```

### 3.2 执行 chunk 参数变更

```bash
# 1. 修改环境变量或 .env 文件
# 例如：调整 chunk_size_chars 从 800 到 600
export RAG_CHUNK_SIZE_CHARS=600

# 2. 重启后端服务使配置生效
# 开发环境：Ctrl+C 停止后重新 make dev-api
# 生产环境：systemctl restart rag-api
```

### 3.3 执行重建

**方式 A：全量重建（所有文档）**

```bash
# 1. 获取所有文档 ID 列表
curl -s http://localhost:8020/api/v1/documents \
     -H "Authorization: Bearer $TOKEN" \
     | jq -r '.items[].document_id' > all_doc_ids.txt

# 2. 执行批量重建
python scripts/rebuild_documents.py --document-list all_doc_ids.txt

# 3. 监控重建进度
python scripts/rebuild_documents.py --status
```

**方式 B：选择性重建（部分文档）**

```bash
# 1. 创建目标文档列表
cat > target_docs.txt << EOF
doc_20260321070337_445684f4
doc_20260401092629_f470103f
EOF

# 2. 执行批量重建
python scripts/rebuild_documents.py --document-list target_docs.txt
```

### 3.4 验证阶段

```bash
# 1. 等待所有重建任务完成
python scripts/rebuild_documents.py --wait

# 2. 运行 eval
make eval-baseline TAG=after_chunk_change

# 3. 对比结果
python scripts/compare_eval_results.py \
    eval/results/baseline_baseline_before_change.json \
    eval/results/baseline_after_chunk_change.json

# 4. 检查关键指标变化
# 如果 top1_accuracy / topk_recall 下降 → 考虑回滚
# 如果 chunk_type 命中率提升 → 变更有效
```

### 3.5 回滚（如需要）

```bash
# 1. 恢复 chunk 参数
export RAG_CHUNK_SIZE_CHARS=800  # 原始值

# 2. 重启后端
make dev-api

# 3. 重新执行 3.3 的重建流程

# 4. 重新验证（3.4）
```

---

## 4. 风险与注意事项

### 4.1 已知风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 重建期间服务不可用 | 用户查询可能返回不完整结果 | 在低峰期执行，或分批重建 |
| Embedding API 限流 | 重建速度受限，可能超时 | 控制并发数，增加重试 |
| Qdrant 写入失败 | 数据不一致 | 检查 job status，失败时重试 |
| 磁盘空间不足 | 重建失败 | 提前检查磁盘空间 |

### 4.2 不做的事（Phase 2A 边界）

- ❌ 不修改 `chunk_size_chars` / `chunk_overlap_chars` / `chunk_min_chars` 默认值
- ❌ 不修改 `text_chunker.py` 或 `structured_chunker.py` 的行为逻辑
- ❌ 不启动真实的全量重建
- ❌ 不进入 Phase 2B（chunk 参数扫描）

### 4.3 进入 Phase 2B 的前置条件

- [x] Phase 1 样本集就位（31 条 verified 样本）
- [x] Phase 1 eval 脚本可用（`make eval-retrieval`）
- [x] Phase 2A runbook 文档完成（本文档）
- [x] Phase 2A 命令入口就位
- [ ] Phase 1B-B 部门级 supplemental 评估闭环（当前 blocker）
- [ ] 决策：chunk 是否已成为主瓶颈（需 Phase 1 完整闭环后判断）

---

## 5. 文件变更清单

### 5.1 新增文件

| 文件 | 说明 |
|------|------|
| `OPS_CHUNK_REBUILD_RUNBOOK.md` | 本 runbook 文档 |
| `scripts/rebuild_documents.py` | 批量重建编排脚本 |
| `scripts/compare_eval_results.py` | eval 结果对比脚本 |

### 5.2 修改文件

| 文件 | 变更说明 |
|------|---------|
| `Makefile` | 新增 `eval-baseline`、`show-chunk-config` 目标 |
| `RETRIEVAL_OPTIMIZATION_BACKLOG.md` | 标记 Phase 2A Gate 条目完成 |

---

## 6. 验证清单

完成以下验证后，Phase 2A Gate 视为就绪：

- [ ] `make eval-baseline TAG=test` 可正常运行
- [ ] `make show-chunk-config` 显示当前 chunk 参数
- [ ] `python scripts/rebuild_documents.py --help` 显示帮助信息
- [ ] `python scripts/compare_eval_results.py --help` 显示帮助信息
- [ ] 本 runbook 文档已评审

---

## 7. 相关文档

- [RETRIEVAL_OPTIMIZATION_PLAN.md](RETRIEVAL_OPTIMIZATION_PLAN.md) — 检索优化总体计划
- [RETRIEVAL_OPTIMIZATION_BACKLOG.md](RETRIEVAL_OPTIMIZATION_BACKLOG.md) — 执行清单
- [eval/README.md](eval/README.md) — 评估样本与评分规则
- [OPS_SMOKE_TEST.md](OPS_SMOKE_TEST.md) — 运维冒烟测试
