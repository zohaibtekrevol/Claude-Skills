#!/usr/bin/env python3
"""Regression tests for .claude/scripts/artifact-publisher.py.

Stdlib only. Run: python3 .claude/scripts/test_artifact_publisher.py
Exit 0 = all pass, 1 = at least one failure.

LOCAL TESTING ONLY: every "remote" here is a local bare Git repository
created and torn down in a temporary directory. Never touches the real
Smart Basket Bitbucket repository, never performs a real network call, and
never mutates the PMO Engine checkout this test file lives in - every
"PMO Engine root" is itself a disposable temporary directory too.
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLISHER = os.path.join(HERE, "artifact-publisher.py")
_spec = importlib.util.spec_from_file_location("artifact_publisher", PUBLISHER)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

# artifact-publisher.py imports artifact_publish_core the same way
# artifact-publish-guard.py does (sys.path insert of .claude/lib + a plain
# `import`), registering it in sys.modules under this name - fetch that
# exact object so monkeypatches here are visible to the publisher's own
# internal calls (which look it up as `core.<name>`, i.e. via this same
# module object).
core_mod = sys.modules["artifact_publish_core"]

_RESULTS = []


def check(name, ok, detail=""):
    _RESULTS.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + "  " + name
          + ("" if ok else "   :: " + str(detail)))


def code(decision):
    return getattr(decision, "code", None)


def msg(decision):
    return getattr(decision, "message", "")


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

PROVIDER = "bitbucket"
WORKSPACE = "devops-tekrevol"
REPOSITORY = "lets-explore-more-specs"
BRANCH = "pmo-artifacts"
PROJECT = "Smart Basket"

CONFIG_YAML = (
    'project:\n'
    '  name: "{project}"\n'
    'repository:\n'
    '  provider: "{provider}"\n'
    '  workspace: "{workspace}"\n'
    '  repository: "{repository}"\n'
    '  working_branch: "{branch}"\n'
    'artifacts:\n'
    '  intent:\n'
    '    latest_version: "1.0"\n'
    '  scope:\n'
    '    latest_version: "0.1"\n'
    '    approved_version: null\n'
    '  specifications:\n'
    '    latest_version: "0.2"\n'
).format(project=PROJECT, provider=PROVIDER, workspace=WORKSPACE,
         repository=REPOSITORY, branch=BRANCH)

SPECS_RELPATH = "docs/pmo/specs/specs.md"


def rm(path):
    shutil.rmtree(path, ignore_errors=True)


def sh(args, cwd=None, check_rc=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check_rc and r.returncode != 0:
        raise RuntimeError(
            "command failed: {} :: stdout={!r} stderr={!r}".format(args, r.stdout, r.stderr)
        )
    return r


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def git_identity(path):
    sh(["git", "config", "user.email", "pmo-test@example.com"], cwd=path)
    sh(["git", "config", "user.name", "PMO Test"], cwd=path)


def mk_engine_root(specs_text="# Specs\n\ncontent v1\n", config_text=CONFIG_YAML):
    root = tempfile.mkdtemp(prefix="publisher-engine-")
    _w(os.path.join(root, ".pmo", "project-config.yaml"), config_text)
    if specs_text is not None:
        _w(os.path.join(root, SPECS_RELPATH), specs_text)
    return root


def mk_bare_remote(tmp_root, workspace_slug, repo_slug, branch, files=None, empty=True):
    """A local bare repo standing in for the Project Artifact Repository."""
    ws_dir = os.path.join(tmp_root, workspace_slug)
    os.makedirs(ws_dir, exist_ok=True)
    bare = os.path.join(ws_dir, repo_slug + ".git")
    sh(["git", "init", "--bare", "-q", bare])

    seed = os.path.join(tmp_root, "seed-" + repo_slug)
    sh(["git", "clone", "-q", bare, seed])
    git_identity(seed)
    sh(["git", "checkout", "-q", "-b", branch], cwd=seed)
    if empty and not files:
        sh(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=seed)
    else:
        for relpath, content in (files or {}).items():
            _w(os.path.join(seed, relpath), content)
        sh(["git", "add", "-A"], cwd=seed)
        sh(["git", "commit", "-q", "-m", "seed"], cwd=seed)
    sh(["git", "push", "-q", "origin", branch], cwd=seed)
    rm(seed)
    return bare


def bare_file_content(bare, branch, relpath):
    r = sh(["git", "show", "{}:{}".format(branch, relpath)], cwd=bare, check_rc=False)
    return r.stdout if r.returncode == 0 else None


def bare_head_sha(bare, branch):
    r = sh(["git", "rev-parse", branch], cwd=bare)
    return r.stdout.strip()


def default_fields():
    return {"provider": PROVIDER, "workspace": WORKSPACE, "repository": REPOSITORY,
            "working_branch": BRANCH}


def stub_governance():
    """Bypass source governance (not what these scenarios test - see the
    dedicated real-governance test). Returns the original for restoration."""
    original = core_mod.validate_source_governance
    core_mod.validate_source_governance = lambda family, root: None
    return original


def unstub_governance(original):
    core_mod.validate_source_governance = original


def managed_ws_path(home, fields=None):
    fields = fields or default_fields()
    return str(core_mod.managed_workspace_path(
        fields["provider"], fields["workspace"], fields["repository"],
        fields["working_branch"], home=home,
    ))


# =========================================================================== #
# 1 - dry-run, identical artifact -> NO_CHANGES_TO_PUBLISH
# =========================================================================== #

def test_1_dry_run_identical():
    text = "# Specs\n\nsame content\n"
    engine = mk_engine_root(specs_text=text)
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH, files={SPECS_RELPATH: text})
        r = mod.run("specs", "dry-run", root=engine, home=home, clone_url_override=bare)
        check("1_dry_run_identical__no_changes", r["status"] == "NO_CHANGES_TO_PUBLISH",
              (r["status"], code(r["decision"])))
        check("1_dry_run_identical__no_mutation", r["commit_hash"] is None and not r["pushed"])
    finally:
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 2 - dry-run, changed artifact -> CHANGES_TO_PUBLISH, no mutation
# =========================================================================== #

def test_2_dry_run_changed():
    engine = mk_engine_root(specs_text="# Specs\n\nv2 content\n")
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH,
                               files={SPECS_RELPATH: "# Specs\n\nv1 content\n"})
        r = mod.run("specs", "dry-run", root=engine, home=home, clone_url_override=bare)
        check("2_dry_run_changed__plan", r["status"] == "CHANGES_TO_PUBLISH",
              (r["status"], code(r["decision"])))
        check("2_dry_run_changed__classification",
              r["transaction"]["classification"] == "MODIFY", r["transaction"])
        ws = r["managed_workspace"]
        status = sh(["git", "status", "--porcelain"], cwd=ws).stdout
        check("2_dry_run_changed__worktree_still_clean", status.strip() == "", status)
        check("2_dry_run_changed__no_commit", r["commit_hash"] is None and not r["pushed"])
        check("2_dry_run_changed__remote_unchanged",
              bare_file_content(bare, BRANCH, SPECS_RELPATH) == "# Specs\n\nv1 content\n")
    finally:
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 3 - publish changed artifact -> copy, hash match, stage, commit, push, verify
# =========================================================================== #

def test_3_publish_changed():
    new_text = "# Specs\n\nv2 content\n"
    engine = mk_engine_root(specs_text=new_text)
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH,
                               files={SPECS_RELPATH: "# Specs\n\nv1 content\n"})
        r = mod.run("specs", "publish", root=engine, home=home, clone_url_override=bare)
        check("3_publish__status", r["status"] == "PUBLISHED", (r["status"], code(r["decision"])))
        check("3_publish__staged_exact", r["staged"] == [SPECS_RELPATH], r["staged"])
        check("3_publish__commit_created", bool(r["commit_hash"]))
        check("3_publish__pushed", r["pushed"] is True)
        check("3_publish__remote_verified", r["remote_verified"] is True)
        check("3_publish__hash_match",
              r["transaction"]["source_hash"] == r["transaction"]["destination_hash"])
        check("3_publish__remote_sha_matches",
              bare_head_sha(bare, BRANCH) == r["commit_hash"],
              (bare_head_sha(bare, BRANCH), r["commit_hash"]))
        check("3_publish__remote_content_matches",
              bare_file_content(bare, BRANCH, SPECS_RELPATH) == new_text)
        check("3_publish__source_untouched",
              open(os.path.join(engine, SPECS_RELPATH)).read() == new_text)
        return engine, home, tmp, bare, new_text
    finally:
        unstub_governance(orig)


def test_4_second_run_no_changes():
    # Reuses the exact post-publish state from test_3 to exercise the
    # "workspace already exists" fetch+ff-only path in _ensure_workspace.
    engine, home, tmp, bare, published_text = test_3_publish_changed()
    orig = stub_governance()
    try:
        r = mod.run("specs", "publish", root=engine, home=home, clone_url_override=bare)
        check("4_second_run__no_changes", r["status"] == "NO_CHANGES_TO_PUBLISH",
              (r["status"], code(r["decision"])))
        check("4_second_run__no_new_commit", r["commit_hash"] is None and not r["pushed"])
        log = sh(["git", "log", "--oneline", BRANCH], cwd=bare).stdout.strip().splitlines()
        check("4_second_run__remote_commit_count_unchanged", len(log) == 2, log)  # seed + publish
    finally:
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 5 - wrong remote identity -> 004
# =========================================================================== #

def test_5_wrong_remote_identity():
    engine = mk_engine_root(specs_text="# Specs\n\nv2\n")
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    try:
        wrong_bare = mk_bare_remote(tmp, "wrong-workspace", "wrong-repo", BRANCH)
        r = mod.run("specs", "dry-run", root=engine, home=home, clone_url_override=wrong_bare)
        check("5_wrong_remote_identity__004", code(r["decision"]) == "PMO-PUBLISH-004",
              (r["status"], code(r["decision"]), msg(r["decision"])))
    finally:
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 6 - wrong branch -> 005 (preflight, via run() with _ensure_workspace
#     stubbed to a no-op so the Publisher's own self-healing checkout does
#     not mask the check under test)
# =========================================================================== #

def test_6_wrong_branch():
    engine = mk_engine_root(specs_text="# Specs\n\nv2\n")
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    orig_ensure = mod._ensure_workspace
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH,
                               files={SPECS_RELPATH: "# Specs\n\nv1\n"})
        ws = managed_ws_path(home)
        sh(["git", "clone", "-q", "--branch", BRANCH, "--single-branch", bare, ws])
        git_identity(ws)
        sh(["git", "checkout", "-q", "-b", "some-other-branch"], cwd=ws)

        mod._ensure_workspace = lambda ws_, fields, clone_url_override=None: (False, None)
        r = mod.run("specs", "dry-run", root=engine, home=home, clone_url_override=bare)
        check("6_wrong_branch__005", code(r["decision"]) == "PMO-PUBLISH-005",
              (r["status"], code(r["decision"])))
    finally:
        mod._ensure_workspace = orig_ensure
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 7 - dirty target worktree -> 006
# =========================================================================== #

def test_7_dirty_worktree():
    engine = mk_engine_root(specs_text="# Specs\n\nv2\n")
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    orig_ensure = mod._ensure_workspace
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH,
                               files={SPECS_RELPATH: "# Specs\n\nv1\n"})
        ws = managed_ws_path(home)
        sh(["git", "clone", "-q", "--branch", BRANCH, "--single-branch", bare, ws])
        git_identity(ws)
        _w(os.path.join(ws, "unrelated.txt"), "developer scratch\n")

        mod._ensure_workspace = lambda ws_, fields, clone_url_override=None: (False, None)
        r = mod.run("specs", "dry-run", root=engine, home=home, clone_url_override=bare)
        check("7_dirty_worktree__006", code(r["decision"]) == "PMO-PUBLISH-006",
              (r["status"], code(r["decision"])))
    finally:
        mod._ensure_workspace = orig_ensure
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 8 - disallowed destination -> 007 (feedback/change-request: reserved,
#     not yet resolved to a single canonical path)
# =========================================================================== #

def test_8_disallowed_destination():
    engine = mk_engine_root(specs_text="# Specs\n\nv2\n")
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        r = mod.run("feedback", "dry-run", root=engine, home=home, clone_url_override=bare)
        check("8_disallowed_destination__007", code(r["decision"]) == "PMO-PUBLISH-007",
              (r["status"], code(r["decision"])))
    finally:
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 9 - invalid source governance -> 008 (REAL governance, not stubbed)
# =========================================================================== #

def test_9_invalid_source_governance():
    engine = mk_engine_root(specs_text="# Specs\n\nnot a real spec document\n")
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH,
                               files={SPECS_RELPATH: "# Specs\n\nold\n"})
        r = mod.run("specs", "dry-run", root=engine, home=home, clone_url_override=bare)
        check("9_invalid_source_governance__008", code(r["decision"]) == "PMO-PUBLISH-008",
              (r["status"], code(r["decision"]), msg(r["decision"])))
    finally:
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 10 - simulated hash mismatch -> 009 (transfer corruption), with rollback
# =========================================================================== #

def test_10_simulated_hash_mismatch():
    old_text = "# Specs\n\nv1\n"
    new_text = "# Specs\n\nv2\n"
    engine = mk_engine_root(specs_text=new_text)
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    original_copyfile = mod.shutil.copyfile
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH, files={SPECS_RELPATH: old_text})

        def _corrupt_copy(s, d):
            original_copyfile(s, d)
            with open(d, "ab") as fh:
                fh.write(b"\x00corrupted")

        mod.shutil.copyfile = _corrupt_copy
        r = mod.run("specs", "publish", root=engine, home=home, clone_url_override=bare)
        check("10_hash_mismatch__009", code(r["decision"]) == "PMO-PUBLISH-009",
              (r["status"], code(r["decision"])))
        mod.shutil.copyfile = original_copyfile

        ws = r["managed_workspace"]
        dst_text = open(os.path.join(ws, SPECS_RELPATH)).read()
        check("10_hash_mismatch__rollback_restored_baseline", dst_text == old_text, dst_text)
        status = sh(["git", "status", "--porcelain"], cwd=ws).stdout
        check("10_hash_mismatch__no_residual_dirt", status.strip() == "", status)
        check("10_hash_mismatch__no_commit_created", r["commit_hash"] is None)
        check("10_hash_mismatch__remote_unchanged",
              bare_file_content(bare, BRANCH, SPECS_RELPATH) == old_text)
    finally:
        mod.shutil.copyfile = original_copyfile
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 11 - unrelated staged file -> 010 (pre-existing dirt in the index)
# =========================================================================== #

def test_11_unrelated_staged_file():
    engine = mk_engine_root(specs_text="# Specs\n\nv2\n")
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    orig_ensure = mod._ensure_workspace
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH,
                               files={SPECS_RELPATH: "# Specs\n\nv1\n"})
        ws = managed_ws_path(home)
        sh(["git", "clone", "-q", "--branch", BRANCH, "--single-branch", bare, ws])
        git_identity(ws)
        _w(os.path.join(ws, "sneaky.env"), "SECRET=1\n")
        sh(["git", "add", "sneaky.env"], cwd=ws)

        mod._ensure_workspace = lambda ws_, fields, clone_url_override=None: (False, None)
        r = mod.run("specs", "dry-run", root=engine, home=home, clone_url_override=bare)
        check("11_unrelated_staged__010", code(r["decision"]) == "PMO-PUBLISH-010",
              (r["status"], code(r["decision"])))
    finally:
        mod._ensure_workspace = orig_ensure
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 12 - simulated commit failure -> 011
# =========================================================================== #

def test_12_simulated_commit_failure():
    old_text = "# Specs\n\nv1\n"
    new_text = "# Specs\n\nv2\n"
    engine = mk_engine_root(specs_text=new_text)
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    original_run_git = core_mod._run_git
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH, files={SPECS_RELPATH: old_text})

        class _FakeResult:
            returncode = 1
            stdout = ""
            stderr = "simulated commit failure"

        def _fail_on_commit(args, timeout=10):
            if "commit" in args:
                return _FakeResult()
            return original_run_git(args, timeout=timeout)

        core_mod._run_git = _fail_on_commit
        r = mod.run("specs", "publish", root=engine, home=home, clone_url_override=bare)
        core_mod._run_git = original_run_git

        check("12_commit_failure__011", code(r["decision"]) == "PMO-PUBLISH-011",
              (r["status"], code(r["decision"])))
        check("12_commit_failure__not_pushed", not r["pushed"])
        ws = r["managed_workspace"]
        log = sh(["git", "log", "--oneline"], cwd=ws).stdout.strip().splitlines()
        check("12_commit_failure__no_local_commit_created", len(log) == 1, log)
        status = sh(["git", "status", "--porcelain"], cwd=ws).stdout
        check("12_commit_failure__worktree_reset", status.strip() == "", status)
    finally:
        core_mod._run_git = original_run_git
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 13 - simulated push failure -> 012 (local commit preserved, reported)
# =========================================================================== #

def test_13_simulated_push_failure():
    old_text = "# Specs\n\nv1\n"
    new_text = "# Specs\n\nv2\n"
    engine = mk_engine_root(specs_text=new_text)
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    original_run_git = core_mod._run_git
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH, files={SPECS_RELPATH: old_text})

        class _FakeResult:
            returncode = 1
            stdout = ""
            stderr = "simulated push failure"

        def _fail_on_push(args, timeout=10):
            if len(args) >= 4 and args[3] == "push":
                return _FakeResult()
            return original_run_git(args, timeout=timeout)

        core_mod._run_git = _fail_on_push
        r = mod.run("specs", "publish", root=engine, home=home, clone_url_override=bare)
        core_mod._run_git = original_run_git

        check("13_push_failure__012", code(r["decision"]) == "PMO-PUBLISH-012",
              (r["status"], code(r["decision"])))
        check("13_push_failure__local_commit_reported", bool(r["commit_hash"]))
        check("13_push_failure__status_committed_local",
              r["status"] == "COMMITTED_LOCAL", r["status"])
        check("13_push_failure__remote_not_updated",
              bare_file_content(bare, BRANCH, SPECS_RELPATH) == old_text)
    finally:
        core_mod._run_git = original_run_git
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 14 - force-push path impossible/prohibited -> 013 (structural guarantee)
# =========================================================================== #

def test_14_force_push_prohibited():
    new_text = "# Specs\n\nv2\n"
    engine = mk_engine_root(specs_text=new_text)
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    original_run_git = core_mod._run_git
    captured = {}
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH,
                               files={SPECS_RELPATH: "# Specs\n\nv1\n"})

        def _capture_push(args, timeout=10):
            if len(args) >= 4 and args[3] == "push":
                captured["argv"] = list(args)
            return original_run_git(args, timeout=timeout)

        core_mod._run_git = _capture_push
        r = mod.run("specs", "publish", root=engine, home=home, clone_url_override=bare)
        core_mod._run_git = original_run_git

        check("14_force_push__push_actually_ran", "argv" in captured, captured)
        argv = captured.get("argv", [])
        check("14_force_push__no_force_flag",
              "-f" not in argv and "--force" not in argv
              and not any(a.startswith("--force-with-lease") for a in argv), argv)
        check("14_force_push__no_plus_refspec",
              not any(a.startswith("+") for a in argv), argv)
        check("14_force_push__has_force_flag_predicate_shared",
              core_mod.has_force_flag(["-f"]) and core_mod.has_force_flag(["--force"]))
        check("14_force_push__publish_still_succeeded", r["status"] == "PUBLISHED", r["status"])
    finally:
        core_mod._run_git = original_run_git
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 15 - remote branch missing -> 014 (fresh-clone path)
# =========================================================================== #

def test_15_remote_branch_missing():
    engine = mk_engine_root(specs_text="# Specs\n\nv2\n")
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, "some-other-branch")
        r = mod.run("specs", "dry-run", root=engine, home=home, clone_url_override=bare)
        check("15_remote_branch_missing__014", code(r["decision"]) == "PMO-PUBLISH-014",
              (r["status"], code(r["decision"])))
        check("15_remote_branch_missing__no_workspace_created",
              not os.path.isdir(managed_ws_path(home)))
    finally:
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 16 - unexpected controlled failure -> 015 (fails closed, not a traceback)
# =========================================================================== #

def test_16_unexpected_failure_fails_closed():
    engine = mk_engine_root(specs_text="# Specs\n\nv2\n")
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    original_sha256 = core_mod.sha256_of_file
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH,
                               files={SPECS_RELPATH: "# Specs\n\nv1\n"})

        def _boom(path):
            raise RuntimeError("simulated internal fault")

        core_mod.sha256_of_file = _boom
        r = mod.run("specs", "dry-run", root=engine, home=home, clone_url_override=bare)
        core_mod.sha256_of_file = original_sha256

        check("16_unexpected_failure__015", code(r["decision"]) == "PMO-PUBLISH-015",
              (r["status"], code(r["decision"])))
    finally:
        core_mod.sha256_of_file = original_sha256
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 17 - source artifact remains byte-identical before/after publish
# =========================================================================== #

def test_17_source_immutability():
    new_text = "# Specs\n\nv2 - immutability check\n"
    engine = mk_engine_root(specs_text=new_text)
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH,
                               files={SPECS_RELPATH: "# Specs\n\nv1\n"})
        src_path = os.path.join(engine, SPECS_RELPATH)
        before = open(src_path, "rb").read()
        r = mod.run("specs", "publish", root=engine, home=home, clone_url_override=bare)
        after = open(src_path, "rb").read()
        check("17_source_immutability", before == after and r["status"] == "PUBLISHED",
              (before == after, r["status"]))
    finally:
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 18 - project approval/execution state remains unchanged
# =========================================================================== #

def test_18_pmo_state_unchanged():
    new_text = "# Specs\n\nv2 - state check\n"
    engine = mk_engine_root(specs_text=new_text)
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH,
                               files={SPECS_RELPATH: "# Specs\n\nv1\n"})
        cfg_path = os.path.join(engine, ".pmo", "project-config.yaml")
        before = open(cfg_path, "r", encoding="utf-8").read()
        r = mod.run("specs", "publish", root=engine, home=home, clone_url_override=bare)
        after = open(cfg_path, "r", encoding="utf-8").read()
        check("18_pmo_state_unchanged", before == after and r["status"] == "PUBLISHED",
              (before == after, r["status"]))
    finally:
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 19 - no branch creation occurs, anywhere in the flow
# =========================================================================== #

def test_19_no_branch_creation():
    engine = mk_engine_root(specs_text="# Specs\n\nv2\n")
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    original_run_git = core_mod._run_git
    seen_branch_flags = []
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH,
                               files={SPECS_RELPATH: "# Specs\n\nv1\n"})

        def _watch(args, timeout=10):
            joined = " ".join(args)
            if "checkout" in args or "switch" in args or "branch" in args:
                seen_branch_flags.append(list(args))
            return original_run_git(args, timeout=timeout)

        core_mod._run_git = _watch
        r = mod.run("specs", "publish", root=engine, home=home, clone_url_override=bare)
        core_mod._run_git = original_run_git

        forbidden = ("-b", "-B", "--orphan", "-c")
        offending = [a for a in seen_branch_flags for f in forbidden if f in a]
        check("19_no_branch_creation__no_forbidden_flags", offending == [], offending)
        check("19_no_branch_creation__publish_succeeded", r["status"] == "PUBLISHED", r["status"])
    finally:
        core_mod._run_git = original_run_git
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# 20 - existing empty branch supports first publication
# =========================================================================== #

def test_20_empty_branch_first_publication():
    new_text = "# Specs\n\nfirst publication\n"
    engine = mk_engine_root(specs_text=new_text)
    home = tempfile.mkdtemp(prefix="publisher-home-")
    tmp = tempfile.mkdtemp(prefix="publisher-remotes-")
    orig = stub_governance()
    try:
        # empty=True, no files: the configured branch exists remotely and
        # contains zero project files - a valid state for first publication.
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH, empty=True)
        r = mod.run("specs", "publish", root=engine, home=home, clone_url_override=bare)
        check("20_empty_branch_first_publication__published",
              r["status"] == "PUBLISHED", (r["status"], code(r["decision"])))
        check("20_empty_branch_first_publication__classification_add",
              r["transaction"]["classification"] == "ADD", r["transaction"])
        check("20_empty_branch_first_publication__content_matches",
              bare_file_content(bare, BRANCH, SPECS_RELPATH) == new_text)
        check("20_empty_branch_first_publication__no_branch_was_created",
              r["workspace_created"] is True)  # fresh clone of the EXISTING branch, not a new one
    finally:
        unstub_governance(orig)
        rm(engine); rm(home); rm(tmp)


# =========================================================================== #
# Unit-level coverage
# =========================================================================== #

def test_units():
    fields = default_fields()
    check("unit_build_clone_url", core_mod.build_clone_url(fields)
          == "git@bitbucket.org:devops-tekrevol/lets-explore-more-specs.git")
    check("unit_build_clone_url_override",
          core_mod.build_clone_url(fields, override="/local/bare.git") == "/local/bare.git")

    home = tempfile.mkdtemp(prefix="publisher-home-")
    try:
        p = core_mod.managed_workspace_path(fields["provider"], fields["workspace"],
                                             fields["repository"], fields["working_branch"],
                                             home=home)
        check("unit_managed_workspace_path_under_home", str(p).startswith(home))
    finally:
        rm(home)

    engine = mk_engine_root()
    try:
        cfg = core_mod.load_project_config(engine)
        relpath, err = core_mod.resolve_family_source_relpath("scope", engine, cfg)
        check("unit_scope_resolution_config_driven_not_glob",
              err is not None and code(err) == "PMO-PUBLISH-008",
              (relpath, code(err)))  # no docs/pmo/scope/scope-v0.1.md written -> not found, not guessed
        relpath2, err2 = core_mod.resolve_family_source_relpath("intent", engine, cfg)
        check("unit_intent_fixed_path", relpath2 == "docs/pmo/intent/intent.md" and err2 is None)
        relpath3, err3 = core_mod.resolve_family_source_relpath("specs", engine, cfg)
        check("unit_specs_fixed_path", relpath3 == "docs/pmo/specs/specs.md" and err3 is None)
    finally:
        rm(engine)


# --------------------------------------------------------------------------- #

def main():
    test_units()
    for fn in (
        test_1_dry_run_identical,
        test_2_dry_run_changed,
        test_4_second_run_no_changes,  # runs test_3 internally as setup
        test_5_wrong_remote_identity,
        test_6_wrong_branch,
        test_7_dirty_worktree,
        test_8_disallowed_destination,
        test_9_invalid_source_governance,
        test_10_simulated_hash_mismatch,
        test_11_unrelated_staged_file,
        test_12_simulated_commit_failure,
        test_13_simulated_push_failure,
        test_14_force_push_prohibited,
        test_15_remote_branch_missing,
        test_16_unexpected_failure_fails_closed,
        test_17_source_immutability,
        test_18_pmo_state_unchanged,
        test_19_no_branch_creation,
        test_20_empty_branch_first_publication,
    ):
        fn()
    total = len(_RESULTS)
    failed = [n for n, ok in _RESULTS if not ok]
    print("\n{}/{} passed".format(total - len(failed), total))
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
