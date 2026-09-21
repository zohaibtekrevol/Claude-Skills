#!/usr/bin/env python3
"""Regression tests for .claude/scripts/specs-structural-repair.py and its
shared core, .claude/lib/specs_structural_repair_core.py.

Stdlib only. Run: python3 .claude/scripts/test_specs_structural_repair.py
Exit 0 = all pass, 1 = at least one failure.

Uses temporary, synthetic project fixtures only - no real WM Trucking
project artifact is ever created, read as a mutable fixture, or modified.
"""

import importlib.util
import json
import re
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
LIB_DIR = os.path.join(REPO_ROOT, ".claude", "lib")


def _load(name, path, register=False):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


iac = _load("intent_approval_core", os.path.join(LIB_DIR, "intent_approval_core.py"), register=True)
qac = _load("qa_register_core", os.path.join(LIB_DIR, "qa_register_core.py"), register=True)
crc = _load("change_request_incorporation_core", os.path.join(LIB_DIR, "change_request_incorporation_core.py"), register=True)
sac = _load("specs_approval_core", os.path.join(LIB_DIR, "specs_approval_core.py"), register=True)
core = _load("specs_structural_repair_core", os.path.join(LIB_DIR, "specs_structural_repair_core.py"), register=True)
cli = _load("specs_structural_repair", os.path.join(HERE, "specs-structural-repair.py"))
approval_cli = _load("specs_approval_recorder", os.path.join(HERE, "specs-approval-recorder.py"))

assert cli.finalize_transaction is core.finalize_transaction, (
    "cli and core did not share one module instance")

_RESULTS = []


def check(name, ok, detail=""):
    _RESULTS.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + "  " + name + ("" if ok else "   :: " + str(detail)))


def code_of(result):
    d = (result or {}).get("decision")
    return d.get("code") if d else None


# --------------------------------------------------------------------------- #
# Fixtures (same shape/identity as test_specs_approval_recorder.py, so both
# suites exercise the same real specs-governance-guard.py rules)
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

QA_ALL_RESOLVED = (
    "# Questions & Assumptions\n\n"
    "## Document Control\n\n"
    "- **Project:** Smart Basket\n"
    "- **Client:** Smart Basket\n"
    "- **Project ID:** SMART-BASKET\n"
    "- **PM:** Jane PM\n"
    "- **Date:** 2026-09-11\n"
    "- **Intent Version:** 1.0\n\n"
    "## Register\n\n"
    "#### QST-001 - Title\n\n"
    "- **ID:** QST-001\n"
    "- **Type:** QUESTION\n"
    "- **Statement:** Statement.\n"
    "- **Why Resolution Is Required:** Needed.\n"
    "- **Source / Evidence:** SRC-001\n"
    "- **Related Intent Item:** \n"
    "- **Owner:** PM\n"
    "- **Status:** RESOLVED\n"
    "- **Blocking:** NO\n"
    "- **Resolution:** Resolved.\n"
    "- **Resolution Authority:** PM_EXPLICIT\n"
    "- **Resolution Evidence / Date:** 2026-09-11\n"
    "- **Specs Impact:** Impacts FR-001.\n\n"
)


