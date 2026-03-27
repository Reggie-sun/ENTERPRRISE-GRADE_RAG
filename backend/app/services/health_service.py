from functools import lru_cache

from ..core.config import Settings, get_llm_base_url, get_llm_model, get_postgres_metadata_dsn, get_settings
from ..schemas.health import HealthResponse


class HealthService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def get_snapshot(self) -> HealthResponse:
        settings = self.settings
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
        )


@lru_cache
def get_health_service() -> HealthService:
    return HealthService()
