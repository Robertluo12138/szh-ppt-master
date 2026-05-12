#!/usr/bin/env python3
"""generate_svg_previews.py

Deterministic, stdlib-only SVG preview generator. Reads a workspace's
existing `render_models/*.json` and writes
`<workspace>/svg_previews/<stem>.svg` for each.

SOURCE OF TRUTH
    The renderer consumes `render_model.json` only. It does NOT read
    `slide_plan.json` — the controlled primitive contract cannot be
    bypassed (see references/svg-design-rules.md and
    references/slide-contracts.md).

SUPPORTED PRIMITIVE KINDS
    text         single-line <text> sized from design_system.typography
    line         <line> drawn corner-to-corner inside bounds
    shape        <rect>, <rect rx>, or <ellipse>
    image_slot   <image> whose href is the workspace-relative local_path
                 declared by image_manifest — no URLs, no '..', no
                 absolute paths
    kpi          composite <g> with <text> runs for label, value, delta
    table        composite <g> with grid <rect> outline, bold header row
                 (filled with palette.background, stroked in
                 palette.primary), and one <text> per cell sized from
                 typography.body; intended as a preview of the native
                 PPTX table the exporter emits

    Any other kind (`chart_placeholder` or any future kind) fails closed
    on that slide. Adding renderer support requires a paired scaffold
    update.

TOKEN RESOLUTION
    palette.X is resolved against design_system.palette.X (raw hex) and
    the resolved value MUST match ^#[0-9A-Fa-f]{6}$. A non-hex palette
    value is rejected fail-closed — XML escaping protects against XML
    breakage, but a value like `url(javascript:alert(1))` would be
    dereferenced by an SVG consumer if emitted, so the resolver
    refuses to emit anything that does not look like a hex color.
    typography.heading|body is resolved against design_system.typography
    and font_family is checked against ^[^,]+(\\s*,\\s*[^,]+)*$
    (CSS-style fallback chain, same pattern the design_system schema
    declares). size_pt must be a positive number. An unresolved or
    schema-violating token fails closed.

PREFLIGHT (runs BEFORE the svg_previews/ cleanup sweep)
    - design_system.json is schema-validated against
      schemas/design_system.schema.json. The renderer emits resolved
      palette / typography values into the SVG, so a malformed
      design_system must not reach cleanup.
    - image_manifest.json is schema-validated against
      schemas/image_manifest.schema.json, and every declared
      images[].local_path is run through local_path_is_safe. Without
      this gate, a workspace whose manifest is `{}` (missing the
      required `images` array) or lists unsafe paths could silently
      pass when the current render_models happen not to use image
      slots — and then the next slide that adds one would crash.
    - Each render_model is schema-validated against
      schemas/render_model.schema.json before its primitives are
      rendered. A schema failure on a render_model is per-slide
      fatal but does not abort the rest of the run.
    Any preflight failure exits non-zero, prints no `OK:`, and does
    NOT delete any pre-existing svg_previews/*.svg.

IMAGE REFERENCES
    Resolved through image_manifest.images[].id -> local_path. The
    local_path must pass the same fail-closed path-safety rule the
    workspace validator already enforces (no URI scheme prefix, no
    absolute paths, no leading backslash, no protocol-relative, no
    '..' segment, no empty string). An image_ref not declared in the
    manifest, or declared with an unsafe local_path, fails closed.

OUTPUT
    <workspace>/svg_previews/<stem>.svg, where <stem> matches the
    corresponding render_model file stem (zero-padded index +
    layout, e.g. 01_cover.svg).

STALE-FILE CLEANUP
    Before generating, every existing `svg_previews/*.svg` is removed.
    The workspace validator pairs each render_model with a matching
    svg_preview by stem, so the *.svg namespace is generator-owned.
    Non-SVG files (READMEs, NOTES.md, ...) are preserved — the cleanup
    glob targets *.svg only.

FAIL-CLOSED GATES (every gate exits non-zero on failure)
    - workspace / template-root not a directory;
    - design_system or image_manifest missing, unloadable, or wrong
      root shape;
    - render_models/ missing or empty;
    - render_model fails schema validation
      (schemas/render_model.schema.json);
    - unsupported primitive kind on a slide;
    - palette / typography token does not resolve;
    - image_slot.image_ref not declared in manifest or declared with
      an unsafe local_path;
    - generated SVG fails the same `check_svg_previews` gate the
      workspace validator runs, so output drift fails immediately.

OUT OF SCOPE
    PPTX export, D-One, Qoder, charts, broad SVG parsing,
    arbitrary-SVG-to-PPTX conversion, public network behavior.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validate_scaffold import local_path_is_safe  # noqa: E402
from validate_workspace import (  # noqa: E402
    _try_load,
    _as_dict,
    _as_list,
    _schema_validate,
    check_svg_previews,
)

SCHEMAS = REPO_ROOT / "schemas"
SUPPORTED_PRIMITIVE_KINDS = ("text", "line", "shape", "image_slot", "kpi", "table")

# pt -> px ratio at 96 dpi. SVG accepts mixed units; pt is fine on its
# own, but our canvas is in px, so we keep one consistent unit (px) for
# every numeric value the renderer emits.
PT_TO_PX = 4.0 / 3.0

# Padding inside bounds before text starts, for both text and kpi.
TEXT_INSET_X = 8

# Strict patterns the renderer enforces on every design-token VALUE
# before emitting it into the SVG. These mirror the patterns in
# schemas/design_system.schema.json but are re-applied here as a
# defense-in-depth gate: if the renderer is run before (or instead of)
# schema validation, an attacker-controlled design_system could
# otherwise inject SVG-interpretable strings into `fill` / `stroke` /
# `font-family` attributes — XML escaping prevents XML breakage but
# does NOT prevent semantically meaningful injection like
# `fill="url(javascript:alert(1))"` (a browser will dereference the
# `url(...)`). Fail closed on anything that does not match.
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_FONT_FAMILY = re.compile(r"^[^,]+(\s*,\s*[^,]+)*$")


class RenderError(RuntimeError):
    """Raised on a per-slide rendering failure. Caller catches and
    records the slide as fatal without aborting the rest of the run."""


def _fatal(msg: str) -> int:
    print(f"FAIL: {msg}", file=sys.stderr)
    return 1


def _load_required_object(path: Path, label: str) -> tuple[dict | None, str]:
    data, err = _try_load(path)
    if data is None:
        return (None, f"{label} not loadable: {err}")
    if not isinstance(data, dict):
        return (None, f"{label} root is not an object: got {type(data).__name__}")
    return (data, "")


def _resolve_palette(design: dict, token: str) -> str:
    """palette.X -> design_system.palette.X (raw hex).

    The resolved value is strictly validated against ^#[0-9A-Fa-f]{6}$
    before being returned, so a malformed / attacker-controlled
    design_system cannot inject SVG-interpretable strings like
    `url(javascript:alert(1))` into a `fill` / `stroke` / `color`
    attribute. XML escaping protects against XML breakage but NOT
    against `url(...)` dereferencing by the SVG consumer."""
    if not token.startswith("palette."):
        raise RenderError(f"non-palette token used as color: {token!r}")
    key = token.split(".", 1)[1]
    palette = _as_dict(design.get("palette")) or {}
    value = palette.get(key)
    if not isinstance(value, str) or not value:
        raise RenderError(
            f"palette token {token!r} does not resolve in design_system.palette"
        )
    if not _HEX_COLOR.match(value):
        raise RenderError(
            f"palette token {token!r} resolves to an unsafe value "
            f"{value!r}; expected a 6-digit hex color matching "
            f"^#[0-9A-Fa-f]{{6}}$ (defense-in-depth: a non-hex palette "
            f"value could be a SVG `url(...)` reference and would be "
            f"dereferenced by the consumer)"
        )
    return value


def _resolve_typography(design: dict, token: str) -> tuple[str, float]:
    """typography.heading|body -> (font_family, size_pt).

    font_family is strictly validated against the same CSS-style
    fallback-chain pattern the design_system schema declares, so a
    malformed design_system cannot smuggle structurally broken values
    (e.g. trailing comma, empty entry) into the SVG `font-family`
    attribute. size_pt must be a positive number."""
    if not token.startswith("typography."):
        raise RenderError(f"non-typography token used as typography: {token!r}")
    role = token.split(".", 1)[1]
    typo = _as_dict(design.get("typography")) or {}
    entry = _as_dict(typo.get(role))
    if entry is None:
        raise RenderError(
            f"typography token {token!r} does not resolve in design_system.typography"
        )
    family = entry.get("font_family")
    size = entry.get("size_pt")
    if not isinstance(family, str) or not family:
        raise RenderError(f"typography {token!r}: font_family missing or not a string")
    if not _FONT_FAMILY.match(family):
        raise RenderError(
            f"typography {token!r}: font_family {family!r} does not match "
            f"^[^,]+(\\s*,\\s*[^,]+)*$ (expected a CSS-style fallback chain)"
        )
    if not isinstance(size, (int, float)) or isinstance(size, bool) or size <= 0:
        raise RenderError(f"typography {token!r}: size_pt missing or not a positive number")
    return (family, float(size))


def _attrs(items: dict) -> str:
    """Stable, deterministic attribute serialization for SVG elements.
    Keys are emitted in insertion order; values are XML-escaped. Numeric
    values are emitted as plain integers when whole, else with the
    minimal float repr."""
    parts: list[str] = []
    for k, v in items.items():
        if isinstance(v, bool):
            raise RenderError(f"bool attribute value not allowed: {k}={v!r}")
        if isinstance(v, int):
            sv = str(v)
        elif isinstance(v, float):
            sv = (f"{v:.3f}").rstrip("0").rstrip(".")
            if sv in ("", "-"):
                sv = "0"
        else:
            sv = xml_escape(str(v), {"\"": "&quot;"})
        parts.append(f'{k}="{sv}"')
    return " ".join(parts)


def _bounds_tuple(bounds: dict) -> tuple[int, int, int, int]:
    return (
        int(bounds["x"]), int(bounds["y"]),
        int(bounds["w"]), int(bounds["h"]),
    )


def _px(value: float) -> str:
    """Compact pixel string with up to 3 decimal places and no trailing zeros."""
    s = f"{value:.3f}".rstrip("0").rstrip(".")
    if s in ("", "-"):
        s = "0"
    return s + "px"


def _render_text(prim: dict, design: dict, content_override: str | None = None) -> str:
    x, y, w, h = _bounds_tuple(prim["bounds"])
    style = _as_dict(prim.get("style")) or {}
    color_token = style.get("color_token")
    typo_token = style.get("typography_token")
    if not isinstance(color_token, str):
        raise RenderError("text primitive missing style.color_token")
    if not isinstance(typo_token, str):
        raise RenderError("text primitive missing style.typography_token")
    color = _resolve_palette(design, color_token)
    family, size_pt = _resolve_typography(design, typo_token)
    size_px = size_pt * PT_TO_PX
    payload = _as_dict(prim.get("text")) or {}
    text_content = content_override if content_override is not None else payload.get("content")
    if not isinstance(text_content, str) or not text_content:
        raise RenderError("text primitive has no non-empty content")
    # Position baseline one font-height down from the top of the bounds,
    # which keeps the glyph visually inside the bounds rectangle for the
    # common case of single-line previews. Multi-line text wrapping is
    # not implemented; the preview shows one line and is clipped by the
    # consumer if it overflows.
    baseline_y = y + size_px
    attrs = {
        "x": x + TEXT_INSET_X,
        "y": round(baseline_y, 3),
        "font-family": family,
        "font-size": _px(size_px),
        "fill": color,
    }
    role = payload.get("role")
    if role == "heading":
        attrs["font-weight"] = "700"
    body = xml_escape(text_content)
    return f"  <text {_attrs(attrs)}>{body}</text>"


def _render_line(prim: dict, design: dict) -> str:
    x, y, w, h = _bounds_tuple(prim["bounds"])
    style = _as_dict(prim.get("style")) or {}
    stroke_token = style.get("stroke_token")
    if not isinstance(stroke_token, str):
        raise RenderError("line primitive missing style.stroke_token")
    stroke = _resolve_palette(design, stroke_token)
    width = style.get("stroke_width_px", 1)
    if not isinstance(width, int) or isinstance(width, bool) or width < 1:
        raise RenderError("line primitive has invalid stroke_width_px")
    payload = _as_dict(prim.get("line")) or {}
    dash = payload.get("stroke_style") == "dashed"
    attrs = {
        "x1": x, "y1": y,
        "x2": x + w, "y2": y + h,
        "stroke": stroke,
        "stroke-width": width,
    }
    if dash:
        attrs["stroke-dasharray"] = f"{width * 4} {width * 2}"
    return f"  <line {_attrs(attrs)}/>"


def _render_shape(prim: dict, design: dict) -> str:
    x, y, w, h = _bounds_tuple(prim["bounds"])
    style = _as_dict(prim.get("style")) or {}
    payload = _as_dict(prim.get("shape")) or {}
    shape_kind = payload.get("shape_kind")
    fill_token = style.get("fill_token")
    stroke_token = style.get("stroke_token")
    stroke_width = style.get("stroke_width_px")
    attrs: dict = {}
    if shape_kind == "rectangle" or shape_kind == "rounded_rectangle":
        attrs.update({"x": x, "y": y, "width": w, "height": h})
        if shape_kind == "rounded_rectangle":
            r = payload.get("corner_radius_px", 0)
            if not isinstance(r, int) or isinstance(r, bool) or r < 0:
                raise RenderError("rounded_rectangle has invalid corner_radius_px")
            if r > 0:
                attrs["rx"] = r
                attrs["ry"] = r
        tag = "rect"
    elif shape_kind == "ellipse":
        cx = x + w // 2
        cy = y + h // 2
        rx = w // 2
        ry = h // 2
        attrs.update({"cx": cx, "cy": cy, "rx": rx, "ry": ry})
        tag = "ellipse"
    else:
        raise RenderError(f"shape primitive has unsupported shape_kind: {shape_kind!r}")
    if isinstance(fill_token, str):
        attrs["fill"] = _resolve_palette(design, fill_token)
    else:
        attrs["fill"] = "none"
    if isinstance(stroke_token, str):
        attrs["stroke"] = _resolve_palette(design, stroke_token)
        if not isinstance(stroke_width, int) or isinstance(stroke_width, bool) or stroke_width < 1:
            raise RenderError("shape primitive has stroke_token but invalid stroke_width_px")
        attrs["stroke-width"] = stroke_width
    return f"  <{tag} {_attrs(attrs)}/>"


def _render_image_slot(
    prim: dict,
    manifest_paths: dict,
    manifest_alts: dict,
) -> str:
    x, y, w, h = _bounds_tuple(prim["bounds"])
    payload = _as_dict(prim.get("image_slot")) or {}
    image_ref = payload.get("image_ref")
    if not isinstance(image_ref, str) or not image_ref:
        raise RenderError("image_slot primitive missing image_ref")
    if image_ref not in manifest_paths:
        raise RenderError(
            f"image_slot primitive references image id {image_ref!r} "
            f"that is not declared in image_manifest"
        )
    local_path = manifest_paths[image_ref]
    if not local_path_is_safe(local_path):
        raise RenderError(
            f"image_slot primitive resolves to unsafe local_path "
            f"{local_path!r} for image id {image_ref!r}"
        )
    alt = payload.get("alt_text") or manifest_alts.get(image_ref) or ""
    attrs = {
        "x": x, "y": y, "width": w, "height": h,
        "href": local_path,
        "preserveAspectRatio": "xMidYMid meet",
    }
    if isinstance(alt, str) and alt:
        # SVG accessibility: <title> child of the <image>.
        return (
            f"  <image {_attrs(attrs)}>"
            f"<title>{xml_escape(alt)}</title>"
            f"</image>"
        )
    return f"  <image {_attrs(attrs)}/>"


def _render_kpi(prim: dict, design: dict) -> str:
    x, y, w, h = _bounds_tuple(prim["bounds"])
    style = _as_dict(prim.get("style")) or {}
    color_token = style.get("color_token")
    if not isinstance(color_token, str):
        raise RenderError("kpi primitive missing style.color_token")
    color = _resolve_palette(design, color_token)
    body_family, body_pt = _resolve_typography(design, "typography.body")
    head_family, head_pt = _resolve_typography(design, "typography.heading")
    payload = _as_dict(prim.get("kpi")) or {}
    label = payload.get("label")
    value = payload.get("value")
    delta = payload.get("delta")
    if not isinstance(label, str) or not label:
        raise RenderError("kpi primitive missing label")
    if not isinstance(value, str) or not value:
        raise RenderError("kpi primitive missing value")
    # Stack vertically: label (small), value (large heading), delta (small).
    label_size_px = body_pt * PT_TO_PX
    value_size_px = head_pt * PT_TO_PX
    delta_size_px = body_pt * PT_TO_PX
    label_y = y + label_size_px + 8
    value_y = label_y + value_size_px + 12
    tx = x + TEXT_INSET_X
    parts: list[str] = ["  <g>"]
    label_attrs = {
        "x": tx,
        "y": round(label_y, 3),
        "font-family": body_family,
        "font-size": _px(label_size_px),
        "fill": color,
    }
    parts.append(f"    <text {_attrs(label_attrs)}>{xml_escape(label)}</text>")
    value_attrs = {
        "x": tx,
        "y": round(value_y, 3),
        "font-family": head_family,
        "font-size": _px(value_size_px),
        "font-weight": "700",
        "fill": color,
    }
    parts.append(f"    <text {_attrs(value_attrs)}>{xml_escape(value)}</text>")
    if isinstance(delta, str) and delta:
        delta_y = value_y + delta_size_px + 8
        delta_attrs = {
            "x": tx,
            "y": round(delta_y, 3),
            "font-family": body_family,
            "font-size": _px(delta_size_px),
            "fill": color,
        }
        parts.append(f"    <text {_attrs(delta_attrs)}>{xml_escape(delta)}</text>")
    parts.append("  </g>")
    return "\n".join(parts)


def _render_table(prim: dict, design: dict) -> str:
    """Render a controlled `table` primitive into a composite <g>.

    Cells are laid out on a deterministic uniform grid: every column has
    the same width and every body row has the same height. The header
    row uses the body typography size scaled to the same row height; the
    rendering is a preview, not a typographically precise table — the
    native PPTX table emitter is the source of truth for export.

    Integer arithmetic only so the output is byte-stable. Failure to
    distribute (zero-width column, zero-height row) is a per-slide
    RenderError so the issue surfaces in the run rather than producing
    a degenerate SVG."""
    x, y, w, h = _bounds_tuple(prim["bounds"])
    style = _as_dict(prim.get("style")) or {}
    color_token = style.get("color_token")
    if not isinstance(color_token, str):
        raise RenderError("table primitive missing style.color_token")
    text_color = _resolve_palette(design, color_token)
    grid_color = _resolve_palette(design, "palette.primary")
    header_fill = _resolve_palette(design, "palette.background")
    body_family, body_pt = _resolve_typography(design, "typography.body")
    body_size_px = body_pt * PT_TO_PX
    payload = _as_dict(prim.get("table")) or {}
    columns = payload.get("columns")
    rows = payload.get("rows")
    if not isinstance(columns, list) or not columns:
        raise RenderError("table primitive missing non-empty columns")
    if not isinstance(rows, list) or not rows:
        raise RenderError("table primitive missing non-empty rows")
    col_count = len(columns)
    row_count = len(rows) + 1  # header + body rows
    col_w = w // col_count
    row_h = h // row_count
    if col_w <= 0 or row_h <= 0:
        raise RenderError(
            f"table primitive bounds {w}x{h} too small for "
            f"{col_count} cols x {row_count} rows"
        )
    parts: list[str] = ["  <g>"]
    # Header background.
    header_bg_attrs = {
        "x": x, "y": y, "width": col_count * col_w, "height": row_h,
        "fill": header_fill,
        "stroke": grid_color, "stroke-width": 2,
    }
    parts.append(f"    <rect {_attrs(header_bg_attrs)}/>")
    # Outer body outline. Header rect already drew the top edge; the
    # body outline adds the remaining grid box.
    body_outline_attrs = {
        "x": x, "y": y + row_h,
        "width": col_count * col_w, "height": (row_count - 1) * row_h,
        "fill": "none",
        "stroke": grid_color, "stroke-width": 2,
    }
    parts.append(f"    <rect {_attrs(body_outline_attrs)}/>")
    # Interior column dividers (skip the outer left/right).
    for c in range(1, col_count):
        div_attrs = {
            "x1": x + c * col_w, "y1": y,
            "x2": x + c * col_w, "y2": y + row_count * row_h,
            "stroke": grid_color, "stroke-width": 1,
        }
        parts.append(f"    <line {_attrs(div_attrs)}/>")
    # Interior row dividers (skip the outer top/bottom).
    for r in range(1, row_count):
        div_attrs = {
            "x1": x, "y1": y + r * row_h,
            "x2": x + col_count * col_w, "y2": y + r * row_h,
            "stroke": grid_color, "stroke-width": 1,
        }
        parts.append(f"    <line {_attrs(div_attrs)}/>")
    # Cell text. Baseline anchored near the row's vertical midline so
    # the preview stays inside its row regardless of body font size.
    def _cell_text(col_idx: int, row_idx: int, content: str, *, bold: bool) -> str:
        tx = x + col_idx * col_w + TEXT_INSET_X
        ty = y + row_idx * row_h + (row_h + int(body_size_px)) // 2
        cell_attrs = {
            "x": tx,
            "y": ty,
            "font-family": body_family,
            "font-size": _px(body_size_px),
            "fill": text_color,
        }
        if bold:
            cell_attrs["font-weight"] = "700"
        return (
            f"    <text {_attrs(cell_attrs)}>{xml_escape(content)}</text>"
        )

    for c_i, header in enumerate(columns):
        if not isinstance(header, str) or not header:
            raise RenderError(
                f"table primitive columns[{c_i}] is not a non-empty string"
            )
        parts.append(_cell_text(c_i, 0, header, bold=True))
    for r_i, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != col_count:
            raise RenderError(
                f"table primitive rows[{r_i}] has the wrong cell count "
                f"(expected {col_count})"
            )
        for c_i, cell in enumerate(row):
            if not isinstance(cell, str) or not cell:
                raise RenderError(
                    f"table primitive rows[{r_i}][{c_i}] is not a "
                    f"non-empty string"
                )
            parts.append(_cell_text(c_i, r_i + 1, cell, bold=False))
    parts.append("  </g>")
    return "\n".join(parts)


def _render_primitive(
    prim: dict,
    design: dict,
    manifest_paths: dict,
    manifest_alts: dict,
) -> str:
    kind = prim.get("kind")
    if kind == "text":
        return _render_text(prim, design)
    if kind == "line":
        return _render_line(prim, design)
    if kind == "shape":
        return _render_shape(prim, design)
    if kind == "image_slot":
        return _render_image_slot(prim, manifest_paths, manifest_alts)
    if kind == "kpi":
        return _render_kpi(prim, design)
    if kind == "table":
        return _render_table(prim, design)
    # Fail closed for chart_placeholder / anything else — these are
    # absent from current generator output and have no renderer.
    raise RenderError(
        f"primitive kind {kind!r} is not supported by the SVG renderer "
        f"today (supported: {SUPPORTED_PRIMITIVE_KINDS})"
    )


def _render_svg(render_model: dict, design: dict, manifest_paths: dict, manifest_alts: dict) -> str:
    canvas = render_model["canvas"]
    width = int(canvas["width_px"])
    height = int(canvas["height_px"])
    # Resolve the background colour through _resolve_palette so the
    # ^#[0-9A-Fa-f]{6}$ gate applies to the background rect just like it
    # does to every primitive. design_system.schema.json declares
    # palette.background as required and constrains it to hex, but the
    # renderer must not rely on schema validation alone here — a direct
    # dict read would leak an unsafe value into the SVG's first <rect>
    # `fill` attribute, defeating the rest of the gate.
    bg = _resolve_palette(design, "palette.background")
    bg_attrs = {
        "x": 0, "y": 0, "width": width, "height": height,
        "fill": bg,
    }
    body: list[str] = [f"  <rect {_attrs(bg_attrs)}/>"]
    for prim in render_model["primitives"]:
        if not isinstance(prim, dict):
            raise RenderError(
                f"render_model primitive is not an object: got {type(prim).__name__}"
            )
        body.append(_render_primitive(prim, design, manifest_paths, manifest_alts))
    header = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}">'
    )
    return header + "\n" + "\n".join(body) + "\n</svg>\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic SVG preview generator from per-slide render_models.",
    )
    parser.add_argument("--workspace", required=True, type=Path,
                        help="Caller-supplied workspace directory.")
    parser.add_argument("--template-root", required=True, type=Path,
                        help="Directory containing template subdirectories. "
                             "Used by the post-write SVG cross-check.")
    args = parser.parse_args(argv)

    ws = args.workspace
    tr = args.template_root
    if not ws.is_dir():
        return _fatal(f"workspace is not a directory: {ws}")
    if not tr.is_dir():
        return _fatal(f"template-root is not a directory: {tr}")

    design, err = _load_required_object(ws / "design_system.json", "design_system.json")
    if design is None:
        return _fatal(err)
    manifest, err = _load_required_object(ws / "image_manifest.json", "image_manifest.json")
    if manifest is None:
        return _fatal(err)

    # Schema-validate design_system before any rendering. The renderer
    # emits resolved palette / typography values into SVG attributes,
    # and a malformed design_system whose values don't match the schema
    # patterns could otherwise smuggle SVG-interpretable strings into
    # `fill` / `stroke` / `font-family`. The per-token resolvers also
    # re-check the patterns at use time (defense-in-depth), but this
    # up-front gate stops a bad workspace before any output is produced.
    design_errors = _schema_validate(design, SCHEMAS / "design_system.schema.json")
    if design_errors:
        return _fatal(
            f"design_system.json fails design_system.schema.json: "
            f"{'; '.join(design_errors)}"
        )

    # Schema-validate image_manifest before cleanup. Without this gate, a
    # workspace whose image_manifest.json is e.g. `{}` (no required
    # `images` array) but whose render_models currently use no image
    # slots would silently report OK — and then the next slide that
    # adds an image_slot would crash. Path-safety on every declared
    # local_path is also enforced here so the cleanup phase below cannot
    # delete pre-existing svg_previews/*.svg on a manifest that lists
    # unsafe references; the schema's own description states '..' and
    # leading '/' are forbidden, but the runtime predicate is the
    # authoritative gate.
    manifest_errors = _schema_validate(manifest, SCHEMAS / "image_manifest.schema.json")
    if manifest_errors:
        return _fatal(
            f"image_manifest.json fails image_manifest.schema.json: "
            f"{'; '.join(manifest_errors)}"
        )
    for img in _as_list(manifest.get("images")) or []:
        img_d = _as_dict(img)
        if img_d is None:
            # Schema validation already enforces this, but stay defensive
            # so a future schema loosening cannot regress the path gate.
            return _fatal(
                f"image_manifest.images contains a non-object entry: "
                f"{type(img).__name__}"
            )
        img_id = img_d.get("id")
        local_path = img_d.get("local_path")
        if not isinstance(local_path, str):
            return _fatal(
                f"image_manifest entry {img_id!r}: local_path is not a string"
            )
        if not local_path_is_safe(local_path):
            return _fatal(
                f"image_manifest entry {img_id!r} has unsafe local_path "
                f"{local_path!r}; refusing to render before validating "
                f"image_manifest path-safety (no URI scheme, no absolute, "
                f"no '..', no protocol-relative)"
            )

    rm_dir = ws / "render_models"
    if not rm_dir.is_dir():
        return _fatal(
            f"render_models/ not found at {rm_dir} — run "
            f"generate_render_models.py first"
        )
    rm_files = sorted(rm_dir.glob("*.json"))
    if not rm_files:
        return _fatal(
            f"render_models/ at {rm_dir} contains no *.json files — "
            f"run generate_render_models.py first"
        )

    manifest_paths: dict[str, str] = {}
    manifest_alts: dict[str, str] = {}
    for img in _as_list(manifest.get("images")) or []:
        img_d = _as_dict(img)
        if img_d is None:
            continue
        img_id = img_d.get("id")
        local_path = img_d.get("local_path")
        if isinstance(img_id, str) and isinstance(local_path, str):
            manifest_paths[img_id] = local_path
            alt = img_d.get("alt_text")
            if isinstance(alt, str):
                manifest_alts[img_id] = alt

    out_dir = ws / "svg_previews"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Fail-closed cleanup: every *.svg in svg_previews/ is generator-owned.
    # Non-SVG files (NOTES.md, checklist.txt, ...) are preserved — the glob
    # targets *.svg only. The cleanup matches the render_model generator's
    # *.json cleanup philosophy: a stale lie cannot survive a fail-closed
    # mismatch or a render_model deletion.
    cleaned_stale: list[Path] = []
    for stale in sorted(out_dir.glob("*.svg")):
        stale.unlink()
        cleaned_stale.append(stale)

    generated: list[Path] = []
    fatal_errors: list[str] = []

    for rm_file in rm_files:
        rm_raw, err = _try_load(rm_file)
        if rm_raw is None:
            fatal_errors.append(f"{rm_file.relative_to(ws)}: not loadable: {err}")
            continue
        rm = _as_dict(rm_raw)
        if rm is None:
            fatal_errors.append(
                f"{rm_file.relative_to(ws)}: root is not an object "
                f"(got {type(rm_raw).__name__})"
            )
            continue
        schema_errors = _schema_validate(rm, SCHEMAS / "render_model.schema.json")
        if schema_errors:
            fatal_errors.append(
                f"{rm_file.relative_to(ws)}: render_model fails schema: "
                f"{'; '.join(schema_errors)}"
            )
            continue
        try:
            svg = _render_svg(rm, design, manifest_paths, manifest_alts)
        except RenderError as exc:
            fatal_errors.append(f"{rm_file.relative_to(ws)}: {exc}")
            continue
        out_path = out_dir / f"{rm_file.stem}.svg"
        out_path.write_text(svg)
        generated.append(out_path)

    # Post-write cross-check: run the same gate the workspace validator
    # uses. Catches output drift between the renderer and the validator
    # (canvas mismatch, forbidden element, undeclared image reference,
    # element outside the canvas, ...).
    cross_results = check_svg_previews(ws, tr)
    cross_failures = [r for r in cross_results if not r.ok]
    if cross_failures:
        for r in cross_failures:
            fatal_errors.append(
                f"svg_previews cross-check failed for generator output: "
                f"{r.name} — {r.detail}"
            )

    if cleaned_stale:
        print(
            f"Cleaned {len(cleaned_stale)} stale svg_preview file(s) "
            f"before regeneration (these will only re-appear if the "
            f"current run succeeds for those slides):"
        )
        for f in cleaned_stale:
            print(f"  [CLEAN] {f.relative_to(ws)}")
    print(f"Generated {len(generated)} svg_preview(s):")
    for p in generated:
        print(f"  [GEN]  {p.relative_to(ws)}")
    if fatal_errors:
        print(f"\nFAIL: {len(fatal_errors)} svg-preview error(s):", file=sys.stderr)
        for err in fatal_errors:
            print(f"  [FAIL] {err}", file=sys.stderr)
        return 1
    print(
        f"\nOK: svg_preview generation succeeded for {len(generated)} "
        f"slide(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
