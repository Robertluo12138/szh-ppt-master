# SVG Design Rules

The SVG layer is the **intermediate design layer**: per-slide layouts, text, shapes, and image references are first expressed as SVG, then converted to editable PPTX. Direct PPTX construction from a slide plan is not allowed.

SVG rendering is not implemented yet; this file is the contract the renderer must satisfy.

## Bounds

- Every SVG must declare an explicit `viewBox` matching the design grid (see `design_system.json.grid`).
- No element may extend outside the `viewBox`. Renderer must reject or repair out-of-bounds shapes.
- Text frames must declare width/height; no auto-overflow.

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

- Every text run must be a real `<text>` (or `<tspan>`) node. Outlined / pathified text is not allowed.
- Every shape must be expressible as a native PPTX shape after conversion. A list of supported SVG primitives is **TODO**; until it exists, prefer the obvious primitives (`rect`, `circle`, `ellipse`, `line`, `polygon`, `path` with straight + cubic segments, `text`, `g`).

## Validation / repair

- Validator passes: bounds, references, colors, fonts, density, editability.
- Repair is allowed for bounded automatic fixes (e.g. clipping out-of-bounds shapes). The repair report must list every modification.
- A slide that cannot be safely repaired is failed and surfaced to the caller; the pipeline does not silently drop slides.

## TODOs

- Choose the density threshold.
- Choose the minimum effective body font size.
- Enumerate supported SVG primitives.
- Define palette-derivation rules for tints/shades.
