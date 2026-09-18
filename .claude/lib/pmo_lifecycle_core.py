"""PMO pmo_lifecycle_core - deterministic, READ-ONLY lifecycle-state
detection and PM-facing projection for the PMO Orchestrator control plane.

Architectural rule this module exists under
-----------------------------------------------
This module must NEVER become a second source of governance truth. Every
readiness/validity fact it reports is obtained by calling an existing,
already-authoritative validator - never re-implemented:

* ``intent_approval_core.py``            - Intent existence/status/approval
* ``qa_register_core.py``                - Q&A register readiness/blocking
* ``specs-governance-guard.py``          - Specs structural validity
  (imported the same way the project's own test suite already imports it -
  see that module's docstring: "every validator is importable and callable
  directly for regression testing")
* ``specs_approval_core.py``             - Specs approval record validity
* ``change_request_incorporation_core.py`` - CR/Feedback transaction state
* ``artifact_publish_core.py``           - repository-binding field presence

If a state this module reports would ever disagree with what the
corresponding guard would say about the exact same on-disk artifacts, that
is a bug in THIS module, never a reason to trust this module over the
guard - the guard always wins (see the framework's own standing rule from
the CR-guard INITIAL_SPECS_CREATION correction).

Hard read-only contract
--------------------------
Every function in this module:

* never calls ``write_text`` / ``os.remove`` / any mutating filesystem
  operation, and never invokes a write-capable Skill, CLI, or guard;
* never changes ``Status``, ``Spec Status``, ``Execution Authorized``, or
  any other governed field;
* never repairs, normalises, or "fixes" anything it finds;
* is a pure function of on-disk state at the moment it is called - repeated
  calls against unchanged state return identical results (byte-for-byte
  equal JSON), the property the regression suite for this module directly
  tests.

project-config is not an independent authorization source
-------------------------------------------------------------
Every readiness fact below is derived from canonical artifacts through the
functions listed above. ``.pmo/project-config.yaml`` is consulted only for
project *identity* (id/name/client, used the same way every existing guard
already uses it) and for the presence of repository *routing* fields
(never to confirm the repository is actually reachable - that remains
``repo-binding-guard.py`` / ``artifact-publish-guard.py``'s job at publish
time, which do make live checks this module deliberately never makes).

Python 3, standard library only. No third-party dependencies.
"""

from __future__ import annotations

import importlib.util as _ilu
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import intent_approval_core as iac  # noqa: E402
import qa_register_core as qac  # noqa: E402
import change_request_incorporation_core as crc  # noqa: E402
import artifact_publish_core as apc  # noqa: E402
import specs_approval_core as sac  # noqa: E402


def _load_hook_module(name, filename):
    path = _HERE.parent / "hooks" / filename
    spec = _ilu.spec_from_file_location(name, str(path))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# specs-governance-guard.py is designed for exactly this - see its own
# docstring ("This hook does NOT register itself ... every validator is
# importable and callable directly") - and the existing test suite
# (test_wm_trucking_new_lifecycle_eligibility.py) already establishes this
# precedent against the real project.
specs_guard = _load_hook_module("specs_governance_guard_for_lifecycle",
                                "specs-governance-guard.py")

_clean = iac._clean
read_text = iac.read_text


# --------------------------------------------------------------------------- #
# Lifecycle state model
# --------------------------------------------------------------------------- #

