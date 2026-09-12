#!/usr/bin/env python3
"""PMO repository-binding guard (Claude Code PreToolUse hook).

Purpose
-------
Deterministic guard that blocks `git push` whenever the repository the working
copy is actually bound to does not match its declared identity. This guard
classifies every `git push` into exactly one of three independent domains
and validates it against that domain's own, and only that domain's, routing
authority - the two configuration files below MUST NEVER control one
another:

* `.claude/pmo-engine-config.yaml`  - PMO Engine framework repository only.
* `.pmo/project-config.yaml`        - Project artifact repository only.

This hook never infers repository or branch identity from conversation
history, environment hints, hardcoded defaults, or anything other than
these files and the live Git configuration of the checkout.

Three Git security domains
---------------------------
* DOMAIN A - PMO_ENGINE: the effective Git working directory of the push
  resolves (by walking upward, like a normal project-root search) to a
  directory containing `.claude/pmo-engine-config.yaml`. That file - and
  ONLY that file - is the identity authority for this push. This guard
  never falls back to `.pmo/project-config.yaml` for an Engine push, even
  when that file also exists at the same repository root (as it does for
  the PMO Engine's own checkout, which also carries Smart Basket project
  state alongside the framework).

* DOMAIN B - MANAGED_PROJECT_WORKSPACE: the effective Git working directory
  resolves under `~/.pmo-workspaces/<provider>/<workspace>/<repository>/
  <working_branch>/`. This guard returns *silently* (no deny, no allow
  output) and takes no further action: `artifact-publish-guard.py` is
  solely responsible for approving or denying that operation, using
  `.pmo/project-config.yaml`. Delegating is NOT an approval.

* DOMAIN C - UNRELATED_OR_UNKNOWN: neither of the above. This preserves the
  guard's original, unchanged behaviour: validate against
  `.pmo/project-config.yaml` relative to the PreToolUse payload's ambient
  `cwd`, exactly as before this three-domain model existed. A repository
  with no `.pmo/project-config.yaml` at all fails closed (`PMO-REPO-001`).

Domain classification is based only on the resolved, normalized effective
working directory (honouring shell `cd <dir> && ...` / `cd <dir>; ...`
sequencing, a `-C <dir>` global git option, simple wrapper commands (`env`,
`sudo`, `command`, `nice`), and `~` / `$HOME` / `${HOME}` expansion via
`Path.home()`) - `Path.resolve()` collapses any `..` / path-traversal
attempt before comparison, and text inside quotes (e.g. `echo "cd ... &&
git push"`) is never treated as an executed command.

Behaviour
---------
* Reads the Claude Code PreToolUse payload from stdin (JSON).
* Only acts on `Bash` tool calls whose command contains a `git push`
  (compound commands such as `cd x && git push` are handled).
* Every non-`git push` command is allowed with no output (exit 0).
* Domain B pushes are delegated silently (exit 0, no output).
* Domain A and Domain C pushes are allowed (exit 0, no output) only when
  every validation rule for that domain passes; otherwise a structured
  PreToolUse *deny* response is emitted and the push is blocked.

Deny response shape (nested under `hookSpecificOutput`):
    {
      "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "<PMO-REPO-0XX | PMO-ENGINE-0XX>: <reason>"
      }
    }

Error IDs - Domain C (`.pmo/project-config.yaml`, unchanged)
--------------------------------------------------------------
PMO-REPO-001  `.pmo/project-config.yaml` does not exist.
PMO-REPO-002  `.pmo/project-config.yaml` cannot be read/parsed, or it has no
              usable `repository:` section.
PMO-REPO-003  `repository.workspace` is missing / empty.
PMO-REPO-004  `repository.repository` is missing / empty.
PMO-REPO-005  The configured Git remote (`repository.remote`, default
              `origin`) cannot be resolved in this checkout.
PMO-REPO-006  The resolved remote URL cannot be parsed into
              provider / workspace / repository (GitHub, Bitbucket, GitLab;
              HTTPS or SSH).
PMO-REPO-007  The configured `repository.provider` does not match the provider
              of the actual remote host.
PMO-REPO-008  The configured workspace / repository name does not match the
              actual remote.
PMO-REPO-009  The configured PMO working branch does not match the current
              branch (and the push does not explicitly target the configured
              PMO branch), or the current branch cannot be determined.
PMO-REPO-010  Unexpected internal error while validating the push (fail closed).

Error IDs - Domain A (`.claude/pmo-engine-config.yaml`, new)
--------------------------------------------------------------
PMO-ENGINE-001  ENGINE_CONFIG_MISSING            - `.claude/pmo-engine-config.yaml`
                                                    missing/unparseable, or a
                                                    required `engine:` field
                                                    is missing/unsupported.
PMO-ENGINE-002  ENGINE_REMOTE_UNRESOLVABLE       - the configured
                                                    `remote_name` cannot be
                                                    resolved in this checkout.
PMO-ENGINE-003  ENGINE_REMOTE_URL_UNPARSEABLE    - the resolved remote URL is
                                                    not a recognizable
                                                    GitHub / Bitbucket /
                                                    GitLab URL.
PMO-ENGINE-004  ENGINE_REMOTE_IDENTITY_MISMATCH  - the configured remote does
                                                    not resolve to the
                                                    configured
                                                    provider/workspace/
                                                    repository.
PMO-ENGINE-005  ENGINE_WRONG_REMOTE_USED         - the push command names a
                                                    remote other than the
                                                    configured `remote_name`;
                                                    no fallback remote is
                                                    permitted.
PMO-ENGINE-006  ENGINE_BRANCH_MISMATCH           - the push destination (or
                                                    current) branch does not
                                                    equal `working_branch`
                                                    (no fallback to
                                                    main/master), or HEAD is
                                                    detached.
PMO-ENGINE-007  ENGINE_FORCE_PUSH_PROHIBITED     - a force flag/refspec was
                                                    used; force push is never
                                                    permitted for the Engine
                                                    repository.
PMO-ENGINE-008  ENGINE_NOT_VERIFIED              - `engine.verified` is not
                                                    literally `true`; a real
                                                    Engine push is blocked
                                                    regardless of every other
                                                    check passing. The guard
                                                    never mutates this value.
PMO-ENGINE-009  ENGINE_FORBIDDEN_STAGED_CONTENT  - a staged path is outside
                                                    the Engine framework
                                                    allowlist (`.claude/`,
                                                    excluding bytecode /
                                                    cache / scratch content) -
                                                    project-specific or
                                                    generated content must
                                                    never ride along with an
                                                    Engine push.
PMO-ENGINE-010  ENGINE_INTERNAL_ERROR            - unexpected exception while
                                                    validating an Engine push
                                                    (fail closed).

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


# --------------------------------------------------------------------------- #
# Decision / deny / allow / emit
# --------------------------------------------------------------------------- #

class Decision(object):
    __slots__ = ("code", "message")

    def __init__(self, code, message):
        self.code = code
        self.message = message

    def __repr__(self):
        return "Decision({!r}, {!r})".format(self.code, self.message)


def deny(code, message):
    return Decision(code, message)


def allow():
    return None


def emit(decision):
    """Write the PreToolUse deny envelope for a Decision, or nothing."""
    if decision is None:
        return
    reason = "{}: {}".format(decision.code, decision.message)
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


# --------------------------------------------------------------------------- #
# Minimal YAML subset parser (stdlib only)
# --------------------------------------------------------------------------- #
# Supports exactly what the PMO project-config / engine-config need:
# 2-space indented nested mappings, quoted / unquoted scalars, null /
# booleans, inline `[]` / `{}`, and simple block sequences.

def _strip_comment(line: str) -> str:
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


def _parse_scalar(text: str):
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


def parse_simple_yaml(text: str) -> dict:
    root: dict = {}
    # stack entries: (indent, container)
    stack = [(-1, root)]
    # pending: (indent, parent_dict, key) - container type not yet decided
    pending = None

    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        s = line.strip()
        if s in ("---", "..."):
            continue
        indent = len(line) - len(line.lstrip(" "))

        # Decide the type of a freshly-created empty container.
        if pending is not None:
            p_indent, p_parent, p_key = pending
            if indent > p_indent and (s.startswith("- ") or s == "-"):
                new_list: list = []
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
            child: dict = {}
            container[key] = child
            stack.append((indent, child))
            pending = (indent, container, key)
        else:
            container[key] = _parse_scalar(rest)

    return root


# --------------------------------------------------------------------------- #
# Managed publishing workspace root (DOMAIN B) - delegation detection
# --------------------------------------------------------------------------- #
# Self-contained on purpose (mirrors, but does not import, the equivalent
# logic in artifact-publish-guard.py) so this guard has no runtime dependency
# on that module and keeps working even if that file changes shape.

def managed_workspace_root(home=None):
    home_path = Path(home) if home is not None else Path.home()
    return home_path / ".pmo-workspaces"


def is_under_managed_workspace_root(path, home=None):
    """True iff `path`, normalized (expanduser + resolve, so `..` segments
    and path-traversal attempts are collapsed first), lies under the
    managed workspace root. Never delegates based on raw command text -
    only on the resolved, normalized effective directory."""
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
# PMO Engine repository root (DOMAIN A) - detection
# --------------------------------------------------------------------------- #

_ENGINE_CONFIG_RELPATH = os.path.join(".claude", "pmo-engine-config.yaml")


def locate_engine_root(cwd):
    """The nearest ancestor (including `cwd` itself) that contains
    `.claude/pmo-engine-config.yaml`, or None. Uses `Path.resolve()` first,
    so a traversal-laden path (`.../.pmo-workspaces/../Projects/...`) is
    normalized before the search ever runs - classification is never
    fooled by unresolved `..` segments."""
    try:
        cur = Path(cwd).expanduser().resolve(strict=False)
    except Exception:
        return None
    for candidate in (cur, *cur.parents):
        if (candidate / ".claude" / "pmo-engine-config.yaml").is_file():
            return str(candidate)
    return None


def load_engine_config(root):
    path = os.path.join(root, ".claude", "pmo-engine-config.yaml")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return None
    try:
        cfg = parse_simple_yaml(text)
    except Exception:
        return None
    return cfg if isinstance(cfg, dict) else None


def extract_engine_fields(cfg):
    """(fields-dict-or-None, Decision-or-None)."""
    engine = cfg.get("engine") if isinstance(cfg, dict) else None
    if not isinstance(engine, dict) or not engine:
        return None, deny(
            "PMO-ENGINE-001",
            "PMO engine guard: '.claude/pmo-engine-config.yaml' has no "
            "usable 'engine:' section.",
        )

    provider = _as_clean_str(engine.get("provider"))
    workspace = _as_clean_str(engine.get("workspace"))
    repository = _as_clean_str(engine.get("repository"))
    remote_name = _as_clean_str(engine.get("remote_name")) or "origin"
    working_branch = _as_clean_str(engine.get("working_branch"))
    verified_raw = engine.get("verified")

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
            "PMO-ENGINE-001",
            "PMO engine guard: required 'engine:' routing field(s) "
            "missing/empty in '.claude/pmo-engine-config.yaml': "
            "{}.".format(", ".join(missing)),
        )

    return (
        {
            "provider": provider.lower(),
            "workspace": workspace,
            "repository": repository,
            "remote_name": remote_name,
            "working_branch": working_branch,
            "verified": verified_raw is True,
        },
        None,
    )


# --------------------------------------------------------------------------- #
# Command parsing: detect `git push` and its effective working directory
# --------------------------------------------------------------------------- #

_GIT_GLOBAL_VALUE_OPTS = {
    "-C", "-c", "--git-dir", "--work-tree", "--namespace",
    "--super-prefix", "--exec-path",
}
_WRAPPER_CMDS = {"env", "sudo", "command", "nice"}


def _split_top_level_segments(command: str):
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


def _tokenize(segment: str):
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _strip_wrappers(tokens):
    """Skip leading simple wrapper commands (`env`, `sudo`, `command`,
    `nice`) together with their own flags / VAR=value assignments."""
    i = 0
    while i < len(tokens) and os.path.basename(tokens[i]) in _WRAPPER_CMDS:
        i += 1
        while i < len(tokens) and "=" in tokens[i] and not tokens[i].startswith("-"):
            i += 1
        while i < len(tokens) and tokens[i].startswith("-"):
            i += 1
    return tokens[i:]


def _expand_home_vars(arg: str) -> str:
    """Expand literal `$HOME` / `${HOME}` text. No shell is invoked to run
    these commands, so shlex never performs variable substitution for us -
    this hook must do it explicitly for the forms it needs to recognize."""
    if not arg:
        return arg
    home = str(Path.home())
    return arg.replace("${HOME}", home).replace("$HOME", home)


def _resolve_cd_target(cur_cwd: str, arg: str) -> str:
    if not arg or arg == "~":
        return str(Path.home())
    arg = _expand_home_vars(arg)
    arg = os.path.expanduser(arg)
    if os.path.isabs(arg):
        return os.path.normpath(arg)
    return os.path.normpath(os.path.join(cur_cwd, arg))


def parse_first_git_push(command: str, base_cwd: str):
    """(push_args-or-None, effective_cwd-or-None) for the FIRST `git push`
    invocation found in `command`.

    Splits on shell sequencing (&&, ||, ;, |, &, newlines - quote-aware),
    tracks `cd <dir>` state across top-level segments, and honours a
    `-C <dir>` global option on the git invocation itself (whichever was
    set most recently wins). Text inside quotes (e.g. an
    `echo "... git push ..."`) is never treated as an executed command,
    since `_split_top_level_segments` / `_tokenize` never split or unquote
    inside a quoted string."""
    effective_cwd = base_cwd
    for segment in _split_top_level_segments(command):
        tokens = _tokenize(segment)
        if not tokens:
            continue
        if tokens[0] == "cd":
            target = tokens[1] if len(tokens) > 1 else "~"
            if target != "-":
                effective_cwd = _resolve_cd_target(effective_cwd, target)
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
                    target_dir = _resolve_cd_target(effective_cwd, stripped[i + 1])
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
        if subcommand == "push":
            return rest, target_dir
    return None, None


# --------------------------------------------------------------------------- #
# Push argument helpers
# --------------------------------------------------------------------------- #

_PUSH_VALUE_OPTS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}


def push_positionals(args):
    """Positional (non-option) tokens of a `git push` invocation."""
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
    return positionals


def refspec_destinations(refspecs):
    """Destination branch names referenced by a list of refspecs."""
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


# --------------------------------------------------------------------------- #
# Remote URL parsing
# --------------------------------------------------------------------------- #

_PROVIDER_HOSTS = {
    "github": ("github.com", "www.github.com"),
    "bitbucket": ("bitbucket.org", "www.bitbucket.org"),
    "gitlab": ("gitlab.com", "www.gitlab.com"),
}


def provider_from_host(host: str):
    host = (host or "").lower()
    for provider, hosts in _PROVIDER_HOSTS.items():
        if host in hosts:
            return provider
    # Self-hosted instances, e.g. gitlab.example.com / bitbucket.internal.
    for provider in _PROVIDER_HOSTS:
        if provider in host:
            return provider
    return None


def parse_remote_url(url: str):
    """Parse GitHub / Bitbucket / GitLab HTTPS or SSH remote URLs.

    Returns dict(host, workspace, repository, segments) or None.
    """
    url = (url or "").strip()
    if not url:
        return None

    host = None
    path = None

    # scp-like syntax: [user@]host:path/to/repo(.git)
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
        "segments": segments,
    }


# --------------------------------------------------------------------------- #
# Git helpers
# --------------------------------------------------------------------------- #

def _run_git(cwd, args):
    try:
        return subprocess.run(
            ["git", "-C", cwd] + args,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return None


def current_branch(cwd):
    result = _run_git(cwd, ["rev-parse", "--abbrev-ref", "HEAD"])
    if result is None or result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def resolve_remote_url(cwd, remote):
    result = _run_git(cwd, ["remote", "get-url", remote])
    if result is None or result.returncode != 0:
        return None
    url = result.stdout.strip().splitlines()
    return url[0].strip() if url and url[0].strip() else None


def git_diff_cached_names(cwd):
    result = _run_git(cwd, ["diff", "--cached", "--name-only"])
    if result is None or result.returncode != 0:
        return None
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# Domain C validation - `.pmo/project-config.yaml` (unchanged semantics)
# --------------------------------------------------------------------------- #

def _as_clean_str(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def validate_push(push_args, cwd: str):
    """(Decision-or-None). Unchanged PMO-REPO-001..009 semantics, evaluated
    against the PreToolUse payload's ambient `cwd` exactly as before. This
    is DOMAIN C (unrelated/unknown) - reached only when the push is neither
    a Domain B (managed workspace) nor a Domain A (PMO Engine) operation."""
    config_path = os.path.join(cwd, ".pmo", "project-config.yaml")

    # Rule 1 -----------------------------------------------------------------
    if not os.path.isfile(config_path):
        return deny(
            "PMO-REPO-001",
            "PMO repository guard: '.pmo/project-config.yaml' was not found at "
            "'{path}'. Repository identity is undefined, so 'git push' is "
            "blocked. Create the PMO project configuration first.".format(path=config_path),
        )

    # Rule 2 (read + parse) -------------------------------------------------
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            raw_text = handle.read()
        config = parse_simple_yaml(raw_text)
        if not isinstance(config, dict):
            raise ValueError("top-level content is not a mapping")
    except Exception as exc:  # noqa: BLE001 - fail closed on any read/parse issue
        return deny(
            "PMO-REPO-002",
            "PMO repository guard: '.pmo/project-config.yaml' could not be "
            "read or parsed ({err}). 'git push' is blocked.".format(err=exc),
        )

    repo_cfg = config.get("repository")
    if not isinstance(repo_cfg, dict) or not repo_cfg:
        return deny(
            "PMO-REPO-002",
            "PMO repository guard: '.pmo/project-config.yaml' has no usable "
            "'repository:' section. 'git push' is blocked.",
        )

    cfg_provider = _as_clean_str(repo_cfg.get("provider"))
    cfg_workspace = _as_clean_str(repo_cfg.get("workspace"))
    cfg_repository = _as_clean_str(repo_cfg.get("repository"))
    cfg_remote = _as_clean_str(repo_cfg.get("remote")) or "origin"
    cfg_branch = _as_clean_str(repo_cfg.get("working_branch"))

    # Rule 3 ----------------------------------------------------------------
    if not cfg_workspace:
        return deny(
            "PMO-REPO-003",
            "PMO repository guard: 'repository.workspace' is missing in "
            "'.pmo/project-config.yaml'. Repository identity is incomplete, so "
            "'git push' is blocked.",
        )

    # Rule 4 ----------------------------------------------------------------
    if not cfg_repository:
        return deny(
            "PMO-REPO-004",
            "PMO repository guard: 'repository.repository' is missing in "
            "'.pmo/project-config.yaml'. Repository identity is incomplete, so "
            "'git push' is blocked.",
        )

    # Rule 5 (resolve configured remote) ----------------------------------
    actual_url = resolve_remote_url(cwd, cfg_remote)
    if not actual_url:
        return deny(
            "PMO-REPO-005",
            "PMO repository guard: the configured Git remote '{remote}' could "
            "not be resolved in this checkout (`git remote get-url {remote}` "
            "failed). 'git push' is blocked.".format(remote=cfg_remote),
        )

    # Rule 6 (parse actual remote URL) ----------------------------------
    parsed = parse_remote_url(actual_url)
    if parsed is None:
        return deny(
            "PMO-REPO-006",
            "PMO repository guard: the Git remote '{remote}' resolves to "
            "'{url}', which is not a recognizable GitHub / Bitbucket / GitLab "
            "URL (HTTPS or SSH). 'git push' is blocked.".format(
                remote=cfg_remote, url=actual_url
            ),
        )

    actual_provider = provider_from_host(parsed["host"])

    # Rule 7 (provider match) ----------------------------------
    if cfg_provider:
        if actual_provider is None:
            return deny(
                "PMO-REPO-007",
                "PMO repository guard: configured provider is "
                "'{cfg}', but the actual remote host '{host}' ({url}) is not a "
                "recognized {known} provider. 'git push' is blocked.".format(
                    cfg=cfg_provider,
                    host=parsed["host"],
                    url=actual_url,
                    known="/".join(sorted(_PROVIDER_HOSTS)),
                ),
            )
        if actual_provider != cfg_provider.lower():
            return deny(
                "PMO-REPO-007",
                "PMO repository guard: configured provider is "
                "'{cfg}', but the actual remote '{remote}' points at "
                "'{actual}' ({url}). 'git push' is blocked.".format(
                    cfg=cfg_provider,
                    remote=cfg_remote,
                    actual=actual_provider,
                    url=actual_url,
                ),
            )

    # Rule 8 (workspace + repository match) ----------------------------------
    same_workspace = parsed["workspace"].casefold() == cfg_workspace.casefold()
    same_repository = parsed["repository"].casefold() == cfg_repository.casefold()
    if not (same_workspace and same_repository):
        return deny(
            "PMO-REPO-008",
            "PMO repository guard: '.pmo/project-config.yaml' binds this "
            "project to '{cfg_ws}/{cfg_repo}', but the Git remote '{remote}' "
            "points at '{act_ws}/{act_repo}' ({url}). 'git push' is blocked "
            "because the working copy is bound to the wrong "
            "repository.".format(
                cfg_ws=cfg_workspace,
                cfg_repo=cfg_repository,
                remote=cfg_remote,
                act_ws=parsed["workspace"],
                act_repo=parsed["repository"],
                url=actual_url,
            ),
        )

    # Rule 9 (working branch) ----------------------------------
    if cfg_branch:
        positionals = push_positionals(push_args)
        refspecs = positionals[1:] if len(positionals) > 1 else []
        pushes_to_pmo_branch = cfg_branch in refspec_destinations(refspecs)

        if not pushes_to_pmo_branch:
            branch = current_branch(cwd)
            if branch is None or branch == "HEAD":
                return deny(
                    "PMO-REPO-009",
                    "PMO repository guard: the current branch could not be "
                    "determined (detached HEAD or not a Git work tree). The "
                    "configured PMO working branch is '{cfg}'. 'git push' is "
                    "blocked.".format(cfg=cfg_branch),
                )
            if branch != cfg_branch:
                return deny(
                    "PMO-REPO-009",
                    "PMO repository guard: the current branch '{cur}' does not "
                    "match the configured PMO working branch '{cfg}', and this "
                    "push does not explicitly target '{cfg}'. 'git push' is "
                    "blocked. Either switch to '{cfg}' or push explicitly with "
                    "`git push {remote} {cfg}`.".format(
                        cur=branch, cfg=cfg_branch, remote=cfg_remote
                    ),
                )

    # All rules satisfied.
    return allow()


# --------------------------------------------------------------------------- #
# Domain A validation - `.claude/pmo-engine-config.yaml`
# --------------------------------------------------------------------------- #

_ENGINE_CACHE_SEGMENT_RE = re.compile(r"(^|/)__pycache__(/|$)")


def is_engine_publishable_path(path):
    """Allowlist for content an Engine push may carry: framework source
    under `.claude/` only, excluding bytecode caches and scratch content.
    This is deliberately an allowlist (closed-world), not a denylist, so it
    can never be fooled by a project-specific or generated path this guard
    didn't anticipate."""
    rel = (path or "").strip().replace("\\", "/")
    if rel.startswith("./"):
        rel = rel[2:]
    rel = rel.lstrip("/")
    if not rel.startswith(".claude/"):
        return False
    if rel.endswith(".pyc"):
        return False
    if _ENGINE_CACHE_SEGMENT_RE.search(rel):
        return False
    if "scratchpad" in rel.lower():
        return False
    return True


