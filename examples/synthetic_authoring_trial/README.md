# Synthetic Authoring Trial

**This is a synthetic smoke test, NOT production readiness.**

This directory is an agent-authored input bundle for the explicit-input PPT pipeline. It exercises `scripts/validate_authoring_bundle.py` and `scripts/run_explicit_pipeline.py` end-to-end on synthetic, non-sensitive content. The deck is intentionally short (7 slides) and adaptive — do NOT treat this as a deck-length default or a layout sequence default.

## Scope

- **Synthetic only.** No real company, product, customer, employee, or financial data appears anywhere in this bundle. Every name, label, and counter is a placeholder.
- **Clean-room.** No content from `ppt-master` or any similarly named prior implementation.
- **Offline.** No D-One, Qoder, public network, telemetry, model API, or external service is invoked.
- **No images.** `image_manifest_spec.json` declares an empty `images[]`; no rastered slides, no full-slide backgrounds.

## Contents

| File | Role |
| --- | --- |
| `source.md` | Synthetic markdown source body. Body text never leaks beyond `<workspace>/input/source.md`. |
| `brief.json` | Brief metadata for the `--bundle` shortcut: `title`, `audience`, `objective`, plus optional `tone`, `language`, `approximate_slide_count`, `source_id`, and `brand_preset_ref` (an OPTIONAL `{id, path}` object that triggers a READ-ONLY authoring-time check against `scripts/validate_brand_preset.py` — see "Brand preset reference" below). Not consumed by the explicit per-flag form. |
| `plan_spec.json` | `deck_plan` candidate. 7 slides across 6 sections; single source ref `synthetic_trial_source`. |
| `design_system_spec.json` | `design_system` candidate (the `--design-system-spec` mode). Use `--theme-from-template` against `templates/layouts` for the alternative. |
| `slide_specs/01_cover.json` ... `07_conclusion.json` | Per-slide `slide_plan` candidates against the `business_review` template's layout vocabulary. |
| `image_manifest_spec.json` | Empty `images[]`. |

Layouts exercised: `cover`, `executive_summary`, `key_message`, `two_column`, `kpi_dashboard`, `timeline`, `conclusion`.

## How to run

From the repo root:

```bash
# 1. Pre-pipeline structural gate (non-mutating). The --bundle shortcut
# resolves the canonical layout (source.md, brief.json, plan_spec.json,
# design_system_spec.json, slide_specs/, image_manifest_spec.json) from
# a single directory.
env PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_authoring_bundle.py \
  --bundle examples/synthetic_authoring_trial \
  --template-root templates/layouts

# The same gate also accepts the explicit per-input flags; both forms
# resolve to the same inputs.
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

# 2. Stage-1-to-10 explicit-input pipeline (writes a workspace + PPTX OUTSIDE the repo)
env PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_explicit_pipeline.py \
  --workspace /tmp/synthetic_authoring_trial_ws \
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
  --image-manifest-spec examples/synthetic_authoring_trial/image_manifest_spec.json \
  --output /tmp/synthetic_authoring_trial.pptx \
  --report-dir /tmp/synthetic_authoring_trial_report
```

`--workspace`, `--output`, and `--report-dir` must live OUTSIDE the repo. Each run requires a fresh (non-existent or empty) `--workspace`.

## Authoring gate vs. runtime generator

