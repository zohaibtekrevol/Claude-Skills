---
name: requirement-gathering
description: >-
  Turn a VALIDATED PMO Intent into a versioned, client-facing Scope artifact
  under docs/pmo/scope/. Use after docs/pmo/intent/intent.md reaches Status
  VALIDATED (with a matching PM approval record) and before Specification
  Generation. Produces docs/pmo/scope/scope-v0.1.md and successive immutable
  drafts (scope-v0.2.md, scope-v0.3.md, ...); the client-approved baseline is
  docs/pmo/scope/scope-v1.0.md. Establishes a context map (platforms, actors,
  modules, integration inventory, source inventory, Intent-coverage inventory),
  then SCP-REQ-* scope requirements (never FR-XXX / NFR-XXX), WF-* key user and
  operational workflows, product-level WBS-* work breakdown, and the
  BRAND-OPEN-* / INTG-* / CLIENT-RESP-* / DELIVERY-RESP-* / SCP-GAP-* /
  OPEN-* (open questions carried from the Intent, keeping their exact Intent id)
  / SCP-OPEN-* (open questions first raised during Requirement Gathering) /
  SCP-DEP-* / SCP-OOS-* / SCP-ASM-* / SCP-RISK-* / SCP-CONFLICT-* /
  PSE-* / CRQ-* registers, an Intent-to-Scope traceability matrix with a row for
  every INT-REQ, client review questions, a version history, a Scope Validation
  Summary, and a final PMO REQUIREMENT GATHERING RESULT report. PMO-SCOPE-*
  failure conditions define deterministic halt behaviour. Scope approval
  authorises Specification Generation only; Development is gated on approved
  Specifications.
---

# Requirement Gathering (PMO)

## 1. Purpose and position in the PMO lifecycle

Artifact roles across the PMO lifecycle:

- **Intent** preserves **WHY** the project exists and its original context.
- **Scope** (this stage) establishes **WHAT** is being delivered.
- **Specifications** establish the **precise behaviour** for Development and QA.
- **Development Plan** establishes **HOW** implementation will be executed.

Requirement Gathering is the PMO workflow stage **between a VALIDATED Intent and
Specification Generation**. It elicits and structures the detailed,
evidence-backed project scope into a versioned, client-facing Scope artifact. It
does **not** write functional/technical specifications (`specs.md`), it does
**not** authorise development, and it does **not** create developer task
identifiers.

Purpose of the stage:

- Convert each Intent-level requirement (`INT-REQ-*`) into one or more concrete,
  testable **scope requirements** (`SCP-REQ-*`) with acceptance criteria.
- Identify the important end-to-end **user and operational workflows** (`WF-*`).
- Decompose delivery into a **product-level Work Breakdown Structure** (`WBS-*`).
- Capture brand/design evidence, the third-party **integration inventory**,
  **data and content requirements**, **client** and **delivery-team
  responsibilities**, and the **commercial / change-control boundaries**.
- Record boundaries (`SCP-OOS-*`), assumptions (`SCP-ASM-*`), dependencies
  (`SCP-DEP-*`), scope gaps (`SCP-GAP-*`), open items (open questions carried
  from the Intent keep their `OPEN-*` id; open questions first raised in
  Requirement Gathering are `SCP-OPEN-*`; brand/design questions are
  `BRAND-OPEN-*`), source conflicts (`SCP-CONFLICT-*`) and scope risks
  (`SCP-RISK-*`).
- Maintain a complete **Intent-to-Scope traceability matrix**.
- Surface every material client request not supported by the validated Intent or
  the executed contract as a `POTENTIAL_SCOPE_EXPANSION` (`PSE-*`) — never
  silently added to scope.
- Produce **client review questions** (`CRQ-*`), a **version history**, a **Scope
  Validation Summary**, and a final **PMO REQUIREMENT GATHERING RESULT** report.

`.pmo/project-config.yaml` governance applies throughout: `source_of_truth:
repository`, `markdown_authoritative: true`, `docx_export_only: true`,
`approved_artifacts_immutable: true`, `silent_assumptions_prohibited: true`.

---

## 2. Prerequisites — hard gate

Do **not** begin Requirement Gathering unless **all** of the following hold:

1. `docs/pmo/intent/intent.md` exists with document-control `Status: VALIDATED`
   and an `Intent Version` of `1.0` or higher.
