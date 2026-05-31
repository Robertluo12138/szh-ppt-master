# Operator Generated-Image Pilot Trial Record

A single executed-trial evidence record for the first-stage lane: a **messy
folder of generated images -> validated editable-PPT review package**, walked end
to end through the full reviewed chain — `--prepare-images-only` ->
`--templates-only` -> `--plan` -> `--resume` ->
`validate_operator_review_package.py` -> PPTX contract / inventory. Docs-only: it
records one local trial run on 2026-05-30 and a verdict; it changes no pipeline
behavior. It complements
[`operator-image-folder-pilot-readiness.md`](operator-image-folder-pilot-readiness.md)
(which records the one-command `--images-dir/--out-dir` synthetic pilot) by
exercising the **two-step reviewed** chain with the prepare/templates front end,
following the runbook in
[`core-image-to-editable-ppt-quickstart.md`](core-image-to-editable-ppt-quickstart.md)
under *Full pilot: messy generated folder -> validated package*.

## Verdict

**Ready for a first real user image-folder pilot.** Every step returned rc 0, the
produced package re-validates on disk, and the deck passes the PPTX contract gate
at the expected slide count with a clean inventory. The one nuance below
(byte-identical-input readback fan-out) is an artifact of the copy-paste fixture,
not the tooling, and disappears with a real folder of distinct images.

## Exact Command Sequence

Run from the repo root with `TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1`. The fixture
is the documented messy synthetic folder — one committed synthetic PNG copied to
three realistic messy names (spaces, uppercase, parentheses, hyphens, CJK). Point
`--images-dir` at your own folder of distinct generated images to skip step 0.

```bash
PILOT=$(mktemp -d /tmp/szh-genimg-pilot-XXXX)
mkdir "$PILOT/messy"
SRC=examples/synthetic_8_page_product_brief/assets/synthetic_marker.png
cp "$SRC" "$PILOT/messy/Hero Cover (v2).png"
cp "$SRC" "$PILOT/messy/Q3-Report FINAL.png"
cp "$SRC" "$PILOT/messy/季度总结.png"

# 1 PREPARE    normalise messy names -> images/ + filename_mapping.json
python3 scripts/operator_images_to_review_package.py --prepare-images-only \
  --images-dir "$PILOT/messy" --out-dir "$PILOT/prepared"

# 2 TEMPLATES  editable starter manifest.json + generated_provenance.json
python3 scripts/operator_images_to_review_package.py --templates-only \
  --images-dir "$PILOT/prepared/images" --out-dir "$PILOT/templates"

# 3 PLAN       stage bundle + reviewable approved_plan.json, then stop
python3 scripts/operator_images_to_review_package.py --plan \
  --images-dir "$PILOT/prepared/images" --out-dir "$PILOT/out" \
  --manifest "$PILOT/templates/manifest.json" \
  --generated-provenance "$PILOT/templates/generated_provenance.json"

# 4 RESUME     build review_package/ (deck.pptx + summary.json + ...)
python3 scripts/operator_images_to_review_package.py --resume --out-dir "$PILOT/out"

# 5 VALIDATE   read-only on-disk re-check of the produced package
python3 scripts/validate_operator_review_package.py \
  --out-dir "$PILOT/out/review_package"

# 6 PPTX gate (optional)  contract + inventory on the produced deck
python3 scripts/validate_pptx_contract.py \
  --pptx "$PILOT/out/review_package/deck.pptx" --expected-slide-count 3
python3 scripts/inspect_pptx_inventory.py \
  --pptx "$PILOT/out/review_package/deck.pptx"
```

## Where Each Named Artifact Landed

All under the throwaway `$PILOT` dir outside the repo (`/tmp/...`). The repo tree
stayed byte-identical (`git status` clean), and the source `messy/` folder was
never mutated.

| Artifact | Path | Step |
| --- | --- | --- |
| `filename_mapping.json` | `$PILOT/prepared/filename_mapping.json` | 1 prepare |
| `manifest.json` / `generated_provenance.json` | `$PILOT/templates/` | 2 templates |
| `approved_plan.json` | `$PILOT/out/approved_plan.json` | 3 plan |
| `summary.json`, `deck.pptx` | `$PILOT/out/review_package/` | 4 resume |

