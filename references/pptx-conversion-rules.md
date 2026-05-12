# PPTX Conversion Rules

The terminal output of the pipeline is an **editable** PPTX. PPTX export is **NOT implemented** yet. This file is the contract the future exporter must satisfy, and the surface the in-tree contract validator skeleton (`scripts/validate_pptx_contract.py`) checks against today.

## Implementation status

- PPTX export is **NOT implemented**. The pipeline stops at the SVG preview for the supported render-model subset; no `*.pptx` is produced.
- The future PPTX exporter **must consume `render_model.json` directly**. It must **not** parse `svg_previews/*.svg`, must **not** screenshot a slide, and must **not** rasterize a whole slide into a single picture.
- Native editable PPTX objects only: every text body is a real text frame; every shape is a native PPTX shape; every picture is a native picture shape; every line is a native line / connector. An "all-image" slide is **not** a valid output.
- Initial export scope, when the exporter lands, is the existing supported render-model subset only:
  - layouts: `cover` and `kpi_dashboard`;
  - primitive kinds: `text`, `line`, `shape`, `image_slot`, `kpi`.
- Out-of-scope primitive kinds remain TODO and must **fail closed** in the exporter when encountered:
  - `table` — TODO / fail-closed (no native PPTX-table emission yet);
  - `chart_placeholder` — TODO / fail-closed (no native chart-frame emission yet).
- Out-of-scope layouts (everything other than `cover` / `kpi_dashboard`) likewise fail closed in the exporter until the render-model generator covers them.

## Editability requirements

- Every body of text is a real text frame. No outlined-to-path text.
- Every shape is a native PPTX shape, not a rasterized image of a shape.
- Tables (when implemented) are real PPTX tables.
- Images appear only as picture shapes referencing media stored inside the PPTX package.
- A slide that is "one big PNG" is not editable and is not a valid output.

## Relationship safety

- Allowed relationship types are an explicit allow-list (**TODO** to enumerate). Anything outside the list fails the security scan.
- No OLE objects, ActiveX controls, embedded macros, or external/remote media.
- All media must be embedded; no remote URLs in `<a:blip r:link="…"/>` style references.

## Theme mapping

- Theme colors and fonts come from `design_system.json` and the template's `theme.json`.
- Conversion must preserve palette identity: a color used as `primary` in design_system should land in the corresponding theme slot in the PPTX (mapping is **TODO**).

## Layouts

- Each template layout under `templates/layouts/<template>/layouts/` maps to a PPTX slide layout. The mapping is **TODO**; the scaffold layouts are placeholders.

## Determinism

- Conversion must be deterministic given the same inputs. Random ordering of relationships, IDs, or media file names is not allowed.

## Contract validator skeleton

`scripts/validate_pptx_contract.py` is a stdlib-only **contract / skeleton** validator. It is **not** proof that PPTX export works — it is a fail-closed surface that grows alongside the exporter. Today the skeleton checks only the OOXML container basics:

- A claimed PPTX path (`--pptx <path>`) must exist on disk.
- The file extension must be `.pptx` (case-insensitive).
- The file must open as a readable ZIP container.
- The ZIP must contain the required basic OOXML package entries (`[Content_Types].xml`, `_rels/.rels`, and at least one `ppt/presentation.xml` part).

Detailed native-object inspection, text-frame editability checks, allow-list relationship enforcement, media inventory, and chart / table emission validation are **all TODO** and are explicitly marked as such in the script's `--help` and in the per-check output. The validator must not be cited as evidence that export is implemented; it gates the future exporter's container before any of those deeper checks come online.

When no `--pptx` path is supplied, the validator runs in "skeleton" mode and only reports the contract / TODO surface; it does not fabricate a fake PPTX.

## Inspection

- A conversion report must list every media item, every relationship type, and confirm that every text run is editable. (TODO — depends on the deeper PPTX checks above.)

## TODOs

- Enumerate the allowed PPTX relationship allow-list.
- Define palette → theme slot mapping.
- Define `render_model` primitive → native PPTX object mapping (`text` → text frame, `shape` → native PPTX shape, `line` → native line / connector, `image_slot` → picture shape, `table` → native PPTX table, `kpi` → composite text frame, `chart_placeholder` → blank chart frame). The PPTX exporter consumes `render_model.json` directly; it does not parse SVG.
- Implement native-object / editability / relationship allow-list / media / determinism checks inside `scripts/validate_pptx_contract.py` once the exporter lands. Today these are skeleton TODOs.
- Decide whether speaker notes round-trip.