2. A matching PM approval record exists at
   `.pmo/approvals/intent-approval.yaml` with `decision: APPROVED`,
   `approval_source: PM_EXPLICIT`, `artifact: docs/pmo/intent/intent.md`, a
   non-empty `approved_by`, and `version` equal to the Intent's `Intent
   Version`.
3. `.pmo/project-config.yaml` shows `workflow.intent.approved: true` and
   `workflow.current_stage` is `INTENT_VALIDATED` (or a later stage).

If any prerequisite fails, stop and report which one (see **Failure
Conditions**, `PMO-SCOPE-001` / `-002` / `-003`). Do not draft Scope from an
unvalidated Intent.

---

## 3. Source authority hierarchy and conflict handling

For initial Scope generation, sources rank in this deterministic order (highest
authority first):

1. **Validated Intent** (`docs/pmo/intent/intent.md`, VALIDATED) — authoritative
   for WHY, the actor set, and the mandatory `INT-REQ-*` coverage list.
2. **Executed contract / signed SOW** — the primary **contractual** authority
   for WHAT is sold, commercials, milestones, IP, support and change control.
3. **Approved commercial scope / LOE** — effort/cost basis and change-request
   re-pricing reference.
4. **Formal client requirements** (client-authored requirement documents/notes).
5. **Client written communications** (emails, messages).
6. **Recorded client discussions** (call transcripts, meeting notes).
7. **BD handover** materials.
8. **Internal notes**.

Rules:

- The **executed contract** overrides earlier conflicting discovery or
  commercial statements. Where the Intent already resolved such a conflict, carry
  that resolution forward.
- **If evidence conflicts, do not silently resolve it.** Raise a
  `SCP-CONFLICT-*` entry (classification `RESOLVED_BY_CONTRACT`, `UNRESOLVED`, or
  `HISTORICAL_ONLY`), and where the resolution needs client or PM input, add a
  linked `SCP-OPEN-*` and/or route it to a PM decision. A conflict is never
  converted into an assumption.

---

## 4. Mandatory project source set

The skill MUST:

- Consult **every `SRC-*`** registered in the validated Intent's Source
  Register.
- Review, **where present** under `docs/pmo/sources/`, at least: the executed
  contract / signed SOW; the approved commercial scope / LOE; formal client
  requirement documents; client emails / written communications; recorded client
  discussions (transcripts); BD handover; any roadmap referenced by or appended
  to the contract; internal notes.
- Record a **Source Inventory** in the Scope artifact: for each source — id,
  type, date, authority tier (Section 3), and `consulted: YES/NO` with a reason.
  A registered or expected source that was **not** consulted must be justified,
  and if it is material its absence is recorded as a `SCP-GAP-*` or blocking
  `SCP-OPEN-*` (see `PMO-SCOPE-013`).
- Add any **new evidence** gathered during Requirement Gathering (workshop
  notes, client confirmations, retrieved LOE/proposal/roadmap) under
  `docs/pmo/sources/` and register it **before** it is relied upon.

---

## 5. Inputs

- **Primary:** the VALIDATED `docs/pmo/intent/intent.md` — all sections and all
  `INT-REQ-*`, `INT-OOS-*`, `ASM-*`, `OPEN-*`, `CONFLICT-*`, `RISK-*`, `SRC-*`.
- **Evidence:** the mandatory source set (Section 4).
- `.pmo/project-config.yaml` for project identity and workflow state.

Do not infer missing scope. Unknowns become `SCP-OPEN-*` / `SCP-GAP-*` /
`BRAND-OPEN-*`; unsupported client asks become `PSE-*`.

---

## 6. Outputs and file naming

| Artifact | Path |
|---|---|
| First Scope draft | `docs/pmo/scope/scope-v0.1.md` |
| Subsequent drafts | `docs/pmo/scope/scope-v0.2.md`, `scope-v0.3.md`, ... |
| Client-approved baseline | `docs/pmo/scope/scope-v1.0.md` |
| Post-baseline changes (Change Request only) | `scope-v1.1.md`, `scope-v2.0.md`, ... |
| Scope approval record | `.pmo/approvals/scope-approval.yaml` |

The **initial output is exactly `docs/pmo/scope/scope-v0.1.md`**. Nothing in
`docs/pmo/scope/` other than `.gitkeep` may exist before this skill runs
(`PMO-SCOPE-005`).

---

## 7. Draft versioning and immutability

- Drafting proceeds **`0.1 → 0.2 → 0.3 → ...`**. Each review/revision cycle
  writes a **new file** at the next minor version. Minor increments only
  pre-baseline; no skipping, no decrementing, no reusing a version number; no
  `1.x` file before an approved `scope-v1.0.md` (`PMO-SCOPE-010`).
- **Existing Scope versions are never overwritten or edited in place**
  (`PMO-SCOPE-006`). A correction to `scope-v0.2.md` is issued as
  `scope-v0.3.md`; the prior file is retained verbatim as immutable history.
- Every draft's Document Control records `Supersedes: scope-v0.(N-1).md` (or
  `Supersedes: none` for `scope-v0.1.md`) and `Status: DRAFT`.
- On client approval, the approved draft's content is published **as a new
  file** `docs/pmo/scope/scope-v1.0.md` (recording `Approved from:
  scope-v0.x.md`). `scope-v1.0.md` is the immutable baseline; it changes only by
  issuing `scope-v1.1.md` / `scope-v2.0.md` through the Change Request process
  (`pm_approval_required`, `client_approval_required`,
  `commercial_clearance_required`).

---

## 8. Identifier namespaces

| Namespace | Meaning | Owning section |
|---|---|---|
| `SCP-REQ-###` | In-scope scope requirement (with acceptance criteria) | In-Scope Requirements |
| `WF-###` | Key user / operational workflow (`WF-001`, `WF-002`, ...) | Key User and Operational Workflows |
| `MOD-###` | Module / functional area | Context Map |
| `WBS-#`, `WBS-#.#`, `WBS-#.#.#` | Product-level work-breakdown element (hierarchical) | Work Breakdown Structure |
| `SCP-OOS-###` | Explicit scope exclusion | Out of Scope |
| `SCP-ASM-###` | Scope-level assumption (clearly labelled) | Assumptions |
| `SCP-DEP-###` | Dependency (typed) | Dependencies |
| `SCP-GAP-###` | Scope gap — evidence insufficient to fix scope | Scope Gaps |
| `OPEN-###` | Unresolved question **carried forward from the validated Intent**, stage-aware — keeps the exact `OPEN-###` id it had in `intent.md`, never renamed or renumbered | Open Items |
| `SCP-OPEN-###` | Unresolved scope question **first raised during Requirement Gathering / Scope creation** (no Intent origin), stage-aware | Open Items |
| `BRAND-OPEN-###` | Unresolved brand / design question, stage-aware | Brand and Design Guidelines / Open Items |
| `INTG-###` | Third-party integration (`INTG-001`, `INTG-002`, ...) | Third-Party Integrations |
| `CLIENT-RESP-###` | Client responsibility (evidence-referenced) | Client Responsibilities |
| `DELIVERY-RESP-###` | Delivery-team responsibility (evidence-referenced) | Delivery Team Responsibilities |
| `SCP-RISK-###` | Scope-level, evidence-based risk | Risks |
| `SCP-CONFLICT-###` | Source conflict surfaced during Requirement Gathering | Source Conflicts |
| `PSE-###` | Potential Scope Expansion — client ask with no Intent/contract basis | Potential Scope Expansion |
| `CRQ-###` | Client review question (may reference existing `OPEN` / `SCP-OPEN` / `BRAND-OPEN` / `SCP-GAP` ids) | Client Review Questions |
| `TRACE-INT-REQ-###` | Traceability matrix row — one per `INT-REQ-*` | Intent-to-Scope Traceability Matrix |
| `PMO-SCOPE-###` | Failure / governance condition (`PMO-SCOPE-001` ...) | Failure Conditions |

**`FR-XXX` / `NFR-XXX` (`FR-###` / `NFR-###`) MUST NOT appear in any Scope
artifact** — they are reserved for `specs.md` in Specification Generation. Scope
requirements are always `SCP-REQ-*` (`PMO-SCOPE-008`).

**No developer task identifiers** (e.g. `TASK-###`, `DEV-###`, ticket keys).
The WBS is product-level only.

**Identifier stability:** every identifier is assigned once and **never
renumbered or reused across versions** (`PMO-SCOPE-009`). When a `SCP-REQ` (or
any other identifier) is dropped, its number is **retired and left as a gap**
with a one-line note; it is not reused, and remaining identifiers are **not**
renumbered to close the gap.

**OPEN identifier provenance (lifecycle identity).** A question first raised in
the validated Intent keeps its exact `OPEN-###` identifier in **every**
downstream artifact — Scope, Specifications, and Development / QA governance. It
is **never** re-prefixed to `SCP-OPEN-###` and never renumbered; carrying it
forward is not a rename. `SCP-OPEN-###` is reserved for a question **first
raised during Requirement Gathering / Scope creation** with no Intent origin. A
retired Intent `OPEN-###` id is never reused for a different Scope question.
`scope-version-guard.py` enforces this deterministically (`PMO-SCOPE-015`): a
`SCP-OPEN-###` record that cites a carried Intent `OPEN-###`, or a bare
`OPEN-###` record that matches no `OPEN` definition in `intent.md`, is blocked.

---

## 9. Workflow stages and the SCOPE_BASELINE gate

Canonical workflow stage order (shared with the Intent governance):

```
INTENT_VALIDATION
REQUIREMENT_GATHERING
SCOPE_BASELINE
SPECIFICATION_GENERATION
DEVELOPMENT
QA
UAT
DEPLOYMENT
```

- Every stage-aware register item (`OPEN-*`, `SCP-OPEN-*`, `BRAND-OPEN-*`,
  `SCP-GAP-*`) records `Blocking: YES|NO` and a `Required Before` value drawn
  **only** from the list above. An unrecognised stage makes the record invalid.
- **Unresolved `SCOPE_BASELINE` blockers do NOT stop Scope drafting.** Drafts
  `scope-v0.x.md` may be authored, reviewed and iterated while such items are
  open; each carries forward under its stable identifier (`OPEN-*` when carried
  from the Intent, otherwise `SCP-OPEN-*` / `BRAND-OPEN-*` / `SCP-GAP-*`).
- **Unresolved `SCOPE_BASELINE` blockers DO stop Scope approval.**
  `scope-v1.0.md` MUST NOT be produced while any `Blocking: YES` item —
  inherited from the Intent's future-gate blockers or raised during Requirement
  Gathering — has `Required Before: SCOPE_BASELINE` and is still open
  (`PMO-SCOPE-011`).
- **Inherit** the validated Intent's future-gate blockers into the Scope Open
  Items register **under their original `OPEN-*` identifiers** — carried
  unchanged, never re-prefixed to `SCP-OPEN-*` (`PMO-SCOPE-015`). Confirm the
  list against the Intent's Scope-baseline blocker section at run time; each
  carried row records that it originates in the Intent (its id already makes the
  provenance explicit).
- Items gated at `SPECIFICATION_GENERATION` or later may remain open at Scope
  baseline and carry forward. `BRAND-OPEN-*` items that must be resolved before
  design is approved are gated at `SPECIFICATION_GENERATION` (design detail is
  produced with the specifications), unless the brand gap changes scope size, in
  which case `SCOPE_BASELINE`.

---

## 10. Context map — establish BEFORE detailed SCP-REQ generation

Before any `SCP-REQ-*` is written, establish and record a **Context Map**:

- **Product platforms / interfaces** — from Intent Sections 4–5 + contract
  (e.g. customer mobile app, rider app, web admin panel, backend service).
