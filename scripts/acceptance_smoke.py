#!/usr/bin/env python3
"""MVP acceptance smoke for the explicit-input pipeline.

Runs the implemented explicit-input flow against the synthetic authoring
trial bundle (``examples/synthetic_authoring_trial/``) into a temporary
output directory that lives OUTSIDE the committed example tree, then
asserts the produced PPTX, inventory, and visual-quality report agree
with the bundle's declared shape:

  1. ``scripts/validate_authoring_bundle.py`` — authoring preflight on
     the bundle's spec files (non-mutating, no workspace created).
  2. ``scripts/run_explicit_pipeline.py`` with ``--report-dir`` — Stage
     1-to-10 explicit-input orchestration; internally runs
     ``validate_workspace``, ``generate_render_models``,
     ``generate_svg_previews``, ``export_pptx``,
     ``validate_pptx_contract``, and ``inspect_pptx_inventory`` (the
     last writes ``<report-dir>/inventory.json``).
  3. ``scripts/validate_pptx_contract.py --pptx ... --expected-slide-count N``
     — belt-and-braces direct re-validation of the produced PPTX with
     the slide-count gate active.
  4. ``scripts/validate_visual_quality.py --workspace ... --output
     <report-dir>/visual_quality.json`` — non-mutating visual review
     against the prepared workspace; the deterministic JSON report is
     persisted alongside the pipeline reports so the smoke leaves a
     reviewable artifact, not just stdout.

Post-conditions (asserted only after every stage above has passed):

  - the final ``.pptx`` exists as a regular non-symlink file and is
    non-empty;
  - the same ``.pptx`` passes the contract validator with
    ``--expected-slide-count = len(deck_plan.slides)``;
  - ``<report-dir>/inventory.json`` is a regular non-symlink file whose
    JSON body carries ``ok == True``, ``findings == []``, the
    evidence-basis line
    ``"OOXML structure only; not proof of full PowerPoint editability"``,
    and a ``slide_count`` equal to the expected slide count;
  - ``<report-dir>/visual_quality.json`` is a regular non-symlink file
    and parses as JSON (the validator's own ERROR/WARN bookkeeping is
    captured at stage time; the post-condition only proves the report
    landed on disk).

**This is MVP acceptance smoke only — NOT full prompt/report/Markdown-to-
PPTX automation.** Every Stage-1-to-6 artifact's content still comes
from the bundle's already-authored JSON spec files; in live mode
(``run_smoke`` against ``--bundle``) the smoke script never extracts
business content from ``input/source.md``, never generates any image /
spec / slide body, never calls D-One / Qoder / any public network /
image generation / telemetry / external service / model API, and never
modifies files inside the repo (every output lands under
``--output-root`` or an auto-created temporary directory). The
``--self-test`` image-asset chain scenario (described below) delegates
to ``scripts/image_asset_acceptance_smoke.py --self-test`` which DOES
emit a single fixed magic-byte synthetic PNG payload (the delegated
smoke's synthetic bundle declares exactly one ``cover_accent`` image
at ``media/cover_accent.png``; ``run_d_one_generation`` in
``--allow-synthetic-bytes`` mode supports both PNG and JPEG, but this
smoke only exercises PNG today) under its own
``tempfile.TemporaryDirectory()`` — strictly local: no real D-One
call, no MCP, no public network, no model API, no image search, no
Qoder, no external service. The parent self-test never mutates files
under ``REPO_ROOT/examples/`` (final snapshot-diff scenario asserts
this).

Fail-closed: any stage exiting non-zero, or any post-condition failing,
aborts the smoke immediately and the script exits non-zero with a clear
per-stage / per-assertion diagnostic.

``--self-test`` exercises in-script tempfixture scenarios under
``tempfile.TemporaryDirectory()`` covering: the real-pipeline happy
path against ``examples/synthetic_authoring_trial`` (deck.pptx +
pipeline_report.{json,txt} + inventory.json + visual_quality.json all
land under the output/report location; inventory ok=true / findings=[]
/ slide_count=7 / exact evidence_basis line); missing bundle directory;
invalid bundle directory (missing required file); preflight failure
(corrupt slide_spec); explicit-pipeline failure (pre-existing non-empty
``<output_root>/workspace/``); PPTX-contract failure (injected stage 3
exit-1); inventory-post-condition failure (manufactured bad
inventory.json: ok=false / findings non-empty / wrong basis / wrong
slide_count); visual-quality failure (injected stage 4 exit-1); the
image-asset chain smoke (delegates to
``scripts/image_asset_acceptance_smoke.py --self-test``, which exercises
the explicit-input acceptance path with a synthetic two-slide bundle:
the d_one chain runs against a *staging* workspace
(``init_workspace`` + hand-written ``image_manifest.json`` per the
*direct-author workflow* at ``scripts/materialize_image_assets.py:14-47``)
through ``done_image_adapter`` -> ``run_d_one_generation`` (mock
``--allow-synthetic-bytes`` provider, fixed magic-byte-valid PNG
payload for the single ``cover_accent`` image declared in the
synthetic bundle; the runner also supports JPEG but this smoke does
not exercise it) -> ``materialize_image_assets`` (copy branch); then
``scripts/run_explicit_pipeline.py --assets-dir <staging>`` is
invoked once against a fresh *production* workspace + the same
d_one_local bundle and is expected to return rc=0. The staging
workspace already carries the materialized PNG bytes at
``<staging>/<local_path>``, so the orchestrator's
materialize_image_assets step (inserted between Stage 5 and Stage 6
when ``--assets-dir`` is passed) copies the bytes into the production
workspace before ``init_image_manifest`` (Stage 6) runs; the cascade
then completes Stages 1-10 in a single shot — no expected failure,
no manual recovery, no fallback to the Stage-7-to-10 prepared-
workspace runner. The delegated smoke adds
``scripts/validate_pptx_contract.py --expected-slide-count N`` +
``scripts/validate_visual_quality.py --workspace ... --output
<report-dir>/visual_quality.json`` as belt-and-braces validators and
asserts a SEPARATE post-condition contract on the produced artifacts:
the final ``.pptx`` exists as a non-empty regular non-symlink file,
embeds at least one ``ppt/media/<file>`` part whose extension is
``.png`` / ``.jpg`` / ``.jpeg``, carries no ``.rels`` Target with a
URI scheme prefix and no ``TargetMode='External'`` relationship; the
``<report-dir>/inventory.json`` parses with ``ok == True`` /
``findings == []`` / ``slide_count == len(deck_plan.slides)`` /
``len(media_parts) > 0`` / ``evidence_basis`` exactly equal to
``"OOXML structure only; not proof of full PowerPoint editability"``;
and ``<report-dir>/visual_quality.json`` exists as a regular
non-symlink file under the temp report directory and parses as JSON.
The delegated smoke also asserts the explicit-pipeline output
contains every documented success marker (``OK: explicit-input
end-to-end run succeeded``, ``[PASS] materialize_image_assets``,
``[PASS] init_image_manifest``) and NO expected-failure / recovery
wording, statically refuses any reference to the Stage-7-to-10
prepared-workspace runner in its own source body, and re-snapshots
``REPO_ROOT/examples/`` to refuse any byte-level change. **MOCK /
stub acceptance only — NOT real D-One integration; no public
network, no MCP, no model API, no image search, no Qoder.** This
scenario passes/fails the parent self-test on the delegated smoke's
exit code and a substring check on its stdout banner; the parent
does NOT re-verify the delegated post-conditions); inventory determinism (re-running
``inspect_pptx_inventory.py`` on the happy-path PPTX produces
byte-identical inventory bytes); and a snapshot-diff that proves no
file under ``REPO_ROOT/examples/`` was mutated by any scenario.

Stdlib-only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
TEMPLATE_ROOT = REPO_ROOT / "templates" / "layouts"
DEFAULT_BUNDLE = REPO_ROOT / "examples" / "synthetic_authoring_trial"

# Must match scripts/inspect_pptx_inventory.py::EVIDENCE_BASIS verbatim.
EXPECTED_EVIDENCE_BASIS = (
    "OOXML structure only; not proof of full PowerPoint editability"
)

# Top-level directories under REPO_ROOT that the smoke refuses as a
# destination for generated PPTX / reports / render_models / SVG. Two
# distinct reasons share one list:
#   * "examples" / "references" / "schemas" / "scripts" / "templates"
#     ship committed source bytes — writing generated output into any
#     of them would dirty the committed tree;
#   * ".git" carries git metadata (object database, refs, hooks,
#     index). Writing a workspace / .pptx / report into `.git/` can
#     corrupt the repository in ways that are hard to recover from
#     (an unexpected `objects/xx/yyy...` file, a clobbered `index`,
#     a hook script left in a half-written state). Even though `.git`
#     is not "committed bytes" in the source sense, it is the one
#     directory under REPO_ROOT we MUST keep generated output out of;
#   * ".claude" carries the user's Claude Code project state
#     (transcripts, memory, hook config). Writing generated PPTX or
#     report files into `.claude/` can clobber session bytes the
#     harness owns; the smoke has no business touching it.
# Gitignored locations under REPO_ROOT (e.g. tmp/, output/, projects/)
# and anywhere outside REPO_ROOT remain valid.
_REFUSED_TOP_LEVEL_DIR_NAMES: tuple[str, ...] = (
    ".claude",
    ".git",
    "examples",
    "references",
    "schemas",
    "scripts",
    "templates",
)

# RFC 3986 scheme prefix. Mirrors init_workspace.py's URI-shape guard: a
# string like "data:foo" / "s3:bucket/key" / "https://x" would otherwise
# be wrapped by Path() and `.mkdir(parents=True, exist_ok=True)` would
# happily create a literal `data:foo/` directory in CWD before any
# pipeline subprocess could see and refuse it.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Tiny no-op subprocess commands the --self-test uses to inject
# guaranteed pass / fail outcomes at individual stages without running
# the real (slow) pipeline. Production never sees these; they exist
# only to prove the smoke aborts at the stage it claims to abort at.
_PASS_CMD: list[str] = [sys.executable, "-c", "import sys; sys.exit(0)"]
_FAIL_CMD: list[str] = [sys.executable, "-c", "import sys; sys.exit(1)"]


@dataclass
class BundleSpec:
    """The CLI surface the smoke runs against. Mirrors what the
    ``examples/synthetic_authoring_trial/README.md`` documents."""
    source: Path
    plan_spec: Path
    design_system_spec: Path
    slide_specs_dir: Path
    image_manifest_spec: Path
    template_root: Path
    title: str
    audience: str
    objective: str
    source_id: str
    tone: str
    language: str
    approximate_slide_count: int


def _bundle_spec(bundle_dir: Path) -> BundleSpec:
    return BundleSpec(
        source=bundle_dir / "source.md",
        plan_spec=bundle_dir / "plan_spec.json",
        design_system_spec=bundle_dir / "design_system_spec.json",
        slide_specs_dir=bundle_dir / "slide_specs",
        image_manifest_spec=bundle_dir / "image_manifest_spec.json",
        template_root=TEMPLATE_ROOT,
        title="Synthetic Authoring Trial",
        audience="Internal pipeline smoke-test reviewers",
        objective=(
            "Exercise the explicit-input authoring bundle gate end-to-end "
            "on a synthetic, non-sensitive narrative."
        ),
        source_id="synthetic_trial_source",
        tone="neutral-professional",
        language="en",
        approximate_slide_count=7,
    )


def _validate_bundle(bundle_dir: Path) -> None:
    """Confirm the bundle ships every file the smoke forwards to the
    pipeline. The downstream gates would also catch a missing file with
    their own diagnostics, but checking up-front gives a single clear
    message and avoids a half-spawned subprocess chain."""
    if not bundle_dir.is_dir():
        raise SystemExit(f"FAIL: --bundle is not a directory: {bundle_dir}")
    fx = _bundle_spec(bundle_dir)
    for label, path, must_be_dir in (
        ("source", fx.source, False),
        ("plan-spec", fx.plan_spec, False),
        ("design-system-spec", fx.design_system_spec, False),
        ("slide-specs-dir", fx.slide_specs_dir, True),
        ("image-manifest-spec", fx.image_manifest_spec, False),
    ):
        if path.is_symlink():
            raise SystemExit(
                f"FAIL: bundle entry --{label} is a symlink (refused): {path}"
            )
        if must_be_dir and not path.is_dir():
            raise SystemExit(
                f"FAIL: bundle entry --{label} is not a directory: {path}"
            )
        if not must_be_dir and not path.is_file():
            raise SystemExit(
                f"FAIL: bundle entry --{label} is not a regular file: {path}"
            )


def _expected_slide_count(plan_spec: Path) -> int:
    """Read len(plan_spec.slides) so the expected slide count is
    derived from the bundle, not hardcoded — if the trial is ever
    re-shaped to a different slide count, the smoke follows along.

    Refuses cleanly via SystemExit("FAIL: ...") on every shape the
    smoke cannot recover from without a preflight: read errors, non-
    JSON content, non-object JSON root, missing or non-list ``slides``
    field, empty ``slides`` list. The authoring preflight stage (the
    smoke's stage 1) re-validates ``plan_spec.json`` against
    ``schemas/deck_plan.schema.json`` with a structured diagnostic;
    this helper only owns the up-front read/shape gate so a malformed
    plan_spec never crashes the smoke with a Python traceback BEFORE
    the preflight stage can run."""
    try:
        raw = plan_spec.read_text()
    except OSError as exc:
        raise SystemExit(
            f"FAIL: --bundle plan_spec.json is unreadable: {plan_spec} "
            f"({type(exc).__name__}: {exc}). Run "
            f"scripts/validate_authoring_bundle.py against the bundle "
            f"for the structured diagnostic."
        )
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"FAIL: --bundle plan_spec.json is not valid JSON: "
            f"{plan_spec} ({type(exc).__name__}: {exc}). Run "
            f"scripts/validate_authoring_bundle.py against the bundle "
            f"for the structured diagnostic."
        )
    if not isinstance(plan, dict):
        raise SystemExit(
            f"FAIL: --bundle plan_spec.json must be a JSON object; got "
            f"{type(plan).__name__} at {plan_spec}. Run "
            f"scripts/validate_authoring_bundle.py against the bundle "
            f"for the structured diagnostic."
        )
    slides = plan.get("slides")
    if not isinstance(slides, list) or not slides:
        raise SystemExit(
            f"FAIL: --bundle plan_spec.json does not declare a non-empty "
            f"slides[] list: {plan_spec}. Run "
            f"scripts/validate_authoring_bundle.py against the bundle "
            f"for the structured diagnostic."
        )
    return len(slides)


def _validate_output_root(output_root: Path) -> None:
    """Refuse output roots that the pipeline cannot use.

    The smoke owns these up-front checks so that an --output-root which
    would either dirty the committed tree OR crash before the pipeline
    can run is rejected with a clean diagnostic rather than a Python
    traceback. Downstream pipeline subprocesses each enforce their own
    safety gates against the workspace / output / report-dir paths the
    smoke derives from --output-root, so the smoke only owns the rules
    that fire BEFORE those subprocesses can be invoked:

      - URI-shaped --output-root (`data:foo`, `s3:bucket/key`,
        `https://x`, ...): Path() would wrap the literal string and
        `.mkdir(parents=True, exist_ok=True)` would happily create a
        directory whose name carries the scheme prefix in CWD; the
        pipeline subprocess would then refuse it for the URI shape,
        but only after the smoke had already polluted CWD. Mirrors
        init_workspace.py's --workspace URI-shape guard so the smoke
        and the pipeline agree on what a usable path looks like.
      - symlink --output-root: never silently followed (same anti-
        pattern run_pipeline.py forbids at --output / --report-dir).
      - pre-existing non-directory at --output-root: a regular file
        (or block device, pipe, ...) at that path would cause
        `mkdir(exist_ok=True)` to raise FileExistsError, because
        `exist_ok=True` only suppresses the error when the existing
        path is already a directory; the pipeline would never run.
      - --output-root that resolves inside a refused top-level
        directory under REPO_ROOT (examples/, references/, schemas/,
        scripts/, templates/, .git/, .claude/): the first five ship
        committed source bytes — writing generated PPTX / reports /
        render_models / SVG into them would dirty the committed tree.
        `.git/` carries git metadata (object database, refs, hooks,
        index); writing into it can corrupt the repository in ways
        that are hard to recover from. `.claude/` carries the user's
        Claude Code project state (transcripts, memory, hook config);
        writing generated bytes into it can clobber session state
        the harness owns. Gitignored locations under REPO_ROOT
        (tmp/, output/, projects/, ...) and anywhere outside
        REPO_ROOT remain valid.
      - --output-root equal to REPO_ROOT itself: a .pptx at the repo
        root would dirty the tree (the .gitignore ignores *.pptx,
        but render_models/, svg_previews/, etc. would still appear
        as untracked changes under REPO_ROOT and risk being
        committed).
    """
    if _URI_SCHEME_PREFIX.match(str(output_root)):
        raise SystemExit(
            f"FAIL: --output-root looks like a URI (refused): {output_root}. "
            f"The smoke only accepts local directory paths; the pipeline "
            f"would refuse a URI-shaped --workspace anyway."
        )
    if output_root.is_symlink():
        raise SystemExit(
            f"FAIL: --output-root is a symlink (refused): {output_root}"
        )
    if output_root.exists() and not output_root.is_dir():
        raise SystemExit(
            f"FAIL: --output-root exists and is not a directory (refused): "
            f"{output_root}. The smoke writes its workspace, output PPTX, "
            f"and report files under this path, so it must be a directory."
        )
    try:
        resolved = output_root.resolve()
    except OSError as exc:
        raise SystemExit(
            f"FAIL: --output-root could not be resolved: {output_root} "
            f"({type(exc).__name__}: {exc})"
        )
    repo_resolved = REPO_ROOT.resolve()
    # The repo-prefix comparison AND the first-component comparison
    # both use casefolded parts so a case-variant bypass is refused on
    # case-insensitive filesystems (macOS APFS, Windows NTFS by
    # default). Two distinct case-variant attacks exist and both must
    # be closed:
    #
    #   (1) Case-variant of a refused first component:
    #       `--output-root=/repo/.GIT/foo` — on case-insensitive FS,
    #       `.GIT/foo` and `.git/foo` are the SAME on-disk directory,
    #       but Path('/repo/.GIT/foo').resolve() preserves the input
    #       case rather than canonicalizing. A naive
    #       `resolved.relative_to(repo / '.git')` (pure string-prefix
    #       compare) says "not a match" while mkdir/write_bytes would
    #       still land inside the real `.git/`.
    #
    #   (2) Case-variant of the REPO prefix itself:
    #       `--output-root=/Users/Robert/.../szh-ppt-master/.git/foo`
    #       (capital R in `Robert` when the on-disk path is
    #       `/Users/robert/...`). Path.resolve() again preserves the
    #       input case for the prefix. A naive
    #       `resolved.relative_to(repo_resolved)` says "not in the
    #       subpath" (case mismatch in the prefix), the gate concludes
    #       "outside the repo entirely" and skips the refusal — yet
    #       the underlying case-insensitive FS still routes the write
    #       into the real `.git/`.
    #
    # We close (1) and (2) together by case-folding every path
    # component on both sides before any comparison. Display strings
    # use the original case so the diagnostic is still informative
    # about what the user typed.
    resolved_parts_cf = tuple(p.casefold() for p in resolved.parts)
    repo_parts_cf = tuple(p.casefold() for p in repo_resolved.parts)
    if resolved_parts_cf == repo_parts_cf:
        raise SystemExit(
            f"FAIL: --output-root must not be the repo root itself; got "
            f"{output_root} (resolved to {resolved}, case-folds to the "
            f"repo root {repo_resolved}). Use a subdirectory or a path "
            f"outside the repo."
        )
    repo_prefix_match = (
        len(resolved_parts_cf) > len(repo_parts_cf)
        and resolved_parts_cf[:len(repo_parts_cf)] == repo_parts_cf
    )
    if repo_prefix_match:
        # Original-case parts beyond the repo prefix; used for the
        # diagnostic so the user sees what they typed.
        inside_parts = resolved.parts[len(repo_parts_cf):]
        first = inside_parts[0]
        first_cf = first.casefold()
        for name in _REFUSED_TOP_LEVEL_DIR_NAMES:
            if first_cf != name.casefold():
                continue
            if name == ".git":
                why = (
                    "the .git/ directory carries git metadata (object "
                    "database, refs, hooks, index); writing generated "
                    "PPTX / reports / render_models / SVG into it can "
                    "corrupt the repository"
                )
            elif name == ".claude":
                why = (
                    "the .claude/ directory carries the user's Claude "
                    "Code project state (transcripts, memory, hook "
                    "config); writing generated bytes into it can "
                    "clobber session state the harness owns"
                )
            else:
                why = (
                    "this directory ships committed source bytes; "
                    "writing generated PPTX / reports / render_models / "
                    "SVG into it would dirty the committed tree"
                )
            raise SystemExit(
                f"FAIL: --output-root must not live inside the refused "
                f"top-level directory {repo_resolved / name}; got "
                f"{output_root} (resolved to {resolved}, first component "
                f"beyond the repo prefix is {first!r} which case-folds "
                f"to {first_cf!r} and matches the refused name {name!r}). "
                f"{why}."
            )


@dataclass
class StageOutcome:
    name: str
    cmd: list[str]
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _run_stage(name: str, cmd: list[str]) -> StageOutcome:
    """Spawn a stage as a subprocess so its own argparse / fail-closed
    gates / stdout-stderr cascade are exercised verbatim. The smoke
    runs from REPO_ROOT so relative paths inside subprocesses behave
    the same way they do when a user invokes the scripts directly."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    return StageOutcome(
        name=name,
        cmd=cmd,
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def _print_stage(stage: StageOutcome) -> None:
    mark = "PASS" if stage.ok else "FAIL"
    print(f"  [{mark}] {stage.name} (rc={stage.exit_code})")
    if not stage.ok:
        # On failure tail the streams so the cause is visible without
        # forcing the caller to re-run with --keep + extra inspection.
        tail = stage.stdout.splitlines()[-15:]
        if tail:
            print("    stdout tail:")
            for line in tail:
                print(f"      {line}")
        tail = stage.stderr.splitlines()[-15:]
        if tail:
            print("    stderr tail:")
            for line in tail:
                print(f"      {line}")


def _build_stage_commands(
    fx: BundleSpec,
    *,
    workspace: Path,
    pptx_out: Path,
    report_dir: Path,
    expected_slide_count: int,
) -> list[tuple[str, list[str]]]:
    py = sys.executable
    preflight = [
        py, str(SCRIPTS_DIR / "validate_authoring_bundle.py"),
        "--source", str(fx.source),
        "--source-id", fx.source_id,
        "--title", fx.title,
        "--audience", fx.audience,
        "--objective", fx.objective,
        "--tone", fx.tone,
        "--language", fx.language,
        "--approximate-slide-count", str(fx.approximate_slide_count),
        "--plan-spec", str(fx.plan_spec),
        "--design-system-spec", str(fx.design_system_spec),
        "--template-root", str(fx.template_root),
        "--slide-specs-dir", str(fx.slide_specs_dir),
        "--image-manifest-spec", str(fx.image_manifest_spec),
    ]
    pipeline = [
        py, str(SCRIPTS_DIR / "run_explicit_pipeline.py"),
        "--workspace", str(workspace),
        "--source", str(fx.source),
        "--source-id", fx.source_id,
        "--title", fx.title,
        "--audience", fx.audience,
        "--objective", fx.objective,
        "--tone", fx.tone,
        "--language", fx.language,
        "--approximate-slide-count", str(fx.approximate_slide_count),
        "--plan-spec", str(fx.plan_spec),
        "--design-system-spec", str(fx.design_system_spec),
        "--template-root", str(fx.template_root),
        "--slide-specs-dir", str(fx.slide_specs_dir),
        "--image-manifest-spec", str(fx.image_manifest_spec),
        "--output", str(pptx_out),
        "--report-dir", str(report_dir),
    ]
    contract = [
        py, str(SCRIPTS_DIR / "validate_pptx_contract.py"),
        "--pptx", str(pptx_out),
        "--expected-slide-count", str(expected_slide_count),
    ]
    # Persist the visual-quality JSON report alongside the pipeline's
    # own pipeline_report.{json,txt} + inventory.json so the smoke
    # leaves a reviewable artifact, not just stdout. The validator's
    # --output rules already refuse a path inside --workspace, a
    # symlink, and a URI scheme; <report_dir>/visual_quality.json is a
    # sibling of pipeline_report.{json,txt}/inventory.json, well
    # outside <workspace>.
    visual_quality_report = report_dir / "visual_quality.json"
    visual = [
        py, str(SCRIPTS_DIR / "validate_visual_quality.py"),
        "--workspace", str(workspace),
        "--output", str(visual_quality_report),
    ]
    return [
        ("authoring_preflight", preflight),
        ("explicit_pipeline", pipeline),
        ("validate_pptx_contract", contract),
        ("validate_visual_quality", visual),
    ]


@dataclass
class PostCondition:
    name: str
    ok: bool
    detail: str = ""


def _check_post_conditions(
    *,
    pptx_out: Path,
    report_dir: Path,
    expected_slide_count: int,
) -> list[PostCondition]:
    results: list[PostCondition] = []

    pptx_is_file = pptx_out.is_file() and not pptx_out.is_symlink()
    results.append(PostCondition(
        "PPTX exists as a regular non-symlink file",
        pptx_is_file,
        f"path={pptx_out}, is_file={pptx_out.is_file()}, "
        f"is_symlink={pptx_out.is_symlink()}",
    ))
    if pptx_is_file:
        size = pptx_out.stat().st_size
        results.append(PostCondition(
            "PPTX is non-empty",
            size > 0,
            f"size={size}",
        ))

    inv_path = report_dir / "inventory.json"
    inv_is_file = inv_path.is_file() and not inv_path.is_symlink()
    results.append(PostCondition(
        "inventory.json exists as a regular non-symlink file",
        inv_is_file,
        f"path={inv_path}, is_file={inv_path.is_file()}, "
        f"is_symlink={inv_path.is_symlink()}",
    ))
    if not inv_is_file:
        return results

    try:
        inv = json.loads(inv_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        results.append(PostCondition(
            "inventory.json parses as JSON",
            False,
            f"{type(exc).__name__}: {exc}",
        ))
        return results

    results.append(PostCondition(
        "inventory.ok is True",
        inv.get("ok") is True,
        f"got: {inv.get('ok')!r}",
    ))
    results.append(PostCondition(
        "inventory.findings is []",
        inv.get("findings") == [],
        f"got: {inv.get('findings')!r}",
    ))
    results.append(PostCondition(
        "inventory.evidence_basis matches the documented line",
        inv.get("evidence_basis") == EXPECTED_EVIDENCE_BASIS,
        f"expected: {EXPECTED_EVIDENCE_BASIS!r}; "
        f"got: {inv.get('evidence_basis')!r}",
    ))
    results.append(PostCondition(
        f"inventory.slide_count == {expected_slide_count}",
        inv.get("slide_count") == expected_slide_count,
        f"got: {inv.get('slide_count')!r}",
    ))

    # Visual-quality report persistence post-condition. The validator
    # writes its full ERROR/WARN bookkeeping into this file at stage
    # time; here we only prove the report landed on disk as a regular
    # non-symlink file and the JSON is parseable. Stage 4 already
    # exited non-zero (and aborted the smoke before we reach this
    # function) on any visual-quality ERROR finding, so the
    # parse-only post-condition is intentionally minimal.
    vq_path = report_dir / "visual_quality.json"
    vq_is_file = vq_path.is_file() and not vq_path.is_symlink()
    results.append(PostCondition(
        "visual_quality.json exists as a regular non-symlink file",
        vq_is_file,
        f"path={vq_path}, is_file={vq_path.is_file()}, "
        f"is_symlink={vq_path.is_symlink()}",
    ))
    if vq_is_file:
        try:
            json.loads(vq_path.read_text())
            vq_parses = True
            vq_detail = ""
        except (json.JSONDecodeError, OSError) as exc:
            vq_parses = False
            vq_detail = f"{type(exc).__name__}: {exc}"
        results.append(PostCondition(
            "visual_quality.json parses as JSON",
            vq_parses,
            vq_detail,
        ))
    return results


def run_smoke(
    bundle_dir: Path,
    output_root: Path,
    *,
    _stage_command_overrides: dict[str, list[str]] | None = None,
) -> int:
    """Run the four stages in order, then check post-conditions.

    Returns 0 on full pass, 1 on any stage failure or any failing
    post-condition. The workspace, PPTX, and report directory are
    derived from ``output_root`` and the bundle's shape; nothing under
    ``REPO_ROOT/examples/`` is mutated.

    ``_stage_command_overrides`` is a TEST-ONLY hook: when supplied, it
    maps stage names (``authoring_preflight`` / ``explicit_pipeline`` /
    ``validate_pptx_contract`` / ``validate_visual_quality``) to the
    subprocess command the smoke should run for that stage instead of
    the canonical one. The ``--self-test`` flow uses this to inject
    guaranteed pass/fail outcomes at individual stages without running
    the real (slow) pipeline; production callers must never pass it
    (the leading underscore + the keyword-only requirement make this
    explicit)."""
    fx = _bundle_spec(bundle_dir)
    expected = _expected_slide_count(fx.plan_spec)

    workspace = output_root / "workspace"
    pptx_out = output_root / "deck.pptx"
    report_dir = output_root / "report"

    print("=== MVP acceptance smoke ===")
    print(f"  bundle:       {bundle_dir.relative_to(REPO_ROOT) if bundle_dir.is_relative_to(REPO_ROOT) else bundle_dir}")
    print(f"  output_root:  {output_root}")
    print(f"  workspace:    {workspace}")
    print(f"  output PPTX:  {pptx_out}")
    print(f"  report dir:   {report_dir}")
    print(f"  expected:     {expected} slides")
    print()

    print("--- stages ---")
    stages = _build_stage_commands(
        fx,
        workspace=workspace,
        pptx_out=pptx_out,
        report_dir=report_dir,
        expected_slide_count=expected,
    )
    if _stage_command_overrides:
        stages = [
            (name, _stage_command_overrides.get(name, cmd))
            for (name, cmd) in stages
        ]
    for name, cmd in stages:
        outcome = _run_stage(name, cmd)
        _print_stage(outcome)
        if not outcome.ok:
            print(
                f"\nFAIL: stage {name!r} did not pass; aborting smoke "
                f"(no further stages run; post-conditions not checked).",
                file=sys.stderr,
            )
            return 1
    print()

    print("--- post-conditions ---")
    pconds = _check_post_conditions(
        pptx_out=pptx_out,
        report_dir=report_dir,
        expected_slide_count=expected,
    )
    fails = 0
    for pc in pconds:
        mark = "PASS" if pc.ok else "FAIL"
        suffix = f" -- {pc.detail}" if not pc.ok and pc.detail else ""
        print(f"  [{mark}] {pc.name}{suffix}")
        if not pc.ok:
            fails += 1
    print()

    if fails:
        print(
            f"FAIL: {fails} post-condition(s) did not hold; the pipeline "
            f"stages all reported PASS but the produced artifacts did not "
            f"match the smoke's contract.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: MVP acceptance smoke passed "
        f"(bundle={bundle_dir.name}, slides={expected})."
    )
    print(f"    PPTX:      {pptx_out}")
    print(f"    inventory: {report_dir / 'inventory.json'}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "MVP acceptance smoke: runs the explicit-input pipeline "
            "against the synthetic authoring trial bundle into a "
            "temporary output directory and verifies the final PPTX, "
            "inventory, and visual quality report. NOT a full prompt/"
            "report/Markdown-to-PPTX automation — every spec file the "
            "pipeline consumes is the trial's already-authored JSON."
        ),
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        default=DEFAULT_BUNDLE,
        help=(
            "Authoring bundle directory (defaults to "
            "examples/synthetic_authoring_trial). Must ship source.md, "
            "plan_spec.json, design_system_spec.json, slide_specs/, and "
            "image_manifest_spec.json."
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Directory under which the smoke writes its workspace, "
            "output PPTX, and report files. MUST NOT live inside a "
            "refused top-level directory under the repo "
            "(examples/, references/, schemas/, scripts/, "
            "templates/ — these ship committed source bytes; "
            ".git/ — git metadata, writing into it can corrupt the "
            "repository; .claude/ — the user's Claude Code project "
            "state, writing into it can clobber session bytes the "
            "harness owns). The goal of the smoke is to leave the "
            "committed tree, the git metadata directory, and the "
            "harness state all untouched. When omitted, a fresh "
            "tempfile.mkdtemp() directory is created and removed at "
            "exit (unless --keep is passed)."
        ),
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help=(
            "Preserve the output root after the smoke completes. When "
            "combined with the auto-created tempdir (no --output-root), "
            "prints the surviving path so the caller can inspect the "
            "produced artifacts. The smoke never deletes a caller-"
            "supplied --output-root."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run the in-script tempfixture scenarios (happy path; "
            "missing / invalid bundle; preflight / pipeline / "
            "pptx-contract / inventory-post-condition / visual-quality "
            "failures; image-asset D-One-stub chain smoke "
            "(scripts/image_asset_acceptance_smoke.py --self-test; "
            "MOCK / stub acceptance only — NOT real D-One "
            "integration); inventory determinism; no-mutation snapshot "
            "of examples/). Mutually exclusive with the orchestration "
            "flags so a caller cannot accidentally run the live smoke "
            "and the self-test at the same time."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        orchestration_args = (
            args.output_root,
            args.keep,
            args.bundle != DEFAULT_BUNDLE,
        )
        if any(orchestration_args):
            print(
                "FAIL: --self-test does not take any other argument",
                file=sys.stderr,
            )
            return 2
        return _run_self_tests()

    _validate_bundle(args.bundle)

    if args.output_root is not None:
        _validate_output_root(args.output_root)
        # `_validate_output_root` already refused pre-existing non-
        # directories at this path, but mkdir can still fail on
        # permission / parent-not-a-directory / read-only-mount /
        # full-disk states the smoke cannot probe without doing the
        # actual mkdir. Catch the OSError so the smoke surfaces a clean
        # FAIL diagnostic instead of a Python traceback.
        try:
            args.output_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(
                f"FAIL: could not create --output-root {args.output_root}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 2
        rc = run_smoke(args.bundle, args.output_root)
        if args.keep:
            print(f"\n(--keep) preserved output root: {args.output_root}")
        return rc

    # Auto-created tempdir, outside the repo by virtue of $TMPDIR.
    tmp_parent = Path(tempfile.mkdtemp(prefix="szh_acceptance_smoke_"))
    try:
        return run_smoke(args.bundle, tmp_parent)
    finally:
        if args.keep:
            print(f"\n(--keep) preserved output root: {tmp_parent}")
        else:
            shutil.rmtree(tmp_parent, ignore_errors=True)


# ---------------------------------------------------------------------------
# Self-test scenarios. Each runs under tempfile.TemporaryDirectory() and
# either invokes this script as a subprocess (so the real argparse + main()
# flow is exercised) OR calls run_smoke()/_check_post_conditions() in-process
# (for failure-mode injection that doesn't need to go through argparse).
# Fixtures never leak into the repo: every path lives under the TemporaryDirectory.
# ---------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    name: str
    ok: bool
    detail: str = ""


def _snapshot_dir(dir_path: Path) -> dict[str, bytes]:
    """Flat path -> bytes map of every regular file under ``dir_path``.

    Used to assert that committed example directories (``REPO_ROOT/
    examples/``) are not mutated by any scenario. Symlinks and non-
    regular files are skipped because they cannot meaningfully appear
    in a clean checkout of this repo; a future scenario that wanted to
    detect a stray symlink under ``examples/`` would need a different
    helper."""
    snapshot: dict[str, bytes] = {}
    if not dir_path.is_dir():
        return snapshot
    for p in sorted(dir_path.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(dir_path)
        snapshot[str(rel)] = p.read_bytes()
    return snapshot


def _invoke_smoke_subprocess(extra_args: list[str]) -> tuple[int, str]:
    """Spawn THIS script as a subprocess so the real argparse + main()
    flow is exercised. Returns ``(returncode, combined_stdout_stderr)``."""
    cmd = [sys.executable, str(Path(__file__).resolve())] + extra_args
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _scenario_happy_path(output_root: Path) -> ScenarioResult:
    """Real-pipeline happy path against ``examples/synthetic_authoring_trial``.

    Spawns the smoke as a subprocess so the actual CLI exit code is
    observed, then verifies every documented artifact lands on disk
    under ``output_root`` and the inventory's contract holds."""
    rc, captured = _invoke_smoke_subprocess([
        "--bundle", str(DEFAULT_BUNDLE),
        "--output-root", str(output_root),
    ])
    pptx = output_root / "deck.pptx"
    report_dir = output_root / "report"
    inv_path = report_dir / "inventory.json"
    pipeline_json = report_dir / "pipeline_report.json"
    pipeline_txt = report_dir / "pipeline_report.txt"
    visual_path = report_dir / "visual_quality.json"
    artifacts_ok = (
        pptx.is_file() and not pptx.is_symlink() and pptx.stat().st_size > 0
        and pipeline_json.is_file() and not pipeline_json.is_symlink()
        and pipeline_txt.is_file() and not pipeline_txt.is_symlink()
        and inv_path.is_file() and not inv_path.is_symlink()
        and visual_path.is_file() and not visual_path.is_symlink()
    )
    inv_contract_ok = False
    inv_detail = ""
    if inv_path.is_file():
        try:
            inv = json.loads(inv_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            inv = None
            inv_detail = f"{type(exc).__name__}: {exc}"
        if inv is not None:
            inv_contract_ok = (
                inv.get("ok") is True
                and inv.get("findings") == []
                and inv.get("slide_count") == 7
                and inv.get("evidence_basis") == EXPECTED_EVIDENCE_BASIS
            )
            if not inv_contract_ok:
                inv_detail = (
                    f"ok={inv.get('ok')!r}, findings={inv.get('findings')!r}, "
                    f"slide_count={inv.get('slide_count')!r}, "
                    f"evidence_basis={inv.get('evidence_basis')!r}"
                )
    ok = rc == 0 and artifacts_ok and inv_contract_ok
    return ScenarioResult(
        "happy path: real pipeline against examples/synthetic_authoring_trial "
        "produces deck.pptx + pipeline_report.{json,txt} + inventory.json + "
        "visual_quality.json under output/report; inventory carries ok=true / "
        "findings=[] / slide_count=7 / exact evidence_basis line",
        ok,
        (f"rc={rc}, artifacts_ok={artifacts_ok}, "
         f"inv_contract_ok={inv_contract_ok}, inv_detail={inv_detail!r}"
         if not ok else ""),
    )


def _scenario_missing_bundle(td: Path) -> ScenarioResult:
    """Smoke must refuse a non-existent bundle directory before any
    stage runs."""
    bundle = td / "scenario_missing_bundle" / "does_not_exist"
    output_root = td / "scenario_missing_bundle" / "output_root"
    rc, captured = _invoke_smoke_subprocess([
        "--bundle", str(bundle),
        "--output-root", str(output_root),
    ])
    no_artifacts = not output_root.exists() or not any(output_root.iterdir())
    ok = (
        rc != 0
        and "--bundle is not a directory" in captured
        and no_artifacts
    )
    return ScenarioResult(
        "missing bundle: --bundle pointing at a non-existent directory "
        "fails closed before any stage runs (no artifacts written)",
        ok,
        (f"rc={rc}, no_artifacts={no_artifacts}, "
         f"captured_tail={captured.splitlines()[-3:]!r}"
         if not ok else ""),
    )


def _scenario_invalid_bundle(td: Path) -> ScenarioResult:
    """Smoke must refuse a bundle directory that is missing a required
    file (here: ``source.md``). The downstream gates would also catch
    the absence eventually, but the smoke's up-front
    ``_validate_bundle`` should report it cleanly first."""
    bundle = td / "scenario_invalid_bundle" / "bundle"
    bundle.mkdir(parents=True)
    # Create everything except source.md so the gate fires on source.md.
    (bundle / "plan_spec.json").write_text("{}\n")
    (bundle / "design_system_spec.json").write_text("{}\n")
    (bundle / "slide_specs").mkdir()
    (bundle / "image_manifest_spec.json").write_text("{}\n")
    output_root = td / "scenario_invalid_bundle" / "output_root"
    rc, captured = _invoke_smoke_subprocess([
        "--bundle", str(bundle),
        "--output-root", str(output_root),
    ])
    no_artifacts = not output_root.exists() or not any(output_root.iterdir())
    ok = (
        rc != 0
        and "bundle entry --source is not a regular file" in captured
        and no_artifacts
    )
    return ScenarioResult(
        "invalid bundle: --bundle missing source.md fails closed before "
        "any stage runs (no artifacts written)",
        ok,
        (f"rc={rc}, no_artifacts={no_artifacts}, "
         f"captured_tail={captured.splitlines()[-3:]!r}"
         if not ok else ""),
    )


def _scenario_malformed_plan_spec(td: Path) -> ScenarioResult:
    """The smoke reads ``<bundle>/plan_spec.json`` BEFORE stage 1
    (preflight) runs, to derive the expected slide count for the
    contract validator's --expected-slide-count gate. A malformed
    plan_spec.json must fail closed with a clean FAIL diagnostic — NOT
    a Python traceback — and must abort before any stage runs, so no
    workspace / PPTX / report files are written."""
    bundle = td / "scenario_malformed_plan_spec" / "bundle"
    shutil.copytree(DEFAULT_BUNDLE, bundle)
    (bundle / "plan_spec.json").write_text("{ this is intentionally not JSON")
    output_root = td / "scenario_malformed_plan_spec" / "output_root"
    rc, captured = _invoke_smoke_subprocess([
        "--bundle", str(bundle),
        "--output-root", str(output_root),
    ])
    no_traceback = "Traceback (most recent call last)" not in captured
    no_pptx = not (output_root / "deck.pptx").exists()
    no_report_files = not (output_root / "report").exists() or not any(
        (output_root / "report").iterdir()
    )
    ok = (
        rc != 0
        and "plan_spec.json is not valid JSON" in captured
        and no_traceback
        and no_pptx
        and no_report_files
    )
    return ScenarioResult(
        "malformed plan_spec: --bundle plan_spec.json with non-JSON "
        "content fails closed BEFORE the preflight stage with a clean "
        "FAIL diagnostic (no Python traceback); no workspace / PPTX / "
        "report files are written",
        ok,
        (f"rc={rc}, no_traceback={no_traceback}, no_pptx={no_pptx}, "
         f"no_report_files={no_report_files}, "
         f"captured_tail={captured.splitlines()[-3:]!r}"
         if not ok else ""),
    )


def _scenario_preflight_failure(td: Path) -> ScenarioResult:
    """Real authoring preflight failure: copy the trial bundle to a
    tempdir and corrupt one slide_spec to be malformed JSON. The
    smoke's stage 1 (authoring_preflight) must FAIL, stages 2-4 must
    not run, and no deck.pptx / inventory.json / visual_quality.json
    is produced."""
    bundle = td / "scenario_preflight_failure" / "bundle"
    shutil.copytree(DEFAULT_BUNDLE, bundle)
    (bundle / "slide_specs" / "01_cover.json").write_text(
        "{ this is intentionally not valid JSON"
    )
    output_root = td / "scenario_preflight_failure" / "output_root"
    rc, captured = _invoke_smoke_subprocess([
        "--bundle", str(bundle),
        "--output-root", str(output_root),
    ])
    no_pptx = not (output_root / "deck.pptx").exists()
    no_inv = not (output_root / "report" / "inventory.json").exists()
    no_vq = not (output_root / "report" / "visual_quality.json").exists()
    ok = (
        rc != 0
        and "[FAIL] authoring_preflight" in captured
        and "stage 'authoring_preflight' did not pass" in captured
        and no_pptx and no_inv and no_vq
    )
    return ScenarioResult(
        "preflight failure: corrupt slide_spec JSON aborts at stage 1 "
        "(authoring_preflight); no deck.pptx / inventory.json / "
        "visual_quality.json is written",
        ok,
        (f"rc={rc}, no_pptx={no_pptx}, no_inv={no_inv}, no_vq={no_vq}"
         if not ok else ""),
    )


def _scenario_pipeline_failure(td: Path) -> ScenarioResult:
    """Real explicit-pipeline failure: pre-populate
    ``<output_root>/workspace/`` with a junk file so the pipeline's
    Stage-1 ``init_workspace.py`` refuses the non-empty workspace.
    Preflight (stage 1) passes against the clean bundle; the pipeline
    subprocess (stage 2) exits non-zero; the smoke aborts at stage 2."""
    output_root = td / "scenario_pipeline_failure" / "output_root"
    output_root.mkdir(parents=True)
    workspace_dir = output_root / "workspace"
    workspace_dir.mkdir()
    (workspace_dir / "stale.txt").write_text("stale workspace content\n")
    rc, captured = _invoke_smoke_subprocess([
        "--bundle", str(DEFAULT_BUNDLE),
        "--output-root", str(output_root),
    ])
    no_pptx = not (output_root / "deck.pptx").exists()
    no_inv = not (output_root / "report" / "inventory.json").exists()
    ok = (
        rc != 0
        and "[FAIL] explicit_pipeline" in captured
        and "stage 'explicit_pipeline' did not pass" in captured
        and no_pptx
        and no_inv
    )
    return ScenarioResult(
        "pipeline failure: pre-existing non-empty <output_root>/workspace/ "
        "aborts at stage 2 (init_workspace refuses non-empty workspace); "
        "no deck.pptx or inventory.json is written by the smoke",
        ok,
        (f"rc={rc}, no_pptx={no_pptx}, no_inv={no_inv}"
         if not ok else ""),
    )


def _scenario_pptx_contract_failure(td: Path) -> ScenarioResult:
    """Inject a stage-3 (validate_pptx_contract) failure. Stages 1-2
    are also overridden to pass instantly so the test does not run the
    real (slow) pipeline; the only thing this scenario proves is that
    a non-zero stage-3 exit aborts the smoke at stage 3."""
    output_root = td / "scenario_pptx_contract_failure"
    output_root.mkdir()
    overrides = {
        "authoring_preflight": _PASS_CMD,
        "explicit_pipeline": _PASS_CMD,
        "validate_pptx_contract": _FAIL_CMD,
    }
    rc = run_smoke(
        DEFAULT_BUNDLE, output_root,
        _stage_command_overrides=overrides,
    )
    ok = rc != 0
    return ScenarioResult(
        "pptx contract failure: stage 3 (validate_pptx_contract) "
        "returning non-zero aborts the smoke at stage 3 (no further "
        "stages or post-conditions checked)",
        ok,
        f"rc={rc}" if not ok else "",
    )


def _scenario_inventory_post_condition_failure(td: Path) -> ScenarioResult:
    """Direct test of ``_check_post_conditions`` against a manufactured
    bad inventory.json. Every inventory contract violation
    (``ok=false`` / non-empty ``findings`` / wrong ``evidence_basis``
    / wrong ``slide_count``) must produce a failing post-condition;
    in the live smoke flow this means the smoke would return non-zero
    after all four stages pass."""
    report_dir = td / "scenario_inventory_post_failure" / "report"
    report_dir.mkdir(parents=True)
    pptx = td / "scenario_inventory_post_failure" / "deck.pptx"
    # 22-byte empty ZIP central-directory record + EOCD. The post-
    # condition only checks ``is_file`` / ``stat.st_size > 0``; it does
    # not parse the PPTX (validate_pptx_contract is what runs at stage
    # time, and it ran and PASSED upstream of this hypothetical).
    pptx.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    (report_dir / "inventory.json").write_text(json.dumps({
        "ok": False,
        "findings": [{
            "severity": "error",
            "code": "test.post_condition_failure",
            "part": "x",
            "detail": "synthesized bad inventory for the self-test only",
        }],
        "evidence_basis": "deliberately wrong evidence_basis text",
        "slide_count": 99,
    }) + "\n")
    # Also produce visual_quality.json so the visual-quality post-
    # conditions don't shadow the inventory failures with their own
    # FAILs. The two visual-quality post-conditions PASS in this
    # scenario; the inventory ones FAIL.
    (report_dir / "visual_quality.json").write_text("{}\n")
    pconds = _check_post_conditions(
        pptx_out=pptx,
        report_dir=report_dir,
        expected_slide_count=7,
    )
    failed = {pc.name for pc in pconds if not pc.ok}
    expected = {
        "inventory.ok is True",
        "inventory.findings is []",
        "inventory.evidence_basis matches the documented line",
        "inventory.slide_count == 7",
    }
    ok = expected.issubset(failed)
    return ScenarioResult(
        "inventory failure: _check_post_conditions catches every "
        "inventory contract violation (ok=false; findings non-empty; "
        "wrong evidence_basis; wrong slide_count) so the smoke "
        "returns non-zero even when all four stages pass",
        ok,
        f"failed_post_conditions={sorted(failed)}" if not ok else "",
    )


def _scenario_image_asset_chain(td: Path) -> ScenarioResult:
    """Invoke ``scripts/image_asset_acceptance_smoke.py --self-test`` as
    a subprocess so the existing-input authoring-trial smoke and the
    D-One-stub chain smoke share one verification entry point.

    The invoked script runs entirely under its own
    ``tempfile.TemporaryDirectory()``. The chain it exercises:

      1. d_one chain in a *staging* workspace (init_workspace +
         hand-written ``image_manifest.json`` with ``d_one_local``
         entries — the direct-author workflow at
         scripts/materialize_image_assets.py:14–47) ->
         ``done_image_adapter`` -> ``run_d_one_generation``
         (``--allow-synthetic-bytes``) -> ``materialize_image_assets``;
      2. ``scripts/run_explicit_pipeline.py --assets-dir <staging>``
         against a fresh *production* workspace + the same
         ``d_one_local`` bundle: the orchestrator's
         materialize_image_assets step (Stage 5.5, only present when
         ``--assets-dir`` is passed) copies the staged bytes from
         ``<staging>/<local_path>`` into
         ``<workspace>/<local_path>`` so init_image_manifest (Stage 6)
         finds them, and the cascade then completes Stages 1-10 in one
         invocation with rc=0 — no expected failure, no manual
         recovery;
      3. belt-and-braces ``scripts/validate_pptx_contract.py
         --expected-slide-count N`` + ``scripts/validate_visual_quality.py
         --output <report-dir>/visual_quality.json``;
      4. post-conditions: PPTX embeds at least one
         ppt/media/<file>.{png|jpg|jpeg}, no external / file:// /
         data: relationships, inventory.json ok=true / findings=[] /
         slide_count == len(deck_plan.slides) / media_parts non-empty
         / exact evidence_basis line; visual_quality.json exists as
         a regular non-symlink file and parses as JSON; the
         explicit-pipeline output carries every success marker and NO
         expected-failure / recovery wording.

    **Mock / stub acceptance only — NOT real D-One integration.** The
    invoked script's own examples/-snapshot gate proves no generated
    artifact lands in any committed example directory; we don't
    double-check it here. ``td`` is unused (the invoked script owns
    its own tempdir) — kept in the signature so this scenario matches
    the other ``td``-receiving scenarios in the suite."""
    del td  # invoked script owns its own tempdir
    rc, captured = _invoke_image_asset_smoke()
    ok = (
        rc == 0
        and "image-asset acceptance smoke passed" in captured
        and "MOCK D-One chain only" in captured
        and "Traceback (most recent call last)" not in captured
    )
    return ScenarioResult(
        "image-asset chain: d_one_local image_manifest entries -> "
        "done_image_adapter -> run_d_one_generation (mock --allow-"
        "synthetic-bytes) -> materialize_image_assets -> "
        "run_explicit_pipeline.py --assets-dir <staging> (one shot, "
        "rc=0; materialize_image_assets step + init_image_manifest "
        "both PASS) -> validate_pptx_contract -> "
        "validate_visual_quality -> inventory passes end-to-end; "
        "PPTX embeds ppt/media PNG; no external / file:// / data: "
        "rels; inventory ok=true / findings=[] / slide_count matches "
        "deck_plan / media_parts non-empty / exact evidence_basis "
        "line; visual_quality.json exists and parses. MOCK / stub "
        "acceptance only — NOT real D-One integration",
        ok,
        (f"rc={rc}, "
         f"captured_tail={captured.splitlines()[-5:]!r}"
         if not ok else ""),
    )


def _invoke_image_asset_smoke() -> tuple[int, str]:
    """Spawn scripts/image_asset_acceptance_smoke.py --self-test as a
    subprocess. Returns ``(returncode, combined_stdout_stderr)``."""
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "image_asset_acceptance_smoke.py"),
        "--self-test",
    ]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _scenario_visual_quality_failure(td: Path) -> ScenarioResult:
    """Inject a stage-4 (validate_visual_quality) failure. Stages 1-3
    are also overridden to pass instantly so the test does not run the
    real (slow) pipeline; this scenario proves that a non-zero stage-4
    exit aborts the smoke at stage 4 (no post-conditions checked)."""
    output_root = td / "scenario_visual_quality_failure"
    output_root.mkdir()
    overrides = {
        "authoring_preflight": _PASS_CMD,
        "explicit_pipeline": _PASS_CMD,
        "validate_pptx_contract": _PASS_CMD,
        "validate_visual_quality": _FAIL_CMD,
    }
    rc = run_smoke(
        DEFAULT_BUNDLE, output_root,
        _stage_command_overrides=overrides,
    )
    ok = rc != 0
    return ScenarioResult(
        "visual quality failure: stage 4 (validate_visual_quality) "
        "returning non-zero aborts the smoke at stage 4 (no post-"
        "conditions checked)",
        ok,
        f"rc={rc}" if not ok else "",
    )


def _case_variant_repo_root() -> Path | None:
    """Return a case-variant of REPO_ROOT.resolve() whose lower-case
    form is identical to REPO_ROOT.resolve() but whose string form
    differs in at least one alphabetic character. Returns None when no
    alphabetic character is found in the path (vanishingly unlikely on
    any real filesystem). The variant is built by flipping the case of
    every alphabetic character in the path's string form — that gives
    the maximum chance of catching a string-prefix comparison that
    only checks one segment."""
    s = str(REPO_ROOT.resolve())
    flipped = s.swapcase()
    if flipped == s:
        return None
    return Path(flipped)


def _scenario_refused_output_root_case_variant_repo_prefix() -> ScenarioResult:
    """Exercise attack (2) above: case-variant of the REPO prefix
    itself (e.g. `/Users/Robert/.../szh-ppt-master/.git/foo` instead
    of `/Users/robert/...`). On a case-insensitive filesystem
    (macOS APFS, Windows NTFS) this points at the SAME on-disk
    directory as the canonical-case path, so the gate must refuse it
    even though a naive `Path.relative_to(repo_resolved)` would raise
    ValueError (case mismatch in the prefix) and incorrectly conclude
    "outside the repo entirely".

    On a case-sensitive filesystem the case-variant prefix points at
    a different (non-existent) directory and `Path.resolve()` returns
    a path the case-folded repo-prefix check still won't match — so
    the gate skips the refusal and the path is accepted, which is
    fine: no real `.git/` is at risk because the case-sensitive FS
    would have created a brand-new `/Users/Robert/` directory.
    Either way, the gate does not silently allow a write into the
    real refused directory.
    """
    variant_repo = _case_variant_repo_root()
    label = (
        "--output-root with case-variant REPO prefix "
        "(e.g. /Users/Robert/... instead of /Users/robert/...) descending "
        "into .git/ is refused on case-insensitive filesystems; the "
        "case-folded repo-prefix comparison catches the bypass"
    )
    if variant_repo is None:
        return ScenarioResult(
            label, True,
            "no alphabetic character in repo path; skip",
        )
    probe = variant_repo / ".git" / "szh_acceptance_smoke_refusal_probe"
    # Test whether the filesystem is case-insensitive by checking if
    # the case-variant prefix still names the real repo on disk.
    case_insensitive_fs = variant_repo.exists() and (
        variant_repo.resolve() == REPO_ROOT.resolve()
        or str(variant_repo.resolve()).casefold()
        == str(REPO_ROOT.resolve()).casefold()
    )
    try:
        _validate_output_root(probe)
    except SystemExit as exc:
        msg = str(exc)
        ok = (
            "must not live inside the refused top-level directory" in msg
            and ".git" in msg
            and not probe.exists()
        )
        return ScenarioResult(
            label, ok,
            f"msg={msg[:250]!r}, probe_exists={probe.exists()}"
            if not ok else "",
        )
    if case_insensitive_fs:
        return ScenarioResult(
            label, False,
            f"case-insensitive FS detected (variant_repo={variant_repo} "
            f"resolves into the same on-disk repo as REPO_ROOT) but "
            f"_validate_output_root did NOT raise for {probe} — the "
            f"case-variant repo-prefix bypass is still open",
        )
    # Case-sensitive filesystem: case-variant prefix points at a
    # different directory (does not exist), gate correctly skipped
    # because the resolved path is genuinely outside the real repo.
    return ScenarioResult(
        label, True,
        "case-sensitive FS detected; gate correctly skipped the case-"
        "variant prefix because it points at a different (non-existent) "
        "on-disk directory",
    )


def _scenario_refused_output_root_case_variant_repo_root() -> ScenarioResult:
    """Same attack (2) but the supplied path IS the repo root itself
    with case-variant prefix. The repo-root-itself check must use a
    case-folded comparison; the previous `resolved == repo_resolved`
    check would have missed `/Users/Robert/.../szh-ppt-master`."""
    variant_repo = _case_variant_repo_root()
    label = (
        "--output-root equal to a case-variant of REPO_ROOT (e.g. "
        "/Users/Robert/... instead of /Users/robert/...) is refused on "
        "case-insensitive filesystems via case-folded repo-root "
        "comparison"
    )
    if variant_repo is None:
        return ScenarioResult(
            label, True,
            "no alphabetic character in repo path; skip",
        )
    case_insensitive_fs = variant_repo.exists() and (
        variant_repo.resolve() == REPO_ROOT.resolve()
        or str(variant_repo.resolve()).casefold()
        == str(REPO_ROOT.resolve()).casefold()
    )
    try:
        _validate_output_root(variant_repo)
    except SystemExit as exc:
        msg = str(exc)
        ok = "must not be the repo root itself" in msg
        return ScenarioResult(label, ok, f"msg={msg[:250]!r}" if not ok else "")
    if case_insensitive_fs:
        return ScenarioResult(
            label, False,
            f"case-insensitive FS detected but _validate_output_root "
            f"did NOT raise for case-variant repo root {variant_repo}",
        )
    return ScenarioResult(
        label, True,
        "case-sensitive FS detected; gate correctly skipped the case-"
        "variant repo root because it is a different (non-existent) "
        "on-disk directory",
    )


def _scenario_refused_output_root(
    path_component: str,
    canonical_name: str,
    why_substr: str,
) -> ScenarioResult:
    """Pass an `--output-root` that resolves inside one of the refused
    top-level directories under REPO_ROOT and assert
    ``_validate_output_root`` raises ``SystemExit`` with the right why-
    fragment in the diagnostic.

    ``path_component`` is the directory name the user typed (may be a
    case-variant of ``canonical_name`` to exercise the case-folded
    comparison). ``canonical_name`` is the lowercased entry in
    ``_REFUSED_TOP_LEVEL_DIR_NAMES`` that the diagnostic should name
    as the matched refused name. ``why_substr`` is a substring of the
    per-reason "why" line. The probe path is never created — the gate
    runs in-memory only — so no bytes land in the refused location
    even if the gate were accidentally removed; on a case-insensitive
    filesystem (macOS APFS, Windows NTFS) a probe of ``.GIT/foo``
    points at the SAME on-disk directory as ``.git/foo``, so the
    ``not probe.exists()`` check catches both the "gate fired and
    blocked the write" and the "gate did not fire but something else
    happened to not write" cases.
    """
    probe = REPO_ROOT / path_component / "szh_acceptance_smoke_refusal_probe"
    label = (
        f"--output-root inside {path_component}/ refused with the "
        f"'{why_substr}' diagnostic (case-folds to "
        f"{canonical_name}); probe path never created"
    )
    try:
        _validate_output_root(probe)
    except SystemExit as exc:
        msg = str(exc)
        ok = (
            "must not live inside the refused top-level directory" in msg
            and canonical_name in msg
            and why_substr in msg
            and not probe.exists()
        )
        return ScenarioResult(
            label,
            ok,
            f"msg={msg!r}, probe_exists={probe.exists()}" if not ok else "",
        )
    return ScenarioResult(
        label,
        False,
        f"_validate_output_root did NOT raise for {probe}",
    )


def _scenario_inventory_determinism(
    td: Path,
    happy_pptx: Path,
    happy_inventory: Path,
) -> ScenarioResult:
    """Re-invoke ``inspect_pptx_inventory.py`` on the happy-path PPTX
    and compare byte-for-byte against the inventory.json the smoke
    produced. The inventory writer sorts keys and findings, so two
    independent runs against the same PPTX must produce byte-identical
    inventory bytes."""
    second_inv = td / "scenario_determinism" / "inventory2.json"
    second_inv.parent.mkdir(parents=True)
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "inspect_pptx_inventory.py"),
        "--pptx", str(happy_pptx),
        "--out", str(second_inv),
    ]
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if proc.returncode != 0:
        return ScenarioResult(
            "inventory determinism: re-running inspect_pptx_inventory "
            "on the happy-path PPTX produces byte-identical inventory bytes",
            False,
            f"second inventory run failed: rc={proc.returncode}, "
            f"stderr={proc.stderr[-200:]!r}",
        )
    a = happy_inventory.read_bytes()
    b = second_inv.read_bytes()
    ok = a == b
    return ScenarioResult(
        "inventory determinism: re-running inspect_pptx_inventory on "
        "the happy-path PPTX produces byte-identical inventory bytes",
        ok,
        (f"happy_size={len(a)}, second_size={len(b)}, equal={a == b}"
         if not ok else ""),
    )


def _print_self_test_results(results: list[ScenarioResult]) -> int:
    """Print a per-scenario [PASS]/[FAIL] line and return 0 on full
    pass, 1 on any failure."""
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
            f"FAIL: {fails} self-test scenario(s) did not behave as "
            f"expected."
        )
        return 1
    print(
        f"OK (self-test): {len(results)} scenario(s) behaved as expected. "
        f"This is MVP acceptance smoke for the explicit-input synthetic "
        f"flow, NOT proof of full prompt/report/Markdown-to-PPTX "
        f"automation."
    )
    return 0


def _run_self_tests() -> int:
    """Run every scenario under one ``tempfile.TemporaryDirectory()``.

    Captures a snapshot of ``REPO_ROOT/examples/`` before any scenario
    runs and re-snapshots at the end so a final scenario can prove no
    file under that committed directory was mutated by any scenario."""
    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    results: list[ScenarioResult] = []
    with tempfile.TemporaryDirectory(
        prefix="szh_acceptance_smoke_selftest_"
    ) as raw_td:
        td = Path(raw_td)

        # Happy path runs the real pipeline once. We reuse its PPTX +
        # inventory for the determinism scenario at the end so we
        # don't pay the pipeline cost twice.
        happy_root = td / "happy"
        happy_root.mkdir()
        results.append(_scenario_happy_path(happy_root))

        results.append(_scenario_missing_bundle(td))
        results.append(_scenario_invalid_bundle(td))
        results.append(_scenario_malformed_plan_spec(td))
        results.append(_scenario_preflight_failure(td))
        results.append(_scenario_pipeline_failure(td))
        results.append(_scenario_pptx_contract_failure(td))
        results.append(_scenario_inventory_post_condition_failure(td))
        results.append(_scenario_visual_quality_failure(td))
        results.append(_scenario_image_asset_chain(td))
        # Direct-call probes of _validate_output_root's
        # refused-top-level-directory branch. These exercise the
        # diagnostic without invoking the real pipeline so they are
        # cheap to add even though every other scenario in the suite
        # goes through the full subprocess chain.
        #
        # Each refused name is exercised twice: once with the canonical
        # (lower-case) on-disk name, and once with a case-variant the
        # underlying filesystem treats as the SAME directory but a naive
        # string-prefix comparison would treat as different. The
        # case-variant scenarios prove the gate is case-insensitive on
        # macOS APFS / Windows NTFS (where `.GIT/foo` is the same on-
        # disk dir as `.git/foo`) and harmless on case-sensitive
        # filesystems (where it refuses a brand-new `.GIT/` directory
        # the agent never meant to create either way).
        why_git = "the .git/ directory carries git metadata"
        why_claude = (
            "the .claude/ directory carries the user's Claude Code "
            "project state"
        )
        why_examples = "this directory ships committed source bytes"
        results.append(_scenario_refused_output_root(".git", ".git", why_git))
        results.append(_scenario_refused_output_root(".GIT", ".git", why_git))
        results.append(_scenario_refused_output_root(".Git", ".git", why_git))
        results.append(_scenario_refused_output_root(
            ".claude", ".claude", why_claude,
        ))
        results.append(_scenario_refused_output_root(
            ".CLAUDE", ".claude", why_claude,
        ))
        results.append(_scenario_refused_output_root(
            "examples", "examples", why_examples,
        ))
        results.append(_scenario_refused_output_root(
            "EXAMPLES", "examples", why_examples,
        ))
        results.append(_scenario_refused_output_root(
            "Examples", "examples", why_examples,
        ))
        # Two more probes for case-variant REPO prefix attacks: the
        # gate must casefold the prefix comparison too, not just the
        # first component beyond the repo. Both probes resolve to the
        # SAME on-disk directory as the canonical-case path on
        # case-insensitive filesystems (macOS APFS, Windows NTFS).
        results.append(
            _scenario_refused_output_root_case_variant_repo_prefix()
        )
        results.append(
            _scenario_refused_output_root_case_variant_repo_root()
        )

        happy_pptx = happy_root / "deck.pptx"
        happy_inv = happy_root / "report" / "inventory.json"
        if happy_pptx.is_file() and happy_inv.is_file():
            results.append(_scenario_inventory_determinism(
                td, happy_pptx, happy_inv,
            ))
        else:
            results.append(ScenarioResult(
                "inventory determinism: re-running inspect_pptx_inventory "
                "on the happy-path PPTX produces byte-identical inventory bytes",
                False,
                "prerequisite failed: happy-path PPTX or inventory missing",
            ))

    examples_after = _snapshot_dir(REPO_ROOT / "examples")
    examples_unchanged = examples_before == examples_after
    changed_paths: list[str] = []
    if not examples_unchanged:
        for key in sorted(set(examples_before) | set(examples_after)):
            if examples_before.get(key) != examples_after.get(key):
                changed_paths.append(key)
    results.append(ScenarioResult(
        "no generated artifacts written into committed examples/ "
        "(byte-identical snapshot of REPO_ROOT/examples/ before and "
        "after every scenario)",
        examples_unchanged,
        f"changed paths: {changed_paths!r}" if changed_paths else "",
    ))

    return _print_self_test_results(results)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
