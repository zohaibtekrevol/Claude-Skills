#!/usr/bin/env python3
"""Regression tests for specs-governance-guard.py (PMO-SPEC-001 .. PMO-SPEC-020).

Standard-library `unittest`. Temporary fixtures only - the real Smart Basket
docs/pmo/specs/specs.md is never created. Scenarios A .. AK from the guard
specification are each covered by at least one test.
"""

import importlib.util
import os
import pathlib
import re
import shutil
import tempfile
import unittest

_HOOK_DIR = pathlib.Path(__file__).resolve().parent
_GUARD_PATH = _HOOK_DIR / "specs-governance-guard.py"
_spec = importlib.util.spec_from_file_location("specs_governance_guard", _GUARD_PATH)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

GOOD_CONFIG = '''schema_version: "1.0"

project:
  id: "SMART-BASKET"
  name: "Smart Basket"
  client: "Smart Basket / eBasket KSA"

repository:
  provider: "bitbucket"
  workspace: "devops-tekrevol"
  repository: "lets-explore-more-specs"
  verified: true

workflow:
  current_stage: "SCOPE_READY_FOR_CLIENT_REVIEW"
  scope:
    approved: false
    pm_review: "COMPLETE"
    client_review: "PENDING"
  intent:
    approved: true

artifacts:
  scope:
    latest_version: "0.1"
    approved_version: null
    status: "DRAFT_CLIENT_REVIEW"
  intent:
    latest_version: "1.0"
    status: "VALIDATED"
'''

GOOD_CONFIG_SPECS = GOOD_CONFIG.replace(
    '  intent:\n    latest_version: "1.0"\n    status: "VALIDATED"\n',
    '  intent:\n    latest_version: "1.0"\n    status: "VALIDATED"\n'
    '  specifications:\n    path: "docs/pmo/specs/specs.md"\n'
    '    latest_version: "0.1"\n    status: "PROVISIONAL"\n'
    '    execution_authorized: false\n',
)

GOOD_INTENT = '''# Project Intent: Smart Basket

| Field | Value |
|---|---|
| Intent Version | 1.0 |
| Status | VALIDATED |
'''

GOOD_SCOPE = '''# Scope of Work: Smart Basket

## 1. Document Control

| Field | Value |
|---|---|
| Project | Smart Basket |
| Scope Version | 0.1 |
| Status | DRAFT_CLIENT_REVIEW |

## 7. Detailed Scope of Work

#### SCP-REQ-001 - Customer places an online order
- **Statement:** The customer can place an order and pay online or by cash on delivery.

#### SCP-REQ-002 - Bilingual customer experience
- **Statement:** The customer app is available in English and Arabic.
'''

