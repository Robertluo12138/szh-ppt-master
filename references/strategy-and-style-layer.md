# Strategy & Style Layer (the next quality layer above the MVP)

This document defines two clean-room contracts that move szh-ppt-master from
"**source headings + one image each**" toward "**business strategy plan +
brand style profile + editable visual structures**". It is **clean-room** —
nothing here is copied, paraphrased, or summarised from `ppt-master` or any
other external project. The field names, enums, defaults, and validator
gates below were derived from this repo's own contracts
(`schemas/image_request_plan.schema.json`,
`schemas/design_system.schema.json`, `schemas/brand_preset.schema.json`) and
`references/clean-room-policy.md`.

## 1. Where this sits

This is the **next quality layer ABOVE the company-machine MVP**, not a
replacement for it. The MVP (see `references/mvp-quickstart.md`) already runs
end to end: a local source becomes a generation packet, returned images
become a validated editable deck. What the MVP lacks is *design strategy* —
it plans one image per heading and little else, which is why recent output
looked like generic headings with icon-ish decoration.

The strategy & style layer adds the missing planning surface. It is additive
and **opt-in**: every existing MVP command is byte-identical unless you ask
for the new artifacts.

## 2. The quality direction

The core correction is this:

- **Generated images are auxiliary.** More images do not make a better
  business deck; they made the recent output worse. An image earns its place
  on the rare slide (a cover hero), not on every heading.
- **The main quality path is editable visual structure.** Most business
  slides should be built from the controlled render primitives — shapes,
  lines, tables, and KPI blocks — driven by a deliberate per-slide plan.
- **Design is intake, not invention.** A deck should follow a declared brand
  *style profile* (palette, background mode, type scale, motifs, layout
  archetypes) instead of ad-hoc per-run styling.

So the quality recipe is: **brand style profile + per-slide strategy plan +
editable visual structures**, with generated images as an occasional
accent — not the backbone.

## 3. The two contracts

### 3.1 `style_profile` — brand / style intake

`schemas/style_profile.schema.json` (example:
`examples/style_profile_template.json`). A single JSON object capturing the
abstract design direction:

| Field                 | Shape                                                                   |
| --------------------- | ----------------------------------------------------------------------- |
| `schema_version`      | string enum `["1"]`                                                      |
| `profile_id`          | string `^synthetic_[a-z0-9][a-z0-9_]*$` (forced synthetic prefix)        |
| `display_name`        | string, no trademark / URL punctuation                                   |
| `runtime_status`      | string enum `["non_runtime_contract"]` (locks the file as shape-only)    |
| `palette`             | object `{primary, secondary?, accent?, background, text}` hex colours     |
| `background_mode`     | enum `solid` / `subtle_tint` / `gradient_band` / `paneled`              |
| `typography_scale`    | object `{heading, body, scale_ratio}` (CSS chain + modular ratio)        |
| `page_motifs`         | array of abstract motifs (`corner_accent`, `footer_band`, `card_grid`…)  |
| `layout_archetypes`   | array from the shared visual-structure vocabulary (§3.2)                 |
| `image_usage_policy`  | object `{mode, max_image_slides_ratio, editable_structures_first}`        |
| `notes`               | optional, terse, synthetic                                               |

Like `brand_preset`, this is **not runtime brand application** — no script
projects a `style_profile` onto a `design_system` today, so every profile
pins `runtime_status: "non_runtime_contract"`. It is the *intake* the runtime
will read once that projection is built (a separate, user-approved step).

### 3.2 `strategy_plan` — one strategy record per slide

`schemas/strategy_plan.schema.json` (example:
`examples/strategy_plan_template.json`). The plan that sits between the deck
outline and per-slide artwork. Each `slides[]` record carries:

| Field              | Shape                                                                                  |
| ------------------ | -------------------------------------------------------------------------------------- |
| `slide_index`      | integer, unique + contiguous `1..N`                                                     |
| `slide_title`      | string                                                                                  |
| `core_message`     | the single point the slide must land                                                    |
| `page_type`        | enum `cover` / `section` / `content` / `data` / `summary` / `closing`                   |
| `key_metrics`      | optional array of `{label, value}` to foreground as editable KPI / table content        |
| `visual_structure` | enum (the shared vocabulary, §below)                                                     |
| `image_need`       | enum `none` / `optional` / `recommended` — **no `required` value**                      |

