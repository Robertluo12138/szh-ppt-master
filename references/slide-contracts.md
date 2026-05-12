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

The `render_model` is the per-slide intermediate that the SVG preview renderer (implemented today for a subset of kinds; see below) and the future editable PPTX exporter both consume. PPTX export is **not implemented yet**; the SVG preview stage is partially implemented and described under "SVG preview generator" below.

Authoritative shape lives in `schemas/render_model.schema.json`. Key invariants:

- The model lists only **owned primitives** — `text`, `shape`, `line`, `image_slot`, `table`, `kpi`, `chart_placeholder`. New kinds may not be added without a schema bump and matching validator support. This is deliberately **not** an arbitrary-SVG-to-PPTX contract: SVG-specific keys (`transform`, `viewBox`, `href`, `xlink:href`, `xmlns`, `defs`, `foreignObject`, `filter`, …) are rejected at the schema level (`additionalProperties: false` at every nested object).
- Every primitive carries a required `bounds` (`{ x, y, w, h }`). The runtime validator enforces `x+w ≤ canvas.width_px` and `y+h ≤ canvas.height_px`; when the primitive references a layout slot whose own bounds are declared, the primitive's bounds must fit inside the slot's bounds.
- `style` is **token-only**: `fill_token`, `color_token`, `stroke_token` must match `^palette\.[a-z][a-z0-9_]*$`; `typography_token` must be `typography.heading` or `typography.body`. Raw hex colors and font families do not appear in primitives; the renderer resolves tokens against `design_system.json`.
- Image references are by `image_manifest` entry id, not by URL or path. The schema's `image_ref` pattern forbids URI schemes (`http`, `https`, `file`, `data`, `s3`, …), absolute paths, Windows drive prefixes, and `..` segments. The workspace validator additionally cross-checks that every `image_ref` is declared in `image_manifest`.
- Every primitive has a stable `id` unique within the slide. `slot_id` is optional; when set it must resolve to a slot on the chosen layout, and its primitive `kind` must match either `slot.primitive_kind` (when set) or the default mapping above.
- `source_refs` is **required and non-empty**. Each value must be declared in `deck_brief.source_refs`. The cross-check is fail-closed: a missing, malformed, or empty `deck_brief.source_refs` causes the render model to fail rather than silently skip — a render model cannot claim traceability without a brief that lists the same source ids. Raw sensitive source text never appears in a render model.

The render_model is **not** itself a render of a slide — it carries no SVG path data, no font metrics, no resolved colors. It is the structured input from which the renderer produces SVG and from which the PPTX exporter constructs native shapes / text frames / tables / pictures.

### Generator scope

Today `scripts/generate_render_models.py` produces render models for the **supported layouts only**: `cover` and `kpi_dashboard`. The generator is deterministic and stdlib-only.

- `cover`: emits a structural `line` (title divider, no slot), then `text` primitives for the required `title` and any present optional `subtitle` / `presenter` / `date`, then an `image_slot` for `accent` if the slide_plan has an `accent` block whose `image_ref` is declared in `image_manifest`. Bounds come from the layout slot when set; otherwise from the deterministic fallback table in the script.
- `kpi_dashboard`: emits a `text` primitive for `title`, a decorative `shape` (rounded_rectangle, no slot) sized to the `kpis` slot bounds, and one `kpi` primitive per entry in `slide_plan.blocks[id="kpis"].content`. Tiles are sized and positioned by a centered-row formula inside the `kpis` slot bounds.

Every other layout — `agenda`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `comparison_table`, `timeline`, `conclusion`, and any future addition — is **not** generated. The script lists those slides as `[SKIP] … not implemented`. A run is `OK` when generation succeeds for every supported slide; skipped slides are surfaced in the output but never counted as success.

The generator never invents source content. All text and KPI rows come from `slide_plan.blocks[].content`. The generator is fail-closed on missing / malformed inputs, unsafe `deck_plan.template`, unknown `image_ref`, malformed kpi entries, a missing required slide_plan block, **a stale / mismatched slide_plan** (matched by JSON index but whose `layout` or `title` disagrees with the deck_plan slide), schema-invalid output, or workspace cross-check failure — and re-runs the same `check_render_models` gate the workspace validator uses, so output drift fails immediately rather than after the next CI run.

### SVG preview generator

`scripts/generate_svg_previews.py` is the stage-8 implementation. It reads `<workspace>/render_models/*.json` and writes `<workspace>/svg_previews/<stem>.svg` for each. The renderer consumes `render_model.json` only — it does NOT read `slide_plan.json`, so the controlled primitive contract cannot be bypassed.

- Supported primitive kinds today: `text`, `line`, `shape`, `image_slot`, `kpi`. Every other kind (`table`, `chart_placeholder`, or any future kind) fails closed on that slide.
- Tokens: `palette.*` resolves to a raw hex via `design_system.palette.X`; `typography.heading|body` resolves to a `(font_family, size_pt)` pair via `design_system.typography.X`. An unresolved token fails closed.
- Image references: resolve through `image_manifest.images[].id → local_path`. The resolved `local_path` must pass the same path-safety rule the workspace validator enforces; an undeclared or unsafe `image_ref` fails closed.
- Output naming: `<idx>_<layout>.svg`, matching the render_model file stem.
- Stale-file cleanup: every existing `svg_previews/*.svg` is removed before regeneration (the `*.svg` namespace is generator-owned). Non-SVG files (READMEs, `.md` / `.txt` notes) are preserved.
- Post-write check: the script re-runs the same `check_svg_previews` gate the workspace validator uses, so output drift fails immediately.

See `references/svg-design-rules.md` for the SVG-side contract and the exhaustive list of validator checks; see `references/quality-gates.md` for the `svg.*` gate identifiers.

Before generating, the script also **removes every** `render_models/*.json` file. The workspace validator schema-validates every `*.json` in this directory as a render_model, so the `*.json` namespace is generator-owned. This covers four stale-file scenarios: (1) a previous successful run for a slide that now fails closed, (2) a previous successful run for a slide whose deck_plan layout has since changed to one the generator does not implement (slide gets skipped, no replacement), (3) the slide has been **removed from deck_plan entirely** (orphan with no current owner — would otherwise surface as a post-hoc cross-check failure), and (4) idempotent regeneration (the file is deleted and immediately rewritten). Non-`.json` files (READMEs, `.md` / `.txt` notes) are left untouched — the cleanup glob targets `*.json` only.

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
- The scaffold's `scripts/validate_workspace.py` looks for per-slide plans under `<workspace>/slide_plans/*.json` and matches by the JSON `index` field, not by filename. The full canonical workspace path layout (whether `slides/<index>/slide_plan.json`, `slide_plans/<index>_<layout>.json`, or something else) remains **TODO**.

## TODOs

- Tighten `slide_plan.blocks[].content` shape per `kind` (today the schema accepts free-form content; the `render_model` primitives tighten this for renderable artifacts).
- Decide canonical workspace path layout (including per-slide directory vs flat `slide_plans/` and `render_models/`).
- Extend `render_model` once SVG / PPTX export is in scope: stroke styles, gradients, dashed-pattern enumeration, multi-paragraph text runs, table cell styling, and a controlled chart spec to replace `chart_placeholder`. None of these are in scope today.
