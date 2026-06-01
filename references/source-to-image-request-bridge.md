# Source-to-Image-Request Bridge

A narrow, local-only **bridge** that moves the project one step earlier
than the operator image lane: from "an operator already has images" to
"a Markdown source document can produce an image request plan, which can
then feed the existing local image-to-editable-PPT lane."

It is implemented by `scripts/source_to_image_requests.py`. It is a
**bridge, not full report-to-PPT automation**: it derives one image
request per Markdown heading, never extracts business content from the
source body, and never performs real image generation.

## What it produces

- An **image request plan** (`image_request_plan.json`) validated against
  `schemas/image_request_plan.schema.json`: one entry per ATX heading,
  each with synthetic-safe per-slide metadata (`slide_title`,
  `alt_text`, `image_descriptor`, `placement_role`, `intended_use`) and
  structural traceability back to the heading (level + ordinal). Raw
  source body text is never copied into the plan.
- In `--mock-handoff` mode, a plan-derived operator **bundle**
  (`bundle/images/` byte-distinct placeholder PNGs + `bundle/manifest.json`
  + `bundle/generated_provenance.json`), fed into the existing operator
  lane (`scripts/operator_local_images_to_editable_ppt.py --bundle`) to
  produce a validated review package with an editable `deck.pptx` whose
  slide titles, alt text, and role-aware layouts reflect the image request
  plan, plus per-image provenance, re-checked by
  `scripts/validate_operator_review_package.py`.
  - The manifest carries each request's `slide_title` / `alt_text` /
    `intended_use`; the sidecar carries `generator_source` /
    `placement_role` / `text_policy` / `subject_domain` / `intent_summary`,
    reusing the operator manifest + generated_provenance contracts
    verbatim. `placement_role` drives the operator's role-aware layout
    (`hero_page` → `cover`, `local_region` → `section_divider`), and the
    produced `summary.json` `image_provenance` carries the full trace per
    image: source heading → `image_request_plan.json` request → placeholder
    filename → `placement_role` → `chosen_layout` → embedded
    `ppt/media/*` part, plus `operator_slide_title` / `operator_alt_text`.
- In `--generation-packet` mode, a source-free **operator handoff packet**
  written under a fresh `--out-dir` outside the repo. It stops one step
  BEFORE `--mock-handoff`: it synthesises NO pixels and runs NO operator
  lane, exporting only what a human / internal image generator needs:
  - `image_request_plan.json` — the same schema-validated plan;
  - `image_generation_requests.md` — a human-readable brief, one block per
    request, preserving `filename` / `slide_title` / `alt_text` /
    `intended_use` / `image_descriptor` / `placement_role` (no raw source
    body text);
  - starter `manifest.json` + `generated_provenance.json` — the SAME
    plan-derived operator-bundle sidecars `--mock-handoff` builds, so they
    feed the operator `--bundle` lane verbatim;
  - `expected_images/README.md` — names every required filename and gives
    the exact finishing commands (drop the returned images into a bundle's
    `images/`, copy the two sidecars, run
    `operator_local_images_to_editable_ppt.py --bundle`).
  Because the packet is written BEFORE the images exist, the starter
  `generated_provenance.json` declares `text_policy: "no_text"` as the
  REQUESTED (text-free) intent, not a verified fact — unlike `--mock-handoff`,
  where the tool makes the blank pixels itself so `no_text` is true. Both
  packet docs therefore require a text-free image AND tell the operator to
  correct each entry's `text_policy` (to `decorative_glyphs` / `caption_safe`)
  if a returned image contains text, so an unverified `no_text` claim cannot
  silently ride into the deck. A `.docx` / `.txt` source reaches this mode
  via `ingest_local_source_file.py --md-out` first.
- In `--resume-packet` mode, the source-free **finish** for a completed
  generation packet. Given the packet directory (`--packet-dir`) and a
  folder of returned local images (`--images-dir`), it builds a validated
  `<out-dir>/review_package` via the existing operator `--bundle` lane:
  - it confirms the packet carries `image_request_plan.json` +
    `manifest.json` + `generated_provenance.json`, derives the expected
    filename set from the schema-validated plan, and checks the returned
    images match it **EXACTLY** — one regular file per request, valid PNG
    magic bytes (every requested filename ends in `.png`), no symlinks, no
    missing, no extras (the
    packet's own `expected_images/README.md` sidecar is tolerated and
    skipped). Every missing / extra / mismatch / non-image / unsafe-path
    case fails closed with an actionable message **before** any bundle is
    assembled or any output directory is created;
  - it then assembles a **temporary** operator bundle under `TMPDIR`
    (the returned images plus the packet's `manifest.json` /
    `generated_provenance.json`, verbatim — auto-cleaned, never under the
    repo) and runs `operator_local_images_to_editable_ppt.py --bundle`,
    whose own MAN/GP content gates validate the sidecars, then re-checks
    the result read-only with `validate_operator_review_package.py`.
  It synthesises NO pixels and adds NO renderer; it is the documented
  packet-finish commands wrapped behind one guarded entry point.

