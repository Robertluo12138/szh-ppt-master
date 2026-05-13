# Slide Contracts

The shapes of the five core artifacts plus the slot model that layouts must satisfy.

Authoritative shape lives in `schemas/`; this file is the human-readable companion.

## Adaptive shape

The shape rules here apply to **any** deck the planner produces — short or long, business-review or research-report. None of these contracts hard-codes a slide count or a section sequence. In particular:

- `deck_brief.json` may carry an `approximate_slide_count`, but the planner is free to land on a different count once it sees the source.
- `deck_plan.slides[]` is an ordered array with `minItems: 1` only. There is no universal upper bound and no required mix of layouts.
- A `deck_plan` is allowed to include or omit any layout the chosen template family declares (agenda, section dividers, KPI dashboards, timelines, conclusion, etc.); none is mandatory.

## Planner contract (machine-enforced)

The planner contract is enforced by schema **and** by cross-artifact checks in `scripts/validate_workspace.py` / `scripts/validate_scaffold.py`. Neither check fixes a maximum slide count or a required layout sequence:

- `deck_brief.source_refs` is **required and non-empty** — every brief lists the opaque source identifiers the deck draws from. Raw sensitive text never goes here.
- `deck_plan.planning.planned_slide_count` is required and must equal `len(deck_plan.slides)`. The validator catches drift between the planner's declared length and the actual slide list.
- `deck_plan.planning.rationale` is a required short string. It records *why* the planner chose this length and section structure for this brief.
- `deck_plan.sections[]` is required and non-empty. Each section carries `id`, `title`, `summary`, and `slide_indices`. The union of all `slide_indices` must equal the set of `deck_plan.slides[].index` values, with no duplicates across sections, no missing deck indices, and no orphan section indices.
- Every `deck_plan.slides[]` entry carries `section_id`, `summary`, `density` (enum `low` / `medium` / `high`), and a non-empty `source_refs`. The validator requires `section_id` to resolve to an existing section, the slide's `index` to be listed in that section's `slide_indices`, and every `source_refs` value to be declared in `deck_brief.source_refs`.

## Artifacts

| Artifact | Schema | Produced by | Required to start |
|---|---|---|---|
| `deck_brief.json` | `schemas/deck_brief.schema.json` | Brief stage | normalized source |
| `deck_plan.json` | `schemas/deck_plan.schema.json` | Plan stage (chooses length, structure, layouts, density) | `deck_brief.json` |
| `design_system.json` | `schemas/design_system.schema.json` | Design system stage | `deck_plan.json` + chosen template |
| `slide_plan.json` (one per slide) | `schemas/slide_plan.schema.json` | Per-slide plan stage | `deck_plan.json` + `design_system.json` |
| `image_manifest.json` | `schemas/image_manifest.schema.json` | Image manifest stage | all per-slide plans |

## Slot model (for layouts)

Each layout under `templates/layouts/<template>/layouts/<layout>.json` declares a list of `slots`. A slot has:

- `id` — stable identifier referenced by `slide_plan.blocks[].id`;
- `type` — one of `text`, `list`, `kpi`, `table`, `image_ref`, `chart_ref`, `callout`;
- `required` — whether the slot must be filled for the layout to render;
- `bounds` (optional) — `{ x, y, w, h }` in canvas pixels, on the same grid as `design_system.grid`. When set, a `render_model` primitive whose `slot_id` targets this slot must keep its own bounds inside this rectangle;
- `primitive_kind` (optional) — explicit mapping to a controlled render primitive. When unset, validators fall back to the default mapping below.

Default slot.type → render primitive kind:

| slot.type | default primitive.kind |
|---|---|
| `text` | `text` |
| `list` | `text` |
| `callout` | `text` |
| `kpi` | `kpi` |
| `table` | `table` |
| `image_ref` | `image_slot` |
| `chart_ref` | `chart_placeholder` |

A `slide_plan` is valid against a layout when every `required` slot has a matching block. The scaffold-level matcher is implemented in `scripts/validate_scaffold.py` and `scripts/validate_workspace.py`: for each layout slot with `required: true`, the slide_plan must contain a block where `block.id == slot.id` **and** `block.kind == slot.type`. Negative tests in both runners prove that a dropped required block and a kind mismatch are detected. Per-`kind` content schemas (e.g. tightening `kpi` to `{label, value, delta}`, `table` to header+rows) remain **TODO**.

