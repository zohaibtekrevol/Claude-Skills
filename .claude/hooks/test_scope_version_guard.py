#!/usr/bin/env python3
"""Regression tests for .claude/hooks/scope-version-guard.py.

Stdlib only. Run: python3 .claude/hooks/test_scope_version_guard.py
Exit 0 = all pass, 1 = at least one failure.

Covers the A-W scenarios from the hook specification plus a few unit checks.
Uses simulated PreToolUse payloads and temporary Scope fixtures only - no real
Smart Basket Scope artifact is created.
"""

import importlib.util
import os
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "scope-version-guard.py")
_spec = importlib.util.spec_from_file_location("scope_version_guard", HOOK)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

_RESULTS = []


def check(name, ok, detail=""):
    _RESULTS.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + "  " + name + ("" if ok else "   :: " + str(detail)))


def code(decision):
    return getattr(decision, "code", None)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

INTENT_MD = """# Intent: Smart Basket

| Field | Value |
|---|---|
| Status | VALIDATED |
| Intent Version | 1.0 |

## 6. High-Level Product Requirements

| ID | Requirement | Evidence |
|---|---|---|
| INT-REQ-001 | Customer app | SRC-001 |
| INT-REQ-002 | Rider app | SRC-001 |
"""

CONFIG_YAML = (
    'project:\n'
    '  id: "SMART-BASKET"\n'
    '  name: "Smart Basket"\n'
    '  client: "Smart Basket / eBasket KSA"\n'
    'artifacts:\n'
    '  intent:\n'
    '    status: "VALIDATED"\n'
    'workflow:\n'
    '  intent:\n'
    '    approved: true\n'
)

APPROVAL_OK = (
    'artifact: docs/pmo/scope/scope-v1.0.md\n'
    'version: "1.0"\n'
    'decision: APPROVED\n'
    'approved_by: "PMO"\n'
    'approval_source: PM_EXPLICIT\n'
    'client_approval: CONFIRMED\n'
    'client_approval_reference: "client email 2026-09-25"\n'
    'approved_at: "2026-09-25T09:00:00Z"\n'
)

_SECTIONS = [
    "1. Executive Scope Summary", "2. Scope Basis",
    "3. Product Platforms and Interfaces", "4. Users and Roles",
    "5. Detailed Scope of Work", "6. Key User and Operational Workflows",
    "7. Brand and Design Guidelines", "8. Third-Party Integrations",
    "9. Data and Content Requirements", "10. Assumptions", "11. Dependencies",
    "12. Scope Gaps", "13. Open Questions", "14. Explicitly Out of Scope",
    "15. Client Responsibilities", "16. Delivery Team Responsibilities",
    "17. Commercial and Change-Control Boundaries",
    "18. Work Breakdown Structure", "19. Intent-to-Scope Traceability",
    "20. Scope Validation Summary", "21. Client Review Questions",
    "22. Acceptance and Approval", "23. Version History",
]


