---
name: artifact-export
description: >-
  Convert an authoritative PMO Markdown artifact (Intent, Scope of Work, Change
  Request, Feedback / Review report, Requirement / Specification summary,
  project handover / completion artifact, or a PMO governance report intended
  for external distribution) into a professional stakeholder- or client-facing
  document (DOCX, and optionally PDF) under docs/pmo/exports/, while keeping the
  Markdown artifact as the single source of truth. Export is a
  presentation / distribution action only: it never adds, removes, renumbers,
  resolves, reinterprets, re-words or re-statuses substantive content, and it
  never changes PMO state (no approval, no version bump). If the source looks
  substantively wrong it STOPs with EXPORT_REQUIRES_SOURCE_CORRECTION and routes
  the issue back to the owning PMO workflow. Records a SHA-256 of the exact
  source and an entry in docs/pmo/exports/export-manifest.json for every
  export. PMO-EXPORT-001 … PMO-EXPORT-010 failure conditions define
  deterministic halt behaviour. Validation runs in two mandatory phases —
  pre-export and post-export — and because this project has no PostToolUse
  registration for the export guard, the skill invokes
  .claude/hooks/artifact-export-guard.py directly after generation; a generated
  document is a valid deliverable only when both PRE_EXPORT_VALIDATION and
  POST_EXPORT_VALIDATION return PASS.
---

# Artifact Export (PMO)

## 1. Purpose and position in the PMO lifecycle

Artifact Export sits **beside** the PMO authoring stages (Intent Validation,
Requirement Gathering, Specification Generation, Change Request, Feedback,
Handover), not inside them. It is invoked whenever an already-authored PMO
Markdown artifact needs to be handed to a **person outside the authoring
system** — a client, a client's legal/commercial team, an executive sponsor, a
partner, or an auditor — in a document format they can read, comment on and
sign.

It produces a **derived** deliverable. The Markdown artifact under `docs/pmo/`
remains the **only** authoritative record. The exported DOCX/PDF is a faithful
presentation of a specific Markdown version, tied to it by a recorded hash.

The exporter's contract in one line: **presentation may change; meaning may
not.** If meaning would have to change to produce a sensible document, the
source is wrong and the export stops.

Supported artifact categories (the skill is artifact-type-driven, not
project-specific):

