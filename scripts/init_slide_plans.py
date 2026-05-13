#!/usr/bin/env python3
"""Stage-5 (Per-slide Plan) workspace bridge: produce slide_plans/*.json.

Bridges an already-stage-4-initialized workspace (the one
``scripts/init_workspace.py`` + ``scripts/init_deck_brief.py`` +
``scripts/init_deck_plan.py`` + ``scripts/init_design_system.py``
produce — i.e. the workspace ships ``source_manifest.json`` +
``input/source.md`` + ``deck_brief.json`` + ``deck_plan.json`` +
``design_system.json``) into a complete ``<workspace>/slide_plans/``
directory whose contents come from EXACTLY ONE explicit caller input:

  --specs-dir <dir>
    A directory of caller-supplied JSON files, each one a slide_plan
    candidate. The helper iterates ``*.json`` files at the directory
    root, validates every candidate against
    ``schemas/slide_plan.schema.json``, cross-checks coverage against
    ``deck_plan.slides[]`` (1:1 by ``index``, ``layout`` / ``title``
    match, required layout slots covered), and writes each accepted
    candidate to ``<workspace>/slide_plans/<idx:02d>_<layout>.json``
    deterministically.

This is **Stage-5 contract support only**. It is NOT a full
prompt/report/Markdown-to-PPTX automation. The helper deliberately
does NOT:

  - read or parse any business content out of ``input/source.md``
    — the helper invokes the Stage-1/Stage-2 bridge
    (``check_source_manifest_bridge``), which reads the file's
    bytes ONLY for byte-level integrity checks (UTF-8 decode
    validity; ``source.byte_count`` / ``source.line_count`` /
    ``source.sha256`` match against the manifest); the decoded
    string is discarded inside the bridge, and the helper itself
    never opens the source body at all — no heading / bullet /
    paragraph / sentence parsing, no token inference, no copy of
    any source bytes into a slide_plan;
  - infer slide content from raw source text — the caller must
    supply every slide_plan body explicitly via ``--specs-dir``;
  - invent ``image_manifest.json``, ``render_models/*``,
    ``svg_previews/*``, or any ``.pptx``;
  - emit any artifact other than ``<workspace>/slide_plans/*.json``;
  - call any public network, D-One, Qoder, image generation, or
    external service;
  - mutate or inspect any file outside ``--workspace`` (the only
    file tree outside the workspace the helper opens is
    ``--specs-dir`` for spec bytes and ``--template-root`` for the
    template / layout files referenced by ``deck_plan.template``).

After this script succeeds, Stage 6 (``image_manifest.json``)
remains agent-driven per the schemas under ``schemas/`` before
``scripts/run_pipeline.py`` can take over for stages 7-10.

Stdlib-only. Deterministic — given the same workspace + specs-dir +
template-root, the produced slide_plans are byte-identical. The
slide content is exactly what the caller provided; nothing derived
from clock, environment, or file order ends up in any artifact.

Fail-closed gates (every gate aborts the run and writes nothing):

  --workspace
    * must be an existing directory; URI-shaped values refused; the
      workspace itself must not be a symlink;
    * must contain ``source_manifest.json`` + ``deck_brief.json`` +
      ``deck_plan.json`` + ``design_system.json`` all as **regular
      in-workspace files** (symlinks refused);
    * each artifact validates against its schema; the Stage-1/Stage-2
      bridge (manifest <-> input/source.md <-> deck_brief.source_refs)
      must pass;
    * ``deck_plan.json`` must additionally satisfy the planner-
      semantics cross-checks ``init_deck_plan.py`` applies before it
      writes a Stage-3 artifact — re-using
      ``init_deck_plan._cross_check_planner_semantics`` so a
      semantically-broken prior stage (duplicate / non-contiguous
      indices, section coverage gaps, undeclared
      ``slide.source_refs``) is refused before Stage-5 advances;
    * must NOT already contain a non-empty ``slide_plans/``
      directory; the directory itself must not be a symlink (broken
      or resolvable). An empty pre-existing ``slide_plans/`` is
      accepted and reused.

  --template-root
    * must be an existing directory; URI-shaped values refused; the
      template-root itself must not be a symlink;
    * ``deck_plan.template`` resolves inside ``--template-root``
      via ``local_path_is_safe`` + ``_resolves_within``;
    * the template directory contains a regular-file ``template.json``
      that validates against ``schemas/template.schema.json``;
    * every layout declared in ``deck_plan.slides[].layout`` appears
      in ``template.layouts``;
    * the per-layout file ``layouts/<layout>.json`` is a regular file
      that validates against ``schemas/layout.schema.json``.

  --specs-dir
    * must be an existing directory; URI-shaped values refused; the
      specs-dir itself must not be a symlink;
    * every ``*.json`` file at the root must be a regular file
      (symlinks refused), parse as JSON, decode to an object, and
      validate against ``schemas/slide_plan.schema.json``;
    * the union of ``spec.index`` across every spec must exactly
      cover the ``deck_plan.slides[].index`` set — no duplicates,
      no missing slides, no orphan slides;
    * each spec's ``layout`` / ``title`` must match the deck_plan
      slide with the same index;
    * each spec's ``blocks`` must cover every required slot of the
      layout (matching on ``slot.id`` -> ``block.id`` AND
      ``slot.type`` -> ``block.kind``).

Each accepted candidate is schema-validated **in memory** before
any write, then written to ``<workspace>/slide_plans/<idx:02d>_<layout>.json``,
then **re-validated on disk**. A post-write re-validation failure
rolls back EVERY slide_plan the helper wrote in this run so the
workspace returns to its pre-call state.
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
from validate_scaffold import (  # noqa: E402
    local_path_is_safe,
    _resolves_within,
    _slide_plan_against_layout,
)
from validate_workspace import (  # noqa: E402
    check_source_manifest_bridge,
    SOURCE_MANIFEST_FILENAME,
)
from init_deck_plan import _cross_check_planner_semantics  # noqa: E402

DECK_BRIEF_SCHEMA = SCHEMAS_DIR / "deck_brief.schema.json"
DECK_PLAN_SCHEMA = SCHEMAS_DIR / "deck_plan.schema.json"
DESIGN_SYSTEM_SCHEMA = SCHEMAS_DIR / "design_system.schema.json"
SLIDE_PLAN_SCHEMA = SCHEMAS_DIR / "slide_plan.schema.json"
TEMPLATE_SCHEMA = SCHEMAS_DIR / "template.schema.json"
LAYOUT_SCHEMA = SCHEMAS_DIR / "layout.schema.json"

DECK_BRIEF_FILENAME = "deck_brief.json"
DECK_PLAN_FILENAME = "deck_plan.json"
DESIGN_SYSTEM_FILENAME = "design_system.json"
SLIDE_PLANS_DIRNAME = "slide_plans"

_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _has_uri_scheme(s: str) -> bool:
    return bool(_URI_SCHEME_PREFIX.match(s))


def _refuse_symlink(path: Path, label: str) -> tuple[bool, str]:
    """Return (is_symlink, fail_message). Same anti-pattern the other
    init_* helpers reject everywhere: Path.exists() returns False for
    a dangling link and Path.is_file() follows symlinks, so an explicit
    is_symlink() check is the only way to refuse both broken and
    resolvable links."""
    if not path.is_symlink():
        return False, ""
    try:
        target = str(path.readlink())
    except OSError:
        target = "<unreadable>"
    return True, (
        f"FAIL: {path} ({label}) is a symlink (-> {target}); "
        f"init_slide_plans refuses to follow it (broken or not). "
        f"Remove or rename the symlink and re-run."
    )


def _schema_validate(value: dict, schema_path: Path) -> list[str]:
    """In-memory schema validation reusing validate_artifacts._validate."""
    schema = json.loads(schema_path.read_text())
    from validate_artifacts import _validate  # noqa: WPS433
    errors: list[str] = []
    _validate(value, schema, "<root>", errors)
    return errors


def _canonical_plan_filename(index: int, layout: str) -> str:
    """Canonical slide_plan filename: zero-padded two-digit index +
    layout token from the JSON, e.g. ``01_cover.json``,
    ``09_two_column.json``. Mirrors the convention the existing
    examples and the render-model exporter both use."""
    return f"{index:02d}_{layout}.json"


def init_slide_plans(
    *,
    workspace: Path,
    template_root: Path,
    specs_dir: Path,
) -> tuple[int, str]:
    """Run the full Stage-5 bridge. Returns (exit_code, message).

    Filesystem contract: preflight failures (bad inputs, missing /
    schema-invalid prior-stage artifacts, pre-existing non-empty
    ``slide_plans/``, malformed specs) leave the workspace untouched.

    A post-write re-validation failure rolls back EVERY slide_plan the
    helper wrote so the workspace returns to its pre-call state."""
    # --workspace shape gates (string-level FIRST, then filesystem).
    if _has_uri_scheme(str(workspace)):
        return 2, (
            f"FAIL: --workspace {workspace} looks like a URI; "
            f"init_slide_plans only accepts local directory paths"
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

    # --template-root shape gates.
    if _has_uri_scheme(str(template_root)):
        return 2, (
            f"FAIL: --template-root {template_root} looks like a URI; "
            f"init_slide_plans only accepts local directory paths"
        )
    if template_root.is_symlink():
        return 2, (
            f"FAIL: --template-root {template_root} is a symlink; "
            f"refusing to follow it."
        )
    if not template_root.exists():
        return 2, f"FAIL: --template-root {template_root} does not exist"
    if not template_root.is_dir():
        return 2, (
            f"FAIL: --template-root {template_root} is not a directory"
        )

    # --specs-dir shape gates.
    if _has_uri_scheme(str(specs_dir)):
        return 2, (
            f"FAIL: --specs-dir {specs_dir} looks like a URI; "
            f"init_slide_plans only accepts local directory paths"
        )
    if specs_dir.is_symlink():
        return 2, (
            f"FAIL: --specs-dir {specs_dir} is a symlink; refusing to "
            f"follow it. Pass a regular directory path."
        )
    if not specs_dir.exists():
        return 2, f"FAIL: --specs-dir {specs_dir} does not exist"
    if not specs_dir.is_dir():
        return 2, f"FAIL: --specs-dir {specs_dir} is not a directory"

    # Stage-5 contract gate: the slide_plans/ output directory. A
    # symlink at slide_plans/ (broken or resolvable) is refused — same
    # anti-pattern the other init_* helpers reject at their write paths.
    # A non-empty pre-existing slide_plans/ is refused so no prior file
    # is silently overwritten; an empty directory is accepted and reused.
    plans_dir = workspace / SLIDE_PLANS_DIRNAME
    is_symlink, msg = _refuse_symlink(plans_dir, SLIDE_PLANS_DIRNAME)
    if is_symlink:
        return 2, msg
    if plans_dir.exists():
        if not plans_dir.is_dir():
            return 2, (
                f"FAIL: {plans_dir} exists but is not a directory"
            )
        existing = sorted(plans_dir.iterdir())
        if existing:
            names = [p.name for p in existing]
            return 2, (
                f"FAIL: {plans_dir} is not empty (contains {names}); "
                f"init_slide_plans refuses to overwrite existing slide "
                f"plans. Remove its contents and re-run."
            )

    # Stage-1 prerequisite: source_manifest.json must exist as a
    # regular file. The bridge below validates its contents.
    manifest_path = workspace / SOURCE_MANIFEST_FILENAME
    is_symlink, msg = _refuse_symlink(manifest_path, SOURCE_MANIFEST_FILENAME)
    if is_symlink:
        return 2, msg
    if not manifest_path.is_file():
        return 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{SOURCE_MANIFEST_FILENAME}; run scripts/init_workspace.py "
            f"first to seed Stage-1 intake."
        )

    # Stage-2 prerequisite: deck_brief.json must exist as a regular file.
    brief_path = workspace / DECK_BRIEF_FILENAME
    is_symlink, msg = _refuse_symlink(brief_path, DECK_BRIEF_FILENAME)
    if is_symlink:
        return 2, msg
    if not brief_path.is_file():
        return 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{DECK_BRIEF_FILENAME}; run scripts/init_deck_brief.py "
            f"first to seed Stage-2."
        )

    # Stage-3 prerequisite: deck_plan.json must exist as a regular file.
    plan_path = workspace / DECK_PLAN_FILENAME
    is_symlink, msg = _refuse_symlink(plan_path, DECK_PLAN_FILENAME)
    if is_symlink:
        return 2, msg
    if not plan_path.is_file():
        return 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{DECK_PLAN_FILENAME}; run scripts/init_deck_plan.py first "
            f"to seed Stage-3."
        )

    # Stage-4 prerequisite: design_system.json must exist as a regular file.
    ds_path = workspace / DESIGN_SYSTEM_FILENAME
    is_symlink, msg = _refuse_symlink(ds_path, DESIGN_SYSTEM_FILENAME)
    if is_symlink:
        return 2, msg
    if not ds_path.is_file():
        return 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{DESIGN_SYSTEM_FILENAME}; run scripts/init_design_system.py "
            f"first to seed Stage-4."
        )

    # Stage-1/Stage-2 bridge must pass (manifest <-> source.md <->
    # deck_brief.source_refs). This is the ONLY place input/source.md
    # is touched, and the bridge only does byte-level integrity checks
    # (UTF-8 decode, byte_count / line_count / sha256 match against the
    # manifest). The decoded string is discarded inside the bridge.
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

    # Re-parse + schema-validate the four prior-stage artifacts.
    try:
        brief = json.loads(brief_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return 2, f"FAIL: cannot read {brief_path}: {exc}"
    if not isinstance(brief, dict):
        return 2, (
            f"FAIL: {brief_path} did not decode to an object "
            f"(got {type(brief).__name__})"
        )
    brief_errors = _schema_validate(brief, DECK_BRIEF_SCHEMA)
    if brief_errors:
        return 1, (
            f"FAIL: {brief_path} does not validate against "
            f"deck_brief.schema.json: {brief_errors}"
        )

    try:
        plan = json.loads(plan_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return 2, f"FAIL: cannot read {plan_path}: {exc}"
    if not isinstance(plan, dict):
        return 2, (
            f"FAIL: {plan_path} did not decode to an object "
            f"(got {type(plan).__name__})"
        )
    plan_errors = _schema_validate(plan, DECK_PLAN_SCHEMA)
    if plan_errors:
        return 1, (
            f"FAIL: {plan_path} does not validate against "
            f"deck_plan.schema.json: {plan_errors}"
        )

    try:
        ds = json.loads(ds_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return 2, f"FAIL: cannot read {ds_path}: {exc}"
    if not isinstance(ds, dict):
        return 2, (
            f"FAIL: {ds_path} did not decode to an object "
            f"(got {type(ds).__name__})"
        )
    ds_errors = _schema_validate(ds, DESIGN_SYSTEM_SCHEMA)
    if ds_errors:
        return 1, (
            f"FAIL: {ds_path} does not validate against "
            f"design_system.schema.json: {ds_errors}"
        )

    # Planner-semantics cross-checks the schema cannot express. We
    # re-use init_deck_plan.py's gate so Stage-5 enforces EXACTLY what
    # Stage-3 would have accepted (planned-count equality, slide
    # indices unique AND contiguous 1..N, section coverage 1:1,
    # slide.section_id resolution, slide.source_refs subset of
    # deck_brief.source_refs).
    brief_refs_raw = brief.get("source_refs") or []
    brief_refs = [r for r in brief_refs_raw if isinstance(r, str)]
    planner_errors = _cross_check_planner_semantics(
        plan=plan, brief_source_refs=brief_refs,
    )
    if planner_errors:
        return 1, (
            f"FAIL: {plan_path} fails planner-semantics cross-checks "
            f"(the same gate init_deck_plan.py applies before writing "
            f"a Stage-3 artifact): " + "; ".join(planner_errors)
        )

    template_name = plan.get("template")
    if not isinstance(template_name, str) or not template_name:
        return 1, (
            f"FAIL: {plan_path}.template must be a non-empty string "
            f"(got {template_name!r})"
        )
    # Path-safety on deck_plan.template (rejects URIs, '..', leading
    # slash); then symlink-escape check via _resolves_within. No
    # product-level default — "business_review" is just the template
    # the current repo ships.
    if not local_path_is_safe(template_name):
        return 2, (
            f"FAIL: deck_plan.template {template_name!r} is not a "
            f"safe local path; refusing to resolve."
        )
    if not _resolves_within(template_root, template_name):
        return 2, (
            f"FAIL: deck_plan.template {template_name!r} escapes "
            f"--template-root {template_root} after resolution; "
            f"refusing."
        )
    template_dir = template_root / template_name
    if template_dir.is_symlink():
        return 2, (
            f"FAIL: template directory {template_dir} is a symlink; "
            f"refusing to follow it."
        )
    if not template_dir.is_dir():
        return 2, (
            f"FAIL: template {template_name!r} not found under "
            f"--template-root (expected directory {template_dir})"
        )

    template_json_path = template_dir / "template.json"
    is_symlink, msg = _refuse_symlink(template_json_path, "template.json")
    if is_symlink:
        return 2, msg
    if not template_json_path.is_file():
        return 2, (
            f"FAIL: template {template_name!r} has no template.json "
            f"(expected {template_json_path})"
        )
    try:
        template = json.loads(template_json_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return 2, (
            f"FAIL: {template_json_path} did not parse as JSON: {exc}"
        )
    if not isinstance(template, dict):
        return 2, (
            f"FAIL: {template_json_path} did not decode to an object "
            f"(got {type(template).__name__})"
        )
    template_errors = _schema_validate(template, TEMPLATE_SCHEMA)
    if template_errors:
        return 1, (
            f"FAIL: {template_json_path} does not validate against "
            f"template.schema.json: {template_errors}"
        )

    declared_layouts_raw = template.get("layouts") or []
    declared_layouts = {
        n for n in declared_layouts_raw if isinstance(n, str)
    }

    # Every deck_plan slide layout must be declared by the template.
    # This is the same gate validate_workspace.check_template_chain
    # applies as `plan.layouts`. Stage-5 needs it explicitly because
    # template-layout drift makes downstream slot coverage meaningless.
    deck_slides = plan.get("slides") or []
    unknown_layouts = []
    for s in deck_slides:
        if not isinstance(s, dict):
            continue
        layout = s.get("layout")
        if not isinstance(layout, str) or layout not in declared_layouts:
            unknown_layouts.append(
                f"slide index {s.get('index')}: layout {layout!r}"
            )
    if unknown_layouts:
        return 1, (
            f"FAIL: {plan_path} references layouts not declared by "
            f"template {template_name!r} (declared: "
            f"{sorted(declared_layouts)}): " + "; ".join(unknown_layouts)
        )

    # Pre-load and schema-validate the per-layout files we need. A
    # missing or malformed layout file is fail-closed since slot
    # coverage cannot proceed without it. Path-safety is mandatory
    # here: deck_plan.slides[].layout is schema-validated as a non-
    # empty string but is NOT pattern-locked, so a deck_plan whose
    # slide layout is e.g. "../../etc/passwd" would schema-validate
    # and walk the path. We refuse: (a) a symlink at the layouts/
    # subdir itself; (b) layout names that fail local_path_is_safe;
    # (c) any layout file that resolves outside the template_dir.
    layouts_dir = template_dir / "layouts"
    is_symlink, msg = _refuse_symlink(layouts_dir, "layouts/")
    if is_symlink:
        return 2, msg
    if not layouts_dir.is_dir():
        return 2, (
            f"FAIL: template {template_name!r} has no layouts/ directory "
            f"(expected {layouts_dir})"
        )
    deck_layouts_used = {
        s["layout"] for s in deck_slides
        if isinstance(s, dict) and isinstance(s.get("layout"), str)
    }
    layouts_by_name: dict[str, dict] = {}
    for layout_name in sorted(deck_layouts_used):
        if not local_path_is_safe(layout_name):
            return 2, (
                f"FAIL: deck_plan slide layout {layout_name!r} is not a "
                f"safe local path; refusing to resolve."
            )
        layout_ref = f"layouts/{layout_name}.json"
        if not _resolves_within(template_dir, layout_ref):
            return 2, (
                f"FAIL: deck_plan slide layout {layout_name!r} escapes "
                f"template {template_name!r} after resolution; refusing."
            )
        layout_file = template_dir / layout_ref
        is_symlink, msg = _refuse_symlink(
            layout_file, f"layouts/{layout_name}.json",
        )
        if is_symlink:
            return 2, msg
        if not layout_file.is_file():
            return 2, (
                f"FAIL: template {template_name!r} layout file "
                f"{layout_file} does not exist"
            )
        try:
            layout = json.loads(layout_file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return 2, (
                f"FAIL: {layout_file} did not parse as JSON: {exc}"
            )
        if not isinstance(layout, dict):
            return 2, (
                f"FAIL: {layout_file} did not decode to an object "
                f"(got {type(layout).__name__})"
            )
        layout_errors = _schema_validate(layout, LAYOUT_SCHEMA)
        if layout_errors:
            return 1, (
                f"FAIL: {layout_file} does not validate against "
                f"layout.schema.json: {layout_errors}"
            )
        layouts_by_name[layout_name] = layout

    # Build deck_plan slide map for cross-checks.
    deck_slides_by_index: dict[int, dict] = {}
    for s in deck_slides:
        if isinstance(s, dict) and isinstance(s.get("index"), int):
            deck_slides_by_index[s["index"]] = s
    expected_indices = sorted(deck_slides_by_index)

    # Read every *.json file at the specs-dir root. Symlinks at any
    # individual spec file are refused. Files that do not parse / do
    # not decode to an object / fail schema validation surface a
    # clear per-file FAIL.
    spec_files = sorted(specs_dir.glob("*.json"))
    if not spec_files:
        return 2, (
            f"FAIL: --specs-dir {specs_dir} contains no *.json spec "
            f"files (expected one per deck_plan slide)"
        )
    specs_by_index: dict[int, tuple[Path, dict]] = {}
    duplicates: list[str] = []
    for spec_file in spec_files:
        is_symlink, msg = _refuse_symlink(
            spec_file, f"--specs-dir/{spec_file.name}",
        )
        if is_symlink:
            return 2, msg
        if not spec_file.is_file():
            return 2, (
                f"FAIL: {spec_file} is not a regular file"
            )
        try:
            spec = json.loads(spec_file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return 2, (
                f"FAIL: {spec_file} did not parse as JSON: {exc}"
            )
        if not isinstance(spec, dict):
            return 2, (
                f"FAIL: {spec_file} did not decode to an object "
                f"(got {type(spec).__name__})"
            )
        errs = _schema_validate(spec, SLIDE_PLAN_SCHEMA)
        if errs:
            return 1, (
                f"FAIL: {spec_file} does not validate against "
                f"slide_plan.schema.json: " + "; ".join(errs)
            )
        idx = spec["index"]
        if idx in specs_by_index:
            prior_file = specs_by_index[idx][0]
            duplicates.append(
                f"index {idx}: {prior_file.name} and {spec_file.name}"
            )
        else:
            specs_by_index[idx] = (spec_file, spec)
    if duplicates:
        return 1, (
            f"FAIL: --specs-dir {specs_dir} contains duplicate slide "
            f"indices: " + "; ".join(duplicates)
        )

    # Coverage: every deck_plan index has a spec; no orphan specs.
    spec_index_set = set(specs_by_index)
    deck_index_set = set(deck_slides_by_index)
    missing = sorted(deck_index_set - spec_index_set)
    orphans = sorted(spec_index_set - deck_index_set)
    if missing:
        return 1, (
            f"FAIL: --specs-dir {specs_dir} is missing slide_plans for "
            f"deck_plan indices {missing} (deck declares "
            f"{sorted(deck_index_set)})"
        )
    if orphans:
        return 1, (
            f"FAIL: --specs-dir {specs_dir} contains orphan slide_plan "
            f"indices {orphans} that --workspace deck_plan does not "
            f"declare (deck declares {sorted(deck_index_set)})"
        )

    # Per-spec match: layout / title agree with deck_plan; required
    # layout slots are covered. We collect all errors before failing
    # so the operator sees every spec-level problem at once.
    mismatch_errors: list[str] = []
    slot_errors: list[str] = []
    for idx in expected_indices:
        spec_file, spec = specs_by_index[idx]
        deck_slide = deck_slides_by_index[idx]
        if spec.get("layout") != deck_slide.get("layout"):
            mismatch_errors.append(
                f"{spec_file.name}: layout {spec.get('layout')!r} != "
                f"deck_plan slide {idx} layout "
                f"{deck_slide.get('layout')!r}"
            )
        if spec.get("title") != deck_slide.get("title"):
            mismatch_errors.append(
                f"{spec_file.name}: title {spec.get('title')!r} != "
                f"deck_plan slide {idx} title "
                f"{deck_slide.get('title')!r}"
            )
        layout = layouts_by_name.get(spec.get("layout"))
        if layout is None:
            # Already filtered upstream — spec.layout would have been
            # caught at unknown_layouts. Defensive belt-and-braces.
            mismatch_errors.append(
                f"{spec_file.name}: layout {spec.get('layout')!r} not "
                f"loaded from template"
            )
            continue
        problems = _slide_plan_against_layout(spec, layout)
        if problems:
            slot_errors.append(
                f"{spec_file.name} (layout {spec.get('layout')!r}): "
                + "; ".join(problems)
            )
    if mismatch_errors:
        return 1, (
            f"FAIL: spec / deck_plan mismatch: "
            + "; ".join(mismatch_errors)
        )
    if slot_errors:
        return 1, (
            f"FAIL: required layout slots not covered: "
            + "; ".join(slot_errors)
        )

    # Write. Same rollback contract as the other init_* helpers: the
    # catch clause is (Exception, SystemExit) so validate_artifact's
    # SystemExit branch on read-errors still routes through rollback.
    # KeyboardInterrupt is intentionally NOT caught.
    #
    # Rollback symmetry: track whether this run created plans_dir so
    # we can remove it on failure, matching init_workspace.py's
    # "remove what this run created" contract. An empty pre-existing
    # plans_dir is preserved as-is.
    plans_dir_created_by_this_run = not plans_dir.exists()
    if plans_dir_created_by_this_run:
        try:
            plans_dir.mkdir(parents=False, exist_ok=False)
        except (Exception, SystemExit) as exc:
            return 2, (
                f"FAIL: cannot create {plans_dir}: "
                f"{type(exc).__name__}: {exc}"
            )

    written: list[Path] = []
    for idx in expected_indices:
        spec_file, spec = specs_by_index[idx]
        out_name = _canonical_plan_filename(idx, spec["layout"])
        out_path = plans_dir / out_name
        # Pre-track out_path BEFORE the write so a half-written file
        # (write_text opens + truncates + writes; a mid-write failure
        # can leave the file at zero or partial bytes) is still
        # included in the rollback set. Mirrors the explicit
        # `if plan_path.exists(): plan_path.unlink()` pattern
        # init_deck_plan.py uses around its single write call,
        # generalized to N files.
        written.append(out_path)
        try:
            out_path.write_text(
                json.dumps(spec, indent=2, sort_keys=True) + "\n"
            )
        except (Exception, SystemExit) as exc:
            _rollback(
                written, plans_dir,
                created_plans_dir=plans_dir_created_by_this_run,
            )
            return 2, (
                f"FAIL: writing {out_path} raised "
                f"{type(exc).__name__}: {exc}\n"
                f"rolled back: removed up to {len(written)} slide_plan "
                f"file(s)"
                + (f" and slide_plans/ directory"
                   if plans_dir_created_by_this_run else "")
            )

    # Post-write re-validation: every file we just wrote must validate
    # against slide_plan.schema.json on disk. A failure here rolls
    # back every file we wrote AND (if this run created it) the
    # slide_plans/ directory itself, so the workspace returns to its
    # pre-call state.
    for out_path in written:
        try:
            errors = validate_artifact(out_path, SLIDE_PLAN_SCHEMA)
        except (Exception, SystemExit) as exc:
            _rollback(
                written, plans_dir,
                created_plans_dir=plans_dir_created_by_this_run,
            )
            return 1, (
                f"FAIL: post-write re-validation of {out_path} raised "
                f"{type(exc).__name__}: {exc}\n"
                f"rolled back: removed {len(written)} slide_plan file(s)"
                + (f" and slide_plans/ directory"
                   if plans_dir_created_by_this_run else "")
            )
        if errors:
            _rollback(
                written, plans_dir,
                created_plans_dir=plans_dir_created_by_this_run,
            )
            return 1, (
                f"FAIL: on-disk slide_plan at {out_path} did not "
                f"re-validate: {errors}\n"
                f"rolled back: removed {len(written)} slide_plan file(s)"
                + (f" and slide_plans/ directory"
                   if plans_dir_created_by_this_run else "")
            )

    return 0, (
        f"OK: Stage-5 slide_plans seeded under {plans_dir}.\n"
        f"  template (from deck_plan.template): {template_name!r}\n"
        f"  slides written: {len(written)} "
        f"({[p.name for p in written]})\n"
        f"Next stages (agent-driven; init_slide_plans.py does not "
        f"automate them):\n"
        f"  6. image_manifest.json\n"
        f"Once that exists, scripts/run_pipeline.py can take over "
        f"for stages 7-10."
    )


def _rollback(
    written: list[Path], plans_dir: Path, *, created_plans_dir: bool,
) -> None:
    """Best-effort rollback. Removes every file ``written`` records
    (each path may or may not actually exist on disk — a mid-write
    failure can leave the path partially created, completed, or
    missing; ``unlink()``'s OSError is swallowed in every case). When
    ``created_plans_dir`` is True, also rmdir() the now-empty
    ``slide_plans/`` directory so the workspace returns to its
    pre-call state. This mirrors init_workspace.py's "remove what
    this run created" contract — an empty pre-existing slide_plans/
    is intentionally preserved (``created_plans_dir=False``)."""
    for p in written:
        try:
            p.unlink()
        except OSError:
            pass
    if created_plans_dir:
        try:
            plans_dir.rmdir()
        except OSError:
            # rmdir refuses if the directory is non-empty or has
            # been removed already; either way the rollback has
            # done what it can.
            pass


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs under
# tempfile.TemporaryDirectory(); no fixture leaks into the repo.
# ---------------------------------------------------------------------------

_SYNTH_SOURCE_MD = (
    "# Synthetic Source\n\n"
    "Synthetic .md body — never inspected by init_slide_plans.\n"
    "Line three.\n"
)

_SAMPLE_THEME = {
    "name": "synthetic_template",
    "version": "0.1.0",
    "status": "scaffold",
    "palette": {
        "primary": "#112233",
        "secondary": "#445566",
        "accent": "#AABBCC",
        "background": "#FFFFFF",
        "text": "#101010",
    },
    "typography": {
        "heading": {"font_family": "Arial, sans-serif", "size_pt": 24},
        "body": {"font_family": "Arial, sans-serif", "size_pt": 12},
    },
    "grid": {"width_px": 1280, "height_px": 720, "margin_px": 32},
}

_SAMPLE_DESIGN_SYSTEM = {
    "palette": {
        "primary": "#112233",
        "background": "#FFFFFF",
        "text": "#101010",
    },
    "typography": {
        "heading": {"font_family": "Arial, sans-serif", "size_pt": 24},
        "body": {"font_family": "Arial, sans-serif", "size_pt": 12},
    },
    "grid": {"width_px": 1280, "height_px": 720, "margin_px": 32},
}


def _seed_stage1234_workspace(
    ws: Path,
    *,
    template_name: str = "synthetic_template",
    source_id: str = "synthetic_src",
    body: bytes | None = None,
    write_source_manifest: bool = True,
    write_deck_brief: bool = True,
    write_deck_plan: bool = True,
    write_design_system: bool = True,
    plan_override: dict | None = None,
    plan_raw_text: str | None = None,
    ds_override: dict | None = None,
    ds_raw_text: str | None = None,
    brief_source_refs: list[str] | None = None,
    slide_count: int = 2,
) -> None:
    """Mimic what init_workspace + init_deck_brief + init_deck_plan +
    init_design_system would have written. Synthetic only; does not
    invoke them as subprocesses so targeted negative mutations stay
    simple."""
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
        refs = brief_source_refs or [source_id]
        brief = {
            "title": "Synthetic Title",
            "audience": "Synthetic Audience",
            "objective": "Synthetic Objective",
            "source_refs": refs,
        }
        (ws / DECK_BRIEF_FILENAME).write_text(
            json.dumps(brief, indent=2, sort_keys=True) + "\n"
        )
    if write_deck_plan:
        if plan_raw_text is not None:
            (ws / DECK_PLAN_FILENAME).write_text(plan_raw_text)
        elif plan_override is not None:
            (ws / DECK_PLAN_FILENAME).write_text(
                json.dumps(plan_override, indent=2, sort_keys=True) + "\n"
            )
        else:
            layouts = ["cover", "kpi_dashboard"][:slide_count]
            slides = [
                {
                    "index": i + 1,
                    "layout": layouts[i],
                    "title": f"Slide {i+1}",
                    "section_id": "main",
                    "summary": f"Synthetic slide {i+1}.",
                    "density": "low",
                    "source_refs": [source_id],
                }
                for i in range(slide_count)
            ]
            plan = {
                "template": template_name,
                "planning": {
                    "planned_slide_count": slide_count,
                    "rationale": (
                        "Synthetic plan for init_slide_plans self-test."
                    ),
                },
                "sections": [
                    {
                        "id": "main",
                        "title": "Main",
                        "summary": "Synthetic section.",
                        "slide_indices": [i + 1 for i in range(slide_count)],
                    },
                ],
                "slides": slides,
            }
            (ws / DECK_PLAN_FILENAME).write_text(
                json.dumps(plan, indent=2, sort_keys=True) + "\n"
            )
    if write_design_system:
        if ds_raw_text is not None:
            (ws / DESIGN_SYSTEM_FILENAME).write_text(ds_raw_text)
        else:
            ds = ds_override if ds_override is not None else dict(
                _SAMPLE_DESIGN_SYSTEM
            )
            (ws / DESIGN_SYSTEM_FILENAME).write_text(
                json.dumps(ds, indent=2, sort_keys=True) + "\n"
            )


def _seed_template_root(
    template_root: Path,
    *,
    template_name: str = "synthetic_template",
    layouts: list[str] | None = None,
) -> Path:
    """Write a synthetic template under
    <template-root>/<template_name>/ that declares the cover and
    kpi_dashboard layouts the seeded deck_plan uses. Each layout file
    declares one required slot whose id matches a block id the
    spec-builder produces, so the slot-coverage gate is satisfied on
    a positive run."""
    if layouts is None:
        layouts = ["cover", "kpi_dashboard"]
    template_root.mkdir(parents=True, exist_ok=True)
    tdir = template_root / template_name
    tdir.mkdir(parents=True, exist_ok=True)
    template_manifest = {
        "name": template_name,
        "version": "0.1.0",
        "status": "scaffold",
        "theme_ref": "theme.json",
        "layouts": layouts,
    }
    (tdir / "template.json").write_text(
        json.dumps(template_manifest, indent=2, sort_keys=True) + "\n"
    )
    theme = dict(_SAMPLE_THEME)
    theme["name"] = template_name
    (tdir / "theme.json").write_text(
        json.dumps(theme, indent=2, sort_keys=True) + "\n"
    )
    (tdir / "layouts").mkdir(exist_ok=True)
    layout_defs = {
        "cover": {
            "name": "cover",
            "status": "skeleton",
            "purpose": "Opening slide.",
            "slots": [
                {
                    "id": "title", "type": "text", "required": True,
                    "primitive_kind": "text",
                },
                {
                    "id": "subtitle", "type": "text", "required": False,
                    "primitive_kind": "text",
                },
            ],
        },
        "kpi_dashboard": {
            "name": "kpi_dashboard",
            "status": "skeleton",
            "purpose": "Grid of KPI tiles.",
            "slots": [
                {
                    "id": "title", "type": "text", "required": True,
                    "primitive_kind": "text",
                },
                {
                    "id": "kpis", "type": "kpi", "required": True,
                    "primitive_kind": "kpi",
                },
            ],
        },
        "key_message": {
            "name": "key_message",
            "status": "skeleton",
            "purpose": "Single hero statement.",
            "slots": [
                {
                    "id": "title", "type": "text", "required": True,
                    "primitive_kind": "text",
                },
                {
                    "id": "message", "type": "text", "required": True,
                    "primitive_kind": "text",
                },
            ],
        },
    }
    for layout_name in layouts:
        if layout_name not in layout_defs:
            # Minimal valid layout with only a required title slot.
            layout = {
                "name": layout_name,
                "status": "skeleton",
                "slots": [
                    {
                        "id": "title", "type": "text", "required": True,
                        "primitive_kind": "text",
                    },
                ],
            }
        else:
            layout = layout_defs[layout_name]
        (tdir / "layouts" / f"{layout_name}.json").write_text(
            json.dumps(layout, indent=2, sort_keys=True) + "\n"
        )
    return tdir


def _build_positive_specs(
    specs_dir: Path,
    *,
    deck_plan: dict | None = None,
) -> None:
    """Write spec files matching the synthetic 2-slide deck_plan
    (slide 1: cover with title; slide 2: kpi_dashboard with title + kpis)."""
    specs_dir.mkdir(parents=True, exist_ok=True)
    if deck_plan is None:
        slides = [
            {
                "index": 1, "layout": "cover", "title": "Slide 1",
                "blocks": [
                    {"id": "title", "kind": "text",
                     "content": "Slide 1 title"},
                ],
            },
            {
                "index": 2, "layout": "kpi_dashboard", "title": "Slide 2",
                "blocks": [
                    {"id": "title", "kind": "text",
                     "content": "Slide 2 title"},
                    {"id": "kpis", "kind": "kpi",
                     "content": [
                         {"label": "m1", "value": "v1"},
                     ]},
                ],
            },
        ]
    else:
        slides = []
        for ds in deck_plan["slides"]:
            blocks = [
                {"id": "title", "kind": "text",
                 "content": f"{ds['title']} title"},
            ]
            if ds["layout"] == "kpi_dashboard":
                blocks.append({
                    "id": "kpis", "kind": "kpi",
                    "content": [{"label": "m1", "value": "v1"}],
                })
            elif ds["layout"] == "key_message":
                blocks.append({
                    "id": "message", "kind": "text",
                    "content": "synthetic message",
                })
            slides.append({
                "index": ds["index"],
                "layout": ds["layout"],
                "title": ds["title"],
                "blocks": blocks,
            })
    for s in slides:
        path = specs_dir / f"spec_{s['index']:02d}.json"
        path.write_text(json.dumps(s, indent=2, sort_keys=True) + "\n")


def _expect(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


def _run_self_tests() -> list[tuple[str, bool, str]]:
    import tempfile

    results: list[tuple[str, bool, str]] = []

    # 1. happy path: 2-slide deck_plan with 2 specs writes 2 canonical
    # files; helper exits 0; output files are schema-valid on disk.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_happy"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        plans_dir = ws / SLIDE_PLANS_DIRNAME
        f1 = plans_dir / "01_cover.json"
        f2 = plans_dir / "02_kpi_dashboard.json"
        ok = (
            rc == 0
            and f1.is_file() and f2.is_file()
            and not validate_artifact(f1, SLIDE_PLAN_SCHEMA)
            and not validate_artifact(f2, SLIDE_PLAN_SCHEMA)
        )
        results.append(_expect(
            "happy path: 2-slide deck_plan + matching specs writes "
            "canonical 01_cover.json / 02_kpi_dashboard.json",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 2. determinism: two independent runs from identical inputs
    # produce byte-identical slide_plan files.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws_a = td / "ws_a"
        ws_b = td / "ws_b"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws_a)
        _seed_stage1234_workspace(ws_b)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        rc_a, _ = init_slide_plans(
            workspace=ws_a, template_root=troot, specs_dir=specs,
        )
        rc_b, _ = init_slide_plans(
            workspace=ws_b, template_root=troot, specs_dir=specs,
        )
        if rc_a == 0 and rc_b == 0:
            files_a = sorted((ws_a / SLIDE_PLANS_DIRNAME).glob("*.json"))
            files_b = sorted((ws_b / SLIDE_PLANS_DIRNAME).glob("*.json"))
            same_names = [p.name for p in files_a] == [p.name for p in files_b]
            same_bytes = all(
                (ws_a / SLIDE_PLANS_DIRNAME / p.name).read_bytes()
                == (ws_b / SLIDE_PLANS_DIRNAME / p.name).read_bytes()
                for p in files_a
            )
            ok = same_names and same_bytes
        else:
            ok = False
        results.append(_expect(
            "determinism: two independent runs produce byte-identical "
            "slide_plan files (no timestamps, no env leak, sorted keys)",
            ok, f"rc_a={rc_a}, rc_b={rc_b}",
        ))

    # 3. missing deck_plan.json -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_plan"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws, write_deck_plan=False)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc == 2
            and DECK_PLAN_FILENAME in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "missing deck_plan.json refused (no silent fallback)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 4. malformed deck_plan (non-JSON bytes) -> refused; no
    # slide_plans/ directory created.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_bad_plan"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws, plan_raw_text="{ not valid json")
        _seed_template_root(troot)
        _build_positive_specs(specs)
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc in (1, 2)
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "malformed deck_plan.json refused before any slide_plan "
            "is written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 5. missing design_system.json -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_ds"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws, write_design_system=False)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc == 2
            and DESIGN_SYSTEM_FILENAME in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "missing design_system.json refused (no silent fallback)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 6. malformed design_system (schema invalid: bad hex color) -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_bad_ds"
        troot = td / "tpl"
        specs = td / "specs"
        bad_ds = dict(_SAMPLE_DESIGN_SYSTEM)
        bad_ds["palette"] = dict(bad_ds["palette"])
        bad_ds["palette"]["primary"] = "not-a-hex-color"
        _seed_stage1234_workspace(ws, ds_override=bad_ds)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc == 1
            and "design_system" in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "schema-invalid design_system.json (bad hex color) refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 7. unknown template (deck_plan.template names a template the
    # template-root does not ship) -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_unknown_tpl"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws, template_name="not_a_real_template")
        _seed_template_root(troot, template_name="synthetic_template")
        _build_positive_specs(specs)
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc == 2
            and "not_a_real_template" in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "unknown template (no business_review fallback) refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 8. spec missing a required layout slot -> refused at slot coverage.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_missing_slot"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        # Drop the required "kpis" block from slide 2.
        spec_path = specs / "spec_02.json"
        spec = json.loads(spec_path.read_text())
        spec["blocks"] = [b for b in spec["blocks"] if b["id"] != "kpis"]
        spec_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc == 1
            and "missing required slot" in msg
            and "kpis" in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "spec missing a required layout slot refused at slot "
            "coverage; no slide_plan file written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 9. orphan slide_plan: spec.index not declared by deck_plan -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_orphan"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        # Add an extra spec with index 9 the deck_plan does not declare.
        (specs / "spec_99.json").write_text(json.dumps({
            "index": 9,
            "layout": "cover",
            "title": "Orphan",
            "blocks": [
                {"id": "title", "kind": "text", "content": "Orphan title"},
            ],
        }, indent=2, sort_keys=True) + "\n")
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc == 1
            and "orphan" in msg.lower()
            and "9" in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "orphan spec (index not in deck_plan) refused; no "
            "slide_plan written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 10. missing slide_plan: deck_plan declares more slides than the
    # specs-dir supplies -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_missing"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        # Remove the spec for slide 2.
        (specs / "spec_02.json").unlink()
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc == 1
            and "missing slide_plans" in msg
            and "2" in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "missing spec (deck_plan declares slide 2 but specs-dir "
            "has no entry) refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 11. duplicate slide_plan index across two spec files -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_dup"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        # Duplicate spec_01 under a different filename.
        original = (specs / "spec_01.json").read_text()
        (specs / "spec_01_dup.json").write_text(original)
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc == 1
            and "duplicate" in msg
            and "index 1" in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "duplicate slide_plan index across two spec files refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 12. --specs-dir is a symlink -> refused at the preflight.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_specs_link"
        troot = td / "tpl"
        real_specs = td / "real_specs"
        link_specs = td / "link_specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(real_specs)
        link_specs.symlink_to(real_specs)
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=link_specs,
        )
        ok = (
            rc == 2
            and "symlink" in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "symlink at --specs-dir refused at the preflight",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 12b. an individual spec file is a symlink -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_one_spec_link"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        # Replace spec_01.json with a symlink to a sibling file.
        original = specs / "spec_01.json"
        sibling = td / "elsewhere.json"
        sibling.write_text(original.read_text())
        original.unlink()
        original.symlink_to(sibling)
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc == 2
            and "symlink" in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "symlink at an individual --specs-dir/*.json file refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 13. pre-existing non-empty slide_plans/ -> refused; prior content
    # preserved byte-identical.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_existing"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        plans_dir = ws / SLIDE_PLANS_DIRNAME
        plans_dir.mkdir()
        prior_path = plans_dir / "01_cover.json"
        prior_bytes = b'{"prior":true}\n'
        prior_path.write_bytes(prior_bytes)
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        preserved = prior_path.read_bytes() == prior_bytes
        ok = (
            rc == 2
            and "not empty" in msg
            and preserved
        )
        results.append(_expect(
            "pre-existing non-empty slide_plans/ refused; prior bytes "
            "preserved",
            ok, f"rc={rc}, preserved={preserved}, msg={msg!r}",
        ))

    # 14. no raw source file read by the helper. Embed a unique
    # marker phrase into input/source.md and assert it never appears
    # in any written slide_plan.
    marker = "MARKER_NEVER_EXTRACT_5stage_b91f7c"
    body = (
        f"# Title\n\nBody with {marker} in it.\n"
    ).encode("utf-8")
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_extract"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws, body=body)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        rc, _ = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = rc == 0
        if ok:
            for plan_file in sorted((ws / SLIDE_PLANS_DIRNAME).glob("*.json")):
                if marker in plan_file.read_text():
                    ok = False
                    break
        results.append(_expect(
            "source body marker phrase is NEVER copied into any "
            "slide_plan (helper does not extract content)",
            ok, f"rc={rc}",
        ))

    # 15. --workspace is a URI -> refused at the string layer.
    rc, msg = init_slide_plans(
        workspace=Path("https://attacker.example/ws"),
        template_root=Path("/tmp/no_tpl"),
        specs_dir=Path("/tmp/no_specs"),
    )
    ok = rc == 2 and "URI" in msg
    results.append(_expect(
        "--workspace with URI scheme refused at the string level",
        ok, f"rc={rc}",
    ))

    # 16. spec layout/title disagrees with deck_plan -> refused at the
    # mismatch gate.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_mismatch"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        # Mutate spec 1 to claim a different title than deck_plan has.
        spec1 = specs / "spec_01.json"
        s1 = json.loads(spec1.read_text())
        s1["title"] = "Different Title Than Deck Plan"
        spec1.write_text(json.dumps(s1, indent=2, sort_keys=True) + "\n")
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc == 1
            and "title" in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "spec/deck_plan title mismatch refused at the match gate; "
            "no slide_plan written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 17. spec is schema-invalid (missing required 'blocks' field) -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_spec_schema_bad"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        # Remove the required 'blocks' key from spec 1.
        spec1 = specs / "spec_01.json"
        s1 = json.loads(spec1.read_text())
        del s1["blocks"]
        spec1.write_text(json.dumps(s1, indent=2, sort_keys=True) + "\n")
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc == 1
            and "slide_plan.schema.json" in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "schema-invalid spec (missing 'blocks') refused at the "
            "schema layer",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 18. non-contiguous deck_plan indices ([1, 2, 4]) -> refused at
    # the planner-semantics cross-check (Stage-5 cannot advance from a
    # semantically invalid deck_plan).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_noncontig"
        troot = td / "tpl"
        specs = td / "specs"
        bad_plan = {
            "template": "synthetic_template",
            "planning": {
                "planned_slide_count": 3,
                "rationale": "Synthetic non-contiguous plan.",
            },
            "sections": [
                {
                    "id": "main",
                    "title": "Main",
                    "summary": "All",
                    "slide_indices": [1, 2, 4],
                },
            ],
            "slides": [
                {
                    "index": 1, "layout": "cover", "title": "S1",
                    "section_id": "main", "summary": "S1",
                    "density": "low", "source_refs": ["synthetic_src"],
                },
                {
                    "index": 2, "layout": "cover", "title": "S2",
                    "section_id": "main", "summary": "S2",
                    "density": "low", "source_refs": ["synthetic_src"],
                },
                {
                    "index": 4, "layout": "cover", "title": "S4",
                    "section_id": "main", "summary": "S4",
                    "density": "low", "source_refs": ["synthetic_src"],
                },
            ],
        }
        _seed_stage1234_workspace(ws, plan_override=bad_plan)
        _seed_template_root(troot)
        specs.mkdir()
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc == 1
            and "contiguous" in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "non-contiguous deck_plan indices ([1, 2, 4]) refused at "
            "the planner-semantics cross-check",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 19. deck_plan declares a layout the template does not -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_layout_undeclared"
        troot = td / "tpl"
        specs = td / "specs"
        # template declares only ['cover']
        _seed_template_root(troot, layouts=["cover"])
        # deck_plan slide 2 uses kpi_dashboard (NOT in template.layouts)
        _seed_stage1234_workspace(ws)
        _build_positive_specs(specs)
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc == 1
            and "kpi_dashboard" in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "deck_plan layout not declared by template refused at the "
            "template-chain gate",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 20. empty pre-existing slide_plans/ directory is accepted; the
    # helper writes into it without error.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_empty_dir"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        (ws / SLIDE_PLANS_DIRNAME).mkdir()
        rc, _ = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        f1 = ws / SLIDE_PLANS_DIRNAME / "01_cover.json"
        ok = rc == 0 and f1.is_file()
        results.append(_expect(
            "empty pre-existing slide_plans/ directory is accepted "
            "and written into",
            ok, f"rc={rc}",
        ))

    # 21. broken symlink at slide_plans/ refused; dangling target
    # never created.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_link_dir"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        target = td / "outside_dir_must_not_exist"
        assert not target.exists()
        (ws / SLIDE_PLANS_DIRNAME).symlink_to(target)
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        still_symlink = (ws / SLIDE_PLANS_DIRNAME).is_symlink()
        target_absent = not target.exists()
        ok = (
            rc == 2
            and "symlink" in msg
            and still_symlink
            and target_absent
        )
        results.append(_expect(
            "broken symlink at slide_plans/ refused before any write; "
            "dangling target never created",
            ok,
            f"rc={rc}, still_symlink={still_symlink}, "
            f"target_absent={target_absent}, msg={msg!r}",
        ))

    # 21b. symlink at the template's layouts/ subdirectory refused.
    # An attacker who controls the template root could otherwise
    # replace layouts/ with a symlink to a directory outside the
    # template; the helper would then read the per-layout files
    # from there. The gate fires BEFORE any layout file is opened.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_layouts_link"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        # Redirect <template>/layouts to a sibling directory the
        # helper has no business reading from.
        outside = td / "evil_layouts"
        outside.mkdir()
        # Plant a file the helper would otherwise mis-load if it
        # silently followed the symlink.
        (outside / "cover.json").write_text(json.dumps({
            "name": "cover", "status": "skeleton", "slots": [],
        }))
        layouts_dir = troot / "synthetic_template" / "layouts"
        import shutil
        shutil.rmtree(layouts_dir)
        layouts_dir.symlink_to(outside)
        rc, msg = init_slide_plans(
            workspace=ws, template_root=troot, specs_dir=specs,
        )
        ok = (
            rc == 2
            and "symlink" in msg
            and "layouts/" in msg
            and not (ws / SLIDE_PLANS_DIRNAME).exists()
        )
        results.append(_expect(
            "symlink at <template>/layouts/ refused before any layout "
            "file is opened",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # NOTE: A deck_plan whose slides[].layout escapes the template
    # dir via traversal (e.g. "../../etc/passwd") is already refused
    # at the earlier "deck_plan layouts not declared by template"
    # gate, because the template schema pattern-locks
    # template.layouts[] to ^[a-z][a-z0-9_]*$ — so any traversal-
    # shaped layout name in deck_plan can never appear in
    # declared_layouts. The local_path_is_safe / _resolves_within
    # checks above are belt-and-braces against template-schema
    # drift; we deliberately do not synthesize a self-test for that
    # path because it would require constructing a schema-invalid
    # template, which other gates refuse first.

    # 22. mocked post-write re-validation failure rolls back every
    # written slide_plan AND the slide_plans/ directory the helper
    # created in this run, so the workspace returns to its pre-call
    # state (no leftover files AND no leftover empty directory).
    import unittest.mock
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_rb"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        with unittest.mock.patch(
            f"{__name__}.validate_artifact",
            return_value=["forced test failure"],
        ):
            rc, msg = init_slide_plans(
                workspace=ws, template_root=troot, specs_dir=specs,
            )
        plans_dir = ws / SLIDE_PLANS_DIRNAME
        ok = (
            rc == 1
            and "rolled back" in msg
            and "slide_plans/ directory" in msg
            and not plans_dir.exists()
        )
        results.append(_expect(
            "mocked post-write re-validation failure rolls back every "
            "written slide_plan AND the slide_plans/ directory this run "
            "created — workspace returns to pre-call state",
            ok, f"rc={rc}, plans_dir_exists={plans_dir.exists()}",
        ))

    # 22a. mocked write_text failure mid-loop rolls back every file
    # already on disk INCLUDING the (potentially partial) file at the
    # failing path — proves write_text raising leaves nothing behind
    # because out_path is added to ``written`` BEFORE the write call.
    # The slide_plans/ directory the helper created is also removed.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_rb_midwrite"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)

        # Patch Path.write_text so it succeeds for slide 1 (creates
        # 01_cover.json) and then RAISES for slide 2 — simulating a
        # half-written 02_kpi_dashboard.json. The empty file at
        # 02_kpi_dashboard.json gets created by write_text's
        # open-truncate phase before the raise, mimicking disk-full.
        real_write_text = Path.write_text
        plans_dir = ws / SLIDE_PLANS_DIRNAME

        call_state = {"n": 0}

        def flaky_write_text(self, data, *args, **kwargs):
            # Only flake on writes into the slide_plans/ directory.
            try:
                is_in_plans = self.parent == plans_dir
            except (Exception, SystemExit):
                is_in_plans = False
            if is_in_plans:
                call_state["n"] += 1
                if call_state["n"] == 2:
                    # Simulate a partial file: open + truncate first,
                    # then raise. write_text() uses open(mode='w'),
                    # which truncates immediately on open.
                    self.write_bytes(b"")  # zero-byte partial
                    raise OSError("simulated disk-full mid-write")
            return real_write_text(self, data, *args, **kwargs)

        with unittest.mock.patch.object(
            Path, "write_text", flaky_write_text,
        ):
            rc, msg = init_slide_plans(
                workspace=ws, template_root=troot, specs_dir=specs,
            )
        ok = (
            rc == 2
            and "writing" in msg
            and "simulated disk-full mid-write" in msg
            and "rolled back" in msg
            and not plans_dir.exists()
        )
        results.append(_expect(
            "write_text raising mid-loop rolls back every file "
            "already on disk PLUS the partial file at the failing "
            "path AND the slide_plans/ directory this run created",
            ok, f"rc={rc}, plans_dir_exists={plans_dir.exists()}, msg={msg[:200]!r}",
        ))

    # 22b. mocked post-write re-validation failure WHEN slide_plans/
    # pre-existed empty preserves the directory (rollback only
    # removes what this run created). This is the symmetric case to
    # scenario 22: an empty pre-existing slide_plans/ is the
    # caller's, not the helper's, so rollback must NOT rmdir it.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_rb_pre_empty"
        troot = td / "tpl"
        specs = td / "specs"
        _seed_stage1234_workspace(ws)
        _seed_template_root(troot)
        _build_positive_specs(specs)
        plans_dir = ws / SLIDE_PLANS_DIRNAME
        plans_dir.mkdir()
        with unittest.mock.patch(
            f"{__name__}.validate_artifact",
            return_value=["forced test failure"],
        ):
            rc, msg = init_slide_plans(
                workspace=ws, template_root=troot, specs_dir=specs,
            )
        ok = (
            rc == 1
            and "rolled back" in msg
            # The directory message variant is absent because we did
            # NOT create the dir; only files were rolled back.
            and "slide_plans/ directory" not in msg
            and plans_dir.is_dir()
            and not list(plans_dir.iterdir())
        )
        results.append(_expect(
            "mocked post-write re-validation failure preserves an "
            "empty pre-existing slide_plans/ directory (rollback only "
            "removes what THIS run created)",
            ok, f"rc={rc}, dir_present={plans_dir.is_dir()}",
        ))

    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage-5 (Per-slide Plan) slide_plans/*.json helper. "
            "Bridges a stage-4-initialized workspace "
            "(source_manifest.json + input/source.md + deck_brief.json "
            "+ deck_plan.json + design_system.json) plus a caller-"
            "supplied --specs-dir of slide_plan JSON files into a "
            "complete <workspace>/slide_plans/ directory whose contents "
            "are validated against schemas/slide_plan.schema.json and "
            "cross-checked against deck_plan.slides[] (1:1 by index; "
            "layout/title match; required layout slots covered). Does "
            "NOT extract business content from the source body; does "
            "NOT infer slide content from raw text; does NOT generate "
            "image_manifest.json, render_models/, svg_previews/, or "
            "any .pptx. Stage 6 (image_manifest.json) remains agent-"
            "driven."
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Workspace directory (must already contain source_manifest.json "
             "+ input/source.md + deck_brief.json + deck_plan.json + "
             "design_system.json — e.g. seeded by scripts/init_workspace.py, "
             "scripts/init_deck_brief.py, scripts/init_deck_plan.py, and "
             "scripts/init_design_system.py).",
    )
    parser.add_argument(
        "--template-root", type=Path, default=None,
        help="Local directory containing template families. The template "
             "named by deck_plan.template must resolve to a real directory "
             "inside this root; there is NO product-level template default.",
    )
    parser.add_argument(
        "--specs-dir", type=Path, default=None,
        help="Local directory of caller-supplied slide_plan JSON files. The "
             "helper iterates *.json at the directory root, validates each "
             "against schemas/slide_plan.schema.json, and writes one "
             "canonical <workspace>/slide_plans/<idx:02d>_<layout>.json per "
             "deck_plan slide.",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios (happy path, determinism, "
             "missing / malformed deck_plan, missing / schema-invalid "
             "design_system, unknown template, missing required slot, "
             "orphan slide_plan, missing slide_plan, duplicate slide_plan "
             "index, symlink at --specs-dir / individual spec, pre-existing "
             "non-empty slide_plans/, no source-body extraction, URI-shaped "
             "--workspace, layout/title mismatch, schema-invalid spec, non-"
             "contiguous deck_plan indices, undeclared template layout, "
             "empty pre-existing slide_plans/ accepted, broken symlink at "
             "slide_plans/, symlink at <template>/layouts/, mocked post-"
             "write rollback (removes every written slide_plan AND the "
             "slide_plans/ directory this run created), mocked write_text "
             "failure mid-loop (rolls back files already on disk plus the "
             "partial file at the failing path), rollback preserves an "
             "empty pre-existing slide_plans/ directory). Exits non-zero "
             "if any scenario does not behave as expected. Mutually "
             "exclusive with --workspace / --template-root / --specs-dir.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if any(v is not None for v in (
            args.workspace, args.template_root, args.specs_dir,
        )):
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
            "happy-path slide_plans are written from the caller-supplied "
            "specs."
        )
        return 0

    missing = [
        name for name, value in (
            ("--workspace", args.workspace),
            ("--template-root", args.template_root),
            ("--specs-dir", args.specs_dir),
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

    rc, msg = init_slide_plans(
        workspace=args.workspace,
        template_root=args.template_root,
        specs_dir=args.specs_dir,
    )
    if rc == 0:
        print(msg)
    else:
        print(msg, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
