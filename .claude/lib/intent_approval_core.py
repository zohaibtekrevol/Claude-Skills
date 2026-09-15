"""PMO intent_approval_core - shared deterministic governance and
orchestration primitives for the PMO Intent artifact and its governed PM
Approval transaction.

Why this module exists
-----------------------
Two surfaces need to agree, byte-for-byte, on what a valid Intent write, a
valid PM-approval transaction marker, and a valid completed approval look
like:

* ``.claude/hooks/intent-schema-guard.py`` - the Claude Code PreToolUse hook
  that governs every Write/Edit Claude itself performs against
  ``docs/pmo/intent/intent.md``.
* ``.claude/scripts/intent-approval-recorder.py`` - the deterministic
  CLI/orchestrator that records an explicit PM approval as a single atomic
  transaction (begin / status / validate / finalize), performing the final
  multi-part write directly (outside the Write/Edit tool chain entirely).

This module is the single implementation of the deterministic rules both
depend on, so "guard says PASS, CLI says FAIL" (or vice versa) for the same
on-disk state cannot happen by construction - both call the same functions.
The guard remains a thin PreToolUse shim over this module; the CLI is a
second, independent consumer with its own I/O (argparse, direct file
writes) built on the same core. This mirrors the established pattern in
this codebase (``artifact_publish_core.py`` / ``artifact-publish-guard.py``
/ ``artifact-publisher.py``; ``change_request_incorporation_core.py`` /
``change-request-governance-guard.py`` / ``change-request-incorporator.py``).

Root cause this module exists to close
-----------------------------------------
A PM approval was previously recorded as two independent, sequential
Write/Edit tool calls: (1) flip Document Control ``Status: DRAFT ->
VALIDATED``, (2) update Section 16 / Acceptance to match. Step (1)
correctly and immediately made ``intent.md`` immutable under
``PMO-INTENT-009`` (a VALIDATED Intent cannot be rewritten in place); step
(2) was then correctly rejected by that same rule. The result was an
internally inconsistent canonical artifact: Document Control said
VALIDATED while Section 16 still said "not approved". The guard behaved
correctly at each individual step - the defect was the absence of an
atomic operation boundary around "record PM approval" as a whole. This
module supplies that boundary: ``apply_approval_to_intent`` always produces
the Document Control Status flip and the Section 16 update together, in one
computed string, so there is no reachable intermediate state with one but
not the other; ``PMO-INTENT-014`` (see ``validate_acceptance_consistency``)
additionally denies, at the guard level, any Write/Edit that would produce
the inconsistent state directly, independent of whether the orchestrator is
used.

Architectural boundary this module enforces
-----------------------------------------------
Nothing here ever invents Intent substance - Client Vision, requirements,
assumptions, open questions, source register entries, or any other
semantic content. This module owns exactly two things: (1) the same
mechanical/structural validation rules ``intent-schema-guard.py`` always
enforced (schema, workflow, immutability, identity, PM-approval-record
matching), moved here so both call sites share one implementation, and (2)
TRANSACTION EXECUTION / RECONCILIATION for the PM-approval operation - the
Document Control Status field and the Section 16 Acceptance block are
mechanically derived from explicit PM-supplied fields (approved_by,
decision_date, approval_statement) using a fixed template; every other
byte of the document (Sections 1-15) is passed through unchanged.

Security boundary
-------------------
The CLI runs via Bash, entirely outside Claude Code's PreToolUse hook
system - hooks only ever see Claude's own Write/Edit/MultiEdit tool calls,
never a subprocess's direct file I/O. The existence of a transaction marker
is therefore NOT itself authorization for anything: every mutating
operation this module performs (``finalize_transaction``) independently
re-derives the candidate content from the CURRENT on-disk Intent and
re-runs the full deterministic validation (``full_schema_validation``,
``validate_acceptance_consistency``, and - by explicit, documented, always
``existing_status=None`` design - ``validate_pm_approval``) before writing
a single byte, and fails closed on any exception. There is no Bash-side
shortcut around governance here - the same rules apply whether the write is
attempted by Claude through a hook or by this CLI directly.

Marker schema - .pmo/intent-approval-transaction.json
-----------------------------------------------------------------------------
See ``INTENT_APPROVAL_MARKER_REQUIRED_FIELDS`` below for the exact field
list; ``build_marker_data`` constructs it from a ``run_begin_preconditions``
plan. Status model is the same three states as ``feedback-transaction.json``
/ ``change-request-transaction.json`` (existing precedent): ``ACTIVE`` /
``RECONCILING`` / ``RECOVERY_REQUIRED`` - no additional states introduced.
The marker is purely a *runtime* transaction artifact: it is written under
``.pmo/`` (already untracked - see the repository's ``.gitignore`` rule for
``.pmo/``), is always removed on a clean ``finalize``, and must never be
treated as permanent framework or project content.

Error namespace
-----------------
Two disjoint namespaces are emitted by this module:

* ``PMO-INTENT-001`` .. ``PMO-INTENT-013`` - the existing, unchanged Intent
  guard invariants (schema / workflow / immutability / identity / PM
  approval / OPEN-item governance). These functions moved here verbatim
  from ``intent-schema-guard.py`` so the guard and this module's
  orchestration functions apply the identical rules; their codes and
  meanings are unchanged.
* ``PMO-INTENT-014`` - new: ``ACCEPTANCE_SECTION_INCONSISTENT``. Denies a
  Write/Edit that would set Document Control ``Status: VALIDATED`` while
  Section 16 / Acceptance is missing, stale, or inconsistent with
  ``.pmo/approvals/intent-approval.yaml``.
* ``PMO-INTENT-APPROVAL-001`` .. ``PMO-INTENT-APPROVAL-015`` (see
  ``PMO_INTENT_APPROVAL_CODES``) - new, orchestration-specific conditions
  (BEGIN preconditions, transaction conflicts, baseline drift,
  reconciliation/partial-transaction states, idempotency). Never reuses a
  ``PMO-INTENT-0XX`` code for a different meaning.

Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import hashlib
import json
import os
import re


# --------------------------------------------------------------------------- #
# Constants - moved verbatim from intent-schema-guard.py
# --------------------------------------------------------------------------- #

INTENT_RELPATH = os.path.join("docs", "pmo", "intent", "intent.md")
INTENT_POSIX = "docs/pmo/intent/intent.md"
CONFIG_RELPATH = os.path.join(".pmo", "project-config.yaml")
APPROVALS_RELDIR = os.path.join(".pmo", "approvals")
INTENT_APPROVAL_RELPATH = os.path.join(".pmo", "approvals", "intent-approval.yaml")
INTENT_APPROVAL_POSIX = ".pmo/approvals/intent-approval.yaml"

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

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Decision({!r}, {!r})".format(self.code, self.message)


def deny(code, message):
    """Build a deny Decision (kept as a value so controls stay testable)."""
    return Decision(code, message)


def allow():
    return None


# --------------------------------------------------------------------------- #
# Minimal YAML subset parser (stdlib only) - just enough for project-config
# and the approval record.
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
# Filesystem helpers
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


# Backwards-compatible alias (the CR/feedback cores name the same helper
# `locate_project_root`; the Intent guard historically named it
# `project_root`). Both names are kept so every existing caller/importer
# keeps working unchanged.
locate_project_root = project_root


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


def write_text(path, text):
    """Create parent directories as needed, then write `text` verbatim."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def sha256_of_text(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def sha256_of_file(path):
    text = read_text(path)
    if text is None:
        return None
    return sha256_of_text(text)


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

