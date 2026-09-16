#!/usr/bin/env python3
"""Shared deterministic parsing/validation for the PMO Questions & Assumptions
register:

    docs/pmo/requirements/questions-and-assumptions.md

This is the canonical NEW-lifecycle artifact that replaces Scope generation
for a project with no pre-existing Scope lineage (see `requirement-gathering`
SKILL.md). It is deliberately file/Git based - no marker file, no
multi-artifact transaction - the same "deterministic mechanical controls in
the hook/lib, semantic judgement in the skill" split already used for Intent,
Scope and Specs.

Used by:

* `.claude/hooks/qa-register-guard.py` - the register's own governance
  (structural integrity, id stability, resolution-required-when-claiming-
  resolution, no silent loss of a prior resolution).
* `.claude/hooks/specs-governance-guard.py` - the NEW-lifecycle Specs entry
  contract, which reads the register's resolved/blocking state through
  `validate_new_path_readiness` but never re-implements or mutates it.

Python 3, standard library only. No third-party dependencies.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Imported under its own namespace on purpose (never `from ... import
# <bare names>`): this module reuses `intent_approval_core`'s Intent /
# approval / identity validation unchanged - the exact same prerequisite
# rule `scope-version-guard.py` enforces for Scope (PMO-SCOPE-001) - so the
# NEW-lifecycle Q&A/Specs entry gate never duplicates that truth.
import intent_approval_core as iac  # noqa: E402


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

QA_DIR_POSIX = "docs/pmo/requirements"
QA_FILE_POSIX = "docs/pmo/requirements/questions-and-assumptions.md"
INTENT_POSIX = "docs/pmo/intent/intent.md"

QA_ID_RE = re.compile(r"^(?:QST|ASM)-\d+$")

ALLOWED_TYPES = ("QUESTION", "ASSUMPTION")
ALLOWED_STATUSES = (
    "OPEN", "CONFIRMED", "REJECTED", "RESOLVED", "DEFERRED", "NON_BLOCKING",
)
# Statuses that claim an actual resolution decision - require the full
# Resolution / Resolution Authority / Resolution Evidence-Date triple.
CLAIMS_RESOLUTION_STATUSES = ("CONFIRMED", "REJECTED", "RESOLVED")
# Statuses that claim a governed disposition short of resolution - require
# who decided and why, but not necessarily a dated evidence citation (the
# Intent's own NON_BLOCKING_FUTURE_DECISION pattern: no date is invented).
CLAIMS_DISPOSITION_STATUSES = ("DEFERRED", "NON_BLOCKING")
BLOCKING_VALUES = ("YES", "NO")

QA_REQUIRED_DOC_CONTROL = (
    "Project", "Client", "Project ID", "PM", "Date", "Intent Version",
)

# A non-canonical variant of the single live Q&A artifact.
FORBIDDEN_QA_BASENAME_RE = re.compile(
    r"^(?:"
    r"questions?-and-assumptions?[-_]v\d+(?:\.\d+)*\.md"
    r"|questions?-and-assumptions?[-_](?:latest|final|current|draft|new|old)\.md"
    r"|(?:latest|final|current|previous|old|new)[-_]questions?-and-assumptions?\.md"
    r")$",
    re.IGNORECASE,
)

_QA_HEADING_STRICT_RE = re.compile(r"(?m)^(#{2,6})\s+((?:QST|ASM)-\d+)\b.*$")
_QA_HEADING_LOOSE_RE = re.compile(r"(?m)^#{2,6}\s+((?:QST|ASM)-\S+)\b")


# --------------------------------------------------------------------------- #
# Filesystem helpers
# --------------------------------------------------------------------------- #

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        return None


def qa_abspath(root):
    return os.path.join(root, *QA_FILE_POSIX.split("/"))


def intent_abspath(root):
    return os.path.join(root, *INTENT_POSIX.split("/"))


# --------------------------------------------------------------------------- #
# Field / metadata parsing (same label:value convention as the sibling
# Scope/Specs guards - `Label: value`, `**Label:** value`, `| Label | value |`)
# --------------------------------------------------------------------------- #

def _clean(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def norm_token(value):
    if value is None:
        return None
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(value).strip().upper()).strip("_")
    return s or None


def _field(text, label):
    """First `Label: value` (or `**Label:** value`, `| Label | value |`) in
    text, or None when the label is absent or its value is blank. Whitespace
    on the value side is horizontal-only so an empty field never borrows the
    next line's content."""
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


