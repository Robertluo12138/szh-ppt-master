---
name: editable-ppt
description: Internal clean-room skill that turns prompts, reports, or Markdown into editable PowerPoint decks through a planned pipeline. Invoke when the user asks to scaffold, plan, validate, or extend deck-generation artifacts in this repo.
status: scaffold
---

# editable-ppt

## Status

Scaffold only. The pipeline is defined and the on-disk contracts are sketched, but no real rendering, conversion, image generation, charting, visual-regression, or CLI integration is implemented yet. See per-file TODOs and `references/`.

## Adaptive deck shape

There is **no universal deck structure** and no fixed slide count. The planner decides shape from the user request and source material:

- `deck_brief` is derived from the user request / source bundle.
- `deck_plan` chooses the deck's **target length**, **section structure**, **slide layouts**, and **density**.
- Expected capacity range is **12–25 slides** as guidance, not a contract. A real run may produce 6, 8, 10, 15, 20, 25, or another reasonable count depending on the brief.
- Different scenarios use different structures — e.g. executive summary, product proposal, technical solution, project review, research report, training deck, strategy memo. None of them is "the" canonical sequence.
- The `business_review` layout family is the **first** (initial scaffold) template family, not the product's identity. Future template families may share, drop, or replace any of its layouts.

## Pipeline (invariants)

1. source prompt / report / Markdown
2. → `deck_brief.json`
3. → `deck_plan.json` (adaptive length, structure, layouts, density)
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
- `templates/layouts/business_review/` — **first** template family (initial scaffold). Template + theme + 10 layout skeletons. Theme `font_family` is a CSS-style fallback chain. Additional template families are expected later and may declare a different set of layouts.
- `examples/synthetic_20_page_business_review/` — **upper-range stress-test fixture**: synthetic input, schema-valid fixtures for `deck_brief`, `deck_plan`, `design_system`, `image_manifest`, a `slide_plans/` set covering every slide in this fixture's `deck_plan`, and the synthetic SVG assets referenced by the manifest under `assets/`. This is **one** fixture at the upper end of the capacity range, not the canonical or default deck shape.
- `examples/synthetic_8_page_product_brief/` — **smaller synthetic fixture** at the lower end of the range: an 8-slide product-brief deck reusing the `business_review` template family. Demonstrates that the pipeline does not assume any single deck length.
- `scripts/validate_artifacts.py` — stdlib-only structural validator (subset of JSON Schema; full validation is TODO).
- `scripts/validate_scaffold.py` — stdlib-only scaffold runner. **Discovers** example workspaces under `examples/` (anything with `deck_plan.json` + `slide_plans/`) and runs the positive / per-workspace checks against each, so no example name and no fixed slide count is hardcoded. It exercises positive fixtures, negative cases, path-safety on `image_manifest.local_path` **and** `template.theme_ref` (rejecting **any URI-like scheme prefix** matching `^[A-Za-z][A-Za-z0-9+.\-]*:` — `http://`, `https://`, `file://`, `s3://`, `ftp://`, `data:`, `mailto:`, `javascript:`, etc., including Windows drive prefixes like `C:\...` / `D:/...` which match the same shape — plus POSIX-absolute, leading-backslash, protocol-relative `//host/...`, `..` segments, and the empty string), **media resolution (every `local_path` must exist; every `slide_plan.image_refs` id must be declared)**, layout-aware slide-plan coverage, the template/theme/layout cross-check (including `template.name` matching its directory, and `theme_ref` not escaping the template dir). Layout-aware negative mutations pick fixtures by layout name from any discovered workspace rather than hardcoding a file path. The theme load is **gated** on the `theme_ref` guards in two stages: a string-only `local_path_is_safe` check runs first and short-circuits before any filesystem call, then the within-template-dir resolve check runs, and only then can the theme file be opened. An unsafe `theme_ref` never reaches `Path.resolve()` or any file read.
- `scripts/validate_workspace.py` — stdlib-only, fail-closed validator for an **arbitrary** workspace (the path is caller-supplied via `--workspace`, with templates discovered via `--template-root`). Missing or malformed required artifacts now report `[FAIL]` with no traceback. The runner checks: schemas; the `deck_plan.template` chain into the template-root; **full template validation** (`template.name` matches its directory, `theme_ref` passes the two-stage gate, theme file exists and validates against `theme.schema.json`, every declared layout file exists, validates against `layout.schema.json`, and its file stem matches `layout["name"]`); **strict 1:1 slide_plan/deck_plan coverage** (duplicate `deck_plan` indices, duplicate `slide_plan` indices, orphan `slide_plan` indices, and missing indices all fail — neither side may silently collapse duplicates); per-slide layout-slot coverage; image_manifest path-safety; media resolution inside the workspace; and `slide_plan.image_refs` consistency. Built-in negative tests cover unsafe schemes, absolute paths, path traversal, missing media, unknown layouts, missing/orphan/duplicate slide_plans, required-slot mismatches, and wrong block kinds. A separate tempfixture suite proves detection of missing theme files, invalid theme schemas, invalid layout schemas (extra field), missing declared layout files, duplicate slide_plan indices, and missing `deck_plan.json` (no traceback). Tempfixtures are built under `tempfile.TemporaryDirectory()` so no synthetic data leaks into the repo.

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

Three stdlib-only commands run:

```
# Single-artifact structural check (subset of JSON Schema). Any
# example workspace may be substituted for the path below.
python3 scripts/validate_artifacts.py \
  --schema schemas/deck_brief.schema.json \
  examples/synthetic_20_page_business_review/deck_brief.json

# Full scaffold check: schemas, negative cases, image_manifest path-safety
# (including any URI-like scheme prefix), layout-aware slide_plan coverage,
# and the two-stage fail-closed template/theme/layout cross-check. Runs
# against every example workspace under examples/ that contains the
# expected files — no example is hardcoded.
python3 scripts/validate_scaffold.py

# Arbitrary-workspace check: validates a caller-supplied workspace
# against the schemas, the template chain, full slide-plan coverage of
# the deck plan, per-slide layout-slot coverage, image path-safety,
# media resolution inside the workspace, and image_refs consistency.
# Works on any deck length; the upper-range fixture below is one
# example, the 8-page fixture is another.
python3 scripts/validate_workspace.py \
  --workspace examples/synthetic_20_page_business_review \
  --template-root templates/layouts

python3 scripts/validate_workspace.py \
  --workspace examples/synthetic_8_page_product_brief \
  --template-root templates/layouts
```

All three exit non-zero if any check disagrees, including built-in negative cases (e.g. unsafe `http://` / `s3://` / `data:` paths must be rejected, dropping a required layout slot must be detected, an orphan slide_plan must be detected). All other verification commands — SVG, PPTX, security scan, visual regression — are TODO until their scripts exist.
