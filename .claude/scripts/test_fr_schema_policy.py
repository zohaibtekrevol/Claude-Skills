#!/usr/bin/env python3
"""Regression tests for the applicability-aware Functional Requirement schema
policy (PMO-SPEC-010: CORE_REQUIRED / GOVERNANCE_DERIVED / CONDITIONALLY_REQUIRED
/ OPTIONAL, applicability states DEFINED / NOT_APPLICABLE / NOT_SPECIFIED /
PENDING_DECISION, multi-line Acceptance Criteria).

Fixtures are synthetic temporary projects (shared with the STRUCTURAL_REPAIR
suite, so the same real guard/validators run); the real project is only read
in memory and asserted unchanged.
"""

import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import test_specs_structural_repair as T  # noqa: E402
import test_specs_schema_migration as M  # noqa: E402
import specs_schema_migration_core as mig  # noqa: E402
import specs_structural_repair_core as src  # noqa: E402

guard = src.specs_guard
check = T.check
_RESULTS = T._RESULTS
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

QA_WITH_PENDING = T.QA_ALL_RESOLVED + (
    "#### QST-002 - Refund window\n\n"
    "- **ID:** QST-002\n"
    "- **Type:** QUESTION\n"
    "- **Statement:** How long is the refund window?\n"
    "- **Why Resolution Is Required:** Drives cancellation behaviour.\n"
    "- **Source / Evidence:** SRC-001\n"
    "- **Related Intent Item:** \n"
    "- **Owner:** PM\n"
    "- **Status:** OPEN\n"
    "- **Blocking:** NO\n"
    "- **Resolution:** \n"
    "- **Resolution Authority:** \n"
    "- **Resolution Evidence / Date:** \n"
    "- **Specs Impact:** Shapes FR-001 cancellation.\n\n"
)


def specs_with(label, value, remove=False, base=None):
    text = base if base is not None else T.build_specs(include_validation_summary=True)
    pat = re.compile(r"(?m)^- \*\*" + re.escape(label) + r":\*\*.*\n(?:[ \t]+[-*+][ \t].*\n)*")
    new = "" if remove else "- **{}:** {}\n".format(label, value)
    assert pat.search(text), label
    return pat.sub(lambda _m: new, text, count=1)


def validate(text, qa=None, approved=False, specs_approval=None):
    kw = {}
    if qa is not None:
        kw["qa"] = qa
    if approved:
        text = text.replace("- **Execution Authorized:** false",
                            "- **Execution Authorized:** true\n- **Execution Authorization Evidence:** "
                            "PM-DECISION 2026-09-12 (test fixture)")
        specs_approval = specs_approval or T.matching_specs_approval()
    root = T.mkroot(specs=text, specs_approval=specs_approval, **kw)
    try:
        return guard.full_spec_validation(root)
    finally:
        T._cleanup(root)


def is_010(d, needle=None):
    return d is not None and d.code == "PMO-SPEC-010" and (needle is None or needle in d.message)


def test_1_2_core_required():
    check("2/valid_baseline_passes", validate(T.build_specs(include_validation_summary=True)) is None)
    for label in guard.FR_CORE_LABELS:
        if label in ("Source Scope",):
            continue
        d = validate(specs_with(label, "", remove=True))
        check("1/core_absent_blocked/" + label, is_010(d), d)
    d = validate(specs_with("Requirement", "N/A"))
    check("1/core_placeholder_blocked", is_010(d, "placeholder"), d)
    d = validate(specs_with("Actor(s)", "TBD"))
    check("1/core_actor_placeholder_blocked", is_010(d), d)
    d = validate(specs_with("Source Requirement", "", remove=True))
    check("1/core_source_absent_blocked", is_010(d, "Source"), d)