class LifecycleState:
    NEW_PROJECT = "NEW_PROJECT"
    SOURCE_BASELINE_READY = "SOURCE_BASELINE_READY"
    INTENT_REVIEW_REQUIRED = "INTENT_REVIEW_REQUIRED"
    INTENT_APPROVED = "INTENT_APPROVED"
    DECISION_REVIEW_REQUIRED = "DECISION_REVIEW_REQUIRED"
    READY_FOR_SPECS = "READY_FOR_SPECS"
    SPECS_REVIEW_REQUIRED = "SPECS_REVIEW_REQUIRED"
    BASELINE_READY_FOR_APPROVAL = "BASELINE_READY_FOR_APPROVAL"
    BASELINE_APPROVED = "BASELINE_APPROVED"
    FEEDBACK_REVIEW_REQUIRED = "FEEDBACK_REVIEW_REQUIRED"
    CR_REVIEW_REQUIRED = "CR_REVIEW_REQUIRED"
    CR_READY_FOR_INCORPORATION = "CR_READY_FOR_INCORPORATION"
    PUBLICATION_READY = "PUBLICATION_READY"
    ERROR = "ERROR"


ALL_STATES = tuple(
    v for k, v in vars(LifecycleState).items()
    if not k.startswith("_") and isinstance(v, str)
)

# The single next-action label for each state - a recommendation only; this
# module never invokes any of these (see NEXT_ACTION_DESCRIPTIONS + the
# module docstring's read-only contract).
NEXT_ACTION = {
    LifecycleState.NEW_PROJECT: "INITIALIZE_PROJECT",
    LifecycleState.SOURCE_BASELINE_READY: "GENERATE_INTENT",
    LifecycleState.INTENT_REVIEW_REQUIRED: "REVIEW_DECISIONS",
    LifecycleState.INTENT_APPROVED: "GENERATE_QA",
    LifecycleState.DECISION_REVIEW_REQUIRED: "REVIEW_DECISIONS",
    LifecycleState.READY_FOR_SPECS: "GENERATE_SPECS",
    LifecycleState.SPECS_REVIEW_REQUIRED: "REVIEW_SPECS",
    LifecycleState.BASELINE_READY_FOR_APPROVAL: "APPROVE_BASELINE",
    LifecycleState.BASELINE_APPROVED: "SHOW_STATUS",
    LifecycleState.FEEDBACK_REVIEW_REQUIRED: "PROCESS_FEEDBACK",
    LifecycleState.CR_REVIEW_REQUIRED: "REVIEW_CHANGE_REQUEST",
    LifecycleState.CR_READY_FOR_INCORPORATION: "APPROVE_CHANGE_REQUEST",
    LifecycleState.PUBLICATION_READY: "PUBLISH",
    LifecycleState.ERROR: "SHOW_STATUS",
}

NEXT_ACTION_DESCRIPTION = {
    "INITIALIZE_PROJECT": "Set up project identity, repository binding and source discovery.",
    "GENERATE_INTENT": "Generate the governed Intent from the classified source corpus.",
    "REVIEW_DECISIONS": "Review the open decisions in the Decision Inbox.",
    "GENERATE_QA": "Generate the Questions & Assumptions register from the validated Intent.",
    "GENERATE_SPECS": "Generate the initial Specs baseline.",
    "REVIEW_SPECS": "Review the generated Specs baseline before approval.",
    "APPROVE_BASELINE": "Approve the Specs baseline.",
    "SHOW_STATUS": "Review current project status.",
    "PROCESS_FEEDBACK": "Process pending client feedback.",
    "REVIEW_CHANGE_REQUEST": "Review the pending Change Request.",
    "APPROVE_CHANGE_REQUEST": "Decide on the Change Request awaiting approval.",
    "PUBLISH": "Publish the governed baseline to the project repository.",
}


# --------------------------------------------------------------------------- #
# Diagnostics container
# --------------------------------------------------------------------------- #

def _diag(**kw):
    return dict(kw)


# --------------------------------------------------------------------------- #
# Individual stage detectors - each is a thin composition of an existing
# authoritative validator. None re-implements a rule any guard already
# enforces.
# --------------------------------------------------------------------------- #

def _detect_sources(root):
    sources_dir = os.path.join(root, "docs", "pmo", "sources")
    if not os.path.isdir(sources_dir):
        return False, _diag(reason="no docs/pmo/sources/ directory")
    found = []
    for dirpath, _, filenames in os.walk(sources_dir):
        for fn in filenames:
            if fn == ".gitkeep":
                continue
            found.append(os.path.relpath(os.path.join(dirpath, fn), sources_dir))
    return bool(found), _diag(source_files=len(found))


