#!/usr/bin/env python3
"""Regression tests for .claude/lib/pmo_lifecycle_core.py.

Stdlib only. Run: python3 .claude/lib/test_pmo_lifecycle_core.py
Exit 0 = all pass, 1 = at least one failure.

Uses temporary, synthetic project fixtures for every lifecycle boundary,
plus a READ-ONLY reference check against the real WM Trucking project -
never created, edited, or deleted as a mutable fixture.
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))


def _load(name, path, register=False):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


iac = _load("intent_approval_core", os.path.join(HERE, "intent_approval_core.py"), register=True)
qac = _load("qa_register_core", os.path.join(HERE, "qa_register_core.py"), register=True)
crc = _load("change_request_incorporation_core", os.path.join(HERE, "change_request_incorporation_core.py"), register=True)
apc = _load("artifact_publish_core", os.path.join(HERE, "artifact_publish_core.py"), register=True)
sac = _load("specs_approval_core", os.path.join(HERE, "specs_approval_core.py"), register=True)
plc = _load("pmo_lifecycle_core", os.path.join(HERE, "pmo_lifecycle_core.py"), register=True)

cli = _load("specs_approval_recorder",
           os.path.join(REPO_ROOT, ".claude", "scripts", "specs-approval-recorder.py"))

_RESULTS = []


def check(name, ok, detail=""):
    _RESULTS.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + "  " + name + ("" if ok else "   :: " + str(detail)))


# --------------------------------------------------------------------------- #
# Fixtures
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
  working_branch: "main"
  verified: true
'''

CONFIG_NO_REPO = '''schema_version: "1.0"

project:
  id: "SMART-BASKET"
  name: "Smart Basket"
  client: "Smart Basket / eBasket KSA"
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

## 11. Open Questions

| ID | Question | Owner | Blocking | Required Before | Reconciliation Status |
|---|---|---|---|---|---|
| OPEN-001 | Fully resolved item | PM | NO | SCOPE_BASELINE | RESOLVED (via PM decision) |
'''

INTENT_DRAFT = INTENT_VALIDATED.replace("**Status:** VALIDATED", "**Status:** DRAFT")

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
        "- **Statement:** Statement for {rid}.\n"
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


def qa_doc(records_md):
    return (
        "# Questions & Assumptions\n\n"
        "## Document Control\n\n"
        "- **Project:** Smart Basket\n"
        "- **Client:** Smart Basket / eBasket KSA\n"
        "- **Project ID:** SMART-BASKET\n"
        "- **PM:** Jane PM\n"
        "- **Date:** 2026-09-11\n"
        "- **Intent Version:** 1.0\n\n"
        "## Register\n\n"
    ) + records_md


QA_BLOCKING = qa_doc(qa_record("QST-001", status="OPEN", blocking="YES"))
QA_ALL_RESOLVED = qa_doc(qa_record("QST-001", status="RESOLVED", blocking="NO"))
QA_DEFERRED_ONLY = qa_doc(
    qa_record("QST-001", status="DEFERRED", blocking="NO") +
    qa_record("QST-002", status="NON_BLOCKING", blocking="NO"))


def build_specs(exec_auth="false", spec_version="0.1", include_validation_summary=True):
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


def mkroot(config=CONFIG_YAML, intent=None, approval=None, qa=None, specs=None,
          specs_approval=None, sources=None, cr_files=None, cr_marker=None,
          feedback_marker=None, specs_approval_marker=None):
    root = tempfile.mkdtemp(prefix="pmo-lifecycle-test-")
    os.makedirs(os.path.join(root, ".pmo", "approvals"), exist_ok=True)
    if config is not None:
        _w(os.path.join(root, ".pmo", "project-config.yaml"), config)
    if sources:
        for relpath, text in sources.items():
            _w(os.path.join(root, "docs", "pmo", "sources", relpath), text)
    if intent is not None:
        _w(os.path.join(root, "docs", "pmo", "intent", "intent.md"), intent)
    if approval is not None:
        _w(os.path.join(root, ".pmo", "approvals", "intent-approval.yaml"), approval)
    if qa is not None:
        _w(os.path.join(root, "docs", "pmo", "requirements",
                        "questions-and-assumptions.md"), qa)
    if specs is not None:
        _w(os.path.join(root, "docs", "pmo", "specs", "specs.md"), specs)
    if specs_approval is not None:
        _w(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml"), specs_approval)
    if cr_files:
        for cr_id, text in cr_files.items():
            _w(os.path.join(root, "docs", "pmo", "cr", cr_id + ".md"), text)
    if cr_marker is not None:
        _w(os.path.join(root, ".pmo", "change-request-transaction.json"), cr_marker)
    if feedback_marker is not None:
        _w(os.path.join(root, ".pmo", "feedback-transaction.json"), feedback_marker)
    if specs_approval_marker is not None:
        _w(os.path.join(root, ".pmo", "specs-approval-transaction.json"), specs_approval_marker)
    return root


def cr_doc(cr_id, status):
    rows = [
        ("CR ID", cr_id), ("Status", status),
    ]
    lines = ["# Change Request " + cr_id, "", "| Field | Requirement | Value |", "|---|---|---|"]
    for f, v in rows:
        lines.append("| {} | REQUIRED | {} |".format(f, v))
    return "\n".join(lines)


def _cleanup(root):
    shutil.rmtree(root, ignore_errors=True)


def approved_specs(spec_version="0.1"):
    """A specs.md whose Execution Authorized is true AND carries the
    evidence text specs-governance-guard.py's own PMO-SPEC-009 requires -
    i.e. exactly what specs-approval-recorder.py's finalize would produce."""
    base = build_specs(exec_auth="true", spec_version=spec_version)
    return base.replace(
        "| Generated |",
        "| Approved - Execution Authorized per PM-DECISION: approved by "
        "Jane PM on 2026-09-12 for Spec Version {}. |".format(spec_version))