## Controlled render model (per slide)

The `render_model` is the per-slide intermediate that the SVG preview renderer (implemented today for a subset of kinds; see below) and the expanded editable PPTX exporter (`scripts/export_pptx.py`, **consumes** render_models for layouts `cover`, `kpi_dashboard`, `agenda`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `timeline`, `conclusion`, `comparison_table` with primitive kinds `text` / `line` / `shape` / `image_slot` / `kpi` / `table`; everything else fails closed) both consume. SVG is preview / inspection only — the PPTX exporter does not parse SVG, it builds native OOXML from the render_model directly. See `references/pptx-conversion-rules.md` for the PPTX exporter contract.

Authoritative shape lives in `schemas/render_model.schema.json`. Key invariants:

- The model lists only **owned primitives** — `text`, `shape`, `line`, `image_slot`, `table`, `kpi`, `chart_placeholder`. New kinds may not be added without a schema bump and matching validator support. This is deliberately **not** an arbitrary-SVG-to-PPTX contract: SVG-specific keys (`transform`, `viewBox`, `href`, `xlink:href`, `xmlns`, `defs`, `foreignObject`, `filter`, …) are rejected at the schema level (`additionalProperties: false` at every nested object).
- Every primitive carries a required `bounds` (`{ x, y, w, h }`). The runtime validator enforces `x+w ≤ canvas.width_px` and `y+h ≤ canvas.height_px`; when the primitive references a layout slot whose own bounds are declared, the primitive's bounds must fit inside the slot's bounds.
- `style` is **token-only**: `fill_token`, `color_token`, `stroke_token` must match `^palette\.[a-z][a-z0-9_]*$`; `typography_token` must be `typography.heading` or `typography.body`. Raw hex colors and font families do not appear in primitives; the renderer resolves tokens against `design_system.json`.
- Image references are by `image_manifest` entry id, not by URL or path. The schema's `image_ref` pattern forbids URI schemes (`http`, `https`, `file`, `data`, `s3`, …), absolute paths, Windows drive prefixes, and `..` segments. The workspace validator additionally cross-checks that every `image_ref` is declared in `image_manifest`.
- Every primitive has a stable `id` unique within the slide. `slot_id` is optional; when set it must resolve to a slot on the chosen layout, and its primitive `kind` must match either `slot.primitive_kind` (when set) or the default mapping above.
- `source_refs` is **required and non-empty**. Each value must be declared in `deck_brief.source_refs`. The cross-check is fail-closed: a missing, malformed, or empty `deck_brief.source_refs` causes the render model to fail rather than silently skip — a render model cannot claim traceability without a brief that lists the same source ids. Raw sensitive source text never appears in a render model.

The render_model is **not** itself a render of a slide — it carries no SVG path data, no font metrics, no resolved colors. It is the structured input from which the renderer produces SVG and from which the PPTX exporter constructs native shapes / text frames / tables / pictures.

### Generator scope

Today `scripts/generate_render_models.py` produces render models for every layout reachable from the controlled `text` / `line` / `shape` / `image_slot` / `kpi` / `table` primitive set: `cover`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `kpi_dashboard`, `timeline`, `agenda`, `conclusion`, `comparison_table`. The generator is deterministic and stdlib-only. Keep two phrasings distinct: which layouts this stage **can produce end-to-end** from a slide_plan (above) and which layouts the **PPTX exporter can consume** (see `references/pptx-conversion-rules.md`) — today both sets are the same.

