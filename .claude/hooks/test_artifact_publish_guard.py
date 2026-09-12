#!/usr/bin/env python3
"""Regression tests for .claude/hooks/artifact-publish-guard.py.

Stdlib only. Run: python3 .claude/hooks/test_artifact_publish_guard.py
Exit 0 = all pass, 1 = at least one failure.

Covers scenarios A-AZ from the artifact-publish-guard specification
(.claude/skills/artifact-publish/SKILL.md). Uses temporary directories and
local (file-path / local bare) Git repositories only - never the real Smart
Basket Bitbucket branch, never a managed production workspace, never a real
network call. All fixtures are created and torn down per test.
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "artifact-publish-guard.py")
_spec = importlib.util.spec_from_file_location("artifact_publish_guard", HOOK)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

# artifact-publish-guard.py is a thin shim: process()/dispatch_validation()/
# validate_add() etc. actually live in, and internally resolve each other
# from, the shared core module's own globals - so fault-injection tests that
# monkeypatch a single function must patch it on the CORE module, not on the
# guard shim, for `mod.process(...)` to observe the patched behaviour.
# Loading the guard registers "artifact_publish_core" in sys.modules (it
# adds .claude/lib to sys.path and imports it by that name) - fetch that
# exact module object rather than loading a second, disconnected copy.
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
BRANCH = "smart-basket"

CONFIG_YAML = (
    'repository:\n'
    '  provider: "{provider}"\n'
    '  workspace: "{workspace}"\n'
    '  repository: "{repository}"\n'
    '  working_branch: "{branch}"\n'
).format(provider=PROVIDER, workspace=WORKSPACE, repository=REPOSITORY, branch=BRANCH)


def rm(path):
    shutil.rmtree(path, ignore_errors=True)


def sh(args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
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


def mk_engine_root(config_text=CONFIG_YAML):
    """A fake PMO Engine checkout: only `.pmo/project-config.yaml` matters."""
    root = tempfile.mkdtemp(prefix="publish-guard-engine-")
    if config_text is not None:
        _w(os.path.join(root, ".pmo", "project-config.yaml"), config_text)
    return root


def mk_bare_remote(tmp_root, workspace_slug, repo_slug, branch, files=None,
                    empty=True):
    """A local bare repo standing in for the Project Artifact Repository,
    addressed by a `file://`-free local path (parse_remote_url's local-path
    branch reads the last two path segments as workspace/repository, so the
    bare repo's parent directory name doubles as the 'workspace')."""
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


def mk_workspace(home, fields, origin_url, checkout_branch=None,
                  detached=False):
    """A managed-workspace-shaped local repo at the exact path this guard
    expects, with `origin` pointing at `origin_url`."""
    ws = mod.managed_workspace_path(
        fields["provider"], fields["workspace"], fields["repository"],
        fields["working_branch"], home=home,
    )
    ws = str(ws)
    os.makedirs(ws, exist_ok=True)
    sh(["git", "init", "-q", ws])
    git_identity(ws)
    sh(["git", "remote", "add", "origin", origin_url], cwd=ws)
    branch = checkout_branch or fields["working_branch"]
    sh(["git", "checkout", "-q", "-b", branch], cwd=ws)
    sh(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=ws)
    if detached:
        rev = sh(["git", "rev-parse", "HEAD"], cwd=ws).stdout.strip()
        sh(["git", "checkout", "-q", rev], cwd=ws)
    return ws


def default_fields():
    return {
        "provider": PROVIDER,
        "workspace": WORKSPACE,
        "repository": REPOSITORY,
        "working_branch": BRANCH,
    }


def payload_for(command, cwd, home_dir):
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd,
    }, home_dir


# --------------------------------------------------------------------------- #
# A - unrelated Bash command
# --------------------------------------------------------------------------- #