INTENT_EXIT_STAGE_INDEX = STAGE_ORDER["REQUIREMENT_GATHERING"]

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


def _section_line_range(content, heading_title):
    """(start, end) line indices (end exclusive) of the heading title's own
    body, i.e. the same span `section_body` returns - as raw line indices
    into `content.splitlines()`, so callers can splice/replace it. Returns
    None when the heading is absent."""
    target = _norm_heading(heading_title)
    lines = content.splitlines()
    heading_idx = None
    for i, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match and _norm_heading(match.group(1)) == target:
            heading_idx = i
            break
    if heading_idx is None:
        return None
    end = len(lines)
    for j in range(heading_idx + 1, len(lines)):
        if _HEADING_RE.match(lines[j]):
            end = j
            break
    return heading_idx + 1, end


def replace_section_body(content, heading_title, new_body_text):
    """Replace the body of `heading_title` (everything after the heading
    line up to, but not including, the next `##`+ heading or EOF) with
    `new_body_text`. Every other line - including every other section - is
    passed through byte-for-byte unchanged. Returns (new_content, replaced).
    """
    rng = _section_line_range(content, heading_title)
    if rng is None:
        return content, False
    start, end = rng
    lines = content.splitlines()
    new_lines = lines[:start] + [""] + new_body_text.rstrip("\n").splitlines() + [""] + lines[end:]
    return "\n".join(new_lines), True


_DOC_CONTROL_FIELD_LINE_RE_CACHE = {}


def _doc_control_field_line_regex(label):
    if label in _DOC_CONTROL_FIELD_LINE_RE_CACHE:
        return _DOC_CONTROL_FIELD_LINE_RE_CACHE[label]
    core = r"\s+".join(re.escape(part) for part in label.split())
    pattern = re.compile(
        r"^([ \t>*\-+|]*\**\s*" + core + r"\s*\**\s*[:|]\s*\**\s*)"
        r"(.+?)"
        r"(\s*\**\s*\|?\s*)$",
        re.IGNORECASE | re.MULTILINE,
    )
    _DOC_CONTROL_FIELD_LINE_RE_CACHE[label] = pattern
    return pattern


