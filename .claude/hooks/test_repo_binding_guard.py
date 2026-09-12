#!/usr/bin/env python3
"""Regression tests for .claude/hooks/repo-binding-guard.py.

Stdlib only. Run: python3 .claude/hooks/test_repo_binding_guard.py
Exit 0 = all pass, 1 = at least one failure.

Two areas are covered:

1. PMO-REPO-001..010 - the pre-existing repository-binding validation for
   `git push` originating from the PMO Engine's own ambient working
   directory. Semantics must be byte-for-byte unchanged from before the
   managed-workspace delegation feature was added. Uses a real local Git
   checkout (never a real network remote) standing in for the PMO Engine
   repository.

2. The managed-publishing-workspace delegation boundary (DOMAIN B): a
   `git push` whose EFFECTIVE Git working directory (after resolving shell
   `cd` sequencing, `-C`, wrapper commands, and `~` / `$HOME` expansion,
   then normalizing away any `..` / path-traversal) resolves under
   `~/.pmo-workspaces/` must be silently delegated (repo-binding-guard
   returns None without evaluating it) so that artifact-publish-guard.py is
   solely responsible for approving or denying it.

3. DOMAIN A - the PMO Engine repository itself: a `git push` whose
   effective working directory resolves (by walking upward) to a directory
   containing `.claude/pmo-engine-config.yaml` must be validated using
   ONLY that file - never `.pmo/project-config.yaml`, even when both exist
   at the same root. Everything else (DOMAIN C) falls through to the
   unchanged behaviour in area 1.

Never touches a real network, a real Bitbucket/GitHub remote, or any file
outside per-test temporary directories.
"""

import importlib.util
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "repo-binding-guard.py")
_spec = importlib.util.spec_from_file_location("repo_binding_guard", HOOK)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

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

CONFIG_YAML = (
    'repository:\n'
    '  provider: "{provider}"\n'
    '  workspace: "{workspace}"\n'
    '  repository: "{repository}"\n'
    '  working_branch: "{branch}"\n'
).format(provider=PROVIDER, workspace=WORKSPACE, repository=REPOSITORY, branch=BRANCH)

CONFIG_NO_REPOSITORY_SECTION = 'schema_version: "1.0"\n'

CONFIG_MISSING_WORKSPACE = (
    'repository:\n'
    '  provider: "{provider}"\n'
    '  repository: "{repository}"\n'
    '  working_branch: "{branch}"\n'
).format(provider=PROVIDER, repository=REPOSITORY, branch=BRANCH)

CONFIG_MISSING_REPOSITORY = (
    'repository:\n'
    '  provider: "{provider}"\n'
    '  workspace: "{workspace}"\n'
    '  working_branch: "{branch}"\n'
).format(provider=PROVIDER, workspace=WORKSPACE, branch=BRANCH)


def rm(path):
    shutil.rmtree(path, ignore_errors=True)


def sh(args, cwd=None, check_rc=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check_rc and r.returncode != 0:
        raise RuntimeError(
            "command failed: {} :: stdout={!r} stderr={!r}".format(
                args, r.stdout, r.stderr
            )
        )
    return r


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def git_identity(path):
    sh(["git", "config", "user.email", "pmo-test@example.com"], cwd=path)
    sh(["git", "config", "user.name", "PMO Test"], cwd=path)


def mk_engine_root(config_text=CONFIG_YAML, remote_url=None, branch=BRANCH,
                    init_git=True, no_remote=False):
    """A fake PMO Engine checkout: `.pmo/project-config.yaml` plus (usually)
    a real local Git repo with an `origin` remote, standing in for the
    Engine's own ambient working directory that repo-binding-guard.py
    validates `git push` against."""
    root = tempfile.mkdtemp(prefix="repo-guard-engine-")
    if config_text is not None:
        _w(os.path.join(root, ".pmo", "project-config.yaml"), config_text)
    if init_git:
        sh(["git", "init", "-q", root])
        git_identity(root)
        sh(["git", "checkout", "-q", "-b", branch], cwd=root)
        sh(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=root)
        if not no_remote:
            url = remote_url or "git@bitbucket.org:{}/{}.git".format(WORKSPACE, REPOSITORY)
            sh(["git", "remote", "add", "origin", url], cwd=root)
    return root


def payload(command, cwd):
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}


def managed_ws(home, *parts):
    return os.path.join(home, ".pmo-workspaces", *parts)


# =========================================================================== #
# Area 1 - PMO-REPO-001..010 regression (must remain unchanged)
# =========================================================================== #

def test_repo_001_missing_config():
    engine = mk_engine_root(config_text=None)
    try:
        cmd = "git push origin {}".format(BRANCH)
        d = mod.process(payload(cmd, engine))
        check("REPO_001_missing_config", code(d) == "PMO-REPO-001", (code(d), msg(d)))
    finally:
        rm(engine)


