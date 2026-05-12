---
name: editable-ppt
description: Internal clean-room skill that turns prompts, reports, or Markdown into editable PowerPoint decks through a planned pipeline. Invoke when the user asks to scaffold, plan, validate, or extend deck-generation artifacts in this repo.
status: scaffold
---

# editable-ppt

## Status

Scaffold + expanded vertical slice. The pipeline is defined, the on-disk contracts are sketched, and the render-model stage produces output for the controlled `text` / `line` / `shape` / `image_slot` / `kpi` primitive set across `cover`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `kpi_dashboard`, `timeline`, `agenda`, and `conclusion`. An SVG preview stage renders those render-models into per-slide `*.svg` files under `svg_previews/`; SVG is **preview / inspection** only, not the source language for PPTX. The **expanded native editable PPTX export stage** (`scripts/export_pptx.py`) accepts render_models for the same nine layouts (primitives `text` / `line` / `shape` / `image_slot` / `kpi`; `image_slot` is rendered as a native placeholder shape — media embedding is intentionally TODO). Keep two phrasings distinct: the **render-model generator can produce** end-to-end render_models for those nine layouts from a slide_plan (`SUPPORTED_LAYOUTS` in `scripts/generate_render_models.py`), and the **PPTX exporter can consume** a render_model whose `layout` is one of those nine (`SUPPORTED_LAYOUTS` in `scripts/export_pptx.py`). Today both sets are the same; the exporter's slide-body emitter is layout-agnostic — it walks each render_model's `primitives` list — so widening the layout allow-list does not change how any single shape is rendered. Layouts that map to the `table` or `chart_placeholder` primitive kinds (e.g. `comparison_table`) remain unimplemented and are reported as `[SKIP] ... not implemented` by the render-model generator and fail closed at the exporter's layout gate. Charting, visual regression, image generation, full editability inventory, theme palette mapping, validator-side layout/primitive-scope inspection of the produced PPTX, media inventory, and CLI integration are not implemented yet. See per-file TODOs and `references/`.

## Adaptive deck shape

There is **no universal deck structure** and no fixed slide count. The planner decides shape from the user request and source material:

- `deck_brief` is derived from the user request / source bundle. `deck_brief.source_refs` is required and non-empty so every slide can reference the source bundle.
- `deck_plan` chooses the deck's **target length**, **section structure**, **slide layouts**, and **density**.
- Expected capacity range is **12–25 slides** as guidance, not a contract. A real run may produce 6, 8, 10, 15, 20, 25, or another reasonable count depending on the brief.
- Different scenarios use different structures — e.g. executive summary, product proposal, technical solution, project review, research report, training deck, strategy memo. None of them is "the" canonical sequence.
- The `business_review` layout family is the **first** (initial scaffold) template family, not the product's identity. Future template families may share, drop, or replace any of its layouts.

### Planner contract (machine-enforced)

The validators cross-check the planner contract without imposing a maximum slide count or a required layout sequence:

