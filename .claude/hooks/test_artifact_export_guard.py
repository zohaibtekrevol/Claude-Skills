#!/usr/bin/env python3
"""Regression tests for .claude/hooks/artifact-export-guard.py.

Stdlib only. Run: python3 .claude/hooks/test_artifact_export_guard.py
Exit 0 = all pass, 1 = at least one failure.

Covers scenarios A-X from the hook specification plus a few process()-level
and unit checks. Uses temporary fixtures only - no real Smart Basket DOCX,
no real export-manifest.json, no modification of any project file.
"""

import importlib.util
import io
import json
import os
import shutil
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "artifact-export-guard.py")
_spec = importlib.util.spec_from_file_location("artifact_export_guard", HOOK)
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

CONFIG_YAML = (
    'project:\n'
    '  id: "SMART-BASKET"\n'
    '  name: "Smart Basket"\n'
    '  client: "Smart Basket / eBasket KSA"\n'
    'artifacts:\n'
    '  intent:\n'
    '    latest_version: "1.0"\n'
    '    status: "VALIDATED"\n'
    '  scope:\n'
    '    latest_version: "0.1"\n'
    '    approved_version: null\n'
    '    status: "DRAFT_CLIENT_REVIEW"\n'
    '  specifications:\n'
    '    status: "NOT_CREATED"\n'
    'workflow:\n'
    '  current_stage: "SCOPE_READY_FOR_CLIENT_REVIEW"\n'
    '  intent:\n'
    '    approved: true\n'
    '  scope:\n'
    '    required: true\n'
    '    approved: false\n'
    '    pm_review: "COMPLETE"\n'
    '    client_review: "PENDING"\n'
)

SCOPE_MD = (
    "# Scope of Work: Smart Basket\n\n"
    "## 1. Document Control\n\n"
    "| Field | Value |\n"
    "|---|---|\n"
    "| Project | Smart Basket |\n"
    "| Project ID | SMART-BASKET |\n"
    "| Client | Smart Basket / eBasket KSA |\n"
    "| PM | Muneeb |\n"
    "| Scope Version | 0.1 |\n"
    "| Status | DRAFT_CLIENT_REVIEW |\n"
    "| Intent Version | 1.0 |\n"
    "| Date | 2026-09-11 |\n\n"
    "## 7. Detailed Scope of Work\n\n"
    "| ID | Requirement |\n"
    "|---|---|\n"
    "| SCP-REQ-001 | Customer application |\n"
    "| SCP-REQ-002 | Rider application |\n"
    "| SCP-REQ-003 | Admin panel |\n\n"
    "## 20. Open Questions\n\n"
    "| ID | Blocking | Question | Why | Owner | Required Before | Source |\n"
    "|---|---|---|---|---|---|---|\n"
    "| OPEN-002 | YES | Which payment providers? | effort | PM to Client "
    "| SCOPE_BASELINE | contract TBD |\n\n"
    "## 9. Work Breakdown Structure\n\n"
    "| WBS | Deliverable |\n"
    "|---|---|\n"
    "| WBS-1 | Customer application |\n"
)

SOURCE_REL = "docs/pmo/scope/scope-v0.1.md"
EXPORT_REL = "docs/pmo/exports/scope/Smart-Basket-Scope-of-Work-v0.1.docx"
MANIFEST_REL = "docs/pmo/exports/export-manifest.json"

_SRC_IDS = "SCP-REQ-001 SCP-REQ-002 SCP-REQ-003 OPEN-002 WBS-1"


def mkroot(config=CONFIG_YAML, scope_md=SCOPE_MD, with_scope=True):
    tmp = tempfile.mkdtemp(prefix="export-guard-test-")
    os.makedirs(os.path.join(tmp, ".pmo"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "docs", "pmo", "scope"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "docs", "pmo", "exports", "scope"), exist_ok=True)
    if config is not None:
        _w(os.path.join(tmp, ".pmo", "project-config.yaml"), config)
    if with_scope and scope_md is not None:
        _w(os.path.join(tmp, SOURCE_REL), scope_md)
    return tmp


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _docx_bytes(paragraphs):
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
          'content-types">'
          '<Default Extension="rels" ContentType="application/'
          'vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/'
          'vnd.openxmlformats-officedocument.wordprocessingml.document.main'
          '+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Id="rId1" Type="http://'
            'schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="word/document.xml"/></Relationships>')

    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    body = "".join(
        '<w:p><w:r><w:t xml:space="preserve">{}</w:t></w:r></w:p>'.format(esc(p))
        for p in paragraphs
    )
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/'
           'wordprocessingml/2006/main"><w:body>{}</w:body>'
           '</w:document>'.format(body))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def write_docx(path, paragraphs):
    _w_bytes(path, _docx_bytes(paragraphs))


