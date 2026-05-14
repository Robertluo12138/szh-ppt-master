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
| `plan_spec.json` | `deck_plan` candidate. 7 slides across 6 sections; single source ref `synthetic_trial_source`. |
| `design_system_spec.json` | `design_system` candidate (the `--design-system-spec` mode). Use `--theme-from-template` against `templates/layouts` for the alternative. |
| `slide_specs/01_cover.json` ... `07_conclusion.json` | Per-slide `slide_plan` candidates against the `business_review` template's layout vocabulary. |
| `image_manifest_spec.json` | Empty `images[]`. |

Layouts exercised: `cover`, `executive_summary`, `key_message`, `two_column`, `kpi_dashboard`, `timeline`, `conclusion`.

## How to run

From the repo root:

```bash
# 1. Pre-pipeline structural gate (non-mutating)
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

## Known quality gap

The authoring bundle gate validates `slide_plan` blocks against `schemas/slide_plan.schema.json`, which leaves `blocks[*].content` intentionally loose ("Free-form in the scaffold. TODO: tighten per kind"). The render-model generator applies stricter per-kind rules — for example, a `kpi` block whose `content[*].delta` is an empty string is refused at render-time. The gate cannot catch that today; an agent who authors `delta: ""` will see the failure at Stage 7 (`generate_render_models`), not at the pre-flight. Tightening the gate to mirror the generator's per-kind rules is out of scope for this trial.

## What this trial does NOT do

- It is not an end-to-end automation of "prompt → PPTX" — every slide body is authored by the caller via the JSON spec files.
- It is not a source-fidelity check. The gate does not verify that slide text traces back to specific source passages; that remains agent-managed per `references/authoring-workflow.md`.
- It is not a privacy or clean-room audit. The forbidden-token / full-slide-raster / raw-source-leakage scans catch obvious mistakes, not every possible failure mode.
- It is not a substitute for the runtime pipeline's gates. Schema, planner-semantics, layout-coverage, KPI-shape, and PPTX-container checks all re-fire downstream.
