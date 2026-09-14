#!/usr/bin/env python3
"""Regression tests for .claude/hooks/feedback-governance-guard.py.

Stdlib only. Run: python3 .claude/hooks/test_feedback_governance_guard.py
Exit 0 = all pass, 1 = at least one failure.

Covers the A-AA scenarios from the Phase 1C specification plus unit checks
and a few extra scenarios the implementation makes directly testable. Uses
simulated PreToolUse payloads and temporary, synthetic project fixtures only
- no real Smart Basket project artifact is ever created, read as a mutable
fixture, or modified.
"""

import importlib.util
import json
import os
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "feedback-governance-guard.py")
_spec = importlib.util.spec_from_file_location("feedback_governance_guard", HOOK)
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
    '  feedback:\n'
    '    path: "docs/pmo/feedback"\n'
    '    latest_id: null\n'
    '    total_count: 0\n'
    '  change_requests:\n'
    '    path: "docs/pmo/cr"\n'
    '    latest_id: null\n'
    '  change_log:\n'
    '    path: "docs/pmo/change-log"\n'
    '    latest_id: null\n'
    '    total_count: 0\n'
    'repository:\n'
    '  provider: "bitbucket"\n'
    '  workspace: "devops-tekrevol"\n'
    '  repository: "lets-explore-more-specs"\n'
    '  working_branch: "pmo-artifacts"\n'
    'workflow:\n'
    '  current_stage: "SCOPE_READY_FOR_CLIENT_REVIEW"\n'
)


def item_block(item_id, batch_id, classification, rationale="cites SCP-REQ-010",
              confidence="HIGH", status="OPEN", related_cr="", duplicate_of="",
              original="Client said: the checkout page shows an error on submit."):
    rows = [
        ("Feedback Item ID", item_id),
        ("Logical Global ID", "SMART-BASKET::" + item_id),
        ("Parent Feedback Batch", batch_id),
        ("Original Feedback", original),
        ("Normalized Interpretation", "Checkout submit fails."),
        ("Classification", classification),
        ("Classification Rationale", rationale),
        ("Classification Confidence", confidence),
        ("Affected Artifact", "Customer App"),
        ("Affected Module", "Checkout"),
        ("Affected Existing Requirement IDs", "FR-020"),
        ("Affected Scope IDs", "SCP-REQ-010"),
        ("Priority / Severity", "HIGH" if classification == "BUG" else ""),
        ("Status", status),
        ("Duplicate Of", duplicate_of),
        ("Related CR", related_cr),
        ("Evidence / Source Reference", "email para 2"),
        ("Created Date", "2026-09-14"),
        ("Last Updated", "2026-09-14"),
    ]
    lines = ["### " + item_id, "", "| Field | Requirement | Value |", "|---|---|---|"]
    for f, v in rows:
        lines.append("| {} | REQUIRED | {} |".format(f, v))
    return "\n".join(lines)


def batch_doc(batch_id, item_count, items_text, project_id="SMART-BASKET"):
    dc = "\n".join([
        "| Field | Requirement | Value |",
        "|---|---|---|",
        "| Feedback Batch ID | REQUIRED | {} |".format(batch_id),
        "| Logical Global ID | REQUIRED | {}::{} |".format(project_id, batch_id),
        "| Project ID | REQUIRED | {} |".format(project_id),
        "| Received Date | REQUIRED | 2026-09-14 |",
        "| Recorded Date | REQUIRED | 2026-09-14 |",
        "| Received By | REQUIRED | PM |",
        "| Feedback Source | REQUIRED | EMAIL |",
        "| Source Person / Organization | REQUIRED | Client PM |",
        "| Artifact / Deliverable | REQUIRED | Customer App |",
        "| Item Count | REQUIRED | {} |".format(item_count),
        "| Classification Status | REQUIRED | CLASSIFIED |",
        "| Created By | REQUIRED | PM |",
        "| Last Updated | REQUIRED | 2026-09-14 |",
        "| Version | REQUIRED | 1 |",
    ])
    return "\n".join([
        "# Feedback Batch " + batch_id, "",
        "## Document Control", "", dc, "",
        "## Original Feedback (Verbatim)", "", "> client email text", "",
        "## Normalized Interpretation / Processing Notes", "", "notes", "",
        "## Feedback Items", "", items_text, "",
    ])


def cr_doc(cr_id, origin="CLIENT_REQUESTED", status="DRAFT",
          batch_id="FB-2026-001", item_id="FB-2026-001-001",
          project_id="SMART-BASKET"):
    if origin != "CLIENT_REQUESTED":
        batch_id = "No Feedback ID — PM_PROPOSED"
        item_id = "No Feedback ID — PM_PROPOSED"
    rows = [
        ("CR ID", cr_id),
        ("Logical Global ID", "{}::{}".format(project_id, cr_id)),
        ("Project ID", project_id),
        ("Title", "Add loyalty points redemption"),
        ("Origin", origin),
        ("Origin Feedback Batch", batch_id),
        ("Origin Feedback Item", item_id),
        ("Created By", "feedback-management"),
        ("Created Date", "2026-09-14"),
        ("Description", "Client wants a new loyalty redemption workflow."),
        ("Business Rationale", "Requested by client."),
        ("Affected Modules", "Checkout"),
        ("Affected Scope", "SCP-REQ-010"),
        ("Affected Requirements", "FR-020"),
        ("Proposed Change", "Add redemption step."),
        ("Scope Impact", "New workflow."),
        ("Technical Impact", "New endpoint."),
        ("Status", status),
    ]
    lines = ["# Change Request " + cr_id, "", "| Field | Requirement | Value |", "|---|---|---|"]
    for f, v in rows:
        lines.append("| {} | REQUIRED | {} |".format(f, v))
    lines += [
        "", "## Status History", "",
        "| Date | From | To | By | Evidence/Note |", "|---|---|---|---|---|",
        "| 2026-09-14 | — | DRAFT | feedback-management | initial creation from {} |".format(item_id),
    ]
    return "\n".join(lines)


