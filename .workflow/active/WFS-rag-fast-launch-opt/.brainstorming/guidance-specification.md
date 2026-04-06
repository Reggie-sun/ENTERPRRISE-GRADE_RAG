# RAG 快速首发优化 - Confirmed Guidance Specification

**Generated**: 2026-04-06
**Type**: Fast Launch Optimization
**Focus**: 1周内全量发布，评估链补全，保持后续可优化
**Roles**: system-architect, test-strategist, product-manager, data-architect

## 1. Project Positioning & Goals

**CONFIRMED Objectives**:
- 1周内完成全量发布，目标用户为所有目标用户
- 首发定位为**证据型文档问答系统**，非通用聊天助手
- 回答尽量准确，错了宁可拒答，不要自信胡答
- 保留后续优化空间：supplemental → chunk → router → rerank 顺序不变

**CONFIRMED Success Criteria**:
- Evaluation chain 从 threshold experiment 升级为正式 calibration
- Evidence-first gate 实装，不满足条件时引导式拒答
- Bundle freeze 机制建立，防止"测试A发B"
- 人工复核分桶完成，go/no-go 门槛明确
- 回滚链（kill switch + bundle 级）可演练

**CONFIRMED Constraints**:
- 时间窗口：1周
- 不动 retrieval 内部逻辑，只在 chat 层加门控
- 前端最小改动
- 不引入新基础设施（保持 docker-compose）
- SOP 明确排除

## 2. Concepts & Terminology

| Term | Definition | Aliases | Category |
|------|------------|---------|----------|
| Launch Bundle | 首发冻结的不可变组件集合（commit + config + corpus + index + ACL） | pinned bundle, 首发包 | core |
| Evidence Gate | chat 层的 score threshold + citation 验证，决定是否拒答 | evidence-first gate, 证据门控 | core |
| Calibration Eval | 从 threshold experiment 升级的正式评估，样本数 60-80 | final eval, 正式评估 | core |
| Human Review Bucket | 5桶分类：correct / abstained / unsupported-query / wrong-with-citation / permission-boundary-failure | 人工复核分桶, review bucket | core |
| Kill Switch | 配置级紧急关停开关，切换后所有回答变为拒答 | 紧急开关, emergency toggle | technical |
| Corpus Manifest | 语料库冻结清单，包含文档列表 + chunk 数量 + hash | 语料清单, 语料清单 | technical |
| ACL Seed | 权限配置快照，评估和上线必须一致 | 权限种子, 权限种子 | technical |
| Score Threshold | retrieval 结果的相关性分数阈值，低于此值触发拒答 | 相关性阈值, 相关性阈值 | technical |

## 3. Non-Goals (Out of Scope)

- **SOP 功能**: 用户明确排除，延后到首发之后
- **Chunk/Router/Rerank 重构**: RETRIEVAL_OPTIMIZATION_PLAN 规定的顺序不变
- **新 API 接口**: 冻结主契约，不扩接口
- **通用聊天助手定位**: 产品定义是证据型问答，不做开放式长回答
- **新基础设施**: 不引入 K8s、Prometheus 等新基础设施
- **Retrieval 内部调整**: 不动 retrieval service 内部逻辑

## 4. System-Architect Decisions

### Bundle Freeze Mechanism
**SELECTED**: 脚本自动化冻结，写入 `launch-bundle.json`
- **Rationale**: 1-2天可完成，自动校验一致性
- **Impact**: The system MUST generate launch-bundle.json containing commit SHA, config snapshot, corpus manifest, index version, ACL seed state
- **Requirement Level**: MUST

### Rollback Strategy
**SELECTED**: 配置级 kill switch
- **Rationale**: 最快实装，system-config 中加标志即可
- **Impact**: The system MUST provide a config-level kill switch that switches all responses to abstention mode
- **Requirement Level**: MUST

### Deployment
**SELECTED**: 保持 docker-compose
- **Rationale**: 不引入新基础设施，首发稳定性优先
- **Impact**: The system MUST NOT require Kubernetes or new infrastructure for launch
- **Requirement Level**: MUST

### Monitoring
**SELECTED**: 复用现有 event_log + request_trace，加脚本 dashboard
- **Rationale**: 现有 trace 已足够，不需要 Prometheus
- **Impact**: The system SHOULD provide a monitoring script that analyzes existing traces for launch health
- **Requirement Level**: SHOULD

