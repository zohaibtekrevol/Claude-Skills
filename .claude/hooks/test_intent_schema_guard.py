#!/usr/bin/env python3
"""Smoke tests for .claude/hooks/intent-schema-guard.py.

Stdlib only. Run:  python3 .claude/hooks/test_intent_schema_guard.py
Exit code 0 = all pass, 1 = at least one failure.

Covers:
  * existing behaviour (DRAFT editable, VALIDATED immutable, FR/NFR prohibited,
    PM approval required, project identity, source register, fail closed),
  * DEFECT 1 - robust OPEN-record parser (table rows, subsections, long
    multi-line records; no fixed lookahead; repeated references ignored),
  * DEFECT 2 - stage-aware blocking (future-gate blockers do not stop Intent
    validation; current-gate blockers do; unknown Required Before -> 007).
"""

import importlib.util
import json
import os
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_PATH = os.path.join(HERE, "intent-schema-guard.py")

_spec = importlib.util.spec_from_file_location("intent_schema_guard", HOOK_PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# --------------------------------------------------------------------------- #
# test plumbing
# --------------------------------------------------------------------------- #

_RESULTS = []


def check(name, ok, detail=""):
    _RESULTS.append((name, bool(ok)))
    line = "PASS" if ok else "FAIL"
    print("{:4}  {}{}".format(line, name, "" if ok else "   :: " + detail))


def code_of(decision):
    return getattr(decision, "code", None)


# --------------------------------------------------------------------------- #
# document builders
# --------------------------------------------------------------------------- #

SECTIONS = (
    "1. Client Vision", "2. Business Problem", "3. Overall Client Goal",
    "4. Proposed Product Outcome", "5. Users, Actors and Systems",
    "6. High-Level Product Requirements", "7. Constraints",
    "8. Explicitly Out of Scope", "9. Dependencies", "10. Assumptions",
    "11. Open Questions", "12. Contradictions / Source Conflicts",
    "13. Risks Carried Into Requirement Gathering", "14. Source Register",
    "15. Intent Validation Summary", "16. Acceptance",
)

_GOOD_SOURCE_ROW = (
    "| SRC-001 | docs/pmo/sources/contract/agreement.pdf | Executed contract "
    "| 2026-05-08 | PRIMARY | scope, commercials |"
)
_WEAK_SOURCE_ROW = "| SRC-001 | intent.md | the intent itself | - | low | n/a |"

OPEN_HEADER = (
    "| ID | Blocking | Question | Why it matters | Owner | Required Before | Source |\n"
    "|---|---|---|---|---|---|---|"
)


def orow(oid="OPEN-001", blocking="NO", question="What is X?",
         why="it matters", owner="PM to Client", rb="Scope Baseline",
         source="SRC-004"):
    return "| {} | {} | {} | {} | {} | {} | {} |".format(
        oid, blocking, question, why, owner, rb, source)


def open_table(rows):
    return "### Items\n\n" + OPEN_HEADER + "\n" + "\n".join(rows)


def build_doc(status="DRAFT", project_id="SMART-BASKET",
              open_section="_No open items._", source_row=_GOOD_SOURCE_ROW,
              next_stage="REQUIREMENT_GATHERING"):
    dc = "\n".join([
        "| Field | Value |",
        "|---|---|",
        "| Project | Smart Basket |",
        "| Project ID | {} |".format(project_id),
        "| Client | Smart Basket / eBasket KSA |",
        "| Date | 2026-09-10 |",
        "| Intent Version | 0.1 |",
        "| Status | {} |".format(status),
        "| Repository | Bitbucket - unverified |",
        "| Source Count | 1 |",
        "| Next Stage | {} |".format(next_stage),
    ])
    parts = ["# Intent: Smart Basket", "", dc, ""]
    for s in SECTIONS:
        parts.append("## " + s)
        if s.startswith("11."):
            parts.append(open_section)
        elif s.startswith("14."):
            parts.append("| Source ID | Reference | Type | Date | Authority | How used |")
            parts.append("|---|---|---|---|---|---|")
            parts.append(source_row)
        else:
            parts.append("Body of section {}.".format(s))
        parts.append("")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# process() harness (temp repo)
# --------------------------------------------------------------------------- #

def run_process(tool_name, tool_input, on_disk=None, config=True, approval=None):
    tmp = tempfile.mkdtemp(prefix="intent-hook-test-")
    try:
        os.makedirs(os.path.join(tmp, ".pmo"), exist_ok=True)
        os.makedirs(os.path.join(tmp, "docs", "pmo", "intent"), exist_ok=True)
        if config:
            with open(os.path.join(tmp, ".pmo", "project-config.yaml"), "w") as fh:
                fh.write(
                    'project:\n'
                    '  id: "SMART-BASKET"\n'
                    '  name: "Smart Basket"\n'
                    '  client: "Smart Basket / eBasket KSA"\n'
                )
        intent_abs = os.path.join(tmp, "docs", "pmo", "intent", "intent.md")
        if on_disk is not None:
            with open(intent_abs, "w") as fh:
                fh.write(on_disk)
        if approval is not None:
            os.makedirs(os.path.join(tmp, ".pmo", "approvals"), exist_ok=True)
            with open(os.path.join(tmp, ".pmo", "approvals",
                                   "intent-approval.yaml"), "w") as fh:
                fh.write(approval)
        ti = dict(tool_input)
        if tool_name in ("Write", "Edit", "MultiEdit") and "file_path" not in ti:
            ti["file_path"] = intent_abs
        payload = {"tool_name": tool_name, "tool_input": ti, "cwd": tmp}
        return mod.process(payload)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


APPROVAL_OK = (
    'decision: "APPROVED"\n'
    'approval_source: "PM_EXPLICIT"\n'
    'artifact: "docs/pmo/intent/intent.md"\n'
    'approved_by: "Muneeb"\n'
    'version: "0.1"\n'
)


# --------------------------------------------------------------------------- #
# EXISTING BEHAVIOUR
# --------------------------------------------------------------------------- #

def test_existing_behaviour():
    # DRAFT editable - a Write of an incomplete DRAFT is allowed.
    d = run_process("Write", {"content": "# Intent\n\n| Status | DRAFT |\n"
                              "| Project | Smart Basket |\n"
                              "| Project ID | SMART-BASKET |\n"
                              "| Client | Smart Basket / eBasket KSA |\n"})
    check("existing/draft_editable", d is None, "got {}".format(code_of(d)))

    # DRAFT editable even with a messy / incomplete OPEN table (no finalisation).
    messy = build_doc(status="DRAFT", open_section=open_table(
        [orow("OPEN-%03d" % i, "NO") for i in range(1, 13)]
        + ["| OPEN-999 | | | | | | |"]))
    d = run_process("Write", {"content": messy})
    check("existing/draft_editable_messy_open", d is None,
          "got {}".format(code_of(d)))

    # VALIDATED immutable.
    d = run_process("Edit",
                    {"old_string": "Body of section 9. Dependencies.",
                     "new_string": "changed"},
                    on_disk=build_doc(status="VALIDATED"))
    check("existing/validated_immutable", code_of(d) == "PMO-INTENT-009",
          "got {}".format(code_of(d)))

    # FR/NFR prohibited.
    d = run_process("Write", {"content": build_doc(status="DRAFT").replace(
        "Body of section 6. High-Level Product Requirements.",
        "FR-999 leaked in")})
    check("existing/fr_nfr_prohibited", code_of(d) == "PMO-INTENT-004",
          "got {}".format(code_of(d)))

    # PM approval required for VALIDATED (no approval record on disk).
    d = run_process("Write",
                    {"content": build_doc(status="VALIDATED")},
                    on_disk=build_doc(status="DRAFT"))
    check("existing/pm_approval_required", code_of(d) == "PMO-INTENT-011",
          "got {}".format(code_of(d)))

    # Project identity mismatch.
    d = run_process("Write", {"content": build_doc(status="DRAFT",
                                                   project_id="WRONG-ID")})
    check("existing/project_identity", code_of(d) == "PMO-INTENT-010",
          "got {}".format(code_of(d)))

    # Source register has no external source (finalisation).
    d = run_process("Write", {"content": build_doc(status="PM_REVIEWED",
                                                   source_row=_WEAK_SOURCE_ROW)})
    check("existing/source_validation", code_of(d) == "PMO-INTENT-006",
          "got {}".format(code_of(d)))

    # Fail closed - an internal error becomes PMO-INTENT-012.
    original = mod.parse_doc_control

    def boom(*_a, **_k):
        raise RuntimeError("boom")

    mod.parse_doc_control = boom
    try:
        d = run_process("Write", {"content": build_doc(status="DRAFT")})
    finally:
        mod.parse_doc_control = original
    check("existing/fail_closed", code_of(d) == "PMO-INTENT-012",
          "got {}".format(code_of(d)))

    # Unrelated tool call is ignored.
    d = run_process("Bash", {"command": "ls -la"})
    check("existing/unrelated_ignored", d is None, "got {}".format(code_of(d)))

    # A clean full DRAFT with a well-formed OPEN table passes light checks.
    d = run_process("Write", {"content": build_doc(
        status="DRAFT", open_section=open_table([orow("OPEN-001", "YES",
                                                      rb="Scope Baseline")]))})
    check("existing/clean_draft_ok", d is None, "got {}".format(code_of(d)))


# --------------------------------------------------------------------------- #
# DEFECT 1 - OPEN parser robustness
# --------------------------------------------------------------------------- #

LONG_MULTILINE_OPEN = """### Items

#### OPEN-001 - Which fulfilment SLAs apply to corporate credit orders?

Context: several considerations are captured here so this record runs well
past any fixed lookahead window:

- warehouse pick and pack timing
- courier hand-off windows
- regional cut-off times
- weekend handling
- public-holiday handling
- escalation path when an SLA is missed
- reporting expectations
- monthly review cadence
- penalties, if any

Owner: PM to Client
Blocking: NO
Required Before: Development
Source: SRC-004 discovery discussion
"""

MULTILINE_MISSING_RB = """### Items

#### OPEN-001 - What is the credit limit policy?

Owner: PM to Client
Blocking: NO
Source: SRC-004
"""

TABLE_NO_OWNER = (
    "### Items\n\n"
    "| ID | Blocking | Question | Why | Required Before | Source |\n"
    "|---|---|---|---|---|---|\n"
    "| OPEN-001 | NO | What? | why | Scope Baseline | SRC-001 |"
)

TABLE_NO_BLOCKING = (
    "### Items\n\n"
    "| ID | Question | Why | Owner | Required Before | Source |\n"
    "|---|---|---|---|---|---|\n"
    "| OPEN-001 | What? | why | PM to Client | Scope Baseline | SRC-001 |"
)


def test_defect1_parser():
    # (a) long multi-line record > 10 lines - PASS because every field exists.
    doc = build_doc(open_section=LONG_MULTILINE_OPEN)
    check("defect1/a_long_multiline_pass",
          mod.validate_open_items(doc) is None,
          "got {}".format(code_of(mod.validate_open_items(doc))))

    # (b) plain Markdown table row - PASS.
    doc = build_doc(open_section=open_table([orow("OPEN-001", "NO")]))
    check("defect1/b_table_row_pass",
          mod.validate_open_items(doc) is None,
          "got {}".format(code_of(mod.validate_open_items(doc))))

    # regression: a row far below its header (was a 6-line-lookahead false
    # positive) - must now PASS.
    rows = [orow("OPEN-%03d" % i, "NO") for i in range(1, 16)]
    doc = build_doc(open_section=open_table(rows))
    d = mod.validate_open_items(doc)
    check("defect1/regression_row_far_from_header", d is None,
          "got {}".format(code_of(d)))
    recs = mod.parse_open_records(doc)
    check("defect1/regression_all_rows_parsed", len(recs) == 15,
          "parsed {}".format(len(recs)))

    # individual OPEN subsection - PASS.
    doc = build_doc(open_section=LONG_MULTILINE_OPEN.replace(
        "Required Before: Development", "Required Before: Requirement Gathering"))
    check("defect1/subsection_pass", mod.validate_open_items(doc) is None)

    # repeated reference to an OPEN id is not a second definition.
    body = open_table([orow("OPEN-001", "NO")]) + \
        "\n\nOPEN-001 is also discussed under CONFLICT-002 above."
    doc = build_doc(open_section=body)
    recs = mod.parse_open_records(doc)
    check("defect1/repeated_reference_ignored", len(recs) == 1,
          "parsed {}".format(len(recs)))

    # (h) missing Owner -> DENY 007 naming Owner.
    d = mod.validate_open_items(build_doc(open_section=TABLE_NO_OWNER))
    check("defect1/h_missing_owner_denies_007",
          code_of(d) == "PMO-INTENT-007" and "Owner" in d.message,
          "got {} / {}".format(code_of(d), getattr(d, "message", "")))

    # (i) missing Blocking -> DENY 007 naming Blocking.
    d = mod.validate_open_items(build_doc(open_section=TABLE_NO_BLOCKING))
    check("defect1/i_missing_blocking_denies_007",
          code_of(d) == "PMO-INTENT-007" and "Blocking" in d.message,
          "got {} / {}".format(code_of(d), getattr(d, "message", "")))

    # multi-line record missing Required Before -> DENY 007.
    d = mod.validate_open_items(build_doc(open_section=MULTILINE_MISSING_RB))
    check("defect1/multiline_missing_required_before_denies_007",
          code_of(d) == "PMO-INTENT-007" and "Required Before" in d.message,
          "got {} / {}".format(code_of(d), getattr(d, "message", "")))


# --------------------------------------------------------------------------- #
# DEFECT 2 - stage-aware blocking
# --------------------------------------------------------------------------- #

def test_defect2_stage_aware():
    # normalize_stage spelling variants.
    ns = mod.normalize_stage
    checks = {
        "Intent Validation": "INTENT_VALIDATION",
        "Requirements Gathering": "REQUIREMENT_GATHERING",
        "requirement-gathering": "REQUIREMENT_GATHERING",
        "Scope Baseline": "SCOPE_BASELINE",
        "scope": "SCOPE_BASELINE",
        "Specification Generation": "SPECIFICATION_GENERATION",
        "specs": "SPECIFICATION_GENERATION",
        "Development": "DEVELOPMENT",
        "dev": "DEVELOPMENT",
        "QA": "QA",
        "user acceptance testing": "UAT",
        "Deployment": "DEPLOYMENT",
        "go live": "DEPLOYMENT",
        "Scope Baseline gate": "SCOPE_BASELINE",
    }
    ok = all(ns(k) == v for k, v in checks.items())
    check("defect2/normalize_stage_variants", ok,
          {k: ns(k) for k, v in checks.items() if ns(k) != v})
    check("defect2/normalize_stage_unknown_is_none",
          ns("Banana O'Clock") is None and ns("Artifact Publishing") is None)

    def gate(rb, blocking="YES"):
        doc = build_doc(open_section=open_table([orow("OPEN-001", blocking, rb=rb)]))
        return mod.validate_blocking_open_gate(doc)

    # (c) Scope Baseline - does NOT block Intent validation.
    check("defect2/c_scope_baseline_not_block", gate("Scope Baseline") is None)
    # (d) Development - does NOT block Intent validation.
    check("defect2/d_development_not_block", gate("Development") is None)
    # extra future gates.
    check("defect2/future_specs_not_block",
          gate("Specification Generation") is None)
    check("defect2/future_uat_not_block", gate("UAT") is None)
    check("defect2/future_deployment_not_block", gate("Deployment") is None)

    # (e) Intent Validation - BLOCKS.
    d = gate("Intent Validation")
    check("defect2/e_intent_validation_blocks", code_of(d) == "PMO-INTENT-013",
          "got {}".format(code_of(d)))
    # (f) Requirement Gathering - BLOCKS.
    d = gate("Requirement Gathering")
    check("defect2/f_requirement_gathering_blocks",
          code_of(d) == "PMO-INTENT-013", "got {}".format(code_of(d)))

    # Blocking = NO at a current gate does not block.
    check("defect2/blocking_no_at_current_gate_ok",
          gate("Requirement Gathering", blocking="NO") is None)

    # (g) unknown Required Before -> DENY 007 reporting the value.
    d = mod.validate_open_items(build_doc(
        open_section=open_table([orow("OPEN-001", "NO", rb="Banana Time")])))
    check("defect2/g_unknown_stage_denies_007",
          code_of(d) == "PMO-INTENT-007" and "Banana Time" in d.message,
          "got {} / {}".format(code_of(d), getattr(d, "message", "")))

    # end-to-end: VALIDATED write blocked by a current-gate YES blocker.
    d = run_process(
        "Write",
        {"content": build_doc(status="VALIDATED", open_section=open_table(
            [orow("OPEN-001", "YES", rb="Requirement Gathering")]))},
        on_disk=build_doc(status="DRAFT"), approval=APPROVAL_OK)
    check("defect2/e2e_validated_blocked_current_gate",
          code_of(d) == "PMO-INTENT-013", "got {}".format(code_of(d)))

    # end-to-end: VALIDATED write ALLOWED with a future-gate YES blocker open.
    d = run_process(
        "Write",
        {"content": build_doc(status="VALIDATED", open_section=open_table(
            [orow("OPEN-001", "YES", rb="Scope Baseline"),
             orow("OPEN-002", "YES", rb="Development")]))},
        on_disk=build_doc(status="DRAFT"), approval=APPROVAL_OK)
    check("defect2/e2e_validated_allowed_future_gate", d is None,
          "got {} / {}".format(code_of(d), getattr(d, "message", "")))


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def main():
    test_existing_behaviour()
    test_defect1_parser()
    test_defect2_stage_aware()
    total = len(_RESULTS)
    failed = [n for n, ok in _RESULTS if not ok]
    print("\n{}/{} passed".format(total - len(failed), total))
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
