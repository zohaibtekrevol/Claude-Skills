#!/usr/bin/env python3
"""Regression tests for governed publication state: publication receipts
(.pmo/publications/), lifecycle detection of an already-published approved
baseline, publisher Specs-version extraction, and governed reconciliation.

All fixtures are synthetic temporary projects and LOCAL bare Git remotes
(never the real repository, never the network).
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import test_specs_structural_repair as T  # noqa: E402
import test_artifact_publisher as PT  # noqa: E402
import publication_evidence_core as pev  # noqa: E402
import pmo_lifecycle_core as plc  # noqa: E402
import specs_approval_core as sac  # noqa: E402

check = T.check
_RESULTS = T._RESULTS
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
BRANCH = "pmo-artifacts"
SPECS_REL = "docs/pmo/specs/specs.md"
CFG = T.CONFIG_YAML.replace(
    "  verified: true\n",
    '  working_branch: "{}"\n  verified: true\n'.format(BRANCH))

EXEC_EVIDENCE = ("- **Execution Authorized:** true\n- **Execution Authorization "
                 "Evidence:** PM-DECISION 2026-09-12 (test fixture)")


def approved_specs(version="0.1"):
    text = T.build_specs(include_validation_summary=True, spec_version=version)
    text = text.replace("- **Execution Authorized:** false", EXEC_EVIDENCE)
    if version != "0.1":
        # a later approved version keeps the prior version's history row
        row = re.search(r"(?m)^\| {} \|.*$".format(re.escape(version)), text).group(0)
        text = text.replace(row, row.replace("| {} |".format(version), "| 0.1 |", 1) + "\n" + row, 1)
    return text


def mk_project(version="0.1", specs=None):
    text = specs if specs is not None else approved_specs(version)
    return T.mkroot(specs=text, config=CFG,
                    specs_approval=T.matching_specs_approval(version))


def specs_bytes(root):
    return open(os.path.join(root, *SPECS_REL.split("/")), "rb").read()


def current_receipt(root, **over):
    data = specs_bytes(root)
    text = data.decode()
    cfg = pev.iac.load_project_config(root)
    fields, _ = pev.apc.extract_repo_fields(cfg)
    r = pev.build_receipt("SMART-BASKET", "specs", SPECS_REL,
                          pev.artifact_version("specs", text, cfg), hashlib.sha256(data).hexdigest(),
                          fields, "a" * 40, "2026-09-21T12:00:00Z")
    r.update(over)
    return r


def put_receipt(root, receipt, name=None):
    """Write raw (possibly invalid) receipt evidence, bypassing write-time validation."""
    d = pev.publications_dir(root)
    os.makedirs(d, exist_ok=True)
    name = name or pev.receipt_filename("specs", receipt.get("version", "x"),
                                        (receipt.get("artifact_sha256") or "0" * 12))
    with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
        fh.write(pev.render_receipt_yaml({k: receipt.get(k, "") for k in pev.REQUIRED_FIELDS}))


def state(root):
    return plc.get_project_state(root)


def test_1_unpublished_is_publication_ready():
    root = mk_project()
    try:
        s = state(root)
        check("1/approved_unpublished_publication_ready",
              s["lifecycle_state"] == "PUBLICATION_READY" and s["next_action"] == "PUBLISH"
              and s["publication_status"] == "Eligible", s)
    finally:
        T._cleanup(root)


def test_2_3_valid_receipt_is_published_and_publish_not_suggested():
    root = mk_project()
    try:
        path, err = pev.write_receipt(root, current_receipt(root))
        check("2/receipt_written", err is None and os.path.isfile(path), err)
        s = state(root)
        check("2/published_state", s["lifecycle_state"] == "BASELINE_APPROVED"
              and s["publication_status"] == "Published" and s["health"] == "Baseline Published", s)
        check("3/publish_not_suggested", s["next_action"] != "PUBLISH" and s["next_action"] == "SHOW_STATUS", s)
        check("2/evidence_in_engineering_diag",
              s["_engineering"]["publication"]["evidence"]["remote_commit"] == "a" * 40)
        check("2/lifecycle_deterministic", state(root) == s)
        before = specs_bytes(root)
        state(root)
        check("12/lifecycle_never_mutates_specs", specs_bytes(root) == before)
        check("2/receipt_is_evidence_only_no_specs_content",
              "Functional Requirements" not in open(path).read())
    finally:
        T._cleanup(root)


def rejected(over, name, extra_check=None):
    root = mk_project()
    try:
        put_receipt(root, current_receipt(root, **over))
        s = state(root)
        check("4-8/{}_rejected".format(name),
              s["lifecycle_state"] == "PUBLICATION_READY" and s["next_action"] == "PUBLISH", s)
        rej = s["_engineering"]["publication"]["evidence"]["receipts"]["rejected"]
        check("4-8/{}_reason_reported".format(name), len(rej) == 1 and rej[0]["reason"], rej)
    finally:
        T._cleanup(root)


def test_4_to_8_mismatched_or_unverified_receipts():
    rejected({"project_id": "OTHER-PROJECT"}, "wrong_project")
    rejected({"artifact": "docs/pmo/intent/intent.md"}, "wrong_artifact")
    rejected({"artifact_family": "intent"}, "wrong_family")
    rejected({"version": "0.2"}, "wrong_version")
    rejected({"artifact_sha256": "b" * 64}, "wrong_hash")
    rejected({"branch": "some-other-branch"}, "wrong_branch")
    rejected({"repository": "other-repo"}, "wrong_repository")
    rejected({"status": "FAILED"}, "failed_status")
    rejected({"status": "PUSHED_UNVERIFIED"}, "unverified_status")
    rejected({"remote_verified": "false"}, "remote_not_verified")
    rejected({"remote_commit": "abc123"}, "short_remote_commit")
    rejected({"remote_commit": ""}, "missing_remote_commit")
    rejected({"published_at": "yesterday"}, "bad_timestamp")
    rejected({"evidence_source": "HAND_WRITTEN"}, "unknown_evidence_source")
    root = mk_project()
    try:
        os.makedirs(pev.publications_dir(root), exist_ok=True)
        with open(os.path.join(pev.publications_dir(root), "specs-v0.1-garbage.yaml"), "w") as fh:
            fh.write("not: [valid")
        s = state(root)
        check("8/malformed_receipt_not_evidence", s["lifecycle_state"] == "PUBLICATION_READY", s)
    finally:
        T._cleanup(root)
    # the writer itself refuses invalid evidence
    root = mk_project()
    try:
        path, err = pev.write_receipt(root, current_receipt(root, status="FAILED"))
        check("8/writer_refuses_failed_publication", path is None and err, err)
        check("8/no_file_created", not os.path.isdir(pev.publications_dir(root))
              or not os.listdir(pev.publications_dir(root)))
        pev.write_receipt(root, current_receipt(root))
        path2, err2 = pev.write_receipt(root, current_receipt(root, remote_commit="c" * 40))
        check("8/existing_receipt_is_immutable", path2 is None and "already exists" in err2, err2)
    finally:
        T._cleanup(root)


def test_9_10_stale_receipt_and_new_version():
    root = mk_project()
    try:
        old = current_receipt(root)
        pev.write_receipt(root, old)
        check("9/v0_1_published", state(root)["publication_status"] == "Published")
        # a later approved version (v0.2) is a different artifact
        new_specs = approved_specs("0.2")
        T._w(os.path.join(root, *SPECS_REL.split("/")), new_specs)
        T._w(os.path.join(root, ".pmo", "approvals", "specs-approval.yaml"),
             T.matching_specs_approval("0.2"))
        s = state(root)
        if s["lifecycle_state"] not in ("PUBLICATION_READY", "BASELINE_APPROVED"):
            check("10/v0_2_fixture_valid", False, (s["lifecycle_state"], s["_engineering"].get("specs")))
            return
        check("9/stale_v0_1_receipt_does_not_satisfy_v0_2",
              s["lifecycle_state"] == "PUBLICATION_READY" and s["next_action"] == "PUBLISH", s)
        rej = s["_engineering"]["publication"]["evidence"]["receipts"]["rejected"]
        check("9/stale_receipt_reported_as_history_with_reason", any("version" in r["reason"] for r in rej), rej)
        check("10/v0_1_receipt_file_preserved_as_history", len(os.listdir(pev.publications_dir(root))) == 1)
        pev.write_receipt(root, current_receipt(root))
        s2 = state(root)
        check("10/v0_2_published_separately", s2["lifecycle_state"] == "BASELINE_APPROVED"
              and s2["publication_status"] == "Published", s2)
        check("10/both_receipts_kept", len(os.listdir(pev.publications_dir(root))) == 2)
        # same version but changed bytes (hash) also invalidates
        T._w(os.path.join(root, *SPECS_REL.split("/")), new_specs.replace("Customer places", "Customer submits"))
        s3 = state(root)
        check("9/same_version_changed_hash_not_published",
              s3["publication_status"] != "Published", (s3["lifecycle_state"], s3["publication_status"]))
    finally:
        T._cleanup(root)


def test_11_approved_baseline_protection_intact():
    root = mk_project()
    try:
        d = T.core.specs_guard.full_spec_validation(root)
        check("11/approved_baseline_valid", d is None, d)
    finally:
        T._cleanup(root)
    for path in (".claude/hooks/test_specs_governance_guard.py",
                 ".claude/hooks/test_change_request_governance_guard.py",
                 ".claude/scripts/test_change_request_incorporator.py",
                 ".claude/scripts/test_specs_approval_recorder.py"):
        r = subprocess.run([sys.executable, os.path.join(REPO, path)], capture_output=True, text=True)
        check("11/suite_green/" + os.path.basename(path), r.returncode == 0)


# --------------------------------------------------------------------------- #
# Publisher: version extraction, commit message, receipt, reconciliation
# --------------------------------------------------------------------------- #

def pub_config(latest_version=None):
    return (
        'project:\n  id: "SMART-BASKET"\n  name: "Smart Basket"\n'
        'repository:\n  provider: "bitbucket"\n  workspace: "devops-tekrevol"\n'
        '  repository: "lets-explore-more-specs"\n  working_branch: "{b}"\n'
        'artifacts:\n  specifications:\n    latest_version: {v}\n'
    ).format(b=PT.BRANCH, v=('"{}"'.format(latest_version) if latest_version else "null"))


def test_13_14_15_version_extraction_and_commit_message():
    check("13/parser_reads_spec_version_field", pev.artifact_version("specs", approved_specs("0.1")) == "0.1")
    check("13/parser_reads_two_part_and_multi", pev.artifact_version("specs", approved_specs("1.12")) == "1.12")
    check("13/parser_unknown_when_absent", pev.artifact_version("specs", "# no version here") == "unknown")
    check("15/legacy_config_fallback_when_artifact_has_no_version",
          pev.artifact_version("specs", "# none", {"artifacts": {"specifications": {"latest_version": "0.7"}}}) == "0.7")
    check("13/artifact_wins_over_stale_config",
          pev.artifact_version("specs", approved_specs("0.1"),
                               {"artifacts": {"specifications": {"latest_version": "9.9"}}}) == "0.1")
    check("13/intent_version_parsed_from_real_shape",
          pev.artifact_version("intent", "# Intent\n\n- **Intent Version:** 0.3\n") == "0.3")
    for latest, label in ((None, "null_config"), ("0.2", "stale_config")):
        engine = PT.mk_engine_root(specs_text=approved_specs("0.1"), config_text=pub_config(latest))
        home = tempfile.mkdtemp(prefix="pubstate-home-")
        tmp = tempfile.mkdtemp(prefix="pubstate-remotes-")
        orig = PT.stub_governance()
        try:
            bare = PT.mk_bare_remote(tmp, PT.WORKSPACE, PT.REPOSITORY, PT.BRANCH,
                                     files={SPECS_REL: "# old\n"})
            before = open(os.path.join(engine, SPECS_REL), "rb").read()
            r = PT.mod.run("specs", "publish", root=engine, home=home, clone_url_override=bare)
            check("13/{}_transaction_version_0_1".format(label), r["transaction"]["version"] == "0.1", r["transaction"])
            check("14/{}_commit_message_v0_1".format(label),
                  PT.sh(["git", "log", "-1", "--format=%s", PT.BRANCH], cwd=bare).stdout.strip()
                  == "PMO: publish Smart Basket specs v0.1")
            check("12/{}_publish_never_mutates_specs".format(label),
                  open(os.path.join(engine, SPECS_REL), "rb").read() == before)
            check("14/{}_published".format(label), r["status"] == "PUBLISHED", (r["status"], r["decision"]))
            rc = r["receipt"] or {}
            check("14/{}_receipt_written".format(label), rc.get("written") is True, rc)
            if rc.get("written"):
                back = pev.load_receipts(engine, "specs")[0][1]
                check("14/{}_receipt_matches_publication".format(label),
                      back["remote_commit"] == r["commit_hash"] == PT.bare_head_sha(bare, PT.BRANCH)
                      and back["artifact_sha256"] == hashlib.sha256(before).hexdigest()
                      and back["version"] == "0.1" and back["evidence_source"] == "PUBLISHER_TRANSACTION"
                      and back["branch"] == PT.BRANCH, back)
                found, diag = pev.find_valid_publication(engine, "specs", SPECS_REL, "0.1",
                                                         hashlib.sha256(before).hexdigest())
                check("14/{}_receipt_is_valid_evidence".format(label), found is not None, diag)
        finally:
            PT.unstub_governance(orig)
            PT.rm(engine); PT.rm(home); PT.rm(tmp)
    # unknown version: no dangling 'v' in the commit message
    engine = PT.mk_engine_root(specs_text="# Specs without a version\n", config_text=pub_config(None))
    home = tempfile.mkdtemp(prefix="pubstate-home-"); tmp = tempfile.mkdtemp(prefix="pubstate-remotes-")
    orig = PT.stub_governance()
    try:
        bare = PT.mk_bare_remote(tmp, PT.WORKSPACE, PT.REPOSITORY, PT.BRANCH, files={SPECS_REL: "# old\n"})
        r = PT.mod.run("specs", "publish", root=engine, home=home, clone_url_override=bare)
        msg = PT.sh(["git", "log", "-1", "--format=%s", PT.BRANCH], cwd=bare).stdout.strip()
        check("14/unknown_version_message_has_no_vunknown", r["status"] == "PUBLISHED"
              and msg == "PMO: publish Smart Basket specs", msg)
        check("14/unversioned_publication_writes_no_receipt", (r["receipt"] or {}).get("written") is False
              and not os.path.isdir(pev.publications_dir(engine)))
    finally:
        PT.unstub_governance(orig)
        PT.rm(engine); PT.rm(home); PT.rm(tmp)


def test_16_lifecycle_after_real_publication_and_reconciliation():
    # (a) real publisher transaction -> lifecycle sees it
    root = mk_project()
    home = tempfile.mkdtemp(prefix="pubstate-home-"); tmp = tempfile.mkdtemp(prefix="pubstate-remotes-")
    try:
        T._w(os.path.join(root, ".pmo", "project-config.yaml"),
             pub_config(None).replace("bitbucket", "bitbucket").replace(PT.BRANCH, BRANCH))
        cfg_text = open(os.path.join(root, ".pmo", "project-config.yaml")).read()
        # keep the structural fixture's identity fields (project.client etc.)
        T._w(os.path.join(root, ".pmo", "project-config.yaml"), cfg_text)
        bare = PT.mk_bare_remote(tmp, PT.WORKSPACE, PT.REPOSITORY, BRANCH, files={SPECS_REL: "# old\n"})
        s0 = state(root)
        check("16/before_publication_ready", s0["lifecycle_state"] == "PUBLICATION_READY", s0["lifecycle_state"])
        r = PT.mod.run("specs", "publish", root=root, home=home, clone_url_override=bare)
        check("16/real_governance_publish_ok", r["status"] == "PUBLISHED", (r["status"], r["decision"]))
        s1 = state(root)
        check("16/after_publication_published", s1["lifecycle_state"] == "BASELINE_APPROVED"
              and s1["next_action"] == "SHOW_STATUS" and s1["publication_status"] == "Published", s1)
        # (b) reconciliation of a publication that pre-dates receipts
        for f in os.listdir(pev.publications_dir(root)):
            os.remove(os.path.join(pev.publications_dir(root), f))
        s2 = state(root)
        check("16/no_receipt_means_ready_again", s2["lifecycle_state"] == "PUBLICATION_READY")
        pre = {f: open(os.path.join(root, f), "rb").read() for f in (SPECS_REL,)}
        rp = PT.mod.run("specs", "reconcile", root=root, home=home, clone_url_override=bare)
        check("16/reconcile_preview_ready", rp["status"] == "RECONCILE_READY", (rp["status"], rp["decision"]))
        check("16/reconcile_preview_writes_nothing", not os.listdir(pev.publications_dir(root)))
        pv = rp["receipt"]["preview"]
        check("16/reconcile_evidence_is_remote_head_commit",
              pv["remote_commit"] == PT.bare_head_sha(bare, BRANCH) == r["commit_hash"]
              and pv["evidence_source"] == "RECONCILED_FROM_REMOTE" and pv["version"] == "0.1", pv)
        rw = PT.mod.run("specs", "reconcile-write", root=root, home=home, clone_url_override=bare)
        check("16/reconcile_write_ok", rw["status"] == "RECONCILED", (rw["status"], rw["decision"]))
        check("16/reconcile_makes_lifecycle_published", state(root)["publication_status"] == "Published")
        check("16/reconcile_never_touches_specs_or_remote",
              all(open(os.path.join(root, f), "rb").read() == b for f, b in pre.items())
              and PT.bare_head_sha(bare, BRANCH) == r["commit_hash"])
        rw2 = PT.mod.run("specs", "reconcile-write", root=root, home=home, clone_url_override=bare)
        check("16/reconcile_idempotent", rw2["status"] == "RECONCILED"
              and len(os.listdir(pev.publications_dir(root))) == 1, rw2["status"])
    finally:
        T._cleanup(root); PT.rm(home); PT.rm(tmp)
    # (c) reconcile refuses when the remote does NOT hold the approved bytes
    root = mk_project()
    home = tempfile.mkdtemp(prefix="pubstate-home-"); tmp = tempfile.mkdtemp(prefix="pubstate-remotes-")
    try:
        bare = PT.mk_bare_remote(tmp, PT.WORKSPACE, PT.REPOSITORY, BRANCH, files={SPECS_REL: "# different\n"})
        rr = PT.mod.run("specs", "reconcile-write", root=root, home=home, clone_url_override=bare)
        check("16/reconcile_refused_when_remote_differs",
              rr["status"] == "BLOCKED" and rr["decision"].code == "PMO-PUBLISH-017", (rr["status"], rr["decision"]))
        check("16/no_receipt_created_on_refusal", not os.path.isdir(pev.publications_dir(root))
              or not os.listdir(pev.publications_dir(root)))
    finally:
        T._cleanup(root); PT.rm(home); PT.rm(tmp)


def test_17_legacy_publisher_behaviour_intact():
    r = subprocess.run([sys.executable, os.path.join(HERE, "test_artifact_publisher.py")],
                       capture_output=True, text=True)
    check("15/legacy_publisher_suite_green", r.returncode == 0, r.stdout[-300:])
    r = subprocess.run([sys.executable, os.path.join(REPO, ".claude", "lib", "test_pmo_lifecycle_core.py")],
                       capture_output=True, text=True)
    check("15/lifecycle_suite_green", r.returncode == 0, r.stdout[-300:])


def main():
    for fn in (
        test_1_unpublished_is_publication_ready,
        test_2_3_valid_receipt_is_published_and_publish_not_suggested,
        test_4_to_8_mismatched_or_unverified_receipts,
        test_9_10_stale_receipt_and_new_version,
        test_11_approved_baseline_protection_intact,
        test_13_14_15_version_extraction_and_commit_message,
        test_16_lifecycle_after_real_publication_and_reconciliation,
        test_17_legacy_publisher_behaviour_intact,
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
    sys.exit(main())
