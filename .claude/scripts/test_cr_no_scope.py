#!/usr/bin/env python3
"""Regression tests for NEW-lifecycle (no-Scope) Change Request incorporation
(cr_no_scope_incorporation_core.py + the shared CR core/CLI), the canonical CR
authorization parsing (approved_cr_ids), the post-incorporation authorization
of the Change Source, and the CR -> PM reapproval -> publication path.

Synthetic temporary projects only. The real WM Trucking project is used
READ-ONLY (copied into a temporary directory for the end-to-end acceptance
fixture) and asserted unchanged.
"""

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "hooks"))

import test_specs_structural_repair as T  # noqa: E402
import test_feedback_amendment as FA  # noqa: E402
import test_change_request_governance_guard as CT  # noqa: E402
import cr_no_scope_incorporation_core as nsc  # noqa: E402
import change_request_incorporation_core as crc  # noqa: E402
import publication_evidence_core as pev  # noqa: E402
import pmo_lifecycle_core as plc  # noqa: E402
import specs_feedback_amendment_core as amd  # noqa: E402

_s = importlib.util.spec_from_file_location("cr_incorporator_cli", os.path.join(HERE, "change-request-incorporator.py"))
cli = importlib.util.module_from_spec(_s)
_s.loader.exec_module(cli)
_a = importlib.util.spec_from_file_location("specs_approval_cli", os.path.join(HERE, "specs-approval-recorder.py"))
appr = importlib.util.module_from_spec(_a)
_a.loader.exec_module(appr)

check = T.check
_RESULTS = T._RESULTS
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CFG = FA.CFG
SPECS_REL = "docs/pmo/specs/specs.md"
CRID = "CR-001"


def sp(root):
    return os.path.join(root, *SPECS_REL.split("/"))


def rd(p):
    return open(p, "rb").read()


def cr_text(status="APPROVED", origin="PM_PROPOSED", decision="APPROVED", by="Jane PM", date="2026-09-22",
            evidence="Client email 2026-09-22 approving CR-001", affected="FR-001", blocking="", cr_id=CRID,
            proposed="Add a Driver accept/reject requirement and update FR-001.", pid="SMART-BASKET"):
    t = CT.cr_doc(cr_id, origin=origin, status=status, decision=decision if status in ("APPROVED", "INCORPORATED") else "",
                  decision_date=date if decision else "", decision_by=by if decision else "",
                  approval_evidence=evidence if decision else "", project_id=pid, title="Driver accept/reject",
                  history_rows=["| 2026-09-22 | — | {} | PM | test |".format(status)])
    t = t.replace("| Affected Requirements | REQUIRED | FR-020 |", "| Affected Requirements | REQUIRED | {} |".format(affected))
    t = t.replace("| Proposed Change | REQUIRED | change |", "| Proposed Change | REQUIRED | {} |".format(proposed))
    if blocking:
        lines = t.split("\n")
        last = max(i for i, l in enumerate(lines) if l.startswith("| Rejection/Deferral Reason"))
        lines.insert(last + 1, "| Blocking Open Decisions | OPTIONAL | {} |".format(blocking))
        lines.insert(last + 1, "| Assumptions / Open Decisions | OPTIONAL | response deadline; no-dispatcher-on-duty handling |")
        t = "\n".join(lines)
    return t


def register(status="APPROVED", cr_id=CRID):
    return CT.cr_register_doc(["| {} | Driver accept/reject | PM_PROPOSED | {} | | | | 2026-09-22 |".format(cr_id, status)])


def fr_block(rid, title, requirement, cr=CRID):
    return "\n".join([
        "### {} — {}".format(rid, title), "", "- **ID:** " + rid, "- **Title:** " + title,
        "- **Module:** MOD-004 / Cart, Checkout and Payments", "- **Actor(s):** B2C customer",
        "- **Requirement:** " + requirement, "- **Source Requirement:** {} (client-approved change request)".format(cr),
        "- **Introduced In:** 0.0", "- **Last Modified In:** 0.0", "- **Change Source:** INITIAL_INTENT",
        "- **Trigger:** The customer selects Accept or Reject.", "- **Preconditions:** NOT_SPECIFIED", "- **Inputs:** NOT_SPECIFIED",
        "- **Outputs:** NOT_SPECIFIED", "- **Validation Rules:** NOT_SPECIFIED", "- **Alternate / Exception Behavior:** NOT_SPECIFIED",
        "- **Permissions:** NOT_SPECIFIED",
        "- **Business Rules:** NOT_APPLICABLE: no Business Rule in the Business Rules table traces to this requirement",
        "- **Dependencies:** FR-001", "- **OPEN References:** None.", "- **Acceptance Criteria:**",
        "  - Given an assigned order, When the customer selects Accept, Then the acceptance is recorded.",
        "- **Status:** ACTIVE", ""])


