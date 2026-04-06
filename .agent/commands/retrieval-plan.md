# `/retrieval-plan`

用于 retrieval 相关改动的专用规划命令。

它不是替代通用 `/plan`，而是 retrieval 场景下更具体的版本。

---

## 1. 什么时候必须用

命中以下任一情况时，优先使用 `/retrieval-plan`：

- 修改 `retrieval_service.py`
- 修改 `retrieval_scope_policy.py`
- 修改 `query_profile_service.py`
- 修改 `retrieval_query_router.py`
- 修改 `eval/retrieval_samples.yaml`
- 修改 `eval/README.md`
- 修改 `scripts/eval_retrieval.py`
- 修改 supplemental / router / hybrid / rerank / diagnostics 相关测试
- 需要判断“现在该不该进入下一阶段”

---

## 2. 先判断当前属于哪一层

在输出 plan 前，必须先判断当前任务属于：

1. `baseline`
   - 样本是否 verified
   - baseline 是否真实可复跑
2. `supplemental`
   - 是否在做 auth / ACL / 阈值 / diagnostics / false negative 审计
3. `chunk`
   - 是否已经完成 Phase 1 收口
4. `router`
5. `rerank`

如果当前还在 `baseline / supplemental`，禁止跳去 `chunk / router / rerank`。

---

## 3. 必读文件

### 通用必读

1. `MAIN_CONTRACT_MATRIX.md`
2. `RETRIEVAL_OPTIMIZATION_PLAN.md`
3. `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
4. `.agent/context/repo-map.md`
5. `.agent/context/retrieval-state.md`

如果读取后发现以下任一信息已变化，必须先更新 `.agent/context/retrieval-state.md`，再继续输出 plan：

- 最新 baseline 报告
- 当前 provisional / final 阈值
- 当前阶段判断
- 当前 blocker 判断

建议在输出 plan 前或收尾时运行：

- `make check-retrieval-state`

### Retrieval / Eval 必读

1. `eval/README.md`
2. `eval/retrieval_samples.yaml`
3. `scripts/eval_retrieval.py`
4. `eval/results/` 最新结果
5. 目标实现文件
6. 目标测试文件

如果未完成这些读取，禁止进入编码。

---

## 4. 输出格式

### 4.1 当前状态

- 当前阶段：
- 当前层级：`baseline / supplemental / chunk / router / rerank`
- 最新 baseline：
- 当前关键指标：
- 当前 blocker：

### 4.2 本轮目标

- 这次要解决什么：
- 这次明确不解决什么：

### 4.3 影响文件

- 准备修改：
- 只读参考：
- 不允许触碰：

### 4.4 证据

至少列出：

- 最新 eval 报告路径
- 当前样本状态
- 当前相关测试落点
- 当前实现证据（函数 / 逻辑 / diagnostic）

### 4.5 变更步骤

1. 
2. 
3. 

### 4.6 验证计划

- pytest：
- eval：
- API：
- smoke：
- 手工验证：

### 4.6.1 停止过度验证 / 退出条件

在 retrieval 的 `baseline / supplemental / gate stabilization / readiness review` 场景下，验证计划不能只写“补跑更多 eval”。

输出 plan 时，必须额外写清：

- 这轮验证要支持哪一个阶段判断
- 本轮只补哪些高价值证据
- 哪些现象属于结构性 blocker
- 哪些现象只是可接受的非确定性波动
- 最多再做哪些验证：
  - 哪几条 targeted behavior tests
  - 哪几组样本
  - 最多几次重复 eval
- 满足什么条件就停止继续追加验证

如果继续追加验证已经不能改变阶段结论，就不要再把 plan 写成开放式“继续观察”。

建议直接带上这段 prompt：

```md
停止过度验证，先定义退出条件。

- 当前层级：
- 当前要支持的阶段决策：
- 本轮只补哪些高价值证据：
- 哪些现象属于结构性 blocker，哪些属于可接受非确定性：
- 最多再做哪些验证：
  - 哪几条行为测试
  - 哪几组样本
  - 最多几次重复 eval
- 满足什么条件就停止，并输出 pass / not pass / conditionally passed：

如果新增验证已经不能改变阶段结论，就不要继续扩大验证范围；直接收敛文档、证据和下一步建议。
```

### 4.7 风险与回滚

- 行为回归风险：
- 阶段顺序风险：
- 数据 / ACL / rebuild 风险：
- 回滚方式：

### 4.8 回切条件

命中以下任一情况必须停止编码并回切：

- 发现会触碰稳定主契约
- 样本 / eval / 实现三者不一致
- 需要从 supplemental 跳去 chunk
- 需要从 chunk 跳去 router / rerank
- 需要改 schema / frontend API / 主字段
- 当前 baseline 不再可信

### 4.9 Harness task contract

retrieval 场景默认同步维护 `.agent/runs/<task>.yaml`，至少写清：

- `task_type: retrieval`
- `phase`
- `allowed_paths`
- `required_reads`
- `required_checks`
- `risk_notes`
- `expected_artifacts`

在开始实现前，默认先跑：

- `make agent-inspect`
- `make agent-preflight TASK=.agent/runs/<task>.yaml`

实现收尾时，默认再跑：

- `make agent-verify TASK=.agent/runs/<task>.yaml`

---

## 5. Retrieval 场景下的强约束

### 5.1 不允许跳阶段

默认顺序：

1. `baseline`
2. `supplemental`
3. `chunk`
4. `router / hybrid`
5. `rerank`

### 5.2 不允许用后层掩盖前层问题

- 不要先动 rerank 掩盖 retrieval 问题
- 不要先动 router 掩盖 chunk 问题
- 不要在 Phase 1 未收口前正式开始 Phase 2B

### 5.3 不允许把 heuristic 当 ground truth

- `chunk_type` heuristic 只能做观察
- diagnostics 只能反映当前实现，不等于正确性本身
- placeholder / provisional baseline 不能包装成 final snapshot

### 5.4 不允许跳过 eval

retrieval 改动默认必须：

- 跑相关 pytest
- 跑 eval，或明确说明为什么当前不能跑
- 如果是 docs-only，必须明确写 “docs-only，没有跑代码测试”

---

## 6. 交给 GLM / Claude 执行时必须写清

如果 plan 不是自己执行，而是交给别的 coding agent：

- 当前真实状态
- 必读文件
- 硬约束
- 本轮目标
- 明确可改文件
- 明确不可触碰边界
- 输出要求
- 回切条件

不要只给提纲。

---

## 7. 当前仓库默认判断

如果今天的 retrieval 任务没有额外说明，默认按以下顺序判断：

1. 先看 `.agent/context/retrieval-state.md`
2. 如果当前 still in `Phase 1B-B`，继续补 `supplemental`
3. 只有当：
   - baseline 稳定
   - supplemental 指标可解释
   - blocker 已收口
   才允许讨论进入 `Phase 2`

如果当前状态文件和最新 eval 不一致，先更新状态，再计划实现。

如果本轮实现或审计会导致以下任一信息变化，也必须把“更新 `.agent/context/retrieval-state.md`”写进收尾清单：

- baseline
- 阈值
- 阶段判断
- blocker 判断
