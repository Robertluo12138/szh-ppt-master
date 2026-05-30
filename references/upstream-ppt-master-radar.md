# Upstream `ppt-master` Radar (Idea-Only)

This file records HIGH-LEVEL idea **categories** that an unrelated
upstream PowerPoint project appears to be exploring. It is a **radar
note**, not a design import.

Nothing in this file copies or paraphrases code, prompts, templates,
examples, images, assets, or wording from `hugohe3/ppt-master`, a
local `ppt-master` checkout, or any other external project. Upstream
may be inspected only at the level of commit summaries and high-level
behavior, for direction; no upstream source file, schema, prompt,
template, image, or asset was copied or paraphrased into this note —
the categories below are described in this repo's own vocabulary so
szh-ppt-master can decide, **on its own contract surface**, whether
and how to address them independently.

## 1. Status

- This document is **idea-only**. Nothing here is a roadmap commitment.
- Every category below requires **clean-room reimplementation** from
  this repo's `references/` and `schemas/` contracts before any code
  may land, per `references/clean-room-policy.md`.
- Real D-One integration remains **UNVERIFIED** (see
  `references/d-one-live-prerequisites.md` §1 and
  `references/d-one-live-trial-packet.md` §3). This document does
  **not** change that status.
- No upstream code, prompts, templates, examples, images, or assets
  have been copied or paraphrased into this repo; upstream is treated
  as a direction radar (commit summaries and high-level behavior)
  only.

## 2. Scope

This file lists idea categories at the level of "topic szh-ppt-master
may want to consider on its own contract surface" only. It does NOT:

- import upstream module names, function signatures, schema fields,
  prompt text, template files, image bytes, or example artifacts;
- mirror upstream sequencing, naming conventions, or commit history;
- add public-network behavior, telemetry, model APIs, image search,
  Qoder runtime, PPTX-export behavior, image generation, or D-One
  calls;
- change any existing pipeline contract, schema, validator,
  generator, exporter, or example in this repo.

If any category below is later picked up as work, the corresponding
design must be drafted from this repo's existing contracts FIRST and
reviewed against `references/clean-room-policy.md` before any code
lands.

## 3. Idea categories (each is idea-only)

### 3.1 Controlled image descriptor / layout taxonomy

- **Idea.** Define an internal taxonomy that constrains what an image
  slot can describe (a closed set of descriptor kinds) **and** what
  role that slot plays in its slide layout (a closed set of layout
  roles), so prompt-assembly and slide composition both operate on a
  fixed vocabulary instead of free text.
- **Why it is interesting here.** Our `image_manifest.json` and
  per-slide `slide_plan.json` already gesture at this through
  controlled fields, and `schemas/d_one_descriptor_vocabulary.schema.json`
  already pins a narrow `color_token` / `geometric_noun` /
  `mood_adjective` / `composition_adjective` set. A broader internal
  taxonomy that also covers **layout role** (e.g. cover hero, KPI
  accent, divider background, table cell decoration) would let
  validators refuse a "wrong slot, wrong descriptor kind" pair at the
  schema layer instead of at runtime.
- **Clean-room status.** **Idea-only.** Any szh-ppt-master version
  must be re-derived from `schemas/image_manifest.schema.json`,
  `schemas/slide_plan.schema.json`,
  `schemas/d_one_descriptor_vocabulary.schema.json`, and
  `references/d-one-image-policy.md`. No upstream taxonomy file,
  enum, or wording may be imported.

### 3.2 Source image asset propagation

- **Idea.** Make the local path from an authoring step that locates
  or produces a candidate image asset to the per-slide image slot
  that will embed it a **controlled, validated handoff**, so the
  asset's safety (path-within-workspace, supported extension, byte
  cap, magic-byte match) is asserted once at the handoff boundary
  and re-checked at every downstream gate.
- **Why it is interesting here.** We already have a pre-D-One local
  asset materialization gate (`scripts/materialize_image_assets.py`)
  and a fail-closed embed gate inside `scripts/export_pptx.py`. The
  propagation contract today is informal — `image_manifest.local_path`
  plus a caller-supplied assets directory. A more explicit "asset
  propagation" contract could record provenance (e.g. `source` value
  on each manifest entry) and let validators refuse a slot whose
  declared source disagrees with the materialized bytes.
- **Clean-room status.** **Idea-only.** Any szh-ppt-master version
  must be re-derived from `references/d-one-image-policy.md`,
  `schemas/image_manifest.schema.json`, the existing materialization
  gate, and the existing exporter embed gate. No upstream asset-
  handoff code, descriptor wording, or provenance enum may be
  imported.

### 3.3 SVG / PPTX export-readback bug probes

- **Idea.** Small, deterministic probes that take a known-good
  render_model, run it through the SVG preview and the PPTX exporter,
  read each output back via an inspector, and assert the original
  primitive set survives intact (bounds, token references, alt text,
  table cells, native shape count, image rel target placement).
- **Why it is interesting here.** The validator surface we have
  (`scripts/validate_pptx_contract.py`, `scripts/inspect_pptx_inventory.py`)
  gates package-level shape and minimal-evidence, but does not yet
  round-trip the controlled render-model surface end-to-end through
  a `slide_plan` → `render_model` → `*.svg` + `*.pptx` → readback
  comparison. A probe suite using **synthetic** fixtures only would
  catch silent shape-loss and silent attribute-drift before they
  leak into a real workspace.
- **Clean-room status.** **Idea-only.** Any szh-ppt-master version
  must be built on the existing `examples/` synthetic fixtures and
  the existing validator / inspector scripts. No upstream probe
  code, golden file, fixture, or wording may be imported.