def build_scope(version="0.1", status="DRAFT_CLIENT_REVIEW",
                project_id="SMART-BASKET", client="Smart Basket / eBasket KSA",
                next_stage="SCOPE_REVIEW", prev="NONE",
                trace_reqs=("INT-REQ-001", "INT-REQ-002"),
                scp_req_rows=("SCP-REQ-001", "SCP-REQ-002"),
                open_rows=(), pse_rows=(), body_extra=""):
    dc = "\n".join([
        "## Document Control", "",
        "| Field | Value |", "|---|---|",
        "| Project | Smart Basket |",
        "| Project ID | {} |".format(project_id),
        "| Client | {} |".format(client),
        "| PM | Muneeb |",
        "| Scope Version | {} |".format(version),
        "| Status | {} |".format(status),
        "| Intent Version | 1.0 |",
        "| Date | 2026-09-15 |",
        "| Repository | Bitbucket - unverified |",
        "| Source Count | 4 |",
        "| Previous Scope Version | {} |".format(prev),
        "| Next Stage | {} |".format(next_stage),
    ])
    parts = ["# Scope: Smart Basket", "", dc, ""]
    for s in _SECTIONS:
        parts.append("## " + s)
        parts.append("")
        if s.endswith("Detailed Scope of Work"):
            parts.append("| ID | Requirement | Acceptance | Traces |")
            parts.append("|---|---|---|---|")
            for i, rid in enumerate(scp_req_rows, 1):
                parts.append("| {} | requirement {} | a criterion | INT-REQ-{:03d} |"
                             .format(rid, i, i))
        elif s.endswith("Open Questions"):
            if open_rows:
                parts.append("| ID | Blocking | Question | Why it matters | Owner | Required Before | Source |")
                parts.append("|---|---|---|---|---|---|---|")
                parts.extend(open_rows)
            else:
                parts.append("_No open items._")
        elif s.endswith("Work Breakdown Structure"):
            parts.append("| WBS | Deliverable | SCP-REQ |")
            parts.append("|---|---|---|")
            parts.append("| WBS-1 | Customer application | SCP-REQ-001 |")
            parts.append("| WBS-1.1 | Registration | SCP-REQ-001 |")
        elif s.endswith("Intent-to-Scope Traceability"):
            parts.append("| Trace | INT-REQ | Scope | Coverage |")
            parts.append("|---|---|---|---|")
            for i, r in enumerate(trace_reqs, 1):
                parts.append("| TRACE-INT-REQ-{:03d} | {} | SCP-REQ-{:03d} | COVERED |"
                             .format(i, r, i))
        elif s.endswith("Version History"):
            parts.append("| Version | Date | Status | Change Summary | Previous Version |")
            parts.append("|---|---|---|---|---|")
            if version == "0.1":
                parts.append("| 0.1 | 2026-09-15 | {} | Initial draft | NONE |".format(status))
            else:
                parts.append("| {} | 2026-09-15 | {} | Revision | {} |".format(version, status, prev))
        parts.append("")
    if pse_rows:
        parts.append("## Potential Scope Expansion")
        parts.append("")
        parts.append("| ID | Item | State | Disposition |")
        parts.append("|---|---|---|---|")
        parts.extend(pse_rows)
        parts.append("")
    if body_extra:
        parts.append(body_extra)
    return "\n".join(parts)


def run(tool, tool_input, scope_files=None, approval=None,
        intent=INTENT_MD, config=CONFIG_YAML):
    tmp = tempfile.mkdtemp(prefix="scope-guard-test-")
    try:
        os.makedirs(os.path.join(tmp, ".pmo", "approvals"), exist_ok=True)
        os.makedirs(os.path.join(tmp, "docs", "pmo", "intent"), exist_ok=True)
        os.makedirs(os.path.join(tmp, "docs", "pmo", "scope"), exist_ok=True)
        if config is not None:
            _w(os.path.join(tmp, ".pmo", "project-config.yaml"), config)
        if intent is not None:
            _w(os.path.join(tmp, "docs", "pmo", "intent", "intent.md"), intent)
        for name, text in (scope_files or {}).items():
            _w(os.path.join(tmp, "docs", "pmo", "scope", name), text)
        if approval is not None:
            _w(os.path.join(tmp, ".pmo", "approvals", "scope-approval.yaml"), approval)
        ti = dict(tool_input)
        fp = ti.get("file_path")
        if tool in ("Write", "Edit", "MultiEdit") and fp and not os.path.isabs(fp):
            ti["file_path"] = os.path.join(tmp, fp)
        return mod.process({"tool_name": tool, "tool_input": ti, "cwd": tmp})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _w(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


SCOPE_PATH = "docs/pmo/scope/scope-v0.1.md"


# --------------------------------------------------------------------------- #
# unit checks
# --------------------------------------------------------------------------- #

def test_units():
    check("unit/filename_parse", mod.parse_scope_version_from_filename(
        "docs/pmo/scope/scope-v2.7.md") == (2, 7))
    check("unit/filename_reject", mod.parse_scope_version_from_filename(
        "scope-v1.md") is None)
    ns = mod.normalize_stage
    check("unit/normalize_stage", ns("scope baseline") == "SCOPE_BASELINE"
          and ns("Specification Generation") == "SPECIFICATION_GENERATION"
          and ns("dev") == "DEVELOPMENT" and ns("nonsense") is None)
    check("unit/is_scope_path", mod.is_scope_file_path(
        "/x/docs/pmo/scope/scope-v0.1.md", "/x")
        and not mod.is_scope_file_path("/x/docs/pmo/intent/intent.md", "/x"))


# --------------------------------------------------------------------------- #
# A - W
# --------------------------------------------------------------------------- #

def test_A_valid_draft_create():
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.1.md",
                      "content": build_scope(version="0.1")})
    check("A/valid_draft_v0.1_create__ALLOW", d is None, code(d))


