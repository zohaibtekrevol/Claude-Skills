#!/usr/bin/env python3
"""PMO specs-governance-guard - deterministic governance for docs/pmo/specs/specs.md.

Fifth PMO PreToolUse governance hook. The *spec-generation skill* performs the
semantic transformation of the current PM-reviewed commercial / product Scope
into the canonical Dev/QA execution artifact:

    docs/pmo/specs/specs.md

This hook owns the mechanical, deterministic controls around that canonical
artifact. It is standard-library only and fails closed.

Behaviour
---------
* PreToolUse: reads the Claude Code payload from stdin (JSON) and acts on
  `Write` / `Edit` / `MultiEdit` whose `file_path` is the canonical Specs
  artifact, a forbidden non-canonical live Specs path, or
  `.pmo/project-config.yaml`; and on `Bash` `git add` / `git commit`
  invocations that stage the canonical Specs artifact. Unrelated operations
  are allowed silently.
* Progressive authoring of docs/pmo/specs/specs.md is permitted: Write/Edit of
  the canonical file runs only lightweight always-on checks (forbidden path,
  duplicate/invalid identifier syntax, project identity when present, OPEN
  provenance when deterministically available, Execution-Authorized value and
  false->true transition). Full schema / traceability / version / history
  validation runs at controlled gates (git add / git commit of specs.md).
* A blocked operation emits the standard PreToolUse deny response:
    {"hookSpecificOutput": {"hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": "<PMO-SPEC-0XX>: <reason>"}}
* Every validator is importable and callable directly for regression testing.
  This module does NOT register itself; wiring into .claude/settings.json is a
  separate, deliberate step.

Error IDs
---------
PMO-SPEC-001  SOURCE_SCOPE_NOT_READY          - no sufficiently PM-reviewed Scope.
PMO-SPEC-002  NON_CANONICAL_SPEC_PATH         - live Specs artifact is not
                                               docs/pmo/specs/specs.md.
PMO-SPEC-003  SPEC_SCHEMA_INVALID             - Document Control / required
                                               sections incomplete at a gate.
PMO-SPEC-004  SCOPE_TRACEABILITY_INCOMPLETE   - an active SCP-REQ is missing a
                                               disposition in the matrix.
PMO-SPEC-005  DUPLICATE_REQUIREMENT_ID        - duplicate / malformed FR / NFR /
                                               BR / SPEC-OPEN definition, or an
                                               orphan Business Rule.
PMO-SPEC-006  REQUIREMENT_ID_REUSE            - an existing / retired FR / NFR id
                                               reused for a different identity.
PMO-SPEC-007  INVALID_SPEC_VERSION            - illegal logical version.
PMO-SPEC-008  INVALID_SPEC_STATUS            - bad status, or ACTIVE without an
                                               approved Scope baseline.
PMO-SPEC-009  EXECUTION_AUTHORIZATION_INVALID - bad value or an unauthorised
                                               false -> true transition.
PMO-SPEC-010  FR_STRUCTURE_INVALID            - an active FR is missing mandatory
                                               structure / acceptance criteria.
PMO-SPEC-011  NFR_STRUCTURE_INVALID           - an active NFR is missing
                                               mandatory structure / criteria.
PMO-SPEC-012  OPEN_ID_PROVENANCE_MISMATCH     - an upstream OPEN item was
                                               renamed / re-provenanced.
PMO-SPEC-013  CHANGE_HISTORY_INVALID          - missing / malformed
                                               Specification Change History.
PMO-SPEC-014  CHANGE_PROVENANCE_INVALID       - bad / unbacked Change Source.
PMO-SPEC-015  UNAPPROVED_SCOPE_EXPANSION      - an active FR / NFR has no Scope
                                               trace and no approved change
                                               origin.
PMO-SPEC-016  PROJECT_IDENTITY_MISMATCH       - identity != project-config.
PMO-SPEC-017  SOURCE_VERSION_MISMATCH         - Intent / Scope version metadata
                                               is inaccurate.
PMO-SPEC-018  PMO_STATE_MUTATION_INVALID      - spec generation changed protected
                                               Scope / Intent / approval state.
PMO-SPEC-019  PUBLISH_STATE_INVALID           - publishing attempted / claimed
                                               without a verified repository.
PMO-SPEC-020  SPEC_GUARD_INTERNAL_ERROR       - unexpected exception; fail closed.
PMO-SPEC-021  INTENT_NOT_READY               - (NEW lifecycle, no Scope
                                               artifact exists) the canonical
                                               Intent is absent, not
                                               VALIDATED, lacks a matching PM
                                               approval record, or its
                                               project identity does not
                                               match project-config.
PMO-SPEC-022  QA_REGISTER_NOT_READY          - (NEW lifecycle) no canonical
                                               Q&A register, or it is
                                               structurally invalid.
PMO-SPEC-023  QA_BLOCKING_ITEM_OPEN          - (NEW lifecycle) an unresolved
                                               Blocking Q&A record remains.

A project with at least one Scope artifact under docs/pmo/scope/ always uses
the LEGACY entry gate (PMO-SPEC-001) and SCP-REQ-based traceability
(PMO-SPEC-004/015), unchanged. A project with none uses the NEW entry gate
(PMO-SPEC-021/022/023) and Intent/Q&A-based traceability. The framework
never requires a new project to manufacture an empty Scope directory merely
for compatibility; the path is selected deterministically by artifact
presence, never by a project-config flag.

Python 3, standard library only.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

# Imported under its own namespace on purpose (see qa_register_core.py's own
# module docstring for why `iac.*` / `qac.*`-style namespacing is used
# throughout these guards instead of bare imports). The NEW-lifecycle
# Specs-entry gate (PMO-SPEC-021/022/023) delegates entirely to this shared
# module - this hook never re-implements Q&A validation.
import qa_register_core as qac  # noqa: E402
import change_request_incorporation_core as crcore  # noqa: E402


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

CONFIG_RELPATH = os.path.join(".pmo", "project-config.yaml")
INTENT_RELPATH = "docs/pmo/intent/intent.md"
SCOPE_DIR_POSIX = "docs/pmo/scope"
SPEC_DIR_POSIX = "docs/pmo/specs"
CANONICAL_SPEC_POSIX = "docs/pmo/specs/specs.md"
FEEDBACK_DIRS = ("docs/pmo/feedback",)
CR_DIRS = ("docs/pmo/change-requests", "docs/pmo/cr")

VALID_COVERAGE = {"COVERED", "PARTIALLY_COVERED", "OPEN", "DEFERRED", "EXCLUDED"}
VALID_FR_STATUS = {"ACTIVE", "DEFERRED", "RETIRED"}
VALID_SPEC_STATUS = {"PROVISIONAL", "ACTIVE"}
NOT_APPLICABLE = {"N_A", "NA", "NONE", "TBD", "TBC", ""}

# A non-canonical *live* Specs artifact the normal workflow must not create.
FORBIDDEN_SPEC_BASENAME_RE = re.compile(
    r"^(?:"
    r"specs?[-_]v\d+(?:\.\d+)*\.md"
    r"|specs?[-_](?:latest|final|current|baseline|draft|new|old)\.md"
    r"|(?:latest|final|current|previous|old|new)[-_]specs?\.md"
    r"|specs?\.v\d+(?:\.\d+)*\.md"
    r"|specs?-\d+(?:\.\d+)*\.md"
    r")$",
    re.IGNORECASE,
)

REQUIRED_DOC_CONTROL = (
    "Project", "Client", "Project ID", "Spec Version", "Spec Status",
    "Intent Version", "Generated From", "Last Updated",
    "Execution Authorized", "Repository",
)
# "Scope Version" is required only on the LEGACY (Scope-based) path - see
# validate_required_sections(legacy_scope=...). The NEW (Intent + Q&A) path
# has no Scope artifact to version.

# (human name, heading regex, conditional?) - conditional sections are required
# only when the corresponding content is present.
REQUIRED_SECTIONS = (
    ("Functional Requirements", r"functional\s+requirements", False),
    ("Non-Functional Requirements", r"non[-\s]functional\s+requirements", False),
    ("Business Rules", r"business\s+rules", True),
    ("System States", r"system\s+states", True),
    ("Data Requirements", r"data\s+requirements", False),
    ("Integrations", r"integrations?", False),
    ("Open Questions", r"open\s+questions", False),
    ("Scope/Intent -> Specs Traceability",
     r"(?:scope|intent|requirements?)\s*(?:→|-+>|to)\s*specs?\s+traceability",
     False),
    ("Specification Change History", r"specification\s+change\s+history", False),
    ("Validation Summary", r"validation\s+summary", False),
)

# Matches "Scope -> Specs Traceability" (LEGACY) as well as "Intent -> Specs
# Traceability" / "Requirements -> Specs Traceability" (NEW lifecycle).
TRACE_HEADING_RE = r"(?:scope|intent|requirements?)\s*(?:→|-+>|to)\s*specs?\s+traceability"
HISTORY_HEADING_RE = r"specification\s+change\s+history"
OPEN_HEADING_RE = r"open\s+questions"

# --------------------------------------------------------------------------- #
# Functional Requirement field POLICY (PMO-SPEC-010)
#
# CORE_REQUIRED        every active FR carries a substantive value.
# GOVERNANCE_DERIVED   stamped from lifecycle/governance state (presence here;
#                      value provenance is validated by PMO-SPEC-014).
# CONDITIONALLY_REQUIRED  exactly one explicit applicability state:
#                      DEFINED (a substantive value) | NOT_APPLICABLE: <reason>
#                      | NOT_SPECIFIED | PENDING_DECISION: <QST-###/ASM-###>.
# OPTIONAL             absence is valid; preserved when present.
#
# Rationale: the framework must never force fabricated detail merely to
# satisfy a schema slot; only material unresolved decisions become Q&A.
# --------------------------------------------------------------------------- #
FR_CORE_LABELS = (
    "ID", "Title", "Module", "Actor(s)", "Requirement", "Source Scope",
    "Acceptance Criteria",
)
FR_DERIVED_LABELS = (
    "Introduced In", "Last Modified In", "Change Source", "Status",
)
FR_CONDITIONAL_LABELS = (
    "Trigger", "Preconditions", "Inputs", "Outputs", "Validation Rules",
    "Alternate / Exception Behavior", "Permissions", "Business Rules",
    "Dependencies",
)
FR_OPTIONAL_LABELS = (
    "Primary Behavior", "Priority", "Integration References",
    "OPEN References", "Constraints", "State Transitions",
)
# Kept for reference/back-compat: every label that used to be enforced.
FR_ACTIVE_LABELS = FR_CORE_LABELS[:-1] + FR_DERIVED_LABELS[:-1] \
    + FR_CONDITIONAL_LABELS + ("Acceptance Criteria", "Status")
APPLICABILITY_STATES = ("DEFINED", "NOT_APPLICABLE", "NOT_SPECIFIED",
                        "PENDING_DECISION")
FR_HISTORICAL_LABELS = (
    "Source Scope", "Introduced In", "Last Modified In", "Change Source", "Status",
)
# "Source Scope" is the mandatory upstream-traceability field on every FR/NFR
# on BOTH paths. On the LEGACY path it carries SCP-REQ-* ids; on the NEW
# (no-Scope) path the same mandatory field is written as "Source Requirement"
# and carries INT-REQ-* / QST-* / ASM-* ids instead - a field-label alias,
# not a schema fork. See validate_fr_structure / validate_reverse_traceability.
FR_SOURCE_ALIASES = ("Source Scope", "Source Requirement")
NFR_ACTIVE_LABELS = (
    "ID", "Title", "Category", "Requirement", "Introduced In", "Last Modified In",
    "Change Source", "Status",
)
NFR_SOURCE_ALIASES = (
    "Source Scope", "Source Requirement", "Source", "Evidence", "Source / Evidence",
)
NFR_CRITERIA_ALIASES = (
    "Acceptance Criteria", "Verification", "Verification Criteria",
    "Acceptance / Verification Criteria", "Acceptance / Verification",
)

PERMITTED_CHANGE_SOURCE_RE = re.compile(
    r"^(?:INITIAL_SCOPE|INITIAL_INTENT|SCOPE[-_]RECONCILIATION|PM[-_]DECISION"
    r"|FDB-\d+|FB-\d{4}-\d{3}-\d{3}|CR-\d+|QST-\d+|ASM-\d+"
    r"|SCOPE\s*V?\d+(?:\.\d+)*(?:\s*\([^)]*\))?)$",
    re.IGNORECASE,
)

OPEN_PREFIX_EXPECT = {
    "OPEN": "INTENT",
    "SCP-OPEN": "SCOPE",
    "BRAND-OPEN": "BRAND",
    "SPEC-OPEN": "SPEC",
}

# Protected project-config paths a Specs generation run must never move.
PROTECTED_STATE_PATHS = (
    ("workflow", "current_stage"),
    ("workflow", "scope", "approved"),
    ("workflow", "scope", "pm_review"),
    ("workflow", "scope", "client_review"),
    ("workflow", "intent", "approved"),
    ("artifacts", "scope", "latest_version"),
    ("artifacts", "scope", "approved_version"),
    ("artifacts", "scope", "status"),
    ("artifacts", "intent", "latest_version"),
    ("artifacts", "intent", "status"),
)

# Scope workflow stages that are too early for any Specs generation.
TOO_EARLY_STAGES = {
    "INTENT_VALIDATION", "INTENT_READY", "INTENT_DRAFT", "INTENT_IN_PROGRESS",
    "SCOPE_GENERATION", "SCOPE_DRAFTING", "SCOPE_IN_PROGRESS",
    "REQUIREMENT_GATHERING", "SCOPE_NOT_STARTED",
}
SCOPE_STATUS_OK = {
    "DRAFT_CLIENT_REVIEW", "CLIENT_FEEDBACK_RECEIVED", "PM_REVIEWED",
    "APPROVED", "BASELINED", "CLIENT_APPROVED",
}


# --------------------------------------------------------------------------- #
# Decision plumbing
# --------------------------------------------------------------------------- #

class Decision(object):
    __slots__ = ("code", "message")

    def __init__(self, code, message):
        self.code = code
        self.message = message

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Decision({!r}, {!r})".format(self.code, self.message)


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
# Minimal YAML subset parser (stdlib only) - ported from the sibling guards
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


def parse_project_config_file(root):
    text = read_text(os.path.join(root, CONFIG_RELPATH))
    if text is None:
        return None
    try:
        data = parse_project_config(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _abspath(p, root):
    p = (p or "").strip().strip('"').strip("'")
    if not p:
        return ""
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(root, p))


def _relpath(p, root):
    ap = _abspath(p, root)
    try:
        return os.path.relpath(ap, root).replace(os.sep, "/")
    except Exception:
        return (p or "").replace(os.sep, "/")


# --------------------------------------------------------------------------- #
# Small scalar helpers
# --------------------------------------------------------------------------- #

def _clean(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return value.strip() if isinstance(value, str) and value.strip() else None


def norm_token(value):
    if value is None:
        return None
    if isinstance(value, bool):
        value = "true" if value else "false"
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(value).strip().upper()).strip("_")
    return s or None


def norm_ver(value):
    m = re.match(r"^\s*[vV]?(\d+)\.(\d+)\s*$", str(value or ""))
    if not m:
        return None
    return "{}.{}".format(int(m.group(1)), int(m.group(2)))


def parse_spec_version(meta):
    """(major, minor) tuple from the Spec Version metadata, or None."""
    nv = norm_ver((meta or {}).get("spec version"))
    if not nv:
        return None
    a, b = nv.split(".")
    return (int(a), int(b))


def ver_str(v):
    return "{}.{}".format(v[0], v[1]) if v else "<none>"


def parse_ver(value):
    m = re.match(r"^\s*[vV]?(\d+)\.(\d+)", str(value or "").strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def _dig(data, path):
    cur = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


# --------------------------------------------------------------------------- #
# Markdown field / section / table helpers
# --------------------------------------------------------------------------- #

def _field(text, label):
    """First `Label: value` (or `**Label:** value`, `| Label | value |`) in text.

    Whitespace on the value side is horizontal-only so an empty field never
    borrows the next line's content."""
    core = r"[ \t]+".join(re.escape(p) for p in label.split())
    pattern = re.compile(
        r"^[ \t>*\-+|]*\**[ \t]*" + core
        + r"[ \t]*\**[ \t]*[:|][ \t]*\**[ \t]*(.+?)[ \t]*\**[ \t]*\|?[ \t]*$",
        re.IGNORECASE | re.MULTILINE,
    )
    m = pattern.search(text or "")
    if not m:
        return None
    value = m.group(1).strip().strip("*").strip().strip("`").strip()
    return value or None


