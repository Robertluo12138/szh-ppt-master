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

NEGATIVE TESTS (built in; exercised in the same run)
    unsafe scheme, absolute path, path traversal, missing media,
    unknown layout, missing slide_plan, required-slot mismatch.

TRACEBACK SAFETY
    Every check function is defensive against malformed-but-loadable
    caller workspaces. If a JSON artifact loads but is the wrong
    shape (a list at root, a non-dict slide, an image entry missing
    'id'/'local_path', a non-string template name, ...), the
    validator reports a structured [FAIL] line rather than tracebacking.
    Two tempfixtures (#8 malformed-but-loadable, #9 list-rooted core
    artifacts) prove this stays true.

OUT OF SCOPE
    No SVG generation, no PPTX export, no D-One, no Qoder, no network.
    Those stages are not implemented in this repo.
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
)

SCHEMAS = REPO_ROOT / "schemas"

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
