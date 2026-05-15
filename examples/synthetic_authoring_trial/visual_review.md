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

## Refinements applied

The scoped follow-up pass took the coordinated-fixture-refresh path:
the generator + layout JSONs change in lock-step with a regeneration
of the committed `examples/synthetic_*/render_models/*.json` and
`svg_previews/*.svg` so `validate_workspace` continues to enforce
`primitive.bounds ⊆ slot.bounds` against the new geometry. The trial
deck length stays at 7 slides; no new layouts, primitives, schemas,
or templates were introduced.

| # | File | Change |
|---|---|---|
| 1 | `scripts/generate_render_models.py` — `_list_item_bounds` + new `LIST_ITEM_MAX_H = 96` | Clamp every list item to 96px so a small N (2–3 bullets) packs at the top of the slot instead of sprawling. Trailing whitespace below is intentional. |
| 2 | `scripts/generate_render_models.py` — `_generate_timeline` + new `TIMELINE_*` constants | Emit a structural vertical axis line + one filled-ellipse marker per step, then render each step's text to the right of the marker (no bullet prefix; the marker replaces it). Axis + markers are structural shapes / lines (no `slot_id`); only the per-step text remains slot-bound to `timeline_items`, so `slot.primitive_kind=text` still binds the right primitives. |
| 3 | `scripts/generate_render_models.py` — `_generate_kpi_dashboard` (+ `KPI_TILE_CORNER_RADIUS`, tightened `KPI_INSET_Y`) and `templates/layouts/business_review/layouts/kpi_dashboard.json` | Shrink the `kpis` slot from `h=600` to `h=200` so the slot wraps the actual KPI tile content (label + value + optional delta) instead of reserving a 600px-tall empty band. Replace the single outer decorative band with one rounded-rect card per tile (structural shape painted at each KPI tile's bounds) so the dashboard reads as a grid of cards. |
| 4 | `scripts/generate_render_models.py` — `LAYOUT_FALLBACK_BOUNDS["key_message"]` and `templates/layouts/business_review/layouts/key_message.json` | Shrink `message` bounds from `h=360` to `h=140` and pull `supporting_text` up from `y=700, h=280` to `y=440, h=180`. The callout no longer renders as a single-line statement floating at the top of a 360px-tall empty rectangle. |
| 5 | `scripts/generate_render_models.py` — `COVER_FALLBACK_BOUNDS` and `templates/layouts/business_review/layouts/cover.json` | Tighten the cover title/subtitle lockup: shrink `title.h` from 200 to 100, declare `subtitle`/`presenter`/`date`/`accent` bounds directly in the layout (the generator no longer relies on its forward-compat fallback for cover slots), and pull `subtitle` up from `y=540` to `y=460`. |
| 6 | `examples/synthetic_authoring_trial/slide_specs/01_cover.json` | (Carried from the prior pass.) Replace `"<placeholder-date>"` with `"Season 24 review window"` — still a synthetic placeholder per the bundle README, but reads as deliberate. |

## Fixture refresh

The geometry changes invalidated the committed example fixtures, so
they were regenerated in-place against the new generator + layouts:

- `examples/synthetic_20_page_business_review/render_models/*.json` (20 files)
- `examples/synthetic_20_page_business_review/svg_previews/*.svg`     (20 files)
- `examples/synthetic_8_page_product_brief/render_models/*.json`      (8 files)
- `examples/synthetic_8_page_product_brief/svg_previews/*.svg`        (8 files)

These are NOT trial outputs; they ship with the repo so
`validate_workspace` can prove generator/template alignment against
real worked examples. Both workspaces still validate clean against
`scripts/validate_workspace.py`, and `scripts/validate_scaffold.py`
continues to pass. The trial's own workspace, PPTX, JSON report, and
contact sheet remain OUTSIDE the repo (every trial run writes them to
`/tmp/sat_*`).

## After-refinement findings

After the refinements above, the pipeline still runs green —
`validate_authoring_bundle`, every stage of `run_explicit_pipeline`,
`validate_visual_quality`, and the container + minimal-evidence PPTX
gates all pass. The single `text_density_low` warning on slide 5
remains (the validator measures `text` primitives only; the KPI tiles
are `kpi` primitives, so the metric does not change with this work).

Concrete before / after on the gaps above (all measurements via the
JSON visual-quality report and per-slide render_model inspection):

| Gap | Before | After |
|---|---|---|
| 1. List items stretched | slide 2: 3 bullets ~193px apart in a 580px slot; slide 4: 2 bullets ~340px apart in a 680px column; slide 6: 4 steps ~175px apart in a 700px slot; slide 7: 2 CTAs ~300px apart in a 600px slot | every list item is exactly 96px tall and packs at the top of the slot (slide 2 stack 288px tall in a 580px slot; slide 4 columns 192px tall in 680px; slide 7 stack 192px tall in 600px). Trailing whitespace below is intentional. |
| 2. KPI band mostly empty | `kpis` slot `h=600`, ~80px of content at the top, ~520px of empty band below | `kpis` slot `h=200`; per-tile rounded-rect card (one per KPI) wraps each tile. No outer band. Slide 5 primitive count: 5 → 7. |
| 3. Cover title/subtitle gap | title bound `h=200`, subtitle fallback `y=540` → ~202px between text baselines | title bound `h=100`, subtitle declared at `y=460` → ~122px between baselines. Slide 1 primitive count unchanged at 5; geometry only. |
| 4. Key-message callout empty | message bound `h=360`, single-line text hugging the top | message bound `h=140` (callout wraps its line); `supporting_text` pulled up to `y=440, h=180`. Slide 3 primitive count unchanged at 4. |
| 5. Timeline reads as plain bullet list | only the slide title distinguishes it from `agenda`; per-step bullets aligned to a list slot | structural vertical axis line + filled ellipse marker per step + step text to the right of the marker. Slide 6 primitive count: 5 → 10. |
| 6. Placeholder-looking date | (already addressed in prior pass) | (unchanged) — `Season 24 review window`. |

The after-change visual-quality report (`/tmp/sat_visual.json`)
records: `0 errors, 1 warning` (the same informational `text_density_low`
on the KPI dashboard, unchanged from the baseline — discussed below).

## Remaining visual gaps (not fixed by this pass)

These remain visible in the contact sheet but are out of scope for the
current narrow geometry pass; they would require a new primitive, a
new template family, a different design-system default, or a
validator surface change. Recording them so the next pass can pick
them up:

- **Cover has no visible structural rule under the title.** The
  decorative kicker bar above the title is still the cover's only
  structural flourish. Adding a thin rule under the title (mirroring
  the `section_divider` rule) would tighten the lockup; deferred —
  it would add a structural primitive and another fallback constant
  pair.
- **`text_density_low` on the KPI dashboard.** The visual-quality
  gate measures `text` primitives only and does not count `kpi`
  content. Either the metric or the gate's WARN threshold should
  treat `kpi` primitives as text-bearing; deferred — it is a
  validator surface, not a deck surface.
- **Body type weight.** Body runs at 14pt is on the small side for a
  1920×1080 canvas. Raising it to 16 – 18pt would improve the
  legibility of every bulleted slide; deferred — it would change the
  default design system and touch every committed example
  workspace's visual baseline.
- **Timeline marker style.** Markers are simple filled ellipses with
  no per-step badge or date. Adding numeric step badges or a
  date-strip alongside the marker would be a generator change with
  its own contract; deferred.
- **KPI tile dividers within a card.** Each card carries the label,
  value, and (optional) delta stacked as plain text; no rule between
  label and value, no delta-direction styling (green/red, up/down).
  Adding any of those would extend the controlled primitive set;
  deferred.

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
