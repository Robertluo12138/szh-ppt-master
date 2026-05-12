# SVG Design Rules

The SVG layer is the per-slide **preview / inspection artifact** and the deterministic visual-validation gate. It is rendered from `render_model.json` (see `schemas/render_model.schema.json` and `references/slide-contracts.md`), the same controlled source the editable PPTX exporter will read. SVG is **not** an intermediate stage on the way to PPTX: the PPTX exporter will not parse SVG. Both stages produce their output from the same render model, so the visual preview and the editable deck agree by construction.

SVG rendering is **partially implemented**: `scripts/generate_svg_previews.py` reads `<workspace>/render_models/*.json` and writes `<workspace>/svg_previews/<stem>.svg` for the primitive kinds the render-model generator emits today (`text`, `line`, `shape`, `image_slot`, `kpi`, `table`). Every other kind (`chart_placeholder` or any future kind) fails closed on that slide. PPTX export is implemented for the same primitive set — see `references/pptx-conversion-rules.md`.

## Source of truth

The renderer consumes `render_model.json`. It does **not** consume `slide_plan.json` directly — the controlled primitive contract cannot be bypassed. The render model already enforces:

- a closed set of primitive kinds (`text`, `shape`, `line`, `image_slot`, `table`, `kpi`, `chart_placeholder`); no arbitrary SVG-like fields (`transform`, `viewBox`, `href`, `xlink:href`, `xmlns`, `defs`, `foreignObject`, `filter`, …) appear in the input;
- required bounds for every primitive (so the renderer never has to invent them);
- token-only style references (`palette.*`, `typography.heading|body`) instead of raw colors / families;
- image references by `image_manifest` id only, never by URL or filesystem path.

Therefore the SVG layer adds **rendering** on top of an already-controlled model. It does not need to re-enforce the model's invariants, but the SVG-side rules below remain in force for the output it produces.

This repo is **not** a general SVG → PPTX converter, and SVG is **not** the source language for PPTX shapes. The renderer emits only the SVG shapes corresponding to the controlled primitive set, and the PPTX exporter independently emits native PowerPoint objects from the same render model. A `render_model` that contains an unsupported kind never reaches either consumer (validators fail closed before then).

## Bounds

- Every SVG must declare an explicit `viewBox` matching the design grid (see `design_system.json.grid`). **Implemented** — `check_svg_previews` fails closed when the root `viewBox` does not match the render_model canvas.
- No element may extend outside the `viewBox`. **Partially implemented.** `check_svg_previews` runs a best-effort geometry walk over `<rect>`, `<image>`, `<ellipse>`, `<circle>`, `<line>` (full box check via `x`/`y`/`w`/`h`, `cx`/`cy`/`r[xy]`, or `x1`/`y1`/`x2`/`y2`) and `<text>` (anchor point only, via `x`/`y`). Repair (clipping out-of-bounds shapes) is not implemented.
- Text frames must declare width/height; no auto-overflow. **Not implemented yet (TODO).** Today the renderer emits each `text` primitive as a single-line `<text>` element positioned by `x`/`y` only, without a declared bounding box. The validator therefore only checks that the `<text>` anchor point sits inside the canvas; it cannot prove that the rendered glyphs stay inside the original render_model primitive bounds without font metrics. Closing this gap requires either a deterministic SVG text-measurement step (stdlib-only options are limited) or a switch to laying out text with explicit width / height attributes the consumer can clip against. Until then, slides with overflowing text are not auto-detected.

## References

- Images are referenced by `id` from the slide's `image_manifest.json`, resolved to a relative `local_path` at render time.
- Any URI-like scheme inside an SVG reference is **forbidden**. The validator must reject any string matching `^[A-Za-z][A-Za-z0-9+.\-]*:` (covers `http://`, `https://`, `file://`, `s3://`, `ftp://`, `data:`, `mailto:`, `javascript:`, and Windows drive prefixes like `C:`, `D:/`). POSIX-absolute paths (`/...`), leading-backslash, protocol-relative (`//host/...`), and any `..` segment are also forbidden — same fail-closed rule as `scripts/validate_workspace.py` and `scripts/validate_scaffold.py`'s `local_path_is_safe`.
- Fonts must be referenced by family name only. No `@font-face` rules pointing to remote URLs.

## Color

- Colors must come from `design_system.json.palette` plus tints/shades derived deterministically. Hardcoded ad-hoc colors are not allowed in production SVG (TODO: define the derivation rules).
- All colors must be 6-digit hex.

## Density

- A single slide's SVG should not contain more than **N** primary elements (TODO: choose N, likely ~12–15) excluding decorative shapes. The validator should flag dense slides.
- Text must remain readable at the deck's intended display size; minimum effective font size is **TODO**.

## Editability

SVG editability matters because the SVG is the per-slide preview / inspection artifact. A reviewer opening it must be able to pick text out as text, identify each shape, and trust that what they see corresponds 1:1 to a primitive declared on the same `render_model` the PPTX exporter independently reads.