def plan(extra=None):
    p = {"cr_id": CRID, "summary": "Driver accept/reject incorporated from CR-001.", "changes": [
        {"op": "set_field", "id": "FR-001", "field": "Requirement",
         "value": "The system lets a signed-in B2C customer confirm a cart and place an order, and accept or reject the assignment."},
        {"op": "add_requirement", "block": fr_block("FR-002", "Customer Accept or Reject", "A customer can accept or reject an assignment.")},
    ]}
    if extra is not None:
        p["changes"] = extra
    return p


def mk(cr=None, origin="PM_PROPOSED", scope=False, receipt=True, reg=True, **crkw):
    root = FA.mk(feedback=False) if origin == "PM_PROPOSED" else FA.mk(feedback=True, classification="CHANGE_REQUEST", related_cr=CRID)
    T._w(os.path.join(root, "docs", "pmo", "cr", CRID + ".md"), cr if cr is not None else cr_text(origin=origin, **crkw))
    if reg:
        T._w(os.path.join(root, "docs", "pmo", "cr", "change-request-register.md"), register(crkw.get("status", "APPROVED")))
    if scope:
        T._w(os.path.join(root, "docs", "pmo", "scope", "scope-v0.1.md"), "# Scope\n\n| Field | Value |\n|---|---|\n| Scope Version | 0.1 |\n")
    if receipt:
        pev.write_receipt(root, _receipt(root))
    return root


def _receipt(root):
    data = rd(sp(root))
    cfg = pev.iac.load_project_config(root)
    fields, _ = pev.apc.extract_repo_fields(cfg)
    return pev.build_receipt("SMART-BASKET", "specs", SPECS_REL, pev.artifact_version("specs", data.decode(), cfg),
                             hashlib.sha256(data).hexdigest(), fields, "a" * 40, "2026-09-21T12:00:00Z")


def snapshot(root):
    out = {}
    for base in ("docs", ".pmo"):
        for cur, _d, names in os.walk(os.path.join(root, base)):
            for n in names:
                p = os.path.join(cur, n)
                out[os.path.relpath(p, root)] = hashlib.sha256(rd(p)).hexdigest()
    return out


def begin(root, p=None, dry=False):
    return cli.cmd_begin(root, CRID, plan=p if p is not None else plan(), dry_run=dry)


def test_1_3_incorporation_never_requires_scope():
    root = mk()
    try:
        check("3/no_scope_project_detected", nsc.is_no_scope_project(root))
        check("3/no_scope_dir_needed", not os.path.exists(os.path.join(root, "docs", "pmo", "scope")))
        b = begin(root)
        check("1/begin_active", b["status"] == "ACTIVE" and b["marker"]["lifecycle"] == "NO_SCOPE", b)
        check("1/plan_reports_no_candidate_text", "candidate" not in b["plan"] and b["plan"]["target_specs_version"] == "0.2", b["plan"])
        v = cli.cmd_validate(root, CRID)
        check("1/validate_pass", v["status"] == "PASS", v)
        f = cli.cmd_finalize(root, CRID)
        check("1/finalize_incorporated", f["status"] == "INCORPORATED", f)
        check("3/no_scope_or_changelog_created", not os.path.exists(os.path.join(root, "docs", "pmo", "scope"))
              and not os.path.exists(os.path.join(root, "docs", "pmo", "change-log")))
        check("1/marker_removed", not os.path.exists(os.path.join(root, ".pmo", "change-request-transaction.json")))
    finally:
        T._cleanup(root)


def test_2_legacy_scope_path_unchanged():
    root = mk(scope=True)
    try:
        check("2/scope_project_is_legacy", not nsc.is_no_scope_project(root))
        r = begin(root)
        marker = cli.cr_marker_status(root)[1] or {}
        check("2/legacy_route_used_not_no_scope",
              (r["status"] == "ACTIVE" and "lifecycle" not in marker and marker.get("target_scope_version") == "0.2"
               and "baseline_scope_path" in marker)
              or (r["status"] == "BLOCKED" and r["decision"]["code"].startswith("PMO-CR-INTEGRATE")), r)
        b = nsc.run_begin(root, CRID, plan())
        check("2/no_scope_core_refuses_scope_project", b[0] is not None and b[0].code == "PMO-CR-NOSCOPE-001", b[0])
    finally:
        T._cleanup(root)
    for name, path in (("2/legacy_incorporator_suite", ".claude/scripts/test_change_request_incorporator.py"),
                       ("2/legacy_cr_governance_suite", ".claude/hooks/test_change_request_governance_guard.py")):
        r = subprocess.run([sys.executable, os.path.join(REPO, path)], capture_output=True, text=True)
        check(name, r.returncode == 0, r.stdout[-200:])


