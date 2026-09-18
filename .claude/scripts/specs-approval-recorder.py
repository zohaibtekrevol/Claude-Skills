#!/usr/bin/env python3
"""PMO specs-approval-recorder - the deterministic Specs PM-approval
transaction orchestrator.

Role boundary
---------------
Recording that a PM has approved a Specs baseline is a PROCESS action, not a
semantic one: it never decides whether the Specs content is right, only
whether an explicit approval given for it is faithfully and atomically
recorded. This CLI owns TRANSACTION EXECUTION only - see
``.claude/lib/specs_approval_core.py`` (this CLI's sole source of validation
logic) for the full architecture note, including the exact scope boundary
(it never promotes Spec Status, never bumps Spec Version, never touches
FR/NFR/BR content).

Flow
------
::

    specs-approval-recorder.py begin --approved-by "Muhammad Faizan" \\
        --decision-date 2026-09-19 --statement "..."
        -> runs the full BEGIN precondition checklist (read-only) against
           the CURRENT on-disk specs.md; on PASS, writes
           .pmo/specs-approval-transaction.json
        |
        v
    specs-approval-recorder.py finalize
        -> re-validates everything from disk (never trusts a stale prior
           `validate`), and only on a full PASS writes
           .pmo/approvals/specs-approval.yaml followed by the single
           computed specs.md edit pair (Execution Authorized flip + one
           appended Change History row), then removes the marker

``status`` is available at any point and is always pure read-only. There is
no intermediate Skill-authored content step between `begin` and `finalize`
(the same reason Intent approval doesn't need one either) - a Specs
approval's content is fully determined by the explicit fields supplied at
`begin`.

Security boundary
-------------------
This CLI runs via Bash - entirely outside Claude Code's PreToolUse hook
system. The existence of ``.pmo/specs-approval-transaction.json`` is NOT
itself authorization for anything: every command here independently
re-runs the same deterministic checks a Write/Edit-time guard would apply
(reusing ``specs-governance-guard.py``'s own ``full_spec_validation``), and
``finalize`` fails closed on any exception, on a moved specs.md hash, or on
a computed edit that touches anything beyond the approval-only diff.

Runtime marker only
----------------------
``.pmo/specs-approval-transaction.json`` is a runtime transaction artifact,
not permanent framework or project content: always removed on a clean
``finalize``, and ``.pmo/`` is already untracked by this repository's own
``.gitignore``.

Exit code: 0 for every non-exceptional result (including BLOCKED - a valid,
correctly-reported outcome, not a CLI failure), 1 only for a command-line
usage error. The JSON result's own ``status`` field is the actual outcome.

Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from specs_approval_core import (  # noqa: E402
    build_marker_data,
    deny,
    finalize_transaction,
    load_specs_approval,
    marker_abspath,
    marker_status,
    parse_spec_doc_control,
    read_text,
    reconcile_transaction,
    run_begin_preconditions,
    specs_abspath,
    write_text,
)
from intent_approval_core import locate_project_root  # noqa: E402


def _new_result(command):
    return {"command": command, "status": None, "decision": None,
           "plan": None, "marker": None, "report": None}


def _fail(result, decision, status="BLOCKED"):
    result["status"] = status
    result["decision"] = {"code": decision.code, "message": decision.message}
    return result


def _new_transaction_id():
    return "SPECAPX-{}-{}".format(
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:8])


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_begin(root, approved_by, decision_date, statement=None, dry_run=False):
    result = _new_result("begin")
    state, existing_marker, err = marker_status(root)
    if state == "OPEN":
        result["marker"] = existing_marker
        return _fail(result, deny(
            "PMO-SPEC-APPROVAL-016",
            "a transaction is already {} for Spec Version {} (transaction_id "
            "{}) - use `status`/`finalize` to resume it, or resolve it "
            "manually before starting a new one.".format(
                existing_marker.get("status"), existing_marker.get("spec_version"),
                existing_marker.get("transaction_id"))))
    if state in ("INVALID", "WRONG_PROJECT"):
        return _fail(result, deny("PMO-SPEC-APPROVAL-017", err))

    plan, decision = run_begin_preconditions(
        root, approved_by, decision_date, approval_statement=statement)
    if decision is not None:
        return _fail(result, decision)

    result["plan"] = plan
    if dry_run:
        result["status"] = "DRY_RUN_PASS"
        return result

    marker_data = build_marker_data(plan, _new_transaction_id(), _now_iso())
    write_text(marker_abspath(root), json.dumps(marker_data, indent=2))
    result["marker"] = marker_data
    result["status"] = "ACTIVE"
    return result


def cmd_status(root):
    result = _new_result("status")
    state, data, err = marker_status(root)
    if state == "ABSENT":
        approval_data, approval_err = load_specs_approval(root)
        result["status"] = "APPROVED" if (approval_data and not approval_err) \
            else "NO_TRANSACTION"
        result["report"] = approval_data
        return result
    if state in ("INVALID", "WRONG_PROJECT"):
        result["status"] = "INVALID_MARKER"
        result["decision"] = {"code": "PMO-SPEC-APPROVAL-017", "message": err}
        return result
    result["marker"] = data
    result["status"] = data.get("status")
    return result


def cmd_validate(root):
    result = _new_result("validate")
    state, data, err = marker_status(root)
    if state == "ABSENT":
        return _fail(result, deny(
            "PMO-SPEC-APPROVAL-018", "no specs-approval transaction is in progress."),
            status="NO_TRANSACTION")
    if state in ("INVALID", "WRONG_PROJECT"):
        return _fail(result, deny("PMO-SPEC-APPROVAL-017", err))
    result["marker"] = data
    plan, decision = reconcile_transaction(root, data)
    if decision is not None:
        return _fail(result, decision, status="RECOVERY_REQUIRED")
    result["plan"] = plan
    result["status"] = "VALID"
    return result


def cmd_finalize(root):
    result = _new_result("finalize")
    state, data, err = marker_status(root)
    if state == "ABSENT":
        return _fail(result, deny(
            "PMO-SPEC-APPROVAL-018", "no specs-approval transaction is in progress."),
            status="NO_TRANSACTION")
    if state in ("INVALID", "WRONG_PROJECT"):
        return _fail(result, deny("PMO-SPEC-APPROVAL-017", err))
    result["marker"] = data
    report, decision = finalize_transaction(root, data)
    if decision is not None:
        return _fail(result, decision, status="RECOVERY_REQUIRED")
    result["report"] = report
    result["status"] = "APPROVED"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog="specs-approval-recorder.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_begin = sub.add_parser("begin")
    p_begin.add_argument("--approved-by", required=True)
    p_begin.add_argument("--decision-date", required=True)
    p_begin.add_argument("--statement", default=None)
    p_begin.add_argument("--dry-run", action="store_true")
    p_begin.add_argument("--root", default=None)

    for name in ("status", "validate", "finalize"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=None)

    args = parser.parse_args(argv)
    root = args.root or locate_project_root(os.getcwd())

    if args.command == "begin":
        result = cmd_begin(root, args.approved_by, args.decision_date,
                          statement=args.statement, dry_run=args.dry_run)
    elif args.command == "status":
        result = cmd_status(root)
    elif args.command == "validate":
        result = cmd_validate(root)
    elif args.command == "finalize":
        result = cmd_finalize(root)
    else:  # pragma: no cover - argparse enforces choices
        parser.error("unknown command")
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
