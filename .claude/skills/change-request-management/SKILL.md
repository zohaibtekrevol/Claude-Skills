---
name: change-request-management
description: >-
  Own the full governed Change Request lifecycle for both CR origins:
  CLIENT_REQUESTED (handed off from feedback-management as a DRAFT CR under
  docs/pmo/cr/) and PM_PROPOSED (created directly here, Mode B, when the PM
  proposes additional scope to the client). Both origins share one lifecycle
  — DRAFT -> PM_REVIEW -> PENDING_CLIENT_DECISION -> APPROVED ->
  INCORPORATED, with REJECTED / DEFERRED / CANCELLED off-ramps — and the same
  approval authority: proposing or classifying a CR is never authorization,
  only explicit approval evidence (Decision + Decision Date + Decision By +
  Approval Evidence, recorded at PENDING_CLIENT_DECISION -> APPROVED) is. This
  Skill allocates CR-NNN identifiers by inspecting the real register (never
  from conversation history), never renumbers or reuses one — including after
  REJECTED/CANCELLED, where a later reconsideration becomes a new CR with a
  Related Prior CR back-reference — and preserves append-only lifecycle
  history so a later cancellation never erases a prior approval. It owns the
  single governed transaction an APPROVED CR must pass through to reach
  INCORPORATED — a new immutable Scope version, an in-place specs.md update
  (never specs-v0.2.md), and exactly one new Change Log (CHG-NNN) entry, all
  three or none — but this Skill itself never authors that content or
  executes the transaction: it always performs the actual Scope/Specs/
  Change Log edits as ordinary, guard-governed Write/Edit calls, and hands
  transaction execution/reconciliation to the deterministic orchestrator
  .claude/scripts/change-request-incorporator.py (begin / status / validate
  / finalize), sharing one implementation,
  .claude/lib/change_request_incorporation_core.py, with
  change-request-governance-guard.py so the two can never disagree.
  INCORPORATED is never reported on a partial transaction; a genuine
  inconsistency moves the transaction marker to RECOVERY_REQUIRED rather
  than silently rolling back or falsely succeeding. Never writes
  Scope/specs.md/Change Log outside that governed transaction, never commits
  or pushes. PMO-CR-001 … PMO-CR-023 (Skill-level), PMO-CR-GUARD-001 …
  PMO-CR-GUARD-026 (guard), and PMO-CR-INTEGRATE-001 … PMO-CR-INTEGRATE-025
  (orchestrator) define deterministic halt behaviour, in namespaces disjoint
  from each other and from PMO-FEEDBACK-*, PMO-FEEDBACK-GUARD-*,
  PMO-SCOPE-*, PMO-SPEC-*, and PMO-PUBLISH-*.
---

# Change Request Management (PMO)

## 1. Purpose and position in the PMO lifecycle

Artifact/Skill roles across the PMO lifecycle:

- **Intent** preserves **WHY** the project exists.
- **Scope** establishes **WHAT** is being delivered (commercial/product
  boundary), owned by `requirement-gathering`.
- **Specifications** (`specs.md`) establish the **precise behaviour** Dev
  builds and QA verifies, owned by `spec-generation`.
- **Feedback Management** captures and classifies feedback; a
  `CHANGE_REQUEST`-classified item produces a `DRAFT` `CLIENT_REQUESTED` CR
  and stops there.
- **Change Request Management** (this Skill) owns everything from that
  `DRAFT` CR onward — and the entire lifecycle of a `PM_PROPOSED` CR from its
  first moment — through review, client decision, approval, and (once
  approved) the single governed transaction that actually changes Scope,
  `specs.md`, and the Change Log.

This Skill sits **between** "a proposed scope change exists" and "the
governed requirement baseline reflects it." Its defining discipline, repeated
throughout this document because it is the one rule every other rule serves:

> **Classification is not approval. Proposal is not approval. PM creation is
> not approval.** A CR may modify Scope/`specs.md` only after explicit
> approval evidence has been recorded (Section 12) **and** every
> incorporation precondition (Section 18) is satisfied.

`.pmo/project-config.yaml` governance applies throughout: `source_of_truth:
repository`, `markdown_authoritative: true`, `approved_artifacts_immutable:
true`, `silent_assumptions_prohibited: true`. This Skill additionally
implements the Phase-1A CR/Change Log contracts it consumes (Section 5) and
does not redefine them.

---

## 2. Authority — what this Skill owns and does not own

**Owns:**

- `PM_PROPOSED` CR creation (Mode B, Section 4/9)
- reading `CLIENT_REQUESTED` `DRAFT` CRs handed off from `feedback-management`
  (Section 8) and taking ownership of them from that point
- every CR lifecycle transition (Section 11): PM review state, client-decision
  state, approval evidence, rejection evidence, deferral evidence,
  cancellation evidence
- reconsideration/supersession relationships between CRs (Section 15)
- preparation for incorporation — validating preconditions (Section 18)
- the approved-CR incorporation transaction as a **contract** (Section 19):
  Scope revision orchestration, `specs.md` revision orchestration, Change Log
  creation, and marking a CR `INCORPORATED` only after all three succeed
  (implementation and enforcement guard are **explicitly out of scope for
  this phase** — see Section 30)

**Does not own — never performs:**

- feedback classification, Feedback Batch creation, or Feedback Item
  classification history (owned by `feedback-management`) — this Skill may
  **read** feedback provenance for context (Section 8) but never edits it
- Development execution or QA execution
- payment / invoice / collection / commercial-approval tracking (Section 27)
- repository publishing itself — `git commit`, `git push`, branch
  creation/switching, remote selection (owned by `artifact-publish`,
  Section 28)
- arbitrary Scope edits unrelated to an approved CR (only `requirement-
  gathering`'s own governed drafting, or this Skill's incorporation
  transaction for an `APPROVED` CR, may ever write `docs/pmo/scope/`)
- arbitrary `specs.md` edits unrelated to an approved CR (only `spec-
  generation`'s own governed drafting, or this Skill's incorporation
  transaction for an `APPROVED` CR, may ever write `docs/pmo/specs/specs.md`)

---

## 3. CR origins

Exactly two, both using the **same** lifecycle (Section 11) and the **same**
approval authority (Section 12):

