# MVP Quickstart: local source → images → editable PPT

The shortest path a new operator can run on a company machine to turn a
local source document into an **editable** PowerPoint deck. One wrapper,
`scripts/run_mvp_image_to_ppt.py`, run twice, with an image-generation
step in between. No prior chat history or repo knowledge required.

**This is the MVP, honestly scoped — read this first:**

- Images are **manual / local / mock** only. The wrapper synthesises **no
  pixels** and calls **no** image generator. A human or an internal tool
  produces the requested images; you drop them into a named folder.
- It is **not** real D-One, **not** a model API, **not** public web
  ingestion, **not** full report understanding, and **not** full
  `ppt-master` parity. Only ATX **headings** drive the plan (one image
  request per heading); body prose is never extracted into the deck.
- Local-only: no D-One, MCP, Qoder, public network, telemetry, model API,
  or image search.

## Prerequisites

- `python3` (standard library only — no `pip install`).
- A local source file: `.md` / `.markdown` (used directly) or `.docx` /
  `.txt` (normalised to Markdown first). `.pdf` is a documented TODO.
- A working directory **outside this repo** for outputs (e.g. under
  `/tmp`). The wrapper refuses an output dir that is URI-shaped, a
  symlink, inside the repo tree, or already non-empty; its parent must
  exist.

A bundled synthetic demo source ships at `examples/mvp_demo_source.md`
(five ATX headings, no real data) so you can run the whole flow before
pointing it at your own document.

## Step 1 — first run: source → generation packet

```bash
# Use a FRESH dir outside the repo. Re-running needs an empty dir, so
# remove a stale one first: rm -rf /tmp/szh-mvp-demo
python3 scripts/run_mvp_image_to_ppt.py \
  --source examples/mvp_demo_source.md \
  --out-dir /tmp/szh-mvp-demo
```

This writes the **generation packet** under:

```
/tmp/szh-mvp-demo/generation_packet/
  image_request_plan.json          # one image request per heading
  image_generation_requests.md     # human-readable: hand THIS to the generator
  manifest.json                    # starter operator-bundle sidecars
  generated_provenance.json
  expected_images/
    README.md                      # names every required return filename
```

Hand `generation_packet/image_generation_requests.md` to your local /
internal image generator. Save each returned image under its **exact**
requested filename (e.g. `img_01.png`, `img_02.png`, …) into:

```
/tmp/szh-mvp-demo/generation_packet/expected_images/
```

The first run prints these next steps, including the exact `--resume`
command, when it finishes.

## Step 2 — resume run: packet + returned images → editable deck

```bash
python3 scripts/run_mvp_image_to_ppt.py --resume /tmp/szh-mvp-demo
```

The resume run checks the returned images against the plan **1:1** (exact
filenames, valid PNG/JPG/JPEG bytes, no symlinks / extras / missing —
failing closed with an actionable message otherwise), builds the editable
deck, and re-validates the result read-only. The final deck lands at:

```
/tmp/szh-mvp-demo/review/review_package/deck.pptx
```

alongside `summary.json`, `inventory.json`, `visual_quality.json`,
`workspace/`, and `reports/`. Re-check a produced package on disk at any
time with `python3 scripts/validate_operator_review_package.py --out-dir
/tmp/szh-mvp-demo/review/review_package`.

## Optional — fully-local smoke with no image generator

To see the whole flow produce a deck on one machine with no external
generator, write a placeholder PNG for each requested filename between
Step 1 and Step 2. This stdlib-only snippet reads the required filenames
from the plan and writes a tiny, byte-distinct, valid PNG for each (it
embeds **no** source text — placeholder pixels only):

```bash
python3 - /tmp/szh-mvp-demo <<'PY'
import json, struct, sys, zlib
from pathlib import Path

out = Path(sys.argv[1])
packet = out / "generation_packet"
plan = json.loads((packet / "image_request_plan.json").read_text("utf-8"))
expected = packet / "expected_images"

def png(w, h, rgb):                      # minimal valid 8-bit RGB PNG (stdlib only)
    def chunk(typ, data):
        body = typ + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))
    raw = bytearray()
    row = bytes(rgb) * w
    for _ in range(h):
        raw.append(0)                    # filter byte 0 (None) per scanline
        raw += row
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))

for i, req in enumerate(plan["image_requests"], 1):
    rgb = ((i * 37) % 256, (i * 53) % 256, (i * 71) % 256)   # byte-distinct
    (expected / req["filename"]).write_bytes(png(8, 8, rgb))
print(f"wrote {len(plan['image_requests'])} placeholder PNG(s) into {expected}")
PY
```

Then run Step 2. The deck appears at
`/tmp/szh-mvp-demo/review/review_package/deck.pptx`. These placeholders
are flat solid-colour squares — useful only to prove the pipeline; swap
in real returned images for a real deck.

## Behind the wrapper

`run_mvp_image_to_ppt.py` is a thin orchestrator. It adds no renderer and
no second validator and synthesises no pixels — it sequences the existing
helpers and reuses their safety gates verbatim:

- `.docx` / `.txt` sources are normalised to `<out-dir>/normalized_source.md`
  via `scripts/ingest_local_source_file.py --md-out`.
- the Markdown source feeds `scripts/source_to_image_requests.py
  --generation-packet` (Step 1) and `--resume-packet` (Step 2).

For the lower-level commands and the full flag surface, see
[`source-to-image-request-bridge.md`](source-to-image-request-bridge.md)
and [`core-image-to-editable-ppt-quickstart.md`](core-image-to-editable-ppt-quickstart.md).
The MVP scope and goal sequence live in
[`mvp-ddl-sprint-plan.md`](mvp-ddl-sprint-plan.md).

Self-test the wrapper any time: `python3 scripts/run_mvp_image_to_ppt.py
--self-test`.
