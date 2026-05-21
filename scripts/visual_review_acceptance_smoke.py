#!/usr/bin/env python3
"""Visual-review acceptance smoke for the per-slide rubric contract.

Focused, ``$TMPDIR``-only acceptance smoke that proves the committed
visual-review contract (``schemas/visual_review.schema.json`` +
``scripts/validate_visual_review.py`` + the synthetic example
``examples/synthetic_visual_review.json``) refuses every boundary the
contract names and accepts the legitimate static-metadata wording it
must continue to allow. Each scenario invokes the validator AS A
SUBPROCESS from ``REPO_ROOT`` with ``PYTHONDONTWRITEBYTECODE=1`` so
the CLI surface (argparse, exit codes, file IO) is exercised, not just
the in-process Python entry point that ``validate_visual_review.py
--self-test`` covers.

What the smoke proves (every scenario writes its candidate JSON under
``tempfile.TemporaryDirectory()`` so no artifact lands in the repo):

  1. The committed ``examples/synthetic_visual_review.json`` passes
     ``scripts/validate_visual_review.py --review <path>`` (full
     schema + content gates V1-V14) AND
     ``scripts/validate_artifacts.py --schema
     schemas/visual_review.schema.json <path>`` (independent stdlib
     schema-only re-validation). Two independent entry points
     agreeing on the same fixture closes the regression where one
     side drifts from the other.
  2. Per-slide coverage refusals: a review that skips a slide_index
     in ``1..deck.slide_count`` AND a review whose records carry an
     extra slide_index outside that range both fail closed.
  3. Duplicate-slide_index refusal.
  4. Summary-vs-records drift refusal.
  5. Closed-enum refusals for every closed field the contract
     touches: ``records[].status`` / ``issue_type`` / ``severity`` /
     ``recommended_action`` (V2 fires from the schema enum AND V5
     fires from the validator's runtime re-check).
  6. Non-synthetic id refusal at every ``synthetic_``-prefixed
     field: ``review_id``, ``deck.deck_id``, ``generated_by.name``.
  7. URL / URI-scheme / unsafe-path / data-URI / file-URI refusals
     (V9 + V10).
  8. Public-upload / public-hosting wording refusal (V11) across
     several propagation-verb variants (``upload``, ``share``,
     ``host``, ``publish``, ``link``).
  9. Credential-shaped wording refusal (V12) across the contract's
     compound-token denylist AND the ``sk-``-prefixed API-key regex.
  10. Raw-source / confidential wording refusal (V13).
  11. Out-of-scope tool-claim refusal (V14): screenshot, headless
      browser / Selenium / Playwright / Puppeteer, D-One ("done +
      image"), MCP ("mcp + call"), Qoder, model API
      ("model api was queried"), external service ("external
      service called"), bare ``model`` + every contract-required
      generic usage verb (``used`` / ``called`` / ``invoked`` /
      ``prompted``) AND the same usage-verb set against the
      ``called the model`` subject-after-verb shape.
  12. Negative-positive: legitimate render_model evidence wording
      (``render_model used by slide 3 has overflow``,
      ``render_model was invoked / called / prompted``) passes the
      same validator that refuses the bare ``model was used`` shape
      — the ``\\bmodel\\b`` word-boundary check excludes underscored
      compounds.
  13. ``REPO_ROOT/examples/`` and ``REPO_ROOT/scripts/`` are
      byte-identical before and after the smoke (snapshot-diff
      proves no generated artifact landed in the committed tree).

Stdlib-only. NETWORK-FREE. NO-D-ONE. NO-Qoder. NO-MCP. NO model API.
NO browser. NO screenshot. NO image generation. NO PPTX export. NO
telemetry. NOT a full prompt/report/Markdown-to-PPTX automation —
this smoke composes existing read-only validators against synthetic
fixtures and asserts the contract holds at every documented boundary.

The smoke has only a ``--self-test`` invocation surface. It exits 0
on full pass, 1 on any scenario failure, 2 on a missing flag.

Usage:
  python3 scripts/visual_review_acceptance_smoke.py --self-test
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
REVIEW_SCHEMA = REPO_ROOT / "schemas" / "visual_review.schema.json"
COMMITTED_REVIEW = REPO_ROOT / "examples" / "synthetic_visual_review.json"

# In-script baseline used by every mutating scenario. Identical in
# shape to the committed example so the mutations stay surgical and
# easy to read. Re-derived per scenario via ``copy.deepcopy``.
_BASELINE: dict = {
    "schema_version": "1",
    "review_id": "synthetic_acceptance_smoke",
    "evidence_basis": "local_artifact_metadata_only",
    "generated_by": {
        "name": "synthetic_acceptance_smoke",
        "mode": "self_test_fixture",
    },
    "deck": {
        "deck_id": "synthetic_demo_deck",
        "slide_count": 3,
    },
    "records": [
        {
            "slide_index": 1,
            "slide_layout": "cover",
            "status": "pass",
            "issue_type": "other_synthetic_probe",
            "severity": "info",
            "evidence_basis": "local_artifact_metadata_only",
            "recommended_action": "no_action",
        },
        {
            "slide_index": 2,
            "slide_layout": "kpi_dashboard",
            "status": "warn",
            "issue_type": "text_density",
            "severity": "low",
            "evidence_basis": "local_artifact_metadata_only",
            "recommended_action": "adjust_copy",
        },
        {
            "slide_index": 3,
            "slide_layout": "comparison_table",
            "status": "fail",
            "issue_type": "overflow_risk",
            "severity": "high",
            "evidence_basis": "local_artifact_metadata_only",
            "recommended_action": "adjust_layout",
        },
    ],
    "summary": {
        "pass_count": 1,
        "warn_count": 1,
        "fail_count": 1,
    },
}


@dataclass
class _Outcome:
    name: str
    ok: bool
    detail: str = ""


def _run(cmd: list[str]) -> tuple[int, str, str]:
    """Spawn ``cmd`` from REPO_ROOT with ``PYTHONDONTWRITEBYTECODE=1``
    so a ``__pycache__`` side-effect cannot dirty the repo. Returns
    ``(returncode, stdout, stderr)``."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _snapshot(root: Path) -> dict[str, bytes]:
    """Flat ``relative-path -> bytes`` map of every regular file under
    ``root``. Symlinks are skipped (a clean checkout of this repo has
    none). Used to prove no committed file is mutated by the smoke."""
    snap: dict[str, bytes] = {}
    if not root.is_dir():
        return snap
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(root)
        snap[str(rel)] = p.read_bytes()
    return snap