def tracker_doc(item_rows=(), batch_rows=()):
    ir = "\n".join(item_rows) if item_rows else "| _(none)_ | | | | | | |"
    br = "\n".join(batch_rows) if batch_rows else "| _(none)_ | | | | | | |"
    return "\n".join([
        "# Feedback Tracker", "",
        "## 7. Feedback Batch Register", "",
        "| Batch ID | Received Date | Source | Artifact/Deliverable | Item Count | Classification Status | Status Last Updated |",
        "|---|---|---|---|---|---|---|",
        br, "",
        "## 8. Feedback Item Register", "",
        "| Item ID | Parent Batch | Classification | Status | Related CR | Duplicate Of | Last Updated |",
        "|---|---|---|---|---|---|---|",
        ir, "",
    ])


def _w(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


MARKER_RELPATH = os.path.join(".pmo", "feedback-transaction.json")


def marker_json(project_id="SMART-BASKET", batch_id=None, status="ACTIVE",
                transaction_id="FBTX-TEST-0001", started_at="2026-09-14T20:00:00Z"):
    return json.dumps({
        "transaction_type": "FEEDBACK_MANAGEMENT",
        "transaction_id": transaction_id,
        "project_id": project_id,
        "feedback_batch_id": batch_id,
        "started_at": started_at,
        "status": status,
    })


CR_MARKER_RELPATH = os.path.join(".pmo", "change-request-transaction.json")


def cr_marker_json(project_id="SMART-BASKET", cr_id=None, status="ACTIVE",
                   operation="STATE_TRANSITION", transaction_id="CRTX-TEST-0001",
                   started_at="2026-09-14T20:00:00Z"):
    return json.dumps({
        "transaction_type": "CHANGE_REQUEST_MANAGEMENT",
        "transaction_id": transaction_id,
        "project_id": project_id,
        "cr_id": cr_id,
        "operation": operation,
        "started_at": started_at,
        "status": status,
    })


def run(tool, tool_input, files=None, marker=None, cr_marker=None, config=CONFIG_YAML):
    """marker: None/False = no marker file. True = a default valid ACTIVE
    marker. A string = literal marker file content (for malformed/invalid
    cases). A dict = kwargs forwarded to marker_json(). cr_marker: same
    shapes, forwarded to cr_marker_json(), for the change-request marker."""
    tmp = tempfile.mkdtemp(prefix="feedback-guard-test-")
    try:
        for d in (
            os.path.join(tmp, ".pmo"),
            os.path.join(tmp, "docs", "pmo", "feedback", "batches"),
            os.path.join(tmp, "docs", "pmo", "cr"),
            os.path.join(tmp, "docs", "pmo", "change-log"),
            os.path.join(tmp, "docs", "pmo", "scope"),
            os.path.join(tmp, "docs", "pmo", "specs"),
            os.path.join(tmp, "docs", "pmo", "intent"),
            os.path.join(tmp, "docs", "pmo", "sources"),
        ):
            os.makedirs(d, exist_ok=True)
        if config is not None:
            _w(os.path.join(tmp, ".pmo", "project-config.yaml"), config)
        if marker is True:
            _w(os.path.join(tmp, MARKER_RELPATH), marker_json())
        elif isinstance(marker, dict):
            _w(os.path.join(tmp, MARKER_RELPATH), marker_json(**marker))
        elif isinstance(marker, str):
            _w(os.path.join(tmp, MARKER_RELPATH), marker)
        if cr_marker is True:
            _w(os.path.join(tmp, CR_MARKER_RELPATH), cr_marker_json())
        elif isinstance(cr_marker, dict):
            _w(os.path.join(tmp, CR_MARKER_RELPATH), cr_marker_json(**cr_marker))
        elif isinstance(cr_marker, str):
            _w(os.path.join(tmp, CR_MARKER_RELPATH), cr_marker)
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
    check("unit/split_row", mod._split_row("| a | b | c |") == ["a", "b", "c"])
    check("unit/is_separator", mod._is_separator_row(["---", ":--", "--:"]))
    check("unit/flatten", mod.flatten({"a": {"b": 1, "c": [1, 2]}}) == {"a.b": 1, "a.c": "[1, 2]"})
    before = 'workflow:\n  current_stage: "X"\nartifacts:\n  feedback:\n    latest_id: null\n'
    after = 'workflow:\n  current_stage: "Y"\nartifacts:\n  feedback:\n    latest_id: "FB-2026-001"\n'
    bad = mod.config_diff_violations(before, after, {"artifacts.feedback.latest_id"})
    check("unit/config_diff_violations", bad == ["workflow.current_stage"], bad)
    check("unit/clean_cr_ref", mod._clean_cr_ref("CR-011 (CANCELLED — reclassification)") == "CR-011")
    check("unit/clean_cr_ref_empty", mod._clean_cr_ref("none") == "")
    check("unit/batch_id_re", bool(mod.BATCH_ID_RE.match("FB-2026-001"))
          and not mod.BATCH_ID_RE.match("FB-26-1"))
    check("unit/item_id_re", bool(mod.ITEM_ID_RE.match("FB-2026-001-001"))
          and not mod.ITEM_ID_RE.match("FB-2026-001"))


# --------------------------------------------------------------------------- #
# A - AA (required scenarios)
# --------------------------------------------------------------------------- #

def test_A_bug_no_cr():
    batch_id = "FB-2026-001"
    item = item_block(batch_id + "-001", batch_id, "BUG", status="OPEN")
    doc = batch_doc(batch_id, 1, item)
    d = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                      "content": doc}, marker=True)
    check("A/bug_batch_write__ALLOW", d is None, code(d))

    tdoc = tracker_doc(
        item_rows=["| {}-001 | {} | BUG | OPEN | | | 2026-09-14 |".format(batch_id, batch_id)],
        batch_rows=["| {} | 2026-09-10 | EMAIL | Customer App | 1 | CLASSIFIED | 2026-09-14 |".format(batch_id)],
    )
    d2 = run("Write", {"file_path": "docs/pmo/feedback/feedback-tracker.md", "content": tdoc},
            files={"docs/pmo/feedback/batches/{}.md".format(batch_id): doc}, marker=True)
    check("A/bug_tracker_write__ALLOW", d2 is None, code(d2))


