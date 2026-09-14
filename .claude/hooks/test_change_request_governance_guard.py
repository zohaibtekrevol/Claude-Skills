#!/usr/bin/env python3
"""Regression tests for .claude/hooks/change-request-governance-guard.py.

Stdlib only. Run: python3 .claude/hooks/test_change_request_governance_guard.py
Exit 0 = all pass, 1 = at least one failure.

Uses simulated PreToolUse payloads and temporary, synthetic project fixtures
only - no real Smart Basket project artifact is ever created, read as a
mutable fixture, or modified.
"""

import importlib.util
import json
import os
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "change-request-governance-guard.py")
_spec = importlib.util.spec_from_file_location("change_request_governance_guard", HOOK)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

_RESULTS = []


def check(name, ok, detail=""):
    _RESULTS.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + "  " + name + ("" if ok else "   :: " + str(detail)))


def code(decision):
    return getattr(decision, "code", None)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

CONFIG_YAML = (
    'project:\n'
    '  id: "SMART-BASKET"\n'
    '  name: "Smart Basket"\n'
    'artifacts:\n'
    '  change_requests:\n'
    '    path: "docs/pmo/cr"\n'
    '    latest_id: null\n'
    '  change_log:\n'
    '    path: "docs/pmo/change-log"\n'
    '    latest_id: null\n'
    '    total_count: 0\n'
    '  scope:\n'
    '    latest_version: "0.1"\n'
    '  specifications:\n'
    '    latest_version: "0.1"\n'
    'repository:\n'
    '  provider: "bitbucket"\n'
    '  workspace: "devops-tekrevol"\n'
    '  repository: "lets-explore-more-specs"\n'
    '  working_branch: "pmo-artifacts"\n'
    'workflow:\n'
    '  current_stage: "SCOPE_READY_FOR_CLIENT_REVIEW"\n'
)

MARKER_RELPATH = os.path.join(".pmo", "change-request-transaction.json")
FEEDBACK_MARKER_RELPATH = os.path.join(".pmo", "feedback-transaction.json")


def marker_json(project_id="SMART-BASKET", cr_id=None, operation="STATE_TRANSITION",
                status="ACTIVE", transaction_id="CRTX-TEST-0001",
                started_at="2026-09-14T20:00:00Z", **extra):
    d = {
        "transaction_type": "CHANGE_REQUEST_MANAGEMENT",
        "transaction_id": transaction_id,
        "project_id": project_id,
        "cr_id": cr_id,
        "operation": operation,
        "started_at": started_at,
        "status": status,
    }
    d.update(extra)
    return json.dumps(d)


def feedback_marker_json(project_id="SMART-BASKET", status="ACTIVE"):
    return json.dumps({
        "transaction_type": "FEEDBACK_MANAGEMENT",
        "transaction_id": "FBTX-TEST-0001",
        "project_id": project_id,
        "feedback_batch_id": None,
        "started_at": "2026-09-14T20:00:00Z",
        "status": status,
    })


def cr_doc(cr_id, origin="CLIENT_REQUESTED", status="DRAFT",
          batch_id="FB-2026-001", item_id="FB-2026-001-001",
          project_id="SMART-BASKET", decision="", decision_date="",
          decision_by="", approval_evidence="", reason="",
          incorporated_date="", chg_ref="", history_rows=None,
          title="Add loyalty points redemption"):
    if origin != "CLIENT_REQUESTED":
        batch_id = "No Feedback ID — PM_PROPOSED"
        item_id = "No Feedback ID — PM_PROPOSED"
    rows = [
        ("CR ID", cr_id),
        ("Logical Global ID", "{}::{}".format(project_id, cr_id)),
        ("Project ID", project_id),
        ("Title", title),
        ("Origin", origin),
        ("Origin Feedback Batch", batch_id),
        ("Origin Feedback Item", item_id),
        ("Created By", "PM"),
        ("Created Date", "2026-09-14"),
        ("Description", "desc"),
        ("Business Rationale", "rationale"),
        ("Affected Modules", "Checkout"),
        ("Affected Scope", "SCP-REQ-010"),
        ("Affected Requirements", "FR-020"),
        ("Proposed Change", "change"),
        ("Scope Impact", "impact"),
        ("Technical Impact", "impact"),
        ("Status", status),
        ("Decision", decision),
        ("Decision Date", decision_date),
        ("Decision By", decision_by),
        ("Approval Evidence", approval_evidence),
        ("Target Scope Version", ""),
        ("Target Spec Version", ""),
        ("Incorporated Date", incorporated_date),
        ("Change Log Reference", chg_ref),
        ("Rejection/Deferral Reason", reason),
    ]
    lines = ["# Change Request " + cr_id, "", "| Field | Requirement | Value |", "|---|---|---|"]
    for f, v in rows:
        lines.append("| {} | REQUIRED | {} |".format(f, v))
    if history_rows is None:
        history_rows = ["| 2026-09-14 | — | {} | PM | initial creation |".format(status)]
    lines += ["", "## Status History", "",
             "| Date | From | To | By | Evidence/Note |", "|---|---|---|---|---|"]
    lines += history_rows
    return "\n".join(lines)