def _detect_intent(root):
    """(stage, diag) where stage in {"absent", "draft", "validated"}."""
    intent_path = os.path.join(root, *iac.INTENT_POSIX.split("/"))
    text = read_text(intent_path)
    if text is None:
        return "absent", _diag(reason="docs/pmo/intent/intent.md not found")
    meta = iac.parse_doc_control(text)
    status = iac._norm_status(meta.get("status"))
    open_records = iac.parse_open_records(text)
    if status != "VALIDATED":
        return "draft", _diag(
            status=status, open_items=len(open_records),
            reason="Intent Status is '{}', not VALIDATED".format(status),
        )
    approval_check = iac.validate_pm_approval(None, "VALIDATED", meta, root)
    if approval_check is not None:
        return "draft", _diag(
            status=status,
            reason="Intent VALIDATED but approval record invalid: {}".format(
                approval_check.message),
            guard_code=approval_check.code,
        )
    return "validated", _diag(
        status=status, intent_version=_clean(meta.get("intent version")))


def _detect_qa(root):
    """(stage, diag) where stage in {"absent", "invalid", "blocking",
    "ready"}."""
    result = qac.validate_new_path_readiness(root)
    if result is None:
        return "ready", _diag()
    kind, message = result
    if kind == "INTENT_NOT_READY":
        # Should not normally be reached (Intent already checked separately)
        # but stay defensive/read-only - never assume.
        return "absent", _diag(reason=message)
    if kind == "QA_REGISTER_NOT_READY":
        text = read_text(qac.qa_abspath(root))
        stage = "invalid" if text is not None else "absent"
        return stage, _diag(reason=message)
    if kind == "QA_BLOCKING_ITEM_OPEN":
        return "blocking", _diag(reason=message)
    return "invalid", _diag(reason=message)  # pragma: no cover - defensive


def _detect_specs(root):
    """(stage, diag) where stage in {"absent", "invalid", "clean",
    "approved"}."""
    specs_path = os.path.join(root, "docs", "pmo", "specs", "specs.md")
    text = read_text(specs_path)
    if text is None:
        return "absent", _diag(reason="docs/pmo/specs/specs.md not found")
    d = specs_guard.full_spec_validation(root, spec_text=text)
    if d is not None:
        return "invalid", _diag(reason=d.message, guard_code=d.code)
    meta = sac.parse_spec_doc_control(text)
    exec_auth = (meta.get("execution_authorized") or "").strip().lower()
    approval_data, approval_err = sac.load_specs_approval(root)
    match_err = sac.validate_specs_approval_matches(
        root, spec_version=meta.get("spec_version"))
    if exec_auth == "true" and approval_data is not None and approval_err is None \
            and match_err is None:
        return "approved", _diag(
            spec_version=meta.get("spec_version"),
            approved_by=_clean(approval_data.get("approved_by")),
            approved_at=_clean(approval_data.get("approved_at")),
        )
    return "clean", _diag(spec_version=meta.get("spec_version"))


def _detect_feedback(root):
    return crc.feedback_marker_is_open(root)


def _list_cr_ids(root):
    cr_dir = os.path.join(root, "docs", "pmo", "cr")
    if not os.path.isdir(cr_dir):
        return []
    ids = []
    for fn in os.listdir(cr_dir):
        m = re.match(r"^(CR-\d+)\.md$", fn)
        if m:
            ids.append(m.group(1))
    return sorted(ids)


