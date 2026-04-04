# Phase 2B Readiness Audit Report

> **日期**：2026-04-04
> **性质**：Readiness audit，不是实现启动
> **约束**：未修改 `structured_chunker.py` / `text_chunker.py` / 任何 chunk 参数

---

## 1. 修改文件列表

本次 audit 未修改任何代码文件。仅新增本报告文件。

---

## 2. 当前 2B Readiness 状态

**结论：2B 尚未 Ready。**

硬性前置条件对照：

| 前置条件 | 状态 | 说明 |
|---------|------|------|
| Phase 2A Gate（runbook + 命令入口） | ✅ 已完成 | `OPS_CHUNK_REBUILD_RUNBOOK.md` 已就位 |
| Phase 1 样本集就位 | ✅ 已完成 | 31 条 verified 样本 |
| Phase 1 eval 脚本可用 | ✅ 已完成 | `make eval-retrieval` 可运行 |
| Phase 1B-B 部门级 supplemental 闭环 | ❌ 未完成 | `supplemental_precision=null`, `supplemental_recall=0.0`, `conservative_trigger_count=0` |
| chunk 已成为主瓶颈的样本证据 | ⚠️ 部分成立 | 文档命中 100%，但 chunk 类型命中仅 39% |

---

## 3. 结构化 Chunk 的主要热点 / 风险点

### 3.1 【已确认 · 代码 + eval 双重支撑】SOPStructuredChunker 对当前语料库大部分 SOP/WI 文档未触发

**证据来源**：实际 chunk 文件输出

检查了 3 份核心 SOP/WI 文档的 chunk 输出：

| 文档 | chunk_type 字段 | 使用的 chunker | 结构化字段（doc_title/section/keywords） |
|------|----------------|---------------|----------------------------------------|
| `doc_20260401092629_f470103f`（皮带轮部品 SOP, PPTX） | 全部 `text` | TextChunker | 全部 null |
| `doc_20260330055115_c20cfc5a`（WI-SJ-052, DOCX+OCR） | 全部 `text` | TextChunker | 全部 null |
| `doc_20260321070337_445684f4`（123.txt 报警手册） | 全部 `text` | TextChunker | 全部 null |

**根因分析**：

- **PPTX SOP（皮带轮部品）**：使用 `Step1/Step2/Step3` 格式而非 `X.Y` 条款号。`_CLAUSE_PATTERN` 不匹配 → `clause_hits=0` → `should_use` 返回 False。
- **WI-SJ-052（摇臂钻床）**：文本包含 `目的/适用范围/职责/内容` 四个标题和 `4.1`-`4.27` 条款号。**理论上应该触发** `should_use`。但实际 chunk 输出显示走的是 TextChunker。可能原因：OCR + 原生文本合并后，标题行的格式被破坏（如 OCR 行与前一行合并），导致 `_HEADING_SEQUENCE` 精确匹配失败。
- **123.txt（报警手册）**：Markdown 格式，使用 `## 6.1` 和 `#### 700000` 层级标题，没有 `目的/适用范围/职责/内容` 四标题结构。`should_use` 正确返回 False。

**影响**：当 SOPStructuredChunker 未触发时，这些文档得到的是无结构化元数据的纯文本 chunk。没有 `retrieval_text` 增强、没有 `keywords`、没有 `chunk_type` 分层，直接导致：
- 条款级 query 无法精准命中条款级 chunk
- 没有结构化 rerank 信号可供后续使用

### 3.2 【已确认 · eval 直接支撑】section_summary 系统性抢占 clause query

**证据来源**：最新 eval 结果（`eval_20260402_154413.json`）

全局统计：
- `heuristic_chunk_type_full_match_rate = 38.7%`（12/31）
- `heuristic_chunk_type_partial_match_rate = 61.3%`（19/31）

逐条分析：**所有 `expected_chunk_type=clause` 的 19 条样本，heuristic actual 全部为 `section_summary`**。没有一条 clause 样本的 top1 chunk 被判定为 clause 类型。