### 3.4 Chart verification expansion

- **Idea.** Expand the chart surface from today's `chart_placeholder`
  (which fails closed in both the render-model generator and the
  PPTX exporter) toward a small, controlled chart primitive set —
  for example one bar shape and one line shape — whose render_model
  shape AND produced PPTX shape are both verifiable against a
  deterministic readback inventory.
- **Why it is interesting here.** The current contract is
  "`chart_placeholder` is unimplemented and explicitly fails closed
  at the layout gate." A chart slice that ships with its own row in
  `schemas/render_model.schema.json`, its own SVG renderer branch,
  its own native OOXML emit branch in `scripts/export_pptx.py`, and
  matching coverage in `scripts/validate_pptx_contract.py` would
  close one of the largest open gaps in the controlled-primitive
  surface.
- **Clean-room status.** **Idea-only.** Any szh-ppt-master version
  must be re-derived from `schemas/render_model.schema.json`,
  `scripts/export_pptx.py`'s primitive emit conventions, and the
  existing readback validators. No upstream chart schema, OOXML
  fragment, sample chart JSON, or descriptor wording may be
  imported.

### 3.5 Live-preview / visual-edit (later-stage scope)

- **Idea.** At a later stage, offer a live preview of the deck while
  it is being authored, plus a small set of visual edits (re-order
  slides, swap a layout within the controlled set, retitle a slide)
  that round-trip cleanly through the existing artifact contracts.
- **Why this is later-stage here.** Our pipeline today is
  intentionally one-shot and file-based — `slide_plans/*.json` →
  `render_models/*.json` → `svg_previews/*.svg` → `*.pptx`. A
  live-preview / visual-edit layer touches authoring UX, transient
  state, and re-validation policy; it is **out of scope** until the
  controlled-primitive, chart, and round-trip-probe surfaces above
  are stable.
- **Clean-room status.** **Idea-only and de-prioritized.** Any
  szh-ppt-master version must be designed from the existing artifact
  contracts only, must not introduce public-network behavior or
  telemetry, and is gated by an explicit user request well after
  §3.1 – §3.4 land.

## 4. Recommended next three szh-ppt-master tasks

Prioritization deliberately puts descriptor / layout taxonomy and its
validation FIRST, because everything else (asset propagation, chart
verification, round-trip probes, live-preview) tightens once the
taxonomy is named.

Each task's first step is a short design note under `references/`,
**not** code. Implementation follows only after the design note is
reviewed.

1. **(highest priority) Internal descriptor / layout taxonomy
   contract sketch.** Write `references/internal-descriptor-layout-taxonomy.md`
   that re-derives a closed `descriptor_kind × layout_role` grid
   from `schemas/image_manifest.schema.json`,
   `schemas/slide_plan.schema.json`,
   `schemas/d_one_descriptor_vocabulary.schema.json`, and
   `references/d-one-image-policy.md`. Outcome: a single document
   that enumerates every (descriptor_kind, layout_role) pair the
   pipeline will accept, marked **idea-only** until validators are
   wired. (See §3.1.)
2. **Validator-side coverage for the new taxonomy.** Extend
   `scripts/validate_artifacts.py` and `scripts/validate_workspace.py`
   with the cross-checks the taxonomy makes possible (e.g. "an
   `image_slot` whose layout_role is a KPI accent cannot carry a
   `geometric_noun` descriptor"). Outcome: schema-PASS plus
   workspace-PASS must imply taxonomy-PASS for every synthetic
   example under `examples/`. (See §3.1.)
3. **SVG / PPTX round-trip probe on synthetic fixtures.** Add a
   small deterministic probe under `scripts/` that runs each
   synthetic example workspace end-to-end through the existing
   pipeline and asserts the readback inventory matches the source
   render_model's primitive count, alt_text set, and table-cell
   content. Outcome: a single command that fails closed when the
   round-trip drifts. (See §3.3.)

Categories §3.2 (source image asset propagation), §3.4 (chart
verification expansion), and §3.5 (live-preview / visual-edit) are
deferred until the first three land.

## 5. Hard constraints (carry into every follow-up)

- **No copying.** No code, prompts, templates, examples, images,
  assets, or wording from `hugohe3/ppt-master`, a local `ppt-master`
  checkout, or any other external project may be copied, paraphrased,
  ported, or imported. Upstream may be inspected only at the level of
  commit summaries and high-level behavior, for direction. Every
  contract is re-derived from this repo's `references/` and
  `schemas/`.
- **No D-One live calls.** Real D-One integration remains
  **UNVERIFIED**. Nothing here flips that status. See
  `references/d-one-live-prerequisites.md` §1.
- **No new public-network behavior.** No telemetry, model APIs,
  image search, Qoder runtime, or image generation may be added by
  any follow-up scoped against this radar without an explicit,
  separate user request.
- **Synthetic data only.** Any follow-up that adds an example or a
  fixture must use synthetic content per
  `references/clean-room-policy.md` ("Synthetic examples only").

## 6. Cross-references

- `references/clean-room-policy.md` — the clean-room constraint
  this radar lives inside.
- `references/security-policy.md`, `SECURITY.md` — the privacy /
  network gates every follow-up must satisfy.
- `references/d-one-image-policy.md` — the image-policy envelope
  categories §3.1, §3.2, and §3.5 sit inside.
- `references/d-one-live-prerequisites.md` — the live-D-One status
  this radar does NOT change.
- `schemas/image_manifest.schema.json`,
  `schemas/slide_plan.schema.json`,
  `schemas/render_model.schema.json`,
  `schemas/d_one_descriptor_vocabulary.schema.json` — the contracts
  every follow-up re-derives from.
