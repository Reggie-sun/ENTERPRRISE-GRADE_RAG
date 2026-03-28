from functools import lru_cache

from ..core.config import Settings, get_llm_base_url, get_llm_model, get_postgres_metadata_dsn, get_settings
from ..rag.rerankers.client import RerankerClient
from ..rag.ocr.client import OCRClient
from ..schemas.health import HealthResponse
from .system_config_service import SystemConfigService


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
        return HealthResponse(
            status="ok",
            app_name=settings.app_name,
            environment=settings.app_env,
            vector_store={
                "provider": "qdrant",
                "url": settings.qdrant_url,
                "collection": settings.qdrant_collection,
            },
            llm={
                "provider": settings.llm_provider,
                "base_url": get_llm_base_url(settings) if settings.llm_provider.lower().strip() != "mock" else "",
                "model": "mock" if settings.llm_provider.lower().strip() == "mock" else get_llm_model(settings),
            },
            embedding={
                "provider": settings.embedding_provider,
                "base_url": settings.embedding_base_url or settings.ollama_base_url,
                "model": settings.embedding_model,
            },
            reranker={
                "provider": reranker_status["provider"],
                "base_url": reranker_status["base_url"],
                "model": reranker_status["model"],
                "default_strategy": reranker_status["default_strategy"],
                "timeout_seconds": reranker_status["timeout_seconds"],
                "failure_cooldown_seconds": reranker_status["failure_cooldown_seconds"],
                "effective_provider": reranker_status["effective_provider"],
                "effective_model": reranker_status["effective_model"],
                "effective_strategy": reranker_status["effective_strategy"],
                "fallback_enabled": reranker_status["fallback_enabled"],
                "lock_active": reranker_status["lock_active"],
                "lock_source": reranker_status["lock_source"],
                "cooldown_remaining_seconds": reranker_status["cooldown_remaining_seconds"],
                "ready": reranker_status["ready"],
                "detail": reranker_status["detail"],
            },
            queue={
                "provider": "celery",
                "broker_url": settings.celery_broker_url,
                "result_backend": settings.celery_result_backend,
                "ingest_queue": settings.celery_ingest_queue,
            },
            metadata_store={
                "provider": "postgres" if settings.postgres_metadata_enabled else "local_json",
                "postgres_enabled": settings.postgres_metadata_enabled,
                "dsn_configured": bool(get_postgres_metadata_dsn(settings)),
            },
            ocr=OCRClient(settings).get_runtime_status(),
        )


@lru_cache
def get_health_service() -> HealthService:
    return HealthService()
