---
name: requirement-gathering
description: >-
  Turn a VALIDATED, PM-approved PMO Intent into a lightweight Questions &
  Assumptions register under docs/pmo/requirements/questions-and-assumptions.md
  - the NEW-lifecycle stage between Intent approval and Specification
  Generation. Use after docs/pmo/intent/intent.md reaches Status VALIDATED
  with a matching PM approval record. Reads the validated Intent end to end
  plus the verified source corpus, identifies only genuinely unresolved
  QUESTION / ASSUMPTION items that require human confirmation, and carries
  forward every already-resolved, already-deferred or already-non-blocking
  Intent decision unchanged rather than restating it or rebuilding a
  feature-by-feature scope narrative. Produces stable QST-### (question) /
  ASM-### (assumption) records - ID, Type, Statement, Why Resolution Is
  Required, Source / Evidence, Related Intent Item, Owner, Status, Blocking,
  Resolution, Resolution Authority, Resolution Evidence / Date, Specs Impact
  - with allowed statuses OPEN / CONFIRMED / REJECTED / RESOLVED / DEFERRED /
  NON_BLOCKING. Does NOT generate a Scope document and does NOT write to
  docs/pmo/scope/ - Scope generation remains available only for LEGACY
  projects that already have a pre-existing Scope lineage; a project with
  none proceeds Intent -> Questions & Assumptions -> Specifications directly,
  with no mandatory Scope stage. PMO-QA-* failure conditions (enforced by the
  installed .claude/hooks/qa-register-guard.py) define deterministic halt
  behaviour. Resolving every Blocking Q&A item authorises Specification
  Generation; Development remains gated on approved Specifications, never on
  this register directly.
---

# Requirement Gathering (PMO)

## 1. Purpose and position in the PMO lifecycle

Artifact roles across the PMO lifecycle:

- **Intent** preserves **WHY** the project exists and its original context,
  and already carries the confirmed high-level requirements (`INT-REQ-*`),
  resolved assumptions (`ASM-*`) and PM decisions reached during Intent
  validation.
- **Questions & Assumptions** (this stage) closes the **specific remaining
  gaps** between a validated Intent and a build-ready Specification - nothing
  more.
- **Specifications** (`specs.md`) establish the **precise behaviour** for
  Development and QA.

Target lifecycle for a project with no pre-existing Scope lineage:

```
Source Evidence
  -> Intent
    -> PM Intent Approval
      -> Questions & Assumptions
        -> PM / Client / Technical Resolution
          -> Specification Generation
            -> PM Specs Review / Approval
              -> Development
                -> Feedback / CR governance
```

**There is no mandatory Scope-generation stage between Intent approval and
Specification Generation.** A project that already has a Scope artifact under
`docs/pmo/scope/` is a LEGACY project and continues on its existing Scope ->
Specs path unchanged (Section 14) - this skill does not touch it. A project
with none never creates one; it uses this stage instead.

This stage:

- does **not** write functional/technical specifications (`specs.md`);
- does **not** write a Scope document or anything under `docs/pmo/scope/`;
- does **not** restate requirements the Intent has already confirmed;
- does **not** authorise development or create developer task identifiers;
- produces **only** the register of matters that still require a human
  decision before Specification Generation can proceed responsibly.

`.pmo/project-config.yaml` governance applies throughout: `source_of_truth:
repository`, `markdown_authoritative: true`, `silent_assumptions_prohibited:
true`. Any `workflow.requirements.*` / `artifacts.requirements.*` field this
stage writes is **derived / display state only** - it records where the
project is, but Specification Generation never authorises itself from those
fields; it re-reads the canonical Intent, approval record and Q&A register
directly every time (Section 9, Section 13).

---

## 2. Prerequisites - hard gate

Do **not** begin Requirement Gathering unless **all** of the following hold:

1. `docs/pmo/intent/intent.md` exists with Document Control `Status:
   VALIDATED` and a non-empty `Intent Version`.
