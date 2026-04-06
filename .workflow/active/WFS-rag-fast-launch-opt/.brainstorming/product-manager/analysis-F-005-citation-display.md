# F-005: Citation Display — Product Analysis

**Feature**: citation-display
**Description**: Frontend minimal change — document name + paragraph summary, expandable
**PM Priority**: Medium (MUST for launch, but implementation is small)
**Related**: F-001 evidence-gate (citation validation), F-006 guided-abstention (no-citation case)

---

## 1. Current State Assessment

### Existing Implementation

The frontend already has citation display capability. Review of the codebase reveals:

**PortalChatPage.tsx** (lines 287-326):
- Citations render as a "信息来源" (Information Sources) section below the answer
- Each citation shows: `document_name`, `snippet` (truncated to 220 chars), and `EvidenceSourceSummary` component
- "查看资料" link navigates to library page filtered by document
- "去 SOP 中心" link navigates to SOP generation for that document

**ChatPanel.tsx** (workspace, lines 226-251):
- Citations render as "引用来源" (Citation Sources) section
- Each shows: `document_name`, score, chunk_id prefix, and `snippet` (truncated to 300 chars)
- Uses `ResultCard` component with meta tags

**EvidenceSourceSummary.tsx**:
- Shows OCR status, parser type, page number, quality score
- Provides contextual explanation of evidence quality

### What Already Works

- Document name display: Already implemented and functional
- Snippet/paragraph display: Already implemented with truncation
- Evidence quality indicators: Already implemented via `EvidenceSourceSummary`
- Link to full document: Already implemented in portal

### Gap Analysis

| Current State | Required State | Gap |
|---------------|---------------|-----|
| Snippet shown as raw text | Paragraph summary with clear labeling | Minor wording adjustment |
| No expand-to-full-text | Expandable to show full snippet (optional) | MAY for launch |
| Score shown in workspace only | Score hidden in portal (correct for users) | Already correct |
| Truncation at 220 chars (portal) / 300 chars (workspace) | Consistent truncation with expand option | Minor |
| "查看资料" and "去 SOP 中心" links present | Keep as-is | No gap |

---

## 2. Citation Display Specification

### Information Architecture

Each citation MUST display, in order:

1. **Document name** — `item.document_name` (already rendered, keep as-is)
2. **Paragraph summary** — `item.snippet` truncated to 200 characters with "..." ellipsis
3. **Evidence quality badge** — `EvidenceSourceSummary` component (already present, keep as-is)
4. **Action links** — "查看资料" and "去 SOP 中心" (already present, keep as-is)

### Truncation Rules

- Snippets longer than 200 characters MUST be truncated with "..." suffix
- Truncation MUST break at the last complete sentence within 200 chars if possible; otherwise break at the last complete word
- For launch: simple character-based truncation is acceptable; sentence-aware truncation is a post-launch enhancement

### Expand-to-Full-Text (MAY for Launch)

If time permits, the citation card SHOULD support a "展开全文" (Expand) toggle:

- Default state: truncated snippet
- Expanded state: full `item.snippet` text
- Toggle text: "展开全文" / "收起"
- Animation: simple slide-down (CSS transition, no JS animation library)
- Implementation: Use existing `<details>` HTML element or a simple React state toggle

**Decision**: This is a MAY. If implementation takes more than 2 hours, defer to post-launch. The truncated snippet already provides sufficient context for users to judge answer quality.

---

## 3. Citation Ordering

### Ordering Rule

Citations MUST be ordered by relevance score (descending), which is the default behavior from the backend. The frontend MUST NOT reorder citations. The first citation is the most relevant evidence.

### Why This Matters

Users scan top-to-bottom. The first citation they see is the strongest evidence for the answer. If citations were ordered arbitrarily, users might see weak evidence first and distrust the answer.

---

## 4. Citation Count Display

### Header Text

The "信息来源" section header in `PortalChatPage.tsx` MUST include the citation count:

```
信息来源 (3 条引用)
```

This helps users quickly assess how many evidence sources support the answer.

### Zero Citations Case

When `citations` is empty (evidence gate triggered or `no_context` mode), the citation section MUST NOT render at all. The current behavior is correct — `shouldShowSources` (line 44) already gates this:

```typescript
const shouldShowSources = status === 'success' && Boolean(data?.citations.length);
```

No change needed for this case. The guided abstention component (F-006) handles the zero-citation user experience.

---

## 5. Citation and Answer Relationship

### Visual Connection

The answer text and citation section MUST be visually connected. Current layout in `PortalChatPage.tsx` places them in sequence within the same card, which is correct.

### In-Answer References (Post-Launch)

For launch, the answer text will NOT contain inline reference markers (e.g., "[1]", "[2]"). This is a post-launch enhancement that requires backend support (mapping answer sentences to citation indices). The current approach — answer text above, citations below — is sufficient and honest.

---

## 6. Mobile Considerations

### Responsive Layout

The existing citation card layout uses responsive CSS (`flex-wrap`, `gap`). For launch:

- Citation cards MUST stack vertically on mobile (already the case with `grid gap-3`)
- Snippet truncation MUST account for narrower viewports — 200-char truncation is still appropriate since snippet content is text, not layout-dependent
- "查看资料" and "去 SOP 中心" links MUST remain visible without horizontal scrolling (already the case with `flex-wrap`)

### No Additional Mobile Changes Required

The existing responsive behavior is adequate for launch. Do NOT introduce mobile-specific citation layouts in the 1-week window.

---

## 7. Edge Cases

| Edge Case | Expected Behavior | Current Behavior |
|-----------|-------------------|------------------|
| Very long document name | Name wraps naturally (already uses `break-all`) | Correct, no change |
| Empty snippet | Show "(无摘要)" placeholder | Needs handling — snippet SHOULD always have content, but defensive code needed |
| Special characters in snippet | Render as plain text (already in `<p>` tag, not dangerouslySetInnerHTML) | Correct, no change |
| OCR evidence with low quality | `EvidenceSourceSummary` already shows quality warning | Correct, no change |
| Multiple citations from same document | Show each as separate card (each has different `chunk_id`) | Correct, no change |

### Empty Snippet Handling

Add a defensive check: if `item.snippet` is empty or whitespace-only, display "(该片段无可用摘要)" instead of a blank space. This is a 1-line change in the citation rendering template.

---

## 8. Changes Required for Launch

### MUST (Required)

| Change | File | Effort |
|--------|------|--------|
| Add citation count to "信息来源" header | `PortalChatPage.tsx` line 289 | 5 minutes |
| Add empty snippet defensive text | `PortalChatPage.tsx` citation card | 5 minutes |
| Verify truncation is 200 chars (currently 220) | `PortalChatPage.tsx` line 298 | 2 minutes |

### SHOULD (If Time Permits)

| Change | File | Effort |
|--------|------|--------|
| Expand-to-full-text toggle | `PortalChatPage.tsx` citation card | 1-2 hours |
| Consistent truncation between portal and workspace | `ChatPanel.tsx` line 239 | 5 minutes |

### MAY (Post-Launch)

| Change | File | Effort |
|--------|------|--------|
| In-answer inline reference markers | Backend + Frontend | Multi-day |
| Sentence-aware truncation | Frontend | 2-3 hours |
| Citation highlighting in answer text | Backend + Frontend | Multi-day |

---

## 9. Success Criteria

From product perspective, citation display is successful when:

1. Every answered query with citations shows at least one citation card with document name and snippet
2. Users can identify which document the answer came from within 3 seconds of scanning the citation section
3. No citation card shows blank or broken content for any valid response
4. Citation section never appears for abstention responses (handled by F-006 instead)
