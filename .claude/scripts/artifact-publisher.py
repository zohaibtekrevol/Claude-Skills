#!/usr/bin/env python3
"""PMO Artifact Publisher - deterministic execution engine.

Publishes a governed PMO artifact family (Intent / Scope / Specs, with
Feedback / Change Request reserved for future extension) from the PMO
Engine workspace into the canonical managed publishing workspace
(``~/.pmo-workspaces/<provider>/<workspace>/<repository>/<working_branch>/``),
which is a clone of the configured Project Artifact Repository.

Why this exists
----------------
Claude Code PreToolUse hooks (``.claude/hooks/artifact-publish-guard.py``)
only see Bash commands the agent is about to run - they do NOT
independently inspect Git subprocesses that this program launches
internally. So this Publisher MUST NOT rely on the guard alone for safety:
it reuses the exact same deterministic validation as the guard, from
``.claude/lib/artifact_publish_core.py`` (repository identity, branch
existence, allowlist, hash integrity, staging exactness, source
governance). There is exactly one implementation of each of those rules;
this file only adds the orchestration (workspace init, byte copy, git
add/commit/push, remote verification) around it.

Repository identity is read ONLY from ``.pmo/project-config.yaml`` -
never from the command line, conversation history, Claude's ambient
checkout, the current shell branch, `origin`, or `main`/`master`.

Branch model
------------
The configured `working_branch` MUST already exist on the remote. This
Publisher has NO branch-provisioning authority: it never runs
`git switch --orphan`, `git checkout -b`, or `git switch -c` against the
configured branch. A missing branch is always PMO-PUBLISH-014
(TARGET_BRANCH_NOT_FOUND) - reported, never remediated by creating one.

Modes
-----
``--dry-run`` (default): validates everything and computes the
publication transaction plan, but never copies, stages, commits, pushes,
or otherwise mutates the managed workspace or PMO Engine source.

``--publish``: performs the transaction when (and only when) a genuine
byte-level difference exists between source and destination. When source
and destination are already byte-identical, this is a no-op
(NO_CHANGES_TO_PUBLISH) in either mode - no empty commit is ever created.

Usage
-----
    python3 .claude/scripts/artifact-publisher.py --artifact specs --dry-run
    python3 .claude/scripts/artifact-publisher.py --artifact specs --publish

Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import artifact_publish_core as core  # noqa: E402  (path setup must precede this)
import publication_evidence_core as pev  # noqa: E402


FAMILIES = ("intent", "scope", "specs", "feedback", "change-request")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _project_name(cfg):
    return core.extract_project_name(cfg)


def _artifact_version(family, cfg, src=None):
    """Version of the artifact being published, read from the ARTIFACT'S OWN
    document control through the authoritative parser (publication_evidence_core
    .artifact_version); project-config is only a legacy fallback."""
    text = None
    if src and os.path.isfile(src):
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
    return pev.artifact_version(family, text, cfg)


def _new_result():
    return {
        "status": None,
        "decision": None,
        "project": None,
        "artifact": None,
        "mode": None,
        "fields": None,
        "managed_workspace": None,
        "workspace_created": False,
        "preflight": None,
        "transaction": None,
        "staged": [],
        "commit_hash": None,
        "pushed": False,
        "remote_verified": None,
        "receipt": None,
    }


def _fail(result, decision, status="BLOCKED"):
    result["status"] = status
    result["decision"] = decision
    return result


# --------------------------------------------------------------------------- #
# Managed workspace initialization / update (existing-branch-only)
# --------------------------------------------------------------------------- #

def _ensure_workspace(ws, fields, clone_url_override=None):
    """(created-bool, Decision-or-None).

    If `ws` does not exist: create parent directories, then clone ONLY the
    existing configured remote branch (`git clone --branch <b>
    --single-branch`) - this never creates a branch.

    If `ws` exists: validate its remote identity matches project-config
    (never silently reusing a workspace bound to the wrong repository),
    fetch, verify the configured branch still exists remotely, and
    fast-forward the existing local branch to `origin/<branch>` - again,
    never creating a branch.
    """
    if os.path.isdir(os.path.join(ws, ".git")):
        remote_url = core.git_remote_get_url(ws, "origin")
        if not remote_url:
            return False, core.deny(
                "PMO-PUBLISH-002",
                "TARGET_REPOSITORY_UNREACHABLE: existing managed workspace "
                "at '{}' has no resolvable 'origin' remote.".format(ws),
            )
        if not core.remote_identity_ok(remote_url, fields):
            return False, core.deny(
                "PMO-PUBLISH-004",
                "REMOTE_IDENTITY_MISMATCH: existing managed workspace remote "
                "'{}' does not match the configured {}/{}/{}; refusing to "
                "silently reuse it.".format(
                    remote_url, fields["provider"], fields["workspace"], fields["repository"],
                ),
            )

        fetch = core._run_git(["git", "-C", ws, "fetch", "--quiet", "origin"], timeout=60)
        if fetch is None or fetch.returncode != 0:
            code = core.classify_remote_error(fetch.stderr if fetch else "")
            return False, core.deny(
                code,
                "{}: 'git fetch' failed for the existing managed workspace "
                "({}).".format(core.code_name(code), (fetch.stderr.strip() if fetch else "no detail")),
            )

        exists, err = core.check_branch_exists_remote(remote_url, fields["working_branch"])
        if err is not None:
            return False, err
        if not exists:
            return False, core.deny(
                "PMO-PUBLISH-014",
                "TARGET_BRANCH_NOT_FOUND: the configured branch '{}' no "
                "longer exists on the remote.".format(fields["working_branch"]),
            )

        current = core.git_current_branch(ws)
        if current != fields["working_branch"]:
            local = core._run_git(["git", "-C", ws, "branch", "--list", fields["working_branch"]])
            has_local = bool(local and local.stdout.strip())
            if has_local:
                co = core._run_git(["git", "-C", ws, "checkout", fields["working_branch"]])
            else:
                co = core._run_git([
                    "git", "-C", ws, "checkout", "--track",
                    "origin/{}".format(fields["working_branch"]),
                ])
            if co is None or co.returncode != 0:
                return False, core.deny(
                    "PMO-PUBLISH-015",
                    "PUBLISH_INTERNAL_ERROR: could not check out the existing "
                    "configured branch '{}' ({}).".format(
                        fields["working_branch"], (co.stderr.strip() if co else "no detail")
                    ),
                )

        ff = core._run_git([
            "git", "-C", ws, "merge", "--ff-only", "origin/{}".format(fields["working_branch"]),
        ])
        if ff is None or ff.returncode != 0:
            return False, core.deny(
                "PMO-PUBLISH-006",
                "TARGET_WORKTREE_DIRTY: could not fast-forward the existing "
                "managed workspace to 'origin/{}' (local history may have "
                "diverged).".format(fields["working_branch"]),
            )
        return False, None

    # Does not exist yet: create parents, clone ONLY the existing branch.
    url = core.build_clone_url(fields, override=clone_url_override)
    if not url:
        return False, core.deny(
            "PMO-PUBLISH-001",
            "PROJECT_CONFIG_MISSING: unsupported provider '{}'; cannot "
            "derive a clone URL.".format(fields.get("provider")),
        )

    exists, err = core.check_branch_exists_remote(url, fields["working_branch"])
    if err is not None:
        return False, err
    if not exists:
        return False, core.deny(
            "PMO-PUBLISH-014",
            "TARGET_BRANCH_NOT_FOUND: the configured branch '{}' does not "
            "exist on the remote; Artifact Publisher never creates "
            "it.".format(fields["working_branch"]),
        )

    parent = os.path.dirname(ws)
    try:
        os.makedirs(parent, exist_ok=True)
    except Exception as exc:
        return False, core.deny(
            "PMO-PUBLISH-015",
            "PUBLISH_INTERNAL_ERROR: could not create managed workspace "
            "parent directory '{}' ({!r}).".format(parent, exc),
        )

    clone = core._run_git(
        ["git", "clone", "--branch", fields["working_branch"], "--single-branch", url, ws],
        timeout=120,
    )
    if clone is None or clone.returncode != 0:
        code = core.classify_remote_error(clone.stderr if clone else "")
        return False, core.deny(
            code,
            "{}: 'git clone' failed for the managed workspace ({}).".format(
                core.code_name(code), (clone.stderr.strip() if clone else "no detail")
            ),
        )
    return True, None


# --------------------------------------------------------------------------- #
# Publication transaction
# --------------------------------------------------------------------------- #

def _rollback_copy(dst, baseline_existed, baseline_bytes):
    try:
        if baseline_existed:
            with open(dst, "wb") as fh:
                fh.write(baseline_bytes)
        elif os.path.isfile(dst):
            os.remove(dst)
    except Exception:
        pass


def _git_reset_mixed(ws):
    core._run_git(["git", "-C", ws, "reset", "--mixed", "HEAD", "--"])


def _execute_publish(result, ws, fields, relpath, src, dst, src_hash, project_name, family, version,
                     engine_root=None, project_id=None):
    """Fail-closed wrapper: any unexpected exception during the mutating
    transaction (copy / hash / stage / commit) is converted into a clean
    PMO-PUBLISH-015 Decision, with a best-effort rollback of the
    destination file - never a bare traceback, never a fabricated
    success."""
    baseline_existed = os.path.isfile(dst)
    baseline_bytes = None
    if baseline_existed:
        with open(dst, "rb") as fh:
            baseline_bytes = fh.read()
    try:
        return _execute_publish_inner(
            result, ws, fields, relpath, src, dst, src_hash, project_name,
            family, version, baseline_existed, baseline_bytes,
            engine_root, project_id,
        )
    except Exception as exc:  # noqa: BLE001 - fail closed
        _rollback_copy(dst, baseline_existed, baseline_bytes)
        return _fail(result, core.deny(
            "PMO-PUBLISH-015",
            "PUBLISH_INTERNAL_ERROR: unexpected error during the publication "
            "transaction ({!r}).".format(exc),
        ))


def _execute_publish_inner(result, ws, fields, relpath, src, dst, src_hash,
                            project_name, family, version, baseline_existed,
                            baseline_bytes, engine_root=None, project_id=None):
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
    except Exception as exc:
        _rollback_copy(dst, baseline_existed, baseline_bytes)
        return _fail(result, core.deny(
            "PMO-PUBLISH-015",
            "PUBLISH_INTERNAL_ERROR: failed to copy '{}' -> '{}' "
            "({!r}).".format(src, dst, exc),
        ))

    dst_hash = core.sha256_of_file(dst)
    if dst_hash != src_hash:
        _rollback_copy(dst, baseline_existed, baseline_bytes)
        return _fail(result, core.deny(
            "PMO-PUBLISH-009",
            "SOURCE_DESTINATION_HASH_MISMATCH: source sha256 {} != "
            "destination sha256 {} ({} -> {}).".format(src_hash, dst_hash, src, dst),
        ))
    result["transaction"]["destination_hash"] = dst_hash

    add = core._run_git(["git", "-C", ws, "add", "--", relpath])
    if add is None or add.returncode != 0:
        _rollback_copy(dst, baseline_existed, baseline_bytes)
        return _fail(result, core.deny(
            "PMO-PUBLISH-015",
            "PUBLISH_INTERNAL_ERROR: 'git add' failed for '{}' "
            "({}).".format(relpath, (add.stderr.strip() if add else "no detail")),
        ))

    staged = core.git_diff_cached_names(ws) or []
    result["staged"] = staged
    if staged != [relpath]:
        _git_reset_mixed(ws)
        _rollback_copy(dst, baseline_existed, baseline_bytes)
        return _fail(result, core.deny(
            "PMO-PUBLISH-010",
            "UNRELATED_STAGED_FILE: staged set {} does not exactly match the "
            "transaction ({}).".format(staged, relpath),
        ))

    message = ("PMO: publish {} {} v{}".format(project_name, family, version)
               if version and version != "unknown"
               else "PMO: publish {} {}".format(project_name, family))
    commit = core._run_git(["git", "-C", ws, "commit", "-m", message])
    if commit is None or commit.returncode != 0:
        _git_reset_mixed(ws)
        _rollback_copy(dst, baseline_existed, baseline_bytes)
        return _fail(result, core.deny(
            "PMO-PUBLISH-011",
            "COMMIT_FAILED: 'git commit' failed for the publication "
            "transaction ({}).".format(commit.stderr.strip() if commit else "no detail"),
        ))

    rev = core._run_git(["git", "-C", ws, "rev-parse", "HEAD"])
    commit_hash = rev.stdout.strip() if (rev and rev.returncode == 0) else None
    result["commit_hash"] = commit_hash
    result["status"] = "COMMITTED_LOCAL"

    # --- pre-push revalidation (provider / identity / remote branch / current branch) ---
    _preflight, err = core.preflight_repository(ws, fields)
    if err is not None:
        # A local commit now genuinely exists - report it clearly, do not
        # fabricate success, and never auto-reset/rewrite history.
        return _fail(result, err, status="COMMITTED_LOCAL")

    push = core._run_git(["git", "-C", ws, "push", "origin", fields["working_branch"]])
    if push is None or push.returncode != 0:
        return _fail(result, core.deny(
            "PMO-PUBLISH-012",
            "PUSH_FAILED: 'git push origin {}' failed ({}). Local commit {} "
            "was created but NOT pushed.".format(
                fields["working_branch"], (push.stderr.strip() if push else "no detail"), commit_hash,
            ),
        ), status="COMMITTED_LOCAL")
    result["pushed"] = True

    remote_url = core.git_remote_get_url(ws, "origin")
    rc, out, _err_text = core.run_ls_remote_heads(remote_url, fields["working_branch"])
    remote_sha = out.strip().split()[0] if (rc == 0 and out.strip()) else None
    result["remote_verified"] = (remote_sha is not None and remote_sha == commit_hash)
    if not result["remote_verified"]:
        return _fail(result, core.deny(
            "PMO-PUBLISH-012",
            "PUSH_FAILED: remote branch '{}' resolves to '{}', not the newly "
            "created commit '{}' - push could not be verified.".format(
                fields["working_branch"], remote_sha, commit_hash,
            ),
        ), status="PUSHED_UNVERIFIED")

    result["status"] = "PUBLISHED"
    result["decision"] = None
    _record_receipt(result, engine_root, project_id, family, relpath, version,
                    src_hash, fields, commit_hash, "PUBLISHER_TRANSACTION",
                    _now_utc())
    return result


def _now_utc():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_receipt(result, engine_root, project_id, family, relpath, version,
                    src_hash, fields, remote_commit, evidence_source, published_at):
    """Write the publication receipt for a VERIFIED remote publication. The
    publication itself already succeeded - a receipt failure is reported
    loudly (PMO-PUBLISH-016) but never disguised, and never rolls back or
    rewrites the remote publication."""
    if not (engine_root and project_id and version and version != "unknown"):
        result["receipt"] = {"written": False, "reason": "no versioned artifact identity"}
        return
    receipt = pev.build_receipt(project_id, family, relpath, version, src_hash,
                                fields, remote_commit, published_at, evidence_source)
    path, err = pev.write_receipt(engine_root, receipt)
    if err:
        result["receipt"] = {"written": False, "reason": err}
        result["status"] = "PUBLISHED_RECEIPT_FAILED"
        result["decision"] = core.deny(
            "PMO-PUBLISH-016",
            "RECEIPT_WRITE_FAILED: the remote publication succeeded and was "
            "verified, but its local publication receipt could not be written "
            "({}). Run `--reconcile --write-receipt` to record it.".format(err))
        return
    result["receipt"] = {"written": True, "path": path, "remote_commit": remote_commit,
                         "artifact_sha256": src_hash, "version": version}


def _git_out(ws, args):
    r = core._run_git(["git", "-C", ws] + args)
    return r.stdout.strip() if (r is not None and r.returncode == 0) else None


def _reconcile(result, ws, fields, relpath, src, src_hash, project_id, family,
               version, engine_root, write):
    """Governed reconciliation for a publication that already happened
    (before receipts existed, or whose receipt could not be written). It
    NEVER publishes. It records a receipt only from live, independently
    verifiable remote evidence: the remote branch head, the remote blob at
    `relpath` equal to the approved source's blob, and the remote commit that
    introduced exactly those bytes (with its own commit time)."""
    branch = fields["working_branch"]
    if version == "unknown":
        return _fail(result, core.deny(
            "PMO-PUBLISH-017", "RECONCILE_REFUSED: the artifact version cannot be determined."))
    remote_url = core.git_remote_get_url(ws, "origin")
    rc, out, _e = core.run_ls_remote_heads(remote_url, branch)
    remote_sha = out.strip().split()[0] if (rc == 0 and out.strip()) else None
    fetch = core._run_git(["git", "-C", ws, "fetch", "origin", branch])
    local_remote_head = _git_out(ws, ["rev-parse", "origin/" + branch])
    if fetch is None or fetch.returncode != 0 or not remote_sha or remote_sha != local_remote_head:
        return _fail(result, core.deny(
            "PMO-PUBLISH-017",
            "RECONCILE_REFUSED: the remote branch head could not be verified "
            "(remote={}, fetched={}).".format(remote_sha, local_remote_head)))
    src_blob = _git_out(ws, ["hash-object", "--", src])
    remote_blob = _git_out(ws, ["rev-parse", "origin/{}:{}".format(branch, relpath)])
    if not src_blob or src_blob != remote_blob:
        return _fail(result, core.deny(
            "PMO-PUBLISH-017",
            "RECONCILE_REFUSED: the remote '{}' does not contain exactly the "
            "approved artifact bytes.".format(relpath)))
    commit = _git_out(ws, ["log", "-n1", "--format=%H", "origin/" + branch, "--", relpath])
    ts = _git_out(ws, ["log", "-n1", "--format=%ct", "origin/" + branch, "--", relpath])
    at_commit = _git_out(ws, ["rev-parse", "{}:{}".format(commit or "HEAD", relpath)]) if commit else None
    if not commit or not ts or at_commit != src_blob:
        return _fail(result, core.deny(
            "PMO-PUBLISH-017",
            "RECONCILE_REFUSED: no remote commit introducing exactly these bytes "
            "could be identified."))
    published_at = datetime.datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%dT%H:%M:%SZ")
    receipt = pev.build_receipt(project_id, family, relpath, version, src_hash, fields,
                                commit, published_at, "RECONCILED_FROM_REMOTE")
    result["receipt"] = {"written": False, "preview": receipt}
    if not write:
        result["status"] = "RECONCILE_READY"
        return result
    path, err = pev.write_receipt(engine_root, receipt)
    if err:
        return _fail(result, core.deny("PMO-PUBLISH-016", "RECEIPT_WRITE_FAILED: {}".format(err)))
    result["receipt"] = {"written": True, "path": path, "remote_commit": commit,
                         "artifact_sha256": src_hash, "version": version,
                         "evidence_source": "RECONCILED_FROM_REMOTE"}
    result["status"] = "RECONCILED"
    return result


# --------------------------------------------------------------------------- #
# Top-level orchestration
# --------------------------------------------------------------------------- #

def run(family, mode, root=None, home=None, clone_url_override=None):
    """Validate, plan, and (only in "publish" mode, with a genuine change)
    execute the publication transaction for `family`.

    mode: "dry-run" or "publish". Returns a result dict - see module
    docstring / README-style comments above for the shape. Never raises for
    expected failure modes, nor for a genuinely unexpected internal fault
    (fails closed as PMO-PUBLISH-015); those come back as
    `result["decision"]` (a `core.Decision`) with
    `result["status"] == "BLOCKED"` (or a publish-time status - see
    `_execute_publish`).
    """
    result = _new_result()
    result["mode"] = mode
    result["artifact"] = family
    try:
        return _run_inner(result, family, mode, root, home, clone_url_override)
    except Exception as exc:  # noqa: BLE001 - fail closed
        return _fail(result, core.deny(
            "PMO-PUBLISH-015",
            "PUBLISH_INTERNAL_ERROR: unexpected error while validating/planning "
            "the publication transaction ({!r}).".format(exc),
        ))


def _run_inner(result, family, mode, root, home, clone_url_override):
    if family not in FAMILIES:
        return _fail(result, core.deny(
            "PMO-PUBLISH-007",
            "UNAPPROVED_ARTIFACT_PATH: unknown artifact family '{}' "
            "(supported: {}).".format(family, ", ".join(FAMILIES)),
        ))

    engine_root = root or core.locate_project_root(os.getcwd())
    if engine_root is None:
        return _fail(result, core.deny(
            "PMO-PUBLISH-001",
            "PROJECT_CONFIG_MISSING: '.pmo/project-config.yaml' was not found.",
        ))

    cfg = core.load_project_config(engine_root)
    if cfg is None:
        return _fail(result, core.deny(
            "PMO-PUBLISH-001",
            "PROJECT_CONFIG_MISSING: '.pmo/project-config.yaml' could not be "
            "read or parsed.",
        ))
    result["project"] = _project_name(cfg)

    fields, err = core.extract_repo_fields(cfg)
    if err is not None:
        return _fail(result, err)
    result["fields"] = fields

    ws_path, err = core.resolve_expected_workspace(fields, home=home)
    if err is not None:
        return _fail(result, err)
    result["managed_workspace"] = str(ws_path)

    created, err = _ensure_workspace(str(ws_path), fields, clone_url_override=clone_url_override)
    result["workspace_created"] = created
    if err is not None:
        return _fail(result, err)

    preflight, err = core.preflight_repository(str(ws_path), fields)
    result["preflight"] = preflight
    if err is not None:
        return _fail(result, err)

    gov_err = core.validate_source_governance(family, engine_root)
    if gov_err is not None:
        return _fail(result, gov_err)

    relpath, err = core.resolve_family_source_relpath(family, engine_root, cfg)
    if err is not None:
        return _fail(result, err)

    if not core.is_allowlisted_path(relpath):
        return _fail(result, core.deny(
            "PMO-PUBLISH-007",
            "UNAPPROVED_ARTIFACT_PATH: '{}' is outside the PMO artifact "
            "allowlist / canonical Specs path.".format(relpath),
        ))

    src = os.path.join(engine_root, relpath)
    dst = os.path.join(str(ws_path), relpath)
    if not os.path.isfile(src):
        return _fail(result, core.deny(
            "PMO-PUBLISH-008",
            "SOURCE_ARTIFACT_NOT_VALID: authoritative source file not found "
            "at '{}'.".format(src),
        ))

    src_hash = core.sha256_of_file(src)
    dst_hash = core.sha256_of_file(dst) if os.path.isfile(dst) else None
    classification = "IDENTICAL" if dst_hash == src_hash else ("MODIFY" if dst_hash else "ADD")
    version = _artifact_version(family, cfg, src)

    result["transaction"] = {
        "project": result["project"],
        "artifact": family,
        "version": version,
        "source_path": src,
        "destination_path": dst,
        "source_hash": src_hash,
        "destination_hash": dst_hash,
        "classification": classification,
        "target_provider": fields["provider"],
        "target_repository": "{}/{}".format(fields["workspace"], fields["repository"]),
        "target_branch": fields["working_branch"],
        "managed_workspace": str(ws_path),
    }

    project_id = core._clean(((cfg or {}).get("project") or {}).get("id")) if isinstance(cfg, dict) else None

    if mode in ("reconcile", "reconcile-write"):
        if classification != "IDENTICAL":
            return _fail(result, core.deny(
                "PMO-PUBLISH-017",
                "RECONCILE_REFUSED: the published copy differs from the approved "
                "artifact ({}); reconciliation only records a publication that "
                "already matches byte-for-byte - publish instead.".format(classification)))
        return _reconcile(result, str(ws_path), fields, relpath, src, src_hash,
                          project_id, family, version, engine_root,
                          write=(mode == "reconcile-write"))

    if classification == "IDENTICAL":
        result["status"] = "NO_CHANGES_TO_PUBLISH"
        return result

    if mode != "publish":
        result["status"] = "CHANGES_TO_PUBLISH"
        return result

    return _execute_publish(
        result, str(ws_path), fields, relpath, src, dst, src_hash,
        result["project"], family, version,
        engine_root=engine_root, project_id=project_id,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _print_report(result):
    print(json.dumps({
        k: (str(v) if k == "decision" and v is not None else v)
        for k, v in result.items()
    }, indent=2, default=str))


def build_arg_parser():
    p = argparse.ArgumentParser(
        description="PMO Artifact Publisher - deterministic publish transaction "
                     "for a governed PMO artifact family."
    )
    p.add_argument("--artifact", required=True, choices=FAMILIES,
                    help="Artifact family to publish.")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                       help="Validate and plan only (default).")
    mode.add_argument("--publish", action="store_true",
                       help="Execute the publication transaction if a "
                            "genuine change exists.")
    mode.add_argument("--reconcile", action="store_true",
                       help="Verify (read-only) that the approved artifact is "
                            "already published byte-for-byte and preview the "
                            "publication receipt; never publishes.")
    p.add_argument("--write-receipt", action="store_true",
                    help="With --reconcile: write the verified publication "
                         "receipt to .pmo/publications/.")
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    if args.write_receipt and not args.reconcile:
        build_arg_parser().error("--write-receipt requires --reconcile")
    mode = ("publish" if args.publish
            else ("reconcile-write" if (args.reconcile and args.write_receipt)
                  else ("reconcile" if args.reconcile else "dry-run")))
    result = run(args.artifact, mode)
    _print_report(result)
    if result["status"] in ("NO_CHANGES_TO_PUBLISH", "CHANGES_TO_PUBLISH", "PUBLISHED",
                            "RECONCILE_READY", "RECONCILED"):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
