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
  * OPEN questions are governed records whose "Required Before" gate is a known
    workflow stage; an unresolved OPEN may be carried past Intent validation
    when that gate falls later than the Intent hand-off.

A DRAFT Intent stays fully editable. Structural completeness is only enforced
when the artifact is being validated / staged / committed / moved to
PM_REVIEWED or VALIDATED.

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

Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

INTENT_RELPATH = os.path.join("docs", "pmo", "intent", "intent.md")
INTENT_POSIX = "docs/pmo/intent/intent.md"
CONFIG_RELPATH = os.path.join(".pmo", "project-config.yaml")
APPROVALS_RELDIR = os.path.join(".pmo", "approvals")
INTENT_APPROVAL_RELPATH = os.path.join(".pmo", "approvals", "intent-approval.yaml")

# Fields the PM-explicit Intent approval record must carry.
APPROVAL_REQUIRED_DECISION = "APPROVED"
APPROVAL_REQUIRED_SOURCE = "PM_EXPLICIT"

ALLOWED_STATUSES = ("DRAFT", "PM_REVIEWED", "VALIDATED", "SUPERSEDED")

REQUIRED_SECTIONS = (
    "1. Client Vision",
    "2. Business Problem",
    "3. Overall Client Goal",
    "4. Proposed Product Outcome",
    "5. Users, Actors and Systems",
    "6. High-Level Product Requirements",
    "7. Constraints",
    "8. Explicitly Out of Scope",
    "9. Dependencies",
    "10. Assumptions",
    "11. Open Questions",
    "12. Contradictions / Source Conflicts",
    "13. Risks Carried Into Requirement Gathering",
    "14. Source Register",
    "15. Intent Validation Summary",
    "16. Acceptance",
)

REQUIRED_DOC_CONTROL_FIELDS = (
    "Project",
    "Client",
    "Project ID",
    "Date",
    "Intent Version",
    "Status",
    "Repository",
    "Source Count",
    "Next Stage",
)

REQUIRED_NEXT_STAGE = "REQUIREMENT_GATHERING"
ACCEPTED_NEXT_STAGE = {"REQUIREMENT_GATHERING", "REQUIREMENTS_GATHERING"}
FORBIDDEN_NEXT_STAGE = {
    "SPEC", "SPECS", "SPECIFICATION", "SPECIFICATIONS",
    "DEVELOPMENT", "DEV", "BUILD", "DESIGN",
}

# Intent-owned identifier namespaces and the section that owns each one.
NS_OWNING_SECTION = {
    "INT-REQ": "6. High-Level Product Requirements",
    "INT-OOS": "8. Explicitly Out of Scope",
    "ASM": "10. Assumptions",
    "OPEN": "11. Open Questions",
    "CONFLICT": "12. Contradictions / Source Conflicts",
    "RISK": "13. Risks Carried Into Requirement Gathering",
    "SRC": "14. Source Register",
}
INTENT_NAMESPACES = tuple(NS_OWNING_SECTION.keys())

# FR-XXX / NFR-XXX are reserved for specs.md and must never appear in Intent.
_FR_NFR_RE = re.compile(r"(?<![0-9A-Za-z])(?:FR|NFR)-\d+")

_HEADING_RE = re.compile(r"^\s{0,3}#{2,}\s+(.+?)\s*#*\s*$")


# --------------------------------------------------------------------------- #
# Decision plumbing
# --------------------------------------------------------------------------- #

class Decision(object):
    """A deny decision produced by one of the controls."""

    __slots__ = ("code", "message")

    def __init__(self, code, message):
        self.code = code
        self.message = message


def deny(code, message):
    """Build a deny Decision (kept as a value so controls stay testable)."""
    return Decision(code, message)


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
# Minimal YAML subset parser (stdlib only) - just enough for project-config
# --------------------------------------------------------------------------- #

def _strip_comment(line):
    out = []
    quote = None
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


def parse_simple_yaml(text):
    """Parse the 2-space-indented mapping subset used by PMO project-config."""
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
            item_str = s[2:] if s.startswith("- ") else ""
            stripped = item_str.strip()
            if ":" in stripped and not stripped.startswith(('"', "'")):
                key, _, rest = stripped.partition(":")
                d = {key.strip(): _parse_scalar(rest.strip())}
                container.append(d)
                stack.append((indent, d))
            else:
                container.append(_parse_scalar(item_str))
            continue

        if ":" not in s:
            continue
        key, _, rest = s.partition(":")
        key = key.strip()
        rest = rest.strip()
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
# Project-root detection / project-config parsing
# --------------------------------------------------------------------------- #

