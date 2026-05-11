# PPTX Conversion Rules

The terminal output is an **editable** PPTX. Conversion is not implemented yet; this is the contract.

## Editability requirements

- Every body of text is a real text frame. No outlined-to-path text.
- Every shape is a native PPTX shape, not a rasterized image of a shape.
- Tables are real PPTX tables.
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

## Inspection

- A conversion report must list every media item, every relationship type, and confirm that every text run is editable.

## TODOs

- Enumerate the allowed PPTX relationship allow-list.
- Define palette → theme slot mapping.
- Define SVG primitive → PPTX shape mapping.
- Decide whether speaker notes round-trip.
