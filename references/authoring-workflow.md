# Agent Authoring Workflow (Stage 2-6 Specs)

This doc explains how an **internal agent** should read a locally prepared source, the user's request, and the repo's contracts, and then **author** the five spec files that the deterministic explicit-input pipeline consumes:

- `--title` / `--audience` / `--objective` (and optional `--tone` / `--language` / `--approximate-slide-count`) — deck_brief metadata flags;
- `--plan-spec <deck_plan.json candidate>` — Stage-3 plan spec;
- `--design-system-spec <design_system.json candidate>` OR `--theme-from-template` — Stage-4 design choice;
- `--slide-specs-dir <dir of slide_plan candidates>` — Stage-5 per-slide spec bundle;
- `--image-manifest-spec <image_manifest.json candidate>` — Stage-6 image manifest spec.

The agent hands those off to `scripts/run_explicit_pipeline.py` (or `scripts/prepare_workspace.py` followed by `scripts/run_pipeline.py`, or the per-stage chain `scripts/init_workspace.py` → `init_deck_brief.py` → `init_deck_plan.py` → `init_design_system.py` → `init_slide_plans.py` → `init_image_manifest.py` → `scripts/run_pipeline.py`), which then produces a validated editable PPTX deterministically.

## Three surfaces, kept separate

This repo intentionally separates three concerns. Mixing them is the failure mode this doc exists to prevent.