def parse_qa_metadata(text):
    meta = {}
    for label in ("Project", "Client", "Project ID", "Project Name", "PM",
                  "Date", "Intent Version", "Repository"):
        v = _field(text, label)
        if v is not None:
            meta[label.lower()] = v
    if "project" not in meta and "project name" in meta:
        meta["project"] = meta["project name"]
    return meta


def validate_doc_control(text):
    missing = [f for f in QA_REQUIRED_DOC_CONTROL if _field(text, f) is None]
    if missing:
        return ("the Q&A register Document Control is missing field(s): "
                "{}.".format(", ".join(missing)))
    return None


# --------------------------------------------------------------------------- #
# Record parsing
# --------------------------------------------------------------------------- #

def parse_qa_record_blocks(text):
    """[(id, block_text), ...] in document order, one entry per `#### QST-###`
    / `#### ASM-###` heading. Duplicates are returned as separate entries -
    callers decide what a repeat means."""
    text = text or ""
    matches = list(_QA_HEADING_STRICT_RE.finditer(text))
    out = []
    for i, m in enumerate(matches):
        rid = m.group(2)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((rid, text[start:end]))
    return out


def find_duplicate_ids(blocks):
    counts = {}
    for rid, _ in blocks:
        counts[rid] = counts.get(rid, 0) + 1
    return sorted(k for k, v in counts.items() if v > 1)


def find_malformed_ids(text):
    """A heading that starts `QST-` / `ASM-` but is not exactly `<PREFIX>-<digits>`."""
    bad = []
    for m in _QA_HEADING_LOOSE_RE.finditer(text or ""):
        token = m.group(1)
        if not QA_ID_RE.match(token):
            bad.append(token)
    return sorted(set(bad))


def parse_qa_record(rid, block):
    return {
        "id": rid,
        "type": _field(block, "Type"),
        "statement": _field(block, "Statement"),
        "why": _field(block, "Why Resolution Is Required"),
        "source_evidence": _field(block, "Source / Evidence"),
        "related_intent_item": _field(block, "Related Intent Item"),
        "owner": _field(block, "Owner"),
        "status": _field(block, "Status"),
        "blocking": _field(block, "Blocking"),
        "resolution": _field(block, "Resolution"),
        "resolution_authority": _field(block, "Resolution Authority"),
        "resolution_evidence_date": _field(block, "Resolution Evidence / Date"),
        "specs_impact": _field(block, "Specs Impact"),
        "text": block,
    }


def qa_records(root):
    """[record, ...] for the canonical Q&A register, or [] when absent /
    unreadable. Does not itself deduplicate or validate - see
    `validate_record_structure` / `find_duplicate_ids` for that."""
    text = read_text(qa_abspath(root))
    if text is None:
        return []
    return [parse_qa_record(rid, block)
            for rid, block in parse_qa_record_blocks(text)]


# --------------------------------------------------------------------------- #
# Structural validation - one record
# --------------------------------------------------------------------------- #

def check_required_fields(rec):
    rid = rec["id"]
    missing = [label for label, key in (
        ("Statement", "statement"),
        ("Why Resolution Is Required", "why"),
        ("Source / Evidence", "source_evidence"),
        ("Owner", "owner"),
    ) if not rec.get(key)]
    if missing:
        return "{} is missing required field(s): {}.".format(
            rid, ", ".join(missing))
    return None


def check_type(rec):
    rid = rec["id"]
    rtype = norm_token(rec.get("type"))
    if rtype not in ALLOWED_TYPES:
        return "{} has Type '{}' - must be QUESTION or ASSUMPTION.".format(
            rid, rec.get("type"))
    return None


def check_status(rec):
    rid = rec["id"]
    status = norm_token(rec.get("status"))
    if status not in ALLOWED_STATUSES:
        return "{} has Status '{}' - must be one of {}.".format(
            rid, rec.get("status"), ", ".join(ALLOWED_STATUSES))
    return None


def check_blocking(rec):
    rid = rec["id"]
    blocking = norm_token(rec.get("blocking"))
    if blocking not in BLOCKING_VALUES:
        return ("{} has Blocking '{}' - Blocking must be explicitly YES or "
                "NO; it is never inferred.".format(rid, rec.get("blocking")))
    return None


