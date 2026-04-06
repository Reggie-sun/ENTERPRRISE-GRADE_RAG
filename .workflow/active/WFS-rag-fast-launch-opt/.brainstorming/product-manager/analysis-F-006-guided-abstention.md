# F-006: Guided Abstention — Product Analysis

**Feature**: guided-abstention
**Description**: Frontend abstention UX — query reformulation suggestions + example questions
**PM Priority**: Medium (MUST for launch, critical for user trust)
**Related**: F-001 evidence-gate (triggers abstention), F-005 citation-display (absence of citations)

---

## 1. Current State Assessment

### Existing Abstention Behavior

The backend already has abstention-adjacent modes:

1. **`no_context`** (`chat_service.py` line 987-994): When no documents are available. Returns: "No uploaded documents are available yet. Upload a document before asking questions." This message is in English and does not provide guidance.
2. **`retrieval_fallback`** (`chat_service.py` line 1006-1013): When LLM is unavailable. Returns a summary of top 2 citation snippets with English header "Generation model is unavailable."
3. **Error states**: `PortalChatPage.tsx` shows `formatApiError` messages in red text.

### Gap Analysis

| Current State | Required State | Gap |
|---------------|---------------|-----|
| `no_context` message is in English | All messages MUST be in Chinese | Needs translation |
| `no_context` message says "upload documents" | Should explain evidence was insufficient for THIS query | Needs rewrite |
| No query reformulation suggestions | MUST provide reformulation hints | New component needed |
| No example questions shown during abstention | SHOULD show example questions the system can handle | New component needed |
| Error state uses generic red text | Abstention should not look like an error | Styling adjustment |
| No distinction between "out of scope" and "insufficient evidence" | SHOULD distinguish for better guidance | Backend support needed |

---

## 2. Abstention Response Specification

### Abstention Triggers and Types

The evidence gate (F-001) determines WHEN to abstain. The product defines HOW based on the abstention reason:

| Abstention Type | Trigger | User-Visible Distinction |
|----------------|---------|------------------------|
| **insufficient-evidence** | Retrieval scores below threshold; query is in-scope but evidence is weak | "Could not find sufficiently relevant information" |
| **out-of-scope** | Query is clearly outside document scope (detected by low scores across all strategies) | "This question may be outside the document library's scope" |

For launch, both types MAY use the same abstention template. Distinguishing between them requires a backend classification step that is not essential for the 1-week timeline. If implementation time allows, the distinction improves user guidance significantly.

### Mandatory Template (MUST for Launch)

Every abstention response MUST contain these elements:

1. **Primary message**: Clear, honest statement that the system cannot answer this question
2. **Reason hint**: Brief explanation of why (without technical details)
3. **Reformulation suggestions**: 2-3 alternative ways to ask the question
4. **Example questions**: 1-2 questions the system CAN answer (drawn from role-based `suggestedQuestions`)

---

## 3. Wording Templates

### Template A: Insufficient Evidence (Primary)

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

### Template B: Out of Scope

```
当前问题可能不在资料库的覆盖范围内。本系统基于已上传的组织文档回答问题，不处理通用知识或非文档相关的查询。

您可以尝试：
- 围绕本部门已有的流程、规范、设备文档提问
- 查看资料中心确认当前可用的文档范围

您也可以参考以下问题格式：
"{suggested_q_1}"
"{suggested_q_2}"
```

### Template C: No Context (Empty Library)

```
当前资料库中尚无可用的文档资料，无法回答问题。请联系管理员确认文档上传状态，或稍后再试。

可先前往资料中心查看当前部门的资料情况。
```

### Template Selection Logic

For launch, use Template A as the default. The backend `mode` field determines which template to show:
- `mode === "no_context"`: Template C
- Evidence gate triggered (score below threshold): Template A
- Out-of-scope detection (future): Template B

---

## 4. Reformulation Suggestions

### Strategy

Reformulation suggestions help users reformulate their query. The system SHOULD generate these, but for the 1-week launch, a simpler approach is acceptable:

### Option 1: Static Suggestions by Pattern (Recommended for Launch)

Match common query patterns and provide pre-written reformulations:

| Query Pattern | Detected By | Reformulation |
|---------------|-------------|---------------|
| Too broad ("tell me about X") | Short query (< 10 chars after trim) | "尝试具体描述你需要的环节或步骤" |
| Too specific (unique IDs, names) | Contains numbers/special chars | "尝试使用更通用的流程名称或设备类型" |
| Question about process | Contains "怎么", "如何", "流程" | "尝试指定具体的设备型号或操作环节" |
| Question about policy | Contains "规定", "要求", "标准" | "尝试指定是哪个部门或哪类操作的规定" |

### Option 2: Role-Based Suggestions (Alternative for Launch)

Use the existing `suggestedQuestions` from `getRoleExperience()` as reformulation examples. This requires zero backend changes — the frontend already has these strings.

```typescript
// Already available in PortalChatPage
const experience = getRoleExperience(profile);
experience.suggestedQuestions  // e.g., ["设备报警后第一步应该检查什么？", ...]
```

**Recommendation**: Use Option 2 for launch. It reuses existing data, requires no backend changes, and provides role-relevant examples. The reformulation text can be a generic instruction ("参考以下问题格式") followed by the role-specific suggested questions.

---

## 5. Example Questions

### Source

Example questions MUST come from the existing `suggestedQuestions` array in `roleExperience.ts`. This ensures:

1. Examples are role-appropriate (different for employee vs admin vs sys_admin)
2. Examples are already validated (they are the system's suggested defaults)
3. No new content needs to be written or reviewed

### Display Rules

- Show exactly 2 example questions from the role's `suggestedQuestions` array
- Rotate examples: if the user's current question matches one of the suggestions, pick different ones
- Each example MUST be clickable (same behavior as the existing suggestion chips on the portal home)

### Clickable Example Behavior

When a user clicks an example question in the abstention response:

1. The question text MUST populate the input field (NOT auto-submit)
2. The user MUST click "发起问答" to submit
3. This prevents accidental repeated abstention loops

---

## 6. Visual Design Specification

### Abstention Card Layout

The abstention response MUST render in the answer area with distinct visual treatment from successful answers:

```
+--------------------------------------------------+
|  [Icon: info circle]                              |
|  未能在当前资料库中找到与您的问题直接相关的信息。    |
|                                                   |
|  您可以尝试：                                      |
|  - 使用更具体的描述                                |
|  - 缩小问题范围                                    |
|  - 检查相关资料是否已上传                          |
|                                                   |
|  您也可以参考以下问题格式：                          |
|  [chip: "设备报警后第一步应该检查什么？"]            |
|  [chip: "新员工上岗前需要阅读哪些资料？"]            |
+--------------------------------------------------+
```

### Styling Requirements

- Background: Light blue-gray tint (not white, not red — neutral, not alarming)
- Border: Subtle dashed border (consistent with `ResultBox` styling but different from error)
- Text color: Standard ink color (NOT red, NOT orange)
- Icon: Info circle (not warning triangle, not error X)
- Overall feel: Helpful guidance, NOT error message

### Key CSS Approach

```css
/* Abstention card — neutral guidance, not error */
.abstention-card {
  background: rgba(15, 23, 42, 0.03);
  border: 1px dashed rgba(15, 23, 42, 0.12);
  border-radius: 1rem;
  padding: 1.25rem;
}
```

This matches the existing design language (`ResultBox` uses `rgba(15,23,42,0.02)` background with dashed border) but is visually distinct from the error state.

---

## 7. Frontend Implementation Approach

### Where to Render

In `PortalChatPage.tsx`, after the answer display area (line 277-285). Currently:

```tsx
<div className="min-h-[280px] whitespace-pre-wrap text-base leading-8 text-ink">
  {data?.answer || '回答会在这里以流式方式逐步展示。'}
</div>
```

Add abstention detection:

```tsx
const isAbstention = data?.mode === 'no_context' || /* evidence-gate triggered */;
```

The abstention card replaces the normal answer display when `isAbstention` is true.

### Data Flow

1. Backend returns `mode: "no_context"` or evidence-gate triggered response
2. Frontend detects abstention mode
3. Frontend renders abstention card with:
   - Static template text (mapped from mode)
   - Dynamic example questions from `experience.suggestedQuestions`
4. Example question clicks populate input field

### Minimal Implementation Scope

For the 1-week launch, the implementation MUST be:

1. A new `AbstentionCard` component (~80 lines of TSX)
2. Conditional rendering in `PortalChatPage.tsx` (~10 lines of logic)
3. CSS styles matching existing design system (~20 lines)
4. No new backend endpoints required (reuse existing `mode` field and existing `suggestedQuestions`)

---

## 8. Edge Cases

| Edge Case | Expected Behavior |
|-----------|-------------------|
| User asks same question after abstention | Show same abstention (no loop prevention needed; user will naturally try a different question) |
| User clicks example question then modifies it | Normal flow — user can edit the populated question freely |
| Abstention during streaming | If evidence gate triggers before stream completes, backend returns abstention mode in `onDone` |
| Multiple abstentions in a row | No special handling; each query is independent |
| User with no suggested questions (edge role) | Show reformulation hints only, skip example question chips |
| Kill switch activated | All queries show abstention (same Template A) |

---

## 9. Tone Guidelines

### Core Tone Principles

1. **Neutral, not apologetic**: Do NOT say "抱歉" or "对不起". The system is performing correctly by abstaining.
2. **Helpful, not defensive**: Focus on what the user CAN do, not what the system cannot do.
3. **Specific, not generic**: Provide concrete suggestions, not "please try again later."
4. **Consistent, not varied**: Use the same template structure for all abstention instances. Users learn the pattern.

### Language Examples

| Avoid | Use Instead | Reason |
|-------|-------------|--------|
| "抱歉，我无法回答" | "未能在当前资料库中找到相关信息" | Neutral, not apologetic |
| "请稍后再试" | "尝试使用更具体的描述" | Actionable, not dismissive |
| "系统错误" | "当前问题可能不在资料库覆盖范围" | Honest, not alarming |
| "我不懂你的问题" | "尝试包含设备名称或流程编号" | Helpful, not blaming |

---

## 10. Changes Required for Launch

### MUST (Required)

| Change | File | Effort |
|--------|------|--------|
| New `AbstentionCard` component | New file `components/AbstentionCard.tsx` | 2-3 hours |
| Abstention detection logic in portal | `PortalChatPage.tsx` | 30 minutes |
| Chinese abstention templates (3 templates) | `AbstentionCard.tsx` or constants file | 1 hour |
| Example question chips in abstention card | `AbstentionCard.tsx` | 30 minutes |
| Backend: Chinese `no_context` message | `chat_service.py` line 990 | 5 minutes |

### SHOULD (If Time Permits)

| Change | File | Effort |
|--------|------|--------|
| Abstention in workspace ChatPanel | `ChatPanel.tsx` | 1 hour |
| Abstention type distinction (insufficient vs out-of-scope) | Backend + Frontend | 3-4 hours |

### MAY (Post-Launch)

| Change | File | Effort |
|--------|------|--------|
| Query pattern-based reformulation suggestions | Frontend | 2-3 hours |
| Abstention analytics tracking | Frontend + Backend | 1-2 hours |
| A/B testing of abstention wording | Frontend + Backend | Multi-day |

---

## 11. Success Criteria

From product perspective, guided abstention is successful when:

1. Every abstention response provides at least one actionable suggestion the user can try
2. Abstention responses never use error styling or alarming language
3. At least 50% of users who see an abstention response attempt a follow-up query (measured post-launch via event logs)
4. Zero users report confusion about WHY the system could not answer (measured via post-launch feedback)
5. The abstention template is fully in Chinese with no English strings exposed to the user