| `Artifact Type` | Typical source | Human label used in the export |
|---|---|---|
| `INTENT` | `docs/pmo/intent/intent.md` | Project Intent |
| `SCOPE` | `docs/pmo/scope/scope-vX.Y.md` | Scope of Work |
| `CHANGE_REQUEST` | `docs/pmo/cr/cr-*.md` | Change Request |
| `FEEDBACK` | `docs/pmo/feedback/*.md` | Review Report |
| `SPEC_SUMMARY` | `docs/pmo/specs/*summary*.md` | Requirement / Specification Summary |
| `HANDOVER` | `docs/pmo/*handover*.md` / completion artifact | Project Handover |
| `GOVERNANCE_REPORT` | any PMO report marked for external distribution | (the report's own title) |

Any other PMO Markdown artifact explicitly nominated by the caller is also
in-scope; treat an unrecognised type as `GOVERNANCE_REPORT` and use the
document's own H1 as the label.

`.pmo/project-config.yaml` governance still applies: `source_of_truth:
repository`, `markdown_authoritative: true`, `docx_export_only: true`,
`approved_artifacts_immutable: true`.

---

## 2. Source of truth — non-negotiable

The input Markdown file is authoritative. The exporter **must never**:

- add a new requirement, workflow, dependency, assumption, exclusion, risk,
  responsibility, integration, open question or expansion item;
- remove any of the above;
- resolve, answer, close or hide an OPEN / blocking question;
- change a commercial commitment (price, milestones, timeline, support window,
  payment terms, change-control terms, currency, IP terms);
- change an exclusion or an out-of-scope statement;
- change, renumber or re-prefix any requirement or register identifier;
- alter a status, an approval field, a decision, or a version number;
- alter a client or delivery-team responsibility;
- reinterpret, re-scope or "tidy up" an assumption;
- silently correct scope, wording, or an apparent error.

**If substantive content appears wrong** (a contradiction, a mislabelled
status, a broken commitment, an identifier collision, an OPEN item that the
evidence clearly answers, an exclusion that contradicts an in-scope
requirement, a count that does not reconcile) — **STOP**.

Return:

```
EXPORT_REQUIRES_SOURCE_CORRECTION
```

State the specific source issue (section, identifier, quoted text), name the
PMO workflow that owns the fix (Requirement Gathering for a Scope defect, the
Intent stage for an Intent defect, the Change Request process for a
post-baseline change, PM semantic review for an interpretation call, …), and
hand it back. **Do not edit the source during export.** The source file is
opened read-only for the entire run.

---

## 3. Inputs

The caller supplies, or the skill resolves and echoes back for confirmation:

| Input | Notes |
|---|---|
| `project` | Project name / id. Cross-checked against `.pmo/project-config.yaml`. |
| `source` | Path to the authoritative Markdown artifact. |
| `artifact_type` | One of Section 1's types. |
| `version` | The artifact version (e.g. `0.1`, `1.0`, `2.3`). Cross-checked against the document's own version field and its filename. |
| `audience` | `CLIENT` \| `STAKEHOLDER` \| `EXECUTIVE` \| `INTERNAL`. Drives Section 4's redaction rules. |
| `output` | `DOCX` \| `PDF` \| `DOCX+PDF`. Default `DOCX`. |
| `branding` (optional) | A named, approved brand-asset set. Omitted ⇒ neutral professional style (Section 5). |
| `regenerate` (optional) | `true` to deliberately overwrite an existing export at the same path (Section 16 / PMO-EXPORT-009). |

Example:

```
Source:        docs/pmo/scope/scope-v0.1.md
Artifact Type: SCOPE
Version:       0.1
Audience:      CLIENT
Output:        DOCX
```

If the source artifact cannot be **reliably** identified — path missing, more
than one candidate, the file is empty, the filename version and the document
version disagree, or the artifact type does not match the document's structure
— **STOP** (`PMO-EXPORT-001` or `PMO-EXPORT-003`). Do not guess.

---

## 4. Client-facing presentation rules

`audience` governs redaction. **Redaction removes only presentation of internal
automation mechanics — never substantive project content.** The Markdown
source is never modified; redaction is applied to an in-memory / scratchpad
intermediate copy that is then rendered.

### 4.1 For `CLIENT`, `STAKEHOLDER`, `EXECUTIVE`

**Omit** (these must not appear in the exported document):

- `.claude/…` paths, `.pmo/…` paths, hook file names, any `*-guard.py`,
  `scope-version-guard`, `intent-schema-guard`, `repo-binding-guard`;
- Python / script references, `import …`, `py_compile`, `ast.parse`,
  `pytest` / `test_*` / "regression suite" / "regression tests";
- parser-behaviour or identifier-governance commentary
  ("line-leading", "provenance regex", "the parser", "namespace translation");
- PMO internal error / condition codes (`PMO-SCOPE-0xx`, `PMO-INTENT-0xx`,
  `PMO-EXPORT-0xx`) and "self-check" notes;
- internal test results, internal validation implementation notes,
  repository-control / repo-binding mechanics (`repository.verified`,
  "artifact publishing"), draft-state-pointer mechanics;
- Claude-specific instructions, skill names, `SKILL.md`, "skill Section N";
- internal PM commentary, margin / LOE / hour breakdowns, cost or effort
  estimates, internal-only review checklists.

**Retain** (client-relevant governance — keep it in the document):

- project name, client name, document version, document status, date,
  Document Control table;
- every scope / requirement item and its wording;
- assumptions, dependencies, scope gaps, OPEN questions;
- exclusions / out-of-scope statements;
- client and delivery-team responsibilities;
- commercial and change-control terms as stated in the source;
- acceptance / sign-off status and checklist;
- version history;
- source basis / list of documents relied on (as named in the source);
- the identifiers in Section 7.

**How to redact safely.** A block may be omitted **only** when the source has
**explicitly classified it as internal** — e.g. a line, blockquote or
sub-section the author marked `Internal note`, `PMO internal`, `Not for
client`, or an equivalent unambiguous label. If internal-automation text
appears in the source **without** such a marker, that is a source defect:
raise `PMO-EXPORT-006`, `STOP`, and route it back (the source must be cleaned
in its owning workflow, not silently stripped here). A well-formed
client-facing PMO artifact should already contain no such text.

### 4.2 For `INTERNAL`

No redaction. Export the document as-is (presentational transforms only).
`PMO-EXPORT-006` does not apply.

---

## 5. Document design

Produce a **professional business document**, not a decorated one.

Include, where the output format supports it:

- a cover / title page: document title, project name, client name, artifact
  type (human label), version, status, date;
- a **status banner** on the cover and in the running footer when the source
  status is a draft/review status (Section 10) — e.g. `DRAFT — FOR CLIENT
  REVIEW`;
- a Document Control table mirroring the source's Document Control section
  (values verbatim);
- a Table of Contents built from the document headings (Section 12);
- a clear heading hierarchy (H1 → the document title; H2 → the source's `##`
  sections; H3 → `###`; etc.);
- readable tables with a header row, sensible column widths, no clipped text,
  and wrapping enabled;
- page numbers and a footer (document title · version · status · page x of y);
- one consistent typographic system: one body font, one heading font (may be
  the same family), consistent sizes, consistent paragraph spacing;
- sensible whitespace and a page break before each top-level section for
  substantial artifacts.

Do **not**:

- add decorative elements that reduce readability (heavy rules, coloured
  blocks behind body text, watermarks other than a plain `DRAFT` mark);
- invent client branding, a client logo, a client colour palette, or a
  client letterhead;
- change the reading order or merge/split the source's sections.

**Branding.** If `branding` names an **approved, explicitly-selected** asset
set that exists in the repository, apply it (logo on the cover and footer,
palette for headings and table headers, approved fonts). If no branding is
supplied or approved, use a **neutral professional style** (e.g. a dark-grey
heading colour, black body text, a thin accent rule under H1/H2, a system
serif or humanist sans body). Never fabricate brand assets.

---

## 6. Content parity — presentational transforms only

Every substantive section and item in the exported document must correspond
1:1 to the authoritative Markdown. The exporter makes **presentational**
transformations only.

**Allowed**

| Source | Export |
|---|---|
| Markdown heading | DOCX/PDF heading of the matching level |
| Markdown table | formatted table, same rows and columns, same cell text |
| bullet / numbered list | Word list of the same kind and nesting |
| `- [ ]` / `- [x]` checkbox | a visual unchecked / checked box (or `☐` / `☑`) with the same label |
| long or bare URL | a hyperlink (display text may be shortened; target unchanged) |
| inline code / backticks | a monospace run, same text |
| block explicitly classified "internal" | omitted from `CLIENT` / `STAKEHOLDER` / `EXECUTIVE` output (Section 4) |
| soft line wraps inside a paragraph | reflowed |
| a fenced code block that only exists to carry an internal report | omitted from non-`INTERNAL` output if explicitly internal; otherwise kept verbatim |

**Not allowed**

| Source | Must not become |
|---|---|
| a requirement's wording | a differently-worded commitment |
| an OPEN / blocking question | resolved, answered, hidden, or moved out of view |
| an out-of-scope / exclusion item | removed, softened, or turned into an in-scope item |
| an assumption | a requirement, a decision, or a guarantee |
| a `PARTIALLY_COVERED` / draft disposition | `COVERED` / `FINAL` |
| a count, total or identifier list | a different count or list |
| a status or version | any other value |

If producing a readable document would require any "not allowed"
transformation, that is a source problem → Section 2 → `STOP`.

---

## 7. Identifier preservation

Preserve **exactly** every substantive identifier that appears in the
client-facing content, verbatim and un-renumbered, including where applicable:

```
INT-REQ   INT-OOS   OPEN
SCP-REQ   SCP-ASM   SCP-DEP   SCP-GAP   SCP-OPEN   SCP-OOS
BRAND-OPEN   WF   INTG   CLIENT-RESP   DELIVERY-RESP   WBS
MOD   TRACE-INT-REQ   PSE   CRQ   SCP-RISK   SCP-CONFLICT
FR   NFR   CR   DEC
```

Rules:

- never renumber, re-prefix, zero-pad differently, or "tidy" an identifier;
- keep retired/skipped-number notes as written (they are meaningful);
- an identifier that the source shows only inside an explicitly-internal block
  is dropped with that block; every other identifier is retained;
- after generation, the **set and count** of each identifier family in the
  export must equal the set and count in the source's non-internal content
  (Section 18 / `PMO-EXPORT-005`).

---

## 8. Artifact status awareness

The exporter must present the source status **accurately and unchanged**.

- A source status of `DRAFT_CLIENT_REVIEW` (or `DRAFT`, `PM_REVIEWED`,
  `CLIENT_FEEDBACK_RECEIVED`, `IN_REVIEW`, …) **must not** be exported as
  `APPROVED`, `FINAL`, `SIGNED`, `BASELINED` or `ISSUED`.
- For any draft / review status, the exported document must be **visibly
  identified** as a draft — a cover banner and a footer tag such as
  `DRAFT — FOR CLIENT REVIEW` (or `DRAFT — FOR STAKEHOLDER REVIEW`,
  `DRAFT — NOT APPROVED`) — worded so it does **not** change the underlying
  PMO status value, which is still shown verbatim in the Document Control
  table.
- For `APPROVED` / `VALIDATED` sources, the exported document preserves that
  status; the exporter **never infers** approval and never adds a signature
  block that implies one that the source does not record.
- The Document Control table always shows the source's exact `Status` string.

---

## 9. OPEN / blocking items in exports

- Do **not** hide unresolved OPEN questions to make the document look cleaner.
  If the source keeps an OPEN item in client-facing content, it stays in the
  export, in a place where the client can see that their input is needed
  (typically the Open Questions section and, where the source has one, the
  Client Review Questions section).
- Future-gate / blocking items may be **presented** in client-friendly
  language, but their **meaning must not change**. A field like
  `Required Before: SCOPE_BASELINE` may be shown as a governance/status field,
  or rendered with a plain-language gloss that the source itself provides
  (e.g. "before this Scope is approved as the baseline"); it must not be
  removed, re-labelled to a different gate, or made to look optional.
- Blocking items keep their `Blocking: YES` marker.
- Do not expose internal gate mechanics beyond what the source already
  presents.

---

## 10. Draft / review presentation wording

Map the source status to a cover/footer banner (the Document Control table
still shows the raw value):

| Source status | Banner |
|---|---|
| `DRAFT`, `DRAFT_CLIENT_REVIEW` | `DRAFT — FOR CLIENT REVIEW` |
| `PM_REVIEWED` (client not yet reviewing) | `DRAFT — FOR CLIENT REVIEW` |
| `CLIENT_FEEDBACK_RECEIVED` | `DRAFT — UNDER REVISION` |
| `APPROVED` / `VALIDATED` / `BASELINED` | *(no draft banner)* |
| `SUPERSEDED` | `SUPERSEDED — SEE LATER VERSION` |

For `STAKEHOLDER` / `EXECUTIVE` audiences substitute "STAKEHOLDER" for
"CLIENT" in the banner.

---

## 11. Table of contents

- Generate a usable Table of Contents from the document's headings (H2/H3,
  optionally H4).
