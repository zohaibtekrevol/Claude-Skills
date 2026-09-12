---
name: artifact-publish
description: >-
  Publish validated PMO project artifacts (Intent, Scope, canonical Specs,
  Feedback, Change Requests) from the PMO Engine workspace to the
  project-specific Project Artifact Git repository and branch declared in
  .pmo/project-config.yaml. The PMO Engine repository and the Project Artifact
  repository are always treated as two separate repositories; this Skill never
  assumes Claude's current Git checkout is the publishing target and never
  infers repository or branch identity from conversation history, the
  Engine's own Git origin, the current Git branch, similarly-named branches,
  provider defaults, main/master, or a previous project configuration.
  Repository and branch identity are resolved exclusively from
  .pmo/project-config.yaml (provider, workspace, repository, working_branch).
  Development/DevOps creates the project branch before PMO publishing begins,
  as part of project initialization — Artifact Publish is a publisher, not a
  branch-provisioning workflow, and has no authority to create, orphan, or
  rename a branch under any circumstance, including when the configured
  branch is missing. Publication runs against a portable, non-user-specific
  managed workspace clone
  (~/.pmo-workspaces/<provider>/<workspace>/<repository>/<branch>/) that only
  ever checks out an already-existing remote branch, and deterministically
  verifies the target repository — provider, workspace, repository,
  authentication, reachability, the exact configured branch's remote
  existence, managed-workspace remote identity, checked-out branch identity,
  clean worktree, zero unrelated staged files — before touching it; a missing
  remote branch is a hard block (never remediated by creating it, never
  falling back to another branch, another repository, or main/master). It
  only ever copies artifact families on the fixed allowlist
  (docs/pmo/intent/, docs/pmo/scope/, docs/pmo/specs/specs.md,
  docs/pmo/feedback/, docs/pmo/change-requests/) — never .claude/, .pmo/,
  docs/pmo/sources/, hooks, skills, contracts, transcripts, emails, LOEs,
  credentials or other PMO-Engine-only material, and never an ad-hoc
  docs/pmo/exports/ file unless a separate publication policy explicitly
  authorises it. Every copy is source-hash verified against its destination
  hash (SHA-256) before commit. Publishing an artifact requires that
  artifact's owning governance workflow already reports PASS (Intent schema
  governance, Scope version/approval governance, Specs governance, future
  Feedback/CR governance) — publication is transport only, it never approves,
  never bumps a version, never flips Specs Execution Authorized, and never
  alters Intent/Scope/Specs/client-approval/commercial state. Byte-identical
  artifacts already on the target produce NO_CHANGES_TO_PUBLISH with no empty
  commit. Only allowlisted, hash-verified files are staged and committed with
  a deterministic message; push targets only the configured
  provider/workspace/repository/branch with no fallback remote, no fallback
  branch, and no force push. PMO-PUBLISH-001 … PMO-PUBLISH-015 define
  deterministic, fail-closed halt conditions (PMO-PUBLISH-014 =
  TARGET_BRANCH_NOT_FOUND — the configured branch does not exist remotely;
  remediation is Development/DevOps or an authorised repository administrator
  creating it, never this Skill), and every run ends with a PMO ARTIFACT
  PUBLISH RESULT report.
---

# Artifact Publish (PMO)

## 1. Purpose and position in the PMO lifecycle

Artifact Publish is the **transport** stage of the PMO workflow. It sits after
every authoring stage (Intent Validation, Requirement Gathering, Specification
Generation, Feedback, Change Request) and is invoked whenever a validated PMO
artifact needs to reach the **Project Artifact Repository** — the separate,
project-specific Git repository that Development and QA actually consume.

It is not an authoring stage, and it is not a governance stage. It does not
decide whether an artifact is right; it moves an artifact that another
workflow has already governed. Its contract in one line: **publishing is
transport, not approval.**

It is also, per Section 3, **not a branch-provisioning workflow**: it
publishes into a branch someone else already created; it never creates one
itself.

---

## 2. Architecture — two separate repositories

There are exactly two repositories in play, and they are never the same
checkout:

| | PMO Engine (this checkout) | Project Artifact Repository (publish target) |
|---|---|---|
| Contains | Skills, hooks, `.pmo/project-config.yaml`, source evidence (contracts, transcripts, emails, LOEs), the authoring copies of Intent / Scope / Specs / Feedback / Change Requests, validation logic, `.claude/`, `docs/pmo/sources/`, `docs/pmo/exports/` | Only the allowlisted, approved/project-consumable PMO artifacts Development and QA need (Section 13) |
| Git identity | Whatever remote this checkout happens to have (irrelevant to publishing) | `provider` / `workspace` / `repository` / `working_branch` from `.pmo/project-config.yaml` |
| Normal target structure | n/a | `docs/pmo/intent/intent.md`, `docs/pmo/scope/scope-vX.Y.md`, `docs/pmo/specs/specs.md`, `docs/pmo/feedback/`, `docs/pmo/change-requests/` |