**根因分析**（代码级确认）：

1. `_build_section_summary_chunk` 中，`content` 通过 `_compact_clause_text` 把分组内所有 clause 的内容拼入 summary：
   ```python
   body = "；".join(self._compact_clause_text(entry) for entry in group.entries)
   content = f"本部分涵盖 {group.section}，包括：{body}。"
   ```

2. `_build_retrieval_text` 对所有 chunk_type 使用相同结构：
   ```python
   parts = [doc_title]
   if document_code: parts.append(document_code)
   parts.extend(part for part in (chunk_type, section, section_label) if part)
   parts.extend(keywords)
   parts.append(content)  # ← section_summary 的 content 已包含所有 clause 内容
   ```

3. 因此 section_summary 的 `retrieval_text` 在语义覆盖范围上 **天然包含** 每个 clause chunk 的全部内容，再加上额外的上下文框架。在 vector 和 lexical 双路检索中，section_summary 几乎必然排在 clause 之前。

**但需注意**：这个结论基于 SOPStructuredChunker 触发的情况。当前语料库中大部分 SOP/WI 文档实际未触发 SOPStructuredChunker（见 3.1），所以 eval 中看到的 `section_summary` heuristic 判定可能来自 eval 脚本的推断逻辑，而非真正的结构化 chunk 类型。

### 3.3 【已确认 · 代码直接支撑】Step 风格条目识别缺失

**证据来源**：`_CLAUSE_PATTERN` 定义

```python
_CLAUSE_PATTERN = re.compile(r"^(?P<number>\d+\.\d+)\.?\s*(?P<body>.*)$")
```

只匹配 `X.Y` 格式。以下格式不在识别范围内：
- `Step1` / `Step2` / `Step3`（PPTX SOP 普遍使用）
- `步骤1` / `步骤2`
- `1)` / `2)` / `3)`
- `一、` / `二、` / `三、`

这直接导致皮带轮部品等 PPTX SOP 文档无法被 SOPStructuredChunker 处理。

### 3.4 【已确认 · 代码直接支撑】`_HEADING_SEQUENCE` 和 `_PREDEFINED_CONTENT_GROUPS` 硬编码

- `_HEADING_SEQUENCE = ("目的", "适用范围", "职责", "内容")`：只覆盖一种 SOP 模板格式。不覆盖 "范围"、"定义"、"引用文件"、"工作程序"、"安全要求" 等常见变体。
- `_PREDEFINED_CONTENT_GROUPS`：5 个分组全部基于 WI-SJ-052 的 `4.1-4.27` 编号体系。其他 SOP 可能有完全不同的编号方案。

### 3.5 【合理怀疑 · 需更多证据】clause 信号偏弱

当前 clause chunk 的 `retrieval_text` 组成：
```
doc_title
document_code（如有）
clause
4.13
清屑要求
清屑要求
[clause 具体内容]
```

对比 section_summary 的 `retrieval_text`：
```
doc_title
document_code（如有）
section_summary
4.13-4.18
清屑、变速与停车要求
清屑、变速与停车要求
本部分涵盖 4.13-4.18，包括：4.13 钻孔时必须经常注意清除铁屑...；4.14 工作中注意超负荷现象...；4.15 攻螺纹时...；4.16 禁止开车变速...；4.17 钻孔过程中钻头未退离工件前不得停车...；4.18 薄板、大型或长形的工件竖着钻孔时...
```

section_summary 的 retrieval_text 在语义信息量上显著大于 clause。这不是简单的"clause_no_normalized 没进 retrieval_text"的问题（clause_no 已经通过 section 和 keywords 间接进入），而是 **section_summary 天然包含 clause 的全部信息再加额外上下文**。

### 3.6 【已确认 · eval 直接支撑】通用 TextChunker 对 SOP/WI 文档的 chunk 质量不足

当前 SOP/WI 文档走 TextChunker 时：
- chunk 纯按字符长度切分，不考虑条款/步骤边界
- chunk 重叠区域（默认 120 字符）可能把两个不同条款的内容混在一起
- 没有 `retrieval_text` 增强，embedding 质量完全依赖原始文本
- 没有 `chunk_type` / `section` / `clause_no` 等结构化元数据