def check_resolution_completeness(rec):
    rid = rec["id"]
    status = norm_token(rec.get("status"))
    if status in CLAIMS_RESOLUTION_STATUSES:
        need = [lbl for lbl, key in (
            ("Resolution", "resolution"),
            ("Resolution Authority", "resolution_authority"),
            ("Resolution Evidence / Date", "resolution_evidence_date"),
        ) if not rec.get(key)]
        if need:
            return (
                "{} has Status {} but is missing {} - a record that claims "
                "CONFIRMED/REJECTED/RESOLVED must record what was decided, "
                "who decided it, and the evidence or date.".format(
                    rid, status, ", ".join(need))
            )
    elif status in CLAIMS_DISPOSITION_STATUSES:
        need = [lbl for lbl, key in (
            ("Resolution", "resolution"),
            ("Resolution Authority", "resolution_authority"),
        ) if not rec.get(key)]
        if need:
            return (
                "{} has Status {} but is missing {} - a DEFERRED / "
                "NON_BLOCKING record must still record who made that call "
                "and why, even with no date invented.".format(
                    rid, status, ", ".join(need))
            )
    return None


def validate_record_structure(rec):
    """Deterministic structural rules for a single parsed record, in order.
    Returns the first violation's error message (str), or None when the
    record is structurally clean. Used where fine-grained error codes are
    not needed (e.g. the NEW-lifecycle Specs-entry readiness check); the
    guard itself calls the individual `check_*` functions for distinct
    PMO-QA-* codes."""
    for check in (check_required_fields, check_type, check_status,
                  check_blocking, check_resolution_completeness):
        msg = check(rec)
        if msg is not None:
            return msg
    return None


def blocking_open_records(records):
    """Records that block Specs generation: Status OPEN and Blocking YES -
    the exact, and only, blocking condition (every other Status/Blocking
    combination permits Specs generation)."""
    return [rec for rec in records
            if norm_token(rec.get("status")) == "OPEN"
            and norm_token(rec.get("blocking")) == "YES"]


# --------------------------------------------------------------------------- #
# No silent loss of a prior resolution
# --------------------------------------------------------------------------- #

def detect_resolution_regression(old_text, new_text):
    """A record that already carried a recorded resolution/disposition
    (Status in CLAIMS_RESOLUTION_STATUSES / CLAIMS_DISPOSITION_STATUSES with
    a non-empty Resolution) must not silently disappear, nor have its
    Resolution blanked while some non-OPEN Status is kept. Reverting Status
    to OPEN and clearing Resolution is a legitimate, visible reopening - not
    a silent loss - and is allowed."""
    old_blocks = {}
    for rid, block in parse_qa_record_blocks(old_text or ""):
        old_blocks.setdefault(rid, block)
    if not old_blocks:
        return None
    new_blocks = {}
    for rid, block in parse_qa_record_blocks(new_text or ""):
        new_blocks.setdefault(rid, block)

    for rid, old_block in old_blocks.items():
        old_status = norm_token(_field(old_block, "Status"))
        old_resolution = _field(old_block, "Resolution")
        if old_status not in (CLAIMS_RESOLUTION_STATUSES
                              + CLAIMS_DISPOSITION_STATUSES):
            continue
        if not old_resolution:
            continue
        new_block = new_blocks.get(rid)
        if new_block is None:
            return ("{} previously carried a recorded {} resolution and has "
                    "been removed from the register entirely.".format(
                        rid, old_status))
        new_resolution = _field(new_block, "Resolution")
        new_status = norm_token(_field(new_block, "Status"))
        if not new_resolution and new_status != "OPEN":
            return (
                "{} previously carried a recorded {} resolution ('{}') that "
                "has been blanked while Status stayed {} - reopen it "
                "explicitly (Status: OPEN) instead of silently dropping the "
                "resolution.".format(
                    rid, old_status, old_resolution, new_status)
            )
    return None


# --------------------------------------------------------------------------- #
# Project identity
# --------------------------------------------------------------------------- #

def validate_qa_project_identity(meta, cfg):
    if not isinstance(cfg, dict):
        return None
    project = cfg.get("project") if isinstance(cfg.get("project"), dict) else {}
    checks = (
        ("project id", project.get("id"), "Project ID"),
        ("project", project.get("name"), "Project"),
        ("client", project.get("client"), "Client"),
    )
    for key, cfg_val, label in checks:
        doc_val = _clean(meta.get(key))
        cval = _clean(cfg_val)
        if not doc_val or not cval:
            continue
        if doc_val.casefold() != cval.casefold():
            return (
                "Q&A register {} '{}' does not match .pmo/project-config.yaml "
                "('{}'); project-config is the identity authority.".format(
                    label, doc_val, cval)
            )
    return None


# --------------------------------------------------------------------------- #
# Canonical path
# --------------------------------------------------------------------------- #