- Prefer a **live TOC field** (updates in Word) for DOCX; a generated static
  list is acceptable if a field cannot be produced, but it must be built from
  the actual headings.
- Do **not** invent, rename, reorder or merge section names. TOC entries are
  the source headings verbatim (a leading section number in the source
  heading is kept).
- Omit from the TOC only the cover page and the TOC itself.

---

## 12. Output location and naming

Exports are written under:

```
docs/pmo/exports/
```

with an artifact-type sub-directory:

```
docs/pmo/exports/intent/
docs/pmo/exports/scope/
docs/pmo/exports/change-request/
docs/pmo/exports/feedback/
docs/pmo/exports/spec-summary/
docs/pmo/exports/handover/
docs/pmo/exports/governance/
```

**Filename** — project-neutral, human, versioned:

```
<Project-Name-Kebab>-<Artifact-Label-Kebab>-v<version>.<ext>
```

- `Project-Name-Kebab`: the project name from `.pmo/project-config.yaml`,
  spaces → `-`, punctuation stripped (e.g. `Smart Basket` → `Smart-Basket`).
- `Artifact-Label-Kebab`: `Intent`, `Scope-of-Work`, `Change-Request`,
  `Review-Report`, `Requirement-Specification-Summary`, `Project-Handover`,
  or the governance report's own title kebab-cased.
- `version`: exactly the source version (Section 15).

Example (Smart Basket Scope v0.1):

```
docs/pmo/exports/scope/Smart-Basket-Scope-of-Work-v0.1.docx
```

**Collision.** Do not overwrite an existing export silently. If a file already
exists at the target path:

1. compute the source hash (Section 13);
2. look it up in the export manifest (Section 16) for the same
   `(artifact_type, audience, export_format, export_path)`;
3. if the manifest shows the **same `source_hash`** and the existing file is
   intact — the export is already current: report it, regenerate nothing
   unless `regenerate: true`;
4. if the source hash **differs** (source changed) and `regenerate` is not
   set — `STOP` with `PMO-EXPORT-009`; the caller must confirm regeneration or
   bump the version;
5. if `regenerate: true` — overwrite, and update the manifest record in place.

Never write a `-v0.2` (or any other) filename from a `-v0.1` source
(Section 15).

---

## 13. Source hash

