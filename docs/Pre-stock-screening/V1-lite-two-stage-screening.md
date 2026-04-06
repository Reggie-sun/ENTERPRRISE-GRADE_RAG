# V1 Lite Two-Stage Screening

Date: 2026-04-06

## 1. Positioning

This is the lightest practical version of pre-stock screening.

It is designed for the current repository shape, where the ingest path is still dominated by a single mainline:

- parse / OCR
- text normalization
- chunking
- embedding
- vector upsert

Reference:

- [backend/app/services/ingestion_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/ingestion_service.py)
- [backend/app/rag/parsers/document_parser.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/parsers/document_parser.py)

## 2. Main Idea

Insert one new screening stage between "parsed text ready" and "chunk building".

Pipeline becomes:

1. parse / OCR
2. normalize text
3. regex screening
4. semantic screening
5. chunk
6. embedding
7. index

## 3. Screening Logic

### 3.1 Regex Screening

Remove or suppress highly deterministic noise:

- repeated page header and footer
- page number only lines
- scan watermark fragments
- empty separator lines
- repeated signature lines
- duplicated table header rows copied across pages
- obvious OCR garbage lines

This stage should be conservative.

It should only target patterns with high confidence and high repetition.

### 3.2 Semantic Screening

Split parsed text into blocks first:

- paragraph
- table row group
- bullet group

Then classify each block as:

- `keep`
- `drop`

The semantic classifier should focus on one question:

"Does this block materially help retrieval, citation, or answer grounding?"

## 4. Good Fit

V1 works well for:

- plain text manuals
- FAQ-like documents
- OCR-heavy scanned instructions
- noisy exports with repeated decoration

## 5. Bad Fit

V1 is weak for:

- SOP / WI documents with strong structure
- documents where metadata lines are also retrieval anchors
- corpora where many blocks are borderline useful rather than obviously useless

This is important because current SOP / WI ingestion already relies on multi-granularity chunking and structured fields:

- [backend/app/rag/chunkers/structured_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/structured_chunker.py)
- [backend/tests/test_document_ingestion.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_document_ingestion.py)

## 6. Implementation Shape

Introduce a small screening component, for example:

- `backend/app/services/pre_stock_screening_service.py`

Suggested responsibilities:

- split parsed text into blocks
- run regex rules
- run semantic keep / drop classification
- emit screened text
- emit audit report

Suggested output model:

```json
{
  "original_block_count": 120,
  "kept_block_count": 93,
  "dropped_block_count": 27,
  "drop_reasons": {
    "repeated_footer": 12,
    "page_number": 4,
    "semantic_irrelevant": 11
  }
}
```

## 7. Strengths

- low implementation risk
- low coupling to current chunkers
- easy to canary
- easy to explain

## 8. Risks

- binary keep / drop is too rough
- easy to over-delete useful metadata
- hard to express "keep but low priority"
- may improve noise rate without improving retrieval precision much

## 9. Recommended Verification

Before rollout:

- extend ingest unit tests
- compare chunk counts before and after
- compare retrieved top chunks for canary samples
- rerun retrieval eval on the same sample set

Recommended first canary:

- noisy digitalization documents
- OCR-heavy files
- non-SOP manuals

## 10. Verdict

V1 is a good first experiment.

It is not the best long-term design, but it is a low-risk way to prove that pre-stock screening is worth doing at all.
