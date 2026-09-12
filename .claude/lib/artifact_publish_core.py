#!/usr/bin/env python3
"""PMO Artifact Publish - shared deterministic validation core.

Purpose
-------
Claude Code PreToolUse hooks (``artifact-publish-guard.py``) only see Bash
commands the agent is about to run - they do NOT independently inspect Git
subprocesses a Python program launches internally. That means a standalone
publisher program (``artifact-publisher.py``) that shells out to `git`
itself is invisible to the hook. It must not rely on the hook for safety;
it must reuse the *same* deterministic validation as the hook.

This module is that shared core. It contains every piece of validation
logic that both the PreToolUse guard and the Artifact Publisher need:

* `.pmo/project-config.yaml` parsing and routing-field extraction
* provider / remote URL parsing and identity comparison
* managed publishing workspace path resolution (`Path.home()`-based,
  traversal-safe)
* the publishable-artifact allowlist and family classification
* authoritative-version resolution for artifact families that have more
  than one file on disk (Scope) - resolved from governed project state,
  never by lexicographic filename sorting
* SHA-256 hashing / byte-identity comparison
* source governance dispatch (Intent / Scope / Specs), read-only
* Git plumbing primitives (remote URL, status, staged names, current
  branch, `ls-remote` branch existence, error classification)
* Bash command parsing (quote-aware, `cd`-aware, wrapper-aware) used to
  find `git` invocations and their effective working directory
* the `add` / `commit` / `push` governance dispatch used by the guard
* a repository pre-flight bundle (`preflight_repository`) used by the
  Publisher before any mutation
* the canonical `PMO-PUBLISH-001..015` code -> name mapping

Contract
--------
* No import-time Git operations.
* No import-time filesystem mutation.
* No network action at import time.
* Every function here is a pure computation or an explicit, single Git
  read/query call made only when invoked - importing this module never
  does anything by itself.
* Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import glob
import hashlib
import importlib.util
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


# --------------------------------------------------------------------------- #
# Canonical PMO-PUBLISH-* code mapping
# --------------------------------------------------------------------------- #

PMO_PUBLISH_CODES = {
    "PMO-PUBLISH-001": "PROJECT_CONFIG_MISSING",
    "PMO-PUBLISH-002": "TARGET_REPOSITORY_UNREACHABLE",
    "PMO-PUBLISH-003": "AUTHENTICATION_FAILED",
    "PMO-PUBLISH-004": "REMOTE_IDENTITY_MISMATCH",
    "PMO-PUBLISH-005": "BRANCH_MISMATCH",
    "PMO-PUBLISH-006": "TARGET_WORKTREE_DIRTY",
    "PMO-PUBLISH-007": "UNAPPROVED_ARTIFACT_PATH",
    "PMO-PUBLISH-008": "SOURCE_ARTIFACT_NOT_VALID",
    "PMO-PUBLISH-009": "SOURCE_DESTINATION_HASH_MISMATCH",
    "PMO-PUBLISH-010": "UNRELATED_STAGED_FILE",
    "PMO-PUBLISH-011": "COMMIT_FAILED",
    "PMO-PUBLISH-012": "PUSH_FAILED",
    "PMO-PUBLISH-013": "FORCE_PUSH_ATTEMPT",
    "PMO-PUBLISH-014": "TARGET_BRANCH_NOT_FOUND",
    "PMO-PUBLISH-015": "PUBLISH_INTERNAL_ERROR",
}


def code_name(code):
    return PMO_PUBLISH_CODES.get(code, "UNKNOWN")


# --------------------------------------------------------------------------- #
# Decision / deny / allow
# --------------------------------------------------------------------------- #

class Decision(object):
    __slots__ = ("code", "message")

    def __init__(self, code, message):
        self.code = code
        self.message = message

    def __repr__(self):
        return "Decision({!r}, {!r})".format(self.code, self.message)

    def __str__(self):
        return "{}: {}".format(self.code, self.message)


def deny(code, message):
    return Decision(code, message)


def allow():
    return None


# --------------------------------------------------------------------------- #
# Minimal YAML subset parser (stdlib only)
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
# Project config / routing identity
# --------------------------------------------------------------------------- #

def _clean(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return None


def locate_project_root(cwd):
    """Walk upward from `cwd` looking for `.pmo/project-config.yaml`."""
    try:
        cur = Path(cwd).resolve()
    except Exception:
        return None
    for candidate in (cur, *cur.parents):
        if (candidate / ".pmo" / "project-config.yaml").is_file():
            return str(candidate)
    return None


def load_project_config(root):
    path = os.path.join(root, ".pmo", "project-config.yaml")
    text = read_text(path)
    if text is None:
        return None
    try:
        cfg = parse_simple_yaml(text)
    except Exception:
        return None
    return cfg if isinstance(cfg, dict) else None


_PROVIDER_HOSTS = {
    "github": ("github.com", "www.github.com"),
    "bitbucket": ("bitbucket.org", "www.bitbucket.org"),
    "gitlab": ("gitlab.com", "www.gitlab.com"),
}


def provider_from_host(host):
    host = (host or "").lower()
    for provider, hosts in _PROVIDER_HOSTS.items():
        if host in hosts:
            return provider
    for provider in _PROVIDER_HOSTS:
        if provider in host:
            return provider
    return None


def build_clone_url(fields, override=None):
    """Deterministic clone URL for a supported provider, derived only from
    `fields` (which itself comes only from project-config routing). `override`
    is a narrow, explicit testing seam - production code paths never pass it,
    so real usage always derives the URL from the configured provider, never
    a hardcoded host."""
    if override:
        return override
    host = {
        "github": "github.com",
        "bitbucket": "bitbucket.org",
        "gitlab": "gitlab.com",
    }.get(fields.get("provider"))
    if not host:
        return None
    return "git@{}:{}/{}.git".format(host, fields["workspace"], fields["repository"])


def extract_repo_fields(cfg):
    """Return (fields-dict, Decision-or-None). Fields are lower/clean strings."""
    repo = cfg.get("repository") if isinstance(cfg, dict) else None
    if not isinstance(repo, dict) or not repo:
        return None, deny(
            "PMO-PUBLISH-001",
            "PROJECT_CONFIG_MISSING: '.pmo/project-config.yaml' has no usable "
            "'repository:' section.",
        )

    provider = _clean(repo.get("provider"))
    workspace = _clean(repo.get("workspace"))
    repository = _clean(repo.get("repository"))
    working_branch = _clean(repo.get("working_branch"))

    missing = [
        name
        for name, value in (
            ("provider", provider),
            ("workspace", workspace),
            ("repository", repository),
            ("working_branch", working_branch),
        )
        if not value
    ]
    if missing:
        return None, deny(
            "PMO-PUBLISH-001",
            "PROJECT_CONFIG_MISSING: required repository routing field(s) "
            "missing/empty: {}.".format(", ".join(missing)),
        )

    if provider.lower() not in _PROVIDER_HOSTS:
        return None, deny(
            "PMO-PUBLISH-001",
            "PROJECT_CONFIG_MISSING: unsupported 'repository.provider' "
            "'{}' (supported: {}).".format(
                provider, "/".join(sorted(_PROVIDER_HOSTS))
            ),
        )

    return (
        {
            "provider": provider.lower(),
            "workspace": workspace,
            "repository": repository,
            "working_branch": working_branch,
        },
        None,
    )


def extract_project_name(cfg):
    project = cfg.get("project") if isinstance(cfg, dict) else None
    if isinstance(project, dict):
        name = _clean(project.get("name")) or _clean(project.get("id"))
        if name:
            return name
    return "Project"


def parse_remote_url(url):
    """Parse GitHub / Bitbucket / GitLab HTTPS or SSH remote URLs.

    Returns dict(host, workspace, repository) or None.
    """
    url = (url or "").strip()
    if not url:
        return None

    host = None
    path = None

    scp = re.match(r"^([A-Za-z0-9._~-]+@)?([^/:]+):(.+)$", url)
    if "://" not in url and scp and not url.startswith("/"):
        host = scp.group(2)
        path = scp.group(3)
    else:
        m = re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*://([^/]+)/(.+)$", url)
        if m:
            netloc = m.group(1)
            path = m.group(2)
            if "@" in netloc:
                netloc = netloc.split("@", 1)[1]
            host = netloc.split(":", 1)[0]
        else:
            # Local filesystem path (used by tests as a stand-in remote).
            if os.sep in url or url.startswith("."):
                norm = url.replace("\\", "/").rstrip("/")
                if norm.endswith(".git"):
                    norm = norm[:-4]
                segments = [seg for seg in norm.split("/") if seg]
                if len(segments) >= 2:
                    return {
                        "host": "local",
                        "workspace": segments[-2],
                        "repository": segments[-1],
                    }
            return None

    if not host or not path:
        return None

    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    path = path.strip("/")

    segments = [seg for seg in path.split("/") if seg]
    if len(segments) < 2:
        return None

    return {
        "host": host.lower(),
        "workspace": segments[0],
        "repository": segments[-1],
    }


def remote_identity_ok(remote_url, fields):
    """True iff `remote_url` resolves to the configured provider/workspace/
    repository. Local (file-path) remotes only check workspace/repository -
    used by the local-repo test suites as a stand-in for a real host."""
    parsed = parse_remote_url(remote_url)
    if parsed is None:
        return False
    provider_ok = (
        provider_from_host(parsed["host"]) == fields["provider"]
        or parsed["host"] == "local"
    )
    return (
        provider_ok
        and parsed["workspace"].casefold() == fields["workspace"].casefold()
        and parsed["repository"].casefold() == fields["repository"].casefold()
    )


# --------------------------------------------------------------------------- #
# Managed publishing workspace path
# --------------------------------------------------------------------------- #

_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _safe_segment(value):
    return bool(value) and bool(_SAFE_SEGMENT_RE.match(value)) and ".." not in value


def managed_workspace_path(provider, workspace, repository, branch, home=None):
    """Path or None (segment unsafe / path-traversal attempt)."""
    for seg in (provider, workspace, repository, branch):
        if not _safe_segment(seg):
            return None
    home_path = Path(home) if home is not None else Path.home()
    return home_path / ".pmo-workspaces" / provider / workspace / repository / branch


def resolve_expected_workspace(fields, home=None):
    """(Path-or-None, Decision-or-None) for a fields dict from extract_repo_fields."""
    path = managed_workspace_path(
        fields["provider"],
        fields["workspace"],
        fields["repository"],
        fields["working_branch"],
        home=home,
    )
    if path is None:
        return None, deny(
            "PMO-PUBLISH-001",
            "PROJECT_CONFIG_MISSING: repository routing field(s) contain "
            "unsafe or path-traversal characters; refusing to derive a "
            "managed workspace path from provider={!r} workspace={!r} "
            "repository={!r} working_branch={!r}.".format(
                fields.get("provider"),
                fields.get("workspace"),
                fields.get("repository"),
                fields.get("working_branch"),
            ),
        )
    return path, None


def managed_workspace_root(home=None):
    home_path = Path(home) if home is not None else Path.home()
    return home_path / ".pmo-workspaces"


def is_under_managed_workspace_root(path, home=None):
    root = managed_workspace_root(home)
    try:
        candidate = Path(path).expanduser().resolve(strict=False)
        root_resolved = root.expanduser().resolve(strict=False)
    except Exception:
        return False
    try:
        candidate.relative_to(root_resolved)
        return True
    except ValueError:
        return candidate == root_resolved


# --------------------------------------------------------------------------- #
# Artifact allowlist / canonical Specs path / family resolution
# --------------------------------------------------------------------------- #

_ALLOWED_PREFIXES = (
    "docs/pmo/intent/",
    "docs/pmo/scope/",
    "docs/pmo/feedback/",
    "docs/pmo/change-requests/",
)
_CANONICAL_SPECS_PATH = "docs/pmo/specs/specs.md"
_CANONICAL_INTENT_PATH = "docs/pmo/intent/intent.md"

FAMILIES = ("intent", "scope", "specs", "feedback", "change-request")


def _norm_rel(path):
    p = (path or "").strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def is_allowlisted_path(path):
    rel = _norm_rel(path)
    if rel == _CANONICAL_SPECS_PATH:
        return True
    if rel.startswith("docs/pmo/specs/"):
        return False
    return any(rel.startswith(prefix) for prefix in _ALLOWED_PREFIXES)


def family_of(path):
    rel = _norm_rel(path)
    if rel.startswith("docs/pmo/intent/"):
        return "intent"
    if rel.startswith("docs/pmo/scope/"):
        return "scope"
    if rel == _CANONICAL_SPECS_PATH:
        return "specs"
    if rel.startswith("docs/pmo/feedback/"):
        return "feedback"
    if rel.startswith("docs/pmo/change-requests/"):
        return "change-requests"
    return None


def resolve_scope_source_relpath(root, cfg=None):
    """(relpath-or-None, Decision-or-None). Resolves the current
    authoritative Scope source file from governed project state
    (`.pmo/project-config.yaml` -> `artifacts.scope.approved_version`,
    falling back to `artifacts.scope.latest_version`) - never by
    lexicographic filename sorting of `docs/pmo/scope/scope-v*.md`."""
    if cfg is None:
        cfg = load_project_config(root)
    if not isinstance(cfg, dict):
        return None, deny(
            "PMO-PUBLISH-008",
            "SOURCE_ARTIFACT_NOT_VALID: '.pmo/project-config.yaml' could not "
            "be read/parsed; cannot determine the authoritative Scope "
            "version to publish.",
        )
    artifacts = cfg.get("artifacts")
    scope_cfg = artifacts.get("scope") if isinstance(artifacts, dict) else None
    if not isinstance(scope_cfg, dict):
        return None, deny(
            "PMO-PUBLISH-008",
            "SOURCE_ARTIFACT_NOT_VALID: '.pmo/project-config.yaml' has no "
            "usable 'artifacts.scope' section; cannot determine the "
            "authoritative Scope version to publish.",
        )
    version = _clean(scope_cfg.get("approved_version")) or _clean(scope_cfg.get("latest_version"))
    if not version:
        return None, deny(
            "PMO-PUBLISH-008",
            "SOURCE_ARTIFACT_NOT_VALID: neither 'artifacts.scope.approved_version' "
            "nor 'artifacts.scope.latest_version' is set in "
            "'.pmo/project-config.yaml'; cannot determine the authoritative "
            "Scope version to publish (never guessed from filename order).",
        )
    relpath = "docs/pmo/scope/scope-v{}.md".format(version)
    path = os.path.join(root, relpath)
    if not os.path.isfile(path):
        return None, deny(
            "PMO-PUBLISH-008",
            "SOURCE_ARTIFACT_NOT_VALID: the governed authoritative Scope "
            "source '{}' (version {}) does not exist on disk.".format(relpath, version),
        )
    return relpath, None


def resolve_family_source_relpath(family, root, cfg=None):
    """(relpath-or-None, Decision-or-None) - the canonical source path for
    `family` relative to the PMO Engine root `root`. Intent and Specs are
    fixed single files; Scope is resolved from governed project state via
    `resolve_scope_source_relpath`. Feedback / change-request are
    per-item collections with no single canonical file yet - reserved for
    future extension."""
    if family == "intent":
        return _CANONICAL_INTENT_PATH, None
    if family == "specs":
        return _CANONICAL_SPECS_PATH, None
    if family == "scope":
        return resolve_scope_source_relpath(root, cfg=cfg)
    if family in ("feedback", "change-request", "change-requests"):
        return None, deny(
            "PMO-PUBLISH-007",
            "UNAPPROVED_ARTIFACT_PATH: publishing a specific '{}' item "
            "requires an explicit target path/id, which this Publisher does "
            "not yet resolve automatically (reserved for future "
            "extension).".format(family),
        )
    return None, deny(
        "PMO-PUBLISH-007",
        "UNAPPROVED_ARTIFACT_PATH: unknown artifact family '{}'.".format(family),
    )


# --------------------------------------------------------------------------- #
# Hash integrity
# --------------------------------------------------------------------------- #

def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_hash_match(source_path, destination_path):
    if not os.path.isfile(source_path):
        return deny(
            "PMO-PUBLISH-008",
            "SOURCE_ARTIFACT_NOT_VALID: authoritative source file not found "
            "at '{}'.".format(source_path),
        )
    if not os.path.isfile(destination_path):
        return deny(
            "PMO-PUBLISH-009",
            "SOURCE_DESTINATION_HASH_MISMATCH: destination file not found at "
            "'{}'.".format(destination_path),
        )
    src_hash = sha256_of_file(source_path)
    dst_hash = sha256_of_file(destination_path)
    if src_hash != dst_hash:
        return deny(
            "PMO-PUBLISH-009",
            "SOURCE_DESTINATION_HASH_MISMATCH: source sha256 {} != "
            "destination sha256 {} ({} -> {}).".format(
                src_hash, dst_hash, source_path, destination_path
            ),
        )
    return None


def is_no_change(source_path, destination_path):
    """True when both files exist and are byte-identical (NO_CHANGES_TO_PUBLISH)."""
    if not (os.path.isfile(source_path) and os.path.isfile(destination_path)):
        return False
    return sha256_of_file(source_path) == sha256_of_file(destination_path)


# --------------------------------------------------------------------------- #
# Source governance integration (read-only; never re-derives from scratch)
# --------------------------------------------------------------------------- #

def _load_sibling_module(name, filename):
    """Load a hook module from `.claude/hooks/<filename>`, resolved relative
    to this file's location (`.claude/lib/`) - never from cwd or PATH."""
    p = Path(__file__).resolve().parent.parent / "hooks" / filename
    spec = importlib.util.spec_from_file_location(name, str(p))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_source_governance(family, root):
    """Read-only governance check for one artifact family. Never mutates
    Intent/Scope/Specs and never writes an approval record."""
    try:
        if family == "specs":
            path = os.path.join(root, "docs", "pmo", "specs", "specs.md")
            if not os.path.isfile(path):
                return deny(
                    "PMO-PUBLISH-008",
                    "SOURCE_ARTIFACT_NOT_VALID: canonical Specs source not "
                    "found at '{}'.".format(path),
                )
            text = read_text(path) or ""
            g = _load_sibling_module(
                "_pmo_specs_governance_guard", "specs-governance-guard.py"
            )
            d = g.full_spec_validation(root, spec_text=text)
            if d is not None:
                return deny(
                    "PMO-PUBLISH-008",
                    "SOURCE_ARTIFACT_NOT_VALID: Specs governance did not "
                    "PASS ({}: {}).".format(
                        getattr(d, "code", "?"), getattr(d, "message", "")
                    ),
                )
            return None

        if family == "intent":
            path = os.path.join(root, "docs", "pmo", "intent", "intent.md")
            if not os.path.isfile(path):
                return deny(
                    "PMO-PUBLISH-008",
                    "SOURCE_ARTIFACT_NOT_VALID: Intent source not found at "
                    "'{}'.".format(path),
                )
            text = read_text(path) or ""
            g = _load_sibling_module(
                "_pmo_intent_schema_guard", "intent-schema-guard.py"
            )
            meta = g.parse_doc_control(text)
            status = g.parse_status(text)
            d = g.full_schema_validation(text, meta, root, status=status)
            if d is not None:
                return deny(
                    "PMO-PUBLISH-008",
                    "SOURCE_ARTIFACT_NOT_VALID: Intent governance did not "
                    "PASS ({}: {}).".format(
                        getattr(d, "code", "?"), getattr(d, "message", "")
                    ),
                )
            return None

        if family == "scope":
            relpath, err = resolve_scope_source_relpath(root)
            if err is not None:
                return err
            path = os.path.join(root, relpath)
            text = read_text(path) or ""
            g = _load_sibling_module(
                "_pmo_scope_version_guard", "scope-version-guard.py"
            )
            meta = g.parse_scope_metadata(text)
            status = meta.get("Status") if isinstance(meta, dict) else None
            target_ver = g.parse_scope_version_from_filename(path)
            d = g.full_scope_validation(text, meta, status, root, target_ver)
            if d is not None:
                return deny(
                    "PMO-PUBLISH-008",
                    "SOURCE_ARTIFACT_NOT_VALID: Scope governance did not "
                    "PASS ({}: {}).".format(
                        getattr(d, "code", "?"), getattr(d, "message", "")
                    ),
                )
            return None

        if family in ("feedback", "change-requests", "change-request"):
            # No dedicated governance guard exists yet for these families
            # (SKILL.md Section 15). Do not block on governance that does
            # not yet exist.
            return None

        return None
    except Exception as exc:  # fail closed on any governance-integration fault
        return deny(
            "PMO-PUBLISH-008",
            "SOURCE_ARTIFACT_NOT_VALID: unable to establish governance PASS "
            "for '{}' ({!r}).".format(family, exc),
        )


