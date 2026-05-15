# PPTX Conversion Rules

The terminal output of the pipeline is an **editable** PPTX. An **expanded native editable subset** is now implemented by `scripts/export_pptx.py`, including a narrow PNG / JPG / JPEG embed slice for `image_slot` primitives; full PPT generation (every layout, every primitive, SVG / GIF / WebP embedded media, theme palette mapping, determinism inventory) remains TODO. This file is the contract the exporter satisfies for that subset and the surface the contract validator (`scripts/validate_pptx_contract.py`) checks against today.

## Implementation status

- An **expanded vertical slice** of PPTX export is implemented (`scripts/export_pptx.py`):
  - slide enumeration is driven by `deck_plan.json`: the exporter iterates `deck_plan.slides[]` in declared order and resolves each entry to its canonical `render_models/<idx:02d>_<layout>.json`. A missing planned render_model, an orphan render_model not named by `deck_plan`, or a `planning.planned_slide_count` that disagrees with `len(slides)` fails closed before any output is written;
  - layouts: `cover`, `kpi_dashboard`, `agenda`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `timeline`, `conclusion`, `comparison_table`. The slide-body emitter is layout-agnostic — it iterates the render_model's `primitives` list and emits one native PPTX object per primitive — so adding a layout to this allow-list does not change how any single shape is rendered;
  - primitive kinds: `text`, `line`, `shape`, `image_slot`, `kpi`, `table` (the `table` primitive emits a native `<p:graphicFrame>` wrapping `<a:tbl>` with one `<a:gridCol>` per column, a bold header row, and an editable `<a:txBody>` per `<a:tc>` cell);
  - the exporter consumes `render_model.json` directly — it does **not** parse `svg_previews/*.svg`, does **not** screenshot a slide, and does **not** rasterize a whole slide into a single picture;
  - the package contains stdlib-written XML parts (`[Content_Types].xml`, `_rels/.rels`, `ppt/presentation.xml`, `ppt/_rels/presentation.xml.rels`, one `ppt/slides/slide{N}.xml` + `_rels/` per exported slide, `ppt/slideLayouts/slideLayout1.xml` + `_rels/`, `ppt/slideMasters/slideMaster1.xml` + `_rels/`, and `ppt/theme/theme1.xml`) plus zero or more embedded PNG / JPG / JPEG media parts under `ppt/media/imageN.<ext>` (one per unique embedded image_id; the bytes are written verbatim with the same fixed ZIP timestamp so the package stays byte-stable). There are no remote relationships, no macros, no OLE, and no ActiveX parts; embedded media is restricted to the PNG / JPG / JPEG slice described below.
- The slice intentionally fails closed on everything outside that surface:
  - `chart_placeholder` primitive — fail-closed (no native chart-frame emission yet);
  - layouts outside the allow-list above — per-slide fail-closed with a `[FAIL]` line; the whole run aborts and no `.pptx` is written. Every layout declared by the business_review template skeleton is currently in scope; new layouts must add a paired generator branch before they may appear here. The exporter contract is intentionally all-or-nothing: it refuses to drop coverage for slides whose layout is not yet implemented.
- A **narrow PNG / JPG / JPEG embed slice** is now implemented. An `image_slot` primitive whose `image_manifest` entry resolves to a local PNG / JPG / JPEG file is exported as a native `<p:pic>` (with `<p:blipFill>` and `<a:blip r:embed="rIdN"/>`); the bytes are copied verbatim into `ppt/media/imageN.<ext>` (deterministic, manifest-declared order — `image1.<ext>`, `image2.<ext>`, ...), the matching `<Default Extension="png" ContentType="image/png"/>` (or `image/jpeg`) is added to `[Content_Types].xml`, and a per-slide `image` relationship lands in `ppt/slides/_rels/slideN.xml.rels` with an internal Target like `../media/image1.png` (no `TargetMode="External"`, no `file://`, no URI scheme). Two `image_slot` primitives referencing the same `image_id` share a single relationship.
- All other manifest extensions (SVG, GIF, WebP, ...) still fall back to the **native placeholder rectangle shape** carrying the `image_manifest` alt_text (or the image_ref id when no alt_text is declared); SVG / GIF / WebP embedding remains TODO.
- The PNG / JPG / JPEG embed gate is fail-closed: a manifest entry whose path-safety fails, whose resolved path escapes the workspace, whose asset is a symlink (broken or resolvable), whose asset is missing or not a regular file, whose size exceeds the 10 MiB embed cap, or whose magic bytes do not match the declared extension all abort the run before any `.pptx` is written. Manifest entries with a non-PNG/JPG extension are intentionally NOT errors — they demote to the placeholder shape.

