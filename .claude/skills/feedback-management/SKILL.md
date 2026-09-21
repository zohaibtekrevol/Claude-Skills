---
name: feedback-management
description: >-
  Take a complete client feedback package from the PM and turn it into a
  governed Feedback Batch under docs/pmo/feedback/batches/, classified
  Feedback Items in the canonical docs/pmo/feedback/feedback-tracker.md, and —
  only for items classified CHANGE_REQUEST — a linked DRAFT CLIENT_REQUESTED
  Change Request record under docs/pmo/cr/, registered in
  docs/pmo/cr/change-request-register.md. Classification vocabulary is exactly
  BUG / ENHANCEMENT / CHANGE_REQUEST / SUGGESTION / CLARIFICATION / DUPLICATE /
  NOT_ACTIONABLE, driven by requirement/scope impact and never by effort.
  Preserves the client's original wording verbatim, separate from any
  Normalized Interpretation. Allocates FB-YYYY-NNN / FB-YYYY-NNN-NNN /
  CR-NNN identifiers by inspecting the existing canonical registers — never by
  inference from conversation history — and never renumbers or reuses one.
  Classification is never approval: this Skill creates CRs only in DRAFT, never
  transitions one past DRAFT, never writes docs/pmo/change-log/change-log.md,
  and never modifies docs/pmo/scope/, docs/pmo/specs/specs.md or
  docs/pmo/intent/. As of Phase 1D this is enforced, not merely self-checked:
  every real write requires an open governed transaction, declared by
  creating .pmo/feedback-transaction.json (schema in Section 26) before the
  first write and removed only after full reconciliation passes (Sections
  27–32); feedback-governance-guard.py denies any Tracker/Batch/Register/CR
  write with no open marker, any write to Scope/specs.md/Intent/source
  evidence/change-log while a marker exists, and any attempt to overwrite or
  impersonate an existing marker. Does not commit, push, or publish. Supports
  PM correction of a prior classification with full provenance retained.
  Emits a final PMO FEEDBACK MANAGEMENT RESULT report. PMO-FEEDBACK-001 …
  PMO-FEEDBACK-015 define deterministic halt behaviour. CR approval,
  PM-proposed CR creation, and CR incorporation into Scope/specs.md belong to
  the separate change-request-management Skill, not this one.
---

# Feedback Management (PMO)

## 1. Purpose and position in the PMO lifecycle

Artifact roles across the PMO lifecycle (see `requirement-gathering`,
`spec-generation`):

- **Intent** preserves **WHY** the project exists.
- **Scope** establishes **WHAT** is being delivered (commercial/product
  boundary).
- **Specifications** (`specs.md`) establish the **precise behaviour** Dev
  builds and QA verifies.
- **Feedback Management** (this Skill) captures and classifies feedback
  raised against any of the above, or against a delivered artifact/build, once
  the project is in flight.
- **Change Request Management** (a separate Skill, not yet built) owns CR
  approval and the governed incorporation of an `APPROVED` CR back into Scope,
  `specs.md`, and the Change Log.

This Skill sits **between** "client feedback arrives" and "a scope change is
authorised." It never authorises anything. Its job is narrower and
deterministic:

1. identify the project context from `.pmo/project-config.yaml`;
2. preserve the feedback event substantially as received;
3. create exactly one Feedback Batch per intake event;
4. extract every distinct, independently actionable feedback item;
5. classify each item against the fixed vocabulary (Section 7);
6. write/update the canonical Feedback Tracker and the batch record so they
   agree;
7. for every item finally classified `CHANGE_REQUEST`, create/link exactly one
   `DRAFT` `CLIENT_REQUESTED` Change Request;
8. leave every other classification inside Feedback Management only — no CR;
9. never move a CR past `DRAFT`;
10. never touch Scope, `specs.md`, Intent, or the Change Log.

`.pmo/project-config.yaml` governance applies throughout: `source_of_truth:
repository`, `markdown_authoritative: true`, `approved_artifacts_immutable:
true`, `silent_assumptions_prohibited: true`. This Skill additionally answers
to the Phase-1A project artifact contracts it consumes (Section 5) and does
not redefine.

---

## 2. Authority — what this Skill owns and does not own

**Owns:**

- feedback intake and Feedback Batch identity allocation (Section 9)
- preserving original feedback verbatim (Section 10)
- feedback item extraction and identity allocation (Section 10, Section 11)
- classification, classification rationale, and classification confidence
  (Section 7)
- affected-artifact/module references and requirement/scope traceability,
  only where evidence supports them (Section 8)
- Feedback Tracker updates, kept in sync with each batch record (Section 13)
- batch record creation under `docs/pmo/feedback/batches/`
- `CLIENT_REQUESTED` `DRAFT` CR creation when an item is finally classified
  `CHANGE_REQUEST` (Section 12)
- bidirectional Feedback Item ↔ CR linking (Section 12)
- reporting unresolved classifications, low-confidence items, and open
  questions to the PM (Section 19)
- receiving and applying PM classification corrections (Section 14)
- creating, transitioning, and normally removing the transaction marker
  `.pmo/feedback-transaction.json` around every processing run (Sections
  26–32) — this Skill's own writes are no longer authorised without one

**Does not own — never performs:**

- CR approval or any transition of a CR past `DRAFT` (owned by
  `change-request-management`)
