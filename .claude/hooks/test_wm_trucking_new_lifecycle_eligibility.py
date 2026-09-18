#!/usr/bin/env python3
"""Read-only compatibility check: is the real WM Trucking project eligible to
enter the NEW (Intent + Q&A) lifecycle under the redesigned framework, and -
as of the INITIAL_SPECS_CREATION framework correction - is it eligible for
INITIAL_SPECS_CREATION specifically?

This test reads the actual repository state (docs/pmo/intent/intent.md,
.pmo/approvals/intent-approval.yaml, .pmo/project-config.yaml, and - since a
separate, already-completed PMO_ENGINE run produced it -
docs/pmo/requirements/questions-and-assumptions.md) and asserts eligibility -
it never writes anything. It does not create or modify the Q&A register, and
it does not create docs/pmo/specs/specs.md or any docs/pmo/scope/ artifact;
Specs generation itself remains a separate, explicit run.

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

    def test_qa_register_exists_and_this_check_never_modifies_it(self):
        """The canonical Q&A register is a real, separately-produced PMO
        artifact (requirement-gathering's own governed deliverable) - this
        test only reads it, byte-for-byte, and never writes it."""
        qa_path = os.path.join(
            _REPO_ROOT, "docs", "pmo", "requirements",
            "questions-and-assumptions.md")
        self.assertTrue(
            os.path.isfile(qa_path),
            "WM Trucking's canonical Q&A register should already exist as "
            "a governed artifact for this eligibility check to be "
            "meaningful.")
        before = pathlib.Path(qa_path).read_bytes()
        qac.validate_new_path_readiness(_REPO_ROOT)
        after = pathlib.Path(qa_path).read_bytes()
        self.assertEqual(
            before, after,
            "This eligibility check is read-only and must never modify "
            "the real Q&A register.")

    def test_no_specs_created_by_this_check(self):
        specs_path = os.path.join(_REPO_ROOT, "docs", "pmo", "specs", "specs.md")
        self.assertFalse(
            os.path.exists(specs_path),
            "This eligibility check is read-only and must never create the "
            "real Specs artifact.")

    def test_initial_specs_creation_eligible(self):
        """The precise INITIAL_SPECS_CREATION classification: reuses the
        exact same `qa_register_core.validate_new_path_readiness` that both
        `specs-governance-guard.py` (PMO-SPEC-021/022/023) and the CR
        guard's new `validate_initial_specs_creation`
        (PMO-CR-GUARD-027/028/029/030) delegate to - so this assertion is
        the single source of truth for "is WM Trucking
        INITIAL_SPECS_CREATION_ELIGIBLE", not a third, divergent check."""
        result = qac.validate_new_path_readiness(_REPO_ROOT)
        self.assertIsNone(
            result,
            "WM Trucking should be classified INITIAL_SPECS_CREATION_"
            "ELIGIBLE (VALIDATED Intent + matching PM approval + a "
            "structurally valid Q&A register with zero OPEN+Blocking:YES "
            "records); got failure: {}".format(result),
        )

    def test_no_files_modified_by_this_entire_check(self):
        """Belt-and-suspenders: every artifact this file reads must be
        byte-identical before and after the full eligibility check runs."""
        paths = [
            os.path.join(_REPO_ROOT, "docs", "pmo", "intent", "intent.md"),
            os.path.join(_REPO_ROOT, ".pmo", "approvals",
                        "intent-approval.yaml"),
            os.path.join(_REPO_ROOT, ".pmo", "project-config.yaml"),
            os.path.join(_REPO_ROOT, "docs", "pmo", "requirements",
                        "questions-and-assumptions.md"),
        ]
        before = {p: pathlib.Path(p).read_bytes() for p in paths
                 if os.path.isfile(p)}
        qac.validate_new_path_readiness(_REPO_ROOT)
        qac.validate_prerequisite_intent(_REPO_ROOT)
        specs_guard.has_legacy_scope(_REPO_ROOT)
        for p, content in before.items():
            self.assertEqual(
                content, pathlib.Path(p).read_bytes(),
                "{} was modified by a read-only eligibility check.".format(p))


if __name__ == "__main__":
    unittest.main(verbosity=2)
