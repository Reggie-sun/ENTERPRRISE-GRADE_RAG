from collections import Counter
from dataclasses import dataclass
import math
import re

from ..vectorstores.qdrant_store import QdrantVectorStore

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")


@dataclass(frozen=True)
class LexicalMatch:
    point_id: str
    payload: dict[str, object]
    score: float


class QdrantLexicalRetriever:
    _SCROLL_BATCH_SIZE = 256

    def __init__(self, vector_store: QdrantVectorStore, *, k1: float = 1.5, b: float = 0.75) -> None:
        self.vector_store = vector_store
        self.k1 = k1
        self.b = b

    def search(
        self,
        query: str,
        *,
        limit: int,
        document_id: str | None = None,
    ) -> list[LexicalMatch]:
        normalized_query = query.strip()
        if not normalized_query or limit <= 0:
            return []
        if not hasattr(self.vector_store, "scroll_records"):
            return []

        query_tokens = self._tokenize(normalized_query)
        if not query_tokens:
            return []

        query_counter = Counter(query_tokens)
        query_token_set = set(query_counter)
        corpus_size = 0
        total_doc_length = 0
        document_frequency: Counter[str] = Counter()
        matched_records: list[tuple[object, Counter[str], int]] = []

        try:
            for record in self.vector_store.scroll_records(document_id=document_id, batch_size=self._SCROLL_BATCH_SIZE):
                payload = dict(record.payload or {})
                text = str(payload.get("text") or "")
                doc_tokens = self._tokenize(text)
                if not doc_tokens:
                    continue

                corpus_size += 1
                doc_length = len(doc_tokens)
                total_doc_length += doc_length
                term_frequency = Counter(doc_tokens)
                matched_terms = Counter({token: term_frequency[token] for token in query_token_set if term_frequency[token] > 0})
                if not matched_terms:
                    continue
                matched_records.append((record, matched_terms, doc_length))
                for token in matched_terms:
                    document_frequency[token] += 1
        except Exception as exc:  # pragma: no cover - 由 RetrievalService 兜底退回纯向量检索。
            raise RuntimeError(f"Lexical retrieval failed: {exc}") from exc

        if corpus_size <= 0 or not matched_records:
            return []

        average_doc_length = total_doc_length / corpus_size if total_doc_length > 0 else 1.0
        scored_matches: list[LexicalMatch] = []
        for record, matched_terms, doc_length in matched_records:
            score = self._bm25_score(
                query_counter=query_counter,
                matched_terms=matched_terms,
                document_frequency=document_frequency,
                corpus_size=corpus_size,
                doc_length=doc_length,
                average_doc_length=average_doc_length,
            )
            if score <= 0:
                continue
            scored_matches.append(
                LexicalMatch(
                    point_id=str(record.id),
                    payload=dict(record.payload or {}),
                    score=score,
                )
            )

        scored_matches.sort(key=lambda item: item.score, reverse=True)
        return scored_matches[:limit]

    def _bm25_score(
        self,
        *,
        query_counter: Counter[str],
        matched_terms: Counter[str],
        document_frequency: Counter[str],
        corpus_size: int,
        doc_length: int,
        average_doc_length: float,
    ) -> float:
        score = 0.0
        normalization = 1 - self.b + self.b * (doc_length / max(average_doc_length, 1.0))
        for token, query_term_frequency in query_counter.items():
            term_frequency = matched_terms.get(token, 0)
            if term_frequency <= 0:
                continue
            doc_frequency = document_frequency.get(token, 0)
            inverse_document_frequency = math.log(1 + (corpus_size - doc_frequency + 0.5) / (doc_frequency + 0.5))
            denominator = term_frequency + self.k1 * normalization
            score += query_term_frequency * (inverse_document_frequency * term_frequency * (self.k1 + 1) / max(denominator, 1e-9))
        return score

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        tokens: list[str] = []
        for raw_token in TOKEN_PATTERN.findall(text.lower()):
            if raw_token.isascii():
                tokens.append(raw_token)
                continue
            if len(raw_token) == 1:
                tokens.append(raw_token)
                continue
            tokens.extend(raw_token[index : index + 2] for index in range(len(raw_token) - 1))
        return tokens