def cr_register_doc(rows=None):
    header = [
        "# Change Request Register", "",
        "| CR ID | Title | Origin | Status | Origin Feedback | Target Scope Version | Target Spec Version | Last Updated |",
        "|---|---|---|---|---|---|---|---|",
    ]
    return "\n".join(header + (rows or []))


def scope_doc(version="0.2", prev_version="0.1", cr_id=None):
    lines = [
        "# Scope v{}".format(version), "",
        "| Field | Value |", "|---|---|",
        "| Project | Smart Basket |",
        "| Scope Version | {} |".format(version),
        "| Previous Scope Version | {} |".format(prev_version),
        "| Status | DRAFT |",
        "",
    ]
    if cr_id:
        lines.append("SCP-REQ-010 updated. Change Source: {}".format(cr_id))
    return "\n".join(lines)


def specs_doc(spec_version="0.1", cr_id=None):
    lines = [
        "# Specs", "",
        "| Field | Value |", "|---|---|",
        "| Spec Version | {} |".format(spec_version),
        "",
    ]
    if cr_id:
        lines.append("FR-020 updated. Change Source: {} (CHG-001)".format(cr_id))
    return "\n".join(lines)


def changelog_doc(rows=None):
    header = [
        "# Change Log", "",
        "| CHG ID | Logical Global ID | Date | CR ID | CR Origin | Feedback Reference | "
        "Prev Scope Ver | New Scope Ver | Prev Spec Ver | New Spec Ver | "
        "Affected Requirements | Supersedes | Incorporated By |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    return "\n".join(header + (rows or []))


def chg_row(chg_id, cr_id, new_scope_ver, new_spec_ver,
           prev_scope_ver="0.1", prev_spec_ver="0.1"):
    return ("| {} | SMART-BASKET::{} | 2026-09-15 | {} | CLIENT_REQUESTED | | "
           "{} | {} | {} | {} | FR-020 | | PM |").format(
        chg_id, chg_id, cr_id, prev_scope_ver, new_scope_ver, prev_spec_ver, new_spec_ver)


def _w(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def run(tool, tool_input, files=None, cr_marker=None, feedback_marker=None,
       config=CONFIG_YAML):
    """cr_marker/feedback_marker: None/False = absent. True = default valid
    ACTIVE marker. A string = literal content. A dict = kwargs forwarded to
    the respective *_json() builder."""
    tmp = tempfile.mkdtemp(prefix="cr-guard-test-")
    try:
        for d in (
            os.path.join(tmp, ".pmo"),
            os.path.join(tmp, "docs", "pmo", "cr"),
            os.path.join(tmp, "docs", "pmo", "change-log"),
            os.path.join(tmp, "docs", "pmo", "scope"),
            os.path.join(tmp, "docs", "pmo", "specs"),
            os.path.join(tmp, "docs", "pmo", "feedback", "batches"),
        ):
            os.makedirs(d, exist_ok=True)
        if config is not None:
            _w(os.path.join(tmp, ".pmo", "project-config.yaml"), config)
        if cr_marker is True:
            _w(os.path.join(tmp, MARKER_RELPATH), marker_json())
        elif isinstance(cr_marker, dict):
            _w(os.path.join(tmp, MARKER_RELPATH), marker_json(**cr_marker))
        elif isinstance(cr_marker, str):
            _w(os.path.join(tmp, MARKER_RELPATH), cr_marker)
        if feedback_marker is True:
            _w(os.path.join(tmp, FEEDBACK_MARKER_RELPATH), feedback_marker_json())
        elif isinstance(feedback_marker, dict):
            _w(os.path.join(tmp, FEEDBACK_MARKER_RELPATH), feedback_marker_json(**feedback_marker))
        for relpath, text in (files or {}).items():
            p = os.path.join(tmp, *relpath.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            _w(p, text)
        ti = dict(tool_input)
        fp = ti.get("file_path")
        if fp and not os.path.isabs(fp):
            ti["file_path"] = os.path.join(tmp, *fp.split("/"))
        return mod.process({"tool_name": tool, "tool_input": ti, "cwd": tmp})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
# unit checks
# --------------------------------------------------------------------------- #

def test_units():
    check("unit/transitions_draft", mod.TRANSITIONS["DRAFT"] == {"PM_REVIEW", "CANCELLED"})
    check("unit/transitions_incorporated_terminal", mod.TRANSITIONS["INCORPORATED"] == set())
    check("unit/pm_proposed_literal", mod.PM_PROPOSED_LITERAL == "No Feedback ID — PM_PROPOSED")
    check("unit/change_source_match",
          mod.content_has_change_source("blah Change Source: CR-005 (CHG-002) blah", "CR-005"))
    check("unit/change_source_no_partial_match",
          not mod.content_has_change_source("Change Source: CR-0051", "CR-005"))
    check("unit/cr_id_re", bool(mod.CR_ID_RE.match("CR-030")) and not mod.CR_ID_RE.match("CR"))


# --------------------------------------------------------------------------- #
# 1-8: required positive scenarios
# --------------------------------------------------------------------------- #

def test_1_pm_proposed_draft_creation_allowed():
    doc = cr_doc("CR-100", origin="PM_PROPOSED", status="DRAFT")
    d = run("Write", {"file_path": "docs/pmo/cr/CR-100.md", "content": doc},
            cr_marker={"operation": "CREATE_PM_PROPOSED", "cr_id": "CR-100"})
    check("1/pm_proposed_draft_creation__ALLOW", d is None, code(d))


def test_2_client_requested_draft_to_pm_review_allowed():
    old = cr_doc("CR-101", status="DRAFT")
    new = cr_doc("CR-101", status="PM_REVIEW", history_rows=[
        "| 2026-09-14 | — | DRAFT | PM | initial creation |",
        "| 2026-09-15 | DRAFT | PM_REVIEW | PM | ready for review |",
    ])
    d = run("Write", {"file_path": "docs/pmo/cr/CR-101.md", "content": new},
            files={"docs/pmo/cr/CR-101.md": old,
                  "docs/pmo/feedback/batches/FB-2026-001.md":
                      "### FB-2026-001-001\n\n| Field | Value |\n|---|---|\n"
                      "| Related CR | CR-101 |\n"},
            cr_marker={"cr_id": "CR-101"})
    check("2/client_requested_draft_to_pm_review__ALLOW", d is None, code(d))


def test_3_pm_review_to_pending_client_decision_allowed():
    old = cr_doc("CR-102", status="PM_REVIEW", history_rows=[
        "| 2026-09-14 | — | DRAFT | PM | initial creation |",
        "| 2026-09-15 | DRAFT | PM_REVIEW | PM | ready |",
    ])
    new = cr_doc("CR-102", status="PENDING_CLIENT_DECISION", history_rows=[
        "| 2026-09-14 | — | DRAFT | PM | initial creation |",
        "| 2026-09-15 | DRAFT | PM_REVIEW | PM | ready |",
        "| 2026-09-16 | PM_REVIEW | PENDING_CLIENT_DECISION | PM | sent to client |",
    ])
    d = run("Write", {"file_path": "docs/pmo/cr/CR-102.md", "content": new},
            files={"docs/pmo/cr/CR-102.md": old}, cr_marker={"cr_id": "CR-102"})
    check("3/pm_review_to_pending_client_decision__ALLOW", d is None, code(d))


def test_4_pending_to_approved_with_evidence_allowed():
    old = cr_doc("CR-103", status="PENDING_CLIENT_DECISION", history_rows=[
        "| 2026-09-14 | — | DRAFT | PM | initial |",
        "| 2026-09-16 | PM_REVIEW | PENDING_CLIENT_DECISION | PM | sent |",
    ])
    new = cr_doc("CR-103", status="APPROVED", decision="APPROVED",
                decision_date="2026-09-17", decision_by="PM",
                approval_evidence="client email 2026-09-17",
                history_rows=[
                    "| 2026-09-14 | — | DRAFT | PM | initial |",
                    "| 2026-09-16 | PM_REVIEW | PENDING_CLIENT_DECISION | PM | sent |",
                    "| 2026-09-17 | PENDING_CLIENT_DECISION | APPROVED | PM | client email |",
                ])
    d = run("Write", {"file_path": "docs/pmo/cr/CR-103.md", "content": new},
            files={"docs/pmo/cr/CR-103.md": old}, cr_marker={"cr_id": "CR-103", "operation": "APPROVAL"})
    check("4/pending_to_approved_with_evidence__ALLOW", d is None, code(d))


def test_5_pending_to_rejected_with_evidence_allowed():
    old = cr_doc("CR-104", status="PENDING_CLIENT_DECISION", history_rows=[
        "| 2026-09-14 | — | DRAFT | PM | initial |",
    ])
    new = cr_doc("CR-104", status="REJECTED", decision="REJECTED",
                decision_date="2026-09-17", decision_by="PM",
                reason="client declined - out of budget",
                history_rows=[
                    "| 2026-09-14 | — | DRAFT | PM | initial |",
                    "| 2026-09-17 | PENDING_CLIENT_DECISION | REJECTED | PM | client declined |",
                ])
    d = run("Write", {"file_path": "docs/pmo/cr/CR-104.md", "content": new},
            files={"docs/pmo/cr/CR-104.md": old}, cr_marker={"cr_id": "CR-104", "operation": "REJECTION"})
    check("5/pending_to_rejected_with_evidence__ALLOW", d is None, code(d))


def test_6_pending_to_deferred_with_evidence_allowed():
    old = cr_doc("CR-105", status="PENDING_CLIENT_DECISION", history_rows=[
        "| 2026-09-14 | — | DRAFT | PM | initial |",
    ])
    new = cr_doc("CR-105", status="DEFERRED", decision="DEFERRED",
                decision_date="2026-09-17", decision_by="PM",
                reason="client wants to revisit next quarter",
                history_rows=[
                    "| 2026-09-14 | — | DRAFT | PM | initial |",
                    "| 2026-09-17 | PENDING_CLIENT_DECISION | DEFERRED | PM | revisit later |",
                ])
    d = run("Write", {"file_path": "docs/pmo/cr/CR-105.md", "content": new},
            files={"docs/pmo/cr/CR-105.md": old}, cr_marker={"cr_id": "CR-105", "operation": "DEFERRAL"})
    check("6/pending_to_deferred_with_evidence__ALLOW", d is None, code(d))


def test_7_approved_to_cancelled_before_incorporation_allowed():
    old = cr_doc("CR-106", status="APPROVED", decision="APPROVED",
                decision_date="2026-09-17", decision_by="PM",
                approval_evidence="client email 2026-09-17",
                history_rows=[
                    "| 2026-09-14 | — | DRAFT | PM | initial |",
                    "| 2026-09-17 | PENDING_CLIENT_DECISION | APPROVED | PM | client email |",
                ])
    new = cr_doc("CR-106", status="CANCELLED", decision="CANCELLED",
                decision_date="2026-09-18", decision_by="PM",
                approval_evidence="client email 2026-09-17",  # unchanged
                reason="client withdrew before build started",
                history_rows=[
                    "| 2026-09-14 | — | DRAFT | PM | initial |",
                    "| 2026-09-17 | PENDING_CLIENT_DECISION | APPROVED | PM | client email |",
                    "| 2026-09-18 | APPROVED | CANCELLED | PM | client withdrew |",
                ])
    d = run("Write", {"file_path": "docs/pmo/cr/CR-106.md", "content": new},
            files={"docs/pmo/cr/CR-106.md": old},
            cr_marker={"cr_id": "CR-106", "operation": "CANCELLATION"})
    check("7/approved_to_cancelled_before_incorporation__ALLOW", d is None, code(d))


def test_8_full_synthetic_incorporation():
    tmp = tempfile.mkdtemp(prefix="cr-guard-incorp-")
    try:
        for d in (
            os.path.join(tmp, ".pmo"),
            os.path.join(tmp, "docs", "pmo", "cr"),
            os.path.join(tmp, "docs", "pmo", "change-log"),
            os.path.join(tmp, "docs", "pmo", "scope"),
            os.path.join(tmp, "docs", "pmo", "specs"),
        ):
            os.makedirs(d, exist_ok=True)
        _w(os.path.join(tmp, ".pmo", "project-config.yaml"), CONFIG_YAML)

        approved_cr = cr_doc("CR-107", status="APPROVED", decision="APPROVED",
                             decision_date="2026-09-17", decision_by="PM",
                             approval_evidence="client email 2026-09-17",
                             history_rows=[
                                 "| 2026-09-14 | — | DRAFT | PM | initial |",
                                 "| 2026-09-17 | PENDING_CLIENT_DECISION | APPROVED | PM | client email |",
                             ])
        _w(os.path.join(tmp, "docs", "pmo", "cr", "CR-107.md"), approved_cr)
        _w(os.path.join(tmp, "docs", "pmo", "specs", "specs.md"), specs_doc("0.1"))

        marker_path = os.path.join(tmp, MARKER_RELPATH)
        _w(marker_path, marker_json(cr_id="CR-107", operation="INCORPORATION",
                                    baseline_scope_version="0.1",
                                    baseline_specs_version="0.1"))

        def call(tool, file_path, content):
            return mod.process({
                "tool_name": tool,
                "tool_input": {"file_path": os.path.join(tmp, *file_path.split("/")),
                               "content": content},
                "cwd": tmp,
            })

        # a. new Scope revision
        d = call("Write", "docs/pmo/scope/scope-v0.2.md", scope_doc("0.2", "0.1", "CR-107"))
        check("8a/new_scope_revision__ALLOW", d is None, code(d))
        _w(os.path.join(tmp, "docs", "pmo", "scope", "scope-v0.2.md"), scope_doc("0.2", "0.1", "CR-107"))

        # b. specs.md update
        d = call("Write", "docs/pmo/specs/specs.md", specs_doc("0.2", "CR-107"))
        check("8b/specs_update__ALLOW", d is None, code(d))
        _w(os.path.join(tmp, "docs", "pmo", "specs", "specs.md"), specs_doc("0.2", "CR-107"))

        # c. CHG entry
        d = call("Write", "docs/pmo/change-log/change-log.md",
                changelog_doc([chg_row("CHG-001", "CR-107", "0.2", "0.2")]))
        check("8c/change_log_entry__ALLOW", d is None, code(d))
        _w(os.path.join(tmp, "docs", "pmo", "change-log", "change-log.md"),
          changelog_doc([chg_row("CHG-001", "CR-107", "0.2", "0.2")]))

        # d. CR -> INCORPORATED
        incorporated_cr = cr_doc("CR-107", status="INCORPORATED", decision="APPROVED",
                                 decision_date="2026-09-17", decision_by="PM",
                                 approval_evidence="client email 2026-09-17",
                                 incorporated_date="2026-09-19", chg_ref="CHG-001",
                                 history_rows=[
                                     "| 2026-09-14 | — | DRAFT | PM | initial |",
                                     "| 2026-09-17 | PENDING_CLIENT_DECISION | APPROVED | PM | client email |",
                                     "| 2026-09-19 | APPROVED | INCORPORATED | PM | incorporation transaction |",
                                 ])
        d = call("Write", "docs/pmo/cr/CR-107.md", incorporated_cr)
        check("8d/cr_marked_incorporated__ALLOW", d is None, code(d))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 9-28: required negative scenarios
# --------------------------------------------------------------------------- #

def test_9_pm_proposed_fake_feedback_id_denied():
    doc = cr_doc("CR-108", origin="PM_PROPOSED", status="DRAFT")
    doc = doc.replace("No Feedback ID — PM_PROPOSED", "FB-2026-099-001", 1)
    d = run("Write", {"file_path": "docs/pmo/cr/CR-108.md", "content": doc},
            cr_marker={"operation": "CREATE_PM_PROPOSED", "cr_id": "CR-108"})
    check("9/pm_proposed_fake_feedback_id__DENY_008", code(d) == "PMO-CR-GUARD-008", code(d))


def test_10_client_requested_missing_provenance_denied():
    # An existing CLIENT_REQUESTED DRAFT CR (as feedback-management would
    # hand off) but with corrupted/missing provenance fields - change-
    # request-management must catch this the moment it touches the CR,
    # even for an otherwise-valid transition.
    old = cr_doc("CR-109", origin="CLIENT_REQUESTED", status="DRAFT",
                batch_id="", item_id="")
    new = cr_doc("CR-109", origin="CLIENT_REQUESTED", status="PM_REVIEW",
                batch_id="", item_id="",
                history_rows=[
                    "| 2026-09-14 | — | DRAFT | PM | initial |",
                    "| 2026-09-15 | DRAFT | PM_REVIEW | PM | ready |",
                ])
    d = run("Write", {"file_path": "docs/pmo/cr/CR-109.md", "content": new},
            files={"docs/pmo/cr/CR-109.md": old}, cr_marker={"cr_id": "CR-109"})
    check("10/client_requested_missing_provenance__DENY_008",
          code(d) == "PMO-CR-GUARD-008", code(d))


def test_11_approved_without_evidence_denied():
    old = cr_doc("CR-110", status="PENDING_CLIENT_DECISION")
    new = cr_doc("CR-110", status="APPROVED", history_rows=[
        "| 2026-09-14 | — | DRAFT | PM | initial |",
        "| 2026-09-17 | PENDING_CLIENT_DECISION | APPROVED | PM | |",
    ])
    d = run("Write", {"file_path": "docs/pmo/cr/CR-110.md", "content": new},
            files={"docs/pmo/cr/CR-110.md": old},
            cr_marker={"cr_id": "CR-110", "operation": "APPROVAL"})
    check("11/approved_without_evidence__DENY_007", code(d) == "PMO-CR-GUARD-007", code(d))


def test_12_draft_to_incorporated_denied():
    old = cr_doc("CR-111", status="DRAFT")
    new = cr_doc("CR-111", status="INCORPORATED", history_rows=[
        "| 2026-09-14 | — | DRAFT | PM | initial |",
        "| 2026-09-17 | DRAFT | INCORPORATED | PM | shortcut |",
    ])
    d = run("Write", {"file_path": "docs/pmo/cr/CR-111.md", "content": new},
            files={"docs/pmo/cr/CR-111.md": old},
            cr_marker={"cr_id": "CR-111", "operation": "INCORPORATION"})
    check("12/draft_to_incorporated__DENY_006", code(d) == "PMO-CR-GUARD-006", code(d))


def test_13_incorporated_to_cancelled_denied():
    old = cr_doc("CR-112", status="INCORPORATED", decision="APPROVED",
                decision_date="2026-09-17", decision_by="PM",
                approval_evidence="evidence", incorporated_date="2026-09-19",
                chg_ref="CHG-002")
    new = cr_doc("CR-112", status="CANCELLED", decision="CANCELLED",
                decision_date="2026-09-20", decision_by="PM", reason="oops",
                approval_evidence="evidence", incorporated_date="2026-09-19",
                chg_ref="CHG-002",
                history_rows=[
                    "| 2026-09-14 | — | DRAFT | PM | initial |",
                    "| 2026-09-20 | INCORPORATED | CANCELLED | PM | oops |",
                ])
    d = run("Write", {"file_path": "docs/pmo/cr/CR-112.md", "content": new},
            files={"docs/pmo/cr/CR-112.md": old}, cr_marker={"cr_id": "CR-112"})
    check("13/incorporated_to_cancelled__DENY_011", code(d) == "PMO-CR-GUARD-011", code(d))


def test_14_scope_mutation_ordinary_transition_denied():
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.2.md",
                      "content": scope_doc("0.2", "0.1", "CR-113")},
            cr_marker={"cr_id": "CR-113", "operation": "STATE_TRANSITION"})
    check("14/scope_mutation_ordinary_transition__DENY_012",
          code(d) == "PMO-CR-GUARD-012", code(d))


def test_15_specs_mutation_ordinary_transition_denied():
    d = run("Write", {"file_path": "docs/pmo/specs/specs.md",
                      "content": specs_doc("0.2", "CR-114")},
            files={"docs/pmo/specs/specs.md": specs_doc("0.1")},
            cr_marker={"cr_id": "CR-114", "operation": "STATE_TRANSITION"})
    check("15/specs_mutation_ordinary_transition__DENY_013",
          code(d) == "PMO-CR-GUARD-013", code(d))


def test_16_change_log_write_before_incorporation_denied():
    d = run("Write", {"file_path": "docs/pmo/change-log/change-log.md",
                      "content": changelog_doc([chg_row("CHG-003", "CR-115", "0.2", "0.2")])},
            cr_marker={"cr_id": "CR-115", "operation": "APPROVAL"})
    check("16/change_log_before_incorporation__DENY_014",
          code(d) == "PMO-CR-GUARD-014", code(d))


def test_17_change_source_mismatch_denied():
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.2.md",
                      "content": scope_doc("0.2", "0.1", cr_id=None)},  # no Change Source tag
            files={"docs/pmo/cr/CR-116.md": cr_doc(
                "CR-116", status="APPROVED", decision="APPROVED",
                decision_date="2026-09-17", decision_by="PM",
                approval_evidence="evidence")},
            cr_marker={"cr_id": "CR-116", "operation": "INCORPORATION",
                      "baseline_scope_version": "0.1"})
    check("17/change_source_mismatch__DENY_016", code(d) == "PMO-CR-GUARD-016", code(d))


