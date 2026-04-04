# ──────────────────────────────────────────────────────────
#  Enterprise RAG — Unified dev / test / build entry points
# ──────────────────────────────────────────────────────────
#
#  This Makefile provides a single surface for common workflows.
#  It delegates to the existing scripts inside frontend/ and backend/
#  without modifying them.
#
#  Quick reference:
#    make dev          – start backend API + worker + frontend (parallel)
#    make dev-api      – start backend API only
#    make dev-worker   – start Celery worker only
#    make dev-frontend – start frontend dev server only
#    make test         – run backend unit tests
#    make test-smoke   – run integration smoke tests (requires running API)
#    make lint         – lint frontend + backend
#    make build        – production build (frontend + docker images)
#    make build-fe     – frontend production build only
#    make clean        – remove generated artifacts
#    make help         – show all targets
#
#  Environment:
#    CONDA_ENV   – backend Conda environment name   (default: rag_backend)
#    API_PORT    – backend API port                  (default: 8020)
#    FE_PORT     – frontend dev server port          (default: 3000)
# ──────────────────────────────────────────────────────────

# Configurable variables ──────────────────────────────────
CONDA_ENV   ?= rag_backend
API_PORT    ?= 8020
FE_PORT     ?= 3000

# Helpers ─────────────────────────────────────────────────
# "conda run" wrapper – override CONDA_ENV if needed
conda-run = conda run -n $(CONDA_ENV)

