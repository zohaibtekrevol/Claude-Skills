#!/usr/bin/env python3
"""Regression tests for .claude/scripts/change-request-incorporator.py and
its shared core, .claude/lib/change_request_incorporation_core.py.

Stdlib only. Run: python3 .claude/scripts/test_change_request_incorporator.py
Exit 0 = all pass, 1 = at least one failure.

Uses temporary, synthetic project fixtures only - no real Smart Basket
project artifact is ever created, read as a mutable fixture, or modified.
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# Load the core module FIRST and register it in sys.modules under the exact
# name change-request-incorporator.py imports ("change_request_incorporation_core").
# Without this, `from change_request_incorporation_core import ...` inside the
# CLI would trigger Python's normal import machinery to load a SECOND,
# independent module instance from .claude/lib (since that directory is only
# on sys.path via the CLI's own runtime sys.path.insert) - and monkeypatching
# a function on *this* test's `core` reference would then silently miss the
# CLI's actual calls, which run against that other instance's globals.
CORE_PATH = os.path.join(HERE, "..", "lib", "change_request_incorporation_core.py")
_core_spec = importlib.util.spec_from_file_location(
    "change_request_incorporation_core", CORE_PATH)
core = importlib.util.module_from_spec(_core_spec)
sys.modules["change_request_incorporation_core"] = core
_core_spec.loader.exec_module(core)

CLI_PATH = os.path.join(HERE, "change-request-incorporator.py")
_cli_spec = importlib.util.spec_from_file_location("change_request_incorporator", CLI_PATH)
cli = importlib.util.module_from_spec(_cli_spec)
_cli_spec.loader.exec_module(cli)

assert cli.finalize_transaction is core.finalize_transaction, (
    "cli and core did not share one module instance - monkeypatch-based "
    "tests would silently no-op")

_RESULTS = []


def check(name, ok, detail=""):
    _RESULTS.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + "  " + name + ("" if ok else "   :: " + str(detail)))


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


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def cr_doc(cr_id, origin="CLIENT_REQUESTED", status="APPROVED",
          batch_id="FB-2026-001", item_id="FB-2026-001-001",
          project_id="SMART-BASKET", decision="APPROVED",
          decision_date="2026-09-17", decision_by="PM",
          approval_evidence="client email 2026-09-17", reason="",
          incorporated_date="", chg_ref="", history_rows=None,
          affected_scope="SCP-REQ-010", affected_reqs="FR-020",
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
        ("Affected Scope", affected_scope),
        ("Affected Requirements", affected_reqs),
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
        history_rows = [
            "| 2026-09-14 | — | DRAFT | PM | initial creation |",
            "| 2026-09-17 | PENDING_CLIENT_DECISION | APPROVED | PM | client email |",
        ]
    lines += ["", "## Status History", "",
             "| Date | From | To | By | Evidence/Note |", "|---|---|---|---|---|"]
    lines += history_rows
    return "\n".join(lines)


def scope_doc(version, prev_version, cr_id=None):
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


def specs_doc(spec_version, cr_id=None):
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


def chg_row(chg_id, cr_id, new_scope_ver, new_spec_ver, prev_scope_ver="0.1",
           prev_spec_ver="0.1", origin="CLIENT_REQUESTED", feedback_ref=""):
    return ("| {} | SMART-BASKET::{} | 2026-09-15 | {} | {} | {} | "
           "{} | {} | {} | {} | FR-020 | | change-request-incorporator |").format(
        chg_id, chg_id, cr_id, origin, feedback_ref,
        prev_scope_ver, new_scope_ver, prev_spec_ver, new_spec_ver)


def batch_with_item(batch_id, item_id, cr_id):
    return "\n".join([
        "# Feedback Batch {}".format(batch_id), "",
        "## Document Control", "",
        "| Field | Requirement | Value |", "|---|---|---|",
        "| Feedback Batch ID | REQUIRED | {} |".format(batch_id), "",
        "## Feedback Items", "",
        "### {}".format(item_id), "",
        "| Field | Requirement | Value |", "|---|---|---|",
        "| Feedback Item ID | REQUIRED | {} |".format(item_id),
        "| Related CR | REQUIRED | {} |".format(cr_id),
    ])


def make_project(tmp, cr_id="CR-007", origin="CLIENT_REQUESTED", cr_status="APPROVED",
                 config=CONFIG_YAML, extra_cr_kwargs=None, include_feedback=True):
    for d in (
        os.path.join(tmp, ".pmo"),
        os.path.join(tmp, "docs", "pmo", "cr"),
        os.path.join(tmp, "docs", "pmo", "change-log"),
        os.path.join(tmp, "docs", "pmo", "scope"),
        os.path.join(tmp, "docs", "pmo", "specs"),
        os.path.join(tmp, "docs", "pmo", "intent"),
        os.path.join(tmp, "docs", "pmo", "feedback", "batches"),
    ):
        os.makedirs(d, exist_ok=True)
    _w(os.path.join(tmp, ".pmo", "project-config.yaml"), config)
    _w(os.path.join(tmp, "docs", "pmo", "scope", "scope-v0.1.md"), scope_doc("0.1", "NONE"))
    _w(os.path.join(tmp, "docs", "pmo", "specs", "specs.md"), specs_doc("0.1"))
    _w(os.path.join(tmp, "docs", "pmo", "change-log", "change-log.md"), changelog_doc())
    _w(os.path.join(tmp, "docs", "pmo", "intent", "intent.md"), "# Intent\n\nSome intent text.\n")
    kwargs = dict(origin=origin, status=cr_status)
    if extra_cr_kwargs:
        kwargs.update(extra_cr_kwargs)
    _w(os.path.join(tmp, "docs", "pmo", "cr", cr_id + ".md"), cr_doc(cr_id, **kwargs))
    _w(os.path.join(tmp, "docs", "pmo", "cr", "change-request-register.md"),
      "# Change Request Register\n\n"
      "| CR ID | Title | Origin | Status | Origin Feedback | Target Scope Version | "
      "Target Spec Version | Last Updated |\n|---|---|---|---|---|---|---|---|\n")
    if include_feedback and origin == "CLIENT_REQUESTED":
        _w(os.path.join(tmp, "docs", "pmo", "feedback", "feedback-tracker.md"), "# Feedback Tracker\n")
        _w(os.path.join(tmp, "docs", "pmo", "feedback", "batches", "FB-2026-001.md"),
          batch_with_item("FB-2026-001", "FB-2026-001-001", cr_id))
    return tmp


def new_tmp(prefix):
    return tempfile.mkdtemp(prefix="cr-incorporator-" + prefix + "-")


def write_full_incorporation_artifacts(tmp, plan, cr_id, origin="CLIENT_REQUESTED",
                                       feedback_ref=""):
    scope_path = os.path.join(tmp, *plan["target_scope_path"].split("/"))
    _w(scope_path, scope_doc(plan["target_scope_version"], plan["current_scope_version"], cr_id))
    specs_path = os.path.join(tmp, *plan["baseline_specs_path"].split("/"))
    _w(specs_path, specs_doc(plan["target_specs_version"], cr_id))
    changelog_path = os.path.join(tmp, *plan["change_log_path"].split("/"))
    _w(changelog_path, changelog_doc([chg_row(
        plan["target_change_log_id"], cr_id,
        plan["target_scope_version"], plan["target_specs_version"],
        plan["current_scope_version"], plan["current_specs_version"],
        origin=origin, feedback_ref=feedback_ref)]))
    return scope_path, specs_path, changelog_path


def marker_path(tmp):
    return os.path.join(tmp, ".pmo", "change-request-transaction.json")


# --------------------------------------------------------------------------- #
# 1-13: required positive scenarios
# --------------------------------------------------------------------------- #

def test_1_client_requested_preflight():
    tmp = new_tmp("t1")
    try:
        make_project(tmp, cr_id="CR-001", origin="CLIENT_REQUESTED")
        r = cli.run("begin", root=tmp, cr_id="CR-001", dry_run=True)
        check("1/client_requested_preflight__DRY_RUN_PASS", r["status"] == "DRY_RUN_PASS", r)
        check("1/plan_target_scope_version", r["plan"]["target_scope_version"] == "0.2", r.get("plan"))
        check("1/no_marker_created", not os.path.exists(marker_path(tmp)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_2_pm_proposed_preflight():
    tmp = new_tmp("t2")
    try:
        make_project(tmp, cr_id="CR-002", origin="PM_PROPOSED", include_feedback=False)
        r = cli.run("begin", root=tmp, cr_id="CR-002", dry_run=True)
        check("2/pm_proposed_preflight__DRY_RUN_PASS", r["status"] == "DRY_RUN_PASS", r)
        check("2/no_marker_created", not os.path.exists(marker_path(tmp)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3_begin_creates_valid_marker():
    tmp = new_tmp("t3")
    try:
        make_project(tmp, cr_id="CR-003")
        r = cli.run("begin", root=tmp, cr_id="CR-003")
        check("3/begin_status_active", r["status"] == "ACTIVE", r)
        check("3/marker_file_exists", os.path.exists(marker_path(tmp)))
        data = json.loads(_read(marker_path(tmp)))
        check("3/marker_transaction_type", data["transaction_type"] == "CHANGE_REQUEST_MANAGEMENT")
        check("3/marker_operation", data["operation"] == "INCORPORATION")
        check("3/marker_cr_id", data["cr_id"] == "CR-003")
        check("3/marker_valid_per_core", core.parse_cr_marker(_read(marker_path(tmp)))[1] is None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_4_to_10_full_happy_path_client_requested():
    tmp = new_tmp("t4-10")
    try:
        make_project(tmp, cr_id="CR-010", origin="CLIENT_REQUESTED")
        b = cli.run("begin", root=tmp, cr_id="CR-010")
        check("3b/begin_ok", b["status"] == "ACTIVE", b)
        plan = b["plan"]

        scope_path, specs_path, changelog_path = write_full_incorporation_artifacts(
            tmp, plan, "CR-010", origin="CLIENT_REQUESTED", feedback_ref="FB-2026-001-001")

        check("4/scope_revision_file_written", os.path.exists(scope_path))
        check("5/specs_target_version_written",
              core.field_map_from_table(*core.first_table(_read(specs_path))).get("Spec Version")
              == plan["target_specs_version"])
        check("6/chg_entry_written",
              core.find_changelog_row_for_cr(_read(changelog_path), "CR-010") is not None)

        r = cli.run("validate", root=tmp, cr_id="CR-010")
        check("7/full_reconciliation_passes", r["status"] == "PASS", r)
        check("7b/report_all_valid",
              r["report"]["scope_target_valid"] and r["report"]["specs_valid"]
              and r["report"]["change_log_valid"], r["report"])

        f = cli.run("finalize", root=tmp, cr_id="CR-010")
        check("8/finalize_incorporated", f["status"] == "INCORPORATED", f)

        cr_content = _read(os.path.join(tmp, "docs", "pmo", "cr", "CR-010.md"))
        fields = core.field_map_from_table(*core.first_table(cr_content))
        check("8b/cr_status_incorporated", fields.get("Status") == "INCORPORATED")
        hist = core.status_history_rows(cr_content)
        check("9/history_incorporated_row_appended",
              any(row.get("To", "").strip() == "INCORPORATED" for row in hist))
        check("9b/history_preserves_approval_row",
              any(row.get("To", "").strip() == "APPROVED" for row in hist))

        check("10/marker_removed_after_success", not os.path.exists(marker_path(tmp)))
        check("12/client_requested_traceability_intact",
              "FB-2026-001-001" in _read(changelog_path))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_11_already_incorporated_idempotent():
    tmp = new_tmp("t11")
    try:
        make_project(tmp, cr_id="CR-011", origin="CLIENT_REQUESTED", cr_status="INCORPORATED",
                    extra_cr_kwargs={
                        "incorporated_date": "2026-09-19", "chg_ref": "CHG-001",
                        "history_rows": [
                            "| 2026-09-14 | — | DRAFT | PM | initial |",
                            "| 2026-09-17 | PENDING_CLIENT_DECISION | APPROVED | PM | evidence |",
                            "| 2026-09-19 | APPROVED | INCORPORATED | PM | done |",
                        ]})
        r = cli.run("begin", root=tmp, cr_id="CR-011")
        check("11/begin_already_incorporated__NO_CHANGE", r["status"] == "NO_CHANGE", r)
        check("11/decision_code_021",
              r["decision"]["code"] == "PMO-CR-INTEGRATE-021", r.get("decision"))
        check("11/no_marker_created", not os.path.exists(marker_path(tmp)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_13_pm_proposed_full_happy_path():
    tmp = new_tmp("t13")
    try:
        make_project(tmp, cr_id="CR-013", origin="PM_PROPOSED", include_feedback=False)
        b = cli.run("begin", root=tmp, cr_id="CR-013")
        check("13/begin_ok", b["status"] == "ACTIVE", b)
        plan = b["plan"]
        write_full_incorporation_artifacts(tmp, plan, "CR-013", origin="PM_PROPOSED")
        r = cli.run("validate", root=tmp, cr_id="CR-013")
        check("13/validate_pass", r["status"] == "PASS", r)
        f = cli.run("finalize", root=tmp, cr_id="CR-013")
        check("13/finalize_incorporated_no_feedback_id_needed", f["status"] == "INCORPORATED", f)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 14-38: required negative scenarios
# --------------------------------------------------------------------------- #

def test_14_draft_cr_begin_blocked():
    tmp = new_tmp("t14")
    try:
        make_project(tmp, cr_id="CR-014", cr_status="DRAFT")
        r = cli.run("begin", root=tmp, cr_id="CR-014")
        check("14/draft_begin__BLOCK_002",
              r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-002", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_15_approved_missing_evidence_blocked():
    tmp = new_tmp("t15")
    try:
        make_project(tmp, cr_id="CR-015", cr_status="APPROVED",
                    extra_cr_kwargs={"approval_evidence": ""})
        r = cli.run("begin", root=tmp, cr_id="CR-015")
        check("15/missing_evidence__BLOCK_003",
              r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-003", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_16_feedback_transaction_active_blocked():
    tmp = new_tmp("t16")
    try:
        make_project(tmp, cr_id="CR-016")
        _w(os.path.join(tmp, ".pmo", "feedback-transaction.json"), json.dumps({
            "transaction_type": "FEEDBACK_MANAGEMENT", "transaction_id": "FBTX-1",
            "project_id": "SMART-BASKET", "feedback_batch_id": None,
            "started_at": "2026-09-14T20:00:00Z", "status": "ACTIVE"}))
        r = cli.run("begin", root=tmp, cr_id="CR-016")
        check("16/feedback_active__BLOCK_010",
              r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-010", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_17_second_cr_transaction_active_blocked():
    tmp = new_tmp("t17")
    try:
        make_project(tmp, cr_id="CR-017")
        first = cli.run("begin", root=tmp, cr_id="CR-017")
        check("17/first_begin_ok", first["status"] == "ACTIVE", first)
        r = cli.run("begin", root=tmp, cr_id="CR-017")
        check("17/second_begin__BLOCK_009",
              r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-009", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_18_baseline_scope_drift_blocked():
    tmp = new_tmp("t18")
    try:
        make_project(tmp, cr_id="CR-018")
        b = cli.run("begin", root=tmp, cr_id="CR-018")
        plan = b["plan"]
        baseline_path = os.path.join(tmp, *plan["baseline_scope_path"].split("/"))
        _w(baseline_path, scope_doc("0.1", "NONE") + "\ntampered")
        r = cli.run("validate", root=tmp, cr_id="CR-018")
        check("18/baseline_scope_drift__RECOVERY_011",
              r["status"] == "RECOVERY_REQUIRED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-011", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_19_baseline_specs_drift_blocked():
    tmp = new_tmp("t19")
    try:
        make_project(tmp, cr_id="CR-019")
        b = cli.run("begin", root=tmp, cr_id="CR-019")
        plan = b["plan"]
        # Scope must be correctly incorporated first so reconciliation
        # actually reaches the Specs check rather than stopping earlier.
        _w(os.path.join(tmp, *plan["target_scope_path"].split("/")),
          scope_doc(plan["target_scope_version"], plan["current_scope_version"], "CR-019"))
        specs_path = os.path.join(tmp, *plan["baseline_specs_path"].split("/"))
        _w(specs_path, specs_doc("9.9"))  # neither baseline (0.1) nor target (0.2)
        r = cli.run("validate", root=tmp, cr_id="CR-019")
        check("19/baseline_specs_drift__RECOVERY_011",
              r["status"] == "RECOVERY_REQUIRED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-011", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_20_target_scope_collision_blocked():
    # next_scope_version() always derives the target from the ACTUAL
    # current latest Scope file, so a stray pre-existing "next" file is
    # self-healingly treated as the new latest, not a collision - this is
    # correct, safe behaviour, not a gap. The collision guard exists for
    # the case that derivation is ever overridden/wrong; exercise it
    # directly so it is proven correct without relying on an otherwise
    # unreachable setup.
    tmp = new_tmp("t20")
    try:
        make_project(tmp, cr_id="CR-020")
        _w(os.path.join(tmp, "docs", "pmo", "scope", "scope-v0.2.md"), scope_doc("0.2", "0.1"))
        original = core.next_scope_version
        core.next_scope_version = lambda root: "0.2"
        try:
            r = cli.run("begin", root=tmp, cr_id="CR-020")
            check("20/target_scope_collision__BLOCK_007",
                  r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-007", r)
        finally:
            core.next_scope_version = original
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_21_chg_collision_blocked():
    tmp = new_tmp("t21")
    try:
        make_project(tmp, cr_id="CR-021")
        _w(os.path.join(tmp, "docs", "pmo", "change-log", "change-log.md"),
          changelog_doc([chg_row("CHG-001", "CR-021", "0.2", "0.2")]))
        r = cli.run("begin", root=tmp, cr_id="CR-021")
        check("21/chg_collision__BLOCK_008",
              r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-008", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_22_wrong_change_source_scope_blocked():
    tmp = new_tmp("t22")
    try:
        make_project(tmp, cr_id="CR-022")
        b = cli.run("begin", root=tmp, cr_id="CR-022")
        plan = b["plan"]
        _w(os.path.join(tmp, *plan["target_scope_path"].split("/")),
          scope_doc(plan["target_scope_version"], plan["current_scope_version"], cr_id=None))
        _w(os.path.join(tmp, *plan["baseline_specs_path"].split("/")),
          specs_doc(plan["target_specs_version"], "CR-022"))
        _w(os.path.join(tmp, *plan["change_log_path"].split("/")),
          changelog_doc([chg_row(plan["target_change_log_id"], "CR-022",
                                 plan["target_scope_version"], plan["target_specs_version"])]))
        r = cli.run("validate", root=tmp, cr_id="CR-022")
        check("22/wrong_change_source_scope__RECOVERY_017",
              r["status"] == "RECOVERY_REQUIRED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-017", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_23_wrong_change_source_specs_blocked():
    tmp = new_tmp("t23")
    try:
        make_project(tmp, cr_id="CR-023")
        b = cli.run("begin", root=tmp, cr_id="CR-023")
        plan = b["plan"]
        _w(os.path.join(tmp, *plan["target_scope_path"].split("/")),
          scope_doc(plan["target_scope_version"], plan["current_scope_version"], "CR-023"))
        _w(os.path.join(tmp, *plan["baseline_specs_path"].split("/")),
          specs_doc(plan["target_specs_version"], cr_id=None))
        _w(os.path.join(tmp, *plan["change_log_path"].split("/")),
          changelog_doc([chg_row(plan["target_change_log_id"], "CR-023",
                                 plan["target_scope_version"], plan["target_specs_version"])]))
        r = cli.run("validate", root=tmp, cr_id="CR-023")
        check("23/wrong_change_source_specs__RECOVERY_017",
              r["status"] == "RECOVERY_REQUIRED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-017", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_24_scope_version_field_mismatch_blocked():
    tmp = new_tmp("t24")
    try:
        make_project(tmp, cr_id="CR-024")
        b = cli.run("begin", root=tmp, cr_id="CR-024")
        plan = b["plan"]
        _w(os.path.join(tmp, *plan["target_scope_path"].split("/")),
          scope_doc("0.3", plan["current_scope_version"], "CR-024"))  # file says 0.3, filename/target say 0.2
        _w(os.path.join(tmp, *plan["baseline_specs_path"].split("/")),
          specs_doc(plan["target_specs_version"], "CR-024"))
        _w(os.path.join(tmp, *plan["change_log_path"].split("/")),
          changelog_doc([chg_row(plan["target_change_log_id"], "CR-024",
                                 plan["target_scope_version"], plan["target_specs_version"])]))
        r = cli.run("validate", root=tmp, cr_id="CR-024")
        check("24/scope_version_field_mismatch__RECOVERY_016",
              r["status"] == "RECOVERY_REQUIRED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-016", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_25_change_log_spec_version_mismatch_blocked():
    tmp = new_tmp("t25")
    try:
        make_project(tmp, cr_id="CR-025")
        b = cli.run("begin", root=tmp, cr_id="CR-025")
        plan = b["plan"]
        _w(os.path.join(tmp, *plan["target_scope_path"].split("/")),
          scope_doc(plan["target_scope_version"], plan["current_scope_version"], "CR-025"))
        _w(os.path.join(tmp, *plan["baseline_specs_path"].split("/")),
          specs_doc(plan["target_specs_version"], "CR-025"))
        _w(os.path.join(tmp, *plan["change_log_path"].split("/")),
          changelog_doc([chg_row(plan["target_change_log_id"], "CR-025",
                                 plan["target_scope_version"], "9.9")]))
        r = cli.run("validate", root=tmp, cr_id="CR-025")
        check("25/change_log_spec_version_mismatch__RECOVERY_016",
              r["status"] == "RECOVERY_REQUIRED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-016", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_26_change_log_scope_version_mismatch_blocked():
    tmp = new_tmp("t26")
    try:
        make_project(tmp, cr_id="CR-026")
        b = cli.run("begin", root=tmp, cr_id="CR-026")
        plan = b["plan"]
        _w(os.path.join(tmp, *plan["target_scope_path"].split("/")),
          scope_doc(plan["target_scope_version"], plan["current_scope_version"], "CR-026"))
        _w(os.path.join(tmp, *plan["baseline_specs_path"].split("/")),
          specs_doc(plan["target_specs_version"], "CR-026"))
        _w(os.path.join(tmp, *plan["change_log_path"].split("/")),
          changelog_doc([chg_row(plan["target_change_log_id"], "CR-026",
                                 "9.9", plan["target_specs_version"])]))
        r = cli.run("validate", root=tmp, cr_id="CR-026")
        check("26/change_log_scope_version_mismatch__RECOVERY_016",
              r["status"] == "RECOVERY_REQUIRED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-016", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_27_unauthorized_intent_change_blocked():
    tmp = new_tmp("t27")
    try:
        make_project(tmp, cr_id="CR-027")
        b = cli.run("begin", root=tmp, cr_id="CR-027")
        check("27/begin_ok", b["status"] == "ACTIVE", b)
        _w(os.path.join(tmp, "docs", "pmo", "intent", "intent.md"), "# Intent\n\ntampered!\n")
        r = cli.run("validate", root=tmp, cr_id="CR-027")
        check("27/intent_changed__RECOVERY_012",
              r["status"] == "RECOVERY_REQUIRED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-012", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_28_previous_scope_version_modified_after_write_blocked():
    tmp = new_tmp("t28")
    try:
        make_project(tmp, cr_id="CR-028")
        b = cli.run("begin", root=tmp, cr_id="CR-028")
        plan = b["plan"]
        write_full_incorporation_artifacts(tmp, plan, "CR-028")
        baseline_path = os.path.join(tmp, *plan["baseline_scope_path"].split("/"))
        _w(baseline_path, scope_doc(plan["current_scope_version"], "NONE") + "\nunauthorized edit")
        r = cli.run("finalize", root=tmp, cr_id="CR-028")
        check("28/previous_scope_modified__RECOVERY_011",
              r["status"] == "RECOVERY_REQUIRED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-011", r)
        cr_content = _read(os.path.join(tmp, "docs", "pmo", "cr", "CR-028.md"))
        check("28/cr_not_incorporated",
              core.field_map_from_table(*core.first_table(cr_content)).get("Status") != "INCORPORATED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_29_versioned_specs_file_blocked():
    tmp = new_tmp("t29")
    try:
        make_project(tmp, cr_id="CR-029")
        b = cli.run("begin", root=tmp, cr_id="CR-029")
        plan = b["plan"]
        write_full_incorporation_artifacts(tmp, plan, "CR-029")
        # a stray version-forked Specs file appears (never authorised)
        _w(os.path.join(tmp, "docs", "pmo", "specs", "specs-v0.2.md"),
          specs_doc(plan["target_specs_version"], "CR-029"))
        r = cli.run("validate", root=tmp, cr_id="CR-029")
        check("29/versioned_specs_file__RECOVERY_014",
              r["status"] == "RECOVERY_REQUIRED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-014", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_30_premature_incorporated_blocked():
    tmp = new_tmp("t30")
    try:
        make_project(tmp, cr_id="CR-030")
        b = cli.run("begin", root=tmp, cr_id="CR-030")
        plan = b["plan"]
        # No Scope/Specs/Change Log writes at all - but someone hand-edits
        # the CR's own Status straight to INCORPORATED, bypassing finalize.
        cr_path = os.path.join(tmp, "docs", "pmo", "cr", "CR-030.md")
        content = _read(cr_path)
        new_content, _ = core.set_field_value(content, "Status", "INCORPORATED")
        new_content = core.append_history_row(new_content, "2026-09-18", "APPROVED",
                                              "INCORPORATED", "someone", "bypassed finalize")
        _w(cr_path, new_content)
        r = cli.run("validate", root=tmp, cr_id="CR-030")
        check("30/premature_incorporated__RECOVERY_REQUIRED_NOT_NO_CHANGE",
              r["status"] == "RECOVERY_REQUIRED", r)
        check("30/not_waved_through_as_already_incorporated",
              r["decision"]["code"] != "PMO-CR-INTEGRATE-021", r.get("decision"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_31_missing_change_log_blocked():
    tmp = new_tmp("t31")
    try:
        make_project(tmp, cr_id="CR-031")
        b = cli.run("begin", root=tmp, cr_id="CR-031")
        plan = b["plan"]
        _w(os.path.join(tmp, *plan["target_scope_path"].split("/")),
          scope_doc(plan["target_scope_version"], plan["current_scope_version"], "CR-031"))
        _w(os.path.join(tmp, *plan["baseline_specs_path"].split("/")),
          specs_doc(plan["target_specs_version"], "CR-031"))
        r = cli.run("validate", root=tmp, cr_id="CR-031")
        check("31/missing_change_log__RECOVERY_020",
              r["status"] == "RECOVERY_REQUIRED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-020", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_32_scope_exists_specs_failed_recovery():
    tmp = new_tmp("t32")
    try:
        make_project(tmp, cr_id="CR-032")
        b = cli.run("begin", root=tmp, cr_id="CR-032")
        plan = b["plan"]
        _w(os.path.join(tmp, *plan["target_scope_path"].split("/")),
          scope_doc(plan["target_scope_version"], plan["current_scope_version"], "CR-032"))
        r = cli.run("validate", root=tmp, cr_id="CR-032")
        check("32/scope_only__RECOVERY_REQUIRED", r["status"] == "RECOVERY_REQUIRED", r)
        check("32/scope_valid_specs_not_yet",
              r["report"]["scope_target_valid"] and not r["report"]["specs_target_reached"], r["report"])
        marker = json.loads(_read(marker_path(tmp)))
        check("32/marker_status_recovery_required", marker["status"] == "RECOVERY_REQUIRED", marker)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_33_scope_specs_exist_changelog_failed_recovery():
    tmp = new_tmp("t33")
    try:
        make_project(tmp, cr_id="CR-033")
        b = cli.run("begin", root=tmp, cr_id="CR-033")
        plan = b["plan"]
        _w(os.path.join(tmp, *plan["target_scope_path"].split("/")),
          scope_doc(plan["target_scope_version"], plan["current_scope_version"], "CR-033"))
        _w(os.path.join(tmp, *plan["baseline_specs_path"].split("/")),
          specs_doc(plan["target_specs_version"], "CR-033"))
        r = cli.run("validate", root=tmp, cr_id="CR-033")
        check("33/scope_specs_only__RECOVERY_REQUIRED", r["status"] == "RECOVERY_REQUIRED", r)
        check("33/scope_specs_valid_changelog_not",
              r["report"]["scope_target_valid"] and r["report"]["specs_valid"]
              and not r["report"]["change_log_entry_exists"], r["report"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_34_artifacts_valid_but_finalization_write_fails_recovery():
    tmp = new_tmp("t34")
    try:
        make_project(tmp, cr_id="CR-034")
        b = cli.run("begin", root=tmp, cr_id="CR-034")
        plan = b["plan"]
        write_full_incorporation_artifacts(tmp, plan, "CR-034")

        original_write_text = core.write_text

        def boom(path, text):
            if path.endswith("CR-034.md"):
                raise RuntimeError("synthetic disk failure")
            return original_write_text(path, text)

        core.write_text = boom
        try:
            r = cli.run("finalize", root=tmp, cr_id="CR-034")
            check("34/finalize_write_failure__RECOVERY_REQUIRED",
                  r["status"] == "RECOVERY_REQUIRED"
                  and r["decision"]["code"] == "PMO-CR-INTEGRATE-018", r)
        finally:
            core.write_text = original_write_text

        cr_content = _read(os.path.join(tmp, "docs", "pmo", "cr", "CR-034.md"))
        check("34/cr_not_incorporated",
              core.field_map_from_table(*core.first_table(cr_content)).get("Status") != "INCORPORATED")
        check("34/marker_still_present_for_recovery", os.path.exists(marker_path(tmp)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_35_malformed_marker_blocked():
    tmp = new_tmp("t35")
    try:
        make_project(tmp, cr_id="CR-035")
        _w(marker_path(tmp), "{not valid json")
        r = cli.run("validate", root=tmp, cr_id="CR-035")
        check("35/malformed_marker__BLOCK_023",
              r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-023", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_36_wrong_project_marker_blocked():
    tmp = new_tmp("t36")
    try:
        make_project(tmp, cr_id="CR-036")
        b = cli.run("begin", root=tmp, cr_id="CR-036")
        check("36/begin_ok", b["status"] == "ACTIVE", b)
        data = json.loads(_read(marker_path(tmp)))
        data["project_id"] = "SOME-OTHER-PROJECT"
        _w(marker_path(tmp), json.dumps(data))
        r = cli.run("validate", root=tmp, cr_id="CR-036")
        check("36/wrong_project_marker__BLOCK_024",
              r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-024", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_37_marker_transaction_id_changed_mid_run_blocked():
    tmp = new_tmp("t37")
    try:
        make_project(tmp, cr_id="CR-037")
        b = cli.run("begin", root=tmp, cr_id="CR-037")
        check("37/begin_ok", b["status"] == "ACTIVE", b)
        # The actual enforcement point for "transaction_id changed mid-run"
        # is the shared marker-write validator both the guard and this CLI
        # rely on - proving the two surfaces agree (no Bash-side bypass).
        new_marker = dict(b["marker"])
        new_marker["transaction_id"] = "CRTX-HIJACK-0000"
        decision = core.validate_marker_write(
            "Write",
            {"file_path": marker_path(tmp), "content": json.dumps(new_marker)},
            tmp,
        )
        check("37/mid_run_transaction_id_change__BLOCK_023",
              decision is not None and decision.code == "PMO-CR-GUARD-023", decision)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_38_unexpected_exception_fail_closed():
    tmp = new_tmp("t38")
    try:
        make_project(tmp, cr_id="CR-038")
        cli.run("begin", root=tmp, cr_id="CR-038")

        original = cli.reconcile_transaction

        def boom(*a, **kw):
            raise RuntimeError("synthetic failure")

        cli.reconcile_transaction = boom
        try:
            r = cli.run("validate", root=tmp, cr_id="CR-038")
            check("38/unexpected_exception__FAIL_CLOSED_025",
                  r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-025", r)
        finally:
            cli.reconcile_transaction = original

        cr_content = _read(os.path.join(tmp, "docs", "pmo", "cr", "CR-038.md"))
        check("38/cr_untouched",
              core.field_map_from_table(*core.first_table(cr_content)).get("Status") == "APPROVED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
# extra coverage
# --------------------------------------------------------------------------- #

def test_extra_status_no_transaction():
    tmp = new_tmp("extra-status-none")
    try:
        make_project(tmp, cr_id="CR-050")
        r = cli.run("status", root=tmp)
        check("extra/status_no_transaction__NO_TRANSACTION", r["status"] == "NO_TRANSACTION", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_extra_status_different_cr_active():
    tmp = new_tmp("extra-status-diff")
    try:
        make_project(tmp, cr_id="CR-051")
        cli.run("begin", root=tmp, cr_id="CR-051")
        r = cli.run("status", root=tmp, cr_id="CR-999")
        check("extra/status_different_cr_active", r["status"] == "DIFFERENT_CR_ACTIVE", r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_extra_dry_run_never_touches_disk():
    tmp = new_tmp("extra-dryrun")
    try:
        make_project(tmp, cr_id="CR-052")
        before = sorted(
            (root, tuple(files))
            for root, _dirs, files in os.walk(tmp)
        )
        cli.run("begin", root=tmp, cr_id="CR-052", dry_run=True)
        after = sorted(
            (root, tuple(files))
            for root, _dirs, files in os.walk(tmp)
        )
        check("extra/dry_run_zero_filesystem_mutation", before == after, (before, after))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_extra_config_protection_scope_pointer_only_after_incorporation():
    tmp = new_tmp("extra-config")
    try:
        make_project(tmp, cr_id="CR-053")
        b = cli.run("begin", root=tmp, cr_id="CR-053")
        plan = b["plan"]
        write_full_incorporation_artifacts(tmp, plan, "CR-053")
        cli.run("validate", root=tmp, cr_id="CR-053")
        f = cli.run("finalize", root=tmp, cr_id="CR-053")
        check("extra/config_untouched_by_orchestrator", f["status"] == "INCORPORATED", f)
        cfg_after = _read(os.path.join(tmp, ".pmo", "project-config.yaml"))
        check("extra/config_byte_identical", cfg_after == CONFIG_YAML)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_extra_no_git_calls_in_source():
    # The real guarantee: no process-spawning API is imported/used at all,
    # so this CLI cannot invoke git (or anything else) as a subprocess -
    # checked structurally, not by grepping for the word "git" (which the
    # module's own docstring legitimately mentions while explaining this
    # exact boundary).
    src = _read(CLI_PATH)
    for forbidden in ("subprocess", "os.system(", "os.popen(", "os.exec"):
        check("extra/no_process_spawning_api::" + forbidden, forbidden not in src, src)


# --------------------------------------------------------------------------- #

def main():
    for fn in (
        test_1_client_requested_preflight,
        test_2_pm_proposed_preflight,
        test_3_begin_creates_valid_marker,
        test_4_to_10_full_happy_path_client_requested,
        test_11_already_incorporated_idempotent,
        test_13_pm_proposed_full_happy_path,
        test_14_draft_cr_begin_blocked,
        test_15_approved_missing_evidence_blocked,
        test_16_feedback_transaction_active_blocked,
        test_17_second_cr_transaction_active_blocked,
        test_18_baseline_scope_drift_blocked,
        test_19_baseline_specs_drift_blocked,
        test_20_target_scope_collision_blocked,
        test_21_chg_collision_blocked,
        test_22_wrong_change_source_scope_blocked,
        test_23_wrong_change_source_specs_blocked,
        test_24_scope_version_field_mismatch_blocked,
        test_25_change_log_spec_version_mismatch_blocked,
        test_26_change_log_scope_version_mismatch_blocked,
        test_27_unauthorized_intent_change_blocked,
        test_28_previous_scope_version_modified_after_write_blocked,
        test_29_versioned_specs_file_blocked,
        test_30_premature_incorporated_blocked,
        test_31_missing_change_log_blocked,
        test_32_scope_exists_specs_failed_recovery,
        test_33_scope_specs_exist_changelog_failed_recovery,
        test_34_artifacts_valid_but_finalization_write_fails_recovery,
        test_35_malformed_marker_blocked,
        test_36_wrong_project_marker_blocked,
        test_37_marker_transaction_id_changed_mid_run_blocked,
        test_38_unexpected_exception_fail_closed,
        test_extra_status_no_transaction,
        test_extra_status_different_cr_active,
        test_extra_dry_run_never_touches_disk,
        test_extra_config_protection_scope_pointer_only_after_incorporation,
        test_extra_no_git_calls_in_source,
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