# --------------------------------------------------------------------------- #
# Git plumbing against the managed workspace
# --------------------------------------------------------------------------- #

def _run_git(args, timeout=10):
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=timeout
        )
    except Exception:
        return None


def git_remote_get_url(target_dir, remote="origin"):
    r = _run_git(["git", "-C", target_dir, "remote", "get-url", remote])
    if r is None or r.returncode != 0:
        return None
    lines = r.stdout.strip().splitlines()
    return lines[0].strip() if lines and lines[0].strip() else None


def git_status_porcelain(target_dir):
    r = _run_git(
        ["git", "-C", target_dir, "status", "--porcelain", "--untracked-files=all"]
    )
    if r is None or r.returncode != 0:
        return None
    return r.stdout


def parse_porcelain(text):
    entries = []
    for line in (text or "").splitlines():
        if not line or len(line) < 3:
            continue
        status = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"').replace("\\", "/")
        if path:
            entries.append({"path": path, "index": status[0], "worktree": status[1]})
    return entries


def git_diff_cached_names(target_dir):
    r = _run_git(["git", "-C", target_dir, "diff", "--cached", "--name-only"])
    if r is None or r.returncode != 0:
        return None
    return [line.strip().replace("\\", "/") for line in r.stdout.splitlines() if line.strip()]