def test_A():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    try:
        d = mod.process({"tool_name": "Bash",
                          "tool_input": {"command": "ls -la"},
                          "cwd": home}, home=home)
        check("A_unrelated_bash_allowed", d is None, d)
    finally:
        rm(home)


# --------------------------------------------------------------------------- #
# B - missing project config during controlled publish -> 001
# --------------------------------------------------------------------------- #

def test_B():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root(config_text=None)  # no .pmo/project-config.yaml
    ws = mod.managed_workspace_path(PROVIDER, WORKSPACE, REPOSITORY, BRANCH,
                                     home=home)
    os.makedirs(str(ws), exist_ok=True)
    sh(["git", "init", "-q", str(ws)])
    try:
        cmd = "git -C {} add docs/pmo/intent/intent.md".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("B_missing_project_config__001", code(d) == "PMO-PUBLISH-001",
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)


# --------------------------------------------------------------------------- #
# C - unreachable repository -> 002
# --------------------------------------------------------------------------- #

def test_C():
    exists, d = mod.check_branch_exists_remote(
        "/definitely/not/a/git/repo/at/all", BRANCH
    )
    check("C_unreachable_repository__002", exists is None and code(d) == "PMO-PUBLISH-002",
          (exists, code(d), msg(d)))


# --------------------------------------------------------------------------- #
# D - simulated auth failure -> 003
# --------------------------------------------------------------------------- #

def test_D():
    c1 = mod.classify_remote_error("Permission denied (publickey).")
    c2 = mod.classify_remote_error("fatal: Authentication failed for "
                                    "'https://bitbucket.org/x/y.git/'")
    check("D_simulated_auth_failure__003",
          c1 == "PMO-PUBLISH-003" and c2 == "PMO-PUBLISH-003", (c1, c2))


# --------------------------------------------------------------------------- #
# E - wrong target remote identity -> 004
# --------------------------------------------------------------------------- #