def set_doc_control_field(content, label, new_value):
    """Replace a single Document Control field's value in place, preserving
    whatever list/table/bold markup surrounds it (bullet-list style
    `- **Status:** DRAFT` and single-line table style `| Status | DRAFT |`
    are both supported, matching every layout `_find_field` can read).
    Returns (new_content, replaced_bool); replaces only the FIRST match so a
    field name that also appears in prose elsewhere is never touched.
    """
    pattern = _doc_control_field_line_regex(label)

    def _repl(match):
        return match.group(1) + new_value + match.group(3)

    new_content, n = pattern.subn(_repl, content, count=1)
    return new_content, n == 1


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

    `existing_status` is the status to treat the artifact as being promoted
    *from*. The guard always passes the real on-disk status (so an already
    VALIDATED artifact is correctly left to PMO-INTENT-009 immutability
    instead). The Intent-approval orchestrator (`intent_approval_core`'s own
    transaction functions) always passes `None` here by deliberate design,
    regardless of the artifact's actual on-disk status: its job includes
    *repairing* an already-VALIDATED-but-inconsistent artifact (the exact
    defect this module exists to close - see the module docstring), so it
    must independently re-verify the approval record matches even when
    on-disk status already reads VALIDATED.
    """
    if new_status != "VALIDATED":
        return None
    if existing_status not in (None, "DRAFT", "PM_REVIEWED"):
        # Already VALIDATED - immutability (PMO-INTENT-009) owns this case
        # for the ordinary guard path. (See docstring above for why the
        # orchestrator never relies on this early-return.)
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
# PMO-INTENT-014 - Acceptance-section / approval-record consistency
# --------------------------------------------------------------------------- #

def _acceptance_fields(content):
    """(decision, decision_date, approved_by, approval_evidence) from the
    Section 16 / Acceptance body, or (None, None, None, None) if absent."""
    body = section_body(content, "16. Acceptance")
    if body is None:
        return None, None, None, None
    return (
        _find_field(body, "Decision"),
        _find_field(body, "Decision Date"),
        _find_field(body, "Approved By"),
        _find_field(body, "Approval Evidence"),
    )


def validate_acceptance_consistency(content, meta, root, record_override=None):
    """PMO-INTENT-014 - a Write/Edit that sets Status: VALIDATED must
    already contain a Section 16 / Acceptance block that is complete and
    consistent with `.pmo/approvals/intent-approval.yaml` IN THE SAME
    WRITE. This is the deterministic guard invariant that closes the defect
    this module exists to fix: it makes the exact previously-reachable bad
    state (Status VALIDATED, Acceptance still "pending") structurally
    unreachable through the normal Write/Edit tool chain, independent of
    whether the intent-approval-recorder orchestrator is used.

    `record_override`, when given, is used instead of reading
    `.pmo/approvals/intent-approval.yaml` from disk - used by the
    orchestrator to pre-validate a CANDIDATE approval record before it has
    been written anywhere.
    """
    decision, decision_date, approved_by, evidence = _acceptance_fields(content)
    missing = []
    if not decision:
        missing.append("Decision")
    if not decision_date:
        missing.append("Decision Date")
    if not approved_by:
        missing.append("Approved By")
    if not evidence:
        missing.append("Approval Evidence")
    if missing:
        return deny(
            "PMO-INTENT-014",
            "PMO Intent guard: Status is VALIDATED but Section 16 / "
            "Acceptance is incomplete - missing {}. The Acceptance section "
            "must be updated to record the approval in the SAME write that "
            "sets Status: VALIDATED; a separate follow-up edit is blocked by "
            "PMO-INTENT-009 once this write completes.".format(
                ", ".join(missing)
            ),
        )
    if _norm_status(decision) != APPROVAL_REQUIRED_DECISION:
        return deny(
            "PMO-INTENT-014",
            "PMO Intent guard: Section 16 Acceptance 'Decision' is '{}', not "
            "APPROVED, while Status is being set to VALIDATED.".format(
                decision
            ),
        )

    if record_override is not None:
        record, error = record_override, None
    else:
        record, error = load_intent_approval(root)
    if record is None:
        return deny(
            "PMO-INTENT-014",
            "PMO Intent guard: Section 16 Acceptance reports the Intent as "
            "approved, but no matching approval record could be read - "
            "{}.".format(error),
        )

    record_approved_by = _clean(record.get("approved_by"))
    if not record_approved_by or record_approved_by.casefold() != approved_by.strip().casefold():
        return deny(
            "PMO-INTENT-014",
            "PMO Intent guard: Section 16 'Approved By' ('{}') does not match "
            "the approval record's approved_by ('{}').".format(
                approved_by, record_approved_by
            ),
        )

    record_version = record.get("version")
    record_version = str(record_version).strip() if record_version is not None else ""
    intent_version = _clean(meta.get("intent version"))
    if not intent_version or not record_version or record_version != intent_version:
        return deny(
            "PMO-INTENT-014",
            "PMO Intent guard: approval record version ('{}') does not match "
            "the Intent's own 'Intent Version' ('{}').".format(
                record_version, intent_version
            ),
        )

    return None


# --------------------------------------------------------------------------- #
# Controlled validation - the same gate the guard and the orchestrator share
# --------------------------------------------------------------------------- #

def full_schema_validation(content, meta, root, status=None,
                          acceptance_record_override=None):
    """Structural / workflow / evidence checks applied at finalisation.

    `status` is the (normalised) Intent Status the operation moves to. The
    stage-aware OPEN blocker (PMO-INTENT-013) and the Acceptance-consistency
    check (PMO-INTENT-014) apply only when that status is VALIDATED; every
    other check applies to any finalisation (DRAFT -> PM_REVIEWED too).

    `acceptance_record_override`, when given, is forwarded to
    `validate_acceptance_consistency` instead of reading
    `.pmo/approvals/intent-approval.yaml` from disk. The guard's own
    Write/Edit path never passes this (the real Write/Edit path requires
    the approval record to already exist on disk, enforced earlier by
    PMO-INTENT-011); the Intent-approval orchestrator's `begin` precondition
    check passes its CANDIDATE record here, since at `begin` time that
    record has not been written yet.
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
        blocked = validate_acceptance_consistency(
            content, meta, root, record_override=acceptance_record_override)
        if blocked is not None:
            return blocked
    return None


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


