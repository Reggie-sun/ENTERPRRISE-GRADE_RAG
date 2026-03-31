# Enterprise-grade RAG

企业级检索增强生成（RAG）系统，包含后端 FastAPI 服务 + 前端 React 应用。

## 快速开始

### 环境准备

1. Python 3.11 + Conda 环境 `rag_backend`（见 [LOCAL_DEV_RUNBOOK.md](LOCAL_DEV_RUNBOOK.md)）
2. Node.js（前端开发）
3. 外部服务：Qdrant、Redis、Embedding、LLM（详见 `.env` 配置）

### 统一命令

项目根目录提供 `Makefile` 统一入口：

| 命令 | 说明 |
|------|------|
| `make dev` | 同时启动 API + Worker + 前端（开发模式） |
| `make dev-api` | 仅启动后端 API（端口 8020，热重载） |
| `make dev-worker` | 仅启动 Celery Worker |
| `make dev-frontend` | 仅启动前端开发服务器（端口 3000） |
| `make test` | 运行后端 pytest + 前端 lint |
| `make test-backend` | 仅运行后端测试 |
| `make test-frontend` | 仅运行前端 lint |
| `make test-smoke` | 运行 v0.1 主链路 smoke test（需要先启动 API） |
| `make test-smoke-v02` | 运行 v0.2 文档管理 smoke test |
| `make lint` | 前端 ESLint + 后端 ruff |
| `make build` | 生产构建：前端打包 + Docker 镜像 |
| `make build-fe` | 仅前端生产打包 |
| `make build-docker` | 仅构建 Docker 镜像 |
| `make install` | 安装前端依赖 |
| `make clean` | 清理生成产物（dist、__pycache__、.pytest_cache） |
| `make help` | 显示所有可用命令 |

> **提示：** 所有 `make dev-*` 命令会占用当前终端。建议开多个终端分别运行，或使用 tmux。
>
> 可通过环境变量覆盖默认配置：`make dev-api API_PORT=9000 CONDA_ENV=myenv`

### Docker Compose

一键启动 API + Worker（本地基础设施仍使用 `.env` 中的远程地址）：

```bash
docker compose up -d          # 启动
docker compose ps             # 状态
docker compose logs -f api    # 查看日志
docker compose down           # 停止
```

### 验证

```bash
# 健康检查
curl http://127.0.0.1:8020/api/v1/health

# 一键 smoke test
make test-smoke
```

## 项目结构

```
├── backend/           # FastAPI 后端（Python 3.11）
│   ├── app/           # 应用主体（routes, services, models）
│   └── tests/         # pytest 测试套件
├── frontend/          # React + Vite 前端
│   └── src/           # 页面和组件
├── scripts/           # 工具脚本（smoke test、backfill 等）
├── requirements/      # Python 依赖（分模块管理）
├── docker/            # Docker 相关配置
├── prisma/            # 数据库 schema
├── docker-compose.yml # 本地开发 Compose
├── Makefile           # 统一命令入口
└── .env               # 环境变量
```

## 更多文档

- [本地开发手册](LOCAL_DEV_RUNBOOK.md)
- [Worker 运行手册](backend/WORKER_RUNBOOK.md)
- [本地模型部署](backend/LOCAL_MODEL_RUNBOOK.md)
- [PostgreSQL 元数据迁移](backend/POSTGRES_METADATA_MIGRATION.md)
- [架构说明](RAG架构.md)
- [V1 计划](V1_PLAN.md)
