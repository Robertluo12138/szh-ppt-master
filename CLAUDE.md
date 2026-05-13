# Claude Code Instructions

## Boundary With Codex

`AGENTS.md` is intended for Codex only. Claude Code should not read, import, depend on, summarize, or edit `AGENTS.md` unless the user explicitly asks. Use this `CLAUDE.md` file as the implementation source of truth.

## Project Overview

This repo is an internal clean-room skill for turning prompts, reports, or Markdown into editable PowerPoint decks through a controlled local pipeline.

The project should meet the same business need as a PPT-generation workflow, but it must not copy implementation, wording, templates, examples, or assets from the parent `ppt-master` project. Treat that project as out of scope unless the user explicitly asks for a comparative review.

Claude Code's job is to implement the user's current prompt narrowly, preserve the local-only and clean-room constraints, and keep the repo verifiable.

## Current Capability Surface

The repo currently contains scaffold docs, JSON schemas, template skeletons, synthetic examples, stdlib-only validators, a stage-1 workspace initializer (`scripts/init_workspace.py`), a **narrow stage-2 deck_brief contract helper** (`scripts/init_deck_brief.py` — contract-only; it bridges a stage-1 workspace into a minimal schema-valid `deck_brief.json` whose `source_refs` carries the manifest's `source.id`, but does NOT extract business content from the source body and is NOT a full prompt/report-to-PPTX automation), a **narrow stage-3 deck_plan contract helper** (`scripts/init_deck_plan.py` — contract-only; it bridges a stage-2 workspace plus a caller-supplied `--plan-spec` JSON file into a minimal schema-valid `deck_plan.json`, enforcing schema validation + planner-semantics cross-checks (planned-count equality, unique + contiguous slide indices, section coverage 1:1, slide.section_id resolution, slide.source_refs subset of deck_brief.source_refs), but does NOT extract business content from the source body and is NOT a full prompt/report/Markdown-to-PPTX automation), a **narrow stage-4 design_system contract helper** (`scripts/init_design_system.py` — contract-only; it bridges a stage-3 workspace plus EXACTLY ONE explicit caller input — either `--spec <design_system.json>` or `--theme-from-template` + `--template-root <dir>` — into a minimal schema-valid `design_system.json`, validating palette / typography / grid against `schemas/design_system.schema.json`; in theme mode it resolves the template via `deck_plan.template` only and projects palette/typography/grid from the template's `theme.json`, but does NOT extract business content from the source body, does NOT infer design from raw source text, and is NOT a full prompt/report/Markdown-to-PPTX automation), a **narrow stage-5 slide_plans contract helper** (`scripts/init_slide_plans.py` — contract-only; it bridges a stage-4 workspace plus a required `--template-root <dir>` and `--specs-dir <dir>` of caller-supplied per-slide JSON specs into a complete `<workspace>/slide_plans/<idx:02d>_<layout>.json` set, validating every candidate against `schemas/slide_plan.schema.json` and cross-checking against `deck_plan.slides[]` (1:1 by index, no missing / orphan / duplicate slides, layout/title match, required layout slots covered, deck_plan layouts declared by the template) and against the same planner-semantics gate `init_deck_plan.py` applies — but does NOT extract business content from the source body, does NOT infer slide content from raw source text, does NOT generate `image_manifest.json` / render_models / SVG / PPTX, and is NOT a full prompt/report/Markdown-to-PPTX automation), a deterministic render-model generator (`scripts/generate_render_models.py`), a deterministic SVG preview renderer (`scripts/generate_svg_previews.py`), and a deterministic native editable PPTX exporter (`scripts/export_pptx.py`). All three downstream stages consume `render_model.json` directly. Coverage today:

- render-model generator supported layouts (the layouts the generator can **produce** end-to-end from a slide_plan): `cover`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `kpi_dashboard`, `timeline`, `agenda`, `conclusion`, `comparison_table` (every emit uses only the controlled primitive kinds below);
- SVG preview supported primitive kinds: `text`, `line`, `shape`, `image_slot`, `kpi`, `table` — i.e. exactly the kinds the render-model generator emits today;
- PPTX exporter supported layouts (the layouts the exporter can **consume** a render_model for): `cover`, `kpi_dashboard`, `agenda`, `section_divider`, `executive_summary`, `key_message`, `two_column`, `timeline`, `conclusion`, `comparison_table`, with the same `text` / `line` / `shape` / `image_slot` / `kpi` / `table` primitive set. Today the generator-supported and exporter-supported layout sets are the same — the exporter can consume any render_model the generator can produce. The slide-body emitter is layout-agnostic — it walks the render_model's `primitives` list — so the allow-list is a contract gate, not per-shape logic. The `table` primitive is exported as a native PPTX `<p:graphicFrame>` wrapping `<a:tbl>` whose cells are directly editable in PowerPoint.

`image_slot` is exported as a native PPTX placeholder shape carrying the `image_manifest` alt_text; media embedding (copying PNG / JPG / SVG bytes into `ppt/media/`) is intentionally TODO. Anything outside the supported subset must fail closed: `chart_placeholder` primitives, layouts outside the per-stage allow-lists above, malformed render_models, undeclared image refs, and unsafe manifest paths all abort the run with a clear per-slide error rather than producing a partial deck.

The PPTX exporter's slide enumeration is **driven by `deck_plan.json`**, not by a file-stem glob: it iterates `deck_plan.slides[]` in declared order and resolves each entry to its canonical `render_models/<idx:02d>_<layout>.json`. A `deck_plan` whose `planning.planned_slide_count` disagrees with `len(slides)`, a planned render_model missing on disk, or an orphan render_model file the `deck_plan` did not name all fail closed before any `.pptx` is written — the contract is intentionally 1:1.

The PPTX contract validator (`scripts/validate_pptx_contract.py`) now enforces `relationships.allow_list` over the five canonical OOXML rel types the exporter emits today (`officeDocument`, `slide`, `slideMaster`, `slideLayout`, `theme`) and `minimal_evidence.every_slide_has_native_shape` alongside the earlier container, package, and minimal-evidence gates. A caller can also pass `--expected-slide-count N` to activate the `slide_count.expected` gate (the slide-part count must equal `N` or the run fails closed — catches an exporter that silently truncated the deck). Full PPTX coverage (every layout, every primitive, embedded media, full editability inventory, theme palette mapping, determinism inventory, layout/primitive-scope inspection of the produced PPTX, media inventory) remains **not** implemented; chart rendering, visual regression, D-One integration, Qoder CLI integration, arbitrary-SVG parsing, and full-slide raster fallback also remain TODO. SVG repair (clipping out-of-bounds shapes, font fallback) and glyph-level text-overflow detection are still TODO.

Do not document unimplemented stages as working behavior, and do not claim end-to-end success — the pipeline now stops at the expanded native editable PPTX for the supported subset above.

Stage 2 has **narrow contract support**, not full automation. `scripts/init_deck_brief.py` writes only the four schema-required `deck_brief` fields (`title` / `audience` / `objective` from explicit CLI flags plus `source_refs = [source_manifest.source.id]`) plus any optional fields the caller passed verbatim. It never reads `input/source.md` for content, never invents `key_messages` / `constraints` / `tone` / `language` / `approximate_slide_count`, never produces stage-3+ artifacts, and never calls any network.

Stage 3 has **narrow contract support**, not full automation. `scripts/init_deck_plan.py` validates a caller-supplied `--plan-spec` JSON file (whose shape is exactly the deck_plan candidate to be written) against `schemas/deck_plan.schema.json` plus the planner-semantics cross-checks (`planning.planned_slide_count == len(slides)`, slide indices unique + contiguous 1..N, section coverage 1:1 with deck_plan slides, every `slide.section_id` resolves to a declared section, every `slide.source_refs` value is declared in `deck_brief.source_refs`) and writes the result deterministically to `<workspace>/deck_plan.json`. It never reads `input/source.md` for content, never invents `template` / `rationale` / `slides` / `sections`, never produces stage-4+ artifacts, and never calls any network.

