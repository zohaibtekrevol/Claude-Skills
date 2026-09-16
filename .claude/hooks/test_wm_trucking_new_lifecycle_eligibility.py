#!/usr/bin/env python3
"""Read-only compatibility check: is the real WM Trucking project eligible to
enter the NEW (Intent + Q&A) lifecycle under the redesigned framework?

This test reads the actual repository state (docs/pmo/intent/intent.md,
.pmo/approvals/intent-approval.yaml, .pmo/project-config.yaml) and asserts
eligibility - it never writes anything. It does not create
docs/pmo/requirements/questions-and-assumptions.md, docs/pmo/specs/specs.md,
or any docs/pmo/scope/ artifact; those remain PMO_ENGINE deliverables for a
separate, explicit run.

Standard-library `unittest`.
"""

import importlib.util
import os
import pathlib
import sys
import unittest

_HOOK_DIR = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _HOOK_DIR.parent.parent
_LIB_DIR = _HOOK_DIR.parent / "lib"
sys.path.insert(0, str(_LIB_DIR))

import qa_register_core as qac  # noqa: E402

_SPECS_GUARD_PATH = _HOOK_DIR / "specs-governance-guard.py"
_spec = importlib.util.spec_from_file_location(
    "specs_governance_guard_wm", _SPECS_GUARD_PATH)
specs_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(specs_guard)


class WmTruckingNewLifecycleEligibilityTests(unittest.TestCase):
    """Read-only. No file under the real repository is created, edited or
    deleted by any test in this file."""

    def test_repo_root_resolved(self):
        self.assertTrue(os.path.isdir(os.path.join(_REPO_ROOT, ".pmo")))
        self.assertTrue(os.path.isfile(
            os.path.join(_REPO_ROOT, "docs", "pmo", "intent", "intent.md")))

    def test_no_scope_artifact_exists_yet(self):
        scope_dir = os.path.join(_REPO_ROOT, "docs", "pmo", "scope")
        if os.path.isdir(scope_dir):
            self.assertEqual(
                [n for n in os.listdir(scope_dir) if n != ".gitkeep"], [],
                "WM Trucking must have no Scope artifact for this "
                "NEW-lifecycle eligibility check to be meaningful.")

    def test_new_lifecycle_path_selected(self):
        self.assertFalse(
            specs_guard.has_legacy_scope(_REPO_ROOT),
            "WM Trucking has no Scope artifact, so the framework must select "
            "the NEW (Intent + Q&A) lifecycle path for it, never LEGACY.")

    def test_intent_prerequisite_satisfied(self):
        """Intent v0.3 VALIDATED + matching PM approval + identity match -
        exactly PMO-QA-001 / the Q&A-register half of PMO-SPEC-021."""
        err = qac.validate_prerequisite_intent(_REPO_ROOT)
        self.assertIsNone(
            err,
            "WM Trucking's canonical Intent should already satisfy the "
            "NEW-lifecycle prerequisite (VALIDATED + matching PM approval + "
            "identity match); got: {}".format(err),
        )

    def test_no_qa_register_created_by_this_check(self):
        qa_path = os.path.join(
            _REPO_ROOT, "docs", "pmo", "requirements",
            "questions-and-assumptions.md")
        self.assertFalse(
            os.path.exists(qa_path),
            "This eligibility check is read-only and must never create the "
            "real Q&A register.")

    def test_no_specs_created_by_this_check(self):
        specs_path = os.path.join(_REPO_ROOT, "docs", "pmo", "specs", "specs.md")
        self.assertFalse(
            os.path.exists(specs_path),
            "This eligibility check is read-only and must never create the "
            "real Specs artifact.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
