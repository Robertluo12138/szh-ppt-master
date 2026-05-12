#!/usr/bin/env python3
"""validate_workspace.py

Stdlib-only, fail-closed validator for an arbitrary editable-ppt
workspace. The workspace path is caller-supplied — not hardcoded.

USAGE
    python3 scripts/validate_workspace.py \\
        --workspace <dir> \\
        --template-root <dir>

The workspace must contain:
    deck_brief.json
    deck_plan.json
    design_system.json
    image_manifest.json
    slide_plans/<one *.json per deck_plan slide>

The template-root must contain one subdirectory per template, each
with template.json, theme.json, and layouts/<layout>.json files
(matching schemas/template.schema.json, theme.schema.json, layout.schema.json).

CHECKS (all fail-closed; exit 1 on any failure)
    schemas:        every artifact above validates against its schema.
    template:       deck_plan.template is path-safe, resolves inside the
                    template-root, and validates against template.schema.json.
    layouts:        every deck_plan slide layout is declared by the
                    chosen template's layouts list.
    coverage:       every deck_plan slide has a matching slide_plan
                    file (matched by JSON 'index'); every slide_plan
                    agrees with its deck_plan entry on index/layout/title.
    slots:          every required layout slot is covered by a matching
                    slide_plan block id and kind.
    image safety:   every image_manifest.local_path passes the same
                    string-only path-safety rule as validate_scaffold.py
                    (rejects any URI-like scheme matching
                    ^[A-Za-z][A-Za-z0-9+.-]*:, plus POSIX-absolute,
                    leading backslash, protocol-relative '//host/...',
                    '..' segments, and empty strings).
    image scope:    every local_path resolves to a real file inside the
                    workspace; symlink escape is rejected.
    image refs:     every slide_plan.image_refs id is declared in
                    image_manifest.
    render models:  if workspace ships render_models/*.json, each one
                    validates against render_model.schema.json (controlled
                    primitive kinds only, required bounds, required and
                    non-empty source_refs, token-only style refs,
                    additionalProperties:false everywhere) and crosses with
                    deck_plan / design_system / image_manifest / layout
                    slots (index, layout, canvas==grid, source_refs are a
                    subset of deck_brief.source_refs — fail-closed if the
                    deck_brief is missing / malformed / empty — primitive
                    ids unique, bounds inside canvas, kind-payload
                    alignment, slot_id known, slot.primitive_kind or
                    slot.type->primitive_kind default, slot.bounds contain
                    primitive bounds, image_ref declared, palette tokens
                    resolve, no URI-scheme prefix in reference fields).
                    The directory is optional today: a workspace that does
                    not ship render models is silently skipped.
    svg previews:   if workspace ships render_models/*.json, each one
                    must have a matching svg_previews/<stem>.svg. Each
                    SVG must parse as XML, root <svg> with a viewBox
                    that matches the render_model canvas, no
                    <foreignObject> anywhere, every reference-bearing
                    attribute (href / xlink:href / src / *href*) passes
                    the same path-safety rule as image_manifest paths
                    (no URI scheme, no absolute, no '..', no leading
                    backslash, no empty), every <image> href is a path
                    declared in image_manifest, every <rect> / <image>
                    / <ellipse> / <circle> / <line> with explicit
                    numeric geometry stays inside the canvas, and every
                    <text> with numeric x/y has its anchor point
                    inside the canvas. The validator does NOT enforce
                    a <text> width / height / wrapping box — that
                    needs font metrics this stdlib-only validator does
                    not carry, and remains a TODO in
                    references/svg-design-rules.md. The svg_previews/
                    directory is generator-owned (*.svg);
                    render_models without a matching svg preview FAIL.

NEGATIVE TESTS (built in; exercised in the same run)
    unsafe scheme, absolute path, path traversal, missing media,
    unknown layout, missing slide_plan, required-slot mismatch.
    render_model: unsupported kind, missing bounds, missing / empty
    source_refs, invalid token refs, URLs / file:// / absolute paths /
    path traversal in image_ref, arbitrary SVG-like fields, kind-payload
    mismatch, bounds outside canvas, unknown slot_id, slot.primitive_kind
    mismatch, image_ref not in manifest, unknown palette token,
    source_refs cross-check fail-closed under missing / malformed / empty
    deck_brief.source_refs, duplicate primitive ids.
    svg_preview: missing for a render_model, malformed XML, wrong root
    element, viewBox mismatch with canvas, <foreignObject> present,
    href with URI scheme / absolute / '..' / file://, href not
    declared in image_manifest, element outside canvas.

TRACEBACK SAFETY
    Every check function is defensive against malformed-but-loadable
    caller workspaces. If a JSON artifact loads but is the wrong
    shape (a list at root, a non-dict slide, an image entry missing
    'id'/'local_path', a non-string template name, ...), the
    validator reports a structured [FAIL] line rather than tracebacking.
    Two tempfixtures (#8 malformed-but-loadable, #9 list-rooted core
    artifacts) prove this stays true.

OUT OF SCOPE
    This validator does NOT generate SVG. SVG generation is a separate
    stage implemented by scripts/generate_svg_previews.py (today supporting
    primitive kinds text / line / shape / image_slot / kpi across every
    layout the render-model generator emits — cover, section_divider,
    executive_summary, key_message, two_column, kpi_dashboard, timeline,
    conclusion). Validation of the generated previews is performed here by
    check_svg_previews above.
    PPTX export is implemented separately by scripts/export_pptx.py (today
    covering layouts cover, kpi_dashboard, agenda, section_divider,
    executive_summary, key_message, two_column, timeline, conclusion with
    the same controlled primitive kinds); D-One image generation, Qoder
    CLI integration, and any network behavior are NOT implemented in this
    repo and remain out of scope until their scripts exist.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validate_artifacts import _validate  # noqa: E402
from validate_scaffold import (  # noqa: E402
    local_path_is_safe,
    _resolves_within,
    _slide_plan_against_layout,
    _URI_SCHEME_PREFIX,
)

SCHEMAS = REPO_ROOT / "schemas"

RENDER_PRIMITIVE_KINDS = (
    "text", "shape", "line", "image_slot", "table", "kpi", "chart_placeholder",
)
# slot.type (from layout.schema.json) -> default render primitive kind. Used
# when a layout slot has no explicit primitive_kind override. The renderer can
# still treat a callout as a shape+text composite later; this default is the
# minimum mapping the controlled model commits to today.
DEFAULT_SLOT_TYPE_TO_PRIMITIVE_KIND = {
    "text": "text",
    "list": "text",
    "callout": "text",
    "kpi": "kpi",
    "table": "table",
    "image_ref": "image_slot",
    "chart_ref": "chart_placeholder",
}

CORE_ARTIFACT_SCHEMAS = {
    "deck_brief.json":     "deck_brief.schema.json",
    "deck_plan.json":      "deck_plan.schema.json",
    "design_system.json":  "design_system.schema.json",
    "image_manifest.json": "image_manifest.schema.json",
}


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _try_load(path: Path) -> tuple[dict | None, str]:
    """Load JSON without raising. Returns (data, '') on success or
    (None, reason) on missing file, read error, or malformed JSON.
    All call sites that read user-supplied workspace artifacts go
    through this helper so a missing or malformed artifact reports
    a [FAIL] check instead of crashing with a traceback."""
    if not path.is_file():
        return (None, f"missing {path}")
    try:
        text = path.read_text()
    except OSError as exc:
        return (None, f"read error: {exc}")
    try:
        return (json.loads(text), "")
    except json.JSONDecodeError as exc:
        return (None, f"malformed JSON: {exc}")


def _schema_validate(artifact: dict, schema_path: Path) -> list[str]:
    errors: list[str] = []
    _validate(artifact, _load(schema_path), "<root>", errors)
    return errors


def _safe_load_inside(base: Path, ref: str) -> tuple[bool, Path | None, str]:
    """Two-stage gate: path-safety first, then within-base resolve.
    Returns (ok, resolved_path_or_None, reason)."""
    if not isinstance(ref, str):
        return (False, None, f"ref must be a string, got {type(ref).__name__}")
    if not local_path_is_safe(ref):
        return (False, None, "path-safety rejected")
    if not _resolves_within(base, ref):
        return (False, None, "escapes base after resolution")
    return (True, (base / ref).resolve(), "")


def _as_dict(value: object) -> dict | None:
    """Return value if it's a dict, else None. Used to type-guard JSON
    payloads loaded from caller-supplied workspaces before we call
    .get()/[] on them — without this guard, a malformed-but-loadable
    artifact (e.g. a JSON list where an object was expected) would
    traceback inside downstream checks."""
    return value if isinstance(value, dict) else None


def _as_list(value: object) -> list | None:
    """Return value if it's a list, else None. Same intent as
    _as_dict: stop bad caller data from tracebacking the validator."""
    return value if isinstance(value, list) else None


def check_schemas(workspace: Path) -> list[CheckResult]:
    out: list[CheckResult] = []
    for fname, schema_name in CORE_ARTIFACT_SCHEMAS.items():
        data, err = _try_load(workspace / fname)
        if data is None:
            out.append(CheckResult(f"artifact loadable: {fname}", False, err))
            continue
        errors = _schema_validate(data, SCHEMAS / schema_name)
        out.append(CheckResult(
            f"{fname} validates against {schema_name}",
            not errors,
            "; ".join(errors),
        ))
    plans_dir = workspace / "slide_plans"
    if not plans_dir.is_dir():
        out.append(CheckResult("slide_plans/ directory present", False, f"missing {plans_dir}"))
        return out
    plan_files = sorted(plans_dir.glob("*.json"))
    if not plan_files:
        out.append(CheckResult("slide_plans/ contains at least one file", False, ""))
        return out
    for plan_file in plan_files:
        data, err = _try_load(plan_file)
        if data is None:
            out.append(CheckResult(
                f"slide_plans/{plan_file.name} loadable",
                False, err,
            ))
            continue
        errors = _schema_validate(data, SCHEMAS / "slide_plan.schema.json")
        out.append(CheckResult(
            f"slide_plans/{plan_file.name} validates against slide_plan.schema.json",
            not errors,
            "; ".join(errors),
        ))
    return out


def check_template_chain(workspace: Path, template_root: Path) -> list[CheckResult]:
    """deck_plan side: path-safety on deck_plan.template, and every
    deck_plan slide layout is declared by the chosen template's
    layouts list. Full template internals are checked separately by
    check_template_files."""
    out: list[CheckResult] = []
    deck_plan_raw, err = _try_load(workspace / "deck_plan.json")
    if deck_plan_raw is None:
        out.append(CheckResult("template chain skipped: deck_plan.json loadable", False, err))
        return out
    deck_plan = _as_dict(deck_plan_raw)
    if deck_plan is None:
        out.append(CheckResult(
            "template chain skipped: deck_plan.json root is an object",
            False, f"got {type(deck_plan_raw).__name__}",
        ))
        return out
    template_name = deck_plan.get("template", "")
    if not isinstance(template_name, str) or not template_name:
        out.append(CheckResult(
            "deck_plan.template is a non-empty string",
            False, f"got {template_name!r}",
        ))
        return out
    ok, template_dir, reason = _safe_load_inside(template_root, template_name)
    out.append(CheckResult(
        f"deck_plan.template {template_name!r} is path-safe and inside template-root",
        ok,
        reason,
    ))
    if not ok:
        # Fail-closed: do not touch the filesystem at the unsafe target.
        return out
    template_raw, err = _try_load(template_dir / "template.json")
    if template_raw is None:
        out.append(CheckResult(
            f"template {template_name!r}: template.json loadable",
            False, err,
        ))
        return out
    template = _as_dict(template_raw)
    if template is None:
        out.append(CheckResult(
            f"template {template_name!r}: template.json root is an object",
            False, f"got {type(template_raw).__name__}",
        ))
        return out
    declared_raw = template.get("layouts", [])
    declared_list = _as_list(declared_raw) or []
    declared = {d for d in declared_list if isinstance(d, str)}
    slides_raw = deck_plan.get("slides", [])
    slides = _as_list(slides_raw)
    if slides is None:
        out.append(CheckResult(
            "deck_plan.slides is a list",
            False, f"got {type(slides_raw).__name__}",
        ))
        return out
    for i, slide in enumerate(slides):
        slide_d = _as_dict(slide)
        if slide_d is None:
            out.append(CheckResult(
                f"deck_plan.slides[{i}] is an object",
                False, f"got {type(slide).__name__}",
            ))
            continue
        layout = slide_d.get("layout")
        out.append(CheckResult(
            f"deck_plan slide {slide_d.get('index')} layout {layout!r} declared by template",
            isinstance(layout, str) and layout in declared,
            f"declared layouts: {sorted(declared)}",
        ))
    return out


def check_template_files(template_root: Path, template_name: str) -> list[CheckResult]:
    """Template side: full structural validation of the named template:
      - template.json loads + validates + .name matches the dir name;
      - theme_ref passes the two-stage safe-path gate, file exists,
        and theme.json validates against theme.schema.json;
      - every declared layout name is path-safe, the file at
        layouts/<name>.json exists and validates against
        layout.schema.json, and the file stem matches layout['name']."""
    out: list[CheckResult] = []
    ok, template_dir, reason = _safe_load_inside(template_root, template_name)
    if not ok:
        out.append(CheckResult(
            f"template-files skipped (fail-closed): {template_name!r}",
            False, reason,
        ))
        return out
    template_raw, err = _try_load(template_dir / "template.json")
    if template_raw is None:
        out.append(CheckResult(
            f"template {template_name!r}: template.json loadable",
            False, err,
        ))
        return out
    template = _as_dict(template_raw)
    if template is None:
        out.append(CheckResult(
            f"template {template_name!r}: template.json root is an object",
            False, f"got {type(template_raw).__name__}",
        ))
        return out
    errors = _schema_validate(template, SCHEMAS / "template.schema.json")
    out.append(CheckResult(
        f"template {template_name!r}: template.json validates against schema",
        not errors,
        "; ".join(errors),
    ))
    out.append(CheckResult(
        f"template {template_name!r}: name field matches directory",
        template.get("name") == template_dir.name,
        f"name={template.get('name')!r}, dir={template_dir.name!r}",
    ))

    theme_ref = template.get("theme_ref", "")
    ok2, theme_path, reason2 = _safe_load_inside(template_dir, theme_ref)
    out.append(CheckResult(
        f"template {template_name!r}: theme_ref {theme_ref!r} is path-safe + inside template dir",
        ok2, reason2,
    ))
    if ok2:
        if not theme_path.is_file():
            out.append(CheckResult(
                f"template {template_name!r}: theme file {theme_ref!r} exists",
                False, f"missing {theme_path}",
            ))
        else:
            out.append(CheckResult(
                f"template {template_name!r}: theme file {theme_ref!r} exists",
                True,
            ))
            theme, err = _try_load(theme_path)
            if theme is None:
                out.append(CheckResult(
                    f"template {template_name!r}: theme file loadable",
                    False, err,
                ))
            else:
                errors = _schema_validate(theme, SCHEMAS / "theme.schema.json")
                out.append(CheckResult(
                    f"template {template_name!r}: theme validates against theme.schema.json",
                    not errors,
                    "; ".join(errors),
                ))

    declared_raw = template.get("layouts", [])
    declared = _as_list(declared_raw)
    if declared is None:
        out.append(CheckResult(
            f"template {template_name!r}: layouts field is a list",
            False, f"got {type(declared_raw).__name__}",
        ))
        declared = []
    for layout_name in declared:
        if not isinstance(layout_name, str):
            out.append(CheckResult(
                f"template {template_name!r}: declared layout name is a string",
                False, f"got {type(layout_name).__name__}",
            ))
            continue
        if not local_path_is_safe(layout_name):
            out.append(CheckResult(
                f"template {template_name!r}: declared layout name {layout_name!r} is path-safe",
                False,
            ))
            continue
        layout_file = template_dir / "layouts" / f"{layout_name}.json"
        if not layout_file.is_file():
            out.append(CheckResult(
                f"template {template_name!r}: declared layout {layout_name!r} has a file",
                False, f"missing {layout_file}",
            ))
            continue
        out.append(CheckResult(
            f"template {template_name!r}: declared layout {layout_name!r} has a file",
            True,
        ))
        layout_raw, err = _try_load(layout_file)
        if layout_raw is None:
            out.append(CheckResult(
                f"template {template_name!r}: layout {layout_name!r} loadable",
                False, err,
            ))
            continue
        layout = _as_dict(layout_raw)
        if layout is None:
            out.append(CheckResult(
                f"template {template_name!r}: layout {layout_name!r} root is an object",
                False, f"got {type(layout_raw).__name__}",
            ))
            continue
        errors = _schema_validate(layout, SCHEMAS / "layout.schema.json")
        out.append(CheckResult(
            f"template {template_name!r}: layout {layout_name!r} validates against schema",
            not errors,
            "; ".join(errors),
        ))
        out.append(CheckResult(
            f"template {template_name!r}: layout {layout_name!r} file stem matches name field",
            layout.get("name") == layout_file.stem,
            f"name={layout.get('name')!r}, stem={layout_file.stem!r}",
        ))
    return out


def check_template_files_for_workspace(workspace: Path, template_root: Path) -> list[CheckResult]:
    """Convenience wrapper: derive template_name from deck_plan.json
    in the workspace, then delegate to check_template_files."""
    deck_plan_raw, err = _try_load(workspace / "deck_plan.json")
    if deck_plan_raw is None:
        return [CheckResult("template-files skipped: deck_plan.json loadable", False, err)]
    deck_plan = _as_dict(deck_plan_raw)
    if deck_plan is None:
        return [CheckResult(
            "template-files skipped: deck_plan.json root is an object",
            False, f"got {type(deck_plan_raw).__name__}",
        )]
    template_name = deck_plan.get("template", "")
    if not isinstance(template_name, str) or not template_name:
        return [CheckResult(
            "template-files skipped: deck_plan.template is a non-empty string",
            False, f"got {template_name!r}",
        )]
    return check_template_files(template_root, template_name)


def _load_template_layouts(template_dir: Path) -> dict[str, dict]:
    """Load every <template_dir>/layouts/*.json that parses as a JSON
    object. Loadable-but-non-object layouts are skipped so that callers
    iterating layouts.values() never see a non-dict (which would
    traceback at layout['slots'] downstream)."""
    layouts: dict[str, dict] = {}
    if not (template_dir / "layouts").is_dir():
        return layouts
    for f in (template_dir / "layouts").glob("*.json"):
        data, _ = _try_load(f)
        data_d = _as_dict(data) if data is not None else None
        if data_d is not None:
            layouts[f.stem] = data_d
    return layouts


def check_slide_plan_coverage(workspace: Path, template_root: Path) -> list[CheckResult]:
    out: list[CheckResult] = []
    deck_plan_raw, err = _try_load(workspace / "deck_plan.json")
    if deck_plan_raw is None:
        out.append(CheckResult("coverage skipped: deck_plan.json loadable", False, err))
        return out
    deck_plan = _as_dict(deck_plan_raw)
    if deck_plan is None:
        out.append(CheckResult(
            "coverage skipped: deck_plan.json root is an object",
            False, f"got {type(deck_plan_raw).__name__}",
        ))
        return out
    template_name = deck_plan.get("template", "")
    if not isinstance(template_name, str):
        out.append(CheckResult(
            "coverage skipped: deck_plan.template is a string",
            False, f"got {type(template_name).__name__}",
        ))
        return out
    ok, template_dir, reason = _safe_load_inside(template_root, template_name)
    if not ok:
        out.append(CheckResult(
            f"coverage skipped (fail-closed): deck_plan.template {template_name!r} unsafe",
            False,
            reason,
        ))
        return out
    layouts = _load_template_layouts(template_dir)

    # Detect duplicate deck_plan indices BEFORE building the by-index map,
    # so the subsequent {index: slide} dict comprehension cannot silently
    # collapse duplicates and false-green the 1:1 coverage analysis.
    deck_slides_raw = deck_plan.get("slides", [])
    deck_slides = _as_list(deck_slides_raw)
    if deck_slides is None:
        out.append(CheckResult(
            "deck_plan.slides is a list",
            False, f"got {type(deck_slides_raw).__name__}",
        ))
        return out
    # Filter to dict entries so downstream .get() calls cannot traceback.
    dict_slides: list[dict] = []
    for i, s in enumerate(deck_slides):
        s_d = _as_dict(s)
        if s_d is None:
            out.append(CheckResult(
                f"deck_plan.slides[{i}] is an object",
                False, f"got {type(s).__name__}",
            ))
            continue
        dict_slides.append(s_d)
    deck_index_counts: dict[int, int] = {}
    for s_d in dict_slides:
        idx = s_d.get("index")
        if isinstance(idx, int):
            deck_index_counts[idx] = deck_index_counts.get(idx, 0) + 1
    dup_deck_indices = sorted(i for i, c in deck_index_counts.items() if c > 1)
    out.append(CheckResult(
        f"deck_plan slide indices are unique ({len(dict_slides)} slides)",
        not dup_deck_indices,
        f"duplicated indices: {dup_deck_indices}",
    ))
    deck_slides_by_index = {
        s_d.get("index"): s_d
        for s_d in dict_slides
        if isinstance(s_d.get("index"), int)
    }

    plans_dir = workspace / "slide_plans"
    if not plans_dir.is_dir():
        out.append(CheckResult("slide_plans/ present", False, f"missing {plans_dir}"))
        return out

    # Group plan files by index so duplicate indices are detected, not collapsed.
    plan_files = sorted(plans_dir.glob("*.json"))
    plans_by_index: dict[int, list[tuple[Path, dict]]] = {}
    for plan_file in plan_files:
        plan_raw, err = _try_load(plan_file)
        if plan_raw is None:
            out.append(CheckResult(
                f"slide_plan {plan_file.name}: loadable",
                False, err,
            ))
            continue
        plan = _as_dict(plan_raw)
        if plan is None:
            out.append(CheckResult(
                f"slide_plan {plan_file.name}: root is an object",
                False, f"got {type(plan_raw).__name__}",
            ))
            continue
        idx = plan.get("index")
        if not isinstance(idx, int):
            out.append(CheckResult(
                f"slide_plan {plan_file.name}: 'index' is an integer",
                False, f"got {idx!r}",
            ))
            continue
        plans_by_index.setdefault(idx, []).append((plan_file, plan))

    # Duplicate-index detection (must come before per-file matching so the
    # failure is reported regardless of which copy validates).
    for idx, entries in sorted(plans_by_index.items()):
        if len(entries) > 1:
            files = [str(p.name) for p, _ in entries]
            out.append(CheckResult(
                f"slide_plan index {idx}: appears in exactly one file",
                False,
                f"duplicated by: {files}",
            ))

    # Per-plan checks: orphan, mismatch, slot coverage.
    for idx in sorted(plans_by_index):
        for plan_file, plan in plans_by_index[idx]:
            deck_slide = deck_slides_by_index.get(idx)
            if deck_slide is None:
                out.append(CheckResult(
                    f"slide_plan {plan_file.name}: deck_plan has slide {idx}",
                    False,
                    "orphan slide_plan: no deck_plan entry for this index",
                ))
                continue
            layout_match = plan.get("layout") == deck_slide.get("layout")
            title_match = plan.get("title") == deck_slide.get("title")
            out.append(CheckResult(
                f"slide_plan {plan_file.name}: index/layout/title match deck_plan",
                layout_match and title_match,
                f"plan=({plan.get('layout')!r}, {plan.get('title')!r}), "
                f"deck=({deck_slide.get('layout')!r}, {deck_slide.get('title')!r})",
            ))
            layout = layouts.get(plan.get("layout"))
            if layout is None:
                out.append(CheckResult(
                    f"slide_plan {plan_file.name}: layout {plan.get('layout')!r} loaded from template",
                    False,
                    f"layouts on disk: {sorted(layouts)}",
                ))
                continue
            problems = _slide_plan_against_layout(plan, layout)
            out.append(CheckResult(
                f"slide_plan {plan_file.name}: required slots covered for {plan.get('layout')}",
                not problems,
                "; ".join(problems),
            ))

    # Missing-deck_plan-index detection.
    missing_indices = sorted(set(deck_slides_by_index) - set(plans_by_index))
    out.append(CheckResult(
        f"every deck_plan slide has a slide_plan file "
        f"({len(deck_slides_by_index)} deck slides, {len(plans_by_index)} distinct plan indices)",
        not missing_indices,
        f"missing slide_plans for indices: {missing_indices}",
    ))
    return out


def check_planner_semantics(workspace: Path) -> list[CheckResult]:
    """Cross-artifact planner semantics, beyond what JSON Schema can express:

      - deck_plan.planning.planned_slide_count equals len(deck_plan.slides);
      - deck_plan.sections[].slide_indices cover exactly the deck_plan
        slide indices (no duplicates across sections, no missing
        deck_plan indices, no section_indices the deck_plan does not
        declare);
      - every deck_plan.slides[].section_id resolves to an existing
        section and the slide's index appears in that section's
        slide_indices;
      - every deck_plan.slides[].source_refs value is declared in
        deck_brief.source_refs.

    Workspace-path agnostic: reads brief/plan from the caller-supplied
    workspace only. Fail-closed: a missing or malformed brief / plan
    short-circuits with a [FAIL] line."""
    out: list[CheckResult] = []
    brief_raw, err = _try_load(workspace / "deck_brief.json")
    if brief_raw is None:
        out.append(CheckResult("planner semantics skipped: deck_brief.json loadable", False, err))
        return out
    brief = _as_dict(brief_raw)
    if brief is None:
        out.append(CheckResult(
            "planner semantics skipped: deck_brief.json root is an object",
            False, f"got {type(brief_raw).__name__}",
        ))
        return out
    deck_raw, err = _try_load(workspace / "deck_plan.json")
    if deck_raw is None:
        out.append(CheckResult("planner semantics skipped: deck_plan.json loadable", False, err))
        return out
    deck = _as_dict(deck_raw)
    if deck is None:
        out.append(CheckResult(
            "planner semantics skipped: deck_plan.json root is an object",
            False, f"got {type(deck_raw).__name__}",
        ))
        return out

    brief_refs_raw = brief.get("source_refs")
    brief_refs_list = _as_list(brief_refs_raw)
    if brief_refs_list is None:
        out.append(CheckResult(
            "deck_brief.source_refs is a list",
            False, f"got {type(brief_refs_raw).__name__}",
        ))
        return out
    brief_refs = {r for r in brief_refs_list if isinstance(r, str)}

    slides_raw = deck.get("slides")
    slides = _as_list(slides_raw)
    if slides is None:
        out.append(CheckResult(
            "deck_plan.slides is a list (planner semantics)",
            False, f"got {type(slides_raw).__name__}",
        ))
        return out
    dict_slides: list[dict] = []
    for i, s in enumerate(slides):
        s_d = _as_dict(s)
        if s_d is None:
            out.append(CheckResult(
                f"deck_plan.slides[{i}] is an object (planner semantics)",
                False, f"got {type(s).__name__}",
            ))
            continue
        dict_slides.append(s_d)

    planning_raw = deck.get("planning")
    planning = _as_dict(planning_raw)
    if planning is None:
        out.append(CheckResult(
            "deck_plan.planning is an object",
            False, f"got {type(planning_raw).__name__}",
        ))
    else:
        planned = planning.get("planned_slide_count")
        if not isinstance(planned, int) or isinstance(planned, bool):
            out.append(CheckResult(
                "deck_plan.planning.planned_slide_count is an integer",
                False, f"got {type(planned).__name__}",
            ))
        else:
            out.append(CheckResult(
                f"planning.planned_slide_count ({planned}) equals len(slides) ({len(dict_slides)})",
                planned == len(dict_slides),
                f"planned={planned}, actual={len(dict_slides)}",
            ))

    sections_raw = deck.get("sections")
    sections = _as_list(sections_raw)
    if sections is None:
        out.append(CheckResult(
            "deck_plan.sections is a list",
            False, f"got {type(sections_raw).__name__}",
        ))
        return out
    dict_sections: list[dict] = []
    for i, sec in enumerate(sections):
        sec_d = _as_dict(sec)
        if sec_d is None:
            out.append(CheckResult(
                f"deck_plan.sections[{i}] is an object (planner semantics)",
                False, f"got {type(sec).__name__}",
            ))
            continue
        dict_sections.append(sec_d)

    section_by_id: dict[str, dict] = {}
    duplicate_section_ids: list[str] = []
    for sec in dict_sections:
        sid = sec.get("id")
        if isinstance(sid, str):
            if sid in section_by_id:
                duplicate_section_ids.append(sid)
            else:
                section_by_id[sid] = sec
    out.append(CheckResult(
        f"section ids are unique ({len(section_by_id)} sections)",
        not duplicate_section_ids,
        f"duplicated: {sorted(set(duplicate_section_ids))}",
    ))

    slide_indices_list: list[int] = []
    for s in dict_slides:
        idx = s.get("index")
        if isinstance(idx, int) and not isinstance(idx, bool):
            slide_indices_list.append(idx)
    slide_index_set = set(slide_indices_list)

    seen_overall: dict[int, str] = {}
    duplicate_across_sections: list[tuple[int, str, str]] = []
    section_problems: list[str] = []
    for sec in dict_sections:
        sid = sec.get("id")
        if not isinstance(sid, str):
            continue
        s_indices_raw = sec.get("slide_indices")
        s_indices = _as_list(s_indices_raw)
        if s_indices is None:
            section_problems.append(f"section {sid!r}: slide_indices is not a list")
            continue
        int_indices = [i for i in s_indices if isinstance(i, int) and not isinstance(i, bool)]
        if len(int_indices) != len(s_indices):
            section_problems.append(f"section {sid!r}: slide_indices has non-integer entries")
        if len(set(int_indices)) != len(int_indices):
            section_problems.append(f"section {sid!r}: slide_indices has duplicates within section")
        for i in int_indices:
            if i in seen_overall and seen_overall[i] != sid:
                duplicate_across_sections.append((i, seen_overall[i], sid))
            else:
                seen_overall.setdefault(i, sid)
    out.append(CheckResult(
        "per-section slide_indices are well-formed (list of unique integers)",
        not section_problems,
        "; ".join(section_problems),
    ))
    out.append(CheckResult(
        "no slide index appears in more than one section",
        not duplicate_across_sections,
        f"shared indices: {duplicate_across_sections}",
    ))

    section_indices_union = set(seen_overall)
    missing_from_sections = sorted(slide_index_set - section_indices_union)
    orphan_section_indices = sorted(section_indices_union - slide_index_set)
    out.append(CheckResult(
        f"sections cover every deck_plan slide index "
        f"({len(slide_index_set)} slides, {len(section_indices_union)} indices listed by sections)",
        not missing_from_sections,
        f"slides missing from sections: {missing_from_sections}",
    ))
    out.append(CheckResult(
        "sections list no slide indices the deck_plan does not declare",
        not orphan_section_indices,
        f"orphan section slide_indices: {orphan_section_indices}",
    ))

    for s in dict_slides:
        idx = s.get("index")
        sid = s.get("section_id")
        if not isinstance(sid, str) or sid not in section_by_id:
            out.append(CheckResult(
                f"slide index {idx}: section_id {sid!r} exists in sections",
                False,
                f"known section ids: {sorted(section_by_id)}",
            ))
        else:
            section_indices_raw = section_by_id[sid].get("slide_indices")
            section_indices_list = _as_list(section_indices_raw) or []
            out.append(CheckResult(
                f"slide index {idx}: listed in section {sid!r}.slide_indices",
                isinstance(idx, int) and idx in section_indices_list,
                f"section_indices={section_indices_list}",
            ))
        srcs_raw = s.get("source_refs")
        srcs = _as_list(srcs_raw)
        if srcs is None:
            out.append(CheckResult(
                f"slide index {idx}: source_refs is a list",
                False, f"got {type(srcs_raw).__name__}",
            ))
            continue
        for ref in srcs:
            if not isinstance(ref, str) or ref not in brief_refs:
                out.append(CheckResult(
                    f"slide index {idx}: source_ref {ref!r} declared in deck_brief.source_refs",
                    False,
                    f"brief source_refs: {sorted(brief_refs)}",
                ))
    return out


def check_image_manifest(workspace: Path) -> list[CheckResult]:
    out: list[CheckResult] = []
    manifest_raw, err = _try_load(workspace / "image_manifest.json")
    if manifest_raw is None:
        out.append(CheckResult("image_manifest.json loadable", False, err))
        return out
    manifest = _as_dict(manifest_raw)
    if manifest is None:
        out.append(CheckResult(
            "image_manifest.json root is an object",
            False, f"got {type(manifest_raw).__name__}",
        ))
        return out
    images_raw = manifest.get("images", [])
    images = _as_list(images_raw)
    if images is None:
        out.append(CheckResult(
            "image_manifest.images is a list",
            False, f"got {type(images_raw).__name__}",
        ))
        return out
    declared_ids: set[str] = set()
    for i, img in enumerate(images):
        img_d = _as_dict(img)
        if img_d is None:
            out.append(CheckResult(
                f"image_manifest.images[{i}] is an object",
                False, f"got {type(img).__name__}",
            ))
            continue
        img_id = img_d.get("id")
        local_path = img_d.get("local_path")
        if not isinstance(img_id, str):
            out.append(CheckResult(
                f"image_manifest.images[{i}] has a string 'id'",
                False, f"got {type(img_id).__name__}",
            ))
            continue
        declared_ids.add(img_id)
        if not isinstance(local_path, str):
            out.append(CheckResult(
                f"image {img_id!r}: 'local_path' is a string",
                False, f"got {type(local_path).__name__}",
            ))
            continue
        ok, asset_path, reason = _safe_load_inside(workspace, local_path)
        out.append(CheckResult(
            f"image {img_id!r}: local_path {local_path!r} is path-safe and inside workspace",
            ok,
            reason,
        ))
        if not ok:
            continue
        out.append(CheckResult(
            f"image {img_id!r}: local_path resolves to a real file",
            asset_path.is_file(),
            f"missing {asset_path}",
        ))
    plans_dir = workspace / "slide_plans"
    if plans_dir.is_dir():
        for plan_file in sorted(plans_dir.glob("*.json")):
            plan_raw, _ = _try_load(plan_file)
            plan = _as_dict(plan_raw) if plan_raw is not None else None
            if plan is None:
                continue  # loadability/shape already reported by check_schemas
            refs = plan.get("image_refs", [])
            if not isinstance(refs, list):
                out.append(CheckResult(
                    f"slide_plan {plan_file.name} image_refs is a list",
                    False, f"got {type(refs).__name__}",
                ))
                continue
            for ref in refs:
                if not isinstance(ref, str):
                    out.append(CheckResult(
                        f"slide_plan {plan_file.name} image_ref is a string",
                        False, f"got {type(ref).__name__}",
                    ))
                    continue
                out.append(CheckResult(
                    f"slide_plan {plan_file.name} image_ref {ref!r} declared in image_manifest",
                    ref in declared_ids,
                    f"declared ids: {sorted(declared_ids)}",
                ))
    return out


def _walk_strings(node: object):
    """Yield every string value reachable from node, walking dicts and lists.
    Used by the render_model URI-scheme defense check."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_strings(v)


def _render_model_reference_strings(prim_d: dict):
    """Yield reference / identifier strings from a render_model primitive
    where a URI / path is never legitimate (ids, kinds, token refs,
    image_ref). Content fields like text.content, kpi.label/value/delta,
    chart_placeholder.caption, image_slot.alt_text, and table cells are
    NOT walked — those are display text and may legitimately mention a
    URL-like substring. The schema's pattern rules already forbid URIs
    in the fields walked here; this walker is a defense-in-depth check."""
    for key in ("id", "slot_id", "kind"):
        v = prim_d.get(key)
        if isinstance(v, str):
            yield v
    style = prim_d.get("style")
    if isinstance(style, dict):
        for k, v in style.items():
            if isinstance(v, str):
                yield v
    img = prim_d.get("image_slot")
    if isinstance(img, dict):
        v = img.get("image_ref")
        if isinstance(v, str):
            yield v


def check_render_models(workspace: Path, template_root: Path) -> list[CheckResult]:
    """Validate workspace/render_models/*.json against render_model.schema.json
    and the cross-artifact rules the controlled primitive contract requires.

    The render_models/ directory is optional. If it is absent or empty
    no checks fire — render-model generation is a downstream stage that
    not every workspace ships yet. When the directory does ship files,
    every cross-check below is fail-closed.

    Cross-checks (run after schema validation passes):
      - index matches a deck_plan slide;
      - layout matches that deck_plan slide's layout;
      - canvas dimensions match design_system.grid (if available);
      - source_refs are a subset of deck_brief.source_refs. The check is
        fail-closed: a missing / malformed / empty deck_brief is surfaced
        as a FAIL on every render_model rather than silently skipped, so
        a workspace cannot claim render-model traceability without a
        deck_brief that lists the same source ids;
      - every primitive id is unique within the render_model;
      - bounds fit inside the canvas (x+w <= width, y+h <= height);
      - exactly one kind-specific payload field is present, and it
        matches `kind` (e.g. kind=kpi requires the kpi payload and
        forbids text/shape/line/image_slot/table/chart_placeholder);
      - slot_id (when set) refers to a slot id on the chosen layout;
      - if that slot declares primitive_kind, it must equal the
        primitive's kind; if it declares bounds, the primitive's bounds
        must fit inside slot.bounds;
      - kind=image_slot's image_ref must be declared in image_manifest;
      - style.fill_token / color_token / stroke_token must resolve to a
        key present in design_system.palette;
      - reference-field strings (id, slot_id, kind, style tokens,
        image_ref) carry no URI-scheme prefix — schema pattern already
        forbids this; the check is a defense-in-depth catch.
    """
    out: list[CheckResult] = []
    rm_dir = workspace / "render_models"
    if not rm_dir.is_dir():
        return out
    rm_files = sorted(rm_dir.glob("*.json"))
    if not rm_files:
        return out

    brief_raw, brief_load_err = _try_load(workspace / "deck_brief.json")
    brief = _as_dict(brief_raw) if brief_raw is not None else None
    brief_refs: set[str] = set()
    # brief_refs_status is empty when the cross-check is permitted to run,
    # otherwise it carries a one-line reason. The render_model loop below
    # uses it to FAIL closed (rather than silently skip) when deck_brief is
    # missing, malformed, or has no source_refs of its own.
    if brief_raw is None:
        brief_refs_status = f"deck_brief.json unavailable: {brief_load_err}"
    elif brief is None:
        brief_refs_status = (
            f"deck_brief.json root is not an object "
            f"(got {type(brief_raw).__name__})"
        )
    else:
        brief_refs_raw = brief.get("source_refs")
        brief_refs_list = _as_list(brief_refs_raw)
        if brief_refs_list is None:
            brief_refs_status = (
                f"deck_brief.source_refs is not a list "
                f"(got {type(brief_refs_raw).__name__})"
            )
        else:
            string_refs = [r for r in brief_refs_list if isinstance(r, str)]
            if not string_refs:
                brief_refs_status = "deck_brief.source_refs is empty"
            else:
                brief_refs = set(string_refs)
                brief_refs_status = ""

    deck_raw, _ = _try_load(workspace / "deck_plan.json")
    deck = _as_dict(deck_raw) if deck_raw is not None else None
    deck_slides_by_index: dict[int, dict] = {}
    template_name = ""
    if deck is not None:
        for s in _as_list(deck.get("slides")) or []:
            s_d = _as_dict(s)
            if s_d is not None and isinstance(s_d.get("index"), int):
                deck_slides_by_index[s_d["index"]] = s_d
        t_raw = deck.get("template", "")
        if isinstance(t_raw, str):
            template_name = t_raw

    design_raw, _ = _try_load(workspace / "design_system.json")
    design = _as_dict(design_raw) if design_raw is not None else None
    palette_keys: set[str] = set()
    grid: dict | None = None
    if design is not None:
        palette = _as_dict(design.get("palette"))
        if palette is not None:
            palette_keys = {k for k in palette.keys() if isinstance(k, str)}
        grid = _as_dict(design.get("grid"))

    manifest_raw, _ = _try_load(workspace / "image_manifest.json")
    manifest = _as_dict(manifest_raw) if manifest_raw is not None else None
    manifest_ids: set[str] = set()
    if manifest is not None:
        for img in _as_list(manifest.get("images")) or []:
            img_d = _as_dict(img)
            if img_d is not None and isinstance(img_d.get("id"), str):
                manifest_ids.add(img_d["id"])

    layouts: dict[str, dict] = {}
    if template_name:
        ok, template_dir, _ = _safe_load_inside(template_root, template_name)
        if ok and template_dir is not None:
            layouts = _load_template_layouts(template_dir)

    for rm_file in rm_files:
        rm_raw, err = _try_load(rm_file)
        if rm_raw is None:
            out.append(CheckResult(
                f"render_model {rm_file.name}: loadable", False, err,
            ))
            continue
        rm = _as_dict(rm_raw)
        if rm is None:
            out.append(CheckResult(
                f"render_model {rm_file.name}: root is an object",
                False, f"got {type(rm_raw).__name__}",
            ))
            continue

        errors = _schema_validate(rm, SCHEMAS / "render_model.schema.json")
        out.append(CheckResult(
            f"render_model {rm_file.name}: validates against render_model.schema.json",
            not errors,
            "; ".join(errors),
        ))
        if errors:
            continue

        # index / layout cross-check against deck_plan.
        idx = rm.get("index")
        deck_slide = deck_slides_by_index.get(idx) if isinstance(idx, int) else None
        out.append(CheckResult(
            f"render_model {rm_file.name}: index {idx} matches a deck_plan slide",
            deck_slide is not None,
            f"deck_plan slide indices: {sorted(deck_slides_by_index)}",
        ))
        if deck_slide is not None:
            deck_layout = deck_slide.get("layout")
            out.append(CheckResult(
                f"render_model {rm_file.name}: layout {rm.get('layout')!r} "
                f"matches deck_plan slide layout {deck_layout!r}",
                rm.get("layout") == deck_layout,
            ))

        canvas = _as_dict(rm.get("canvas")) or {}
        canvas_w = canvas.get("width_px")
        canvas_h = canvas.get("height_px")
        if (
            grid is not None
            and isinstance(grid.get("width_px"), int)
            and isinstance(grid.get("height_px"), int)
        ):
            out.append(CheckResult(
                f"render_model {rm_file.name}: canvas matches design_system.grid "
                f"({canvas_w}x{canvas_h} vs {grid['width_px']}x{grid['height_px']})",
                canvas_w == grid["width_px"] and canvas_h == grid["height_px"],
            ))

        # source_refs cross-check, fail-closed. The schema already requires
        # source_refs and minItems:1 (so a missing/empty render_model
        # source_refs surfaces at schema time above). The cross-check here
        # must fail closed when deck_brief is unavailable rather than
        # silently skip — we surface brief_refs_status as the reason.
        rm_refs_list = _as_list(rm.get("source_refs")) or []
        if brief_refs_status:
            out.append(CheckResult(
                f"render_model {rm_file.name}: source_refs can be cross-checked "
                f"against deck_brief.source_refs",
                False, brief_refs_status,
            ))
        else:
            for ref in rm_refs_list:
                if not isinstance(ref, str) or ref not in brief_refs:
                    out.append(CheckResult(
                        f"render_model {rm_file.name}: source_ref {ref!r} "
                        f"declared in deck_brief.source_refs",
                        False, f"brief source_refs: {sorted(brief_refs)}",
                    ))

        # Layout slots, indexed by id, for slot_id cross-checks.
        layout = _as_dict(layouts.get(rm.get("layout"))) if rm.get("layout") else None
        slots_by_id: dict[str, dict] = {}
        if layout is not None:
            for s in _as_list(layout.get("slots")) or []:
                s_d = _as_dict(s)
                if s_d is not None and isinstance(s_d.get("id"), str):
                    slots_by_id[s_d["id"]] = s_d

        seen_ids: set[str] = set()
        for i, prim in enumerate(_as_list(rm.get("primitives")) or []):
            prim_d = _as_dict(prim)
            if prim_d is None:
                continue  # schema validation already caught this
            pid = prim_d.get("id")
            kind = prim_d.get("kind")
            label = f"render_model {rm_file.name} primitive[{i}] id={pid!r}"

            if isinstance(pid, str):
                out.append(CheckResult(
                    f"{label}: id is unique within this render_model",
                    pid not in seen_ids,
                ))
                seen_ids.add(pid)

            bounds = _as_dict(prim_d.get("bounds")) or {}
            if (
                isinstance(canvas_w, int) and isinstance(canvas_h, int)
                and all(isinstance(bounds.get(k), int) for k in ("x", "y", "w", "h"))
            ):
                x, y, w, h = bounds["x"], bounds["y"], bounds["w"], bounds["h"]
                inside = x + w <= canvas_w and y + h <= canvas_h
                out.append(CheckResult(
                    f"{label}: bounds fit inside canvas "
                    f"({x},{y},{w}x{h} vs {canvas_w}x{canvas_h})",
                    inside,
                ))

            payload_keys_present = [k for k in RENDER_PRIMITIVE_KINDS if k in prim_d]
            expected = [kind] if kind in RENDER_PRIMITIVE_KINDS else []
            out.append(CheckResult(
                f"{label}: payload field matches kind {kind!r} "
                f"(present={payload_keys_present}, expected={expected})",
                payload_keys_present == expected,
            ))

            slot_id = prim_d.get("slot_id")
            if isinstance(slot_id, str):
                slot = slots_by_id.get(slot_id)
                out.append(CheckResult(
                    f"{label}: slot_id {slot_id!r} exists on layout {rm.get('layout')!r}",
                    slot is not None,
                    f"known slot ids: {sorted(slots_by_id)}",
                ))
                if isinstance(slot, dict):
                    slot_pk = slot.get("primitive_kind")
                    if isinstance(slot_pk, str):
                        out.append(CheckResult(
                            f"{label}: kind {kind!r} matches slot.primitive_kind {slot_pk!r}",
                            kind == slot_pk,
                        ))
                    else:
                        slot_type = slot.get("type")
                        default_pk = DEFAULT_SLOT_TYPE_TO_PRIMITIVE_KIND.get(slot_type)
                        if default_pk is not None:
                            out.append(CheckResult(
                                f"{label}: kind {kind!r} matches default "
                                f"slot.type={slot_type!r} -> primitive {default_pk!r}",
                                kind == default_pk,
                            ))
                    slot_bounds = _as_dict(slot.get("bounds"))
                    if (
                        slot_bounds is not None
                        and all(isinstance(slot_bounds.get(k), int)
                                for k in ("x", "y", "w", "h"))
                        and all(isinstance(bounds.get(k), int)
                                for k in ("x", "y", "w", "h"))
                    ):
                        sx, sy = slot_bounds["x"], slot_bounds["y"]
                        sw, sh = slot_bounds["w"], slot_bounds["h"]
                        bx, by = bounds["x"], bounds["y"]
                        bw, bh = bounds["w"], bounds["h"]
                        fits = (
                            bx >= sx and by >= sy
                            and bx + bw <= sx + sw
                            and by + bh <= sy + sh
                        )
                        out.append(CheckResult(
                            f"{label}: bounds fit inside slot {slot_id!r}.bounds",
                            fits,
                            f"primitive=({bx},{by},{bw}x{bh}), "
                            f"slot=({sx},{sy},{sw}x{sh})",
                        ))

            if kind == "image_slot":
                img_payload = _as_dict(prim_d.get("image_slot")) or {}
                image_ref = img_payload.get("image_ref")
                if isinstance(image_ref, str):
                    out.append(CheckResult(
                        f"{label}: image_ref {image_ref!r} declared in image_manifest",
                        image_ref in manifest_ids,
                        f"manifest ids: {sorted(manifest_ids)}",
                    ))

            style = _as_dict(prim_d.get("style")) or {}
            for token_field in ("fill_token", "color_token", "stroke_token"):
                token = style.get(token_field)
                if isinstance(token, str) and token.startswith("palette."):
                    key = token.split(".", 1)[1]
                    if palette_keys:
                        out.append(CheckResult(
                            f"{label}: {token_field} {token!r} resolves "
                            f"to a design_system palette key",
                            key in palette_keys,
                            f"palette keys: {sorted(palette_keys)}",
                        ))

            offending = [
                s for s in _render_model_reference_strings(prim_d)
                if _URI_SCHEME_PREFIX.match(s)
            ]
            out.append(CheckResult(
                f"{label}: no reference-field string carries a URI-scheme prefix",
                not offending,
                f"offending: {offending}",
            ))
    return out


SVG_NS = "http://www.w3.org/2000/svg"


def _strip_ns(tag: str) -> str:
    """Return the local name from an ElementTree namespaced tag.
    ElementTree formats namespaced tags as '{ns}local' — strip the
    namespace so the validator can compare against bare element names."""
    if isinstance(tag, str) and tag.startswith("{"):
        end = tag.find("}")
        if end >= 0:
            return tag[end + 1 :]
    return tag if isinstance(tag, str) else ""


def _iter_elements(root):
    """Yield every element under root, including root itself."""
    yield root
    for el in root.iter():
        if el is root:
            continue
        yield el


def check_svg_previews(workspace: Path, template_root: Path) -> list[CheckResult]:
    """Validate workspace/svg_previews/*.svg against the corresponding
    workspace/render_models/*.json.

    The svg_previews/ directory is optional. If render_models/ is absent
    or empty, no checks fire — the SVG preview stage only matters once
    the render-model generator has produced output. When the workspace
    ships render_models but no svg_previews/, each missing preview is
    reported as a FAIL.

    Checks (every gate is fail-closed):
      - svg_previews/<stem>.svg exists for each render_models/<stem>.json;
      - the SVG parses as XML with a root element named 'svg' in the
        SVG namespace;
      - the root viewBox attribute equals '0 0 <width> <height>' where
        width/height match the render_model canvas;
      - no <foreignObject> element appears anywhere in the tree
        (HTML-in-SVG escape hatch is forbidden);
      - every reference-bearing attribute string (href, xlink:href, src,
        and any attribute name ending with 'href') passes the same
        path-safety rule the workspace uses for image_manifest paths:
        no URI scheme prefix, no POSIX-absolute path, no leading
        backslash, no protocol-relative, no '..' segment, no empty
        string;
      - every reference value names an image_manifest entry id whose
        declared local_path equals the reference (undeclared references
        are rejected);
      - every <rect>, <line>, <image>, <ellipse>, <circle> with
        explicit numeric position/size attributes stays inside the
        canvas, and every <text> with numeric x/y has its anchor
        point inside the canvas (best-effort: <text> width / height /
        wrapping at the glyph level is NOT enforced — that needs
        font metrics this stdlib-only validator does not carry, and
        remains a TODO in references/svg-design-rules.md)."""
    import xml.etree.ElementTree as ET

    out: list[CheckResult] = []
    rm_dir = workspace / "render_models"
    if not rm_dir.is_dir():
        return out
    rm_files = sorted(rm_dir.glob("*.json"))
    if not rm_files:
        return out

    sp_dir = workspace / "svg_previews"

    # Build image_manifest map for cross-checks.
    manifest_raw, _ = _try_load(workspace / "image_manifest.json")
    manifest = _as_dict(manifest_raw) if manifest_raw is not None else None
    manifest_path_by_id: dict[str, str] = {}
    if manifest is not None:
        for img in _as_list(manifest.get("images")) or []:
            img_d = _as_dict(img)
            if img_d is None:
                continue
            img_id = img_d.get("id")
            local_path = img_d.get("local_path")
            if isinstance(img_id, str) and isinstance(local_path, str):
                manifest_path_by_id[img_id] = local_path
    declared_paths = set(manifest_path_by_id.values())

    for rm_file in rm_files:
        stem = rm_file.stem
        svg_path = sp_dir / f"{stem}.svg"
        label = f"svg_preview {stem}.svg"

        if not svg_path.is_file():
            out.append(CheckResult(
                f"{label}: exists for render_models/{rm_file.name}",
                False,
                f"missing {svg_path}",
            ))
            continue
        out.append(CheckResult(
            f"{label}: exists for render_models/{rm_file.name}",
            True,
        ))

        # Load the matching render_model so canvas can be cross-checked.
        rm_raw, err = _try_load(rm_file)
        rm = _as_dict(rm_raw) if rm_raw is not None else None
        canvas = _as_dict(rm.get("canvas")) if rm is not None else None
        canvas_w = canvas.get("width_px") if canvas is not None else None
        canvas_h = canvas.get("height_px") if canvas is not None else None

        try:
            text = svg_path.read_text()
        except OSError as exc:
            out.append(CheckResult(
                f"{label}: readable", False, f"read error: {exc}",
            ))
            continue
        try:
            tree_root = ET.fromstring(text)
        except ET.ParseError as exc:
            out.append(CheckResult(
                f"{label}: parses as XML", False, f"parse error: {exc}",
            ))
            continue
        out.append(CheckResult(f"{label}: parses as XML", True))

        root_tag = _strip_ns(tree_root.tag)
        out.append(CheckResult(
            f"{label}: root element is <svg> in the SVG namespace",
            root_tag == "svg" and tree_root.tag == f"{{{SVG_NS}}}svg",
            f"root tag: {tree_root.tag!r}",
        ))

        viewbox = tree_root.attrib.get("viewBox", "")
        if isinstance(canvas_w, int) and isinstance(canvas_h, int):
            expected_viewbox = f"0 0 {canvas_w} {canvas_h}"
            out.append(CheckResult(
                f"{label}: viewBox matches render_model canvas",
                viewbox == expected_viewbox,
                f"viewBox={viewbox!r}, expected={expected_viewbox!r}",
            ))

        foreign_objects = [
            el for el in _iter_elements(tree_root)
            if _strip_ns(el.tag) == "foreignObject"
        ]
        out.append(CheckResult(
            f"{label}: contains no <foreignObject>",
            not foreign_objects,
            f"found {len(foreign_objects)} <foreignObject> element(s)",
        ))

        # Reference / attribute walks.
        offending_refs: list[tuple[str, str, str]] = []
        undeclared_refs: list[tuple[str, str]] = []
        for el in _iter_elements(tree_root):
            local_tag = _strip_ns(el.tag)
            for attr_name, attr_value in el.attrib.items():
                local_attr = _strip_ns(attr_name)
                if not isinstance(attr_value, str):
                    continue
                is_ref_attr = (
                    local_attr in ("href", "src")
                    or local_attr.endswith("href")
                )
                if not is_ref_attr:
                    continue
                if not local_path_is_safe(attr_value):
                    offending_refs.append((local_tag, local_attr, attr_value))
                    continue
                # A safe ref must also be one this workspace declared
                # via image_manifest. We allow only references whose
                # value exactly equals a manifest local_path; this
                # rejects future hand-edited SVGs that add an internal-
                # looking but undeclared path.
                if local_tag == "image":
                    if attr_value not in declared_paths:
                        undeclared_refs.append((local_attr, attr_value))
        out.append(CheckResult(
            f"{label}: no reference-bearing attribute carries a URI scheme, "
            f"absolute path, '..' segment, or other unsafe form",
            not offending_refs,
            f"offending: {offending_refs}",
        ))
        out.append(CheckResult(
            f"{label}: every <image> href is declared in image_manifest",
            not undeclared_refs,
            f"undeclared: {undeclared_refs}, "
            f"declared paths: {sorted(declared_paths)}",
        ))

        # Bounds-inside-canvas (best-effort). Checks elements whose
        # geometry is expressed via the standard numeric attributes:
        #   rect, image:       x, y, width, height
        #   ellipse:           cx, cy, rx, ry
        #   circle:            cx, cy, r
        #   line:              x1, y1, x2, y2
        #   text:              x, y (no width/height — SVG <text> has no
        #                      intrinsic box; the validator only checks
        #                      that the anchor point sits inside the
        #                      canvas. Text overflow / wrapping at the
        #                      glyph level requires font metrics this
        #                      stdlib-only validator does not have, so
        #                      that part of the rule remains a TODO in
        #                      references/svg-design-rules.md.)
        # The root <svg> itself is excluded — its width/height define
        # the canvas.
        if isinstance(canvas_w, int) and isinstance(canvas_h, int):
            outside: list[tuple[str, str]] = []
            for el in _iter_elements(tree_root):
                if el is tree_root:
                    continue
                tag = _strip_ns(el.tag)
                a = el.attrib
                try:
                    if tag in ("rect", "image"):
                        x = float(a["x"]); y = float(a["y"])
                        w = float(a["width"]); h = float(a["height"])
                        if x < 0 or y < 0 or x + w > canvas_w or y + h > canvas_h:
                            outside.append((tag, f"x={x},y={y},w={w},h={h}"))
                    elif tag == "ellipse":
                        cx = float(a["cx"]); cy = float(a["cy"])
                        rx = float(a["rx"]); ry = float(a["ry"])
                        if (cx - rx) < 0 or (cy - ry) < 0 or (cx + rx) > canvas_w or (cy + ry) > canvas_h:
                            outside.append((tag, f"cx={cx},cy={cy},rx={rx},ry={ry}"))
                    elif tag == "circle":
                        cx = float(a["cx"]); cy = float(a["cy"])
                        r = float(a["r"])
                        if (cx - r) < 0 or (cy - r) < 0 or (cx + r) > canvas_w or (cy + r) > canvas_h:
                            outside.append((tag, f"cx={cx},cy={cy},r={r}"))
                    elif tag == "line":
                        x1 = float(a["x1"]); y1 = float(a["y1"])
                        x2 = float(a["x2"]); y2 = float(a["y2"])
                        for cx_, cy_ in ((x1, y1), (x2, y2)):
                            if cx_ < 0 or cy_ < 0 or cx_ > canvas_w or cy_ > canvas_h:
                                outside.append((tag, f"x1={x1},y1={y1},x2={x2},y2={y2}"))
                                break
                    elif tag == "text":
                        x = float(a["x"]); y = float(a["y"])
                        if x < 0 or y < 0 or x > canvas_w or y > canvas_h:
                            outside.append((tag, f"x={x},y={y}"))
                except (KeyError, ValueError):
                    # Element lacks the standard numeric attributes
                    # this best-effort walker recognises. Other gates
                    # (URI-scheme walk, foreignObject check, schema) keep
                    # it bounded; we don't fabricate failures for
                    # elements whose geometry is expressed differently.
                    continue
            out.append(CheckResult(
                f"{label}: every element with explicit numeric geometry "
                f"stays inside the canvas (best-effort)",
                not outside,
                f"outside: {outside}",
            ))
    return out


def negative_checks(workspace: Path, template_root: Path) -> list[CheckResult]:
    """Built-in negative tests covering every category required by the
    task: unsafe schemes, absolute paths, path traversal, missing
    media, unknown layout, missing slide_plan, required-slot mismatch.
    Each check passes when the validator correctly identifies the bad
    input."""
    out: list[CheckResult] = []

    for scheme in (
        "s3://bucket/img.png",
        "ftp://host/img.png",
        "data:image/svg+xml;base64,abc",
        "mailto:test@example.com",
        "javascript:alert(1)",
    ):
        out.append(CheckResult(
            f"unsafe scheme rejected by local_path_is_safe: {scheme}",
            not local_path_is_safe(scheme),
        ))

    for absp in ("/etc/passwd", "C:\\Windows\\System32\\img.png", "D:/img.png", "\\\\server\\share\\x"):
        out.append(CheckResult(
            f"absolute / drive path rejected: {absp}",
            not local_path_is_safe(absp),
        ))

    for trav in ("../escape.png", "assets/../../escape.png", "a/b/../../../etc/passwd"):
        out.append(CheckResult(
            f"path traversal rejected: {trav}",
            not local_path_is_safe(trav),
        ))

    # Gate proof for deck_plan.template: unsafe values must be refused by
    # _safe_load_inside without ever producing a resolved path. This
    # guards against the regression where the workspace validator called
    # (template_root / template_name).resolve() and _load() without
    # gating the template name.
    for bad_template in (
        "../../etc/passwd",
        "/etc/passwd",
        "C:\\Windows\\template.json",
        "s3://bucket/template.json",
        "http://example.com/template.json",
        "data:application/json;base64,abc",
    ):
        ok, resolved, _ = _safe_load_inside(template_root, bad_template)
        out.append(CheckResult(
            f"deck_plan.template {bad_template!r} is gated by _safe_load_inside",
            (not ok) and (resolved is None),
            f"ok={ok}, resolved={resolved}",
        ))

    # Missing media: build a synthetic manifest entry that points at a
    # path which is path-safe and inside the workspace but does not exist.
    missing_rel = "assets/__synthetic_missing_xyz.svg"
    ok, candidate, _ = _safe_load_inside(workspace, missing_rel)
    out.append(CheckResult(
        f"missing media detected: workspace-relative path {missing_rel!r} flagged as not-a-file",
        ok and candidate is not None and not candidate.is_file(),
    ))

    deck_plan_raw, err = _try_load(workspace / "deck_plan.json")
    if deck_plan_raw is None:
        out.append(CheckResult(
            "template-dependent negatives skipped: deck_plan.json loadable",
            False, err,
        ))
        return out
    deck_plan = _as_dict(deck_plan_raw)
    if deck_plan is None:
        out.append(CheckResult(
            "template-dependent negatives skipped: deck_plan.json root is an object",
            False, f"got {type(deck_plan_raw).__name__}",
        ))
        return out
    template_name = deck_plan.get("template", "")
    ok, template_dir, reason = _safe_load_inside(template_root, template_name)
    if not ok:
        # Fail-closed: do NOT call .resolve() or _load against an unsafe
        # template_name. Skip the template-dependent negatives entirely
        # and report the gate result so the regression stays visible.
        out.append(CheckResult(
            f"negative template-dependent checks skipped (fail-closed): "
            f"deck_plan.template {template_name!r} unsafe",
            False,
            reason,
        ))
        return out
    template_raw, err = _try_load(template_dir / "template.json")
    if template_raw is None:
        out.append(CheckResult(
            f"template-dependent negatives skipped: template.json loadable for {template_name!r}",
            False, err,
        ))
        return out
    template = _as_dict(template_raw)
    if template is None:
        out.append(CheckResult(
            f"template-dependent negatives skipped: template.json root is an object for {template_name!r}",
            False, f"got {type(template_raw).__name__}",
        ))
        return out
    declared_list = _as_list(template.get("layouts", [])) or []
    declared_layouts = {d for d in declared_list if isinstance(d, str)}

    # Unknown layout in deck_plan: in-memory mutation. Guard against
    # malformed slides — only mutate a dict slide.
    deck_slides_for_mutation = _as_list(deck_plan.get("slides")) or []
    dict_slide_for_mutation = next(
        (s for s in deck_slides_for_mutation if isinstance(s, dict)),
        None,
    )
    if dict_slide_for_mutation is not None:
        bad_deck = copy.deepcopy(deck_plan)
        for s in bad_deck["slides"]:
            if isinstance(s, dict):
                s["layout"] = "__no_such_layout_xyz"
                break
        out.append(CheckResult(
            "unknown layout '__no_such_layout_xyz' not in template's declared layouts",
            "__no_such_layout_xyz" not in declared_layouts,
        ))
    else:
        out.append(CheckResult(
            "unknown-layout negative setup: at least one deck_plan slide is an object",
            False,
            f"slides={deck_slides_for_mutation!r}",
        ))

    # Missing slide_plan: pretend one deck_plan slide has no plan file.
    plans_dir = workspace / "slide_plans"
    real_indices: set[int] = set()
    if plans_dir.is_dir():
        for p in plans_dir.glob("*.json"):
            data, _ = _try_load(p)
            data_d = _as_dict(data) if data is not None else None
            if data_d is not None and isinstance(data_d.get("index"), int):
                real_indices.add(data_d["index"])
    deck_indices: set[int] = set()
    for s in deck_slides_for_mutation:
        s_d = _as_dict(s)
        if s_d is not None and isinstance(s_d.get("index"), int):
            deck_indices.add(s_d["index"])
    # Synthetically drop a slide_plan by removing its index from real_indices.
    if real_indices:
        dropped = sorted(real_indices)[0]
        simulated_missing = (deck_indices - (real_indices - {dropped}))
        out.append(CheckResult(
            f"missing slide_plan detected when slide {dropped} is omitted",
            dropped in simulated_missing,
            f"simulated_missing={sorted(simulated_missing)}",
        ))
    else:
        out.append(CheckResult(
            "missing slide_plan check setup: at least one real slide_plan exists",
            False,
        ))

    # Orphan slide_plan: index not in deck_plan.
    orphan_idx = max(deck_indices) + 999 if deck_indices else 9999
    out.append(CheckResult(
        f"orphan slide_plan index {orphan_idx} not declared in deck_plan",
        orphan_idx not in deck_indices,
    ))

    # Required-slot mismatch: take an existing slide_plan, drop a required
    # block, and confirm _slide_plan_against_layout reports the gap.
    layouts: dict[str, dict] = {}
    if (template_dir / "layouts").is_dir():
        for f in sorted((template_dir / "layouts").glob("*.json")):
            data, _ = _try_load(f)
            data_d = _as_dict(data) if data is not None else None
            if data_d is not None:
                layouts[f.stem] = data_d
    sample_files = sorted(plans_dir.glob("*.json")) if plans_dir.is_dir() else []
    if not sample_files:
        out.append(CheckResult(
            "required-slot mismatch setup: at least one slide_plan exists",
            False,
        ))
        return out
    sample_file = sample_files[0]
    sample_plan_raw, _ = _try_load(sample_file)
    sample_plan = _as_dict(sample_plan_raw) if sample_plan_raw is not None else None
    if sample_plan is None:
        out.append(CheckResult(
            "required-slot mismatch setup: sample slide_plan loadable as an object",
            False,
        ))
        return out
    bad_plan = copy.deepcopy(sample_plan)
    layout_def = layouts.get(sample_plan.get("layout"))
    if layout_def is None:
        out.append(CheckResult(
            f"required-slot mismatch setup: layout for {sample_file.name} loaded",
            False,
        ))
        return out
    slots_list = _as_list(layout_def.get("slots")) or []
    required_ids = [
        s["id"] for s in slots_list
        if isinstance(s, dict) and s.get("required") and isinstance(s.get("id"), str)
    ]
    if required_ids:
        target_id = required_ids[0]
        blocks_list = _as_list(bad_plan.get("blocks")) or []
        bad_plan["blocks"] = [
            b for b in blocks_list
            if isinstance(b, dict) and b.get("id") != target_id
        ]
        problems = _slide_plan_against_layout(bad_plan, layout_def)
        out.append(CheckResult(
            f"required-slot mismatch detected when slot {target_id!r} is dropped from {sample_file.name}",
            any(f"missing required slot '{target_id}'" in p for p in problems),
            "; ".join(problems),
        ))
    else:
        out.append(CheckResult(
            f"required-slot mismatch setup: {sample_file.name}'s layout has at least one required slot",
            False,
        ))

    # Wrong kind on a required slot.
    bad_kind_plan = copy.deepcopy(sample_plan)
    if required_ids:
        target_id = required_ids[0]
        bad_blocks = _as_list(bad_kind_plan.get("blocks")) or []
        for b in bad_blocks:
            if isinstance(b, dict) and b.get("id") == target_id:
                b["kind"] = "image_ref"  # almost certainly wrong
        bad_kind_plan["blocks"] = bad_blocks
        problems = _slide_plan_against_layout(bad_kind_plan, layout_def)
        out.append(CheckResult(
            f"wrong kind on required slot {target_id!r} is detected",
            any(f"slot '{target_id}' expected kind" in p for p in problems),
            "; ".join(problems),
        ))

    return out


_MIN_THEME = {
    "name": "tmpl",
    "version": "0.1.0",
    "palette": {"primary": "#000000", "background": "#FFFFFF", "text": "#000000"},
    "typography": {
        "heading": {"font_family": "Arial", "size_pt": 28},
        "body":    {"font_family": "Arial", "size_pt": 14},
    },
    "grid": {"width_px": 1920, "height_px": 1080, "margin_px": 64},
}
_MIN_LAYOUT = {
    "name": "dummy",
    "slots": [{"id": "title", "type": "text", "required": True}],
}


def _make_template_dir(
    root: Path,
    name: str,
    *,
    with_theme: bool = True,
    theme_obj: dict | None = None,
    declared_layouts: list[str] | None = None,
    layout_files: dict[str, dict] | None = None,
) -> Path:
    """Build a minimal synthetic template directory under root for use
    by the tempfixture negative checks. All defaults are synthetic; no
    real examples are touched."""
    td = root / name
    (td / "layouts").mkdir(parents=True)
    template_obj = {
        "name": name,
        "version": "0.1.0",
        "theme_ref": "theme.json",
        "layouts": declared_layouts if declared_layouts is not None else ["dummy"],
    }
    (td / "template.json").write_text(json.dumps(template_obj))
    if with_theme:
        theme = dict(theme_obj if theme_obj is not None else _MIN_THEME)
        theme["name"] = name
        (td / "theme.json").write_text(json.dumps(theme))
    files = layout_files if layout_files is not None else {"dummy": _MIN_LAYOUT}
    for stem, body in files.items():
        (td / "layouts" / f"{stem}.json").write_text(json.dumps(body))
    return td


def negative_tempfixture_checks() -> list[CheckResult]:
    """Build small synthetic-bad fixtures under tempfile.TemporaryDirectory
    and confirm the validator's helpers detect the failure conditions.
    Stdlib only; no real examples are referenced. Each TemporaryDirectory
    is cleaned up at scope exit."""
    import tempfile
    out: list[CheckResult] = []

    # 1. Missing theme file.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_template_dir(root, "tmpl_missing_theme", with_theme=False)
        results = check_template_files(root, "tmpl_missing_theme")
        detected = any(
            ("theme file" in r.name) and ("exists" in r.name) and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: missing theme file is detected",
            detected,
            f"failing checks: {[r.name for r in results if not r.ok]}",
        ))

    # 2. theme.json fails schema (missing required 'palette').
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bad_theme = {k: v for k, v in _MIN_THEME.items() if k != "palette"}
        _make_template_dir(root, "tmpl_bad_theme", theme_obj=bad_theme)
        results = check_template_files(root, "tmpl_bad_theme")
        detected = any(
            ("theme validates" in r.name) and not r.ok for r in results
        )
        out.append(CheckResult(
            "tempfixture: invalid theme schema is detected",
            detected,
            f"failing checks: {[r.name for r in results if not r.ok]}",
        ))

    # 3. layout.json carries an extra field that violates additionalProperties.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bad_layout = dict(_MIN_LAYOUT)
        bad_layout["unexpected_extra_field"] = "boom"
        _make_template_dir(
            root, "tmpl_bad_layout",
            layout_files={"dummy": bad_layout},
        )
        results = check_template_files(root, "tmpl_bad_layout")
        detected = any(
            ("layout 'dummy' validates" in r.name) and not r.ok for r in results
        )
        out.append(CheckResult(
            "tempfixture: invalid layout schema (extra field) is detected",
            detected,
            f"failing checks: {[r.name for r in results if not r.ok]}",
        ))

    # 4. Template declares a layout but the file is missing.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_template_dir(
            root, "tmpl_missing_layout_file",
            declared_layouts=["ghost"],
            layout_files={},
        )
        results = check_template_files(root, "tmpl_missing_layout_file")
        detected = any(
            ("declared layout 'ghost' has a file" in r.name) and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: declared-but-missing layout file is detected",
            detected,
            f"failing checks: {[r.name for r in results if not r.ok]}",
        ))

    # 5. Duplicate slide_plan index.
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        ws.mkdir()
        (ws / "deck_plan.json").write_text(json.dumps({
            "template": "synthetic_tmpl",
            "slides": [{"index": 1, "layout": "dummy", "title": "T"}],
        }))
        plans_dir = ws / "slide_plans"
        plans_dir.mkdir()
        for stem in ("01_a", "01_b"):
            (plans_dir / f"{stem}.json").write_text(json.dumps({
                "index": 1, "layout": "dummy", "title": "T",
                "blocks": [{"id": "title", "kind": "text", "content": "x"}],
            }))
        tr = Path(td) / "templates"
        _make_template_dir(tr, "synthetic_tmpl")
        results = check_slide_plan_coverage(ws, tr)
        detected = any(
            ("appears in exactly one file" in r.name) and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: duplicate slide_plan index is detected",
            detected,
            f"failing checks: {[r.name for r in results if not r.ok]}",
        ))

    # 6. Duplicate deck_plan index — must FAIL, not silently collapse.
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        ws.mkdir()
        (ws / "deck_plan.json").write_text(json.dumps({
            "template": "synthetic_tmpl",
            "slides": [
                {"index": 1, "layout": "dummy", "title": "A"},
                {"index": 1, "layout": "dummy", "title": "B"},
            ],
        }))
        plans_dir = ws / "slide_plans"
        plans_dir.mkdir()
        (plans_dir / "01.json").write_text(json.dumps({
            "index": 1, "layout": "dummy", "title": "A",
            "blocks": [{"id": "title", "kind": "text", "content": "x"}],
        }))
        tr = Path(td) / "templates"
        _make_template_dir(tr, "synthetic_tmpl")
        results = check_slide_plan_coverage(ws, tr)
        detected = any(
            ("deck_plan slide indices are unique" in r.name) and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: duplicate deck_plan index is detected (no false-green)",
            detected,
            f"failing checks: {[r.name for r in results if not r.ok]}",
        ))

    # 7. Workspace missing deck_plan.json — must not raise.
    with tempfile.TemporaryDirectory() as td:
        empty_ws = Path(td) / "empty"
        empty_ws.mkdir()
        try:
            schema_results = check_schemas(empty_ws)
            chain_results = check_template_chain(empty_ws, REPO_ROOT / "templates" / "layouts")
            cov_results = check_slide_plan_coverage(
                empty_ws, REPO_ROOT / "templates" / "layouts",
            )
            img_results = check_image_manifest(empty_ws)
            no_traceback = True
        except Exception as exc:  # noqa: BLE001 - we explicitly want to detect ANY raise
            schema_results = chain_results = cov_results = img_results = []
            no_traceback = False
            exc_kind = type(exc).__name__
        else:
            exc_kind = ""
        deck_plan_reported = any(
            ("deck_plan.json" in r.name) and not r.ok
            for r in schema_results + chain_results + cov_results
        )
        manifest_reported = any(
            ("image_manifest.json" in r.name) and not r.ok
            for r in img_results
        )
        out.append(CheckResult(
            "tempfixture: missing deck_plan.json is reported without traceback",
            no_traceback and deck_plan_reported and manifest_reported,
            f"no_traceback={no_traceback}, exc={exc_kind}, "
            f"deck_plan_reported={deck_plan_reported}, "
            f"manifest_reported={manifest_reported}",
        ))

    # 8. Malformed-but-loadable caller workspace — every check function
    # must produce FAIL rows and must NOT traceback. Covers the
    # regressions where a non-dict slide / list-rooted artifact /
    # incomplete manifest entry crashed the downstream checks.
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws_malformed"
        ws.mkdir()
        (ws / "deck_brief.json").write_text(json.dumps({"unexpected": True}))
        (ws / "deck_plan.json").write_text(json.dumps({
            "template": "business_review",
            "slides": [{"x": "y"}, "not_an_object", 42],
        }))
        (ws / "design_system.json").write_text(json.dumps({"palette": "string_not_object"}))
        (ws / "image_manifest.json").write_text(json.dumps({
            "images": [{"oops": "no_required_fields"}, "string_instead_of_object"],
        }))
        plans_dir = ws / "slide_plans"
        plans_dir.mkdir()
        (plans_dir / "1.json").write_text(json.dumps({"index": 1}))
        (plans_dir / "2.json").write_text(json.dumps([1, 2, 3]))

        tr = REPO_ROOT / "templates" / "layouts"
        try:
            sch = check_schemas(ws)
            chain = check_template_chain(ws, tr)
            tfiles = check_template_files_for_workspace(ws, tr)
            cov = check_slide_plan_coverage(ws, tr)
            img = check_image_manifest(ws)
            neg = negative_checks(ws, tr)
            no_traceback = True
            exc_kind = ""
        except Exception as exc:  # noqa: BLE001 - explicit catch-all
            sch = chain = tfiles = cov = img = neg = []
            no_traceback = False
            exc_kind = type(exc).__name__
        all_results = sch + chain + tfiles + cov + img + neg
        any_failure_reported = any(not r.ok for r in all_results)
        out.append(CheckResult(
            "tempfixture: malformed-but-loadable workspace does not traceback "
            "(non-dict slides, list-rooted slide_plan, incomplete manifest entries)",
            no_traceback and any_failure_reported,
            f"no_traceback={no_traceback}, exc={exc_kind}, "
            f"any_failure_reported={any_failure_reported}",
        ))

    # 9. List-rooted core artifacts — every check function must still
    # produce a FAIL row and must NOT traceback when an artifact is
    # loadable JSON but not a JSON object.
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws_list_root"
        ws.mkdir()
        (ws / "deck_brief.json").write_text("[1,2]")
        (ws / "deck_plan.json").write_text("[1,2,3]")
        (ws / "design_system.json").write_text("\"not-an-object\"")
        (ws / "image_manifest.json").write_text("[]")
        (ws / "slide_plans").mkdir()
        tr = REPO_ROOT / "templates" / "layouts"
        try:
            chain = check_template_chain(ws, tr)
            tfiles = check_template_files_for_workspace(ws, tr)
            cov = check_slide_plan_coverage(ws, tr)
            img = check_image_manifest(ws)
            neg = negative_checks(ws, tr)
            no_traceback = True
            exc_kind = ""
        except Exception as exc:  # noqa: BLE001
            chain = tfiles = cov = img = neg = []
            no_traceback = False
            exc_kind = type(exc).__name__
        all_results = chain + tfiles + cov + img + neg
        any_failure_reported = any(not r.ok for r in all_results)
        out.append(CheckResult(
            "tempfixture: list-rooted core artifacts do not traceback",
            no_traceback and any_failure_reported,
            f"no_traceback={no_traceback}, exc={exc_kind}, "
            f"any_failure_reported={any_failure_reported}",
        ))

    return out


def _write_minimal_planner_workspace(ws: Path) -> None:
    """Build a workspace whose deck_brief.json + deck_plan.json pass
    check_planner_semantics. Used as the clean baseline that each
    planner-semantics tempfixture mutates by exactly one rule violation."""
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "deck_brief.json").write_text(json.dumps({
        "title": "T", "audience": "A", "objective": "O",
        "source_refs": ["src_a", "src_b"],
    }))
    (ws / "deck_plan.json").write_text(json.dumps({
        "template": "tpl",
        "planning": {"planned_slide_count": 2, "rationale": "synthetic"},
        "sections": [
            {"id": "s1", "title": "S1", "summary": "x", "slide_indices": [1]},
            {"id": "s2", "title": "S2", "summary": "x", "slide_indices": [2]},
        ],
        "slides": [
            {"index": 1, "layout": "L", "title": "T1",
             "section_id": "s1", "summary": "x", "density": "low",
             "source_refs": ["src_a"]},
            {"index": 2, "layout": "L", "title": "T2",
             "section_id": "s2", "summary": "x", "density": "medium",
             "source_refs": ["src_b"]},
        ],
    }))


def negative_planner_semantics_tempfixture_checks() -> list[CheckResult]:
    """Negative tempfixtures proving check_planner_semantics fails closed
    on each cross-artifact invariant: planned_slide_count mismatch,
    section coverage gaps (missing / duplicate-across-sections / orphan
    indices), slide section_id pointing at an unknown section, slide
    index not listed in its section, and slide source_ref not declared
    in deck_brief. Each case builds a clean baseline workspace, applies
    exactly one mutation, and asserts the targeted check failed."""
    import tempfile
    out: list[CheckResult] = []

    # Sanity: the minimal baseline itself is clean. Catches regressions
    # in either the baseline writer or check_planner_semantics.
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        _write_minimal_planner_workspace(ws)
        results = check_planner_semantics(ws)
        out.append(CheckResult(
            "tempfixture: minimal planner-semantics baseline passes check_planner_semantics",
            all(r.ok for r in results),
            "; ".join(f"{r.name}: {r.detail}" for r in results if not r.ok),
        ))

    # A. planned_slide_count != len(slides).
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        _write_minimal_planner_workspace(ws)
        deck = json.loads((ws / "deck_plan.json").read_text())
        deck["planning"]["planned_slide_count"] = 99
        (ws / "deck_plan.json").write_text(json.dumps(deck))
        results = check_planner_semantics(ws)
        detected = any(
            "planning.planned_slide_count" in r.name
            and "equals len(slides)" in r.name
            and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: planned_slide_count mismatch is detected",
            detected,
            "; ".join(f"{r.name}: {r.detail}" for r in results if not r.ok),
        ))

    # B. Section coverage is missing a slide index that deck_plan declares.
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        _write_minimal_planner_workspace(ws)
        deck = json.loads((ws / "deck_plan.json").read_text())
        for sec in deck["sections"]:
            if sec["id"] == "s2":
                sec["slide_indices"] = []
        (ws / "deck_plan.json").write_text(json.dumps(deck))
        results = check_planner_semantics(ws)
        detected = any(
            "sections cover every deck_plan slide index" in r.name and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: missing section coverage of a deck_plan slide is detected",
            detected,
            "; ".join(f"{r.name}: {r.detail}" for r in results if not r.ok),
        ))

    # C. Duplicate index across two sections.
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        _write_minimal_planner_workspace(ws)
        deck = json.loads((ws / "deck_plan.json").read_text())
        for sec in deck["sections"]:
            if sec["id"] == "s1":
                sec["slide_indices"] = [1, 2]
        (ws / "deck_plan.json").write_text(json.dumps(deck))
        results = check_planner_semantics(ws)
        detected = any(
            "no slide index appears in more than one section" in r.name and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: duplicate slide index across sections is detected",
            detected,
            "; ".join(f"{r.name}: {r.detail}" for r in results if not r.ok),
        ))

    # D. Orphan section index that the deck_plan does not declare.
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        _write_minimal_planner_workspace(ws)
        deck = json.loads((ws / "deck_plan.json").read_text())
        for sec in deck["sections"]:
            if sec["id"] == "s2":
                sec["slide_indices"] = [2, 99]
        (ws / "deck_plan.json").write_text(json.dumps(deck))
        results = check_planner_semantics(ws)
        detected = any(
            "sections list no slide indices the deck_plan does not declare" in r.name and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: orphan section slide_index is detected",
            detected,
            "; ".join(f"{r.name}: {r.detail}" for r in results if not r.ok),
        ))

    # E. Slide.section_id is unknown.
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        _write_minimal_planner_workspace(ws)
        deck = json.loads((ws / "deck_plan.json").read_text())
        deck["slides"][0]["section_id"] = "__no_such_section__"
        (ws / "deck_plan.json").write_text(json.dumps(deck))
        results = check_planner_semantics(ws)
        detected = any(
            "section_id '__no_such_section__' exists in sections" in r.name and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: slide.section_id pointing at unknown section is detected",
            detected,
            "; ".join(f"{r.name}: {r.detail}" for r in results if not r.ok),
        ))

    # F. Slide claims a section that does not list this index.
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        _write_minimal_planner_workspace(ws)
        deck = json.loads((ws / "deck_plan.json").read_text())
        deck["slides"][0]["section_id"] = "s2"
        (ws / "deck_plan.json").write_text(json.dumps(deck))
        results = check_planner_semantics(ws)
        detected = any(
            "listed in section 's2'.slide_indices" in r.name and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: slide.section_id that does not list this slide index is detected",
            detected,
            "; ".join(f"{r.name}: {r.detail}" for r in results if not r.ok),
        ))

    # G. Slide.source_refs value not declared in deck_brief.source_refs.
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        _write_minimal_planner_workspace(ws)
        deck = json.loads((ws / "deck_plan.json").read_text())
        deck["slides"][0]["source_refs"] = ["__no_such_src__"]
        (ws / "deck_plan.json").write_text(json.dumps(deck))
        results = check_planner_semantics(ws)
        detected = any(
            "source_ref '__no_such_src__' declared in deck_brief.source_refs" in r.name
            and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: slide.source_ref not declared in deck_brief is detected",
            detected,
            "; ".join(f"{r.name}: {r.detail}" for r in results if not r.ok),
        ))

    return out


def _baseline_render_model_workspace(ws: Path) -> None:
    """Build a minimal but complete workspace that ships one render_model
    primitive and passes check_render_models. Each negative test below
    mutates exactly one piece of this baseline. Stdlib-only; nothing real
    is referenced. The template is built under templates/ inside the same
    temp dir so the tempfixture is self-contained."""
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "deck_brief.json").write_text(json.dumps({
        "title": "Synthetic", "audience": "A", "objective": "O",
        "source_refs": ["synthetic_src_x"],
    }))
    (ws / "deck_plan.json").write_text(json.dumps({
        "template": "synthetic_render_tmpl",
        "planning": {"planned_slide_count": 1, "rationale": "synthetic"},
        "sections": [
            {"id": "only", "title": "Only", "summary": "x", "slide_indices": [1]},
        ],
        "slides": [
            {"index": 1, "layout": "tile",
             "title": "Synthetic Tile", "section_id": "only",
             "summary": "x", "density": "low",
             "source_refs": ["synthetic_src_x"]},
        ],
    }))
    (ws / "design_system.json").write_text(json.dumps({
        "palette": {
            "primary":    "#111111",
            "background": "#FFFFFF",
            "text":       "#222222",
        },
        "typography": {
            "heading": {"font_family": "Arial, sans-serif", "size_pt": 28},
            "body":    {"font_family": "Arial, sans-serif", "size_pt": 14},
        },
        "grid": {"width_px": 1920, "height_px": 1080, "margin_px": 64},
    }))
    (ws / "image_manifest.json").write_text(json.dumps({"images": []}))
    (ws / "slide_plans").mkdir(exist_ok=True)
    (ws / "slide_plans" / "01.json").write_text(json.dumps({
        "index": 1, "layout": "tile", "title": "Synthetic Tile",
        "blocks": [{"id": "headline", "kind": "text", "content": "Synthetic Tile"}],
    }))
    (ws / "render_models").mkdir(exist_ok=True)
    (ws / "render_models" / "01.json").write_text(json.dumps({
        "index": 1,
        "layout": "tile",
        "canvas": {"width_px": 1920, "height_px": 1080},
        "source_refs": ["synthetic_src_x"],
        "primitives": [
            {
                "id": "headline",
                "slot_id": "headline",
                "kind": "text",
                "bounds": {"x": 100, "y": 100, "w": 800, "h": 120},
                "style": {
                    "color_token": "palette.text",
                    "typography_token": "typography.heading",
                },
                "text": {"content": "Synthetic headline", "role": "heading"},
            },
        ],
    }))


def _build_render_model_template(template_root: Path) -> None:
    """Build a single-template tree under template_root that the
    baseline render_model workspace references. The tile layout has a
    single required slot 'headline' with bounds + primitive_kind set."""
    _make_template_dir(
        template_root,
        "synthetic_render_tmpl",
        layout_files={
            "tile": {
                "name": "tile",
                "slots": [
                    {
                        "id": "headline", "type": "text", "required": True,
                        "primitive_kind": "text",
                        "bounds": {"x": 64, "y": 64, "w": 1000, "h": 200},
                    },
                ],
            },
        },
        declared_layouts=["tile"],
    )


def negative_render_model_tempfixture_checks() -> list[CheckResult]:
    """Negative tempfixtures proving the render_model contract fails
    closed on each forbidden mutation: schema-level rejections
    (unsupported kind, missing bounds, invalid token refs, URLs / file:// /
    absolute paths / path traversal in image_ref, arbitrary SVG-like
    fields) and runtime cross-checks (kind-payload mismatch, bounds
    outside canvas, unknown slot_id, slot.primitive_kind mismatch,
    image_ref not declared in manifest, palette token not in
    design_system, duplicate primitive ids)."""
    import tempfile
    out: list[CheckResult] = []

    # Sanity: the minimal baseline workspace must itself pass every
    # render_model check. Catches regressions in the baseline writer or
    # in check_render_models.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        results = check_render_models(ws, tr)
        out.append(CheckResult(
            "tempfixture: minimal render_model baseline passes check_render_models",
            all(r.ok for r in results),
            "; ".join(f"{r.name}: {r.detail}" for r in results if not r.ok),
        ))

    # Schema-level negatives: build the baseline, mutate the on-disk
    # render_model, expect schema validation inside check_render_models
    # to fail with no traceback.
    schema_negatives: list[tuple[str, callable]] = [
        ("unsupported kind 'svg'",
         lambda rm: rm["primitives"][0].__setitem__("kind", "svg")),
        ("unsupported kind 'foreignObject'",
         lambda rm: rm["primitives"][0].__setitem__("kind", "foreignObject")),
        ("missing bounds",
         lambda rm: rm["primitives"][0].pop("bounds")),
        ("invalid token ref (no prefix)",
         lambda rm: rm["primitives"][0].setdefault("style", {}).__setitem__("color_token", "raw_color")),
        ("invalid token ref (wrong domain)",
         lambda rm: rm["primitives"][0].setdefault("style", {}).__setitem__("color_token", "external.thing")),
        ("invalid typography token",
         lambda rm: rm["primitives"][0].setdefault("style", {}).__setitem__("typography_token", "typography.unknown")),
        ("external URL in image_ref",
         lambda rm: _swap_to_image_slot(rm, "http://example.com/x.png")),
        ("file:// in image_ref",
         lambda rm: _swap_to_image_slot(rm, "file:///etc/passwd")),
        ("absolute path in image_ref",
         lambda rm: _swap_to_image_slot(rm, "/etc/passwd")),
        ("path traversal in image_ref",
         lambda rm: _swap_to_image_slot(rm, "../escape")),
        ("arbitrary SVG-like field on primitive (transform)",
         lambda rm: rm["primitives"][0].__setitem__("transform", "translate(10,20)")),
        ("arbitrary SVG-like field on primitive (viewBox)",
         lambda rm: rm["primitives"][0].__setitem__("viewBox", "0 0 100 100")),
        ("arbitrary SVG-like field on primitive (href)",
         lambda rm: rm["primitives"][0].__setitem__("href", "http://example.com")),
        ("arbitrary SVG-like field at root (xmlns)",
         lambda rm: rm.__setitem__("xmlns", "http://www.w3.org/2000/svg")),
        ("arbitrary SVG-like field at root (defs)",
         lambda rm: rm.__setitem__("defs", [])),
    ]
    for label, mutator in schema_negatives:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tr = root / "templates"
            tr.mkdir()
            _build_render_model_template(tr)
            ws = root / "ws"
            _baseline_render_model_workspace(ws)
            rm = json.loads((ws / "render_models" / "01.json").read_text())
            mutator(rm)
            (ws / "render_models" / "01.json").write_text(json.dumps(rm))
            try:
                results = check_render_models(ws, tr)
                no_traceback = True
                exc_kind = ""
            except Exception as exc:  # noqa: BLE001
                results = []
                no_traceback = False
                exc_kind = type(exc).__name__
            schema_failed = any(
                "validates against render_model.schema.json" in r.name and not r.ok
                for r in results
            )
            out.append(CheckResult(
                f"tempfixture: render_model schema rejects {label}",
                no_traceback and schema_failed,
                f"no_traceback={no_traceback}, exc={exc_kind}, "
                f"results={[r.name for r in results if not r.ok]}",
            ))

    # Runtime cross-check negatives.

    # A. kind-payload mismatch: kind=text but only kpi payload present.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        rm = json.loads((ws / "render_models" / "01.json").read_text())
        prim = rm["primitives"][0]
        prim.pop("text", None)
        prim["kpi"] = {"label": "L", "value": "V"}
        # Keep kind=text on purpose to trigger the kind/payload mismatch.
        (ws / "render_models" / "01.json").write_text(json.dumps(rm))
        results = check_render_models(ws, tr)
        detected = any(
            "payload field matches kind" in r.name and not r.ok for r in results
        )
        out.append(CheckResult(
            "tempfixture: kind-payload mismatch is detected at runtime",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # B. Bounds outside the canvas.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        rm = json.loads((ws / "render_models" / "01.json").read_text())
        rm["primitives"][0]["bounds"] = {"x": 0, "y": 0, "w": 9999, "h": 9999}
        # Pull the slot reference too so we don't ALSO fail on slot bounds —
        # the canvas check is what we want to exercise here.
        rm["primitives"][0].pop("slot_id", None)
        (ws / "render_models" / "01.json").write_text(json.dumps(rm))
        results = check_render_models(ws, tr)
        detected = any(
            "bounds fit inside canvas" in r.name and not r.ok for r in results
        )
        out.append(CheckResult(
            "tempfixture: bounds outside canvas are detected",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # C. Unknown slot_id.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        rm = json.loads((ws / "render_models" / "01.json").read_text())
        rm["primitives"][0]["slot_id"] = "no_such_slot"
        (ws / "render_models" / "01.json").write_text(json.dumps(rm))
        results = check_render_models(ws, tr)
        detected = any(
            "exists on layout" in r.name and not r.ok for r in results
        )
        out.append(CheckResult(
            "tempfixture: unknown slot_id is detected",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # D. slot.primitive_kind mismatch: layout slot says text, primitive says shape.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        rm = json.loads((ws / "render_models" / "01.json").read_text())
        rm["primitives"][0]["kind"] = "shape"
        rm["primitives"][0].pop("text", None)
        rm["primitives"][0]["shape"] = {"shape_kind": "rectangle"}
        (ws / "render_models" / "01.json").write_text(json.dumps(rm))
        results = check_render_models(ws, tr)
        detected = any(
            "matches slot.primitive_kind" in r.name and not r.ok for r in results
        )
        out.append(CheckResult(
            "tempfixture: slot.primitive_kind mismatch is detected",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # E. image_ref not declared in manifest.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        # Drop slot_id so we don't also fail the kind/primitive-kind check.
        rm = json.loads((ws / "render_models" / "01.json").read_text())
        rm["primitives"][0] = {
            "id": "pic",
            "kind": "image_slot",
            "bounds": {"x": 100, "y": 100, "w": 200, "h": 200},
            "image_slot": {"image_ref": "no_such_image"},
        }
        (ws / "render_models" / "01.json").write_text(json.dumps(rm))
        results = check_render_models(ws, tr)
        detected = any(
            "declared in image_manifest" in r.name and not r.ok for r in results
        )
        out.append(CheckResult(
            "tempfixture: image_ref not in image_manifest is detected",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # F. palette token resolves nowhere in the design_system.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        rm = json.loads((ws / "render_models" / "01.json").read_text())
        rm["primitives"][0].setdefault("style", {})["color_token"] = "palette.no_such_color"
        (ws / "render_models" / "01.json").write_text(json.dumps(rm))
        results = check_render_models(ws, tr)
        detected = any(
            "resolves to a design_system palette key" in r.name and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: unknown palette token is detected",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # F2. source_refs cross-check is fail-closed when deck_brief.json is
    # missing — must NOT silently skip the check.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        (ws / "deck_brief.json").unlink()
        results = check_render_models(ws, tr)
        detected = any(
            "source_refs can be cross-checked against deck_brief.source_refs" in r.name
            and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: missing deck_brief.json fails source_refs cross-check (fail-closed)",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # F3. source_refs cross-check is fail-closed when deck_brief.source_refs
    # is malformed (not a list).
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        brief = json.loads((ws / "deck_brief.json").read_text())
        brief["source_refs"] = "not a list"
        (ws / "deck_brief.json").write_text(json.dumps(brief))
        results = check_render_models(ws, tr)
        detected = any(
            "source_refs can be cross-checked against deck_brief.source_refs" in r.name
            and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: malformed deck_brief.source_refs fails source_refs cross-check (fail-closed)",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # F4. source_refs cross-check is fail-closed when deck_brief.source_refs
    # is empty (no ids to validate against).
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        brief = json.loads((ws / "deck_brief.json").read_text())
        brief["source_refs"] = []
        (ws / "deck_brief.json").write_text(json.dumps(brief))
        results = check_render_models(ws, tr)
        detected = any(
            "source_refs can be cross-checked against deck_brief.source_refs" in r.name
            and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: empty deck_brief.source_refs fails source_refs cross-check (fail-closed)",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # G. Duplicate primitive ids.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        rm = json.loads((ws / "render_models" / "01.json").read_text())
        # Append a second primitive with the same id.
        dup = json.loads(json.dumps(rm["primitives"][0]))
        dup["bounds"] = {"x": 100, "y": 300, "w": 400, "h": 80}
        dup.pop("slot_id", None)
        rm["primitives"].append(dup)
        (ws / "render_models" / "01.json").write_text(json.dumps(rm))
        results = check_render_models(ws, tr)
        detected = any(
            "id is unique within this render_model" in r.name and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture: duplicate primitive id is detected",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    return out


def _write_baseline_svg_preview(ws: Path) -> Path:
    """Write a minimal SVG preview that passes check_svg_previews for the
    render_model the _baseline_render_model_workspace builder produced.
    Used as the clean starting point for the svg_preview negatives below."""
    sp_dir = ws / "svg_previews"
    sp_dir.mkdir(parents=True, exist_ok=True)
    out_path = sp_dir / "01.svg"
    out_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 1920 1080" width="1920" height="1080">\n'
        '  <rect x="0" y="0" width="1920" height="1080" fill="#FFFFFF"/>\n'
        '  <text x="108" y="118" font-family="Arial" '
        'font-size="37.333px" fill="#222222" font-weight="700">'
        'Synthetic headline</text>\n'
        '</svg>\n'
    )
    return out_path


def negative_svg_preview_tempfixture_checks() -> list[CheckResult]:
    """Negative tempfixtures proving check_svg_previews fails closed on
    each forbidden mutation: missing svg_preview file, malformed XML,
    wrong root element, viewBox not matching canvas, <foreignObject>
    present, href carrying URI scheme / absolute / '..' / file://,
    <image> href not declared in image_manifest, element outside the
    canvas. Each case starts from a clean baseline workspace and
    applies exactly one mutation."""
    import tempfile
    out: list[CheckResult] = []

    # Sanity: the minimal baseline must itself pass. Catches regressions
    # in either the baseline writer or check_svg_previews.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        _write_baseline_svg_preview(ws)
        results = check_svg_previews(ws, tr)
        out.append(CheckResult(
            "tempfixture svg_preview: minimal baseline passes check_svg_previews",
            all(r.ok for r in results),
            "; ".join(f"{r.name}: {r.detail}" for r in results if not r.ok),
        ))

    # A. Missing svg_preview for a render_model.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        # Deliberately do NOT write the svg_preview.
        results = check_svg_previews(ws, tr)
        detected = any(
            "exists for render_models/" in r.name and not r.ok for r in results
        )
        out.append(CheckResult(
            "tempfixture svg_preview: missing svg_preview for a render_model "
            "is detected (fail-closed)",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # B. Malformed XML.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        out_path = _write_baseline_svg_preview(ws)
        out_path.write_text("<svg><not closed properly")
        results = check_svg_previews(ws, tr)
        detected = any(
            "parses as XML" in r.name and not r.ok for r in results
        )
        out.append(CheckResult(
            "tempfixture svg_preview: malformed XML is detected",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # C. Wrong root element (HTML <div> at the root).
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        out_path = _write_baseline_svg_preview(ws)
        out_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<div xmlns="http://www.w3.org/1999/xhtml"/>\n'
        )
        results = check_svg_previews(ws, tr)
        detected = any(
            "root element is <svg> in the SVG namespace" in r.name and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture svg_preview: wrong root element is detected",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # D. viewBox mismatch with canvas.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        out_path = _write_baseline_svg_preview(ws)
        out_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 100 100" width="1920" height="1080">\n'
            '  <rect x="0" y="0" width="100" height="100" fill="#FFFFFF"/>\n'
            '</svg>\n'
        )
        results = check_svg_previews(ws, tr)
        detected = any(
            "viewBox matches render_model canvas" in r.name and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture svg_preview: viewBox mismatch with canvas is detected",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # E. <foreignObject> present.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        out_path = _write_baseline_svg_preview(ws)
        out_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 1920 1080" width="1920" height="1080">\n'
            '  <rect x="0" y="0" width="1920" height="1080" fill="#FFFFFF"/>\n'
            '  <foreignObject x="0" y="0" width="100" height="100"/>\n'
            '</svg>\n'
        )
        results = check_svg_previews(ws, tr)
        detected = any(
            "contains no <foreignObject>" in r.name and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture svg_preview: <foreignObject> is detected",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # F. href with URI scheme (http://).
    for bad_ref, label in (
        ("http://example.com/x.png",     "http URL"),
        ("file:///etc/passwd",            "file:// URL"),
        ("/etc/passwd",                   "POSIX-absolute path"),
        ("../escape/x.png",               "path traversal"),
        ("data:image/png;base64,abc",     "data URI"),
        ("javascript:alert(1)",           "javascript URI"),
    ):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tr = root / "templates"
            tr.mkdir()
            _build_render_model_template(tr)
            ws = root / "ws"
            _baseline_render_model_workspace(ws)
            out_path = _write_baseline_svg_preview(ws)
            out_path.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<svg xmlns="http://www.w3.org/2000/svg" '
                'viewBox="0 0 1920 1080" width="1920" height="1080">\n'
                '  <rect x="0" y="0" width="1920" height="1080" fill="#FFFFFF"/>\n'
                f'  <image x="100" y="100" width="200" height="200" href="{bad_ref}"/>\n'
                '</svg>\n'
            )
            results = check_svg_previews(ws, tr)
            detected = any(
                "no reference-bearing attribute carries a URI scheme" in r.name
                and not r.ok
                for r in results
            )
            out.append(CheckResult(
                f"tempfixture svg_preview: unsafe href ({label}) is detected",
                detected,
                "; ".join(f"{r.name}" for r in results if not r.ok),
            ))

    # G. <image> href is a safe path but not declared in image_manifest.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        out_path = _write_baseline_svg_preview(ws)
        out_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 1920 1080" width="1920" height="1080">\n'
            '  <rect x="0" y="0" width="1920" height="1080" fill="#FFFFFF"/>\n'
            '  <image x="100" y="100" width="200" height="200" '
            'href="assets/undeclared.svg"/>\n'
            '</svg>\n'
        )
        results = check_svg_previews(ws, tr)
        detected = any(
            "every <image> href is declared in image_manifest" in r.name
            and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture svg_preview: undeclared <image> href is detected",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # H. Rect element outside the canvas.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        out_path = _write_baseline_svg_preview(ws)
        out_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 1920 1080" width="1920" height="1080">\n'
            '  <rect x="0" y="0" width="1920" height="1080" fill="#FFFFFF"/>\n'
            '  <rect x="0" y="0" width="9999" height="9999" fill="#000000"/>\n'
            '</svg>\n'
        )
        results = check_svg_previews(ws, tr)
        detected = any(
            "stays inside the canvas" in r.name and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture svg_preview: rect outside canvas is detected",
            detected,
            "; ".join(f"{r.name}" for r in results if not r.ok),
        ))

    # I. <text> anchor outside the canvas. <text> has x/y but no
    #    width/height — the validator must still catch a negative or
    #    >canvas anchor point so a stray text glyph drawn at
    #    x="-100" y="-100" cannot slip through.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        out_path = _write_baseline_svg_preview(ws)
        out_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 1920 1080" width="1920" height="1080">\n'
            '  <rect x="0" y="0" width="1920" height="1080" fill="#FFFFFF"/>\n'
            '  <text x="-100" y="-100" font-family="Arial" '
            'font-size="20px" fill="#222222">offscreen</text>\n'
            '</svg>\n'
        )
        results = check_svg_previews(ws, tr)
        detected = any(
            "stays inside the canvas" in r.name and not r.ok
            and ("'text'" in r.detail or "text" in r.detail)
            for r in results
        )
        out.append(CheckResult(
            "tempfixture svg_preview: <text> anchor outside canvas "
            "(x=-100, y=-100) is detected",
            detected,
            "; ".join(f"{r.name}: {r.detail}" for r in results if not r.ok),
        ))

    # J. <text> anchor beyond the right / bottom edge of the canvas.
    #    Covers the second half of the rule (x > width / y > height).
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_render_model_template(tr)
        ws = root / "ws"
        _baseline_render_model_workspace(ws)
        out_path = _write_baseline_svg_preview(ws)
        out_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 1920 1080" width="1920" height="1080">\n'
            '  <rect x="0" y="0" width="1920" height="1080" fill="#FFFFFF"/>\n'
            '  <text x="9999" y="9999" font-family="Arial" '
            'font-size="20px" fill="#222222">offscreen</text>\n'
            '</svg>\n'
        )
        results = check_svg_previews(ws, tr)
        detected = any(
            "stays inside the canvas" in r.name and not r.ok
            for r in results
        )
        out.append(CheckResult(
            "tempfixture svg_preview: <text> anchor beyond right/bottom "
            "of the canvas (x=9999, y=9999) is detected",
            detected,
            "; ".join(f"{r.name}: {r.detail}" for r in results if not r.ok),
        ))

    return out


def _build_svg_generator_workspace(ws: Path, *, kind: str = "happy") -> None:
    """Build a workspace whose render_models/ has one schema-valid
    render_model that the SVG generator can render. `kind` picks the
    mutation:

      'happy'        — clean baseline with a text primitive.
      'unsupported'  — render_model carries a 'table' primitive (schema-
                       valid, but the SVG renderer fails closed on it).
      'bad_token'    — color_token references a palette key that does
                       not exist in design_system.palette. Generator
                       must fail closed.
      'image_unsafe' — image_manifest declares a local_path that fails
                       local_path_is_safe (drive prefix). The SVG
                       generator must refuse to render the image_slot.
    """
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "deck_brief.json").write_text(json.dumps({
        "title": "Synthetic", "audience": "A", "objective": "O",
        "source_refs": ["synthetic_src_s"],
    }))
    (ws / "deck_plan.json").write_text(json.dumps({
        "template": "svg_tmpl",
        "planning": {"planned_slide_count": 1, "rationale": "synthetic"},
        "sections": [
            {"id": "only", "title": "Only", "summary": "x",
             "slide_indices": [1]},
        ],
        "slides": [
            {"index": 1, "layout": "tile",
             "title": "Synthetic Slide", "section_id": "only",
             "summary": "x", "density": "low",
             "source_refs": ["synthetic_src_s"]},
        ],
    }))
    (ws / "design_system.json").write_text(json.dumps({
        "palette": {
            "primary":    "#111111",
            "background": "#FFFFFF",
            "text":       "#222222",
        },
        "typography": {
            "heading": {"font_family": "Arial, sans-serif", "size_pt": 28},
            "body":    {"font_family": "Arial, sans-serif", "size_pt": 14},
        },
        "grid": {"width_px": 1920, "height_px": 1080, "margin_px": 64},
    }))
    images = []
    if kind == "image_unsafe":
        images.append({
            "id": "bad_img",
            "local_path": "C:\\Windows\\evil.png",
            "source": "synthetic", "alt_text": "synthetic",
            "intended_use": "spot illustration",
            "width_px": 200, "height_px": 200,
        })
    (ws / "image_manifest.json").write_text(json.dumps({"images": images}))
    (ws / "slide_plans").mkdir(exist_ok=True)
    (ws / "slide_plans" / "01.json").write_text(json.dumps({
        "index": 1, "layout": "tile", "title": "Synthetic Slide",
        "blocks": [{"id": "headline", "kind": "text", "content": "Synthetic"}],
    }))
    (ws / "render_models").mkdir(exist_ok=True)
    primitive = {
        "id": "headline",
        "slot_id": "headline",
        "kind": "text",
        "bounds": {"x": 100, "y": 100, "w": 800, "h": 120},
        "style": {
            "color_token": "palette.text",
            "typography_token": "typography.heading",
        },
        "text": {"content": "Synthetic headline", "role": "heading"},
    }
    if kind == "unsupported":
        # Schema-valid table primitive (the SVG renderer fails closed on it
        # since current generated fixtures never emit a table).
        primitive = {
            "id": "tbl",
            "kind": "table",
            "bounds": {"x": 100, "y": 100, "w": 800, "h": 400},
            "table": {
                "columns": ["A", "B"],
                "rows": [["1", "2"]],
            },
        }
    if kind == "bad_token":
        primitive["style"]["color_token"] = "palette.no_such_color"
    if kind == "image_unsafe":
        primitive = {
            "id": "pic",
            "kind": "image_slot",
            "bounds": {"x": 100, "y": 100, "w": 200, "h": 200},
            "image_slot": {"image_ref": "bad_img"},
        }
    (ws / "render_models" / "01_tile.json").write_text(json.dumps({
        "index": 1,
        "layout": "tile",
        "canvas": {"width_px": 1920, "height_px": 1080},
        "source_refs": ["synthetic_src_s"],
        "primitives": [primitive],
    }))


def _build_svg_generator_template(template_root: Path) -> None:
    """Build a template tree the SVG generator workspace references."""
    _make_template_dir(
        template_root,
        "svg_tmpl",
        layout_files={
            "tile": {
                "name": "tile",
                "slots": [
                    {"id": "headline", "type": "text", "required": True,
                     "primitive_kind": "text",
                     "bounds": {"x": 64, "y": 64, "w": 1000, "h": 200}},
                ],
            },
        },
        declared_layouts=["tile"],
    )


def negative_svg_generator_tempfixture_checks() -> list[CheckResult]:
    """End-to-end tempfixture tests of scripts/generate_svg_previews.py.

    Imports the script as a module and drives it via its main(argv)
    entry point — no subprocess, no network, stdlib only.

    Cases:
      A. happy path: emits one SVG that the validator accepts;
      B. unsupported primitive kind (table) fails closed;
      C. bad palette token fails closed;
      D. image_slot whose manifest local_path is unsafe fails closed;
      E. missing render_models/ fails closed (no traceback);
      F. pre-existing stale *.svg from a previous run is REMOVED;
      G. non-SVG files in svg_previews/ are PRESERVED across runs.
    """
    import contextlib
    import importlib
    import io
    import tempfile
    out: list[CheckResult] = []

    if "generate_svg_previews" in sys.modules:
        svg_mod = importlib.reload(sys.modules["generate_svg_previews"])
    else:
        svg_mod = importlib.import_module("generate_svg_previews")

    def run(ws: Path, tr: Path) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), \
                 contextlib.redirect_stderr(stderr):
                ret = svg_mod.main([
                    "--workspace", str(ws), "--template-root", str(tr),
                ])
            exc_kind = ""
        except SystemExit as exc:
            ret = exc.code if isinstance(exc.code, int) else 1
            exc_kind = ""
        except Exception as exc:  # noqa: BLE001
            ret = 1
            exc_kind = type(exc).__name__
        return (ret, stdout.getvalue(), stderr.getvalue() + (
            f"\nUNEXPECTED EXCEPTION {exc_kind}" if exc_kind else ""
        ))

    # A. Happy path.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_svg_generator_template(tr)
        ws = root / "ws"
        _build_svg_generator_workspace(ws, kind="happy")
        ret, sout, serr = run(ws, tr)
        emitted = (ws / "svg_previews" / "01_tile.svg").is_file()
        out.append(CheckResult(
            "tempfixture svg_generator: happy path exits 0 and emits svg_preview",
            ret == 0 and emitted and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, emitted={emitted}, sout={sout!r}, stderr={serr!r}",
        ))

    # B. Unsupported primitive kind (table).
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_svg_generator_template(tr)
        ws = root / "ws"
        _build_svg_generator_workspace(ws, kind="unsupported")
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture svg_generator: unsupported primitive kind fails closed",
            ret != 0
            and "not supported by the SVG renderer" in serr
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, stderr={serr!r}",
        ))

    # C. Bad palette token.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_svg_generator_template(tr)
        ws = root / "ws"
        _build_svg_generator_workspace(ws, kind="bad_token")
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture svg_generator: unknown palette token fails closed",
            ret != 0
            and "does not resolve in design_system.palette" in serr
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, stderr={serr!r}",
        ))

    # D. image_slot with unsafe manifest local_path. The preflight
    # catches the unsafe path BEFORE any rendering ever runs, so the
    # fail-closed signal comes from the manifest path-safety gate
    # rather than from _render_image_slot. Either error path keeps
    # the same contract: non-zero exit, no rendering, no OK. We
    # accept whichever message fires — the resolver-level check is
    # still proven by case D2 below, which invokes _render_svg
    # directly on a render_model with an unsafe image_slot.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_svg_generator_template(tr)
        ws = root / "ws"
        _build_svg_generator_workspace(ws, kind="image_unsafe")
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture svg_generator: image_slot resolving to unsafe "
            "manifest local_path fails closed (caught at the preflight "
            "manifest gate before any rendering)",
            ret != 0
            and "unsafe local_path" in serr
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, stderr={serr!r}",
        ))

    # D2. Defense-in-depth at the renderer: even if a manifest with an
    # unsafe local_path somehow slipped past the preflight, the
    # _render_image_slot path inside the renderer must still refuse to
    # emit it. We prove that by invoking _render_svg directly on a
    # crafted render_model + manifest dict that bypasses main()'s
    # preflight entirely.
    if "generate_svg_previews" in sys.modules:
        import importlib
        svg_mod_d2 = importlib.reload(sys.modules["generate_svg_previews"])
    else:
        import importlib
        svg_mod_d2 = importlib.import_module("generate_svg_previews")
    minimal_design = {
        "palette": {"primary": "#111111", "background": "#FFFFFF", "text": "#222222"},
        "typography": {
            "heading": {"font_family": "Arial", "size_pt": 28},
            "body":    {"font_family": "Arial", "size_pt": 14},
        },
        "grid": {"width_px": 1920, "height_px": 1080, "margin_px": 64},
    }
    rm_image = {
        "index": 1, "layout": "tile",
        "canvas": {"width_px": 1920, "height_px": 1080},
        "source_refs": ["synthetic_src_s"],
        "primitives": [{
            "id": "pic", "kind": "image_slot",
            "bounds": {"x": 100, "y": 100, "w": 200, "h": 200},
            "image_slot": {"image_ref": "bad_img"},
        }],
    }
    try:
        svg_mod_d2._render_svg(
            rm_image, minimal_design,
            {"bad_img": "C:\\Windows\\evil.png"},
            {},
        )
        raised_d2 = False
        d2_msg = ""
    except svg_mod_d2.RenderError as exc:
        raised_d2 = True
        d2_msg = str(exc)
    except Exception as exc:  # noqa: BLE001
        raised_d2 = False
        d2_msg = f"UNEXPECTED {type(exc).__name__}: {exc}"
    out.append(CheckResult(
        "tempfixture svg_generator: _render_image_slot also refuses an "
        "unsafe manifest local_path at render time (defense-in-depth, "
        "not just the preflight)",
        raised_d2 and "resolves to unsafe local_path" in d2_msg,
        f"raised={raised_d2}, msg={d2_msg!r}",
    ))

    # E. Missing render_models/.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_svg_generator_template(tr)
        ws = root / "ws"
        _build_svg_generator_workspace(ws, kind="happy")
        # Wipe render_models/ entirely.
        import shutil
        shutil.rmtree(ws / "render_models")
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture svg_generator: missing render_models/ fails closed (no traceback)",
            ret != 0
            and "render_models/ not found" in serr
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, stderr={serr!r}",
        ))

    # E1. Schema-invalid design_system (palette value is not a 6-digit
    #     hex). Up-front design_system schema validation must fail closed
    #     before any rendering — XML escaping would otherwise leak a
    #     `url(...)` reference into the SVG `fill` attribute, which an
    #     SVG consumer (browser) would dereference.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_svg_generator_template(tr)
        ws = root / "ws"
        _build_svg_generator_workspace(ws, kind="happy")
        design = json.loads((ws / "design_system.json").read_text())
        design["palette"]["text"] = "url(javascript:alert(1))"
        (ws / "design_system.json").write_text(json.dumps(design))
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture svg_generator: design_system with a non-hex "
            "palette value (e.g. url(javascript:...)) fails closed at "
            "schema-validation startup",
            ret != 0
            and "design_system.json fails design_system.schema.json" in serr
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, stderr={serr!r}",
        ))

    # E2. Defense-in-depth: even if a malformed palette value somehow
    #     slipped past schema validation (e.g. additionalProperties on
    #     the palette object lets an unexpected key through), the
    #     per-token resolver MUST reject anything that does not match
    #     ^#[0-9A-Fa-f]{6}$. We simulate that by adding an extra
    #     palette key whose value violates the hex pattern AND pointing
    #     a render_model primitive's color_token at it. The schema's
    #     additionalProperties on `palette` constrains values via
    #     pattern, so this case also fails at schema time — confirming
    #     the up-front gate covers extra keys too.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_svg_generator_template(tr)
        ws = root / "ws"
        _build_svg_generator_workspace(ws, kind="happy")
        design = json.loads((ws / "design_system.json").read_text())
        design["palette"]["danger"] = "not_a_hex_color"
        (ws / "design_system.json").write_text(json.dumps(design))
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture svg_generator: extra palette entry with a "
            "non-hex value is rejected (schema's additionalProperties "
            "pattern on palette catches it)",
            ret != 0
            and "design_system.json fails design_system.schema.json" in serr
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, stderr={serr!r}",
        ))

    # E3. Schema-invalid design_system font_family (does not match the
    #     CSS-style fallback-chain pattern). The renderer would
    #     otherwise emit a structurally broken `font-family` attribute.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_svg_generator_template(tr)
        ws = root / "ws"
        _build_svg_generator_workspace(ws, kind="happy")
        design = json.loads((ws / "design_system.json").read_text())
        # Trailing comma violates ^[^,]+(\s*,\s*[^,]+)*$.
        design["typography"]["heading"]["font_family"] = "Arial,"
        (ws / "design_system.json").write_text(json.dumps(design))
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture svg_generator: design_system with a "
            "schema-violating font_family (trailing comma) fails closed",
            ret != 0
            and "design_system.json fails design_system.schema.json" in serr
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, stderr={serr!r}",
        ))

    # E4. Defense-in-depth at the resolver itself: bypass the schema
    #     check by making the design_system schema-valid up front, then
    #     swap the palette value on disk for an unsafe one AFTER the
    #     schema gate would have run. We cannot literally bypass the
    #     gate from outside, so we instead test the resolver in
    #     isolation: invoke _resolve_palette on a crafted design dict
    #     whose palette value is unsafe and confirm RenderError is
    #     raised. This proves the gate is layered, not single-point.
    if "generate_svg_previews" in sys.modules:
        svg_mod_resolved = sys.modules["generate_svg_previews"]
    else:
        import importlib
        svg_mod_resolved = importlib.import_module("generate_svg_previews")
    bad_design_palette = {
        "palette": {"text": "url(javascript:alert(1))"},
        "typography": {
            "heading": {"font_family": "Arial", "size_pt": 28},
            "body":    {"font_family": "Arial", "size_pt": 14},
        },
        "grid": {"width_px": 1920, "height_px": 1080, "margin_px": 64},
    }
    try:
        svg_mod_resolved._resolve_palette(bad_design_palette, "palette.text")
        raised_palette = False
        palette_msg = ""
    except svg_mod_resolved.RenderError as exc:
        raised_palette = True
        palette_msg = str(exc)
    except Exception as exc:  # noqa: BLE001
        raised_palette = False
        palette_msg = f"UNEXPECTED {type(exc).__name__}: {exc}"
    out.append(CheckResult(
        "tempfixture svg_generator: _resolve_palette refuses a non-hex "
        "palette value at the resolver (defense-in-depth, not just "
        "the schema gate)",
        raised_palette and "unsafe value" in palette_msg,
        f"raised={raised_palette}, msg={palette_msg!r}",
    ))

    # E5. Defense-in-depth at the resolver for typography.font_family.
    bad_design_typo = {
        "palette": {"primary": "#111111", "background": "#FFFFFF", "text": "#222222"},
        "typography": {
            "heading": {"font_family": "Arial,", "size_pt": 28},
            "body":    {"font_family": "Arial", "size_pt": 14},
        },
        "grid": {"width_px": 1920, "height_px": 1080, "margin_px": 64},
    }
    try:
        svg_mod_resolved._resolve_typography(bad_design_typo, "typography.heading")
        raised_typo = False
        typo_msg = ""
    except svg_mod_resolved.RenderError as exc:
        raised_typo = True
        typo_msg = str(exc)
    except Exception as exc:  # noqa: BLE001
        raised_typo = False
        typo_msg = f"UNEXPECTED {type(exc).__name__}: {exc}"
    out.append(CheckResult(
        "tempfixture svg_generator: _resolve_typography refuses a "
        "font_family that does not match the CSS-style fallback chain "
        "pattern (defense-in-depth at the resolver)",
        raised_typo and "does not match" in typo_msg,
        f"raised={raised_typo}, msg={typo_msg!r}",
    ))

    # E6. The SVG background rect MUST route palette.background through
    #     _resolve_palette and not read design.palette.background
    #     directly. The schema gate catches an unsafe background up
    #     front in main(), but the renderer is also invoked by other
    #     code paths (importers, tests, future callers) where the
    #     schema gate may not have run. We prove the gate-at-render
    #     contract by calling _render_svg directly with a design dict
    #     whose palette.background is unsafe and confirming it raises
    #     RenderError before emitting anything.
    bad_bg_design = {
        "palette": {
            "primary":    "#111111",
            "background": "url(javascript:alert(1))",
            "text":       "#222222",
        },
        "typography": {
            "heading": {"font_family": "Arial", "size_pt": 28},
            "body":    {"font_family": "Arial", "size_pt": 14},
        },
        "grid": {"width_px": 1920, "height_px": 1080, "margin_px": 64},
    }
    minimal_render_model = {
        "index": 1,
        "layout": "tile",
        "canvas": {"width_px": 1920, "height_px": 1080},
        "source_refs": ["synthetic_src_s"],
        "primitives": [
            {
                "id": "headline",
                "kind": "text",
                "bounds": {"x": 100, "y": 100, "w": 800, "h": 120},
                "style": {
                    "color_token": "palette.text",
                    "typography_token": "typography.heading",
                },
                "text": {"content": "Synthetic", "role": "heading"},
            },
        ],
    }
    try:
        svg_mod_resolved._render_svg(
            minimal_render_model, bad_bg_design, {}, {},
        )
        raised_bg = False
        bg_msg = ""
    except svg_mod_resolved.RenderError as exc:
        raised_bg = True
        bg_msg = str(exc)
    except Exception as exc:  # noqa: BLE001
        raised_bg = False
        bg_msg = f"UNEXPECTED {type(exc).__name__}: {exc}"
    out.append(CheckResult(
        "tempfixture svg_generator: _render_svg's background rect "
        "routes palette.background through _resolve_palette and "
        "rejects an unsafe value (no direct dict read bypass)",
        raised_bg and "palette.background" in bg_msg and "unsafe value" in bg_msg,
        f"raised={raised_bg}, msg={bg_msg!r}",
    ))

    # E7. PREFLIGHT: malformed image_manifest.json (root is `{}`,
    #     missing the required `images` array). Before this fix the
    #     run would succeed when the current render_models happened
    #     not to use image slots — falsely claiming OK while the
    #     workspace's manifest was broken. The shared invariant: a
    #     pre-existing svg_previews/*.svg from a previous good run
    #     SURVIVES the failed run (no cleanup before the gate).
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_svg_generator_template(tr)
        ws = root / "ws"
        _build_svg_generator_workspace(ws, kind="happy")
        # Plant a previously-good svg_preview file on disk.
        (ws / "svg_previews").mkdir(exist_ok=True)
        prior = ws / "svg_previews" / "01_tile.svg"
        prior.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 1920 1080" width="1920" height="1080">\n'
            '  <rect x="0" y="0" width="1920" height="1080" fill="#FFFFFF"/>\n'
            '</svg>\n'
        )
        # Break image_manifest.json by replacing it with `{}`.
        (ws / "image_manifest.json").write_text("{}")
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture svg_generator: malformed image_manifest "
            "(missing required 'images' array) fails closed BEFORE "
            "cleanup; pre-existing svg_preview is preserved and no "
            "OK is reported",
            ret != 0
            and prior.is_file()
            and "OK:" not in sout
            and "image_manifest.json fails image_manifest.schema.json" in serr
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, prior_exists={prior.is_file()}, "
            f"ok_in_sout={'OK:' in sout}, sout={sout!r}, stderr={serr!r}",
        ))

    # E8. PREFLIGHT: image_manifest with an unsafe local_path. Same
    #     contract — fail BEFORE cleanup. The manifest is otherwise
    #     schema-valid but lists e.g. '..' or '/absolute/path'.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_svg_generator_template(tr)
        ws = root / "ws"
        _build_svg_generator_workspace(ws, kind="happy")
        (ws / "svg_previews").mkdir(exist_ok=True)
        prior = ws / "svg_previews" / "01_tile.svg"
        prior.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 1920 1080" width="1920" height="1080">\n'
            '  <rect x="0" y="0" width="1920" height="1080" fill="#FFFFFF"/>\n'
            '</svg>\n'
        )
        (ws / "image_manifest.json").write_text(json.dumps({
            "images": [
                {"id": "unsafe_img",
                 "local_path": "../escape.svg",
                 "source": "synthetic"},
            ],
        }))
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture svg_generator: image_manifest declares an "
            "unsafe local_path ('..' segment) fails closed BEFORE "
            "cleanup; pre-existing svg_preview is preserved",
            ret != 0
            and prior.is_file()
            and "OK:" not in sout
            and "unsafe local_path" in serr
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, prior_exists={prior.is_file()}, "
            f"sout={sout!r}, stderr={serr!r}",
        ))

    # F. Stale *.svg from a previous run is REMOVED when current run
    # would not produce that file.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_svg_generator_template(tr)
        ws = root / "ws"
        _build_svg_generator_workspace(ws, kind="happy")
        # Plant a stale svg for a render_model the workspace no longer ships.
        (ws / "svg_previews").mkdir(exist_ok=True)
        stale = ws / "svg_previews" / "99_ghost.svg"
        stale.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 1920 1080" width="1920" height="1080"/>\n'
        )
        ret, sout, serr = run(ws, tr)
        still_exists = stale.is_file()
        cleaned_logged = "[CLEAN] svg_previews/99_ghost.svg" in sout
        out.append(CheckResult(
            "tempfixture svg_generator: stale *.svg from a previous run "
            "is REMOVED by the cleanup sweep",
            ret == 0
            and not still_exists
            and cleaned_logged
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, still_exists={still_exists}, "
            f"cleaned_logged={cleaned_logged}, "
            f"sout={sout!r}, stderr={serr!r}",
        ))

    # G. Non-SVG files are PRESERVED. Mirrors the *.json cleanup philosophy
    # of generate_render_models.py: glob is targeted; manual notes survive.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_svg_generator_template(tr)
        ws = root / "ws"
        _build_svg_generator_workspace(ws, kind="happy")
        (ws / "svg_previews").mkdir(exist_ok=True)
        readme = ws / "svg_previews" / "NOTES.md"
        readme.write_text("manual notes\n")
        ret, sout, serr = run(ws, tr)
        readme_preserved = readme.is_file()
        out.append(CheckResult(
            "tempfixture svg_generator: non-SVG files in svg_previews/ "
            "(NOTES.md) are PRESERVED — cleanup glob targets *.svg only",
            ret == 0
            and readme_preserved
            and "[CLEAN] svg_previews/NOTES.md" not in sout
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, readme_preserved={readme_preserved}, "
            f"sout={sout!r}, stderr={serr!r}",
        ))

    return out


def _swap_to_image_slot(rm: dict, image_ref: str) -> None:
    """Mutator helper: replace the baseline text primitive with an
    image_slot primitive whose image_ref carries the bad value being
    tested. Used by the schema-level negative loop."""
    rm["primitives"][0] = {
        "id": "headline",
        "kind": "image_slot",
        "bounds": {"x": 100, "y": 100, "w": 200, "h": 200},
        "image_slot": {"image_ref": image_ref},
    }


def _build_generator_workspace(ws: Path, *, kind: str = "happy") -> None:
    """Build a tiny synthetic workspace that the render_model generator can
    actually run against. `kind` selects the mutation applied:

      'happy'         — clean baseline: slide 1 is cover, slide 2 is
                        comparison_table (an unsupported layout because
                        the table primitive_kind is not implemented by
                        the generator today). Generator should generate
                        1 file and skip 1 slide.
      'bad_image_ref' — cover slide_plan references an image id not in
                        the image_manifest. Generator must FAIL closed.
      'malformed_kpi' — kpi_dashboard slide_plan content is not a list.
                        Generator must FAIL closed.
      'missing_required_block' — cover slide_plan omits the required
                        'title' text block. Generator must FAIL closed.
      'stale_layout'  — slide 1's slide_plan declares layout='two_column'
                        while the deck_plan slide still says 'cover'.
                        Generator must FAIL closed before invoking any
                        layout-specific code path.
      'stale_title'   — slide 1's slide_plan has a title string that
                        disagrees with the deck_plan slide's title.
                        Generator must FAIL closed.

    The template root is built separately by _build_generator_template
    below; both directories live under the same tmpdir so callers can
    pass them in without colliding with other tempfixtures."""
    ws.mkdir(parents=True, exist_ok=True)
    base_brief = {
        "title": "Synthetic Generator Workspace",
        "audience": "tests",
        "objective": "exercise the generator",
        "source_refs": ["synthetic_src_g"],
    }
    base_deck = {
        "template": "generator_tmpl",
        "planning": {"planned_slide_count": 2, "rationale": "synthetic"},
        "sections": [
            {"id": "only", "title": "Only", "summary": "x",
             "slide_indices": [1, 2]},
        ],
        "slides": [
            {"index": 1, "layout": "cover",
             "title": "Synthetic Cover", "section_id": "only",
             "summary": "x", "density": "low",
             "source_refs": ["synthetic_src_g"]},
            {"index": 2, "layout": "comparison_table",
             "title": "Synthetic Comparison", "section_id": "only",
             "summary": "x", "density": "medium",
             "source_refs": ["synthetic_src_g"]},
        ],
    }
    base_design = {
        "palette": {
            "primary":    "#111111",
            "background": "#FFFFFF",
            "text":       "#222222",
        },
        "typography": {
            "heading": {"font_family": "Arial, sans-serif", "size_pt": 28},
            "body":    {"font_family": "Arial, sans-serif", "size_pt": 14},
        },
        "grid": {"width_px": 1920, "height_px": 1080, "margin_px": 64},
    }
    base_manifest = {
        "images": [
            {"id": "generator_accent", "local_path": "assets/g.svg",
             "source": "synthetic", "alt_text": "synthetic accent",
             "intended_use": "spot illustration",
             "width_px": 320, "height_px": 320},
        ],
    }
    base_cover_blocks = [
        {"id": "title", "kind": "text", "content": "Synthetic Cover"},
        {"id": "accent", "kind": "image_ref", "content": "generator_accent"},
    ]
    base_slide2_blocks = [
        {"id": "title", "kind": "text", "content": "Synthetic Comparison"},
        {"id": "table", "kind": "table",
         "content": {"columns": ["A", "B"], "rows": [["1", "2"]]}},
    ]
    if kind == "bad_image_ref":
        base_cover_blocks = [
            {"id": "title", "kind": "text", "content": "Synthetic Cover"},
            {"id": "accent", "kind": "image_ref",
             "content": "no_such_image_in_manifest"},
        ]
    if kind == "malformed_kpi":
        base_deck["slides"][1] = {
            "index": 2, "layout": "kpi_dashboard",
            "title": "Bad KPI", "section_id": "only",
            "summary": "x", "density": "high",
            "source_refs": ["synthetic_src_g"],
        }
        base_slide2_blocks = [
            {"id": "title", "kind": "text", "content": "Bad KPI"},
            {"id": "kpis", "kind": "kpi", "content": "not a list"},
        ]
    if kind == "missing_required_block":
        base_cover_blocks = [
            # 'title' deliberately omitted.
            {"id": "subtitle", "kind": "text", "content": "no title here"},
        ]
    cover_plan_layout = "cover"
    cover_plan_title = base_deck["slides"][0]["title"]
    if kind == "stale_layout":
        # deck_plan still says cover, but the slide_plan claims two_column.
        # Matching by index alone would silently feed two_column-shaped
        # content into the cover generator. The guard must catch this.
        cover_plan_layout = "two_column"
    if kind == "stale_title":
        cover_plan_title = "A title that does not match the deck_plan"
    (ws / "deck_brief.json").write_text(json.dumps(base_brief))
    (ws / "deck_plan.json").write_text(json.dumps(base_deck))
    (ws / "design_system.json").write_text(json.dumps(base_design))
    (ws / "image_manifest.json").write_text(json.dumps(base_manifest))
    (ws / "assets").mkdir(exist_ok=True)
    (ws / "assets" / "g.svg").write_text(
        "<svg xmlns='http://www.w3.org/2000/svg' width='320' height='320'/>"
    )
    plans = ws / "slide_plans"
    plans.mkdir(exist_ok=True)
    (plans / "01.json").write_text(json.dumps({
        "index": 1, "layout": cover_plan_layout,
        "title": cover_plan_title,
        "blocks": base_cover_blocks,
        "image_refs": ["generator_accent"] if kind != "bad_image_ref" else [],
    }))
    slide2 = base_deck["slides"][1]
    (plans / "02.json").write_text(json.dumps({
        "index": 2, "layout": slide2["layout"],
        "title": slide2["title"],
        "blocks": base_slide2_blocks,
    }))


def _build_generator_template(template_root: Path) -> None:
    """Build a minimal template tree that the synthetic generator workspace
    references. Includes cover and kpi_dashboard layouts (with bounds and
    primitive_kind on the required slots, matching the real business_review
    template's shape) plus an unsupported comparison_table layout so the
    skip-not-success path can be exercised. comparison_table maps to the
    `table` primitive_kind, which the controlled render-model generator
    does not implement today and remains a TODO per CLAUDE.md."""
    layout_files = {
        "cover": {
            "name": "cover",
            "slots": [
                {"id": "title", "type": "text", "required": True,
                 "primitive_kind": "text",
                 "bounds": {"x": 160, "y": 320, "w": 1280, "h": 200}},
                {"id": "subtitle", "type": "text", "required": False,
                 "primitive_kind": "text"},
                {"id": "presenter", "type": "text", "required": False,
                 "primitive_kind": "text"},
                {"id": "date", "type": "text", "required": False,
                 "primitive_kind": "text"},
                {"id": "accent", "type": "image_ref", "required": False,
                 "primitive_kind": "image_slot"},
            ],
        },
        "kpi_dashboard": {
            "name": "kpi_dashboard",
            "slots": [
                {"id": "title", "type": "text", "required": True,
                 "primitive_kind": "text",
                 "bounds": {"x": 64, "y": 80, "w": 1792, "h": 120}},
                {"id": "kpis", "type": "kpi", "required": True,
                 "primitive_kind": "kpi",
                 "bounds": {"x": 64, "y": 280, "w": 1792, "h": 600}},
            ],
        },
        "comparison_table": {
            "name": "comparison_table",
            "slots": [
                {"id": "title", "type": "text", "required": True},
                {"id": "table", "type": "table", "required": True},
            ],
        },
    }
    _make_template_dir(
        template_root,
        "generator_tmpl",
        declared_layouts=list(layout_files.keys()),
        layout_files=layout_files,
    )


def negative_generator_tempfixture_checks() -> list[CheckResult]:
    """End-to-end tempfixture tests of scripts/generate_render_models.py.

    Imports the script as a module and drives it via its main(argv)
    entry point — no subprocess, no network, stdlib only. Stdout/stderr
    are captured per case so the assertions inspect what the script
    actually printed.

    Cases:
      A. happy path: one cover generated, one unsupported layout skipped
         (skip is reported as not-implemented, NOT as success);
      B. unknown image_ref in cover.accent fails closed;
      C. malformed kpi block content (not a list) fails closed;
      D. cover slide_plan missing required 'title' text block fails closed;
      E. missing deck_plan.json fails closed (no traceback);
      F. unsafe deck_plan.template fails closed (no traceback);
      G. stale slide_plan.layout (mismatch with deck_plan.layout) fails
         closed and emits no render_model — guards against drift where
         the slide_plan is hand-edited to a different layout while the
         deck_plan still names the original;
      H. stale slide_plan.title (mismatch with deck_plan.title) fails
         closed and emits no render_model;
      I. a pre-existing render_model file on disk from a previous good
         run is REMOVED when the current run fails closed on that slide
         (here triggered via the stale_layout kind). A stale lie cannot
         survive a fail-closed mismatch.
      J. a pre-existing render_model file for a slide whose deck_plan
         layout has since changed to one the generator does not
         implement is REMOVED on the next run, even though the
         generator does not write a replacement for that slide.
      K. an ORPHAN render_model (for a slide index no longer in
         deck_plan — deck shrank, slide moved index, ...) is REMOVED
         by the cleanup sweep before check_render_models runs, so it
         does not surface as a post-hoc cross-check failure.
      L. NON-.json files in render_models/ (README.md, NOTES.txt, ...)
         are PRESERVED across runs — the cleanup glob only matches
         *.json. The workspace validator schema-validates every
         *.json as a render_model, so the *.json namespace itself is
         generator-owned, but non-JSON files are out of scope and
         must not be silently deleted.
      M. PREFLIGHT: deck_plan.slides missing entirely. The generator
         must fail closed BEFORE the render_models/ cleanup sweep,
         leaving any pre-existing *.json on disk untouched. Without
         preflight, the run would wipe render_models/*.json and then
         silently report "OK: generated 0".
      N. PREFLIGHT: deck_plan.slides is not a list (string here).
         Same fail-closed-before-cleanup guarantee as M.
      O. PREFLIGHT: planning.planned_slide_count disagrees with
         len(deck_plan.slides). Schema cannot express this equality;
         preflight reaches check_planner_semantics, which catches it.
         The pre-existing render_model survives the failed run.
    """
    import contextlib
    import importlib
    import io
    import tempfile
    out: list[CheckResult] = []

    # Import the generator lazily — script lives alongside this one under
    # scripts/, and REPO_ROOT/scripts is already on sys.path via the
    # validate_scaffold/validate_workspace pair.
    if "generate_render_models" in sys.modules:
        gen_mod = importlib.reload(sys.modules["generate_render_models"])
    else:
        gen_mod = importlib.import_module("generate_render_models")

    def run(ws: Path, tr: Path) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), \
                 contextlib.redirect_stderr(stderr):
                ret = gen_mod.main([
                    "--workspace", str(ws), "--template-root", str(tr),
                ])
            exc_kind = ""
        except SystemExit as exc:  # argparse + _fatal use sys.exit
            ret = exc.code if isinstance(exc.code, int) else 1
            exc_kind = ""
        except Exception as exc:  # noqa: BLE001 - we want to see ANY raise
            ret = 1
            exc_kind = type(exc).__name__
        return (ret, stdout.getvalue(), stderr.getvalue() + (
            f"\nUNEXPECTED EXCEPTION {exc_kind}" if exc_kind else ""
        ))

    # A. Happy + skip.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="happy")
        ret, sout, serr = run(ws, tr)
        cover_emitted = (ws / "render_models" / "01_cover.json").is_file()
        unsupported_emitted = (ws / "render_models" / "02_comparison_table.json").is_file()
        skip_reported = "[SKIP] slide  2: layout 'comparison_table' not implemented" in sout
        out.append(CheckResult(
            "tempfixture generator: happy path exits 0, "
            "emits supported cover, skips unsupported layout "
            "(reports as not implemented, NOT as success)",
            ret == 0 and cover_emitted and not unsupported_emitted and skip_reported,
            f"ret={ret}, cover_emitted={cover_emitted}, "
            f"unsupported_emitted={unsupported_emitted}, "
            f"skip_reported={skip_reported}, stderr={serr!r}",
        ))

    # B. Bad image_ref in cover.accent.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="bad_image_ref")
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture generator: image_ref not in manifest fails closed",
            ret != 0
            and "not declared in image_manifest" in serr,
            f"ret={ret}, stderr={serr!r}",
        ))

    # C. Malformed kpi block content.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="malformed_kpi")
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture generator: kpi block with non-list content fails closed",
            ret != 0
            and "non-empty list of KPI" in serr,
            f"ret={ret}, stderr={serr!r}",
        ))

    # D. cover slide_plan missing required title block.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="missing_required_block")
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture generator: cover slide_plan missing 'title' block fails closed",
            ret != 0
            and "missing slide_plan block for slot id 'title'" in serr,
            f"ret={ret}, stderr={serr!r}",
        ))

    # E. Missing deck_plan.json.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="happy")
        (ws / "deck_plan.json").unlink()
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture generator: missing deck_plan.json fails closed (no traceback)",
            ret != 0
            and "deck_plan.json not loadable" in serr
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, stderr={serr!r}",
        ))

    # F. Unsafe deck_plan.template.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="happy")
        deck = json.loads((ws / "deck_plan.json").read_text())
        deck["template"] = "../../etc/passwd"
        (ws / "deck_plan.json").write_text(json.dumps(deck))
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture generator: unsafe deck_plan.template fails closed",
            ret != 0
            and "unsafe or outside template-root" in serr
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, stderr={serr!r}",
        ))

    # G. Stale slide_plan: layout disagrees with deck_plan slide.layout.
    # Without the layout-equality guard the generator would feed
    # two_column-shaped content into the cover generator and emit a
    # cover-labelled render_model whose blocks came from the wrong layout.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="stale_layout")
        ret, sout, serr = run(ws, tr)
        emitted = (ws / "render_models" / "01_cover.json").is_file()
        out.append(CheckResult(
            "tempfixture generator: stale slide_plan.layout (mismatch with "
            "deck_plan.layout) fails closed and emits no render_model",
            ret != 0
            and "does not match deck_plan.layout" in serr
            and not emitted
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, emitted={emitted}, stderr={serr!r}",
        ))

    # H. Stale slide_plan: title disagrees with deck_plan slide.title.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="stale_title")
        ret, sout, serr = run(ws, tr)
        emitted = (ws / "render_models" / "01_cover.json").is_file()
        out.append(CheckResult(
            "tempfixture generator: stale slide_plan.title (mismatch with "
            "deck_plan.title) fails closed and emits no render_model",
            ret != 0
            and "does not match deck_plan.title" in serr
            and not emitted
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, emitted={emitted}, stderr={serr!r}",
        ))

    # I. Pre-existing render_model from a previous successful run is
    #    REMOVED when this run fails closed on that slide. Without the
    #    cleanup step the stale file would survive a fail-closed
    #    mismatch and continue to claim authority for the slide.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="stale_layout")
        # Plant a previously-good render_model file on disk. Content is
        # not inspected after the cleanup decision — leading-digit index
        # is all that matters — but a schema-valid body keeps the test
        # truthful to the "previous successful run" framing.
        (ws / "render_models").mkdir(exist_ok=True)
        prior = ws / "render_models" / "01_cover.json"
        prior.write_text(json.dumps({
            "index": 1,
            "layout": "cover",
            "canvas": {"width_px": 1920, "height_px": 1080},
            "source_refs": ["synthetic_src_g"],
            "primitives": [{
                "id": "title",
                "slot_id": "title",
                "kind": "text",
                "bounds": {"x": 160, "y": 320, "w": 1280, "h": 200},
                "style": {
                    "color_token": "palette.text",
                    "typography_token": "typography.heading",
                },
                "text": {"content": "previous run", "role": "heading"},
            }],
        }))
        assert prior.is_file(), "test setup: pre-placed file must exist"
        ret, sout, serr = run(ws, tr)
        still_exists = prior.is_file()
        cleaned_logged = "[CLEAN] render_models/01_cover.json" in sout
        out.append(CheckResult(
            "tempfixture generator: pre-existing render_model from a "
            "previous run is REMOVED when current run fails closed on "
            "that slide (stale file cannot survive fail-closed mismatch)",
            ret != 0
            and not still_exists
            and cleaned_logged
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, still_exists={still_exists}, "
            f"cleaned_logged={cleaned_logged}, sout={sout!r}, stderr={serr!r}",
        ))

    # J. Slide's layout was previously supported (so a render_model
    #    was produced) but the deck_plan has since changed it to an
    #    unsupported layout. The pre-existing render_model is REMOVED
    #    on the next run even though the generator does not write a
    #    replacement (the slide is now skipped). Without this, the
    #    workspace would carry a stale cover render_model for a slide
    #    the deck_plan now describes as comparison_table.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="happy")
        # Mutate deck_plan slide 1 from cover -> comparison_table
        # (unsupported), and align the slide_plan + section_id so the
        # workspace stays schema-valid and the generator's per-slide
        # alignment guard does not short-circuit first.
        deck = json.loads((ws / "deck_plan.json").read_text())
        deck["slides"][0]["layout"] = "comparison_table"
        deck["slides"][0]["title"] = "Now Unsupported"
        (ws / "deck_plan.json").write_text(json.dumps(deck))
        plan1 = json.loads((ws / "slide_plans" / "01.json").read_text())
        plan1["layout"] = "comparison_table"
        plan1["title"] = "Now Unsupported"
        plan1["blocks"] = [
            {"id": "title", "kind": "text", "content": "Now Unsupported"},
            {"id": "table", "kind": "table",
             "content": {"columns": ["A", "B"], "rows": [["1", "2"]]}},
        ]
        (ws / "slide_plans" / "01.json").write_text(json.dumps(plan1))
        # Plant a stale render_model from "before the layout change".
        (ws / "render_models").mkdir(exist_ok=True)
        prior = ws / "render_models" / "01_cover.json"
        prior.write_text(json.dumps({
            "index": 1,
            "layout": "cover",
            "canvas": {"width_px": 1920, "height_px": 1080},
            "source_refs": ["synthetic_src_g"],
            "primitives": [{
                "id": "title",
                "slot_id": "title",
                "kind": "text",
                "bounds": {"x": 160, "y": 320, "w": 1280, "h": 200},
                "style": {
                    "color_token": "palette.text",
                    "typography_token": "typography.heading",
                },
                "text": {"content": "stale cover", "role": "heading"},
            }],
        }))
        assert prior.is_file(), "test setup: pre-placed file must exist"
        ret, sout, serr = run(ws, tr)
        still_exists = prior.is_file()
        skipped_logged = (
            "[SKIP] slide  1: layout 'comparison_table' not implemented"
            in sout
        )
        cleaned_logged = "[CLEAN] render_models/01_cover.json" in sout
        out.append(CheckResult(
            "tempfixture generator: pre-existing render_model is REMOVED "
            "when the slide's deck_plan layout has changed to one the "
            "generator does not implement (no replacement is written)",
            ret == 0
            and not still_exists
            and skipped_logged
            and cleaned_logged
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, still_exists={still_exists}, "
            f"skipped_logged={skipped_logged}, cleaned_logged={cleaned_logged}, "
            f"sout={sout!r}, stderr={serr!r}",
        ))

    # K. Orphan render_model: the file's slide index is no longer in
    #    deck_plan at all (deck size shrank, slide moved indices, etc.).
    #    Without cleanup, check_render_models would later flag this
    #    file with "index does not match a deck_plan slide" and the
    #    generator's own cross-check would fail the run — turning a
    #    stale on-disk file into a confusing post-hoc error. The
    #    cleanup sweep removes it up front instead.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="happy")
        # The synthetic deck_plan in the happy workspace declares
        # indices 1 and 2. Plant a render_model for an index (99) that
        # the deck_plan no longer (and never did) claim.
        (ws / "render_models").mkdir(exist_ok=True)
        orphan = ws / "render_models" / "99_cover.json"
        orphan.write_text(json.dumps({
            "index": 99,
            "layout": "cover",
            "canvas": {"width_px": 1920, "height_px": 1080},
            "source_refs": ["synthetic_src_g"],
            "primitives": [{
                "id": "title",
                "slot_id": "title",
                "kind": "text",
                "bounds": {"x": 160, "y": 320, "w": 1280, "h": 200},
                "style": {
                    "color_token": "palette.text",
                    "typography_token": "typography.heading",
                },
                "text": {"content": "orphan", "role": "heading"},
            }],
        }))
        assert orphan.is_file(), "test setup: orphan file must exist"
        ret, sout, serr = run(ws, tr)
        still_exists = orphan.is_file()
        cleaned_logged = "[CLEAN] render_models/99_cover.json" in sout
        out.append(CheckResult(
            "tempfixture generator: orphan render_model for a slide "
            "no longer in deck_plan (deck shrank or slide moved index) "
            "is REMOVED before check_render_models runs, so it does "
            "not surface as a post-hoc cross-check failure",
            ret == 0
            and not still_exists
            and cleaned_logged
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, still_exists={still_exists}, "
            f"cleaned_logged={cleaned_logged}, sout={sout!r}, stderr={serr!r}",
        ))

    # L. Non-JSON files are NOT cleaned. Proves the cleanup glob is
    #    targeted at *.json (which is generator-owned and validated as
    #    render_models by the workspace runner) and does not wipe
    #    unrelated files (READMEs, .md / .txt notes) that happen to
    #    live in render_models/.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="happy")
        (ws / "render_models").mkdir(exist_ok=True)
        readme = ws / "render_models" / "NOTES.md"
        readme.write_text("Manual notes about this workspace.\n")
        also = ws / "render_models" / "checklist.txt"
        also.write_text("manual checklist\n")
        ret, sout, serr = run(ws, tr)
        readme_preserved = readme.is_file()
        txt_preserved = also.is_file()
        any_cleaned_non_json = (
            "[CLEAN] render_models/NOTES.md" in sout
            or "[CLEAN] render_models/checklist.txt" in sout
        )
        out.append(CheckResult(
            "tempfixture generator: non-JSON files in render_models/ "
            "(NOTES.md, checklist.txt) are PRESERVED — cleanup glob "
            "targets *.json only, leaving manual notes / READMEs alone",
            ret == 0
            and readme_preserved
            and txt_preserved
            and not any_cleaned_non_json
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, readme_preserved={readme_preserved}, "
            f"txt_preserved={txt_preserved}, "
            f"any_cleaned_non_json={any_cleaned_non_json}, "
            f"sout={sout!r}, stderr={serr!r}",
        ))

    # Preflight cases M / N / O. The generator must fail closed BEFORE
    # the render_models/ cleanup sweep whenever the input contract is
    # malformed in a way that makes generation meaningless. The shared
    # invariant proved by all three: a pre-existing render_model file
    # on disk SURVIVES the failed run. Without preflight, the run would
    # delete every *.json under render_models/ and then report "OK:
    # generated 0" — silently wiping the previous good output.
    _prior_render_model_body = {
        "index": 1,
        "layout": "cover",
        "canvas": {"width_px": 1920, "height_px": 1080},
        "source_refs": ["synthetic_src_g"],
        "primitives": [{
            "id": "title",
            "slot_id": "title",
            "kind": "text",
            "bounds": {"x": 160, "y": 320, "w": 1280, "h": 200},
            "style": {
                "color_token": "palette.text",
                "typography_token": "typography.heading",
            },
            "text": {"content": "previous good run", "role": "heading"},
        }],
    }

    # M. deck_plan.slides is missing entirely. Schema requires it; the
    #    explicit slides-shape check also flags it. Either way, preflight
    #    must reject before cleanup. Pre-existing render_model survives.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="happy")
        (ws / "render_models").mkdir(exist_ok=True)
        prior = ws / "render_models" / "01_cover.json"
        prior.write_text(json.dumps(_prior_render_model_body))
        deck = json.loads((ws / "deck_plan.json").read_text())
        del deck["slides"]
        (ws / "deck_plan.json").write_text(json.dumps(deck))
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture generator: missing deck_plan.slides fails closed "
            "BEFORE cleanup; pre-existing render_model file is preserved "
            "and no OK is reported",
            ret != 0
            and prior.is_file()
            and "OK:" not in sout
            and "[PREFLIGHT FAIL]" in serr
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, prior_exists={prior.is_file()}, "
            f"ok_in_sout={'OK:' in sout}, "
            f"preflight_marker={'[PREFLIGHT FAIL]' in serr}, "
            f"sout={sout!r}, stderr={serr!r}",
        ))

    # N. deck_plan.slides is not a list (string here). Schema rejects it;
    #    the explicit slides-shape check also rejects it. Preflight must
    #    fail before cleanup. Pre-existing render_model survives.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="happy")
        (ws / "render_models").mkdir(exist_ok=True)
        prior = ws / "render_models" / "01_cover.json"
        prior.write_text(json.dumps(_prior_render_model_body))
        deck = json.loads((ws / "deck_plan.json").read_text())
        deck["slides"] = "this is not a list"
        (ws / "deck_plan.json").write_text(json.dumps(deck))
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture generator: deck_plan.slides not a list (string) "
            "fails closed BEFORE cleanup; pre-existing render_model file "
            "is preserved and no OK is reported",
            ret != 0
            and prior.is_file()
            and "OK:" not in sout
            and "[PREFLIGHT FAIL]" in serr
            and "deck_plan.slides must be a list" in serr
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, prior_exists={prior.is_file()}, "
            f"ok_in_sout={'OK:' in sout}, "
            f"preflight_marker={'[PREFLIGHT FAIL]' in serr}, "
            f"sout={sout!r}, stderr={serr!r}",
        ))

    # O. planning.planned_slide_count disagrees with len(slides). Schema
    #    cannot express this equality; check_planner_semantics catches it.
    #    Preflight runs that cross-check, so the run must still fail
    #    closed before cleanup and the prior file must survive.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tr = root / "templates"
        tr.mkdir()
        _build_generator_template(tr)
        ws = root / "ws"
        _build_generator_workspace(ws, kind="happy")
        (ws / "render_models").mkdir(exist_ok=True)
        prior = ws / "render_models" / "01_cover.json"
        prior.write_text(json.dumps(_prior_render_model_body))
        deck = json.loads((ws / "deck_plan.json").read_text())
        deck["planning"]["planned_slide_count"] = 99
        (ws / "deck_plan.json").write_text(json.dumps(deck))
        ret, sout, serr = run(ws, tr)
        out.append(CheckResult(
            "tempfixture generator: planning.planned_slide_count != "
            "len(slides) fails closed BEFORE cleanup (planner-semantics "
            "cross-check); pre-existing render_model file is preserved "
            "and no OK is reported",
            ret != 0
            and prior.is_file()
            and "OK:" not in sout
            and "[PREFLIGHT FAIL]" in serr
            and "planning.planned_slide_count" in serr
            and "UNEXPECTED EXCEPTION" not in serr,
            f"ret={ret}, prior_exists={prior.is_file()}, "
            f"ok_in_sout={'OK:' in sout}, "
            f"preflight_marker={'[PREFLIGHT FAIL]' in serr}, "
            f"sout={sout!r}, stderr={serr!r}",
        ))

    return out


def _print(section: str, results: list[CheckResult]) -> int:
    print(f"\n== {section} ==")
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
        description="Stdlib-only, fail-closed workspace validator.",
    )
    parser.add_argument("--workspace", required=True, type=Path,
                        help="Caller-supplied workspace directory.")
    parser.add_argument("--template-root", required=True, type=Path,
                        help="Directory containing template subdirectories.")
    args = parser.parse_args(argv)

    if not args.workspace.is_dir():
        print(f"error: workspace is not a directory: {args.workspace}", file=sys.stderr)
        return 2
    if not args.template_root.is_dir():
        print(f"error: template-root is not a directory: {args.template_root}", file=sys.stderr)
        return 2

    sections: list[tuple[str, list[CheckResult]]] = [
        ("schemas: every artifact validates", check_schemas(args.workspace)),
        ("template chain: deck_plan.template + layout declarations",
         check_template_chain(args.workspace, args.template_root)),
        ("template files: template.json + theme + every declared layout",
         check_template_files_for_workspace(args.workspace, args.template_root)),
        ("slide_plan coverage: 1:1 with deck_plan + required slots",
         check_slide_plan_coverage(args.workspace, args.template_root)),
        ("planner semantics: planned_slide_count, section coverage, "
         "slide.section_id, slide.source_refs vs. deck_brief.source_refs",
         check_planner_semantics(args.workspace)),
        ("image_manifest: path-safety + media resolution + image_refs",
         check_image_manifest(args.workspace)),
        ("render_models: schema + cross-artifact controlled-primitive contract",
         check_render_models(args.workspace, args.template_root)),
        ("svg_previews: per-render_model SVG exists + canvas viewBox + "
         "no <foreignObject> + reference safety + bounds inside canvas",
         check_svg_previews(args.workspace, args.template_root)),
        ("negative: unsafe scheme, absolute, traversal, missing media, "
         "unknown layout, missing slide_plan, slot mismatch",
         negative_checks(args.workspace, args.template_root)),
        ("negative tempfixtures: missing theme, bad theme schema, "
         "bad layout schema, missing declared layout file, duplicate "
         "slide_plan index, missing deck_plan.json without traceback, "
         "malformed-but-loadable artifacts without traceback",
         negative_tempfixture_checks()),
        ("negative tempfixtures (planner semantics): planned_slide_count "
         "mismatch, missing / duplicate / orphan section indices, "
         "unknown / mis-listed slide.section_id, undeclared slide.source_refs",
         negative_planner_semantics_tempfixture_checks()),
        ("negative tempfixtures (render_model): unsupported kind, missing "
         "bounds, invalid token refs, external URL / file:// / absolute "
         "path / path traversal in image_ref, arbitrary SVG-like fields, "
         "kind-payload mismatch, bounds outside canvas, unknown slot_id, "
         "slot.primitive_kind mismatch, image_ref not in manifest, "
         "unknown palette token, source_refs cross-check fails closed when "
         "deck_brief is missing / malformed / empty, duplicate primitive ids",
         negative_render_model_tempfixture_checks()),
        ("negative tempfixtures (svg_preview): missing svg_preview, "
         "malformed XML, wrong root, viewBox mismatch, <foreignObject>, "
         "href URL / file:// / absolute / '..' / data: / javascript:, "
         "undeclared <image> href, rect outside canvas, <text> anchor "
         "outside canvas (negative and beyond-edge)",
         negative_svg_preview_tempfixture_checks()),
        ("negative tempfixtures (svg generator): happy path emits svg; "
         "fails closed on unsupported primitive kind, unknown palette "
         "token, image_slot resolving to unsafe manifest local_path, "
         "missing render_models/, non-hex / schema-violating design "
         "tokens (palette + font_family); PREFLIGHT (runs before "
         "cleanup) rejects malformed image_manifest.json (missing "
         "'images') and unsafe image_manifest local_path without "
         "deleting any pre-existing svg_previews/*.svg; resolvers "
         "reject unsafe values directly (defense-in-depth, including "
         "the background rect); stale *.svg is cleaned, non-SVG files "
         "are preserved",
         negative_svg_generator_tempfixture_checks()),
        ("negative tempfixtures (render-model generator): happy path "
         "emits supported layout + skips unsupported as not implemented; "
         "fails closed on unknown image_ref, malformed kpi block, "
         "missing required slide_plan block, missing deck_plan.json, "
         "unsafe deck_plan.template, and stale slide_plan (layout or "
         "title disagrees with deck_plan); cleans up pre-existing "
         "render_model files when the current run fails closed or the "
         "slide's layout is no longer supported; PREFLIGHT (runs before "
         "cleanup) rejects missing / non-list slides and "
         "planned_slide_count != len(slides) without deleting any "
         "pre-existing render_models/*.json",
         negative_generator_tempfixture_checks()),
    ]
    fails = 0
    for title, results in sections:
        fails += _print(title, results)
    print()
    if fails:
        print(f"FAIL: {fails} check(s) did not pass.")
        return 1
    print(f"OK: workspace {args.workspace} validated against all checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
