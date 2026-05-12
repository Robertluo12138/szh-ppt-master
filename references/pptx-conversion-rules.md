# PPTX Conversion Rules

The terminal output of the pipeline is an **editable** PPTX. A **minimal native editable subset** is now implemented by `scripts/export_pptx.py`; full PPT generation (every layout, every primitive, embedded media, theme palette mapping, allow-listed relationships, determinism inventory) remains TODO. This file is the contract the exporter satisfies for that subset and the surface the contract validator (`scripts/validate_pptx_contract.py`) checks against today.

## Implementation status

- A **minimal vertical slice** of PPTX export is implemented (`scripts/export_pptx.py`):
  - layouts: `cover` and `kpi_dashboard`;
  - primitive kinds: `text`, `line`, `shape`, `image_slot`, `kpi`;
  - the exporter consumes `render_model.json` directly — it does **not** parse `svg_previews/*.svg`, does **not** screenshot a slide, and does **not** rasterize a whole slide into a single picture;
  - the package contains only stdlib-written XML parts (`[Content_Types].xml`, `_rels/.rels`, `ppt/presentation.xml`, `ppt/_rels/presentation.xml.rels`, one `ppt/slides/slide{N}.xml` + `_rels/` per exported slide, `ppt/slideLayouts/slideLayout1.xml` + `_rels/`, `ppt/slideMasters/slideMaster1.xml` + `_rels/`, and `ppt/theme/theme1.xml`); there are no embedded media parts, no remote relationships, no macros, no OLE, and no ActiveX parts.
- The slice intentionally fails closed on everything outside that surface:
  - `table` primitive — fail-closed (no native PPTX-table emission yet);
  - `chart_placeholder` primitive — fail-closed (no native chart-frame emission yet);
  - layouts other than `cover` / `kpi_dashboard` — per-slide fail-closed with a `[FAIL]` line; the whole run aborts and no `.pptx` is written. The exporter contract is intentionally all-or-nothing: it refuses to drop coverage for slides whose layout is not yet implemented. The render-model generator already only emits the supported layouts, so today no `render_models/*.json` in the example workspaces trips this gate.
- Media embedding is **not** implemented. `image_slot` primitives are exported as **native placeholder rectangle shapes** carrying the `image_manifest` alt_text (or the image_ref id when no alt_text is declared). PNG / JPG / SVG bytes are NOT copied into `ppt/media/`. The exporter still validates the `image_ref` against `image_manifest` and re-runs `local_path_is_safe` on the resolved path, so an unsafe / missing reference fails closed at preflight.

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

## Contract validator: today's checks

`scripts/validate_pptx_contract.py` is a stdlib-only, fail-closed contract validator that grows alongside the exporter. It is **not** proof of full export correctness — it gates a known minimum surface and explicitly names the deeper checks that remain TODO.

In skeleton mode (no `--pptx`) the validator reports only the contract / TODO surface and does not open or fabricate any file. With `--pptx <path>` it runs two layers of fail-closed checks:

Container basics (unchanged):

- the claimed `--pptx <path>` exists on disk;
- the file extension is `.pptx` (case-insensitive);
- the file opens as a readable ZIP container;
- the ZIP contains the required OOXML entries `[Content_Types].xml`, `_rels/.rels`, and `ppt/presentation.xml`.

Minimal-evidence gates (added with the minimal exporter):

- `slide_count.inspectable` — counts `ppt/slides/slide{N}.xml` parts; a run with zero slide parts fails closed (the exporter requires at least one exported slide);
- `relationships.no_external` — no `Relationship` element has `TargetMode="External"`, and no `Target` value matches the `^[A-Za-z][A-Za-z0-9+.-]*:` URI-scheme prefix;
- `relationships.no_file_uri` — no `Relationship` `Target` starts with `file://` (subset of the above, surfaced separately so a regression is unmistakable);
- `package.no_macros` — no `ppt/vbaProject.bin` part, no `vbaProject` content-type override;
- `package.no_ole` — no part under `ppt/embeddings/`, no `oleObject` content-type override;
- `package.no_activex` — no part under `ppt/activeX/`, no `activeX` content-type override;
- `minimal_evidence.editable_text` — at least one slide carries a `<p:txBody>` with a non-empty `<a:t>` run. This is a positive-existence proof on one slide; it is **minimal evidence** and does NOT prove every text on every slide is editable;
- `minimal_evidence.not_all_image_slide` — every slide that carries a `<p:pic>` also carries at least one `<p:sp>` or `<p:cxnSp>`. This is **minimal evidence** that the slide is not a one-big-PNG output; a full inventory of editable shapes remains TODO.
- `minimal_evidence.no_blank_slide` — every slide carries at least one structural element (`<p:sp>`, `<p:cxnSp>`, or `<p:pic>`); a slide whose `<p:spTree>` is structurally empty fails closed. **Minimal evidence** only: paired with `not_all_image_slide` above, the two together close the loophole where slide 1 carries editable text and slide 2 is blank (which would otherwise satisfy both `editable_text` and `not_all_image_slide` individually).

`--self-test` exercises tempfixture negatives for every gate (missing file, wrong extension, non-zip content, empty ZIP, ZIP missing `ppt/presentation.xml`, external rel, `file://` rel, `vbaProject.bin`, `oleObject1.bin`, `activeX1.xml`, all-image slide, no editable text) plus two positives (minimal valid container, minimal editable PPTX).

The following checks remain explicitly TODO and are surfaced in every run:

- `editability.full_inventory` — every text frame on every slide is a real text frame (full inventory, not just one slide);
- `no_image_only_slides.full_inventory` — every slide is positively confirmed to contain editable shapes;
- `relationships.allow_list` — restrict the relationship type set to an explicit allow-list (slide, slideMaster, slideLayout, theme, officeDocument);
- `media.embedded_only` — every media item is embedded inside the package (the closest gate today is `relationships.no_external`);
- `media.inventory` — every media item exists inside the package; no dangling refs;
- `theme.palette_mapping` — `design_system` palette resolves to the matching PPTX theme slots;
- `determinism` — stable IDs, relationship order, and media filenames across runs (the exporter uses a fixed ZIP timestamp and deterministic ids today; the validator does not yet read these back out);
- `layouts.scope` / `primitives.scope` — the exporter enforces layout / primitive scope at write time; the validator does not yet read the layout slot or primitive mapping back out of the produced PPTX.

A passing run of this validator therefore proves the container shape, the absence of macro / OLE / ActiveX parts and external / `file://` relationships, and minimal evidence of editable native content. It does NOT prove the deeper TODO surface above.

## Inspection

- A conversion report should list every media item, every relationship type, and confirm that every text run is editable. (TODO — depends on the full-inventory editability checks above.)

## TODOs

- Enumerate the allowed PPTX relationship allow-list.
- Define palette → theme slot mapping.
- Cover the remaining `render_model` primitive → native PPTX object mapping: `table` → native PPTX table, `chart_placeholder` → blank chart frame. Today the exporter maps `text` → text frame, `shape` → native PPTX shape, `line` → native line / connector, `image_slot` → placeholder rectangle (alt_text only, no embedded media), `kpi` → composite text frame with stacked paragraphs; `table` and `chart_placeholder` fail closed.
- Implement native-object / full-inventory editability / relationship allow-list / media / determinism / layouts.scope / primitives.scope checks inside `scripts/validate_pptx_contract.py`. Today these are explicitly TODO.
- Decide whether speaker notes round-trip.
- Decide whether and how to embed PNG / JPG / SVG media into `ppt/media/` (PowerPoint requires a PNG fallback for SVG, plus a media relationship per slide picture).