## 5. Test-Strategist Decisions

### Eval Calibration
**SELECTED**: 扩展现有 eval 到 60-80 样本，补充 semantic/coarse 类型
- **Rationale**: 在现有 43 样本基础上扩展，重点补薄弱 query 类型
- **Impact**: The eval dataset MUST contain at least 60 samples with balanced coverage of exact/fine/semantic/coarse query types
- **Requirement Level**: MUST

### Human Review
**SELECTED**: 抽样 20-30 个代表性样本，5桶分桶复核
- **Rationale**: 半天可完成，覆盖各类结果
- **Impact**: The launch evidence package MUST include 5-bucket human review results: correct, abstained, unsupported-query, wrong-with-citation, permission-boundary-failure
- **Requirement Level**: MUST

### Evidence Gate
**SELECTED**: Retrieval score 门控，在 chat 层实装
- **Rationale**: 最直接，不增加延迟和成本，不动 retrieval 内部
- **Impact**: The chat service MUST implement score threshold validation; responses below threshold MUST trigger guided abstention
- **Requirement Level**: MUST

## 6. Product-Manager Decisions

### Abstention Strategy
**SELECTED**: 引导式拒答，提供 query 改写建议和示例问题
- **Rationale**: 用户感受更好，帮助用户理解系统边界
- **Impact**: The system MUST provide query reformulation suggestions when abstaining; the UI SHOULD show example questions the system can handle
- **Requirement Level**: MUST (suggestions), SHOULD (examples)

### Citation Display
**SELECTED**: 文档名 + 段落摘要，可展开查看
- **Rationale**: 最实用的最小前端改动，信息量足够
- **Impact**: The UI MUST display document name and paragraph summary for each citation; the UI MAY support expand-to-full-text
- **Requirement Level**: MUST (name+summary), MAY (expand)

### Product Positioning
**SELECTED**: 明确定位为"文档问答系统"
- **Rationale**: 设定正确预期，避免用户当通用助手用
- **Impact**: The system MUST communicate its positioning as a document-grounded Q&A system, not a general assistant
- **Requirement Level**: MUST

## 7. Data-Architect Decisions

### Corpus Locking
**SELECTED**: 自动导出 corpus-manifest.json
- **Rationale**: 自动校验一致性，作为 bundle 的一部分冻结
- **Impact**: The system MUST export corpus manifest including document list, chunk counts, and content hashes
- **Requirement Level**: MUST

### ACL Seed
**SELECTED**: 导出 ACL 快照到 acl-seed.json
- **Rationale**: 评估和上线必须用同一份 ACL 配置
- **Impact**: The system MUST export current ACL rules as a snapshot; eval and production MUST use the same ACL seed
- **Requirement Level**: MUST

### Index Version
**SELECTED**: 记录 collection 名 + embedding model 版本
- **Rationale**: 简单且足够追踪索引一致性
- **Impact**: The launch bundle MUST record Qdrant collection name and embedding model version
- **Requirement Level**: MUST

## 8. Cross-Role Integration

### Bundle Freeze ↔ Data Artifacts
The bundle freeze script MUST integrate corpus manifest, ACL snapshot, and index version recording into a single launch-bundle.json file. Data-architect artifacts are inputs to system-architect's bundle freeze mechanism.

### Evidence Gate ↔ Abstention Display
The evidence gate (test-strategist) determines WHEN to abstain; the guided abstention (product-manager) determines HOW to communicate it. Both MUST be coordinated: score threshold triggers abstention, UI shows guidance.

### Eval ↔ Bundle
The calibration eval MUST run against the frozen bundle. If the bundle changes, the eval MUST be re-run. This creates a hard dependency: bundle freeze → eval → human review → go/no-go.

### Monitoring ↔ Kill Switch
The monitoring dashboard (system-architect) SHOULD trigger alerts when metrics degrade; the kill switch (system-architect) provides the emergency response. Both are part of the post-launch safety net.

## 9. Risks & Constraints

| Risk | Mitigation | Level |
|------|-----------|-------|
| 1周时间窗太紧，可能无法完成全部 8 个 feature | 按优先级排序：evidence-gate > bundle-freeze > eval > human-review > citation > abstention > kill-switch > monitoring | Critical |
| Eval 扩展到 60-80 样本可能暴露更多问题 | 这是好事——首发前发现问题比上线后发现好 | Medium |
| 全量发布意味着没有灰度缓冲 | kill switch 提供紧急关停能力；首发定位清晰降低用户预期风险 | High |
| 前端最小改动可能不够 | citation + abstention 是硬性要求，其余可延后 | Medium |
| Corpus/Index/ACL 冻结后变更导致 evidence package 失效 | 冻结后任何变更 MUST 触发重新评估 | Critical |