def matching_specs_approval(spec_version="0.1"):
    return sac.render_specs_approval_yaml(
        "SMART-BASKET", spec_version, "Jane PM", "2026-09-12")


# --------------------------------------------------------------------------- #
# 1-17: lifecycle boundary tests
# --------------------------------------------------------------------------- #

def test_01_new_project():
    root = mkroot(config=None)
    try:
        s = plc.get_project_state(root)
        check("01/new_project", s["lifecycle_state"] == plc.LifecycleState.NEW_PROJECT, s)
    finally:
        _cleanup(root)


def test_02_sources_no_intent():
    root = mkroot(sources={"contract/sow.txt": "some content"})
    try:
        s = plc.get_project_state(root)
        check("02/source_baseline_ready",
              s["lifecycle_state"] == plc.LifecycleState.SOURCE_BASELINE_READY, s)
    finally:
        _cleanup(root)


def test_03_intent_draft():
    root = mkroot(intent=INTENT_DRAFT)
    try:
        s = plc.get_project_state(root)
        check("03/intent_review_required",
              s["lifecycle_state"] == plc.LifecycleState.INTENT_REVIEW_REQUIRED, s)
    finally:
        _cleanup(root)


def test_04_intent_validated_no_approval():
    root = mkroot(intent=INTENT_VALIDATED)
    try:
        s = plc.get_project_state(root)
        check("04/intent_ready_for_approval_review_required",
              s["lifecycle_state"] == plc.LifecycleState.INTENT_REVIEW_REQUIRED, s)
    finally:
        _cleanup(root)


def test_05_intent_approved_no_qa():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID)
    try:
        s = plc.get_project_state(root)
        check("05/intent_approved", s["lifecycle_state"] == plc.LifecycleState.INTENT_APPROVED, s)
    finally:
        _cleanup(root)


def test_06_unresolved_blocking_decisions():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_BLOCKING)
    try:
        s = plc.get_project_state(root)
        check("06/decision_review_required",
              s["lifecycle_state"] == plc.LifecycleState.DECISION_REVIEW_REQUIRED, s)
        check("06/blocking_count", s["blocking_decision_count"] == 1, s)
    finally:
        _cleanup(root)


def test_07_only_deferred_decisions_ready_for_specs():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_DEFERRED_ONLY)
    try:
        s = plc.get_project_state(root)
        check("07/ready_for_specs", s["lifecycle_state"] == plc.LifecycleState.READY_FOR_SPECS, s)
        check("07/deferred_count", s["deferred_decision_count"] == 2, s)
    finally:
        _cleanup(root)