def _detect_crs(root):
    """(needs_review, ready_for_incorporation, diag) - a read-only scan of
    docs/pmo/cr/CR-*.md via the existing crc.read_cr_fields reader; never
    re-parses CR field semantics itself."""
    review_statuses = {"DRAFT", "PM_REVIEW", "PENDING_CLIENT_DECISION"}
    review_ids, approved_ids = [], []
    for cr_id in _list_cr_ids(root):
        fields = crc.read_cr_fields(root, cr_id)
        if not fields:
            continue
        status = _clean(fields.get("Status")).upper()
        if status in review_statuses:
            review_ids.append(cr_id)
        elif status == "APPROVED":
            approved_ids.append(cr_id)
    return review_ids, approved_ids, _diag(
        total_cr_files=len(_list_cr_ids(root)))


def _detect_publication_eligibility(root):
    cfg = iac.load_project_config(root) or {}
    fields, decision = apc.extract_repo_fields(cfg)
    if decision is not None:
        return False, _diag(reason=decision.message, guard_code=decision.code)
    return True, _diag(provider=fields["provider"], repository=fields["repository"])


def _detect_transaction_anomalies(root):
    """Any OPEN-marker-shaped file that fails to parse cleanly, or whose
    project_id mismatches, is reported as a diagnostic - never silently
    ignored, never auto-repaired."""
    problems = []
    cr_state, cr_data, cr_err = crc.cr_marker_status(root)
    if cr_state in ("INVALID", "WRONG_PROJECT"):
        problems.append(_diag(marker="change-request-transaction.json",
                              state=cr_state, reason=cr_err))
    spec_state, spec_data, spec_err = sac.marker_status(root)
    if spec_state in ("INVALID", "WRONG_PROJECT"):
        problems.append(_diag(marker="specs-approval-transaction.json",
                              state=spec_state, reason=spec_err))
    return problems


# --------------------------------------------------------------------------- #
# Main entrypoint
# --------------------------------------------------------------------------- #

def get_project_state(root):
    """The single deterministic entrypoint. Returns a plain dict - safe to
    JSON-serialise - containing both the PM-safe projection fields (top
    level) and a nested "_engineering" diagnostics block. Never raises;
    any unexpected internal failure is caught and reported as lifecycle
    state ERROR with the exception recorded only under "_engineering"."""
    try:
        return _get_project_state_unsafe(root)
    except Exception as exc:  # pragma: no cover - fail closed, never crash
        return _build_result(
            root, LifecycleState.ERROR,
            health="Error",
            needs_pm_attention=True,
            engineering=_diag(
                internal_error=str(exc),
                exception_type=type(exc).__name__,
            ),
        )


def _build_result(root, state, health, needs_pm_attention, engineering,
                  decision_count=0, blocking_decision_count=0,
                  deferred_decision_count=0, requirement_count=None,
                  specs_status=None, baseline_status=None,
                  publication_status=None, project_name=None, project_id=None):
    cfg = iac.load_project_config(root) or {}
    if project_id is None:
        project_id = _clean((cfg.get("project") or {}).get("id")) or None
    if project_name is None:
        project_name = _clean((cfg.get("project") or {}).get("name")) or None
    action = NEXT_ACTION.get(state, "SHOW_STATUS")
    return {
        "project": project_name,
        "project_id": project_id,
        "lifecycle_state": state,
        "health": health,
        "next_action": action,
        "next_action_description": NEXT_ACTION_DESCRIPTION.get(action, ""),
        "needs_pm_attention": bool(needs_pm_attention),
        "decision_count": decision_count,
        "blocking_decision_count": blocking_decision_count,
        "deferred_decision_count": deferred_decision_count,
        "requirement_count": requirement_count,
        "specs_status": specs_status,
        "baseline_status": baseline_status,
        "publication_status": publication_status,
        "_engineering": engineering or {},
    }