def _diff_keys(
    before: dict[str, bytes], after: dict[str, bytes],
) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [k for k in keys if before.get(k) != after.get(k)]


def _write_candidate(tmp: Path, payload: dict) -> Path:
    p = tmp / "review.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _validator_returncode(review_path: Path) -> tuple[int, str, str]:
    py = sys.executable
    return _run([
        py, str(SCRIPTS_DIR / "validate_visual_review.py"),
        "--review", str(review_path),
    ])


def _schema_returncode(review_path: Path) -> tuple[int, str, str]:
    py = sys.executable
    return _run([
        py, str(SCRIPTS_DIR / "validate_artifacts.py"),
        "--schema", str(REVIEW_SCHEMA),
        str(review_path),
    ])


def _baseline() -> dict:
    return copy.deepcopy(_BASELINE)


# ----------------------------------------------------------------------
# Scenario shape: each mutator returns the candidate to be written.
# A ``None`` mutator means "use the committed example bytes directly"
# (so the committed fixture is exercised as a single subprocess
# invocation, the same way trace_acceptance_smoke composes existing
# validators against an on-disk fixture).
# ----------------------------------------------------------------------

Mutator = Callable[[dict], dict]


def _scenario_refuses(
    name: str, mutate: Mutator,
) -> Callable[[Path], _Outcome]:
    """Build a scenario that MUST exit non-zero from the validator."""
    def run(tmp: Path) -> _Outcome:
        candidate = mutate(_baseline())
        path = _write_candidate(tmp, candidate)
        rc, stdout, stderr = _validator_returncode(path)
        if rc == 0:
            return _Outcome(
                name, False,
                (f"expected rc!=0; got rc=0; stdout={stdout!r}; "
                 f"stderr={stderr!r}"),
            )
        return _Outcome(name, True)
    return run


