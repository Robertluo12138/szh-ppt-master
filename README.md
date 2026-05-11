# szh-ppt-master

Internal, local, clean-room skill for turning a prompt, report, or Markdown source into an editable PowerPoint deck through a controlled pipeline.

This README is for maintainers. End-user / agent behavior is described in `SKILL.md`.

## Current state

Scaffold only. The directory layout, the JSON-Schema contracts for the five core artifacts, and a single template skeleton (`business_review`) exist. No rendering, conversion, image generation, or CLI integration is implemented.

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
  layouts/business_review/
    template.json
    theme.json
    layouts/<layout>.json
examples/               # synthetic-only example material
scripts/                # local deterministic tooling
projects/               # generated workspaces (not committed; created by users)
```

`projects/<name>` is **not** hardcoded anywhere. Scripts accept arbitrary workspace paths.

## Verification today

Two stdlib-only Python checks are wired up. No third-party dependencies are required.

### Single-artifact structural validation

```
python3 scripts/validate_artifacts.py \
  --schema schemas/deck_brief.schema.json \
  examples/synthetic_20_page_business_review/deck_brief.json
```

The validator implements a **subset** of JSON Schema (`type`, `required`, `enum`, `pattern`, `minLength`/`maxLength`, `minimum`/`maximum`/`exclusiveMinimum`/`exclusiveMaximum`, `minItems`/`maxItems`, nested `properties`, `additionalProperties` boolean or schema, and `items` as a single subschema). Full JSON-Schema validation is TODO and the script labels its output `(subset)`.

### Scaffold validation runner

`scripts/validate_scaffold.py` exercises every check the scaffold currently supports in one pass:

```
python3 scripts/validate_scaffold.py
```

It runs:

- **Positive:** every synthetic fixture under `examples/synthetic_20_page_business_review/` validates against its schema (`deck_brief`, `deck_plan`, `design_system`, each `slide_plan`, `image_manifest`).
- **Negative:** removing a required field from each artifact in memory must fail validation.
- **Path-safety:** workspace-relative paths only. Rejects the empty string, POSIX-absolute (`/...`), leading-backslash, protocol-relative (`//host/...`), **any URI-like scheme prefix** matching `^[A-Za-z][A-Za-z0-9+.\-]*:` (covers `http://`, `https://`, `file://`, `s3://`, `ftp://`, `data:`, `mailto:`, `javascript:`, and anything else of that shape — which also subsumes Windows drive prefixes like `C:\...`, `D:/...`, `c:foo`), and any path containing a `..` segment. Applied to both `image_manifest.local_path` and `template.theme_ref`.
- **Media resolution (fail-closed):** every `image_manifest` `local_path` must resolve to a real file under the workspace, and every `slide_plan.image_refs` entry must point to an id declared in the manifest. Enforces `references/security-policy.md` item 6.
- **Layout-aware slide plans:** every required slot declared by a template layout is covered by a matching block in the slide plan (`block.id == slot.id`, `block.kind == slot.type`). Negative cases prove that a dropped required block or a wrong block kind is detected.
- **Template / theme / layout cross-check:** `template.json`, `theme.json`, and every layout file validate against their schemas; the template's `name` matches its containing directory; `theme_ref` passes a string-only path-safety check **and then** resolves to a path under the template directory; layout filenames match the declared `name`; and the template's `layouts` list matches the files on disk. The `theme_ref` guards run in two stages and are **fail-closed**: stage 1 (`local_path_is_safe`) is string-only and short-circuits before any filesystem call; only a stage-1 pass allows stage 2 (which calls `Path.resolve()` to catch symlink escape), and only a stage-2 pass allows the theme file to be opened. The same gate shape is mirrored in the negative loop, so the stage-2 helper is never called on a string-unsafe `theme_ref`. A meta-check iterates every unsafe `theme_ref` in the negative list through the loader under recorders for `_resolves_within` and `_load`, and asserts both recorders stayed empty and the loader emitted its "NOT opened (fail-closed)" result every time. Other negative cases prove that unsafe `theme_ref` values and a `template.name` mismatch are rejected.

Exit code is `0` only when every check (positives **and** negatives) behaves as expected.

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