**The Skill MUST NOT assume Claude's current Git repository is the project
repository.** It never runs `git push` against the PMO Engine's own working
tree as a way of publishing, and it never reads the PMO Engine's `git remote
get-url origin` as a substitute for `.pmo/project-config.yaml`. Every
publishing Git operation happens inside the managed workspace clone
(Section 9), addressed by path, independent of whatever directory the current
Claude Code session happens to be in.

---

## 3. Confirmed organizational branch model

This is the production governance model this Skill operates under, and it
overrides any earlier assumption that publication could bootstrap a branch:

- The **Development/DevOps team** creates the project branch on the Project
  Artifact Repository **before** PMO publishing ever begins.
- A newly created project branch **may be completely empty** — that is
  expected and valid (Section 6).
- The **PM** supplies the exact repository name and the exact branch name
  during **project initialization** (`project-init`; Section 11) — not during
  a publish run.
- **Artifact Publish MUST publish into that already-EXISTING configured
  branch.**
- **Artifact Publish MUST NOT create project branches** — not a normal
  branch, not an orphan branch, not a differently-named branch, not `main`,
  not `master`. This applies **even when the configured branch is missing**
  (Sections 5, 8): a missing branch is a block condition, never a trigger to
  create one.

Artifact Publish is a **publisher**, not a branch-provisioning workflow
(Section 8 makes this explicit as a guardrail).

---

## 4. Source of repository and branch identity

`provider`, `workspace`, `repository`, and `working_branch` are authoritative
project routing identity. They are read **only** from:

```
.pmo/project-config.yaml → repository:
  provider          (required — must resolve to a supported provider, Section 10)
  workspace          (required)
  repository         (required)
  working_branch     (required — the EXACT branch DevOps already created)
  remote             (optional, informational only — the PMO Engine's own
                      remote name; irrelevant to the managed workspace clone)
  verified           (boolean — set true only after this Skill's Section 10
                      verification passes in full, including branch existence;
                      Specs governance's validate_publish_readiness() reads
                      this field and blocks marking Specs as published while
                      it is not true)
```

**Do not infer** `provider`, `workspace`, `repository`, or `working_branch`
from any of the following, even as a fallback when the config looks
incomplete:

- the current Git branch (in the PMO Engine checkout or anywhere else);
- conversation history, a prior session, or a URL pasted earlier;
- an existing branch with a similar or plausible-looking name;
- a provider's default branch;
- `main` or `master`;
- a previous project's configuration, or a previous value this project used
  before it was reconfigured.

Further rules:

- **Do not use** the PMO Engine's own Git origin as the publishing target,
  even if it happens to look plausible.
- If any of `provider`, `workspace`, `repository`, `working_branch` is
  missing, empty, or the file itself is missing/unparseable →
  `PMO-PUBLISH-001 PROJECT_CONFIG_MISSING`, `STOP`, before any network or Git
  action. A missing `working_branch` is `PMO-PUBLISH-001`, not a cue to guess
  one.
- `provider` must be one of the supported providers (Section 10); an
  unrecognised value is also `PMO-PUBLISH-001`.

---

## 5. Branch existence is mandatory

Before any other repository verification, and before the managed workspace is
touched, perform a **remote, read-only** branch-existence check. Conceptually:

```
git ls-remote --heads <configured-repository> <configured-branch>
```

The **exact** branch named in `working_branch` must already exist on the
remote — not a similarly-named branch, not a case-insensitive match, not a
branch that merely exists locally in some other checkout.

- **If it exists remotely** → continue to full repository verification
  (Section 10).
- **If it does not exist remotely** → `BLOCK` with `PMO-PUBLISH-014
  TARGET_BRANCH_NOT_FOUND` (Section 21). Specifically, do **not**:
  - create it;
  - create an orphan branch in its place;
  - derive or guess an alternative branch name;
  - fall back to `main`;
  - fall back to `master`;
  - reuse another project's branch, or another branch in the same
    repository;
  - accept a **local-only** branch (e.g. one left over in a stale managed
    workspace) as proof that the remote branch exists — the check is against
    the remote, every run.

This check is mandatory on **every** run, not cached from a prior verified
run — a branch that existed yesterday and was deleted today must be caught
today.

---

## 6. Empty existing branch vs. non-existent branch

These two situations look superficially similar (no PMO files visible) and
must be handled as opposites:

| | Empty existing branch | Non-existent branch |
|---|---|---|
| Remote branch-existence check (Section 5) | **passes** — the ref exists | **fails** — no such ref |
| PMO content present | none — no `docs/pmo/`, no Intent, no Scope, no Specs | n/a |
| Valid publication target? | **YES** | **NO** |
| Action | continue verification and publish into it (this section) | `BLOCK` — `PMO-PUBLISH-014` (Section 5, Section 21) |

An existing configured project branch may legitimately contain no PMO files,
no Intent, no Scope, and no Specs. That is a valid, expected state — **not**
an error and **not** license to create a different branch instead.

For a valid empty existing branch:

- The first Artifact Publish run **may create** the `docs/pmo/` directory
  structure — only the allowlisted sub-directories actually being published
  (Section 13) — inside that **already-existing** branch. This is not treated
  as an unrelated or unexpected change.
- Do **not** require sample/placeholder Intent, Scope, or Specs files to
  pre-exist on the target branch before a real publish can happen.
- `.gitkeep` placeholders (as already used for `docs/pmo/feedback/.gitkeep`
  and `docs/pmo/change-requests/.gitkeep` in the verified manual publication)
  remain a valid way to materialise an otherwise-empty allowlisted directory;
  they are part of the normal target structure, not an off-allowlist file.

**Worked example — valid first publication.** Repository
`devops-tekrevol/lets-explore-more-specs`, branch `smart-basket`. The branch
already exists remotely (created by DevOps) but currently contains no files.
PMO has generated validated artifacts. Artifact Publish checks out the
existing `smart-basket` branch (Section 9) and publishes:

```
docs/pmo/intent/intent.md
docs/pmo/scope/scope-v0.1.md
docs/pmo/specs/specs.md
docs/pmo/feedback/
docs/pmo/change-requests/
```

This is a **valid** first publication. **No new branch is created** — only
files are added inside the branch DevOps already created.

---

## 7. No fallback routing

The following redirections are all explicitly prohibited, with no exception
this Skill can grant itself:

| Condition | Prohibited redirection | Result |
|---|---|---|
| Configured branch unavailable | publishing to another branch | `BLOCK` |
| Configured repository unavailable | publishing to another repository | `BLOCK` |
| Configured branch missing | creating the branch | `BLOCK` |
| Configured branch missing | falling back to `main`/`master` | `BLOCK` |

There is no "just this once" or "close enough" substitute target. Every row
above maps to a `PMO-PUBLISH-0XX` block (chiefly `PMO-PUBLISH-014` for the
branch rows, `PMO-PUBLISH-002`/`004` for the repository row) — see
Section 21.

---

## 8. Artifact Publish has no branch-creation authority

Artifact Publish is a **publisher**, not a branch-provisioning workflow. It
carries no language, mode, flag, or caller override that lets it normally
create the configured project branch — that authority does not exist in this
Skill.

- If branch provisioning is ever automated in the future, it must be a
  **separate, explicitly-authorised administrative/bootstrap workflow** —
  outside this Skill, invoked deliberately by someone with repository-admin
  authority, and never triggered implicitly by a publish request.
- A caller asking this Skill to "just create the branch and publish anyway"
  is asking for something out of scope: refuse the branch-creation half,
  explain that Development/DevOps or an authorised repository administrator
  must create `working_branch` first (Section 21, `PMO-PUBLISH-014`
  remediation), and do not publish until Section 5's check passes on a
  subsequent run.

---

## 9. Managed publishing workspace

Publication never runs inside the PMO Engine checkout and never hardcodes a
user-specific absolute path (e.g. `/Users/<user>/Projects/...`). It uses a
portable, reusable convention rooted at the invoking user's home directory:

```
~/.pmo-workspaces/
  <provider>/
    <workspace>/
      <repository>/
        <branch>/
