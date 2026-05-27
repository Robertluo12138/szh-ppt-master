"""Operator-facing one-command **trial** for the core local
image-to-editable-PPT lane.

Drives the existing
``scripts/operator_local_images_to_editable_ppt.py`` helper twice — once
in plan-only mode to write an approved plan, once in normal operator
mode under the same approved plan — into a caller-supplied directory
outside the repo, then re-checks the produced review package on disk
via ``scripts/validate_operator_review_package.py --out-dir <produced
review package>`` (read-only stdlib companion; never writes to the
package), leaves both on disk for a human reviewer to inspect, and
writes a concise top-level ``README.md`` that names the first artifacts
to open and records the validator rc + the read-only / local-only
nature of that re-check.

The helper remains the source of truth for every manifest / plan /
approved-plan / pipeline / contract / inventory / visual-quality
validation. This script only orchestrates the helper's real CLI path,
runs the read-only review-package validator over the helper's output,
and verifies that the key produced files exist; the helper's own
truth-checker still gates the run.

CLI shape::

    # Persistent trial that leaves the produced review package on disk:
    python3 scripts/operator_local_images_trial.py --out-dir DIR

    # Self-test (every scenario under TMPDIR; no caller-visible
    # artifacts retained):
    python3 scripts/operator_local_images_trial.py --self-test

``--out-dir`` is validated through
``core_image_to_editable_ppt_demo._validate_out_dir_arg`` so the same
URI / symlink / symlink-ancestor / repo-tree / non-empty refusals the
sibling helpers already enforce apply here too. Stale bytes on a
refused ``--out-dir`` are preserved (the script never deletes anything
under a refused path).

Local-only — does NOT call D-One, MCP, Qoder, a public network,
telemetry, a model API, an image search, or any external service. NOT
a full prompt / report / Markdown-to-PPTX automation. Real D-One
remains UNVERIFIED.
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
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

# Reuse the helper's own out-dir gate so the trial cannot diverge from
# the contract the helper enforces, and reuse the helper's tiny PNG /
# JPEG payloads + synthetic-image writer + locked boundaries tuple so
# the trial does not invent its own image-asset shape.
from core_image_to_editable_ppt_demo import (  # noqa: E402
    _validate_out_dir_arg,
)
from operator_local_images_to_editable_ppt import (  # noqa: E402
    _EXPLICIT_BOUNDARIES,
    _write_synthetic_images,
)

HELPER_PATH = SCRIPTS_DIR / "operator_local_images_to_editable_ppt.py"
VALIDATOR_PATH = SCRIPTS_DIR / "validate_operator_review_package.py"

# Files the helper writes under its --out-dir on a happy normal-mode
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
    """Drive the helper twice (plan-out, then normal mode under the
    approved plan) into ``out_dir`` and write the trial's top-level
    README. Returns 0 on success, 1 on any helper / verification
    failure. The helper itself leaves partial artifacts under
    ``<out_dir>/review_package/`` on failure — the trial does NOT
    delete them; an operator inspects the partial state directly.

    Caller MUST have already passed ``out_dir`` through
    ``_validate_out_dir_arg`` and confirmed it exists (the trial
    ``mkdir`` happens earlier in the entrypoint)."""
    images_dir = out_dir / "input_images"
    approved_plan = out_dir / "approved_plan.json"
    review_package = out_dir / "review_package"

    print(f"=== operator_local_images_trial ===")
    print(f"  out-dir:         {out_dir}")
    print(f"  images-dir:      {images_dir}")
    print(f"  approved-plan:   {approved_plan}")
    print(f"  review-package:  {review_package}")
    print()

    # Stage A — generate the synthetic image folder the helper will
    # discover. Uses the helper's own _write_synthetic_images so the
    # trial does not re-invent the magic-byte payloads.
    _write_synthetic_images(images_dir)
    discovered = sorted(p.name for p in images_dir.iterdir())
    print(f"--- synthetic images written ({len(discovered)}): "
          f"{discovered} ---")

    # Stage B — plan-out preflight. Writes the approved plan into the
    # trial's out-dir so step C can lock against it.
    plan_outcome = _run(
        "operator_local_images_to_editable_ppt --plan-out",
        [
            sys.executable, str(HELPER_PATH),
            "--images-dir", str(images_dir),
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
    print(f"  [PASS] approved plan written to {approved_plan}")

    # Stage C — normal operator mode under the approved-plan run lock.
    normal_outcome = _run(
        "operator_local_images_to_editable_ppt --out-dir --approved-plan",
        [
            sys.executable, str(HELPER_PATH),
            "--images-dir", str(images_dir),
            "--out-dir", str(review_package),
            "--approved-plan", str(approved_plan),
        ],
    )
    if normal_outcome.rc != 0:
        print(f"  [FAIL] operator helper rc={normal_outcome.rc}")
        _print_outcome_tail(normal_outcome)
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

    # Stage E — confirm the approved-plan run lock fired (defense in
    # depth — the helper's truth-checker already refused any summary
    # whose approved_plan block was wrong, so reaching rc==0 above
    # implies matched=True; the trial re-reads the file so a future
    # helper regression that returns 0 without writing the block
    # surfaces here too).
    summary_path = review_package / "summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"  [FAIL] could not parse summary.json: "
              f"{type(exc).__name__}: {exc}")
        return 1
    ap = summary.get("approved_plan")
    if not isinstance(ap, dict) or ap.get("matched") is not True:
        print(f"  [FAIL] summary.approved_plan.matched is not True "
              f"(approved_plan={ap!r})")
        return 1
    print(f"  [PASS] summary.approved_plan.matched=True "
          f"(path={ap.get('path')!r}, "
          f"sha256={ap.get('sha256', '')[:12]}...)")

    # Stage F — read-only stdlib re-check of the produced review
    # package via the companion validator. The validator never writes
    # to the package; it re-checks every locked summary field +
    # path-resolve gate + inventory / visual-quality / approved-plan
    # invariant the helper's own truth-checker enforced before exit,
    # so a tampered post-helper edit (or a future helper regression
    # that lets such an edit through) fails closed here too. Run
    # BEFORE the trial README write so the README can carry the
    # validator rc, and so a torn re-check cannot leave a
    # positive-looking README behind.
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

    # Stage G — concise top-level README pointing the operator at what
    # to open first. Written after every verification passes so a torn
    # run cannot leave a positive-looking README behind.
    trial_readme = out_dir / "README.md"
    trial_readme.write_text(
        _render_trial_readme(
            review_package=review_package,
            approved_plan=approved_plan,
            images_dir=images_dir,
            validator_rc=validator_outcome.rc,
        ),
        encoding="utf-8",
    )
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
    approved_plan: Path,
    images_dir: Path,
    validator_rc: int,
) -> str:
    """Render the trial's top-level operator-facing README. Names what
    landed where, which files to open first, and the rc of the
    read-only stdlib re-check the trial just ran over the produced
    review package."""
    return "\n".join([
        "# operator_local_images_trial — review package",
        "",
        "A one-command trial run of the core local image-to-editable-PPT "
        "lane. Open the files in the order below to confirm the lane "
        "produced a usable editable PPTX from synthetic local images.",
        "",
        "## What to open first",
        "",
        f"1. `{(review_package / 'README.md').relative_to(review_package.parent)}` — operator-facing review-package README "
        "written by the helper. Names every produced artifact and the "
        "approved-plan lock evidence.",
        f"2. `{(review_package / 'deck.pptx').relative_to(review_package.parent)}` — the produced editable PPTX. "
        "One cover slide per synthetic image; titles and shapes are "
        "native PowerPoint objects.",
        f"3. `{(review_package / 'summary.json').relative_to(review_package.parent)}` — compact summary. The "
        "`approved_plan` block confirms the run lock matched the "
        "reviewer-approved plan.",
        f"4. `{(review_package / 'inventory.json').relative_to(review_package.parent)}` — `inspect_pptx_inventory` "
        "readback over the produced PPTX.",
        f"5. `{(review_package / 'visual_quality.json').relative_to(review_package.parent)}` — `validate_visual_quality` "
        "report over the produced workspace.",
        f"6. `{(review_package / 'workspace').relative_to(review_package.parent)}/source_image_assets.json` — "
        "source-attached image registry the helper wrote into the "
        "production workspace.",
        f"7. `{(review_package / 'reports').relative_to(review_package.parent)}/` — `pipeline_report.{{json,txt}}` "
        "from the underlying `run_pipeline.py`.",
        "",
        "## How this trial was produced",
        "",
        f"- Synthetic local images: `{images_dir.name}/` (one PNG + one "
        "JPEG, magic-byte-valid, byte-distinct so each operator file "
        "maps to a distinct embedded `ppt/media/*` part).",
        f"- Reviewer-approved plan: `{approved_plan.name}` — written "
        "by `scripts/operator_local_images_to_editable_ppt.py "
        "--plan-out` against the synthetic images.",
        f"- Review package: `{review_package.name}/` — written by the "
        "same helper in normal operator mode under "
        "`--approved-plan`, so the plan-out / approved-plan loop is "
        "exercised end-to-end.",
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
        f"python3 scripts/validate_operator_review_package.py "
        f"--out-dir {review_package}",
        "```",
        "",
        "## Boundary statement",
        "",
        "Local-only. Does NOT call D-One, MCP, Qoder, a public "
        "network, telemetry, a model API, an image search, or any "
        "external service. Real D-One image generation remains "
        "UNVERIFIED. NOT a prompt / report / Markdown-to-PPTX "
        "automation.",
        "",
        "## Cleaning up",
        "",
        "When done inspecting, remove the trial directory directly:",
        "",
        "```",
        f"rm -rf {review_package.parent}",
        "```",
        "",
    ])


# ---------------------------------------------------------------------------
# Helpers reused by --self-test for repo-tree snapshotting.
# ---------------------------------------------------------------------------


def _snapshot_dir(d: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        out[str(p.relative_to(d))] = p.read_bytes()
    return out


def _check_repo_unchanged(
    *,
    examples_before: dict[str, bytes],
    scripts_before: dict[str, bytes],
) -> int:
    """Compare REPO_ROOT/examples + REPO_ROOT/scripts byte-snapshots
    pre/post the self-test. Returns 0 when byte-identical, 1
    otherwise."""
    rc = 0
    examples_after = _snapshot_dir(REPO_ROOT / "examples")
    if examples_before != examples_after:
        changed = sorted(
            k for k in set(examples_before) | set(examples_after)
            if examples_before.get(k) != examples_after.get(k)
        )
        print(
            f"FAIL: examples/ was mutated by self-test (changed: "
            f"{changed!r})",
            file=sys.stderr,
        )
        rc = 1
    scripts_after = _snapshot_dir(REPO_ROOT / "scripts")
    if scripts_before != scripts_after:
        changed = sorted(
            k for k in set(scripts_before) | set(scripts_after)
            if scripts_before.get(k) != scripts_after.get(k)
        )
        print(
            f"FAIL: scripts/ was mutated by self-test (changed: "
            f"{changed!r})",
            file=sys.stderr,
        )
        rc = 1
    return rc


@dataclass
class _ProbeResult:
    name: str
    ok: bool
    detail: str = ""


# ---------------------------------------------------------------------------
# Self-test entrypoint.
# ---------------------------------------------------------------------------


def _run_self_tests() -> int:
    print("=== operator_local_images_trial --self-test ===")
    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    scripts_before = _snapshot_dir(REPO_ROOT / "scripts")

    results: list[_ProbeResult] = []

    # T1 happy path: drive the trial into a per-run tempdir; confirm
    # the produced review package + trial README + approved-plan
    # evidence + helper-locked boundaries are all in place.
    with tempfile.TemporaryDirectory(prefix="op-trial-T1-") as raw_td:
        td = Path(raw_td)
        out_dir = td / "trial"
        rc = main(["--out-dir", str(out_dir)])
        ok = rc == 0
        detail = ""
        if ok:
            # Sanity check the produced review package + trial README +
            # absence of any positive D-One / MCP / Qoder / network /
            # model-API / image-search / telemetry claim in the
            # helper-written summary's locked boundary tuple.
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
            if ok and not (out_dir / "approved_plan.json").is_file():
                ok = False
                detail = "missing approved_plan.json"
            if ok and not (out_dir / "input_images").is_dir():
                ok = False
                detail = "missing input_images/"
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
                if ok:
                    ap = summary.get("approved_plan")
                    if not isinstance(ap, dict):
                        ok = False
                        detail = (
                            f"summary.approved_plan is not a dict: "
                            f"{ap!r}"
                        )
                    elif ap.get("matched") is not True:
                        ok = False
                        detail = (
                            f"summary.approved_plan.matched is not "
                            f"True: {ap!r}"
                        )
                if ok:
                    boundaries = summary.get("explicit_boundaries")
                    if list(_EXPLICIT_BOUNDARIES) != boundaries:
                        ok = False
                        detail = (
                            f"summary.explicit_boundaries drifted from "
                            f"the locked helper tuple"
                        )
                if ok:
                    if summary.get("real_d_one_status") != "UNVERIFIED":
                        ok = False
                        detail = (
                            f"summary.real_d_one_status != "
                            f"'UNVERIFIED' "
                            f"(got {summary.get('real_d_one_status')!r})"
                        )
                if ok:
                    # The trial README must record the on-disk
                    # re-validation rc the trial just ran via the
                    # read-only companion validator. Re-reading the
                    # README here locks the wiring in place — a future
                    # regression that skips the validator stage OR
                    # writes the README without the validator line
                    # surfaces as a T1 FAIL rather than as silent
                    # drift.
                    try:
                        readme_text = (out_dir / "README.md").read_text(
                            encoding="utf-8",
                        )
                    except OSError as exc:
                        ok = False
                        detail = (
                            f"trial README unreadable: "
                            f"{type(exc).__name__}: {exc}"
                        )
                    else:
                        if "validate_operator_review_package" not in readme_text:
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
            detail = f"main(--out-dir) rc={rc}"
        results.append(_ProbeResult(name="T1 happy path", ok=ok, detail=detail))

    # T2 OP1: URI-shaped --out-dir refused before any filesystem touch.
    with tempfile.TemporaryDirectory(prefix="op-trial-T2-") as raw_td:
        td = Path(raw_td)
        uri_out = "file:///" + str(td / "uri_out").lstrip("/")
        rc = main(["--out-dir", uri_out])
        ok = (
            rc == 2
            and not (td / "uri_out").exists()
            and not (Path("/" + uri_out.removeprefix("file:///"))).exists()
        )
        detail = "" if ok else f"rc={rc}; uri_out probe leaked filesystem"
        results.append(_ProbeResult(name="T2 OP1 URI refused", ok=ok, detail=detail))

    # T3 OP2: symlinked --out-dir refused.
    with tempfile.TemporaryDirectory(prefix="op-trial-T3-") as raw_td:
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
    with tempfile.TemporaryDirectory(prefix="op-trial-T4-") as raw_td:
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
    repo_inside = REPO_ROOT / "tmp_trial_inside_repo_tree"
    rc = main(["--out-dir", str(repo_inside)])
    ok = rc == 2 and not repo_inside.exists()
    detail = "" if ok else (
        f"rc={rc}; repo_inside.exists={repo_inside.exists()}"
    )
    results.append(_ProbeResult(name="T5 OP4 inside REPO_ROOT refused",
                                ok=ok, detail=detail))

    # T6 OP5: pre-existing non-empty --out-dir refused AND stale bytes
    # preserved byte-identical after the refusal.
    with tempfile.TemporaryDirectory(prefix="op-trial-T6-") as raw_td:
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
            # No new sibling artifacts created by the refused run.
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

    # T7 absence of D-One / MCP / network / model-API / image-search /
    # Qoder / telemetry indicators in the trial's own happy-path
    # output, the trial README, the helper-written review-package
    # README, and the helper-written summary.json. The locked boundary
    # tuple already passes T1; this probe confirms that no positive
    # success claim slipped past on a different surface (the trial's
    # own stdout + the trial README + the helper README).
    with tempfile.TemporaryDirectory(prefix="op-trial-T7-") as raw_td:
        td = Path(raw_td)
        out_dir = td / "trial"
        # Capture the trial's stdout via subprocess so the parent
        # process is not contaminated by another _run_trial print
        # stream.
        outcome = _run(
            "operator_local_images_trial --out-dir (T7 capture)",
            [sys.executable, str(Path(__file__).resolve()),
             "--out-dir", str(out_dir)],
        )
        positives = (
            "real d-one verified", "real d-one online",
            "real d-one succeeded", "d-one verified",
            "d-one online", "mcp call succeeded",
            "called mcp", "called qoder",
            "qoder run succeeded", "model api call",
            "called model api", "image search returned",
            "called image search", "public network call",
            "called the public network", "telemetry emitted",
            "telemetry sent", "telemetry call",
        )
        scanned: list[tuple[str, str]] = [
            ("trial stdout", outcome.stdout + outcome.stderr),
        ]
        try:
            scanned.append((
                "trial README",
                (out_dir / "README.md").read_text(encoding="utf-8"),
            ))
            scanned.append((
                "review-package README",
                (out_dir / "review_package" / "README.md").read_text(
                    encoding="utf-8",
                ),
            ))
            scanned.append((
                "summary.json",
                (out_dir / "review_package" / "summary.json").read_text(
                    encoding="utf-8",
                ),
            ))
        except OSError as exc:
            results.append(_ProbeResult(
                name="T7 no external-service claims",
                ok=False,
                detail=f"could not read surface: {exc!r}",
            ))
        else:
            offenders: list[tuple[str, str]] = []
            for label, text in scanned:
                lowered = text.lower()
                for positive in positives:
                    if positive in lowered:
                        offenders.append((label, positive))
            ok = outcome.rc == 0 and not offenders
            detail = "" if ok else (
                f"trial rc={outcome.rc}; offenders={offenders!r}"
            )
            results.append(_ProbeResult(
                name="T7 no external-service claims",
                ok=ok, detail=detail,
            ))

    repo_rc = _check_repo_unchanged(
        examples_before=examples_before,
        scripts_before=scripts_before,
    )

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
        print("OK: every self-test probe passed; REPO_ROOT/examples and "
              "REPO_ROOT/scripts byte-identical pre/post; local-only "
              "(no D-One, MCP, Qoder, model API, image search, public "
              "network, or telemetry).")
    return rc


# ---------------------------------------------------------------------------
# CLI entrypoint.
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Operator-facing one-command trial for the core local "
            "image-to-editable-PPT lane. Generates a tiny synthetic "
            "local image folder under --out-dir, runs "
            "scripts/operator_local_images_to_editable_ppt.py first "
            "with --plan-out and then in normal mode under "
            "--approved-plan, leaves the produced review package "
            "(deck.pptx, summary.json, README.md, inventory.json, "
            "visual_quality.json, workspace/, reports/) under "
            "--out-dir for a human reviewer to inspect, and writes a "
            "concise top-level README.md naming the first files to "
            "open. Local-only — does NOT call D-One, MCP, Qoder, a "
            "public network, telemetry, a model API, an image "
            "search, or any external service. NOT a full prompt / "
            "report / Markdown-to-PPTX automation."
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
            "input_images/, approved_plan.json, review_package/, and "
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
            "non-empty --out-dir). No caller-visible artifacts "
            "retained; mutually exclusive with --out-dir."
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
