from backend.app.core.config import Settings
from backend.app.services.retrieval_query_router import RetrievalQueryRouter


def test_query_router_classifies_exact_queries() -> None:
    router = RetrievalQueryRouter(Settings(_env_file=None, retrieval_dynamic_weighting_enabled=True))

    classification = router.classify("PLC_A01错误")

    assert classification.query_type == "exact"
    assert classification.exact_signals >= 2


def test_query_router_classifies_semantic_queries() -> None:
    router = RetrievalQueryRouter(Settings(_env_file=None, retrieval_dynamic_weighting_enabled=True))

    classification = router.classify("为什么设备夜班频繁停机")

    assert classification.query_type == "semantic"
    assert classification.semantic_signals >= 2


def test_query_router_classifies_mixed_queries() -> None:
    router = RetrievalQueryRouter(Settings(_env_file=None, retrieval_dynamic_weighting_enabled=True))

    classification = router.classify("SOP-1024夜班停机原因")

    assert classification.query_type == "mixed"
    assert classification.exact_signals >= 2
    assert classification.semantic_signals >= 2


def test_query_router_uses_fixed_fallback_when_dynamic_weighting_is_disabled() -> None:
    router = RetrievalQueryRouter(Settings(_env_file=None, retrieval_dynamic_weighting_enabled=False))

    weights = router.resolve_branch_weights("Qwen2.5-32B")

    assert weights.query_type == "fixed"
    assert weights.dynamic_enabled is False
    assert weights.vector_weight == 1.0
    assert weights.lexical_weight == 1.0
