#!/usr/bin/env python3
"""PMO change-request-incorporator - the deterministic CR incorporation
transaction orchestrator (Phase 2C).

Role boundary
---------------
``change-request-management`` (the Skill, Claude) owns SEMANTIC decisions:
what the new Scope requirement says, what specs.md's updated behaviour is,
which modules/requirements are affected, the Change Log's change summary.
This CLI owns TRANSACTION EXECUTION and RECONCILIATION only. It never
invents requirement text, Scope/Spec interpretation, acceptance criteria,
affected modules, or business rules - see
``.claude/lib/change_request_incorporation_core.py`` (this CLI's sole
source of validation logic) for the full architecture note.

Flow
------
::

    change-request-incorporator.py begin --cr CR-007
        -> runs the full BEGIN precondition checklist (read-only); on PASS,
           writes .pmo/change-request-transaction.json
        |
        v
    (the Skill performs the actual, governed Scope/Specs/Change Log edits,
     as ordinary Write/Edit calls - change-request-governance-guard.py
     validates each one exactly as it always has)
        |
        v
    change-request-incorporator.py validate --cr CR-007
        -> re-reads everything from disk and re-runs the SAME reconciliation
           checks finalize will use; reports PASS / RECOVERY_REQUIRED /
           NO_CHANGE
        |
        v
    change-request-incorporator.py finalize --cr CR-007
        -> re-validates (never trusts a stale prior `validate`), and only on
           a full PASS flips the CR to INCORPORATED and removes the marker

``status`` is available at any point and is always pure read-only.

Security boundary
-------------------
This CLI runs via Bash - entirely outside Claude Code's PreToolUse hook
system. The existence of ``.pmo/change-request-transaction.json`` is NOT
itself authorization for anything: every command here independently
re-runs the same deterministic checks
``change-request-governance-guard.py`` applies to a live Write/Edit
(imported from the same core module), and ``finalize`` additionally
re-validates its own output against ``validate_incorporated_gate`` /
``validate_history_append_only`` before writing a single byte. There is no
Bash-side shortcut around governance.

Publication boundary
-----------------------
This CLI never runs ``git add`` / ``git commit`` / ``git push``, creates or
switches a branch, or selects a remote. It modifies governed local project
artifacts only (the CR record, and, on ``finalize``, nothing else -
Scope/Specs/Change Log are always written by the Skill via governed
Write/Edit calls, never by this CLI). Publishing remains a later, explicit,
separate ``artifact-publish`` operation.

Idempotency
-------------
``begin`` and ``finalize`` both check the CR's actual current status first;
if it is already ``INCORPORATED``, no marker is created / no artifact is
touched and the result reports ``status: "NO_CHANGE"``
(``PMO-CR-INTEGRATE-021 ALREADY_INCORPORATED``).

Recovery
----------
There is no automatic rollback. A genuine partial-transaction inconsistency
found by ``validate`` or ``finalize`` moves the marker's ``status`` to
``RECOVERY_REQUIRED`` (never silently cleared, never silently removed) and
is reported precisely - which artifacts exist, which are missing, which are
inconsistent. Re-running ``validate``/``finalize`` after a PM/system fix is
always safe (both re-derive everything from disk); nothing here ever
restores a "known snapshot" by overwriting a newer change - see
``reconcile_transaction`` in the core module.

Exit code: 0 for every non-exceptional result (including BLOCKED /
RECOVERY_REQUIRED - those are valid, correctly-reported outcomes, not CLI
failures), 1 only for a command-line usage error. The JSON result's own
``status`` field is the actual outcome; callers must inspect it rather
than rely on the process exit code alone.

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

from change_request_incorporation_core import (  # noqa: E402
    CR_MARKER_RELPATH_PARTS,
    MARKER_STATUS_TRANSITIONS,
    build_marker_data,
    cr_marker_status,
    deny,
    finalize_transaction,
    locate_project_root,
    reconcile_transaction,
    run_begin_preconditions,
    write_text,
)


# --------------------------------------------------------------------------- #
# Result plumbing
# --------------------------------------------------------------------------- #

def _new_result(command, cr_id):
    return {
        "command": command,
        "cr_id": cr_id,
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
    return "CRTX-{}-{}".format(
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:8]
    )


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _marker_path(root):
    return os.path.join(root, *CR_MARKER_RELPATH_PARTS)


def _try_transition_marker(root, old_data, new_status):
    """Best-effort, rule-respecting status-only update - never touches
    transaction_id/started_at/cr_id/operation, and never moves to a status
    not present in MARKER_STATUS_TRANSITIONS for the current one. A no-op
    (not an error) if the transition isn't applicable."""
    if old_data.get("status") == new_status:
        return
    allowed = MARKER_STATUS_TRANSITIONS.get(old_data.get("status"), set())
    if new_status not in allowed:
        return
    new_data = dict(old_data)
    new_data["status"] = new_status
    write_text(_marker_path(root), json.dumps(new_data, indent=2))


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_begin(root, cr_id, project_id_hint=None, dry_run=False):
    """Runs the full BEGIN precondition checklist (read-only). On PASS and
    not --dry-run, writes the transaction marker. Never generates
    Scope/Specs/Change Log content - `plan` only reports what already
    exists (the approved CR's own fields) plus deterministically computed
    target versions/ids."""
    result = _new_result("begin", cr_id)
    decision, plan = run_begin_preconditions(root, cr_id, project_id_hint)
    if decision is not None:
        if decision.code == "PMO-CR-INTEGRATE-021":
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