- `deck_plan.planning.planned_slide_count` must equal `len(deck_plan.slides)`; `planning.rationale` is a required short string.
- `deck_plan.sections[]` (each with `id`, `title`, `summary`, `slide_indices`) partitions the deck: union of all `slide_indices` equals the set of `slides[].index`, with no duplicates across sections, no missing deck indices, and no orphan section indices.
- Every `slides[]` entry carries `section_id` (must exist and list this slide's `index`), `summary`, `density` (`low` / `medium` / `high`), and a non-empty `source_refs` whose values are all declared in `deck_brief.source_refs`.

## Pipeline (invariants)

1. source prompt / report / Markdown
2. → `deck_brief.json`
3. → `deck_plan.json` (adaptive length, structure, layouts, density)
4. → `design_system.json`
5. → per-slide `slide_plan.json`
6. → `image_manifest.json`
7. → per-slide `render_model.json` (controlled primitives — text / shape / line / image_slot / table / kpi / chart_placeholder — with bounds and token-only style refs)
8. → per-slide SVG
9. → SVG validation / repair
10. → editable PPTX export
11. → security / editability / visual reports

Hard invariants (must remain true as the skill grows):

- `deck_plan` is produced **before** any render model or SVG.
- A per-slide plan precedes that slide's render model, and a slide's render model precedes that slide's SVG and PPTX shapes.
- The `render_model` is the **only** input to the SVG renderer and the PPTX exporter; neither stage may read `slide_plan.json` directly. This is why the controlled primitive contract — closed kind enum, required bounds, token-only style refs, no arbitrary SVG-like fields — cannot be bypassed.
- SVG preview / inspection is the contract gate between render_model and PPTX, and is **partially implemented**: `scripts/generate_svg_previews.py` (renderer) + `check_svg_previews` in `scripts/validate_workspace.py` (validator) run today for every render_model the generator currently produces (i.e. every slide whose layout is in `cover`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `kpi_dashboard`, `timeline`, `agenda`, `conclusion`) and cover the primitive kinds `text`, `line`, `shape`, `image_slot`, `kpi`. The gate fails closed for those slides and must not be skipped. Slides whose layout the render-model generator does not yet produce — i.e. layouts mapped to the `table` or `chart_placeholder` primitive kinds (`comparison_table`, anything chart-bearing) — have no `render_model.json` and therefore no SVG preview; extending the gate to those slides requires extending the render-model generator first. SVG repair (clipping out-of-bounds shapes, font fallback) and glyph-level text-overflow detection remain TODO (see `references/svg-design-rules.md`). SVG is **not** the source language for PPTX — `scripts/export_pptx.py` consumes the same `render_model` directly and emits native PowerPoint objects. This repo is intentionally not a generic SVG-to-PPTX converter.
- The main output is an **editable** PPTX. No all-image-on-a-slide outputs.
- D-One (or any image generator) supplies **local image assets only** — never full-slide screenshots.
- Security checks fail closed.

## What exists in this repo today

- Root docs: `SKILL.md`, `README.md`, `SECURITY.md`, `.gitignore`.
- `references/` — policy and contract documents.
- `schemas/` — JSON Schemas for the five core artifacts (`deck_brief`, `deck_plan`, `design_system`, `slide_plan`, `image_manifest`), the per-slide `render_model`, and the template-side schemas (`template`, `theme`, `layout`).
- `templates/layouts/business_review/` — **first** template family (initial scaffold). Template + theme + 10 layout skeletons. Theme `font_family` is a CSS-style fallback chain. Layouts may declare optional `bounds` (per slot) and `primitive_kind` (slot → render-model primitive mapping); the minimal scaffold sets these on `cover` and `kpi_dashboard` so the contract is exercised. Other layouts keep them optional. Additional template families are expected later and may declare a different set of layouts.
- `examples/synthetic_20_page_business_review/` — **upper-range stress-test fixture**: synthetic input, schema-valid fixtures for `deck_brief`, `deck_plan`, `design_system`, `image_manifest`, a `slide_plans/` set covering every slide in this fixture's `deck_plan`, the synthetic SVG assets referenced by the manifest under `assets/`, generator-produced `render_models/` for every supported layout that appears in this fixture (19 of 20 slides today — `comparison_table` at slide 11 is the one unsupported layout, intentionally left out), and the matching SVG previews under `svg_previews/`. This is **one** fixture at the upper end of the capacity range, not the canonical or default deck shape.
- `examples/synthetic_8_page_product_brief/` — **smaller synthetic fixture** at the lower end of the range: an 8-slide product-brief deck reusing the `business_review` template family. Includes generator-produced `render_models/*.json` and matching `svg_previews/*.svg` files for every supported layout in this fixture (`01_cover`, `02_executive_summary`, `03_key_message`, `04_two_column`, `05_kpi_dashboard`, `06_timeline`, `07_two_column`, `08_conclusion`). Demonstrates that the pipeline does not assume any single deck length.
- `scripts/generate_render_models.py` — stdlib-only, deterministic generator for the per-slide `render_model`. Supports the layouts reachable from the controlled `text` / `line` / `shape` / `image_slot` / `kpi` primitive set: `cover`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `kpi_dashboard`, `timeline`, `agenda`, `conclusion`. Layouts mapped to the `table` or `chart_placeholder` primitive kinds (e.g. `comparison_table`) are reported as `[SKIP] … not implemented`, never as success. Reads the existing pipeline artifacts in a workspace; never invents source content; fails closed on missing / malformed inputs, unsafe `deck_plan.template`, unknown `image_ref`, malformed kpi entries, missing required slide_plan block, list slots with empty / non-string content, schema-invalid output, or workspace cross-check failure.
- `scripts/generate_svg_previews.py` — stdlib-only, deterministic SVG preview renderer. Reads `<workspace>/render_models/*.json` and writes `<workspace>/svg_previews/<stem>.svg` for each. Consumes `render_model.json` only — does NOT read `slide_plan.json`, so the controlled primitive contract cannot be bypassed. Supports the primitive kinds the generator emits today (`text`, `line`, `shape`, `image_slot`, `kpi`); every other kind (`table`, `chart_placeholder`, future kinds) fails closed on that slide. Resolves `palette.*` (resolved value must match `^#[0-9A-Fa-f]{6}$`) and `typography.heading|body` (`font_family` must match the CSS fallback pattern) through `design_system.json` — including the background `<rect>` so no direct dict bypass exists; image refs through `image_manifest.json` whose `local_path` must pass the same path-safety rule the workspace validator enforces. **Preflight** (runs before cleanup): `design_system.json` and `image_manifest.json` are schema-validated and every manifest `local_path` is run through `local_path_is_safe`; preflight failure exits non-zero, prints no `OK:`, and does NOT delete pre-existing `svg_previews/*.svg`. Sweeps stale `*.svg` before regeneration (non-SVG files preserved) and re-runs the same `check_svg_previews` gate the workspace validator uses, so output drift fails immediately.
- `scripts/validate_artifacts.py` — stdlib-only structural validator (subset of JSON Schema; full validation is TODO).
- `scripts/validate_scaffold.py` — stdlib-only scaffold runner. **Discovers** example workspaces under `examples/` (anything with `deck_plan.json` + `slide_plans/`) and runs the positive / per-workspace checks against each, so no example name and no fixed slide count is hardcoded. It exercises positive fixtures (including any `render_models/*.json` the workspace ships, against `render_model.schema.json`), negative cases, path-safety on `image_manifest.local_path` **and** `template.theme_ref` (rejecting **any URI-like scheme prefix** matching `^[A-Za-z][A-Za-z0-9+.\-]*:` — `http://`, `https://`, `file://`, `s3://`, `ftp://`, `data:`, `mailto:`, `javascript:`, etc., including Windows drive prefixes like `C:\...` / `D:/...` which match the same shape — plus POSIX-absolute, leading-backslash, protocol-relative `//host/...`, `..` segments, and the empty string), **media resolution (every `local_path` must exist; every `slide_plan.image_refs` id must be declared)**, layout-aware slide-plan coverage, **planner semantics** (the same cross-artifact rules as the workspace validator: `planning.planned_slide_count` matches `len(slides)`, sections partition slide indices, `slides[].section_id` resolves and lists this index, `slides[].source_refs` declared in `deck_brief.source_refs`), the template/theme/layout cross-check (including `template.name` matching its directory, and `theme_ref` not escaping the template dir), and a **render-model schema-level negative loop** that builds a clean baseline render_model and proves the schema rejects every required mutation: unsupported `kind` (`svg`, `foreignObject`), missing `bounds`, invalid token refs (no prefix, wrong domain, unknown typography role), `image_ref` carrying an `http://` / `https://` / `file://` / `data:` URI / POSIX-absolute / path-traversal / Windows drive prefix, and arbitrary SVG-like fields on a primitive or at the root (`transform`, `viewBox`, `href`, `xlink_href`, `foreignObject`, `filter`, `xmlns`, `defs`, `path`). Layout-aware negative mutations pick fixtures by layout name from any discovered workspace rather than hardcoding a file path. The theme load is **gated** on the `theme_ref` guards in two stages: a string-only `local_path_is_safe` check runs first and short-circuits before any filesystem call, then the within-template-dir resolve check runs, and only then can the theme file be opened. An unsafe `theme_ref` never reaches `Path.resolve()` or any file read.
- `scripts/export_pptx.py` — stdlib-only, deterministic, fail-closed PPTX exporter. Reads `<workspace>/render_models/*.json` (sorted by file stem) and writes one editable `.pptx` to `--output`. Supports layouts `cover`, `kpi_dashboard`, `agenda`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `timeline`, `conclusion`; primitive kinds `text` (editable text frame), `line` (native `<p:cxnSp>` connector), `shape` (native `<p:sp>` with prstGeom rect / roundRect / ellipse), `kpi` (editable `<p:sp>` text frame with stacked label / value / optional delta paragraphs), and `image_slot` (native placeholder rectangle whose `<a:txBody>` carries the `image_manifest` alt_text — media embedding is intentionally TODO). The slide-body emitter is layout-agnostic: it walks each render_model's `primitives` list and emits one native PPTX object per primitive, so widening the layout allow-list does not change how any single shape is rendered. `comparison_table` is intentionally NOT in the allow-list because it requires the still-unsupported `table` primitive. Fails closed on: workspace not a directory, output extension other than `.pptx` (case-insensitive), design_system / image_manifest failing their schemas, image_manifest entry with an unsafe `local_path`, missing or empty `render_models/`, render_model failing `render_model.schema.json`, render_model canvas not matching `design_system.grid`, primitive kind `table` / `chart_placeholder` / other unsupported, `image_slot.image_ref` not declared in `image_manifest`, palette / typography token resolving to a non-hex / non-CSS-chain value (defense-in-depth gate mirroring the SVG renderer). A render_model whose layout is outside the SUPPORTED_LAYOUTS allow-list above fails closed with a per-slide error and aborts the whole run; no partial `.pptx` is written. The contract is intentionally all-or-nothing. The output ZIP uses a fixed timestamp (1980-01-01) and shape ids starting at 2 for reproducibility. `--self-test` builds a synthetic workspace under `tempfile.TemporaryDirectory()` and exercises every fail-closed gate plus two positives that re-check the produced `.pptx` against `validate_pptx_contract.check_container` and `check_generated_pptx` (a happy-path cover + kpi_dashboard deck and an expanded-layout `two_column` deck). There is also a `--render-model <path>` debug entry that exports a single render_model; the primary path is `--workspace`.
- `scripts/validate_pptx_contract.py` — stdlib-only, fail-closed validator that grows alongside `scripts/export_pptx.py`. In skeleton mode (no `--pptx`) it reports the TODO surface only (full-inventory editability, no-image-only-slides full inventory, embedded-only media, media inventory, theme palette mapping, determinism, validator-side layout scope, validator-side primitive scope). With `--pptx <path>` it runs the basic OOXML container checks (file exists, `.pptx` extension, readable ZIP, required package entries `[Content_Types].xml` / `_rels/.rels` / `ppt/presentation.xml`) AND the **minimal-evidence** layer: `slide_count.inspectable` (counts `ppt/slides/slide{N}.xml` parts, zero is FAIL), `relationships.no_external` (no `TargetMode="External"`, no URI-scheme prefix on `Target`), `relationships.no_file_uri` (no `Target` starting with `file://`), `relationships.allow_list` (every `Relationship` `Type` URL is one of the canonical OOXML rel URLs `officeDocument`, `slide`, `slideMaster`, `slideLayout`, `theme`), `package.no_macros` (no `ppt/vbaProject.bin`, no `vbaProject` content type), `package.no_ole` (no `ppt/embeddings/*`, no `oleObject` content type), `package.no_activex` (no `ppt/activeX/*`, no `activeX` content type), `minimal_evidence.editable_text` (at least one slide carries a `<p:txBody>` with a non-empty `<a:t>` run — minimal evidence only), `minimal_evidence.not_all_image_slide` (every slide that carries a `<p:pic>` also carries at least one `<p:sp>`/`<p:cxnSp>` — minimal evidence only), `minimal_evidence.no_blank_slide` (every slide carries at least one `<p:sp>`/`<p:cxnSp>`/`<p:pic>`; an empty `<p:spTree>` fails closed — minimal evidence only; this gate is what catches a deck where slide 1 is editable but slide 2 is structurally empty), and `minimal_evidence.every_slide_has_native_shape` (every slide carries at least one native editable `<p:sp>`/`<p:cxnSp>` structure — minimal evidence only, the single positive statement of "every slide has at least one native editable structure"). `--self-test` exercises tempfixture negatives for every gate (missing file, wrong extension, non-zip content, empty ZIP, ZIP missing `ppt/presentation.xml`, external rel, `file://` rel, unexpected relationship `Type`, `vbaProject.bin`, `oleObject1.bin`, `activeX1.xml`, all-image slide (fails both `not_all_image_slide` and `every_slide_has_native_shape`), no editable text, editable+blank deck) plus two positives (minimal valid container, minimal editable PPTX). A passing `--pptx` run proves the container shape, the absence of macro / OLE / ActiveX parts and external / `file://` relationships, the relationship `Type` allow-list, and minimal evidence of editable native content on every slide; it does NOT prove the deeper TODO surface. See `references/pptx-conversion-rules.md` and `references/quality-gates.md`.
- `scripts/validate_workspace.py` — stdlib-only, fail-closed validator for an **arbitrary** workspace (the path is caller-supplied via `--workspace`, with templates discovered via `--template-root`). Missing or malformed required artifacts now report `[FAIL]` with no traceback. The runner checks: schemas; the `deck_plan.template` chain into the template-root; **full template validation** (`template.name` matches its directory, `theme_ref` passes the two-stage gate, theme file exists and validates against `theme.schema.json`, every declared layout file exists, validates against `layout.schema.json`, and its file stem matches `layout["name"]`); **strict 1:1 slide_plan/deck_plan coverage** (duplicate `deck_plan` indices, duplicate `slide_plan` indices, orphan `slide_plan` indices, and missing indices all fail — neither side may silently collapse duplicates); per-slide layout-slot coverage; **planner semantics** (`planning.planned_slide_count` equals `len(deck_plan.slides)`, sections partition the set of slide indices, every `slides[].section_id` resolves to an existing section that lists the slide's index, every `slides[].source_refs` value is declared in `deck_brief.source_refs`); image_manifest path-safety; media resolution inside the workspace; `slide_plan.image_refs` consistency; and (when the workspace ships any) **render-model validation**: each `render_models/*.json` validates against `render_model.schema.json` and then crosses with `deck_plan` (index/layout), `design_system` (canvas equals grid), `deck_brief` (source_refs subset), `image_manifest` (image_ref declared), and the chosen template's layouts (slot_id resolves; `slot.primitive_kind` or default `slot.type` → primitive mapping matches; `slot.bounds` contain the primitive's bounds); per primitive it also enforces bounds-inside-canvas, kind/payload alignment, palette-token resolution, and a defensive URI-scheme walker over reference fields. The validator also enforces a **render-model coverage gate** (`check_generator_render_model_coverage`): once a workspace ships any `render_models/*.json`, every deck_plan slide whose layout is in the render-model generator's `SUPPORTED_LAYOUTS` set must have a matching render_model on disk. Slides whose layout is **not** in that set (today only `comparison_table`) are allowed to have no render_model. The check imports `SUPPORTED_LAYOUTS` lazily from `scripts/generate_render_models.py` so the two stay in sync, and is fully adaptive — no example name, slide count, or template name is hardcoded. **SVG-preview validation** also runs whenever `render_models/` ships: every `render_models/<stem>.json` must have a matching `svg_previews/<stem>.svg`, each SVG must parse, declare a root `<svg>` whose `viewBox` matches the render_model canvas, carry no `<foreignObject>`, route every `href` / `xlink:href` / `src` value through the same path-safety rule as `image_manifest`, name an `image_manifest` `local_path` for every `<image>` href, keep every `<rect>` / `<image>` / `<ellipse>` / `<circle>` / `<line>` with numeric geometry inside the canvas, and keep every `<text>` with numeric `x`/`y` anchor inside the canvas. The validator does NOT enforce a `<text>` width / height / wrapping box — that needs font metrics this stdlib-only validator does not carry and remains a TODO in `references/svg-design-rules.md`. Built-in negative tests cover unsafe schemes, absolute paths, path traversal, missing media, unknown layouts, missing/orphan/duplicate slide_plans, required-slot mismatches, and wrong block kinds. A separate tempfixture suite proves detection of missing theme files, invalid theme schemas, invalid layout schemas (extra field), missing declared layout files, duplicate slide_plan indices, missing `deck_plan.json` (no traceback), each planner-semantics rule (planned-count mismatch, missing / duplicate-across-sections / orphan section indices, unknown / mis-listed slide `section_id`, undeclared slide `source_refs`), each render-model rule (unsupported `kind`, missing `bounds`, invalid token refs, external URL / `file://` / absolute path / path traversal in `image_ref`, arbitrary SVG-like fields, kind / payload mismatch, bounds outside canvas, unknown `slot_id`, `slot.primitive_kind` mismatch, `image_ref` not in manifest, unknown palette token, duplicate primitive ids), and each SVG-preview rule (missing svg, malformed XML, wrong root, viewBox mismatch, `<foreignObject>` present, unsafe `href` of every shape, undeclared `<image>` href, element outside canvas; plus generator-side fail-closed on unsupported primitive kind, unknown palette token, image_slot resolving to unsafe manifest `local_path`, and missing `render_models/`). Tempfixtures are built under `tempfile.TemporaryDirectory()` so no synthetic data leaks into the repo.

## What is NOT implemented yet

- Render-model generation for layouts mapped to the `table` or `chart_placeholder` primitive kinds. `scripts/generate_render_models.py` covers `cover`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `kpi_dashboard`, `timeline`, `agenda`, `conclusion`; layouts like `comparison_table` and any chart-bearing layout are listed as `[SKIP] … not implemented` and are **not** claimed as success.
- SVG rendering for primitive kinds outside the five supported today (`text`, `line`, `shape`, `image_slot`, `kpi`). `table` and `chart_placeholder` fail closed at render time; they are absent from current generator output, so the pipeline succeeds for the supported subset.
- SVG repair (clipping out-of-bounds elements, font fallback, density thresholds — see `references/svg-design-rules.md` TODOs).
- Full PPTX generation. The expanded vertical slice (`scripts/export_pptx.py`) covers layouts `cover`, `kpi_dashboard`, `agenda`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `timeline`, `conclusion`; primitive kinds `text` / `line` / `shape` / `image_slot` / `kpi`. Out of scope (fail-closed in the exporter, TODO in the deeper validator):
  - PPTX emission for `table` and `chart_placeholder` primitives;
  - PPTX emission for `comparison_table` (gated behind the still-unsupported `table` primitive) or for any other future layout outside the SUPPORTED_LAYOUTS allow-list;
  - media embedding inside the package (`image_slot` primitives are emitted as native placeholder rectangles carrying the `image_manifest` alt_text — no PNG / JPG / SVG bytes are copied to `ppt/media/`, and no media relationships are written);
  - PPTX theme palette mapping back into a deck-plan-driven theme;
  - validator-side full-inventory editability, media inventory, theme palette mapping, determinism, layout-scope, and primitive-scope checks inside `scripts/validate_pptx_contract.py` (today the validator runs container checks plus minimal-evidence checks for safety / editability surface area and the relationship `Type` allow-list, with the editability / media-inventory layers reported as MINIMAL EVIDENCE / TODO).
- D-One integration of any kind.
- Chart rendering or chart templates. The `chart_placeholder` primitive reserves the slot only; it carries no chart data.
- Visual regression.
- Qoder CLI integration.
- Public network behavior, telemetry, voiceover, video, complex animation.

Do not document any of the above as "working". If a task needs one, mark it as a blocker.

## Path handling

Project workspaces are user-provided. Scripts must accept arbitrary paths. Do not hardcode `projects/<name>`.

## Verification available today

Seven stdlib-only commands run:

```
# Single-artifact structural check (subset of JSON Schema). Any
# example workspace may be substituted for the path below.
python3 scripts/validate_artifacts.py \
  --schema schemas/deck_brief.schema.json \
  examples/synthetic_20_page_business_review/deck_brief.json

# Full scaffold check: schemas, negative cases, image_manifest path-safety
# (including any URI-like scheme prefix), layout-aware slide_plan coverage,
# and the two-stage fail-closed template/theme/layout cross-check. Runs
# against every example workspace under examples/ that contains the
# expected files — no example is hardcoded.
python3 scripts/validate_scaffold.py

# Arbitrary-workspace check: validates a caller-supplied workspace
# against the schemas, the template chain, full slide-plan coverage of
# the deck plan, per-slide layout-slot coverage, image path-safety,
# media resolution inside the workspace, image_refs consistency, and
# (when the workspace ships any) render_models against
# render_model.schema.json plus the controlled-primitive cross-checks.
# Works on any deck length; the upper-range fixture below is one
# example, the 8-page fixture is another.
python3 scripts/validate_workspace.py \
  --workspace examples/synthetic_20_page_business_review \
  --template-root templates/layouts

python3 scripts/validate_workspace.py \
  --workspace examples/synthetic_8_page_product_brief \
  --template-root templates/layouts

# Render-model generation. Supported layouts today: cover,
# section_divider, executive_summary, key_message, two_column,
# kpi_dashboard, timeline, agenda, conclusion (every emit uses only
# the controlled text / line / shape / image_slot / kpi primitives).
# Layouts mapped to the table or chart_placeholder primitive kinds
# (e.g. comparison_table, anything chart-bearing) are listed as
# [SKIP] ... not implemented and are NOT counted as success.
# Re-runs the same render_model cross-check the workspace validator
# uses, so output drift fails immediately.
python3 scripts/generate_render_models.py \
  --workspace examples/synthetic_20_page_business_review \
  --template-root templates/layouts

python3 scripts/generate_render_models.py \
  --workspace examples/synthetic_8_page_product_brief \
  --template-root templates/layouts

# SVG preview generation. Reads <workspace>/render_models/*.json and
# writes <workspace>/svg_previews/<stem>.svg for each. Supports the
# primitive kinds the render-model generator emits today (text, line,
# shape, image_slot, kpi); every other kind fails closed. Re-runs the
# same check_svg_previews gate the workspace validator uses, so output
# drift fails immediately.
python3 scripts/generate_svg_previews.py \
  --workspace examples/synthetic_20_page_business_review \
  --template-root templates/layouts

python3 scripts/generate_svg_previews.py \
  --workspace examples/synthetic_8_page_product_brief \
  --template-root templates/layouts

# Expanded native editable PPTX export. Reads
# <workspace>/render_models/*.json (sorted by file stem) and writes
# a deterministic .pptx covering the supported subset (layouts cover,
# kpi_dashboard, agenda, section_divider, executive_summary,
# key_message, two_column, timeline, conclusion; primitives text /
# line / shape / image_slot / kpi). `table`, `chart_placeholder`,
# comparison_table, every other layout outside the allow-list, wrong
# --output extension, malformed render_model, undeclared image_ref,
# and unsafe manifest local_path all fail closed. --self-test
# exercises every gate against a synthetic workspace under
# tempfile.TemporaryDirectory().
python3 scripts/export_pptx.py \
  --workspace examples/synthetic_8_page_product_brief \
  --output /tmp/szh-ppt-master-smoke/synthetic_8_page_product_brief.pptx

python3 scripts/export_pptx.py --self-test

# PPTX contract + minimal-evidence validator. In skeleton mode it
# reports the TODO surface only. With --pptx it runs the basic OOXML
# container checks AND the minimal-evidence layer (slide count, no
# external rels, no file:// rels, relationship Type allow-list,
# no macros / OLE / ActiveX parts, at least one editable text run,
# no all-image slide, no blank slide, every slide has at least one
# native editable structure). --self-test exercises every gate
# against tempfixture negatives plus a minimal-valid-container
# positive and a minimal-editable PPTX positive.
python3 scripts/validate_pptx_contract.py
python3 scripts/validate_pptx_contract.py --self-test
python3 scripts/validate_pptx_contract.py --pptx \
  /tmp/szh-ppt-master-smoke/synthetic_8_page_product_brief.pptx
```

All commands exit non-zero if any check disagrees, including built-in negative cases (e.g. unsafe `http://` / `s3://` / `data:` paths must be rejected, dropping a required layout slot must be detected, an orphan slide_plan must be detected, a render_model that uses an unsupported `kind` must be rejected, the generator must fail closed on an unknown `image_ref`, an SVG preview missing for a render_model or carrying a `<foreignObject>` / unsafe `href` / `<text>` anchor outside the canvas must fail, an `.pptx` carrying an external relationship / `file://` Target / unexpected relationship `Type` / vbaProject / OLE / ActiveX part / all-image slide / no editable text / blank slide must be rejected). SVG-preview generation and validation are implemented for the supported primitive subset (`text`, `line`, `shape`, `image_slot`, `kpi`) and only run against render_models the generator produces today (the 9 supported layouts above); slides whose layout maps to the `table` or `chart_placeholder` primitive kinds have no render_model and no SVG preview yet. The PPTX exporter covers the same 9 layouts and emits native editable shapes (text frames, connectors, preset shapes); `image_slot` is rendered as a native placeholder rectangle with alt_text (media embedding is TODO). `validate_pptx_contract.py --pptx` reports a passing run as `OK (container + minimal-evidence)` and explicitly names the full-inventory editability, media inventory, theme palette mapping, determinism, layout-scope, and primitive-scope checks that remain TODO. SVG repair, full PPTX coverage, security scan, visual regression, and SVG / render-model coverage for the `table` / `chart_placeholder`-mapped layouts and primitive kinds remain TODO until their scripts exist.