- `PM_PROPOSED` CR creation (owned by `change-request-management`, Mode B)
- CR incorporation into Scope/`specs.md` (owned by `change-request-management`)
- writing `docs/pmo/change-log/change-log.md` (owned by
  `change-request-management`'s incorporation transaction only)
- Development execution or QA execution
- payment / commercial / invoice tracking
- `git commit`, `git push`, branch creation/switching, or any project-artifact
  publishing (owned by `artifact-publish`)

---

## 3. PM entry mode — Mode A: Process Client Feedback

This Skill implements exactly one PM entry point. The PM may provide:

| Field | Required to start? |
|---|---|
| Project identifier/name | No — defaulted from `.pmo/project-config.yaml` `project.id` if the PM doesn't state it; if the PM states one, it must match (Section 6, `PMO-FEEDBACK-001`) |
| Feedback received date | Recommended; see Section 9 for what happens if unknown |
| Source / client / person | Recommended |
| Channel | Optional |
| Artifact / deliverable | Recommended |
| Artifact version | Optional |
| Complete feedback material | **Required** — without it there is nothing to process |
| Supporting attachments / evidence | Optional |

Do not require every optional field before processing — proceed with what the
PM supplies, record what is unknown as unknown (never fabricated), and
surface materially missing context (e.g. no artifact named at all) as a
`CLARIFICATION`-flavoured note in the final report rather than blocking
intake outright, unless Section 9's received-date rule specifically blocks
Batch ID allocation.

---

## 4. Input discovery

Feedback may arrive as plain text, meeting notes, email content, document
content, exported comments, testing/UAT notes, a consolidated feedback list,
transcript excerpts, or PM-uploaded client material — as one or several files
making up a single feedback event.

Rules:

- Treat as feedback only material the PM identifies as, or that self-evidently
  is, the feedback being processed for this batch.
- Do **not** classify contextual/reference material (e.g. a background
  contract excerpt the PM attaches only for context) as feedback items unless
  it explicitly contains or is identified as feedback content.
- When it is unclear whether a supplied document is feedback or background
  reference, ask the PM rather than guessing (`CLARIFICATION` at the batch
  level, not silently included or silently dropped).

---

## 5. Authoritative project artifact contracts (consumed, not redefined)

This Skill reads and writes only the paths already established by Phase 1A.
It does not invent alternate paths or schemas.

| Artifact | Path |
|---|---|
| Feedback Tracker | `docs/pmo/feedback/feedback-tracker.md` |
| Feedback Batch record | `docs/pmo/feedback/batches/FB-YYYY-NNN.md` |
| Feedback Batch template | `docs/pmo/feedback/batches/_TEMPLATE-FB.md` |
| Change Request Register | `docs/pmo/cr/change-request-register.md` |
| Change Request record | `docs/pmo/cr/CR-NNN.md` |
| CR template | `docs/pmo/cr/_TEMPLATE-CR.md` |
| Change Log (read-only reference, never written here) | `docs/pmo/change-log/change-log.md` |
| Specifications (read-only reference, never written here) | `docs/pmo/specs/specs.md` |
| Scope (read-only reference, never written here) | `docs/pmo/scope/` |
| Intent (read-only reference, never written here) | `docs/pmo/intent/` |
| Project configuration | `.pmo/project-config.yaml` |
| Transaction marker (owned by this Skill — Sections 26–32) | `.pmo/feedback-transaction.json` |

The field contracts, identifier rules, classification vocabulary, status
vocabulary, and transition matrix defined in the Feedback Tracker and the CR
Register are the schema authority. This Skill implements those contracts; if
a future edit to those files changes a schema, this Skill follows the file,
not a cached assumption.

---

## 6. Required project state — hard gate

Do **not** begin processing unless **all** of the following hold:

1. `.pmo/project-config.yaml` exists, parses, and its `project.id` is
   readable. If the PM stated a project identifier/name, it must match
   (case-insensitive) — `PMO-FEEDBACK-001`.
2. `docs/pmo/feedback/feedback-tracker.md` exists (Phase 1A scaffolding).
3. `docs/pmo/cr/change-request-register.md` exists (Phase 1A scaffolding).
4. `docs/pmo/feedback/batches/_TEMPLATE-FB.md` and `docs/pmo/cr/_TEMPLATE-CR.md`
   exist (used as the authoring basis for new records — never edited in
   place, only copied).
5. A governed transaction has been started per Section 27 — as of Phase 1D
   this Skill no longer relies on an implied transaction context.
   `feedback-governance-guard.py` denies every Tracker/Batch/Register/CR
   write outright (`PMO-FEEDBACK-GUARD-025`) unless
   `.pmo/feedback-transaction.json` exists, is well-formed, matches the
   current project, and has `status` `ACTIVE` or `RECONCILING`. Section 6
   items 1–4 must hold *before* starting that transaction (Section 27
   step 1 re-validates project identity as part of starting it).

If any prerequisite fails, stop and report which one; do not attempt to
create the missing scaffolding from inside this Skill (that is Phase-1A
territory, not a feedback-processing responsibility). Do not attempt any
Tracker/Batch/Register/CR write before item 5 is satisfied — see Section 27.

---

## 7. Classification rules

### 7.1 Vocabulary — exactly these seven values, no others

| Value | Definition |
|---|---|
| `BUG` | An existing **accepted** requirement/capability does not behave as required. |
| `ENHANCEMENT` | Improves quality, usability, presentation, or implementation of an existing accepted capability **without** materially expanding the approved product/scope boundary. |
| `CHANGE_REQUEST` | Adds, removes, or materially changes an approved product capability, workflow, user role, permission model, integration, platform, business rule, data requirement, acceptance condition, or delivery/project responsibility. |
| `SUGGESTION` | A future/optional idea not yet expressed as an actionable approved change; insufficient evidence of firm requirement impact. |
| `CLARIFICATION` | Not enough information exists yet to safely distinguish Bug / Enhancement / Change Request. |
| `DUPLICATE` | Substantively — not merely lexically — equivalent to an already-recorded Feedback Item. |
| `NOT_ACTIONABLE` | No actionable product/project request or issue (praise, acknowledgment, off-topic remark). Use conservatively. |

No production item may carry a classification outside this set. Introducing an
eighth value requires an explicit architecture amendment, not an ad-hoc
extension by this Skill.

### 7.2 Deterministic evaluation order (first match wins)

1. Not enough information to classify safely → `CLARIFICATION`.
2. Not about the product/project/deliverable at all → `NOT_ACTIONABLE`.
3. Substantively duplicates an already-recorded item (Section 15) →
   `DUPLICATE`, with `Duplicate Of` set.
4. Describes accepted behaviour not matching implementation (BUG rule,
   Section 7.3) → `BUG`.
5. Stays within an accepted capability's boundary (ENHANCEMENT rule, Section
   7.4) → `ENHANCEMENT`.
6. Adds/removes/materially changes an approved boundary (CHANGE_REQUEST rule,
   Section 7.5) → `CHANGE_REQUEST`.
7. Still ambiguous after 1–6 → `SUGGESTION`.

### 7.3 BUG rule

Classify `BUG` only when the item traces, where possible, to an existing
accepted requirement/capability — Scope, `specs.md`, or other previously
accepted project behaviour — that is not behaving as required.

- Do **not** classify as `BUG` merely because the client used the word "bug."
- If the requested behaviour never existed in the approved requirements,
  assess it as a possible `CHANGE_REQUEST` instead — it cannot be a `BUG` if
  there was never an accepted requirement to violate.
- Development effort never determines this classification.
- Record `Affected Existing Requirement IDs` when traceable; if no match is
  found, state that explicitly rather than leaving it blank with no note
  (Section 8).

### 7.4 ENHANCEMENT rule

Classify `ENHANCEMENT` when the feedback improves usability, presentation,
quality, or implementation of an existing accepted capability **without**
materially expanding the approved product/scope boundary — e.g. a minor UI
usability improvement, a presentation refinement, non-scope-expanding
workflow polish.

- Assess actual Scope/Specs impact, not apparent implementation size.
- Do **not** classify an additional product capability as `ENHANCEMENT`
  simply because it looks small to build. Small effort is not evidence of
  "no scope impact."

### 7.5 CHANGE_REQUEST rule

Classify `CHANGE_REQUEST` when the feedback adds, removes, or materially
changes an approved product capability, workflow, user role, permission
model, integration, platform, business rule, data requirement, acceptance
condition, or delivery/project responsibility.

- Effort is irrelevant — a small implementation may still be a
  `CHANGE_REQUEST`; a large correction may still be a `BUG`.
- This is the **only** classification that creates a CR (Section 12).

### 7.6 Supporting classifications

- **SUGGESTION** — record as-is; never force it into `ENHANCEMENT` or
  `CHANGE_REQUEST` to resolve ambiguity. It may be reclassified later once
  evidence solidifies (Section 14).
- **CLARIFICATION** — the preferred outcome whenever evidence is insufficient
  to safely distinguish Bug/Enhancement/CR. Record the specific question that
  would resolve it; surface it prominently in the PM report (Section 19).