## Commands

```bash
# Plan only: Markdown -> image_request_plan.json
python3 scripts/source_to_image_requests.py \
  --source examples/source_to_image_requests/sample_report.md \
  --plan-out /tmp/image_request_plan.json

# Validate a produced plan against the schema
python3 scripts/validate_artifacts.py \
  --schema schemas/image_request_plan.schema.json \
  examples/source_to_image_requests/image_request_plan.json

# Mock/local handoff: plan + placeholder images -> review package
python3 scripts/source_to_image_requests.py \
  --source examples/source_to_image_requests/sample_report.md \
  --mock-handoff --out-dir /tmp/s2ir_out      # fresh dir, outside the repo

# Generation packet: source-free operator handoff for an image generator
python3 scripts/source_to_image_requests.py \
  --source examples/source_to_image_requests/sample_report.md \
  --generation-packet --out-dir /tmp/s2ir_packet   # fresh dir, outside the repo

# Resume: completed packet + returned local images -> validated review package
python3 scripts/source_to_image_requests.py --resume-packet \
  --packet-dir /tmp/s2ir_packet \
  --images-dir /tmp/s2ir_packet/expected_images \
  --out-dir /tmp/s2ir_review            # fresh dir, outside the repo

# Self-test (every scenario under TMPDIR)
python3 scripts/source_to_image_requests.py --self-test
```

## Synthetic-safety and boundary

- The whole source is scanned (case-insensitive) for credential,
  public-network, file-URI, and absolute-path wording, **and** for
  credential value shapes (AWS-style keys, PEM private-key blocks, bearer
  and key/value secrets — reusing the shared
  `verify_skill_package.CREDENTIAL_PATTERNS` detector), before any
  artifact is produced; any hit fails the run closed with the offending
  token and 1-based line number.
- The values that flow downstream (the source filename and each heading
  title) are re-scanned **after** sanitisation. That emitted-value gate
  is the **union** of this bridge's deny-list, the credential-shape
  detector, **and the operator lane's own `_safe_manifest_string`
  contract**, so the bridge's safety gate is provably **no weaker than
  the operator review-package contract** — it inherits the operator's
  OpenAI-key, upload/share/public-hosting wording, social-media channel,
  22-shape public-share regex, confidential/customer marker, and
  positive-real-service-claim gates. Path separators are normalised to a
  space during sanitisation so a benign heading like `TCP/IP overview`
  is not falsely refused while no `/` or `\` ever reaches the deck text.
- The gate is applied **per emitted deck string** — `deck.title` and each
  request's `slide_title` / `alt_text` / `image_descriptor` /
  `intended_use` (the composed outputs, not just the heading input) — at
  the operator contract's **own per-field length limits** (`slide_title`
  120, `alt_text` 300, `intended_use` 120; `image_descriptor` inherits the
  alt_text limit), so a value the operator would refuse on length cannot
  pass the bridge. Titles are truncated to the operator `slide_title` cap
  during sanitisation, and the plan schema's `maxLength`s match these
  limits.
- Placeholder PNGs are tiny locally-synthesised raster bytes. No real
  image generator runs.
- `--mock-handoff` hands the operator lane a **plan-derived bundle**, not
  an images-only folder: `bundle/manifest.json` carries each request's
  `slide_title` / `alt_text` / `intended_use`, and
  `bundle/generated_provenance.json` carries `generator_source` /
  `placement_role` / `text_policy` / `subject_domain` / `intent_summary`.
  `placement_role` drives the operator's role-aware layout (`hero_page` →
  `cover`, `local_region` → `section_divider`). Join the plan (filename ↔
  heading) with the review package's `summary.json` `image_provenance`
  (`operator_slide_title` / `operator_alt_text`, `placement_role`,
  `chosen_layout`, `embedded_media_parts`) for end-to-end provenance.

Local-only: no D-One, MCP, Qoder, public network, telemetry, model API,
or image search. Real image generation remains UNVERIFIED / out of scope
for this bridge.