Before rendering, compute the **SHA-256 of the exact bytes** of the
authoritative Markdown source and record it in the manifest. This is the
deterministic link between a delivered document and the Markdown version that
produced it. Re-read and re-hash immediately before writing the output so a
mid-run source change is detected (`PMO-EXPORT-005`).

Illustrative:

```bash
shasum -a 256 docs/pmo/scope/scope-v0.1.md
```

---

## 14. DOCX generation

- Use a **reliable, structured** document-generation method available in the
  environment. Prefer, in order:
  1. **`python-docx`** (`python3 -c "import docx"` to check) — build the
     document programmatically: `Document()`, `add_heading(text, level)`,
     `add_paragraph`, `add_table(rows, cols)` with a table style, `Styles`
     for body/heading fonts, a `section.footer` paragraph carrying a `PAGE`
     field for page numbers, and a page break (`add_page_break()`) before
     each top-level section.
  2. **`pandoc`** (`command -v pandoc`) — run it on a **sanitised intermediate
     Markdown file written to the scratchpad** (never on the source), e.g.
     `pandoc <intermediate>.md -o <out>.docx --toc --reference-doc=<style>.docx`.
     The intermediate is the source with presentational transforms and (for
     non-`INTERNAL` audiences) explicitly-internal blocks removed; the source
     file itself stays byte-unchanged.
- The output must be a real, **editable** `.docx`: editable text, editable
  tables, proper Word heading styles, working pagination, usable hyperlinks,
  clean margins (≈ 2.0–2.5 cm), no clipped or overflowing text.
- **Never rasterize.** No screenshot-to-document, no image-of-a-page, no
  "print to PNG then embed". A table must be a Word table, not a picture of
  one.
- If no structured method is available: `STOP` with `PMO-EXPORT-007` and state
  what the environment is missing (e.g. "install `python-docx` or `pandoc`").

---

## 15. PDF generation

- Produce a PDF only when `output` is `PDF` or `DOCX+PDF`, or when a workflow
  explicitly requires both.
- Prefer converting the generated **DOCX** to PDF (e.g.
  `soffice --headless --convert-to pdf <file>.docx`), so the PDF and DOCX are
  visually identical; alternatively render the sanitised intermediate Markdown
  to PDF with a structured engine (pandoc + a LaTeX/`weasyprint`/`wkhtmltopdf`
  backend). Never rasterize page-by-page.
- The PDF is a **distribution** format. Markdown remains authoritative; the
  DOCX remains the editable client document where one was generated.
- Name it the same as the DOCX with a `.pdf` extension, in the same
  directory.

---

## 16. Export manifest

For **every successful export**, create or update:

```
docs/pmo/exports/export-manifest.json
```

Structure:

```json
{
  "schema_version": "1.0",
  "exports": [
    {
      "project_id": "SMART-BASKET",
      "source_artifact": "docs/pmo/scope/scope-v0.1.md",
      "source_version": "0.1",
      "source_status": "DRAFT_CLIENT_REVIEW",
      "source_hash": "sha256:<64 hex>",
      "artifact_type": "SCOPE",
      "audience": "CLIENT",
      "export_format": "DOCX",
      "export_path": "docs/pmo/exports/scope/Smart-Basket-Scope-of-Work-v0.1.docx",
      "generated_at": "2026-09-11T00:00:00Z",
      "generated_by": "PMO / Muneeb",
      "substantive_content_changed": false
    }
  ]
}
```

Rules:

- append one record per export (one per format — a `DOCX+PDF` run adds two
  records);
- if a record with the same `(source_artifact, artifact_type, audience,
  export_format, export_path)` already exists, **update it in place** (new
  hash, new timestamp) rather than duplicating;
- `generated_by` is a name/role (`project.pm` from `.pmo/project-config.yaml`,
  or a caller-supplied operator label) — **never** a token, password, API key
  or other secret, and no personal contact details beyond a name/role;
- `substantive_content_changed` is always `false`; if it would ever be `true`,
  the run must already have stopped under Section 2;
- `generated_at` is UTC ISO-8601;
- the manifest is machine-readable JSON — validate that it parses after
  writing (`PMO-EXPORT-008`).

The manifest lives under `docs/pmo/exports/` (a distribution directory) and is
not a governance artifact; it records evidence of what was distributed and
from which source version.

---

## 17. Versioning

- The export filename version **must equal** the source artifact version — the
  value in the document's version field, which must also match the source
  filename (`scope-v0.1.md` → version `0.1`).
- A `-v0.1` source must never produce a `-v0.2` (or any other version) export.
- Any version disagreement — filename vs document field vs caller-supplied
  `version` — is `PMO-EXPORT-003`: `BLOCK`, report the three values, do not
  export.

---

## 18. Client-review Scope export (draft, not approved)

A Scope with `Status: DRAFT_CLIENT_REVIEW` **may** be exported for the client
when **all** of:

1. PM semantic review of that version is complete
   (`.pmo/project-config.yaml` shows `workflow.scope.pm_review: COMPLETE` and
   `workflow.current_stage` indicates the Scope is ready for client review, or
   an equivalent recorded signal);
2. the workflow indicates the artifact is ready for client review;
3. the source passes its stage's governance validation — i.e. the Scope
   governance guard would **not** block the current file. A governance BLOCK on
   the source is `PMO-EXPORT-002`: do not export a source its own governance
   rejects.

The Scope does **not** need to be `APPROVED` to produce a client-review
export. Producing an export **never** creates or implies Scope approval, never
writes `scope-approval.yaml`, never publishes `scope-v1.0.md`, and never
changes `workflow.scope.approved`.

The same principle applies to other artifact types: a `DRAFT` / `IN_REVIEW`
Intent, Change Request or report may be exported for review when its owning
workflow says it is ready and its governance validation passes; the export
changes no state.

---

## 19. Approved / validated artifact export

When the source status is `APPROVED` / `VALIDATED` / `BASELINED`:

- the exported document preserves that status verbatim;
- no draft banner is applied;
- a sign-off / acceptance section present in the source is rendered as-is
  (including any recorded approver names and dates) — the exporter adds none
  that the source does not contain;