def project_root(cwd):
    """Walk up from `cwd` to the checkout root (`.pmo/` or `.git/` marker)."""
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


def config_path_for(root):
    return os.path.join(root, CONFIG_RELPATH)


def load_project_config(root):
    """Return the parsed project-config mapping, or None when absent/unreadable."""
    path = config_path_for(root)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = parse_simple_yaml(handle.read())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Intent metadata parsing
# --------------------------------------------------------------------------- #

def _find_field(content, label):
    """Extract a `Label: value` style document-control field.

    Handles list rows (`- **Label:** value`), plain rows (`Label: value`) and
    single-line table rows (`| Label | value |`). Returns the first hit.
    """
    core = r"\s+".join(re.escape(part) for part in label.split())
    pattern = re.compile(
        r"^[ \t>*\-+|]*\**\s*" + core + r"\s*\**\s*[:|]\s*\**\s*(.+?)\s*\**\s*\|?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(content or "")
    if not match:
        return None
    value = match.group(1).strip().strip("*").strip()
    return value or None


def parse_doc_control(content):
    """Return a dict of the document-control fields present in `content`.

    Keys are lower-cased field labels. `project` falls back to `project name`.
    """
    meta = {}
    labels = (
        "Project ID", "Project Name", "Project", "Client", "Date",
        "Intent Version", "Status", "Repository", "Source Count", "Next Stage",
    )
    for label in labels:
        value = _find_field(content, label)
        if value is not None:
            meta[label.lower()] = value
    if "project" not in meta and "project name" in meta:
        meta["project"] = meta["project name"]
    return meta


def _norm_status(value):
    if not value:
        return None
    s = value.strip().upper().split("(")[0].strip()
    s = re.sub(r"[\s\-]+", "_", s)
    return s or None


def parse_status(content):
    """Return the normalised Intent Status token, or None."""
    return _norm_status(_find_field(content, "Status"))


def _norm_stage(value):
    return re.sub(r"[^A-Z0-9]+", "_", (value or "").strip().upper()).strip("_")


def _norm_heading(text):
    text = re.sub(r"\s*/\s*", " / ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


# --------------------------------------------------------------------------- #
# Workflow-stage ordering  (OPEN "Required Before" governance)
# --------------------------------------------------------------------------- #

# Deterministic order of the PMO workflow gates. An OPEN item's "Required
# Before" value names the gate by which the question must be resolved.
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
STAGE_ORDER = {name: index for index, name in enumerate(WORKFLOW_STAGES)}

# The Intent hands off to Requirement Gathering. An unresolved Blocking = YES
# OPEN item blocks Intent validation only when it must be resolved at or before
# this point (i.e. before the workflow may leave Intent).
INTENT_EXIT_STAGE_INDEX = STAGE_ORDER["REQUIREMENT_GATHERING"]

# Reasonable spelling / phrasing variants -> canonical stage. Keys are matched
# after upper-casing and collapsing non-alphanumerics to single spaces (and,
# separately, to single underscores).
_STAGE_ALIASES = {
    "INTENT VALIDATION": "INTENT_VALIDATION",
    "INTENT VALIDATED": "INTENT_VALIDATION",
    "VALIDATE INTENT": "INTENT_VALIDATION",
    "INTENT APPROVAL": "INTENT_VALIDATION",
    "INTENT SIGN OFF": "INTENT_VALIDATION",
    "REQUIREMENT GATHERING": "REQUIREMENT_GATHERING",
    "REQUIREMENTS GATHERING": "REQUIREMENT_GATHERING",
    "REQ GATHERING": "REQUIREMENT_GATHERING",
    "REQUIREMENTS": "REQUIREMENT_GATHERING",
    "RG": "REQUIREMENT_GATHERING",
    "SCOPE BASELINE": "SCOPE_BASELINE",
    "SCOPE BASELINING": "SCOPE_BASELINE",
    "BASELINE SCOPE": "SCOPE_BASELINE",
    "SCOPE": "SCOPE_BASELINE",
    "SCOPE DEFINITION": "SCOPE_BASELINE",
    "SCOPE APPROVAL": "SCOPE_BASELINE",
    "SPECIFICATION GENERATION": "SPECIFICATION_GENERATION",
    "SPECIFICATIONS GENERATION": "SPECIFICATION_GENERATION",
    "SPEC GENERATION": "SPECIFICATION_GENERATION",
    "SPECS GENERATION": "SPECIFICATION_GENERATION",
    "SPECIFICATION": "SPECIFICATION_GENERATION",
    "SPECIFICATIONS": "SPECIFICATION_GENERATION",
    "SPECS": "SPECIFICATION_GENERATION",
    "SPEC": "SPECIFICATION_GENERATION",
    "DEV": "DEVELOPMENT",
    "DEVELOP": "DEVELOPMENT",
    "BUILD": "DEVELOPMENT",
    "IMPLEMENTATION": "DEVELOPMENT",
    "CODING": "DEVELOPMENT",
    "QUALITY ASSURANCE": "QA",
    "QA TESTING": "QA",
    "TESTING": "QA",
    "TEST": "QA",
    "USER ACCEPTANCE": "UAT",
    "USER ACCEPTANCE TEST": "UAT",
    "USER ACCEPTANCE TESTING": "UAT",
    "DEPLOY": "DEPLOYMENT",
    "RELEASE": "DEPLOYMENT",
    "GO LIVE": "DEPLOYMENT",
    "LAUNCH": "DEPLOYMENT",
    "ROLLOUT": "DEPLOYMENT",
    "PRODUCTION": "DEPLOYMENT",
    "STORE UPLOAD": "DEPLOYMENT",
    "STORE SUBMISSION": "DEPLOYMENT",
}


def normalize_stage(value):
    """Canonical workflow stage for a free-text "Required Before" value.

    Returns one of WORKFLOW_STAGES, or None when the value cannot be understood.
    The caller then treats the OPEN record as invalid (PMO-INTENT-007) and
    reports the offending value - it never guesses at an unknown stage.
    """
    if value is None:
        return None
    base = re.sub(r"[^A-Za-z0-9]+", " ", str(value)).strip().upper()
    if not base:
        return None
    trimmed = re.sub(r"\b(GATE|STAGE|PHASE|MILESTONE|STEP)\b", " ", base)
    trimmed = re.sub(r"\s+", " ", trimmed).strip()
    for candidate in (base, base.replace(" ", "_"),
                      trimmed, trimmed.replace(" ", "_")):
        if not candidate:
            continue
        if candidate in STAGE_ORDER:
            return candidate
        if candidate in _STAGE_ALIASES:
            return _STAGE_ALIASES[candidate]
    return None


# --------------------------------------------------------------------------- #
# Section handling
# --------------------------------------------------------------------------- #

def document_headings(content):
    """All `##`+ heading titles in `content`, normalised for comparison."""
    found = []
    for line in (content or "").splitlines():
        match = _HEADING_RE.match(line)
        if match:
            found.append(_norm_heading(match.group(1)))
    return found


def missing_sections(content):
    """Required section titles that are absent from `content`."""
    present = set(document_headings(content))
    return [title for title in REQUIRED_SECTIONS
            if _norm_heading(title) not in present]


def section_body(content, heading_title):
    """Text between `heading_title` and the next `##`+ heading (or None)."""
    target = _norm_heading(heading_title)
    lines = (content or "").splitlines()
    body = []
    capturing = False
    for line in lines:
        match = _HEADING_RE.match(line)
        if match:
            if capturing:
                break
            if _norm_heading(match.group(1)) == target:
                capturing = True
            continue
        if capturing:
            body.append(line)
    return "\n".join(body) if capturing else None


def validate_sections(content):
    """PMO-INTENT-002 - the full section skeleton must be present."""
    missing = missing_sections(content)
    if missing:
        return deny(
            "PMO-INTENT-002",
            "PMO Intent guard: intent.md is missing required section "
            "heading(s): {}. The Intent skeleton must be complete before it "
            "is validated, staged or committed.".format(
                "; ".join("## " + title for title in missing)
            ),
        )
    return None


# --------------------------------------------------------------------------- #
# Status validation
# --------------------------------------------------------------------------- #

def validate_status_value(status):
    """PMO-INTENT-008 - Status, when present, must be an allowed value."""
    if status is None:
        return None
    if status not in ALLOWED_STATUSES:
        return deny(
            "PMO-INTENT-008",
            "PMO Intent guard: Intent Status '{}' is not allowed. Allowed "
            "statuses: {}.".format(status, ", ".join(ALLOWED_STATUSES)),
        )
    return None


# --------------------------------------------------------------------------- #
# Workflow-stage / document-control validation
# --------------------------------------------------------------------------- #

def validate_doc_control_fields(meta):
    """PMO-INTENT-003 (part 1) - all document-control fields must be present."""
    missing = [field for field in REQUIRED_DOC_CONTROL_FIELDS
               if not meta.get(field.lower())]
    if missing:
        return deny(
            "PMO-INTENT-003",
            "PMO Intent guard: Intent document control is missing required "
            "field(s): {}. Required fields: {}.".format(
                ", ".join(missing), ", ".join(REQUIRED_DOC_CONTROL_FIELDS)
            ),
        )
    return None


def validate_next_stage(meta, finalizing):
    """PMO-INTENT-003 (part 2) - Next Stage must be REQUIREMENT_GATHERING.

    The "must not skip ahead" check runs even for DRAFT edits; the "must be
    present and exactly REQUIREMENT_GATHERING" check only runs at finalisation.
    """
    raw = meta.get("next stage")
    norm = _norm_stage(raw) if raw else None

    if norm and norm in FORBIDDEN_NEXT_STAGE:
        return deny(
            "PMO-INTENT-003",
            "PMO Intent guard: Next Stage '{}' skips ahead. Intent must hand "
            "off to {} - not directly to Specifications, Development or "
            "Build.".format(raw.strip(), REQUIRED_NEXT_STAGE),
        )

    if finalizing:
        if not norm:
            return deny(
                "PMO-INTENT-003",
                "PMO Intent guard: Next Stage is not set. A finalised Intent "
                "must declare Next Stage: {}.".format(REQUIRED_NEXT_STAGE),
            )
        if norm not in ACCEPTED_NEXT_STAGE:
            return deny(
                "PMO-INTENT-003",
                "PMO Intent guard: Next Stage '{}' is invalid. A finalised "
                "Intent must declare Next Stage: {}.".format(
                    raw.strip(), REQUIRED_NEXT_STAGE
                ),
            )
    return None


# --------------------------------------------------------------------------- #
# FR / NFR detection
# --------------------------------------------------------------------------- #

def find_fr_nfr(content):
    """Return sorted unique FR-XXX / NFR-XXX tokens found in `content`."""
    return sorted(set(_FR_NFR_RE.findall(content or "")))


def validate_no_fr_nfr(content):
    """PMO-INTENT-004 - FR-XXX / NFR-XXX are reserved for specs.md."""
    hits = find_fr_nfr(content)
    if hits:
        return deny(
            "PMO-INTENT-004",
            "PMO Intent guard: Intent must not define specification "
            "identifiers {}. FR-XXX / NFR-XXX are reserved for specs.md. "
            "Intent may use INT-REQ-XXX, INT-OOS-XXX, ASM-XXX, OPEN-XXX, "
            "CONFLICT-XXX, RISK-XXX, SRC-XXX.".format(", ".join(hits)),
        )
    return None


# --------------------------------------------------------------------------- #
# Identifier-definition validation
# --------------------------------------------------------------------------- #

def _definition_regex(namespace):
    return re.compile(
        r"^[\s>|`*_+\-#.0-9\[\]]*(" + re.escape(namespace) + r"-\d+)(?![A-Za-z0-9-])",
        re.MULTILINE,
    )


def identifier_definitions(content, namespace, scope_text=None):
    """Count line-leading definitions of `namespace` identifiers.

    A "definition" is an identifier at the start of a line (after list / table /
    heading markup). A mention in prose is a reference and is ignored.
    """
    counts = {}
    text = scope_text if scope_text is not None else (content or "")
    for match in _definition_regex(namespace).finditer(text):
        ident = match.group(1)
        counts[ident] = counts.get(ident, 0) + 1
    return counts


def validate_no_duplicate_definitions(content):
    """PMO-INTENT-005 - block a second definition inside the same namespace.

    Definitions are counted within each namespace's owning section so that
    cross-references from other sections (e.g. the validation summary) are not
    mistaken for redefinitions. If the owning section is absent (early DRAFT),
    the whole document is scanned instead.
    """
    duplicates = []
    for namespace, owning in NS_OWNING_SECTION.items():
        scope = section_body(content, owning)
        counts = identifier_definitions(content, namespace, scope_text=scope)
        duplicates.extend(ident for ident, n in counts.items() if n > 1)
    if duplicates:
        return deny(
            "PMO-INTENT-005",
            "PMO Intent guard: duplicate identifier definition(s): {}. Each "
            "identifier must be defined once within its namespace; repeated "
            "references elsewhere are fine.".format(
                ", ".join(sorted(set(duplicates)))
            ),
        )
    return None


# --------------------------------------------------------------------------- #
# OPEN-item validation  (PMO-INTENT-007 / PMO-INTENT-013)
# --------------------------------------------------------------------------- #
#
# An OPEN item is a governed record. It may stay unresolved when the Intent is
# validated - Intent exists partly to carry open questions into Requirement
# Gathering - but it must be fully managed and its "Required Before" gate must
# resolve to a known workflow stage.
#
# The parser finds the *logical* boundary of each OPEN record (a Markdown table
# row, an OPEN subsection, or a multi-line block) instead of relying on a fixed
# lookahead, so a correctly governed record of any length or layout is
# accepted. Repeated references to an OPEN id are not new definitions.

_OPEN_LINE_RE = re.compile(r"^[\s>|`*_+\-#.0-9\[\]]*(OPEN-\d+)(?![A-Za-z0-9-])")


def _heading_level(line):
    """Markdown ATX heading level (1-6) for `line`, or 0 when it is not one."""
    match = re.match(r"^\s{0,3}(#{1,6})\s+\S", line or "")
    return len(match.group(1)) if match else 0


def open_questions_block(content):
    """Text of the '## Open Questions' section.

    Runs from the section heading to the next level-1/level-2 heading, so
    `### sub-sections` inside Open Questions are kept. Returns "" when absent.
    """
    lines = (content or "").splitlines()
    start = None
    for i, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match and "open questions" in _norm_heading(match.group(1)):
            start = i
            break
    if start is None:
        return ""
    body = []
    for j in range(start + 1, len(lines)):
        level = _heading_level(lines[j])
        if level and level <= 2:
            break
        body.append(lines[j])
    return "\n".join(body)


def _split_table_row(line):
    """Cells of a Markdown table row, outer pipes stripped, each trimmed."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [cell.strip() for cell in s.split("|")]


def _is_table_line(line):
    return line.strip().startswith("|")


def _is_separator_row(line):
    s = line.strip()
    return bool(s) and "-" in s and re.match(r"^\|?[\s:\-|]+\|?$", s) is not None


def _table_header_for(lines, row_index):
    """Header row of the contiguous table block that contains `row_index`.

    Walks the whole block (no fixed line budget). The header is the row just
    above the `|---|` separator, or the first row of the block when there is no
    separator. Returns None when `row_index` is itself that header row.
    """
    start = row_index
    while start - 1 >= 0 and _is_table_line(lines[start - 1]):
        start -= 1
    end = row_index
    while end + 1 < len(lines) and _is_table_line(lines[end + 1]):
        end += 1
    sep_pos = next((k for k in range(start, end + 1)
                    if _is_separator_row(lines[k])), None)
    header_idx = sep_pos - 1 if (sep_pos is not None and sep_pos - 1 >= start) else start
    if header_idx == row_index:
        return None
    return lines[header_idx]


def _column_index_map(header_line):
    """Map {'question','owner','blocking','required_before'} -> column index."""
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
                or "resolution stage" in cell or "required resolution" in cell
                or "resolve by" in cell or "required by stage" in cell):
            cmap.setdefault("required_before", idx)
    return cmap


_LABEL_QUESTION_RE = re.compile(
    r"(?:^|\n|\|)\s*[\-*>#\s]*\**\s*question\s*\**\s*[:|]\s*([^\n|]+)", re.I)
_LABEL_OWNER_RE = re.compile(
    r"(?:^|\n|\|)\s*[\-*>#\s]*\**\s*owner\s*\**\s*[:|]\s*([^\n|]+)", re.I)
_LABEL_BLOCKING_RE = re.compile(
    r"\bblock(?:ing|er)?\b\s*\**\s*[:|]?\s*\**\s*(yes|no)\b", re.I)
_LABEL_REQUIRED_BEFORE_RE = re.compile(
    r"(?:required\s*[-_ ]?before|resolution\s*stage|required\s*resolution|"
    r"resolve\s*by|required\s*by\s*stage)\s*\**\s*[:|]?\s*\**\s*"
    r"([A-Za-z][A-Za-z0-9 /_&-]{1,60})", re.I)


def _record_fields(text, header_line, row_cells):
    """(question, owner, blocking, required_before_raw) for one OPEN record.

    Table columns are used when a header can be mapped; anything still missing
    is looked for as a `Label: value` line anywhere in the record text.
    """
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
            blocking = "present"          # recorded but not YES/NO -> fails below

    if required_before is None:
        m = _LABEL_REQUIRED_BEFORE_RE.search(text)
        if m and m.group(1).strip():
            required_before = m.group(1).strip()

    return question, owner, blocking, required_before


def parse_open_records(content):
    """One dict per OPEN definition inside the Open Questions section.

    Keys: id, question, owner, blocking, required_before_raw, stage.
    `stage` is the canonical workflow stage or None when unrecognised. A later
    line-leading repeat of an id is a reference, not a new definition.
    """
    block = open_questions_block(content)
    if not block:
        return []
    lines = block.splitlines()
    seen = set()
    records = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        match = _OPEN_LINE_RE.match(line)
        if not match:
            i += 1
            continue
        ident = match.group(1)
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
                if _OPEN_LINE_RE.match(lines[j]):
                    break
                lv = _heading_level(lines[j])
                if lv and (not level or lv <= level):
                    break
                buf.append(lines[j])
                j += 1
            text = "\n".join(buf)
            nxt = j

        question, owner, blocking, rb_raw = _record_fields(
            text, header_line, row_cells
        )
        records.append({
            "id": ident,
            "question": question,
            "owner": owner,
            "blocking": blocking,
            "required_before_raw": rb_raw,
            "stage": normalize_stage(rb_raw) if rb_raw else None,
        })
        i = nxt
    return records


def validate_open_items(content):
    """PMO-INTENT-007 - every OPEN definition must be a fully managed record.

    Unresolved is fine; unmanaged is not. Each record must carry a Question, an
    Owner, a Blocking status of exactly YES/NO, and a Required Before value that
    resolves to a known workflow stage. Formatting and length do not matter.
    """
    for rec in parse_open_records(content):
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
                "PMO-INTENT-007",
                "PMO Intent guard: open item {ident} is not fully managed - "
                "missing {fields}. An unresolved OPEN item is allowed, but each "
                "must record Question, Owner, Blocking status (YES/NO) and "
                "Required Before (a workflow stage).".format(
                    ident=ident, fields=", ".join(missing)
                ),
            )
        if str(rec["blocking"]).strip().upper() not in ("YES", "NO"):
            return deny(
                "PMO-INTENT-007",
                "PMO Intent guard: open item {ident} has an invalid Blocking "
                "value '{value}' - it must be exactly YES or NO.".format(
                    ident=ident, value=rec["blocking"]
                ),
            )
        if rec["stage"] is None:
            return deny(
                "PMO-INTENT-007",
                "PMO Intent guard: open item {ident} has an unrecognised "
                "Required Before stage '{value}'. Use one of: {stages}.".format(
                    ident=ident,
                    value=rec["required_before_raw"],
                    stages=", ".join(WORKFLOW_STAGES),
                ),
            )
    return None


def validate_blocking_open_gate(content):
    """PMO-INTENT-013 - stage-aware blocking for Intent validation.

    A well-formed OPEN item may remain unresolved when the Intent is validated
    as long as its Required Before gate falls later than the point where the
    workflow leaves Intent. Blocking = YES only means "resolve before that
    gate" - it does not freeze every earlier stage.

    The Intent hands off to Requirement Gathering, so an unresolved
    Blocking = YES item blocks validation only when its Required Before gate is
    INTENT_VALIDATION or REQUIREMENT_GATHERING. Items gated at SCOPE_BASELINE or
    later are valid at validation and carried forward.
    """
    offenders = []
    for rec in parse_open_records(content):
        if str(rec["blocking"] or "").strip().upper() != "YES":
            continue
        if rec["stage"] is None:
            continue  # PMO-INTENT-007 already owns an unrecognised stage
        if STAGE_ORDER[rec["stage"]] <= INTENT_EXIT_STAGE_INDEX:
            offenders.append(
                "{id} (Required Before: {stage})".format(
                    id=rec["id"], stage=rec["stage"]
                )
            )
    if offenders:
        return deny(
            "PMO-INTENT-013",
            "PMO Intent guard: the Intent cannot be validated while these "
            "unresolved OPEN item(s) are gated at or before Requirement "
            "Gathering: {}. A Blocking = YES OPEN item whose Required Before "
            "gate is SCOPE_BASELINE or later is valid at Intent validation and "
            "is carried into Requirement Gathering.".format("; ".join(offenders))
        )
    return None


# --------------------------------------------------------------------------- #
# Source Register validation
# --------------------------------------------------------------------------- #

_SRC_ROW_RE = re.compile(r"(SRC-\d+)")
_EXTERNAL_SOURCE_HINTS = (
    "transcript", "email", "contract", "proposal", "requirement", "loe",
    "handover", "hand-over", "document", "spec", "brief", "deck", "call",
    "meeting", "notes", "slack", "figma", "jira", "confluence", "scope",
    "kickoff", "kick-off", "workshop", "interview", "sow", "rfp", "attachment",
    "recording", "whitepaper", "sheet", "backlog", "ticket",
)
_PLACEHOLDER_VALUES = {"tbd", "n/a", "na", "none", "-", "--", "pending", "xxx", "todo"}


def _looks_external_source(descriptor):
    text = descriptor.strip().lower()
    if len(text) < 3 or text in _PLACEHOLDER_VALUES:
        return False
    mentions_intent = re.search(r"\bintent(\.md)?\b", text) or \
        "this document" in text or "this artifact" in text
    if mentions_intent and not any(h in text for h in _EXTERNAL_SOURCE_HINTS):
        return False
    return True


def validate_source_register(content):
    """PMO-INTENT-006 - a real external source must back the Intent."""
    body = section_body(content, "14. Source Register")
    if body is None:
        return deny(
            "PMO-INTENT-006",
            "PMO Intent guard: intent.md has no '## 14. Source Register' "
            "section. At least one meaningful external project source must be "
            "recorded before the Intent can be validated.",
        )
    descriptors = []
    for line in body.splitlines():
        match = _SRC_ROW_RE.search(line)
        if not match:
            continue
        descriptor = line.replace(match.group(1), " ")
        descriptor = re.sub(r"[|*_`>#\-]+", " ", descriptor)
        descriptor = re.sub(r"\s+", " ", descriptor).strip()
        descriptors.append(descriptor)
    if not descriptors:
        return deny(
            "PMO-INTENT-006",
            "PMO Intent guard: the Source Register contains no SRC-XXX "
            "entries. At least one meaningful external project source is "
            "required; the Intent itself does not count as evidence.",
        )
    if not any(_looks_external_source(d) for d in descriptors):
        return deny(
            "PMO-INTENT-006",
            "PMO Intent guard: the Source Register has no meaningful external "
            "source. Record at least one real project source (transcript, "
            "email, contract, proposal, requirements doc, handover, ...). The "
            "Intent itself must not count as source evidence.",
        )
    return None


# --------------------------------------------------------------------------- #
# Project-identity validation
# --------------------------------------------------------------------------- #

def _clean(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def validate_project_identity(meta, config):
    """PMO-INTENT-010 - identity must match `.pmo/project-config.yaml`.

    `.pmo/project-config.yaml` is the only authority. Conversation memory is
    never consulted. Fields absent on either side are skipped.
    """
    if not isinstance(config, dict):
        return None
    project = config.get("project")
    if not isinstance(project, dict):
        return None

    checks = (
        ("project id", project.get("id"), "Project ID"),
        ("project", project.get("name"), "Project Name"),
        ("client", project.get("client"), "Client"),
    )
    for meta_key, cfg_value, label in checks:
        doc_value = _clean(meta.get(meta_key))
        cfg_value = _clean(cfg_value)
        if not doc_value or not cfg_value:
            continue
        if doc_value.casefold() != cfg_value.casefold():
            return deny(
                "PMO-INTENT-010",
                "PMO Intent guard: Intent {label} '{doc}' does not match "
                "'.pmo/project-config.yaml' ('{cfg}'). Fix the mismatch - the "
                "project configuration is the authority.".format(
                    label=label, doc=doc_value, cfg=cfg_value
                ),
            )
    return None


# --------------------------------------------------------------------------- #
# Immutability / PM-approval validation
# --------------------------------------------------------------------------- #

def validate_immutable(existing_status):
    """PMO-INTENT-009 - a VALIDATED Intent cannot be rewritten in place."""
    if existing_status == "VALIDATED":
        return deny(
            "PMO-INTENT-009",
            "PMO Intent guard: intent.md is VALIDATED and immutable. Silent "
            "Write/Edit changes are blocked - later changes must go through "
            "Scope, Feedback, Decision or Change Request governance.",
        )
    return None


def load_intent_approval(root):
    """Return (record_dict, error_text).

    `record_dict` is the parsed `.pmo/approvals/intent-approval.yaml` mapping,
    or None when the file is missing / unreadable / not a mapping (with a short
    reason in `error_text`).
    """
    path = os.path.join(root, INTENT_APPROVAL_RELPATH)
    if not os.path.isfile(path):
        return None, "no approval record at '{}'".format(INTENT_APPROVAL_RELPATH)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = parse_simple_yaml(handle.read())
    except Exception as exc:
        return None, "approval record could not be read ({})".format(exc)
    if not isinstance(data, dict) or not data:
        return None, "approval record is malformed (not a mapping)"
    return data, None


def _deny_pm_approval(detail):
    return deny(
        "PMO-INTENT-011",
        "PMO Intent guard: moving the Intent to VALIDATED requires an explicit "
        "PM approval record at '{path}' - {detail}. Document completeness, a "
        "Claude recommendation, or a passing hook check are not PM approval. "
        "The record is created only when the PM explicitly approves the Intent "
        "in the PMO workflow; the hook never writes it.".format(
            path=INTENT_APPROVAL_RELPATH, detail=detail
        ),
    )


def validate_pm_approval(existing_status, new_status, meta, root):
    """PMO-INTENT-011 - a VALIDATED transition needs a matching PM approval.

    Only Claude-driven self-promotion is blocked: the move to VALIDATED is
    allowed (subject to every other Intent rule) when
    `.pmo/approvals/intent-approval.yaml` exists and records an explicit PM
    decision for *this* artifact and *this* Intent version.
    """
    if new_status != "VALIDATED":
        return None
    if existing_status not in (None, "DRAFT", "PM_REVIEWED"):
        # Already VALIDATED - immutability (PMO-INTENT-009) owns this case.
        return None

    record, error = load_intent_approval(root)
    if record is None:
        return _deny_pm_approval(error)

    decision = _clean(record.get("decision"))
    if not decision or decision.upper() != APPROVAL_REQUIRED_DECISION:
        return _deny_pm_approval(
            "decision must be {}".format(APPROVAL_REQUIRED_DECISION)
        )

    source = _clean(record.get("approval_source"))
    if not source or source.upper() != APPROVAL_REQUIRED_SOURCE:
        return _deny_pm_approval(
            "approval_source must be {}".format(APPROVAL_REQUIRED_SOURCE)
        )

    artifact = _clean(record.get("artifact"))
    artifact_norm = os.path.normpath(artifact).replace(os.sep, "/") if artifact else None
    if artifact_norm != INTENT_POSIX:
        return _deny_pm_approval(
            "artifact must be '{}'".format(INTENT_POSIX)
        )

    approved_by = _clean(record.get("approved_by"))
    if not approved_by:
        return _deny_pm_approval("approved_by must be a non-empty PM name")

    record_version = record.get("version")
    record_version = str(record_version).strip() if record_version is not None else ""
    intent_version = _clean(meta.get("intent version"))
    if not intent_version:
        return _deny_pm_approval(
            "the Intent has no 'Intent Version' to match against the approval "
            "record"
        )
    if not record_version:
        return _deny_pm_approval("version must match the Intent version being "
                                 "validated")
    if record_version != intent_version:
        return _deny_pm_approval(
            "approval is for version '{rec}', but the Intent being validated is "
            "version '{doc}'".format(rec=record_version, doc=intent_version)
        )

    return None


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
# Resulting-content reconstruction for Write / Edit / MultiEdit
# --------------------------------------------------------------------------- #

def resulting_content(tool_name, tool_input, existing):
    """Best-effort reconstruction of intent.md after the pending operation."""
    if tool_name == "Write":
        content = tool_input.get("content")
        return content if isinstance(content, str) else ""

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
# Controlled validation
# --------------------------------------------------------------------------- #

def full_schema_validation(content, meta, root, status=None):
    """Structural / workflow / evidence checks applied at finalisation.

    `status` is the (normalised) Intent Status the operation moves to. The
    stage-aware OPEN blocker (PMO-INTENT-013) applies only when that status is
    VALIDATED; every other check applies to any finalisation.
    """
    if not os.path.isfile(config_path_for(root)):
        return deny(
            "PMO-INTENT-001",
            "PMO Intent guard: '.pmo/project-config.yaml' does not exist. "
            "The project is not initialised, so the Intent cannot be "
            "finalised. Run project initialisation first.",
        )

    for check in (
        validate_sections(content),
        validate_doc_control_fields(meta),
        validate_next_stage(meta, finalizing=True),
        validate_source_register(content),
        validate_open_items(content),
    ):
        if check is not None:
            return check

    if status == "VALIDATED":
        blocked = validate_blocking_open_gate(content)
        if blocked is not None:
            return blocked
    return None


def _light_checks(content, meta, root):
    """Deterministic checks that apply to every Intent edit, DRAFT included."""
    config = load_project_config(root)
    for check in (
        validate_status_value(_norm_status(meta.get("status"))),
        validate_no_fr_nfr(content),
        validate_no_duplicate_definitions(content),
        validate_next_stage(meta, finalizing=False),
        validate_project_identity(meta, config),
    ):
        if check is not None:
            return check
    return None


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