GOOD_SPEC = '''# Specification: Smart Basket

## Specification Document Control

- **Project:** Smart Basket
- **Client:** Smart Basket / eBasket KSA
- **Project ID:** SMART-BASKET
- **Spec Version:** 0.1
- **Spec Status:** PROVISIONAL
- **Intent Version:** 1.0
- **Scope Version:** 0.1
- **Generated From:** docs/pmo/scope/scope-v0.1.md
- **Last Updated:** 2026-09-11T00:00:00Z
- **Execution Authorized:** false
- **Repository:** bitbucket:devops-tekrevol/lets-explore-more-specs

## Functional Requirements

### FR-001 - Customer places an online order

- **ID:** FR-001
- **Title:** Customer places an online order
- **Module:** MOD-004 / Cart, Checkout and Payments
- **Actor(s):** B2C customer
- **Requirement:** The system lets a signed-in B2C customer confirm a cart and place an order using a supported payment method.
- **Source Scope:** SCP-REQ-001
- **Source Intent:** INT-REQ-014
- **Introduced In:** 0.1
- **Last Modified In:** 0.1
- **Change Source:** INITIAL_SCOPE
- **Priority:** MUST
- **Preconditions:** The customer is authenticated and the cart holds at least one available item.
- **Trigger:** The customer confirms checkout.
- **Primary Behavior:** The system validates the cart, records the order and returns an order reference.
- **Business Rules:** BR-001
- **Validation Rules:** The cart must be non-empty and a delivery address must be selected.
- **Alternate / Exception Behavior:** If payment fails the order is not created and the customer may retry or choose Cash on Delivery.
- **Permissions:** A B2C customer may place their own order; other actors may not.
- **Inputs:** Cart contents, delivery address, payment selection.
- **Outputs:** A persisted order, an order reference and a confirmation notification.
- **Dependencies:** FR-002
- **Integration References:** INTG-001
- **OPEN References:** OPEN-002
- **Acceptance Criteria:** Given a signed-in customer with a valid cart When they confirm checkout Then the system creates an order using the confirmed details and returns a reference.
- **Status:** ACTIVE

### FR-002 - Customer switches app language

- **ID:** FR-002
- **Title:** Customer switches app language
- **Module:** MOD-013 / Localization
- **Actor(s):** B2C customer
- **Requirement:** The customer can switch the customer app between English and Arabic at any time.
- **Source Scope:** SCP-REQ-002
- **Source Intent:** INT-REQ-004
- **Introduced In:** 0.1
- **Last Modified In:** 0.1
- **Change Source:** INITIAL_SCOPE
- **Priority:** MUST
- **Preconditions:** The app is installed and open.
- **Trigger:** The customer selects a language from settings.
- **Primary Behavior:** The system re-renders customer-facing screens in the selected language.
- **Business Rules:** N/A
- **Validation Rules:** The selected language must be one of the supported set (English, Arabic).
- **Alternate / Exception Behavior:** If a translation string is missing the English string is shown as a fallback.
- **Permissions:** Any customer may change their own language preference.
- **Inputs:** Selected language code.
- **Outputs:** Updated UI language and a persisted preference.
- **Dependencies:** N/A
- **Acceptance Criteria:** Given the app is open When the customer selects Arabic Then all customer-facing UI text is presented in Arabic.
- **Status:** ACTIVE

## Non-Functional Requirements

### NFR-001 - Bilingual customer experience integrity

- **ID:** NFR-001
- **Title:** Bilingual customer experience integrity
- **Category:** Localization
- **Requirement:** The customer app fully supports English and Arabic including right-to-left layout for Arabic.
- **Source Scope:** SCP-REQ-002
- **Introduced In:** 0.1
- **Last Modified In:** 0.1
- **Change Source:** INITIAL_SCOPE
- **Acceptance Criteria:** Given the customer selects Arabic When any customer-facing screen renders Then layout direction is right-to-left and no text is clipped. RTL depth target remains OPEN (OPEN-009).
- **Status:** ACTIVE

## Business Rules

### BR-001 - Account required before checkout

- **ID:** BR-001
- **Rule:** A registered customer account is required before an order can be placed.
- **Traces To:** FR-001
- **Source:** SCP-REQ-001

## System States

### Order lifecycle state model

| State | Entry Condition | Permitted Transitions | Actor | Terminal | FR IDs |
|---|---|---|---|---|---|
| Pending | Order created, payment not settled | Confirmed, Cancelled | System, Admin | No | FR-001 |
| Confirmed | Payment settled or COD accepted | Cancelled | System | No | FR-001 |
| Cancelled | Cancellation processed | none | Admin | Yes | FR-001 |

## Data Requirements

| Entity | Field | Required | Validation | Related FR |
|---|---|---|---|---|
| Order | order_reference | Yes | System-generated, unique | FR-001 |
| Customer | preferred_language | No | One of English, Arabic | FR-002 |

## Integrations

| Integration | Provider | FR / NFR | OPEN |
|---|---|---|---|
| INTG-001 | Payment gateway (provider TBD) | FR-001 | OPEN-002 |

## Open Questions

| ID | Provenance | Origin | Question |
|---|---|---|---|
| OPEN-002 | INTENT | Intent OPEN-002 | Which payment providers are inside the committed baseline? |
| SCP-OPEN-001 | SCOPE | Requirement Gathering | Confirm the serviceable delivery area for launch. |
| SPEC-OPEN-001 | SPEC | Raised during specification authoring | Confirm the order-reference format shown on invoices. |

## Scope -> Specs Traceability

| Scope ID | FR/NFR IDs | Coverage | Notes |
|---|---|---|---|
| SCP-REQ-001 | FR-001, NFR-001 | COVERED |  |
| SCP-REQ-002 | FR-002 | PARTIALLY_COVERED | OPEN-002 |

## Specification Change History

| Version | Date | Change Source | Changed IDs | Summary | PM Decision |
|---|---|---|---|---|---|
| 0.1 | 2026-09-11 | INITIAL_SCOPE | FR-001, FR-002, NFR-001, BR-001 | Initial provisional specification generated from Scope v0.1 | Generated |

## Validation Summary

All active Scope requirements (SCP-REQ-001, SCP-REQ-002) are represented in the
Scope -> Specs Traceability matrix. Blocking Scope open questions remain visible.
Execution is not authorized.
'''

