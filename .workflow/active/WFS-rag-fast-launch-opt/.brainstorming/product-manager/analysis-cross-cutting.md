# Cross-Cutting Product Decisions

**Scope**: Decisions spanning multiple features and the overall launch.

---

## 1. Product Positioning Strategy

### Core Positioning Statement

The system is a **document-grounded question-answering tool**. It answers questions by finding relevant passages in the organization's document library and synthesizing a response with direct citations.

### What the System IS

- A search-powered knowledge assistant that reads your organization's documents
- A tool that provides answers with verifiable evidence and source references
- A system that honestly says "I cannot find a confident answer" when evidence is insufficient

### What the System IS NOT

- A general-purpose chatbot (no open-ended conversation about arbitrary topics)
- A creative writing tool (does not generate content without document evidence)
- A substitute for reading original documents (answers are summaries, not replacements)

### Positioning Touchpoints

The positioning MUST be communicated at these user-facing surfaces:

1. **Portal home page** (`PortalShell.tsx` header area): The existing `portalTitle` and `portalDescription` already frame the tool correctly. No change needed for launch.
2. **Chat input area** (`PortalChatPage.tsx`): The placeholder text "请输入你的问题" and suggested questions already channel document-related queries. The `suggestedQuestions` per role already set the right expectation.
3. **Abstention responses** (F-006): Every abstention message MUST reinforce the document-grounded nature of the system. See @analysis-F-006-guided-abstention.md for wording templates.
4. **Empty-state text** (`PortalChatPage.tsx` line 282): Current text "回答会在这里以流式方式逐步展示" is neutral and acceptable for launch.

### Principle

Under-promise, over-deliver. Every user-facing string MUST position the system conservatively. Users who discover the system does more than expected become advocates; users who expect more than delivered become detractors.

---

## 2. Launch Communication Plan

### Internal Communication (Pre-Launch, Day -3 to Day -1)

| Audience | Message | Channel | Timing |
|----------|---------|---------|--------|
| Stakeholders | Launch readiness evidence: eval scores, human review results, bundle hash | Shared document | Day -2 |
| IT/Ops team | Rollback procedure, kill switch activation steps, monitoring script usage | Runbook document | Day -2 |
| Support team | FAQ for user questions about system capabilities and limitations | Internal wiki | Day -1 |

### User-Facing Communication (Launch Day)

| Audience | Message | Channel | Timing |
|----------|---------|---------|--------|
| All users | "Knowledge Q&A tool available — ask questions about your department's documents and get sourced answers" | In-app banner or notification | Day 0 |
| All users | "This tool answers questions based on uploaded documents. If it cannot find a confident answer, it will let you know." | First-time tooltip or onboarding hint | Day 0, optional |

### What NOT to Communicate

- Do NOT mention "AI" or "LLM" prominently. Frame as "document-based knowledge service."
- Do NOT promise accuracy percentages. Say "sourced answers" not "accurate answers."
- Do NOT advertise future features (SOP generation improvements, chunk optimization, etc.).

---

## 3. Human Review Bucket Definitions (F-004 Contribution)

The 5-bucket human review MUST use these definitions. Each bucket has a clear product implication:

### Bucket Definitions

| Bucket | Definition | Product Implication |
|--------|------------|---------------------|
| **correct** | Answer accurately reflects cited evidence; citation is relevant; user question is addressed | Ideal outcome. No action needed. |
| **abstained** | System correctly refused to answer because evidence was insufficient | Positive signal. Abstention is working as designed. |
| **unsupported-query** | User asked something outside document scope (e.g., general knowledge, personal advice) | System correctly abstained. Consider adding to suggested questions to show what IS supported. |
| **wrong-with-citation** | Answer is factually wrong despite having citations, OR citations do not support the answer | Critical failure. MUST count toward go/no-go threshold. |
| **permission-boundary-failure** | System answered using documents the user should not access, OR refused to answer on documents the user should access | ACL bug. MUST be fixed before launch. |

### Go/No-Go Criteria

- **wrong-with-citation** rate MUST be below 5% of reviewed samples
- **permission-boundary-failure** count MUST be zero
- **correct + abstained** combined rate MUST exceed 85% of reviewed samples
- Any single **wrong-with-citation** case involving safety-critical content (equipment operation, compliance) blocks launch regardless of rate

