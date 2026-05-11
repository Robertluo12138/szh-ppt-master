# szh-ppt-master

Internal, local, clean-room skill for turning a prompt, report, or Markdown source into an editable PowerPoint deck through a controlled pipeline.

This README is for maintainers. End-user / agent behavior is described in `SKILL.md`.

## Current state

Scaffold only. The directory layout, the JSON-Schema contracts for the five core artifacts, and a **first** template-family skeleton (`business_review`) exist. No rendering, conversion, image generation, or CLI integration is implemented.

## Deck shape is adaptive

There is no fixed deck length and no universal slide sequence. The planner derives a `deck_brief` from the user request / source bundle, and the `deck_plan` stage chooses target length, section structure, slide layouts, and density for that specific brief. Expected capacity range is **12–25 slides** as guidance; a run may produce 6, 8, 10, 15, 20, 25, or another reasonable count. Different scenarios (executive summary, product proposal, technical solution, project review, research report, training deck, strategy memo) use different structures. The `business_review` template family is the first scaffold template family, not the product's identity. The 20-page synthetic example below is one upper-range stress-test fixture, not the canonical deck.

## Layout

```
SKILL.md                # skill entry point, pipeline invariants, status
README.md               # this file
SECURITY.md             # privacy and security policy
.gitignore              # ignored generated outputs and local caches
references/             # source-of-truth policy and contract docs
schemas/                # JSON Schemas for the five core artifacts
                        # plus template / theme / layout schemas
templates/              # internal layout / theme skeletons
  layouts/business_review/   # first template family; more may be added
    template.json
    theme.json
    layouts/<layout>.json
examples/               # synthetic-only example workspaces of varying lengths
scripts/                # local deterministic tooling
projects/               # generated workspaces (not committed; created by users)
```

`projects/<name>` is **not** hardcoded anywhere. Scripts accept arbitrary workspace paths.

## Verification today

Three stdlib-only Python checks are wired up. No third-party dependencies are required.

### Single-artifact structural validation

```
python3 scripts/validate_artifacts.py \
  --schema schemas/deck_brief.schema.json \
  examples/synthetic_20_page_business_review/deck_brief.json
```

(Any example workspace can be substituted; the upper-range 20-page fixture is shown here, but any deck shape under `examples/` works the same way.)

The validator implements a **subset** of JSON Schema (`type`, `required`, `enum`, `pattern`, `minLength`/`maxLength`, `minimum`/`maximum`/`exclusiveMinimum`/`exclusiveMaximum`, `minItems`/`maxItems`, nested `properties`, `additionalProperties` boolean or schema, and `items` as a single subschema). Full JSON-Schema validation is TODO and the script labels its output `(subset)`.

### Scaffold validation runner

`scripts/validate_scaffold.py` exercises every check the scaffold currently supports in one pass:

```
python3 scripts/validate_scaffold.py
```

It runs:

- **Positive:** every synthetic fixture under each example workspace in `examples/` (currently `synthetic_20_page_business_review` — the upper-range stress-test fixture — and `synthetic_8_page_product_brief` — a lower-range fixture) validates against its schema (`deck_brief`, `deck_plan`, `design_system`, each `slide_plan`, `image_manifest`). The runner discovers workspaces by inspecting `examples/`; no example name is hardcoded.
- **Negative:** removing a required field from each artifact in memory must fail validation.
- **Path-safety:** workspace-relative paths only. Rejects the empty string, POSIX-absolute (`/...`), leading-backslash, protocol-relative (`//host/...`), **any URI-like scheme prefix** matching `^[A-Za-z][A-Za-z0-9+.\-]*:` (covers `http://`, `https://`, `file://`, `s3://`, `ftp://`, `data:`, `mailto:`, `javascript:`, and anything else of that shape — which also subsumes Windows drive prefixes like `C:\...`, `D:/...`, `c:foo`), and any path containing a `..` segment. Applied to both `image_manifest.local_path` and `template.theme_ref`.
- **Media resolution (fail-closed):** every `image_manifest` `local_path` must resolve to a real file under the workspace, and every `slide_plan.image_refs` entry must point to an id declared in the manifest. Enforces `references/security-policy.md` item 6.
- **Layout-aware slide plans:** every required slot declared by a template layout is covered by a matching block in the slide plan (`block.id == slot.id`, `block.kind == slot.type`). Negative cases prove that a dropped required block or a wrong block kind is detected.
- **Planner semantics:** the same machine-enforced planner contract as the workspace runner — `deck_brief.source_refs` required and non-empty, `planning.planned_slide_count` matches `len(slides)`, `sections[]` partition the deck's slide indices, every `slides[].section_id` resolves to an existing section that lists this index, and every `slides[].source_refs` value is declared in `deck_brief.source_refs`. The check runs against every discovered workspace; no slide-count or example name is hardcoded.
- **Template / theme / layout cross-check:** `template.json`, `theme.json`, and every layout file validate against their schemas; the template's `name` matches its containing directory; `theme_ref` passes a string-only path-safety check **and then** resolves to a path under the template directory; layout filenames match the declared `name`; and the template's `layouts` list matches the files on disk. The `theme_ref` guards run in two stages and are **fail-closed**: stage 1 (`local_path_is_safe`) is string-only and short-circuits before any filesystem call; only a stage-1 pass allows stage 2 (which calls `Path.resolve()` to catch symlink escape), and only a stage-2 pass allows the theme file to be opened. The same gate shape is mirrored in the negative loop, so the stage-2 helper is never called on a string-unsafe `theme_ref`. A meta-check iterates every unsafe `theme_ref` in the negative list through the loader under recorders for `_resolves_within` and `_load`, and asserts both recorders stayed empty and the loader emitted its "NOT opened (fail-closed)" result every time. Other negative cases prove that unsafe `theme_ref` values and a `template.name` mismatch are rejected.