def test_18_scope_spec_version_mismatch_denied():
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.1.md",  # not > baseline
                      "content": scope_doc("0.1", "0.1", "CR-117")},
            files={"docs/pmo/cr/CR-117.md": cr_doc(
                "CR-117", status="APPROVED", decision="APPROVED",
                decision_date="2026-09-17", decision_by="PM",
                approval_evidence="evidence")},
            cr_marker={"cr_id": "CR-117", "operation": "INCORPORATION",
                      "baseline_scope_version": "0.1"})
    check("18/scope_version_not_advanced__DENY_015", code(d) == "PMO-CR-GUARD-015", code(d))


def test_19_change_log_version_mismatch_denied():
    d = run("Write", {"file_path": "docs/pmo/change-log/change-log.md",
                      "content": changelog_doc([chg_row("CHG-004", "CR-118", "0.9", "0.9")])},
            files={
                "docs/pmo/cr/CR-118.md": cr_doc(
                    "CR-118", status="APPROVED", decision="APPROVED",
                    decision_date="2026-09-17", decision_by="PM",
                    approval_evidence="evidence"),
                "docs/pmo/scope/scope-v0.2.md": scope_doc("0.2", "0.1", "CR-118"),
                "docs/pmo/specs/specs.md": specs_doc("0.2", "CR-118"),
            },
            cr_marker={"cr_id": "CR-118", "operation": "INCORPORATION"})
    check("19/change_log_version_mismatch__DENY_015", code(d) == "PMO-CR-GUARD-015", code(d))