从 chunk 文件可以确认：皮带轮部品 SOP 的两个 chunk 在 "Step3" 和 "Step1" 之间被切断，导致 Step3 的后半部分和 Step1 的前半部分混在同一个 chunk 中。

---

## 4. 未来真正进入 2B 时最值得优先改的 1-3 个点

按优先级排序：

### 优先级 1：扩展 `should_use` 识别范围，让更多 SOP/WI 文档进入结构化分块

**最小改动候选**：
- 扩展 `_CLAUSE_PATTERN` 增加 `Step\d+` 识别
- 放宽 `_HEADING_SEQUENCE` 或增加替代标题匹配
- 考虑 filename-based 触发（当前已有 `_BUSINESS_FILENAME_PATTERN`，但阈值要求过高）

**预期收益**：让当前语料库中大部分 SOP/WI 文档从无结构化 chunk 变为有结构化 chunk，直接提升 clause query 的检索精度。

**风险评估**：低。只影响 `should_use` 判定，不改变已有 chunk 的行为。

### 优先级 2：section_summary 与 clause 的 retrieval_text 信号平衡

**最小改动候选**：
- clause chunk 的 `retrieval_text` 增加更强的位置/编号信号
- section_summary 的 `retrieval_text` 缩短聚合内容，只保留概要而非完整拼接
- 或引入 chunk_type 权重调整（在 rerank 或 hybrid 阶段）

**预期收益**：让条款级 query 更容易命中 clause chunk 而非 section_summary。

**风险评估**：中。需要 before/after eval 对比，可能影响 section_summary 类型 query 的命中率。

### 优先级 3：`_PREDEFINED_CONTENT_GROUPS` 从硬编码改为自适应

**最小改动候选**：
- 保留 `_PREDEFINED_CONTENT_GROUPS` 作为已知模板的快速匹配
- 增加基于 clause 编号间隔和语义相似度的自动分组 fallback
- 或直接改为等距/等量分组

**预期收益**：让 SOPStructuredChunker 适用于不同编号体系的 SOP 文档。

**风险评估**：中。分组逻辑变化会影响 section_summary 的粒度和内容。

---

## 5. 建议补的测试与评估入口

### 5.1 `backend/tests/test_structured_chunker.py`（新增）

建议覆盖的测试场景：

```
1. should_use 判定
   - 标准四标题 + X.Y 条款号 → True
   - filename 包含 WI/SOP + 两标题 + 两条款号 → True
   - Step1/Step2/Step3 格式 → 当前 False（记录预期行为）
   - 非 SOP 文档 → False

2. clause 识别
   - X.Y 格式条款 → 正确提取 clause_no 和 content
   - X.Y 后跟 tab → 正确处理
   - X.Y 后无内容 → 正确处理空 body
   - Step1 格式 → 当前不识别（记录预期行为）

3. retrieval_text 组成
   - clause chunk 的 retrieval_text 包含 doc_title, section, clause_no
   - section_summary 的 retrieval_text 不应逐字包含所有 clause 内容
   - doc_summary 的 retrieval_text 包含关键信息但不冗长

4. section 分组
   - 4.1-4.27 编号 → 使用 _PREDEFINED_CONTENT_GROUPS
   - 非标准编号 → 使用 fallback 分组
   - 无 clause_no 的 entries → 正确处理

5. 文档覆盖
   - 用 WI-SJ-052 原文做端到端 split 测试
   - 用 PPTX SOP 原文做 should_use 判定测试
   - 用 markdown 文档做 should_use 判定测试（预期 False）
```

### 5.2 `backend/tests/test_document_ingestion.py`（增强）

建议增加：

