---
name: editable-ppt
description: Internal clean-room skill that turns prompts, reports, or Markdown into editable PowerPoint decks through a planned pipeline. Invoke when the user asks to scaffold, plan, validate, or extend deck-generation artifacts in this repo.
status: scaffold
---

# editable-ppt

## Status

Scaffold only. The pipeline is defined and the on-disk contracts are sketched, but no real rendering, conversion, image generation, charting, visual-regression, or CLI integration is implemented yet. See per-file TODOs and `references/`.

## Pipeline (invariants)

1. source prompt / report / Markdown
2. → `deck_brief.json`
3. → `deck_plan.json`
4. → `design_system.json`
5. → per-slide `slide_plan.json`
6. → `image_manifest.json`
7. → per-slide SVG
8. → SVG validation / repair
9. → editable PPTX export
10. → security / editability / visual reports

Hard invariants (must remain true as the skill grows):

- `deck_plan` is produced **before** any SVG.
- A per-slide plan precedes that slide's SVG.
- SVG is the intermediate design layer; it must not be bypassed.
- The main output is an **editable** PPTX. No all-image-on-a-slide outputs.
- D-One (or any image generator) supplies **local image assets only** — never full-slide screenshots.
- Security checks fail closed.

## What exists in this repo today

- Root docs: `SKILL.md`, `README.md`, `SECURITY.md`, `.gitignore`.
- `references/` — policy and contract documents.
- `schemas/` — minimal JSON Schemas for the five core artifacts.
- `templates/layouts/business_review/` — template + theme + 10 layout skeletons.
- `examples/synthetic_20_page_business_review/` — synthetic input and a schema-valid `deck_brief.json` fixture.
- `scripts/validate_artifacts.py` — stdlib-only structural validator (subset of JSON Schema; full validation is TODO).

## What is NOT implemented yet

- SVG generation, repair, or validation.
- PPTX conversion, editability inspection, or security scan.
- D-One integration of any kind.
- Chart rendering or chart templates.
- Visual regression.
- Qoder CLI integration.
- Public network behavior, telemetry, voiceover, video, complex animation.

Do not document any of the above as "working". If a task needs one, mark it as a blocker.

## Path handling

Project workspaces are user-provided. Scripts must accept arbitrary paths. Do not hardcode `projects/<name>`.

## Verification available today

Only the structural validator runs:

```
python3 scripts/validate_artifacts.py \
  --schema schemas/deck_brief.schema.json \
  examples/synthetic_20_page_business_review/deck_brief.json
```

All other verification commands are TODO until their scripts exist.