# =========================================================================== #
# Intent Approval Transaction - orchestration primitives
# =========================================================================== #

INTENT_APPROVAL_MARKER_RELPATH_PARTS = (".pmo", "intent-approval-transaction.json")

INTENT_APPROVAL_MARKER_REQUIRED_FIELDS = (
    "transaction_type", "transaction_id", "project_id", "artifact_path",
    "intent_version", "started_at", "operation", "status",
    "baseline_intent_hash", "approved_by", "decision_date",
)
ALLOWED_APPROVAL_OPERATIONS = {"RECORD_APPROVAL"}
ALLOWED_APPROVAL_MARKER_STATUSES = {"ACTIVE", "RECONCILING", "RECOVERY_REQUIRED"}
OPEN_APPROVAL_MARKER_STATUSES = {"ACTIVE", "RECONCILING"}
APPROVAL_MARKER_STATUS_TRANSITIONS = {
    "ACTIVE": {"ACTIVE", "RECONCILING", "RECOVERY_REQUIRED"},
    "RECONCILING": {"RECONCILING", "ACTIVE", "RECOVERY_REQUIRED"},
    "RECOVERY_REQUIRED": {"RECOVERY_REQUIRED", "ACTIVE", "RECONCILING"},
}

_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PMO_INTENT_APPROVAL_CODES = {
    "PMO-INTENT-APPROVAL-001": "PROJECT_NOT_INITIALIZED",
    "PMO-INTENT-APPROVAL-002": "INTENT_NOT_FOUND",
    "PMO-INTENT-APPROVAL-003": "ALREADY_APPROVED",
    "PMO-INTENT-APPROVAL-004": "INTENT_STATUS_NOT_APPROVABLE",
    "PMO-INTENT-APPROVAL-005": "INTENT_CONTENT_INVALID",
    "PMO-INTENT-APPROVAL-006": "APPROVAL_INPUT_INVALID",
    "PMO-INTENT-APPROVAL-007": "TRANSACTION_ALREADY_ACTIVE",
    "PMO-INTENT-APPROVAL-008": "MARKER_INVALID",
    "PMO-INTENT-APPROVAL-009": "MARKER_WRONG_PROJECT",
    "PMO-INTENT-APPROVAL-010": "NO_ACTIVE_TRANSACTION",
    "PMO-INTENT-APPROVAL-011": "BASELINE_DRIFT",
    "PMO-INTENT-APPROVAL-012": "APPROVAL_EVIDENCE_WRITE_FAILED",
    "PMO-INTENT-APPROVAL-013": "INTENT_WRITE_FAILED",
    "PMO-INTENT-APPROVAL-014": "POST_WRITE_VERIFICATION_FAILED",
    "PMO-INTENT-APPROVAL-015": "INTERNAL_ERROR",
    "PMO-INTENT-APPROVAL-016": "EXISTING_APPROVAL_IDENTITY_MISMATCH",
}


# --------------------------------------------------------------------------- #
# Deterministic content rendering (no free-form authorship - fixed template)
# --------------------------------------------------------------------------- #

def render_acceptance_body(approved_by, decision_date, version, next_stage=None):
    """The exact Section 16 / Acceptance body text for an APPROVED Intent.
    Used by BOTH the orchestrator (to build the write) and available to any
    caller that needs to know what a *consistent* Acceptance section looks
    like. Deterministic - the same inputs always render the same text, so
    the guard's PMO-INTENT-014 check and this renderer can never drift
    apart in practice."""
    stage = next_stage or REQUIRED_NEXT_STAGE
    return (
        "- **Decision:** APPROVED\n"
        "- **Decision Date:** {date}\n"
        "- **Approved By:** {by}\n"
        "- **Approval Evidence:** `{evidence_path}` (decision: APPROVED, "
        "approval_source: {source}, artifact: {artifact}, version: {version}, "
        "approved_by: {by})\n"
        "\n"
        "This Intent has been explicitly approved by the Project Manager as "
        "the governed business baseline for proceeding to {stage}. This is "
        "**PM approval only** - it is not client approval, contractual "
        "evidence, or technical evidence. Per governance, this Intent is now "
        "VALIDATED and immutable; further changes must go through Scope, "
        "Feedback, Decision or Change Request governance, not a direct edit "
        "of this file."
    ).format(
        date=decision_date, by=approved_by,
        evidence_path=INTENT_APPROVAL_POSIX, source=APPROVAL_REQUIRED_SOURCE,
        artifact=INTENT_POSIX, version=version, stage=stage,
    )


def _yaml_quote(value):
    return '"{}"'.format(str(value).replace('\\', '\\\\').replace('"', '\\"'))


