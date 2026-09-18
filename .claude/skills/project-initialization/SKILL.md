# Project Initialization (PMO)

## 1. Purpose and position in the PMO lifecycle

Project Initialization is the **first** stage of the PMO lifecycle - it
establishes the governed identity a new project needs before any content
artifact (Intent, Q&A, Specs) can legitimately exist:

```
(nothing)
  -> Project Initialization (this skill)
    -> Intent Generation
      -> PM Intent Approval
        -> Questions & Assumptions
          -> Specification Generation
```

This stage produces exactly one artifact: `.pmo/project-config.yaml`, the
single identity/routing record every downstream guard already treats as
authoritative for **identity** (`project.id` / `project.name` /
`project.client`) and **repository routing**
(`repository.provider` / `.workspace` / `.repository` / `.working_branch`).
It also performs source discovery and classification, producing the
verified corpus under `docs/pmo/sources/` that Intent Generation consumes.

This stage does **not** generate Intent, does **not** touch
`docs/pmo/requirements/`, `docs/pmo/scope/`, or `docs/pmo/specs/`, and does
**not** decide anything about project content - only project identity,
repository binding, and which source documents are part of the verified
corpus.

**Filling a real framework gap.** Prior to this skill, project identity and
repository binding were governed only at the guard layer
(`repo-binding-guard.py` validating `.pmo/project-config.yaml`), with no
owning Skill analogous to `requirement-gathering` or `spec-generation` -
`.pmo/project-config.yaml` was hand-authored. This skill closes that gap
without changing `repo-binding-guard.py` or any other guard: the guard
remains the sole enforcement point for what a valid `project-config.yaml`
looks like at push time; this skill's job is to produce one that already
satisfies it.

---

## 2. Prerequisites - hard gate

None. This is the entry point of the lifecycle. It is safe to invoke at
any time; if `.pmo/project-config.yaml` already exists with a usable
`project.id`, this stage reports the existing identity read-only and takes
no action unless the PM explicitly asks to reconfigure it (Section 9).

---

## 3. Inputs

- Project identity supplied by the PM: project name, client name, a stable
  Project ID (short, uppercase, hyphenated - e.g. `WM-TRUCKING`), and the
  PM's own name.
- Repository routing supplied by the PM or already known from the
  engagement: provider (`bitbucket` / `github` / `gitlab`), workspace,
  repository name, and the working branch this project's artifacts will
  live on.
- Whatever source material the PM provides or points to: contracts, SOWs,
  proposals, LOEs, change requests, client emails, meeting notes,
  transcripts.

Do not infer a missing identity field. A project with no stable Project ID
supplied stops and asks - never invents one from a project name.

---

## 4. Procedure

### 4.1 Project identity

Collect `project.id`, `project.name`, `project.client`, and the PM's name.
The Project ID is permanent once other artifacts (Intent, Q&A, Specs) exist
against it - `intent_approval_core.validate_project_identity` and every
other guard's identity check compares against it for the lifetime of the
project. Confirm it explicitly with the PM before writing it.

### 4.2 Repository binding

Collect `repository.provider`, `.workspace`, `.repository`, and
`.working_branch`. These fields are exactly what
`artifact_publish_core.extract_repo_fields` requires and what
`repo-binding-guard.py` Domain C validates against the actual Git remote at
push time - do not fabricate a workspace/repository name; if the PM does
not yet know it, leave the section absent rather than guessing (an absent
`repository:` section is a normal, valid intermediate state -
`extract_repo_fields` reports `PMO-PUBLISH-001` cleanly for it, and no
downstream stage requires repository binding before Specs).

### 4.3 Source discovery and classification

Discover the source material the PM provides and place it under
`docs/pmo/sources/<category>/`, using the same category vocabulary the
existing corpus already establishes (`contract/`, `proposal/`, `loe/`,
`client-requirements/`, `emails/`, `transcripts/`, `handover/`, `other/`).
Classify each source's authority the same way Intent Generation's own
Source Register does (Section 14 of `intent-generation`): `AUTHORITATIVE`
(signed contract/SOW/proposal), `SUPPORTING` / `SUPPORTED / CORROBORATED`
(emails, LOE, client requirements docs that corroborate the authoritative
set), or `AMBIGUOUS / SUPPORTING ONLY` (generic meeting links, ambiguous
correspondence with no independent content). Do not silently drop a source
the PM provided - an ambiguous source is recorded as ambiguous, never
discarded.

