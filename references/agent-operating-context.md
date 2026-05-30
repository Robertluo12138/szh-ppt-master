# Agent Operating Context

A durable orientation note for any agent — Claude Code, Codex, or a Superset
workspace — picking up work in `szh-ppt-master`. Read it before planning or
implementing so project direction does not depend on chat history. It
complements, and does not replace, `CLAUDE.md` (Claude implementation rules),
`AGENTS.md` (Codex steering), and `SECURITY.md`.

## North Star

Build an internal, clean-room skill that turns prompts, reports, or Markdown
into **editable** PowerPoint decks through a controlled local pipeline:
adaptive planning, controlled layouts, SVG preview, native editable PPTX
output, and fail-closed validation. The aim is to meet the same business need
as a PPT-generation workflow **without** copying the upstream `ppt-master`
implementation. See `references/clean-room-policy.md`.

## Current First-Stage Target

The active lane is narrow on purpose: **local or generated images -> validated
editable-PPT review package**. An operator hands in a folder of
already-produced images and gets back a review package built from native,
editable PowerPoint objects plus its validation reports. This lane is the
near-term product; broader prompt/report-to-deck automation is later roadmap,
not current work.

## Progress Estimate

The first-stage image lane is roughly **85% complete**. The operator
entrypoint, bundle copy, manifest and generated-provenance templates,
approved-plan gating, review-package export, on-disk re-validation, and
native PNG / JPG / JPEG media embedding into the editable PPTX are wired —
the operator image-folder -> review-package lane runs end to end for those
raster formats. The remaining work is real local pilot usability, human
review-loop clarity, broader media formats (SVG / GIF / WebP), real D-One
wiring later, and further polish surfaced by pilot evidence. Treat the number
as a direction estimate, not a precise metric.

## Operator Entrypoint

The implemented one-command lane is:

```
scripts/operator_images_to_review_package.py --images-dir DIR --out-dir OUT
```

It only sequences existing local helpers: it copies the images into a bundle,
writes the starter manifest and generated-provenance sidecar, drives the
approved-plan -> review-package -> on-disk re-check loop, and writes a
top-level README carrying the exact commands it ran. It is local-only.

## Out Of Scope Now

Do not start work on any of these for the current phase unless the user
explicitly expands scope:

- animation and slide transitions;
- audio / voiceover;
- web ingestion, scraping, or public image search;
- model / LLM APIs;
- real D-One wiring (D-One stays a local-image-asset idea only);
- full upstream `ppt-master` feature parity.

## Using Upstream `ppt-master`

Upstream is a **direction radar only**, never a source to copy from. You may
inspect upstream commit summaries and high-level behavior for direction, but
stay clean-room: do not copy, paraphrase, port, or import its code, prompts,
templates, docs, examples, or assets. Borrow at most high-level **idea
categories**, and only ones relevant to image generation or image-asset
handling for the current lane. See `references/upstream-ppt-master-radar.md` and
`references/clean-room-policy.md`.

## Superset Workflow

- **One workspace per task.** Each task runs in its own Superset workspace so
  diffs stay isolated.
- **Claude implements.** Claude Code makes the change narrowly against the task
  prompt and `CLAUDE.md`.
- **Codex reviews the same workspace diff.** Codex reviews the exact diff
  produced in that workspace using `AGENTS.md`.
- **Tests before commit/push.** Run the relevant verification — the narrowest
  real checks covering the changed surface — and confirm it is green before any
  commit or push.
