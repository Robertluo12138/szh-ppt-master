# Synthetic Authoring Trial — Visual Review

**Scope.** A narrow visual baseline review of the seven-slide synthetic deck
produced by `scripts/run_explicit_pipeline.py` from the bundle in this
directory. Findings inform only repo-owned style/layout/template
refinements; the deck length, layout vocabulary, and pipeline contracts are
unchanged.

This file is committed; the workspace, PPTX, JSON report, and contact sheet
that produced it are intentionally NOT — every run writes them OUTSIDE the
repo (see this directory's `README.md`).

## Trial commands

The trial is run twice (before and after the minimal refinement):

```bash
# Pre-pipeline structural gate
env PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_authoring_bundle.py \
  --source examples/synthetic_authoring_trial/source.md \
  --source-id synthetic_trial_source \
  --title "Synthetic Authoring Trial" \
  --audience "Internal pipeline smoke-test reviewers" \
  --objective "Exercise the explicit-input authoring bundle gate end-to-end on a synthetic, non-sensitive narrative." \
  --tone neutral-professional \
  --language en \
  --approximate-slide-count 7 \
  --plan-spec examples/synthetic_authoring_trial/plan_spec.json \
  --design-system-spec examples/synthetic_authoring_trial/design_system_spec.json \
  --template-root templates/layouts \
  --slide-specs-dir examples/synthetic_authoring_trial/slide_specs \
  --image-manifest-spec examples/synthetic_authoring_trial/image_manifest_spec.json

# End-to-end pipeline (workspace + PPTX + report all OUTSIDE the repo)
env PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_explicit_pipeline.py \
  --workspace /tmp/sat_ws \
  ...same flags as above... \
  --output /tmp/sat.pptx \
  --report-dir /tmp/sat_report

# Visual quality gate (JSON + HTML contact sheet outside the repo)
env PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_visual_quality.py \
  --workspace /tmp/sat_ws --output /tmp/sat_visual.json
env PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_visual_quality.py \
  --workspace /tmp/sat_ws --output /tmp/sat_visual.html
```

The pipeline self-tests, `validate_authoring_bundle --self-test`,
`validate_visual_quality --self-test`, `run_explicit_pipeline --self-test`,
`validate_scaffold`, and `validate_pptx_contract --self-test` are run
separately as part of repo verification.

## Baseline findings (before any refinement)

The pipeline runs green — `validate_authoring_bundle`, every stage of
`run_explicit_pipeline`, and the OOXML container + minimal-evidence gates
in `validate_pptx_contract` all pass. The visual quality gate reports `0
errors, 1 warning`: slide 5 (`kpi_dashboard`) trips `text_density_low`
because the validator counts only `text` primitives (the three KPI tiles
on this slide are rendered as `kpi` primitives, not as text). The warning
is informational here.

Inspecting `svg_previews/*.svg` and the HTML contact sheet surfaces five
concrete visual gaps that are not flagged by any automated check today:

1. **List items stretched to fill the entire body slot (slides 2, 4, 6, 7).**
   `_list_item_bounds` in `scripts/generate_render_models.py` divides the
   slot height evenly across N items, regardless of how few items the
   slide carries. For two bullets in a 680px-tall column slot, item 1 sits
   at the top and item 2 at the bottom with a ~340px empty band between
   them. The deck looks airy / under-filled even though every bound is
   legal and every primitive type is correct.
   - slide 2 (`executive_summary`): three key-points spaced ~193px apart
     across a 580px slot
   - slide 4 (`two_column`): two bullets per column spaced ~340px apart
     across a 680px slot
   - slide 6 (`timeline`): four steps spaced ~175px apart across a 700px
     slot — and the timeline renders as a plain bulleted list with no
     visible axis, indistinguishable from a regular list
   - slide 7 (`conclusion`): two CTA bullets spaced ~300px apart across a
     600px slot

2. **KPI dashboard band is mostly empty (slide 5).** The decorative
   rounded-rect background spans the full 600px-tall `kpis` slot, but
   the actual KPI tiles only occupy the top ~80px of that band (label +
   value lines). The bottom ~500px of the band is empty space inside a
   visible border, which reads as a broken placeholder.

3. **Cover has a large vertical dead zone between title and subtitle.**
   The title bound is 200px tall with the text rendered near the top
   (baseline y=357), and the subtitle falls back to y=540. The result is
   ~180px of empty space between the title and subtitle baselines on a
   slide that only carries four short text runs.

4. **Key-message callout box is mostly empty inside (slide 3).** The
   `message` slot bound is 360px tall, but the single-line callout text
   hugs the top edge (baseline y=297, only 37px below the box top). The
   bottom ~300px of the callout rectangle is empty.

5. **Cover date is literally `<placeholder-date>`.** The cover slide spec
   carries `"content": "<placeholder-date>"` for the `date` block. The
   string renders verbatim and reads as obviously unfinished — the
   bundle README already documents that every value is a synthetic
   placeholder; the date string can be a synthetic-but-specific value
   without changing the trial's "no real data" guarantee.

## Why most refinements are deferred

Gaps #1 – #4 all sit downstream of either the render-model generator
(`scripts/generate_render_models.py`) or the layout slot bounds in
`templates/layouts/business_review/layouts/*.json`. The committed example
workspaces `examples/synthetic_20_page_business_review` and
`examples/synthetic_8_page_product_brief` already ship `render_models/`
and `svg_previews/` that were generated against the current generator
and current layouts. Any change to the generator's geometry — including
the obvious "cap each list item at ~96px so a 2-bullet column doesn't
sprawl 340px wide" fix — produces render_models that differ from those
committed snapshots, and `validate_workspace` enforces
`primitive.bounds ⊆ slot.bounds` against the layout slots, so shrinking
a slot's bounds without regenerating the committed render_models also
fails. Refreshing those committed `render_models/` and `svg_previews/`
artifacts in the same change would mean committing generated pipeline
outputs, which this trial's scope rules explicitly forbid (`Do not
commit generated PPTX, HTML, JSON reports, render_models, svg_previews,
or pipeline outputs.`).

Gaps #1 – #4 are therefore deferred to a follow-up change that picks
between two paths: (a) accept a coordinated fixture refresh of the
committed `render_models/` and `svg_previews/`, or (b) leave the
shipped examples on the legacy layout while introducing the refined
layout under a new template family. Neither path is "minimal" for this
trial.

## Refinement applied

That leaves one minimal refinement that improves the deck without
touching the generator's geometry or the committed example fixtures:

| # | File | Change |
|---|---|---|
| 5 | `examples/synthetic_authoring_trial/slide_specs/01_cover.json` | Replace `"<placeholder-date>"` with `"Season 24 review window"` — still a synthetic placeholder per the bundle README, but reads as deliberate. |

## After-refinement findings

After the refinement above, the pipeline still runs green —
`validate_authoring_bundle`, every stage of `run_explicit_pipeline`,
`validate_visual_quality`, and the container + minimal-evidence PPTX
gates all pass. The single `text_density_low` warning on slide 5
remains (the validator measures `text` primitives only; the KPI tiles
are `kpi` primitives, so the metric does not change with this work).

Concrete before / after on the gaps above:

| Gap | Before | After |
|---|---|---|
| 1. List items stretched | bullets 175 – 340px apart on slides 2/4/6/7 | unchanged — deferred (would require regenerating committed example render_models, which the scope forbids) |
| 2. KPI band mostly empty | 600px decorative band, ~80px content | unchanged — deferred (same reason) |
| 3. Cover title/subtitle gap | ~180px empty band between baselines | unchanged — deferred (same reason) |
| 4. Key-message callout empty | 360px box, single-line text hugging top | unchanged — deferred (same reason) |
| 5. Placeholder-looking date | literal `<placeholder-date>` | synthetic-but-specific `Season 24 review window` |

## Remaining visual gaps (not fixed by this pass)

These remain visible in the contact sheet but are out of scope for a
minimal style pass; they require either a coordinated fixture refresh,
a new template family, or new primitives. Recording them so the next
pass can pick them up:

- **Geometry fixes for gaps #1 – #4.** Each is a one- or two-line edit
  in the relevant generator helper / layout JSON. They are deferred as
  one bundle until a follow-up change that also refreshes the committed
  `examples/synthetic_*/render_models/*.json` and the matching
  `svg_previews/*.svg` files in the same commit (so `validate_workspace`
  continues to pass and the shipped examples stop being stale relative
  to the generator). The minimal-but-self-coherent shape of that
  follow-up is: (a) add `LIST_ITEM_MAX_H ≈ 96` and clamp in
  `_list_item_bounds`, (b) shrink `key_message.message` bounds to
  ~h=140 and pull `supporting_text` up to ~y=440, h=180, (c) shrink
  `kpi_dashboard.kpis` to ~h=320 and lower its top, (d) declare bounds
  on `cover.subtitle`/`presenter`/`date` so the renderer stops relying
  on the generator's forward-compat fallback table.
- **Timeline reads as a plain bullet list.** The `timeline` layout has
  no axis primitive, no step badges, no dates — the only visual
  difference from a plain `agenda` slide is the slide title. Adding a
  structural axis line and step markers would be a generator change
  with its own contract (primitives, schema implications); deferred.
- **Cover has no visible structural rule under the title.** The
  decorative kicker bar above the title is the cover's only structural
  flourish; the title/subtitle/presenter/date stack reads as a single
  body block. Adding a thin rule under the title (mirroring the
  `section_divider` rule) would tighten the lockup; deferred — it
  would add a structural primitive and a fallback constant pair.
- **KPI tiles still lack per-tile cards.** Even after the band shrinks,
  the three tiles would still share one outer rectangle. Per-tile
  rounded-rect backgrounds would make the dashboard read as a grid;
  deferred — it would add one shape primitive per tile in
  `_generate_kpi_dashboard`.
- **`text_density_low` on the KPI dashboard.** The visual-quality gate
  measures `text` primitives only and does not count `kpi` content.
  Either the metric or the gate's WARN threshold should treat `kpi`
  primitives as text-bearing; deferred — it is a validator surface,
  not a deck surface.
- **Body type weight.** Body runs at 14pt is on the small side for a
  1920×1080 canvas. Raising it to 16 – 18pt would improve the
  legibility of every bulleted slide; deferred — it would change the
  default design system and touch every committed example workspace's
  visual baseline.

## What this review does NOT do

- It does not change the deck length (still 7), the layout vocabulary,
  the controlled primitive set, the per-stage gates, the authoring
  bundle contract, the PPTX exporter, or the design-system schema.
- It does not add charts, an arbitrary-SVG parser, a new template
  family, public-network behaviour, telemetry, image generation, or
  any external service.
- It does not paraphrase any prior implementation or sibling project.
- It does not commit generated PPTX, HTML reports, JSON reports,
  render_models, or `svg_previews/` — every run writes those OUTSIDE
  the repo (see this directory's `README.md`).