Observed normalisation (step 1): `Hero Cover (v2).png -> hero_cover_v2_.png`,
`Q3-Report FINAL.png -> q3_report_final.png`, `季度总结.png -> img.png`.

## Validation Results

| Check | Result |
| --- | --- |
| 1 `--prepare-images-only` | rc 0 — 3 images normalised; `filename_mapping.json` + README written; nothing heavier built |
| 2 `--templates-only` | rc 0 — `manifest.json` + `generated_provenance.json` templates written |
| 3 `--plan` | rc 0 — bundle staged, `approved_plan.json` written, stopped at the review checkpoint (no deck) |
| 4 `--resume` | rc 0 — `review_package/` built; `summary.approved_plan.matched=true`; in-run `validate_operator_review_package` rc 0 |
| 5 `validate_operator_review_package.py` | rc 0 — package re-validates on disk |
| 6 `validate_pptx_contract.py --expected-slide-count 3` | rc 0 — all gates PASS: `slide_count.expected` 3/3, `media.targets_internal` / `media.inventory` / `media.embedded_only`, all four `minimal_evidence` |
| 6 `inspect_pptx_inventory.py` | rc 0 — 3 slides, 3 embedded `ppt/media/image{1,2,3}.png` parts, **no findings** |

`summary.json`: `slide_count=3`, `embedded_media_count=3`, `minimal_evidence` all
true, `generated_provenance` present. `approved_plan.json`: `slide_count=3`,
`image_count=3`. `deck.pptx` is a real ~8 KB OOXML package, one native slide per
prepared image.

## Operator Friction Discovered

- **Byte-identical inputs fan out the provenance readback (fixture artifact, not
  a defect).** The copy-paste fixture copies one committed PNG to three names, so
  all three inputs share a sha256. The PPTX keeps three distinct 1:1 media parts
  (`inventory.media_parts[].referencing_slides` = `[1]`, `[2]`, `[3]`), but the
  sha256-keyed readback in `summary.image_provenance[]` lists every matching
  part/slide per asset (`embedded_media_parts=[image1,image2,image3]`,
  `embedded_referencing_slides=[1,2,3]`) while `placement_verified` stays `true`.
  This refines the readiness note's Non-Blocking TODO wording: nothing "dedupes
  to a shared part" — there are three parts; the fan-out is purely in the
  provenance readback and disappears with a real folder of **distinct** images.
  Prefer distinct images for a real pilot.
- **All-CJK / no-ASCII-stem filenames need no pre-rename (resolved).**
  `季度总结.png` has no usable ASCII stem, so `--prepare-images-only` maps it to
  the uniform base `img` (step 1 above). A folder with several such names no
  longer collapses onto one `img_` stem and gets refused: each is given a
  distinct name with a deterministic numeric suffix (`img`, `img_2`, `img_3`, …)
  in sorted order, so a CJK-heavy folder prepares to distinct, `image_ref`-valid
  names with no manual rename. (An earlier revision instead normalised every
  no-ASCII-stem name toward `img_` and refused the resulting collision; this
  normalisation removes that friction.)
- **`review_package/` carries an internal `_pipeline_fixture/` dir.** The helper
  retains its materialised workspace inputs (`source.md`, `plan_spec.json`,
  `image_manifest_spec.json`, `assets/`, `specs/`) inside the operator-facing
  review package. Validator-accepted and harmless, but an operator browsing the
  package sees a dir the docs do not enumerate — minor cleanup candidate.
- **README records an absolute interpreter path.** The step READMEs quote the
  exact commands using the resolved `sys.executable`; copy-paste-safe locally, but
  a human moving them to another machine may prefer a bare `python3` (already in
  the readiness TODOs).

## Boundary

Local-only. The trial called no D-One, MCP, Qoder, public network, telemetry,
model API, or image search, and added no such behavior. Real D-One image
generation remains UNVERIFIED and out of scope for this lane. Nothing was written
under the repo tree; clean up the trial with `rm -rf "$PILOT"`.