```

Concretely, resolved from `.pmo/project-config.yaml`:

```
~/.pmo-workspaces/bitbucket/devops-tekrevol/lets-explore-more-specs/smart-basket/
```

- Build this path with the user's home directory resolved at run time
  (`$HOME` / `~`, never a literal `/Users/<name>/...` string), so the Skill
  behaves identically on any PM's machine.

**If the managed workspace does not exist:**

1. Clone/fetch the target repository.
2. Verify remote identity (Section 10, checks 1–4, 7).
3. Fetch branches.
4. Check out the **existing** configured branch — Section 5 must already
   have confirmed it exists remotely before this step runs.

**If the managed workspace already exists:**

1. Verify remote identity is still correct (Section 10, check 7).
2. Fetch.
3. Re-verify the configured branch **still** exists remotely (Section 5 is
   re-run, not assumed from a prior session).
4. Check out / update the configured branch safely (fast-forward /
   hard-sync to the remote tip so stale local state from an earlier run
   cannot leak into a new publish — confined entirely to this managed
   workspace clone, never applied to the PMO Engine checkout or any other
   repository on the machine).

**Never use, for normal Artifact Publish operations:**

```
git switch --orphan
git checkout -b <configured-branch>
git switch -c <configured-branch>
```

The publisher **must consume an existing remote branch** — every checkout in
this Skill tracks a ref that Section 5 already confirmed is present on the
remote. If those confirmations ever fail mid-run, stop; do not fall back to
one of the commands above to "make it work."

- All Git operations against the managed workspace address it **by path**
  (`git -C <managed-workspace-path> …`) rather than by `cd`-ing the Claude
  Code session's persistent working directory into it. This keeps the
  session's cwd stable for unrelated commands and keeps the managed
  workspace's identity explicit at every step (see Section 20 for why this
  also matters for the existing `repo-binding-guard.py` hook).
- Never place `.pmo/`, `.claude/`, source evidence, or anything off the
  allowlist (Section 13) inside the managed workspace as tracked content —
  the managed workspace mirrors the Project Artifact Repository, not the
  Engine.

---

## 10. Target repository verification

**Before publication**, deterministically verify all ten of the following. A
repository is **VERIFIED** only once **every** check below passes for the
*current* run — a stale `verified: true` from an earlier run is not trusted
on its own, and **`repository.verified` must never be set to `true` merely
because authentication succeeds**: exact branch verification (check 6) is an
inseparable part of repository verification, not an optional extra. Re-verify
reachability, auth, and branch state every time; only treat identity/provider
parsing as reusable once already confirmed unchanged since the last verified
run.

| # | Check | Method | Failure code |
|---|---|---|---|
| 1 | `provider` is supported | `provider` is one of `github` / `bitbucket` / `gitlab` (self-hosted variants matched by hostname, mirroring `repo-binding-guard.py`'s `provider_from_host`) | `PMO-PUBLISH-001` |
| 2 | `workspace` exists | provider API/CLI or `git ls-remote` against the constructed URL resolves without a "not found" response | `PMO-PUBLISH-002` |
| 3 | `repository` exists | same `git ls-remote` call succeeds against the specific repository path | `PMO-PUBLISH-002` |
| 4 | authentication succeeds | `git ls-remote`/`clone`/`fetch` completes without an interactive credential prompt or an auth error; never embed a token/password in a URL that gets logged or committed | `PMO-PUBLISH-003` |
| 5 | remote reachability | the network call above completes (not a DNS/timeout/connection failure) | `PMO-PUBLISH-002` |
| 6 | the **exact** configured branch exists remotely | `git ls-remote --heads <url> <branch>` returns a ref (Section 5) — **no creation-authorised alternative exists** | branch missing → `PMO-PUBLISH-014` (never remediated by this Skill) |
| 7 | managed publishing workspace remote identity matches | parse the managed workspace's own `origin` URL (HTTPS or SSH) the same way `repo-binding-guard.py`'s `parse_remote_url` does, and compare host→provider, workspace, repository against config | `PMO-PUBLISH-004` |
| 8 | checked-out publishing branch equals configured `working_branch` | `git -C <workspace> rev-parse --abbrev-ref HEAD` equals `working_branch` after checkout | `PMO-PUBLISH-005` |
| 9 | target worktree is clean | `git -C <workspace> status --porcelain` is empty after the fetch/sync in Section 9 | `PMO-PUBLISH-006` |
| 10 | unrelated staged files = 0 | `git -C <workspace> diff --cached --name-only` is empty before this run stages anything | `PMO-PUBLISH-010` |

Only when **all ten** pass is the repository **VERIFIED** for this run. Record
the outcome (Section 22/23) but do not silently downgrade any check — a
partial pass is not a pass, and passing checks 1–5 (identity/reachability/
auth) without check 6 (branch existence) is **not** verification — it is,
at most, "repository reachable, branch unconfirmed."

---

## 11. Project-init relationship

The lifecycle relationship between project initialization and this Skill is
strict and one-directional:

- **`project-init`** → captures repository identity **and** the exact,
  already-existing branch DevOps created, and records both in
  `.pmo/project-config.yaml`.
- **Artifact Publish** → **consumes** that configuration as-is.

**Artifact Publish does not repair or invent missing routing information.**
It is not this Skill's job to guess a branch name, offer to create one, or
patch `.pmo/project-config.yaml` to make a publish succeed. Concretely:

- If `working_branch` is **missing** from the config → `BLOCK`
  (`PMO-PUBLISH-001`, Section 4).
- If `working_branch` is present but **does not exist remotely** → `BLOCK`
  (`PMO-PUBLISH-014`, Section 5).

Either way, the fix happens upstream — in `project-init` (correcting the
recorded branch) or in DevOps' repository administration (creating the
branch) — never inside this Skill.

---

## 12. Current `pmo-artifacts` branch — not a naming convention

The current Smart Basket `pmo-artifacts` branch was created **manually**, as
a controlled infrastructure proof-of-concept, before this branch model was
formalised. It demonstrated that manual publication to a Bitbucket branch
works; it does not define a pattern this Skill should expect or require.

- Do **not** treat `pmo-artifacts` as a mandatory or implied branch-naming
  convention.
- Future projects must use whatever **actual** project branch DevOps created
  and the PM recorded during `project-init` (Section 11) — `smart-basket` in
  the worked example (Section 6), or any other name a given project actually
  uses.
- This task does not alter or delete the existing `pmo-artifacts` branch; it
  remains exactly as manually published.

---

## 13. Artifact allowlist

Only these PMO artifact families may ever be published:

```
docs/pmo/intent/
docs/pmo/scope/
docs/pmo/specs/specs.md
docs/pmo/feedback/
docs/pmo/change-requests/
```

**Never** published automatically, regardless of caller phrasing:

```
.claude/
.pmo/
docs/pmo/sources/
hooks
Skills / SKILL.md files
test scripts
contracts
transcripts
emails
LOEs
raw client evidence
scratchpads / temporary files
credentials / SSH keys / tokens
internal validation logs
docs/pmo/exports/   (requires an explicit, separate publication policy —
                      never bundled into a normal artifact publish)