def validate_canonical_qa_path(rel_posix):
    """Given a repo-relative POSIX path, return an error message when it is a
    non-canonical *live* Q&A artifact, else None."""
    rel = (rel_posix or "").lstrip("./")
    if not rel.startswith(QA_DIR_POSIX + "/"):
        return None
    base = rel.split("/")[-1]
    if base == "questions-and-assumptions.md":
        return None
    if FORBIDDEN_QA_BASENAME_RE.match(base):
        return (
            "the live Q&A register must be {} - '{}' is a non-canonical "
            "versioned/aliased variant. The register is a single canonical "
            "file; its history lives in git, not in filename versions."
            .format(QA_FILE_POSIX, rel)
        )
    return None


# --------------------------------------------------------------------------- #
# Intent prerequisite (shared, identical rule to PMO-SCOPE-001)
# --------------------------------------------------------------------------- #

def validate_prerequisite_intent(root, artifact_label="Q&A register"):
    """The canonical Intent must exist, be VALIDATED, carry a structurally
    valid matching PM approval record, and match project-config identity -
    exactly the same rule `scope-version-guard.py` enforces as
    PMO-SCOPE-001 and `intent-schema-guard.py` enforces as PMO-INTENT-011.
    Returns an error message (str) or None."""
    text = read_text(intent_abspath(root))
    if text is None:
        return ("docs/pmo/intent/intent.md not found - the {} must not be "
                "based on a missing/unvalidated Intent.".format(artifact_label))

    meta = iac.parse_doc_control(text)
    status = iac._norm_status(meta.get("status"))
    if status != "VALIDATED":
        return "Intent Status is '{}', not VALIDATED.".format(status)

    if not iac._clean(meta.get("intent version")):
        return "the Intent has no 'Intent Version' in Document Control."

    approval_check = iac.validate_pm_approval(None, "VALIDATED", meta, root)
    if approval_check is not None:
        return (
            "the canonical Intent is not backed by a valid, matching PM "
            "approval record at '{}' - {}".format(
                iac.INTENT_APPROVAL_POSIX, approval_check.message)
        )

    cfg = iac.load_project_config(root)
    if not isinstance(cfg, dict):
        return ".pmo/project-config.yaml is missing or unreadable."
    identity_check = iac.validate_project_identity(meta, cfg)
    if identity_check is not None:
        return (
            "the Intent's project identity does not match "
            "project-config.yaml - {}".format(identity_check.message)
        )
    return None


# --------------------------------------------------------------------------- #
# Full NEW-lifecycle Specs-entry readiness (used by specs-governance-guard.py)
# --------------------------------------------------------------------------- #

def validate_new_path_readiness(root):
    """Full Specs-entry readiness for the NEW (no-Scope) lifecycle path.
    Returns (kind, message) on failure, where `kind` is one of
    "INTENT_NOT_READY" / "QA_REGISTER_NOT_READY" / "QA_BLOCKING_ITEM_OPEN",
    or None when the new path is ready. This function reads the canonical
    Intent, approval record and Q&A register directly - it never consults
    project-config booleans as an authorization source (those are
    derived/display state only)."""
    err = validate_prerequisite_intent(root, artifact_label="Specification")
    if err is not None:
        return ("INTENT_NOT_READY", err)

    text = read_text(qa_abspath(root))
    if text is None:
        return (
            "QA_REGISTER_NOT_READY",
            "no canonical Q&A register at {} - the new-lifecycle Specs entry "
            "requires it (Scope is not required).".format(QA_FILE_POSIX),
        )

    dc_err = validate_doc_control(text)
    if dc_err is not None:
        return ("QA_REGISTER_NOT_READY", dc_err)

    blocks = parse_qa_record_blocks(text)
    dups = find_duplicate_ids(blocks)
    if dups:
        return (
            "QA_REGISTER_NOT_READY",
            "the Q&A register has duplicate record id(s): {}.".format(
                ", ".join(dups)),
        )
    malformed = find_malformed_ids(text)
    if malformed:
        return (
            "QA_REGISTER_NOT_READY",
            "the Q&A register has malformed record id(s): {}.".format(
                ", ".join(malformed)),
        )

    records = [parse_qa_record(rid, block) for rid, block in blocks]
    for rec in records:
        msg = validate_record_structure(rec)
        if msg is not None:
            return ("QA_REGISTER_NOT_READY", msg)

    blockers = blocking_open_records(records)
    if blockers:
        ids = ", ".join(r["id"] for r in blockers)
        return (
            "QA_BLOCKING_ITEM_OPEN",
            "unresolved Blocking Q&A record(s) prevent Specs generation: "
            "{}.".format(ids),
        )
    return None