- the exporter still **never infers** approval, and still records
  `substantive_content_changed: false`.

---

## 20. Mandatory phased export control

Every export runs as **ordered phases**. A phase failure **stops** the run at
that phase — later phases do not execute, and no document is presented as a
deliverable. This project's Claude Code configuration has **no `PostToolUse`
registration** for `artifact-export-guard.py`; the skill therefore **must
invoke the guard directly** in Phase 1 and Phase 4 (Section 27). Do **not**
assume any hook runs automatically after generation.

### Phase 0 — Resolve and read (read-only)

1. **Resolve inputs** (Section 3): project, artifact type, source path, source
   version, source status, audience, requested output format, requested output
   path. Echo them back. If the source cannot be reliably identified →
   `PMO-EXPORT-001`, `STOP`.
2. Open the source Markdown **read-only** for the whole run. Load
   `.pmo/project-config.yaml` and **keep its exact text** as
   `project_config_before` (used in Phase 4).

### Phase 1 — Pre-export validation (must PASS before any generation)

3. **Compute the source SHA-256** of the exact source bytes (Section 13) and
   record it as `source_hash_pre`. Capture the guard's source-state snapshot
   (`capture_source_state`) for the Phase 4 comparison.
4. **Run the deterministic guard in its pre-export mode** (Section 27) —
   `pre_export_check(source, export_path, audience, root)` — enforcing
   `PMO-EXPORT-001` (source exists), `PMO-EXPORT-002` (project / workflow state
   authorises this audience; approval is **not** required for a
   `DRAFT_CLIENT_REVIEW` client export), `PMO-EXPORT-003` (source-filename,
   source-metadata and export-filename versions all agree), `PMO-EXPORT-004`
   (project identity matches `.pmo/project-config.yaml`), and that the export
   path is under `docs/pmo/exports/`.
5. **Substantive-integrity scan of the source** (Section 2): contradictions,
   status/version sanity, identifier collisions, count reconciliation,
   OPEN-vs-evidence sanity, exclusion-vs-inclusion sanity. Any real defect →
   `EXPORT_REQUIRES_SOURCE_CORRECTION` (+ `PMO-EXPORT-005` framing), name the
   owning workflow, `STOP`.
6. **Collision check** (Section 12): if the target path already exists and this
   is not an authorised same-version `regenerate` → `PMO-EXPORT-009`, `STOP`.

   If any Phase 1 check fails: **`PRE_EXPORT_VALIDATION = FAIL`**, report the
   `PMO-EXPORT-*` code (or `EXPORT_REQUIRES_SOURCE_CORRECTION`), and `STOP`.
   **Do not generate output.** Otherwise `PRE_EXPORT_VALIDATION = PASS`.

### Phase 2 — Document generation

7. **Build the sanitised intermediate** (Sections 4, 6) in the scratchpad —
   the source file is never written. For a non-`INTERNAL` audience, drop only
   explicitly-internal-classified blocks; unmarked internal-automation text in
   the source is a source defect → `PMO-EXPORT-006`, `STOP`, route back.
8. **Generate the presentation artifact** — DOCX (Section 14), then PDF if
   requested (Section 15). Editable OpenXML, structured, never rasterised.
   Failure → `PMO-EXPORT-007`, `STOP`.
9. Generation **must not** modify the source Markdown and **must not** change
   any PMO workflow / approval state.

### Phase 3 — Manifest

10. **Create / update** `docs/pmo/exports/export-manifest.json` (Section 16)
    from the **actual** source and generated-export information: real
    `source_hash` (equal to `source_hash_pre`), real `export_path`, real
    `generated_at`, `substantive_content_changed: false`.

### Phase 4 — Direct post-export validation (must PASS to deliver)

11. **Invoke `artifact-export-guard.py` directly** (Section 27) — module mode,
    **not** the stdin hook path (after generation the export file exists, so a
    replayed `Write` payload would always return `PMO-EXPORT-009`). Run
    `post_export_validation(source, export_path, root, audience,
    pre_state=<Phase 1 snapshot>, allowed_missing=<identifiers deliberately
    redacted for this audience>)` **and** `validate_pmo_state_unchanged(
    project_config_before, <current .pmo/project-config.yaml text>)`.

    Together these must verify **all** of:
    - source SHA-256 **unchanged** vs `source_hash_pre` (`PMO-EXPORT-005`);
    - the output file **exists** and is non-empty (`PMO-EXPORT-007`);
    - the DOCX package is **structurally valid** OpenXML (`PMO-EXPORT-007`);
    - a `CLIENT` / `STAKEHOLDER` / `EXECUTIVE` export contains **no prohibited
      internal PMO content** (`PMO-EXPORT-006`);
    - **governed identifiers reconcile** between source and export
      (`PMO-EXPORT-005`);
    - `export-manifest.json` is **valid JSON** with a complete record
      (`PMO-EXPORT-008`);
    - the manifest `source_hash` **matches the actual current source hash**
      (`PMO-EXPORT-008`);
    - `substantive_content_changed` is **exactly `false`** (`PMO-EXPORT-008`);
    - **PMO project state is unchanged** — `workflow.current_stage`,
      `workflow.intent.approved`, `workflow.scope.approved`,
      `artifacts.intent.latest_version`, `artifacts.scope.latest_version`,
      `artifacts.scope.approved_version`, `artifacts.specifications.status`
      (`PMO-EXPORT-005`).

12. Each call returns `None` on pass or a `Decision` (`.code`, `.message`) on
    the first failure. If **any** returns a `Decision`:
    **`POST_EXPORT_VALIDATION = FAIL`** — report the export as
    **`EXPORT_VALIDATION_FAILED`** with the `PMO-EXPORT-*` code, and **do not
    present the document as a valid client deliverable.** Do **not** modify
    source content to make validation pass (Section 2). Otherwise
    `POST_EXPORT_VALIDATION = PASS`.

### Phase 5 — Report

