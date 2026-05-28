"""Operator-facing one-command **trial** for the generated-image
bundle path through the local image-to-editable-PPT lane.

Sibling to ``scripts/operator_local_images_trial.py`` (which exercises
the same ``--plan-out`` / ``--approved-plan`` loop on operator-photo
inputs). This trial exercises the OTHER operator shortcut the helper
supports — a flat ``<bundle>/`` carrying ``images/`` +
``manifest.json`` + the optional ``generated_provenance.json``
sidecar — and now drives the full reviewer-approved-plan loop end to
end so a reviewer can see the generated-image sidecar surface
(``summary.generated_provenance`` + the per-row ``generator_source`` /
``intent_summary`` / ``placement_role`` / ``text_policy`` /
``subject_domain`` / ``custom_descriptor`` projection + the
``## Generated image provenance`` README section) AND the approved-plan
run lock (``summary.approved_plan.matched=true``) on the same run,
without having to assemble the bundle or write the plan by hand.

On a clean ``--out-dir`` run the trial:

  1. assembles a synthetic ``<out-dir>/bundle/`` carrying one PNG +
     one JPEG (the byte-distinct minimum-viable magic-byte-valid
     payloads the helper's own ``--self-test`` uses), a safe
     ``manifest.json``, and a safe ``generated_provenance.json``
     sidecar exercising BOTH ``placement_role`` values, two distinct
     ``text_policy`` / ``subject_domain`` values, AND both the
     present and absent forms of the optional ``custom_descriptor``
     field — representative diversity, NOT exhaustive enum coverage.
     The remaining values (``text_policy = caption_safe``;
     ``subject_domain = data_visual_concept`` / ``icon_concept`` /
     ``process_concept``) are NOT positively exercised by this
     trial OR by the helper's own ``--self-test``; the helper's
     GP9 gate guarantees closure (any value outside the
     ``_SIDECAR_ALLOWED_*`` constants is refused at ingest), and
     the negative ``GP-BAD-*`` probes in the helper's ``--self-test``
     prove that closure fires, but no component positively walks
     each member end-to-end today;
  2. invokes ``scripts/operator_local_images_to_editable_ppt.py
     --bundle <out-dir>/bundle --plan-out
     <out-dir>/approved_plan.json`` to write the reviewer-approved
     plan (which carries the top-level ``generated_provenance``
     block plus the per-row sidecar fields) without running the
     pipeline;
  3. invokes ``scripts/operator_local_images_to_editable_ppt.py
     --bundle <out-dir>/bundle --out-dir <out-dir>/review_package
     --approved-plan <out-dir>/approved_plan.json`` so the
     produced review package is gated behind the approved plan and
     the resulting ``summary.json`` carries
     ``approved_plan.matched=true``;
  4. invokes ``scripts/validate_operator_review_package.py --out-dir
     <out-dir>/review_package`` as a read-only on-disk re-check;
  5. writes a concise top-level ``<out-dir>/README.md`` naming the
     approved plan, the produced review package, the on-disk
     re-validation rc, and the local-only / no-external-service
     boundary.

The helper remains the source of truth for every manifest / sidecar /
pipeline / contract / inventory / visual-quality validation. This
script only orchestrates the helper's real CLI path, runs the
read-only review-package validator over the helper's output, and
verifies that the key produced files exist + the sidecar surface flows
through onto every ``summary.image_provenance`` row.

CLI shape::

    # Persistent trial that leaves the produced review package on disk:
    python3 scripts/generated_images_to_editable_ppt_trial.py --out-dir DIR

    # Self-test (every scenario under TMPDIR; no caller-visible
    # artifacts retained):
    python3 scripts/generated_images_to_editable_ppt_trial.py --self-test

``--out-dir`` is validated through
``core_image_to_editable_ppt_demo._validate_out_dir_arg`` so the same
URI / symlink / symlink-ancestor / repo-tree / non-empty refusals the
sibling helpers already enforce apply here too. Stale bytes on a
refused ``--out-dir`` are preserved (the script never deletes anything
under a refused path).

Local-only — does NOT call D-One, MCP, Qoder, a public network,
telemetry, a model API, an image search, or any external service. NOT
a full prompt / report / Markdown-to-PPTX automation. Real D-One
remains UNVERIFIED. The sidecar carries ``generator_source ==
"mock_generated"`` — declared operator intent for the staged synthetic
bytes, NOT a claim that any external generator ran.
"""

from __future__ import annotations

import sys

# Refuse `.pyc` writes from any imported module. Mirrors the gate every
# sibling smoke / helper applies; the bytecode flag must be flipped
# BEFORE any first-party import so the interpreter sees it at
# bytecode-write time.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shlex  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

# Reuse the helper's own out-dir gate so the trial cannot diverge from
# the contract the helper enforces, and reuse the helper's tiny PNG /
# JPEG payloads + locked boundaries tuple so the trial does not invent
# its own image-asset shape.
from core_image_to_editable_ppt_demo import (  # noqa: E402
    _validate_out_dir_arg,
)
from operator_local_images_to_editable_ppt import (  # noqa: E402
    _EXPLICIT_BOUNDARIES,
    _TINY_JPEG_BYTES,
    _TINY_PNG_BYTES,
)

HELPER_PATH = SCRIPTS_DIR / "operator_local_images_to_editable_ppt.py"
VALIDATOR_PATH = SCRIPTS_DIR / "validate_operator_review_package.py"

# Files the helper writes under its --out-dir on a happy bundle-mode
# run. Verifying these exist after the subprocess returns 0 is the
# trial's only post-run readback — the helper's own truth-checker
# already pinned every byte-level invariant.
_REVIEW_PACKAGE_FILES: tuple[str, ...] = (
    "deck.pptx",
    "summary.json",
    "README.md",
    "inventory.json",
    "visual_quality.json",
)
_REVIEW_PACKAGE_DIRS: tuple[str, ...] = (
    "workspace",
    "reports",
)

# Bundle layout. Filenames carry the ``mock_generated_`` prefix so a
# reviewer scanning ``summary.image_provenance[].operator_filename``
# can trace the bytes back to this trial. Stems match the schema id
# pattern ``^[A-Za-z0-9][A-Za-z0-9_.\\-]*$`` the operator helper
# enforces.
_BUNDLE_IMAGES: tuple[tuple[str, bytes], ...] = (
    ("mock_generated_alpha.png", _TINY_PNG_BYTES),
    ("mock_generated_beta.jpg", _TINY_JPEG_BYTES),
)

# Per-image sidecar entry. Every value is hand-picked to pass the
# helper's GP1..GP13 gates AND the validator's mirror gates. The two
# rows together exercise BOTH placement_role values (the full closed
# set, 2 of 2), two distinct text_policy values (representative
# diversity from the 3-member closed set — caption_safe is NOT
# positively exercised here), two distinct subject_domain values
# (representative diversity from the 5-member closed set —
# data_visual_concept / icon_concept / process_concept are NOT
# positively exercised here), AND both the present and absent forms
# of the optional custom_descriptor field. The trial intentionally
# exercises representative diversity rather than exhaustive enum
# coverage. The helper's own --self-test sidecar fixture uses the
# same 2-of-3 / 2-of-5 subset, so neither component walks every
# member of every closed enum end-to-end today; closure of the
# legal set is what is gated (the helper's GP9 enum-membership
# refusal + the validator's mirror gate), not per-member positive
# exercise.
_SIDECAR_ENTRIES: tuple[dict, ...] = (
    {
        "filename": "mock_generated_alpha.png",
        "generator_source": "mock_generated",
        "intent_summary": (
            "Synthetic accent for alpha (mock; local-only)"
        ),
        "placement_role": "hero_page",
        "text_policy": "no_text",
        "subject_domain": "abstract_marker",
        "custom_descriptor": "soft_color_block_v1",
    },
    {
        "filename": "mock_generated_beta.jpg",
        "generator_source": "mock_generated",
        "intent_summary": (
            "Synthetic accent for beta (mock; local-only)"
        ),
        "placement_role": "local_region",
        "text_policy": "decorative_glyphs",
        "subject_domain": "background_pattern",
    },
)