def _scenario_passes(
    name: str, mutate: Mutator,
) -> Callable[[Path], _Outcome]:
    """Build a scenario that MUST exit 0 from the validator."""
    def run(tmp: Path) -> _Outcome:
        candidate = mutate(_baseline())
        path = _write_candidate(tmp, candidate)
        rc, stdout, stderr = _validator_returncode(path)
        if rc != 0:
            return _Outcome(
                name, False,
                (f"expected rc=0; got rc={rc}; stdout={stdout!r}; "
                 f"stderr={stderr!r}"),
            )
        return _Outcome(name, True)
    return run


# ----------------------------------------------------------------------
# Mutators
# ----------------------------------------------------------------------

def _m_baseline_unchanged(d: dict) -> dict:
    return d


def _m_missing_slide_coverage(d: dict) -> dict:
    # Drop the middle record; deck.slide_count=3 still requires three
    # records covering 1..3 inclusive.
    del d["records"][1]
    d["summary"] = {"pass_count": 1, "warn_count": 0, "fail_count": 1}
    return d


def _m_extra_slide_index(d: dict) -> dict:
    # APPEND a 4th record at slide_index = 99 while keeping
    # records[0..2] covering slots 1..3 in full. The "missing"
    # branch of V6 sees nothing missing (1..3 all present), the
    # "extra" branch fires on slot 99 — so the smoke asserts an
    # extras refusal WITHOUT the missing branch masking a regression
    # on the extras-branch logic. V7 stays quiet because 99 does not
    # duplicate any existing slot, and the summary is bumped to
    # pass=2/warn=1/fail=1 so V8 stays quiet too — V6 extras is the
    # only gate that can fire.
    d["records"].append({
        "slide_index": 99,
        "slide_layout": "cover",
        "status": "pass",
        "issue_type": "other_synthetic_probe",
        "severity": "info",
        "evidence_basis": "local_artifact_metadata_only",
        "recommended_action": "no_action",
    })
    d["summary"] = {"pass_count": 2, "warn_count": 1, "fail_count": 1}
    return d


def _m_duplicate_slide_index(d: dict) -> dict:
    # records[1].slide_index re-uses slot 1.
    d["records"][1]["slide_index"] = 1
    return d


def _m_summary_drift(d: dict) -> dict:
    d["summary"]["pass_count"] = 99
    return d


def _m_unknown_status(d: dict) -> dict:
    d["records"][0]["status"] = "maybe_pass"
    return d


def _m_unknown_issue_type(d: dict) -> dict:
    d["records"][0]["issue_type"] = "made_up_category"
    return d


def _m_unknown_severity(d: dict) -> dict:
    d["records"][0]["severity"] = "critical"
    return d


def _m_unknown_action(d: dict) -> dict:
    d["records"][0]["recommended_action"] = "ask_model"
    return d


def _m_non_synthetic_review_id(d: dict) -> dict:
    d["review_id"] = "real_company_q4"
    return d


def _m_non_synthetic_deck_id(d: dict) -> dict:
    d["deck"]["deck_id"] = "real_internal_deck"
    return d


def _m_non_synthetic_generated_by_name(d: dict) -> dict:
    d["generated_by"]["name"] = "manual_authoring_team"
    return d


def _m_url(d: dict) -> dict:
    d["notes"] = "see https://example/notes for context"
    return d


