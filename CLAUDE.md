# Claude Code Instructions

## Boundary With Codex

`AGENTS.md` is intended for Codex only. Claude Code should not read, import, depend on, summarize, or edit `AGENTS.md` unless the user explicitly asks. Use this `CLAUDE.md` file as the implementation source of truth.

## Project Role

This repo is for an internal clean-room skill that turns prompts, reports, or Markdown into editable PowerPoint decks through controlled planning, SVG rendering, validation, and PPTX export.

Implement only the work requested in the user's current prompt. Do not treat this file as a task list or roadmap.

## Repo Conventions

Expected stable layout, once created:

- `SKILL.md` for skill behavior.
- `README.md` for maintainer usage.
- `SECURITY.md` for privacy and security policy.
- `references/` for detailed workflow, design, writing, SVG, conversion, D-One, and quality-gate rules.
- `schemas/` for JSON schemas.
- `templates/` for internal layout and chart templates.
- `scripts/` for local deterministic tooling.
- `projects/` for generated local workspaces, without hardcoded project names.
- `examples/` for synthetic or redacted examples only.

Detailed product/process rules should live in `references/` after those files exist. Until then, mark missing sources as `TODO / not created yet` rather than expanding this file into a PRD.

Do not document commands, dependencies, package formats, or validation results as real until the corresponding files exist.

## Engineering Rules

- If the `karpathy-guidelines` skill is available, use it for coding, review, and refactor work: keep changes simple, surgical, assumption-aware, and verifiable.
- Keep changes narrow. Do not implement later phases or broad architecture rewrites unless explicitly asked.
- Prefer structured schemas, templates, and deterministic validators over ad hoc conventions.
- Preserve these pipeline invariants: `deck_plan` before SVG, per-slide plans before SVG, SVG as the intermediate layer, and editable PPTX as the main output.
- D-One or similar image generation may only produce local image assets, never full-slide screenshots.
- Qoder CLI and project handling must accept arbitrary paths; do not hardcode `projects/<name>`.
- Mark missing decisions as TODOs or blockers instead of inventing policy, dependencies, or product behavior.

## Privacy Rules

- Default to no public network access.
- Do not add public scraping, public image search, telemetry, or undeclared remote calls without explicit user approval.
- Do not commit real examples, credentials, endpoints, account IDs, customer names, or sensitive report text.
- Do not send raw source documents or sensitive text to image-generation prompts.
- Security checks should fail closed for external URLs, `file://`, absolute paths, unsafe PPTX relationships, missing media, or uncertain safety.

## Verification Expectations

Run the narrowest real checks that cover the changed surface. When available, prefer:

- schema validation for structured artifacts;
- SVG validation for bounds, references, colors, fonts, and density;
- PPTX inspection for editability, media, and relationship safety;
- security scan output;
- synthetic demo generation;
- package/archive inspection.

If no verification command exists yet, say that clearly and describe the static checks performed.

## Reporting Expectations

When finished, report:

- files changed;
- verification run;
- scope completed;
- blockers, TODOs, or the next recommended step.