- **User / actor model** — from Intent Section 5: primary actors, supporting
  actors, external systems.
- **Module map** (`MOD-###`) — the functional areas of the product; **every
  `SCP-REQ` maps to exactly one `MOD`**.
- **Integration inventory** (`INTG-###`) — every third-party integration named
  anywhere in the evidence.
- **Source inventory** (Section 4) — every `SRC-*`, its authority tier, and
  consulted status.
- **Intent coverage inventory** — the full list of `INT-REQ-*` from the
  validated Intent's requirements section that must be traced (retired
  identifiers, e.g. `INT-REQ-006`, noted as gaps, not rows to satisfy).

Detailed requirement elicitation begins **only after** this map exists.

---

## 11. Procedure

1. **Verify the gate** (Section 2). Stop and report on any failure
   (`PMO-SCOPE-001..004`).
2. **Read project state:** load `.pmo/project-config.yaml`; confirm project
   identity matches; read the validated `intent.md` end to end; list
   `docs/pmo/scope/` (must contain no `scope-v*.md` on first run —
   `PMO-SCOPE-005`); check for an existing `scope-approval.yaml`.
3. **Consume the mandatory source set** (Section 4); build the Source Inventory.
4. **Build the Context Map** (Section 10): platforms, actor model, module map
   (`MOD-*`), integration inventory (`INTG-*`), source inventory, Intent
   coverage inventory.
5. **Identify key workflows** (`WF-*`) supported by evidence (Section 14).
6. **Elicit detailed scope requirements** (`SCP-REQ-*`, Section 13): for each
   `INT-REQ-*` derive one or more `SCP-REQ` with plain-language statements and
   testable acceptance criteria, each assigned to a `MOD`. Keep at Scope
   altitude — behaviour and boundaries, not field-level design, UI specs or API
   contracts.
7. **Build the product-level WBS** (`WBS-*`, Section 12 §8): phases → work
   packages → deliverables, each linked to the `SCP-REQ-*` it delivers. No
   developer task identifiers.
8. **Capture** brand/design evidence + `BRAND-OPEN-*` (Section 15); the
   third-party integration inventory `INTG-*` (Section 16); data & content
   requirements (Section 17); `CLIENT-RESP-*` (Section 18); `DELIVERY-RESP-*`
   (Section 19); commercial & change-control boundaries (Section 21).
9. **Record** `SCP-OOS-*` (carry Intent `INT-OOS-*` + new; do not convert
   "optional / pending client election" items into exclusions unless the client
   elects out); `SCP-ASM-*` (each explicitly an assumption; a Gap never becomes
   an assumption); `SCP-DEP-*` (typed); `SCP-GAP-*` (Section 20); `SCP-RISK-*`
   (project-specific, evidence-based); `SCP-CONFLICT-*` (Section 3).
10. **Carry open items:** carry every unresolved Intent `OPEN-*` forward into the
    Scope Open Items register **keeping its exact `OPEN-*` identifier** (never
    re-prefixed to `SCP-OPEN-*`; `PMO-SCOPE-015`); create `SCP-OPEN-*` only for
    questions first raised during Requirement Gathering. Each row carries
    `Blocking` and a canonical `Required Before` stage (Section 9).
11. **Handle unsupported client asks:** anything material the client wants that
    the validated Intent and executed contract do not support → `PSE-*`
    (Section 23). Never fold it silently into `SCP-REQ-*` (`PMO-SCOPE-012`).
12. **Build the Intent-to-Scope traceability matrix** — one `TRACE-INT-REQ-*`
    row per `INT-REQ-*` (Section 24). A missing row blocks client-review
    readiness (`PMO-SCOPE-007`).
13. **Generate client review questions** (`CRQ-*`, Section 25) from unresolved
    items needing client input.
14. **Write the draft** as the next `scope-v0.x.md` (Section 12 structure).
    First run writes `scope-v0.1.md`. Never overwrite an existing version.
    Update the **Version History** table (Section 26).
15. **Run the quality validation rules** (Section 31) and populate the Scope
    Validation Summary.
16. **PM review → client review:** handle client feedback per Section 27; each
    revision is a new minor version. Move `Status` through
    `DRAFT → PM_REVIEWED → CLIENT_REVIEW`.
17. **Approve** only when every Section 28 condition holds: publish
    `scope-v1.0.md` as a new file and write
    `.pmo/approvals/scope-approval.yaml` (`PMO-SCOPE-014`).
18. **Update `.pmo/project-config.yaml`** (Section 30): apply the draft-state
    update (Section 30.1) as soon as each draft is written at step 14; apply the
    approval-state update (Section 30.2) only after step 17 completes with a
    published `scope-v1.0.md` plus a well-formed approval record, and only when
    explicitly instructed.
19. **Emit the final report** (Section 35). Do not generate `specs.md`; do not
    plan or create development tasks; do not commit or push unless asked.

---

## 12. Client-facing Scope document structure (`scope-vX.Y.md`)

The Scope artifact is a **client-facing deliverable**. Write it in plain
language. It MUST NOT contain internal PM commentary, internal cost / margin /
LOE hour breakdowns, or commercial speculation; that analysis stays in PM
working notes outside the artifact. The `Client Review Questions` and the client
sign-off checklist are the client-facing decision surfaces.

**No PMO-automation internals in the Scope body.** The Scope artifact must not
expose the internal mechanics of the PMO automation framework: hook file names
(`scope-version-guard.py`, `intent-schema-guard.py`, `repo-binding-guard.py`,
…), config or repo paths (`.pmo/project-config.yaml`, `.claude/…`,
`docs/pmo/…` internals), regression-test or self-check results, parser or
identifier-governance commentary, and the `PMO-SCOPE-*` / `PMO-INTENT-*`
error-code mechanics. Normal client-appropriate document governance stays in the
artifact — version, status, source basis, requirement traceability, open
questions, dependencies, exclusions, approval status, and the change-control
process — and substantive requirements keep their traceability identifiers
(`SCP-REQ`, `OPEN`, `SCP-GAP`, `SCP-DEP`, `WF`, `INTG`, `WBS`, …). Internal
validation results are reported to the PM in the completion report, never inside
the Scope file.

Every Scope file contains these sections, in order:

1. **Document Control** — Project, Project ID, Client, PM, Scope Version,
   Status, Date, Source Intent Version + Status, Supersedes / Approved from,
   Next Stage (`SPECIFICATION_GENERATION`).
2. **Scope Summary & Objectives** — WHAT is being delivered, derived from Intent
   Sections 1–4.
3. **Context Map** — product platforms / interfaces; user & actor model; module
   map (`MOD-*`).
4. **Source Inventory & Authority** — table of `SRC-*`: type, date, authority
   tier (Section 3), consulted (YES/NO + note).
5. **Key User and Operational Workflows** — `WF-*` (Section 14).
6. **In-Scope Requirements** — `SCP-REQ-*` grouped by module (Section 13).
7. **Explicitly Out of Scope** — `SCP-OOS-*` (carried Intent `INT-OOS-*` plus
   exclusions discovered during elicitation). "Optional / pending client
   election" items are **not** converted to exclusions unless the client elects
   out; each exclusion cites its evidence.
8. **Work Breakdown Structure** — hierarchical, product-level `WBS-*`, each
   linked to `SCP-REQ-*`. No developer task identifiers.
9. **Brand and Design Guidelines** — captured evidence + `BRAND-OPEN-*`
   (Section 15).
10. **Third-Party Integrations** — `INTG-*` register (Section 16).
11. **Data and Content Requirements** — (Section 17).
12. **Client Responsibilities** — `CLIENT-RESP-*` (Section 18).
13. **Delivery Team Responsibilities** — `DELIVERY-RESP-*` (Section 19).
14. **Constraints** — commercial, schedule, technical, operational,
    data / security / compliance, governance / IP (Intent Section 7 + contract).
15. **Commercial and Change-Control Boundaries** — (Section 21).
16. **Assumptions** — `SCP-ASM-*` (each explicitly labelled).
17. **Dependencies** — `SCP-DEP-*` (typed: client / third-party / internal /
    external / upstream-artifact).
