"""PMO NEW-lifecycle (no-Scope) Change Request incorporation - deterministic core.

Same INCORPORATION operation, same CR record, same CR marker file and the same
CR core (`change_request_incorporation_core`) as the legacy Scope-based path;
what differs is what is being incorporated INTO. A NEW-lifecycle project has no
Scope, so the authorization chain is

    APPROVED baseline (Specs + matching approval)  +  APPROVED CR
        -> incorporation of the CR's approved change into Specs
        -> next Specs version, Change Source = CR, one Change History row
        -> previous baseline / approval / publication evidence preserved
        -> Execution Authorized false -> PM reapproval -> publication.

Branch rule (deterministic, no config flag): a project WITH a Scope artifact
under docs/pmo/scope/ keeps the legacy path untouched; a project without one
(and with no ambiguous stray files there) uses this module.

One change-history model
------------------------
For NEW projects the Specification Change History inside specs.md is the single
authoritative model (version, date, Change Source = CR id, changed ids, summary,
approval state). No standalone docs/pmo/change-log/ is created and no Scope is
manufactured; the CR record points at it (`Change Log Reference: Specs Change
History vX.Y`) and carries Incorporated Date / Target Spec Version. The guard
denies any Scope / Change Log / Write-Edit Specs write during such a transaction.

What is authored and what is proven
-----------------------------------
Requirement retirement, deferral or removal is deliberately NOT supported: a
plan cannot set `Status`, has no remove/retire operation, and `verify_confined`
rejects any disappearing requirement (fails closed, `PMO-CR-NOSCOPE-018`).

The framework NEVER invents requirement content. The semantic content of an
incorporation is a PLAN prepared (by the change-request-management Skill / PM)
from the approved CR's own Proposed Change:

    {"summary": "...",
     "changes": [
       {"op": "add_requirement", "block": "### FR-069 - Title\\n- **ID:** ..."},
       {"op": "set_field", "id": "FR-033", "field": "Requirement", "value": "..." | ["..", ".."]}]}

This module applies the plan deterministically to a copy of the approved Specs
and PROVES the result: every modified existing requirement must be listed in the
CR's Affected Requirements; new ids must be unused; every requirement block not
touched by the plan is byte-identical; outside the blocks only the Spec Version,
Execution Authorized and the one new Change History row differ; the candidate
passes the authoritative full_spec_validation (applicability policy included -
unknown details must be NOT_SPECIFIED / PENDING_DECISION, never invented).
CR-level open decisions stay in the CR; none becomes Q&A automatically, and a
CR whose `Blocking Open Decisions` field is non-empty cannot begin.

Atomicity: begin (validate, construct, prove, marker) -> validate (re-derive,
read-only) -> finalize (specs + baseline archive + approval archive + CR
INCORPORATED + register, all-or-nothing with rollback) / abort.

Python 3, standard library only.
"""

from __future__ import annotations

import datetime as _dt
import difflib
import hashlib
import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import change_request_incorporation_core as crc  # noqa: E402
import intent_approval_core as iac  # noqa: E402
import specs_feedback_amendment_core as amd  # noqa: E402
import specs_structural_repair_core as src  # noqa: E402
import specs_approval_core as sac  # noqa: E402

specs_guard = src.specs_guard
deny = crc.deny
read_text = crc.read_text
_ID_RE = re.compile(r"^(FR|NFR)-\d{3,}$")
_IDS_IN_TEXT_RE = re.compile(r"\b(?:FR|NFR)-\d{3,}\b")


def is_no_scope_project(root):
    """True for the NEW lifecycle: no Scope artifact. (A scope directory that
    holds files but no recognised Scope artifact is ambiguous and reported as
    such by the begin gate, never treated as new.)"""
    return not crc.list_scope_versions(root)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Plan validation + candidate construction
# --------------------------------------------------------------------------- #

def _block_range(lines, rid):
    for s, e, r in amd.blocks_of(lines):
        if r == rid:
            return s, e
    return None