Stage 4 has **narrow contract support**, not full automation. `scripts/init_design_system.py` requires a stage-3 workspace (source_manifest + deck_brief + deck_plan all present and schema-valid) and EXACTLY ONE explicit caller input — `--spec <path-to-design_system.json>` (a complete design_system the caller wants validated and written verbatim) OR `--theme-from-template` + `--template-root <dir>` (project palette/typography/grid from the theme of the template named in `deck_plan.template`, resolved against the supplied template root). It re-validates `deck_brief.json` and `deck_plan.json` against their schemas AND runs EXACTLY the planner-semantics cross-checks `init_deck_plan.py` applies before writing a Stage-3 artifact (re-using `init_deck_plan._cross_check_planner_semantics` — planned_slide_count == len(slides), slide indices unique AND contiguous 1..N, section coverage 1:1, slide.section_id resolves to a declared section, slide.source_refs subset of deck_brief.source_refs) so a schema-valid-but-semantically-broken prior stage (duplicate indices, `[1, 2, 4]`-style gaps, sections that orphan a slide, undeclared slide source ids, etc.) is refused before Stage-4 advances. It validates the resulting candidate against `schemas/design_system.schema.json` in memory before writing and re-validates on disk after writing, rolling back on failure. Template resolution is anchored on `deck_plan.template` only; there is no product-level template default — the name `business_review` is just the template the current repo ships, not a fallback. The helper itself never opens `input/source.md` — it invokes the Stage-1/Stage-2 bridge, which reads the source bytes ONLY for byte-level integrity checks (UTF-8 decode validity, byte_count / line_count / sha256 match against the manifest) and discards the decoded string; the helper never infers design tokens from raw source text, never produces stage-5+ artifacts (it does NOT itself generate any `slide_plans/*.json`), and never calls any network. Stage 5 has narrow contract support via `scripts/init_slide_plans.py` (caller-supplied `--specs-dir` + `--template-root`); Stage 6 (`image_manifest.json`) remains agent-driven. Do not extend `init_deck_brief.py`, `init_deck_plan.py`, or `init_design_system.py` to plan a deck, design a deck from source, generate slide_plans, or extract source content.

Stage 5 has **narrow contract support**, not full automation. `scripts/init_slide_plans.py` requires a stage-4 workspace (source_manifest + deck_brief + deck_plan + design_system all present and schema-valid), a `--template-root <dir>` against which `deck_plan.template` must resolve (no product-level default — `business_review` is just the template the current repo ships), and a `--specs-dir <dir>` of caller-supplied `*.json` slide-plan candidates. Per-file, every candidate is symlink-refused, JSON-parsed, decoded as an object, schema-validated against `schemas/slide_plan.schema.json`, and matched against `deck_plan.slides[]` 1:1 by `index` — duplicates across spec files, missing indices, orphan indices, layout/title mismatches with the deck_plan slide, undeclared template layouts, and missing required layout slots are all refused before any write. It re-runs the planner-semantics gate `init_deck_plan.py` applies (planned-count equality, contiguous 1..N indices, section coverage 1:1, slide.section_id resolution, slide.source_refs subset of deck_brief.source_refs) so a schema-valid-but-semantically-broken prior stage is refused before Stage-5 advances. A non-empty pre-existing `<workspace>/slide_plans/` is refused with prior bytes preserved; a symlink at that path (broken or resolvable) is refused outright; an empty pre-existing `slide_plans/` is accepted and reused. The `<template-root>/<deck_plan.template>/layouts/` subdirectory must itself NOT be a symlink (broken or resolvable; otherwise an attacker who controls the template root could redirect layout-file reads outside the template directory); every layout name used by `deck_plan.slides[].layout` is additionally run through `local_path_is_safe` AND `_resolves_within` against the template directory as belt-and-braces against template-schema drift. Each accepted candidate output path is added to the rollback set BEFORE its `write_text()` call, written deterministically to `<workspace>/slide_plans/<idx:02d>_<layout>.json`, and re-validated on disk; a mid-write OR post-write re-validation failure rolls back every slide_plan file the helper wrote in this run AND (when this run created it) the `slide_plans/` directory itself, so the workspace returns to its pre-call state. An empty pre-existing `slide_plans/` is intentionally preserved. The helper itself never opens `input/source.md` — it invokes the Stage-1/Stage-2 bridge for byte-level integrity checks only — never infers slide content from raw source text, never produces stage-6+ artifacts (`image_manifest.json`, render_models, SVG, PPTX), and never calls any network. Stage 6 (`image_manifest`) remains entirely agent-driven; do not extend `init_slide_plans.py` to plan slide bodies, infer image references, or extract source content.