def test_B_enhancement_no_cr():
    batch_id = "FB-2026-002"
    item = item_block(batch_id + "-001", batch_id, "ENHANCEMENT", status="OPEN")
    doc = batch_doc(batch_id, 1, item)
    d = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                      "content": doc}, marker=True)
    check("B/enhancement_batch_write__ALLOW", d is None, code(d))

    tdoc = tracker_doc(
        item_rows=["| {}-001 | {} | ENHANCEMENT | OPEN | | | 2026-09-14 |".format(batch_id, batch_id)],
        batch_rows=["| {} | 2026-09-10 | EMAIL | Customer App | 1 | CLASSIFIED | 2026-09-14 |".format(batch_id)],
    )
    d2 = run("Write", {"file_path": "docs/pmo/feedback/feedback-tracker.md", "content": tdoc},
            files={"docs/pmo/feedback/batches/{}.md".format(batch_id): doc}, marker=True)
    check("B/enhancement_tracker_write__ALLOW", d2 is None, code(d2))


def test_C_change_request_full_chain():
    batch_id = "FB-2026-003"
    item_id = batch_id + "-001"
    item = item_block(item_id, batch_id, "CHANGE_REQUEST", related_cr="CR-001")
    bdoc = batch_doc(batch_id, 1, item)
    d1 = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                       "content": bdoc}, marker=True)
    check("C/cr_batch_write__ALLOW", d1 is None, code(d1))

    crdoc = cr_doc("CR-001", batch_id=batch_id, item_id=item_id)
    d2 = run("Write", {"file_path": "docs/pmo/cr/CR-001.md", "content": crdoc},
            files={"docs/pmo/feedback/batches/{}.md".format(batch_id): bdoc}, marker=True)
    check("C/cr_record_write__ALLOW", d2 is None, code(d2))

    regdoc = "\n".join([
        "# Change Request Register", "",
        "| CR ID | Title | Origin | Status | Origin Feedback | Target Scope Version | Target Spec Version | Last Updated |",
        "|---|---|---|---|---|---|---|---|",
        "| CR-001 | Add loyalty points redemption | CLIENT_REQUESTED | DRAFT | {} | | | 2026-09-14 |".format(item_id),
    ])
    d3 = run("Write", {"file_path": "docs/pmo/cr/change-request-register.md", "content": regdoc}, marker=True)
    check("C/cr_register_write__ALLOW", d3 is None, code(d3))

    tdoc = tracker_doc(
        item_rows=["| {} | {} | CHANGE_REQUEST | OPEN | CR-001 | | 2026-09-14 |".format(item_id, batch_id)],
        batch_rows=["| {} | 2026-09-10 | EMAIL | Customer App | 1 | CLASSIFIED | 2026-09-14 |".format(batch_id)],
    )
    d4 = run("Write", {"file_path": "docs/pmo/feedback/feedback-tracker.md", "content": tdoc},
            files={"docs/pmo/feedback/batches/{}.md".format(batch_id): bdoc}, marker=True)
    check("C/cr_tracker_write__ALLOW", d4 is None, code(d4))


def test_D_duplicate_new_id_allowed():
    batch_id = "FB-2026-004"
    item1 = item_block(batch_id + "-001", batch_id, "BUG", status="OPEN")
    item2 = item_block(batch_id + "-002", batch_id, "DUPLICATE", status="DUPLICATE",
                       duplicate_of=batch_id + "-001", related_cr="")
    doc = batch_doc(batch_id, 2, item1 + "\n\n" + item2)
    d = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                      "content": doc}, marker=True)
    check("D/duplicate_new_item_id__ALLOW", d is None, code(d))


def test_E_pm_override_creates_cr():
    batch_id = "FB-2026-005"
    item_id = batch_id + "-003"
    item = item_block(item_id, batch_id, "CHANGE_REQUEST", related_cr="CR-002")
    doc = batch_doc(batch_id, 1, item) + (
        "\n### Classification History\n\n"
        "| Date | Previous Classification | New Classification | Overridden By | Rationale |\n"
        "|---|---|---|---|---|\n"
        "| 2026-09-14 | ENHANCEMENT | CHANGE_REQUEST | PM | adds a new payment workflow |\n"
    )
    d1 = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                       "content": doc}, marker=True)
    check("E/override_batch_write__ALLOW", d1 is None, code(d1))

    crdoc = cr_doc("CR-002", batch_id=batch_id, item_id=item_id)
    d2 = run("Write", {"file_path": "docs/pmo/cr/CR-002.md", "content": crdoc},
            files={"docs/pmo/feedback/batches/{}.md".format(batch_id): doc}, marker=True)
    check("E/override_cr_write__ALLOW", d2 is None, code(d2))


def test_F_specs_mutation_denied():
    d = run("Write", {"file_path": "docs/pmo/specs/specs.md", "content": "# altered"},
            files={"docs/pmo/specs/specs.md": "# Specs\n"}, marker=True)
    check("F/specs_mutation_during_transaction__DENY_011",
          code(d) == "PMO-FEEDBACK-GUARD-011", code(d))


def test_G_scope_mutation_denied():
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.1.md", "content": "# altered"},
            marker=True)
    check("G/scope_mutation_during_transaction__DENY_010",
          code(d) == "PMO-FEEDBACK-GUARD-010", code(d))


def test_H_intent_mutation_denied():
    d = run("Write", {"file_path": "docs/pmo/intent/intent.md", "content": "# altered"},
            marker=True)
    check("H/intent_mutation_during_transaction__DENY_009",
          code(d) == "PMO-FEEDBACK-GUARD-009", code(d))


def test_I_change_log_write_denied():
    d = run("Write", {"file_path": "docs/pmo/change-log/change-log.md",
                      "content": "# Change Log\n"})
    check("I/change_log_write__DENY_012", code(d) == "PMO-FEEDBACK-GUARD-012", code(d))


def test_J_bug_with_cr_denied():
    batch_id = "FB-2026-006"
    item = item_block(batch_id + "-001", batch_id, "BUG", related_cr="CR-099")
    doc = batch_doc(batch_id, 1, item)
    d = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                      "content": doc}, marker=True)
    check("J/bug_with_cr_link__DENY_017", code(d) == "PMO-FEEDBACK-GUARD-017", code(d))


def test_K_enhancement_with_cr_denied():
    batch_id = "FB-2026-007"
    item = item_block(batch_id + "-001", batch_id, "ENHANCEMENT", related_cr="CR-098")
    doc = batch_doc(batch_id, 1, item)
    d = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                      "content": doc}, marker=True)
    check("K/enhancement_with_cr_link__DENY_017", code(d) == "PMO-FEEDBACK-GUARD-017", code(d))