def _set_line(block_lines, label, value):
    """Replace (or add) `- **label:** value` inside one block; a list value is
    written as an indented bullet list. Returns new block lines."""
    out, i, done = [], 0, False
    field_re = re.compile(r"^- \*\*" + re.escape(label) + r":\*\*")
    new = ["- **{}:** {}".format(label, value)] if isinstance(value, str) else \
        ["- **{}:**".format(label)] + ["  - {}".format(v) for v in value]
    while i < len(block_lines):
        l = block_lines[i]
        if field_re.match(l) and not done:
            i += 1
            while i < len(block_lines) and amd._LIST_ITEM_RE.match(block_lines[i]):
                i += 1
            out.extend(new)
            done = True
            continue
        out.append(l)
        i += 1
    if not done:
        last = len(out) - 1
        while last >= 0 and not out[last].strip():
            last -= 1
        out[last + 1:last + 1] = new
    return out


def apply_plan(text, plan, cr_id, target_version, date_iso, cr_title, approval_note, affected_ids):
    """(candidate_text, touched_ids, Decision|None). Pure."""
    lines = text.split("\n")
    changes = plan.get("changes")
    if not isinstance(changes, list) or not changes:
        return None, [], deny("PMO-CR-NOSCOPE-010", "the incorporation plan has no changes.")
    touched = []
    existing_ids = {r for _s, _e, r in amd.blocks_of(lines)}
    added = []
    for ch in changes:
        op = ch.get("op")
        if op == "set_field":
            rid, label, value = ch.get("id"), ch.get("field"), ch.get("value")
            if not _ID_RE.match(rid or "") or rid not in existing_ids:
                return None, [], deny("PMO-CR-NOSCOPE-011", "set_field targets '{}', which is not an existing requirement.".format(rid))
            if rid not in affected_ids:
                return None, [], deny("PMO-CR-NOSCOPE-012", "{} is not listed in the CR's Affected Requirements - the CR does not authorize changing it.".format(rid))
            if label in ("ID", "Title", "Introduced In", "Last Modified In", "Change Source"):
                return None, [], deny("PMO-CR-NOSCOPE-013", "field '{}' is governance-managed and cannot be set by a plan.".format(label))
            if label == "Status":
                return None, [], deny(
                    "PMO-CR-NOSCOPE-018",
                    "requirement retirement / deferral / removal (Status changes) is not supported by this "
                    "incorporation path and fails closed - it needs its own governed mechanism.")
            if not (isinstance(value, str) and value.strip()) and not (isinstance(value, list) and value and all(isinstance(v, str) and v.strip() for v in value)):
                return None, [], deny("PMO-CR-NOSCOPE-010", "set_field {}.{} needs a non-empty string or list of strings.".format(rid, label))
            rng = _block_range(lines, rid)
            s, e = rng
            block = lines[s:e]
            lines[s:e] = [block[0]] + _set_line(block[1:], label, value)
            if rid not in touched:
                touched.append(rid)
        elif op == "add_requirement":
            block = ch.get("block") or ""
            bl = block.rstrip("\n").split("\n")
            m = amd._BLOCK_HEADING_RE.match(bl[0]) if bl else None
            if not m:
                return None, [], deny("PMO-CR-NOSCOPE-010", "add_requirement needs a block starting with '### FR-nnn - Title'.")
            rid = m.group(1)
            if rid in existing_ids or rid in added or re.search(r"\b" + re.escape(rid) + r"\b", text):
                return None, [], deny("PMO-CR-NOSCOPE-014", "{} already exists in the baseline - identifiers are never reused.".format(rid))
            body = bl
            for lbl, val in (("Introduced In", target_version), ("Last Modified In", target_version), ("Change Source", cr_id)):
                body = [body[0]] + _set_line(body[1:], lbl, val)
            prefix = rid.split("-")[0]
            same = [(s, e, r) for s, e, r in amd.blocks_of(lines) if r.startswith(prefix + "-")]
            if not same:
                return None, [], deny("PMO-CR-NOSCOPE-010", "no existing {} block to insert after.".format(prefix))
            s, e, _r = max(same, key=lambda x: x[0])
            lines[e:e] = body + [""]
            added.append(rid)
            touched.append(rid)
        else:
            return None, [], deny("PMO-CR-NOSCOPE-010", "unknown plan operation '{}'.".format(op))
    cand = "\n".join(lines)
    # governance stamping of modified existing requirements
    lines = cand.split("\n")
    for rid in touched:
        if rid in added:
            continue
        s, e = _block_range(lines, rid)
        blk = lines[s:e]
        for lbl, val in (("Last Modified In", target_version), ("Change Source", cr_id)):
            blk = [blk[0]] + _set_line(blk[1:], lbl, val)
        lines[s:e] = blk
    cand = "\n".join(lines)
    cand, ok1 = iac.set_doc_control_field(cand, "Spec Version", target_version)
    cand, ok2 = iac.set_doc_control_field(cand, "Execution Authorized", "false") if ok1 else (None, False)
    if not (ok1 and ok2):
        return None, [], deny("PMO-CR-NOSCOPE-015", "the Document Control fields could not be located.")
    summary = plan.get("summary") or "Incorporated approved change request {}{}.".format(
        cr_id, (": " + cr_title) if cr_title else "")
    row = "| {} | {} | {} | {} | {} | Pending PM approval ({}) |".format(
        target_version, date_iso, cr_id, ", ".join(touched), summary.replace("|", "/"), approval_note)
    out = cand.rstrip("\n").split("\n")
    hm = [i for i, l in enumerate(out) if re.match(r"^#{1,6}\s+.*specification change history", l, re.I)]
    if not hm:
        return None, [], deny("PMO-CR-NOSCOPE-015", "the Specification Change History could not be located.")
    i = hm[0] + 1
    while i < len(out) and not out[i].strip().startswith("|"):
        i += 1
    while i < len(out) and out[i].strip().startswith("|"):
        i += 1
    out.insert(i, row)
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), touched, None


