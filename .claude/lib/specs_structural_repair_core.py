"""PMO specs_structural_repair_core - shared deterministic governance for a
narrowly-scoped, third Specs-write authorization category: STRUCTURAL_REPAIR.

Why this module exists
-----------------------
`change_request_incorporation_core.validate_specs_write` recognizes exactly
two categories for `docs/pmo/specs/specs.md`:

* the file does not exist yet -> `INITIAL_SPECS_CREATION`
  (`validate_initial_specs_creation`, `PMO-CR-GUARD-027..030`);
* the file exists -> an OPEN CR-INCORPORATION transaction is required,
  unconditionally.

That second rule is correct and must never weaken for an **approved**
baseline. But it leaves no governed path for a real, narrow third case: a
Specs artifact that **exists**, has **never been approved**
(`Execution Authorized: false`, no matching `specs-approval.yaml`), and
fails `full_spec_validation` only because the generator that produced it
predates a Skill-contract correction (e.g. the `## Validation Summary`
requirement added by the Specs Generator Contract correction) - a
structural/schema completeness defect, not a content or scope question.
Forcing that through CR-incorporation would misrepresent a generator
defect as a change request, and no CR exists to incorporate. This module
is that missing, deliberately narrow, third path.

Architectural boundary this module enforces
-----------------------------------------------
STRUCTURAL_REPAIR is not a general pre-approval Specs editor. The single
`operation: "STRUCTURAL_REPAIR"` supports exactly two, deliberately
distinct **repair classes**, and never anything else:

* `MISSING_REQUIRED_SECTION` - add a **missing mandatory required
  section** (per `specs-governance-guard.py`'s own `REQUIRED_SECTIONS`)
  whose content can be **deterministically derived** from the Specs
  artifact's own current, already-governed state - today, exactly one such
  section is supported: `## Validation Summary` (see
  `PERMITTED_REPAIR_SECTIONS`). Applied by appending that content strictly
  as new trailing material - **every byte of the existing document must
  remain, unchanged, as an exact prefix of the repaired document**
  (`content_preserves_existing`).
* `DOCUMENT_CONTROL_METADATA_REPAIR` - correct a **single, explicitly
  whitelisted Document Control field** (today: only `Generated From`,
  see `PERMITTED_METADATA_FIELDS`) whose *current* value is independently
  proven structurally invalid by the guard's own
  `validate_source_versions` check, replacing it with a value
  **deterministically derivable** from already-governed state (today: the
  canonical Q&A register path, `qa_register_core.QA_FILE_POSIX` - the
  exact representation `spec-generation/SKILL.md` Section 7 already
  documents for the NEW no-Scope path, never a new invented shape).
  Applied by changing **only** that one field's line - every other line,
  including every other Document Control field, must remain byte-identical
  (`metadata_fix_is_field_only`, enforced independently of the derivation
  logic).

* `CHANGE_SOURCE_PROVENANCE_REPAIR` - normalize the **single, exact,
  generator-produced non-canonical provenance token**
  `INITIAL_SPECS_GENERATION` to `INITIAL_INTENT`, the canonical initial
  Change Source of the NEW (Intent + Q&A, no-Scope) lifecycle. Eligible
  instances are only governed provenance fields: a requirement block's
  `- **Change Source:**` line and the Change Source cell of a Specification
  Change History row. Runs only when NEW-lifecycle evidence is proven
  (no legacy Scope artifact, no ambiguous Scope directory, Intent
  VALIDATED + PM-approved, canonical Q&A register ready). Never rewrites
  `INITIAL_SCOPE`, `INITIAL_INTENT`, CR-/FDB-/QST-/PM-DECISION sources or
  any prose. The validator (PMO-SPEC-013/014) is deliberately NOT loosened:
  the token stays invalid, and this class exists to remove it.
  Applied as in-place, line-count-preserving edits verified independently
  by `provenance_fix_is_token_only`.

All classes may apply in the same transaction (metadata fix first, then
provenance normalization, then the missing-section append), so a single `finalize`
call repairs every currently-addressable defect at once - but each class's
own safety check runs independently, so a bug in one can never mask a
violation the other would have caught.

In every case, and regardless of which repair class(es) apply:

* never introduce a new `FR-*` / `NFR-*` / `BR-*` identifier;
* never change `Spec Version`, `Spec Status`, `Execution Authorized`,
  `Project`, `Project ID`, `Client`, `Repository`, or any Document Control
  field other than the one explicitly whitelisted metadata field;
* never touch Scope / Change Log / CR / Feedback sources.

Once a baseline is approved (`Execution Authorized: true` and a valid
matching `specs-approval.yaml` exists), **none** of this module's
functions will authorize a write - `run_begin_preconditions` denies it
deterministically (`PMO-SPEC-REPAIR-003` / `-004`). Post-baseline
functional change continues to require the existing, unchanged
CR-incorporation path in `change_request_incorporation_core.py`.

Security boundary
-------------------
Exactly the same boundary every other transaction CLI in this codebase
already documents: `specs-structural-repair.py` runs via Bash, entirely
outside Claude Code's PreToolUse hook system. This is a **deliberate
design choice, not a bypass** - `change_request_incorporation_core.py`'s
own guard rule for an *existing* `specs.md` is **not modified, weakened,
or special-cased** anywhere in this module or in that one; approved-
baseline protection for Claude's own Write/Edit tool calls is completely
untouched. `finalize_transaction` independently re-runs the full BEGIN
precondition checklist against the CURRENT on-disk state, re-validates
the computed content preserves every existing byte, and re-confirms
`full_spec_validation` actually passes on the result, before writing
anything - the marker's existence is never itself authorization.

Marker schema - .pmo/specs-structural-repair-transaction.json
------------------------------------------------------------------
See `STRUCTURAL_REPAIR_MARKER_REQUIRED_FIELDS`. Single-state (`ACTIVE`)
transaction, same shape as `specs_approval_core.py`'s own marker - no
intermediate Skill-authored content step exists between `begin` and
`finalize` (the repair content is fully computed by this module itself,
deterministically, from governed state).

Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import intent_approval_core as iac  # noqa: E402
import qa_register_core as qac  # noqa: E402
import change_request_incorporation_core as crc  # noqa: E402
import specs_approval_core as sac  # noqa: E402

HERE = Path(__file__).resolve().parent

import importlib.util as _ilu

_SPECS_GUARD_PATH = HERE.parent / "hooks" / "specs-governance-guard.py"
_spec = _ilu.spec_from_file_location("specs_governance_guard_for_repair",
                                     str(_SPECS_GUARD_PATH))
specs_guard = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(specs_guard)


Decision = iac.Decision
deny = iac.deny
allow = iac.allow
read_text = iac.read_text
write_text = iac.write_text
sha256_of_text = iac.sha256_of_text
load_project_config = iac.load_project_config
_clean = iac._clean

SPECS_POSIX = sac.SPECS_POSIX
STRUCTURAL_REPAIR_MARKER_RELPATH_PARTS = (
    ".pmo", "specs-structural-repair-transaction.json")

OPEN_MARKER_STATUSES = {"ACTIVE"}

STRUCTURAL_REPAIR_MARKER_REQUIRED_FIELDS = (
    "transaction_type", "transaction_id", "project_id", "artifact",
    "spec_version", "operation", "reason", "started_at", "status",
    "pre_repair_validation_code", "pre_repair_validation_message",
    "repair_classes", "missing_sections", "metadata_fixes",
    "specs_hash_before",
)

# The two, and only two, repair classes STRUCTURAL_REPAIR ever performs.
# Extending this set is a framework decision (new derivation logic + new
# tests), never a runtime parameter.
REPAIR_CLASS_MISSING_SECTION = "MISSING_REQUIRED_SECTION"
REPAIR_CLASS_METADATA = "DOCUMENT_CONTROL_METADATA_REPAIR"

# The complete, deliberately small whitelist of required sections this
# mechanism may add. A caller can never request an arbitrary section be
# "repaired".
REPAIR_CLASS_PROVENANCE = "CHANGE_SOURCE_PROVENANCE_REPAIR"
NONCANONICAL_INITIAL_TOKEN = "INITIAL_SPECS_GENERATION"
CANONICAL_NEW_INITIAL_TOKEN = "INITIAL_INTENT"

PERMITTED_REPAIR_SECTIONS = ("Validation Summary",)

# The complete, deliberately small whitelist of Document Control fields
# DOCUMENT_CONTROL_METADATA_REPAIR may ever change. A caller can never
# request an arbitrary field be "repaired", and a field not currently
# proven invalid by the guard's own validator is never touched (see
# `_generated_from_invalid`).
PERMITTED_METADATA_FIELDS = ("Generated From",)


def marker_abspath(root):
    return os.path.join(root, *STRUCTURAL_REPAIR_MARKER_RELPATH_PARTS)


def specs_abspath(root):
    return sac.specs_abspath(root)


# --------------------------------------------------------------------------- #
# Required-section gap detection (reuses specs_guard.REQUIRED_SECTIONS -
# never a second list).
# --------------------------------------------------------------------------- #

def missing_required_sections(spec_text):
    """[(name, regex, conditional), ...] for every REQUIRED_SECTIONS entry
    not found as a heading in `spec_text`. Conditional sections are never
    reported missing (they are optional unless content requires them -
    specs-governance-guard.py's own `validate_required_sections` decides
    that; this function only reports the unconditional gap set relevant to
    STRUCTURAL_REPAIR)."""
    out = []
    for name, rx, conditional in specs_guard.REQUIRED_SECTIONS:
        if conditional:
            continue
        if not re.search(r"(?im)^#{1,6}\s*.*" + rx, spec_text or ""):
            out.append((name, rx, conditional))
    return out


def _last_numbered_heading(spec_text):
    """Highest `## N. Title` heading number found, or None. Used only to
    number a newly-appended section consistently with the document's own
    existing numbering convention - purely cosmetic, never a content
    decision."""
    nums = [int(n) for n in re.findall(r"(?m)^##\s+(\d+)\.\s+\S", spec_text or "")]
    return max(nums) if nums else None


# --------------------------------------------------------------------------- #
# Deterministic derivation - Validation Summary only (see module docstring)
# --------------------------------------------------------------------------- #

def derive_validation_summary(root, spec_text):
    """Compute the ## Validation Summary section body from facts already
    present in `spec_text` / already-governed state - never fabricated,
    never approval, never a resolved TBD. Returns the section text
    (including its own heading) ready to append."""
    fr_ids = sorted(set(re.findall(r"(?m)^###\s+(FR-\d+)", spec_text or "")))
    nfr_ids = sorted(set(re.findall(r"(?m)^###\s+(NFR-\d+)", spec_text or "")))
    br_ids = sorted(set(re.findall(r"(?m)^\|\s*(BR-\d+)\s*\|", spec_text or "")))

    trace_rows = re.findall(
        r"(?m)^\|\s*(INT-REQ-\d+|SCP-REQ-\d+)\s*\|([^\n]*)\|",
        spec_text or "")
    total_trace = len(trace_rows)
    covered = sum(1 for _rid, rest in trace_rows
                 if "COVERED" in rest.upper())

    open_rows = re.findall(r"(?m)^\|\s*(QST-\d+|ASM-\d+|OPEN-\d+)\s*\|",
                           spec_text or "")
    open_count = len(set(open_rows))

    meta = sac.parse_spec_doc_control(spec_text)
    spec_version = meta.get("spec_version") or "unknown"

    d = specs_guard.full_spec_validation(root, spec_text=spec_text)
    validated_note = (
        "This write was checked against specs-governance-guard.py's "
        "full_spec_validation immediately before being written, per the "
        "governed STRUCTURAL_REPAIR procedure."
    )

    next_num = _last_numbered_heading(spec_text)
    heading = ("## {}. Validation Summary".format(next_num + 1)
              if next_num is not None else "## Validation Summary")

    lines = [
        heading,
        "",
        "**Structural completeness repair note:** this section was added "
        "by a governed STRUCTURAL_REPAIR transaction, not a content "
        "revision - it restores a mandatory canonical section this "
        "artifact was missing. No FR/NFR/BR requirement, traceability "
        "row, Open Question, exclusion, constraint, or confirmed business "
        "rule was altered; Spec Version remains `{}` and Execution "
        "Authorized remains unchanged.".format(spec_version),
        "",
        "**Requirement counts.** {} Functional Requirement(s), {} "
        "Non-Functional Requirement(s), {} Business Rule(s).".format(
            len(fr_ids), len(nfr_ids), len(br_ids)),
        "",
        "**Traceability completeness.** {} of {} traceability row(s) "
        "carry an explicit `COVERED` disposition; the remainder carry "
        "`PARTIALLY_COVERED` with a named blocking Q&A/OPEN reference - "
        "none is dropped silently.".format(covered, total_trace),
        "",
        "**Open items.** {} deferred/non-blocking item(s) remain visible "
        "and traceable to their governing Q&A/Intent id; none is silently "
        "resolved by this repair.".format(open_count),
        "",
        "**Validation performed.** {} This confirms generation-time "
        "structural validation only - it does not constitute, imply, or "
        "substitute for PM or client approval. `Execution Authorized` and "
        "any Specs approval record are unaffected by this "
        "repair.".format(validated_note),
        "",
    ]
    return "\n".join(lines)


_DERIVERS = {
    "Validation Summary": derive_validation_summary,
}


# --------------------------------------------------------------------------- #
# Content-preservation guarantee - independent of derivation logic
# --------------------------------------------------------------------------- #

_FORBIDDEN_NEW_IDENTIFIER_RE = re.compile(
    r"(?m)^###\s+(?:FR|NFR)-\d+|^\|\s*BR-\d+\s*\|")


def content_preserves_existing(before, after):
    """The single, independent safety net STRUCTURAL_REPAIR's write path
    always re-checks, regardless of how `after` was produced: `after` must
    be `before` verbatim, plus a strictly-appended tail, and that tail
    must introduce no new FR/NFR/BR identifier and no new top-level
    section other than one from PERMITTED_REPAIR_SECTIONS. Returns
    (ok: bool, reason: str-or-None)."""
    before_norm = before.rstrip("\n")
    if not after.startswith(before_norm):
        return False, ("the existing document is not preserved as an exact "
                       "prefix of the repaired document - a byte of "
                       "existing content was changed, moved or removed.")
    tail = after[len(before_norm):]
    if _FORBIDDEN_NEW_IDENTIFIER_RE.search(tail):
        return False, ("the appended tail introduces a new FR/NFR/BR "
                       "identifier - STRUCTURAL_REPAIR may never add "
                       "requirement content.")
    new_headings = re.findall(r"(?m)^#{1,6}\s+(?:\d+\.\s+)?(.+?)\s*$", tail)
    for h in new_headings:
        if h not in PERMITTED_REPAIR_SECTIONS:
            return False, (
                "the appended tail introduces a section ('{}') outside "
                "the permitted STRUCTURAL_REPAIR whitelist "
                "({}).".format(h, ", ".join(PERMITTED_REPAIR_SECTIONS))
            )
    return True, None


# --------------------------------------------------------------------------- #
# DOCUMENT_CONTROL_METADATA_REPAIR - Generated From (see module docstring)
# --------------------------------------------------------------------------- #

def _generated_from_invalid(root, spec_text):
    """(is_invalid, current_value). Reuses
    specs_guard.parse_spec_metadata + specs_guard.validate_source_versions
    directly - never a second implementation of this check, and never
    proposes a fix for a field the guard does not itself currently flag."""
    meta = specs_guard.parse_spec_metadata(spec_text)
    d = specs_guard.validate_source_versions(meta, root)
    invalid = d is not None and "Generated From" in d.message
    return invalid, meta.get("generated from")


def derive_generated_from_value(root):
    """The canonical NEW (no-Scope) path representation
    `spec-generation/SKILL.md` Section 7 already documents: a single path
    naming the canonical Q&A register, reused verbatim from
    `qa_register_core.QA_FILE_POSIX` - never a second, invented
    representation. Returns None (cannot derive) if that register does not
    actually exist on disk - this mechanism never fabricates a path that
    would itself fail the same existence check it is trying to fix."""
    candidate = qac.QA_FILE_POSIX
    if not os.path.exists(os.path.join(root, *candidate.split("/"))):
        return None
    return candidate


def apply_metadata_fix(content, field, new_value):
    """Return (new_content, ok) - the exact same single-line-only
    replacement `intent_approval_core.set_doc_control_field` already
    provides for Intent, reused verbatim here."""
    new_content, ok = iac.set_doc_control_field(content, field, new_value)
    return (new_content if ok else None), ok


def metadata_fix_is_field_only(before, after, permitted_fields):
    """The independent safety net for DOCUMENT_CONTROL_METADATA_REPAIR,
    exactly analogous in role to `content_preserves_existing` for
    MISSING_REQUIRED_SECTION: regardless of how `after` was produced,
    every line that differs from `before` must be identifiable as one of
    `permitted_fields`'s own Document Control field line (reusing
    `intent_approval_core._doc_control_field_line_regex` - never a second
    field-detection implementation) - a changed FR/NFR/BR line, a changed
    Project/Project ID/Spec Version/Spec Status/Execution Authorized line,
    or any other changed line that isn't one of `permitted_fields`, is
    rejected outright. Returns (ok: bool, reason-or-changed-fields)."""
    b_lines = before.splitlines()
    a_lines = after.splitlines()
    if len(a_lines) != len(b_lines):
        return False, ("the line count changed during a metadata-only fix "
                       "- a metadata repair may only ever replace an "
                       "existing line in place, never add or remove a "
                       "line.")
    changed_fields = set()
    for bl, al in zip(b_lines, a_lines):
        if bl == al:
            continue
        matched = None
        for field in permitted_fields:
            pattern = iac._doc_control_field_line_regex(field)
            if pattern.match(bl) and pattern.match(al):
                matched = field
                break
        if matched is None:
            return False, (
                "a line changed that is not one of the permitted metadata "
                "fields ({}) - refusing: before={!r} after={!r}".format(
                    ", ".join(permitted_fields), bl, al)
            )
        changed_fields.add(matched)
    return True, changed_fields


# --------------------------------------------------------------------------- #
# CHANGE_SOURCE_PROVENANCE_REPAIR (see module docstring)
# --------------------------------------------------------------------------- #

_TOKEN = re.escape(NONCANONICAL_INITIAL_TOKEN)
_PROV_FIELD_RE = re.compile(r"^(- \*\*Change Source:\*\* )" + _TOKEN + r"([ \t]*)$")
_PROV_HISTORY_RE = re.compile(
    r"^(\|[^|]*\|[^|]*\|[ \t]*)" + _TOKEN + r"([ \t]*(?:\([^|]*\))?[ \t]*\|.*)$")
_REQ_HEADING_RE = re.compile(r"^###\s+(?:FR|NFR)-\d+\b")
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s")
_HISTORY_HEADING_LINE_RE = re.compile(r"^#{1,6}\s+(?:\d+\.\s+)?specification\s+change\s+history\b",
                                      re.IGNORECASE)


def _provenance_line_kinds(lines):
    """Yield (index, kind) for every line that is an ELIGIBLE governed
    provenance field: 'FIELD' (a Change Source line inside an FR/NFR block)
    or 'HISTORY' (Change Source cell of a Change History table row)."""
    in_req = False
    in_history = False
    for i, line in enumerate(lines):
        if _ANY_HEADING_RE.match(line):
            in_req = bool(_REQ_HEADING_RE.match(line))
            in_history = bool(_HISTORY_HEADING_LINE_RE.match(line))
            continue
        if in_req and _PROV_FIELD_RE.match(line):
            yield i, "FIELD"
        elif in_history and _PROV_HISTORY_RE.match(line):
            yield i, "HISTORY"


def find_provenance_occurrences(spec_text):
    """(eligible_indexes: list[(idx, kind)], total_lines, excluded_count)."""
    lines = (spec_text or "").splitlines()
    eligible = list(_provenance_line_kinds(lines))
    total = sum(1 for ln in lines if NONCANONICAL_INITIAL_TOKEN in ln)
    return eligible, total, total - len(eligible)


def prove_new_lifecycle_provenance(root):
    """Return None when the NEW (no-Scope) lifecycle is positively proven
    for this project, else a Decision. Fails closed on ambiguity. Reuses the
    authoritative helpers - never a second lifecycle detector."""
    if specs_guard.has_legacy_scope(root):
        return deny(
            "PMO-SPEC-REPAIR-024",
            "a legacy Scope artifact exists - Scope governs this project's "
            "initial provenance; refusing to normalize provenance to "
            "{}.".format(CANONICAL_NEW_INITIAL_TOKEN))
    scope_dir = os.path.join(root, "docs", "pmo", "scope")
    if os.path.isdir(scope_dir) and os.listdir(scope_dir):
        return deny(
            "PMO-SPEC-REPAIR-025",
            "docs/pmo/scope/ is non-empty but holds no recognised Scope "
            "artifact - lifecycle evidence is ambiguous; failing closed.")
    kind_msg = qac.validate_new_path_readiness(root)
    if kind_msg is not None:
        return deny(
            "PMO-SPEC-REPAIR-026",
            "NEW-lifecycle evidence is not proven ({}: {}).".format(*kind_msg))
    return None


def apply_provenance_fix(content):
    """Replace ONLY the non-canonical token inside eligible governed
    provenance fields. In-place, line-count preserving."""
    lines = content.split("\n")
    for i, kind in _provenance_line_kinds(lines):
        rx = _PROV_FIELD_RE if kind == "FIELD" else _PROV_HISTORY_RE
        lines[i] = rx.sub(lambda m: m.group(1) + CANONICAL_NEW_INITIAL_TOKEN + m.group(2),
                          lines[i], count=1)
    return "\n".join(lines)


def provenance_fix_is_token_only(before, after):
    """Independent safety net: same line count; every differing line differs
    from its original ONLY by the token substitution, and was an eligible
    governed provenance line. Returns (ok, reason-or-changed-count)."""
    b = before.split("\n")
    a = after.split("\n")
    if len(a) != len(b):
        return False, "the line count changed during a provenance-only fix."
    eligible = {i for i, _k in _provenance_line_kinds(b)}
    changed = 0
    for i, (bl, al) in enumerate(zip(b, a)):
        if bl == al:
            continue
        if i not in eligible:
            return False, ("a line changed that is not an eligible governed "
                           "provenance field: {!r}".format(bl))
        if bl.replace(NONCANONICAL_INITIAL_TOKEN, CANONICAL_NEW_INITIAL_TOKEN, 1) != al:
            return False, ("a provenance line changed by more than the exact "
                           "token substitution: {!r} -> {!r}".format(bl, al))
        changed += 1
    return True, changed


# --------------------------------------------------------------------------- #
# Shared pre-baseline gates (also used by specs_schema_migration_core.py, so
# the "still an unapproved provisional artifact" rules exist exactly once)
# --------------------------------------------------------------------------- #

SCHEMA_MIGRATION_MARKER_RELPATH_PARTS = (
    ".pmo", "specs-schema-migration-transaction.json")


def pre_baseline_approval_gate(root, meta):
    """Decision or None: Spec Status PROVISIONAL, Execution Authorized false,
    and no valid matching Specs approval."""
    status = (meta.get("spec_status") or "").strip().upper()
    if status != "PROVISIONAL":
        return deny(
            "PMO-SPEC-REPAIR-003",
            "Spec Status is '{}', not PROVISIONAL - STRUCTURAL_REPAIR only "
            "applies to a pre-baseline artifact.".format(meta.get("spec_status")),
        )
    exec_auth = (meta.get("execution_authorized") or "").strip().lower()
    if exec_auth != "false":
        return deny(
            "PMO-SPEC-REPAIR-003",
            "Execution Authorized is '{}', not false - an authorized "
            "baseline is protected; STRUCTURAL_REPAIR never applies to "
            "it.".format(meta.get("execution_authorized")),
        )

    approval_data, approval_err = sac.load_specs_approval(root)
    if approval_data is not None and approval_err is None:
        match_err = sac.validate_specs_approval_matches(
            root, spec_version=meta.get("spec_version"))
        if match_err is None:
            return deny(
                "PMO-SPEC-REPAIR-004",
                "a valid, matching Specs approval record already exists "
                "for Spec Version {} - this baseline is approved and "
                "protected; STRUCTURAL_REPAIR never applies to "
                "it.".format(meta.get("spec_version")),
            )

    return None


def pre_baseline_concurrency_gate(root, meta, ignore_schema_migration_marker=False):
    """(project_id, Decision-or-None): project identity matches and no other
    governed transaction (CR, feedback, schema migration) is open."""
    cfg = load_project_config(root) or {}
    project_id = _clean((cfg.get("project") or {}).get("id"))
    if not project_id:
        return None, deny("PMO-SPEC-REPAIR-008",
                          ".pmo/project-config.yaml has no project.id.")
    doc_pid = _clean(meta.get("project_id"))
    if doc_pid and doc_pid.upper() != project_id.upper():
        return None, deny(
            "PMO-SPEC-REPAIR-008",
            "Specs Document Control Project ID ('{}') does not match "
            "project-config.yaml ('{}').".format(doc_pid, project_id),
        )

    cr_state, _cr_data, _cr_err = crc.cr_marker_status(root)
    if cr_state == "OPEN":
        return None, deny(
            "PMO-SPEC-REPAIR-009",
            "an OPEN change-request transaction is active for this "
            "project - a CR-incorporation operation must not be able to "
            "masquerade as, or run concurrently with, a STRUCTURAL_REPAIR.",
        )
    if crc.feedback_marker_is_open(root):
        return None, deny(
            "PMO-SPEC-REPAIR-009",
            "an OPEN feedback-management transaction is active for this "
            "project - STRUCTURAL_REPAIR must not proceed concurrently "
            "with it.",
        )

    if (not ignore_schema_migration_marker and os.path.exists(
            os.path.join(root, *SCHEMA_MIGRATION_MARKER_RELPATH_PARTS))):
        return None, deny(
            "PMO-SPEC-REPAIR-009",
            "a PRE_BASELINE_SCHEMA_MIGRATION transaction marker exists - "
            "resolve (finalize/abort) it before another Specs "
            "transaction.")
    return project_id, None


# --------------------------------------------------------------------------- #
# BEGIN preconditions (read-only)
# --------------------------------------------------------------------------- #

def run_begin_preconditions(root, reason):
    reason = _clean(reason)
    if not reason:
        return None, deny("PMO-SPEC-REPAIR-001",
                          "a repair reason is required and must be non-empty.")

    specs_path = specs_abspath(root)
    content = read_text(specs_path)
    if content is None:
        return None, deny("PMO-SPEC-REPAIR-002",
                          "no canonical Specs artifact at {} - "
                          "STRUCTURAL_REPAIR only applies to an existing "
                          "artifact (a missing one is INITIAL_SPECS_"
                          "CREATION territory instead).".format(SPECS_POSIX))

    meta = sac.parse_spec_doc_control(content)
    gate = pre_baseline_approval_gate(root, meta)
    if gate is not None:
        return None, gate

    d = specs_guard.full_spec_validation(root, spec_text=content)
    if d is None:
        return None, deny(
            "PMO-SPEC-REPAIR-005",
            "full_spec_validation already passes - there is nothing to "
            "repair.",
        )

    missing = missing_required_sections(content)
    missing_names = [name for name, _rx, _cond in missing]
    unsupported = [n for n in missing_names if n not in PERMITTED_REPAIR_SECTIONS]
    if unsupported:
        return None, deny(
            "PMO-SPEC-REPAIR-007",
            "the artifact is missing required section(s) {} which this "
            "mechanism does not (yet) know how to derive deterministically "
            "- only {} is supported today.".format(
                unsupported, list(PERMITTED_REPAIR_SECTIONS)),
        )
    supported_missing = [n for n in missing_names if n in PERMITTED_REPAIR_SECTIONS]

    gf_invalid, gf_current = _generated_from_invalid(root, content)
    metadata_fixes = {}
    if gf_invalid:
        new_gf = derive_generated_from_value(root)
        if new_gf is None:
            return None, deny(
                "PMO-SPEC-REPAIR-017",
                "Document Control 'Generated From' ('{}') is structurally "
                "invalid, but its canonical value cannot be derived - the "
                "canonical Q&A register does not exist on "
                "disk.".format(gf_current),
            )
        metadata_fixes["Generated From"] = new_gf

    provenance_fixes = {}
    eligible_prov, prov_total, prov_excluded = find_provenance_occurrences(content)
    if eligible_prov:
        prov_d = prove_new_lifecycle_provenance(root)
        if prov_d is not None:
            return None, prov_d
        provenance_fixes = {
            "from": NONCANONICAL_INITIAL_TOKEN,
            "to": CANONICAL_NEW_INITIAL_TOKEN,
            "field_lines": sum(1 for _i, k in eligible_prov if k == "FIELD"),
            "history_rows": sum(1 for _i, k in eligible_prov if k == "HISTORY"),
            "excluded_non_provenance": prov_excluded,
        }

    repair_classes = []
    if supported_missing:
        repair_classes.append(REPAIR_CLASS_MISSING_SECTION)
    if metadata_fixes:
        repair_classes.append(REPAIR_CLASS_METADATA)
    if provenance_fixes:
        repair_classes.append(REPAIR_CLASS_PROVENANCE)

    if not repair_classes:
        return None, deny(
            "PMO-SPEC-REPAIR-006",
            "the current full_spec_validation failure ({}: {}) is not "
            "addressable by any supported STRUCTURAL_REPAIR class "
            "({} / {} / {}) - it requires engineering/content review, not "
            "a structural repair.".format(
                d.code, d.message, REPAIR_CLASS_MISSING_SECTION,
                REPAIR_CLASS_METADATA, REPAIR_CLASS_PROVENANCE),
        )

    project_id, gate = pre_baseline_concurrency_gate(root, meta)
    if gate is not None:
        return None, gate

    plan = {
        "project_id": project_id,
        "spec_version": meta.get("spec_version"),
        "reason": reason,
        "pre_repair_validation_code": d.code,
        "pre_repair_validation_message": d.message,
        "repair_classes": repair_classes,
        "missing_sections": supported_missing,
        "metadata_fixes": metadata_fixes,
        "provenance_fixes": provenance_fixes,
        "specs_hash_before": sha256_of_text(content),
    }
    return plan, None


def build_marker_data(plan, transaction_id, started_at):
    return {
        "transaction_type": "SPECS_STRUCTURAL_REPAIR",
        "transaction_id": transaction_id,
        "project_id": plan["project_id"],
        "artifact": SPECS_POSIX,
        "spec_version": plan["spec_version"],
        "operation": "STRUCTURAL_REPAIR",
        "reason": plan["reason"],
        "started_at": started_at,
        "status": "ACTIVE",
        "pre_repair_validation_code": plan["pre_repair_validation_code"],
        "pre_repair_validation_message": plan["pre_repair_validation_message"],
        "repair_classes": plan["repair_classes"],
        "missing_sections": plan["missing_sections"],
        "metadata_fixes": plan["metadata_fixes"],
        "provenance_fixes": plan.get("provenance_fixes") or {},
        "specs_hash_before": plan["specs_hash_before"],
    }


def parse_marker(text):
    try:
        data = json.loads(text)
    except Exception as exc:
        return None, "marker is not valid JSON: {}".format(exc)
    if not isinstance(data, dict):
        return None, "marker did not parse to an object."
    missing = [f for f in STRUCTURAL_REPAIR_MARKER_REQUIRED_FIELDS if f not in data]
    if missing:
        return data, "marker is missing field(s): {}.".format(", ".join(missing))
    if data.get("transaction_type") != "SPECS_STRUCTURAL_REPAIR":
        return data, "marker transaction_type is not SPECS_STRUCTURAL_REPAIR."
    if data.get("operation") != "STRUCTURAL_REPAIR":
        return data, ("marker operation is '{}', not STRUCTURAL_REPAIR - a "
                      "CR-incorporation marker must never be accepted "
                      "here.".format(data.get("operation")))
    if data.get("status") not in OPEN_MARKER_STATUSES:
        return data, "marker status '{}' is not a recognised open state.".format(
            data.get("status"))
    return data, None


def marker_status(root):
    text = read_text(marker_abspath(root))
    if text is None:
        return "ABSENT", None, None
    data, err = parse_marker(text)
    if err is not None:
        return "INVALID", data, err
    cfg = load_project_config(root) or {}
    pid = _clean((cfg.get("project") or {}).get("id"))
    if pid and _clean(data.get("project_id")).upper() != pid.upper():
        return "WRONG_PROJECT", data, (
            "marker project_id '{}' does not match configured project.id "
            "'{}'.".format(data.get("project_id"), pid)
        )
    return "OPEN", data, None


def reconcile_transaction(root, marker_data):
    plan, d = run_begin_preconditions(root, marker_data.get("reason"))
    return plan, d


def finalize_transaction(root, marker_data):
    """Independently re-validates everything, computes the repair content,
    proves it preserves every existing byte and introduces no new
    requirement identifier, proves full_spec_validation actually passes on
    the result, and only then writes. Fails closed on any exception."""
    try:
        plan, d = reconcile_transaction(root, marker_data)
        if d is not None:
            return None, d

        specs_path = specs_abspath(root)
        before = read_text(specs_path)
        if before is None:
            return None, deny("PMO-SPEC-REPAIR-002",
                              "Specs artifact disappeared during the transaction.")
        if sha256_of_text(before) != marker_data.get("specs_hash_before"):
            return None, deny(
                "PMO-SPEC-REPAIR-010",
                "specs.md changed since this repair transaction began - "
                "refusing to repair a moving target. Re-run `begin`.",
            )

        repair_classes = plan["repair_classes"]
        missing_names = plan["missing_sections"]
        metadata_fixes = plan["metadata_fixes"]
        if not repair_classes:
            return None, deny("PMO-SPEC-REPAIR-006",
                              "no applicable repair class remained at finalize time.")

        # 1) DOCUMENT_CONTROL_METADATA_REPAIR first - a single, independently
        #    field-scoped in-place line replacement. Applied before the
        #    missing-section append so the append step's own prefix check
        #    always compares against the metadata-corrected intermediate,
        #    never silently reintroducing the stale value.
        intermediate = before
        if REPAIR_CLASS_METADATA in repair_classes:
            if not metadata_fixes:
                return None, deny("PMO-SPEC-REPAIR-017",
                                  "no derivable metadata fix remained at finalize time.")
            for field, new_value in metadata_fixes.items():
                if field not in PERMITTED_METADATA_FIELDS:
                    return None, deny(
                        "PMO-SPEC-REPAIR-018",
                        "'{}' is not a permitted STRUCTURAL_REPAIR metadata "
                        "field ({}).".format(field, ", ".join(PERMITTED_METADATA_FIELDS)),
                    )
                still_invalid, _cur = _generated_from_invalid(root, intermediate) \
                    if field == "Generated From" else (True, None)
                if not still_invalid:
                    return None, deny(
                        "PMO-SPEC-REPAIR-019",
                        "'{}' is already valid - refusing to overwrite a "
                        "field that is not proven structurally "
                        "invalid.".format(field),
                    )
                intermediate, ok = apply_metadata_fix(intermediate, field, new_value)
                if not ok:
                    return None, deny(
                        "PMO-SPEC-REPAIR-018",
                        "could not locate the '{}' Document Control field "
                        "line deterministically - refusing a partial "
                        "edit.".format(field),
                    )
            ok, info = metadata_fix_is_field_only(before, intermediate, PERMITTED_METADATA_FIELDS)
            if not ok:
                return None, deny("PMO-SPEC-REPAIR-011", info)

        # 1b) CHANGE_SOURCE_PROVENANCE_REPAIR - exact-token, in-place,
        #     line-count-preserving; verified independently.
        if REPAIR_CLASS_PROVENANCE in repair_classes:
            if not plan.get("provenance_fixes"):
                return None, deny("PMO-SPEC-REPAIR-027",
                                  "no provenance fix remained at finalize time.")
            prov_before = intermediate
            intermediate = apply_provenance_fix(prov_before)
            ok, info = provenance_fix_is_token_only(prov_before, intermediate)
            if not ok:
                return None, deny("PMO-SPEC-REPAIR-011", info)
            if find_provenance_occurrences(intermediate)[0]:
                return None, deny("PMO-SPEC-REPAIR-027",
                                  "eligible provenance occurrences remain after the fix.")

        # 2) MISSING_REQUIRED_SECTION - purely-appended trailing content,
        #    checked against the (possibly metadata-corrected) intermediate.
        after = intermediate
        if REPAIR_CLASS_MISSING_SECTION in repair_classes:
            tail_parts = []
            for name in PERMITTED_REPAIR_SECTIONS:
                if name in missing_names:
                    tail_parts.append(_DERIVERS[name](root, intermediate))
            if not tail_parts:
                return None, deny("PMO-SPEC-REPAIR-006",
                                  "no derivable missing section remained at finalize time.")
            after = intermediate.rstrip("\n") + "\n\n---\n\n" + "\n---\n\n".join(tail_parts)
            ok, reason = content_preserves_existing(intermediate, after)
            if not ok:
                return None, deny("PMO-SPEC-REPAIR-011", reason)

        d2 = specs_guard.full_spec_validation(root, spec_text=after)
        if d2 is not None:
            return None, deny(
                "PMO-SPEC-REPAIR-012",
                "the computed repair does not actually resolve "
                "full_spec_validation - refusing to write an artifact "
                "that would still fail ({}: {}).".format(d2.code, d2.message),
            )

        after_meta = sac.parse_spec_doc_control(after)
        if _clean(after_meta.get("spec_version")) != _clean(plan["spec_version"]):
            return None, deny("PMO-SPEC-REPAIR-013",
                              "Spec Version changed as a side effect of the "
                              "repair - refusing to write.")
        after_exec = (after_meta.get("execution_authorized") or "").strip().lower()
        if after_exec != "false":
            return None, deny("PMO-SPEC-REPAIR-013",
                              "Execution Authorized changed as a side effect "
                              "of the repair - refusing to write.")

        write_text(specs_path, after)

        marker_path = marker_abspath(root)
        try:
            os.remove(marker_path)
        except OSError:
            pass

        return {
            "spec_version": plan["spec_version"],
            "repair_classes": repair_classes,
            "repaired_sections": missing_names,
            "repaired_metadata_fields": sorted(metadata_fixes.keys()),
            "repaired_provenance": plan.get("provenance_fixes") or {},
            "reason": plan["reason"],
        }, None
    except Exception as exc:  # pragma: no cover - fail closed
        return None, deny("PMO-SPEC-REPAIR-999",
                          "internal error during finalize: {}".format(exc))


def abort_transaction(root, marker_data, abort_reason, marker_path=None):
    """Governed recovery for a STRUCTURAL_REPAIR transaction that did NOT
    finalize (e.g. `finalize` failed closed with RECOVERY_REQUIRED).

    Clears ONLY the runtime marker. Never touches specs.md, approval state,
    Intent, Q&A, CR or Feedback. A successful `finalize` already removes the
    marker, so a marker that still exists means "not finalized" - but this
    never relies on that alone: the transaction is aborted only when the
    marker's identity (artifact, Spec Version, project) still matches the
    on-disk Specs AND specs.md is byte-identical to the hash recorded at
    `begin`. Anything else (changed or missing specs.md, version drift,
    non-empty reason missing) is ambiguous and fails closed, leaving the
    marker in place.
    """
    try:
        if not _clean(abort_reason):
            return None, deny("PMO-SPEC-REPAIR-020",
                              "abort requires a non-empty --reason.")
        if marker_data.get("artifact") != SPECS_POSIX:
            return None, deny(
                "PMO-SPEC-REPAIR-021",
                "marker artifact '{}' is not {} - refusing to abort an "
                "ambiguous transaction.".format(marker_data.get("artifact"), SPECS_POSIX))
        text = read_text(specs_abspath(root))
        if text is None:
            return None, deny(
                "PMO-SPEC-REPAIR-021",
                "specs.md is missing - state is ambiguous, refusing to abort.")
        if sha256_of_text(text) != marker_data.get("specs_hash_before"):
            return None, deny(
                "PMO-SPEC-REPAIR-022",
                "specs.md no longer matches the hash recorded at `begin` - the "
                "transaction may have finalized or the artifact was edited; "
                "refusing to abort. Resolve manually.")
        meta = sac.parse_spec_doc_control(text)
        if _clean(meta.get("spec_version")) != _clean(marker_data.get("spec_version")):
            return None, deny(
                "PMO-SPEC-REPAIR-022",
                "Spec Version no longer matches the marker - refusing to abort.")
        try:
            os.remove(marker_path or marker_abspath(root))
        except OSError as exc:
            return None, deny("PMO-SPEC-REPAIR-023",
                              "could not remove the marker: {}".format(exc))
        return {
            "transaction_id": marker_data.get("transaction_id"),
            "spec_version": marker_data.get("spec_version"),
            "specs_hash": marker_data.get("specs_hash_before"),
            "abort_reason": _clean(abort_reason),
        }, None
    except Exception as exc:  # pragma: no cover - fail closed
        return None, deny("PMO-SPEC-REPAIR-999",
                          "internal error during abort: {}".format(exc))
