#!/usr/bin/env python3
"""generate_render_models.py

Deterministic, stdlib-only generator for per-slide render_model artifacts.
Reads a workspace's existing pipeline outputs and emits
`<workspace>/render_models/<idx>_<layout>.json` for the supported layouts.

SUPPORTED LAYOUTS
    cover              text + structural line (title divider)
                       + (optional) image_slot
    section_divider    text + structural line (rule under the title)
                       + (optional) image_slot
    executive_summary  text + bulleted text list (key_points)
    key_message        text + decorative rounded shape (callout
                       background, sized to message slot bounds)
                       + callout text on top
    two_column         text + paired bulleted text lists per column
    kpi_dashboard      text + one rounded-rectangle "card" shape
                       per KPI tile + one kpi primitive layered on
                       top of each card (no outer decorative band)
    timeline           text + structural vertical line (axis)
                       + one filled-ellipse marker per step
                       + one text primitive per step offset to the
                       right of the marker (no bullet prefix; the
                       marker replaces it)
    agenda             text + bulleted text list (agenda_items)
    conclusion         text + bulleted text list (call_to_action)
    comparison_table   text + native table primitive (columns + rows)

Supported layouts emit only the controlled primitive kinds the
downstream renderers cover today: text, line, shape, image_slot, kpi,
and (for comparison_table only) table. Slides with any other layout
(e.g. a chart_placeholder layout) are SKIPPED and reported as not
implemented; they are NOT counted as success. A successful run therefore
says exactly how many render models were generated AND how many slides
were skipped.

INPUTS (all workspace-relative)
    deck_brief.json
    deck_plan.json
    design_system.json
    image_manifest.json
    slide_plans/<file>.json (one per deck_plan slide; matched by JSON index)

Plus the chosen template's `template.json` and `layouts/<layout>.json`
under --template-root, resolved through the two-stage path-safety gate
imported from validate_workspace.

DETERMINISM
    The generator never invents source content. Text and callout
    strings come from `slide_plan.blocks[].content`. List entries
    (key_points, left_content, right_content, agenda_items,
    call_to_action) are read from the matching slide_plan list
    block's content array; each entry becomes its own bulleted text
    primitive whose height is `min(slot.h // count, LIST_ITEM_MAX_H)`
    so a short list packs tight at the top of the slot rather than
    sprawling across the full slot height. timeline_items uses the
    same per-item-height helper but its visual shape is different:
    each entry becomes a non-bulleted text primitive offset to the
    right of a structural axis line plus one filled-ellipse marker
    centered on the axis at the item's vertical midline. KPI rows
    come from `slide_plan.blocks[id="kpis"].content`; each entry
    becomes one rounded-rectangle "card" shape (structural, no slot)
    plus one `kpi` primitive layered on top at the same bounds —
    there is no single outer band shape. Image refs come from
    `slide_plan.blocks[id="accent"].content` and must be declared
    in `image_manifest`. Bounds use the layout slot's `bounds` when
    set, otherwise the deterministic fallback table at the top of
    this file (LAYOUT_FALLBACK_BOUNDS / COVER_FALLBACK_BOUNDS /
    KPI_FALLBACK_BOUNDS).

PREFLIGHT GATES (run BEFORE render_models/ cleanup)
    Cleanup deletes every *.json under render_models/, so any check that
    might fail must fire first. The preflight is fail-closed and prevents
    cleanup when the workspace cannot legitimately drive generation:
      - schema validation of all four core inputs (deck_brief.json,
        deck_plan.json, design_system.json, image_manifest.json) against
        their schemas under schemas/;
      - deck_plan.slides is a non-empty list of objects (defense in depth:
        the deck_plan schema already requires this, but the explicit
        runtime check keeps the cleanup gate intact even if the schema
        ever loosens);
      - planner semantics from validate_workspace.check_planner_semantics:
        planning.planned_slide_count equals len(slides), sections cover
        slide indices, slide.section_id resolves and lists this index,
        slide.source_refs are all declared in deck_brief.source_refs.
    The render_models cross-check (check_render_models) is intentionally
    NOT run in preflight — a stale render_model may legitimately exist
    from a previous run and is the very thing the cleanup phase below
    is responsible for sweeping. Calling it here would false-fail on
    that legitimate stale state.

STALE-FILE CLEANUP (runs after preflight, before per-slide generation)
    Before generating, the script removes every *.json file under
    render_models/. The workspace validator schema-validates every
    *.json in this directory as a render_model, so the namespace is
    fully generator-owned: any leftover .json file that the generator
    did not produce in the current run would be either a stale lie or
    a guaranteed validation failure. Sweeping unconditionally covers:
      - a previous run succeeded for this slide, but the current run
        fails closed on it (mismatched slide_plan, missing image_ref,
        malformed kpi, ...);
      - a previous run succeeded for this slide, but the deck_plan
        layout has since changed to one the generator does not
        implement (slide is now skipped — no replacement written);
      - the slide has been REMOVED from deck_plan entirely (deck
        shrank, slide moved indices, ...). The orphan render_model
        would otherwise be flagged by check_render_models as "index
        does not match a deck_plan slide" and surface as a
        post-hoc failure rather than a clean cleanup;
      - the slide is still supported, in which case the file is
        deleted and immediately rewritten (idempotent regeneration).
    Non-.json files (READMEs, .md / .txt notes, ...) are left alone —
    the cleanup glob only matches *.json.

FAIL-CLOSED GATES (every gate exits non-zero on failure)
    - workspace / template-root path is not a directory;
    - any required artifact missing, unloadable, or wrong root shape;
    - any preflight gate above (schema, slides shape, planner semantics);
    - deck_plan.template unsafe or outside --template-root;
    - template / layout files missing, unloadable, or non-object;
    - deck_plan slide missing required source_refs or referencing source
      ids that the deck_brief does not declare;
    - stale / mismatched slide_plan: matched by JSON index, but its
      `layout` or `title` disagrees with the deck_plan slide;
    - slide_plan content shape that the supported layout does not expect
      (missing required block, wrong block kind, malformed kpi entries,
      empty list content, list-slot too short for the requested items);
    - cover slot 'accent' content referencing an image_ref that
      image_manifest does not declare;
    - design_system missing required palette keys (primary/background/text)
      or non-integer grid dimensions;
    - generated output failing schema validation
      (schemas/render_model.schema.json);
    - generated output failing the workspace cross-checks in
      validate_workspace.check_render_models.

OUT OF SCOPE
    SVG rendering, PPTX export, D-One, Qoder integration, network
    behavior, charts, chart-bearing layouts (any slot mapped to
    chart_placeholder), and any new fixtures beyond the workspaces the
    caller already ships.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validate_artifacts import _validate  # noqa: E402
from validate_scaffold import local_path_is_safe  # noqa: E402
from validate_workspace import (  # noqa: E402
    _safe_load_inside,
    _try_load,
    _as_dict,
    _as_list,
    _schema_validate,
    check_planner_semantics,
    check_render_models,
)

SCHEMAS = REPO_ROOT / "schemas"
SUPPORTED_LAYOUTS = (
    "cover",
    "section_divider",
    "executive_summary",
    "key_message",
    "two_column",
    "kpi_dashboard",
    "timeline",
    "agenda",
    "conclusion",
    "comparison_table",
)

# Deterministic fallback bounds for cover slots that don't carry their own
# bounds. The cover layout now declares bounds for every text slot (title,
# subtitle, presenter, date) and the optional image slot (accent); these
# fallbacks remain as a forward-compat safety net so the generator still
# produces a deterministic render_model if any of those bounds are ever
# removed from the layout.
COVER_FALLBACK_BOUNDS = {
    "title":     (160, 320, 1280, 100),
    "subtitle":  (160, 460, 1280, 80),
    "presenter": (160, 880, 600, 60),
    "date":      (1160, 880, 600, 60),
    "accent":    (1480, 200, 320, 320),
}
# Structural primitive: a divider line above the title. No slot id — the
# line is purely decorative and not driven by slide_plan content.
COVER_TITLE_DIVIDER_BOUNDS = (160, 290, 1280, 4)

# Deterministic fallback bounds for the kpi_dashboard slots. The kpis slot
# is sized to wrap the actual KPI tile content (label + value + optional
# delta) rather than reserving an oversized empty band; matches the
# bounds declared by templates/layouts/business_review/layouts/kpi_dashboard.json.
KPI_FALLBACK_BOUNDS = {
    "title": (64, 80, 1792, 120),
    "kpis":  (64, 280, 1792, 200),
}
KPI_TILE_GAP = 12
KPI_INSET_X = 32  # horizontal padding inside the kpis slot
KPI_INSET_Y = 20  # vertical padding inside the kpis slot
# Corner radius used for the per-tile card backgrounds. Structural shapes
# painted behind every KPI tile so the dashboard reads as a grid of cards
# instead of a single wide band with empty space below the text.
KPI_TILE_CORNER_RADIUS = 12

# Deterministic fallback bounds for the non-cover / non-kpi_dashboard layouts.
# Used only when the layout slot omits `bounds`. The owned business_review
# layouts (executive_summary, key_message, two_column, conclusion,
# section_divider) declare bounds explicitly; these fallbacks let the
# generator still produce a valid render_model against a bounds-less layout
# (notably timeline.json, whose layout JSON is outside this script's
# ownership and remains unbounded today).
LAYOUT_FALLBACK_BOUNDS = {
    "executive_summary": {
        "title":      (64, 80, 1792, 100),
        "summary":    (64, 210, 1792, 180),
        "key_points": (64, 420, 1792, 580),
    },
    "key_message": {
        "title":           (64, 80, 1792, 100),
        "message":         (160, 260, 1600, 140),
        "supporting_text": (160, 440, 1600, 180),
    },
    "two_column": {
        "title":         (64, 80, 1792, 100),
        "left_heading":  (96, 220, 832, 80),
        "left_content":  (96, 320, 832, 680),
        "right_heading": (992, 220, 832, 80),
        "right_content": (992, 320, 832, 680),
    },
    "conclusion": {
        "title":          (64, 80, 1792, 100),
        "summary":        (64, 210, 1792, 160),
        "call_to_action": (64, 400, 1792, 600),
    },
    "section_divider": {
        "section_number": (64, 360, 400, 80),
        "section_title":  (64, 460, 1792, 220),
        "subtitle":       (64, 720, 1792, 140),
        # Accent image sits in the top band ABOVE section_title (y < 460)
        # and right of section_number (x > 464), so it never overlaps the
        # full-width title/subtitle text — a long title cannot be hidden
        # under the image. Keep it clear of those bands if these change.
        "accent":         (640, 80, 640, 340),
    },
    "timeline": {
        "title":          (64, 80, 1792, 100),
        "timeline_items": (64, 260, 1792, 700),
    },
    "agenda": {
        "title":         (64, 80, 1792, 100),
        "agenda_items":  (64, 260, 1792, 700),
    },
    "comparison_table": {
        "title": (64, 80, 1792, 100),
        "table": (64, 240, 1792, 760),
    },
}

# Decorative line drawn between section_title and subtitle on the
# section_divider layout. Structural: no slot binding.
SECTION_DIVIDER_RULE_BOUNDS = (64, 700, 1792, 4)

# Timeline visual-affordance constants. The timeline layout otherwise
# renders as a plain bulleted list — visually indistinguishable from an
# agenda. A structural axis line + a filled circle marker per step give
# it a recognisable timeline silhouette using only the controlled
# primitive set (line, shape, text).
TIMELINE_AXIS_OFFSET_PX = 24   # x-inset of the axis inside the slot
TIMELINE_AXIS_STROKE_PX = 2    # axis stroke width
TIMELINE_MARKER_RADIUS_PX = 8  # half-side of the marker bounding box
TIMELINE_TEXT_OFFSET_PX = 48   # x-inset of step text inside the slot

# Minimum vertical pixels per list item before the generator refuses to
# distribute. Body text is ~19px tall at 14pt; 28px gives modest leading.
LIST_ITEM_MIN_H = 28
# Maximum vertical pixels per list item before items pack at the top of
# the slot with trailing whitespace below. Without this clamp, two
# bullets in a 680px slot each become 340px tall and read as a sparse
# pair of headlines rather than a list. 96px fits the 14pt body line
# (~19px) with generous breathing room while keeping a 7- or 8-item
# list visually contained.
LIST_ITEM_MAX_H = 96
# Bullet prefix prepended to each list item's text content. Renderers
# treat text.content as a literal display string; the prefix gives the
# preview a recognisable bullet without requiring rich-text support.
LIST_ITEM_BULLET_PREFIX = "• "


class GenerationError(RuntimeError):
    """Raised when the generator cannot proceed on a specific slide.
    The caller catches this per-slide and records the slide as a fatal
    error without aborting the rest of the run; the script's overall
    exit code becomes non-zero if any slide raised."""


def _fatal(msg: str) -> int:
    print(f"FAIL: {msg}", file=sys.stderr)
    return 1


def _load_required_object(path: Path, label: str) -> tuple[dict | None, str]:
    """Load path as JSON and require an object root. Returns (data, '') on
    success or (None, reason) — never raises."""
    data, err = _try_load(path)
    if data is None:
        return (None, f"{label} not loadable: {err}")
    if not isinstance(data, dict):
        return (None, f"{label} root is not an object: got {type(data).__name__}")
    return (data, "")


def _bounds_or_fallback(slot: object, fallback: tuple[int, int, int, int]) -> dict:
    """Return {x,y,w,h} from slot['bounds'] when fully integer, else from the
    fallback tuple. Used by the cover generator for slots that don't yet
    declare bounds in the layout JSON."""
    if isinstance(slot, dict):
        b = slot.get("bounds")
        if isinstance(b, dict) and all(
            isinstance(b.get(k), int) and not isinstance(b.get(k), bool)
            for k in ("x", "y", "w", "h")
        ):
            return {"x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"]}
    x, y, w, h = fallback
    return {"x": x, "y": y, "w": w, "h": h}


def _text_block_content(blocks_by_id: dict, slot_id: str) -> str:
    block = blocks_by_id.get(slot_id)
    if not isinstance(block, dict):
        raise GenerationError(
            f"missing slide_plan block for slot id {slot_id!r}"
        )
    if block.get("kind") != "text":
        raise GenerationError(
            f"slot {slot_id!r} expects a text block; "
            f"got kind={block.get('kind')!r}"
        )
    content = block.get("content")
    if not isinstance(content, str) or not content:
        raise GenerationError(
            f"slot {slot_id!r} text block has no non-empty string content"
        )
    return content


def _check_slot_present(slots_by_id: dict, slot_id: str, layout_name: str) -> dict:
    slot = slots_by_id.get(slot_id)
    if not isinstance(slot, dict):
        raise GenerationError(
            f"layout {layout_name!r} has no slot id {slot_id!r}"
        )
    return slot


def _list_block_content(blocks_by_id: dict, slot_id: str) -> list[str]:
    """Validate a `kind=list` slide_plan block and return its items as a
    list of non-empty strings. Raises GenerationError on any drift from
    the controlled contract (wrong kind, non-list content, empty list,
    non-string entry)."""
    block = blocks_by_id.get(slot_id)
    if not isinstance(block, dict):
        raise GenerationError(
            f"missing slide_plan block for slot id {slot_id!r}"
        )
    if block.get("kind") != "list":
        raise GenerationError(
            f"slot {slot_id!r} expects a list block; "
            f"got kind={block.get('kind')!r}"
        )
    content = block.get("content")
    if not isinstance(content, list) or not content:
        raise GenerationError(
            f"slot {slot_id!r} list block content must be a non-empty list of strings"
        )
    items: list[str] = []
    for i, item in enumerate(content):
        if not isinstance(item, str) or not item:
            raise GenerationError(
                f"slot {slot_id!r} list block content[{i}] is not a non-empty string"
            )
        items.append(item)
    return items


def _callout_block_content(blocks_by_id: dict, slot_id: str) -> str:
    """Validate a `kind=callout` slide_plan block and return its string
    content. Mirrors _text_block_content but for the callout kind so the
    key_message generator can keep callouts distinct from plain text."""
    block = blocks_by_id.get(slot_id)
    if not isinstance(block, dict):
        raise GenerationError(
            f"missing slide_plan block for slot id {slot_id!r}"
        )
    if block.get("kind") != "callout":
        raise GenerationError(
            f"slot {slot_id!r} expects a callout block; "
            f"got kind={block.get('kind')!r}"
        )
    content = block.get("content")
    if not isinstance(content, str) or not content:
        raise GenerationError(
            f"slot {slot_id!r} callout block has no non-empty string content"
        )
    return content


def _list_item_bounds(slot_bounds: dict, count: int, index: int) -> dict:
    """Distribute `count` list items vertically inside slot_bounds and
    return the bounds for the item at `index`. Integer-only arithmetic
    so output is byte-stable.

    Each item gets ``min(slot.h // count, LIST_ITEM_MAX_H)`` pixels of
    vertical space. The clamp keeps a short list packed at the top of
    the slot rather than letting two bullets sprawl across a 680px
    column slot (which read visually as a sparse pair of headlines,
    not as a list). Trailing whitespace below the last item is
    intentional; keeping every item the same height keeps the preview
    legible at any count."""
    if count <= 0 or index < 0 or index >= count:
        raise GenerationError(
            f"invalid list item request: count={count}, index={index}"
        )
    sx = slot_bounds["x"]
    sy = slot_bounds["y"]
    sw = slot_bounds["w"]
    sh = slot_bounds["h"]
    item_h = sh // count
    if item_h < LIST_ITEM_MIN_H:
        raise GenerationError(
            f"list slot too short for {count} items "
            f"(item_h={item_h} < {LIST_ITEM_MIN_H})"
        )
    if item_h > LIST_ITEM_MAX_H:
        item_h = LIST_ITEM_MAX_H
    return {"x": sx, "y": sy + index * item_h, "w": sw, "h": item_h}


def _fallback_for(layout_name: str, slot_id: str) -> tuple[int, int, int, int]:
    """Return the fallback bounds tuple registered for (layout_name, slot_id).
    Raises GenerationError if the generator forgot to register a fallback —
    every supported layout slot the generator touches must have one so a
    bounds-less layout still produces a deterministic render_model."""
    by_slot = LAYOUT_FALLBACK_BOUNDS.get(layout_name)
    if not isinstance(by_slot, dict) or slot_id not in by_slot:
        raise GenerationError(
            f"internal: no fallback bounds registered for "
            f"layout={layout_name!r}, slot={slot_id!r}"
        )
    return by_slot[slot_id]


def _make_text_primitive(
    prim_id: str,
    slot_id: str | None,
    bounds: dict,
    content: str,
    *,
    role: str,
    typography_token: str,
) -> dict:
    """Build a controlled text primitive. `slot_id=None` means structural
    text not bound to a layout slot — currently unused but kept symmetric
    with `_make_text_primitive` for shape and line helpers below."""
    prim: dict = {
        "id": prim_id,
        "kind": "text",
        "bounds": bounds,
        "style": {
            "color_token": "palette.text",
            "typography_token": typography_token,
        },
        "text": {"content": content, "role": role},
    }
    if slot_id is not None:
        prim["slot_id"] = slot_id
    return prim


def _generate_cover(
    slide_plan: dict,
    deck_slide: dict,
    layout: dict,
    design_system: dict,
    manifest_ids: set[str],
    manifest_alt_by_id: dict,
) -> dict:
    grid = design_system["grid"]
    canvas = {"width_px": grid["width_px"], "height_px": grid["height_px"]}
    slots_by_id = {
        s["id"]: s for s in (_as_list(layout.get("slots")) or [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    blocks_by_id = {
        b["id"]: b for b in (_as_list(slide_plan.get("blocks")) or [])
        if isinstance(b, dict) and isinstance(b.get("id"), str)
    }

    primitives: list[dict] = []

    # Decorative title divider. Structural (no slot binding, no slide_plan
    # content). Stroke uses palette.primary which is a required palette key,
    # so this works against any conforming design_system.
    primitives.append({
        "id": "title_divider",
        "kind": "line",
        "bounds": dict(zip(("x", "y", "w", "h"), COVER_TITLE_DIVIDER_BOUNDS)),
        "style": {
            "stroke_token": "palette.primary",
            "stroke_width_px": 4,
        },
        "line": {"stroke_style": "solid"},
    })

    # Required: title.
    title_slot = _check_slot_present(slots_by_id, "title", "cover")
    primitives.append({
        "id": "title",
        "slot_id": "title",
        "kind": "text",
        "bounds": _bounds_or_fallback(title_slot, COVER_FALLBACK_BOUNDS["title"]),
        "style": {
            "color_token": "palette.text",
            "typography_token": "typography.heading",
        },
        "text": {
            "content": _text_block_content(blocks_by_id, "title"),
            "role": "heading",
        },
    })

    # Optional text-only slots, in deterministic order.
    for slot_id, role in (
        ("subtitle", "subheading"),
        ("presenter", "body"),
        ("date", "body"),
    ):
        if slot_id not in blocks_by_id:
            continue
        slot = _check_slot_present(slots_by_id, slot_id, "cover")
        primitives.append({
            "id": slot_id,
            "slot_id": slot_id,
            "kind": "text",
            "bounds": _bounds_or_fallback(slot, COVER_FALLBACK_BOUNDS[slot_id]),
            "style": {
                "color_token": "palette.text",
                "typography_token": "typography.body",
            },
            "text": {
                "content": _text_block_content(blocks_by_id, slot_id),
                "role": role,
            },
        })

    # Optional accent image. The slide_plan block must be kind=image_ref,
    # its content must be a manifest id, and the manifest must declare it.
    if "accent" in blocks_by_id:
        accent_slot = _check_slot_present(slots_by_id, "accent", "cover")
        block = blocks_by_id["accent"]
        if block.get("kind") != "image_ref":
            raise GenerationError(
                f"slot 'accent' expects an image_ref block; "
                f"got kind={block.get('kind')!r}"
            )
        image_ref = block.get("content")
        if not isinstance(image_ref, str) or not image_ref:
            raise GenerationError(
                "slot 'accent' image_ref block has no string content"
            )
        if image_ref not in manifest_ids:
            raise GenerationError(
                f"slot 'accent' references image id {image_ref!r} that is "
                f"not declared in image_manifest"
            )
        payload: dict = {"image_ref": image_ref}
        alt = manifest_alt_by_id.get(image_ref)
        if isinstance(alt, str) and alt:
            payload["alt_text"] = alt
        primitives.append({
            "id": "accent_image",
            "slot_id": "accent",
            "kind": "image_slot",
            "bounds": _bounds_or_fallback(
                accent_slot, COVER_FALLBACK_BOUNDS["accent"],
            ),
            "image_slot": payload,
        })

    return {
        "index": deck_slide["index"],
        "layout": "cover",
        "canvas": canvas,
        "source_refs": list(deck_slide.get("source_refs") or []),
        "primitives": primitives,
    }


def _kpi_tile_bounds(slot_bounds: dict, count: int, index: int) -> dict:
    """Distribute `count` KPI tiles inside slot_bounds with a fixed gap and
    horizontal centering. Pure-integer arithmetic, deterministic, and
    bounded inside slot_bounds for every (count, index) pair tested
    (1..6 tiles)."""
    sx = slot_bounds["x"]
    sy = slot_bounds["y"]
    sw = slot_bounds["w"]
    sh = slot_bounds["h"]
    if count <= 0 or index < 0 or index >= count:
        raise GenerationError(
            f"invalid kpi tile request: count={count}, index={index}"
        )
    usable_w = sw - 2 * KPI_INSET_X
    h = sh - 2 * KPI_INSET_Y
    y = sy + KPI_INSET_Y
    if count == 1:
        return {"x": sx + KPI_INSET_X, "y": y, "w": usable_w, "h": h}
    tile_w = (usable_w - (count - 1) * KPI_TILE_GAP) // count
    if tile_w <= 0:
        raise GenerationError(
            f"kpi slot bounds too narrow for {count} tiles "
            f"(usable_w={usable_w})"
        )
    total_row = count * tile_w + (count - 1) * KPI_TILE_GAP
    left_pad = (sw - total_row) // 2
    x = sx + left_pad + index * (tile_w + KPI_TILE_GAP)
    return {"x": x, "y": y, "w": tile_w, "h": h}


def _generate_kpi_dashboard(
    slide_plan: dict,
    deck_slide: dict,
    layout: dict,
    design_system: dict,
    manifest_ids: set[str],
    manifest_alt_by_id: dict,
) -> dict:
    """kpi_dashboard: required title text + required kpi list. For each
    entry in `slide_plan.blocks[id="kpis"].content` the generator emits
    one structural rounded-rectangle "card" shape (no slot_id, sized to
    the tile's bounds — the visible card border) and one `kpi`
    primitive layered on top at the same bounds (slot_bound to the
    `kpis` slot — the editable label / value / optional delta).
    There is no single outer band shape: the kpis slot is sized to
    wrap the actual tile content, and each tile carries its own
    border, so the dashboard reads as a grid of cards rather than a
    band with text floating at the top."""
    grid = design_system["grid"]
    canvas = {"width_px": grid["width_px"], "height_px": grid["height_px"]}
    slots_by_id = {
        s["id"]: s for s in (_as_list(layout.get("slots")) or [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    blocks_by_id = {
        b["id"]: b for b in (_as_list(slide_plan.get("blocks")) or [])
        if isinstance(b, dict) and isinstance(b.get("id"), str)
    }

    title_slot = _check_slot_present(slots_by_id, "title", "kpi_dashboard")
    kpis_slot = _check_slot_present(slots_by_id, "kpis", "kpi_dashboard")
    kpis_block = blocks_by_id.get("kpis")
    if not isinstance(kpis_block, dict):
        raise GenerationError(
            "kpi_dashboard slide_plan missing block id='kpis'"
        )
    if kpis_block.get("kind") != "kpi":
        raise GenerationError(
            f"slot 'kpis' expects a kpi block; "
            f"got kind={kpis_block.get('kind')!r}"
        )
    kpis_content = kpis_block.get("content")
    if not isinstance(kpis_content, list) or not kpis_content:
        raise GenerationError(
            "slot 'kpis' content must be a non-empty list of "
            "KPI dicts ({label, value, delta?})"
        )

    primitives: list[dict] = []
    primitives.append({
        "id": "title",
        "slot_id": "title",
        "kind": "text",
        "bounds": _bounds_or_fallback(title_slot, KPI_FALLBACK_BOUNDS["title"]),
        "style": {
            "color_token": "palette.text",
            "typography_token": "typography.heading",
        },
        "text": {
            "content": _text_block_content(blocks_by_id, "title"),
            "role": "heading",
        },
    })

    kpis_bounds = _bounds_or_fallback(kpis_slot, KPI_FALLBACK_BOUNDS["kpis"])

    # Per-tile card backgrounds. Each card is a structural rounded
    # rectangle (no slot_id) painted at the same bounds as its KPI
    # tile, then the tile primitive is layered on top. The dashboard
    # reads as a grid of cards rather than a single wide band with
    # empty space below the value line. Structural-only — the kpis
    # slot's primitive_kind=kpi gate fires only on slot-bound
    # primitives, so card shapes do not trip the mismatch check.
    for i, entry in enumerate(kpis_content):
        if not isinstance(entry, dict):
            raise GenerationError(
                f"slot 'kpis' content[{i}] is not an object: "
                f"got {type(entry).__name__}"
            )
        label = entry.get("label")
        value = entry.get("value")
        if not isinstance(label, str) or not label:
            raise GenerationError(
                f"slot 'kpis' content[{i}].label is not a non-empty string"
            )
        if not isinstance(value, str) or not value:
            raise GenerationError(
                f"slot 'kpis' content[{i}].value is not a non-empty string"
            )
        delta = entry.get("delta")
        kpi_payload: dict = {"label": label, "value": value}
        if delta is None:
            pass
        elif isinstance(delta, str) and delta:
            kpi_payload["delta"] = delta
        else:
            raise GenerationError(
                f"slot 'kpis' content[{i}].delta must be a non-empty "
                f"string when set; got {type(delta).__name__}"
            )
        tile_bounds = _kpi_tile_bounds(kpis_bounds, len(kpis_content), i)
        primitives.append({
            "id": f"kpi_card_{i + 1:02d}",
            "kind": "shape",
            "bounds": dict(tile_bounds),
            "style": {
                "fill_token": "palette.background",
                "stroke_token": "palette.primary",
                "stroke_width_px": 2,
            },
            "shape": {
                "shape_kind": "rounded_rectangle",
                "corner_radius_px": KPI_TILE_CORNER_RADIUS,
            },
        })
        primitives.append({
            "id": f"kpi_{i + 1:02d}",
            "slot_id": "kpis",
            "kind": "kpi",
            "bounds": tile_bounds,
            "style": {"color_token": "palette.text"},
            "kpi": kpi_payload,
        })

    return {
        "index": deck_slide["index"],
        "layout": "kpi_dashboard",
        "canvas": canvas,
        "source_refs": list(deck_slide.get("source_refs") or []),
        "primitives": primitives,
    }


def _bounds_for(slots_by_id: dict, layout_name: str, slot_id: str) -> dict:
    """Resolve the canonical bounds for `slot_id` on `layout_name`: prefer
    the layout slot's declared bounds, else the fallback table. Raises
    GenerationError if the slot is missing from the layout (the caller
    must check the slot is required or that the slide_plan asks for it
    before calling this)."""
    slot = _check_slot_present(slots_by_id, slot_id, layout_name)
    return _bounds_or_fallback(slot, _fallback_for(layout_name, slot_id))


def _generate_executive_summary(
    slide_plan: dict,
    deck_slide: dict,
    layout: dict,
    design_system: dict,
    manifest_ids: set[str],
    manifest_alt_by_id: dict,
) -> dict:
    """executive_summary: title + summary (both required) + optional
    bulleted key_points list. Every primitive emits a text kind."""
    grid = design_system["grid"]
    canvas = {"width_px": grid["width_px"], "height_px": grid["height_px"]}
    slots_by_id = {
        s["id"]: s for s in (_as_list(layout.get("slots")) or [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    blocks_by_id = {
        b["id"]: b for b in (_as_list(slide_plan.get("blocks")) or [])
        if isinstance(b, dict) and isinstance(b.get("id"), str)
    }

    primitives: list[dict] = []

    # Required: title.
    primitives.append(_make_text_primitive(
        "title", "title",
        _bounds_for(slots_by_id, "executive_summary", "title"),
        _text_block_content(blocks_by_id, "title"),
        role="heading",
        typography_token="typography.heading",
    ))

    # Required: summary.
    primitives.append(_make_text_primitive(
        "summary", "summary",
        _bounds_for(slots_by_id, "executive_summary", "summary"),
        _text_block_content(blocks_by_id, "summary"),
        role="body",
        typography_token="typography.body",
    ))

    # Optional: key_points (list). Only fired when the slide_plan declares
    # the optional block; the layout slot still has to exist for the
    # primitives to bind to it.
    if "key_points" in blocks_by_id:
        kp_bounds = _bounds_for(slots_by_id, "executive_summary", "key_points")
        items = _list_block_content(blocks_by_id, "key_points")
        for i, item in enumerate(items):
            primitives.append(_make_text_primitive(
                f"key_point_{i + 1:02d}", "key_points",
                _list_item_bounds(kp_bounds, len(items), i),
                LIST_ITEM_BULLET_PREFIX + item,
                role="body",
                typography_token="typography.body",
            ))

    return {
        "index": deck_slide["index"],
        "layout": "executive_summary",
        "canvas": canvas,
        "source_refs": list(deck_slide.get("source_refs") or []),
        "primitives": primitives,
    }


def _generate_key_message(
    slide_plan: dict,
    deck_slide: dict,
    layout: dict,
    design_system: dict,
    manifest_ids: set[str],
    manifest_alt_by_id: dict,
) -> dict:
    """key_message: optional title, required callout message rendered as a
    rounded-rectangle background plus a text primitive on top, and
    optional supporting_text. The decorative shape is structural (no
    slot_id) so the layout slot.primitive_kind=text constraint binds the
    overlayed text only."""
    grid = design_system["grid"]
    canvas = {"width_px": grid["width_px"], "height_px": grid["height_px"]}
    slots_by_id = {
        s["id"]: s for s in (_as_list(layout.get("slots")) or [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    blocks_by_id = {
        b["id"]: b for b in (_as_list(slide_plan.get("blocks")) or [])
        if isinstance(b, dict) and isinstance(b.get("id"), str)
    }

    primitives: list[dict] = []

    if "title" in blocks_by_id:
        primitives.append(_make_text_primitive(
            "title", "title",
            _bounds_for(slots_by_id, "key_message", "title"),
            _text_block_content(blocks_by_id, "title"),
            role="heading",
            typography_token="typography.heading",
        ))

    # Required: message. Decorative band first, then the text on top —
    # the shape carries no slot_id so the slot.primitive_kind check on
    # the 'message' slot still only binds the text primitive below.
    msg_bounds = _bounds_for(slots_by_id, "key_message", "message")
    primitives.append({
        "id": "message_callout_bg",
        "kind": "shape",
        "bounds": dict(msg_bounds),
        "style": {
            "fill_token": "palette.background",
            "stroke_token": "palette.primary",
            "stroke_width_px": 2,
        },
        "shape": {
            "shape_kind": "rounded_rectangle",
            "corner_radius_px": 16,
        },
    })
    primitives.append(_make_text_primitive(
        "message", "message",
        dict(msg_bounds),
        _callout_block_content(blocks_by_id, "message"),
        role="callout",
        typography_token="typography.heading",
    ))

    if "supporting_text" in blocks_by_id:
        primitives.append(_make_text_primitive(
            "supporting_text", "supporting_text",
            _bounds_for(slots_by_id, "key_message", "supporting_text"),
            _text_block_content(blocks_by_id, "supporting_text"),
            role="body",
            typography_token="typography.body",
        ))

    return {
        "index": deck_slide["index"],
        "layout": "key_message",
        "canvas": canvas,
        "source_refs": list(deck_slide.get("source_refs") or []),
        "primitives": primitives,
    }


def _generate_two_column(
    slide_plan: dict,
    deck_slide: dict,
    layout: dict,
    design_system: dict,
    manifest_ids: set[str],
    manifest_alt_by_id: dict,
) -> dict:
    """two_column: title + two parallel columns of optional heading and
    required content list. Each column's heading is a text primitive,
    each list item is its own text primitive distributed inside the
    column's content slot."""
    grid = design_system["grid"]
    canvas = {"width_px": grid["width_px"], "height_px": grid["height_px"]}
    slots_by_id = {
        s["id"]: s for s in (_as_list(layout.get("slots")) or [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    blocks_by_id = {
        b["id"]: b for b in (_as_list(slide_plan.get("blocks")) or [])
        if isinstance(b, dict) and isinstance(b.get("id"), str)
    }

    primitives: list[dict] = []

    # Required: title.
    primitives.append(_make_text_primitive(
        "title", "title",
        _bounds_for(slots_by_id, "two_column", "title"),
        _text_block_content(blocks_by_id, "title"),
        role="heading",
        typography_token="typography.heading",
    ))

    # Per-side: optional heading + required content list. The render order
    # (left heading, left items, right heading, right items) is deterministic
    # and mirrors the slide_plan's visual reading order.
    for side, prefix in (("left", "left"), ("right", "right")):
        heading_slot_id = f"{side}_heading"
        content_slot_id = f"{side}_content"
        if heading_slot_id in blocks_by_id:
            primitives.append(_make_text_primitive(
                heading_slot_id, heading_slot_id,
                _bounds_for(slots_by_id, "two_column", heading_slot_id),
                _text_block_content(blocks_by_id, heading_slot_id),
                role="subheading",
                typography_token="typography.heading",
            ))
        content_bounds = _bounds_for(slots_by_id, "two_column", content_slot_id)
        items = _list_block_content(blocks_by_id, content_slot_id)
        for i, item in enumerate(items):
            primitives.append(_make_text_primitive(
                f"{prefix}_item_{i + 1:02d}", content_slot_id,
                _list_item_bounds(content_bounds, len(items), i),
                LIST_ITEM_BULLET_PREFIX + item,
                role="body",
                typography_token="typography.body",
            ))

    return {
        "index": deck_slide["index"],
        "layout": "two_column",
        "canvas": canvas,
        "source_refs": list(deck_slide.get("source_refs") or []),
        "primitives": primitives,
    }


def _generate_conclusion(
    slide_plan: dict,
    deck_slide: dict,
    layout: dict,
    design_system: dict,
    manifest_ids: set[str],
    manifest_alt_by_id: dict,
) -> dict:
    """conclusion: required title + optional summary text + optional
    call_to_action bulleted list. Mirrors executive_summary's text-only
    shape but with a different slot vocabulary."""
    grid = design_system["grid"]
    canvas = {"width_px": grid["width_px"], "height_px": grid["height_px"]}
    slots_by_id = {
        s["id"]: s for s in (_as_list(layout.get("slots")) or [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    blocks_by_id = {
        b["id"]: b for b in (_as_list(slide_plan.get("blocks")) or [])
        if isinstance(b, dict) and isinstance(b.get("id"), str)
    }

    primitives: list[dict] = []

    primitives.append(_make_text_primitive(
        "title", "title",
        _bounds_for(slots_by_id, "conclusion", "title"),
        _text_block_content(blocks_by_id, "title"),
        role="heading",
        typography_token="typography.heading",
    ))

    if "summary" in blocks_by_id:
        primitives.append(_make_text_primitive(
            "summary", "summary",
            _bounds_for(slots_by_id, "conclusion", "summary"),
            _text_block_content(blocks_by_id, "summary"),
            role="body",
            typography_token="typography.body",
        ))

    if "call_to_action" in blocks_by_id:
        cta_bounds = _bounds_for(slots_by_id, "conclusion", "call_to_action")
        items = _list_block_content(blocks_by_id, "call_to_action")
        for i, item in enumerate(items):
            primitives.append(_make_text_primitive(
                f"call_to_action_{i + 1:02d}", "call_to_action",
                _list_item_bounds(cta_bounds, len(items), i),
                LIST_ITEM_BULLET_PREFIX + item,
                role="body",
                typography_token="typography.body",
            ))

    return {
        "index": deck_slide["index"],
        "layout": "conclusion",
        "canvas": canvas,
        "source_refs": list(deck_slide.get("source_refs") or []),
        "primitives": primitives,
    }


def _generate_section_divider(
    slide_plan: dict,
    deck_slide: dict,
    layout: dict,
    design_system: dict,
    manifest_ids: set[str],
    manifest_alt_by_id: dict,
) -> dict:
    """section_divider: optional section_number, required section_title,
    a structural horizontal rule below the title, and optional subtitle.
    The rule is decorative (no slot_id)."""
    grid = design_system["grid"]
    canvas = {"width_px": grid["width_px"], "height_px": grid["height_px"]}
    slots_by_id = {
        s["id"]: s for s in (_as_list(layout.get("slots")) or [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    blocks_by_id = {
        b["id"]: b for b in (_as_list(slide_plan.get("blocks")) or [])
        if isinstance(b, dict) and isinstance(b.get("id"), str)
    }

    primitives: list[dict] = []

    if "section_number" in blocks_by_id:
        primitives.append(_make_text_primitive(
            "section_number", "section_number",
            _bounds_for(slots_by_id, "section_divider", "section_number"),
            _text_block_content(blocks_by_id, "section_number"),
            role="subheading",
            typography_token="typography.body",
        ))

    primitives.append(_make_text_primitive(
        "section_title", "section_title",
        _bounds_for(slots_by_id, "section_divider", "section_title"),
        _text_block_content(blocks_by_id, "section_title"),
        role="heading",
        typography_token="typography.heading",
    ))

    primitives.append({
        "id": "section_rule",
        "kind": "line",
        "bounds": dict(zip(("x", "y", "w", "h"), SECTION_DIVIDER_RULE_BOUNDS)),
        "style": {
            "stroke_token": "palette.primary",
            "stroke_width_px": 4,
        },
        "line": {"stroke_style": "solid"},
    })

    if "subtitle" in blocks_by_id:
        primitives.append(_make_text_primitive(
            "subtitle", "subtitle",
            _bounds_for(slots_by_id, "section_divider", "subtitle"),
            _text_block_content(blocks_by_id, "subtitle"),
            role="subheading",
            typography_token="typography.body",
        ))

    # Optional accent image. Mirrors the cover generator's accent slot:
    # the slide_plan block must be kind=image_ref, its content must be a
    # manifest id, and the manifest must declare it. Absent the block,
    # nothing is emitted, so a section_divider slide without an image
    # renders exactly as before.
    if "accent" in blocks_by_id:
        block = blocks_by_id["accent"]
        if block.get("kind") != "image_ref":
            raise GenerationError(
                f"slot 'accent' expects an image_ref block; "
                f"got kind={block.get('kind')!r}"
            )
        image_ref = block.get("content")
        if not isinstance(image_ref, str) or not image_ref:
            raise GenerationError(
                "slot 'accent' image_ref block has no string content"
            )
        if image_ref not in manifest_ids:
            raise GenerationError(
                f"slot 'accent' references image id {image_ref!r} that is "
                f"not declared in image_manifest"
            )
        payload: dict = {"image_ref": image_ref}
        alt = manifest_alt_by_id.get(image_ref)
        if isinstance(alt, str) and alt:
            payload["alt_text"] = alt
        primitives.append({
            "id": "accent_image",
            "slot_id": "accent",
            "kind": "image_slot",
            "bounds": _bounds_for(slots_by_id, "section_divider", "accent"),
            "image_slot": payload,
        })

    return {
        "index": deck_slide["index"],
        "layout": "section_divider",
        "canvas": canvas,
        "source_refs": list(deck_slide.get("source_refs") or []),
        "primitives": primitives,
    }


def _generate_timeline(
    slide_plan: dict,
    deck_slide: dict,
    layout: dict,
    design_system: dict,
    manifest_ids: set[str],
    manifest_alt_by_id: dict,
) -> dict:
    """timeline: required title + required timeline_items list. The
    timeline_items list is rendered as a structural vertical axis line
    plus one filled ellipse marker per step plus one text primitive per
    step (no bullet prefix — the marker replaces the bullet). The axis
    and markers are structural primitives (no slot_id), so the
    slot.primitive_kind=text gate on `timeline_items` binds only the
    text primitives; the structural shapes are checked against the
    canvas only. The timeline.json layout (outside this script's
    ownership) does not declare bounds today; both slots fall back to
    the table in LAYOUT_FALLBACK_BOUNDS."""
    grid = design_system["grid"]
    canvas = {"width_px": grid["width_px"], "height_px": grid["height_px"]}
    slots_by_id = {
        s["id"]: s for s in (_as_list(layout.get("slots")) or [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    blocks_by_id = {
        b["id"]: b for b in (_as_list(slide_plan.get("blocks")) or [])
        if isinstance(b, dict) and isinstance(b.get("id"), str)
    }

    primitives: list[dict] = []

    primitives.append(_make_text_primitive(
        "title", "title",
        _bounds_for(slots_by_id, "timeline", "title"),
        _text_block_content(blocks_by_id, "title"),
        role="heading",
        typography_token="typography.heading",
    ))

    items_bounds = _bounds_for(slots_by_id, "timeline", "timeline_items")
    items = _list_block_content(blocks_by_id, "timeline_items")
    count = len(items)
    sx = items_bounds["x"]
    sy = items_bounds["y"]
    sw = items_bounds["w"]
    # _list_item_bounds applies LIST_ITEM_MIN_H / LIST_ITEM_MAX_H. Use it
    # to compute the per-item slice height once so the axis length
    # matches the actual item stack rather than the full slot height.
    first_item = _list_item_bounds(items_bounds, count, 0)
    item_h = first_item["h"]
    axis_height = count * item_h
    axis_x = sx + TIMELINE_AXIS_OFFSET_PX

    # Structural vertical axis. Bounds.w must be > 0 per the schema;
    # the SVG renderer draws the line from (x, y) to (x+w, y+h), so
    # w=1 with the stroke width supplied by style gives a clean axis.
    primitives.append({
        "id": "timeline_axis",
        "kind": "line",
        "bounds": {
            "x": axis_x, "y": sy,
            "w": 1, "h": axis_height,
        },
        "style": {
            "stroke_token": "palette.primary",
            "stroke_width_px": TIMELINE_AXIS_STROKE_PX,
        },
        "line": {"stroke_style": "solid"},
    })

    for i, item in enumerate(items):
        item_bounds = _list_item_bounds(items_bounds, count, i)
        marker_cy = item_bounds["y"] + item_h // 2
        primitives.append({
            "id": f"timeline_marker_{i + 1:02d}",
            "kind": "shape",
            "bounds": {
                "x": axis_x - TIMELINE_MARKER_RADIUS_PX,
                "y": marker_cy - TIMELINE_MARKER_RADIUS_PX,
                "w": TIMELINE_MARKER_RADIUS_PX * 2,
                "h": TIMELINE_MARKER_RADIUS_PX * 2,
            },
            "style": {
                "fill_token": "palette.primary",
                "stroke_token": "palette.primary",
                "stroke_width_px": 2,
            },
            "shape": {"shape_kind": "ellipse"},
        })
        text_bounds = {
            "x": sx + TIMELINE_TEXT_OFFSET_PX,
            "y": item_bounds["y"],
            "w": sw - TIMELINE_TEXT_OFFSET_PX,
            "h": item_h,
        }
        primitives.append(_make_text_primitive(
            f"timeline_item_{i + 1:02d}", "timeline_items",
            text_bounds, item,
            role="body",
            typography_token="typography.body",
        ))

    return {
        "index": deck_slide["index"],
        "layout": "timeline",
        "canvas": canvas,
        "source_refs": list(deck_slide.get("source_refs") or []),
        "primitives": primitives,
    }


def _generate_agenda(
    slide_plan: dict,
    deck_slide: dict,
    layout: dict,
    design_system: dict,
    manifest_ids: set[str],
    manifest_alt_by_id: dict,
) -> dict:
    """agenda: required title + required agenda_items list. Items are
    rendered as a vertically stacked bulleted list inside the
    agenda_items slot, mirroring the timeline generator. The agenda
    layout JSON in business_review does not declare bounds today; both
    slots fall back to the table in LAYOUT_FALLBACK_BOUNDS."""
    grid = design_system["grid"]
    canvas = {"width_px": grid["width_px"], "height_px": grid["height_px"]}
    slots_by_id = {
        s["id"]: s for s in (_as_list(layout.get("slots")) or [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    blocks_by_id = {
        b["id"]: b for b in (_as_list(slide_plan.get("blocks")) or [])
        if isinstance(b, dict) and isinstance(b.get("id"), str)
    }

    primitives: list[dict] = []

    primitives.append(_make_text_primitive(
        "title", "title",
        _bounds_for(slots_by_id, "agenda", "title"),
        _text_block_content(blocks_by_id, "title"),
        role="heading",
        typography_token="typography.heading",
    ))

    items_bounds = _bounds_for(slots_by_id, "agenda", "agenda_items")
    items = _list_block_content(blocks_by_id, "agenda_items")
    for i, item in enumerate(items):
        primitives.append(_make_text_primitive(
            f"agenda_item_{i + 1:02d}", "agenda_items",
            _list_item_bounds(items_bounds, len(items), i),
            LIST_ITEM_BULLET_PREFIX + item,
            role="body",
            typography_token="typography.body",
        ))

    return {
        "index": deck_slide["index"],
        "layout": "agenda",
        "canvas": canvas,
        "source_refs": list(deck_slide.get("source_refs") or []),
        "primitives": primitives,
    }


def _generate_comparison_table(
    slide_plan: dict,
    deck_slide: dict,
    layout: dict,
    design_system: dict,
    manifest_ids: set[str],
    manifest_alt_by_id: dict,
) -> dict:
    """comparison_table: required title text + required table primitive.

    The slide_plan's `table` block carries the cell content as a
    `{headers: [...], rows: [[...], ...]}` dict; the render_model's
    `table` primitive renames `headers` to `columns` (to match
    render_model.schema.json's payload field) and requires every row to
    have the same column count as `headers`. Every cell value must be a
    non-empty string — the controlled primitive contract does not yet
    accept numeric or rich-text cell payloads."""
    grid = design_system["grid"]
    canvas = {"width_px": grid["width_px"], "height_px": grid["height_px"]}
    slots_by_id = {
        s["id"]: s for s in (_as_list(layout.get("slots")) or [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    blocks_by_id = {
        b["id"]: b for b in (_as_list(slide_plan.get("blocks")) or [])
        if isinstance(b, dict) and isinstance(b.get("id"), str)
    }

    primitives: list[dict] = []

    primitives.append(_make_text_primitive(
        "title", "title",
        _bounds_for(slots_by_id, "comparison_table", "title"),
        _text_block_content(blocks_by_id, "title"),
        role="heading",
        typography_token="typography.heading",
    ))

    table_block = blocks_by_id.get("table")
    if not isinstance(table_block, dict):
        raise GenerationError(
            "comparison_table slide_plan missing block id='table'"
        )
    if table_block.get("kind") != "table":
        raise GenerationError(
            f"slot 'table' expects a table block; "
            f"got kind={table_block.get('kind')!r}"
        )
    content = _as_dict(table_block.get("content"))
    if content is None:
        raise GenerationError(
            "slot 'table' block content must be an object with "
            "'headers' (non-empty list of strings) and 'rows' "
            "(non-empty list of equal-length row arrays)"
        )
    headers = content.get("headers")
    rows_raw = content.get("rows")
    if not isinstance(headers, list) or not headers:
        raise GenerationError(
            "slot 'table' content.headers must be a non-empty list of strings"
        )
    columns: list[str] = []
    for i, h in enumerate(headers):
        if not isinstance(h, str) or not h:
            raise GenerationError(
                f"slot 'table' content.headers[{i}] is not a non-empty string"
            )
        columns.append(h)
    if not isinstance(rows_raw, list) or not rows_raw:
        raise GenerationError(
            "slot 'table' content.rows must be a non-empty list of row arrays"
        )
    rows: list[list[str]] = []
    for r_i, row in enumerate(rows_raw):
        if not isinstance(row, list) or not row:
            raise GenerationError(
                f"slot 'table' content.rows[{r_i}] must be a non-empty list"
            )
        if len(row) != len(columns):
            raise GenerationError(
                f"slot 'table' content.rows[{r_i}] has {len(row)} cells but "
                f"there are {len(columns)} column(s); every row must match "
                f"the column count"
            )
        cells: list[str] = []
        for c_i, cell in enumerate(row):
            if not isinstance(cell, str) or not cell:
                raise GenerationError(
                    f"slot 'table' content.rows[{r_i}][{c_i}] is not a "
                    f"non-empty string"
                )
            cells.append(cell)
        rows.append(cells)

    primitives.append({
        "id": "comparison_table",
        "slot_id": "table",
        "kind": "table",
        "bounds": _bounds_for(slots_by_id, "comparison_table", "table"),
        "style": {"color_token": "palette.text"},
        "table": {"columns": columns, "rows": rows},
    })

    return {
        "index": deck_slide["index"],
        "layout": "comparison_table",
        "canvas": canvas,
        "source_refs": list(deck_slide.get("source_refs") or []),
        "primitives": primitives,
    }


GENERATORS = {
    "cover": _generate_cover,
    "executive_summary": _generate_executive_summary,
    "key_message": _generate_key_message,
    "two_column": _generate_two_column,
    "kpi_dashboard": _generate_kpi_dashboard,
    "timeline": _generate_timeline,
    "agenda": _generate_agenda,
    "conclusion": _generate_conclusion,
    "section_divider": _generate_section_divider,
    "comparison_table": _generate_comparison_table,
}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic render_model generator for the "
                    "controlled primitive set (text / line / shape / "
                    "image_slot / kpi / table). Supported layouts: cover, "
                    "section_divider, executive_summary, key_message, "
                    "two_column, kpi_dashboard, timeline, agenda, "
                    "conclusion, comparison_table. Layouts mapped to the "
                    "chart_placeholder primitive kind are skipped as not "
                    "implemented.",
    )
    parser.add_argument("--workspace", required=True, type=Path,
                        help="Caller-supplied workspace directory.")
    parser.add_argument("--template-root", required=True, type=Path,
                        help="Directory containing template subdirectories.")
    args = parser.parse_args(argv)

    ws = args.workspace
    tr = args.template_root
    if not ws.is_dir():
        return _fatal(f"workspace is not a directory: {ws}")
    if not tr.is_dir():
        return _fatal(f"template-root is not a directory: {tr}")

    brief, err = _load_required_object(ws / "deck_brief.json", "deck_brief.json")
    if brief is None:
        return _fatal(err)
    deck, err = _load_required_object(ws / "deck_plan.json", "deck_plan.json")
    if deck is None:
        return _fatal(err)
    design, err = _load_required_object(ws / "design_system.json", "design_system.json")
    if design is None:
        return _fatal(err)
    manifest, err = _load_required_object(ws / "image_manifest.json", "image_manifest.json")
    if manifest is None:
        return _fatal(err)

    # PREFLIGHT: runs BEFORE the render_models/ cleanup sweep below. The
    # cleanup deletes every *.json in render_models/, so a malformed
    # caller workspace must not be permitted to reach it — otherwise a
    # broken planner contract (missing slides, wrong slide_count, ...)
    # would silently wipe a previously-good render_model set and report
    # zero generated. The gates here are read-only and stop short of
    # touching render_models/ at all. The render_models cross-check is
    # intentionally NOT called here: stale render_models may legitimately
    # exist from a previous run; the cleanup phase below is what removes
    # them, and calling check_render_models in preflight would false-fail
    # on that legitimate stale state.
    preflight_errors: list[str] = []
    for fname, schema_name, artifact in (
        ("deck_brief.json",     "deck_brief.schema.json",     brief),
        ("deck_plan.json",      "deck_plan.schema.json",      deck),
        ("design_system.json",  "design_system.schema.json",  design),
        ("image_manifest.json", "image_manifest.schema.json", manifest),
    ):
        errors = _schema_validate(artifact, SCHEMAS / schema_name)
        if errors:
            preflight_errors.append(
                f"{fname} fails {schema_name}: {'; '.join(errors)}"
            )

    # Defense-in-depth shape check for deck_plan.slides. The schema above
    # already enforces a non-empty array of objects with the right keys,
    # but the cleanup phase below is a destructive action against a
    # caller-supplied directory and the contract that gates it (slides is
    # iterable, non-empty, dict-rooted entries) is small enough to re-prove
    # here explicitly. If the deck_plan schema is ever loosened, this
    # remains a hard wall in front of cleanup.
    slides_raw = deck.get("slides")
    if not isinstance(slides_raw, list):
        preflight_errors.append(
            f"deck_plan.slides must be a list "
            f"(got {type(slides_raw).__name__}); refusing to clean up "
            f"render_models/ when the planner contract is malformed"
        )
    elif not slides_raw:
        preflight_errors.append(
            "deck_plan.slides is empty; refusing to clean up "
            "render_models/ when the planner contract is malformed"
        )
    else:
        for i, s in enumerate(slides_raw):
            if not isinstance(s, dict):
                preflight_errors.append(
                    f"deck_plan.slides[{i}] must be an object "
                    f"(got {type(s).__name__})"
                )

    # Planner-semantics cross-checks (planned_slide_count == len(slides),
    # section coverage, section_id resolution + listing, slide.source_refs
    # subset of deck_brief.source_refs). Reuses validate_workspace so the
    # generator and the workspace runner enforce the same contract.
    for r in check_planner_semantics(ws):
        if not r.ok:
            preflight_errors.append(
                f"planner semantics: {r.name} — {r.detail}"
            )

    if preflight_errors:
        print(
            f"FAIL: render_model generation aborted BEFORE cleanup; "
            f"{len(preflight_errors)} preflight failure(s):",
            file=sys.stderr,
        )
        for err in preflight_errors:
            print(f"  [PREFLIGHT FAIL] {err}", file=sys.stderr)
        return 1

    template_name = deck.get("template")
    if not isinstance(template_name, str) or not template_name:
        return _fatal(
            f"deck_plan.template is not a non-empty string: got {template_name!r}"
        )
    ok, template_dir, reason = _safe_load_inside(tr, template_name)
    if not ok:
        return _fatal(
            f"deck_plan.template {template_name!r} unsafe or outside "
            f"template-root: {reason}"
        )
    template, err = _load_required_object(
        template_dir / "template.json",
        f"template.json for {template_name!r}",
    )
    if template is None:
        return _fatal(err)

    declared_layouts_raw = _as_list(template.get("layouts")) or []
    declared_layouts = {n for n in declared_layouts_raw if isinstance(n, str)}
    layouts: dict[str, dict] = {}
    for name in sorted(declared_layouts):
        if not local_path_is_safe(name):
            return _fatal(
                f"template {template_name!r}: layout name {name!r} is not path-safe"
            )
        layout_path = template_dir / "layouts" / f"{name}.json"
        layout, err = _load_required_object(
            layout_path, f"layout {name!r} for template {template_name!r}",
        )
        if layout is None:
            return _fatal(err)
        layouts[name] = layout

    # design_system requires palette.primary/background/text and integer grid.
    palette = _as_dict(design.get("palette")) or {}
    grid = _as_dict(design.get("grid")) or {}
    for key in ("primary", "background", "text"):
        if not isinstance(palette.get(key), str):
            return _fatal(
                f"design_system.palette.{key} is missing or not a string; "
                f"generator emits palette.{key} as a token ref and requires it"
            )
    for key in ("width_px", "height_px"):
        if not isinstance(grid.get(key), int) or isinstance(grid.get(key), bool):
            return _fatal(
                f"design_system.grid.{key} must be a positive integer"
            )

    # image_manifest map for fast lookup.
    manifest_ids: set[str] = set()
    manifest_alt_by_id: dict[str, str] = {}
    for img in _as_list(manifest.get("images")) or []:
        img_d = _as_dict(img)
        if img_d is None:
            continue
        img_id = img_d.get("id")
        if isinstance(img_id, str):
            manifest_ids.add(img_id)
            alt = img_d.get("alt_text")
            if isinstance(alt, str):
                manifest_alt_by_id[img_id] = alt

    # brief source_refs allow-list. Required and non-empty.
    brief_refs_list = _as_list(brief.get("source_refs"))
    if not brief_refs_list:
        return _fatal(
            "deck_brief.source_refs is missing or empty; generator requires "
            "a non-empty allow-list to copy onto each render_model"
        )
    brief_refs = {r for r in brief_refs_list if isinstance(r, str)}
    if not brief_refs:
        return _fatal(
            "deck_brief.source_refs contains no string ids"
        )

    # Index slide_plans by their JSON index field, defensively against
    # malformed-but-loadable plans.
    plans_dir = ws / "slide_plans"
    plans_by_index: dict[int, dict] = {}
    if plans_dir.is_dir():
        for f in sorted(plans_dir.glob("*.json")):
            data, _ = _try_load(f)
            d = _as_dict(data) if data is not None else None
            if d is not None and isinstance(d.get("index"), int):
                plans_by_index[d["index"]] = d

    out_dir = ws / "render_models"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Fail-closed cleanup: before generating, remove every *.json file
    # under render_models/. The render_models/*.json namespace is
    # generator-owned — the workspace validator treats every *.json in
    # this directory as a render_model and schema-validates it, so any
    # leftover *.json that the generator did not produce in this run
    # would either be a stale lie or a guaranteed validation failure.
    # Sweeping unconditionally covers four scenarios:
    #   - a previous successful run, but this slide now fails closed
    #     (mismatched slide_plan, missing image_ref, malformed kpi, ...);
    #   - a previous successful run, but the slide's deck_plan layout
    #     has since been changed to one the generator does not
    #     implement (slide gets skipped, no replacement written);
    #   - the slide has been REMOVED from deck_plan entirely (deck
    #     size shrank, the slide moved to a different index, etc.) —
    #     the orphan render_model has no current owner and would
    #     otherwise be flagged by check_render_models as "index ...
    #     does not match a deck_plan slide";
    #   - the slide is still in deck_plan and still supported, in
    #     which case the file is deleted and immediately rewritten
    #     by the generator below (idempotent).
    # Non-.json files (READMEs, manual notes with .md / .txt
    # extensions, ...) are left alone — the glob only matches *.json.
    cleaned_stale: list[Path] = []
    for stale in sorted(out_dir.glob("*.json")):
        stale.unlink()
        cleaned_stale.append(stale)

    generated: list[tuple[int, str, Path]] = []
    skipped: list[tuple[int, str]] = []
    fatal_errors: list[str] = []

    for slide in _as_list(deck.get("slides")) or []:
        slide_d = _as_dict(slide)
        if slide_d is None:
            fatal_errors.append(
                f"deck_plan slide is not an object: got {type(slide).__name__}"
            )
            continue
        idx = slide_d.get("index")
        layout_name = slide_d.get("layout")
        if not isinstance(idx, int) or isinstance(idx, bool):
            fatal_errors.append(
                f"deck_plan slide has non-integer index: {idx!r}"
            )
            continue
        if not isinstance(layout_name, str):
            fatal_errors.append(
                f"deck_plan slide {idx}: layout is not a string"
            )
            continue

        if layout_name not in SUPPORTED_LAYOUTS:
            skipped.append((idx, layout_name))
            continue
        if layout_name not in layouts:
            fatal_errors.append(
                f"deck_plan slide {idx}: layout {layout_name!r} is supported "
                f"but not declared by template {template_name!r}"
            )
            continue
        slide_plan = plans_by_index.get(idx)
        if not isinstance(slide_plan, dict):
            fatal_errors.append(
                f"deck_plan slide {idx}: no slide_plan with index {idx} "
                f"under {plans_dir}"
            )
            continue

        # Fail closed on a stale / mismatched slide_plan. Matching by JSON
        # index is not enough: the slide_plan's own `layout` and `title`
        # must also agree with the deck_plan slide before we feed its
        # blocks into a layout-specific generator. If they drift (e.g. a
        # slide_plan is hand-edited to a different layout while the
        # deck_plan still names the original), the generator would
        # otherwise silently emit a render_model whose declared layout
        # came from the deck_plan but whose content came from the wrong
        # slide_plan. The workspace validator's check_slide_plan_coverage
        # enforces the same pair of equalities; we mirror it here so the
        # generator never runs on stale input.
        sp_layout = slide_plan.get("layout")
        if sp_layout != layout_name:
            fatal_errors.append(
                f"deck_plan slide {idx}: slide_plan.layout {sp_layout!r} "
                f"does not match deck_plan.layout {layout_name!r} "
                f"(stale or mismatched slide_plan)"
            )
            continue
        sp_title = slide_plan.get("title")
        deck_title = slide_d.get("title")
        if sp_title != deck_title:
            fatal_errors.append(
                f"deck_plan slide {idx}: slide_plan.title {sp_title!r} "
                f"does not match deck_plan.title {deck_title!r} "
                f"(stale or mismatched slide_plan)"
            )
            continue

        srcs = _as_list(slide_d.get("source_refs")) or []
        if not srcs:
            fatal_errors.append(
                f"deck_plan slide {idx}: source_refs is missing or empty"
            )
            continue
        bad = [r for r in srcs if not isinstance(r, str) or r not in brief_refs]
        if bad:
            fatal_errors.append(
                f"deck_plan slide {idx}: source_refs {bad!r} not declared "
                f"in deck_brief.source_refs"
            )
            continue

        try:
            rm = GENERATORS[layout_name](
                slide_plan, slide_d, layouts[layout_name],
                design, manifest_ids, manifest_alt_by_id,
            )
        except GenerationError as exc:
            fatal_errors.append(
                f"deck_plan slide {idx} ({layout_name}): {exc}"
            )
            continue

        errors = _schema_validate(rm, SCHEMAS / "render_model.schema.json")
        if errors:
            fatal_errors.append(
                f"deck_plan slide {idx} ({layout_name}): generated render_model "
                f"fails schema: {'; '.join(errors)}"
            )
            continue

        out_path = out_dir / f"{idx:02d}_{layout_name}.json"
        out_path.write_text(json.dumps(rm, indent=2) + "\n")
        generated.append((idx, layout_name, out_path))

    # Cross-check the on-disk render_models against the rest of the workspace
    # (canvas vs design_system, slot bounds, image_ref vs manifest, etc.).
    # The generator already enforces most of these — this is the same gate
    # the workspace runner applies, and we want the script to fail if its
    # own output ever drifts out of agreement with the workspace.
    cross_results = check_render_models(ws, tr)
    cross_failures = [r for r in cross_results if not r.ok]
    if cross_failures:
        for r in cross_failures:
            fatal_errors.append(
                f"workspace cross-check failed for generator output: "
                f"{r.name} — {r.detail}"
            )

    if cleaned_stale:
        print(f"Cleaned {len(cleaned_stale)} stale render_model file(s) "
              f"before regeneration (these will only re-appear if the "
              f"current run succeeds for those slides):")
        for f in cleaned_stale:
            print(f"  [CLEAN] {f.relative_to(ws)}")
    print(f"Generated {len(generated)} render_model(s):")
    for idx, layout_name, p in generated:
        print(f"  [GEN]  slide {idx:>2} ({layout_name}) -> {p.relative_to(ws)}")
    if skipped:
        print(f"Skipped {len(skipped)} slide(s) with layouts not yet supported "
              f"by the generator (supported: {', '.join(SUPPORTED_LAYOUTS)}):")
        for idx, layout_name in skipped:
            print(f"  [SKIP] slide {idx:>2}: layout {layout_name!r} "
                  f"not implemented")
    else:
        print("Skipped 0 slide(s) — all slides used supported layouts.")
    if fatal_errors:
        print(f"\nFAIL: {len(fatal_errors)} generation error(s):",
              file=sys.stderr)
        for err in fatal_errors:
            print(f"  [FAIL] {err}", file=sys.stderr)
        return 1
    print(
        f"\nOK: render_model generation succeeded for {len(generated)} "
        f"slide(s); skipped {len(skipped)} unsupported layout(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