def verify_confined(before, after, touched_ids, target_version, cr_id):
    """(ok, reason). Independent proof that only authorized content changed."""
    bl, al = before.split("\n"), after.split("\n")
    bb = {r: bl[s:e] for s, e, r in amd.blocks_of(bl)}
    ab = {r: al[s:e] for s, e, r in amd.blocks_of(al)}
    for rid, blk in bb.items():
        if rid not in ab:
            return False, "requirement {} disappeared".format(rid)
        if rid not in touched_ids and ab[rid] != blk:
            return False, "unrelated requirement {} changed".format(rid)
    new_ids = [r for r in ab if r not in bb]
    if any(r not in touched_ids for r in new_ids):
        return False, "an unauthorized requirement was added"
    order_b = [r for _s, _e, r in amd.blocks_of(bl)]
    order_a = [r for _s, _e, r in amd.blocks_of(al) if r in bb]
    if order_b != order_a:
        return False, "existing requirement order changed"

    def outside(lines):
        keep, cur = [], 0
        for s, e, _r in amd.blocks_of(lines):
            keep.extend(lines[cur:s])
            cur = e
        keep.extend(lines[cur:])
        return keep
    ob, oa = outside(bl), outside(al)
    inserted = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ob, b=oa, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        a_txt, b_txt = ob[i1:i2], oa[j1:j2]
        if tag == "replace" and len(a_txt) == len(b_txt) and all(
                re.match(r"^- \*\*(Spec Version|Execution Authorized):\*\*", x) and
                re.match(r"^- \*\*(Spec Version|Execution Authorized):\*\*", y) for x, y in zip(a_txt, b_txt)):
            continue
        if tag == "insert" and len(b_txt) == 1 and b_txt[0].startswith("| {} |".format(target_version)) and cr_id in b_txt[0]:
            inserted += 1
            continue
        return False, "content outside the requirement blocks changed"
    if inserted != 1:
        return False, "exactly one Change History row must be added"
    return True, None


# --------------------------------------------------------------------------- #
# begin / marker / validate / finalize / abort
# --------------------------------------------------------------------------- #

def _affected_ids(fields):
    return set(_IDS_IN_TEXT_RE.findall(fields.get("Affected Requirements", "")))