- **DUPLICATE** — see Section 15 (substantive equivalence required; lexical
  similarity alone is not sufficient, and dissimilar wording does not rule it
  out).
- **NOT_ACTIONABLE** — used conservatively; if in doubt between
  `NOT_ACTIONABLE` and `CLARIFICATION`, prefer `CLARIFICATION`.

### 7.7 Classification confidence

Record `Classification Confidence` as exactly one of `HIGH` / `MEDIUM` /
`LOW` for every item classified `BUG`, `ENHANCEMENT`, or `CHANGE_REQUEST`. No
numeric precision (no percentages, no decimals) — this is a PM-facing signal,
not a model score.

- `LOW`-confidence items on a material classification (especially
  `CHANGE_REQUEST` and `BUG`) are surfaced prominently and separately in the
  final report (Section 19) — never buried in the item table alone.
- When confidence would be `LOW` **and** the ambiguity is about missing
  information rather than a judgment call, prefer reclassifying as
  `CLARIFICATION` over recording a low-confidence guess (Section 7.6).

### 7.8 Classification ≠ Approval — stated operationally

`CHANGE_REQUEST` classification means only: *"this feedback item represents a
proposed scope change."* It never means approved, authorised, commercially
accepted, ready to implement, or incorporated. This Skill:

- never sets a CR `Status` to anything other than `DRAFT` at creation;
- never writes `Decision`, `Decision Date`, `Decision By`, or `Approval
  Evidence` on a CR;
- never writes a Change Log entry;
- never edits Scope or `specs.md`.

A Feedback Item's own `Status` (Section 16) likewise never implies CR
approval — it tracks feedback handling only.

---

## 8. Traceability rules

Where applicable, compare each item against Intent, Scope, `specs.md`, the
existing Feedback Tracker, and the existing CR Register — read-only, never
written to except the Tracker/Batch/CR files this Skill itself owns.

- Populate `Affected Existing Requirement IDs`, `Affected Scope IDs`,
  `Affected Artifact`, `Affected Module` **only** when evidence supports the
  specific reference.
- A no-match is recorded explicitly (e.g. `Affected Existing Requirement IDs:
  none identified`) — never left blank with no indication whether it was
  checked.
- Never fabricate a requirement/scope ID that does not exist in the current
  `specs.md` / Scope files.
- Reverse traceability for any resulting CR is enabled by the CR's own
  `Origin Feedback Batch` / `Origin Feedback Item` fields (Section 12) — this
  Skill does not need to write anything into `specs.md` to achieve that; the
  `Change Source` tagging of `specs.md` requirements happens only during
  incorporation, owned by `change-request-management`.

---

## 9. Batch procedure — Feedback Batch ID allocation

0. **Start the transaction first** (Section 27) if it is not already open for
   this run — no step below may write anything until
   `.pmo/feedback-transaction.json` exists, is confirmed readable, and
   matches the current project.
1. **Read project identity** from `.pmo/project-config.yaml` (`project.id`,
   `project.name`). Verify against any PM-stated project identifier
   (`PMO-FEEDBACK-001`). (Already done once as part of starting the
   transaction — Section 27 step 1; re-confirming here is cheap and keeps
   this procedure self-contained.)
2. **Establish the received-date year.** The batch ID's `YYYY` is the
   feedback's **Received Date** year, not the processing date, when the
   received date is known.
   - If the PM has not stated a received date and it cannot be safely
     inferred from the material itself (e.g. a dated email header, a dated
     transcript), **do not fabricate it.** Ask the PM for the received date
     before allocating a Batch ID (`PMO-FEEDBACK-002`). Batch ID allocation
     is a one-way, immutable action — it must not be performed on a
     provisional/guessed year that might later prove wrong, because the ID
     could never be renumbered to correct it.
   - If the PM explicitly confirms the received date is genuinely unknown and
     directs the Skill to proceed, record `Received Date: UNKNOWN (PM
     confirmed unrecoverable)` in the batch's Document Control, use the
     **processing date's** year for `YYYY`, and flag this prominently in the
     final report — this is the only permitted fallback, and only on
     explicit PM direction, never assumed.
3. **Inspect existing canonical records before allocating `NNN`:** read the
   Feedback Batch Register (`feedback-tracker.md` §7) and list
   `docs/pmo/feedback/batches/FB-YYYY-*.md` for the target year. `NNN` is the
   next sequential, zero-padded 3-digit number for that year — never inferred
   from conversation history, never left with a silent gap
   (`PMO-FEEDBACK-003`).
4. **Allocate** `FB-YYYY-NNN` and its Logical Global ID
   `<Project-ID>::FB-YYYY-NNN`. This ID is immutable, never renumbered, never
   reused, from this point forward — including if the batch later turns out
   to contain zero actionable items. Update the open transaction marker's
   `feedback_batch_id` to this value (a same-transaction, same-`started_at`
   status-preserving edit — allowed per Section 27/28).
5. **Create the batch record** by copying
   `docs/pmo/feedback/batches/_TEMPLATE-FB.md` to
   `docs/pmo/feedback/batches/FB-YYYY-NNN.md` (the template itself is never
   edited in place) and completing its Document Control per the schema in
   `feedback-tracker.md` §3.
6. **Preserve original feedback** (Section 10) into the batch's *Original
   Feedback (Verbatim)* section before any extraction/classification begins.
7. Set `Classification Status: IN_PROGRESS` while items are being extracted
   and classified; move to `CLASSIFIED` only once every item has a final
   classification (Section 7) and the item count matches (Section 13).

---

## 10. Original feedback preservation

- The client/source content is preserved **substantially as received** in
  each batch's *Original Feedback (Verbatim)* section — pasted transcript
  excerpt, quoted email text, or a precise reference to an already-archived
  source file under `docs/pmo/sources/`.
- Never silently replace, paraphrase, or "clean up" the client's wording in
  this section (`PMO-FEEDBACK-004`).
- Every item's interpretation is recorded **separately**, in *Normalized
  Interpretation / Processing Notes* (batch-level) and the item's own
  `Normalized Interpretation` field — never represented as, or intermixed
  with, a verbatim client statement.
- Source files supplied by the PM (attachments, exported documents) are never
  rewritten; this Skill only quotes or references them.

---

## 11. Item extraction procedure — Feedback Item ID allocation

1. Read the batch's preserved Original Feedback (Section 10) end to end.
2. Identify each **independently actionable** requirement/issue/question.
   - One client statement may produce more than one item **only** when it
     contains genuinely independent actionable points (e.g. "the checkout
     button is broken and we'd also like Arabic support on the receipts" →
     two items).
   - Do **not** over-fragment an ordinary sentence into multiple items when
     it expresses one point.
   - Do **not** merge unrelated feedback into one item merely because it was
     delivered in the same paragraph or message.
3. Allocate item IDs **sequentially within the batch**, starting at `-001`:
   `FB-YYYY-NNN-001`, `FB-YYYY-NNN-002`, ... and their Logical Global IDs
   `<Project-ID>::FB-YYYY-NNN-NNN`. Immutable once persisted — never
   renumbered, never reused, even if a later item is found to be a duplicate
   or not-actionable.