## Architecture Notes

Preferred pipeline:

`input -> deck_brief -> adaptive deck_plan -> slide_plans -> layout model -> SVG preview -> native editable PPTX -> validation reports`

Stable architecture direction:

- `deck_brief`, `deck_plan`, `slide_plan`, template layouts, and the design system are the source of truth.
- Deck length and structure are adaptive. Do not assume 20 slides, business-review sequencing, or mandatory agenda/KPI/timeline/conclusion pages.
- Use a controlled rendering primitive model: text, shapes, lines, image slots, tables, KPI blocks, and simple charts.
- SVG is the visual preview and inspection layer, but this repo should not become a broad arbitrary-SVG-to-PPTX converter.
- Editable PPTX should be generated from the controlled model as native PowerPoint objects whenever possible.
- D-One or similar image generation may only create local image assets. It must not generate full-slide screenshots or receive raw sensitive source text.

## Repo Conventions

- `SKILL.md`: skill-facing workflow status, invariants, and available commands.
- `README.md`: maintainer usage and verification surface.
- `SECURITY.md`: privacy and security policy.
- `references/`: durable product/process contracts.
- `schemas/`: JSON schemas for artifacts and template files.
- `templates/`: layout and theme families.
- `scripts/`: deterministic local tooling.
- `examples/`: synthetic or redacted fixtures only.
- `projects/`: generated local workspaces if needed; do not hardcode this path.

Use zero-padded slide artifact names when creating slide files, such as `01_cover.json` and `01_cover.svg`.

## Engineering Rules

- If the `karpathy-guidelines` skill is available, use it for coding, review, and refactor work: keep changes simple, surgical, assumption-aware, and verifiable.
- Keep changes narrow to the user's prompt. Do not implement later roadmap phases unless explicitly asked.
- Prefer structured schemas, templates, and deterministic validators over prose-only conventions.
- Preserve pipeline ordering: `deck_plan` before slide artwork, and per-slide plans before SVG.
- Do not add a generic arbitrary-SVG parser/converter unless the user explicitly accepts that scope.
- Do not add public-network behavior, telemetry, real-data examples, broad template markets, voiceover, video export, or complex animation without explicit user approval.
- Mark missing product or technical decisions as TODOs or blockers instead of inventing behavior.
- When changing schemas, update matching examples, validators, and docs in the same change.
- When changing templates, update validators or examples that prove template/runtime alignment.

## Privacy Rules

- Default to no public network access.
- Do not add public scraping, public image search, telemetry, or undeclared remote calls.
- Do not commit real company data, credentials, endpoints, account IDs, customer names, internal screenshots, or sensitive report text.
- Do not send raw source documents or sensitive text to image-generation prompts.
- Outputs and manifests must not contain external URLs, `file://` links, absolute paths, undeclared remote media, or unsafe PPTX relationships.
- Examples and tests must be synthetic or clearly redacted.

## Verification Commands

Use the narrowest real checks that cover the changed surface. Existing stdlib-only checks include:

```bash
python3 scripts/validate_scaffold.py

python3 scripts/validate_workspace.py \
  --workspace examples/synthetic_20_page_business_review \
  --template-root templates/layouts

python3 scripts/validate_workspace.py \
  --workspace examples/synthetic_8_page_product_brief \
  --template-root templates/layouts
```

For single-artifact checks:

```bash
python3 scripts/validate_artifacts.py \
  --schema schemas/deck_brief.schema.json \
  examples/synthetic_20_page_business_review/deck_brief.json
```

If a relevant check does not exist yet, say that clearly and describe the static inspection performed.

## Reporting Expectations

When finished, report:

- files changed;
- verification run and exact result;
- scope completed;
- blockers, TODOs, or the recommended next step.

## Roadmap Reference

Background only. The current task must come from the user's prompt.

- Planner contract: adaptive deck planning with sections, density, source references, and no fixed slide count.
- Minimal vertical slice: a small controlled primitive set rendered to SVG preview and editable PPTX.
- Quality gates: deterministic artifact, SVG, PPTX, editability, media, and security checks.
- Internal image assets: D-One integration only after the local pipeline is stable.
- Runtime packaging: Qoder/skill integration only after local generation and validation work end to end.