| Surface | What it does | Where it lives | Status |
|---|---|---|---|
| **Implemented explicit-input runtime pipeline** | Validates the five authored specs, writes Stage-1-to-6 artifacts, then runs Stage 7-10 (`render_models/` → `svg_previews/` → editable `.pptx` → contract validator). Reads only what the caller passes. | Six per-stage helpers (`scripts/init_workspace.py`, `init_deck_brief.py`, `init_deck_plan.py`, `init_design_system.py`, `init_slide_plans.py`, `init_image_manifest.py`), the Stage-1-to-6 orchestrator `scripts/prepare_workspace.py`, the Stage-7-to-10 pipeline runner `scripts/run_pipeline.py`, and the Stage-1-to-10 end-to-end orchestrator `scripts/run_explicit_pipeline.py`. Every script ships its own `--self-test`. | Implemented for the supported layout / primitive subset. |
| **Agent authoring workflow** | Reads `input/source.md` and the user's request, decides the deck's shape, and **emits** the spec files the pipeline consumes. | This document. Performed by an internal agent (a human or LLM operator working inside this repo's policies). | Documented here. There is **no** deterministic code that performs this stage — and there will not be without explicit user approval. |
| **NOT implemented** | Automatic extraction of `deck_brief` / `deck_plan` / `design_system` / `slide_plan` / `image_manifest` content directly from `input/source.md`; D-One (or any) image generation; Qoder runtime packaging; any model API call from any script in this repo; any public network / telemetry / external service. | Out of scope for the current code base. Adding any of it requires explicit user approval and its own reference doc. | Blocker for end-to-end "prompt → PPTX". The agent must do the authoring; the runtime pipeline must not be quietly extended to do it. |

The deterministic pipeline **does not** parse `input/source.md` for business content, **does not** invent any `deck_brief` / `deck_plan` / `design_system` / `slide_plan` / `image_manifest` content, **does not** call D-One / Qoder / any public network / image generation / telemetry / external service, and **does not** make any model API call. It is a contract validator + render + export chain. The agent fills the gap between the raw source and the deterministic pipeline's strict, schema-locked inputs.

This means: **a passing `scripts/run_explicit_pipeline.py` (or per-stage chain) run is not, by itself, evidence that an automatic "prompt-to-PPTX" stack exists**. It is evidence that the authored specs round-trip cleanly to a validated PPTX. The authoring quality of the deck (truthfulness, source fidelity, density, layout fit) is the agent's responsibility — the gates the runtime pipeline enforces are structural.

## Pre-conditions

Before the agent starts authoring:

- The user has supplied (or pointed to) a local `.md` or `.txt` source file. The repo's Stage-1 helper, `scripts/init_workspace.py`, will normalize it to `input/source.md` inside the workspace. The agent may invoke that helper itself for inspection, OR it may pass `--source <path>` straight to the deterministic pipeline — the same Stage-1 step runs there too.
- The agent has read `CLAUDE.md`, `SECURITY.md`, `references/clean-room-policy.md`, `references/writing-guide.md`, `references/d-one-image-policy.md`, and this file.
- A `--template-root` is available (e.g. `templates/layouts/`). The agent must NOT hardcode `business_review` as a default — it is the template the current repo ships, not the product's identity.
- No public network access is required, used, or assumed at any point.

## Authoring steps

The five spec authoring steps below are in canonical order. The deterministic pipeline runs them in this same order, so an earlier step's invariants are pre-conditions for the next.

### Step A. deck_brief metadata

**Inputs the agent reads.** The user's request, `input/source.md`, and the operator's policy file (clean-room, security).

**Outputs the agent produces.** Three required values (passed as CLI flags), plus three optional ones:

- `--title` — short, declarative, ≤ 8 words (see `references/writing-guide.md`). Trace it to the source or the user's request, never invent.
- `--audience` — who reads this deck. Names of real people / accounts are forbidden; use role / function / forum.
- `--objective` — one sentence on what the deck is meant to do. Trace it to the user's request.
- `--tone` (optional) — `neutral-professional` is the default style; only override if the brief calls for it.
- `--language` (optional) — defaults to the source language; declare it when the source is multilingual.
- `--approximate-slide-count` (optional) — see Step B's note on adaptive sizing. Pass it only when the user explicitly stated a number; otherwise let the planner choose.

**What the agent does NOT do here.** `scripts/init_deck_brief.py` sets `source_refs = [source_manifest.source.id]` automatically; the agent does not pass it. The agent does not pass `key_messages` / `constraints` via CLI — those fields are part of the `deck_brief.schema.json` shape, but the current `init_deck_brief.py` CLI only forwards the six fields above. If the brief shape needs more, that is a TODO; do **not** silently extend the helper.

**Quality checks at this step.**

- The title / audience / objective each trace to a specific section of the source or the user's request. The agent records that trace in its working notes (not in any artifact under `--workspace`).
- No raw source paragraphs are copied into any of the six fields. Use compressed phrasing, not quotation.
- No customer / account / employee name appears anywhere unless the user explicitly confirmed it is safe to include.

### Step B. `--plan-spec` (deck_plan candidate)

The deck_plan is the central planning artifact: it picks **target slide count**, **section structure**, **per-slide layout**, **per-slide density**, and **per-slide `source_refs`**. The deterministic helper (`scripts/init_deck_plan.py`) only validates and writes this spec — it does **not** plan a deck.

**Shape of the spec.** A single JSON file whose object root matches `schemas/deck_plan.schema.json`. The agent authors:

```jsonc
{
  "template": "<name-of-template-folder-under-template-root>",
  "planning": {
    "planned_slide_count": <N>,                 // must equal len(slides)
    "rationale": "<one short sentence on length/structure choice>"
  },
  "sections": [
    {
      "id": "<short_slug>",
      "title": "<section title>",
      "summary": "<one sentence>",
      "slide_indices": [<1-based slide indices in this section>]
    }
    // ... every slide index from 1..N belongs to exactly one section
  ],
  "slides": [
    {
      "index": 1,
      "layout": "<one of template.layouts>",
      "title": "<short, traceable to source>",
      "section_id": "<id of an entry in sections[]>",
      "summary": "<one sentence on what this slide carries>",
      "density": "low" | "medium" | "high",
      "source_refs": ["<id from deck_brief.source_refs>", ...]
    }
    // ... one entry per slide, index 1..N contiguous, unique
  ]
}
```

**Adaptive shape rules.**

- Slide count is **not** fixed. Expected capacity range is **12–25 slides** as guidance only; a real run may produce 6, 8, 10, 15, 20, 25, or another reasonable number depending on the brief.
- There is **no universal sequence**. Agenda, section dividers, KPI dashboards, timelines, comparison tables, and conclusion slides are layouts the planner **may** use, not slots it **must** fill.
- `business_review` is the template the current repo ships. It is **not** a product default — pass whichever template name the workspace's `--template-root` provides, and prefer the template whose layout vocabulary fits the brief.

**Layout choices.** Pick `layout` per slide from the chosen template's `template.json::layouts`. The render-model generator's `SUPPORTED_LAYOUTS` allow-list is the layouts it can produce a render_model for end-to-end today; a layout outside that allow-list is not a generator-side fatal — the generator reports `[SKIP] slide N: layout 'X' not implemented` and exits 0, leaving the workspace without a render_model for that slide — but the PPTX exporter then fails closed at its 1:1 deck_plan ↔ render_model coverage gate before any `.pptx` is written. The agent should therefore pick only from the intersection of (a) the template's declared `template.layouts` and (b) the generator's `SUPPORTED_LAYOUTS` set listed in `SKILL.md` ("What exists in this repo today"). If a slide truly needs a layout outside that intersection, mark it as a blocker and stop — do not author a slide that the runtime pipeline cannot render.

**`source_refs` rules.**

- `deck_brief.source_refs` is the allow-list for the whole deck (the deterministic helper sets it to `[source_manifest.source.id]` by default).
- Every `slides[].source_refs` value must be a member of `deck_brief.source_refs`. The agent **must** assign a non-empty list to every slide; a slide with no traceable source coverage is a defect.
- The agent must not invent additional source ids that the brief does not declare.

**Quality checks at this step (the agent runs these before invoking the pipeline).**

- `planning.planned_slide_count == len(slides)`.
- `slides[].index` is unique and contiguous over `1..N`.
- `sections[].slide_indices` partitions the set `{1..N}` exactly (no duplicates across sections, no missing indices, no orphan indices).
- Every `slides[].section_id` resolves to an entry in `sections[]`, and that section's `slide_indices` lists the slide's index.
- Every `slides[].source_refs` is non-empty and ⊆ `deck_brief.source_refs`.
- Every `slides[].layout` ∈ `template.layouts` and ∈ the render-model generator's supported layout set.
- The rationale is a short, source-grounded sentence — not a marketing claim.

The deterministic pipeline re-enforces all of these; running them at authoring time saves a six-stage retry.

### Step C. Design system (`--design-system-spec` OR `--theme-from-template`)

Exactly one of two paths. The deterministic helper (`scripts/init_design_system.py`) refuses both / neither.

**Default path — `--theme-from-template`.** Project the palette / typography / grid from the theme of the template named in the deck_plan. This is the preferred path; it keeps the deck visually consistent with the template family.

**Override path — `--design-system-spec <design_system.json>`.** Use only when the brief or the user's request requires a custom palette / typography / grid that the template's theme cannot represent. The spec must conform to `schemas/design_system.schema.json`:

- `palette.*` hex colors (`^#[0-9A-Fa-f]{6}$`); keys are at least `primary` / `secondary` / `accent` / `background` / `text`.
- `typography.heading` / `typography.body` each carry a CSS-style font fallback chain and a positive numeric `size_pt`.
- `grid.width_px` / `grid.height_px` are positive integers; `grid.margin_px` is non-negative.

**The agent NEVER infers design tokens from raw source text.** Tokens come from the explicit spec OR from the named template's theme — never from "I read the source and it felt corporate-blue."

**Quality checks at this step.**

- Exactly one of the two paths is chosen.
- If `--theme-from-template`, the workspace's template root resolves the template named in the deck_plan.
- If `--design-system-spec`, the spec validates against the design_system schema in memory before it goes on disk.

### Step D. `--slide-specs-dir` (slide_plan candidates)

For every slide in the deck_plan, the agent authors a `*.json` file in `--slide-specs-dir/`. The deterministic helper (`scripts/init_slide_plans.py`) then validates each, cross-checks 1:1 coverage against `deck_plan.slides[]`, and writes the canonical `<workspace>/slide_plans/<idx:02d>_<layout>.json`.

**Two vocabularies, don't conflate them.** The agent authors at the **slide_plan / layout-slot** level. Both `slide_plan.blocks[].kind` (`schemas/slide_plan.schema.json`) and `layout.slots[].type` (`schemas/layout.schema.json`) share one enum: `["text", "list", "callout", "kpi", "table", "image_ref", "chart_ref"]`. The Stage-7 render-model generator then projects each slide_plan into a **render_model**, whose primitive `kind` enum (`schemas/render_model.schema.json`) is different: `["text", "shape", "line", "image_slot", "table", "kpi", "chart_placeholder"]`. The default slot-type → primitive-kind mapping is `text` / `list` / `callout` → `text`; `kpi` → `kpi`; `table` → `table`; `image_ref` → `image_slot`; `chart_ref` → `chart_placeholder` (a layout slot may override via `slot.primitive_kind`). The agent never writes `image_slot`, `line`, `shape`, or `chart_placeholder` directly in a slide_plan — those are render-model primitive kinds, not block kinds.

**Shape.** Each spec matches `schemas/slide_plan.schema.json`. The block object's `additionalProperties` is `false`, so a block carries only `kind`, optional `id`, and optional `content`:

```jsonc
{
  "index": <slide index from deck_plan.slides[]>,
  "layout": "<same layout as the matching deck_plan slide>",
  "title": "<same title as the matching deck_plan slide>",
  // optional: "subtitle": "...", "notes": "..."
  "blocks": [
    { "id": "<slot_id>", "kind": "text",      "content": "<short string>" },
    { "id": "<slot_id>", "kind": "list",      "content": ["<short string>", "<short string>"] },
    { "id": "<slot_id>", "kind": "callout",   "content": "<short string>" },
    { "id": "<slot_id>", "kind": "kpi",       "content": [ { "label": "...", "value": "...", "delta": "..." } ] },
    { "id": "<slot_id>", "kind": "table",     "content": { "headers": ["..."], "rows": [["..."]] } },
    { "id": "<slot_id>", "kind": "image_ref", "content": "<image manifest id>" }
    // ... cover every required slot of <template-root>/<template>/layouts/<layout>.json
  ],
  "image_refs": ["<image manifest id>", ...]   // every image id this slide cites
  // optional: "notes": "..."
}
```

**Slot coverage.** Read the per-layout file at `<template-root>/<template>/layouts/<layout>.json`. Every required slot (the file's `slots[]` entries where `required: true`) must be covered by exactly one block whose `id` equals the slot's `id` and whose `kind` equals the slot's `type`. The deterministic helper fails closed if a required slot is missing.

**Block content rules.**

- `text` blocks: short strings, NEVER raw source paragraphs. Apply `references/writing-guide.md` style ceilings (titles ≤ 8 words; key points ≤ 14 words; body paragraphs ≤ 40 words as guidance).
- `list` blocks: `content` is an array of short strings; one idea per item.
- `callout` blocks: a single short string for the highlighted statement.
- `kpi` blocks: `content` is an array of `{label, value, delta}` entries; each entry's fields trace to the source. If a number is not in the source, leave the field absent or mark it as a placeholder; never fabricate.
- `table` blocks: `content` is `{headers: [...], rows: [[...]]}` with row lengths matching the header count; cells trace to the source.
- `image_ref` blocks: `content` is the image-manifest id (a string). The slide's top-level `image_refs` array must also list every image id the slide cites — that is the field `init_image_manifest.py` and `validate_workspace.py` cross-check against `image_manifest.images[].id`.
- `chart_ref` blocks: avoid for now. The render-model generator's `SUPPORTED_LAYOUTS` allow-list does **not** include any chart-bearing layout (the layouts whose required slots map to the `chart_placeholder` primitive kind). For any slide whose `deck_plan.layout` falls outside `SUPPORTED_LAYOUTS`, the generator does not fail — it reports `[SKIP] slide N: layout 'X' not implemented` and exits 0, leaving the workspace without a render_model for that slide. The PPTX exporter then fails closed at its 1:1 deck_plan ↔ render_model coverage gate ("planned render_model is missing on disk") before any `.pptx` is written; the exporter would also fail closed independently on a `chart_placeholder` primitive if one ever appeared on disk in a supported-layout render_model. Either path means a chart-bearing slide cannot be produced by the runtime pipeline today — so the agent should not pick a layout whose required slot is `chart_ref`.

**Filenames inside `--slide-specs-dir`.** The deterministic helper does not require any particular spec filename — it matches specs to deck_plan slides by the JSON's `index`. The canonical on-disk name is assigned by the helper as `<idx:02d>_<layout>.json`. The agent **may** mirror that convention in the specs dir for legibility, but the helper itself only reads JSON.

**Quality checks at this step.**

- The set of `spec.index` values equals exactly `{1..N}` (no duplicates, no missing slides, no orphan specs).
- Each spec's `layout` and `title` match the corresponding deck_plan slide.
- Each spec covers every required slot of its per-layout file (slot `id` matched by block `id`; slot `type` matched by block `kind`).
- Every id appearing in an `image_ref` block's `content` AND every id appearing in the slide's top-level `image_refs` array is one the agent intends to declare in Step E.
- Source fidelity is honored: every text / list / callout / kpi / table cell traces to a slide-level `source_refs` entry in the deck_plan.

### Step E. `--image-manifest-spec` (image_manifest candidate)

The image manifest declares the local image assets the deck cites. The deterministic helper (`scripts/init_image_manifest.py`) validates the spec, cross-checks every `slide_plan.image_refs` against `images[].id`, and refuses unsafe paths and symlinks.

**Shape.** A JSON object matching `schemas/image_manifest.schema.json` (`additionalProperties: false`, so only the fields below are allowed):

```jsonc
{
  "images": [
    {
      "id": "<id used by slide_plan image_ref blocks and the slide_plan.image_refs array>",
      "local_path": "<path relative to workspace; no '..', no URI scheme, no absolute path, no leading backslash>",
      "source": "local_asset" /* or "synthetic" — "d_one_local" is reserved for a future image-gen integration that is NOT implemented */,
      "alt_text": "<short abstracted description; NOT a raw source paragraph>",
      "intended_use": "<short purpose, e.g. 'spot illustration', 'icon', 'decorative pattern'; never 'full-slide background'>"
      // optional: "width_px": <positive integer>, "height_px": <positive integer>
    }
    // ... or [] when no slide cites an image
  ]
}
```

Required fields per entry are `id`, `local_path`, and `source`. The `source` enum is `["local_asset", "d_one_local", "synthetic"]`; the agent uses `local_asset` for real local assets supplied by the user and `synthetic` for fixture-style placeholders. `d_one_local` is reserved for a future image-generation integration that is **not** implemented in this repo today (see `references/d-one-image-policy.md`).

**Asset placement.** Every `local_path` must resolve inside the workspace to an existing **regular non-symlink** file at the time the deterministic helper runs. The agent (or the user) is responsible for putting the asset bytes there before the pipeline starts. The deterministic pipeline does **not** generate, fetch, or download any image.

**Image generation policy (out of scope).** This repo currently has no image-generation integration. If a future phase adds one (e.g. D-One), `references/d-one-image-policy.md` is binding: prompts must be assembled from abstracted descriptors, **never** from raw source text; full-slide raster output is forbidden; assets stay local; no public network. The agent therefore:

- **Never** includes raw source paragraphs in `alt_text`, `intended_use`, or any sidecar prompt.
- **Never** generates a full-slide background image. Every slide must carry editable native shapes; image_ref blocks (and the render-model `image_slot` primitives they project into) are decorative or illustrative, not text replacements.
- **Never** invents a `local_path` that does not exist on disk.

**Quality checks at this step.**

- `images[].id` is unique.
- Every `local_path` is workspace-relative, free of `..` / URI scheme / absolute path / leading backslash / protocol-relative shape, and resolves to an existing regular file inside the workspace.
- Every `slide_plan.image_refs[*]` value across `--slide-specs-dir/` is declared in `images[].id`.
- Empty `images[]` is allowed only when no slide cites an image.
- No raw source text appears in any manifest field.

## Pre-pipeline authoring quality loop

Before invoking the deterministic pipeline, the agent runs through this loop. Each item maps to a machine-checked gate downstream (so the loop is also a "fail fast at authoring time" trick), or to a source-fidelity / safety rule the machine cannot check on its own.

Machine-checkable (the deterministic pipeline will enforce these — running them at authoring time saves a six-stage retry). The bundled helper `scripts/validate_authoring_bundle.py` runs items 1–12 plus the curated forbidden-token / full-slide raster / raw-source-leakage scans in one shot, without creating a workspace or generating any artifact:

```
python3 scripts/validate_authoring_bundle.py \
  --source S --title T --audience A --objective O \
  --plan-spec P {--design-system-spec D | --theme-from-template} \
  --template-root TR --slide-specs-dir SP --image-manifest-spec IM \
  [--strict]                              # promote every WARN to ERROR
```

The gate emits `ERROR` findings (exit 1) and `WARN` findings (informational; exit 0 unless `--strict`). A clean run is `OK: no findings — bundle passed the structural gate.` The list below stays as the source of truth for what each check covers; reach for the helper when an agent wants the bundled pre-flight in one command.

1. Each spec parses as JSON. `python3 -c "import json; json.load(open(p))"` is sufficient.
2. Each spec validates against its schema. Use `python3 scripts/validate_artifacts.py --schema schemas/<artifact>.schema.json <path>` per spec.
3. `deck_plan.planning.planned_slide_count == len(deck_plan.slides)`.
4. `deck_plan.slides[].index` is unique and contiguous `1..N`.
5. `deck_plan.sections[].slide_indices` partitions `{1..N}` (no duplicates / no missing / no orphans).
6. Every `deck_plan.slides[].section_id` resolves; the slide's index appears in that section's `slide_indices`.
7. Every `deck_plan.slides[].source_refs` ⊆ `deck_brief.source_refs` (the deterministic pipeline sets `deck_brief.source_refs = [source_manifest.source.id]` by default).
8. Every `deck_plan.slides[].layout` ∈ `template.layouts` AND ∈ the render-model generator's supported set (see `SKILL.md` "What exists in this repo today").
9. The set of spec `index` values in `--slide-specs-dir/` equals `{1..N}`; each spec's `layout` and `title` match the deck_plan; each spec covers every required slot of its per-layout file.
10. Every `slide_plan.image_refs[*]` value is in `image_manifest.images[].id`.
11. Every `image_manifest.images[].local_path` resolves inside the workspace to an existing regular non-symlink file.
12. The design system path is exactly one of `--design-system-spec` / `--theme-from-template`.

Agent-managed (machine cannot check):

13. Every slide title, summary, key point, kpi, and table cell traces to its declared `source_refs`. No fabricated statistics, dates, names, or quotations.
14. No raw customer / account / employee names or sensitive figures unless the user explicitly confirmed they are safe.
15. No raw source paragraphs are copied into any artifact — only short paraphrased summaries.
16. `alt_text`, `intended_use`, and any sidecar image prompts are abstracted; they carry no raw source text.
17. No slide is a full-slide raster or all-image slide. Every slide carries editable native shapes (the PPTX exporter's `minimal_evidence.every_slide_has_native_shape` gate enforces this on the output, but the agent should not even author such a slide).
18. The agent did **not** read, copy, paraphrase, or summarize anything from `/Users/robert/ppt-master` (or any similarly named prior implementation). See `references/clean-room-policy.md`.

If any check fails, the agent fixes the spec and re-runs the loop. Only when every check passes does the agent invoke the deterministic pipeline.

## Hand-off command

When the loop passes, the agent has three equivalent ways to invoke the implemented explicit-input runtime pipeline. They differ only in how much intermediate state the agent wants to inspect; the artifacts written and the validation gates run are identical.

**One command, end to end (the default).** `scripts/run_explicit_pipeline.py` chains Stage 1-6 preparation and Stage 7-10 export+validation into a single deterministic run:

```
python3 scripts/run_explicit_pipeline.py \
  --workspace <fresh empty dir outside the workspace tree's parent> \
  --source <path/to/source.md> \
  --title "..." \
  --audience "..." \
  --objective "..." \
  [--tone "..." --language "..." --approximate-slide-count <N>] \
  --plan-spec <path/to/plan_spec.json> \
  {--design-system-spec <path/to/design_system.json> | --theme-from-template} \
  --template-root <path/to/templates/layouts> \
  --slide-specs-dir <path/to/slide_specs/> \
  --image-manifest-spec <path/to/image_manifest_spec.json> \
  --output <path/to/out.pptx> \
  [--report-dir <path/to/reports/>]
```

Fail-closed semantics: if Stage 1-6 preparation fails at any stage, the Stage 7-10 pipeline is **not** invoked at all — no `render_models/`, `svg_previews/`, `.pptx`, or `pipeline_report.{json,txt}` is produced. If Stage 7-10 fails, the failing stage is reported via the pipeline subprocess's own `[FAIL] / [SKIP]` cascade.

**Two commands, inspect between prep and export.** Split into `scripts/prepare_workspace.py` and `scripts/run_pipeline.py` when the agent wants to look at the prepared workspace before exporting:

```
python3 scripts/prepare_workspace.py --workspace W --source S --title T --audience A --objective O \
  --plan-spec P {--design-system-spec D | --theme-from-template} --template-root TR \
  --slide-specs-dir SP --image-manifest-spec IM
# inspect <W> here: source_manifest.json / deck_brief.json / deck_plan.json /
#                   design_system.json / slide_plans/*.json / image_manifest.json

python3 scripts/run_pipeline.py --workspace W --template-root TR --output O.pptx [--report-dir R]
```

**Seven commands, per-stage chain (deepest inspection).** Each per-stage helper validates and writes exactly one artifact, with its own `--self-test`; use this form to inspect or rerun any stage in isolation:

```
python3 scripts/init_workspace.py      --source <path/to/source.md> --workspace <ws>
python3 scripts/init_deck_brief.py     --workspace <ws> --title "..." --audience "..." --objective "..." \
                                       [--tone "..." --language "..." --approximate-slide-count <N>]
python3 scripts/init_deck_plan.py      --workspace <ws> --plan-spec <path/to/plan_spec.json>
python3 scripts/init_design_system.py  --workspace <ws> \
                                       {--spec <path/to/design_system.json> | --theme-from-template --template-root <tr>}
python3 scripts/init_slide_plans.py    --workspace <ws> --template-root <tr> --specs-dir <path/to/slide_specs/>
python3 scripts/init_image_manifest.py --workspace <ws> --spec <path/to/image_manifest_spec.json>

python3 scripts/run_pipeline.py        --workspace <ws> --template-root <tr> \
                                       --output <path/to/out.pptx> [--report-dir <path/to/reports/>]
```

Each step's exit code gates the next: if `init_deck_plan.py` fails, the agent fixes the `--plan-spec` and reruns just that step. All three forms run the same scripts; the orchestrators add no behavior beyond chaining the per-stage helpers and threading exit codes.

## Post-generation visual review

After the pipeline writes `render_models/` and `svg_previews/` (Stages 7–8 of `run_pipeline.py`, or the equivalent stages inside `run_explicit_pipeline.py`), the agent (or the user) may want a quick visual / structural sanity check on the generated deck before opening the `.pptx`. `scripts/validate_visual_quality.py` is that pass — a stdlib-only, **non-mutating** review gate that inspects only the workspace's `render_models/*.json` and `svg_previews/*.svg`, never plans, never regenerates, never exports, and never calls any external service:

```
# Human-readable summary (per-slide findings + aggregate counters)
python3 scripts/validate_visual_quality.py --workspace <prepared workspace>

# Machine-readable JSON report
python3 scripts/validate_visual_quality.py \
  --workspace <prepared workspace> \
  --output <path/to/report.json>

# Self-contained HTML contact sheet (inline SVG; no remote refs)
python3 scripts/validate_visual_quality.py \
  --workspace <prepared workspace> \
  --output <path/to/contact_sheet.html>
```

What the gate flags (per slide): missing SVG preview, blank slide (zero primitives), near-empty slide (primitive count < 2 AND text chars < 32), image-only slide, all-placeholder text slide, no native editable primitive, out-of-canvas render_model bounds, out-of-canvas SVG geometry, text density floor / ceiling. Aggregate counters: slide count vs `deck_plan.slides[]`, layout distribution, missing-preview count, per-slide primitive-kind histogram. `--strict` promotes every `WARN` to `ERROR`. `--output` must live OUTSIDE `--workspace`; the HTML contact sheet inlines each SVG **with sanitize-by-rejection** — any SVG carrying `<script>` / `<foreignObject>` / `<use>` / `<a>` / `<style>`, any SMIL/timing/filter-image element (`<animate>` / `<animateMotion>` / `<animateTransform>` / `<set>` / `<discard>` / `<mpath>` / `<feImage>`), an `on*` event-handler attribute, a `style="..."` attribute, any attribute value containing a CSS `url(...)` reference (`fill` / `stroke` / `mask` / `clip-path` / `filter` / `cursor` / `marker-*` would otherwise fetch the referenced external paint server / filter / mask / cursor), an `xml:base` attribute on any element (would rewrite the document's base URL so an otherwise-safe relative href resolves against an attacker-controlled base), or a `href` / `src` / `xlink:href` whose value either has surrounding whitespace (`" https://attacker/x"` — browsers strip leading/trailing whitespace before URL resolution, so the whitespace gate catches the bypass that the bare URI-scheme regex would miss) OR does not pass `validate_scaffold.local_path_is_safe` (URI schemes, POSIX-absolute, leading backslash, **protocol-relative `//host/x`**, `..` traversal, empty) is replaced by a textual `SVG not embedded (unsafe for inline): <reason>` notice rather than spliced into the page, and safe SVGs are re-serialized from the parsed tree so XML declarations, DOCTYPEs, processing instructions, and comments cannot leak into the HTML host. **Second layer (strip-by-removal):** even after the sanitize-by-rejection gate accepts the SVG, every `href` / `src` / `xlink:href` / `*href` attribute is stripped from the re-serialized tree before inlining — including legitimate workspace-relative paths like `<image href="generated_assets/cover.png">` that pass `local_path_is_safe`. Such paths still fetch against the HTML host directory when the contact sheet is opened (the output gate requires that directory to live OUTSIDE the workspace by design, so the path 404s on disk anyway), so the fetchable surface is removed entirely. Geometry (`x` / `y` / `width` / `height`) survives. The produced contact sheet contains no `file://` URLs, no scheme-relative references, no `href` / `src` / `xlink:href` attribute of any value, no `url(...)` CSS references, no `xml:base`, no SMIL/animation elements, and no JavaScript — it never reaches the network OR the filesystem when opened in a browser. The gate does **not** replace `scripts/validate_workspace.py` (which is stricter — schemas, coverage, layout, bounds, SVG safety) or `scripts/validate_pptx_contract.py` (which validates the produced PPTX). It is an additional inspection-time signal so the agent can eyeball the deck structurally without re-running the pipeline.

## What this workflow does NOT do

Out of scope for this document AND for the deterministic pipeline:

- **No automatic prompt/report-to-PPTX.** The deterministic pipeline does not invent any spec content; the agent does. There is no model API call, no LLM-driven extraction step inside the scripts.
- **No D-One integration.** Image assets must already exist locally. See `references/d-one-image-policy.md` for the policy any future integration must satisfy.
- **No Qoder integration.** Runtime packaging is a separate, later concern.
- **No public network behavior, telemetry, scraping, public image search, or undeclared remote calls** at any stage of authoring or running.
- **No model API calls** from any script in this repo.
- **No real business data.** Examples committed to the repo are synthetic. Authoring against real source files happens inside a user-chosen workspace that is not committed.
- **No `business_review`-as-default** assumption. The template is chosen per-deck.
- **No fixed 20-slide deck shape.** Length is adaptive.
- **No full-slide raster output.** Every slide carries editable native shapes.
- **No arbitrary-SVG-to-PPTX conversion.** SVG is a preview / inspection artifact only.
- **No copying from `ppt-master`.** See `references/clean-room-policy.md`.

When a brief truly needs one of the above, treat it as a blocker, not as a quiet extension of this workflow.
