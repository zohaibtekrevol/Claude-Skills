#!/usr/bin/env python3
"""Regression tests for FEEDBACK_AMENDMENT (specs-feedback-amendment.py +
specs_feedback_amendment_core.py): the governed, non-functional amendment of an
APPROVED Specs baseline from a canonical Feedback record.

Every fixture is a synthetic temporary project (shared with the STRUCTURAL_REPAIR
suite, so the same real guards run). The real WM Trucking project is only read
in memory (test_wm_read_only) and asserted unchanged.
"""

import hashlib
import importlib.util
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "hooks"))

import test_specs_structural_repair as T  # noqa: E402
import test_fr_schema_policy as FP  # noqa: E402
import test_feedback_governance_guard as FT  # noqa: E402
import specs_feedback_amendment_core as amd  # noqa: E402
import publication_evidence_core as pev  # noqa: E402
import pmo_lifecycle_core as plc  # noqa: E402
import change_request_incorporation_core as crc  # noqa: E402

_spec = importlib.util.spec_from_file_location("specs_feedback_amendment_cli", os.path.join(HERE, "specs-feedback-amendment.py"))
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)
_aspec = importlib.util.spec_from_file_location("specs_approval_cli", os.path.join(HERE, "specs-approval-recorder.py"))
appr = importlib.util.module_from_spec(_aspec)
_aspec.loader.exec_module(appr)

check = T.check
_RESULTS = T._RESULTS
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
ITEM = "FB-2026-001-001"
BATCH = "FB-2026-001"
CFG = T.CONFIG_YAML.replace("  verified: true\n", '  working_branch: "pmo-artifacts"\n  verified: true\n')
EVIDENCE = ("- **Execution Authorized:** true\n- **Execution Authorization Evidence:** "
            "PM-DECISION 2026-09-12 (test fixture)")
SPECS_REL = "docs/pmo/specs/specs.md"


def approved_text(mut=None):
    t = T.build_specs(include_validation_summary=True).replace("- **Execution Authorized:** false", EVIDENCE)
    t = t.replace("place an order.", "place an order and recieve a confirmation.", 1)
    t = t.replace("- **Outputs:** A persisted order.", "- **Outputs:** A persisted order confirmation.")
    return mut(t) if mut else t


def fb_files(classification="BUG", status="OPEN", original=None, normalized=None,
             affected="FR-001", artifact="Specification (specs.md)", related_cr="", item_id=ITEM):
    original = original or "Client: FR-001 says 'recieve' but it should read 'receive'; also 'cart' is fine."
    normalized = normalized or "Correct the spelling of 'recieve' to 'receive' in FR-001."
    blk = FT.item_block(item_id, BATCH, classification, status=status, related_cr=related_cr, original=original)
    blk = blk.replace("| Normalized Interpretation | REQUIRED | Checkout submit fails. |",
                      "| Normalized Interpretation | REQUIRED | {} |".format(normalized))
    blk = blk.replace("| Affected Artifact | REQUIRED | Customer App |", "| Affected Artifact | REQUIRED | {} |".format(artifact))
    blk = blk.replace("| Affected Existing Requirement IDs | REQUIRED | FR-020 |",
                      "| Affected Existing Requirement IDs | REQUIRED | {} |".format(affected))
    batch = FT.batch_doc(BATCH, 1, blk)
    trow = "| {} | {} | {} | {} | {} | | 2026-09-14 |".format(item_id, BATCH, classification, status, related_cr or "")
    brow = "| {} | 2026-09-14 | EMAIL | Specs | 1 | CLASSIFIED | 2026-09-14 |".format(BATCH)
    tracker = FT.tracker_doc(item_rows=[trow], batch_rows=[brow])
    return batch, tracker


def mk(mut=None, feedback=True, qa=None, **fbkw):
    kw = {"qa": qa} if qa is not None else {}
    root = T.mkroot(specs=approved_text(mut), config=CFG, specs_approval=T.matching_specs_approval(), **kw)
    if feedback:
        batch, tracker = fb_files(**fbkw)
        T._w(os.path.join(root, "docs", "pmo", "feedback", "batches", BATCH + ".md"), batch)
        T._w(os.path.join(root, "docs", "pmo", "feedback", "feedback-tracker.md"), tracker)
    return root