def render_approval_yaml(approved_by, decision_date, version,
                         approval_statement=None, notes=None):
    """Deterministic serializer for `.pmo/approvals/intent-approval.yaml` -
    stdlib only, no YAML library dependency, mirroring the fixed field order
    every human-authored approval record in this repository already uses."""
    lines = [
        'schema_version: "1.0"',
        "",
        "decision: {}".format(_yaml_quote(APPROVAL_REQUIRED_DECISION)),
        "approval_source: {}".format(_yaml_quote(APPROVAL_REQUIRED_SOURCE)),
        "artifact: {}".format(_yaml_quote(INTENT_POSIX)),
        "version: {}".format(_yaml_quote(version)),
        "approved_by: {}".format(_yaml_quote(approved_by)),
        "approved_at: {}".format(_yaml_quote(decision_date)),
    ]
    if approval_statement:
        lines.append("approval_statement: {}".format(_yaml_quote(approval_statement)))
    if notes:
        lines.append("")
        lines.append("notes: {}".format(_yaml_quote(notes)))
    lines.append("")
    return "\n".join(lines)


def apply_approval_to_intent(content, approved_by, decision_date, version,
                             next_stage=None):
    """The single function that produces BOTH the Document Control
    `Status: VALIDATED` flip and the Section 16 / Acceptance update, in one
    computed string. There is no reachable path through this module that
    produces one without the other - see the module docstring."""
    new_content, ok_status = set_doc_control_field(content, "Status", "VALIDATED")
    if not ok_status:
        return None, False
    body = render_acceptance_body(approved_by, decision_date, version, next_stage)
    new_content, ok_section = replace_section_body(
        new_content, "16. Acceptance", body)
    return new_content, ok_section


# --------------------------------------------------------------------------- #
# Marker parsing / status
# --------------------------------------------------------------------------- #

def parse_intent_approval_marker(text):
    """Returns (data, error). error is None iff structurally/semantically
    valid: required fields present, transaction_type/operation/status from
    their closed enums, started_at timestamp-shaped, decision_date
    date-shaped."""
    try:
        data = json.loads(text)
    except Exception as exc:
        return None, "marker is not valid JSON ({})".format(exc)
    if not isinstance(data, dict):
        return None, "marker JSON must be an object"
    for field in INTENT_APPROVAL_MARKER_REQUIRED_FIELDS:
        if field not in data or data.get(field) in (None, ""):
            return None, "marker is missing required field '{}'".format(field)
    if data.get("transaction_type") != "INTENT_APPROVAL":
        return None, "marker transaction_type must be 'INTENT_APPROVAL'"
    if data.get("operation") not in ALLOWED_APPROVAL_OPERATIONS:
        return None, "marker operation '{}' is not one of {}".format(
            data.get("operation"), sorted(ALLOWED_APPROVAL_OPERATIONS))
    if data.get("status") not in ALLOWED_APPROVAL_MARKER_STATUSES:
        return None, "marker status '{}' is not one of {}".format(
            data.get("status"), sorted(ALLOWED_APPROVAL_MARKER_STATUSES))
    if not _TIMESTAMP_RE.match(str(data.get("started_at"))):
        return None, "marker started_at is not a recognisable ISO 8601 timestamp"
    if not _DATE_RE.match(str(data.get("decision_date"))):
        return None, "marker decision_date is not a recognisable YYYY-MM-DD date"
    if os.path.normpath(str(data.get("artifact_path"))).replace(os.sep, "/") != INTENT_POSIX:
        return None, "marker artifact_path must be '{}'".format(INTENT_POSIX)
    return data, None


def intent_approval_marker_status(root):
    """(state, data, error). state in ABSENT / OPEN / BLOCKED / INVALID /
    WRONG_PROJECT - INVALID and WRONG_PROJECT are kept distinct so callers
    can raise an accurate code, though both otherwise behave as 'not open'.
    Mirrors `cr_marker_status` in change_request_incorporation_core.py."""
    text = read_text(os.path.join(root, *INTENT_APPROVAL_MARKER_RELPATH_PARTS))
    if text is None:
        return "ABSENT", None, None
    data, err = parse_intent_approval_marker(text)
    if err is not None:
        return "INVALID", None, err
    config = load_project_config(root)
    pid = (config or {}).get("project", {}).get("id") if config else None
    if pid and str(data.get("project_id")).strip().upper() != str(pid).strip().upper():
        return "WRONG_PROJECT", data, (
            "marker project_id '{}' does not match the configured "
            "project.id '{}'".format(data.get("project_id"), pid)
        )
    if data.get("status") in OPEN_APPROVAL_MARKER_STATUSES:
        return "OPEN", data, None
    return "BLOCKED", data, None


# --------------------------------------------------------------------------- #
# Transaction lifecycle: begin / reconcile / finalize
# --------------------------------------------------------------------------- #

def _validate_decision_date(value):
    if not value or not _DATE_RE.match(str(value)):
        return False
    return True