def _heading_lines(text):
    return [m.group(2).strip()
            for m in re.finditer(r"(?m)^(#{1,6})\s+(.*\S)\s*$", text or "")]


def _has_heading(text, rx):
    cre = re.compile(rx, re.IGNORECASE)
    return any(cre.search(h) for h in _heading_lines(text))


def _table_after(text, heading_rx):
    """(header_cells, [row_cells, ...]) for the first pipe table following a
    heading whose text matches heading_rx; None when absent."""
    lines = (text or "").split("\n")
    cre = re.compile(heading_rx, re.IGNORECASE)
    start = None
    for i, line in enumerate(lines):
        hm = re.match(r"^#{1,6}\s+(.*\S)\s*$", line)
        if hm and cre.search(hm.group(1)):
            start = i + 1
            break
    if start is None:
        return None
    i = start
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("|"):
            break
        if re.match(r"^#{1,6}\s", lines[i]):
            return None
        i += 1
    rows = []
    while i < len(lines) and lines[i].strip().startswith("|"):
        raw = lines[i].strip()
        if re.match(r"^\|?[\s:|\-]+\|?$", raw) and "-" in raw:
            i += 1
            continue
        cells = [c.strip() for c in raw.strip().strip("|").split("|")]
        rows.append(cells)
        i += 1
    if not rows:
        return None
    return rows[0], rows[1:]