4. For each item, complete the full schema from `feedback-tracker.md` §9
   (Original Feedback, Normalized Interpretation, Classification,
   Classification Rationale, Classification Confidence, traceability fields,
   Status, Evidence/Source Reference, dates) directly in the batch file's
   *Feedback Items* section, following the structure in
   `_TEMPLATE-FB.md`.
5. Set each item's initial `Status` per Section 16 (Phase-1 vocabulary only —
   never `READY_FOR_QA`).
6. Update `Item Count` on the batch's Document Control to the number of items
   actually written.

---

## 12. CR-creation procedure — CLIENT_REQUESTED DRAFT CRs

For every item whose **final** classification is `CHANGE_REQUEST` (i.e. not
itself a `DUPLICATE` of an existing CR-backed item — Section 15):

1. **Inspect the existing CR Register** (`change-request-register.md` §8) and
   list `docs/pmo/cr/CR-*.md` before allocating an ID — never infer the next
   `CR-NNN` from conversation history (`PMO-FEEDBACK-003`).
2. **Allocate** the next sequential `CR-NNN` (project-scoped, register-global,
   never per-year) and its Logical Global ID `<Project-ID>::CR-NNN`.
   Immutable, never renumbered, never reused.
3. **Create the CR record** by copying `docs/pmo/cr/_TEMPLATE-CR.md` to
   `docs/pmo/cr/CR-NNN.md` (template never edited in place) and completing:
   - `Origin: CLIENT_REQUESTED`
   - `Origin Feedback Batch: FB-YYYY-NNN`, `Origin Feedback Item:
     FB-YYYY-NNN-NNN` — must resolve to the real batch/item just written
   - `Description`, `Business Rationale`, `Proposed Change`, `Scope Impact`,
     `Technical Impact`, `Affected Modules/Scope/Requirements` drawn from the
     item's Normalized Interpretation and traceability fields
   - `Status: DRAFT`
   - a `Status History` row: `— | — | DRAFT | <this Skill / PM> | initial
     creation from FB-YYYY-NNN-NNN`
4. **Register** the new CR as a row in `change-request-register.md` §8.
5. **Link back:** set the Feedback Item's `Related CR: CR-NNN`.
6. **Verify bidirectional consistency** before reporting success: the CR's
   `Origin Feedback Item` must equal the item's own ID, and the item's
   `Related CR` must equal the CR's own ID. A mismatch is
   `PMO-FEEDBACK-008` and blocks completion of this item's processing.
7. This Skill stops here. It never sets `Status` to anything past `DRAFT`,
   never records `Decision`/`Approval Evidence`, and never writes to the
   Change Log.

**No CR for other classifications.** `BUG`, `ENHANCEMENT`, `SUGGESTION`,
`CLARIFICATION`, and `NOT_ACTIONABLE` items never create a CR. A `DUPLICATE`
item never creates a **second** CR for the same underlying ask — see Section
15 for when something that looks like a duplicate is not actually one.

---

## 13. Feedback Tracker update — atomicity

After batch and item processing, the Feedback Tracker and the batch record
must **agree** on: Batch ID, dates, item count, item IDs, classifications,
statuses, and CR links.

- Add/update the batch's row in `feedback-tracker.md` §7 (Feedback Batch
  Register).
- Add/update each item's row in `feedback-tracker.md` §8 (Feedback Item
  Register) — this is a rollup index; the item's authoritative full record
  stays in the batch file.
- The Tracker's rollup rows may summarize (short description, not full
  verbatim text) but every row must carry enough (Batch ID, Item ID) to
  resolve back to the full record in the batch file — never a dangling
  index entry.
- Treat the batch file and Tracker update as one logical transaction: if the
  Tracker cannot be updated after the batch file is written, do not report
  the batch as complete (`PMO-FEEDBACK-013`) — see Section 17.

---

## 14. Manual PM correction procedure

The PM may correct a prior classification at any time, e.g.: *"Change
FB-2026-004-003 from ENHANCEMENT to CHANGE_REQUEST because it adds a new
payment workflow."*

1. **Never overwrite** the item's original classification fields in place.
   Append a `Classification History` entry on the item (in the batch file):

   | Date | Previous Classification | New Classification | Overridden By |
   Rationale |
   |---|---|---|---|---|

