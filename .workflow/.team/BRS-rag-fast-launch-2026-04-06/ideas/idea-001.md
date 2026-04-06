# IDEA-001

## Topic

最快上线当前 RAG，暂不处理 SOP，优先保证回答准确性，同时保留后续可优化空间。

## Angle

accuracy-first MVP

## Mode

Initial Generation

## Ideas

### 1. 以“证据型问答”定义 MVP，而不是通用助手

MVP 只承诺两类高确定性场景：明确文号、故障码、步骤号的精确问答，以及已有文档内的事实型检索问答。当前仓库的 exact/fine 样本已经接近可上线水平，但 semantic/coarse 仍有明显落差，所以产品定义必须跟现状对齐，不能把它包装成泛化推理助手。

Key assumption: 用户首批真实价值主要来自“找准条款、步骤、故障处理”，不是开放式总结。

Potential impact: 直接把当前强项变成上线面，降低语义型误答带来的信任损失。

Implementation hint: 首页、输入框提示、帮助文案都明确写成“基于已收录文档回答，并优先适配故障码、条款、步骤、规范问答”。

### 2. 把“有证据才回答”设成硬门槛

`chat/ask` 已经支持 citations 和无上下文响应，但 MVP 需要更进一步：当引用数量不足、top1/topk 证据弱、或检索结果互相冲突时，默认输出“当前证据不足，建议改写问题、限定文档或人工确认”，而不是继续生成顺滑答案。准确性优先意味着宁可少答，也不能把 LLM 流畅度当正确性。

Key assumption: 用户更能接受“我不确定”，而不能接受带引用外观的错误答案。

Potential impact: 显著降低幻觉式误答，把错误模式从“自信瞎答”改成“保守拒答”。

Implementation hint: 先用现有 retrieval diagnostic、citation count、top1/topk 命中强度做一个内部 answerability gate，不改 public contract。

### 3. 首发只开放“已验证语料 + 已验证权限模型”

最快上线不等于全量放开上传和全量放开部门补充召回。MVP 应该只挂载一批已经过样本验证、索引状态清楚、ACL 已 seed 的文档集合；如果 active metadata store 还没完成 ACL seed，就把 cross-dept supplemental 限定为内测能力，正式首发先走单部门或管理员可控范围。

Key assumption: 当前最大上线风险不是接口缺失，而是语料质量边界和权限边界不够稳定。

Potential impact: 把“答案错”风险拆成可控变量，避免把索引、权限、补充召回三件事同时在线试错。

Implementation hint: 用现有 auth profile mapping 和 retrieval ACL seed 先圈定 launch corpus，未验证文档不进首发白名单。

### 4. 用 eval gate 决定是否上线，而不是看单次 smoke 体感

这个仓库已经有 retrieval eval、样本集和结果目录，MVP 上线门槛应该直接绑定它，而不是只看 demo 效果。建议把当前 43 条样本作为最低 gate，并把 exact/fine、semantic/coarse、supplemental 三类指标拆开看，任何一类退化都阻断上线。

Key assumption: 准确率必须靠固定样本复跑证明，不能靠临场提问运气。

Potential impact: 防止“局部看起来很好”掩盖真实退化，给后续优化保留可比基线。

Implementation hint: 首版 gate 至少要求 overall top1/topk 不低于当前基线、exact/fine 保持 1.0、semantic/coarse 单独人工复核失败样本、supplemental 指标只有在 ACL seed 生效后才作为正式放行条件。

### 5. Citation 必须是用户可读证据，不只是字段存在

主契约里 `chat/ask` 的 `citations` 已经是稳定字段，但 MVP 的非协商项不是“返回 citations 数组”，而是“引用真的能支撑答案”。当前 heuristic chunk type full match 只有约 44%，说明命中文档虽准，引用粒度还不够稳，所以首发必须要求回答正文尽量贴着引用内容，优先输出短答案和原文摘录型依据。

Key assumption: 当前系统更擅长找对文档，不一定总能找对最理想的证据块。

Potential impact: 即使 chunk 还没进入下一阶段优化，也能先把用户感知准确性抬高。

Implementation hint: UI 上展示 `document_name + snippet + page_no`，并鼓励“答案结论 + 引用证据”格式；对 broad summary 问题提示用户继续追问到更具体粒度。

### 6. 明确延后 SOP、复杂总结、自动扩展能力

题目已经说明暂不处理 SOP，这不该只停留在口头范围，而应落实为首发边界：不承诺 SOP 生成、SOP 专属工作流、复杂跨文档总结、全量自助上传后的即刻高质量问答。因为 retrieval、chat、SOP 共享底层逻辑，若为了上线速度硬塞 SOP，只会把评估面和风险面一起放大。

Key assumption: 首发目标是验证“当前 RAG 能否稳定回答”，不是验证所有知识工作流。

Potential impact: 极大压缩测试面、文档面和运营面，让团队把精力集中在 retrieval/chat 的正确性闭环。

Implementation hint: 前端隐藏或降级 SOP 入口；对 broad semantic 场景标记为 beta，避免作为主卖点。

### 7. 通过“内部可调、外部不扩约”保留后续优化空间

后续还要做 supplemental 阈值校准、chunk 优化、router/hybrid 权重、最后才是 rerank 默认路由，所以 MVP 不应新增公开配置面或新 contract 字段。最好的上线形态是继续把调优能力收在 system config 内部真源、diagnostic、trace、eval 脚本和 canary 结果里，让后续优化可以持续迭代但不破坏主契约。

Key assumption: 未来优化会频繁发生，公开接口一旦提前暴露错误抽象，会拖慢后续所有阶段。

Potential impact: 既能快速上线，又不会把当前经验性参数固化成长期包袱。

Implementation hint: 对外只保留现有 stable endpoints；对内继续用 `system_config_service`、diagnostic、eval results 做实验和回归。

## Summary

这条 accuracy-first MVP 路线的核心不是“做少一点功能”，而是把现有强项收敛成一个可信产品面。建议首发只包含受控语料下的 `retrieval/search` 与 `chat/ask`，强制证据门槛、引用可读性和固定样本 eval gate；同时明确延后 SOP、复杂总结和未验证的跨部门补充召回，把后续优化继续留在内部配置与评估体系里。
