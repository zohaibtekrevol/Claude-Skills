#!/usr/bin/env python3
"""PMO specs-feedback-amendment - deterministic transaction orchestrator for
FEEDBACK_AMENDMENT: the governed, non-functional amendment of an APPROVED Specs
baseline from a canonical Feedback record (no Change Request).

All logic lives in ``.claude/lib/specs_feedback_amendment_core.py``.

    specs-feedback-amendment.py assess  --feedback FB-YYYY-NNN-NNN [correction]   (read-only)
        -> NO_ARTIFACT_CHANGE | FEEDBACK_AMENDMENT | CHANGE_REQUEST_REQUIRED,
           with a PM-facing message (--engineering adds the technical detail).
           Never writes and never creates a Change Request.
    specs-feedback-amendment.py begin   --feedback ... [correction] --reason "PM approves processing" [--dry-run]
    specs-feedback-amendment.py validate | status                                   (read-only)
    specs-feedback-amendment.py finalize
        -> re-derives everything from disk; writes the amended Specs (next minor
           version, Execution Authorized false, Change History row, Feedback
           Item Change Source), resolves the Feedback item, archives the
           previous approval and previous approved bytes, removes the marker.
           All-or-nothing with rollback.
    specs-feedback-amendment.py abort --reason "..."     (marker only)
    specs-feedback-amendment.py resolve-no-change --feedback ... --reason "..."

A correction is one of:
    --target FR-018 --before "recieve" --after "receive" [--equivalence "P=Q"]
    --rename "Dispatcher=Dispatch Coordinator"          (uniform rename)

The amended Specs needs a fresh PM approval (specs-approval-recorder.py) and its
own publication; this CLI never approves or publishes. Runs via Bash outside the
PreToolUse hook system; the marker is never authorization.
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

import specs_feedback_amendment_core as core  # noqa: E402
from intent_approval_core import locate_project_root  # noqa: E402
from specs_structural_repair_core import write_text, deny  # noqa: E402


def _new(command):
    return {"command": command, "status": None, "outcome": None, "message": None,
            "reasons": None, "decision": None, "plan": None, "marker": None, "report": None}


def _fail(result, decision, status="BLOCKED"):
    result["status"] = status
    result["decision"] = {"code": decision.code, "message": decision.message}
    return result


def _tid():
    return "SPECFBX-{}-{}".format(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:8])


def correction_from_args(a):
    if getattr(a, "rename", None):
        if "=" not in a.rename:
            return None
        p, q = a.rename.split("=", 1)
        return {"kind": "rename", "from": p.strip(), "to": q.strip()}
    if getattr(a, "before", None) is not None or getattr(a, "target", None):
        eq = None
        if getattr(a, "equivalence", None):
            if "=" not in a.equivalence:
                return {"kind": "text", "target": a.target, "before": a.before, "after": a.after,
                        "equivalence": ["?", "?"]}
            p, q = a.equivalence.split("=", 1)
            eq = [p.strip(), q.strip()]
        return {"kind": "text", "target": a.target, "before": a.before, "after": a.after, "equivalence": eq}
    return None


def cmd_assess(root, feedback, correction, engineering=False):
    r = _new("assess")
    res = core.build_candidate(root, feedback, correction)
    r["outcome"] = res.get("outcome")
    r["reasons"] = res.get("reasons")
    if res.get("decision") is not None:
        _fail(r, res["decision"], status="BLOCKED")
    else:
        r["status"] = res["outcome"]
    r["message"] = core.pm_message(res, engineering=engineering)
    return r


def cmd_begin(root, feedback, correction, reason, dry_run=False):
    r = _new("begin")
    state, data, err = core.marker_status(root)
    if state == "OPEN":
        r["marker"] = data
        return _fail(r, deny("PMO-FB-AMEND-020", "a Feedback amendment is already in progress ({}).".format(data.get("transaction_id"))))
    if state in ("INVALID", "WRONG_PROJECT"):
        return _fail(r, deny("PMO-FB-AMEND-021", err))
    if correction is None:
        return _fail(r, deny("PMO-FB-AMEND-022", "no correction supplied (use `resolve-no-change` for Feedback that needs no Specs edit)."))
    plan, d, res = core.plan_transaction(root, feedback, correction, reason)
    if res is not None:
        r["outcome"] = res.get("outcome")
        r["reasons"] = res.get("reasons")
        r["message"] = core.pm_message(res)
    if d is not None:
        return _fail(r, d)
    if plan is None:
        r["status"] = res["outcome"]  # CHANGE_REQUEST_REQUIRED / NO_ARTIFACT_CHANGE: nothing written
        return r
    r["plan"] = plan
    if dry_run:
        r["status"] = "DRY_RUN_PASS"
        return r
    marker = core.build_marker_data(plan, _tid(), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    write_text(core.marker_abspath(root), json.dumps(marker, indent=2))
    r["marker"] = marker
    r["status"] = "ACTIVE"
    return r


def _load(root, r):
    state, data, err = core.marker_status(root)
    if state == "ABSENT":
        return None, _fail(r, deny("PMO-FB-AMEND-023", "no Feedback amendment is in progress."), status="NO_TRANSACTION")
    if state in ("INVALID", "WRONG_PROJECT"):
        return None, _fail(r, deny("PMO-FB-AMEND-021", err))
    r["marker"] = data
    return data, None


def cmd_status(root):
    r = _new("status")
    state, data, err = core.marker_status(root)
    if state == "ABSENT":
        r["status"] = "NO_TRANSACTION"
    elif state in ("INVALID", "WRONG_PROJECT"):
        _fail(r, deny("PMO-FB-AMEND-021", err), status="INVALID_MARKER")
    else:
        r["marker"] = data
        r["status"] = data["status"]
    return r


def cmd_validate(root):
    r = _new("validate")
    data, bad = _load(root, r)
    if bad:
        return bad
    plan, d, res = core.plan_transaction_for_finalize(root, data)
    if d is not None:
        return _fail(r, d, status="RECOVERY_REQUIRED")
    r["plan"] = plan
    r["status"] = "VALID" if plan else (res or {}).get("outcome")
    return r


def cmd_finalize(root):
    r = _new("finalize")
    data, bad = _load(root, r)
    if bad:
        return bad
    report, d = core.finalize_amendment(root, data)
    if d is not None:
        return _fail(r, d, status="RECOVERY_REQUIRED")
    r["report"] = report
    r["status"] = "AMENDED"
    return r


def cmd_abort(root, reason):
    r = _new("abort")
    data, bad = _load(root, r)
    if bad:
        return bad
    report, d = core.abort_transaction(root, data, reason)
    if d is not None:
        return _fail(r, d)
    r["report"] = report
    r["status"] = "ABORTED"
    return r


def cmd_resolve_no_change(root, feedback, reason):
    r = _new("resolve-no-change")
    report, d = core.resolve_without_change(root, feedback, reason)
    if d is not None:
        return _fail(r, d)
    r["report"] = report
    r["outcome"] = core.NO_ARTIFACT_CHANGE
    r["status"] = "RESOLVED_NO_CHANGE"
    return r


def build_parser():
    p = argparse.ArgumentParser(prog="specs-feedback-amendment.py")
    sub = p.add_subparsers(dest="command", required=True)

    def corr(sp):
        sp.add_argument("--feedback", required=True)
        sp.add_argument("--target")
        sp.add_argument("--before")
        sp.add_argument("--after")
        sp.add_argument("--equivalence")
        sp.add_argument("--rename")
        sp.add_argument("--root", default=None)

    a = sub.add_parser("assess"); corr(a); a.add_argument("--engineering", action="store_true")
    b = sub.add_parser("begin"); corr(b); b.add_argument("--reason", required=True); b.add_argument("--dry-run", action="store_true")
    for n in ("status", "validate", "finalize"):
        s = sub.add_parser(n); s.add_argument("--root", default=None)
    ab = sub.add_parser("abort"); ab.add_argument("--reason", required=True); ab.add_argument("--root", default=None)
    nc = sub.add_parser("resolve-no-change"); nc.add_argument("--feedback", required=True)
    nc.add_argument("--reason", required=True); nc.add_argument("--root", default=None)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    root = args.root or locate_project_root(os.getcwd())
    c = args.command
    if c == "assess":
        out = cmd_assess(root, args.feedback, correction_from_args(args), args.engineering)
    elif c == "begin":
        out = cmd_begin(root, args.feedback, correction_from_args(args), args.reason, args.dry_run)
    elif c == "status":
        out = cmd_status(root)
    elif c == "validate":
        out = cmd_validate(root)
    elif c == "finalize":
        out = cmd_finalize(root)
    elif c == "abort":
        out = cmd_abort(root, args.reason)
    else:
        out = cmd_resolve_no_change(root, args.feedback, args.reason)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