def test_20_incorporated_while_specs_failed_denied():
    # Change Log entry exists and matches Scope, but specs.md was never
    # actually advanced/tagged for this CR - INCORPORATED must be refused.
    old_cr = cr_doc("CR-119", status="APPROVED", decision="APPROVED",
                    decision_date="2026-09-17", decision_by="PM",
                    approval_evidence="evidence",
                    history_rows=[
                        "| 2026-09-14 | — | DRAFT | PM | initial |",
                        "| 2026-09-17 | PENDING_CLIENT_DECISION | APPROVED | PM | evidence |",
                    ])
    new_cr = cr_doc("CR-119", status="INCORPORATED", decision="APPROVED",
                    decision_date="2026-09-17", decision_by="PM",
                    approval_evidence="evidence", incorporated_date="2026-09-19",
                    chg_ref="CHG-005",
                    history_rows=[
                        "| 2026-09-14 | — | DRAFT | PM | initial |",
                        "| 2026-09-17 | PENDING_CLIENT_DECISION | APPROVED | PM | evidence |",
                        "| 2026-09-19 | APPROVED | INCORPORATED | PM | incorporation |",
                    ])
    d = run("Write", {"file_path": "docs/pmo/cr/CR-119.md", "content": new_cr},
            files={
                "docs/pmo/cr/CR-119.md": old_cr,
                "docs/pmo/scope/scope-v0.2.md": scope_doc("0.2", "0.1", "CR-119"),
                "docs/pmo/specs/specs.md": specs_doc("0.1", cr_id=None),  # never advanced
                "docs/pmo/change-log/change-log.md": changelog_doc(
                    [chg_row("CHG-005", "CR-119", "0.2", "0.2")]),
            },
            cr_marker={"cr_id": "CR-119", "operation": "INCORPORATION"})
    check("20/incorporated_while_specs_failed__DENY_015",
          code(d) == "PMO-CR-GUARD-015", code(d))