18. **Scope Gaps** — `SCP-GAP-*` (Section 20).
19. **Open Items** — `OPEN-*` (carried from the Intent, id unchanged),
    `SCP-OPEN-*` (Scope-native) and `BRAND-OPEN-*`: ID, Blocking (YES/NO),
    Question, Why it matters, Owner, Required Before (canonical stage), Source,
    Origin (`Intent v1.0` for a carried `OPEN-*` — its id is already the Intent
    id — or `Scope` for `SCP-OPEN-*` / `BRAND-OPEN-*`).
20. **Potential Scope Expansion** — `PSE-*` (Section 23).
21. **Source Conflicts** — `SCP-CONFLICT-*` with classification.
22. **Risks** — `SCP-RISK-*`.
23. **Intent-to-Scope Traceability Matrix** — `TRACE-INT-REQ-*`, one per
    `INT-REQ-*` (Section 24).
24. **Client Review Questions** — `CRQ-*` (Section 25).
25. **Version History** — table (Section 26).
26. **Scope Validation Summary** — counts, current-gate vs future-gate blocker
    breakdown, traceability coverage %, quality-rule results, approval-readiness
    verdict.
27. **Acceptance & Sign-off** — PM checklist, client checklist, PM Decision,
    status.

Status lifecycle: `DRAFT → PM_REVIEWED → CLIENT_REVIEW → CLIENT_APPROVED`
(→ published as `scope-v1.0.md`) → `SUPERSEDED`.

---

## 13. In-Scope Requirement structure (`SCP-REQ-*`)

Every `SCP-REQ-###` records:

- **ID** — `SCP-REQ-###` (stable, never renumbered/reused).
- **Title** — short noun phrase.
- **Module** — the `MOD-###` it belongs to.
- **Statement** — plain-language WHAT (behaviour and boundary, not design).
- **Rationale** — why it is in scope; the need it meets.
- **Primary Actor / Supporting Actors**.
- **Priority** — `MUST` / `SHOULD` / `COULD` (contracted baseline features
  default to `MUST`).
- **Acceptance Criteria** — one or more testable statements (Given/When/Then or
  checklist form). At least one is mandatory.
- **Traces To** — one or more of `INT-REQ-###`, an executed-contract clause, or
  a registered `SRC-###`.
- **Related Workflows** — `WF-###`.
- **Related Open Items** — `OPEN-###` / `SCP-OPEN-###` / `BRAND-OPEN-###` / `SCP-GAP-###`.
- **Dependencies** — `SCP-DEP-###` / `INTG-###`.
- **Source Evidence**.

No field-level design, UI specifications, API contracts, data schemas or
algorithms — those belong in `specs.md`.

---

## 14. Key User and Operational Workflows (`WF-*`)

Identify the important **end-to-end** workflows that project evidence supports.
For each:

- **Workflow ID** — `WF-001`, `WF-002`, `WF-003`, ...
- **Workflow Name**
- **Primary Actor**
- **Supporting Actors**
- **Entry Condition**
- **Primary Flow** (numbered steps, business-level)
- **Important Alternate / Exception Flow**
- **Business Rules**
- **Expected Outcome**
- **Related SCP-REQ IDs**
- **Related OPEN IDs** (`OPEN-*` / `SCP-OPEN-*` / `BRAND-OPEN-*` / `SCP-GAP-*`)
- **Source Evidence**

Rules: do **not** generate workflows unsupported by evidence; do **not** turn a
workflow into developer implementation tasks — it stays a business-level
end-to-end description.

---

## 15. Brand and Design Guidelines

Capture **only available evidence** for: logo; approved colours; typography;
visual identity; imagery direction; existing design system; UI references;
accessibility requirements; RTL (right-to-left) requirements; responsive
behaviour; client-provided brand assets.

If branding information is unavailable, **do not invent it**. Create a
`BRAND-OPEN-###` item with:

- **Question**
- **Owner**
- **Required Before** — a canonical workflow stage (Section 9). Brand items that
  must be resolved before design is approved use `SPECIFICATION_GENERATION`
  (unless the gap changes scope size, then `SCOPE_BASELINE`).
- **Source / Reason**

`BRAND-OPEN-*` items are also listed in the Open Items section and counted in
the blocker breakdown.

---

## 16. Third-Party Integrations (`INTG-*`)

For **every** integration named in the evidence, capture:

- **Integration ID** — `INTG-001`, `INTG-002`, ...
- **Provider / Service**
- **Purpose**
- **Current Status** — e.g. `CONFIRMED`, `TBD`, `MIGRATION`, `OPTIONAL`.
- **Client Account Required** — YES/NO
- **Account Owner**
- **Commercial / Subscription Owner**
- **Credentials Owner**
- **Dependency** — what it blocks / is blocked by
- **Related Scope Requirements** — `SCP-REQ-###`
- **Related OPEN Items** — `OPEN-###` / `SCP-OPEN-###`
- **Source**

Rules: do **not** select an integration provider where project evidence says
`TBD`. Provider ambiguity is left as a `SCP-OPEN-*` item (`Required Before` set
by when the choice actually blocks work).

---

## 17. Data and Content Requirements

Capture, **where applicable and evidenced**: data supplied by the client;
existing data sources; catalogue / product data; migration requirements; bulk
import requirements; expected file formats; images / media; legal content;
translations; policy content; data ownership; content approval responsibility;
retention / migration obligations **only where contractually supported**.

Do **not** invent migration or data-seeding obligations. Where a data or content
need is implied but undefined, record a `SCP-GAP-*` or `SCP-OPEN-*` rather than
an assumption.

---

## 18. Client Responsibilities (`CLIENT-RESP-*`)

Include **only** responsibilities supported by evidence. Typical (where
applicable): content provision; credentials; third-party accounts;
payment-gateway merchant account; Apple / Google developer accounts; legal copy;
brand assets; feedback / approvals; translations; infrastructure ownership; test
data; business-rule clarification.

- **ID** — `CLIENT-RESP-001`, ...
- Each responsibility MUST reference **source evidence** (contract clause,
  Intent constraint/dependency, `SRC-###`).

---

## 19. Delivery Team Responsibilities (`DELIVERY-RESP-*`)

Document **only** supplier / delivery responsibilities supported by the executed
contract, SOW, validated Intent, or other authoritative evidence. Typical:
design; application development; backend development; QA; deployment support;
integration implementation; documentation; the support window.

- **ID** — `DELIVERY-RESP-001`, ...
- Each references its evidence. Do **not** convert a client responsibility into
  a delivery-team obligation (or vice versa).

---

## 20. Scope Gaps (`SCP-GAP-*`)

Every scope gap records:

- **Gap** — what cannot yet be scoped.
- **Affected Module** — `MOD-###`.
- **Related Intent Requirement** — `INT-REQ-###`.
- **Related Scope Requirement** — `SCP-REQ-###` (if any).
- **Supporting Source**.
- **Why detail is insufficient**.
- **Business / Delivery Impact**.
- **Owner**.
- **Required Before** — canonical workflow stage.
- **Recommended Resolution**.

**A Gap must not silently become an assumption.** If a gap is closed by a
client/PM decision, it is replaced by an updated `SCP-REQ` (or `SCP-ASM` only
when the decision itself is an explicit, recorded assumption).

---

## 21. Commercial and Change-Control Boundaries

Capture **only evidence-supported** terms: engagement model; sold commercial
baseline; milestone structure; client acceptance obligations; support period;
warranty / defect-support limits; excluded services; the Change Request / Change
Order mechanism; response / approval windows; timeline impact of client delay.

Do **not** create new commercial terms. State explicitly:

> New functionality that is not supported by the approved commercial baseline
> must not silently enter Scope. It is recorded as a `PSE-*` and routed through
> Change Request / Change Order, next phase, an Intent update, or rejection.

---

## 22. Open Items and stage-aware governance

The Open Items section holds three kinds of open question:

- **`OPEN-*`** — a question **carried forward from the validated Intent**. It
  keeps the **exact `OPEN-*` id** it has in `intent.md` — carrying it into Scope
  is not a rename and never re-prefixes it to `SCP-OPEN-*` (`PMO-SCOPE-015`).
  Its id must match an `OPEN` definition in `intent.md`; a retired Intent
  `OPEN-*` id is never reused for a different question.
- **`SCP-OPEN-*`** — a question **first raised during Requirement Gathering /
  Scope creation**, with no Intent origin.
- **`BRAND-OPEN-*`** — a brand / design question (Section 15).

Each row: ID, `Blocking` (YES/NO), Question, Why it matters, Owner,
`Required Before` (canonical stage — Section 9), Source, and Origin
(`Intent v1.0` for a carried `OPEN-*`, `Scope` for `SCP-OPEN-*` /
`BRAND-OPEN-*`). `SCP-GAP-*` items with `Required Before: SCOPE_BASELINE` and
`Blocking: YES` are also treated as current-gate blockers for approval.

---

## 23. Potential Scope Expansion (`PSE-*`)

Any material client-stated requirement **not** supported by the validated Intent
or the executed contract:

- is **never** added to `SCP-REQ-*` or the WBS in this stage;
- is logged as `PSE-###`: description, requesting source, why it is outside the
  current Intent/contract, a qualitative impact note (effort / cost / schedule
  direction), and a **routing recommendation** — one of `CHANGE_REQUEST`
  (Change Order process), `NEXT_PHASE`, `NEEDS_INTENT_UPDATE`, or `REJECTED`;
- is visible in the Scope document and carried forward; the PM/client decide
  disposition. Non-material or out-of-context asks are recorded briefly and
  marked `REJECTED` with a reason — never dropped silently
  (`silent_assumptions_prohibited`).

---

## 24. Intent-to-Scope Traceability Matrix

- **One `TRACE-INT-REQ-###` row for every `INT-REQ-*` in the validated Intent's
  requirements section.** Retired Intent identifiers (e.g. `INT-REQ-006`) are
  noted as gaps and need no row. A Scope draft with any `INT-REQ-*` missing from
  the matrix is **incomplete** and cannot progress to client review
  (`PMO-SCOPE-007`).
- Each row: `INT-REQ-###` → mapped `SCP-REQ-*` and/or `WBS-*` → **Coverage**
  (`FULL` / `PARTIAL` / `DEFERRED` / `OUT_OF_SCOPE`) → rationale + evidence.
- `PARTIAL`, `DEFERRED`, `OUT_OF_SCOPE` require an explicit reason and a linked
  `OPEN-*`, `SCP-OPEN-*`, `SCP-GAP-*`, `PSE-*` or `SCP-OOS-*`.
- Any `SCP-REQ-*` that does **not** trace back to an `INT-REQ-*` must trace to
  the executed contract or another registered source, or be reclassified as
  `PSE-*` (`PMO-SCOPE-012`).
- **Traceability Coverage %** = (INT-REQ rows present with an accepted
  disposition) ÷ (active INT-REQ count) × 100. It must be **100%** for
  PM/client review readiness.

---

## 25. Client Review Questions (`CRQ-*`)

A concise, **client-facing** list drawn from unresolved items that require
client input (`OPEN-*`, `SCP-OPEN-*`, `BRAND-OPEN-*`, `SCP-GAP-*`, `PSE-*`
awaiting disposition). Each:

- **Question ID** — `CRQ-###` (may reference the existing `OPEN` / `SCP-OPEN` /
  `BRAND-OPEN` / `SCP-GAP` id it derives from).
- **Question** — plain language, decision-oriented.
- **Why confirmation is needed**.
- **Affected Module** — `MOD-###`.
- **Decision Needed By** — a canonical workflow stage.

Do **not** expose internal PM commentary or commercial speculation in this
section.

---

## 26. Version History

Every Scope artifact contains:

```
## Version History

| Version | Date | Status | Change Summary | Previous Version |
|---|---|---|---|---|
```

- The initial row is `0.1`.
- Each new revision records **exactly what changed** (which `SCP-REQ` /
  workflow / register entries were added, changed, retired, and why).
- Historical Scope files are never overwritten; the table is cumulative across
  the version currently being written.

---

## 27. Pre-baseline client feedback handling

Ordinary pre-baseline refinement is **not** the post-baseline Change Request
process. Explicit process:

```
scope-v0.1
  → client feedback
  → compare each feedback item against:
       - the validated Intent
       - the current Scope draft
       - the original source evidence
  → classify the disposition
  → author scope-v0.2 incorporating the accepted dispositions
```

For each feedback item determine one disposition:

| Disposition | Meaning |
|---|---|
| `IN_SCOPE_CLARIFICATION` | Wording/detail clarified; no scope change. |
| `IN_SCOPE_CORRECTION` | Scope draft misread the evidence; corrected to match. |
| `IN_SCOPE_ENHANCEMENT` | Minor elaboration already within the Intent/contract envelope. |
| `POTENTIAL_SCOPE_EXPANSION` | Material ask beyond the Intent/contract → `PSE-*`, not incorporated. |
| `CONTRADICTION` | Conflicts with the Intent, contract or another feedback item → `SCP-CONFLICT-*` + PM decision. |
| `DUPLICATE` | Already covered by an existing `SCP-REQ` / item. |
| `NEEDS_PM_DECISION` | Cannot be dispositioned without PM input → `SCP-OPEN-*` for the PM. |

Rules: do **not** apply the post-baseline CR classification automatically to
ordinary pre-baseline refinement; **but** any material unsupported expansion
MUST be surfaced (as `PSE-*`) **before** it is incorporated — it is never folded
in silently.

---

## 28. Approval and promotion to `scope-v1.0.md`

Publish `docs/pmo/scope/scope-v1.0.md` **only** when **all** hold:

1. A specific `scope-v0.x.md` draft has `Status: CLIENT_REVIEW` and recorded,
   explicit **client** approval, plus explicit **PM** approval.
2. **No `Blocking: YES` item (`OPEN-*` / `SCP-OPEN-*` / `BRAND-OPEN-*` /
   `SCP-GAP-*`) with `Required Before: SCOPE_BASELINE` is still open**
   (`PMO-SCOPE-011`). Items at `SPECIFICATION_GENERATION` or later may remain
   open.
3. The Intent-to-Scope traceability matrix accounts for **every** `INT-REQ-*`
   (100% coverage — Section 24, `PMO-SCOPE-007`).
4. No `FR-XXX` / `NFR-XXX` identifiers appear anywhere in the artifact
   (`PMO-SCOPE-008`).
5. Commercial clearance is recorded if any `PSE-*` was accepted into scope via
   Change Request.
6. The quality validation rules (Section 31) all pass.

Then:

- Write `scope-v1.0.md` as a **new file** (never by renaming/overwriting a
  draft); Document Control records `Approved from: scope-v0.x.md`,
  `Status: CLIENT_APPROVED`.
- Write `.pmo/approvals/scope-approval.yaml` with:
  `artifact: docs/pmo/scope/scope-v1.0.md`, `version: "1.0"`,
  `decision: APPROVED`, `approved_by: <PM>`, `client_approved_by: <client>`,
  `approval_source: PM_EXPLICIT`, `approved_at: <timestamp>`
  (`PMO-SCOPE-014`).
- `scope-v1.0.md` is immutable thereafter.

---

## 29. Relationship to Specifications and Development

**Approved Scope does NOT directly authorise Development.** The correct flow is:

```
Intent v1.0 VALIDATED
  → Scope v1.0 APPROVED
    → Specifications generated
      → Specifications validated / approved under their own governance
        → Development planning
          → Development
```

- **Scope approval authorises Specification Generation only.**
- **Development is gated on approved Specifications**, not merely approved Scope.
- Do **not** generate development tasks, estimates-to-build, or a development
  plan during Requirement Gathering.
- `FR-XXX` / `NFR-XXX` are defined in `specs.md` during Specification
  Generation, never here.

---

## 30. PMO project-state updates