def _col_index(header, *names):
    low = [h.strip().lower() for h in header]
    for name in names:
        if name.lower() in low:
            return low.index(name.lower())
    for idx, h in enumerate(low):
        for name in names:
            if name.lower() in h:
                return idx
    return None


# --------------------------------------------------------------------------- #
# Metadata / scope / intent
# --------------------------------------------------------------------------- #

def parse_spec_metadata(text):
    meta = {}
    for label in ("Project", "Client", "Project ID", "Project Name",
                  "Spec Version", "Spec Status", "Status", "Intent Version",
                  "Scope Version", "Generated From", "Last Updated",
                  "Execution Authorized", "Repository"):
        v = _field(text, label)
        if v is not None:
            meta[label.lower()] = v
    if "project" not in meta and "project name" in meta:
        meta["project"] = meta["project name"]
    if "spec status" not in meta and "status" in meta:
        meta["spec status"] = meta["status"]
    return meta


def all_scope_artifacts(root):
    """[(path, (maj, min)), ...] for docs/pmo/scope/scope-vX.Y.md, sorted asc."""
    out = []
    d = os.path.join(root, SCOPE_DIR_POSIX)
    try:
        names = os.listdir(d)
    except Exception:
        return out
    for name in names:
        m = re.match(r"^scope-v(\d+)\.(\d+)\.md$", name)
        if m:
            out.append((os.path.join(d, name),
                        (int(m.group(1)), int(m.group(2)))))
    out.sort(key=lambda t: t[1])
    return out


def locate_current_scope(root):
    """(path, (maj, min)) of the highest-versioned Scope artifact, or (None, None)."""
    arts = all_scope_artifacts(root)
    if not arts:
        return None, None
    return arts[-1]


def read_scope_requirements(scope_text):
    """Set of active SCP-REQ identifiers defined in a Scope artifact."""
    ids = set(re.findall(r"(?m)^#{2,6}\s+(SCP-REQ-\d+)\b", scope_text or ""))
    ids |= set(re.findall(r"(?m)^\|\s*(SCP-REQ-\d+)\s*\|", scope_text or ""))
    ids |= set(re.findall(r"(?m)^[-*]\s+\*{0,2}(SCP-REQ-\d+)\b", scope_text or ""))
    return ids


def _scope_is_approved(cfg):
    if _dig(cfg, ("workflow", "scope", "approved")) is True:
        return True
    if _clean(_dig(cfg, ("artifacts", "scope", "approved_version"))):
        return True
    return False


# --------------------------------------------------------------------------- #
# PMO-SPEC-001  source Scope readiness
# --------------------------------------------------------------------------- #

def validate_scope_readiness(root):
    scope_path, scope_ver = locate_current_scope(root)
    if not scope_path:
        return deny("PMO-SPEC-001",
                    "no current Scope artifact under docs/pmo/scope/; initial "
                    "Specs require a PM-reviewed Scope draft.")
    if scope_ver < (0, 1):
        return deny("PMO-SPEC-001",
                    "the current Scope version {} is below 0.1.".format(
                        ver_str(scope_ver)))
    cfg = parse_project_config_file(root) or {}
    pm_review = norm_token(_dig(cfg, ("workflow", "scope", "pm_review")))
    if pm_review != "COMPLETE":
        return deny(
            "PMO-SPEC-001",
            "workflow.scope.pm_review is '{}', not COMPLETE - Specs may be "
            "generated only after the first PM semantic review of the "
            "Scope.".format(pm_review or "<unset>"),
        )
    stage = norm_token(_dig(cfg, ("workflow", "current_stage")))
    if stage in TOO_EARLY_STAGES:
        return deny(
            "PMO-SPEC-001",
            "workflow.current_stage '{}' is earlier than a Scope that is ready "
            "for client review.".format(stage),
        )
    scope_text = read_text(scope_path) or ""
    status = norm_token(_field(scope_text, "Status")
                        or _field(scope_text, "Scope Status"))
    if status and status not in SCOPE_STATUS_OK:
        return deny(
            "PMO-SPEC-001",
            "the current Scope Status '{}' does not authorise Specs "
            "generation.".format(status),
        )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-021/022/023  NEW (no-Scope) lifecycle Specs-entry readiness
# --------------------------------------------------------------------------- #

def has_legacy_scope(root):
    """True when the project has at least one docs/pmo/scope/scope-vX.Y.md
    artifact - the sole, deterministic signal that selects the LEGACY entry
    gate/traceability model over the NEW (Intent + Q&A) one. Never a
    project-config flag; never inferred from workflow.current_stage."""
    return bool(all_scope_artifacts(root))


def read_intent_requirements(root):
    """Set of active INT-REQ ids defined as table rows in intent.md - the
    NEW-lifecycle traceability anchor, identical in shape to
    scope-version-guard.py's same-named helper for Scope."""
    text = read_text(os.path.join(root, INTENT_RELPATH)) or ""
    return set(re.findall(r"(?m)^\|\s*(INT-REQ-\d+)\s*\|", text))


def validate_new_lifecycle_readiness(root):
    """The NEW (no-Scope) lifecycle Specs-entry gate: canonical Intent
    VALIDATED + matching PM approval + identity match, a structurally valid
    canonical Q&A register, and no unresolved Blocking Q&A record. Reads the
    canonical Intent, approval record and Q&A register directly - never a
    project-config boolean - by delegating entirely to
    `qa_register_core.validate_new_path_readiness`; this hook never
    re-implements Q&A validation."""
    result = qac.validate_new_path_readiness(root)
    if result is None:
        return None
    kind, message = result
    code = {
        "INTENT_NOT_READY": "PMO-SPEC-021",
        "QA_REGISTER_NOT_READY": "PMO-SPEC-022",
        "QA_BLOCKING_ITEM_OPEN": "PMO-SPEC-023",
    }.get(kind, "PMO-SPEC-021")
    return deny(code, message)


# --------------------------------------------------------------------------- #
# PMO-SPEC-002  canonical path
# --------------------------------------------------------------------------- #

def validate_canonical_path(rel_posix):
    """Given a repo-relative POSIX path targeted by a Write/Edit, return a
    Decision when it is a non-canonical *live* Specs artifact."""
    rel = (rel_posix or "").lstrip("./")
    if not rel.startswith(SPEC_DIR_POSIX + "/"):
        return None
    base = rel.split("/")[-1]
    if base == "specs.md":
        return None
    if FORBIDDEN_SPEC_BASENAME_RE.match(base):
        return deny(
            "PMO-SPEC-002",
            "the live execution Specs artifact must be {} - '{}' is a "
            "non-canonical versioned/aliased Specs file. Logical history lives "
            "in the Spec Version metadata, the Specification Change History and "
            "git/Bitbucket history.".format(CANONICAL_SPEC_POSIX, rel),
        )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-003  schema / required sections
# --------------------------------------------------------------------------- #

def validate_required_sections(spec_text, meta=None, legacy_scope=True):
    meta = meta if meta is not None else parse_spec_metadata(spec_text)
    missing_dc = [lbl for lbl in REQUIRED_DOC_CONTROL
                  if _field(spec_text, lbl) in (None, "")]
    if legacy_scope and _field(spec_text, "Scope Version") in (None, ""):
        missing_dc.append("Scope Version")
    if missing_dc:
        return deny(
            "PMO-SPEC-003",
            "Specification Document Control is missing field(s): {}.".format(
                ", ".join(missing_dc)),
        )
    has_br = bool(re.search(r"(?m)^#{2,6}\s+BR-\d{3,}\b", spec_text or "")) \
        or bool(re.search(r"(?m)^\|\s*BR-\d{3,}\s*\|", spec_text or ""))
    has_states = bool(re.search(r"(?i)\bstate\s+(?:model|machine|lifecycle)\b",
                                spec_text or ""))
    for name, rx, conditional in REQUIRED_SECTIONS:
        if _has_heading(spec_text, rx):
            continue
        if conditional and name == "Business Rules" and not has_br:
            continue
        if conditional and name == "System States" and not has_states:
            continue
        return deny(
            "PMO-SPEC-003",
            "the Specification is missing the required '{}' section.".format(name),
        )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-004  Scope/Intent -> Specs traceability (forward)
# --------------------------------------------------------------------------- #