2. Update the item's **current** `Classification`, `Classification
   Rationale`, and `Classification Confidence` to the new values, and update
   `Last Updated`.
3. Update the Tracker's rollup row (Section 13) to match.
4. **If the new classification is `CHANGE_REQUEST`** and the item had no
   `Related CR` (or its only prior CR was itself `CANCELLED` per step 5
   below): run the CR-creation procedure (Section 12) in full, including the
   bidirectional-link verification. The new CR's `Description` notes it
   originated from a PM reclassification, citing the item's Classification
   History entry — never presented as if extracted directly from the
   original evidence.
5. **If the item is reclassified away from `CHANGE_REQUEST`** (e.g. to
   `BUG`) and it has a `Related CR`:
   - If that CR's `Status` is still `DRAFT` (has never been transitioned
     beyond intake): this Skill may transition it to `CANCELLED` with a
     `Status History` row recording the reclassification as the reason,
     `Decision By` = the PM who made the correction, `Decision Date` = now.
     The Feedback Item's `Related CR` field is **retained**, not cleared,
     annotated as `Related CR: CR-NNN (CANCELLED — reclassification, see
     Classification History)` — history is never destroyed
     (`approved_artifacts_immutable`-style discipline applied here too).
   - If that CR's `Status` has already progressed past `DRAFT` (e.g.
     `PM_REVIEW` or later), this Skill has **no authority** to change it
     (Section 2). Record the reclassification and rationale on the Feedback
     Item as normal, leave the CR untouched, and surface this explicitly in
     the final report as an item requiring PM action via
     `change-request-management` (`PMO-FEEDBACK-010` if this Skill is ever
     asked to force the transition instead — refuse and report, do not
     comply).
6. Never silently delete a CR record, a batch record, or a Tracker row as
   part of a correction.

---

## 15. Duplicate handling

Before finalizing any classification conclusion, inspect the existing
Feedback Tracker (all batches) and the existing CR Register for a
**substantively equivalent** prior item.

- Different wording does **not** automatically mean different feedback; do
  not skip the check just because phrasing differs.
- Similar wording does **not** automatically mean the same feedback;
  classify `DUPLICATE` only on **substantive equivalence** of the underlying
  ask — never on lexical similarity alone.
- A true duplicate still gets its **own new** Feedback Item ID (the client
  did provide the feedback again — that occurrence is real and is recorded),
  classified `DUPLICATE`, with `Duplicate Of: <original Feedback Item ID>`
  set. It never reuses the original ID.
- If, on inspection, the new item is **not** actually the same ask —
  overlapping topic but a materially different scope-changing request — it
  is **not** `DUPLICATE`. Classify it on its own merits (Section 7), and
  optionally note a `Related To` reference to the similar prior item for
  context; this may still create its own CR under Section 12.
- A `DUPLICATE` item never creates a second CR for the same underlying ask.

---

## 16. Feedback status (Phase 1)

Use only the Phase-1 vocabulary from `feedback-tracker.md` §6: `OPEN`,
`ACKNOWLEDGED`, `IN_PROGRESS`, `RESOLVED`, `REJECTED`, `DUPLICATE`,
`DEFERRED`. **Never** `READY_FOR_QA` — it is explicitly excluded from Phase 1.

- New items default to `Status: OPEN` unless the PM directs otherwise at
  intake.
- A `DUPLICATE`-classified item's `Status` is set to `DUPLICATE` directly
  (its handling is complete once linked).
- Feedback status **never** implies CR approval — a `CHANGE_REQUEST` item can
  sit at `OPEN` or `ACKNOWLEDGED` indefinitely while its linked CR is still
  `DRAFT`; the two states are independent.

---

## 16a. Outcome of a recorded item against an APPROVED baseline

This Skill still never writes `specs.md`. Once an item is recorded and
classified, what happens to an approved Specs baseline is decided by exactly
one of three outcomes (assessed read-only by `specs-feedback-amendment.py
assess`, never by this Skill's own judgement of "meaning unchanged"):

| Outcome | Meaning | Mechanism |
|---|---|---|
| `NO_ARTIFACT_CHANGE` | Feedback needs no Specs edit (resolved / duplicate / not actionable) | `specs-feedback-amendment.py resolve-no-change`; Specs, approval, publication and version untouched |
| `FEEDBACK_AMENDMENT` | A wording-only correction (typo, capitalization, punctuation, grammar, declared terminology equivalence or uniform rename) that is PROVEN not to change requirement meaning | `specs-feedback-amendment.py begin / finalize`: next minor Specs version, `Execution Authorized: false`, Change History row, Feedback-Item `Change Source`, previous approval and bytes archived; needs fresh PM approval and its own publication |
| `CHANGE_REQUEST_REQUIRED` | Anything substantive (requirements, actors, workflow, permissions, acceptance outcomes, business rules, integrations, numbers, identifiers, applicability states, mappings, tables, headings) | The existing CR lifecycle (Section 12); nothing is written and no CR is created automatically |

A Specs amendment may start only from a canonical Feedback Item recorded here
(never a direct edit followed by retroactive Feedback) whose own text attests the
requested correction. PM-facing wording never exposes guard codes.

---

## 17. No Scope / Specs / Intent mutation — integrity checks

Before starting any write in a processing run, compute a content hash (or
equivalent integrity snapshot) of every file under `docs/pmo/scope/`,
`docs/pmo/specs/specs.md`, and every file under `docs/pmo/intent/`. After all
writes for the run complete, recompute and compare.

- If **any** of those files differ from their pre-run snapshot for any
  reason — including as a side effect of this Skill's own logic — the run
  **fails closed**: do not report success, do not leave the transaction
  half-applied where avoidable, and surface `PMO-FEEDBACK-006` (Scope/Specs)
  or `PMO-FEEDBACK-007` (Intent) in the result.
- This Skill has no legitimate code path that writes to any of these three
  locations. The check exists to catch a defect, not to permit an
  intentional write under any condition.

---

## 18. Change Log boundary

This Skill **never** writes `docs/pmo/change-log/change-log.md`. A `DRAFT`
`CLIENT_REQUESTED` CR does not create a `CHG-NNN` entry — a Change Log entry
exists only as the final step of a successful CR **incorporation**
transaction, which belongs entirely to `change-request-management`
(`PMO-FEEDBACK-011` if any code path is ever found attempting this — refuse
and report, do not comply).

---

## 19. Failure model

| Situation | Required behaviour |
|---|---|
| Batch allocated but Tracker cannot be updated to match | Do not report the batch as complete; surface the batch as `IN_PROGRESS`/inconsistent and require re-run or manual reconciliation before it is considered done (`PMO-FEEDBACK-013`). |
| Item classified `CHANGE_REQUEST` but the linked CR record cannot be created/registered | Do not report processing as complete for that item; the batch-level result explicitly lists it as incomplete (`PMO-FEEDBACK-009`). |
| CR created but the Feedback Item backlink is missing or mismatched | Reconcile (fix the link) before completion; if it cannot be reconciled in-run, report it explicitly rather than silently completing (`PMO-FEEDBACK-008`). |
| Scope/Specs/Intent changed unexpectedly (Section 17) | Fail closed — `PMO-FEEDBACK-006` / `PMO-FEEDBACK-007`. |
| An identifier would be invalid, duplicated, or reused | Fail closed on that identifier's allocation — `PMO-FEEDBACK-003`. |
| Classification is ambiguous | Use `CLARIFICATION`, never invent a forced Bug/Enhancement/CR determination. |
| Any attempt (directly or via a PM correction request) to move a CR past `DRAFT`, write the Change Log, mutate `project-config.yaml` outside Section 21's whitelist, or perform a `git`/publish operation | Refuse, do not perform it, and report why (`PMO-FEEDBACK-010` / `-011` / `-012` / `-014`). |
| Unexpected internal error mid-run | Fail closed: stop, do not claim success, report the partial state precisely (`PMO-FEEDBACK-015`). |

---

## 20. PMO-FEEDBACK-* failure / result codes

| Code | Name | Condition | Effect |
|---|---|---|---|
| `PMO-FEEDBACK-001` | `PROJECT_IDENTITY_MISMATCH` | `.pmo/project-config.yaml` missing/unreadable, or a PM-stated project identifier does not match `project.id`. | BLOCK start of processing. |
| `PMO-FEEDBACK-002` | `RECEIVED_DATE_UNKNOWN` | The feedback's received-date year cannot be established and the PM has not explicitly confirmed proceeding under the processing-date fallback (Section 9). | BLOCK Batch ID allocation until resolved. |
| `PMO-FEEDBACK-003` | `DUPLICATE_OR_REUSED_IDENTIFIER` | A Batch/Item/CR ID would collide with an existing one, or a retired/prior ID would be reused or renumbered. | BLOCK that allocation. |
| `PMO-FEEDBACK-004` | `SILENT_EVIDENCE_REWRITE` | The Original Feedback (Verbatim) section would be paraphrased/altered instead of preserved as received. | BLOCK the write. |
| `PMO-FEEDBACK-005` | `CLASSIFICATION_UNSUPPORTED` | An item is classified `BUG` / `ENHANCEMENT` / `CHANGE_REQUEST` with no rationale citing supporting evidence/requirement. | BLOCK finalising that item's classification. |
| `PMO-FEEDBACK-006` | `SCOPE_MUTATION_DETECTED` | Any file under `docs/pmo/scope/` differs from its pre-run snapshot. | FAIL CLOSED — abort, report, do not claim success. |
| `PMO-FEEDBACK-007` | `SPECS_OR_INTENT_MUTATION_DETECTED` | `docs/pmo/specs/specs.md` or any file under `docs/pmo/intent/` differs from its pre-run snapshot. | FAIL CLOSED — abort, report, do not claim success. |
| `PMO-FEEDBACK-008` | `CR_LINK_INCONSISTENT` | A `CHANGE_REQUEST` item's `Related CR` and the CR's `Origin Feedback Item` do not match each other. | BLOCK completion of that item; report explicitly. |
| `PMO-FEEDBACK-009` | `CR_CREATION_INCOMPLETE` | An item is classified `CHANGE_REQUEST` but its linked CR record/registration could not be completed. | BLOCK reporting that item — and therefore the batch — as complete. |
| `PMO-FEEDBACK-010` | `UNAUTHORIZED_CR_TRANSITION` | Any attempt to set a CR `Status` to anything other than `DRAFT` (creation) or `CANCELLED` (Section 14, DRAFT-only correction path). | REFUSE, do not perform, report. |
| `PMO-FEEDBACK-011` | `CHANGE_LOG_WRITE_ATTEMPTED` | Any attempt to write `docs/pmo/change-log/change-log.md` from this Skill. | REFUSE, do not perform, report. |
| `PMO-FEEDBACK-012` | `PROJECT_CONFIG_OVERREACH` | Any attempted write to `.pmo/project-config.yaml` outside the Section 21 whitelist. | REFUSE, do not perform, report. |
| `PMO-FEEDBACK-013` | `TRACKER_BATCH_DESYNC` | After writes, the Feedback Tracker and the batch file disagree on item count, item IDs, classifications, statuses, or CR links. | BLOCK reporting the batch complete; require reconciliation. |
| `PMO-FEEDBACK-014` | `PUBLICATION_BOUNDARY_VIOLATION` | Any attempt to `git add`/`commit`/`push`, create/switch a branch, or publish to GitHub/Bitbucket from this Skill. | REFUSE, do not perform, report. Publication is `artifact-publish`'s job. |
| `PMO-FEEDBACK-015` | `FEEDBACK_GUARD_INTERNAL_ERROR` | An unexpected error occurs during processing. | FAIL CLOSED — stop, report the precise partial state, do not claim success. |

These codes are the **design contract** for this Skill's own self-discipline
in Phase 1B. They are not yet enforced by an installed, independent
`PostToolUse` hook — that enforcement is `feedback-governance-guard`, built
separately (explicitly out of scope for this task). Until that guard exists,
this Skill is solely responsible for applying these rules to itself, and must
do so without exception.

---

## 21. Project-config.yaml protection

This Skill may **read** `.pmo/project-config.yaml` freely for project
identity and routing. Its write authority, once it is actually run against
real feedback, is a strict whitelist — **only**:

- `artifacts.feedback.latest_id` → the most recently allocated Feedback Batch
  ID (`FB-YYYY-NNN`)
- `artifacts.feedback.total_count` → the running total of Feedback **Items**
  recorded across all batches
- `artifacts.change_requests.latest_id` → the most recently allocated CR ID
  (`CR-NNN`), updated only as a direct byproduct of this Skill allocating one
  under Section 12

**Never** touched by this Skill, under any circumstance: `project.*`,
`repository.*`, `artifacts.intent.*`, `artifacts.scope.*`,
`artifacts.specifications.*`, `artifacts.change_log.*`,
`artifacts.decisions.*`, `artifacts.exports.*`, any `workflow.*` field
(including `workflow.feedback.classification_required` and
`workflow.change_request.*`), and `governance.*` (`PMO-FEEDBACK-012`).

Each write is a minimal, additive value update to the three fields above —
never a rewrite of the surrounding block, never a reformat of unrelated
sections.

**This Phase-1B task does not run this Skill against real feedback**, so no
`project-config.yaml` write occurs as part of producing this file — the
whitelist above documents what a future real run is authorised to do.

---

## 22. Publication boundary

Feedback processing and project-artifact publishing are separate operations.
This Skill never independently runs `git commit`, `git push`, creates or
switches branches, or publishes to GitHub/Bitbucket (`PMO-FEEDBACK-014`).
Publishing project artifacts — including a newly written batch, Tracker
update, or DRAFT CR — remains owned exclusively by `artifact-publish`, run
separately and explicitly by the PM.

---

## 23. Prohibited operations — summary

For quick reference, this Skill must never:

- approve, or transition past `DRAFT`, any CR (except the narrow `DRAFT →
  CANCELLED` correction path in Section 14, step 5)
- create a `PM_PROPOSED` CR
- run the CR incorporation transaction
- write `docs/pmo/change-log/change-log.md`
- write to `docs/pmo/scope/`, `docs/pmo/specs/specs.md`, or `docs/pmo/intent/`
- invent a `READY_FOR_QA` feedback status
- fabricate a received date, a requirement/scope traceability reference, or
  an identifier's sequence position
- reuse or renumber any `FB-*` or `CR-*` identifier
- rewrite or paraphrase the client's original feedback wording
- silently delete a batch, item, CR, or Tracker row
- mutate `.pmo/project-config.yaml` outside the Section 21 whitelist
- `git commit`, `git push`, branch, or publish

---

## 24. Output / result contract — PM Review Report

Every processing run ends with exactly this report shape:

```
PMO FEEDBACK MANAGEMENT RESULT

