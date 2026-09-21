#!/usr/bin/env python3
"""Regression tests for PRE_BASELINE_SCHEMA_MIGRATION
(.claude/scripts/specs-schema-migration.py + specs_schema_migration_core.py).

Reuses the STRUCTURAL_REPAIR test fixtures (same real guard, same project
identity) so both suites exercise the same authoritative validator. Every test
runs against a synthetic temporary project; the real project is only ever read
(see the WM assessment test) and is asserted unchanged.
"""

import hashlib
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import test_specs_structural_repair as T  # noqa: E402
import specs_schema_migration_core as mig  # noqa: E402
import specs_structural_repair_core as src  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "specs_schema_migration_cli", os.path.join(HERE, "specs-schema-migration.py"))
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

check = T.check
_RESULTS = T._RESULTS
code_of = T.code_of
TOK = src.NONCANONICAL_INITIAL_TOKEN
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

NFR_CANON = '''
### NFR-001 - Order confirmation latency

- **ID:** NFR-001
- **Title:** Order confirmation latency
- **Category:** Performance
- **Requirement:** Order confirmation is qualitative until a target is confirmed.
- **Source Requirement:** INT-REQ-001
- **Introduced In:** 0.1
- **Last Modified In:** 0.1
- **Change Source:** INITIAL_INTENT
- **Acceptance Criteria:** Qualitative only; no numeric threshold is invented.
- **Status:** ACTIVE
'''


def canonical_specs(with_nfr=False, **kw):
    text = T.build_specs(include_validation_summary=True, **kw)
    if with_nfr:
        text = text.replace("## Non-Functional Requirements\n",
                            "## Non-Functional Requirements\n" + NFR_CANON, 1)
    return text


def to_legacy(text, token=None):
    """Render a canonical fixture in the OLD generator layout: heading-only
    ID/Title, combined inline field lines."""
    text = re.sub(r"(?m)^- \*\*ID:\*\* .*\n- \*\*Title:\*\* .*\n", "", text)
    text = re.sub(r"(?m)^(- \*\*Module:\*\* .*)\n- (\*\*Actor\(s\):\*\* .*)$", r"\1 | \2", text)
    text = re.sub(r"(?m)^(- \*\*Introduced In:\*\* .*)\n- (\*\*Last Modified In:\*\* .*)\n- (\*\*Change Source:\*\* .*)$",
                  r"\1 | \2 | \3", text)
    if token:
        text = text.replace("**Change Source:** INITIAL_INTENT", "**Change Source:** " + token)
    return text


def legacy_root(with_nfr=False, token=None, **kw):
    return T.mkroot(specs=to_legacy(canonical_specs(with_nfr=with_nfr), token), **kw)


def spath(root):
    return T._specs_path(root)


def mpath(root):
    return os.path.join(root, ".pmo", "specs-schema-migration-transaction.json")


def rd(p):
    return open(p, "rb").read()


def test_1_fixture_is_legacy_and_fails_010_and_canonical_passes():
    root = legacy_root()
    try:
        d = src.specs_guard.full_spec_validation(root)
        check("1/legacy_fails_010", d is not None and d.code == "PMO-SPEC-010", d)
    finally:
        T._cleanup(root)
    r2 = T.mkroot(specs=canonical_specs())
    try:
        check("1/canonical_passes", src.specs_guard.full_spec_validation(r2) is None)
    finally:
        T._cleanup(r2)


def test_2_positive_migration_end_to_end():
    root = legacy_root(with_nfr=True)
    legacy = open(spath(root)).read()
    try:
        b = cli.cmd_begin(root, "migrate legacy layout")
        check("2/begin_active", b["status"] == "ACTIVE", b)
        check("2/plan_counts", b["plan"]["plan"]["layout"]["fr_blocks"] == 1
              and b["plan"]["plan"]["layout"]["nfr_blocks"] == 1, b.get("plan"))
        f = cli.cmd_finalize(root)
        check("2/finalize_migrated", f["status"] == "MIGRATED", f)
        after = open(spath(root)).read()
        check("2/marker_removed", not os.path.exists(mpath(root)))
        check("2/full_validation_passes", src.specs_guard.full_spec_validation(root) is None)
        check("2/matches_canonical_fixture", after == canonical_specs(with_nfr=True))
        check("2/fr_ids_and_count_identical",
              re.findall(r"(?m)^###\s+((?:FR|NFR)-\d+)", after)
              == re.findall(r"(?m)^###\s+((?:FR|NFR)-\d+)", legacy))
        check("2/values_identical",
              mig.semantic_records(legacy) == mig.semantic_records(after))
        check("2/outside_blocks_identical", mig.outside_blocks(legacy) == mig.outside_blocks(after))
        check("2/nfr_migrated", "- **ID:** NFR-001\n- **Title:** Order confirmation latency" in after)
        check("2/exec_false_no_approval",
              "**Execution Authorized:** false" in after and not os.path.exists(
                  os.path.join(root, ".pmo", "approvals", "specs-approval.yaml")))
        check("2/no_cr_no_feedback", not os.path.exists(os.path.join(root, "docs", "pmo", "cr"))
              and not os.path.exists(os.path.join(root, "docs", "pmo", "feedback")))
        check("2/version_unchanged", "**Spec Version:** 0.1" in after)
    finally:
        T._cleanup(root)


