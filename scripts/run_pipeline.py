#!/usr/bin/env python3
"""Deterministic local end-to-end pipeline runner for prepared workspaces.

Chains the existing per-stage scripts in a single command:

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
    6. scripts/inspect_pptx_inventory.py (deterministic OOXML structure
                                          readback — only invoked when
                                          --report-dir is supplied; writes
                                          <report-dir>/inventory.json after
                                          validate_pptx_contract has passed.
                                          Evidence only: OOXML structure
                                          counts, media / relationship
                                          report, and findings — NOT proof
                                          of full PowerPoint editability)

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
    --report-dir     optional directory under which `pipeline_report.json`,
                     `pipeline_report.txt`, and `inventory.json` are
                     written. When omitted, no inventory is produced (the
                     inspect_pptx_inventory stage is not added at all).
                     MUST be outside --workspace (the workspace contract
                     above applies to reports + inventory too — only
                     render_models/ and svg_previews/ are runner-writable
                     inside it).
    --self-test      run the in-script tempfixture scenarios (happy path,
                     wrong --output extension, --output inside workspace,
                     --report-dir inside workspace, pre-existing regular
                     file at --report-dir, pre-existing symlink at
                     --report-dir, pre-existing read-only directory at
                     --report-dir (writability probe; skipped under root),
                     pre-existing symlink at <report-dir>/pipeline_report.json
                     (target untouched), pre-existing read-only
                     pipeline_report.txt (prior bytes preserved; skipped
                     under root), happy-path --report-dir outside the
                     workspace writes pipeline_report.{json,txt},
                     happy-path --report-dir writes inventory.json,
                     happy-path WITHOUT --report-dir produces no
                     inventory anywhere, pre-existing symlink at
                     <report-dir>/inventory.json refused, validate
                     failure with --report-dir cascades [SKIP] to
                     inspect_pptx_inventory, stale inventory.json
                     from a prior successful run is removed before
                     a later failing rerun's stages execute, a LATE
                     preflight failure (--output is a symlink) with
                     the same --report-dir preserves the prior
                     inventory.json byte-identical (the destructive
                     unlink only runs AFTER every preflight gate),
                     --output parent path blocked by a regular file
                     returns rc=2 with a clean FAIL diagnostic and no
                     Python traceback,
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
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

# The two files _write_reports() writes inside --report-dir. The
# preflight gate probes BOTH of these names specifically, not just
# the parent directory, because the parent-directory writability
# probe does NOT catch a pre-existing pipeline_report.{json,txt}
# that is itself a symlink (Path.write_text would follow it), a
# directory (write_text → IsADirectoryError), or a read-only
# regular file (write_text → PermissionError).
_REPORT_FILENAMES = ("pipeline_report.json", "pipeline_report.txt")

# Inventory file written into --report-dir by the
# inspect_pptx_inventory stage AFTER validate_pptx_contract has
# passed. Only produced when --report-dir is supplied — a no-report-dir
# invocation neither adds the stage nor creates the file. The preflight
# gate probes this name the same way it probes the pipeline_report.*
# files because the inventory subprocess uses Path.write_text(), which
# follows symlinks (silently redirecting writes), raises
# IsADirectoryError on a directory, and PermissionError on a read-only
# regular file. Without the up-front gate the pipeline would validate
# / generate / export (writing the PPTX!) and only then crash inside
# the inspect_pptx_inventory subprocess. Catching all three states
# up-front keeps the failure surface observable BEFORE any stage runs.
_INVENTORY_FILENAME = "inventory.json"


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

    # Optional inventory readback. Only added to the stage list when
    # --report-dir is supplied — a no-report-dir run must not create
    # extra repo artifacts. The aborted-cascade below treats this like
    # any other stage: if any upstream stage fails, the inventory stage
    # is recorded as [SKIP] and the subprocess is NOT invoked, so the
    # inventory subprocess only runs after the .pptx has been written
    # AND validate_pptx_contract has passed. A non-zero exit from the
    # inventory subprocess (invocation error OR findings present) fails
    # the pipeline closed — there is no fail-open path.
    if report_dir is not None:
        inventory_cmd = [
            py, str(SCRIPTS_DIR / "inspect_pptx_inventory.py"),
            "--pptx", str(output),
            "--out", str(report_dir / _INVENTORY_FILENAME),
        ]
        stages.append(("inspect_pptx_inventory", inventory_cmd))

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
    json_name, txt_name = _REPORT_FILENAMES
    json_path = report_dir / json_name
    txt_path = report_dir / txt_name

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


def _scenario_report_dir_is_regular_file(
    td: Path, shared_ws: Path,
) -> ScenarioResult:
    """A regular file at --report-dir must fail closed BEFORE any
    pipeline stage runs. Without the up-front gate, the runner would
    validate / generate / export (writing the PPTX!) and only then
    crash inside _write_reports() when mkdir() raises
    FileExistsError — so the failure surface check must observe
    *both* the exit-code path and the absence of any side-effect
    .pptx."""
    out = td / "report_is_file.pptx"
    report_path = td / "reports_as_file"
    prior_text = "PRIOR REPORT-PATH FILE BYTES"
    report_path.write_text(prior_text)
    rc, _sout, serr = _invoke_runner([
        "--workspace", str(shared_ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
        "--report-dir", str(report_path),
    ])
    ok = (
        rc == 2
        and "--report-dir" in serr
        and "not a directory" in serr
        and not out.exists()
        and report_path.is_file()
        and report_path.read_text() == prior_text
    )
    return ScenarioResult(
        "pre-existing regular file at --report-dir is refused BEFORE "
        "any pipeline stage runs (no PPTX written; the prior file "
        "is preserved byte-identical)",
        ok,
        (f"rc={rc}, report_dir_marker={'--report-dir' in serr}, "
         f"not_dir_marker={'not a directory' in serr}, "
         f"output_exists={out.exists()}, "
         f"prior_preserved="
         f"{report_path.is_file() and report_path.read_text() == prior_text}"
         if not ok else ""),
    )


def _scenario_report_dir_is_symlink(
    td: Path, shared_ws: Path,
) -> ScenarioResult:
    """A pre-existing symlink at --report-dir is refused for
    consistency with --output. The symlink's target directory must
    be untouched: no pipeline_report.{json,txt} written into it and
    a canary file inside the target survives unchanged."""
    out = td / "report_sym.pptx"
    target = td / "real_report_target_dir"
    target.mkdir()
    canary = target / "canary.txt"
    canary_text = "DO NOT TOUCH REPORT TARGET"
    canary.write_text(canary_text)
    sym = td / "reports_link"
    sym.symlink_to(target)
    rc, _sout, serr = _invoke_runner([
        "--workspace", str(shared_ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
        "--report-dir", str(sym),
    ])
    ok = (
        rc == 2
        and "--report-dir" in serr
        and "symlink" in serr
        and not out.exists()
        and sym.is_symlink()
        and target.is_dir()
        and canary.is_file()
        and canary.read_text() == canary_text
        and not (target / "pipeline_report.json").exists()
        and not (target / "pipeline_report.txt").exists()
    )
    return ScenarioResult(
        "pre-existing symlink at --report-dir is refused and the "
        "symlink's target directory is untouched (no pipeline_report "
        "files written; canary inside the target preserved)",
        ok,
        (f"rc={rc}, report_dir_marker={'--report-dir' in serr}, "
         f"symlink_marker={'symlink' in serr}, "
         f"output_exists={out.exists()}, "
         f"sym_still_symlink={sym.is_symlink()}, "
         f"canary_intact="
         f"{canary.is_file() and canary.read_text() == canary_text}, "
         f"no_report_json_in_target="
         f"{not (target / 'pipeline_report.json').exists()}, "
         f"no_report_txt_in_target="
         f"{not (target / 'pipeline_report.txt').exists()}"
         if not ok else ""),
    )


def _scenario_report_dir_readonly_dir(
    td: Path, shared_ws: Path,
) -> ScenarioResult:
    """A pre-existing directory at --report-dir that exists but is
    not writable by the current user must fail closed BEFORE any
    pipeline stage runs. mkdir(parents=True, exist_ok=True) returns
    success on an existing read-only directory without testing
    write access — the runner therefore probes writability with a
    NamedTemporaryFile inside the directory and refuses the run if
    the probe cannot be created. Without this probe, the pipeline
    would validate / generate / export (writing the PPTX!) and
    only then crash inside _write_reports() on
    pipeline_report.json's open()."""
    import os
    import stat

    out = td / "readonly_report.pptx"
    report_dir = td / "readonly_reports"
    report_dir.mkdir()
    original_mode = report_dir.stat().st_mode
    if os.geteuid() == 0:
        # chmod cannot meaningfully restrict root, so the probe
        # would succeed and this scenario would mis-report. Mark
        # the scenario as a no-op pass under root and return.
        return ScenarioResult(
            "pre-existing read-only directory at --report-dir is "
            "refused BEFORE any pipeline stage runs (no PPTX "
            "written; no report files written into the read-only "
            "directory) — skipped under root because chmod cannot "
            "restrict root",
            True,
            "",
        )
    try:
        os.chmod(report_dir, stat.S_IRUSR | stat.S_IXUSR)
        rc, _sout, serr = _invoke_runner([
            "--workspace", str(shared_ws),
            "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
            "--output", str(out),
            "--report-dir", str(report_dir),
        ])
        ok = (
            rc == 2
            and "--report-dir" in serr
            and "not writable" in serr
            and not out.exists()
            and not (report_dir / "pipeline_report.json").exists()
            and not (report_dir / "pipeline_report.txt").exists()
        )
        detail = (
            f"rc={rc}, report_dir_marker={'--report-dir' in serr}, "
            f"not_writable_marker={'not writable' in serr}, "
            f"output_exists={out.exists()}"
            if not ok else ""
        )
    finally:
        # Restore mode so the TemporaryDirectory cleanup at the end
        # of _run_self_tests() can remove the directory.
        os.chmod(report_dir, original_mode)
    return ScenarioResult(
        "pre-existing read-only directory at --report-dir is "
        "refused BEFORE any pipeline stage runs (no PPTX written; "
        "no report files written into the read-only directory)",
        ok,
        detail,
    )


