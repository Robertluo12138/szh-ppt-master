# Operator Generated-Image Pilot Trial Record

A single executed-trial evidence record for the first-stage lane: a **messy folder
of byte-distinct generated images -> validated editable-PPT review package**, walked
end to end through the full reviewed chain — `--prepare-images-only` ->
`--templates-only` -> minimal metadata edit -> `--plan` -> `--resume` ->
`validate_operator_review_package.py` -> PPTX contract / inventory. Docs-only: it
records one local trial run on 2026-05-30 and a verdict; it changes no pipeline
behavior. It complements
[`operator-image-folder-pilot-readiness.md`](operator-image-folder-pilot-readiness.md)
(which records the one-command `--images-dir/--out-dir` synthetic pilot) by
exercising the **two-step reviewed** chain on a **distinct, mixed-format** fixture
— four byte-distinct, visually-distinct solid-colour PNGs plus one minimal,
byte-distinct, magic-byte-valid JPEG *container* with no scan data (see the JPEG
caveat below) — following the runbook in
[`core-image-to-editable-ppt-quickstart.md`](core-image-to-editable-ppt-quickstart.md)
under *Full pilot: messy generated folder -> validated package*.

## Verdict

**The current path is good enough for a first real user image-folder pilot — no
blocker found.** Every step returned rc 0, the produced package re-validates on
disk, and the deck passes the PPTX contract gate at the expected slide count with a
clean inventory. With **byte-distinct** inputs the per-image provenance readback is
**clean 1:1** (each operator file -> exactly one `ppt/media` part -> exactly one
slide, `placement_verified=true`); this run *verifies* what the earlier
byte-identical copy-paste fixture could only assert. The output deck is
**practically usable as an editable starting scaffold, not a finished narrative
deck** — see *Is The Deck Usable?*. The three gaps below are usability polish, not
gates.

## Exact Command Sequence

Run from the repo root with `TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1`. The repo ships
only one tiny committed image, so the fixture is generated (stdlib only) under a
throwaway dir — four renderable, visually-distinct solid-colour PNGs plus one minimal
magic-byte JPEG container with no scan data — nothing is added to the repo. Point
`--images-dir` at your own folder of real generated images to skip step 0 (and to
exercise real JPEG photo content, which this synthetic fixture does not).

```bash
PILOT=$(mktemp -d /tmp/szh-genimg-pilot-XXXXXX)
mkdir "$PILOT/messy"

# 0 FIXTURE  five byte-distinct images with messy realistic generated-image names
#            (spaces / parens / uppercase ext / CJK / hyphen): four renderable,
#            visually-distinct solid-colour PNGs + one minimal magic-byte JPEG
#            container with NO scan data. Stdlib-only; writes only under $PILOT.
PILOT="$PILOT" python3 - <<'PY'
import os, struct, zlib
from pathlib import Path
messy = Path(os.environ["PILOT"]) / "messy"
def png_solid(p, w, h, rgb):
    def chunk(t, d):
        return (struct.pack(">I", len(d)) + t + d
                + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)         # 8-bit RGB
    raw  = (b"\x00" + bytes(rgb) * w) * h                       # filter 0 + rows
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                  + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
def jpeg(p, comment):                          # magic-byte-valid container, NO scan data (won't render)
    seg = comment[:200]
    p.write_bytes(b"\xff\xd8" b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
                  + b"\xff\xfe" + struct.pack(">H", len(seg) + 2) + seg + b"\xff\xd9")
png_solid(messy / "Hero Cover (v2).png",  8,  8, (200, 30, 30))
png_solid(messy / "Q3 Revenue Chart.png", 12, 6, (30, 160, 60))
png_solid(messy / "Diagram-FINAL.PNG",    6, 10, (40, 60, 200))   # uppercase ext
png_solid(messy / "产品路线图.png",         10, 10, (230, 140, 20))  # CJK-only stem
jpeg(messy / "photo_sample.jpeg", b"szh-pilot distinct sample photo")
PY

# 1 PREPARE    normalise messy names -> images/ + filename_mapping.json
python3 scripts/operator_images_to_review_package.py --prepare-images-only \
  --images-dir "$PILOT/messy" --out-dir "$PILOT/prepared"

# 2 TEMPLATES  editable starter manifest.json + generated_provenance.json
python3 scripts/operator_images_to_review_package.py --templates-only \
  --images-dir "$PILOT/prepared/images" --out-dir "$PILOT/templates"

# 3 EDIT       hand-edit "$PILOT/templates/manifest.json" slide_title / alt_text to
#              realistic safe titles (the default title is just the safe filename;
#              see Gap 1). No schema fields added/removed, filename set unchanged.

# 4 PLAN       stage bundle + reviewable approved_plan.json from the edited metadata,
#              then stop at the human-review checkpoint
python3 scripts/operator_images_to_review_package.py --plan \
  --images-dir "$PILOT/prepared/images" --out-dir "$PILOT/out" \
  --manifest "$PILOT/templates/manifest.json" \
  --generated-provenance "$PILOT/templates/generated_provenance.json"

# 5 RESUME     build review_package/ (deck.pptx + summary.json + ...)
python3 scripts/operator_images_to_review_package.py --resume --out-dir "$PILOT/out"

# 6 VALIDATE   read-only on-disk re-check of the produced package
python3 scripts/validate_operator_review_package.py \
  --out-dir "$PILOT/out/review_package"

# 7 PPTX contract gate (expected slide count == image count)
python3 scripts/validate_pptx_contract.py \
  --pptx "$PILOT/out/review_package/deck.pptx" --expected-slide-count 5

# 8 PPTX inventory (1:1 media readback)
python3 scripts/inspect_pptx_inventory.py \
  --pptx "$PILOT/out/review_package/deck.pptx"
```