def cmd_status(root, cr_id=None):
    """Always read-only - never writes the marker or any project file,
    regardless of what it finds."""
    result = _new_result("status", cr_id)
    state, data, err = cr_marker_status(root)
    if state == "ABSENT":
        result["status"] = "NO_TRANSACTION"
        return result
    if state == "INVALID":
        result["status"] = "INVALID_MARKER"
        result["decision"] = {"code": "PMO-CR-INTEGRATE-023", "message": err}
        return result
    if state == "WRONG_PROJECT":
        result["status"] = "INVALID_MARKER"
        result["decision"] = {"code": "PMO-CR-INTEGRATE-024", "message": err}
        return result

    result["marker"] = data
    if cr_id and data.get("cr_id") != cr_id:
        result["status"] = "DIFFERENT_CR_ACTIVE"
        return result

    decision, report = reconcile_transaction(root, data)
    result["report"] = report
    if decision is None:
        result["status"] = "RECONCILED"
    elif decision.code == "PMO-CR-INTEGRATE-021":
        result["status"] = "ALREADY_INCORPORATED"
    else:
        result["status"] = "IN_PROGRESS" if data.get("status") == "ACTIVE" else data.get("status")
        result["decision"] = {"code": decision.code, "message": decision.message}
    return result


def _load_marker_for(root, cr_id, result):
    """Shared preamble for validate/finalize: locate and sanity-check the
    marker. Returns marker_data on success, or None after populating
    result as a failure."""
    state, data, err = cr_marker_status(root)
    if state == "ABSENT":
        _fail(result, deny("PMO-CR-INTEGRATE-023",
                           "no active change-request-transaction.json found."))
        return None
    if state == "INVALID":
        _fail(result, deny("PMO-CR-INTEGRATE-023", err))
        return None
    if state == "WRONG_PROJECT":
        _fail(result, deny("PMO-CR-INTEGRATE-024", err))
        return None
    if data.get("cr_id") != cr_id:
        _fail(result, deny("PMO-CR-INTEGRATE-023",
                           "active transaction is for a different CR "
                           "('{}').".format(data.get("cr_id"))))
        return None
    result["marker"] = data
    return data


def cmd_validate(root, cr_id):
    """Re-runs full reconciliation (read-only against project artifacts).
    On PASS, advances the marker status ACTIVE -> RECONCILING (a same-
    transaction, rule-respecting update) to signal "ready for finalize". On
    a genuine partial-transaction failure, moves it to RECOVERY_REQUIRED -
    never silently left at a stale ACTIVE."""
    result = _new_result("validate", cr_id)
    data = _load_marker_for(root, cr_id, result)
    if data is None:
        return result

    decision, report = reconcile_transaction(root, data)
    result["report"] = report
    if decision is None:
        result["status"] = "PASS"
        _try_transition_marker(root, data, "RECONCILING")
        return result
    if decision.code == "PMO-CR-INTEGRATE-021":
        result["status"] = "NO_CHANGE"
        result["decision"] = {"code": decision.code, "message": decision.message}
        return result

    _try_transition_marker(root, data, "RECOVERY_REQUIRED")
    return _fail(result, decision, status="RECOVERY_REQUIRED")