def git_current_branch(target_dir):
    r = _run_git(["git", "-C", target_dir, "rev-parse", "--abbrev-ref", "HEAD"])
    if r is None or r.returncode != 0:
        return None
    branch = r.stdout.strip()
    if not branch or branch == "HEAD":
        return None
    return branch


def run_ls_remote_heads(url_or_path, branch, timeout=10):
    """(returncode-or-None, stdout, stderr). returncode None = could not run at all."""
    try:
        r = subprocess.run(
            ["git", "ls-remote", "--heads", url_or_path, branch],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return None, "", str(exc)
    return r.returncode, r.stdout, r.stderr


_AUTH_ERROR_MARKERS = (
    "permission denied",
    "authentication failed",
    "could not read username",
    "could not read password",
    "publickey",
    "403",
    "401",
    "access denied",
    "invalid credentials",
)


def classify_remote_error(stderr):
    """PMO-PUBLISH-003 for auth-shaped errors, else PMO-PUBLISH-002."""
    s = (stderr or "").lower()
    if any(marker in s for marker in _AUTH_ERROR_MARKERS):
        return "PMO-PUBLISH-003"
    return "PMO-PUBLISH-002"


def check_branch_exists_remote(url_or_path, branch):
    """(exists-bool-or-None, Decision-or-None). exists is None iff Decision is set."""
    rc, out, err = run_ls_remote_heads(url_or_path, branch)
    if rc is None:
        return None, deny(
            "PMO-PUBLISH-002",
            "TARGET_REPOSITORY_UNREACHABLE: could not query the remote for "
            "branch '{}' ({}).".format(branch, err.strip() or "no detail"),
        )
    if rc != 0:
        code = classify_remote_error(err)
        name = code_name(code)
        return None, deny(
            code,
            "{}: 'git ls-remote --heads' failed while checking branch "
            "'{}' ({}).".format(name, branch, err.strip() or "no detail"),
        )
    return bool(out.strip()), None


# --------------------------------------------------------------------------- #
# Repository pre-flight bundle (used by the Publisher before any mutation)
# --------------------------------------------------------------------------- #

def preflight_repository(target_dir, fields, remote_url_hint=None):
    """(report-dict, Decision-or-None). Deterministic pre-flight checks
    required before any Publisher mutation: remote reachable/authenticated,
    remote identity matches, configured branch exists remotely, checked-out
    branch equals working_branch, worktree clean, zero staged files.
    Returns on the first failing check (deterministic priority order);
    `report` always reflects what was actually checked before that point."""
    report = {
        "remote_url": None,
        "identity_ok": None,
        "branch_exists_remote": None,
        "current_branch": None,
        "current_branch_ok": None,
        "worktree_clean": None,
        "staged_count": None,
    }

    remote_url = remote_url_hint or git_remote_get_url(target_dir, "origin")
    report["remote_url"] = remote_url
    if not remote_url:
        return report, deny(
            "PMO-PUBLISH-002",
            "TARGET_REPOSITORY_UNREACHABLE: the managed workspace at '{}' has "
            "no resolvable 'origin' remote.".format(target_dir),
        )

    identity_ok = remote_identity_ok(remote_url, fields)
    report["identity_ok"] = identity_ok
    if not identity_ok:
        return report, deny(
            "PMO-PUBLISH-004",
            "REMOTE_IDENTITY_MISMATCH: managed workspace remote '{}' does not "
            "resolve to the configured {}/{}/{}.".format(
                remote_url, fields["provider"], fields["workspace"], fields["repository"],
            ),
        )

    exists, err = check_branch_exists_remote(remote_url, fields["working_branch"])
    report["branch_exists_remote"] = exists
    if err is not None:
        return report, err
    if not exists:
        return report, deny(
            "PMO-PUBLISH-014",
            "TARGET_BRANCH_NOT_FOUND: the configured branch '{}' does not "
            "exist on the remote; Artifact Publisher never creates "
            "it.".format(fields["working_branch"]),
        )

    current = git_current_branch(target_dir)
    report["current_branch"] = current
    current_ok = current is not None and current == fields["working_branch"]
    report["current_branch_ok"] = current_ok
    if not current_ok:
        return report, deny(
            "PMO-PUBLISH-005",
            "BRANCH_MISMATCH: the managed workspace is checked out on '{}', "
            "not the configured working branch '{}'.".format(
                current, fields["working_branch"]
            ),
        )

    porcelain = git_status_porcelain(target_dir)
    if porcelain is None:
        return report, deny(
            "PMO-PUBLISH-002",
            "TARGET_REPOSITORY_UNREACHABLE: could not read 'git status' for "
            "the managed workspace at '{}'.".format(target_dir),
        )
    entries = parse_porcelain(porcelain)
    # Distinguish unstaged/untracked worktree dirt (006) from cleanly staged
    # index content (010, checked separately below) - a file that is staged
    # with no further worktree modification (index != ' ', worktree == ' ')
    # is NOT worktree dirt; it is caught by the staged-files check instead.
    worktree_dirty = [e for e in entries if e["worktree"] != " "]
    report["worktree_clean"] = len(worktree_dirty) == 0
    if worktree_dirty:
        return report, deny(
            "PMO-PUBLISH-006",
            "TARGET_WORKTREE_DIRTY: the managed workspace has {} pending "
            "unstaged/untracked change(s) before the publication transaction "
            "even begins: {}.".format(
                len(worktree_dirty), ", ".join(e["path"] for e in worktree_dirty)
            ),
        )

    staged = git_diff_cached_names(target_dir)
    report["staged_count"] = len(staged) if staged is not None else None
    if staged:
        return report, deny(
            "PMO-PUBLISH-010",
            "UNRELATED_STAGED_FILE: {} file(s) already staged in the managed "
            "workspace before the publication transaction begins: "
            "{}.".format(len(staged), ", ".join(staged)),
        )

    return report, None


# --------------------------------------------------------------------------- #
# Bash command parsing - quote-aware, compound-command-aware, cd-aware
# (used by the PreToolUse guard to find `git` invocations and their
# effective working directory)
# --------------------------------------------------------------------------- #

_WRAPPER_CMDS = {"env", "sudo", "command", "nice"}
_GIT_GLOBAL_VALUE_OPTS = {
    "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
    "--exec-path",
}


def _split_top_level_segments(command):
    """Split a shell command on &&, ||, ;, |, & and newlines (quote-aware)."""
    segments = []
    buf = []
    quote = None
    i = 0
    n = len(command)
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


def _strip_wrappers(tokens):
    i = 0
    while i < len(tokens) and os.path.basename(tokens[i]) in _WRAPPER_CMDS:
        i += 1
        while i < len(tokens) and "=" in tokens[i] and not tokens[i].startswith("-"):
            i += 1
        while i < len(tokens) and tokens[i].startswith("-"):
            i += 1
    return tokens[i:]


def _resolve_path(cur_cwd, arg):
    if not arg or arg == "~":
        return str(Path.home())
    arg = os.path.expanduser(arg)
    if os.path.isabs(arg):
        return os.path.normpath(arg)
    return os.path.normpath(os.path.join(cur_cwd, arg))


def parse_git_invocations(command, cwd):
    """[{subcommand, args, cwd}, ...] for every git invocation found, in
    left-to-right order, honouring `cd` state changes within the same
    compound command."""
    results = []
    effective_cwd = cwd
    for segment in _split_top_level_segments(command):
        tokens = _tokenize(segment)
        if not tokens:
            continue
        if tokens[0] == "cd":
            target = tokens[1] if len(tokens) > 1 else "~"
            if target != "-":
                effective_cwd = _resolve_path(effective_cwd, target)
            continue

        stripped = _strip_wrappers(tokens)
        if not stripped or os.path.basename(stripped[0]) != "git":
            continue

        target_dir = effective_cwd
        i = 1
        subcommand = None
        rest = []
        while i < len(stripped):
            tok = stripped[i]
            if tok == "-C":
                if i + 1 < len(stripped):
                    target_dir = _resolve_path(effective_cwd, stripped[i + 1])
                    i += 2
                    continue
                i += 1
                continue
            if tok in _GIT_GLOBAL_VALUE_OPTS:
                i += 2
                continue
            if tok.startswith("--") and "=" in tok:
                i += 1
                continue
            if tok.startswith("-"):
                i += 1
                continue
            subcommand = tok
            rest = stripped[i + 1:]
            break
        if subcommand:
            results.append(
                {"subcommand": subcommand, "args": rest, "cwd": target_dir}
            )
    return results


# --------------------------------------------------------------------------- #
# Branch-creation detection
# --------------------------------------------------------------------------- #

def is_branch_creation_command(subcommand, args):
    if subcommand == "switch":
        return any(
            a in ("--orphan", "-c", "--create") or a.startswith("--orphan=")
            for a in args
        )
    if subcommand == "checkout":
        return any(a in ("-b", "-B") for a in args)
    if subcommand == "branch":
        positionals = [a for a in args if not a.startswith("-")]
        flags = [a for a in args if a.startswith("-")]
        if any(f in ("-d", "-D", "--delete") for f in flags):
            return False
        if any(f in ("-a", "-r", "-l", "--list", "-v", "-vv", "-m", "-M") for f in flags):
            return False
        return bool(positionals)
    return False


def branch_creation_target(subcommand, args):
    positionals = [a for a in args if not a.startswith("-")]
    return positionals[0] if positionals else None


# --------------------------------------------------------------------------- #
# git add / commit / push governance (guard-side dispatch)
# --------------------------------------------------------------------------- #

_BROAD_ADD_MARKERS = {".", "-A", "--all", "-u", "--update"}


def is_broad_add(args):
    return any(a in _BROAD_ADD_MARKERS for a in args)


def extract_add_paths(args):
    return [a for a in args if not a.startswith("-")]


def validate_add(target_dir, args, root):
    porcelain = git_status_porcelain(target_dir)
    if porcelain is None:
        return deny(
            "PMO-PUBLISH-002",
            "TARGET_REPOSITORY_UNREACHABLE: could not read 'git status' for "
            "the managed workspace at '{}'.".format(target_dir),
        )
    entries = parse_porcelain(porcelain)
    broad = is_broad_add(args)
    candidates = (
        [e["path"] for e in entries] if broad else extract_add_paths(args)
    )

    for candidate in candidates:
        if not is_allowlisted_path(candidate):
            return deny(
                "PMO-PUBLISH-007",
                "UNAPPROVED_ARTIFACT_PATH: '{}' is outside the PMO artifact "
                "allowlist / canonical Specs path.".format(candidate),
            )

    if not broad:
        candidate_set = {_norm_rel(c) for c in candidates}
        for entry in entries:
            if _norm_rel(entry["path"]) in candidate_set:
                continue
            if not is_allowlisted_path(entry["path"]):
                return deny(
                    "PMO-PUBLISH-006",
                    "TARGET_WORKTREE_DIRTY: unrelated change present in the "
                    "managed workspace ('{}') outside this publish "
                    "transaction.".format(entry["path"]),
                )

    families = {family_of(c) for c in candidates if family_of(c)}
    for fam in families:
        d = validate_source_governance(fam, root)
        if d is not None:
            return d

    return None


def validate_commit(target_dir):
    staged = git_diff_cached_names(target_dir)
    if staged is None:
        return deny(
            "PMO-PUBLISH-002",
            "TARGET_REPOSITORY_UNREACHABLE: could not read staged changes "
            "for the managed workspace at '{}'.".format(target_dir),
        )
    if not staged:
        return None
    for path in staged:
        if not is_allowlisted_path(path):
            return deny(
                "PMO-PUBLISH-010",
                "UNRELATED_STAGED_FILE: staged path '{}' is outside the PMO "
                "artifact allowlist.".format(path),
            )
    return None


_PUSH_VALUE_OPTS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}


