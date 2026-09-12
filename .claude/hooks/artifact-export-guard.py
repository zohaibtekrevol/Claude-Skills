#!/usr/bin/env python3
"""PMO artifact-export governance guard (Claude Code PreToolUse + reusable validator).

The *artifact-export skill* owns presentation, layout and document generation.
This hook owns only the mechanical, deterministic controls around an export of a
PMO Markdown artifact into a stakeholder / client-facing document under:

    docs/pmo/exports/

Deterministic guarantees
------------------------
* the export comes from an authoritative PMO Markdown source that exists;
* the export uses the correct project identity and the correct version;
* the authoritative source is read-only and byte-identical after the export;
* an existing export is never silently overwritten;
* a valid SHA-256 of the source is recorded;
* docs/pmo/exports/export-manifest.json stays structurally valid;
* the export does not advance PMO approval / workflow state;
* the generated artifact lands under the correct export location, and (for a
  DOCX) is a structurally readable OpenXML package;
* for a CLIENT audience, no internal PMO-automation markers leak into the
  generated document;
* governed substantive identifiers present in the source remain represented in
  the exported client-facing content (no drop, no renumber).

Behaviour
---------
* PreToolUse: reads the Claude Code payload from stdin (JSON); acts on `Write` /
  `Edit` / `MultiEdit` whose `file_path` is a generated export (`*.docx` /
  `*.pdf`) or `export-manifest.json`, and on `Bash` conversions that would emit
  a document outside the export root. Unrelated operations are allowed silently
  (exit 0, no output).
* A blocked operation emits the standard PreToolUse deny response:
    {"hookSpecificOutput": {"hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": "<PMO-EXPORT-0XX>: <reason>"}}
* Every validator is importable and callable directly, so the artifact-export
  skill can run the same checks as post-generation validation (source-hash
  unchanged, DOCX structure, internal-content scan, manifest integrity,
  identifier reconciliation, PMO-state protection). The script does not register
  itself; wiring into .claude/settings.json is a separate, deliberate step.

Error IDs
---------
PMO-EXPORT-001  SOURCE_NOT_FOUND            - the authoritative Markdown source
                                             does not exist / is unreadable.
PMO-EXPORT-002  SOURCE_NOT_READY           - project / workflow state does not
                                             authorise distribution of the
                                             source for the requested audience.
                                             A DRAFT_CLIENT_REVIEW Scope client
                                             export requires
                                             artifacts.scope.latest_version ==
                                             source version,
                                             workflow.scope.pm_review COMPLETE,
                                             workflow.scope.client_review
                                             PENDING and
                                             workflow.current_stage
                                             SCOPE_READY_FOR_CLIENT_REVIEW.
                                             workflow.scope.approved is NOT
                                             required for that export.
PMO-EXPORT-003  VERSION_MISMATCH           - the source filename version, the
                                             source metadata version and the
                                             requested export version do not all
                                             agree.
PMO-EXPORT-004  PROJECT_IDENTITY_MISMATCH  - source Project / Project ID /
                                             Client != .pmo/project-config.yaml
                                             (project-config is the authority;
                                             conversation history is not).
PMO-EXPORT-005  SUBSTANTIVE_CONTENT_DRIFT  - the source Markdown changed during
                                             the export operation, or a governed
                                             identifier present in the source is
                                             missing from / added to the export
                                             with no permitted reason, or a
                                             protected PMO state value changed as
                                             a side effect of the export.
PMO-EXPORT-006  INTERNAL_CONTENT_LEAK      - a CLIENT-audience export exposes a
                                             known internal PMO-automation marker
                                             (.claude/ , .pmo/ , a *-guard.py
                                             hook name, a PMO-*- code, hook
                                             payload keys, parser / test-suite
                                             wording, "Claude Code").
PMO-EXPORT-007  OUTPUT_GENERATION_FAILED   - the generated file is missing /
                                             empty / has the wrong extension /
                                             is not a readable DOCX package, or
                                             the export target is outside
                                             docs/pmo/exports/.
PMO-EXPORT-008  MANIFEST_VALIDATION_FAILED - export-manifest.json is not valid
                                             JSON, is missing a required record
                                             field, has substantive_content_changed
                                             != false, records a source_hash that
                                             does not match the current source,
                                             or appears to embed a secret.
PMO-EXPORT-009  EXISTING_EXPORT_COLLISION  - the requested export path already
                                             exists and the operation is not an
                                             authorised same-version regeneration.
PMO-EXPORT-010  EXPORT_INTERNAL_ERROR      - an unexpected exception during a
                                             controlled export validation
                                             (fail closed - never fail open).

Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
import xml.etree.ElementTree as ET
import zipfile


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

CONFIG_RELPATH = os.path.join(".pmo", "project-config.yaml")
EXPORT_DIR_POSIX = "docs/pmo/exports"
MANIFEST_POSIX = "docs/pmo/exports/export-manifest.json"
MANIFEST_BASENAME = "export-manifest.json"
EXPORT_DOC_EXTS = (".docx", ".pdf")

# Authoritative PMO Markdown sources this guard recognises, most specific first.
SOURCE_PATTERNS = (
    (re.compile(r"(?:^|/)docs/pmo/intent/intent\.md$"), "INTENT"),
    (re.compile(r"(?:^|/)docs/pmo/scope/scope-v\d+\.\d+\.md$"), "SCOPE"),
    (re.compile(r"(?:^|/)docs/pmo/cr/[^/]+\.md$"), "CHANGE_REQUEST"),
    (re.compile(r"(?:^|/)docs/pmo/feedback/[^/]+\.md$"), "FEEDBACK"),
    (re.compile(r"(?:^|/)docs/pmo/specs/[^/]+\.md$"), "SPEC_SUMMARY"),
    (re.compile(r"(?:^|/)docs/pmo/[^/]*handover[^/]*\.md$", re.I), "HANDOVER"),
)

REQUIRED_MANIFEST_FIELDS = (
    "project_id", "source_artifact", "source_version", "source_status",
    "source_hash", "artifact_type", "audience", "export_format", "export_path",
    "generated_at", "generated_by", "substantive_content_changed",
)

CLIENT_AUDIENCES = ("CLIENT", "STAKEHOLDER", "EXECUTIVE")

# Governed substantive identifier namespaces reconciled between source and export.
_GOVERNED_ID_RE = re.compile(
    r"(?<![A-Za-z0-9-])("
    r"(?:TRACE-INT-REQ|BRAND-OPEN|SCP-OPEN|SCP-REQ|SCP-ASM|SCP-DEP|SCP-GAP|"
    r"SCP-OOS|SCP-RISK|SCP-CONFLICT|INT-OOS|INT-REQ|CLIENT-RESP|DELIVERY-RESP|"
    r"OPEN|WBS|INTG|PSE|CRQ|WF)-\d+(?:\.\d+)*"
    r")(?![A-Za-z0-9-])"
)

# Internal PMO-automation markers that must never appear in a CLIENT export.
_LEAK_LITERALS = (
    ".claude/", ".claude\\", ".pmo/", ".pmo\\",
    "scope-version-guard.py", "intent-schema-guard.py",
    "repo-binding-guard.py", "artifact-export-guard.py",
    "pmo-scope-", "pmo-intent-", "pmo-repo-", "pmo-export-",
    "hookeventname", "permissiondecision", "pretooluse", "posttooluse",
)
_LEAK_PHRASES = ("parser logic", "test suite", "regression test", "claude code")

_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|password\s*[:=]|bearer\s+[A-Za-z0-9._-]{12,}"
    r"|-----BEGIN|AKIA[0-9A-Z]{16}|xox[baprs]-[0-9A-Za-z-]{10,})"
)
_LONG_HEX_RE = re.compile(r"\b[0-9a-fA-F]{40,}\b")

_VER_RE = re.compile(r"^\s*[vV]?(\d+)\.(\d+)\s*$")
_EXPORT_VER_RE = re.compile(r"-[vV](\d+\.\d+)\.(?:docx|pdf)$")


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
# Minimal YAML subset parser (stdlib only) - ported from the Scope guard
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


def _is_under_export_root(p, root):
    try:
        ap = _abspath(p, root)
        er = os.path.abspath(os.path.join(root, EXPORT_DIR_POSIX))
        return os.path.commonpath([ap, er]) == er
    except Exception:
        return False


def _same_export_path(a, b, root):
    if not a or not b:
        return False
    return _abspath(a, root) == _abspath(b, root)


# --------------------------------------------------------------------------- #
# Small scalar helpers
# --------------------------------------------------------------------------- #

def _clean(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _up(value):
    v = _clean(value if isinstance(value, str) else (str(value) if value is not None else None))
    return v.upper() if v else None


def _norm_token(value):
    if value is None:
        return None
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(value).strip().upper()).strip("_")
    return s or None


def _norm_ver(value):
    m = _VER_RE.match(str(value or ""))
    if not m:
        return None
    return "{}.{}".format(int(m.group(1)), int(m.group(2)))


def _dig(data, path):
    cur = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _unescape_xml(text):
    if not text:
        return ""
    out = (text.replace("&lt;", "<").replace("&gt;", ">")
           .replace("&quot;", '"').replace("&apos;", "'"))
    out = re.sub(r"&#x([0-9A-Fa-f]+);", lambda m: chr(int(m.group(1), 16)), out)
    out = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), out)
    return out.replace("&amp;", "&")


# --------------------------------------------------------------------------- #
# Source metadata
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


def parse_source_metadata(content):
    """Document-control fields of a PMO Markdown artifact (best effort)."""
    meta = {}
    for label in ("Project ID", "Project Name", "Project", "Client", "PM",
                  "Status", "Scope Version", "Intent Version", "Version",
                  "Date", "Artifact Type"):
        v = _find_field(content, label)
        if v is not None:
            meta[label.lower()] = v
    if "project" not in meta and "project name" in meta:
        meta["project"] = meta["project name"]
    return meta


def detect_artifact_type(source_rel):
    """Governed artifact type for a source path, or None when unrecognised."""
    rel = (source_rel or "").replace(os.sep, "/")
    for rx, atype in SOURCE_PATTERNS:
        if rx.search(rel):
            return atype
    return None


def source_version(source_rel, artifact_type, meta):
    """The authoritative version string for the source (e.g. '0.1')."""
    rel = (source_rel or "").replace(os.sep, "/")
    meta = meta or {}
    if artifact_type == "SCOPE":
        m = re.search(r"scope-v(\d+\.\d+)\.md$", rel)
        return _norm_ver(meta.get("scope version")) or (m.group(1) if m else None)
    if artifact_type == "INTENT":
        return _norm_ver(meta.get("intent version"))
    return (_norm_ver(meta.get("version"))
            or _norm_ver(meta.get("scope version"))
            or _norm_ver(meta.get("intent version")))


def export_version_from_path(export_path):
    m = _EXPORT_VER_RE.search(os.path.basename(export_path or ""))
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# Hashing / source immutability
# --------------------------------------------------------------------------- #

def calculate_sha256(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def capture_source_state(path):
    """Snapshot used to prove the source is byte-identical after an export."""
    ap = os.path.abspath(path or "")
    return {
        "path": ap,
        "sha256": calculate_sha256(ap),
        "size": os.path.getsize(ap) if os.path.exists(ap) else None,
    }


def validate_source_unchanged(pre_state, path=None):
    """PMO-EXPORT-005 - the authoritative source must not change during export."""
    pre_state = pre_state or {}
    target = path or pre_state.get("path")
    if not pre_state.get("sha256"):
        return deny("PMO-EXPORT-005",
                    "no pre-export source hash was captured; cannot prove the "
                    "authoritative source is unchanged.")
    now = calculate_sha256(target)
    if now is None:
        return deny("PMO-EXPORT-005",
                    "the authoritative source '{}' is no longer readable after "
                    "export.".format(target))
    if now != pre_state["sha256"]:
        return deny(
            "PMO-EXPORT-005",
            "the authoritative source changed during export (pre {}..., post "
            "{}...). The exporter must never modify the source; source "
            "correction belongs to the owning PMO skill.".format(
                pre_state["sha256"][:12], now[:12]
            ),
        )
    return None


# --------------------------------------------------------------------------- #
# Project identity / readiness / version
# --------------------------------------------------------------------------- #

def validate_project_identity(meta, config):
    """PMO-EXPORT-004 - source identity must match .pmo/project-config.yaml."""
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
        doc_val = _clean((meta or {}).get(key))
        cfg_val = _clean(cfg_val)
        if not doc_val or not cfg_val:
            continue
        if doc_val.casefold() != cfg_val.casefold():
            return deny(
                "PMO-EXPORT-004",
                "source {} '{}' does not match .pmo/project-config.yaml ('{}'). "
                "project-config is the identity authority; conversation history "
                "is not.".format(label, doc_val, cfg_val),
            )
    return None


def validate_export_version(src_version, export_path, meta):
    """PMO-EXPORT-003 - source filename / source metadata / export filename
    versions must all agree."""
    ev = _norm_ver(export_version_from_path(export_path))
    mv = _norm_ver((meta or {}).get("scope version")
                   or (meta or {}).get("intent version")
                   or (meta or {}).get("version"))
    sv = _norm_ver(src_version)
    present = [("source", sv), ("source-metadata", mv), ("export-filename", ev)]
    present = [(k, v) for k, v in present if v]
    if len({v for _, v in present}) > 1:
        return deny(
            "PMO-EXPORT-003",
            "version disagreement: {}. The source filename version, the source "
            "metadata version and the requested export version must all "
            "match.".format(", ".join("{}={}".format(k, v) for k, v in present)),
        )
    return None


def validate_export_path(export_path, root):
    """PMO-EXPORT-007 - a generated export must live under docs/pmo/exports/."""
    if not _clean(export_path):
        return deny("PMO-EXPORT-007", "the export target path is empty.")
    if not _is_under_export_root(export_path, root):
        return deny(
            "PMO-EXPORT-007",
            "export target '{}' is outside the PMO export root "
            "docs/pmo/exports/. Exports must be written only under "
            "docs/pmo/exports/<artifact-type>/.".format(
                _relpath(export_path, root)
            ),
        )
    return None


def validate_source_readiness(artifact_type, meta, config, src_version, audience):
    """PMO-EXPORT-001 / PMO-EXPORT-002 - the source exists and the project /
    workflow state authorises distribution for the requested audience.

    Approval is NOT required for a DRAFT_CLIENT_REVIEW client-review export.
    """
    status = _norm_token((meta or {}).get("status"))
    if not status:
        return deny("PMO-EXPORT-002",
                    "the source declares no Status; an export requires a known "
                    "artifact status.")
    cfg = config if isinstance(config, dict) else {}
    wf = cfg.get("workflow") if isinstance(cfg.get("workflow"), dict) else {}
    arts = cfg.get("artifacts") if isinstance(cfg.get("artifacts"), dict) else {}
    aud = _up(audience) or ""

    if artifact_type == "SCOPE":
        sc_art = arts.get("scope") if isinstance(arts.get("scope"), dict) else {}
        sc_wf = wf.get("scope") if isinstance(wf.get("scope"), dict) else {}
        if status == "DRAFT_CLIENT_REVIEW" and aud in CLIENT_AUDIENCES:
            lv = _clean(sc_art.get("latest_version"))
            if src_version and lv and _norm_ver(lv) != _norm_ver(src_version):
                return deny(
                    "PMO-EXPORT-002",
                    "project-config artifacts.scope.latest_version ('{}') is "
                    "not the source version ('{}').".format(lv, src_version),
                )
            if _up(sc_wf.get("pm_review")) != "COMPLETE":
                return deny(
                    "PMO-EXPORT-002",
                    "workflow.scope.pm_review is not COMPLETE - a client-review "
                    "export requires a completed PM semantic review.",
                )
            if _up(sc_wf.get("client_review")) != "PENDING":
                return deny(
                    "PMO-EXPORT-002",
                    "workflow.scope.client_review is not PENDING.",
                )
            if _norm_token(wf.get("current_stage")) != "SCOPE_READY_FOR_CLIENT_REVIEW":
                return deny(
                    "PMO-EXPORT-002",
                    "workflow.current_stage is not "
                    "SCOPE_READY_FOR_CLIENT_REVIEW.",
                )
            return None  # workflow.scope.approved is deliberately NOT required
        if status == "APPROVED":
            av = _clean(sc_art.get("approved_version"))
            if src_version and av and _norm_ver(av) != _norm_ver(src_version):
                return deny(
                    "PMO-EXPORT-002",
                    "source is APPROVED but project-config "
                    "artifacts.scope.approved_version ('{}') != source version "
                    "('{}').".format(av, src_version),
                )
            return None
        if status in ("PM_REVIEWED", "CLIENT_FEEDBACK_RECEIVED", "DRAFT",
                      "DRAFT_CLIENT_REVIEW", "SUPERSEDED"):
            if aud and aud != "INTERNAL":
                return deny(
                    "PMO-EXPORT-002",
                    "source Status '{}' is an internal / in-progress state and "
                    "is not eligible for a '{}' export (only INTERNAL).".format(
                        status, aud
                    ),
                )
            return None
        return deny("PMO-EXPORT-002",
                    "source Status '{}' does not authorise a Scope "
                    "export.".format(status))

    if artifact_type == "INTENT":
        in_art = arts.get("intent") if isinstance(arts.get("intent"), dict) else {}
        in_wf = wf.get("intent") if isinstance(wf.get("intent"), dict) else {}
        if status == "VALIDATED":
            if in_wf.get("approved") is not True:
                return deny("PMO-EXPORT-002",
                            "workflow.intent.approved is not true.")
            if _clean(in_art.get("status")) and _up(in_art.get("status")) != "VALIDATED":
                return deny("PMO-EXPORT-002",
                            "artifacts.intent.status is not VALIDATED.")
            return None
        if aud and aud != "INTERNAL":
            return deny(
                "PMO-EXPORT-002",
                "Intent Status '{}' is not VALIDATED; not eligible for a '{}' "
                "export (only INTERNAL).".format(status, aud),
            )
        return None

    # Other artifact types: do not invent an approval gate. Block only an
    # obvious work-in-progress state for a non-INTERNAL audience.
    if aud and aud != "INTERNAL" and status in ("DRAFT", "WIP", "IN_PROGRESS",
                                                "IN_REVIEW", "SUPERSEDED"):
        return deny(
            "PMO-EXPORT-002",
            "source Status '{}' is not eligible for a '{}' export.".format(
                status, aud
            ),
        )
    return None


def resolve_source(source_rel, root):
    """(abspath, text) for the authoritative source, or (abspath, None)."""
    ap = _abspath(source_rel, root)
    return ap, read_text(ap)


def pre_export_check(source_rel, export_path, audience, root, artifact_type=None):
    """Composite PreToolUse gate: PMO-EXPORT-001..004 + export-path validity."""
    ap, text = resolve_source(source_rel, root)
    if text is None:
        return deny("PMO-EXPORT-001",
                    "authoritative source '{}' does not exist or is "
                    "unreadable.".format(_relpath(source_rel, root)))
    atype = artifact_type or detect_artifact_type(source_rel)
    meta = parse_source_metadata(text)
    config = parse_project_config_file(root)
    sv = source_version(source_rel, atype, meta)
    for check in (
        validate_source_readiness(atype, meta, config, sv, audience),
        validate_project_identity(meta, config),
        validate_export_version(sv, export_path, meta),
        validate_export_path(export_path, root),
    ):
        if check is not None:
            return check
    return None


# --------------------------------------------------------------------------- #
# DOCX structure / text extraction
# --------------------------------------------------------------------------- #

def validate_docx_package(path):
    """PMO-EXPORT-007 - the generated DOCX is a structurally readable
    OpenXML package (no Microsoft Word required)."""
    if not path or not os.path.exists(path):
        return deny("PMO-EXPORT-007",
                    "expected export '{}' does not exist.".format(path))
    try:
        size = os.path.getsize(path)
    except Exception:
        size = 0
    if size == 0:
        return deny("PMO-EXPORT-007",
                    "generated export '{}' is zero bytes.".format(path))
    if not path.lower().endswith(".docx"):
        return deny("PMO-EXPORT-007",
                    "'{}' does not have the requested .docx extension.".format(path))
    if not zipfile.is_zipfile(path):
        return deny("PMO-EXPORT-007",
                    "'{}' is not a readable ZIP / OpenXML package.".format(path))
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "[Content_Types].xml" not in names:
                return deny("PMO-EXPORT-007",
                            "DOCX package is missing [Content_Types].xml.")
            if "word/document.xml" not in names:
                return deny("PMO-EXPORT-007",
                            "DOCX package is missing word/document.xml.")
            try:
                ET.fromstring(zf.read("word/document.xml"))
            except Exception as exc:
                return deny("PMO-EXPORT-007",
                            "word/document.xml is not parseable XML "
                            "({}).".format(exc))
    except zipfile.BadZipFile:
        return deny("PMO-EXPORT-007",
                    "'{}' is a corrupt ZIP package.".format(path))
    return None


def extract_docx_text(path):
    """Best-effort plain text of a DOCX for deterministic content scanning."""
    parts = []
    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                low = name.lower()
                if not low.endswith(".xml"):
                    continue
                if not (low.startswith("word/") or low.startswith("docprops/")):
                    continue
                try:
                    raw = zf.read(name).decode("utf-8", "replace")
                except Exception:
                    continue
                for m in re.finditer(r"<w:t[^>]*>(.*?)</w:t>", raw, re.S):
                    parts.append(_unescape_xml(m.group(1)))
                # fallback: field codes, hyperlink targets, doc properties
                parts.append(_unescape_xml(re.sub(r"<[^>]+>", " ", raw)))
    except Exception:
        return ""
    return "\n".join(parts)


def extract_text_for_scan(path):
    """Text of an export document for scanning; DOCX via zip, others via bytes."""
    low = (path or "").lower()
    if low.endswith(".docx"):
        return extract_docx_text(path)
    try:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", "replace")
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Internal-content leakage / identifier reconciliation
# --------------------------------------------------------------------------- #

def detect_internal_content(text, audience="CLIENT"):
    """PMO-EXPORT-006 - a CLIENT-audience export must not expose internal
    PMO-automation markers."""
    if _up(audience) not in CLIENT_AUDIENCES:
        return None
    low = (text or "").lower()
    hits = sorted(
        {lit for lit in _LEAK_LITERALS if lit in low}
        | {ph for ph in _LEAK_PHRASES if ph in low}
    )
    if hits:
        return deny(
            "PMO-EXPORT-006",
            "the {}-audience export exposes internal PMO-automation marker(s): "
            "{}. Remove PMO-framework implementation detail from the "
            "client-facing document (the Markdown source stays "
            "unchanged).".format(_up(audience), ", ".join(hits)),
        )
    return None


def extract_governed_identifiers(text):
    """{namespace -> set(full identifiers)} for governed substantive ids."""
    out = {}
    for m in _GOVERNED_ID_RE.finditer(text or ""):
        ident = m.group(1)
        ns = ident.rsplit("-", 1)[0]
        out.setdefault(ns, set()).add(ident)
    return out


def _flatten_ids(mapping):
    all_ids = set()
    for group in (mapping or {}).values():
        all_ids |= group
    return all_ids


def validate_identifier_reconciliation(source_text, export_text,
                                      audience="CLIENT", allowed_missing=None):
    """PMO-EXPORT-005 - governed identifiers in the source must remain
    represented in the export, and the export must not add / renumber any."""
    allowed = {i.strip() for i in (allowed_missing or ()) if i and i.strip()}
    src = _flatten_ids(extract_governed_identifiers(source_text))
    exp = _flatten_ids(extract_governed_identifiers(export_text))
    missing = sorted((src - exp) - allowed)
    added = sorted(exp - src)
    if missing:
        return deny(
            "PMO-EXPORT-005",
            "governed identifier(s) present in the source are absent from the "
            "exported content: {}. Export is presentational only - identifiers "
            "must not be dropped or renumbered. Pass an explicit allowed-missing "
            "set only for identifiers deliberately excluded from this "
            "audience.".format(", ".join(missing)),
        )
    if added:
        return deny(
            "PMO-EXPORT-005",
            "the exported content introduces governed identifier(s) not present "
            "in the source: {}. Export must not add or renumber "
            "identifiers.".format(", ".join(added)),
        )
    return None


# --------------------------------------------------------------------------- #
# Manifest integrity
# --------------------------------------------------------------------------- #

def read_export_manifest(root):
    """(data, parse_error). data is None when the manifest is absent."""
    text = read_text(os.path.join(root, MANIFEST_POSIX))
    if text is None:
        return None, None
    try:
        return json.loads(text), None
    except Exception as exc:
        return None, str(exc)


def _manifest_records(manifest_data):
    if isinstance(manifest_data, dict):
        recs = manifest_data.get("exports")
        return recs if isinstance(recs, list) else None
    if isinstance(manifest_data, list):
        return manifest_data
    return None


def validate_manifest(manifest_data, root=None, expect_record_for=None,
                      parse_error=None, require_present=True):
    """PMO-EXPORT-008 - export-manifest.json is valid JSON, every record is
    complete, substantive_content_changed is exactly false, no secret is
    embedded, and (when root is given) source_hash matches the current source."""
    if parse_error is not None:
        return deny("PMO-EXPORT-008",
                    "export-manifest.json is not valid JSON "
                    "({}).".format(parse_error))
    if manifest_data is None:
        if require_present:
            return deny("PMO-EXPORT-008",
                        "export-manifest.json is missing; a successful export "
                        "must record a manifest entry.")
        return None
    records = _manifest_records(manifest_data)
    if records is None:
        return deny("PMO-EXPORT-008",
                    "export-manifest.json must be an object with an 'exports' "
                    "list (or a bare list of records).")
    if not records:
        return deny("PMO-EXPORT-008",
                    "export-manifest.json has no export records.")
    for idx, rec in enumerate(records, 1):
        if not isinstance(rec, dict):
            return deny("PMO-EXPORT-008",
                        "export-manifest.json record #{} is not an "
                        "object.".format(idx))
        label = rec.get("export_path") or "record #{}".format(idx)
        missing = [k for k in REQUIRED_MANIFEST_FIELDS
                   if k != "substantive_content_changed"
                   and (k not in rec or rec[k] in (None, ""))]
        if "substantive_content_changed" not in rec:
            missing.append("substantive_content_changed")
        if missing:
            return deny("PMO-EXPORT-008",
                        "export-manifest.json record for '{}' is missing "
                        "field(s): {}.".format(label, ", ".join(missing)))
        if rec.get("substantive_content_changed") is not False:
            return deny(
                "PMO-EXPORT-008",
                "export-manifest.json record for '{}' has "
                "substantive_content_changed={!r}; it must be exactly "
                "false.".format(label, rec.get("substantive_content_changed")),
            )
        for key, val in rec.items():
            if key == "source_hash" or not isinstance(val, str):
                continue
            if _SECRET_RE.search(val) or _LONG_HEX_RE.search(val):
                return deny(
                    "PMO-EXPORT-008",
                    "export-manifest.json record for '{}' field '{}' looks like "
                    "it embeds a secret; manifests must carry only export "
                    "metadata.".format(label, key),
                )
        if root is not None and (
            expect_record_for is None
            or _same_export_path(rec.get("export_path"), expect_record_for, root)
        ):
            recorded = str(rec.get("source_hash") or "")
            if recorded.lower().startswith("sha256:"):
                recorded = recorded.split(":", 1)[1]
            actual = calculate_sha256(_abspath(rec.get("source_artifact"), root))
            if actual is None:
                return deny(
                    "PMO-EXPORT-008",
                    "export-manifest.json record for '{}' references source '{}' "
                    "which cannot be read to verify source_hash.".format(
                        label, rec.get("source_artifact")
                    ),
                )
            if recorded.lower() != actual.lower():
                return deny(
                    "PMO-EXPORT-008",
                    "export-manifest.json source_hash for '{}' ({}...) does not "
                    "match the current SHA-256 of {} ({}...).".format(
                        label, recorded[:12] or "<empty>",
                        rec.get("source_artifact"), actual[:12]
                    ),
                )
    return None


def check_manifest_file(root, expect_record_for=None, require_present=True):
    data, err = read_export_manifest(root)
    return validate_manifest(data, root=root, expect_record_for=expect_record_for,
                             parse_error=err, require_present=require_present)


# --------------------------------------------------------------------------- #
# Collision / PMO-state protection
# --------------------------------------------------------------------------- #

def detect_export_collision(export_path, root, regeneration_authorized=False,
                            src_version=None, manifest_data=None):
    """PMO-EXPORT-009 - never silently overwrite an existing export."""
    ap = _abspath(export_path, root)
    if not ap or not os.path.exists(ap):
        return None
    if not regeneration_authorized:
        return deny(
            "PMO-EXPORT-009",
            "an export already exists at '{}'. Do not overwrite it silently - "
            "confirm an authorised regeneration of the same source version, or "
            "bump the source version.".format(_relpath(export_path, root)),
        )
    if src_version and manifest_data is not None:
        for rec in (_manifest_records(manifest_data) or []):
            if not isinstance(rec, dict):
                continue
            if _same_export_path(rec.get("export_path"), export_path, root):
                rv = _norm_ver(str(rec.get("source_version") or ""))
                if rv and rv != _norm_ver(src_version):
                    return deny(
                        "PMO-EXPORT-009",
                        "regeneration of '{}' is authorised but the recorded "
                        "source version ({}) differs from the requested version "
                        "({}); a different source version must be exported under "
                        "its own filename.".format(
                            _relpath(export_path, root), rv, src_version
                        ),
                    )
    return None


_PROTECTED_STATE_PATHS = (
    ("workflow", "current_stage"),
    ("workflow", "intent", "approved"),
    ("workflow", "scope", "approved"),
    ("artifacts", "intent", "latest_version"),
    ("artifacts", "scope", "latest_version"),
    ("artifacts", "scope", "approved_version"),
    ("artifacts", "specifications", "status"),
)


def validate_pmo_state_unchanged(before_text, after_text):
    """PMO-EXPORT-005 - an export must not advance PMO approval / workflow
    state. Compares protected project-config values before vs after."""
    try:
        before = parse_project_config(before_text or "")
        after = parse_project_config(after_text or "")
    except Exception as exc:
        return deny("PMO-EXPORT-010",
                    "could not parse project-config for state comparison "
                    "({}).".format(exc))
    changed = [".".join(p) for p in _PROTECTED_STATE_PATHS
               if _dig(before, p) != _dig(after, p)]
    if changed:
        return deny(
            "PMO-EXPORT-005",
            "the export operation changed protected PMO state: {}. Export "
            "records export metadata only - it must not advance approval or "
            "workflow state.".format(", ".join(changed)),
        )
    return None


# --------------------------------------------------------------------------- #
# Post-generation validation (reusable by the artifact-export skill)
# --------------------------------------------------------------------------- #

def post_export_validation(source_rel, export_path, root, audience="CLIENT",
                           pre_state=None, allowed_missing=None,
                           expect_manifest_record=True):
    """Run every deterministic post-generation check in order. Returns a
    Decision on the first failure, or None when the export is clean."""
    ap_src, src_text = resolve_source(source_rel, root)
    ap_export = _abspath(export_path, root)

    if pre_state is not None:
        chk = validate_source_unchanged(pre_state, ap_src)
        if chk is not None:
            return chk

    if ap_export.lower().endswith(".docx"):
        chk = validate_docx_package(ap_export)
        if chk is not None:
            return chk
    elif not os.path.exists(ap_export) or os.path.getsize(ap_export) == 0:
        return deny("PMO-EXPORT-007",
                    "generated export '{}' is missing or empty.".format(
                        _relpath(export_path, root)))

    export_text = extract_text_for_scan(ap_export)

    chk = detect_internal_content(export_text, audience)
    if chk is not None:
        return chk

    if src_text is not None:
        chk = validate_identifier_reconciliation(
            src_text, export_text, audience, allowed_missing)
        if chk is not None:
            return chk

    chk = check_manifest_file(root, expect_record_for=export_path,
                              require_present=expect_manifest_record)
    if chk is not None:
        return chk
    return None


# --------------------------------------------------------------------------- #
# Shell command splitting (ported from the Scope guard)
# --------------------------------------------------------------------------- #

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
    base = os.path.basename(path)
    ext = os.path.splitext(base)[1].lower()

    # A generated export document (.docx / .pdf).
    if ext in EXPORT_DOC_EXTS:
        bad = validate_export_path(path, root)
        if bad is not None:
            return bad
        if os.path.exists(_abspath(path, root)):
            return deny(
                "PMO-EXPORT-009",
                "an export already exists at '{}'. Overwriting requires an "
                "explicit authorised regeneration performed by the "
                "artifact-export skill (which re-checks the source version and "
                "updates the manifest).".format(_relpath(path, root)),
            )
        return None

    # The export manifest.
    if base == MANIFEST_BASENAME and _is_under_export_root(path, root):
        new_content = resulting_content(
            tool_name, tool_input, read_text(_abspath(path, root)))
        if new_content is None or not new_content.strip():
            return deny("PMO-EXPORT-008",
                        "export-manifest.json must not be written empty.")
        try:
            data = json.loads(new_content)
        except Exception as exc:
            return deny("PMO-EXPORT-008",
                        "export-manifest.json is not valid JSON "
                        "({}).".format(exc))
        return validate_manifest(data, root=root, require_present=True)

    return None


def process_bash(command, root):
    if not isinstance(command, str) or not command.strip():
        return None
    low = command.lower()
    if not any(t in low for t in (".docx", ".pdf")):
        return None
    for seg in _split_segments(command):
        m = re.search(r">>?\s*([^\s|&;<>]+\.(?:docx|pdf))", seg, re.I)
        if m:
            bad = validate_export_path(m.group(1), root)
            if bad is not None:
                return bad
        toks = _tokenize(seg)
        if not toks:
            continue
        head = os.path.basename(toks[0]).lower()
        if head not in ("soffice", "libreoffice", "pandoc", "cp", "mv",
                        "rsync", "install", "tee"):
            continue
        outs, i = [], 0
        while i < len(toks):
            t = toks[i]
            if t in ("-o", "--output", "--outdir", "--out-dir") and i + 1 < len(toks):
                outs.append(toks[i + 1])
                i += 2
                continue
            if t.lower().endswith((".docx", ".pdf")):
                outs.append(t)
            i += 1
        for out in outs:
            if out.lower().endswith((".docx", ".pdf")) and not _is_under_export_root(out, root):
                return validate_export_path(out, root)
            if head in ("soffice", "libreoffice") and "--outdir" not in toks and "--out-dir" not in toks:
                # convert-to with no outdir writes next to the input
                pass
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
                "PMO-EXPORT-010",
                "unexpected internal error during controlled export validation "
                "({}). Blocking as a precaution.".format(exc),
            )

    if tool_name == "Bash":
        try:
            return process_bash(tool_input.get("command") or "", root)
        except Exception as exc:  # fail closed
            return deny(
                "PMO-EXPORT-010",
                "unexpected internal error validating an export command "
                "({}). Blocking as a precaution.".format(exc),
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