def test_3_conditional_defined_and_states():
    check("3/defined_value_passes", validate(specs_with("Trigger", "The customer confirms checkout.")) is None)
    for label in guard.FR_CONDITIONAL_LABELS:
        d = validate(specs_with(label, "", remove=True))
        check("3/conditional_absent_blocked/" + label, is_010(d, "applicability"), d)
    check("4/not_applicable_with_reason_passes",
          validate(specs_with("Trigger", "NOT_APPLICABLE: configuration requirement, not event-driven")) is None)
    check("4/not_applicable_em_dash_reason_passes",
          validate(specs_with("Trigger", "NOT_APPLICABLE — configuration requirement")) is None)
    for bad in ("NOT_APPLICABLE", "NOT_APPLICABLE:", "NOT_APPLICABLE: N/A", "NOT_APPLICABLE: none"):
        check("5/invalid_not_applicable_blocked/" + bad, is_010(validate(specs_with("Trigger", bad))), bad)
    check("6/not_specified_accepted", validate(specs_with("Trigger", "NOT_SPECIFIED")) is None)
    check("6/not_specified_with_note_accepted",
          validate(specs_with("Trigger", "NOT_SPECIFIED: the source does not define a trigger")) is None)
    check("13/lowercase_state_rejected", is_010(validate(specs_with("Trigger", "not_specified"))))


def test_7_8_9_pending_decision():
    d = validate(specs_with("Permissions", "PENDING_DECISION"), qa=QA_WITH_PENDING)
    check("7/pending_without_reference_blocked", is_010(d, "canonical Q&A"), d)
    d = validate(specs_with("Permissions", "PENDING_DECISION: QST-099"), qa=QA_WITH_PENDING)
    check("7/pending_unknown_record_blocked", is_010(d, "no such canonical Q&A"), d)
    d = validate(specs_with("Permissions", "PENDING_DECISION: QST-002"), qa=QA_WITH_PENDING)
    check("8/pending_with_unresolved_record_passes", d is None, d)
    d = validate(specs_with("Permissions", "PENDING_DECISION: QST-001"), qa=QA_WITH_PENDING)
    check("9/pending_linked_to_resolved_blocked", is_010(d, "already RESOLVED"), d)
    # An approved baseline is immutable: a later resolution is not a defect there
    d = validate(specs_with("Permissions", "PENDING_DECISION: QST-001"), qa=QA_WITH_PENDING, approved=True)
    check("9/approved_baseline_not_invalidated_by_later_resolution", d is None, d)
    # PENDING_DECISION surfaces through the Q&A record in the PM decision inbox
    import pmo_lifecycle_core as plc
    root = T.mkroot(specs=specs_with("Permissions", "PENDING_DECISION: QST-002"), qa=QA_WITH_PENDING)
    try:
        ids = {i["id"] for i in plc.build_decision_inbox(root)}
        check("8/pending_decision_in_pm_inbox", "QST-002" in ids and "QST-001" not in ids, ids)
    finally:
        T._cleanup(root)


def test_10_optional_absent():
    for label in ("Primary Behavior", "Priority"):
        check("10/optional_absent_passes/" + label,
              validate(specs_with(label, "", remove=True)) is None)
    check("10/optional_present_preserved",
          "- **Primary Behavior:**" in T.build_specs(include_validation_summary=True))


def test_11_12_acceptance_criteria():
    ml = specs_with("Acceptance Criteria", "", remove=True).replace(
        "- **Status:** ACTIVE",
        "- **Acceptance Criteria:**\n  - Given a valid cart, When checkout is confirmed, Then an order is created.\n"
        "  - Given an empty cart, When checkout is attempted, Then it is rejected.\n- **Status:** ACTIVE", 1)
    check("11/multiline_bullets_pass", validate(ml) is None)
    num = ml.replace("  - Given a valid", "  1. Given a valid").replace("  - Given an empty", "  2. Given an empty")
    check("11/numbered_list_passes", validate(num) is None)
    blk = guard.parse_fr_definitions(ml)["FR-001"]
    check("11/parser_returns_verbatim_items",
          guard._field_value(blk, "Acceptance Criteria").split("\n")[0]
          == "Given a valid cart, When checkout is confirmed, Then an order is created.")
    empty = specs_with("Acceptance Criteria", "", remove=True).replace(
        "- **Status:** ACTIVE", "- **Acceptance Criteria:**\n- **Status:** ACTIVE", 1)
    check("12/label_without_criteria_blocked", is_010(validate(empty), "Acceptance"), validate(empty))
    check("12/absent_blocked", is_010(validate(specs_with("Acceptance Criteria", "", remove=True))))
    check("12/na_blocked", is_010(validate(specs_with("Acceptance Criteria", "N/A"))))
    bullets_na = specs_with("Acceptance Criteria", "", remove=True).replace(
        "- **Status:** ACTIVE", "- **Acceptance Criteria:**\n  - N/A\n- **Status:** ACTIVE", 1)
    check("12/placeholder_bullets_blocked", is_010(validate(bullets_na)))


