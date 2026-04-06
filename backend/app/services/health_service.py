"""健康检查服务模块。检测各依赖组件（Qdrant、数据库等）的可用性状态。"""
from functools import lru_cache

from ..core.config import Settings, get_llm_base_url, get_llm_model, get_postgres_metadata_dsn, get_settings
from ..rag.rerankers.client import RerankerClient
from ..rag.ocr.client import OCRClient
from ..schemas.health import (
    HealthEmbedding,
    HealthLLM,
    HealthMetadataStore,
    HealthOCR,
    HealthQueue,
    HealthReranker,
    HealthResponse,
    HealthTokenizer,
    HealthVectorStore,
)
from .system_config_service import SystemConfigService
from .token_budget_service import TokenBudgetService


class HealthService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        system_config_service: SystemConfigService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.system_config_service = system_config_service or SystemConfigService(self.settings)

    def get_snapshot(self) -> HealthResponse:
        settings = self.settings
        reranker_status = RerankerClient(settings, system_config_service=self.system_config_service).get_runtime_status()
        tokenizer_status = TokenBudgetService(settings).get_runtime_info(model_name=get_llm_model(settings))
        ocr_status = OCRClient(settings).get_runtime_status()
        return HealthResponse(
            status="ok",
            app_name=settings.app_name,
            environment=settings.app_env,
            vector_store=HealthVectorStore(
                provider="qdrant",
                url=settings.qdrant_url,
                collection=settings.qdrant_collection,
            ),
            llm=HealthLLM(
                provider=settings.llm_provider,
                base_url=get_llm_base_url(settings) if settings.llm_provider.lower().strip() != "mock" else "",
                model="mock" if settings.llm_provider.lower().strip() == "mock" else get_llm_model(settings),
            ),
            embedding=HealthEmbedding(
                provider=settings.embedding_provider,
                base_url=settings.embedding_base_url or settings.ollama_base_url,
                model=settings.embedding_model,
            ),
            reranker=HealthReranker(
                provider=str(reranker_status["provider"]),
                base_url=str(reranker_status["base_url"]),
                model=str(reranker_status["model"]),
                default_strategy=str(reranker_status["default_strategy"]),
                timeout_seconds=float(reranker_status["timeout_seconds"]),
                failure_cooldown_seconds=float(reranker_status["failure_cooldown_seconds"]),
                effective_provider=str(reranker_status["effective_provider"]),
                effective_model=str(reranker_status["effective_model"]),
                effective_strategy=str(reranker_status["effective_strategy"]),
                fallback_enabled=bool(reranker_status["fallback_enabled"]),
                lock_active=bool(reranker_status["lock_active"]),
                lock_source=str(reranker_status["lock_source"]) if isinstance(reranker_status["lock_source"], str) else None,
                cooldown_remaining_seconds=float(reranker_status["cooldown_remaining_seconds"]),
                ready=bool(reranker_status["ready"]),
                detail=str(reranker_status["detail"]) if isinstance(reranker_status["detail"], str) else None,
            ),
            queue=HealthQueue(
                provider="celery",
                broker_url=settings.celery_broker_url,
                result_backend=settings.celery_result_backend,
                ingest_queue=settings.celery_ingest_queue,
            ),
            metadata_store=HealthMetadataStore(
                provider="postgres" if settings.postgres_metadata_enabled else "local_json",
                postgres_enabled=settings.postgres_metadata_enabled,
                dsn_configured=bool(get_postgres_metadata_dsn(settings)),
            ),
            ocr=HealthOCR(
                provider=str(ocr_status["provider"]),
                language=str(ocr_status["language"]),
                enabled=bool(ocr_status["enabled"]),
                ready=bool(ocr_status["ready"]),
                pdf_native_text_min_chars=int(ocr_status["pdf_native_text_min_chars"]),
                angle_cls_enabled=bool(ocr_status["angle_cls_enabled"]),
                detail=str(ocr_status["detail"]) if isinstance(ocr_status["detail"], str) else None,
            ),
            tokenizer=HealthTokenizer(
                provider=str(tokenizer_status["provider"]),
                model=str(tokenizer_status["model"]),
                ready=bool(tokenizer_status["ready"]),
                trust_remote_code=settings.tokenizer_trust_remote_code,
                detail=str(tokenizer_status["detail"]) if isinstance(tokenizer_status["detail"], str) else None,
                error=str(tokenizer_status["error"]) if isinstance(tokenizer_status["error"], str) else None,
            ),
        )


@lru_cache
def get_health_service() -> HealthService:
    return HealthService()