`.pmo/project-config.yaml` records where the workflow is. During Requirement
Gathering it is updated at **two** points, and only as set out below. Never
modify `intent.md`, the Intent approval record, `repository.*`, or any hook.

### 30.1 Draft-state update — after a Scope draft is written

Immediately after a `scope-v0.x.md` draft is successfully written (Section 11
step 14) — the first draft or any later minor revision — update
`.pmo/project-config.yaml` to record that a draft now exists for review.
Recording the draft is part of writing it; this step does **not** need a
separate explicit instruction, and it is **not** an approval — it MUST NOT
touch any approval field:

- `artifacts.scope.path` → `"docs/pmo/scope"`
- `artifacts.scope.latest_version` → the draft just written (`"0.1"`, then
  `"0.2"`, ...)
- `artifacts.scope.approved_version` → **stays `null`**
- `artifacts.scope.status` → the latest draft's Document-Control status
  (`"DRAFT_CLIENT_REVIEW"`, or `"CLIENT_FEEDBACK_RECEIVED"` / `"PM_REVIEWED"` as
  review progresses)
- `workflow.current_stage` → `"SCOPE_DRAFTED"`
- `workflow.scope.required` → **stays `true`**
- `workflow.scope.approved` → **stays `false`**

This update carries no approval semantics: `approved_version` stays `null`,
`workflow.scope.approved` stays `false`, and `workflow.current_stage` never
advances past `SCOPE_DRAFTED` on the strength of a draft.

### 30.2 Approval-state update — only after client + PM approval of scope-v1.0

Only **after** a `scope-v0.x.md` draft has recorded explicit **client** approval
**and** explicit **PM** approval, `scope-v1.0.md` has been published as a new
file (Section 28), `.pmo/approvals/scope-approval.yaml` has been written, and
**only when explicitly instructed**, update `.pmo/project-config.yaml`:

- `artifacts.scope.latest_version` → `"1.0"`
- `artifacts.scope.approved_version` → `"1.0"`
- `artifacts.scope.status` → `VALIDATED`
- `workflow.current_stage` → `SCOPE_BASELINED` (or the project's configured
  post-Scope stage token)
- `workflow.scope.approved` → `true`

Do **not** set any field in 30.2 until every Section 28 condition holds.
Creating or revising a draft never triggers a 30.2 update, and 30.2 never runs
without a published `scope-v1.0.md` and its approval record. This section
changes **no** approval rule: `scope-v1.0.md` still requires the full explicit
client + PM approval workflow of Section 28.

---

## 31. Quality validation rules

A Scope draft is quality-valid only if **all** of the following hold; the Scope
Validation Summary reports each:

1. The Context Map (Section 10) was established before any `SCP-REQ`.
2. Every `SCP-REQ-*` has ≥ 1 testable acceptance criterion and ≥ 1 trace
   (`INT-REQ` / contract clause / `SRC-*`), and belongs to exactly one `MOD-*`.
3. No orphan `SCP-REQ-*` (one with no trace and no `PSE-*` record).
4. Every `WBS-*` element links to ≥ 1 `SCP-REQ-*`; the WBS uses only `WBS`
   identifiers; there are no developer task identifiers.
5. Every `INT-REQ-*` from the validated Intent has a `TRACE-INT-REQ-*` row with
   an accepted disposition (100% coverage).
6. Every `OPEN-*` / `SCP-OPEN-*` / `BRAND-OPEN-*` / `SCP-GAP-*` has `Blocking`
   (YES/NO) and a canonical `Required Before` stage.
7. No `FR-XXX` / `NFR-XXX` identifier appears anywhere.
8. No identifier is duplicated within its owning section; no identifier was
   renumbered or reused across versions.
8a. Every carried-forward Intent question keeps its exact `OPEN-*` id (never
    re-prefixed to `SCP-OPEN-*`); every bare `OPEN-*` in the Open Items section
    matches an `OPEN` definition in `intent.md`; `SCP-OPEN-*` is used only for
    questions first raised during Requirement Gathering; no retired Intent
    `OPEN-*` id is reused (`PMO-SCOPE-015`).
9. Every `CLIENT-RESP-*`, `DELIVERY-RESP-*` and Constraint references source
   evidence.
10. No `SCP-GAP-*` has been silently converted into a `SCP-ASM-*`.
11. Every `WF-*` links to `SCP-REQ-*` and to source evidence, and describes
    business-level flow (not implementation tasks).
12. The counts in the Scope Validation Summary reconcile with the document body.
13. The Version History table is present and records what changed.
14. Scope is **evidence-driven**, not assumption-driven (Section 4,
    `PMO-SCOPE-013`).

---

## 32. Failure Conditions

`.claude/hooks/scope-version-guard.py` is the **installed deterministic
enforcement** for Scope artifacts, and its implemented `PMO-SCOPE-*` semantics
are the governance contract. The table below documents the **same 15 codes with
the same meaning** — Code, Name, Condition, Effect, Required remediation. Do
not invent a different code for a condition the hook already covers, and do not
change hook behaviour to preserve older skill numbering; this table follows the
hook.

Each code fires either on **every** `Write` / `Edit` to a `scope-v*.md` (DRAFT
included) or only at a **finalisation gate** — the draft's `Status` moves to
`PM_REVIEWED` / `APPROVED`, or a `git add` / `git commit` stages the file. The
Effect column says which.