- `cover`: emits a structural `line` (title divider, no slot), then `text` primitives for the required `title` and any present optional `subtitle` / `presenter` / `date`, then an `image_slot` for `accent` if the slide_plan has an `accent` block whose `image_ref` is declared in `image_manifest`. Bounds come from the layout slot when set; otherwise from the deterministic fallback table in the script.
- `section_divider`: optional `text` for `section_number`, required `text` for `section_title`, a structural `line` (no slot) below the title, and an optional `text` for `subtitle`.
- `executive_summary`: required `text` for `title` and `summary`, then one bulleted `text` per entry in the optional `key_points` list block, distributed vertically inside the `key_points` slot.
- `key_message`: optional `text` for `title`, a decorative `shape` (rounded_rectangle, no slot) sized to the `message` slot bounds, a `text` primitive overlaying it carrying the callout content, and an optional `text` for `supporting_text`.
- `two_column`: required `text` for `title`, then per side an optional `text` heading plus one bulleted `text` per entry in the required content list, distributed vertically inside each column's content slot.
- `kpi_dashboard`: emits a `text` primitive for `title`, a decorative `shape` (rounded_rectangle, no slot) sized to the `kpis` slot bounds, and one `kpi` primitive per entry in `slide_plan.blocks[id="kpis"].content`. Tiles are sized and positioned by a centered-row formula inside the `kpis` slot bounds.
- `timeline`: required `text` for `title`, then one bulleted `text` per entry in the required `timeline_items` list, distributed vertically inside the slot's fallback bounds (the `timeline.json` layout does not declare bounds today; the generator's `LAYOUT_FALLBACK_BOUNDS` covers the gap).
- `agenda`: required `text` for `title`, then one bulleted `text` per entry in the required `agenda_items` list, distributed vertically inside the slot's fallback bounds. The `agenda.json` layout does not declare bounds today; the generator's `LAYOUT_FALLBACK_BOUNDS` covers the gap — same shape as `timeline`.
- `conclusion`: required `text` for `title`, optional `text` for `summary`, then one bulleted `text` per entry in the optional `call_to_action` list, distributed vertically inside the slot bounds.
- `comparison_table`: required `text` for `title` plus one `table` primitive from the `slide_plan` `table` block's `{headers, rows}` content (renamed to `columns` + `rows` to match the render_model schema). Every row must have exactly `len(headers)` cells, and every cell must be a non-empty string; an inconsistent row count or an empty cell fails closed.

Layouts mapped to the `chart_placeholder` primitive kind — anything chart-bearing — are **not** generated. The script lists those slides as `[SKIP] … not implemented`. A run is `OK` when generation succeeds for every supported slide; skipped slides are surfaced in the output but never counted as success.

The generator never invents source content. All text and KPI rows come from `slide_plan.blocks[].content`. The generator is fail-closed on missing / malformed inputs, unsafe `deck_plan.template`, unknown `image_ref`, malformed kpi entries, a missing required slide_plan block, **a stale / mismatched slide_plan** (matched by JSON index but whose `layout` or `title` disagrees with the deck_plan slide), schema-invalid output, or workspace cross-check failure — and re-runs the same `check_render_models` gate the workspace validator uses, so output drift fails immediately rather than after the next CI run.

Before generating, the script **removes every** `render_models/*.json` file. The workspace validator schema-validates every `*.json` in this directory as a render_model, so the `*.json` namespace is generator-owned by `scripts/generate_render_models.py`. This covers four stale-file scenarios: (1) a previous successful run for a slide that now fails closed, (2) a previous successful run for a slide whose deck_plan layout has since changed to one the generator does not implement (slide gets skipped, no replacement), (3) the slide has been **removed from deck_plan entirely** (orphan with no current owner — would otherwise surface as a post-hoc cross-check failure), and (4) idempotent regeneration (the file is deleted and immediately rewritten). Non-`.json` files in `render_models/` (READMEs, `.md` / `.txt` notes) are left untouched — the cleanup glob targets `*.json` only.

### SVG preview generator

`scripts/generate_svg_previews.py` is the stage-8 implementation. It reads `<workspace>/render_models/*.json` and writes `<workspace>/svg_previews/<stem>.svg` for each. The renderer consumes `render_model.json` only — it does NOT read `slide_plan.json`, so the controlled primitive contract cannot be bypassed.

- Supported primitive kinds today: `text`, `line`, `shape`, `image_slot`, `kpi`, `table`. Every other kind (`chart_placeholder` or any future kind) fails closed on that slide. The `table` primitive is rendered as a composite `<g>` with a bold header row, grid `<rect>` outline, and one `<text>` per cell — a visual preview of the native PPTX table the exporter emits.
- Tokens: `palette.*` resolves to a raw hex via `design_system.palette.X`; `typography.heading|body` resolves to a `(font_family, size_pt)` pair via `design_system.typography.X`. An unresolved token fails closed.
- Image references: resolve through `image_manifest.images[].id → local_path`. The resolved `local_path` must pass the same path-safety rule the workspace validator enforces; an undeclared or unsafe `image_ref` fails closed.
- Output naming: `<idx>_<layout>.svg`, matching the render_model file stem.
- Stale-file cleanup: every existing `svg_previews/*.svg` is removed before regeneration. The `*.svg` namespace under `svg_previews/` is owned by `scripts/generate_svg_previews.py` and only `*.svg` files are deleted — non-SVG files in `svg_previews/` (READMEs, `.md` / `.txt` notes) are preserved. This script does NOT touch `render_models/`; cleanup of `render_models/*.json` is owned by `scripts/generate_render_models.py` (see "Generator scope" above).
- Post-write check: the script re-runs the same `check_svg_previews` gate the workspace validator uses, so output drift fails immediately.