- Every text run must be a real `<text>` (or `<tspan>`) node. Outlined / pathified text is not allowed; it breaks the preview's editability contract and hides what the renderer was given.
- Every SVG element must visually lower a controlled `render_model` primitive (`text`, `shape`, `line`, `image_slot`, `table`, `kpi`, `chart_placeholder`). The SVG layer adds no shapes the render_model did not declare; it is a faithful preview of the same primitive set the PPTX exporter consumes. PPTX editability is delivered by the PPTX exporter constructing native PowerPoint objects from the render_model directly — not by re-parsing this SVG.
- Each controlled render_model primitive must therefore remain expressible both as a native PPTX object (text frame, native shape, native connector / line, picture, native `<a:tbl>` for `table`, composite text frame for `kpi`, blank chart frame for `chart_placeholder`) and as a corresponding SVG element in the preview. Today the renderer uses: `text` → `<text>`; `line` → `<line>`; `shape` → `<rect>` / `<rect rx>` / `<ellipse>`; `image_slot` → `<image>`; `kpi` → composite `<g>` with stacked `<text>` runs; `table` → composite `<g>` with grid `<rect>` outline plus one `<text>` per cell. `chart_placeholder` rendering remains TODO.

## Validation / repair

- Validator passes: bounds, references, colors, fonts, density, editability.
- Repair is allowed for bounded automatic fixes (e.g. clipping out-of-bounds shapes). The repair report must list every modification.
- A slide that cannot be safely repaired is failed and surfaced to the caller; the pipeline does not silently drop slides.

## What `check_svg_previews` enforces today

`scripts/validate_workspace.py` runs `check_svg_previews(workspace, template_root)` whenever the workspace ships `render_models/`. The check is fail-closed and exercises:

- **existence**: every `render_models/<stem>.json` must have a matching `svg_previews/<stem>.svg`;
- **shape**: the SVG must parse as XML; the root element must be `<svg>` in the SVG namespace (`http://www.w3.org/2000/svg`); the root `viewBox` must equal `0 0 <width> <height>` matching the render_model canvas;
- **no escape hatch**: no `<foreignObject>` may appear anywhere in the tree;
- **safe references**: every attribute whose local name ends in `href`, plus `src`, is run through the same `local_path_is_safe` rule that gates `image_manifest.local_path` and `deck_plan.template`. URI schemes (`http://`, `https://`, `file://`, `s3://`, `data:`, `mailto:`, `javascript:`, …), POSIX-absolute paths, leading backslash, protocol-relative `//host/...`, `..` segments, Windows drive prefixes, and the empty string are all rejected;
- **declared image refs**: every `<image>` `href` value must equal a `local_path` declared in `image_manifest.images[]`;
- **bounds (best-effort)**: every `<rect>`, `<image>`, `<ellipse>`, `<circle>`, `<line>` with explicit numeric geometry must stay inside the canvas, and every `<text>` with numeric `x`/`y` must have its anchor point inside the canvas. The validator does NOT enforce a `<text>` width / height / wrapping box — that requires font metrics this stdlib-only validator does not carry, and remains the TODO at the top of this file. Elements whose geometry is expressed differently (e.g. `path d="…"`) are also not checked by this best-effort pass.

Tempfixture negatives in `validate_workspace.py` prove each of these mutations is detected (missing svg, malformed XML, wrong root, viewBox mismatch, `<foreignObject>` present, `href` carrying every unsafe shape above, undeclared `<image>` href, `<rect>` outside the canvas, and `<text>` whose anchor `x`/`y` is negative or beyond the canvas), and that the generator fails closed on an unsupported primitive kind, unknown palette token, image_slot resolving to an unsafe manifest `local_path`, missing `render_models/`, malformed / unsafe `image_manifest.json` (preflight runs before cleanup — pre-existing `svg_previews/*.svg` survive a failed run), non-hex / schema-violating design tokens (palette + font_family), background `palette.background` routed through `_resolve_palette` (no direct dict bypass), and that stale `*.svg` from a previous run is removed by the cleanup sweep while non-SVG files (READMEs, `NOTES.md`, …) are preserved.

## TODOs

- **Text overflow detection.** The renderer emits each `text` primitive as a single-line `<text>` with `x` / `y` / `font-size` only — no width / height / wrapping box. The validator therefore only checks that the `<text>` anchor sits inside the canvas; it cannot prove the rendered glyph run stays inside the render_model primitive's `bounds.w` / `bounds.h`. Closing this requires either font-metric measurement (no satisfying stdlib option) or a layout change that emits a clippable wrapping box. Until then, an overflowing text primitive is not auto-detected.
- Choose the density threshold.
- Choose the minimum effective body font size.
- Enumerate supported SVG primitives.
- Define palette-derivation rules for tints/shades.
