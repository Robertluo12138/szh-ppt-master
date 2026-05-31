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

### Optional `--approved-plan` for a reviewer-approved run lock

Once a reviewer has signed off on a `--plan-out` plan, a follow-up normal operator run can pass the same file as `--approved-plan PATH` to refuse the run unless the current `--images-dir` (and `--manifest`, when supplied) re-produce the byte-equivalent in-memory plan. The compare runs AFTER every argument-shape gate but BEFORE any out-dir `mkdir`, any pipeline subprocess, or any out-dir artifact write, so a drift in `schema_version` / `helper_id` / `mode` / `explicit_boundaries` (boundary drift) / `image_count` / `slide_count` / `manifest_path` / image order / per-image `filename` / `asset_id` / `media_type` / `byte_count` / `sha256` / `intended_slide_index` / `slide_title` / `alt_text` / `intended_use` refuses the run with rc 2 and leaves the out-dir untouched.

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_local_images_to_editable_ppt.py \
  --images-dir "$IMAGES_DIR" \
  --out-dir "$RUN_DIR/out" \
  --approved-plan "$RUN_DIR/approved.json"
```

Contract for `--approved-plan PATH`: must be a regular local non-symlink file, must not be URI-shaped, must have no symlink ancestor; refused for directories and missing paths (AP1..AP4). The bytes are decoded as UTF-8 JSON and structurally validated (schema_version / helper_id / mode / explicit_boundaries / image_count / slide_count / manifest_path / images array); integer fields reject Python booleans (an approved plan with `"image_count": true` would otherwise compare-match the current `1` via Python's `True == 1` equality). `--approved-plan` is mutually exclusive with `--plan-out` / `--write-manifest-template` / `--self-test`; it requires `--images-dir` + `--out-dir` and may combine with the optional `--manifest`.

On a clean match the run proceeds exactly as the unlocked normal operator mode does, and the produced `summary.json` carries an `approved_plan` block `{ "path": "<approved plan path>", "sha256": "<64-char lowercase hex of approved-plan bytes>", "matched": true }` (the truth-checker refuses on a missing key, a non-True `matched`, or a non-hex `sha256`). On an unlocked run, `summary.approved_plan` is exactly `null` and the README has no approval claim. The produced `README.md` adds an `## Approved-plan lock` section naming the same path + sha256 and pointing reviewers at `summary.json` field `approved_plan`, so a reviewer can confirm the lock by running `sha256sum <approved-plan-path>` against the recorded sha256.

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

### `--bundle` operator handoff shortcut

Operators who hand off a single folder to a reviewer (`bundle/images/` and an optional `bundle/manifest.json`) can use the `--bundle DIR` shortcut instead of typing `--images-dir <bundle>/images` and (when present) `--manifest <bundle>/manifest.json` explicitly. The shortcut resolves to the same two paths and then delegates to the same image discovery, manifest, plan-only, approved-plan, out-dir, summary, README, visual-quality, inventory, and PPTX gates the explicit-flag flow runs — no new content rules are added on top.

```bash
# Bundle layout (operator handoff folder outside the repo):
#   bundle/
#     images/         # required, flat directory of PNG / JPG / JPEG
#     manifest.json   # optional caller-supplied manifest

# Easiest real-operator command — produces deck.pptx + summary.json +
# inventory.json + visual_quality.json + workspace/ + reports/ +
# README.md under "$RUN_DIR/operator_out":
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_local_images_to_editable_ppt.py \
  --bundle "$RUN_DIR/bundle" \
  --out-dir "$RUN_DIR/operator_out"

# Plan-only preflight through the bundle:
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_local_images_to_editable_ppt.py \
  --bundle "$RUN_DIR/bundle" \
  --plan-out "$RUN_DIR/plan.json"

# Reviewer-approved run lock through the bundle:
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_local_images_to_editable_ppt.py \
  --bundle "$RUN_DIR/bundle" \
  --out-dir "$RUN_DIR/operator_out" \
  --approved-plan "$RUN_DIR/approved.json"
```

Contract for `--bundle DIR` (BUN1..BUN8): must not be URI-shaped, a symlink, or have a symlink ancestor; must exist and be a directory; must contain a non-symlink `images/` subdirectory. `<bundle>/manifest.json` is optional — when present it is forwarded verbatim to the existing manifest validator (MAN1..MAN12), so malformed JSON, missing fields, URL/credential/public-hosting wording, and the rest of the manifest content gates still fire with the same diagnostics they produce under explicit `--manifest`. `--bundle` is mutually exclusive with `--images-dir` / `--manifest` (mixed input styles are ambiguous and refused) and with `--write-manifest-template` / `--self-test`; combine it with `--plan-out`, `--out-dir`, and `--approved-plan` exactly as you would the explicit flags. The explicit `--images-dir` / `--manifest` flags keep working as documented above — `--bundle` is purely a usability shortcut for the operator-handoff shape.

### Optional `<bundle>/generated_provenance.json` sidecar