See `references/svg-design-rules.md` for the SVG-side contract and the exhaustive list of validator checks; see `references/quality-gates.md` for the `svg.*` gate identifiers.

## Block kinds

`slide_plan.blocks[].kind` values:

- `text` — heading, subtitle, paragraph;
- `list` — ordered or unordered points;
- `kpi` — a labeled number with optional delta;
- `table` — header + rows;
- `image_ref` — references an `image_manifest` entry by id;
- `chart_ref` — references a chart spec (charts are out of scope in the scaffold);
- `callout` — short emphasized text.

Per-kind content shape is **TODO**; the scaffold schema accepts `content` as free-form until tightened.

## Naming and indexing

- Slide indices are 1-based.
- The scaffold's `scripts/validate_workspace.py` looks for per-slide plans under `<workspace>/slide_plans/*.json` and matches by the JSON `index` field, not by filename. **Stage-5 commits to the flat layout:** `scripts/init_slide_plans.py` writes per-slide plans as `<workspace>/slide_plans/<idx:02d>_<layout>.json` (zero-padded two-digit `index` + `layout` token from inside the JSON — same shape as the render-model canonical name). The workspace validator continues to match by the `index` field, not by filename, so a hand-prepared or migrated workspace may still ship non-canonical filenames; `scripts/init_slide_plans.py` only guarantees the canonical shape on freshly-written sets. (A workspace-validator filename gate equivalent to `render.filename` for `slide_plans/*.json` remains TODO; it would let the validator catch hand-edited workspaces that drift from the canonical shape.)
- **Render model filenames are canonical.** Every `render_models/*.json` file must be named `<index:02d>_<layout>.json`, where `index` and `layout` come from inside the JSON (zero-padded two-digit index + the layout token verbatim — e.g. `02_agenda.json`, `09_two_column.json`, `20_conclusion.json`). The PPTX exporter (`scripts/export_pptx.py`) iterates `deck_plan.slides[]` in declared order and resolves each entry to its canonical render_model filename, so a mis-named `99_agenda.json` whose JSON `index` is 2 fails closed at the 1:1 coverage gate (the canonical `02_agenda.json` is missing on disk, the mis-named file is orphan) before any output is written. The workspace validator enforces this on disk (`check_render_model_filenames` / `render.filename` in `references/quality-gates.md`); the render-model generator always writes the canonical name. Schema-invalid files (no integer `index`, no string `layout`) are not double-flagged by this gate — `check_render_models` already rejects them. The Stage-5 helper writes per-slide plans using the same canonical shape; `init_slide_plans.py` is the producer-side commitment, while the workspace-validator filename gate for `slide_plans/*.json` itself remains TODO.

## TODOs

- Tighten `slide_plan.blocks[].content` shape per `kind` (today the schema accepts free-form content; the `render_model` primitives tighten this for renderable artifacts).
- Add a workspace-validator filename gate for `slide_plans/*.json` (equivalent to `render.filename` for `render_models/`) so hand-edited workspaces that drift from the canonical `<idx:02d>_<layout>.json` shape `init_slide_plans.py` writes are caught on disk. The producer-side choice (flat `slide_plans/<idx:02d>_<layout>.json`, not a per-slide subdirectory) is now committed to by `init_slide_plans.py`.
- Extend `render_model` further: stroke styles, gradients, dashed-pattern enumeration, multi-paragraph text runs, richer table cell styling (zebra striping, per-cell typography), and a controlled chart spec to replace `chart_placeholder`. None of these are in scope today; the current `table` primitive carries cell strings only and the native PPTX `<a:tbl>` inherits the default table style.
