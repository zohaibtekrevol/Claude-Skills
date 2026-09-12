#!/usr/bin/env python3
"""PMO artifact-publish-guard (Claude Code PreToolUse hook).

Purpose
-------
Deterministic, fail-closed governance for the *transport* stage of the PMO
workflow: publishing validated PMO artifacts from the PMO Engine checkout
into the separate, project-specific **managed publishing workspace**
(a clone of the Project Artifact Repository at
``~/.pmo-workspaces/<provider>/<workspace>/<repository>/<working_branch>/``).

This hook is the functional enforcement of
``.claude/skills/artifact-publish/SKILL.md``. It never assumes Claude's
ambient/current Git checkout (the PMO Engine repository) is the project
repository - it only ever governs Git operations whose *target directory*
resolves under the managed-workspace root, and it reads routing identity
(``provider`` / ``workspace`` / ``repository`` / ``working_branch``) only
from ``.pmo/project-config.yaml``, located relative to the Claude Code
session's ambient working directory (the PMO Engine root).

Confirmed organizational branch model (see the Skill, Sections 3-8): the
configured branch is created by Development/DevOps *before* PMO publishing
begins. Artifact Publish - and this guard - has **no branch-creation
authority**: a missing remote branch is always a hard block
(``PMO-PUBLISH-014``), never remediated by creating, orphaning, or
renaming a branch.

Shared validation core
-----------------------
A Claude Code PreToolUse hook only sees Bash commands the agent is about to
run - it does NOT independently inspect Git subprocesses that a separate
Python program (``.claude/scripts/artifact-publisher.py``) launches
internally. So this guard and the Artifact Publisher share ONE
implementation of every repository/branch/allowlist/hash/staging/push
validation rule: ``.claude/lib/artifact_publish_core.py``. This file is a
thin PreToolUse shim over that shared core - it owns only the stdin/stdout
hook protocol (reading the PreToolUse JSON payload, emitting the deny
envelope); every actual validation decision is delegated to the core.

Behaviour
---------
* Reads the Claude Code PreToolUse payload from stdin (JSON).
* Only acts on ``Bash`` tool calls. Every command is parsed (quote-aware,
  compound-command-aware, ``cd``-aware) for embedded ``git`` invocations.
* A parsed git invocation is governed only when its *effective target
  directory* resolves under ``~/.pmo-workspaces/`` (the managed workspace
  root) - operations against any other directory, including the PMO Engine
  checkout itself, are out of scope for this guard and are allowed with no
  output. (``repo-binding-guard.py`` remains the guard for the PMO Engine's
  own ``git push``; this guard does not duplicate or replace it, and does
  not assume it protects the managed workspace - see the Skill, Section 20.)
* Governed subcommands: ``add``, ``commit``, ``push``, plus branch-creation
  detection on ``switch`` / ``checkout`` / ``branch`` (always denied inside
  the managed workspace, regardless of the branch name requested - this
  guard never lets Artifact Publish provision a branch).
* A blocked operation emits the standard PreToolUse deny response:
    {"hookSpecificOutput": {"hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": "<PMO-PUBLISH-0XX>: <reason>"}}
* An allowed operation, or any command outside this guard's scope, produces
  no output and exits 0.
* Failures while parsing/classifying a command that turns out to be outside
  this guard's controlled scope never block the command (fail *open* for
  classification). Failures once a command has been identified as an
  in-scope publish operation always fail *closed*
  (``PMO-PUBLISH-015 PUBLISH_INTERNAL_ERROR``).

Error IDs
---------
See ``.claude/lib/artifact_publish_core.py``'s ``PMO_PUBLISH_CODES`` for the
canonical PMO-PUBLISH-001..015 code -> name mapping shared by this guard
and the Artifact Publisher.

Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from artifact_publish_core import (  # noqa: E402  (path setup must precede this)
    Decision,
    deny,
    allow,
    PMO_PUBLISH_CODES,
    code_name,
    parse_simple_yaml,
    locate_project_root,
    load_project_config,
    extract_repo_fields,
    provider_from_host,
    parse_remote_url,
    remote_identity_ok,
    managed_workspace_path,
    resolve_expected_workspace,
    managed_workspace_root,
    is_under_managed_workspace_root,
    is_allowlisted_path,
    family_of,
    resolve_scope_source_relpath,
    resolve_family_source_relpath,
    sha256_of_file,
    verify_hash_match,
    is_no_change,
    validate_source_governance,
    git_remote_get_url,
    git_status_porcelain,
    parse_porcelain,
    git_diff_cached_names,
    git_current_branch,
    run_ls_remote_heads,
    classify_remote_error,
    check_branch_exists_remote,
    preflight_repository,
    parse_git_invocations,
    is_branch_creation_command,
    branch_creation_target,
    is_broad_add,
    extract_add_paths,
    validate_add,
    validate_commit,
    parse_push_positionals,
    refspec_destinations,
    has_force_flag,
    validate_push,
    dispatch_validation,
    process,
)


# --------------------------------------------------------------------------- #
# PreToolUse I/O (guard-specific; not part of the shared core)
# --------------------------------------------------------------------------- #

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


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    decision = process(payload)
    emit(decision)
    return 0


if __name__ == "__main__":
    sys.exit(main())
