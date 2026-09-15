#!/usr/bin/env python3
"""PMO intent-approval-recorder - the deterministic Intent PM-approval
transaction orchestrator.

Role boundary
---------------
Recording that a PM has approved an Intent is a PROCESS action, not a
semantic one: it never decides whether the Intent's content is right, only
whether the explicit approval given for it is faithfully and atomically
recorded. This CLI owns TRANSACTION EXECUTION and RECONCILIATION only - see
``.claude/lib/intent_approval_core.py`` (this CLI's sole source of
validation logic) for the full architecture note, including the exact
defect this module exists to close.

Flow
------
::

    intent-approval-recorder.py begin --approved-by "Muhammad Faizan" \\
        --decision-date 2026-09-16 --statement "..."
        -> runs the full BEGIN precondition checklist (read-only) against
           the CURRENT on-disk intent.md; on PASS, writes
           .pmo/intent-approval-transaction.json
        |
        v
    intent-approval-recorder.py validate
        -> re-reads everything from disk and re-runs the SAME reconciliation
           checks finalize will use; reports PASS / RECOVERY_REQUIRED /
           ALREADY_APPROVED
        |
        v
    intent-approval-recorder.py finalize
        -> re-validates (never trusts a stale prior `validate`), and only on
           a full PASS writes .pmo/approvals/intent-approval.yaml followed by
           the single, complete intent.md rewrite (Status: VALIDATED AND the
           Section 16 / Acceptance update, together), then removes the
           marker

``status`` is available at any point and is always pure read-only.

There is no intermediate Skill-authored content step between `begin` and
`finalize` (unlike CR incorporation, which needs the Skill's own governed
Scope/Specs/Change Log edits in between) - a PM approval's content is fully
determined by the explicit fields supplied at `begin`. `begin` and
`finalize` may therefore be invoked back-to-back; the separate commands
still exist so `status`/`validate` provide the same crash-recovery /
idempotency guarantees as every other PMO transaction in this codebase.

Security boundary
-------------------
This CLI runs via Bash - entirely outside Claude Code's PreToolUse hook
system. The existence of ``.pmo/intent-approval-transaction.json`` is NOT
itself authorization for anything: every command here independently
re-runs the same deterministic checks ``intent-schema-guard.py`` applies to
a live Write/Edit (imported from the same core module), and ``finalize``
additionally re-verifies its own output by re-reading it back from disk
before declaring success. There is no Bash-side shortcut around
governance - PMO-INTENT-009 (immutability) is not weakened; this CLI's
writes are a SEPARATE, equally strict enforcement point that happens to run
outside the hook, not a bypass of it.

Runtime marker only
----------------------
``.pmo/intent-approval-transaction.json`` is a *runtime* transaction
artifact, not permanent framework or project content: it is always removed
on a clean ``finalize``, and ``.pmo/`` is already untracked by this
repository's own ``.gitignore``.

Idempotency
-------------
``begin`` and ``finalize`` both check whether the Intent is already
VALIDATED with a fully consistent, matching Acceptance section and approval
record; if so, no marker/artifact is touched and the result reports
``status: "NO_CHANGE"`` (``PMO-INTENT-APPROVAL-003 ALREADY_APPROVED``).

Recovery
----------
There is no automatic rollback. A genuine partial-transaction inconsistency
found by ``validate`` or ``finalize`` moves the marker's ``status`` to
``RECOVERY_REQUIRED`` (never silently cleared, never silently removed) and
is reported precisely. Re-running ``validate``/``finalize`` after a fix is
always safe (both re-derive everything from disk); nothing here ever
restores a "known snapshot" by overwriting a newer change - see
``reconcile_transaction`` in the core module.

Exit code: 0 for every non-exceptional result (including BLOCKED /
RECOVERY_REQUIRED - those are valid, correctly-reported outcomes, not CLI
failures), 1 only for a command-line usage error. The JSON result's own
``status`` field is the actual outcome; callers must inspect it rather than
rely on the process exit code alone.

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

from intent_approval_core import (  # noqa: E402
    INTENT_APPROVAL_MARKER_RELPATH_PARTS,
    APPROVAL_MARKER_STATUS_TRANSITIONS,
    build_marker_data,
    deny,
    finalize_transaction,
    intent_approval_marker_status,
    locate_project_root,
    reconcile_transaction,
    run_begin_preconditions,
    write_text,
)


# --------------------------------------------------------------------------- #
# Result plumbing
# --------------------------------------------------------------------------- #

def _new_result(command):
    return {
        "command": command,
        "status": None,
        "decision": None,
        "plan": None,
        "marker": None,
        "report": None,
    }


def _fail(result, decision, status="BLOCKED"):
    result["status"] = status
    result["decision"] = {"code": decision.code, "message": decision.message}
    return result


def _new_transaction_id():
    return "INTAPX-{}-{}".format(
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:8]
    )


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _marker_path(root):
    return os.path.join(root, *INTENT_APPROVAL_MARKER_RELPATH_PARTS)


def _try_transition_marker(root, old_data, new_status):
    """Best-effort, rule-respecting status-only update - never touches
    transaction_id/started_at/artifact_path/operation, and never moves to a
    status not present in APPROVAL_MARKER_STATUS_TRANSITIONS for the
    current one. A no-op (not an error) if the transition isn't applicable."""
    if old_data.get("status") == new_status:
        return
    allowed = APPROVAL_MARKER_STATUS_TRANSITIONS.get(old_data.get("status"), set())
    if new_status not in allowed:
        return
    new_data = dict(old_data)
    new_data["status"] = new_status
    write_text(_marker_path(root), json.dumps(new_data, indent=2))


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_begin(root, approved_by, decision_date, statement=None,
             project_id=None, dry_run=False):
    """Runs the full BEGIN precondition checklist (read-only) against the
    current on-disk Intent. On PASS and not --dry-run, writes the
    transaction marker. Never invents Intent substance - `plan` only
    reports the deterministically-derived candidate content/evidence."""
    result = _new_result("begin")
    state, existing_marker, err = intent_approval_marker_status(root)
    if state == "OPEN":
        result["marker"] = existing_marker
        return _fail(result, deny(
            "PMO-INTENT-APPROVAL-007",
            "a transaction is already {} for Intent v{} (transaction_id "
            "{}) - refusing to silently overwrite it. Use `status` / "
            "`validate` / `finalize` to resume it, or resolve it manually "
            "before starting a new one.".format(
                existing_marker.get("status"),
                existing_marker.get("intent_version"),
                existing_marker.get("transaction_id"),
            )))
    if state == "WRONG_PROJECT":
        return _fail(result, deny("PMO-INTENT-APPROVAL-009", err))

    decision, plan = run_begin_preconditions(
        root, approved_by, decision_date, approval_statement=statement,
        project_id_hint=project_id)
    if decision is not None:
        if decision.code == "PMO-INTENT-APPROVAL-003":
            result["status"] = "NO_CHANGE"
            result["decision"] = {"code": decision.code, "message": decision.message}
            return result
        return _fail(result, decision)

    result["plan"] = plan
    if dry_run:
        result["status"] = "DRY_RUN_PASS"
        return result

    marker_data = build_marker_data(plan, _new_transaction_id(), _now_iso())
    write_text(_marker_path(root), json.dumps(marker_data, indent=2))
    result["marker"] = marker_data
    result["status"] = "ACTIVE"
    return result