---

## 4. Evidence Gate Product Behavior (F-001 Contribution)

### When Evidence Gate Triggers

The evidence gate fires when retrieval scores fall below the configured threshold. From the product perspective, the trigger MUST produce one of two user-visible outcomes:

1. **Full abstention** — No answer generated. User sees guided abstention UX (F-006).
2. **Answer with caveat** — Answer generated but with a confidence indicator. This is a MAY for post-launch; for the initial launch, prefer full abstention over caveat answers.

### Launch Decision: Full Abstention Only

For the 1-week launch, the system MUST use full abstention when evidence is insufficient. Partial answers with caveats introduce UX complexity (new confidence UI component) that is not justified within the timeline. Conservative bias: prefer refusing to answer over giving a wrong answer.

### Score Threshold Product Requirement

The threshold value is a technical parameter owned by test-strategist. From product perspective:
- Threshold MUST be calibrated so that the system abstains on at least 90% of unsupported queries in the eval set
- Threshold MUST NOT be so aggressive that the system abstains on more than 30% of supported queries
- Threshold value MUST be documented in the launch bundle for reproducibility

---

## 5. Kill Switch UX Behavior (F-007)

### What the User Sees When Kill Switch Is Activated

When the kill switch is triggered, ALL queries MUST return the guided abstention response regardless of retrieval score. The user-facing behavior is identical to a normal abstention — the user MUST NOT see error messages or technical failure indicators.

### Wording

Use the same abstention template as F-006. The kill switch is an operational tool, not a user-facing feature. Users should perceive it as "the system could not find an answer to this question" not "the system is broken."

### Rollback Communication

If kill switch is activated, the support team MUST be notified immediately with:
- Activation timestamp
- Reason (if documented)
- Estimated time to restore

---

## 6. Monitoring Expectations (F-008)

### Product-Critical Metrics

The monitoring script MUST surface these metrics for product health assessment:

| Metric | Alert Threshold | Action |
|--------|----------------|--------|
| Abstention rate | > 40% of queries in 1-hour window | Investigate: threshold too aggressive or corpus gap |
| Wrong-answer reports | Any user-reported wrong answer | Immediate investigation |
| Empty citation rate | > 20% of non-abstained queries have zero citations | Investigate: retrieval failure |
| Average response latency | > 15 seconds P95 | Investigate: user experience degradation |

### Post-Launch Feedback Collection Plan

| Method | Timing | Target | Action |
|--------|--------|--------|--------|
| Event log analysis | Continuous (daily review for first week) | Abstention rate, retry rate, citation interaction | Automated script |
| In-app feedback prompt | Week 2 (post-launch stabilization) | Thumbs up/down on answer quality | Requires frontend component (MAY for launch, SHOULD for week 2) |
| Manual user interviews | Week 2-3 | 5-8 power users from different roles | Product team conducts |
| Support ticket review | Continuous | Any complaint or confusion about system behavior | Support team triages, PM reviews weekly |

---

## 7. Bundle Freeze Product Gate (F-002 Contribution)

From product perspective, the bundle freeze is a launch gate, not a user-facing feature. The product requirements are:

1. Bundle freeze MUST complete before eval calibration runs (hard dependency)
2. Any change to bundle contents after freeze MUST trigger re-evaluation (hard rule)
3. Bundle hash MUST be included in launch announcement for traceability

---

## 8. Tone and Language Guidelines

All user-facing text in the launch MUST follow these principles:

- **Chinese** for all user-facing strings (the existing frontend is fully Chinese-localized)
- **Professional but approachable** tone — avoid technical jargon in user-facing messages
- **Honest about limitations** — never imply the system can do more than it does
- **Action-oriented** — when the system cannot answer, it MUST suggest what the user can try next
- **Consistent terminology** — always use the same terms: "回答" for answer, "引用" for citation, "资料" for document, "来源" for source

### Forbidden Language

- Do NOT use "AI" or "人工智能" in user-facing text
- Do NOT use "我" (first person) in system messages — use passive or impersonal constructions
- Do NOT use exclamation marks in abstention messages
- Do NOT promise "准确" or "精确" — use "基于资料" or "有据可查"
