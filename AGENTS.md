# Codex Steering

## Role

This file is for Codex only. Use it to steer, review, and keep the project aligned. Claude Code should use `CLAUDE.md` as its implementation guidance.

Keep current tasks, milestones, and phase status out of this file. Put immediate work in the Claude Code prompt.

## Hard Policy

- This is an internal clean-room PPT skill, not a public generic deck generator.
- No public network access by default. Do not add web scraping, public image search, telemetry, or undeclared remote dependencies without explicit user approval.
- No real examples. Fixtures, examples, previews, and package artifacts must be synthetic or clearly redacted.
- `deck_plan` must exist before slide artwork.
- Per-slide plans must exist before SVG generation.
- SVG is the required intermediate design layer.
- Editable PPTX is the main output. Full-slide screenshots must not become the primary deck body.
- D-One may generate local image assets only, not full-slide screenshots and not from raw sensitive source text.
- Security scans must fail closed on external URLs, `file://`, absolute paths, unsafe PPTX relationships, missing media, or uncertain safety.
- Qoder CLI and project-path handling must work for arbitrary user paths; do not hardcode `projects/<name>`.

## Review Rules

- Block one-shot deck generation that skips structured planning.
- Block changes that weaken editability, clean-room handling, local-only defaults, or fail-closed security behavior.
- Block real company data, credentials, endpoints, customer names, or sensitive report text in committed examples.
- Check docs, schemas, scripts, templates, examples, and packages for drift when any one of those surfaces changes.
- Treat future `references/` files as product/process source of truth once they exist. Until then, do not let `AGENTS.md` become the PRD.
- Ask for user direction instead of inventing missing policy, dependency, D-One, packaging, or Qoder CLI decisions.

## Source Of Truth

- `CLAUDE.md`: stable Claude Code implementation guidance.
- `SKILL.md`: TODO / not created yet.
- `SECURITY.md`: TODO / not created yet.
- `references/`: TODO / not created yet.
- `schemas/`: TODO / not created yet.
- `templates/`: TODO / not created yet.
- `scripts/`: TODO / not created yet.

## Verification Bias

Prefer concrete evidence over summaries: schema checks, SVG validation, PPTX relationship inspection, editability checks, security scan output, synthetic demo output, and package/archive inspection when those surfaces exist.