def test_B_incomplete_progressive():
    incomplete = ("# Scope\n\n## Document Control\n\n"
                  "| Scope Version | 0.1 |\n| Status | DRAFT_CLIENT_REVIEW |\n")
    d = run("Edit", {"file_path": "docs/pmo/scope/scope-v0.1.md",
                     "old_string": "## Document Control",
                     "new_string": "## Document Control\n\n## 1. Executive Scope Summary\n"},
            scope_files={"scope-v0.1.md": incomplete})
    check("B/incomplete_progressive_draft__ALLOW", d is None, code(d))


def test_C_fr_definition():
    doc = build_scope(version="0.1",
                      body_extra="## Appendix\n\n| FR-001 | login must respond in 2s |\n")
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.1.md", "content": doc})
    check("C/FR-001_in_scope__DENY_008", code(d) == "PMO-SCOPE-008", code(d))


def test_D_nfr_definition():
    doc = build_scope(version="0.1",
                      body_extra="## Appendix\n\n- NFR-001: availability 99.9%\n")
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.1.md", "content": doc})
    check("D/NFR-001_in_scope__DENY_008", code(d) == "PMO-SCOPE-008", code(d))


def test_E_duplicate_scp_req():
    doc = build_scope(version="0.1",
                      body_extra=("## Appendix\n\n"
                                  "| SCP-REQ-005 | first meaning | a | INT-REQ-001 |\n"
                                  "| SCP-REQ-005 | different meaning | a | INT-REQ-002 |\n"))
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.1.md", "content": doc})
    check("E/duplicate_SCP-REQ__DENY_009", code(d) == "PMO-SCOPE-009", code(d))


def test_F_missing_traceability():
    doc = build_scope(version="0.2", status="PM_REVIEWED", prev="0.1",
                      trace_reqs=("INT-REQ-001",))
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.2.md", "content": doc},
            scope_files={"scope-v0.1.md": build_scope(version="0.1")})
    check("F/missing_intent_traceability__DENY_007", code(d) == "PMO-SCOPE-007", code(d))


def test_G_edit_historical():
    d = run("Edit", {"file_path": "docs/pmo/scope/scope-v0.1.md",
                     "old_string": "Smart Basket", "new_string": "Smart Basket "},
            scope_files={"scope-v0.1.md": build_scope(version="0.1"),
                         "scope-v0.2.md": build_scope(version="0.2", prev="0.1")})
    check("G/edit_v0.1_while_v0.2_exists__DENY_006", code(d) == "PMO-SCOPE-006", code(d))


def test_H_valid_progression():
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.2.md",
                      "content": build_scope(version="0.2", prev="0.1")},
            scope_files={"scope-v0.1.md": build_scope(version="0.1")})
    check("H/valid_0.1_to_0.2__ALLOW", d is None, code(d))


def test_I_invalid_progression():
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.3.md",
                      "content": build_scope(version="0.3", prev="0.2")},
            scope_files={"scope-v0.1.md": build_scope(version="0.1")})
    check("I/invalid_0.1_to_0.3__DENY_010", code(d) == "PMO-SCOPE-010", code(d))


