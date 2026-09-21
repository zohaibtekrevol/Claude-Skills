#!/usr/bin/env python3
"""PMO specs-schema-migration - deterministic transaction orchestrator for
PRE_BASELINE_SCHEMA_MIGRATION: a governed, pre-approval-only REPRESENTATION
migration of a provisional Specs artifact written in an older generator layout
(heading-only ID/Title, several fields on one line) to the canonical layout the
current Specs parser reads. Never content regeneration, never a CR.

All logic lives in ``.claude/lib/specs_schema_migration_core.py`` (which reuses
the STRUCTURAL_REPAIR primitives rather than re-implementing them).

    specs-schema-migration.py begin --reason "..." [--dry-run]
        read-only precondition + candidate + equivalence + full validation;
        on PASS writes .pmo/specs-schema-migration-transaction.json
    specs-schema-migration.py finalize
        re-derives everything from disk, proves semantic equivalence and
        full_spec_validation on the COMPLETE candidate, then writes atomically
    specs-schema-migration.py abort --reason "..."
        clears a marker that did not finalize (hash-verified; never touches
        specs.md or approval state)
    specs-schema-migration.py status | validate      (read-only)

Runs via Bash, outside the PreToolUse hook system, exactly like the other
transaction CLIs; approved-baseline protection for Write/Edit is untouched and
the marker is never authorization. Automatic orchestration remains disabled.
Exit code 0 for every non-exceptional result; the JSON ``status`` is the outcome.
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

from specs_schema_migration_core import (  # noqa: E402
    abort_transaction,
    build_marker_data,
    finalize_transaction,
    marker_abspath,
    marker_status,
    reconcile_transaction,
    run_begin_preconditions,
)
from specs_structural_repair_core import deny, write_text  # noqa: E402
from intent_approval_core import locate_project_root  # noqa: E402


def _new_result(command):
    return {"command": command, "status": None, "decision": None,
           "plan": None, "marker": None, "report": None}


def _fail(result, decision, status="BLOCKED"):
    result["status"] = status
    result["decision"] = {"code": decision.code, "message": decision.message}
    return result


def _new_transaction_id():
    return "SPECMIGX-{}-{}".format(
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:8])


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_begin(root, reason, dry_run=False):
    result = _new_result("begin")
    state, existing_marker, err = marker_status(root)
    if state == "OPEN":
        result["marker"] = existing_marker
        return _fail(result, deny(
            "PMO-SCHEMA-MIG-020",
            "a schema-migration transaction is already {} (transaction_id "
            "{}) - use `status`/`finalize` to resume it, or resolve it "
            "manually before starting a new one.".format(
                existing_marker.get("status"), existing_marker.get("transaction_id"))))
    if state in ("INVALID", "WRONG_PROJECT"):
        return _fail(result, deny("PMO-SCHEMA-MIG-021", err))

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
        result["decision"] = {"code": "PMO-SCHEMA-MIG-021", "message": err}
        return result
    result["marker"] = data
    result["status"] = data.get("status")
    return result


def cmd_validate(root):
    result = _new_result("validate")
    state, data, err = marker_status(root)
    if state == "ABSENT":
        return _fail(result, deny(
            "PMO-SCHEMA-MIG-022", "no schema-migration transaction is in progress."),
            status="NO_TRANSACTION")
    if state in ("INVALID", "WRONG_PROJECT"):
        return _fail(result, deny("PMO-SCHEMA-MIG-021", err))
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
            "PMO-SCHEMA-MIG-022", "no schema-migration transaction is in progress."),
            status="NO_TRANSACTION")
    if state in ("INVALID", "WRONG_PROJECT"):
        return _fail(result, deny("PMO-SCHEMA-MIG-021", err))
    result["marker"] = data
    report, decision = finalize_transaction(root, data)
    if decision is not None:
        return _fail(result, decision, status="RECOVERY_REQUIRED")
    result["report"] = report
    result["status"] = "MIGRATED"
    return result


def cmd_abort(root, reason):
    result = _new_result("abort")
    state, data, err = marker_status(root)
    if state == "ABSENT":
        return _fail(result, deny(
            "PMO-SCHEMA-MIG-022", "no schema-migration transaction is in progress."),
            status="NO_TRANSACTION")
    if state in ("INVALID", "WRONG_PROJECT"):
        return _fail(result, deny("PMO-SCHEMA-MIG-021", err))
    result["marker"] = data
    report, decision = abort_transaction(root, data, reason)
    if decision is not None:
        return _fail(result, decision)
    result["report"] = report
    result["status"] = "ABORTED"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog="specs-schema-migration.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_begin = sub.add_parser("begin")
    p_begin.add_argument("--reason", required=True)
    p_begin.add_argument("--dry-run", action="store_true")
    p_begin.add_argument("--root", default=None)

    p_abort = sub.add_parser("abort")
    p_abort.add_argument("--reason", required=True)
    p_abort.add_argument("--root", default=None)

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
    elif args.command == "abort":
        result = cmd_abort(root, args.reason)
    else:  # pragma: no cover
        parser.error("unknown command")
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