The authoring bundle gate validates `slide_plan` blocks against `schemas/slide_plan.schema.json` AND re-applies the *per-block* shape rules in `scripts/generate_render_models.py`. Every block the render-model generator would silently drop at runtime now fails closed at the preflight as an **ERROR**: `chart_ref` kind anywhere (no SUPPORTED layout maps to the `chart_placeholder` primitive today), duplicate block ids within a spec, anonymous blocks with no `id` (the generator builds `blocks_by_id` only from id-bearing blocks, so anonymous blocks would be silently dropped at runtime), and any block whose `id` is not declared by the resolved layout's slots (the generator silently drops the block — payload smuggling for chart/image/table/kpi kinds, dead content for text/list/callout kinds; the diagnostic distinguishes the two so the agent sees the right fix). The gate also enforces kind drift on optional layout slots, per-kind content shapes (text / callout / image_ref non-empty string, list non-empty list of non-empty strings, kpi list-of-dicts with non-empty `label` / `value` and optional non-empty `delta` with no extra keys, table with non-empty `headers` and equal-length rows of non-empty cells with no extra keys), and list-slot capacity vs. `LIST_ITEM_MIN_H`. An agent who authors `kpi.delta: ""`, a `comparison_table` row whose cell count disagrees with `headers`, an `image_ref` block on a layout without an image slot, a duplicate `block.id`, kind drift on an optional layout slot, an anonymous block, a block whose `id` is not a declared layout slot, or a list whose item count would overflow the slot height will see the failure at the pre-flight rather than at Stage 7.

This is **not full generator parity**. The render-model generator additionally enforces integer-arithmetic gates (KPI tile-width positivity in `_kpi_tile_bounds`, palette / typography token resolution against `design_system.json`, slot-presence checks the generator itself hardcodes per layout) that are layout / token concerns rather than per-block authoring concerns; those remain runtime-only. This remains authoring validation, not automatic generation — every block body is caller-authored via the JSON spec files.

## Brand preset reference (authoring-time, READ-ONLY)

`brief.json` may OPTIONALLY declare a `brand_preset_ref` against a local synthetic preset under the registry roots `examples/` or `templates/`. The `path` value uses the form `<registry-root>/<file>` — the first segment names the registry root (`examples` or `templates`) and the rest is resolved under that root. The committed trial declares:

```json
"brand_preset_ref": {
  "id": "synthetic_neutral_minimal",
  "path": "examples/brand_preset_template.json"
}
```

This is **authoring-time reference validation, NOT style application**. The `--bundle` flow confirms (read-only):

- `id` matches `^synthetic_[a-z0-9][a-z0-9_]*$` (the same `preset_id` pattern in `schemas/brand_preset.schema.json`);
- `id` carries no real-brand wording (Google / Anthropic / Claude / OpenAI / ChatGPT / Microsoft / PowerPoint / Apple / Keynote / Adobe / Figma), no credential-shape token (`api_key` / `secret` / `bearer` / `password` / bare `token` / etc.), and no `public` + propagation-verb combination (`upload` / `share` / `url` / `link` / `host` / ...);
- `path` passes `local_path_is_safe` (refuses URI schemes, absolute paths, `..` traversal, and surrounding whitespace);
- `path` is of the form `<registry-root>/<file>`, the first segment names a registered root (`examples` or `templates`), and the joined path resolves under that root (defense-in-depth against symlink escape). A bare filename (no `/`) or an unknown first segment (`not_a_registry/foo.json`) fails closed before any disk access;
- the resolved file is a regular non-symlink file that passes `scripts/validate_brand_preset.py` (P1..P11);
- the file's `preset_id` matches `brand_preset_ref.id` (registry-lookup drift detection — rename / typo fails closed).

The preset is **never** projected onto `design_system.json`, `slide_plans/*.json`, `render_models/*.json`, `previews/*.svg`, or `deck.pptx`. No script in this repo reads a preset at runtime; `scripts/validate_brand_preset.py` and the bundle reference check are the only consumers.

Omit the field entirely to skip the check — it is optional.

## What this trial does NOT do

- It is not an end-to-end automation of "prompt → PPTX" — every slide body is authored by the caller via the JSON spec files.
- It is not a source-fidelity check. The gate does not verify that slide text traces back to specific source passages; that remains agent-managed per `references/authoring-workflow.md`.
- It is not a privacy or clean-room audit. The forbidden-token / full-slide-raster / raw-source-leakage scans catch obvious mistakes, not every possible failure mode.
- It is not a substitute for the runtime pipeline's gates. Schema, planner-semantics, layout-coverage, KPI-shape, and PPTX-container checks all re-fire downstream.
