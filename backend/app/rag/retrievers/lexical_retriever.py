"""词法检索器，基于 Qdrant 全文索引实现关键词召回。

通过 scroll 遍历 collection 中的 payload，对 query 和文档文本做 BM25 评分，
支持中英文混合分词（jieba/pkuseg），并自动生成补充 bigram token 提升中文召回效果。
"""
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
import math
import re
from typing import Callable

from ..vectorstores.qdrant_store import QdrantVectorStore

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
SUPPLEMENTAL_BIGRAM_WEIGHT = 0.35
DEFAULT_CHINESE_TOKENIZER_MODE = "jieba_search"


@dataclass(frozen=True)
class LexicalMatch:
    """词法检索命中文档，包含 Qdrant point ID、payload 和 BM25 得分。"""
    point_id: str
    payload: dict[str, object]
    score: float


@dataclass(frozen=True)
class _TokenizedText:
    """分词结果：primary_tokens 为主分词，supplemental_tokens 为补充 bigram token。"""
    primary_tokens: list[str]
    supplemental_tokens: list[str]


@lru_cache(maxsize=4)
def _load_chinese_segmenter(mode: str) -> Callable[[str], list[str]] | None:
    """按配置加载中文分词器，支持 jieba（search/precise）和 pkuseg，bigram_only 时返回 None。"""
    normalized_mode = mode.strip().lower() or DEFAULT_CHINESE_TOKENIZER_MODE
    if normalized_mode == "bigram_only":
        return None
    if normalized_mode == "pkuseg":
        try:
            import pkuseg
        except ImportError:
            return None

        segmenter = pkuseg.pkuseg()

        def segment(text: str) -> list[str]:
            return [token.strip().lower() for token in segmenter.cut(text) if token and token.strip()]

        return segment

    try:
        import jieba
    except ImportError:
        return None

    def segment(text: str) -> list[str]:
        if normalized_mode == "jieba_precise":
            tokens = jieba.lcut(text, HMM=True)
        else:
            tokens = jieba.cut_for_search(text, HMM=True)
        return [token.strip().lower() for token in tokens if token and token.strip()]

    return segment