A bundle may optionally include a local-only `generated_provenance.json` sidecar describing operator-declared intent for mock / generated image bytes already staged under `<bundle>/images/`. The sidecar is metadata only — the helper does NOT call D-One, MCP, Qoder, a public network, a model API, an image search, or telemetry to materialise the bytes; the sidecar only records what the operator declared so the review package surfaces inspectable provenance alongside the embedded `ppt/media/*` parts. The sidecar is bundle-only by design (no explicit `--generated-provenance` flag). On absent-sidecar bundles the produced `deck.pptx`, `workspace/`, `reports/`, `inventory.json`, `visual_quality.json`, and the `README.md` section list are unchanged versus the pre-sidecar bundle path; `summary.json` always carries a new top-level `generated_provenance` key — `null` when no sidecar was supplied, mirroring the way every run already carries `approved_plan: null` when no `--approved-plan` was supplied — and every `image_provenance[*]` row continues to carry no sidecar fields. The new key is a forward-only summary-shape evolution: an older `summary.json` from before this change does not carry the key and is refused by the helper truth-checker and by `validate_operator_review_package.py` (same enforcement as the pre-existing `approved_plan` key).

```json
{
  "schema_version": "1",
  "entries": [
    {
      "filename": "alpha_marker.png",
      "generator_source": "mock_generated",
      "intent_summary": "Synthetic accent for the alpha cover (mock; local-only)",
      "placement_role": "hero_page",
      "text_policy": "no_text",
      "subject_domain": "abstract_marker",
      "custom_descriptor": "soft_color_block_v1"
    }
  ]
}
```

Contract for `<bundle>/generated_provenance.json` (GP1..GP13): must not be URI-shaped, a symlink, or have a symlink ancestor; must parse as a UTF-8 JSON object carrying exactly `schema_version == "1"` and a non-empty `entries` array. Each entry carries exactly `filename` / `generator_source` / `intent_summary` / `placement_role` / `text_policy` / `subject_domain` plus an optional `custom_descriptor`. Enums are closed: `generator_source` ∈ `{"mock_generated", "operator_declared_generated"}` (`mock_generated` describes synthetic bytes the local mock pipeline materialised; `operator_declared_generated` describes generated bytes the operator declares from a prior local image-gen run they ran themselves — same validator surface, same lane); `placement_role` ∈ `{"hero_page", "local_region"}`; `text_policy` ∈ `{"no_text", "decorative_glyphs", "caption_safe"}`; `subject_domain` ∈ `{"abstract_marker", "background_pattern", "data_visual_concept", "icon_concept", "process_concept"}`. `intent_summary` passes the same safe-string gates `--manifest` free-text fields apply (no URL / URI / path separator / credential / token / API-key shape / public upload-share-hosting wording / raw-source / confidential / customer marker / positive D-One / MCP / Qoder / model API / image search / network / telemetry / AI-brand success claim). Optional `custom_descriptor` must match `^[a-z][a-z0-9_]{0,63}$`. The sidecar filename set must equal the discovered images set exactly — no missing, no extra, no duplicate.

### Optional `--write-generated-provenance-template` for a starter sidecar

If you would rather start from a skeleton sidecar than hand-author the `<bundle>/generated_provenance.json` JSON, run the helper in generated-provenance template writer mode against either `--images-dir DIR` or `--bundle DIR`:

```bash
# From a flat images directory:
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_local_images_to_editable_ppt.py \
  --images-dir "$IMAGES_DIR" \
  --write-generated-provenance-template "$RUN_DIR/generated_provenance_template.json"

# From a bundle (writer consumes <bundle>/images only and ignores any
# auto-detected <bundle>/manifest.json / <bundle>/generated_provenance.json):
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_local_images_to_editable_ppt.py \
  --bundle "$RUN_DIR/bundle" \
  --write-generated-provenance-template "$RUN_DIR/generated_provenance_template.json"
```

The writer reuses the same flat PNG / JPG / JPEG discovery the normal mode applies (IG1..IG9 gates), then writes a JSON sidecar at the supplied path whose `entries[]` array carries one entry per discovered image, sorted by filename, with `schema_version="1"` plus the helper's safe defaults: `generator_source = "operator_declared_generated"`, `placement_role = "local_region"`, `text_policy = "no_text"`, `subject_domain = "abstract_marker"`, and a bland `intent_summary` placeholder that explicitly reminds the operator to edit before use. `custom_descriptor` is omitted by default. The generated file is byte-compatible with the bundle's expected sidecar path — copy it to `<bundle>/generated_provenance.json`, hand-edit the per-entry fields as needed, then re-run with `--bundle DIR + --out-dir OUT` (or `--plan-out PATH`).

Contract for `--write-generated-provenance-template PATH` (GPT1..GPT6) mirrors `--write-manifest-template` (MT1..MT6) byte-for-byte: must not be URI-shaped, a symlink, or have a symlink ancestor, must not anchor under the repo tree, must have an existing directory parent, and must not already exist (stale bytes on a pre-existing target are preserved; the writer never overwrites operator files). The writer does NOT run the pipeline, does NOT produce a PPTX, does NOT produce a `visual_quality.json` report or operator-facing `README.md`, and does NOT call D-One / MCP / Qoder / a public network / a model API / an image search / telemetry. Mutually exclusive with `--out-dir` / `--manifest` / `--plan-out` / `--approved-plan` / `--write-manifest-template` / `--self-test`; requires `--images-dir` OR `--bundle`. After editing, the produced file passes GP1..GP13 unchanged, so the next `--bundle DIR --plan-out PATH` or `--bundle DIR --out-dir OUT --approved-plan PATH` accepts it and surfaces the per-row `generator_source` / `intent_summary` / `placement_role` / `text_policy` / `subject_domain` (and `custom_descriptor` when supplied) in the plan + summary alongside the top-level `generated_provenance = {path, entry_count}` block.