def run_begin(root, cr_id, plan, project_id_hint=None, ignore_own_marker=False):
    """(Decision|None, marker-plan|None). Read-only."""
    if not is_no_scope_project(root):
        return deny("PMO-CR-NOSCOPE-001", "a Scope artifact exists - this project uses the legacy Scope-based incorporation path."), None
    scope_dir = os.path.join(root, "docs", "pmo", "scope")
    if os.path.isdir(scope_dir) and os.listdir(scope_dir):
        return deny("PMO-CR-NOSCOPE-002", "docs/pmo/scope/ is non-empty but holds no Scope artifact - lifecycle evidence is ambiguous; failing closed."), None
    d, ctx = crc.validate_cr_for_incorporation(root, cr_id, project_id_hint)
    if d is not None:
        return d, None
    fields = ctx["fields"]
    blocking = fields.get("Blocking Open Decisions", "").strip()
    if blocking and blocking.lower() not in ("none", "n/a", "-", "null"):
        return deny("PMO-CR-NOSCOPE-003", "CR {} has blocking open decisions that must be resolved first: {}".format(cr_id, blocking)), None
    if not fields.get("Proposed Change", "").strip() or not (
            fields.get("Affected Requirements", "").strip() or fields.get("Requested Change", "").strip()):
        return deny("PMO-CR-NOSCOPE-004", "CR {} is not sufficiently defined (Proposed Change / Affected Requirements).".format(cr_id)), None
    specs_path = src.specs_abspath(root)
    before = read_text(specs_path)
    if before is None:
        return deny("PMO-CR-INTEGRATE-006", "canonical specs.md does not exist."), None
    g = amd.approved_baseline_gate(root, before)
    if g is not None:
        return deny("PMO-CR-NOSCOPE-005", "the current Specs is not a valid approved baseline ({}).".format(g.message)), None
    g = amd.concurrency_gate(root, ignore_cr_marker=ignore_own_marker)
    if g is not None:
        return deny("PMO-CR-NOSCOPE-006", g.message), None
    if not isinstance(plan, dict):
        return deny("PMO-CR-NOSCOPE-010", "an incorporation plan (JSON) is required."), None
    if plan.get("cr_id") not in (None, cr_id):
        return deny("PMO-CR-NOSCOPE-010", "the plan is for a different CR."), None
    meta = sac.parse_spec_doc_control(before)
    baseline_version = crc._clean(meta.get("spec_version"))
    target = crc.bump_specs_version(baseline_version)
    if target is None:
        return deny("PMO-CR-INTEGRATE-006", "Spec Version '{}' cannot be advanced.".format(baseline_version)), None
    date_iso = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    approval_note = "{} approved {} by {}".format(cr_id, fields.get("Decision Date", "").strip(), fields.get("Decision By", "").strip())
    cand, touched, d = apply_plan(before, plan, cr_id, target, date_iso, fields.get("Title", "").strip(),
                                  approval_note, _affected_ids(fields))
    if d is not None:
        return d, None
    ok, why = verify_confined(before, cand, touched, target, cr_id)
    if not ok:
        return deny("PMO-CR-NOSCOPE-016", "semantic diff failed: {}.".format(why)), None
    dv = specs_guard.full_spec_validation(root, spec_text=cand)
    if dv is not None:
        return deny("PMO-CR-NOSCOPE-017", "the incorporated Specs would fail validation ({}: {}) - nothing written.".format(dv.code, dv.message)), None
    cfg_hash = crc.sha256_of_file(os.path.join(root, *crc.CONFIG_RELPATH.split("/")))
    return None, {
        "project_id": ctx["pid"], "cr_id": cr_id, "cr_path": ctx["cr_relpath"], "origin": ctx["origin"],
        "baseline_specs_version": baseline_version, "target_specs_version": target,
        "baseline_specs_hash": _sha(before), "touched_ids": touched,
        "candidate": cand, "date": date_iso, "plan": plan,
        "approval_evidence_reference": fields.get("Approval Evidence", "").strip(),
        "project_config_hash": cfg_hash,
        "intent_hash": crc.capture_protected_hash(root, ["docs/pmo/intent"]),
        "feedback_hash": (crc.capture_protected_hash(root, ["docs/pmo/feedback"]) if ctx["origin"] == "CLIENT_REQUESTED" else None),
        "affected_requirement_ids": fields.get("Affected Requirements", "").strip(),
    }