def test_L_change_request_missing_cr_denied():
    batch_id = "FB-2026-008"
    item = item_block(batch_id + "-001", batch_id, "CHANGE_REQUEST", related_cr="")
    doc = batch_doc(batch_id, 1, item)
    d = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                      "content": doc}, marker=True)
    check("L/change_request_no_cr__DENY_016", code(d) == "PMO-FEEDBACK-GUARD-016", code(d))


def test_M_change_request_pm_proposed_denied():
    d = run("Write", {"file_path": "docs/pmo/cr/CR-003.md",
                      "content": cr_doc("CR-003", origin="PM_PROPOSED")}, marker=True)
    check("M/pm_proposed_cr_from_feedback__DENY_014",
          code(d) == "PMO-FEEDBACK-GUARD-014", code(d))


def test_N_change_request_approved_denied():
    d = run("Write", {"file_path": "docs/pmo/cr/CR-004.md",
                      "content": cr_doc("CR-004", status="APPROVED")}, marker=True)
    check("N/approved_cr_from_feedback__DENY_015",
          code(d) == "PMO-FEEDBACK-GUARD-015", code(d))


def test_O_related_cr_backlink_mismatch():
    batch_id = "FB-2026-009"
    item_id = batch_id + "-001"
    item = item_block(item_id, batch_id, "CHANGE_REQUEST", related_cr="CR-005")
    bdoc = batch_doc(batch_id, 1, item)
    crdoc = cr_doc("CR-005", batch_id=batch_id, item_id=batch_id + "-999")
    d = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                      "content": bdoc},
            files={"docs/pmo/cr/CR-005.md": crdoc}, marker=True)
    check("O/related_cr_backlink_mismatch__DENY_018",
          code(d) == "PMO-FEEDBACK-GUARD-018", code(d))


def test_P_cr_backlink_wrong_item():
    batch_id = "FB-2026-010"
    item_id = batch_id + "-001"
    item = item_block(item_id, batch_id, "CHANGE_REQUEST", related_cr="CR-006")
    bdoc = batch_doc(batch_id, 1, item)
    crdoc = cr_doc("CR-006", batch_id=batch_id, item_id=batch_id + "-777")
    d = run("Write", {"file_path": "docs/pmo/cr/CR-006.md", "content": crdoc},
            files={"docs/pmo/feedback/batches/{}.md".format(batch_id): bdoc}, marker=True)
    check("P/cr_backlink_wrong_item__DENY_018", code(d) == "PMO-FEEDBACK-GUARD-018", code(d))


def test_Q_duplicate_item_id_reused():
    batch_id = "FB-2026-011"
    item_id = batch_id + "-001"
    i1 = item_block(item_id, batch_id, "BUG")
    i2 = item_block(item_id, batch_id, "ENHANCEMENT")
    doc = batch_doc(batch_id, 2, i1 + "\n\n" + i2)
    d = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                      "content": doc}, marker=True)
    check("Q/duplicate_item_id__DENY_004", code(d) == "PMO-FEEDBACK-GUARD-004", code(d))


def test_R_invalid_batch_filename():
    d = run("Write", {"file_path": "docs/pmo/feedback/batches/FB-26-1.md",
                      "content": "# not a valid name\n"}, marker=True)
    check("R/invalid_batch_filename__DENY_002", code(d) == "PMO-FEEDBACK-GUARD-002", code(d))


def test_S_missing_rationale():
    batch_id = "FB-2026-012"
    item = item_block(batch_id + "-001", batch_id, "BUG", rationale="")
    doc = batch_doc(batch_id, 1, item)
    d = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                      "content": doc}, marker=True)
    check("S/missing_rationale__DENY_006", code(d) == "PMO-FEEDBACK-GUARD-006", code(d))


def test_T_invalid_confidence():
    batch_id = "FB-2026-013"
    item = item_block(batch_id + "-001", batch_id, "BUG", confidence="SUPER_HIGH")
    doc = batch_doc(batch_id, 1, item)
    d = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                      "content": doc}, marker=True)
    check("T/invalid_confidence__DENY_007", code(d) == "PMO-FEEDBACK-GUARD-007", code(d))


def test_U_tracker_batch_count_disagree():
    batch_id = "FB-2026-014"
    item = item_block(batch_id + "-001", batch_id, "BUG")
    bdoc = batch_doc(batch_id, 1, item)
    tdoc = tracker_doc(
        batch_rows=["| {} | 2026-09-10 | EMAIL | Customer App | 2 | CLASSIFIED | 2026-09-14 |".format(batch_id)],
    )
    d = run("Write", {"file_path": "docs/pmo/feedback/feedback-tracker.md", "content": tdoc},
            files={"docs/pmo/feedback/batches/{}.md".format(batch_id): bdoc}, marker=True)
    check("U/tracker_batch_count_mismatch__DENY_008", code(d) == "PMO-FEEDBACK-GUARD-008", code(d))


def test_V_config_repository_change_denied():
    new_config = CONFIG_YAML.replace('working_branch: "pmo-artifacts"',
                                     'working_branch: "some-other-branch"')
    d = run("Write", {"file_path": ".pmo/project-config.yaml", "content": new_config},
            marker=True)
    check("V/config_repository_branch_change__DENY_020",
          code(d) == "PMO-FEEDBACK-GUARD-020", code(d))


def test_W_config_workflow_stage_change_denied():
    new_config = CONFIG_YAML.replace('current_stage: "SCOPE_READY_FOR_CLIENT_REVIEW"',
                                     'current_stage: "SCOPE_BASELINED"')
    d = run("Write", {"file_path": ".pmo/project-config.yaml", "content": new_config},
            marker=True)
    check("W/config_workflow_stage_change__DENY_020",
          code(d) == "PMO-FEEDBACK-GUARD-020", code(d))


def test_X_source_evidence_rewrite_denied():
    d = run("Write", {"file_path": "docs/pmo/sources/contract/agreement.pdf.txt",
                      "content": "altered"},
            files={"docs/pmo/sources/contract/agreement.pdf.txt": "original"},
            marker=True)
    check("X/source_evidence_rewrite__DENY_019", code(d) == "PMO-FEEDBACK-GUARD-019", code(d))


