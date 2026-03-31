# 检索评测集 (Retrieval Eval Dataset)

## 文件位置

```
backend/eval/retrieval_eval_dataset.json
```

## 用途

为 RAG 检索管线提供最小可重复评测基准，守住主链路检索质量。

## 样本类型覆盖

| 类型 | 数量 | 说明 |
|------|------|------|
| `alarm_code` | 8 | 报警码查询（E102/E204/E331/E990/E205/E700/E901/E301） |
| `concept_explanation` | 5 | 概念解释（CPPS、主轴冷却、吸盘、传感器校准等） |
| `process_steps` | 5 | 流程步骤（交接班、点检、急停复位、PLC恢复、电压排查） |
| `comparison` | 4 | 对比类（E102 vs E205、部门流程对比、rerank 策略、查询模式） |
| `metric` | 4 | 指标类（主轴温度、冷却液压力、伺服转速、真空度） |
| `department_private` | 5 | 部门私有知识（E990调查、巡检SOP、维修模板、校准记录、扭矩规范） |
| `global_knowledge` | 5 | 全局知识（安全规程、异常上报、消防预案、入职培训、5S管理） |
| `refuse_or_empty` | 4 | 拒答/空结果（恶意查询、无关查询、隐私查询、虚构报警码） |

**合计：40 条**

## 字段说明

每条样本包含以下字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 唯一标识，格式 `eval_NNN` |
| `type` | 是 | 样本类型（见上表） |
| `query` | 是 | 检索查询文本 |
| `expected_document_ids` | 是 | 期望命中的文档 ID 列表，空数组=不应命中 |
| `scope_expectation` | 是 | `global`（所有部门可访问）或 `department`（仅指定部门） |
| `accessible_departments` | 条件 | 有权访问的部门列表（`scope_expectation=department` 时必填） |
| `inaccessible_departments` | 否 | 不应有权访问的部门列表（用于权限回归验证） |
| `should_refuse` | 是 | 是否应被拒答 |
| `expected_top1_hit` | 是 | 期望第一条结果命中目标文档 |
| `notes` | 是 | 补充说明 |

## 如何扩充评测集

### 1. 新增单条样本

在 `samples` 数组末尾追加：

```json
{
  "id": "eval_041",
  "type": "alarm_code",
  "query": "E888 报警码含义",
  "expected_document_ids": ["doc_alarm_e888"],
  "scope_expectation": "global",
  "should_refuse": false,
  "expected_top1_hit": true,
  "notes": "新增报警码，验证对新报警文档的覆盖"
}
```

### 2. 新增类型

在 `sample_type_distribution` 中登记新类型，然后添加样本：

```json
{
  "id": "eval_050",
  "type": "multi_hop",
  "query": "E102 报警处理后需要做哪些设备复检",
  "expected_document_ids": ["doc_alarm_e102_handling", "doc_equipment_inspection"],
  "scope_expectation": "global",
  "should_refuse": false,
  "expected_top1_hit": false,
  "notes": "多跳推理类：需要综合两份文档才能回答"
}
```

### 3. 扩充原则

- **ID 连续递增**：从当前最大 `eval_NNN` + 1 开始
- **每新增一批样本后更新**：`total_samples`、`updated_at`、`sample_type_distribution`
- **`expected_document_ids` 留空**：如果文档尚未入库，先留空数组，入库后再补充
- **覆盖边界情况**：优先补充以下场景
  - 长尾报警码（出现频率低的报警）
  - 跨文档推理（需要综合 2+ 份文档）
  - 近义词/改写（同一意图的不同表达）
  - 中英文混合查询
  - 极短查询（1-3 个字）
  - 极长查询（完整段落级问题）

### 4. 与文档库对齐

当 `expected_document_ids` 中引用的文档实际入库后，需要验证：

1. 检索确实能命中对应文档
2. 部门隔离规则生效（`inaccessible_departments` 确实检索不到）
3. 排名质量（`expected_top1_hit=true` 的样本确实排在第一位）

## 与现有测试的关系

| 测试文件 | 定位 |
|----------|------|
| `test_main_chain_smoke.py` | 主链路烟测，守住 HTTP 契约骨架 |
| `test_main_contract_endpoints.py` | 契约字段形状回归 |
| `test_authorization_filters.py` | 权限隔离回归 |
| **`eval/retrieval_eval_dataset.json`** | **检索质量评测基准，关注内容命中率和排名** |

## 评测运行方式（预留）

```bash
# 未来可对接评测脚本
python -m backend.eval.run_retrieval_eval \
  --dataset backend/eval/retrieval_eval_dataset.json \
  --base-url http://localhost:8020
```

评测脚本不在本次范围内，当前评测集作为数据资产先行建立。
