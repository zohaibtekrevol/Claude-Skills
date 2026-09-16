#!/usr/bin/env python3
"""PMO Questions & Assumptions register guard (Claude Code PreToolUse hook).

Deterministic governance for the canonical NEW-lifecycle requirements
artifact:

    docs/pmo/requirements/questions-and-assumptions.md

which replaces Scope generation for a project with no pre-existing Scope
lineage (see `.claude/skills/requirement-gathering/SKILL.md`). The
*requirement-gathering skill* performs the semantic work (reading Intent +
source evidence, deciding what is genuinely still open). This hook owns only
the mechanical, deterministic controls: canonical path, project identity,
Document Control completeness, record id stability, Type/Status/Blocking
validity, resolution-required-when-a-record-claims-resolution, and no silent
loss of a previously recorded resolution.

Behaviour
---------
* Reads the Claude Code PreToolUse payload from stdin (JSON).
* Acts on `Write` / `Edit` / `MultiEdit` whose `file_path` is
  `docs/pmo/requirements/questions-and-assumptions.md` (or a forbidden
  non-canonical variant of it), and on `Bash` `git add` / `git commit` that
  includes the canonical file.
* Every unrelated operation is allowed silently (exit 0, no output).
* The register carries no document-level draft/final status of its own -
  each record's own `Status` already carries that distinction - so, unlike
  the Scope guard, full structural validation runs on every write, not only
  at a separate finalisation gate. This is deliberately NOT a
  marker-file/transaction system: the register is a single ordinary
  Markdown file, validated deterministically on each save, exactly the
  "PM resolution stays file/Git based" instruction requires.
* A blocked operation emits a structured PreToolUse deny response:
    {"hookSpecificOutput": {"hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": "<PMO-QA-0XX>: <reason>"}}

Error IDs
---------
PMO-QA-001  INTENT_NOT_VALIDATED       - the canonical Intent is absent, not
                                        VALIDATED, lacks a structurally valid
                                        matching PM approval record, or its
                                        project identity does not match
                                        project-config.yaml. Reuses
                                        `qa_register_core.validate_prerequisite_intent`
                                        (itself reusing
                                        `intent_approval_core.validate_pm_approval`
                                        unchanged) - the same rule
                                        `scope-version-guard.py` enforces as
                                        PMO-SCOPE-001.
PMO-QA-002  PROJECT_IDENTITY_MISMATCH  - the register's Document Control
                                        Project / Client / Project ID does
                                        not match project-config.yaml.
PMO-QA-003  QA_SCHEMA_INVALID          - a required Document Control field is
                                        absent, or a record is missing a
                                        required field (Statement / Why
                                        Resolution Is Required / Source /
                                        Evidence / Owner).
PMO-QA-004  INVALID_TYPE               - a record's Type is not QUESTION or
                                        ASSUMPTION.
PMO-QA-005  INVALID_STATUS             - a record's Status is not one of
                                        OPEN / CONFIRMED / REJECTED /
                                        RESOLVED / DEFERRED / NON_BLOCKING.
PMO-QA-006  INVALID_BLOCKING           - a record's Blocking value is not
                                        explicitly YES or NO.
PMO-QA-007  DUPLICATE_OR_INVALID_ID    - a record id is defined more than
                                        once, or is not exactly `QST-###` /
                                        `ASM-###`.
PMO-QA-008  RESOLUTION_REQUIRED        - a record claims CONFIRMED / REJECTED
                                        / RESOLVED / DEFERRED / NON_BLOCKING
                                        without the Resolution fields that
                                        status requires.
PMO-QA-009  RESOLUTION_REGRESSION      - a previously recorded resolution or
                                        disposition was silently blanked or
                                        the record disappeared, without an
                                        explicit reopen (Status: OPEN).
PMO-QA-010  NON_CANONICAL_QA_PATH      - the live Q&A artifact is not
                                        docs/pmo/requirements/questions-and-assumptions.md.
PMO-QA-011  QA_GUARD_INTERNAL_ERROR    - unexpected exception during a
                                        controlled Q&A validation (fail
                                        closed).

Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

# Imported under its own namespace on purpose - see the module docstring in
# qa_register_core.py for why (mirrors scope-version-guard.py's `iac.*`
# convention).
import qa_register_core as qac  # noqa: E402


# --------------------------------------------------------------------------- #
# Decision plumbing
# --------------------------------------------------------------------------- #

class Decision(object):
    __slots__ = ("code", "message")

    def __init__(self, code, message):
        self.code = code
        self.message = message


def deny(code, message):
    return Decision(code, message)


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
# Filesystem / path helpers
# --------------------------------------------------------------------------- #

def locate_project_root(cwd):
    cur = os.path.abspath(cwd or os.getcwd())
    for _ in range(64):
        if os.path.isdir(os.path.join(cur, ".pmo")) or \
                os.path.isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.abspath(cwd or os.getcwd())


def _relpath(p, root):
    p = (p or "").strip().strip('"').strip("'")
    if not p:
        return ""
    ap = p if os.path.isabs(p) else os.path.normpath(os.path.join(root, p))
    try:
        return os.path.relpath(ap, root).replace(os.sep, "/")
    except Exception:
        return p.replace(os.sep, "/")


def _abspath(rel_posix, root):
    return os.path.join(root, *rel_posix.split("/"))


# --------------------------------------------------------------------------- #
# Write/Edit content reconstruction (same convention as the sibling guards)
# --------------------------------------------------------------------------- #

def resulting_content(tool_name, tool_input, existing):
    if tool_name == "Write":
        c = tool_input.get("content")
        return c if isinstance(c, str) else ""
    base = existing or ""
    if tool_name == "Edit":
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        if not isinstance(old, str) or not isinstance(new, str):
            return base
        if tool_input.get("replace_all"):
            return base.replace(old, new)
        if old == "":
            return new if base == "" else base
        return base.replace(old, new, 1)
    if tool_name == "MultiEdit":
        for edit in tool_input.get("edits", []) or []:
            if not isinstance(edit, dict):
                continue
            old = edit.get("old_string", "")
            new = edit.get("new_string", "")
            if not isinstance(old, str) or not isinstance(new, str):
                continue
            if edit.get("replace_all"):
                base = base.replace(old, new)
            elif old == "":
                base = new if base == "" else base
            else:
                base = base.replace(old, new, 1)
        return base
    return None


# --------------------------------------------------------------------------- #
# Full deterministic validation
# --------------------------------------------------------------------------- #

def full_qa_validation(new_text, root, disk_text=None):
    """Every deterministic check, in order. Returns the first Decision, or
    None when the register is clean. Fails closed."""
    try:
        prereq_err = qac.validate_prerequisite_intent(root)
        if prereq_err is not None:
            return deny("PMO-QA-001", prereq_err)

        dc_err = qac.validate_doc_control(new_text)
        if dc_err is not None:
            return deny("PMO-QA-003", dc_err)

        cfg = qac.iac.load_project_config(root)
        if isinstance(cfg, dict):
            meta = qac.parse_qa_metadata(new_text)
            identity_err = qac.validate_qa_project_identity(meta, cfg)
            if identity_err is not None:
                return deny("PMO-QA-002", identity_err)

        blocks = qac.parse_qa_record_blocks(new_text)
        dups = qac.find_duplicate_ids(blocks)
        if dups:
            return deny(
                "PMO-QA-007",
                "duplicate Q&A record id(s): {}. Each id is defined exactly "
                "once (repeated references elsewhere are fine).".format(
                    ", ".join(dups)),
            )
        malformed = qac.find_malformed_ids(new_text)
        if malformed:
            return deny(
                "PMO-QA-007",
                "malformed Q&A record id(s): {} (expected exactly QST-### or "
                "ASM-###).".format(", ".join(malformed)),
            )

        records = [qac.parse_qa_record(rid, block) for rid, block in blocks]
        for rec in records:
            msg = qac.check_required_fields(rec)
            if msg is not None:
                return deny("PMO-QA-003", msg)
            msg = qac.check_type(rec)
            if msg is not None:
                return deny("PMO-QA-004", msg)
            msg = qac.check_status(rec)
            if msg is not None:
                return deny("PMO-QA-005", msg)
            msg = qac.check_blocking(rec)
            if msg is not None:
                return deny("PMO-QA-006", msg)
            msg = qac.check_resolution_completeness(rec)
            if msg is not None:
                return deny("PMO-QA-008", msg)

        if disk_text is not None:
            reg = qac.detect_resolution_regression(disk_text, new_text)
            if reg is not None:
                return deny("PMO-QA-009", reg)

        return None
    except Exception as exc:  # fail closed
        return deny(
            "PMO-QA-011",
            "unexpected internal error during Q&A register validation "
            "({!r}); blocking as a precaution.".format(exc),
        )


# --------------------------------------------------------------------------- #
# Payload dispatch
# --------------------------------------------------------------------------- #

def process_write_edit(tool_name, tool_input, root):
    path = tool_input.get("file_path")
    if not isinstance(path, str) or not path.strip():
        return None
    rel = _relpath(path, root)

    bad = qac.validate_canonical_qa_path(rel)
    if bad is not None:
        return deny("PMO-QA-010", bad)

    if rel != qac.QA_FILE_POSIX:
        return None

    disk_text = qac.read_text(_abspath(qac.QA_FILE_POSIX, root))
    new_text = resulting_content(tool_name, tool_input, disk_text)
    if new_text is None:
        return None

    return full_qa_validation(new_text, root, disk_text=disk_text)


_WRAPPERS = {"env", "sudo", "command", "nice", "time", "xargs", "stdbuf"}


def _split_segments(command):
    parts = re.split(r"&&|\|\||[;\n|&]", command or "")
    return [p.strip() for p in parts if p.strip()]


def _tokenize(segment):
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _git_subcommand(tokens):
    if not tokens:
        return None, []
    idx = 0
    while idx < len(tokens) and os.path.basename(tokens[idx]) in _WRAPPERS:
        idx += 1
        while idx < len(tokens) and ("=" in tokens[idx] or tokens[idx].startswith("-")):
            idx += 1
    if idx >= len(tokens) or os.path.basename(tokens[idx]) != "git":
        return None, []
    return tokens[idx + 1] if idx + 1 < len(tokens) else None, tokens[idx + 2:]


def detect_relevant_git_action(command):
    """True when a `git add` / `git commit` in `command` stages/commits the
    canonical Q&A register."""
    if not isinstance(command, str) or not command.strip():
        return False
    for segment in _split_segments(command):
        sub, rest = _git_subcommand(_tokenize(segment))
        if sub not in ("add", "commit"):
            continue
        broad = any(t in (".", "-A", "--all", "-u", "--update", "*", ":/")
                    for t in rest)
        explicit = any(
            (not t.startswith("-"))
            and (t.rstrip("/").endswith("questions-and-assumptions.md")
                 or t.rstrip("/") in ("docs", "docs/pmo", "docs/pmo/requirements"))
            for t in rest
        )
        allflag = sub == "commit" and any(
            t in ("-a", "--all")
            or (t.startswith("-") and not t.startswith("--") and "a" in t)
            for t in rest
        )
        if broad or explicit or allflag:
            return True
    return False


def process_bash(command, root):
    if not detect_relevant_git_action(command):
        return None
    text = qac.read_text(_abspath(qac.QA_FILE_POSIX, root))
    if text is None:
        return None
    return full_qa_validation(text, root, disk_text=None)


def process(payload):
    if not isinstance(payload, dict):
        return None
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None
    cwd = payload.get("cwd") or os.getcwd()
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    root = locate_project_root(cwd)

    if tool_name in ("Write", "Edit", "MultiEdit"):
        try:
            return process_write_edit(tool_name, tool_input, root)
        except Exception as exc:  # fail closed
            return deny(
                "PMO-QA-011",
                "unexpected internal error during Q&A write validation "
                "({!r}); blocking as a precaution.".format(exc),
            )

    if tool_name == "Bash":
        command = tool_input.get("command") or ""
        try:
            return process_bash(command, root)
        except Exception as exc:  # fail closed
            return deny(
                "PMO-QA-011",
                "unexpected internal error validating a git operation on the "
                "Q&A register ({!r}); blocking as a precaution.".format(exc),
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
