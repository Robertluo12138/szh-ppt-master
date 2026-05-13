# szh-ppt-master

Internal, local, clean-room skill for turning a prompt, report, or Markdown source into an editable PowerPoint deck through a controlled pipeline.

This README is for maintainers. End-user / agent behavior is described in `SKILL.md`.

## Current state

Scaffold + expanded vertical slice. The directory layout, the JSON-Schema contracts for the five core artifacts plus a per-slide **controlled render model**, a **first** template-family skeleton (`business_review`), a **deterministic render-model generator** that covers every layout reachable from the controlled text / line / shape / image_slot / kpi / table primitive set (`cover`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `kpi_dashboard`, `timeline`, `agenda`, `conclusion`, `comparison_table`), a **minimal SVG preview generator + validator** built on top of the render-model output, and an **expanded native editable PPTX exporter** that consumes render_models for the same ten layouts all exist. The generator-supported and exporter-supported layout sets are deliberately the same today — the exporter can consume any render_model the generator can produce. D-One image generation, full PPTX coverage (every layout, every primitive, embedded media, full editability inventory, theme palette mapping, determinism inventory, layout/primitive-scope inspection of the produced PPTX, media inventory), `chart_placeholder` rendering, and Qoder CLI integration are not implemented.

The `render_model` contract is the intermediate the SVG renderer and the PPTX exporter both consume directly. It locks the renderable surface to a closed set of owned primitives (`text`, `shape`, `line`, `image_slot`, `table`, `kpi`, `chart_placeholder`) with required bounds and token-only style references; arbitrary SVG-like fields are rejected at the schema level. **The repo separates two questions:** which layouts the **generator can produce end-to-end** from a slide_plan, and which layouts the **exporter can consume** from a render_model. Today both sets are the same ten — `cover`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `kpi_dashboard`, `timeline`, `agenda`, `conclusion`, `comparison_table` — every layout reachable from the `text` / `line` / `shape` / `image_slot` / `kpi` / `table` primitive subset. `scripts/generate_render_models.py` reads an existing workspace and emits `render_models/*.json` for slides whose layout is in that supported set; slides with any other layout — notably those whose required slot maps to the `chart_placeholder` primitive_kind — are reported as not implemented and skipped, never claimed as success. `scripts/generate_svg_previews.py` then turns each `render_models/*.json` into a deterministic per-slide SVG under `svg_previews/`, supporting the primitive kinds the generator emits today (`text`, `line`, `shape`, `image_slot`, `kpi`, `table`); every other kind fails closed on that slide. `scripts/export_pptx.py` is driven by `deck_plan.json`: it iterates `deck_plan.slides[]` in declared order, resolves each entry to its canonical `render_models/<idx:02d>_<layout>.json`, and writes one editable `.pptx` for any render_model whose layout is in the exporter's allow-list. A `deck_plan` declaring N slides whose `render_models/` is missing one file (or carries an orphan file `deck_plan` did not name) fails closed at the 1:1 coverage gate before any output is produced. The exporter's slide-body emitter is layout-agnostic — it walks each render_model's `primitives` list — so widening the layout allow-list does not change how any single shape is rendered. The `table` primitive is exported as a native `<p:graphicFrame>` wrapping `<a:tbl>` (one `<a:gridCol>` per column, bold header row, editable `<a:txBody>` per cell), so every cell is directly editable in PowerPoint without media embedding. Unsupported primitives (`chart_placeholder`), any layout outside the exporter's allow-list, wrong output extension, malformed render_models, undeclared image refs, and unsafe manifest paths all fail closed. The contract is intentionally all-or-nothing: a render_model with an out-of-scope layout aborts the run with a per-slide error and no partial deck is written. `image_slot` primitives are exported as native placeholder rectangles carrying the `image_manifest` alt_text — media embedding (copying PNG / JPG / SVG bytes into `ppt/media/`) is intentionally TODO. SVG remains a **preview / inspection** layer — the PPTX exporter does not parse SVG, it builds native OOXML from the render_model directly. The PPTX contract validator (`scripts/validate_pptx_contract.py`) now enforces a `relationships.allow_list` over the canonical OOXML rel types the exporter emits and a `minimal_evidence.every_slide_has_native_shape` positive gate; media inventory, full editability inventory, theme palette mapping, determinism inventory, and validator-side layout/primitive-scope inspection of the produced PPTX all remain TODO. D-One, the remaining PPTX coverage (`chart_placeholder` / embedded media), and Qoder behavior remain unimplemented and are documented as such.

## Deck shape is adaptive

There is no fixed deck length and no universal slide sequence. The planner derives a `deck_brief` from the user request / source bundle, and the `deck_plan` stage chooses target length, section structure, slide layouts, and density for that specific brief. Expected capacity range is **12–25 slides** as guidance; a run may produce 6, 8, 10, 15, 20, 25, or another reasonable count. Different scenarios (executive summary, product proposal, technical solution, project review, research report, training deck, strategy memo) use different structures. The `business_review` template family is the first scaffold template family, not the product's identity. The 20-page synthetic example below is one upper-range stress-test fixture, not the canonical deck.

