#!/usr/bin/env python3
"""PMO specs-structural-repair - the deterministic transaction orchestrator
for the STRUCTURAL_REPAIR Specs-write authorization category.

Role boundary
---------------
STRUCTURAL_REPAIR restores canonical structural/schema completeness to a
Specs artifact that has **never been approved** - it is never a content,
scope, or approval decision. See
``.claude/lib/specs_structural_repair_core.py`` (this CLI's sole source of
validation and derivation logic) for the full architecture note, including
the exact, narrow permitted-repair-section whitelist and the independent
content-preservation guarantee every write re-checks regardless of how the
repair content was derived.

Flow
------
::

    specs-structural-repair.py begin --reason "..."
        -> runs the full BEGIN precondition checklist (read-only) against
           the CURRENT on-disk specs.md; on PASS, writes
           .pmo/specs-structural-repair-transaction.json
        |
        v
    specs-structural-repair.py finalize
        -> re-validates everything from disk, computes the repair content,
           proves it preserves every existing byte and full_spec_validation
           actually passes on the result, then writes and removes the marker

``status`` is available at any point and is always pure read-only.

Security boundary
-------------------
This CLI runs via Bash - entirely outside Claude Code's PreToolUse hook
system. ``change_request_incorporation_core.py``'s own approved-baseline
protection rule for Claude's own Write/Edit tool calls is **not modified,
weakened, or special-cased anywhere** - this is a deliberate, separate,
equally strict enforcement point, not a bypass of it. The existence of
``.pmo/specs-structural-repair-transaction.json`` is NOT itself
authorization for anything.

Runtime marker only
----------------------
``.pmo/specs-structural-repair-transaction.json`` is a runtime transaction
artifact, always removed on a clean ``finalize``; ``.pmo/`` is already
untracked by this repository's own ``.gitignore``.

Exit code: 0 for every non-exceptional result (including BLOCKED), 1 only
for a command-line usage error. The JSON result's own ``status`` field is
the actual outcome.

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

from specs_structural_repair_core import (  # noqa: E402
    build_marker_data,
    deny,
    finalize_transaction,
    marker_abspath,
    marker_status,
    reconcile_transaction,
    run_begin_preconditions,
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
    return "SPECREPX-{}-{}".format(
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:8])


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_begin(root, reason, dry_run=False):
    result = _new_result("begin")
    state, existing_marker, err = marker_status(root)
    if state == "OPEN":
        result["marker"] = existing_marker
        return _fail(result, deny(
            "PMO-SPEC-REPAIR-014",
            "a STRUCTURAL_REPAIR transaction is already {} (transaction_id "
            "{}) - use `status`/`finalize` to resume it, or resolve it "
            "manually before starting a new one.".format(
                existing_marker.get("status"), existing_marker.get("transaction_id"))))
    if state in ("INVALID", "WRONG_PROJECT"):
        return _fail(result, deny("PMO-SPEC-REPAIR-015", err))

    plan, decision = run_begin_preconditions(root, reason)
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
        result["status"] = "NO_TRANSACTION"
        return result
    if state in ("INVALID", "WRONG_PROJECT"):
        result["status"] = "INVALID_MARKER"
        result["decision"] = {"code": "PMO-SPEC-REPAIR-015", "message": err}
        return result
    result["marker"] = data
    result["status"] = data.get("status")
    return result


def cmd_validate(root):
    result = _new_result("validate")
    state, data, err = marker_status(root)
    if state == "ABSENT":
        return _fail(result, deny(
            "PMO-SPEC-REPAIR-016", "no STRUCTURAL_REPAIR transaction is in progress."),
            status="NO_TRANSACTION")
    if state in ("INVALID", "WRONG_PROJECT"):
        return _fail(result, deny("PMO-SPEC-REPAIR-015", err))
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
            "PMO-SPEC-REPAIR-016", "no STRUCTURAL_REPAIR transaction is in progress."),
            status="NO_TRANSACTION")
    if state in ("INVALID", "WRONG_PROJECT"):
        return _fail(result, deny("PMO-SPEC-REPAIR-015", err))
    result["marker"] = data
    report, decision = finalize_transaction(root, data)
    if decision is not None:
        return _fail(result, decision, status="RECOVERY_REQUIRED")
    result["report"] = report
    result["status"] = "REPAIRED"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog="specs-structural-repair.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_begin = sub.add_parser("begin")
    p_begin.add_argument("--reason", required=True)
    p_begin.add_argument("--dry-run", action="store_true")
    p_begin.add_argument("--root", default=None)

    for name in ("status", "validate", "finalize"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=None)

    args = parser.parse_args(argv)
    root = args.root or locate_project_root(os.getcwd())

    if args.command == "begin":
        result = cmd_begin(root, args.reason, dry_run=args.dry_run)
    elif args.command == "status":
        result = cmd_status(root)
    elif args.command == "validate":
        result = cmd_validate(root)
    elif args.command == "finalize":
        result = cmd_finalize(root)
    else:  # pragma: no cover
        parser.error("unknown command")
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