## Editability requirements

- Every body of text is a real text frame. No outlined-to-path text.
- Every shape is a native PPTX shape, not a rasterized image of a shape.
- Tables are real PPTX tables (`<a:tbl>` inside `<p:graphicFrame>`), not images or text-frame impostors.
- Images appear only as picture shapes referencing media stored inside the PPTX package.
- A slide that is "one big PNG" is not editable and is not a valid output.

## Relationship safety

- Allowed relationship types are an explicit allow-list, validated by `relationships.allow_list`: `officeDocument`, `slide`, `slideMaster`, `slideLayout`, `theme`, `image` (the canonical `http://schemas.openxmlformats.org/officeDocument/2006/relationships/...` URLs). Anything outside this set fails the security scan.
- The `image` URL is reserved for per-slide PNG / JPG / JPEG media relationships emitted by the embed slice. Every such relationship carries an internal Target under `../media/imageN.<ext>` and never sets `TargetMode="External"`. The `media.targets_internal` gate enforces this.
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

Minimal-evidence gates (grew alongside the exporter):

- `slide_count.inspectable` — counts `ppt/slides/slide{N}.xml` parts; a run with zero slide parts fails closed (the exporter requires at least one exported slide);
- `slide_count.expected` — caller-driven. When the CLI is invoked with `--expected-slide-count N` alongside `--pptx`, the slide-part count must equal `N`, otherwise the run fails closed. This is the validator-side complement to the exporter's `deck_plan` / `render_models` 1:1 coverage gate — it catches a deck the exporter silently truncated;
- `relationships.no_external` — no `Relationship` element has `TargetMode="External"`, and no `Target` value matches the `^[A-Za-z][A-Za-z0-9+.-]*:` URI-scheme prefix;
- `relationships.no_file_uri` — no `Relationship` `Target` starts with `file://` (subset of the above, surfaced separately so a regression is unmistakable);
- `relationships.allow_list` — every `Relationship` `Type` URL is in `{officeDocument, slide, slideMaster, slideLayout, theme, image}` (canonical OOXML URLs). An unexpected internal Type (hyperlink, comments, chart, embedding, ...) trips the gate even when the Target is local and lacks a URI scheme;
- `media.targets_internal` — every `image`-typed `Relationship` `Target` is an internal package path (no URI scheme, no `file://`, no `TargetMode="External"`). Subset of `relationships.no_external` + `.no_file_uri`, surfaced separately so a media-only regression is unmistakable;
- `media.inventory` — every `image`-typed `Relationship` `Target` resolves to an actual `ppt/media/<name>` part inside the ZIP (no dangling refs); every `ppt/media/` part is referenced by at least one `image` relationship (no orphan media); each part's extension is in `{png, jpg, jpeg}` and matches a `<Default Extension="..." ContentType="..."/>` entry whose ContentType is one of `{image/png, image/jpeg}`;
- `media.embedded_only` — no `<a:blip>` element anywhere in the package's content XML carries an `r:link="..."` attribute. Scope is every `*.xml` part under `ppt/` that is not a `_rels/` file (slides, slideMasters, slideLayouts, theme, presentation). The `r:link` form is OOXML's external-linked-image reference; the exporter only emits `r:embed`. This is the deeper guarantee that complements `relationships.no_external` + `relationships.allow_list` + `media.targets_internal` on the rels side — even if a tampered rels file pointed an `image` rel at an internal Target, a slide that USES the rel through `r:link` still fails closed. Read + parse handling is fail-closed: ANY exception during `ZipFile.read()` or `ET.fromstring()` against an in-scope part is itself reported as an offender — including `zipfile.BadZipFile` (CRC mismatch; its base class is `Exception`, NOT `OSError`) and `RuntimeError` (archive-internal failures) — so a corrupted or malformed XML part cannot silently bypass the gate. The exception type name is included in the offender string for debuggability;
- `package.no_macros` — no `ppt/vbaProject.bin` part, no `vbaProject` content-type override;
- `package.no_ole` — no part under `ppt/embeddings/`, no `oleObject` content-type override;
- `package.no_activex` — no part under `ppt/activeX/`, no `activeX` content-type override;
- `minimal_evidence.editable_text` — at least one slide carries a `<p:txBody>` with a non-empty `<a:t>` run. This is a positive-existence proof on one slide; it is **minimal evidence** and does NOT prove every text on every slide is editable;
- `minimal_evidence.not_all_image_slide` — every slide that carries a `<p:pic>` also carries at least one `<p:sp>` or `<p:cxnSp>`. This is **minimal evidence** that the slide is not a one-big-PNG output; a full inventory of editable shapes remains TODO;
- `minimal_evidence.no_blank_slide` — every slide carries at least one structural element (`<p:sp>`, `<p:cxnSp>`, or `<p:pic>`); a slide whose `<p:spTree>` is structurally empty fails closed. **Minimal evidence** only;
- `minimal_evidence.every_slide_has_native_shape` — every slide carries at least one native editable structure (`<p:sp>` or `<p:cxnSp>`). This is the single positive statement of "every slide has at least one native editable structure"; the combination of `not_all_image_slide` + `no_blank_slide` covers the same surface as failure-mode disambiguation, but this gate spells the contract out as one explicit positive check so a regression is unmistakable. Still **minimal evidence** — it counts structures, not per-shape editability.