## Layout

```
SKILL.md                # skill entry point, pipeline invariants, status
README.md               # this file
SECURITY.md             # privacy and security policy
.gitignore              # ignored generated outputs and local caches
references/             # source-of-truth policy and contract docs
schemas/                # JSON Schemas for the five core artifacts,
                        # the per-slide render_model, and the template /
                        # theme / layout schemas
templates/              # internal layout / theme skeletons
  layouts/business_review/   # first template family; more may be added
    template.json
    theme.json
    layouts/<layout>.json
examples/               # synthetic-only example workspaces of varying lengths
scripts/                # local deterministic tooling
projects/               # generated workspaces (not committed; created by users)
```

`projects/<name>` is **not** hardcoded anywhere. Scripts accept arbitrary workspace paths.

## Verification today

Eight stdlib-only Python commands are wired up — four validators (`validate_artifacts.py`, `validate_scaffold.py`, `validate_workspace.py`, `validate_pptx_contract.py`), two deterministic generators (`generate_render_models.py`, `generate_svg_previews.py`), a deterministic PPTX exporter (`export_pptx.py`), and a deterministic local pipeline runner (`run_pipeline.py`) that chains validate → generate render_models → generate SVG previews → export PPTX → validate the produced PPTX for a prepared workspace. No third-party dependencies are required. `validate_pptx_contract.py` now gates the produced `.pptx` at the container level **and** with a minimal-evidence safety / editability layer (slide count, no external rels, no `file://` rels, relationship `Type` allow-list over the canonical OOXML rel URLs, no macros / OLE / ActiveX parts, at least one editable `<a:t>` run, no all-image slide, no blank slide, every slide carries at least one `<p:sp>` or `<p:cxnSp>`); full-inventory editability, the media inventory, theme palette mapping, determinism, and validator-side layout / primitive scope all remain TODO and are explicitly named that way in every run.

### Single-artifact structural validation

```
python3 scripts/validate_artifacts.py \
  --schema schemas/deck_brief.schema.json \
  examples/synthetic_20_page_business_review/deck_brief.json
```

(Any example workspace can be substituted; the upper-range 20-page fixture is shown here, but any deck shape under `examples/` works the same way.)

The validator implements a **subset** of JSON Schema (`type`, `required`, `enum`, `pattern`, `minLength`/`maxLength`, `minimum`/`maximum`/`exclusiveMinimum`/`exclusiveMaximum`, `minItems`/`maxItems`, nested `properties`, `additionalProperties` boolean or schema, and `items` as a single subschema). Full JSON-Schema validation is TODO and the script labels its output `(subset)`.

### Scaffold validation runner

`scripts/validate_scaffold.py` exercises every check the scaffold currently supports in one pass:

```
python3 scripts/validate_scaffold.py
```

It runs:

- **Positive:** every synthetic fixture under each example workspace in `examples/` (currently `synthetic_20_page_business_review` — the upper-range stress-test fixture — and `synthetic_8_page_product_brief` — a lower-range fixture) validates against its schema (`deck_brief`, `deck_plan`, `design_system`, each `slide_plan`, `image_manifest`, and — when the workspace ships any — each `render_models/*.json` against `render_model.schema.json`). The runner discovers workspaces by inspecting `examples/`; no example name is hardcoded.
- **Negative:** removing a required field from each artifact in memory must fail validation.
- **Path-safety:** workspace-relative paths only. Rejects the empty string, POSIX-absolute (`/...`), leading-backslash, protocol-relative (`//host/...`), **any URI-like scheme prefix** matching `^[A-Za-z][A-Za-z0-9+.\-]*:` (covers `http://`, `https://`, `file://`, `s3://`, `ftp://`, `data:`, `mailto:`, `javascript:`, and anything else of that shape — which also subsumes Windows drive prefixes like `C:\...`, `D:/...`, `c:foo`), and any path containing a `..` segment. Applied to both `image_manifest.local_path` and `template.theme_ref`.
- **Media resolution (fail-closed):** every `image_manifest` `local_path` must resolve to a real file under the workspace, and every `slide_plan.image_refs` entry must point to an id declared in the manifest. Enforces `references/security-policy.md` item 6.
- **Layout-aware slide plans:** every required slot declared by a template layout is covered by a matching block in the slide plan (`block.id == slot.id`, `block.kind == slot.type`). Negative cases prove that a dropped required block or a wrong block kind is detected.
- **Planner semantics:** the same machine-enforced planner contract as the workspace runner — `deck_brief.source_refs` required and non-empty, `planning.planned_slide_count` matches `len(slides)`, `sections[]` partition the deck's slide indices, every `slides[].section_id` resolves to an existing section that lists this index, and every `slides[].source_refs` value is declared in `deck_brief.source_refs`. The check runs against every discovered workspace; no slide-count or example name is hardcoded.
- **Template / theme / layout cross-check:** `template.json`, `theme.json`, and every layout file validate against their schemas; the template's `name` matches its containing directory; `theme_ref` passes a string-only path-safety check **and then** resolves to a path under the template directory; layout filenames match the declared `name`; and the template's `layouts` list matches the files on disk. The `theme_ref` guards run in two stages and are **fail-closed**: stage 1 (`local_path_is_safe`) is string-only and short-circuits before any filesystem call; only a stage-1 pass allows stage 2 (which calls `Path.resolve()` to catch symlink escape), and only a stage-2 pass allows the theme file to be opened. The same gate shape is mirrored in the negative loop, so the stage-2 helper is never called on a string-unsafe `theme_ref`. A meta-check iterates every unsafe `theme_ref` in the negative list through the loader under recorders for `_resolves_within` and `_load`, and asserts both recorders stayed empty and the loader emitted its "NOT opened (fail-closed)" result every time. Other negative cases prove that unsafe `theme_ref` values and a `template.name` mismatch are rejected.
- **Render model schema-level negatives:** a clean in-memory baseline `render_model` validates, and every required negative mutation is rejected by the schema: unsupported `kind` (`svg`, `foreignObject`), missing `bounds`, invalid token refs (no prefix, wrong domain, unknown typography role), `image_ref` carrying an `http://` / `https://` / `file://` / `data:` URI / POSIX-absolute / path-traversal / Windows drive prefix, and arbitrary SVG-like fields on a primitive or at the root (`transform`, `viewBox`, `href`, `xlink_href`, `foreignObject`, `filter`, `xmlns`, `defs`, `path`). The schema's `additionalProperties: false` at every nested object plus the pattern restrictions on ids and token refs are what enforce this. The runtime cross-checks (kind/payload alignment, bounds inside canvas, slot resolution, image_ref vs manifest, palette token resolution) are exercised by `validate_workspace.py`'s tempfixtures.

Exit code is `0` only when every check (positives **and** negatives) behaves as expected.

### Workspace validator

`scripts/validate_workspace.py` validates an **arbitrary** workspace directory (the workspace path is caller-supplied; nothing is hardcoded). Pair it with a template-root directory containing the templates. The validator is agnostic to deck length — it works on a 6-slide deck or a 25-slide deck:

```
python3 scripts/validate_workspace.py \
  --workspace examples/synthetic_20_page_business_review \
  --template-root templates/layouts

python3 scripts/validate_workspace.py \
  --workspace examples/synthetic_8_page_product_brief \
  --template-root templates/layouts
```

It runs (every check is fail-closed; exit 1 on any failure):