def parse_push_positionals(args):
    positionals = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--":
            positionals.extend(args[i + 1:])
            break
        if tok in _PUSH_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        positionals.append(tok)
        i += 1
    remote = positionals[0] if positionals else None
    refspecs = positionals[1:] if len(positionals) > 1 else []
    return remote, refspecs


def refspec_destinations(refspecs):
    dsts = set()
    for spec in refspecs:
        ref = spec.lstrip("+")
        dst = ref.rsplit(":", 1)[1] if ":" in ref else ref
        dst = dst.strip()
        if dst.startswith("refs/heads/"):
            dst = dst[len("refs/heads/"):]
        elif dst.startswith("refs/") and "/" in dst[5:]:
            dst = dst.rsplit("/", 1)[1]
        if dst:
            dsts.add(dst)
    return dsts


def has_force_flag(args):
    for a in args:
        if a in ("-f", "--force"):
            return True
        if a.startswith("--force-with-lease"):
            return True
        if a.startswith("+") and len(a) > 1:
            return True
    return False


def validate_push(target_dir, args, fields, remote_url_hint=None):
    if has_force_flag(args):
        return deny(
            "PMO-PUBLISH-013",
            "FORCE_PUSH_ATTEMPT: a force flag/refspec was used on a "
            "governed publish push; force push is never permitted.",
        )

    remote_name, refspecs = parse_push_positionals(args)
    remote_name = remote_name or "origin"
    if remote_name != "origin":
        return deny(
            "PMO-PUBLISH-004",
            "REMOTE_IDENTITY_MISMATCH: push targets remote '{}' instead of "
            "the managed workspace's configured 'origin'; no fallback "
            "remote is permitted.".format(remote_name),
        )

    dest_branches = refspec_destinations(refspecs)
    current = git_current_branch(target_dir)
    if dest_branches:
        for b in dest_branches:
            if b != fields["working_branch"]:
                return deny(
                    "PMO-PUBLISH-005",
                    "BRANCH_MISMATCH: push destination branch '{}' does not "
                    "equal the configured working branch '{}'; no fallback "
                    "branch is permitted.".format(b, fields["working_branch"]),
                )
    if current is None:
        return deny(
            "PMO-PUBLISH-005",
            "BRANCH_MISMATCH: the managed workspace HEAD is detached; "
            "cannot verify the push originates from the configured working "
            "branch '{}'.".format(fields["working_branch"]),
        )
    if current != fields["working_branch"]:
        return deny(
            "PMO-PUBLISH-005",
            "BRANCH_MISMATCH: the managed workspace is checked out on '{}', "
            "not the configured working branch '{}'.".format(
                current, fields["working_branch"]
            ),
        )

    remote_url = remote_url_hint or git_remote_get_url(target_dir, "origin")
    if not remote_url:
        return deny(
            "PMO-PUBLISH-002",
            "TARGET_REPOSITORY_UNREACHABLE: the managed workspace has no "
            "resolvable 'origin' remote.",
        )

    exists, d = check_branch_exists_remote(remote_url, fields["working_branch"])
    if d is not None:
        return d
    if not exists:
        return deny(
            "PMO-PUBLISH-014",
            "TARGET_BRANCH_NOT_FOUND: the configured branch '{}' does not "
            "exist on the remote; Artifact Publish never creates it - "
            "Development/DevOps or an authorised repository administrator "
            "must create it first.".format(fields["working_branch"]),
        )

    return None