# Per-image manifest entry. Same safe wording the sibling
# ``mock_generated_images_to_editable_ppt_smoke`` uses so the manifest
# free-text fields pass the helper's MAN1..MAN12 gates AND the
# validator's string-safety scans.
_MANIFEST_ENTRIES: tuple[dict, ...] = (
    {
        "filename": "mock_generated_alpha.png",
        "slide_title": "Mock generated alpha accent",
        "alt_text": "Mock generated alpha marker bytes",
        "intended_use": "decorative accent",
    },
    {
        "filename": "mock_generated_beta.jpg",
        "slide_title": "Mock generated beta accent",
        "alt_text": "Mock generated beta marker bytes",
        "intended_use": "decorative accent",
    },
)

# Sidecar fields the trial expects to find on every image_provenance
# row of a sidecar-carrying run. Mirrors
# ``operator_local_images_to_editable_ppt._ABSENT_SIDECAR_LEAK_FIELDS``
# minus the optional ``custom_descriptor`` — the trial probes presence
# of the required projection, NOT the optional field (the helper only
# emits it when the sidecar carried it).
_REQUIRED_SIDECAR_ROW_FIELDS: tuple[str, ...] = (
    "generator_source",
    "intent_summary",
    "placement_role",
    "text_policy",
    "subject_domain",
)

# Overclaim phrases the trial-written README MUST NOT carry. The
# trial's sidecar covers BOTH placement_role values (full closed set)
# but only TWO of three text_policy and TWO of five subject_domain
# values — anyone reading the README must not be told the sidecar
# covers "every" closed enum value. Defense in depth: T1 re-reads the
# rendered README and refuses the run on any match (case-insensitive)
# so a future regression that re-introduces overclaim wording surfaces
# here, not just on a code review. Phrases are positive overclaim
# variants only; the explicitly NEGATED form (e.g. "NOT exhaustive
# enum coverage") is deliberately NOT in the list because the rendered
# README uses that exact phrasing to disclaim the overclaim. Phrases
# are kept lowercased; the scan lowercases the README text before
# checking each substring.
_FORBIDDEN_OVERCLAIMS: tuple[str, ...] = (
    "every closed enum",
    "every closed-enum",
    "every enum value",
    "every enum member",
    "covers every enum",
    "covering every enum",
    "covers all enum",
    "covering all enum",
)


def _readme_overclaim_offenders(readme_text: str) -> list[str]:
    """Return the list of ``_FORBIDDEN_OVERCLAIMS`` phrases present in
    ``readme_text`` (case-insensitive substring scan). The trial's T1
    happy path AND T7 load-bearing probe both call this helper so a
    future regression in either the deny list OR the scan logic
    surfaces consistently. A future refactor that quietly drops the
    helper or changes the scan semantics breaks both probes (T1's
    happy-path assertion vs T7's tamper-injection assertion) at once,
    which is what makes T7 actually load-bearing."""
    lowered = readme_text.lower()
    return [phrase for phrase in _FORBIDDEN_OVERCLAIMS if phrase in lowered]


# ---------------------------------------------------------------------------
# Bundle assembly.
# ---------------------------------------------------------------------------


def _write_bundle(bundle: Path) -> None:
    """Materialize the synthetic bundle at ``bundle/``.

    Writes::

        <bundle>/images/mock_generated_alpha.png   (PNG bytes)
        <bundle>/images/mock_generated_beta.jpg    (JPEG bytes)
        <bundle>/manifest.json                     (safe per-image metadata)
        <bundle>/generated_provenance.json         (sidecar exercising
                                                    representative diversity —
                                                    both placement_role values,
                                                    two distinct text_policy /
                                                    subject_domain values,
                                                    optional custom_descriptor
                                                    present/absent — NOT
                                                    exhaustive enum coverage)

    No symlinks, no subdirectories under images/, no manifest or
    sidecar field that would trip the validator's string-safety scans.
    The caller MUST have already passed the parent --out-dir through
    ``_validate_out_dir_arg`` — this function assumes the parent is
    safe to mkdir under."""
    images = bundle / "images"
    images.mkdir(parents=True, exist_ok=False)
    for filename, payload in _BUNDLE_IMAGES:
        (images / filename).write_bytes(payload)
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "images": list(_MANIFEST_ENTRIES),
            },
            indent=2, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    (bundle / "generated_provenance.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "entries": list(_SIDECAR_ENTRIES),
            },
            indent=2, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Subprocess runner.
# ---------------------------------------------------------------------------


@dataclass
class _ToolOutcome:
    name: str
    rc: int
    stdout: str
    stderr: str