def test_08_eligible_for_initial_specs_same_as_07():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED)
    try:
        s = plc.get_project_state(root)
        check("08/eligible_for_initial_specs",
              s["lifecycle_state"] == plc.LifecycleState.READY_FOR_SPECS, s)
    finally:
        _cleanup(root)


def test_09_specs_provisional_not_clean():
    broken = build_specs(include_validation_summary=False)
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=broken)
    try:
        s = plc.get_project_state(root)
        check("09/specs_review_required",
              s["lifecycle_state"] == plc.LifecycleState.SPECS_REVIEW_REQUIRED, s)
    finally:
        _cleanup(root)


def test_10_specs_ready_for_approval():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=build_specs())
    try:
        s = plc.get_project_state(root)
        check("10/baseline_ready_for_approval",
              s["lifecycle_state"] == plc.LifecycleState.BASELINE_READY_FOR_APPROVAL, s)
        check("10/requirement_count", s["requirement_count"] == 1, s)
    finally:
        _cleanup(root)


def test_11_specs_approved_baseline():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=approved_specs(), specs_approval=matching_specs_approval(),
                  config=CONFIG_NO_REPO)
    try:
        s = plc.get_project_state(root)
        check("11/baseline_approved",
              s["lifecycle_state"] == plc.LifecycleState.BASELINE_APPROVED, s)
    finally:
        _cleanup(root)


def test_12_feedback_pending():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=approved_specs(), specs_approval=matching_specs_approval(),
                  feedback_marker=json.dumps({
                      "transaction_type": "FEEDBACK_MANAGEMENT",
                      "transaction_id": "FBTX-1", "project_id": "SMART-BASKET",
                      "feedback_batch_id": None, "started_at": "2026-09-11T00:00:00Z",
                      "status": "ACTIVE"}))
    try:
        s = plc.get_project_state(root)
        check("12/feedback_review_required",
              s["lifecycle_state"] == plc.LifecycleState.FEEDBACK_REVIEW_REQUIRED, s)
    finally:
        _cleanup(root)


def test_13_cr_pending():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=approved_specs(), specs_approval=matching_specs_approval(),
                  cr_files={"CR-001": cr_doc("CR-001", "PM_REVIEW")})
    try:
        s = plc.get_project_state(root)
        check("13/cr_review_required",
              s["lifecycle_state"] == plc.LifecycleState.CR_REVIEW_REQUIRED, s)
    finally:
        _cleanup(root)


def test_14_approved_cr_ready_for_incorporation():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=approved_specs(), specs_approval=matching_specs_approval(),
                  cr_files={"CR-001": cr_doc("CR-001", "APPROVED")})
    try:
        s = plc.get_project_state(root)
        check("14/cr_ready_for_incorporation",
              s["lifecycle_state"] == plc.LifecycleState.CR_READY_FOR_INCORPORATION, s)
    finally:
        _cleanup(root)


def test_15_incorporated_cr_does_not_block_publication():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=approved_specs(), specs_approval=matching_specs_approval(),
                  cr_files={"CR-001": cr_doc("CR-001", "INCORPORATED")})
    try:
        s = plc.get_project_state(root)
        check("15/incorporated_cr_reaches_publication",
              s["lifecycle_state"] == plc.LifecycleState.PUBLICATION_READY, s)
    finally:
        _cleanup(root)


def test_16_publication_ready():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=approved_specs(), specs_approval=matching_specs_approval())
    try:
        s = plc.get_project_state(root)
        check("16/publication_ready",
              s["lifecycle_state"] == plc.LifecycleState.PUBLICATION_READY, s)
    finally:
        _cleanup(root)


def test_17_recovery_error_state():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  cr_marker="{not valid json")
    try:
        s = plc.get_project_state(root)
        check("17/error_recovery_required", s["lifecycle_state"] == plc.LifecycleState.ERROR, s)
    finally:
        _cleanup(root)


# --------------------------------------------------------------------------- #
# Cross-cutting regression requirements
# --------------------------------------------------------------------------- #

def test_18_read_only_no_files_written():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=build_specs())
    try:
        def snapshot():
            paths = []
            for dirpath, _, filenames in os.walk(root):
                for fn in filenames:
                    paths.append(os.path.join(dirpath, fn))
            return {p: os.path.getmtime(p) for p in sorted(paths)}, len(paths)

        before, count_before = snapshot()
        plc.get_project_state(root)
        plc.build_decision_inbox(root)
        after, count_after = snapshot()
        check("18/no_new_files", count_before == count_after,
              (count_before, count_after))
        check("18/no_files_touched", before == after)
    finally:
        _cleanup(root)