When the sidecar is present and validated, every `summary.image_provenance[]` row carries `generator_source` / `intent_summary` / `placement_role` / `text_policy` / `subject_domain` (and `custom_descriptor` when supplied), `summary.generated_provenance` becomes `{ "path": "<sidecar-path>", "entry_count": <int> }`, and the produced `README.md` adds a `## Generated image provenance` section listing the per-entry fields. When the sidecar is absent, `summary.generated_provenance` is exactly `null` and the README omits that section. `scripts/validate_operator_review_package.py` enforces the same closed enums and the `{path, entry_count}` shape so a tampered post-helper edit refuses on re-validation.

For the broader aggregate that runs every delegated core editable-PPT smoke in order (operator local-image intake, operator local-images trial, placement readback, image-asset acceptance, taxonomy / text-policy / provenance handoff smokes, render-model roundtrip, trace acceptance, …) — `scripts/operator_local_images_to_editable_ppt.py --self-test` and `scripts/operator_local_images_trial.py --self-test` are both wired in as delegated smokes so the operator local-images route AND the one-command trial are covered by this single top-level command:

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
  python3 scripts/core_editable_ppt_acceptance.py --self-test
```

For the future-real-D-One readiness side (`PREFLIGHT_READY_FOR_MANUAL_TRIAL` is the best outcome today; it is **not** a live PASS):

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
  python3 scripts/d_one_live_readiness_preflight.py --self-test
```

## One-command operator trial

For a reviewer who wants the shortest end-to-end run on synthetic inputs without hand-authoring a `--plan-out` / `--approved-plan` loop, `scripts/operator_local_images_trial.py` drives the helper twice — first with `--plan-out` to write an approved plan, then in normal mode under `--approved-plan` — into a caller-supplied directory outside the repo, re-checks the produced review package on disk via `scripts/validate_operator_review_package.py --out-dir <produced review package>` (read-only stdlib companion; never writes to the package), and writes a concise top-level `README.md` naming what to open first AND recording the on-disk re-validation rc + the read-only / local-only nature of that re-check under an `## On-disk re-validation` section.

```bash
RUN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/szh-trial-XXXX")
echo "Trial artifacts will land under: $RUN_DIR/trial"

TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_local_images_trial.py \
  --out-dir "$RUN_DIR/trial"

# When done inspecting, clean up:
#   rm -rf "$RUN_DIR"
```

On a clean run the trial leaves the following layout under `--out-dir`:

- `input_images/` — the synthetic flat folder the trial generated (one PNG + one JPEG, magic-byte-valid; same payloads the helper's `--self-test` uses).
- `approved_plan.json` — the plan written by `scripts/operator_local_images_to_editable_ppt.py --plan-out` against the synthetic folder. A reviewer in a real workflow would inspect and sign off on this file before allowing the normal-mode run.
- `review_package/` — the full helper output under the approved-plan run lock: `deck.pptx`, `summary.json` (with the `approved_plan` block carrying `matched: true`), `README.md` (helper-written review-package README), `inventory.json`, `visual_quality.json`, `workspace/source_image_assets.json`, and `reports/pipeline_report.{json,txt}`.
- `README.md` — top-level operator README pointing reviewers at the seven files above in the order they should open them.

The trial does NOT duplicate the helper's manifest / plan / approved-plan / pipeline / contract / inventory / visual-quality validation; it only verifies that the canonical produced files exist and that `summary.approved_plan.matched == true` (defense in depth — the helper's own truth-checker already gates every byte-level invariant before it returns 0), then delegates a final on-disk re-check to `scripts/validate_operator_review_package.py --out-dir <produced review package>` (the read-only stdlib companion documented in the next section) and refuses the run on any validator failure so a tampered or torn package cannot leave a positive-looking trial README behind. The validator rc is recorded in the trial-written top-level README under `## On-disk re-validation` alongside the literal command an operator can re-run anytime. The `--out-dir` argument re-uses the same gate the sibling helpers enforce (URI / symlink / symlink-ancestor / inside-REPO_ROOT / non-empty pre-existing refusals; stale bytes on a refused path are preserved).

Run `--self-test` to exercise the trial under per-run TMPDIR fixtures plus every documented `--out-dir` refusal probe and the boundary-claim scan:

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
  python3 scripts/operator_local_images_trial.py --self-test
```

Local-only — the trial does NOT call D-One, MCP, Qoder, a public network, telemetry, a model API, an image search, or any external service. NOT a prompt / report / Markdown-to-PPTX automation. Real D-One remains UNVERIFIED.

### Generated-image bundle trial (sidecar end-to-end)

For a reviewer who wants to see the optional `<bundle>/generated_provenance.json` sidecar surface end to end (the `summary.generated_provenance` block AND the per-row `generator_source` / `intent_summary` / `placement_role` / `text_policy` / `subject_domain` projection AND the helper-written `## Generated image provenance` README section) AND the reviewer-approved-plan run lock (`summary.approved_plan.matched=true`) on the same run, without assembling a bundle or writing the plan by hand, `scripts/generated_images_to_editable_ppt_trial.py` drives the helper twice — once through `--bundle <bundle> --plan-out <DIR>/approved_plan.json` to write the reviewer-approved plan (which carries the top-level `generated_provenance` block plus the per-row sidecar fields), and once through `--bundle <bundle> --out-dir <DIR>/review_package --approved-plan <DIR>/approved_plan.json` so the produced review package is gated behind the plan — against a synthetic two-image bundle that exercises representative sidecar diversity (both `placement_role` values, two distinct `text_policy` / `subject_domain` values, plus both the present and absent forms of the optional `custom_descriptor` — not exhaustive enum coverage, since `text_policy` has three closed members (`caption_safe` is not positively exercised) and `subject_domain` has five (`data_visual_concept` / `icon_concept` / `process_concept` are not positively exercised); the helper's own `--self-test` sidecar fixture uses the same 2-of-3 / 2-of-5 subset, so no component positively walks every closed-enum member end-to-end today, and what IS gated is closure of the legal set via the helper's GP9 enum-membership refusal and the validator's mirror gate):