| Origin | Meaning | Provenance rule |
|---|---|---|
| `CLIENT_REQUESTED` | Identified from client feedback classified `CHANGE_REQUEST` by `feedback-management` | `Origin Feedback Batch` and `Origin Feedback Item` are **REQUIRED**, must already exist, and must be mutually consistent (the batch contains that item, and the item's `Related CR` points back to this CR — `feedback-management` already established this bidirectional link before handoff; this Skill re-verifies it, never assumes it, per Section 8). |
| `PM_PROPOSED` | Additional/new scope the PM proposes directly to the client, not via client feedback | `Origin Feedback Batch` and `Origin Feedback Item` **must not be fabricated**. Both fields carry the literal canonical value already established by the Phase-1A CR contract: `"No Feedback ID — PM_PROPOSED"` — never `NONE`, never a blank, never an invented Feedback ID. |

A PM proposing additional scope is **not** self-authorizing it: `PM_PROPOSED`
CRs pass through the identical `PENDING_CLIENT_DECISION → APPROVED` gate as
`CLIENT_REQUESTED` CRs before incorporation (Section 12, "PM-Proposed
Approval").

---

## 4. PM entry mode — Mode B: Create PM-Proposed CR

This is the one PM-initiated **creation** entry point this Skill owns
(reading/transitioning an existing CR, Section 26, is a separate class of
operation). The PM provides:

| Field | Required to start? |
|---|---|
| Project | No — defaulted from `.pmo/project-config.yaml` `project.id`; if the PM states one, it must match (`PMO-CR-001`) |
| Title | **Required** |
| Proposed Change | **Required** |
| Business Rationale | **Required** |
| Affected Module | Optional |
| Affected Scope | Optional |
| Affected Requirements | Optional |
| Technical Impact | Optional |
| Dependencies | Optional |
| Risks | Optional |
| Assumptions | Optional |
| Supporting evidence | Optional |

See Section 9 for the procedure this triggers.

---

## 5. Authoritative project artifact contracts (consumed, not redefined)

This Skill reads and writes only the paths already established by Phase 1A —
it does not invent alternate paths or schemas, and it does **not** introduce
`docs/pmo/change-requests/`. The canonical CR path remains `docs/pmo/cr/`.

| Artifact | Path |
|---|---|
| Change Request Register | `docs/pmo/cr/change-request-register.md` |
| Change Request record | `docs/pmo/cr/CR-NNN.md` |
| CR template | `docs/pmo/cr/_TEMPLATE-CR.md` |
| Change Log | `docs/pmo/change-log/change-log.md` |
| Feedback Tracker (read-only context; never edited here) | `docs/pmo/feedback/feedback-tracker.md` |
| Feedback Batches (read-only context; never edited here) | `docs/pmo/feedback/batches/` |
| Scope (written only by the incorporation transaction, Section 19–20) | `docs/pmo/scope/` |
| Specifications (written only by the incorporation transaction, Section 19–21) | `docs/pmo/specs/specs.md` |
| Intent (read-only reference; never written here) | `docs/pmo/intent/` |
| Project configuration | `.pmo/project-config.yaml` |
| CR transaction marker (contract only this phase — Section 25) | `.pmo/change-request-transaction.json` |

The field contracts, identifier rules, origin model, status model, transition
matrix, approval-evidence rules, incorporation rules, traceability rules, and
supersession rules already defined in `docs/pmo/cr/change-request-
register.md` (§1–§14) and `docs/pmo/change-log/change-log.md` (§1–§8) are the
schema authority. This Skill implements those contracts; where this document
restates them for a specific procedure, the canonical file — not this
restatement — wins if they ever drift.

---

## 6. Required project state — hard gate

Do **not** begin any operation (Mode B creation, a lifecycle transition, or
incorporation-precondition validation) unless **all** hold:

1. `.pmo/project-config.yaml` exists, parses, and its `project.id` is
   readable. If the PM stated a project identifier/name, it must match
   (case-insensitive) — `PMO-CR-001`.
2. `docs/pmo/cr/change-request-register.md` exists (Phase 1A scaffolding).
3. `docs/pmo/cr/_TEMPLATE-CR.md` exists (authoring basis for new records —
   never edited in place, only copied).
4. `docs/pmo/change-log/change-log.md` exists (read for traceability
   verification; never written outside a completed incorporation).

If any prerequisite fails, stop and report which one; do not attempt to
create the missing scaffolding from inside this Skill (Phase-1A territory).

---

## 7. Identifier governance

| Identifier | Format | Scope | Rule |
|---|---|---|---|
| Change Request | `CR-NNN` | project-scoped, register-global | monotonic, never per-year, never reused |
| Logical Global ID | `<Project-ID>::CR-NNN` | cross-project aggregation only | e.g. `SMART-BASKET::CR-011`; never the human-facing ID on a record |

Rules:

- **Inspect the real Change Request Register and `docs/pmo/cr/CR-*.md`
  files before allocating** the next `CR-NNN`. Never infer the next number
  solely from conversation history (`PMO-CR-004` on collision).
- Immutable, never renumbered, never reused once allocated — including after
  `REJECTED` or `CANCELLED`. **Rejected/cancelled CR IDs remain permanently
  consumed.**
- If a previously rejected/cancelled idea returns, **create a new CR** — do
  not resurrect the old one. Example: `CR-004` is `REJECTED`; the idea
  resurfaces later as `CR-011`, with `Related Prior CR: CR-004` and
  `Relationship: RECONSIDERS`. `CR-004`'s own record is never reopened or
  edited.

---

## 8. CLIENT_REQUESTED CR handoff

When `feedback-management` has already created, e.g.:

```
CR-005
Origin: CLIENT_REQUESTED
Status: DRAFT
```

`change-request-management` takes ownership **from that point**. Concretely,
on first touching such a CR:

1. Read the CR record and confirm `Origin: CLIENT_REQUESTED`, `Status:
   DRAFT`, and that `Origin Feedback Batch` / `Origin Feedback Item` are
   populated with syntactically valid ids.
2. Re-verify the bidirectional link: the named Feedback Item, in its parent
   Batch file, must have `Related CR` pointing back to this exact CR ID. A
   mismatch is `PMO-CR-008` (`INVALID_CLIENT_FEEDBACK_PROVENANCE`) — stop,
   do not proceed with this CR until the inconsistency is resolved
   (typically by re-running `feedback-management` reconciliation, not by
   this Skill silently "fixing" the feedback side).
3. From here, this Skill owns every further transition.

This Skill must **not**, under any circumstance:

- reclassify the originating Feedback Item,
- rewrite the original feedback content,
- change the Feedback Batch's identity,

— those remain exclusively `feedback-management`'s territory (Section 2). It
**may** read feedback provenance for context (e.g. to populate `Description`
/ `Business Rationale` more precisely during `PM_REVIEW`), never to alter it.

---

## 9. PM_PROPOSED CR creation procedure (Mode B)

1. **Validate project identity and gate** (Section 6).
2. **Inspect the current CR Register and `docs/pmo/cr/CR-*.md`** before
   allocating (Section 7).
3. **Allocate the next valid `CR-NNN`** and its Logical Global ID
   `<Project-ID>::CR-NNN`.
4. **Create the canonical CR record** by copying `docs/pmo/cr/_TEMPLATE-
   CR.md` to `docs/pmo/cr/CR-NNN.md` (template never edited in place) and
   completing the full field contract (`change-request-register.md` §9):
   - `Origin: PM_PROPOSED`
   - `Origin Feedback Batch: "No Feedback ID — PM_PROPOSED"`
   - `Origin Feedback Item: "No Feedback ID — PM_PROPOSED"`
   - `Status: DRAFT`
   - `Title`, `Proposed Change`, `Business Rationale` from the PM's input;
     `Description`, `Affected Modules/Scope/Requirements`, `Scope Impact`,
     `Technical Impact`, `Assumptions`, `Dependencies`, `Risks` populated
     from whatever the PM supplied — anything not supplied is left explicit
     as unknown, never fabricated (Section 17)
   - a `Status History` opening row: `— | — | DRAFT | <PM name> | PM-
     proposed creation`
5. **Register** the new CR as a row in `change-request-register.md` §8.
6. **Preserve no fake Feedback provenance** — step 4's literal string is the
   only acceptable value for the two Origin Feedback fields on a
   `PM_PROPOSED` CR; inventing a plausible-looking `FB-YYYY-NNN` id here is
   `PMO-CR-009` (`INVALID_PM_PROPOSED_PROVENANCE`).
7. **Do not modify Scope or `specs.md`.**
8. **Do not approve automatically** — the CR is created at `DRAFT` and stays
   there until a PM explicitly moves it forward (Section 26).

---

## 10. Lifecycle states — semantics

| Status | Deterministic meaning |
|---|---|
| `DRAFT` | Captured proposal. No review or approval is implied. Freely editable. |
| `PM_REVIEW` | The PM is validating wording, scope, and impact before it goes external. No client decision has been sought yet. |
| `PENDING_CLIENT_DECISION` | The proposal has been put forward for an external (client) decision. Awaiting that decision. |
| `APPROVED` | Explicit approval evidence exists (Section 12). The CR is **eligible** for incorporation — incorporation has **not** necessarily happened (Section 18). |
| `REJECTED` | Explicit rejection exists. Terminal. Retained forever as historical record (Section 16). |
| `DEFERRED` | Decision or action postponed. Not terminal — may be reactivated (Section 11). Proposal and decision context both retained. |
| `CANCELLED` | Proposal withdrawn before incorporation. Terminal. Retained forever (Section 16). |
| `INCORPORATED` | The approved CR has successfully completed the Scope + specs.md + Change Log transaction (Section 19). Terminal, immutable. |

---

## 11. Transition matrix

The architecture-approved matrix (`change-request-register.md` §7),
restated here as the operational contract this Skill enforces on itself —
**no arbitrary transitions, no invented shortcut**:

| From \ To | PM_REVIEW | PENDING_CLIENT_DECISION | APPROVED | REJECTED | DEFERRED | CANCELLED | INCORPORATED |
|---|---|---|---|---|---|---|---|
| **DRAFT** | ✅ | ❌ | ❌ | ❌ | ❌ | ✅¹ | ❌ **prohibited** |
| **PM_REVIEW** | — | ✅ | ❌ | ❌ | ✅¹ | ✅¹ | ❌ **prohibited** |
| **PENDING_CLIENT_DECISION** | ✅ (bounce back) | — | ✅² | ✅² | ✅² | ❌ | ❌ **prohibited** |
| **APPROVED** | ❌ | ❌ | — | ❌ | ❌ | ✅³ | ✅⁴ |
| **DEFERRED** | ✅ (reactivate) | ❌ | ❌ | ❌ | — | ✅¹ | ❌ |
| **REJECTED** | ❌ | ❌ | ❌ | — (terminal) | ❌ | ❌ | ❌ |
| **CANCELLED** | ❌ | ❌ | ❌ | ❌ | ❌ | — (terminal) | ❌ |
| **INCORPORATED** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ **prohibited** | — (terminal, immutable) |

¹ requires recorded evidence/rationale (Section 13) — a bare status flip with
no reason is invalid (`PMO-CR-006`).
² requires `Decision`, `Decision Date`, `Decision By`, and non-empty
`Approval Evidence`/`Reason` populated in the same transition (Section 12).
³ `APPROVED → CANCELLED` — only **before** incorporation, with the full
cancellation evidence bundle (Section 14).
⁴ `APPROVED → INCORPORATED` — only through the complete incorporation
transaction (Section 19); a failed transaction leaves the CR at `APPROVED`
(Section 24).

**`DEFERRED` reactivation is deliberately routed only to `PM_REVIEW`, never
directly back to `PENDING_CLIENT_DECISION`** — whatever caused the deferral
may have changed the wording/scope/impact, so a re-submission to the client
always passes through a fresh PM check first. This is the one place the
architecture leaves a choice, and this Skill resolves it this way rather
than inventing an ungoverned shortcut back to the client.

Explicitly prohibited, regardless of how it is requested: `DRAFT →
INCORPORATED`, `PM_REVIEW → INCORPORATED`, `PENDING_CLIENT_DECISION →
INCORPORATED`, `INCORPORATED → CANCELLED`, and any transition into
`APPROVED` without the Section 12 evidence bundle. A request for any of these
is `PMO-CR-006` (`INVALID_STATE_TRANSITION`) or, for the two most specific
cases, `PMO-CR-010` (`INCORPORATION_BEFORE_APPROVAL`) and `PMO-CR-020`
(`INCORPORATED_CANCELLATION_ATTEMPT`).

---

## 12. Approval evidence

A CR must **never** become `APPROVED` without explicit approval evidence.
Reachable only from `PENDING_CLIENT_DECISION`, and only with all of:

| Field | Requirement |
|---|---|
| `Decision` | `APPROVED` |
| `Decision Date` | the date the decision was made |
| `Decision By` | who made/recorded it |
| `Approval Evidence` | a concrete, checkable reference |

`Approval Evidence` may reference: an email, a meeting record, a client
message, a signed document, a ticket/comment, or another persisted client-
decision source. It is never fabricated from: silence, development having
started, a PM assumption, a previous verbal implication, the CR's
classification, a commercial discussion, or an internal recommendation. **If
evidence is insufficient, do not transition to `APPROVED`** —
`PMO-CR-007` (`MISSING_APPROVAL_EVIDENCE`).

**PM-Proposed approval.** `PM_PROPOSED` uses the identical requirement.
Creating the CR (Section 9) is a proposal, not an approval — the PM
proposing it does not authorize it. The conceptual path remains `DRAFT →
PM_REVIEW → PENDING_CLIENT_DECISION → APPROVED` before incorporation is even
eligible, exactly as for `CLIENT_REQUESTED`.

---

## 13. Rejection / deferral / cancellation

All three require recorded evidence/rationale — never a bare status flip:

- **`REJECTED`** — `Decision: REJECTED`, `Decision Date`, `Decision By`,
  `Rejection/Deferral Reason`. Retained **forever** as historical record;
  never deleted because it "didn't proceed."
- **`DEFERRED`** — `Decision: DEFERRED`, `Decision Date`, `Decision By`,
  `Rejection/Deferral Reason` (the postponement reason). The proposal and
  its decision context are both retained; reactivation returns to
  `PM_REVIEW` (Section 11).
- **`CANCELLED`** (pre-approval, i.e. from `DRAFT` / `PM_REVIEW` /
  `DEFERRED`) — `Decision: CANCELLED`, `Decision Date`, `Decision By`,
  `Rejection/Deferral Reason` (the withdrawal reason). Retained forever.

Never delete a historical CR record simply because it did not proceed —
doing so is `PMO-CR-019` (`UNAUTHORIZED_HISTORY_DELETION`).

---

## 14. APPROVED → CANCELLED

Allowed **only** when **all** hold:

1. `Status = APPROVED`.
2. The CR is **not** `INCORPORATED`.
3. The cancellation decision is explicit (not inferred).
4. `Decision: CANCELLED`, `Decision Date`, `Decision By`, and a `Rejection/
   Deferral Reason`-equivalent evidence reference are all recorded.

**The prior approval record must remain in history** — this transition never
rewrites `Decision`/`Decision Date`/`Decision By`/`Approval Evidence` from
the earlier `APPROVED` event; it appends a new Status History row on top of
it. History must never be rewritten to make it appear the CR was never
approved.

---

## 15. Incorporated reversal

An `INCORPORATED` CR **cannot** be cancelled or silently removed
(`PMO-CR-020` on any attempt). To reverse or replace it: **create a new
CR** referencing the incorporated one with `Related Prior CR: CR-NNN` and
`Relationship: SUPERSEDES` (or `REVERSES`, treated identically by this
Skill — both mean "this new CR's own eventual incorporation is intended to
undo or replace the referenced one"). The previous `CHG-NNN` record and the
Scope/specs.md history it produced remain intact and unedited — the new
CR's own incorporation (once approved) produces a **new** `CHG-NNN` entry
that sets `Supersedes` pointing at the old one (`change-log.md` §5); the old
entry is never rewritten (`change-request-register.md` §13).

---

## 16. Change Request history — append-only

Every CR preserves an append-only `Status History` (mirroring the schema
already in `docs/pmo/cr/_TEMPLATE-CR.md`):

| Field | Notes |
|---|---|
| Date/time | when the transition happened |
| Previous Status | |
| New Status | |
| Changed By | PM name, or the CR's originating actor for the opening row |
| Reason | required for any transition per Sections 11/13/14 |
| Evidence Reference | required where Section 12/14 requires evidence |

A later transition **never erases** a prior row. Approval followed by
cancellation shows **both** events, in order, with both evidence bundles
intact — an auditor reading the history top to bottom sees exactly what
happened and when, never a rewritten "as if it had always been cancelled"
version.

---

## 17. Scope/requirement analysis — no fabrication

Before approval or incorporation planning, this Skill may **read** Intent,
Scope, `specs.md`, feedback provenance, and existing CRs to populate
`Affected Scope`, `Affected Requirements`, `Affected Modules`, and
`Technical Impact` — but **only where the evidence supports the specific
reference**. Do not fabricate an affected Scope id, a Requirement id, a
Module, or a technical-impact claim that isn't traceable to something
actually read. An unknown stays **explicitly** unknown (e.g. `Affected
Requirements: none identified` / `Technical Impact: not yet assessed`) —
never silently blank, never guessed to look complete.

---

## 18. Incorporation authorization — preconditions

`APPROVED` means the CR is **eligible** for incorporation. It does **not**
itself mean incorporation has happened. Before incorporation may begin,
**all** of the following must validate:

1. The CR exists and is readable.
2. `Status = APPROVED`.
3. Approval evidence is complete (Section 12's four fields, all non-empty).
4. Origin provenance is valid (`CLIENT_REQUESTED` backlink re-verified per
   Section 8, or `PM_PROPOSED`'s canonical literal fields intact).
5. The affected change is sufficiently defined (`Proposed Change`, `Scope
   Impact`, and at least one of `Affected Scope`/`Affected Requirements` are
   non-empty — an approved CR with literally nothing to incorporate cannot
   proceed).
6. The current Scope version is identifiable (exactly one `docs/pmo/
   scope/scope-vX.Y.md` is the latest by version number, matching
   `.pmo/project-config.yaml` `artifacts.scope.latest_version`).
7. The current Spec version is identifiable (`docs/pmo/specs/specs.md`'s
   Document Control `Spec Version` matches `artifacts.specifications.
   latest_version`).
8. No conflicting active incorporation transaction exists (no live
   `.pmo/change-request-transaction.json` for a **different** CR — Section
   25; this phase defines the contract only, so this check is inert until
   the future guard/marker orchestration is built, exactly as
   `feedback-management`'s Scope/Specs protections were inert before its
   own transaction marker existed).
9. Scope/Specs baseline hashes/versions are captured as the transaction's
   starting point (for later mismatch detection — Section 24).
10. Project identity/config is valid (Section 6 item 1).

**If any mandatory condition fails, do not begin incorporation.** Report the
specific failed condition (`PMO-CR-010`/`-011`/`-012` as applicable) and
leave the CR at `APPROVED` — never a partial state.

---

## 19. Incorporation transaction — orchestrated by change-request-incorporator.py

This section defines the **complete transaction contract**. As of Phase 2C
it is implemented, not merely specified: `change-request-governance-guard.py`
enforces it on every Claude Write/Edit, and
`.claude/scripts/change-request-incorporator.py` — the deterministic
orchestrator — executes and reconciles the transaction end to end. Both
share one implementation, `.claude/lib/change_request_incorporation_core.py`,
so "the guard says PASS but the orchestrator says FAIL" for the same
on-disk state cannot happen by construction.

**Ownership boundary, restated precisely because it is the one rule
everything else here serves:** this Skill (the semantic layer) decides
*what* an incorporation contains — the new Scope requirement's wording, the
updated Spec behaviour, which modules/requirements are affected, the Change
Log's change summary. The orchestrator decides *whether the transaction may
proceed and whether it actually succeeded* — it never authors requirement
text, Scope/Spec interpretation, acceptance criteria, affected modules, or
business rules. Concretely: this Skill always performs the actual
Scope/Specs/Change Log edits itself, as ordinary Write/Edit calls governed
exactly as they always have been; the orchestrator only runs before (BEGIN)
and after (VALIDATE / FINALIZE) that work.

**The four-command interface** (`.claude/scripts/change-request-incorporator.py`):

| Command | When | Does |
|---|---|---|
| `begin --cr CR-NNN [--dry-run]` | **Before the first Scope/Specs/Change Log write** | Runs the full BEGIN precondition checklist (Section 18) read-only; on PASS (and not `--dry-run`), writes `.pmo/change-request-transaction.json` with the computed target versions/ids. `--dry-run` reports the same eligibility/targets and never touches disk — this is the preflight/dry-run mode. |
| `status [--cr CR-NNN]` | Any time | Pure read-only inspection of the current transaction, if any — never mutates anything. |
| `validate --cr CR-NNN` | **After this Skill has performed the governed Scope/Specs/Change Log edits** | Re-reads everything from disk and re-runs full reconciliation (Section 24, "Final Reconciliation"). PASS means ready for `finalize`; a genuine inconsistency moves the marker to `RECOVERY_REQUIRED` and reports exactly what is missing/wrong. |
| `finalize --cr CR-NNN` | **Only after `validate` reports PASS** | Re-validates from scratch (never trusts a stale prior `validate`) and, only on a full PASS, performs the CR's `APPROVED → INCORPORATED` write with an appended history row, then removes the marker as the last step. |

This is the concrete realisation of the flow this section already specified:

```
change-request-incorporator.py begin --cr CR-007
    ↓
transaction marker created

Semantic Skill performs governed Scope/Specs/Change Log edits
    ↓
change-request-incorporator.py validate --cr CR-007
    ↓
reconciliation PASS

change-request-incorporator.py finalize --cr CR-007
    ↓
CR → INCORPORATED
marker removed
```

**Publication remains entirely separate** — the orchestrator never runs
`git add` / `git commit` / `git push`, creates or switches a branch, or
selects a remote (Section 28 is unchanged by this implementation).
`artifact-publish` remains the only Skill authorised to publish the
resulting project-artifact changes, run as its own later, explicit step.

Required outcome, as **one logical governed transaction**:

```
APPROVED CR
    │
    ▼
new Scope revision           (Section 20)
    │
    ▼
specs.md in-place update     (Section 21)
    │
    ▼
new Change Log entry         (Section 22)
    │
    ▼
CR marked INCORPORATED       (last write, only after all three above)
```

**A CR must not be marked `INCORPORATED` until all three artifact outcomes
are valid** — a new, correctly-versioned Scope file exists; `specs.md` has
been updated in place with a matching version bump and Change Source tags;
and exactly one new `CHG-NNN` entry exists referencing this CR and both
version changes. Marking `INCORPORATED` is deliberately the **last** write
of the transaction (mirrors `change-request-register.md` §11 step 5) so that
a CR's `Status` always accurately reflects whether the transaction actually
finished — see Section 24 for what happens when it does not.

---

## 20. Scope behavior

- Scope remains **multi-version and append-only**. Approved CR incorporation
  creates the **next** governed Scope revision as a **new file**
  (`docs/pmo/scope/scope-vX.(Y+1).md` pre-baseline, or `scope-v(X+1).0.md` /
  `scope-vX.(Y+1).md` post-baseline per `requirement-gathering`'s existing
  versioning rules) — **never** overwrites a historical Scope version.
- The new Scope version's Document Control records `Previous Scope Version`
  and, on the specific `SCP-REQ-*` item(s) the CR touches, a `Change Source:
  CR-NNN` tag.
- Requirement/`OPEN` identifier governance is preserved exactly as
  `requirement-gathering` already defines it (stable ids, no reuse, `OPEN-*`
  provenance rules) — this transaction does not get a separate, looser rule
  set merely because it originates from a CR rather than ordinary drafting.
- **Do not silently renumber unrelated requirements.** Only the `SCP-REQ-*`
  item(s) the CR actually adds/changes/retires are touched; everything else
  in the new version is carried forward unchanged from the previous version.

---

## 21. Specs behavior

Canonical execution Specs remains exactly **`docs/pmo/specs/specs.md`** —
this transaction does **not** create `specs-v0.2.md`, `specs-v1.0.md`, or any
other version-forked filename. Approved CR incorporation updates `specs.md`
**in place**, under the existing Spec governance (`spec-generation`'s own
rules), and must:

- bump the internal `Spec Version` (Document Control) appropriately;
- preserve stable `FR-XXX` / `NFR-XXX` / `BR-XXX` identifiers — never
  renumber an unaffected requirement;
- add/update **only** the requirements legitimately affected by this CR —
  everything else is carried forward unchanged;
- append a row to the Specification Change History table;
- tag every added/changed requirement `Change Source: CR-NNN (CHG-NNN)`;
- remain fully consumable by Development and QA immediately after the
  update (no half-written requirement, no dangling reference).

`BUG`s and `ENHANCEMENT`s classified by `feedback-management` do **not**
reach this Skill as requirement-mutation authority on their own — they carry
no CR and therefore have no incorporation path at all, unless a human
separately, explicitly converts the underlying need into a new CR that goes
through this full governance from `DRAFT` onward (Section 3's origin model
has no "convert a Bug into a Spec change" back door).

---

## 22. Change Log behavior

A successful incorporation creates **exactly one** new `CHG-NNN` record,
appended to `docs/pmo/change-log/change-log.md` per its established schema
(§5), referencing: CR ID, CR Origin, Feedback Reference (when `CLIENT_
REQUESTED`), Previous/New Scope Version, Previous/New Spec Version, Affected
Scope Items, Affected Requirements, Description Before/After, Change
Summary, Approval Reference, and Incorporated By/Date.

**No `CHG` record is ever created for** a CR at `DRAFT`, `PM_REVIEW`,
`PENDING_CLIENT_DECISION`, `REJECTED`, `DEFERRED`, or `CANCELLED`. Only a
**successful** incorporation creates the Change Log record — never a
speculative or partial one (Section 24).

---

## 23. Traceability

- **`CLIENT_REQUESTED`**: `Feedback Batch → Feedback Item → CR → CHG →
  Scope → specs.md`.
- **`PM_PROPOSED`**: `CR → CHG → Scope → specs.md`.
- **Reverse** (must also be possible, in both cases): a `specs.md`
  requirement's `Change Source: CR-NNN (CHG-NNN)` tag → the `CHG-NNN` entry
  → the CR record → (if `CLIENT_REQUESTED`) the originating Feedback Item →
  its Feedback Batch.
- **Every incorporated Spec/Scope mutation must identify its CR source** —
  an added/changed `SCP-REQ-*`/`FR`/`NFR`/`BR` with no `Change Source` tag
  after this transaction is a traceability failure (`PMO-CR-017`).

---

## 24. Transaction failure model

Fail-closed, file/Git-based (no database — none is introduced here), mirroring
the same discipline already established for `feedback-management`'s
transaction (its Phase 1D orchestration is the direct precedent for this
section). **The system must never falsely report `INCORPORATED`.**

| Failure | Required behaviour |
|---|---|
| Scope revision succeeds, `specs.md` update fails | CR stays `APPROVED`. The orphaned new Scope file is left in place (it is otherwise valid, immutable, append-only history) but is **not** yet referenced by any `CHG` entry — surfaced as an inconsistency (`PMO-CR-018`, `PARTIAL_TRANSACTION`) for manual PM/governance remediation, never auto-reverted (Scope files are never deleted once written) and never auto-completed. |
| Specs succeeds, Change Log write fails | CR stays `APPROVED`. Both the new Scope file and the updated `specs.md` exist without a matching `CHG-NNN` — same `PMO-CR-018` surfacing; the missing Change Log entry is the specific gap to close, not a reason to revert the Scope/specs writes already made. |
| Scope + Specs succeed but the CR `Status → INCORPORATED` write fails | The Scope file, `specs.md` update, and `CHG-NNN` entry all exist and are mutually consistent, but the CR itself still reads `APPROVED`. This is the narrowest, most recoverable partial state: the **only** remaining step is retrying the final CR-status write — `PMO-CR-018` with the specific sub-detail "artifacts complete, CR status pending." |
| Change Log entry created with mismatched versions | `PMO-CR-016` (`VERSION_MISMATCH`) — the entry's `New Spec Version`/`New Scope Version` must equal the actual files' current versions; a mismatch blocks marking `INCORPORATED` and is surfaced, never silently corrected by rewriting the `CHG` entry (Change Log is append-only — Section 22, `change-log.md` §7). |
| CR status altered before transaction completion (e.g. something sets `INCORPORATED` early) | `PMO-CR-010`/`PMO-CR-018` — refuse; a `Status` write to `INCORPORATED` is valid only as literally the last step of a transaction that has already confirmed Scope + Specs + Change Log are all present and consistent. |
| Partial artifact writes generally | Never silently discarded, never silently completed. Reported precisely: which of {Scope, Specs, Change Log, CR status} exist and which are missing, so recovery is a targeted retry of the missing step(s), not a guess. |
| Identifier collision (e.g. the intended `CHG-NNN` already exists from an unrelated cause) | `PMO-CR-004` (`CR_ID_COLLISION`, reused generically for any identifier collision in this Skill's namespace) — halt before writing; re-derive the next free id from the real register/log, never overwrite. |
| Unexpected exception at any step | `PMO-CR-023` (`CR_INTERNAL_ERROR`) — fail closed, stop, report the precise partial state (per the table above), never claim success. |

**Recommended recovery strategy** (simplest deterministic option compatible
with the existing PMO architecture, no database introduced): the CR's own
`Status` field **is** the recovery state machine. `APPROVED` with no
matching `CHG-NNN` means "not done"; `APPROVED` with a fully consistent
Scope+Specs+`CHG-NNN` triple but no `INCORPORATED` status means "one write
away from done." A future `change-request-governance-guard.py` can detect
both shapes deterministically by cross-reading the CR, the Change Log, Scope,
and `specs.md` — exactly the same detect-don't-auto-repair pattern
`feedback-governance-guard.py` already uses for Tracker/Batch desync
(`PMO-FEEDBACK-GUARD-008`). No new persistence mechanism is needed.

---

## 25. CR transaction marker — implemented (Phase 2C)

Parallel to `feedback-management`'s `.pmo/feedback-transaction.json`
(Phase 1D). As of Phase 2C this marker, its schema, and its enforcement are
fully implemented — not a future contract.

**Path:** `.pmo/change-request-transaction.json`

**Schema** (`operation: "INCORPORATION"` — see
`change_request_incorporation_core.py` for the full field set, including
the smaller schema used by this CR's other lifecycle operations, Section 11):

```json
{
  "transaction_type": "CHANGE_REQUEST_MANAGEMENT",
  "transaction_id": "<opaque, unique per run>",
  "project_id": "<must equal .pmo/project-config.yaml project.id>",
  "cr_id": "CR-NNN",
  "operation": "INCORPORATION",
  "started_at": "<ISO 8601 UTC, set once, never rewritten>",
  "status": "ACTIVE",
  "baseline_scope_version": "<e.g. 0.1>",
  "baseline_scope_path": "docs/pmo/scope/scope-v0.1.md",
  "baseline_scope_hash": "<sha256 of the current latest scope-vX.Y.md at start>",
  "baseline_specs_version": "<e.g. 0.1>",
  "baseline_specs_path": "docs/pmo/specs/specs.md",
  "baseline_specs_hash": "<sha256 of specs.md at start>",
  "target_scope_version": "<deterministically computed - baseline minor + 1>",
  "target_specs_version": "<deterministically computed>",
  "target_change_log_id": "<next free CHG-NNN>",
  "cr_path": "docs/pmo/cr/CR-NNN.md",
  "change_log_path": "docs/pmo/change-log/change-log.md",
  "project_config_hash": "<sha256 of project-config.yaml at start>",
  "approval_evidence_reference": "<the CR's own Approval Evidence value>",
  "intent_hash": "<combined sha256 over docs/pmo/intent/ at start>",
  "feedback_hash": "<combined sha256 over docs/pmo/feedback/ at start, CLIENT_REQUESTED only, else null>"
}
```

`status` stays the same three-state model as the feedback marker: `ACTIVE`
/ `RECONCILING` / `RECOVERY_REQUIRED` — no additional states.

Ownership mirrors Section 26/32 of `feedback-management/SKILL.md`:
`change-request-incorporator.py`'s `begin` command creates it (only after
the full BEGIN precondition checklist passes, Section 18), `validate`/
`finalize` transition its `status` (same-transaction, rule-respecting
updates only — never a different `transaction_id`/`started_at`/`cr_id`/
`operation`), and `finalize` removes it as the last step of a successful
transaction. `change-request-governance-guard.py` reads and validates every
write to it (and to the Scope/Specs/Change Log paths it gates) — both the
guard and the CLI call the identical functions in
`.claude/lib/change_request_incorporation_core.py`, so they cannot
disagree on the same on-disk state. `intent_hash`/`feedback_hash` give
`reconcile_transaction` a deterministic way to detect the one class of
drift no Write/Edit-based guard can see on its own: something outside the
Write/Edit tool chain altering Intent or feedback source evidence during
the transaction.

---

## 26. Manual PM operations

PM-friendly intents this Skill recognises, each of which **inspects current
state before acting** — natural language never bypasses lifecycle
governance (Section 11):

| PM says | This Skill does |
|---|---|
| "Create a PM-proposed CR for…" | Mode B (Section 9). |
| "Move CR-007 to PM review." | Validate `CR-007` is currently `DRAFT`; if so, `DRAFT → PM_REVIEW` with a Status History row. If not `DRAFT`, report the actual status and refuse (`PMO-CR-006`). |
| "CR-007 was sent to the client." | Validate `CR-007` is currently `PM_REVIEW`; if so, `PM_REVIEW → PENDING_CLIENT_DECISION`. Otherwise refuse and report actual status. |
| "Mark CR-007 approved based on this client email." | Validate `CR-007` is `PENDING_CLIENT_DECISION`; require the PM to supply (or this Skill to extract from the cited evidence) `Decision Date`/`Decision By`/`Approval Evidence`; if the evidence is genuinely insufficient, refuse (`PMO-CR-007`) rather than approve on a thin citation. |
| "Reject CR-007." | Validate `CR-007` is `PENDING_CLIENT_DECISION`; require a reason; `→ REJECTED`. |
| "Defer CR-007." | Validate current status allows deferral (Section 11); require a reason; `→ DEFERRED`. |
| "Cancel CR-007 before incorporation." | Validate `CR-007` is not `INCORPORATED`; require cancellation evidence (Section 14 if `APPROVED`, Section 13 otherwise); `→ CANCELLED`. |
| "Incorporate approved CR-007." | Validate `CR-007` is `APPROVED`; run the full Section 18 precondition check; only then proceed to the Section 19 contract (which, this phase, has no execution code — report `PMO-CR-010`-adjacent "incorporation transaction not yet implemented" rather than performing any Scope/specs/Change Log write). |

Every row above reads the CR's actual current state first; an instruction
that assumes a state the CR is not actually in is refused with the real
state reported, never silently reinterpreted to "make the instruction work."

---

## 27. No payment tracking

Do not add price, invoice, payment, collection, or commercial-approval-
status fields to the required Phase-1 CR lifecycle or its schema (Section
5's field contract is the authority — nothing beyond it). A future
commercial subsystem may extend CR metadata; this Skill does not anticipate
or half-implement that extension now.

---

## 28. Publication boundary

This Skill may **prepare** project-artifact changes (CR records, the
Register, and — once Section 19 is actually implemented in a later phase —
Scope/specs.md/Change Log). It never independently runs `git commit`, `git
push`, creates or switches branches, or selects a remote. Publishing remains
owned exclusively by `artifact-publish`, run separately and explicitly by
the PM (`PMO-CR-022` on any attempt from inside this Skill).

---

## 29. Project-config.yaml protection

This Skill may **read** `.pmo/project-config.yaml` freely. It must **not**
alter: repository identity (`provider`/`workspace`/`repository`/`remote`),
`working_branch`, `verified` state, artifact routing paths, Intent/Scope/
Specs approval state, `workflow.current_stage`, or any unrelated counter.

The **only** field this Skill is ever authorised to update — and only once
the Section 19 transaction actually exists and completes in a later phase —
is `artifacts.change_requests.latest_id` (mirroring how `feedback-
management` owns that same field as a byproduct of CLIENT_REQUESTED CR
creation) and, symmetrically, `artifacts.change_log.latest_id` /
`artifacts.change_log.total_count` once a `CHG-NNN` is actually written.
Every write is minimal and additive — never a rewrite of the surrounding
block. Any change outside this exact whitelist is `PMO-CR-021`
(`PROJECT_CONFIG_OVERREACH`). This phase performs **no** config mutation at
all (no real CR is created or incorporated by this task).

---

## 30. Cross-guard integration — resolved (Phase 2B)

Previously documented here as a known blocking dependency: until
`change-request-governance-guard.py` existed, `feedback-governance-
guard.py` governed **every** write to `docs/pmo/cr/` unconditionally,
permitting only the feedback-authorised subset (`Origin: CLIENT_REQUESTED`,
`Status` in `{DRAFT, CANCELLED}`) — meaning this Skill could not yet
operate end-to-end on a real CR.

**This is now resolved.** `change-request-governance-guard.py` (Phase 2B)
exists and is registered; domain routing between the two guards is
content-based — a CR write whose resulting content is exactly the
feedback-safe shape defers to `feedback-governance-guard.py` (unchanged,
narrow authority), and every other shape (`PM_PROPOSED` origin, or any
status beyond `DRAFT`/`CANCELLED`) is this Skill's guard's territory,
requiring an open `.pmo/change-request-transaction.json`. The two
transactions (`.pmo/feedback-transaction.json` and
`.pmo/change-request-transaction.json`) are mutually exclusive — both
guards independently detect and deny the both-active case
(`PMO-FEEDBACK-GUARD-026` / `PMO-CR-GUARD-025`). This Skill is fully
operable end-to-end on real CRs, including incorporation (Section 19,
Phase 2C).

---

## 31. Prohibited operations — summary

This Skill must never, in this phase or any future one:

- transition any CR to `APPROVED` without the full Section 12 evidence
  bundle
- transition `DRAFT`/`PM_REVIEW`/`PENDING_CLIENT_DECISION` directly to
  `INCORPORATED`
- transition `INCORPORATED` to anything else, including `CANCELLED`
- reuse or renumber a `CR-NNN` or `CHG-NNN` identifier
- fabricate `Origin Feedback Batch`/`Origin Feedback Item` for a
  `PM_PROPOSED` CR
- reclassify a Feedback Item, rewrite original feedback, or change a
  Feedback Batch's identity
- delete or silently rewrite a CR's history (`Status History`, prior
  `Decision`/`Approval Evidence`)
- create a `CHG-NNN` entry for anything other than a fully successful
  incorporation
- mark a CR `INCORPORATED` on a partial transaction
- write `docs/pmo/scope/`, `docs/pmo/specs/specs.md`, or `docs/pmo/change-
  log/change-log.md` outside the Section 19 transaction (this Skill's own
  Write/Edit calls remain governed by `change-request-governance-guard.py`
  exactly as always; only `change-request-incorporator.py`'s `finalize`
  ever writes the CR's own `INCORPORATED` state directly, and only after
  full reconciliation passes)
- mutate `.pmo/project-config.yaml` outside the Section 29 whitelist
- `git commit`, `git push`, branch, or publish

---

## 32. PMO-CR-* error / result codes

Dedicated namespace — never reuses `PMO-FEEDBACK-*`, `PMO-FEEDBACK-GUARD-*`,
`PMO-SCOPE-*`, `PMO-SPEC-*`, or `PMO-PUBLISH-*`.

| Code | Name | Condition |
|---|---|---|
| `PMO-CR-001` | `PROJECT_IDENTITY_INVALID` | `.pmo/project-config.yaml` missing/unreadable, or a stated project identifier doesn't match `project.id`. |
| `PMO-CR-002` | `CR_NOT_FOUND` | An operation names a `CR-NNN` that does not exist in the register/`docs/pmo/cr/`. |
| `PMO-CR-003` | `INVALID_CR_ID` | A referenced or newly-allocated id does not match the `CR-NNN` syntax. |
| `PMO-CR-004` | `CR_ID_COLLISION` | An allocation target (`CR-NNN` or `CHG-NNN`) already exists. |
| `PMO-CR-005` | `INVALID_ORIGIN` | `Origin` is not exactly one of `CLIENT_REQUESTED` / `PM_PROPOSED`. |
| `PMO-CR-006` | `INVALID_STATE_TRANSITION` | A requested transition is not present in the Section 11 matrix. |
| `PMO-CR-007` | `MISSING_APPROVAL_EVIDENCE` | `APPROVED` (or `APPROVED → CANCELLED`) attempted without the full evidence bundle. |
| `PMO-CR-008` | `INVALID_CLIENT_FEEDBACK_PROVENANCE` | A `CLIENT_REQUESTED` CR's Feedback Batch/Item backlink is missing, invalid, or mismatched. |
| `PMO-CR-009` | `INVALID_PM_PROPOSED_PROVENANCE` | A `PM_PROPOSED` CR's Origin Feedback fields are anything other than the canonical literal. |
| `PMO-CR-010` | `INCORPORATION_BEFORE_APPROVAL` | Incorporation attempted while `Status != APPROVED`. |
| `PMO-CR-011` | `INVALID_SCOPE_BASELINE` | The current Scope version cannot be uniquely identified before incorporation. |
| `PMO-CR-012` | `INVALID_SPECS_BASELINE` | The current Specs version cannot be uniquely identified before incorporation. |
| `PMO-CR-013` | `SCOPE_UPDATE_FAILURE` | The new Scope revision could not be written/validated during incorporation. |
| `PMO-CR-014` | `SPECS_UPDATE_FAILURE` | The in-place `specs.md` update could not be written/validated during incorporation. |
| `PMO-CR-015` | `CHANGE_LOG_FAILURE` | The `CHG-NNN` entry could not be written during incorporation. |
| `PMO-CR-016` | `VERSION_MISMATCH` | A Change Log entry's version fields don't match the actual Scope/Specs files. |
| `PMO-CR-017` | `TRACEABILITY_FAILURE` | An incorporated Scope/Specs mutation has no resolvable `Change Source: CR-NNN` back-reference. |
| `PMO-CR-018` | `PARTIAL_TRANSACTION` | Any subset of {Scope, Specs, Change Log, CR status} exists inconsistently with the others after an incorporation attempt. |
| `PMO-CR-019` | `UNAUTHORIZED_HISTORY_DELETION` | An attempt to delete or silently rewrite a CR's history/prior decision. |
| `PMO-CR-020` | `INCORPORATED_CANCELLATION_ATTEMPT` | Any attempt to move an `INCORPORATED` CR to `CANCELLED` or any other status. |
| `PMO-CR-021` | `PROJECT_CONFIG_OVERREACH` | An attempted `.pmo/project-config.yaml` write outside the Section 29 whitelist. |
| `PMO-CR-022` | `PUBLICATION_BOUNDARY_VIOLATION` | Any attempt to `git add`/`commit`/`push`, branch, or publish from this Skill. |
| `PMO-CR-023` | `CR_INTERNAL_ERROR` | Unexpected exception during a controlled CR operation — fail closed. |

---

## 33. PM-facing result contracts

Every operation returns one of these result shapes. All share this minimum
field set:

```
Project:
CR ID:
Origin:
Previous Status:
Current Status:
Decision:
Evidence:
Affected Scope/Requirements:
Scope Changed:
Specs Changed:
Change Log Changed:
Next Human/System Gate:
Publish Eligibility:
```

| Result | Header | `Current Status` | Typical `Next Human/System Gate` |
|---|---|---|---|
| CR created (Mode B) | `PMO CR CREATED` | `DRAFT` | `PM_REVIEW` |
| Any lifecycle transition not covered below | `PMO CR STATE UPDATED` | new status | depends on new status |
| Approval recorded | `PMO CR APPROVED` | `APPROVED` | `INCORPORATION_ELIGIBLE` (not automatic — Section 18) |
| Rejection recorded | `PMO CR REJECTED` | `REJECTED` | none — terminal |
| Deferral recorded | `PMO CR DEFERRED` | `DEFERRED` | `PM_REVIEW` (on reactivation) |
| Cancellation recorded | `PMO CR CANCELLED` | `CANCELLED` | none — terminal |
| `change-request-incorporator.py begin` preconditions all pass | `PMO CR READY FOR INCORPORATION` | `APPROVED` | `change-request-incorporator.py validate` / `finalize` (Section 19) |
| Incorporation transaction completes (`finalize` PASS) | `PMO CR INCORPORATED` | `INCORPORATED` | none — terminal; Development/QA consume the updated `specs.md` |
| Any refusal (`PMO-CR-*` / `PMO-CR-GUARD-*` / `PMO-CR-INTEGRATE-*` fired) | `PMO CR OPERATION BLOCKED` | unchanged | fix the cited condition, then retry |

`Scope Changed` / `Specs Changed` / `Change Log Changed` are `NO` for every
result this Skill itself produces directly (its own lifecycle-transition
writes never touch those files); a `PMO CR INCORPORATED` result reports
`YES` for all three, since that is precisely what a successful incorporation
transaction did. `Publish Eligibility` is `NO` whenever
any `PMO-CR-*` condition fired during the operation, `YES` otherwise (a
successful state update is publishable by `artifact-publish` as a project
artifact change; that is a separate, later action this Skill never performs
itself).

---

## 34. Definition of Done

This Skill's authoring is complete only because it explicitly defines, and
this section is the audit trail confirming each:

1. **Both CR origins** — Section 3.
2. **`PM_PROPOSED` creation** — Section 4, Section 9.
3. **`CLIENT_REQUESTED` handoff** — Section 8.
4. **Identifier allocation** — Section 7.
5. **Global logical identity** — Section 7 (`<Project-ID>::CR-NNN`).
6. **Complete CR lifecycle** — Section 10.
7. **Deterministic transition matrix** — Section 11.
8. **Approval evidence** — Section 12.
9. **Rejection handling** — Section 13.
10. **Deferral handling** — Section 13.
11. **Cancellation handling** — Section 13.
12. **`APPROVED → CANCELLED` restriction** — Section 14.
13. **Incorporated reversal via new CR** — Section 15.
14. **Append-only CR history** — Section 16.
15. **Affected Scope/Requirement analysis (no fabrication)** — Section 17.
16. **Approval != incorporation** — stated in Section 1's core principle,
    operationalised in Section 10 (`APPROVED` semantics) and Section 18.
17. **Scope versioning behaviour** — Section 20.
18. **Canonical `specs.md` update behaviour** — Section 21.
19. **Change Log behaviour** — Section 22.
20. **Complete traceability** — Section 23.
21. **Transaction failure model** — Section 24.
22. **Transaction marker contract** — Section 25.
23. **Project-config protection** — Section 29.
24. **Publication separation** — Section 28.
25. **Dedicated error codes** — Section 32.
26. **PM-facing result contracts** — Section 33.

If any item above were missing, this Skill would not be ready; all 26 are
present.