def cmd_finalize(root, cr_id, actor="change-request-incorporator",
                 reason="approved CR incorporation transaction completed"):
    """Re-validates from scratch (never trusts a stale prior `validate`)
    and, only on a full PASS, performs the single authorized write: CR ->
    INCORPORATED with an appended history row, followed by removing the
    marker as the last step. On failure, the marker is moved to
    RECOVERY_REQUIRED and nothing is falsely reported as INCORPORATED."""
    result = _new_result("finalize", cr_id)
    data = _load_marker_for(root, cr_id, result)
    if data is None:
        return result

    decision, report = finalize_transaction(root, data, actor, _now_iso()[:10], reason)
    result["report"] = report
    if decision is not None:
        if decision.code == "PMO-CR-INTEGRATE-021":
            result["status"] = "NO_CHANGE"
            result["decision"] = {"code": decision.code, "message": decision.message}
            return result
        _try_transition_marker(root, data, "RECOVERY_REQUIRED")
        return _fail(result, decision, status="RECOVERY_REQUIRED")

    try:
        os.remove(_marker_path(root))
    except Exception:
        pass
    result["status"] = "INCORPORATED"
    return result


# --------------------------------------------------------------------------- #
# CLI wiring
# --------------------------------------------------------------------------- #

def build_arg_parser():
    p = argparse.ArgumentParser(
        prog="change-request-incorporator.py",
        description="Deterministic execution/reconciliation for an APPROVED "
                    "Change Request's incorporation transaction. Never "
                    "authors Scope/Specs/Change Log content - see module "
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
    b.add_argument("--cr", required=True, dest="cr_id")
    b.add_argument("--project", default=None, dest="project_id")
    b.add_argument("--dry-run", action="store_true",
                   help="Report eligibility/targets only; never writes the "
                        "marker or any project file.")

    s = sub.add_parser("status", help="Read-only inspection of the current "
                                      "transaction, if any.")
    s.add_argument("--cr", default=None, dest="cr_id")

    v = sub.add_parser("validate", help="Re-run full reconciliation after "
                                        "the Skill's governed Scope/Specs/"
                                        "Change Log edits.")
    v.add_argument("--cr", required=True, dest="cr_id")

    f = sub.add_parser("finalize", help="Re-validate and, only on PASS, "
                                        "flip the CR to INCORPORATED and "
                                        "remove the marker.")
    f.add_argument("--cr", required=True, dest="cr_id")
    f.add_argument("--by", default="change-request-incorporator", dest="actor")
    f.add_argument("--reason",
                   default="approved CR incorporation transaction completed")
    return p


_TERMINAL_OK_STATUSES = {
    "ACTIVE", "DRY_RUN_PASS", "PASS", "RECONCILED", "INCORPORATED",
    "NO_CHANGE", "ALREADY_INCORPORATED", "NO_TRANSACTION",
    "DIFFERENT_CR_ACTIVE", "IN_PROGRESS", "RECONCILING",
}


def run(command, root=None, **kwargs):
    """Testable entry point - every unit/integration test, and main(),
    calls this directly. Fail-closed lives HERE (not only in main()) so
    that any caller of this module - not just the CLI's own argv path -
    gets the same "never a bare traceback claiming nothing happened"
    guarantee."""
    cr_id = kwargs.get("cr_id")
    try:
        root = root or locate_project_root(os.getcwd())
        if command == "begin":
            return cmd_begin(root, kwargs["cr_id"], kwargs.get("project_id"),
                             kwargs.get("dry_run", False))
        if command == "status":
            return cmd_status(root, kwargs.get("cr_id"))
        if command == "validate":
            return cmd_validate(root, kwargs["cr_id"])
        if command == "finalize":
            return cmd_finalize(
                root, kwargs["cr_id"],
                kwargs.get("actor", "change-request-incorporator"),
                kwargs.get("reason",
                          "approved CR incorporation transaction completed"))
        raise ValueError("unknown command: {}".format(command))
    except Exception as exc:  # fail closed - never a bare traceback
        return {
            "command": command,
            "cr_id": cr_id,
            "status": "BLOCKED",
            "decision": {"code": "PMO-CR-INTEGRATE-025",
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
        result = run("begin", root, cr_id=args.cr_id, project_id=args.project_id,
                    dry_run=args.dry_run)
    elif args.command == "status":
        result = run("status", root, cr_id=args.cr_id)
    elif args.command == "validate":
        result = run("validate", root, cr_id=args.cr_id)
    elif args.command == "finalize":
        result = run("finalize", root, cr_id=args.cr_id, actor=args.actor,
                    reason=args.reason)
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