def _run(name: str, cmd: list[str]) -> _ToolOutcome:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    return _ToolOutcome(
        name=name, rc=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


def _print_outcome_tail(outcome: _ToolOutcome, *, tail_lines: int = 30) -> None:
    combined = (outcome.stdout or "") + (outcome.stderr or "")
    lines = combined.splitlines()
    if not lines:
        print(f"    (no output from {outcome.name})")
        return
    print(f"    --- last {min(len(lines), tail_lines)} line(s) of "
          f"{outcome.name} output ---")
    for line in lines[-tail_lines:]:
        print(f"    {line}")


# ---------------------------------------------------------------------------
# Trial run shared by --out-dir and --self-test.
# ---------------------------------------------------------------------------


def _run_trial(out_dir: Path) -> int:
    """Drive the helper through the ``--bundle`` shortcut twice
    (``--plan-out`` to write the reviewer-approved plan, then
    ``--approved-plan`` + ``--out-dir`` to produce the review package
    behind the plan's run lock) into ``<out_dir>/`` and write the
    trial's top-level README. Returns 0 on success, 1 on any helper /
    verification failure. The helper itself leaves partial artifacts
    under ``<out_dir>/review_package/`` on failure — the trial does NOT
    delete them; an operator inspects the partial state directly.

    Caller MUST have already passed ``out_dir`` through
    ``_validate_out_dir_arg`` and confirmed it exists (the trial
    ``mkdir`` happens earlier in the entrypoint)."""
    bundle = out_dir / "bundle"
    approved_plan = out_dir / "approved_plan.json"
    review_package = out_dir / "review_package"

    print(f"=== generated_images_to_editable_ppt_trial ===")
    print(f"  out-dir:         {out_dir}")
    print(f"  bundle:          {bundle}")
    print(f"  approved-plan:   {approved_plan}")
    print(f"  review-package:  {review_package}")
    print()

    # Stage A — assemble the synthetic bundle the helper will discover.
    _write_bundle(bundle)
    discovered_images = sorted(p.name for p in (bundle / "images").iterdir())
    print(f"--- synthetic bundle written ---")
    print(f"  images:          {discovered_images}")
    print(f"  manifest.json:   {(bundle / 'manifest.json').is_file()}")
    print(f"  sidecar:         "
          f"{(bundle / 'generated_provenance.json').is_file()}")

    # Stage B — drive the helper through --bundle + --plan-out to
    # write the reviewer-approved plan. Plan-only mode does NOT touch
    # the pipeline; it captures the deterministic plan body (image
    # rows + manifest_path + generated_provenance) the operator-mode
    # run will compare against. Run BEFORE any out-dir review-package
    # mkdir so the plan is the first thing on disk.
    plan_outcome = _run(
        "operator_local_images_to_editable_ppt --bundle --plan-out",
        [
            sys.executable, str(HELPER_PATH),
            "--bundle", str(bundle),
            "--plan-out", str(approved_plan),
        ],
    )
    if plan_outcome.rc != 0:
        print(f"  [FAIL] plan-out helper rc={plan_outcome.rc}")
        _print_outcome_tail(plan_outcome)
        return 1
    if not approved_plan.is_file() or approved_plan.is_symlink():
        print(f"  [FAIL] expected approved plan at {approved_plan} as "
              f"a regular non-symlink file")
        return 1
    try:
        plan_body = json.loads(approved_plan.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"  [FAIL] could not parse approved plan: "
              f"{type(exc).__name__}: {exc}")
        return 1
    plan_gp = plan_body.get("generated_provenance")
    if not isinstance(plan_gp, dict):
        print(f"  [FAIL] approved plan generated_provenance is not a "
              f"dict (got {plan_gp!r}); expected {{path, entry_count}}")
        return 1
    if plan_gp.get("entry_count") != len(_BUNDLE_IMAGES):
        print(f"  [FAIL] approved plan generated_provenance."
              f"entry_count={plan_gp.get('entry_count')!r}; expected "
              f"{len(_BUNDLE_IMAGES)}")
        return 1
    print(f"  [PASS] approved plan written to {approved_plan} "
          f"(generated_provenance.entry_count="
          f"{plan_gp['entry_count']})")

    # Stage C — drive the helper through --bundle + --out-dir +
    # --approved-plan so the review package is gated behind the plan
    # the previous stage wrote. The helper refuses with rc 2 BEFORE
    # any mkdir if the current bundle drifts from the approved plan;
    # reaching rc==0 here means the approved-plan compare passed AND
    # the produced summary carries the matched=True evidence block.
    helper_outcome = _run(
        "operator_local_images_to_editable_ppt --bundle --approved-plan",
        [
            sys.executable, str(HELPER_PATH),
            "--bundle", str(bundle),
            "--out-dir", str(review_package),
            "--approved-plan", str(approved_plan),
        ],
    )
    if helper_outcome.rc != 0:
        print(f"  [FAIL] operator helper rc={helper_outcome.rc}")
        _print_outcome_tail(helper_outcome)
        return 1
    print(f"  [PASS] operator helper rc=0")

    # Stage D — verify the review package on disk. The helper's own
    # truth-checker already gated every byte-level invariant before it
    # returned 0; the trial only spot-checks that the canonical files
    # exist so an operator does not have to chase down a torn run.
    missing_files = [
        name for name in _REVIEW_PACKAGE_FILES
        if not (review_package / name).is_file()
        or (review_package / name).is_symlink()
    ]
    missing_dirs = [
        name for name in _REVIEW_PACKAGE_DIRS
        if not (review_package / name).is_dir()
        or (review_package / name).is_symlink()
    ]
    if missing_files or missing_dirs:
        for name in missing_files:
            print(f"  [FAIL] missing review-package file: "
                  f"{review_package / name}")
        for name in missing_dirs:
            print(f"  [FAIL] missing review-package directory: "
                  f"{review_package / name}")
        return 1
    print(f"  [PASS] every review-package artifact exists "
          f"(files={list(_REVIEW_PACKAGE_FILES)}, "
          f"dirs={list(_REVIEW_PACKAGE_DIRS)})")

    # Stage E — confirm the sidecar surface AND the approved-plan
    # run lock both flow through. Required so the trial directly
    # proves what its name advertises (a regression that silently
    # drops the sidecar block, fails to project the per-row fields,
    # or returns 0 without recording approved_plan.matched=True
    # surfaces here, not just in the validator stage).
    summary_path = review_package / "summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"  [FAIL] could not parse summary.json: "
              f"{type(exc).__name__}: {exc}")
        return 1

    image_count = summary.get("image_count")
    gp = summary.get("generated_provenance")
    if not isinstance(gp, dict):
        print(f"  [FAIL] summary.generated_provenance is not a dict "
              f"(got {gp!r}); expected {{path, entry_count}}")
        return 1
    if gp.get("entry_count") != image_count:
        print(f"  [FAIL] summary.generated_provenance.entry_count="
              f"{gp.get('entry_count')!r}; expected "
              f"summary.image_count={image_count!r}")
        return 1
    if not isinstance(gp.get("path"), str) or not gp.get("path"):
        print(f"  [FAIL] summary.generated_provenance.path is not a "
              f"non-empty string (got {gp.get('path')!r})")
        return 1
    print(f"  [PASS] summary.generated_provenance carries "
          f"entry_count={gp['entry_count']} == image_count={image_count}")

    ap = summary.get("approved_plan")
    if not isinstance(ap, dict) or ap.get("matched") is not True:
        print(f"  [FAIL] summary.approved_plan.matched is not True "
              f"(approved_plan={ap!r})")
        return 1
    print(f"  [PASS] summary.approved_plan.matched=True "
          f"(path={ap.get('path')!r}, "
          f"sha256={(ap.get('sha256') or '')[:12]}...)")

    prov = summary.get("image_provenance")
    if not isinstance(prov, list) or len(prov) != image_count:
        n = len(prov) if isinstance(prov, list) else "n/a"
        print(f"  [FAIL] summary.image_provenance length={n}; expected "
              f"{image_count}")
        return 1
    for i, entry in enumerate(prov):
        if not isinstance(entry, dict):
            print(f"  [FAIL] image_provenance[{i}] is not a dict")
            return 1
        missing = [
            f for f in _REQUIRED_SIDECAR_ROW_FIELDS if f not in entry
        ]
        if missing:
            print(f"  [FAIL] image_provenance[{i}] for "
                  f"{entry.get('operator_filename')!r} missing sidecar "
                  f"field(s) {missing!r}")
            return 1
    print(f"  [PASS] every image_provenance row carries "
          f"{list(_REQUIRED_SIDECAR_ROW_FIELDS)} from the sidecar")

    # Stage F — read-only stdlib re-check of the produced review
    # package via the companion validator. The validator never writes
    # to the package; it re-checks every locked summary field + path-
    # resolve gate + inventory / visual-quality / approved-plan /
    # generated_provenance invariant the helper's own truth-checker
    # enforced before exit, so a tampered post-helper edit (or a
    # future helper regression that lets such an edit through) fails
    # closed here too. Run BEFORE the trial README write so the README
    # can carry the validator rc, and so a torn re-check cannot leave
    # a positive-looking README behind.
    validator_outcome = _run(
        "validate_operator_review_package --out-dir",
        [
            sys.executable, str(VALIDATOR_PATH),
            "--out-dir", str(review_package),
        ],
    )
    if validator_outcome.rc != 0:
        print(f"  [FAIL] validate_operator_review_package "
              f"rc={validator_outcome.rc}")
        _print_outcome_tail(validator_outcome)
        return 1
    print(f"  [PASS] validate_operator_review_package rc=0 "
          f"(read-only / local-only)")

    # Stage G — concise top-level README pointing the operator at
    # what to open first. Rendered into memory FIRST so the overclaim
    # gate can refuse to write before any bytes land on disk: the
    # trial's sidecar covers both placement_role values (full closed
    # set) but only TWO of three text_policy and TWO of five
    # subject_domain values, so a regression that re-introduced
    # "every closed enum value"-style wording into the rendered README
    # would mislead reviewers. Gating BEFORE write means a tampered
    # render leaves no on-disk README behind for the validator + T1
    # to chase. Routed through ``_readme_overclaim_offenders`` so
    # T7's load-bearing probe can drive the same gate via a
    # monkey-patched renderer.
    trial_readme = out_dir / "README.md"
    rendered_readme = _render_trial_readme(
        review_package=review_package,
        bundle=bundle,
        approved_plan=approved_plan,
        validator_rc=validator_outcome.rc,
        entry_count=gp["entry_count"],
    )
    rendered_offenders = _readme_overclaim_offenders(rendered_readme)
    if rendered_offenders:
        print(
            f"  [FAIL] rendered trial README carries forbidden "
            f"overclaim phrase(s) {rendered_offenders!r} — the "
            f"sidecar covers representative diversity, NOT every "
            f"enum member; refusing to write the README"
        )
        return 1
    trial_readme.write_text(rendered_readme, encoding="utf-8")
    if not trial_readme.is_file() or trial_readme.is_symlink():
        print(f"  [FAIL] expected trial README at {trial_readme} as a "
              f"regular non-symlink file")
        return 1
    print(f"  [PASS] trial README written to {trial_readme}")

    print()
    print(f"OK: trial review package under {review_package}. Open "
          f"{trial_readme} first.")
    return 0