def validate_requirement_traceability(req_ids, spec_text, id_regex=r"SCP-REQ-\d+",
                                      req_label="Scope requirement",
                                      matrix_label="Scope -> Specs"):
    """Generalized forward-traceability check. LEGACY path calls this with
    SCP-REQ ids (`validate_scope_traceability`); NEW (no-Scope) lifecycle
    calls it with INT-REQ ids (`validate_intent_traceability_specs`). Same
    rule either way: every active upstream requirement must appear, exactly
    once, with a valid coverage disposition."""
    tbl = _table_after(spec_text, TRACE_HEADING_RE)
    if tbl is None:
        return deny(
            "PMO-SPEC-004",
            "no {} Traceability matrix found; every active {} must have a "
            "disposition.".format(matrix_label, req_label),
        )
    header, rows = tbl
    cov_idx = _col_index(header, "coverage", "disposition", "status")
    seen = {}
    bad_cov = []
    id_re = re.compile(id_regex)
    for row in rows:
        if not row:
            continue
        for cid in id_re.findall(row[0]):
            seen[cid] = seen.get(cid, 0) + 1
        if cov_idx is not None and cov_idx < len(row):
            cov = norm_token(row[cov_idx])
            if cov and cov not in VALID_COVERAGE:
                bad_cov.append(row[cov_idx])
    missing = sorted(set(req_ids) - set(seen))
    dupes = sorted(k for k, v in seen.items() if v > 1)
    if missing:
        return deny(
            "PMO-SPEC-004",
            "active {}(s) absent from the {} Traceability matrix: {}.".format(
                req_label, matrix_label, ", ".join(missing)),
        )
    if dupes:
        return deny(
            "PMO-SPEC-004",
            "{}(s) appear in more than one traceability row (exactly one "
            "disposition each): {}.".format(req_label, ", ".join(dupes)),
        )
    if bad_cov:
        return deny(
            "PMO-SPEC-004",
            "invalid coverage disposition(s) {} - allowed: {}.".format(
                ", ".join(sorted(set(bad_cov))), ", ".join(sorted(VALID_COVERAGE))),
        )
    return None


def validate_scope_traceability(scope_req_ids, spec_text):
    """LEGACY path - unchanged behavior, SCP-REQ ids."""
    return validate_requirement_traceability(
        scope_req_ids, spec_text, id_regex=r"SCP-REQ-\d+",
        req_label="Scope requirement", matrix_label="Scope -> Specs")


def validate_intent_traceability_specs(intent_req_ids, spec_text):
    """NEW (no-Scope) lifecycle path - INT-REQ ids, no Scope artifact
    required or consulted."""
    return validate_requirement_traceability(
        intent_req_ids, spec_text, id_regex=r"INT-REQ-\d+",
        req_label="Intent requirement", matrix_label="Intent -> Specs")


# --------------------------------------------------------------------------- #
# PMO-SPEC-005  identifier uniqueness / syntax / orphan Business Rules
# --------------------------------------------------------------------------- #

def _open_prefix(pid):
    m = re.match(r"^(SPEC-OPEN|SCP-OPEN|BRAND-OPEN|OPEN)-\d+$",
                 (pid or "").strip(), re.IGNORECASE)
    return m.group(1).upper() if m else None


def parse_open_items(spec_text):
    """[{id, provenance, origin, question}] from the Open Questions table."""
    tbl = _table_after(spec_text, OPEN_HEADING_RE)
    if tbl is None:
        return []
    header, rows = tbl
    id_idx = _col_index(header, "id", "identifier")
    prov_idx = _col_index(header, "provenance", "source type", "origin type",
                          "type", "class")
    origin_idx = _col_index(header, "origin", "derived from", "upstream",
                            "source", "traces to")
    q_idx = _col_index(header, "question", "summary", "detail")
    out = []
    for row in rows:
        if id_idx is None or id_idx >= len(row):
            continue
        pid = row[id_idx].strip().strip("`*")
        if not _open_prefix(pid):
            continue
        out.append({
            "id": pid,
            "provenance": row[prov_idx].strip() if prov_idx is not None
            and prov_idx < len(row) else "",
            "origin": row[origin_idx].strip() if origin_idx is not None
            and origin_idx < len(row) else "",
            "question": row[q_idx].strip() if q_idx is not None
            and q_idx < len(row) else "",
        })
    return out


def _definition_counts(spec_text):
    counts = {}
    for m in re.finditer(r"(?m)^#{2,6}\s+((?:FR|NFR|BR)-\d{3,})\b", spec_text or ""):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    for m in re.finditer(r"(?m)^\|\s*((?:FR|NFR|BR)-\d{3,})\s*\|", spec_text or ""):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return counts


def validate_identifier_uniqueness(spec_text):
    # malformed identifier syntax on a definition heading
    bad = re.findall(
        r"(?m)^#{2,6}\s+((?:FR|NFR|BR)-(?!\d{3,}\b)[0-9A-Za-z.\-]+)\b",
        spec_text or "",
    )
    if bad:
        return deny(
            "PMO-SPEC-005",
            "malformed requirement identifier(s) on definition heading(s): {} "
            "(expected FR-/NFR-/BR- followed by >= 3 digits).".format(
                ", ".join(sorted(set(bad)))),
        )
    counts = _definition_counts(spec_text)
    dupes = sorted(k for k, v in counts.items() if v > 1)
    if dupes:
        return deny(
            "PMO-SPEC-005",
            "duplicate requirement definition(s): {} - each FR/NFR/BR may be "
            "defined once (references may repeat).".format(", ".join(dupes)),
        )
    # SPEC-OPEN uniqueness from the Open Questions table
    so_seen = {}
    for it in parse_open_items(spec_text):
        if _open_prefix(it["id"]) == "SPEC-OPEN":
            so_seen[it["id"]] = so_seen.get(it["id"], 0) + 1
    so_dupes = sorted(k for k, v in so_seen.items() if v > 1)
    if so_dupes:
        return deny(
            "PMO-SPEC-005",
            "duplicate SPEC-OPEN definition(s): {}.".format(", ".join(so_dupes)),
        )
    return None


def parse_business_rules(spec_text):
    """[(id, body_text)] - heading-defined or Business-Rules-table-defined."""
    out = []
    for bid, body in _split_headed_blocks(spec_text, r"BR-\d{3,}").items():
        out.append((bid, body))
    tbl = _table_after(spec_text, r"business\s+rules")
    if tbl is not None:
        header, rows = tbl
        id_idx = _col_index(header, "id", "br", "rule id")
        if id_idx is None:
            id_idx = 0
        for row in rows:
            if id_idx < len(row):
                m = re.match(r"^(BR-\d{3,})$", row[id_idx].strip().strip("`*"))
                if m:
                    out.append((m.group(1), " | ".join(row)))
    return out


def validate_business_rules(brs):
    seen = set()
    for bid, body in brs:
        if bid in seen:
            return deny("PMO-SPEC-005",
                        "duplicate Business Rule definition: {}.".format(bid))
        seen.add(bid)
        if not re.search(r"\b(?:FR|NFR)-\d{3,}\b", body or ""):
            return deny(
                "PMO-SPEC-005",
                "orphan Business Rule {} - every BR must reference at least one "
                "FR-XXX or NFR-XXX.".format(bid),
            )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-006  retired / existing identifier reuse
# --------------------------------------------------------------------------- #

