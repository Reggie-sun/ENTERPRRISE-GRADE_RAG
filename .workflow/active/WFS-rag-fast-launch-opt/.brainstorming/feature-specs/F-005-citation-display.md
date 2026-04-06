# Feature Spec: F-005 - Citation Display

**Priority**: Medium
**Contributing Roles**: product-manager (lead), system-architect
**Status**: Draft (from synthesis)

---

## 1. Requirements Summary

The system SHALL ensure that every non-abstention answer displays at least one citation card with document name and paragraph summary. The existing frontend already implements most citation display functionality; this feature addresses minor consistency gaps.

- Every answered query with citations MUST show at least one citation card with document name and snippet.
- Snippet truncation MUST be at 200 characters with "..." ellipsis (RESOLVED: PM's 200 chars).
- The "Information Sources" section header MUST include citation count in Chinese.
- Empty snippets MUST show aplaceholder text in Chinese.
- The citation section MUST NOT render when citations is empty (abstention case handled by F-006).
- Citations MUST remain ordered by relevance score (descending) as returned by the backend.

## 2. Design Decisions

### 2.1 Truncation Length: 200 Characters (RESOLVED)

**Decision**: Snippets MUST be truncated at 200 characters with "..." ellipsis. Currently portal uses 220 chars and workspace uses 300 chars.

**Rationale**: 200 chars is sufficient for document identification. Users who want full context can use the link. Consistent truncation across portal and workspace reduces cognitive load.

**Source roles**: product-manager (truncation rules, user scanability).

### 2.2 Minimal Change Approach

The portal already has citation display with document names, snippets, evidence quality badges, and navigation links. Changes are small additions:

| Current | Required | Change |
|---------|----------|--------|
| Truncation at 220 chars | 200 chars | Adjust constant |
| Header: "信息来源" | "信息来源 (N 条引用)" | Add count |
| No empty snippet handling | "(该片段无可用摘要)" | Add defensive check |

**Total effort**: ~15 minutes for MUST items.

### 2.3 Expand-to-Full-Text Deferred

The expand-to-full-text toggle ("展开全文" / "收起") is a MAY for launch. If implementation takes more than 2 hours, defer to post-launch.

## 3. Interface Contract

Each citation card displays, in order:
1. Document name (`item.document_name`)
2. Paragraph summary (`item.snippet` truncated to 200 chars)
3. Evidence quality badge (`EvidenceSourceSummary`)
4. Action links ("查看资料" and "去 SOP 中心")

Section header format: `信息来源 (N 条引用)` where N = citations.length.

Empty snippet fallback: `(该片段无可用摘要)`.

## 4. Constraints & Risks

| Constraint | Description |
|-----------|-------------|
| No new components for MUST items | Reuse existing citation card layout |
| Frontend-only changes | No backend changes required |
| Consistent with existing design system | Match `ResultBox` styling, `rgba(15,23,42,...)` palette |
| Mobile responsive | Existing `grid gap-3` handles stacking |

## 5. Acceptance Criteria

1. Section header shows citation count in Chinese.
2. All snippets longer than 200 chars are truncated with "...".
3. Empty snippets show placeholder text in Chinese.
4. Zero-citation case: Section does not render.
5. Citation ordering preserved (backend order).
6. No blank or broken citation cards.
7. Mobile: Cards stack without horizontal scroll.

8. Multiple citations from same document: Each shows as separate card.

## 6. Detailed Analysis References

- @product-manager/analysis-F-005-citation-display.md
- @product-manager/analysis-cross-cutting.md

## 7. Cross-Feature Dependencies

**Depends on**: F-001 (evidence-gate): When citations are empty, section does not render. Handled by existing `shouldShowSources` logic.

**Required by**: None directly. F-006 (guided-abstention) complements by handling no-citation case.

**Shared patterns**: Zero-citation detection shared between F-005 and F-006 via `shouldShowSources` logic.