def test_repo_002_no_repository_section():
    engine = mk_engine_root(config_text=CONFIG_NO_REPOSITORY_SECTION)
    try:
        cmd = "git push origin {}".format(BRANCH)
        d = mod.process(payload(cmd, engine))
        check("REPO_002_no_repository_section", code(d) == "PMO-REPO-002", (code(d), msg(d)))
    finally:
        rm(engine)


def test_repo_003_missing_workspace():
    engine = mk_engine_root(config_text=CONFIG_MISSING_WORKSPACE)
    try:
        cmd = "git push origin {}".format(BRANCH)
        d = mod.process(payload(cmd, engine))
        check("REPO_003_missing_workspace", code(d) == "PMO-REPO-003", (code(d), msg(d)))
    finally:
        rm(engine)


def test_repo_004_missing_repository():
    engine = mk_engine_root(config_text=CONFIG_MISSING_REPOSITORY)
    try:
        cmd = "git push origin {}".format(BRANCH)
        d = mod.process(payload(cmd, engine))
        check("REPO_004_missing_repository", code(d) == "PMO-REPO-004", (code(d), msg(d)))
    finally:
        rm(engine)


def test_repo_005_remote_unresolvable():
    engine = mk_engine_root(no_remote=True)
    try:
        cmd = "git push origin {}".format(BRANCH)
        d = mod.process(payload(cmd, engine))
        check("REPO_005_remote_unresolvable", code(d) == "PMO-REPO-005", (code(d), msg(d)))
    finally:
        rm(engine)


def test_repo_006_remote_unparseable():
    engine = mk_engine_root(remote_url="not-a-git-url")
    try:
        cmd = "git push origin {}".format(BRANCH)
        d = mod.process(payload(cmd, engine))
        check("REPO_006_remote_unparseable", code(d) == "PMO-REPO-006", (code(d), msg(d)))
    finally:
        rm(engine)


def test_repo_007_provider_mismatch():
    engine = mk_engine_root(
        remote_url="https://github.com/{}/{}.git".format(WORKSPACE, REPOSITORY)
    )
    try:
        cmd = "git push origin {}".format(BRANCH)
        d = mod.process(payload(cmd, engine))
        check("REPO_007_provider_mismatch", code(d) == "PMO-REPO-007", (code(d), msg(d)))
    finally:
        rm(engine)


def test_repo_008_workspace_repo_mismatch():
    engine = mk_engine_root(remote_url="git@bitbucket.org:wrong-workspace/wrong-repo.git")
    try:
        cmd = "git push origin {}".format(BRANCH)
        d = mod.process(payload(cmd, engine))
        check("REPO_008_workspace_repo_mismatch", code(d) == "PMO-REPO-008", (code(d), msg(d)))
    finally:
        rm(engine)


def test_repo_009_branch_mismatch():
    engine = mk_engine_root(branch="other-branch")
    try:
        cmd = "git push origin other-branch"  # not the configured working_branch
        d = mod.process(payload(cmd, engine))
        check("REPO_009_branch_mismatch", code(d) == "PMO-REPO-009", (code(d), msg(d)))
    finally:
        rm(engine)


def test_repo_009_explicit_branch_target_allowed():
    # Current branch differs from configured working_branch, but the push
    # explicitly targets the configured branch - Rule 9 must allow this.
    engine = mk_engine_root(branch="other-branch")
    try:
        cmd = "git push origin {}".format(BRANCH)
        d = mod.process(payload(cmd, engine))
        check("REPO_009_explicit_target_allowed", d is None, (code(d), msg(d)))
    finally:
        rm(engine)


def test_repo_009_detached_head():
    engine = mk_engine_root()
    try:
        rev = sh(["git", "rev-parse", "HEAD"], cwd=engine).stdout.strip()
        sh(["git", "checkout", "-q", rev], cwd=engine)
        cmd = "git push origin some-other-branch"
        d = mod.process(payload(cmd, engine))
        check("REPO_009_detached_head", code(d) == "PMO-REPO-009", (code(d), msg(d)))
    finally:
        rm(engine)


def test_repo_allow_when_fully_matched():
    engine = mk_engine_root()
    try:
        cmd = "git push origin {}".format(BRANCH)
        d = mod.process(payload(cmd, engine))
        check("REPO_allow_when_fully_matched", d is None, (code(d), msg(d)))
    finally:
        rm(engine)


def test_repo_010_internal_error_fails_closed():
    engine = mk_engine_root()
    original = mod.validate_push
    try:
        def _boom(*a, **k):
            raise RuntimeError("simulated internal fault")
        mod.validate_push = _boom
        cmd = "git push origin {}".format(BRANCH)
        d = mod.process(payload(cmd, engine))
        check("REPO_010_internal_error_fails_closed", code(d) == "PMO-REPO-010",
              (code(d), msg(d)))
    finally:
        mod.validate_push = original
        rm(engine)


# =========================================================================== #
# Area 2 - managed workspace delegation boundary
# =========================================================================== #