2. A structurally valid, matching PM approval record exists at
   `.pmo/approvals/intent-approval.yaml`: `decision: APPROVED`,
   `approval_source: PM_EXPLICIT`, `artifact: docs/pmo/intent/intent.md`, a
   non-empty `approved_by`, and `version` equal to the Intent's `Intent
   Version`.
3. The Intent's project identity (`Project` / `Client` / `Project ID`)
   matches `.pmo/project-config.yaml`.

There is deliberately **no numeric Intent-version floor** - a VALIDATED
Intent is a legitimate governed baseline at any version (e.g. `0.3`) once a
matching PM approval exists. This is exactly the same prerequisite rule
`scope-version-guard.py` enforces for Scope entry (`PMO-SCOPE-001`) and
`intent-schema-guard.py` enforces for the Intent's own VALIDATED transition
(`PMO-INTENT-011`) - reused unchanged via `intent_approval_core.py`, so there
is no duplicated approval-validation truth anywhere in the framework.

If any prerequisite fails, stop and report which one (`PMO-QA-001`, Section
12). Do not draft the register from an unvalidated Intent.

---

## 3. Source authority hierarchy and conflict handling

Unchanged from the framework's general evidentiary discipline:

1. **Validated Intent** - authoritative for WHY, the actor set, and every
   already-confirmed `INT-REQ-*`.
2. **Executed contract / signed SOW**.
3. **Approved commercial scope / LOE**.
4. **Formal client requirements**.
5. **Client written communications** (emails, messages).
6. **Recorded client discussions** (call transcripts, meeting notes).
7. **BD handover / internal notes**.

A conflict between sources is never silently resolved: it is either already
dispositioned in the Intent (carry that disposition forward, do not reopen
it) or, if genuinely new, becomes a Q&A record with `Type: QUESTION`,
`Why Resolution Is Required` naming the conflict, and both positions cited
under `Source / Evidence`.

---

## 4. Inputs

- **Primary:** the VALIDATED `docs/pmo/intent/intent.md` - every section,
  every `INT-REQ-*`, `ASM-*`, `OPEN-*`, `CONFLICT-*`, `RISK-*`, `SRC-*`, and
  its PM Decision Register where one exists.
- **Evidence:** the verified source corpus under `docs/pmo/sources/`
  registered as `SRC-*` in the Intent's Source Register - consulted only to
  identify a genuinely new ambiguity or to corroborate a record's `Source /
  Evidence` field, never as a route to restate what the Intent already
  confirmed.
- **`.pmo/project-config.yaml`** for project identity.
- **The current register**, if this is not the first run - see Section 9
  (append / update semantics).

Do not infer a missing answer. An unresolved matter becomes a Q&A record;
never a silent assumption embedded in a later artifact.

---

## 5. Output and file naming

| Artifact | Path |
|---|---|
| Questions & Assumptions register (the only artifact this stage produces) | `docs/pmo/requirements/questions-and-assumptions.md` |

This is a **single canonical, continuously-live file** - not a versioned
draft series like Scope. There is no `questions-and-assumptions-v0.1.md`;
history lives in git, exactly as it does for `specs.md`. Any other filename
under `docs/pmo/requirements/` (a `-v2`, `-final`, `-latest` variant) is
rejected by the installed guard (`PMO-QA-010`).

**This stage never creates `docs/pmo/scope/scope-v0.1.md` or any file under
`docs/pmo/scope/`.** That path exists only for LEGACY projects that already
have one (Section 14).

---

## 6. What the register is - and is not

The register is **not** a rewritten Scope document. It does not restate
platforms, actors, modules, workflows, or every `INT-REQ-*` the Intent
already confirmed - that would just be Scope under a new name, and
duplicates a source of truth this redesign deliberately removed.

It contains **only** matters that:

- the validated Intent left genuinely open (a carried `OPEN-*` still without
  a PM/client/source-evidence answer), **or**
- a fresh read of the source corpus surfaces as a real ambiguity the Intent
  did not anticipate, **or**
- require an explicit assumption to proceed toward Specification Generation,
  recorded as such rather than silently built in.

An Intent decision that is already `RESOLVED` / `CONFIRMED` (by source
evidence or by explicit PM decision) is **not** re-entered here. Carry it
forward by reference only if a later Specs record needs to trace to it
(`Related Intent Item`); do not duplicate its content into a new Q&A record.

---

## 7. Record model

Each record is a `#### QST-###` or `#### ASM-###` heading followed by its
fields:

```
#### QST-004 - Payment gateway selection

- **ID:** QST-004
- **Type:** QUESTION
- **Statement:** Which payment gateway will the checkout flow integrate?
- **Why Resolution Is Required:** Blocks FR design for the checkout payment step.
- **Source / Evidence:** SRC-001 (SOW §26); client email SRC-008
- **Related Intent Item:** OPEN-002
- **Owner:** PM / Client
- **Status:** OPEN
- **Blocking:** YES
- **Resolution:**
- **Resolution Authority:**
- **Resolution Evidence / Date:**
- **Specs Impact:** Blocks the FR covering payment-method selection at checkout.
```

| Field | Meaning |
|---|---|
| `ID` | `QST-###` (question) or `ASM-###` (assumption) - stable, never renumbered or reused. |
| `Type` | Exactly `QUESTION` or `ASSUMPTION`. |
| `Statement` | Plain-language description of the question or the assumption being made. |
| `Why Resolution Is Required` | The concrete downstream impact if left unresolved (what it blocks or shapes). |
| `Source / Evidence` | `SRC-*` reference(s) or explicit "no corpus evidence" note. Never blank. |
| `Related Intent Item` | The Intent id this traces to (`OPEN-*`, `ASM-*`, `INT-REQ-*`), where applicable. Optional - leave blank for a genuinely new item. |
| `Owner` | Who must resolve it (PM / Client / Technical / PM+Client). |
| `Status` | One of `OPEN`, `CONFIRMED`, `REJECTED`, `RESOLVED`, `DEFERRED`, `NON_BLOCKING` (Section 8). |
| `Blocking` | Explicitly `YES` or `NO` - never inferred, never omitted (Section 8). |
| `Resolution` | What was decided (required once Status claims a resolution/disposition - Section 8). |
| `Resolution Authority` | Who decided - `PM_EXPLICIT`, `CLIENT`, or the specific `SRC-*` that resolved it by direct source evidence, distinguished exactly as the Intent's own PM Decision Register distinguishes management authority from documentary evidence. |
| `Resolution Evidence / Date` | The citation or date backing the resolution. Required for `CONFIRMED` / `REJECTED` / `RESOLVED`; a `DEFERRED` / `NON_BLOCKING` item still needs `Resolution` + `Resolution Authority`, but no date is invented if none exists (mirrors Intent `OPEN-002`'s `NON_BLOCKING_FUTURE_DECISION`). |
| `Specs Impact` | What Specification Generation must do with this record once it resolves (which FR/NFR it shapes, or "carries forward as a traceable TBD" for a deferred/non-blocking item). |

Carried-forward Intent `OPEN-*` questions keep their **exact** `OPEN-*` id
here too when a record is opened for one - the same lifecycle-identity rule
Scope enforces (`PMO-SCOPE-015`); a Q&A record about a carried Intent
question cites it under `Related Intent Item`, it does not invent a new
`QST-*` identity for something the Intent already numbered.

---

## 8. Blocking semantics

Every record explicitly states whether it currently blocks Specification
Generation, and that is a function of **`Status` and `Blocking` together**,
never of `Blocking` alone:

| Status | Blocking | Effect on Specs generation |
|---|---|---|
| `OPEN` | `YES` | **Blocked.** This is the only combination that blocks. |
| `OPEN` | `NO` | Permitted; the item stays visible and unresolved. |
| `CONFIRMED` | any | Permitted. |
| `RESOLVED` | any | Permitted. |
| `REJECTED` | any | Permitted, **provided** `Resolution` states how the rejected question/assumption is actually handled (e.g. the feature it would have unlocked is explicitly out of scope for this baseline) - a bare `REJECTED` with no handling note is a schema defect (`PMO-QA-008`). |
| `DEFERRED` | `NO` | Permitted; the deferred decision must remain traceable in `specs.md` (`Specs Impact`). |
| `NON_BLOCKING` | any | Permitted and traceable. |

**Never silently convert an unanswered item to non-blocking.** A `Status`
change away from `OPEN`, or a `Blocking` change to `NO`, is only ever made
because a real decision happened (Section 9) - never as a way to clear the
gate.

---

## 9. Lifecycle governance - append / update semantics, authority, history

- **Stable ID convention.** `QST-###` / `ASM-###`, allocated by inspecting
  the real register (never from conversation history), and **never
  renumbered or reused** - the same discipline `SCP-REQ-*` and `FR-*` already
  follow elsewhere in this framework.
- **Append vs. update.** A new record appends. An existing record's
  `Status` / `Resolution` / `Resolution Authority` / `Resolution Evidence /
  Date` fields update in place as a governed transition - the record's
  `Statement` and identity never change; a materially different question
  becomes a new id, not a rewritten old one.
- **Who may resolve an item.** `Resolution Authority` distinguishes exactly
  three sources, mirroring the Intent's own PM Decision Register:
  - `PM_EXPLICIT` - an explicit PM management decision (not client approval,
    not source evidence).
  - `CLIENT` - an explicit client decision or confirmation.
  - a cited `SRC-*` - resolved directly by existing documentary evidence,
    with no PM/client decision needed.
  A record is never marked resolved on an inferred or assumed basis.
- **Deferred / non-blocking items** stay in the register indefinitely (or
  until later resolved) with `Resolution Authority` naming who made the
  deferral call and `Resolution` stating the rationale - no date is invented
  if none exists.
- **Rejected assumptions/questions** are recorded, not deleted -
  `Resolution` states the disposition so a later reader (or Specification
  Generation) knows exactly what was decided and why, not just that it was
  closed.
- **No silent loss of resolution history.** A record that already carried a
  recorded resolution or disposition must not have it silently blanked, nor
  can the whole record disappear from the file, without an explicit,
  visible reopen (`Status: OPEN`). The installed guard enforces this
  deterministically (`PMO-QA-009`).
- **Guard, not a transaction.** This is ordinary, guard-governed Markdown
  editing - file/Git based, exactly as Phase 1 requires. There is no marker
  file, no multi-artifact atomic transaction; a single record update is a
  single ordinary `Edit`/`Write`, validated on save by
  `.claude/hooks/qa-register-guard.py` (Section 12).

---

## 10. Procedure

1. **Verify the gate** (Section 2). Stop and report on failure (`PMO-QA-001`).
2. **Read project state:** load `.pmo/project-config.yaml`; confirm project
   identity; read the validated `intent.md` end to end, including its PM
   Decision Register where present; read the current
   `questions-and-assumptions.md` if one already exists (an update run).
3. **Consult the source corpus** registered as `SRC-*` in the Intent, where
   needed to corroborate a new item or check a carried `OPEN-*` for evidence
   the Intent may not have had.
4. **Identify unresolved matters only:**
   - every Intent `OPEN-*` that is still genuinely open (not already
     `RESOLVED` / classified `NON_BLOCKING_FUTURE_DECISION` /
     `RESOLVED_WITH_PENDING_CONFIGURATION` by the Intent itself - those
     carry forward unchanged, they are **not** re-opened here);
   - a new ambiguity the source corpus surfaces that the Intent did not
     anticipate;
   - an assumption genuinely required to let Specification Generation
     proceed, stated explicitly as `Type: ASSUMPTION` rather than built in
     silently.
5. **Do not restate** any Intent decision that is already resolved,
   confirmed, or explicitly classified non-blocking/deferred by the Intent
   itself. If a later Specs record needs to trace to it, reference the
   Intent id directly (`Related Intent Item`) - do not duplicate it into a
   new `QST-*` / `ASM-*` record.
6. **Write or update** `docs/pmo/requirements/questions-and-assumptions.md`
   - append new records; update existing records' resolution fields in
     place per Section 9. First run creates the file with its Document
     Control block (Project, Client, Project ID, PM, Date, Intent Version)
     plus the register.
7. **Classify Blocking** on every record explicitly (Section 8) - never
   left implicit.
8. **Run the quality checks** (Section 11) before finishing.
9. **Emit the final report** (Section 15). Do not generate `specs.md`; do
   not create a Scope artifact; do not commit or push unless asked.

---

## 11. Quality validation rules

A register is quality-valid only when **all** of the following hold:

1. Every record has a stable `QST-###` / `ASM-###` id, never renumbered or
   reused; no id is defined twice.
2. Every record has a valid `Type` (`QUESTION` / `ASSUMPTION`) and a valid
   `Status` (Section 7's six values).
3. Every record has an explicit `Blocking` value - `YES` or `NO`, never
   blank, never inferred.
4. Every record has `Statement`, `Why Resolution Is Required`, `Source /
   Evidence` and `Owner` populated - no fabricated evidence, no blank
   rationale.
5. A record with `Status` in `CONFIRMED` / `REJECTED` / `RESOLVED` has
   `Resolution`, `Resolution Authority` and `Resolution Evidence / Date` all
   populated.
6. A record with `Status` in `DEFERRED` / `NON_BLOCKING` has `Resolution`
   and `Resolution Authority` populated (no date fabricated if none exists).
7. No record that previously carried a resolution has had it silently
   blanked or the record removed without an explicit reopen to `OPEN`.
8. No Intent decision already `RESOLVED` / `CONFIRMED` / explicitly
   classified non-blocking or deferred by the Intent itself has been
   restated as a new open record here.
9. No `SCP-REQ-*`, `FR-*`, `NFR-*` or any Scope-namespace identifier appears
   anywhere in this artifact - those belong to Scope (legacy only) and Specs
   respectively, never to this register.
10. Nothing under `docs/pmo/scope/` was created or modified by this run.

---

## 12. Failure Conditions

`.claude/hooks/qa-register-guard.py` is the **installed deterministic
enforcement** for this artifact, and its implemented `PMO-QA-*` semantics are
the governance contract. This table documents the same codes with the same
meaning; if this document and the hook ever disagree, the hook wins.

| Code | Name | Condition | Remediation |
|---|---|---|---|
| `PMO-QA-001` | `INTENT_NOT_VALIDATED` | The canonical Intent is absent, not `VALIDATED`, lacks a structurally valid matching PM approval record, or its project identity does not match project-config. | Complete and validate the Intent first (Section 2); do not draft the register against an unvalidated Intent. |
| `PMO-QA-002` | `PROJECT_IDENTITY_MISMATCH` | The register's Document Control `Project` / `Client` / `Project ID` does not match `.pmo/project-config.yaml`. | Align the identity fields - project-config is the authority. |
| `PMO-QA-003` | `QA_SCHEMA_INVALID` | A required Document Control field is absent, or a record is missing `Statement` / `Why Resolution Is Required` / `Source / Evidence` / `Owner`. | Complete the missing field(s). |
| `PMO-QA-004` | `INVALID_TYPE` | A record's `Type` is not `QUESTION` or `ASSUMPTION`. | Correct the value. |
| `PMO-QA-005` | `INVALID_STATUS` | A record's `Status` is not one of the six allowed values (Section 7). | Correct the value. |
| `PMO-QA-006` | `INVALID_BLOCKING` | A record's `Blocking` value is not explicitly `YES` or `NO`. | Set it explicitly - it is never inferred. |
| `PMO-QA-007` | `DUPLICATE_OR_INVALID_ID` | An id is defined more than once, or is not exactly `QST-###` / `ASM-###`. | Fix the id; allocate a new one rather than reusing/renumbering. |
| `PMO-QA-008` | `RESOLUTION_REQUIRED` | A record claims `CONFIRMED` / `REJECTED` / `RESOLVED` / `DEFERRED` / `NON_BLOCKING` without the resolution fields that status requires (Section 8, Section 11 rules 5-6). | Complete `Resolution` / `Resolution Authority` (/ `Resolution Evidence / Date` for the resolved-class statuses), or leave the record `OPEN` until it genuinely is decided. |
| `PMO-QA-009` | `RESOLUTION_REGRESSION` | A previously recorded resolution or disposition was silently blanked, or the record disappeared, without an explicit reopen (`Status: OPEN`). | Reopen explicitly, or restore the prior resolution; never blank it silently. |
| `PMO-QA-010` | `NON_CANONICAL_QA_PATH` | The live artifact targeted is not exactly `docs/pmo/requirements/questions-and-assumptions.md`. | Write to the canonical path; the register has no versioned filename variants. |
| `PMO-QA-011` | `QA_GUARD_INTERNAL_ERROR` | Unexpected exception during a controlled validation. | Fail-closed by design; fix the malformed input and retry. |

---

## 13. Relationship to Specification Generation

**A resolved-or-classified Q&A register does not itself write `specs.md`.**
The correct flow is:

```
Intent VALIDATED (+ matching PM approval)
  -> Questions & Assumptions register (this stage)
    -> no unresolved Blocking record remains
      -> Specification Generation reads Intent + the register directly
        -> Specifications validated / approved under their own governance
          -> Development
```

- Specification Generation's NEW-lifecycle entry gate re-reads the canonical
  Intent, the approval record, and this register **directly** - it never
  authorises itself from a project-config boolean (`PMO-SPEC-021` /
  `-022` / `-023` in `spec-generation`'s own governance).
- A `DEFERRED` / `NON_BLOCKING` record does not vanish once Specs generation
  proceeds - its `Specs Impact` field is exactly how the deferred decision
  stays traceable inside `specs.md` (an explicit TBD / open item, never a
  silently dropped question).
- **A post-baseline Q&A resolution that materially changes already-approved
  Specs functionality must not bypass Change Request governance.** Resolving
  a Q&A record after `specs.md` has reached an approved baseline is not, by
  itself, authority to edit that baseline directly - see
  `change-request-management`.

---

## 14. Legacy Scope compatibility

Existing projects that already have a Scope lineage under `docs/pmo/scope/`
are **LEGACY** projects. This skill does not run for them in the sense
described above; their existing `Requirement Gathering -> Scope ->
Specification Generation` path (Scope drafts, `SCP-REQ-*`, the
`scope-version-guard.py` governance, client Scope approval) continues to
apply unchanged, and remains fully documented in git history / prior
versions of this skill. `scope-version-guard.py` remains installed and
active for any write to an existing Scope artifact; it simply never fires
for a project that has none.

**A new project is never required to manufacture an empty Scope artifact for
compatibility.** The framework selects the path deterministically by
artifact presence: if `docs/pmo/scope/` contains at least one
`scope-v*.md`, the project is on the LEGACY path; if it contains none, the
project is on the NEW path described in this document. This is never a
project-config flag - it is read directly from what actually exists on disk.

---

## 15. Guardrails - MUST NOT

- MUST NOT start without a VALIDATED Intent + matching PM approval record
  (Section 2).
- MUST NOT write a Scope document, or anything under `docs/pmo/scope/`.
- MUST NOT restate an Intent decision that is already resolved, confirmed,
  or explicitly classified non-blocking/deferred by the Intent itself.
- MUST NOT produce feature-by-feature scope prose, a context map, a module
  map, a work-breakdown structure, or any other Scope-shaped content - this
  register is a list of open matters, not a rewritten Scope.
- MUST NOT silently convert an unanswered (`OPEN` + `Blocking: YES`) item to
  non-blocking, deferred, or resolved.
- MUST NOT fabricate a resolution, a date, a source citation, or an owner.
- MUST NOT renumber or reuse a `QST-*` / `ASM-*` id.
- MUST NOT silently blank a previously recorded resolution or delete a
  record that carried one, without an explicit reopen to `OPEN`.
- MUST NOT create `FR-*` / `NFR-*` / `SCP-REQ-*` identifiers - those belong
  to Specifications / legacy Scope respectively.
- MUST NOT modify `docs/pmo/intent/intent.md`, `.pmo/approvals/intent-
  approval.yaml`, existing skills, or existing hooks.
- MUST NOT generate `specs.md`, plan development, or begin Specification
  Generation.
- MUST NOT set any project-config field as if it were an authorization
  source - any `workflow.requirements.*` / `artifacts.requirements.*` field
  this stage writes is derived/display state only (Section 1).
- MUST NOT commit or push unless explicitly asked.

---

## 16. Definition of done

- `docs/pmo/requirements/questions-and-assumptions.md` exists (or is
  updated) with a complete Document Control block.
- Every record has a stable id, a valid `Type`, a valid `Status`, an
  explicit `Blocking` value, and all fields Section 11 requires for that
  status.
- No Intent decision already resolved/confirmed/classified is restated.
- No Scope artifact was created or touched.
- No previously recorded resolution was silently lost.
- The **PMO REQUIREMENT GATHERING RESULT** report (Section 17) is emitted.

---

## 17. Final output - PMO REQUIREMENT GATHERING RESULT

On completion, emit:

```
PMO REQUIREMENT GATHERING RESULT

Project:                <Project>
Q&A Artifact:            docs/pmo/requirements/questions-and-assumptions.md
Intent Baseline:         <Intent version / status>
Sources Consulted:       <count>
Total Records:           <count>
Questions:               <count of QST-*>
Assumptions:             <count of ASM-*>
Open Blocking:           <count> (IDs)
Open Non-Blocking:       <count> (IDs)
Confirmed / Resolved:    <count>
Rejected:                <count>
Deferred / Non-Blocking: <count>
Carried Intent Items Referenced (not restated): <count> (IDs)
Validation:              PASS / BLOCKED
Specs Generation:        AUTHORISED / BLOCKED (Blocking items remain)
Next Human Gate:         PM / CLIENT / TECHNICAL RESOLUTION
Next Workflow:           SPECIFICATION_GENERATION (once no Blocking record remains)
```

`Validation: BLOCKED` whenever any `PMO-QA-*` condition applies or any
Section 11 quality rule fails; the report then lists the offending IDs.
`Specs Generation: BLOCKED` whenever at least one record is `OPEN` with
`Blocking: YES` - this is reported even when `Validation: PASS`, since a
structurally clean register can still leave Specs generation blocked on
substance.

---

## 18. Installed control

Structural, identity, id-stability and resolution-integrity enforcement for
this artifact is provided by the **installed**
`.claude/hooks/qa-register-guard.py` PreToolUse hook (the Q&A analogue of
`scope-version-guard.py`), which implements the `PMO-QA-*` conditions in
Section 12 deterministically, reusing `intent_approval_core.py`'s Intent /
approval validation unchanged. This skill does not modify that hook; its
output must satisfy every rule above so the hook passes. Regression coverage
lives in `.claude/hooks/test_qa_register_guard.py`. The hook is the authority
for the `PMO-QA-*` contract - if this document and the hook ever disagree,
the hook wins and this document is corrected to match it (never the
reverse).