def test_21_lifecycle_history_deleted_denied():
    old = cr_doc("CR-120", status="PM_REVIEW", history_rows=[
        "| 2026-09-14 | — | DRAFT | PM | initial |",
        "| 2026-09-15 | DRAFT | PM_REVIEW | PM | ready |",
    ])
    new = cr_doc("CR-120", status="PENDING_CLIENT_DECISION", history_rows=[
        "| 2026-09-16 | PM_REVIEW | PENDING_CLIENT_DECISION | PM | sent |",
    ])  # dropped the first two rows
    d = run("Write", {"file_path": "docs/pmo/cr/CR-120.md", "content": new},
            files={"docs/pmo/cr/CR-120.md": old}, cr_marker={"cr_id": "CR-120"})
    check("21/lifecycle_history_deleted__DENY_009", code(d) == "PMO-CR-GUARD-009", code(d))


def test_22_cr_id_reused_denied():
    existing = cr_doc("CR-121", status="REJECTED", decision="REJECTED",
                      decision_date="2026-09-14", decision_by="PM", reason="no")
    doc = cr_doc("CR-121", origin="PM_PROPOSED", status="DRAFT")
    d = run("Write", {"file_path": "docs/pmo/cr/CR-121.md", "content": doc},
            files={"docs/pmo/cr/CR-121.md": existing},
            cr_marker={"operation": "CREATE_PM_PROPOSED", "cr_id": "CR-121"})
    check("22/cr_id_reused__DENY_004", code(d) == "PMO-CR-GUARD-004", code(d))


