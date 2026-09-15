#!/usr/bin/env python3
"""PMO Scope version & governance guard (Claude Code PreToolUse hook).

Deterministic governance for PMO Scope artifacts:

    docs/pmo/scope/scope-v<major>.<minor>.md

The *requirement-gathering skill* performs semantic requirement analysis. This
hook owns only the mechanical, deterministic controls: prerequisite validation,
filename/version integrity, Scope structure, identifier integrity, FR/NFR
namespace protection, Intent-to-Scope traceability, draft version history,
version progression, prior-version protection, Scope approval evidence,
SCOPE_BASELINE blocking gates, approved-baseline immutability, and fail-closed
behaviour.

Behaviour
---------
* Reads the Claude Code PreToolUse payload from stdin (JSON).
* Acts on `Write` / `Edit` / `MultiEdit` whose `file_path` is a
  `docs/pmo/scope/scope-v*.md`, and on `Bash` `git add` / `git commit` that
  includes such a file.
* Progressive DRAFT authoring of the current latest Scope version is always
  allowed. Full schema is enforced only at finalisation gates (Status
  `PM_REVIEWED` / `APPROVED`, or a git add/commit).
* Every unrelated operation is allowed silently (exit 0, no output).
* A blocked operation emits a structured PreToolUse deny response:
    {"hookSpecificOutput": {"hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": "<PMO-SCOPE-0XX>: <reason>"}}

Error IDs
---------
PMO-SCOPE-001  INTENT_NOT_VALIDATED            - Intent absent/unreadable; Intent
                                                Status != VALIDATED; Intent has
                                                no Intent Version value; no
                                                structurally valid, matching PM
                                                approval record at
                                                .pmo/approvals/intent-approval.yaml
                                                (decision APPROVED,
                                                approval_source PM_EXPLICIT,
                                                artifact/version match); or the
                                                Intent's project identity does
                                                not match project-config.yaml.
                                                Reuses
                                                intent_approval_core.validate_pm_approval
                                                (the same rule
                                                intent-schema-guard.py enforces
                                                as PMO-INTENT-011) and
                                                .validate_project_identity - no
                                                duplicated approval-validation
                                                truth. There is deliberately NO
                                                numeric Intent-version floor: a
                                                VALIDATED Intent is a legitimate
                                                governed baseline at any version
                                                (e.g. "0.3") once a matching PM
                                                approval exists ("approval is
                                                the baseline" - Option B).
                                                project-config's
                                                workflow.intent.approved /
                                                artifacts.intent.status fields
                                                are NOT consulted here - they
                                                are derived/display state, not
                                                authorization; the canonical
                                                Intent + its approval evidence
                                                are the sole source of truth
                                                (governance.source_of_truth:
                                                "repository").
PMO-SCOPE-002  PROJECT_IDENTITY_MISMATCH       - Scope Project / Client /
                                                Project ID != project-config.
PMO-SCOPE-003  SCOPE_SCHEMA_INVALID            - required section(s) / Document
                                                Control field(s) absent at a
                                                gate; TASK-* identifiers used;
                                                an OPEN item unmanaged or with an
                                                unknown Required Before stage;
                                                Version History incomplete;
                                                approved Scope Next Stage wrong.
PMO-SCOPE-004  INVALID_SCOPE_STATUS            - Status not one of the allowed
                                                Scope statuses.
PMO-SCOPE-005  VERSION_FILENAME_MISMATCH       - filename version != document
                                                `Scope Version`.
PMO-SCOPE-006  SCOPE_VERSION_OVERWRITE         - Write/Edit against a historical
                                                or APPROVED Scope version.
PMO-SCOPE-007  INTENT_TRACEABILITY_INCOMPLETE  - an active INT-REQ is absent from
                                                (or duplicated / undispositioned
                                                in) the Intent-to-Scope
                                                Traceability section.
PMO-SCOPE-008  RESERVED_REQUIREMENT_ID         - Scope defines FR-XXX / NFR-XXX.
PMO-SCOPE-009  DUPLICATE_OR_REUSED_IDENTIFIER  - an identifier defined twice, or
                                                a retired SCP-REQ id reused for
                                                an unrelated requirement.
PMO-SCOPE-010  INVALID_VERSION_PROGRESSION     - first Scope not 0.1; a skipped /
                                                decremented / reused version;
                                                APPROVED status on a 0.x file.
PMO-SCOPE-011  SCOPE_BASELINE_BLOCKER          - approval attempted while a
                                                Blocking: YES OPEN item is gated
                                                at (or before) SCOPE_BASELINE.
PMO-SCOPE-012  UNCONTROLLED_SCOPE_EXPANSION    - a Potential Scope Expansion item
                                                is also treated as committed
                                                in-scope with no PM disposition.
PMO-SCOPE-013  APPROVAL_REQUIRED               - scope-v1.0 -> APPROVED without a
                                                well-formed
                                                `.pmo/approvals/scope-approval.yaml`.
PMO-SCOPE-014  SCOPE_GUARD_INTERNAL_ERROR      - unexpected exception during a
                                                controlled Scope validation
                                                (fail closed).
PMO-SCOPE-015  OPEN_ID_PROVENANCE_MISMATCH     - an Open Items record breaks the
                                                identifier-provenance rule:
                                                either a Scope-native
                                                `SCP-OPEN-<n>` record cites an
                                                Intent `OPEN-<m>` question (a
                                                carried question renamed into
                                                the Scope namespace - it must
                                                keep its `OPEN-<m>` id), or a
                                                bare `OPEN-<n>` record in the
                                                Scope Open Items register does
                                                not correspond to any `OPEN`
                                                definition in
                                                `docs/pmo/intent/intent.md`
                                                (a mislabelled Scope-native
                                                question, or a retired Intent
                                                `OPEN` id reused). Deterministic
                                                only; skipped when the Intent
                                                cannot be read or defines no
                                                `OPEN` question.

Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

# Imported under its own namespace (never `from ... import <bare names>`):
# this module already defines its own `_clean` / `_norm_status` / `deny` /
# `Decision` / `validate_project_identity` for SCOPE's own field parsing, and
# bare-importing same-named functions from intent_approval_core would
# silently shadow them. `iac.*` is used explicitly at every call site instead
# - see `validate_prerequisite_intent` (PMO-SCOPE-001) for why: it reuses
# `intent_approval_core.validate_pm_approval` - the exact same rule
# `intent-schema-guard.py` enforces as PMO-INTENT-011 - so there is no
# duplicated approval-validation truth between the Intent and Scope guards.
import intent_approval_core as iac  # noqa: E402


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

SCOPE_DIR_POSIX = "docs/pmo/scope"
SCOPE_FILE_RE = re.compile(r"^scope-v(\d+)\.(\d+)\.md$")
INTENT_POSIX = "docs/pmo/intent/intent.md"
CONFIG_RELPATH = os.path.join(".pmo", "project-config.yaml")
SCOPE_APPROVAL_RELPATH = os.path.join(".pmo", "approvals", "scope-approval.yaml")
SCOPE_APPROVAL_POSIX = ".pmo/approvals/scope-approval.yaml"
SCOPE_V1_POSIX = "docs/pmo/scope/scope-v1.0.md"

ALLOWED_STATUSES = (
    "DRAFT_CLIENT_REVIEW",
    "CLIENT_FEEDBACK_RECEIVED",
    "PM_REVIEWED",
    "APPROVED",
    "SUPERSEDED",
)
FINALIZING_STATUSES = ("PM_REVIEWED", "APPROVED")

REQUIRED_SECTIONS = (
    "Document Control",
    "Executive Scope Summary",
    "Scope Basis",
    "Product Platforms and Interfaces",
    "Users and Roles",
    "Detailed Scope of Work",
    "Key User and Operational Workflows",
    "Brand and Design Guidelines",
    "Third-Party Integrations",
    "Data and Content Requirements",
    "Assumptions",
    "Dependencies",
    "Scope Gaps",
    "Open Questions",
    "Explicitly Out of Scope",
    "Client Responsibilities",
    "Delivery Team Responsibilities",
    "Commercial and Change-Control Boundaries",
    "Work Breakdown Structure",
    "Intent-to-Scope Traceability",
    "Scope Validation Summary",
    "Client Review Questions",
    "Acceptance and Approval",
    "Version History",
)

REQUIRED_DOC_CONTROL_FIELDS = (
    "Project",
    "Client",
    "Project ID",
    "PM",
    "Scope Version",
    "Status",
    "Intent Version",
    "Date",
    "Repository",
    "Source Count",
    "Previous Scope Version",
    "Next Stage",
)

# Scope-owned identifier namespaces whose definitions must be unique.
SCOPE_NAMESPACES = (
    "SCP-REQ", "SCP-ASM", "SCP-DEP", "SCP-GAP", "SCP-OPEN", "SCP-OOS",
    "BRAND-OPEN", "WF", "INTG", "CLIENT-RESP", "DELIVERY-RESP", "WBS",
    "PSE", "CRQ", "SCP-RISK", "SCP-CONFLICT",
)

TRACE_DISPOSITIONS = ("COVERED", "PARTIALLY_COVERED", "OPEN", "DEFERRED", "EXCLUDED")

_RESERVED_ID_RE = re.compile(
    r"^[\s>|`*_+\-#.0-9\[\]]*((?:FR|NFR)-\d+)(?![A-Za-z0-9-])", re.MULTILINE
)
_TASK_ID_RE = re.compile(
    r"^[\s>|`*_+\-#.0-9\[\]]*(TASK-\d+)(?![A-Za-z0-9-])", re.MULTILINE
)
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(\S.*?)\s*#*\s*$")
_OPEN_ID_LEADING_RE = re.compile(
    r"^[\s>|`*_+\-#.0-9\[\]]*((?:BRAND-OPEN|SCP-OPEN|OPEN)-\d+)(?![A-Za-z0-9-])"
)


# --------------------------------------------------------------------------- #
# Workflow-stage ordering (shared model with the Intent governance)
# --------------------------------------------------------------------------- #

WORKFLOW_STAGES = (
    "INTENT_VALIDATION",
    "REQUIREMENT_GATHERING",
    "SCOPE_BASELINE",
    "SPECIFICATION_GENERATION",
    "DEVELOPMENT",
    "QA",
    "UAT",
    "DEPLOYMENT",
)
STAGE_ORDER = {name: i for i, name in enumerate(WORKFLOW_STAGES)}
SCOPE_CURRENT_GATE_INDEX = STAGE_ORDER["SCOPE_BASELINE"]

_STAGE_ALIASES = {
    "INTENT VALIDATION": "INTENT_VALIDATION",
    "INTENT VALIDATED": "INTENT_VALIDATION",
    "VALIDATE INTENT": "INTENT_VALIDATION",
    "REQUIREMENT GATHERING": "REQUIREMENT_GATHERING",
    "REQUIREMENTS GATHERING": "REQUIREMENT_GATHERING",
    "RG": "REQUIREMENT_GATHERING",
    "SCOPE BASELINE": "SCOPE_BASELINE",
    "SCOPE BASELINING": "SCOPE_BASELINE",
    "BASELINE": "SCOPE_BASELINE",
    "SCOPE": "SCOPE_BASELINE",
    "SCOPE APPROVAL": "SCOPE_BASELINE",
    "SPECIFICATION GENERATION": "SPECIFICATION_GENERATION",
    "SPECIFICATIONS GENERATION": "SPECIFICATION_GENERATION",
    "SPEC GENERATION": "SPECIFICATION_GENERATION",
    "SPECIFICATION": "SPECIFICATION_GENERATION",
    "SPECIFICATIONS": "SPECIFICATION_GENERATION",
    "SPECS": "SPECIFICATION_GENERATION",
    "SPEC": "SPECIFICATION_GENERATION",
    "DEV": "DEVELOPMENT",
    "DEVELOP": "DEVELOPMENT",
    "BUILD": "DEVELOPMENT",
    "IMPLEMENTATION": "DEVELOPMENT",
    "QUALITY ASSURANCE": "QA",
    "TESTING": "QA",
    "TEST": "QA",
    "USER ACCEPTANCE": "UAT",
    "USER ACCEPTANCE TESTING": "UAT",
    "DEPLOY": "DEPLOYMENT",
    "RELEASE": "DEPLOYMENT",
    "GO LIVE": "DEPLOYMENT",
    "LAUNCH": "DEPLOYMENT",
    "PRODUCTION": "DEPLOYMENT",
}


def normalize_stage(value):
    """Canonical workflow stage for a free-text value, or None when unknown."""
    if value is None:
        return None
    base = re.sub(r"[^A-Za-z0-9]+", " ", str(value)).strip().upper()
    if not base:
        return None
    trimmed = re.sub(r"\b(GATE|STAGE|PHASE|MILESTONE|STEP)\b", " ", base)
    trimmed = re.sub(r"\s+", " ", trimmed).strip()
    for cand in (base, base.replace(" ", "_"), trimmed, trimmed.replace(" ", "_")):
        if not cand:
            continue
        if cand in STAGE_ORDER:
            return cand
        if cand in _STAGE_ALIASES:
            return _STAGE_ALIASES[cand]
    return None


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
# Minimal YAML subset parser (stdlib only)
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
    for raw in text.splitlines():
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
    path = os.path.join(root, CONFIG_RELPATH)
    text = read_text(path)
    if text is None:
        return None
    try:
        data = parse_project_config(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def parse_scope_version_from_filename(path):
    """Return (major, minor) for a scope-v*.md path, or None."""
    match = SCOPE_FILE_RE.match(os.path.basename(path or ""))
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)))


def is_scope_file_path(path, root):
    if not isinstance(path, str) or not path.strip():
        return False
    cand = os.path.normpath(path.strip())
    if not os.path.isabs(cand):
        cand = os.path.normpath(os.path.join(root, cand))
    cand = cand.replace(os.sep, "/")
    base = os.path.basename(cand)
    return ("/" + SCOPE_DIR_POSIX + "/") in (cand + "/") \
        and SCOPE_FILE_RE.match(base) is not None


def list_scope_versions(root):
    """Sorted list of (major, minor, abspath) for docs/pmo/scope/scope-v*.md."""
    out = []
    d = os.path.join(root, "docs", "pmo", "scope")
    try:
        names = os.listdir(d)
    except Exception:
        return out
    for name in names:
        m = SCOPE_FILE_RE.match(name)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), os.path.join(d, name)))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


def determine_latest_scope_version(versions):
    if not versions:
        return None
    return max(versions, key=lambda t: (t[0], t[1]))


# --------------------------------------------------------------------------- #
# Metadata / heading helpers
# --------------------------------------------------------------------------- #

def _find_field(content, label):
    core = r"\s+".join(re.escape(p) for p in label.split())
    pattern = re.compile(
        r"^[ \t>*\-+|]*\**\s*" + core + r"\s*\**\s*[:|]\s*\**\s*(.+?)\s*\**\s*\|?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    m = pattern.search(content or "")
    if not m:
        return None
    value = m.group(1).strip().strip("*").strip().strip("`").strip()
    return value or None


def parse_scope_metadata(content):
    meta = {}
    for label in ("Project ID", "Project Name", "Project", "Client", "PM",
                  "Scope Version", "Status", "Intent Version", "Date",
                  "Repository", "Source Count", "Previous Scope Version",
                  "Next Stage"):
        v = _find_field(content, label)
        if v is not None:
            meta[label.lower()] = v
    if "project" not in meta and "project name" in meta:
        meta["project"] = meta["project name"]
    return meta


def _norm_status(value):
    if not value:
        return None
    s = value.strip().upper().split("(")[0].strip()
    s = re.sub(r"[^A-Z0-9]+", "_", s).strip("_")
    return s or None


def _norm_stage_token(value):
    return re.sub(r"[^A-Z0-9]+", "_", (value or "").strip().upper()).strip("_")


def _norm_heading(text):
    text = re.sub(r"\s*/\s*", " / ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def _heading_level(line):
    m = _HEADING_RE.match(line or "")
    return len(m.group(1)) if m else 0


def document_heading_texts(content):
    out = []
    for line in (content or "").splitlines():
        m = _HEADING_RE.match(line)
        if m:
            out.append(_norm_heading(m.group(2)))
    return out


def section_block(content, title_substring):
    """Body text of the first heading whose normalised text contains
    `title_substring`, up to the next heading of the same-or-higher level."""
    target = _norm_heading(title_substring)
    lines = (content or "").splitlines()
    start = None
    start_level = 0
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m and target in _norm_heading(m.group(2)):
            start = i
            start_level = len(m.group(1))
            break
    if start is None:
        return None
    body = []
    for j in range(start + 1, len(lines)):
        lv = _heading_level(lines[j])
        if lv and lv <= start_level:
            break
        body.append(lines[j])
    return "\n".join(body)


def parse_version_tuple(text):
    m = re.match(r"^\s*v?(\d+)\.(\d+)\s*$", str(text or ""))
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


# --------------------------------------------------------------------------- #
# Write/Edit content reconstruction
# --------------------------------------------------------------------------- #

def resulting_content(tool_name, tool_input, existing):
    if tool_name == "Write":
        c = tool_input.get("content")
        return c if isinstance(c, str) else ""
    if tool_name == "Edit":
        base = existing or ""
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
        base = existing or ""
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
# Identifier definition / duplicate / reuse checks
# --------------------------------------------------------------------------- #

def _definition_regex(namespace):
    if namespace == "WBS":
        body = r"WBS-\d+(?:\.\d+)*"
    else:
        body = re.escape(namespace) + r"-\d+"
    return re.compile(
        r"^[\s>|`*_+\-#.0-9\[\]]*(" + body + r")(?![A-Za-z0-9-])", re.MULTILINE
    )


def _line_leading_ids(content, namespace):
    return [m.group(1) for m in _definition_regex(namespace).finditer(content or "")]


def detect_reserved_ids(content):
    """PMO-SCOPE-008 - FR-XXX / NFR-XXX must not be defined in Scope."""
    hits = sorted(set(m.group(1) for m in _RESERVED_ID_RE.finditer(content or "")))
    if hits:
        return deny(
            "PMO-SCOPE-008",
            "Scope must not define specification identifiers {}. FR-XXX / "
            "NFR-XXX are reserved exclusively for Specifications. Scope uses "
            "SCP-REQ-XXX (and SCP-ASM / SCP-DEP / SCP-GAP / SCP-OPEN / SCP-OOS "
            "/ WF / INTG / CLIENT-RESP / DELIVERY-RESP / WBS).".format(
                ", ".join(hits)
            ),
        )
    return None


def validate_identifier_definitions(content):
    """PMO-SCOPE-009 - each Scope identifier is defined at most once."""
    for ns in SCOPE_NAMESPACES:
        counts = {}
        for ident in _line_leading_ids(content, ns):
            counts[ident] = counts.get(ident, 0) + 1
        dups = sorted(i for i, n in counts.items() if n > 1)
        if dups:
            return deny(
                "PMO-SCOPE-009",
                "duplicate identifier definition(s): {}. Each identifier must "
                "be defined once; repeated references are fine.".format(
                    ", ".join(dups)
                ),
            )
    return None


def _active_scp_req_ids(content):
    ids = set()
    for m in _definition_regex("SCP-REQ").finditer(content or ""):
        line = (content or "")[max(0, m.start()):m.start() + 400].splitlines()[0]
        if "retire" not in line.lower():
            ids.add(m.group(1))
    return ids


def _retired_scp_req_ids(text):
    out = set()
    for line in (text or "").splitlines():
        m = re.search(r"(SCP-REQ-\d+)", line)
        if m and "retire" in line.lower():
            out.add(m.group(1))
    return out


def compare_scp_req_identity_across_versions(new_content, root, exclude_path):
    """PMO-SCOPE-009 - a retired SCP-REQ id must not be reused for an
    unrelated requirement in a later version."""
    retired = set()
    for _maj, _min, path in list_scope_versions(root):
        if os.path.abspath(path) == os.path.abspath(exclude_path or ""):
            continue
        retired |= _retired_scp_req_ids(read_text(path))
    reused = sorted(_active_scp_req_ids(new_content) & retired)
    if reused:
        return deny(
            "PMO-SCOPE-009",
            "retired SCP-REQ identifier(s) {} reused for an active requirement. "
            "Retired identifiers are never reassigned; allocate a new id.".format(
                ", ".join(reused)
            ),
        )
    return None


def detect_task_identifiers(content):
    """TASK-* implementation identifiers are not permitted in Scope."""
    hits = sorted(set(m.group(1) for m in _TASK_ID_RE.finditer(content or "")))
    if hits:
        return deny(
            "PMO-SCOPE-003",
            "developer task identifier(s) {} found. The Work Breakdown "
            "Structure must remain product-level (WBS-* only); implementation "
            "tasks belong to Development planning, not Scope.".format(
                ", ".join(hits)
            ),
        )
    return None


# --------------------------------------------------------------------------- #
# OPEN-item parser (ported from the corrected Intent guard)
# --------------------------------------------------------------------------- #

def _split_table_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_table_line(line):
    return line.strip().startswith("|")


def _is_separator_row(line):
    s = line.strip()
    return bool(s) and "-" in s and re.match(r"^\|?[\s:\-|]+\|?$", s) is not None


def _table_header_for(lines, row_index):
    start = row_index
    while start - 1 >= 0 and _is_table_line(lines[start - 1]):
        start -= 1
    end = row_index
    while end + 1 < len(lines) and _is_table_line(lines[end + 1]):
        end += 1
    sep = next((k for k in range(start, end + 1) if _is_separator_row(lines[k])), None)
    header_idx = sep - 1 if (sep is not None and sep - 1 >= start) else start
    if header_idx == row_index:
        return None
    return lines[header_idx]


def _column_index_map(header_line):
    cells = [c.strip().lower() for c in _split_table_row(header_line)]
    cmap = {}
    for idx, cell in enumerate(cells):
        if "question" in cell:
            cmap.setdefault("question", idx)
        if "owner" in cell:
            cmap.setdefault("owner", idx)
        if cell == "block" or "blocking" in cell:
            cmap.setdefault("blocking", idx)
        if ("required before" in cell or "required-before" in cell
                or "resolution stage" in cell or "resolve by" in cell):
            cmap.setdefault("required_before", idx)
    return cmap


_LABEL_QUESTION_RE = re.compile(
    r"(?:^|\n|\|)\s*[\-*>#\s]*\**\s*question\s*\**\s*[:|]\s*([^\n|]+)", re.I)
_LABEL_OWNER_RE = re.compile(
    r"(?:^|\n|\|)\s*[\-*>#\s]*\**\s*owner\s*\**\s*[:|]\s*([^\n|]+)", re.I)
_LABEL_BLOCKING_RE = re.compile(
    r"\bblock(?:ing|er)?\b\s*\**\s*[:|]?\s*\**\s*(yes|no)\b", re.I)
_LABEL_REQ_BEFORE_RE = re.compile(
    r"(?:required\s*[-_ ]?before|resolution\s*stage|resolve\s*by)\s*\**\s*"
    r"[:|]?\s*\**\s*([A-Za-z][A-Za-z0-9 /_&-]{1,60})", re.I)


def _record_fields(text, header_line, row_cells):
    question = owner = blocking = required_before = None
    if header_line is not None and row_cells is not None:
        cmap = _column_index_map(header_line)

        def cell(key):
            idx = cmap.get(key)
            if idx is None or idx >= len(row_cells):
                return None
            return row_cells[idx].strip() or None

        question = cell("question")
        owner = cell("owner")
        blocking = cell("blocking")
        required_before = cell("required_before")
    if question is None:
        if "?" in text:
            question = "present"
        else:
            m = _LABEL_QUESTION_RE.search(text)
            if m and m.group(1).strip():
                question = m.group(1).strip()
    if owner is None:
        m = _LABEL_OWNER_RE.search(text)
        if m and m.group(1).strip():
            owner = m.group(1).strip()
        elif re.search(r"\bowner\b", text, re.I):
            owner = "present"
    if blocking is None:
        m = _LABEL_BLOCKING_RE.search(text)
        if m:
            blocking = m.group(1)
        elif re.search(r"\bblock(?:ing|er)?\b", text, re.I):
            blocking = "present"
    if required_before is None:
        m = _LABEL_REQ_BEFORE_RE.search(text)
        if m and m.group(1).strip():
            required_before = m.group(1).strip()
    return question, owner, blocking, required_before


def _open_questions_block(content):
    lines = (content or "").splitlines()
    start = None
    start_level = 0
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if not m:
            continue
        h = _norm_heading(m.group(2))
        if "open questions" in h or "open items" in h:
            start = i
            start_level = len(m.group(1))
            break
    if start is None:
        return ""
    body = []
    for j in range(start + 1, len(lines)):
        lv = _heading_level(lines[j])
        if lv and lv <= max(start_level, 2):
            break
        body.append(lines[j])
    return "\n".join(body)


def parse_open_items(content):
    """One dict per OPEN / SCP-OPEN / BRAND-OPEN definition inside the Open
    Questions section: id, question, owner, blocking, required_before_raw,
    stage."""
    block = _open_questions_block(content)
    if not block:
        return []
    lines = block.splitlines()
    seen = set()
    records = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        m = _OPEN_ID_LEADING_RE.match(line)
        if not m:
            i += 1
            continue
        ident = m.group(1)
        if ident in seen:
            i += 1
            continue
        seen.add(ident)
        stripped = line.strip()
        header_line = None
        row_cells = None
        if stripped.startswith("|") and stripped.count("|") >= 2:
            header_line = _table_header_for(lines, i)
            row_cells = _split_table_row(line)
            text = line if header_line is None else header_line + "\n" + line
            nxt = i + 1
        else:
            level = _heading_level(line)
            j = i + 1
            buf = [line]
            while j < n:
                if _OPEN_ID_LEADING_RE.match(lines[j]):
                    break
                lv = _heading_level(lines[j])
                if lv and (not level or lv <= level):
                    break
                buf.append(lines[j])
                j += 1
            text = "\n".join(buf)
            nxt = j
        q, own, blk, rb = _record_fields(text, header_line, row_cells)
        records.append({
            "id": ident, "question": q, "owner": own, "blocking": blk,
            "required_before_raw": rb,
            "stage": normalize_stage(rb) if rb else None,
            "text": text,
        })
        i = nxt
    return records


def validate_open_items_governance(content):
    """PMO-SCOPE-003 - every OPEN item is a managed record with a known
    Required Before stage."""
    for rec in parse_open_items(content):
        ident = rec["id"]
        missing = []
        if not rec["question"]:
            missing.append("Question")
        if not rec["owner"]:
            missing.append("Owner")
        if not rec["blocking"]:
            missing.append("Blocking status")
        if not rec["required_before_raw"]:
            missing.append("Required Before")
        if missing:
            return deny(
                "PMO-SCOPE-003",
                "open item {} is not fully managed - missing {}. Each OPEN "
                "item must record Question, Owner, Blocking (YES/NO) and "
                "Required Before (a workflow stage).".format(
                    ident, ", ".join(missing)
                ),
            )
        if str(rec["blocking"]).strip().upper() not in ("YES", "NO"):
            return deny(
                "PMO-SCOPE-003",
                "open item {} has an invalid Blocking value '{}' - it must be "
                "YES or NO.".format(ident, rec["blocking"]),
            )
        if rec["stage"] is None:
            return deny(
                "PMO-SCOPE-003",
                "open item {} has an unrecognised Required Before stage '{}'. "
                "Use one of: {}.".format(
                    ident, rec["required_before_raw"], ", ".join(WORKFLOW_STAGES)
                ),
            )
    return None


def validate_scope_baseline_blockers(content):
    """PMO-SCOPE-011 - approval is blocked while a Blocking: YES OPEN item is
    gated at or before SCOPE_BASELINE."""
    offenders = []
    for rec in parse_open_items(content):
        if str(rec["blocking"] or "").strip().upper() != "YES":
            continue
        if rec["stage"] is None:
            continue  # PMO-SCOPE-003 owns an unrecognised stage
        if STAGE_ORDER[rec["stage"]] <= SCOPE_CURRENT_GATE_INDEX:
            offenders.append("{} (Required Before: {})".format(
                rec["id"], rec["stage"]))
    if offenders:
        return deny(
            "PMO-SCOPE-011",
            "the Scope cannot be approved while these Blocking: YES OPEN "
            "item(s) are gated at or before SCOPE_BASELINE: {}. Items gated at "
            "SPECIFICATION_GENERATION or later carry forward.".format(
                "; ".join(offenders)
            ),
        )
    return None


# --------------------------------------------------------------------------- #
# OPEN identifier provenance  (PMO-SCOPE-015)
# --------------------------------------------------------------------------- #
#
# Lifecycle-identity rule: a question first raised in the validated Intent keeps
# its exact `OPEN-<n>` identifier in every downstream artifact. `SCP-OPEN-<n>` is
# reserved for a question first raised during Requirement Gathering / Scope
# creation. This control is deterministic only - it never guesses whether two
# differently worded questions are "the same". It fires on two mechanical facts:
#
#   1. a Scope-native `SCP-OPEN-<n>` Open Items record whose own text cites an
#      Intent `OPEN-<m>` question  -> the record declares itself carried while
#      wearing the Scope namespace (a pure namespace translation); it must be
#      defined as `OPEN-<m>`.
#   2. a bare `OPEN-<n>` Open Items record whose id matches no `OPEN` definition
#      in `docs/pmo/intent/intent.md`  -> a bare `OPEN-<n>` is reserved for a
#      carried Intent question, so one with no Intent origin is either a
#      mislabelled Scope-native question (use `SCP-OPEN-<n>`) or a reused
#      retired Intent id.
#
# When intent.md is absent/unreadable or defines no `OPEN` question, provenance
# cannot be established and the check is skipped.

_INTENT_OPEN_DEF_RE = re.compile(
    r"(?m)^[\s>|`*_+\-#.0-9\[\]]*(OPEN-\d+)(?![A-Za-z0-9-])"
)
_CITED_OPEN_RE = re.compile(r"(?<![A-Za-z0-9-])(OPEN-\d+)(?![A-Za-z0-9-])")
_SCOPE_OPEN_ID_RE = re.compile(r"^(SCP-OPEN|OPEN)-(\d+)$")


def read_intent_open_ids(root):
    """Set of line-leading `OPEN-<n>` definitions in the validated Intent.

    Uses the same "line-leading, after markup" notion of a definition as the
    rest of this hook, so a prose mention of a retired id in intent.md is not
    counted.
    """
    text = read_text(os.path.join(root, INTENT_POSIX))
    if text is None:
        return set()
    return set(_INTENT_OPEN_DEF_RE.findall(text))


def validate_open_id_provenance(content, root):
    """PMO-SCOPE-015 - carried Intent OPEN questions keep their `OPEN-<n>` id."""
    intent_open = read_intent_open_ids(root)
    if not intent_open:
        return None  # cannot establish provenance - do not guess
    for rec in parse_open_items(content):
        m = _SCOPE_OPEN_ID_RE.match(rec.get("id") or "")
        if not m:
            continue  # BRAND-OPEN-* and anything else are out of scope here
        prefix = m.group(1)
        ident = rec["id"]
        if prefix == "OPEN":
            if ident not in intent_open:
                return deny(
                    "PMO-SCOPE-015",
                    "Open Items record {id} uses a bare OPEN-<n> identifier but "
                    "docs/pmo/intent/intent.md defines no {id}. A bare OPEN-<n> "
                    "id is reserved for a question carried forward from the "
                    "validated Intent and must match an Intent OPEN definition. "
                    "A question first raised in Scope must use SCP-OPEN-<n>; a "
                    "retired Intent OPEN id must not be reused.".format(id=ident),
                )
        else:  # SCP-OPEN-<n>
            cited = sorted(set(_CITED_OPEN_RE.findall(rec.get("text") or ""))
                           & intent_open)
            if cited:
                return deny(
                    "PMO-SCOPE-015",
                    "Open Items record {id} is Scope-native (SCP-OPEN-*) but "
                    "its record cites carried-forward Intent question(s) {cited}. "
                    "A question that originates in the validated Intent keeps "
                    "its exact {cited} identifier in Scope - it is not renamed "
                    "into SCP-OPEN-<n>. Define it under its Intent id, or, if it "
                    "is genuinely a new Scope question, remove the Intent "
                    "cross-reference.".format(
                        id=ident, cited=", ".join(cited)
                    ),
                )
    return None


# --------------------------------------------------------------------------- #
# Prerequisite / identity
# --------------------------------------------------------------------------- #

def _clean(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def validate_prerequisite_intent(root):
    """PMO-SCOPE-001 - Scope-entry eligibility ("approval is the baseline",
    Option B). Directly validates the canonical governed Intent state - it
    does not consult project-config's Intent-derived fields at all, since
    those are display/index state with no synchronization owner (see
    intent_approval_core.py module docstring for the full architecture
    note). Required, in order:

    A. Intent exists and is readable.
    B. Intent Status == VALIDATED.
    C. A structurally valid, matching PM approval record exists (decision
       APPROVED, approval_source PM_EXPLICIT, artifact + version match) -
       reuses `intent_approval_core.validate_pm_approval` unchanged, so
       this is exactly the same rule intent-schema-guard.py enforces as
       PMO-INTENT-011 for the Intent's own VALIDATED transition.
    D. The Intent's project identity matches project-config.yaml - reuses
       `intent_approval_core.validate_project_identity` unchanged.

    Deliberately NO numeric Intent-version floor: a VALIDATED Intent is a
    legitimate governed baseline at any version string once a matching PM
    approval exists.
    """
    intent_path = os.path.join(root, INTENT_POSIX)
    text = read_text(intent_path)
    if text is None:
        return deny("PMO-SCOPE-001",
                    "docs/pmo/intent/intent.md not found - Scope must not be "
                    "based on a missing/unvalidated Intent.")

    meta = iac.parse_doc_control(text)
    status = iac._norm_status(meta.get("status"))
    if status != "VALIDATED":
        return deny("PMO-SCOPE-001",
                    "Intent Status is '{}', not VALIDATED.".format(status))

    if not iac._clean(meta.get("intent version")):
        return deny("PMO-SCOPE-001",
                    "the Intent has no 'Intent Version' in Document "
                    "Control.")

    # C - reuse the exact same PM-approval rule intent-schema-guard.py
    # enforces (PMO-INTENT-011). `existing_status=None` is that function's
    # documented contract for an independent, from-scratch verification
    # (it is not asking "did this Write just promote the Intent" - it is
    # asking "is there, right now, a valid approval for this Intent").
    approval_check = iac.validate_pm_approval(None, "VALIDATED", meta, root)
    if approval_check is not None:
        return deny(
            "PMO-SCOPE-001",
            "the canonical Intent is not backed by a valid, matching PM "
            "approval record at '{}' - {}".format(
                iac.INTENT_APPROVAL_POSIX, approval_check.message),
        )

    # D - the Intent's own project identity must match project-config.
    cfg = load_config(root)
    if not isinstance(cfg, dict):
        return deny("PMO-SCOPE-001",
                    ".pmo/project-config.yaml is missing or unreadable.")
    identity_check = iac.validate_project_identity(meta, cfg)
    if identity_check is not None:
        return deny(
            "PMO-SCOPE-001",
            "the Intent's project identity does not match "
            "project-config.yaml - {}".format(identity_check.message),
        )

    return None


def validate_project_identity(meta, config):
    """PMO-SCOPE-002 - Scope identity must match project-config (the authority)."""
    if not isinstance(config, dict):
        return None
    project = config.get("project")
    if not isinstance(project, dict):
        return None
    checks = (
        ("project id", project.get("id"), "Project ID"),
        ("project", project.get("name"), "Project"),
        ("client", project.get("client"), "Client"),
    )
    for key, cfg_val, label in checks:
        doc_val = _clean(meta.get(key))
        cfg_val = _clean(cfg_val)
        if not doc_val or not cfg_val:
            continue
        if doc_val.casefold() != cfg_val.casefold():
            return deny(
                "PMO-SCOPE-002",
                "Scope {} '{}' does not match .pmo/project-config.yaml "
                "('{}'). project-config is the authority.".format(
                    label, doc_val, cfg_val
                ),
            )
    return None


# --------------------------------------------------------------------------- #
# Structural validation (finalisation gate)
# --------------------------------------------------------------------------- #

def validate_status(status, at_gate):
    """PMO-SCOPE-004 - status, when present, must be an allowed value.
    At a finalisation gate the status must also be present."""
    if status is None:
        if at_gate:
            return deny("PMO-SCOPE-004",
                        "Scope Status is not set. Allowed: {}.".format(
                            ", ".join(ALLOWED_STATUSES)))
        return None
    if status not in ALLOWED_STATUSES:
        return deny("PMO-SCOPE-004",
                    "Scope Status '{}' is not allowed. Allowed: {}.".format(
                        status, ", ".join(ALLOWED_STATUSES)))
    return None


def validate_required_sections(content):
    """PMO-SCOPE-003 - the full Scope section skeleton must be present."""
    present = document_heading_texts(content)
    missing = [title for title in REQUIRED_SECTIONS
               if not any(_norm_heading(title) in h for h in present)]
    if missing:
        return deny(
            "PMO-SCOPE-003",
            "Scope is missing required section(s): {}.".format("; ".join(missing)),
        )
    return None


def validate_document_control(meta, status):
    """PMO-SCOPE-003 - Document Control fields + Next Stage rules."""
    missing = [f for f in REQUIRED_DOC_CONTROL_FIELDS if not meta.get(f.lower())]
    if missing:
        return deny(
            "PMO-SCOPE-003",
            "Document Control is missing field(s): {}.".format(", ".join(missing)),
        )
    ns = _norm_stage_token(meta.get("next stage"))
    if status == "APPROVED":
        if ns == "DEVELOPMENT":
            return deny(
                "PMO-SCOPE-003",
                "an APPROVED Scope must not point Next Stage directly to "
                "DEVELOPMENT - it authorises SPECIFICATION_GENERATION only.",
            )
        if ns != "SPECIFICATION_GENERATION":
            return deny(
                "PMO-SCOPE-003",
                "an APPROVED Scope must declare Next Stage: "
                "SPECIFICATION_GENERATION (found '{}').".format(
                    meta.get("next stage")
                ),
            )
    return None


def read_intent_requirements(root):
    """Set of active INT-REQ ids defined as table rows in intent.md."""
    text = read_text(os.path.join(root, INTENT_POSIX)) or ""
    return set(re.findall(r"(?m)^\|\s*(INT-REQ-\d+)\s*\|", text))


def validate_intent_traceability(content, root):
    """PMO-SCOPE-007 - every active INT-REQ appears once, dispositioned, in the
    Intent-to-Scope Traceability section."""
    active = read_intent_requirements(root)
    if not active:
        return None
    body = section_block(content, "Intent-to-Scope Traceability")
    if body is None:
        return deny("PMO-SCOPE-007",
                    "no 'Intent-to-Scope Traceability' section - every active "
                    "INT-REQ must be traced.")
    lines = body.splitlines()
    missing, multi, undisposed = [], [], []
    for req in sorted(active):
        rows = [ln for ln in lines
                if re.search(r"(?<![A-Za-z0-9-])" + re.escape(req)
                             + r"(?![A-Za-z0-9-])", ln)]
        if not rows:
            missing.append(req)
            continue
        if len(rows) > 1:
            multi.append(req)
        if not any(any(d in ln.upper() for d in TRACE_DISPOSITIONS) for ln in rows):
            undisposed.append(req)
    if missing:
        return deny("PMO-SCOPE-007",
                    "active INT-REQ not present in Intent-to-Scope "
                    "Traceability: {}.".format(", ".join(missing)))
    if multi:
        return deny("PMO-SCOPE-007",
                    "INT-REQ appears more than once in the traceability "
                    "section: {}.".format(", ".join(multi)))
    if undisposed:
        return deny("PMO-SCOPE-007",
                    "INT-REQ has no disposition ({}): {}.".format(
                        "/".join(TRACE_DISPOSITIONS), ", ".join(undisposed)))
    return None


def validate_version_history(content, meta, root):
    """PMO-SCOPE-003 - Version History section carries the current version and,
    for revisions, a Previous Version that resolves to a real artifact."""
    body = section_block(content, "Version History")
    if body is None:
        return deny("PMO-SCOPE-003", "no 'Version History' section.")
    cur = _clean(meta.get("scope version"))
    if not cur:
        return deny("PMO-SCOPE-003",
                    "Version History cannot be validated - Scope Version is "
                    "not set.")
    if not re.search(r"(?<![0-9.])" + re.escape(cur) + r"(?![0-9.])", body):
        return deny("PMO-SCOPE-003",
                    "Version History does not record the current version "
                    "{}.".format(cur))
    tv = parse_version_tuple(cur)
    if tv and tv != (0, 1):
        rows = [ln for ln in body.splitlines()
                if cur in ln and ln.count("|") >= 2]
        if not rows:
            return deny("PMO-SCOPE-003",
                        "Version History has no row for {}.".format(cur))
        cells = [c.strip() for c in rows[-1].strip().strip("|").split("|")]
        if len([c for c in cells if c]) < 4:
            return deny("PMO-SCOPE-003",
                        "Version History row for {} is incomplete (needs "
                        "Version, Date, Status, Change Summary, Previous "
                        "Version).".format(cur))
        prev = None
        for c in cells:
            mm = re.search(r"\b(\d+\.\d+)\b", c)
            if mm and mm.group(1) != cur:
                prev = mm.group(1)
        if prev:
            existing = {"{}.{}".format(a, b) for a, b, _ in list_scope_versions(root)}
            if prev not in existing:
                return deny(
                    "PMO-SCOPE-003",
                    "Version History Previous Version {} has no scope-v{}.md "
                    "artifact.".format(prev, prev),
                )
    return None


def validate_uncontrolled_scope_expansion(content):
    """PMO-SCOPE-012 - a Potential Scope Expansion item must not also be
    treated as committed in-scope with no PM disposition."""
    body = section_block(content, "Potential Scope Expansion")
    if body is None:
        body = section_block(content, "POTENTIAL_SCOPE_EXPANSION")
    if body is None:
        return None
    dispo_keys = ("CHANGE_REQUEST", "CHANGE ORDER", "NEXT_PHASE",
                  "NEEDS_INTENT_UPDATE", "REJECTED", "DEFERRED", "PM DECISION",
                  "PM DISPOSITION", "DISPOSITION:", "DISPOSITION ",
                  "ROUTING", "PENDING")
    commit_keys = ("COMMITTED", "IN-SCOPE", "IN SCOPE", "APPROVED INTO SCOPE",
                   "ACCEPTED INTO SCOPE", "BASELINED")
    for ln in body.splitlines():
        m = re.match(r"^[\s>|`*_+\-#.0-9\[\]]*(PSE-\d+)(?![A-Za-z0-9-])", ln)
        if not m:
            continue
        up = ln.upper()
        if any(c in up for c in commit_keys) and not any(d in up for d in dispo_keys):
            return deny(
                "PMO-SCOPE-012",
                "Potential Scope Expansion item {} is marked as committed "
                "in-scope with no PM disposition. It must be routed (Change "
                "Request / next phase / Intent update / rejected) before it "
                "enters Scope.".format(m.group(1)),
            )
    return None


# --------------------------------------------------------------------------- #
# Version progression / historical protection
# --------------------------------------------------------------------------- #

def validate_version_progression(target_ver, versions, existing_status):
    """PMO-SCOPE-010 - a newly created Scope file must be the valid next
    version."""
    if target_ver is None:
        return deny("PMO-SCOPE-010",
                    "Scope file name must be scope-v<major>.<minor>.md.")
    existing = sorted((v[0], v[1]) for v in versions)
    if not existing:
        if target_ver != (0, 1):
            return deny("PMO-SCOPE-010",
                        "the first Scope artifact must be scope-v0.1.md (got "
                        "scope-v{}.{}.md).".format(*target_ver))
        return None
    latest = max(existing)
    if latest[0] == 0:
        if target_ver == (0, latest[1] + 1) or target_ver == (1, 0):
            return None
        return deny(
            "PMO-SCOPE-010",
            "invalid pre-baseline progression: latest draft is scope-v{}.{}.md; "
            "the next file must be scope-v0.{}.md or the approved baseline "
            "scope-v1.0.md (got scope-v{}.{}.md).".format(
                latest[0], latest[1], latest[1] + 1, *target_ver
            ),
        )
    if target_ver == (1, latest[1] + 1) or target_ver == (latest[0] + 1, 0):
        return None
    return deny(
        "PMO-SCOPE-010",
        "invalid post-baseline progression: latest baseline is scope-v{}.{}.md; "
        "a Change Request produces scope-v1.{}.md or scope-v{}.0.md.".format(
            latest[0], latest[1], latest[1] + 1, latest[0] + 1
        ),
    )


def detect_historical_scope_edit(target_ver, versions, existing_status):
    """PMO-SCOPE-006 - a Write/Edit must not target a historical or APPROVED
    Scope version."""
    if _norm_status(existing_status) == "APPROVED":
        return deny("PMO-SCOPE-006",
                    "scope-v{}.{}.md is APPROVED and immutable. Post-baseline "
                    "changes go through a Change Request (scope-v1.1.md / "
                    "scope-v2.0.md).".format(*(target_ver or (0, 0))))
    if target_ver is None:
        return None
    newer = sorted((v[0], v[1]) for v in versions if (v[0], v[1]) > target_ver)
    if newer:
        return deny(
            "PMO-SCOPE-006",
            "scope-v{}.{}.md is immutable version history - scope-v{}.{}.md "
            "already exists. Issue changes as a new version.".format(
                target_ver[0], target_ver[1], newer[-1][0], newer[-1][1]
            ),
        )
    return None


# --------------------------------------------------------------------------- #
# Filename / version match
# --------------------------------------------------------------------------- #

def validate_version_filename_match(meta, target_ver):
    """PMO-SCOPE-005 - filename version must equal document Scope Version."""
    doc_ver = parse_version_tuple(meta.get("scope version"))
    if doc_ver is None or target_ver is None:
        return None
    if doc_ver != target_ver:
        return deny(
            "PMO-SCOPE-005",
            "filename is scope-v{}.{}.md but the document declares Scope "
            "Version {}.{}.".format(
                target_ver[0], target_ver[1], doc_ver[0], doc_ver[1]
            ),
        )
    return None


# --------------------------------------------------------------------------- #
# Scope approval evidence
# --------------------------------------------------------------------------- #

def validate_scope_approval(meta, root):
    """PMO-SCOPE-013 - scope-v1.0 -> APPROVED needs explicit PM + client
    approval evidence."""
    path = os.path.join(root, SCOPE_APPROVAL_RELPATH)
    text = read_text(path)
    if text is None:
        return deny("PMO-SCOPE-013",
                    "no approval record at {}.".format(SCOPE_APPROVAL_POSIX))
    try:
        data = parse_project_config(text)
    except Exception as exc:
        return deny("PMO-SCOPE-013",
                    "approval record unreadable ({}).".format(exc))
    if not isinstance(data, dict) or not data:
        return deny("PMO-SCOPE-013", "approval record is malformed.")

    artifact = _clean(data.get("artifact"))
    artifact_norm = (os.path.normpath(artifact).replace(os.sep, "/")
                     if artifact else None)
    if artifact_norm != SCOPE_V1_POSIX:
        return deny("PMO-SCOPE-013",
                    "approval 'artifact' must be {}.".format(SCOPE_V1_POSIX))

    version = str(data.get("version")).strip() if data.get("version") is not None else ""
    if version != "1.0":
        return deny("PMO-SCOPE-013", "approval 'version' must be \"1.0\".")
    doc_ver = _clean(meta.get("scope version"))
    if doc_ver and parse_version_tuple(doc_ver) != (1, 0):
        return deny("PMO-SCOPE-013",
                    "approval requires Scope Version 1.0 (document declares "
                    "{}).".format(doc_ver))

    if (_clean(data.get("decision")) or "").upper() != "APPROVED":
        return deny("PMO-SCOPE-013", "approval 'decision' must be APPROVED.")
    if not _clean(data.get("approved_by")):
        return deny("PMO-SCOPE-013", "approval 'approved_by' must be non-empty.")
    if (_clean(data.get("approval_source")) or "").upper() != "PM_EXPLICIT":
        return deny("PMO-SCOPE-013",
                    "approval 'approval_source' must be PM_EXPLICIT.")
    if (_clean(data.get("client_approval")) or "").upper() != "CONFIRMED":
        return deny("PMO-SCOPE-013",
                    "approval 'client_approval' must be CONFIRMED.")
    if not _clean(data.get("client_approval_reference")):
        return deny("PMO-SCOPE-013",
                    "approval 'client_approval_reference' must be non-empty.")
    return None


# --------------------------------------------------------------------------- #
# Relevant git-action detection
# --------------------------------------------------------------------------- #

_WRAPPERS = {"env", "sudo", "command", "nice", "time", "xargs", "stdbuf"}
_GIT_GLOBAL_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


def _split_segments(command):
    segs, buf, quote, i, n = [], [], None, 0, len(command)
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
            segs.append("".join(buf))
            buf = []
            i += 2
            continue
        if ch in (";", "\n", "|", "&"):
            segs.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        segs.append("".join(buf))
    return [s.strip() for s in segs if s.strip()]


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
    i = idx + 1
    while i < len(tokens):
        tok = tokens[i]
        if tok in _GIT_GLOBAL_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        return tok, tokens[i + 1:]
    return None, []


def _run_git(cwd, args):
    try:
        return subprocess.run(["git", "-C", cwd] + list(args),
                              capture_output=True, text=True, timeout=15)
    except Exception:
        return None


def detect_relevant_git_action(command, root):
    """Return the list of scope-v*.md abspaths a `git add`/`git commit` in
    `command` would stage/commit, or None when the command is not relevant."""
    if not isinstance(command, str) or not command.strip():
        return None
    relevant = []
    for segment in _split_segments(command):
        sub, rest = _git_subcommand(_tokenize(segment))
        if sub not in ("add", "commit"):
            continue
        explicit = []
        for tok in rest:
            if tok.startswith("-"):
                continue
            norm = os.path.normpath(tok.strip("'\"")).replace(os.sep, "/")
            if SCOPE_FILE_RE.match(os.path.basename(norm)) and SCOPE_DIR_POSIX in norm:
                explicit.append(os.path.join(root, norm) if not os.path.isabs(norm)
                                else norm)
        if explicit:
            relevant.extend(explicit)
            continue
        broad = any(t in (".", "-A", "--all", "-u", "--update", "*", ":/")
                    for t in rest) or any(
            (not t.startswith("-")) and (t.startswith("docs") or t == "docs/pmo")
            for t in rest)
        has_all_commit = sub == "commit" and any(
            t in ("-a", "--all") or
            (t.startswith("-") and not t.startswith("--") and "a" in t)
            for t in rest)
        if broad or has_all_commit:
            res = _run_git(root, ["status", "--porcelain", "--", SCOPE_DIR_POSIX])
            if res is not None and res.returncode == 0:
                for ln in (res.stdout or "").splitlines():
                    p = ln[3:].strip().strip('"')
                    if SCOPE_FILE_RE.match(os.path.basename(p)):
                        relevant.append(os.path.join(root, p))
    if not relevant:
        return None
    # de-duplicate, keep order
    seen, out = set(), []
    for p in relevant:
        ap = os.path.abspath(p)
        if ap not in seen:
            seen.add(ap)
            out.append(ap)
    return out


# --------------------------------------------------------------------------- #
# Controlled (finalisation-gate) validation
# --------------------------------------------------------------------------- #

def full_scope_validation(content, meta, status, root, target_ver):
    """Full structural / workflow / evidence checks at a finalisation gate."""
    for check in (
        validate_prerequisite_intent(root),
        validate_project_identity(meta, load_config(root)),
        validate_status(status, at_gate=True),
        validate_required_sections(content),
        validate_document_control(meta, status),
        detect_task_identifiers(content),
        validate_open_items_governance(content),
        validate_version_history(content, meta, root),
        validate_intent_traceability(content, root),
        validate_uncontrolled_scope_expansion(content),
    ):
        if check is not None:
            return check

    if status == "APPROVED":
        if target_ver is not None and target_ver[0] < 1:
            return deny(
                "PMO-SCOPE-010",
                "APPROVED status is only valid on the baseline scope-v1.0.md "
                "(or a later 1.x / 2.0), not scope-v{}.{}.md.".format(*target_ver),
            )
        for check in (
            validate_scope_approval(meta, root),
            validate_scope_baseline_blockers(content),
        ):
            if check is not None:
                return check
    return None


# --------------------------------------------------------------------------- #
# Payload dispatch
# --------------------------------------------------------------------------- #

def process_write_edit(tool_name, tool_input, root):
    path = tool_input.get("file_path")
    if not is_scope_file_path(path, root):
        return None
    abspath = path if os.path.isabs(path) else os.path.join(root, path)
    target_ver = parse_scope_version_from_filename(path)
    existing = read_text(abspath)
    existing_meta = parse_scope_metadata(existing) if existing is not None else {}
    existing_status = existing_meta.get("status")
    versions = list_scope_versions(root)
    other_versions = [v for v in versions
                      if os.path.abspath(v[2]) != os.path.abspath(abspath)]

    # PMO-SCOPE-006 - never rewrite a historical or APPROVED version.
    blocked = detect_historical_scope_edit(target_ver, other_versions, existing_status)
    if blocked is not None:
        return blocked

    new_content = resulting_content(tool_name, tool_input, existing)
    if new_content is None:
        return None
    meta = parse_scope_metadata(new_content)
    status = _norm_status(meta.get("status"))

    # --- light checks (every edit, DRAFT included) --------------------------- #
    for check in (
        detect_reserved_ids(new_content),                     # 008
        validate_identifier_definitions(new_content),         # 009
        compare_scp_req_identity_across_versions(
            new_content, root, abspath),                       # 009 (reuse)
        validate_open_id_provenance(new_content, root),       # 015
        validate_status(status, at_gate=False),               # 004
        validate_version_filename_match(meta, target_ver),    # 005
        validate_project_identity(meta, load_config(root)),   # 002
    ):
        if check is not None:
            return check

    # PMO-SCOPE-010 - version progression, only when creating a new file.
    if existing is None:
        blocked = validate_version_progression(target_ver, other_versions,
                                               existing_status)
        if blocked is not None:
            return blocked

    finalizing = status in FINALIZING_STATUSES
    if not finalizing:
        return None  # progressive DRAFT authoring is allowed

    return full_scope_validation(new_content, meta, status, root, target_ver)


def process_bash(command, root):
    targets = detect_relevant_git_action(command, root)
    if not targets:
        return None
    for abspath in targets:
        content = read_text(abspath)
        if content is None:
            continue
        meta = parse_scope_metadata(content)
        status = _norm_status(meta.get("status"))
        target_ver = parse_scope_version_from_filename(abspath)

        for check in (
            detect_reserved_ids(content),
            validate_identifier_definitions(content),
            validate_open_id_provenance(content, root),
            validate_status(status, at_gate=True),
            validate_version_filename_match(meta, target_ver),
        ):
            if check is not None:
                return check

        blocked = full_scope_validation(content, meta, status, root, target_ver)
        if blocked is not None:
            return blocked
    return None


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
                "PMO-SCOPE-014",
                "unexpected internal error during controlled Scope validation "
                "({}). Blocking as a precaution.".format(exc),
            )

    if tool_name == "Bash":
        command = tool_input.get("command") or ""
        try:
            return process_bash(command, root)
        except Exception as exc:  # fail closed
            return deny(
                "PMO-SCOPE-014",
                "unexpected internal error validating a git operation on a "
                "Scope artifact ({}). Blocking as a precaution.".format(exc),
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
