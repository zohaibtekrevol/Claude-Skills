#!/usr/bin/env python3
"""Regression tests for .claude/scripts/intent-approval-recorder.py and its
shared core, .claude/lib/intent_approval_core.py.

Stdlib only. Run: python3 .claude/scripts/test_intent_approval_recorder.py
Exit 0 = all pass, 1 = at least one failure.

Uses temporary, synthetic project fixtures only - no real WM Trucking /
Smart Basket project artifact is ever created, read as a mutable fixture,
or modified.
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# Load the core module FIRST and register it in sys.modules under the exact
# name intent-approval-recorder.py imports ("intent_approval_core"). Without
# this, `from intent_approval_core import ...` inside the CLI would trigger
# Python's normal import machinery to load a SECOND, independent module
# instance from .claude/lib - and monkeypatching a function on *this* test's
# `core` reference would then silently miss the CLI's actual calls, which
# run against that other instance's globals. (Same pattern as
# test_change_request_incorporator.py.)
CORE_PATH = os.path.join(HERE, "..", "lib", "intent_approval_core.py")
_core_spec = importlib.util.spec_from_file_location("intent_approval_core", CORE_PATH)
core = importlib.util.module_from_spec(_core_spec)
sys.modules["intent_approval_core"] = core
_core_spec.loader.exec_module(core)

CLI_PATH = os.path.join(HERE, "intent-approval-recorder.py")
_cli_spec = importlib.util.spec_from_file_location("intent_approval_recorder", CLI_PATH)
cli = importlib.util.module_from_spec(_cli_spec)
_cli_spec.loader.exec_module(cli)

assert cli.finalize_transaction is core.finalize_transaction, (
    "cli and core did not share one module instance - monkeypatch-based "
    "tests would silently no-op")

# Also load the guard, the same way, so we can assert guard/CLI agreement
# on the SAME on-disk artifact (they must never disagree - see module
# docstrings).
GUARD_PATH = os.path.join(HERE, "..", "hooks", "intent-schema-guard.py")
_guard_spec = importlib.util.spec_from_file_location("intent_schema_guard", GUARD_PATH)
guard = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(guard)

_RESULTS = []


def check(name, ok, detail=""):
    _RESULTS.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + "  " + name + ("" if ok else "   :: " + str(detail)))


def code_of(result):
    d = (result or {}).get("decision")
    return d.get("code") if d else None


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

CONFIG_YAML = (
    'project:\n'
    '  id: "WM-TRUCKING"\n'
    '  name: "WM Trucking"\n'
    '  client: "WM Trucking"\n'
)

SECTIONS = (
    "1. Client Vision", "2. Business Problem", "3. Overall Client Goal",
    "4. Proposed Product Outcome", "5. Users, Actors and Systems",
    "6. High-Level Product Requirements", "7. Constraints",
    "8. Explicitly Out of Scope", "9. Dependencies", "10. Assumptions",
    "11. Open Questions", "12. Contradictions / Source Conflicts",
    "13. Risks Carried Into Requirement Gathering", "14. Source Register",
    "15. Intent Validation Summary", "16. Acceptance",
)


def build_intent(status="DRAFT", version="0.3", project_id="WM-TRUCKING",
                 next_stage="REQUIREMENT_GATHERING"):
    dc = "\n".join([
        "- **Project:** WM Trucking",
        "- **Client:** WM Trucking",
        "- **Project ID:** {}".format(project_id),
        "- **Date:** 2026-09-16",
        "- **Intent Version:** {}".format(version),
        "- **Status:** {}".format(status),
        "- **Repository:** bitbucket:devops-tekrevol/lets-explore-more-specs",
        "- **Source Count:** 1",
        "- **Next Stage:** {}".format(next_stage),
    ])
    parts = ["# WM Trucking - Project Intent", "", "## Document Control", "",
            dc, ""]
    for s in SECTIONS:
        parts.append("## " + s)
        if s.startswith("11."):
            parts.append(
                "| ID | Question | Owner | Blocking | Required Before |\n"
                "|---|---|---|---|---|\n"
                "| OPEN-001 | What stack? | PM | NO | Specification Generation |"
            )
        elif s.startswith("14."):
            parts.append(
                "| ID | File | Category | Authority |\n"
                "|---|---|---|---|\n"
                "| SRC-001 | `contract/SOW.docx` | Contract / SOW | AUTHORITATIVE |"
            )
        elif s.startswith("16."):
            parts.append("- **Decision:** PENDING\n"
                         "- **Decision Date:** _(not recorded)_\n"
                         "- **Approved By:** _(not recorded)_\n"
                         "- **Approval Evidence:** _(not recorded)_")
        else:
            parts.append("Body of section {}.".format(s))
        parts.append("")
    return "\n".join(parts)


class Project(object):
    """A temporary, synthetic project fixture - config + intent.md."""

    def __init__(self, status="DRAFT", version="0.3"):
        self.root = tempfile.mkdtemp(prefix="intent-approval-test-")
        os.makedirs(os.path.join(self.root, ".pmo"), exist_ok=True)
        os.makedirs(os.path.join(self.root, "docs", "pmo", "intent"), exist_ok=True)
        self._write(os.path.join(".pmo", "project-config.yaml"), CONFIG_YAML)
        self.intent_path = os.path.join(self.root, "docs", "pmo", "intent",
                                        "intent.md")
        self.write_intent(build_intent(status=status, version=version))

    def _write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def write_intent(self, text):
        self._write(os.path.join("docs", "pmo", "intent", "intent.md"), text)

    def read_intent(self):
        with open(self.intent_path, "r", encoding="utf-8") as fh:
            return fh.read()

    def approval_path(self):
        return os.path.join(self.root, ".pmo", "approvals", "intent-approval.yaml")

    def read_approval(self):
        try:
            with open(self.approval_path(), "r", encoding="utf-8") as fh:
                return fh.read()
        except FileNotFoundError:
            return None

    def marker_path(self):
        return os.path.join(self.root, ".pmo", "intent-approval-transaction.json")

    def read_marker(self):
        try:
            with open(self.marker_path(), "r", encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return None

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def guard_allows_validated_write(intent_text):
    """True iff intent-schema-guard.py's own process() would allow a Write
    of `intent_text` (used to assert guard/CLI agreement on finalize's
    output, per the module docstrings' 'cannot disagree by construction'
    claim)."""
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "docs/pmo/intent/intent.md",
                      "content": intent_text},
        "cwd": "/nonexistent-cwd-not-used",
    }
    # process_write_edit reads the "existing" on-disk file itself, so this
    # helper is only meaningful when called with cwd/root wired through the
    # real project fixture - see test_finalize_output_accepted_by_guard.
    return payload


# --------------------------------------------------------------------------- #
# 1 & 2 & 3 - begin fails closed, zero partial mutation
# --------------------------------------------------------------------------- #

def test_begin_validation():
    # (1) missing approved_by -> fails closed, no marker, no writes.
    p = Project()
    try:
        r = cli.run("begin", p.root, approved_by="", decision_date="2026-09-16")
        check("begin/missing_approved_by_fails_closed",
              r["status"] == "BLOCKED" and code_of(r) == "PMO-INTENT-APPROVAL-006",
              r)
        check("begin/missing_approved_by_no_marker", p.read_marker() is None)
        check("begin/missing_approved_by_no_approval_file", p.read_approval() is None)
    finally:
        p.cleanup()

    # malformed decision_date -> fails closed.
    p = Project()
    try:
        r = cli.run("begin", p.root, approved_by="Muhammad Faizan",
                    decision_date="16 Sep 2026")
        check("begin/bad_date_fails_closed",
              r["status"] == "BLOCKED" and code_of(r) == "PMO-INTENT-APPROVAL-006", r)
    finally:
        p.cleanup()

    # (2) structurally invalid current Intent (missing a required section)
    # -> fails closed at BEGIN, before any marker/approval file exists.
    p = Project()
    try:
        broken = p.read_intent().replace("## 9. Dependencies", "## 9. Renamed")
        p.write_intent(broken)
        r = cli.run("begin", p.root, approved_by="Muhammad Faizan",
                    decision_date="2026-09-16")
        check("begin/invalid_intent_content_fails_closed",
              r["status"] == "BLOCKED", r)
        check("begin/invalid_intent_content_no_marker", p.read_marker() is None)
        check("begin/invalid_intent_content_no_approval_file",
              p.read_approval() is None)
    finally:
        p.cleanup()

    # (3) version-mismatched pre-existing approval evidence is a conflict,
    # not silently overwritten, once discovered at validate/finalize time.
    p = Project(version="0.3")
    try:
        p._write(os.path.join(".pmo", "approvals", "intent-approval.yaml"), (
            'decision: "APPROVED"\n'
            'approval_source: "PM_EXPLICIT"\n'
            'artifact: "docs/pmo/intent/intent.md"\n'
            'version: "0.1"\n'
            'approved_by: "Someone Else"\n'
        ))
        b = cli.run("begin", p.root, approved_by="Muhammad Faizan",
                    decision_date="2026-09-16")
        check("begin/conflicting_prior_evidence_begin_ok", b["status"] == "ACTIVE", b)
        f = cli.run("finalize", p.root)
        check("begin/conflicting_prior_evidence_finalize_denied",
              f["status"] == "RECOVERY_REQUIRED"
              and code_of(f) == "PMO-INTENT-APPROVAL-011", f)
        # the conflicting evidence file was NOT overwritten.
        check("begin/conflicting_prior_evidence_not_overwritten",
              "Someone Else" in (p.read_approval() or ""))
    finally:
        p.cleanup()


# --------------------------------------------------------------------------- #
# 4 & 5 - a successful approval produces ONE consistent state, never one
# field without the other
# --------------------------------------------------------------------------- #

def test_successful_approval_is_consistent():
    p = Project(status="DRAFT", version="0.3")
    try:
        b = cli.run("begin", p.root, approved_by="Muhammad Faizan",
                    decision_date="2026-09-16", statement="I approve v0.3.")
        check("success/begin_active", b["status"] == "ACTIVE", b)

        f = cli.run("finalize", p.root)
        check("success/finalize_validated", f["status"] == "VALIDATED", f)
        check("success/marker_removed", p.read_marker() is None)

        final_text = p.read_intent()
        meta = core.parse_doc_control(final_text)
        check("success/status_is_validated",
              core._norm_status(meta.get("status")) == "VALIDATED")
        acc_decision, acc_date, acc_by, acc_evi = core._acceptance_fields(final_text)
        check("success/acceptance_decision_approved", acc_decision == "APPROVED")
        check("success/acceptance_approved_by", acc_by == "Muhammad Faizan")
        check("success/acceptance_has_evidence_ref", bool(acc_evi))

        approval_text = p.read_approval()
        check("success/approval_file_written", approval_text is not None)
        record = core.parse_simple_yaml(approval_text)
        check("success/approval_matches_version", record.get("version") == "0.3")
        check("success/approval_matches_approver",
              record.get("approved_by") == "Muhammad Faizan")

        # (5) there is no reachable field on disk reporting only one half.
        check("success/no_reachable_half_state",
              core._norm_status(meta.get("status")) == "VALIDATED"
              and acc_decision == "APPROVED")

        # every other section is untouched byte-for-byte.
        original = build_intent(status="DRAFT", version="0.3")
        for s in SECTIONS[:-1]:  # every section except 16. Acceptance
            check("success/section_preserved[{}]".format(s),
                  core.section_body(original, s) == core.section_body(final_text, s),
                  s)
    finally:
        p.cleanup()


def test_finalize_output_accepted_by_guard():
    """The guard and the CLI must agree: a Write of finalize's own output,
    replayed through the guard's process(), must be allowed (immutability
    aside - this checks PMO-INTENT-014 specifically, by asking the guard to
    evaluate the exact content finalize already committed)."""
    p = Project(status="DRAFT", version="0.3")
    try:
        cli.run("begin", p.root, approved_by="Muhammad Faizan",
               decision_date="2026-09-16")
        cli.run("finalize", p.root)
        final_text = p.read_intent()
        meta = guard.parse_doc_control(final_text)
        d = guard.validate_acceptance_consistency(final_text, meta, p.root)
        check("guard_agreement/acceptance_consistency_passes", d is None,
              getattr(d, "message", None))
    finally:
        p.cleanup()


# --------------------------------------------------------------------------- #
# 6 - simulated interruption is recoverable without duplicating the
# original PM approval
# --------------------------------------------------------------------------- #

def test_interrupted_transaction_recovers():
    p = Project(status="DRAFT", version="0.3")
    try:
        cli.run("begin", p.root, approved_by="Muhammad Faizan",
               decision_date="2026-09-16", statement="Approved.")

        # Simulate the exact historical defect scenario: the approval
        # evidence write succeeded, but the process was interrupted before
        # the Intent rewrite happened.
        marker = p.read_marker()
        decision, plan = core._rederive_plan_from_marker(p.root, marker)
        assert decision is None, decision
        core.write_text(p.approval_path(), plan["candidate_approval_yaml"])

        # Intent is still DRAFT on disk at this point - never a moment
        # where Status says VALIDATED without a matching Acceptance.
        pre_status = core._norm_status(
            core.parse_doc_control(p.read_intent()).get("status"))
        check("recover/still_draft_before_resume", pre_status == "DRAFT")

        v = cli.run("validate", p.root)
        check("recover/validate_detects_resumable_state", v["status"] == "PASS", v)

        f = cli.run("finalize", p.root)
        check("recover/finalize_completes", f["status"] == "VALIDATED", f)

        approval_text = p.read_approval()
        record = core.parse_simple_yaml(approval_text)
        check("recover/approval_not_duplicated_or_altered",
              record.get("approved_by") == "Muhammad Faizan"
              and record.get("version") == "0.3")
    finally:
        p.cleanup()


def test_interrupted_after_intent_write_failure_is_recoverable():
    """Simulate the intent.md write itself failing after the approval
    evidence was already correctly written - finalize must report
    RECOVERY_REQUIRED (never a false clean success), and re-running it must
    complete without re-writing (or corrupting) the approval evidence."""
    p = Project(status="DRAFT", version="0.3")
    try:
        cli.run("begin", p.root, approved_by="Muhammad Faizan",
               decision_date="2026-09-16")

        original_write_text = core.write_text
        calls = {"n": 0}

        def flaky_write_text(path, text):
            calls["n"] += 1
            if path == p.intent_path and calls["n"] <= 2:
                raise OSError("simulated disk failure")
            return original_write_text(path, text)

        core.write_text = flaky_write_text
        try:
            f1 = cli.run("finalize", p.root)
        finally:
            core.write_text = original_write_text

        check("recover2/first_finalize_reports_recovery_required",
              f1["status"] == "RECOVERY_REQUIRED"
              and code_of(f1) == "PMO-INTENT-APPROVAL-013", f1)
        check("recover2/approval_evidence_survived_the_failure",
              p.read_approval() is not None)
        check("recover2/intent_not_falsely_validated",
              core._norm_status(core.parse_doc_control(p.read_intent()).get("status"))
              == "DRAFT")

        approval_before_retry = p.read_approval()
        f2 = cli.run("finalize", p.root)
        check("recover2/retry_completes", f2["status"] == "VALIDATED", f2)
        check("recover2/approval_evidence_unchanged_by_retry",
              p.read_approval() == approval_before_retry)
    finally:
        p.cleanup()


# --------------------------------------------------------------------------- #
# 7 & 12 (idempotency) - re-running against an already fully consistent
# VALIDATED Intent is a safe no-op
# --------------------------------------------------------------------------- #

def test_idempotent_on_already_consistent_validated_intent():
    p = Project(status="DRAFT", version="0.3")
    try:
        cli.run("begin", p.root, approved_by="Muhammad Faizan",
               decision_date="2026-09-16")
        cli.run("finalize", p.root)
        after_first = p.read_intent()
        approval_after_first = p.read_approval()

        b2 = cli.run("begin", p.root, approved_by="Muhammad Faizan",
                     decision_date="2026-09-16")
        check("idempotent/begin_reports_no_change",
              b2["status"] == "NO_CHANGE"
              and code_of(b2) == "PMO-INTENT-APPROVAL-003", b2)
        check("idempotent/no_marker_created_on_no_change", p.read_marker() is None)
        check("idempotent/intent_untouched", p.read_intent() == after_first)
        check("idempotent/approval_untouched", p.read_approval() == approval_after_first)
    finally:
        p.cleanup()


# --------------------------------------------------------------------------- #
# 8 - a Write/Edit setting VALIDATED while Acceptance is stale/absent is
# denied with PMO-INTENT-014 (delegated to test_intent_schema_guard.py's
# own dedicated suite; re-asserted here at the guard/CLI boundary).
# --------------------------------------------------------------------------- #

def test_guard_denies_stale_acceptance_at_validated_transition():
    p = Project(status="DRAFT", version="0.3")
    try:
        # A valid, matching approval record exists (so PMO-INTENT-011 - a
        # different, earlier check - passes), but Section 16 in the
        # candidate write is still the original pre-approval placeholder -
        # PMO-INTENT-014 must be the one that catches this.
        p._write(os.path.join(".pmo", "approvals", "intent-approval.yaml"), (
            'decision: "APPROVED"\n'
            'approval_source: "PM_EXPLICIT"\n'
            'artifact: "docs/pmo/intent/intent.md"\n'
            'version: "0.3"\n'
            'approved_by: "Muhammad Faizan"\n'
        ))
        stale = build_intent(status="VALIDATED", version="0.3")  # Section 16 still PENDING
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": p.intent_path, "content": stale},
            "cwd": p.root,
        }
        decision = guard.process(payload)
        check("guard_boundary/stale_acceptance_denied_014",
              decision is not None and decision.code == "PMO-INTENT-014",
              getattr(decision, "message", decision))
    finally:
        p.cleanup()


# --------------------------------------------------------------------------- #
# 9 - existing PMO-INTENT-009 immutability is unchanged for ordinary
# post-validation editing (the CLI's own direct writes are a SEPARATE,
# equally strict path - not a general bypass of the hook)
# --------------------------------------------------------------------------- #

def test_pmo_intent_009_unchanged_for_ordinary_edits():
    p = Project(status="DRAFT", version="0.3")
    try:
        cli.run("begin", p.root, approved_by="Muhammad Faizan",
               decision_date="2026-09-16")
        cli.run("finalize", p.root)

        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": p.intent_path,
                          "old_string": "Body of section 9. Dependencies.",
                          "new_string": "changed"},
            "cwd": p.root,
        }
        decision = guard.process(payload)
        check("immutability/ordinary_edit_still_blocked",
              decision is not None and decision.code == "PMO-INTENT-009",
              getattr(decision, "message", decision))
    finally:
        p.cleanup()


# --------------------------------------------------------------------------- #
# 10 - existing PMO-INTENT-011 behaviour is preserved
# --------------------------------------------------------------------------- #

def test_pmo_intent_011_unchanged():
    p = Project(status="DRAFT", version="0.3")
    try:
        validated = build_intent(status="VALIDATED", version="0.3")
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": p.intent_path, "content": validated},
            "cwd": p.root,
        }
        decision = guard.process(payload)
        # No approval record exists at all yet - PMO-INTENT-011 must still
        # be the reported reason (it runs before the new PMO-INTENT-014
        # check in process_write_edit).
        check("pm_approval/011_still_enforced",
              decision is not None and decision.code == "PMO-INTENT-011",
              getattr(decision, "message", decision))
    finally:
        p.cleanup()


# --------------------------------------------------------------------------- #
# Marker contract: no silent overwrite, no cross-project reuse
# --------------------------------------------------------------------------- #

def test_marker_no_silent_overwrite_and_no_cross_project_reuse():
    p = Project(status="DRAFT", version="0.3")
    try:
        b1 = cli.run("begin", p.root, approved_by="Muhammad Faizan",
                     decision_date="2026-09-16")
        check("marker/first_begin_active", b1["status"] == "ACTIVE", b1)

        b2 = cli.run("begin", p.root, approved_by="Someone Else",
                     decision_date="2026-09-16")
        check("marker/second_begin_refused",
              b2["status"] == "BLOCKED"
              and code_of(b2) == "PMO-INTENT-APPROVAL-007", b2)
        check("marker/original_marker_untouched",
              p.read_marker()["approved_by"] == "Muhammad Faizan")
    finally:
        p.cleanup()

    # cross-project reuse: a marker whose project_id does not match the
    # CURRENT project-config.yaml must be rejected, never silently adopted.
    p2 = Project(status="DRAFT", version="0.3")
    try:
        cli.run("begin", p2.root, approved_by="Muhammad Faizan",
               decision_date="2026-09-16")
        marker = p2.read_marker()
        marker["project_id"] = "SOME-OTHER-PROJECT"
        core.write_text(p2.marker_path(), json.dumps(marker, indent=2))
        s = cli.run("status", p2.root)
        check("marker/wrong_project_detected", s["status"] == "INVALID_MARKER"
              and code_of(s) == "PMO-INTENT-APPROVAL-009", s)
    finally:
        p2.cleanup()


# --------------------------------------------------------------------------- #
# Baseline drift: content approved must be the content on disk
# --------------------------------------------------------------------------- #

def test_baseline_drift_detected():
    p = Project(status="DRAFT", version="0.3")
    try:
        cli.run("begin", p.root, approved_by="Muhammad Faizan",
               decision_date="2026-09-16")
        drifted = p.read_intent().replace(
            "Body of section 1. Client Vision.", "Materially different vision.")
        p.write_intent(drifted)
        f = cli.run("finalize", p.root)
        check("drift/finalize_denied", f["status"] == "RECOVERY_REQUIRED"
              and code_of(f) == "PMO-INTENT-APPROVAL-011", f)
        check("drift/drifted_content_preserved_not_overwritten",
              "Materially different vision." in p.read_intent())
    finally:
        p.cleanup()


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def main():
    test_begin_validation()
    test_successful_approval_is_consistent()
    test_finalize_output_accepted_by_guard()
    test_interrupted_transaction_recovers()
    test_interrupted_after_intent_write_failure_is_recoverable()
    test_idempotent_on_already_consistent_validated_intent()
    test_guard_denies_stale_acceptance_at_validated_transition()
    test_pmo_intent_009_unchanged_for_ordinary_edits()
    test_pmo_intent_011_unchanged()
    test_marker_no_silent_overwrite_and_no_cross_project_reuse()
    test_baseline_drift_detected()

    total = len(_RESULTS)
    failed = [n for n, ok in _RESULTS if not ok]
    print("\n{}/{} passed".format(total - len(failed), total))
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