def build_marker(plan, transaction_id, started_at):
    return {
        "transaction_type": "CHANGE_REQUEST_MANAGEMENT", "transaction_id": transaction_id,
        "project_id": plan["project_id"], "cr_id": plan["cr_id"], "operation": "INCORPORATION",
        "lifecycle": crc.NO_SCOPE_LIFECYCLE, "started_at": started_at, "status": "ACTIVE",
        "baseline_specs_version": plan["baseline_specs_version"], "baseline_specs_path": crc.SPECS_POSIX,
        "baseline_specs_hash": plan["baseline_specs_hash"], "target_specs_version": plan["target_specs_version"],
        "artifact": crc.SPECS_POSIX, "spec_version": plan["baseline_specs_version"],
        "specs_hash_before": plan["baseline_specs_hash"], "cr_path": plan["cr_path"],
        "project_config_hash": plan["project_config_hash"], "intent_hash": plan["intent_hash"],
        "feedback_hash": plan["feedback_hash"], "approval_evidence_reference": plan["approval_evidence_reference"],
        "touched_ids": plan["touched_ids"], "plan": plan["plan"], "planned_date": plan["date"],
    }


def reconcile(root, marker):
    """(Decision|None, report). Read-only: re-derives the whole incorporation
    from the marker's plan and reports whether finalize would succeed. Also
    used by `status` / `validate`."""
    report = {"cr_id": marker.get("cr_id"), "lifecycle": crc.NO_SCOPE_LIFECYCLE}
    if marker.get("intent_hash") and crc.capture_protected_hash(root, ["docs/pmo/intent"]) != marker["intent_hash"]:
        return deny("PMO-CR-INTEGRATE-012", "docs/pmo/intent/ has changed since the transaction began."), report
    if marker.get("feedback_hash") and crc.capture_protected_hash(root, ["docs/pmo/feedback"]) != marker["feedback_hash"]:
        return deny("PMO-CR-INTEGRATE-012", "docs/pmo/feedback/ has changed since the transaction began."), report
    specs = read_text(src.specs_abspath(root))
    if specs is None or _sha(specs) != marker.get("baseline_specs_hash"):
        return deny("PMO-CR-INTEGRATE-011", "specs.md changed since the transaction began - refusing a moving target."), report
    d, mp = run_begin(root, marker["cr_id"], dict(marker["plan"], cr_id=marker["cr_id"]), ignore_own_marker=True)
    if d is not None:
        return d, report
    if mp["target_specs_version"] != marker["target_specs_version"]:
        return deny("PMO-CR-INTEGRATE-011", "the target version drifted."), report
    report.update({"target_specs_version": mp["target_specs_version"], "touched_ids": mp["touched_ids"], "ready": True})
    return None, report


class _Txn(object):
    """Snapshot-and-rollback file transaction."""

    def __init__(self):
        self.snap = {}
        self.made_dirs = []

    def _mkdirs(self, d):
        missing = []
        cur = d
        while cur and not os.path.isdir(cur):
            missing.append(cur)
            cur = os.path.dirname(cur)
        os.makedirs(d, exist_ok=True)
        self.made_dirs.extend(missing)

    def _s(self, p):
        if p not in self.snap:
            self.snap[p] = open(p, "rb").read() if os.path.isfile(p) else None

    def write(self, p, text):
        self._s(p)
        self._mkdirs(os.path.dirname(p))
        crc.write_text(p, text)

    def move(self, a, b):
        self._s(a); self._s(b)
        self._mkdirs(os.path.dirname(b))
        with open(a, "rb") as fh:
            data = fh.read()
        with open(b, "wb") as fh:
            fh.write(data)
        os.remove(a)

    def rollback(self):
        for p, data in self.snap.items():
            try:
                if data is None:
                    if os.path.exists(p):
                        os.remove(p)
                else:
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    with open(p, "wb") as fh:
                        fh.write(data)
            except OSError:
                pass
        for d in sorted(set(self.made_dirs), key=len, reverse=True):
            try:
                os.rmdir(d)  # only directories this transaction created, and only if empty
            except OSError:
                pass


