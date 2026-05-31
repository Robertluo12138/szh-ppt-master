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
- In `--mock-handoff` mode, a byte-distinct locally-synthesised
  **placeholder PNG** per request, fed into the existing operator lane
  (`scripts/operator_local_images_to_editable_ppt.py`) to produce a
  validated review package with an editable `deck.pptx` and per-image
  provenance, re-checked by
  `scripts/validate_operator_review_package.py`.

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
- The image folder handed to the operator lane is **images-only** (no
  manifest), so the operator lane synthesises slide titles; the rich
  per-image metadata + heading traceability live in the plan. Join the
  plan (filename ↔ heading) with the review package's `summary.json`
  (filename ↔ embedded media part + slide) for end-to-end provenance.

Local-only: no D-One, MCP, Qoder, public network, telemetry, model API,
or image search. Real image generation remains UNVERIFIED / out of scope
for this bridge.
