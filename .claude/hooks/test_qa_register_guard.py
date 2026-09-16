#!/usr/bin/env python3
"""Regression tests for qa-register-guard.py and qa_register_core.py
(PMO-QA-001 .. PMO-QA-011).

Standard-library `unittest`. Temporary fixtures only - no real project's
docs/pmo/requirements/questions-and-assumptions.md is ever created here.
"""

import importlib.util
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

_HOOK_DIR = pathlib.Path(__file__).resolve().parent
_LIB_DIR = _HOOK_DIR.parent / "lib"
sys.path.insert(0, str(_LIB_DIR))

_GUARD_PATH = _HOOK_DIR / "qa-register-guard.py"
_spec = importlib.util.spec_from_file_location("qa_register_guard", _GUARD_PATH)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

import qa_register_core as qac  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

GOOD_CONFIG = '''project:
  id: "TEST-CO"
  name: "Test Co"
  client: "Test Co"
'''

GOOD_INTENT = '''# Intent

## Document Control

- **Project:** Test Co
- **Client:** Test Co
- **Project ID:** TEST-CO
- **Intent Version:** 1.0
- **Status:** VALIDATED

## 6. High-Level Product Requirements

| ID | Requirement |
|---|---|
| INT-REQ-001 | Customer app |
| INT-REQ-002 | Rider app |
'''

DRAFT_INTENT = GOOD_INTENT.replace("**Status:** VALIDATED", "**Status:** DRAFT")

GOOD_APPROVAL = '''decision: APPROVED
approval_source: PM_EXPLICIT
artifact: docs/pmo/intent/intent.md
version: "1.0"
approved_by: Jane PM
'''

WRONG_VERSION_APPROVAL = GOOD_APPROVAL.replace('version: "1.0"', 'version: "0.9"')


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def record(rid, rtype="QUESTION", statement="Statement text",
          why="Blocks downstream design.", source="SRC-001", related="",
          owner="PM", status="OPEN", blocking="YES", resolution="",
          authority="", evidence="", impact="Impacts checkout FR."):
    lines = [
        "#### {} - Title".format(rid),
        "",
        "- **ID:** {}".format(rid),
        "- **Type:** {}".format(rtype),
        "- **Statement:** {}".format(statement),
        "- **Why Resolution Is Required:** {}".format(why),
        "- **Source / Evidence:** {}".format(source),
        "- **Related Intent Item:** {}".format(related),
        "- **Owner:** {}".format(owner),
        "- **Status:** {}".format(status),
        "- **Blocking:** {}".format(blocking),
        "- **Resolution:** {}".format(resolution),
        "- **Resolution Authority:** {}".format(authority),
        "- **Resolution Evidence / Date:** {}".format(evidence),
        "- **Specs Impact:** {}".format(impact),
        "",
    ]
    return "\n".join(lines)


def qa_doc(records_md, project="Test Co"):
    return (
        "# Questions & Assumptions\n\n"
        "## Document Control\n\n"
        "- **Project:** {}\n"
        "- **Client:** Test Co\n"
        "- **Project ID:** TEST-CO\n"
        "- **PM:** Jane PM\n"
        "- **Date:** 2026-09-16\n"
        "- **Intent Version:** 1.0\n\n"
        "## Register\n\n"
        "{}".format(project, records_md)
    )


GOOD_QA = qa_doc(record(
    "QST-001", status="OPEN", blocking="NO",
))


def mkroot(config=GOOD_CONFIG, intent=GOOD_INTENT, approval=GOOD_APPROVAL):
    root = tempfile.mkdtemp(prefix="pmo-qa-guard-")
    os.makedirs(os.path.join(root, ".pmo", "approvals"), exist_ok=True)
    os.makedirs(os.path.join(root, "docs", "pmo", "intent"), exist_ok=True)
    os.makedirs(os.path.join(root, "docs", "pmo", "requirements"), exist_ok=True)
    if config is not None:
        _w(os.path.join(root, ".pmo", "project-config.yaml"), config)
    if intent is not None:
        _w(os.path.join(root, "docs", "pmo", "intent", "intent.md"), intent)
    if approval is not None:
        _w(os.path.join(root, ".pmo", "approvals", "intent-approval.yaml"), approval)
    return root