# Colors (when stdout is a tty)
ifneq ($(TERM),dumb)
  _CYN  := \033[36m
  _GRN  := \033[32m
  _RED  := \033[31m
  _RST  := \033[0m
else
  _CYN  :=
  _GRN  :=
  _RED  :=
  _RST  :=
endif

# ── Dev targets ──────────────────────────────────────────

.PHONY: dev dev-api dev-worker dev-frontend

## Start everything: API + worker + frontend (all in foreground, Ctrl-C stops all)
dev: dev-api dev-worker dev-frontend

## Start backend API (uvicorn with reload)
dev-api:
	@printf "$(_CYN)▸ Starting API on :$(API_PORT) …$(_RST)\n"
	$(conda-run) uvicorn backend.app.main:app --host 0.0.0.0 --port $(API_PORT) --reload

## Start Celery worker
dev-worker:
	@printf "$(_CYN)▸ Starting Celery worker …$(_RST)\n"
	$(conda-run) celery -A backend.app.worker.celery_app:celery_app worker --loglevel=info -Q ingest

## Start frontend dev server
dev-frontend:
	@printf "$(_CYN)▸ Starting frontend on :$(FE_PORT) …$(_RST)\n"
	cd frontend && npm run dev -- --port $(FE_PORT)

# ── Test targets ─────────────────────────────────────────

.PHONY: test test-backend test-frontend test-smoke test-smoke-v02 eval-retrieval eval-baseline show-chunk-config

## Run all tests (backend unit + frontend lint)
test: test-backend test-frontend

## Run backend pytest suite
test-backend:
	@printf "$(_CYN)▸ Running backend tests …$(_RST)\n"
	$(conda-run) pytest backend/tests/ -v

## Run frontend lint (no test framework configured yet)
test-frontend:
	@printf "$(_CYN)▸ Running frontend lint …$(_RST)\n"
	cd frontend && npm run lint

## Run v0.1 smoke test (requires running API + worker)
test-smoke:
	@printf "$(_CYN)▸ Running smoke test v0.1 …$(_RST)\n"
	bash scripts/smoke_test.sh

## Run v0.2 document-management smoke test
test-smoke-v02:
	@printf "$(_CYN)▸ Running smoke test v0.2 …$(_RST)\n"
	bash scripts/smoke_test_v02.sh

## Run retrieval evaluation against curated samples (requires running API)
## Override credentials: AUTH_USERNAME=x AUTH_PASSWORD=y make eval-retrieval
eval-retrieval:
	@printf "$(_CYN)▸ Running retrieval evaluation …$(_RST)\n"
	$(conda-run) python scripts/eval_retrieval.py --api-base http://localhost:$(API_PORT)

## Run retrieval evaluation and save as tagged baseline
## Usage: make eval-baseline TAG=before_change
eval-baseline:
	@if [ -z "$(TAG)" ]; then \
		printf "$(_RED)ERROR: TAG is required. Usage: make eval-baseline TAG=name$(_RST)\n"; \
		exit 1; \
	fi
	@printf "$(_CYN)▸ Running eval baseline with tag '$(TAG)' …$(_RST)\n"
	$(conda-run) python scripts/eval_retrieval.py --api-base http://localhost:$(API_PORT) --results-dir eval/results --experiment-name $(TAG)
	@printf "$(_GRN)▸ Baseline saved to eval/results/baseline_$(TAG).json$(_RST)\n"

## Show current chunk configuration
show-chunk-config:
	@printf "$(_CYN)▸ Current chunk configuration$(_RST)\n"
	$(conda-run) python -c "from backend.app.core.config import get_settings; s=get_settings(); print(f'  chunk_size_chars: {s.chunk_size_chars}'); print(f'  chunk_overlap_chars: {s.chunk_overlap_chars}'); print(f'  chunk_min_chars: {s.chunk_min_chars}')"

# ── Lint targets ─────────────────────────────────────────

.PHONY: lint lint-fe lint-py

## Lint everything
lint: lint-fe lint-py

## Lint frontend (ESLint)
lint-fe:
	cd frontend && npm run lint

## Lint backend (ruff if installed, otherwise no-op)
lint-py:
	@command -v ruff >/dev/null 2>&1 && ruff check backend/ || printf "  (ruff not installed, skipping Python lint)\n"

# ── Build targets ────────────────────────────────────────

.PHONY: build build-fe build-docker

## Production build: frontend assets + Docker images
build: build-fe build-docker

## Build frontend production bundle
build-fe:
	@printf "$(_CYN)▸ Building frontend …$(_RST)\n"
	cd frontend && npm run build

## Build Docker images via docker compose
build-docker:
	@printf "$(_CYN)▸ Building Docker images …$(_RST)\n"
	docker compose build

# ── Utility targets ──────────────────────────────────────

.PHONY: clean install help

## Remove generated artifacts
clean:
	@printf "$(_GRN)▸ Cleaning frontend dist …$(_RST)\n"
	rm -rf frontend/dist
	@printf "$(_GRN)▸ Cleaning Python caches …$(_RST)\n"
	find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find backend -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@printf "$(_GRN)▸ Done.$(_RST)\n"

## Install frontend dependencies
install:
	cd frontend && npm install

## Show this help
help:
	@printf "\nUsage: make <target>\n\n"
	@printf "  $(_CYN)dev$(_RST)              Start API + worker + frontend\n"
	@printf "  $(_CYN)dev-api$(_RST)          Start backend API (port $(API_PORT), reload)\n"
	@printf "  $(_CYN)dev-worker$(_RST)       Start Celery worker\n"
	@printf "  $(_CYN)dev-frontend$(_RST)     Start frontend dev server (port $(FE_PORT))\n"
	@printf "\n"
	@printf "  $(_CYN)test$(_RST)             Run backend tests + frontend lint\n"
	@printf "  $(_CYN)test-backend$(_RST)     Run backend pytest suite\n"
	@printf "  $(_CYN)test-frontend$(_RST)    Run frontend lint\n"
	@printf "  $(_CYN)test-smoke$(_RST)       Run v0.1 smoke test (needs running API)\n"
	@printf "  $(_CYN)test-smoke-v02$(_RST)   Run v0.2 smoke test (needs running API)\n"
	@printf "  $(_CYN)eval-retrieval$(_RST)   Run retrieval evaluation (needs running API)\n"
	@printf "  $(_CYN)eval-baseline$(_RST)    Run eval and save as baseline (TAG=name)\n"
	@printf "  $(_CYN)show-chunk-config$(_RST) Show current chunk parameters\n"
	@printf "\n"
	@printf "  $(_CYN)lint$(_RST)             Lint frontend + backend\n"
	@printf "  $(_CYN)build$(_RST)            Production build (frontend + Docker)\n"
	@printf "  $(_CYN)build-fe$(_RST)         Frontend production build only\n"
	@printf "  $(_CYN)build-docker$(_RST)     Docker image build only\n"
	@printf "\n"
	@printf "  $(_CYN)install$(_RST)          Install frontend dependencies\n"
	@printf "  $(_CYN)clean$(_RST)            Remove generated artifacts\n"
	@printf "\n"
	@printf "Variables: CONDA_ENV=$(CONDA_ENV)  API_PORT=$(API_PORT)  FE_PORT=$(FE_PORT)\n"
