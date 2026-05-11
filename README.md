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

Only structural JSON validation of fixtures is wired up, and it uses Python's standard library only:

```
python3 scripts/validate_artifacts.py \
  --schema schemas/deck_brief.schema.json \
  examples/synthetic_20_page_business_review/deck_brief.json
```

The validator implements a **subset** of JSON Schema (type / required / enum / pattern / nested properties / items). Full JSON-Schema validation is TODO and will be marked clearly in the script output.

All other tools — SVG generation, PPTX export, security scan, visual regression, image manifest population, D-One integration, Qoder CLI — are not implemented. Do not document them as available.

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