# --- A: ordinary PMO Engine push -> still evaluated by this guard -------- #

def test_delegation_A_ordinary_engine_push_still_evaluated():
    # Deliberately misconfigured (provider mismatch) so a PMO-REPO-007 deny
    # is only possible if validate_push actually ran - proving this is not
    # a silent delegation/allow.
    engine = mk_engine_root(
        remote_url="https://github.com/{}/{}.git".format(WORKSPACE, REPOSITORY)
    )
    try:
        cmd = "git push origin {}".format(BRANCH)
        d = mod.process(payload(cmd, engine))
        check("DELEGATION_A_ordinary_push_evaluated", code(d) == "PMO-REPO-007",
              (code(d), msg(d)))
    finally:
        rm(engine)


# --- B: managed workspace exact path (no cd) -> DELEGATES ---------------- #

def test_delegation_B_managed_workspace_exact_path():
    home = tempfile.mkdtemp(prefix="repo-guard-home-")
    ws = managed_ws(home, "bitbucket", WORKSPACE, REPOSITORY, "smart-basket")
    try:
        cmd = "git push origin main"
        # Ambient cwd already lies inside the managed workspace - no config
        # exists there, so a non-None result would prove validate_push ran
        # (i.e. delegation failed).
        d = mod.process(payload(cmd, ws), home=home)
        check("DELEGATION_B_exact_path_delegates", d is None, (code(d), msg(d)))
    finally:
        rm(home)


# --- C: `cd ... && git push` -> DELEGATES --------------------------------- #

