#!/usr/bin/env python3
"""PMO feedback-governance-guard (Claude Code PreToolUse hook).

Deterministic, fail-closed governance for the artifacts owned by the
``feedback-management`` Skill (``.claude/skills/feedback-management/SKILL.md``):

    docs/pmo/feedback/feedback-tracker.md
    docs/pmo/feedback/batches/FB-YYYY-NNN.md
    docs/pmo/cr/change-request-register.md
    docs/pmo/cr/CR-NNN.md                      (creation/DRAFT-only authority)

The Skill describes intended behaviour; this guard enforces the mechanical,
deterministic invariants. Where the two disagree, this guard wins. It does
**not** attempt semantic classification quality-control (whether BUG vs
ENHANCEMENT vs CHANGE_REQUEST was the "right" call) - only that the
classification is structurally valid and that its consequences obey
governance (Sections below).

Why a "transaction marker", and what it does and does not protect
-------------------------------------------------------------------
A Claude Code PreToolUse hook sees only ``tool_name`` / ``tool_input`` / a
``cwd`` - it carries no signal for *which Skill* issued the call. Every
existing guard in this repository (``scope-version-guard.py``,
``specs-governance-guard.py``, ``intent-schema-guard.py``, ...) reflects that
reality: they govern a file path unconditionally, regardless of caller.

That approach cannot be reused for the "feedback-management must never touch
Scope / specs.md / Intent" requirement, because those three paths *do* have
other, legitimate writers in this repository (``requirement-gathering``,
``spec-generation``, Intent authoring/validation) that must keep working.
Blocking those paths unconditionally would silently break existing, working
Skills - which this task explicitly forbids ("Existing Engine Semantics
Changed: NO").

So this guard uses an explicit, schema-validated transaction marker instead
of trying to infer caller identity:

    .pmo/feedback-transaction.json

As of Phase 1D this marker is no longer a bare presence flag - it is a real,
validated governance record (see "Transaction marker schema" below), and its
*state* (absent / open / blocked / invalid) drives two independent gates:

1. **Cross-artifact boundary** - whenever any marker file exists at all
   (open, blocked, or even invalid/unreadable - "fail closed where
   uncertain"), this guard denies any write to ``docs/pmo/intent/``,
   ``docs/pmo/scope/``, ``docs/pmo/specs/specs.md``, ``docs/pmo/sources/``
   (source evidence), and any ``.pmo/project-config.yaml`` change outside
   the exact whitelist in ``CONFIG_WHITELIST``. No marker at all means this
   guard does not interfere with those paths - leaving Requirement
   Gathering / Specification Generation / Intent governance exactly as they
   were.
2. **Feedback-owned writes now require an OPEN transaction.** As of Phase
   1D, ``feedback-management`` "must no longer rely on an implied
   transaction context": a Write/Edit to the Feedback Tracker, a Feedback
   Batch, the CR Register, or a CR-NNN.md record is denied
   (``PMO-FEEDBACK-GUARD-025``) unless a well-formed marker for the correct
   project exists with ``status`` ``ACTIVE`` or ``RECONCILING`` ("OPEN").
   ``_TEMPLATE-FB.md`` / ``_TEMPLATE-CR.md`` are exempt (never real
   production records, never governed, marker or not).

Transaction marker schema
--------------------------
::

    {
      "transaction_type": "FEEDBACK_MANAGEMENT",
      "transaction_id": "<opaque, Skill-generated, unique per run>",
      "project_id": "<must equal .pmo/project-config.yaml project.id>",
      "feedback_batch_id": null,            // or "FB-YYYY-NNN" once allocated
      "started_at": "2026-09-14T20:00:00Z", // ISO 8601, set once, never changed
      "status": "ACTIVE"                    // ACTIVE | RECONCILING | RECOVERY_REQUIRED
    }

All five non-nullable fields are required; ``feedback_batch_id`` may be
``null`` (the transaction starts before a batch id is necessarily known) but
if present must be a syntactically valid ``FB-YYYY-NNN``. A marker missing a
required field, with an unrecognised ``transaction_type``/``status``, an
unparseable ``started_at``, or a ``project_id`` that does not match the
configured project is **invalid** and blocks everything this guard governs
(maximally fail-closed, since its validity cannot be established).

There is deliberately no ``COMPLETE`` status: successful completion is
represented by the Skill *removing the file* (an out-of-band deletion, not a
Write/Edit - this guard does not need to authorise it, and deleting an
ephemeral runtime marker is not a governance-sensitive action). ``RECOVERY_
REQUIRED`` exists so a controlled failure can be recorded durably (blocking
further feedback writes and preserving diagnostic evidence) without needing
a fourth "is it actually still running" heuristic - seeing it is enough to
know the marker's owning run needs PM attention before anything resumes.

**Marker writes are themselves governed** (``.pmo/feedback-transaction.json``
is a first-class governed path, not just something this guard reads):
creating a fresh marker requires the full schema above; updating an existing
one may only change ``feedback_batch_id`` and ``status`` (per the transition
table below) for the *same* ``transaction_id`` and the *same* ``started_at``
- never both. **No transaction may be silently overwritten by a different
transaction_id** (``PMO-FEEDBACK-GUARD-024``) - "no other Skill may
impersonate feedback-management by creating this marker", and
feedback-management itself may not bypass a denial by replacing its own
marker either. If the *existing* on-disk marker is invalid, it cannot be
"fixed" via Write/Edit either - it must be removed out-of-band first (a
deliberate, visible action) before a fresh, valid marker can be created.

Allowed same-transaction status transitions: ``ACTIVE -> RECONCILING``,
``ACTIVE -> RECOVERY_REQUIRED``, ``RECONCILING -> ACTIVE`` (more work found),
``RECONCILING -> RECOVERY_REQUIRED``, ``RECOVERY_REQUIRED -> ACTIVE`` /
``-> RECONCILING`` (after the PM/operator resolves it), plus a same-status
no-op (e.g. only ``feedback_batch_id`` changing).

Creating and removing this marker around a real processing run, and the
stale/incompatible-marker recovery procedure at the start of a new run, are
Skill-side orchestration, documented in
``.claude/skills/feedback-management/SKILL.md``. This guard supplies the
deterministic enforcement that orchestration relies on; it does not itself
decide *when* to start or end a transaction.

Unconditionally governed, independent of the marker
-------------------------------------------------------
* ``docs/pmo/change-log/`` - denied unconditionally, always. Nothing in this
  repository has legitimate authority to write a Change Log entry outside a
  successful CR incorporation transaction, and that transaction does not
  exist yet either.
* ``_TEMPLATE-FB.md`` / ``_TEMPLATE-CR.md`` - never governed (never real
  production records).

Error IDs - dedicated namespace, never overlaps PMO-FEEDBACK-* (the Skill's
own self-discipline codes) or any other PMO-*-GUARD namespace.
-----------------------------------------------------------------------------
PMO-FEEDBACK-GUARD-001  PROJECT_IDENTITY_INVALID
PMO-FEEDBACK-GUARD-002  INVALID_ARTIFACT_PATH
PMO-FEEDBACK-GUARD-003  INVALID_IDENTIFIER_SYNTAX
PMO-FEEDBACK-GUARD-004  DUPLICATE_OR_REUSED_IDENTIFIER
PMO-FEEDBACK-GUARD-005  INVALID_CLASSIFICATION
PMO-FEEDBACK-GUARD-006  MISSING_CLASSIFICATION_RATIONALE
PMO-FEEDBACK-GUARD-007  INVALID_CONFIDENCE
PMO-FEEDBACK-GUARD-008  TRACKER_BATCH_DESYNC
PMO-FEEDBACK-GUARD-009  INTENT_MUTATION
PMO-FEEDBACK-GUARD-010  SCOPE_MUTATION
PMO-FEEDBACK-GUARD-011  SPECS_MUTATION
PMO-FEEDBACK-GUARD-012  CHANGE_LOG_MUTATION
PMO-FEEDBACK-GUARD-013  UNAUTHORIZED_CR_CREATION
PMO-FEEDBACK-GUARD-014  INVALID_CR_ORIGIN
PMO-FEEDBACK-GUARD-015  INVALID_CR_STATUS
PMO-FEEDBACK-GUARD-016  MISSING_CR_FOR_CHANGE_REQUEST
PMO-FEEDBACK-GUARD-017  UNEXPECTED_CR_LINK
PMO-FEEDBACK-GUARD-018  CR_TRACEABILITY_MISMATCH
PMO-FEEDBACK-GUARD-019  SOURCE_EVIDENCE_MUTATION
PMO-FEEDBACK-GUARD-020  PROJECT_CONFIG_OVERREACH
PMO-FEEDBACK-GUARD-021  GUARD_INTERNAL_ERROR       (fail closed)
PMO-FEEDBACK-GUARD-022  MISSING_REQUIRED_FIELD
PMO-FEEDBACK-GUARD-023  INVALID_TRANSACTION_MARKER
PMO-FEEDBACK-GUARD-024  TRANSACTION_MARKER_OVERWRITE
PMO-FEEDBACK-GUARD-025  NO_ACTIVE_TRANSACTION
PMO-FEEDBACK-GUARD-026  CONFLICTING_TRANSACTION_MARKERS (Phase 2B)

Phase 2B: CR-path authority is transaction-scoped, not this guard's alone
-----------------------------------------------------------------------------
``docs/pmo/cr/change-request-register.md`` and ``docs/pmo/cr/CR-NNN.md`` can
legitimately be governed by *either* an open feedback transaction (this
guard's own narrow ``CLIENT_REQUESTED``/``DRAFT``-only intake authority,
unchanged since Phase 1D) *or* an open change-request transaction (the full
CR lifecycle, owned entirely by ``change-request-governance-guard.py``) -
never both at once. This guard now reads
``.pmo/change-request-transaction.json`` (read-only, via ``cr_marker_is_open``
- it never interprets that marker's ``operation``/``cr_id``/baselines, only
whether it is well-formed, correct-project, and ``ACTIVE``/``RECONCILING``)
purely to decide: delegate (return ``None``, no opinion) when a CR
transaction validly owns the path and no feedback transaction is open;
deny with ``PMO-FEEDBACK-GUARD-026`` if *both* are open at once (mutually
exclusive - resolve one first); otherwise behave exactly as before Phase 2B.

Behaviour
---------
* Reads the Claude Code PreToolUse payload from stdin (JSON).
* Acts only on ``Write`` / ``Edit`` / ``MultiEdit``. This guard does not
  govern ``Bash`` / git operations - ``repo-binding-guard.py`` and
  ``artifact-publish-guard.py`` remain authoritative there (Section
  "GIT / PUBLICATION BOUNDARY" of the Skill); duplicating that logic here is
  deliberately avoided.
* Project routing is read from ``.pmo/project-config.yaml`` at the located
  project root; no project identity is hardcoded, so this guard is reusable
  across projects.
* A blocked operation emits the standard PreToolUse deny response; an
  allowed operation, or any operation outside this guard's scope, produces
  no output and exits 0.
* Any unexpected exception while validating an in-scope write fails closed
  (``PMO-FEEDBACK-GUARD-021``).

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

FEEDBACK_DIR_POSIX = "docs/pmo/feedback"
BATCHES_DIR_POSIX = "docs/pmo/feedback/batches"
TRACKER_POSIX = "docs/pmo/feedback/feedback-tracker.md"

CR_DIR_POSIX = "docs/pmo/cr"
CR_REGISTER_POSIX = "docs/pmo/cr/change-request-register.md"

CHANGE_LOG_DIR_POSIX = "docs/pmo/change-log"

INTENT_DIR_POSIX = "docs/pmo/intent"
SCOPE_DIR_POSIX = "docs/pmo/scope"
SPECS_POSIX = "docs/pmo/specs/specs.md"
SOURCES_DIR_POSIX = "docs/pmo/sources"

CONFIG_RELPATH = ".pmo/project-config.yaml"
MARKER_POSIX = ".pmo/feedback-transaction.json"
MARKER_RELPATH_PARTS = (".pmo", "feedback-transaction.json")

TEMPLATE_BATCH_NAME = "_TEMPLATE-FB.md"
TEMPLATE_CR_NAME = "_TEMPLATE-CR.md"

BATCH_FILE_RE = re.compile(r"^FB-(\d{4})-(\d{3})\.md$")
CR_FILE_RE = re.compile(r"^CR-(\d+)\.md$")
BATCH_ID_RE = re.compile(r"^FB-\d{4}-\d{3}$")
ITEM_ID_RE = re.compile(r"^FB-\d{4}-\d{3}-\d{3}$")
CR_ID_RE = re.compile(r"^CR-\d+$")
CR_ID_LEADING_RE = re.compile(r"^(CR-\d+)")

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
MARKER_REQUIRED_FIELDS = (
    "transaction_type", "transaction_id", "project_id", "started_at", "status",
)
ALLOWED_MARKER_STATUSES = {"ACTIVE", "RECONCILING", "RECOVERY_REQUIRED"}
OPEN_MARKER_STATUSES = {"ACTIVE", "RECONCILING"}
MARKER_STATUS_TRANSITIONS = {
    "ACTIVE": {"ACTIVE", "RECONCILING", "RECOVERY_REQUIRED"},
    "RECONCILING": {"RECONCILING", "ACTIVE", "RECOVERY_REQUIRED"},
    "RECOVERY_REQUIRED": {"RECOVERY_REQUIRED", "ACTIVE", "RECONCILING"},
}

ALLOWED_CLASSIFICATIONS = {
    "BUG", "ENHANCEMENT", "CHANGE_REQUEST", "SUGGESTION",
    "CLARIFICATION", "DUPLICATE", "NOT_ACTIONABLE",
}
ALLOWED_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
CONFIDENCE_REQUIRED_FOR = {"BUG", "ENHANCEMENT", "CHANGE_REQUEST"}
ALLOWED_ITEM_STATUS = {
    "OPEN", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED",
    "REJECTED", "DUPLICATE", "DEFERRED",
}
# Statuses feedback-management itself may WRITE onto a CR-NNN.md file.
FEEDBACK_AUTHORED_CR_STATUSES = {"DRAFT", "CANCELLED"}
# Full legal CR status vocabulary, used only for the passive register rollup
# (which may legitimately reflect other statuses once change-request-
# management exists) - never used to gate a feedback-authored CR-NNN.md file.
ALL_CR_STATUSES = {
    "DRAFT", "PM_REVIEW", "PENDING_CLIENT_DECISION", "APPROVED",
    "REJECTED", "DEFERRED", "CANCELLED", "INCORPORATED",
}
ALL_CR_ORIGINS = {"CLIENT_REQUESTED", "PM_PROPOSED"}

CONFIG_WHITELIST = {
    "artifacts.feedback.latest_id",
    "artifacts.feedback.total_count",
    "artifacts.change_requests.latest_id",
}

_EMPTYISH = {"", "none", "n/a", "-", "null"}


# --------------------------------------------------------------------------- #
# Decision plumbing (same shape as the other PMO PreToolUse guards)
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
    """Parse the 2-space-indented mapping subset used by PMO YAML files."""
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
    """Flatten a nested dict/list/scalar into {dotted.path: value}."""
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
    """Dotted-path keys whose value changed between before/after and are
    NOT in the given whitelist. Deterministic, no fuzzy matching."""
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


CR_MARKER_RELPATH_PARTS = (".pmo", "change-request-transaction.json")


def cr_marker_is_open(root):
    """Phase 2B reconciliation: minimal, read-only check for whether a
    well-formed, correct-project, OPEN-status CHANGE_REQUEST_MANAGEMENT
    transaction marker exists. Used only to (a) delegate CR-path authority
    to change-request-governance-guard.py once it is registered, and (b)
    detect the mutually-exclusive "both markers active" case. This guard
    does not otherwise interpret CR-transaction content (operation, cr_id,
    baselines, ...) - that is entirely change-request-governance-guard.py's
    domain."""
    text = read_text(os.path.join(root, *CR_MARKER_RELPATH_PARTS))
    if text is None:
        return False
    try:
        data = json.loads(text)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    if data.get("transaction_type") != "CHANGE_REQUEST_MANAGEMENT":
        return False
    if data.get("status") not in ("ACTIVE", "RECONCILING"):
        return False
    config = load_config(root)
    pid = (config or {}).get("project", {}).get("id") if config else None
    if pid and str(data.get("project_id", "")).strip().upper() != str(pid).strip().upper():
        return False
    return True




def parse_marker(text):
    """Validate marker JSON text against the schema. Returns (data, error) -
    error is None iff the marker is structurally and semantically valid
    (well-formed JSON object, all required fields present and non-empty,
    transaction_type/status from the allowed sets, started_at timestamp-
    shaped, feedback_batch_id null or a syntactically valid FB-YYYY-NNN)."""
    try:
        data = json.loads(text)
    except Exception as exc:
        return None, "marker is not valid JSON ({})".format(exc)
    if not isinstance(data, dict):
        return None, "marker JSON must be an object"
    for field in MARKER_REQUIRED_FIELDS:
        if field not in data or data.get(field) in (None, ""):
            return None, "marker is missing required field '{}'".format(field)
    if data.get("transaction_type") != "FEEDBACK_MANAGEMENT":
        return None, "marker transaction_type must be 'FEEDBACK_MANAGEMENT'"
    if data.get("status") not in ALLOWED_MARKER_STATUSES:
        return None, "marker status '{}' is not one of {}".format(
            data.get("status"), sorted(ALLOWED_MARKER_STATUSES))
    if not TIMESTAMP_RE.match(str(data.get("started_at"))):
        return None, "marker started_at is not a recognisable ISO 8601 timestamp"
    fbid = data.get("feedback_batch_id")
    if fbid not in (None, "") and not BATCH_ID_RE.match(str(fbid)):
        return None, "marker feedback_batch_id '{}' is not a valid FB-YYYY-NNN id".format(fbid)
    return data, None


def marker_status(root):
    """(state, data, error) for the transaction marker on disk.

    state is one of:
      "ABSENT"  - no marker file at all.
      "OPEN"    - well-formed, correct project, status ACTIVE/RECONCILING.
      "BLOCKED" - well-formed, correct project, status RECOVERY_REQUIRED.
      "INVALID" - malformed, wrong project, or otherwise unparseable/unsafe.
    """
    text = read_text(os.path.join(root, *MARKER_RELPATH_PARTS))
    if text is None:
        return "ABSENT", None, None
    data, err = parse_marker(text)
    if err is not None:
        return "INVALID", None, err
    config = load_config(root)
    pid = (config or {}).get("project", {}).get("id") if config else None
    if pid and str(data.get("project_id")).strip().upper() != str(pid).strip().upper():
        return "INVALID", data, (
            "marker project_id '{}' does not match the configured "
            "project.id '{}'".format(data.get("project_id"), pid)
        )
    if data.get("status") in OPEN_MARKER_STATUSES:
        return "OPEN", data, None
    return "BLOCKED", data, None


def validate_marker_write(tool_name, tool_input, root):
    """Governs Write/Edit/MultiEdit to .pmo/feedback-transaction.json itself."""
    marker_abspath = os.path.join(root, *MARKER_RELPATH_PARTS)
    existing = read_text(marker_abspath)
    new_content = resulting_content(tool_name, tool_input, existing)
    if new_content is None:
        return None

    new_data, new_err = parse_marker(new_content)
    if new_err is not None:
        return deny(
            "PMO-FEEDBACK-GUARD-023",
            "refusing to write .pmo/feedback-transaction.json: {}.".format(new_err),
        )

    config = load_config(root)
    pid = (config or {}).get("project", {}).get("id") if config else None
    if pid and str(new_data.get("project_id")).strip().upper() != str(pid).strip().upper():
        return deny(
            "PMO-FEEDBACK-GUARD-023",
            "refusing to write a transaction marker for project_id '{}' - "
            "the configured project is '{}'.".format(new_data.get("project_id"), pid),
        )

    if existing is None:
        return None  # fresh, schema-valid creation for the right project - ALLOW

    old_data, old_err = parse_marker(existing)
    if old_err is not None:
        return deny(
            "PMO-FEEDBACK-GUARD-023",
            "an existing .pmo/feedback-transaction.json is present but "
            "invalid ({}) - it must be removed out-of-band (never overwritten "
            "by a Write/Edit) before a new transaction can start.".format(old_err),
        )

    if old_data.get("transaction_id") != new_data.get("transaction_id"):
        return deny(
            "PMO-FEEDBACK-GUARD-024",
            "an existing transaction marker (transaction_id '{}') may not be "
            "silently replaced by a different transaction_id ('{}'). No Skill "
            "may impersonate feedback-management by overwriting its marker; "
            "remove the file out-of-band first if the prior transaction is "
            "genuinely finished.".format(
                old_data.get("transaction_id"), new_data.get("transaction_id")),
        )

    if old_data.get("started_at") != new_data.get("started_at"):
        return deny(
            "PMO-FEEDBACK-GUARD-024",
            "transaction '{}' may not change its started_at once created "
            "({} -> {}).".format(
                new_data.get("transaction_id"), old_data.get("started_at"),
                new_data.get("started_at")),
        )

    allowed_next = MARKER_STATUS_TRANSITIONS.get(old_data.get("status"), set())
    if new_data.get("status") not in allowed_next:
        return deny(
            "PMO-FEEDBACK-GUARD-024",
            "transaction '{}' may not move from status '{}' to '{}'.".format(
                new_data.get("transaction_id"), old_data.get("status"),
                new_data.get("status")),
        )

    return None


def posix_rel(abspath, root):
    try:
        rel = os.path.relpath(abspath, root)
    except Exception:
        return None
    return rel.replace(os.sep, "/")


def resulting_content(tool_name, tool_input, existing):
    """The file content that would exist after this Write/Edit/MultiEdit."""
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
# Markdown pipe-table parsing (stdlib only, deterministic, no fuzzy logic)
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
    """Yield (start_line_index, headers, rows) for every pipe-table block."""
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
    """A 'Field | ... | Value' record table -> {field: value}."""
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
    """A register table -> [{header: cell, ...}, ...], placeholder rows skipped."""
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


_ITEM_HEADING_RE = re.compile(r"^###\s+(FB-\d{4}-\d{3}-\d{3})\s*$", re.MULTILINE)


def find_item_blocks(content):
    """[(item_id, block_text), ...] for every '### FB-YYYY-NNN-NNN' heading."""
    text = content or ""
    matches = list(_ITEM_HEADING_RE.finditer(text))
    blocks = []
    for idx, m in enumerate(matches):
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        blocks.append((m.group(1), text[start:end]))
    return blocks


def _clean_cr_ref(value):
    v = (value or "").strip()
    if v.lower() in _EMPTYISH:
        return ""
    m = CR_ID_LEADING_RE.match(v)
    return m.group(1) if m else v


# --------------------------------------------------------------------------- #
# Cross-file backlink checks (tolerant of write ordering within one
# transaction: a counterpart file that does not exist YET is not an error)
# --------------------------------------------------------------------------- #

def check_cr_backlink(root, cr_id, batch_id, item_id):
    cr_path = os.path.join(root, "docs", "pmo", "cr", cr_id + ".md")
    content = read_text(cr_path)
    if content is None:
        return None
    fields = field_map_from_table(*first_table(content))
    if fields.get("CR ID", "").strip() != cr_id:
        return deny(
            "PMO-FEEDBACK-GUARD-018",
            "{}.md declares CR ID '{}', expected '{}'.".format(
                cr_id, fields.get("CR ID", ""), cr_id),
        )
    if fields.get("Origin Feedback Batch", "").strip() != batch_id:
        return deny(
            "PMO-FEEDBACK-GUARD-018",
            "{} Origin Feedback Batch is '{}', expected '{}' (the batch of the "
            "Feedback Item linking to it).".format(
                cr_id, fields.get("Origin Feedback Batch", ""), batch_id),
        )
    if fields.get("Origin Feedback Item", "").strip() != item_id:
        return deny(
            "PMO-FEEDBACK-GUARD-018",
            "{} Origin Feedback Item is '{}', expected '{}'.".format(
                cr_id, fields.get("Origin Feedback Item", ""), item_id),
        )
    return None


def check_item_backlink(root, batch_id, item_id, cr_id):
    """Verify a CR's declared (Origin Feedback Batch, Origin Feedback Item)
    against the batch file's own view of who links to this CR. Two distinct
    failure shapes are caught: the item the CR claims to originate from
    exists but points somewhere else, or a *different* item in the batch is
    the one actually linking back to this CR (the CR names the wrong item,
    possibly one that does not exist at all)."""
    batch_path = os.path.join(root, "docs", "pmo", "feedback", "batches",
                              batch_id + ".md")
    content = read_text(batch_path)
    if content is None:
        return None

    claimant = None
    declared_item_found = False
    declared_item_related = ""
    for iid, block in find_item_blocks(content):
        fields = field_map_from_table(*first_table(block))
        related = _clean_cr_ref(fields.get("Related CR", ""))
        if related == cr_id:
            claimant = iid
        if iid == item_id:
            declared_item_found = True
            declared_item_related = related

    if declared_item_found and declared_item_related and declared_item_related != cr_id:
        return deny(
            "PMO-FEEDBACK-GUARD-018",
            "Feedback Item '{}' Related CR is '{}', expected a backlink to "
            "'{}'.".format(item_id, declared_item_related, cr_id),
        )
    if claimant is not None and claimant != item_id:
        return deny(
            "PMO-FEEDBACK-GUARD-018",
            "{} declares Origin Feedback Item '{}', but Feedback Item '{}' "
            "is the one whose Related CR actually links back to it.".format(
                cr_id, item_id, claimant),
        )
    return None


# --------------------------------------------------------------------------- #
# Feedback Batch validation (unconditional)
# --------------------------------------------------------------------------- #

def validate_batch_content(content, root, expected_id):
    config = load_config(root)
    dc = field_map_from_table(*first_table(content))

    declared_id = dc.get("Feedback Batch ID", "").strip()
    if declared_id and declared_id != expected_id:
        return deny(
            "PMO-FEEDBACK-GUARD-002",
            "batch file declares Feedback Batch ID '{}' but its filename "
            "requires '{}'.".format(declared_id, expected_id),
        )

    if config:
        pid = ((config.get("project") or {}).get("id"))
        declared_pid = dc.get("Project ID")
        if pid and declared_pid and str(declared_pid).strip().upper() != str(pid).strip().upper():
            return deny(
                "PMO-FEEDBACK-GUARD-001",
                "batch Project ID '{}' does not match the configured "
                "project.id '{}'.".format(declared_pid, pid),
            )

    blocks = find_item_blocks(content)
    seen_ids = set()

    for item_id, block in blocks:
        if item_id in seen_ids:
            return deny(
                "PMO-FEEDBACK-GUARD-004",
                "Feedback Item ID '{}' is defined more than once in this "
                "batch.".format(item_id),
            )
        seen_ids.add(item_id)

        if not item_id.startswith(expected_id + "-"):
            return deny(
                "PMO-FEEDBACK-GUARD-003",
                "Feedback Item ID '{}' does not belong to batch "
                "'{}'.".format(item_id, expected_id),
            )

        fields = field_map_from_table(*first_table(block))

        parent = fields.get("Parent Feedback Batch", "").strip()
        if parent and parent != expected_id:
            return deny(
                "PMO-FEEDBACK-GUARD-003",
                "item '{}' declares Parent Feedback Batch '{}', expected "
                "'{}'.".format(item_id, parent, expected_id),
            )

        for req_field in ("Original Feedback", "Status"):
            if not fields.get(req_field, "").strip():
                return deny(
                    "PMO-FEEDBACK-GUARD-022",
                    "item '{}' is missing required field '{}'.".format(
                        item_id, req_field),
                )

        classification = fields.get("Classification", "").strip()
        if classification not in ALLOWED_CLASSIFICATIONS:
            return deny(
                "PMO-FEEDBACK-GUARD-005",
                "item '{}' has classification '{}', which is not one of the "
                "seven allowed values.".format(item_id, classification or "(empty)"),
            )

        rationale = fields.get("Classification Rationale", "").strip()
        if not rationale:
            return deny(
                "PMO-FEEDBACK-GUARD-006",
                "item '{}' ({}) has no Classification Rationale.".format(
                    item_id, classification),
            )

        confidence = fields.get("Classification Confidence", "").strip()
        if confidence and confidence not in ALLOWED_CONFIDENCE:
            return deny(
                "PMO-FEEDBACK-GUARD-007",
                "item '{}' has Classification Confidence '{}', must be one "
                "of HIGH / MEDIUM / LOW.".format(item_id, confidence),
            )
        if not confidence and classification in CONFIDENCE_REQUIRED_FOR:
            return deny(
                "PMO-FEEDBACK-GUARD-007",
                "item '{}' ({}) is missing a required Classification "
                "Confidence.".format(item_id, classification),
            )

        status = fields.get("Status", "").strip()
        if status not in ALLOWED_ITEM_STATUS:
            return deny(
                "PMO-FEEDBACK-GUARD-022",
                "item '{}' has Status '{}', which is not a valid Phase-1 "
                "feedback status.".format(item_id, status),
            )

        related_cr = _clean_cr_ref(fields.get("Related CR", ""))
        if classification == "CHANGE_REQUEST":
            if not related_cr or not CR_ID_RE.match(related_cr):
                return deny(
                    "PMO-FEEDBACK-GUARD-016",
                    "item '{}' is classified CHANGE_REQUEST but has no valid "
                    "linked Related CR.".format(item_id),
                )
        else:
            if related_cr:
                return deny(
                    "PMO-FEEDBACK-GUARD-017",
                    "item '{}' is classified {} but carries a Related CR "
                    "('{}') - only a CHANGE_REQUEST item may create or hold "
                    "a CR link.".format(item_id, classification, related_cr),
                )

        if classification == "DUPLICATE":
            dup_of = fields.get("Duplicate Of", "").strip()
            if not dup_of or not ITEM_ID_RE.match(dup_of) or dup_of == item_id:
                return deny(
                    "PMO-FEEDBACK-GUARD-022",
                    "item '{}' is classified DUPLICATE but 'Duplicate Of' is "
                    "missing or invalid.".format(item_id),
                )

        if related_cr:
            mismatch = check_cr_backlink(root, related_cr, expected_id, item_id)
            if mismatch is not None:
                return mismatch

    item_count_declared = dc.get("Item Count", "").strip()
    if item_count_declared:
        try:
            declared_n = int(item_count_declared)
        except ValueError:
            declared_n = None
        if declared_n is not None and declared_n != len(blocks):
            return deny(
                "PMO-FEEDBACK-GUARD-008",
                "batch Document Control declares Item Count {} but {} "
                "Feedback Item(s) are present in the file.".format(
                    declared_n, len(blocks)),
            )

    return None


# --------------------------------------------------------------------------- #
# Change Request validation (unconditional; feedback-authorised subset only)
# --------------------------------------------------------------------------- #

def validate_cr_content(content, root, expected_id):
    config = load_config(root)
    fields = field_map_from_table(*first_table(content))

    declared_id = fields.get("CR ID", "").strip()
    if declared_id and declared_id != expected_id:
        return deny(
            "PMO-FEEDBACK-GUARD-002",
            "CR file declares CR ID '{}' but its filename requires "
            "'{}'.".format(declared_id, expected_id),
        )

    if config:
        pid = ((config.get("project") or {}).get("id"))
        declared_pid = fields.get("Project ID")
        if pid and declared_pid and str(declared_pid).strip().upper() != str(pid).strip().upper():
            return deny(
                "PMO-FEEDBACK-GUARD-001",
                "CR Project ID '{}' does not match the configured "
                "project.id '{}'.".format(declared_pid, pid),
            )

    title = fields.get("Title", "").strip()
    if not title:
        return deny(
            "PMO-FEEDBACK-GUARD-013",
            "CR '{}' has no Title - not a valid CR creation.".format(expected_id),
        )

    origin = fields.get("Origin", "").strip()
    if origin != "CLIENT_REQUESTED":
        return deny(
            "PMO-FEEDBACK-GUARD-014",
            "feedback-management may create/write a CR only with "
            "Origin CLIENT_REQUESTED; got '{}'. PM_PROPOSED CRs belong "
            "exclusively to change-request-management.".format(origin or "(empty)"),
        )

    status = fields.get("Status", "").strip()
    if status not in FEEDBACK_AUTHORED_CR_STATUSES:
        return deny(
            "PMO-FEEDBACK-GUARD-015",
            "feedback-management may only write a CR at Status DRAFT "
            "(creation) or the DRAFT -> CANCELLED reclassification "
            "correction; got '{}'.".format(status or "(empty)"),
        )

    batch_field = fields.get("Origin Feedback Batch", "").strip()
    item_field = fields.get("Origin Feedback Item", "").strip()
    if not BATCH_ID_RE.match(batch_field):
        return deny(
            "PMO-FEEDBACK-GUARD-013",
            "CR '{}' (Origin CLIENT_REQUESTED) has an invalid or missing "
            "Origin Feedback Batch '{}'.".format(expected_id, batch_field or "(empty)"),
        )
    if not ITEM_ID_RE.match(item_field):
        return deny(
            "PMO-FEEDBACK-GUARD-013",
            "CR '{}' (Origin CLIENT_REQUESTED) has an invalid or missing "
            "Origin Feedback Item '{}'.".format(expected_id, item_field or "(empty)"),
        )

    mismatch = check_item_backlink(root, batch_field, item_field, expected_id)
    if mismatch is not None:
        return mismatch

    if status == "CANCELLED":
        sh_headers, sh_rows = table_by_header_prefix(content, "Date")
        found = False
        if sh_headers:
            idx_to = next(
                (i for i, h in enumerate(sh_headers) if h.strip().lower() == "to"),
                None,
            )
            if idx_to is not None:
                for row in sh_rows:
                    if idx_to < len(row) and row[idx_to].strip() == "CANCELLED":
                        found = True
                        break
        if not found:
            return deny(
                "PMO-FEEDBACK-GUARD-015",
                "CR '{}' is Status CANCELLED with no recorded Status History "
                "transition to CANCELLED.".format(expected_id),
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
                "PMO-FEEDBACK-GUARD-003",
                "Change Request Register lists invalid CR ID '{}'.".format(cid),
            )
        if cid in seen:
            return deny(
                "PMO-FEEDBACK-GUARD-004",
                "CR ID '{}' is registered more than once.".format(cid),
            )
        seen.add(cid)

        origin = entry.get("Origin", "").strip()
        if origin and origin not in ALL_CR_ORIGINS:
            return deny(
                "PMO-FEEDBACK-GUARD-014",
                "register row for '{}' has invalid Origin '{}'.".format(cid, origin),
            )

        status = entry.get("Status", "").strip()
        if status and status not in ALL_CR_STATUSES:
            return deny(
                "PMO-FEEDBACK-GUARD-015",
                "register row for '{}' has invalid Status '{}'.".format(cid, status),
            )
    return None


# --------------------------------------------------------------------------- #
# Feedback Tracker validation (unconditional)
# --------------------------------------------------------------------------- #

def validate_tracker_content(content, root):
    ih, irows = table_by_header_prefix(content, "Item ID")
    bh, brows = table_by_header_prefix(content, "Batch ID")

    items = rows_as_dicts(ih, irows) if ih else []
    batches = rows_as_dicts(bh, brows) if bh else []

    seen_items = set()
    for it in items:
        iid = it.get("Item ID", "").strip()
        if not iid:
            continue
        if not ITEM_ID_RE.match(iid):
            return deny(
                "PMO-FEEDBACK-GUARD-003",
                "Feedback Item Register lists invalid Item ID '{}'.".format(iid),
            )
        if iid in seen_items:
            return deny(
                "PMO-FEEDBACK-GUARD-004",
                "Item ID '{}' is registered more than once in the Feedback "
                "Item Register.".format(iid),
            )
        seen_items.add(iid)

        classification = it.get("Classification", "").strip()
        if classification and classification not in ALLOWED_CLASSIFICATIONS:
            return deny(
                "PMO-FEEDBACK-GUARD-005",
                "Feedback Item Register row '{}' has invalid classification "
                "'{}'.".format(iid, classification),
            )

        related_cr = _clean_cr_ref(it.get("Related CR", ""))
        if classification == "CHANGE_REQUEST" and not related_cr:
            return deny(
                "PMO-FEEDBACK-GUARD-016",
                "Feedback Item Register row '{}' is CHANGE_REQUEST with no "
                "Related CR.".format(iid),
            )
        if classification and classification != "CHANGE_REQUEST" and related_cr:
            return deny(
                "PMO-FEEDBACK-GUARD-017",
                "Feedback Item Register row '{}' is {} but lists a Related "
                "CR.".format(iid, classification),
            )

        parent = it.get("Parent Batch", "").strip()
        if parent:
            batch_content = read_text(
                os.path.join(root, "docs", "pmo", "feedback", "batches",
                            parent + ".md"))
            if batch_content is not None:
                match = next(
                    (block for bid2, block in find_item_blocks(batch_content)
                     if bid2 == iid), None,
                )
                if match is not None:
                    bfields = field_map_from_table(*first_table(match))
                    for key in ("Classification", "Status"):
                        tv = it.get(key, "").strip()
                        bv = bfields.get(key, "").strip()
                        if tv and bv and tv != bv:
                            return deny(
                                "PMO-FEEDBACK-GUARD-008",
                                "Tracker row for '{}' shows {}='{}' but the "
                                "batch record shows '{}'.".format(
                                    iid, key, tv, bv),
                            )

    seen_batches = set()
    for b in batches:
        bid = b.get("Batch ID", "").strip()
        if not bid:
            continue
        if not BATCH_ID_RE.match(bid):
            return deny(
                "PMO-FEEDBACK-GUARD-003",
                "Feedback Batch Register lists invalid Batch ID '{}'.".format(bid),
            )
        if bid in seen_batches:
            return deny(
                "PMO-FEEDBACK-GUARD-004",
                "Batch ID '{}' is registered more than once.".format(bid),
            )
        seen_batches.add(bid)

        item_count = b.get("Item Count", "").strip()
        if item_count:
            bcontent = read_text(
                os.path.join(root, "docs", "pmo", "feedback", "batches",
                            bid + ".md"))
            if bcontent is not None:
                try:
                    declared_n = int(item_count)
                except ValueError:
                    declared_n = None
                if declared_n is not None:
                    actual_n = len(find_item_blocks(bcontent))
                    if declared_n != actual_n:
                        return deny(
                            "PMO-FEEDBACK-GUARD-008",
                            "Tracker Batch Register shows Item Count {} for "
                            "'{}' but the batch record contains {}.".format(
                                declared_n, bid, actual_n),
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

    # -- The transaction marker itself: special-cased, always active. -------#
    if rel == MARKER_POSIX:
        return validate_marker_write(tool_name, tool_input, root)

    state, marker_data, marker_err = marker_status(root)

    # -- Change Log: exclusively change-request-management's territory -----#
    # (Phase 2B). feedback-management never legitimately writes here under
    # any circumstance, so this guard keeps denying by default - but a valid
    # CR incorporation transaction (owned entirely by change-request-
    # governance-guard.py) must not be blocked by this guard either. Both
    # markers open at once is the same forbidden state as for CR paths.
    if rel == CHANGE_LOG_DIR_POSIX or rel.startswith(CHANGE_LOG_DIR_POSIX + "/"):
        cr_open_here = cr_marker_is_open(root)
        if state == "OPEN" and cr_open_here:
            return deny(
                "PMO-FEEDBACK-GUARD-026",
                "a feedback-management transaction and a change-request-"
                "management transaction are both active for this project at "
                "the same time - this is mutually exclusive. Resolve "
                "(complete or recover) one transaction before the other "
                "proceeds.",
            )
        if cr_open_here:
            # Out of scope for this guard - change-request-governance-
            # guard.py owns Change Log writes entirely (only during its own
            # validated INCORPORATION operation; it applies that check
            # itself, this guard does not need to duplicate it).
            return None
        return deny(
            "PMO-FEEDBACK-GUARD-012",
            "feedback-management must never write docs/pmo/change-log/ - a "
            "Change Log entry may only be written by a successful CR "
            "incorporation transaction, owned exclusively by "
            "change-request-management.",
        )

    # -- Cross-artifact boundary: active whenever ANY marker exists at all -- #
    # (open, blocked, or invalid) - "fail closed where uncertain."
    if state != "ABSENT":
        if rel == INTENT_DIR_POSIX or rel.startswith(INTENT_DIR_POSIX + "/"):
            return deny(
                "PMO-FEEDBACK-GUARD-009",
                "a feedback-management transaction marker is present "
                "(.pmo/feedback-transaction.json) and must not write to "
                "docs/pmo/intent/.",
            )
        if rel == SCOPE_DIR_POSIX or rel.startswith(SCOPE_DIR_POSIX + "/"):
            return deny(
                "PMO-FEEDBACK-GUARD-010",
                "a feedback-management transaction marker is present and "
                "must not write to docs/pmo/scope/.",
            )
        if rel == SPECS_POSIX:
            return deny(
                "PMO-FEEDBACK-GUARD-011",
                "a feedback-management transaction marker is present and "
                "must not write docs/pmo/specs/specs.md.",
            )
        if rel.startswith(SOURCES_DIR_POSIX + "/"):
            return deny(
                "PMO-FEEDBACK-GUARD-019",
                "a feedback-management transaction marker is present and "
                "must not rewrite source evidence under docs/pmo/sources/.",
            )
        if rel == CONFIG_RELPATH:
            existing = read_text(abspath) or ""
            new_content = resulting_content(tool_name, tool_input, existing)
            if new_content is not None:
                bad = config_diff_violations(existing, new_content, CONFIG_WHITELIST)
                if bad:
                    return deny(
                        "PMO-FEEDBACK-GUARD-020",
                        "a feedback-management transaction may only update {} "
                        "in .pmo/project-config.yaml; this write also "
                        "changes: {}.".format(
                            ", ".join(sorted(CONFIG_WHITELIST)), ", ".join(bad)),
                    )

    basename = os.path.basename(rel)
    is_feedback_intake_path = (
        rel == TRACKER_POSIX or rel.startswith(BATCHES_DIR_POSIX + "/")
    )
    is_cr_path = (
        rel == CR_REGISTER_POSIX or rel.startswith(CR_DIR_POSIX + "/")
    )
    is_template = basename in (TEMPLATE_BATCH_NAME, TEMPLATE_CR_NAME)

    # -- Feedback intake (Tracker/Batches): unchanged since Phase 1D - always --
    # -- this guard's own exclusive domain, requires an OPEN feedback marker. --
    if is_feedback_intake_path and not is_template:
        if state == "INVALID":
            return deny(
                "PMO-FEEDBACK-GUARD-023",
                "cannot validate a feedback-owned write to '{}': the existing "
                "transaction marker is invalid ({}).".format(rel, marker_err),
            )
        if state in ("ABSENT", "BLOCKED"):
            return deny(
                "PMO-FEEDBACK-GUARD-025",
                "no open feedback-management transaction is active for '{}' "
                "(.pmo/feedback-transaction.json is {}) - a governed "
                "transaction must be started (status ACTIVE/RECONCILING) "
                "before this write.".format(
                    rel,
                    "absent" if state == "ABSENT"
                    else "status RECOVERY_REQUIRED and not accepting writes"),
            )
        # state == "OPEN" falls through to normal structural validation below.

    # -- CR paths (Register + CR-NNN.md): Phase 2B transaction-scoped -------#
    # -- ownership. Two authorities can legitimately govern these paths:    -#
    # -- a feedback transaction (narrow: CLIENT_REQUESTED / DRAFT intake    -#
    # -- only) or a change-request transaction (the full CR lifecycle,      -#
    # -- owned entirely by change-request-governance-guard.py). They must   -#
    # -- never both claim authority at once, and this guard must never      -#
    # -- itself deny a write that genuinely belongs to the other authority. -#
    if is_cr_path and not is_template:
        cr_open = cr_marker_is_open(root)
        if state == "OPEN":
            if cr_open:
                return deny(
                    "PMO-FEEDBACK-GUARD-026",
                    "a feedback-management transaction and a change-request-"
                    "management transaction are both active for this project "
                    "at the same time - this is mutually exclusive. Resolve "
                    "(complete or recover) one transaction before the other "
                    "proceeds.",
                )
            # Only the feedback transaction is open - this guard's own,
            # narrow, CLIENT_REQUESTED/DRAFT-only authority applies below,
            # exactly as it has since Phase 1D.
        else:
            if cr_open:
                # A change-request transaction validly owns this path instead
                # - out of scope for this guard. Delegate entirely: no
                # opinion, no denial. change-request-governance-guard.py (a
                # separately registered hook) is authoritative here.
                return None
            if state == "INVALID":
                return deny(
                    "PMO-FEEDBACK-GUARD-023",
                    "cannot validate a feedback-owned write to '{}': the "
                    "existing transaction marker is invalid ({}).".format(
                        rel, marker_err),
                )
            return deny(
                "PMO-FEEDBACK-GUARD-025",
                "no open feedback-management transaction is active for '{}' "
                "(.pmo/feedback-transaction.json is {}), and no open change-"
                "request-management transaction claims this path either - a "
                "governed transaction must be started before this "
                "write.".format(
                    rel,
                    "absent" if state == "ABSENT"
                    else "status RECOVERY_REQUIRED and not accepting writes"),
            )

    # -- Feedback Tracker --------------------------------------------------- #
    if rel == TRACKER_POSIX:
        existing = read_text(abspath)
        new_content = resulting_content(tool_name, tool_input, existing)
        if new_content is None:
            return None
        return validate_tracker_content(new_content, root)

    # -- Feedback Batch records ---------------------------------------------#
    if rel.startswith(BATCHES_DIR_POSIX + "/"):
        if is_template:
            return None
        m = BATCH_FILE_RE.match(basename)
        if not m:
            return deny(
                "PMO-FEEDBACK-GUARD-002",
                "'{}' is not a valid Feedback Batch filename (expected "
                "FB-YYYY-NNN.md).".format(basename),
            )
        # Note: batch-ID reuse across two DIFFERENT files is structurally
        # impossible to reach here - the filename IS the id (enforced by
        # BATCH_FILE_RE + the declared-id-must-match-filename check inside
        # validate_batch_content), filenames are unique per directory, and
        # two files can therefore never both legitimately declare the same
        # Feedback Batch ID. Reuse *within* a batch (item ids) and *within*
        # the register (rows) is still fully checked below / in
        # validate_tracker_content / validate_cr_register_content.
        expected_id = "FB-{}-{}".format(m.group(1), m.group(2))
        existing = read_text(abspath)
        new_content = resulting_content(tool_name, tool_input, existing)
        if new_content is None:
            return None
        return validate_batch_content(new_content, root, expected_id)

    # -- Change Request Register --------------------------------------------#
    if rel == CR_REGISTER_POSIX:
        existing = read_text(abspath)
        new_content = resulting_content(tool_name, tool_input, existing)
        if new_content is None:
            return None
        return validate_cr_register_content(new_content, root)

    # -- Change Request records ----------------------------------------------#
    if rel.startswith(CR_DIR_POSIX + "/"):
        if is_template:
            return None
        m = CR_FILE_RE.match(basename)
        if not m:
            return deny(
                "PMO-FEEDBACK-GUARD-002",
                "'{}' is not a valid Change Request filename (expected "
                "CR-NNN.md).".format(basename),
            )
        # Same reasoning as the batch case above: CR-id reuse across two
        # different filenames is unreachable given the mandatory
        # filename == declared-CR-ID equality check in validate_cr_content.
        expected_id = "CR-{}".format(m.group(1))
        existing = read_text(abspath)
        new_content = resulting_content(tool_name, tool_input, existing)
        if new_content is None:
            return None
        return validate_cr_content(new_content, root, expected_id)

    return None

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
            "PMO-FEEDBACK-GUARD-021",
            "unexpected internal error during feedback governance validation "
            "({}). Blocking as a precaution.".format(exc),
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