def cmd_status(root):
    """Always read-only - never writes the marker or any project file,
    regardless of what it finds."""
    result = _new_result("status")
    state, data, err = intent_approval_marker_status(root)
    if state == "ABSENT":
        result["status"] = "NO_TRANSACTION"
        return result
    if state == "INVALID":
        result["status"] = "INVALID_MARKER"
        result["decision"] = {"code": "PMO-INTENT-APPROVAL-008", "message": err}
        return result
    if state == "WRONG_PROJECT":
        result["status"] = "INVALID_MARKER"
        result["decision"] = {"code": "PMO-INTENT-APPROVAL-009", "message": err}
        return result

    result["marker"] = data
    decision, report = reconcile_transaction(root, data)
    result["report"] = report
    if decision is None:
        result["status"] = "ALREADY_APPROVED" if report.get("already_done") else "RECONCILED"
    else:
        result["status"] = "IN_PROGRESS" if data.get("status") == "ACTIVE" else data.get("status")
        result["decision"] = {"code": decision.code, "message": decision.message}
    return result


def _load_marker(root, result):
    """Shared preamble for validate/finalize: locate and sanity-check the
    marker. Returns marker_data on success, or None after populating
    result as a failure."""
    state, data, err = intent_approval_marker_status(root)
    if state == "ABSENT":
        _fail(result, deny("PMO-INTENT-APPROVAL-010",
                           "no active intent-approval-transaction.json "
                           "found - run `begin` first."))
        return None
    if state == "INVALID":
        _fail(result, deny("PMO-INTENT-APPROVAL-008", err))
        return None
    if state == "WRONG_PROJECT":
        _fail(result, deny("PMO-INTENT-APPROVAL-009", err))
        return None
    result["marker"] = data
    return data


def cmd_validate(root):
    """Re-runs full reconciliation (read-only against project artifacts).
    On PASS, advances the marker status ACTIVE -> RECONCILING (a same-
    transaction, rule-respecting update) to signal "ready for finalize". On
    a genuine partial-transaction failure, moves it to RECOVERY_REQUIRED -
    never silently left at a stale ACTIVE."""
    result = _new_result("validate")
    data = _load_marker(root, result)
    if data is None:
        return result

    decision, report = reconcile_transaction(root, data)
    result["report"] = report
    if decision is None:
        result["status"] = "ALREADY_APPROVED" if report.get("already_done") else "PASS"
        if not report.get("already_done"):
            _try_transition_marker(root, data, "RECONCILING")
        return result

    _try_transition_marker(root, data, "RECOVERY_REQUIRED")
    return _fail(result, decision, status="RECOVERY_REQUIRED")