- **Schemas:** every artifact in the workspace (`deck_brief.json`, `deck_plan.json`, `design_system.json`, `image_manifest.json`, and every `slide_plans/*.json`) loads and validates against its schema. Missing or malformed artifacts produce a `[FAIL]` line — never a Python traceback.
- **Template chain:** `deck_plan.template` is path-safe **and** resolves inside `--template-root`; every `deck_plan` slide layout is declared by the template's `layouts` list.
- **Template files (full):** the selected template's `template.json` validates against its schema; `template.name` matches its directory; `theme_ref` passes the two-stage path-safety + within-template-dir gate, the theme file exists, and `theme.json` validates against `schemas/theme.schema.json`; every declared layout has a `layouts/<name>.json` file that validates against `schemas/layout.schema.json` and whose file stem matches `layout["name"]`.
- **Slide-plan coverage (strict 1:1):** `deck_plan` slide indices must be unique (duplicates in `deck_plan.slides[].index` `[FAIL]` before any further analysis); every `deck_plan` slide has exactly one matching `slide_plan` file (matched by JSON `index`); duplicate `slide_plan` indices, orphan `slide_plan` indices (no deck_plan entry), and missing indices (deck_plan slide with no `slide_plan`) all `[FAIL]`. Every `slide_plan` agrees with its deck_plan entry on `index`/`layout`/`title`, and every required layout slot is covered by a matching `slide_plan` block (`block.id == slot.id`, `block.kind == slot.type`).
- **Planner semantics (machine-enforced contract):** `deck_brief.source_refs` is required and non-empty; `deck_plan.planning.planned_slide_count` equals `len(deck_plan.slides)`; `deck_plan.sections[].slide_indices` partition the set of `slides[].index` values (no duplicates across sections, no missing deck indices, no orphan section indices); every `slides[].section_id` resolves to an existing section that lists this slide's index; and every `slides[].source_refs` value is declared in `deck_brief.source_refs`. No maximum slide count and no required layout sequence is imposed.
- **Image manifest:** every `local_path` passes the same path-safety rule as `validate_scaffold.py` (any URI-like scheme prefix, absolute paths, leading-backslash, protocol-relative, `..` segments, and the empty string are rejected); every safe path resolves to a real file inside the workspace; every `slide_plan.image_refs` id is declared in `image_manifest`.
- **Render models (when present):** if the workspace ships any `render_models/*.json`, each validates against `schemas/render_model.schema.json` and then cross-checks against the rest of the workspace — index matches a `deck_plan` slide, layout matches that slide's layout, canvas equals `design_system.grid`, `source_refs` are declared in `deck_brief.source_refs`, primitive ids are unique, bounds fit inside the canvas, exactly one kind-specific payload field is present and matches `kind`, `slot_id` (when set) resolves to a layout slot whose `primitive_kind` (or the default `slot.type` → primitive mapping) matches and whose `bounds` (when declared) contain the primitive's bounds, `image_ref` is declared in `image_manifest`, palette tokens resolve to a `design_system.palette` key, and no reference-field string carries a URI-scheme prefix. The `render_models/` directory is optional today — workspaces that don't ship one are silently skipped.
- **Render-model coverage (anti-drift):** once a workspace ships at least one `render_models/*.json`, every deck_plan slide whose `layout` is in the render-model generator's `SUPPORTED_LAYOUTS` set must have a matching render_model on disk. A committed workspace cannot quietly ship a partial subset (e.g. `01_cover.json` only while the deck declares twenty supported slides). The check imports `SUPPORTED_LAYOUTS` from `scripts/generate_render_models.py` lazily so the two always agree, and is fully **adaptive** — no example name, no slide count, and no template name is hardcoded. Slides whose layout is **not** in the supported set are explicitly allowed to have no render_model; every layout declared by the business_review template skeleton is now in `SUPPORTED_LAYOUTS`. An empty `render_models/` directory still means "not yet generated" and does not trigger this check.
- **Render-model filename (canonical name):** every `render_models/*.json` file must be named `<index:02d>_<layout>.json`, where `index` and `layout` come from inside the JSON (zero-padded two-digit index, layout token verbatim — e.g. `02_agenda.json`, `09_two_column.json`). The PPTX exporter (`scripts/export_pptx.py`) iterates `deck_plan.slides[]` in declared order and resolves each entry to its canonical render_model filename, so a mis-named `99_agenda.json` whose JSON `index` is 2 fails closed at the deck_plan/render_models 1:1 coverage gate (the canonical `02_agenda.json` is missing, the mis-named file is orphan) before any output is produced. The validator fails closed with FAIL lines that name both the missing and the orphan filename. Schema-invalid files (no integer `index`, no string `layout`) are not double-flagged here — `check_render_models` already surfaces those. The generator always writes canonical names; this on-disk gate catches hand-edited or copied workspaces. This naming rule is render-model-specific and does not commit the broader workspace path layout — `slide_plans/` filename canonicalization remains TODO (see `references/slide-contracts.md`).
- **SVG previews (when render_models ship):** each `render_models/<stem>.json` must have a matching `svg_previews/<stem>.svg`. The SVG must parse, the root `<svg>` must declare a `viewBox` of `0 0 <width> <height>` matching the render_model canvas, no `<foreignObject>` may appear anywhere in the tree, every reference-bearing attribute (`href`, `xlink:href`, `src`, anything ending in `href`) must pass the same path-safety rule as `image_manifest.local_path` (no URI scheme, no POSIX-absolute, no leading backslash, no protocol-relative, no `..` segment, no empty string), every `<image>` href value must match a `local_path` declared in `image_manifest`, every `<rect>` / `<image>` / `<ellipse>` / `<circle>` / `<line>` with explicit numeric geometry must stay inside the canvas, and every `<text>` with numeric `x`/`y` must have its anchor point inside the canvas. The validator does **not** enforce a `<text>` width / height / wrapping box — that needs font metrics this stdlib-only validator does not carry, and is recorded as a TODO in `references/svg-design-rules.md`. Tempfixture negatives prove the validator catches each forbidden mutation (missing svg, malformed XML, wrong root, viewBox mismatch, `<foreignObject>` present, unsafe `href` of every shape, undeclared `<image>` href, `<rect>` outside canvas, `<text>` anchor outside canvas — both negative and beyond-edge).
- **Negative tests (in-memory + tempfixture):** the runner explicitly proves the validator detects unsafe schemes (`s3://`, `ftp://`, `data:`, `mailto:`, `javascript:`), absolute paths (POSIX, Windows drive, UNC), path traversal (`..` segments), missing media, unknown layouts, missing slide_plans, orphan slide_plans, duplicate `slide_plan` indices, **duplicate `deck_plan` indices** (no false-green), required-slot mismatches, wrong block kinds, missing theme files, invalid theme schemas, invalid layout schemas (extra fields), missing declared layout files, missing `deck_plan.json` (no traceback), every planner-semantics rule (planned-count mismatch, missing / duplicate-across-sections / orphan section indices, unknown / mis-listed slide `section_id`, undeclared slide `source_refs`), and every render-model rule (unsupported `kind`, missing `bounds`, invalid token refs, external URL / `file://` / absolute path / path traversal in `image_ref`, arbitrary SVG-like fields, kind / payload mismatch, bounds outside canvas, unknown `slot_id`, `slot.primitive_kind` mismatch, `image_ref` not in manifest, unknown palette token, duplicate primitive ids). Tempfixture cases build their bad fixtures under `tempfile.TemporaryDirectory()` so nothing synthetic leaks into the repo.