## Where Each Named Artifact Landed

All under the throwaway `$PILOT` dir outside the repo (`/tmp/...`). The repo tree
stayed byte-identical (`git status` clean), and the source `messy/` folder was never
mutated.

| Artifact | Path | Step |
| --- | --- | --- |
| `filename_mapping.json` | `$PILOT/prepared/filename_mapping.json` | 1 prepare |
| `manifest.json` / `generated_provenance.json` | `$PILOT/templates/` | 2 templates |
| `approved_plan.json` | `$PILOT/out/approved_plan.json` | 4 plan |
| `summary.json`, `deck.pptx`, `inventory.json`, `visual_quality.json` | `$PILOT/out/review_package/` | 5 resume |

Observed normalisation (step 1): `Hero Cover (v2).png -> hero_cover_v2_.png`,
`Q3 Revenue Chart.png -> q3_revenue_chart.png`, `Diagram-FINAL.PNG -> diagram_final.png`
(uppercase `.PNG` lowercased), `产品路线图.png -> img.png` (CJK-only stem).

## Validation Results

| Check | Result |
| --- | --- |
| 1 `--prepare-images-only` | rc 0 — 5 distinct images normalised; `filename_mapping.json` + README written; nothing heavier built |
| 2 `--templates-only` | rc 0 — `manifest.json` + `generated_provenance.json` templates written against the prepared 5-image snapshot |
| 4 `--plan` | rc 0 — bundle staged, edited titles flow into `approved_plan.json`, stopped at the review checkpoint (no deck) |
| 5 `--resume` | rc 0 — `review_package/` built; `summary.approved_plan.matched=true`; in-run `validate_operator_review_package` rc 0 |
| 6 `validate_operator_review_package.py` | rc 0 — package re-validates on disk |
| 7 `validate_pptx_contract.py --expected-slide-count 5` | rc 0 — all gates PASS: `slide_count.expected` 5/5, `relationships.allow_list`, `media.targets_internal`/`inventory`/`embedded_only`, `package.no_macros`/`no_ole`/`no_activex`, all four `minimal_evidence` |
| 8 `inspect_pptx_inventory.py` | rc 0 — 5 slides, 5 embedded parts (`image{1,2,3,5}.png` + `image4.jpeg`), each `referencing_slides=[N]` **1:1**, **no findings** |

`summary.json`: `slide_count=5`, `embedded_media_count=5`, `minimal_evidence` all
true, `generated_provenance` present. Each `image_provenance[]` row carries exactly
one `embedded_media_parts` and one `embedded_referencing_slides` with
`placement_verified=true`. Every `ppt/media` part sha256 round-trips its source
image byte-for-byte; the lone JPEG embeds as an internal `image/jpeg` part (see the
JPEG caveat below). The edited titles reach the deck's editable text frames (`<a:t>`
per slide = `Solution Architecture`, `Quarterly Business Review`, `Product Roadmap`,
`Team Highlight`, `Q3 Revenue Performance`). `deck.pptx` is a real ~11 KB OOXML
package.