def test_Y_silent_cr_cancellation_denied():
    crdoc_no_history = "\n".join([
        "# Change Request CR-007", "",
        "| Field | Requirement | Value |", "|---|---|---|",
        "| CR ID | REQUIRED | CR-007 |",
        "| Project ID | REQUIRED | SMART-BASKET |",
        "| Title | REQUIRED | Add loyalty points redemption |",
        "| Origin | REQUIRED | CLIENT_REQUESTED |",
        "| Origin Feedback Batch | REQUIRED | FB-2026-015 |",
        "| Origin Feedback Item | REQUIRED | FB-2026-015-001 |",
        "| Status | REQUIRED | CANCELLED |",
        "", "## Status History", "",
        "| Date | From | To | By | Evidence/Note |", "|---|---|---|---|---|",
        "| 2026-09-14 | — | DRAFT | feedback-management | initial creation |",
    ])
    d = run("Write", {"file_path": "docs/pmo/cr/CR-007.md", "content": crdoc_no_history}, marker=True)
    check("Y/silent_cr_cancellation_no_history__DENY_015",
          code(d) == "PMO-FEEDBACK-GUARD-015", code(d))


def test_Z_modify_cr_beyond_draft_denied():
    d = run("Write", {"file_path": "docs/pmo/cr/CR-008.md",
                      "content": cr_doc("CR-008", status="PM_REVIEW")}, marker=True)
    check("Z/modify_cr_beyond_draft__DENY_015", code(d) == "PMO-FEEDBACK-GUARD-015", code(d))


def test_AA_internal_error_fail_closed():
    original = mod.validate_batch_content

    def boom(*a, **kw):
        raise RuntimeError("synthetic failure")

    mod.validate_batch_content = boom
    try:
        batch_id = "FB-2026-016"
        item = item_block(batch_id + "-001", batch_id, "BUG")
        doc = batch_doc(batch_id, 1, item)
        d = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                          "content": doc}, marker=True)
        check("AA/internal_error__FAIL_CLOSED_021",
              code(d) == "PMO-FEEDBACK-GUARD-021", code(d))
    finally:
        mod.validate_batch_content = original


# --------------------------------------------------------------------------- #
# Extra coverage: template exemption, no-marker non-interference, misc DENY
# --------------------------------------------------------------------------- #

def test_extra_templates_never_governed():
    d1 = run("Write", {"file_path": "docs/pmo/feedback/batches/_TEMPLATE-FB.md",
                       "content": "anything at all, even malformed"})
    check("extra/template_fb_never_governed__ALLOW", d1 is None, code(d1))
    d2 = run("Write", {"file_path": "docs/pmo/cr/_TEMPLATE-CR.md",
                       "content": "anything at all, even malformed"})
    check("extra/template_cr_never_governed__ALLOW", d2 is None, code(d2))


def test_extra_no_marker_scope_specs_intent_untouched():
    d1 = run("Write", {"file_path": "docs/pmo/scope/scope-v0.2.md", "content": "# new draft"})
    check("extra/scope_write_no_transaction__ALLOW", d1 is None, code(d1))
    d2 = run("Write", {"file_path": "docs/pmo/specs/specs.md", "content": "# specs"})
    check("extra/specs_write_no_transaction__ALLOW", d2 is None, code(d2))
    d3 = run("Write", {"file_path": "docs/pmo/intent/intent.md", "content": "# intent"})
    check("extra/intent_write_no_transaction__ALLOW", d3 is None, code(d3))
    d4 = run("Write", {"file_path": ".pmo/project-config.yaml",
                       "content": CONFIG_YAML.replace(
                           'current_stage: "SCOPE_READY_FOR_CLIENT_REVIEW"',
                           'current_stage: "SCOPE_BASELINED"')})
    check("extra/config_write_no_transaction__ALLOW", d4 is None, code(d4))


def test_extra_cr_register_duplicate_row():
    regdoc = "\n".join([
        "# Change Request Register", "",
        "| CR ID | Title | Origin | Status | Origin Feedback | Target Scope Version | Target Spec Version | Last Updated |",
        "|---|---|---|---|---|---|---|---|",
        "| CR-009 | A | CLIENT_REQUESTED | DRAFT | FB-2026-017-001 | | | 2026-09-14 |",
        "| CR-009 | A again | CLIENT_REQUESTED | DRAFT | FB-2026-017-001 | | | 2026-09-14 |",
    ])
    d = run("Write", {"file_path": "docs/pmo/cr/change-request-register.md", "content": regdoc}, marker=True)
    check("extra/cr_register_duplicate_row__DENY_004", code(d) == "PMO-FEEDBACK-GUARD-004", code(d))


def test_extra_unrelated_path_and_tool():
    d1 = run("Write", {"file_path": "README.md", "content": "hi"})
    check("extra/unrelated_path__ALLOW", d1 is None, code(d1))
    d2 = mod.process({"tool_name": "Bash", "tool_input": {"command": "echo hi"},
                      "cwd": tempfile.gettempdir()})
    check("extra/bash_not_governed__ALLOW", d2 is None, code(d2))


def test_extra_batch_id_filename_mismatch_still_blocks_reuse():
    # A file whose filename doesn't match its own declared Feedback Batch ID
    # is rejected outright (GUARD-002) - which is exactly what makes true
    # cross-file ID reuse structurally unreachable: the filename IS the id.
    d = run("Write", {"file_path": "docs/pmo/feedback/batches/FB-2026-019.md",
                      "content": batch_doc("FB-2026-018", 1,
                                          item_block("FB-2026-018-001", "FB-2026-018", "BUG"))},
            marker=True)
    check("extra/batch_filename_id_mismatch__DENY_002",
          code(d) == "PMO-FEEDBACK-GUARD-002", code(d))


# --------------------------------------------------------------------------- #
# Phase 1D: transaction marker lifecycle
# --------------------------------------------------------------------------- #

def test_marker_no_marker_feedback_write_denied():
    batch_id = "FB-2026-020"
    item = item_block(batch_id + "-001", batch_id, "BUG")
    doc = batch_doc(batch_id, 1, item)
    d = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                      "content": doc})
    check("marker/no_marker_feedback_write__DENY_025",
          code(d) == "PMO-FEEDBACK-GUARD-025", code(d))


def test_marker_fresh_creation_allowed():
    d = run("Write", {"file_path": ".pmo/feedback-transaction.json",
                      "content": marker_json()})
    check("marker/fresh_creation__ALLOW", d is None, code(d))