```
1. SOP/WI 文档的 chunk 类型验证
   - 上传标准 WI 文档 → 验证 chunk 输出包含结构化字段
   - 上传 PPTX SOP 文档 → 验证当前走 TextChunker（记录预期行为）
   - 上传非结构化文档 → 验证走 TextChunker

2. chunk 文件完整性
   - 验证 chunk JSON 文件包含所有必需字段
   - 验证 retrieval_text 不为空（当使用 SOPStructuredChunker 时）

3. 混合 OCR+原生文本文档
   - 验证 OCR 参与后 SOPStructuredChunker 仍能正确识别标题
   - 验证 chunk 元数据正确标注 OCR 来源
```

### 5.3 评估增强建议

1. **chunk 类型 ground-truth**：当前 `heuristic_chunk_type_score` 是从 `retrieval_strategy`/`source_scope`/文本长度推断的，不是真实类型。建议在 chunk 文件中直接读取 `chunk_type` 字段作为 ground-truth。
2. **clause query 精度指标**：增加 `clause_precision` 指标 —— 在 `expected_chunk_type=clause` 的样本中，top-k 结果中是否有至少一个 clause 类型 chunk。
3. **section_summary 覆盖度**：记录 section_summary 被错误命中的频率，作为 section_summary 抢占程度的直接度量。

---

## 6. 当前为什么还不能正式进入 2B

1. **Phase 1B-B 未闭环**：`supplemental_precision=null`、`supplemental_recall=0.0`、`conservative_trigger_count=0`。部门级 supplemental 评估尚不可用。
2. **无法区分 chunk 问题 vs supplemental 问题**：当前 eval 以 `sys_admin` 运行，所有文档可见。在这种模式下，文档命中率 100% 是预期的。chunk 类型命中率低（39%）可能部分是因为 SOPStructuredChunker 根本没触发（走了 TextChunker），而不是 chunk 策略本身的问题。
3. **缺少 before/after 对比基线**：当前只有一个 eval baseline，没有 chunk 变更前后的对比数据。
4. **RETRIEVAL_OPTIMIZATION_PLAN 的顺序约束**：计划明确要求 "先调在线策略，再动入库底座"。supplemental 阈值收口应在 chunk 优化之前。

---

## 7. 这轮是否只是 audit / readiness，而不是实现

**是的，这轮纯粹是 audit 和 readiness 评估。**

本报告：
- 未修改 `structured_chunker.py`
- 未修改 `text_chunker.py`
- 未修改任何 chunk 参数
- 未执行任何 reindex / rebuild
- 未宣称 "2B 已开始" 或 "chunk 优化已完成"

---

## 8. Hotspot 证据分类

### 已被代码或 eval 直接支持的问题

| 编号 | Hotspot | 证据类型 | 证据来源 |
|------|---------|---------|---------|
| H1 | SOPStructuredChunker 对大部分 SOP/WI 文档未触发 | chunk 文件输出 | `data/chunks/*.json` |
| H2 | section_summary 系统性抢占 clause query | eval 结果 | `eval_20260402_154413.json`，19/19 clause 样本被抢 |
| H3 | `_CLAUSE_PATTERN` 不识别 Step 格式 | 代码 | `structured_chunker.py:13` |
| H4 | `_HEADING_SEQUENCE` / `_PREDEFINED_CONTENT_GROUPS` 硬编码 | 代码 | `structured_chunker.py:35-43` |
| H5 | TextChunker 对 SOP 文档的 chunk 边界不对 | chunk 文件输出 | `doc_20260401092629_f470103f.json` |

### 合理怀疑但还需要更多证据的问题

| 编号 | Hotspot | 为什么还需要证据 |
|------|---------|----------------|
| S1 | section_summary retrieval_text 过长导致 embedding 偏移 | 需要对比 clause vs section_summary 的 embedding 相似度分布 |
| S2 | WI-SJ-052 的 `should_use` 为何未触发 | 需要用实际 parsed text 调用 `should_use` 验证 |
| S3 | 扩展 Step 识别后是否能提升 clause 命中率 | 需要 before/after eval 对比 |
| S4 | clause retrieval_text 增强后是否能对抗 section_summary | 需要 before/after eval 对比 |
