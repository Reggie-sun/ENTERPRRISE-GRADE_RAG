from types import SimpleNamespace

from backend.app.rag.retrievers.lexical_retriever import QdrantLexicalRetriever


class _FakeVectorStore:
    def __init__(self, records: list[object]) -> None:
        self.records = records

    def scroll_records(self, *, document_id=None, batch_size=256):
        del document_id, batch_size
        yield from self.records


def test_lexical_retriever_uses_primary_segmenter_and_supplemental_bigrams() -> None:
    retriever = QdrantLexicalRetriever(
        _FakeVectorStore([]),
        chinese_segmenter=lambda text: ["设备", "异常", "处理"] if text == "设备异常处理" else [text],
    )

    tokenized = retriever._tokenize("设备异常处理")

    assert tokenized.primary_tokens == ["设备", "异常", "处理"]
    assert tokenized.supplemental_tokens == ["设备", "备异", "异常", "常处", "处理"]


def test_lexical_retriever_falls_back_to_bigrams_when_primary_segmenter_is_unavailable() -> None:
    retriever = QdrantLexicalRetriever(
        _FakeVectorStore([]),
        chinese_segmenter=lambda text: [],
    )

    tokenized = retriever._tokenize("设备异常处理")

    assert tokenized.primary_tokens == ["设备", "备异", "异常", "常处", "处理"]
    assert tokenized.supplemental_tokens == []


def test_lexical_retriever_supports_bigram_only_mode() -> None:
    retriever = QdrantLexicalRetriever(
        _FakeVectorStore([]),
        chinese_tokenizer_mode="bigram_only",
    )

    tokenized = retriever._tokenize("设备异常处理")

    assert tokenized.primary_tokens == ["设备", "备异", "异常", "常处", "处理"]
    assert tokenized.supplemental_tokens == []


def test_lexical_retriever_supplemental_bigrams_rescue_partial_chinese_match() -> None:
    retriever = QdrantLexicalRetriever(
        _FakeVectorStore(
            [
                SimpleNamespace(
                    id="point-1",
                    payload={
                        "chunk_id": "chunk-1",
                        "document_id": "doc-1",
                        "text": "异常处理流程",
                    },
                )
            ]
        ),
        chinese_segmenter=lambda text: [text],
    )

    matches = retriever.search("设备异常处理", limit=3)

    assert [item.point_id for item in matches] == ["point-1"]
    assert matches[0].score > 0
