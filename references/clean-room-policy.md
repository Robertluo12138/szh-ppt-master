# Clean-Room Policy

This skill must be implemented independently of any pre-existing reference implementation, including a project named `ppt-master`.

## Rules

- Upstream `ppt-master` (or any similarly named prior implementation) is a **direction radar only**: you may inspect its commit summaries and high-level behavior for direction, but stay clean-room.
- Do **not** copy, paraphrase, port, or summarize its code, prompts, templates, documentation, examples, or assets into this repo.
- Do not import its modules, schemas, templates, or example artifacts.
- Design decisions here must be re-derived from the contracts in `references/` and `schemas/`, not inherited.
- File names and directory shapes here may overlap with conventional industry names (e.g. `deck_plan.json`), but the **content** of each file is original to this repo.
- When in doubt about whether a design choice came from a reference implementation: treat it as out of bounds and re-derive it from this repo's contracts.

## Review

PRs that touch core schemas, templates, or pipeline code should be reviewed for:

- absence of copied wording or copied structure;
- explicit reasoning trail in the PR description for any non-obvious shape that resembles an external reference.

## Synthetic examples only

Examples in `examples/` must be **synthetic**. They must not be derived from real customer decks, real internal documents, or real reports — even with redaction. See `security-policy.md` for the broader privacy rules.