def test_3_provenance_normalization_new_lifecycle_only():
    root = legacy_root(token=TOK)
    try:
        b = cli.cmd_begin(root, "migrate + provenance")
        check("3/plan_has_provenance", src.REPAIR_CLASS_PROVENANCE in b["plan"]["plan"]["classes"], b)
        f = cli.cmd_finalize(root)
        after = open(spath(root)).read()
        check("3/finalized", f["status"] == "MIGRATED", f)
        check("3/token_normalized_to_initial_intent",
              TOK not in after and "**Change Source:** INITIAL_INTENT" in after)
        check("3/valid", src.specs_guard.full_spec_validation(root) is None)
    finally:
        T._cleanup(root)
    # legacy INITIAL_SCOPE is preserved untouched by the layout migration
    text = to_legacy(canonical_specs()).replace("**Change Source:** INITIAL_INTENT",
                                                "**Change Source:** INITIAL_SCOPE")
    lay, _ = mig.migrate_layout(text)
    check("3/initial_scope_preserved", "**Change Source:** INITIAL_SCOPE" in lay
          and TOK not in lay and mig.layout_equivalent(text, lay)[0])
    # token present but NEW lifecycle not proven (legacy Scope governs) -> blocked
    root = legacy_root(token=TOK)
    try:
        T._w(os.path.join(root, "docs", "pmo", "scope", "scope-v0.1.md"), "# Scope\n\n- **Scope Version:** 0.1\n")
        r = cli.cmd_begin(root, "x")
        check("3/scope_governed_provenance_blocked",
              r["status"] == "BLOCKED" and not os.path.exists(mpath(root)), r)
    finally:
        T._cleanup(root)
    # prose is never touched
    prose = to_legacy(canonical_specs(), TOK).replace(
        "## Open Questions", "The token {} appears in prose.\n\n## Open Questions".format(TOK), 1)
    root = T.mkroot(specs=prose)
    try:
        cli.cmd_begin(root, "x")
        f = cli.cmd_finalize(root)
        check("3/prose_untouched", f["status"] == "MIGRATED"
              and "The token {} appears in prose.".format(TOK) in open(spath(root)).read(), f)
    finally:
        T._cleanup(root)


def test_4_negative_gates():
    for name, kw, patch in (
        ("exec_true", {}, ("**Execution Authorized:** false", "**Execution Authorized:** true")),
        ("approved_status", {}, ("**Spec Status:** PROVISIONAL", "**Spec Status:** APPROVED")),
    ):
        text = to_legacy(canonical_specs()).replace(*patch)
        root = T.mkroot(specs=text)
        try:
            r = cli.cmd_begin(root, "x")
            check("4/{}_blocked".format(name), r["status"] == "BLOCKED"
                  and code_of(r) == "PMO-SCHEMA-MIG-003" and not os.path.exists(mpath(root)), r)
        finally:
            T._cleanup(root)
    root = legacy_root(specs_approval=T.matching_specs_approval())
    try:
        r = cli.cmd_begin(root, "x")
        check("4/existing_approval_blocked", code_of(r) == "PMO-SCHEMA-MIG-003", r)
    finally:
        T._cleanup(root)
    root = legacy_root(cr_marker=json.dumps({
        "transaction_type": "CHANGE_REQUEST_MANAGEMENT", "transaction_id": "CRTX-1",
        "project_id": "SMART-BASKET", "cr_id": "CR-001", "operation": "STATE_TRANSITION",
        "started_at": "2026-09-19T00:00:00Z", "status": "ACTIVE"}))
    try:
        r = cli.cmd_begin(root, "x")
        check("4/concurrent_cr_blocked", r["status"] == "BLOCKED" and not os.path.exists(mpath(root)), r)
    finally:
        T._cleanup(root)
    root = T.mkroot(specs=canonical_specs())
    try:
        r = cli.cmd_begin(root, "x")
        check("4/already_valid_nothing_to_migrate", code_of(r) == "PMO-SCHEMA-MIG-005", r)
    finally:
        T._cleanup(root)
    root = legacy_root()
    try:
        r = cli.cmd_begin(root, "  ")
        check("4/empty_reason_blocked", code_of(r) == "PMO-SCHEMA-MIG-001", r)
    finally:
        T._cleanup(root)


