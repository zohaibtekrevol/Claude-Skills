"""PMO PRE_BASELINE_SCHEMA_MIGRATION - deterministic core.

A governed, pre-approval-only REPRESENTATION migration for a provisional
`docs/pmo/specs/specs.md` whose FR/NFR blocks use an older generator layout
that the current Specs parser (`specs-governance-guard.py`) cannot read:

* the requirement ID and title live only in the `### FR-001 - Title` heading
  (no standalone `ID` / `Title` field);
* several fields share one line (`**Module:** X | **Actor(s):** Y`,
  `**Introduced In:** 0.1 | **Last Modified In:** 0.1 | **Change Source:** Z`).

This is NOT content regeneration, NOT a Change Request, and NOT a general
editor. The ONLY supported layout transformations are:

  1. add `- **ID:**` / `- **Title:**` lines whose values are the heading's own
     ID and title (nothing inferred);
  2. split a combined line into one `- **Label:** value` line per segment,
     only when the first label is a known combinable label and EVERY segment
     is a well-formed `**Label:** value` of a known combinable label
     (`COMBINABLE_LABELS`); anything else is ambiguous -> fail closed.

  3. classify each MISSING conditional Functional Requirement field under the
     applicability policy (`specs-governance-guard.py`, PMO-SPEC-010), without
     inventing anything: `Business Rules` is derived from the Business Rules
     table's own "Traced FRs" column (values, or NOT_APPLICABLE stating that no
     rule traces to the requirement); every other missing conditional field is
     `NOT_SPECIFIED` (the artifact does not define it - advisory, no PM
     question). A bare legacy placeholder in a conditional field is mapped to
     NOT_APPLICABLE (N/A, None) or NOT_SPECIFIED (TBD/TBC) with the original
     text quoted. PENDING_DECISION is never auto-created: linking a field to a
     Q&A decision is a human/Q&A-flow act. Acceptance Criteria bullets are
     preserved verbatim (the parser understands the list form).

Anything the parser cannot prove (an `ID` field that disagrees with its
heading, an unrecognised combined line, a missing mandatory field whose value
would have to be invented, multi-line acceptance criteria the validator
rejects, ...) is NOT migrated: the candidate is run through the authoritative
`full_spec_validation` and, if it still fails, NOTHING is written.

Composition with the existing repair primitives (never re-implemented here):
after the layout step the candidate may additionally receive, through
`specs_structural_repair_core`'s own functions and safety checks, the
provenance normalization (INITIAL_SPECS_GENERATION -> INITIAL_INTENT, only
when the NEW lifecycle is proven), the Generated From canonicalization and
the missing Validation Summary - so a single transaction can end in a fully
valid artifact. Semantic equivalence is verified independently
(`layout_equivalent`): block count/order/IDs, every field value, and all
content outside the blocks (Business Rules table, sections, exclusions,
Intent/Q&A mappings, deferred/TBD text) must be unchanged.

Transaction: `.pmo/specs-schema-migration-transaction.json`
(begin -> validate -> finalize, or abort). Runtime marker only; the marker is
never authorization. Approval, Execution Authorized and Spec Version are
never touched. Automatic orchestration remains disabled.

Python 3, standard library only.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import specs_structural_repair_core as src  # noqa: E402
from specs_structural_repair_core import (  # noqa: E402
    deny, read_text, write_text, sha256_of_text, sac, specs_guard,
    specs_abspath, SPECS_POSIX,
)
import json  # noqa: E402

OPERATION = "PRE_BASELINE_SCHEMA_MIGRATION"
TRANSACTION_TYPE = "SPECS_SCHEMA_MIGRATION"
MARKER_RELPATH_PARTS = src.SCHEMA_MIGRATION_MARKER_RELPATH_PARTS
MARKER_REQUIRED_FIELDS = (
    "transaction_type", "transaction_id", "project_id", "artifact",
    "spec_version", "operation", "reason", "started_at", "status",
    "pre_migration_validation_code", "plan", "specs_hash_before",
)
OPEN_STATUSES = {"ACTIVE"}

COMBINABLE_LABELS = ("Module", "Actor(s)", "Introduced In", "Last Modified In",
                     "Change Source")

_HEADING_RE = re.compile(r"^###\s+((?:FR|NFR)-\d+)\s+[—–-]\s+(\S.*?)\s*$")
_BLOCK_END_RE = re.compile(r"^(?:#{1,3}\s|---\s*$)")
_LABEL_SEG_RE = re.compile(r"^\*\*([^*|]+?):\*\*[ \t]*(\S.*?)[ \t]*$")
_FIELD_LINE_RE = re.compile(r"^- \*\*([^*|]+?):\*\*[ \t]*(.*)$")
_SPLIT_RE = re.compile(r"[ \t]+\|[ \t]+(?=\*\*)")


def marker_abspath(root):
    return os.path.join(root, *MARKER_RELPATH_PARTS)


# --------------------------------------------------------------------------- #
# Block discovery + deterministic parsing
# --------------------------------------------------------------------------- #

def find_blocks(lines):
    """[(start, end_exclusive, rid, title)] for every FR/NFR heading block."""
    out = []
    i = 0
    while i < len(lines):
        m = _HEADING_RE.match(lines[i])
        if m:
            j = i + 1
            while j < len(lines) and not _BLOCK_END_RE.match(lines[j]):
                j += 1
            out.append((i, j, m.group(1), m.group(2)))
            i = j
        else:
            i += 1
    return out


class Ambiguous(Exception):
    pass


def split_combined(line):
    """None when `line` is not a combined field line; else the list of
    (label, value). Raises Ambiguous for a malformed/unknown combined line."""
    m = _FIELD_LINE_RE.match(line)
    if not m or m.group(1) not in COMBINABLE_LABELS:
        return None
    segs = _SPLIT_RE.split(line[2:])
    if len(segs) == 1:
        return None
    out = []
    for seg in segs:
        sm = _LABEL_SEG_RE.match(seg)
        if not sm or sm.group(1) not in COMBINABLE_LABELS or "|" in sm.group(2):
            raise Ambiguous("unrecognised combined field line: {!r}".format(line))
        out.append((sm.group(1), sm.group(2)))
    labels = [l for l, _v in out]
    if len(set(labels)) != len(labels):
        raise Ambiguous("duplicate label in combined line: {!r}".format(line))
    return out


def block_fields(lines, rid, title):
    """Legacy-tolerant semantic parse of one block body -> ordered list of
    (label, value) with continuation lines attached to the previous label.
    ID/Title fields, if present, must agree with the heading (else Ambiguous)
    and are dropped (they are heading-derived)."""
    fields = []
    for line in lines:
        m = _FIELD_LINE_RE.match(line)
        if m:
            comb = split_combined(line)
            if comb is not None:
                fields.extend(comb)
            else:
                fields.append((m.group(1), m.group(2)))
        elif fields and line.strip():
            fields[-1] = (fields[-1][0], fields[-1][1] + "\n" + line)
        elif line.strip():
            raise Ambiguous("unattached content line in {}: {!r}".format(rid, line))
    out = []
    for label, value in fields:
        if label == "ID":
            if value.strip() != rid:
                raise Ambiguous("{} ID field '{}' disagrees with heading".format(rid, value))
            continue
        if label == "Title":
            if value.strip() != title:
                raise Ambiguous("{} Title field disagrees with heading".format(rid))
            continue
        out.append((label, value))
    return out


def semantic_records(text):
    """[(rid, title, fields)] for every block, in document order."""
    lines = text.split("\n")
    recs = []
    for start, end, rid, title in find_blocks(lines):
        recs.append((rid, title, block_fields(lines[start + 1:end], rid, title)))
    return recs


def outside_blocks(text):
    """Document text with every FR/NFR block (heading through body) removed."""
    lines = text.split("\n")
    keep = []
    cur = 0
    for start, end, _r, _t in find_blocks(lines):
        keep.extend(lines[cur:start])
        cur = end
    keep.extend(lines[cur:])
    return "\n".join(keep)


# --------------------------------------------------------------------------- #
# Layout migration (pure) + independent equivalence proof
# --------------------------------------------------------------------------- #

def layout_needs_migration(text):
    lines = text.split("\n")
    for start, end, rid, _t in find_blocks(lines):
        body = lines[start + 1:end]
        if not any(l.startswith("- **ID:**") for l in body):
            return True
        if any(split_combined(l) for l in body):
            return True
    return False


def migrate_layout(text):
    """Return (new_text, stats). Raises Ambiguous. Pure layout transformation."""
    lines = text.split("\n")
    blocks = find_blocks(lines)
    out = []
    cur = 0
    stats = {"blocks": 0, "id_title_added": 0, "combined_lines_split": 0,
             "fr_blocks": 0, "nfr_blocks": 0}
    for start, end, rid, title in blocks:
        out.extend(lines[cur:start])
        out.append(lines[start])
        body = lines[start + 1:end]
        stats["blocks"] += 1
        stats["nfr_blocks" if rid.startswith("NFR") else "fr_blocks"] += 1
        has_id = any(l.startswith("- **ID:**") for l in body)
        has_title = any(l.startswith("- **Title:**") for l in body)
        if has_id != has_title:
            raise Ambiguous("{} has only one of ID/Title fields".format(rid))
        block_fields(body, rid, title)  # validates ID/Title agreement, attachments
        lead = 0
        while lead < len(body) and not body[lead].strip():
            lead += 1
        if not has_id:
            out.extend(body[:lead])
            out.append("- **ID:** {}".format(rid))
            out.append("- **Title:** {}".format(title))
            stats["id_title_added"] += 1
            body = body[lead:]
        for l in body:
            comb = split_combined(l)
            if comb is None:
                out.append(l)
            else:
                stats["combined_lines_split"] += 1
                out.extend("- **{}:** {}".format(a, b) for a, b in comb)
        cur = end
    out.extend(lines[cur:])
    return "\n".join(out), stats


def layout_equivalent(before, after):
    """Independent proof that `after` differs from `before` only by layout:
    same blocks in the same order (id + title), identical ordered
    (label, value) records, and byte-identical content outside the blocks.
    Returns (ok, reason)."""
    try:
        rb = semantic_records(before)
        ra = semantic_records(after)
    except Ambiguous as exc:
        return False, str(exc)
    if [(r, t) for r, t, _f in rb] != [(r, t) for r, t, _f in ra]:
        return False, "requirement identifiers / titles / order changed."
    for (rid, _t, fb), (_r, _t2, fa) in zip(rb, ra):
        if fb != fa:
            return False, "{} field values changed during layout migration.".format(rid)
    if outside_blocks(before) != outside_blocks(after):
        return False, "content outside the FR/NFR blocks changed."
    return True, None


# --------------------------------------------------------------------------- #
# Applicability classification (PMO-SPEC-010 policy) - additive only
# --------------------------------------------------------------------------- #

def _br_trace_map(text):
    """{FR-id: [BR-id, ...]} from the Business Rules table's 'Traced FRs'
    column (the authoritative BR->FR trace); {} when there is no table."""
    tbl = specs_guard._table_after(text, r"business\s+rules")
    if tbl is None:
        return {}
    header, rows = tbl
    id_idx = specs_guard._col_index(header, "id", "br", "rule id")
    tr_idx = specs_guard._col_index(header, "traced frs", "traced fr", "traces to",
                                    "related fr", "traced")
    if id_idx is None:
        id_idx = 0
    out = {}
    if tr_idx is None:
        return out
    for row in rows:
        if id_idx < len(row) and tr_idx < len(row):
            bid = row[id_idx].strip().strip("`*")
            if re.match(r"^BR-\d+$", bid):
                for fr in re.findall(r"FR-\d+", row[tr_idx]):
                    out.setdefault(fr, []).append(bid)
    return out


_NA_WORDS = ("N_A", "NA", "NONE")


def _is_classification_statement(label, value):
    """An ADDED conditional field may only be NOT_APPLICABLE (with reason),
    NOT_SPECIFIED, or the Business Rules list derived from the BR table -
    never an invented DEFINED value."""
    state, _d, err = specs_guard.classify_applicability(value)
    if err is None and state in ("NOT_APPLICABLE", "NOT_SPECIFIED"):
        return True
    return label == "Business Rules" and bool(re.match(r"^BR-\d+(, BR-\d+)*$", value or ""))


def classify_conditional_fields(text):
    """Return (new_text, stats). Adds a missing applicability statement to
    each ACTIVE FR block and normalizes bare legacy placeholders. Pure text
    transformation; raises Ambiguous when a CORE field holds a placeholder."""
    lines = text.split("\n")
    trace = _br_trace_map(text)
    stats = {"added_not_specified": 0, "added_business_rules_defined": 0,
             "added_business_rules_not_applicable": 0,
             "placeholders_to_not_applicable": 0, "placeholders_to_not_specified": 0}
    out = []
    cur = 0
    for start, end, rid, title in find_blocks(lines):
        if not rid.startswith("FR-"):
            continue
        out.extend(lines[cur:start + 1])
        body = list(lines[start + 1:end])
        cur = end
        block_text = "\n".join(body)
        status = specs_guard.norm_token(specs_guard._field(block_text, "Status"))
        if status != "ACTIVE":
            out.extend(body)
            continue
        for label in specs_guard.FR_CORE_LABELS:
            if label == "Source Scope":
                continue
            v = specs_guard._field_value(block_text, label)
            if v is not None and specs_guard._is_bare_placeholder(v) \
                    and label != "Acceptance Criteria":
                raise Ambiguous("{} core field '{}' holds a placeholder".format(rid, label))
        # in-place normalization of bare placeholders
        for i, l in enumerate(body):
            fm = _FIELD_LINE_RE.match(l)
            if not fm or fm.group(1) not in specs_guard.FR_CONDITIONAL_LABELS:
                continue
            val = fm.group(2).strip()
            if val and specs_guard._is_bare_placeholder(val):
                kind = specs_guard.norm_token(val.rstrip(".").strip())
                if kind in _NA_WORDS:
                    body[i] = '- **{}:** NOT_APPLICABLE: legacy placeholder "{}" normalized by {}'.format(
                        fm.group(1), val, OPERATION)
                    stats["placeholders_to_not_applicable"] += 1
                else:
                    body[i] = "- **{}:** NOT_SPECIFIED".format(fm.group(1))
                    stats["placeholders_to_not_specified"] += 1
        block_text = "\n".join(body)
        adds = []
        for label in specs_guard.FR_CONDITIONAL_LABELS:
            if specs_guard._field_value(block_text, label) is not None:
                continue
            if label == "Business Rules":
                if trace.get(rid):
                    adds.append("- **Business Rules:** " + ", ".join(sorted(set(trace[rid]))))
                    stats["added_business_rules_defined"] += 1
                else:
                    adds.append("- **Business Rules:** NOT_APPLICABLE: no Business Rule "
                                "in the Business Rules table traces to this requirement")
                    stats["added_business_rules_not_applicable"] += 1
            else:
                adds.append("- **{}:** NOT_SPECIFIED".format(label))
                stats["added_not_specified"] += 1
        if adds:
            last = len(body) - 1
            while last >= 0 and not body[last].strip():
                last -= 1
            body[last + 1:last + 1] = adds
        out.extend(body)
    out.extend(lines[cur:])
    return "\n".join(out), stats


def classification_is_additive(before, after):
    """Independent proof for the classification stage: identical blocks and
    outside-block content; every original field kept in order and value
    (except a bare legacy placeholder mapped to an applicability statement);
    everything else is an appended conditional field carrying a valid state
    (or the derived Business Rules list)."""
    try:
        rb = semantic_records(before)
        ra = semantic_records(after)
    except Ambiguous as exc:
        return False, str(exc)
    if [(r, t) for r, t, _f in rb] != [(r, t) for r, t, _f in ra]:
        return False, "requirement identifiers / titles / order changed."
    if outside_blocks(before) != outside_blocks(after):
        return False, "content outside the FR/NFR blocks changed."
    cond = specs_guard.FR_CONDITIONAL_LABELS
    for (rid, _t, fb), (_r, _t2, fa) in zip(rb, ra):
        if len(fa) < len(fb):
            return False, "{} lost field(s).".format(rid)
        for (lb, vb), (la, va) in zip(fb, fa):
            if lb != la:
                return False, "{} field order/label changed.".format(rid)
            if vb == va:
                continue
            if lb in cond and specs_guard._is_bare_placeholder(vb):
                state, _d, err = specs_guard.classify_applicability(va)
                if err is None and state in ("NOT_APPLICABLE", "NOT_SPECIFIED"):
                    continue
            return False, "{} field '{}' value changed.".format(rid, lb)
        present = {l for l, _v in fb}
        for la, va in fa[len(fb):]:
            if la not in cond or la in present:
                return False, "{} gained a non-conditional or duplicate field '{}'.".format(rid, la)
            if not _is_classification_statement(la, va):
                return False, "{} added field '{}' is not a permitted classification.".format(rid, la)
    return True, None


# --------------------------------------------------------------------------- #
# Candidate construction (layout + existing repair primitives)
# --------------------------------------------------------------------------- #

def build_candidate(root, content):
    """(candidate_text, plan, Decision-or-None). Reuses the STRUCTURAL_REPAIR
    primitives for provenance / Generated From / Validation Summary, each
    with its own independent safety check. Never writes."""
    try:
        layout, stats = migrate_layout(content)
    except Ambiguous as exc:
        return None, None, deny("PMO-SCHEMA-MIG-006",
                                "ambiguous legacy parsing - refusing: {}".format(exc))
    ok, why = layout_equivalent(content, layout)
    if not ok:
        return None, None, deny("PMO-SCHEMA-MIG-007", why)
    plan = {"layout": stats, "classes": ["LAYOUT_CANONICALIZATION"],
            "provenance": {}, "metadata": {}, "missing_sections": [],
            "applicability": {}}
    cand = layout
    try:
        classified, cstats = classify_conditional_fields(cand)
    except Ambiguous as exc:
        return None, None, deny("PMO-SCHEMA-MIG-006",
                                "ambiguous classification - refusing: {}".format(exc))
    if classified != cand:
        ok, why = classification_is_additive(cand, classified)
        if not ok:
            return None, None, deny("PMO-SCHEMA-MIG-007", why)
        cand = classified
        plan["classes"].append("APPLICABILITY_CLASSIFICATION")
        plan["applicability"] = cstats

    eligible, _tot, excluded = src.find_provenance_occurrences(cand)
    if eligible:
        d = src.prove_new_lifecycle_provenance(root)
        if d is not None:
            return None, None, d
        before_p = cand
        cand = src.apply_provenance_fix(before_p)
        ok, info = src.provenance_fix_is_token_only(before_p, cand)
        if not ok:
            return None, None, deny("PMO-SCHEMA-MIG-008", info)
        plan["classes"].append(src.REPAIR_CLASS_PROVENANCE)
        plan["provenance"] = {"from": src.NONCANONICAL_INITIAL_TOKEN,
                              "to": src.CANONICAL_NEW_INITIAL_TOKEN,
                              "occurrences": len(eligible),
                              "excluded_non_provenance": excluded}

    invalid, _cur = src._generated_from_invalid(root, cand)
    if invalid:
        new_gf = src.derive_generated_from_value(root)
        if new_gf is None:
            return None, None, deny(
                "PMO-SCHEMA-MIG-008",
                "Generated From is invalid and its canonical value cannot be derived.")
        before_m = cand
        cand, ok = src.apply_metadata_fix(before_m, "Generated From", new_gf)
        if not ok:
            return None, None, deny("PMO-SCHEMA-MIG-008",
                                    "could not locate the Generated From line.")
        ok, info = src.metadata_fix_is_field_only(before_m, cand, src.PERMITTED_METADATA_FIELDS)
        if not ok:
            return None, None, deny("PMO-SCHEMA-MIG-008", info)
        plan["classes"].append(src.REPAIR_CLASS_METADATA)
        plan["metadata"] = {"Generated From": new_gf}

    missing = [n for n, _rx, _c in src.missing_required_sections(cand)]
    if missing:
        unsupported = [n for n in missing if n not in src.PERMITTED_REPAIR_SECTIONS]
        if unsupported:
            return None, None, deny(
                "PMO-SCHEMA-MIG-009",
                "required section(s) {} cannot be derived deterministically.".format(unsupported))
        before_t = cand
        tail = [src._DERIVERS[n](root, before_t) for n in missing]
        cand = before_t.rstrip("\n") + "\n\n---\n\n" + "\n---\n\n".join(tail)
        ok, why = src.content_preserves_existing(before_t, cand)
        if not ok:
            return None, None, deny("PMO-SCHEMA-MIG-008", why)
        plan["classes"].append(src.REPAIR_CLASS_MISSING_SECTION)
        plan["missing_sections"] = missing
    return cand, plan, None


def final_equivalence(before, after):
    """Whole-transaction semantic proof: per block, every original field is
    kept in order with an identical value - modulo (a) the one approved
    provenance token substitution and (b) bare legacy placeholders mapped to
    an applicability statement - and anything else is an appended conditional
    field. Content outside the blocks may differ only by the approved repair
    primitives (each checked stage-by-stage in build_candidate)."""
    def norm(text):
        recs = semantic_records(text)
        return [(r, t, [(l, v.replace(src.NONCANONICAL_INITIAL_TOKEN,
                                      src.CANONICAL_NEW_INITIAL_TOKEN) if l == "Change Source" else v)
                        for l, v in f]) for r, t, f in recs]
    try:
        nb, na = norm(before), norm(after)
    except Ambiguous:
        return False
    if [(r, t) for r, t, _f in nb] != [(r, t) for r, t, _f in na]:
        return False
    cond = specs_guard.FR_CONDITIONAL_LABELS
    for (_r, _t, fb), (_r2, _t2, fa) in zip(nb, na):
        if len(fa) < len(fb):
            return False
        for (lb, vb), (la, va) in zip(fb, fa):
            if lb != la:
                return False
            if vb != va and not (lb in cond and specs_guard._is_bare_placeholder(vb)):
                return False
        present = {l for l, _v in fb}
        if any(la not in cond or la in present or not _is_classification_statement(la, va)
               for la, va in fa[len(fb):]):
            return False
    return True


# --------------------------------------------------------------------------- #
# Begin / marker / finalize / abort
# --------------------------------------------------------------------------- #

def run_begin_preconditions(root, reason):
    reason = (reason or "").strip()
    if not reason:
        return None, deny("PMO-SCHEMA-MIG-001", "a migration reason is required.")
    content = read_text(specs_abspath(root))
    if content is None:
        return None, deny("PMO-SCHEMA-MIG-002",
                          "no canonical Specs artifact at {}.".format(SPECS_POSIX))
    meta = sac.parse_spec_doc_control(content)
    gate = src.pre_baseline_approval_gate(root, meta)
    if gate is not None:
        return None, deny("PMO-SCHEMA-MIG-003",
                          "pre-baseline gate failed ({}: {})".format(gate.code, gate.message))
    d = specs_guard.full_spec_validation(root, spec_text=content)
    if d is None:
        return None, deny("PMO-SCHEMA-MIG-005",
                          "full_spec_validation already passes - nothing to migrate.")
    project_id, gate = src.pre_baseline_concurrency_gate(
        root, meta, ignore_schema_migration_marker=True)
    if gate is not None:
        return None, gate
    if os.path.exists(src.marker_abspath(root)):
        return None, deny("PMO-SCHEMA-MIG-004",
                          "a STRUCTURAL_REPAIR transaction marker exists - resolve it first.")
    if not layout_needs_migration(content):
        return None, deny(
            "PMO-SCHEMA-MIG-010",
            "the artifact is not in a supported legacy layout (nothing for "
            "a schema migration to do); current failure {}: {}.".format(d.code, d.message))
    cand, plan, dec = build_candidate(root, content)
    if dec is not None:
        return None, dec
    dv = specs_guard.full_spec_validation(root, spec_text=cand)
    if dv is not None:
        return None, deny(
            "PMO-SCHEMA-MIG-011",
            "the migrated candidate still fails full_spec_validation ({}: {}) - "
            "the artifact is not migratable by a pure schema migration; nothing "
            "would be written.".format(dv.code, dv.message))
    if not final_equivalence(content, cand):
        return None, deny("PMO-SCHEMA-MIG-007", "semantic equivalence could not be proven.")
    return {
        "project_id": project_id,
        "spec_version": meta.get("spec_version"),
        "reason": reason,
        "pre_migration_validation_code": d.code,
        "pre_migration_validation_message": d.message,
        "plan": plan,
        "specs_hash_before": sha256_of_text(content),
    }, None


def build_marker_data(plan, transaction_id, started_at):
    return {
        "transaction_type": TRANSACTION_TYPE,
        "transaction_id": transaction_id,
        "project_id": plan["project_id"],
        "artifact": SPECS_POSIX,
        "spec_version": plan["spec_version"],
        "operation": OPERATION,
        "reason": plan["reason"],
        "started_at": started_at,
        "status": "ACTIVE",
        "pre_migration_validation_code": plan["pre_migration_validation_code"],
        "plan": plan["plan"],
        "specs_hash_before": plan["specs_hash_before"],
    }


def parse_marker(text):
    try:
        data = json.loads(text)
    except Exception as exc:
        return None, "marker is not valid JSON: {}".format(exc)
    if not isinstance(data, dict):
        return None, "marker did not parse to an object."
    missing = [f for f in MARKER_REQUIRED_FIELDS if f not in data]
    if missing:
        return data, "marker is missing field(s): {}.".format(", ".join(missing))
    if data.get("transaction_type") != TRANSACTION_TYPE or data.get("operation") != OPERATION:
        return data, "marker is not a {} transaction.".format(OPERATION)
    if data.get("status") not in OPEN_STATUSES:
        return data, "marker status '{}' is not a recognised open state.".format(data.get("status"))
    return data, None


def marker_status(root):
    text = read_text(marker_abspath(root))
    if text is None:
        return "ABSENT", None, None
    data, err = parse_marker(text)
    if err is not None:
        return "INVALID", data, err
    cfg = src.load_project_config(root) or {}
    pid = src._clean((cfg.get("project") or {}).get("id"))
    if pid and src._clean(data.get("project_id")).upper() != pid.upper():
        return "WRONG_PROJECT", data, "marker project_id does not match project-config.yaml."
    return "OPEN", data, None


def reconcile_transaction(root, marker_data):
    return run_begin_preconditions(root, marker_data.get("reason"))


def finalize_transaction(root, marker_data):
    """Re-derives everything from disk, proves equivalence and full
    validation on the complete candidate, then writes atomically. Any
    failure writes nothing."""
    try:
        plan, d = reconcile_transaction(root, marker_data)
        if d is not None:
            return None, d
        specs_path = specs_abspath(root)
        before = read_text(specs_path)
        if before is None or sha256_of_text(before) != marker_data.get("specs_hash_before"):
            return None, deny(
                "PMO-SCHEMA-MIG-012",
                "specs.md changed since this migration began - refusing a moving target.")
        cand, cplan, dec = build_candidate(root, before)
        if dec is not None:
            return None, dec
        dv = specs_guard.full_spec_validation(root, spec_text=cand)
        if dv is not None:
            return None, deny(
                "PMO-SCHEMA-MIG-011",
                "the migrated candidate does not pass full_spec_validation - "
                "nothing written ({}: {}).".format(dv.code, dv.message))
        if not final_equivalence(before, cand):
            return None, deny("PMO-SCHEMA-MIG-007", "semantic equivalence could not be proven.")
        bm = sac.parse_spec_doc_control(before)
        am = sac.parse_spec_doc_control(cand)
        for key in ("spec_version", "spec_status", "execution_authorized", "project_id"):
            if src._clean(bm.get(key)) != src._clean(am.get(key)):
                return None, deny("PMO-SCHEMA-MIG-013",
                                  "Document Control '{}' changed as a side effect.".format(key))
        write_text(specs_path, cand)
        try:
            os.remove(marker_abspath(root))
        except OSError:
            pass
        return {"spec_version": plan["spec_version"], "plan": cplan,
                "reason": plan["reason"]}, None
    except Exception as exc:  # pragma: no cover - fail closed
        return None, deny("PMO-SCHEMA-MIG-999", "internal error during finalize: {}".format(exc))


def abort_transaction(root, marker_data, abort_reason):
    """Governed recovery for a migration that did not finalize; identical
    guarantees to the STRUCTURAL_REPAIR abort (marker only, hash-verified)."""
    return src.abort_transaction(root, marker_data, abort_reason,
                                 marker_path=marker_abspath(root))
