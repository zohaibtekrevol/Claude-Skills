#!/usr/bin/env python3
"""PMO change-request-governance-guard (Claude Code PreToolUse hook).

Deterministic, fail-closed governance for the artifacts owned by the
``change-request-management`` Skill
(``.claude/skills/change-request-management/SKILL.md``): the full Change
Request lifecycle for both origins (``CLIENT_REQUESTED`` and
``PM_PROPOSED``), and the single governed incorporation transaction an
``APPROVED`` CR must pass through to reach ``INCORPORATED``.

Transaction-scoped, dual-authority model (Phase 2B)
-----------------------------------------------------
``docs/pmo/cr/change-request-register.md`` and ``docs/pmo/cr/CR-NNN.md`` can
be legitimately governed by *either*:

* an open **feedback** transaction (``feedback-governance-guard.py``'s own
  narrow authority: ``CLIENT_REQUESTED`` origin, ``DRAFT``/``CANCELLED``
  status only - unchanged since Phase 1D), or
* an open **change-request** transaction (this guard's full authority:
  every origin, every lifecycle transition, incorporation) -

never both at once. Rather than either guard trying to infer the other's
intent, **domain routing is content-based**: a CR write whose *resulting*
content is exactly the feedback-safe shape (``Origin: CLIENT_REQUESTED``,
``Status`` in ``{DRAFT, CANCELLED}``) is left to the feedback transaction
(this guard defers - returns ``None`` - unless a change-request marker is
*also* open, which is the mutually-exclusive conflict case). Any other
shape (``PM_PROPOSED`` origin, or a status outside ``{DRAFT, CANCELLED}``)
is unconditionally this guard's territory and requires an OPEN
``.pmo/change-request-transaction.json`` - with no such marker, it is
denied here directly (not merely left to the other guard), because that
shape was never within the feedback guard's authority either. This mirrors,
and was verified against, the symmetric delegation
``feedback-governance-guard.py`` implements on its own side (see that
file's module docstring, "Phase 2B: CR-path authority is transaction-scoped").

Change Request transaction marker
------------------------------------
Path: ``.pmo/change-request-transaction.json``. Schema (mirrors
``.claude/skills/change-request-management/SKILL.md`` Section 25):

    {
      "transaction_type": "CHANGE_REQUEST_MANAGEMENT",
      "transaction_id": "<opaque, unique per run>",
      "project_id": "<must equal .pmo/project-config.yaml project.id>",
      "cr_id": "CR-NNN or null (null only while operation == CREATE_PM_PROPOSED, before allocation)",
      "operation": "CREATE_PM_PROPOSED | STATE_TRANSITION | APPROVAL | REJECTION | DEFERRAL | CANCELLATION | INCORPORATION",
      "started_at": "<ISO 8601 UTC, set once, never rewritten>",
      "status": "ACTIVE | RECONCILING | RECOVERY_REQUIRED",
      "baseline_scope_version": "<only meaningful for INCORPORATION>",
      "baseline_scope_hash": "<...>",
      "baseline_specs_version": "<...>",
      "baseline_specs_hash": "<...>"
    }

``operation`` is a closed enum - never arbitrary free text. Only
``operation == "INCORPORATION"`` (with the CR already ``APPROVED``)
authorises any write to ``docs/pmo/scope/``, ``docs/pmo/specs/specs.md``, or
``docs/pmo/change-log/``; every other operation keeps those three paths
denied, exactly as when no CR transaction exists at all.

Scope/Specs schema is NOT re-validated here
-----------------------------------------------
``scope-version-guard.py`` and ``specs-governance-guard.py`` already fire
independently on every write to their respective files and fully validate
structure/identifiers/versioning regardless of caller. This guard adds only
the CR-transaction-specific layer on top: whether the write is authorised at
all right now, whether it targets a genuinely new (never-existing) Scope
version file, whether the Spec Version actually advanced, and whether the
``Change Source: CR-NNN`` tag and version lineage are present and consistent
with the transaction's own baseline and with the Change Log entry it
produces. It never re-implements those other guards' full schema checks.

Error IDs - dedicated namespace, disjoint from PMO-FEEDBACK-*,
PMO-FEEDBACK-GUARD-*, PMO-SCOPE-*, PMO-SPEC-*, PMO-PUBLISH-*.
-----------------------------------------------------------------------------
PMO-CR-GUARD-001  PROJECT_IDENTITY_INVALID
PMO-CR-GUARD-002  INVALID_ARTIFACT_PATH
PMO-CR-GUARD-003  INVALID_CR_ID
PMO-CR-GUARD-004  CR_ID_REUSE_OR_COLLISION
PMO-CR-GUARD-005  INVALID_ORIGIN
PMO-CR-GUARD-006  INVALID_STATE_TRANSITION
PMO-CR-GUARD-007  MISSING_APPROVAL_EVIDENCE
PMO-CR-GUARD-008  INVALID_PROVENANCE
PMO-CR-GUARD-009  HISTORY_DELETION_OR_REWRITE
PMO-CR-GUARD-010  INVALID_CANCELLATION
PMO-CR-GUARD-011  INCORPORATED_CANCELLATION_ATTEMPT
PMO-CR-GUARD-012  UNAUTHORIZED_SCOPE_MUTATION
PMO-CR-GUARD-013  UNAUTHORIZED_SPECS_MUTATION
PMO-CR-GUARD-014  UNAUTHORIZED_CHANGE_LOG_MUTATION
PMO-CR-GUARD-015  VERSION_MISMATCH
PMO-CR-GUARD-016  CHANGE_SOURCE_MISMATCH
PMO-CR-GUARD-017  TRACEABILITY_MISMATCH
PMO-CR-GUARD-018  PREMATURE_INCORPORATED
PMO-CR-GUARD-019  PARTIAL_TRANSACTION
PMO-CR-GUARD-020  PROJECT_CONFIG_OVERREACH
PMO-CR-GUARD-021  PUBLICATION_BOUNDARY_VIOLATION
PMO-CR-GUARD-022  INVALID_TRANSACTION_MARKER
PMO-CR-GUARD-023  TRANSACTION_MARKER_OVERWRITE
PMO-CR-GUARD-024  NO_ACTIVE_TRANSACTION
PMO-CR-GUARD-025  CONFLICTING_TRANSACTION_MARKERS
PMO-CR-GUARD-026  GUARD_INTERNAL_ERROR       (fail closed)

Behaviour
---------
* Reads the Claude Code PreToolUse payload from stdin (JSON).
* Acts only on ``Write`` / ``Edit`` / ``MultiEdit``. Does not govern
  ``Bash`` / git - ``repo-binding-guard.py`` and ``artifact-publish-
  guard.py`` remain authoritative there; this guard never duplicates that.
* Project routing is read from ``.pmo/project-config.yaml``; no project
  identity is hardcoded.
* A blocked operation emits the standard PreToolUse deny response; an
  allowed or out-of-scope operation produces no output and exits 0.
* Any unexpected exception while validating an in-scope write fails closed
  (``PMO-CR-GUARD-026``).

Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import json
import os
import re
import sys


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

CR_DIR_POSIX = "docs/pmo/cr"
CR_REGISTER_POSIX = "docs/pmo/cr/change-request-register.md"

CHANGE_LOG_DIR_POSIX = "docs/pmo/change-log"
CHANGE_LOG_POSIX = "docs/pmo/change-log/change-log.md"

SCOPE_DIR_POSIX = "docs/pmo/scope"
SPECS_POSIX = "docs/pmo/specs/specs.md"

CONFIG_RELPATH = ".pmo/project-config.yaml"

CR_MARKER_POSIX = ".pmo/change-request-transaction.json"
CR_MARKER_RELPATH_PARTS = (".pmo", "change-request-transaction.json")
FEEDBACK_MARKER_RELPATH_PARTS = (".pmo", "feedback-transaction.json")

TEMPLATE_CR_NAME = "_TEMPLATE-CR.md"

CR_FILE_RE = re.compile(r"^CR-(\d+)\.md$")
CR_ID_RE = re.compile(r"^CR-\d+$")
CHG_ID_RE = re.compile(r"^CHG-\d+$")
BATCH_ID_RE = re.compile(r"^FB-\d{4}-\d{3}$")
ITEM_ID_RE = re.compile(r"^FB-\d{4}-\d{3}-\d{3}$")
SCOPE_FILE_RE = re.compile(r"^scope-v(\d+)\.(\d+)\.md$")

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

PM_PROPOSED_LITERAL = "No Feedback ID — PM_PROPOSED"

ALL_CR_STATUSES = {
    "DRAFT", "PM_REVIEW", "PENDING_CLIENT_DECISION", "APPROVED",
    "REJECTED", "DEFERRED", "CANCELLED", "INCORPORATED",
}
FEEDBACK_SAFE_STATUSES = {"DRAFT", "CANCELLED"}
ALL_ORIGINS = {"CLIENT_REQUESTED", "PM_PROPOSED"}

# Section 11 of change-request-management/SKILL.md - the approved matrix.
# Absent key / absent target => not a valid transition (terminal or unknown).
TRANSITIONS = {
    "DRAFT": {"PM_REVIEW", "CANCELLED"},
    "PM_REVIEW": {"PENDING_CLIENT_DECISION", "DEFERRED", "CANCELLED"},
    "PENDING_CLIENT_DECISION": {"PM_REVIEW", "APPROVED", "REJECTED", "DEFERRED"},
    "APPROVED": {"CANCELLED", "INCORPORATED"},
    "DEFERRED": {"PM_REVIEW", "CANCELLED"},
    "REJECTED": set(),
    "CANCELLED": set(),
    "INCORPORATED": set(),
}
# Statuses whose entry requires Decision/Decision Date/Decision By non-empty.
DECISION_REQUIRED_FOR = {"APPROVED", "REJECTED", "DEFERRED", "CANCELLED"}
# Statuses whose entry additionally requires Rejection/Deferral Reason.
REASON_REQUIRED_FOR = {"REJECTED", "DEFERRED", "CANCELLED"}

CR_MARKER_REQUIRED_FIELDS = (
    "transaction_type", "transaction_id", "project_id", "operation",
    "started_at", "status",
)
ALLOWED_OPERATIONS = {
    "CREATE_PM_PROPOSED", "STATE_TRANSITION", "APPROVAL", "REJECTION",
    "DEFERRAL", "CANCELLATION", "INCORPORATION",
}
ALLOWED_MARKER_STATUSES = {"ACTIVE", "RECONCILING", "RECOVERY_REQUIRED"}
OPEN_MARKER_STATUSES = {"ACTIVE", "RECONCILING"}
MARKER_STATUS_TRANSITIONS = {
    "ACTIVE": {"ACTIVE", "RECONCILING", "RECOVERY_REQUIRED"},
    "RECONCILING": {"RECONCILING", "ACTIVE", "RECOVERY_REQUIRED"},
    "RECOVERY_REQUIRED": {"RECOVERY_REQUIRED", "ACTIVE", "RECONCILING"},
}

# Fields this guard may ever write in .pmo/project-config.yaml, and only
# in the circumstances noted (see config_diff_violations call sites).
BASE_CONFIG_WHITELIST = {"artifacts.change_requests.latest_id"}
INCORPORATION_CONFIG_WHITELIST = BASE_CONFIG_WHITELIST | {
    "artifacts.change_log.latest_id",
    "artifacts.change_log.total_count",
    "artifacts.scope.latest_version",
    "artifacts.specifications.latest_version",
    "artifacts.specifications.derived_from_scope_version",
}

_EMPTYISH = {"", "none", "n/a", "-", "null"}


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


def allow():
    return None


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
# Minimal YAML subset parser (same stdlib-only subset as the other guards)
# --------------------------------------------------------------------------- #

def _strip_comment(line):
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (i == 0 or line[i - 1] in (" ", "\t")):
            break
        out.append(ch)
    return "".join(out)


def _parse_scalar(text):
    s = text.strip()
    if s == "" or s in ("null", "Null", "NULL", "~"):
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    if s == "[]":
        return []
    if s == "{}":
        return {}
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    return s


def parse_project_config(text):
    root = {}
    stack = [(-1, root)]
    pending = None
    for raw in (text or "").splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        s = line.strip()
        if s in ("---", "..."):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if pending is not None:
            p_indent, p_parent, p_key = pending
            if indent > p_indent and (s.startswith("- ") or s == "-"):
                new_list = []
                p_parent[p_key] = new_list
                top_indent, _ = stack[-1]
                stack[-1] = (top_indent, new_list)
            pending = None
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        container = stack[-1][1]
        if s.startswith("- ") or s == "-":
            if not isinstance(container, list):
                continue
            item = s[2:] if s.startswith("- ") else ""
            stripped = item.strip()
            if ":" in stripped and not stripped.startswith(('"', "'")):
                key, _, rest = stripped.partition(":")
                d = {key.strip(): _parse_scalar(rest.strip())}
                container.append(d)
                stack.append((indent, d))
            else:
                container.append(_parse_scalar(item))
            continue
        if ":" not in s:
            continue
        key, _, rest = s.partition(":")
        key, rest = key.strip(), rest.strip()
        if not isinstance(container, dict):
            continue
        if rest == "":
            child = {}
            container[key] = child
            stack.append((indent, child))
            pending = (indent, container, key)
        else:
            container[key] = _parse_scalar(rest)
    return root


def flatten(value, prefix=""):
    out = {}
    if isinstance(value, dict):
        for k, v in value.items():
            key = "{}.{}".format(prefix, k) if prefix else str(k)
            out.update(flatten(v, key))
    elif isinstance(value, list):
        out[prefix] = repr(value)
    else:
        out[prefix] = value
    return out


def config_diff_violations(before_text, after_text, whitelist):
    try:
        before = parse_project_config(before_text)
    except Exception:
        before = {}
    try:
        after = parse_project_config(after_text)
    except Exception:
        after = {}
    fb = flatten(before)
    fa = flatten(after)
    keys = set(fb) | set(fa)
    changed = [k for k in keys if fb.get(k) != fa.get(k)]
    return sorted(k for k in changed if k not in whitelist)


# --------------------------------------------------------------------------- #
# Filesystem helpers
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


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        return None


def load_config(root):
    text = read_text(os.path.join(root, *CONFIG_RELPATH.split("/")))
    if text is None:
        return None
    try:
        data = parse_project_config(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def posix_rel(abspath, root):
    try:
        rel = os.path.relpath(abspath, root)
    except Exception:
        return None
    return rel.replace(os.sep, "/")


def resulting_content(tool_name, tool_input, existing):
    if tool_name == "Write":
        c = tool_input.get("content")
        return c if isinstance(c, str) else None
    base = existing if existing is not None else ""
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
# Markdown pipe-table parsing (stdlib only, deterministic)
# --------------------------------------------------------------------------- #

def _split_row(line):
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def _is_separator_row(cells):
    if not cells:
        return False
    return all(re.match(r"^:?-{2,}:?$", c.strip()) for c in cells if c.strip() != "")


def find_tables(content):
    lines = (content or "").splitlines()
    n = len(lines)
    out = []
    i = 0
    while i < n:
        line = lines[i].strip()
        if line.startswith("|") and line.endswith("|") and i + 1 < n:
            sep_line = lines[i + 1].strip()
            if sep_line.startswith("|"):
                sep_cells = _split_row(sep_line)
                if _is_separator_row(sep_cells):
                    headers = _split_row(lines[i])
                    j = i + 2
                    rows = []
                    while j < n:
                        row_line = lines[j].strip()
                        if row_line.startswith("|") and row_line.endswith("|"):
                            rows.append(_split_row(lines[j]))
                            j += 1
                        else:
                            break
                    out.append((i, headers, rows))
                    i = j
                    continue
        i += 1
    return out


def first_table(text):
    tables = find_tables(text)
    if not tables:
        return None, None
    _, headers, rows = tables[0]
    return headers, rows


def table_by_header_prefix(content, first_header_text):
    for (_idx, headers, rows) in find_tables(content):
        if headers and headers[0].strip().lower() == first_header_text.strip().lower():
            return headers, rows
    return None, None


def field_map_from_table(headers, rows):
    out = {}
    if not headers:
        return out
    for row in rows:
        if not row:
            continue
        field = row[0].strip()
        if not field or field.startswith("_("):
            continue
        value = row[-1].strip() if len(row) > 1 else ""
        out[field] = value
    return out


def rows_as_dicts(headers, rows):
    out = []
    if not headers:
        return out
    for row in rows:
        if not row:
            continue
        first_cell = row[0].strip()
        if not first_cell or first_cell.startswith("_("):
            continue
        d = {}
        for i, h in enumerate(headers):
            d[h.strip()] = row[i].strip() if i < len(row) else ""
        out.append(d)
    return out


def _clean(value):
    v = (value or "").strip()
    return "" if v.lower() in _EMPTYISH else v


# --------------------------------------------------------------------------- #
# Change-request transaction marker
# --------------------------------------------------------------------------- #

def parse_cr_marker(text):
    """Returns (data, error). error is None iff structurally/semantically
    valid: required fields present, transaction_type/operation/status from
    their closed enums, started_at timestamp-shaped, cr_id null or a valid
    CR-NNN id."""
    try:
        data = json.loads(text)
    except Exception as exc:
        return None, "marker is not valid JSON ({})".format(exc)
    if not isinstance(data, dict):
        return None, "marker JSON must be an object"
    for field in CR_MARKER_REQUIRED_FIELDS:
        if field not in data or data.get(field) in (None, ""):
            return None, "marker is missing required field '{}'".format(field)
    if data.get("transaction_type") != "CHANGE_REQUEST_MANAGEMENT":
        return None, "marker transaction_type must be 'CHANGE_REQUEST_MANAGEMENT'"
    if data.get("operation") not in ALLOWED_OPERATIONS:
        return None, "marker operation '{}' is not one of {}".format(
            data.get("operation"), sorted(ALLOWED_OPERATIONS))
    if data.get("status") not in ALLOWED_MARKER_STATUSES:
        return None, "marker status '{}' is not one of {}".format(
            data.get("status"), sorted(ALLOWED_MARKER_STATUSES))
    if not TIMESTAMP_RE.match(str(data.get("started_at"))):
        return None, "marker started_at is not a recognisable ISO 8601 timestamp"
    cr_id = data.get("cr_id")
    if cr_id not in (None, "") and not CR_ID_RE.match(str(cr_id)):
        return None, "marker cr_id '{}' is not a valid CR-NNN id".format(cr_id)
    if cr_id in (None, "") and data.get("operation") != "CREATE_PM_PROPOSED":
        return None, "marker cr_id may only be null while operation is CREATE_PM_PROPOSED"
    return data, None


def cr_marker_status(root):
    """(state, data, error). state in ABSENT / OPEN / BLOCKED / INVALID /
    WRONG_PROJECT - INVALID and WRONG_PROJECT are kept distinct so callers
    can raise PMO-CR-GUARD-022 (malformed) vs PMO-CR-GUARD-001 (identity)
    with an accurate code, though both otherwise behave as 'not open'."""
    text = read_text(os.path.join(root, *CR_MARKER_RELPATH_PARTS))
    if text is None:
        return "ABSENT", None, None
    data, err = parse_cr_marker(text)
    if err is not None:
        return "INVALID", None, err
    config = load_config(root)
    pid = (config or {}).get("project", {}).get("id") if config else None
    if pid and str(data.get("project_id")).strip().upper() != str(pid).strip().upper():
        return "WRONG_PROJECT", data, (
            "marker project_id '{}' does not match the configured "
            "project.id '{}'".format(data.get("project_id"), pid)
        )
    if data.get("status") in OPEN_MARKER_STATUSES:
        return "OPEN", data, None
    return "BLOCKED", data, None


def feedback_marker_is_open(root):
    """Minimal, read-only mirror of feedback-governance-guard.py's own
    cr_marker_is_open(): used only to detect the mutually-exclusive
    both-transactions-active case. Never interprets feedback-transaction
    content beyond that."""
    text = read_text(os.path.join(root, *FEEDBACK_MARKER_RELPATH_PARTS))
    if text is None:
        return False
    try:
        data = json.loads(text)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    if data.get("transaction_type") != "FEEDBACK_MANAGEMENT":
        return False
    if data.get("status") not in ("ACTIVE", "RECONCILING"):
        return False
    config = load_config(root)
    pid = (config or {}).get("project", {}).get("id") if config else None
    if pid and str(data.get("project_id", "")).strip().upper() != str(pid).strip().upper():
        return False
    return True


def validate_marker_write(tool_name, tool_input, root):
    """Governs Write/Edit/MultiEdit to .pmo/change-request-transaction.json
    itself - same discipline as feedback-governance-guard.py's own marker:
    fresh creation must be fully valid; an existing marker may only be
    updated in place for the SAME transaction_id/started_at/cr_id-once-set,
    with a status transition drawn from MARKER_STATUS_TRANSITIONS; a
    different transaction_id, or editing an invalid existing marker, is
    refused - remove it out-of-band first."""
    marker_abspath = os.path.join(root, *CR_MARKER_RELPATH_PARTS)
    existing = read_text(marker_abspath)
    new_content = resulting_content(tool_name, tool_input, existing)
    if new_content is None:
        return None

    new_data, new_err = parse_cr_marker(new_content)
    if new_err is not None:
        return deny(
            "PMO-CR-GUARD-022",
            "refusing to write .pmo/change-request-transaction.json: "
            "{}.".format(new_err),
        )

    config = load_config(root)
    pid = (config or {}).get("project", {}).get("id") if config else None
    if pid and str(new_data.get("project_id")).strip().upper() != str(pid).strip().upper():
        return deny(
            "PMO-CR-GUARD-001",
            "refusing to write a transaction marker for project_id '{}' - "
            "the configured project is '{}'.".format(new_data.get("project_id"), pid),
        )

    if existing is None:
        return None  # fresh, schema-valid creation for the right project

    old_data, old_err = parse_cr_marker(existing)
    if old_err is not None:
        return deny(
            "PMO-CR-GUARD-022",
            "an existing .pmo/change-request-transaction.json is present "
            "but invalid ({}) - it must be removed out-of-band before a new "
            "transaction can start.".format(old_err),
        )

    if old_data.get("transaction_id") != new_data.get("transaction_id"):
        return deny(
            "PMO-CR-GUARD-023",
            "an existing transaction marker (transaction_id '{}') may not "
            "be silently replaced by a different transaction_id "
            "('{}').".format(old_data.get("transaction_id"),
                             new_data.get("transaction_id")),
        )
    if old_data.get("started_at") != new_data.get("started_at"):
        return deny(
            "PMO-CR-GUARD-023",
            "transaction '{}' may not change its started_at once "
            "created.".format(new_data.get("transaction_id")),
        )
    old_cr_id = old_data.get("cr_id")
    new_cr_id = new_data.get("cr_id")
    if old_cr_id not in (None, "") and old_cr_id != new_cr_id:
        return deny(
            "PMO-CR-GUARD-023",
            "transaction '{}' may not change its cr_id once allocated "
            "({} -> {}).".format(new_data.get("transaction_id"),
                                 old_cr_id, new_cr_id),
        )
    if old_data.get("operation") != new_data.get("operation"):
        return deny(
            "PMO-CR-GUARD-023",
            "transaction '{}' may not change its operation once "
            "created.".format(new_data.get("transaction_id")),
        )
    allowed_next = MARKER_STATUS_TRANSITIONS.get(old_data.get("status"), set())
    if new_data.get("status") not in allowed_next:
        return deny(
            "PMO-CR-GUARD-023",
            "transaction '{}' may not move from status '{}' to "
            "'{}'.".format(new_data.get("transaction_id"),
                          old_data.get("status"), new_data.get("status")),
        )
    return None


# --------------------------------------------------------------------------- #
# Scope / Specs / Change Log readers (used only for baseline / reconciliation)
# --------------------------------------------------------------------------- #

def list_scope_versions(root):
    """[(major, minor, abspath), ...] for every docs/pmo/scope/scope-v*.md."""
    dirpath = os.path.join(root, "docs", "pmo", "scope")
    try:
        names = os.listdir(dirpath)
    except Exception:
        return []
    out = []
    for name in names:
        m = SCOPE_FILE_RE.match(name)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), os.path.join(dirpath, name)))
    return sorted(out)


def latest_scope_version(root):
    versions = list_scope_versions(root)
    return versions[-1] if versions else None


def read_specs_spec_version(root):
    content = read_text(os.path.join(root, *SPECS_POSIX.split("/")))
    if content is None:
        return None, None
    fields = field_map_from_table(*first_table(content))
    return fields.get("Spec Version"), content


def read_cr_fields(root, cr_id):
    path = os.path.join(root, "docs", "pmo", "cr", cr_id + ".md")
    content = read_text(path)
    if content is None:
        return None
    return field_map_from_table(*first_table(content))


def find_changelog_row_for_cr(content, cr_id):
    headers, rows = table_by_header_prefix(content or "", "CHG ID")
    if not headers:
        return None
    for entry in rows_as_dicts(headers, rows):
        if entry.get("CR ID", "").strip() == cr_id:
            return entry
    return None


def content_has_change_source(content, cr_id):
    return bool(re.search(r"Change Source:\s*" + re.escape(cr_id) + r"(\D|$)",
                          content or ""))


# --------------------------------------------------------------------------- #
# Status History (append-only) helpers
# --------------------------------------------------------------------------- #

def status_history_rows(content):
    headers, rows = table_by_header_prefix(content or "", "Date")
    if not headers:
        return []
    return rows_as_dicts(headers, rows)


def validate_history_append_only(existing, new_content):
    """Every row present in the OLD Status History must still be present,
    unchanged and in order, as a prefix of the NEW one. Returns a Decision
    on violation, else None."""
    old_rows = status_history_rows(existing) if existing is not None else []
    new_rows = status_history_rows(new_content)
    if len(new_rows) < len(old_rows):
        return deny(
            "PMO-CR-GUARD-009",
            "Status History has fewer rows than before - history may never "
            "be deleted.",
        )
    for i, old_row in enumerate(old_rows):
        if i >= len(new_rows) or new_rows[i] != old_row:
            return deny(
                "PMO-CR-GUARD-009",
                "Status History row {} was changed or removed - existing "
                "lifecycle history is immutable and append-only.".format(i + 1),
            )
    return None


# --------------------------------------------------------------------------- #
# CR record validation
# --------------------------------------------------------------------------- #

def is_feedback_safe_shape(fields):
    return (fields.get("Origin") == "CLIENT_REQUESTED"
            and fields.get("Status") in FEEDBACK_SAFE_STATUSES)


def verify_client_requested_backlink(root, batch_id, item_id, cr_id):
    """Read-only, tolerant of a missing counterpart (never invented here -
    feedback-management owns that file)."""
    if not BATCH_ID_RE.match(batch_id or "") or not ITEM_ID_RE.match(item_id or ""):
        return deny(
            "PMO-CR-GUARD-008",
            "CLIENT_REQUESTED CR '{}' has invalid Origin Feedback Batch/Item "
            "syntax ('{}' / '{}').".format(cr_id, batch_id, item_id),
        )
    batch_path = os.path.join(root, "docs", "pmo", "feedback", "batches",
                              batch_id + ".md")
    content = read_text(batch_path)
    if content is None:
        return None
    _ITEM_HEADING_RE = re.compile(r"^###\s+(FB-\d{4}-\d{3}-\d{3})\s*$", re.MULTILINE)
    matches = list(_ITEM_HEADING_RE.finditer(content))
    for idx, m in enumerate(matches):
        if m.group(1) != item_id:
            continue
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        block = content[start:end]
        fields = field_map_from_table(*first_table(block))
        related = _clean(fields.get("Related CR", ""))
        related_id = re.match(r"^(CR-\d+)", related)
        got = related_id.group(1) if related_id else related
        if got != cr_id:
            return deny(
                "PMO-CR-GUARD-008",
                "Feedback Item '{}' Related CR is '{}', expected a backlink "
                "to '{}'.".format(item_id, got or "(empty)", cr_id),
            )
        return None
    return None


def validate_provenance(root, fields, cr_id):
    origin = fields.get("Origin", "").strip()
    if origin not in ALL_ORIGINS:
        return deny(
            "PMO-CR-GUARD-005",
            "CR '{}' has Origin '{}', which is not one of {}.".format(
                cr_id, origin or "(empty)", sorted(ALL_ORIGINS)),
        )
    batch_field = fields.get("Origin Feedback Batch", "").strip()
    item_field = fields.get("Origin Feedback Item", "").strip()
    if origin == "PM_PROPOSED":
        if batch_field != PM_PROPOSED_LITERAL or item_field != PM_PROPOSED_LITERAL:
            return deny(
                "PMO-CR-GUARD-008",
                "PM_PROPOSED CR '{}' must carry the canonical literal "
                "'{}' in both Origin Feedback fields - never a fabricated "
                "Feedback id.".format(cr_id, PM_PROPOSED_LITERAL),
            )
        return None
    # CLIENT_REQUESTED
    return verify_client_requested_backlink(root, batch_field, item_field, cr_id)


def validate_evidence(old_status, new_status, fields, cr_id):
    if new_status not in DECISION_REQUIRED_FOR or old_status == new_status:
        return None
    decision = fields.get("Decision", "").strip()
    decision_date = fields.get("Decision Date", "").strip()
    decision_by = fields.get("Decision By", "").strip()
    if not decision or not decision_date or not decision_by:
        return deny(
            "PMO-CR-GUARD-007",
            "CR '{}' transitioning to {} requires non-empty Decision / "
            "Decision Date / Decision By.".format(cr_id, new_status),
        )
    if decision != new_status:
        return deny(
            "PMO-CR-GUARD-007",
            "CR '{}' Decision field ('{}') does not match the target "
            "status ({}).".format(cr_id, decision, new_status),
        )
    if new_status == "APPROVED":
        evidence = fields.get("Approval Evidence", "").strip()
        if not evidence:
            return deny(
                "PMO-CR-GUARD-007",
                "CR '{}' cannot become APPROVED without a non-empty "
                "Approval Evidence reference. Silence, PM assumption, "
                "development activity, classification, or a proposal are "
                "never acceptable evidence.".format(cr_id),
            )
    if new_status in REASON_REQUIRED_FOR:
        reason = fields.get("Rejection/Deferral Reason", "").strip()
        if not reason:
            return deny(
                "PMO-CR-GUARD-007",
                "CR '{}' transitioning to {} requires a non-empty "
                "Rejection/Deferral Reason.".format(cr_id, new_status),
            )
    return None


def validate_cancellation(old_status, new_status, old_fields, fields, cr_id):
    if new_status != "CANCELLED":
        return None
    if old_status == "INCORPORATED":
        return deny(
            "PMO-CR-GUARD-011",
            "CR '{}' is INCORPORATED and may never be transitioned to "
            "CANCELLED. To reverse it, create a new CR referencing it "
            "(Related Prior CR / Relationship: SUPERSEDES).".format(cr_id),
        )
    if old_status == "APPROVED":
        # Prior approval evidence must remain intact and unchanged - the
        # accompanying Status History retention check runs separately in
        # validate_cr_content (it needs the NEW content, not available here).
        if old_fields.get("Approval Evidence", "") != fields.get("Approval Evidence", ""):
            return deny(
                "PMO-CR-GUARD-010",
                "CR '{}' cancellation must not alter the prior "
                "Approval Evidence field - it is retained as history, "
                "not overwritten.".format(cr_id),
            )
    return None


def validate_transition(old_status, new_status, cr_id):
    if old_status == new_status:
        return None
    if old_status not in ALL_CR_STATUSES:
        return deny(
            "PMO-CR-GUARD-006",
            "CR '{}' has an unrecognised current status '{}'.".format(
                cr_id, old_status),
        )
    if new_status not in ALL_CR_STATUSES:
        return deny(
            "PMO-CR-GUARD-006",
            "CR '{}' target status '{}' is not one of the eight canonical "
            "statuses.".format(cr_id, new_status),
        )
    allowed = TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        return deny(
            "PMO-CR-GUARD-006",
            "CR '{}': '{}' -> '{}' is not a valid transition.".format(
                cr_id, old_status, new_status),
        )
    return None


def validate_new_history_row(old_status, new_status, existing, new_content, cr_id):
    if old_status == new_status:
        return None
    old_rows = status_history_rows(existing) if existing is not None else []
    new_rows = status_history_rows(new_content)
    if len(new_rows) != len(old_rows) + 1:
        return deny(
            "PMO-CR-GUARD-009",
            "CR '{}' status changed ({} -> {}) but Status History does not "
            "show exactly one new row.".format(cr_id, old_status, new_status),
        )
    last = new_rows[-1]
    if last.get("From", "").strip() != old_status or last.get("To", "").strip() != new_status:
        return deny(
            "PMO-CR-GUARD-009",
            "CR '{}' new Status History row does not record From='{}' "
            "To='{}'.".format(cr_id, old_status, new_status),
        )
    if not last.get("By", "").strip():
        return deny(
            "PMO-CR-GUARD-009",
            "CR '{}' new Status History row is missing 'By'.".format(cr_id),
        )
    return None


def validate_cr_content(root, content, existing, expected_id, marker_data):
    config = load_config(root)
    fields = field_map_from_table(*first_table(content))

    declared_id = fields.get("CR ID", "").strip()
    if declared_id and declared_id != expected_id:
        return deny(
            "PMO-CR-GUARD-002",
            "CR file declares CR ID '{}' but its filename requires "
            "'{}'.".format(declared_id, expected_id),
        )
    if config:
        pid = (config.get("project") or {}).get("id")
        declared_pid = fields.get("Project ID")
        if pid and declared_pid and str(declared_pid).strip().upper() != str(pid).strip().upper():
            return deny(
                "PMO-CR-GUARD-001",
                "CR Project ID '{}' does not match the configured "
                "project.id '{}'.".format(declared_pid, pid),
            )

    operation = marker_data.get("operation")
    old_fields = field_map_from_table(*first_table(existing)) if existing is not None else {}
    old_status = old_fields.get("Status", "DRAFT" if existing is None else "").strip()
    new_status = fields.get("Status", "").strip()

    if existing is None:
        if operation != "CREATE_PM_PROPOSED":
            return deny(
                "PMO-CR-GUARD-004",
                "'{}' does not exist yet; creating it is only authorised "
                "under operation CREATE_PM_PROPOSED (got '{}').".format(
                    expected_id, operation),
            )
        if new_status != "DRAFT":
            return deny(
                "PMO-CR-GUARD-006",
                "a newly created CR must start at Status DRAFT (got "
                "'{}').".format(new_status),
            )
        if fields.get("Origin") != "PM_PROPOSED":
            return deny(
                "PMO-CR-GUARD-005",
                "operation CREATE_PM_PROPOSED must create a CR with Origin "
                "PM_PROPOSED (got '{}').".format(fields.get("Origin")),
            )
        if not fields.get("Title", "").strip():
            return deny(
                "PMO-CR-GUARD-002",
                "CR '{}' has no Title - not a valid CR creation.".format(expected_id),
            )
    else:
        if operation == "CREATE_PM_PROPOSED":
            return deny(
                "PMO-CR-GUARD-004",
                "'{}' already exists - CREATE_PM_PROPOSED may not target an "
                "existing CR (no ID reuse).".format(expected_id),
            )
        if marker_data.get("cr_id") and marker_data.get("cr_id") != expected_id:
            return deny(
                "PMO-CR-GUARD-024",
                "this transaction is scoped to '{}', not '{}' - only one CR "
                "may be operated on per transaction.".format(
                    marker_data.get("cr_id"), expected_id),
            )

    prov = validate_provenance(root, fields, expected_id)
    if prov is not None:
        return prov

    # Checked before the generic transition matrix so that an attempt to
    # cancel an INCORPORATED CR gets the specific, more informative
    # PMO-CR-GUARD-011 rather than being folded into a generic "invalid
    # transition" - INCORPORATED's empty transition set would otherwise
    # deny it just as validly, but less usefully, first.
    cancel = validate_cancellation(old_status, new_status, old_fields, fields, expected_id)
    if cancel is not None:
        return cancel

    trans = validate_transition(old_status or "DRAFT", new_status, expected_id)
    if trans is not None:
        return trans

    evid = validate_evidence(old_status, new_status, fields, expected_id)
    if evid is not None:
        return evid

    hist_delete = validate_history_append_only(existing, content)
    if hist_delete is not None:
        return hist_delete

    hist_new = validate_new_history_row(old_status or "DRAFT", new_status,
                                        existing, content, expected_id)
    if hist_new is not None:
        return hist_new

    if old_status == "APPROVED" and new_status == "CANCELLED":
        found = any(r.get("To", "").strip() == "APPROVED"
                   for r in status_history_rows(content))
        if not found:
            return deny(
                "PMO-CR-GUARD-010",
                "CR '{}' cancellation must retain the prior APPROVED "
                "Status History row - approval history is never "
                "erased.".format(expected_id),
            )

    if new_status == "INCORPORATED":
        gate = validate_incorporated_gate(root, old_status, fields, expected_id, marker_data)
        if gate is not None:
            return gate

    return None


def validate_incorporated_gate(root, old_status, fields, cr_id, marker_data):
    if marker_data.get("operation") != "INCORPORATION":
        return deny(
            "PMO-CR-GUARD-018",
            "CR '{}' may only become INCORPORATED under operation "
            "INCORPORATION (marker operation is '{}').".format(
                cr_id, marker_data.get("operation")),
        )
    if old_status != "APPROVED":
        return deny(
            "PMO-CR-GUARD-018",
            "CR '{}' may only become INCORPORATED from APPROVED (was "
            "'{}').".format(cr_id, old_status),
        )
    for field in ("Decision", "Decision Date", "Decision By", "Approval Evidence"):
        if not fields.get(field, "").strip():
            return deny(
                "PMO-CR-GUARD-018",
                "CR '{}' is missing '{}' - incomplete approval evidence "
                "cannot be incorporated.".format(cr_id, field),
            )
    changelog_content = read_text(os.path.join(root, *CHANGE_LOG_POSIX.split("/")))
    row = find_changelog_row_for_cr(changelog_content, cr_id) if changelog_content else None
    if row is None:
        return deny(
            "PMO-CR-GUARD-018",
            "CR '{}' has no matching Change Log entry yet - INCORPORATED "
            "may only be set after the Change Log entry already "
            "exists.".format(cr_id),
        )
    latest = latest_scope_version(root)
    scope_version_str = "{}.{}".format(latest[0], latest[1]) if latest else None
    if scope_version_str is None or row.get("New Scope Ver", "").strip() != scope_version_str:
        return deny(
            "PMO-CR-GUARD-015",
            "CR '{}' Change Log entry's New Scope Ver ('{}') does not match "
            "the actual latest Scope file ('{}').".format(
                cr_id, row.get("New Scope Ver", ""), scope_version_str),
        )
    spec_version, specs_content = read_specs_spec_version(root)
    if spec_version is None or row.get("New Spec Ver", "").strip() != spec_version.strip():
        return deny(
            "PMO-CR-GUARD-015",
            "CR '{}' Change Log entry's New Spec Ver ('{}') does not match "
            "the actual specs.md Spec Version ('{}').".format(
                cr_id, row.get("New Spec Ver", ""), spec_version),
        )
    scope_content = read_text(latest[2]) if latest else None
    if not scope_content or not content_has_change_source(scope_content, cr_id):
        return deny(
            "PMO-CR-GUARD-016",
            "CR '{}' latest Scope file does not carry a 'Change Source: "
            "{}' tag.".format(cr_id, cr_id),
        )
    if not specs_content or not content_has_change_source(specs_content, cr_id):
        return deny(
            "PMO-CR-GUARD-016",
            "CR '{}' specs.md does not carry a 'Change Source: {}' "
            "tag.".format(cr_id, cr_id),
        )
    if not fields.get("Incorporated Date", "").strip():
        return deny(
            "PMO-CR-GUARD-018",
            "CR '{}' must set Incorporated Date when becoming "
            "INCORPORATED.".format(cr_id),
        )
    chg_ref = fields.get("Change Log Reference", "").strip()
    if chg_ref != row.get("CHG ID", "").strip():
        return deny(
            "PMO-CR-GUARD-017",
            "CR '{}' Change Log Reference ('{}') does not match the real "
            "Change Log entry id ('{}').".format(
                cr_id, chg_ref, row.get("CHG ID", "")),
        )
    return None


def validate_cr_register_content(content, root):
    headers, rows = table_by_header_prefix(content, "CR ID")
    if not headers:
        return None
    seen = set()
    for entry in rows_as_dicts(headers, rows):
        cid = entry.get("CR ID", "").strip()
        if not cid:
            continue
        if not CR_ID_RE.match(cid):
            return deny(
                "PMO-CR-GUARD-003",
                "Change Request Register lists invalid CR ID '{}'.".format(cid),
            )
        if cid in seen:
            return deny(
                "PMO-CR-GUARD-004",
                "CR ID '{}' is registered more than once.".format(cid),
            )
        seen.add(cid)
        origin = entry.get("Origin", "").strip()
        if origin and origin not in ALL_ORIGINS:
            return deny(
                "PMO-CR-GUARD-005",
                "register row for '{}' has invalid Origin '{}'.".format(cid, origin),
            )
        status = entry.get("Status", "").strip()
        if status and status not in ALL_CR_STATUSES:
            return deny(
                "PMO-CR-GUARD-006",
                "register row for '{}' has invalid Status '{}'.".format(cid, status),
            )
    return None


def register_is_feedback_safe(content):
    headers, rows = table_by_header_prefix(content, "CR ID")
    if not headers:
        return True
    for entry in rows_as_dicts(headers, rows):
        origin = entry.get("Origin", "").strip()
        status = entry.get("Status", "").strip()
        if not origin and not status:
            continue
        if origin != "CLIENT_REQUESTED" or status not in FEEDBACK_SAFE_STATUSES:
            return False
    return True


# --------------------------------------------------------------------------- #
# Scope / Specs / Change Log incorporation validation
# --------------------------------------------------------------------------- #

def validate_scope_write(tool_name, tool_input, root, rel, state, marker_data, marker_err):
    if state != "OPEN" or marker_data.get("operation") != "INCORPORATION":
        return deny(
            "PMO-CR-GUARD-012",
            "docs/pmo/scope/ may only be written during an OPEN change-"
            "request transaction whose operation is INCORPORATION.",
        )
    abspath = os.path.join(root, *rel.split("/"))
    existing = read_text(abspath)
    if existing is not None:
        return deny(
            "PMO-CR-GUARD-012",
            "'{}' already exists - Scope is append-only; incorporation may "
            "only create a brand-new Scope version file, never edit an "
            "existing one.".format(rel),
        )
    cr_id = marker_data.get("cr_id")
    cr_fields = read_cr_fields(root, cr_id) if cr_id else None
    if not cr_fields or cr_fields.get("Status", "").strip() != "APPROVED":
        return deny(
            "PMO-CR-GUARD-018",
            "Scope incorporation write attempted but CR '{}' is not "
            "APPROVED.".format(cr_id),
        )
    new_content = resulting_content(tool_name, tool_input, existing)
    if new_content is None:
        return None
    if not content_has_change_source(new_content, cr_id):
        return deny(
            "PMO-CR-GUARD-016",
            "new Scope version does not carry a 'Change Source: {}' "
            "tag.".format(cr_id),
        )
    baseline = marker_data.get("baseline_scope_version")
    m = SCOPE_FILE_RE.match(os.path.basename(rel))
    if not m:
        return deny(
            "PMO-CR-GUARD-002",
            "'{}' is not a valid Scope version filename.".format(rel),
        )
    new_ver = (int(m.group(1)), int(m.group(2)))
    if baseline:
        try:
            bmaj, bmin = [int(x) for x in str(baseline).split(".")]
        except Exception:
            bmaj, bmin = (0, 0)
        if new_ver <= (bmaj, bmin):
            return deny(
                "PMO-CR-GUARD-015",
                "new Scope version {}.{} is not greater than the "
                "transaction's baseline_scope_version {}.".format(
                    new_ver[0], new_ver[1], baseline),
            )
    return None


def validate_specs_write(tool_name, tool_input, root, state, marker_data, marker_err):
    if state != "OPEN" or marker_data.get("operation") != "INCORPORATION":
        return deny(
            "PMO-CR-GUARD-013",
            "docs/pmo/specs/specs.md may only be written during an OPEN "
            "change-request transaction whose operation is INCORPORATION.",
        )
    abspath = os.path.join(root, *SPECS_POSIX.split("/"))
    existing = read_text(abspath)
    cr_id = marker_data.get("cr_id")
    cr_fields = read_cr_fields(root, cr_id) if cr_id else None
    if not cr_fields or cr_fields.get("Status", "").strip() != "APPROVED":
        return deny(
            "PMO-CR-GUARD-018",
            "Specs incorporation write attempted but CR '{}' is not "
            "APPROVED.".format(cr_id),
        )
    new_content = resulting_content(tool_name, tool_input, existing)
    if new_content is None:
        return None
    if not content_has_change_source(new_content, cr_id):
        return deny(
            "PMO-CR-GUARD-016",
            "specs.md update does not carry a 'Change Source: {}' "
            "tag.".format(cr_id),
        )
    old_fields = field_map_from_table(*first_table(existing)) if existing else {}
    new_fields = field_map_from_table(*first_table(new_content))
    old_ver = old_fields.get("Spec Version", "")
    new_ver = new_fields.get("Spec Version", "")
    baseline = marker_data.get("baseline_specs_version") or old_ver
    if not new_ver or new_ver == baseline:
        return deny(
            "PMO-CR-GUARD-015",
            "specs.md Spec Version was not advanced beyond the "
            "transaction's baseline ('{}').".format(baseline),
        )
    return None


def validate_change_log_write(tool_name, tool_input, root, rel, state, marker_data, marker_err):
    if rel != CHANGE_LOG_POSIX:
        return deny(
            "PMO-CR-GUARD-014",
            "'{}' is not the canonical Change Log path.".format(rel),
        )
    if state != "OPEN" or marker_data.get("operation") != "INCORPORATION":
        return deny(
            "PMO-CR-GUARD-014",
            "docs/pmo/change-log/ may only be written during an OPEN "
            "change-request transaction whose operation is INCORPORATION.",
        )
    cr_id = marker_data.get("cr_id")
    cr_fields = read_cr_fields(root, cr_id) if cr_id else None
    if not cr_fields or cr_fields.get("Status", "").strip() != "APPROVED":
        return deny(
            "PMO-CR-GUARD-018",
            "Change Log write attempted but CR '{}' is not APPROVED.".format(cr_id),
        )
    abspath = os.path.join(root, *rel.split("/"))
    existing = read_text(abspath)
    new_content = resulting_content(tool_name, tool_input, existing)
    if new_content is None:
        return None

    old_headers, old_rows_raw = table_by_header_prefix(existing or "", "CHG ID")
    new_headers, new_rows_raw = table_by_header_prefix(new_content, "CHG ID")
    old_rows = rows_as_dicts(old_headers, old_rows_raw) if old_headers else []
    new_rows = rows_as_dicts(new_headers, new_rows_raw) if new_headers else []
    if len(new_rows) != len(old_rows) + 1:
        return deny(
            "PMO-CR-GUARD-019",
            "Change Log write must append exactly one new CHG entry.",
        )
    for i, old_row in enumerate(old_rows):
        if new_rows[i] != old_row:
            return deny(
                "PMO-CR-GUARD-009",
                "Change Log row {} was changed - the Change Log is "
                "append-only.".format(i + 1),
            )
    new_row = new_rows[-1]
    chg_id = new_row.get("CHG ID", "").strip()
    if not CHG_ID_RE.match(chg_id):
        return deny(
            "PMO-CR-GUARD-003",
            "new Change Log entry has an invalid CHG ID '{}'.".format(chg_id),
        )
    if any(r.get("CHG ID", "").strip() == chg_id for r in old_rows):
        return deny(
            "PMO-CR-GUARD-004",
            "CHG ID '{}' already exists - identifiers are never "
            "reused.".format(chg_id),
        )
    if new_row.get("CR ID", "").strip() != cr_id:
        return deny(
            "PMO-CR-GUARD-017",
            "new Change Log entry's CR ID ('{}') does not match the "
            "transaction's cr_id ('{}').".format(new_row.get("CR ID", ""), cr_id),
        )
    latest = latest_scope_version(root)
    actual_scope_ver = "{}.{}".format(latest[0], latest[1]) if latest else None
    if actual_scope_ver is None or new_row.get("New Scope Ver", "").strip() != actual_scope_ver:
        return deny(
            "PMO-CR-GUARD-015",
            "new Change Log entry's New Scope Ver ('{}') does not match "
            "the actual latest Scope file ('{}').".format(
                new_row.get("New Scope Ver", ""), actual_scope_ver),
        )
    spec_version, _specs_content = read_specs_spec_version(root)
    if spec_version is None or new_row.get("New Spec Ver", "").strip() != spec_version.strip():
        return deny(
            "PMO-CR-GUARD-015",
            "new Change Log entry's New Spec Ver ('{}') does not match "
            "the actual specs.md Spec Version ('{}').".format(
                new_row.get("New Spec Ver", ""), spec_version),
        )
    return None


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