def test_19_idempotent_same_state():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_DEFERRED_ONLY)
    try:
        s1 = plc.get_project_state(root)
        s2 = plc.get_project_state(root)
        check("19/idempotent_json_equal", json.dumps(s1, sort_keys=True) == json.dumps(s2, sort_keys=True))
    finally:
        _cleanup(root)


def test_20_reuses_authoritative_qa_validator():
    """Proves the detector and the real Q&A guard's own readiness function
    agree on the SAME fixture - not merely structurally similar logic."""
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_BLOCKING)
    try:
        s = plc.get_project_state(root)
        direct = qac.validate_new_path_readiness(root)
        check("20/lifecycle_agrees_with_qa_core",
              s["lifecycle_state"] == plc.LifecycleState.DECISION_REVIEW_REQUIRED
              and direct is not None and direct[0] == "QA_BLOCKING_ITEM_OPEN")
    finally:
        _cleanup(root)


def test_21_no_project_config_authorization_shortcut():
    """A project-config claiming a far-advanced status field (were one to
    exist) must NOT change the detected state - only canonical artifacts do.
    This asserts the actual behavior: project-config carries no lifecycle
    field at all, and adding an arbitrary unknown key changes nothing."""
    poisoned_config = CONFIG_YAML + "\nworkflow:\n  current_stage: \"PUBLICATION_READY\"\n"
    root = mkroot(config=poisoned_config)  # otherwise a NEW_PROJECT fixture
    try:
        s = plc.get_project_state(root)
        check("21/config_claim_ignored", s["lifecycle_state"] == plc.LifecycleState.NEW_PROJECT, s)
    finally:
        _cleanup(root)


def test_22_pm_mode_excludes_forbidden_detail():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=build_specs(include_validation_summary=False))
    try:
        s = plc.get_project_state(root)
        pm_text = plc.pm_status_view(s)
        forbidden = ["PMO-SPEC", "PMO-QA", "PMO-CR", "guard", "hook", ".py",
                    "transaction_id", "sha256", ".pmo/"]
        hits = [f for f in forbidden if f.lower() in pm_text.lower()]
        check("22/pm_mode_clean", not hits, hits)
    finally:
        _cleanup(root)


def test_23_engineering_mode_retains_diagnostics():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=build_specs(include_validation_summary=False))
    try:
        s = plc.get_project_state(root)
        eng_text = plc.engineering_status_view(s)
        check("23/engineering_mode_has_guard_code", "PMO-SPEC-003" in eng_text, eng_text)
    finally:
        _cleanup(root)


def test_24_decision_inbox_maps_to_canonical_ids():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_DEFERRED_ONLY)
    try:
        items = plc.build_decision_inbox(root)
        ids = {i["id"] for i in items}
        check("24/canonical_ids_present", ids == {"QST-001", "QST-002"}, ids)
        rendered = plc.render_decision_inbox_pm(items)
        check("24/rendered_contains_ids",
              "QST-001" in rendered and "QST-002" in rendered, rendered)
    finally:
        _cleanup(root)


def test_25_specs_approval_atomic_and_governed():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=build_specs())
    try:
        before_state = plc.get_project_state(root)
        check("25/pre_approval_state",
              before_state["lifecycle_state"] == plc.LifecycleState.BASELINE_READY_FOR_APPROVAL)
        result = cli.cmd_begin(root, "Jane PM", "2026-09-19", statement="Reviewed.")
        check("25/begin_active", result["status"] == "ACTIVE", result)
        result2 = cli.cmd_finalize(root)
        check("25/finalize_approved", result2["status"] == "APPROVED", result2)
        after_state = plc.get_project_state(root)
        check("25/post_approval_state",
              after_state["lifecycle_state"] == plc.LifecycleState.PUBLICATION_READY,
              after_state)
    finally:
        _cleanup(root)