def _w_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def manifest_obj(root, **overrides):
    src_abs = os.path.join(root, SOURCE_REL)
    rec = {
        "project_id": "SMART-BASKET",
        "source_artifact": SOURCE_REL,
        "source_version": "0.1",
        "source_status": "DRAFT_CLIENT_REVIEW",
        "source_hash": "sha256:" + (mod.calculate_sha256(src_abs) or "0" * 64),
        "artifact_type": "SCOPE",
        "audience": "CLIENT",
        "export_format": "DOCX",
        "export_path": EXPORT_REL,
        "generated_at": "2026-09-11T00:00:00Z",
        "generated_by": "PMO / Muneeb",
        "substantive_content_changed": False,
    }
    rec.update(overrides)
    return {"schema_version": "1.0", "exports": [rec]}


def rm(root):
    shutil.rmtree(root, ignore_errors=True)


# --------------------------------------------------------------------------- #
# unit checks
# --------------------------------------------------------------------------- #

def test_units():
    check("unit/detect_artifact_type",
          mod.detect_artifact_type("docs/pmo/scope/scope-v0.1.md") == "SCOPE"
          and mod.detect_artifact_type("docs/pmo/intent/intent.md") == "INTENT"
          and mod.detect_artifact_type("docs/pmo/cr/cr-001.md") == "CHANGE_REQUEST"
          and mod.detect_artifact_type("README.md") is None)
    check("unit/export_version_from_path",
          mod.export_version_from_path(
              "Smart-Basket-Scope-of-Work-v0.1.docx") == "0.1"
          and mod.export_version_from_path("x.docx") is None)
    check("unit/governed_identifiers",
          mod._flatten_ids(mod.extract_governed_identifiers(SCOPE_MD)) ==
          {"SCP-REQ-001", "SCP-REQ-002", "SCP-REQ-003", "OPEN-002", "WBS-1"})
    check("unit/sha256_roundtrip",
          isinstance(mod.calculate_sha256(HOOK), str)
          and len(mod.calculate_sha256(HOOK)) == 64)


# --------------------------------------------------------------------------- #
# A - X
# --------------------------------------------------------------------------- #

