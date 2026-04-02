# Retrieval Phase 1A Patch GLM Prompt

## 这一阶段做什么

这是对已完成的 Phase 1A scaffold 做一轮修补，不是新开一轮大功能。

目标是把“看起来能用”修到“默认路径不踩坑、结果语义不误导”。

这轮只修以下问题：

1. 默认登录账号与本地 runbook 不一致
2. `requester_department_id` 已出现在样本里，但脚本并没有真的按样本身份评估
3. `chunk_type` 评分目前是启发式猜测，不能伪装成正式指标
4. `diagnostic_trigger_basis` 字段取值不准确
5. `baseline_config_snapshot.yaml` 目前更像模板，不像真实运行时快照

---

## 硬约束

- 不新增 `retrieval/search`、`chat/ask`、`system-config` 的稳定 public 字段
- 不改变现有主契约字段语义
- 不在这轮里直接做阈值校准
- 不在这轮里修改 retrieval 主逻辑
- 这轮优先修“默认可运行”和“结果语义真实”，不是扩功能

---

## 开工前必须先读

- [RETRIEVAL_PHASE1A_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE1A_GLM_PROMPT.md)
- [RETRIEVAL_OPTIMIZATION_BACKLOG.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_BACKLOG.md)
- [LOCAL_DEV_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/LOCAL_DEV_RUNBOOK.md)
- [eval/retrieval_samples.yaml](/home/reggie/vscode_folder/Enterprise-grade_RAG/eval/retrieval_samples.yaml)
- [eval/README.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/eval/README.md)
- [eval/baseline_config_snapshot.yaml](/home/reggie/vscode_folder/Enterprise-grade_RAG/eval/baseline_config_snapshot.yaml)
- [scripts/eval_retrieval.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/scripts/eval_retrieval.py)
- [Makefile](/home/reggie/vscode_folder/Enterprise-grade_RAG/Makefile)
- [retrieval.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/api/v1/endpoints/retrieval.py)
- [auth.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/api/v1/endpoints/auth.py)
- [retrieval.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/schemas/retrieval.py)

---

## 已确认的问题

### 1. 默认账号错误

当前脚本默认使用：

- `admin`
- `admin123`

但本仓库本地 runbook 明确的 demo 账号是：

- `sys.admin.demo`
- `sys-admin-demo-pass`

因此 `make eval-retrieval` 默认直接失败。

### 2. 样本中的部门上下文没有真正参与评估

当前样本有 `requester_department_id`，但脚本并没有真的使用不同身份运行样本。

所以：

- `by_department` 分组现在只是按样本标签分组
- `cross-dept supplemental` 的结论并不一定可信

### 3. `chunk_type` 评分目前只是 heuristic

当前脚本是根据：

- `retrieval_strategy`
- `source_scope`
- 文本长度

去推断 `chunk_type`。

这可以当 placeholder，但不能在 README 和报告里写得像正式 ground truth 评分。

### 4. `diagnostic_trigger_basis` 取值不对

当前脚本把它记成了 `supplemental_reason`，而不是更稳定、语义更直接的 `supplemental_trigger_basis`。

### 5. baseline 快照更像模板，不像真实快照

当前 `eval/baseline_config_snapshot.yaml` 里很多值是手填或 `TBD`。

可以接受，但必须明确它是：

- `template`
- `manual snapshot`

或者改成脚本可导出的真实运行时快照。

---

## 本轮推荐修法

### A. 修默认账号和 Makefile 默认行为

最少要做到：

- 脚本默认账号改成与 [LOCAL_DEV_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/LOCAL_DEV_RUNBOOK.md) 一致
- Makefile 默认运行方式也一致
- 同时支持环境变量覆盖，例如：
  - `AUTH_USERNAME`
  - `AUTH_PASSWORD`

### B. 不要再“假装”按部门评估

这轮不要做重型身份模拟系统，但要让语义真实。

可接受的最小方案有两种，任选其一：

#### 方案 1：引入最小 auth profile 映射

- 样本可选引用 `auth_profile`
- 增加一个轻量 auth profiles 配置文件
- 脚本按 profile 登录并缓存 token

#### 方案 2：如果做不到真实身份模拟，就降级表述

