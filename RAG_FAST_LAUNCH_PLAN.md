# RAG 快速上线方案

## 目标

目标不是把当前仓库一次性做成“全能 AI 助手”，而是尽快把它收口成一个可上线、可验证、可回滚的**证据型问答产品**。

这次上线只追求三件事：

- 回答尽量准确
- 错了宁可拒答，也不要自信胡答
- 上线后还能继续按既定顺序优化，不被首发方案锁死

## 单一路径

推荐的上线主线只有一条：

- 只上线 `POST /api/v1/retrieval/search` 和 `POST /api/v1/chat/ask` 这条主链路
- 暂时不带 SOP，不带“未来优化型重构”，不做大范围产品扩展
- 把当前产品定义成“有证据才回答”的 RAG 问答系统，而不是通用聊天助手
- 先冻结一个 `launch bundle`，再只用这个 bundle 产出一份不可变 `evidence package` 做 go/no-go
- 只有这份证据包过关，才允许发版

## 为什么这样做

当前仓库已经给出了很清楚的边界：

- `MAIN_CONTRACT_MATRIX.md` 已冻结主契约，至少包括 `POST /api/v1/retrieval/search`、`POST /api/v1/chat/ask`、`GET /api/v1/system-config`、`PUT /api/v1/system-config`
- `RETRIEVAL_OPTIMIZATION_PLAN.md` 明确要求后续优化顺序是 `supplemental -> chunk -> router/hybrid -> rerank`
- `RETRIEVAL_OPTIMIZATION_BACKLOG.md` 也强调“没有样本基线，不进入下一阶段；没有回滚预案，不改 chunk”

这意味着最快、最稳的路线不是现在去做更多功能，而是先把**首发边界、证据链、回滚链**立住。

## 当前可用信号

截至 `2026-04-06T02:57:18+00:00` 的评估结果 `eval/results/eval_20260406_105718.json` 显示：

- 总样本数：`43`
- overall `top1_accuracy`：约 `0.953`
- overall `topk_recall`：约 `0.977`
- `supplemental_precision` / `supplemental_recall`：约 `0.957 / 0.957`
- heuristic `chunk_type_full_match_rate`：约 `0.442`
- `exact` / `fine` 类 query 很强，但 `semantic` / `coarse` 类仍弱一些

这组结果说明两件事：

- 当前 retrieval 主体已经具备首发基础，不是“完全不能上”
- 但 citation 粒度、语义类 query、以及“命中文档对但证据块不够准”的问题还不能靠乐观叙述掩盖

另外，这份结果的 `threshold_experiment.note` 明确写着：**这是一轮 threshold experiment，不是最终 calibration**。所以它可以作为首发参考，但不能直接当最终放行凭证。

## 首发范围

这次上线建议只保留以下能力：

- 已验证语料上的证据型问答
- 带 citation 的回答
- 无充分证据时的拒答 / 改写提示
- department / ACL 边界内的受控检索
- 必要的 trace、diagnostic、request snapshot、event log

## 明确不做

以下内容全部延后到首发之后：

- SOP
- 大范围 chunk 策略重构
- router / hybrid 权重大调
- rerank 默认路由决策
- “像通用助手一样”的开放式长回答
- 依赖未验证 cross-dept supplemental 的正式首发
- 为了首发去扩稳定主契约

## 首发必须具备的产品行为

### 1. 有证据才回答

- `chat/ask` 必须执行 evidence-first gate
- 证据不足、证据冲突、citation 不成立时，默认拒答或要求用户改写问题
- 不允许“回答看起来很顺，但 citation 实际支撑不了答案”

### 2. 非拒答答案必须带 citation

- citation 不是接口里有字段就算完成
- 前端必须能让用户看到“答案依据来自哪份文档、哪一段、哪一页或哪一块内容”
- 首发宁可回答短一点，也要保证证据链清楚

### 3. 只支持高确定性问题

首发问题类型建议收口在：

- 故障码
- 条款
- 步骤
- 规范
- 明确字段或明确信息定位类问题

不把首发包装成“可稳定处理复杂跨文档推理和 SOP 流程”的系统。

## Launch Bundle

首发不能只说“代码差不多了”，必须冻结一份 `launch bundle`。这份 bundle 至少要包含：

- `commit SHA`
- frontend release mode
- model version
- `system-config` snapshot
- corpus manifest
- index version / index artifact
- metadata mode
- ACL seed state
- rollout scope
- verified eval subset

原则很简单：

- 你验证的是什么 bundle，上线的就必须是什么 bundle
- 如果 bundle 变了，之前的放行结论自动失效

## Evidence Package

真正决定能不能上线的，不是“感觉已经不错”，而是一份不可变的 `evidence package`。

这份证据包建议至少包含：

- pinned bundle 清单
- retrieval eval 结果
- 人工复核答案结果
- 权限边界预检结果
- rollback 对象清单
- 放行结论和责任人

人工复核建议至少按下面 5 类分桶：

- `correct`
- `abstained`
- `unsupported-query`
- `wrong-with-citation`
- `permission-boundary-failure`

## Go / No-Go 门槛

建议按保守标准执行：

- `permission-boundary-failure = 0`
- 非拒答答案 `citation presence = 100%`
- `wrong-with-citation = 0`
- 用于放行的 eval 子集必须重新跑在 pinned bundle 上
- active metadata store 的 ACL seed 状态必须和评估假设一致
- rollback 演练通过

这里有一个非常重要的取舍：

- 首发允许 `abstained` 偏高
- 首发不允许“看起来答了，但其实答错”

## 最快上线的执行顺序

### Phase 1

- 冻结主契约，不扩接口
- 冻结首发语料范围
- 冻结首发 ACL / rollout scope
- 实装或收紧 evidence-first gate
- 确保 citation 展示对用户可读

### Phase 2

- 产出 pinned launch bundle
- 重新跑用于放行的 eval 子集
- 做人工复核分桶
- 做权限边界预检
- 做 rollback 演练

### Phase 3

- evidence package 过关则发版
- 不过关则只在当前 retrieval/chat 核心上继续收口
- 不在首发窗口内引入 chunk/router/rerank 的新变量

## 上线后的优化顺序

上线后继续按仓库既定主线推进，不要倒序：

1. supplemental 校准
2. chunk 优化
3. router / hybrid 权重优化
4. rerank 默认路由优化

这样做的好处是：

- 你的首发版本有明确边界
- 后续每一步优化都有可比 baseline
- 不会为了首发把系统改成难以解释、难以回滚的状态

## 主要风险

- 当前 eval 结果不错，但仍不是最终 calibration
- `semantic` / `coarse` query 相比 `exact` / `fine` 仍更弱
- heuristic chunk match 说明 citation 粒度还不是完全稳态
- 如果 ACL seed 和 active metadata store 不一致，supplemental 相关判断会失真
- 如果不冻结 bundle，很容易出现“测试的是 A，发布的是 B”

## 结论

如果你的目标是“最快上线这个 RAG，同时尽量保准确，而且后续还能继续优化”，那就不要在首发阶段追求功能完整。

正确做法是：

- 把它收口成一个证据型问答产品
- 用 pinned bundle + evidence package 决定能不能发
- 允许保守拒答
- 延后 SOP、chunk/router/rerank 大动作

这条路径最不花哨，但最稳，也最适合当前仓库。