def test_13_bare_placeholders_cannot_bypass():
    for label in guard.FR_CONDITIONAL_LABELS:
        for ph in ("N/A", "None", "TBD", "NA", "None."):
            d = validate(specs_with(label, ph))
            if not is_010(d, "placeholder"):
                check("13/bare_{}_blocked_for_{}".format(ph, label), False, d)
                break
        else:
            check("13/bare_placeholders_blocked/" + label, True)
    # substantive text that merely starts with 'None' is a value, not a placeholder
    check("13/none_with_substance_is_defined",
          validate(specs_with("Business Rules", "None beyond the BR set in Section 22.")) is None)
    # approved legacy baseline valid under the prior schema keeps free-text values
    check("13/approved_legacy_free_text_still_valid",
          validate(specs_with("Trigger", "N/A"), approved=True) is None)


def test_14_15_generator_contract():
    skill = open(os.path.join(REPO, ".claude", "skills", "spec-generation", "SKILL.md"),
                 encoding="utf-8").read()
    flat = " ".join(skill.split())
    for state in guard.APPLICABILITY_STATES:
        check("15/skill_documents_state/" + state, state in flat)
    check("15/skill_examples_use_canonical_serialization",
          "NOT_APPLICABLE: <reason>" in flat and "PENDING_DECISION: QST-###" in flat)
    check("14/skill_forbids_fabrication",
          "Never invent a behavioural detail merely to avoid `NOT_SPECIFIED`" in flat)
    check("14/skill_forbids_bare_placeholders", "never write a bare `N/A`/`None`/`TBD`" in flat)
    check("14/skill_classifies_every_field",
          all(l in flat for l in guard.FR_CORE_LABELS[:-1] + guard.FR_CONDITIONAL_LABELS
              + guard.FR_OPTIONAL_LABELS if l != "Source Scope"))
    check("14/skill_defers_to_guard_definition", "FR_CORE_LABELS" in flat and "reuse, never re-type" in flat)
    rg = open(os.path.join(REPO, ".claude", "skills", "requirement-gathering", "SKILL.md"),
              encoding="utf-8").read()
    rgf = " ".join(rg.split())
    check("14/qa_skill_only_material_decisions",
          "only for an unresolved decision that materially affects" in rgf
          and "`NOT_SPECIFIED` create **no** Q&A record" in rgf)
    check("14/qa_skill_never_reopens_resolved", "Never re-open or duplicate an already-resolved record" in rgf)
    # the guard's classes partition the enforced fields with no overlap
    groups = [guard.FR_CORE_LABELS, guard.FR_DERIVED_LABELS, guard.FR_CONDITIONAL_LABELS,
              guard.FR_OPTIONAL_LABELS]
    flat_labels = [l for g in groups for l in g]
    check("14/classes_do_not_overlap", len(flat_labels) == len(set(flat_labels)))