def test_E():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        wrong_bare = mk_bare_remote(tmp, "wrong-workspace", "wrong-repo", BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, wrong_bare)
        _w(os.path.join(ws, "docs", "pmo", "intent", "intent.md"), "# Intent\n")
        cmd = "git -C {} add docs/pmo/intent/intent.md".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("E_wrong_remote_identity__004", code(d) == "PMO-PUBLISH-004",
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


# --------------------------------------------------------------------------- #
# F - wrong checked-out branch -> 005
# --------------------------------------------------------------------------- #

def test_F():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare, checkout_branch="feature-x")
        _w(os.path.join(ws, "docs", "pmo", "intent", "intent.md"), "# Intent\n")
        cmd = "git -C {} add docs/pmo/intent/intent.md".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("F_wrong_checked_out_branch__005", code(d) == "PMO-PUBLISH-005",
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


# --------------------------------------------------------------------------- #
# G - detached HEAD -> 005
# --------------------------------------------------------------------------- #

def test_G():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare, detached=True)
        _w(os.path.join(ws, "docs", "pmo", "intent", "intent.md"), "# Intent\n")
        cmd = "git -C {} add docs/pmo/intent/intent.md".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("G_detached_head__005", code(d) == "PMO-PUBLISH-005", (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


# --------------------------------------------------------------------------- #
# H - dirty unrelated target worktree -> 006
# --------------------------------------------------------------------------- #

def test_H():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        _w(os.path.join(ws, "docs", "pmo", "intent", "intent.md"), "# Intent\n")
        _w(os.path.join(ws, "notes.txt"), "unrelated developer scratch\n")
        cmd = "git -C {} add docs/pmo/intent/intent.md".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("H_dirty_unrelated_worktree__006", code(d) == "PMO-PUBLISH-006",
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


# --------------------------------------------------------------------------- #
# I / J / K - allowed Intent / Scope / canonical Specs paths
# --------------------------------------------------------------------------- #

def _allow_single_path(label, relpath):
    # Path-allowlisting is what these scenarios test; per-family governance
    # PASS/FAIL is exercised separately and deterministically by test_P.
    # Stub it here so I/J/K/AF/AR don't need a full, hand-authored
    # governance-passing Intent/Scope/Specs fixture.
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    original = core_mod.validate_source_governance
    try:
        core_mod.validate_source_governance = lambda family, root: None
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        _w(os.path.join(ws, relpath), "content\n")
        cmd = "git -C {} add {}".format(ws, relpath)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check(label, d is None, (code(d), msg(d)))
    finally:
        core_mod.validate_source_governance = original
        rm(home)
        rm(engine)
        rm(tmp)


def test_I():
    _allow_single_path("I_allowed_intent_path", "docs/pmo/intent/intent.md")


def test_J():
    _allow_single_path("J_allowed_scope_path", "docs/pmo/scope/scope-v0.1.md")


def test_K():
    _allow_single_path("K_canonical_specs_md", "docs/pmo/specs/specs.md")


# --------------------------------------------------------------------------- #
# L / M / N / O - unapproved paths -> 007
# --------------------------------------------------------------------------- #

def _deny_single_path(label, relpath):
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        _w(os.path.join(ws, relpath), "content\n")
        cmd = "git -C {} add {}".format(ws, relpath)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check(label, code(d) == "PMO-PUBLISH-007", (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def test_L():
    _deny_single_path("L_specs_v0_1_md__007", "docs/pmo/specs/specs-v0.1.md")


def test_M():
    _deny_single_path("M_dot_claude_path__007", ".claude/hooks/x.py")


def test_N():
    _deny_single_path("N_dot_pmo_path__007", ".pmo/project-config.yaml")


def test_O():
    _deny_single_path("O_docs_pmo_sources_path__007", "docs/pmo/sources/contract.pdf")


# --------------------------------------------------------------------------- #
# P - invalid Specs source governance -> 008
# --------------------------------------------------------------------------- #

def test_P():
    root = tempfile.mkdtemp(prefix="publish-guard-source-")
    try:
        _w(os.path.join(root, "docs", "pmo", "specs", "specs.md"),
           "# Specs\n\nnot a real spec document\n")
        # deliberately no docs/pmo/scope/ at all -> specs-governance-guard's
        # validate_scope_readiness() fails first, deterministically.
        d = mod.validate_source_governance("specs", root)
        check("P_invalid_specs_governance__008", code(d) == "PMO-PUBLISH-008",
              (code(d), msg(d)))
    finally:
        rm(root)


# --------------------------------------------------------------------------- #
# Q - source/destination hash mismatch -> 009
# --------------------------------------------------------------------------- #

def test_Q():
    tmp = tempfile.mkdtemp(prefix="publish-guard-hash-")
    try:
        src = os.path.join(tmp, "src.md")
        dst = os.path.join(tmp, "dst.md")
        _w(src, "authoritative content\n")
        _w(dst, "tampered content\n")
        d = mod.verify_hash_match(src, dst)
        check("Q_hash_mismatch__009", code(d) == "PMO-PUBLISH-009", (code(d), msg(d)))
        _w(dst, "authoritative content\n")
        d2 = mod.verify_hash_match(src, dst)
        check("Q2_hash_match__allow", d2 is None, (code(d2), msg(d2)))
    finally:
        rm(tmp)


# --------------------------------------------------------------------------- #
# R / S / V / W - commit staging governance
# --------------------------------------------------------------------------- #

def test_R():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        _w(os.path.join(ws, "unrelated.txt"), "oops\n")
        sh(["git", "add", "unrelated.txt"], cwd=ws)
        cmd = "git -C {} commit -m test".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("R_staged_unrelated_file__010", code(d) == "PMO-PUBLISH-010",
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def test_S_and_V():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        _w(os.path.join(ws, "docs", "pmo", "scope", "scope-v0.1.md"), "# Scope\n")
        sh(["git", "add", "docs/pmo/scope/scope-v0.1.md"], cwd=ws)
        cmd = "git -C {} commit -m test".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("S_staged_only_allowlisted__allow", d is None, (code(d), msg(d)))
        check("V_controlled_valid_commit__allow", d is None, (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def test_W():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        _w(os.path.join(ws, "docs", "pmo", "feedback", "FDB-001.md"), "# FDB\n")
        _w(os.path.join(ws, "extra.txt"), "stray\n")
        sh(["git", "add", "docs/pmo/feedback/FDB-001.md", "extra.txt"], cwd=ws)
        cmd = "git -C {} commit -m test".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("W_commit_with_unrelated_staged__010", code(d) == "PMO-PUBLISH-010",
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


# --------------------------------------------------------------------------- #
# T / U - broad `git add .`
# --------------------------------------------------------------------------- #

def test_T():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        _w(os.path.join(ws, "docs", "pmo", "change-requests", "CR-001.md"), "# CR\n")
        cmd = "git -C {} add .".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("T_broad_add_only_approved__allow", d is None, (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def test_U():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        _w(os.path.join(ws, "docs", "pmo", "change-requests", "CR-001.md"), "# CR\n")
        _w(os.path.join(ws, "sneaky.env"), "SECRET=1\n")
        cmd = "git -C {} add -A".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("U_broad_add_with_unrelated__deny", code(d) == "PMO-PUBLISH-007",
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


# --------------------------------------------------------------------------- #
# X / Y / Z / AA-AD / AE / AO / AP / AQ / AR / AS / AT - push governance
# --------------------------------------------------------------------------- #

def test_X():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        cmd = "git -C {} push origin {}".format(ws, BRANCH)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("X_normal_exact_branch_push__allow", d is None, (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def test_Y():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        cmd = "git -C {} push origin other-branch".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("Y_push_wrong_branch__005", code(d) == "PMO-PUBLISH-005", (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def test_Z():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        cmd = "git -C {} push upstream {}".format(ws, BRANCH)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("Z_push_wrong_remote__004", code(d) == "PMO-PUBLISH-004", (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def _force_case(label, push_suffix):
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        cmd = "git -C {} push {}".format(ws, push_suffix)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check(label, code(d) == "PMO-PUBLISH-013", (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def test_AA():
    _force_case("AA_force_push_long_flag__013", "--force origin {}".format(BRANCH))


def test_AB():
    _force_case("AB_force_push_short_flag__013", "-f origin {}".format(BRANCH))


def test_AC():
    _force_case("AC_force_with_lease__013", "--force-with-lease origin {}".format(BRANCH))


def test_AD():
    _force_case("AD_force_refspec__013",
                 "origin +{}:{}".format(BRANCH, BRANCH))


def test_AE():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, "main", empty=True)
        fields = default_fields()  # working_branch == "smart-basket"
        os.makedirs(str(mod.managed_workspace_path(
            fields["provider"], fields["workspace"], fields["repository"],
            fields["working_branch"], home=home)), exist_ok=True)
        ws = str(mod.managed_workspace_path(
            fields["provider"], fields["workspace"], fields["repository"],
            fields["working_branch"], home=home))
        sh(["git", "init", "-q", ws])
        git_identity(ws)
        sh(["git", "remote", "add", "origin", bare], cwd=ws)
        sh(["git", "checkout", "-q", "-b", BRANCH], cwd=ws)
        sh(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=ws)
        cmd = "git -C {} add docs/pmo/intent/intent.md".format(ws)
        _w(os.path.join(ws, "docs", "pmo", "intent", "intent.md"), "# Intent\n")
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("AE_configured_branch_missing__014", code(d) == "PMO-PUBLISH-014",
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def test_AF():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    original = core_mod.validate_source_governance
    try:
        core_mod.validate_source_governance = lambda family, root: None
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH, empty=True)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        _w(os.path.join(ws, "docs", "pmo", "intent", "intent.md"), "# Intent\n")
        cmd = "git -C {} add docs/pmo/intent/intent.md".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("AF_empty_existing_branch__allow", d is None, (code(d), msg(d)))
    finally:
        core_mod.validate_source_governance = original
        rm(home)
        rm(engine)
        rm(tmp)


def test_AO():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        # Bare repo is reachable and has *a* branch, just not the configured
        # one - reachability/auth succeed, only branch existence fails.
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, "develop", empty=True)
        fields = default_fields()
        ws = str(mod.managed_workspace_path(
            fields["provider"], fields["workspace"], fields["repository"],
            fields["working_branch"], home=home))
        os.makedirs(ws, exist_ok=True)
        sh(["git", "init", "-q", ws])
        git_identity(ws)
        sh(["git", "remote", "add", "origin", bare], cwd=ws)
        sh(["git", "checkout", "-q", "-b", BRANCH], cwd=ws)
        sh(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=ws)
        cmd = "git -C {} push origin {}".format(ws, BRANCH)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("AO_auth_ok_branch_missing__014", code(d) == "PMO-PUBLISH-014",
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def test_AP():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        wrong_bare = mk_bare_remote(tmp, "some-other-ws", "some-other-repo", BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, wrong_bare)
        cmd = "git -C {} push origin {}".format(ws, BRANCH)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("AP_branch_exists_wrong_remote__004", code(d) == "PMO-PUBLISH-004",
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def test_AQ():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare, checkout_branch="wip")
        cmd = "git -C {} push origin {}".format(ws, BRANCH)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("AQ_branch_exists_current_wrong__005", code(d) == "PMO-PUBLISH-005",
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def test_AR():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    original = core_mod.validate_source_governance
    try:
        core_mod.validate_source_governance = lambda family, root: None
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        _w(os.path.join(ws, "docs", "pmo", "intent", "intent.md"), "# Intent\n")
        cmd = "git -C {} add docs/pmo/intent/intent.md".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("AR_fully_verified__allow", d is None, (code(d), msg(d)))
    finally:
        core_mod.validate_source_governance = original
        rm(home)
        rm(engine)
        rm(tmp)


def test_AS():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    config = (
        'repository:\n'
        '  provider: "{provider}"\n'
        '  workspace: "{workspace}"\n'
        '  repository: "{repository}"\n'
        '  working_branch: "main"\n'
    ).format(provider=PROVIDER, workspace=WORKSPACE, repository=REPOSITORY)
    engine = mk_engine_root(config_text=config)
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, "main")
        fields = {"provider": PROVIDER, "workspace": WORKSPACE,
                  "repository": REPOSITORY, "working_branch": "main"}
        ws = mk_workspace(home, fields, bare)
        cmd = "git -C {} push origin main".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("AS_main_allowed_when_configured__allow", d is None, (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def test_AT():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()  # working_branch == "smart-basket"
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        cmd = "git -C {} push origin main".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("AT_main_fallback_denied", code(d) in ("PMO-PUBLISH-005", "PMO-PUBLISH-014"),
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


# --------------------------------------------------------------------------- #
# AG / AH / AI - branch-creation commands prohibited
# --------------------------------------------------------------------------- #

def test_AG():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        cmd = "git -C {} switch --orphan {}".format(ws, BRANCH)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("AG_switch_orphan_denied__014", code(d) == "PMO-PUBLISH-014",
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def test_AH():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        cmd = "git -C {} checkout -b {}".format(ws, BRANCH)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("AH_checkout_dash_b_denied__014", code(d) == "PMO-PUBLISH-014",
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


def test_AI():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        cmd = "git -C {} switch -c {}".format(ws, BRANCH)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("AI_switch_dash_c_denied__014", code(d) == "PMO-PUBLISH-014",
              (code(d), msg(d)))
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


# --------------------------------------------------------------------------- #
# AJ - AN - Bash command parsing
# --------------------------------------------------------------------------- #

def test_AJ():
    invs = mod.parse_git_invocations("cd /tmp/ws && git push origin main", "/session/cwd")
    ok = len(invs) == 1 and invs[0]["subcommand"] == "push" and invs[0]["cwd"] == "/tmp/ws"
    check("AJ_cd_and_push_detected", ok, invs)


def test_AK():
    invs = mod.parse_git_invocations("cd /tmp/ws; git add docs/pmo/intent/intent.md",
                                      "/session/cwd")
    ok = len(invs) == 1 and invs[0]["subcommand"] == "add" and invs[0]["cwd"] == "/tmp/ws"
    check("AK_cd_semicolon_add_detected", ok, invs)


def test_AL():
    invs = mod.parse_git_invocations("env GIT_TRACE=1 git push origin main", "/session/cwd")
    ok = len(invs) == 1 and invs[0]["subcommand"] == "push" and invs[0]["cwd"] == "/session/cwd"
    check("AL_env_wrapper_detected", ok, invs)


def test_AM():
    invs = mod.parse_git_invocations("/usr/bin/git push origin main", "/session/cwd")
    ok = len(invs) == 1 and invs[0]["subcommand"] == "push"
    check("AM_absolute_path_git_detected", ok, invs)


def test_AN():
    invs = mod.parse_git_invocations('echo "git push"', "/session/cwd")
    check("AN_echo_git_push_not_triggered", invs == [], invs)


# --------------------------------------------------------------------------- #
# AU - no-change publish support
# --------------------------------------------------------------------------- #

def test_AU():
    tmp = tempfile.mkdtemp(prefix="publish-guard-nochange-")
    try:
        src = os.path.join(tmp, "specs.md")
        dst = os.path.join(tmp, "specs-dst.md")
        _w(src, "identical content\n")
        _w(dst, "identical content\n")
        no_change = mod.is_no_change(src, dst)
        d = mod.verify_hash_match(src, dst)
        check("AU_no_change_detected_and_passes_hash", no_change and d is None,
              (no_change, code(d)))

        home = tempfile.mkdtemp(prefix="publish-guard-home-")
        engine = mk_engine_root()
        remotes = tempfile.mkdtemp(prefix="publish-guard-remotes-")
        bare = mk_bare_remote(remotes, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        cmd = "git -C {} commit -m noop".format(ws)  # nothing staged
        d2 = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                           "cwd": engine}, home=home)
        check("AU_empty_commit_not_blocked", d2 is None, (code(d2), msg(d2)))
        rm(home)
        rm(engine)
        rm(remotes)
    finally:
        rm(tmp)


# --------------------------------------------------------------------------- #
# AV - state protection
# --------------------------------------------------------------------------- #

def test_AV():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    try:
        cfg_path = os.path.join(engine, ".pmo", "project-config.yaml")
        before = open(cfg_path, "r", encoding="utf-8").read()

        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        _w(os.path.join(ws, "docs", "pmo", "intent", "intent.md"), "# Intent\n")
        cmd = "git -C {} add docs/pmo/intent/intent.md".format(ws)
        mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                     "cwd": engine}, home=home)

        after = open(cfg_path, "r", encoding="utf-8").read()
        check("AV_project_config_unchanged", before == after, "config mutated")
    finally:
        rm(home)
        rm(engine)
        rm(tmp)


# --------------------------------------------------------------------------- #
# AW - internal exception fails closed (015)
# --------------------------------------------------------------------------- #

def test_AW():
    home = tempfile.mkdtemp(prefix="publish-guard-home-")
    engine = mk_engine_root()
    tmp = tempfile.mkdtemp(prefix="publish-guard-remotes-")
    original = core_mod.validate_add
    try:
        bare = mk_bare_remote(tmp, WORKSPACE, REPOSITORY, BRANCH)
        fields = default_fields()
        ws = mk_workspace(home, fields, bare)
        _w(os.path.join(ws, "docs", "pmo", "intent", "intent.md"), "# Intent\n")

        def _boom(*a, **k):
            raise RuntimeError("simulated internal fault")

        core_mod.validate_add = _boom
        cmd = "git -C {} add docs/pmo/intent/intent.md".format(ws)
        d = mod.process({"tool_name": "Bash", "tool_input": {"command": cmd},
                          "cwd": engine}, home=home)
        check("AW_internal_exception_fails_closed__015", code(d) == "PMO-PUBLISH-015",
              (code(d), msg(d)))
    finally:
        core_mod.validate_add = original
        rm(home)
        rm(engine)
        rm(tmp)


# --------------------------------------------------------------------------- #
# AX - parser/classification exception does not block unrelated Bash
# --------------------------------------------------------------------------- #

def test_AX():
    original = core_mod.parse_git_invocations
    try:
        def _boom(command, cwd):
            raise RuntimeError("simulated parser fault")

        core_mod.parse_git_invocations = _boom
        d = mod.process({"tool_name": "Bash",
                          "tool_input": {"command": "echo hello"},
                          "cwd": "/tmp"})
        check("AX_parser_fault_does_not_block", d is None, (code(d), msg(d)))
    finally:
        core_mod.parse_git_invocations = original


# --------------------------------------------------------------------------- #
# AY - path traversal attempt
# --------------------------------------------------------------------------- #

def test_AY():
    p = mod.managed_workspace_path("bitbucket", "../../etc", "passwd", BRANCH)
    check("AY_traversal_rejected_in_path_builder", p is None, p)

    fields = {"provider": "bitbucket", "workspace": "../../etc",
              "repository": "passwd", "working_branch": BRANCH}
    path, d = mod.resolve_expected_workspace(fields)
    check("AY_traversal_rejected_via_resolver", path is None and code(d) == "PMO-PUBLISH-001",
          (path, code(d)))


# --------------------------------------------------------------------------- #
# AZ - managed workspace derives from Path.home(), not a hardcoded path
# --------------------------------------------------------------------------- #

def test_AZ():
    fake_home = tempfile.mkdtemp(prefix="publish-guard-fakehome-")
    old_home = os.environ.get("HOME")
    try:
        os.environ["HOME"] = fake_home
        p = mod.managed_workspace_path(PROVIDER, WORKSPACE, REPOSITORY, BRANCH)
        ok = str(p).startswith(fake_home) and "/Users/" not in str(p)
        check("AZ_uses_path_home_not_hardcoded", ok, p)
    finally:
        if old_home is not None:
            os.environ["HOME"] = old_home
        else:
            os.environ.pop("HOME", None)
        rm(fake_home)


# --------------------------------------------------------------------------- #
# Unit-level coverage for parsing / classification helpers
# --------------------------------------------------------------------------- #

def test_units():
    check("unit_is_allowlisted_intent", mod.is_allowlisted_path("docs/pmo/intent/intent.md"))
    check("unit_is_allowlisted_scope", mod.is_allowlisted_path("docs/pmo/scope/scope-v0.1.md"))
    check("unit_is_allowlisted_specs_canonical",
          mod.is_allowlisted_path("docs/pmo/specs/specs.md"))
    check("unit_rejects_specs_version_file",
          not mod.is_allowlisted_path("docs/pmo/specs/specs-v0.1.md"))
    check("unit_rejects_final_specs_alias",
          not mod.is_allowlisted_path("docs/pmo/specs/final-specs.md"))
    check("unit_rejects_dot_claude", not mod.is_allowlisted_path(".claude/hooks/x.py"))
    check("unit_rejects_dot_pmo", not mod.is_allowlisted_path(".pmo/project-config.yaml"))
    check("unit_rejects_sources", not mod.is_allowlisted_path("docs/pmo/sources/contract.pdf"))
    check("unit_rejects_exports", not mod.is_allowlisted_path("docs/pmo/exports/x.docx"))

    check("unit_family_intent", mod.family_of("docs/pmo/intent/intent.md") == "intent")
    check("unit_family_specs", mod.family_of("docs/pmo/specs/specs.md") == "specs")
    check("unit_family_unknown", mod.family_of(".claude/hooks/x.py") is None)

    check("unit_force_dash_f", mod.has_force_flag(["origin", "-f", "main"]))
    check("unit_force_long", mod.has_force_flag(["--force", "origin", "main"]))
    check("unit_force_lease", mod.has_force_flag(["--force-with-lease=origin/main",
                                                    "origin", "main"]))
    check("unit_force_refspec", mod.has_force_flag(["origin", "+main:main"]))
    check("unit_no_force", not mod.has_force_flag(["origin", "main"]))

    check("unit_branch_creation_switch_orphan",
          mod.is_branch_creation_command("switch", ["--orphan", "x"]))
    check("unit_branch_creation_checkout_b",
          mod.is_branch_creation_command("checkout", ["-b", "x"]))
    check("unit_branch_creation_switch_c",
          mod.is_branch_creation_command("switch", ["-c", "x"]))
    check("unit_branch_creation_branch_new",
          mod.is_branch_creation_command("branch", ["x"]))
    check("unit_branch_listing_not_creation",
          not mod.is_branch_creation_command("branch", ["-a"]))
    check("unit_branch_delete_not_creation",
          not mod.is_branch_creation_command("branch", ["-d", "x"]))
    check("unit_plain_checkout_not_creation",
          not mod.is_branch_creation_command("checkout", ["main"]))

    check("unit_parse_remote_bitbucket_ssh",
          mod.parse_remote_url("git@bitbucket.org:devops-tekrevol/lets-explore-more-specs.git")
          == {"host": "bitbucket.org", "workspace": "devops-tekrevol",
              "repository": "lets-explore-more-specs"})
    check("unit_parse_remote_bitbucket_https",
          mod.parse_remote_url("https://bitbucket.org/devops-tekrevol/lets-explore-more-specs.git")
          == {"host": "bitbucket.org", "workspace": "devops-tekrevol",
              "repository": "lets-explore-more-specs"})
    check("unit_parse_remote_bitbucket_ssh_scheme",
          mod.parse_remote_url("ssh://git@bitbucket.org/devops-tekrevol/lets-explore-more-specs.git")
          == {"host": "bitbucket.org", "workspace": "devops-tekrevol",
              "repository": "lets-explore-more-specs"})
    check("unit_provider_from_host_bitbucket",
          mod.provider_from_host("bitbucket.org") == "bitbucket")
    check("unit_provider_from_host_unknown", mod.provider_from_host("example.com") is None)

    check("unit_refspec_dest_simple",
          mod.refspec_destinations(["main"]) == {"main"})
    check("unit_refspec_dest_full_ref",
          mod.refspec_destinations(["HEAD:refs/heads/smart-basket"]) == {"smart-basket"})
    check("unit_refspec_dest_forced",
          mod.refspec_destinations(["+main:main"]) == {"main"})


# --------------------------------------------------------------------------- #

def main():
    test_units()
    for fn in (
        test_A, test_B, test_C, test_D, test_E, test_F, test_G, test_H,
        test_I, test_J, test_K, test_L, test_M, test_N, test_O, test_P,
        test_Q, test_R, test_S_and_V, test_W, test_T, test_U,
        test_X, test_Y, test_Z, test_AA, test_AB, test_AC, test_AD,
        test_AE, test_AF, test_AG, test_AH, test_AI, test_AJ, test_AK,
        test_AL, test_AM, test_AN, test_AO, test_AP, test_AQ, test_AR,
        test_AS, test_AT, test_AU, test_AV, test_AW, test_AX, test_AY,
        test_AZ,
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