# --------------------------------------------------------------------------- #
# Dispatch (guard-side)
# --------------------------------------------------------------------------- #

def dispatch_validation(invocation, session_cwd, home=None):
    subcommand = invocation["subcommand"]
    args = invocation["args"]
    target_dir = invocation["cwd"]

    if subcommand in ("switch", "checkout", "branch") and is_branch_creation_command(
        subcommand, args
    ):
        branch_name = branch_creation_target(subcommand, args)
        return deny(
            "PMO-PUBLISH-014",
            "TARGET_BRANCH_NOT_FOUND: Artifact Publish has no "
            "branch-creation authority; refusing to create/orphan a branch "
            "('{}') in the managed publishing workspace. Development/DevOps "
            "or an authorised repository administrator must create the "
            "required branch.".format(branch_name or "<unnamed>"),
        )

    if subcommand not in ("add", "commit", "push"):
        return None

    root = locate_project_root(session_cwd)
    if root is None:
        return deny(
            "PMO-PUBLISH-001",
            "PROJECT_CONFIG_MISSING: '.pmo/project-config.yaml' was not "
            "found relative to '{}'.".format(session_cwd),
        )
    cfg = load_project_config(root)
    if cfg is None:
        return deny(
            "PMO-PUBLISH-001",
            "PROJECT_CONFIG_MISSING: '.pmo/project-config.yaml' could not "
            "be read or parsed.",
        )
    fields, err = extract_repo_fields(cfg)
    if err is not None:
        return err

    expected_path, err = resolve_expected_workspace(fields, home=home)
    if err is not None:
        return err

    try:
        actual_dir = Path(target_dir).expanduser().resolve(strict=False)
        expected_dir = expected_path.expanduser().resolve(strict=False)
    except Exception as exc:
        return deny(
            "PMO-PUBLISH-015",
            "PUBLISH_INTERNAL_ERROR: could not resolve workspace paths "
            "({!r}).".format(exc),
        )
    if actual_dir != expected_dir:
        return deny(
            "PMO-PUBLISH-004",
            "REMOTE_IDENTITY_MISMATCH: target directory '{}' does not "
            "match the configured managed workspace '{}'.".format(
                actual_dir, expected_dir
            ),
        )

    remote_url = git_remote_get_url(str(actual_dir), "origin")
    if remote_url:
        if not remote_identity_ok(remote_url, fields):
            return deny(
                "PMO-PUBLISH-004",
                "REMOTE_IDENTITY_MISMATCH: managed workspace remote '{}' "
                "does not resolve to the configured "
                "{}/{}/{}.".format(
                    remote_url, fields["provider"], fields["workspace"],
                    fields["repository"],
                ),
            )

        exists, err = check_branch_exists_remote(remote_url, fields["working_branch"])
        if err is not None:
            return err
        if not exists:
            return deny(
                "PMO-PUBLISH-014",
                "TARGET_BRANCH_NOT_FOUND: the configured branch '{}' does "
                "not exist on the remote; Artifact Publish never creates "
                "it.".format(fields["working_branch"]),
            )

    current_branch = git_current_branch(str(actual_dir))
    if current_branch is None:
        return deny(
            "PMO-PUBLISH-005",
            "BRANCH_MISMATCH: the managed workspace HEAD is detached; "
            "publication requires the workspace to be checked out on the "
            "configured working branch '{}'.".format(fields["working_branch"]),
        )
    if current_branch != fields["working_branch"]:
        return deny(
            "PMO-PUBLISH-005",
            "BRANCH_MISMATCH: the managed workspace is checked out on "
            "'{}', not the configured working branch '{}'; publication "
            "into an existing branch other than 'working_branch' is not "
            "permitted.".format(current_branch, fields["working_branch"]),
        )

    if subcommand == "add":
        return validate_add(str(actual_dir), args, root)
    if subcommand == "commit":
        return validate_commit(str(actual_dir))
    if subcommand == "push":
        return validate_push(str(actual_dir), args, fields, remote_url)
    return None