```

A requested source path outside the allowlist is `PMO-PUBLISH-007
UNAPPROVED_ARTIFACT_PATH` — `BLOCK`, do not stage, do not ask the Skill to
"just this once" widen the allowlist. Widening the allowlist is a change to
this Skill file, not a runtime decision.

---

## 14. Canonical Specs path

The only live execution Specs path is:

```
docs/pmo/specs/specs.md
```

Never create or publish `specs-vX.Y.md`. Development and QA consume the single
canonical `specs.md`; its logical version lives in the file's own metadata and
Change History table, not in the filename. A requested destination like
`docs/pmo/specs/specs-v0.2.md` is `PMO-PUBLISH-007`.

---

## 15. Publishing eligibility — governance must already PASS

Publication of an artifact requires that the artifact's **owning governance
workflow** already reports PASS for the version being published. This Skill
does not re-derive governance from scratch; it calls the same deterministic
guards the authoring skills already use, in read-only / query mode, and
treats a governance failure as a hard block:

| Artifact | Owning governance | How this Skill checks it |
|---|---|---|
| Intent | Intent schema governance | Import `.claude/hooks/intent-schema-guard.py` and run `full_schema_validation(content, meta, root, status=...)` against the current `docs/pmo/intent/intent.md`; a returned `Decision` → `PMO-PUBLISH-008`. |
| Scope | Scope version/approval governance appropriate to its lifecycle state | Import `.claude/hooks/scope-version-guard.py` and run `full_scope_validation(content, meta, status, root, target_ver)` for the scope file being published; a `Decision` → `PMO-PUBLISH-008`. Publishing a `DRAFT_CLIENT_REVIEW` scope does not require `validate_scope_approval` to have passed — only that the draft's own governance for its declared status passes (mirrors `artifact-export`'s treatment: a draft may be published for review without being approved). |
| Specs | Specs governance | Import `.claude/hooks/specs-governance-guard.py` and run `full_spec_validation(root, spec_text=...)`; a `Decision` → `PMO-PUBLISH-008`. Also call `validate_publish_readiness(root)` — if it returns a `Decision` (i.e. `repository.verified` is not `true`), that means *this Skill's own* Section 10 verification has not yet completed for this run; do **not** treat it as a Specs content defect, run/complete Section 10 first. |
| Feedback | Future Feedback governance | When a Feedback governance guard exists, call it the same way; until then, `PMO-PUBLISH-008` on any structural defect this Skill can detect deterministically (non-empty, matches the expected Feedback record shape), and otherwise proceed — do not block on governance that does not yet exist. |
| Change Request | Future CR governance (PM + client approval, commercial clearance) | Same treatment as Feedback: call the guard once it exists; until then, require `.pmo/project-config.yaml`'s `change_request.pm_approval_required` / `client_approval_required` / `commercial_clearance_required` gates to be satisfiable from recorded approval evidence the caller supplies, or block with `PMO-PUBLISH-008` naming what is missing. |

**Publishing MUST NOT convert an artifact into an approved state.** Calling a
governance guard here is read-only validation, not a re-run of the authoring
skill — this Skill never writes Intent/Scope/Specs content, never writes an
approval record under `.pmo/approvals/`, and never changes `workflow.*` in
`.pmo/project-config.yaml`.

---

## 16. Execution authorization is untouched

Publishing `docs/pmo/specs/specs.md` **must never** change `Execution
Authorized` in the Specs metadata, and must never change
`artifacts.specifications.execution_authorized` in
`.pmo/project-config.yaml`.

A `PROVISIONAL` specification with `execution_authorized: false` **may** still
be published — for review, QA preparation, estimation, or controlled
visibility. **Publication ≠ Development authorization.** If a caller asks this
Skill to "authorize" or "approve" anything while publishing, refuse that part
of the request and point back to the Specs governance workflow; publish only
the transport.

---

## 17. Content transfer

For every artifact file being published, in this exact order:

1. **Resolve the authoritative source** — the exact file under
   `docs/pmo/{intent,scope,specs,feedback,change-requests}/` in the PMO
   Engine checkout that the caller (or the allowlist-driven default) names.
2. **Calculate SHA-256** of the source file's exact bytes.
3. **Validate the destination path** — it must map 1:1 onto the same
   `docs/pmo/<family>/<filename>` layout inside the managed workspace, and
   must itself be inside the allowlist (Section 13). Reject any destination
   that would land outside `docs/pmo/{intent,scope,specs,feedback,change-requests}/`.
4. **Copy** the file to that destination path in the managed workspace
   (create intermediate directories as needed — Section 6).
5. **Calculate the destination SHA-256** immediately after the copy.
6. **Require `source hash == destination hash`.** A mismatch is
   `PMO-PUBLISH-009 SOURCE_DESTINATION_HASH_MISMATCH` — `BLOCK`, do not stage,
   do not retry silently; re-copy once and re-hash, and if it still mismatches
   treat it as an environment fault (Section 21) rather than continuing.

**Never mutate the authoritative source** during publishing — the PMO Engine
copy is opened read-only for the whole run; only the managed workspace copy is
written.

---

## 18. No-change behavior

Before staging anything, compare the post-copy destination content
(Section 17) against what the managed workspace's target branch already
holds at each destination path.

If **every** artifact this run would publish is already present at the
destination with a byte-identical hash:

- create **no commit**;
- create **no push**;
- return:

```
NO_CHANGES_TO_PUBLISH
```

as the `Final Result` (Section 23), still reporting source/destination hashes
and the fact that they matched. Never fabricate a commit to "show activity."

---

## 19. Controlled staging and commit

Only the allowlisted PMO artifact files actually copied in this run may be
`git add`-ed. Before committing:

1. Re-run `git -C <workspace> status --porcelain` and confirm every changed
   path is inside the allowlist (Section 13). Any path outside it —
   including a path that was already dirty in the workspace before this run
   started (Section 10, check 10) — is `PMO-PUBLISH-010
   UNRELATED_STAGED_FILE`: `BLOCK`, unstage, do not commit anything this run
   until the workspace is clean of unrelated changes.
2. Stage exactly the allowlisted, hash-verified files (`git add
   docs/pmo/<family>/<file>` per file — never `git add -A` / `git add .`
   inside the managed workspace).
3. **Report before committing**:
   - files added / modified / removed (by path);
   - source SHA-256 and destination SHA-256 for each file;
   - target repository (`workspace/repository`);
   - target branch.
4. Reject (do not commit) if any staged file is not on the allowlist, or if
   its source hash and destination hash disagree (Section 17).
5. **Commit** with a deterministic, informative message naming the project,
   artifact family, and version/identifier, e.g.:

   ```
   PMO: publish Smart Basket specs v0.2
   PMO: publish Smart Basket scope v0.3
   PMO: publish Smart Basket feedback FDB-004
   PMO: publish approved CR-002
   ```

   A commit failure (hook rejection inside the managed workspace, nothing
   staged, non-zero `git commit` exit) is `PMO-PUBLISH-011 COMMIT_FAILED`.

---

## 20. Push

Push **only** to the configured provider / workspace / repository / branch
resolved in Section 4 and re-verified in Section 10:

- **No fallback remote.** Never push to a remote other than the one pointing
  at the verified `workspace/repository` (Section 7).
- **No fallback branch.** Never push to a branch other than
  `working_branch`, and never push `HEAD` to an ambiguous/current-branch
  default if that would resolve differently (Section 7).
- **No force push**, ever, from this Skill. A caller asking for `--force` /
  `-f` / `--force-with-lease` is `PMO-PUBLISH-013 FORCE_PUSH_ATTEMPT` —
  refuse, do not execute, explain why.
- **No push to `main`/`master`** unless `.pmo/project-config.yaml`'s
  `repository.working_branch` **explicitly** designates `main` (or `master`)
  as the branch DevOps actually created for this project **and**
  `workflow.publishing` / organizational governance permits it. Absent that
  explicit designation, a push targeting `main`/`master` is a fallback
  (Section 7) and is `PMO-PUBLISH-014`.
- A push that fails for any other reason (auth expired mid-run, remote
  rejected the ref, non-fast-forward) is `PMO-PUBLISH-012 PUSH_FAILED` —
  `BLOCK`, do not retry with `--force`, surface the underlying Git error.

**Known constraint — `repo-binding-guard.py`.** This project's
`.claude/settings.json` already wires `repo-binding-guard.py` as a
`PreToolUse` hook on every `Bash` call, and it inspects `git push` regardless
of which directory the command actually targets. That hook reads
`.pmo/project-config.yaml` and `git remote get-url` **relative to the Claude
Code session's current working directory**, not relative to a `-C <path>`
target — so it validates the *session's* checkout, not necessarily the
managed workspace this Skill pushes from. Because the PMO Engine root and the
managed workspace are different repositories, **`repo-binding-guard.py` alone
does not protect the managed-workspace push**, and this Skill must not assume
otherwise or rely on it for that purpose.

The forthcoming, not-yet-built artifact-publish guard (Section 24 — explicitly
out of scope for this task, and `repo-binding-guard.py` itself is **not**
modified as part of this task) must **independently** validate, for the
managed-workspace push specifically:

```
provider
workspace
repository
branch
remote URL
managed workspace (path/identity)
staged files
push destination
```

before allowing publication. Until that guard exists, the checks in this
section, Section 7, and Section 10 are this Skill's own, independent
enforcement — it does not delegate push safety to `repo-binding-guard.py`. If
a managed-workspace `git push` is unexpectedly denied by that hook, do not
attempt to work around, disable, or reconfigure it; report `PMO-PUBLISH-012`
(or `PMO-PUBLISH-002` if the denial reads as a reachability/identity problem)
and stop.

---

## 21. Failure conditions

Deterministic, fail-closed halt behaviour. `BLOCK` = do not publish, do not
commit, do not push; report and stop.

| Code | Name | Condition | Effect | Required remediation |
|---|---|---|---|---|
| `PMO-PUBLISH-001` | `PROJECT_CONFIG_MISSING` | `.pmo/project-config.yaml` is missing/unparseable, or `repository.provider` / `workspace` / `repository` / `working_branch` is missing, empty, or `provider` is unsupported. | BLOCK before any network/Git action. | Fix `.pmo/project-config.yaml` in `project-init` (Section 11); this Skill does not guess the missing value. |
| `PMO-PUBLISH-002` | `TARGET_REPOSITORY_UNREACHABLE` | The configured workspace/repository cannot be found, or the network call to it fails (DNS, timeout, connection refused). | BLOCK. | Confirm the workspace/repository name and network access; retry. |
| `PMO-PUBLISH-003` | `AUTHENTICATION_FAILED` | Git/API authentication to the provider fails, or would require an interactive credential prompt this Skill cannot satisfy non-interactively. | BLOCK. Never prompt for or embed a secret to force it through. | Fix the credential/auth configuration for the provider; retry. |
| `PMO-PUBLISH-004` | `REMOTE_IDENTITY_MISMATCH` | The managed workspace's actual remote (host/workspace/repository) does not match `.pmo/project-config.yaml`. | BLOCK. | Re-point or re-clone the managed workspace to the configured remote; never publish against a mismatched identity. |
| `PMO-PUBLISH-005` | `BRANCH_MISMATCH` | The managed workspace's checked-out branch does not equal `working_branch` after checkout. | BLOCK. | Check out `working_branch` explicitly in the managed workspace; do not publish from another checked-out branch. |
| `PMO-PUBLISH-006` | `TARGET_WORKTREE_DIRTY` | `git status --porcelain` in the managed workspace is non-empty before this run stages anything. | BLOCK. | Investigate and resolve the pre-existing dirty state in the managed workspace before retrying. |
| `PMO-PUBLISH-007` | `UNAPPROVED_ARTIFACT_PATH` | A requested source or destination path is outside the Section 13 allowlist, or is a non-canonical Specs path (Section 14). | BLOCK. | Publish only allowlisted, canonical paths; widening the allowlist is a Skill-file change, not a runtime override. |
| `PMO-PUBLISH-008` | `SOURCE_ARTIFACT_NOT_VALID` | The artifact's owning governance workflow (Section 15) does not report PASS for the version being published. | BLOCK. | Resolve the governance failure in the artifact's owning authoring workflow; retry once it reports PASS. |
| `PMO-PUBLISH-009` | `SOURCE_DESTINATION_HASH_MISMATCH` | Destination SHA-256 does not equal source SHA-256 after copy (and after one re-copy attempt). | BLOCK. | Treat as an environment fault; investigate the copy path/filesystem before retrying. |
| `PMO-PUBLISH-010` | `UNRELATED_STAGED_FILE` | A staged/dirty path in the managed workspace is outside the allowlist, whether pre-existing or introduced mid-run. | BLOCK. | Clean the unrelated file out of the managed workspace; never commit it alongside allowlisted artifacts. |
| `PMO-PUBLISH-011` | `COMMIT_FAILED` | `git commit` fails, is rejected by a hook in the managed workspace, or nothing valid is left staged. | BLOCK. | Diagnose the commit failure/hook rejection in the managed workspace; retry. |
| `PMO-PUBLISH-012` | `PUSH_FAILED` | `git push` fails for any reason other than an explicit force-push or a branch/routing violation already covered by another code (auth expiry, non-fast-forward, remote rejection, an unrelated hook denial per Section 20). | BLOCK. | Diagnose the specific Git push failure; never retry with `--force`. |
| `PMO-PUBLISH-013` | `FORCE_PUSH_ATTEMPT` | The run would require, or a caller requests, `--force` / `-f` / `--force-with-lease`. | BLOCK — refuse outright, never execute. | Resolve the underlying divergence without rewriting remote history; this Skill never force-pushes. |
| `PMO-PUBLISH-014` | `TARGET_BRANCH_NOT_FOUND` | The branch configured in `.pmo/project-config.yaml` (`working_branch`) does not exist in the target remote repository (Section 5), or a push/routing action would fall back to another branch, another repository, or `main`/`master` without explicit authorised configuration (Section 7). | BLOCK. | **Development/DevOps or an authorised repository administrator must create the required branch** (or correct `project-init`'s recorded branch, Section 11); PMO publication may then be **retried**. Artifact Publish must **never** remediate this condition by creating the branch itself. |
| `PMO-PUBLISH-015` | `PUBLISH_INTERNAL_ERROR` | Any unexpected exception during a controlled publishing step. | BLOCK (fail closed) — never publish partially or guess a recovery. | Fix the underlying defect in the Skill's execution or its inputs; retry. |

Any check in Sections 5, 7, 10, 13, 15, 17, 19, or 20 that fails maps to the
code shown in that section; this table is the canonical index. No unlisted
failure mode should ever silently proceed — an unmapped failure is
`PMO-PUBLISH-015`.

---

## 22. Project state — publishing records metadata, not approval

Publication **may** record publishing metadata, separately from any
authoring/approval state, e.g. under a `publishing:` block in
`.pmo/project-config.yaml`:

```yaml
publishing:
  repository_verified: true
  last_publish_at: "2026-09-11T00:00:00Z"
  last_publish_commit: "<hash>"
  last_published_artifact: "specs"
  last_published_version: "0.2"