def validate_engine_push(engine_root: str, push_args):
    """(Decision-or-None). DOMAIN A: validates a `git push` whose effective
    working directory resolved to the PMO Engine repository root, using
    ONLY `.claude/pmo-engine-config.yaml` - `.pmo/project-config.yaml` is
    never consulted here, even though it exists at the same root."""
    cfg = load_engine_config(engine_root)
    if cfg is None:
        return deny(
            "PMO-ENGINE-001",
            "PMO engine guard: '.claude/pmo-engine-config.yaml' could not be "
            "read or parsed at '{}'.".format(engine_root),
        )
    fields, err = extract_engine_fields(cfg)
    if err is not None:
        return err

    # Force-push prohibition -------------------------------------------------
    if has_force_flag(push_args):
        return deny(
            "PMO-ENGINE-007",
            "PMO engine guard: a force flag/refspec was used on a governed "
            "Engine push; force push is never permitted for the PMO Engine "
            "repository.",
        )

    # Remote-name governance --------------------------------------------------
    positionals = push_positionals(push_args)
    used_remote = positionals[0] if positionals else fields["remote_name"]
    if used_remote != fields["remote_name"]:
        return deny(
            "PMO-ENGINE-005",
            "PMO engine guard: push targets remote '{used}' instead of the "
            "configured Engine remote '{cfg}'; no fallback remote is "
            "permitted for the PMO Engine repository.".format(
                used=used_remote, cfg=fields["remote_name"]
            ),
        )

    # Branch governance - no fallback to main/master/any other branch --------
    refspecs = positionals[1:] if len(positionals) > 1 else []
    dest_branches = refspec_destinations(refspecs)
    current = current_branch(engine_root)
    if dest_branches:
        for b in dest_branches:
            if b != fields["working_branch"]:
                return deny(
                    "PMO-ENGINE-006",
                    "PMO engine guard: push destination branch '{}' does not "
                    "equal the configured Engine working branch '{}'; no "
                    "fallback branch (including main/master) is "
                    "permitted.".format(b, fields["working_branch"]),
                )
    if current is None:
        return deny(
            "PMO-ENGINE-006",
            "PMO engine guard: the Engine repository HEAD is detached; "
            "publication requires the configured working branch "
            "'{}'.".format(fields["working_branch"]),
        )
    if current != fields["working_branch"]:
        return deny(
            "PMO-ENGINE-006",
            "PMO engine guard: the Engine repository is checked out on "
            "'{}', not the configured working branch '{}'.".format(
                current, fields["working_branch"]
            ),
        )

    # Remote identity ----------------------------------------------------------
    remote_url = resolve_remote_url(engine_root, fields["remote_name"])
    if not remote_url:
        return deny(
            "PMO-ENGINE-002",
            "PMO engine guard: the configured Engine remote '{}' could not "
            "be resolved in this checkout.".format(fields["remote_name"]),
        )
    parsed = parse_remote_url(remote_url)
    if parsed is None:
        return deny(
            "PMO-ENGINE-003",
            "PMO engine guard: the Engine remote '{}' resolves to '{}', "
            "which is not a recognizable GitHub / Bitbucket / GitLab URL "
            "(HTTPS or SSH).".format(fields["remote_name"], remote_url),
        )
    actual_provider = provider_from_host(parsed["host"])
    identity_ok = (
        actual_provider == fields["provider"]
        and parsed["workspace"].casefold() == fields["workspace"].casefold()
        and parsed["repository"].casefold() == fields["repository"].casefold()
    )
    if not identity_ok:
        return deny(
            "PMO-ENGINE-004",
            "PMO engine guard: configured Engine identity is "
            "'{}/{}/{}', but remote '{}' resolves to '{}' ({}).".format(
                fields["provider"], fields["workspace"], fields["repository"],
                fields["remote_name"], remote_url,
                "{}/{}/{}".format(actual_provider, parsed["workspace"], parsed["repository"]),
            ),
        )

    # Framework content boundary - project/generated content must never ride
    # along with an Engine push. --------------------------------------------
    staged = git_diff_cached_names(engine_root)
    if staged:
        offending = [p for p in staged if not is_engine_publishable_path(p)]
        if offending:
            return deny(
                "PMO-ENGINE-009",
                "PMO engine guard: staged path(s) outside the Engine "
                "framework allowlist ('.claude/', excluding caches/scratch) "
                "are present and would ride along with this push: "
                "{}.".format(", ".join(offending)),
            )

    # Verified gate - the guard never mutates this value. --------------------
    if not fields["verified"]:
        return deny(
            "PMO-ENGINE-008",
            "PMO engine guard: 'engine.verified' is not true in "
            "'.claude/pmo-engine-config.yaml'; a real Engine push is blocked "
            "until a separate, controlled remote-verification task sets it "
            "to true.",
        )

    return allow()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def process(payload, home=None):
    """(Decision-or-None). Classifies every `git push` into exactly one
    domain and validates it against that domain's own authority only:

    * DOMAIN B (managed publishing workspace) is checked first and, when
      matched, this guard returns None *without* calling any validator -
      that is a silent delegation to `artifact-publish-guard.py`, never an
      approval.
    * DOMAIN A (PMO Engine repository) is checked next, using ONLY
      `.claude/pmo-engine-config.yaml` - never `.pmo/project-config.yaml`.
    * DOMAIN C (everything else) preserves the original, unchanged
      `.pmo/project-config.yaml`-based validation, evaluated against the
      PreToolUse payload's ambient `cwd`.
    """
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

        # Rule 10: everything that is not `git push` is allowed normally.
        push_args, effective_cwd = parse_first_git_push(command, cwd)
        if push_args is None:
            return None

        # DOMAIN B --------------------------------------------------------
        if effective_cwd and is_under_managed_workspace_root(effective_cwd, home=home):
            # Delegation boundary (not an allow decision): this push's
            # effective working directory is inside the managed publishing
            # workspace. repo-binding-guard.py has no jurisdiction there;
            # artifact-publish-guard.py owns approval/denial for it.
            return None

        # DOMAIN A ----------------------------------------------------------
        engine_root = locate_engine_root(effective_cwd or cwd)
        if engine_root is not None:
            try:
                return validate_engine_push(engine_root, push_args)
            except Exception as exc:  # noqa: BLE001 - fail closed
                return deny(
                    "PMO-ENGINE-010",
                    "PMO engine guard: an unexpected internal error occurred "
                    "while validating an Engine 'git push' ({err}). Blocking "
                    "the push as a precaution.".format(err=exc),
                )

        # DOMAIN C ------------------------------------------------------------
        return validate_push(push_args, cwd)
    except Exception as exc:  # noqa: BLE001 - fail closed
        return deny(
            "PMO-REPO-010",
            "PMO repository guard: an unexpected internal error occurred while "
            "validating 'git push' ({err}). Blocking the push as a "
            "precaution.".format(err=exc),
        )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    decision = process(payload)
    emit(decision)
    return 0


if __name__ == "__main__":
    sys.exit(main())
