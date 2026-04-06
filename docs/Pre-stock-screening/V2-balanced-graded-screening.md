# V2 Balanced Graded Screening

Date: 2026-04-06

## 1. Positioning

This is the recommended version for the current repository.

It keeps the implementation reasonably small, but avoids the biggest weakness of V1:

not all "unimportant" content should be deleted.

Some content should stay available as:

- low-priority evidence
- summary-only material
- metadata anchor

## 2. Main Idea

Replace binary screening with graded screening.

Each block is classified as one of:

- `keep`
- `demote`
- `summary_only`
- `drop`

## 3. Meaning Of Each Grade

### `keep`

Full participation:

- chunk
- embedding
- vector index
- lexical retrieval
- citations

Typical examples:

- clause body
- operation steps
- fault handling instructions
- acceptance criteria
- safety rules

### `demote`

Keep in chunking and indexing, but mark as lower-priority for ranking.

Typical examples:

- directory-like section overviews
- repeated contextual boilerplate
- generic introduction paragraphs
- appendix-like explanatory text

### `summary_only`

Do not enter the main fine-grained retrieval path as raw evidence.

Instead:

- compress into section summary or doc summary
- retain in audit trail

Typical examples:

- long revision history
- document issuance boilerplate
- repeated signing section
- organization disclaimer

### `drop`

Exclude from main indexing path.

Typical examples:

- page number only
- repeated footer/header
- OCR garbage
- empty decoration rows

## 4. Why V2 Fits This Repository

The current repository already distinguishes between multiple content roles in structured documents:

- `metadata`
- `doc_summary`
- `section_summary`
- `clause`

Reference:

- [backend/app/rag/chunkers/structured_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/structured_chunker.py)
- [backend/tests/test_document_ingestion.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_document_ingestion.py#L2521)

That means the system already has a natural place for:

- high-value evidence
- lower-priority context
- summary-only material

So V2 aligns with the codebase better than a hard delete-only design.

## 5. Proposed Pipeline

1. parse / OCR
2. normalize text
3. block split
4. repeated block detection
5. regex classification
6. semantic classification
7. graded output merge
8. chunk strategy selection
9. embedding and indexing

## 6. Classification Strategy

Use a layered decision order:

### Step 1: Hard rules

Immediately mark obvious noise:

- `drop`
- or `summary_only`

### Step 2: Structure-aware rules

Use document signals:

- document code
- clause number
- section heading
- version
- effective date

Examples:

- clause-numbered lines should rarely be dropped
- document code and version lines should usually be `keep` or `summary_only`
- revision table rows should usually be `summary_only`

### Step 3: Semantic classifier

Only classify the remaining uncertain blocks.

This classifier should output:

- relevance to retrieval
- evidential value
- whether the content is procedural, factual, decorative, or duplicated

## 7. Data Model Suggestion

Add block-level screening metadata before chunk generation.

Suggested fields:

```json
{
  "block_id": "doc_001::block_23",
  "text": "版本号 A/0",
  "screening_decision": "summary_only",
  "screening_reason": "document_metadata",
  "screening_score": 0.82,
  "is_repeated": false,
  "section_hint": "metadata"
}
```

## 8. Indexing Policy

V2 should not index all block grades the same way.

Recommended policy:

- `keep`: full weight
- `demote`: full index, lower retrieval weight
- `summary_only`: summary path only
- `drop`: no index

This is the key difference from V1.

The design goal is not only to clean content.

It is to shape the retrieval surface.

## 9. Rollout Strategy

Start with a config gate.

Suggested modes:

- `off`
- `lite`
- `graded`

Recommended first default:

- enable `graded` only for selected departments or canary document categories

## 10. Strengths

- more precise than binary deletion
- safer for structured evidence
- better fit for current chunk model
- better long-term foundation for retrieval weighting

## 11. Risks

- more implementation work than V1
- ranking logic may need follow-up tuning
- requires clearer audit visibility

## 12. Recommended Verification

Minimum verification:

- add unit tests for screening decisions
- preserve existing SOP / WI structured chunk tests
- compare chunk distribution before and after
- compare retrieval eval before and after
- inspect failure cases where a previously correct clause disappears

## 13. Verdict

V2 is the best default choice.

It is detailed enough to be useful, but still small enough to land in the current repository without turning screening into a separate platform project.
