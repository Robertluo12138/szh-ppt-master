#!/usr/bin/env python3
"""Stage-1-to-10 explicit-input end-to-end runner.

Chains the existing Stage-1-to-6 preparation flow and the existing
Stage-7-to-10 prepared-workspace pipeline into one local, deterministic
command that produces a validated editable PPTX from caller-supplied
source / spec files:

    1. scripts/prepare_workspace.py — Stage 1-6 explicit-input
       orchestration (init_workspace -> init_deck_brief ->
       init_deck_plan -> init_design_system -> init_slide_plans ->
       init_image_manifest), invoked in-process so the structured
       per-stage result is preserved for reporting.
    2. scripts/run_pipeline.py      — Stage 7-10 prepared-workspace
       pipeline (validate_workspace -> generate_render_models ->
       generate_svg_previews -> export_pptx -> validate_pptx_contract),
       invoked as a subprocess so its existing fail-closed gates,
       reporting, and (optional) ``--report-dir`` writes are reused
       verbatim — no stage logic is duplicated.

**This is explicit-input end-to-end orchestration only — it is NOT a
full prompt/report/Markdown-to-PPTX automation.** Every Stage-1-to-6
artifact's content comes from the caller via flags or JSON spec files;
Stage 7-10 consumes only what Stage 1-6 wrote. The orchestrator NEVER:

  - parses ``input/source.md`` for business content (the prepare_workspace
    helpers each delegate to the Stage-1/Stage-2 bridge, which reads the
    source bytes only for byte-level integrity checks and discards the
    decoded string);
  - invents ``deck_brief`` / ``deck_plan`` / ``design_system`` /
    ``slide_plans`` / ``image_manifest`` content;
  - generates any image asset, plan, spec, or slide body;
  - calls D-One, Qoder, any public network, image generation,
    telemetry, or external service;
  - duplicates per-stage logic — every stage is delegated to
    ``prepare_workspace.py`` or ``run_pipeline.py``;
  - modifies files outside ``--workspace`` apart from the final
    ``--output`` PPTX and, if supplied, ``--report-dir``.

Fail-closed semantics:

  - if Stage-1-to-6 preparation fails at any stage (non-zero exit), the
    Stage-7-to-10 pipeline is NOT invoked at all; no ``render_models/``,
    ``svg_previews/``, ``.pptx``, or ``pipeline_report.{json,txt}`` is
    produced;
  - if Stage-7-to-10 fails, the failing stage is reported clearly via
    the pipeline subprocess's own ``[FAIL] <stage>`` / ``[SKIP] <stage>``
    cascade plus stderr tail;
  - the final ``--output`` PPTX and (optional) ``--report-dir`` follow
    ``scripts/run_pipeline.py``'s existing safety rules — must live
    OUTSIDE the workspace, ``--output`` must end in ``.pptx``, no
    symlinks, no directory at ``--output``, no symlink / non-directory /
    read-only directory at ``--report-dir``, no symlink /
    non-regular-file / read-only regular file at
    ``<report-dir>/pipeline_report.{json,txt}``.

Stdlib-only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

from prepare_workspace import prepare_workspace, PrepareResult  # noqa: E402


@dataclass
class PipelineOutcome:
    """Outcome of the ``scripts/run_pipeline.py`` subprocess.

    ``invoked=False`` means Stage-1-to-6 preparation failed and we
    deliberately did not start the pipeline — there is no
    ``render_models/`` / ``svg_previews/`` / ``.pptx`` /
    ``pipeline_report.{json,txt}`` to look at."""
    invoked: bool
    exit_code: int  # -1 when invoked=False
    stdout: str
    stderr: str
    skip_reason: str = ""

    @property
    def ok(self) -> bool:
        return self.invoked and self.exit_code == 0


@dataclass
class ExplicitPipelineResult:
    prep: PrepareResult
    pipeline: PipelineOutcome

    @property
    def overall_ok(self) -> bool:
        return self.prep.overall_ok and self.pipeline.ok


def _invoke_run_pipeline(
    *,
    workspace: Path,
    template_root: Path,
    output: Path,
    report_dir: Path | None,
) -> PipelineOutcome:
    """Spawn ``scripts/run_pipeline.py`` as a subprocess.

    Uses the same ``sys.executable`` that started us so we inherit the
    caller's Python. The subprocess owns every Stage-7-to-10 gate
    (``--output`` extension, ``--output`` inside-workspace, ``--output``
    symlink / non-regular-file, ``--report-dir`` inside-workspace /
    symlink / non-directory / read-only / report-file pre-existing
    paths) and writes ``--report-dir`` reports itself when supplied —
    no logic is reimplemented here."""
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "run_pipeline.py"),
        "--workspace", str(workspace),
        "--template-root", str(template_root),
        "--output", str(output),
    ]
    if report_dir is not None:
        cmd += ["--report-dir", str(report_dir)]
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return PipelineOutcome(
        invoked=True,
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def run_explicit_pipeline(
    *,
    workspace: Path,
    source: Path,
    title: str,
    audience: str,
    objective: str,
    plan_spec: Path,
    slide_specs_dir: Path,
    image_manifest_spec: Path,
    template_root: Path,
    output: Path,
    report_dir: Path | None = None,
    design_system_spec: Path | None = None,
    theme_from_template: bool = False,
    source_id: str | None = None,
    tone: str | None = None,
    language: str | None = None,
    approximate_slide_count: int | None = None,
) -> ExplicitPipelineResult:
    """Run Stage 1-6 (in-process) then Stage 7-10 (subprocess).

    If Stage 1-6 preparation fails at any stage, the Stage 7-10
    pipeline is intentionally NOT invoked — no ``render_models/`` /
    ``svg_previews/`` / ``.pptx`` / ``pipeline_report.{json,txt}`` is
    produced. The orchestrator does not retry stages and does not roll
    back earlier-stage artifacts when a later stage fails (each helper
    owns its own rollback contract)."""
    prep = prepare_workspace(
        workspace=workspace,
        source=source,
        title=title,
        audience=audience,
        objective=objective,
        plan_spec=plan_spec,
        slide_specs_dir=slide_specs_dir,
        image_manifest_spec=image_manifest_spec,
        template_root=template_root,
        design_system_spec=design_system_spec,
        theme_from_template=theme_from_template,
        source_id=source_id,
        tone=tone,
        language=language,
        approximate_slide_count=approximate_slide_count,
    )
    if not prep.overall_ok:
        failed = prep.first_failure.name if prep.first_failure else "unknown"
        return ExplicitPipelineResult(
            prep=prep,
            pipeline=PipelineOutcome(
                invoked=False,
                exit_code=-1,
                stdout="",
                stderr="",
                skip_reason=(
                    f"Stage-1-to-6 preparation failed at {failed!r}; "
                    f"Stage-7-to-10 pipeline was not invoked — no "
                    f"render_models/, svg_previews/, .pptx, or pipeline "
                    f"report produced."
                ),
            ),
        )
    pipeline = _invoke_run_pipeline(
        workspace=workspace,
        template_root=template_root,
        output=output,
        report_dir=report_dir,
    )
    return ExplicitPipelineResult(prep=prep, pipeline=pipeline)


def _format_prep(prep: PrepareResult) -> str:
    lines = ["=== Stage 1-6: prepare_workspace ==="]
    for s in prep.stages:
        if s.skipped:
            mark = "SKIP"
        elif s.ok:
            mark = "PASS"
        else:
            mark = "FAIL"
        lines.append(f"  [{mark}] {s.name} (rc={s.exit_code})")
    if not prep.overall_ok and prep.first_failure is not None:
        f = prep.first_failure
        lines.append(f"  --- {f.name} message tail ---")
        for line in f.message.splitlines()[-15:]:
            lines.append(f"    {line}")
    return "\n".join(lines)


def _format_pipeline(p: PipelineOutcome) -> str:
    lines = ["=== Stage 7-10: run_pipeline ==="]
    if not p.invoked:
        lines.append(f"  [SKIP] pipeline not invoked — {p.skip_reason}")
        return "\n".join(lines)
    lines.append(f"  invoked (rc={p.exit_code}).")
    if p.stdout:
        lines.append("  --- pipeline stdout ---")
        for line in p.stdout.splitlines():
            lines.append(f"    {line}")
    if p.stderr and p.exit_code != 0:
        lines.append("  --- pipeline stderr ---")
        for line in p.stderr.splitlines():
            lines.append(f"    {line}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage-1-to-10 explicit-input end-to-end runner. Chains "
            "scripts/prepare_workspace.py (Stage 1-6 explicit-input "
            "orchestration) and scripts/run_pipeline.py (Stage 7-10 "
            "prepared-workspace pipeline) into one command. "
            "Explicit-input end-to-end orchestration only — does NOT "
            "plan a deck, does NOT extract source content, does NOT "
            "generate any image / spec / slide body, does NOT call any "
            "public network or external service."
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Workspace directory to create (forwarded to init_workspace).",
    )
    parser.add_argument(
        "--source", type=Path, default=None,
        help="Local .md or .txt source file (forwarded to init_workspace).",
    )
    parser.add_argument(
        "--source-id", type=str, default=None,
        help="Opaque source identifier (forwarded to init_workspace; "
             "defaults to the --source filename stem).",
    )
    parser.add_argument(
        "--title", type=str, default=None,
        help="Deck title (forwarded to init_deck_brief).",
    )
    parser.add_argument(
        "--audience", type=str, default=None,
        help="Audience (forwarded to init_deck_brief).",
    )
    parser.add_argument(
        "--objective", type=str, default=None,
        help="Deck objective (forwarded to init_deck_brief).",
    )
    parser.add_argument(
        "--tone", type=str, default=None,
        help="Optional tone (forwarded to init_deck_brief).",
    )
    parser.add_argument(
        "--language", type=str, default=None,
        help="Optional language (forwarded to init_deck_brief).",
    )
    parser.add_argument(
        "--approximate-slide-count", type=int, default=None,
        help="Optional planning hint (forwarded to init_deck_brief).",
    )
    parser.add_argument(
        "--plan-spec", type=Path, default=None,
        help="Deck-plan JSON candidate (forwarded to init_deck_plan).",
    )
    parser.add_argument(
        "--design-system-spec", type=Path, default=None,
        help="Design-system JSON candidate (forwarded to "
             "init_design_system). Mutually exclusive with "
             "--theme-from-template.",
    )
    parser.add_argument(
        "--theme-from-template", action="store_true",
        help="Project palette / typography / grid from the theme of "
             "deck_plan.template (resolved against --template-root). "
             "Mutually exclusive with --design-system-spec.",
    )
    parser.add_argument(
        "--template-root", type=Path, default=None,
        help="Template root directory (e.g. templates/layouts/). "
             "Forwarded to init_slide_plans, init_design_system (in "
             "theme mode), and run_pipeline.",
    )
    parser.add_argument(
        "--slide-specs-dir", type=Path, default=None,
        help="Directory of slide_plan JSON candidates (forwarded to "
             "init_slide_plans).",
    )
    parser.add_argument(
        "--image-manifest-spec", type=Path, default=None,
        help="Image-manifest JSON candidate (forwarded to "
             "init_image_manifest).",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Path to write the .pptx output. Extension must be .pptx. "
             "MUST live outside --workspace. Symlinks and directories "
             "at this path are refused by run_pipeline.",
    )
    parser.add_argument(
        "--report-dir", type=Path, default=None,
        help="Optional directory under which run_pipeline will write "
             "pipeline_report.{json,txt}. MUST live outside --workspace. "
             "Same pre-existing-path gates apply as run_pipeline.",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run the in-script tempfixture scenarios (happy path, "
             "preparation failure skipping the pipeline, pipeline "
             "failure reported clearly, wrong --output extension, "
             "--output inside the workspace refused by the pipeline "
             "gate, source-body marker phrase never copied outside "
             "input/source.md or into the PPTX, deterministic repeated "
             "runs from byte-identical inputs both pass validation). "
             "Mutually exclusive with the orchestration flags.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        orchestration_args = (
            args.workspace, args.source, args.source_id,
            args.title, args.audience, args.objective,
            args.tone, args.language, args.approximate_slide_count,
            args.plan_spec, args.design_system_spec,
            args.template_root, args.slide_specs_dir,
            args.image_manifest_spec, args.output, args.report_dir,
        )
        if any(v is not None for v in orchestration_args) or args.theme_from_template:
            print(
                "FAIL: --self-test does not take any other argument",
                file=sys.stderr,
            )
            return 2
        fails = _print_self_test_results(_run_self_tests())
        print()
        if fails:
            print(
                f"FAIL: {fails} self-test scenario(s) did not behave as "
                f"expected."
            )
            return 1
        print(
            "OK (self-test): explicit-input end-to-end orchestrator "
            "behaves as expected — preparation failures short-circuit "
            "the pipeline, pipeline failures surface clearly, source-body "
            "content stays in input/source.md only, and deterministic "
            "repeated runs both pass validation."
        )
        return 0

    missing = [
        name for name, value in (
            ("--workspace", args.workspace),
            ("--source", args.source),
            ("--title", args.title),
            ("--audience", args.audience),
            ("--objective", args.objective),
            ("--plan-spec", args.plan_spec),
            ("--slide-specs-dir", args.slide_specs_dir),
            ("--image-manifest-spec", args.image_manifest_spec),
            ("--template-root", args.template_root),
            ("--output", args.output),
        )
        if value is None
    ]
    if missing:
        print(
            f"FAIL: missing required argument(s): {', '.join(missing)} "
            f"(use --self-test for the in-script scenarios)",
            file=sys.stderr,
        )
        return 2

    # Mode-selection gate (mirrors init_design_system / prepare_workspace).
    if args.design_system_spec is None and not args.theme_from_template:
        print(
            "FAIL: must pass either --design-system-spec <path> or "
            "--theme-from-template (with --template-root <dir>)",
            file=sys.stderr,
        )
        return 2
    if args.design_system_spec is not None and args.theme_from_template:
        print(
            "FAIL: --design-system-spec and --theme-from-template are "
            "mutually exclusive; pick exactly one design-system input",
            file=sys.stderr,
        )
        return 2

    # Fail-fast on a wrong --output extension so a six-stage prep run
    # is never wasted on an obviously bad output path. All other
    # --output / --report-dir safety gates (inside-workspace, symlink,
    # non-regular-file, pre-existing report-file paths, ...) belong to
    # run_pipeline.py and fire there for defense-in-depth.
    if args.output.suffix.lower() != ".pptx":
        print(
            f"FAIL: --output must end in .pptx; got {args.output}",
            file=sys.stderr,
        )
        return 2

    result = run_explicit_pipeline(
        workspace=args.workspace,
        source=args.source,
        title=args.title,
        audience=args.audience,
        objective=args.objective,
        plan_spec=args.plan_spec,
        slide_specs_dir=args.slide_specs_dir,
        image_manifest_spec=args.image_manifest_spec,
        template_root=args.template_root,
        output=args.output,
        report_dir=args.report_dir,
        design_system_spec=args.design_system_spec,
        theme_from_template=args.theme_from_template,
        source_id=args.source_id,
        tone=args.tone,
        language=args.language,
        approximate_slide_count=args.approximate_slide_count,
    )

    print(_format_prep(result.prep))
    print()
    print(_format_pipeline(result.pipeline))
    print()
    if result.overall_ok:
        print(
            f"OK: explicit-input end-to-end run succeeded; PPTX written "
            f"to {args.output}."
        )
        return 0
    if not result.prep.overall_ok:
        f = result.prep.first_failure
        print(
            f"FAIL: Stage-1-to-6 preparation failed at "
            f"{f.name if f else 'unknown'}; Stage-7-to-10 pipeline was "
            f"NOT invoked (no render_models / SVG / PPTX / report).",
            file=sys.stderr,
        )
        return f.exit_code if f else 1
    print(
        f"FAIL: Stage-7-to-10 pipeline failed "
        f"(rc={result.pipeline.exit_code}); see the pipeline stdout / "
        f"stderr above for the failing stage.",
        file=sys.stderr,
    )
    return result.pipeline.exit_code or 1


# ---------------------------------------------------------------------------
# Self-test scenarios. Each runs under tempfile.TemporaryDirectory() and
# invokes THIS script as a subprocess (so the real argparse + main flow
# is exercised, not an in-process shortcut). Fixtures are written inline
# and never leak into the repo.
# ---------------------------------------------------------------------------


_MARKER_PHRASE = "EXPLICIT-PIPELINE-MARKER-3f9a18b4"

_FIXTURE_SOURCE = (
    "# Synthetic Fixture Source\n\n"
    f"{_MARKER_PHRASE}\n"
    "This synthetic body is the secret the explicit-input end-to-end "
    "orchestrator must never copy into any artifact beyond "
    "input/source.md (and must never embed into the produced PPTX). "
    "Stage 2 only takes --title / --audience / --objective from the "
    "CLI; Stage 3-6 each accept explicit --*-spec JSON files; Stage "
    "7-10 consume only the prepared workspace.\n"
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _build_fixture(td: Path, *, source_id: str = "fixture_source") -> dict:
    """Build a minimal Stage-1-through-6 fixture under ``td``.

    Two slides (cover + key_message) against the business_review
    template (the template this repo ships) — small enough to keep
    self-test runtime manageable, and large enough for run_pipeline to
    actually run validate_workspace, generate render_models, generate
    SVG previews, export the PPTX, and validate the PPTX container."""
    td.mkdir(parents=True, exist_ok=True)
    source = td / "fixture_source.md"
    source.write_text(_FIXTURE_SOURCE)

    plan_spec = td / "plan_spec.json"
    _write_json(plan_spec, {
        "template": "business_review",
        "planning": {
            "planned_slide_count": 2,
            "rationale": (
                "Two-slide fixture exercising the end-to-end orchestrator "
                "only — no business content."
            ),
        },
        "sections": [
            {
                "id": "intro",
                "title": "Intro",
                "summary": "Cover plus one body slide.",
                "slide_indices": [1, 2],
            },
        ],
        "slides": [
            {
                "index": 1,
                "layout": "cover",
                "title": "Fixture Cover Title",
                "section_id": "intro",
                "summary": "Cover slide.",
                "density": "low",
                "source_refs": [source_id],
            },
            {
                "index": 2,
                "layout": "key_message",
                "title": "Fixture Message",
                "section_id": "intro",
                "summary": "Single key-message slide.",
                "density": "low",
                "source_refs": [source_id],
            },
        ],
    })

    specs_dir = td / "specs"
    specs_dir.mkdir()
    _write_json(specs_dir / "01_cover.json", {
        "index": 1,
        "layout": "cover",
        "title": "Fixture Cover Title",
        "blocks": [
            {"id": "title", "kind": "text", "content": "Fixture Cover Title"},
        ],
    })
    _write_json(specs_dir / "02_key_message.json", {
        "index": 2,
        "layout": "key_message",
        "title": "Fixture Message",
        "blocks": [
            {
                "id": "message",
                "kind": "callout",
                "content": "Fixture key-message body.",
            },
        ],
    })

    image_manifest_spec = td / "image_manifest_spec.json"
    _write_json(image_manifest_spec, {"images": []})

    return {
        "source": source,
        "title": "Fixture Title",
        "audience": "Internal fixture audience",
        "objective": (
            "Exercise the explicit-input end-to-end orchestrator."
        ),
        "plan_spec": plan_spec,
        "slide_specs_dir": specs_dir,
        "image_manifest_spec": image_manifest_spec,
        "template_root": REPO_ROOT / "templates" / "layouts",
        "theme_from_template": True,
        "source_id": source_id,
    }


def _invoke_runner(extra_args: list[str]) -> tuple[int, str, str]:
    """Spawn this very script as a subprocess and capture its exit
    code + stdout + stderr. Using the live entry point gives full
    fidelity for the argparse + main() flow."""
    cmd = [sys.executable, str(Path(__file__).resolve())] + extra_args
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _args_from_fixture(
    fx: dict,
    *,
    workspace: Path,
    output: Path,
    report_dir: Path | None = None,
) -> list[str]:
    args = [
        "--workspace", str(workspace),
        "--source", str(fx["source"]),
        "--title", fx["title"],
        "--audience", fx["audience"],
        "--objective", fx["objective"],
        "--plan-spec", str(fx["plan_spec"]),
        "--slide-specs-dir", str(fx["slide_specs_dir"]),
        "--image-manifest-spec", str(fx["image_manifest_spec"]),
        "--template-root", str(fx["template_root"]),
        "--output", str(output),
    ]
    if fx.get("theme_from_template"):
        args.append("--theme-from-template")
    if fx.get("source_id"):
        args += ["--source-id", fx["source_id"]]
    if report_dir is not None:
        args += ["--report-dir", str(report_dir)]
    return args


@dataclass
class ScenarioResult:
    name: str
    ok: bool
    detail: str = ""


def _scenario_happy_path(td: Path) -> ScenarioResult:
    fx = _build_fixture(td / "fx_happy_dir")
    ws = td / "ws_happy"
    out = td / "happy.pptx"
    rc, sout, _serr = _invoke_runner(
        _args_from_fixture(fx, workspace=ws, output=out)
    )
    expected_prep_passes = [
        "[PASS] init_workspace",
        "[PASS] init_deck_brief",
        "[PASS] init_deck_plan",
        "[PASS] init_design_system",
        "[PASS] init_slide_plans",
        "[PASS] init_image_manifest",
    ]
    expected_pipeline_passes = [
        "[PASS] validate_workspace",
        "[PASS] generate_render_models",
        "[PASS] generate_svg_previews",
        "[PASS] export_pptx",
        "[PASS] validate_pptx_contract",
    ]
    ok = (
        rc == 0
        and out.is_file()
        and out.stat().st_size > 0
        and "OK: explicit-input end-to-end run succeeded" in sout
        and all(line in sout for line in expected_prep_passes)
        and all(line in sout for line in expected_pipeline_passes)
    )
    return ScenarioResult(
        "happy path: explicit source/spec inputs produce a validated "
        "PPTX (every Stage-1-to-6 stage PASS and every Stage-7-to-10 "
        "stage PASS via run_pipeline's own cascade)",
        ok,
        (f"rc={rc}, out_exists={out.is_file()}, "
         f"size={out.stat().st_size if out.is_file() else 0}, "
         f"ok_marker={'OK: explicit-input end-to-end run succeeded' in sout}, "
         f"prep_all={all(line in sout for line in expected_prep_passes)}, "
         f"pipeline_all={all(line in sout for line in expected_pipeline_passes)}"
         if not ok else ""),
    )


def _scenario_prep_failure_skips_pipeline(td: Path) -> ScenarioResult:
    """Stage-1-to-6 preparation failure must short-circuit the
    pipeline. We force init_workspace to reject by passing an empty
    source file (the same failure prepare_workspace's own self-test
    uses to drive its 'per-stage failure' scenarios). Verify: exit
    non-zero, no .pptx written, no render_models/ / svg_previews/
    under the workspace, and the pipeline-not-invoked marker."""
    fx = _build_fixture(td / "fx_prep_fail_dir")
    empty_src = td / "empty_source.md"
    empty_src.write_bytes(b"")
    fx["source"] = empty_src
    ws = td / "ws_prep_fail"
    out = td / "prep_fail.pptx"
    rc, sout, _serr = _invoke_runner(
        _args_from_fixture(fx, workspace=ws, output=out)
    )
    ok = (
        rc != 0
        and not out.exists()
        and not (ws / "render_models").exists()
        and not (ws / "svg_previews").exists()
        and "[FAIL] init_workspace" in sout
        and "pipeline not invoked" in sout
        and "[SKIP] init_deck_brief" in sout
        and "[SKIP] init_image_manifest" in sout
    )
    return ScenarioResult(
        "preparation failure short-circuits the pipeline; no "
        "render_models/, svg_previews/, or PPTX is produced; every "
        "downstream prep stage is marked SKIP",
        ok,
        (f"rc={rc}, out_exists={out.exists()}, "
         f"render_models_exists={(ws / 'render_models').exists()}, "
         f"svg_previews_exists={(ws / 'svg_previews').exists()}, "
         f"fail_marker={'[FAIL] init_workspace' in sout}, "
         f"skip_marker={'pipeline not invoked' in sout}"
         if not ok else ""),
    )


def _scenario_pipeline_failure_reported(td: Path) -> ScenarioResult:
    """A clean failure path AFTER prep succeeds: we pre-create a real
    directory whose name ends in '.pptx' at the --output path. Prep
    does not look at --output, so it passes; run_pipeline's up-front
    'pre-existing non-regular-file at --output' gate fires before any
    pipeline stage runs, returning rc=2 with a 'not a regular file'
    stderr. The orchestrator must surface that failure (rc != 0,
    pipeline section visible, run_pipeline's diagnostic relayed) and
    must NOT touch the canary inside the directory."""
    fx = _build_fixture(td / "fx_pipe_fail_dir")
    ws = td / "ws_pipe_fail"
    out_dir = td / "directory.pptx"
    out_dir.mkdir()
    canary = out_dir / "canary.txt"
    canary_text = "DO NOT DELETE"
    canary.write_text(canary_text)
    rc, sout, serr = _invoke_runner(
        _args_from_fixture(fx, workspace=ws, output=out_dir)
    )
    diagnostic_in_orchestrator_output = (
        "not a regular file" in sout or "not a regular file" in serr
    )
    ok = (
        rc != 0
        and "[PASS] init_image_manifest" in sout
        and "Stage 7-10: run_pipeline" in sout
        and "FAIL: Stage-7-to-10 pipeline failed" in serr
        and diagnostic_in_orchestrator_output
        and out_dir.is_dir()
        and canary.is_file()
        and canary.read_text() == canary_text
    )
    return ScenarioResult(
        "pipeline failure is reported clearly: a pre-existing directory "
        "at --output is caught by run_pipeline's gate after prep "
        "succeeds, the orchestrator surfaces the diagnostic, and the "
        "directory's canary is untouched",
        ok,
        (f"rc={rc}, "
         f"pipeline_header={'Stage 7-10: run_pipeline' in sout}, "
         f"orch_fail_marker={'FAIL: Stage-7-to-10 pipeline failed' in serr}, "
         f"diagnostic_relayed={diagnostic_in_orchestrator_output}, "
         f"canary_intact={canary.is_file() and canary.read_text() == canary_text}"
         if not ok else ""),
    )


def _scenario_wrong_output_extension(td: Path) -> ScenarioResult:
    """Wrong --output extension fails before ANY stage runs. The
    orchestrator's own up-front gate catches this so a six-stage prep
    run is never wasted. Verify: rc=2, no workspace created, no .pptx
    or .txt at the requested path."""
    fx = _build_fixture(td / "fx_wrong_ext_dir")
    ws = td / "ws_wrong_ext"
    out = td / "out.txt"
    rc, _sout, serr = _invoke_runner(
        _args_from_fixture(fx, workspace=ws, output=out)
    )
    ok = (
        rc == 2
        and "--output must end in .pptx" in serr
        and not out.exists()
        and not ws.exists()
    )
    return ScenarioResult(
        "wrong --output extension fails fast in the orchestrator "
        "(before any prep stage runs); no workspace is created",
        ok,
        (f"rc={rc}, ext_marker={'--output must end in .pptx' in serr}, "
         f"ws_exists={ws.exists()}, out_exists={out.exists()}"
         if not ok else ""),
    )


def _scenario_output_inside_workspace(td: Path) -> ScenarioResult:
    """--output landing inside the workspace must be refused. The
    orchestrator delegates this gate to run_pipeline (defense in
    depth), so prep runs through Stage 6 first and then the pipeline
    subprocess catches it. Verify: rc != 0, the run_pipeline gate
    diagnostic is relayed, no .pptx is written inside the workspace
    tree."""
    fx = _build_fixture(td / "fx_inside_dir")
    ws = td / "ws_inside"
    out = ws / "inside.pptx"
    rc, sout, serr = _invoke_runner(
        _args_from_fixture(fx, workspace=ws, output=out)
    )
    inside_marker = (
        "inside the workspace" in sout or "inside the workspace" in serr
    )
    ok = (
        rc != 0
        and inside_marker
        and not out.exists()
    )
    return ScenarioResult(
        "--output inside the workspace is refused by run_pipeline's "
        "gate; no .pptx written inside the workspace tree",
        ok,
        (f"rc={rc}, inside_marker={inside_marker}, "
         f"out_exists={out.exists()}"
         if not ok else ""),
    )


def _scenario_marker_phrase_isolation(td: Path) -> ScenarioResult:
    """The source body's marker phrase must appear in
    ``<workspace>/input/source.md`` only — never in any other
    workspace artifact (source_manifest, deck_brief, deck_plan,
    design_system, slide_plans, image_manifest, render_models,
    svg_previews) and never embedded in the produced PPTX bytes."""
    fx = _build_fixture(td / "fx_marker_dir")
    ws = td / "ws_marker"
    out = td / "marker.pptx"
    rc, _sout, _serr = _invoke_runner(
        _args_from_fixture(fx, workspace=ws, output=out)
    )
    if rc != 0 or not out.is_file():
        return ScenarioResult(
            "marker-phrase test prerequisite: happy path completed",
            False,
            f"rc={rc}, out_exists={out.exists()}",
        )
    source_copy = (ws / "input" / "source.md").read_text()
    artifact_text_parts: list[str] = []
    for rel in (
        "source_manifest.json",
        "deck_brief.json",
        "deck_plan.json",
        "design_system.json",
        "image_manifest.json",
    ):
        p = ws / rel
        if p.is_file():
            artifact_text_parts.append(p.read_text())
    for sp in sorted((ws / "slide_plans").glob("*.json")):
        artifact_text_parts.append(sp.read_text())
    for rm in sorted((ws / "render_models").glob("*.json")):
        artifact_text_parts.append(rm.read_text())
    for sv in sorted((ws / "svg_previews").glob("*.svg")):
        artifact_text_parts.append(sv.read_text())
    artifact_text = "\n".join(artifact_text_parts)
    pptx_bytes = out.read_bytes()
    in_source = _MARKER_PHRASE in source_copy
    in_artifacts = _MARKER_PHRASE in artifact_text
    in_pptx = _MARKER_PHRASE.encode("utf-8") in pptx_bytes
    ok = in_source and not in_artifacts and not in_pptx
    return ScenarioResult(
        "marker phrase appears in input/source.md only — never copied "
        "into source_manifest / deck_brief / deck_plan / design_system "
        "/ slide_plans / image_manifest / render_models / svg_previews, "
        "and never embedded in the produced PPTX bytes",
        ok,
        (f"in_source={in_source}, in_artifacts={in_artifacts}, "
         f"in_pptx={in_pptx}"
         if not ok else ""),
    )


def _scenario_determinism(td: Path) -> ScenarioResult:
    """Two independent end-to-end runs from byte-identical inputs into
    different empty workspaces should both pass validation. We assert
    both runs succeed (the per-stage outputs are deterministic so the
    Stage-1-through-6 artifacts are byte-identical across runs)."""
    fx_a = _build_fixture(td / "fx_det_a_dir")
    fx_b = _build_fixture(td / "fx_det_b_dir")
    ws_a = td / "ws_det_a"
    ws_b = td / "ws_det_b"
    out_a = td / "det_a.pptx"
    out_b = td / "det_b.pptx"
    rc_a, sout_a, _serr_a = _invoke_runner(
        _args_from_fixture(fx_a, workspace=ws_a, output=out_a)
    )
    rc_b, sout_b, _serr_b = _invoke_runner(
        _args_from_fixture(fx_b, workspace=ws_b, output=out_b)
    )
    ok = (
        rc_a == 0 and rc_b == 0
        and out_a.is_file() and out_b.is_file()
        and out_a.stat().st_size > 0 and out_b.stat().st_size > 0
        and "OK: explicit-input end-to-end run succeeded" in sout_a
        and "OK: explicit-input end-to-end run succeeded" in sout_b
    )
    diffs: list[str] = []
    if ok:
        intermediates = [
            "input/source.md",
            "source_manifest.json",
            "deck_brief.json",
            "deck_plan.json",
            "design_system.json",
            "image_manifest.json",
            "slide_plans/01_cover.json",
            "slide_plans/02_key_message.json",
        ]
        for rel in intermediates:
            a = (ws_a / rel).read_bytes()
            b = (ws_b / rel).read_bytes()
            if a != b:
                diffs.append(rel)
                ok = False
    return ScenarioResult(
        "deterministic repeated runs from byte-identical inputs both "
        "pass validation, and Stage-1-through-6 artifacts are "
        "byte-identical across the two runs",
        ok,
        (f"rc_a={rc_a}, rc_b={rc_b}, "
         f"out_a_size={out_a.stat().st_size if out_a.is_file() else 0}, "
         f"out_b_size={out_b.stat().st_size if out_b.is_file() else 0}, "
         f"intermediate_diffs={diffs}"
         if not ok else ""),
    )


def _run_self_tests() -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    template_root = REPO_ROOT / "templates" / "layouts"
    if not template_root.is_dir():
        results.append(ScenarioResult(
            "fixture: templates/layouts/ exists (required for self-test)",
            False,
            f"not found: {template_root}",
        ))
        return results
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        results.append(_scenario_happy_path(td))
        results.append(_scenario_prep_failure_skips_pipeline(td))
        results.append(_scenario_pipeline_failure_reported(td))
        results.append(_scenario_wrong_output_extension(td))
        results.append(_scenario_output_inside_workspace(td))
        results.append(_scenario_marker_phrase_isolation(td))
        results.append(_scenario_determinism(td))
    return results


def _print_self_test_results(results: list[ScenarioResult]) -> int:
    fails = 0
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        suffix = f" -- {r.detail}" if r.detail and not r.ok else ""
        print(f"  [{mark}] {r.name}{suffix}")
        if not r.ok:
            fails += 1
    return fails


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