```

If Section 10 verification passes **in full — including the exact-branch
check (check 6)** — this Skill **may also** set the existing top-level
`repository.verified: true` (the field `specs-governance-guard.py`'s
`validate_publish_readiness()` already reads) — this is the one field this
Skill is explicitly permitted to update, because it is itself the
verification's own state, not authoring/approval state. It must never be set
on the strength of authentication/reachability alone (Section 10).

Publication **must never** alter, as a side effect of a successful publish:

- Intent approval (`workflow.intent.approved`, `artifacts.intent.status`);
- Scope approval or version fields (`workflow.scope.approved`,
  `artifacts.scope.status`, `artifacts.scope.approved_version`,
  `artifacts.scope.latest_version`);
- Specs execution authorization (`artifacts.specifications.execution_authorized`,
  `artifacts.specifications.status`) — Section 16;
- client approval or commercial status of any kind;
- `workflow.current_stage`;
- `repository.working_branch` itself (Section 11 — only `project-init` owns
  that value).

If a caller frames "publish it" as "and mark it approved/authorized", decline
the state-change half of that request and complete only the transport.

---

## 23. Report — PMO ARTIFACT PUBLISH RESULT

On completion of every run (success, `NO_CHANGES_TO_PUBLISH`, or a `BLOCK`,
with only the fields that were actually reached filled in and the failure
code named), emit:

```
PMO ARTIFACT PUBLISH RESULT