def build_specs(exec_auth="false", spec_version="0.1", include_validation_summary=False):
    tail = (
        "\n## Validation Summary\n\nAll active Intent requirements are "
        "represented.\n" if include_validation_summary else ""
    )
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
- **Business Rules:** N/A
- **Validation Rules:** The cart must be non-empty.
- **Alternate / Exception Behavior:** If payment fails the order is not created.
- **Permissions:** A B2C customer may place their own order.
- **Inputs:** Cart contents.
- **Outputs:** A persisted order.
- **Dependencies:** N/A
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
{validation_summary}'''.format(spec_version=spec_version, exec_auth=exec_auth,
                              validation_summary=tail)


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def mkroot(specs=None, exec_auth="false", spec_version="0.1", config=CONFIG_YAML,
          intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
          specs_approval=None, cr_marker=None, feedback_marker=None,
          repair_marker=None):
    root = tempfile.mkdtemp(prefix="specs-repair-test-")
    os.makedirs(os.path.join(root, ".pmo", "approvals"), exist_ok=True)
    _w(os.path.join(root, ".pmo", "project-config.yaml"), config)
    _w(os.path.join(root, "docs", "pmo", "intent", "intent.md"), intent)
    _w(os.path.join(root, ".pmo", "approvals", "intent-approval.yaml"), approval)
    _w(os.path.join(root, "docs", "pmo", "requirements",
                    "questions-and-assumptions.md"), qa)
    specs_text = specs if specs is not None else build_specs(
        exec_auth=exec_auth, spec_version=spec_version)
    _w(os.path.join(root, "docs", "pmo", "specs", "specs.md"), specs_text)
    if specs_approval is not None:
        _w(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml"), specs_approval)
    if cr_marker is not None:
        _w(os.path.join(root, ".pmo", "change-request-transaction.json"), cr_marker)
    if feedback_marker is not None:
        _w(os.path.join(root, ".pmo", "feedback-transaction.json"), feedback_marker)
    if repair_marker is not None:
        _w(os.path.join(root, ".pmo", "specs-structural-repair-transaction.json"), repair_marker)
    return root


def _cleanup(root):
    shutil.rmtree(root, ignore_errors=True)


def matching_specs_approval(spec_version="0.1"):
    return sac.render_specs_approval_yaml("SMART-BASKET", spec_version, "Jane PM", "2026-09-12")


# --------------------------------------------------------------------------- #
# POSITIVE tests
# --------------------------------------------------------------------------- #

def test_1_eligible_repair_succeeds():
    root = mkroot()
    try:
        r1 = cli.cmd_begin(root, "restore missing Validation Summary per corrected Skill contract")
        check("1/begin_active", r1["status"] == "ACTIVE", r1)
        r2 = cli.cmd_finalize(root)
        check("1/finalize_repaired", r2["status"] == "REPAIRED", r2)
    finally:
        _cleanup(root)


def test_2_validation_summary_derived_correctly():
    root = mkroot()
    try:
        cli.cmd_begin(root, "reason")
        cli.cmd_finalize(root)
        text = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        check("2/heading_present", "Validation Summary" in text)
        check("2/fr_count_correct", "1 Functional Requirement(s)" in text, text)
        check("2/no_fabricated_approval", "PM approved" not in text and "client sign" not in text.lower())
    finally:
        _cleanup(root)


def test_3_full_validation_passes_after():
    root = mkroot()
    try:
        cli.cmd_begin(root, "reason")
        cli.cmd_finalize(root)
        d = core.specs_guard.full_spec_validation(root)
        check("3/full_validation_passes", d is None, d)
    finally:
        _cleanup(root)


def test_4_5_fr_content_and_ids_byte_identical():
    root = mkroot()
    before = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
    try:
        cli.cmd_begin(root, "reason")
        cli.cmd_finalize(root)
        after = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        check("4/before_is_exact_prefix", after.startswith(before.rstrip("\n")))
        check("5/fr_block_unchanged",
              "### FR-001 - Customer places an online order" in after
              and after.count("### FR-001") == before.count("### FR-001") == 1)
    finally:
        _cleanup(root)


def test_6_7_still_unapproved_after_repair():
    root = mkroot()
    try:
        cli.cmd_begin(root, "reason")
        cli.cmd_finalize(root)
        check("6/no_approval_file", not os.path.exists(
            os.path.join(root, ".pmo", "approvals", "specs-approval.yaml")))
        after = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        check("7/exec_authorized_still_false", "**Execution Authorized:** false" in after)
    finally:
        _cleanup(root)


def test_8_9_no_cr_no_changelog_created():
    root = mkroot()
    try:
        cli.cmd_begin(root, "reason")
        cli.cmd_finalize(root)
        check("8/no_cr_dir_created", not os.path.isdir(os.path.join(root, "docs", "pmo", "cr"))
              or not os.listdir(os.path.join(root, "docs", "pmo", "cr")))
        check("9/no_changelog_dir_created", not os.path.isdir(
            os.path.join(root, "docs", "pmo", "change-log")))
    finally:
        _cleanup(root)


def test_10_subsequent_approval_still_required_and_now_possible():
    root = mkroot()
    try:
        cli.cmd_begin(root, "reason")
        cli.cmd_finalize(root)
        # Before repair this would have failed at PMO-SPEC-APPROVAL-004
        # (full_spec_validation not clean); now it should reach a clean
        # BEGIN plan - proving approval remains a SEPARATE, still-required
        # explicit action, and that the repair actually unblocked it.
        r = approval_cli.cmd_begin(root, "Jane PM", "2026-09-19", statement="Reviewed.")
        check("10/approval_now_reachable", r["status"] == "ACTIVE", r)
        after = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        check("10/still_unapproved_until_explicit_finalize",
              "**Execution Authorized:** false" in after)
    finally:
        _cleanup(root)


# --------------------------------------------------------------------------- #
# NEGATIVE tests
# --------------------------------------------------------------------------- #

def test_11_blocked_when_execution_authorized_true():
    evidence_text = build_specs(exec_auth="true", include_validation_summary=True).replace(
        "| Generated |",
        "| Approved - Execution Authorized per PM-DECISION: approved by "
        "Jane PM on 2026-09-12 for Spec Version 0.1. |")
    root = mkroot(specs=evidence_text)
    try:
        r = cli.cmd_begin(root, "reason")
        check("11/blocked_exec_authorized_true",
              code_of(r) == "PMO-SPEC-REPAIR-003", r)
    finally:
        _cleanup(root)


def test_12_blocked_when_matching_approval_exists():
    approved_text = build_specs(exec_auth="true", include_validation_summary=True).replace(
        "| Generated |",
        "| Approved - Execution Authorized per PM-DECISION: approved by "
        "Jane PM on 2026-09-12 for Spec Version 0.1. |")
    root = mkroot(specs=approved_text, specs_approval=matching_specs_approval())
    try:
        r = cli.cmd_begin(root, "reason")
        check("12/blocked_matching_approval_exists",
              code_of(r) in ("PMO-SPEC-REPAIR-003", "PMO-SPEC-REPAIR-004"), r)
    finally:
        _cleanup(root)


def test_13_fr_text_change_rejected_by_preservation_check():
    before = build_specs()
    after = before.replace(
        "The system validates the cart and records the order.",
        "The system validates the cart and records the order immediately.")
    ok, reason = core.content_preserves_existing(before, after)
    check("13/fr_text_change_rejected", not ok, reason)


def test_14_fr_id_change_rejected():
    before = build_specs()
    after = before.replace("### FR-001", "### FR-002").replace(
        "- **ID:** FR-001", "- **ID:** FR-002")
    ok, reason = core.content_preserves_existing(before, after)
    check("14/fr_id_change_rejected", not ok, reason)


def test_15_business_rule_change_rejected():
    before = build_specs().replace(
        "## Non-Functional Requirements\n",
        "## Non-Functional Requirements\n\n## Business Rules\n\n"
        "| ID | Rule |\n|---|---|\n| BR-001 | Original rule text |\n")
    after = before.replace("| BR-001 | Original rule text |",
                           "| BR-001 | Changed rule text |")
    ok, reason = core.content_preserves_existing(before, after)
    check("15/business_rule_change_rejected", not ok, reason)


def test_16_nfr_change_rejected():
    before = build_specs().replace(
        "## Non-Functional Requirements\n",
        "## Non-Functional Requirements\n\n### NFR-001 - Latency\n\n"
        "- **Requirement:** p95 under 500ms\n")
    after = before.replace("p95 under 500ms", "p95 under 300ms")
    ok, reason = core.content_preserves_existing(before, after)
    check("16/nfr_change_rejected", not ok, reason)


def test_17_deferred_tbd_resolution_rejected():
    before = build_specs().replace(
        "| N/A | N/A | N/A | N/A |",
        "| Weather | TBD (QST-007) | N/A | QST-007 |")
    after = before.replace("| Weather | TBD (QST-007) | N/A | QST-007 |",
                           "| Weather | AccuWeather | N/A |  |")
    ok, reason = core.content_preserves_existing(before, after)
    check("17/tbd_resolution_rejected", not ok, reason)


def test_18_source_traceability_change_rejected():
    before = build_specs()
    after = before.replace(
        "- **Source Requirement:** INT-REQ-001\n",
        "- **Source Requirement:** INT-REQ-002\n")
    ok, reason = core.content_preserves_existing(before, after)
    check("18/traceability_change_rejected", not ok, reason)


def test_19_intent_mapping_change_rejected():
    before = build_specs()
    after = before.replace(
        "| INT-REQ-001 | FR-001 | COVERED |  |",
        "| INT-REQ-001 | FR-001 | PARTIALLY_COVERED | now blocked |")
    ok, reason = core.content_preserves_existing(before, after)
    check("19/intent_mapping_change_rejected", not ok, reason)


def test_20_qa_mapping_change_rejected():
    before = build_specs().replace(
        "| N/A | N/A | N/A | N/A |", "| N/A | N/A | N/A | QST-005 |")
    after = before.replace("| N/A | N/A | N/A | QST-005 |",
                           "| N/A | N/A | N/A | QST-009 |")
    ok, reason = core.content_preserves_existing(before, after)
    check("20/qa_mapping_change_rejected", not ok, reason)


def test_21_version_change_rejected():
    before = build_specs(spec_version="0.1")
    after = before.replace("- **Spec Version:** 0.1", "- **Spec Version:** 0.2")
    ok, reason = core.content_preserves_existing(before, after)
    check("21/version_change_rejected", not ok, reason)


def test_22_new_requirement_introduction_rejected():
    before = build_specs()
    tail = before.rstrip("\n") + "\n\n---\n\n### FR-999 - Sneaky new requirement\n\n- **ID:** FR-999\n"
    ok, reason = core.content_preserves_existing(before, tail)
    check("22/new_requirement_rejected", not ok, reason)


def test_23_scope_expansion_new_section_rejected():
    before = build_specs()
    tail = before.rstrip("\n") + "\n\n---\n\n## New Feature Module\n\nExpanded scope text.\n"
    ok, reason = core.content_preserves_existing(before, tail)
    check("23/scope_expansion_rejected", not ok, reason)


def test_24_unrelated_typo_edit_rejected():
    before = build_specs()
    after = before.replace("Cart, Checkout and Payments", "Cart, Checkout & Payments")
    ok, reason = core.content_preserves_existing(before, after)
    check("24/unrelated_edit_rejected", not ok, reason)


def test_25_cr_marker_masquerade_rejected():
    # (a) an OPEN CR transaction blocks BEGIN outright.
    root = mkroot(cr_marker=json.dumps({
        "transaction_type": "CHANGE_REQUEST_MANAGEMENT", "transaction_id": "CRTX-1",
        "project_id": "SMART-BASKET", "cr_id": "CR-001", "operation": "STATE_TRANSITION",
        "started_at": "2026-09-19T00:00:00Z", "status": "ACTIVE"}))
    try:
        r = cli.cmd_begin(root, "reason")
        check("25a/open_cr_blocks_repair", code_of(r) == "PMO-SPEC-REPAIR-009", r)
    finally:
        _cleanup(root)
    # (b) a marker claiming operation=INCORPORATION is never accepted as a
    # valid STRUCTURAL_REPAIR marker.
    fake = json.dumps({
        "transaction_type": "SPECS_STRUCTURAL_REPAIR", "transaction_id": "X",
        "project_id": "SMART-BASKET", "artifact": "docs/pmo/specs/specs.md",
        "spec_version": "0.1", "operation": "INCORPORATION", "reason": "r",
        "started_at": "2026-09-19T00:00:00Z", "status": "ACTIVE",
        "pre_repair_validation_code": "PMO-SPEC-003",
        "pre_repair_validation_message": "m",
        "repair_classes": ["MISSING_REQUIRED_SECTION"],
        "missing_sections": ["Validation Summary"],
        "metadata_fixes": {},
        "specs_hash_before": "x"})
    data, err = core.parse_marker(fake)
    check("25b/incorporation_operation_marker_rejected",
          err is not None and "STRUCTURAL_REPAIR" in err, err)


# --------------------------------------------------------------------------- #
# Additional integrity checks
# --------------------------------------------------------------------------- #

def test_26_status_is_read_only():
    root = mkroot()
    try:
        cli.cmd_begin(root, "reason")
        before = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        cli.cmd_status(root)
        cli.cmd_status(root)
        after = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        check("26/status_read_only", before == after)
    finally:
        _cleanup(root)


def test_27_dry_run_writes_nothing():
    root = mkroot()
    try:
        before_marker = os.path.exists(os.path.join(root, ".pmo", "specs-structural-repair-transaction.json"))
        before_specs = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        r = cli.cmd_begin(root, "reason", dry_run=True)
        after_marker = os.path.exists(os.path.join(root, ".pmo", "specs-structural-repair-transaction.json"))
        after_specs = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        check("27/dry_run_pass", r["status"] == "DRY_RUN_PASS", r)
        check("27/no_marker_written", before_marker == after_marker == False)
        check("27/no_specs_written", before_specs == after_specs)
    finally:
        _cleanup(root)


def test_28_already_valid_specs_has_nothing_to_repair():
    root = mkroot(specs=build_specs(include_validation_summary=True))
    try:
        r = cli.cmd_begin(root, "reason")
        check("28/nothing_to_repair", code_of(r) == "PMO-SPEC-REPAIR-005", r)
    finally:
        _cleanup(root)


def malformed_generated_from_specs(include_validation_summary=True, spec_version="0.1"):
    """Mirrors the real WM Trucking defect shape exactly: a combined
    reference + descriptive/version text inside the path field."""
    text = build_specs(spec_version=spec_version,
                       include_validation_summary=include_validation_summary)
    return text.replace(
        "- **Generated From:** docs/pmo/requirements/questions-and-assumptions.md\n",
        "- **Generated From:** docs/pmo/requirements/questions-and-assumptions.md "
        "(+ docs/pmo/intent/intent.md v1.0)\n",
    )


# --------------------------------------------------------------------------- #
# DOCUMENT_CONTROL_METADATA_REPAIR - positive tests
# --------------------------------------------------------------------------- #

def test_30_malformed_generated_from_corrected_to_canonical():
    root = mkroot(specs=malformed_generated_from_specs())
    try:
        r1 = cli.cmd_begin(root, "correct malformed Generated From")
        check("30/begin_active", r1["status"] == "ACTIVE", r1)
        check("30/repair_class_metadata",
              core.REPAIR_CLASS_METADATA in r1["plan"]["repair_classes"], r1)
        r2 = cli.cmd_finalize(root)
        check("30/finalize_repaired", r2["status"] == "REPAIRED", r2)
        text = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        check("30/canonical_value_written",
              "- **Generated From:** docs/pmo/requirements/questions-and-assumptions.md\n" in text,
              text)
        check("30/no_descriptive_suffix_remains", "(+ docs/pmo" not in text, text)
    finally:
        _cleanup(root)


def test_31_generated_from_fix_changes_nothing_substantive():
    root = mkroot(specs=malformed_generated_from_specs())
    before = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
    try:
        cli.cmd_begin(root, "reason")
        cli.cmd_finalize(root)
        after = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        ok, changed_fields = core.metadata_fix_is_field_only(
            before, after.split("\n\n---\n\n")[0] if "Validation Summary" in after
            else after, core.PERMITTED_METADATA_FIELDS)
        # Compare only up through the (unchanged) pre-existing body - the
        # Validation Summary append is a separate, already-proven check.
        check("31/only_generated_from_field_changed",
              ok and changed_fields == {"Generated From"}, (ok, changed_fields))
        check("31/fr_block_unchanged", "### FR-001 - Customer places an online order" in after)
    finally:
        _cleanup(root)


def test_32_both_repair_classes_applied_sequentially():
    root = mkroot(specs=malformed_generated_from_specs(include_validation_summary=False))
    try:
        r1 = cli.cmd_begin(root, "repair both missing section and malformed metadata")
        check("32/both_classes_detected",
              set(r1["plan"]["repair_classes"]) ==
              {core.REPAIR_CLASS_MISSING_SECTION, core.REPAIR_CLASS_METADATA}, r1)
        r2 = cli.cmd_finalize(root)
        check("32/finalize_repaired", r2["status"] == "REPAIRED", r2)
        check("32/report_lists_both_classes",
              set(r2["report"]["repair_classes"]) ==
              {core.REPAIR_CLASS_MISSING_SECTION, core.REPAIR_CLASS_METADATA}, r2)
    finally:
        _cleanup(root)


def test_33_full_validation_passes_after_combined_repair():
    root = mkroot(specs=malformed_generated_from_specs(include_validation_summary=False))
    try:
        cli.cmd_begin(root, "reason")
        cli.cmd_finalize(root)
        d = core.specs_guard.full_spec_validation(root)
        check("33/full_validation_passes", d is None, d)
    finally:
        _cleanup(root)


def test_34_still_unapproved_after_combined_repair():
    root = mkroot(specs=malformed_generated_from_specs(include_validation_summary=False))
    try:
        cli.cmd_begin(root, "reason")
        cli.cmd_finalize(root)
        check("34/no_approval_file", not os.path.exists(
            os.path.join(root, ".pmo", "approvals", "specs-approval.yaml")))
        after = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        check("34/exec_authorized_still_false", "**Execution Authorized:** false" in after)
    finally:
        _cleanup(root)


def test_35_cr_not_required_for_metadata_repair():
    root = mkroot(specs=malformed_generated_from_specs())
    try:
        cli.cmd_begin(root, "reason")
        cli.cmd_finalize(root)
        check("35/no_cr_marker_created", not os.path.exists(
            os.path.join(root, ".pmo", "change-request-transaction.json")))
        check("35/no_cr_files", not os.path.isdir(os.path.join(root, "docs", "pmo", "cr"))
              or not os.listdir(os.path.join(root, "docs", "pmo", "cr")))
    finally:
        _cleanup(root)


# --------------------------------------------------------------------------- #
# DOCUMENT_CONTROL_METADATA_REPAIR - negative tests (metadata_fix_is_field_only)
# --------------------------------------------------------------------------- #

def test_36_project_change_rejected():
    before = malformed_generated_from_specs()
    after = before.replace("- **Project:** Smart Basket\n", "- **Project:** Renamed Co\n")
    ok, reason = core.metadata_fix_is_field_only(before, after, core.PERMITTED_METADATA_FIELDS)
    check("36/project_change_rejected", not ok, reason)


def test_37_project_id_change_rejected():
    before = malformed_generated_from_specs()
    after = before.replace("- **Project ID:** SMART-BASKET\n", "- **Project ID:** OTHER-ID\n")
    ok, reason = core.metadata_fix_is_field_only(before, after, core.PERMITTED_METADATA_FIELDS)
    check("37/project_id_change_rejected", not ok, reason)


def test_38_pm_identity_change_rejected():
    before = malformed_generated_from_specs().replace(
        "- **Repository:**", "- **PM:** Jane PM\n- **Repository:**")
    after = before.replace("- **PM:** Jane PM\n", "- **PM:** Someone Else\n")
    ok, reason = core.metadata_fix_is_field_only(before, after, core.PERMITTED_METADATA_FIELDS)
    check("38/pm_identity_change_rejected", not ok, reason)


def test_39_specs_version_change_rejected_by_metadata_check():
    before = malformed_generated_from_specs(spec_version="0.1")
    after = before.replace("- **Spec Version:** 0.1", "- **Spec Version:** 0.2")
    ok, reason = core.metadata_fix_is_field_only(before, after, core.PERMITTED_METADATA_FIELDS)
    check("39/spec_version_change_rejected", not ok, reason)


def test_40_specs_status_change_rejected():
    before = malformed_generated_from_specs()
    after = before.replace("- **Spec Status:** PROVISIONAL", "- **Spec Status:** ACTIVE")
    ok, reason = core.metadata_fix_is_field_only(before, after, core.PERMITTED_METADATA_FIELDS)
    check("40/spec_status_change_rejected", not ok, reason)


def test_41_execution_authorized_change_rejected_by_metadata_check():
    before = malformed_generated_from_specs()
    after = before.replace("- **Execution Authorized:** false", "- **Execution Authorized:** true")
    ok, reason = core.metadata_fix_is_field_only(before, after, core.PERMITTED_METADATA_FIELDS)
    check("41/execution_authorized_change_rejected", not ok, reason)


def test_42_requirement_content_change_rejected_by_metadata_check():
    before = malformed_generated_from_specs()
    after = before.replace(
        "The system validates the cart and records the order.",
        "The system validates the cart and records the order instantly.")
    ok, reason = core.metadata_fix_is_field_only(before, after, core.PERMITTED_METADATA_FIELDS)
    check("42/requirement_content_change_rejected", not ok, reason)


def test_43_requirement_id_change_rejected_by_metadata_check():
    before = malformed_generated_from_specs()
    after = before.replace("### FR-001", "### FR-002")
    ok, reason = core.metadata_fix_is_field_only(before, after, core.PERMITTED_METADATA_FIELDS)
    check("43/requirement_id_change_rejected", not ok, reason)


def test_44_business_rule_change_rejected_by_metadata_check():
    before = malformed_generated_from_specs().replace(
        "## Non-Functional Requirements\n",
        "## Non-Functional Requirements\n\n## Business Rules\n\n"
        "| ID | Rule |\n|---|---|\n| BR-001 | Original |\n")
    after = before.replace("| BR-001 | Original |", "| BR-001 | Changed |")
    ok, reason = core.metadata_fix_is_field_only(before, after, core.PERMITTED_METADATA_FIELDS)
    check("44/business_rule_change_rejected", not ok, reason)


def test_45_nfr_change_rejected_by_metadata_check():
    before = malformed_generated_from_specs().replace(
        "## Non-Functional Requirements\n",
        "## Non-Functional Requirements\n\n### NFR-001 - Latency\n\n"
        "- **Requirement:** p95 under 500ms\n")
    after = before.replace("p95 under 500ms", "p95 under 100ms")
    ok, reason = core.metadata_fix_is_field_only(before, after, core.PERMITTED_METADATA_FIELDS)
    check("45/nfr_change_rejected", not ok, reason)


def test_46_qa_decision_change_rejected_by_metadata_check():
    before = malformed_generated_from_specs().replace(
        "| N/A | N/A | N/A | N/A |", "| N/A | N/A | N/A | QST-005 |")
    after = before.replace("| N/A | N/A | N/A | QST-005 |", "| N/A | N/A | N/A | QST-009 |")
    ok, reason = core.metadata_fix_is_field_only(before, after, core.PERMITTED_METADATA_FIELDS)
    check("46/qa_decision_change_rejected", not ok, reason)


def test_47_intent_mapping_change_rejected_by_metadata_check():
    before = malformed_generated_from_specs()
    after = before.replace(
        "| INT-REQ-001 | FR-001 | COVERED |  |",
        "| INT-REQ-001 | FR-001 | PARTIALLY_COVERED | now blocked |")
    ok, reason = core.metadata_fix_is_field_only(before, after, core.PERMITTED_METADATA_FIELDS)
    check("47/intent_mapping_change_rejected", not ok, reason)


def test_48_source_semantics_change_rejected_by_metadata_check():
    before = malformed_generated_from_specs()
    after = before.replace(
        "- **Source Requirement:** INT-REQ-001\n",
        "- **Source Requirement:** INT-REQ-002\n")
    ok, reason = core.metadata_fix_is_field_only(before, after, core.PERMITTED_METADATA_FIELDS)
    check("48/source_semantics_change_rejected", not ok, reason)


def test_49_arbitrary_valid_metadata_field_change_rejected():
    """A field OTHER than the whitelisted one, even a harmless-looking
    metadata change (e.g. Repository), must be rejected - the whitelist is
    exactly one field, never 'any Document Control field'."""
    before = malformed_generated_from_specs()
    after = before.replace(
        "- **Repository:** bitbucket:devops-tekrevol/lets-explore-more-specs",
        "- **Repository:** bitbucket:devops-tekrevol/renamed-repo")
    ok, reason = core.metadata_fix_is_field_only(before, after, core.PERMITTED_METADATA_FIELDS)
    check("49/arbitrary_valid_field_change_rejected", not ok, reason)


def test_50_repair_requires_evidence_field_is_invalid():
    """A field that is already valid must never be 'repaired' - the
    governed begin path refuses even to propose a fix for it."""
    root = mkroot(specs=build_specs())  # already-canonical Generated From
    try:
        text = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        invalid, _cur = core._generated_from_invalid(root, text)
        check("50/valid_field_not_flagged_invalid", invalid is False, invalid)
    finally:
        _cleanup(root)


def test_29_unsupported_failure_class_rejected():
    # Fails validation for a reason STRUCTURAL_REPAIR cannot address
    # (unsupported requirement, PMO-SPEC-015) rather than a missing section.
    unsupported = build_specs(include_validation_summary=True).replace(
        "- **Source Requirement:** INT-REQ-001\n",
        "- **Source Requirement:** INT-REQ-099\n").replace(
        "- **Change Source:** INITIAL_INTENT\n", "- **Change Source:** UNSOURCED\n")
    root = mkroot(specs=unsupported)
    try:
        r = cli.cmd_begin(root, "reason")
        check("29/unsupported_failure_class_rejected",
              code_of(r) == "PMO-SPEC-REPAIR-006", r)
    finally:
        _cleanup(root)


# --------------------------------------------------------------------------- #
# Governed recovery (abort) + NEW-lifecycle Change Source provenance
# --------------------------------------------------------------------------- #

def _specs_path(root):
    return os.path.join(root, "docs", "pmo", "specs", "specs.md")


def _marker_path(root):
    return os.path.join(root, ".pmo", "specs-structural-repair-transaction.json")


def _failed_finalize_root():
    """A project whose repair fails closed at finalize (PMO-SPEC-013 on an
    initial row carrying an unrepairable non-canonical Change Source), leaving the marker."""
    root = mkroot()
    text = open(_specs_path(root)).read()
    text = text.replace("| 2026-09-11 | INITIAL_INTENT | FR-001 | Initial provisional "
                        "specification generated from validated Intent + resolved Q&A |",
                        "| 2026-09-11 | BOGUS_SOURCE | FR-001 | Initial provisional "
                        "specification baseline |")
    _w(_specs_path(root), text)
    return root


def test_51_failed_transaction_can_be_governedly_aborted():
    root = _failed_finalize_root()
    try:
        b = cli.cmd_begin(root, "repair")
        f = cli.cmd_finalize(root)
        check("51/begin_active", b["status"] == "ACTIVE", b)
        check("51/finalize_failed_closed", f["status"] == "RECOVERY_REQUIRED", f)
        check("51/marker_left_behind", os.path.exists(_marker_path(root)))
        before = open(_specs_path(root), "rb").read()
        a = cli.cmd_abort(root, "finalize failed closed")
        check("51/aborted", a["status"] == "ABORTED", a)
        check("51/marker_removed", not os.path.exists(_marker_path(root)))
        check("51/specs_byte_identical", open(_specs_path(root), "rb").read() == before)
        check("51/no_approval_created", not os.path.exists(
            os.path.join(root, ".pmo", "approvals", "specs-approval.yaml")))
        check("51/no_cr_marker", not os.path.exists(
            os.path.join(root, ".pmo", "change-request-transaction.json")))
        check("51/status_no_transaction", cli.cmd_status(root)["status"] == "NO_TRANSACTION")
    finally:
        _cleanup(root)


def test_52_abort_requires_reason_and_marker():
    root = mkroot()
    try:
        check("52/no_marker_no_transaction",
              cli.cmd_abort(root, "x")["status"] == "NO_TRANSACTION")
        cli.cmd_begin(root, "repair")
        r = cli.cmd_abort(root, "   ")
        check("52/empty_reason_blocked", code_of(r) == "PMO-SPEC-REPAIR-020", r)
        check("52/marker_kept", os.path.exists(_marker_path(root)))
    finally:
        _cleanup(root)


def test_53_finalized_transaction_cannot_be_aborted():
    root = mkroot()
    try:
        cli.cmd_begin(root, "repair")
        marker_text = open(_marker_path(root)).read()
        f = cli.cmd_finalize(root)
        check("53/finalized", f["status"] == "REPAIRED", f)
        check("53/marker_removed_by_finalize", not os.path.exists(_marker_path(root)))
        check("53/abort_after_finalize_no_transaction",
              cli.cmd_abort(root, "x")["status"] == "NO_TRANSACTION")
        # Even if a stale copy of the marker reappears, the changed specs.md
        # hash makes the state ambiguous and abort must refuse.
        _w(_marker_path(root), marker_text)
        after = open(_specs_path(root), "rb").read()
        r = cli.cmd_abort(root, "x")
        check("53/stale_marker_abort_blocked", code_of(r) == "PMO-SPEC-REPAIR-022", r)
        check("53/specs_untouched", open(_specs_path(root), "rb").read() == after)
        check("53/marker_kept", os.path.exists(_marker_path(root)))
    finally:
        _cleanup(root)


def test_54_abort_fails_closed_on_ambiguous_marker():
    root = mkroot()
    try:
        cli.cmd_begin(root, "repair")
        with open(_specs_path(root), "a") as fh:
            fh.write("\nedited\n")
        r = cli.cmd_abort(root, "x")
        check("54/edited_specs_blocked", code_of(r) == "PMO-SPEC-REPAIR-022", r)
        check("54/marker_kept", os.path.exists(_marker_path(root)))
        _w(_marker_path(root), "{not json")
        r = cli.cmd_abort(root, "x")
        check("54/invalid_marker_blocked", code_of(r) == "PMO-SPEC-REPAIR-015", r)
        check("54/invalid_marker_kept", os.path.exists(_marker_path(root)))
    finally:
        _cleanup(root)


def test_55_abort_rejects_cr_marker_masquerade():
    root = mkroot()
    try:
        _w(_marker_path(root), json.dumps({"operation": "CR_INCORPORATION"}))
        r = cli.cmd_abort(root, "x")
        check("55/cr_style_marker_blocked", code_of(r) == "PMO-SPEC-REPAIR-015", r)
        check("55/marker_kept", os.path.exists(_marker_path(root)))
    finally:
        _cleanup(root)


def _initial_row_validation(source, summary="Initial provisional specification"):
    root = mkroot(specs=build_specs(include_validation_summary=True))
    try:
        text = open(_specs_path(root)).read()
        text = text.replace(
            "| INITIAL_INTENT | FR-001 | Initial provisional specification generated "
            "from validated Intent + resolved Q&A |",
            "| {} | FR-001 | {} |".format(source, summary))
        return core.specs_guard.full_spec_validation(root, spec_text=text)
    finally:
        _cleanup(root)


def test_56_new_lifecycle_change_source_provenance():
    ok = _initial_row_validation("INITIAL_INTENT")
    check("56/new_path_initial_intent_valid", ok is None, ok)
    scope = _initial_row_validation("INITIAL_SCOPE")
    check("56/legacy_initial_scope_row_not_rejected_by_013",
          scope is None or scope.code != "PMO-SPEC-013", scope)
    for bad in ("INITIAL_SPECS_GENERATION", "SOMETHING_ELSE"):
        d = _initial_row_validation(bad)
        check("56/{}_rejected".format(bad.lower()),
              d is not None and d.code == "PMO-SPEC-013", d)


# --------------------------------------------------------------------------- #
# CHANGE_SOURCE_PROVENANCE_REPAIR
# --------------------------------------------------------------------------- #
TOK = core.NONCANONICAL_INITIAL_TOKEN
CANON = core.CANONICAL_NEW_INITIAL_TOKEN
HIST_CANON = ("| INITIAL_INTENT | FR-001 | Initial provisional specification generated "
              "from validated Intent + resolved Q&A |")


def provenance_specs(include_validation_summary=True, malformed_gf=False, prose=False):
    """Mirrors the real WM Trucking defect: the FR Change Source line and the
    Change History row carry the non-canonical token (row with a descriptive
    parenthetical, exactly as generated)."""
    text = build_specs(include_validation_summary=include_validation_summary)
    text = text.replace("- **Change Source:** INITIAL_INTENT\n",
                        "- **Change Source:** {}\n".format(TOK))
    text = text.replace(
        HIST_CANON,
        "| {} (Intent v0.3 + Q&A register, NEW no-Scope path) | FR-001 | Initial "
        "provisional specification generated from validated Intent + resolved Q&A |".format(TOK))
    if malformed_gf:
        text = text.replace(
            "- **Generated From:** docs/pmo/requirements/questions-and-assumptions.md\n",
            "- **Generated From:** docs/pmo/requirements/questions-and-assumptions.md "
            "(+ docs/pmo/intent/intent.md v1.0)\n")
    if prose:
        text = text.replace("## Open Questions",
                            "Note: the token {} is discussed in prose here.\n\n## Open Questions".format(TOK), 1)
    return text


def test_60_provenance_repair_normalizes_only_governed_fields():
    text = provenance_specs(prose=True)
    root = mkroot(specs=text)
    try:
        b = cli.cmd_begin(root, "normalize provenance")
        check("60/begin_active", b["status"] == "ACTIVE", b)
        check("60/only_provenance_class",
              b["plan"]["repair_classes"] == [core.REPAIR_CLASS_PROVENANCE], b["plan"])
        pf = b["plan"]["provenance_fixes"]
        check("60/counts", pf["field_lines"] == 1 and pf["history_rows"] == 1
              and pf["excluded_non_provenance"] == 1, pf)
        f = cli.cmd_finalize(root)
        # the prose mention is deliberately left alone, so full validation
        # must still pass (prose is not a governed field)
        check("60/finalize_repaired", f["status"] == "REPAIRED", f)
        after = open(_specs_path(root)).read()
        check("60/field_and_row_normalized",
              "- **Change Source:** INITIAL_INTENT\n" in after
              and "| INITIAL_INTENT (Intent v0.3 + Q&A register, NEW no-Scope path) |" in after)
        check("60/prose_untouched", "the token {} is discussed in prose".format(TOK) in after)
        exp = text.replace("- **Change Source:** {}\n".format(TOK), "- **Change Source:** INITIAL_INTENT\n") \
                  .replace("| {} (Intent".format(TOK), "| INITIAL_INTENT (Intent")
        check("60/everything_else_byte_identical", after == exp)
        check("60/fr_ids_identical", re.findall(r"(?m)^###\s+(FR-\d+)", after)
              == re.findall(r"(?m)^###\s+(FR-\d+)", text))
        check("60/validation_passes", core.specs_guard.full_spec_validation(root) is None)
        check("60/exec_still_false", "**Execution Authorized:** false" in after
              or "Execution Authorized: false" in after)
        check("60/no_approval", not os.path.exists(
            os.path.join(root, ".pmo", "approvals", "specs-approval.yaml")))
        check("60/no_cr_or_feedback", not os.path.exists(os.path.join(root, "docs", "pmo", "cr"))
              and not os.path.exists(os.path.join(root, "docs", "pmo", "feedback")))
    finally:
        _cleanup(root)


def test_61_three_class_combined_repair():
    root = mkroot(specs=provenance_specs(include_validation_summary=False, malformed_gf=True))
    try:
        b = cli.cmd_begin(root, "three-class repair")
        check("61/all_three_classes", b["plan"]["repair_classes"] == [
            core.REPAIR_CLASS_MISSING_SECTION, core.REPAIR_CLASS_METADATA,
            core.REPAIR_CLASS_PROVENANCE], b)
        before = open(_specs_path(root)).read()
        f = cli.cmd_finalize(root)
        check("61/finalize_repaired", f["status"] == "REPAIRED", f)
        after = open(_specs_path(root)).read()
        check("61/full_validation_passes", core.specs_guard.full_spec_validation(root) is None)
        check("61/generated_from_canonical",
              "- **Generated From:** docs/pmo/requirements/questions-and-assumptions.md\n" in after)
        check("61/validation_summary_added", "Validation Summary" in after)
        check("61/no_noncanonical_token_left", TOK not in after)
        check("61/fr_ids_identical", re.findall(r"(?m)^###\s+(FR-\d+)", after)
              == re.findall(r"(?m)^###\s+(FR-\d+)", before))
        check("61/version_unchanged", "**Spec Version:** 0.1" in after or "Spec Version: 0.1" in after)
    finally:
        _cleanup(root)


def test_62_provenance_blocked_when_not_new_lifecycle():
    scope = "# Scope\n\n- **Scope Version:** 0.1\n"
    root = mkroot(specs=provenance_specs())
    try:
        _w(os.path.join(root, "docs", "pmo", "scope", "scope-v0.1.md"), scope)
        r = cli.cmd_begin(root, "x")
        check("62/legacy_scope_governs_blocked", code_of(r) == "PMO-SPEC-REPAIR-024", r)
        check("62/no_marker", not os.path.exists(_marker_path(root)))
    finally:
        _cleanup(root)
    root = mkroot(specs=provenance_specs())
    try:
        _w(os.path.join(root, "docs", "pmo", "scope", "stray.txt"), "?")
        r = cli.cmd_begin(root, "x")
        check("62/ambiguous_scope_dir_blocked", code_of(r) == "PMO-SPEC-REPAIR-025", r)
    finally:
        _cleanup(root)
    root = mkroot(specs=provenance_specs(), approval="")
    try:
        os.remove(os.path.join(root, ".pmo", "approvals", "intent-approval.yaml"))
        r = cli.cmd_begin(root, "x")
        check("62/missing_intent_approval_blocked", code_of(r) == "PMO-SPEC-REPAIR-026", r)
    finally:
        _cleanup(root)
    root = mkroot(specs=provenance_specs())
    try:
        os.remove(os.path.join(root, "docs", "pmo", "requirements", "questions-and-assumptions.md"))
        r = cli.cmd_begin(root, "x")
        check("62/missing_qa_blocked",
              code_of(r) in ("PMO-SPEC-REPAIR-026", "PMO-SPEC-REPAIR-017")
              and not os.path.exists(_marker_path(root)), r)
        d = core.prove_new_lifecycle_provenance(root)
        check("62/missing_qa_not_proven_new_lifecycle",
              d is not None and d.code == "PMO-SPEC-REPAIR-026", d)
    finally:
        _cleanup(root)


def test_63_provenance_blocked_when_approved():
    root = mkroot(specs=provenance_specs().replace(
        "**Execution Authorized:** false", "**Execution Authorized:** true"))
    try:
        r = cli.cmd_begin(root, "x")
        check("63/exec_true_blocked", code_of(r) == "PMO-SPEC-REPAIR-003", r)
    finally:
        _cleanup(root)
    root = mkroot(specs=provenance_specs(), specs_approval=matching_specs_approval())
    try:
        r = cli.cmd_begin(root, "x")
        check("63/existing_approval_blocked", code_of(r) == "PMO-SPEC-REPAIR-004", r)
    finally:
        _cleanup(root)


def test_64_provenance_mutation_boundary():
    base = provenance_specs()
    fixed = core.apply_provenance_fix(base)
    check("64/valid_fix_is_token_only", core.provenance_fix_is_token_only(base, fixed)[0])
    check("64/fix_is_idempotent", core.apply_provenance_fix(fixed) == fixed)
    # INITIAL_SCOPE / INITIAL_INTENT / CR / FDB / QST sources are never rewritten
    for src in ("INITIAL_SCOPE", "INITIAL_INTENT", "CR-001", "FDB-002", "QST-003", "PM-DECISION"):
        t = base.replace("- **Change Source:** {}\n".format(TOK), "- **Change Source:** {}\n".format(src))
        t = t.replace("| {} (Intent".format(TOK), "| {} (Intent".format(src))
        check("64/{}_not_rewritten".format(src.lower()),
              core.find_provenance_occurrences(t)[0] == [] and core.apply_provenance_fix(t) == t)
    # arbitrary replacement / content / version / identifier mutation rejected
    def rej(name, after):
        check("64/reject_" + name, not core.provenance_fix_is_token_only(base, after)[0])
    rej("arbitrary_source", fixed.replace("- **Change Source:** INITIAL_INTENT\n",
                                          "- **Change Source:** SOMETHING\n"))
    rej("scope_source", fixed.replace("- **Change Source:** INITIAL_INTENT\n",
                                      "- **Change Source:** INITIAL_SCOPE\n"))
    rej("fr_content", fixed.replace("confirm a cart", "confirm a basket"))
    rej("fr_id", fixed.replace("### FR-001", "### FR-009"))
    rej("version", fixed.replace("**Spec Version:** 0.1", "**Spec Version:** 0.2"))
    rej("added_line", fixed + "\n- extra\n")
    rej("cr_line_rewrite", base.replace("- **Change Source:** {}\n".format(TOK),
                                         "- **Change Source:** CR-001\n"))
    # token outside a governed field is never eligible
    prose = base.replace("## Open Questions", "{} in prose\n\n## Open Questions".format(TOK), 1)
    e, total, excl = core.find_provenance_occurrences(prose)
    check("64/prose_excluded", len(e) == 2 and excl == 1 and total == 3, (len(e), total, excl))


def test_65_already_canonical_new_lifecycle_needs_no_provenance_repair():
    root = mkroot()
    try:
        check("65/no_eligible_occurrences",
              core.find_provenance_occurrences(open(_specs_path(root)).read())[0] == [])
        r = cli.cmd_begin(root, "x")
        check("65/no_provenance_class",
              core.REPAIR_CLASS_PROVENANCE not in ((r.get("plan") or {}).get("repair_classes") or []), r)
    finally:
        _cleanup(root)


def test_66_provenance_repair_fail_closed_writes_nothing():
    # provenance fixable but ANOTHER defect (unrepairable) remains -> nothing written
    text = provenance_specs().replace("- **Status:** ACTIVE", "- **Status:** BOGUS_STATUS")
    root = mkroot(specs=text)
    try:
        b = cli.cmd_begin(root, "x")
        if b["status"] != "ACTIVE":
            check("66/other_defect_blocked_at_begin_or_finalize", True)
        else:
            before = open(_specs_path(root), "rb").read()
            f = cli.cmd_finalize(root)
            check("66/finalize_fails_closed", f["status"] == "RECOVERY_REQUIRED", f)
            check("66/nothing_written", open(_specs_path(root), "rb").read() == before)
            a = cli.cmd_abort(root, "cleanup")
            check("66/abort_ok", a["status"] == "ABORTED", a)
            check("66/specs_identical_after_abort", open(_specs_path(root), "rb").read() == before)
    finally:
        _cleanup(root)


def main():
    for fn in (
        test_1_eligible_repair_succeeds,
        test_2_validation_summary_derived_correctly,
        test_3_full_validation_passes_after,
        test_4_5_fr_content_and_ids_byte_identical,
        test_6_7_still_unapproved_after_repair,
        test_8_9_no_cr_no_changelog_created,
        test_10_subsequent_approval_still_required_and_now_possible,
        test_11_blocked_when_execution_authorized_true,
        test_12_blocked_when_matching_approval_exists,
        test_13_fr_text_change_rejected_by_preservation_check,
        test_14_fr_id_change_rejected,
        test_15_business_rule_change_rejected,
        test_16_nfr_change_rejected,
        test_17_deferred_tbd_resolution_rejected,
        test_18_source_traceability_change_rejected,
        test_19_intent_mapping_change_rejected,
        test_20_qa_mapping_change_rejected,
        test_21_version_change_rejected,
        test_22_new_requirement_introduction_rejected,
        test_23_scope_expansion_new_section_rejected,
        test_24_unrelated_typo_edit_rejected,
        test_25_cr_marker_masquerade_rejected,
        test_26_status_is_read_only,
        test_27_dry_run_writes_nothing,
        test_28_already_valid_specs_has_nothing_to_repair,
        test_29_unsupported_failure_class_rejected,
        test_30_malformed_generated_from_corrected_to_canonical,
        test_31_generated_from_fix_changes_nothing_substantive,
        test_32_both_repair_classes_applied_sequentially,
        test_33_full_validation_passes_after_combined_repair,
        test_34_still_unapproved_after_combined_repair,
        test_35_cr_not_required_for_metadata_repair,
        test_36_project_change_rejected,
        test_37_project_id_change_rejected,
        test_38_pm_identity_change_rejected,
        test_39_specs_version_change_rejected_by_metadata_check,
        test_40_specs_status_change_rejected,
        test_41_execution_authorized_change_rejected_by_metadata_check,
        test_42_requirement_content_change_rejected_by_metadata_check,
        test_43_requirement_id_change_rejected_by_metadata_check,
        test_44_business_rule_change_rejected_by_metadata_check,
        test_45_nfr_change_rejected_by_metadata_check,
        test_46_qa_decision_change_rejected_by_metadata_check,
        test_47_intent_mapping_change_rejected_by_metadata_check,
        test_48_source_semantics_change_rejected_by_metadata_check,
        test_49_arbitrary_valid_metadata_field_change_rejected,
        test_50_repair_requires_evidence_field_is_invalid,
        test_51_failed_transaction_can_be_governedly_aborted,
        test_52_abort_requires_reason_and_marker,
        test_53_finalized_transaction_cannot_be_aborted,
        test_54_abort_fails_closed_on_ambiguous_marker,
        test_55_abort_rejects_cr_marker_masquerade,
        test_56_new_lifecycle_change_source_provenance,
        test_60_provenance_repair_normalizes_only_governed_fields,
        test_61_three_class_combined_repair,
        test_62_provenance_blocked_when_not_new_lifecycle,
        test_63_provenance_blocked_when_approved,
        test_64_provenance_mutation_boundary,
        test_65_already_canonical_new_lifecycle_needs_no_provenance_repair,
        test_66_provenance_repair_fail_closed_writes_nothing,
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