def _m_data_uri(d: dict) -> dict:
    d["records"][0]["note"] = "data:image/png;base64,AAAA"
    return d


def _m_file_uri(d: dict) -> dict:
    d["records"][0]["note"] = "file:///etc/passwd"
    return d


def _m_absolute_path(d: dict) -> dict:
    d["records"][0]["note"] = "/etc/passwd should not appear here"
    return d


def _m_parent_traversal(d: dict) -> dict:
    d["records"][0]["note"] = "uses ../../secrets path"
    return d


def _m_public_upload(d: dict) -> dict:
    d["notes"] = "auto public upload after build"
    return d


def _m_public_hosting(d: dict) -> dict:
    d["notes"] = "public hosting enabled"
    return d


def _m_public_share(d: dict) -> dict:
    d["notes"] = "public sharing link will be generated"
    return d


def _m_public_publish(d: dict) -> dict:
    d["notes"] = "public publish to portal"
    return d


def _m_public_link(d: dict) -> dict:
    d["notes"] = "public link distributed to reviewers"
    return d


def _m_credential_api_key(d: dict) -> dict:
    d["notes"] = "store api_key here"
    return d


def _m_credential_secret(d: dict) -> dict:
    d["notes"] = "client secret value"
    return d


def _m_credential_token(d: dict) -> dict:
    d["notes"] = "token placeholder"
    return d


def _m_credential_sk_prefix(d: dict) -> dict:
    d["notes"] = "key is sk-abcdef0123456789xyz"
    return d


def _m_confidential(d: dict) -> dict:
    d["notes"] = "marked confidential, internal only review"
    return d


def _m_raw_source(d: dict) -> dict:
    d["notes"] = "carries raw source excerpt verbatim"
    return d


def _m_screenshot(d: dict) -> dict:
    d["notes"] = "screenshot diff was taken across slides"
    return d


def _m_headless_browser(d: dict) -> dict:
    d["notes"] = "headless browser captured the canvas"
    return d


def _m_playwright(d: dict) -> dict:
    d["notes"] = "playwright was launched per slide"
    return d


def _m_d_one(d: dict) -> dict:
    d["notes"] = "D-One image generated for cover slot"
    return d


def _m_mcp(d: dict) -> dict:
    d["notes"] = "an MCP call was invoked at review time"
    return d


def _m_qoder(d: dict) -> dict:
    d["notes"] = "qoder runtime ran the review"
    return d


def _m_model_api(d: dict) -> dict:
    d["notes"] = "model API was queried for tone grading"
    return d


def _m_external_service(d: dict) -> dict:
    d["notes"] = "external service called during review"
    return d


def _m_bare_model_used(d: dict) -> dict:
    d["notes"] = "model was used to grade contrast"
    return d


def _m_bare_model_called(d: dict) -> dict:
    d["notes"] = "called the model for a second opinion"
    return d


def _m_bare_model_invoked(d: dict) -> dict:
    d["notes"] = "model was invoked once per slide"
    return d


def _m_bare_model_prompted(d: dict) -> dict:
    d["notes"] = "the model was prompted with the source body"
    return d


def _m_safe_render_model_used(d: dict) -> dict:
    # The exact wording the V14 fix preserved: the bare-word
    # \bmodel\b check excludes "render_model" because '_' is a regex
    # word character, so this MUST pass.
    d["notes"] = "render_model used by slide 3 has overflow"
    return d


def _m_safe_render_model_invoked(d: dict) -> dict:
    d["notes"] = "render_model was invoked by export_pptx"
    return d


def _m_safe_render_model_called(d: dict) -> dict:
    d["notes"] = "the render_model was called from the export step"
    return d


def _m_safe_render_model_prompted(d: dict) -> dict:
    d["notes"] = "the render_model prompted a layout retry"
    return d


# ----------------------------------------------------------------------
# Scenario list — declared in execution order so the smoke output reads
# top-to-bottom along the contract boundaries it proves.
# ----------------------------------------------------------------------

