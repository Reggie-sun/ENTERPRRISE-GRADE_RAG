# V1 Release / V1 发布说明

## Status / 状态

V1 is ready to freeze as a "minimum closed-loop backend" release.
V1 已准备好作为"最小闭环后端"版本冻结。

This release means the project has completed the `document -> ingest -> retrieval -> answer` path in a single-node development environment. It does not mean the full enterprise feature set is complete.
本次发布意味着项目已在单机开发环境下完成了 `文档 -> 入库 -> 检索 -> 回答` 的完整链路。这并不代表企业级全部功能已完成。

## Included In V1 / V1 包含内容

- FastAPI API skeleton and routed endpoints / FastAPI API 骨架和路由端点
- Document upload and metadata persistence / 文档上传和元数据持久化
- Real async ingest with `Celery + Redis` / 使用 `Celery + Redis` 的真实异步入库
- Ingest job status query / 入库任务状态查询
- Manual job re-run endpoint: `POST /api/v1/ingest/jobs/{job_id}/run` / 手动重跑任务端点
- Retry-limit and `dead_letter` terminal semantics / 重试上限和 `dead_letter` 终态语义
- Document parsing for `PDF / Markdown / TXT` / 支持 `PDF / Markdown / TXT` 文档解析
- Chunking, embedding, vector upsert, retrieval, rerank, chat answer, citations / 切块、向量化、向量写入、检索、重排、问答生成、引用返回
- Worker runbook and ingest state-machine docs / Worker 运行手册和入库状态机文档

## Verification / 验证结果

Verified on `2026-03-20` in local development:
于 `2026-03-20` 在本地开发环境验证通过：

- Swagger MCP test passed for `POST /api/v1/documents` / 文档创建接口测试通过
- Swagger MCP test passed for `GET /api/v1/ingest/jobs/{job_id}` / 任务状态查询接口测试通过
- Swagger MCP test passed for `POST /api/v1/ingest/jobs/{job_id}/run` / 手动重跑接口测试通过
- `pytest -q` passed: `24 passed` / 单元测试全部通过

## Explicitly Out Of Scope / 明确不在 V1 范围内

The following are not part of the V1 release gate:
以下内容不属于 V1 发布门槛：

- ACL filtering / ACL 权限过滤
- BM25 / RRF hybrid retrieval / BM25 / RRF 混合检索
- OCR and Office deep parsing / OCR 和 Office 深度解析
- Multi-tenant enterprise controls / 多租户企业级管控
- High-concurrency tuning / 高并发调优
- Full admin console / 完整管理后台
- Distributed scheduling / 分布式调度

## Tagging Rule / 打标签规则

Do not tag V1 from a dirty worktree.
不要从脏工作区打 V1 标签。

Recommended release sequence:
推荐的发布流程：

1. Review local modifications / 检查本地修改
2. Commit the V1 freeze state / 提交 V1 冻结状态
3. Create a tag such as `v0.1.0` or `v1-mvp` / 创建标签，如 `v0.1.0` 或 `v1-mvp`
4. Keep post-V1 work on a new commit after the tag / 在标签之后的新提交中继续 V1 后续工作