Project:
<project name / id from .pmo/project-config.yaml>

Artifact:
<INTENT | SCOPE | SPECS | FEEDBACK | CHANGE_REQUEST>

Artifact Version:
<version / identifier being published>

Source:
<path in the PMO Engine checkout>

Destination:
<path in the managed workspace / target repository>

Source SHA-256:
<hash>

Destination SHA-256:
<hash>

Provider:
<provider>

Repository:
<workspace/repository>

Branch:
<branch>

Branch Existence (remote):
CONFIRMED / NOT_FOUND

Repository Verification:
PASS / BLOCKED (<PMO-PUBLISH-0XX>: <reason>)

Artifact Governance:
PASS / BLOCKED (<PMO-PUBLISH-008>: <reason>)

Files Staged:
<count>

Unrelated Files:
<count>

Commit:
<hash / NOT_CREATED>

Push:
PUBLISHED / NOT_ATTEMPTED / BLOCKED

Remote Verification:
PASS / BLOCKED

Final Result:
PUBLISHED
NO_CHANGES_TO_PUBLISH
BLOCKED (<PMO-PUBLISH-0XX>: <reason>)
```

`Final Result: PUBLISHED` requires `Branch Existence (remote): CONFIRMED`,
`Repository Verification: PASS`, `Artifact Governance: PASS`, a real `Commit`
hash, and `Push: PUBLISHED` with `Remote Verification: PASS` (i.e. the pushed
ref, fetched back, matches the committed hash). `Final Result:
NO_CHANGES_TO_PUBLISH` requires `Branch Existence (remote): CONFIRMED`,
`Repository Verification: PASS`, and every candidate file's
source/destination hashes already matching pre-publish, with `Commit:
NOT_CREATED` and `Push: NOT_ATTEMPTED`. Any other outcome is `BLOCKED` with
the specific `PMO-PUBLISH-0XX` code named — in particular, `Branch Existence
(remote): NOT_FOUND` always yields `Final Result: BLOCKED
(PMO-PUBLISH-014: ...)`, never a fallback publish.

---

## 24. Guardrails — MUST NOT

- MUST NOT assume the PMO Engine's current Git checkout is the Project
  Artifact Repository, and MUST NOT use the Engine's own `git remote` as the
  publishing target (Section 2).
- MUST NOT infer repository or branch identity from the current Git branch,
  conversation history, a similarly-named branch, a provider default,
  `main`/`master`, a previous project's configuration, or anything other than
  `.pmo/project-config.yaml` (Section 4).
- MUST NOT create, orphan, or rename the configured project branch under any
  circumstance — including when it is missing — and MUST NOT treat branch
  provisioning as part of this Skill's job (Sections 3, 5, 7, 8, 9).
- MUST NOT fall back to another branch, another repository, or `main`/`master`
  when the configured branch or repository is unavailable (Section 7).
- MUST NOT hardcode a user-specific filesystem path for the managed
  workspace (Section 9).
- MUST NOT publish any path outside the Section 13 allowlist, and MUST NOT
  create `specs-vX.Y.md` (Section 14).
- MUST NOT publish an artifact whose owning governance does not report PASS,
  and MUST NOT run an authoring skill's write path to force a PASS
  (Section 15).
- MUST NOT change Specs Execution Authorized, or any approval/commercial
  state, as a side effect of publishing (Sections 16, 22).
- MUST NOT set `repository.verified: true` on authentication/reachability
  alone, without a passing exact-branch check (Section 10, Section 22).
- MUST NOT mutate the authoritative PMO Engine source artifact during
  publishing (Section 17).
- MUST NOT create an empty/no-op commit when nothing actually changed
  (Section 18).
- MUST NOT stage or commit a file outside the allowlist, even if it was
  already dirty in the managed workspace before this run (Section 19).
- MUST NOT push with `--force` in any form, or to a branch other than the
  verified `working_branch` (Section 20).
- MUST NOT attempt to bypass, disable, or reconfigure
  `repo-binding-guard.py` or any other existing hook to get a push through
  (Section 20).
- MUST NOT treat `pmo-artifacts` as a required or implied branch-naming
  convention for other projects (Section 12).
- MUST NOT alter or delete the existing Smart Basket `pmo-artifacts` branch,
  create the managed-workspace push-safety hook, execute an actual
  publication, or modify `.pmo/project-config.yaml`, Intent, Scope, Specs,
  approvals, or exports as part of *this* governance-refinement task
  (Section 25) — this Skill file's edit is itself dry.

---

## 25. This task's scope

This edit is a **governance refinement only**, aligning the Skill with the
confirmed production branch-governance model (Section 3). Per the task that
produced it:

- no publishing hook is created here, and `repo-binding-guard.py` is not
  modified;
- no publication is executed;
- `.pmo/project-config.yaml` is not modified;
- Intent, Scope, Specs, approvals, and exports are not modified;
- the existing `pmo-artifacts` branch is not altered or deleted;
- nothing is committed or pushed by virtue of editing this file.

A future task wires a `PreToolUse`/`PostToolUse` hook (analogous to
`repo-binding-guard.py`, but correctly scoped to the managed workspace path
and independently validating provider, workspace, repository, branch, remote
URL, managed workspace, staged files, and push destination — Section 20) and
exercises this Skill end-to-end against a real configured branch (the
verified Bitbucket target `devops-tekrevol/lets-explore-more-specs`, using
whichever branch `project-init` records for a given project — Section 12).

---

## 26. Definition of done

- Repository and branch identity are read only from
  `.pmo/project-config.yaml`, with `project-init` — not this Skill — owning
  branch capture (Sections 4, 11); the managed workspace convention is
  portable and user-path-free (Section 9).
- The configured branch's remote existence is confirmed on every run
  (Section 5) before any other verification; an empty existing branch is a
  valid publish target while a non-existent branch is always blocked
  (Section 6).
- This Skill has no branch-creation authority — no branch, orphan branch,
  alternative-name branch, or `main`/`master` fallback is ever created, even
  when the configured branch is missing (Sections 3, 7, 8, 9).
- All ten Section 10 checks — including exact branch verification — pass
  before anything is copied, and `repository.verified` reflects full
  verification of the **target**, never authentication alone and never the
  Engine.
- `pmo-artifacts` is documented as a one-off manual proof-of-concept, not a
  naming convention future projects must follow (Section 12).
- Only allowlisted paths (Section 13) are ever touched, `specs.md` is the
  only live Specs path (Section 14), and every publishable artifact's owning
  governance already reports PASS (Section 15) without this Skill approving
  anything.
- Every copied file has matching source/destination SHA-256 (Section 17); a
  byte-identical target produces `NO_CHANGES_TO_PUBLISH` with no commit
  (Section 18).
- Only hash-verified, allowlisted files are staged; any unrelated file blocks
  the commit (Section 19); the commit message is deterministic.
- Push targets only the configured provider/workspace/repository/branch, with
  no fallback, no force, and no unauthorised `main`/`master` push
  (Sections 7, 20).
- Every `PMO-PUBLISH-0XX` condition in Section 21 fails closed, and
  `PMO-PUBLISH-014` is defined as `TARGET_BRANCH_NOT_FOUND` with
  DevOps/repository-administrator remediation, never self-remediation.
- No approval, version, execution-authorization, or `working_branch` state
  changes as a side effect of a successful publish (Sections 16, 22).
- The `repo-binding-guard.py` architectural constraint remains documented,
  and the forthcoming dedicated guard's required checks are specified
  (Section 20), without modifying that hook in this task.
- The **PMO ARTIFACT PUBLISH RESULT** report (Section 23) is emitted on every
  run, including blocked ones, and now reports remote branch existence
  explicitly.
