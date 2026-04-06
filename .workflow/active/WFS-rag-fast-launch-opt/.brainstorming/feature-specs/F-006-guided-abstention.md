# Feature Spec: F-006 - Guided Abstention

**Priority**: Medium
**Contributing Roles**: product-manager (lead), system-architect, test-strategist
**Status**: Draft (from synthesis)

---

## 1. Requirements Summary

The system SHALL display a guided abstention card when the evidence gate (F-001) or kill switch (F-007) triggers, or when no documents are available (`no_context`). The abstention card provides the clear, honest statement that the system cannot answer, followed by actionable reformulation suggestions and clickable example questions.

- All abstention messages MUST be in Chinese (EP-008).
- v1 implements two modes: `no_context` (Template C) and `evidence_gate_abstain` (Template A).
- Template B (out-of-scope detection) is deferred to post-launch.
- Abstention card MUST use neutral styling (light background, dashed border, info icon) -- NOT error styling.
- Example questions MUST come from existing `suggestedQuestions` in `roleExperience.ts` (no new backend needed).
- Clicking an example question MUST populate the input field, NOT auto-submit.
- The abstention card MUST NOT use apologetic language ("抱歉", "对不起") or first person ("我").
- The abstention card MUST NOT use exclamation marks or the term "AI".

## 2. Design Decisions

### 2.1 Two Abstention Modes for v1 (RESOLVED)

**Decision**: v1 implements exactly two abstention modes with two corresponding templates:

| Mode | Template | Trigger |
|------|---------|---------|
| `no_context` | Template C | Empty citations (no documents available) |
| `evidence_gate_abstain` | Template A | Non-empty citations but top1 score below threshold |
| `kill_switch` | Template A | Kill switch activated (F-007) |

Template B (out-of-scope) is deferred to post-launch because distinguishing "insufficient evidence" from "out of scope" requires backend classification logic that is not essential for the 1-week timeline.

**Source roles**: product-manager (template design, language), system-architect (mode naming).

### 2.2 Wording Templates

**Template A -- Insufficient Evidence** (modes: evidence_gate_abstain, kill_switch):

```
未能在当前资料库中找到与您的问题直接相关的信息。

您可以尝试：
- 使用更具体的描述，例如包含设备名称、流程编号或文件标题
- 缩小问题范围，聚焦到一个具体环节
- 检查是否有相关资料尚未上传到知识库

您也可以参考以下问题格式：
"{suggested_q_1}"
"{suggested_q_2}"
```

**Template C -- No Context** (mode: no_context):

```
当前资料库中尚无可用的文档资料，无法回答问题。请联系管理员确认文档上传状态，或稍后再试.

可先前往资料中心查看当前部门的资料情况.
```

**Key tone rules**:
- Neutral, not apologetic: "未能..." not "抱歉..."
- Action-oriented: "您可以尝试..." not "请稍后再试"
- Specific suggestions, not generic: "包含设备名称..." not "重新提问"
- No "AI" terminology,- No first person pronouns

### 2.3 Example Questions Strategy

**Decision**: Use existing `suggestedQuestions` from `getRoleExperience()`. Zero backend changes.

**Implementation**: Show exactly 2 example questions from the role's `suggestedQuestions` array. Rotate examples if the user's current question matches one of the suggestions. Each example is rendered as a clickable chip.

**Click behavior**: Populate input field only. User MUST click "发起问答" to submit. This prevents accidental repeated abstention loops.

**Source roles**: product-manager (Option 2 recommended for launch).

### 2.4 Visual Design Specification

The `PortalChatPage.tsx` answer area, conditionally render `AbstentionCard` instead of normal answer text.

**Styling**:
- Background: `rgba(15, 23, 42, 0.03)` (light blue-gray tint)
- Border: `1px dashed rgba(15, 23, 42, 0.12)` (subtle dashed border)
- Border-radius: `1rem` (consistent with `ResultBox`)
- Text color: Standard ink (NOT red, NOT orange)
- Icon: Info circle (not warning triangle, not error X)

- Overall feel: Helpful guidance, NOT error message

This matches the existing design language (`ResultBox` uses similar palette) but is visually distinct from error state.

## 3. Interface Contract

### 3.1 Component Interface

