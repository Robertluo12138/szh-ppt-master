#!/usr/bin/env python3
"""export_pptx.py

Stdlib-only, fail-closed, deterministic native PPTX exporter for the
editable-ppt pipeline. Consumes a workspace's `render_models/*.json`
directly and emits one editable `.pptx` covering the currently
supported subset:

    layouts:         cover, kpi_dashboard
    primitive kinds: text, line, shape, image_slot, kpi

This is NOT a generic SVG-to-PPTX converter. It does NOT parse SVG, it
does NOT screenshot a slide, and it does NOT rasterize a slide into a
single picture. It also does NOT embed media — image_slot primitives
are emitted as native PPTX placeholder shapes carrying the
image_manifest alt_text. SVG / PNG / JPG embedding (and the PNG
fallback PowerPoint needs for SVG) remain TODO.

INPUTS (all workspace-relative; the same artifacts validate_workspace
exercises today)
    design_system.json  — palette + typography + grid
    image_manifest.json — image_ref id -> local_path + alt_text
    render_models/*.json — one per supported slide (deterministic
                           order: sorted by file stem)

OUTPUT
    A single .pptx ZIP at --output. The OOXML package contains:
      [Content_Types].xml
      _rels/.rels
      ppt/presentation.xml
      ppt/_rels/presentation.xml.rels
      ppt/slides/slide{N}.xml             (one per exported slide)
      ppt/slides/_rels/slide{N}.xml.rels  (one per exported slide)
      ppt/slideLayouts/slideLayout1.xml
      ppt/slideLayouts/_rels/slideLayout1.xml.rels
      ppt/slideMasters/slideMaster1.xml
      ppt/slideMasters/_rels/slideMaster1.xml.rels
      ppt/theme/theme1.xml

PRIMITIVE -> NATIVE PPTX OBJECT MAPPING
    text         <p:sp> textBox with <p:txBody> and one <a:r> run
    line         <p:cxnSp> straight connector (prstGeom prst="line")
    shape        <p:sp> with prstGeom prst in {rect, roundRect, ellipse}
    kpi          <p:sp> textBox with stacked <a:p> paragraphs
                 (label / value / optional delta) — fully editable
    image_slot   <p:sp> placeholder rectangle whose <a:txBody> carries
                 the image_manifest alt_text. Media embedding is TODO.

PREFLIGHT GATES (run BEFORE any output ZIP is created)
    - workspace is a directory; output extension is `.pptx`
      (case-insensitive); output parent directory is created with
      mkdir(parents=True, exist_ok=True) only when --output sits inside
      an existing or createable tree (consistent with how
      generate_render_models / generate_svg_previews create their
      workspace-internal directories);
    - design_system.json schema-validates against
      schemas/design_system.schema.json;
    - image_manifest.json schema-validates against
      schemas/image_manifest.schema.json and every declared
      images[].local_path passes local_path_is_safe;
    - render_models/ exists and contains at least one *.json file;
    - every render_model file schema-validates against
      schemas/render_model.schema.json;
    - every render_model's `image_slot.image_ref` is declared in
      image_manifest.

PER-SLIDE GATES (every gate FAILS CLOSED for that slide and aborts
the whole run; no partial `.pptx` is written if ANY render_model
trips ANY gate)
    - layout is in SUPPORTED_LAYOUTS (cover, kpi_dashboard); a
      render_model whose layout is outside that set fails closed with
      a per-slide error. The contract is intentionally all-or-nothing:
      the exporter refuses to write a deck that silently drops
      coverage for slides whose layout is not yet implemented.
    - every primitive kind is in SUPPORTED_PRIMITIVE_KINDS (text, line,
      shape, image_slot, kpi); a `table` or `chart_placeholder`
      primitive fails closed with an explicit error.

FAIL-CLOSED OVERALL
    - Fails if any render_model fails any per-slide gate above (no
      `.pptx` is written; the run reports every per-slide failure).
    - Fails if no slide was exported (e.g. render_models/ is empty
      after preflight).
    - Fails if the output extension is not `.pptx`.
    - Fails if the resolved palette / typography token does not match
      the same defense-in-depth patterns the SVG renderer applies
      (hex color ^#[0-9A-Fa-f]{6}$; CSS-style font_family chain).

DETERMINISM
    - Render models are read in sorted file-stem order; the resulting
      `ppt/slides/slide{N}.xml` numbering follows that order
      (slide1.xml is the first exported render_model, slide2.xml the
      second, ...). The original render_model `index` is preserved in
      the slide's non-visual name so the slide can still be traced
      back to its workspace artifact.
    - Shape ids start at 2 and increment per primitive, deterministic.
    - Every ZIP entry is written with a fixed timestamp (1980-01-01).

OUT OF SCOPE
    - SVG / PNG / JPG / GIF media embedding (deferred — image_slot is
      a placeholder shape only).
    - PPTX `table` / `chart_placeholder` emission (deferred — fail
      closed today).
    - Layouts other than cover / kpi_dashboard.
    - Speaker notes, transitions, animations, master/layout palettes
      driven by deck-plan template themes.
    - D-One image generation, Qoder CLI integration, public network
      behavior.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape


def _attr(value: str) -> str:
    """Escape a string for use inside a double-quoted XML attribute.

    `xml.sax.saxutils.escape` only handles `&`, `<`, `>` by default, so
    a schema-valid but quote-bearing input — most notably a typography
    `font_family` like `Calibri "Bold", Helvetica` (the schema pattern
    `^[^,]+(\\s*,\\s*[^,]+)*$` only forbids commas) — would otherwise
    break the resulting `<a:latin typeface="..."/>` attribute. Apply
    this helper to every attribute value that carries data we did not
    fully constrain at the schema level."""
    return xml_escape(value, {'"': '&quot;'})

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validate_scaffold import local_path_is_safe  # noqa: E402
from validate_workspace import (  # noqa: E402
    _try_load,
    _as_dict,
    _as_list,
    _schema_validate,
)

SCHEMAS = REPO_ROOT / "schemas"

SUPPORTED_LAYOUTS = ("cover", "kpi_dashboard")
SUPPORTED_PRIMITIVE_KINDS = ("text", "line", "shape", "image_slot", "kpi")

# 1 px at 96 dpi = 9525 EMU. The render_model canvas (default
# 1920x1080 px) maps to a 20" x 11.25" slide. We do NOT scale to the
# default 16:9 PowerPoint size; matching the canvas exactly keeps the
# pixel coordinates on render_model bounds 1:1 with PPTX EMU placement.
EMU_PER_PX = 9525

# Hundredths of a point: PPTX `sz` attribute on <a:rPr> uses centiPoints.
SZ_PER_PT = 100

# Defense-in-depth patterns mirrored from generate_svg_previews. Even
# when design_system.schema.json has validated the file, the exporter
# re-validates the resolved value to avoid emitting attacker-controlled
# strings into PPTX color/font attributes.
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_FONT_FAMILY = re.compile(r"^[^,]+(\s*,\s*[^,]+)*$")

# OOXML/PresentationML namespaces. Kept inline in the strings below
# for readability; this dict is the source of truth for the package.
_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
}

# Content-Type strings for [Content_Types].xml. Kept as constants so the
# self-test fixtures can introspect them.
CT_RELS = "application/vnd.openxmlformats-package.relationships+xml"
CT_XML = "application/xml"
CT_PRESENTATION = (
    "application/vnd.openxmlformats-officedocument."
    "presentationml.presentation.main+xml"
)
CT_SLIDE = (
    "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
)
CT_SLIDE_LAYOUT = (
    "application/vnd.openxmlformats-officedocument."
    "presentationml.slideLayout+xml"
)
CT_SLIDE_MASTER = (
    "application/vnd.openxmlformats-officedocument."
    "presentationml.slideMaster+xml"
)
CT_THEME = (
    "application/vnd.openxmlformats-officedocument.theme+xml"
)

# OOXML relationship types we emit. NOTE: every entry here is an
# `officeDocument/2006/relationships/*` URI. The exporter does NOT emit
# any external (TargetMode="External") relationships — the
# `validate_pptx_contract.py --pptx` checks reject those.
REL_OFFICE_DOCUMENT = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
    "officeDocument"
)
REL_SLIDE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
)
REL_SLIDE_LAYOUT = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
    "slideLayout"
)
REL_SLIDE_MASTER = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
    "slideMaster"
)
REL_THEME = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
)

_XML_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

# Fixed timestamp for every ZIP entry. Using 1980-01-01 (the ZIP epoch)
# makes the resulting .pptx byte-stable across machines and runs.
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class ExportError(RuntimeError):
    """Raised when a single slide cannot be exported. The caller
    records the failure and continues; the overall run exits non-zero
    if any slide raised."""


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


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
    """palette.X -> raw hex (#RRGGBB). Same defense-in-depth gate as the
    SVG renderer; re-applied here so a misbehaved design_system cannot
    smuggle SVG-style url(...) tokens into the PPTX color attributes."""
    if not isinstance(token, str) or not token.startswith("palette."):
        raise ExportError(f"non-palette token used as color: {token!r}")
    key = token.split(".", 1)[1]
    palette = _as_dict(design.get("palette")) or {}
    value = palette.get(key)
    if not isinstance(value, str) or not value:
        raise ExportError(
            f"palette token {token!r} does not resolve in design_system.palette"
        )
    if not _HEX_COLOR.match(value):
        raise ExportError(
            f"palette token {token!r} resolves to an unsafe value "
            f"{value!r}; expected a 6-digit hex color matching "
            f"^#[0-9A-Fa-f]{{6}}$"
        )
    return value


def _hex_to_srgbclr(hex_color: str) -> str:
    """'#1F3A5F' -> '1F3A5F'. Used in <a:srgbClr val=.../>."""
    return hex_color.lstrip("#").upper()


def _resolve_typography(design: dict, token: str) -> tuple[str, float]:
    """typography.heading|body -> (font_family_chain, size_pt). The font
    family chain pattern is enforced again here as defense-in-depth."""
    if not isinstance(token, str) or not token.startswith("typography."):
        raise ExportError(f"non-typography token used as typography: {token!r}")
    role = token.split(".", 1)[1]
    typo = _as_dict(design.get("typography")) or {}
    entry = _as_dict(typo.get(role))
    if entry is None:
        raise ExportError(
            f"typography token {token!r} does not resolve in "
            f"design_system.typography"
        )
    family = entry.get("font_family")
    size = entry.get("size_pt")
    if not isinstance(family, str) or not family:
        raise ExportError(
            f"typography {token!r}: font_family missing or not a string"
        )
    if not _FONT_FAMILY.match(family):
        raise ExportError(
            f"typography {token!r}: font_family {family!r} does not "
            f"match ^[^,]+(\\s*,\\s*[^,]+)*$ (expected a CSS-style chain)"
        )
    if not isinstance(size, (int, float)) or isinstance(size, bool) or size <= 0:
        raise ExportError(
            f"typography {token!r}: size_pt missing or not a positive number"
        )
    return (family, float(size))


def _font_first(family_chain: str) -> str:
    """PPTX picks the first family available on the target platform; we
    therefore emit the FIRST entry in the design_system fallback chain
    on each <a:latin typeface=.../>. The trimmed first entry must be
    non-empty (the schema pattern already guarantees this, but we
    re-check here)."""
    head = family_chain.split(",", 1)[0].strip()
    if not head:
        raise ExportError(
            f"typography font_family {family_chain!r} has an empty head entry"
        )
    return head


def _sz_centipoints(size_pt: float) -> int:
    """PPTX font sizes are integer hundredths of a point. We round
    deterministically (banker's rounding via int(round(x))); the input
    sizes come from design_system.typography.size_pt which is already a
    positive number."""
    cp = int(round(size_pt * SZ_PER_PT))
    if cp <= 0:
        raise ExportError(f"computed font size in centipoints <= 0: {cp}")
    return cp


def _emu(px: int) -> int:
    """px (integer canvas units) -> EMU (integer)."""
    if not isinstance(px, int) or isinstance(px, bool):
        raise ExportError(f"_emu expected int px, got {type(px).__name__}: {px!r}")
    return px * EMU_PER_PX


def _bounds_to_xfrm(bounds: dict) -> tuple[int, int, int, int]:
    return (
        _emu(int(bounds["x"])),
        _emu(int(bounds["y"])),
        _emu(int(bounds["w"])),
        _emu(int(bounds["h"])),
    )


def _xfrm_xml(off_x: int, off_y: int, ext_cx: int, ext_cy: int) -> str:
    return (
        f'<a:xfrm>'
        f'<a:off x="{off_x}" y="{off_y}"/>'
        f'<a:ext cx="{ext_cx}" cy="{ext_cy}"/>'
        f'</a:xfrm>'
    )


def _nv_sp_pr_xml(shape_id: int, name: str, *, tx_box: bool) -> str:
    """<p:nvSpPr> block. tx_box=True marks the shape as a free text box
    (so PowerPoint treats it as an editable text frame rather than a
    placeholder). The non-visual name is human-readable and ASCII-only;
    it doubles as a back-trace to the render_model primitive id."""
    tx_attr = ' txBox="1"' if tx_box else ""
    return (
        f'<p:nvSpPr>'
        f'<p:cNvPr id="{shape_id}" name="{_attr(name)}"/>'
        f'<p:cNvSpPr{tx_attr}/>'
        f'<p:nvPr/>'
        f'</p:nvSpPr>'
    )


def _ln_xml(stroke_hex: str, stroke_width_px: int, *, dashed: bool = False) -> str:
    """<a:ln> with srgb stroke color. stroke_width_px is the canvas-px
    width; converted to EMU. dashed -> <a:prstDash val="dash"/>."""
    width_emu = _emu(stroke_width_px)
    dash_xml = '<a:prstDash val="dash"/>' if dashed else ""
    return (
        f'<a:ln w="{width_emu}">'
        f'<a:solidFill><a:srgbClr val="{_hex_to_srgbclr(stroke_hex)}"/></a:solidFill>'
        f'{dash_xml}'
        f'</a:ln>'
    )


def _solid_fill_xml(hex_color: str) -> str:
    return (
        f'<a:solidFill><a:srgbClr val="{_hex_to_srgbclr(hex_color)}"/></a:solidFill>'
    )


def _run_pr_xml(*, size_cp: int, hex_color: str, bold: bool, font_first: str) -> str:
    """<a:rPr> with size, color, bold, and latin typeface. lang=en-US is
    a stable default; the controlled primitive model does not yet carry
    locale information."""
    b_attr = ' b="1"' if bold else ""
    return (
        f'<a:rPr lang="en-US" sz="{size_cp}"{b_attr} dirty="0">'
        f'<a:solidFill><a:srgbClr val="{_hex_to_srgbclr(hex_color)}"/></a:solidFill>'
        f'<a:latin typeface="{_attr(font_first)}"/>'
        f'</a:rPr>'
    )


def _paragraph_xml(content: str, run_pr: str) -> str:
    """<a:p><a:r>...content...</a:r></a:p>. content is XML-escaped."""
    return (
        f'<a:p>'
        f'<a:r>{run_pr}<a:t>{xml_escape(content)}</a:t></a:r>'
        f'</a:p>'
    )


def _txbody_open(*, anchor: str = "t") -> str:
    """<p:txBody> with bodyPr + empty lstStyle. anchor="t" is top, "ctr"
    centers vertically."""
    return (
        f'<p:txBody>'
        f'<a:bodyPr wrap="square" lIns="91440" tIns="45720" '
        f'rIns="91440" bIns="45720" anchor="{anchor}">'
        f'<a:normAutofit/>'
        f'</a:bodyPr>'
        f'<a:lstStyle/>'
    )


def _txbody_close() -> str:
    return "</p:txBody>"


# --- Per-primitive emitters ------------------------------------------------

def _render_text_sp(prim: dict, design: dict, shape_id: int) -> str:
    """text primitive -> editable text box <p:sp>. role=heading is bold."""
    bounds = prim["bounds"]
    off_x, off_y, ext_cx, ext_cy = _bounds_to_xfrm(bounds)
    style = _as_dict(prim.get("style")) or {}
    color_token = style.get("color_token")
    typo_token = style.get("typography_token")
    if not isinstance(color_token, str):
        raise ExportError("text primitive missing style.color_token")
    if not isinstance(typo_token, str):
        raise ExportError("text primitive missing style.typography_token")
    color = _resolve_palette(design, color_token)
    family_chain, size_pt = _resolve_typography(design, typo_token)
    family = _font_first(family_chain)
    size_cp = _sz_centipoints(size_pt)

    payload = _as_dict(prim.get("text")) or {}
    text_content = payload.get("content")
    role = payload.get("role")
    if not isinstance(text_content, str) or not text_content:
        raise ExportError("text primitive has no non-empty content")
    bold = role == "heading"
    pid = prim.get("id") or "text"
    return (
        f'<p:sp>'
        f'{_nv_sp_pr_xml(shape_id, f"text:{pid}", tx_box=True)}'
        f'<p:spPr>{_xfrm_xml(off_x, off_y, ext_cx, ext_cy)}'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f'<a:noFill/>'
        f'</p:spPr>'
        f'{_txbody_open(anchor="t")}'
        f'{_paragraph_xml(text_content, _run_pr_xml(size_cp=size_cp, hex_color=color, bold=bold, font_first=family))}'
        f'{_txbody_close()}'
        f'</p:sp>'
    )


def _render_line_cxn(prim: dict, design: dict, shape_id: int) -> str:
    """line primitive -> native <p:cxnSp> straight connector. Drawn
    corner-to-corner inside the primitive bounds (top-left to
    bottom-right) — same convention as the SVG renderer."""
    bounds = prim["bounds"]
    off_x, off_y, ext_cx, ext_cy = _bounds_to_xfrm(bounds)
    style = _as_dict(prim.get("style")) or {}
    stroke_token = style.get("stroke_token")
    if not isinstance(stroke_token, str):
        raise ExportError("line primitive missing style.stroke_token")
    stroke = _resolve_palette(design, stroke_token)
    width_px = style.get("stroke_width_px", 1)
    if not isinstance(width_px, int) or isinstance(width_px, bool) or width_px < 1:
        raise ExportError("line primitive has invalid stroke_width_px")
    payload = _as_dict(prim.get("line")) or {}
    dashed = payload.get("stroke_style") == "dashed"
    pid = prim.get("id") or "line"
    return (
        f'<p:cxnSp>'
        f'<p:nvCxnSpPr>'
        f'<p:cNvPr id="{shape_id}" name="{_attr(f"line:{pid}")}"/>'
        f'<p:cNvCxnSpPr/>'
        f'<p:nvPr/>'
        f'</p:nvCxnSpPr>'
        f'<p:spPr>{_xfrm_xml(off_x, off_y, ext_cx, ext_cy)}'
        f'<a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
        f'{_ln_xml(stroke, width_px, dashed=dashed)}'
        f'</p:spPr>'
        f'</p:cxnSp>'
    )


_SHAPE_KIND_TO_PRST = {
    "rectangle": "rect",
    "rounded_rectangle": "roundRect",
    "ellipse": "ellipse",
}


def _render_shape_sp(prim: dict, design: dict, shape_id: int) -> str:
    bounds = prim["bounds"]
    off_x, off_y, ext_cx, ext_cy = _bounds_to_xfrm(bounds)
    style = _as_dict(prim.get("style")) or {}
    payload = _as_dict(prim.get("shape")) or {}
    shape_kind = payload.get("shape_kind")
    if shape_kind not in _SHAPE_KIND_TO_PRST:
        raise ExportError(
            f"shape primitive has unsupported shape_kind: {shape_kind!r}"
        )
    prst = _SHAPE_KIND_TO_PRST[shape_kind]
    av_lst = "<a:avLst/>"
    if shape_kind == "rounded_rectangle":
        radius = payload.get("corner_radius_px", 0)
        if not isinstance(radius, int) or isinstance(radius, bool) or radius < 0:
            raise ExportError("rounded_rectangle has invalid corner_radius_px")
        # PPTX rounded-rect adjustment is a fraction (1/100000) of the
        # smaller bounds dimension. We map the requested corner radius
        # in px onto that fraction.
        if radius > 0:
            base_px = min(int(bounds["w"]), int(bounds["h"]))
            if base_px > 0:
                adj = max(0, min(50000, int(round(radius * 100000 / base_px))))
                av_lst = f'<a:avLst><a:gd name="adj" fmla="val {adj}"/></a:avLst>'

    fill_token = style.get("fill_token")
    stroke_token = style.get("stroke_token")
    stroke_width_px = style.get("stroke_width_px")
    fill_xml = "<a:noFill/>"
    if isinstance(fill_token, str):
        fill_hex = _resolve_palette(design, fill_token)
        fill_xml = _solid_fill_xml(fill_hex)
    ln_xml = ""
    if isinstance(stroke_token, str):
        stroke_hex = _resolve_palette(design, stroke_token)
        if (
            not isinstance(stroke_width_px, int)
            or isinstance(stroke_width_px, bool)
            or stroke_width_px < 1
        ):
            raise ExportError(
                "shape primitive has stroke_token but invalid stroke_width_px"
            )
        ln_xml = _ln_xml(stroke_hex, stroke_width_px)

    pid = prim.get("id") or "shape"
    # Shapes also carry an (empty) txBody — having one keeps the shape
    # editable as a "type into me" target in PowerPoint without
    # injecting content the render_model did not declare.
    return (
        f'<p:sp>'
        f'{_nv_sp_pr_xml(shape_id, f"shape:{pid}", tx_box=False)}'
        f'<p:spPr>{_xfrm_xml(off_x, off_y, ext_cx, ext_cy)}'
        f'<a:prstGeom prst="{prst}">{av_lst}</a:prstGeom>'
        f'{fill_xml}'
        f'{ln_xml}'
        f'</p:spPr>'
        f'{_txbody_open(anchor="ctr")}'
        f'<a:p><a:endParaRPr lang="en-US"/></a:p>'
        f'{_txbody_close()}'
        f'</p:sp>'
    )


def _render_kpi_sp(prim: dict, design: dict, shape_id: int) -> str:
    """kpi primitive -> editable text box with up to three paragraphs:
    label, value, optional delta. The result is one native <p:sp> the
    user can click into and edit directly."""
    bounds = prim["bounds"]
    off_x, off_y, ext_cx, ext_cy = _bounds_to_xfrm(bounds)
    style = _as_dict(prim.get("style")) or {}
    color_token = style.get("color_token")
    if not isinstance(color_token, str):
        raise ExportError("kpi primitive missing style.color_token")
    color = _resolve_palette(design, color_token)
    body_family_chain, body_pt = _resolve_typography(design, "typography.body")
    head_family_chain, head_pt = _resolve_typography(design, "typography.heading")
    body_family = _font_first(body_family_chain)
    head_family = _font_first(head_family_chain)
    body_cp = _sz_centipoints(body_pt)
    head_cp = _sz_centipoints(head_pt)

    payload = _as_dict(prim.get("kpi")) or {}
    label = payload.get("label")
    value = payload.get("value")
    delta = payload.get("delta")
    if not isinstance(label, str) or not label:
        raise ExportError("kpi primitive missing label")
    if not isinstance(value, str) or not value:
        raise ExportError("kpi primitive missing value")
    if delta is not None and (not isinstance(delta, str) or not delta):
        raise ExportError(
            "kpi primitive delta must be a non-empty string when set"
        )

    paragraphs = [
        _paragraph_xml(label, _run_pr_xml(
            size_cp=body_cp, hex_color=color, bold=False, font_first=body_family)),
        _paragraph_xml(value, _run_pr_xml(
            size_cp=head_cp, hex_color=color, bold=True, font_first=head_family)),
    ]
    if isinstance(delta, str) and delta:
        paragraphs.append(
            _paragraph_xml(delta, _run_pr_xml(
                size_cp=body_cp, hex_color=color, bold=False, font_first=body_family))
        )

    pid = prim.get("id") or "kpi"
    return (
        f'<p:sp>'
        f'{_nv_sp_pr_xml(shape_id, f"kpi:{pid}", tx_box=True)}'
        f'<p:spPr>{_xfrm_xml(off_x, off_y, ext_cx, ext_cy)}'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f'<a:noFill/>'
        f'</p:spPr>'
        f'{_txbody_open(anchor="t")}'
        f'{"".join(paragraphs)}'
        f'{_txbody_close()}'
        f'</p:sp>'
    )


def _render_image_slot_sp(
    prim: dict,
    design: dict,
    shape_id: int,
    manifest_alts: dict,
    manifest_paths: dict,
) -> str:
    """image_slot primitive -> placeholder rectangle whose txBody carries
    the image_manifest alt_text. Media embedding is intentionally
    deferred: PowerPoint's SVG support needs a PNG fallback and a
    matching SVGBlip extension, and JPG/PNG embedding adds media
    relationships, neither of which is in this minimal slice. The
    image_ref is still validated against image_manifest so unsafe
    references fail closed."""
    bounds = prim["bounds"]
    off_x, off_y, ext_cx, ext_cy = _bounds_to_xfrm(bounds)
    payload = _as_dict(prim.get("image_slot")) or {}
    image_ref = payload.get("image_ref")
    if not isinstance(image_ref, str) or not image_ref:
        raise ExportError("image_slot primitive missing image_ref")
    if image_ref not in manifest_paths:
        raise ExportError(
            f"image_slot primitive references image id {image_ref!r} "
            f"that is not declared in image_manifest"
        )
    # Defense in depth: manifest path-safety has been preflight-checked,
    # but re-check at use time so a later regression cannot leak an
    # unsafe path into the alt text (or a future media-embed branch).
    local_path = manifest_paths[image_ref]
    if not local_path_is_safe(local_path):
        raise ExportError(
            f"image_slot primitive resolves to unsafe local_path "
            f"{local_path!r} for image id {image_ref!r}"
        )
    alt_text = payload.get("alt_text") or manifest_alts.get(image_ref) or image_ref
    # Use a thin neutral stroke and no fill so the placeholder is
    # visible during editing but does not overpaint slide content.
    text_family_chain, text_pt = _resolve_typography(design, "typography.body")
    text_family = _font_first(text_family_chain)
    text_color = _resolve_palette(design, "palette.text")
    body_cp = _sz_centipoints(text_pt)
    # Always render the alt text deterministically.
    placeholder_label = f"[image: {alt_text}]"
    pid = prim.get("id") or "image_slot"
    return (
        f'<p:sp>'
        f'{_nv_sp_pr_xml(shape_id, f"image_slot:{pid}", tx_box=False)}'
        f'<p:spPr>{_xfrm_xml(off_x, off_y, ext_cx, ext_cy)}'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f'<a:noFill/>'
        f'{_ln_xml(text_color, 1)}'
        f'</p:spPr>'
        f'{_txbody_open(anchor="ctr")}'
        f'{_paragraph_xml(placeholder_label, _run_pr_xml(size_cp=body_cp, hex_color=text_color, bold=False, font_first=text_family))}'
        f'{_txbody_close()}'
        f'</p:sp>'
    )


def _render_primitive(
    prim: dict,
    design: dict,
    shape_id: int,
    manifest_alts: dict,
    manifest_paths: dict,
) -> str:
    kind = prim.get("kind")
    if kind == "text":
        return _render_text_sp(prim, design, shape_id)
    if kind == "line":
        return _render_line_cxn(prim, design, shape_id)
    if kind == "shape":
        return _render_shape_sp(prim, design, shape_id)
    if kind == "kpi":
        return _render_kpi_sp(prim, design, shape_id)
    if kind == "image_slot":
        return _render_image_slot_sp(
            prim, design, shape_id, manifest_alts, manifest_paths,
        )
    # Fail closed on table / chart_placeholder / anything else. These
    # remain TODO per references/pptx-conversion-rules.md.
    raise ExportError(
        f"primitive kind {kind!r} is not supported by the PPTX exporter "
        f"today (supported: {SUPPORTED_PRIMITIVE_KINDS}); "
        f"`table` and `chart_placeholder` are deferred and must fail closed"
    )


# --- Slide / package XML ---------------------------------------------------

def _slide_xml(
    render_model: dict,
    design: dict,
    manifest_alts: dict,
    manifest_paths: dict,
) -> str:
    """Build the per-slide XML for a supported render_model. Shape ids
    start at 2 because id=1 is reserved for the spTree group root."""
    primitives = _as_list(render_model.get("primitives")) or []
    bg_hex = _resolve_palette(design, "palette.background")
    shape_xml_parts: list[str] = []
    next_id = 2
    for prim in primitives:
        if not isinstance(prim, dict):
            raise ExportError(
                f"render_model primitive is not an object: "
                f"got {type(prim).__name__}"
            )
        kind = prim.get("kind")
        if kind not in SUPPORTED_PRIMITIVE_KINDS:
            raise ExportError(
                f"render_model contains unsupported primitive kind "
                f"{kind!r} (supported: {SUPPORTED_PRIMITIVE_KINDS}); "
                f"`table` and `chart_placeholder` remain TODO and must "
                f"fail closed in this exporter"
            )
        shape_xml_parts.append(
            _render_primitive(prim, design, next_id, manifest_alts, manifest_paths)
        )
        next_id += 1

    body_xml = "".join(shape_xml_parts)
    layout = render_model.get("layout", "")
    idx = render_model.get("index", 0)
    return (
        f'{_XML_HEADER}'
        f'<p:sld xmlns:a="{_NS["a"]}" xmlns:p="{_NS["p"]}" xmlns:r="{_NS["r"]}">'
        f'<p:cSld name="{_attr(f"slide_index_{idx:02d}_{layout}")}">'
        f'<p:bg><p:bgPr>{_solid_fill_xml(bg_hex)}'
        f'<a:effectLst/></p:bgPr></p:bg>'
        f'<p:spTree>'
        f'<p:nvGrpSpPr>'
        f'<p:cNvPr id="1" name=""/>'
        f'<p:cNvGrpSpPr/>'
        f'<p:nvPr/>'
        f'</p:nvGrpSpPr>'
        f'<p:grpSpPr>'
        f'<a:xfrm>'
        f'<a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        f'<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/>'
        f'</a:xfrm>'
        f'</p:grpSpPr>'
        f'{body_xml}'
        f'</p:spTree>'
        f'</p:cSld>'
        f'<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>'
        f'</p:sld>'
    )


def _slide_master_xml() -> str:
    return (
        f'{_XML_HEADER}'
        f'<p:sldMaster xmlns:a="{_NS["a"]}" xmlns:p="{_NS["p"]}" xmlns:r="{_NS["r"]}">'
        f'<p:cSld>'
        f'<p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>'
        f'<p:spTree>'
        f'<p:nvGrpSpPr>'
        f'<p:cNvPr id="1" name=""/>'
        f'<p:cNvGrpSpPr/>'
        f'<p:nvPr/>'
        f'</p:nvGrpSpPr>'
        f'<p:grpSpPr>'
        f'<a:xfrm>'
        f'<a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        f'<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/>'
        f'</a:xfrm>'
        f'</p:grpSpPr>'
        f'</p:spTree>'
        f'</p:cSld>'
        f'<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" '
        f'accent1="accent1" accent2="accent2" accent3="accent3" '
        f'accent4="accent4" accent5="accent5" accent6="accent6" '
        f'hlink="hlink" folHlink="folHlink"/>'
        f'<p:sldLayoutIdLst>'
        f'<p:sldLayoutId id="2147483649" r:id="rId1"/>'
        f'</p:sldLayoutIdLst>'
        f'<p:txStyles>'
        f'<p:titleStyle/><p:bodyStyle/><p:otherStyle/>'
        f'</p:txStyles>'
        f'</p:sldMaster>'
    )


def _slide_layout_xml() -> str:
    return (
        f'{_XML_HEADER}'
        f'<p:sldLayout xmlns:a="{_NS["a"]}" xmlns:p="{_NS["p"]}" xmlns:r="{_NS["r"]}" '
        f'type="blank" preserve="1">'
        f'<p:cSld name="Blank">'
        f'<p:spTree>'
        f'<p:nvGrpSpPr>'
        f'<p:cNvPr id="1" name=""/>'
        f'<p:cNvGrpSpPr/>'
        f'<p:nvPr/>'
        f'</p:nvGrpSpPr>'
        f'<p:grpSpPr>'
        f'<a:xfrm>'
        f'<a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        f'<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/>'
        f'</a:xfrm>'
        f'</p:grpSpPr>'
        f'</p:spTree>'
        f'</p:cSld>'
        f'<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>'
        f'</p:sldLayout>'
    )


def _theme_xml(design: dict) -> str:
    """Minimal theme. Picks a deterministic seed for accent slots from
    design_system.palette so the resulting theme is at least
    self-consistent; PowerPoint will still resolve each slide's explicit
    srgbClr values, so this is informational rather than load-bearing."""
    primary = _hex_to_srgbclr(_resolve_palette(design, "palette.primary"))
    background = _hex_to_srgbclr(_resolve_palette(design, "palette.background"))
    text = _hex_to_srgbclr(_resolve_palette(design, "palette.text"))
    # Optional palette slots; fall back to neutral grays so the theme
    # parses regardless of which optional keys are present.
    palette = _as_dict(design.get("palette")) or {}
    def _opt(key: str, fallback: str) -> str:
        v = palette.get(key)
        if isinstance(v, str) and _HEX_COLOR.match(v):
            return _hex_to_srgbclr(v)
        return fallback
    secondary = _opt("secondary", "999999")
    accent = _opt("accent", "CCCCCC")
    # Heading/body fonts -> latin typeface name.
    head_family, _ = _resolve_typography(design, "typography.heading")
    body_family, _ = _resolve_typography(design, "typography.body")
    head_face = _font_first(head_family)
    body_face = _font_first(body_family)
    return (
        f'{_XML_HEADER}'
        f'<a:theme xmlns:a="{_NS["a"]}" name="szh-ppt-master">'
        f'<a:themeElements>'
        f'<a:clrScheme name="szh-ppt-master">'
        f'<a:dk1><a:srgbClr val="{text}"/></a:dk1>'
        f'<a:lt1><a:srgbClr val="{background}"/></a:lt1>'
        f'<a:dk2><a:srgbClr val="{primary}"/></a:dk2>'
        f'<a:lt2><a:srgbClr val="E8E8E8"/></a:lt2>'
        f'<a:accent1><a:srgbClr val="{primary}"/></a:accent1>'
        f'<a:accent2><a:srgbClr val="{secondary}"/></a:accent2>'
        f'<a:accent3><a:srgbClr val="{accent}"/></a:accent3>'
        f'<a:accent4><a:srgbClr val="{text}"/></a:accent4>'
        f'<a:accent5><a:srgbClr val="999999"/></a:accent5>'
        f'<a:accent6><a:srgbClr val="CCCCCC"/></a:accent6>'
        f'<a:hlink><a:srgbClr val="0000FF"/></a:hlink>'
        f'<a:folHlink><a:srgbClr val="800080"/></a:folHlink>'
        f'</a:clrScheme>'
        f'<a:fontScheme name="szh-ppt-master">'
        f'<a:majorFont>'
        f'<a:latin typeface="{_attr(head_face)}"/>'
        f'<a:ea typeface=""/><a:cs typeface=""/>'
        f'</a:majorFont>'
        f'<a:minorFont>'
        f'<a:latin typeface="{_attr(body_face)}"/>'
        f'<a:ea typeface=""/><a:cs typeface=""/>'
        f'</a:minorFont>'
        f'</a:fontScheme>'
        f'<a:fmtScheme name="szh-ppt-master">'
        f'<a:fillStyleLst>'
        f'<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        f'<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        f'<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        f'</a:fillStyleLst>'
        f'<a:lnStyleLst>'
        f'<a:ln w="6350" cap="flat" cmpd="sng" algn="ctr">'
        f'<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        f'<a:prstDash val="solid"/></a:ln>'
        f'<a:ln w="12700" cap="flat" cmpd="sng" algn="ctr">'
        f'<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        f'<a:prstDash val="solid"/></a:ln>'
        f'<a:ln w="19050" cap="flat" cmpd="sng" algn="ctr">'
        f'<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        f'<a:prstDash val="solid"/></a:ln>'
        f'</a:lnStyleLst>'
        f'<a:effectStyleLst>'
        f'<a:effectStyle><a:effectLst/></a:effectStyle>'
        f'<a:effectStyle><a:effectLst/></a:effectStyle>'
        f'<a:effectStyle><a:effectLst/></a:effectStyle>'
        f'</a:effectStyleLst>'
        f'<a:bgFillStyleLst>'
        f'<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        f'<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        f'<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        f'</a:bgFillStyleLst>'
        f'</a:fmtScheme>'
        f'</a:themeElements>'
        f'<a:objectDefaults/>'
        f'<a:extraClrSchemeLst/>'
        f'</a:theme>'
    )


def _presentation_xml(slide_count: int, canvas_w_px: int, canvas_h_px: int) -> str:
    sld_ids = "".join(
        f'<p:sldId id="{256 + i}" r:id="rId{2 + i}"/>'
        for i in range(slide_count)
    )
    return (
        f'{_XML_HEADER}'
        f'<p:presentation xmlns:a="{_NS["a"]}" xmlns:r="{_NS["r"]}" '
        f'xmlns:p="{_NS["p"]}" saveSubsetFonts="1">'
        f'<p:sldMasterIdLst>'
        f'<p:sldMasterId id="2147483648" r:id="rId1"/>'
        f'</p:sldMasterIdLst>'
        f'<p:sldIdLst>{sld_ids}</p:sldIdLst>'
        f'<p:sldSz cx="{_emu(canvas_w_px)}" cy="{_emu(canvas_h_px)}"/>'
        f'<p:notesSz cx="6858000" cy="9144000"/>'
        f'<p:defaultTextStyle/>'
        f'</p:presentation>'
    )


def _rels_xml(rels: list[tuple[str, str, str]]) -> str:
    """rels: list of (Id, Type, Target). Emits a Relationships file
    with Target only (no TargetMode), so every relationship is internal."""
    body = "".join(
        f'<Relationship Id="{rid}" Type="{rtype}" Target="{_attr(target)}"/>'
        for rid, rtype, target in rels
    )
    return (
        f'{_XML_HEADER}'
        f'<Relationships xmlns="{_NS["pkg"]}">{body}</Relationships>'
    )


def _content_types_xml(slide_count: int) -> str:
    """[Content_Types].xml.

    Defaults declare the well-known extensions (`rels` + `xml`); every
    document part is registered via an explicit Override so the package
    is unambiguous."""
    overrides = [
        ("/ppt/presentation.xml", CT_PRESENTATION),
        ("/ppt/slideMasters/slideMaster1.xml", CT_SLIDE_MASTER),
        ("/ppt/slideLayouts/slideLayout1.xml", CT_SLIDE_LAYOUT),
        ("/ppt/theme/theme1.xml", CT_THEME),
    ]
    for n in range(1, slide_count + 1):
        overrides.append((f"/ppt/slides/slide{n}.xml", CT_SLIDE))
    override_xml = "".join(
        f'<Override PartName="{pn}" ContentType="{ct}"/>'
        for pn, ct in overrides
    )
    return (
        f'{_XML_HEADER}'
        f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        f'<Default Extension="rels" ContentType="{CT_RELS}"/>'
        f'<Default Extension="xml" ContentType="{CT_XML}"/>'
        f'{override_xml}'
        f'</Types>'
    )


# --- Package assembly ------------------------------------------------------

def _build_package_parts(
    slides: list[tuple[dict, str]],
    design: dict,
    canvas_w_px: int,
    canvas_h_px: int,
) -> dict[str, str]:
    """Assemble every package part as a dict of {member_path: utf-8 text}.
    Returns the dict; the caller writes it to a ZIP. Member paths are
    POSIX style (forward slashes) — that is what zipfile expects."""
    slide_count = len(slides)
    parts: dict[str, str] = {}

    parts["[Content_Types].xml"] = _content_types_xml(slide_count)
    parts["_rels/.rels"] = _rels_xml([
        ("rId1", REL_OFFICE_DOCUMENT, "ppt/presentation.xml"),
    ])
    parts["ppt/presentation.xml"] = _presentation_xml(
        slide_count, canvas_w_px, canvas_h_px,
    )
    # Presentation-level relationships: rId1=slideMaster, rId2..N=slides,
    # rIdTheme=theme. Slide rels follow the same numbering as the
    # presentation.xml sldIdLst so a slide's r:id resolves to its slide
    # part deterministically.
    pres_rels: list[tuple[str, str, str]] = [
        ("rId1", REL_SLIDE_MASTER, "slideMasters/slideMaster1.xml"),
    ]
    for i in range(slide_count):
        pres_rels.append(
            (f"rId{2 + i}", REL_SLIDE, f"slides/slide{1 + i}.xml")
        )
    pres_rels.append(
        (f"rId{2 + slide_count}", REL_THEME, "theme/theme1.xml")
    )
    parts["ppt/_rels/presentation.xml.rels"] = _rels_xml(pres_rels)

    parts["ppt/slideMasters/slideMaster1.xml"] = _slide_master_xml()
    parts["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = _rels_xml([
        ("rId1", REL_SLIDE_LAYOUT, "../slideLayouts/slideLayout1.xml"),
        ("rId2", REL_THEME, "../theme/theme1.xml"),
    ])
    parts["ppt/slideLayouts/slideLayout1.xml"] = _slide_layout_xml()
    parts["ppt/slideLayouts/_rels/slideLayout1.xml.rels"] = _rels_xml([
        ("rId1", REL_SLIDE_MASTER, "../slideMasters/slideMaster1.xml"),
    ])
    parts["ppt/theme/theme1.xml"] = _theme_xml(design)

    for i, (rm, slide_xml) in enumerate(slides, start=1):
        parts[f"ppt/slides/slide{i}.xml"] = slide_xml
        parts[f"ppt/slides/_rels/slide{i}.xml.rels"] = _rels_xml([
            ("rId1", REL_SLIDE_LAYOUT, "../slideLayouts/slideLayout1.xml"),
        ])

    return parts


def _write_pptx(output_path: Path, parts: dict[str, str]) -> None:
    """Write parts (sorted by member path) into a deterministic ZIP."""
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(parts):
            info = zipfile.ZipInfo(name)
            info.date_time = _ZIP_TIMESTAMP
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, parts[name])


# --- Workspace orchestration ----------------------------------------------

def _has_pptx_extension(path: Path) -> bool:
    return path.suffix.lower() == ".pptx"


def export_workspace(workspace: Path, output: Path) -> int:
    """Top-level entry. Returns process exit code."""
    if not workspace.is_dir():
        return _fatal(f"workspace is not a directory: {workspace}")
    if not _has_pptx_extension(output):
        return _fatal(
            f"output extension must be '.pptx' (case-insensitive); "
            f"got {output.suffix!r}"
        )

    design, err = _load_required_object(
        workspace / "design_system.json", "design_system.json",
    )
    if design is None:
        return _fatal(err)
    manifest, err = _load_required_object(
        workspace / "image_manifest.json", "image_manifest.json",
    )
    if manifest is None:
        return _fatal(err)

    # Preflight schema gates on the artifacts the exporter consumes.
    for fname, schema_name, artifact in (
        ("design_system.json",  "design_system.schema.json",  design),
        ("image_manifest.json", "image_manifest.schema.json", manifest),
    ):
        errors = _schema_validate(artifact, SCHEMAS / schema_name)
        if errors:
            return _fatal(
                f"{fname} fails {schema_name}: {'; '.join(errors)}"
            )

    # Manifest path-safety preflight: defense-in-depth even though the
    # workspace validator already exercises this rule.
    manifest_paths: dict[str, str] = {}
    manifest_alts: dict[str, str] = {}
    for img in _as_list(manifest.get("images")) or []:
        img_d = _as_dict(img)
        if img_d is None:
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
                f"{local_path!r}; refusing to export"
            )
        if isinstance(img_id, str):
            manifest_paths[img_id] = local_path
            alt = img_d.get("alt_text")
            if isinstance(alt, str):
                manifest_alts[img_id] = alt

    rm_dir = workspace / "render_models"
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

    # Canvas dimensions come from design_system.grid. Every render_model
    # must agree (validate_workspace.check_render_models enforces this);
    # we additionally re-check here so the slide-size in the PPTX
    # matches every primitive's bounds.
    grid = _as_dict(design.get("grid")) or {}
    canvas_w = grid.get("width_px")
    canvas_h = grid.get("height_px")
    if (
        not isinstance(canvas_w, int) or isinstance(canvas_w, bool) or canvas_w <= 0
        or not isinstance(canvas_h, int) or isinstance(canvas_h, bool) or canvas_h <= 0
    ):
        return _fatal(
            "design_system.grid.width_px/height_px must be positive integers"
        )

    exported: list[tuple[dict, str]] = []
    fatal_errors: list[str] = []

    for rm_file in rm_files:
        raw, load_err = _try_load(rm_file)
        rel = rm_file.relative_to(workspace)
        if raw is None:
            fatal_errors.append(f"{rel}: not loadable: {load_err}")
            continue
        rm = _as_dict(raw)
        if rm is None:
            fatal_errors.append(
                f"{rel}: root is not an object (got {type(raw).__name__})"
            )
            continue
        schema_errors = _schema_validate(
            rm, SCHEMAS / "render_model.schema.json",
        )
        if schema_errors:
            fatal_errors.append(
                f"{rel}: render_model fails schema: {'; '.join(schema_errors)}"
            )
            continue

        layout = rm.get("layout")
        idx = rm.get("index")
        # render_model.schema.json already enforces int+string, but
        # check defensively so we never traceback on caller input.
        if not isinstance(idx, int) or isinstance(idx, bool):
            fatal_errors.append(f"{rel}: render_model.index is not an integer")
            continue
        if not isinstance(layout, str):
            fatal_errors.append(f"{rel}: render_model.layout is not a string")
            continue

        # Cross-check canvas vs. design_system.grid here so a stale
        # render_model that drifted from the grid cannot quietly emit a
        # mis-sized slide.
        canvas = _as_dict(rm.get("canvas")) or {}
        if (
            canvas.get("width_px") != canvas_w
            or canvas.get("height_px") != canvas_h
        ):
            fatal_errors.append(
                f"{rel}: render_model.canvas {canvas} does not match "
                f"design_system.grid {canvas_w}x{canvas_h}"
            )
            continue

        # Unsupported layouts FAIL CLOSED. Earlier versions of this
        # script recorded them as harmless [SKIP] lines and still
        # wrote a partial deck containing the other slides; that
        # silently produced an incomplete `.pptx` whenever the
        # workspace shipped a render_model the exporter did not
        # implement. The contract is now "all-or-nothing": any
        # render_model under render_models/*.json must either export
        # cleanly or abort the whole run with a per-slide error.
        if layout not in SUPPORTED_LAYOUTS:
            fatal_errors.append(
                f"{rel} (index={idx}, layout={layout!r}): layout is not "
                f"in the exporter's supported set {SUPPORTED_LAYOUTS}; "
                f"extending coverage requires extending the exporter — "
                f"refusing to write a partial deck"
            )
            continue

        try:
            xml = _slide_xml(rm, design, manifest_alts, manifest_paths)
        except ExportError as exc:
            fatal_errors.append(f"{rel} (index={idx}, {layout}): {exc}")
            continue
        exported.append((rm, xml))

    if fatal_errors:
        for err in fatal_errors:
            print(f"  [FAIL] {err}", file=sys.stderr)
        print(
            f"FAIL: PPTX export aborted; {len(fatal_errors)} "
            f"per-slide error(s). No `.pptx` was written.",
            file=sys.stderr,
        )
        return 1

    if not exported:
        print(
            f"FAIL: no render_model was exported "
            f"(found {len(rm_files)} file(s)); refusing to write an "
            f"empty `.pptx`.",
            file=sys.stderr,
        )
        return 1

    # Output parent directory: create with parents=True/exist_ok=True
    # for consistency with how generate_render_models / generate_svg_previews
    # create workspace-internal output directories.
    output.parent.mkdir(parents=True, exist_ok=True)

    parts = _build_package_parts(exported, design, canvas_w, canvas_h)
    _write_pptx(output, parts)

    print(f"Exported {len(exported)} slide(s) to {output}:")
    for i, (rm, _) in enumerate(exported, start=1):
        print(
            f"  [EXPORT] slide {i:>2} (render_model index "
            f"{rm.get('index'):>2}, layout {rm.get('layout')!r}) "
            f"-> ppt/slides/slide{i}.xml"
        )
    print(
        f"\nOK: PPTX export succeeded for {len(exported)} slide(s). "
        f"This is the minimal native editable subset — `table` and "
        f"`chart_placeholder` primitives, media embedding, and layouts "
        f"other than {SUPPORTED_LAYOUTS} fail closed and remain TODO."
    )
    return 0


def export_single_render_model(rm_path: Path, design_path: Path, manifest_path: Path, output: Path) -> int:
    """Debug helper: export a single render_model file into a one-slide
    .pptx. Not the primary path — workspace mode is the main entry —
    but useful when iterating on a single primitive."""
    if not _has_pptx_extension(output):
        return _fatal(
            f"output extension must be '.pptx' (case-insensitive); "
            f"got {output.suffix!r}"
        )
    design, err = _load_required_object(design_path, "design_system.json")
    if design is None:
        return _fatal(err)
    manifest, err = _load_required_object(manifest_path, "image_manifest.json")
    if manifest is None:
        return _fatal(err)
    for fname, schema_name, artifact in (
        ("design_system.json",  "design_system.schema.json",  design),
        ("image_manifest.json", "image_manifest.schema.json", manifest),
    ):
        errors = _schema_validate(artifact, SCHEMAS / schema_name)
        if errors:
            return _fatal(
                f"{fname} fails {schema_name}: {'; '.join(errors)}"
            )
    manifest_paths: dict[str, str] = {}
    manifest_alts: dict[str, str] = {}
    for img in _as_list(manifest.get("images")) or []:
        img_d = _as_dict(img)
        if img_d is None:
            continue
        img_id = img_d.get("id")
        local_path = img_d.get("local_path")
        if not isinstance(local_path, str) or not local_path_is_safe(local_path):
            return _fatal(
                f"image_manifest entry {img_id!r}: unsafe or missing local_path"
            )
        if isinstance(img_id, str):
            manifest_paths[img_id] = local_path
            alt = img_d.get("alt_text")
            if isinstance(alt, str):
                manifest_alts[img_id] = alt
    raw, load_err = _try_load(rm_path)
    if raw is None:
        return _fatal(f"{rm_path}: not loadable: {load_err}")
    rm = _as_dict(raw)
    if rm is None:
        return _fatal(f"{rm_path}: root is not an object")
    errors = _schema_validate(rm, SCHEMAS / "render_model.schema.json")
    if errors:
        return _fatal(f"{rm_path}: render_model fails schema: {'; '.join(errors)}")
    layout = rm.get("layout")
    if layout not in SUPPORTED_LAYOUTS:
        return _fatal(
            f"{rm_path}: layout {layout!r} is not supported by the exporter; "
            f"supported: {SUPPORTED_LAYOUTS}"
        )
    grid = _as_dict(design.get("grid")) or {}
    canvas_w = grid.get("width_px")
    canvas_h = grid.get("height_px")
    canvas = _as_dict(rm.get("canvas")) or {}
    if (
        canvas.get("width_px") != canvas_w
        or canvas.get("height_px") != canvas_h
    ):
        return _fatal(
            f"{rm_path}: canvas does not match design_system.grid"
        )
    try:
        xml = _slide_xml(rm, design, manifest_alts, manifest_paths)
    except ExportError as exc:
        return _fatal(f"{rm_path}: {exc}")
    output.parent.mkdir(parents=True, exist_ok=True)
    parts = _build_package_parts([(rm, xml)], design, canvas_w, canvas_h)
    _write_pptx(output, parts)
    print(
        f"OK (single render_model): exported {rm_path} -> {output} "
        f"(one slide). Workspace mode is the primary entry point."
    )
    return 0


def _write_synthetic_workspace(ws: Path) -> None:
    """Build a deterministic happy-path workspace under `ws`. Used by
    the self-test fixtures. The render_models exercise the supported
    primitive kinds without needing any real images, so the manifest
    stays empty and no asset files are produced. The caller can mutate
    the fixture (add unsupported primitives, malformed JSON, ...) to
    drive each negative test."""
    import json
    (ws / "render_models").mkdir(parents=True, exist_ok=True)
    (ws / "design_system.json").write_text(json.dumps({
        "palette": {
            "primary":    "#1F3A5F",
            "background": "#FFFFFF",
            "text":       "#1A1A1A",
        },
        "typography": {
            "heading": {
                "font_family": "Calibri, Helvetica Neue, Arial, sans-serif",
                "size_pt": 28,
            },
            "body": {
                "font_family": "Calibri, Helvetica Neue, Arial, sans-serif",
                "size_pt": 14,
            },
        },
        "grid": {"width_px": 1920, "height_px": 1080, "margin_px": 64},
    }, indent=2))
    (ws / "image_manifest.json").write_text(json.dumps({"images": []}))
    # Cover slide: line + text. No image_slot so the empty manifest is
    # legitimate.
    (ws / "render_models" / "01_cover.json").write_text(json.dumps({
        "index": 1,
        "layout": "cover",
        "canvas": {"width_px": 1920, "height_px": 1080},
        "source_refs": ["synthetic_src"],
        "primitives": [
            {
                "id": "title_divider",
                "kind": "line",
                "bounds": {"x": 160, "y": 290, "w": 1280, "h": 4},
                "style": {
                    "stroke_token": "palette.primary",
                    "stroke_width_px": 4,
                },
                "line": {"stroke_style": "solid"},
            },
            {
                "id": "title",
                "slot_id": "title",
                "kind": "text",
                "bounds": {"x": 160, "y": 320, "w": 1280, "h": 200},
                "style": {
                    "color_token": "palette.text",
                    "typography_token": "typography.heading",
                },
                "text": {"content": "Synthetic Cover", "role": "heading"},
            },
        ],
    }, indent=2))
    # kpi_dashboard slide: title + shape + two kpi tiles.
    (ws / "render_models" / "02_kpi_dashboard.json").write_text(json.dumps({
        "index": 2,
        "layout": "kpi_dashboard",
        "canvas": {"width_px": 1920, "height_px": 1080},
        "source_refs": ["synthetic_src"],
        "primitives": [
            {
                "id": "title",
                "slot_id": "title",
                "kind": "text",
                "bounds": {"x": 64, "y": 80, "w": 1792, "h": 120},
                "style": {
                    "color_token": "palette.text",
                    "typography_token": "typography.heading",
                },
                "text": {"content": "Synthetic Metrics", "role": "heading"},
            },
            {
                "id": "kpi_band_bg",
                "kind": "shape",
                "bounds": {"x": 64, "y": 280, "w": 1792, "h": 600},
                "style": {
                    "fill_token": "palette.background",
                    "stroke_token": "palette.primary",
                    "stroke_width_px": 2,
                },
                "shape": {"shape_kind": "rounded_rectangle", "corner_radius_px": 12},
            },
            {
                "id": "kpi_01",
                "slot_id": "kpis",
                "kind": "kpi",
                "bounds": {"x": 96, "y": 310, "w": 864, "h": 540},
                "style": {"color_token": "palette.text"},
                "kpi": {"label": "alpha", "value": "<value>", "delta": "<delta>"},
            },
            {
                "id": "kpi_02",
                "slot_id": "kpis",
                "kind": "kpi",
                "bounds": {"x": 972, "y": 310, "w": 864, "h": 540},
                "style": {"color_token": "palette.text"},
                "kpi": {"label": "beta", "value": "<value>"},
            },
        ],
    }, indent=2))


def _run_self_tests() -> list[CheckResult]:
    """Build a synthetic workspace under TemporaryDirectory and exercise
    the exporter's positive + fail-closed paths. Returns one
    CheckResult per scenario.

    Positive:
      - happy-path workspace exports two slides, and the resulting
        PPTX passes every container + minimal-evidence check from
        validate_pptx_contract.

    Negatives (each returns a non-zero exit and the scenario asserts
    that — the exporter must fail closed):
      - wrong --output extension (.zip);
      - render_model containing a `table` primitive (unsupported);
      - render_model containing a `chart_placeholder` primitive
        (unsupported);
      - render_model with a missing required field (no `primitives`);
      - image_slot whose image_ref is not declared in image_manifest;
      - image_manifest local_path with an unsafe URI scheme."""
    import io
    import json
    import tempfile
    from contextlib import redirect_stderr, redirect_stdout

    # The validator is imported lazily so the export_pptx CLI can run
    # without pulling validate_pptx_contract into its public surface.
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from validate_pptx_contract import check_container, check_generated_pptx  # noqa: E402

    def _run_capture(workspace: Path, output: Path) -> tuple[int, str, str]:
        """Run export_workspace under captured stdout/stderr so the
        self-test output is not polluted by per-scenario noise. Returns
        (exit_code, stdout_text, stderr_text)."""
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = export_workspace(workspace, output)
        return (rc, out_buf.getvalue(), err_buf.getvalue())

    results: list[CheckResult] = []

    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)

        # 1. POSITIVE: happy-path workspace exports cleanly.
        happy = td / "happy"
        _write_synthetic_workspace(happy)
        out_pptx = td / "happy.pptx"
        rc, _stdout, stderr = _run_capture(happy, out_pptx)
        ok_export = rc == 0 and out_pptx.is_file()
        results.append(CheckResult(
            "selftest: happy workspace exports successfully (rc=0, file exists)",
            ok_export,
            stderr.strip() if not ok_export else "",
        ))
        if ok_export:
            c_res = check_container(out_pptx)
            g_res = check_generated_pptx(out_pptx)
            all_ok = all(r.ok for r in c_res) and all(r.ok for r in g_res)
            results.append(CheckResult(
                "selftest: exported PPTX passes validate_pptx_contract "
                "container + minimal-evidence checks",
                all_ok,
                "; ".join(
                    f"{r.name}: {r.detail}"
                    for r in (c_res + g_res)
                    if not r.ok
                ),
            ))
        else:
            results.append(CheckResult(
                "selftest: exported PPTX passes validate_pptx_contract "
                "container + minimal-evidence checks",
                False,
                "skipped — export failed",
            ))

        # 2. NEGATIVE: wrong output extension.
        wrong_ext_out = td / "happy.zip"
        rc, _stdout, stderr = _run_capture(happy, wrong_ext_out)
        results.append(CheckResult(
            "selftest: wrong output extension fails closed (rc!=0)",
            rc != 0 and not wrong_ext_out.exists(),
            stderr.strip() if rc == 0 else "",
        ))

        # 3. NEGATIVE: render_model with `table` primitive.
        table_ws = td / "with_table"
        _write_synthetic_workspace(table_ws)
        (table_ws / "render_models" / "01_cover.json").write_text(json.dumps({
            "index": 1,
            "layout": "cover",
            "canvas": {"width_px": 1920, "height_px": 1080},
            "source_refs": ["synthetic_src"],
            "primitives": [
                {
                    "id": "bad_table",
                    "kind": "table",
                    "bounds": {"x": 100, "y": 100, "w": 800, "h": 400},
                    "table": {
                        "columns": ["c1", "c2"],
                        "rows": [["a", "b"], ["c", "d"]],
                    },
                },
            ],
        }))
        table_out = td / "table.pptx"
        rc, _stdout, stderr = _run_capture(table_ws, table_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: render_model with `table` primitive fails closed",
            rc != 0 and "table" in msg and not table_out.exists(),
            (f"rc={rc}, missing 'table' in stderr/stdout, "
             f"output_exists={table_out.exists()}"
             if rc == 0 or "table" not in msg or table_out.exists() else ""),
        ))

        # 4. NEGATIVE: render_model with `chart_placeholder` primitive.
        chart_ws = td / "with_chart"
        _write_synthetic_workspace(chart_ws)
        (chart_ws / "render_models" / "01_cover.json").write_text(json.dumps({
            "index": 1,
            "layout": "cover",
            "canvas": {"width_px": 1920, "height_px": 1080},
            "source_refs": ["synthetic_src"],
            "primitives": [
                {
                    "id": "bad_chart",
                    "kind": "chart_placeholder",
                    "bounds": {"x": 100, "y": 100, "w": 800, "h": 400},
                    "chart_placeholder": {
                        "caption": "placeholder",
                        "chart_kind": "bar",
                    },
                },
            ],
        }))
        chart_out = td / "chart.pptx"
        rc, _stdout, stderr = _run_capture(chart_ws, chart_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: render_model with `chart_placeholder` primitive fails closed",
            rc != 0 and "chart_placeholder" in msg and not chart_out.exists(),
            (f"rc={rc}, missing chart_placeholder in messages, "
             f"output_exists={chart_out.exists()}"
             if rc == 0 or "chart_placeholder" not in msg or chart_out.exists() else ""),
        ))

        # 5. NEGATIVE: render_model missing required field (`primitives`).
        malformed_ws = td / "malformed"
        _write_synthetic_workspace(malformed_ws)
        (malformed_ws / "render_models" / "01_cover.json").write_text(json.dumps({
            "index": 1,
            "layout": "cover",
            "canvas": {"width_px": 1920, "height_px": 1080},
            "source_refs": ["synthetic_src"],
            # `primitives` deliberately omitted — fails schema.
        }))
        malformed_out = td / "malformed.pptx"
        rc, _stdout, stderr = _run_capture(malformed_ws, malformed_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: render_model missing required field fails closed",
            rc != 0 and "schema" in msg.lower() and not malformed_out.exists(),
            (f"rc={rc}, missing 'schema' in messages, "
             f"output_exists={malformed_out.exists()}"
             if rc == 0 or "schema" not in msg.lower() or malformed_out.exists() else ""),
        ))

        # 6. NEGATIVE: image_slot referencing an undeclared image id.
        bad_ref_ws = td / "bad_image_ref"
        _write_synthetic_workspace(bad_ref_ws)
        (bad_ref_ws / "render_models" / "01_cover.json").write_text(json.dumps({
            "index": 1,
            "layout": "cover",
            "canvas": {"width_px": 1920, "height_px": 1080},
            "source_refs": ["synthetic_src"],
            "primitives": [
                {
                    "id": "ghost_image",
                    "kind": "image_slot",
                    "bounds": {"x": 100, "y": 100, "w": 400, "h": 400},
                    "image_slot": {"image_ref": "not_in_manifest"},
                },
            ],
        }))
        bad_ref_out = td / "bad_ref.pptx"
        rc, _stdout, stderr = _run_capture(bad_ref_ws, bad_ref_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: image_slot with undeclared image_ref fails closed",
            (
                rc != 0
                and "not_in_manifest" in msg
                and not bad_ref_out.exists()
            ),
            (f"rc={rc}, missing 'not_in_manifest' in messages, "
             f"output_exists={bad_ref_out.exists()}"
             if rc == 0
                or "not_in_manifest" not in msg
                or bad_ref_out.exists() else ""),
        ))

        # 7. POSITIVE (regression): a schema-valid font_family that
        # embeds double-quotes must NOT break the resulting XML
        # attribute. The design_system.schema.json pattern
        # `^[^,]+(\\s*,\\s*[^,]+)*$` only forbids commas, so a value
        # like `Calibri "Bold", Helvetica` is schema-valid. Before
        # the `_attr` helper landed, that string flowed through the
        # default xml_escape (which leaves `"` alone) and broke the
        # <a:latin typeface="..."/> attribute. This scenario builds
        # the workspace, exports, and then parses every slide /
        # theme part with ElementTree to prove the output is still
        # well-formed XML and that the original quoted string is
        # preserved (round-trips through &quot;).
        import xml.etree.ElementTree as _ET
        import zipfile as _zipfile
        quoted_ws = td / "quoted_typography"
        _write_synthetic_workspace(quoted_ws)
        ds_path = quoted_ws / "design_system.json"
        ds = json.loads(ds_path.read_text())
        risky_chain = 'Calibri "Bold Italic", Helvetica & Co, sans-serif'
        ds["typography"]["heading"]["font_family"] = risky_chain
        ds["typography"]["body"]["font_family"] = risky_chain
        ds_path.write_text(json.dumps(ds, indent=2))
        quoted_out = td / "quoted.pptx"
        rc, _stdout, stderr = _run_capture(quoted_ws, quoted_out)
        well_formed = False
        head_face_in_theme = False
        head_face_in_slide = False
        if rc == 0 and quoted_out.is_file():
            try:
                with _zipfile.ZipFile(quoted_out) as _zf:
                    for _name in _zf.namelist():
                        if _name.endswith(".xml") or _name.endswith(".rels"):
                            _ET.fromstring(_zf.read(_name))
                    well_formed = True
                    theme_xml = _zf.read("ppt/theme/theme1.xml").decode("utf-8")
                    head_face_in_theme = 'Calibri &quot;Bold Italic&quot;' in theme_xml
                    slide_xml = _zf.read("ppt/slides/slide1.xml").decode("utf-8")
                    head_face_in_slide = 'Calibri &quot;Bold Italic&quot;' in slide_xml
            except (_ET.ParseError, KeyError, OSError) as exc:
                stderr += f"; parse failed: {exc}"
        results.append(CheckResult(
            "selftest: schema-valid font_family with embedded \" emits "
            "well-formed XML (round-trips through &quot;)",
            rc == 0 and well_formed and head_face_in_theme and head_face_in_slide,
            (f"rc={rc}, well_formed={well_formed}, "
             f"theme_face={head_face_in_theme}, "
             f"slide_face={head_face_in_slide}; {stderr.strip()}"
             if not (rc == 0 and well_formed and head_face_in_theme and head_face_in_slide)
             else ""),
        ))

        # 8. NEGATIVE: image_manifest with an unsafe local_path
        # (URI-scheme prefix). This is also enforced by the workspace
        # validator, but the exporter re-checks it at preflight.
        unsafe_ws = td / "unsafe_manifest"
        _write_synthetic_workspace(unsafe_ws)
        (unsafe_ws / "image_manifest.json").write_text(json.dumps({
            "images": [
                {
                    "id": "unsafe",
                    "local_path": "https://example.invalid/sneaky.png",
                    "source": "synthetic",
                    "alt_text": "should never resolve",
                    "intended_use": "icon",
                    "width_px": 64,
                    "height_px": 64,
                },
            ],
        }))
        unsafe_out = td / "unsafe.pptx"
        rc, _stdout, stderr = _run_capture(unsafe_ws, unsafe_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: image_manifest local_path with URI scheme fails closed",
            (
                rc != 0
                and "unsafe local_path" in msg
                and not unsafe_out.exists()
            ),
            (f"rc={rc}, missing 'unsafe local_path' in messages, "
             f"output_exists={unsafe_out.exists()}"
             if rc == 0
                or "unsafe local_path" not in msg
                or unsafe_out.exists() else ""),
        ))

        # 9. NEGATIVE: render_model with an unsupported layout fails
        # closed and no partial deck is written. Earlier versions of
        # this script treated unsupported layouts as a harmless
        # [SKIP] and still produced a `.pptx` containing the other
        # slides; the contract is now all-or-nothing. The
        # render_model schema's layout pattern is
        # `^[a-z][a-z0-9_]*$`, so a value like "agenda" is
        # schema-valid but outside SUPPORTED_LAYOUTS. The fixture
        # below replaces the workspace's cover slide with an
        # "agenda" layout and keeps the kpi_dashboard slide
        # untouched. The exporter must abort and leave no `.pptx`
        # on disk.
        unsupp_ws = td / "unsupported_layout"
        _write_synthetic_workspace(unsupp_ws)
        (unsupp_ws / "render_models" / "01_cover.json").write_text(json.dumps({
            "index": 1,
            "layout": "agenda",
            "canvas": {"width_px": 1920, "height_px": 1080},
            "source_refs": ["synthetic_src"],
            "primitives": [
                {
                    "id": "title",
                    "kind": "text",
                    "bounds": {"x": 100, "y": 100, "w": 1280, "h": 120},
                    "style": {
                        "color_token": "palette.text",
                        "typography_token": "typography.heading",
                    },
                    "text": {"content": "Agenda", "role": "heading"},
                },
            ],
        }))
        unsupp_out = td / "unsupported.pptx"
        rc, _stdout, stderr = _run_capture(unsupp_ws, unsupp_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: render_model with unsupported layout fails closed "
            "(no partial deck written)",
            (
                rc != 0
                and "agenda" in msg
                and "supported set" in msg
                and not unsupp_out.exists()
            ),
            (f"rc={rc}, missing 'agenda'/'supported set' in messages, "
             f"output_exists={unsupp_out.exists()}"
             if rc == 0
                or "agenda" not in msg
                or "supported set" not in msg
                or unsupp_out.exists() else ""),
        ))

    return results


def _print_results(section: str, results: list[CheckResult]) -> int:
    print(f"\n== {section} ==")
    fails = 0
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        suffix = f" — {r.detail}" if r.detail else ""
        print(f"  [{mark}] {r.name}{suffix}")
        if not r.ok:
            fails += 1
    return fails


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic, stdlib-only PPTX exporter from per-slide "
            "render_model artifacts. Supports the cover and "
            "kpi_dashboard layouts and the text / line / shape / "
            "image_slot / kpi primitive kinds; everything else fails "
            "closed. image_slot primitives emit a placeholder native "
            "shape with alt_text — media embedding is TODO. See "
            "references/pptx-conversion-rules.md for the full contract."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--workspace", type=Path,
        help="Workspace directory containing render_models/*.json. "
             "Required for workspace export; mutually exclusive with "
             "--render-model and --self-test.",
    )
    parser.add_argument(
        "--output", type=Path,
        help="Path to write the .pptx output. Extension must be .pptx. "
             "Required for workspace export and --render-model; ignored "
             "by --self-test.",
    )
    parser.add_argument(
        "--render-model", type=Path,
        help="Optional debug path: export a single render_model.json "
             "file. Requires --design-system and --image-manifest. The "
             "workspace mode (--workspace) is the primary entry point.",
    )
    parser.add_argument(
        "--design-system", type=Path,
        help="Used only with --render-model: path to design_system.json.",
    )
    parser.add_argument(
        "--image-manifest", type=Path,
        help="Used only with --render-model: path to image_manifest.json.",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run the in-script tempfixture positives (happy-path "
             "workspace exports and passes validate_pptx_contract; "
             "schema-valid font_family with embedded \" round-trips as "
             "&quot;) and negatives (wrong output extension, unsupported "
             "`table` primitive, unsupported `chart_placeholder` "
             "primitive, render_model missing a required field, "
             "image_slot image_ref not in manifest, manifest local_path "
             "with a URI scheme, render_model with an unsupported "
             "layout). Exits non-zero if any positive or negative is "
             "not handled as expected.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if any(
            v is not None for v in (
                args.workspace, args.output, args.render_model,
                args.design_system, args.image_manifest,
            )
        ):
            return _fatal(
                "--self-test does not take any other argument"
            )
        fails = _print_results(
            "self-test: tempfixture positives + fail-closed negatives",
            _run_self_tests(),
        )
        print()
        if fails:
            print(f"FAIL: {fails} self-test scenario(s) did not pass.")
            return 1
        print(
            "OK (self-test): the synthetic workspace exports cleanly, "
            "the exported PPTX passes validate_pptx_contract's "
            "container + minimal-evidence checks, and every "
            "fail-closed gate is caught."
        )
        return 0

    if args.output is None:
        return _fatal(
            "--output is required (unless --self-test is used)"
        )

    if args.render_model is not None:
        if args.workspace is not None:
            return _fatal(
                "--workspace and --render-model are mutually exclusive"
            )
        if args.design_system is None or args.image_manifest is None:
            return _fatal(
                "--render-model requires both --design-system and "
                "--image-manifest"
            )
        return export_single_render_model(
            args.render_model, args.design_system, args.image_manifest, args.output,
        )

    if args.workspace is None:
        return _fatal(
            "either --workspace, --render-model, or --self-test is required"
        )
    return export_workspace(args.workspace, args.output)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
