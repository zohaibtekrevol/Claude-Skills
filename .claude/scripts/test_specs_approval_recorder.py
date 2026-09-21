#!/usr/bin/env python3
"""Regression tests for .claude/scripts/specs-approval-recorder.py and its
shared core, .claude/lib/specs_approval_core.py.

Stdlib only. Run: python3 .claude/scripts/test_specs_approval_recorder.py
Exit 0 = all pass, 1 = at least one failure.

Uses temporary, synthetic project fixtures only - no real WM Trucking
project artifact is ever created, read as a mutable fixture, or modified.
The Specs fixture below is deliberately the exact same shape
test_specs_governance_guard.py's SpecsGuardNewPathTests already proves
passes `full_spec_validation` cleanly, so these tests exercise the approval
transaction against a genuinely valid Specs baseline, not a hand-waved one.
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path, register=False):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load core FIRST under the exact name the CLI/guard import it as, so every
# consumer shares one module instance (same discipline as
# test_intent_approval_recorder.py / test_change_request_incorporator.py).
iac = _load("intent_approval_core", os.path.join(HERE, "..", "lib", "intent_approval_core.py"), register=True)
qac = _load("qa_register_core", os.path.join(HERE, "..", "lib", "qa_register_core.py"), register=True)
core = _load("specs_approval_core", os.path.join(HERE, "..", "lib", "specs_approval_core.py"), register=True)
cli = _load("specs_approval_recorder", os.path.join(HERE, "specs-approval-recorder.py"))

assert cli.finalize_transaction is core.finalize_transaction, (
    "cli and core did not share one module instance - monkeypatch-based "
    "tests would silently no-op")

_RESULTS = []


def check(name, ok, detail=""):
    _RESULTS.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + "  " + name + ("" if ok else "   :: " + str(detail)))


def code_of(result):
    d = (result or {}).get("decision")
    return d.get("code") if d else None


# --------------------------------------------------------------------------- #
# Fixtures - same shape as SpecsGuardNewPathTests in test_specs_governance_guard.py
# --------------------------------------------------------------------------- #

CONFIG_YAML = '''schema_version: "1.0"

project:
  id: "SMART-BASKET"
  name: "Smart Basket"
  client: "Smart Basket / eBasket KSA"

repository:
  provider: "bitbucket"
  workspace: "devops-tekrevol"
  repository: "lets-explore-more-specs"
  verified: true
'''

INTENT_VALIDATED = '''# Intent

## Document Control

- **Project:** Smart Basket
- **Client:** Smart Basket / eBasket KSA
- **Project ID:** SMART-BASKET
- **Intent Version:** 1.0
- **Status:** VALIDATED

## 6. High-Level Product Requirements

| ID | Requirement |
|---|---|
| INT-REQ-001 | Customer app |
'''

APPROVAL_VALID = '''decision: APPROVED
approval_source: PM_EXPLICIT
artifact: docs/pmo/intent/intent.md
version: "1.0"
approved_by: Jane PM
'''


def qa_record(rid, status="RESOLVED", blocking="NO"):
    return (
        "#### {rid} - Title\n\n"
        "- **ID:** {rid}\n"
        "- **Type:** QUESTION\n"
        "- **Statement:** Statement.\n"
        "- **Why Resolution Is Required:** Needed.\n"
        "- **Source / Evidence:** SRC-001\n"
        "- **Related Intent Item:** \n"
        "- **Owner:** PM\n"
        "- **Status:** {status}\n"
        "- **Blocking:** {blocking}\n"
        "- **Resolution:** Resolved.\n"
        "- **Resolution Authority:** PM_EXPLICIT\n"
        "- **Resolution Evidence / Date:** 2026-09-11\n"
        "- **Specs Impact:** Impacts FR-001.\n\n"
    ).format(rid=rid, status=status, blocking=blocking)


QA_VALID = (
    "# Questions & Assumptions\n\n"
    "## Document Control\n\n"
    "- **Project:** Smart Basket\n"
    "- **Client:** Smart Basket / eBasket KSA\n"
    "- **Project ID:** SMART-BASKET\n"
    "- **PM:** Jane PM\n"
    "- **Date:** 2026-09-11\n"
    "- **Intent Version:** 1.0\n\n"
    "## Register\n\n"
) + qa_record("QST-001")


def build_specs(exec_auth="false", spec_version="0.1"):
    return '''# Specification: Smart Basket

## Specification Document Control

- **Project:** Smart Basket
- **Client:** Smart Basket / eBasket KSA
- **Project ID:** SMART-BASKET
- **Spec Version:** {spec_version}
- **Spec Status:** PROVISIONAL
- **Intent Version:** 1.0
- **Generated From:** docs/pmo/requirements/questions-and-assumptions.md
- **Last Updated:** 2026-09-11T00:00:00Z
- **Execution Authorized:** {exec_auth}
- **Repository:** bitbucket:devops-tekrevol/lets-explore-more-specs

## Functional Requirements

### FR-001 - Customer places an online order

- **ID:** FR-001
- **Title:** Customer places an online order
- **Module:** MOD-004 / Cart, Checkout and Payments
- **Actor(s):** B2C customer
- **Requirement:** The system lets a signed-in B2C customer confirm a cart and place an order.
- **Source Requirement:** INT-REQ-001
- **Introduced In:** 0.1
- **Last Modified In:** 0.1
- **Change Source:** INITIAL_INTENT
- **Priority:** MUST
- **Preconditions:** The customer is authenticated.
- **Trigger:** The customer confirms checkout.
- **Primary Behavior:** The system validates the cart and records the order.
- **Business Rules:** NOT_APPLICABLE: no business rule applies to this requirement
- **Validation Rules:** The cart must be non-empty.
- **Alternate / Exception Behavior:** If payment fails the order is not created.
- **Permissions:** A B2C customer may place their own order.
- **Inputs:** Cart contents.
- **Outputs:** A persisted order.
- **Dependencies:** NOT_APPLICABLE: no dependency applies to this requirement
- **Acceptance Criteria:** Given a valid cart When checkout is confirmed Then an order is created.
- **Status:** ACTIVE

## Non-Functional Requirements

## Data Requirements

| Entity | Field | Required | Validation | Related FR |
|---|---|---|---|---|
| Order | order_reference | Yes | System-generated, unique | FR-001 |

## Integrations

| Integration | Provider | FR / NFR | OPEN |
|---|---|---|---|
| N/A | N/A | N/A | N/A |

## Open Questions

| ID | Provenance | Origin | Question |
|---|---|---|---|

## Intent -> Specs Traceability

| Requirement ID | FR/NFR IDs | Coverage | Notes |
|---|---|---|---|
| INT-REQ-001 | FR-001 | COVERED |  |

## 30. Specification Change History

| Version | Date | Change Source | Changed IDs | Summary | PM Decision |
|---|---|---|---|---|---|
| {spec_version} | 2026-09-11 | INITIAL_INTENT | FR-001 | Initial provisional specification generated from validated Intent + resolved Q&A | Generated |

## Validation Summary

All active Intent requirements are represented in the Intent -> Specs
Traceability matrix. No Scope artifact was consulted or required.
'''.format(exec_auth=exec_auth, spec_version=spec_version)


def mkroot(exec_auth="false", spec_version="0.1", intent=INTENT_VALIDATED,
          approval=APPROVAL_VALID, qa=QA_VALID, config=CONFIG_YAML,
          specs=None, existing_approval=None, marker=None):
    root = tempfile.mkdtemp(prefix="specs-approval-test-")
    os.makedirs(os.path.join(root, ".pmo", "approvals"))
    os.makedirs(os.path.join(root, "docs", "pmo", "intent"))
    os.makedirs(os.path.join(root, "docs", "pmo", "specs"))
    os.makedirs(os.path.join(root, "docs", "pmo", "requirements"))
    if config is not None:
        _w(os.path.join(root, ".pmo", "project-config.yaml"), config)
    if intent is not None:
        _w(os.path.join(root, "docs", "pmo", "intent", "intent.md"), intent)
    if approval is not None:
        _w(os.path.join(root, ".pmo", "approvals", "intent-approval.yaml"), approval)
    if qa is not None:
        _w(os.path.join(root, "docs", "pmo", "requirements",
                        "questions-and-assumptions.md"), qa)
    specs_text = specs if specs is not None else build_specs(exec_auth=exec_auth, spec_version=spec_version)
    _w(os.path.join(root, "docs", "pmo", "specs", "specs.md"), specs_text)
    if existing_approval is not None:
        _w(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml"), existing_approval)
    if marker is not None:
        _w(os.path.join(root, ".pmo", "specs-approval-transaction.json"), marker)
    return root


def _w(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _snapshot(root):
    paths = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            paths.append(os.path.join(dirpath, fn))
    return {p: open(p, "rb").read() for p in sorted(paths)}


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_1_begin_eligible_produces_valid_plan():
    root = mkroot()
    try:
        result = cli.cmd_begin(root, "Muhammad Faizan", "2026-09-19", statement="Reviewed and approved.")
        check("1/begin_eligible__ACTIVE", result["status"] == "ACTIVE", result)
        check("1/plan_spec_version", result["plan"]["spec_version"] == "0.1", result)
        check("1/marker_written", os.path.exists(os.path.join(root, ".pmo", "specs-approval-transaction.json")))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_2_finalize_writes_approval_and_flips_flag_only():
    root = mkroot()
    try:
        before_specs = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        cli.cmd_begin(root, "Muhammad Faizan", "2026-09-19", statement="Reviewed and approved.")
        result = cli.cmd_finalize(root)
        check("2/finalize_approved", result["status"] == "APPROVED", result)
        approval_path = os.path.join(root, ".pmo", "approvals", "specs-approval.yaml")
        check("2/approval_file_written", os.path.exists(approval_path))
        approval_text = open(approval_path).read()
        check("2/approval_has_decision", "decision: \"APPROVED\"" in approval_text, approval_text)
        check("2/approval_has_project_id", "project_id: \"SMART-BASKET\"" in approval_text, approval_text)
        specs_text = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        check("2/exec_authorized_true", "**Execution Authorized:** true" in specs_text)
        check("2/change_source_pm_decision", "PM-DECISION" in specs_text)
        check("2/marker_removed", not os.path.exists(
            os.path.join(root, ".pmo", "specs-approval-transaction.json")))
        # Nothing else in Specs changed - same FR count, same single history row
        # for the current version (updated in place, never appended - PMO-SPEC-013).
        check("2/fr_content_unchanged", "### FR-001 - Customer places an online order" in specs_text)
        check("2/history_row_count_unchanged",
              specs_text.count("| 0.1 |") == before_specs.count("| 0.1 |"), specs_text)
        check("2/history_row_updated_in_place", "Approved - Execution Authorized" in specs_text)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_3_finalize_requires_prior_begin():
    root = mkroot()
    try:
        result = cli.cmd_finalize(root)
        check("3/finalize_without_begin__NO_TRANSACTION",
              result["status"] == "NO_TRANSACTION", result)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_4_cannot_approve_without_explicit_fields():
    root = mkroot()
    try:
        result = cli.cmd_begin(root, "", "2026-09-19")
        check("4/empty_approver__BLOCKED",
              result["status"] == "BLOCKED" and code_of(result) == "PMO-SPEC-APPROVAL-001", result)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_5_already_approved_cannot_be_reapproved():
    specs_text = build_specs(exec_auth="true").replace(
        "| INITIAL_INTENT | FR-001 | Initial provisional specification generated from validated Intent + resolved Q&A | Generated |",
        "| INITIAL_INTENT | FR-001 | Initial provisional specification generated from validated Intent + resolved Q&A | "
        "Approved - Execution Authorized per PM-DECISION: approved by Prior PM on 2026-09-12 for Spec Version 0.1. |")
    root = mkroot(exec_auth="true", specs=specs_text)
    try:
        result = cli.cmd_begin(root, "Muhammad Faizan", "2026-09-19")
        check("5/already_approved__DENY_007",
              code_of(result) == "PMO-SPEC-APPROVAL-007", result)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_6_existing_matching_approval_record_blocks_silent_rewrite():
    existing = (
        'schema_version: "1.0"\n\n'
        'decision: "APPROVED"\n'
        'approval_source: "PM_EXPLICIT"\n'
        'project_id: "SMART-BASKET"\n'
        'artifact: "docs/pmo/specs/specs.md"\n'
        'spec_version: "0.1"\n'
        'approved_by: "Prior PM"\n'
        'approved_at: "2026-09-10"\n'
    )
    root = mkroot(exec_auth="false", existing_approval=existing)
    try:
        result = cli.cmd_begin(root, "Muhammad Faizan", "2026-09-19")
        check("6/existing_matching_approval__DENY_009",
              code_of(result) == "PMO-SPEC-APPROVAL-009", result)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_7_structurally_invalid_specs_cannot_be_approved():
    broken = build_specs().replace("## Intent -> Specs Traceability", "## Something Else")
    root = mkroot(specs=broken)
    try:
        result = cli.cmd_begin(root, "Muhammad Faizan", "2026-09-19")
        check("7/structurally_invalid__DENY_004",
              code_of(result) == "PMO-SPEC-APPROVAL-004", result)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_8_missing_specs_denied():
    root = mkroot()
    os.remove(os.path.join(root, "docs", "pmo", "specs", "specs.md"))
    try:
        result = cli.cmd_begin(root, "Muhammad Faizan", "2026-09-19")
        check("8/missing_specs__DENY_003",
              code_of(result) == "PMO-SPEC-APPROVAL-003", result)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_9_double_begin_denied():
    root = mkroot()
    try:
        cli.cmd_begin(root, "Muhammad Faizan", "2026-09-19")
        result = cli.cmd_begin(root, "Muhammad Faizan", "2026-09-19")
        check("9/double_begin__DENY_016_or_012",
              code_of(result) in ("PMO-SPEC-APPROVAL-016", "PMO-SPEC-APPROVAL-012"), result)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_10_status_is_read_only():
    root = mkroot()
    try:
        cli.cmd_begin(root, "Muhammad Faizan", "2026-09-19")
        before = _snapshot(root)
        cli.cmd_status(root)
        cli.cmd_status(root)
        after = _snapshot(root)
        check("10/status_read_only", before == after)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_11_dry_run_writes_nothing():
    root = mkroot()
    try:
        before = _snapshot(root)
        result = cli.cmd_begin(root, "Muhammad Faizan", "2026-09-19", dry_run=True)
        after = _snapshot(root)
        check("11/dry_run_pass", result["status"] == "DRY_RUN_PASS", result)
        check("11/dry_run_writes_nothing", before == after)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_12_moved_target_detected():
    root = mkroot()
    try:
        cli.cmd_begin(root, "Muhammad Faizan", "2026-09-19")
        specs_path = os.path.join(root, "docs", "pmo", "specs", "specs.md")
        text = open(specs_path).read()
        _w(specs_path, text.replace("Cart, Checkout and Payments", "Cart, Checkout & Payments"))
        result = cli.cmd_finalize(root)
        check("12/moved_target__DENY_013_or_004",
              code_of(result) in ("PMO-SPEC-APPROVAL-013", "PMO-SPEC-APPROVAL-004"), result)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_13_idempotent_status_across_calls():
    root = mkroot()
    try:
        cli.cmd_begin(root, "Muhammad Faizan", "2026-09-19")
        r1 = cli.cmd_status(root)
        r2 = cli.cmd_status(root)
        check("13/status_idempotent", r1["marker"] == r2["marker"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_14_wrong_project_marker_denied():
    root = mkroot()
    try:
        marker = json.dumps({
            "transaction_type": "SPECS_APPROVAL", "transaction_id": "X",
            "project_id": "OTHER-PROJECT", "artifact": "docs/pmo/specs/specs.md",
            "spec_version": "0.1", "started_at": "2026-09-19T00:00:00Z",
            "status": "ACTIVE", "approved_by": "X", "decision_date": "2026-09-19",
        })
        _w(os.path.join(root, ".pmo", "specs-approval-transaction.json"), marker)
        result = cli.cmd_status(root)
        check("14/wrong_project__INVALID_MARKER", result["status"] == "INVALID_MARKER", result)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_15_new_spec_version_requires_fresh_approval():
    """A different Spec Version's approval must not be satisfied by a prior
    version's record - proves immutability doesn't silently apply cross-version."""
    existing = (
        'schema_version: "1.0"\n\n'
        'decision: "APPROVED"\n'
        'approval_source: "PM_EXPLICIT"\n'
        'project_id: "SMART-BASKET"\n'
        'artifact: "docs/pmo/specs/specs.md"\n'
        'spec_version: "0.1"\n'
        'approved_by: "Prior PM"\n'
        'approved_at: "2026-09-10"\n'
    )
    root = mkroot(spec_version="0.2", exec_auth="false", existing_approval=existing)
    try:
        result = cli.cmd_begin(root, "Muhammad Faizan", "2026-09-19")
        check("15/new_version_needs_fresh_approval__NOT_009",
              code_of(result) != "PMO-SPEC-APPROVAL-009", result)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    for fn in (
        test_1_begin_eligible_produces_valid_plan,
        test_2_finalize_writes_approval_and_flips_flag_only,
        test_3_finalize_requires_prior_begin,
        test_4_cannot_approve_without_explicit_fields,
        test_5_already_approved_cannot_be_reapproved,
        test_6_existing_matching_approval_record_blocks_silent_rewrite,
        test_7_structurally_invalid_specs_cannot_be_approved,
        test_8_missing_specs_denied,
        test_9_double_begin_denied,
        test_10_status_is_read_only,
        test_11_dry_run_writes_nothing,
        test_12_moved_target_detected,
        test_13_idempotent_status_across_calls,
        test_14_wrong_project_marker_denied,
        test_15_new_spec_version_requires_fresh_approval,
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
    sys.exit(main())