def _get_project_state_unsafe(root):
    anomalies = _detect_transaction_anomalies(root)
    if anomalies:
        return _build_result(
            root, LifecycleState.ERROR, health="Recovery Required",
            needs_pm_attention=True,
            engineering=_diag(transaction_anomalies=anomalies),
        )

    cfg = iac.load_project_config(root)
    if not isinstance(cfg, dict) or not (cfg.get("project") or {}).get("id"):
        return _build_result(
            root, LifecycleState.NEW_PROJECT, health="Not Started",
            needs_pm_attention=True,
            engineering=_diag(reason="no usable .pmo/project-config.yaml project identity"),
        )

    has_sources, src_diag = _detect_sources(root)
    intent_stage, intent_diag = _detect_intent(root)

    if intent_stage == "absent":
        if not has_sources:
            return _build_result(
                root, LifecycleState.NEW_PROJECT, health="Not Started",
                needs_pm_attention=True, engineering=_diag(sources=src_diag),
            )
        return _build_result(
            root, LifecycleState.SOURCE_BASELINE_READY, health="Ready",
            needs_pm_attention=False, engineering=_diag(sources=src_diag),
        )

    if intent_stage == "draft":
        return _build_result(
            root, LifecycleState.INTENT_REVIEW_REQUIRED,
            health="Needs PM Review", needs_pm_attention=True,
            engineering=_diag(intent=intent_diag),
        )

    # intent_stage == "validated" from here on.
    qa_stage, qa_diag = _detect_qa(root)

    if qa_stage in ("absent", "invalid"):
        if qa_stage == "absent":
            return _build_result(
                root, LifecycleState.INTENT_APPROVED, health="Ready",
                needs_pm_attention=False,
                engineering=_diag(intent=intent_diag, qa=qa_diag),
            )
        return _build_result(
            root, LifecycleState.ERROR, health="Needs Engineering Review",
            needs_pm_attention=True,
            engineering=_diag(intent=intent_diag, qa=qa_diag),
        )

    decisions = qac.qa_records(root)
    blocking = qac.blocking_open_records(decisions)
    deferred = [d for d in decisions
               if _clean(d.get("status")).upper() in ("DEFERRED", "NON_BLOCKING", "OPEN")
               and d not in blocking]

    if qa_stage == "blocking":
        return _build_result(
            root, LifecycleState.DECISION_REVIEW_REQUIRED,
            health="Needs PM Decisions", needs_pm_attention=True,
            decision_count=len(decisions), blocking_decision_count=len(blocking),
            deferred_decision_count=len(deferred),
            engineering=_diag(intent=intent_diag, qa=qa_diag),
        )

    # qa_stage == "ready" from here.
    specs_stage, specs_diag = _detect_specs(root)

    if specs_stage == "absent":
        return _build_result(
            root, LifecycleState.READY_FOR_SPECS, health="Ready",
            needs_pm_attention=False,
            decision_count=len(decisions), blocking_decision_count=0,
            deferred_decision_count=len(deferred),
            engineering=_diag(intent=intent_diag, qa=qa_diag),
        )

    if specs_stage == "invalid":
        return _build_result(
            root, LifecycleState.SPECS_REVIEW_REQUIRED,
            health="Needs Review", needs_pm_attention=True,
            decision_count=len(decisions), blocking_decision_count=0,
            deferred_decision_count=len(deferred),
            requirement_count=_fr_count(root),
            specs_status="PROVISIONAL", baseline_status="Not Approved",
            engineering=_diag(intent=intent_diag, qa=qa_diag, specs=specs_diag),
        )

    fr_count = _fr_count(root)

    if specs_stage == "clean":
        return _build_result(
            root, LifecycleState.BASELINE_READY_FOR_APPROVAL,
            health="Ready for PM Review", needs_pm_attention=True,
            decision_count=len(decisions), blocking_decision_count=0,
            deferred_decision_count=len(deferred),
            requirement_count=fr_count,
            specs_status="PROVISIONAL", baseline_status="Awaiting Approval",
            engineering=_diag(intent=intent_diag, qa=qa_diag, specs=specs_diag),
        )

    # specs_stage == "approved" from here - baseline exists.
    feedback_open = _detect_feedback(root)
    review_crs, approved_crs, cr_diag = _detect_crs(root)

    if feedback_open:
        return _build_result(
            root, LifecycleState.FEEDBACK_REVIEW_REQUIRED,
            health="Needs PM Review", needs_pm_attention=True,
            decision_count=len(decisions), deferred_decision_count=len(deferred),
            requirement_count=fr_count, specs_status="PROVISIONAL",
            baseline_status="Approved",
            engineering=_diag(intent=intent_diag, qa=qa_diag, specs=specs_diag),
        )

    if review_crs:
        return _build_result(
            root, LifecycleState.CR_REVIEW_REQUIRED,
            health="Needs PM Review", needs_pm_attention=True,
            decision_count=len(decisions), deferred_decision_count=len(deferred),
            requirement_count=fr_count, specs_status="PROVISIONAL",
            baseline_status="Approved",
            engineering=_diag(intent=intent_diag, qa=qa_diag, specs=specs_diag,
                              crs=cr_diag, review_crs=review_crs),
        )

    if approved_crs:
        return _build_result(
            root, LifecycleState.CR_READY_FOR_INCORPORATION,
            health="Ready", needs_pm_attention=True,
            decision_count=len(decisions), deferred_decision_count=len(deferred),
            requirement_count=fr_count, specs_status="PROVISIONAL",
            baseline_status="Approved",
            engineering=_diag(intent=intent_diag, qa=qa_diag, specs=specs_diag,
                              crs=cr_diag, approved_crs=approved_crs),
        )

    publishable, pub_diag = _detect_publication_eligibility(root)
    return _build_result(
        root, LifecycleState.PUBLICATION_READY if publishable else LifecycleState.BASELINE_APPROVED,
        health="Ready" if publishable else "Baseline Approved",
        needs_pm_attention=False,
        decision_count=len(decisions), deferred_decision_count=len(deferred),
        requirement_count=fr_count, specs_status="PROVISIONAL",
        baseline_status="Approved",
        publication_status="Eligible" if publishable else "Not Configured",
        engineering=_diag(intent=intent_diag, qa=qa_diag, specs=specs_diag,
                          publication=pub_diag),
    )


