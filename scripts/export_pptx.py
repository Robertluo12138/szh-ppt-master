#!/usr/bin/env python3
"""export_pptx.py

Stdlib-only, fail-closed, deterministic native PPTX exporter for the
editable-ppt pipeline. Consumes a workspace's `render_models/*.json`
directly and emits one editable `.pptx` covering the currently
supported subset:

    layouts:         cover, kpi_dashboard, agenda, section_divider,
                     executive_summary, key_message, two_column,
                     timeline, conclusion, comparison_table
    primitive kinds: text, line, shape, image_slot, kpi, table

The slide body emitter is layout-agnostic — it iterates the
render_model's `primitives` list and emits one native PPTX object per
primitive — so widening the layout allow-list does not change how any
single shape is rendered. `comparison_table` is now in the allow-list:
its defining `table` primitive emits a native PPTX `<p:graphicFrame>`
wrapping `<a:tbl>` (one `<a:gridCol>` per column, one `<a:tr>` per row,
each `<a:tc>` holding an editable `<a:txBody>`), so every cell is
directly editable in PowerPoint without media embedding.

This is NOT a generic SVG-to-PPTX converter. It does NOT parse SVG, it
does NOT screenshot a slide, and it does NOT rasterize a slide into a
single picture. The exporter embeds local PNG / JPG / JPEG assets
referenced by `image_slot` primitives — the bytes are copied into
`ppt/media/imageN.<ext>`, registered with the matching `image/png` or
`image/jpeg` content-type Default, and wired up via per-slide `image`
relationships. SVG / GIF / WebP and any other extension are NOT
embedded today: an `image_slot` whose manifest entry resolves to a
non-PNG/JPG file falls back to the original placeholder shape that
carries the `image_manifest` alt_text. Unsafe / missing / symlinked /
undeclared image references all fail closed at preflight.

INPUTS (all workspace-relative; the same artifacts validate_workspace
exercises today)
    deck_plan.json      — adaptive deck outline; drives the slide
                          enumeration. planning.planned_slide_count
                          must equal len(slides), and each slides[]
                          entry maps 1:1 to a render_model file named
                          `<index:02d>_<layout>.json`.
    design_system.json  — palette + typography + grid
    image_manifest.json — image_ref id -> local_path + alt_text
    render_models/*.json — exactly one per deck_plan slide, named
                           `<index:02d>_<layout>.json`. The exporter
                           iterates deck_plan.slides[] in declared
                           order — it does NOT just glob the directory
                           — so a missing or orphan file aborts the
                           run with no partial deck written.

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
      ppt/media/imageN.<ext>              (one per embedded PNG / JPG /
                                           JPEG manifest entry, indexed
                                           in the manifest's declared
                                           order; binary-byte-stable)

PRIMITIVE -> NATIVE PPTX OBJECT MAPPING
    text         <p:sp> textBox with <p:txBody> and one <a:r> run
    line         <p:cxnSp> straight connector (prstGeom prst="line")
    shape        <p:sp> with prstGeom prst in {rect, roundRect, ellipse}
    kpi          <p:sp> textBox with stacked <a:p> paragraphs
                 (label / value / optional delta) — fully editable
    image_slot   PNG / JPG / JPEG manifest entries -> native <p:pic>
                 with <p:blipFill r:embed="rIdN"/>; the bytes are
                 embedded under ppt/media/imageN.<ext>. Manifest
                 entries with a non-PNG/JPG/JPEG extension (SVG, GIF,
                 WebP, ...) silently demote to a <p:sp> placeholder
                 rectangle whose <a:txBody> carries the
                 image_manifest alt_text. A PNG/JPG/JPEG entry whose
                 path is unsafe / escapes the workspace / is a
                 symlink / is missing or not a regular file / exceeds
                 the 10 MiB embed cap / fails the magic-byte check
                 fails CLOSED at the media preflight and aborts the
                 run before any output is written.
    table        <p:graphicFrame> wrapping <a:tbl> with one <a:gridCol>
                 per column and a bold header row of <a:tc> cells, each
                 cell carrying an editable <a:txBody> with its declared
                 string content. The frame is fully editable as a native
                 PowerPoint table.

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
      images[].local_path passes local_path_is_safe AND, for entries
      whose extension is .png / .jpg / .jpeg (case-insensitive), the
      resolved path stays inside the workspace, is NOT a symlink
      (broken or resolvable), is a regular file, and is small enough
      to read once into memory. Any of those gates failing aborts
      the run before any output is written;
    - deck_plan.json schema-validates against
      schemas/deck_plan.schema.json, planning.planned_slide_count
      equals len(slides), every slides[] entry has integer `index`
      and string `layout`, and `index` values are unique;
    - render_models/ exists and contains exactly the canonical
      filenames named by deck_plan.slides[] (no missing entry, no
      orphan file). The exporter then iterates render_models in the
      order declared by deck_plan.slides[];
    - every render_model file schema-validates against
      schemas/render_model.schema.json and its declared `index` and
      `layout` match the deck_plan entry that named the file;
    - every render_model's `image_slot.image_ref` is declared in
      image_manifest.

PER-SLIDE GATES (every gate FAILS CLOSED for that slide and aborts
the whole run; no partial `.pptx` is written if ANY render_model
trips ANY gate)
    - layout is in SUPPORTED_LAYOUTS (cover, kpi_dashboard, agenda,
      section_divider, executive_summary, key_message, two_column,
      timeline, conclusion, comparison_table); a render_model whose
      layout is outside that set fails closed with a per-slide error.
      The contract is intentionally all-or-nothing: the exporter
      refuses to write a deck that silently drops coverage for slides
      whose layout is not yet implemented.
    - every primitive kind is in SUPPORTED_PRIMITIVE_KINDS (text, line,
      shape, image_slot, kpi, table); a `chart_placeholder` primitive
      fails closed with an explicit error.

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
    - Render models are read in deck_plan.slides[] order; the
      resulting `ppt/slides/slide{N}.xml` numbering follows that order
      (slide1.xml is the first deck_plan slide, slide2.xml the second,
      ...). The original render_model `index` is preserved in the
      slide's non-visual name so the slide can still be traced back
      to its workspace artifact.
    - Shape ids start at 2 and increment per primitive, deterministic.
    - Every ZIP entry is written with a fixed timestamp (1980-01-01).

OUT OF SCOPE
    - SVG / GIF / WebP media embedding (deferred — these manifest
      entries fall back to the placeholder shape).
    - PPTX `chart_placeholder` emission (deferred — fail closed today).
    - Layouts outside the SUPPORTED_LAYOUTS allow-list above. Every
      layout declared by the business_review template skeleton is
      currently in scope; new layouts must add a paired generator
      branch before they may appear here.
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
from dataclasses import dataclass, field
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

# Layouts the exporter is willing to emit. The slide-body emitter
# (`_slide_xml`) is layout-agnostic — it walks the render_model's
# `primitives` list and emits one native PPTX object per primitive —
# so this allow-list is purely a contract gate: the exporter only
# accepts render_models whose `layout` value is on this list, and
# fails closed (whole-run abort, no partial deck) on any other layout.
# Every layout declared by the business_review template skeleton is
# currently in scope; the `table` primitive is exported as a native
# `<p:graphicFrame>` wrapping `<a:tbl>`, so `comparison_table` is now
# in the allow-list. New layouts must add a paired generator branch
# before they may appear here.
SUPPORTED_LAYOUTS = (
    "cover",
    "kpi_dashboard",
    "agenda",
    "section_divider",
    "executive_summary",
    "key_message",
    "two_column",
    "timeline",
    "conclusion",
    "comparison_table",
)
SUPPORTED_PRIMITIVE_KINDS = ("text", "line", "shape", "image_slot", "kpi", "table")

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
REL_IMAGE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)

# PNG / JPG / JPEG embedding map. The exporter only embeds these
# extensions today; manifest entries with any other extension fall back
# to the placeholder shape (see _render_image_slot_sp). Keys are the
# lower-cased extension WITHOUT a leading dot; values are the OOXML
# Default `ContentType` we register for that extension and the file
# extension we use inside `ppt/media/`.
EMBEDDABLE_IMAGE_EXTENSIONS: dict[str, tuple[str, str]] = {
    "png":  ("image/png",  "png"),
    "jpg":  ("image/jpeg", "jpg"),
    "jpeg": ("image/jpeg", "jpeg"),
}

# Magic-byte signatures used as a defense-in-depth check that the file
# behind a manifest entry is actually the format its extension claims
# to be. We refuse to embed (and fall back to the placeholder shape) if
# the file's leading bytes do not match the expected signature for its
# extension. This catches a `.png`-named text file before the bytes
# ever land in the PPTX. JPEG covers JFIF / EXIF / SPIFF leading bytes
# that all start `FF D8 FF`; PNG always starts with the 8-byte
# `\x89PNG\r\n\x1a\n` signature.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE_PREFIX = b"\xff\xd8\xff"

# Hard cap on the per-asset byte size we are willing to read into
# memory. The pipeline targets spot illustrations / icons / decorative
# artwork, so a 10 MiB ceiling is a generous upper bound. Anything
# larger is refused at preflight rather than silently embedded — this
# keeps the deterministic ZIP under control and makes a regression
# (someone wiring up a full-slide screenshot) loud.
_MAX_EMBEDDED_BYTES = 10 * 1024 * 1024

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


@dataclass
class MediaResolution:
    """Resolved media information for an image_manifest entry the
    exporter is willing to embed.

    Built once at preflight in `_build_media_plan`. Only PNG / JPG /
    JPEG entries that pass every safety gate (path-safety, no symlink,
    inside the workspace, regular file, magic bytes match, file size
    under the embed cap) get a MediaResolution; every other manifest
    entry stays out of the plan and falls back to the placeholder shape
    in `_render_image_slot_sp`.

    `media_filename` is deterministic and follows the manifest's
    declared order so the resulting PPTX bytes are stable across runs:
    the first embeddable manifest entry is `image1.<ext>`, the second
    `image2.<ext>`, and so on. The leading number is shared across
    extensions; an embedded mix of PNG and JPG keeps a single counter."""
    image_id: str
    local_path: str
    abs_path: Path
    extension: str  # lower-cased, no leading dot, e.g. "png"
    content_type: str  # e.g. "image/png"
    media_filename: str  # e.g. "image1.png"
    bytes_payload: bytes = field(default=b"", repr=False)


def _fatal(msg: str) -> int:
    print(f"FAIL: {msg}", file=sys.stderr)
    return 1


def _embeddable_extension(local_path: str) -> str | None:
    """Return the lower-cased extension WITHOUT the leading dot if the
    path's extension is in EMBEDDABLE_IMAGE_EXTENSIONS, else None.

    The check is purely on the string suffix — the caller handles the
    filesystem checks separately so a fail-closed gate can report the
    exact reason (extension vs. symlink vs. magic bytes vs. ...)."""
    suffix = Path(local_path).suffix.lower().lstrip(".")
    if suffix in EMBEDDABLE_IMAGE_EXTENSIONS:
        return suffix
    return None


def _matches_image_signature(extension: str, payload: bytes) -> bool:
    """True iff `payload` starts with the magic bytes for `extension`.

    Defense-in-depth alongside `_embeddable_extension` so a `.png`-
    named text file (or a `.jpg`-named SVG document) cannot be embedded
    even when its name and the manifest pass every other gate."""
    if extension == "png":
        return payload.startswith(_PNG_SIGNATURE)
    if extension in ("jpg", "jpeg"):
        return payload.startswith(_JPEG_SIGNATURE_PREFIX)
    return False


def _resolve_inside_workspace(workspace: Path, local_path: str) -> Path | None:
    """Resolve `local_path` against `workspace` and confirm the result
    stays under `workspace` after resolution.

    Returns the resolved absolute Path on success, or None if the
    resolution escapes the workspace (the caller must already have
    confirmed the string-level safety via `local_path_is_safe`).
    Reused for the per-asset symlink-escape gate below."""
    base_resolved = workspace.resolve()
    candidate = (workspace / local_path).resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError:
        return None
    return candidate


def _build_media_plan(
    workspace: Path, manifest: dict,
) -> tuple[dict[str, MediaResolution], list[str]]:
    """Walk image_manifest.images[] and return the (media_plan, errors)
    pair the exporter uses to decide which entries embed and which
    fall back to the placeholder shape.

    Per-entry gates (each a fail-closed reason; the FIRST failure for an
    entry is recorded and the entry stays out of the plan):

      0. id and local_path are already string-validated by the caller's
         path-safety preflight; this function trusts the caller's prior
         pass on those (it still re-checks `local_path_is_safe` because
         the cost is minimal).
      1. extension is in EMBEDDABLE_IMAGE_EXTENSIONS — otherwise the
         entry is silently demoted to placeholder (NOT an error: the
         contract permits SVG / GIF / WebP placeholders).
      2. asset path is NOT a symlink (broken or resolvable) — a
         symlink at the asset path would otherwise let the exporter
         embed bytes outside the workspace. Checked BEFORE the
         resolve gate so the symlink-specific error message fires
         even when the symlink target sits outside the workspace
         (which would also trip gate 3). Mirrors the symlink gate the
         workspace validator already enforces on
         `source_manifest.json`.
      3. resolved path stays inside the workspace after Path.resolve()
         (defense in depth against a path that passed the string-level
         path-safety check but resolves outside via a symlink in a
         parent directory).
      4. resolved path is a regular file (not a directory, not a
         device, not missing).
      5. file size is under `_MAX_EMBEDDED_BYTES`.
      6. magic bytes match the declared extension.

    Gates 2-6 are fail-closed errors recorded in the returned list and
    the export aborts. Gate 1 (extension) silently demotes to
    placeholder — the entry is intentionally NOT in the plan and the
    placeholder branch in `_render_image_slot_sp` handles it. The
    manifest's declared order drives the deterministic
    `image1.<ext>`, `image2.<ext>`, ... numbering."""
    plan: dict[str, MediaResolution] = {}
    errors: list[str] = []
    media_index = 0
    for img in _as_list(manifest.get("images")) or []:
        img_d = _as_dict(img)
        if img_d is None:
            continue
        image_id = img_d.get("id")
        local_path = img_d.get("local_path")
        if not isinstance(image_id, str) or not image_id:
            continue
        if not isinstance(local_path, str) or not local_path:
            continue
        if not local_path_is_safe(local_path):
            errors.append(
                f"image_manifest entry {image_id!r}: local_path "
                f"{local_path!r} fails path-safety; refusing to embed"
            )
            continue
        ext = _embeddable_extension(local_path)
        if ext is None:
            # Non-PNG/JPG entries fall back to the placeholder shape.
            # This is intentional behavior, NOT an error.
            continue
        # Symlink gate fires BEFORE resolve. Path.is_symlink() does
        # NOT follow the link, so it catches the case where the
        # symlink itself sits inside the workspace but points
        # anywhere — inside or outside.
        unresolved_asset = workspace / local_path
        if unresolved_asset.is_symlink():
            errors.append(
                f"image_manifest entry {image_id!r}: local_path "
                f"{local_path!r} is a symlink (refused; broken or "
                f"resolvable)"
            )
            continue
        resolved = _resolve_inside_workspace(workspace, local_path)
        if resolved is None:
            errors.append(
                f"image_manifest entry {image_id!r}: local_path "
                f"{local_path!r} resolves outside the workspace; "
                f"refusing to embed"
            )
            continue
        if not resolved.is_file():
            errors.append(
                f"image_manifest entry {image_id!r}: local_path "
                f"{local_path!r} does not resolve to a regular file"
            )
            continue
        try:
            size = resolved.stat().st_size
        except OSError as exc:
            errors.append(
                f"image_manifest entry {image_id!r}: cannot stat "
                f"{local_path!r}: {exc}"
            )
            continue
        if size > _MAX_EMBEDDED_BYTES:
            errors.append(
                f"image_manifest entry {image_id!r}: local_path "
                f"{local_path!r} is {size} bytes, exceeds the "
                f"{_MAX_EMBEDDED_BYTES}-byte embed cap"
            )
            continue
        try:
            payload = resolved.read_bytes()
        except OSError as exc:
            errors.append(
                f"image_manifest entry {image_id!r}: cannot read "
                f"{local_path!r}: {exc}"
            )
            continue
        if not _matches_image_signature(ext, payload):
            errors.append(
                f"image_manifest entry {image_id!r}: local_path "
                f"{local_path!r} does not start with the expected "
                f"{ext.upper()} magic bytes; refusing to embed"
            )
            continue
        media_index += 1
        content_type, ext_used = EMBEDDABLE_IMAGE_EXTENSIONS[ext]
        media_filename = f"image{media_index}.{ext_used}"
        plan[image_id] = MediaResolution(
            image_id=image_id,
            local_path=local_path,
            abs_path=resolved,
            extension=ext,
            content_type=content_type,
            media_filename=media_filename,
            bytes_payload=payload,
        )
    return (plan, errors)


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


def _render_image_slot_pic(
    prim: dict,
    shape_id: int,
    alt_text: str,
    image_ref: str,
    media_rel_id: str,
) -> str:
    """image_slot primitive -> native <p:pic> with <p:blipFill> pointing
    at an embedded media relationship.

    Used when `_build_media_plan` resolved a PNG / JPG / JPEG file for
    the manifest entry. The bounds are mapped 1:1 from the
    render_model's pixel canvas to EMU just like every other primitive
    so the picture lands exactly where the SVG preview shows it.

    `media_rel_id` is the per-slide relationship Id (e.g. `rId2`) that
    the slide's `_rels/slideN.xml.rels` will resolve to
    `../media/imageM.<ext>` — callers assemble that rels file
    separately. The picture carries the manifest's `alt_text` as
    `descr=`, which screen readers use AND PowerPoint preserves when
    the picture is edited."""
    bounds = prim["bounds"]
    off_x, off_y, ext_cx, ext_cy = _bounds_to_xfrm(bounds)
    pid = prim.get("id") or "image_slot"
    return (
        f'<p:pic>'
        f'<p:nvPicPr>'
        f'<p:cNvPr id="{shape_id}" name="{_attr(f"image_slot:{pid}")}" '
        f'descr="{_attr(alt_text)}"/>'
        f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>'
        f'<p:nvPr/>'
        f'</p:nvPicPr>'
        f'<p:blipFill>'
        f'<a:blip r:embed="{media_rel_id}"/>'
        f'<a:stretch><a:fillRect/></a:stretch>'
        f'</p:blipFill>'
        f'<p:spPr>{_xfrm_xml(off_x, off_y, ext_cx, ext_cy)}'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f'</p:spPr>'
        f'</p:pic>'
    )


def _render_image_slot_sp(
    prim: dict,
    design: dict,
    shape_id: int,
    manifest_alts: dict,
    manifest_paths: dict,
    media_plan: dict,
    slide_media_uses: list[str],
) -> str:
    """image_slot primitive -> editable native shape.

    Two cases:
      - `image_ref` resolves to an entry in `media_plan` (PNG / JPG /
        JPEG passed every embed gate): we emit a `<p:pic>` carrying the
        embedded media relationship. The slide's per-slide rels list
        records the use through `slide_media_uses` so the caller can
        build `_rels/slideN.xml.rels` deterministically.
      - otherwise: we emit a `<p:sp>` placeholder rectangle whose
        `<a:txBody>` carries the manifest's `alt_text`. This is the
        SVG / GIF / WebP / missing-asset fallback. The placeholder
        contract is unchanged from earlier versions — the test suite's
        baseline placeholder fixture still passes.

    Defense in depth: the manifest path-safety preflight has already
    run, but we re-check `local_path_is_safe` at use time so a later
    regression cannot leak an unsafe path through the alt-text branch."""
    payload = _as_dict(prim.get("image_slot")) or {}
    image_ref = payload.get("image_ref")
    if not isinstance(image_ref, str) or not image_ref:
        raise ExportError("image_slot primitive missing image_ref")
    if image_ref not in manifest_paths:
        raise ExportError(
            f"image_slot primitive references image id {image_ref!r} "
            f"that is not declared in image_manifest"
        )
    local_path = manifest_paths[image_ref]
    if not local_path_is_safe(local_path):
        raise ExportError(
            f"image_slot primitive resolves to unsafe local_path "
            f"{local_path!r} for image id {image_ref!r}"
        )
    alt_text = payload.get("alt_text") or manifest_alts.get(image_ref) or image_ref

    media = media_plan.get(image_ref)
    if media is not None:
        # Embed branch: record the use (deterministic per-slide order,
        # de-duplicated so two image_slots referencing the same asset
        # share a single relationship) and emit a <p:pic>.
        if image_ref in slide_media_uses:
            slot_index = slide_media_uses.index(image_ref)
        else:
            slot_index = len(slide_media_uses)
            slide_media_uses.append(image_ref)
        # rId1 is reserved for the slideLayout relationship; image rels
        # start at rId2.
        media_rel_id = f"rId{2 + slot_index}"
        return _render_image_slot_pic(
            prim, shape_id, alt_text, image_ref, media_rel_id,
        )

    # Placeholder branch (SVG / GIF / WebP / non-embeddable extension):
    # exactly the prior behavior. Thin neutral stroke + no fill keeps
    # the placeholder visible during editing without overpainting slide
    # content.
    bounds = prim["bounds"]
    off_x, off_y, ext_cx, ext_cy = _bounds_to_xfrm(bounds)
    text_family_chain, text_pt = _resolve_typography(design, "typography.body")
    text_family = _font_first(text_family_chain)
    text_color = _resolve_palette(design, "palette.text")
    body_cp = _sz_centipoints(text_pt)
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


def _table_cell_xml(content: str, *, run_pr: str, anchor: str = "ctr") -> str:
    """Emit one <a:tc> with a single <a:p> + <a:r> + <a:t> run. anchor
    centers the cell text vertically; PowerPoint accepts `ctr`, `t`, `b`.
    The cell carries an empty <a:tcPr/> so the table inherits the
    default style and the export stays minimal — styling extensions
    (zebra striping, borders, ...) remain TODO."""
    return (
        f'<a:tc>'
        f'<a:txBody>'
        f'<a:bodyPr wrap="square" lIns="36576" tIns="22860" '
        f'rIns="36576" bIns="22860" anchor="{anchor}"/>'
        f'<a:lstStyle/>'
        f'<a:p><a:r>{run_pr}<a:t>{xml_escape(content)}</a:t></a:r></a:p>'
        f'</a:txBody>'
        f'<a:tcPr/>'
        f'</a:tc>'
    )


def _render_table_graphicframe(prim: dict, design: dict, shape_id: int) -> str:
    """table primitive -> native <p:graphicFrame> wrapping <a:tbl>.

    Every cell carries an editable <a:txBody> with the declared string
    content, so a PowerPoint user can click into the cell and edit it
    directly. Column widths are distributed uniformly across the
    primitive bounds; rows split the bounds between a single header row
    and the body rows. Integer arithmetic only so the output is
    byte-stable across machines and runs.

    Defense-in-depth: the controlled schema already constrains
    `columns` to a non-empty list of strings and `rows` to a non-empty
    list of equal-length string arrays, but the emitter re-checks at
    the point of XML generation so a malformed render_model that
    sneaks past schema validation still fails closed here rather than
    smuggling untrusted text into the output."""
    bounds = prim["bounds"]
    off_x, off_y, ext_cx, ext_cy = _bounds_to_xfrm(bounds)
    style = _as_dict(prim.get("style")) or {}
    color_token = style.get("color_token")
    if not isinstance(color_token, str):
        raise ExportError("table primitive missing style.color_token")
    color = _resolve_palette(design, color_token)
    body_family_chain, body_pt = _resolve_typography(design, "typography.body")
    head_family_chain, head_pt = _resolve_typography(design, "typography.heading")
    body_family = _font_first(body_family_chain)
    head_family = _font_first(head_family_chain)
    body_cp = _sz_centipoints(body_pt)
    head_cp = _sz_centipoints(head_pt)

    payload = _as_dict(prim.get("table")) or {}
    columns = payload.get("columns")
    rows = payload.get("rows")
    if not isinstance(columns, list) or not columns:
        raise ExportError("table primitive missing non-empty columns")
    if not isinstance(rows, list) or not rows:
        raise ExportError("table primitive missing non-empty rows")
    col_count = len(columns)
    body_row_count = len(rows)
    total_rows = body_row_count + 1  # header + body

    col_w_emu = ext_cx // col_count
    row_h_emu = ext_cy // total_rows
    if col_w_emu <= 0 or row_h_emu <= 0:
        raise ExportError(
            f"table primitive bounds {ext_cx}x{ext_cy} EMU too small for "
            f"{col_count} cols x {total_rows} rows"
        )

    grid_cols_xml = "".join(
        f'<a:gridCol w="{col_w_emu}"/>' for _ in range(col_count)
    )

    head_run_pr = _run_pr_xml(
        size_cp=head_cp, hex_color=color, bold=True, font_first=head_family,
    )
    body_run_pr = _run_pr_xml(
        size_cp=body_cp, hex_color=color, bold=False, font_first=body_family,
    )

    header_cells: list[str] = []
    for c_i, header in enumerate(columns):
        if not isinstance(header, str) or not header:
            raise ExportError(
                f"table primitive columns[{c_i}] is not a non-empty string"
            )
        header_cells.append(_table_cell_xml(header, run_pr=head_run_pr))
    rows_xml: list[str] = [
        f'<a:tr h="{row_h_emu}">{"".join(header_cells)}</a:tr>'
    ]
    for r_i, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != col_count:
            raise ExportError(
                f"table primitive rows[{r_i}] has the wrong cell count "
                f"(expected {col_count})"
            )
        body_cells: list[str] = []
        for c_i, cell in enumerate(row):
            if not isinstance(cell, str) or not cell:
                raise ExportError(
                    f"table primitive rows[{r_i}][{c_i}] is not a "
                    f"non-empty string"
                )
            body_cells.append(_table_cell_xml(cell, run_pr=body_run_pr))
        rows_xml.append(
            f'<a:tr h="{row_h_emu}">{"".join(body_cells)}</a:tr>'
        )

    pid = prim.get("id") or "table"
    return (
        f'<p:graphicFrame>'
        f'<p:nvGraphicFramePr>'
        f'<p:cNvPr id="{shape_id}" name="{_attr(f"table:{pid}")}"/>'
        f'<p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr>'
        f'<p:nvPr/>'
        f'</p:nvGraphicFramePr>'
        f'<p:xfrm>'
        f'<a:off x="{off_x}" y="{off_y}"/>'
        f'<a:ext cx="{ext_cx}" cy="{ext_cy}"/>'
        f'</p:xfrm>'
        f'<a:graphic>'
        f'<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">'
        f'<a:tbl>'
        f'<a:tblPr firstRow="1"><a:tableStyleId>'
        f'{{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}}'
        f'</a:tableStyleId></a:tblPr>'
        f'<a:tblGrid>{grid_cols_xml}</a:tblGrid>'
        f'{"".join(rows_xml)}'
        f'</a:tbl>'
        f'</a:graphicData>'
        f'</a:graphic>'
        f'</p:graphicFrame>'
    )


def _render_primitive(
    prim: dict,
    design: dict,
    shape_id: int,
    manifest_alts: dict,
    manifest_paths: dict,
    media_plan: dict,
    slide_media_uses: list[str],
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
            media_plan, slide_media_uses,
        )
    if kind == "table":
        return _render_table_graphicframe(prim, design, shape_id)
    # Fail closed on chart_placeholder / anything else. These remain
    # TODO per references/pptx-conversion-rules.md.
    raise ExportError(
        f"primitive kind {kind!r} is not supported by the PPTX exporter "
        f"today (supported: {SUPPORTED_PRIMITIVE_KINDS}); "
        f"`chart_placeholder` is deferred and must fail closed"
    )


# --- Slide / package XML ---------------------------------------------------

def _slide_xml(
    render_model: dict,
    design: dict,
    manifest_alts: dict,
    manifest_paths: dict,
    media_plan: dict,
) -> tuple[str, list[str]]:
    """Build the per-slide XML for a supported render_model.

    Returns (xml, slide_media_uses) where `slide_media_uses` is the
    ordered list of `image_id` values the slide embeds via `<p:pic>`
    (one per referenced asset, de-duplicated). The caller turns that
    list into per-slide `image` relationships in the slide's
    `_rels/slideN.xml.rels`.

    Shape ids start at 2 because id=1 is reserved for the spTree group
    root."""
    primitives = _as_list(render_model.get("primitives")) or []
    bg_hex = _resolve_palette(design, "palette.background")
    shape_xml_parts: list[str] = []
    slide_media_uses: list[str] = []
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
                f"`chart_placeholder` remains TODO and must fail closed "
                f"in this exporter"
            )
        shape_xml_parts.append(
            _render_primitive(
                prim, design, next_id, manifest_alts, manifest_paths,
                media_plan, slide_media_uses,
            )
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
    ), slide_media_uses


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


def _content_types_xml(
    slide_count: int,
    embedded_image_extensions: set[str] | None = None,
) -> str:
    """[Content_Types].xml.

    Defaults declare the well-known extensions (`rels` + `xml`) and one
    extra Default per embedded image extension (png / jpg / jpeg). Every
    document part is registered via an explicit Override so the package
    is unambiguous; embedded media parts under `ppt/media/` are
    recognised through the matching Default rather than per-file
    Overrides — that is the conventional OOXML pattern PowerPoint
    consumes."""
    extensions = embedded_image_extensions or set()
    extra_defaults: list[tuple[str, str]] = []
    # Sort so the rendered XML is deterministic across runs.
    for ext in sorted(extensions):
        ct, _ = EMBEDDABLE_IMAGE_EXTENSIONS[ext]
        extra_defaults.append((ext, ct))
    extra_default_xml = "".join(
        f'<Default Extension="{ext}" ContentType="{ct}"/>'
        for ext, ct in extra_defaults
    )
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
        f'{extra_default_xml}'
        f'{override_xml}'
        f'</Types>'
    )


# --- Package assembly ------------------------------------------------------

def _build_package_parts(
    slides: list[tuple[dict, str, list[str]]],
    design: dict,
    canvas_w_px: int,
    canvas_h_px: int,
    media_plan: dict,
) -> tuple[dict[str, str], dict[str, bytes]]:
    """Assemble every package part for the PPTX ZIP.

    Returns `(text_parts, binary_parts)` — both keyed by POSIX member
    path. `text_parts` carries the OOXML / rels XML payloads (UTF-8
    strings); `binary_parts` carries the embedded media bytes (PNG /
    JPG / JPEG). The caller writes both into the ZIP.

    Each entry in `slides` is `(render_model, slide_xml, media_uses)`.
    `media_uses` is the per-slide ordered list of `image_id` values the
    slide embeds; we turn it into per-slide `image` relationships
    deterministically — the first image used on a slide gets `rId2`
    (rId1 is reserved for the slideLayout relationship), the second
    `rId3`, and so on. The slide XML emitted by `_slide_xml` already
    references those rId values."""
    slide_count = len(slides)

    # Collect the embedded extensions actually in use so the
    # [Content_Types].xml emits matching `<Default>` entries.
    referenced_image_ids: set[str] = set()
    for _, _, uses in slides:
        for image_id in uses:
            referenced_image_ids.add(image_id)
    embedded_extensions: set[str] = set()
    for image_id in referenced_image_ids:
        media = media_plan.get(image_id)
        if media is not None:
            embedded_extensions.add(media.extension)

    text_parts: dict[str, str] = {}
    binary_parts: dict[str, bytes] = {}

    text_parts["[Content_Types].xml"] = _content_types_xml(
        slide_count, embedded_extensions,
    )
    text_parts["_rels/.rels"] = _rels_xml([
        ("rId1", REL_OFFICE_DOCUMENT, "ppt/presentation.xml"),
    ])
    text_parts["ppt/presentation.xml"] = _presentation_xml(
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
    text_parts["ppt/_rels/presentation.xml.rels"] = _rels_xml(pres_rels)

    text_parts["ppt/slideMasters/slideMaster1.xml"] = _slide_master_xml()
    text_parts["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = _rels_xml([
        ("rId1", REL_SLIDE_LAYOUT, "../slideLayouts/slideLayout1.xml"),
        ("rId2", REL_THEME, "../theme/theme1.xml"),
    ])
    text_parts["ppt/slideLayouts/slideLayout1.xml"] = _slide_layout_xml()
    text_parts["ppt/slideLayouts/_rels/slideLayout1.xml.rels"] = _rels_xml([
        ("rId1", REL_SLIDE_MASTER, "../slideMasters/slideMaster1.xml"),
    ])
    text_parts["ppt/theme/theme1.xml"] = _theme_xml(design)

    for i, (rm, slide_xml, media_uses) in enumerate(slides, start=1):
        text_parts[f"ppt/slides/slide{i}.xml"] = slide_xml
        slide_rels: list[tuple[str, str, str]] = [
            ("rId1", REL_SLIDE_LAYOUT, "../slideLayouts/slideLayout1.xml"),
        ]
        for j, image_id in enumerate(media_uses):
            media = media_plan[image_id]  # KeyError would trip _slide_xml first
            slide_rels.append(
                (f"rId{2 + j}", REL_IMAGE, f"../media/{media.media_filename}")
            )
        text_parts[f"ppt/slides/_rels/slide{i}.xml.rels"] = _rels_xml(slide_rels)

    # Embed the media bytes once per unique referenced asset. The plan
    # already pre-loaded the bytes at preflight; we just hand them to
    # the ZIP writer here.
    for image_id in sorted(referenced_image_ids):
        media = media_plan.get(image_id)
        if media is None:
            continue
        binary_parts[f"ppt/media/{media.media_filename}"] = media.bytes_payload

    return (text_parts, binary_parts)


def _write_pptx(
    output_path: Path,
    text_parts: dict[str, str],
    binary_parts: dict[str, bytes] | None = None,
) -> None:
    """Write text + binary parts (sorted by member path) into a
    deterministic ZIP. Text parts are written as UTF-8; binary parts
    (PPTX media: PNG / JPG / JPEG bytes) are written verbatim with the
    same fixed timestamp so the ZIP byte-stable property still holds."""
    binary_parts = binary_parts or {}
    overlap = set(text_parts) & set(binary_parts)
    if overlap:
        raise ExportError(
            f"text and binary part names overlap: {sorted(overlap)!r}"
        )
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(set(text_parts) | set(binary_parts)):
            info = zipfile.ZipInfo(name)
            info.date_time = _ZIP_TIMESTAMP
            info.compress_type = zipfile.ZIP_DEFLATED
            if name in text_parts:
                zf.writestr(info, text_parts[name])
            else:
                zf.writestr(info, binary_parts[name])


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

    # Media-embed preflight: walk the manifest and build the
    # `media_plan` (PNG / JPG / JPEG entries that pass every embed
    # gate). Manifest entries with a non-PNG/JPG extension are
    # intentionally NOT errors — they fall back to the placeholder
    # shape (`_render_image_slot_sp` handles that). Any embed-gate
    # error (escapes workspace, symlink, missing file, oversize, magic
    # mismatch) aborts the run before any output is written.
    media_plan, media_errors = _build_media_plan(workspace, manifest)
    if media_errors:
        for err in media_errors:
            print(f"  [FAIL] {err}", file=sys.stderr)
        return _fatal(
            f"image_manifest media embed preflight failed "
            f"({len(media_errors)} error(s)); refusing to export"
        )

    # deck_plan.json is the source of truth for slide count and order.
    # The exporter does NOT just glob render_models/*.json: a workspace
    # missing one render_model would otherwise silently export a partial
    # deck. Loading deck_plan first lets us assert exact 1:1 coverage
    # before any output is produced.
    deck_plan, err = _load_required_object(
        workspace / "deck_plan.json", "deck_plan.json",
    )
    if deck_plan is None:
        return _fatal(err)
    schema_errors = _schema_validate(
        deck_plan, SCHEMAS / "deck_plan.schema.json",
    )
    if schema_errors:
        return _fatal(
            f"deck_plan.json fails schema: {'; '.join(schema_errors)}"
        )
    planning = _as_dict(deck_plan.get("planning")) or {}
    planned_count = planning.get("planned_slide_count")
    plan_slides_raw = _as_list(deck_plan.get("slides"))
    if plan_slides_raw is None:
        return _fatal("deck_plan.slides must be a list")
    if (
        not isinstance(planned_count, int)
        or isinstance(planned_count, bool)
        or planned_count < 1
    ):
        return _fatal(
            f"deck_plan.planning.planned_slide_count must be a positive "
            f"integer; got {planned_count!r}"
        )
    if planned_count != len(plan_slides_raw):
        return _fatal(
            f"deck_plan.planning.planned_slide_count "
            f"({planned_count}) does not equal len(slides) "
            f"({len(plan_slides_raw)}); refusing to export"
        )

    # Build the (index, layout, canonical_filename) tuples in declared
    # order. Each per-slide defensive check is also enforced by the
    # schema, but we re-check here so a non-schema-validated deck_plan
    # cannot reach the slide-emit loop.
    plan_entries: list[tuple[int, str, str]] = []
    seen_indices: set[int] = set()
    for i, raw_slide in enumerate(plan_slides_raw):
        slide_d = _as_dict(raw_slide)
        if slide_d is None:
            return _fatal(
                f"deck_plan.slides[{i}] is not an object "
                f"(got {type(raw_slide).__name__})"
            )
        idx = slide_d.get("index")
        layout = slide_d.get("layout")
        if not isinstance(idx, int) or isinstance(idx, bool):
            return _fatal(
                f"deck_plan.slides[{i}].index is not an integer "
                f"(got {type(idx).__name__})"
            )
        if not isinstance(layout, str) or not layout:
            return _fatal(
                f"deck_plan.slides[{i}].layout is not a non-empty string "
                f"(got {layout!r})"
            )
        if idx in seen_indices:
            return _fatal(
                f"deck_plan.slides has duplicate index {idx} "
                f"(slot {i}); refusing to export"
            )
        seen_indices.add(idx)
        plan_entries.append((idx, layout, f"{idx:02d}_{layout}.json"))

    rm_dir = workspace / "render_models"
    if not rm_dir.is_dir():
        return _fatal(
            f"render_models/ not found at {rm_dir} — run "
            f"generate_render_models.py first"
        )

    # 1:1 coverage: every deck_plan slide must have its canonical
    # render_model on disk, and there must be no extra/orphan *.json
    # under render_models/. The deck_plan is authoritative; we do NOT
    # silently export only the files that happen to be present.
    expected_files = {fname for _, _, fname in plan_entries}
    on_disk_files = {p.name for p in rm_dir.glob("*.json")}
    missing = sorted(expected_files - on_disk_files)
    orphan = sorted(on_disk_files - expected_files)
    if missing or orphan:
        for name in missing:
            print(
                f"  [FAIL] deck_plan declares render_models/{name} but "
                f"it is missing on disk",
                file=sys.stderr,
            )
        for name in orphan:
            print(
                f"  [FAIL] render_models/{name} exists on disk but is "
                f"not declared by deck_plan.slides[]; refusing to "
                f"export an orphan",
                file=sys.stderr,
            )
        print(
            f"FAIL: PPTX export aborted; deck_plan declares "
            f"{len(plan_entries)} slide(s) but render_models/ disagrees "
            f"({len(missing)} missing, {len(orphan)} orphan). "
            f"No `.pptx` was written.",
            file=sys.stderr,
        )
        return 1

    # Build the deck_plan-ordered list of files the exporter will read.
    rm_files = [rm_dir / fname for _, _, fname in plan_entries]

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

    exported: list[tuple[dict, str, list[str]]] = []
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

        # Canonical filename gate (fail-closed).
        #
        # The 1:1 coverage gate already guaranteed that every on-disk
        # filename is the canonical `<idx:02d>_<layout>.json` named by
        # deck_plan, and every deck_plan slide has its canonical file
        # present. This in-loop gate additionally requires the JSON's
        # OWN declared `index`/`layout` to agree with the filename it
        # was loaded from — so a `02_kpi_dashboard.json` whose body
        # claims `index=7` or `layout="cover"` is rejected even though
        # deck_plan and the filename agree. The two gates together
        # transitively pin (deck_plan entry) == (canonical filename) ==
        # (JSON body) for every slide.
        expected_name = f"{idx:02d}_{layout}.json"
        if rm_file.name != expected_name:
            fatal_errors.append(
                f"{rel} (index={idx}, layout={layout!r}): on-disk filename "
                f"{rm_file.name!r} disagrees with the render_model's own "
                f"index + layout; expected {expected_name!r}. Rename the "
                f"file or re-run scripts/generate_render_models.py"
            )
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
            xml, slide_media_uses = _slide_xml(
                rm, design, manifest_alts, manifest_paths, media_plan,
            )
        except ExportError as exc:
            fatal_errors.append(f"{rel} (index={idx}, {layout}): {exc}")
            continue
        exported.append((rm, xml, slide_media_uses))

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

    text_parts, binary_parts = _build_package_parts(
        exported, design, canvas_w, canvas_h, media_plan,
    )
    _write_pptx(output, text_parts, binary_parts)

    embedded_count = len(binary_parts)
    print(f"Exported {len(exported)} slide(s) to {output}:")
    for i, (rm, _, media_uses) in enumerate(exported, start=1):
        media_note = (
            f" [media: {', '.join(media_uses)}]" if media_uses else ""
        )
        print(
            f"  [EXPORT] slide {i:>2} (render_model index "
            f"{rm.get('index'):>2}, layout {rm.get('layout')!r}) "
            f"-> ppt/slides/slide{i}.xml{media_note}"
        )
    print(
        f"\nOK: PPTX export succeeded for {len(exported)} slide(s). "
        f"Embedded {embedded_count} unique image asset(s) under "
        f"ppt/media/ (PNG / JPG / JPEG only); SVG / GIF / WebP "
        f"manifest entries fall back to the placeholder shape. "
        f"`chart_placeholder` primitives and layouts outside the "
        f"allow-list {SUPPORTED_LAYOUTS} still fail closed and remain "
        f"TODO."
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
    # Single-render-model debug mode resolves the media plan against
    # the manifest's parent directory (the workspace it lives in) so
    # the same PNG / JPG / JPEG embed branch as workspace mode applies.
    media_plan, media_errors = _build_media_plan(
        manifest_path.parent, manifest,
    )
    if media_errors:
        for err in media_errors:
            print(f"  [FAIL] {err}", file=sys.stderr)
        return _fatal(
            f"image_manifest media embed preflight failed "
            f"({len(media_errors)} error(s)); refusing to export"
        )
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
        xml, slide_media_uses = _slide_xml(
            rm, design, manifest_alts, manifest_paths, media_plan,
        )
    except ExportError as exc:
        return _fatal(f"{rm_path}: {exc}")
    output.parent.mkdir(parents=True, exist_ok=True)
    text_parts, binary_parts = _build_package_parts(
        [(rm, xml, slide_media_uses)], design, canvas_w, canvas_h,
        media_plan,
    )
    _write_pptx(output, text_parts, binary_parts)
    print(
        f"OK (single render_model): exported {rm_path} -> {output} "
        f"(one slide; {len(binary_parts)} embedded media asset(s)). "
        f"Workspace mode is the primary entry point."
    )
    return 0


def _write_synthetic_deck_plan(
    ws: Path,
    slides: list[tuple[int, str]],
) -> None:
    """Write a synthetic deck_plan.json under `ws` whose slides[]
    matches the supplied (index, layout) pairs. Used by the self-test
    fixtures so the deck_plan-driven enumeration in `export_workspace`
    has a 1:1 source of truth to gate against. Sections are aggregated
    under a single synthetic section so the schema's
    `sections[].slide_indices` requirement is satisfied without forcing
    callers to pick section ids."""
    import json
    indices = [idx for idx, _ in slides]
    plan = {
        "template": "synthetic",
        "planning": {
            "planned_slide_count": len(slides),
            "rationale": "synthetic self-test fixture",
        },
        "sections": [
            {
                "id": "all",
                "title": "All",
                "summary": "synthetic",
                "slide_indices": indices,
            },
        ],
        "slides": [
            {
                "index": idx,
                "layout": layout,
                "title": f"synthetic slide {idx}",
                "section_id": "all",
                "summary": "synthetic",
                "density": "low",
                "source_refs": ["synthetic_src"],
            }
            for idx, layout in slides
        ],
    }
    (ws / "deck_plan.json").write_text(json.dumps(plan, indent=2))


def _write_synthetic_workspace(ws: Path) -> None:
    """Build a deterministic happy-path workspace under `ws`. Used by
    the self-test fixtures. The render_models exercise the supported
    primitive kinds without needing any real images, so the manifest
    stays empty and no asset files are produced. The deck_plan declares
    slides 1 (cover) and 2 (kpi_dashboard) — callers that swap layouts
    must also rewrite the deck_plan via `_write_synthetic_deck_plan` so
    the deck_plan / render_models coverage gate stays consistent."""
    import json
    (ws / "render_models").mkdir(parents=True, exist_ok=True)
    _write_synthetic_deck_plan(ws, [(1, "cover"), (2, "kpi_dashboard")])
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
    # Cover slide: structural title divider + title text. Geometry
    # mirrors what scripts/generate_render_models.py emits today
    # against the business_review cover layout (title bound h=100;
    # subtitle / presenter / date / accent slots are optional and
    # omitted by this minimal fixture).
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
                "bounds": {"x": 160, "y": 320, "w": 1280, "h": 100},
                "style": {
                    "color_token": "palette.text",
                    "typography_token": "typography.heading",
                },
                "text": {"content": "Synthetic Cover", "role": "heading"},
            },
        ],
    }, indent=2))
    # kpi_dashboard slide: title + one rounded-rectangle "card" shape
    # per KPI tile + one `kpi` primitive layered on top of each card.
    # The fixture mirrors the new generator output: there is NO
    # single outer band shape; every tile carries its own card.
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
                "id": "kpi_card_01",
                "kind": "shape",
                "bounds": {"x": 96, "y": 300, "w": 858, "h": 160},
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
                "bounds": {"x": 96, "y": 300, "w": 858, "h": 160},
                "style": {"color_token": "palette.text"},
                "kpi": {"label": "alpha", "value": "<value>", "delta": "<delta>"},
            },
            {
                "id": "kpi_card_02",
                "kind": "shape",
                "bounds": {"x": 966, "y": 300, "w": 858, "h": 160},
                "style": {
                    "fill_token": "palette.background",
                    "stroke_token": "palette.primary",
                    "stroke_width_px": 2,
                },
                "shape": {"shape_kind": "rounded_rectangle", "corner_radius_px": 12},
            },
            {
                "id": "kpi_02",
                "slot_id": "kpis",
                "kind": "kpi",
                "bounds": {"x": 966, "y": 300, "w": 858, "h": 160},
                "style": {"color_token": "palette.text"},
                "kpi": {"label": "beta", "value": "<value>"},
            },
        ],
    }, indent=2))


_TINY_PNG_BYTES = bytes([
    # Minimal 1x1 transparent PNG. Hand-rolled (stdlib-only — no
    # `from PIL` dependency) and exercised in the media-embed self-test
    # scenarios below. Confirmed to start with the PNG magic
    # `\x89PNG\r\n\x1a\n` so `_matches_image_signature` accepts it.
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,             # signature
    0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,             # IHDR len + tag
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,             # 1x1
    0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4, 0x89,        # bit depth, color, ...
    0x00, 0x00, 0x00, 0x0A, 0x49, 0x44, 0x41, 0x54,             # IDAT len + tag
    0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00, 0x05, 0x00, 0x01, # zlib stream
    0x0D, 0x0A, 0x2D, 0xB4,                                     # IDAT crc
    0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44,             # IEND len + tag
    0xAE, 0x42, 0x60, 0x82,                                     # IEND crc
])

_TINY_JPEG_BYTES = bytes([
    # Minimal-shape JPEG buffer for the magic-byte gate exercises. The
    # file is intentionally not a complete decodeable JPEG — the embed
    # path inside this exporter only checks the 3-byte SOI / marker
    # prefix, so a 4-byte payload starting `FF D8 FF E0` is enough to
    # exercise the JPEG branch without pulling in a JPEG encoder.
    0xFF, 0xD8, 0xFF, 0xE0,
])


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
      - render_model containing a `chart_placeholder` primitive
        (unsupported);
      - render_model with a missing required field (no `primitives`);
      - image_slot whose image_ref is not declared in image_manifest;
      - image_manifest local_path with an unsafe URI scheme;
      - render_model with an unsupported layout (org_chart);
      - render_model on disk whose filename has been renamed away
        from `<idx:02d>_<layout>.json` (fixture exercises the
        deck_plan/render_models 1:1 coverage gate);
      - deck_plan declares N slides but one render_model is missing;
      - render_model on disk not declared by deck_plan (orphan);
      - deck_plan.planning.planned_slide_count != len(slides);
      - PNG manifest entry whose .png file is missing on disk;
      - PNG manifest entry whose magic bytes do not match the
        declared extension;
      - PNG manifest entry whose local_path is a symlink (refused).

    Media-embed positives:
      - PNG manifest entry: image_slot exports as a native
        `<p:pic>` referencing `ppt/media/image1.png`; the PNG bytes
        appear inside the package; the slide's rels file carries the
        `image` relationship type and an internal `../media/image1.png`
        Target;
      - JPG manifest entry: image_slot exports as a native `<p:pic>`
        referencing `ppt/media/image1.jpg`; the JPEG bytes appear
        inside the package; `[Content_Types].xml` registers
        `<Default Extension="jpg" ContentType="image/jpeg"/>`; the
        slide's rels file carries an internal `../media/image1.jpg`
        Target;
      - JPEG manifest entry (the `.jpeg` spelling): same as the JPG
        scenario but the on-disk media filename uses `.jpeg` and
        `[Content_Types].xml` registers
        `<Default Extension="jpeg" ContentType="image/jpeg"/>` so a
        regression that collapses `.jpeg` to `.jpg` (or vice versa)
        in the media filename is unmistakable;
      - SVG manifest entry: image_slot still falls back to the
        placeholder `<p:sp>` (the SVG branch remains TODO), and
        `ppt/media/` carries no entry."""
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

        # 3. POSITIVE: comparison_table workspace exports a native
        # editable PPTX table. Replaces the previous fail-closed
        # scenario for the `table` primitive — table is now in the
        # SUPPORTED_PRIMITIVE_KINDS allow-list and renders as an
        # <a:tbl> inside a <p:graphicFrame>. The fixture swaps the
        # happy-path kpi_dashboard slide for a comparison_table slide
        # carrying a title and a 2-col x 2-row table; the run must
        # succeed and the resulting PPTX must contain a graphicFrame
        # whose tbl has the expected number of <a:tr> rows.
        import xml.etree.ElementTree as _ET
        import zipfile as _zipfile
        table_ws = td / "with_table"
        _write_synthetic_workspace(table_ws)
        (table_ws / "render_models" / "02_kpi_dashboard.json").unlink()
        _write_synthetic_deck_plan(
            table_ws, [(1, "cover"), (2, "comparison_table")],
        )
        (table_ws / "render_models" / "02_comparison_table.json").write_text(
            json.dumps({
                "index": 2,
                "layout": "comparison_table",
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
                        "text": {"content": "Synthetic Comparison",
                                 "role": "heading"},
                    },
                    {
                        "id": "comparison_table",
                        "slot_id": "table",
                        "kind": "table",
                        "bounds": {"x": 64, "y": 240, "w": 1792, "h": 760},
                        "style": {"color_token": "palette.text"},
                        "table": {
                            "columns": ["metric", "before", "after"],
                            "rows": [
                                ["alpha", "<v1>", "<v2>"],
                                ["beta", "<v3>", "<v4>"],
                            ],
                        },
                    },
                ],
            })
        )
        table_out = td / "table.pptx"
        rc, _stdout, stderr = _run_capture(table_ws, table_out)
        table_in_slide = False
        cell_text_present = False
        if rc == 0 and table_out.is_file():
            with _zipfile.ZipFile(table_out) as _zf:
                slide_xml = _zf.read("ppt/slides/slide2.xml").decode("utf-8")
                table_in_slide = (
                    "<p:graphicFrame>" in slide_xml
                    and "<a:tbl>" in slide_xml
                    and slide_xml.count("<a:tr") == 3  # 1 header + 2 body
                    and slide_xml.count("<a:tc>") == 9  # 3 cols x 3 rows
                )
                cell_text_present = (
                    "Synthetic Comparison" in slide_xml
                    and "<a:t>metric</a:t>" in slide_xml
                    and "<a:t>alpha</a:t>" in slide_xml
                    and "<a:t>&lt;v4&gt;</a:t>" in slide_xml
                )
                # Defense-in-depth: every slide XML must still parse.
                for _name in _zf.namelist():
                    if _name.endswith(".xml") or _name.endswith(".rels"):
                        _ET.fromstring(_zf.read(_name))
        results.append(CheckResult(
            "selftest: comparison_table workspace exports a native "
            "<p:graphicFrame>/<a:tbl> with editable cell text",
            rc == 0 and table_in_slide and cell_text_present,
            (f"rc={rc}, table_in_slide={table_in_slide}, "
             f"cell_text_present={cell_text_present}; {stderr.strip()}"
             if not (rc == 0 and table_in_slide and cell_text_present) else ""),
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
        # slides; the contract is now all-or-nothing. The fixture
        # uses a synthetic `org_chart` layout name — every template-
        # declared layout in the business_review skeleton is now in
        # SUPPORTED_LAYOUTS, so the test must use a layout the
        # exporter has explicitly never been taught about to exercise
        # the gate. The render_model filename MUST be
        # `01_org_chart.json` (canonical-name gate fires first in the
        # exporter preflight) so this scenario actually exercises the
        # unsupported-layout gate rather than the filename gate.
        unsupp_ws = td / "unsupported_layout"
        _write_synthetic_workspace(unsupp_ws)
        (unsupp_ws / "render_models" / "01_cover.json").unlink()
        _write_synthetic_deck_plan(
            unsupp_ws, [(1, "org_chart"), (2, "kpi_dashboard")],
        )
        (unsupp_ws / "render_models" / "01_org_chart.json").write_text(
            json.dumps({
                "index": 1,
                "layout": "org_chart",
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
                        "text": {"content": "Org Chart", "role": "heading"},
                    },
                ],
            })
        )
        unsupp_out = td / "unsupported.pptx"
        rc, _stdout, stderr = _run_capture(unsupp_ws, unsupp_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: render_model with unsupported layout fails closed "
            "(no partial deck written)",
            (
                rc != 0
                and "org_chart" in msg
                and "supported set" in msg
                and not unsupp_out.exists()
            ),
            (f"rc={rc}, missing 'org_chart'/'supported set' in "
             f"messages, output_exists={unsupp_out.exists()}"
             if rc == 0
                or "org_chart" not in msg
                or "supported set" not in msg
                or unsupp_out.exists() else ""),
        ))

        # 10. POSITIVE: render_models using the newly allowed layouts
        # (agenda, section_divider, executive_summary, key_message,
        # two_column, timeline, conclusion) export successfully using
        # only the supported primitive kinds. The slide body emitter
        # is layout-agnostic, so this is structurally a regression
        # check that the layout allow-list widened correctly without
        # changing per-primitive emission. The fixture builds a
        # workspace where slide 01_cover stays as the existing cover
        # (so the workspace still has its happy-path baseline) and
        # adds a 02_two_column slide using a title + two list-derived
        # text primitives. The exporter must succeed and the
        # validator must accept the output under container +
        # minimal-evidence + allow-list gates.
        expanded_ws = td / "expanded_layouts"
        _write_synthetic_workspace(expanded_ws)
        (expanded_ws / "render_models" / "02_kpi_dashboard.json").unlink()
        _write_synthetic_deck_plan(
            expanded_ws, [(1, "cover"), (2, "two_column")],
        )
        (expanded_ws / "render_models" / "02_two_column.json").write_text(
            json.dumps({
                "index": 2,
                "layout": "two_column",
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
                        "text": {"content": "Synthetic Pairing",
                                 "role": "heading"},
                    },
                    {
                        "id": "left_heading",
                        "slot_id": "left_heading",
                        "kind": "text",
                        "bounds": {"x": 64, "y": 240, "w": 880, "h": 80},
                        "style": {
                            "color_token": "palette.text",
                            "typography_token": "typography.body",
                        },
                        "text": {"content": "Left", "role": "subheading"},
                    },
                    {
                        "id": "left_body",
                        "slot_id": "left_content",
                        "kind": "text",
                        "bounds": {"x": 64, "y": 340, "w": 880, "h": 600},
                        "style": {
                            "color_token": "palette.text",
                            "typography_token": "typography.body",
                        },
                        "text": {"content": "<left placeholder>",
                                 "role": "body"},
                    },
                    {
                        "id": "right_heading",
                        "slot_id": "right_heading",
                        "kind": "text",
                        "bounds": {"x": 976, "y": 240, "w": 880, "h": 80},
                        "style": {
                            "color_token": "palette.text",
                            "typography_token": "typography.body",
                        },
                        "text": {"content": "Right", "role": "subheading"},
                    },
                    {
                        "id": "right_body",
                        "slot_id": "right_content",
                        "kind": "text",
                        "bounds": {"x": 976, "y": 340, "w": 880, "h": 600},
                        "style": {
                            "color_token": "palette.text",
                            "typography_token": "typography.body",
                        },
                        "text": {"content": "<right placeholder>",
                                 "role": "body"},
                    },
                ],
            }, indent=2)
        )
        expanded_out = td / "expanded.pptx"
        rc, _stdout, stderr = _run_capture(expanded_ws, expanded_out)
        ok_expanded = rc == 0 and expanded_out.is_file()
        results.append(CheckResult(
            "selftest: expanded-layout workspace (cover + two_column) "
            "exports successfully",
            ok_expanded,
            stderr.strip() if not ok_expanded else "",
        ))
        if ok_expanded:
            c_res = check_container(expanded_out)
            g_res = check_generated_pptx(expanded_out)
            all_ok = all(r.ok for r in c_res) and all(r.ok for r in g_res)
            results.append(CheckResult(
                "selftest: expanded-layout PPTX passes validate_pptx_contract "
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
                "selftest: expanded-layout PPTX passes validate_pptx_contract "
                "container + minimal-evidence checks",
                False,
                "skipped — export failed",
            ))

        # 11. NEGATIVE: render_model whose on-disk filename does not
        # match `<index:02d>_<layout>.json` fails closed before any
        # output is written. The deck_plan/render_models 1:1 coverage
        # gate fires first (the renamed `99_cover.json` is orphan;
        # `01_cover.json` is missing), so the exporter aborts with a
        # FAIL line for each filename. The earlier in-loop
        # canonical-filename gate is still in place as defense in
        # depth for any case the coverage gate cannot catch (a JSON
        # whose declared index/layout disagrees with the filename
        # deck_plan named).
        mis_named_ws = td / "mis_named_filename"
        _write_synthetic_workspace(mis_named_ws)
        (mis_named_ws / "render_models" / "01_cover.json").rename(
            mis_named_ws / "render_models" / "99_cover.json",
        )
        mis_named_out = td / "mis_named.pptx"
        rc, _stdout, stderr = _run_capture(mis_named_ws, mis_named_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: render_model whose filename disagrees with its "
            "own index + layout fails closed in the exporter preflight "
            "(no partial deck written)",
            (
                rc != 0
                and "99_cover.json" in msg
                and "01_cover.json" in msg
                and not mis_named_out.exists()
            ),
            (f"rc={rc}, missing '99_cover.json'/'01_cover.json' in "
             f"messages, output_exists={mis_named_out.exists()}"
             if rc == 0
                or "99_cover.json" not in msg
                or "01_cover.json" not in msg
                or mis_named_out.exists() else ""),
        ))

        # 12. NEGATIVE: deck_plan declares 2 slides but one
        # render_model file is missing on disk. Codex review flagged
        # that the previous workspace-mode happily globbed
        # render_models/*.json and exported only the files present —
        # so a 20-slide deck_plan missing one render_model would yield
        # a 19-slide `.pptx` and exit 0. The fixture builds the happy
        # workspace (2 deck_plan slides + 2 render_models), deletes
        # `02_kpi_dashboard.json`, runs the exporter, and asserts that
        # the run aborts naming the missing file and that no `.pptx`
        # is written.
        miss_rm_ws = td / "missing_render_model"
        _write_synthetic_workspace(miss_rm_ws)
        (miss_rm_ws / "render_models" / "02_kpi_dashboard.json").unlink()
        miss_rm_out = td / "missing_rm.pptx"
        rc, _stdout, stderr = _run_capture(miss_rm_ws, miss_rm_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: deck_plan declares 2 slides but one render_model "
            "is missing fails closed (no partial deck written)",
            (
                rc != 0
                and "02_kpi_dashboard.json" in msg
                and "missing" in msg.lower()
                and not miss_rm_out.exists()
            ),
            (f"rc={rc}, missing '02_kpi_dashboard.json'/'missing' in "
             f"messages, output_exists={miss_rm_out.exists()}"
             if rc == 0
                or "02_kpi_dashboard.json" not in msg
                or "missing" not in msg.lower()
                or miss_rm_out.exists() else ""),
        ))

        # 13. NEGATIVE: an orphan render_model (on disk but not
        # declared by deck_plan.slides[]) fails closed. The happy
        # workspace declares slides 1 + 2 in deck_plan; the fixture
        # drops a third file `03_orphan.json` under render_models/.
        # The exporter must refuse to export rather than silently
        # ignoring or including the orphan.
        orphan_ws = td / "orphan_render_model"
        _write_synthetic_workspace(orphan_ws)
        (orphan_ws / "render_models" / "03_orphan.json").write_text(
            json.dumps({
                "index": 3,
                "layout": "cover",
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
                        "text": {"content": "stray", "role": "heading"},
                    },
                ],
            })
        )
        orphan_out = td / "orphan.pptx"
        rc, _stdout, stderr = _run_capture(orphan_ws, orphan_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: orphan render_model not declared by deck_plan "
            "fails closed (no partial deck written)",
            (
                rc != 0
                and "03_orphan.json" in msg
                and "orphan" in msg.lower()
                and not orphan_out.exists()
            ),
            (f"rc={rc}, missing '03_orphan.json'/'orphan' in messages, "
             f"output_exists={orphan_out.exists()}"
             if rc == 0
                or "03_orphan.json" not in msg
                or "orphan" not in msg.lower()
                or orphan_out.exists() else ""),
        ))

        # 14. NEGATIVE: deck_plan.planning.planned_slide_count
        # disagrees with len(slides). The render_models on disk match
        # slides[], but the planning record is internally inconsistent
        # — the exporter must refuse the deck_plan rather than trust
        # one field over the other.
        bad_plan_ws = td / "bad_plan_count"
        _write_synthetic_workspace(bad_plan_ws)
        plan_path = bad_plan_ws / "deck_plan.json"
        plan_obj = json.loads(plan_path.read_text())
        plan_obj["planning"]["planned_slide_count"] = 99
        plan_path.write_text(json.dumps(plan_obj, indent=2))
        bad_plan_out = td / "bad_plan.pptx"
        rc, _stdout, stderr = _run_capture(bad_plan_ws, bad_plan_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: deck_plan.planned_slide_count != len(slides) "
            "fails closed",
            (
                rc != 0
                and "planned_slide_count" in msg
                and not bad_plan_out.exists()
            ),
            (f"rc={rc}, missing 'planned_slide_count' in messages, "
             f"output_exists={bad_plan_out.exists()}"
             if rc == 0
                or "planned_slide_count" not in msg
                or bad_plan_out.exists() else ""),
        ))

        # 15. POSITIVE: PNG manifest entry exports as embedded
        # <p:pic> + ppt/media/image1.png. The fixture is a standard
        # happy-path workspace plus a tiny on-disk PNG and an
        # image_manifest entry pointing at it; the cover render_model
        # gains an image_slot referencing the new entry. The exporter
        # must:
        #   - copy the PNG bytes into ppt/media/image1.png;
        #   - register `<Default Extension="png" ContentType="image/png"/>`
        #     in [Content_Types].xml;
        #   - emit `<p:pic>` (NOT the placeholder `[image: ...]` text)
        #     inside slide1.xml referencing the rId of the image rel;
        #   - emit a per-slide rels file with the matching `image`
        #     relationship type and an internal Target
        #     `../media/image1.png` (no TargetMode="External", no
        #     URI scheme).
        png_ws = td / "png_embed"
        _write_synthetic_workspace(png_ws)
        (png_ws / "assets").mkdir(exist_ok=True)
        (png_ws / "assets" / "tiny.png").write_bytes(_TINY_PNG_BYTES)
        (png_ws / "image_manifest.json").write_text(json.dumps({
            "images": [
                {
                    "id": "tiny",
                    "local_path": "assets/tiny.png",
                    "source": "synthetic",
                    "alt_text": "Tiny synthetic PNG fixture.",
                    "intended_use": "icon",
                    "width_px": 1,
                    "height_px": 1,
                },
            ],
        }, indent=2))
        # Replace 01_cover with one carrying an image_slot.
        (png_ws / "render_models" / "01_cover.json").write_text(json.dumps({
            "index": 1,
            "layout": "cover",
            "canvas": {"width_px": 1920, "height_px": 1080},
            "source_refs": ["synthetic_src"],
            "primitives": [
                {
                    "id": "title",
                    "slot_id": "title",
                    "kind": "text",
                    "bounds": {"x": 160, "y": 320, "w": 1280, "h": 100},
                    "style": {
                        "color_token": "palette.text",
                        "typography_token": "typography.heading",
                    },
                    "text": {"content": "PNG Embed", "role": "heading"},
                },
                {
                    "id": "tiny_image",
                    "kind": "image_slot",
                    "bounds": {"x": 100, "y": 600, "w": 200, "h": 200},
                    "image_slot": {"image_ref": "tiny",
                                   "alt_text": "tiny PNG"},
                },
            ],
        }))
        png_out = td / "png.pptx"
        rc, _stdout, stderr = _run_capture(png_ws, png_out)
        png_embedded = False
        png_pic_in_slide = False
        png_default_ct = False
        png_image_rel_internal = False
        no_placeholder_text = False
        if rc == 0 and png_out.is_file():
            with _zipfile.ZipFile(png_out) as _zf:
                names = _zf.namelist()
                png_embedded = "ppt/media/image1.png" in names
                # PNG bytes round-trip verbatim
                if png_embedded:
                    png_embedded = (
                        _zf.read("ppt/media/image1.png") == _TINY_PNG_BYTES
                    )
                slide_xml = _zf.read("ppt/slides/slide1.xml").decode("utf-8")
                png_pic_in_slide = (
                    "<p:pic>" in slide_xml
                    and 'r:embed="rId2"' in slide_xml
                )
                no_placeholder_text = "[image: tiny PNG]" not in slide_xml
                ct_xml = _zf.read("[Content_Types].xml").decode("utf-8")
                png_default_ct = (
                    '<Default Extension="png" ContentType="image/png"/>' in ct_xml
                )
                rels_xml = _zf.read(
                    "ppt/slides/_rels/slide1.xml.rels"
                ).decode("utf-8")
                png_image_rel_internal = (
                    "/relationships/image" in rels_xml
                    and "../media/image1.png" in rels_xml
                    and "TargetMode" not in rels_xml
                    and "file://" not in rels_xml
                )
        results.append(CheckResult(
            "selftest: PNG manifest entry exports as embedded "
            "<p:pic> + ppt/media/image1.png + image relationship",
            (
                rc == 0
                and png_embedded
                and png_pic_in_slide
                and png_default_ct
                and png_image_rel_internal
                and no_placeholder_text
            ),
            (f"rc={rc}, png_embedded={png_embedded}, "
             f"png_pic_in_slide={png_pic_in_slide}, "
             f"png_default_ct={png_default_ct}, "
             f"png_image_rel_internal={png_image_rel_internal}, "
             f"no_placeholder_text={no_placeholder_text}; "
             f"{stderr.strip()}"
             if not (
                rc == 0
                and png_embedded
                and png_pic_in_slide
                and png_default_ct
                and png_image_rel_internal
                and no_placeholder_text
             ) else ""),
        ))

        # 16. POSITIVE: SVG manifest entry stays a placeholder.
        # Even with the PNG embed branch in place, an SVG manifest
        # entry must still produce the placeholder `<p:sp>` (alt-text
        # carrying) shape — there is no SVG embed in this slice. The
        # package therefore carries NO `ppt/media/` entries.
        svg_ws = td / "svg_placeholder"
        _write_synthetic_workspace(svg_ws)
        (svg_ws / "assets").mkdir(exist_ok=True)
        (svg_ws / "assets" / "icon.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 16 16"><rect width="16" height="16"/></svg>'
        )
        (svg_ws / "image_manifest.json").write_text(json.dumps({
            "images": [
                {
                    "id": "icon",
                    "local_path": "assets/icon.svg",
                    "source": "synthetic",
                    "alt_text": "Tiny synthetic SVG.",
                    "intended_use": "icon",
                    "width_px": 16,
                    "height_px": 16,
                },
            ],
        }, indent=2))
        (svg_ws / "render_models" / "01_cover.json").write_text(json.dumps({
            "index": 1,
            "layout": "cover",
            "canvas": {"width_px": 1920, "height_px": 1080},
            "source_refs": ["synthetic_src"],
            "primitives": [
                {
                    "id": "title",
                    "slot_id": "title",
                    "kind": "text",
                    "bounds": {"x": 160, "y": 320, "w": 1280, "h": 100},
                    "style": {
                        "color_token": "palette.text",
                        "typography_token": "typography.heading",
                    },
                    "text": {"content": "SVG fallback", "role": "heading"},
                },
                {
                    "id": "icon_image",
                    "kind": "image_slot",
                    "bounds": {"x": 100, "y": 600, "w": 200, "h": 200},
                    "image_slot": {"image_ref": "icon",
                                   "alt_text": "icon SVG"},
                },
            ],
        }))
        svg_out = td / "svg.pptx"
        rc, _stdout, stderr = _run_capture(svg_ws, svg_out)
        no_media_dir = False
        placeholder_in_slide = False
        no_pic_in_slide = False
        if rc == 0 and svg_out.is_file():
            with _zipfile.ZipFile(svg_out) as _zf:
                names = _zf.namelist()
                no_media_dir = not any(
                    n.startswith("ppt/media/") for n in names
                )
                slide_xml = _zf.read("ppt/slides/slide1.xml").decode("utf-8")
                placeholder_in_slide = "[image: icon SVG]" in slide_xml
                no_pic_in_slide = "<p:pic>" not in slide_xml
        results.append(CheckResult(
            "selftest: SVG manifest entry falls back to the "
            "placeholder <p:sp> (no ppt/media/ entry, no <p:pic>)",
            (
                rc == 0
                and no_media_dir
                and placeholder_in_slide
                and no_pic_in_slide
            ),
            (f"rc={rc}, no_media_dir={no_media_dir}, "
             f"placeholder_in_slide={placeholder_in_slide}, "
             f"no_pic_in_slide={no_pic_in_slide}; {stderr.strip()}"
             if not (
                rc == 0
                and no_media_dir
                and placeholder_in_slide
                and no_pic_in_slide
             ) else ""),
        ))

        # 17. NEGATIVE: PNG manifest entry whose .png file is missing
        # on disk fails closed at the embed preflight before any PPTX
        # is written. This is the "manifest declares an image, but the
        # asset never landed in the workspace" case — `_build_media_plan`
        # must refuse it (regular-file gate) rather than silently
        # demoting to placeholder; placeholder-only fallback is reserved
        # for non-embeddable extensions.
        miss_png_ws = td / "missing_png"
        _write_synthetic_workspace(miss_png_ws)
        (miss_png_ws / "image_manifest.json").write_text(json.dumps({
            "images": [
                {
                    "id": "ghost",
                    "local_path": "assets/missing.png",
                    "source": "synthetic",
                    "alt_text": "Asset never written to disk.",
                    "intended_use": "icon",
                    "width_px": 1,
                    "height_px": 1,
                },
            ],
        }, indent=2))
        miss_png_out = td / "missing_png.pptx"
        rc, _stdout, stderr = _run_capture(miss_png_ws, miss_png_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: PNG manifest entry whose file is missing on disk "
            "fails closed at media preflight",
            (
                rc != 0
                and "missing.png" in msg
                and "regular file" in msg
                and not miss_png_out.exists()
            ),
            (f"rc={rc}, missing 'missing.png'/'regular file' in messages, "
             f"output_exists={miss_png_out.exists()}; {stderr.strip()}"
             if rc == 0
                or "missing.png" not in msg
                or "regular file" not in msg
                or miss_png_out.exists() else ""),
        ))

        # 18. NEGATIVE: PNG manifest entry whose magic bytes do not
        # match the declared extension fails closed. This catches the
        # "rename a text file `.png` to sneak it past the extension
        # gate" attack.
        bad_magic_ws = td / "bad_magic_png"
        _write_synthetic_workspace(bad_magic_ws)
        (bad_magic_ws / "assets").mkdir(exist_ok=True)
        (bad_magic_ws / "assets" / "fake.png").write_text(
            "this is not a PNG"
        )
        (bad_magic_ws / "image_manifest.json").write_text(json.dumps({
            "images": [
                {
                    "id": "fake",
                    "local_path": "assets/fake.png",
                    "source": "synthetic",
                    "alt_text": "Not actually a PNG.",
                    "intended_use": "icon",
                    "width_px": 1,
                    "height_px": 1,
                },
            ],
        }, indent=2))
        bad_magic_out = td / "bad_magic.pptx"
        rc, _stdout, stderr = _run_capture(bad_magic_ws, bad_magic_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: PNG manifest entry whose magic bytes mismatch "
            "fails closed at media preflight",
            (
                rc != 0
                and "fake.png" in msg
                and "magic bytes" in msg
                and not bad_magic_out.exists()
            ),
            (f"rc={rc}, missing 'fake.png'/'magic bytes' in messages, "
             f"output_exists={bad_magic_out.exists()}; {stderr.strip()}"
             if rc == 0
                or "fake.png" not in msg
                or "magic bytes" not in msg
                or bad_magic_out.exists() else ""),
        ))

        # 19. NEGATIVE: PNG manifest entry whose local_path is a
        # symlink fails closed. Mirrors the symlink gate the workspace
        # validator already enforces on source_manifest.json. Without
        # this gate, an attacker could redirect the embedded bytes to
        # a file outside the workspace.
        sym_ws = td / "symlink_png"
        _write_synthetic_workspace(sym_ws)
        (sym_ws / "assets").mkdir(exist_ok=True)
        # Real PNG sits OUTSIDE the workspace; the symlink inside the
        # workspace would otherwise let the exporter follow it and
        # embed the external bytes.
        outside_png = td / "outside.png"
        outside_png.write_bytes(_TINY_PNG_BYTES)
        try:
            (sym_ws / "assets" / "linked.png").symlink_to(outside_png)
            symlink_supported = True
        except (OSError, NotImplementedError):
            # Some platforms (Windows non-admin) refuse symlinks; skip
            # the negative entirely so the suite still passes there.
            symlink_supported = False
        if symlink_supported:
            (sym_ws / "image_manifest.json").write_text(json.dumps({
                "images": [
                    {
                        "id": "linked",
                        "local_path": "assets/linked.png",
                        "source": "synthetic",
                        "alt_text": "Symlink to a PNG.",
                        "intended_use": "icon",
                        "width_px": 1,
                        "height_px": 1,
                    },
                ],
            }, indent=2))
            sym_out = td / "symlink.pptx"
            rc, _stdout, stderr = _run_capture(sym_ws, sym_out)
            msg = stderr + _stdout
            results.append(CheckResult(
                "selftest: PNG manifest entry whose local_path is a "
                "symlink fails closed at media preflight",
                (
                    rc != 0
                    and "linked.png" in msg
                    and "symlink" in msg
                    and not sym_out.exists()
                ),
                (f"rc={rc}, missing 'linked.png'/'symlink' in messages, "
                 f"output_exists={sym_out.exists()}; {stderr.strip()}"
                 if rc == 0
                    or "linked.png" not in msg
                    or "symlink" not in msg
                    or sym_out.exists() else ""),
            ))
        else:
            results.append(CheckResult(
                "selftest: PNG manifest entry whose local_path is a "
                "symlink fails closed at media preflight",
                True,
                "skipped — platform refused symlink creation",
            ))

        # 20. POSITIVE: JPG manifest entry exports as embedded
        # <p:pic> + ppt/media/image1.jpg. Same shape as the PNG
        # positive (#15), but exercises the second EMBEDDABLE_IMAGE_-
        # EXTENSIONS row: extension `jpg` -> ContentType image/jpeg
        # and a JPEG magic-byte signature. Without this scenario the
        # JPG branch would only be exercised by the negative magic-
        # byte test, which would let a regression in the JPG embed
        # path (e.g. wrong ContentType, wrong target extension) ship
        # silently.
        jpg_ws = td / "jpg_embed"
        _write_synthetic_workspace(jpg_ws)
        (jpg_ws / "assets").mkdir(exist_ok=True)
        (jpg_ws / "assets" / "tiny.jpg").write_bytes(_TINY_JPEG_BYTES)
        (jpg_ws / "image_manifest.json").write_text(json.dumps({
            "images": [
                {
                    "id": "tiny_jpg",
                    "local_path": "assets/tiny.jpg",
                    "source": "synthetic",
                    "alt_text": "Tiny synthetic JPG fixture.",
                    "intended_use": "icon",
                    "width_px": 1,
                    "height_px": 1,
                },
            ],
        }, indent=2))
        (jpg_ws / "render_models" / "01_cover.json").write_text(json.dumps({
            "index": 1,
            "layout": "cover",
            "canvas": {"width_px": 1920, "height_px": 1080},
            "source_refs": ["synthetic_src"],
            "primitives": [
                {
                    "id": "title",
                    "slot_id": "title",
                    "kind": "text",
                    "bounds": {"x": 160, "y": 320, "w": 1280, "h": 100},
                    "style": {
                        "color_token": "palette.text",
                        "typography_token": "typography.heading",
                    },
                    "text": {"content": "JPG Embed", "role": "heading"},
                },
                {
                    "id": "tiny_jpg_image",
                    "kind": "image_slot",
                    "bounds": {"x": 100, "y": 600, "w": 200, "h": 200},
                    "image_slot": {"image_ref": "tiny_jpg",
                                   "alt_text": "tiny JPG"},
                },
            ],
        }))
        jpg_out = td / "jpg.pptx"
        rc, _stdout, stderr = _run_capture(jpg_ws, jpg_out)
        jpg_embedded = False
        jpg_pic_in_slide = False
        jpg_default_ct = False
        jpg_image_rel_internal = False
        no_jpg_placeholder_text = False
        if rc == 0 and jpg_out.is_file():
            with _zipfile.ZipFile(jpg_out) as _zf:
                names = _zf.namelist()
                jpg_embedded = "ppt/media/image1.jpg" in names
                if jpg_embedded:
                    jpg_embedded = (
                        _zf.read("ppt/media/image1.jpg") == _TINY_JPEG_BYTES
                    )
                slide_xml = _zf.read("ppt/slides/slide1.xml").decode("utf-8")
                jpg_pic_in_slide = (
                    "<p:pic>" in slide_xml
                    and 'r:embed="rId2"' in slide_xml
                )
                no_jpg_placeholder_text = "[image: tiny JPG]" not in slide_xml
                ct_xml = _zf.read("[Content_Types].xml").decode("utf-8")
                jpg_default_ct = (
                    '<Default Extension="jpg" ContentType="image/jpeg"/>'
                    in ct_xml
                )
                rels_xml = _zf.read(
                    "ppt/slides/_rels/slide1.xml.rels"
                ).decode("utf-8")
                jpg_image_rel_internal = (
                    "/relationships/image" in rels_xml
                    and "../media/image1.jpg" in rels_xml
                    and "TargetMode" not in rels_xml
                    and "file://" not in rels_xml
                )
        results.append(CheckResult(
            "selftest: JPG manifest entry exports as embedded "
            "<p:pic> + ppt/media/image1.jpg + image relationship",
            (
                rc == 0
                and jpg_embedded
                and jpg_pic_in_slide
                and jpg_default_ct
                and jpg_image_rel_internal
                and no_jpg_placeholder_text
            ),
            (f"rc={rc}, jpg_embedded={jpg_embedded}, "
             f"jpg_pic_in_slide={jpg_pic_in_slide}, "
             f"jpg_default_ct={jpg_default_ct}, "
             f"jpg_image_rel_internal={jpg_image_rel_internal}, "
             f"no_jpg_placeholder_text={no_jpg_placeholder_text}; "
             f"{stderr.strip()}"
             if not (
                rc == 0
                and jpg_embedded
                and jpg_pic_in_slide
                and jpg_default_ct
                and jpg_image_rel_internal
                and no_jpg_placeholder_text
             ) else ""),
        ))

        # 21. POSITIVE: JPEG manifest entry (the `.jpeg` spelling)
        # exports as embedded <p:pic> + ppt/media/image1.jpeg. Same
        # shape as #20 but covers the THIRD EMBEDDABLE_IMAGE_EXTEN-
        # SIONS row: extension `jpeg` (5-char spelling) ALSO maps to
        # ContentType image/jpeg, but the on-disk media filename uses
        # `.jpeg` (not `.jpg`) so the deterministic media name follows
        # the manifest's declared extension. Without this scenario a
        # regression that collapses `.jpeg` to `.jpg` (or vice versa)
        # in the media filename would not be caught by #15 or #20.
        jpeg_ws = td / "jpeg_embed"
        _write_synthetic_workspace(jpeg_ws)
        (jpeg_ws / "assets").mkdir(exist_ok=True)
        (jpeg_ws / "assets" / "tiny.jpeg").write_bytes(_TINY_JPEG_BYTES)
        (jpeg_ws / "image_manifest.json").write_text(json.dumps({
            "images": [
                {
                    "id": "tiny_jpeg",
                    "local_path": "assets/tiny.jpeg",
                    "source": "synthetic",
                    "alt_text": "Tiny synthetic JPEG fixture.",
                    "intended_use": "icon",
                    "width_px": 1,
                    "height_px": 1,
                },
            ],
        }, indent=2))
        (jpeg_ws / "render_models" / "01_cover.json").write_text(json.dumps({
            "index": 1,
            "layout": "cover",
            "canvas": {"width_px": 1920, "height_px": 1080},
            "source_refs": ["synthetic_src"],
            "primitives": [
                {
                    "id": "title",
                    "slot_id": "title",
                    "kind": "text",
                    "bounds": {"x": 160, "y": 320, "w": 1280, "h": 100},
                    "style": {
                        "color_token": "palette.text",
                        "typography_token": "typography.heading",
                    },
                    "text": {"content": "JPEG Embed", "role": "heading"},
                },
                {
                    "id": "tiny_jpeg_image",
                    "kind": "image_slot",
                    "bounds": {"x": 100, "y": 600, "w": 200, "h": 200},
                    "image_slot": {"image_ref": "tiny_jpeg",
                                   "alt_text": "tiny JPEG"},
                },
            ],
        }))
        jpeg_out = td / "jpeg.pptx"
        rc, _stdout, stderr = _run_capture(jpeg_ws, jpeg_out)
        jpeg_embedded = False
        jpeg_pic_in_slide = False
        jpeg_default_ct = False
        jpeg_image_rel_internal = False
        no_jpeg_placeholder_text = False
        if rc == 0 and jpeg_out.is_file():
            with _zipfile.ZipFile(jpeg_out) as _zf:
                names = _zf.namelist()
                jpeg_embedded = "ppt/media/image1.jpeg" in names
                if jpeg_embedded:
                    jpeg_embedded = (
                        _zf.read("ppt/media/image1.jpeg") == _TINY_JPEG_BYTES
                    )
                slide_xml = _zf.read("ppt/slides/slide1.xml").decode("utf-8")
                jpeg_pic_in_slide = (
                    "<p:pic>" in slide_xml
                    and 'r:embed="rId2"' in slide_xml
                )
                no_jpeg_placeholder_text = (
                    "[image: tiny JPEG]" not in slide_xml
                )
                ct_xml = _zf.read("[Content_Types].xml").decode("utf-8")
                jpeg_default_ct = (
                    '<Default Extension="jpeg" ContentType="image/jpeg"/>'
                    in ct_xml
                )
                rels_xml = _zf.read(
                    "ppt/slides/_rels/slide1.xml.rels"
                ).decode("utf-8")
                jpeg_image_rel_internal = (
                    "/relationships/image" in rels_xml
                    and "../media/image1.jpeg" in rels_xml
                    and "TargetMode" not in rels_xml
                    and "file://" not in rels_xml
                )
        results.append(CheckResult(
            "selftest: JPEG manifest entry exports as embedded "
            "<p:pic> + ppt/media/image1.jpeg + image relationship",
            (
                rc == 0
                and jpeg_embedded
                and jpeg_pic_in_slide
                and jpeg_default_ct
                and jpeg_image_rel_internal
                and no_jpeg_placeholder_text
            ),
            (f"rc={rc}, jpeg_embedded={jpeg_embedded}, "
             f"jpeg_pic_in_slide={jpeg_pic_in_slide}, "
             f"jpeg_default_ct={jpeg_default_ct}, "
             f"jpeg_image_rel_internal={jpeg_image_rel_internal}, "
             f"no_jpeg_placeholder_text={no_jpeg_placeholder_text}; "
             f"{stderr.strip()}"
             if not (
                rc == 0
                and jpeg_embedded
                and jpeg_pic_in_slide
                and jpeg_default_ct
                and jpeg_image_rel_internal
                and no_jpeg_placeholder_text
             ) else ""),
        ))

        # 22. NEGATIVE: a primitive carrying a forbidden
        # `rotation` key fails closed at schema validation. The
        # render_model contract is intentionally bounds-only —
        # primitives have {id, slot_id, kind, bounds, style, ...
        # kind-payload} under `additionalProperties: false`, so
        # group-rotation / pivot fields are NOT representable.
        # Clean-room cross-check: if the schema ever drifts to
        # accept rotation-style keys, this probe fires before a
        # bounds-vs-pivot double-application can manifest in an
        # exported deck.
        rotated_ws = td / "forbidden_rotation"
        _write_synthetic_workspace(rotated_ws)
        rotated_path = rotated_ws / "render_models" / "01_cover.json"
        rotated_obj = json.loads(rotated_path.read_text())
        rotated_obj["primitives"][1]["rotation"] = 45
        rotated_path.write_text(json.dumps(rotated_obj, indent=2))
        rotated_out = td / "rotated.pptx"
        rc, _stdout, stderr = _run_capture(rotated_ws, rotated_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: primitive with forbidden `rotation` key "
            "fails closed at schema (group rotation/pivot is not "
            "representable in the current render model)",
            (
                rc != 0
                and "rotation" in msg
                and "schema" in msg.lower()
                and not rotated_out.exists()
            ),
            (f"rc={rc}, missing 'rotation'/'schema' in messages, "
             f"output_exists={rotated_out.exists()}; {stderr.strip()}"
             if rc == 0
                or "rotation" not in msg
                or "schema" not in msg.lower()
                or rotated_out.exists() else ""),
        ))

        # 23. NEGATIVE: an image_slot carrying a forbidden
        # `transform` key fails closed at schema validation.
        # image_slot's properties are `image_ref` + `alt_text`
        # under `additionalProperties: false`, so no transform /
        # matrix / crop / clip_path key can sneak through. This
        # is the contract-layer guarantee that the bounds-to-EMU
        # map (`_bounds_to_xfrm`) is the ONLY spatial transform
        # applied to an image — there is no upstream `transform`
        # field for a downstream stage to double-apply.
        bad_xform_ws = td / "forbidden_image_transform"
        _write_synthetic_workspace(bad_xform_ws)
        (bad_xform_ws / "assets").mkdir(exist_ok=True)
        (bad_xform_ws / "assets" / "tiny.png").write_bytes(_TINY_PNG_BYTES)
        (bad_xform_ws / "image_manifest.json").write_text(json.dumps({
            "images": [
                {
                    "id": "tiny",
                    "local_path": "assets/tiny.png",
                    "source": "synthetic",
                    "alt_text": "Tiny synthetic PNG fixture.",
                    "intended_use": "icon",
                    "width_px": 1,
                    "height_px": 1,
                },
            ],
        }, indent=2))
        (bad_xform_ws / "render_models" / "01_cover.json").write_text(json.dumps({
            "index": 1,
            "layout": "cover",
            "canvas": {"width_px": 1920, "height_px": 1080},
            "source_refs": ["synthetic_src"],
            "primitives": [
                {
                    "id": "title",
                    "slot_id": "title",
                    "kind": "text",
                    "bounds": {"x": 160, "y": 320, "w": 1280, "h": 100},
                    "style": {
                        "color_token": "palette.text",
                        "typography_token": "typography.heading",
                    },
                    "text": {"content": "transformed", "role": "heading"},
                },
                {
                    "id": "ill_image",
                    "kind": "image_slot",
                    "bounds": {"x": 100, "y": 600, "w": 200, "h": 200},
                    "image_slot": {
                        "image_ref": "tiny",
                        "alt_text": "doubled",
                        "transform": "rotate(45)",
                    },
                },
            ],
        }))
        bad_xform_out = td / "bad_xform.pptx"
        rc, _stdout, stderr = _run_capture(bad_xform_ws, bad_xform_out)
        msg = stderr + _stdout
        results.append(CheckResult(
            "selftest: image_slot with forbidden `transform` key "
            "fails closed at schema (image transform is not "
            "representable, so cannot be double-applied)",
            (
                rc != 0
                and "transform" in msg
                and "schema" in msg.lower()
                and not bad_xform_out.exists()
            ),
            (f"rc={rc}, missing 'transform'/'schema' in messages, "
             f"output_exists={bad_xform_out.exists()}; {stderr.strip()}"
             if rc == 0
                or "transform" not in msg
                or "schema" not in msg.lower()
                or bad_xform_out.exists() else ""),
        ))

        # 24. POSITIVE: a full-bleed image_slot (bounds == canvas
        # dimensions) exports with a single <p:pic> whose
        # <a:off>/<a:ext> map 1:1 from the canvas px to EMU and
        # carries no <a:srcRect> (no clip artifact). This is the
        # runtime-layer cross-check on the "no-op rectangular
        # clip / fit" surface: the only spatial transform on the
        # picture is the bounds-to-EMU multiplication, so a
        # regression that double-multiplies (or invents a clip
        # rect on a full-bleed slot) would be caught by the
        # exact-EMU + srcRect-absent assertions below.
        full_bleed_ws = td / "full_bleed_image"
        _write_synthetic_workspace(full_bleed_ws)
        (full_bleed_ws / "assets").mkdir(exist_ok=True)
        (full_bleed_ws / "assets" / "tiny.png").write_bytes(_TINY_PNG_BYTES)
        (full_bleed_ws / "image_manifest.json").write_text(json.dumps({
            "images": [
                {
                    "id": "tiny",
                    "local_path": "assets/tiny.png",
                    "source": "synthetic",
                    "alt_text": "Tiny synthetic PNG fixture.",
                    "intended_use": "icon",
                    "width_px": 1,
                    "height_px": 1,
                },
            ],
        }, indent=2))
        (full_bleed_ws / "render_models" / "01_cover.json").write_text(json.dumps({
            "index": 1,
            "layout": "cover",
            "canvas": {"width_px": 1920, "height_px": 1080},
            "source_refs": ["synthetic_src"],
            "primitives": [
                {
                    "id": "title",
                    "slot_id": "title",
                    "kind": "text",
                    "bounds": {"x": 160, "y": 320, "w": 1280, "h": 100},
                    "style": {
                        "color_token": "palette.text",
                        "typography_token": "typography.heading",
                    },
                    "text": {"content": "Full Bleed", "role": "heading"},
                },
                {
                    "id": "tiny_full",
                    "kind": "image_slot",
                    "bounds": {"x": 0, "y": 0, "w": 1920, "h": 1080},
                    "image_slot": {"image_ref": "tiny",
                                   "alt_text": "full-bleed PNG"},
                },
            ],
        }))
        full_bleed_out = td / "full_bleed.pptx"
        rc, _stdout, stderr = _run_capture(full_bleed_ws, full_bleed_out)
        single_pic = False
        emu_off_ok = False
        emu_ext_ok = False
        no_src_rect = False
        if rc == 0 and full_bleed_out.is_file():
            with _zipfile.ZipFile(full_bleed_out) as _zf:
                slide_xml = _zf.read("ppt/slides/slide1.xml").decode("utf-8")
            single_pic = slide_xml.count("<p:pic>") == 1
            pic_start = slide_xml.find("<p:pic>")
            pic_end = slide_xml.find("</p:pic>", pic_start)
            pic_block = (
                slide_xml[pic_start: pic_end + len("</p:pic>")]
                if pic_start >= 0 and pic_end >= 0 else ""
            )
            # 1920 px * 9525 EMU/px = 18288000; 1080 * 9525 = 10287000.
            emu_off_ok = '<a:off x="0" y="0"/>' in pic_block
            emu_ext_ok = (
                '<a:ext cx="18288000" cy="10287000"/>' in pic_block
            )
            no_src_rect = "<a:srcRect" not in pic_block
        results.append(CheckResult(
            "selftest: full-bleed image_slot (bounds == canvas) "
            "exports as a single <p:pic> with 1:1 px->EMU "
            "<a:off>/<a:ext> and no <a:srcRect> clip artifact "
            "(no-op fit does not break or double-transform)",
            (
                rc == 0
                and single_pic
                and emu_off_ok
                and emu_ext_ok
                and no_src_rect
            ),
            (f"rc={rc}, single_pic={single_pic}, "
             f"emu_off_ok={emu_off_ok}, emu_ext_ok={emu_ext_ok}, "
             f"no_src_rect={no_src_rect}; {stderr.strip()}"
             if not (
                rc == 0
                and single_pic
                and emu_off_ok
                and emu_ext_ok
                and no_src_rect
             ) else ""),
        ))

        # 25. POSITIVE: a successful export writes only the
        # named .pptx into the output directory — no
        # `.tmp` / `.partial` / `.cache` / `~` sibling files and
        # no media-fallback cache subdirectory survive. The
        # exporter goes straight from `zipfile.ZipFile(output,
        # "w")` to a complete archive, so this probe is a
        # regression gate against any future atomic-write swap
        # or SVG/PNG fallback cache that would leak intermediate
        # bytes next to the deck after a clean run. The fixture
        # uses its own isolated subdirectory under `td` so the
        # other scenarios' workspaces / `.pptx` outputs don't
        # appear as siblings.
        no_leftover_dir = td / "no_leftover_root"
        no_leftover_dir.mkdir()
        no_leftover_ws = no_leftover_dir / "ws"
        _write_synthetic_workspace(no_leftover_ws)
        no_leftover_out = no_leftover_dir / "deck.pptx"
        rc, _stdout, stderr = _run_capture(no_leftover_ws, no_leftover_out)
        sibling_names = sorted(p.name for p in no_leftover_dir.iterdir())
        only_expected_siblings = sibling_names == ["deck.pptx", "ws"]
        # Walk the workspace for any post-export stray cache or
        # temp files: png / svg / jpg / jpeg / tmp / partial /
        # cache that we did not author. Authored entries are the
        # JSON artifacts under render_models/ and the four
        # stage artifacts at the workspace root. Anything else
        # is a leftover.
        workspace_extras: list[str] = []
        if no_leftover_ws.is_dir():
            for p in no_leftover_ws.rglob("*"):
                if not p.is_file():
                    continue
                rel = p.relative_to(no_leftover_ws).as_posix()
                if rel in {
                    "design_system.json",
                    "deck_plan.json",
                    "image_manifest.json",
                }:
                    continue
                if rel.startswith("render_models/") and rel.endswith(".json"):
                    continue
                workspace_extras.append(rel)
        workspace_clean = not workspace_extras
        results.append(CheckResult(
            "selftest: successful export writes no temp / partial "
            "/ cache siblings next to the output and leaves no "
            "media-fallback artifacts in the workspace (clean "
            "media-leftover surface)",
            (
                rc == 0
                and no_leftover_out.is_file()
                and only_expected_siblings
                and workspace_clean
            ),
            (f"rc={rc}, output_exists={no_leftover_out.is_file()}, "
             f"sibling_names={sibling_names}, "
             f"workspace_extras={workspace_extras}; {stderr.strip()}"
             if not (
                rc == 0
                and no_leftover_out.is_file()
                and only_expected_siblings
                and workspace_clean
             ) else ""),
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
            "render_model artifacts. Supports the cover / "
            "kpi_dashboard / agenda / section_divider / "
            "executive_summary / key_message / two_column / timeline / "
            "conclusion / comparison_table layouts and the text / line "
            "/ shape / image_slot / kpi / table primitive kinds; "
            "everything else fails closed. image_slot primitives whose "
            "manifest entry resolves to a local PNG / JPG / JPEG file "
            "embed as a native <p:pic> referencing ppt/media/imageN.<ext>; "
            "SVG / GIF / WebP and other extensions fall back to the "
            "placeholder native shape carrying the alt_text. Unsafe / "
            "missing / symlinked / undeclared / oversized / magic-byte-"
            "mismatched media all fail closed. See "
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
             "&quot;; expanded-layout workspace using two_column exports "
             "and passes validate_pptx_contract; comparison_table "
             "workspace exports a native <p:graphicFrame>/<a:tbl> with "
             "editable cells; PNG manifest entry exports as embedded "
             "<p:pic> + ppt/media/image1.png; JPG manifest entry "
             "exports as embedded <p:pic> + ppt/media/image1.jpg with "
             "<Default Extension=\"jpg\" ContentType=\"image/jpeg\"/>; "
             "JPEG manifest entry exports as embedded <p:pic> + "
             "ppt/media/image1.jpeg with <Default Extension=\"jpeg\" "
             "ContentType=\"image/jpeg\"/>; SVG manifest entry still "
             "falls back to the placeholder shape; full-bleed "
             "image_slot bounds==canvas maps 1:1 px->EMU with no "
             "<a:srcRect> clip artifact; successful export writes no "
             "temp / partial / cache siblings or workspace fallback "
             "leftovers) and negatives "
             "(wrong output extension, unsupported `chart_placeholder` "
             "primitive, render_model missing a required field, "
             "image_slot image_ref not in manifest, manifest local_path "
             "with a URI scheme, manifest entry whose .png file is "
             "missing on disk, manifest entry whose declared extension "
             "does not match the on-disk magic bytes, manifest entry "
             "whose local_path is a symlink, render_model with an "
             "unsupported layout, mis-named render_model file, "
             "deck_plan-declared render_model missing on disk, orphan "
             "render_model not declared by deck_plan, deck_plan "
             "planned_slide_count disagrees with len(slides), primitive "
             "carrying a forbidden `rotation` key fails closed at "
             "schema, image_slot carrying a forbidden `transform` key "
             "fails closed at schema). Exits "
             "non-zero if any positive or negative is not handled as "
             "expected.",
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