def test_23_project_working_branch_altered_denied():
    new_config = CONFIG_YAML.replace('working_branch: "pmo-artifacts"',
                                     'working_branch: "some-other-branch"')
    d = run("Write", {"file_path": ".pmo/project-config.yaml", "content": new_config},
            cr_marker=True)
    check("23/config_working_branch_altered__DENY_020", code(d) == "PMO-CR-GUARD-020", code(d))


def test_24_both_markers_active_denied():
    doc = cr_doc("CR-122", status="PM_REVIEW")
    d = run("Write", {"file_path": "docs/pmo/cr/CR-122.md", "content": doc},
            files={"docs/pmo/cr/CR-122.md": cr_doc("CR-122", status="DRAFT")},
            cr_marker={"cr_id": "CR-122"}, feedback_marker=True)
    check("24/both_markers_active__DENY_025", code(d) == "PMO-CR-GUARD-025", code(d))


def test_25_malformed_cr_marker_denied():
    d1 = run("Write", {"file_path": ".pmo/change-request-transaction.json",
                       "content": "{not valid json"})
    check("25/malformed_marker_creation__DENY_022", code(d1) == "PMO-CR-GUARD-022", code(d1))

    doc = cr_doc("CR-123", origin="PM_PROPOSED", status="DRAFT")
    d2 = run("Write", {"file_path": "docs/pmo/cr/CR-123.md", "content": doc},
            cr_marker="{not valid json")
    check("25/malformed_marker_blocks_write__DENY_022", code(d2) == "PMO-CR-GUARD-022", code(d2))