def process(payload, home=None):
    """(Decision-or-None). Fails open on classification errors outside
    controlled publication scope; fails closed once a command is confirmed
    to be an in-scope publish operation. This is the PreToolUse guard's
    top-level decision function."""
    try:
        if not isinstance(payload, dict):
            return None
        if payload.get("tool_name") != "Bash":
            return None
        tool_input = payload.get("tool_input") or {}
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str) or not command.strip():
            return None
        cwd = payload.get("cwd") or os.getcwd()
        if not isinstance(cwd, str) or not cwd:
            cwd = os.getcwd()

        try:
            invocations = parse_git_invocations(command, cwd)
        except Exception:
            return None  # parser fault outside controlled scope -> allow

        for invocation in invocations:
            try:
                in_scope = is_under_managed_workspace_root(
                    invocation["cwd"], home=home
                )
            except Exception:
                continue  # classification fault -> skip, do not block
            if not in_scope:
                continue
            try:
                decision = dispatch_validation(invocation, cwd, home=home)
            except Exception as exc:
                return deny(
                    "PMO-PUBLISH-015",
                    "PUBLISH_INTERNAL_ERROR: unexpected error validating a "
                    "publish operation ({!r}).".format(exc),
                )
            if decision is not None:
                return decision
        return None
    except Exception as exc:  # outermost fail-closed net
        return deny(
            "PMO-PUBLISH-015",
            "PUBLISH_INTERNAL_ERROR: unexpected error in the publish guard "
            "({!r}).".format(exc),
        )