def test_marker_malformed_denied():
    # malformed JSON as a fresh creation
    d1 = run("Write", {"file_path": ".pmo/feedback-transaction.json",
                       "content": "{not valid json"})
    check("marker/malformed_json_creation__DENY_023",
          code(d1) == "PMO-FEEDBACK-GUARD-023", code(d1))

    # missing a required field
    bad = json.dumps({"transaction_type": "FEEDBACK_MANAGEMENT",
                      "transaction_id": "FBTX-X", "project_id": "SMART-BASKET",
                      "status": "ACTIVE"})  # no started_at
    d2 = run("Write", {"file_path": ".pmo/feedback-transaction.json", "content": bad})
    check("marker/missing_field_creation__DENY_023",
          code(d2) == "PMO-FEEDBACK-GUARD-023", code(d2))

    # an existing malformed marker also blocks unrelated feedback writes
    batch_id = "FB-2026-021"
    item = item_block(batch_id + "-001", batch_id, "BUG")
    doc = batch_doc(batch_id, 1, item)
    d3 = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                       "content": doc},
            marker="{not valid json")
    check("marker/existing_malformed_blocks_feedback_write__DENY_023",
          code(d3) == "PMO-FEEDBACK-GUARD-023", code(d3))


def test_marker_wrong_project_denied():
    d1 = run("Write", {"file_path": ".pmo/feedback-transaction.json",
                       "content": marker_json(project_id="SOME-OTHER-PROJECT")})
    check("marker/wrong_project_creation__DENY_023",
          code(d1) == "PMO-FEEDBACK-GUARD-023", code(d1))

    batch_id = "FB-2026-022"
    item = item_block(batch_id + "-001", batch_id, "BUG")
    doc = batch_doc(batch_id, 1, item)
    d2 = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                       "content": doc},
            marker={"project_id": "SOME-OTHER-PROJECT"})
    check("marker/existing_wrong_project_blocks_feedback_write__DENY_023",
          code(d2) == "PMO-FEEDBACK-GUARD-023", code(d2))


def test_marker_stale_incompatible_blocked():
    batch_id = "FB-2026-023"
    item = item_block(batch_id + "-001", batch_id, "BUG")
    doc = batch_doc(batch_id, 1, item)
    d = run("Write", {"file_path": "docs/pmo/feedback/batches/{}.md".format(batch_id),
                      "content": doc},
            marker={"status": "RECOVERY_REQUIRED"})
    check("marker/recovery_required_blocks_feedback_write__DENY_025",
          code(d) == "PMO-FEEDBACK-GUARD-025", code(d))


def test_marker_overwrite_denied():
    # different transaction_id replacing an existing marker - the impersonation case
    d1 = run("Write", {"file_path": ".pmo/feedback-transaction.json",
                       "content": marker_json(transaction_id="FBTX-NEW-9999")},
            marker=True)  # existing marker uses the default transaction_id
    check("marker/different_transaction_id_overwrite__DENY_024",
          code(d1) == "PMO-FEEDBACK-GUARD-024", code(d1))

    # started_at rewritten for the SAME transaction_id
    d2 = run("Write", {"file_path": ".pmo/feedback-transaction.json",
                       "content": marker_json(started_at="2026-01-01T00:00:00Z")},
            marker=True)
    check("marker/started_at_rewrite__DENY_024",
          code(d2) == "PMO-FEEDBACK-GUARD-024", code(d2))

    # legitimate same-transaction status update IS allowed
    d3 = run("Write", {"file_path": ".pmo/feedback-transaction.json",
                       "content": marker_json(status="RECONCILING")},
            marker=True)
    check("marker/same_transaction_status_update__ALLOW", d3 is None, code(d3))