class QaRegisterGuardTests(unittest.TestCase):

    def _root(self, **kw):
        root = mkroot(**kw)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root

    # ------------------------------------------------------------------ #
    # Happy path
    # ------------------------------------------------------------------ #
    def test_A_well_formed_register_allowed(self):
        root = self._root()
        d = guard.full_qa_validation(GOOD_QA, root)
        self.assertIsNone(d)

    def test_A2_write_payload_allowed(self):
        root = self._root()
        payload = {
            "tool_name": "Write", "cwd": root,
            "tool_input": {
                "file_path": os.path.join(
                    root, "docs/pmo/requirements/questions-and-assumptions.md"),
                "content": GOOD_QA,
            },
        }
        self.assertIsNone(guard.process(payload))

    # ------------------------------------------------------------------ #
    # PMO-QA-001 - Intent prerequisite
    # ------------------------------------------------------------------ #
    def test_B_missing_intent_denies_001(self):
        root = self._root(intent=None)
        d = guard.full_qa_validation(GOOD_QA, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-001")

    def test_C_non_validated_intent_denies_001(self):
        root = self._root(intent=DRAFT_INTENT)
        d = guard.full_qa_validation(GOOD_QA, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-001")

    def test_D_missing_approval_denies_001(self):
        root = self._root(approval=None)
        d = guard.full_qa_validation(GOOD_QA, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-001")

    def test_D2_mismatched_approval_version_denies_001(self):
        root = self._root(approval=WRONG_VERSION_APPROVAL)
        d = guard.full_qa_validation(GOOD_QA, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-001")

    # ------------------------------------------------------------------ #
    # PMO-QA-002 - project identity
    # ------------------------------------------------------------------ #
    def test_E_project_identity_mismatch_denies_002(self):
        root = self._root()
        bad = qa_doc(record("QST-001", status="OPEN", blocking="NO"),
                    project="Someone Else Co")
        d = guard.full_qa_validation(bad, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-002")

    # ------------------------------------------------------------------ #
    # PMO-QA-003 - schema / required fields
    # ------------------------------------------------------------------ #
    def test_F_missing_doc_control_field_denies_003(self):
        root = self._root()
        bad = GOOD_QA.replace("- **PM:** Jane PM\n", "")
        d = guard.full_qa_validation(bad, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-003")

    def test_G_missing_record_field_denies_003(self):
        root = self._root()
        bad = qa_doc(record("QST-001", statement="", status="OPEN", blocking="NO"))
        d = guard.full_qa_validation(bad, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-003")

    # ------------------------------------------------------------------ #
    # PMO-QA-004 / 005 / 006 - Type / Status / Blocking validity
    # ------------------------------------------------------------------ #
    def test_H_invalid_type_denies_004(self):
        root = self._root()
        bad = qa_doc(record("QST-001", rtype="OBSERVATION", status="OPEN",
                            blocking="NO"))
        d = guard.full_qa_validation(bad, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-004")

    def test_I_invalid_status_denies_005(self):
        root = self._root()
        bad = qa_doc(record("QST-001", status="PENDING", blocking="NO"))
        d = guard.full_qa_validation(bad, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-005")

    def test_J_invalid_blocking_denies_006(self):
        root = self._root()
        bad = qa_doc(record("QST-001", status="OPEN", blocking="MAYBE"))
        d = guard.full_qa_validation(bad, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-006")

    def test_J2_blocking_never_inferred_from_absence(self):
        root = self._root()
        bad = qa_doc(record("QST-001", status="OPEN", blocking=""))
        d = guard.full_qa_validation(bad, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-006")

    # ------------------------------------------------------------------ #
    # PMO-QA-007 - duplicate / malformed ids
    # ------------------------------------------------------------------ #
    def test_K_duplicate_id_denies_007(self):
        root = self._root()
        bad = qa_doc(
            record("QST-001", status="OPEN", blocking="NO")
            + record("QST-001", status="RESOLVED", blocking="NO",
                     resolution="Resolved.", authority="PM",
                     evidence="2026-09-16"))
        d = guard.full_qa_validation(bad, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-007")

    def test_L_malformed_id_denies_007(self):
        root = self._root()
        bad = qa_doc("#### QST-1a - Title\n\n- **Status:** OPEN\n")
        d = guard.full_qa_validation(bad, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-007")

    # ------------------------------------------------------------------ #
    # PMO-QA-008 - resolution required when a record claims resolution
    # ------------------------------------------------------------------ #
    def test_M_resolved_without_resolution_denies_008(self):
        root = self._root()
        bad = qa_doc(record("QST-001", status="RESOLVED", blocking="NO"))
        d = guard.full_qa_validation(bad, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-008")

    def test_M2_resolved_with_full_resolution_allowed(self):
        root = self._root()
        good = qa_doc(record(
            "QST-001", status="RESOLVED", blocking="NO",
            resolution="Payment gateway confirmed as Stripe.",
            authority="PM_EXPLICIT", evidence="2026-09-16",
        ))
        self.assertIsNone(guard.full_qa_validation(good, root))

    def test_M3_confirmed_without_resolution_denies_008(self):
        root = self._root()
        bad = qa_doc(record("ASM-001", rtype="ASSUMPTION", status="CONFIRMED",
                            blocking="NO"))
        d = guard.full_qa_validation(bad, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-008")

    def test_M4_rejected_without_resolution_denies_008(self):
        root = self._root()
        bad = qa_doc(record("ASM-001", rtype="ASSUMPTION", status="REJECTED",
                            blocking="NO"))
        d = guard.full_qa_validation(bad, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-008")

    def test_M5_deferred_without_authority_denies_008(self):
        root = self._root()
        bad = qa_doc(record("QST-001", status="DEFERRED", blocking="NO"))
        d = guard.full_qa_validation(bad, root)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-008")

    def test_M6_deferred_with_authority_no_date_allowed(self):
        root = self._root()
        good = qa_doc(record(
            "QST-001", status="DEFERRED", blocking="NO",
            resolution="Timing decided later; no date invented.",
            authority="PM_EXPLICIT",
        ))
        self.assertIsNone(guard.full_qa_validation(good, root))

    def test_M7_non_blocking_with_authority_allowed(self):
        root = self._root()
        good = qa_doc(record(
            "QST-001", status="NON_BLOCKING", blocking="NO",
            resolution="Classified non-blocking for this baseline.",
            authority="PM_EXPLICIT",
        ))
        self.assertIsNone(guard.full_qa_validation(good, root))

    def test_M8_open_with_no_resolution_fields_allowed(self):
        root = self._root()
        self.assertIsNone(guard.full_qa_validation(GOOD_QA, root))

    # ------------------------------------------------------------------ #
    # PMO-QA-009 - no silent loss of a prior resolution
    # ------------------------------------------------------------------ #
    def test_N_resolution_blanked_denies_009(self):
        old = qa_doc(record(
            "QST-001", status="RESOLVED", blocking="NO",
            resolution="Decided X.", authority="PM_EXPLICIT",
            evidence="2026-09-16",
        ))
        new = qa_doc(record("QST-001", status="RESOLVED", blocking="NO"))
        err = qac.detect_resolution_regression(old, new)
        self.assertIsNotNone(err)

    def test_N2_record_removed_denies_009(self):
        old = qa_doc(record(
            "QST-001", status="RESOLVED", blocking="NO",
            resolution="Decided X.", authority="PM_EXPLICIT",
            evidence="2026-09-16",
        ))
        new = qa_doc("")
        err = qac.detect_resolution_regression(old, new)
        self.assertIsNotNone(err)

    def test_N3_explicit_reopen_to_open_allowed(self):
        old = qa_doc(record(
            "QST-001", status="RESOLVED", blocking="NO",
            resolution="Decided X.", authority="PM_EXPLICIT",
            evidence="2026-09-16",
        ))
        new = qa_doc(record("QST-001", status="OPEN", blocking="YES"))
        err = qac.detect_resolution_regression(old, new)
        self.assertIsNone(err)

    def test_N4_wired_into_edit_payload(self):
        # Structurally-invalid "blanked but status kept" is caught by
        # PMO-QA-008 before the pipeline ever reaches the PMO-QA-009 check
        # (every non-OPEN status structurally requires a non-empty
        # Resolution - see test_N_resolution_blanked_denies_009 for that
        # unit-level case). The scenario PMO-QA-008 structurally cannot
        # catch - and that PMO-QA-009 exists specifically for - is the
        # record disappearing entirely. Exercise that through the real
        # Write payload path.
        root = self._root()
        old = qa_doc(record(
            "QST-001", status="RESOLVED", blocking="NO",
            resolution="Decided X.", authority="PM_EXPLICIT",
            evidence="2026-09-16",
        ) + record("QST-002", status="OPEN", blocking="NO"))
        qa_path = os.path.join(
            root, "docs", "pmo", "requirements", "questions-and-assumptions.md")
        _w(qa_path, old)
        new = qa_doc(record("QST-002", status="OPEN", blocking="NO"))
        payload = {
            "tool_name": "Write", "cwd": root,
            "tool_input": {"file_path": qa_path, "content": new},
        }
        d = guard.process(payload)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-009")

    # ------------------------------------------------------------------ #
    # PMO-QA-010 - canonical path
    # ------------------------------------------------------------------ #
    def test_O_non_canonical_path_denies_010(self):
        root = self._root()
        payload = {
            "tool_name": "Write", "cwd": root,
            "tool_input": {
                "file_path": os.path.join(
                    root, "docs/pmo/requirements/questions-and-assumptions-v2.md"),
                "content": GOOD_QA,
            },
        }
        d = guard.process(payload)
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "PMO-QA-010")

    def test_O2_canonical_path_helper(self):
        self.assertIsNone(qac.validate_canonical_qa_path(
            "docs/pmo/requirements/questions-and-assumptions.md"))
        self.assertIsNotNone(qac.validate_canonical_qa_path(
            "docs/pmo/requirements/questions-and-assumptions-final.md"))

    def test_O3_unrelated_file_ignored(self):
        root = self._root()
        payload = {
            "tool_name": "Write", "cwd": root,
            "tool_input": {"file_path": os.path.join(root, "README.md"),
                           "content": "hello"},
        }
        self.assertIsNone(guard.process(payload))

    # ------------------------------------------------------------------ #
    # Unit checks on qa_register_core
    # ------------------------------------------------------------------ #
    def test_units_blocking_open_records(self):
        recs = [
            {"status": "OPEN", "blocking": "YES"},
            {"status": "OPEN", "blocking": "NO"},
            {"status": "RESOLVED", "blocking": "YES"},
            {"status": "DEFERRED", "blocking": "NO"},
            {"status": "NON_BLOCKING", "blocking": "NO"},
        ]
        blockers = qac.blocking_open_records(recs)
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["status"], "OPEN")

    def test_units_find_duplicate_ids(self):
        blocks = [("QST-001", ""), ("QST-002", ""), ("QST-001", "")]
        self.assertEqual(qac.find_duplicate_ids(blocks), ["QST-001"])

    def test_units_parse_record_fields(self):
        text = qa_doc(record(
            "ASM-007", rtype="ASSUMPTION", status="RESOLVED", blocking="NO",
            resolution="Confirmed reusable.", authority="PM_EXPLICIT",
            evidence="2026-09-16", related="OPEN-001",
        ))
        blocks = qac.parse_qa_record_blocks(text)
        self.assertEqual(len(blocks), 1)
        rec = qac.parse_qa_record(*blocks[0])
        self.assertEqual(rec["id"], "ASM-007")
        self.assertEqual(rec["type"], "ASSUMPTION")
        self.assertEqual(rec["related_intent_item"], "OPEN-001")
        self.assertIsNone(qac.validate_record_structure(rec))


if __name__ == "__main__":
    unittest.main(verbosity=2)