### Render-model generation

`scripts/generate_render_models.py` produces `render_models/<index:02d>_<layout>.json` for the **supported layouts only** (`cover`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `kpi_dashboard`, `timeline`, `agenda`, `conclusion`, `comparison_table` — every emit uses only the controlled `text` / `line` / `shape` / `image_slot` / `kpi` / `table` primitive kinds). The canonical filename is `<index:02d>_<layout>.json` (zero-padded two-digit `index` + `layout` token from the JSON, e.g. `02_agenda.json`); the workspace validator's `render_models filename` gate enforces this on disk so the exporter's deck_plan-driven 1:1 coverage gate doesn't see a mis-named file as orphan. It reads `deck_brief.json`, `deck_plan.json`, `design_system.json`, `image_manifest.json`, and the matching `slide_plans/*.json`, plus the chosen template's layout slot definitions. Layouts that map to the `chart_placeholder` primitive_kind (anything chart-bearing) are listed as `[SKIP]` and reported as not implemented — they are **not** counted as success.

```
python3 scripts/generate_render_models.py \
  --workspace examples/synthetic_20_page_business_review \
  --template-root templates/layouts

python3 scripts/generate_render_models.py \
  --workspace examples/synthetic_8_page_product_brief \
  --template-root templates/layouts
```

Determinism: the generator never invents source content. Text comes from `slide_plan.blocks[].content`; KPI rows come from `slide_plan.blocks[id="kpis"].content`; image refs come from `slide_plan.blocks[id="accent"].content` and must be declared in `image_manifest`. Bounds use the layout slot's `bounds` when set, otherwise the deterministic fallback table at the top of the script. The script fails closed on missing / malformed inputs, an unsafe `deck_plan.template`, an unknown image_ref, malformed kpi entries, a missing required slide_plan block, a stale / mismatched slide_plan (matched by JSON index but whose `layout` or `title` disagrees with the deck_plan slide), or an output that fails `render_model.schema.json` or the workspace cross-checks. Before generating, the script also removes **every** pre-existing `render_models/*.json` file — the workspace validator schema-validates every `*.json` in that directory as a render_model, so the `*.json` namespace is generator-owned. This means a stale render_model from a previous good run cannot survive a current-run fail-closed mismatch, a deck_plan change that moves the slide to an unsupported layout, **or a slide being removed from `deck_plan` entirely (orphan)**. Non-JSON files (READMEs, `.md` / `.txt` notes) are preserved. After writing, the script re-runs the same `check_render_models` gate the workspace validator uses, so output drift fails immediately.

### SVG preview generation

`scripts/generate_svg_previews.py` reads `render_models/*.json` and writes `svg_previews/<stem>.svg` for each. It consumes `render_model.json` only — never `slide_plan.json` — so the controlled primitive contract cannot be bypassed (see `references/svg-design-rules.md`).

```
python3 scripts/generate_svg_previews.py \
  --workspace examples/synthetic_20_page_business_review \
  --template-root templates/layouts

python3 scripts/generate_svg_previews.py \
  --workspace examples/synthetic_8_page_product_brief \
  --template-root templates/layouts
```

The renderer supports the primitive kinds the generator emits today — `text`, `line`, `shape`, `image_slot`, `kpi`, `table`. Any other kind (`chart_placeholder`, or any future kind) fails closed on that slide. The `table` primitive is rendered as a composite `<g>` with a bold header row, grid `<rect>` outline, and one `<text>` per cell — a visual preview of the native PPTX table the exporter emits. Token resolution: `palette.*` resolves to a raw hex via `design_system.palette.X` (the resolved value must match `^#[0-9A-Fa-f]{6}$`); `typography.heading|body` resolves to a `(font_family, size_pt)` pair via `design_system.typography.X` (`font_family` must match the CSS-style fallback-chain pattern); an unresolved or schema-violating token fails closed at the resolver, including for the background `<rect>` (no direct dict bypass). Image references resolve through `image_manifest.images[].id -> local_path`; the resolved path must pass the same path-safety rule the workspace validator enforces (no URI scheme, no POSIX-absolute, no leading backslash, no protocol-relative, no `..` segment, no empty). **Preflight** (runs before any cleanup): `design_system.json` and `image_manifest.json` are schema-validated, and every `image_manifest.images[].local_path` is run through `local_path_is_safe`. A preflight failure exits non-zero, prints no `OK:`, and does **not** delete any pre-existing `svg_previews/*.svg`. Before generating, every existing `svg_previews/*.svg` is removed (the `*.svg` namespace is generator-owned), so a stale preview cannot survive a fail-closed mismatch or a render_model deletion; non-SVG files (READMEs, `.md` / `.txt` notes) are preserved. After writing, the script re-runs the same `check_svg_previews` gate the workspace validator uses, so output drift fails immediately.