def _v1(status="APPROVED", next_stage="SPECIFICATION_GENERATION", open_rows=(), pse_rows=()):
    return build_scope(version="1.0", status=status, next_stage=next_stage,
                       prev="0.1", open_rows=open_rows, pse_rows=pse_rows)


def test_J_approved_no_record():
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v1.0.md", "content": _v1()},
            scope_files={"scope-v0.1.md": build_scope(version="0.1")})
    check("J/v1.0_APPROVED_no_record__DENY_013", code(d) == "PMO-SCOPE-013", code(d))


def test_K_approved_ok():
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v1.0.md", "content": _v1()},
            scope_files={"scope-v0.1.md": build_scope(version="0.1")},
            approval=APPROVAL_OK)
    check("K/v1.0_APPROVED_with_record_no_blockers__ALLOW", d is None,
          "{} / {}".format(code(d), getattr(d, "message", "")))


def test_L_approval_wrong_version():
    bad = APPROVAL_OK.replace('version: "1.0"', 'version: "0.9"')
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v1.0.md", "content": _v1()},
            scope_files={"scope-v0.1.md": build_scope(version="0.1")}, approval=bad)
    check("L/approval_record_wrong_version__DENY_013", code(d) == "PMO-SCOPE-013", code(d))


def test_M_client_not_confirmed():
    bad = APPROVAL_OK.replace("client_approval: CONFIRMED", "client_approval: PENDING")
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v1.0.md", "content": _v1()},
            scope_files={"scope-v0.1.md": build_scope(version="0.1")}, approval=bad)
    check("M/client_approval_not_CONFIRMED__DENY_013", code(d) == "PMO-SCOPE-013", code(d))


def test_N_blocker_scope_baseline():
    row = ("| SCP-OPEN-001 | YES | What payment providers? | drives effort | "
           "PM to Client | SCOPE_BASELINE | contract TBD |")
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v1.0.md",
                      "content": _v1(open_rows=[row])},
            scope_files={"scope-v0.1.md": build_scope(version="0.1")},
            approval=APPROVAL_OK)
    check("N/approval_with_SCOPE_BASELINE_blocker__DENY_011", code(d) == "PMO-SCOPE-011", code(d))


def test_O_blocker_development():
    row = ("| SCP-OPEN-001 | YES | Which analytics library? | later detail | "
           "PM to Dev | DEVELOPMENT | tbd |")
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v1.0.md",
                      "content": _v1(open_rows=[row])},
            scope_files={"scope-v0.1.md": build_scope(version="0.1")},
            approval=APPROVAL_OK)
    check("O/blocker_gated_DEVELOPMENT_does_not_block__ALLOW", d is None,
          "{} / {}".format(code(d), getattr(d, "message", "")))


def test_P_edit_approved_v1():
    d = run("Edit", {"file_path": "docs/pmo/scope/scope-v1.0.md",
                     "old_string": "requirement 1", "new_string": "requirement one"},
            scope_files={"scope-v1.0.md": _v1()})
    check("P/edit_APPROVED_v1.0__DENY_006", code(d) == "PMO-SCOPE-006", code(d))


def test_Q_filename_version_mismatch():
    doc = build_scope(version="0.3", prev="0.1")  # written to scope-v0.2.md
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.2.md", "content": doc},
            scope_files={"scope-v0.1.md": build_scope(version="0.1")})
    check("Q/filename_v0.2_metadata_v0.3__DENY_005", code(d) == "PMO-SCOPE-005", code(d))


def test_R_unknown_open_stage():
    row = ("| SCP-OPEN-001 | NO | Some question? | context | PM | BANANA_TIME | src |")
    doc = build_scope(version="0.2", status="PM_REVIEWED", prev="0.1", open_rows=[row])
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.2.md", "content": doc},
            scope_files={"scope-v0.1.md": build_scope(version="0.1")})
    check("R/unknown_OPEN_Required_Before_stage__DENY_003",
          code(d) == "PMO-SCOPE-003" and "BANANA_TIME" in getattr(d, "message", ""),
          "{} / {}".format(code(d), getattr(d, "message", "")))