def _norm_text(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def compare_requirement_identity(prev_defs, new_defs):
    """prev_defs / new_defs: {id: {"status", "source_scope"(set), "title",
    "requirement"}}. Deterministically reject reuse of an existing / retired id
    for a materially different requirement identity."""
    for rid, nf in (new_defs or {}).items():
        pf = (prev_defs or {}).get(rid)
        if not pf:
            continue
        p_scope = set(pf.get("source_scope") or ())
        n_scope = set(nf.get("source_scope") or ())
        p_status = norm_token(pf.get("status"))
        n_status = norm_token(nf.get("status"))
        if p_status == "RETIRED" and n_status != "RETIRED":
            if p_scope and n_scope and not (p_scope & n_scope):
                return deny(
                    "PMO-SPEC-006",
                    "{} was RETIRED and is reused for a different requirement "
                    "identity (Source Scope {} -> {}); retired identifiers are "
                    "never reused.".format(
                        rid, sorted(p_scope), sorted(n_scope)),
                )
        if p_status != "RETIRED" and n_status != "RETIRED":
            if (p_scope and n_scope and not (p_scope & n_scope)
                    and _norm_text(pf.get("title")) != _norm_text(nf.get("title"))
                    and _norm_text(pf.get("requirement"))
                    != _norm_text(nf.get("requirement"))):
                return deny(
                    "PMO-SPEC-006",
                    "{} is reused for a different requirement identity "
                    "(disjoint Source Scope and changed title/requirement); "
                    "identifiers are permanent.".format(rid),
                )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-007  logical version progression
# --------------------------------------------------------------------------- #

def validate_spec_version(cur, history_versions, scope_approved):
    if cur is None:
        return deny("PMO-SPEC-007", "Spec Version metadata missing / unparseable.")
    if cur < (0, 1):
        return deny("PMO-SPEC-007",
                    "Spec Version {} is invalid (minimum 0.1).".format(ver_str(cur)))
    prior = sorted({v for v in (history_versions or []) if v and v < cur})
    prev = prior[-1] if prior else None
    if prev is None:
        if cur != (0, 1):
            return deny(
                "PMO-SPEC-007",
                "the initial Spec Version must be 0.1, not {}.".format(ver_str(cur)),
            )
        return None
    # same major, minor + 1
    if cur[0] == prev[0] and cur[1] == prev[1] + 1:
        return None
    # pre-baseline 0.x -> 1.0 promotion, only with an approved Scope baseline
    if prev[0] == 0 and cur == (1, 0):
        if not scope_approved:
            return deny(
                "PMO-SPEC-007",
                "promotion to Spec Version 1.0 requires an approved / baselined "
                "commercial Scope.",
            )
        return None
    return deny(
        "PMO-SPEC-007",
        "invalid Spec Version progression {} -> {} (allowed: minor+1, or "
        "0.x -> 1.0 on Scope baseline).".format(ver_str(prev), ver_str(cur)),
    )


# --------------------------------------------------------------------------- #
# PMO-SPEC-008  status
# --------------------------------------------------------------------------- #

def validate_spec_status(meta, scope_approved):
    st = norm_token((meta or {}).get("spec status"))
    if st not in VALID_SPEC_STATUS:
        return deny(
            "PMO-SPEC-008",
            "Spec Status '{}' is invalid - must be PROVISIONAL or ACTIVE.".format(
                (meta or {}).get("spec status")),
        )
    if st == "ACTIVE" and not scope_approved:
        return deny(
            "PMO-SPEC-008",
            "Spec Status ACTIVE requires an approved / baselined commercial "
            "Scope; ACTIVE must not be inferred from publication.",
        )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-009  execution authorization independence
# --------------------------------------------------------------------------- #

def _has_pm_execution_evidence(text):
    if not text:
        return False
    if re.search(r"(?is)pm[-_ ]?decision.{0,160}execution", text):
        return True
    if re.search(r"(?is)execution.{0,160}pm[-_ ]?decision", text):
        return True
    if re.search(r"(?im)^[ \t>*\-+|]*\**\s*Execution Authoriz(?:ation|ed) "
                 r"Evidence\s*[:|]\s*\S", text):
        return True
    return False


def validate_execution_authorization(meta, spec_text="", spec_version=None):
    raw = (meta or {}).get("execution authorized")
    if raw is None:
        return deny("PMO-SPEC-009",
                    "Document Control is missing 'Execution Authorized'.")
    tok = norm_token(raw)
    if tok not in ("TRUE", "FALSE"):
        return deny(
            "PMO-SPEC-009",
            "Execution Authorized must be literally true or false, not "
            "'{}'.".format(raw),
        )
    if spec_version == (0, 1) and tok == "TRUE" and not _has_pm_execution_evidence(
            spec_text):
        return deny(
            "PMO-SPEC-009",
            "initial PROVISIONAL Specs must default Execution Authorized to "
            "false; true requires explicit PM authorization evidence and must "
            "not be inferred from generation or publication.",
        )
    return None


def validate_execution_authorization_transition(old_text, new_text,
                                                evidence_text=None):
    was_false = bool(re.search(
        r"(?i)execution\s+authoriz(?:ed|ation)?\s*[:|]\s*\**\s*false",
        old_text or ""))
    now_true = bool(re.search(
        r"(?i)execution\s+authoriz(?:ed|ation)?\s*[:|]\s*\**\s*true",
        new_text or ""))
    if was_false and now_true and not _has_pm_execution_evidence(
            evidence_text if evidence_text is not None else new_text):
        return deny(
            "PMO-SPEC-009",
            "Execution Authorized false -> true requires explicit PM "
            "authorization evidence (a PM-DECISION change-history entry or an "
            "'Execution Authorization Evidence' reference); it must not be "
            "inferred from generation, publication or repository upload.",
        )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-010 / 011  FR / NFR structure
# --------------------------------------------------------------------------- #

def _split_headed_blocks(spec_text, id_rx):
    """{id: block_text} for `#### <ID> ...` headed blocks (body until next heading)."""
    out = {}
    pattern = re.compile(r"(?m)^(#{2,6})\s+(" + id_rx + r")\b.*$")
    matches = list(pattern.finditer(spec_text or ""))
    for m in matches:
        rid = m.group(2)
        rest = (spec_text or "")[m.end():]
        nm = re.search(r"(?m)^#{1,6}\s+\S", rest)
        block = rest[:nm.start()] if nm else rest
        out[rid] = block
    return out


def parse_fr_definitions(spec_text):
    return _split_headed_blocks(spec_text, r"FR-\d{3,}")


def parse_nfr_definitions(spec_text):
    return _split_headed_blocks(spec_text, r"NFR-\d{3,}")


def _requirement_identity_map(blocks):
    out = {}
    for rid, block in blocks.items():
        source_text = _nfr_field(block, FR_SOURCE_ALIASES) or ""
        out[rid] = {
            "status": _field(block, "Status"),
            "title": _field(block, "Title"),
            "requirement": _field(block, "Requirement"),
            "source_scope": set(re.findall(
                r"SCP-REQ-\d+|INT-REQ-\d+", source_text)),
        }
    return out



_LIST_ITEM_RE = re.compile(r"^[ \t]+(?:[-*+]|\d+[.)])[ \t]+(\S.*?)[ \t]*$")
_STATE_TOKEN_RE = re.compile(
    r"^(NOT_APPLICABLE|NOT_SPECIFIED|PENDING_DECISION)\b(.*)$",
    re.IGNORECASE | re.DOTALL)
_PENDING_REF_RE = re.compile(
    r"\b(?:QST|ASM)-\d+\b|\b(?:SPEC-|SCP-|BRAND-)?OPEN-\d+\b")


def _field_value(block, label):
    """Value of a `Label:` field that may be given inline (`- **Label:** v`)
    OR as an indented bullet / numbered list under the label
    (`- **Label:**` + `  - item`). Multi-line values are joined with newlines
    (the original item text is never rewritten). None when the field is
    absent or has no value at all."""
    core = r"[ \t]+".join(re.escape(p) for p in label.split())
    pattern = re.compile(
        r"^[ \t>*\-+|]*\**[ \t]*" + core
        + r"[ \t]*\**[ \t]*[:|][ \t]*\**[ \t]*(.*?)[ \t]*\**[ \t]*\|?[ \t]*$",
        re.IGNORECASE | re.MULTILINE)
    m = pattern.search(block or "")
    if not m:
        return None
    inline = m.group(1).strip().strip("*").strip().strip("`").strip()
    if inline:
        return inline
    items = []
    for line in (block or "")[m.end():].split("\n")[1:]:
        lm = _LIST_ITEM_RE.match(line)
        if not lm:
            break
        items.append(lm.group(1))
    return "\n".join(items) if items else None


def _is_bare_placeholder(value):
    return norm_token((value or "").strip().rstrip(".").strip()) in NOT_APPLICABLE


def classify_applicability(value):
    """(state, detail, error). `state` is one of APPLICABILITY_STATES, or None
    when `error` explains why the value is not a valid applicability
    statement. A bare N/A / None / TBD placeholder is never DEFINED."""
    text = (value or "").strip()
    m = _STATE_TOKEN_RE.match(text)
    if m:
        token = m.group(1)
        if token != token.upper():
            return None, None, ("applicability state '{}' must be written in "
                                "upper case.".format(token))
        state = token.upper()
        rest = re.sub(r"^[\s:\u2014\u2013(-]+", "", m.group(2)).strip()
        rest = rest[:-1].strip() if rest.endswith(")") and "(" not in rest else rest
        if state == "NOT_APPLICABLE":
            if not rest or _is_bare_placeholder(rest):
                return None, None, ("NOT_APPLICABLE requires a stated reason "
                                    "(NOT_APPLICABLE: <why this does not apply>).")
        elif state == "PENDING_DECISION":
            if not _PENDING_REF_RE.search(rest):
                return None, None, ("PENDING_DECISION must reference the "
                                    "canonical Q&A record (QST-###/ASM-###).")
        return state, rest, None
    if not text or _is_bare_placeholder(text):
        return None, None, ("a bare '{}' placeholder is not a valid value - use "
                            "DEFINED text, NOT_APPLICABLE: <reason>, "
                            "NOT_SPECIFIED or PENDING_DECISION: <QST-###>."
                            .format(text))
    return "DEFINED", text, None


def _pending_reference_error(rid, label, detail, root, spec_text, approved):
    """None when every cited Q&A / OPEN reference exists and (pre-approval)
    is still unresolved; else an explanatory message."""
    refs = sorted(set(_PENDING_REF_RE.findall(detail or "")))
    qa_ids = [r for r in refs if r.startswith(("QST-", "ASM-"))]
    open_ids = [r for r in refs if r not in qa_ids]
    if root is None:
        return "{} {}: cannot verify PENDING_DECISION without a project root.".format(rid, label)
    records = {r["id"]: r for r in qac.qa_records(root)}
    for ref in qa_ids:
        rec = records.get(ref)
        if rec is None:
            return ("{} {} PENDING_DECISION cites {} but no such canonical Q&A "
                    "record exists.".format(rid, label, ref))
        status = norm_token(rec.get("status"))
        if not approved and status in qac.CLAIMS_RESOLUTION_STATUSES:
            return ("{} {} is PENDING_DECISION on {}, which is already {} - "
                    "convert the field to its resolved DEFINED value.".format(
                        rid, label, ref, status))
    known_open = {i["id"] for i in parse_open_items(spec_text or "")}
    for ref in open_ids:
        if ref not in known_open:
            return ("{} {} PENDING_DECISION cites {} which is not an open item "
                    "of this Specification.".format(rid, label, ref))
    return None


def validate_fr_structure(fr_blocks, root=None, spec_text=None, approved=False):
    for rid, block in fr_blocks.items():
        status = norm_token(_field(block, "Status"))
        if status not in VALID_FR_STATUS:
            return deny(
                "PMO-SPEC-010",
                "{} has Status '{}' - must be ACTIVE, DEFERRED or RETIRED.".format(
                    rid, _field(block, "Status")),
            )
        if status == "ACTIVE":
            for label in FR_CORE_LABELS:
                if label == "Source Scope":
                    if _nfr_field(block, FR_SOURCE_ALIASES) is None:
                        return deny(
                            "PMO-SPEC-010",
                            "active {} is missing a Source Scope / Source "
                            "Requirement reference.".format(rid),
                        )
                    continue
                val = _field_value(block, label)
                if val is None:
                    return deny(
                        "PMO-SPEC-010",
                        "active {} is missing the mandatory (core) field "
                        "'{}'.".format(rid, label),
                    )
                if label == "Acceptance Criteria":
                    if _is_bare_placeholder(val) or all(
                            _is_bare_placeholder(i) for i in val.split("\n")):
                        return deny(
                            "PMO-SPEC-010",
                            "active {} has empty / N/A Acceptance Criteria - it "
                            "must be objective and testable.".format(rid),
                        )
                elif _is_bare_placeholder(val):
                    return deny(
                        "PMO-SPEC-010",
                        "active {} core field '{}' has only a placeholder "
                        "('{}') - a substantive value is required.".format(
                            rid, label, val),
                    )
            for label in FR_DERIVED_LABELS:
                if _field(block, label) is None:
                    return deny(
                        "PMO-SPEC-010",
                        "active {} is missing the governance-derived field "
                        "'{}'.".format(rid, label),
                    )
            for label in FR_CONDITIONAL_LABELS:
                val = _field_value(block, label)
                if val is None:
                    return deny(
                        "PMO-SPEC-010",
                        "active {} is missing an applicability statement for "
                        "'{}' (DEFINED value, NOT_APPLICABLE: <reason>, "
                        "NOT_SPECIFIED or PENDING_DECISION: <QST-###>).".format(
                            rid, label),
                    )
                state, detail, err = classify_applicability(val)
                if err is not None:
                    # An APPROVED baseline that was valid under the prior schema
                    # keeps its legacy free-text values: no mass migration.
                    if approved and not _STATE_TOKEN_RE.match(val.strip()):
                        continue
                    return deny("PMO-SPEC-010",
                                "active {} field '{}': {}".format(rid, label, err))
                if state == "PENDING_DECISION":
                    perr = _pending_reference_error(
                        rid, label, detail, root, spec_text, approved)
                    if perr is not None:
                        return deny("PMO-SPEC-010", perr)
        else:
            for label in FR_HISTORICAL_LABELS:
                if label == "Source Scope":
                    if _nfr_field(block, FR_SOURCE_ALIASES) is None:
                        return deny(
                            "PMO-SPEC-010",
                            "{} ({}) must retain a historical Source Scope / "
                            "Source Requirement reference.".format(rid, status),
                        )
                    continue
                if _field(block, label) is None:
                    return deny(
                        "PMO-SPEC-010",
                        "{} ({}) must retain the historical field '{}'.".format(
                            rid, status, label),
                    )
    return None


def _nfr_field(block, aliases):
    for label in aliases:
        v = _field(block, label)
        if v is not None:
            return v
    return None


def validate_nfr_structure(nfr_blocks):
    for rid, block in nfr_blocks.items():
        status = norm_token(_field(block, "Status"))
        if status not in VALID_FR_STATUS:
            return deny(
                "PMO-SPEC-011",
                "{} has Status '{}' - must be ACTIVE, DEFERRED or RETIRED.".format(
                    rid, _field(block, "Status")),
            )
        if status != "ACTIVE":
            for label in ("Introduced In", "Last Modified In", "Change Source",
                          "Status"):
                if _field(block, label) is None:
                    return deny(
                        "PMO-SPEC-011",
                        "{} ({}) must retain the historical field '{}'.".format(
                            rid, status, label),
                    )
            continue
        for label in NFR_ACTIVE_LABELS:
            if _field(block, label) is None:
                return deny(
                    "PMO-SPEC-011",
                    "active {} is missing the mandatory field '{}'.".format(
                        rid, label),
                )
        if _nfr_field(block, NFR_SOURCE_ALIASES) is None:
            return deny(
                "PMO-SPEC-011",
                "active {} is missing a Source Scope / evidence reference.".format(
                    rid),
            )
        crit = None
        for _lbl in NFR_CRITERIA_ALIASES:
            crit = _field_value(block, _lbl)
            if crit is not None:
                break
        if not crit or all(_is_bare_placeholder(i) for i in crit.split("\n")):
            return deny(
                "PMO-SPEC-011",
                "active {} has empty acceptance / verification criteria - an "
                "unknown threshold must remain OPEN, not blank.".format(rid),
            )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-012  OPEN identifier provenance
# --------------------------------------------------------------------------- #

def validate_open_provenance(open_items):
    for it in open_items or []:
        pid = it.get("id", "")
        pref = _open_prefix(pid)
        if not pref:
            continue
        prov = norm_token(it.get("provenance") or "")
        origin = it.get("origin") or ""
        if pref == "SPEC-OPEN":
            if re.search(r"\b(?:OPEN|SCP-OPEN|BRAND-OPEN)-\d+\b", origin, re.I):
                return deny(
                    "PMO-SPEC-012",
                    "{} is a SPEC-OPEN id whose Origin references an upstream "
                    "item ('{}'); an upstream OPEN keeps its own identity and "
                    "is never re-issued as SPEC-OPEN.".format(pid, origin.strip()),
                )
            if prov in ("INTENT", "SCOPE", "BRAND"):
                return deny(
                    "PMO-SPEC-012",
                    "{} is a SPEC-OPEN id declared with upstream provenance "
                    "'{}'; SPEC-OPEN is only for specification-native "
                    "questions.".format(pid, it.get("provenance")),
                )
        else:
            expected = OPEN_PREFIX_EXPECT.get(pref)
            if prov and expected and prov != expected:
                return deny(
                    "PMO-SPEC-012",
                    "{} declares provenance '{}' but its identifier prefix is "
                    "reserved for {}-originated questions; upstream OPEN items "
                    "must not be renamed or re-provenanced.".format(
                        pid, it.get("provenance"), expected),
                )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-013  Specification Change History
# --------------------------------------------------------------------------- #

def parse_change_history_rows(spec_text):
    tbl = _table_after(spec_text, HISTORY_HEADING_RE)
    if tbl is None:
        return None
    return tbl[1]


def validate_change_history(cur_ver, spec_text, rows=None):
    if not _has_heading(spec_text, HISTORY_HEADING_RE):
        return deny("PMO-SPEC-013",
                    "the '## Specification Change History' section is missing.")
    if rows is None:
        rows = parse_change_history_rows(spec_text)
    if rows is None:
        return deny("PMO-SPEC-013",
                    "the Specification Change History table is missing.")
    if not rows:
        return deny("PMO-SPEC-013",
                    "the Specification Change History has no rows.")
    for row in rows:
        if len(row) < 6 or any((c is None or not c.strip()) for c in row[:6]):
            return deny(
                "PMO-SPEC-013",
                "a Specification Change History row is incomplete (need "
                "Version, Date, Change Source, Changed IDs, Summary, PM "
                "Decision): {}.".format(row),
            )
    cur_rows = [r for r in rows if parse_ver(r[0]) == cur_ver]
    if len(cur_rows) != 1:
        return deny(
            "PMO-SPEC-013",
            "the current Spec Version {} must have exactly one Specification "
            "Change History row (found {}).".format(
                ver_str(cur_ver), len(cur_rows)),
        )
    if cur_ver == (0, 1):
        blob = (cur_rows[0][2] + " " + cur_rows[0][4]).lower()
        if not re.search(r"initial_scope|initial\s+scope|scope\s*v?0\.1"
                         r"|initial_intent|initial\s+intent", blob):
            return deny(
                "PMO-SPEC-013",
                "the initial (0.1) Specification Change History row must record "
                "Change Source = initial Scope generation (INITIAL_SCOPE).",
            )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-014  change provenance
# --------------------------------------------------------------------------- #

def _change_source_tokens(value):
    return [t for t in re.split(r"[,;/]|\s{2,}", value or "") if t.strip()]


_FEEDBACK_ID_RE = re.compile(r"FDB-\d+|FB-\d{4}-\d{3}-\d{3}", re.I)


def known_feedback_ids(root):
    """Set of feedback ids (legacy FDB-XXX and canonical Feedback Item ids
    FB-YYYY-NNN-NNN) known to the feedback subsystem, or None if it does not
    exist yet."""
    found = set()
    exists = False
    for rel in FEEDBACK_DIRS:
        d = os.path.join(root, rel)
        if not os.path.isdir(d):
            continue
        exists = True
        for cur, _dirs, names in os.walk(d):
            for name in names:
                for m in _FEEDBACK_ID_RE.finditer(name):
                    found.add(m.group(0).upper())
                if name.lower().endswith((".md", ".yaml", ".yml", ".json", ".txt")):
                    txt = read_text(os.path.join(cur, name)) or ""
                    for m in _FEEDBACK_ID_RE.finditer(txt):
                        found.add(m.group(0).upper())
    return found if exists else None


def approved_cr_ids(root):
    """CR ids that may authorize (or remain the Change Source of) Specs
    content: canonical CR records that are APPROVED or INCORPORATED and
    well-formed. Delegates to the CR core's structural parser (never
    string-splits a table row)."""
    return crcore.cr_authorizing_ids(root)


def validate_change_provenance(fr_blocks, nfr_blocks, feedback_ids=None,
                               approved_crs=None):
    approved_crs = {c.upper() for c in (approved_crs or set())}
    both = {}
    both.update(fr_blocks or {})
    both.update(nfr_blocks or {})
    for rid, block in both.items():
        cs = _field(block, "Change Source")
        if cs is None:
            return deny("PMO-SPEC-014",
                        "{} is missing a Change Source.".format(rid))
        status = norm_token(_field(block, "Status"))
        for tok in _change_source_tokens(cs):
            tok = tok.strip().strip("`*")
            if not tok:
                continue
            if not PERMITTED_CHANGE_SOURCE_RE.match(tok):
                return deny(
                    "PMO-SPEC-014",
                    "{} has an invalid Change Source token '{}' (allowed: "
                    "INITIAL_SCOPE, INITIAL_INTENT, SCOPE-RECONCILIATION, "
                    "PM-DECISION, FDB-XXX / FB-YYYY-NNN-NNN, "
                    "CR-XXX, 'Scope vX.Y').".format(rid, tok),
                )
            fm = re.match(r"^(?:FDB-\d+|FB-\d{4}-\d{3}-\d{3})$", tok, re.I)
            if fm and feedback_ids is not None and tok.upper() not in {
                    i.upper() for i in feedback_ids}:
                return deny(
                    "PMO-SPEC-014",
                    "{} cites Change Source {} but no matching feedback record "
                    "exists.".format(rid, tok),
                )
            cm = re.match(r"^CR-\d+$", tok, re.I)
            if cm and status == "ACTIVE" and tok.upper() not in approved_crs:
                return deny(
                    "PMO-SPEC-014",
                    "{} is ACTIVE via {} but that Change Request is not "
                    "APPROVED - out-of-scope functionality must not become "
                    "committed.".format(rid, tok),
                )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-015  reverse traceability (no unapproved Scope expansion)
# --------------------------------------------------------------------------- #

def validate_reverse_traceability(fr_blocks, nfr_blocks, req_ids):
    """req_ids is the current upstream requirement set - SCP-REQ ids on the
    LEGACY path, INT-REQ ids on the NEW (no-Scope) lifecycle path. Either
    way, every active FR/NFR needs a Source Scope / Source Requirement trace
    into that set, or an approved change origin."""
    req_ids = set(req_ids or ())
    both = {}
    both.update(fr_blocks or {})
    both.update(nfr_blocks or {})
    for rid, block in both.items():
        if norm_token(_field(block, "Status")) != "ACTIVE":
            continue
        src = (_field(block, "Source Scope") or _field(block, "Source Requirement")
               or _field(block, "Source") or _field(block, "Evidence") or "")
        src_refs = set(re.findall(r"SCP-REQ-\d+|INT-REQ-\d+", src))
        cs = _field(block, "Change Source") or ""
        approved_origin = bool(re.search(
            r"\b(?:CR-\d+|PM[-_]DECISION|SCOPE[-_]RECONCILIATION|FDB-\d+"
            r"|QST-\d+|ASM-\d+)\b",
            cs, re.I))
        if not (src_refs & req_ids) and not approved_origin:
            return deny(
                "PMO-SPEC-015",
                "active {} has neither upstream traceability (a Source Scope "
                "/ Source Requirement reference in the current Scope or "
                "Intent) nor an approved change origin (CR / PM-DECISION / "
                "SCOPE-RECONCILIATION / FDB / QST / ASM); Specs must not "
                "silently introduce functionality beyond what was "
                "committed.".format(rid),
            )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-016  project identity
# --------------------------------------------------------------------------- #

def validate_project_identity(meta, cfg):
    if not isinstance(cfg, dict):
        return None
    project = cfg.get("project") if isinstance(cfg.get("project"), dict) else {}
    checks = (
        ("project id", project.get("id"), "Project ID"),
        ("project", project.get("name"), "Project"),
        ("client", project.get("client"), "Client"),
    )
    for key, cfg_val, label in checks:
        doc_val = _clean((meta or {}).get(key))
        cfg_val = _clean(cfg_val)
        if not doc_val or not cfg_val:
            continue
        if doc_val.casefold() != cfg_val.casefold():
            return deny(
                "PMO-SPEC-016",
                "Specification {} '{}' does not match .pmo/project-config.yaml "
                "('{}'); project-config is the identity authority.".format(
                    label, doc_val, cfg_val),
            )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-017  Intent / Scope source versions
# --------------------------------------------------------------------------- #

def validate_source_versions(meta, root):
    meta = meta or {}
    iv = norm_ver(meta.get("intent version"))
    intent_text = read_text(os.path.join(root, INTENT_RELPATH))
    if iv and intent_text is not None:
        actual_iv = norm_ver(_field(intent_text, "Intent Version")
                             or _field(intent_text, "Version"))
        if actual_iv and iv != actual_iv:
            return deny(
                "PMO-SPEC-017",
                "Document Control Intent Version {} does not match the "
                "validated Intent ({}).".format(iv, actual_iv),
            )
    sv = norm_ver(meta.get("scope version"))
    arts = all_scope_artifacts(root)
    art_versions = {ver_str(v) for _, v in arts}
    _, cur_ver = locate_current_scope(root)
    if sv:
        if art_versions and sv not in art_versions:
            return deny(
                "PMO-SPEC-017",
                "Document Control Scope Version {} has no matching Scope "
                "artifact under docs/pmo/scope/ ({}).".format(
                    sv, ", ".join(sorted(art_versions)) or "none"),
            )
        if cur_ver and parse_ver(sv) and parse_ver(sv) > cur_ver:
            return deny(
                "PMO-SPEC-017",
                "Document Control Scope Version {} is ahead of the current "
                "Scope artifact ({}).".format(sv, ver_str(cur_ver)),
            )
    gf = _clean(meta.get("generated from"))
    if gf:
        gm = re.search(r"scope-v(\d+\.\d+)\.md", gf)
        if gm and sv and norm_ver(gm.group(1)) != sv:
            return deny(
                "PMO-SPEC-017",
                "'Generated From' ({}) names a different Scope version than "
                "Scope Version {}.".format(gf, sv),
            )
        if not os.path.isabs(gf) and not os.path.exists(_abspath(gf, root)):
            return deny(
                "PMO-SPEC-017",
                "'Generated From' path '{}' does not exist.".format(gf),
            )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-018  PMO state protection
# --------------------------------------------------------------------------- #

def validate_pmo_state(before_text, after_text):
    try:
        before = parse_project_config(before_text or "")
        after = parse_project_config(after_text or "")
    except Exception as exc:  # pragma: no cover - defensive
        return deny("PMO-SPEC-020",
                    "could not parse project-config for state comparison "
                    "({!r}).".format(exc))
    changed = [".".join(p) for p in PROTECTED_STATE_PATHS
               if _dig(before, p) != _dig(after, p)]
    if changed:
        return deny(
            "PMO-SPEC-018",
            "Specs generation must not change protected PMO state: {}. It may "
            "only record artifact-specific state under "
            "artifacts.specifications.".format(", ".join(changed)),
        )
    return None


# --------------------------------------------------------------------------- #
# PMO-SPEC-019  publishing separation
# --------------------------------------------------------------------------- #

def validate_publish_readiness(root):
    cfg = parse_project_config_file(root) or {}
    verified = _dig(cfg, ("repository", "verified"))
    if verified is not True:
        return deny(
            "PUBLISH_BLOCKED_REPOSITORY_NOT_VERIFIED",
            "repository.verified is not true - Specs may be valid locally but "
            "publishing is blocked. Publishing uses only the configured "
            "repository; repo-binding-guard.py governs remote safety. Do not "
            "mark Specs publishing as PUBLISHED.",
        )
    return None


# --------------------------------------------------------------------------- #
# git action detection
# --------------------------------------------------------------------------- #

def _split_segments(command):
    parts = re.split(r"&&|\|\||[;\n|&]", command or "")
    return [p.strip() for p in parts if p.strip()]


def _tokenize(segment):
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def detect_relevant_git_action(command):
    """(action, touches_specs) where action in {git_add, git_commit, git_push,
    None}."""
    for seg in _split_segments(command or ""):
        toks = _tokenize(seg)
        if len(toks) < 2:
            continue
        head = os.path.basename(toks[0])
        if head != "git":
            continue
        sub = toks[1]
        rest = toks[2:]
        if sub == "add":
            broad = {".", "-A", "--all", "-a", ":/", "--", "*"}
            touches = any(
                t in broad
                or t.endswith("specs/specs.md")
                or t.rstrip("/").endswith("docs/pmo/specs")
                or t.rstrip("/") in ("docs", "docs/pmo", "docs/pmo/specs")
                for t in rest
            )
            return "git_add", touches
        if sub == "commit":
            explicit = any(t.endswith("specs/specs.md") for t in rest)
            allflag = any(
                t in ("-a", "--all", "-am", "-ma")
                or (t.startswith("-") and not t.startswith("--")
                    and "a" in t and "m" in t)
                for t in rest
            )
            return "git_commit", (explicit or allflag)
        if sub == "push":
            return "git_push", False
    return None, False


# --------------------------------------------------------------------------- #
# Composite validations
# --------------------------------------------------------------------------- #

def full_spec_validation(root, spec_text=None):
    """Every deterministic controlled-gate check, in order. Returns the first
    Decision, or None when the Specs artifact is clean. Fails closed."""
    try:
        spath = _abspath(CANONICAL_SPEC_POSIX, root)
        if spec_text is None:
            spec_text = read_text(spath)
        if spec_text is None:
            return deny(
                "PMO-SPEC-002",
                "no canonical Specs artifact at {} to validate.".format(
                    CANONICAL_SPEC_POSIX),
            )

        legacy = has_legacy_scope(root)

        d = validate_scope_readiness(root) if legacy \
            else validate_new_lifecycle_readiness(root)
        if d is not None:
            return d

        meta = parse_spec_metadata(spec_text)

        d = validate_required_sections(spec_text, meta, legacy_scope=legacy)
        if d is not None:
            return d

        cfg = parse_project_config_file(root) or {}

        d = validate_project_identity(meta, cfg)
        if d is not None:
            return d

        d = validate_source_versions(meta, root)
        if d is not None:
            return d

        cur_ver = parse_spec_version(meta)
        if cur_ver is None:
            return deny("PMO-SPEC-007",
                        "Spec Version metadata missing or unparseable.")

        hist_rows = parse_change_history_rows(spec_text)
        d = validate_change_history(cur_ver, spec_text, hist_rows)
        if d is not None:
            return d

        scope_approved = _scope_is_approved(cfg)
        hist_versions = [parse_ver(r[0]) for r in (hist_rows or [])
                         if parse_ver(r[0])]
        d = validate_spec_version(cur_ver, hist_versions, scope_approved)
        if d is not None:
            return d

        d = validate_spec_status(meta, scope_approved)
        if d is not None:
            return d

        d = validate_execution_authorization(meta, spec_text, cur_ver)
        if d is not None:
            return d

        fr_blocks = parse_fr_definitions(spec_text)
        approved_baseline = (meta.get("execution authorized") or "").strip().lower() == "true"
        d = validate_fr_structure(fr_blocks, root=root, spec_text=spec_text,
                                  approved=approved_baseline)
        if d is not None:
            return d

        nfr_blocks = parse_nfr_definitions(spec_text)
        d = validate_nfr_structure(nfr_blocks)
        if d is not None:
            return d

        d = validate_identifier_uniqueness(spec_text)
        if d is not None:
            return d

        d = validate_business_rules(parse_business_rules(spec_text))
        if d is not None:
            return d

        d = validate_open_provenance(parse_open_items(spec_text))
        if d is not None:
            return d

        if legacy:
            sc_path, _ = locate_current_scope(root)
            req_ids = read_scope_requirements(read_text(sc_path) or "") \
                if sc_path else set()
            d = validate_scope_traceability(req_ids, spec_text)
        else:
            req_ids = read_intent_requirements(root)
            d = validate_intent_traceability_specs(req_ids, spec_text)
        if d is not None:
            return d

        d = validate_reverse_traceability(fr_blocks, nfr_blocks, req_ids)
        if d is not None:
            return d

        d = validate_change_provenance(
            fr_blocks, nfr_blocks,
            feedback_ids=known_feedback_ids(root),
            approved_crs=approved_cr_ids(root),
        )
        if d is not None:
            return d

        return None
    except Exception as exc:  # fail closed
        return deny(
            "PMO-SPEC-020",
            "internal error during Specs validation ({!r}); failing "
            "closed.".format(exc),
        )


def _lightweight_spec_checks(new_text, tool_name, tool_input, root, disk_text):
    """Always-on checks that never block legitimate progressive authoring."""
    d = validate_identifier_uniqueness(new_text)
    if d is not None:
        return d

    meta = parse_spec_metadata(new_text)
    cfg = parse_project_config_file(root)
    if cfg and (meta.get("project id") or meta.get("project") or meta.get("client")):
        d = validate_project_identity(meta, cfg)
        if d is not None:
            return d

    items = parse_open_items(new_text)
    if items:
        d = validate_open_provenance(items)
        if d is not None:
            return d

    raw_ea = meta.get("execution authorized")
    if raw_ea is not None and norm_token(raw_ea) not in ("TRUE", "FALSE"):
        return deny(
            "PMO-SPEC-009",
            "Execution Authorized must be literally true or false, not "
            "'{}'.".format(raw_ea),
        )

    if tool_name == "Edit":
        d = validate_execution_authorization_transition(
            tool_input.get("old_string", ""),
            tool_input.get("new_string", ""),
            evidence_text=new_text,
        )
        if d is not None:
            return d
    elif tool_name in ("Write", "MultiEdit") and disk_text:
        d = validate_execution_authorization_transition(
            disk_text, new_text, evidence_text=new_text)
        if d is not None:
            return d
    return None


# --------------------------------------------------------------------------- #
# Payload dispatch
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


def process_write_edit(tool_name, tool_input, root):
    path = tool_input.get("file_path")
    if not isinstance(path, str) or not path.strip():
        return None
    rel = _relpath(path, root)

    bad = validate_canonical_path(rel)
    if bad is not None:
        return bad

    if rel == CANONICAL_SPEC_POSIX:
        disk_text = read_text(_abspath(path, root))
        new_text = resulting_content(tool_name, tool_input, disk_text)
        if new_text is None:
            return None
        return _lightweight_spec_checks(new_text, tool_name, tool_input, root,
                                        disk_text)

    if rel == ".pmo/project-config.yaml":
        before = read_text(_abspath(path, root)) or ""
        after = resulting_content(tool_name, tool_input, before)
        if after is None:
            return None
        touches_spec_state = bool(
            re.search(r"(?m)^\s{2,}specifications\s*:", after)
            or re.search(r"(?m)^\s{2,}specifications\s*:", before)
        )
        if touches_spec_state:
            d = validate_pmo_state(before, after)
            if d is not None:
                return d
        return None

    return None


def process_bash(command, root):
    action, touches = detect_relevant_git_action(command)
    if action in ("git_add", "git_commit") and touches:
        spath = _abspath(CANONICAL_SPEC_POSIX, root)
        if not os.path.exists(spath):
            return None
        return full_spec_validation(root)
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
                "PMO-SPEC-020",
                "unexpected internal error during Specs write validation "
                "({!r}); blocking as a precaution.".format(exc),
            )

    if tool_name == "Bash":
        try:
            return process_bash(tool_input.get("command") or "", root)
        except Exception as exc:  # fail closed
            return deny(
                "PMO-SPEC-020",
                "unexpected internal error validating a Specs git gate "
                "({!r}); blocking as a precaution.".format(exc),
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
    if not raw or not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except Exception:
        return 0
    try:
        decision = process(payload)
    except Exception as exc:  # fail closed
        decision = deny(
            "PMO-SPEC-020",
            "unexpected error in specs governance guard ({!r}); failing "
            "closed.".format(exc),
        )
    if decision is not None:
        emit(decision)
    return 0


if __name__ == "__main__":
    sys.exit(main())