def test_5_ambiguous_or_unsupported_layout_fails_closed():
    base = to_legacy(canonical_specs())
    cases = {
        "unknown_label_in_combined_line": base.replace(
            "| **Actor(s):**", "| **Mystery:** x | **Actor(s):**", 1),
        "id_disagrees_with_heading": base.replace(
            "### FR-001 - Customer places an online order\n",
            "### FR-001 - Customer places an online order\n- **ID:** FR-009\n- **Title:** Customer places an online order\n", 1),
        "only_id_no_title": base.replace(
            "### FR-001 - Customer places an online order\n",
            "### FR-001 - Customer places an online order\n- **ID:** FR-001\n", 1),
        "duplicate_label_combined": base.replace(
            "**Last Modified In:** 0.1", "**Introduced In:** 0.1", 1),
        "empty_segment_value": base.replace("**Actor(s):** B2C customer", "**Actor(s):** ", 1),
    }
    for name, text in cases.items():
        root = T.mkroot(specs=text)
        try:
            before = rd(spath(root))
            r = cli.cmd_begin(root, "x")
            check("5/{}_blocked".format(name), r["status"] == "BLOCKED"
                  and not os.path.exists(mpath(root)), r)
            check("5/{}_specs_untouched".format(name), rd(spath(root)) == before)
        finally:
            T._cleanup(root)


def test_6_equivalence_detects_every_semantic_change():
    legacy = to_legacy(canonical_specs(with_nfr=True))
    good, _ = mig.migrate_layout(legacy)
    check("6/good_layout_equivalent", mig.layout_equivalent(legacy, good)[0])

    def rej(name, after):
        ok, why = mig.layout_equivalent(legacy, after)
        check("6/reject_" + name, not ok, why)

    rej("requirement_text", good.replace("confirm a cart", "confirm a basket"))
    rej("requirement_added", good.replace("## Non-Functional Requirements",
        "### FR-002 - Added\n\n- **ID:** FR-002\n- **Title:** Added\n\n## Non-Functional Requirements", 1))
    rej("requirement_removed", good.replace("### NFR-001 - Order confirmation latency", "", 1)
        .replace("- **ID:** NFR-001\n", "", 1))
    rej("requirement_id", good.replace("### FR-001 - Customer", "### FR-002 - Customer", 1))
    rej("title", good.replace("### FR-001 - Customer places an online order",
                              "### FR-001 - Customer places orders", 1))
    rej("business_rule_row", good.replace("| Order | order_reference | Yes |", "| Order | order_ref | Yes |"))
    rej("nfr_meaning", good.replace("qualitative until a target", "under 200 ms until a target"))
    rej("source_semantics", good.replace("**Source Requirement:** INT-REQ-001",
                                          "**Source Requirement:** INT-REQ-002", 1))
    rej("intent_mapping", good.replace("| INT-REQ-001 | FR-001 | COVERED |", "| INT-REQ-001 | FR-001 | DEFERRED |"))
    rej("acceptance_criteria", good.replace("Then an order is created", "Then nothing happens"))
    rej("deferred_resolved", good.replace("**Status:** ACTIVE", "**Status:** DEFERRED", 1))
    rej("version_line", good.replace("**Spec Version:** 0.1", "**Spec Version:** 0.2"))
    rej("arbitrary_provenance", good.replace("**Change Source:** INITIAL_INTENT", "**Change Source:** SOMETHING", 1))
    rej("field_order_changed", good.replace(
        "- **Module:**", "- **Priority:** MUST\n- **Module:**", 1))
    check("6/final_equivalence_allows_only_approved_token",
          mig.final_equivalence(to_legacy(canonical_specs(), TOK), canonical_specs())
          and not mig.final_equivalence(to_legacy(canonical_specs(), "INITIAL_SCOPE"), canonical_specs()))