```bash
RUN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/szh-gen-img-trial-XXXX")
echo "Trial artifacts will land under: $RUN_DIR/trial"

TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/generated_images_to_editable_ppt_trial.py \
  --out-dir "$RUN_DIR/trial"

# When done inspecting, clean up:
#   rm -rf "$RUN_DIR"
```

On a clean run the trial leaves `bundle/` (synthetic `images/` + `manifest.json` + `generated_provenance.json`), `approved_plan.json` (the reviewer-approved plan the second helper invocation was gated behind), `review_package/` (the full helper output, whose `summary.approved_plan.matched=true` records the run lock), and a top-level `README.md` that tells the operator to inspect `approved_plan.json` first, then `review_package/README.md`, then `review_package/deck.pptx`, plus the on-disk re-validation rc. Run `--self-test` to exercise the trial under per-run TMPDIR fixtures plus every documented `--out-dir` refusal probe AND a post-plan sidecar drift probe that proves the approved-plan compare refuses with rc 2 BEFORE any `review_package/` artifact is created:

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
  python3 scripts/generated_images_to_editable_ppt_trial.py --self-test
```

The trial's `--self-test` is wired into `scripts/core_editable_ppt_acceptance.py`. Local-only — the sidecar's `generator_source == "mock_generated"` records declared operator intent for the staged synthetic bytes; the trial does NOT call D-One, MCP, Qoder, a public network, telemetry, a model API, an image search, or any external service. Real D-One remains UNVERIFIED.

## Operator image-folder workflow (one-command and two-step reviewed)

When an operator already has a folder of generated images on disk, `scripts/operator_images_to_review_package.py` is the one-command entrypoint that sequences the existing helper end to end: it copies the images into `<out-dir>/bundle/images/` (refusing symlinks / subdirectories / non-image files before any byte is copied, so the source folder is never mutated), writes the `manifest.json` + `generated_provenance.json` templates and the reviewable `approved_plan.json`, builds the `review_package/` under the helper's approved-plan run lock, runs the read-only `scripts/validate_operator_review_package.py` re-check, and writes a top-level `README.md` carrying the exact commands it ran.

### Try it now (zero-substitution pilot)

No images of your own? Stage a throwaway one-image folder from a committed
synthetic PNG and run the entrypoint end to end — copy-paste, no path edits. Use
a filename whose stem starts with a lowercase letter and uses only `[a-z0-9_]`
(e.g. `cover.png`); a leading-digit stem like `01_cover.png` passes intake but
fails downstream on the render-model `image_ref` pattern. Everything below writes
only under fresh `mktemp -d` dirs outside the repo.

```bash
# Stage a throwaway image folder from a committed synthetic PNG.
RUN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/szh-folder-pilot-XXXX")
mkdir "$RUN_DIR/images"
cp examples/synthetic_8_page_product_brief/assets/synthetic_marker.png \
   "$RUN_DIR/images/cover.png"

# (1) One-command mode: stage + build + re-validate.
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_images_to_review_package.py \
  --images-dir "$RUN_DIR/images" --out-dir "$RUN_DIR/out"
```

Inspect the outputs — `approved_plan.json` sits at the top level, the rest under
`review_package/`:

- `"$RUN_DIR/out/approved_plan.json"` — the reviewable plan.
- `"$RUN_DIR/out/review_package/deck.pptx"` — the editable deck.
- `"$RUN_DIR/out/review_package/summary.json"` — slide / embedded-media evidence.
- `"$RUN_DIR/out/review_package/inventory.json"` — relationship readback.
- `"$RUN_DIR/out/review_package/visual_quality.json"` — per-slide quality report.

```bash
# (2) Two-step reviewed mode (human checkpoint) on the same staged folder.
REV=$(mktemp -d "${TMPDIR:-/tmp}/szh-folder-review-XXXX")
# --plan stages bundle/ + approved_plan.json, then STOPS (no deck.pptx yet).
python3 scripts/operator_images_to_review_package.py --plan \
  --images-dir "$RUN_DIR/images" --out-dir "$REV/out"
# Inspect "$REV/out/approved_plan.json", then build from the reviewed plan:
python3 scripts/operator_images_to_review_package.py --resume \
  --out-dir "$REV/out"
```

```bash
# (3) Optional reviewed metadata: --manifest / --generated-provenance replace
#     the default templates (one-command or --plan; refused with --resume). The
#     filename set must equal the staged images.
META=$(mktemp -d "${TMPDIR:-/tmp}/szh-folder-meta-XXXX")
cat >"$META/manifest.json" <<'JSON'
{ "schema_version": "1",
  "images": [ { "filename": "cover.png", "slide_title": "Cover",
                "alt_text": "Synthetic cover marker",
                "intended_use": "spot illustration" } ] }