| Code | Name | Condition | Effect | Required remediation |
|---|---|---|---|---|
| `PMO-SCOPE-001` | `INTENT_NOT_VALIDATED` | `docs/pmo/intent/intent.md` is absent; or its `Status` ≠ `VALIDATED`; or its `Intent Version` < 1.0; or `.pmo/project-config.yaml` is missing/unreadable or does not record `workflow.intent.approved: true` **and** `artifacts.intent.status: VALIDATED`. | BLOCK at a finalisation gate. (Section 2 also forbids starting Requirement Gathering at all without a validated Intent + matching PM approval record.) | Complete and validate the Intent (explicit PM approval record), and ensure project-config records it as approved + VALIDATED. |
| `PMO-SCOPE-002` | `PROJECT_IDENTITY_MISMATCH` | The Scope Document Control `Project` / `Project ID` / `Client` does not match `.pmo/project-config.yaml` (case-insensitive; blank fields on either side are skipped). | BLOCK (every edit). | Align the Scope identity fields to `.pmo/project-config.yaml` — the configuration is the authority. |
| `PMO-SCOPE-003` | `SCOPE_SCHEMA_INVALID` | At a finalisation gate: a required `## N. …` section heading is missing; a Document Control field is missing; an APPROVED Scope's `Next Stage` is not `SPECIFICATION_GENERATION` (or points at `DEVELOPMENT`); the Version History section is absent, omits the current version, has an incomplete row, or cites a Previous Version with no artifact; an Open Items record is unmanaged (missing Question / Owner / Blocking / Required Before), has a Blocking value other than `YES`/`NO`, or a `Required Before` that is not a canonical workflow stage; a developer `TASK-###` identifier appears (the WBS is product-level only). | BLOCK at a finalisation gate; DRAFT authoring continues. | Complete the section skeleton, Document Control and Version History; fully manage every Open Items record with a canonical `Required Before` stage; remove `TASK-*` identifiers; set an APPROVED Scope's `Next Stage` to `SPECIFICATION_GENERATION`. |
| `PMO-SCOPE-004` | `INVALID_SCOPE_STATUS` | The Scope `Status` is not one of `DRAFT_CLIENT_REVIEW` / `CLIENT_FEEDBACK_RECEIVED` / `PM_REVIEWED` / `APPROVED` / `SUPERSEDED`; and, at a finalisation gate, is absent. | BLOCK (every edit for the value; presence also required at a gate). | Set `Status` to an allowed value. |
| `PMO-SCOPE-005` | `VERSION_FILENAME_MISMATCH` | The version in the filename `scope-vX.Y.md` does not equal the document's `Scope Version` field. | BLOCK (every edit). | Make the filename and the `Scope Version` field agree. |
| `PMO-SCOPE-006` | `SCOPE_VERSION_OVERWRITE` | A `Write` / `Edit` targets a `scope-v*.md` that is `APPROVED` (immutable baseline), or that is historical because a higher-numbered `scope-v*.md` already exists. | BLOCK (every edit). | Issue the change as the next new version file (`scope-v0.(N+1).md`; post-baseline, a Change Request `scope-v1.1.md` / `scope-v2.0.md`). |
| `PMO-SCOPE-007` | `INTENT_TRACEABILITY_INCOMPLETE` | An active `INT-REQ-*` from `intent.md` is absent from the Intent-to-Scope Traceability section, appears in it more than once, or has no disposition (`COVERED` / `PARTIALLY_COVERED` / `OPEN` / `DEFERRED` / `EXCLUDED`). | BLOCK at a finalisation gate (client-review readiness); DRAFT authoring continues. | Give every active `INT-REQ-*` exactly one dispositioned traceability row. |
| `PMO-SCOPE-008` | `RESERVED_REQUIREMENT_ID` | A line-leading `FR-###` / `NFR-###` identifier appears anywhere in the Scope artifact. | BLOCK (every edit). | Remove it; restate the need as `SCP-REQ-*`. `FR` / `NFR` belong only in `specs.md`. |
| `PMO-SCOPE-009` | `DUPLICATE_OR_REUSED_IDENTIFIER` | A Scope identifier (any Scope namespace) is defined line-leading more than once; **or** a `SCP-REQ` id retired in an earlier version is reused for an active requirement. | BLOCK (every edit). | Define each identifier once (repeated references are fine); allocate a new id rather than reusing a retired one; never renumber to close a gap. |
| `PMO-SCOPE-010` | `INVALID_VERSION_PROGRESSION` | The first Scope file is not `scope-v0.1.md`; a skipped / decremented / reused minor; a `1.x` file before an approved `scope-v1.0.md`; `APPROVED` status on a `0.x` file. | BLOCK on create (version progression), and at a finalisation gate for `APPROVED` on a `0.x` file. | Use the correct next version: `0.1 → 0.2 → …`; approved baseline `1.0`; Change Request `1.1` / `2.0`. |
| `PMO-SCOPE-011` | `SCOPE_BASELINE_BLOCKER` | During a `scope-v1.0.md` approval attempt (`Status: APPROVED`), a `Blocking: YES` Open Items record has `Required Before` at or before `SCOPE_BASELINE` and is still open. | BLOCK approval only; DRAFT authoring **and** PM/client review continue. | Resolve the blocker(s), then re-attempt approval. Items gated at `SPECIFICATION_GENERATION` or later carry forward. |
| `PMO-SCOPE-012` | `UNCONTROLLED_SCOPE_EXPANSION` | A `PSE-*` (Potential Scope Expansion) item is marked committed / in-scope / baselined with no PM disposition (`CHANGE_REQUEST` / `NEXT_PHASE` / `NEEDS_INTENT_UPDATE` / `REJECTED` / `DEFERRED` / routing). | BLOCK at a finalisation gate; DRAFT authoring continues. | Route the `PSE-*` item (Change Request / next phase / Intent update / rejection) before it enters Scope. |
| `PMO-SCOPE-013` | `APPROVAL_REQUIRED` | `scope-v1.0` is moved to `APPROVED` without a well-formed `.pmo/approvals/scope-approval.yaml`: file absent / malformed, `artifact` ≠ `docs/pmo/scope/scope-v1.0.md`, `version` ≠ `"1.0"`, document `Scope Version` ≠ `1.0`, `decision` ≠ `APPROVED`, empty `approved_by`, `approval_source` ≠ `PM_EXPLICIT`, `client_approval` ≠ `CONFIRMED`, or empty `client_approval_reference`. | BLOCK `scope-v1.0.md` publication. | Obtain explicit PM + client approval and write a well-formed approval record. |
| `PMO-SCOPE-014` | `SCOPE_GUARD_INTERNAL_ERROR` | An unexpected exception occurred inside a controlled Scope validation (`Write` / `Edit` / `MultiEdit`) or while validating a `git` operation on a Scope artifact. | BLOCK as a precaution (fail closed). | Fix the malformed input, or the hook defect; the operation stays blocked until validation completes cleanly. |
| `PMO-SCOPE-015` | `OPEN_ID_PROVENANCE_MISMATCH` | Deterministic OPEN-identifier provenance: (a) a Scope-native `SCP-OPEN-###` Open Items record cites a carried Intent `OPEN-###` in its own record (a carried question renamed into the Scope namespace); **or** (b) a bare `OPEN-###` Open Items record matches no line-leading `OPEN` definition in `docs/pmo/intent/intent.md` (a mislabelled Scope-native question, or a reused retired Intent `OPEN` id). Skipped when `intent.md` is unreadable or defines no `OPEN`. | BLOCK (every edit). | Define a carried question under its original Intent `OPEN-###` id; use `SCP-OPEN-###` only for questions first raised in Requirement Gathering; never reuse a retired Intent `OPEN` id. |

Earlier drafts of this skill used a different `PMO-SCOPE-*` numbering (a planned
set that drifted from the code). The table above is now aligned to the
**installed** `scope-version-guard.py`; where an older meaning is still useful
as process guidance it is retained in the relevant Procedure / Section (e.g.
initial-file-collision handling is Procedure step 2 and `PMO-SCOPE-010`).

### 32.1 Deterministic-validation boundary

`scope-version-guard.py` performs **deterministic** validation only.
`PMO-SCOPE-015` detects an OPEN-identifier provenance break from mechanical
facts — a cross-reference to an Intent `OPEN-###` inside a `SCP-OPEN-###`
record, or a bare `OPEN-###` with no matching Intent definition. It **cannot**
reliably determine semantic equivalence when a carried Intent question has been
**completely rewritten** under a different identifier with **no traceable
cross-reference** to its Intent origin — two differently worded questions are
not deterministically "the same". That case is outside the hook's reach and
**MUST be detected during PM semantic Scope review**, by comparing each
`SCP-OPEN-*` against the Intent's open questions by meaning. Do **not** try to
close this gap with keyword or fuzzy-similarity matching inside the hook:
unreliable heuristics produce false blocks and false passes and are not
deterministic governance.

### 32.2 Baseline-gate behaviour (confirmation)

Unresolved `Blocking: YES` items whose `Required Before` is `SCOPE_BASELINE`
**do not stop Scope drafting or PM / client review**. They stop only
**approval / baseline promotion** to `scope-v1.0.md` (`PMO-SCOPE-011`). Worked
example — Smart Basket `scope-v0.1.md`: the four carried Intent blockers
`OPEN-002`, `OPEN-003`, `OPEN-004` and `OPEN-021` (`Blocking: YES`,
`Required Before: SCOPE_BASELINE`) may remain open while `scope-v0.1.md`
proceeds to PM and client review; they must be resolved before `scope-v1.0.md`
can be approved.

---

## 33. Guardrails — MUST NOT

- MUST NOT start without a VALIDATED Intent + matching PM approval record
  (Section 2).
- MUST NOT overwrite, delete or edit in place any existing `scope-v*.md`; every
  change is a new version (Sections 7, 32).
- MUST NOT emit `FR-XXX` / `NFR-XXX` in any Scope artifact (Sections 8, 29).
- MUST NOT create developer task identifiers; the WBS is product-level
  (Sections 8, 12 §8).
- MUST NOT silently add an unsupported client requirement to scope — route it to
  `PSE-*` (Section 23).
- MUST NOT invent brand, design, integration, migration, data-seeding, or
  commercial terms; unknowns become `BRAND-OPEN-*` / `SCP-OPEN-*` / `SCP-GAP-*`.
- MUST NOT convert a `SCP-GAP-*` into a `SCP-ASM-*`, or a client responsibility
  into a delivery-team responsibility (or vice versa).
- MUST NOT publish `scope-v1.0.md` while a `SCOPE_BASELINE` blocker is open
  (Section 28); drafting is still allowed.
