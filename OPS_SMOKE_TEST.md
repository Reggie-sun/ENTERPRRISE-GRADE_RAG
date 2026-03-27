# OPS Smoke Test

这份清单用于快速验证 `v0.6` 已落地的运行侧能力是否可用。

目标不是验证“答案是不是最优”，而是验证下面 4 件事：

- 能不能看到请求链路发生了什么
- 能不能看到系统什么时候开始变坏
- 能不能确认配置改动真实生效
- 能不能对历史请求做最小可复现重放

建议测试账号：

- 系统管理员：`sys.admin.demo / sys-admin-demo-pass`

建议前置条件：

- 本地前端已启动：`http://127.0.0.1:3000`
- 本地 `api / worker` 已启动
- 远端 `vLLM / embedding / qdrant / redis` 正常

---

## 1. 智能问答 Trace

1. 登录系统管理员账号
2. 打开 `/workspace/chat`
3. 连续提 2 个问题：
   - `什么是悖论放松法`
   - `详细解释一下悖论放松法，并给出练习步骤`
4. 打开 `/workspace/ops`

预期结果：

- `最近请求 Trace` 里出现刚才的新记录
- 每条请求至少能看到：
  - `query_rewrite`
  - `retrieval`
  - `rerank`
  - `llm`
  - `answer`
- 能看到每一步的 `status / duration_ms / input_size / output_size`
- 大多数情况下 `llm` 会是最慢的一步

如果失败：

- 没有新 trace：先查 `/workspace/logs`
- 只有 `retrieval` 没结果：检查文档是否已入库
- `llm` 直接失败：检查 `.env` 里的 LLM provider / model / base_url

---

## 2. 智能问答 Snapshot / Replay

1. 继续停留在 `/workspace/ops`
2. 下滑到 `最近请求快照与重放`
3. 找到刚才的 chat 请求
4. 先点 `原样重放`
5. 再点 `当前配置重放`

预期结果：

- 卡片内出现 `最近一次重放`
- 能看到：
  - `重放方式`
  - `状态`
  - `mode`
  - `top_k`
  - `response`
  - 重放结果文本

说明：

- `原样重放` 用当时请求真正生效的参数
- `当前配置重放` 用当前系统配置重新展开参数

---

## 3. 配置改动是否真的生效

1. 打开 `/workspace/admin`
2. 把 `fast.top_k` 从 `5` 改成 `8`
3. 保存
4. 回到 `/workspace/ops`
5. 对刚才那条 chat snapshot 点 `当前配置重放`

预期结果：

- `原样重放` 仍保留旧参数
- `当前配置重放` 使用新参数
- 如果结果文本、引用数或耗时变化，说明配置链路已生效

测试结束后建议恢复默认值：

- `fast.top_k = 5`

---

## 4. SOP 生成 Trace / Snapshot / Replay

1. 打开 `/portal/sop`
2. 上传一个小文档
3. 等待入库完成
4. 生成 SOP 草稿
5. 回到 `/workspace/ops`

预期结果：

- 分类汇总中 `sop_generation` 的计数增加
- `最近请求快照与重放` 里出现新的 `generate_document`
- 卡片中能看到：
  - `snapshot_id`
  - `trace_id`
  - `request_id`
  - `草稿预览`
- 点击 `原样重放` 后，卡片中出现 `最近一次重放`

如果失败：

- 先去 `/workspace/logs` 查 `category=sop_generation`
- 再看卡片中是否有失败原因或超时信息

---

## 5. 如何判断这次运行侧能力是“通过”的

通过标准：

- 新问答能产生 trace
- 新问答能产生 snapshot
- replay 成功且结果可见
- 修改配置后，`当前配置重放` 会受影响
- SOP 生成也能被 snapshot / replay
- 失败时可以在 `logs` 或 `ops` 找到对应记录

不通过信号：

- 问了问题但 `/workspace/ops` 没有新记录
- replay 按钮点了没反应
- 改配置后 `当前配置重放` 完全不变
- 失败了但日志和运行态都找不到记录

---

## 6. 这份清单对应的能力范围

当前覆盖：

- chat trace
- chat snapshot / replay
- SOP generation snapshot / replay
- 配置页修改 `fast / accurate / model routing / degrade / retry`
- 运行态页查看健康、积压、失败、降级

当前还不是完整 metrics / tracing 平台：

- 还没有正式 Prometheus / Grafana 大盘
- 还没有全链路分布式 trace 平台
- 还没有请求级下载导出或批量回放

这份 smoke test 的作用，是先确认 `v0.6` 已落的最小运行侧能力是真的活着。