def run_begin_preconditions(root, approved_by, decision_date,
                            approval_statement=None, project_id_hint=None):
    """Read-only. Validates every precondition for recording a PM approval
    and, on PASS, returns a `plan` dict describing exactly what `finalize`
    will write - never writes anything itself. Returns (decision, plan);
    `decision` is None iff every check passed.

    This function is intentionally usable whether the on-disk Intent is
    still DRAFT/PM_REVIEWED (the ordinary "record a new approval" case) or
    already VALIDATED-but-inconsistent (the repair case this module exists
    to support - see module docstring): both produce the same candidate
    content via `apply_approval_to_intent`, and `reconcile_transaction`
    below independently confirms which case applies before `finalize`
    writes anything.
    """
    config = load_project_config(root)
    if config is None:
        return deny(
            "PMO-INTENT-APPROVAL-001",
            "'.pmo/project-config.yaml' does not exist - the project is not "
            "initialised.",
        ), None
    project_id = _clean((config.get("project") or {}).get("id"))
    if project_id_hint and project_id and \
            project_id_hint.strip().upper() != project_id.upper():
        return deny(
            "PMO-INTENT-APPROVAL-001",
            "project id hint '{}' does not match project-config.yaml "
            "('{}').".format(project_id_hint, project_id),
        ), None

    if not _clean(approved_by):
        return deny(
            "PMO-INTENT-APPROVAL-006",
            "approved_by must be a non-empty PM name.",
        ), None
    if not _validate_decision_date(decision_date):
        return deny(
            "PMO-INTENT-APPROVAL-006",
            "decision_date '{}' must be an ISO date (YYYY-MM-DD).".format(
                decision_date),
        ), None

    intent_path = os.path.join(root, INTENT_RELPATH)
    content = read_text(intent_path)
    if content is None:
        return deny(
            "PMO-INTENT-APPROVAL-002",
            "'{}' does not exist or is unreadable.".format(INTENT_POSIX),
        ), None

    meta = parse_doc_control(content)
    existing_status = _norm_status(meta.get("status"))
    if existing_status not in ("DRAFT", "PM_REVIEWED", "VALIDATED"):
        return deny(
            "PMO-INTENT-APPROVAL-004",
            "Intent Status '{}' is not approvable by this transaction (only "
            "DRAFT, PM_REVIEWED, or an already-VALIDATED artifact being "
            "repaired for internal consistency, are supported).".format(
                existing_status),
        ), None

    intent_version = _clean(meta.get("intent version"))
    if not intent_version:
        return deny(
            "PMO-INTENT-APPROVAL-005",
            "the Intent has no 'Intent Version' in Document Control.",
        ), None

    identity_check = validate_project_identity(meta, config)
    if identity_check is not None:
        return identity_check, None

    # ----------------------------------------------------------------- #
    # NEW APPROVAL vs RECONCILIATION OF EXISTING APPROVAL
    # ----------------------------------------------------------------- #
    # An approval record that already exists, is structurally valid, and
    # matches this artifact/version (`validate_pm_approval` - the exact
    # rule PMO-INTENT-011 enforces - reused here unchanged, always with
    # `existing_status=None` per its own documented contract) is READ-ONLY
    # source evidence for this transaction. Reconciliation never
    # regenerates, normalizes, rewrites, or reformats it - not even a
    # free-text field such as `notes` - it only repairs the canonical
    # Intent's Acceptance representation FROM it. A transaction only ever
    # creates/writes new approval evidence when no such valid record exists
    # yet (a genuine first-time approval).
    existing_record, _load_err = load_intent_approval(root)
    existing_valid = existing_record is not None and \
        validate_pm_approval(None, "VALIDATED", meta, root) is None

    if existing_valid:
        mode = "RECONCILE_EXISTING"
        record_approved_by = _clean(existing_record.get("approved_by"))
        record_decision_date = _clean(existing_record.get("approved_at"))
        if not record_decision_date:
            return deny(
                "PMO-INTENT-APPROVAL-016",
                "the existing approval record has no 'approved_at' date to "
                "reconcile from.",
            ), None
        # The supplied approved_by/decision_date must describe the SAME,
        # already-recorded decision - this transaction never silently
        # substitutes a different identity, and never silently creates a
        # second decision under a mismatched name/date.
        if record_approved_by.casefold() != approved_by.strip().casefold() or \
                record_decision_date != decision_date:
            return deny(
                "PMO-INTENT-APPROVAL-016",
                "an existing, valid approval record already covers Intent "
                "v{ver} (approved_by='{rec_by}', approved_at='{rec_date}'), "
                "but this call supplied approved_by='{by}', "
                "decision_date='{date}'. Reconciling an existing approval "
                "requires the same approver and date already on record - "
                "supply matching values, or resolve the existing record "
                "manually before recording a genuinely new decision.".format(
                    ver=intent_version, rec_by=record_approved_by,
                    rec_date=record_decision_date, by=approved_by.strip(),
                    date=decision_date,
                ),
            ), None
        effective_approved_by = record_approved_by
        effective_decision_date = record_decision_date
        acceptance_record_for_schema_check = existing_record
    else:
        mode = "NEW_APPROVAL"
        effective_approved_by = approved_by.strip()
        effective_decision_date = decision_date
        acceptance_record_for_schema_check = {
            "decision": APPROVAL_REQUIRED_DECISION,
            "approval_source": APPROVAL_REQUIRED_SOURCE,
            "artifact": INTENT_POSIX,
            "version": intent_version,
            "approved_by": effective_approved_by,
        }

    next_stage = meta.get("next stage")
    candidate, ok = apply_approval_to_intent(
        content, effective_approved_by, effective_decision_date,
        intent_version, next_stage)
    if not ok or candidate is None:
        return deny(
            "PMO-INTENT-APPROVAL-005",
            "could not locate the Document Control 'Status' field and/or "
            "the '## 16. Acceptance' section heading to update.",
        ), None

    candidate_meta = parse_doc_control(candidate)
    light = _light_checks(candidate, candidate_meta, root)
    if light is not None:
        return light, None
    schema_check = full_schema_validation(
        candidate, candidate_meta, root, status="VALIDATED",
        acceptance_record_override=acceptance_record_for_schema_check)
    if schema_check is not None:
        return schema_check, None

    # Idempotency: when the existing approval is already valid AND the
    # CURRENT on-disk Intent is already VALIDATED with a consistent
    # Acceptance section, there is nothing to do at all - no Intent write,
    # no approval-evidence write, no marker.
    if existing_status == "VALIDATED" and existing_valid:
        acceptance_already_ok = validate_acceptance_consistency(
            content, meta, root) is None
        if acceptance_already_ok:
            return deny(
                "PMO-INTENT-APPROVAL-003",
                "Intent v{} is already VALIDATED with a matching, "
                "internally-consistent approval record - nothing to "
                "do.".format(intent_version),
            ), None

    plan = {
        "mode": mode,
        "project_id": project_id,
        "artifact_path": INTENT_POSIX,
        "intent_version": intent_version,
        "approved_by": effective_approved_by,
        "decision_date": effective_decision_date,
        "approval_statement": approval_statement,
        "baseline_intent_hash": sha256_of_text(content),
        "approval_evidence_hash_before": sha256_of_file(
            os.path.join(root, INTENT_APPROVAL_RELPATH)),
        "candidate_intent_content": candidate,
        "candidate_approval_yaml": None if mode == "RECONCILE_EXISTING" else
        render_approval_yaml(
            effective_approved_by, effective_decision_date, intent_version,
            approval_statement=approval_statement,
            notes="Approval is scoped to this Intent version as the "
                 "governed business baseline. It does not itself authorize "
                 "Requirement Gathering execution, Scope, Specs, Feedback "
                 "processing, or Change Request activity - those remain "
                 "separate governed actions.",
        ),
    }
    return None, plan