Exit code is `0` only when every check (positives **and** negatives) behaves as expected.

### Workspace validator

`scripts/validate_workspace.py` validates an **arbitrary** workspace directory (the workspace path is caller-supplied; nothing is hardcoded). Pair it with a template-root directory containing the templates. The validator is agnostic to deck length — it works on a 6-slide deck or a 25-slide deck:

```
python3 scripts/validate_workspace.py \
  --workspace examples/synthetic_20_page_business_review \
  --template-root templates/layouts

python3 scripts/validate_workspace.py \
  --workspace examples/synthetic_8_page_product_brief \
  --template-root templates/layouts
```

It runs (every check is fail-closed; exit 1 on any failure):

- **Schemas:** every artifact in the workspace (`deck_brief.json`, `deck_plan.json`, `design_system.json`, `image_manifest.json`, and every `slide_plans/*.json`) loads and validates against its schema. Missing or malformed artifacts produce a `[FAIL]` line — never a Python traceback.
- **Template chain:** `deck_plan.template` is path-safe **and** resolves inside `--template-root`; every `deck_plan` slide layout is declared by the template's `layouts` list.
- **Template files (full):** the selected template's `template.json` validates against its schema; `template.name` matches its directory; `theme_ref` passes the two-stage path-safety + within-template-dir gate, the theme file exists, and `theme.json` validates against `schemas/theme.schema.json`; every declared layout has a `layouts/<name>.json` file that validates against `schemas/layout.schema.json` and whose file stem matches `layout["name"]`.
- **Slide-plan coverage (strict 1:1):** `deck_plan` slide indices must be unique (duplicates in `deck_plan.slides[].index` `[FAIL]` before any further analysis); every `deck_plan` slide has exactly one matching `slide_plan` file (matched by JSON `index`); duplicate `slide_plan` indices, orphan `slide_plan` indices (no deck_plan entry), and missing indices (deck_plan slide with no `slide_plan`) all `[FAIL]`. Every `slide_plan` agrees with its deck_plan entry on `index`/`layout`/`title`, and every required layout slot is covered by a matching `slide_plan` block (`block.id == slot.id`, `block.kind == slot.type`).
- **Planner semantics (machine-enforced contract):** `deck_brief.source_refs` is required and non-empty; `deck_plan.planning.planned_slide_count` equals `len(deck_plan.slides)`; `deck_plan.sections[].slide_indices` partition the set of `slides[].index` values (no duplicates across sections, no missing deck indices, no orphan section indices); every `slides[].section_id` resolves to an existing section that lists this slide's index; and every `slides[].source_refs` value is declared in `deck_brief.source_refs`. No maximum slide count and no required layout sequence is imposed.
- **Image manifest:** every `local_path` passes the same path-safety rule as `validate_scaffold.py` (any URI-like scheme prefix, absolute paths, leading-backslash, protocol-relative, `..` segments, and the empty string are rejected); every safe path resolves to a real file inside the workspace; every `slide_plan.image_refs` id is declared in `image_manifest`.
- **Negative tests (in-memory + tempfixture):** the runner explicitly proves the validator detects unsafe schemes (`s3://`, `ftp://`, `data:`, `mailto:`, `javascript:`), absolute paths (POSIX, Windows drive, UNC), path traversal (`..` segments), missing media, unknown layouts, missing slide_plans, orphan slide_plans, duplicate `slide_plan` indices, **duplicate `deck_plan` indices** (no false-green), required-slot mismatches, wrong block kinds, missing theme files, invalid theme schemas, invalid layout schemas (extra fields), missing declared layout files, missing `deck_plan.json` (no traceback), and every planner-semantics rule (planned-count mismatch, missing / duplicate-across-sections / orphan section indices, unknown / mis-listed slide `section_id`, undeclared slide `source_refs`). Tempfixture cases build their bad fixtures under `tempfile.TemporaryDirectory()` so nothing synthetic leaks into the repo.

All other tools — SVG generation, PPTX export, security scan, visual regression, image manifest population from real assets, D-One integration, Qoder CLI — are still **not implemented**. Do not document them as available.

## Engineering rules

See `CLAUDE.md` for the durable engineering and privacy rules that apply to all work here. Highlights:

- Keep changes narrow and surgical.
- Prefer structured schemas, templates, and deterministic validators.
- Preserve pipeline invariants (see `SKILL.md`).
- Mark missing decisions as TODOs, not invented defaults.
- Do not commit real customer data, credentials, endpoints, or sensitive report text.
- Do not copy or paraphrase any code or wording from `ppt-master`. This repo is clean-room.

## How to extend the scaffold

When adding the next pipeline stage:

1. Update or add the relevant schema under `schemas/`.
2. Update the matching reference doc under `references/`.
3. Add a synthetic fixture under `examples/` and confirm it validates.
4. Add or extend a deterministic script under `scripts/` that fails clearly when behavior is not yet implemented.
5. Update `SKILL.md` "What exists" / "What is NOT implemented" sections.