def _fr_count(root):
    specs_path = os.path.join(root, "docs", "pmo", "specs", "specs.md")
    text = read_text(specs_path)
    if text is None:
        return None
    return len(re.findall(r"(?m)^###\s+FR-\d+", text))


# --------------------------------------------------------------------------- #
# PM Mode / Engineering Mode projections
# --------------------------------------------------------------------------- #

_STAGE_LABEL = {
    LifecycleState.NEW_PROJECT: "Not Started",
    LifecycleState.SOURCE_BASELINE_READY: "Sources Ready",
    LifecycleState.INTENT_REVIEW_REQUIRED: "Intent Review",
    LifecycleState.INTENT_APPROVED: "Intent Approved",
    LifecycleState.DECISION_REVIEW_REQUIRED: "Decision Review",
    LifecycleState.READY_FOR_SPECS: "Ready For Specs",
    LifecycleState.SPECS_REVIEW_REQUIRED: "Specs Review",
    LifecycleState.BASELINE_READY_FOR_APPROVAL: "Specs Review",
    LifecycleState.BASELINE_APPROVED: "Baseline Approved",
    LifecycleState.FEEDBACK_REVIEW_REQUIRED: "Feedback Review",
    LifecycleState.CR_REVIEW_REQUIRED: "Change Request Review",
    LifecycleState.CR_READY_FOR_INCORPORATION: "Change Request Approval",
    LifecycleState.PUBLICATION_READY: "Ready To Publish",
    LifecycleState.ERROR: "Needs Attention",
}

# Fields a PM Mode render is allowed to show. Anything not listed here -
# guard codes, hook/module names, transaction JSON, Git hashes, file paths -
# lives only under "_engineering" and is never interpolated into this view.
_PM_SAFE_TOP_LEVEL_FIELDS = (
    "project", "lifecycle_state", "health", "requirement_count",
    "decision_count", "blocking_decision_count", "deferred_decision_count",
    "needs_pm_attention", "next_action_description",
)