## 10. Feature Decomposition

| Feature ID | Name | Description | Related Roles | Priority |
|------------|------|-------------|---------------|----------|
| F-001 | evidence-gate | Chat 层 score threshold + citation 验证门控，不动 retrieval 内部 | test-strategist, system-architect | High |
| F-002 | bundle-freeze | 脚本自动冻结 commit/config/corpus/index/ACL 为 launch-bundle.json | system-architect, data-architect | High |
| F-003 | eval-calibration | 扩展 eval 到 60-80 样本，补充 semantic/coarse 类型 | test-strategist | High |
| F-004 | human-review | 20-30 样本的 5 桶人工复核 | test-strategist, product-manager | High |
| F-005 | citation-display | 前端最小改动：文档名+段落摘要展示 | product-manager | Medium |
| F-006 | guided-abstention | 前端拒答引导：query 改写建议 + 示例问题 | product-manager | Medium |
| F-007 | kill-switch | 配置级紧急关停开关 + 回滚清单文档 | system-architect | Medium |
| F-008 | monitoring-dashboard | 复用现有 trace 的监控脚本 | system-architect | Low |

## 11. Post-Launch Optimization Path

首发后继续按仓库既定主线推进（不倒序）：

1. **Supplemental 校准** — 调整跨部门补充检索的行为
2. **Chunk 优化** — 改善 citation 粒度和语义匹配
3. **Router / Hybrid 权重优化** — 调整检索策略路由
4. **Rerank 默认路由优化** — 优化重排序模型选择

首发方案保留这些优化空间：
- Retrieval service 内部逻辑未被首发方案改动
- 前端 citation 展示可逐步增强（原始高亮跳转等）
- Evidence gate 可从 score threshold 升级为 LLM 自我评估
- 部署可从 docker-compose 迁移到 K8s
- 监控可从脚本迁移到 Prometheus + Grafana

## Appendix: Decision Tracking

| Decision ID | Category | Question | Selected | Phase | Rationale |
|-------------|----------|----------|----------|-------|-----------|
| D-001 | Intent | 距首发最近阻碍 | 评估链不完整 | 1 | eval 是 threshold experiment，不是最终 calibration |
| D-002 | Intent | 首发范围 | 全量发布 | 1 | 目标用户为所有目标用户 |
| D-003 | Intent | 时间窗口 | 1周内 | 1 | 需要尽快上线 |
| D-004 | sys-arch | Bundle freeze | 脚本自动化 | 3 | 1-2天可完成，自动校验 |
| D-005 | sys-arch | 回滚策略 | 配置级 kill switch | 3 | 最快实装 |
| D-006 | sys-arch | 部署方式 | 保持 docker-compose | 3 | 不引入新基础设施 |
| D-007 | test | Eval calibration | 扩展现有 eval | 3 | 补充 semantic/coarse |
| D-008 | test | 人工复核 | 抽样 20-30 个 | 3 | 半天可完成 |
| D-009 | test | Evidence gate | Retrieval score 门控 | 3 | 最直接，不增加延迟 |
| D-010 | pm | 拒答策略 | 引导式拒答 | 3 | 用户感受更好 |
| D-011 | pm | Citation 展示 | 文档名+段落摘要 | 3 | 最小前端改动 |
| D-012 | pm | 产品定位 | 明确定位文档问答 | 3 | 设定正确预期 |
| D-013 | data | Corpus 锁定 | 自动导出 manifest | 3 | 自动校验一致性 |
| D-014 | data | ACL seed | 导出 ACL 快照 | 3 | 评估和上线一致 |
| D-015 | data | Index 版本 | 记录 collection + model | 3 | 简单且足够 |
| D-016 | supplement | Retrieval 优化边界 | 不动 retrieval，只加门控 | 4.5 | 保留后续优化空间 |
| D-017 | supplement | 前端范围 | 最小改动 | 4.5 | 1周时间限制 |
| D-018 | supplement | 监控粒度 | 复用现有 trace | 4.5 | 不需要新基础设施 |