def _scenario_report_file_is_symlink(
    td: Path, shared_ws: Path,
) -> ScenarioResult:
    """A pre-existing pipeline_report.json that is a symlink at the
    moment the runner starts must fail closed BEFORE any pipeline
    stage runs. Without this gate, _write_reports() would follow
    the symlink and overwrite the unrelated target — same
    anti-pattern --output forbids. The symlink's target must be
    untouched."""
    out = td / "report_file_sym.pptx"
    report_dir = td / "reports_with_symlink_inside"
    report_dir.mkdir()
    target = td / "report_symlink_target.txt"
    target_bytes = b"DO NOT OVERWRITE THIS UNRELATED TARGET"
    target.write_bytes(target_bytes)
    sym = report_dir / "pipeline_report.json"
    sym.symlink_to(target)
    rc, _sout, serr = _invoke_runner([
        "--workspace", str(shared_ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
        "--report-dir", str(report_dir),
    ])
    ok = (
        rc == 2
        and "pipeline_report.json" in serr
        and "symlink" in serr
        and not out.exists()
        and sym.is_symlink()
        and target.is_file()
        and target.read_bytes() == target_bytes
    )
    return ScenarioResult(
        "pre-existing symlink at <report-dir>/pipeline_report.json "
        "is refused BEFORE any pipeline stage runs; no PPTX written, "
        "the symlink's unrelated target is preserved byte-identical",
        ok,
        (f"rc={rc}, file_marker={'pipeline_report.json' in serr}, "
         f"symlink_marker={'symlink' in serr}, "
         f"output_exists={out.exists()}, "
         f"sym_still_symlink={sym.is_symlink()}, "
         f"target_bytes_match={target.read_bytes() == target_bytes}"
         if not ok else ""),
    )


def _scenario_report_file_readonly(
    td: Path, shared_ws: Path,
) -> ScenarioResult:
    """A pre-existing pipeline_report.txt that is a read-only
    regular file must fail closed BEFORE any pipeline stage runs.
    Path.write_text would otherwise raise PermissionError when
    truncating the file — but only AFTER the PPTX has already been
    written. The prior file content must be preserved."""
    import stat

    out = td / "report_file_readonly.pptx"
    report_dir = td / "reports_with_readonly_file"
    report_dir.mkdir()
    if os.geteuid() == 0:
        return ScenarioResult(
            "pre-existing read-only pipeline_report.txt at "
            "<report-dir>/pipeline_report.txt is refused BEFORE any "
            "pipeline stage runs — skipped under root because chmod "
            "cannot restrict root",
            True,
            "",
        )
    rp = report_dir / "pipeline_report.txt"
    prior_text = "PRIOR READ-ONLY REPORT CONTENT"
    rp.write_text(prior_text)
    original_mode = rp.stat().st_mode
    try:
        os.chmod(rp, stat.S_IRUSR)  # r--, no write
        rc, _sout, serr = _invoke_runner([
            "--workspace", str(shared_ws),
            "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
            "--output", str(out),
            "--report-dir", str(report_dir),
        ])
        ok = (
            rc == 2
            and "pipeline_report.txt" in serr
            and "not writable" in serr
            and not out.exists()
            and rp.is_file()
            and rp.read_text() == prior_text
        )
        detail = (
            f"rc={rc}, file_marker={'pipeline_report.txt' in serr}, "
            f"not_writable_marker={'not writable' in serr}, "
            f"output_exists={out.exists()}, "
            f"prior_preserved="
            f"{rp.is_file() and rp.read_text() == prior_text}"
            if not ok else ""
        )
    finally:
        os.chmod(rp, original_mode)
    return ScenarioResult(
        "pre-existing read-only pipeline_report.txt at "
        "<report-dir>/pipeline_report.txt is refused BEFORE any "
        "pipeline stage runs (no PPTX written; prior file content "
        "preserved byte-identical)",
        ok,
        detail,
    )


def _scenario_report_dir_outside_writes_reports(td: Path) -> ScenarioResult:
    """A happy-path run with --report-dir outside the workspace
    actually writes pipeline_report.json + pipeline_report.txt.
    Verifies that the new pre-create gate does not regress the
    post-export report-writing path: the directory is created (if
    it did not exist), both files exist, the JSON is loadable, and
    the JSON's overall_ok matches the pipeline's success."""
    ws = td / "ws_reports_outside"
    _copy_synthetic_workspace(ws)
    out = td / "happy_reports.pptx"
    report_dir = td / "happy_reports_dir"
    rc, sout, _serr = _invoke_runner([
        "--workspace", str(ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
        "--report-dir", str(report_dir),
    ])
    json_path = report_dir / "pipeline_report.json"
    txt_path = report_dir / "pipeline_report.txt"
    ok = (
        rc == 0
        and out.is_file()
        and out.stat().st_size > 0
        and "OK: pipeline succeeded" in sout
        and report_dir.is_dir()
        and not report_dir.is_symlink()
        and json_path.is_file()
        and txt_path.is_file()
        and txt_path.read_text().strip() != ""
    )
    if ok:
        try:
            payload = json.loads(json_path.read_text())
            ok = (
                payload.get("overall_ok") is True
                and isinstance(payload.get("stages"), list)
                and len(payload["stages"]) >= 5
            )
        except (json.JSONDecodeError, OSError):
            ok = False
    return ScenarioResult(
        "happy-path --report-dir outside the workspace writes "
        "pipeline_report.json + pipeline_report.txt; the JSON is "
        "loadable with overall_ok=true and a populated stages list",
        ok,
        (f"rc={rc}, output_is_file={out.is_file()}, "
         f"report_dir_is_dir={report_dir.is_dir()}, "
         f"json_is_file={json_path.is_file()}, "
         f"txt_is_file={txt_path.is_file()}"
         if not ok else ""),
    )


def _scenario_inventory_written_with_report_dir(td: Path) -> ScenarioResult:
    """Happy-path run with --report-dir actually writes
    <report-dir>/inventory.json alongside the pipeline_report.*
    files. The JSON must be loadable, declare `ok=true`, carry the
    evidence_basis line, and include the slides / media_parts /
    relationships / findings keys this side-output contracts on. We
    also assert the [PASS] inspect_pptx_inventory stage marker so a
    regression that drops the stage from the list (instead of just
    its file) is caught."""
    ws = td / "ws_inv_happy"
    _copy_synthetic_workspace(ws)
    out = td / "inv_happy.pptx"
    report_dir = td / "inv_happy_reports_dir"
    rc, sout, _serr = _invoke_runner([
        "--workspace", str(ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
        "--report-dir", str(report_dir),
    ])
    inv_path = report_dir / "inventory.json"
    ok = (
        rc == 0
        and out.is_file()
        and "OK: pipeline succeeded" in sout
        and "[PASS] inspect_pptx_inventory" in sout
        and inv_path.is_file()
        and not inv_path.is_symlink()
        and "OOXML structure only; not proof of full PowerPoint editability"
        in sout
    )
    if ok:
        try:
            inv = json.loads(inv_path.read_text())
            ok = (
                inv.get("ok") is True
                and inv.get("evidence_basis") == (
                    "OOXML structure only; not proof of full "
                    "PowerPoint editability"
                )
                and isinstance(inv.get("slides"), list)
                and isinstance(inv.get("media_parts"), list)
                and isinstance(inv.get("relationships"), list)
                and isinstance(inv.get("findings"), list)
                and inv.get("findings") == []
                and isinstance(inv.get("slide_count"), int)
                and inv["slide_count"] == len(inv["slides"])
            )
        except (json.JSONDecodeError, OSError):
            ok = False
    return ScenarioResult(
        "happy-path --report-dir writes inventory.json with ok=true, "
        "the evidence_basis framing line, and the slides / media_parts "
        "/ relationships / findings keys; the inspect_pptx_inventory "
        "stage reports [PASS] and the runner mentions the inventory "
        "path with the evidence-only caveat",
        ok,
        (f"rc={rc}, inv_is_file={inv_path.is_file()}, "
         f"pass_marker={'[PASS] inspect_pptx_inventory' in sout}, "
         f"caveat_marker={'not proof of full PowerPoint editability' in sout}"
         if not ok else ""),
    )


def _scenario_no_inventory_without_report_dir(td: Path) -> ScenarioResult:
    """Happy-path run WITHOUT --report-dir must NOT create any
    inventory.json. The inspect_pptx_inventory stage is not even
    added to the stage list so no [PASS]/[SKIP]/[FAIL]
    inspect_pptx_inventory line appears. We scope the rglob to a
    dedicated subdir under `td` because other scenarios share `td`
    and DO produce inventory.json — a parent-wide rglob would
    misattribute their files to this scenario."""
    scenario_root = td / "no_inv_scenario_root"
    scenario_root.mkdir()
    ws = scenario_root / "ws"
    _copy_synthetic_workspace(ws)
    out = scenario_root / "no_inv.pptx"
    rc, sout, _serr = _invoke_runner([
        "--workspace", str(ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
    ])
    inventory_anywhere = list(scenario_root.rglob("inventory.json"))
    ok = (
        rc == 0
        and out.is_file()
        and "OK: pipeline succeeded" in sout
        and "inspect_pptx_inventory" not in sout
        and not inventory_anywhere
    )
    return ScenarioResult(
        "no --report-dir means no inventory: the inspect_pptx_inventory "
        "stage is not added to the stage list and no inventory.json is "
        "created anywhere under the dedicated scenario root",
        ok,
        (f"rc={rc}, output_is_file={out.is_file()}, "
         f"stage_absent={'inspect_pptx_inventory' not in sout}, "
         f"inventory_files={inventory_anywhere}"
         if not ok else ""),
    )


def _scenario_inventory_path_is_symlink(td: Path) -> ScenarioResult:
    """A pre-existing symlink at <report-dir>/inventory.json must
    fail closed BEFORE any pipeline stage runs. Without the gate the
    inventory subprocess would follow the link and overwrite an
    unrelated target — same anti-pattern --output and pipeline_report.*
    forbid. The symlink's target must be byte-identical after the
    refused run."""
    ws = td / "ws_inv_sym"
    _copy_synthetic_workspace(ws)
    out = td / "inv_sym.pptx"
    report_dir = td / "inv_sym_reports_dir"
    report_dir.mkdir()
    target = td / "inventory_symlink_target.txt"
    target_bytes = b"DO NOT OVERWRITE THIS UNRELATED INVENTORY TARGET"
    target.write_bytes(target_bytes)
    sym = report_dir / "inventory.json"
    sym.symlink_to(target)
    rc, _sout, serr = _invoke_runner([
        "--workspace", str(ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
        "--report-dir", str(report_dir),
    ])
    ok = (
        rc == 2
        and "inventory.json" in serr
        and "symlink" in serr
        and not out.exists()
        and sym.is_symlink()
        and target.is_file()
        and target.read_bytes() == target_bytes
    )
    return ScenarioResult(
        "pre-existing symlink at <report-dir>/inventory.json is "
        "refused BEFORE any pipeline stage runs; no PPTX written, "
        "the symlink's unrelated target is preserved byte-identical",
        ok,
        (f"rc={rc}, file_marker={'inventory.json' in serr}, "
         f"symlink_marker={'symlink' in serr}, "
         f"output_exists={out.exists()}, "
         f"sym_still_symlink={sym.is_symlink()}, "
         f"target_bytes_match={target.read_bytes() == target_bytes}"
         if not ok else ""),
    )


def _scenario_stale_inventory_removed_on_failed_rerun(td: Path) -> ScenarioResult:
    """Stale-inventory hygiene across reruns.

    Run 1: a happy path with --report-dir succeeds and leaves a
    fresh inventory.json on disk. Run 2: the same --report-dir is
    reused but the workspace is tampered so validate_workspace
    fails — the inspect_pptx_inventory stage MUST be [SKIP]'d for
    that run. Without the pre-stage cleanup of inventory.json, the
    Run-1 inventory.json would survive Run 2 untouched and the
    caller would see a fresh pipeline_report.{json,txt} marked
    FAIL alongside a stale inventory.json from Run 1 — easy to
    misread as evidence about the current (failing) run.

    We assert that after Run 2:
      - the pipeline returned non-zero;
      - the inspect_pptx_inventory stage is [SKIP]'d;
      - inventory.json does NOT exist in --report-dir;
      - pipeline_report.json and pipeline_report.txt DO exist and
        reflect the failing Run 2 (overall_ok=false).
    """
    ws_good = td / "ws_stale_good"
    _copy_synthetic_workspace(ws_good)
    out = td / "stale.pptx"
    report_dir = td / "stale_reports_dir"
    rc1, sout1, _serr1 = _invoke_runner([
        "--workspace", str(ws_good),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
        "--report-dir", str(report_dir),
    ])
    inv_path = report_dir / "inventory.json"
    run1_ok = (
        rc1 == 0
        and "OK: pipeline succeeded" in sout1
        and inv_path.is_file()
    )
    if not run1_ok:
        return ScenarioResult(
            "stale inventory hygiene: prior --report-dir run prep",
            False,
            f"run1 rc={rc1}, inv_present={inv_path.is_file()}",
        )
    run1_inv_bytes = inv_path.read_bytes()

    # Now mutate the workspace so Run 2 fails at validate_workspace.
    ws_bad = td / "ws_stale_bad"
    _copy_synthetic_workspace(ws_bad)
    _tamper_planned_slide_count(ws_bad)
    rc2, sout2, _serr2 = _invoke_runner([
        "--workspace", str(ws_bad),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
        "--report-dir", str(report_dir),
    ])
    report_json = report_dir / "pipeline_report.json"
    report_txt = report_dir / "pipeline_report.txt"
    ok = (
        rc2 == 1
        and "[FAIL] validate_workspace" in sout2
        and "[SKIP] inspect_pptx_inventory" in sout2
        and not inv_path.exists()
        and report_json.is_file()
        and report_txt.is_file()
    )
    if ok:
        try:
            payload = json.loads(report_json.read_text())
            ok = payload.get("overall_ok") is False
        except (json.JSONDecodeError, OSError):
            ok = False
    # Belt-and-braces: the Run-1 inventory bytes must not be
    # discoverable anywhere under report_dir after Run 2 (catches a
    # regression that moved the stale file elsewhere instead of
    # removing it).
    if ok:
        for p in report_dir.rglob("*"):
            if p.is_file() and p.read_bytes() == run1_inv_bytes:
                ok = False
                break
    return ScenarioResult(
        "stale inventory.json from a prior successful --report-dir "
        "run is removed BEFORE Run 2's stages execute, so a later "
        "failing rerun cannot leave a fresh FAIL pipeline_report "
        "next to a stale inventory.json the caller could misread",
        ok,
        (f"rc2={rc2}, "
         f"fail_marker={'[FAIL] validate_workspace' in sout2}, "
         f"skip_inv={'[SKIP] inspect_pptx_inventory' in sout2}, "
         f"inv_absent_after_rerun={not inv_path.exists()}, "
         f"report_json_present={report_json.is_file()}"
         if not ok else ""),
    )


def _scenario_output_parent_blocked_returns_rc2(td: Path) -> ScenarioResult:
    """args.output.parent.mkdir() must return rc=2 with a clean
    diagnostic, never traceback, when the parent path is blocked.

    The mkdir call is `mkdir(parents=True, exist_ok=True)`, whose
    Python semantics are: if the FINAL path component already
    exists as a NON-directory, raise FileExistsError (a subclass
    of OSError) even with exist_ok=True. Without an explicit
    try/except + return 2, that exception propagates and Python
    exits with rc=1 and a traceback — breaking the rc=2-on-every-
    preflight-refusal contract every other gate honors. CI / a
    review surface checking for rc=2 would silently miss the
    refusal class.

    Scenario:
      - Place a regular file at `td / "blocker"` (its name has no
        ".pptx" suffix so the --output-extension gate accepts it).
      - Pass `--output <blocker>/run.pptx` so the would-be parent
        directory IS that regular file.
      - The runner must (a) exit 2, (b) print a FAIL line to
        stderr naming the parent path and the OSError detail, AND
        (c) NOT emit a Python "Traceback (most recent call last):"
        in stderr.

    Additionally we add a --report-dir with a pre-existing
    inventory.json from a prior happy run and assert the inventory
    survives the refused run byte-identical — defense-in-depth
    that the destructive stale-inventory unlink still sits AFTER
    this preflight gate (so a guarded refusal here does not strand
    the caller without their prior evidence). The blocker file is
    also asserted byte-identical so the runner never tries to
    remove or overwrite arbitrary content at that path.
    """
    # Set up a prior good inventory.json under --report-dir.
    ws_prior = td / "ws_parent_prior"
    _copy_synthetic_workspace(ws_prior)
    good_out = td / "parent_good.pptx"
    report_dir = td / "parent_reports_dir"
    rc1, sout1, _serr1 = _invoke_runner([
        "--workspace", str(ws_prior),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(good_out),
        "--report-dir", str(report_dir),
    ])
    inv_path = report_dir / "inventory.json"
    if rc1 != 0 or "OK: pipeline succeeded" not in sout1 or not inv_path.is_file():
        return ScenarioResult(
            "output-parent blocked: Run 1 prep",
            False,
            f"rc1={rc1}, inv_present={inv_path.is_file()}",
        )
    prior_inv_bytes = inv_path.read_bytes()

    # Run 2: regular file at the would-be parent path.
    blocker = td / "blocker_for_parent"
    blocker_bytes = b"NOT A DIRECTORY - DO NOT MODIFY OR REMOVE"
    blocker.write_bytes(blocker_bytes)
    bad_out = blocker / "run.pptx"  # parent is a regular file
    ws_bad = td / "ws_parent_bad"
    _copy_synthetic_workspace(ws_bad)
    rc2, _sout2, serr2 = _invoke_runner([
        "--workspace", str(ws_bad),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(bad_out),
        "--report-dir", str(report_dir),
    ])
    ok = (
        rc2 == 2
        and "parent directory" in serr2
        and str(blocker) in serr2
        and "Traceback (most recent call last):" not in serr2
        and blocker.is_file()
        and blocker.read_bytes() == blocker_bytes
        and inv_path.is_file()
        and not inv_path.is_symlink()
        and inv_path.read_bytes() == prior_inv_bytes
    )
    return ScenarioResult(
        "--output parent path blocked by a regular file returns "
        "rc=2 with a clean FAIL diagnostic naming the parent path "
        "and the OSError detail — never a Python traceback. The "
        "blocker file and the prior --report-dir's inventory.json "
        "are both preserved byte-identical (the destructive "
        "stale-inventory unlink stays correctly placed AFTER this "
        "gate, so a guarded refusal here cannot strand the caller "
        "without their prior evidence)",
        ok,
        (f"rc2={rc2}, "
         f"parent_marker={'parent directory' in serr2}, "
         f"path_marker={str(blocker) in serr2}, "
         f"no_traceback={'Traceback (most recent call last):' not in serr2}, "
         f"blocker_intact="
         f"{blocker.is_file() and blocker.read_bytes() == blocker_bytes}, "
         f"inv_intact="
         f"{inv_path.is_file() and inv_path.read_bytes() == prior_inv_bytes}"
         if not ok else ""),
    )


def _scenario_late_preflight_failure_preserves_prior_inventory(
    td: Path,
) -> ScenarioResult:
    """Stale-inventory unlink ordering vs preflight gates.

    The destructive `unlink(<report-dir>/inventory.json)` step
    must run AFTER every preflight gate, never before. Several
    preflight gates fire AFTER the --report-dir checks — in
    particular the --output symlink gate and the --output
    non-regular-file gate. If the unlink ran inside the
    --report-dir block (before those later gates), a late
    preflight failure would return 2 without invoking
    run_pipeline() yet still have destroyed the caller's prior
    inventory.json — leaving them with no fresh run AND no prior
    evidence.

    Scenario:
      Run 1: happy path with --report-dir writes inventory.json.
      Run 2: SAME --report-dir, but --output is now a symlink (a
             preflight gate that fires AFTER the --report-dir
             checks). The runner must refuse the run with rc=2,
             AND inventory.json from Run 1 must remain
             byte-identical on disk.
    """
    ws = td / "ws_late_preflight"
    _copy_synthetic_workspace(ws)
    out = td / "late_preflight.pptx"
    report_dir = td / "late_preflight_reports_dir"
    # Run 1: happy path.
    rc1, sout1, _serr1 = _invoke_runner([
        "--workspace", str(ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
        "--report-dir", str(report_dir),
    ])
    inv_path = report_dir / "inventory.json"
    run1_ok = (
        rc1 == 0
        and "OK: pipeline succeeded" in sout1
        and inv_path.is_file()
    )
    if not run1_ok:
        return ScenarioResult(
            "stale-inventory unlink ordering: Run 1 prep",
            False,
            f"rc1={rc1}, inv_present={inv_path.is_file()}",
        )
    run1_inv_bytes = inv_path.read_bytes()

    # Run 2: replace --output with a symlink so the late
    # --output-is-symlink preflight gate fires AFTER the
    # --report-dir checks. The symlink target deliberately points
    # at an unrelated file outside the workspace so the gate
    # message is unmistakable.
    sym_target = td / "sym_output_target.pptx"
    sym_target_bytes = b"DO NOT OVERWRITE THIS UNRELATED SYM TARGET"
    sym_target.write_bytes(sym_target_bytes)
    out.unlink()
    out.symlink_to(sym_target)
    rc2, _sout2, serr2 = _invoke_runner([
        "--workspace", str(ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
        "--report-dir", str(report_dir),
    ])
    ok = (
        rc2 == 2
        and "symlink" in serr2
        and inv_path.is_file()
        and not inv_path.is_symlink()
        and inv_path.read_bytes() == run1_inv_bytes
        and sym_target.is_file()
        and sym_target.read_bytes() == sym_target_bytes
    )
    return ScenarioResult(
        "late preflight failure (--output is a symlink) preserves "
        "the prior --report-dir's inventory.json byte-identical: "
        "the destructive stale-inventory unlink only runs AFTER "
        "every preflight gate, so a late preflight refusal does "
        "not strand the caller without their prior evidence",
        ok,
        (f"rc2={rc2}, symlink_marker={'symlink' in serr2}, "
         f"inv_present={inv_path.is_file()}, "
         f"inv_bytes_match="
         f"{inv_path.is_file() and inv_path.read_bytes() == run1_inv_bytes}, "
         f"sym_target_intact="
         f"{sym_target.is_file() and sym_target.read_bytes() == sym_target_bytes}"
         if not ok else ""),
    )


def _scenario_upstream_failure_skips_inventory(td: Path) -> ScenarioResult:
    """validate_workspace failure cascading [SKIP] across every
    downstream stage must include the inspect_pptx_inventory stage
    when --report-dir is supplied — otherwise a regression that
    bypassed the aborted-cascade for the new stage would silently
    invoke the inventory subprocess against a missing or
    half-exported PPTX. No inventory.json must exist after the
    refused run."""
    ws = td / "ws_inv_skip"
    _copy_synthetic_workspace(ws)
    _tamper_planned_slide_count(ws)
    out = td / "inv_skip.pptx"
    report_dir = td / "inv_skip_reports_dir"
    rc, sout, _serr = _invoke_runner([
        "--workspace", str(ws),
        "--template-root", str(_SELF_TEST_TEMPLATE_ROOT),
        "--output", str(out),
        "--report-dir", str(report_dir),
    ])
    expected_skips = [
        "[SKIP] generate_render_models",
        "[SKIP] generate_svg_previews",
        "[SKIP] export_pptx",
        "[SKIP] validate_pptx_contract",
        "[SKIP] inspect_pptx_inventory",
    ]
    inventory_anywhere = list(report_dir.rglob("inventory.json"))
    ok = (
        rc == 1
        and "[FAIL] validate_workspace" in sout
        and all(line in sout for line in expected_skips)
        and not out.exists()
        and not inventory_anywhere
    )
    return ScenarioResult(
        "validate_workspace failure with --report-dir cascades [SKIP] "
        "to inspect_pptx_inventory too; no inventory.json is created",
        ok,
        (f"rc={rc}, fail_marker={'[FAIL] validate_workspace' in sout}, "
         f"all_skips_present={all(line in sout for line in expected_skips)}, "
         f"output_exists={out.exists()}, "
         f"inventory_files={inventory_anywhere}"
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
        results.append(_scenario_report_dir_is_regular_file(td, shared_ws))
        results.append(_scenario_report_dir_is_symlink(td, shared_ws))
        results.append(_scenario_report_dir_readonly_dir(td, shared_ws))
        results.append(_scenario_report_file_is_symlink(td, shared_ws))
        results.append(_scenario_report_file_readonly(td, shared_ws))
        results.append(_scenario_report_dir_outside_writes_reports(td))
        results.append(_scenario_inventory_written_with_report_dir(td))
        results.append(_scenario_no_inventory_without_report_dir(td))
        results.append(_scenario_inventory_path_is_symlink(td))
        results.append(_scenario_upstream_failure_skips_inventory(td))
        results.append(_scenario_stale_inventory_removed_on_failed_rerun(td))
        results.append(_scenario_late_preflight_failure_preserves_prior_inventory(td))
        results.append(_scenario_output_parent_blocked_returns_rc2(td))
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
            "Optional directory under which pipeline_report.json, "
            "pipeline_report.txt, and inventory.json will be written. "
            "Created if missing. The inventory.json file is the "
            "deterministic OOXML structure readback produced by "
            "scripts/inspect_pptx_inventory.py — OOXML structure "
            "counts, media / relationship report, and findings; "
            "evidence only, not proof of full PowerPoint editability. "
            "When omitted, no inventory stage is added (no inventory "
            "file is produced)."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run the in-script tempfixture scenarios: happy path "
            "export+validation; wrong --output extension; --output "
            "landing inside the workspace; --report-dir landing "
            "inside the workspace; pre-existing regular file at "
            "--report-dir (refused before any stage runs, no PPTX "
            "written); pre-existing symlink at --report-dir (refused, "
            "symlink target untouched); pre-existing read-only "
            "directory at --report-dir (writability probe; skipped "
            "under root because chmod cannot restrict root); "
            "pre-existing symlink at <report-dir>/pipeline_report.json "
            "(refused, unrelated target untouched); pre-existing "
            "read-only pipeline_report.txt (refused, prior content "
            "preserved; skipped under root); happy-path --report-dir "
            "outside the workspace writes pipeline_report.json + "
            "pipeline_report.txt; happy-path --report-dir produces "
            "inventory.json with the expected structure and "
            "evidence_basis line; happy-path WITHOUT --report-dir "
            "produces no inventory file anywhere; pre-existing "
            "symlink at <report-dir>/inventory.json refused before "
            "any stage runs; stale inventory.json from a prior "
            "successful --report-dir run is removed BEFORE a later "
            "failing rerun's stages execute, so the caller never "
            "sees a fresh FAIL pipeline_report next to a stale "
            "inventory.json; a LATE preflight failure (--output is "
            "a symlink) with the same --report-dir preserves the "
            "prior inventory.json byte-identical because the "
            "destructive stale-inventory unlink only runs AFTER "
            "every preflight gate; --output parent path blocked by "
            "a regular file returns rc=2 with a clean FAIL "
            "diagnostic (no Python traceback) and the blocker file "
            "AND any prior inventory.json are preserved byte-"
            "identical; pre-existing symlink at --output; "
            "pre-existing directory named *.pptx at --output; "
            "validate_workspace failure cascading [SKIP] across every "
            "downstream stage (including the inspect_pptx_inventory "
            "stage when --report-dir is set); pre-existing regular "
            ".pptx preserved when validate_workspace fails before "
            "export. Exits non-zero if any scenario does not behave "
            "as expected. Mutually exclusive with --workspace / "
            "--template-root / --output / --report-dir."
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

        # Refuse a pre-existing --report-dir that is anything other
        # than a real directory, mirroring the gates --output applies
        # to itself. Without these checks the runner would happily
        # run validate / generate / export (writing the PPTX!) and
        # only crash inside _write_reports() when mkdir() raises
        # FileExistsError on the regular-file case — turning a
        # report-path problem into a silent post-export failure that
        # leaves the caller without the report they explicitly asked
        # for. A symlink is refused for the same reason --output
        # rejects one: a symlink can quietly redirect writes into an
        # unrelated tree (or into the workspace via a target outside
        # the resolve()-based inside-workspace gate's view), and the
        # runner contract is "we own this directory; we write
        # pipeline_report.{json,txt} into it" — not "we follow
        # whatever the link points at."
        if args.report_dir.is_symlink():
            print(
                f"FAIL: --report-dir {args.report_dir} is a symlink; "
                f"refusing to follow it. Pass a regular directory "
                f"path.",
                file=sys.stderr,
            )
            return 2
        if args.report_dir.exists() and not args.report_dir.is_dir():
            print(
                f"FAIL: --report-dir {args.report_dir} exists and is "
                f"not a directory (looks like a regular file); refusing "
                f"to overwrite. Pass a directory path or a path that "
                f"does not yet exist.",
                file=sys.stderr,
            )
            return 2

        # Pre-create the report directory up front, BEFORE any
        # pipeline stage runs. After this point _write_reports() can
        # assume the directory exists. (It still calls mkdir with
        # exist_ok=True as defence-in-depth.)
        try:
            args.report_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(
                f"FAIL: --report-dir {args.report_dir} could not be "
                f"created: {exc}",
                file=sys.stderr,
            )
            return 2

        # mkdir(exist_ok=True) is necessary but NOT sufficient: on
        # an existing read-only directory the runner does not own
        # (or any other not-writable-by-us state — read-only mount,
        # full filesystem, ACL block), mkdir(exist_ok=True) returns
        # successfully WITHOUT proving the runner can actually
        # create files inside the directory. Without this probe,
        # the pipeline would validate / generate / export (writing
        # the PPTX!) and only then crash inside _write_reports()
        # when the pipeline_report.json open() raises
        # PermissionError. The probe is a NamedTemporaryFile inside
        # the directory: if we can create + close + delete a file
        # there, the eventual pipeline_report writes will succeed
        # too (modulo the irreducible TOCTOU window between
        # preflight and _write_reports, which is acceptable for a
        # CLI tool).
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=args.report_dir,
                prefix=".run_pipeline_writable_check_",
                suffix=".tmp",
                delete=True,
            ):
                pass
        except OSError as exc:
            print(
                f"FAIL: --report-dir {args.report_dir} is not "
                f"writable by this user (cannot create files inside "
                f"it): {exc}",
                file=sys.stderr,
            )
            return 2

        # The directory-level probe proves the runner can create
        # SOME file in --report-dir but does not prove that
        # pipeline_report.json, pipeline_report.txt, and inventory.json
        # SPECIFICALLY can be written. _write_reports() and the
        # inspect_pptx_inventory subprocess both ultimately call
        # Path.write_text(), which opens with mode 'w' — that follows
        # symlinks, truncates regular files, and fails on directories.
        # So a pre-existing entry at any of the three report-file paths
        # can still break the post-export write:
        #   - a symlink would silently redirect the write to an
        #     unrelated target (same anti-pattern --output forbids);
        #   - a directory would raise IsADirectoryError;
        #   - a read-only regular file would raise PermissionError.
        # Each of these would let validate / generate / export
        # (writing the PPTX!) succeed and only THEN crash inside
        # _write_reports() or the inspect_pptx_inventory subprocess.
        # Refuse all three up-front. os.access is used for the
        # read-only-regular-file case: it follows the standard Unix
        # permission model (chmod-based), which is sufficient for the
        # realistic failure modes and consistent with how the
        # eventual write_text() will be denied. TOCTOU between
        # preflight and the actual write is acceptable for a CLI tool.
        for rname in _REPORT_FILENAMES + (_INVENTORY_FILENAME,):
            rp = args.report_dir / rname
            if rp.is_symlink():
                print(
                    f"FAIL: report file {rp} is a symlink; refusing "
                    f"to follow it (a symlink at this path would "
                    f"redirect the post-export report / inventory "
                    f"write into an unrelated target). Remove it or "
                    f"replace it with a regular file path.",
                    file=sys.stderr,
                )
                return 2
            if rp.exists() and not rp.is_file():
                print(
                    f"FAIL: report file {rp} exists and is not a "
                    f"regular file (looks like a directory); "
                    f"refusing to overwrite.",
                    file=sys.stderr,
                )
                return 2
            if rp.exists() and not os.access(rp, os.W_OK):
                print(
                    f"FAIL: report file {rp} exists but is not "
                    f"writable by this user; the post-export report "
                    f"/ inventory write would raise PermissionError "
                    f"after the PPTX has already been written. Make "
                    f"the file writable or remove it.",
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
    # never confused with a missing-directory error. Wrap the mkdir in
    # a try/except OSError + return 2 so a blocked parent path (a
    # regular file sitting where the parent dir would be — mkdir
    # raises FileExistsError, a subclass of OSError; permission denied;
    # read-only mount; etc.) surfaces as the same rc=2 + clean
    # diagnostic every other preflight gate produces, not as a Python
    # traceback that would otherwise exit with rc=1 and confuse a
    # caller / CI surface that expects the rc=2 contract for all
    # preflight refusals.
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"FAIL: --output {args.output} parent directory "
            f"{args.output.parent} could not be created (or exists "
            f"as a non-directory): {exc}",
            file=sys.stderr,
        )
        return 2

    # Stale-inventory hygiene: destructive pre-stage cleanup of a
    # prior run's inventory.json. The pipeline_report.{json,txt}
    # files are unconditionally overwritten by _write_reports() at
    # end of run, so they always reflect the current run (even on
    # failure). inventory.json is different — it is only written
    # when the inspect_pptx_inventory stage actually runs to
    # completion, and the stage is [SKIP]'d whenever any upstream
    # stage fails. Without this cleanup, a successful prior run
    # leaves an inventory.json on disk that a later failing run
    # does NOT overwrite, so the caller would see a fresh
    # pipeline_report.{json,txt} marked FAIL alongside a stale
    # inventory.json from the earlier successful run — the
    # inventory could easily be misread as evidence about the
    # current (failing) run.
    #
    # Ordering matters: this unlink is DESTRUCTIVE — it removes a
    # prior good artifact from disk — so it MUST run AFTER every
    # preflight gate. The earlier --output symlink / non-regular-
    # file gates and the output-parent mkdir can all still fail
    # and return 2 without ever invoking run_pipeline(); if we
    # unlinked before those gates fired, a late preflight failure
    # would destroy the caller's prior inventory.json even though
    # no stage ran. The per-report-file loop above has already
    # proved this path is a regular writable file (no symlink, no
    # directory) so the unlink call itself is safe. If the
    # inventory stage runs in this invocation, it writes its own
    # inventory.json (ok=true OR with findings, but always
    # reflecting the current PPTX); if the stage is [SKIP]'d, no
    # inventory.json exists on disk after this run — the truthful
    # state.
    if args.report_dir is not None:
        stale_inventory = args.report_dir / _INVENTORY_FILENAME
        if stale_inventory.is_file():
            try:
                stale_inventory.unlink()
            except OSError as exc:
                print(
                    f"FAIL: could not remove stale inventory at "
                    f"{stale_inventory} before this run: {exc}",
                    file=sys.stderr,
                )
                return 2

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
        # The inventory.json side-output is only produced by the
        # inspect_pptx_inventory stage when every upstream stage
        # passed. Surface its path only when the stage actually ran
        # and reported its own [PASS] — otherwise the file does not
        # exist (the stage was skipped because validate_pptx_contract
        # or an earlier gate failed). The framing string mirrors
        # inspect_pptx_inventory's EVIDENCE_BASIS to keep callers
        # honest about what the inventory does and does not prove.
        inv_stage = next(
            (s for s in result.stages if s.name == "inspect_pptx_inventory"),
            None,
        )
        if inv_stage is not None and inv_stage.ok:
            print(
                f"Inventory written to "
                f"{args.report_dir / _INVENTORY_FILENAME} "
                f"(OOXML structure only; not proof of full PowerPoint "
                f"editability)."
            )

    _print_summary(result)

    return 0 if result.overall_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