def test_26_wrong_project_cr_marker_denied():
    doc = cr_doc("CR-124", origin="PM_PROPOSED", status="DRAFT")
    d = run("Write", {"file_path": "docs/pmo/cr/CR-124.md", "content": doc},
            cr_marker={"operation": "CREATE_PM_PROPOSED", "cr_id": "CR-124",
                      "project_id": "SOME-OTHER-PROJECT"})
    check("26/wrong_project_cr_marker__DENY_001", code(d) == "PMO-CR-GUARD-001", code(d))


def test_27_no_marker_on_cr_lifecycle_mutation_denied():
    doc = cr_doc("CR-125", origin="PM_PROPOSED", status="DRAFT")
    d = run("Write", {"file_path": "docs/pmo/cr/CR-125.md", "content": doc})
    check("27/no_marker_pm_proposed__DENY_024", code(d) == "PMO-CR-GUARD-024", code(d))

    old = cr_doc("CR-126", status="DRAFT")
    new = cr_doc("CR-126", status="PM_REVIEW", history_rows=[
        "| 2026-09-14 | — | DRAFT | PM | initial |",
        "| 2026-09-15 | DRAFT | PM_REVIEW | PM | ready |",
    ])
    d2 = run("Write", {"file_path": "docs/pmo/cr/CR-126.md", "content": new},
            files={"docs/pmo/cr/CR-126.md": old})
    check("27/no_marker_transition__DENY_024", code(d2) == "PMO-CR-GUARD-024", code(d2))