13. **Emit the final result** (Section 26). Success requires **both**
    `PRE_EXPORT_VALIDATION = PASS` and `POST_EXPORT_VALIDATION = PASS`
    (Section 28). Do not touch PMO state (Section 23). Do not commit or push
    unless explicitly asked.

---

## 21. Output validation

These checks are the **Phase 4** battery (Section 20). This project has **no
`PostToolUse` registration** for the export guard, so the skill runs them
itself by invoking `artifact-export-guard.py` directly (Section 27) — chiefly
`post_export_validation(...)` plus `validate_pmo_state_unchanged(...)`. After
generation, verify **all** of:

- the output file exists at the expected path and is non-empty;
- it opens / parses successfully where validation tooling allows (a DOCX is a
  valid zip with `word/document.xml`; a PDF has a `%PDF` header and an `%%EOF`);
- the export **filename version** matches the source version;
- the project identity (name / client) in the document matches
  `.pmo/project-config.yaml` and the source;
- the **artifact type / label** matches the requested type;
- **identifier reconciliation**: for every family in Section 7, the set and
  count in the export equal the set and count in the source's non-internal
  content — no additions, no omissions, **no renumbering** (special attention
  to `FR` / `NFR` / `SCP-*` — a renumber here is a hard fail);
- every **OPEN / blocking item** that the source presents to the client is
  present in the export;
- **no internal leak** in a `CLIENT` / `STAKEHOLDER` / `EXECUTIVE` export:
  a scan of the rendered text finds none of the Section 4.1 patterns
  (`.claude`, `.pmo/…`, `*-guard.py`, `PMO-SCOPE-`, `PMO-INTENT-`,
  `PMO-EXPORT-`, `SKILL.md`, `import `, `py_compile`, `pytest`, "regression",
  "parser", "repository.verified", Claude-specific instructions, …);
- the **status** shown equals the source status; a draft source carries the
  draft banner; an approved source does not;
- headings and their order match the source (allowing the added cover/TOC);
- the **source Markdown is byte-unchanged** (hash equals the pre-export hash);
- the source hash is recorded and the **export manifest** is updated and
  parses.

Any failure → `BLOCK` with the matching failure code; do not deliver a
document that fails validation.

---

## 22. Failure conditions

Deterministic halt behaviour. `BLOCK` = do not produce or deliver the export;
report and route.

| Code | Name | Condition | Effect | Required remediation |
|---|---|---|---|---|
| `PMO-EXPORT-001` | `SOURCE_NOT_FOUND` | The source path is missing, empty, unreadable, ambiguous (multiple candidates), or not a Markdown file. | BLOCK — do not export. | Supply an exact, existing source path; disambiguate. |
| `PMO-EXPORT-002` | `SOURCE_NOT_READY` | The artifact's owning workflow does not indicate it is ready for this audience (e.g. Scope PM semantic review not complete), or the source would be blocked by its own stage governance validation. | BLOCK. | Complete the owning workflow step (PM review, governance fixes); re-attempt when the workflow marks it ready. |
| `PMO-EXPORT-003` | `VERSION_MISMATCH` | The filename version, the document's version field, and the caller-supplied `version` do not all agree; or the requested export filename version differs from the source version. | BLOCK. | Reconcile the version in the source and the request; never rename the export to a different version. |
| `PMO-EXPORT-004` | `PROJECT_IDENTITY_MISMATCH` | The project / client / project-id in the source's Document Control does not match `.pmo/project-config.yaml`. | BLOCK. | Align the source's identity to `.pmo/project-config.yaml` in the owning workflow (not here), then re-export. |
| `PMO-EXPORT-005` | `SUBSTANTIVE_CONTENT_DRIFT` | The would-be export differs from the source in meaning: an added/removed/renumbered identifier, a changed count, a reworded commitment, a resolved OPEN item, a removed exclusion, an altered status/version, or the source changed mid-run. | BLOCK — return `EXPORT_REQUIRES_SOURCE_CORRECTION`. | Fix the source in its owning PMO workflow, or fix the exporter transform that introduced the drift; never "correct" the source during export. |
| `PMO-EXPORT-006` | `INTERNAL_CONTENT_LEAK` | Internal PMO-automation text (hook names, `.claude`/`.pmo` paths, script/parser/test/error-code mechanics, Claude-specific instructions) is present in a `CLIENT`/`STAKEHOLDER`/`EXECUTIVE` export, or is present in the source without an explicit "internal" classification. | BLOCK. | If the source carries unmarked internal text, clean it in the owning workflow and mark any genuinely internal notes as internal; then re-export. |
| `PMO-EXPORT-007` | `OUTPUT_GENERATION_FAILED` | No structured document-generation method is available, or generation produced a corrupt / rasterised / non-editable file, or clipped/overflowing content. | BLOCK. | Install / enable a structured generator (`python-docx`, `pandoc`, `soffice`); regenerate as editable, non-rasterised output. |
| `PMO-EXPORT-008` | `MANIFEST_VALIDATION_FAILED` | `docs/pmo/exports/export-manifest.json` cannot be written, does not parse as JSON, or is missing a required field for the new record. | BLOCK the export as "recorded" — do not report success. | Repair the manifest JSON structure; re-write the record with all required fields. |
| `PMO-EXPORT-009` | `EXISTING_EXPORT_COLLISION` | An export already exists at the target path, the source hash differs from the manifest record, and `regenerate: true` was not supplied. | BLOCK. | Confirm regeneration (`regenerate: true`) to overwrite, or bump the source version so a new filename is used. |
| `PMO-EXPORT-010` | `EXPORT_INTERNAL_ERROR` | An unexpected exception during a controlled export step. | BLOCK (fail closed). | Fix the malformed input or the tooling defect; re-run. Never deliver a partially-generated document. |

**Aggregate outcomes.** When **Phase 1** fails the skill reports
`PRE_EXPORT_VALIDATION = FAIL` with the code above and stops before
generation. When **Phase 4** fails it reports **`EXPORT_VALIDATION_FAILED`**
with the code above. `EXPORT_VALIDATION_FAILED` is a skill-level outcome label,
not an additional `PMO-EXPORT-*` code — the underlying `PMO-EXPORT-*` condition
is always named. A document that reaches either state is never presented as a
client deliverable, and the source is never edited to clear the failure
(Sections 2, 28).