### PPTX export

`scripts/export_pptx.py` is driven by `<workspace>/deck_plan.json`: it iterates `deck_plan.slides[]` in declared order, resolves each entry to its canonical `<workspace>/render_models/<idx:02d>_<layout>.json`, and writes one native editable `.pptx` to `--output`. The exporter does NOT just glob `render_models/*.json` — a slide declared by `deck_plan` whose render_model is missing on disk fails closed before any output is written, as does an orphan render_model not declared by `deck_plan`. It is **stdlib-only**, deterministic (fixed ZIP timestamp, deterministic shape ids), and intentionally narrow.

```
python3 scripts/export_pptx.py \
  --workspace examples/synthetic_8_page_product_brief \
  --output /tmp/szh-ppt-master-smoke/synthetic_8_page_product_brief.pptx
```

Supported subset:

- layouts: `cover`, `kpi_dashboard`, `agenda`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `timeline`, `conclusion`, `comparison_table`. The slide-body emitter is layout-agnostic — it walks each render_model's `primitives` list — so widening the layout allow-list does not change how any single shape is rendered. Every layout declared by the business_review template skeleton is currently in this allow-list;
- primitive kinds: `text` (editable text frame), `line` (native `<p:cxnSp>` connector), `shape` (native `<p:sp>` with prstGeom rect / roundRect / ellipse), `kpi` (editable `<p:sp>` text frame with stacked label / value / optional delta paragraphs), `image_slot` (native placeholder rectangle whose `<a:txBody>` carries the `image_manifest` alt_text — **media embedding is intentionally TODO**), and `table` (native `<p:graphicFrame>` wrapping `<a:tbl>` with one `<a:gridCol>` per column, a bold header row, and an editable `<a:txBody>` per cell — every cell is directly editable in PowerPoint, no media embedding required).

Fail-closed gates:

- output extension must be `.pptx` (case-insensitive);
- `design_system.json` and `image_manifest.json` schema-validate, and every manifest `local_path` passes `local_path_is_safe`;
- `deck_plan.json` schema-validates, `planning.planned_slide_count` equals `len(slides)`, every `slides[]` entry has an integer `index` and a non-empty string `layout`, and indices are unique;
- `render_models/` exists and contains exactly the canonical filenames named by `deck_plan.slides[]` (every planned slide present, no orphan file);
- every consumed render_model schema-validates against `render_model.schema.json`;
- the render_model `canvas` matches `design_system.grid`;
- every primitive's `kind` is in the supported set (`chart_placeholder` fails closed with a clear per-slide error);
- palette / typography tokens resolve to a 6-digit hex / CSS-style font chain (defense-in-depth gate mirroring the SVG renderer);
- `image_slot.image_ref` is declared in `image_manifest`;
- a render_model whose layout is outside the SUPPORTED_LAYOUTS allow-list above fails closed with a per-slide error and aborts the whole run; no partial `.pptx` is written. Every layout declared by the business_review template skeleton is currently in scope; new layouts must add a paired generator branch before they may appear here. (Earlier wording said unsupported layouts were `[SKIP]`-ed and a partial deck was still produced — that is no longer the case.)

`--self-test` builds a synthetic workspace under `tempfile.TemporaryDirectory()` and exercises the happy path plus every fail-closed gate:

```
python3 scripts/export_pptx.py --self-test
```

A `--render-model <path>` debug entry exports a single render_model file (paired with `--design-system` and `--image-manifest`); the workspace mode is the primary entry point.

### PPTX contract + minimal-evidence validator

`scripts/validate_pptx_contract.py` is a stdlib-only, fail-closed validator that grows alongside the exporter. See `references/pptx-conversion-rules.md` for the contract.

```
# Skeleton mode — reports the contract / TODO surface only. Does not
# open or fabricate any file.
python3 scripts/validate_pptx_contract.py

# Container + minimal-evidence mode — when a .pptx is supplied,
# runs:
#   container.exists / container.extension / container.zip /
#   container.parts — basic OOXML container shape; AND
#   slide_count.inspectable / relationships.no_external /
#   relationships.no_file_uri / relationships.allow_list /
#   package.no_macros / package.no_ole / package.no_activex /
#   minimal_evidence.editable_text /
#   minimal_evidence.not_all_image_slide /
#   minimal_evidence.no_blank_slide /
#   minimal_evidence.every_slide_has_native_shape —
#   minimal-evidence safety / editability gates.
python3 scripts/validate_pptx_contract.py --pptx \
  /tmp/szh-ppt-master-smoke/synthetic_8_page_product_brief.pptx

# Self-test — exercises tempfixture negatives for every gate
# (missing file, wrong extension, non-zip content, empty ZIP, ZIP
# missing ppt/presentation.xml, external rel, file:// rel,
# unexpected relationship Type, vbaProject.bin, oleObject1.bin,
# activeX1.xml, all-image slide (fails both not_all_image_slide and
# every_slide_has_native_shape), no editable text, blank slide
# alongside an editable one) plus two positives (minimal valid
# container, minimal editable PPTX).
python3 scripts/validate_pptx_contract.py --self-test
```