def test_A_valid_client_review_source():
    root = mkroot()
    try:
        d = mod.pre_export_check(SOURCE_REL, EXPORT_REL, "CLIENT", root)
        check("A/valid_Scope_v0.1_client_review_source__ALLOW", d is None,
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_B_missing_source():
    root = mkroot(with_scope=False)
    try:
        d = mod.pre_export_check(SOURCE_REL, EXPORT_REL, "CLIENT", root)
        check("B/missing_source__DENY_001", code(d) == "PMO-EXPORT-001", code(d))
    finally:
        rm(root)


def test_C_pm_review_not_complete():
    cfg = CONFIG_YAML.replace('pm_review: "COMPLETE"', 'pm_review: "PENDING"')
    root = mkroot(config=cfg)
    try:
        d = mod.pre_export_check(SOURCE_REL, EXPORT_REL, "CLIENT", root)
        check("C/pm_review_not_COMPLETE__DENY_002",
              code(d) == "PMO-EXPORT-002" and "pm_review" in msg(d),
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_D_version_mismatch():
    root = mkroot()
    try:
        bad_export = "docs/pmo/exports/scope/Smart-Basket-Scope-of-Work-v0.2.docx"
        d = mod.pre_export_check(SOURCE_REL, bad_export, "CLIENT", root)
        check("D/v0.1_source_requested_as_v0.2_export__DENY_003",
              code(d) == "PMO-EXPORT-003", "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_E_wrong_project_id():
    wrong = SCOPE_MD.replace("| Project ID | SMART-BASKET |",
                             "| Project ID | WRONG-CO |")
    root = mkroot(scope_md=wrong)
    try:
        d = mod.pre_export_check(SOURCE_REL, EXPORT_REL, "CLIENT", root)
        check("E/wrong_Project_ID__DENY_004", code(d) == "PMO-EXPORT-004",
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_F_source_hash_changes_during_export():
    root = mkroot()
    try:
        src = os.path.join(root, SOURCE_REL)
        pre = mod.capture_source_state(src)
        with open(src, "a", encoding="utf-8") as fh:
            fh.write("\n<!-- exporter reformatted this -->\n")
        d = mod.validate_source_unchanged(pre, src)
        check("F/source_changed_during_export__DENY_005",
              code(d) == "PMO-EXPORT-005", "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_G_docx_contains_claude_hooks():
    root = mkroot()
    try:
        p = os.path.join(root, EXPORT_REL)
        write_docx(p, ["Scope of Work", "See .claude/hooks/ for details."])
        d = mod.detect_internal_content(mod.extract_docx_text(p), "CLIENT")
        check("G/DOCX_contains_.claude_hooks__DENY_006",
              code(d) == "PMO-EXPORT-006", "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_H_docx_contains_hook_filename():
    root = mkroot()
    try:
        p = os.path.join(root, EXPORT_REL)
        write_docx(p, ["Governed by scope-version-guard.py at all times."])
        d = mod.detect_internal_content(mod.extract_docx_text(p), "CLIENT")
        check("H/DOCX_contains_scope-version-guard.py__DENY_006",
              code(d) == "PMO-EXPORT-006", "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_I_normal_word_scope():
    root = mkroot()
    try:
        p = os.path.join(root, EXPORT_REL)
        write_docx(p, ["This Scope of Work describes the project.",
                       "Open Question OPEN-002 remains. Version 0.1. Approval "
                       "pending. Change Request process applies."])
        d = mod.detect_internal_content(mod.extract_docx_text(p), "CLIENT")
        check("I/normal_word_Scope_in_DOCX__ALLOW", d is None,
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_J_zero_byte_output():
    root = mkroot()
    try:
        p = os.path.join(root, EXPORT_REL)
        _w_bytes(p, b"")
        d = mod.validate_docx_package(p)
        check("J/zero_byte_output__DENY_007", code(d) == "PMO-EXPORT-007",
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_K_malformed_docx_zip():
    root = mkroot()
    try:
        p = os.path.join(root, EXPORT_REL)
        _w_bytes(p, b"this is definitely not a zip package")
        d = mod.validate_docx_package(p)
        check("K/malformed_DOCX_zip__DENY_007", code(d) == "PMO-EXPORT-007",
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_L_missing_document_xml():
    root = mkroot()
    try:
        p = os.path.join(root, EXPORT_REL)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
        _w_bytes(p, buf.getvalue())
        d = mod.validate_docx_package(p)
        check("L/missing_word_document.xml__DENY_007",
              code(d) == "PMO-EXPORT-007" and "word/document.xml" in msg(d),
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_M_valid_docx_package():
    root = mkroot()
    try:
        p = os.path.join(root, EXPORT_REL)
        write_docx(p, ["Smart Basket Scope of Work", "SCP-REQ-001"])
        d = mod.validate_docx_package(p)
        check("M/valid_DOCX_OpenXML_package__PASS", d is None,
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_N_malformed_manifest_json():
    root = mkroot()
    try:
        _w(os.path.join(root, MANIFEST_REL), "{ this is : not json ]")
        d = mod.check_manifest_file(root)
        check("N/malformed_manifest_JSON__DENY_008",
              code(d) == "PMO-EXPORT-008", "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_O_manifest_hash_mismatch():
    root = mkroot()
    try:
        obj = manifest_obj(root, source_hash="sha256:" + "de" * 32)
        _w(os.path.join(root, MANIFEST_REL), json.dumps(obj))
        d = mod.check_manifest_file(root, expect_record_for=EXPORT_REL)
        check("O/manifest_source_hash_mismatch__DENY_008",
              code(d) == "PMO-EXPORT-008" and "source_hash" in msg(d),
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_P_manifest_substantive_changed_true():
    root = mkroot()
    try:
        obj = manifest_obj(root, substantive_content_changed=True)
        _w(os.path.join(root, MANIFEST_REL), json.dumps(obj))
        d = mod.check_manifest_file(root)
        check("P/manifest_substantive_content_changed_true__DENY_008",
              code(d) == "PMO-EXPORT-008"
              and "substantive_content_changed" in msg(d),
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_Q_existing_export_no_regen():
    root = mkroot()
    try:
        p = os.path.join(root, EXPORT_REL)
        write_docx(p, ["existing"])
        d = mod.detect_export_collision(EXPORT_REL, root,
                                        regeneration_authorized=False)
        check("Q/existing_export_no_regeneration__DENY_009",
              code(d) == "PMO-EXPORT-009", "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_R_authorized_same_version_regen():
    root = mkroot()
    try:
        p = os.path.join(root, EXPORT_REL)
        write_docx(p, ["existing"])
        obj = manifest_obj(root)
        d = mod.detect_export_collision(EXPORT_REL, root,
                                        regeneration_authorized=True,
                                        src_version="0.1", manifest_data=obj)
        check("R/authorized_same_version_regeneration__ALLOW", d is None,
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_S_unexpected_validation_exception():
    root = mkroot()
    try:
        orig = mod.validate_manifest

        def boom(*_a, **_k):
            raise RuntimeError("boom")

        mod.validate_manifest = boom
        try:
            payload = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": os.path.join(root, MANIFEST_REL),
                    "content": json.dumps(manifest_obj(root)),
                },
                "cwd": root,
            }
            d = mod.process(payload)
        finally:
            mod.validate_manifest = orig
        check("S/unexpected_validation_exception__DENY_010",
              code(d) == "PMO-EXPORT-010", "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_T_export_path_outside_root():
    root = mkroot()
    try:
        d1 = mod.validate_export_path("docs/pmo/scope/leaked-export.docx", root)
        d2 = mod.validate_export_path("/tmp/evil-export.docx", root)
        d3 = mod.process({
            "tool_name": "Write",
            "tool_input": {"file_path": os.path.join(root, "docs", "pmo",
                                                     "scope", "x.docx"),
                           "content": "x"},
            "cwd": root,
        })
        check("T/export_path_outside_docs_pmo_exports__DENY",
              code(d1) == "PMO-EXPORT-007" and code(d2) == "PMO-EXPORT-007"
              and code(d3) == "PMO-EXPORT-007",
              "{} / {} / {}".format(code(d1), code(d2), code(d3)))
    finally:
        rm(root)


def test_U_source_byte_identical():
    root = mkroot()
    try:
        src = os.path.join(root, SOURCE_REL)
        pre = mod.capture_source_state(src)
        # export happens here without touching the source
        d = mod.validate_source_unchanged(pre, src)
        check("U/source_file_byte_identical__PASS", d is None,
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_V_governed_identifiers_preserved():
    export_text = ("Smart Basket Scope of Work\n" + _SRC_IDS
                   + "\nEverything carried through.")
    d = mod.validate_identifier_reconciliation(SCOPE_MD, export_text, "CLIENT")
    check("V/governed_Scope_identifiers_preserved__PASS", d is None,
          "{} / {}".format(code(d), msg(d)))


def test_W_identifier_removed_without_reason():
    export_text = "Smart Basket Scope of Work\nSCP-REQ-001 SCP-REQ-002 OPEN-002 WBS-1"
    d = mod.validate_identifier_reconciliation(SCOPE_MD, export_text, "CLIENT")
    check("W/identifier_removed_without_permitted_reason__DENY_005",
          code(d) == "PMO-EXPORT-005" and "SCP-REQ-003" in msg(d),
          "{} / {}".format(code(d), msg(d)))


def test_W2_identifier_removed_with_allowance():
    export_text = "Smart Basket Scope of Work\nSCP-REQ-001 SCP-REQ-002 OPEN-002 WBS-1"
    d = mod.validate_identifier_reconciliation(
        SCOPE_MD, export_text, "CLIENT", allowed_missing={"SCP-REQ-003"})
    check("W2/identifier_removed_with_explicit_allowance__ALLOW", d is None,
          "{} / {}".format(code(d), msg(d)))


def test_X_export_does_not_modify_workflow_state():
    d_same = mod.validate_pmo_state_unchanged(CONFIG_YAML, CONFIG_YAML)
    drift = CONFIG_YAML.replace(
        'current_stage: "SCOPE_READY_FOR_CLIENT_REVIEW"',
        'current_stage: "SPECIFICATION_GENERATION"')
    d_drift = mod.validate_pmo_state_unchanged(CONFIG_YAML, drift)
    check("X/normal_export_does_not_modify_workflow_state__PASS",
          d_same is None and code(d_drift) == "PMO-EXPORT-005",
          "same={} drift={}".format(code(d_same), code(d_drift)))


# --------------------------------------------------------------------------- #
# process()-level behaviour
# --------------------------------------------------------------------------- #

def test_proc_unrelated_write_allowed():
    root = mkroot()
    try:
        d = mod.process({
            "tool_name": "Write",
            "tool_input": {"file_path": os.path.join(root, "notes.md"),
                           "content": "hello"},
            "cwd": root,
        })
        check("proc/unrelated_write__ALLOW", d is None, code(d))
    finally:
        rm(root)


def test_proc_new_export_under_root_allowed():
    root = mkroot()
    try:
        d = mod.process({
            "tool_name": "Write",
            "tool_input": {"file_path": os.path.join(root, EXPORT_REL),
                           "content": "generated later"},
            "cwd": root,
        })
        check("proc/new_export_doc_under_exports_root__ALLOW", d is None,
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_proc_overwrite_existing_export_denied():
    root = mkroot()
    try:
        p = os.path.join(root, EXPORT_REL)
        write_docx(p, ["existing"])
        d = mod.process({
            "tool_name": "Write",
            "tool_input": {"file_path": p, "content": "overwrite"},
            "cwd": root,
        })
        check("proc/overwrite_existing_export__DENY_009",
              code(d) == "PMO-EXPORT-009", "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_proc_manifest_missing_fields_denied():
    root = mkroot()
    try:
        bad = {"exports": [{"project_id": "SMART-BASKET",
                            "export_path": EXPORT_REL}]}
        d = mod.process({
            "tool_name": "Write",
            "tool_input": {"file_path": os.path.join(root, MANIFEST_REL),
                           "content": json.dumps(bad)},
            "cwd": root,
        })
        check("proc/manifest_missing_required_fields__DENY_008",
              code(d) == "PMO-EXPORT-008", "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_proc_bash_convert_outside_root_denied():
    root = mkroot()
    try:
        d = mod.process({
            "tool_name": "Bash",
            "tool_input": {"command":
                           "pandoc docs/pmo/scope/scope-v0.1.md -o "
                           "/tmp/Smart-Basket-Scope.docx"},
            "cwd": root,
        })
        check("proc/bash_convert_output_outside_exports__DENY_007",
              code(d) == "PMO-EXPORT-007", "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_proc_bash_convert_into_root_allowed():
    root = mkroot()
    try:
        d = mod.process({
            "tool_name": "Bash",
            "tool_input": {"command":
                           "pandoc docs/pmo/scope/scope-v0.1.md -o "
                           "docs/pmo/exports/scope/Smart-Basket-Scope-of-Work-"
                           "v0.1.docx"},
            "cwd": root,
        })
        check("proc/bash_convert_output_into_exports__ALLOW", d is None,
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


def test_post_export_validation_clean():
    root = mkroot()
    try:
        src = os.path.join(root, SOURCE_REL)
        pre = mod.capture_source_state(src)
        p = os.path.join(root, EXPORT_REL)
        write_docx(p, ["Smart Basket Scope of Work",
                       _SRC_IDS,
                       "Status: DRAFT FOR CLIENT REVIEW"])
        _w(os.path.join(root, MANIFEST_REL), json.dumps(manifest_obj(root)))
        d = mod.post_export_validation(SOURCE_REL, EXPORT_REL, root,
                                       audience="CLIENT", pre_state=pre)
        check("post/full_post_export_validation_clean__PASS", d is None,
              "{} / {}".format(code(d), msg(d)))
    finally:
        rm(root)


# --------------------------------------------------------------------------- #

def main():
    test_units()
    for fn in (
        test_A_valid_client_review_source, test_B_missing_source,
        test_C_pm_review_not_complete, test_D_version_mismatch,
        test_E_wrong_project_id, test_F_source_hash_changes_during_export,
        test_G_docx_contains_claude_hooks, test_H_docx_contains_hook_filename,
        test_I_normal_word_scope, test_J_zero_byte_output,
        test_K_malformed_docx_zip, test_L_missing_document_xml,
        test_M_valid_docx_package, test_N_malformed_manifest_json,
        test_O_manifest_hash_mismatch, test_P_manifest_substantive_changed_true,
        test_Q_existing_export_no_regen, test_R_authorized_same_version_regen,
        test_S_unexpected_validation_exception, test_T_export_path_outside_root,
        test_U_source_byte_identical, test_V_governed_identifiers_preserved,
        test_W_identifier_removed_without_reason,
        test_W2_identifier_removed_with_allowance,
        test_X_export_does_not_modify_workflow_state,
        test_proc_unrelated_write_allowed,
        test_proc_new_export_under_root_allowed,
        test_proc_overwrite_existing_export_denied,
        test_proc_manifest_missing_fields_denied,
        test_proc_bash_convert_outside_root_denied,
        test_proc_bash_convert_into_root_allowed,
        test_post_export_validation_clean,
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
