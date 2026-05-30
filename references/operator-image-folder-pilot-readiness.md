# Operator Image-Folder Pilot Readiness

A milestone readiness record for the first-stage lane: **local or generated
images -> validated editable-PPT review package** via the one-command
entrypoint `scripts/operator_images_to_review_package.py`. This is a
docs-only note. It records the result of a synthetic local pilot run on
2026-05-30 and the verdict for a first human local pilot. It does not change
pipeline behavior.

## Verdict

**Ready for a first human local pilot.** No blocking usability or correctness
issue was found. The remaining items in *Non-Blocking TODOs* are polish, not
gates.

## What The Pilot Exercised

A throwaway image folder outside the repo held synthetic PNG / JPEG bytes with
realistic, valid filename stems created in scrambled (non-sorted) order, plus a
second folder whose filenames contained spaces. The pilot then ran:

```
python3 scripts/operator_images_to_review_package.py \
    --images-dir <temp_images_dir> \
    --out-dir <temp_out_dir>
```

Observed on the happy path (both byte-identical and byte-distinct synthetic
inputs):

- the workflow ran end to end, rc=0, writing `bundle/`, `approved_plan.json`,
  `review_package/`, and a top-level `README.md` under the external out-dir;
- `review_package/deck.pptx` is a real OOXML package — one native slide per
  source image, each image embedded byte-for-byte into its own `ppt/media/*`
  part (the part sha256 matches the source file sha256);
- with byte-distinct inputs the per-image mapping is clean 1:1
  (`operator_filename -> ppt/media part -> intended slide`), every row
  `placement_verified=True`;
- `summary.json` carries `approved_plan.matched=true`, `generated_provenance`,
  `slide_count == embedded_media_count`, and all four `minimal_evidence`
  booleans true; `inventory.json` shows internal-only relationships;
  `visual_quality.json` reports 0 errors / 0 warnings;
- scrambled input order was copied into the bundle in deterministic sorted
  order;
- `scripts/validate_operator_review_package.py --out-dir <…>/review_package`
  re-validated the produced package rc=0, both inside the workflow and as a
  separate manual run.

The spaces-in-filenames folder failed closed at the manifest helper's IG6 stem
gate with a per-file, actionable rename message and an explicit recovery NOTE
(remove the partial out-dir or pass a fresh one). The original image folder was
never mutated, and the repo tree (`examples/`, `scripts/`) stayed byte-identical
across every run.

## Non-Blocking TODOs

These do not gate a first human pilot; capture them for follow-up evidence.

- **Copy-before-stem-check ordering.** The wrapper copies bytes into
  `bundle/images/` before the manifest helper's IG6 stem-pattern gate fires, so
  an invalid-stem folder (e.g. names with spaces) leaves a partial
  `bundle/images/` copy before failing. The error and recovery NOTE are clear,
  so this is ordering polish, not a correctness gate; a future change could
  pre-screen stems in the wrapper before any byte is copied.
- **Absolute interpreter path in the README commands.** The top-level README
  records the exact commands run using the resolved interpreter path
  (`sys.executable`). Accurate and copy-paste-safe locally; a human moving the
  commands to another machine may prefer a bare `python3`.
- **Duplicate input bytes fan out media references.** Byte-identical input
  images dedupe to a shared `ppt/media/*` part, so the readback lists every
  slide that shares those bytes. The placement gate still passes correctly
  (intended slide is in the readback set); distinct images map 1:1. Worth a
  human reviewer's awareness, not a defect.
- **Broader media formats.** SVG / GIF / WebP are not yet embeddable and fall
  back to a native placeholder shape; PNG / JPG / JPEG are the embeddable set
  for this lane. Known scope boundary.

## Human-Review Checkpoint (Two-Step Mode)

The one-command entrypoint auto-approves its own plan, which is convenient but
inserts no human review between staging and building. The lane now also offers
a two-step reviewed mode at the wrapper level — the first practical human-review
checkpoint for this path:

- `operator_images_to_review_package.py --plan --images-dir DIR --out-dir OUT`
  stages the bundle, writes the manifest / generated-provenance templates and
  the reviewable `approved_plan.json`, then **stops** — no `deck.pptx` and no
  `review_package/` are produced. The plan-step `README.md` carries the review
  checklist and the exact resume command.
- A human inspects `approved_plan.json` (and the templates), then runs
  `operator_images_to_review_package.py --resume --out-dir OUT`, which builds
  the review package with the same approved-plan run lock, validators, and
  evidence as one-command mode. `--resume` fails closed if the bundle drifted
  from the approved plan, and refuses path-traversal / symlink `--out-dir`
  inputs and any `--out-dir` that is not a prior `--plan` output.

This is covered by the wrapper's `--self-test` probes T15–T20 and documented in
[`core-image-to-editable-ppt-quickstart.md`](core-image-to-editable-ppt-quickstart.md).
One-command mode is unchanged.

## Boundary

The pilot was local-only. It did not call D-One, MCP, Qoder, a public network,
telemetry, a model API, or an image search, and added no such behavior. Real
D-One image generation remains UNVERIFIED and out of scope for this lane.