def test_7_candidate_failing_validation_writes_nothing_and_is_abortable():
    # legacy layout AND a second, non-layout defect (unsupported status)
    text = to_legacy(canonical_specs()).replace("**Status:** ACTIVE", "**Status:** BOGUS", 1)
    root = T.mkroot(specs=text)
    try:
        before = rd(spath(root))
        r = cli.cmd_begin(root, "x")
        check("7/begin_blocked_by_candidate_validation", code_of(r) == "PMO-SCHEMA-MIG-011", r)
        check("7/nothing_written", rd(spath(root)) == before and not os.path.exists(mpath(root)))
    finally:
        T._cleanup(root)
    # a transaction whose finalize fails closed can be governedly aborted
    root = legacy_root()
    try:
        b = cli.cmd_begin(root, "x")
        check("7/begin_active", b["status"] == "ACTIVE", b)
        # break the artifact AFTER begin, with an unrepairable defect that
        # keeps the hash mismatch out of the picture by restoring nothing:
        # instead simulate a failing finalize via a moved target.
        with open(spath(root), "a") as fh:
            fh.write("\nedit\n")
        f = cli.cmd_finalize(root)
        check("7/finalize_fails_closed", f["status"] == "RECOVERY_REQUIRED", f)
        after_edit = rd(spath(root))
        a = cli.cmd_abort(root, "x")
        check("7/moved_target_abort_blocked", code_of(a) == "PMO-SPEC-REPAIR-022", a)
        # restore the original bytes -> marker verifiably matches again -> abort ok
        text = to_legacy(canonical_specs())
        with open(spath(root), "w") as fh:
            fh.write(text)
        a = cli.cmd_abort(root, "migration cancelled")
        check("7/abort_ok_after_hash_matches", a["status"] == "ABORTED", a)
        check("7/marker_removed", not os.path.exists(mpath(root)))
        check("7/specs_byte_identical_after_abort", rd(spath(root)) == text.encode())
        check("7/no_approval_no_cr", not os.path.exists(
            os.path.join(root, ".pmo", "approvals", "specs-approval.yaml"))
            and not os.path.exists(os.path.join(root, ".pmo", "change-request-transaction.json")))
    finally:
        T._cleanup(root)


def test_8_finalized_migration_cannot_be_aborted_and_markers_fail_closed():
    root = legacy_root()
    try:
        cli.cmd_begin(root, "x")
        marker_text = open(mpath(root)).read()
        f = cli.cmd_finalize(root)
        check("8/finalized", f["status"] == "MIGRATED", f)
        check("8/no_transaction_to_abort", cli.cmd_abort(root, "x")["status"] == "NO_TRANSACTION")
        T._w(mpath(root), marker_text)  # stale marker
        after = rd(spath(root))
        a = cli.cmd_abort(root, "x")
        check("8/stale_marker_abort_blocked", code_of(a) == "PMO-SPEC-REPAIR-022", a)
        check("8/specs_untouched", rd(spath(root)) == after and os.path.exists(mpath(root)))
        T._w(mpath(root), "{nope")
        check("8/invalid_marker_blocked", code_of(cli.cmd_abort(root, "x")) == "PMO-SCHEMA-MIG-021")
        T._w(mpath(root), json.dumps({"operation": "STRUCTURAL_REPAIR"}))
        check("8/foreign_marker_blocked", code_of(cli.cmd_abort(root, "x")) == "PMO-SCHEMA-MIG-021")
    finally:
        T._cleanup(root)


def test_9_finalize_rejects_moved_target_and_never_partially_writes():
    root = legacy_root()
    try:
        cli.cmd_begin(root, "x")
        with open(spath(root), "a") as fh:
            fh.write("\n<!-- edited -->\n")
        edited = rd(spath(root))
        f = cli.cmd_finalize(root)
        check("9/moved_target_fail_closed", f["status"] == "RECOVERY_REQUIRED", f)
        check("9/specs_unchanged", rd(spath(root)) == edited)
    finally:
        T._cleanup(root)


def test_10_structural_repair_compatibility():
    # a migrated artifact remains fully governable by STRUCTURAL_REPAIR
    root = legacy_root()
    try:
        cli.cmd_begin(root, "x")
        cli.cmd_finalize(root)
        text = open(spath(root)).read().replace("\n## Validation Summary\n\nAll active Intent requirements are "
                                                 "represented.\n", "")
        T._w(spath(root), text)
        b = T.cli.cmd_begin(root, "restore summary")
        check("10/structural_repair_still_works", b["status"] == "ACTIVE"
              and b["plan"]["repair_classes"] == [src.REPAIR_CLASS_MISSING_SECTION], b)
        f = T.cli.cmd_finalize(root)
        check("10/repair_finalized_and_valid", f["status"] == "REPAIRED"
              and src.specs_guard.full_spec_validation(root) is None, f)
    finally:
        T._cleanup(root)
    # only one Specs transaction at a time
    root = legacy_root()
    try:
        cli.cmd_begin(root, "x")
        # repair-eligible artifact (missing summary) + an open migration marker
        T._w(spath(root), canonical_specs().replace(
            "\n## Validation Summary\n\nAll active Intent requirements are represented.\n", ""))
        r = T.cli.cmd_begin(root, "x")
        check("10/repair_blocked_while_migration_open", r["status"] == "BLOCKED"
              and code_of(r) == "PMO-SPEC-REPAIR-009", r)
    finally:
        T._cleanup(root)
    root = legacy_root()
    try:
        T._w(os.path.join(root, ".pmo", "specs-structural-repair-transaction.json"), "{}")
        r = cli.cmd_begin(root, "x")
        check("10/migration_blocked_while_repair_open", r["status"] == "BLOCKED", r)
    finally:
        T._cleanup(root)