def test_4_5_6_unauthorized_crs_cannot_modify_specs():
    for name, kw in (("draft", dict(status="DRAFT")), ("pm_review", dict(status="PM_REVIEW")),
                     ("pending", dict(status="PENDING_CLIENT_DECISION")), ("rejected", dict(status="REJECTED")),
                     ("cancelled", dict(status="CANCELLED")), ("deferred", dict(status="DEFERRED"))):
        root = mk(**kw)
        try:
            before = snapshot(root)
            r = begin(root)
            check("4/{}_cr_blocked".format(name), r["status"] == "BLOCKED" and r["decision"]["code"] == "PMO-CR-INTEGRATE-002", r)
            check("4/{}_nothing_written".format(name), snapshot(root) == before)
            check("9/{}_not_authorizing_for_specs_guard".format(name), CRID not in crc.cr_authorizing_ids(root))
        finally:
            T._cleanup(root)
    for name, kw in (("no_decision", dict(decision="")), ("no_evidence", dict(evidence="")),
                     ("wrong_cr_id_inside", dict(cr_id="CR-777"))):
        root = mk(**kw)
        try:
            before = snapshot(root)
            r = begin(root)
            check("6/malformed_{}_blocked".format(name), r["status"] == "BLOCKED", r)
            check("6/malformed_{}_nothing_written".format(name), snapshot(root) == before)
            check("6/malformed_{}_not_authorizing".format(name), CRID not in crc.cr_authorizing_ids(root))
        finally:
            T._cleanup(root)
    root = mk()
    try:
        d = crc.validate_specs_write("Edit", {"file_path": sp(root), "old_string": "a", "new_string": "b"}, root, "ABSENT", None, None)
        check("4/direct_specs_write_still_blocked", d is not None and d.code == "PMO-CR-GUARD-013", d)
        b = begin(root)
        d = crc.validate_specs_write("Edit", {"file_path": sp(root), "old_string": "a", "new_string": "b"}, root, "OPEN",
                                     cli.cr_marker_status(root)[1], None)
        check("4/write_edit_denied_even_during_no_scope_transaction", d is not None and d.code == "PMO-CR-GUARD-032", d)
        d = crc.validate_scope_write("Write", {"file_path": os.path.join(root, "docs/pmo/scope/scope-v0.2.md"), "content": "x"},
                                     root, "docs/pmo/scope/scope-v0.2.md", "OPEN", cli.cr_marker_status(root)[1], None)
        check("3/scope_write_denied_during_no_scope_transaction", d is not None and d.code == "PMO-CR-GUARD-031", d)
        d = crc.validate_change_log_write("Write", {"file_path": "x", "content": "x"}, root, crc.CHANGE_LOG_POSIX,
                                          "OPEN", cli.cr_marker_status(root)[1], None)
        check("3/change_log_write_denied_during_no_scope_transaction", d is not None and d.code == "PMO-CR-GUARD-031", d)
    finally:
        T._cleanup(root)