def test_S_task_identifier():
    doc = build_scope(version="0.2", status="PM_REVIEWED", prev="0.1",
                      body_extra="## Appendix\n\n| TASK-001 | build the login screen | dev |\n")
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.2.md", "content": doc},
            scope_files={"scope-v0.1.md": build_scope(version="0.1")})
    check("S/TASK-001_implementation_task__DENY_003",
          code(d) == "PMO-SCOPE-003" and "TASK-001" in getattr(d, "message", ""),
          "{} / {}".format(code(d), getattr(d, "message", "")))


def test_T_unrelated_bash():
    d = run("Bash", {"command": "ls -la /tmp"})
    check("T/unrelated_bash_command__ALLOW", d is None, code(d))


def test_U_internal_error():
    original = mod.validate_required_sections

    def boom(*_a, **_k):
        raise RuntimeError("boom")

    mod.validate_required_sections = boom
    try:
        d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.2.md",
                          "content": build_scope(version="0.2", status="PM_REVIEWED", prev="0.1")},
                scope_files={"scope-v0.1.md": build_scope(version="0.1")})
    finally:
        mod.validate_required_sections = original
    check("U/controlled_validation_exception__DENY_014", code(d) == "PMO-SCOPE-014", code(d))


def test_V_uncontrolled_expansion():
    pse = ["| PSE-001 | Loyalty programme | COMMITTED, IN-SCOPE | - |"]
    doc = build_scope(version="0.2", status="PM_REVIEWED", prev="0.1", pse_rows=pse)
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.2.md", "content": doc},
            scope_files={"scope-v0.1.md": build_scope(version="0.1")})
    check("V/PSE_committed_without_disposition__DENY_012", code(d) == "PMO-SCOPE-012", code(d))


def test_W_retired_id_reused():
    v01 = build_scope(version="0.1")
    v02 = build_scope(version="0.2", prev="0.1",
                      body_extra="## Retirements\n\n| SCP-REQ-003 | old requirement | retired in v0.2 |\n")
    v03 = build_scope(version="0.3", prev="0.2",
                      body_extra="## Appendix\n\n| SCP-REQ-003 | brand-new unrelated requirement | a | INT-REQ-002 |\n")
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.3.md", "content": v03},
            scope_files={"scope-v0.1.md": v01, "scope-v0.2.md": v02})
    check("W/retired_SCP-REQ_reused__DENY_009", code(d) == "PMO-SCOPE-009", code(d))


# --------------------------------------------------------------------------- #
# X - AB : OPEN identifier provenance  (PMO-SCOPE-015)
# --------------------------------------------------------------------------- #

INTENT_WITH_OPEN = INTENT_MD + (
    "\n## 11. Open Questions\n\n"
    "| ID | Blocking | Question | Why it matters | Owner | Required Before | Source |\n"
    "|---|---|---|---|---|---|---|\n"
    "| OPEN-002 | YES | Which payment providers? | drives effort | PM to Client "
    "| SCOPE_BASELINE | contract TBD |\n"
    "| OPEN-003 | YES | Which framework? | architecture basis | PM to Dev "
    "| SCOPE_BASELINE | note |\n"
)


def test_X_carried_open_keeps_intent_id():
    row = ("| OPEN-002 | YES | Which payment providers? | drives effort | "
           "PM to Client | SCOPE_BASELINE | carried from Intent v1.0 |")
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.1.md",
                      "content": build_scope(version="0.1", open_rows=[row])},
            intent=INTENT_WITH_OPEN)
    check("X/carried_Intent_OPEN-002_kept_as_OPEN-002__ALLOW", d is None,
          "{} / {}".format(code(d), getattr(d, "message", "")))


def test_Y_carried_open_renamed_to_scp_open():
    row = ("| SCP-OPEN-002 | YES | Which payment providers? | drives effort | "
           "PM to Client | SCOPE_BASELINE | carried from Intent OPEN-002 |")
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.1.md",
                      "content": build_scope(version="0.1", open_rows=[row])},
            intent=INTENT_WITH_OPEN)
    check("Y/carried_Intent_OPEN-002_renamed_SCP-OPEN-002__DENY_015",
          code(d) == "PMO-SCOPE-015",
          "{} / {}".format(code(d), getattr(d, "message", "")))


