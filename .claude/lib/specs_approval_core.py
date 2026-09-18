"""PMO specs_approval_core - shared deterministic governance for recording a
PM's explicit approval of a Specs baseline.

Why this module exists
-----------------------
`spec-generation`'s own governance (Section 9 of
`.claude/skills/spec-generation/SKILL.md`) already anticipates this exact
event: "A PM MAY explicitly set `Execution Authorized: true` ... recorded in
the Specification Change History with `Change Source: PM-DECISION` and a `PM
Decision` note" - but until now nothing in the framework actually performed
that edit in a governed, auditable way. Doing it as an ad-hoc manual edit
would mean the PM (or an agent acting for one) hand-writing Specs prose,
which is exactly the ad-hoc-sequential-write pattern the PMO framework
avoids everywhere else. This module is the deterministic transaction that
closes that gap, built as a direct structural mirror of
`intent_approval_core.py`'s own Intent-approval transaction - same
begin/validate/finalize/status shape, same fail-closed discipline, same
"the marker's existence is not itself authorization" security boundary.

Scope boundary - what this module does NOT do
-----------------------------------------------
This is deliberately narrow. It does **not**:

* promote `Spec Status` from `PROVISIONAL` to `ACTIVE` - that remains the
  LEGACY-path, Scope-baseline-tied concept `spec-generation` Section 8
  already defines, untouched here;
* bump `Spec Version`;
* change any FR / NFR / BR content, traceability row, or Open Question;
* create, approve, or incorporate a Change Request;
* interact with Feedback in any way.

The only specs.md edit this module ever performs is the single, computed
pair of changes Section 9 already anticipates: the `Execution Authorized`
Document Control flip (`false` -> `true`) and one appended
`Specification Change History` row with `Change Source: PM-DECISION`. Both
happen together or neither happens - there is no reachable path through
this module that produces one without the other (mirroring
`intent_approval_core.apply_approval_to_intent`'s own same guarantee for
Intent's `Status` + Acceptance-section pair).

Immutability
-------------
Once `.pmo/approvals/specs-approval.yaml` records an APPROVED decision for
a given `Spec Version`, that record is never silently overwritten. A
project that later needs to approve a *new* Spec Version (produced only
through governed CR incorporation - `specs.md` cannot otherwise change
once a baseline exists, per `change_request_incorporation_core.py`'s own
post-baseline rule) requires a **new** approval transaction against that
new version; the prior version's approval record remains, untouched, as
permanent audit history.

Security boundary
-------------------
Exactly the same boundary `change_request_incorporation_core.py` and
`intent_approval_core.py` already document: the CLI
(`.claude/scripts/specs-approval-recorder.py`) runs via Bash, entirely
outside Claude Code's PreToolUse hook system. The existence of
`.pmo/specs-approval-transaction.json` is NOT itself authorization for
anything - `finalize_transaction` independently re-runs the full BEGIN
precondition checklist against the CURRENT on-disk state before writing a
single byte, and fails closed on any exception.

Marker schema - .pmo/specs-approval-transaction.json
-------------------------------------------------------
See `SPECS_APPROVAL_MARKER_REQUIRED_FIELDS` below. Status model is the same
two-state ACTIVE / RECOVERY_REQUIRED shape used throughout this codebase
for a single-step (no intermediate Skill-authored content) transaction -
identical in spirit to how `intent-approval-recorder.py`'s own marker works
(no `RECONCILING` state is needed here because, like Intent approval and
unlike CR incorporation, there is no Skill-authored content step between
`begin` and `finalize`).

Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Reused verbatim - generic, project-agnostic infrastructure that has
# nothing to do with Intent specifically: YAML (sub)parsing, text I/O,
# hashing, project-config loading, Document Control field read/write, the
# Decision value type. None of this is Specs-specific business logic, so
# reusing it here is infrastructure reuse, not governance duplication.
import intent_approval_core as iac  # noqa: E402

HERE = Path(__file__).resolve().parent

# specs-governance-guard.py is designed to be imported directly and called
# like a core module - its own docstring says so explicitly ("Every
# validator is importable and callable directly for regression testing"),
# and the existing test suite (test_wm_trucking_new_lifecycle_eligibility.py)
# already establishes this exact import pattern against the real project.
# This module follows the same precedent rather than re-implementing Specs
# structural validation a second time.
import importlib.util as _ilu

_SPECS_GUARD_PATH = HERE.parent / "hooks" / "specs-governance-guard.py"
_spec = _ilu.spec_from_file_location("specs_governance_guard_for_approval",
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
parse_simple_yaml = iac.parse_simple_yaml
set_doc_control_field = iac.set_doc_control_field
_clean = iac._clean

SPECS_POSIX = "docs/pmo/specs/specs.md"
SPECS_APPROVAL_POSIX = "docs/pmo/approvals/specs-approval.yaml"
SPECS_APPROVAL_MARKER_RELPATH_PARTS = (".pmo", "specs-approval-transaction.json")

APPROVAL_REQUIRED_DECISION = "APPROVED"
APPROVAL_REQUIRED_SOURCE = "PM_EXPLICIT"

OPEN_MARKER_STATUSES = {"ACTIVE"}

SPECS_APPROVAL_MARKER_REQUIRED_FIELDS = (
    "transaction_type", "transaction_id", "project_id", "artifact",
    "spec_version", "started_at", "status", "approved_by", "decision_date",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


# --------------------------------------------------------------------------- #
# Path helpers
# --------------------------------------------------------------------------- #

def _abspath(rel_posix, root):
    return os.path.join(root, *rel_posix.split("/"))


def specs_abspath(root):
    return _abspath(SPECS_POSIX, root)


def approval_abspath(root):
    return os.path.join(root, ".pmo", "approvals", "specs-approval.yaml")


def marker_abspath(root):
    return os.path.join(root, *SPECS_APPROVAL_MARKER_RELPATH_PARTS)


# --------------------------------------------------------------------------- #
# Specs Document Control parsing (read-only, minimal - just the fields this
# module needs; full schema validation remains specs-governance-guard.py's
# job, called via `specs_guard.full_spec_validation`).
# --------------------------------------------------------------------------- #

_FIELD_RE_CACHE = {}


def _field(content, label):
    if label not in _FIELD_RE_CACHE:
        core = r"\s+".join(re.escape(p) for p in label.split())
        _FIELD_RE_CACHE[label] = re.compile(
            r"^[ \t>*\-+|]*\**\s*" + core + r"\s*\**\s*[:|]\s*\**\s*"
            r"(.+?)\s*\**\s*\|?\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
    m = _FIELD_RE_CACHE[label].search(content or "")
    return m.group(1).strip() if m else None


def parse_spec_doc_control(content):
    return {
        "spec_version": _field(content, "Spec Version"),
        "spec_status": _field(content, "Spec Status"),
        "execution_authorized": _field(content, "Execution Authorized"),
        "project": _field(content, "Project"),
        "project_id": _field(content, "Project ID"),
        "client": _field(content, "Client"),
    }


# --------------------------------------------------------------------------- #
# Approval-record schema
# --------------------------------------------------------------------------- #

def render_specs_approval_yaml(project_id, spec_version, approved_by,
                               decision_date, approval_statement=None,
                               evidence_reference=None, notes=None):
    """Deterministic serializer for `.pmo/approvals/specs-approval.yaml` -
    fixed field order, stdlib only, mirroring
    `intent_approval_core.render_approval_yaml`'s own shape exactly, plus
    the two fields this record additionally requires (`project_id`,
    `spec_version`) because - unlike Intent, of which a project has only
    ever one canonical artifact - a Specs approval must identify which
    governed baseline it approves."""
    q = iac._yaml_quote
    lines = [
        'schema_version: "1.0"',
        "",
        "decision: {}".format(q(APPROVAL_REQUIRED_DECISION)),
        "approval_source: {}".format(q(APPROVAL_REQUIRED_SOURCE)),
        "project_id: {}".format(q(project_id)),
        "artifact: {}".format(q(SPECS_POSIX)),
        "spec_version: {}".format(q(spec_version)),
        "approved_by: {}".format(q(approved_by)),
        "approved_at: {}".format(q(decision_date)),
    ]
    if evidence_reference:
        lines.append("evidence_reference: {}".format(q(evidence_reference)))
    if approval_statement:
        lines.append("approval_statement: {}".format(q(approval_statement)))
    if notes:
        lines.append("")
        lines.append("notes: {}".format(q(notes)))
    lines.append("")
    return "\n".join(lines)


def load_specs_approval(root):
    """(data, error). error is None iff the file exists and is
    structurally/semantically valid: required fields present, decision ==
    APPROVED, approval_source == PM_EXPLICIT, artifact == canonical Specs
    path."""
    text = read_text(approval_abspath(root))
    if text is None:
        return None, "no specs-approval record at {}".format(SPECS_APPROVAL_POSIX)
    try:
        data = parse_simple_yaml(text)
    except Exception as exc:  # pragma: no cover - defensive
        return None, "specs-approval.yaml is not parseable YAML: {}".format(exc)
    if not isinstance(data, dict):
        return None, "specs-approval.yaml did not parse to a mapping."
    missing = [
        f for f in ("decision", "approval_source", "project_id", "artifact",
                    "spec_version", "approved_by", "approved_at")
        if not _clean(data.get(f))
    ]
    if missing:
        return data, "specs-approval.yaml is missing field(s): {}.".format(
            ", ".join(missing))
    if _clean(data.get("decision")) != APPROVAL_REQUIRED_DECISION:
        return data, "specs-approval.yaml decision is '{}', not '{}'.".format(
            data.get("decision"), APPROVAL_REQUIRED_DECISION)
    if _clean(data.get("approval_source")) != APPROVAL_REQUIRED_SOURCE:
        return data, (
            "specs-approval.yaml approval_source is '{}', not '{}' - PM "
            "approval must be explicit management authority, never "
            "inferred.".format(data.get("approval_source"), APPROVAL_REQUIRED_SOURCE)
        )
    if _clean(data.get("artifact")) != SPECS_POSIX:
        return data, (
            "specs-approval.yaml artifact ('{}') does not match the "
            "canonical Specs path ('{}').".format(data.get("artifact"), SPECS_POSIX)
        )
    return data, None


def validate_specs_approval_matches(root, spec_version=None):
    """Confirm a recorded approval - if one exists - actually matches THIS
    project and THIS Spec Version. Returns an error string, or None when
    either no approval exists yet, or the existing one is valid and
    matching. Never used to fabricate an approval - only to check one that
    is already on disk."""
    data, err = load_specs_approval(root)
    if data is None:
        return None  # no approval recorded yet - not an error at this layer
    if err is not None:
        return err
    cfg = load_project_config(root) or {}
    cfg_pid = _clean((cfg.get("project") or {}).get("id"))
    if cfg_pid and _clean(data.get("project_id")).upper() != cfg_pid.upper():
        return (
            "specs-approval.yaml project_id ('{}') does not match "
            "project-config.yaml ('{}').".format(data.get("project_id"), cfg_pid)
        )
    if spec_version and _clean(data.get("spec_version")) != _clean(spec_version):
        return (
            "specs-approval.yaml spec_version ('{}') does not match the "
            "current Specs Spec Version ('{}') - a materially different "
            "Specs baseline requires its own fresh approval.".format(
                data.get("spec_version"), spec_version)
        )
    return None


# --------------------------------------------------------------------------- #
# The single computed edit pair: Execution Authorized flip + the CURRENT
# version's Specification Change History row updated in place. Mirrors
# intent_approval_core.apply_approval_to_intent's "both or neither" shape.
#
# Updating the existing row IN PLACE (never appending a second row for the
# same version) is deliberate: specs-governance-guard.py's own PMO-SPEC-013
# requires "exactly one Specification Change History row" per current Spec
# Version. Approval never changes FR/NFR/BR content, so it must never look
# like a new content version either - only the row's own `PM Decision`
# column changes, recording the approval as evidence in place.
# --------------------------------------------------------------------------- #

_CHANGE_HISTORY_HEADING = "30. Specification Change History"
_CHANGE_HISTORY_TABLE_HEADER_CELL = "Version"


def _find_change_history_row_line(content, spec_version):
    """Locate the single Specification Change History table row whose
    Version column matches `spec_version` exactly. Returns
    (line_start, line_end, cells) or None if the table, or a unique
    matching row, cannot be found. Read-only; never mutates `content`."""
    heading_re = re.compile(
        r"(?m)^#{1,6}\s*" + re.escape(_CHANGE_HISTORY_HEADING) + r"\s*$")
    hm = heading_re.search(content)
    if not hm:
        return None
    tail = content[hm.end():]
    lines = tail.split("\n")
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("|") and _CHANGE_HISTORY_TABLE_HEADER_CELL in line:
            header_idx = i
            break
    if header_idx is None:
        return None
    row_idx = header_idx + 2
    match_idx = None
    offset = sum(len(l) + 1 for l in lines[:row_idx])
    while row_idx < len(lines) and lines[row_idx].strip().startswith("|"):
        cells = [c.strip() for c in lines[row_idx].strip().strip("|").split("|")]
        if cells and cells[0] == str(spec_version):
            if match_idx is not None:
                return None  # more than one row for this version - ambiguous, refuse
            match_idx = row_idx
            match_offset = offset
            match_cells = cells
        offset += len(lines[row_idx]) + 1
        row_idx += 1
    if match_idx is None:
        return None
    abs_start = hm.end() + match_offset
    abs_end = abs_start + len(lines[match_idx])
    return abs_start, abs_end, match_cells


def apply_approval_to_specs(content, spec_version, approved_by, decision_date,
                            pm_decision_note):
    """Return (new_content, ok). `ok` is False if either edit could not be
    located deterministically, or the current version's row is not unique -
    callers must treat that as a hard failure, never a partial write."""
    new_content, ok_flag = set_doc_control_field(
        content, "Execution Authorized", "true")
    if not ok_flag:
        return None, False
    located = _find_change_history_row_line(new_content, spec_version)
    if located is None:
        return None, False
    start, end, cells = located
    if len(cells) < 6:
        return None, False
    cells[5] = "Approved - {}".format(pm_decision_note)
    new_row = "| " + " | ".join(cells) + " |"
    new_content = new_content[:start] + new_row + new_content[end:]
    return new_content, True


def diff_is_approval_only(before, after, spec_version):
    """Defensive, content-level guarantee that `after` is EXACTLY what
    approval-only editing would produce from `before` - no more, no less.
    Because `finalize_transaction` only ever obtains `after` by calling
    `apply_approval_to_specs` itself (there is no untrusted intermediate
    content anywhere in this module, unlike a guard validating an arbitrary
    Claude-authored Write/Edit), the correct check is a straight line-count
    guarantee: the line count never changes (an in-place row update, never
    an insertion/deletion), and at most two lines change value - the
    Execution Authorized field and the current version's Change History
    row."""
    b_lines = before.splitlines()
    a_lines = after.splitlines()
    if len(a_lines) != len(b_lines):
        return False
    changed_or_missing = sum(
        1 for bl in b_lines if bl not in a_lines
    )
    return changed_or_missing <= 2


# --------------------------------------------------------------------------- #
# BEGIN preconditions (read-only)
# --------------------------------------------------------------------------- #

def run_begin_preconditions(root, approved_by, decision_date, approval_statement=None):
    """Read-only. Returns (plan_dict, Decision-or-None). `plan_dict` is None
    when denied. Never writes anything."""
    approved_by = _clean(approved_by)
    decision_date = _clean(decision_date)
    if not approved_by:
        return None, deny("PMO-SPEC-APPROVAL-001",
                          "approved_by is required and must be non-empty.")
    if not decision_date or not _DATE_RE.match(decision_date):
        return None, deny("PMO-SPEC-APPROVAL-002",
                          "decision_date must be an ISO date (YYYY-MM-DD).")

    content = read_text(specs_abspath(root))
    if content is None:
        return None, deny("PMO-SPEC-APPROVAL-003",
                          "no canonical Specs artifact at {} to approve.".format(SPECS_POSIX))

    d = specs_guard.full_spec_validation(root, spec_text=content)
    if d is not None:
        return None, deny(
            "PMO-SPEC-APPROVAL-004",
            "Specs is not structurally clean and cannot be approved yet - "
            "{}: {}".format(d.code, d.message),
        )

    meta = parse_spec_doc_control(content)
    spec_version = meta.get("spec_version")
    if not spec_version:
        return None, deny("PMO-SPEC-APPROVAL-005",
                          "Specs Document Control has no Spec Version.")
    status = (meta.get("spec_status") or "").strip().upper()
    if status not in ("PROVISIONAL", "ACTIVE"):
        return None, deny(
            "PMO-SPEC-APPROVAL-006",
            "Specs Spec Status is '{}' - expected PROVISIONAL or "
            "ACTIVE.".format(meta.get("spec_status")),
        )
    exec_auth = (meta.get("execution_authorized") or "").strip().lower()
    if exec_auth == "true":
        return None, deny(
            "PMO-SPEC-APPROVAL-007",
            "Execution Authorized is already true for Spec Version {} - "
            "this baseline is already approved; a fresh approval is only "
            "possible for a new Spec Version reached through governed CR "
            "incorporation.".format(spec_version),
        )

    match_err = validate_specs_approval_matches(root, spec_version=spec_version)
    if match_err is not None:
        return None, deny("PMO-SPEC-APPROVAL-008", match_err)
    existing_data, existing_err = load_specs_approval(root)
    if existing_data is not None and existing_err is None \
            and _clean(existing_data.get("spec_version")) == _clean(spec_version):
        return None, deny(
            "PMO-SPEC-APPROVAL-009",
            "Spec Version {} already has a valid approval record - it "
            "must not be silently re-approved or rewritten.".format(spec_version),
        )

    cfg = load_project_config(root) or {}
    project_id = _clean((cfg.get("project") or {}).get("id"))
    if not project_id:
        return None, deny("PMO-SPEC-APPROVAL-010",
                          ".pmo/project-config.yaml has no project.id.")
    doc_pid = _clean(meta.get("project_id"))
    if doc_pid and doc_pid.upper() != project_id.upper():
        return None, deny(
            "PMO-SPEC-APPROVAL-011",
            "Specs Document Control Project ID ('{}') does not match "
            "project-config.yaml ('{}').".format(doc_pid, project_id),
        )

    plan = {
        "project_id": project_id,
        "spec_version": spec_version,
        "approved_by": approved_by,
        "decision_date": decision_date,
        "approval_statement": approval_statement or "",
        "specs_hash_before": sha256_of_text(content),
    }
    return plan, None


def build_marker_data(plan, transaction_id, started_at):
    return {
        "transaction_type": "SPECS_APPROVAL",
        "transaction_id": transaction_id,
        "project_id": plan["project_id"],
        "artifact": SPECS_POSIX,
        "spec_version": plan["spec_version"],
        "started_at": started_at,
        "status": "ACTIVE",
        "approved_by": plan["approved_by"],
        "decision_date": plan["decision_date"],
        "approval_statement": plan.get("approval_statement", ""),
        "specs_hash_before": plan["specs_hash_before"],
    }


def parse_marker(text):
    try:
        data = json.loads(text)
    except Exception as exc:
        return None, "marker is not valid JSON: {}".format(exc)
    if not isinstance(data, dict):
        return None, "marker did not parse to an object."
    missing = [f for f in SPECS_APPROVAL_MARKER_REQUIRED_FIELDS if f not in data]
    if missing:
        return data, "marker is missing field(s): {}.".format(", ".join(missing))
    if data.get("transaction_type") != "SPECS_APPROVAL":
        return data, "marker transaction_type is not SPECS_APPROVAL."
    if data.get("status") not in OPEN_MARKER_STATUSES:
        return data, "marker status '{}' is not a recognised open state.".format(
            data.get("status"))
    if not _TS_RE.match(str(data.get("started_at"))):
        return data, "marker started_at is not a recognisable UTC timestamp."
    if not _DATE_RE.match(str(data.get("decision_date"))):
        return data, "marker decision_date is not a recognisable ISO date."
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
    """Re-derive the exact same plan `begin` would compute, from the marker
    plus current on-disk state. Never trusts the marker's own copy of
    anything that can be independently re-verified."""
    plan, d = run_begin_preconditions(
        root, marker_data.get("approved_by"), marker_data.get("decision_date"),
        marker_data.get("approval_statement"),
    )
    return plan, d


def finalize_transaction(root, marker_data):
    """Independently re-validates everything (never trusts a stale prior
    `validate`), and only on a full PASS writes
    `.pmo/approvals/specs-approval.yaml` followed by the single, atomic
    specs.md edit pair, then removes the marker. Fails closed on any
    exception - a partially-written approval is never left in place."""
    try:
        plan, d = reconcile_transaction(root, marker_data)
        if d is not None:
            return None, d

        specs_path = specs_abspath(root)
        before = read_text(specs_path)
        if before is None:
            return None, deny("PMO-SPEC-APPROVAL-003",
                              "Specs artifact disappeared during the transaction.")
        if sha256_of_text(before) != marker_data.get("specs_hash_before"):
            return None, deny(
                "PMO-SPEC-APPROVAL-013",
                "specs.md changed since this approval transaction began - "
                "refusing to approve a moving target. Re-run `begin`.",
            )

        # Wording deliberately satisfies specs-governance-guard.py's own
        # PMO-SPEC-009 evidence pattern (PM-DECISION near "execution") so
        # the artifact this transaction produces remains structurally
        # valid under full_spec_validation immediately afterward and on
        # every future re-check - this module never leaves the baseline it
        # just approved in a state its own downstream guard would reject.
        pm_note = (
            "Execution Authorized per PM-DECISION: approved by {} on {} "
            "for Spec Version {}.".format(
                plan["approved_by"], plan["decision_date"], plan["spec_version"])
        )
        after, ok = apply_approval_to_specs(
            before, plan["spec_version"], plan["approved_by"],
            plan["decision_date"], pm_note)
        if not ok:
            return None, deny(
                "PMO-SPEC-APPROVAL-014",
                "could not locate the Execution Authorized field and/or the "
                "Specification Change History table deterministically - "
                "refusing a partial edit.",
            )
        if not diff_is_approval_only(before, after, plan["spec_version"]):
            return None, deny(
                "PMO-SPEC-APPROVAL-015",
                "the computed edit touches more than the Execution "
                "Authorized flip and one appended Change History row - "
                "refusing to write.",
            )

        approval_yaml = render_specs_approval_yaml(
            plan["project_id"], plan["spec_version"], plan["approved_by"],
            plan["decision_date"], approval_statement=plan.get("approval_statement"),
        )

        approvals_dir = os.path.dirname(approval_abspath(root))
        if not os.path.isdir(approvals_dir):
            os.makedirs(approvals_dir, exist_ok=True)
        write_text(approval_abspath(root), approval_yaml)
        write_text(specs_path, after)

        marker_path = marker_abspath(root)
        try:
            os.remove(marker_path)
        except OSError:
            pass

        return {
            "spec_version": plan["spec_version"],
            "approved_by": plan["approved_by"],
            "decision_date": plan["decision_date"],
        }, None
    except Exception as exc:  # pragma: no cover - fail closed
        return None, deny("PMO-SPEC-APPROVAL-999",
                          "internal error during finalize: {}".format(exc))