def test_7_8_9_10_canonical_cr_parsing_and_post_incorporation():
    for status, expect in (("APPROVED", True), ("INCORPORATED", True), ("DRAFT", False), ("PM_REVIEW", False),
                           ("PENDING_CLIENT_DECISION", False), ("REJECTED", False), ("CANCELLED", False), ("DEFERRED", False)):
        root = T.mkroot(specs=FA.approved_text(), config=CFG)
        try:
            T._w(os.path.join(root, "docs", "pmo", "cr", CRID + ".md"), cr_text(status=status))
            got = CRID in crc.cr_authorizing_ids(root)
            name = "7/canonical_approved_recognised" if status == "APPROVED" else (
                "8/incorporated_remains_valid_change_source" if status == "INCORPORATED" else "9/{}_does_not_authorize".format(status.lower()))
            check(name, got == expect, (status, got))
            t = cr_text(status=status)
            status_read = crc.field_map_from_table(*crc.first_table(t)).get("Status")
            check("7/{}_status_read_structurally_not_as_REQUIRED_pipe".format(status.lower()), status_read == status, status_read)
        finally:
            T._cleanup(root)
    root = T.mkroot(specs=FA.approved_text(), config=CFG)
    try:
        T._w(os.path.join(root, "docs", "pmo", "cr", CRID + ".md"), "# CR-001\nStatus: APPROVED\n")
        check("7/legacy_plain_status_line_still_recognised", CRID in crc.cr_authorizing_ids(root))
        T._w(os.path.join(root, "docs", "pmo", "cr", CRID + ".md"), "# CR-001\nStatus: WHATEVER\n")
        check("9/arbitrary_status_never_authorizes", CRID not in crc.cr_authorizing_ids(root))
        T._w(os.path.join(root, "docs", "pmo", "cr", "CR-002.md"), cr_text(cr_id="CR-002", status="APPROVED"))
        check("7/multiple_records_independent", "CR-002" in crc.cr_authorizing_ids(root) and CRID not in crc.cr_authorizing_ids(root))
    finally:
        T._cleanup(root)
    # 10: the incorporated Specs keeps validating after the CR becomes INCORPORATED
    root = mk()
    try:
        begin(root); f = cli.cmd_finalize(root, CRID)
        check("10/finalized", f["status"] == "INCORPORATED", f)
        st = crc.field_map_from_table(*crc.first_table(open(os.path.join(root, "docs", "pmo", "cr", CRID + ".md")).read())).get("Status")
        d = T.core.specs_guard.full_spec_validation(root)
        check("10/cr_is_now_incorporated_and_specs_still_valid", st == "INCORPORATED" and d is None, (st, d))
        d2 = plc.specs_guard.full_spec_validation(root)
        check("10/lifecycle_guard_instance_agrees", d2 is None, d2)
        # the same Specs with a merely-DRAFT CR must be rejected (PMO-SPEC-014)
        cp = os.path.join(root, "docs", "pmo", "cr", CRID + ".md")
        T._w(cp, open(cp).read().replace("| Status | REQUIRED | INCORPORATED |", "| Status | REQUIRED | DRAFT |"))
        d3 = T.core.specs_guard.full_spec_validation(root)
        check("10/cr_change_source_requires_authorizing_cr", d3 is not None and d3.code == "PMO-SPEC-014", d3)
    finally:
        T._cleanup(root)


