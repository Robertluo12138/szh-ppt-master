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
| 7 | Render model | per-slide plan + design_system + image_manifest + layout slots | one `render_model.json` per slide (controlled primitives, bounds, token-only style refs) | `schemas/render_model.schema.json` |
| 8 | SVG render | per-slide render model | one SVG preview per slide under `svg_previews/` (partial: `text`, `line`, `shape`, `image_slot`, `kpi`) | XML; controlled by `check_svg_previews` in `scripts/validate_workspace.py` |
| 9 | SVG validate | per-slide SVG | pass/fail against `check_svg_previews` | implemented (repair: TODO) |
| 10 | PPTX export | per-slide render model + template | one editable PPTX (native shapes / text frames / pictures) | TODO — exporter not implemented; contract / container skeleton in `scripts/validate_pptx_contract.py` |
| 11 | Reports | PPTX + artifacts | security / editability / visual reports | TODO |

Stage 7 is the only stage between the per-slide plan and the consumers of the controlled model. Its contract is the controlled primitive / layout model defined in `schemas/render_model.schema.json` and described in `references/slide-contracts.md`. Stage 7 is the boundary the SVG renderer (stage 8) and the PPTX exporter (stage 10) **both** consume directly — they do not read `slide_plan.json` and the PPTX exporter does **not** parse the SVG. Stages 8/9 produce the preview / validation artifact; stage 10 produces native PPTX objects from the same render model.

Stage 7 is **partially implemented**: `scripts/generate_render_models.py` produces deterministic render models for the **two supported layouts only** — `cover` and `kpi_dashboard`. Every other layout (`agenda`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `comparison_table`, `timeline`, `conclusion`, and any future addition) is listed as `[SKIP] … not implemented` by the script and is **not** counted as success. Slides for unsupported layouts have no `render_model.json` and cannot proceed to stages 8 / 10 until the generator is extended. The script is fail-closed on missing / malformed inputs, unsafe `deck_plan.template`, unknown `image_ref`, malformed kpi entries, missing required slide_plan block, schema-invalid output, or workspace cross-check failure.

Stages 8 / 9 are **partially implemented**: `scripts/generate_svg_previews.py` reads every render_model the generator emits and writes one `svg_previews/<stem>.svg` per slide. It supports the primitive kinds the render-model generator emits today (`text`, `line`, `shape`, `image_slot`, `kpi`); every other kind (`table`, `chart_placeholder`, future kinds) fails closed on that slide. Validation runs as `check_svg_previews` inside `scripts/validate_workspace.py` — see `references/svg-design-rules.md` and `references/quality-gates.md` for the exact gates. Automatic SVG repair (out-of-bounds clipping, font fallback, density thresholds) remains TODO.

Stage 10 (PPTX export) is **NOT implemented**. `scripts/validate_pptx_contract.py` is the **contract / skeleton** validator that will grow alongside the future exporter (see `references/pptx-conversion-rules.md`). Today it runs in two modes: with `--pptx <path>` it checks the basic OOXML container surface (file exists, `.pptx` extension, readable ZIP, required package entries `[Content_Types].xml`, `_rels/.rels`, `ppt/presentation.xml`); without `--pptx` it runs in skeleton mode and only reports the TODO surface (editability of text frames, no all-image slides, relationship allow-list, embedded-only media, theme palette mapping, determinism, layout scope `cover` / `kpi_dashboard`, primitive scope `text` / `line` / `shape` / `image_slot` / `kpi`). A `--self-test` flag exercises tempfixture negatives (missing path, wrong extension, non-zip content, empty ZIP, ZIP missing `ppt/presentation.xml`) plus a minimal-valid-container positive. None of this is proof that PPTX export works; the future exporter must consume `render_model.json` directly and emit native editable PPTX objects (no SVG parsing, no full-slide screenshots).

## Adaptive planning

The Brief and Plan stages are **adaptive**, not template-driven:

- The Brief stage derives `deck_brief.json` from the user's request and the normalized source. It captures intent, audience, objective, and any explicit constraints (including `approximate_slide_count` if the caller supplied one). `source_refs` is required and non-empty: every brief lists the opaque source identifiers the deck draws from.
- The Plan stage chooses, for that specific brief: **target slide count**, **section structure**, **which layouts each slide uses**, and **per-slide density**. There is no universal sequence — agenda, section dividers, KPI dashboards, timelines, and conclusion slides are tools the planner *may* use, not slots it *must* fill.
- Expected capacity range is **12–25 slides** as guidance; a real run may produce 6, 8, 10, 15, 20, 25, or another reasonable count. The number depends on the brief, not on the template.
- Different scenarios produce different shapes — e.g. executive summary, product proposal, technical solution, project review, research report, training deck, strategy memo. Template families exist to provide the layout vocabulary; they do not dictate slide count or order.

### Planner contract (machine-enforced)

`deck_plan.json` carries a stricter planner contract that the validators cross-check, while still imposing **no** maximum slide count or required layout sequence:

- `deck_plan.planning.planned_slide_count` must equal `len(deck_plan.slides)`.
- `deck_plan.planning.rationale` is a required short string explaining the planner's length / structure choice.
- `deck_plan.sections[]` (`id`, `title`, `summary`, `slide_indices`) partitions the deck: the union of every section's `slide_indices` must equal the set of `slides[].index` values — no duplicates across sections, no missing deck indices, no orphan section indices.
- Each `slides[]` entry carries `section_id` (must exist; the slide's index must be listed by that section), `summary`, `density` (`low` / `medium` / `high`), and a non-empty `source_refs` whose values must all be declared in `deck_brief.source_refs`.

See `references/slide-contracts.md` and the schemas under `schemas/` for the authoritative shape; `references/quality-gates.md` lists the matching gates.

## Invariants

- Stage `n` may not start until stage `n-1` has produced its output and that output has passed schema validation.
- `deck_plan` must exist before any render-model or SVG work. Per-slide plans must exist before that slide's render model. A slide's render model must exist before that slide's SVG and before its PPTX shapes are emitted.
- The render model is the **only** input to the SVG renderer and the PPTX exporter — neither stage may read `slide_plan.json` directly, so the controlled primitive contract cannot be bypassed.
- SVG is a required **preview / inspection artifact and validation gate** for every slide, not the source language for PPTX. The PPTX exporter does **not** parse SVG; it builds native PowerPoint objects from the same `render_model.json` the SVG renderer consumed. This repo is intentionally not a broad SVG → PPTX converter.
- The terminal output is an **editable** PPTX.

## Project workspace

Each run uses a workspace directory chosen by the caller. All intermediate artifacts live there. The skill must not hardcode `projects/<name>`; the path is always passed in.

## TODOs

- Define the on-disk layout of a workspace (filenames, subfolders) — see `slide-contracts.md`.
- Decide whether stages 7–10 produce one process per slide or a single batched run.
- Decide retry / repair policy at each stage.
