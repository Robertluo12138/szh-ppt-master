#!/usr/bin/env python3
"""Stage-3 (Plan) workspace bridge: produce a minimal deck_plan.json.

Bridges an already-stage-2-initialized workspace (the one
``scripts/init_deck_brief.py`` produces on top of stage-1 — i.e. the
workspace ships ``source_manifest.json`` + ``input/source.md`` +
``deck_brief.json``) into a minimal, schema-valid ``deck_plan.json``
whose ``slides[].source_refs`` are all declared in
``deck_brief.source_refs``.

Source-id traceability is **deck-level, not per-slide**: the
Stage-1/Stage-2 bridge gate guarantees
``source_manifest.source.id`` appears in ``deck_brief.source_refs``,
and this helper guarantees every ``slide.source_refs`` value is in
``deck_brief.source_refs``, so the manifest's source id is part of
the deck-bundle every slide draws from. **It does NOT follow** that
every individual slide cites ``source_manifest.source.id`` — when
``deck_brief.source_refs`` declares multiple ids, a slide may pick
a non-manifest id from that set. The contract proven here is the
chain *manifest -> deck_brief -> deck_plan source bundle*, not
*manifest -> every slide*.

This is **Stage-3 contract support only**. It is NOT a full
prompt/report/Markdown-to-PPTX automation. The helper deliberately
does NOT:

  - read or parse any business content out of ``input/source.md``
    (the source body is never opened by this helper);
  - invent ``template`` / ``rationale`` / ``slides`` / ``sections``
    content (the caller supplies the plan via the ``--plan-spec``
    JSON file);
  - emit any artifact other than ``<workspace>/deck_plan.json``;
  - generate ``design_system.json``, ``slide_plans/*.json``,
    ``image_manifest.json``, ``render_models/*``,
    ``svg_previews/*``, or any ``.pptx``;
  - call any public network, D-One, Qoder, image generation, or
    external service;
  - mutate or inspect any file outside ``--workspace``.

After this script succeeds, stages 4-6 (``design_system.json``,
``slide_plans/*.json``, ``image_manifest.json``) remain agent-driven
per the schemas under ``schemas/`` before ``scripts/run_pipeline.py``
can take over for stages 7-10.

The plan-spec contract is: a JSON object whose shape is exactly the
deck_plan candidate the caller wants written. The helper validates
the spec against ``schemas/deck_plan.schema.json``, applies the
cross-artifact planner-semantics gates (planned_slide_count vs.
len(slides), section coverage, slide.section_id resolution, slide
indices unique + contiguous 1..N, slide.source_refs subset of
deck_brief.source_refs), and writes the result deterministically.

Stdlib-only. Deterministic — given the same workspace + spec, the
produced ``deck_plan.json`` is byte-identical. The plan content is
exactly what the caller provided in the spec; nothing derived from
clock, environment, or file order ends up in the artifact.

Fail-closed gates (every gate aborts the run and writes nothing):

  --workspace
    * must be an existing directory;
    * the string form must not start with a URI-like scheme matching
      ``^[A-Za-z][A-Za-z0-9+.\\-]*:`` (same rule init_workspace.py
      applies to its --workspace and --source values);
    * must contain ``source_manifest.json`` as a **regular in-
      workspace file** (symlinks refused outright by a preflight that
      runs BEFORE the is_file / bridge / read_text gates);
    * the manifest must validate against
      ``schemas/source_manifest.schema.json``;
    * must contain ``input/source.md`` whose byte_count / line_count
      / sha256 match the manifest;
    * must contain ``deck_brief.json`` as a regular in-workspace file
      that validates against ``schemas/deck_brief.schema.json`` AND
      whose ``source_refs`` declares ``source_manifest.source.id``
      (the existing Stage-1 -> Stage-2+ bridge);
    * must NOT already contain ``deck_plan.json`` as a symlink
      (broken or resolvable) OR a regular file — the helper refuses
      to overwrite a prior plan.

  --plan-spec
    * must be an existing **regular file** (symlink refused by a
      preflight that runs BEFORE the is_file / read_text gates);
    * must parse as JSON and decode to an object (``dict``);
    * must validate against ``schemas/deck_plan.schema.json``;
    * must satisfy the planner-semantics cross-checks
      (planned_slide_count == len(slides); slide indices unique +
      contiguous 1..N; section coverage 1:1 with deck_plan slides;
      every slide.section_id resolves; every slide.source_ref is in
      deck_brief.source_refs).

The deck_plan is validated against
``schemas/deck_plan.schema.json`` **in memory** before any write,
and **re-validated on disk** after the write completes — the same
defense-in-depth contract ``init_workspace.py`` and
``init_deck_brief.py`` follow. A post-write failure rolls the plan
back so the workspace is never left in a half-written state.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "schemas"

sys.path.insert(0, str(SCRIPTS_DIR))

from validate_artifacts import validate_artifact  # noqa: E402
from validate_workspace import (  # noqa: E402
    check_source_manifest_bridge,
    SOURCE_MANIFEST_FILENAME,
)

DECK_PLAN_SCHEMA = SCHEMAS_DIR / "deck_plan.schema.json"
DECK_BRIEF_SCHEMA = SCHEMAS_DIR / "deck_brief.schema.json"
DECK_BRIEF_FILENAME = "deck_brief.json"
DECK_PLAN_FILENAME = "deck_plan.json"

# Same URI-scheme guard init_workspace.py / init_deck_brief.py use.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _has_uri_scheme(s: str) -> bool:
    return bool(_URI_SCHEME_PREFIX.match(s))


def _refuse_symlink(path: Path, label: str) -> tuple[bool, str]:
    """Return (is_symlink, fail_message). A symlink at ``path`` —
    broken or resolvable — is the same anti-pattern init_deck_brief
    rejects everywhere. Path.exists() returns False for a dangling
    link, so a bare exists() gate would silently follow the link;
    Path.is_file() follows symlinks too. The explicit is_symlink()
    check closes both holes."""
    if not path.is_symlink():
        return False, ""
    try:
        target = str(path.readlink())
    except OSError:
        target = "<unreadable>"
    return True, (
        f"FAIL: {path} ({label}) is a symlink (-> {target}); "
        f"init_deck_plan refuses to follow it (broken or not). "
        f"Remove or rename the symlink and re-run."
    )


def _validate_against_deck_plan_schema(plan: dict) -> list[str]:
    """In-memory schema validation against deck_plan.schema.json,
    using the same subset validator init_deck_brief.py uses."""
    schema = json.loads(DECK_PLAN_SCHEMA.read_text())
    from validate_artifacts import _validate  # noqa: WPS433
    errors: list[str] = []
    _validate(plan, schema, "<root>", errors)
    return errors


def _cross_check_planner_semantics(
    *,
    plan: dict,
    brief_source_refs: list[str],
) -> list[str]:
    """Stdlib-only port of the planner-semantics cross-checks the
    validate_workspace bridge already enforces, plus the contiguous-
    1..N rule the schema cannot express. Returns a list of error
    strings; an empty list means every gate passed.

    The schema layer has already confirmed shape (object/list/types),
    so this function focuses on cross-artifact semantics: planned
    count equality, slide-index uniqueness + contiguity, section
    coverage 1:1, slide.section_id resolution, slide.source_refs
    subset of deck_brief.source_refs."""
    errors: list[str] = []
    slides = plan.get("slides") or []
    sections = plan.get("sections") or []
    planning = plan.get("planning") or {}

    # planned_slide_count vs. len(slides).
    planned = planning.get("planned_slide_count")
    if planned != len(slides):
        errors.append(
            f"planning.planned_slide_count ({planned}) must equal "
            f"len(slides) ({len(slides)})"
        )

    # Slide indices: unique + contiguous 1..N.
    indices = [s.get("index") for s in slides]
    if len(set(indices)) != len(indices):
        duplicates = sorted({i for i in indices if indices.count(i) > 1})
        errors.append(f"slides[].index has duplicates: {duplicates}")
    expected = list(range(1, len(slides) + 1))
    if sorted(indices) != expected:
        errors.append(
            f"slides[].index must be contiguous 1..{len(slides)}; "
            f"got {sorted(indices)}"
        )

    # Section coverage: union(section.slide_indices) == set(slide.index).
    slide_index_set = set(indices)
    section_index_union: set[int] = set()
    section_problems: list[str] = []
    section_by_id: dict[str, dict] = {}
    for sec in sections:
        sid = sec.get("id")
        if isinstance(sid, str):
            if sid in section_by_id:
                section_problems.append(
                    f"section id {sid!r} appears more than once"
                )
            else:
                section_by_id[sid] = sec
        seen_local: set[int] = set()
        for idx in sec.get("slide_indices") or []:
            if idx in seen_local:
                section_problems.append(
                    f"section {sid!r}: slide_indices has duplicate {idx}"
                )
            seen_local.add(idx)
            if idx in section_index_union:
                section_problems.append(
                    f"slide index {idx} appears in more than one section"
                )
            section_index_union.add(idx)
    if section_problems:
        errors.extend(section_problems)
    missing_from_sections = sorted(slide_index_set - section_index_union)
    if missing_from_sections:
        errors.append(
            f"sections do not cover deck_plan slides: missing "
            f"{missing_from_sections}"
        )
    orphan_section_indices = sorted(section_index_union - slide_index_set)
    if orphan_section_indices:
        errors.append(
            f"sections list slide indices the deck_plan does not "
            f"declare: {orphan_section_indices}"
        )

    # Per-slide: section_id resolves AND slide.index appears in that
    # section's slide_indices; slide.source_refs subset of brief.
    brief_refs_set = set(brief_source_refs)
    for s in slides:
        idx = s.get("index")
        sid = s.get("section_id")
        if sid not in section_by_id:
            errors.append(
                f"slide index {idx}: section_id {sid!r} not declared in "
                f"sections (known: {sorted(section_by_id)})"
            )
        else:
            sec_indices = section_by_id[sid].get("slide_indices") or []
            if idx not in sec_indices:
                errors.append(
                    f"slide index {idx}: not listed in section "
                    f"{sid!r}.slide_indices ({sec_indices})"
                )
        for ref in s.get("source_refs") or []:
            if ref not in brief_refs_set:
                errors.append(
                    f"slide index {idx}: source_ref {ref!r} not "
                    f"declared in deck_brief.source_refs "
                    f"(known: {sorted(brief_refs_set)})"
                )
    return errors


def init_deck_plan(
    *,
    workspace: Path,
    plan_spec: Path,
) -> tuple[int, str]:
    """Run the full Stage-3 bridge. Returns (exit_code, message).

    Filesystem contract: preflight failures (bad ``--workspace``, bad
    ``--plan-spec``, missing / schema-invalid stage-1 / stage-2
    artifacts, pre-existing ``deck_plan.json``) leave the workspace
    untouched.

    A post-write re-validation failure rolls back
    ``deck_plan.json`` so the workspace returns to its pre-call
    state."""
    # --workspace shape gates (string-level FIRST, then filesystem).
    if _has_uri_scheme(str(workspace)):
        return 2, (
            f"FAIL: --workspace {workspace} looks like a URI; "
            f"init_deck_plan only accepts local directory paths"
        )
    if workspace.is_symlink():
        return 2, (
            f"FAIL: --workspace {workspace} is a symlink; refusing to "
            f"follow it. Pass a regular directory path."
        )
    if not workspace.exists():
        return 2, f"FAIL: --workspace {workspace} does not exist"
    if not workspace.is_dir():
        return 2, f"FAIL: --workspace {workspace} is not a directory"

    # --plan-spec shape gates.
    if _has_uri_scheme(str(plan_spec)):
        return 2, (
            f"FAIL: --plan-spec {plan_spec} looks like a URI; "
            f"init_deck_plan only accepts local file paths"
        )
    is_symlink, msg = _refuse_symlink(plan_spec, "--plan-spec")
    if is_symlink:
        return 2, msg
    if not plan_spec.exists():
        return 2, f"FAIL: --plan-spec {plan_spec} does not exist"
    if not plan_spec.is_file():
        return 2, f"FAIL: --plan-spec {plan_spec} is not a regular file"

    # Stage-3 contract gate: refuse to overwrite a pre-existing plan.
    # The symlink check runs FIRST and is independent of
    # ``plan_path.exists()`` for the same reason init_deck_brief
    # refuses symlinks at deck_brief.json: ``exists()`` returns
    # False for a broken symlink, so a bare ``exists()`` gate would
    # let ``write_text()`` follow the symlink and silently clobber
    # whatever the dangling link names. We refuse both broken and
    # resolvable symlinks here.
    plan_path = workspace / DECK_PLAN_FILENAME
    is_symlink, msg = _refuse_symlink(plan_path, "deck_plan.json")
    if is_symlink:
        return 2, msg
    if plan_path.exists():
        return 2, (
            f"FAIL: {plan_path} already exists; init_deck_plan refuses "
            f"to overwrite a prior plan. Rename or remove it and re-run."
        )

    # Stage-1 prerequisite: source_manifest.json must exist and the
    # bridge must pass. The bridge already enforces the symlink
    # preflight + schema-validation + on-disk hash match + the
    # deck_brief.source_refs cross-check.
    manifest_path = workspace / SOURCE_MANIFEST_FILENAME
    is_symlink, msg = _refuse_symlink(manifest_path, SOURCE_MANIFEST_FILENAME)
    if is_symlink:
        return 2, msg
    if not manifest_path.is_file():
        return 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{SOURCE_MANIFEST_FILENAME}; run scripts/init_workspace.py "
            f"first to seed Stage-1 intake (input/source.md + "
            f"source_manifest.json)."
        )

    # Stage-2 prerequisite: deck_brief.json must exist.
    brief_path = workspace / DECK_BRIEF_FILENAME
    is_symlink, msg = _refuse_symlink(brief_path, DECK_BRIEF_FILENAME)
    if is_symlink:
        return 2, msg
    if not brief_path.is_file():
        return 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{DECK_BRIEF_FILENAME}; run scripts/init_deck_brief.py first "
            f"to seed Stage-2 (deck_brief.json)."
        )

    # Run the bridge. It enforces: source_manifest schema-valid,
    # input/source.md matches, deck_brief.source_refs declares
    # source.id. A failed row here is a stage-1 OR stage-2 contract
    # violation we must surface BEFORE writing the plan.
    bridge_results = check_source_manifest_bridge(workspace)
    bridge_failures = [r for r in bridge_results if not r.ok]
    if bridge_failures:
        detail = "; ".join(
            f"{r.name}{(': ' + r.detail) if r.detail else ''}"
            for r in bridge_failures
        )
        return 2, (
            f"FAIL: Stage-1/Stage-2 bridge does not pass for "
            f"{workspace}: {detail}"
        )

    # Re-read the brief so we know its source_refs for the cross-check.
    try:
        brief = json.loads(brief_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return 2, (
            f"FAIL: cannot re-read {brief_path} after the bridge "
            f"reported pass: {exc}"
        )
    if not isinstance(brief, dict):
        return 2, (
            f"FAIL: {brief_path} did not decode to an object "
            f"(got {type(brief).__name__})"
        )
    brief_errors: list[str] = []
    try:
        brief_schema = json.loads(DECK_BRIEF_SCHEMA.read_text())
        from validate_artifacts import _validate  # noqa: WPS433
        _validate(brief, brief_schema, "<root>", brief_errors)
    except (Exception, SystemExit) as exc:
        return 2, (
            f"FAIL: cannot schema-validate {brief_path}: "
            f"{type(exc).__name__}: {exc}"
        )
    if brief_errors:
        return 2, (
            f"FAIL: {brief_path} does not validate against "
            f"deck_brief.schema.json: {brief_errors}"
        )
    brief_refs = brief.get("source_refs")
    if not isinstance(brief_refs, list) or not all(
        isinstance(r, str) for r in brief_refs
    ):
        # The schema validation above already rejects this case;
        # defensive belt-and-suspenders so the cross-check that
        # follows never operates on a malformed list.
        return 1, (
            f"FAIL: {brief_path}.source_refs must be a non-empty list "
            f"of strings (got {brief_refs!r})"
        )

    # --plan-spec content gates.
    try:
        plan = json.loads(plan_spec.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return 2, (
            f"FAIL: --plan-spec {plan_spec} did not parse as JSON: {exc}"
        )
    if not isinstance(plan, dict):
        return 2, (
            f"FAIL: --plan-spec {plan_spec} did not decode to an object "
            f"(got {type(plan).__name__})"
        )

    # Schema validation.
    try:
        schema_errors = _validate_against_deck_plan_schema(plan)
    except (Exception, SystemExit) as exc:
        return 1, (
            f"FAIL: pre-write schema validation of --plan-spec raised "
            f"{type(exc).__name__}: {exc}"
        )
    if schema_errors:
        return 1, (
            f"FAIL: --plan-spec {plan_spec} does not match "
            f"schemas/{DECK_PLAN_SCHEMA.name}: " + "; ".join(schema_errors)
        )

    # Planner-semantics cross-checks (the schema cannot express these).
    cross_errors = _cross_check_planner_semantics(
        plan=plan, brief_source_refs=brief_refs,
    )
    if cross_errors:
        return 1, (
            f"FAIL: --plan-spec {plan_spec} fails planner-semantics "
            f"cross-checks: " + "; ".join(cross_errors)
        )

    # Write. Mirror init_deck_brief.py's rollback contract: the catch
    # clause is explicitly (Exception, SystemExit) so
    # validate_artifact's SystemExit branch on read-errors still
    # routes through rollback. KeyboardInterrupt is intentionally NOT
    # caught so Ctrl-C stays responsive.
    try:
        plan_path.write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n"
        )
    except (Exception, SystemExit) as exc:
        if plan_path.exists():
            try:
                plan_path.unlink()
            except OSError:
                pass
        return 2, (
            f"FAIL: writing {plan_path} raised {type(exc).__name__}: {exc}"
        )

    try:
        errors = validate_artifact(plan_path, DECK_PLAN_SCHEMA)
    except (Exception, SystemExit) as exc:
        try:
            plan_path.unlink()
            rb_note = f"removed {plan_path}"
        except OSError as unlink_exc:
            rb_note = f"could not remove {plan_path}: {unlink_exc}"
        return 1, (
            f"FAIL: post-write re-validation of {plan_path} raised "
            f"{type(exc).__name__}: {exc}\n"
            f"rolled back: {rb_note}"
        )
    if errors:
        try:
            plan_path.unlink()
            rb_note = f"removed {plan_path}"
        except OSError as unlink_exc:
            rb_note = f"could not remove {plan_path}: {unlink_exc}"
        return 1, (
            f"FAIL: on-disk deck_plan at {plan_path} did not "
            f"re-validate: {errors}\n"
            f"rolled back: {rb_note}"
        )

    n_slides = len(plan.get("slides") or [])
    n_sections = len(plan.get("sections") or [])
    template_name = plan.get("template")
    return 0, (
        f"OK: Stage-3 deck_plan seeded at {plan_path}.\n"
        f"  template: {template_name!r}\n"
        f"  planned_slide_count: {n_slides}\n"
        f"  sections: {n_sections}\n"
        f"  source_refs lineage: deck_brief.source_refs "
        f"{brief_refs!r} (each slide.source_refs is a subset)\n"
        f"Next stages (agent-driven; init_deck_plan.py does not "
        f"automate them):\n"
        f"  4. design_system.json\n"
        f"  5. slide_plans/*.json\n"
        f"  6. image_manifest.json\n"
        f"Once those exist, scripts/run_pipeline.py can take over "
        f"for stages 7-10."
    )


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs under
# tempfile.TemporaryDirectory(); no fixture leaks into the repo.
# ---------------------------------------------------------------------------

_SYNTH_SOURCE_MD = (
    "# Synthetic Source\n\n"
    "Synthetic .md body — never inspected by init_deck_plan.\n"
    "Line three.\n"
)


def _seed_stage12_workspace(
    ws: Path,
    *,
    source_id: str = "synthetic_src",
    body: bytes | None = None,
    write_source_manifest: bool = True,
    write_deck_brief: bool = True,
    brief_source_refs: list[str] | None = None,
    brief_extra_keys: dict | None = None,
    brief_override: dict | None = None,
    brief_raw_text: str | None = None,
) -> None:
    """Mimic what scripts/init_workspace.py + scripts/init_deck_brief.py
    would have written. Synthetic only — does not invoke them as
    subprocesses so targeted negative mutations stay simple."""
    import hashlib
    if body is None:
        body = _SYNTH_SOURCE_MD.encode("utf-8")
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "input").mkdir(parents=True, exist_ok=True)
    (ws / "input" / "source.md").write_bytes(body)
    if write_source_manifest:
        line_count = (
            body.count(b"\n") + (0 if body.endswith(b"\n") else 1)
            if body else 0
        )
        sha = hashlib.sha256(body).hexdigest()
        manifest = {
            "schema_version": "1",
            "source": {
                "id": source_id,
                "local_path": "input/source.md",
                "kind": "markdown",
                "byte_count": len(body),
                "line_count": line_count,
                "sha256": sha,
            },
            "tool": {"name": "init_workspace", "version": "1"},
        }
        (ws / SOURCE_MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
    if write_deck_brief:
        if brief_raw_text is not None:
            (ws / DECK_BRIEF_FILENAME).write_text(brief_raw_text)
        else:
            refs = brief_source_refs or [source_id]
            brief = brief_override if brief_override is not None else {
                "title": "Synthetic Title",
                "audience": "Synthetic Audience",
                "objective": "Synthetic Objective",
                "source_refs": refs,
            }
            if brief_extra_keys:
                brief.update(brief_extra_keys)
            (ws / DECK_BRIEF_FILENAME).write_text(
                json.dumps(brief, indent=2, sort_keys=True) + "\n"
            )


def _minimal_plan_spec(
    *,
    source_id: str = "synthetic_src",
    template: str = "business_review",
    slide_count: int = 1,
    indices: list[int] | None = None,
) -> dict:
    """Build a minimal positive plan-spec. ``indices`` overrides the
    contiguous-1..N default so negative tests can inject duplicate /
    non-contiguous index sequences without re-implementing the rest
    of the shape."""
    if indices is None:
        indices = list(range(1, slide_count + 1))
    slides = [
        {
            "index": idx,
            "layout": "cover",
            "title": f"Slide {idx}",
            "section_id": "main",
            "summary": f"Synthetic slide {idx} summary.",
            "density": "low",
            "source_refs": [source_id],
        }
        for idx in indices
    ]
    return {
        "template": template,
        "planning": {
            "planned_slide_count": len(slides),
            "rationale": "Synthetic minimal plan-spec for self-test.",
        },
        "sections": [
            {
                "id": "main",
                "title": "Main",
                "summary": "Synthetic single section.",
                "slide_indices": list(indices),
            },
        ],
        "slides": slides,
    }


def _write_spec(td: Path, plan: dict, name: str = "spec.json") -> Path:
    path = td / name
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    return path


def _expect(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


def _run_self_tests() -> list[tuple[str, bool, str]]:
    import tempfile

    results: list[tuple[str, bool, str]] = []

    # 1. happy path: minimal 1-slide / 1-section plan-spec produces a
    # schema-valid deck_plan.json byte-identical to what we serialized.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_happy"
        _seed_stage12_workspace(ws, source_id="synthetic_a")
        spec_path = _write_spec(td, _minimal_plan_spec(source_id="synthetic_a"))
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        plan_path = ws / DECK_PLAN_FILENAME
        ok = rc == 0 and plan_path.is_file()
        if ok:
            plan = json.loads(plan_path.read_text())
            ok = (
                plan.get("template") == "business_review"
                and plan["planning"]["planned_slide_count"] == 1
                and len(plan["slides"]) == 1
                and plan["slides"][0]["source_refs"] == ["synthetic_a"]
            )
        results.append(_expect(
            "happy path: minimal 1-slide plan-spec yields a schema-valid "
            "deck_plan whose slide.source_refs = [source_manifest.source.id]",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 2. happy path: 3-slide / 2-section plan-spec — non-trivial coverage.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_happy3"
        _seed_stage12_workspace(
            ws,
            source_id="src_p",
            brief_source_refs=["src_p", "src_q"],
        )
        spec = {
            "template": "business_review",
            "planning": {
                "planned_slide_count": 3,
                "rationale": "Synthetic 3-slide / 2-section plan.",
            },
            "sections": [
                {
                    "id": "intro",
                    "title": "Intro",
                    "summary": "Cover + overview.",
                    "slide_indices": [1, 2],
                },
                {
                    "id": "close",
                    "title": "Close",
                    "summary": "Conclusion.",
                    "slide_indices": [3],
                },
            ],
            "slides": [
                {
                    "index": 1, "layout": "cover", "title": "Cover",
                    "section_id": "intro", "summary": "Cover slide.",
                    "density": "low", "source_refs": ["src_p"],
                },
                {
                    "index": 2, "layout": "executive_summary",
                    "title": "Overview", "section_id": "intro",
                    "summary": "Overview slide.", "density": "medium",
                    "source_refs": ["src_p", "src_q"],
                },
                {
                    "index": 3, "layout": "conclusion", "title": "Close",
                    "section_id": "close", "summary": "Close slide.",
                    "density": "low", "source_refs": ["src_q"],
                },
            ],
        }
        spec_path = _write_spec(td, spec)
        rc, _ = init_deck_plan(workspace=ws, plan_spec=spec_path)
        plan_path = ws / DECK_PLAN_FILENAME
        ok = rc == 0 and plan_path.is_file()
        results.append(_expect(
            "happy path: 3-slide / 2-section plan-spec writes a "
            "schema-valid deck_plan with mixed slide.source_refs",
            ok, f"rc={rc}",
        ))

    # 3. determinism: two independent runs from the same workspace +
    # spec produce byte-identical plans.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws_a = td / "ws_det_a"
        ws_b = td / "ws_det_b"
        _seed_stage12_workspace(ws_a, source_id="det_src")
        _seed_stage12_workspace(ws_b, source_id="det_src")
        spec_path_a = _write_spec(td, _minimal_plan_spec(
            source_id="det_src"), "spec_a.json")
        spec_path_b = _write_spec(td, _minimal_plan_spec(
            source_id="det_src"), "spec_b.json")
        rc_a, _ = init_deck_plan(workspace=ws_a, plan_spec=spec_path_a)
        rc_b, _ = init_deck_plan(workspace=ws_b, plan_spec=spec_path_b)
        bytes_a = (ws_a / DECK_PLAN_FILENAME).read_bytes() if rc_a == 0 else b""
        bytes_b = (ws_b / DECK_PLAN_FILENAME).read_bytes() if rc_b == 0 else b""
        ok = rc_a == 0 and rc_b == 0 and bytes_a == bytes_b and bytes_a
        results.append(_expect(
            "determinism: two independent runs produce byte-identical "
            "deck_plans (no timestamps, no environment leak, sorted keys)",
            ok, f"rc_a={rc_a}, rc_b={rc_b}, equal={bytes_a == bytes_b}",
        ))

    # 4. missing deck_brief.json -> refused (helper requires Stage-2).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_brief"
        _seed_stage12_workspace(ws, write_deck_brief=False)
        spec_path = _write_spec(td, _minimal_plan_spec())
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc == 2
            and DECK_BRIEF_FILENAME in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "missing deck_brief.json refused (no silent fallback)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 5. malformed deck_brief.json (non-JSON) -> refused via the
    # bridge layer (validate_workspace's _try_load reports loadable=False
    # which makes the bridge result fail). No deck_plan.json is written.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_bad_brief"
        _seed_stage12_workspace(ws, brief_raw_text="{ not valid json")
        spec_path = _write_spec(td, _minimal_plan_spec())
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc in (1, 2)
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "malformed deck_brief.json (non-JSON bytes) refused before "
            "any deck_plan is written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 6. deck_brief.source_refs missing source_manifest.source.id ->
    # refused by the Stage-1/Stage-2 bridge cross-check.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_brief_no_src"
        _seed_stage12_workspace(
            ws,
            source_id="real_src",
            brief_source_refs=["unrelated_id"],
        )
        spec_path = _write_spec(td, _minimal_plan_spec(source_id="real_src"))
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc == 2
            and "Stage" in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "deck_brief.source_refs missing source_manifest.source.id is "
            "refused at the bridge layer (no deck_plan written)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 7. planned_slide_count mismatch in spec -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_count_mismatch"
        _seed_stage12_workspace(ws, source_id="m_src")
        spec = _minimal_plan_spec(source_id="m_src", slide_count=2)
        spec["planning"]["planned_slide_count"] = 5  # disagrees with 2
        spec_path = _write_spec(td, spec)
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc == 1
            and "planned_slide_count" in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "planning.planned_slide_count != len(slides) refused at the "
            "planner-semantics cross-check",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 8. duplicate slide indices -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_dup_idx"
        _seed_stage12_workspace(ws, source_id="d_src")
        spec = _minimal_plan_spec(
            source_id="d_src",
            slide_count=2,
            indices=[1, 1],  # duplicate
        )
        spec["sections"][0]["slide_indices"] = [1, 1]
        spec_path = _write_spec(td, spec)
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc == 1
            and "duplicates" in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "duplicate slide indices refused at the planner-semantics "
            "cross-check",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 9. non-contiguous slide indices -> refused (e.g. [1, 2, 4]).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_noncontig"
        _seed_stage12_workspace(ws, source_id="nc_src")
        spec = _minimal_plan_spec(
            source_id="nc_src",
            slide_count=3,
            indices=[1, 2, 4],
        )
        spec["sections"][0]["slide_indices"] = [1, 2, 4]
        spec_path = _write_spec(td, spec)
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc == 1
            and "contiguous" in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "non-contiguous slide indices ([1, 2, 4]) refused at the "
            "planner-semantics cross-check",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 10. invalid section coverage: section omits a slide -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_sec_missing"
        _seed_stage12_workspace(ws, source_id="sm_src")
        spec = _minimal_plan_spec(source_id="sm_src", slide_count=2)
        spec["sections"][0]["slide_indices"] = [1]  # missing slide 2
        spec_path = _write_spec(td, spec)
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc == 1
            and "do not cover" in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "sections that omit a deck_plan slide_index are refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 11. invalid section coverage: section lists an orphan index -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_sec_orphan"
        _seed_stage12_workspace(ws, source_id="so_src")
        spec = _minimal_plan_spec(source_id="so_src", slide_count=1)
        spec["sections"][0]["slide_indices"] = [1, 7]  # 7 is orphan
        spec_path = _write_spec(td, spec)
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc == 1
            and "orphan" in msg.lower() or "does not declare" in msg
        )
        ok = ok and not (ws / DECK_PLAN_FILENAME).exists()
        results.append(_expect(
            "sections that list an orphan slide_index (one the deck_plan "
            "does not declare) are refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 12. slide.section_id not declared in sections -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_unknown_section"
        _seed_stage12_workspace(ws, source_id="us_src")
        spec = _minimal_plan_spec(source_id="us_src", slide_count=1)
        spec["slides"][0]["section_id"] = "not_a_real_section_id"
        spec_path = _write_spec(td, spec)
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc == 1
            and ("section_id" in msg or "section" in msg)
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "slide.section_id referencing an unknown section refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 13. slide.source_refs not in deck_brief.source_refs -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_ref_not_brief"
        _seed_stage12_workspace(ws, source_id="declared")
        spec = _minimal_plan_spec(source_id="declared")
        spec["slides"][0]["source_refs"] = ["not_in_brief"]
        spec_path = _write_spec(td, spec)
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc == 1
            and "source_ref" in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "slide.source_refs values not declared in deck_brief.source_refs "
            "refused at the planner-semantics cross-check",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 14. no-source_manifest legacy workspace -> refused (helper
    # requires Stage-1; the existing prepared examples that ship
    # without source_manifest.json simply do not run this helper —
    # they remain valid under validate_workspace which is itself
    # no-op when the manifest is absent).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_manifest"
        _seed_stage12_workspace(ws, write_source_manifest=False)
        spec_path = _write_spec(td, _minimal_plan_spec())
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc == 2
            and SOURCE_MANIFEST_FILENAME in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "no-source_manifest legacy workspace refused (helper requires "
            "Stage-1; existing prepared examples without "
            "source_manifest.json simply do not run this helper)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 15. pre-existing deck_plan.json refused (no overwrite).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_exists"
        _seed_stage12_workspace(ws, source_id="e_src")
        prior = json.dumps({"prior": True})
        (ws / DECK_PLAN_FILENAME).write_text(prior)
        spec_path = _write_spec(td, _minimal_plan_spec(source_id="e_src"))
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        preserved = (ws / DECK_PLAN_FILENAME).read_text() == prior
        ok = rc == 2 and "already exists" in msg and preserved
        results.append(_expect(
            "pre-existing deck_plan.json refused (no overwrite); prior "
            "contents preserved byte-identical",
            ok, f"rc={rc}, preserved={preserved}",
        ))

    # 16. broken symlink at deck_plan.json refused BEFORE write_text
    # could follow it; dangling target never created.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_broken_link"
        _seed_stage12_workspace(ws, source_id="bl_src")
        target = td / "outside_target_must_not_be_written.json"
        assert not target.exists()
        (ws / DECK_PLAN_FILENAME).symlink_to(target)
        spec_path = _write_spec(td, _minimal_plan_spec(source_id="bl_src"))
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        still_symlink = (ws / DECK_PLAN_FILENAME).is_symlink()
        target_absent = not target.exists()
        ok = (
            rc == 2
            and "symlink" in msg
            and still_symlink
            and target_absent
        )
        results.append(_expect(
            "broken symlink at deck_plan.json refused BEFORE write_text "
            "could follow it; dangling target never created",
            ok,
            f"rc={rc}, still_symlink={still_symlink}, "
            f"target_absent={target_absent}, msg={msg!r}",
        ))

    # 17. resolvable symlink at deck_plan.json refused; outside target's
    # bytes preserved.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_live_link"
        _seed_stage12_workspace(ws, source_id="ll_src")
        outside = td / "unrelated.json"
        outside_bytes = b'{"unrelated": "must not be clobbered"}\n'
        outside.write_bytes(outside_bytes)
        (ws / DECK_PLAN_FILENAME).symlink_to(outside)
        spec_path = _write_spec(td, _minimal_plan_spec(source_id="ll_src"))
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        outside_preserved = outside.read_bytes() == outside_bytes
        ok = rc == 2 and "symlink" in msg and outside_preserved
        results.append(_expect(
            "resolvable symlink at deck_plan.json refused; outside target's "
            "bytes preserved byte-identical (write_text never followed)",
            ok, f"rc={rc}, outside_preserved={outside_preserved}",
        ))

    # 18. broken symlink at source_manifest.json refused at the
    # bridge's symlink preflight; no deck_plan.json written.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_manifest_broken"
        _seed_stage12_workspace(ws, source_id="mb_src")
        (ws / SOURCE_MANIFEST_FILENAME).unlink()
        dangling = td / "no_such_manifest.json"
        assert not dangling.exists()
        (ws / SOURCE_MANIFEST_FILENAME).symlink_to(dangling)
        spec_path = _write_spec(td, _minimal_plan_spec(source_id="mb_src"))
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc == 2
            and "symlink" in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
            and not dangling.exists()
        )
        results.append(_expect(
            "broken symlink at source_manifest.json refused; dangling "
            "target never created; no deck_plan.json written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 19. plan-spec is a symlink -> refused at the preflight.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_spec_link"
        _seed_stage12_workspace(ws, source_id="sl_src")
        target = td / "no_such_spec.json"
        assert not target.exists()
        spec_symlink = td / "spec_link.json"
        spec_symlink.symlink_to(target)
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_symlink)
        ok = (
            rc == 2
            and "symlink" in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "symlink at --plan-spec refused at the preflight (broken "
            "or resolvable; deck_plan.json never written)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 20. plan-spec is a non-JSON file -> refused at the parse layer.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_spec_bad_json"
        _seed_stage12_workspace(ws, source_id="bj_src")
        bad_spec = td / "bad.json"
        bad_spec.write_text("{ not valid json")
        rc, msg = init_deck_plan(workspace=ws, plan_spec=bad_spec)
        ok = (
            rc == 2
            and "JSON" in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "malformed (non-JSON) --plan-spec refused at the parse layer",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 21. plan-spec parses but is a list (not object) -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_spec_list"
        _seed_stage12_workspace(ws, source_id="ls_src")
        list_spec = td / "list.json"
        list_spec.write_text("[1, 2, 3]")
        rc, msg = init_deck_plan(workspace=ws, plan_spec=list_spec)
        ok = (
            rc == 2
            and "object" in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "list-rooted --plan-spec refused (must decode to an object)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 22. schema-invalid spec (missing required field) -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_spec_missing"
        _seed_stage12_workspace(ws, source_id="sm2_src")
        broken = _minimal_plan_spec(source_id="sm2_src")
        del broken["planning"]
        spec_path = _write_spec(td, broken)
        rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc == 1
            and "planning" in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "schema-invalid --plan-spec (missing 'planning') refused at "
            "the schema layer",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 23. workspace gates: missing / non-dir / URI / symlink.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec_path = _write_spec(td, _minimal_plan_spec())
        rc, msg = init_deck_plan(
            workspace=td / "no_such_dir", plan_spec=spec_path,
        )
        ok = rc == 2 and "does not exist" in msg
        results.append(_expect(
            "missing --workspace refused", ok, f"rc={rc}",
        ))

    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec_path = _write_spec(td, _minimal_plan_spec())
        f = td / "ws_file"
        f.write_text("hi")
        rc, msg = init_deck_plan(workspace=f, plan_spec=spec_path)
        ok = rc == 2 and "not a directory" in msg
        results.append(_expect(
            "--workspace pointing at a regular file refused",
            ok, f"rc={rc}",
        ))

    rc, msg = init_deck_plan(
        workspace=Path("https://attacker.example/ws"),
        plan_spec=Path("/tmp/no.json"),
    )
    ok = rc == 2 and "URI" in msg
    results.append(_expect(
        "--workspace with URI scheme refused at the string level",
        ok, f"rc={rc}",
    ))

    # 24. source body marker phrase is NEVER copied into deck_plan.json
    # (the helper never opens input/source.md for content).
    marker = "MARKER_NEVER_EXTRACT_8c2c1d"
    body = (
        f"# Title\n\nBody with {marker} in it.\n"
    ).encode("utf-8")
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_extract"
        _seed_stage12_workspace(ws, body=body, source_id="extract_src")
        spec_path = _write_spec(td, _minimal_plan_spec(source_id="extract_src"))
        rc, _ = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = rc == 0
        if ok:
            written = (ws / DECK_PLAN_FILENAME).read_text()
            ok = marker not in written
        results.append(_expect(
            "source body marker phrase is NEVER copied into "
            "deck_plan.json (helper does not extract content)",
            ok, f"rc={rc}",
        ))

    # 25. post-write re-validation failure (forced via mock) rolls back
    # the just-written plan. The plan must not exist on disk after.
    import unittest.mock
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_rb"
        _seed_stage12_workspace(ws, source_id="rb_src")
        spec_path = _write_spec(td, _minimal_plan_spec(source_id="rb_src"))
        with unittest.mock.patch(
            f"{__name__}.validate_artifact",
            return_value=["forced test failure"],
        ):
            rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc == 1
            and "rolled back" in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "post-write re-validation failure (forced via mock) rolls "
            "back the plan so the workspace is never left half-written",
            ok, f"rc={rc}",
        ))

    # 26. post-write re-validation raising SystemExit also rolls back
    # (proves the catch clause is (Exception, SystemExit), not just
    # Exception — validate_artifact's read-error branch raises
    # SystemExit, not Exception).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_rb_sysexit"
        _seed_stage12_workspace(ws, source_id="se_src")
        spec_path = _write_spec(td, _minimal_plan_spec(source_id="se_src"))
        with unittest.mock.patch(
            f"{__name__}.validate_artifact",
            side_effect=SystemExit("simulated read-error branch"),
        ):
            rc, msg = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = (
            rc == 1
            and "rolled back" in msg
            and "SystemExit" in msg
            and not (ws / DECK_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "post-write re-validation raising SystemExit rolls back "
            "(proves catch clause is (Exception, SystemExit))",
            ok, f"rc={rc}",
        ))

    # 27. on-disk plan re-validates via validate_artifact.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_revalidate"
        _seed_stage12_workspace(ws, source_id="rev_src")
        spec_path = _write_spec(td, _minimal_plan_spec(source_id="rev_src"))
        rc, _ = init_deck_plan(workspace=ws, plan_spec=spec_path)
        ok = rc == 0
        if ok:
            errors = validate_artifact(
                ws / DECK_PLAN_FILENAME, DECK_PLAN_SCHEMA,
            )
            ok = not errors
        results.append(_expect(
            "on-disk deck_plan.json re-validates against "
            "schemas/deck_plan.schema.json via validate_artifact",
            ok, f"rc={rc}",
        ))

    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage-3 (Plan) deck_plan.json helper. Bridges a stage-2-"
            "initialized workspace (source_manifest.json + "
            "input/source.md + deck_brief.json) into a minimal, "
            "schema-valid deck_plan.json whose slide.source_refs are "
            "all declared in deck_brief.source_refs. Source-id "
            "traceability is deck-level, not per-slide: "
            "source_manifest.source.id is in deck_brief.source_refs "
            "(bridge gate) and every slide.source_refs is a subset "
            "of deck_brief.source_refs (helper gate), but a slide "
            "may pick a non-manifest id when the brief declares "
            "multiple. Does NOT extract business content from the "
            "source body — stages 4-6 remain agent-driven."
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Workspace directory (must already contain "
             "source_manifest.json + input/source.md + deck_brief.json, "
             "e.g. seeded by scripts/init_workspace.py and "
             "scripts/init_deck_brief.py).",
    )
    parser.add_argument(
        "--plan-spec", type=Path, default=None,
        help="Path to a JSON file describing the plan content. The "
             "file must decode to an object whose shape is exactly "
             "the deck_plan candidate the caller wants written: "
             "{ template, planning {planned_slide_count, rationale}, "
             "sections[], slides[] }. The helper validates this "
             "against schemas/deck_plan.schema.json, applies the "
             "planner-semantics cross-checks (planned count equality, "
             "unique + contiguous slide indices, section coverage, "
             "slide.section_id resolution, slide.source_refs subset of "
             "deck_brief.source_refs) and writes the result.",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios (happy path, "
             "3-slide / 2-section happy path, determinism, missing "
             "deck_brief.json, malformed deck_brief, deck_brief missing "
             "source_manifest source.id, planned_slide_count mismatch, "
             "duplicate slide indices, non-contiguous slide indices, "
             "section coverage missing a slide, section listing an "
             "orphan index, unknown slide.section_id, slide.source_refs "
             "not declared in deck_brief, no-source_manifest legacy "
             "workspace, pre-existing deck_plan.json, broken / "
             "resolvable symlink at deck_plan.json, broken symlink at "
             "source_manifest.json, --plan-spec symlink, malformed / "
             "list-rooted / schema-invalid --plan-spec, --workspace "
             "missing / regular-file / URI, marker phrase never copied, "
             "post-write rollback (return errors / raise SystemExit), "
             "on-disk re-validation). Exits non-zero if any scenario "
             "does not behave as expected. Mutually exclusive with "
             "--workspace / --plan-spec.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if any(v is not None for v in (args.workspace, args.plan_spec)):
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
            print(
                f"FAIL: {fails} self-test scenario(s) did not behave as "
                f"expected."
            )
            return 1
        print(
            "OK (self-test): every fail-closed gate is caught and the "
            "happy-path plan is written from the Stage-2 brief."
        )
        return 0

    missing = [
        name for name, value in (
            ("--workspace", args.workspace),
            ("--plan-spec", args.plan_spec),
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

    rc, msg = init_deck_plan(
        workspace=args.workspace,
        plan_spec=args.plan_spec,
    )
    if rc == 0:
        print(msg)
    else:
        print(msg, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