JSON
cat >"$META/generated_provenance.json" <<'JSON'
{ "schema_version": "1",
  "entries": [ { "filename": "cover.png",
                 "generator_source": "operator_declared_generated",
                 "intent_summary": "Synthetic cover accent for the pilot deck",
                 "placement_role": "hero_page", "text_policy": "no_text",
                 "subject_domain": "abstract_marker" } ] }
JSON
python3 scripts/operator_images_to_review_package.py \
  --images-dir "$RUN_DIR/images" --out-dir "$META/out" \
  --manifest "$META/manifest.json" \
  --generated-provenance "$META/generated_provenance.json"
```

The subsections below document each mode in full; the pilot above is the fastest
way to exercise all four against a committed asset. Clean up when done:
`rm -rf "$RUN_DIR" "$REV" "$META"`.

### Full pilot: messy generated folder -> validated package

The "Try it now" pilot above starts from an already-clean filename. Real
generated-image folders rarely do, so this pilot starts from a **messy** folder
and walks the complete reviewed chain end to end: `--prepare-images-only` ->
`--templates-only` -> `--plan` -> `--resume` ->
`validate_operator_review_package.py`. It is copy-paste with no path edits and
writes only under a fresh `mktemp -d` dir outside the repo. Have your own folder
of generated images? Skip step 0 and point `--images-dir` at it. The per-mode
subsections below carry each mode's full gate/contract details.

```bash
# 0. A throwaway, caller-owned folder of "generated" images with realistic
#    MESSY names -- spaces, uppercase, parentheses, hyphens, and CJK. Staged
#    here from one committed synthetic PNG so the pilot is copy-paste; in real
#    use this is your own folder of distinct images.
PILOT=$(mktemp -d "${TMPDIR:-/tmp}/szh-genimg-pilot-XXXX")
mkdir "$PILOT/messy"
SRC=examples/synthetic_8_page_product_brief/assets/synthetic_marker.png
cp "$SRC" "$PILOT/messy/Hero Cover (v2).png"
cp "$SRC" "$PILOT/messy/Q3-Report FINAL.png"
cp "$SRC" "$PILOT/messy/季度总结.png"

# 1. PREPARE -> normalised images/ + filename_mapping.json. Builds nothing
#    heavier and never mutates your source folder.
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_images_to_review_package.py --prepare-images-only \
  --images-dir "$PILOT/messy" --out-dir "$PILOT/prepared"
```

`--prepare-images-only` writes **`$PILOT/prepared/filename_mapping.json`** (one
record per image: `original_filename`, `safe_filename`, `byte_count`, `sha256`,
`media_type`, `extension`) and the normalised **`$PILOT/prepared/images/`**.
The three messy names normalise to `image_ref`-valid stems —
`Hero Cover (v2).png` -> `hero_cover_v2_.png`, `Q3-Report FINAL.png` ->
`q3_report_final.png`, `季度总结.png` -> `img_.png` (a name with no usable
ASCII stem falls back to the `img_` prefix). Inspect the mapping, then feed the
prepared `images/` forward.

```bash
# 2. METADATA/TEMPLATES -> editable starter manifest.json +
#    generated_provenance.json for the prepared images (hand-edit before a real
#    review; used as-is here).
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_images_to_review_package.py --templates-only \
  --images-dir "$PILOT/prepared/images" --out-dir "$PILOT/templates"

# 3. PLAN -> stage the bundle from the prepared images + reviewed metadata and
#    write the reviewable plan, then STOP (no deck.pptx yet).
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_images_to_review_package.py --plan \
  --images-dir "$PILOT/prepared/images" --out-dir "$PILOT/out" \
  --manifest "$PILOT/templates/manifest.json" \
  --generated-provenance "$PILOT/templates/generated_provenance.json"
```

`--plan` writes **`$PILOT/out/approved_plan.json`** (plus `$PILOT/out/bundle/`)
and stops — a human inspects the plan here; no review package exists yet. To
approve a *changed* plan, discard `$PILOT/out` and re-run `--plan`.

```bash
# 4. RESUME -> build the review package from the reviewed plan (same validators
#    and evidence as one-command mode).
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_images_to_review_package.py --resume \
  --out-dir "$PILOT/out"

# 5. VALIDATE -> read-only on-disk re-check of the produced package (rc 0).
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/validate_operator_review_package.py \
  --out-dir "$PILOT/out/review_package"
```

`--resume` writes **`$PILOT/out/review_package/`** containing **`deck.pptx`**
(native editable deck, one slide per prepared image), **`summary.json`**
(slide / embedded-media evidence, `approved_plan.matched=true`),
`inventory.json`, `visual_quality.json`, `workspace/`, `reports/`, and a
`README.md`; `validate_operator_review_package.py` re-checks it read-only.

Where each named artifact lands:

| Artifact | Path | Written by |
| --- | --- | --- |
| `filename_mapping.json` | `$PILOT/prepared/filename_mapping.json` | step 1 — `--prepare-images-only` |
| `manifest.json` / `generated_provenance.json` | `$PILOT/templates/` | step 2 — `--templates-only` |
| `approved_plan.json` | `$PILOT/out/approved_plan.json` | step 3 — `--plan` |
| `summary.json`, `deck.pptx` | `$PILOT/out/review_package/` | step 4 — `--resume` |

Clean up when done: `rm -rf "$PILOT"`. Local-only — no D-One, MCP, Qoder,
public network, model API, image search, or telemetry, and nothing is written
under the repo tree. Real D-One remains UNVERIFIED.

### Normal (one command)

```bash
RUN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/szh-op-XXXX")

TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_images_to_review_package.py \
  --images-dir /path/to/images \
  --out-dir "$RUN_DIR/out"

# When done inspecting, clean up:
#   rm -rf "$RUN_DIR"
```

One-command mode **auto-approves its own plan** to drive the build — the `--approved-plan` gate still catches drift between staging and building, but no human inspects the plan in between. For a real human-review checkpoint, use the two-step mode below.

### Two-step reviewed mode (plan → review → resume)

`--plan` stages the bundle and writes the reviewable `approved_plan.json`, then **stops** — no `deck.pptx` and no `review_package/` are built. A human inspects the plan (and the `manifest.json` / `generated_provenance.json` templates), and only then runs `--resume`, which builds the review package with the **same validators and evidence** as one-command mode. Running `--resume` is the operator's explicit sign-off that the plan was reviewed.

```bash
RUN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/szh-op-XXXX")

# 1. Plan: stage the bundle + reviewable plan, then stop.
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_images_to_review_package.py --plan \
  --images-dir /path/to/images \
  --out-dir "$RUN_DIR/out"

# 2. Review by hand (the plan-step README spells out this checklist):
#      less "$RUN_DIR/out/README.md"
#      less "$RUN_DIR/out/approved_plan.json"
#      less "$RUN_DIR/out/bundle/generated_provenance.json"

# 3. Resume: build the review package from the reviewed plan.
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_images_to_review_package.py --resume \
  --out-dir "$RUN_DIR/out"

# When done inspecting, clean up:
#   rm -rf "$RUN_DIR"
```

`--resume` takes `--out-dir` only (the bundle + plan are already staged; passing `--images-dir` is refused). It fails closed if the bundle has drifted from the approved plan between the two steps — editing any byte under `bundle/images/`, `bundle/manifest.json`, or `bundle/generated_provenance.json` in a way that changes the plan refuses the resume before any review-package artifact is created. To approve a changed plan, discard the directory and re-run `--plan`. The resume gate also refuses a URI-shaped / symlinked / symlink-ancestor / under-repo `--out-dir`, an `--out-dir` that is not a prior `--plan` output, and an `--out-dir` whose `review_package/` was already built.

### Have messy generated filenames? (`--prepare-images-only`)

Real generated-image folders routinely carry filenames with spaces, uppercase letters, parentheses, dots, hyphens, or CJK characters. The operator lane uses each filename stem **verbatim** as the asset_id that becomes a slide's render_model `image_ref`, which `schemas/render_model.schema.json` constrains to `^[a-z][a-z0-9_]*$` — stricter than the IG6 `--images-dir` gate (it forbids a leading digit, dots, hyphens, and uppercase), so such names pass staging but build a broken deck. Rather than hand-rename every file, point `--prepare-images-only` at the folder: it copies each PNG / JPG / JPEG into `<out-dir>/images/` under a stable, safe filename (lowercased, every character outside `[a-z0-9_]` mapped to `_` and collapsed, prefixed `img_` when it would not start with a lowercase letter, truncated to the byte cap — so the stem matches the `image_ref` contract, which implies IG6) and writes an inspectable `filename_mapping.json` (one record per image: `original_filename`, `safe_filename`, `byte_count`, `sha256`, `media_type`, `extension`) plus a short `README.md`. It builds **nothing heavier** — no `bundle/`, `approved_plan.json`, `review_package/`, `deck.pptx`, `workspace/`, or `reports/` — and never mutates your source folder:

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_images_to_review_package.py --prepare-images-only \
  --images-dir "/path/to/messy images" \
  --out-dir "$RUN_DIR/prepared"
```

Every entry passes the same safety gate the bundle-staging path uses (symlink / subdirectory / non-image / hidden-dotfile / size + count caps), and a filename collision after normalisation is refused on the safe stem (matching IG7) **before any byte is copied**, so a refused run leaves no half-written `images/`. Feed the prepared `<out-dir>/images/` into a `--templates-only` / `--plan` / one-command run. `--prepare-images-only` is mutually exclusive with `--plan` / `--resume` / `--templates-only` / `--manifest` / `--generated-provenance` and is refused (rc 2, no `--out-dir` created) if combined with them.

### Just want editable starter metadata? (`--templates-only`)