def test_Z_new_scope_native_scp_open():
    row = ("| SCP-OPEN-001 | NO | Is guest checkout allowed? | first raised "
           "while detailing checkout | PM to Client | SPECIFICATION_GENERATION "
           "| scope elicitation |")
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.1.md",
                      "content": build_scope(version="0.1", open_rows=[row])},
            intent=INTENT_WITH_OPEN)
    check("Z/new_Scope-native_SCP-OPEN-001_no_Intent_origin__ALLOW", d is None,
          "{} / {}".format(code(d), getattr(d, "message", "")))


def test_AA_open_referenced_after_one_definition():
    row = ("| OPEN-002 | YES | Which payment providers? | drives effort | "
           "PM to Client | SCOPE_BASELINE | contract |")
    extra = ("## Appendix\n\nSee OPEN-002 for the payment decision. OPEN-002 "
             "also gates checkout. Resolve OPEN-002 before the Scope baseline.\n")
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.1.md",
                      "content": build_scope(version="0.1", open_rows=[row],
                                             body_extra=extra)},
            intent=INTENT_WITH_OPEN)
    check("AA/OPEN-002_one_definition_many_references__ALLOW", d is None,
          "{} / {}".format(code(d), getattr(d, "message", "")))


def test_AB_retired_or_absent_intent_open_reused():
    row = ("| OPEN-017 | NO | New Scope-only staffing question? | not from the "
           "Intent | PM | SPECIFICATION_GENERATION | scope elicitation |")
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.1.md",
                      "content": build_scope(version="0.1", open_rows=[row])},
            intent=INTENT_WITH_OPEN)
    check("AB/bare_OPEN-017_with_no_Intent_origin__DENY_015",
          code(d) == "PMO-SCOPE-015",
          "{} / {}".format(code(d), getattr(d, "message", "")))


def test_AC_provenance_skipped_without_intent_open():
    # Intent fixture has no OPEN definitions -> provenance cannot be established.
    row = ("| SCP-OPEN-001 | NO | Some question? | context | PM | "
           "SPECIFICATION_GENERATION | src |")
    d = run("Write", {"file_path": "docs/pmo/scope/scope-v0.1.md",
                      "content": build_scope(version="0.1", open_rows=[row])})
    check("AC/no_Intent_OPEN_defs_provenance_skipped__ALLOW", d is None,
          "{} / {}".format(code(d), getattr(d, "message", "")))


# --------------------------------------------------------------------------- #

def main():
    test_units()
    for fn in (test_A_valid_draft_create, test_B_incomplete_progressive,
               test_C_fr_definition, test_D_nfr_definition,
               test_E_duplicate_scp_req, test_F_missing_traceability,
               test_G_edit_historical, test_H_valid_progression,
               test_I_invalid_progression, test_J_approved_no_record,
               test_K_approved_ok, test_L_approval_wrong_version,
               test_M_client_not_confirmed, test_N_blocker_scope_baseline,
               test_O_blocker_development, test_P_edit_approved_v1,
               test_Q_filename_version_mismatch, test_R_unknown_open_stage,
               test_S_task_identifier, test_T_unrelated_bash,
               test_U_internal_error, test_V_uncontrolled_expansion,
               test_W_retired_id_reused, test_X_carried_open_keeps_intent_id,
               test_Y_carried_open_renamed_to_scp_open,
               test_Z_new_scope_native_scp_open,
               test_AA_open_referenced_after_one_definition,
               test_AB_retired_or_absent_intent_open_reused,
               test_AC_provenance_skipped_without_intent_open):
        fn()
    total = len(_RESULTS)
    failed = [n for n, ok in _RESULTS if not ok]
    print("\n{}/{} passed".format(total - len(failed), total))
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