def _render_trial_readme(
    *,
    review_package: Path,
    bundle: Path,
    approved_plan: Path,
    validator_rc: int,
    entry_count: int,
) -> str:
    """Render the trial's top-level operator-facing README. Names what
    landed where, which files to open first, the on-disk re-validation
    rc, and the locked local-only / no-external-service boundary. The
    approved-plan loop is now the headline path — the README points
    the operator at ``approved_plan.json`` first so the
    reviewer-approved plan is the entry point, not the produced
    PPTX."""
    return "\n".join([
        "# generated_images_to_editable_ppt_trial — review package",
        "",
        "A one-command trial run of the generated-image bundle path "
        "through the local image-to-editable-PPT lane, end to end "
        "through the reviewer-approved-plan loop. Exercises both the "
        "approved-plan run lock (`summary.approved_plan.matched=true`) "
        "AND the optional `<bundle>/generated_provenance.json` sidecar "
        "(the `summary.generated_provenance` block + the per-row "
        "`generator_source` / `intent_summary` / `placement_role` / "
        "`text_policy` / `subject_domain` projection + the "
        "`## Generated image provenance` README section) so a reviewer "
        "can confirm the full operator approval surface fires on the "
        "same run.",
        "",
        "## What to open first",
        "",
        f"1. `{approved_plan.relative_to(approved_plan.parent)}` — "
        "reviewer-approved plan written by "
        "`scripts/operator_local_images_to_editable_ppt.py --bundle "
        "<bundle> --plan-out`. Inspect this BEFORE the review package: "
        "the operator-mode run below was gated behind a "
        "byte-identical match against this plan and refused to "
        "produce any review-package artifact under a drift. Carries "
        f"the top-level `generated_provenance` block "
        f"(entry_count={entry_count}) AND the per-row sidecar "
        "projection.",
        f"2. `{(review_package / 'README.md').relative_to(review_package.parent)}` — operator-facing review-package README "
        "written by the helper. Includes a `## Generated image "
        "provenance` section listing the per-entry sidecar fields.",
        f"3. `{(review_package / 'deck.pptx').relative_to(review_package.parent)}` — the produced editable PPTX. "
        "One cover slide per synthetic image; titles and shapes are "
        "native PowerPoint objects.",
        f"4. `{(review_package / 'summary.json').relative_to(review_package.parent)}` — compact summary. The "
        "`generated_provenance` block confirms the sidecar fired "
        f"(entry_count={entry_count}); the `approved_plan` block "
        "confirms `matched=true` against the plan above; each "
        "`image_provenance[]` row carries `generator_source` / "
        "`intent_summary` / `placement_role` / `text_policy` / "
        "`subject_domain` from the sidecar.",
        f"5. `{(review_package / 'inventory.json').relative_to(review_package.parent)}` — `inspect_pptx_inventory` "
        "readback over the produced PPTX.",
        f"6. `{(review_package / 'visual_quality.json').relative_to(review_package.parent)}` — `validate_visual_quality` "
        "report over the produced workspace.",
        f"7. `{(review_package / 'workspace').relative_to(review_package.parent)}/source_image_assets.json` — "
        "source-attached image registry the helper wrote into the "
        "production workspace.",
        f"8. `{(review_package / 'reports').relative_to(review_package.parent)}/` — `pipeline_report.{{json,txt}}` "
        "from the underlying `run_pipeline.py`.",
        "",
        "## How this trial was produced",
        "",
        f"- Synthetic bundle: `{bundle.name}/` — `images/` (one PNG + "
        "one JPEG, magic-byte-valid, byte-distinct so each operator "
        "file maps to a distinct embedded `ppt/media/*` part), "
        "`manifest.json` (safe per-image slide_title / alt_text / "
        "intended_use), and `generated_provenance.json` (two sidecar "
        "entries exercising representative diversity — both "
        "`placement_role` values (2 of 2), two distinct `text_policy` "
        "values (out of a 3-member closed set; `caption_safe` is "
        "not positively exercised here), two distinct "
        "`subject_domain` values (out of a 5-member closed set; "
        "`data_visual_concept` / `icon_concept` / `process_concept` "
        "are not positively exercised here), and both the present "
        "and absent forms of the optional `custom_descriptor` "
        "field. This is representative diversity, not exhaustive "
        "coverage of the helper's full enum surface; the helper's "
        "own `--self-test` sidecar fixture uses the same 2-of-3 / "
        "2-of-5 subset, so neither this trial nor the helper "
        "positively exercises each value in the closed `text_policy` "
        "and `subject_domain` sets end-to-end today. What IS gated "
        "is closure: the helper's GP9 enum-membership refusal + the "
        "validator's mirror gate refuse any value outside the "
        "closed sets, and the negative GP-BAD-* probes in "
        "`scripts/operator_local_images_to_editable_ppt.py "
        "--self-test` prove those refusals fire.",
        f"- Reviewer-approved plan: `{approved_plan.name}` — written "
        "by `scripts/operator_local_images_to_editable_ppt.py "
        "--bundle <bundle> --plan-out` against the synthetic bundle "
        "above. Plan-only mode does NOT run the pipeline; it captures "
        "the deterministic plan body (image rows + manifest_path + "
        "`generated_provenance`) that the operator-mode run compared "
        "against.",
        f"- Review package: `{review_package.name}/` — written by "
        "`scripts/operator_local_images_to_editable_ppt.py --bundle "
        "<bundle> --out-dir <review_package> --approved-plan "
        f"{approved_plan.name}`, so the plan-out / approved-plan loop "
        "is exercised end to end and the produced summary records "
        "`approved_plan.matched=true`.",
        "",
        "## On-disk re-validation",
        "",
        f"`scripts/validate_operator_review_package.py --out-dir "
        f"{review_package.name}` rc={validator_rc}. Read-only stdlib "
        "re-check; local-only — does not call D-One, MCP, Qoder, a "
        "public network, a model API, an image search, or telemetry. "
        "Re-run anytime with:",
        "",
        "```",
        # shlex.quote so a path with spaces, glob chars, or shell
        # metacharacters survives a copy-paste — the helper's out-dir
        # gate does NOT forbid spaces (a legitimate path under
        # ``/Users/Some Name/...`` is accepted), so an unquoted
        # interpolation would emit a broken command that splits the
        # path on the first whitespace OR (with maliciously crafted
        # paths) be shell-injectable into a reviewer's terminal.
        f"python3 scripts/validate_operator_review_package.py "
        f"--out-dir {shlex.quote(str(review_package))}",
        "```",
        "",
        "## Boundary statement",
        "",
        "Local-only. Does NOT call D-One, MCP, Qoder, a public "
        "network, telemetry, a model API, an image search, or any "
        "external service. The sidecar's `generator_source == "
        "\"mock_generated\"` records declared operator intent for the "
        "staged synthetic bytes; it does NOT claim any external "
        "generator ran. Real D-One image generation remains "
        "UNVERIFIED. NOT a prompt / report / Markdown-to-PPTX "
        "automation.",
        "",
        "## Cleaning up",
        "",
        "When done inspecting, remove the trial directory directly:",
        "",
        "```",
        # Same shlex.quote rationale — ``rm -rf`` on an unquoted
        # spaces-containing path could remove the wrong directory.
        f"rm -rf {shlex.quote(str(review_package.parent))}",
        "```",
        "",
    ])