---

## 23. PMO state — export changes nothing

Generating an export **must not** change:

- Scope approval, Intent approval, or any approval record;
- Scope version or Intent version;
- Specifications state;
- `workflow.scope.approved`, `workflow.intent.approved`,
  `artifacts.*.status`, `artifacts.*.approved_version`, or
  `workflow.current_stage`;
- `.pmo/approvals/*`;
- the source Markdown artifact (byte-unchanged), any other PMO artifact, or
  any existing skill or hook.

Export generation is a **distribution / presentation** action. The only
persistent writes it makes are: the export file(s) under `docs/pmo/exports/`
and the `export-manifest.json` entry. It does not commit or push unless
explicitly asked.

Optionally, a caller may separately record in `.pmo/project-config.yaml` that
an export was produced (e.g. `artifacts.scope.last_export`) — that is a
**caller-driven state note**, outside this skill, and still carries no
approval or version semantics.

---

## 24. Guardrails — MUST NOT

- MUST NOT add, remove, renumber, re-prefix or reinterpret any substantive
  item or identifier (Sections 2, 6, 7).
- MUST NOT resolve, answer or hide an OPEN / blocking question (Sections 2, 9).
- MUST NOT change a status, version, approval field, commercial term,
  exclusion, or responsibility (Sections 2, 8, 19).
- MUST NOT infer or imply approval, sign-off, or finality the source does not
  record (Sections 8, 19).
- MUST NOT modify the source Markdown, any other PMO artifact, any approval
  record, `.pmo/project-config.yaml` (beyond an optional caller-driven export
  note), any existing skill, or any hook (Sections 2, 23).
- MUST NOT leak internal PMO-automation mechanics into a client / stakeholder
  / executive document (Section 4).
- MUST NOT rasterize the document or deliver a non-editable / image-based file
  (Section 14).
- MUST NOT invent client branding or brand assets (Section 5).
- MUST NOT overwrite an existing export silently, or write an export whose
  filename version differs from the source version (Sections 12, 17).
- MUST NOT deliver a document that fails Section 21 validation.
- MUST NOT commit or push unless explicitly asked.
- MUST NOT "fix" a source defect during export — `STOP` and route it back
  (Section 2).

---

## 25. Definition of done

- The requested export file(s) exist under `docs/pmo/exports/<type>/` with the
  correct project-neutral, version-matched name.
- The document is a structured, editable business document: cover page,
  Document Control table, TOC from real headings, heading hierarchy, readable
  tables, page numbers, footer, consistent typography; draft banner iff the
  source status is a draft/review status.
- Every substantive section, item and identifier in the source's client-facing
  content is present, verbatim, un-renumbered; every count reconciles; every
  client-relevant OPEN item is visible.
- For a client / stakeholder / executive export: zero internal-automation
  leakage.
- The source Markdown is byte-unchanged; its SHA-256 is identical before
  Phase 1 and after Phase 4, and is recorded in the manifest.
- `docs/pmo/exports/export-manifest.json` has a valid record for each export
  with `substantive_content_changed: false`.
- No PMO state changed (Section 23).
- **`PRE_EXPORT_VALIDATION = PASS` and `POST_EXPORT_VALIDATION = PASS`**, both
  obtained by invoking `artifact-export-guard.py` directly (Sections 20, 27,
  28). A generated DOCX without both is **not** a success.
- The **PMO ARTIFACT EXPORT RESULT** report (Section 26) is emitted.

---

## 26. Final output — PMO ARTIFACT EXPORT RESULT

On completion (or on a `STOP`, with the relevant fields filled and the failure
code named), emit:

```
PMO ARTIFACT EXPORT RESULT

Project:                   <project name / id>
Artifact Type:             <INTENT | SCOPE | CHANGE_REQUEST | FEEDBACK | SPEC_SUMMARY | HANDOVER | GOVERNANCE_REPORT>
Source:                    <path to the authoritative Markdown>
Source Version:            <version>
Source Status:             <exact status string from the source>
Source Hash:               sha256:<64 hex>
Audience:                  <CLIENT | STAKEHOLDER | EXECUTIVE | INTERNAL>
Export Format:             <DOCX | PDF | DOCX+PDF>
Export Path:               <path(s) under docs/pmo/exports/>
Source Hash (pre):         sha256:<64 hex>
Source Hash (post):        sha256:<64 hex>   (MUST equal pre)
Pre-Export Validation:     PASS | FAIL (<PMO-EXPORT-0XX>: <reason>)
Post-Export Validation:    PASS | FAIL (<PMO-EXPORT-0XX>: <reason>)
Internal Content Leakage:  NONE | FOUND (<where>)
Substantive Content Drift: NONE | FOUND (<what>)
Source File Modified:      NO
PMO State Unchanged:       YES
Manifest:                  docs/pmo/exports/export-manifest.json
Validation:                PASS | BLOCKED (<PMO-EXPORT-0XX>: <reason>)
```

`Validation: PASS` only when **both** `Pre-Export Validation` and `Post-Export
Validation` are `PASS` and `Source Hash (post)` equals `Source Hash (pre)`
(Section 28). `Validation: BLOCKED` whenever any `PMO-EXPORT-*` condition
applies or any Section 21 check fails; the report then names the offending
code(s) and, for a Phase 4 failure, the outcome label
**`EXPORT_VALIDATION_FAILED`**. On a source problem, the report is accompanied
by `EXPORT_REQUIRES_SOURCE_CORRECTION` and the routing note from Section 2.

---

## 27. Direct guard invocation contract (no PostToolUse)

`artifact-export-guard.py` is registered in `.claude/settings.json` as a
**`PreToolUse`** hook only (`Write` / `Edit` / `Bash`). There is **no
`PostToolUse` registration** in this project, so nothing validates a generated
export automatically. The skill **must** invoke the guard itself, in **Phase 1**
and **Phase 4** (Section 20).