```typescript
// New component: components/AbstentionCard.tsx (~80 lines)
interface AbstentionCardProps {
  mode: 'no_context' | 'evidence_gate_abstain' | 'kill_switch';
  suggestedQuestions: string[];  // from getRoleExperience()
  onQuestionClick: (question: string) => void;  // populates input field
}
```

### 3.2 Detection Logic in PortalChatPage.tsx

```typescript
const isAbstention = data?.mode === 'no_context'
  || data?.mode === 'evidence_gate_abstain'
  || data?.mode === 'kill_switch';

// Conditional render
{isAbstention ? (
  <AbstentionCard
    mode={data.mode}
    suggestedQuestions={experience.suggestedQuestions}
    onQuestionClick={(q) => setInputValue(q)}
  />
) : (
  <div className="min-h-[280px] ...">
    {data?.answer || '回答会在这里...'}
  </div>
)}
```

### 3.3 Backend Changes

One MUST change: Rewrite the `no_context` message in `chat_service.py` (line ~990) from English to Chinese using Template C text.

No other backend changes required. The abstention templates live in the frontend.

## 4. Constraints & Risks

| Constraint | Description |
|-----------|-------------|
| ~3-4 hours total implementation | New component + conditional render + backend message rewrite |
| No new backend endpoints | All data from existing sources (mode field, suggestedQuestions) |
| Frontend-only component | AbstentionCard is a self-contained React component |
| Must match existing design system | Use same color palette, border radius, font sizes |

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Template wording feels "robot-like" | Low | Medium | PM reviews all Chinese text before merge |
| User clicks same question after abstention | Medium | Low | Expected behavior; user will naturally try different question |
| Missing suggestedQuestions for edge role | Low | None | Defensive: show reformulation hints only, skip chips |
| Kill switch shows same template as evidence gate | Medium | None | By design; user should not distinguish operational emergency from evidence insufficiency |

## 5. Acceptance Criteria

1. **AbstentionCard component**: New `AbstentionCard.tsx` renders correctly for `no_context`, `evidence_gate_abstain`, and `kill_switch` modes.
2. **Chinese messages**: All abstention text is in Chinese; no English strings visible to user.
3. **Template A renders** for `evidence_gate_abstain` and `kill_switch` modes.
4. **Template C renders** for `no_context` mode.
5. **Example questions**: 2 clickable chips appear from role-based `suggestedQuestions`.
6. **Click behavior**: Clicking chip populates input field, does NOT submit.
7. **Neutral styling**: No red text, no error icons, no exclamation marks.
8. **No apology language**: No "抱歉", "对不起", "我" in any abstention text.
9. **Zero-citation case**: When citations is empty and mode is abstention, AbstentionCard renders; citation section does not render.
10. **Backend message**: `no_context` message in `chat_service.py` is Chinese.

## 6. Detailed Analysis References

- @product-manager/analysis-F-006-guided-abstention.md -- Full specification, templates, visual design, reformulation strategy, implementation approach, tone guidelines
- @product-manager/analysis-cross-cutting.md -- Evidence gate product behavior, kill switch UX, tone and language guidelines
- @system-architect/analysis-F-001-evidence-gate.md -- Mode naming, response schema, SSE behavior
- @test-strategist/analysis-F-001-evidence-gate.md -- Edge cases (empty citations, score at threshold)

## 7. Cross-Feature Dependencies

**Depends on**:
- F-001 (evidence-gate): Produces `mode="evidence_gate_abstain"` which triggers Template A.
- F-007 (kill-switch): Produces `mode="kill_switch"` which also triggers Template A.

**Required by**: None.

**Shared patterns**:
- Mode string contract: `no_context`, `evidence_gate_abstain`, `kill_switch` shared between backend and frontend.
- Zero-citation detection: `shouldShowSources` in `PortalChatPage.tsx` shared between F-005 (hide citations) and F-006 (show abstention card).
- Chinese language standard (EP-008): All user-facing abstention text across F-006 and F-001 response messages.

**Integration points**:
- `PortalChatPage.tsx` answer area -- conditional rendering
- `components/AbstentionCard.tsx` -- new component
- `chat_service.py` line ~990 -- backend `no_context` message rewrite
- `roleExperience.ts` -- suggestedQuestions data source (read-only)