_REFUSAL_SCENARIOS: tuple[tuple[str, Mutator], ...] = (
    ("v6-missing-slide-coverage", _m_missing_slide_coverage),
    ("v6-extra-slide-index", _m_extra_slide_index),
    ("v6-or-v7-duplicate-slide-index", _m_duplicate_slide_index),
    ("v8-summary-count-drift", _m_summary_drift),
    ("v2-or-v5-unknown-status", _m_unknown_status),
    ("v2-or-v5-unknown-issue-type", _m_unknown_issue_type),
    ("v2-or-v5-unknown-severity", _m_unknown_severity),
    ("v2-or-v5-unknown-recommended-action", _m_unknown_action),
    ("v4-non-synthetic-review-id", _m_non_synthetic_review_id),
    ("v4-non-synthetic-deck-id", _m_non_synthetic_deck_id),
    ("v4-non-synthetic-generated-by-name",
        _m_non_synthetic_generated_by_name),
    ("v9-url", _m_url),
    ("v9-data-uri", _m_data_uri),
    ("v9-file-uri", _m_file_uri),
    ("v10-absolute-path", _m_absolute_path),
    ("v10-parent-traversal", _m_parent_traversal),
    ("v11-public-upload", _m_public_upload),
    ("v11-public-hosting", _m_public_hosting),
    ("v11-public-share", _m_public_share),
    ("v11-public-publish", _m_public_publish),
    ("v11-public-link", _m_public_link),
    ("v12-api-key", _m_credential_api_key),
    ("v12-secret", _m_credential_secret),
    ("v12-token", _m_credential_token),
    ("v12-sk-prefix", _m_credential_sk_prefix),
    ("v13-confidential", _m_confidential),
    ("v13-raw-source", _m_raw_source),
    ("v14-screenshot", _m_screenshot),
    ("v14-headless-browser", _m_headless_browser),
    ("v14-playwright", _m_playwright),
    ("v14-d-one", _m_d_one),
    ("v14-mcp", _m_mcp),
    ("v14-qoder", _m_qoder),
    ("v14-model-api", _m_model_api),
    ("v14-external-service", _m_external_service),
    ("v14-bare-model-used", _m_bare_model_used),
    ("v14-bare-model-called", _m_bare_model_called),
    ("v14-bare-model-invoked", _m_bare_model_invoked),
    ("v14-bare-model-prompted", _m_bare_model_prompted),
)


_POSITIVE_SCENARIOS: tuple[tuple[str, Mutator], ...] = (
    ("baseline-unchanged-passes", _m_baseline_unchanged),
    ("safe-render-model-used-passes", _m_safe_render_model_used),
    ("safe-render-model-invoked-passes", _m_safe_render_model_invoked),
    ("safe-render-model-called-passes", _m_safe_render_model_called),
    ("safe-render-model-prompted-passes", _m_safe_render_model_prompted),
)