### 4.4 Write project-config.yaml

Write `.pmo/project-config.yaml` with exactly the identity and repository
fields collected above, using the same shape
`intent_approval_core.load_project_config` /
`artifact_publish_core.load_project_config` already parse (a project
section and, when known, a repository section - see any existing
`project-config.yaml` in this repository for the exact field names). Do
not add speculative `workflow.*` state fields beyond what the framework's
existing artifact-stage placeholders already establish - this skill's own
governed output is `project.*` and `repository.*` identity only.

### 4.5 Stop

Report the initialized identity, the source corpus summary (counts by
category and authority), and stop. **Do not generate Intent.** That is
`intent-generation`'s job, invoked as a separate, explicit next step (by
the PM directly, or - once built - by the PMO Orchestrator's
`INITIALIZE_PROJECT` auto-progression, which this skill does not itself
perform).

---

## 5. Quality validation rules

A project initialization is valid only when:

1. `.pmo/project-config.yaml` has a non-empty `project.id`, `project.name`,
   and `project.client`.
2. If a `repository:` section is present, it has all four required fields
   (`provider`, `workspace`, `repository`, `working_branch`) - a partial
   repository section is worse than none (fails
   `artifact_publish_core.extract_repo_fields` opaquely rather than
   cleanly reporting "not yet configured").
3. Every source file the PM provided is present under `docs/pmo/sources/`
   with a category and an authority classification - none silently
   dropped, none reclassified without stating why.
4. No `workflow.*` field claims a lifecycle stage this skill did not
   itself reach (in particular: never write anything implying Intent,
   Q&A, or Specs exist).

---

## 6. Guardrails - MUST NOT

- MUST NOT generate `docs/pmo/intent/intent.md` or any other downstream
  artifact - this skill's only output is `.pmo/project-config.yaml` and
  the classified source corpus under `docs/pmo/sources/`.
- MUST NOT fabricate a Project ID, workspace, or repository name the PM
  has not supplied or confirmed.
- MUST NOT overwrite an existing `.pmo/project-config.yaml`'s
  `project.id` without the PM's explicit confirmation - once other
  artifacts exist against an identity, changing it silently would break
  every downstream guard's identity check.
- MUST NOT drop, merge, or reclassify a source document without stating
  the change to the PM.
- MUST NOT attempt to verify the repository is actually reachable (no live
  Git remote check) - that remains `repo-binding-guard.py` /
  `artifact-publish-guard.py`'s job at publish time, never this skill's.
- MUST NOT commit or push.

---

## 7. Definition of done

- `.pmo/project-config.yaml` exists with a complete, PM-confirmed
  `project.*` identity block, and a complete `repository.*` block where
  the PM has supplied one.
- Every source document the PM provided is discoverable under
  `docs/pmo/sources/` with a category and authority classification.
- No downstream artifact (Intent, Q&A, Specs) was created or touched.
- The **PMO PROJECT INITIALIZATION RESULT** report (Section 8) is emitted.

---

## 8. Final output - PMO PROJECT INITIALIZATION RESULT

On completion, emit:

```
PMO PROJECT INITIALIZATION RESULT

Project:                <project.name>
Project ID:              <project.id>
Client:                  <project.client>
PM:                      <PM name>
Repository:              <provider>:<workspace>/<repository> (branch: <working_branch>)
                          | NOT YET CONFIGURED
Sources Discovered:       <count>
Sources By Category:      <category: count, ...>
Sources By Authority:     AUTHORITATIVE <n> / SUPPORTING <n> / AMBIGUOUS <n>
Project Config Written:   docs-relative path: .pmo/project-config.yaml
Next Stage:               INTENT_GENERATION
Validation:                PASS | BLOCKED (<reason>)
```

---

## 9. Reconfiguration (identity change on an existing project)

Reconfiguring an already-initialized project's repository fields is safe
and ordinary (the working branch or workspace can legitimately change).
Reconfiguring `project.id` on a project that already has downstream
artifacts is a **materially different, high-risk operation** - it must be
treated the same way any other identity-breaking change would be: stop,
name the exact downstream artifacts whose identity checks would be
affected, and require explicit PM confirmation before writing anything.
This skill never performs that change silently as part of ordinary
initialization.