Project:
<name>

Feedback Batch ID:
<FB-YYYY-NNN>

Feedback Received Date:
<date or "UNKNOWN (PM confirmed unrecoverable)">

Source:
<source/person/organization>

Artifact:
<artifact/deliverable, version if known>

Items Extracted:
<count>

Classification Summary:
Bugs: <n>
Enhancements: <n>
Change Requests: <n>
Suggestions: <n>
Clarifications: <n>
Duplicates: <n>
Not Actionable: <n>

Item Detail:
<for every item —>
  ID: <FB-YYYY-NNN-NNN>
  Short Description: <one line>
  Classification: <value>
  Confidence: <HIGH/MEDIUM/LOW, or n/a>
  Requirement/Scope Reference: <IDs, or "none identified">
  Related CR: <CR-NNN, or "none">
  Status: <Phase-1 status>

CRs Created:
<CR-NNN, CR-NNN, ... or "none">

Low-Confidence Items:
<IDs, or "none">

Clarifications Required:
<IDs with the specific question, or "none">

Scope Changed:
NO

Specs Changed:
NO

Intent Changed:
NO

Next Human Gate:
PM_FEEDBACK_REVIEW

Publish Eligibility:
YES / NO

Final Result:
FEEDBACK_CLASSIFIED_READY_FOR_PM_REVIEW
```

`Publish Eligibility: NO` whenever any `PMO-FEEDBACK-*` block condition fired
during the run, or the Tracker/batch are not in sync (Section 17). The
`Final Result` line is then the specific fail-closed status instead (e.g.
`FEEDBACK_PROCESSING_BLOCKED_SCOPE_MUTATION_DETECTED`,
`FEEDBACK_PROCESSING_INCOMPLETE_TRACKER_DESYNC`) — never a bare failure with
no code.

---

## 25. Definition of Done

A processing run is complete, and may report
`FEEDBACK_CLASSIFIED_READY_FOR_PM_REVIEW`, only when **all** hold:

1. Exactly one Feedback Batch was allocated for this intake event, with an
   ID that did not previously exist, inspected against the real register
   (not inferred).
2. Every extracted item has a sequential, unique, immutable ID and a
   complete record per `feedback-tracker.md` §9.
3. Original feedback is preserved verbatim in the batch file, separate from
   any Normalized Interpretation.
4. Every item has exactly one of the seven allowed classifications, with a
   rationale citing evidence (never effort), and a confidence value where
   required.
5. Every `CHANGE_REQUEST` item has exactly one linked `DRAFT`
   `CLIENT_REQUESTED` CR, bidirectionally consistent, unless it is itself a
   true `DUPLICATE` of an already-CR-linked item.
6. No `BUG` / `ENHANCEMENT` / `SUGGESTION` / `CLARIFICATION` /
   `NOT_ACTIONABLE` item created a CR.
7. No CR was moved past `DRAFT` (except a `DRAFT → CANCELLED` correction per
   Section 14).
8. No Change Log entry was written.
9. The Feedback Tracker and the batch file agree on every synchronized field
   (Section 13).
10. `docs/pmo/scope/`, `docs/pmo/specs/specs.md`, and `docs/pmo/intent/` are
    byte-identical to their pre-run state.
11. No `git`/publish operation was performed.
12. Any `.pmo/project-config.yaml` write, if this were a real run, stayed
    within the Section 21 whitelist.
13. The PM Review Report (Section 24) was produced in full, including an
    explicit, non-empty accounting of low-confidence items and required
    clarifications (even when both are "none").
14. A governed transaction was open (Section 27) for every write in this run,
    full reconciliation (Section 29) passed, and
    `.pmo/feedback-transaction.json` was removed as the last step — never
    left at `ACTIVE`/`RECONCILING` after a run that reports completion.

If any condition fails, the run reports the specific `PMO-FEEDBACK-*`
condition and a corresponding non-success `Final Result` — it never reports
`FEEDBACK_CLASSIFIED_READY_FOR_PM_REVIEW` while a condition above is unmet. A
run that fails leaves the marker at `RECOVERY_REQUIRED` (Section 30), never
silently removed and never left at a stale `ACTIVE`.

---

## 26. Transaction Marker — schema, path, and ownership

Canonical path: **`.pmo/feedback-transaction.json`**.

It is **ephemeral runtime governance state**, scoped to a single processing
run. It is explicitly **not**: project history, client evidence, a Feedback
artifact, a CR artifact, something to publish, or something to commit — it is
never referenced from a PM-facing report as a deliverable, and it plays no
part in Section 22's publication boundary except as something that must never
be committed or pushed.

Schema (this mirrors `feedback-governance-guard.py`'s enforced contract
exactly; the installed guard is authoritative if this section and the guard
ever disagree — Section 1):

```json
{
  "transaction_type": "FEEDBACK_MANAGEMENT",
  "transaction_id": "<opaque, unique per run, e.g. FBTX-<UTC timestamp>-<short random>>",
  "project_id": "<must equal .pmo/project-config.yaml project.id>",
  "feedback_batch_id": null,
  "started_at": "<ISO 8601 UTC timestamp, set once at creation, never rewritten>",
  "status": "ACTIVE"
}
```

| Field | Required | Notes |
|---|---|---|
| `transaction_type` | **Yes** | Always the literal `"FEEDBACK_MANAGEMENT"`. |
| `transaction_id` | **Yes** | Freshly generated per run; never reused. |
| `project_id` | **Yes** | Must equal `.pmo/project-config.yaml` `project.id`. |
| `feedback_batch_id` | No | `null` until a batch id is allocated (Section 9 step 4), then that id. |
| `started_at` | **Yes** | Set once at creation; immutable for the life of the transaction. |
| `status` | **Yes** | One of `ACTIVE` / `RECONCILING` / `RECOVERY_REQUIRED`. |

There is deliberately **no `COMPLETE` status**: successful completion is
signalled by **removing the file** — a plain out-of-band deletion, not a
Write/Edit. The guard does not need to authorise a deletion, and deleting an
ephemeral marker carries no governance risk, so a fourth status would only
add state without adding safety.

`RECOVERY_REQUIRED` **is** needed (recommended and adopted by this Skill):
it durably records a controlled failure — blocking further feedback writes
(`feedback-governance-guard.py` returns `PMO-FEEDBACK-GUARD-025` for any
Tracker/Batch/Register/CR write while it is set) and preserving diagnostic
context — without requiring a wall-clock "is this still really running"
heuristic. Seeing `RECOVERY_REQUIRED` is sufficient on its own to know a
human must look at it before anything resumes; this keeps the whole marker
lifecycle to three simple states rather than inventing an age-based staleness
calculation.

**Ownership**: `feedback-management` owns creating, transitioning, and
normally removing this file (Sections 27–30). `feedback-governance-guard.py`
only reads and validates it — it does not create, remove, or decide when a
transaction starts or ends. **No other Skill may create this marker.** A
marker's mere existence is a claim that a feedback-management run is in
progress; only this Skill may make that claim truthfully. If a future Skill
(e.g. `change-request-management`) ever needs similar cross-artifact
protection, it must get its own, differently-named marker and its own guard
logic — never reuse or repurpose this one.

---

## 27. Starting a transaction

Before creating or editing the Feedback Tracker, a Feedback Batch, the CR
Register, or a `CLIENT_REQUESTED` `DRAFT` CR, run this sequence in order:

1. **Validate project identity** — read `.pmo/project-config.yaml`; confirm
   `project.id` against any PM-stated project identifier (Section 6,
   `PMO-FEEDBACK-001`).
2. **Confirm no incompatible active marker exists** — if
   `.pmo/feedback-transaction.json` is already present, classify it per
   Section 31 *before* doing anything else, and proceed to step 3 only if it
   is genuinely absent (Section 31's table covers every other case, and each
   of them is a STOP, not a continue).
3. **Capture protected-state baselines** — confirm `docs/pmo/scope/`,
   `docs/pmo/specs/specs.md`, and `docs/pmo/intent/` exist and are readable
   right now, so that any later, unexpected difference is immediately
   recognisable as a defect rather than assumed away.
4. **Create `.pmo/feedback-transaction.json`** with the full schema
   (Section 26): `status: "ACTIVE"`, a freshly generated `transaction_id`,
   `started_at` set to now, and `feedback_batch_id: null` (filled in once
   allocated — Section 9 step 4).
5. **Confirm the marker is readable and belongs to the current project** —
   re-read the file just written; verify it parses and its `project_id`
   matches. This is the same check `feedback-governance-guard.py` itself
   performs before allowing any further feedback-owned write, so confirming
   it here catches a problem before any batch/CR work is attempted.
6. **Only then** begin governed writes (Section 9 onward).

**If marker creation fails** — the write is denied, or step 5's re-read
fails — **STOP**. No feedback project artifact may be written. Report the
failure plainly. Do not retry by silently altering the marker's `project_id`
or `transaction_id` to force it through, and do not fall back to writing
Tracker/Batch/CR files without an OPEN marker: `feedback-governance-guard.py`
denies them anyway (`PMO-FEEDBACK-GUARD-025`), and attempting it regardless
would only turn a clean stop into a confusing partial failure.

---

## 28. Active transaction discipline

While the marker exists, every Write/Edit this Skill makes to
Tracker/Batch/Register/CR/Scope/Specs/Intent/source-evidence/
`project-config.yaml` paths is subject to `feedback-governance-guard.py`.
Operationally:

- **Never bypass, delete, or modify the marker merely to avoid a guard
  denial.** A denial means the attempted write was invalid or outside this
  Skill's authority — not an obstacle to route around. In particular, never
  respond to a denial by rewriting the marker to a different
  `transaction_id`, or by deleting it mid-run to "start clean" — both are
  exactly the impersonation/overwrite pattern the guard exists to block
  (`PMO-FEEDBACK-GUARD-024`); doing either from inside this Skill would be
  self-impersonation, not a fix.
- **If the guard denies an operation, STOP the transaction.** Do not
  continue subsequent writes as though the denied write had succeeded — a
  denied Tracker update, for instance, means the Tracker and the Batch file
  may now disagree; proceeding to create a CR that assumes the Tracker
  update happened would compound the inconsistency instead of containing it.
- Move the marker's `status` to `RECONCILING` (a same-`transaction_id`,
  same-`started_at`, status-only edit — allowed by the guard) once all
  intended writes for the run are done and only the Section 29 reconciliation
  checks remain. Move it to `RECOVERY_REQUIRED` if a denial or inconsistency
  is discovered that this run cannot safely resolve on its own (Section 30).

---

## 29. Successful completion and marker removal

Before removing the marker, perform final reconciliation — **every** check
below must pass:

- Feedback Tracker and the Batch file(s) agree (Batch ID, dates, item count,
  item IDs, classifications, statuses, CR links — Section 13).
- Every item has exactly one of the seven allowed classifications, with
  rationale and (where required) confidence populated (Section 7).
- CR consequences are valid: every `CHANGE_REQUEST` item has exactly one
  linked `DRAFT` `CLIENT_REQUESTED` CR (or is a true `DUPLICATE` of one); no
  other classification created a CR (Section 12).
- Feedback ↔ CR links are bidirectionally consistent (Section 12 step 6).
- `docs/pmo/intent/`, `docs/pmo/scope/`, `docs/pmo/specs/specs.md` are
  unchanged from the run's start (Section 17).
- `docs/pmo/change-log/` was not written (Section 18).
- Any `.pmo/project-config.yaml` change stayed within the Section 21
  whitelist.
- Source evidence under `docs/pmo/sources/` was not rewritten (Section 10,
  Section 23).

**Only after every check above passes**, remove
`.pmo/feedback-transaction.json` — a plain out-of-band deletion, not a
Write/Edit; there is no `COMPLETE` status to write first (Section 26). Then
emit the report (Section 24) with
`Final Result: FEEDBACK_CLASSIFIED_READY_FOR_PM_REVIEW`.

If reconciliation was entered (`status: RECONCILING`) but a check fails, do
not force the removal — fall through to Section 30 instead.

---

## 30. Failure cleanup and recovery

On a controlled failure (a guard denial that stopped the transaction per
Section 28, or a reconciliation check in Section 29 that fails):

- **Do not report success.** `Final Result` must reflect the actual
  `PMO-FEEDBACK-*` condition (Section 20), never
  `FEEDBACK_CLASSIFIED_READY_FOR_PM_REVIEW`.
- **Perform safe reconciliation** — determine exactly what was and was not
  written (which batch/item/CR records exist and in what state) so the
  report is accurate, without attempting further writes that might
  themselves fail or compound the inconsistency.
- **Preserve diagnostic evidence in the result/report** — cite the specific
  `PMO-FEEDBACK-*` and/or `PMO-FEEDBACK-GUARD-*` code, the file(s) involved,
  and the state they were left in.
- **Remove the marker only when it is safe to terminate the transaction** —
  i.e. when the partial state is fully understood and described in the
  report, and nothing was left half-written in a way a future run could
  misread as complete. If that is not yet true, move the marker to
  `RECOVERY_REQUIRED` first (recording the failure), report it, and leave
  the decision to delete it (versus investigate further) to the PM — this
  Skill does not delete a `RECOVERY_REQUIRED` marker itself.
- **Do not leave an `ACTIVE` marker merely because classification failed.**
  An `ACTIVE` marker should mean "a run is genuinely in progress right now,"
  not "a run failed here once." Move it to `RECOVERY_REQUIRED` instead —
  exactly the signal `feedback-governance-guard.py` already uses to block
  further feedback writes until this is resolved (`PMO-FEEDBACK-GUARD-025`).
- **However, do not blindly remove a marker if project state is left in an
  unresolved partial-write condition.** A `RECOVERY_REQUIRED` marker is not
  itself the problem; removing it before the underlying inconsistency is
  understood would just make that inconsistency invisible to the next run.

---

## 31. Stale marker handling at the start of a new run

If `.pmo/feedback-transaction.json` already exists when a new run begins:
**do not overwrite it automatically** — `feedback-governance-guard.py` will
refuse a same-path write that changes `transaction_id` anyway
(`PMO-FEEDBACK-GUARD-024`), but this Skill must not even attempt it. Inspect
the existing marker's `project_id`, `transaction_id`, `status`, and
`started_at`, and classify it:

| Observation | Classification | Action |
|---|---|---|
| `project_id` matches; `status` is `ACTIVE` or `RECONCILING` | Active, compatible transaction | **STOP.** Do not start a new run. Report that a feedback transaction already appears in progress (cite its `transaction_id` and `started_at`) and let the PM decide (wait, or investigate and remove it manually). |
| `project_id` matches; `status` is `RECOVERY_REQUIRED` | Interrupted transaction needing recovery | **STOP.** Do not start a new run. Report that a prior transaction requires PM/operator recovery before any new feedback can be processed for this project. |
| `project_id` does not match the configured project | Incompatible project | **STOP.** Report the mismatch plainly (`feedback-governance-guard.py` would refuse any write here regardless — `PMO-FEEDBACK-GUARD-023`). Do not remove or "correct" someone else's marker. |
| File exists but does not parse, or is missing a required field | Malformed marker | **STOP.** Report that the marker is malformed and cannot be safely classified. |

**Fail closed where uncertain**: in every row above, the action is to stop
and report — never to guess that an existing marker is safely stale and
remove it automatically. This Skill never deletes a marker it did not itself
create and successfully reconcile in the *current* run; a marker inherited
from an earlier or unknown run is always surfaced to the PM, who can remove
it out-of-band once they have confirmed it is genuinely abandoned. This keeps
recovery to the two states already defined (no marker / `RECOVERY_REQUIRED`)
rather than adding a third "probably stale" state — see "Avoid unnecessary
state complexity" in the Phase 1D brief this section implements.

---

## 32. Marker ownership — summary

- **`feedback-management` owns**: creating the marker (Section 27),
  transitioning its `status` during a run (Section 28), and removing it on
  successful completion (Section 29) or leaving it at `RECOVERY_REQUIRED` on
  controlled failure (Section 30).
- **`feedback-governance-guard.py` owns**: reading and validating every
  write to the marker and everything gated by its presence — it does not
  create, remove, or decide when a transaction starts or ends; it only
  enforces the invariants once this Skill has acted.
- **No other Skill may create, edit, or remove this marker.** No other Skill
  may impersonate feedback-management by creating this marker — its mere
  existence is a claim only this Skill may make truthfully.