def _run_smoke() -> list[_Outcome]:
    results: list[_Outcome] = []

    examples_before = _snapshot(REPO_ROOT / "examples")
    scripts_before = _snapshot(REPO_ROOT / "scripts")

    # 1. Committed example passes the full validator surface.
    if not COMMITTED_REVIEW.is_file():
        results.append(_Outcome(
            "committed example exists at examples/synthetic_visual_review.json",
            False,
            f"missing: {COMMITTED_REVIEW}",
        ))
        return results
    rc, stdout, stderr = _validator_returncode(COMMITTED_REVIEW)
    results.append(_Outcome(
        "committed examples/synthetic_visual_review.json passes "
        "validate_visual_review.py",
        rc == 0,
        f"rc={rc}; stdout={stdout!r}; stderr={stderr!r}"
        if rc != 0 else "",
    ))

    # 2. Independent schema-only re-validation against the committed
    # example. Two entry points agreeing on the same fixture closes
    # the regression where one side drifts from the other.
    rc, stdout, stderr = _schema_returncode(COMMITTED_REVIEW)
    results.append(_Outcome(
        "committed examples/synthetic_visual_review.json passes "
        "validate_artifacts.py against schemas/visual_review.schema.json",
        rc == 0,
        f"rc={rc}; stdout={stdout!r}; stderr={stderr!r}"
        if rc != 0 else "",
    ))

    with tempfile.TemporaryDirectory(
        prefix="szh_visual_review_smoke_",
    ) as raw_td:
        td = Path(raw_td)

        # 3. The in-script baseline (which mirrors the committed
        # example's shape but with a different review_id) MUST pass.
        # Catches a regression where the smoke's own baseline drifts
        # from a valid candidate, which would silently invalidate
        # every refusal scenario below.
        scenario_td = td / "baseline"
        scenario_td.mkdir()
        path = _write_candidate(scenario_td, _baseline())
        rc, stdout, stderr = _validator_returncode(path)
        results.append(_Outcome(
            "in-script baseline candidate passes the validator",
            rc == 0,
            f"rc={rc}; stdout={stdout!r}; stderr={stderr!r}"
            if rc != 0 else "",
        ))

        # 4. Refusal scenarios — one tempdir per scenario so each
        # candidate writes to a fresh review.json with no carryover.
        for i, (name, mut) in enumerate(_REFUSAL_SCENARIOS):
            scenario_td = td / f"refuse_{i:02d}"
            scenario_td.mkdir()
            scen = _scenario_refuses(name, mut)
            results.append(scen(scenario_td))

        # 5. Positive negative-positive scenarios — render_model
        # evidence wording and other in-scope vocabulary MUST keep
        # passing under the same validator that refuses the bare
        # "model was used" shape.
        for i, (name, mut) in enumerate(_POSITIVE_SCENARIOS):
            scenario_td = td / f"pass_{i:02d}"
            scenario_td.mkdir()
            scen = _scenario_passes(name, mut)
            results.append(scen(scenario_td))

    examples_after = _snapshot(REPO_ROOT / "examples")
    scripts_after = _snapshot(REPO_ROOT / "scripts")
    results.append(_Outcome(
        "no file under REPO_ROOT/examples/ was mutated by the smoke",
        examples_before == examples_after,
        f"changed={_diff_keys(examples_before, examples_after)!r}",
    ))
    results.append(_Outcome(
        "no file under REPO_ROOT/scripts/ was mutated by the smoke",
        scripts_before == scripts_after,
        f"changed={_diff_keys(scripts_before, scripts_after)!r}",
    ))
    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Visual-review acceptance smoke for the per-slide rubric "
            "contract. Stdlib-only; no network, no D-One, no Qoder, "
            "no MCP, no model API, no browser, no screenshot. Runs the "
            "entire scenario set under tempfile.TemporaryDirectory() "
            "so no artifact lands in the repo."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run the in-script positive + refusal scenarios: the "
            "committed example passes the full validator AND the "
            "stdlib schema-only validator; the in-script baseline "
            "passes; every documented contract-boundary refusal "
            "fires; and the render_model evidence wording the V14 "
            "fix preserved continues to pass."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "error: --self-test is required (this script has no other "
            "invocation surface today)",
            file=sys.stderr,
        )
        return 2

    print("=== visual-review acceptance smoke ===")
    results = _run_smoke()
    fails = 0
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        suffix = f" -- {r.detail}" if not r.ok and r.detail else ""
        print(f"  [{mark}] {r.name}{suffix}")
        if not r.ok:
            fails += 1
    print()
    if fails:
        print(
            f"FAIL: {fails} scenario(s) did not behave as expected.",
            file=sys.stderr,
        )
        return 1
    print(
        f"OK (visual-review acceptance smoke): {len(results)} "
        f"scenario(s) passed. The committed visual-review contract "
        f"refuses every documented boundary and accepts the in-scope "
        f"render_model evidence wording."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
