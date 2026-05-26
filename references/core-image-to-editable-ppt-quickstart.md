# Core Image-to-Editable-PPT Quickstart

Operator-facing quickstart for the **local/mock image lane** of the image-to-editable-PPT path. Names the exact existing commands a reviewer should run today against committed synthetic fixtures, and pins what is VERIFIED vs UNVERIFIED vs NOT IMPLEMENTED. No new pipeline; this document does not extend any script.

## Scope at a glance

| Lane | Status | Gate |
| --- | --- | --- |
| Local/mock image bytes + caller-supplied source-image assets, end-to-end into a native editable `.pptx` | **VERIFIED locally** | `scripts/core_image_to_editable_ppt_demo.py --self-test` proves the loop end-to-end (drives the mixed-lane mock pipeline once into a per-run tempdir, then checks every documented invariant + every fail-closed probe). |
| Real D-One image generation | **UNVERIFIED** | `scripts/d_one_live_readiness_preflight.py` is the local readiness preflight; `PREFLIGHT_READY_FOR_MANUAL_TRIAL` is **not** a PASS for live D-One. Nothing in this repo calls D-One, MCP, Qoder, a public network, telemetry, any model API, an image search, or any external service. |
| Full prompt/report/Markdown → PPT automation (raw-source → spec extraction) | **NOT implemented** | The runtime pipeline is intentionally explicit-input. Authoring the five spec inputs (`deck_brief` / `deck_plan` / `design_system` / `slide_plans` / `image_manifest`) is the agent's responsibility; see [`authoring-workflow.md`](authoring-workflow.md). |

## What you run today

The canonical operator-facing command for the synthetic/local image lane is `scripts/run_mock_image_pipeline.py --bundle examples/synthetic_mock_image_trial`. It packages the local image chain (`done_image_adapter.py` → `run_d_one_generation.py --allow-synthetic-bytes` → `materialize_image_assets.py` → `run_explicit_pipeline.py`) into one command and writes only to caller-supplied paths **outside the repo tree**.

```bash
# Use a FRESH per-run tempdir outside the repo. Required: the runner refuses a
# pre-existing non-empty --workspace, a pre-existing --output, or a pre-existing
# --report-dir, so reusing the same fixed path on a second run fails closed
# (rc!=0) and leaves the first run's stale outputs sitting under that path.
RUN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/szh-mock-XXXX")
echo "Outputs will land under: $RUN_DIR"

TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/run_mock_image_pipeline.py \
  --bundle examples/synthetic_mock_image_trial \
  --workspace "$RUN_DIR/ws" \
  --template-root templates/layouts \
  --output "$RUN_DIR/deck.pptx" \
  --report-dir "$RUN_DIR/reports" \
  --allow-synthetic-bytes

# When done inspecting, clean up:
#   rm -rf "$RUN_DIR"
```

Outputs are committed-free:

- `$RUN_DIR/deck.pptx` — native editable PPTX (2 slides; both with editable text and shape evidence).
- `$RUN_DIR/reports/inventory.json` — readback inventory (`ok=true`, `findings=[]`, internal-only relationships, `ppt/media/*` parts).
- `$RUN_DIR/reports/mock_d_one_adapter_plan.json` — runner-written audit sidecar (a byte-identical copy of the staging `d_one_adapter_plan.json` — local/mock/synthetic audit evidence only, never a real D-One artifact).
- `$RUN_DIR/ws/` — production workspace seeded from the bundle (Stages 1–10).

To rerun, pick a new `RUN_DIR` (the snippet above does this for you with `mktemp -d`). Reusing a fixed path on a second run is refused by the runner before any subprocess fires, and prior outputs from the first run remain on disk under that path — confusing UX, not a partial write.

`--allow-synthetic-bytes` is required and pins the run to the local mock provider. Omitting it fails closed at the runner boundary rather than implying a real-D-One mode this repo does not support today. The bundle at `examples/synthetic_mock_image_trial/` is synthetic-only (two `cover`-layout slides each referencing a distinct `d_one_local` image; both `placement_role` values covered; no real data).

## Proof the quickstart command works today

The smallest single command that proves the local/mock loop is healthy end-to-end:

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
  python3 scripts/core_image_to_editable_ppt_demo.py --self-test
```

`core_image_to_editable_ppt_demo.py --self-test` drives the same mixed-lane mock pipeline once into a per-run tempdir, runs `validate_pptx_contract --expected-slide-count 2`, `inspect_pptx_inventory`, and `validate_mixed_image_asset_provenance` against the produced artifacts, composes a demo summary JSON, and asserts every documented invariant plus the documented fail-closed probes. Writes nothing under the repo tree.

For the broader aggregate that runs every delegated core editable-PPT smoke in order (placement readback, image-asset acceptance, taxonomy / text-policy / provenance handoff smokes, render-model roundtrip, trace acceptance, …):

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
  python3 scripts/core_editable_ppt_acceptance.py --self-test
```

For the future-real-D-One readiness side (`PREFLIGHT_READY_FOR_MANUAL_TRIAL` is the best outcome today; it is **not** a live PASS):

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
  python3 scripts/d_one_live_readiness_preflight.py --self-test
```

## Boundary reminders

- The pipeline never calls D-One, MCP, Qoder, a public network, telemetry, any model API, an image search, or any external service. Real D-One remains UNVERIFIED.
- Image-generation bytes under `ppt/media/` come from `run_d_one_generation.py --allow-synthetic-bytes` (a fixed minimal magic-byte-valid PNG/JPG/JPEG payload). Caller-supplied `local_asset` bytes (when the bundle carries `source_assets/`) are copied byte-identically through `materialize_image_assets.py`.
- No write lands under the repo tree on a happy run. The runner refuses symlinks at `--output` / `--workspace` / `--report-dir` and URI-shaped arguments before any subprocess fires.
- For raw-source → spec authoring, see [`authoring-workflow.md`](authoring-workflow.md); for the D-One image policy, see [`d-one-image-policy.md`](d-one-image-policy.md); for quality-gate coverage of each delegated smoke, see [`quality-gates.md`](quality-gates.md).