def test_28_unexpected_exception_fail_closed():
    original = mod.validate_cr_content

    def boom(*a, **kw):
        raise RuntimeError("synthetic failure")

    mod.validate_cr_content = boom
    try:
        old = cr_doc("CR-127", status="DRAFT")
        new = cr_doc("CR-127", status="PM_REVIEW", history_rows=[
            "| 2026-09-14 | — | DRAFT | PM | initial |",
            "| 2026-09-15 | DRAFT | PM_REVIEW | PM | ready |",
        ])
        d = run("Write", {"file_path": "docs/pmo/cr/CR-127.md", "content": new},
                files={"docs/pmo/cr/CR-127.md": old}, cr_marker={"cr_id": "CR-127"})
        check("28/internal_error__FAIL_CLOSED_026", code(d) == "PMO-CR-GUARD-026", code(d))
    finally:
        mod.validate_cr_content = original


# --------------------------------------------------------------------------- #
# extra coverage
# --------------------------------------------------------------------------- #

def test_extra_template_never_governed():
    d = run("Write", {"file_path": "docs/pmo/cr/_TEMPLATE-CR.md",
                      "content": "anything at all"})
    check("extra/template_never_governed__ALLOW", d is None, code(d))


def test_extra_feedback_safe_shape_deferred_without_cr_marker():
    doc = cr_doc("CR-128", status="DRAFT")
    d = run("Write", {"file_path": "docs/pmo/cr/CR-128.md", "content": doc})
    check("extra/feedback_safe_shape_no_cr_marker__ALLOW_deferred", d is None, code(d))


def test_extra_unrelated_path_and_tool():
    d1 = run("Write", {"file_path": "README.md", "content": "hi"})
    check("extra/unrelated_path__ALLOW", d1 is None, code(d1))
    d2 = mod.process({"tool_name": "Bash", "tool_input": {"command": "echo hi"},
                      "cwd": tempfile.gettempdir()})
    check("extra/bash_not_governed__ALLOW", d2 is None, code(d2))


def test_extra_cr_register_lifecycle_write_requires_marker():
    rows = [
        "| CR-129 | Title | PM_PROPOSED | DRAFT | No Feedback ID — PM_PROPOSED | | | 2026-09-15 |",
    ]
    d = run("Write", {"file_path": "docs/pmo/cr/change-request-register.md",
                      "content": cr_register_doc(rows)})
    check("extra/register_pm_proposed_row_no_marker__DENY_024",
          code(d) == "PMO-CR-GUARD-024", code(d))

    d2 = run("Write", {"file_path": "docs/pmo/cr/change-request-register.md",
                       "content": cr_register_doc(rows)},
            cr_marker={"operation": "CREATE_PM_PROPOSED", "cr_id": "CR-129"})
    check("extra/register_pm_proposed_row_with_marker__ALLOW", d2 is None, code(d2))


# --------------------------------------------------------------------------- #

def main():
    test_units()
    for fn in (
        test_1_pm_proposed_draft_creation_allowed,
        test_2_client_requested_draft_to_pm_review_allowed,
        test_3_pm_review_to_pending_client_decision_allowed,
        test_4_pending_to_approved_with_evidence_allowed,
        test_5_pending_to_rejected_with_evidence_allowed,
        test_6_pending_to_deferred_with_evidence_allowed,
        test_7_approved_to_cancelled_before_incorporation_allowed,
        test_8_full_synthetic_incorporation,
        test_9_pm_proposed_fake_feedback_id_denied,
        test_10_client_requested_missing_provenance_denied,
        test_11_approved_without_evidence_denied,
        test_12_draft_to_incorporated_denied,
        test_13_incorporated_to_cancelled_denied,
        test_14_scope_mutation_ordinary_transition_denied,
        test_15_specs_mutation_ordinary_transition_denied,
        test_16_change_log_write_before_incorporation_denied,
        test_17_change_source_mismatch_denied,
        test_18_scope_spec_version_mismatch_denied,
        test_19_change_log_version_mismatch_denied,
        test_20_incorporated_while_specs_failed_denied,
        test_21_lifecycle_history_deleted_denied,
        test_22_cr_id_reused_denied,
        test_23_project_working_branch_altered_denied,
        test_24_both_markers_active_denied,
        test_25_malformed_cr_marker_denied,
        test_26_wrong_project_cr_marker_denied,
        test_27_no_marker_on_cr_lifecycle_mutation_denied,
        test_28_unexpected_exception_fail_closed,
        test_extra_template_never_governed,
        test_extra_feedback_safe_shape_deferred_without_cr_marker,
        test_extra_unrelated_path_and_tool,
        test_extra_cr_register_lifecycle_write_requires_marker,
    ):
        fn()
    total = len(_RESULTS)
    failed = [n for n, ok in _RESULTS if not ok]
    print("\n{}/{} passed".format(total - len(failed), total))
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