- MUST NOT omit any `INT-REQ-*` from the traceability matrix (Section 24).
- MUST NOT renumber or reuse identifiers across versions (Section 8).
- MUST NOT re-prefix a carried-forward Intent question from `OPEN-*` to
  `SCP-OPEN-*` (or otherwise change its id) — a question keeps its `OPEN-*`
  identity through Scope, Specifications and Development / QA governance;
  `SCP-OPEN-*` is only for questions first raised in Requirement Gathering
  (Section 8, Section 22, `PMO-SCOPE-015`).
- MUST NOT silently resolve a source conflict — raise `SCP-CONFLICT-*` /
  `SCP-OPEN-*` / PM decision (Section 3).
- MUST NOT modify `docs/pmo/intent/intent.md`, `.pmo/approvals/intent-approval.yaml`,
  the project-init or intent skills, or existing hooks.
- MUST NOT generate `specs.md`, plan development, or begin Specification
  Generation (Section 29).
- MUST NOT set any Scope **approval** field in `.pmo/project-config.yaml`
  (`artifacts.scope.approved_version`, `artifacts.scope.status: VALIDATED`,
  `workflow.scope.approved: true`, a post-Scope `workflow.current_stage`) before
  `scope-v1.0.md` is published with a well-formed approval record (Section 30.2).
  Recording a written draft via the Section 30.1 draft-state update
  (`latest_version`, review `status`, `workflow.current_stage: SCOPE_DRAFTED`,
  with `approved_version` `null` and `workflow.scope.approved` `false`) is
  expected, not prohibited.
- MUST NOT commit or push unless explicitly asked.
- MUST NOT infer missing project information or record silent assumptions.
- MUST NOT place PMO-automation internals in the client-facing Scope body — hook
  names, config/repo paths, test or self-check results, parser logic, or
  `PMO-SCOPE-*` error-code mechanics (Section 12). Internal validation is
  reported to the PM in the completion report only.

---

## 34. Definition of done (for a Scope draft)

- The next `scope-v0.x.md` exists (first run: `scope-v0.1.md`), no prior version
  altered; Version History updated.
- The Context Map (platforms, actors, `MOD-*`, `INTG-*`, source inventory,
  Intent coverage inventory) is complete and precedes the requirements.
- Every `INT-REQ-*` appears in the traceability matrix with a coverage verdict
  (100% coverage).
- Every in-scope requirement is a `SCP-REQ-*` with the full structure
  (Section 13).
- Key workflows are captured as `WF-*` with the full field set.
- Brand/design, `INTG-*`, data & content, `CLIENT-RESP-*`, `DELIVERY-RESP-*`
  and commercial / change-control boundaries are captured from evidence, with
  unknowns as `BRAND-OPEN-*` / `SCP-OPEN-*` / `SCP-GAP-*`.
- `WBS-*` elements are product-level and link to `SCP-REQ-*`; no task IDs.
- All stage-aware items carry `Blocking` + a canonical `Required Before`;
  `SCOPE_BASELINE` blockers are listed as approval-blocking.
- All unsupported client asks are `PSE-*` with a routing recommendation.
- Source conflicts are `SCP-CONFLICT-*`; no gap has become an assumption.
- The Scope Validation Summary reports counts, blocker breakdown, traceability
  coverage %, quality-rule results and an approval-readiness verdict.
- Client Review Questions (`CRQ-*`) are generated and contain no internal
  commentary.
- Status reflects the review stage; version history is intact.
- The **PMO REQUIREMENT GATHERING RESULT** report (Section 35) is emitted.

---

## 35. Final output — PMO REQUIREMENT GATHERING RESULT

On completion of a draft (and again at approval), emit:

```
PMO REQUIREMENT GATHERING RESULT

Project:                <Project>
Scope Artifact:         <path>
Scope Version:          <version>
Scope Status:           <status>
Intent Baseline:        <Intent version / status>
Sources Analyzed:       <count>
Intent Requirements:    <count of active INT-REQ>
Scope Requirements:     <count of SCP-REQ>
Modules:                <count of MOD>
Workflows:              <count of WF>
Integrations:           <count of INTG>
Assumptions:            <count of SCP-ASM>
Dependencies:           <count of SCP-DEP>
Scope Gaps:             <count of SCP-GAP>
Open Questions:         <count of carried OPEN + Scope-native SCP-OPEN + BRAND-OPEN>
Current-Gate Blockers:  <count> (IDs)
Future-Gate Blockers:   <count> (IDs)
Explicit Exclusions:    <count of SCP-OOS>
Client Responsibilities:<count of CLIENT-RESP>
Delivery Responsibilities:<count of DELIVERY-RESP>
WBS Items:              <count of WBS elements>
Potential Scope Expansions:<count of PSE>
Traceability Coverage:  <percentage>
Validation:             PASS / BLOCKED
Next Human Gate:        PM_SCOPE_REVIEW
Next Workflow:          CLIENT_SCOPE_REVIEW
```

`Validation: BLOCKED` whenever any `PMO-SCOPE-*` condition applies or any
Section 31 quality rule fails; the report then lists the offending IDs.

---

## 36. Preserved governance — re-confirmation

The following conditions are unchanged and MUST NOT be weakened:

- **Prerequisite:** Requirement Gathering runs only against a VALIDATED Intent
  with a matching PM approval record (Section 2).
- **Initial draft:** the first output is exactly `docs/pmo/scope/scope-v0.1.md`
  (Section 6).
- **Draft versioning:** `0.1 → 0.2 → 0.3 → ...`, minor increments, no skips
  (Sections 7, 32 `PMO-SCOPE-010`).
- **Approved baseline:** the client-approved baseline is
  `docs/pmo/scope/scope-v1.0.md` (Sections 6, 28).
- **Scope draft may be generated with future/current `SCOPE_BASELINE`
  blockers** open (Section 9).
- **Scope approval may NOT occur with an unresolved current `SCOPE_BASELINE`
  blocker** (Sections 9, 28, 32 `PMO-SCOPE-011`).
- **`scope-v0.x` files are immutable history** once a newer version exists; no
  previous Scope version is ever overwritten (Sections 7, 32 `PMO-SCOPE-006`).
- **`scope-v1.0` requires an explicit PM + client approval workflow** and a
  well-formed `.pmo/approvals/scope-approval.yaml` (Sections 28, 32
  `PMO-SCOPE-014`).
- **`SCP-REQ` identifiers are stable** and never renumbered merely because
  another requirement is removed (Sections 8, 32 `PMO-SCOPE-009`).
- **OPEN identifier provenance / lifecycle identity:** a question carried
  forward from the validated Intent keeps its exact `OPEN-*` id in Scope,
  Specifications and Development / QA governance; it is never re-prefixed to
  `SCP-OPEN-*`. `SCP-OPEN-*` is only for questions first raised during
  Requirement Gathering. Retired Intent `OPEN-*` ids are never reused
  (Sections 8, 22, 32 `PMO-SCOPE-015`).
- **`FR-XXX` / `NFR-XXX` remain reserved for Specifications** (Sections 8, 29,
  32 `PMO-SCOPE-008`).
- **Every `INT-REQ` appears in the Intent-to-Scope traceability matrix**
  (Sections 24, 32 `PMO-SCOPE-007`).
- **WBS remains product-level**; Scope does not create developer task
  identifiers (Sections 8, 12 §8).
- **`POTENTIAL_SCOPE_EXPANSION`** is the only route for unsupported client asks
  (Section 23).

---

## 37. Installed control

Structural, immutability, identifier-provenance and stage-aware-blocker
enforcement for Scope artifacts is provided by the **installed**
`.claude/hooks/scope-version-guard.py` PreToolUse hook (the Scope analogue of
`.claude/hooks/intent-schema-guard.py`), which implements the `PMO-SCOPE-*`
conditions in Section 32 deterministically. This skill does not modify that
hook; its output must satisfy every rule above so the hook passes. Regression
coverage lives in `.claude/hooks/test_scope_version_guard.py`. The hook is the
authority for the `PMO-SCOPE-*` contract — if this document and the hook ever
disagree, the hook wins and this document is corrected to match it (never the
reverse).
