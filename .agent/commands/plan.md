# `/plan`

用于中大改动的实现规划。

## 1. 使用原则

满足以下任一条件时，必须先 `/plan`，未确认前禁止改代码：

- 新功能或明显新流程
- 多文件联动
- 影响稳定契约
- 影响 `retrieval / chat / system-config / ingestion / auth`
- 影响 chunk / rerank / router / hybrid / supplemental
- 需要 backfill / rebuild / rollback

## 2. 输出要求

### 重述目标

- 这次要解决什么问题
- 这次不解决什么问题

### 涉及文件

- 明确列出准备修改的文件
- 如果不确定，先写待确认

### 修改步骤

1. 
2. 
3. 

### 风险点

- 行为回归风险
- 契约兼容风险
- 数据 / 重建 / 回滚风险

### 执行分工

- GPT-5.4（Brain）：
  - 定义目标、边界、风险、验收标准
  - 判断是否需要 spec、`/plan`、`/review`
  - 判断是否允许交由 GLM 执行
- GLM（Executor）：
  - 只在已确认边界内执行具体编码
  - 落实局部实现、补测试、补文档
  - 不自行扩大范围或改高风险方向
- 回切条件：
  - 一旦触碰 contract、retrieval 策略、schema / frontend 联动、跨模块扩散、eval 异常或计划失效，必须停止编码并回切 GPT-5.4

### 验证计划

- pytest：
- lint / build：
- smoke：
- eval：
- 手工验证：

## 3. 强约束

- 如果命中高风险改动，先跑 `make agent-inspect`，并在 `.agent/runs/` 补 task contract 后再进入实现。
- plan 中写的“涉及文件 / 可改边界 / 验证计划”，应能直接映射到 task contract 的 `allowed_paths / required_checks / expected_artifacts`。
- plan 输出后默认等待确认
- 未确认前禁止改代码
- 命中 `AGENTS.md` 中的 `Auto Enforcement` / 自动触发规则时，不得跳过 `/plan`
- 如果计划交由 GLM 执行，必须在 plan 中写清可改文件、不可触碰边界和回切条件
- retrieval 改动必须说明当前处于：
  - baseline
  - supplemental
  - chunk
  - router
  - rerank
  中的哪一层
- 如果样本或 baseline 不成熟，必须先写缺口，不能跳过