To author reviewed metadata without writing JSON by hand, point `--templates-only` at your image folder: it writes JUST `manifest.json` and `generated_provenance.json` (the helper's safe-default templates) into a fresh `--out-dir` and builds **nothing else** — no `bundle/`, no `approved_plan.json`, no `review_package/`, no `deck.pptx`:

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_images_to_review_package.py --templates-only \
  --images-dir /path/to/images \
  --out-dir "$RUN_DIR/templates"
```

Both files are written by the helper's own `--write-manifest-template` / `--write-generated-provenance-template` writers against a single stable snapshot of the images (copied once into a private temp dir), so they always agree on the filename set and pass the helper's `_validate_manifest_arg` (MAN1..MAN12) / `_validate_generated_provenance_sidecar` (GP1..GP13) gates verbatim. Hand-edit the two files, then feed them back via `--manifest` / `--generated-provenance` (below). `--templates-only` is mutually exclusive with `--plan` / `--resume` / `--manifest` / `--generated-provenance` and is refused (rc 2, no `--out-dir` created) if combined with them.

### Optional operator-supplied metadata (`--manifest` / `--generated-provenance`)

By default the wrapper writes placeholder `manifest.json` / `generated_provenance.json` templates into the bundle. An operator who has already reviewed per-image slide intent or generated-image provenance can supply them instead, in one-command **or** `--plan` mode (the flags are refused with `--resume`, which rebuilds from the already-staged bundle):

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_images_to_review_package.py \
  --images-dir /path/to/images \
  --out-dir "$RUN_DIR/out" \
  --manifest /path/to/reviewed_manifest.json \
  --generated-provenance /path/to/reviewed_provenance.json
```

Each supplied path is gated at the CLI for URI-shape / symlink / symlink-ancestor / missing / non-file (rc 2 **before** any image is staged). Its content is then validated by the helper's own `_validate_manifest_arg` (MAN1..MAN12) / `_validate_generated_provenance_sidecar` (GP1..GP13) gates against the **copied** image basenames — JSON parse, `schema_version == "1"`, the closed field set / closed enums, the safe-string deny lists (no URL / URI / path separator / credential / public-upload / confidential / fake-success wording), and the filename-set-equals-the-copied-images cross-check — and the file is copied race-safely into the bundle in place of the default template. Either flag may be supplied alone or together; an omitted flag keeps the default template for that file. Because the downstream plan-out / approved-plan / resume drift-lock build the plan from the bundle, the produced `approved_plan.json` and `review_package/summary.json` reflect the supplied metadata with no further wiring. The wrapper re-implements no contract logic — it reuses the helper's validators verbatim. A filename-set mismatch, unsafe wording, malformed JSON, or a drift between the supplied metadata at `--plan` time and `--resume` all fail closed with no review package.

```bash
# Thirty-three self-test probes (one-command happy path + copy/TOCTOU gates
# + T15–T20 for the two-step flow + T21–T26 for operator-supplied
# metadata: valid custom manifest/provenance accepted and reflected in
# plan/summary, filename-set mismatch rejected, symlink/URI metadata path
# rejected, unsafe wording rejected, plan/resume works with supplied
# metadata, and the default no-metadata path is unchanged + T27–T28 for
# the --templates-only shortcut: template-only output that passes the
# helper validators, plus mutual-exclusion refusal + T29–T33 for the
# --prepare-images-only step: messy filenames (incl. dots / hyphens / a
# leading digit) normalised into image_ref-valid safe names, a
# post-normalisation collision failing closed, unsafe entries failing
# closed, mutual-exclusion refusal, and an end-to-end one-command build
# on the prepared images proving the safe stems satisfy the downstream
# image_ref contract ^[a-z][a-z0-9_]*$):
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
  python3 scripts/operator_images_to_review_package.py --self-test
```

Local-only — does NOT call D-One, MCP, Qoder, a public network, telemetry, a model API, an image search, or any external service. NOT a prompt / report / Markdown-to-PPTX automation. Real D-One remains UNVERIFIED.

## Re-validate an existing operator review package

After running the helper with `--bundle ... --out-dir ...` (or `operator_local_images_trial.py --out-dir ...`), the produced review package can be re-checked on disk without re-running the pipeline:

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/operator_local_images_to_editable_ppt.py \
  --bundle /path/to/bundle \
  --out-dir /path/to/output

TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/validate_operator_review_package.py \
  --out-dir /path/to/output
```

`scripts/validate_operator_review_package.py` is a read-only stdlib gate. It confirms `--out-dir` carries the required `deck.pptx` / `summary.json` / `inventory.json` / `visual_quality.json` / `README.md` files and `workspace/` / `reports/` directories, re-checks the locked `summary.helper_id == "operator_local_images_to_editable_ppt"` / `summary.real_d_one_status == "UNVERIFIED"` / `summary.explicit_boundaries` deny-tuple (no real D-One, MCP, Qoder, public network, model API, image search, telemetry, or raw prompt / report-to-PPT automation), verifies every `summary.pptx_path` / `summary.workspace_path` / `summary.report_dir` / `summary.inventory_path` / `summary.registry_path` / `summary.visual_quality.path` string resolves under `--out-dir` to the expected existing non-symlink artifact (so a tampered summary that reroutes the workspace's `source_image_assets.json` or the nested visual-quality report outside the package is refused with a `does not resolve under` diagnostic — the every-contract-field gate, not just the flat top-level subset), cross-checks `slide_count` / `image_count` / `embedded_media_count` / `source_classes` / `no_external_relationships` / each validator's `rc` value / `inventory.ok` / `inventory.findings_empty` / `visual_quality.error_count == 0` / every `image_provenance[*].placement_verified == True`, re-runs `validate_pptx_contract.py --expected-slide-count` and `inspect_pptx_inventory.py` against `deck.pptx` to confirm the same slide / media-part counts surface from a fresh inspection, and scans every JSON file plus `README.md` for URI / URL, credential / token / API-key shapes, public-upload / share / hosting wording, confidential / raw-source / customer markers, and positive real-D-One / MCP / Qoder / model-API / image-search / public-network / telemetry success claims (the locked negation-pinned boundary wording is whitelisted so it never false-positives). The URI scan covers BOTH `<scheme>://` shapes (`http://`, `https://`, `ftp://`, ...) AND a known-dangerous single-colon-scheme set that the `://`-anchored regex would otherwise miss — `data:` (defeats the embedded-content boundary by allowing arbitrary inline bytes), `file:` (local-filesystem path leak — `file:/etc/passwd` style; an earlier `\bfile:\b` shape was a silent false-negative because `\b` between non-word `:` and non-word `/` is no boundary, so `file:/foo` and `file://x` slipped through), `javascript:` / `vbscript:` (XSS payloads in a markdown-rendered README), `mailto:` / `tel:` (contact-channel leakage), `urn:` / `gopher:` / `ssh:` / `git:` / `ftp:` / `sftp:` / `ws:` / `wss:` / `view-source:` / `chrome-extension:` / `intent:` / `jdbc:` / `dict:` / `ldap:` / `ldaps:` / `imap:` / `pop:` / `smtp:` / `telnet:` / `rsync:` / `feed:` / `afp:` / `smb:` / `nfs:`. The dangerous-scheme regex requires the scheme to be followed by a non-whitespace / non-quote / non-bracket char, so generic English prose like `Note: foo` or `Time is 10:30` does not false-positive.

The validator also re-checks `summary.approved_plan` to mirror the helper's own truth-checker: the key must be present (a tampered post-helper edit that erases it is refused), the value must be either explicit JSON `null` (the run was not approved-plan-locked — accepted) or exactly `{path, sha256, matched: True}` with `path` a non-empty string, `sha256` a 64-character lowercase hex string (so a reviewer can pipe it to `sha256sum`), `matched` strictly `True` (the helper refuses with rc 2 BEFORE summary creation on a mismatch — by the time the summary exists, `matched=True` is the only valid value), and no unknown extra keys. Tampering that flips `matched` to False, drops the key, swaps in a malformed sha256, or adds an extra field is refused by the validator with a diagnostic naming the `approved_plan` sub-field.

The validator re-checks `summary.generated_provenance` the same way: the key must be present (a tampered erase is refused), the value must be either explicit JSON `null` (no `<bundle>/generated_provenance.json` was supplied — accepted) or exactly `{path, entry_count}` with `path` a non-empty string and `entry_count` an integer equal to `summary.image_count`. When the value is a `{path, entry_count}` object, every `image_provenance[*]` row must additionally carry `generator_source` (∈ `{"mock_generated", "operator_declared_generated"}`), non-empty string `intent_summary`, `placement_role` (∈ `{"hero_page", "local_region"}`), `text_policy` (∈ `{"no_text", "decorative_glyphs", "caption_safe"}`), `subject_domain` (∈ `{"abstract_marker", "background_pattern", "data_visual_concept", "icon_concept", "process_concept"}`), and an optional `custom_descriptor` matching `^[a-z][a-z0-9_]{0,63}$` — a post-helper edit that downgrades any field off the closed set refuses. When the value is `null`, NO `image_provenance[*]` row may carry any of those sidecar fields — the absent-sidecar leak gate refuses a tampered review package that erases the sidecar block AND simultaneously injects `generator_source` / `placement_role` / etc. onto a row to smuggle generated-image claims into a deck where no sidecar was supplied.

The validator does NOT mutate `--out-dir`, does NOT rebuild the pipeline, does NOT touch the committed repo tree, and does NOT call D-One, MCP, Qoder, a public network, a model API, an image search, or telemetry. `--self-test` exercises the happy path against a real review package produced by `scripts/operator_local_images_to_editable_ppt.py --bundle ... --out-dir ...` plus every documented tamper probe (T1–T23): missing `deck.pptx`, stale `summary.pptx_path`, positive real-D-One success claim, `placement_verified=false`, `visual_quality.totals.errors>0`, external URL, credential token, public-hosting wording, missing `summary.approved_plan` key, `approved_plan.matched=False`, malformed `approved_plan.sha256`, unknown `approved_plan` extra key, dangerous single-colon URI scheme `data:` / `mailto:` / `javascript:` in the README, `file:/etc/passwd` + `file:relative.txt` local-path shapes in the README, `summary.registry_path` rerouted outside `--out-dir`, `summary.visual_quality.path` rerouted outside `--out-dir`, sidecar happy path against a `generated_provenance.json`-carrying bundle (T18), missing `summary.generated_provenance` key (T19), out-of-vocab `image_provenance[*].generator_source` (T20), out-of-pattern `image_provenance[*].custom_descriptor` (T21), `generated_provenance.entry_count` mismatch with `image_count` (T22), and absent-sidecar leak — `summary.generated_provenance=null` AND an `image_provenance[*]` row carrying `generator_source` (T23):

```bash
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
  python3 scripts/validate_operator_review_package.py --self-test
```

## Boundary reminders

- The pipeline never calls D-One, MCP, Qoder, a public network, telemetry, any model API, an image search, or any external service. Real D-One remains UNVERIFIED.
- Image-generation bytes under `ppt/media/` come from `run_d_one_generation.py --allow-synthetic-bytes` (a fixed minimal magic-byte-valid PNG/JPG/JPEG payload). Caller-supplied `local_asset` bytes (when the bundle carries `source_assets/`) are copied byte-identically through `materialize_image_assets.py`.
- No write lands under the repo tree on a happy run. The runner refuses symlinks at `--output` / `--workspace` / `--report-dir` and URI-shaped arguments before any subprocess fires.
- For raw-source → spec authoring, see [`authoring-workflow.md`](authoring-workflow.md); for the D-One image policy, see [`d-one-image-policy.md`](d-one-image-policy.md); for quality-gate coverage of each delegated smoke, see [`quality-gates.md`](quality-gates.md).
