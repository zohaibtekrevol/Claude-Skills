#!/usr/bin/env python3
"""PMO change-request-governance-guard (Claude Code PreToolUse hook).

Deterministic, fail-closed governance for the artifacts owned by the
``change-request-management`` Skill
(``.claude/skills/change-request-management/SKILL.md``): the full Change
Request lifecycle for both origins (``CLIENT_REQUESTED`` and
``PM_PROPOSED``), and the single governed incorporation transaction an
``APPROVED`` CR must pass through to reach ``INCORPORATED``.

Shared validation core (Phase 2C)
------------------------------------
As of Phase 2C this file is a thin PreToolUse shim - exactly the pattern
``artifact-publish-guard.py`` already established over
``artifact_publish_core.py`` in this codebase. Every actual validation rule
(marker parsing, CR field/lifecycle/transition/evidence/history rules,
Scope/Specs/Change-Log write validation, project-config whitelist) lives in
``.claude/lib/change_request_incorporation_core.py``, shared with the new
deterministic orchestrator ``.claude/scripts/change-request-incorporator.py``.
This file owns only the stdin/stdout PreToolUse hook protocol; every
decision is delegated to the core, so "Guard says PASS, CLI says FAIL" for
the same on-disk state cannot happen by construction. See the core
module's own docstring for the full architecture, marker schema, and error
namespace (``PMO-CR-GUARD-*`` here, ``PMO-CR-INTEGRATE-*`` for the
orchestrator's own operations - disjoint, never overloaded).

Transaction-scoped, dual-authority model (Phase 2B, unchanged)
-------------------------------------------------------------------
``docs/pmo/cr/change-request-register.md`` and ``docs/pmo/cr/CR-NNN.md`` can
be legitimately governed by *either*:

* an open **feedback** transaction (``feedback-governance-guard.py``'s own
  narrow authority: ``CLIENT_REQUESTED`` origin, ``DRAFT``/``CANCELLED``
  status only), or
* an open **change-request** transaction (this guard's full authority) -

never both at once. Domain routing is content-based: a CR write whose
*resulting* content is exactly the feedback-safe shape (``Origin:
CLIENT_REQUESTED``, ``Status`` in ``{DRAFT, CANCELLED}``) is left to the
feedback transaction (this guard defers - returns ``None``); any other
shape is unconditionally this guard's territory and requires an OPEN
``.pmo/change-request-transaction.json``.

Behaviour
---------
* Reads the Claude Code PreToolUse payload from stdin (JSON).
* Acts only on ``Write`` / ``Edit`` / ``MultiEdit``. Does not govern
  ``Bash`` / git - ``repo-binding-guard.py`` and ``artifact-publish-
  guard.py`` remain authoritative there.
* A blocked operation emits the standard PreToolUse deny response; an
  allowed or out-of-scope operation produces no output and exits 0.
* Any unexpected exception while validating an in-scope write fails closed
  (``PMO-CR-GUARD-026``).

Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from change_request_incorporation_core import (  # noqa: E402
    BASE_CONFIG_WHITELIST,
    CHANGE_LOG_DIR_POSIX,
    CONFIG_RELPATH,
    CR_DIR_POSIX,
    CR_FILE_RE,
    CR_MARKER_POSIX,
    CR_REGISTER_POSIX,
    INCORPORATION_CONFIG_WHITELIST,
    SCOPE_DIR_POSIX,
    SPECS_POSIX,
    TEMPLATE_CR_NAME,
    config_diff_violations,
    cr_marker_status,
    deny,
    feedback_marker_is_open,
    field_map_from_table,
    first_table,
    is_feedback_safe_shape,
    locate_project_root,
    posix_rel,
    read_text,
    register_is_feedback_safe,
    resulting_content,
    validate_change_log_write,
    validate_cr_content,
    validate_cr_register_content,
    validate_marker_write,
    validate_scope_write,
    validate_specs_write,
)


# --------------------------------------------------------------------------- #
# PreToolUse I/O (guard-specific; not part of the shared core)
# --------------------------------------------------------------------------- #

def emit(decision):
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "{}: {}".format(
                decision.code, decision.message
            ),
        }
    }
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


# --------------------------------------------------------------------------- #
# Payload dispatch
# --------------------------------------------------------------------------- #

def process_write_edit(tool_name, tool_input, root):
    path = tool_input.get("file_path")
    if not path or not isinstance(path, str):
        return None
    abspath = path if os.path.isabs(path) else os.path.join(root, path)
    rel = posix_rel(abspath, root)
    if rel is None:
        return None

    if rel == CR_MARKER_POSIX:
        return validate_marker_write(tool_name, tool_input, root)

    state, marker_data, marker_err = cr_marker_status(root)
    fb_open = feedback_marker_is_open(root)

    # -- Mutual exclusion: never both transactions active for this project. -#
    if state == "OPEN" and fb_open and (
        rel.startswith(CR_DIR_POSIX + "/") or rel == CR_REGISTER_POSIX
        or rel.startswith(SCOPE_DIR_POSIX + "/") or rel == SPECS_POSIX
        or rel.startswith(CHANGE_LOG_DIR_POSIX + "/")
    ):
        return deny(
            "PMO-CR-GUARD-025",
            "a change-request-management transaction and a feedback-"
            "management transaction are both active for this project at "
            "the same time - mutually exclusive. Resolve one before the "
            "other proceeds.",
        )

    # -- Scope / Specs / Change Log: only ever authorised during a valid  --#
    # -- INCORPORATION operation; otherwise denied regardless of marker.  --#
    if rel == SPECS_POSIX:
        return validate_specs_write(tool_name, tool_input, root, state, marker_data, marker_err)
    if rel == SCOPE_DIR_POSIX or rel.startswith(SCOPE_DIR_POSIX + "/"):
        return validate_scope_write(tool_name, tool_input, root, rel, state, marker_data, marker_err)
    if rel == CHANGE_LOG_DIR_POSIX or rel.startswith(CHANGE_LOG_DIR_POSIX + "/"):
        return validate_change_log_write(tool_name, tool_input, root, rel, state, marker_data, marker_err)

    if rel == CONFIG_RELPATH:
        if state != "ABSENT":
            existing = read_text(abspath) or ""
            new_content = resulting_content(tool_name, tool_input, existing)
            if new_content is not None:
                whitelist = (INCORPORATION_CONFIG_WHITELIST
                            if marker_data and marker_data.get("operation") == "INCORPORATION"
                            else BASE_CONFIG_WHITELIST)
                bad = config_diff_violations(existing, new_content, whitelist)
                if bad:
                    return deny(
                        "PMO-CR-GUARD-020",
                        "a change-request-management transaction may only "
                        "update {} in .pmo/project-config.yaml; this write "
                        "also changes: {}.".format(
                            ", ".join(sorted(whitelist)), ", ".join(bad)),
                    )
        return None

    basename = os.path.basename(rel)
    is_template = basename == TEMPLATE_CR_NAME
    is_cr_path = rel == CR_REGISTER_POSIX or rel.startswith(CR_DIR_POSIX + "/")
    if not is_cr_path or is_template:
        return None

    existing = read_text(abspath)
    new_content = resulting_content(tool_name, tool_input, existing)
    if new_content is None:
        return None

    if rel == CR_REGISTER_POSIX:
        if register_is_feedback_safe(new_content) and state != "OPEN":
            return None  # entirely feedback-safe content; not this guard's concern
        if state == "INVALID":
            return deny(
                "PMO-CR-GUARD-022",
                "cannot validate a change-request-owned write to '{}': the "
                "existing transaction marker is invalid ({}).".format(rel, marker_err),
            )
        if state == "WRONG_PROJECT":
            return deny(
                "PMO-CR-GUARD-001",
                "cannot validate a change-request-owned write to '{}': {}.".format(
                    rel, marker_err),
            )
        if state in ("ABSENT", "BLOCKED"):
            return deny(
                "PMO-CR-GUARD-024",
                "no open change-request-management transaction is active "
                "for '{}'.".format(rel),
            )
        return validate_cr_register_content(new_content, root)

    # -- Individual CR-NNN.md record. -----------------------------------#
    m = CR_FILE_RE.match(basename)
    if not m:
        return deny(
            "PMO-CR-GUARD-002",
            "'{}' is not a valid Change Request filename (expected "
            "CR-NNN.md).".format(basename),
        )
    expected_id = "CR-{}".format(m.group(1))

    new_fields = field_map_from_table(*first_table(new_content))
    if is_feedback_safe_shape(new_fields) and state != "OPEN":
        return None  # feedback-authorised shape; not this guard's concern

    if state == "INVALID":
        return deny(
            "PMO-CR-GUARD-022",
            "cannot validate a change-request-owned write to '{}': the "
            "existing transaction marker is invalid ({}).".format(rel, marker_err),
        )
    if state == "WRONG_PROJECT":
        return deny(
            "PMO-CR-GUARD-001",
            "cannot validate a change-request-owned write to '{}': {}.".format(
                rel, marker_err),
        )
    if state in ("ABSENT", "BLOCKED"):
        return deny(
            "PMO-CR-GUARD-024",
            "no open change-request-management transaction is active for "
            "'{}' (.pmo/change-request-transaction.json is {}).".format(
                rel, "absent" if state == "ABSENT"
                else "status RECOVERY_REQUIRED and not accepting writes"),
        )
    return validate_cr_content(root, new_content, existing, expected_id, marker_data)


def process(payload):
    if not isinstance(payload, dict):
        return None
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None
    if tool_name not in ("Write", "Edit", "MultiEdit"):
        return None
    cwd = payload.get("cwd") or os.getcwd()
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    root = locate_project_root(cwd)
    try:
        return process_write_edit(tool_name, tool_input, root)
    except Exception as exc:  # fail closed
        return deny(
            "PMO-CR-GUARD-026",
            "unexpected internal error during change-request governance "
            "validation ({}). Blocking as a precaution.".format(exc),
        )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0
    try:
        payload = json.loads(raw) if raw and raw.strip() else {}
    except Exception:
        return 0
    try:
        decision = process(payload)
    except Exception:
        return 0
    if decision is not None:
        emit(decision)
    return 0


if __name__ == "__main__":
    sys.exit(main())
