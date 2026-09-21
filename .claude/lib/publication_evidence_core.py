"""PMO publication evidence - deterministic core.

Publication completion is governed, canonical, LOCAL state: a *publication
receipt* written by the artifact publisher only after a verified remote
publication (or, for a publication that pre-dates this mechanism, by the
publisher's governed `--reconcile` operation from live remote evidence).

Model
-----
* Location: `.pmo/publications/<family>-v<version>-<sha256[:12]>.yaml`
  (one immutable file per published version+content; earlier receipts stay
  as history and are never rewritten or deleted).
* A receipt is EVIDENCE ONLY. It never carries Specs content and is never a
  source of truth for it; it proves one approved version/hash was published
  to one repository/branch at one remote commit.
* Lifecycle detection never touches the network: it reads receipts and
  compares them to the current canonical artifact.

A publication counts as complete for the CURRENT artifact only when a
structurally valid receipt exists whose project, family, artifact path,
version and sha256 all equal the current artifact's, whose repository and
branch equal the project's current routing, whose status is PUBLISHED with
remote_verified true, and whose remote commit is a full 40-hex object id.
Anything else (wrong project/family/path/version/hash/target, unverified or
failed status, malformed fields) is rejected with a reason - a stale receipt
can never authorize a different version or different bytes.

Version extraction lives here too (`artifact_version`) so the publisher and
the lifecycle share one implementation of "what version is this artifact",
reusing the authoritative document-control parsers.

Python 3, standard library only.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import intent_approval_core as iac  # noqa: E402
import specs_approval_core as sac  # noqa: E402
import artifact_publish_core as apc  # noqa: E402

PUBLICATIONS_DIR_PARTS = (".pmo", "publications")
RECEIPT_TYPE = "ARTIFACT_PUBLICATION"
RECEIPT_STATUS_PUBLISHED = "PUBLISHED"
EVIDENCE_SOURCES = ("PUBLISHER_TRANSACTION", "RECONCILED_FROM_REMOTE")
REQUIRED_FIELDS = (
    "schema_version", "receipt_type", "status", "project_id", "artifact_family",
    "artifact", "version", "artifact_sha256", "provider", "workspace",
    "repository", "branch", "remote_commit", "remote_verified", "published_at",
    "evidence_source",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_VERSION_RE = re.compile(r"^\d+(?:\.\d+)*$")
_clean = iac._clean


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    return apc.sha256_of_file(path)


def publications_dir(root):
    return os.path.join(root, *PUBLICATIONS_DIR_PARTS)


# --------------------------------------------------------------------------- #
# Version extraction (single implementation, authoritative parsers)
# --------------------------------------------------------------------------- #

def artifact_version(family, text, cfg=None):
    """Version of a governed artifact, read from the ARTIFACT'S OWN document
    control via the authoritative parser; falls back to the legacy
    project-config value only when the artifact carries none. 'unknown' when
    nothing is available."""
    version = None
    if family == "specs":
        version = _clean(sac.parse_spec_doc_control(text or "").get("spec_version"))
    elif family == "intent":
        version = _clean(iac.parse_doc_control(text or "").get("intent version"))
    if version:
        return version
    if isinstance(cfg, dict):
        key = {"intent": "intent", "specs": "specifications", "scope": "scope"}.get(family)
        sub = (cfg.get("artifacts") or {}).get(key) if key else None
        if isinstance(sub, dict):
            legacy = (_clean(sub.get("approved_version")) if family == "scope" else "") \
                or _clean(sub.get("latest_version"))
            if legacy:
                return legacy
    return "unknown"


# --------------------------------------------------------------------------- #
# Receipt rendering / writing / loading
# --------------------------------------------------------------------------- #

def receipt_filename(family, version, artifact_sha256):
    return "{}-v{}-{}.yaml".format(family, version, artifact_sha256[:12])


def build_receipt(project_id, family, artifact, version, artifact_sha256, fields,
                  remote_commit, published_at, evidence_source="PUBLISHER_TRANSACTION"):
    return {
        "schema_version": "1.0",
        "receipt_type": RECEIPT_TYPE,
        "status": RECEIPT_STATUS_PUBLISHED,
        "project_id": project_id,
        "artifact_family": family,
        "artifact": artifact,
        "version": version,
        "artifact_sha256": artifact_sha256,
        "provider": fields["provider"],
        "workspace": fields["workspace"],
        "repository": fields["repository"],
        "branch": fields["working_branch"],
        "remote_commit": remote_commit,
        "remote_verified": "true",
        "published_at": published_at,
        "evidence_source": evidence_source,
    }


def render_receipt_yaml(receipt):
    q = iac._yaml_quote
    lines = []
    for key in REQUIRED_FIELDS:
        lines.append("{}: {}".format(key, q(receipt[key])))
        if key == "schema_version":
            lines.append("")
    lines.append("")
    return "\n".join(lines)


def write_receipt(root, receipt):
    """(path, error). Refuses to overwrite an existing receipt with different
    content (receipts are immutable evidence). Atomic via rename."""
    err = validate_receipt_structure(receipt)
    if err:
        return None, "refusing to write an invalid receipt: {}".format(err)
    d = publications_dir(root)
    path = os.path.join(d, receipt_filename(
        receipt["artifact_family"], receipt["version"], receipt["artifact_sha256"]))
    text = render_receipt_yaml(receipt)
    try:
        os.makedirs(d, exist_ok=True)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                if fh.read() == text:
                    return path, None
            return None, "a different receipt already exists at {}.".format(path)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError as exc:
        return None, "could not write receipt: {}".format(exc)
    return path, None


def load_receipts(root, family):
    """[(filename, data-or-None, parse_error-or-None)] for every receipt file
    of `family`, sorted by name (deterministic)."""
    d = publications_dir(root)
    out = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not (name.startswith(family + "-v") and name.endswith(".yaml")):
            continue
        text = iac.read_text(os.path.join(d, name))
        try:
            data = iac.parse_simple_yaml(text or "")
        except Exception as exc:  # pragma: no cover - defensive
            out.append((name, None, "not parseable: {}".format(exc)))
            continue
        if not isinstance(data, dict):
            out.append((name, None, "did not parse to a mapping"))
            continue
        out.append((name, data, None))
    return out


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def validate_receipt_structure(data):
    """None when structurally valid, else an explanatory string."""
    missing = [f for f in REQUIRED_FIELDS if not _clean(data.get(f))]
    if missing:
        return "missing field(s): {}".format(", ".join(missing))
    if _clean(data["receipt_type"]) != RECEIPT_TYPE:
        return "receipt_type is not {}".format(RECEIPT_TYPE)
    if _clean(data["status"]) != RECEIPT_STATUS_PUBLISHED:
        return "status is '{}', not {} (an unverified/failed publication is not evidence)".format(
            data["status"], RECEIPT_STATUS_PUBLISHED)
    if _clean(data["remote_verified"]).lower() != "true":
        return "remote_verified is not true"
    if not _SHA256_RE.match(_clean(data["artifact_sha256"])):
        return "artifact_sha256 is not a sha256"
    if not _COMMIT_RE.match(_clean(data["remote_commit"])):
        return "remote_commit is not a full 40-hex object id"
    if not _TS_RE.match(_clean(data["published_at"])):
        return "published_at is not a UTC ISO-8601 timestamp"
    if not _VERSION_RE.match(_clean(data["version"])):
        return "version is not a valid artifact version"
    if _clean(data["evidence_source"]) not in EVIDENCE_SOURCES:
        return "evidence_source is not one of {}".format(", ".join(EVIDENCE_SOURCES))
    return None


def validate_receipt_matches(data, project_id, family, artifact, version,
                             artifact_sha256, fields):
    """None when `data` proves publication of exactly THIS artifact to the
    project's CURRENT routing; else the first mismatch."""
    err = validate_receipt_structure(data)
    if err:
        return err
    checks = (
        ("project_id", _clean(data["project_id"]).upper(), _clean(project_id).upper()),
        ("artifact_family", _clean(data["artifact_family"]), family),
        ("artifact", _clean(data["artifact"]), artifact),
        ("version", _clean(data["version"]), _clean(version)),
        ("artifact_sha256", _clean(data["artifact_sha256"]), artifact_sha256),
        ("provider", _clean(data["provider"]), fields["provider"]),
        ("workspace", _clean(data["workspace"]), fields["workspace"]),
        ("repository", _clean(data["repository"]), fields["repository"]),
        ("branch", _clean(data["branch"]), fields["working_branch"]),
    )
    for name, got, want in checks:
        if got != want:
            return "{} '{}' does not match the current '{}'".format(name, got, want)
    return None


def find_valid_publication(root, family, artifact, version, artifact_sha256):
    """(receipt-or-None, diag). Read-only; never uses the network.
    `diag` = {"considered": n, "rejected": [{"file", "reason"}]}."""
    cfg = iac.load_project_config(root) or {}
    project_id = _clean((cfg.get("project") or {}).get("id"))
    fields, ferr = apc.extract_repo_fields(cfg)
    diag = {"considered": 0, "rejected": []}
    if ferr is not None or not project_id:
        diag["rejected"].append({"file": None, "reason": "project identity or repository routing unavailable"})
        return None, diag
    found = None
    for name, data, perr in load_receipts(root, family):
        diag["considered"] += 1
        if perr:
            diag["rejected"].append({"file": name, "reason": perr})
            continue
        why = validate_receipt_matches(data, project_id, family, artifact,
                                       version, artifact_sha256, fields)
        if why:
            diag["rejected"].append({"file": name, "reason": why})
        elif found is None:
            found = data
    return found, diag