class QdrantLexicalRetriever:
    """基于 BM25 的词法检索器，通过 scroll 遍历 Qdrant payload 并计算相关性得分。

    支持中英文混合分词，自动为中文文本生成补充 bigram token，
    并可按 document_id 或 document_ids 过滤检索范围。
    """

    _SCROLL_BATCH_SIZE = 256

    def __init__(
        self,
        vector_store: QdrantVectorStore,
        *,
        k1: float = 1.5,
        b: float = 0.75,
        chinese_segmenter: Callable[[str], list[str]] | None = None,
        chinese_tokenizer_mode: str = DEFAULT_CHINESE_TOKENIZER_MODE,
        supplemental_bigram_weight: float = SUPPLEMENTAL_BIGRAM_WEIGHT,
    ) -> None:
        """初始化词法检索器。

        Args:
            vector_store: QdrantVectorStore 实例，用于 scroll 遍历 payload。
            k1: BM25 参数 k1，控制词频饱和速度。
            b: BM25 参数 b，控制文档长度归一化强度。
            chinese_segmenter: 可选的自定义中文分词函数。
            chinese_tokenizer_mode: 中文分词模式（jieba_search / jieba_precise / pkuseg / bigram_only）。
            supplemental_bigram_weight: 补充 bigram 得分的权重系数。
        """
        self.vector_store = vector_store
        self.k1 = k1
        self.b = b
        self.chinese_tokenizer_mode = chinese_tokenizer_mode.strip().lower() or DEFAULT_CHINESE_TOKENIZER_MODE
        self.chinese_segmenter = (
            chinese_segmenter
            if chinese_segmenter is not None
            else _load_chinese_segmenter(self.chinese_tokenizer_mode)
        )
        self.supplemental_bigram_weight = max(0.0, supplemental_bigram_weight)

    def search(
        self,
        query: str,
        *,
        limit: int,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[LexicalMatch]:
        """执行词法检索：scroll 遍历 payload，计算 BM25 得分并返回排名靠前的命中文档。"""
        normalized_query = query.strip()
        if not normalized_query or limit <= 0:
            return []
        if not hasattr(self.vector_store, "scroll_records"):
            return []

        query_tokens = self._tokenize(normalized_query)
        query_primary_counter = Counter(query_tokens.primary_tokens)
        query_supplemental_counter = Counter(query_tokens.supplemental_tokens)
        if not query_primary_counter and not query_supplemental_counter:
            return []

        query_primary_token_set = set(query_primary_counter)
        query_supplemental_token_set = set(query_supplemental_counter)
        primary_corpus_size = 0
        supplemental_corpus_size = 0
        primary_total_doc_length = 0
        supplemental_total_doc_length = 0
        primary_document_frequency: Counter[str] = Counter()
        supplemental_document_frequency: Counter[str] = Counter()
        matched_records: list[tuple[object, Counter[str], int, Counter[str], int]] = []

        try:
            scroll_kwargs: dict[str, object] = {"batch_size": self._SCROLL_BATCH_SIZE}
            if document_id is not None:
                scroll_kwargs["document_id"] = document_id
            if document_ids is not None:
                scroll_kwargs["document_ids"] = document_ids
            for record in self.vector_store.scroll_records(**scroll_kwargs):
                payload = dict(record.payload or {})
                text = str(payload.get("text") or "")
                tokenized_text = self._tokenize(text)
                primary_doc_length = len(tokenized_text.primary_tokens)
                supplemental_doc_length = len(tokenized_text.supplemental_tokens)
                if primary_doc_length <= 0 and supplemental_doc_length <= 0:
                    continue

                primary_matched_terms: Counter[str] = Counter()
                supplemental_matched_terms: Counter[str] = Counter()
                if primary_doc_length > 0:
                    primary_corpus_size += 1
                    primary_total_doc_length += primary_doc_length
                    primary_term_frequency = Counter(tokenized_text.primary_tokens)
                    primary_matched_terms = Counter(
                        {
                            token: primary_term_frequency[token]
                            for token in query_primary_token_set
                            if primary_term_frequency[token] > 0
                        }
                    )
                    for token in primary_matched_terms:
                        primary_document_frequency[token] += 1
                if supplemental_doc_length > 0:
                    supplemental_corpus_size += 1
                    supplemental_total_doc_length += supplemental_doc_length
                    supplemental_term_frequency = Counter(tokenized_text.supplemental_tokens)
                    supplemental_matched_terms = Counter(
                        {
                            token: supplemental_term_frequency[token]
                            for token in query_supplemental_token_set
                            if supplemental_term_frequency[token] > 0
                        }
                    )
                    for token in supplemental_matched_terms:
                        supplemental_document_frequency[token] += 1
                if not primary_matched_terms and not supplemental_matched_terms:
                    continue
                matched_records.append(
                    (
                        record,
                        primary_matched_terms,
                        primary_doc_length,
                        supplemental_matched_terms,
                        supplemental_doc_length,
                    )
                )
        except Exception as exc:  # pragma: no cover - 由 RetrievalService 兜底退回纯向量检索。
            raise RuntimeError(f"Lexical retrieval failed: {exc}") from exc

        if not matched_records:
            return []

        primary_average_doc_length = (
            primary_total_doc_length / primary_corpus_size if primary_total_doc_length > 0 and primary_corpus_size > 0 else 1.0
        )
        supplemental_average_doc_length = (
            supplemental_total_doc_length / supplemental_corpus_size
            if supplemental_total_doc_length > 0 and supplemental_corpus_size > 0
            else 1.0
        )
        scored_matches: list[LexicalMatch] = []
        for record, primary_matched_terms, primary_doc_length, supplemental_matched_terms, supplemental_doc_length in matched_records:
            score = 0.0
            if primary_matched_terms:
                score += self._bm25_score(
                    query_counter=query_primary_counter,
                    matched_terms=primary_matched_terms,
                    document_frequency=primary_document_frequency,
                    corpus_size=primary_corpus_size,
                    doc_length=primary_doc_length,
                    average_doc_length=primary_average_doc_length,
                )
            if supplemental_matched_terms:
                score += self.supplemental_bigram_weight * self._bm25_score(
                    query_counter=query_supplemental_counter,
                    matched_terms=supplemental_matched_terms,
                    document_frequency=supplemental_document_frequency,
                    corpus_size=supplemental_corpus_size,
                    doc_length=supplemental_doc_length,
                    average_doc_length=supplemental_average_doc_length,
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
        """标准 BM25 评分：基于词频、逆文档频率和文档长度归一化计算单条文档的相关性得分。"""
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
    def _fallback_tokens(text: str) -> list[str]:
        """兜底分词：当中文分词器不可用时，退回到字符级 bigram。"""
        if len(text) <= 1:
            return [text] if text else []
        return [text[index : index + 2] for index in range(len(text) - 1)]

    @staticmethod
    def _supplemental_bigram_tokens(text: str) -> list[str]:
        """生成补充 bigram token，用于增强中文关键词的召回信号。"""
        if len(text) <= 1:
            return []
        return [text[index : index + 2] for index in range(len(text) - 1)]

    def _tokenize(self, text: str) -> _TokenizedText:
        """对文本进行分词：英文按空格分词，中文按配置的分词器分词并生成补充 bigram。"""
        primary_tokens: list[str] = []
        supplemental_tokens: list[str] = []
        for raw_token in TOKEN_PATTERN.findall(text.lower()):
            if raw_token.isascii():
                primary_tokens.append(raw_token)
                continue
            segmented_tokens = self._segment_chinese(raw_token)
            if segmented_tokens:
                primary_tokens.extend(segmented_tokens)
                supplemental_tokens.extend(self._supplemental_bigram_tokens(raw_token))
                continue
            primary_tokens.extend(self._fallback_tokens(raw_token))
        return _TokenizedText(primary_tokens=primary_tokens, supplemental_tokens=supplemental_tokens)

    def _segment_chinese(self, text: str) -> list[str]:
        """对中文文本调用分词器，失败时返回空列表。"""
        if not text:
            return []
        if self.chinese_segmenter is None:
            return []
        try:
            tokens = [token.strip().lower() for token in self.chinese_segmenter(text) if token and token.strip()]
        except Exception:
            return []
        return tokens