def test_delegation_C_cd_and_push():
    home = tempfile.mkdtemp(prefix="repo-guard-home-")
    engine = mk_engine_root(config_text=None)  # no config: would 001 if evaluated
    ws = managed_ws(home, "bitbucket", WORKSPACE, REPOSITORY, "smart-basket")
    try:
        cmd = "cd {} && git push origin main".format(ws)
        d = mod.process(payload(cmd, engine), home=home)
        check("DELEGATION_C_cd_and_push_delegates", d is None, (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)


# --- D: `cd ... ; git push` -> DELEGATES ---------------------------------- #

def test_delegation_D_cd_semicolon_push():
    home = tempfile.mkdtemp(prefix="repo-guard-home-")
    engine = mk_engine_root(config_text=None)
    ws = managed_ws(home, "bitbucket", WORKSPACE, REPOSITORY, "smart-basket")
    try:
        cmd = "cd {} ; git push origin main".format(ws)
        d = mod.process(payload(cmd, engine), home=home)
        check("DELEGATION_D_cd_semicolon_delegates", d is None, (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)


# --- E: Path.home()-based (`~`) resolution -> DELEGATES ------------------- #

def test_delegation_E_path_home_based():
    fake_home = tempfile.mkdtemp(prefix="repo-guard-fakehome-")
    engine = mk_engine_root(config_text=None)
    old_home = os.environ.get("HOME")
    try:
        os.environ["HOME"] = fake_home
        cmd = "cd ~/.pmo-workspaces/bitbucket/{}/{}/smart-basket && git push origin main".format(
            WORKSPACE, REPOSITORY
        )
        # home= intentionally omitted: this must resolve via the real
        # Path.home()/os.path.expanduser, not a hardcoded path.
        d = mod.process(payload(cmd, engine))
        check("DELEGATION_E_path_home_delegates", d is None, (code(d), msg(d)))
    finally:
        if old_home is not None:
            os.environ["HOME"] = old_home
        else:
            os.environ.pop("HOME", None)
        rm(fake_home)
        rm(engine)


# --- F: `~/.pmo-workspaces/../Projects/...` -> DOES NOT DELEGATE --------- #

def test_delegation_F_traversal_not_delegated():
    fake_home = tempfile.mkdtemp(prefix="repo-guard-fakehome-")
    engine = mk_engine_root(config_text=None)
    old_home = os.environ.get("HOME")
    try:
        os.environ["HOME"] = fake_home
        cmd = "cd ~/.pmo-workspaces/../Projects/Claude-Skills && git push origin main"
        d = mod.process(payload(cmd, engine))
        # Falls through to the unchanged existing behaviour (validated
        # against the ambient engine cwd, which has no project-config.yaml).
        check("DELEGATION_F_traversal_not_delegated", code(d) == "PMO-REPO-001",
              (code(d), msg(d)))
    finally:
        if old_home is not None:
            os.environ["HOME"] = old_home
        else:
            os.environ.pop("HOME", None)
        rm(fake_home)
        rm(engine)


# --- G: `/tmp/.pmo-workspaces/...` lookalike -> DOES NOT DELEGATE -------- #

def test_delegation_G_tmp_lookalike_not_delegated():
    home = tempfile.mkdtemp(prefix="repo-guard-home-")
    engine = mk_engine_root(config_text=None)
    try:
        fake = tempfile.mkdtemp(prefix="repo-guard-nottmp-")
        lookalike = os.path.join(fake, ".pmo-workspaces", "fake")
        cmd = "cd {} && git push origin main".format(lookalike)
        d = mod.process(payload(cmd, engine), home=home)
        check("DELEGATION_G_tmp_lookalike_not_delegated", code(d) == "PMO-REPO-001",
              (code(d), msg(d)))
        rm(fake)
    finally:
        rm(home)
        rm(engine)


# --- H: echo mentioning the workspace -> text-only, never an execution --- #

def test_delegation_H_echo_text_only_not_triggered():
    engine = mk_engine_root(config_text=None)
    try:
        cmd = 'echo "cd ~/.pmo-workspaces/x && git push"'
        push_args, effective_cwd = mod.parse_first_git_push(cmd, engine)
        check("DELEGATION_H_echo_no_push_detected",
              push_args is None and effective_cwd is None,
              (push_args, effective_cwd))
        d = mod.process(payload(cmd, engine))
        check("DELEGATION_H_echo_process_allows_no_op", d is None, (code(d), msg(d)))
    finally:
        rm(engine)


# --- I: non-push git command retains prior behaviour (always allowed) --- #

def test_delegation_I_non_push_git_command():
    engine = mk_engine_root(config_text=None)  # would 001 if this were a push
    try:
        d = mod.process(payload("git status", engine))
        check("DELEGATION_I_non_push_git_allowed", d is None, (code(d), msg(d)))
    finally:
        rm(engine)


# --- J: unrelated Bash retains prior behaviour ---------------------------- #

def test_delegation_J_unrelated_bash():
    d = mod.process(payload("ls -la", "/tmp"))
    check("DELEGATION_J_unrelated_bash_allowed", d is None, (code(d), msg(d)))


# --- extra coverage: nested harmless commands before the git op ---------- #

def test_delegation_nested_harmless_commands():
    home = tempfile.mkdtemp(prefix="repo-guard-home-")
    engine = mk_engine_root(config_text=None)
    ws = managed_ws(home, "bitbucket", WORKSPACE, REPOSITORY, "smart-basket")
    try:
        cmd = "pwd && ls -la && cd {} && git push origin main".format(ws)
        d = mod.process(payload(cmd, engine), home=home)
        check("DELEGATION_nested_harmless_commands", d is None, (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)


# --- extra coverage: `cd "$HOME/..."` quoted form ------------------------- #

def test_delegation_home_var_quoted_form():
    fake_home = tempfile.mkdtemp(prefix="repo-guard-fakehome-")
    engine = mk_engine_root(config_text=None)
    old_home = os.environ.get("HOME")
    try:
        os.environ["HOME"] = fake_home
        cmd = ('cd "$HOME/.pmo-workspaces/bitbucket/{}/{}/smart-basket" '
               '&& git push origin main').format(WORKSPACE, REPOSITORY)
        d = mod.process(payload(cmd, engine))
        check("DELEGATION_home_var_quoted_delegates", d is None, (code(d), msg(d)))
    finally:
        if old_home is not None:
            os.environ["HOME"] = old_home
        else:
            os.environ.pop("HOME", None)
        rm(fake_home)
        rm(engine)


# --- extra coverage: `command git push ...` wrapper ----------------------- #

def test_delegation_wrapper_command_form():
    home = tempfile.mkdtemp(prefix="repo-guard-home-")
    engine = mk_engine_root(config_text=None)
    ws = managed_ws(home, "bitbucket", WORKSPACE, REPOSITORY, "smart-basket")
    try:
        cmd = "cd {} && command git push origin main".format(ws)
        d = mod.process(payload(cmd, engine), home=home)
        check("DELEGATION_wrapper_command_form_delegates", d is None, (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)


# --- extra coverage: `/usr/bin/git push ...` absolute path --------------- #

def test_delegation_absolute_git_path_form():
    home = tempfile.mkdtemp(prefix="repo-guard-home-")
    engine = mk_engine_root(config_text=None)
    ws = managed_ws(home, "bitbucket", WORKSPACE, REPOSITORY, "smart-basket")
    try:
        cmd = "cd {} && /usr/bin/git push origin main".format(ws)
        d = mod.process(payload(cmd, engine), home=home)
        check("DELEGATION_absolute_git_path_delegates", d is None, (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)


# --- extra coverage: `git -C <ws> push ...` (no `cd` at all) ------------- #
# This is the invocation shape artifact-publish-guard.py's own skill/tests
# actually use in practice, so it must delegate too.

def test_delegation_dash_C_form():
    home = tempfile.mkdtemp(prefix="repo-guard-home-")
    engine = mk_engine_root(config_text=None)
    ws = managed_ws(home, "bitbucket", WORKSPACE, REPOSITORY, "smart-basket")
    try:
        cmd = "git -C {} push origin main".format(ws)
        d = mod.process(payload(cmd, engine), home=home)
        check("DELEGATION_dash_C_form_delegates", d is None, (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)


# --- extra coverage: env-wrapped ordinary (non-managed) push unaffected -- #

def test_delegation_env_wrapper_ordinary_push_unaffected():
    engine = mk_engine_root()  # fully matching config + remote + branch
    try:
        cmd = "env GIT_TRACE=1 git push origin {}".format(BRANCH)
        d = mod.process(payload(cmd, engine))
        check("DELEGATION_env_wrapper_ordinary_push_allowed", d is None, (code(d), msg(d)))
    finally:
        rm(engine)


# =========================================================================== #
# Unit-level coverage for the new parsing / classification helpers
# =========================================================================== #

def test_units_parse_first_git_push():
    args, cwd = mod.parse_first_git_push("cd /tmp/ws && git push origin main", "/session/cwd")
    check("unit_cd_and_push", args == ["origin", "main"] and cwd == "/tmp/ws", (args, cwd))

    args, cwd = mod.parse_first_git_push("cd /tmp/ws; git push origin main", "/session/cwd")
    check("unit_cd_semicolon_push", args == ["origin", "main"] and cwd == "/tmp/ws", (args, cwd))

    args, cwd = mod.parse_first_git_push("git status", "/session/cwd")
    check("unit_non_push_not_detected", args is None and cwd is None, (args, cwd))

    args, cwd = mod.parse_first_git_push('echo "git push"', "/session/cwd")
    check("unit_echo_git_push_not_triggered", args is None and cwd is None, (args, cwd))

    args, cwd = mod.parse_first_git_push("git -C /tmp/ws push origin main", "/session/cwd")
    check("unit_dash_C_captured", args == ["origin", "main"] and cwd == "/tmp/ws", (args, cwd))

    args, cwd = mod.parse_first_git_push("env X=1 git push origin main", "/session/cwd")
    check("unit_env_wrapper_cwd_unchanged",
          args == ["origin", "main"] and cwd == "/session/cwd", (args, cwd))


def test_units_is_under_managed_workspace_root():
    home = tempfile.mkdtemp(prefix="repo-guard-home-")
    try:
        inside = os.path.join(home, ".pmo-workspaces", "bitbucket", "ws", "repo", "branch")
        check("unit_inside_root_true",
              mod.is_under_managed_workspace_root(inside, home=home))

        traversal = os.path.join(home, ".pmo-workspaces", "..", "Projects", "Claude-Skills")
        check("unit_traversal_false",
              not mod.is_under_managed_workspace_root(traversal, home=home))

        outside = os.path.join("/tmp", ".pmo-workspaces", "fake")
        check("unit_outside_home_false",
              not mod.is_under_managed_workspace_root(outside, home=home))

        check("unit_root_itself_true",
              mod.is_under_managed_workspace_root(
                  os.path.join(home, ".pmo-workspaces"), home=home))
    finally:
        rm(home)


# =========================================================================== #
# Area 3 - DOMAIN A: PMO Engine repository (.claude/pmo-engine-config.yaml)
# =========================================================================== #

ENGINE_PROVIDER = "github"
ENGINE_WORKSPACE = "zohaibtekrevol"
ENGINE_REPOSITORY = "Claude-Skills"
ENGINE_REMOTE_NAME = "origin"
ENGINE_BRANCH = "pmo-framework"

CONFLICTING_PROJECT_CONFIG = (
    'repository:\n'
    '  provider: "bitbucket"\n'
    '  workspace: "some-other-workspace"\n'
    '  repository: "some-other-repo"\n'
    '  working_branch: "some-other-branch"\n'
)


def mk_engine_config_yaml(provider=ENGINE_PROVIDER, workspace=ENGINE_WORKSPACE,
                           repository=ENGINE_REPOSITORY, remote_name=ENGINE_REMOTE_NAME,
                           working_branch=ENGINE_BRANCH, verified=False):
    return (
        'engine:\n'
        '  provider: "{provider}"\n'
        '  workspace: "{workspace}"\n'
        '  repository: "{repository}"\n'
        '  remote_name: "{remote_name}"\n'
        '  working_branch: "{working_branch}"\n'
        '  verified: {verified}\n'
    ).format(provider=provider, workspace=workspace, repository=repository,
             remote_name=remote_name, working_branch=working_branch,
             verified="true" if verified else "false")


def mk_pmo_engine_root(engine_yaml=None, branch=ENGINE_BRANCH, remotes=None,
                    also_project_config=False, project_yaml=None):
    """A fake PMO Engine checkout: `.claude/pmo-engine-config.yaml` plus a
    real local Git repo standing in for the actual Engine repository.
    Optionally also carries a `.pmo/project-config.yaml` with DELIBERATELY
    CONFLICTING routing, to prove Domain A never consults it."""
    root = tempfile.mkdtemp(prefix="engine-guard-root-")
    _w(os.path.join(root, ".claude", "pmo-engine-config.yaml"),
       engine_yaml if engine_yaml is not None else mk_engine_config_yaml())
    if also_project_config:
        _w(os.path.join(root, ".pmo", "project-config.yaml"),
           project_yaml if project_yaml is not None else CONFLICTING_PROJECT_CONFIG)
    sh(["git", "init", "-q", root])
    git_identity(root)
    sh(["git", "checkout", "-q", "-b", branch], cwd=root)
    sh(["git", "add", ".claude"], cwd=root)
    sh(["git", "commit", "-q", "-m", "init"], cwd=root)
    remotes = remotes or {"origin": "git@github.com:{}/{}.git".format(
        ENGINE_WORKSPACE, ENGINE_REPOSITORY)}
    for name, url in remotes.items():
        sh(["git", "remote", "add", name, url], cwd=root)
    return root


def stage_file(root, relpath, content="content\n"):
    _w(os.path.join(root, relpath), content)
    sh(["git", "add", relpath], cwd=root)


# --- 1: Engine push reads Engine config, not project config ------------- #

def test_engine_1_reads_engine_config_not_project_config():
    root = mk_pmo_engine_root(
        engine_yaml=mk_engine_config_yaml(verified=True),
        also_project_config=True,  # deliberately conflicting bitbucket routing
    )
    try:
        d = mod.process(payload("git push origin pmo-framework", root))
        check("ENGINE_1_reads_engine_config_not_project", d is None, (code(d), msg(d)))
    finally:
        rm(root)


# --- 2: verified=false blocks at the verification gate ------------------- #

def test_engine_2_verified_false_blocks():
    root = mk_pmo_engine_root(engine_yaml=mk_engine_config_yaml(verified=False))
    try:
        d = mod.process(payload("git push origin pmo-framework", root))
        check("ENGINE_2_verified_false_blocks__008", code(d) == "PMO-ENGINE-008",
              (code(d), msg(d)))
    finally:
        rm(root)


# --- 3 / 4: no fallback to main / master ---------------------------------- #

def test_engine_3_no_fallback_to_main():
    root = mk_pmo_engine_root(engine_yaml=mk_engine_config_yaml(verified=True))
    try:
        d = mod.process(payload("git push origin main", root))
        check("ENGINE_3_no_fallback_main__006", code(d) == "PMO-ENGINE-006",
              (code(d), msg(d)))
    finally:
        rm(root)


def test_engine_4_no_fallback_to_master():
    root = mk_pmo_engine_root(engine_yaml=mk_engine_config_yaml(verified=True))
    try:
        d = mod.process(payload("git push origin master", root))
        check("ENGINE_4_no_fallback_master__006", code(d) == "PMO-ENGINE-006",
              (code(d), msg(d)))
    finally:
        rm(root)


# --- 5: wrong remote name denied ------------------------------------------ #

def test_engine_5_wrong_remote_name_denied():
    root = mk_pmo_engine_root(
        engine_yaml=mk_engine_config_yaml(verified=True),
        remotes={
            "origin": "git@github.com:{}/{}.git".format(ENGINE_WORKSPACE, ENGINE_REPOSITORY),
            "bitbucket": "git@bitbucket.org:devops-tekrevol/lets-explore-more-specs.git",
        },
    )
    try:
        d = mod.process(payload("git push bitbucket pmo-framework", root))
        check("ENGINE_5_wrong_remote_denied__005", code(d) == "PMO-ENGINE-005",
              (code(d), msg(d)))
    finally:
        rm(root)


# --- 6: project-specific staged content blocked --------------------------- #

def test_engine_6_project_content_staged_blocked():
    root = mk_pmo_engine_root(engine_yaml=mk_engine_config_yaml(verified=True))
    try:
        stage_file(root, "docs/pmo/intent/intent.md", "# Intent\n")
        d = mod.process(payload("git push origin pmo-framework", root))
        check("ENGINE_6_project_content_staged__009", code(d) == "PMO-ENGINE-009",
              (code(d), msg(d)))
    finally:
        rm(root)


# --- 7: permitted framework content + verified=true -> allowed ----------- #

def test_engine_7_framework_content_verified_allowed():
    root = mk_pmo_engine_root(engine_yaml=mk_engine_config_yaml(verified=True))
    try:
        stage_file(root, ".claude/hooks/new-hook.py", "# new hook\n")
        d = mod.process(payload("git push origin pmo-framework", root))
        check("ENGINE_7_framework_content_verified__allow", d is None, (code(d), msg(d)))
    finally:
        rm(root)


# --- 8 / 9: managed workspace delegates and never reads Engine config ---- #

def test_engine_8_managed_workspace_still_delegates():
    home = tempfile.mkdtemp(prefix="repo-guard-home-")
    ws = managed_ws(home, "bitbucket", WORKSPACE, REPOSITORY, "smart-basket")
    try:
        cmd = "git push origin main"
        d = mod.process(payload(cmd, ws), home=home)
        check("ENGINE_8_managed_workspace_delegates", d is None, (code(d), msg(d)))
    finally:
        rm(home)


def test_engine_9_managed_workspace_ignores_engine_config():
    # The ambient session cwd IS a recognized Engine root, but the push's
    # effective cwd (after `cd`) is the managed workspace - Domain B must be
    # checked and matched BEFORE Domain A is ever considered, so the Engine
    # config's presence at the ambient cwd must have zero effect.
    home = tempfile.mkdtemp(prefix="repo-guard-home-")
    engine_root = mk_pmo_engine_root(engine_yaml=mk_engine_config_yaml(verified=False))
    ws = managed_ws(home, "bitbucket", WORKSPACE, REPOSITORY, "smart-basket")
    try:
        cmd = "cd {} && git push origin main".format(ws)
        d = mod.process(payload(cmd, engine_root), home=home)
        check("ENGINE_9_managed_workspace_ignores_engine_config", d is None,
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine_root)


# --- 10: Engine behavior does not read project config (unit-level) ------- #

def test_engine_10_engine_ignores_project_config_unit():
    with_project = mk_pmo_engine_root(
        engine_yaml=mk_engine_config_yaml(verified=True), also_project_config=True,
    )
    without_project = mk_pmo_engine_root(engine_yaml=mk_engine_config_yaml(verified=True))
    try:
        d1 = mod.validate_engine_push(with_project, ["origin", "pmo-framework"])
        d2 = mod.validate_engine_push(without_project, ["origin", "pmo-framework"])
        check("ENGINE_10_identical_outcome_regardless_of_project_config",
              d1 is None and d2 is None, (code(d1), code(d2)))
    finally:
        rm(with_project)
        rm(without_project)


# --- 11: unrelated repository push -> existing fail-closed behaviour ----- #

def test_engine_11_unrelated_repository_fails_closed():
    root = tempfile.mkdtemp(prefix="unrelated-repo-")
    try:
        sh(["git", "init", "-q", root])
        git_identity(root)
        sh(["git", "checkout", "-q", "-b", "main"], cwd=root)
        sh(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=root)
        sh(["git", "remote", "add", "origin", "git@example.com:someone/somewhere.git"], cwd=root)
        d = mod.process(payload("git push origin main", root))
        check("ENGINE_11_unrelated_repo_fails_closed__001", code(d) == "PMO-REPO-001",
              (code(d), msg(d)))
    finally:
        rm(root)


# --- 12: force push prohibited for Engine domain -------------------------- #

def test_engine_12_force_push_prohibited():
    root = mk_pmo_engine_root(engine_yaml=mk_engine_config_yaml(verified=True))
    try:
        d = mod.process(payload("git push --force origin pmo-framework", root))
        check("ENGINE_12_force_push_prohibited__007", code(d) == "PMO-ENGINE-007",
              (code(d), msg(d)))
    finally:
        rm(root)


# --- 13: traversal/path spoofing does not fool Engine-root detection ----- #

def test_engine_13_traversal_does_not_spoof_engine_root():
    root = mk_pmo_engine_root(engine_yaml=mk_engine_config_yaml(verified=True))
    try:
        outside = os.path.dirname(root)  # a sibling temp dir, NOT the engine root
        spoofed = os.path.join(root, "..", os.path.basename(outside), "..",
                                os.path.basename(root))
        # This normalizes right back to `root` itself - still correctly
        # recognized as the Engine root, never fooled into landing elsewhere.
        found = mod.locate_engine_root(spoofed)
        check("ENGINE_13_traversal_normalizes_correctly",
              found is not None and os.path.realpath(found) == os.path.realpath(root),
              (found, root))

        genuinely_outside = tempfile.mkdtemp(prefix="not-engine-")
        try:
            found2 = mod.locate_engine_root(genuinely_outside)
            check("ENGINE_13_outside_dir_not_engine_root", found2 is None, found2)
        finally:
            rm(genuinely_outside)
    finally:
        rm(root)


# --- 14: text-only command references do not misclassify ----------------- #

def test_engine_14_echo_text_only_not_misclassified():
    root = mk_pmo_engine_root(engine_yaml=mk_engine_config_yaml(verified=False))
    try:
        cmd = 'echo "cd {} && git push origin pmo-framework"'.format(root)
        push_args, effective_cwd = mod.parse_first_git_push(cmd, "/tmp")
        check("ENGINE_14_echo_no_push_detected",
              push_args is None and effective_cwd is None, (push_args, effective_cwd))
        d = mod.process(payload(cmd, "/tmp"))
        check("ENGINE_14_echo_process_allows_no_op", d is None, (code(d), msg(d)))
    finally:
        rm(root)


# --- 15: multiple remotes do not create ambiguity ------------------------- #

def test_engine_15_multiple_remotes_no_ambiguity():
    root = mk_pmo_engine_root(
        engine_yaml=mk_engine_config_yaml(verified=True),
        remotes={
            "origin": "git@github.com:{}/{}.git".format(ENGINE_WORKSPACE, ENGINE_REPOSITORY),
            "bitbucket": "git@bitbucket.org:devops-tekrevol/lets-explore-more-specs.git",
        },
    )
    try:
        d = mod.process(payload("git push origin pmo-framework", root))
        check("ENGINE_15_multiple_remotes_correct_one_used__allow", d is None,
              (code(d), msg(d)))
    finally:
        rm(root)


# --------------------------------------------------------------------------- #
# Unit-level coverage for the new Engine-domain helpers
# --------------------------------------------------------------------------- #

def test_units_engine_helpers():
    root = mk_pmo_engine_root(engine_yaml=mk_engine_config_yaml(verified=True))
    try:
        found = mod.locate_engine_root(root)
        check("unit_locate_engine_root_finds_self", found == str(Path(root).resolve()),
              (found, root))

        subdir = os.path.join(root, "docs")
        os.makedirs(subdir, exist_ok=True)
        found_sub = mod.locate_engine_root(subdir)
        check("unit_locate_engine_root_walks_up", found_sub == str(Path(root).resolve()),
              found_sub)

        cfg = mod.load_engine_config(root)
        fields, err = mod.extract_engine_fields(cfg)
        check("unit_extract_engine_fields_ok", err is None and fields["verified"] is True,
              (fields, code(err)))

        bad_cfg = mod.parse_simple_yaml("engine:\n  provider: \"github\"\n")
        _, err2 = mod.extract_engine_fields(bad_cfg)
        check("unit_extract_engine_fields_missing__001", code(err2) == "PMO-ENGINE-001",
              code(err2))
    finally:
        rm(root)

    check("unit_is_engine_publishable_hooks",
          mod.is_engine_publishable_path(".claude/hooks/repo-binding-guard.py"))
    check("unit_is_engine_publishable_lib",
          mod.is_engine_publishable_path(".claude/lib/artifact_publish_core.py"))
    check("unit_rejects_docs_pmo", not mod.is_engine_publishable_path("docs/pmo/intent/intent.md"))
    check("unit_rejects_dot_pmo", not mod.is_engine_publishable_path(".pmo/project-config.yaml"))
    check("unit_rejects_pycache", not mod.is_engine_publishable_path(".claude/lib/__pycache__/x.pyc"))
    check("unit_rejects_pyc_suffix", not mod.is_engine_publishable_path(".claude/lib/x.pyc"))
    check("unit_rejects_scratchpad",
          not mod.is_engine_publishable_path(".claude/scratchpad/notes.md"))


# --------------------------------------------------------------------------- #

def main():
    for fn in (
        test_repo_001_missing_config,
        test_repo_002_no_repository_section,
        test_repo_003_missing_workspace,
        test_repo_004_missing_repository,
        test_repo_005_remote_unresolvable,
        test_repo_006_remote_unparseable,
        test_repo_007_provider_mismatch,
        test_repo_008_workspace_repo_mismatch,
        test_repo_009_branch_mismatch,
        test_repo_009_explicit_branch_target_allowed,
        test_repo_009_detached_head,
        test_repo_allow_when_fully_matched,
        test_repo_010_internal_error_fails_closed,
        test_delegation_A_ordinary_engine_push_still_evaluated,
        test_delegation_B_managed_workspace_exact_path,
        test_delegation_C_cd_and_push,
        test_delegation_D_cd_semicolon_push,
        test_delegation_E_path_home_based,
        test_delegation_F_traversal_not_delegated,
        test_delegation_G_tmp_lookalike_not_delegated,
        test_delegation_H_echo_text_only_not_triggered,
        test_delegation_I_non_push_git_command,
        test_delegation_J_unrelated_bash,
        test_delegation_nested_harmless_commands,
        test_delegation_home_var_quoted_form,
        test_delegation_wrapper_command_form,
        test_delegation_absolute_git_path_form,
        test_delegation_dash_C_form,
        test_delegation_env_wrapper_ordinary_push_unaffected,
        test_units_parse_first_git_push,
        test_units_is_under_managed_workspace_root,
        test_engine_1_reads_engine_config_not_project_config,
        test_engine_2_verified_false_blocks,
        test_engine_3_no_fallback_to_main,
        test_engine_4_no_fallback_to_master,
        test_engine_5_wrong_remote_name_denied,
        test_engine_6_project_content_staged_blocked,
        test_engine_7_framework_content_verified_allowed,
        test_engine_8_managed_workspace_still_delegates,
        test_engine_9_managed_workspace_ignores_engine_config,
        test_engine_10_engine_ignores_project_config_unit,
        test_engine_11_unrelated_repository_fails_closed,
        test_engine_12_force_push_prohibited,
        test_engine_13_traversal_does_not_spoof_engine_root,
        test_engine_14_echo_text_only_not_misclassified,
        test_engine_15_multiple_remotes_no_ambiguity,
        test_units_engine_helpers,
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
