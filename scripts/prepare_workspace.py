#!/usr/bin/env python3
"""Stage-1-to-6 local orchestration helper.

Chains the six existing per-stage contract helpers in a single
deterministic command, driven entirely by explicit caller-supplied
inputs:

    1. scripts/init_workspace.py        (Intake)
    2. scripts/init_deck_brief.py       (Brief)
    3. scripts/init_deck_plan.py        (Plan)
    4. scripts/init_design_system.py    (Design system)
    5. scripts/init_slide_plans.py      (Per-slide plans)
    6. scripts/init_image_manifest.py   (Image manifest)

After every stage succeeds, the workspace contains the Stage-1-through-6
artifacts ``scripts/run_pipeline.py`` consumes: ``input/source.md``,
``source_manifest.json``, ``deck_brief.json``, ``deck_plan.json``,
``design_system.json``, ``slide_plans/<idx:02d>_<layout>.json``, and
``image_manifest.json``.

**This is explicit-input orchestration only — it is NOT a full
prompt/report/Markdown-to-PPTX automation.** Every stage's content
comes from the caller via flags or JSON spec files:

  - the deck title / audience / objective come from ``--title`` /
    ``--audience`` / ``--objective`` (passed straight through to
    ``init_deck_brief``);
  - the plan body comes from ``--plan-spec`` (a JSON file whose shape is
    exactly the ``deck_plan`` candidate);
  - the design system comes from EXACTLY ONE of ``--design-system-spec``
    (a ``design_system.json`` candidate) or ``--theme-from-template``
    (project palette / typography / grid from the template named in
    ``deck_plan.template`` resolved through ``--template-root``);
  - the slide bodies come from ``--slide-specs-dir`` (a directory of
    ``slide_plan`` JSON candidates);
  - the image manifest comes from ``--image-manifest-spec`` (an
    ``image_manifest`` JSON candidate).

The orchestrator NEVER:

  - parses ``input/source.md`` for business content (Stage-2 through
    Stage-6 each delegate to the same Stage-1/Stage-2 bridge that reads
    the source bytes only for byte-level integrity checks and discards
    the decoded string);
  - invents ``deck_brief`` / ``deck_plan`` / ``design_system`` /
    ``slide_plans`` / ``image_manifest`` content;
  - generates any image asset, ``render_models/``, ``svg_previews/``,
    ``.pptx``, or pipeline report;
  - calls D-One, Qoder, any public network, image generation,
    telemetry, or external service;
  - modifies files outside ``--workspace``.

Fail-closed semantics: the first stage that returns a non-zero exit
code halts the orchestration; every downstream stage is marked SKIPPED
and is NOT run. Each stage helper owns its own rollback contract — the
orchestrator does not roll back earlier-stage artifacts when a later
stage fails (the same as running the helpers manually one at a time).
A caller who needs a clean retry should delete the workspace directory
(or fix the failing input and rerun from the failing stage manually).

Stdlib-only. Deterministic — every stage helper is deterministic, so
two runs from byte-identical inputs into two different empty
workspaces produce byte-identical artifacts inside each workspace.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

from init_workspace import init_workspace  # noqa: E402
from init_deck_brief import init_deck_brief  # noqa: E402
from init_deck_plan import init_deck_plan  # noqa: E402
from init_design_system import init_design_system  # noqa: E402
from init_slide_plans import init_slide_plans  # noqa: E402
from init_image_manifest import init_image_manifest  # noqa: E402


# Artifacts the orchestrator promises a successful run leaves behind.
# Used by the self-test only; the orchestrator itself never inspects
# the workspace beyond delegating to each stage helper.
_STAGE_OUTPUT_FILES = (
    "input/source.md",
    "source_manifest.json",
    "deck_brief.json",
    "deck_plan.json",
    "design_system.json",
    "image_manifest.json",
)

_STAGE_NAMES = (
    "init_workspace",
    "init_deck_brief",
    "init_deck_plan",
    "init_design_system",
    "init_slide_plans",
    "init_image_manifest",
)


@dataclass
class StageOutcome:
    name: str
    skipped: bool
    exit_code: int
    message: str

    @property
    def ok(self) -> bool:
        return (not self.skipped) and self.exit_code == 0


@dataclass
class PrepareResult:
    workspace: Path
    stages: list[StageOutcome] = field(default_factory=list)

    @property
    def overall_ok(self) -> bool:
        return bool(self.stages) and all(s.ok for s in self.stages)

    @property
    def first_failure(self) -> StageOutcome | None:
        for s in self.stages:
            if not s.ok and not s.skipped:
                return s
        return None


def prepare_workspace(
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
    design_system_spec: Path | None = None,
    theme_from_template: bool = False,
    source_id: str | None = None,
    tone: str | None = None,
    language: str | None = None,
    approximate_slide_count: int | None = None,
) -> PrepareResult:
    """Run stages 1-6 in order, halting on the first non-zero exit code.

    Returns a ``PrepareResult`` listing every stage that ran (with its
    rc and message) and every downstream stage that was skipped because
    an earlier stage failed.

    Mode-selection gate: exactly one of ``design_system_spec`` or
    ``theme_from_template`` must be supplied. The orchestrator does not
    silently pick a mode; ambiguous or empty mode arguments halt the
    run at Stage 4 (the design system helper's own gate) with a clear
    message.

    The helpers themselves own their rollback contracts. A failing
    stage rolls back its own writes; earlier-stage artifacts are
    preserved on disk so the caller can inspect them. The orchestrator
    does not delete earlier-stage artifacts on failure — it stops the
    cascade so no half-baked workspace is advanced into a later stage."""
    result = PrepareResult(workspace=workspace)

    # Stage list captured lazily so that downstream stages whose
    # arguments would otherwise raise (e.g. design_system_spec=None
    # passed to a strict signature) are never invoked once an earlier
    # stage has failed.
    stage_fns: list[tuple[str, Callable[[], tuple[int, str]]]] = [
        (
            "init_workspace",
            lambda: init_workspace(
                source=source,
                workspace=workspace,
                source_id=source_id,
            ),
        ),
        (
            "init_deck_brief",
            lambda: init_deck_brief(
                workspace=workspace,
                title=title,
                audience=audience,
                objective=objective,
                tone=tone,
                language=language,
                approximate_slide_count=approximate_slide_count,
            ),
        ),
        (
            "init_deck_plan",
            lambda: init_deck_plan(
                workspace=workspace,
                plan_spec=plan_spec,
            ),
        ),
        (
            "init_design_system",
            # init_design_system refuses --template-root unless
            # --theme-from-template is also supplied; route the path
            # only on the theme-mode branch so the --spec branch passes
            # template_root=None.
            lambda: init_design_system(
                workspace=workspace,
                spec=design_system_spec,
                theme_from_template=theme_from_template,
                template_root=template_root if theme_from_template else None,
            ),
        ),
        (
            "init_slide_plans",
            lambda: init_slide_plans(
                workspace=workspace,
                template_root=template_root,
                specs_dir=slide_specs_dir,
            ),
        ),
        (
            "init_image_manifest",
            lambda: init_image_manifest(
                workspace=workspace,
                spec=image_manifest_spec,
            ),
        ),
    ]

    failed_at: str | None = None
    for name, fn in stage_fns:
        if failed_at is not None:
            result.stages.append(StageOutcome(
                name=name,
                skipped=True,
                exit_code=-1,
                message=f"SKIPPED: prior stage {failed_at!r} failed",
            ))
            continue
        rc, msg = fn()
        result.stages.append(StageOutcome(
            name=name,
            skipped=False,
            exit_code=rc,
            message=msg,
        ))
        if rc != 0:
            failed_at = name

    return result


def _format_result(result: PrepareResult) -> str:
    lines: list[str] = []
    for s in result.stages:
        if s.skipped:
            mark = "SKIP"
        elif s.ok:
            mark = "PASS"
        else:
            mark = "FAIL"
        lines.append(f"  [{mark}] {s.name} (rc={s.exit_code})")
    if result.overall_ok:
        lines.append(
            f"OK: prepared Stage-1-through-6 workspace at {result.workspace}. "
            f"scripts/run_pipeline.py can take over for stages 7-10."
        )
    else:
        fail = result.first_failure
        if fail is not None:
            lines.append(
                f"FAIL: stopped at {fail.name} (rc={fail.exit_code}).\n"
                f"--- {fail.name} message ---\n{fail.message}"
            )
        else:
            lines.append("FAIL: orchestration did not complete (no failure recorded).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs under tempfile.TemporaryDirectory()
# with synthetic fixtures written inline; no fixture leaks into the repo and
# no real source content is ever embedded in this script.
# ---------------------------------------------------------------------------


_MARKER_PHRASE = "FIXTURE-MARKER-7c2f6e91"

_FIXTURE_SOURCE = (
    "# Synthetic Fixture Source\n\n"
    f"{_MARKER_PHRASE}\n"
    "This synthetic body is the secret the orchestrator must never copy "
    "into any generated artifact beyond input/source.md. Stage 2 only "
    "takes --title / --audience / --objective from the CLI; Stage 3-6 "
    "each accept explicit --*-spec JSON files. None of the helpers ever "
    "read this file for business content.\n"
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _build_fixture(td: Path, *, source_id: str = "fixture_source") -> dict:
    """Create a minimal Stage-1-through-6 fixture under ``td``.

    Returns a kwargs dict ready for ``prepare_workspace(**fixture)``
    (excluding ``--workspace``, which the caller picks per scenario).

    The fixture targets the ``business_review`` template (the template
    the current repo ships) with two slides covering its simplest
    required slots: ``cover`` (title only) and ``key_message`` (a single
    callout message). Both slide_plan candidates therefore satisfy
    ``_slide_plan_against_layout``'s required-slot coverage gate.
    """
    td.mkdir(parents=True, exist_ok=True)
    source = td / "fixture_source.md"
    source.write_text(_FIXTURE_SOURCE)

    plan_spec = td / "plan_spec.json"
    _write_json(plan_spec, {
        "template": "business_review",
        "planning": {
            "planned_slide_count": 2,
            "rationale": (
                "Two-slide fixture exercising the orchestrator only — no "
                "business content."
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
        "objective": "Exercise the prepare_workspace orchestrator.",
        "plan_spec": plan_spec,
        "slide_specs_dir": specs_dir,
        "image_manifest_spec": image_manifest_spec,
        "template_root": REPO_ROOT / "templates" / "layouts",
        "design_system_spec": None,
        "theme_from_template": True,
        "source_id": source_id,
    }


def _expect(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


def _all_stage_files_present(workspace: Path) -> bool:
    for rel in _STAGE_OUTPUT_FILES:
        if not (workspace / rel).is_file():
            return False
    # Slide plans land under slide_plans/ with canonical filenames; we
    # check both fixture entries (deck_plan declares slides 1 and 2).
    if not (workspace / "slide_plans" / "01_cover.json").is_file():
        return False
    if not (workspace / "slide_plans" / "02_key_message.json").is_file():
        return False
    return True


def _read_artifact_text(workspace: Path) -> str:
    """Concatenate every stage-2-through-6 artifact's text (plus the
    source_manifest) so the marker-phrase test can scan in one sweep.
    The verbatim source copy at input/source.md is excluded by design —
    the marker is allowed there."""
    parts: list[str] = []
    for rel in (
        "source_manifest.json",
        "deck_brief.json",
        "deck_plan.json",
        "design_system.json",
        "image_manifest.json",
    ):
        p = workspace / rel
        if p.is_file():
            parts.append(p.read_text())
    for plan_file in sorted((workspace / "slide_plans").glob("*.json")):
        parts.append(plan_file.read_text())
    return "\n".join(parts)


def _run_self_tests() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    # 1. Happy path: every stage runs successfully and the workspace
    # carries Stage-1-through-6 artifacts.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        fixture = _build_fixture(td)
        ws = td / "happy_ws"
        result = prepare_workspace(workspace=ws, **fixture)
        ok = (
            result.overall_ok
            and _all_stage_files_present(ws)
            and len(result.stages) == len(_STAGE_NAMES)
            and all(s.name == n for s, n in zip(result.stages, _STAGE_NAMES))
        )
        results.append(_expect(
            "happy path: all six stages run, every Stage-1-through-6 "
            "artifact lands on disk, stage order matches the canonical "
            "init_workspace → init_image_manifest sequence",
            ok,
            f"overall_ok={result.overall_ok}, "
            f"files_present={_all_stage_files_present(ws)}, "
            f"stage_count={len(result.stages)}",
        ))

    # 2. Per-stage failure stops downstream stages. We force each stage
    # to fail with a minimal targeted-bad input and confirm every later
    # stage is marked SKIPPED.
    failure_cases = [
        (
            "init_workspace",
            # init_workspace rejects an empty source file.
            lambda td, fx: fx.__setitem__("source", _write_empty(td / "empty.md")),
        ),
        (
            "init_deck_brief",
            # init_deck_brief rejects an empty title.
            lambda td, fx: fx.__setitem__("title", ""),
        ),
        (
            "init_deck_plan",
            # init_deck_plan rejects a malformed plan_spec.
            lambda td, fx: fx.__setitem__(
                "plan_spec", _write_garbage(td / "bad_plan.json")
            ),
        ),
        (
            "init_design_system",
            # init_design_system refuses both modes simultaneously
            # (--spec + --theme-from-template). Switching from
            # theme_from_template=True to also pass a design_system_spec
            # forces the mode-selection gate to fire.
            lambda td, fx: fx.update({
                "design_system_spec": _write_garbage(td / "bad_ds.json"),
                "theme_from_template": True,
            }),
        ),
        (
            "init_slide_plans",
            # init_slide_plans rejects a non-existent specs directory.
            lambda td, fx: fx.__setitem__(
                "slide_specs_dir", td / "missing_specs",
            ),
        ),
        (
            "init_image_manifest",
            # init_image_manifest rejects a malformed spec.
            lambda td, fx: fx.__setitem__(
                "image_manifest_spec", _write_garbage(td / "bad_img.json"),
            ),
        ),
    ]
    for stage_name, mutator in failure_cases:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            fixture = _build_fixture(td)
            mutator(td, fixture)
            ws = td / f"fail_at_{stage_name}_ws"
            result = prepare_workspace(workspace=ws, **fixture)

            # Identify the index of the failing stage in canonical order.
            stage_index = _STAGE_NAMES.index(stage_name)
            ok = (
                not result.overall_ok
                and result.first_failure is not None
                and result.first_failure.name == stage_name
            )
            # Every stage at or before stage_index should have RUN
            # (skipped=False); the failing stage's exit_code must be
            # non-zero. Every stage AFTER stage_index must be SKIPPED.
            for i, outcome in enumerate(result.stages):
                if i < stage_index:
                    if outcome.skipped or outcome.exit_code != 0:
                        ok = False
                elif i == stage_index:
                    if outcome.skipped or outcome.exit_code == 0:
                        ok = False
                else:
                    if not outcome.skipped:
                        ok = False
            results.append(_expect(
                f"per-stage failure: {stage_name} fails -> every later "
                f"stage is SKIPPED, no half-baked workspace advances",
                ok,
                f"first_failure={result.first_failure.name if result.first_failure else None}, "
                f"stages={[(s.name, s.skipped, s.exit_code) for s in result.stages]}",
            ))

    # 3. Pre-existing unsafe workspace: a symlink at --workspace is
    # refused by init_workspace itself; the orchestrator inherits the
    # gate and never advances past Stage 1.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        fixture = _build_fixture(td)
        real_dir = td / "real_target"
        real_dir.mkdir()
        ws_sym = td / "ws_sym"
        ws_sym.symlink_to(real_dir)
        result = prepare_workspace(workspace=ws_sym, **fixture)
        ok = (
            not result.overall_ok
            and result.first_failure is not None
            and result.first_failure.name == "init_workspace"
            and "symlink" in result.first_failure.message
            # Confirm no artifacts leaked into the symlink target.
            and not (real_dir / "source_manifest.json").exists()
            and not (real_dir / "deck_brief.json").exists()
        )
        results.append(_expect(
            "pre-existing unsafe workspace (symlink) is refused at Stage 1; "
            "symlink target directory is untouched and every downstream "
            "stage is SKIPPED",
            ok,
            f"first_failure={result.first_failure.name if result.first_failure else None}",
        ))

    # 4. Pre-existing non-empty workspace: init_workspace refuses it.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        fixture = _build_fixture(td)
        ws = td / "ws_preexist"
        ws.mkdir()
        (ws / "pre.txt").write_text("prior content")
        result = prepare_workspace(workspace=ws, **fixture)
        ok = (
            not result.overall_ok
            and result.first_failure is not None
            and result.first_failure.name == "init_workspace"
            and (ws / "pre.txt").read_text() == "prior content"
            and not (ws / "deck_brief.json").exists()
        )
        results.append(_expect(
            "pre-existing non-empty workspace is refused at Stage 1; "
            "prior contents preserved byte-identical",
            ok,
            f"first_failure={result.first_failure.name if result.first_failure else None}",
        ))

    # 5. Marker-phrase test: the source body must never appear in any
    # generated artifact except the verbatim copy at input/source.md.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        fixture = _build_fixture(td)
        ws = td / "marker_ws"
        result = prepare_workspace(workspace=ws, **fixture)
        if not result.overall_ok:
            results.append(_expect(
                "marker-phrase test: orchestrator completed all stages "
                "before scanning artifacts",
                False,
                f"orchestration failed: {result.first_failure.message if result.first_failure else 'unknown'}",
            ))
        else:
            source_copy = (ws / "input" / "source.md").read_text()
            artifact_text = _read_artifact_text(ws)
            ok = (
                _MARKER_PHRASE in source_copy
                and _MARKER_PHRASE not in artifact_text
            )
            results.append(_expect(
                "marker phrase appears in input/source.md only — never "
                "copied into source_manifest / deck_brief / deck_plan / "
                "design_system / slide_plans / image_manifest",
                ok,
                f"in_source={_MARKER_PHRASE in source_copy}, "
                f"in_artifacts={_MARKER_PHRASE in artifact_text}",
            ))

    # 6. Determinism: two independent happy-path runs into different
    # empty workspaces produce byte-identical artifacts (each stage
    # helper is deterministic, so the orchestrator is too).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        # Build two fixture dirs whose inputs are byte-identical
        # despite living at different absolute paths. Each stage
        # helper reads the JSON body, never the input file's absolute
        # path, so two runs from byte-identical INPUTS into two
        # different empty workspaces should produce byte-identical
        # OUTPUTS.
        fixture_a = _build_fixture(td / "fixture_a_dir")
        fixture_b = _build_fixture(td / "fixture_b_dir")
        ws_a = td / "det_a"
        ws_b = td / "det_b"
        result_a = prepare_workspace(workspace=ws_a, **fixture_a)
        result_b = prepare_workspace(workspace=ws_b, **fixture_b)
        ok = result_a.overall_ok and result_b.overall_ok
        diffs: list[str] = []
        if ok:
            compared = list(_STAGE_OUTPUT_FILES) + [
                "slide_plans/01_cover.json",
                "slide_plans/02_key_message.json",
            ]
            for rel in compared:
                a_bytes = (ws_a / rel).read_bytes()
                b_bytes = (ws_b / rel).read_bytes()
                if a_bytes != b_bytes:
                    diffs.append(rel)
                    ok = False
        results.append(_expect(
            "determinism: two independent happy-path runs from "
            "byte-identical inputs produce byte-identical artifacts in "
            "every Stage-1-through-6 file (input/source.md, source_manifest, "
            "deck_brief, deck_plan, design_system, slide_plans, "
            "image_manifest)",
            ok,
            f"diffs={diffs}, a_ok={result_a.overall_ok}, b_ok={result_b.overall_ok}",
        ))

    # 7. Run_pipeline.py can consume the resulting workspace: validate
    # via the same workspace gate run_pipeline uses up front. We do not
    # call run_pipeline itself (it would generate render_models / SVG /
    # PPTX, which the orchestrator is intentionally NOT in scope for) —
    # we only confirm that validate_workspace.py against our prepared
    # workspace passes, which is exactly the gate run_pipeline applies.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        fixture = _build_fixture(td)
        ws = td / "validate_ws"
        result = prepare_workspace(workspace=ws, **fixture)
        if not result.overall_ok:
            results.append(_expect(
                "prepared workspace passes validate_workspace.py "
                "(the gate run_pipeline.py applies up front)",
                False,
                f"orchestration failed: {result.first_failure.message if result.first_failure else 'unknown'}",
            ))
        else:
            import subprocess
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "validate_workspace.py"),
                    "--workspace", str(ws),
                    "--template-root", str(REPO_ROOT / "templates" / "layouts"),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            ok = proc.returncode == 0
            results.append(_expect(
                "prepared workspace passes validate_workspace.py against "
                "the business_review template (the gate run_pipeline.py "
                "applies up front)",
                ok,
                f"rc={proc.returncode}, stderr_tail={proc.stderr.strip().splitlines()[-3:] if proc.stderr.strip() else []}",
            ))

    return results


def _write_empty(path: Path) -> Path:
    path.write_bytes(b"")
    return path


def _write_garbage(path: Path) -> Path:
    path.write_text("this is not valid JSON {{{")
    return path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage-1-to-6 local orchestration helper. Chains "
            "scripts/init_workspace.py through scripts/init_image_manifest.py "
            "from explicit caller-supplied inputs into a workspace that "
            "scripts/run_pipeline.py can later consume. Orchestration only "
            "— does not plan a deck, does not extract source content, does "
            "not generate render_models / SVG / PPTX / reports, and does "
            "not call any public network or external service."
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Workspace directory to create. Same gate as "
             "scripts/init_workspace.py (no symlinks, must be empty if it "
             "exists, no URI scheme, outside the repo / fs root / $HOME / "
             "system trees).",
    )
    parser.add_argument(
        "--source", type=Path, default=None,
        help="Local .md or .txt source file (forwarded to init_workspace).",
    )
    parser.add_argument(
        "--source-id", type=str, default=None,
        help="Opaque source identifier the orchestrator passes to "
             "init_workspace. Defaults to the --source filename stem.",
    )
    parser.add_argument(
        "--title", type=str, default=None,
        help="Deck title forwarded to init_deck_brief.",
    )
    parser.add_argument(
        "--audience", type=str, default=None,
        help="Audience forwarded to init_deck_brief.",
    )
    parser.add_argument(
        "--objective", type=str, default=None,
        help="Deck objective forwarded to init_deck_brief.",
    )
    parser.add_argument(
        "--tone", type=str, default=None,
        help="Optional tone forwarded to init_deck_brief.",
    )
    parser.add_argument(
        "--language", type=str, default=None,
        help="Optional language forwarded to init_deck_brief.",
    )
    parser.add_argument(
        "--approximate-slide-count", type=int, default=None,
        help="Optional planning hint forwarded to init_deck_brief.",
    )
    parser.add_argument(
        "--plan-spec", type=Path, default=None,
        help="Deck-plan JSON candidate forwarded to init_deck_plan.",
    )
    parser.add_argument(
        "--design-system-spec", type=Path, default=None,
        help="Design-system JSON candidate forwarded to "
             "init_design_system. Mutually exclusive with "
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
        help="Template root directory (e.g. templates/layouts/). Required "
             "by init_slide_plans, and additionally by init_design_system "
             "in --theme-from-template mode.",
    )
    parser.add_argument(
        "--slide-specs-dir", type=Path, default=None,
        help="Directory of slide_plan JSON candidates forwarded to "
             "init_slide_plans.",
    )
    parser.add_argument(
        "--image-manifest-spec", type=Path, default=None,
        help="Image-manifest JSON candidate forwarded to "
             "init_image_manifest.",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios (happy path through "
             "Stage 6, per-stage failure short-circuits downstream "
             "stages, pre-existing unsafe workspace refused, pre-existing "
             "non-empty workspace refused, source-body marker phrase "
             "never copied beyond input/source.md, deterministic repeat "
             "runs produce byte-identical artifacts, prepared workspace "
             "passes validate_workspace.py). Exits non-zero if any "
             "scenario does not behave as expected. Mutually exclusive "
             "with the orchestration flags.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        orchestration_args = (
            args.workspace, args.source, args.source_id,
            args.title, args.audience, args.objective,
            args.tone, args.language, args.approximate_slide_count,
            args.plan_spec, args.design_system_spec,
            args.template_root, args.slide_specs_dir,
            args.image_manifest_spec,
        )
        if any(v is not None for v in orchestration_args) or args.theme_from_template:
            print(
                "FAIL: --self-test does not take any other argument",
                file=sys.stderr,
            )
            return 2
        results = _run_self_tests()
        fails = 0
        for name, ok, detail in results:
            mark = "PASS" if ok else "FAIL"
            suffix = f" -- {detail}" if not ok and detail else ""
            print(f"  [{mark}] {name}{suffix}")
            if not ok:
                fails += 1
        print()
        if fails:
            print(f"FAIL: {fails} self-test scenario(s) did not behave as expected.")
            return 1
        print(
            "OK (self-test): every orchestration short-circuit fires "
            "correctly and the happy-path workspace is prepared through "
            "Stage 6 from explicit caller-supplied inputs."
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

    # Mode-selection gate: exactly one of --design-system-spec /
    # --theme-from-template must be supplied. init_design_system would
    # also catch this at Stage 4, but surfacing the failure up-front
    # gives a clearer error before Stage 1 runs.
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

    result = prepare_workspace(
        workspace=args.workspace,
        source=args.source,
        title=args.title,
        audience=args.audience,
        objective=args.objective,
        plan_spec=args.plan_spec,
        slide_specs_dir=args.slide_specs_dir,
        image_manifest_spec=args.image_manifest_spec,
        template_root=args.template_root,
        design_system_spec=args.design_system_spec,
        theme_from_template=args.theme_from_template,
        source_id=args.source_id,
        tone=args.tone,
        language=args.language,
        approximate_slide_count=args.approximate_slide_count,
    )

    text = _format_result(result)
    if result.overall_ok:
        print(text)
        return 0
    print(text, file=sys.stderr)
    fail = result.first_failure
    return fail.exit_code if fail is not None else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