def test_11_migration_combined_with_missing_section_and_metadata():
    text = to_legacy(canonical_specs(), TOK)
    text = text.replace("\n## Validation Summary\n\nAll active Intent requirements are represented.\n", "")
    text = text.replace("- **Generated From:** docs/pmo/requirements/questions-and-assumptions.md\n",
                        "- **Generated From:** docs/pmo/requirements/questions-and-assumptions.md (+ intent v1.0)\n")
    root = T.mkroot(specs=text)
    try:
        b = cli.cmd_begin(root, "all primitives")
        check("11/classes", b["plan"]["plan"]["classes"] == [
            "LAYOUT_CANONICALIZATION", src.REPAIR_CLASS_PROVENANCE,
            src.REPAIR_CLASS_METADATA, src.REPAIR_CLASS_MISSING_SECTION], b)
        f = cli.cmd_finalize(root)
        after = open(spath(root)).read()
        check("11/finalized_valid", f["status"] == "MIGRATED"
              and src.specs_guard.full_spec_validation(root) is None, f)
        check("11/generated_from_canonical",
              "- **Generated From:** docs/pmo/requirements/questions-and-assumptions.md\n" in after)
        check("11/summary_added_token_gone", "Validation Summary" in after and TOK not in after)
    finally:
        T._cleanup(root)


def test_12_generator_contract_single_canonical_layout():
    skill = open(os.path.join(REPO_ROOT, ".claude", "skills", "spec-generation", "SKILL.md"),
                 encoding="utf-8").read()
    flat = " ".join(skill.split()).lower()
    check("12/skill_requires_one_field_per_line",
          "one field per line" in flat and "never combine fields on one line" in flat)
    check("12/skill_requires_standalone_id_title",
          "standalone `id` and `title` fields" in flat)
    check("12/skill_names_migration_for_legacy_layout", "PRE_BASELINE_SCHEMA_MIGRATION" in skill)


def test_13_real_project_read_only_assessment_and_untouched():
    real = os.path.join(REPO_ROOT, "docs", "pmo", "specs", "specs.md")
    if not os.path.exists(real):
        check("13/skipped_no_real_project", True)
        return
    before = hashlib.sha256(rd(real)).hexdigest()
    text = open(real, encoding="utf-8").read()
    lay, stats = mig.migrate_layout(text)
    check("13/real_layout_migration_is_equivalent", mig.layout_equivalent(text, lay)[0])
    check("13/real_blocks_counted", stats["blocks"] == stats["fr_blocks"] + stats["nfr_blocks"])
    plan, dec = mig.run_begin_preconditions(REPO_ROOT, "read-only assessment")
    # the assessment is deterministic and never writes; real specs unchanged
    check("13/real_assessment_never_writes", hashlib.sha256(rd(real)).hexdigest() == before)
    check("13/real_no_marker_created", not os.path.exists(
        os.path.join(REPO_ROOT, ".pmo", "specs-schema-migration-transaction.json")))
    check("13/real_result_is_decisive", (plan is None) != (dec is None))


def main():
    for fn in (
        test_1_fixture_is_legacy_and_fails_010_and_canonical_passes,
        test_2_positive_migration_end_to_end,
        test_3_provenance_normalization_new_lifecycle_only,
        test_4_negative_gates,
        test_5_ambiguous_or_unsupported_layout_fails_closed,
        test_6_equivalence_detects_every_semantic_change,
        test_7_candidate_failing_validation_writes_nothing_and_is_abortable,
        test_8_finalized_migration_cannot_be_aborted_and_markers_fail_closed,
        test_9_finalize_rejects_moved_target_and_never_partially_writes,
        test_10_structural_repair_compatibility,
        test_11_migration_combined_with_missing_section_and_metadata,
        test_12_generator_contract_single_canonical_layout,
        test_13_real_project_read_only_assessment_and_untouched,
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
