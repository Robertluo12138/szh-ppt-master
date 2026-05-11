# Slide Contracts

The shapes of the five core artifacts plus the slot model that layouts must satisfy.

Authoritative shape lives in `schemas/`; this file is the human-readable companion.

## Artifacts

| Artifact | Schema | Produced by | Required to start |
|---|---|---|---|
| `deck_brief.json` | `schemas/deck_brief.schema.json` | Brief stage | normalized source |
| `deck_plan.json` | `schemas/deck_plan.schema.json` | Plan stage | `deck_brief.json` |
| `design_system.json` | `schemas/design_system.schema.json` | Design system stage | `deck_plan.json` + chosen template |
| `slide_plan.json` (one per slide) | `schemas/slide_plan.schema.json` | Per-slide plan stage | `deck_plan.json` + `design_system.json` |
| `image_manifest.json` | `schemas/image_manifest.schema.json` | Image manifest stage | all per-slide plans |

## Slot model (for layouts)

Each layout under `templates/layouts/<template>/layouts/<layout>.json` declares a list of `slots`. A slot has:

- `id` — stable identifier referenced by `slide_plan.blocks[].id`;
- `type` — one of `text`, `list`, `kpi`, `table`, `image_ref`, `chart_ref`, `callout`;
- `required` — whether the slot must be filled for the layout to render.

A `slide_plan` is valid against a layout when every `required` slot has a matching block. The block-slot matcher is **TODO**.

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
- Per-slide artifacts are stored under the workspace as `slides/<index>/slide_plan.json` (path convention is **TODO** and not load-bearing yet).

## TODOs

- Tighten `content` shape per `kind`.
- Decide block-slot matching rules.
- Decide canonical workspace path layout.
