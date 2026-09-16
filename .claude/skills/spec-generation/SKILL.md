---
name: spec-generation
description: >-
  Convert the current PMO commercial/product basis into the canonical
  engineering and QA execution artifact docs/pmo/specs/specs.md — the single
  execution source of truth consumed by Development and QA. TWO entry paths,
  selected deterministically by whether the project has a Scope artifact
  under docs/pmo/scope/ — never by a project-config flag, and a new project
  is never required to manufacture an empty Scope for compatibility. LEGACY
  path (a Scope artifact exists): unchanged — Intent stays the contextual
  source of truth (WHY); Scope stays the commercial/product-boundary source
  of truth (WHAT committed); runs immediately after the first PM-reviewed
  Scope draft exists, SCP-REQ traceability, PMO-SPEC-001/004/015. NEW path
  (no Scope artifact — the active lifecycle for a new project): runs once
  Intent is VALIDATED with a matching PM approval AND the canonical Q&A
  register (docs/pmo/requirements/questions-and-assumptions.md) has no
  unresolved Blocking record — PMO-SPEC-021/022/023 — with traceability
  against Intent INT-REQ ids instead of Scope SCP-REQ ids ("Source
  Requirement" / "Intent → Specs Traceability"), reading Intent + Q&A
  directly, never a project-config boolean. specs.md is the EXACT
  operational behaviour Dev must build and QA must verify either way, so
  normal execution never has to reinterpret contracts, transcripts, emails,
  feedback sheets, earlier Scope versions or the Q&A register itself. The
  live path is always docs/pmo/specs/specs.md (never specs-v0.1.md /
  specs-v0.2.md); logical version lives in the Spec Version metadata and the
  Specification Change History table inside the file, plus git history and
  Feedback / CR provenance. Produces Specification Document Control, FR-XXX
  functional requirements (permanent IDs, full behavioural structure,
  Given/When/Then acceptance criteria), NFR-XXX non-functional requirements
  (evidence-supported only, no invented thresholds), BR-XXX business rules,
  system-state models, business-level error / exception behaviour,
  behavioural data requirements, INTG-XXX → FR/NFR integration mapping,
  preserved OPEN-XXX / SCP-OPEN-XXX / BRAND-OPEN-XXX / QST-XXX / ASM-XXX
  items (new spec-level questions become SPEC-OPEN-XXX), a Scope → Specs (or
  Intent → Specs) traceability matrix covering every active upstream
  requirement, and an upstream lineage table. Never adds a requirement
  absent from its upstream basis (it flags instead), never renumbers or
  reuses FR/NFR IDs, never silently resolves an OPEN item, never infers
  ACTIVE status or flips Execution Authorized automatically, and never
  modifies Intent, Scope, the Q&A register, source evidence, feedback or CR
  sources. Feedback that does not move the commercial boundary updates
  specs.md only (Spec Version bump, Feedback ID recorded); commercial-
  boundary changes and approved CRs update specs.md (+ Scope on the LEGACY
  path) plus the Change Log. A post-baseline Q&A resolution that materially
  changes approved functionality must not bypass CR governance either.
  PMO-SPEC-001 … PMO-SPEC-023 define deterministic halt behaviour;
  publishing uses only the repository configured in
  .pmo/project-config.yaml, never bypasses repo-binding-guard.py, and
  reports PUBLISH_BLOCKED_REPOSITORY_NOT_VERIFIED rather than pushing
  elsewhere. Emits a final PMO SPEC GENERATION RESULT report.
---

# Specification Generation (PMO)

## 1. Purpose and position in the PMO lifecycle

Specification Generation converts the current PMO commercial / product **Scope**
into the canonical engineering and QA execution artifact:

```
docs/pmo/specs/specs.md
```

`specs.md` is the **single execution source of truth** consumed by Development
and QA. It is the operational definition of exactly **what Development must
implement and what QA must verify**.

It sits **after** Requirement Gathering and **beside** the still-running Scope
client review (Section 3, Section 24). It is invoked once a **PM-reviewed Scope
draft** exists and re-invoked (UPDATE mode) whenever accepted feedback or an
approved Change Request changes what must be built.

`.pmo/project-config.yaml` governance still applies: `source_of_truth:
repository`, `markdown_authoritative: true`, `approved_artifacts_immutable:
true`. Specifications are a **downstream execution interpretation** of Scope —
they never become an authority over Intent or Scope.

---

## 2. Source-of-truth model — non-negotiable

| Artifact | Role | Question it answers |
|---|---|---|
| `docs/pmo/intent/intent.md` | Contextual source of truth | **WHY** — client vision, original context |
| `docs/pmo/scope/scope-vX.Y.md` | Commercial / product-boundary source of truth | **WHAT** has been committed |
| `docs/pmo/specs/specs.md` | Execution source of truth | **EXACT operational behaviour** Dev builds / QA verifies |

Consequences:

- Intent remains the contextual source of truth and is **never** overridden by
  Specs.
- Scope remains the commercial / product-boundary source of truth and is
  **never** widened, narrowed or re-statused by Specs.
- Development and QA must be able to execute normally from `specs.md` **alone** —
  without reading contracts, transcripts, emails, feedback sheets, decision
  logs or previous Scope versions.
- Therefore **every** currently-applicable implementation behaviour must be
  represented through `specs.md`. If an implementation-relevant behaviour is
  only in an upstream source, it is either brought into `specs.md` **with a
  Scope trace**, or (when Scope does not support it) **flagged** — never
  silently added (Section 6).

This table describes the **LEGACY** path (a project that already has a Scope
lineage). See Section 2a for the **NEW** (no-Scope) path's source-of-truth
model, which most new projects now use.

---

## 2a. NEW (no-Scope) lifecycle — entry contract and source-of-truth model

**Path selection is deterministic and never a flag.** A project with at
least one `docs/pmo/scope/scope-vX.Y.md` artifact is on the LEGACY path
(Section 2, unchanged in every respect). A project with **none** is on this
NEW path. Nothing in `.pmo/project-config.yaml` selects the path, and a new
project is never required to manufacture an empty Scope directory merely for
compatibility — `.claude/hooks/specs-governance-guard.py`'s
`has_legacy_scope(root)` makes this determination by listing
`docs/pmo/scope/`, nothing else.

| Artifact | Role | Question it answers |
|---|---|---|
| `docs/pmo/intent/intent.md` | Contextual **and** commercial/product-boundary source of truth | **WHY**, and **WHAT** was already confirmed at Intent validation |
| `docs/pmo/requirements/questions-and-assumptions.md` | Resolved-matters register | which remaining ambiguities/assumptions were closed, by whom, and how |
| `docs/pmo/specs/specs.md` | Execution source of truth | **EXACT operational behaviour** Dev builds / QA verifies |

There is **no mandatory Scope artifact** in this model. `specs.md` traces
directly to Intent `INT-REQ-*` (never `SCP-REQ-*`) and, where a requirement's
shape was set by a Q&A resolution rather than being already explicit in
Intent, to the resolving `QST-*` / `ASM-*` record.

**Entry preconditions — all required, checked by reading the canonical
artifacts directly (never a project-config boolean):**

1. `docs/pmo/intent/intent.md` exists with `Status: VALIDATED`.
2. A structurally valid, matching PM approval record exists at
   `.pmo/approvals/intent-approval.yaml` (identical rule to the LEGACY
   path's Scope-entry prerequisite — reused unchanged via
   `intent_approval_core.py`).
3. The Intent's project identity matches `.pmo/project-config.yaml`.
4. `docs/pmo/requirements/questions-and-assumptions.md` exists.
5. The Q&A register is structurally valid (every record: valid `Type`,
   valid `Status`, explicit `Blocking`, required fields present — see
   `requirement-gathering`'s own governance, which this stage never
   re-implements, only consults).
6. No record remains `Status: OPEN` with `Blocking: YES`.
7. `docs/pmo/sources/` remains available for ambiguity consultation, exactly
   as on the LEGACY path (Section 6).

A `DEFERRED` / `NON_BLOCKING` Q&A record does **not** block entry — its
`Specs Impact` field is exactly how that still-open decision stays
traceable inside `specs.md` (an explicit `SPEC-OPEN-*` / TBD note on the
affected FR/NFR), never a silently dropped question. Preconditions 1–6 are
enforced deterministically as `PMO-SPEC-021` (Intent), `PMO-SPEC-022`
(Q&A register missing/invalid) and `PMO-SPEC-023` (a Blocking record
remains) — see Section 26.

**Specs generation on this path never requires, checks or references:**
Scope existence, Scope approval, a Scope version, or any
`workflow.scope.*` / `artifacts.scope.*` project-config field.

---

## 3. Generation timing — parallel, not linear

Specs **must not** wait for Scope v1.0 approval. The first Specifications
artifact is generated **immediately after the first PM-reviewed Scope draft
exists**.

Canonical first cycle:

```
Scope:  scope-v0.1.md   Status: DRAFT_CLIENT_REVIEW
   ->
Specs:  specs.md        Spec Version: 0.1   Spec Status: PROVISIONAL
                        Execution Authorized: false
```

`Scope v0.1 -> specs.md v0.1` is an **intended and supported** workflow. After
initial Scope generation the PMO workflow is **no longer strictly linear**: the
Scope client-review stream and the provisional-Specs stream run in parallel,
each governed by its own artifact-specific state (Section 24).

---

## 4. Authoritative output — one canonical file

The only live execution artifact is:

```
docs/pmo/specs/specs.md
```

**Do not** create `specs-v0.1.md`, `specs-v0.2.md`, … as the normal live
artifact. Development and QA **always** read `docs/pmo/specs/specs.md`; they
must never have to work out which versioned filename is latest.

The logical version is carried by, in order of authority:

1. the **Spec Version** field in the Specification Document Control block
   (Section 7);
2. the **Specification Change History** table inside `specs.md` (Section 20);
3. git / Bitbucket commit history of `specs.md`;
4. Feedback / Change-Request provenance recorded against individual
   requirements (Section 21).

The path stays stable across every version.

---

## 5. Inputs

**Always read (INITIAL and UPDATE):**

| Input | Use |
|---|---|
| `.pmo/project-config.yaml` | project identity, repository, artifact state, workflow state (never an authorization source — Section 2a) |
| `docs/pmo/intent/intent.md` | LEGACY: contextual traceability (INT-REQ), ambiguity validation. NEW path: **primary** generation source (WHY + WHAT already confirmed). |
| current Scope artifact under `docs/pmo/scope/`, **when one exists** | LEGACY path only — **primary** generation source, the most recent PM-reviewed Scope draft. Absent entirely on the NEW path (Section 2a) — its absence is not an error. |
| `docs/pmo/requirements/questions-and-assumptions.md`, **when the project has no Scope** | NEW path only — resolved Q&A basis; required (`PMO-SPEC-022`). |
| relevant approved decisions under `docs/pmo/decisions/` where available | resolved questions that constrain behaviour |

**Also read for an UPDATE operation:**

| Input | Use |
|---|---|
| `docs/pmo/feedback/` | accepted feedback items and their classification / disposition |
| `docs/pmo/change-requests/` (equivalently `docs/pmo/cr/`) | Change Request status (APPROVED / REJECTED / PENDING) |
| existing `docs/pmo/specs/specs.md` | current FR/NFR/BR set, IDs, versions, change history to preserve |

**Do not** rely on conversation memory as authoritative project evidence. If a
needed input is missing or unreadable → `PMO-SPEC-002`, `STOP` (Section 26).

---

## 6. Initial-generation source discipline

For the **initial** `specs.md` on the **LEGACY** path (a Scope artifact exists):

- **Primary source:** the current **PM-reviewed Scope**.
- **Supporting traceability source:** the **validated Intent** (for INT-REQ
  lineage).
- **Original evidence** (contract, transcript, email, earlier proposal) may be
  **consulted only to validate ambiguity** in a Scope requirement — never as a
  primary requirement source.

**Do not silently introduce a requirement that is absent from Scope.** If
consulted evidence appears to require functionality that Scope does not
represent:

- record it as a `SPEC-OPEN-XXX` item and/or a traceability note flagged
  `SCOPE_GAP_SUSPECTED`;
- route it back to Requirement Gathering (owning workflow for a Scope defect);
- **do not** insert it into an FR as committed functionality.

For the **initial** `specs.md` on the **NEW** (no-Scope) path (Section 2a):

- **Primary source:** the **validated Intent** (`INT-REQ-*` and its already-
  confirmed detail) **plus** the resolved/deferred/non-blocking records in
  the Q&A register.
- **Original evidence** under `docs/pmo/sources/` may be **consulted only to
  validate ambiguity** — never as a primary requirement source, exactly as
  on the LEGACY path.
- **Do not silently introduce a requirement that neither Intent nor a
  resolved Q&A record supports.** If consulted evidence appears to require
  functionality neither represents, record it as `SPEC-OPEN-XXX` and route
  it back to `requirement-gathering` (a new Q&A record) — do not insert it
  into an FR as committed functionality, and do not invent a Scope defect
  report that names an artifact this path does not use.

Unsourced FR/NFR content is `PMO-SPEC-005` (Section 26) on either path.

---

## 7. Specification Document Control

`specs.md` **must** begin with a Document Control block. On the **LEGACY**
path:

```
Project:              <project.name>
Client:               <project.client>
Project ID:           <project.id>
Spec Version:         <version>            e.g. 0.1
Spec Status:          <status>             PROVISIONAL | ACTIVE
Intent Version:       <intent version>
Scope Version:        <scope version>
Generated From:       <scope artifact path, e.g. docs/pmo/scope/scope-v0.1.md>
Last Updated:         <UTC ISO-8601 timestamp>
Execution Authorized: true | false
Repository:           <repository configured in .pmo/project-config.yaml>
```

On the **NEW** (no-Scope) path (Section 2a), `Scope Version` is **omitted
entirely** — it is not required and must not be fabricated as `N/A` filler;
`Generated From` instead names the Q&A register (and/or the Intent):

```
Project:              <project.name>
Client:               <project.client>
Project ID:           <project.id>
Spec Version:         <version>            e.g. 0.1
Spec Status:          <status>             PROVISIONAL | ACTIVE
Intent Version:       <intent version>
Generated From:       docs/pmo/requirements/questions-and-assumptions.md
Last Updated:         <UTC ISO-8601 timestamp>
Execution Authorized: true | false
Repository:           <repository configured in .pmo/project-config.yaml>
```

All identity values (`Project`, `Client`, `Project ID`, `Repository`) are taken
**verbatim from `.pmo/project-config.yaml`**, never from conversation history. A
mismatch between Specification Document Control and `project-config` identity is
`PMO-SPEC-003` / `PMO-SPEC-016`.

**Field alias on both paths:** every FR/NFR's mandatory upstream-trace field
is written as `Source Scope` on the LEGACY path (carrying `SCP-REQ-*` ids) or
as `Source Requirement` on the NEW path (carrying `INT-REQ-*` and/or `QST-*`
/ `ASM-*` ids) — the same mandatory field under a path-appropriate label, not
two different schemas (Section 12).

---

## 8. Spec Status

| Status | Meaning | When |
|---|---|---|
| `PROVISIONAL` | Specs derived from a Scope that is **not yet** an approved commercial baseline | the only allowed **initial** status; while Scope is pre-baseline |
| `ACTIVE` | Specs reconciled against a **client-approved commercial Scope baseline (v1.0+)** | only after that baseline exists **and** a PM sets it |

Rules:

- **Do not infer `ACTIVE` automatically.** Publishing, exporting or updating
  `specs.md` never promotes status.
- **Do not treat publication as approval.**
- Moving `PROVISIONAL -> ACTIVE` is a deliberate PM action recorded in the
  Specification Change History with `PM Decision`.

---

## 9. Execution Authorization

`Execution Authorized: true | false` is maintained **separately** from Spec
Status and from publication.

- **Default for the initial pre-client-approval Spec: `false`.**
- Publishing `specs.md` to Bitbucket does **not** authorize Development.
- Exporting, publishing or updating Specs **must never** change this value.
- A PM **may** explicitly set `Execution Authorized: true` where organisational
  delivery policy permits Development before Scope approval; this is recorded in
  the Specification Change History with `Change Source: PM-DECISION` and a
  `PM Decision` note.
- Any automatic flip of this flag is `PMO-SPEC-009` (Section 26).

**QA analysis and test design may consume `PROVISIONAL` Specs** regardless of
`Execution Authorized`, unless the PMO workflow explicitly prohibits it.
**Development execution** is gated on `Execution Authorized: true` (or, normally,
on an approved Scope baseline).

---

## 10. Versioning

- Initial Specs generated from Scope v0.1 → **Spec Version `0.1`**.
- Pre-baseline feedback that changes Specs increments the minor:
  `0.1 -> 0.2 -> 0.3 -> 0.4 -> …`.
- When Scope reaches the **approved baseline v1.0**, Specifications are
  **reconciled against the baseline and promoted to `1.0`**.
- After baseline: `1.0 -> 1.1 -> 1.2 -> …` for each accepted change.
- A promotion or bump that skips, repeats or lowers a version, or that assigns
  `1.0` without an approved Scope baseline, is `PMO-SPEC-008`.
- **Never renumber FR / NFR identifiers during version progression**
  (Section 11).

Every version change is a row in the Specification Change History (Section 20)
and a distinct git commit of `specs.md`.

---

## 11. Functional Requirement identifiers

- Functional requirements use `FR-001`, `FR-002`, `FR-003`, … (zero-padded to
  three digits; four when the count exceeds 999).
- Identifiers are **permanent**. Never renumber an FR because another FR is
  removed, Scope changes, feedback arrives, or ordering changes.
- If an FR is **retired**, it keeps its identifier and appears with
  `Status: RETIRED` and a Change Source explaining the retirement. **Its ID is
  never reused.**
- The same rules apply to `NFR-XXX` and `BR-XXX`.
- Any renumber or ID reuse is `PMO-SPEC-006`.

---

## 12. FR structure

Every **active** FR contains at minimum the following fields (Markdown heading
`### FR-XXX — <Title>` followed by a definition list or sub-bullets):

```
ID:                       FR-XXX
Title:                    <name>
Module:                   <module, e.g. MOD-004 / "Cart, Checkout & Payments">
Actor(s):                 <actors>
Requirement:              <precise behaviour statement>
Source Scope:             <SCP-REQ IDs>
Source Intent:            <INT-REQ IDs where applicable>
Introduced In:            <Spec Version, e.g. 0.1>
Last Modified In:         <Spec Version>
Change Source:            <INITIAL_SCOPE | FDB-XXX | CR-XXX | PM-DECISION>
Priority:                 <only when Scope-supported or PM-defined>
Preconditions:            <conditions that must hold before the trigger>
Trigger:                  <the event that starts the behaviour>
Primary Behavior:         <expected behaviour on the happy path>
Business Rules:           <applicable BR-XXX and inline rules>
Validation Rules:         <input / state validation>
Alternate / Exception Behavior: <non-happy-path behaviour>
Permissions:              <what each actor may / may not do>
Inputs:                   <data / inputs consumed>
Outputs:                  <results / side effects / notifications>
Dependencies:             <other FR-XXX / SCP-REQ / platform prerequisites>
Integration References:   <INTG-XXX where applicable>
OPEN References:          <OPEN-XXX / SCP-OPEN-XXX / BRAND-OPEN-XXX / SPEC-OPEN-XXX>
Acceptance Criteria:      <objective, testable conditions — Section 13>
Status:                   ACTIVE | DEFERRED | RETIRED
```

- `DEFERRED` and `RETIRED` FRs keep the ID and the historical fields; they may
  omit behavioural detail that no longer applies but must keep `Source Scope`,
  `Introduced In`, `Last Modified In`, `Change Source` and a reason.
- `Module`, `Actor(s)`, `Source Scope` are mandatory for every active FR.
- **NEW (no-Scope) path:** write `Source Requirement` in place of
  `Source Scope`, carrying `INT-REQ-*` and/or `QST-*` / `ASM-*` ids — the
  same mandatory field under its path-appropriate label (Section 7). Do not
  write both.

---

## 13. Acceptance Criteria

- Must be **objective and testable**. Prefer **Given / When / Then**:

  ```
  Given the customer has valid items in the cart
  When the customer confirms checkout
  Then the system creates an order using the confirmed checkout details.
  ```

- Acceptance Criteria **clarify** a requirement; they **must not expand** it.
- Do not write acceptance criteria that Scope does not support.
- Each FR's Acceptance Criteria should collectively let QA derive the scenario
  set in Section 22 (positive, negative, validation, permission, exception,
  state-transition where applicable).

---

## 14. Non-Functional Requirements

- Use `NFR-001`, `NFR-002`, … for **evidence-supported** non-functional
  requirements only.
- Categories, where supported by project evidence: Performance, Security,
  Availability, Accessibility, Localization, Compatibility, Scalability,
  Privacy, Reliability, Auditability, Maintainability.
- **Do not invent NFR thresholds.** Do not create e.g. `API response time must
  be < 200 ms` unless project evidence establishes that number. Where a category
  is relevant but no threshold is evidenced, state the qualitative requirement
  and attach an `OPEN` / `SPEC-OPEN` item for the missing target.
- Each NFR carries: `ID`, `Title`, `Category`, `Requirement`, `Source Scope`,
  `Source Intent` (where applicable), `Introduced In`, `Last Modified In`,
  `Change Source`, `Acceptance Criteria` (measurable where a target exists),
  `OPEN References`, `Status`.

---

## 15. Business Rules

- Capture explicit business rules **separately** from general requirement text,
  as `BR-001`, `BR-002`, … where a stable rule identity provides value.
- Every BR **must trace to at least one FR or NFR**.
- Do **not** create generic industry rules — only rules the project evidence
  establishes.
- A BR keeps its ID permanently (Section 11).

---

## 16. System states

Where functionality has lifecycle states, define them explicitly. Do **not**
invent states. For each state model, capture — where evidence supports it:

- the **state** name;
- **entry condition(s)**;
- **permitted transitions** (to which states, on what event);
- **actor permissions** per transition;
- whether the state is **terminal / non-terminal**;
- **relevant FR IDs**.

Example shape (only if the evidence supports these states):

```
Order:  Pending -> Confirmed -> Assigned -> Out for Delivery -> Delivered
        (Cancelled reachable from Pending / Confirmed / Assigned per evidence)
```

---

## 17. Error / exception behaviour

Capture **business-level** exception handling that Development must build and QA
must verify, e.g.: invalid credentials, unavailable / out-of-stock product,
payment failure, duplicate submission, unauthorised action, integration
unavailable.

Do **not** invent technical error codes, HTTP statuses or messages unless the
requirements establish them. Describe the expected **behaviour** (what the actor
sees, what the system does, what state results).

---

## 18. Data requirements

Capture **behaviourally relevant** data definitions only. For each important
entity, capture — where supported: `field`, `purpose`, `required / optional`,
`validation`, `ownership`, `visibility`, `related FR`.

Do **not** design physical database schemas, indexes, or storage technology
unless requirements explicitly demand them.

---

## 19. Integrations, OPEN questions, and traceability

### 19.1 Integrations

- Carry the relevant integration context forward from Scope. For **every**
  integration, map `INTG-XXX -> relevant FR / NFR IDs`.
- If a provider is **TBD** in Scope, **do not** select one. Keep the behaviour
  provider-neutral and **preserve the corresponding OPEN item** on every FR/NFR
  that depends on it.

### 19.2 OPEN questions

- Preserve, unchanged: Intent-originated `OPEN-XXX`, Scope-native
  `SCP-OPEN-XXX`, and `BRAND-OPEN-XXX`. **Do not rename them** into
  specification-specific IDs.
- A genuinely new specification-level question uses `SPEC-OPEN-001`,
  `SPEC-OPEN-002`, ….
- **Never silently resolve** an OPEN item. An OPEN item is closed only by its
  owning workflow (Intent / Requirement Gathering / a recorded decision); Specs
  then reference the decision and update affected FRs with a Change Source.
- Every implementation-relevant unresolved question must stay **visible** in
  `specs.md` (a dedicated `## Open Questions` section plus `OPEN References` on
  each affected FR/NFR).

### 19.3 Traceability

**LEGACY path:** `specs.md` **must** contain a **Scope → Specs Traceability**
matrix:

```
| Scope ID | FR/NFR IDs | Coverage | Notes |
|---|---|---|---|
```

`Coverage ∈ { COVERED, PARTIALLY_COVERED, OPEN, DEFERRED, EXCLUDED }`.

- **Every active `SCP-REQ` must appear** with a coverage value. No active Scope
  requirement may disappear silently — an unrepresented active SCP-REQ with no
  disposition is `PMO-SPEC-004`.
- `PARTIALLY_COVERED` / `OPEN` rows must name the `OPEN` / `SCP-OPEN` /
  `SPEC-OPEN` item that blocks full coverage.
- Also maintain an **Intent → Scope → Specs** lineage table where it adds value
  for complete traceability (INT-REQ → SCP-REQ → FR/NFR).

**NEW (no-Scope) path:** `specs.md` **must** contain an **Intent → Specs
Traceability** matrix instead (same heading pattern, `scope`/`intent`/
`requirements` are all recognised — Section 2a):

```
| Requirement ID | FR/NFR IDs | Coverage | Notes |
|---|---|---|---|
```

- **Every active `INT-REQ` must appear** with a coverage value — the direct
  analogue of `PMO-SPEC-004` for this path, checked against `intent.md`
  instead of a Scope artifact.
- `PARTIALLY_COVERED` / `OPEN` rows name the `QST-*` / `ASM-*` /
  `SPEC-OPEN-*` item that blocks full coverage.
- A row may also cite a resolving `QST-*` / `ASM-*` id directly where a
  requirement's exact shape came from a Q&A resolution rather than being
  already explicit in Intent.

---

## 20. Specification Change History

`specs.md` **must** contain:

```
## Specification Change History

| Version | Date | Change Source | Changed IDs | Summary | PM Decision |
|---|---|---|---|---|---|
```

Example rows:

```
| 0.1 | <date> | Scope v0.1 (INITIAL_SCOPE) | FR-001–FR-0NN, NFR-001–NFR-0MM | Initial provisional specification | Generated |
| 0.2 | <date> | FDB-001 | FR-014, FR-021 | Client clarification of checkout confirmation step | Accepted |
```

Rules:

- **Never remove a previous history row.**
- One row per Spec Version.
- `Changed IDs` lists exactly the FR/NFR/BR identifiers added or modified in that
  version (a range is acceptable for the initial row).
- `Change Source` is one of `INITIAL_SCOPE`, `Scope vX.Y`, `FDB-XXX`, `CR-XXX`,
  `PM-DECISION`.

---

## 21. Feedback and Change-Request update model

### 21.1 Feedback that updates `specs.md` only

The **Feedback Classification** workflow decides disposition **first**. By
default, accepted client feedback that does **not** alter the commercial /
product boundary updates **`specs.md` only** — no new Scope version. Typical
classes: `BUG`, `CLARIFICATION`, `IN_SCOPE_CORRECTION`,
`IN_SCOPE_IMPROVEMENT`, `MISSED_SPEC_REQUIREMENT`.

Each accepted Specs update **must**:

1. increment the Spec Version (Section 10);
2. preserve all FR / NFR / BR IDs (Section 11);
3. modify **only** the affected requirements;
4. record the Feedback ID (e.g. `FDB-014`) as the `Change Source` on each
   changed requirement;
5. update `Last Modified In` on each changed requirement;
6. update `Change Source` on each changed requirement;
7. add a Specification Change History row;
8. re-run full Specs validation (Section 25).

Every feedback-driven change references a **persistent Feedback ID**, enabling
the audit chain **Feedback → Specification → Development → QA**.

### 21.2 When Scope must also change

Scope **must** also be updated (via Requirement Gathering) when feedback changes
any of: the committed product boundary, a commercial commitment, an explicitly
approved capability, an exclusion, a client / delivery responsibility, a
contracted integration obligation, or a material acceptance boundary.
**Feedback Classification decides this** — Spec Generation must **not**
independently make commercial-scope decisions.

### 21.3 Change Requests

- Potentially out-of-scope feedback **must not** be inserted into active Specs
  as committed functionality. It stays **pending** until the CR workflow
  resolves it.
- **CR APPROVED** → update **Scope** *and* `specs.md`; record `Change Source:
  CR-XXX` on affected requirements and in the Change History.
- **CR REJECTED** → **do not** add the requested functionality to active Specs.
  Optionally record a `RETIRED` / `DEFERRED` note or a `SPEC-OPEN` closure
  reference for audit.

---

## 22. QA consumption contract

QA must be able to generate test cases **directly from `specs.md`**. Every FR
should carry enough detail to derive:

- a **positive** scenario;
- a **negative** scenario;
- a **validation** scenario;
- a **permission** scenario (where applicable);
- an **exception** scenario;
- a **state-transition** scenario (where applicable).

Do **not** embed complete QA test suites inside `specs.md`. Specs define
**expected behaviour**; the QA skill generates tests from them.

---

## 23. Development consumption contract

- Development agents use `specs.md` as the implementation requirement source and
  must **not** be required to reinterpret Scope documents or client
  communications during normal execution.
- If `specs.md` contains an unresolved `OPEN` / `SCP-OPEN` / `BRAND-OPEN` /
  `SPEC-OPEN` item that affects implementation, the Development agent **must
  not invent the answer** — it reports the blocking requirement and stops on
  that unit of work.
- Development execution additionally respects `Execution Authorized` (Section 9).

---

## 24. Project state and the parallel workflow

After initial `specs.md` generation, record **artifact-specific** state in
`.pmo/project-config.yaml` **without disturbing the concurrent Scope review
state**. Expected shape:

```yaml
artifacts:
  specifications:
    path: "docs/pmo/specs/specs.md"
    latest_version: "0.1"
    status: "PROVISIONAL"
    derived_from_scope_version: "0.1"
    execution_authorized: false
```

- **Do not** move `workflow.current_stage` out of
  `SCOPE_READY_FOR_CLIENT_REVIEW` merely because provisional Specs were
  generated.
- **Do not** change `workflow.scope.*`, `artifacts.scope.*`,
  `workflow.intent.*`, or any approval field.
- Permitted concurrent state (intentional):

  ```
  Scope: v0.1  DRAFT_CLIENT_REVIEW  client_review PENDING
  AND
  Specs: v0.1  PROVISIONAL          execution_authorized false
  ```

Artifact-specific states govern each stream independently.

---

## 25. Mandatory phased generation control

Every run is ordered phases. A phase failure **stops** the run at that phase;
later phases do not execute and no artifact is presented as usable.

### Phase 0 — Resolve & read (read-only)
Resolve mode (`INITIAL` if no `specs.md` exists, else `UPDATE`). Read Section 5
inputs. Open every source **read-only** for the whole run; keep the exact
`.pmo/project-config.yaml` text for the Phase 5 no-collateral-change check.

### Phase 1 — Pre-generation validation
First determine the path (Section 2a): **LEGACY** if `docs/pmo/scope/`
contains at least one `scope-vX.Y.md`, else **NEW**. Never a project-config
flag.

**LEGACY path:**
- `PMO-SPEC-001` — a current Scope artifact exists under `docs/pmo/scope/` and
  is at least **PM-reviewed** (`workflow.scope.pm_review: COMPLETE` or an
  equivalent recorded signal). A pre-PM-review Scope does not authorise Specs.
- `PMO-SPEC-002` — Intent and `project-config` are present and readable; for an
  UPDATE, existing `specs.md`, feedback and CR sources are readable.
- `PMO-SPEC-003` — Scope Document Control identity matches `project-config`
  (`project.id` / `project.name` / `project.client`).
- Determine target Spec Version (Section 10) and Spec Status (Section 8;
  `PROVISIONAL` unless an approved Scope baseline exists **and** a PM has set
  `ACTIVE`).

**NEW (no-Scope) path (Section 2a):**
- `PMO-SPEC-021` — canonical Intent VALIDATED + matching PM approval +
  identity match (read directly, never a project-config boolean).
- `PMO-SPEC-022` — the canonical Q&A register exists and is structurally
  valid.
- `PMO-SPEC-023` — no Q&A record remains `OPEN` with `Blocking: YES`.
- `PMO-SPEC-002` / `PMO-SPEC-003` apply identically (input readability,
  Specification identity match).
- Spec Status is `PROVISIONAL` for every initial NEW-path baseline; the
  `ACTIVE` / Version `1.0` promotion tied to an approved Scope baseline
  (Section 8, Section 10) is a LEGACY-path-only concept — promoting a
  NEW-path baseline past `PROVISIONAL` is Change-Request-governance
  territory, not addressed by this phase.

### Phase 2 — Build the specification model
FRs (Section 12), NFRs (Section 14), BRs (Section 15), system states
(Section 16), error / exception behaviour (Section 17), data requirements
(Section 18), integration map (Section 19.1), OPEN carry-forward (Section 19.2).
LEGACY: primary source = PM-reviewed Scope, Intent for lineage. NEW: primary
source = validated Intent + resolved Q&A. Original evidence only to validate
ambiguity either way (Section 6).

### Phase 3 — Coverage & consistency validation
- `PMO-SPEC-004` — every **active** upstream requirement (`SCP-REQ` on
  LEGACY, `INT-REQ` on NEW) appears in the traceability matrix with a
  coverage value; nothing dropped silently.
- `PMO-SPEC-005` — every FR / NFR traces to an upstream ID (and/or CR /
  PM-DECISION / a resolved `QST-*` / `ASM-*`); no requirement is introduced
  that its upstream basis does not support (otherwise `SPEC-OPEN` +
  `SCOPE_GAP_SUSPECTED` / a new Q&A record + route back to the owning
  workflow; do not embed it).
- `PMO-SPEC-006` — FR / NFR / BR IDs are permanent: no renumber, no reuse, no
  re-prefix vs the existing `specs.md`.
- `PMO-SPEC-007` — no `OPEN` / `SCP-OPEN` / `BRAND-OPEN` item is silently
  resolved, renamed or dropped; all implementation-relevant ones remain visible.
- `PMO-SPEC-008` — version progression is legal (Section 10); status is not
  auto-inferred (Section 8).
- `PMO-SPEC-009` — `Execution Authorized` is unchanged unless an explicit
  PM-DECISION says otherwise; publication / export / update never flips it.

### Phase 4 — Write the canonical artifact
Write / overwrite `docs/pmo/specs/specs.md` (the **only** path — Section 4).
Update the Specification Document Control block and append the Specification
Change History row(s). Never touch Intent, Scope, evidence, feedback or CR
sources (Section 27).

### Phase 5 — Record artifact state
Write only the `artifacts.specifications.*` block in `.pmo/project-config.yaml`
(Section 24). Verify no other `project-config` key changed as a side effect.

### Phase 6 — Publish eligibility (separate from generation)
Specs generation may succeed locally even when publishing cannot. Publishing
uses **only** the repository configured in `.pmo/project-config.yaml`, must not
bypass `repo-binding-guard.py`, and must not fall back to any other repository
(Section 28).

### Phase 7 — Report
Emit **PMO SPEC GENERATION RESULT** (Section 31). Do not commit or push unless
explicitly asked.

---

## 26. Failure conditions

Deterministic halt behaviour. `BLOCK` = do not produce or present `specs.md` as
usable; report and route.

| Code | Name | Condition | Remediation |
|---|---|---|---|
| `PMO-SPEC-001` | `SCOPE_NOT_READY` | No current Scope artifact under `docs/pmo/scope/`, or it is not yet PM-reviewed. | Complete Requirement Gathering + PM semantic review; re-run. |
| `PMO-SPEC-002` | `INPUT_MISSING` | A mandatory input (Intent, `project-config`, or — for UPDATE — existing `specs.md` / feedback / CR sources) is missing or unreadable. | Supply / repair the input; re-run. |
| `PMO-SPEC-003` | `PROJECT_IDENTITY_MISMATCH` | Scope Document Control identity ≠ `.pmo/project-config.yaml`. | Align identity in the owning workflow (not here); re-run. |
| `PMO-SPEC-004` | `SCOPE_COVERAGE_GAP` | An active `SCP-REQ` is not represented in the Scope → Specs matrix, or has no coverage disposition. | Add the FR/NFR coverage or an explicit `DEFERRED` / `EXCLUDED` disposition traced to a decision. |
| `PMO-SPEC-005` | `UNSOURCED_REQUIREMENT` | An FR / NFR (or acceptance criterion / business rule) has no trace to Scope / Intent / CR / PM-DECISION, or adds functionality Scope does not support. | Remove it, or raise `SPEC-OPEN` + route the suspected Scope gap to Requirement Gathering. |
| `PMO-SPEC-006` | `IDENTIFIER_INTEGRITY_VIOLATION` | An FR / NFR / BR ID was renumbered, reused, re-prefixed, or a retired ID was recycled. | Restore permanent IDs; a removed requirement becomes `RETIRED`, never deleted. |
| `PMO-SPEC-007` | `OPEN_ITEM_SILENTLY_RESOLVED` | An `OPEN` / `SCP-OPEN` / `BRAND-OPEN` item was resolved, renamed, hidden or dropped without an owning-workflow decision. | Reinstate the item; close it only via its owning workflow + a recorded decision. |
| `PMO-SPEC-008` | `VERSION_OR_STATUS_VIOLATION` | Illegal version progression (skip / repeat / regress, or `1.0` without an approved Scope baseline), or `ACTIVE` inferred automatically. | Set the correct next version; keep `PROVISIONAL` until a PM sets `ACTIVE` against a v1.0+ baseline. |
| `PMO-SPEC-009` | `EXECUTION_AUTH_AUTO_CHANGE` | `Execution Authorized` changed as a side effect of generating, updating, exporting or publishing. | Restore the prior value; change it only on an explicit PM-DECISION row. |
| `PMO-SPEC-010` | `SPEC_INTERNAL_ERROR` | Unexpected exception during a controlled step. | Fail closed — never present a partially-generated `specs.md`; fix and re-run. |
| `PMO-SPEC-021` | `INTENT_NOT_READY` | **NEW (no-Scope) path only.** The canonical Intent is absent, not VALIDATED, lacks a matching PM approval record, or its identity does not match project-config. | Complete Intent validation + PM approval first (Section 2a); re-run. |
| `PMO-SPEC-022` | `QA_REGISTER_NOT_READY` | **NEW path only.** No canonical Q&A register at `docs/pmo/requirements/questions-and-assumptions.md`, or it is structurally invalid. | Run `requirement-gathering` first, or fix the register's structural defect; re-run. |
| `PMO-SPEC-023` | `QA_BLOCKING_ITEM_OPEN` | **NEW path only.** At least one Q&A record remains `Status: OPEN` with `Blocking: YES`. | Resolve the blocking item(s) via `requirement-gathering`'s governed record-update flow; re-run. |

These three codes are installed identically in
`.claude/hooks/specs-governance-guard.py` (`validate_new_lifecycle_readiness`,
delegating to `qa_register_core.validate_new_path_readiness`) and never fire
on the LEGACY path; `PMO-SPEC-001` never fires on the NEW path. Path
selection is `has_legacy_scope(root)` — Scope-artifact presence, checked
directly, never a project-config flag (Section 2a).

**Routing outcome.** When upstream content looks wrong (a Scope contradiction, a
mislabelled status, an OPEN item the evidence clearly answers, an identifier
collision), do not "fix" it here — return:

```
SPEC_REQUIRES_SOURCE_CORRECTION
```

naming the specific issue (section, identifier, quoted text) and the owning
workflow (Requirement Gathering for a Scope defect; the Intent stage for an
Intent defect; the Change Request process for a post-baseline change; PM
semantic review for an interpretation call).

**Publish outcome (not a generation halt).** If the configured Bitbucket
repository cannot be verified, generation may still succeed locally and the
publish step reports:

```
PUBLISH_BLOCKED_REPOSITORY_NOT_VERIFIED
```

---

## 27. No source modification

Spec Generation **must not** modify:

- the validated Intent;
- any existing Scope artifact;
- the Q&A register (`docs/pmo/requirements/questions-and-assumptions.md`) —
  read it, never write it; a discovered gap routes back to
  `requirement-gathering` as a new record, exactly as a Scope gap routes
  back to Requirement Gathering on the LEGACY path;
- source evidence (contract, transcript, email, proposal, decision records);
- feedback source files;
- Change-Request source files;
- existing skills or hooks;
- approval records under `.pmo/approvals/`;
- `.pmo/project-config.yaml` beyond the `artifacts.specifications.*` block
  (Section 24).

The only persistent writes a run makes are: `docs/pmo/specs/specs.md` and the
`artifacts.specifications.*` block of `project-config`. It does not commit or
push unless explicitly asked.

If upstream content appears incorrect → `SPEC_REQUIRES_SOURCE_CORRECTION`,
route it back, `STOP`.

---

## 28. Bitbucket publishing

- After successful specification validation, `specs.md` is **eligible** for
  repository publishing — publishing is a **separate, explicit** action, never
  automatic on generation.
- Publishing uses **only** the repository configured in
  `.pmo/project-config.yaml` (`repository.*`). **Do not** infer the repository
  from conversation history.
- **Do not bypass `repo-binding-guard.py`.**
- If the configured repository cannot be verified, report
  `PUBLISH_BLOCKED_REPOSITORY_NOT_VERIFIED`. **Do not** push to any other
  repository as a fallback.
- Publication does not change Spec Status, `Execution Authorized`, or any Scope
  / Intent state.

---

## 29. Guardrails — MUST NOT

- MUST NOT introduce a requirement, acceptance criterion, business rule, NFR
  threshold, system state, error code or data field that the Scope (or an
  approved CR / PM-DECISION) does not support — flag it instead (Sections 6,
  14, 16, 17).
- MUST NOT renumber, reuse or re-prefix an FR / NFR / BR identifier
  (Section 11).
- MUST NOT silently resolve, rename, hide or drop an `OPEN` / `SCP-OPEN` /
  `BRAND-OPEN` item (Section 19.2).
- MUST NOT infer `ACTIVE` status, or set Spec Version `1.0`, without an approved
  Scope baseline and a PM decision (Sections 8, 10).
- MUST NOT change `Execution Authorized` automatically from generating,
  updating, exporting or publishing (Section 9).
- MUST NOT make commercial / product-boundary decisions — that is Feedback
  Classification / Requirement Gathering / the CR workflow (Section 21).
- MUST NOT insert pending or rejected CR functionality into active Specs
  (Section 21.3).
- MUST NOT create versioned `specs-vX.Y.md` files as the live execution artifact
  (Section 4).
- MUST NOT modify Intent, Scope, source evidence, feedback / CR sources,
  existing skills, existing hooks, approval records, or `project-config` beyond
  `artifacts.specifications.*` (Section 27).
- MUST NOT move `workflow.current_stage` out of
  `SCOPE_READY_FOR_CLIENT_REVIEW` because provisional Specs exist (Section 24).
- MUST NOT publish to, or fall back to, any repository other than the one
  configured in `project-config` (Section 28).
- MUST NOT rely on conversation memory as authoritative evidence (Section 5).
- MUST NOT authorise NEW-path entry from a project-config boolean — always
  re-read the canonical Intent, approval record and Q&A register directly
  (Section 2a).
- MUST NOT require, check, or fabricate a Scope artifact/version on the NEW
  (no-Scope) path (Section 2a).
- MUST NOT let a post-baseline Q&A resolution bypass Change Request
  governance merely because it happens to close a `QST-*` / `ASM-*` record —
  a resolution that materially changes an already-approved Specs baseline
  still requires CR governance, exactly as an equivalent post-baseline Scope
  change would (Section 21.3).
- MUST NOT commit or push unless explicitly asked.

---

## 30. Definition of done

- `docs/pmo/specs/specs.md` exists at the canonical path with a complete
  Specification Document Control block (Section 7), Spec Status `PROVISIONAL`
  (unless a PM set `ACTIVE` against a v1.0+ baseline), and
  `Execution Authorized: false` (unless an explicit PM-DECISION set it true).
- Every active `SCP-REQ` is represented in the Scope → Specs Traceability matrix
  with a coverage value; no active Scope requirement dropped silently.
- Every FR / NFR traces to Scope (and Intent / CR / PM-DECISION where relevant);
  no unsourced functionality.
- FR / NFR / BR identifiers are permanent; retired items retained with
  `Status: RETIRED`.
- All implementation-relevant `OPEN` / `SCP-OPEN` / `BRAND-OPEN` /
  `SPEC-OPEN` items are visible in `specs.md`; none silently resolved.
- Each FR carries enough detail for QA to derive positive / negative /
  validation / permission / exception / state-transition scenarios.
- The Specification Change History has a row for this version; no prior row
  removed.
- `.pmo/project-config.yaml` has an `artifacts.specifications.*` block matching
  the artifact; no other `project-config` key, and no Intent / Scope / approval
  state, changed.
- Intent, Scope, evidence, feedback and CR sources are byte-unchanged.
- The **PMO SPEC GENERATION RESULT** report (Section 31) is emitted.
- Validation `PASS`; on any `PMO-SPEC-*` condition, `BLOCKED` with the code and
  route named.

---

## 31. Final output — PMO SPEC GENERATION RESULT

On completion (or on a `STOP`, with the relevant fields filled and the failure
code named), emit:

```
PMO SPEC GENERATION RESULT

Project:                   <project name / id>
Specs Artifact:            docs/pmo/specs/specs.md
Spec Version:              <version>
Spec Status:               PROVISIONAL | ACTIVE
Execution Authorized:      true | false
Intent Baseline:           <intent version>
Scope Baseline:            <scope version / status>
Functional Requirements:   <count>
Non-Functional Requirements: <count>
Business Rules:            <count>
OPEN Items:                <count>   (OPEN + SCP-OPEN + BRAND-OPEN + SPEC-OPEN)
Scope Requirements:        <count of active SCP-REQ>
Scope Traceability:        <covered>/<total>   (COVERED + PARTIALLY_COVERED counted per policy)
Feedback Sources Applied:  <count>
CR Sources Applied:        <count>
Validation:                PASS | BLOCKED (<PMO-SPEC-0XX>: <reason>)
Repository:                <repository configured in .pmo/project-config.yaml>
Publish Eligibility:       READY | BLOCKED
Publish Result:            NOT_ATTEMPTED | PUBLISHED | BLOCKED (PUBLISH_BLOCKED_REPOSITORY_NOT_VERIFIED)
```

`Validation: PASS` only when every Phase 1 / Phase 3 check passed and Sections
27 and 24 held (no source or collateral `project-config` change). `Validation:
BLOCKED` names the offending `PMO-SPEC-*` code; a source problem is additionally
reported as `SPEC_REQUIRES_SOURCE_CORRECTION` with the routing note.
