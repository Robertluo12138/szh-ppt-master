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
- `schemas/` — JSON Schemas for the five core artifacts (`deck_brief`, `deck_plan`, `design_system`, `slide_plan`, `image_manifest`) plus the template-side schemas (`template`, `theme`, `layout`).
- `templates/layouts/business_review/` — template + theme + 10 layout skeletons. Theme `font_family` is a CSS-style fallback chain.
- `examples/synthetic_20_page_business_review/` — synthetic input, schema-valid fixtures for `deck_brief`, `deck_plan`, `design_system`, `image_manifest`, a representative set of `slide_plans/`, and the synthetic SVG assets referenced by the manifest under `assets/`.
- `scripts/validate_artifacts.py` — stdlib-only structural validator (subset of JSON Schema; full validation is TODO).
- `scripts/validate_scaffold.py` — stdlib-only scaffold runner that exercises positive fixtures, negative cases, path-safety on `image_manifest.local_path` **and** `template.theme_ref` (rejecting **any URI-like scheme prefix** matching `^[A-Za-z][A-Za-z0-9+.\-]*:` — `http://`, `https://`, `file://`, `s3://`, `ftp://`, `data:`, `mailto:`, `javascript:`, etc., including Windows drive prefixes like `C:\...` / `D:/...` which match the same shape — plus POSIX-absolute, leading-backslash, protocol-relative `//host/...`, `..` segments, and the empty string), **media resolution (every `local_path` must exist; every `slide_plan.image_refs` id must be declared)**, layout-aware slide-plan coverage, the template/theme/layout cross-check (including `template.name` matching its directory, and `theme_ref` not escaping the template dir). The theme load is **gated** on the `theme_ref` guards in two stages: a string-only `local_path_is_safe` check runs first and short-circuits before any filesystem call, then the within-template-dir resolve check runs, and only then can the theme file be opened. An unsafe `theme_ref` never reaches `Path.resolve()` or any file read.

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

Two stdlib-only commands run:

```
# Single-artifact structural check (subset of JSON Schema).
python3 scripts/validate_artifacts.py \
  --schema schemas/deck_brief.schema.json \
  examples/synthetic_20_page_business_review/deck_brief.json

# Full scaffold check: schemas, negative cases, image_manifest path-safety,
# layout-aware slide_plan coverage, and template/theme/layout cross-check.
python3 scripts/validate_scaffold.py
```

`validate_scaffold.py` exits non-zero if any check disagrees, including its built-in negative cases (e.g. unsafe `http://` paths must be rejected, dropping a required layout slot must be detected). All other verification commands — SVG, PPTX, security scan, visual regression — are TODO until their scripts exist.