The **`visual_structure` vocabulary** is the heart of the layer — every value
is realisable from editable primitives, no generated image required:
`cover_hero`, `executive_summary_cards`, `kpi_cluster`, `comparison_panel`,
`metric_table`, `audience_segment`, `competitor_flow`, `product_strategy`,
`roadmap`, `closing_summary`. `style_profile.layout_archetypes` shares this
exact vocabulary, so a future validator can check that every planned slide's
structure is one the chosen style declares.

## 4. Emitting a starter strategy plan today

The planning helper `scripts/init_strategy_plan.py` projects a **starter**
`strategy_plan.json` from a generation packet's `image_request_plan.json`
(one record per heading). It is heading-level only — it reads no source body
text, infers no metrics, and designs no deck. It assigns a conservative
starter (cover → `cover_hero`, last → `closing_summary`, middle →
`executive_summary_cards`) and seeds `core_message` from the title for a
human or agent to refine.

Two ways to produce one:

```bash
# A) standalone, from an existing packet
python3 scripts/init_strategy_plan.py --packet-dir <out-dir>/generation_packet

# B) wired into the MVP first run, BEFORE image generation (opt-in)
python3 scripts/run_mvp_image_to_ppt.py \
  --source examples/mvp_demo_source.md --out-dir /tmp/szh-mvp --emit-strategy-plan
```

Both write `<...>/generation_packet/strategy_plan.json`. The flag is opt-in;
without it the packet is byte-identical to prior runs, and it has no effect
on the `--resume` step.

## 5. Image policy: editable structures first

The bias against over-using images is **encoded in the contracts**, not left
to prose:

- `strategy_plan.image_need` has **no `required` value** — a generated image
  is never mandatory. The starter projection sets `image_need: "none"` on
  every slide except the cover (the one `recommended` slot).
- `style_profile.image_usage_policy.mode` has **no image-first option**
  (`auxiliary` / `minimal` / `none` only), `editable_structures_first` is
  locked `true`, and `max_image_slides_ratio` caps the fraction of slides
  that may carry a generated image.

So the layer pushes *fewer* images than the image-per-heading bridge, and
points the remaining quality budget at editable visual structures.

## 6. Scope and clean-room boundary

This layer **does not**: read or extract source body text, infer real
metrics, design a deck from raw source, project a `style_profile` onto a
runtime `design_system`, generate render_models / SVG / PPTX, or call any
network (no D-One, model API, MCP, telemetry, or image search). It adds no
animation, audio, video, or SVG editor. It introduces no proprietary assets,
no copied template slides, and no public URLs. The `synthetic_` prefix on
`profile_id` and the `non_runtime_contract` literal keep the style profile
shape-only at the file boundary. See `references/clean-room-policy.md`,
`references/security-policy.md`, and `SECURITY.md`.

## 7. Verification

```bash
# the two contracts (positive examples + every fail-closed invariant)
python3 scripts/validate_strategy_layer.py --self-test

# the starter projection (pure + a real-packet round-trip)
python3 scripts/init_strategy_plan.py --self-test

# single-artifact structural checks
python3 scripts/validate_artifacts.py \
  --schema schemas/style_profile.schema.json examples/style_profile_template.json
python3 scripts/validate_strategy_layer.py \
  --strategy-plan examples/strategy_plan_template.json

# the MVP wrapper, including the --emit-strategy-plan wiring
python3 scripts/run_mvp_image_to_ppt.py --self-test
```

## 8. Recommended next step

The natural follow-on is **strategy-plan-driven render models**: teach the
deterministic `scripts/generate_render_models.py` path to consume a
`strategy_plan.json` so that each `visual_structure` archetype emits its
editable layout (cards, KPI cluster, comparison panel, metric table) from the
controlled primitives — turning the plan into real editable slides instead of
heading + image. That is a separate, user-approved scope step; this layer
only adds the planning and style-intake contracts it would consume.