def pm_status_view(state):
    """Deterministic PM-facing text rendering. Contains no guard codes, hook
    names, test-suite counts, transaction JSON, Git hashes, or framework
    filenames - see _PM_SAFE_TOP_LEVEL_FIELDS."""
    lines = [
        "Project:", state.get("project") or "(unnamed project)", "",
        "Stage:", _STAGE_LABEL.get(state["lifecycle_state"], state["lifecycle_state"]), "",
        "Status:", state["health"], "",
    ]
    if state.get("requirement_count") is not None:
        lines += ["Requirements:", str(state["requirement_count"]), ""]
    if state.get("decision_count"):
        lines += ["Pending Decisions:", str(state["decision_count"]), ""]
    needs_attention = state.get("blocking_decision_count", 0)
    lines += ["Needs Attention:", str(needs_attention), ""]
    lines += ["Next Action:", state.get("next_action_description") or "None", ""]
    return "\n".join(lines).rstrip()


def engineering_status_view(state):
    """PM view PLUS the full diagnostics block. Never changes lifecycle
    rules - purely additive presentation of the same `state` dict."""
    pm_text = pm_status_view(state)
    eng = state.get("_engineering") or {}
    diag_lines = ["", "--- Engineering Diagnostics ---",
                 "lifecycle_state: {}".format(state["lifecycle_state"]),
                 "next_action: {}".format(state.get("next_action"))]
    for k, v in eng.items():
        diag_lines.append("{}: {}".format(k, v))
    return pm_text + "\n" + "\n".join(diag_lines)


# --------------------------------------------------------------------------- #
# Error translation (PMO-* guard code -> PM-safe message + recommended
# action). Engineering Mode always gets the raw code/message unchanged.
# --------------------------------------------------------------------------- #

_ERROR_TRANSLATIONS = (
    (re.compile(r"^PMO-CR-GUARD-013$"),
     "Specs is already an approved baseline and can't be changed directly.",
     "This change needs to go through a Change Request."),
    (re.compile(r"^PMO-SPEC-023$"),
     "This project has unresolved decisions that must be answered before a "
     "baseline can be generated.",
     "Review Decisions"),
    (re.compile(r"^PMO-QA-008$"),
     "A recent decision update is missing required detail.",
     "Flagged for engineering review - no changes were made."),
    (re.compile(r"^PMO-CR-GUARD-018$"),
     "This change can't be applied yet - it hasn't been approved.",
     "Review Change Request"),
    (re.compile(r"^PMO-SPEC-APPROVAL-007$"),
     "This Specs baseline is already approved.",
     "Review Status"),
    (re.compile(r"^PMO-SPEC-APPROVAL-009$"),
     "This Specs baseline already has a recorded approval.",
     "Review Status"),
    (re.compile(r"^PMO-SPEC-APPROVAL-004$"),
     "Specs isn't ready for approval yet - it still needs some fixes.",
     "Review Specs"),
)


def translate_error_for_pm(code, message):
    """(pm_message, recommended_action). Falls back to a generic, still
    non-technical message + engineering-review action for any code not in
    the table above - PM Mode NEVER surfaces a raw code with no
    translation."""
    for pattern, pm_message, action in _ERROR_TRANSLATIONS:
        if pattern.match(code or ""):
            return pm_message, action
    return (
        "Something prevented this operation from completing safely.",
        "This has been flagged for engineering review - no changes were made.",
    )


# --------------------------------------------------------------------------- #
# Decision Inbox - read-only aggregation of canonical decision records.
# Never a second datastore: every item carries its canonical ID and is
# recomputed fresh from Intent / Q&A on every call.
# --------------------------------------------------------------------------- #