def _register_update(root, cr_id, target):
    path = os.path.join(root, *crc.CR_REGISTER_POSIX.split("/"))
    text = read_text(path)
    if text is None:
        return None, None
    h, rows = crc.table_by_header_prefix(text, "CR ID")
    if not h:
        return None, None
    idx = {x: i for i, x in enumerate(h)}
    out = []
    for line in text.split("\n"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else None
        if cells and cells[0] == cr_id and len(cells) == len(h):
            if "Status" in idx:
                cells[idx["Status"]] = "INCORPORATED"
            if "Target Spec Version" in idx:
                cells[idx["Target Spec Version"]] = target
            line = "| " + " | ".join(cells) + " |"
        out.append(line)
    return path, "\n".join(out)


def finalize(root, marker, changed_by, changed_date, reason):
    """(Decision|None, report). All-or-nothing."""
    try:
        d, report = reconcile(root, marker)
        if d is not None:
            return d, report
        cr_id = marker["cr_id"]
        d, mp = run_begin(root, cr_id, dict(marker["plan"], cr_id=cr_id), ignore_own_marker=True)
        if d is not None:
            return d, report
        before = read_text(src.specs_abspath(root))
        target = marker["target_specs_version"]
        cr_path = os.path.join(root, *marker["cr_path"].split("/"))
        cr_old = read_text(cr_path)
        new_cr, ok1 = crc.set_field_value(cr_old, "Status", "INCORPORATED")
        new_cr, ok2 = crc.set_field_value(new_cr, "Incorporated Date", changed_date)
        new_cr, ok3 = crc.set_field_value(new_cr, "Change Log Reference", crc.no_scope_history_reference(target))
        if not (ok1 and ok2 and ok3):
            return deny("PMO-CR-INTEGRATE-025", "could not locate the required CR fields to finalize."), report
        new_cr, _ = crc.set_field_value(new_cr, "Target Spec Version", target)
        new_cr = crc.append_history_row(new_cr, changed_date, "APPROVED", "INCORPORATED", changed_by, reason)
        base_archive, appr_archive = amd.archive_targets(root, marker["baseline_specs_version"], marker["baseline_specs_hash"])
        approval = sac.approval_abspath(root)
        txn = _Txn()
        try:
            txn.write(base_archive, before)
            txn.write(src.specs_abspath(root), mp["candidate"])
            if os.path.isfile(approval):
                txn.move(approval, appr_archive)
            # the CR gate reads the NEW specs from disk: validate before the CR flip is written
            g = crc.validate_incorporated_gate(root, "APPROVED", crc.field_map_from_table(*crc.first_table(new_cr)), cr_id, marker)
            if g is None:
                g = crc.validate_history_append_only(cr_old, new_cr)
            if g is not None:
                raise _Refuse(g)
            txn.write(cr_path, new_cr)
            rp, rtext = _register_update(root, cr_id, target)
            if rp:
                rd = crc.validate_cr_register_content(rtext, root)
                if rd is not None and getattr(rd, "code", None):
                    raise _Refuse(rd)
                txn.write(rp, rtext)
        except _Refuse as r:
            txn.rollback()
            return r.decision, report
        except Exception as exc:
            txn.rollback()
            return deny("PMO-CR-INTEGRATE-018", "incorporation failed and was rolled back: {}".format(exc)), report
        report.update({"specs_version_before": marker["baseline_specs_version"], "specs_version_after": target,
                       "changed_requirements": mp["touched_ids"], "previous_baseline_archive": base_archive,
                       "previous_approval_archive": appr_archive, "reapproval_required": True,
                       "publication_required_after_approval": True})
        return None, report
    except Exception as exc:  # pragma: no cover - fail closed
        return deny("PMO-CR-INTEGRATE-018", "internal error during finalize: {}".format(exc)), {}


class _Refuse(Exception):
    def __init__(self, decision):
        Exception.__init__(self)
        self.decision = decision


def abort(root, marker, reason):
    """Marker-only recovery (hash-verified); never touches specs, approval, CR."""
    return src.abort_transaction(root, marker, reason,
                                 marker_path=os.path.join(root, *crc.CR_MARKER_RELPATH_PARTS))


def pm_message(kind, report=None, decision=None):
    """PM-facing wording; codes appear only in Engineering Mode (the caller
    passes the raw decision separately)."""
    if kind == "incorporated":
        v = (report or {}).get("specs_version_after")
        return ("CR approved. I incorporated the approved changes into Specs v{}. The updated Specs now "
                "require your approval before they can be published.".format(v))
    if kind == "ready":
        return "The approved change is ready to be incorporated into the Specs; nothing has been changed yet."
    return "The change could not be incorporated yet: {} No change was made.".format(decision.message if decision else "")
