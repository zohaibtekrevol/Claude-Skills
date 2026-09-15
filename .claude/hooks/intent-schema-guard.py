#!/usr/bin/env python3
"""PMO Intent schema & governance guard (Claude Code PreToolUse hook).

Purpose
-------
Deterministic structural / workflow / immutability guard for the PMO Intent
artifact:

    docs/pmo/intent/intent.md

The *Intent skill* owns semantic analysis (does the Intent capture the client's
real goal, are the requirements sensible, etc.). This hook owns only the
mechanical, deterministic controls that do not require judgement:

  * the artifact has the required section skeleton before it is finalised,
  * document control / workflow metadata is well-formed and points at the
    correct next stage,
  * reserved specification identifiers (FR-XXX / NFR-XXX) never leak into
    Intent,
  * identifiers are not defined twice inside their own namespace,
  * a validated Intent is immutable except through downstream governance,
  * project identity matches `.pmo/project-config.yaml` (the only authority),
  * Claude never self-promotes an Intent to VALIDATED,
  * a VALIDATED transition's Section 16 / Acceptance content is complete and
    consistent with the approval evidence IN THE SAME WRITE (PMO-INTENT-014),
  * OPEN questions are governed records whose "Required Before" gate is a known
    workflow stage; an unresolved OPEN may be carried past Intent validation
    when that gate falls later than the Intent hand-off.

Shared core
-----------
All of the deterministic rules above are implemented once, in
``.claude/lib/intent_approval_core.py``, and imported here unchanged. This
hook is a thin PreToolUse adapter over that module: it classifies the
incoming payload (which tool, which file, which Bash command) and calls the
shared validation functions - it does not duplicate their logic. The same
core module is also the sole validation logic used by
``.claude/scripts/intent-approval-recorder.py``, the deterministic
orchestrator that records a PM approval as a single atomic transaction, so
"guard says PASS, CLI says FAIL" for the same on-disk state cannot happen by
construction.

A DRAFT Intent stays fully editable. Structural completeness is only
enforced when the artifact is being validated / staged / committed / moved
to PM_REVIEWED or VALIDATED.

Behaviour
---------
* Reads the Claude Code PreToolUse payload from stdin (JSON).
* Acts only on `Write` / `Edit` / `MultiEdit` calls whose `file_path` is
  `docs/pmo/intent/intent.md`, and on `Bash` calls whose `git add` / `git
  commit` includes that file.
* Every unrelated operation is allowed silently (exit 0, no output).
* A blocked operation emits a structured PreToolUse *deny* response:

    {
      "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "PMO-INTENT-00X: <reason>"
      }
    }

Error IDs
---------
PMO-INTENT-001  PROJECT_NOT_INITIALIZED     - `.pmo/project-config.yaml` missing
                                              at Intent finalisation.
PMO-INTENT-002  INTENT_SCHEMA_INVALID       - required `## N. ...` sections
                                              absent at finalisation.
PMO-INTENT-003  INVALID_WORKFLOW_STAGE      - document control fields missing,
                                              or Next Stage is not
                                              REQUIREMENT_GATHERING (and must
                                              not skip to specs/dev/build).
PMO-INTENT-004  RESERVED_REQUIREMENT_ID     - Intent defines FR-XXX / NFR-XXX.
PMO-INTENT-005  DUPLICATE_IDENTIFIER        - identifier defined twice in its
                                              owning namespace / section.
PMO-INTENT-006  NO_SOURCE_EVIDENCE          - no meaningful external source in
                                              the Source Register at
                                              finalisation.
PMO-INTENT-007  OPEN_ITEM_INCOMPLETE        - an OPEN-XXX record is unmanaged:
                                              a missing Question / Owner /
                                              Blocking (YES|NO) / Required
                                              Before, or a Required Before value
                                              that is not a recognised workflow
                                              stage. Record layout (table row,
                                              subsection or multi-line block)
                                              and length do not matter.
PMO-INTENT-008  INVALID_INTENT_STATUS       - Status is not one of DRAFT /
                                              PM_REVIEWED / VALIDATED /
                                              SUPERSEDED.
PMO-INTENT-009  VALIDATED_INTENT_IMMUTABLE  - Write/Edit against an on-disk
                                              Intent whose Status is VALIDATED.
PMO-INTENT-010  PROJECT_IDENTITY_MISMATCH   - Project ID / Name / Client do not
                                              match `.pmo/project-config.yaml`.
PMO-INTENT-011  PM_APPROVAL_REQUIRED        - promotion to VALIDATED without a
                                              matching PM-explicit approval
                                              record at
                                              `.pmo/approvals/intent-approval.yaml`
                                              (must be decision: APPROVED,
                                              approval_source: PM_EXPLICIT,
                                              artifact + version matching, and
                                              a non-empty approved_by). The
                                              hook never writes this record.
PMO-INTENT-012  INTENT_GUARD_INTERNAL_ERROR - unexpected internal error during
                                              controlled validation (fail
                                              closed).
PMO-INTENT-013  OPEN_BLOCKER_AT_CURRENT_GATE - promotion to VALIDATED while a
                                              well-formed OPEN item is
                                              unresolved with Blocking = YES and
                                              a Required Before gate of
                                              INTENT_VALIDATION or
                                              REQUIREMENT_GATHERING (it must be
                                              resolved before the workflow may
                                              leave Intent). OPEN items gated at
                                              SCOPE_BASELINE or later remain
                                              open through validation and are
                                              carried into Requirement
                                              Gathering.
PMO-INTENT-014  ACCEPTANCE_SECTION_INCONSISTENT - promotion to VALIDATED whose
                                              Section 16 / Acceptance is
                                              missing, stale, or inconsistent
                                              with `.pmo/approvals/intent-
                                              approval.yaml` in the SAME
                                              write. Closes the defect where a
                                              Status flip and the matching
                                              Acceptance update were performed
                                              as two separate writes, leaving
                                              the artifact self-contradictory
                                              once PMO-INTENT-009 made the
                                              second write unreachable.

Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from intent_approval_core import (  # noqa: E402
    INTENT_POSIX,
    INTENT_RELPATH,
    Decision,
    _norm_status,
    deny,
    document_headings,
    find_fr_nfr,
    full_schema_validation,
    identifier_definitions,
    load_project_config,
    missing_sections,
    normalize_stage,
    open_questions_block,
    parse_doc_control,
    parse_open_records,
    parse_status,
    project_root,
    read_text,
    resulting_content,
    section_body,
    validate_acceptance_consistency,
    validate_blocking_open_gate,
    validate_doc_control_fields,
    validate_immutable,
    validate_next_stage,
    validate_no_duplicate_definitions,
    validate_no_fr_nfr,
    validate_open_items,
    validate_pm_approval,
    validate_project_identity,
    validate_sections,
    validate_source_register,
    validate_status_value,
    _light_checks,
)


# --------------------------------------------------------------------------- #
# Hook-output plumbing
# --------------------------------------------------------------------------- #

def emit(decision):
    """Serialise a deny Decision as a Claude Code PreToolUse response."""
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "{code}: {msg}".format(
                code=decision.code, msg=decision.message
            ),
        }
    }
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


# --------------------------------------------------------------------------- #
# Relevant-Bash-command detection
# --------------------------------------------------------------------------- #

_GIT_GLOBAL_VALUE_OPTS = {
    "-C", "-c", "--git-dir", "--work-tree", "--namespace",
    "--super-prefix", "--exec-path",
}
_WRAPPERS = {"env", "sudo", "command", "nice", "time", "xargs", "stdbuf"}
_COMMIT_VALUE_OPTS = {
    "-m", "--message", "-F", "--file", "-C", "--reuse-message",
    "-c", "--reedit-message", "--author", "--date", "-S", "--gpg-sign",
    "--squash", "--fixup", "-t", "--template", "--cleanup", "--trailer",
}
_ADD_VALUE_OPTS = {"--chmod", "--pathspec-from-file"}


def _split_segments(command):
    """Split a shell command on &&, ||, ;, |, & and newlines (quote-aware)."""
    segments, buf, quote, i, n = [], [], None, 0, len(command)
    while i < n:
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(command[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(ch)
            buf.append(command[i + 1])
            i += 2
            continue
        if command[i:i + 2] in ("&&", "||"):
            segments.append("".join(buf))
            buf = []
            i += 2
            continue
        if ch in (";", "\n", "|", "&"):
            segments.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        segments.append("".join(buf))
    return [seg.strip() for seg in segments if seg.strip()]


def _tokenize(segment):
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _git_subcommand(tokens):
    """Return (subcommand, args_after_subcommand) for a git call, else (None, [])."""
    if not tokens:
        return None, []
    idx = 0
    while idx < len(tokens) and os.path.basename(tokens[idx]) in _WRAPPERS:
        idx += 1
        while idx < len(tokens) and ("=" in tokens[idx] or tokens[idx].startswith("-")):
            idx += 1
    if idx >= len(tokens) or os.path.basename(tokens[idx]) != "git":
        return None, []
    i = idx + 1
    while i < len(tokens):
        tok = tokens[i]
        if tok in _GIT_GLOBAL_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("--") and "=" in tok:
            i += 1
            continue
        if tok.startswith("-"):
            i += 1
            continue
        return tok, tokens[i + 1:]
    return None, []


def _strip_value_opts(tokens, value_opts):
    out, i = [], 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in value_opts:
            i += 2
            continue
        if tok.startswith("--") and "=" in tok and tok.split("=", 1)[0] in value_opts:
            i += 1
            continue
        out.append(tok)
        i += 1
    return out


def _looks_like_intent_path(token):
    text = token.strip().strip("'\"")
    if not text:
        return False
    norm = os.path.normpath(text).replace(os.sep, "/")
    return norm == INTENT_POSIX or norm.endswith("/" + INTENT_POSIX)


def _run_git(cwd, args):
    try:
        return subprocess.run(
            ["git", "-C", cwd] + list(args),
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return None


def _git_reports_intent_change(root, staged):
    if staged:
        result = _run_git(root, ["diff", "--cached", "--name-only", "--", INTENT_POSIX])
    else:
        result = _run_git(root, ["status", "--porcelain", "--", INTENT_POSIX])
    if result is None or result.returncode != 0:
        return False
    return bool((result.stdout or "").strip())


def bash_targets_intent(command, root):
    """True when a `git add` / `git commit` in `command` involves intent.md."""
    if not isinstance(command, str) or not command.strip():
        return False
    for segment in _split_segments(command):
        sub, rest = _git_subcommand(_tokenize(segment))
        if sub not in ("add", "commit"):
            continue

        if sub == "add":
            paths = _strip_value_opts(rest, _ADD_VALUE_OPTS)
        else:
            paths = _strip_value_opts(rest, _COMMIT_VALUE_OPTS)

        if any(_looks_like_intent_path(tok) for tok in paths):
            return True

        if sub == "add":
            broad = any(tok in (".", "-A", "--all", "-u", "--update", "*", ":/")
                        for tok in rest)
            broad = broad or any(
                (not tok.startswith("-")) and
                (tok.startswith("docs/pmo") or tok == "docs" or tok.startswith("docs/"))
                for tok in paths
            )
            if broad and _git_reports_intent_change(root, staged=False):
                return True
        else:  # commit
            has_all = any(
                tok in ("-a", "--all") or
                (tok.startswith("-") and not tok.startswith("--") and "a" in tok)
                for tok in rest
            )
            if has_all:
                if _git_reports_intent_change(root, staged=False) or \
                        _git_reports_intent_change(root, staged=True):
                    return True
            elif _git_reports_intent_change(root, staged=True):
                return True
    return False


# --------------------------------------------------------------------------- #
# Path matching
# --------------------------------------------------------------------------- #

def is_intent_file_path(path, root):
    if not isinstance(path, str) or not path.strip():
        return False
    candidate = os.path.normpath(path.strip())
    if not os.path.isabs(candidate):
        candidate = os.path.normpath(os.path.join(root, candidate))
    target = os.path.normpath(os.path.join(root, INTENT_RELPATH))
    if candidate == target:
        return True
    return candidate.replace(os.sep, "/").endswith("/" + INTENT_POSIX)


# --------------------------------------------------------------------------- #
# Controlled validation entry points
# --------------------------------------------------------------------------- #

def process_write_edit(tool_name, tool_input, root):
    """Handle a Write / Edit / MultiEdit against intent.md."""
    intent_path = os.path.join(root, INTENT_RELPATH)
    existing = read_text(intent_path)
    existing_status = parse_status(existing) if existing is not None else None

    # PMO-INTENT-009 - never rewrite a VALIDATED Intent in place.
    blocked = validate_immutable(existing_status)
    if blocked is not None:
        return blocked

    new_content = resulting_content(tool_name, tool_input, existing)
    if new_content is None:
        return None

    meta = parse_doc_control(new_content)
    new_status = _norm_status(meta.get("status"))

    # PMO-INTENT-011 - a VALIDATED transition needs a matching PM approval record.
    blocked = validate_pm_approval(existing_status, new_status, meta, root)
    if blocked is not None:
        return blocked

    blocked = _light_checks(new_content, meta, root)
    if blocked is not None:
        return blocked

    finalizing = new_status in ("PM_REVIEWED", "VALIDATED")
    if not finalizing:
        # Normal DRAFT authoring - incomplete structure is fine.
        return None

    return full_schema_validation(new_content, meta, root, status=new_status)


def process_bash_finalization(root):
    """Handle `git add` / `git commit` that stages or commits intent.md."""
    intent_path = os.path.join(root, INTENT_RELPATH)
    content = read_text(intent_path)
    if content is None:
        # Nothing on disk to protect; let git surface its own error.
        return None

    meta = parse_doc_control(content)

    blocked = _light_checks(content, meta, root)
    if blocked is not None:
        return blocked

    # Staging / committing is a finalisation gate.
    return full_schema_validation(
        content, meta, root, status=parse_status(content)
    )


def process(payload):
    """Classify the payload and return a deny Decision, or None to allow."""
    if not isinstance(payload, dict):
        return None

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None

    cwd = payload.get("cwd") or os.getcwd()
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    root = project_root(cwd)

    if tool_name in ("Write", "Edit", "MultiEdit"):
        if not is_intent_file_path(tool_input.get("file_path"), root):
            return None
        try:
            return process_write_edit(tool_name, tool_input, root)
        except Exception as exc:  # fail closed - PMO-INTENT-012
            return deny(
                "PMO-INTENT-012",
                "PMO Intent guard: unexpected internal error during "
                "controlled Intent validation ({}). Blocking as a "
                "precaution.".format(exc),
            )

    if tool_name == "Bash":
        command = tool_input.get("command") or ""
        try:
            if not bash_targets_intent(command, root):
                return None
            return process_bash_finalization(root)
        except Exception as exc:  # fail closed - PMO-INTENT-012
            return deny(
                "PMO-INTENT-012",
                "PMO Intent guard: unexpected internal error while validating "
                "a git operation on intent.md ({}). Blocking as a "
                "precaution.".format(exc),
            )

    return None


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
        # Cannot read the hook payload -> cannot classify -> stay out of the way.
        return 0

    try:
        decision = process(payload)
    except Exception:
        # Classification itself failed on an unrelated call - do not interfere.
        return 0

    if decision is not None:
        emit(decision)
    return 0


if __name__ == "__main__":
    sys.exit(main())