### What the script actually implements

The script has **no command-line argument parser** — no `argparse`, no
`sys.argv` handling. **Do not invent flags** such as `--validate`, `--pre` or
`--post`. Its two supported invocation modes are:

**A. Stdin-JSON hook mode** — `python3
"$CLAUDE_PROJECT_DIR/.claude/hooks/artifact-export-guard.py"` with a Claude
Code PreToolUse payload (`{"tool_name", "tool_input", "cwd"}`) on stdin. It
prints a deny JSON object on stdout when it objects, nothing otherwise, and
**always exits `0`**. This mode covers only the pre-write checks (export path
under root, existing-file collision, manifest-JSON structure). **It is not
usable for post-export validation**: after generation the export file exists,
so a replayed `Write` payload always returns `PMO-EXPORT-009`. Phase 4 does not
use this mode.

**B. Module-import mode** — load the file as a module and call its public
functions. This is the contract used for Phase 1 and Phase 4:

```python
import importlib.util, pathlib
_p = pathlib.Path(".claude/hooks/artifact-export-guard.py").resolve()
_s = importlib.util.spec_from_file_location("artifact_export_guard", _p)
guard = importlib.util.module_from_spec(_s); _s.loader.exec_module(guard)

root   = guard.locate_project_root(".")
source = "docs/pmo/scope/scope-v0.1.md"
export = "docs/pmo/exports/scope/Smart-Basket-Scope-of-Work-v0.1.docx"
aud    = "CLIENT"

# ---- Phase 1: before any generation ----
cfg_before = open(f"{root}/.pmo/project-config.yaml").read()
pre_state  = guard.capture_source_state(f"{root}/{source}")   # dict incl. sha256
src_hash   = guard.calculate_sha256(f"{root}/{source}")       # source_hash_pre
d = guard.pre_export_check(source, export, aud, root)
if d is not None:
    raise SystemExit(f"PRE_EXPORT_VALIDATION = FAIL  {d.code}: {d.message}")
# PRE_EXPORT_VALIDATION = PASS  -> proceed to generation + manifest

# ---- Phase 4: after generation + manifest ----
d = guard.post_export_validation(source, export, root, audience=aud,
                                 pre_state=pre_state, allowed_missing=set())
if d is None:
    d = guard.validate_pmo_state_unchanged(
        cfg_before, open(f"{root}/.pmo/project-config.yaml").read())
if d is not None:
    raise SystemExit(f"EXPORT_VALIDATION_FAILED  {d.code}: {d.message}")
print("POST_EXPORT_VALIDATION = PASS")
```

### Return contract

Every validator returns **`None` on pass** or a **`Decision`** on the first
failure. `Decision` exposes `.code` (`PMO-EXPORT-001` … `PMO-EXPORT-010`) and
`.message`. The process entrypoint always exits `0`; the meaningful signal is
the returned object (module mode) or the emitted JSON (hook mode) — **never the
exit code**.

### Functions this skill calls

| Phase | Call | Purpose / codes |
|---|---|---|
| 0/1 | `locate_project_root(cwd)` | resolve the project root |
| 1 | `calculate_sha256(path)` | `source_hash_pre` (Section 13) |
| 1 | `capture_source_state(path)` | snapshot (`{"path","sha256","size"}`) for the Phase 4 hash check |
| 1 | `pre_export_check(source, export_path, audience, root, artifact_type=None)` | `PMO-EXPORT-001` / `002` / `003` / `004` + export path under `docs/pmo/exports/` |
| 1 | `detect_export_collision(export_path, root, regeneration_authorized=False, src_version=None, manifest_data=None)` | `PMO-EXPORT-009` |
| 4 | `post_export_validation(source, export_path, root, audience="CLIENT", pre_state=None, allowed_missing=None, expect_manifest_record=True)` | chains: source hash unchanged (`005`) → DOCX package structure (`007`) → internal-content leak (`006`) → identifier reconciliation (`005`) → manifest integrity + `source_hash` match + `substantive_content_changed == false` (`008`) |
| 4 | `validate_pmo_state_unchanged(before_text, after_text)` | `PMO-EXPORT-005` — protected `project-config` keys unchanged. **Not** covered by `post_export_validation`; call it separately with the Phase 0 text vs the post-Phase-3 text. |
| 4 (granular, optional) | `validate_source_unchanged`, `validate_docx_package`, `extract_text_for_scan`, `detect_internal_content`, `extract_governed_identifiers`, `validate_identifier_reconciliation`, `read_export_manifest`, `check_manifest_file` | run one check in isolation for diagnosis |

`post_export_validation` does **not** inspect PMO project state — Phase 4 must
also call `validate_pmo_state_unchanged` with the `.pmo/project-config.yaml`
text captured in Phase 0 versus its text after Phase 3.

---

## 28. Definition of success

A successful export requires **both**:

```
PRE_EXPORT_VALIDATION  = PASS
POST_EXPORT_VALIDATION = PASS
```

and the source SHA-256 identical before Phase 1 and after Phase 4.

- **Generating a DOCX alone is not success.** A document that has not passed
  Phase 4 direct validation is not a client deliverable.
- If **Phase 1** fails: report the `PMO-EXPORT-*` code (or
  `EXPORT_REQUIRES_SOURCE_CORRECTION`), `PRE_EXPORT_VALIDATION = FAIL`, and
  stop **before** generation.
- If **Phase 4** fails: report **`EXPORT_VALIDATION_FAILED`** with the
  `PMO-EXPORT-*` code and `POST_EXPORT_VALIDATION = FAIL`, and **do not present
  the generated document as valid**. It is not delivered.
- **Never modify source content to make validation pass** (Section 2). A
  validation failure that traces to the source is routed back to the owning
  PMO workflow via `EXPORT_REQUIRES_SOURCE_CORRECTION`.
- Export still changes **no** PMO state (Section 23) — on the success path and
  on every failure path.
