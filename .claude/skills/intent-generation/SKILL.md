# Intent Generation (PMO)

## 1. Purpose and position in the PMO lifecycle

Intent Generation converts the verified source corpus produced by
`project-initialization` into the canonical, governed **Intent** artifact:

```
docs/pmo/intent/intent.md
```

Intent is the **contextual source of truth** for the rest of the PMO
lifecycle - it preserves **WHY** the project exists, its confirmed
high-level requirements (`INT-REQ-*`), resolved assumptions (`ASM-*`), and
any PM decisions reached while reconciling open questions against the
source evidence. It does not define detailed functional or acceptance
criteria (that is `spec-generation`'s job) and does not decide commercial
scope (that is Scope's job on the LEGACY path only - see
`spec-generation` Section 2a for why a NEW-lifecycle project has none).

```
Project Initialization (verified source corpus)
  -> Intent Generation (this skill)
    -> PM Intent Approval (records VALIDATED + .pmo/approvals/intent-approval.yaml)
      -> Questions & Assumptions (requirement-gathering)
        -> Specification Generation (spec-generation)
```

**Filling a real framework gap.** `docs/pmo/intent/intent.md` has always
been governed at the guard layer by `intent-schema-guard.py` (structural /
workflow / immutability controls) and at the approval layer by
`intent_approval_core.py` / `intent-approval-recorder.py` (the PM-approval
transaction) - but nothing packaged the **semantic** generation step itself
as an owned, repeatable Skill the way `requirement-gathering` and
`spec-generation` already package their own semantic steps. This skill
closes that gap. It does not change `intent-schema-guard.py`, and every
structural rule that guard enforces applies to this skill's output
unchanged.

---

## 2. Prerequisites - hard gate

1. `.pmo/project-config.yaml` exists with a usable `project.id` /
   `project.name` / `project.client` (produced by `project-initialization`).
2. A verified source corpus exists under `docs/pmo/sources/`, classified by
   category and authority.
3. `docs/pmo/intent/intent.md` does not already exist as a `VALIDATED`
   artifact - once VALIDATED, Intent is immutable
   (`intent_approval_core.validate_immutable`, `PMO-INTENT-009`); a
   materially different Intent for an already-VALIDATED project is a new
   governed decision (a fresh PM reconciliation pass, exactly as WM
   Trucking's own v0.1 -> v0.2 -> v0.3 history already demonstrates), never
   a silent overwrite.

If prerequisite 1 or 2 fails, stop and route back to
`project-initialization`. If prerequisite 3 fails because Intent is already
VALIDATED, stop and report `INTENT_ALREADY_VALIDATED` - do not touch it.

---

## 3. Source authority hierarchy

Unchanged from the framework's general evidentiary discipline, and the
same hierarchy `requirement-gathering` and `spec-generation` already use:

1. Executed contract / signed SOW.
2. Approved commercial scope / LOE.
3. Formal client requirements documents.
4. Client written communications (emails, messages).
5. Recorded client discussions (call transcripts, meeting notes).
6. BD handover / internal notes.

Do not infer a missing answer from a lower-authority source when a
higher-authority source is silent - record it as an Open Question instead
(Section 5).

---

## 4. Procedure

1. **Read the entire verified source corpus** under `docs/pmo/sources/`,
   per its category/authority classification from `project-initialization`.
2. **Draft the Intent sections**, each citing the specific source(s) it
   derives from - never left unsourced:
   - Client Vision, Business Problem, Overall Client Goal, Proposed Product
     Outcome
   - Users, Actors and Systems
   - High-Level Product Requirements (`INT-REQ-001`, `INT-REQ-002`, ... -
     capability-level only, no detailed functional/acceptance criteria)
   - Constraints, Explicitly Out of Scope (`INT-OOS-*`), Dependencies
   - Assumptions (`ASM-*`) - only where the source corpus genuinely
     requires one to proceed, stated explicitly rather than built in
     silently
   - Open Questions (`OPEN-*`) - every genuine ambiguity the corpus leaves
     unresolved, each with `Owner`, `Blocking`, `Required Before`
   - Contradictions / Source Conflicts (`CONFLICT-*`) - where two
     authoritative sources genuinely disagree
   - Risks Carried Into Requirement Gathering
   - Source Register - every consulted source, with its category and
     authority
3. **Do not fabricate** a requirement, constraint, assumption, or resolved
   open question that the corpus does not support. An `ASM-*` records a
   genuine assumption; it is never a disguised invented answer.
4. **Write `docs/pmo/intent/intent.md`** with `Status: DRAFT` and the
   Document Control block `intent-schema-guard.py` requires (Project,
   Client, Project ID, Date, Intent Version, Status, Source Count).
5. **Stop at DRAFT.** This skill never sets `Status: VALIDATED` itself -
   only the PM-approval transaction
   (`intent-approval-recorder.py begin` / `finalize`) does that, and only
   after the PM has explicitly reviewed the draft (Section 6). If the PM
   raises further decisions during review, record them as an explicit,
   dated PM Decision Register entry (mirroring WM Trucking Intent v0.3's
   own precedent) and produce the next Intent Version - still `DRAFT` -
   rather than silently editing the prior version's content in place.

---

## 5. What Intent is - and is not

Intent is not a rewritten Scope or Specs document. It stays at the
strategic/business level:

- capability-level requirements (`INT-REQ-*`), never detailed functional
  behavior, acceptance criteria, data models, or UI flows;
- genuine open questions the source corpus leaves unresolved, never
  invented resolutions;
- a Source Register tracing every claim back to a specific document,
  never an unsourced assertion.

An Intent that reads like a Scope or Specs document (detailed acceptance
criteria, UI flows, field-level data definitions) has over-reached its
stage - trim it back to capability level and let `requirement-gathering` /
`spec-generation` own the detail.

---

## 6. PM review and the path to VALIDATED

Intent becomes `VALIDATED` only through the existing, unchanged governed
transaction:

```
intent-approval-recorder.py begin --approved-by "<PM name>" \
    --decision-date <date> --statement "<explicit approval statement>"
    -> intent-approval-recorder.py finalize
```

This skill never invokes that transaction itself and never sets
`Status: VALIDATED` by direct edit - `intent-schema-guard.py`'s own
immutability rule (`PMO-INTENT-009`) and `intent_approval_core.py`'s
approval validation are the sole authority for that transition, exactly as
they already are today.

---

## 7. Quality validation rules

An Intent draft is valid only when:

1. Every `INT-REQ-*`, `ASM-*`, `OPEN-*`, `CONFLICT-*`, and `RISK-*` item
   cites specific source(s) in the Source Register.
2. No item is invented beyond what the corpus supports.
3. Document Control identity (`Project` / `Client` / `Project ID`) matches
   `.pmo/project-config.yaml` exactly (`intent-schema-guard.py`'s own
   identity check).
4. `Status` is `DRAFT` on every write this skill performs - never
   `VALIDATED`.
5. No `FR-*` / `NFR-*` / `SCP-REQ-*` identifier appears anywhere (reserved
   for Specs / legacy Scope respectively - `intent-schema-guard.py`'s own
   `validate_no_fr_nfr`).

---

## 8. Guardrails - MUST NOT

- MUST NOT set `Status: VALIDATED` - that is exclusively
  `intent-approval-recorder.py finalize`'s job, gated on an explicit PM
  approval action.
- MUST NOT fabricate a requirement, assumption, resolved question, or
  source citation.
- MUST NOT silently overwrite a VALIDATED Intent - route a later change
  through a fresh, explicitly PM-decided revision (a new Intent Version,
  still starting DRAFT), never a direct edit of governed content.
- MUST NOT write detailed functional/acceptance criteria, data models, or
  UI flows - that is `spec-generation`'s job.
- MUST NOT generate `docs/pmo/requirements/questions-and-assumptions.md`
  or `docs/pmo/specs/specs.md` - those remain
  `requirement-gathering` / `spec-generation`'s own stages.
- MUST NOT commit or push.

---

## 9. Definition of done

- `docs/pmo/intent/intent.md` exists with `Status: DRAFT`, a complete
  Document Control block matching `.pmo/project-config.yaml` identity, and
  every substantive item sourced.
- No requirement, assumption, or resolution was fabricated.
- Intent is left `DRAFT`, explicitly awaiting the separate, PM-driven
  approval transaction.
- The **PMO INTENT GENERATION RESULT** report (Section 10) is emitted.

---

## 10. Final output - PMO INTENT GENERATION RESULT

On completion, emit:

```
PMO INTENT GENERATION RESULT

Project:                <project.name>
Intent Artifact:         docs/pmo/intent/intent.md
Intent Version:          <version>
Status:                  DRAFT
Sources Consulted:       <count>
High-Level Requirements: <count of INT-REQ-*>
Assumptions:             <count of ASM-*>
Open Questions:          <count of OPEN-*>  (<count> Blocking)
Conflicts:               <count of CONFLICT-*>
Validation:              PASS | BLOCKED (<reason>)
Next Human Gate:         PM INTENT APPROVAL (intent-approval-recorder.py)
Next Workflow:           REQUIREMENT_GATHERING (once VALIDATED + approved)
```
