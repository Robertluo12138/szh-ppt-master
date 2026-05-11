# Workflow

The skill is a single linear pipeline. Stages are append-only; do not skip or reorder.

| # | Stage | Input | Output | Schema |
|---|---|---|---|---|
| 1 | Intake | prompt / report / Markdown | normalized source bundle | — |
| 2 | Brief | normalized source | `deck_brief.json` | `schemas/deck_brief.schema.json` |
| 3 | Plan | `deck_brief.json` | `deck_plan.json` (adaptive length, structure, layouts, density) | `schemas/deck_plan.schema.json` |
| 4 | Design system | `deck_plan.json` + template | `design_system.json` | `schemas/design_system.schema.json` |
| 5 | Per-slide plan | `deck_plan.json` + `design_system.json` | one `slide_plan.json` per slide | `schemas/slide_plan.schema.json` |
| 6 | Image manifest | per-slide plans | `image_manifest.json` | `schemas/image_manifest.schema.json` |
| 7 | SVG render | per-slide plan + design_system + image_manifest | one SVG per slide | TODO |
| 8 | SVG validate / repair | per-slide SVG | validated SVG + repair report | TODO |
| 9 | PPTX export | validated SVGs + template | one editable PPTX | TODO |
| 10 | Reports | PPTX + artifacts | security / editability / visual reports | TODO |

## Adaptive planning

The Brief and Plan stages are **adaptive**, not template-driven:

- The Brief stage derives `deck_brief.json` from the user's request and the normalized source. It captures intent, audience, objective, and any explicit constraints (including `approximate_slide_count` if the caller supplied one).
- The Plan stage chooses, for that specific brief: **target slide count**, **section structure**, **which layouts each slide uses**, and **per-slide density**. There is no universal sequence — agenda, section dividers, KPI dashboards, timelines, and conclusion slides are tools the planner *may* use, not slots it *must* fill.
- Expected capacity range is **12–25 slides** as guidance; a real run may produce 6, 8, 10, 15, 20, 25, or another reasonable count. The number depends on the brief, not on the template.
- Different scenarios produce different shapes — e.g. executive summary, product proposal, technical solution, project review, research report, training deck, strategy memo. Template families exist to provide the layout vocabulary; they do not dictate slide count or order.

## Invariants

- Stage `n` may not start until stage `n-1` has produced its output and that output has passed schema validation.
- `deck_plan` must exist before any SVG work. Per-slide plans must exist before that slide's SVG.
- SVG is the **only** path to PPTX. Direct PPTX construction from a slide plan is not allowed.
- The terminal output is an **editable** PPTX.

## Project workspace

Each run uses a workspace directory chosen by the caller. All intermediate artifacts live there. The skill must not hardcode `projects/<name>`; the path is always passed in.

## TODOs

- Define the on-disk layout of a workspace (filenames, subfolders) — see `slide-contracts.md`.
- Decide whether stages 7–10 produce one process per slide or a single batched run.
- Decide retry / repair policy at each stage.