`--self-test` exercises tempfixture negatives for every gate (missing file, wrong extension, non-zip content, empty ZIP, ZIP missing `ppt/presentation.xml`, external rel, `file://` rel, unexpected relationship `Type`, `vbaProject.bin`, `oleObject1.bin`, `activeX1.xml`, all-image slide (fails both `not_all_image_slide` and `every_slide_has_native_shape`), no editable text, blank slide alongside an editable one, external image rel, dangling image-rel Target, orphan `ppt/media/` part, `ppt/media/<name>.gif` outside the embed allow-list, slide carrying `<a:blip r:link="rIdL"/>` alongside an editable text shape, unparseable XML at `ppt/theme/theme1.xml` (fails closed on `media.embedded_only` — no fail-open parse path), direct unit-test that stub-injected `zipfile.BadZipFile` + `RuntimeError` on read are recorded as `media.embedded_only` offenders (no fail-open read path; both exception types are outside the narrow `(KeyError, OSError)` tuple so a regression that re-narrowed the catch would be caught)) plus positives (minimal valid container, minimal editable PPTX, 2-slide PPTX passing `slide_count.expected=2`, minimal PNG-embed PPTX whose slide actually carries `<p:pic>` with `<a:blip r:embed="rId1"/>` next to the editable text shape — so the positive exercises `media.embedded_only`'s accept path rather than passing trivially on a zero-blip slide — passing `media.targets_internal` + `media.inventory` + `media.embedded_only`).

The following checks remain explicitly TODO and are surfaced in every run:

- `editability.full_inventory` — every text frame on every slide is a real text frame (full inventory, not just one slide);
- `no_image_only_slides.full_inventory` — every slide is positively confirmed to contain editable shapes (the `every_slide_has_native_shape` + `not_all_image_slide` + `no_blank_slide` triple is **minimal evidence** for this; a full per-shape inventory still needs per-shape introspection);
- `theme.palette_mapping` — `design_system` palette resolves to the matching PPTX theme slots;
- `determinism` — stable IDs, relationship order, and media filenames across runs (the exporter uses a fixed ZIP timestamp and deterministic ids + `imageN.<ext>` media filenames today; the validator does not yet read these back out);
- `layouts.scope` / `primitives.scope` — the exporter enforces layout / primitive scope at write time; the validator does not yet read the layout slot or primitive mapping back out of the produced PPTX.

A passing run of this validator therefore proves the container shape, the absence of macro / OLE / ActiveX parts and external / `file://` relationships, the relationship `Type` allow-list (including the `image` URL), the embedded-media inventory + targets-internal + embedded-only gates over `ppt/media/` parts and every `<a:blip>` in the package's content XML, and minimal evidence of editable native content on every slide. It does NOT prove the deeper TODO surface above.

## Inspection

- The `media.inventory` gate iterates every embedded media item under `ppt/media/`, every `image`-typed relationship, and the matching `[Content_Types].xml` Defaults internally to gate them, but the validator's PASS output is only a single `[PASS] media.inventory: <pptx>` line — a failing run lists the offending parts in its detail field.
- `scripts/inspect_pptx_inventory.py --pptx <path>` is the **structured readback inventory** that complements the pass/fail validator above. It reads the same package and emits a deterministic JSON document with: slide count, per-slide native object counts (`shapes_sp` / `connectors_cxnSp` / `pictures_pic` / `graphic_frames` / `tables` / `text_bodies` / `text_runs`), per-slide `media_refs` (each entry carries rId, declared Target, resolved package path, and a `used_by_slide_blip` flag that is True iff at least one `<a:blip r:embed="rIdN"/>` actually consumes the rId), embedded `media_parts` under `ppt/media/` (size_bytes, sha256, extension, declared content_type, sorted `referencing_slides[]` list of slide indices), the full relationship list sorted by `(rels_part, id)`, and `findings[]` with stable codes `relationships.external` / `relationships.file_uri` / `relationships.absolute` / `relationships.path_traversal` / `media.missing` (image rel has a missing or empty `Target`, OR its `Target` does not resolve to a part in the package) / `media.orphan` / `media.unsupported_extension` / `slide.image_only` / `media.linked_blip` (any `<a:blip r:link="..."/>` anywhere in slides / slideMasters / slideLayouts / theme / presentation — same surface `media.embedded_only` refuses) / `package.unreadable_zip` / `package.unreadable_xml`. The top-level `evidence_basis` field commits to `"OOXML structure only; not proof of full PowerPoint editability"` so a caller cannot mistake the inventory for a full editability inventory. The script is inspection-only (no writes outside `--out`, no network), fail-closed (exit 1 when any finding is recorded — JSON still emitted), and deterministic (sorted keys / findings / slides / media parts / relationships, so two runs against byte-identical input produce byte-identical JSON). `--self-test` exercises 16 tempfixture scenarios: happy path, deterministic repeated inventory, image-only slide failure, missing media, image rel with NO `Target` attribute (fails closed on `media.missing`; without this explicit check the rel would fall off every downstream media gate — the path-traversal block guards on `target` truthiness, so a missing/empty Target would never reach the resolution map), orphan media, external rel, `file://` rel, absolute-path rel, path-traversal rel, bad XML at a slide part, unsupported media extension (`image1.gif`), linked-blip `<a:blip r:link="rIdL"/>` in a slide (with the rels file untouched, so every `relationships.*` / `media.*` gate stays green — only the per-`<a:blip>` walk catches the linked form), unparseable XML in a non-slide part (`ppt/theme/theme1.xml`) surfaced via the linked-blip walker (no fail-open `continue`), unreadable ZIP, and nonexistent file. The local pipeline runners (`scripts/run_pipeline.py` and `scripts/run_explicit_pipeline.py`) wire this inventory in as an OPTIONAL stage that runs only when `--report-dir <dir>` is supplied AND only after `validate_pptx_contract` has passed: the JSON is written to `<report-dir>/inventory.json` (same JSON contract as the standalone invocation), and a non-zero exit from the inventory subprocess (invocation error OR any finding) fails the pipeline closed. When `--report-dir` is omitted, the pipeline does not add the inventory stage and produces no inventory file anywhere — the inventory remains a strict side-output of the report directory, not a default repo artifact. A standalone conversion report that ALSO confirms every text run is editable end-to-end is still TODO; that piece depends on the full-inventory editability checks above and on a separate writer that combines the inventory with the per-slide rendering pipeline.

## TODOs

- Define palette → theme slot mapping.
- Cover the remaining `render_model` primitive → native PPTX object mapping: `chart_placeholder` → blank chart frame. Today the exporter maps `text` → text frame, `shape` → native PPTX shape, `line` → native line / connector, `image_slot` → native `<p:pic>` (PNG / JPG / JPEG manifest entries) OR placeholder rectangle (everything else), `kpi` → composite text frame with stacked paragraphs, `table` → native `<p:graphicFrame>` / `<a:tbl>` with editable cells; `chart_placeholder` fails closed.
- Implement native-object / full-inventory editability / determinism / layouts.scope / primitives.scope checks inside `scripts/validate_pptx_contract.py`. Today these are explicitly TODO. (`relationships.allow_list`, `media.targets_internal`, `media.inventory`, and `media.embedded_only` are now implemented.)
- Decide whether speaker notes round-trip.
- SVG embedding remains TODO. PowerPoint requires a PNG fallback alongside any SVG `<svg+xml>` blip + an SVGBlip extension; pulling that in safely (without expanding the SVG sanitizer surface) is a separate slice. Today SVG manifest entries fall back to the placeholder rectangle.
