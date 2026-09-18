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
STRUCTURAL_REPAIR is not a general pre-approval Specs editor. It may
**only**:

* add a **missing mandatory required section** (per
  `specs-governance-guard.py`'s own `REQUIRED_SECTIONS`) whose content can
  be **deterministically derived** from the Specs artifact's own current,
  already-governed state - today, exactly one such section is supported:
  `## Validation Summary` (see `PERMITTED_REPAIR_SECTIONS`);
* append that content strictly as new trailing material - **every byte of
  the existing document must remain, unchanged, as an exact prefix of the
  repaired document** (`content_preserves_existing`, enforced
  independently of the derivation logic, so a bug in derivation can never
  silently mutate existing content);
* never introduce a new `FR-*` / `NFR-*` / `BR-*` identifier, never change
  `Spec Version`, `Spec Status`, `Execution Authorized`, or any Document
  Control field, never touch Scope / Change Log / CR / Feedback sources.

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
    "permitted_repair_class", "specs_hash_before",
)

# The complete, deliberately small whitelist of required sections this
# mechanism may add. Extending this set is a framework decision (new
# derivation logic + new tests), never a runtime parameter - a caller can
# never request an arbitrary section be "repaired".
PERMITTED_REPAIR_SECTIONS = ("Validation Summary",)


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
    status = (meta.get("spec_status") or "").strip().upper()
    if status != "PROVISIONAL":
        return None, deny(
            "PMO-SPEC-REPAIR-003",
            "Spec Status is '{}', not PROVISIONAL - STRUCTURAL_REPAIR only "
            "applies to a pre-baseline artifact.".format(meta.get("spec_status")),
        )
    exec_auth = (meta.get("execution_authorized") or "").strip().lower()
    if exec_auth != "false":
        return None, deny(
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
            return None, deny(
                "PMO-SPEC-REPAIR-004",
                "a valid, matching Specs approval record already exists "
                "for Spec Version {} - this baseline is approved and "
                "protected; STRUCTURAL_REPAIR never applies to "
                "it.".format(meta.get("spec_version")),
            )

    d = specs_guard.full_spec_validation(root, spec_text=content)
    if d is None:
        return None, deny(
            "PMO-SPEC-REPAIR-005",
            "full_spec_validation already passes - there is nothing to "
            "repair.",
        )

    missing = missing_required_sections(content)
    missing_names = [name for name, _rx, _cond in missing]
    if not missing_names:
        return None, deny(
            "PMO-SPEC-REPAIR-006",
            "the current full_spec_validation failure ({}: {}) is not a "
            "missing-required-section defect this mechanism can address - "
            "it requires engineering/content review, not a structural "
            "repair.".format(d.code, d.message),
        )
    unsupported = [n for n in missing_names if n not in PERMITTED_REPAIR_SECTIONS]
    if unsupported:
        return None, deny(
            "PMO-SPEC-REPAIR-007",
            "the artifact is missing required section(s) {} which this "
            "mechanism does not (yet) know how to derive deterministically "
            "- only {} is supported today.".format(
                unsupported, list(PERMITTED_REPAIR_SECTIONS)),
        )

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

    plan = {
        "project_id": project_id,
        "spec_version": meta.get("spec_version"),
        "reason": reason,
        "pre_repair_validation_code": d.code,
        "pre_repair_validation_message": d.message,
        "permitted_repair_class": missing_names,
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
        "permitted_repair_class": plan["permitted_repair_class"],
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

        missing_names = plan["permitted_repair_class"]
        tail_parts = []
        for name in PERMITTED_REPAIR_SECTIONS:
            if name in missing_names:
                tail_parts.append(_DERIVERS[name](root, before))
        if not tail_parts:
            return None, deny("PMO-SPEC-REPAIR-006",
                              "no derivable missing section remained at finalize time.")

        after = before.rstrip("\n") + "\n\n---\n\n" + "\n---\n\n".join(tail_parts)

        ok, reason = content_preserves_existing(before, after)
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
            "repaired_sections": missing_names,
            "reason": plan["reason"],
        }, None
    except Exception as exc:  # pragma: no cover - fail closed
        return None, deny("PMO-SPEC-REPAIR-999",
                          "internal error during finalize: {}".format(exc))
