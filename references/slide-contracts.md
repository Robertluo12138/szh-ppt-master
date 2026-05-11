# Slide Contracts

The shapes of the five core artifacts plus the slot model that layouts must satisfy.

Authoritative shape lives in `schemas/`; this file is the human-readable companion.

## Adaptive shape

The shape rules here apply to **any** deck the planner produces — short or long, business-review or research-report. None of these contracts hard-codes a slide count or a section sequence. In particular:

- `deck_brief.json` may carry an `approximate_slide_count`, but the planner is free to land on a different count once it sees the source.
- `deck_plan.slides[]` is an ordered array with `minItems: 1` only. There is no universal upper bound and no required mix of layouts.
- A `deck_plan` is allowed to include or omit any layout the chosen template family declares (agenda, section dividers, KPI dashboards, timelines, conclusion, etc.); none is mandatory.

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
- `required` — whether the slot must be filled for the layout to render.

A `slide_plan` is valid against a layout when every `required` slot has a matching block. The scaffold-level matcher is implemented in `scripts/validate_scaffold.py` and `scripts/validate_workspace.py`: for each layout slot with `required: true`, the slide_plan must contain a block where `block.id == slot.id` **and** `block.kind == slot.type`. Negative tests in both runners prove that a dropped required block and a kind mismatch are detected. Per-`kind` content schemas (e.g. tightening `kpi` to `{label, value, delta}`, `table` to header+rows) remain **TODO**.

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

- Tighten `content` shape per `kind`.
- Decide canonical workspace path layout (including per-slide directory vs flat `slide_plans/`).