def legacy_root_missing_detail():
    """Legacy-layout, provisional, most conditional fields absent (WM shape)."""
    text = M.to_legacy(M.canonical_specs())
    for label in ("Preconditions", "Trigger", "Inputs", "Outputs", "Validation Rules",
                  "Alternate / Exception Behavior", "Permissions", "Primary Behavior"):
        text = specs_with(label, "", remove=True, base=text)
    text = text.replace("- **Business Rules:** NOT_APPLICABLE: no business rule applies to this requirement\n", "")
    text = text.replace("- **Dependencies:** NOT_APPLICABLE: no dependency applies to this requirement\n",
                        "- **Dependencies:** None.\n")
    text = text.replace("| Order | order_reference | Yes | System-generated, unique | FR-001 |",
                        "| Order | order_reference | Yes | System-generated, unique | FR-001 |")
    return T.mkroot(specs=text), text


def test_16_migration_classification():
    root, legacy = legacy_root_missing_detail()
    try:
        d0 = guard.full_spec_validation(root)
        check("16/legacy_fails_before", d0 is not None, d0)
        b = M.cli.cmd_begin(root, "migrate + classify")
        check("16/begin_active", b["status"] == "ACTIVE", b)
        st = b["plan"]["plan"]["applicability"]
        check("16/classification_counts", st["added_not_specified"] == 7
              and st["added_business_rules_not_applicable"] == 1
              and st["placeholders_to_not_applicable"] == 1, st)
        f = M.cli.cmd_finalize(root)
        after = open(M.spath(root)).read()
        check("16/finalized_and_valid", f["status"] == "MIGRATED" and guard.full_spec_validation(root) is None, f)
        check("16/no_pending_decision_invented", "PENDING_DECISION" not in after)
        check("16/no_new_qa_created", open(os.path.join(root, "docs", "pmo", "requirements",
              "questions-and-assumptions.md")).read() == T.QA_ALL_RESOLVED)
        check("16/bare_none_normalized_with_quote",
              '- **Dependencies:** NOT_APPLICABLE: legacy placeholder "None."' in after)
        check("16/existing_values_preserved",
              all(v in after for v in ("The customer confirms checkout." if False else "The system lets a signed-in",
                                       "Given a valid cart When checkout is confirmed Then an order is created.")))
        check("16/ids_and_counts_identical",
              re.findall(r"(?m)^###\s+(FR-\d+)", after) == re.findall(r"(?m)^###\s+(FR-\d+)", legacy))
        check("16/version_and_execution_unchanged",
              "**Spec Version:** 0.1" in after and "**Execution Authorized:** false" in after)
        check("16/no_approval", not os.path.exists(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml")))
    finally:
        T._cleanup(root)
    # a core placeholder is ambiguous: fail closed, nothing written
    text = M.to_legacy(M.canonical_specs()).replace("**Actor(s):** B2C customer", "**Actor(s):** TBD")
    root = T.mkroot(specs=text)
    try:
        before = open(M.spath(root), "rb").read()
        r = M.cli.cmd_begin(root, "x")
        check("16/core_placeholder_ambiguous_fails_closed",
              r["status"] == "BLOCKED" and open(M.spath(root), "rb").read() == before, r)
    finally:
        T._cleanup(root)


def test_16b_classification_is_additive_only():
    base, _ = mig.migrate_layout(M.to_legacy(M.canonical_specs()))
    text = specs_with("Trigger", "", remove=True, base=base)
    cls, _stats = mig.classify_conditional_fields(text)
    check("16b/classified_ok", mig.classification_is_additive(text, cls)[0])
    bad = cls.replace("The system lets a signed-in B2C customer", "The system lets a customer")
    check("16b/value_rewrite_detected", not mig.classification_is_additive(text, bad)[0])
    bad2 = cls.replace("- **Trigger:** NOT_SPECIFIED", "- **Trigger:** The customer taps a button.")
    check("16b/invented_value_detected", not mig.classification_is_additive(text, bad2)[0])
    bad3 = cls.replace("- **Trigger:** NOT_SPECIFIED\n", "- **Trigger:** NOT_SPECIFIED\n- **Priority:** MUST\n")
    check("16b/added_nonconditional_field_detected", not mig.classification_is_additive(text, bad3)[0])
    check("16b/approved_legacy_values_untouched",
          mig.classify_conditional_fields(text.replace(
              "- **Status:** ACTIVE", "- **Status:** DEFERRED"))[0] == text.replace(
              "- **Status:** ACTIVE", "- **Status:** DEFERRED"))


def _suite_ok(path):
    r = subprocess.run([sys.executable, os.path.join(REPO, path)], capture_output=True, text=True)
    return r.returncode == 0


def test_17_to_22_existing_governance_intact():
    suites = {
        "17/approved_baseline_and_specs_guard": ".claude/hooks/test_specs_governance_guard.py",
        "17/specs_approval": ".claude/scripts/test_specs_approval_recorder.py",
        "18/cr_governance": ".claude/hooks/test_change_request_governance_guard.py",
        "18/cr_incorporation": ".claude/scripts/test_change_request_incorporator.py",
        "19/feedback_governance": ".claude/hooks/test_feedback_governance_guard.py",
        "20/qa_register": ".claude/hooks/test_qa_register_guard.py",
        "20/lifecycle": ".claude/lib/test_pmo_lifecycle_core.py",
        "21/legacy_scope_path": ".claude/hooks/test_scope_version_guard.py",
        "22/new_no_scope_path": ".claude/hooks/test_wm_trucking_new_lifecycle_eligibility.py",
    }
    for name, path in suites.items():
        check(name, _suite_ok(path))
    # approved baseline still cannot be edited by Claude's Write/Edit: the
    # policy relaxation never lets an applicability change through.
    approved_text = T.build_specs(include_validation_summary=True).replace(
        "- **Execution Authorized:** false",
        "- **Execution Authorized:** true\n- **Execution Authorization Evidence:** "
        "PM-DECISION 2026-09-12 (test fixture)")
    root = T.mkroot(specs=approved_text, specs_approval=T.matching_specs_approval())
    try:
        d = guard.full_spec_validation(root)
        check("17/approved_baseline_valid_under_policy", d is None, d)
    finally:
        T._cleanup(root)


def test_wm_read_only_compatibility():
    real = os.path.join(REPO, "docs", "pmo", "specs", "specs.md")
    if not os.path.exists(real):
        check("wm/skipped_no_real_project", True)
        return
    h = hashlib.sha256(open(real, "rb").read()).hexdigest()
    text = open(real, encoding="utf-8").read()
    layout, _ = mig.migrate_layout(text)
    frs = guard.parse_fr_definitions(layout)
    recognized = [r for r, b in frs.items() if guard._field_value(b, "Acceptance Criteria")]
    bullets = sum(len(guard._field_value(b, "Acceptance Criteria").split("\n")) for b in frs.values()
                  if guard._field_value(b, "Acceptance Criteria"))
    check("wm/all_acceptance_criteria_recognized", len(recognized) == len(frs) == 68, len(recognized))
    check("wm/acceptance_criteria_bullets", bullets == 105, bullets)
    cand, plan, dec = mig.build_candidate(REPO, text)
    check("wm/candidate_builds_no_regeneration", dec is None, dec)
    counts = src.applicability_counts(cand)
    check("wm/no_pending_decision_or_new_qst_required", counts["PENDING_DECISION"] == 0, counts)
    check("wm/candidate_passes_full_validation", guard.full_spec_validation(REPO, spec_text=cand) is None)
    check("wm/real_file_untouched", hashlib.sha256(open(real, "rb").read()).hexdigest() == h)
    check("wm/no_marker_created", not os.path.exists(
        os.path.join(REPO, ".pmo", "specs-schema-migration-transaction.json")))


def main():
    for fn in (
        test_1_2_core_required,
        test_3_conditional_defined_and_states,
        test_7_8_9_pending_decision,
        test_10_optional_absent,
        test_11_12_acceptance_criteria,
        test_13_bare_placeholders_cannot_bypass,
        test_14_15_generator_contract,
        test_16_migration_classification,
        test_16b_classification_is_additive_only,
        test_17_to_22_existing_governance_intact,
        test_wm_read_only_compatibility,
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