**JPEG caveat (no overclaim).** The `photo_sample.jpeg` fixture is a minimal
magic-byte-valid container (SOI + APP0/JFIF + COM + EOI) with **no scan data**, so
this run evidences only that a `.jpeg` routes through the extension gate, embeds as an
internal `image/jpeg` part, and round-trips its 57 source bytes exactly — it would
**not** render as a visible image in PowerPoint and does **not** prove real JPEG photo
rendering, which stays unverified here. The four PNGs are genuine 8-bit RGB rasters
that do render. Point `--images-dir` at real generated images to exercise visible JPEG
content.

## Is The Deck Usable?

**Yes as an editable starting scaffold; not as a finished deck.** Each image becomes
one native, editable PowerPoint slide — image embedded byte-for-byte as a `<p:pic>`,
plus an editable title text frame, one shape, and one connector — and every gate is
green. A reviewer can open it in PowerPoint and edit every object. (The four PNG
slides show genuine solid-colour rasters; the JPEG slide embeds the contentless
container noted above, so it would not render as a visible image — a fixture artifact,
not a tooling defect.) But it is a uniform one-image-per-slide scaffold: a single
layout for all slides, the title as
the only text, and the image `intended_use` / `alt_text` not reflected in the slide
body. A presenter would still restructure it into a narrative. That matches the
lane's current "review package" purpose.

## Top 3 Actionable Gaps

1. **Default `slide_title` is the *normalised safe* filename, and normalisation
   discards meaning.** The templates step runs on the *prepared* folder, so titles
   default to the safe stem (`"Operator image: hero_cover_v2_.png"`, and for the
   CJK-only `产品路线图.png` just `"Operator image: img.png"`). The semantic original
   lives only in `filename_mapping.json` (`original_filename`), which the separate
   `--templates-only` invocation never reads — so meaningful titles require manual
   hand-editing plus cross-referencing the mapping. **Fix:** seed `slide_title` from
   a de-messied *original* stem (e.g. have `--prepare-images-only` also emit a
   starter manifest seeded from `original_filename`, or let `--templates-only` accept
   the `filename_mapping.json`).

2. **One uniform layout for every slide; `intended_use` / `alt_text` don't shape the
   slide.** A "cover" image and a "chart" image render identically (same layout,
   title + image + one shape + one line), and `alt_text` never becomes a caption.
   Slides are ordered by normalised filename, so the cover image
   (`hero_cover_v2_`) landed at **slide 2**, not slide 1. **Fix:** map a few
   `intended_use` values to differentiated layouts (e.g. a cover layout for the cover
   image) and/or render `alt_text` as a caption text frame — this is what lifts the
   output from scaffold to draft.

3. **Absolute caller paths appear in operator-facing JSON evidence, not just the
   README.** `summary.json` carries three absolute `"path"` fields
   (`approved_plan.json`, `bundle/generated_provenance.json`,
   `visual_quality.json`), and `approved_plan.json` records absolute
   `manifest_path` / provenance `path`. The out-dir is caller-owned and outside the
   repo, so the validator accepts it, but an operator who shares the review package
   leaks their local directory layout. **Fix:** record paths relative to the out-dir
   (or basename only) in the operator-facing `summary.json` / `approved_plan.json`.

(Already recorded elsewhere, not re-counted above: the byte-identical fan-out is now
*resolved/confirmed* by this distinct-image run; `review_package/_pipeline_fixture/`
remains an undocumented-but-harmless internal dir; the README still quotes an
absolute interpreter path.)

## Boundary

Local-only. The trial called no D-One, MCP, Qoder, public network, telemetry, model
API, or image search, and added no such behavior. Real D-One image generation
remains UNVERIFIED and out of scope for this lane; real JPEG photo rendering is
likewise unverified here (the fixture's JPEG carried no scan data). Nothing was
written under the repo tree; clean up the trial with `rm -rf "$PILOT"`.
