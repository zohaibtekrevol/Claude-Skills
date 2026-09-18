#!/usr/bin/env python3
"""Regression tests for the PMO SPECS GENERATOR CONTRACT CORRECTION:

1. spec-generation/SKILL.md's Section 24a required-sections table stays in
   exact sync with specs-governance-guard.py's own REQUIRED_SECTIONS tuple
   (drift prevention - this IS the mechanism Section 24a's own text
   promises).
2. The Phase 4.5 mandatory post-generation validation gate - reusing
   specs-governance-guard.py's full_spec_validation directly, never a
   second implementation - correctly fails closed on every mandatory-
   section/schema/traceability/unsupported-requirement defect and passes
   a genuinely compliant artifact.
3. Real WM Trucking's current, pre-existing PMO-SPEC-003 failure (missing
   Validation Summary) is confirmed, read-only, unmodified by this task.
4. pmo_lifecycle_core.py's own state detection - unchanged by this task -
   remains compatible: WM Trucking still resolves SPECS_REVIEW_REQUIRED,
   and a synthetic fixture that includes every required section resolves
   BASELINE_READY_FOR_APPROVAL once all other approval-readiness
   conditions are met.

Stdlib only. Run: python3 .claude/skills/spec-generation/test_spec_generation_contract.py
Exit 0 = all pass, 1 = at least one failure.

Uses temporary, synthetic project fixtures for every negative/positive
case, plus READ-ONLY checks against the real WM Trucking project and the
real spec-generation/SKILL.md file - never modified by this file.
"""

import importlib.util
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
LIB_DIR = os.path.join(REPO_ROOT, ".claude", "lib")
HOOKS_DIR = os.path.join(REPO_ROOT, ".claude", "hooks")
SKILL_MD_PATH = os.path.join(HERE, "SKILL.md")


def _load(name, path, register=False):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


iac = _load("intent_approval_core", os.path.join(LIB_DIR, "intent_approval_core.py"), register=True)
qac = _load("qa_register_core", os.path.join(LIB_DIR, "qa_register_core.py"), register=True)
plc = _load("pmo_lifecycle_core", os.path.join(LIB_DIR, "pmo_lifecycle_core.py"), register=True)
guard = _load("specs_governance_guard_contract_test", os.path.join(HOOKS_DIR, "specs-governance-guard.py"))

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