# ---------------------------------------------------------------------------
# Helpers reused by --self-test for repo-tree snapshotting.
# ---------------------------------------------------------------------------


_REPO_SNAPSHOT_DIRS: tuple[str, ...] = (
    "examples",
    "references",
    "schemas",
    "scripts",
    "templates",
)
_REPO_SNAPSHOT_FILES: tuple[str, ...] = (
    "README.md",
    "SKILL.md",
)


def _snapshot_dir(d: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        out[str(p.relative_to(d))] = p.read_bytes()
    return out


def _snapshot_repo() -> dict[str, bytes]:
    """Snapshot every committed top-level path the trial promises to
    leave untouched. Top-level files are recorded directly; top-level
    directories are walked recursively. Returns a flat
    ``{rel_path: bytes}`` dict so the byte-level before/after compare
    is a single equality check."""
    out: dict[str, bytes] = {}
    for fname in _REPO_SNAPSHOT_FILES:
        p = REPO_ROOT / fname
        if p.is_file() and not p.is_symlink():
            out[fname] = p.read_bytes()
    for dname in _REPO_SNAPSHOT_DIRS:
        for rel, payload in _snapshot_dir(REPO_ROOT / dname).items():
            out[f"{dname}/{rel}"] = payload
    return out


def _check_repo_unchanged(
    *,
    snapshot_before: dict[str, bytes],
) -> int:
    """Compare the committed-tree snapshot before/after the self-test.
    Returns 0 when byte-identical, 1 otherwise. Mirrors the gate the
    sibling trial applies but covers the broader committed surface the
    goal pins (examples + references + schemas + scripts + templates +
    README.md + SKILL.md)."""
    snapshot_after = _snapshot_repo()
    if snapshot_before == snapshot_after:
        return 0
    changed = sorted(
        k for k in set(snapshot_before) | set(snapshot_after)
        if snapshot_before.get(k) != snapshot_after.get(k)
    )
    print(
        f"FAIL: committed repo surface was mutated by self-test "
        f"(changed: {changed!r})",
        file=sys.stderr,
    )
    return 1


@dataclass
class _ProbeResult:
    name: str
    ok: bool
    detail: str = ""


# ---------------------------------------------------------------------------
# Self-test entrypoint.
# ---------------------------------------------------------------------------


def _run_self_tests() -> int:
    print("=== generated_images_to_editable_ppt_trial --self-test ===")
    snapshot_before = _snapshot_repo()

    results: list[_ProbeResult] = []

    # T1 happy path: drive the trial into a per-run tempdir; confirm
    # the produced review package + trial README + sidecar surface +
    # helper-locked boundaries are all in place.
    with tempfile.TemporaryDirectory(prefix="gen-img-trial-T1-") as raw_td:
        td = Path(raw_td)
        out_dir = td / "trial"
        rc = main(["--out-dir", str(out_dir)])
        ok = rc == 0
        detail = ""
        if ok:
            review_package = out_dir / "review_package"
            for name in _REVIEW_PACKAGE_FILES:
                if not (review_package / name).is_file():
                    ok = False
                    detail = (
                        f"missing review package file: "
                        f"{review_package / name}"
                    )
                    break
            if ok:
                for name in _REVIEW_PACKAGE_DIRS:
                    if not (review_package / name).is_dir():
                        ok = False
                        detail = (
                            f"missing review package dir: "
                            f"{review_package / name}"
                        )
                        break
            if ok and not (out_dir / "README.md").is_file():
                ok = False
                detail = "missing trial README"
            if ok and not (out_dir / "bundle").is_dir():
                ok = False
                detail = "missing bundle/"
            if ok and not (
                out_dir / "bundle" / "generated_provenance.json"
            ).is_file():
                ok = False
                detail = "missing bundle/generated_provenance.json"
            # The trial must land the reviewer-approved plan FIRST —
            # this is the file the operator inspects before the
            # produced review package, and the file the operator-mode
            # run was gated behind. A missing approved_plan.json means
            # either the plan-out subprocess regressed OR the trial
            # skipped Stage B.
            if ok and (
                not (out_dir / "approved_plan.json").is_file()
                or (out_dir / "approved_plan.json").is_symlink()
            ):
                ok = False
                detail = "missing approved_plan.json"
            if ok:
                try:
                    plan_body = json.loads(
                        (out_dir / "approved_plan.json").read_text(
                            encoding="utf-8",
                        )
                    )
                except (OSError, ValueError) as exc:
                    ok = False
                    detail = (
                        f"approved_plan.json unparseable: "
                        f"{type(exc).__name__}: {exc}"
                    )
                else:
                    # generated_provenance MUST appear in the plan as a
                    # dict — when a sidecar is supplied the plan body
                    # carries the top-level {path, entry_count} block
                    # that the operator-mode compare locks the run
                    # against. A null here would prove the plan-out
                    # path lost the sidecar projection.
                    plan_gp = plan_body.get("generated_provenance")
                    if not isinstance(plan_gp, dict):
                        ok = False
                        detail = (
                            f"approved_plan.generated_provenance not "
                            f"a dict: {plan_gp!r}"
                        )
                    elif plan_gp.get("entry_count") != len(
                        _BUNDLE_IMAGES,
                    ):
                        ok = False
                        detail = (
                            f"approved_plan.generated_provenance."
                            f"entry_count="
                            f"{plan_gp.get('entry_count')!r}; "
                            f"expected {len(_BUNDLE_IMAGES)!r}"
                        )
            if ok:
                try:
                    summary = json.loads(
                        (review_package / "summary.json").read_text(
                            encoding="utf-8",
                        )
                    )
                except (OSError, ValueError) as exc:
                    ok = False
                    detail = (
                        f"summary.json unparseable: "
                        f"{type(exc).__name__}: {exc}"
                    )
                else:
                    image_count = summary.get("image_count")
                    if image_count != len(_BUNDLE_IMAGES):
                        ok = False
                        detail = (
                            f"summary.image_count={image_count!r}; "
                            f"expected {len(_BUNDLE_IMAGES)}"
                        )
                if ok:
                    gp = summary.get("generated_provenance")
                    if not isinstance(gp, dict):
                        ok = False
                        detail = (
                            f"summary.generated_provenance not a "
                            f"dict: {gp!r}"
                        )
                    elif gp.get("entry_count") != image_count:
                        ok = False
                        detail = (
                            f"summary.generated_provenance."
                            f"entry_count={gp.get('entry_count')!r}; "
                            f"expected {image_count!r}"
                        )
                if ok:
                    # The approved-plan compare must have matched — a
                    # regression that returned 0 without writing the
                    # matched=True evidence block, or that skipped the
                    # --approved-plan subprocess entirely, surfaces
                    # here.
                    ap = summary.get("approved_plan")
                    if not isinstance(ap, dict):
                        ok = False
                        detail = (
                            f"summary.approved_plan not a dict: "
                            f"{ap!r}"
                        )
                    elif ap.get("matched") is not True:
                        ok = False
                        detail = (
                            f"summary.approved_plan.matched is not "
                            f"True: {ap!r}"
                        )
                if ok:
                    prov = summary.get("image_provenance") or []
                    if len(prov) != image_count:
                        ok = False
                        detail = (
                            f"image_provenance length={len(prov)}; "
                            f"expected {image_count}"
                        )
                    else:
                        for i, entry in enumerate(prov):
                            for fld in _REQUIRED_SIDECAR_ROW_FIELDS:
                                if fld not in entry:
                                    ok = False
                                    detail = (
                                        f"image_provenance[{i}] "
                                        f"missing sidecar field {fld!r}"
                                    )
                                    break
                            if not ok:
                                break
                if ok:
                    boundaries = summary.get("explicit_boundaries")
                    if list(_EXPLICIT_BOUNDARIES) != boundaries:
                        ok = False
                        detail = (
                            f"summary.explicit_boundaries drifted "
                            f"from the locked helper tuple"
                        )
                if ok:
                    if summary.get("real_d_one_status") != "UNVERIFIED":
                        ok = False
                        detail = (
                            f"summary.real_d_one_status != "
                            f"'UNVERIFIED' (got "
                            f"{summary.get('real_d_one_status')!r})"
                        )
                if ok:
                    # The trial README must record the on-disk
                    # re-validation rc the trial just ran via the
                    # read-only companion validator. Re-reading the
                    # README here locks the wiring in place — a
                    # future regression that skips the validator
                    # stage OR writes the README without the
                    # validator line surfaces as a T1 FAIL.
                    try:
                        readme_text = (
                            out_dir / "README.md"
                        ).read_text(encoding="utf-8")
                    except OSError as exc:
                        ok = False
                        detail = (
                            f"trial README unreadable: "
                            f"{type(exc).__name__}: {exc}"
                        )
                    else:
                        if (
                            "validate_operator_review_package"
                            not in readme_text
                        ):
                            ok = False
                            detail = (
                                f"trial README does not mention "
                                f"validate_operator_review_package"
                            )
                        elif "rc=0" not in readme_text:
                            ok = False
                            detail = (
                                f"trial README does not record "
                                f"on-disk re-validation rc=0"
                            )
                        else:
                            # Overclaim absence gate. The trial's
                            # sidecar covers BOTH placement_role
                            # values (full closed set) but only TWO
                            # of three text_policy and TWO of five
                            # subject_domain values. A future
                            # regression that re-introduces "every
                            # closed enum value"-style wording to
                            # the rendered README would mislead
                            # reviewers — refuse here. Routed through
                            # ``_readme_overclaim_offenders`` so T7's
                            # load-bearing probe exercises the same
                            # code path.
                            offenders = _readme_overclaim_offenders(
                                readme_text,
                            )
                            if offenders:
                                ok = False
                                detail = (
                                    f"trial README carries forbidden "
                                    f"overclaim phrase(s) "
                                    f"{offenders!r} — the sidecar "
                                    f"covers representative diversity, "
                                    f"NOT every enum member"
                                )
        else:
            detail = f"main(--out-dir) rc={rc}"
        results.append(
            _ProbeResult(name="T1 happy path", ok=ok, detail=detail),
        )

    # T2 OP1: URI-shaped --out-dir refused before any filesystem touch.
    with tempfile.TemporaryDirectory(prefix="gen-img-trial-T2-") as raw_td:
        td = Path(raw_td)
        uri_out = "file:///" + str(td / "uri_out").lstrip("/")
        rc = main(["--out-dir", uri_out])
        ok = (
            rc == 2
            and not (td / "uri_out").exists()
            and not (Path("/" + uri_out.removeprefix("file:///"))).exists()
        )
        detail = "" if ok else f"rc={rc}; uri_out probe leaked filesystem"
        results.append(
            _ProbeResult(name="T2 OP1 URI refused", ok=ok, detail=detail),
        )

    # T3 OP2: symlinked --out-dir refused.
    with tempfile.TemporaryDirectory(prefix="gen-img-trial-T3-") as raw_td:
        td = Path(raw_td)
        link_target = td / "real_target"
        link_target.mkdir()
        link = td / "linked_out"
        link.symlink_to(link_target)
        rc = main(["--out-dir", str(link)])
        # Refusal MUST leave the symlink + its target untouched.
        ok = (
            rc == 2
            and link.is_symlink()
            and link_target.is_dir()
            and list(link_target.iterdir()) == []
        )
        detail = "" if ok else (
            f"rc={rc}; link.is_symlink={link.is_symlink()}; "
            f"target_contents={list(link_target.iterdir())!r}"
        )
        results.append(_ProbeResult(
            name="T3 OP2 symlink refused", ok=ok, detail=detail,
        ))

    # T4 OP3: symlink ancestor of --out-dir refused.
    with tempfile.TemporaryDirectory(prefix="gen-img-trial-T4-") as raw_td:
        td = Path(raw_td)
        real_parent = td / "real_parent"
        real_parent.mkdir()
        ancestor = td / "ancestor_link"
        ancestor.symlink_to(real_parent)
        leaf = ancestor / "out"
        rc = main(["--out-dir", str(leaf)])
        ok = (
            rc == 2
            and not (real_parent / "out").exists()
            and ancestor.is_symlink()
        )
        detail = "" if ok else (
            f"rc={rc}; (real_parent/out).exists="
            f"{(real_parent / 'out').exists()}"
        )
        results.append(_ProbeResult(
            name="T4 OP3 symlink ancestor refused",
            ok=ok, detail=detail,
        ))

    # T5 OP4: --out-dir inside REPO_ROOT refused.
    repo_inside = REPO_ROOT / "tmp_gen_img_trial_inside_repo_tree"
    rc = main(["--out-dir", str(repo_inside)])
    ok = rc == 2 and not repo_inside.exists()
    detail = "" if ok else (
        f"rc={rc}; repo_inside.exists={repo_inside.exists()}"
    )
    results.append(_ProbeResult(
        name="T5 OP4 inside REPO_ROOT refused",
        ok=ok, detail=detail,
    ))

    # T6 OP5: pre-existing non-empty --out-dir refused AND stale bytes
    # preserved byte-identical after the refusal.
    with tempfile.TemporaryDirectory(prefix="gen-img-trial-T6-") as raw_td:
        td = Path(raw_td)
        stale_out = td / "stale_out"
        stale_out.mkdir()
        stale_file = stale_out / "leftover.txt"
        stale_bytes = b"prior-operator-bytes-must-be-preserved\n"
        stale_file.write_bytes(stale_bytes)
        rc = main(["--out-dir", str(stale_out)])
        ok = (
            rc == 2
            and stale_file.is_file()
            and stale_file.read_bytes() == stale_bytes
            and sorted(p.name for p in stale_out.iterdir())
            == ["leftover.txt"]
        )
        detail = "" if ok else (
            f"rc={rc}; stale_bytes_preserved="
            f"{stale_file.read_bytes() == stale_bytes if stale_file.exists() else 'missing'}"
        )
        results.append(_ProbeResult(
            name="T6 OP5 non-empty refused (stale preserved)",
            ok=ok, detail=detail,
        ))

    # T7 overclaim guard is load-bearing — the probe drives the SAME
    # ``_run_trial`` code path a production ``--out-dir`` invocation
    # takes, with the renderer monkey-patched at the module level to
    # return an overclaim-bearing string. Load-bearing in three
    # independent senses:
    #
    #   (a) deny-list completeness — every phrase in
    #       ``_FORBIDDEN_OVERCLAIMS`` is independently checked by
    #       running a full ``main(["--out-dir", ...])`` for each
    #       phrase under the patched renderer; the gate MUST refuse
    #       (rc != 0) AND MUST NOT have written the README. A
    #       regression that silently drops a deny-list entry surfaces
    #       here as a per-phrase rc-0 / README-exists pair.
    #
    #   (b) case-insensitive scan — every injected phrase is in
    #       mixed-case (.title()). If the helper were weakened to
    #       plain ``in`` against raw text without ``.lower()`` the
    #       gate would silently accept the title-case overclaim AND
    #       the probe would flip red. Locks the helper's case-fold
    #       semantics in place.
    #
    #   (c) gate sits inside the production code path — the probe
    #       calls ``main`` (the same entry production callers use),
    #       not the helper in isolation. If a future refactor removed
    #       the ``_readme_overclaim_offenders`` call from
    #       ``_run_trial`` (the gate's only production site), the
    #       tampered render would land on disk and the per-phrase
    #       ``rc != 0`` assertion AND the ``README must not exist``
    #       assertion would BOTH flip red.
    #
    # The probe restores the original renderer in a ``finally`` so a
    # mid-probe exception cannot leak the patched function into the
    # later probes — every later run sees the canonical renderer.
    # ``globals()`` is the running module's namespace and is what
    # ``_run_trial`` resolves ``_render_trial_readme`` against, so
    # patching here actually affects the production call site.
    # (``import generated_images_to_editable_ppt_trial`` would create
    # a SECOND module instance when this file runs as __main__, and
    # patching THAT would not affect the running module — handy to
    # remember; ``globals()`` sidesteps the issue.)
    canonical_render = globals()["_render_trial_readme"]
    rc_per_phrase: dict[str, int] = {}
    readme_existed_per_phrase: dict[str, bool] = {}
    try:
        for phrase in _FORBIDDEN_OVERCLAIMS:
            tampered_text = (
                "# generated_images_to_editable_ppt_trial — review "
                "package\n\nTamper injection (T7): "
                + phrase.title() +
                "\n\nvalidate_operator_review_package rc=0\n"
            )

            def _tampered_render(
                *,
                review_package: Path,
                bundle: Path,
                approved_plan: Path,
                validator_rc: int,
                entry_count: int,
                _text: str = tampered_text,
            ) -> str:
                return _text

            globals()["_render_trial_readme"] = _tampered_render
            with tempfile.TemporaryDirectory(
                prefix="gen-img-trial-T7-",
            ) as raw_td:
                td = Path(raw_td)
                out_dir = td / "trial"
                rc = main(["--out-dir", str(out_dir)])
                rc_per_phrase[phrase] = rc
                readme_existed_per_phrase[phrase] = (
                    (out_dir / "README.md").is_file()
                )
    finally:
        globals()["_render_trial_readme"] = canonical_render

    unrefused_phrases = [
        phrase for phrase, rc in rc_per_phrase.items() if rc == 0
    ]
    readme_leak_phrases = [
        phrase for phrase, existed in readme_existed_per_phrase.items()
        if existed
    ]
    deny_list_ok = len(_FORBIDDEN_OVERCLAIMS) >= 4
    ran_all = (
        len(rc_per_phrase) == len(_FORBIDDEN_OVERCLAIMS)
        and len(readme_existed_per_phrase)
        == len(_FORBIDDEN_OVERCLAIMS)
    )
    ok = (
        deny_list_ok
        and ran_all
        and not unrefused_phrases
        and not readme_leak_phrases
    )
    detail = "" if ok else (
        f"deny_list_size={len(_FORBIDDEN_OVERCLAIMS)}; "
        f"ran_all={ran_all!r}; "
        f"unrefused_phrases={unrefused_phrases!r}; "
        f"readme_leak_phrases={readme_leak_phrases!r}"
    )
    results.append(_ProbeResult(
        name="T7 overclaim guard load-bearing",
        ok=ok, detail=detail,
    ))

    # T8 shell-quoting of accepted paths with spaces / shell-meta. The
    # helper's ``_validate_out_dir_arg`` gate accepts paths that
    # contain spaces (e.g. ``/Users/Some Name/...``); the trial-written
    # top-level README emits two literal shell commands (the
    # ``validate_operator_review_package --out-dir <review_package>``
    # re-run AND the ``rm -rf <out_dir>`` cleanup). Unquoted f-string
    # interpolation would emit broken commands that split on the first
    # whitespace AND would be shell-injectable on maliciously crafted
    # paths a reviewer might paste. This probe drives a real
    # ``main(--out-dir=<path with spaces>)`` run and asserts:
    #
    #   (a) the rendered README carries the validate command in
    #       ``shlex.quote``-style single-quoted form (the absolute
    #       review_package path embedded inside ``'...'``);
    #   (b) the rendered README carries the cleanup command in the
    #       same single-quoted form for the out_dir parent;
    #   (c) the rendered README does NOT carry the bare unquoted
    #       form — a future regression that drops ``shlex.quote``
    #       would re-introduce that exact substring.
    #
    # The probe also verifies the trial returned rc=0 (a spaces-bearing
    # out-dir is an accepted path, not a failure mode) so a regression
    # that started refusing spaces masquerading as "fixing" the
    # quoting would surface here too.
    with tempfile.TemporaryDirectory(
        prefix="gen-img-trial-T8 spaces-",
    ) as raw_td:
        td = Path(raw_td)
        out_dir = td / "trial with spaces"
        rc = main(["--out-dir", str(out_dir)])
        ok = rc == 0
        detail = ""
        if not ok:
            detail = f"main(--out-dir with spaces) rc={rc}"
        else:
            readme_path = out_dir / "README.md"
            if not readme_path.is_file():
                ok = False
                detail = f"missing README at {readme_path}"
            else:
                readme_text = readme_path.read_text(encoding="utf-8")
                review_package_q = shlex.quote(
                    str(out_dir / "review_package"),
                )
                out_dir_q = shlex.quote(str(out_dir))
                validate_quoted = (
                    "python3 scripts/validate_operator_review_package.py "
                    f"--out-dir {review_package_q}"
                )
                cleanup_quoted = f"rm -rf {out_dir_q}"
                # The bare (unquoted) form a regression would
                # accidentally re-introduce — emit-time substring
                # check so we catch the regression even if the
                # quoted form ALSO happened to land somewhere.
                validate_bare = (
                    "python3 scripts/validate_operator_review_package.py "
                    f"--out-dir {out_dir / 'review_package'}"
                )
                cleanup_bare = f"rm -rf {out_dir}"
                missing: list[str] = []
                if validate_quoted not in readme_text:
                    missing.append("quoted-validate-cmd")
                if cleanup_quoted not in readme_text:
                    missing.append("quoted-cleanup-cmd")
                leaked_bare: list[str] = []
                if validate_bare in readme_text:
                    leaked_bare.append("validate")
                if cleanup_bare in readme_text:
                    leaked_bare.append("cleanup")
                ok = not missing and not leaked_bare
                if not ok:
                    detail = (
                        f"missing={missing!r}; "
                        f"leaked_bare_unquoted={leaked_bare!r}"
                    )
        results.append(_ProbeResult(
            name="T8 shell-quoting of accepted spaces path",
            ok=ok, detail=detail,
        ))

    # T9 post-plan sidecar drift. Drives the helper through --plan-out
    # against the canonical synthetic bundle (so an approved plan is
    # written), then mutates the sidecar (swaps the first entry's
    # placement_role to the OTHER valid enum value, so the sidecar
    # itself still passes GP1..GP13 but the per-row plan comparison
    # is guaranteed to drift), then drives the helper through
    # --bundle + --out-dir + --approved-plan against the mutated
    # bundle. The helper MUST refuse with rc 2 BEFORE any mkdir or
    # pipeline subprocess fires; the trial proves this by asserting
    # the review_package directory does NOT exist on disk after the
    # refused run AND that the per-failure summary / deck / inventory
    # / visual_quality / workspace / reports artifacts the operator
    # mode normally writes are also absent. This locks the
    # "approved-plan run lock fails BEFORE any review_package artifact
    # is created" contract — a future helper regression that mkdir'd
    # the out-dir before the compare or emitted a partial artifact on
    # drift surfaces here as a per-artifact existence assertion.
    with tempfile.TemporaryDirectory(prefix="gen-img-trial-T9-") as raw_td:
        td = Path(raw_td)
        out_dir = td / "trial"
        out_dir.mkdir()
        bundle = out_dir / "bundle"
        approved_plan = out_dir / "approved_plan.json"
        review_package = out_dir / "review_package"

        _write_bundle(bundle)

        plan_outcome = _run(
            "T9 plan-out",
            [
                sys.executable, str(HELPER_PATH),
                "--bundle", str(bundle),
                "--plan-out", str(approved_plan),
            ],
        )
        plan_ok = plan_outcome.rc == 0 and approved_plan.is_file()

        # Mutate the sidecar AFTER the plan has been written so the
        # comparison drifts. Swapping placement_role between the two
        # valid enum values keeps the sidecar itself accepted by the
        # GP1..GP13 gates but guarantees the per-row plan compare
        # surfaces drift.
        sidecar_path = bundle / "generated_provenance.json"
        try:
            sidecar_body = json.loads(
                sidecar_path.read_text(encoding="utf-8"),
            )
            original_role = (
                sidecar_body["entries"][0]["placement_role"]
            )
            sidecar_body["entries"][0]["placement_role"] = (
                "local_region"
                if original_role != "local_region"
                else "hero_page"
            )
            sidecar_path.write_text(
                json.dumps(
                    sidecar_body, indent=2, sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            mutated_ok = True
            mutate_detail = ""
        except (OSError, ValueError, KeyError, IndexError) as exc:
            mutated_ok = False
            mutate_detail = (
                f"sidecar mutation failed: "
                f"{type(exc).__name__}: {exc}"
            )

        drift_outcome = _run(
            "T9 approved-plan after drift",
            [
                sys.executable, str(HELPER_PATH),
                "--bundle", str(bundle),
                "--out-dir", str(review_package),
                "--approved-plan", str(approved_plan),
            ],
        )

        # Every review-package artifact MUST be absent on a refused
        # drift run — the helper refuses BEFORE mkdir, so the
        # directory itself MUST NOT exist. Belt-and-braces: also
        # check the canonical per-file artifacts in case a future
        # regression that pre-created the directory still landed
        # nothing else under it (the directory-existence check would
        # already catch this, but the per-file list reads cleanly in
        # the failure detail).
        leaked_files = [
            name for name in _REVIEW_PACKAGE_FILES
            if (review_package / name).exists()
        ]
        leaked_dirs = [
            name for name in _REVIEW_PACKAGE_DIRS
            if (review_package / name).exists()
        ]

        ok = (
            plan_ok
            and mutated_ok
            and drift_outcome.rc == 2
            and not review_package.exists()
            and not leaked_files
            and not leaked_dirs
        )
        if ok:
            detail = ""
        else:
            detail = (
                f"plan_ok={plan_ok!r}; mutate_detail={mutate_detail!r}; "
                f"drift_rc={drift_outcome.rc!r}; "
                f"review_package.exists={review_package.exists()!r}; "
                f"leaked_files={leaked_files!r}; "
                f"leaked_dirs={leaked_dirs!r}"
            )
        results.append(_ProbeResult(
            name="T9 post-plan sidecar drift refuses before review_package",
            ok=ok, detail=detail,
        ))

    repo_rc = _check_repo_unchanged(snapshot_before=snapshot_before)

    print()
    print("--- self-test results ---")
    rc = 0
    for r in results:
        marker = "PASS" if r.ok else "FAIL"
        detail = f" ({r.detail})" if r.detail else ""
        print(f"  [{marker}] {r.name}{detail}")
        if not r.ok:
            rc = 1
    if repo_rc != 0:
        rc = 1
    if rc == 0:
        print()
        print(
            f"OK: every self-test probe passed; the committed "
            f"surface (examples / references / schemas / scripts / "
            f"templates / README.md / SKILL.md) was byte-identical "
            f"before and after; local-only (no D-One, MCP, Qoder, "
            f"model API, image search, public network, or telemetry)."
        )
    return rc


# ---------------------------------------------------------------------------
# CLI entrypoint.
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Operator-facing one-command trial for the "
            "generated-image bundle path through the full operator "
            "approval loop. Assembles a synthetic bundle under "
            "--out-dir carrying PNG + JPEG bytes, manifest.json, and "
            "the optional generated_provenance.json sidecar; invokes "
            "scripts/operator_local_images_to_editable_ppt.py "
            "--bundle <bundle> --plan-out <out-dir>/approved_plan.json "
            "to write the reviewer-approved plan; invokes the same "
            "helper with --bundle <bundle> --out-dir "
            "<out-dir>/review_package --approved-plan "
            "<out-dir>/approved_plan.json so the produced review "
            "package is gated behind the plan and the resulting "
            "summary records approved_plan.matched=true; invokes "
            "scripts/validate_operator_review_package.py --out-dir "
            "<out-dir>/review_package; writes a top-level README.md "
            "telling the operator to inspect approved_plan.json "
            "first, then review_package/README.md, then "
            "review_package/deck.pptx, plus the local-only boundary. "
            "Local-only — does NOT call D-One, MCP, Qoder, a public "
            "network, telemetry, a model API, an image search, or "
            "any external service. The sidecar's generator_source == "
            "\"mock_generated\" records declared operator intent for "
            "the staged synthetic bytes; it does NOT claim any "
            "external generator ran. NOT a full prompt / report / "
            "Markdown-to-PPTX automation."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--out-dir",
        help=(
            "Caller-supplied output directory outside the repo tree. "
            "Must not be URI-shaped, a symlink, or have a symlink "
            "ancestor; must not anchor under the repo tree; must have "
            "an existing parent; and must either be missing or an "
            "empty pre-existing directory (stale bytes on a refused "
            "path are preserved). On a clean run, the trial writes "
            "bundle/, approved_plan.json, review_package/, and "
            "README.md under this directory."
        ),
    )
    group.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run the trial under a per-run TMPDIR fixture plus every "
            "documented fail-closed probe (URI / symlink / "
            "symlink-ancestor / inside-REPO_ROOT / pre-existing "
            "non-empty --out-dir) and the post-plan sidecar drift "
            "probe (mutating the sidecar between --plan-out and "
            "--approved-plan refuses with rc 2 BEFORE any "
            "review_package artifact is created). No caller-visible "
            "artifacts retained; mutually exclusive with --out-dir."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return _run_self_tests()

    out_dir, failures = _validate_out_dir_arg(args.out_dir)
    if failures or out_dir is None:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 2

    if not out_dir.exists():
        try:
            out_dir.mkdir(parents=False, exist_ok=False)
        except OSError as exc:
            print(
                f"FAIL: cannot create --out-dir {out_dir}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 1

    return _run_trial(out_dir)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
