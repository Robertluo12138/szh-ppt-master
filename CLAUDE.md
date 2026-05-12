# Claude Code Instructions

## Boundary With Codex

`AGENTS.md` is intended for Codex only. Claude Code should not read, import, depend on, summarize, or edit `AGENTS.md` unless the user explicitly asks. Use this `CLAUDE.md` file as the implementation source of truth.

## Project Overview

This repo is an internal clean-room skill for turning prompts, reports, or Markdown into editable PowerPoint decks through a controlled local pipeline.

The project should meet the same business need as a PPT-generation workflow, but it must not copy implementation, wording, templates, examples, or assets from the parent `ppt-master` project. Treat that project as out of scope unless the user explicitly asks for a comparative review.

Claude Code's job is to implement the user's current prompt narrowly, preserve the local-only and clean-room constraints, and keep the repo verifiable.

## Current Capability Surface

The repo currently contains scaffold docs, JSON schemas, template skeletons, synthetic examples, stdlib-only validators, a deterministic render-model generator (`scripts/generate_render_models.py`), a deterministic SVG preview renderer (`scripts/generate_svg_previews.py`), and a deterministic native editable PPTX exporter (`scripts/export_pptx.py`). All three downstream stages consume `render_model.json` directly and cover the same minimal supported subset:

- supported layouts: `cover` and `kpi_dashboard`;
- supported primitive kinds: `text`, `line`, `shape`, `image_slot`, `kpi`.

`image_slot` is exported as a native PPTX placeholder shape carrying the `image_manifest` alt_text; media embedding (copying PNG / JPG / SVG bytes into `ppt/media/`) is intentionally TODO. Anything outside the supported subset must fail closed: `table` and `chart_placeholder` primitives, every other layout, malformed render_models, undeclared image refs, and unsafe manifest paths all abort the run with a clear per-slide error rather than producing a partial deck.

Full PPTX coverage (every layout, every primitive, embedded media, full editability inventory, relationship allow-list, theme palette mapping, determinism inventory), chart rendering, visual regression, D-One integration, and Qoder CLI integration are **not** implemented; SVG repair (clipping out-of-bounds shapes, font fallback) and glyph-level text-overflow detection also remain TODO.

Do not document unimplemented stages as working behavior, and do not claim end-to-end success — the pipeline now stops at the minimal native editable PPTX for the supported subset.

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