- README 明确说明 `requester_department_id` 当前只是样本标签
- `by_department` 是标签视角，不等于真实权限视角
- `cross-dept supplemental` 的结果必须标记为 provisional

如果你选择方案 2，必须把这些限制写清楚，不能继续让人误以为这已经是权限真实评估。

### C. 把 `chunk_type` 指标明确降级为 heuristic

要求：

- README 明确标注这是 `heuristic_chunk_type_score`
- 报告字段名也建议同步改成更诚实的名字
- 或者保留原字段，但额外加 `is_heuristic=true`

### D. 修正 trigger basis 取值

脚本里应优先使用：

- `diagnostic.supplemental_trigger_basis`

只有缺失时才考虑回退到：

- `diagnostic.supplemental_reason`

### E. baseline 快照语义要真实

二选一：

#### 方案 1：把它明确改成 template

- 在文件头和 README 明确写 `template/manual`

#### 方案 2：增加一个轻量导出能力

- 由脚本或单独命令导出当前运行时可见配置
- 如果导不出内部字段，就明确哪些字段来自运行时、哪些是手工补充

不要保留现在这种“看起来像真实快照，但其实半手写”的模糊状态。

---

## 验收标准

- `make eval-retrieval` 默认不再因为错误账号直接失败
- README 对“部门评估能力边界”说清楚
- `chunk_type` 评分被明确标为 heuristic / provisional
- `diagnostic_trigger_basis` 语义正确
- baseline snapshot 的语义被澄清或实现为可导出

---

## 可直接发给 GLM 的 Prompt

```text
你现在在仓库 /home/reggie/vscode_folder/Enterprise-grade_RAG 工作。

请先阅读：
- RETRIEVAL_PHASE1A_GLM_PROMPT.md
- RETRIEVAL_OPTIMIZATION_BACKLOG.md
- LOCAL_DEV_RUNBOOK.md
- eval/retrieval_samples.yaml
- eval/README.md
- eval/baseline_config_snapshot.yaml
- scripts/eval_retrieval.py
- Makefile
- backend/app/api/v1/endpoints/retrieval.py
- backend/app/api/v1/endpoints/auth.py
- backend/app/schemas/retrieval.py

任务：实现 Retrieval Phase 1A Patch。目标不是新建功能，而是修补当前 Phase 1A scaffold 中已经确认的语义和默认运行问题。

已确认问题：
1. make eval-retrieval 默认账号错误，和 LOCAL_DEV_RUNBOOK 不一致
2. requester_department_id 已存在，但脚本并没有真实按样本身份评估
3. chunk_type 评分当前只是 heuristic，却写得像正式指标
4. diagnostic_trigger_basis 实际取的是 supplemental_reason
5. baseline_config_snapshot.yaml 更像模板，不像真实运行时快照

必须遵守：
1. 不新增 retrieval/search、chat/ask、system-config 的稳定 public 字段。
2. 不改变现有主契约字段语义。
3. 不直接修改 retrieval 主逻辑。
4. 这轮优先修“默认可运行”和“结果语义真实”，不要扩到阈值调优。

请完成以下工作：
1. 修正 eval_retrieval.py 和 Makefile 的默认登录账号，与 LOCAL_DEV_RUNBOOK 对齐
2. 支持通过环境变量或参数覆盖账号密码
3. 处理 requester_department_id 的语义问题：
   - 如果能做轻量 auth profile 映射，就实现它
   - 如果不能，就明确降级文档表述，不要假装是权限真实评估
4. 把 chunk_type 评分明确标为 heuristic / provisional
5. 修正 diagnostic trigger basis 的读取逻辑
6. 把 baseline_config_snapshot.yaml 明确为 template/manual，或者提供轻量导出方式

优先推荐：
- 默认账号改为 sys.admin.demo / sys-admin-demo-pass
- 支持 AUTH_USERNAME / AUTH_PASSWORD 覆盖
- 对 chunk_type 指标改更诚实的命名或增加 is_heuristic 标记
- 优先使用 diagnostic.supplemental_trigger_basis

完成后请输出：
1. 修改文件列表
2. 你选择了“真实 auth profile 映射”还是“语义降级说明”，为什么
3. make eval-retrieval 或等价命令的运行结果
4. 还剩哪些限制没有解决，但已经被明确标注出来
```
