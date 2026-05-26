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

## Bring your own local images

After `scripts/core_image_to_editable_ppt_demo.py --out-dir` (which proves the lane on the repo's synthetic mock bytes), the next operator step for a reviewer who has their **own** folder of local PNG / JPG / JPEG bytes is `scripts/operator_local_images_to_editable_ppt.py`. It discovers operator-supplied images in a flat directory, generates the smallest viable fixture (one cover slide per image, each carrying the operator file as a native `ppt/media` accent + a native editable title), drives `run_explicit_pipeline.py` with the existing Stage-5.5 materialize step, runs the same `validate_source_image_assets` (G1..G13), `validate_pptx_contract --expected-slide-count N`, `inspect_pptx_inventory`, and `validate_visual_quality --output <out-dir>/visual_quality.json` (inspection-only; never mutates the workspace, never re-renders, never calls any external service) validators, and writes a compact `summary.json` + per-image provenance record + `visual_quality.json` report that map each operator filename straight to the embedded `ppt/media/*` part and surface per-slide visual-quality `totals.errors` / `totals.warnings`.

```bash
# Caller-supplied flat images directory; PNG / JPG / JPEG only; filename
# stems must match the schema id pattern ^[A-Za-z0-9][A-Za-z0-9_.\-]*$ and
# the deck is capped at 12 images. Pre-flatten any subdirectories.
IMAGES_DIR=/path/to/your/local/png_or_jpg/images

RUN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/szh-operator-XXXX")
echo "Operator artifacts will land under: $RUN_DIR/operator_out"

TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_local_images_to_editable_ppt.py \
  --images-dir "$IMAGES_DIR" \
  --out-dir "$RUN_DIR/operator_out"

# When done inspecting, clean up:
#   rm -rf "$RUN_DIR"
```

### Optional `--manifest` for per-image slide intent

Without `--manifest`, slide order is alphabetical by filename and the slide title / `image_manifest` `alt_text` / `intended_use` use the helper's deterministic defaults. To control any of those — slide order, native editable slide title, alt-text, intended-use — supply a local JSON manifest:

```bash
cat >"$RUN_DIR/manifest.json" <<'JSON'
{
  "schema_version": "1",
  "images": [
    {
      "filename": "hero_marker.png",
      "slide_title": "Hero concept",
      "alt_text": "Synthetic hero marker",
      "intended_use": "spot illustration"
    },
    {
      "filename": "supporting_chart.jpg",
      "slide_title": "Supporting chart",
      "alt_text": "Synthetic supporting chart accent",
      "intended_use": "decorative pattern"
    }
  ]
}
JSON

TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_local_images_to_editable_ppt.py \
  --images-dir "$IMAGES_DIR" \
  --out-dir "$RUN_DIR/operator_out" \
  --manifest "$RUN_DIR/manifest.json"
```

Contract for `--manifest`:

- Local file only — `--manifest` itself, no ancestor up to the filesystem root (closed macOS aliases such as `/tmp -> /private/tmp` excepted), and the JSON must parse as a single object.
- Root carries exactly `schema_version == "1"` and a non-empty `images` array; each entry carries exactly the four required fields `filename` / `slide_title` / `alt_text` / `intended_use` (no extras, no missing).
- `filename` must match a discovered basename under `--images-dir` exactly once; every discovered image must appear in the manifest exactly once.
- Each free-text field must be a non-empty, length-bounded string with no leading / trailing whitespace, no control characters, no `://` or `<scheme>:` URL / URI shape, no `/` or `\` path separator, and no credential / token / API-key / public-upload / public-share / public-hosting / raw-source / confidential / customer / D-One / MCP / Qoder / model-API / image-search / network / telemetry marker. Mention of any upstream service this lane does NOT call (positive or negative) is refused — the boundary statement is concentrated in the locked `summary.explicit_boundaries` tuple, not in operator metadata.
- The operator-typed `slide_title` becomes the native editable slide title; `alt_text` and `intended_use` flow into the generated `image_manifest.json` and are echoed back under `summary.image_provenance[]` as `operator_slide_title` / `operator_alt_text` / `operator_intended_use`. The manifest's `images[]` array order replaces the alphabetical-filename order as the deck slide order. `summary.manifest_path` echoes the supplied path verbatim (and is `null` when `--manifest` is omitted).

### Optional `--write-manifest-template` for a starter manifest

If you would rather start from a skeleton manifest than hand-author the JSON, run the helper in manifest-template writer mode:

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_local_images_to_editable_ppt.py \
  --images-dir "$IMAGES_DIR" \
  --write-manifest-template "$RUN_DIR/manifest_template.json"
```

The writer reuses the same flat PNG / JPG / JPEG discovery the normal mode applies (same IG1..IG9 gates), then writes a JSON manifest at the supplied path whose `images[]` array carries one entry per discovered image, sorted by filename, with the helper's default `slide_title` (`Operator image: <filename>`) / `alt_text` (`Operator-supplied local image '<filename>'.`) / `intended_use` (`spot illustration`). The template is immediately usable: feed it back into the normal command as `--manifest "$RUN_DIR/manifest_template.json"` and the produced `summary.image_provenance[]` echoes those fields exactly as for a hand-authored manifest. Edit the JSON first if you want to override any field or reorder the deck.

Contract for `--write-manifest-template PATH` mirrors the other operator paths: must not be URI-shaped, a symlink, or have a symlink ancestor, must not anchor under the repo tree, must have an existing directory parent, and must not already exist (the writer never overwrites operator files). The writer does NOT run the pipeline, does NOT produce a PPTX, does NOT produce a `visual_quality.json` report (the visual-quality validator only runs in normal operator mode against a produced workspace), does NOT produce an operator-facing `README.md` (the README is written only in normal operator mode after the summary truth-check passes), and does NOT call D-One / MCP / Qoder / a public network / a model API / an image search / telemetry.

### Optional `--plan-out` for a plan-only preflight

Before driving the full pipeline, you can ask the helper for a plan-only preflight: it discovers the same flat PNG / JPG / JPEG folder operator mode uses (reuses the IG1..IG9 gates verbatim), validates the optional `--manifest` against MAN1..MAN12 when supplied, then writes a compact deterministic JSON plan and exits — without running `run_explicit_pipeline.py` and without producing a workspace, PPTX, inventory, visual_quality, summary, reports, or `_pipeline_fixture` artifact.

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_local_images_to_editable_ppt.py \
  --images-dir "$IMAGES_DIR" \
  --plan-out "$RUN_DIR/plan.json"

# With per-image slide intent:
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_local_images_to_editable_ppt.py \
  --images-dir "$IMAGES_DIR" \
  --plan-out "$RUN_DIR/plan.json" \
  --manifest "$RUN_DIR/manifest.json"
```

The plan carries `schema_version="1"`, `helper_id="operator_local_images_to_editable_ppt"`, `mode="plan_only"`, `image_count`, `slide_count` (== `image_count`), `manifest_path` (string when `--manifest` was supplied, `null` otherwise), the locked `explicit_boundaries` tuple identical to the one the operator-mode summary echoes, and one `images[]` row per discovered image carrying `filename` / `asset_id` / `media_type` / `byte_count` / `sha256` / `intended_slide_index` (1-based) / `slide_title` / `alt_text` / `intended_use`, in manifest-array order when `--manifest` was supplied or filename-sorted order otherwise.

Contract for `--plan-out PATH` mirrors `--write-manifest-template` (PO1..PO6): must not be URI-shaped, a symlink, or have a symlink ancestor, must not anchor under the repo tree, must have an existing directory parent, and must not already exist (stale bytes on a pre-existing target are preserved). `--plan-out` is mutually exclusive with `--out-dir` / `--write-manifest-template` / `--self-test`; it requires `--images-dir` and may combine with the optional `--manifest`. Plan-only mode does NOT run the pipeline, does NOT produce an operator-facing `README.md` (the README is written only in normal operator mode after the summary truth-check passes), and does NOT call D-One / MCP / Qoder / a public network / a model API / an image search / telemetry.

Outputs (every path lives under `--out-dir`; nothing lands under the repo tree):

- `deck.pptx` — native editable PPTX, one cover slide per operator image, each carrying the operator file embedded in `ppt/media/`.
- `inventory.json` — `scripts/inspect_pptx_inventory.py` readback (`ok=true`, `findings=[]`, internal-only relationships, every embedded `ppt/media/*` part).
- `visual_quality.json` — `scripts/validate_visual_quality.py` JSON report over the produced workspace's `render_models/` + `svg_previews/` pair (per-slide `totals.errors` / `totals.warnings`, layout distribution, missing-preview count, per-slide finding list). The summary's `visual_quality` block surfaces `rc`, `path`, `report_parsed`, `error_count`, `warning_count`; the truth-checker refuses on non-zero rc / unparseable report / `error_count > 0`. Warnings (`warning_count > 0`) are allowed.
- `summary.json` — compact summary record (slide count, image count, embedded media count, `source_classes = ["local_asset"]`, `no_external_relationships=true`, `minimal_evidence.*` booleans, per-image provenance mapping each `operator_filename` to the embedded `ppt/media/*` parts via shared sha256 — every row also carries `intended_slide_index` (the 1-based deck position the helper assigned to this operator filename — manifest array order when `--manifest` was supplied, filename-sorted order otherwise), `embedded_referencing_slides` (the sorted union of 1-based slide indices whose `<a:blip r:embed>` resolves to one of the operator's `ppt/media/*` parts per `inspect_pptx_inventory.slides[*].media_refs[*]` filtered to `used_by_slide_blip=True` — blip-confirmed, NOT the rels-only `media_parts[*].referencing_slides` field; a slide whose rels declare an image rel but whose `<p:pic>` body does not embed it cannot false-green the placement check), and `placement_verified` (True iff the intended index is in `embedded_referencing_slides`; the truth-checker refuses on False) — with `operator_slide_title` / `operator_alt_text` / `operator_intended_use` keys also present when `--manifest` was supplied, `manifest_path` echoing the supplied path or `null` otherwise, validator rc values including `validate_visual_quality`, the `visual_quality` block described above, `real_d_one_status = "UNVERIFIED"`, locked `explicit_boundaries`).
- `workspace/` — production workspace seeded by `run_explicit_pipeline.py` (Stage 1-10); includes the source-attached `source_image_assets.json` registry the post-run validator ran against.
- `reports/` — `pipeline_report.{json,txt}` and runner-written inventory from the underlying `run_pipeline.py`.
- `_pipeline_fixture/` — the generated explicit-input fixture (plan_spec, slide specs, image_manifest_spec, staged asset bytes) the run consumed; useful for a reviewer who wants to inspect what the helper handed to the orchestrator.
- `README.md` — concise operator-facing review-package README, written after the summary truth-check passes. Names the produced artifacts (`deck.pptx` / `summary.json` / `inventory.json` / `visual_quality.json` / `workspace/source_image_assets.json` / `reports/`), points reviewers at `summary.image_provenance[]` for filename -> sha256 -> ppt/media part -> intended/readback slide evidence, and carries the fixed local-only boundary statement (real D-One UNVERIFIED, no MCP / Qoder / public network / model API / image search / telemetry, NOT a prompt or report-to-PPT automation). Not written in `--write-manifest-template` or `--plan-out` mode.

Fail-closed gates fire before any subprocess runs: URI-shaped paths, symlink `--images-dir` or symlink ancestor, missing / empty / non-directory `--images-dir`, subdirectories or symlinks or unsupported extensions inside the images directory, filenames whose stem does not match the schema id pattern (`my photo.png` with a space, `-leading.jpg` with a leading separator), two files that share a stem, magic-byte mismatch (PNG bytes inside `.jpg`), more than 12 images, URI-shaped `--out-dir`, symlink `--out-dir` or symlink ancestor, `--out-dir` inside the repo tree, missing `--out-dir` parent, non-directory at `--out-dir`, or pre-existing non-empty `--out-dir`. When `--manifest` is supplied, the same boundary applies to the manifest path (URI / symlink / symlink-ancestor / missing / non-file) plus structural refusals for malformed JSON, non-object root, unknown / missing root key, `schema_version != "1"`, empty / wrong-shape entries, unsafe field values (URL / URI / path separator / credential / public-upload / confidential / fake-success), duplicate filename, orphan filename (not in discovered set), and missing filename (discovered but unnamed). Run `--self-test` to exercise every gate against synthetic fixtures under a per-run tempdir:

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
  python3 scripts/operator_local_images_to_editable_ppt.py --self-test
```

Local-only — does NOT call D-One, MCP, Qoder, a public network, telemetry, a model API, an image search, or any external service. Real D-One remains UNVERIFIED.

For the broader aggregate that runs every delegated core editable-PPT smoke in order (operator local-image intake, placement readback, image-asset acceptance, taxonomy / text-policy / provenance handoff smokes, render-model roundtrip, trace acceptance, …) — `scripts/operator_local_images_to_editable_ppt.py --self-test` is wired in as one of twenty delegated smokes so the operator local-images route is covered by this single top-level command:

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