def sp(root):
    return os.path.join(root, *SPECS_REL.split("/"))


def rd(p):
    return open(p, "rb").read()


def fixed(**kw):
    d = {"kind": "text", "target": "FR-001", "before": "recieve", "after": "receive", "equivalence": None}
    d.update(kw)
    return d


def outcome(root, correction, feedback=ITEM):
    r = amd.build_candidate(root, feedback, correction)
    return r.get("outcome"), r


def test_1_2_3_eligible_wording_corrections():
    root = mk()
    try:
        o, r = outcome(root, fixed())
        check("1/typo_is_feedback_amendment", o == amd.FEEDBACK_AMENDMENT, r.get("reasons") or r.get("decision"))
        check("1/typo_ids_and_version", r["changed_ids"] == ["FR-001"] and r["version_after"] == "0.2")
    finally:
        T._cleanup(root)
    root = mk(original="Client: FR-001 use 'Signed-in' for signed-in and 'signed-in b2c' for signed-in B2C.",
              normalized="Capitalization of signed-in / B2C in FR-001.")
    try:
        o, r = outcome(root, fixed(before="signed-in", after="Signed-in"))
        check("2/capitalization_only_eligible", o == amd.FEEDBACK_AMENDMENT, r.get("reasons") or r.get("decision"))
        o, r = outcome(root, fixed(before="signed-in B2C", after="signed-in b2c"))
        check("2/case_change_of_id_like_token_only", o == amd.FEEDBACK_AMENDMENT, r.get("reasons"))
    finally:
        T._cleanup(root)
    # terminology: declared equivalence, target term already used elsewhere
    mut = lambda t: t.replace("place an order.", "place an order.", 1).replace(
        "confirm a cart", "confirm a basket", 1)
    root = mk(mut, original="Client: in FR-001 use 'cart' instead of 'basket' - same thing.",
              normalized="Terminology: basket = cart in FR-001.")
    try:
        o, r = outcome(root, fixed(before="basket", after="cart", equivalence=["basket", "cart"]))
        check("3/declared_equivalence_eligible", o == amd.FEEDBACK_AMENDMENT, r.get("reasons") or r.get("decision"))
        o, r = outcome(root, fixed(before="basket", after="cart"))
        check("3/undeclared_equivalence_is_substantive", o == amd.CHANGE_REQUEST_REQUIRED, r.get("reasons"))
        o, r = outcome(root, fixed(before="basket", after="wishlist", equivalence=["basket", "wishlist"]))
        check("3/equivalence_must_be_attested_and_in_baseline",
              o is None or o == amd.CHANGE_REQUEST_REQUIRED, (o, r.get("reasons")))
    finally:
        T._cleanup(root)
    # uniform rename of an actor term (Q new, replaced everywhere)
    root = mk(original="Client: rename 'B2C customer' to 'Shopper' everywhere (FR-001).",
              normalized="Terminology: B2C customer -> Shopper.")
    try:
        o, r = outcome(root, {"kind": "rename", "from": "B2C customer", "to": "Shopper"})
        check("3/uniform_rename_eligible", o == amd.FEEDBACK_AMENDMENT, r.get("reasons") or r.get("decision"))
        after = "\n".join(l for l in r["candidate"].split("\n") if not l.startswith("| 0.2 |"))
        check("3/rename_leaves_no_old_term", "B2C customer" not in after and "Shopper" in after)
        o, r = outcome(root, {"kind": "rename", "from": "B2C customer", "to": "cart"})
        check("3/rename_to_existing_term_is_a_merge_so_cr_required", o == amd.CHANGE_REQUEST_REQUIRED, (o, r.get("reasons"), r.get("decision")))
    finally:
        T._cleanup(root)