def test_26_specs_approval_requires_explicit_pm_action():
    """No pmo_lifecycle_core call ever produces an approval by itself -
    state detection alone must never flip Execution Authorized."""
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=build_specs())
    try:
        for _ in range(3):
            plc.get_project_state(root)
        specs_text = open(os.path.join(root, "docs", "pmo", "specs", "specs.md")).read()
        check("26/execution_still_false", "**Execution Authorized:** false" in specs_text)
    finally:
        _cleanup(root)


def test_27_already_approved_specs_cannot_be_silently_rewritten():
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=approved_specs(), specs_approval=matching_specs_approval())
    try:
        result = cli.cmd_begin(root, "Another PM", "2026-09-20")
        check("27/reapproval_denied", result["status"] == "BLOCKED", result)
    finally:
        _cleanup(root)


def test_28_invalid_mismatched_approval_fails_closed():
    mismatched = sac.render_specs_approval_yaml(
        "OTHER-PROJECT", "0.1", "Jane PM", "2026-09-12")
    root = mkroot(intent=INTENT_VALIDATED, approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED,
                  specs=approved_specs(), specs_approval=mismatched)
    try:
        s = plc.get_project_state(root)
        # Mismatched approval must not be trusted as "approved" - Specs
        # falls back to needing review/approval again, never silently
        # treated as a valid baseline.
        check("28/mismatched_approval_not_trusted",
              s["lifecycle_state"] != plc.LifecycleState.PUBLICATION_READY, s)
    finally:
        _cleanup(root)


# --------------------------------------------------------------------------- #
# Real WM Trucking - READ-ONLY reference validation
# --------------------------------------------------------------------------- #

def test_29_wm_trucking_real_state_read_only():
    before_paths = []
    watch_dirs = [
        os.path.join(REPO_ROOT, "docs", "pmo"),
        os.path.join(REPO_ROOT, ".pmo"),
    ]
    snapshots = {}
    for d in watch_dirs:
        for dirpath, _, filenames in os.walk(d):
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                snapshots[p] = os.path.getmtime(p)

    s = plc.get_project_state(REPO_ROOT)
    check("29/project_id", s["project_id"] == "WM-TRUCKING", s)
    check("29/state_is_known", s["lifecycle_state"] in plc.ALL_STATES, s)
    check("29/state_not_error", s["lifecycle_state"] != plc.LifecycleState.ERROR, s)
    check("29/requirement_count_68", s["requirement_count"] == 68, s)
    check("29/deferred_count_20", s["deferred_decision_count"] == 20, s)
    check("29/blocking_count_0", s["blocking_decision_count"] == 0, s)

    after_snapshots = {}
    for d in watch_dirs:
        for dirpath, _, filenames in os.walk(d):
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                after_snapshots[p] = os.path.getmtime(p)
    check("29/wm_trucking_untouched", snapshots == after_snapshots)

    items = plc.build_decision_inbox(REPO_ROOT)
    ids = {i["id"] for i in items}
    check("29/decision_inbox_has_qst006",
          "QST-006" in ids and "QST-017" in ids and "QST-018" in ids, ids)


def main():
    for fn in (
        test_01_new_project, test_02_sources_no_intent, test_03_intent_draft,
        test_04_intent_validated_no_approval, test_05_intent_approved_no_qa,
        test_06_unresolved_blocking_decisions, test_07_only_deferred_decisions_ready_for_specs,
        test_08_eligible_for_initial_specs_same_as_07, test_09_specs_provisional_not_clean,
        test_10_specs_ready_for_approval, test_11_specs_approved_baseline,
        test_12_feedback_pending, test_13_cr_pending,
        test_14_approved_cr_ready_for_incorporation,
        test_15_incorporated_cr_does_not_block_publication,
        test_16_publication_ready, test_17_recovery_error_state,
        test_18_read_only_no_files_written, test_19_idempotent_same_state,
        test_20_reuses_authoritative_qa_validator,
        test_21_no_project_config_authorization_shortcut,
        test_22_pm_mode_excludes_forbidden_detail,
        test_23_engineering_mode_retains_diagnostics,
        test_24_decision_inbox_maps_to_canonical_ids,
        test_25_specs_approval_atomic_and_governed,
        test_26_specs_approval_requires_explicit_pm_action,
        test_27_already_approved_specs_cannot_be_silently_rewritten,
        test_28_invalid_mismatched_approval_fails_closed,
        test_29_wm_trucking_real_state_read_only,
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