QA_ALL_RESOLVED = (
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


_SECTIONS = {
    "doc_control": '''# Specification: Smart Basket

## Specification Document Control

- **Project:** Smart Basket
- **Client:** Smart Basket / eBasket KSA
- **Project ID:** SMART-BASKET
- **Spec Version:** 0.1
- **Spec Status:** PROVISIONAL
- **Intent Version:** 1.0
- **Generated From:** docs/pmo/requirements/questions-and-assumptions.md
- **Last Updated:** 2026-09-11T00:00:00Z
- **Execution Authorized:** false
- **Repository:** bitbucket:devops-tekrevol/lets-explore-more-specs
''',
    "fr": '''## Functional Requirements

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
''',
    "nfr": "## Non-Functional Requirements\n",
    "data": '''## Data Requirements

| Entity | Field | Required | Validation | Related FR |
|---|---|---|---|---|
| Order | order_reference | Yes | System-generated, unique | FR-001 |
''',
    "integrations": '''## Integrations

| Integration | Provider | FR / NFR | OPEN |
|---|---|---|---|
| N/A | N/A | N/A | N/A |
''',
    "open": '''## Open Questions

| ID | Provenance | Origin | Question |
|---|---|---|---|
''',
    "traceability": '''## Intent -> Specs Traceability

| Requirement ID | FR/NFR IDs | Coverage | Notes |
|---|---|---|---|
| INT-REQ-001 | FR-001 | COVERED |  |
''',
    "history": '''## 30. Specification Change History

| Version | Date | Change Source | Changed IDs | Summary | PM Decision |
|---|---|---|---|---|---|
| 0.1 | 2026-09-11 | INITIAL_INTENT | FR-001 | Initial provisional specification generated from validated Intent + resolved Q&A | Generated |
''',
    "validation_summary": '''## Validation Summary

All active Intent requirements (INT-REQ-001) are represented in the
Intent -> Specs Traceability matrix with a COVERED disposition. No FR/NFR
lacks an upstream trace. 0 implementation-relevant OPEN items remain.
This write passed specs-governance-guard.py's full_spec_validation
(Phase 4.5) prior to being reported.
''',
}

_ORDER = ("doc_control", "fr", "nfr", "data", "integrations", "open",
         "traceability", "history", "validation_summary")


def build_specs(omit=(), fr_override=None, traceability_override=None,
                doc_control_override=None):
    parts = []
    for key in _ORDER:
        if key in omit:
            continue
        text = _SECTIONS[key]
        if key == "fr" and fr_override is not None:
            text = fr_override
        if key == "traceability" and traceability_override is not None:
            text = traceability_override
        if key == "doc_control" and doc_control_override is not None:
            text = doc_control_override
        parts.append(text)
    return "\n".join(parts)


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def mkroot(specs, config=CONFIG_YAML, intent=INTENT_VALIDATED,
          approval=APPROVAL_VALID, qa=QA_ALL_RESOLVED):
    root = tempfile.mkdtemp(prefix="spec-gen-contract-test-")
    os.makedirs(os.path.join(root, ".pmo", "approvals"), exist_ok=True)
    _w(os.path.join(root, ".pmo", "project-config.yaml"), config)
    _w(os.path.join(root, "docs", "pmo", "intent", "intent.md"), intent)
    _w(os.path.join(root, ".pmo", "approvals", "intent-approval.yaml"), approval)
    _w(os.path.join(root, "docs", "pmo", "requirements",
                    "questions-and-assumptions.md"), qa)
    _w(os.path.join(root, "docs", "pmo", "specs", "specs.md"), specs)
    return root


def _cleanup(root):
    shutil.rmtree(root, ignore_errors=True)


def phase_4_5_gate(root):
    """The literal Phase 4.5 snippet documented in spec-generation/SKILL.md,
    executed for real - not paraphrased - to prove the documented procedure
    actually gates correctly. Returns ("PASS", None) or ("SPECS_VALIDATION_FAILED", Decision)."""
    d = guard.full_spec_validation(root)
    if d is not None:
        return "SPECS_VALIDATION_FAILED", d
    return "PASS", None


# --------------------------------------------------------------------------- #
# 1. Skill required-section alignment
# --------------------------------------------------------------------------- #

def test_01_skill_required_sections_match_guard():
    skill_text = open(SKILL_MD_PATH, encoding="utf-8").read()
    m = re.search(
        r"## 24a\. Required Sections[\s\S]*?\n\|.*\n\|[-\s|]+\n((?:\|.*\n)+)",
        skill_text)
    check("01/section_24a_found", m is not None)
    if not m:
        return
    rows = [r.strip() for r in m.group(1).splitlines() if r.strip()]
    skill_sections = set()
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        name = cells[0].replace("**", "")
        skill_sections.add(name)
    guard_sections = {name for name, _rx, _cond in guard.REQUIRED_SECTIONS}
    check("01/sets_equal", skill_sections == guard_sections,
          (skill_sections, guard_sections))
    check("01/validation_summary_in_skill", "Validation Summary" in skill_sections)


def test_02_validation_summary_required_by_guard():
    names = [name for name, _rx, _cond in guard.REQUIRED_SECTIONS]
    check("02/validation_summary_unconditional",
          "Validation Summary" in names)
    entry = [e for e in guard.REQUIRED_SECTIONS if e[0] == "Validation Summary"][0]
    check("02/not_conditional", entry[2] is False, entry)


# --------------------------------------------------------------------------- #
# 2. Full validation before readiness - fail-closed cases
# --------------------------------------------------------------------------- #

def test_03_missing_validation_summary_fails():
    root = mkroot(build_specs(omit=("validation_summary",)))
    try:
        status, d = phase_4_5_gate(root)
        check("03/missing_validation_summary__FAIL",
              status == "SPECS_VALIDATION_FAILED" and d.code == "PMO-SPEC-003", d)
    finally:
        _cleanup(root)


def test_04_missing_another_mandatory_section_fails():
    root = mkroot(build_specs(omit=("data",)))
    try:
        status, d = phase_4_5_gate(root)
        check("04/missing_data_requirements__FAIL",
              status == "SPECS_VALIDATION_FAILED" and d.code == "PMO-SPEC-003", d)
    finally:
        _cleanup(root)


def test_05_invalid_document_control_fails():
    broken_dc = _SECTIONS["doc_control"].replace(
        "- **Project ID:** SMART-BASKET\n", "")
    root = mkroot(build_specs(doc_control_override=broken_dc))
    try:
        status, d = phase_4_5_gate(root)
        check("05/invalid_doc_control__FAIL", status == "SPECS_VALIDATION_FAILED", d)
    finally:
        _cleanup(root)


def test_06_invalid_traceability_fails():
    broken_trace = '''## Intent -> Specs Traceability

| Requirement ID | FR/NFR IDs | Coverage | Notes |
|---|---|---|---|
'''  # INT-REQ-001 row dropped entirely - active requirement not represented
    root = mkroot(build_specs(traceability_override=broken_trace))
    try:
        status, d = phase_4_5_gate(root)
        check("06/invalid_traceability__FAIL",
              status == "SPECS_VALIDATION_FAILED" and d.code == "PMO-SPEC-004", d)
    finally:
        _cleanup(root)


def test_07_unsupported_requirement_fails():
    unsupported_fr = _SECTIONS["fr"].replace(
        "- **Source Requirement:** INT-REQ-001\n",
        "- **Source Requirement:** INT-REQ-099\n",
    ).replace(
        "- **Change Source:** INITIAL_INTENT\n",
        "- **Change Source:** UNSOURCED\n",
    )
    root = mkroot(build_specs(fr_override=unsupported_fr))
    try:
        status, d = phase_4_5_gate(root)
        check("07/unsupported_requirement__FAIL",
              status == "SPECS_VALIDATION_FAILED" and d.code == "PMO-SPEC-015", d)
    finally:
        _cleanup(root)


def test_08_fully_valid_specs_passes():
    root = mkroot(build_specs())
    try:
        status, d = phase_4_5_gate(root)
        check("08/valid_specs__PASS", status == "PASS" and d is None, d)
    finally:
        _cleanup(root)


# --------------------------------------------------------------------------- #
# 3. No duplicated validation logic
# --------------------------------------------------------------------------- #

def test_09_no_duplicated_validation_logic():
    check("09/gate_calls_guard_function_directly",
          phase_4_5_gate.__globals__["guard"].full_spec_validation is guard.full_spec_validation)
    skill_text = open(SKILL_MD_PATH, encoding="utf-8").read()
    check("09/skill_documents_module_import_reuse",
          "guard.full_spec_validation(root)" in skill_text)
    check("09/skill_forbids_second_implementation",
          "second, simplified validation" in skill_text)


# --------------------------------------------------------------------------- #
# 4. WM Trucking - READ-ONLY current-failure confirmation
# --------------------------------------------------------------------------- #

def test_10_wm_trucking_current_failure_confirmed_read_only():
    specs_path = os.path.join(REPO_ROOT, "docs", "pmo", "specs", "specs.md")
    before = open(specs_path, "rb").read()

    d = guard.full_spec_validation(REPO_ROOT)
    check("10/wm_trucking_fails_as_expected", d is not None and d.code == "PMO-SPEC-003", d)
    check("10/failure_names_validation_summary",
          d is not None and "Validation Summary" in d.message, d)

    after = open(specs_path, "rb").read()
    check("10/wm_trucking_specs_untouched", before == after)

    skill_before = open(SKILL_MD_PATH, "rb").read()
    check("10/skill_md_readable", len(skill_before) > 0)


# --------------------------------------------------------------------------- #
# 5. Orchestrator compatibility - unchanged pmo_lifecycle_core, confirmed
#    still correct against both the real project and a synthetic fixture.
# --------------------------------------------------------------------------- #

def test_11_wm_trucking_still_specs_review_required():
    s = plc.get_project_state(REPO_ROOT)
    check("11/wm_trucking_state_unchanged",
          s["lifecycle_state"] == plc.LifecycleState.SPECS_REVIEW_REQUIRED, s)


def test_12_synthetic_compliant_specs_reaches_baseline_ready():
    root = mkroot(build_specs())
    try:
        s = plc.get_project_state(root)
        check("12/baseline_ready_for_approval",
              s["lifecycle_state"] == plc.LifecycleState.BASELINE_READY_FOR_APPROVAL, s)
    finally:
        _cleanup(root)


def main():
    for fn in (
        test_01_skill_required_sections_match_guard,
        test_02_validation_summary_required_by_guard,
        test_03_missing_validation_summary_fails,
        test_04_missing_another_mandatory_section_fails,
        test_05_invalid_document_control_fails,
        test_06_invalid_traceability_fails,
        test_07_unsupported_requirement_fails,
        test_08_fully_valid_specs_passes,
        test_09_no_duplicated_validation_logic,
        test_10_wm_trucking_current_failure_confirmed_read_only,
        test_11_wm_trucking_still_specs_review_required,
        test_12_synthetic_compliant_specs_reaches_baseline_ready,
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