def build_marker_data(plan, transaction_id, started_at):
    return {
        "transaction_type": "INTENT_APPROVAL",
        "transaction_id": transaction_id,
        "project_id": plan["project_id"],
        "artifact_path": plan["artifact_path"],
        "intent_version": plan["intent_version"],
        "started_at": started_at,
        "operation": "RECORD_APPROVAL",
        "status": "ACTIVE",
        "baseline_intent_hash": plan["baseline_intent_hash"],
        "approved_by": plan["approved_by"],
        "decision_date": plan["decision_date"],
        "approval_statement": plan.get("approval_statement"),
    }


def _rederive_plan_from_marker(root, marker_data):
    """Re-run `run_begin_preconditions` using the marker's own stored input
    parameters, against whatever is CURRENTLY on disk. Never trusts a
    previously-computed candidate string - always re-derives it fresh, so a
    legitimate intervening change is caught as drift rather than silently
    overwritten (mirrors `reconcile_transaction` in
    change_request_incorporation_core.py: 'nothing here ever restores a
    known snapshot by overwriting a newer change')."""
    return run_begin_preconditions(
        root, marker_data["approved_by"], marker_data["decision_date"],
        approval_statement=marker_data.get("approval_statement"),
        project_id_hint=marker_data.get("project_id"),
    )


def reconcile_transaction(root, marker_data):
    """Read-only. Returns (decision, report); decision is None iff the
    transaction is either (a) still cleanly resumable from its recorded
    baseline, or (b) already fully, consistently completed (idempotent
    success - report['already_done'] is True in that case)."""
    report = {
        "already_done": False,
        "intent_unchanged_since_begin": None,
        "approval_evidence_matches": None,
    }
    intent_path = os.path.join(root, INTENT_RELPATH)
    current_content = read_text(intent_path)
    if current_content is None:
        return deny(
            "PMO-INTENT-APPROVAL-002",
            "'{}' no longer exists.".format(INTENT_POSIX),
        ), report

    current_hash = sha256_of_text(current_content)
    current_meta = parse_doc_control(current_content)
    current_status = _norm_status(current_meta.get("status"))

    if current_status == "VALIDATED":
        pm_check = validate_pm_approval(None, "VALIDATED", current_meta, root)
        acceptance_check = validate_acceptance_consistency(current_content, current_meta, root)
        if pm_check is None and acceptance_check is None:
            existing_record, _err = load_intent_approval(root)
            same_approver = existing_record is not None and _clean(
                existing_record.get("approved_by", "")
            ).casefold() == _clean(marker_data.get("approved_by", "")).casefold()
            same_version = existing_record is not None and str(
                existing_record.get("version")
            ).strip() == str(marker_data.get("intent_version"))
            if same_approver and same_version:
                report["already_done"] = True
                return None, report

    decision, plan = _rederive_plan_from_marker(root, marker_data)
    if decision is not None:
        if decision.code == "PMO-INTENT-APPROVAL-003":
            report["already_done"] = True
            return None, report
        return decision, report

    report["intent_unchanged_since_begin"] = (
        current_hash == marker_data.get("baseline_intent_hash")
        or plan["baseline_intent_hash"] == marker_data.get("baseline_intent_hash")
    )
    if not report["intent_unchanged_since_begin"]:
        return deny(
            "PMO-INTENT-APPROVAL-011",
            "'{}' has changed since this approval transaction began - the "
            "content that was approved is no longer the content on disk. "
            "Start a new approval transaction (`begin`) against the current "
            "content.".format(INTENT_POSIX),
        ), report

    existing_evidence = read_text(os.path.join(root, INTENT_APPROVAL_RELPATH))
    if existing_evidence is not None:
        existing_record, _err = load_intent_approval(root)
        conflicting = (
            existing_record is None
            or _clean(existing_record.get("approved_by", "")).casefold()
            != marker_data.get("approved_by", "").casefold()
            or str(existing_record.get("version", "")).strip()
            != str(marker_data.get("intent_version"))
        )
        report["approval_evidence_matches"] = not conflicting
        if conflicting:
            return deny(
                "PMO-INTENT-APPROVAL-011",
                "'{}' already exists and does not match this transaction's "
                "approved_by/version - refusing to silently overwrite. "
                "Resolve the existing record manually before "
                "retrying.".format(INTENT_APPROVAL_POSIX),
            ), report

    return None, report