_HISTORY_0_1 = ("| 0.1 | 2026-09-11 | INITIAL_SCOPE | FR-001, FR-002, NFR-001, "
                "BR-001 | Initial provisional specification generated from "
                "Scope v0.1 | Generated |")
_HISTORY_0_2 = ("| 0.2 | 2026-09-18 | FDB-001 | FR-002 | Client clarification "
                "of checkout confirmation wording | Accepted |")

# feedback-driven update: Spec Version 0.2, FR-002 modified under FDB-001
SPEC_FEEDBACK_UPDATE = (
    GOOD_SPEC
    .replace("- **Spec Version:** 0.1", "- **Spec Version:** 0.2")
    .replace(
        "- **Last Modified In:** 0.1\n- **Change Source:** INITIAL_SCOPE\n"
        "- **Priority:** MUST\n"
        "- **Preconditions:** The app is installed and open.",
        "- **Last Modified In:** 0.2\n- **Change Source:** FDB-001\n"
        "- **Priority:** MUST\n"
        "- **Preconditions:** The app is installed and open.",
    )
    .replace(_HISTORY_0_1, _HISTORY_0_1 + "\n" + _HISTORY_0_2)
)


def _w(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def mkroot(spec=GOOD_SPEC, config=GOOD_CONFIG, scope=GOOD_SCOPE,
           intent=GOOD_INTENT, write_spec=True, feedback=None, crs=None):
    root = tempfile.mkdtemp(prefix="pmo-specs-guard-")
    os.makedirs(os.path.join(root, ".pmo"))
    os.makedirs(os.path.join(root, "docs", "pmo", "scope"))
    os.makedirs(os.path.join(root, "docs", "pmo", "intent"))
    os.makedirs(os.path.join(root, "docs", "pmo", "specs"))
    _w(os.path.join(root, ".pmo", "project-config.yaml"), config)
    _w(os.path.join(root, "docs", "pmo", "scope", "scope-v0.1.md"), scope)
    _w(os.path.join(root, "docs", "pmo", "intent", "intent.md"), intent)
    if write_spec:
        _w(os.path.join(root, "docs", "pmo", "specs", "specs.md"), spec)
    if feedback is not None:
        fd = os.path.join(root, "docs", "pmo", "feedback")
        os.makedirs(fd)
        for name, content in feedback.items():
            _w(os.path.join(fd, name), content)
    if crs is not None:
        cd = os.path.join(root, "docs", "pmo", "change-requests")
        os.makedirs(cd)
        for name, content in crs.items():
            _w(os.path.join(cd, name), content)
    return root


class SpecsGuardTests(unittest.TestCase):

    def _root(self, **kw):
        root = mkroot(**kw)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root

    def _spec_path(self, root):
        return os.path.join(root, "docs", "pmo", "specs", "specs.md")

    # ------------------------------------------------------------------ #
    # A - happy path
    # ------------------------------------------------------------------ #
    def test_A_initial_pm_reviewed_scope_provisional_specs_allow(self):
        root = self._root()
        self.assertIsNone(guard.full_spec_validation(root))

    # ------------------------------------------------------------------ #
    # B - Scope not PM-reviewed -> PMO-SPEC-001
    # ------------------------------------------------------------------ #
    def test_B_scope_not_pm_reviewed_denies_001(self):
        cfg = GOOD_CONFIG.replace('pm_review: "COMPLETE"',
                                  'pm_review: "IN_PROGRESS"')
        root = self._root(config=cfg)
        d = guard.full_spec_validation(root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-SPEC-001")
        self.assertIsNone(guard.validate_scope_readiness(self._root()))

    # ------------------------------------------------------------------ #
    # C - non-canonical live Specs path -> PMO-SPEC-002
    # ------------------------------------------------------------------ #
    def test_C_non_canonical_spec_path_denies_002(self):
        root = self._root(write_spec=False)
        payload = {"tool_name": "Write", "cwd": root,
                   "tool_input": {"file_path": os.path.join(
                       root, "docs/pmo/specs/specs-v0.1.md"), "content": "# x"}}
        d = guard.process(payload)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-SPEC-002")
        for bad in ("docs/pmo/specs/specs-v0.2.md",
                    "docs/pmo/specs/latest-specs.md",
                    "docs/pmo/specs/final-specs.md"):
            self.assertEqual(guard.validate_canonical_path(bad).code,
                             "PMO-SPEC-002")
        self.assertIsNone(
            guard.validate_canonical_path("docs/pmo/specs/specs.md"))

    # ------------------------------------------------------------------ #
    # D - incomplete progressive authoring -> ALLOW
    # ------------------------------------------------------------------ #
    def test_D_progressive_incomplete_authoring_allow(self):
        root = self._root(write_spec=False)
        partial = ("# Specification: Smart Basket\n\n"
                   "## Specification Document Control\n\n"
                   "- **Project:** Smart Basket\n\n"
                   "## Functional Requirements\n\n"
                   "### FR-001 - Customer places an online order\n\n"
                   "- **ID:** FR-001\n- **Status:** ACTIVE\n")
        payload = {"tool_name": "Write", "cwd": root,
                   "tool_input": {"file_path": self._spec_path(root),
                                  "content": partial}}
        self.assertIsNone(guard.process(payload))

    # ------------------------------------------------------------------ #
    # E / F - duplicate FR / NFR definition -> PMO-SPEC-005
    # ------------------------------------------------------------------ #
    def test_E_duplicate_fr_definition_denies_005(self):
        root = self._root(write_spec=False)
        dup = GOOD_SPEC + "\n\n### FR-001 - Duplicate\n- **Status:** ACTIVE\n"
        payload = {"tool_name": "Write", "cwd": root,
                   "tool_input": {"file_path": self._spec_path(root),
                                  "content": dup}}
        d = guard.process(payload)
        self.assertEqual(d.code, "PMO-SPEC-005")

    def test_F_duplicate_nfr_definition_denies_005(self):
        root = self._root(write_spec=False)
        dup = GOOD_SPEC + "\n\n### NFR-001 - Duplicate\n- **Status:** ACTIVE\n"
        payload = {"tool_name": "Write", "cwd": root,
                   "tool_input": {"file_path": self._spec_path(root),
                                  "content": dup}}
        d = guard.process(payload)
        self.assertEqual(d.code, "PMO-SPEC-005")

    def test_E2_malformed_identifier_syntax_denies_005(self):
        bad = GOOD_SPEC.replace("### FR-002 - Customer switches app language",
                                "### FR-02 - Customer switches app language")
        d = guard.validate_identifier_uniqueness(bad)
        self.assertEqual(d.code, "PMO-SPEC-005")

    # ------------------------------------------------------------------ #
    # G - retired FR id reused for unrelated requirement -> PMO-SPEC-006
    # ------------------------------------------------------------------ #
    def test_G_retired_fr_reuse_denies_006(self):
        prev = {"FR-005": {"status": "RETIRED",
                           "source_scope": {"SCP-REQ-010"},
                           "title": "Legacy loyalty points",
                           "requirement": "old"}}
        new = {"FR-005": {"status": "ACTIVE",
                          "source_scope": {"SCP-REQ-030"},
                          "title": "Warehouse transfer note",
                          "requirement": "new"}}
        d = guard.compare_requirement_identity(prev, new)
        self.assertEqual(d.code, "PMO-SPEC-006")

    def test_G2_same_identity_kept_allows(self):
        prev = {"FR-005": {"status": "ACTIVE", "source_scope": {"SCP-REQ-010"},
                           "title": "Thing", "requirement": "r"}}
        new = {"FR-005": {"status": "ACTIVE", "source_scope": {"SCP-REQ-010"},
                          "title": "Thing", "requirement": "r"}}
        self.assertIsNone(guard.compare_requirement_identity(prev, new))

    # ------------------------------------------------------------------ #
    # H / I / J - Spec version progression -> PMO-SPEC-007
    # ------------------------------------------------------------------ #
    def test_H_initial_version_not_0_1_denies_007(self):
        d = guard.validate_spec_version((0, 2), [(0, 2)], False)
        self.assertEqual(d.code, "PMO-SPEC-007")

    def test_I_valid_0_1_to_0_2_allows(self):
        self.assertIsNone(
            guard.validate_spec_version((0, 2), [(0, 1), (0, 2)], False))

    def test_J_invalid_0_1_to_0_3_denies_007(self):
        d = guard.validate_spec_version((0, 3), [(0, 1), (0, 3)], False)
        self.assertEqual(d.code, "PMO-SPEC-007")

    def test_J2_promotion_to_1_0_requires_baseline(self):
        self.assertEqual(
            guard.validate_spec_version((1, 0), [(0, 3), (1, 0)], False).code,
            "PMO-SPEC-007")
        self.assertIsNone(
            guard.validate_spec_version((1, 0), [(0, 3), (1, 0)], True))

    # ------------------------------------------------------------------ #
    # K / L - PROVISIONAL vs ACTIVE -> PMO-SPEC-008
    # ------------------------------------------------------------------ #
    def test_K_provisional_pre_baseline_allows(self):
        self.assertIsNone(
            guard.validate_spec_status({"spec status": "PROVISIONAL"}, False))

    def test_L_active_without_approved_scope_denies_008(self):
        d = guard.validate_spec_status({"spec status": "ACTIVE"}, False)
        self.assertEqual(d.code, "PMO-SPEC-008")
        self.assertIsNone(
            guard.validate_spec_status({"spec status": "ACTIVE"}, True))

    # ------------------------------------------------------------------ #
    # M / N - Execution Authorized independence -> PMO-SPEC-009
    # ------------------------------------------------------------------ #
    def test_M_initial_execution_authorized_false_allows(self):
        root = self._root(write_spec=False)
        payload = {"tool_name": "Write", "cwd": root,
                   "tool_input": {"file_path": self._spec_path(root),
                                  "content": GOOD_SPEC}}
        self.assertIsNone(guard.process(payload))

    def test_N_unauthorized_false_to_true_denies_009(self):
        root = self._root()
        payload = {"tool_name": "Edit", "cwd": root,
                   "tool_input": {
                       "file_path": self._spec_path(root),
                       "old_string": "- **Execution Authorized:** false",
                       "new_string": "- **Execution Authorized:** true"}}
        d = guard.process(payload)
        self.assertEqual(d.code, "PMO-SPEC-009")

    def test_N2_authorized_false_to_true_with_pm_evidence_allows(self):
        root = self._root()
        payload = {"tool_name": "Edit", "cwd": root,
                   "tool_input": {
                       "file_path": self._spec_path(root),
                       "old_string": "- **Execution Authorized:** false",
                       "new_string": "- **Execution Authorized:** true\n"
                       "- **Execution Authorization Evidence:** PM-DECISION "
                       "2026-09-20 recorded by PM"}}
        self.assertIsNone(guard.process(payload))

    # ------------------------------------------------------------------ #
    # O / P - FR / NFR structure -> PMO-SPEC-010 / 011
    # ------------------------------------------------------------------ #
    def test_O_active_fr_missing_acceptance_criteria_denies_010(self):
        block = guard.parse_fr_definitions(GOOD_SPEC)["FR-001"]
        block = re.sub(r"(?m)^- \*\*Acceptance Criteria:\*\*.*$",
                       "- **Acceptance Criteria:**", block)
        d = guard.validate_fr_structure({"FR-001": block})
        self.assertEqual(d.code, "PMO-SPEC-010")

    def test_P_nfr_blank_verification_denied_open_threshold_allowed(self):
        good = guard.parse_nfr_definitions(GOOD_SPEC)["NFR-001"]
        blank = re.sub(r"(?m)^- \*\*Acceptance Criteria:\*\*.*$",
                       "- **Acceptance Criteria:**", good)
        self.assertEqual(
            guard.validate_nfr_structure({"NFR-001": blank}).code,
            "PMO-SPEC-011")
        open_thr = re.sub(
            r"(?m)^- \*\*Acceptance Criteria:\*\*.*$",
            "- **Acceptance Criteria:** Latency target is OPEN (OPEN-012); "
            "verify no regression against the pre-change baseline.", good)
        self.assertIsNone(guard.validate_nfr_structure({"NFR-001": open_thr}))

    # ------------------------------------------------------------------ #
    # Q / R / S / T - OPEN provenance -> PMO-SPEC-012
    # ------------------------------------------------------------------ #
    def test_Q_intent_open_retained_allows(self):
        self.assertIsNone(guard.validate_open_provenance(
            [{"id": "OPEN-002", "provenance": "INTENT",
              "origin": "Intent OPEN-002"}]))

    def test_R_scope_open_retained_allows(self):
        self.assertIsNone(guard.validate_open_provenance(
            [{"id": "SCP-OPEN-001", "provenance": "SCOPE",
              "origin": "Requirement Gathering"}]))

    def test_S_upstream_open_renamed_spec_open_denies_012(self):
        d = guard.validate_open_provenance(
            [{"id": "SPEC-OPEN-001", "provenance": "INTENT",
              "origin": "OPEN-002"}])
        self.assertEqual(d.code, "PMO-SPEC-012")
        d2 = guard.validate_open_provenance(
            [{"id": "OPEN-002", "provenance": "SPEC", "origin": ""}])
        self.assertEqual(d2.code, "PMO-SPEC-012")

    def test_T_genuine_new_spec_open_allows(self):
        self.assertIsNone(guard.validate_open_provenance(
            [{"id": "SPEC-OPEN-001", "provenance": "SPEC",
              "origin": "Raised during specification authoring"}]))

    # ------------------------------------------------------------------ #
    # U / V - Specification Change History -> PMO-SPEC-013
    # ------------------------------------------------------------------ #
    def test_U_current_version_missing_from_history_denies_013(self):
        spec = GOOD_SPEC.replace("- **Spec Version:** 0.1",
                                 "- **Spec Version:** 0.2")
        root = self._root(spec=spec)
        d = guard.full_spec_validation(root)
        self.assertEqual(d.code, "PMO-SPEC-013")

    def test_V_initial_change_source_initial_scope_allows(self):
        self.assertIsNone(guard.validate_change_history((0, 1), GOOD_SPEC))

    # ------------------------------------------------------------------ #
    # W / X / AB - feedback / CR change provenance -> PMO-SPEC-014
    # ------------------------------------------------------------------ #
    def test_W_feedback_update_with_valid_fdb_provenance_allows(self):
        root = self._root(spec=SPEC_FEEDBACK_UPDATE,
                          feedback={"FDB-001.md": "# Feedback FDB-001\nStatus: ACCEPTED\n"})
        self.assertIsNone(guard.full_spec_validation(root))

    def test_AB_specs_only_feedback_update_keeps_scope_version(self):
        self.assertIn("- **Scope Version:** 0.1", SPEC_FEEDBACK_UPDATE)
        root = self._root(spec=SPEC_FEEDBACK_UPDATE,
                          feedback={"FDB-001.md": "Status: ACCEPTED\n"})
        self.assertIsNone(guard.validate_source_versions(
            guard.parse_spec_metadata(SPEC_FEEDBACK_UPDATE), root))

    def test_X_feedback_update_without_record_denies_014(self):
        root = self._root(spec=SPEC_FEEDBACK_UPDATE,
                          feedback={".gitkeep": ""})
        d = guard.full_spec_validation(root)
        self.assertEqual(d.code, "PMO-SPEC-014")

    # ------------------------------------------------------------------ #
    # Y - unapproved Scope expansion -> PMO-SPEC-015
    # ------------------------------------------------------------------ #
    def test_Y_active_fr_without_scope_or_change_origin_denies_015(self):
        spec = GOOD_SPEC.replace("- **Source Scope:** SCP-REQ-001\n",
                                 "- **Source Scope:** N/A\n", 1)
        root = self._root(spec=spec)
        d = guard.full_spec_validation(root)
        self.assertEqual(d.code, "PMO-SPEC-015")

    # ------------------------------------------------------------------ #
    # Z - project identity -> PMO-SPEC-016
    # ------------------------------------------------------------------ #
    def test_Z_wrong_project_id_denies_016(self):
        cfg = guard.parse_project_config(GOOD_CONFIG)
        d = guard.validate_project_identity(
            {"project id": "WRONG-CO", "project": "Smart Basket",
             "client": "Smart Basket / eBasket KSA"}, cfg)
        self.assertEqual(d.code, "PMO-SPEC-016")

    # ------------------------------------------------------------------ #
    # AA - Scope version metadata mismatch -> PMO-SPEC-017
    # ------------------------------------------------------------------ #
    def test_AA_scope_version_metadata_mismatch_denies_017(self):
        spec = GOOD_SPEC.replace("- **Scope Version:** 0.1",
                                 "- **Scope Version:** 0.2")
        root = self._root(spec=spec)
        d = guard.full_spec_validation(root)
        self.assertEqual(d.code, "PMO-SPEC-017")

    # ------------------------------------------------------------------ #
    # AC - PMO state protection -> PMO-SPEC-018
    # ------------------------------------------------------------------ #
    def test_AC_change_to_scope_approved_denies_018(self):
        d = guard.validate_pmo_state(
            GOOD_CONFIG,
            GOOD_CONFIG.replace("    approved: false", "    approved: true"))
        self.assertEqual(d.code, "PMO-SPEC-018")
        self.assertIsNone(guard.validate_pmo_state(GOOD_CONFIG, GOOD_CONFIG))

    def test_AC2_hook_blocks_config_write_moving_scope_state(self):
        root = self._root(config=GOOD_CONFIG_SPECS)
        cfg_path = os.path.join(root, ".pmo", "project-config.yaml")
        payload = {"tool_name": "Edit", "cwd": root,
                   "tool_input": {"file_path": cfg_path,
                                  "old_string": "    approved: false",
                                  "new_string": "    approved: true"}}
        d = guard.process(payload)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-SPEC-018")

    def test_AC3_specs_state_note_only_is_allowed(self):
        after = GOOD_CONFIG_SPECS.replace("execution_authorized: false",
                                          "execution_authorized: true")
        self.assertIsNone(guard.validate_pmo_state(GOOD_CONFIG_SPECS, after))

    # ------------------------------------------------------------------ #
    # AD - repository publishing separation -> PMO-SPEC-019
    # ------------------------------------------------------------------ #
    def test_AD_repo_not_verified_local_allow_publish_blocked(self):
        cfg = GOOD_CONFIG.replace("verified: true", "verified: false")
        root = self._root(config=cfg)
        self.assertIsNone(guard.full_spec_validation(root))
        d = guard.validate_publish_readiness(root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PUBLISH_BLOCKED_REPOSITORY_NOT_VERIFIED")

    # ------------------------------------------------------------------ #
    # AE - fail-closed internal error -> PMO-SPEC-020
    # ------------------------------------------------------------------ #
    def test_AE_internal_exception_fails_closed_020(self):
        root = self._root()
        original = guard.validate_required_sections

        def boom(*_a, **_k):
            raise RuntimeError("boom")

        guard.validate_required_sections = boom
        try:
            d = guard.full_spec_validation(root)
        finally:
            guard.validate_required_sections = original
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-SPEC-020")

    # ------------------------------------------------------------------ #
    # AF - active SCP-REQ missing from matrix -> PMO-SPEC-004
    # ------------------------------------------------------------------ #
    def test_AF_active_scp_req_missing_from_matrix_denies_004(self):
        spec = GOOD_SPEC.replace(
            "| SCP-REQ-002 | FR-002 | PARTIALLY_COVERED | OPEN-002 |\n", "")
        root = self._root(spec=spec)
        d = guard.full_spec_validation(root)
        self.assertEqual(d.code, "PMO-SPEC-004")

    # ------------------------------------------------------------------ #
    # AG / AH - Business Rule governance -> PMO-SPEC-005
    # ------------------------------------------------------------------ #
    def test_AG_orphan_business_rule_denies_005(self):
        spec = GOOD_SPEC.replace("- **Traces To:** FR-001",
                                 "- **Traces To:** (none)")
        root = self._root(spec=spec)
        d = guard.full_spec_validation(root)
        self.assertEqual(d.code, "PMO-SPEC-005")

    def test_AH_business_rule_linked_to_fr_allows(self):
        self.assertIsNone(
            guard.validate_business_rules(guard.parse_business_rules(GOOD_SPEC)))

    # ------------------------------------------------------------------ #
    # AI / AJ / AK - git gates and unrelated Bash
    # ------------------------------------------------------------------ #
    def test_AI_git_add_complete_specs_allows(self):
        root = self._root()
        payload = {"tool_name": "Bash", "cwd": root,
                   "tool_input": {"command": "git add docs/pmo/specs/specs.md"}}
        self.assertIsNone(guard.process(payload))

    def test_AJ_git_add_incomplete_traceability_denies(self):
        spec = GOOD_SPEC.replace(
            "| SCP-REQ-002 | FR-002 | PARTIALLY_COVERED | OPEN-002 |\n", "")
        root = self._root(spec=spec)
        payload = {"tool_name": "Bash", "cwd": root,
                   "tool_input": {"command":
                                  "git add docs/pmo/specs/specs.md"}}
        d = guard.process(payload)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-SPEC-004")

    def test_AJ2_git_commit_gate_runs_full_validation(self):
        spec = GOOD_SPEC.replace(
            "| SCP-REQ-002 | FR-002 | PARTIALLY_COVERED | OPEN-002 |\n", "")
        root = self._root(spec=spec)
        payload = {"tool_name": "Bash", "cwd": root,
                   "tool_input": {"command":
                                  'git commit -am "wip specs.md"'}}
        d = guard.process(payload)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-SPEC-004")

    def test_AK_unrelated_bash_allows(self):
        root = self._root()
        payload = {"tool_name": "Bash", "cwd": root,
                   "tool_input": {"command": "echo hello && ls -la"}}
        self.assertIsNone(guard.process(payload))

    def test_AK2_git_add_without_specs_on_disk_allows(self):
        root = self._root(write_spec=False)
        payload = {"tool_name": "Bash", "cwd": root,
                   "tool_input": {"command": "git add docs/pmo/specs/specs.md"}}
        self.assertIsNone(guard.process(payload))

    # ------------------------------------------------------------------ #
    # schema gate (PMO-SPEC-003) and CR provenance extras
    # ------------------------------------------------------------------ #
    def test_schema_missing_section_denies_003(self):
        spec = GOOD_SPEC.replace("## Validation Summary", "## Wrap Up")
        d = guard.validate_required_sections(spec)
        self.assertEqual(d.code, "PMO-SPEC-003")

    def test_schema_missing_doc_control_field_denies_003(self):
        spec = GOOD_SPEC.replace("- **Repository:** bitbucket:devops-tekrevol/"
                                 "lets-explore-more-specs\n", "")
        d = guard.validate_required_sections(spec)
        self.assertEqual(d.code, "PMO-SPEC-003")

    def test_active_fr_via_unapproved_cr_denies_014(self):
        spec = GOOD_SPEC.replace(
            "- **Last Modified In:** 0.1\n- **Change Source:** INITIAL_SCOPE\n"
            "- **Priority:** MUST\n"
            "- **Preconditions:** The app is installed and open.",
            "- **Last Modified In:** 0.2\n- **Change Source:** CR-007\n"
            "- **Priority:** MUST\n"
            "- **Preconditions:** The app is installed and open.",
        ).replace("- **Spec Version:** 0.1", "- **Spec Version:** 0.2") \
         .replace(_HISTORY_0_1, _HISTORY_0_1 + "\n"
                  "| 0.2 | 2026-09-18 | CR-007 | FR-002 | Requested change | "
                  "Accepted |")
        root = self._root(spec=spec, crs={"CR-007.md":
                                          "# CR-007\nStatus: PENDING\n"})
        d = guard.full_spec_validation(root)
        self.assertEqual(d.code, "PMO-SPEC-014")

    def test_active_fr_via_approved_cr_allows(self):
        spec = GOOD_SPEC.replace(
            "- **Last Modified In:** 0.1\n- **Change Source:** INITIAL_SCOPE\n"
            "- **Priority:** MUST\n"
            "- **Preconditions:** The app is installed and open.",
            "- **Last Modified In:** 0.2\n- **Change Source:** CR-007\n"
            "- **Priority:** MUST\n"
            "- **Preconditions:** The app is installed and open.",
        ).replace("- **Spec Version:** 0.1", "- **Spec Version:** 0.2") \
         .replace(_HISTORY_0_1, _HISTORY_0_1 + "\n"
                  "| 0.2 | 2026-09-18 | CR-007 | FR-002 | Requested change | "
                  "Accepted |")
        root = self._root(spec=spec, crs={"CR-007.md":
                                          "# CR-007\nStatus: APPROVED\n"})
        self.assertIsNone(guard.full_spec_validation(root))

    def test_detect_relevant_git_action(self):
        self.assertEqual(
            guard.detect_relevant_git_action("git add docs/pmo/specs/specs.md"),
            ("git_add", True))
        self.assertEqual(
            guard.detect_relevant_git_action("git add README.md"),
            ("git_add", False))
        self.assertEqual(
            guard.detect_relevant_git_action("git push origin main"),
            ("git_push", False))
        self.assertEqual(
            guard.detect_relevant_git_action("ls -la"), (None, False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