def cmd_finalize(root):
    """Re-validates from scratch (never trusts a stale prior `validate`)
    and, only on a full PASS, writes the approval evidence followed by the
    single, complete Intent rewrite, then removes the marker as the last
    step. On failure, the marker is moved to RECOVERY_REQUIRED and nothing
    is falsely reported as VALIDATED."""
    result = _new_result("finalize")
    data = _load_marker(root, result)
    if data is None:
        return result

    decision, report = finalize_transaction(root, data)
    result["report"] = report
    if decision is not None:
        _try_transition_marker(root, data, "RECOVERY_REQUIRED")
        return _fail(result, decision, status="RECOVERY_REQUIRED")

    if report.get("already_done"):
        result["status"] = "ALREADY_APPROVED"
    else:
        result["status"] = "VALIDATED"
    try:
        os.remove(_marker_path(root))
    except Exception:
        pass
    return result


# --------------------------------------------------------------------------- #
# CLI wiring
# --------------------------------------------------------------------------- #

def build_arg_parser():
    p = argparse.ArgumentParser(
        prog="intent-approval-recorder.py",
        description="Deterministic execution/reconciliation for an explicit "
                    "PM approval of docs/pmo/intent/intent.md. Never decides "
                    "whether the Intent's content is right - see module "
                    "docstring.",
    )
    p.add_argument("--root", default=None,
                   help="Project root override (defaults to the located "
                        "PMO project root from the current working "
                        "directory).")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("begin", help="Validate BEGIN preconditions and, "
                                     "unless --dry-run, create the "
                                     "transaction marker.")
    b.add_argument("--approved-by", required=True, dest="approved_by")
    b.add_argument("--decision-date", required=True, dest="decision_date",
                   help="ISO date (YYYY-MM-DD) the PM made the decision.")
    b.add_argument("--statement", default=None,
                   help="The PM's own approval statement, recorded "
                        "verbatim into the approval evidence file.")
    b.add_argument("--project", default=None, dest="project_id")
    b.add_argument("--dry-run", action="store_true",
                   help="Report eligibility/candidate content only; never "
                        "writes the marker or any project file.")

    sub.add_parser("status", help="Read-only inspection of the current "
                                  "transaction, if any.")

    sub.add_parser("validate", help="Re-run full reconciliation against the "
                                    "current on-disk Intent.")

    sub.add_parser("finalize", help="Re-validate and, only on PASS, write "
                                    "the approval evidence and the Intent "
                                    "update together, then remove the "
                                    "marker.")
    return p


_TERMINAL_OK_STATUSES = {
    "ACTIVE", "DRY_RUN_PASS", "PASS", "RECONCILED", "VALIDATED",
    "NO_CHANGE", "ALREADY_APPROVED", "NO_TRANSACTION", "IN_PROGRESS",
    "RECONCILING",
}


def run(command, root=None, **kwargs):
    """Testable entry point - every unit/integration test, and main(),
    calls this directly. Fail-closed lives HERE (not only in main()) so
    that any caller of this module - not just the CLI's own argv path -
    gets the same "never a bare traceback claiming nothing happened"
    guarantee."""
    try:
        root = root or locate_project_root(os.getcwd())
        if command == "begin":
            return cmd_begin(
                root, kwargs["approved_by"], kwargs["decision_date"],
                kwargs.get("statement"), kwargs.get("project_id"),
                kwargs.get("dry_run", False))
        if command == "status":
            return cmd_status(root)
        if command == "validate":
            return cmd_validate(root)
        if command == "finalize":
            return cmd_finalize(root)
        raise ValueError("unknown command: {}".format(command))
    except Exception as exc:  # fail closed - never a bare traceback
        return {
            "command": command,
            "status": "BLOCKED",
            "decision": {"code": "PMO-INTENT-APPROVAL-015",
                        "message": "unexpected internal error ({}).".format(exc)},
            "plan": None,
            "marker": None,
            "report": None,
        }


def main(argv=None):
    try:
        args = build_arg_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    root = args.root
    if args.command == "begin":
        result = run("begin", root, approved_by=args.approved_by,
                    decision_date=args.decision_date, statement=args.statement,
                    project_id=args.project_id, dry_run=args.dry_run)
    elif args.command == "status":
        result = run("status", root)
    elif args.command == "validate":
        result = run("validate", root)
    elif args.command == "finalize":
        result = run("finalize", root)
    else:
        result = {"status": "UNKNOWN_COMMAND", "command": args.command}

    print(json.dumps(result, indent=2, default=str))
    # Exit 0 for every result the command actually computed - BLOCKED and
    # RECOVERY_REQUIRED are correctly-reported outcomes, not CLI failures.
    # Callers must inspect the JSON `status` field, not the process exit
    # code, to distinguish them. Exit 1 is reserved for a command-line
    # usage error (handled above via the SystemExit catch) or a status this
    # module never produces at all (a defect, not a valid outcome).
    known = _TERMINAL_OK_STATUSES | {"BLOCKED", "RECOVERY_REQUIRED", "INVALID_MARKER"}
    return 0 if result.get("status") in known else 1


if __name__ == "__main__":
    sys.exit(main())