def finalize_transaction(root, marker_data):
    """Runs reconciliation, and only on a full PASS (or an idempotent
    already-done state) performs the writes: the approval evidence file,
    then - in one write - the Intent content carrying BOTH the Status flip
    and the Acceptance update. Re-verifies by re-reading each file back
    from disk before declaring success, so a failure can never be reported
    as a false clean success."""
    decision, report = reconcile_transaction(root, marker_data)
    if decision is not None:
        return decision, report
    if report.get("already_done"):
        return None, report

    decision, plan = _rederive_plan_from_marker(root, marker_data)
    if decision is not None:
        return decision, report

    evidence_path = os.path.join(root, INTENT_APPROVAL_RELPATH)
    reconciling_existing = plan.get("mode") == "RECONCILE_EXISTING"

    if reconciling_existing:
        # GOVERNANCE: an existing, already-valid approval record is
        # read-only source evidence during reconciliation. It is NEVER
        # regenerated, normalized, rewritten, or reformatted here - not
        # even a free-text field such as `notes` - regardless of whether
        # its exact bytes differ from what this module's own template would
        # otherwise render. `plan["candidate_approval_yaml"]` is always
        # None in this mode (see `run_begin_preconditions`) specifically so
        # there is nothing to accidentally write.
        report["approval_evidence_write_skipped"] = True
    else:
        existing_evidence_text = read_text(evidence_path)
        needs_evidence_write = existing_evidence_text != plan["candidate_approval_yaml"]
        if needs_evidence_write:
            try:
                write_text(evidence_path, plan["candidate_approval_yaml"])
            except Exception as exc:
                return deny(
                    "PMO-INTENT-APPROVAL-012",
                    "could not write '{}' ({}). No Intent content was "
                    "touched.".format(INTENT_APPROVAL_POSIX, exc),
                ), report
            written_back = read_text(evidence_path)
            if written_back != plan["candidate_approval_yaml"]:
                return deny(
                    "PMO-INTENT-APPROVAL-012",
                    "'{}' did not verify after writing (re-read did not "
                    "match what was written).".format(INTENT_APPROVAL_POSIX),
                ), report

    intent_path = os.path.join(root, INTENT_RELPATH)
    try:
        write_text(intent_path, plan["candidate_intent_content"])
    except Exception as exc:
        return deny(
            "PMO-INTENT-APPROVAL-013",
            "approval evidence was written correctly, but writing '{}' "
            "failed ({}). Re-run `finalize` - the evidence write is "
            "idempotent and will not be repeated.".format(INTENT_POSIX, exc),
        ), report

    written_intent = read_text(intent_path)
    if written_intent != plan["candidate_intent_content"]:
        return deny(
            "PMO-INTENT-APPROVAL-014",
            "'{}' did not verify after writing (re-read did not match what "
            "was written).".format(INTENT_POSIX),
        ), report
    written_meta = parse_doc_control(written_intent)
    if _norm_status(written_meta.get("status")) != "VALIDATED":
        return deny(
            "PMO-INTENT-APPROVAL-014",
            "post-write verification failed: '{}' Status is not VALIDATED "
            "after the write.".format(INTENT_POSIX),
        ), report
    post_check = validate_acceptance_consistency(written_intent, written_meta, root)
    if post_check is not None:
        return deny(
            "PMO-INTENT-APPROVAL-014",
            "post-write verification failed: {}".format(post_check.message),
        ), report

    if reconciling_existing:
        after_hash = sha256_of_file(evidence_path)
        if after_hash != plan.get("approval_evidence_hash_before"):
            return deny(
                "PMO-INTENT-APPROVAL-014",
                "post-write verification failed: '{}' was supposed to "
                "remain untouched during reconciliation of an existing "
                "approval, but its hash changed.".format(
                    INTENT_APPROVAL_POSIX),
            ), report

    return None, report