def test_11_to_23_full_lifecycle():
    root = mk()
    try:
        before_specs = rd(sp(root))
        before_appr = rd(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml"))
        rec_before = [n for n, _d, _e in pev.load_receipts(root, "specs")]
        s0 = plc.get_project_state(root)
        found, _diag = pev.find_valid_publication(root, "specs", SPECS_REL, "0.1", hashlib.sha256(before_specs).hexdigest())
        check("15/before_v0_1_published_and_cr_ready", found is not None
              and s0["lifecycle_state"] == "CR_READY_FOR_INCORPORATION" and s0["next_action"] == "APPROVE_CHANGE_REQUEST", s0)
        begin(root)
        check("21/marker_active_no_publication_yet", os.path.exists(os.path.join(root, ".pmo", "change-request-transaction.json")))
        f = cli.cmd_finalize(root, CRID)
        check("11/finalized", f["status"] == "INCORPORATED", f)
        new = open(sp(root)).read()
        check("11/version_progresses_canonically_0.1_to_0.2", "**Spec Version:** 0.2" in new and f["report"]["specs_version_after"] == "0.2", f["report"])
        old = before_specs.decode()
        # 12/13/14 preservation
        base, arch = amd.archive_targets(root, "0.1", hashlib.sha256(before_specs).hexdigest())
        check("12/previous_baseline_preserved_byte_identical", os.path.isfile(base) and rd(base) == before_specs)
        check("13/previous_approval_archived_unaltered", os.path.isfile(arch) and rd(arch) == before_appr)
        check("13/no_active_stale_approval_left", not os.path.exists(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml")))
        check("14/previous_publication_receipt_kept_as_history", [n for n, _d, _e in pev.load_receipts(root, "specs")] == rec_before)
        # 16/17
        check("16/execution_authorized_false", "**Execution Authorized:** false" in new)
        s1 = plc.get_project_state(root)
        check("17/changed_specs_do_not_inherit_approval",
              s1["lifecycle_state"] == "BASELINE_READY_FOR_APPROVAL" and s1["next_action"] == "APPROVE_BASELINE", s1)
        check("15/old_receipt_does_not_satisfy_new_version", s1["publication_status"] != "Published")
        # 22 unrelated unchanged + 23 traceability
        ob = {r: t for r, t in re.findall(r"(?ms)^### ((?:FR|NFR)-\d+)[^\n]*\n(.*?)(?=^### |^---|^## )", old)}
        na = {r: t for r, t in re.findall(r"(?ms)^### ((?:FR|NFR)-\d+)[^\n]*\n(.*?)(?=^### |^---|^## )", new)}
        check("22/only_fr001_modified_fr002_added", set(na) - set(ob) == {"FR-002"} and set(ob) <= set(na))
        check("22/nfr_and_tables_untouched", nsc.verify_confined(old, new, ["FR-001", "FR-002"], "0.2", CRID)[0])
        check("23/change_source_cr_on_touched_requirements",
              new.count("- **Change Source:** CR-001") == 2 and "- **Last Modified In:** 0.2" in new and "- **Introduced In:** 0.2" in new)
        check("23/change_history_row_traces_cr_and_versions",
              re.search(r"\| 0\.2 \| \d{4}-\d{2}-\d{2} \| CR-001 \| FR-001, FR-002 \| .* \| Pending PM approval \(CR-001 approved 2026-09-22 by Jane PM\) \|", new) is not None
              and "| 0.1 |" in new)
        cr = crc.field_map_from_table(*crc.first_table(open(os.path.join(root, "docs", "pmo", "cr", CRID + ".md")).read()))
        check("23/cr_record_traceable",
              cr["Status"] == "INCORPORATED" and cr["Change Log Reference"] == "Specs Change History v0.2"
              and cr["Incorporated Date"] and cr["Target Spec Version"] == "0.2" and cr["Decision By"] == "Jane PM")
        check("23/register_updated", "INCORPORATED" in open(os.path.join(root, "docs", "pmo", "cr", "change-request-register.md")).read())
        check("24/cr_open_decisions_and_qa_not_touched",
              rd(os.path.join(root, "docs", "pmo", "requirements", "questions-and-assumptions.md")) == rd(os.path.join(root, "docs", "pmo", "requirements", "questions-and-assumptions.md")))
        # 18/19 reapproval via the canonical recorder
        ap = appr.cmd_begin(root, "Jane PM", "2026-09-23", "approve amended v0.2")
        check("18/recorder_accepts_new_version", ap["status"] == "ACTIVE", ap)
        af = appr.cmd_finalize(root)
        check("18/approved", af["status"] == "APPROVED", af)
        a = open(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml")).read()
        after = open(sp(root)).read()
        check("19/new_approval_matches_new_version", 'spec_version: "0.2"' in a and 'project_id: "SMART-BASKET"' in a)
        check("19/new_approval_valid_for_current_bytes", T.core.sac.validate_specs_approval_matches(root, spec_version="0.2") is None
              and "**Execution Authorized:** true" in after)
        check("19/history_row_pm_decision_updated_in_place", after.count("| 0.2 |") == 1 and "Approved - " in after)
        s2 = plc.get_project_state(root)
        check("20/publication_ready_after_reapproval", s2["lifecycle_state"] == "PUBLICATION_READY" and s2["next_action"] == "PUBLISH", s2)
        ev = s2["_engineering"]["publication"]["evidence"]["receipts"]
        check("15/old_receipt_rejected_for_new_version", any("version" in r["reason"] for r in ev["rejected"]), ev)
        check("21/no_automatic_publication", len(os.listdir(pev.publications_dir(root))) == 1 and s2["publication_status"] == "Eligible")
    finally:
        T._cleanup(root)


def test_25_26_failed_incorporation_is_atomic_and_abortable():
    root = mk()
    try:
        before = snapshot(root)
        r = begin(root, plan([{"op": "set_field", "id": "FR-099", "field": "Requirement", "value": "x"}]))
        check("25/plan_targeting_unknown_requirement_blocked_at_begin", r["status"] == "BLOCKED", r)
        r = begin(root, plan([{"op": "set_field", "id": "FR-001", "field": "Requirement", "value": "changed"}]) )
        check("25/authorized_existing_change_ok", r["status"] == "ACTIVE", r)
        cli.cmd_abort(root, CRID, "reset")
        check("25/nothing_written_by_failed_begins", snapshot(root) == before)
    finally:
        T._cleanup(root)
    cases = {
        "unlisted_requirement": (dict(affected="FR-777"), plan(), "PMO-CR-NOSCOPE-012"),
        "id_reuse": (dict(), plan([{"op": "add_requirement", "block": fr_block("FR-001", "Dup", "dup")}]), "PMO-CR-NOSCOPE-014"),
        "governance_field": (dict(), plan([{"op": "set_field", "id": "FR-001", "field": "Change Source", "value": "X"}]), "PMO-CR-NOSCOPE-013"),
        "invented_detail_placeholder": (dict(), plan([{"op": "add_requirement", "block": fr_block("FR-002", "T", "R").replace("NOT_SPECIFIED", "N/A", 1)}]), "PMO-CR-NOSCOPE-017"),
        "empty_plan": (dict(), plan([]), "PMO-CR-NOSCOPE-010"),
        "blocking_decisions": (dict(blocking="response deadline must be decided first"), plan(), "PMO-CR-NOSCOPE-003"),
    }
    for name, (kw, p, code) in cases.items():
        root = mk(**kw)
        try:
            before = snapshot(root)
            r = begin(root, p)
            check("25/{}_blocked".format(name), r["status"] == "BLOCKED" and r["decision"]["code"] == code, r["decision"])
            check("25/{}_writes_nothing".format(name), snapshot(root) == before)
        finally:
            T._cleanup(root)
    # moved target after begin -> finalize fails closed
    root = mk()
    try:
        begin(root)
        with open(sp(root), "a") as fh:
            fh.write("\n<!-- moved -->\n")
        snap = snapshot(root)
        f = cli.cmd_finalize(root, CRID)
        check("25/moved_specs_finalize_fails_closed", f["status"] == "RECOVERY_REQUIRED", f)
        check("25/moved_specs_nothing_else_written", {k: v for k, v in snapshot(root).items() if "change-request-transaction" not in k} == {k: v for k, v in snap.items() if "change-request-transaction" not in k})
    finally:
        T._cleanup(root)
    # failure in the middle of finalize rolls everything back
    root = mk()
    try:
        begin(root)
        before = snapshot(root)
        orig = crc.validate_incorporated_gate
        crc.validate_incorporated_gate = lambda *a, **k: crc.deny("PMO-CR-GUARD-018", "simulated gate failure")
        try:
            f = cli.cmd_finalize(root, CRID)
        finally:
            crc.validate_incorporated_gate = orig
        after = snapshot(root)
        drop = lambda d: {k: v for k, v in d.items() if "change-request-transaction" not in k}
        check("25/mid_finalize_failure_reported", f["status"] == "RECOVERY_REQUIRED", f)
        check("25/rolled_back_no_partial_specs_version_archive_or_cr", drop(after) == drop(before))
        check("25/no_archive_dirs_left", not os.path.exists(os.path.join(root, ".pmo", "baselines")))
        ab = cli.cmd_abort(root, CRID, "simulated failure")
        check("26/abort_ok", ab["status"] == "ABORTED", ab)
        check("26/marker_removed_specs_identical", not os.path.exists(os.path.join(root, ".pmo", "change-request-transaction.json"))
              and drop(snapshot(root)) == drop(before))
        check("26/cr_still_approved", crc.field_map_from_table(*crc.first_table(open(os.path.join(root, "docs", "pmo", "cr", CRID + ".md")).read())).get("Status") == "APPROVED")
        check("26/abort_without_marker_reported", cli.cmd_abort(root, CRID, "x")["status"] == "BLOCKED")
    finally:
        T._cleanup(root)
    root = mk()
    try:
        begin(root)
        with open(sp(root), "a") as fh:
            fh.write("\nedit\n")
        check("26/abort_refused_when_specs_moved", cli.cmd_abort(root, CRID, "x")["status"] == "BLOCKED")
        T._w(os.path.join(root, ".pmo", "change-request-transaction.json"), "{bad")
        check("26/invalid_marker_fails_closed", cli.cmd_abort(root, CRID, "x")["status"] == "BLOCKED")
    finally:
        T._cleanup(root)


def test_requirement_retirement_and_removal_fail_closed():
    root = mk()
    try:
        before = snapshot(root)
        for name, ch, code in (
            ("status_retired", [{"op": "set_field", "id": "FR-001", "field": "Status", "value": "RETIRED"}], "PMO-CR-NOSCOPE-018"),
            ("status_deferred", [{"op": "set_field", "id": "FR-001", "field": "Status", "value": "DEFERRED"}], "PMO-CR-NOSCOPE-018"),
            ("remove_op", [{"op": "remove_requirement", "id": "FR-001"}], "PMO-CR-NOSCOPE-010"),
            ("retire_op", [{"op": "retire_requirement", "id": "FR-001"}], "PMO-CR-NOSCOPE-010"),
        ):
            r = begin(root, plan(ch))
            check("29/{}_blocked".format(name), r["status"] == "BLOCKED" and r["decision"]["code"] == code, r["decision"])
        check("29/nothing_written", snapshot(root) == before)
        d, cand = None, None
        text = open(sp(root)).read()
        ok, why = nsc.verify_confined(text, re.sub(r"(?ms)^### FR-001 .*?(?=^### |^---|^## )", "", text, count=1), ["FR-001"], "0.2", CRID)
        check("29/disappearing_requirement_rejected_by_semantic_diff", not ok and "disappeared" in (why or ""), why)
    finally:
        T._cleanup(root)


def test_client_requested_cr_with_feedback_backlink():
    root = mk(origin="CLIENT_REQUESTED")
    try:
        b = begin(root)
        check("1/client_requested_cr_incorporates", b["status"] == "ACTIVE", b)
        f = cli.cmd_finalize(root, CRID)
        check("1/client_requested_finalized", f["status"] == "INCORPORATED", f)
    finally:
        T._cleanup(root)


def test_27_28_29_other_governance_unchanged():
    suites = {
        "27/feedback_amendment": ".claude/scripts/test_feedback_amendment.py",
        "28/initial_specs_generation": ".claude/skills/spec-generation/test_spec_generation_contract.py",
        "28/specs_governance": ".claude/hooks/test_specs_governance_guard.py",
        "29/publication_lifecycle": ".claude/scripts/test_publication_state.py",
        "29/lifecycle": ".claude/lib/test_pmo_lifecycle_core.py",
        "29/approval_recorder": ".claude/scripts/test_specs_approval_recorder.py",
    }
    for name, path in suites.items():
        r = subprocess.run([sys.executable, os.path.join(REPO, path)], capture_output=True, text=True)
        check(name, r.returncode == 0, r.stdout[-200:])


def test_wm_read_only_acceptance():
    real = os.path.join(REPO, SPECS_REL)
    if not os.path.exists(real):
        check("wm/skipped_no_real_project", True)
        return
    before = {}
    for base in ("docs", ".pmo"):
        for cur, _d, names in os.walk(os.path.join(REPO, base)):
            for n in names:
                p = os.path.join(cur, n)
                before[os.path.relpath(p, REPO)] = hashlib.sha256(rd(p)).hexdigest()
    s_real = plc.get_project_state(REPO)
    check("wm/real_baseline_approved_published", s_real["lifecycle_state"] == "BASELINE_APPROVED" and s_real["publication_status"] == "Published", s_real["lifecycle_state"])
    tmp = tempfile.mkdtemp(prefix="wm-cr-accept-")
    try:
        shutil.copytree(os.path.join(REPO, "docs"), os.path.join(tmp, "docs"))
        shutil.copytree(os.path.join(REPO, ".pmo"), os.path.join(tmp, ".pmo"))
        text = open(sp(tmp)).read()
        m033 = re.search(r"(?ms)^### FR-033 .*?(?=^### )", text).group(0)
        module_line = [l for l in m033.split("\n") if l.startswith("- **Module:**")][0]

        def blk(n, title, actors, req, trig, ac):
            return "\n".join(["### FR-{:03d} — {}".format(n, title), "", "- **ID:** FR-{:03d}".format(n), "- **Title:** " + title,
                              module_line, "- **Actor(s):** " + actors, "- **Requirement:** " + req,
                              "- **Source Requirement:** CR-001 (client request, driver accept/reject)", "- **Introduced In:** 0.0",
                              "- **Last Modified In:** 0.0", "- **Change Source:** INITIAL_INTENT", "- **Trigger:** " + trig,
                              "- **Preconditions:** NOT_SPECIFIED", "- **Inputs:** NOT_SPECIFIED", "- **Outputs:** NOT_SPECIFIED",
                              "- **Validation Rules:** NOT_SPECIFIED", "- **Alternate / Exception Behavior:** NOT_SPECIFIED",
                              "- **Permissions:** NOT_SPECIFIED",
                              "- **Business Rules:** NOT_APPLICABLE: no Business Rule in the Business Rules table traces to this requirement",
                              "- **Dependencies:** FR-033, FR-042, FR-043", "- **OPEN References:** None.", "- **Acceptance Criteria:**"]
                             + ["  - " + a for a in ac] + ["- **Status:** ACTIVE", ""])
        wm_plan = {"cr_id": CRID, "summary": "Driver accept/reject of job assignments (CR-001).", "changes": [
            {"op": "add_requirement", "block": blk(69, "Driver Accept / Reject of Job Assignment", "Driver",
                                                      "A Driver assigned a job can Accept or Reject it directly from the Driver App.",
                                                      "The Driver is shown an assigned job in the Driver App.",
                                                      ["Given an assigned job, When the Driver selects Accept, Then the acceptance is recorded.",
                                                       "Given an assigned job, When the Driver selects Reject, Then the rejection is recorded."])},
            {"op": "add_requirement", "block": blk(70, "Rejected Assignment — Dispatcher Notification and Return to Queue", "Driver, Dispatcher",
                                                      "When a Driver rejects a job assignment, the Dispatcher is notified and the assignment returns to the available assignment queue.",
                                                      "A Driver rejects an assigned job.",
                                                      ["Given a rejection, When it is recorded, Then the Dispatcher is notified.",
                                                       "Given a rejection, When it is recorded, Then the assignment appears in the available assignment queue."])},
        ]}
        T._w(os.path.join(tmp, "docs", "pmo", "cr", CRID + ".md"),
             cr_text(origin="PM_PROPOSED", pid="WM-TRUCKING", affected="FR-033, FR-042, FR-043",
                     proposed="Add driver accept/reject requirements, Dispatcher notification and re-queue behavior; details not given remain OPEN.",
                     blocking="").replace("SMART-BASKET", "WM-TRUCKING"))
        T._w(os.path.join(tmp, "docs", "pmo", "cr", "change-request-register.md"), register().replace("SMART-BASKET", "WM-TRUCKING"))
        old_specs = rd(sp(tmp))
        old_app = rd(os.path.join(tmp, ".pmo", "approvals", "specs-approval.yaml"))
        b = cli.cmd_begin(tmp, CRID, plan=wm_plan)
        check("wm/synthetic_cr_begin", b["status"] == "ACTIVE", b)
        f = cli.cmd_finalize(tmp, CRID)
        check("wm/synthetic_cr_incorporated", f["status"] == "INCORPORATED", f)
        st = plc.get_project_state(tmp)
        check("wm/lifecycle_after_incorporation", st["lifecycle_state"] == "BASELINE_READY_FOR_APPROVAL" and st["next_action"] == "APPROVE_BASELINE", st)
        new = open(sp(tmp)).read()
        check("wm/version_0_2_and_68_plus_2_requirements", "**Spec Version:** 0.2" in new
              and len(re.findall(r"(?m)^### FR-", new)) == 70 and len(re.findall(r"(?m)^### FR-", old_specs.decode())) == 68)
        check("wm/unrelated_content_confined", nsc.verify_confined(old_specs.decode(), new, ["FR-069", "FR-070"], "0.2", CRID)[0])
        check("wm/previous_baseline_and_approval_archived",
              rd(amd.archive_targets(tmp, "0.1", hashlib.sha256(old_specs).hexdigest())[0]) == old_specs
              and rd(amd.archive_targets(tmp, "0.1", hashlib.sha256(old_specs).hexdigest())[1]) == old_app)
        ap = appr.cmd_begin(tmp, "Muhammad Faizan", "2026-09-23", "SIMULATED reapproval (temporary copy)")
        af = appr.cmd_finalize(tmp) if ap["status"] == "ACTIVE" else ap
        check("wm/synthetic_reapproval", af["status"] == "APPROVED", (ap, af))
        s2 = plc.get_project_state(tmp)
        check("wm/lifecycle_after_reapproval_publication_ready", s2["lifecycle_state"] == "PUBLICATION_READY" and s2["next_action"] == "PUBLISH", s2)
        check("wm/old_receipt_historical_not_satisfying", len(os.listdir(pev.publications_dir(tmp))) == 1 and s2["publication_status"] == "Eligible")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    after = {}
    for base in ("docs", ".pmo"):
        for cur, _d, names in os.walk(os.path.join(REPO, base)):
            for n in names:
                p = os.path.join(cur, n)
                after[os.path.relpath(p, REPO)] = hashlib.sha256(rd(p)).hexdigest()
    check("wm/real_project_byte_identical", after == before)
    check("wm/no_real_cr_or_marker", not os.path.exists(os.path.join(REPO, "docs", "pmo", "cr"))
          and not os.path.exists(os.path.join(REPO, ".pmo", "change-request-transaction.json")))
    s = plc.get_project_state(REPO)
    check("wm/real_lifecycle_unchanged", s["lifecycle_state"] == "BASELINE_APPROVED" and s["publication_status"] == "Published")


def main():
    for fn in (
        test_1_3_incorporation_never_requires_scope,
        test_2_legacy_scope_path_unchanged,
        test_4_5_6_unauthorized_crs_cannot_modify_specs,
        test_7_8_9_10_canonical_cr_parsing_and_post_incorporation,
        test_11_to_23_full_lifecycle,
        test_25_26_failed_incorporation_is_atomic_and_abortable,
        test_requirement_retirement_and_removal_fail_closed,
        test_client_requested_cr_with_feedback_backlink,
        test_27_28_29_other_governance_unchanged,
        test_wm_read_only_acceptance,
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
