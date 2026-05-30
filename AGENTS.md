# Codex Steering

## Role

This file is for Codex only. Use it to steer direction, write Claude Code prompts, and review implementation work. Claude Code should use `CLAUDE.md`.

Before planning or reviewing repo work, read `references/agent-operating-context.md` for the durable project direction and current-phase scope.

Keep current tasks, milestone status, and one-off implementation instructions out of this file. Put immediate work in the Codex or Claude Code prompt.

## Project North Star

Build an internal clean-room PPT skill that turns prompts, reports, or Markdown into editable PowerPoint decks through a controlled local pipeline.

The goal is not to clone `ppt-master`. The goal is to satisfy the same business need with a simpler, safer internal production line: adaptive planning, controlled layouts, SVG preview, native editable PPTX output, and fail-closed validation.

## Stable Product Boundaries

- This is a clean-room internal repo. Do not copy or paraphrase code, prompts, templates, docs, examples, or assets from the parent `ppt-master` project.
- No public network access by default. Do not add web scraping, public image search, telemetry, or undeclared remote dependencies without explicit user approval.
- No real examples. Fixtures, previews, screenshots, and package artifacts must be synthetic or clearly redacted.
- Deck shape is adaptive. Do not hardcode a 20-page structure, a universal business-review sequence, or a page-count catalog.
- `business_review` is only the first template family, not the product identity.
- SVG is required as a visual preview / inspection layer, but the project should not become a generic arbitrary-SVG-to-PPTX converter.
- Editable PPTX is the main output. Full-slide screenshots must not become the primary deck body.
- D-One may generate local image assets only, not full-slide screenshots and not from raw sensitive source text.
- Qoder CLI and workspace handling must work for arbitrary user paths; do not hardcode `projects/<name>`.

## Architecture Direction

Preferred pipeline:

`input -> deck_brief -> adaptive deck_plan -> slide_plans -> layout model -> SVG preview -> native editable PPTX -> validation reports`

Important direction:

- Treat `deck_plan`, `slide_plan`, template layouts, and the design system as source of truth.
- Use a controlled primitive model for rendering: text, shapes, lines, image slots, tables, KPI blocks, and simple charts.
- Generate SVG preview and editable PPTX from the same controlled model where possible.
- Avoid building a broad SVG parser/converter. Support only the primitives and SVG features the repo explicitly owns.
- Keep planning, rendering, validation, security scanning, and packaging as separate stages with persisted artifacts.

## Source Of Truth

- `CLAUDE.md`: stable Claude Code implementation guidance.
- `SKILL.md`: skill-facing status, pipeline invariants, and available commands.
- `README.md`: maintainer usage and current verification surface.
- `SECURITY.md`: durable privacy and security policy.
- `references/`: product/process contracts.
- `schemas/`: artifact and template schemas.
- `templates/`: layout/theme skeletons and future template families.
- `scripts/`: deterministic local validators and future tooling.
- `examples/`: synthetic regression fixtures only, not product recipes.

## Codex Review Rules

- Block one-shot deck generation that skips `deck_plan` or per-slide planning.
- Block changes that make examples, page counts, or `business_review` behave like the default product.
- Block full-slide raster output as the main PPT body.
- Block generic arbitrary-SVG conversion unless the user explicitly accepts that scope.
- Block real company data, credentials, endpoints, customer names, internal screenshots, or sensitive report text in committed files.
- Block external URLs, `file://`, absolute local paths, undeclared remote media, unsafe PPTX relationships, or missing media.
- Check docs, schemas, scripts, templates, examples, and packaged artifacts for drift when any one surface changes.
- Ask for user direction instead of inventing dependency stack, D-One interface, package/import format, Qoder behavior, or visual-quality thresholds.

## Verification Bias

Prefer concrete evidence over summaries:

- schema validation for structured artifacts;
- workspace validation against arbitrary paths;
- SVG validation once SVG exists;
- PPTX relationship and editability inspection once export exists;
- security scan output;
- synthetic smoke decks;
- package/archive inspection when packaging exists.

## Roadmap Reference

Background only. The current task must come from the user prompt.

- Planner contract: adaptive deck planning, sections, density, source references, and no fixed slide count.
- Minimal vertical slice: a small set of controlled slide primitives rendered to SVG preview and editable PPTX.
- Quality gates: deterministic checks for artifacts, SVG, PPTX relationships, editability, and media safety.
- Internal image assets: D-One integration for local asset generation only after the local pipeline is stable.
- Skill packaging: Qoder/runtime integration after local generation and validation work end to end.

## Scope Drift Rules

- Do not paste in the parent `ppt-master` folder or import its implementation into this repo.
- Do not keep adding examples just to represent more page counts.
- Defer broad template libraries until the minimal vertical slice works.
- Defer D-One and Qoder integration until local planning, rendering, export, and validation are stable.
- Defer public/open-mode behavior unless the user explicitly requests it and security policy supports it.