The four `minimal_evidence.*` checks are explicitly named MINIMAL EVIDENCE in the per-check output: they prove *one* slide has an editable `<a:t>` run, they rule out the obvious one-big-PNG failure mode, they reject any slide whose `<p:spTree>` is structurally empty, and they require every slide to carry at least one native editable `<p:sp>` / `<p:cxnSp>` structure. They do not constitute a full per-shape editability inventory. The `relationships.allow_list` gate restricts every package `Relationship` `Type` URL to the canonical OOXML set (`officeDocument`, `slide`, `slideMaster`, `slideLayout`, `theme`); widening the exporter to embed media will widen this set. Full-inventory editability, the media inventory, theme palette mapping, determinism, and validator-side layout / primitive scope all remain TODO and are reported in every run.

### Local end-to-end pipeline runner (prepared workspaces)

`scripts/run_pipeline.py` is a stdlib-only orchestrator that chains the five existing scripts above into a single command for a workspace that **already** ships `deck_brief.json`, `deck_plan.json`, `slide_plans/*.json`, `design_system.json`, and `image_manifest.json`. The runner does **not** plan a deck from a raw prompt — intake → brief → plan from source is still TODO. It runs each stage as a subprocess against the same `python3` that started it (so each stage's existing fail-closed gates and self-tests are the source of truth — no logic is duplicated):

1. `scripts/validate_workspace.py` — contract gate on the inputs;
2. `scripts/generate_render_models.py` — regenerate `render_models/*.json`;
3. `scripts/generate_svg_previews.py` — regenerate `svg_previews/*.svg`;
4. `scripts/export_pptx.py` — write the native editable `.pptx`;
5. `scripts/validate_pptx_contract.py --pptx <output> --expected-slide-count <len(deck_plan.slides)>` — container + minimal-evidence gates on the exported file, including the slide-count gate the per-stage validator exposes.

A non-zero exit code from any stage stops the pipeline; downstream stages are skipped with a `[SKIP] earlier stage failed` note rather than silently passing. Workspace mutability: the runner **regenerates** `<workspace>/render_models/*.json` and `<workspace>/svg_previews/*.svg` in place (each generator owns its subdirectory and sweeps stale files before regenerating). The prepared-input artifacts (`deck_brief.json`, `deck_plan.json`, `slide_plans/`, `design_system.json`, `image_manifest.json`) and any other files under the workspace are read-only. The final `--output` PPTX **must live OUTSIDE** the workspace, and **so must `--report-dir`** when supplied — a stray `.pptx` or report directory under the workspace tree would otherwise be picked up by `validate_workspace` on a later run.

The runner fails closed before invoking any stage if `--workspace` or `--template-root` is not a directory, if `--output` does not end in `.pptx`, if `--output` would land inside the workspace tree, if `--report-dir` (when supplied) would land inside the workspace tree, if `--report-dir` (when supplied) already exists as a symlink (refused — not silently followed, same rule as `--output`), if `--report-dir` (when supplied) already exists and is not a directory (e.g. a regular file at the report path; refused so the pipeline never runs validate / generate / export only to crash inside `_write_reports()` afterwards with a `FileExistsError`), if `--output` already exists as a symlink (refused — not silently followed), or if `--output` already exists and is not a regular file (e.g. a directory named `Documents.pptx/`; refused so the runner never recursively touches arbitrary content). When `--report-dir` is supplied, the runner also pre-creates it (`mkdir(parents=True, exist_ok=True)`) and **then probes writability** by opening + closing + deleting a `NamedTemporaryFile` inside it — `mkdir(exist_ok=True)` alone is not sufficient because it returns success on an existing read-only directory (one the runner does not own, a read-only mount, an ACL block, a full filesystem), leaving `_write_reports()` to crash with `PermissionError` only AFTER the PPTX has already been written. The probe closes that hole: any unrelated permission / parent-not-a-directory / read-only-filesystem / full-disk error surfaces BEFORE any stage runs. The directory probe is not enough on its own either — `_write_reports()` writes two specific filenames (`pipeline_report.json` / `pipeline_report.txt`) via `Path.write_text()`, which follows symlinks and fails on directories or read-only regular files — so the runner ALSO refuses, before any stage runs, a pre-existing symlink at either report-file path (would silently redirect the write to an unrelated target — same anti-pattern `--output` forbids), a non-regular-file at either path (a directory would raise `IsADirectoryError`), and an existing regular file at either path that lacks user write permission (`os.access(..., os.W_OK)` is False; `write_text` would raise `PermissionError`). A pre-existing regular `.pptx` at `--output` is **not** deleted up-front — that prior artifact is overwritten in place by the export stage only when (and only when) the pipeline reaches that stage. An earlier-stage failure therefore leaves the caller's prior good `.pptx` untouched on disk, and the runner's report records the failure surface explicitly. A partial `.pptx` left by a crash inside the export stage itself is not cleaned up by this runner; full atomic-write semantics for the export stage remain a TODO on `scripts/export_pptx.py`, not on this runner.

`scripts/run_pipeline.py --self-test` builds tempfile-based synthetic workspaces (copied from `examples/synthetic_8_page_product_brief/`) and asserts fourteen scenarios: happy-path export+validation, wrong `--output` extension, `--output` inside the workspace, `--report-dir` inside the workspace, pre-existing regular file at `--report-dir` (refused before any stage runs; no PPTX is written and the prior file is preserved byte-identical), pre-existing symlink at `--report-dir` (refused; the symlink's target directory is untouched and no `pipeline_report.{json,txt}` is written into it), pre-existing read-only directory at `--report-dir` (writability probe; refused before any stage runs; auto-skipped under root because `chmod` cannot meaningfully restrict root), pre-existing symlink at `<report-dir>/pipeline_report.json` (refused; no PPTX is written and the symlink's unrelated target is preserved byte-identical), pre-existing read-only `<report-dir>/pipeline_report.txt` (refused; no PPTX is written and the prior file content is preserved; auto-skipped under root), happy-path `--report-dir` outside the workspace writes `pipeline_report.json` + `pipeline_report.txt` with `overall_ok=true`, pre-existing symlink at `--output`, pre-existing directory at `--output`, `validate_workspace` failure cascading `[SKIP]` across every downstream stage, and a pre-existing regular `.pptx` preserved (byte-identical) when `validate_workspace` fails before export. Exits non-zero if any scenario does not behave as expected.

```
python3 scripts/run_pipeline.py \
  --workspace examples/synthetic_8_page_product_brief \
  --template-root templates/layouts \
  --output /tmp/szh-ppt-master-smoke/8_page.pptx \
  --report-dir /tmp/szh-ppt-master-smoke/reports_8

python3 scripts/run_pipeline.py \
  --workspace examples/synthetic_20_page_business_review \
  --template-root templates/layouts \
  --output /tmp/szh-ppt-master-smoke/20_page.pptx \
  --report-dir /tmp/szh-ppt-master-smoke/reports_20
```

When `--report-dir` is supplied, the runner writes:

- `pipeline_report.json` — machine-readable: workspace / template_root / output / expected_slide_count / overall_ok / per-stage `{name, command, ok, skipped, exit_code, duration_s, stdout, stderr}` (stdout / stderr are truncated to 4 KB with an elision marker so the JSON stays bounded);
- `pipeline_report.txt` — short human-readable summary: workspace inputs, overall status, and per-stage PASS / FAIL / SKIP lines with the failing stage's stderr / stdout tail.

This is **not** the end-to-end "prompt → editable PPTX" experience. The runner only composes the existing prepared-workspace stages; everything outside that scope (raw-source ingestion, brief / plan generation from a prompt, `chart_placeholder` rendering, embedded media, full PPTX inventory, D-One image assets, Qoder CLI) remains TODO.

All other tools — full PPTX coverage (every layout, every primitive, embedded media, `chart_placeholder`), security scan, visual regression, image manifest population from real assets, D-One integration, Qoder CLI — are still **not implemented**. Do not document them as available. Render-model generation for layouts mapped to the `chart_placeholder` primitive kind, and SVG rendering / PPTX emission of primitive kinds outside `text` / `line` / `shape` / `image_slot` / `kpi` / `table`, are also not implemented.

## Engineering rules

See `CLAUDE.md` for the durable engineering and privacy rules that apply to all work here. Highlights:

- Keep changes narrow and surgical.
- Prefer structured schemas, templates, and deterministic validators.
- Preserve pipeline invariants (see `SKILL.md`).
- Mark missing decisions as TODOs, not invented defaults.
- Do not commit real customer data, credentials, endpoints, or sensitive report text.
- Do not copy or paraphrase any code or wording from `ppt-master`. This repo is clean-room.

## How to extend the scaffold

When adding the next pipeline stage:

1. Update or add the relevant schema under `schemas/`.
2. Update the matching reference doc under `references/`.
3. Add a synthetic fixture under `examples/` and confirm it validates.
4. Add or extend a deterministic script under `scripts/` that fails clearly when behavior is not yet implemented.
5. Update `SKILL.md` "What exists" / "What is NOT implemented" sections.