def test_marker_no_side_effect_on_deny():
    # A denied write must never mutate anything - including the marker
    # itself. Confirm the on-disk marker is byte-identical after a denial.
    tmp = tempfile.mkdtemp(prefix="feedback-guard-sideeffect-")
    try:
        os.makedirs(os.path.join(tmp, ".pmo"), exist_ok=True)
        os.makedirs(os.path.join(tmp, "docs", "pmo", "specs"), exist_ok=True)
        _w(os.path.join(tmp, ".pmo", "project-config.yaml"), CONFIG_YAML)
        marker_path = os.path.join(tmp, MARKER_RELPATH)
        _w(marker_path, marker_json())
        _w(os.path.join(tmp, "docs", "pmo", "specs", "specs.md"), "# Specs\n")
        before_marker = open(marker_path, encoding="utf-8").read()
        before_specs = open(os.path.join(tmp, "docs", "pmo", "specs", "specs.md"),
                            encoding="utf-8").read()

        d = mod.process({
            "tool_name": "Write",
            "tool_input": {"file_path": os.path.join(tmp, "docs", "pmo", "specs", "specs.md"),
                           "content": "# altered"},
            "cwd": tmp,
        })
        check("marker/deny_produces_no_side_effect__DENY",
              code(d) == "PMO-FEEDBACK-GUARD-011", code(d))

        after_marker = open(marker_path, encoding="utf-8").read()
        after_specs = open(os.path.join(tmp, "docs", "pmo", "specs", "specs.md"),
                           encoding="utf-8").read()
        check("marker/deny_leaves_marker_untouched", after_marker == before_marker)
        check("marker/deny_leaves_target_file_untouched", after_specs == before_specs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_marker_full_activation_sequence():
    """End-to-end synthetic activation test (task Section "HOOK ACTIVATION
    TEST"): no marker -> start transaction -> marker created -> valid
    Tracker/Batch write -> specs.md DENY -> Scope DENY -> valid DRAFT CR ->
    reconciliation -> marker removed -> protected files unchanged."""
    tmp = tempfile.mkdtemp(prefix="feedback-guard-e2e-")
    try:
        for d in (
            os.path.join(tmp, ".pmo"),
            os.path.join(tmp, "docs", "pmo", "feedback", "batches"),
            os.path.join(tmp, "docs", "pmo", "cr"),
            os.path.join(tmp, "docs", "pmo", "scope"),
            os.path.join(tmp, "docs", "pmo", "specs"),
            os.path.join(tmp, "docs", "pmo", "intent"),
        ):
            os.makedirs(d, exist_ok=True)
        _w(os.path.join(tmp, ".pmo", "project-config.yaml"), CONFIG_YAML)
        scope_path = os.path.join(tmp, "docs", "pmo", "scope", "scope-v0.1.md")
        specs_path = os.path.join(tmp, "docs", "pmo", "specs", "specs.md")
        intent_path = os.path.join(tmp, "docs", "pmo", "intent", "intent.md")
        _w(scope_path, "# Scope v0.1\n")
        _w(specs_path, "# Specs v0.1\n")
        _w(intent_path, "# Intent v1.0\n")
        baseline = {p: open(p, encoding="utf-8").read()
                   for p in (scope_path, specs_path, intent_path)}
        marker_path = os.path.join(tmp, MARKER_RELPATH)

        def call(tool, file_path, content):
            return mod.process({
                "tool_name": tool,
                "tool_input": {"file_path": os.path.join(tmp, *file_path.split("/")),
                               "content": content},
                "cwd": tmp,
            })

        # 1. no marker
        check("e2e/1_no_marker", not os.path.isfile(marker_path))

        # 2 & 3. start transaction -> marker created
        d = call("Write", ".pmo/feedback-transaction.json", marker_json(
            batch_id="FB-2026-024", started_at="2026-09-14T21:00:00Z"))
        check("e2e/2_start_transaction__ALLOW", d is None, code(d))
        _w(marker_path, marker_json(batch_id="FB-2026-024",
                                    started_at="2026-09-14T21:00:00Z"))
        check("e2e/3_marker_created_and_readable",
              mod.marker_status(tmp)[0] == "OPEN")

        # 4. valid Feedback Tracker + Batch write -> ALLOW
        batch_id = "FB-2026-024"
        item = item_block(batch_id + "-001", batch_id, "BUG")
        bdoc = batch_doc(batch_id, 1, item)
        d = call("Write", "docs/pmo/feedback/batches/{}.md".format(batch_id), bdoc)
        check("e2e/4_batch_write__ALLOW", d is None, code(d))
        _w(os.path.join(tmp, "docs", "pmo", "feedback", "batches", batch_id + ".md"), bdoc)
        tdoc = tracker_doc(
            item_rows=["| {}-001 | {} | BUG | OPEN | | | 2026-09-14 |".format(batch_id, batch_id)],
            batch_rows=["| {} | 2026-09-10 | EMAIL | Customer App | 1 | CLASSIFIED | 2026-09-14 |".format(batch_id)],
        )
        d = call("Write", "docs/pmo/feedback/feedback-tracker.md", tdoc)
        check("e2e/4_tracker_write__ALLOW", d is None, code(d))

        # 5. specs.md mutation -> DENY
        d = call("Write", "docs/pmo/specs/specs.md", "# altered specs")
        check("e2e/5_specs_mutation__DENY_011", code(d) == "PMO-FEEDBACK-GUARD-011", code(d))

        # 6. Scope mutation -> DENY
        d = call("Write", "docs/pmo/scope/scope-v0.1.md", "# altered scope")
        check("e2e/6_scope_mutation__DENY_010", code(d) == "PMO-FEEDBACK-GUARD-010", code(d))

        # 7. valid CLIENT_REQUESTED DRAFT CR -> ALLOW (separate CR-linked item)
        cr_item_id = batch_id + "-002"
        cr_item = item_block(cr_item_id, batch_id, "CHANGE_REQUEST", related_cr="CR-010")
        bdoc2 = batch_doc(batch_id, 2, item + "\n\n" + cr_item)
        d = call("Write", "docs/pmo/feedback/batches/{}.md".format(batch_id), bdoc2)
        check("e2e/7a_batch_updated_with_cr_item__ALLOW", d is None, code(d))
        _w(os.path.join(tmp, "docs", "pmo", "feedback", "batches", batch_id + ".md"), bdoc2)
        crdoc = cr_doc("CR-010", batch_id=batch_id, item_id=cr_item_id)
        d = call("Write", "docs/pmo/cr/CR-010.md", crdoc)
        check("e2e/7b_draft_cr_write__ALLOW", d is None, code(d))

        # 8. complete reconciliation: ACTIVE -> RECONCILING (same transaction)
        d = call("Write", ".pmo/feedback-transaction.json",
                 marker_json(batch_id="FB-2026-024", status="RECONCILING",
                            started_at="2026-09-14T21:00:00Z"))
        check("e2e/8_reconciliation_status_update__ALLOW", d is None, code(d))

        # 9. marker removed (out-of-band deletion, mirroring a real Bash `rm`)
        _w(marker_path, marker_json(batch_id="FB-2026-024", status="RECONCILING",
                                    started_at="2026-09-14T21:00:00Z"))
        os.remove(marker_path)
        check("e2e/9_marker_removed", not os.path.isfile(marker_path))
        check("e2e/9_post_removal_state_absent", mod.marker_status(tmp)[0] == "ABSENT")

        # 10. protected files unchanged throughout
        for p, before in baseline.items():
            after = open(p, encoding="utf-8").read()
            check("e2e/10_unchanged::" + os.path.basename(p), after == before)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Phase 2B: feedback <-> change-request guard reconciliation (A-F)
# --------------------------------------------------------------------------- #

def test_reconciliation_A_feedback_creates_client_requested_draft_allowed():
    batch_id = "FB-2026-025"
    item_id = batch_id + "-001"
    item = item_block(item_id, batch_id, "CHANGE_REQUEST", related_cr="CR-020")
    bdoc = batch_doc(batch_id, 1, item)
    crdoc = cr_doc("CR-020", batch_id=batch_id, item_id=item_id)
    d = run("Write", {"file_path": "docs/pmo/cr/CR-020.md", "content": crdoc},
            files={"docs/pmo/feedback/batches/{}.md".format(batch_id): bdoc},
            marker=True)
    check("recon/A_feedback_transaction_creates_client_requested_draft__ALLOW",
          d is None, code(d))


def test_reconciliation_B_feedback_creates_pm_proposed_still_denied():
    d = run("Write", {"file_path": "docs/pmo/cr/CR-021.md",
                      "content": cr_doc("CR-021", origin="PM_PROPOSED")},
            marker=True)
    check("recon/B_feedback_transaction_creates_pm_proposed__DENY_014",
          code(d) == "PMO-FEEDBACK-GUARD-014", code(d))


def test_reconciliation_C_feedback_advances_draft_to_approved_still_denied():
    d = run("Write", {"file_path": "docs/pmo/cr/CR-022.md",
                      "content": cr_doc("CR-022", status="APPROVED")},
            marker=True)
    check("recon/C_feedback_transaction_advances_to_approved__DENY_015",
          code(d) == "PMO-FEEDBACK-GUARD-015", code(d))


def test_reconciliation_D_cr_transaction_draft_to_pm_review_delegated():
    # No feedback marker; a valid, OPEN change-request marker exists. The
    # feedback guard must have no opinion at all (delegate), regardless of
    # what the write's content looks like - that content is entirely
    # change-request-governance-guard.py's business, not this guard's.
    d = run("Write", {"file_path": "docs/pmo/cr/CR-023.md",
                      "content": cr_doc("CR-023", status="PM_REVIEW")},
            cr_marker=True)
    check("recon/D_cr_transaction_draft_to_pm_review__DELEGATED",
          d is None, code(d))


def test_reconciliation_E_cr_transaction_creates_pm_proposed_delegated():
    d = run("Write", {"file_path": "docs/pmo/cr/CR-024.md",
                      "content": cr_doc("CR-024", origin="PM_PROPOSED")},
            cr_marker={"operation": "CREATE_PM_PROPOSED", "cr_id": "CR-024"})
    check("recon/E_cr_transaction_creates_pm_proposed__DELEGATED",
          d is None, code(d))


def test_reconciliation_F_no_marker_or_ambiguous_marker_denied():
    # F1: no marker of either kind at all.
    d1 = run("Write", {"file_path": "docs/pmo/cr/CR-025.md",
                       "content": cr_doc("CR-025")})
    check("recon/F1_no_marker_at_all__DENY_025",
          code(d1) == "PMO-FEEDBACK-GUARD-025", code(d1))

    # F2: an existing change-request marker that is malformed/ambiguous -
    # cr_marker_is_open() must treat it as closed, and with no feedback
    # marker either, this still denies (fail closed), never silently allows.
    d2 = run("Write", {"file_path": "docs/pmo/cr/CR-026.md",
                       "content": cr_doc("CR-026")},
            cr_marker="{not valid json")
    check("recon/F2_ambiguous_cr_marker__DENY_025",
          code(d2) == "PMO-FEEDBACK-GUARD-025", code(d2))

    # F3: a change-request marker for the WRONG project - also treated as
    # closed/not-open by cr_marker_is_open(); no feedback marker -> deny.
    d3 = run("Write", {"file_path": "docs/pmo/cr/CR-027.md",
                       "content": cr_doc("CR-027")},
            cr_marker={"project_id": "SOME-OTHER-PROJECT"})
    check("recon/F3_wrong_project_cr_marker__DENY_025",
          code(d3) == "PMO-FEEDBACK-GUARD-025", code(d3))


def test_reconciliation_change_log_delegated_during_cr_transaction():
    d = run("Write", {"file_path": "docs/pmo/change-log/change-log.md",
                      "content": "# Change Log\n"},
            cr_marker={"operation": "INCORPORATION", "cr_id": "CR-030"})
    check("recon/change_log_delegated_to_cr_guard__DELEGATED", d is None, code(d))

    d2 = run("Write", {"file_path": "docs/pmo/change-log/change-log.md",
                       "content": "# Change Log\n"},
            marker=True, cr_marker={"operation": "INCORPORATION", "cr_id": "CR-030"})
    check("recon/change_log_both_markers_active__DENY_026",
          code(d2) == "PMO-FEEDBACK-GUARD-026", code(d2))

    d3 = run("Write", {"file_path": "docs/pmo/change-log/change-log.md",
                       "content": "# Change Log\n"})
    check("recon/change_log_no_markers_still_denied__DENY_012",
          code(d3) == "PMO-FEEDBACK-GUARD-012", code(d3))


def test_reconciliation_both_markers_active_mutual_exclusion_denied():
    d = run("Write", {"file_path": "docs/pmo/cr/CR-028.md",
                      "content": cr_doc("CR-028", status="PM_REVIEW")},
            marker=True, cr_marker=True)
    check("recon/both_markers_active__DENY_026",
          code(d) == "PMO-FEEDBACK-GUARD-026", code(d))


# --------------------------------------------------------------------------- #

def main():
    test_units()
    for fn in (
        test_A_bug_no_cr, test_B_enhancement_no_cr, test_C_change_request_full_chain,
        test_D_duplicate_new_id_allowed, test_E_pm_override_creates_cr,
        test_F_specs_mutation_denied, test_G_scope_mutation_denied,
        test_H_intent_mutation_denied, test_I_change_log_write_denied,
        test_J_bug_with_cr_denied, test_K_enhancement_with_cr_denied,
        test_L_change_request_missing_cr_denied, test_M_change_request_pm_proposed_denied,
        test_N_change_request_approved_denied, test_O_related_cr_backlink_mismatch,
        test_P_cr_backlink_wrong_item, test_Q_duplicate_item_id_reused,
        test_R_invalid_batch_filename, test_S_missing_rationale,
        test_T_invalid_confidence, test_U_tracker_batch_count_disagree,
        test_V_config_repository_change_denied, test_W_config_workflow_stage_change_denied,
        test_X_source_evidence_rewrite_denied, test_Y_silent_cr_cancellation_denied,
        test_Z_modify_cr_beyond_draft_denied, test_AA_internal_error_fail_closed,
        test_extra_templates_never_governed,
        test_extra_no_marker_scope_specs_intent_untouched,
        test_extra_cr_register_duplicate_row, test_extra_unrelated_path_and_tool,
        test_extra_batch_id_filename_mismatch_still_blocks_reuse,
        test_marker_no_marker_feedback_write_denied, test_marker_fresh_creation_allowed,
        test_marker_malformed_denied, test_marker_wrong_project_denied,
        test_marker_stale_incompatible_blocked, test_marker_overwrite_denied,
        test_marker_no_side_effect_on_deny, test_marker_full_activation_sequence,
        test_reconciliation_A_feedback_creates_client_requested_draft_allowed,
        test_reconciliation_B_feedback_creates_pm_proposed_still_denied,
        test_reconciliation_C_feedback_advances_draft_to_approved_still_denied,
        test_reconciliation_D_cr_transaction_draft_to_pm_review_delegated,
        test_reconciliation_E_cr_transaction_creates_pm_proposed_delegated,
        test_reconciliation_F_no_marker_or_ambiguous_marker_denied,
        test_reconciliation_change_log_delegated_during_cr_transaction,
        test_reconciliation_both_markers_active_mutual_exclusion_denied,
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