def test_4_no_artifact_change():
    root = mk(classification="NOT_ACTIONABLE", original="Client: thanks, looks good (FR-001).", normalized="No action.")
    try:
        before = rd(sp(root)); approval = rd(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml"))
        pev.write_receipt(root, _receipt(root))
        r = cli.cmd_assess(root, ITEM, None)
        check("4/assess_no_artifact_change", r["status"] == amd.NO_ARTIFACT_CHANGE, r)
        res = cli.cmd_resolve_no_change(root, ITEM, "acknowledged, no Specs change needed")
        check("4/resolved", res["status"] == "RESOLVED_NO_CHANGE", res)
        check("4/specs_byte_identical", rd(sp(root)) == before)
        check("4/approval_untouched_and_valid", rd(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml")) == approval)
        s = plc.get_project_state(root)
        check("4/publication_still_valid_version_unchanged",
              s["lifecycle_state"] == "BASELINE_APPROVED" and s["publication_status"] == "Published", s)
        tracker = open(os.path.join(root, "docs", "pmo", "feedback", "feedback-tracker.md")).read()
        batch = open(os.path.join(root, "docs", "pmo", "feedback", "batches", BATCH + ".md")).read()
        check("4/feedback_record_resolved", "| RESOLVED |" in tracker and "| Status | REQUIRED | RESOLVED |" in batch)
        check("4/no_cr_created", not os.path.exists(os.path.join(root, "docs", "pmo", "cr")))
        again = cli.cmd_resolve_no_change(root, ITEM, "x")
        check("4/cannot_resolve_twice", again["status"] == "BLOCKED", again)
    finally:
        T._cleanup(root)
    # a CHANGE_REQUEST-classified item can never be resolved this way / amended
    root = mk(classification="CHANGE_REQUEST", related_cr="CR-001")
    try:
        r = cli.cmd_resolve_no_change(root, ITEM, "x")
        check("4/cr_linked_item_not_resolvable_here", r["status"] == "BLOCKED", r)
    finally:
        T._cleanup(root)


def _receipt(root):
    data = rd(sp(root)); text = data.decode()
    cfg = pev.iac.load_project_config(root)
    fields, _ = pev.apc.extract_repo_fields(cfg)
    return pev.build_receipt("SMART-BASKET", "specs", SPECS_REL, pev.artifact_version("specs", text, cfg),
                             hashlib.sha256(data).hexdigest(), fields, "a" * 40, "2026-09-21T12:00:00Z")


def cr_required(name, mut, correction, **fb):
    root = mk(mut, **fb)
    try:
        before = rd(sp(root))
        o, r = outcome(root, correction)
        check("cr/{}".format(name), o == amd.CHANGE_REQUEST_REQUIRED, (o, r.get("reasons") or r.get("decision")))
        check("cr/{}_no_write_no_cr".format(name), rd(sp(root)) == before and not os.path.exists(
            os.path.join(root, "docs", "pmo", "cr")) and not os.path.exists(amd.marker_abspath(root)))
        if o == amd.CHANGE_REQUEST_REQUIRED:
            msg = amd.pm_message(r)
            check("cr/{}_pm_message_business_language".format(name),
                  "Change Request" in msg and "PMO-" not in msg and "guard" not in msg.lower(), msg)
    finally:
        T._cleanup(root)


def test_5_to_14_substantive_changes_require_cr():
    fb = dict(original="Client: change it (FR-001).", normalized="Change: X.")
    ph = lambda a, b: dict(original="Client: FR-001 '{}' should be '{}'.".format(a, b),
                           normalized="'{}' -> '{}' in FR-001".format(a, b))
    cr_required("new_requirement_multiline", None,
                fixed(before="place an order", after="place an order\n### FR-099 - New thing"),
                original="Client: please also add a new requirement FR-099 after 'place an order' (FR-001).",
                normalized="Add FR-099 after 'place an order'.")
    cr_required("added_functionality_words", None,
                fixed(before="place an order", after="place an order and apply loyalty points"),
                **ph("place an order", "place an order and apply loyalty points"))
    cr_required("requirement_text_removed", None,
                fixed(before=" and recieve a confirmation", after=""), **ph(" and recieve a confirmation", ""))
    cr_required("actor_change", None,
                fixed(before="**Actor(s):** B2C customer", after="**Actor(s):** Admin"),
                **ph("**Actor(s):** B2C customer", "**Actor(s):** Admin"))
    cr_required("workflow_change", None,
                fixed(before="confirms checkout", after="cancels checkout"), **ph("confirms checkout", "cancels checkout"))
    cr_required("permission_change", None,
                fixed(before="may place their own order", after="may place any order"),
                **ph("may place their own order", "may place any order"))
    cr_required("acceptance_outcome_change", None,
                fixed(before="Then an order is created", after="Then no order is created"),
                **ph("Then an order is created", "Then no order is created"))
    cr_required("business_rule_field_change", None,
                fixed(before="no business rule applies", after="a 10% discount applies"),
                **ph("no business rule applies", "a 10% discount applies"))
    cr_required("integration_table_change", None,
                {"kind": "text", "target": "section:integrations", "before": "Provider", "after": "Vendor", "equivalence": None},
                **ph("Provider", "Vendor"))
    cr_required("number_change", lambda t: t.replace("a confirmation.", "a confirmation within 5 minutes.", 1),
                fixed(before="within 5 minutes", after="within 15 minutes"), **ph("within 5 minutes", "within 15 minutes"))
    cr_required("identifier_change", None,
                fixed(before="INT-REQ-001", after="INT-REQ-002"), **ph("INT-REQ-001", "INT-REQ-002"))
    cr_required("module_change", None,
                fixed(before="Cart, Checkout and Payments", after="Cart"), **ph("Cart, Checkout and Payments", "Cart"))
    cr_required("not_specified_to_defined",
                lambda t: t.replace("- **Inputs:** Cart contents.", "- **Inputs:** NOT_SPECIFIED"),
                fixed(before="NOT_SPECIFIED", after="The cart items"), **ph("NOT_SPECIFIED", "The cart items"))
    cr_required("not_applicable_to_defined", None,
                fixed(before="NOT_APPLICABLE: no dependency applies to this requirement",
                      after="FR-002"), **ph("NOT_APPLICABLE: no dependency applies to this requirement", "FR-002"))
    cr_required("pending_decision_resolved",
                lambda t: t.replace("- **Inputs:** Cart contents.", "- **Inputs:** PENDING_DECISION: QST-002"),
                fixed(before="PENDING_DECISION: QST-002", after="Cart contents"),
                qa=FP.QA_WITH_PENDING, **ph("PENDING_DECISION: QST-002", "Cart contents"))
    cr_required("title_meaning_change", None,
                fixed(before="**Title:** Customer places an online order", after="**Title:** Customer places online orders"),
                **ph("**Title:** Customer places an online order", "**Title:** Customer places online orders"))
    cr_required("doc_control_change", None,
                {"kind": "text", "target": "section:specification document control", "before": "PROVISIONAL",
                 "after": "ACTIVE", "equivalence": None}, **ph("PROVISIONAL", "ACTIVE"))
    cr_required("changes_meaning_with_similar_word", None,
                fixed(before="customer confirm a cart", after="customer confirms a cart"),
                **ph("customer confirm a cart", "customer confirms a cart"))
    cr_required("classified_change_request", None, fixed(), classification="CHANGE_REQUEST", related_cr="CR-001")


def test_15_direct_write_still_blocked():
    root = mk()
    try:
        d = crc.validate_specs_write("Write", {"file_path": sp(root), "content": open(sp(root)).read() + "\nx\n"},
                                     root, "ABSENT", None, None)
        check("15/direct_write_to_approved_specs_denied", d is not None and d.code == "PMO-CR-GUARD-013", d)
        d = crc.validate_specs_write("Edit", {"file_path": sp(root), "old_string": "recieve", "new_string": "receive"},
                                     root, "ABSENT", None, None)
        check("15/direct_edit_denied_even_for_a_typo", d is not None and d.code == "PMO-CR-GUARD-013", d)
    finally:
        T._cleanup(root)


def test_16_17_18_canonical_feedback_and_baseline_binding():
    root = mk(feedback=False)
    try:
        r = cli.cmd_begin(root, ITEM, fixed(), "PM approves")
        check("16/no_feedback_record_blocked", r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-FB-AMEND-001", r)
        r = cli.cmd_assess(root, "not-an-id", fixed())
        check("16/non_canonical_id_blocked", r["status"] == "BLOCKED", r)
    finally:
        T._cleanup(root)
    root = mk()
    try:
        r = cli.cmd_begin(root, ITEM, fixed(target="FR-099"), "PM approves")
        check("17/nonexistent_target_blocked", r["status"] == "BLOCKED", r)
        r = cli.cmd_begin(root, ITEM, fixed(before="nonexistent text"), "PM approves")
        check("17/before_text_not_present_blocked", r["status"] == "BLOCKED", r)
        r = cli.cmd_begin(root, ITEM, fixed(), "  ")
        check("17/processing_reason_required", r["status"] == "BLOCKED", r)
    finally:
        T._cleanup(root)
    root = mk(affected="FR-020")
    try:
        r = cli.cmd_begin(root, ITEM, fixed(), "PM approves")
        check("17/target_not_in_feedback_affected_ids_blocked",
              r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-FB-AMEND-009", r)
    finally:
        T._cleanup(root)
    root = mk(original="Client: unrelated comment.", normalized="Unrelated.")
    try:
        r = cli.cmd_begin(root, ITEM, fixed(), "PM approves")
        check("16/correction_not_attested_by_record_blocked",
              r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-FB-AMEND-008", r)
    finally:
        T._cleanup(root)
    for name, kw in (("resolved_item", {"status": "RESOLVED"}), ("wrong_artifact", {"artifact": "Customer App"}),
                     ("related_cr", {"related_cr": "CR-001"})):
        root = mk(**kw)
        try:
            r = cli.cmd_begin(root, ITEM, fixed(), "PM approves")
            check("16/{}_blocked".format(name), r["status"] in ("BLOCKED", amd.CHANGE_REQUEST_REQUIRED), r["status"])
        finally:
            T._cleanup(root)
    # baseline binding: unapproved / unclean / wrong version
    root = T.mkroot(specs=T.build_specs(include_validation_summary=True), config=CFG)
    try:
        b, t = fb_files()
        T._w(os.path.join(root, "docs", "pmo", "feedback", "batches", BATCH + ".md"), b)
        T._w(os.path.join(root, "docs", "pmo", "feedback", "feedback-tracker.md"), t)
        r = cli.cmd_begin(root, ITEM, fixed(), "PM approves")
        check("18/unapproved_baseline_not_amendable",
              r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-FB-AMEND-012", r)
    finally:
        T._cleanup(root)
    root = mk()
    try:
        os.remove(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml"))
        r = cli.cmd_begin(root, ITEM, fixed(), "PM approves")
        check("18/missing_approval_blocked", r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-FB-AMEND-012", r)
    finally:
        T._cleanup(root)
    root = mk()
    try:
        T._w(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml"), T.matching_specs_approval("0.9"))
        r = cli.cmd_begin(root, ITEM, fixed(), "PM approves")
        check("18/approval_for_other_version_blocked", r["status"] == "BLOCKED", r)
    finally:
        T._cleanup(root)
    root = mk()
    try:
        b = cli.cmd_begin(root, ITEM, fixed(), "PM approves")
        check("18/begin_active", b["status"] == "ACTIVE", b)
        with open(sp(root), "a") as fh:
            fh.write("\n<!-- moved -->\n")
        moved = rd(sp(root))
        f = cli.cmd_finalize(root)
        check("18/moved_hash_fails_closed", f["status"] == "RECOVERY_REQUIRED", f)
        check("18/moved_specs_untouched", rd(sp(root)) == moved)
    finally:
        T._cleanup(root)


def test_19_20_failed_amendment_is_atomic_and_abortable():
    root = mk()
    try:
        before = rd(sp(root)); appr = rd(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml"))
        b = cli.cmd_begin(root, ITEM, fixed(), "PM approves")
        check("19/begin_active", b["status"] == "ACTIVE", b)
        os.remove(os.path.join(root, "docs", "pmo", "feedback", "feedback-tracker.md"))  # record broken mid-transaction
        f = cli.cmd_finalize(root)
        check("19/finalize_fails_closed", f["status"] == "RECOVERY_REQUIRED", f)
        check("19/approved_artifact_byte_identical", rd(sp(root)) == before)
        check("19/approval_untouched", rd(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml")) == appr)
        check("19/no_archives_written", not os.path.exists(os.path.join(root, ".pmo", "baselines")))
        a = cli.cmd_abort(root, "record broken")
        check("20/abort_ok", a["status"] == "ABORTED", a)
        check("20/marker_removed_specs_identical", not os.path.exists(amd.marker_abspath(root)) and rd(sp(root)) == before)
        check("20/abort_without_marker", cli.cmd_abort(root, "x")["status"] == "NO_TRANSACTION")
    finally:
        T._cleanup(root)
    root = mk()
    try:
        cli.cmd_begin(root, ITEM, fixed(), "PM approves")
        r = cli.cmd_begin(root, ITEM, fixed(), "again")
        check("20/second_begin_blocked_while_open", r["status"] == "BLOCKED", r)
        T._w(amd.marker_abspath(root), "{bad")
        check("20/invalid_marker_abort_fails_closed", cli.cmd_abort(root, "x")["status"] == "BLOCKED")
    finally:
        T._cleanup(root)


def test_21_to_23_successful_amendment_lifecycle():
    root = mk()
    try:
        old_specs = rd(sp(root)); old_appr = rd(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml"))
        pev.write_receipt(root, _receipt(root))
        s0 = plc.get_project_state(root)
        check("21/before_published", s0["lifecycle_state"] == "BASELINE_APPROVED" and s0["publication_status"] == "Published", s0)
        b = cli.cmd_begin(root, ITEM, fixed(), "PM approves processing")
        check("21/begin_active_plan", b["status"] == "ACTIVE" and b["plan"]["spec_version_after"] == "0.2", b)
        f = cli.cmd_finalize(root)
        check("21/finalized", f["status"] == "AMENDED", f)
        new = open(sp(root)).read()
        check("21/marker_removed", not os.path.exists(amd.marker_abspath(root)))
        body = "\n".join(l for l in new.split("\n") if not l.startswith("| 0.2 |"))
        check("21/typo_fixed_only", "recieve" not in body and "receive a confirmation" in body)
        old = old_specs.decode()
        diff = [l for l in new.split("\n") if l not in old.split("\n")]
        check("21/only_governed_lines_changed", all(any(k in l for k in ("receive a confirmation", "Spec Version", "Execution Authorized",
                                                                       "Last Modified In", "Change Source", "| 0.2 |")) for l in diff), diff)
        check("21/version_is_next_minor", "**Spec Version:** 0.2" in new)
        check("21/execution_not_authorized", "**Execution Authorized:** false" in new)
        check("21/change_source_is_feedback_id", "- **Change Source:** {}".format(ITEM) in new and "- **Last Modified In:** 0.2" in new)
        check("21/change_history_row_added", re.search(r"\| 0\.2 \| \d{4}-\d{2}-\d{2} \| " + ITEM + r" \| FR-001 \|", new) is not None
              and new.count("| 0.1 |") >= 1)
        check("21/full_validation_passes", T.core.specs_guard.full_spec_validation(root) is None)
        check("21/requirement_count_unchanged", len(re.findall(r"(?m)^###\s+FR-", new)) == len(re.findall(r"(?m)^###\s+FR-", old)))
        # feedback closed
        check("21/feedback_resolved", "| Status | REQUIRED | RESOLVED |" in open(os.path.join(root, "docs", "pmo", "feedback", "batches", BATCH + ".md")).read())
        # 22: previous baseline + approval preserved, receipt kept
        base = os.path.join(root, ".pmo", "baselines", "specs-v0.1-{}.md".format(hashlib.sha256(old_specs).hexdigest()[:12]))
        arch = os.path.join(root, ".pmo", "approvals", "history",
                            "specs-approval-v0.1-{}.yaml".format(hashlib.sha256(old_specs).hexdigest()[:12]))
        check("22/previous_baseline_recoverable_byte_identical", os.path.isfile(base) and rd(base) == old_specs)
        check("22/previous_approval_archived_unaltered", os.path.isfile(arch) and rd(arch) == old_appr)
        check("22/previous_publication_receipt_kept", len(os.listdir(pev.publications_dir(root))) == 1)
        # 23: lifecycle demands re-approval
        s1 = plc.get_project_state(root)
        check("23/reapproval_required", s1["lifecycle_state"] == "BASELINE_READY_FOR_APPROVAL"
              and s1["next_action"] == "APPROVE_BASELINE", s1)
        check("21/no_automatic_publication", s1["publication_status"] != "Published")
        ap = appr.cmd_begin(root, "Jane PM", "2026-09-22", "approve amended v0.2")
        check("23/approval_recorder_accepts_new_version", ap["status"] == "ACTIVE", ap)
        af = appr.cmd_finalize(root)
        check("23/approved_again", af["status"] == "APPROVED", af)
        s2 = plc.get_project_state(root)
        check("21/prior_publication_does_not_satisfy_new_version",
              s2["lifecycle_state"] == "PUBLICATION_READY" and s2["next_action"] == "PUBLISH", s2)
        rej = s2["_engineering"]["publication"]["evidence"]["receipts"]["rejected"]
        check("21/old_receipt_rejected_as_history", any("version" in r["reason"] or "sha" in r["reason"] for r in rej), rej)
        check("23/history_row_pm_decision_updated", "Approved - " in new or "Approved - " in open(sp(root)).read())
    finally:
        T._cleanup(root)


def test_pm_experience_and_engineering_mode():
    root = mk(original="Client: FR-001 says 'recieve'; also change '**Actor(s):** B2C customer' to '**Actor(s):** Admin'.",
              normalized="Fix 'recieve'; **Actor(s):** B2C customer -> **Actor(s):** Admin.")
    try:
        r = cli.cmd_assess(root, ITEM, fixed())
        check("pm/message_business_language", "non-functional baseline correction" in r["message"]
              and "PMO-" not in r["message"] and "approval again" in r["message"], r["message"])
        r = cli.cmd_assess(root, ITEM, fixed(before="**Actor(s):** B2C customer", after="**Actor(s):** Admin"), engineering=True)
        check("pm/engineering_mode_adds_detail", "[engineering]" in r["message"] and r["status"] == amd.CHANGE_REQUEST_REQUIRED, r["message"])
        r0 = cli.cmd_assess(root, ITEM, fixed(before="**Actor(s):** B2C customer", after="**Actor(s):** Admin"))
        check("pm/no_detail_by_default", "[engineering]" not in r0["message"])
        check("pm/assess_never_writes", not os.path.exists(amd.marker_abspath(root)))
        check("pm/no_cr_ever_created", not os.path.exists(os.path.join(root, "docs", "pmo", "cr")))
    finally:
        T._cleanup(root)


def test_wording_proof_units():
    base = "The system lets a customer confirm a cart within 5 minutes and receive a confirmation."
    def ok(a, b, eq=None):
        return amd.prove_wording_only(a, b, base + "\n" + a, {"Admin", "B2C customer"}, eq)[0]
    check("proof/capitalization", ok("a customer", "A customer"))
    check("proof/punctuation", ok("confirm a cart.", "confirm a cart"))
    check("proof/article_a_an", ok("a order", "an order"))
    check("proof/known_typo", ok("recieve a cart", "receive a cart"))
    check("proof/interior_distance_typo_attested_in_baseline", ok("a confimation", "a confirmation"))
    check("proof/ending_change_rejected", not ok("customer confirm", "customer confirms"))
    check("proof/real_word_ending_swap_rejected", not ok("a manager", "a managed"))
    check("proof/real_word_swap_rejected", not ok("a customer", "a customers"))
    check("proof/number_rejected", not ok("within 5 minutes", "within 15 minutes"))
    check("proof/negation_rejected", not ok("does", "does not"))
    check("proof/modal_swap_rejected", not ok("may confirm", "must confirm"))
    check("proof/quantifier_rejected", not ok("a customer", "any customer"))
    check("proof/symbol_rejected", not ok("a cart", "a cart + tax"))
    check("proof/entity_rename_rejected_locally", not ok("Admin", "Manager", ("Admin", "Manager")))
    check("proof/word_added_rejected", not ok("confirm a cart", "confirm a new cart"))
    check("proof/word_removed_rejected", not ok("confirm a cart within", "confirm cart"))
    check("proof/identity_rejected", not ok("same", "same"))


def test_24_25_26_existing_governance_intact():
    suites = {
        "24/cr_incorporation": ".claude/scripts/test_change_request_incorporator.py",
        "24/cr_governance": ".claude/hooks/test_change_request_governance_guard.py",
        "25/initial_specs_generation": ".claude/skills/spec-generation/test_spec_generation_contract.py",
        "25/specs_governance": ".claude/hooks/test_specs_governance_guard.py",
        "26/legacy_scope_path": ".claude/hooks/test_scope_version_guard.py",
        "26/feedback_governance": ".claude/hooks/test_feedback_governance_guard.py",
        "26/approval_recorder": ".claude/scripts/test_specs_approval_recorder.py",
        "26/publication_state": ".claude/scripts/test_publication_state.py",
        "26/lifecycle": ".claude/lib/test_pmo_lifecycle_core.py",
    }
    for name, path in suites.items():
        r = subprocess.run([sys.executable, os.path.join(REPO, path)], capture_output=True, text=True)
        check(name, r.returncode == 0, r.stdout[-200:])


def test_skill_documentation():
    fm = " ".join(open(os.path.join(REPO, ".claude", "skills", "feedback-management", "SKILL.md"), encoding="utf-8").read().split())
    sg = " ".join(open(os.path.join(REPO, ".claude", "skills", "spec-generation", "SKILL.md"), encoding="utf-8").read().split())
    for t in ("NO_ARTIFACT_CHANGE", "FEEDBACK_AMENDMENT", "CHANGE_REQUEST_REQUIRED"):
        check("docs/feedback_skill_names_" + t, t in fm)
    check("docs/feedback_skill_keeps_no_specs_write", "never writes `specs.md`" in fm)
    check("docs/spec_skill_documents_governed_mechanisms", "FEEDBACK_AMENDMENT" in sg and "never edited directly" in sg)
    r = subprocess.run([sys.executable, os.path.join(HERE, "test_specs_structural_repair.py")], capture_output=True, text=True)
    check("docs/repair_gate_sees_amendment_marker_suite_green", r.returncode == 0)


def test_wm_read_only():
    real = os.path.join(REPO, SPECS_REL)
    if not os.path.exists(real):
        check("wm/skipped_no_real_project", True)
        return
    h = hashlib.sha256(rd(real)).hexdigest()
    text = open(real, encoding="utf-8").read()
    s = plc.get_project_state(REPO)
    check("wm/still_baseline_approved_published",
          s["lifecycle_state"] == "BASELINE_APPROVED" and s["publication_status"] in ("Published", "Eligible"), s["lifecycle_state"])
    lines = text.split("\n")
    idx = [i for i, l in enumerate(lines) if "dispatcher, customer, broker" in l][0]
    rid = [m.group(1) for i in range(idx, -1, -1) for m in [amd._BLOCK_HEADING_RE.match(lines[i])] if m][0]
    cand, changed, why = amd.apply_correction(text, {"kind": "text", "target": rid, "before": "dispatcher, customer", "after": "Dispatcher, customer"})
    o, reasons = amd.classify_candidate(text, cand, changed, {"kind": "text", "target": rid, "before": "dispatcher, customer",
                                                              "after": "Dispatcher, customer"})
    check("wm/synthetic_wording_change_uses_amendment_path", o == amd.FEEDBACK_AMENDMENT, (o, reasons))
    c = {"kind": "text", "target": rid, "before": "English/Spanish", "after": "English/French"}
    cand, changed, why = amd.apply_correction(text, c)
    o, reasons = amd.classify_candidate(text, cand, changed, c)
    check("wm/synthetic_functional_change_is_change_request_required", o == amd.CHANGE_REQUEST_REQUIRED, (o, reasons))
    check("wm/real_baseline_and_receipt_untouched", hashlib.sha256(rd(real)).hexdigest() == h
          and not os.path.exists(os.path.join(REPO, ".pmo", "specs-feedback-amendment-transaction.json"))
          and not os.path.isdir(os.path.join(REPO, "docs", "pmo", "feedback")))


def main():
    for fn in (
        test_wording_proof_units,
        test_1_2_3_eligible_wording_corrections,
        test_4_no_artifact_change,
        test_5_to_14_substantive_changes_require_cr,
        test_15_direct_write_still_blocked,
        test_16_17_18_canonical_feedback_and_baseline_binding,
        test_19_20_failed_amendment_is_atomic_and_abortable,
        test_21_to_23_successful_amendment_lifecycle,
        test_pm_experience_and_engineering_mode,
        test_skill_documentation,
        test_24_25_26_existing_governance_intact,
        test_wm_read_only,
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
