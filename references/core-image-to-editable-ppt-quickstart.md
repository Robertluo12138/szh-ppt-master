# Core Image-to-Editable-PPT Quickstart

Operator-facing quickstart for the **local/mock image lane** of the image-to-editable-PPT path. Names the exact existing commands a reviewer should run today against committed synthetic fixtures, and pins what is VERIFIED vs UNVERIFIED vs NOT IMPLEMENTED. No new pipeline; this document does not extend any script.

## Scope at a glance

| Lane | Status | Gate |
| --- | --- | --- |
| Local/mock image bytes + caller-supplied source-image assets, end-to-end into a native editable `.pptx` | **VERIFIED locally** | `scripts/core_image_to_editable_ppt_demo.py --out-dir DIR` runs the operator demo into a caller-supplied directory outside the repo and leaves inspectable artifacts (PPTX, reports, `demo_summary.json`) on disk. `scripts/core_image_to_editable_ppt_demo.py --self-test` drives the same happy path through a per-run tempdir and additionally runs every documented fail-closed probe. |
| Real D-One image generation | **UNVERIFIED** | `scripts/d_one_live_readiness_preflight.py` is the local readiness preflight; `PREFLIGHT_READY_FOR_MANUAL_TRIAL` is **not** a PASS for live D-One. Nothing in this repo calls D-One, MCP, Qoder, a public network, telemetry, any model API, an image search, or any external service. |
| Full prompt/report/Markdown → PPT automation (raw-source → spec extraction) | **NOT implemented** | The runtime pipeline is intentionally explicit-input. Authoring the five spec inputs (`deck_brief` / `deck_plan` / `design_system` / `slide_plans` / `image_manifest`) is the agent's responsibility; see [`authoring-workflow.md`](authoring-workflow.md). |

## What you run today

The shortest one-command operator demo is:

```bash
# Use a FRESH per-run dir outside the repo. The validator refuses a
# pre-existing non-empty --out-dir, a symlinked --out-dir, a URI-shaped
# argument, and any path that resolves under the repo tree.
RUN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/szh-demo-XXXX")
echo "Operator artifacts will land under: $RUN_DIR/operator_out"

TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/core_image_to_editable_ppt_demo.py \
  --out-dir "$RUN_DIR/operator_out"

# When done inspecting, clean up:
#   rm -rf "$RUN_DIR"
```

The demo drives the same mixed-lane mock pipeline + validators as the lower-level runner below into the operator-supplied `--out-dir` and writes a concise `demo_summary.json` alongside the produced `.pptx`, the runner-written `inventory.json` / `mock_d_one_adapter_plan.json`, the demo's per-run inventory snapshot, and the sanitized handoff record. The summary names slide count, embedded media parts, editable / native-shape evidence, local/mock provenance status, and the explicit boundaries (real D-One UNVERIFIED; no public network, MCP, Qoder, model API, image search, or telemetry; raw prompt-or-report-to-PPT automation NOT implemented).

For the underlying lower-level pipeline command (used by the demo internally and available standalone for callers who want to bypass the demo wrapper), see below. The canonical lower-level operator-facing command for the synthetic/local image lane is `scripts/run_mock_image_pipeline.py --bundle examples/synthetic_mock_image_trial`. It packages the local image chain (`done_image_adapter.py` → `run_d_one_generation.py --allow-synthetic-bytes` → `materialize_image_assets.py` → `run_explicit_pipeline.py`) into one command and writes only to caller-supplied paths **outside the repo tree**.

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

`scripts/core_image_to_editable_ppt_demo.py` ships two modes that share one happy path:

- `--out-dir DIR` (operator mode, shown above) — drives the same mixed-lane mock pipeline once into `DIR`, runs `validate_pptx_contract --expected-slide-count 2`, `inspect_pptx_inventory`, and `validate_mixed_image_asset_provenance` against the produced artifacts, composes `demo_summary.json`, and asserts every documented invariant. Leaves inspectable artifacts under `DIR`. Writes nothing under the repo tree.
- `--self-test` (harness mode) — runs the same happy path under a per-run tempdir (no caller-visible artifacts retained) and additionally runs every documented fail-closed probe, including the operator-mode argument-gate probes (URI-shaped `--out-dir`, symlink `--out-dir` or symlink ancestor, repo-contained `--out-dir`, pre-existing non-empty `--out-dir`):

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
  python3 scripts/core_image_to_editable_ppt_demo.py --self-test
```

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