_TERMINAL_DISPOSITION_RE = re.compile(
    # No trailing \b: these framework status tokens are underscore-extended
    # (RESOLVED_WITH_PENDING_CONFIGURATION, NON_BLOCKING_FUTURE_DECISION) -
    # a right-side \b would never match between two word characters.
    r"\b(?:RESOLVED|CONFIRMED|NON_BLOCKING)", re.IGNORECASE)


def _intent_open_id_is_dispositioned(intent_text, open_id):
    """True when the Intent's own Open Questions table row for `open_id`
    already carries a terminal disposition (RESOLVED / RESOLVED_WITH_* /
    CONFIRMED / NON_BLOCKING_*) in its own Reconciliation-Status text - the
    same free-text column a human reads today. Purely a presentation
    filter (never a governance decision): an Intent OPEN-* item already
    carried forward into - and now represented by - a Q&A record is a
    duplicate entry in the Decision Inbox otherwise, which the Decision
    Inbox design explicitly must avoid ("the PM should not need to inspect
    Intent Open Questions ... as separate concepts")."""
    block = iac.open_questions_block(intent_text)
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and re.match(
                r"^\|\s*" + re.escape(open_id) + r"\s*\|", stripped):
            return bool(_TERMINAL_DISPOSITION_RE.search(stripped))
    return False


def build_decision_inbox(root):
    """[decision, ...] - each item maps back to exactly one canonical
    Intent OPEN-* record or Q&A QST-*/ASM-* record. Includes every
    non-terminal item (OPEN, DEFERRED, NON_BLOCKING); RESOLVED/CONFIRMED/
    REJECTED items are excluded - they are no longer decisions pending
    anything. An Intent OPEN-* item already dispositioned in the Intent's
    own Reconciliation Status text is excluded here too, whether or not it
    was carried forward into a Q&A record - this is a presentation filter
    only, never a re-interpretation of the Intent's own governed content."""
    items = []

    intent_text = read_text(os.path.join(root, *iac.INTENT_POSIX.split("/")))
    if intent_text is not None:
        for rec in iac.parse_open_records(intent_text):
            if _intent_open_id_is_dispositioned(intent_text, rec["id"]):
                continue
            items.append({
                "id": rec["id"],
                "source": "Intent",
                "question": rec.get("question"),
                "owner": rec.get("owner"),
                "blocking": rec.get("blocking"),
                "status": "OPEN",
                "affected_stage": rec.get("stage"),
            })

    for rec in qac.qa_records(root):
        status = _clean(rec.get("status")).upper()
        if status in ("RESOLVED", "CONFIRMED", "REJECTED"):
            continue
        items.append({
            "id": rec["id"],
            "source": "Q&A",
            "question": rec.get("statement"),
            "owner": rec.get("owner"),
            "blocking": rec.get("blocking"),
            "status": status,
            "why_it_matters": rec.get("why"),
            "affected_module": rec.get("specs_impact"),
            "current_resolution": rec.get("resolution") or None,
        })
    return items


def render_decision_inbox_pm(items):
    """PM-facing text rendering of `build_decision_inbox`'s output - no
    canonical ID is ever hidden (auditability), but no guard/hook/test
    vocabulary appears."""
    if not items:
        return "No decisions currently require attention."
    lines = ["DECISIONS REQUIRING ATTENTION", ""]
    for i, item in enumerate(items, 1):
        status = item["status"]
        if status == "OPEN" and _clean(item.get("blocking")).upper() == "YES":
            status_label = "Client confirmation pending (blocking)"
        elif status == "DEFERRED":
            status_label = "Configuration pending"
        elif status == "NON_BLOCKING":
            status_label = "Future-phase decision"
        else:
            status_label = "Client confirmation pending"
        lines.append("{}. {}".format(i, item.get("question") or item["id"]))
        lines.append("   Canonical ID: {}".format(item["id"]))
        if item.get("affected_module"):
            lines.append("   Impact: {}".format(item["affected_module"]))
        lines.append("   Status: {}".format(status_label))
        lines.append("")
    return "\n".join(lines).rstrip()
