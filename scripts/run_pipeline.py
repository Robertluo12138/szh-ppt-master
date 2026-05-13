#!/usr/bin/env python3
"""Deterministic local end-to-end pipeline runner for prepared workspaces.

Chains the five existing per-stage scripts in a single command:

    1. scripts/validate_workspace.py     (input contract gate)
    2. scripts/generate_render_models.py (render_model regeneration —
                                          writes <workspace>/render_models/)
    3. scripts/generate_svg_previews.py  (SVG preview regeneration —
                                          writes <workspace>/svg_previews/)
    4. scripts/export_pptx.py            (native editable PPTX export —
                                          writes the --output PPTX outside
                                          the workspace)
    5. scripts/validate_pptx_contract.py (PPTX container + minimal-evidence
                                          gate with expected slide count)

Workspace contract:

    The runner regenerates <workspace>/render_models/*.json and
    <workspace>/svg_previews/*.svg in place (each generator owns its
    subdirectory and sweeps stale files before regenerating). The
    prepared-input artifacts (deck_brief.json, deck_plan.json,
    slide_plans/, design_system.json, image_manifest.json) are
    read-only. The final --output PPTX MUST live OUTSIDE the workspace
    — a stray .pptx under the workspace would be picked up by
    validate_workspace on a later run.

Inputs:

    --workspace      a prepared workspace directory that already contains
                     deck_brief.json, deck_plan.json, slide_plans/*.json,
                     design_system.json, image_manifest.json. This runner
                     does NOT plan a deck from a raw prompt.
    --template-root  templates/ root containing the deck_plan.template.
    --output         path of the .pptx artifact to write (.pptx required;
                     MUST be outside --workspace).
    --report-dir     optional directory under which `pipeline_report.json`
                     and `pipeline_report.txt` are written. MUST be
                     outside --workspace (the workspace contract above
                     applies to reports too — only render_models/ and
                     svg_previews/ are runner-writable inside it).
    --self-test      run the in-script tempfixture scenarios (happy path,
                     wrong --output extension, --output inside workspace,
                     pre-existing symlink --output, pre-existing directory
                     named *.pptx, upstream validation failure skipping
                     downstream stages, pre-existing regular .pptx
                     preserved when validate_workspace fails before
                     export). Mutually exclusive with the other flags.

Fail-closed semantics: a non-zero exit code from any stage stops the
pipeline. The PPTX is only exported if every upstream stage passes, and
the validator is only run if export succeeded. The script exits non-zero
whenever any stage failed; the report still gets written so the failure
surface is captured.

Stdlib-only. No new dependencies. Each stage is invoked via subprocess
against the SAME `sys.executable` that started the runner, so logic is
reused — not duplicated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


@dataclass
class StageResult:
    name: str
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    skipped: bool = False
    skip_reason: str = ""

    @property
    def ok(self) -> bool:
        return (not self.skipped) and self.exit_code == 0


@dataclass
class PipelineResult:
    workspace: Path
    template_root: Path
    output: Path
    report_dir: Path | None
    expected_slide_count: int | None
    stages: list[StageResult] = field(default_factory=list)

    @property
    def overall_ok(self) -> bool:
        if not self.stages:
            return False
        return all(s.ok for s in self.stages)


def _run_stage(name: str, cmd: list[str]) -> StageResult:
    start = time.monotonic()
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return StageResult(
        name=name,
        command=cmd,
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        duration_s=time.monotonic() - start,
    )


def _skip_stage(name: str, cmd: list[str], reason: str) -> StageResult:
    return StageResult(
        name=name,
        command=cmd,
        exit_code=-1,
        stdout="",
        stderr="",
        duration_s=0.0,
        skipped=True,
        skip_reason=reason,
    )


def _read_expected_slide_count(workspace: Path) -> tuple[int | None, str]:
    """Read deck_plan.slides[] length without duplicating validation logic.

    The downstream validate_workspace stage is the authoritative gate for
    deck_plan well-formedness. This helper only needs to extract a slide
    count when the deck_plan is loadable; on any read/parse failure it
    returns (None, reason) and the validator stage will produce the real
    diagnostic. We do NOT fail the pipeline here — the validator will."""
    dp_path = workspace / "deck_plan.json"
    if not dp_path.is_file():
        return None, f"{dp_path} missing"
    try:
        deck = json.loads(dp_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return None, f"{dp_path} not loadable: {exc}"
    slides = deck.get("slides")
    if not isinstance(slides, list) or not slides:
        return None, "deck_plan.slides is not a non-empty list"
    return len(slides), ""


def run_pipeline(
    workspace: Path,
    template_root: Path,
    output: Path,
    report_dir: Path | None,
) -> PipelineResult:
    expected, expected_reason = _read_expected_slide_count(workspace)
    result = PipelineResult(
        workspace=workspace,
        template_root=template_root,
        output=output,
        report_dir=report_dir,
        expected_slide_count=expected,
    )

    py = sys.executable

    stages: list[tuple[str, list[str]]] = [
        (
            "validate_workspace",
            [py, str(SCRIPTS_DIR / "validate_workspace.py"),
             "--workspace", str(workspace),
             "--template-root", str(template_root)],
        ),
        (
            "generate_render_models",
            [py, str(SCRIPTS_DIR / "generate_render_models.py"),
             "--workspace", str(workspace),
             "--template-root", str(template_root)],
        ),
        (
            "generate_svg_previews",
            [py, str(SCRIPTS_DIR / "generate_svg_previews.py"),
             "--workspace", str(workspace),
             "--template-root", str(template_root)],
        ),
        (
            "export_pptx",
            [py, str(SCRIPTS_DIR / "export_pptx.py"),
             "--workspace", str(workspace),
             "--output", str(output)],
        ),
    ]

    pptx_cmd = [py, str(SCRIPTS_DIR / "validate_pptx_contract.py"),
                "--pptx", str(output)]
    if expected is not None:
        pptx_cmd += ["--expected-slide-count", str(expected)]
    stages.append(("validate_pptx_contract", pptx_cmd))

    aborted = False
    for name, cmd in stages:
        if aborted:
            result.stages.append(_skip_stage(
                name, cmd,
                reason="earlier stage failed; downstream stage skipped",
            ))
            continue
        stage = _run_stage(name, cmd)
        result.stages.append(stage)
        if not stage.ok:
            aborted = True

    if (
        result.expected_slide_count is None
        and not aborted
        and expected_reason
    ):
        # validate_workspace passed but we still couldn't read the slide
        # count up-front. This is unreachable in practice (the validator
        # gates deck_plan structure), so surface it as a defensive note
        # in the report rather than silently dropping the expected gate.
        result.stages.append(StageResult(
            name="expected_slide_count_lookup",
            command=[],
            exit_code=1,
            stdout="",
            stderr=(
                f"could not derive expected slide count from "
                f"deck_plan.json after validate_workspace succeeded: "
                f"{expected_reason}"
            ),
            duration_s=0.0,
        ))

    return result


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2:]
    elided = len(text) - len(head) - len(tail)
    return f"{head}\n... <elided {elided} chars> ...\n{tail}"


def _stage_json(s: StageResult) -> dict:
    return {
        "name": s.name,
        "command": s.command,
        "ok": s.ok,
        "skipped": s.skipped,
        "skip_reason": s.skip_reason,
        "exit_code": s.exit_code,
        "duration_s": round(s.duration_s, 3),
        "stdout": _truncate(s.stdout),
        "stderr": _truncate(s.stderr),
    }


def _write_reports(result: PipelineResult, report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "pipeline_report.json"
    txt_path = report_dir / "pipeline_report.txt"

    payload = {
        "workspace": str(result.workspace),
        "template_root": str(result.template_root),
        "output": str(result.output),
        "expected_slide_count": result.expected_slide_count,
        "overall_ok": result.overall_ok,
        "stages": [_stage_json(s) for s in result.stages],
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n")

    lines = [
        f"workspace: {result.workspace}",
        f"template_root: {result.template_root}",
        f"output: {result.output}",
        f"expected_slide_count: {result.expected_slide_count}",
        f"overall_ok: {result.overall_ok}",
        "",
        "stages:",
    ]
    for s in result.stages:
        status = "SKIP" if s.skipped else ("PASS" if s.ok else "FAIL")
        lines.append(
            f"  [{status}] {s.name} "
            f"(exit={s.exit_code}, "
            f"duration={s.duration_s:.3f}s)"
        )
        if s.skipped and s.skip_reason:
            lines.append(f"    skip_reason: {s.skip_reason}")
        if not s.ok and not s.skipped:
            err_tail = s.stderr.strip().splitlines()[-20:]
            if err_tail:
                lines.append("    stderr tail:")
                for ln in err_tail:
                    lines.append(f"      {ln}")
            out_tail = s.stdout.strip().splitlines()[-10:]
            if out_tail:
                lines.append("    stdout tail:")
                for ln in out_tail:
                    lines.append(f"      {ln}")
    lines.append("")
    txt_path.write_text("\n".join(lines) + "\n")


def _print_summary(result: PipelineResult) -> None:
    print()
    print(f"workspace:      {result.workspace}")
    print(f"template_root:  {result.template_root}")
    print(f"output:         {result.output}")
    print(f"expected_slide_count: {result.expected_slide_count}")
    print()
    for s in result.stages:
        status = "SKIP" if s.skipped else ("PASS" if s.ok else "FAIL")
        print(
            f"  [{status}] {s.name} "
            f"(exit={s.exit_code}, "
            f"duration={s.duration_s:.3f}s)"
        )
        if not s.ok and not s.skipped:
            tail = s.stderr.strip().splitlines()[-5:]
            for ln in tail:
                print(f"      {ln}")
    print()
    if result.overall_ok:
        print(
            f"OK: pipeline succeeded for workspace {result.workspace}; "
            f"PPTX written to {result.output}."
        )
    else:
        first_fail = next(
            (s for s in result.stages if not s.ok and not s.skipped),
            None,
        )
        if first_fail is not None:
            print(
                f"FAIL: pipeline aborted at stage {first_fail.name!r} "
                f"(exit={first_fail.exit_code}). "
                f"No partial artifacts should be trusted."
            )
        else:
            print("FAIL: pipeline did not complete cleanly.")


# ---------------------------------------------------------------------------
# Self-test scenarios. Built on top of a small synthetic example copied
# into a tempdir per scenario. Each scenario invokes this very script
# via subprocess (so the real argparse + main() flow is exercised, not
# an in-process shortcut) and asserts both the exit code and the
# observable side-effects (output existence, prior-artifact checksum,
# canary survival, SKIP markers in stdout).
# ---------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    name: str
    ok: bool
    detail: str = ""


_SELF_TEST_EXAMPLE = "synthetic_8_page_product_brief"
_SELF_TEST_TEMPLATE_ROOT = REPO_ROOT / "templates" / "layouts"


def _invoke_runner(extra_args: list[str]) -> tuple[int, str, str]:
    """Spawn this very script as a subprocess and capture its exit
    code + stdout + stderr. Using the live entry point (not an
    in-process call) gives the self-test full fidelity for the
    argparse + main() flow exercised by the user."""
    cmd = [sys.executable, str(Path(__file__).resolve())] + extra_args
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _copy_synthetic_workspace(dst: Path) -> None:
    src = REPO_ROOT / "examples" / _SELF_TEST_EXAMPLE
    shutil.copytree(src, dst)


def _tamper_planned_slide_count(workspace: Path) -> None:
    """Force planned_slide_count != len(slides). This is the same
    mutation negative_planner_semantics_tempfixture_checks uses, and
    it makes validate_workspace fail closed — but no earlier gate
    (the runner's up-front --output checks) is touched."""
    p = workspace / "deck_plan.json"
    deck = json.loads(p.read_text())
    deck["planning"]["planned_slide_count"] = 99
    p.write_text(json.dumps(deck, indent=2))


def _scenario_happy_path(td: Path) -> ScenarioResult:
    ws = td / "ws_happy"
    _copy_synthetic_workspace(ws)
    out = td / "happy.pptx"
    rc, sout, _serr = _invoke_runner([
        "--workspace", str(ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
    ])
    expected_passes = [
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
        and "OK: pipeline succeeded" in sout
        and all(line in sout for line in expected_passes)
    )
    return ScenarioResult(
        "happy path: a prepared workspace exports + validates end-to-end "
        "with every stage PASS",
        ok,
        (f"rc={rc}, output_is_file={out.is_file()}, "
         f"all_pass_lines={all(line in sout for line in expected_passes)}, "
         f"ok_marker={'OK: pipeline succeeded' in sout}"
         if not ok else ""),
    )


def _scenario_wrong_extension(td: Path, shared_ws: Path) -> ScenarioResult:
    bad_out = td / "fail.txt"
    rc, _sout, serr = _invoke_runner([
        "--workspace", str(shared_ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(bad_out),
    ])
    ok = (
        rc == 2
        and "must end in .pptx" in serr
        and not bad_out.exists()
    )
    return ScenarioResult(
        "wrong --output extension fails closed before any stage runs "
        "(no .pptx produced)",
        ok,
        (f"rc={rc}, extension_marker={'must end in .pptx' in serr}, "
         f"output_exists={bad_out.exists()}"
         if not ok else ""),
    )


def _scenario_output_inside_workspace(
    td: Path, shared_ws: Path,
) -> ScenarioResult:
    inside_out = shared_ws / "inside.pptx"
    rc, _sout, serr = _invoke_runner([
        "--workspace", str(shared_ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(inside_out),
    ])
    ok = (
        rc == 2
        and "inside the workspace" in serr
        and not inside_out.exists()
    )
    return ScenarioResult(
        "--output landing inside the workspace fails closed before any "
        "stage runs (no .pptx written inside the workspace tree)",
        ok,
        (f"rc={rc}, inside_marker={'inside the workspace' in serr}, "
         f"output_exists={inside_out.exists()}"
         if not ok else ""),
    )


def _scenario_report_dir_inside_workspace(
    td: Path, shared_ws: Path,
) -> ScenarioResult:
    """The runner contract keeps the workspace read-only except for
    render_models/ and svg_previews/, so a --report-dir pointed
    inside the workspace must be refused before any stage runs.
    Output is placed outside the workspace so the only thing under
    test is the --report-dir gate."""
    out = td / "report_dir_inside.pptx"
    inside_report_dir = shared_ws / "reports_inside"
    rc, _sout, serr = _invoke_runner([
        "--workspace", str(shared_ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
        "--report-dir", str(inside_report_dir),
    ])
    ok = (
        rc == 2
        and "--report-dir" in serr
        and "inside the workspace" in serr
        and not inside_report_dir.exists()
        and not out.exists()
    )
    return ScenarioResult(
        "--report-dir landing inside the workspace fails closed before "
        "any stage runs (no report files written inside the workspace)",
        ok,
        (f"rc={rc}, report_dir_marker={'--report-dir' in serr}, "
         f"inside_marker={'inside the workspace' in serr}, "
         f"report_dir_exists={inside_report_dir.exists()}, "
         f"output_exists={out.exists()}"
         if not ok else ""),
    )


def _scenario_symlink_output(
    td: Path, shared_ws: Path,
) -> ScenarioResult:
    target = td / "sym_target.pptx"
    target_bytes = b"PRIOR ARTIFACT BYTES"
    target.write_bytes(target_bytes)
    sym = td / "sym_link.pptx"
    sym.symlink_to(target)
    rc, _sout, serr = _invoke_runner([
        "--workspace", str(shared_ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(sym),
    ])
    ok = (
        rc == 2
        and "symlink" in serr
        and target.is_file()
        and target.read_bytes() == target_bytes
        and sym.is_symlink()
    )
    return ScenarioResult(
        "pre-existing symlink at --output is refused and the symlink "
        "target is untouched",
        ok,
        (f"rc={rc}, symlink_marker={'symlink' in serr}, "
         f"target_bytes_match={target.read_bytes() == target_bytes}, "
         f"sym_still_symlink={sym.is_symlink()}"
         if not ok else ""),
    )


def _scenario_directory_at_output(
    td: Path, shared_ws: Path,
) -> ScenarioResult:
    dir_out = td / "Documents.pptx"
    dir_out.mkdir()
    canary = dir_out / "important.txt"
    canary_text = "DO NOT DELETE"
    canary.write_text(canary_text)
    rc, _sout, serr = _invoke_runner([
        "--workspace", str(shared_ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(dir_out),
    ])
    ok = (
        rc == 2
        and "not a regular file" in serr
        and dir_out.is_dir()
        and canary.is_file()
        and canary.read_text() == canary_text
    )
    return ScenarioResult(
        "pre-existing directory named *.pptx at --output is refused and "
        "its contents are preserved (no recursive deletion)",
        ok,
        (f"rc={rc}, non_regular_marker={'not a regular file' in serr}, "
         f"canary_ok={canary.is_file() and canary.read_text() == canary_text}"
         if not ok else ""),
    )


def _scenario_upstream_failure_skips_downstream(td: Path) -> ScenarioResult:
    ws = td / "ws_tampered"
    _copy_synthetic_workspace(ws)
    _tamper_planned_slide_count(ws)
    out = td / "tampered.pptx"
    rc, sout, _serr = _invoke_runner([
        "--workspace", str(ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
    ])
    expected_skips = [
        "[SKIP] generate_render_models",
        "[SKIP] generate_svg_previews",
        "[SKIP] export_pptx",
        "[SKIP] validate_pptx_contract",
    ]
    ok = (
        rc == 1
        and "[FAIL] validate_workspace" in sout
        and all(line in sout for line in expected_skips)
        and not out.exists()
    )
    return ScenarioResult(
        "validate_workspace failure aborts the run and every downstream "
        "stage is recorded as [SKIP] (not silently passing); no .pptx "
        "is written",
        ok,
        (f"rc={rc}, fail_marker={'[FAIL] validate_workspace' in sout}, "
         f"all_skips_present={all(line in sout for line in expected_skips)}, "
         f"output_exists={out.exists()}"
         if not ok else ""),
    )


def _scenario_prior_pptx_preserved_on_early_failure(
    td: Path,
) -> ScenarioResult:
    ws = td / "ws_preserve"
    _copy_synthetic_workspace(ws)
    _tamper_planned_slide_count(ws)
    out = td / "prior.pptx"
    prior_bytes = b"PREVIOUS GOOD ARTIFACT BYTES"
    out.write_bytes(prior_bytes)
    sum_before = hashlib.sha256(prior_bytes).hexdigest()
    rc, _sout, _serr = _invoke_runner([
        "--workspace", str(ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
    ])
    sum_after = (
        hashlib.sha256(out.read_bytes()).hexdigest() if out.is_file() else ""
    )
    ok = (
        rc == 1
        and out.is_file()
        and sum_before == sum_after
        and out.read_bytes() == prior_bytes
    )
    return ScenarioResult(
        "pre-existing regular .pptx at --output is NOT deleted when "
        "validate_workspace fails before export (byte-identical to the "
        "prior artifact)",
        ok,
        (f"rc={rc}, output_is_file={out.is_file()}, "
         f"sha256_match={sum_before == sum_after}, "
         f"bytes_match={out.is_file() and out.read_bytes() == prior_bytes}"
         if not ok else ""),
    )


def _run_self_tests() -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    src = REPO_ROOT / "examples" / _SELF_TEST_EXAMPLE
    if not src.is_dir():
        results.append(ScenarioResult(
            f"fixture: examples/{_SELF_TEST_EXAMPLE}/ exists "
            f"(required for self-test)",
            False,
            f"not found: {src}",
        ))
        return results
    if not _SELF_TEST_TEMPLATE_ROOT.is_dir():
        results.append(ScenarioResult(
            "fixture: templates/layouts/ exists (required for self-test)",
            False,
            f"not found: {_SELF_TEST_TEMPLATE_ROOT}",
        ))
        return results
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        # Shared workspace for scenarios whose failure fires on the
        # runner's up-front --output gates (wrong extension, inside
        # workspace, symlink, directory). Those gates fire BEFORE
        # any per-stage subprocess is launched, so the contents of
        # the workspace are not consulted — only its existence as a
        # directory is needed.
        shared_ws = td / "shared_ws"
        _copy_synthetic_workspace(shared_ws)

        results.append(_scenario_happy_path(td))
        results.append(_scenario_wrong_extension(td, shared_ws))
        results.append(_scenario_output_inside_workspace(td, shared_ws))
        results.append(_scenario_report_dir_inside_workspace(td, shared_ws))
        results.append(_scenario_symlink_output(td, shared_ws))
        results.append(_scenario_directory_at_output(td, shared_ws))
        results.append(_scenario_upstream_failure_skips_downstream(td))
        results.append(_scenario_prior_pptx_preserved_on_early_failure(td))
    return results


def _print_self_test_results(results: list[ScenarioResult]) -> int:
    fails = 0
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        suffix = f" — {r.detail}" if r.detail and not r.ok else ""
        print(f"  [{mark}] {r.name}{suffix}")
        if not r.ok:
            fails += 1
    return fails


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic local end-to-end pipeline runner for prepared "
            "workspaces. Chains validate_workspace -> "
            "generate_render_models -> generate_svg_previews -> "
            "export_pptx -> validate_pptx_contract. Fails closed if any "
            "stage fails. Requires an already-prepared workspace "
            "(deck_brief.json, deck_plan.json, slide_plans/, "
            "design_system.json, image_manifest.json) — this runner does "
            "NOT plan a deck from a raw prompt; that pipeline is TODO. "
            "The runner regenerates <workspace>/render_models/*.json and "
            "<workspace>/svg_previews/*.svg in place, but the final "
            "--output PPTX must live OUTSIDE the workspace."
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Prepared workspace directory.",
    )
    parser.add_argument(
        "--template-root", type=Path, default=None,
        help="Directory containing template subdirectories.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help=(
            "Path to write the .pptx output. Extension must be .pptx. "
            "MUST live outside --workspace."
        ),
    )
    parser.add_argument(
        "--report-dir", type=Path, default=None,
        help=(
            "Optional directory under which pipeline_report.json and "
            "pipeline_report.txt will be written. Created if missing."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run the in-script tempfixture scenarios: happy path "
            "export+validation; wrong --output extension; --output "
            "landing inside the workspace; --report-dir landing "
            "inside the workspace; pre-existing symlink at --output; "
            "pre-existing directory named *.pptx at --output; "
            "validate_workspace failure cascading [SKIP] across every "
            "downstream stage; pre-existing regular .pptx preserved "
            "when validate_workspace fails before export. Exits "
            "non-zero if any scenario does not behave as expected. "
            "Mutually exclusive with --workspace / --template-root / "
            "--output / --report-dir."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if any(
            v is not None for v in (
                args.workspace, args.template_root,
                args.output, args.report_dir,
            )
        ):
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
            "OK (self-test): every fail-closed gate is caught and the "
            "happy-path workspace exports + validates end-to-end."
        )
        return 0

    missing = [
        name for name, value in (
            ("--workspace", args.workspace),
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

    if not args.workspace.is_dir():
        print(
            f"FAIL: workspace is not a directory: {args.workspace}",
            file=sys.stderr,
        )
        return 2
    if not args.template_root.is_dir():
        print(
            f"FAIL: template-root is not a directory: {args.template_root}",
            file=sys.stderr,
        )
        return 2
    if args.output.suffix.lower() != ".pptx":
        print(
            f"FAIL: --output must end in .pptx; got {args.output}",
            file=sys.stderr,
        )
        return 2
    # Refuse a runner invocation that would write the final PPTX
    # anywhere inside the workspace tree. The runner DOES write to
    # <workspace>/render_models/*.json and <workspace>/svg_previews/*.svg
    # via the generator stages (those subdirectories are generator-owned
    # and are regenerated in place), but the final --output PPTX must
    # live outside the workspace — the prepared-input artifacts
    # (deck_brief, deck_plan, slide_plans, design_system, image_manifest)
    # are treated as read-only, and a stray .pptx anywhere under the
    # workspace would be picked up by validate_workspace on a later run.
    try:
        args.output.resolve().relative_to(args.workspace.resolve())
    except ValueError:
        pass
    else:
        print(
            f"FAIL: --output {args.output} would land inside the "
            f"workspace {args.workspace}; pick a path outside the "
            f"workspace tree (render_models/ and svg_previews/ are "
            f"regenerated in place, but the final .pptx must live "
            f"outside).",
            file=sys.stderr,
        )
        return 2

    # Apply the same inside-workspace gate to --report-dir. The
    # pipeline_report.json / pipeline_report.txt files are runner
    # outputs, not pipeline artifacts, so they MUST stay outside the
    # workspace just like the final PPTX. Letting --report-dir land
    # inside the workspace would (a) mkdir an extra directory that
    # validate_workspace's render_models/coverage gate could
    # later trip over, and (b) silently smuggle non-pipeline files
    # into a tree this runner has explicitly contracted to keep
    # read-only (apart from render_models/ and svg_previews/).
    if args.report_dir is not None:
        try:
            args.report_dir.resolve().relative_to(args.workspace.resolve())
        except ValueError:
            pass
        else:
            print(
                f"FAIL: --report-dir {args.report_dir} would land inside "
                f"the workspace {args.workspace}; pick a path outside "
                f"the workspace tree (the runner contract keeps the "
                f"workspace read-only except for render_models/ and "
                f"svg_previews/).",
                file=sys.stderr,
            )
            return 2

    # Refuse a pre-existing --output that is anything other than a
    # regular file. The exporter overwrites a regular file in place
    # (zipfile.ZipFile in 'w' mode truncates), so a stale .pptx from a
    # previous successful run is fine — it gets replaced atomically
    # only if the pipeline reaches the export stage. A directory or
    # symlink at this path is rejected here so that:
    #   - a typo'd / shadowed directory whose name happens to end in
    #     .pptx is never recursively touched by this runner;
    #   - a symlink is never silently followed to overwrite an
    #     unrelated target.
    # The .pptx extension check is not sufficient on its own; a real
    # directory can be named e.g. `Documents.pptx/`. We do NOT delete
    # any pre-existing output up front — a transient failure in an
    # earlier stage (e.g. validate_workspace) would otherwise destroy
    # the caller's prior good artifact.
    if args.output.is_symlink():
        print(
            f"FAIL: --output {args.output} is a symlink; refusing to "
            f"follow it. Pass a regular file path.",
            file=sys.stderr,
        )
        return 2
    if args.output.exists() and not args.output.is_file():
        print(
            f"FAIL: --output {args.output} exists and is not a regular "
            f"file (looks like a directory); refusing to overwrite.",
            file=sys.stderr,
        )
        return 2

    # Pre-create the output's parent so a downstream export failure is
    # never confused with a missing-directory error.
    args.output.parent.mkdir(parents=True, exist_ok=True)

    result = run_pipeline(
        workspace=args.workspace,
        template_root=args.template_root,
        output=args.output,
        report_dir=args.report_dir,
    )

    for stage in result.stages:
        print(f"\n--- {stage.name} ---")
        if stage.skipped:
            print(f"[SKIP] {stage.skip_reason}")
            continue
        if stage.stdout:
            print(stage.stdout, end="" if stage.stdout.endswith("\n") else "\n")
        if stage.stderr:
            print(stage.stderr, end="" if stage.stderr.endswith("\n") else "\n",
                  file=sys.stderr)

    if args.report_dir is not None:
        _write_reports(result, args.report_dir)
        print(
            f"\nReport written to {args.report_dir / 'pipeline_report.json'} "
            f"and {args.report_dir / 'pipeline_report.txt'}."
        )

    _print_summary(result)

    return 0 if result.overall_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
