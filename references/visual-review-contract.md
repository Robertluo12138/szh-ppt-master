# Per-Slide Visual Review Rubric Contract (Clean-Room)

This document defines the SHAPE contract for a **per-slide visual
review rubric report** in szh-ppt-master. It is **clean-room** — no
file, schema, prompt, rubric, validator, example, or wording from
`hugohe3/ppt-master`, a local `ppt-master` checkout, or any other
external project was opened, copied, paraphrased, or summarised while
preparing it. The only signal taken from upstream work is the
high-level radar idea that a per-slide rubric-based review is useful;
every field name, value enum, validator gate, and example fixture was
re-derived from this repo's existing schemas, validators, and content
gates.

## 1. Scope

A review is a single JSON object whose `evidence_basis` is pinned to
the single literal `local_artifact_metadata_only`. That literal is the
contract pin that says **this review is NOT a screenshot / browser /
model review**: every finding MUST be derivable from inspecting
committed local pipeline artifacts (`deck_plan.json`,
`slide_plans/*.json`, `render_models/*.json`,
`<workspace>/conversion_trace.json` when present) and MUST NOT depend
on any of the following:

- a screenshot of the slide;
- opening the slide in PowerPoint, Keynote, a browser, or any other
  viewer;
- a headless browser, Selenium, Playwright, Puppeteer, Chromium,
  WebDriver, or any browser-automation tool;
- a model API, LLM judgment, GPT inference, image-generation model
  (Midjourney, Stable Diffusion, DALL-E, Firefly, Imagen, etc.);
- D-One image generation;
- the Qoder runtime;
- an MCP call, server, or endpoint;
- any external service, public network, telemetry, or remote API.

The validator at `scripts/validate_visual_review.py` enforces both the
SHAPE (closed enums, ids, coverage, summary consistency) and the
content-gate denylists that refuse positive *and* negative wording
about any of the above — because either polarity implies the review
is in scope for an out-of-scope tool, and the contract refuses that
scope expansion regardless of polarity.

This contract is **NOT** an upstream parity target. The general idea
that a deck could one day be reviewed per-slide on a small closed
rubric is the only thing reflected here; the specific field names,
value enums, validator gates, and example fixture were re-derived
locally.

## 2. Status

- The contract recognises **exactly one writer today**: the SHAPE-only
  baseline. The committed example fixture
  (`examples/synthetic_visual_review.json`) and any hand-authored
  static-inspection note carry the synthetic identifiers required by
  the schema. There is no runtime script in this repo that emits a
  visual_review file today; the contract is shape-only.
- `evidence_basis` is a closed single-literal enum
  (`["local_artifact_metadata_only"]`). Adding a second basis (e.g. a
  paired-contract runtime path that derives findings from a different
  source) requires a paired contract change in
  `schemas/visual_review.schema.json`,
  `scripts/validate_visual_review.py` (V3), and in this document. A
  silent reuse of the existing literal by a writer with a different
  evidence basis is precisely what V3 refuses.
- **No new public-network behaviour.** This contract does not call
  D-One, Qoder, MCP, any image generator, any model API, any public
  network, any telemetry, or any external service. It does not
  capture screenshots, open a browser, or render a slide. See
  `references/security-policy.md`, `references/clean-room-policy.md`,
  and `SECURITY.md`.

## 3. What the contract covers

A review is a single JSON object describing one rubric pass over a
deck. Exactly one record per slide; the validator enforces both
uniqueness on `slide_index` AND full coverage of `1..deck.slide_count`.

| Field                                  | Shape                                                                              | Notes                                                                                                            |
| -------------------------------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `schema_version`                       | string enum `["1"]`                                                                | Bump only with a paired contract change.                                                                         |
| `review_id`                            | string `^synthetic_[a-z0-9][a-z0-9_]*$`                                            | Forced `synthetic_` prefix; refuses any real-document id at the schema layer.                                    |
| `evidence_basis`                       | string enum `["local_artifact_metadata_only"]`                                     | Closed single-literal enum. The contract pin for "no screenshot / browser / model / D-One / external service".   |
| `generated_by.name`                    | string `^synthetic_[a-z0-9][a-z0-9_]*$`                                            | Identifier of the synthetic writer.                                                                              |
| `generated_by.mode`                    | string enum `["self_test_fixture", "manual_static_inspection"]`                    | Closed enum.                                                                                                     |
| `deck.deck_id`                         | string `^synthetic_[a-z0-9][a-z0-9_]*$`                                            | Forced `synthetic_` prefix.                                                                                      |
| `deck.slide_count`                     | integer `1..200`                                                                   | Validator enforces full record coverage of `1..slide_count`.                                                     |
| `records[].slide_index`                | integer `>= 1`                                                                     | Unique across records; coverage gate refuses missing or extra slots.                                             |
| `records[].slide_layout`               | string `^[a-z][a-z0-9_]*$`                                                         | Generic id pattern; the contract does NOT pin a closed layout enum here so the rubric is layout-set-independent. |
| `records[].status`                     | string enum `["pass", "warn", "fail"]`                                             | Closed.                                                                                                          |
| `records[].issue_type`                 | string enum (see Section 4)                                                        | Closed.                                                                                                          |
| `records[].severity`                   | string enum `["info", "low", "medium", "high"]`                                    | Closed. The schema does NOT couple severity to status — only enum membership is enforced.                         |
| `records[].evidence_basis`             | string enum `["local_artifact_metadata_only"]`                                     | Per-record duplicate of the root pin so a future relaxation is caught from either side.                          |
| `records[].recommended_action`         | string enum (see Section 4)                                                        | Closed.                                                                                                          |
| `records[].note`                       | optional string `maxLength 280`                                                    | Validator scans all content-gate denylists.                                                                       |
| `summary.{pass,warn,fail}_count`       | integer `>= 0`                                                                     | Must equal per-status totals computed from `records` (validator V8).                                              |
| `notes`                                | optional string `maxLength 280`                                                    | Review-level note. Same content gates apply.                                                                      |

`schemas/visual_review.schema.json` is the source of truth for the
exact patterns, enums, and required-vs-optional flags.
`additionalProperties: false` is set at every object boundary, so
unknown fields fail closed at schema validation.

## 4. Closed rubric vocabularies

### `issue_type`

| Value                   | Local-artifact derivation                                                                                                                                  |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `text_density`          | Sum of text characters across `render_model.primitives[].kind=="text"` content vs. a per-layout density floor / ceiling.                                    |
| `overflow_risk`         | `render_model.primitives[].bounds` (`x + w`, `y + h`) vs. `render_model.canvas` width/height. Already gated in `validate_workspace.check_render_model_bounds`. |
| `contrast_risk`         | `design_system.palette` foreground/background pair vs. `render_model` primitive `style_ref` fill/stroke.                                                    |
| `image_only_risk`       | `render_model.primitives` kind distribution: every primitive is an `image_slot`. Mirrors `validate_visual_quality.image_only_slide`.                       |
| `editability_risk`      | `render_model.primitives[].kind` vs. exporter primitive-kind allow-list. Mirrors `conversion_trace.records[].status in {rejected, degraded}`.               |
| `layout_mismatch`       | `render_model.layout` vs. `deck_plan.slides[].layout` at the same `slide_index`.                                                                            |
| `media_risk`            | `image_manifest.json` declarations vs. `render_model.primitives[].kind=="image_slot"` refs (undeclared, missing, or unsafe path).                            |
| `trace_mismatch`        | Cross-read a present `conversion_trace.json` against the `render_model` (declared layout / primitive ids).                                                  |
| `other_synthetic_probe` | Catch-all for a one-off synthetic probe that does not fit the closed list. The contract does not widen the rubric every time a probe is needed.             |

### `recommended_action`

| Value             | Next step                                                                                                                |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `inspect_source`  | Re-read `input/source.md` to confirm a content question.                                                                 |
| `adjust_copy`     | Edit the slide_plan text spec to shorten / soften / re-word copy.                                                        |
| `adjust_layout`   | Edit the slide_plan / template layout to widen, reflow, or restructure the slot.                                         |
| `rerun_export`    | Re-run `scripts/export_pptx.py` (with `--trace-out` when comparing) after a fix.                                          |
| `inspect_trace`   | Cross-read the `conversion_trace.json` sidecar to understand a primitive's exporter decision.                            |
| `no_action`       | The slide passes the rubric for this issue_type; no follow-up needed.                                                    |

Every action is a local-only pipeline step. There is no
`request_screenshot`, `ask_model`, `open_in_browser`, or
`call_external_service` option — those are out of scope for this
contract.

## 5. Validator gates

`scripts/validate_visual_review.py` exposes one fail-closed gate per
contract claim. The exact gate text lives in the script's module
docstring; the table below names each gate and what it refuses.

| Gate | Refuses                                                                                                                                              |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| V1   | review path is a symlink, missing, not a regular file, unreadable, not UTF-8, not JSON, or not a top-level object. Exit 2.                            |
| V2   | schema-subset violation (closed enums, required fields, `additionalProperties: false`, id patterns).                                                  |
| V3   | root and per-record `evidence_basis` MUST equal the single literal `local_artifact_metadata_only`.                                                    |
| V4   | `review_id` / `deck.deck_id` / `generated_by.name` MUST each carry the `synthetic_` prefix.                                                           |
| V5   | runtime re-check of the `status` / `issue_type` / `severity` / `recommended_action` closed enums (defense-in-depth against a future schema relaxation). |
| V6   | records MUST cover EXACTLY `1..deck.slide_count` — no missing slide, no extra slide.                                                                  |
| V7   | duplicate `slide_index` across records.                                                                                                              |
| V8   | `summary.{pass,warn,fail}_count` MUST equal the per-status totals computed from `records`.                                                            |
| V9   | URL / URI scheme (`http:`, `https:`, `file:`, `data:`, `s3:`, `ftp:`, `mailto:`, `javascript:`) or embedded URL in any string field.                  |
| V10  | absolute path (`/etc/passwd`), backslash-prefixed path (`\\share\\…`), protocol-relative path (`//attacker/x`), or `..` traversal segment.            |
| V11  | canonical-form combo of `public` + propagation verb (`upload`, `share`, `sharing`, `url`, `link`, `post`, `publish`, `distribut`, `host`).            |
| V12  | credential-shape tokens (`api_key`, `access_token`, `bearer`, `secret`, `password`, bare `token`, etc.) OR the `sk-[A-Za-z0-9_\-]{16,}` regex shape. |
| V13  | confidential / raw-source markers (`confidential`, `proprietary`, `internal_only`, `nda_protected`, `customer_name`, `account_id`, `ssn`, `credit_card`; OR `raw` + (`source` / `content` / `paragraph` / `excerpt`)). |
| V14  | out-of-scope tool-claim wording: bare tokens (`screenshot`, `selenium`, `playwright`, `puppeteer`, `chromium`, `webdriver`, `qoder`, `telemetry`, `midjourney`, `stablediffusion`, `dalle`, `firefly`, `imagen`, `imagegen`, `imagegeneration`, `generateimage`, `texttoimage`, `promptimage`, `aiimage`, `aiimagery`, `aimodel`, `languagemodel`, `headlessbrowser`, `browserautomation`); canonical-form marker+qualifier pairs (lower-cased, non-alphanum-stripped substring check): `done`+(`image`/`asset`/`render`/`generated`/`imagegen`/`used`/`called`/`invok`/`queried`); `mcp`+(`call`/`server`/`invoc`/`request`/`endpoint`/`used`/`queried`); `model`+(`api`/`inferenc`/`judg`/`llm`/`gpt`/`queried`); `external`+(`service`/`api`/`endpoint`/`host`); `browser`+(`captur`/`open`/`snapshot`/`render`/`automat`/`used`/`invok`/`launched`); plus a separate hybrid check that pairs the bare-word regex `\bmodel\b` against the ORIGINAL string (so underscored compounds like `render_model` / `design_model` are excluded because `_` is a regex word character) with any of (`used`/`called`/`invok`/`prompted`) in the canonical form — that catches generic "model was used / called / invoked / prompted" tool-claims without false-positiving on legitimate `render_model` evidence wording. The `done` / `mcp` / `browser` qualifier lists deliberately span action AND usage verbs because those three markers never appear in legitimate static-metadata review prose; the `model` canonical-form list and the `external` list are kept narrow to AI-tool-specific or service-specific verbs because a substring check on the canonical form cannot tell `render_model used` from `model used` nor `external border used` from `external service used`. Refused in EITHER polarity — `"no screenshot was taken"` and `"no model was used"` are refused for the same reason `"screenshot captured"` and `"model was queried"` are. |

Exit codes: `0` (every gate passed or `--self-test` scenarios all
behaved as expected), `1` (one or more V2..V14 fired), `2`
(invocation / V1 precheck failure).

## 6. What this contract is NOT

- It is **not** an automatic visual review stage. There is no runtime
  script in this repo that emits a `visual_review.json` today; the
  contract is shape-only and the validator is read-only.
- It is **not** a screenshot review. The `evidence_basis` enum has
  exactly one literal today, `local_artifact_metadata_only`, and
  there is no second literal naming a screenshot or rendered-image
  source.
- It is **not** a model-judgment review. `evidence_basis` does not
  recognise any LLM-judgment basis, and V14 refuses tool-claim
  wording that would imply one.
- It is **not** a browser-rendered review. V14 refuses
  `browser`+`captur`/`open`/`snapshot`/`render`/`automat` wording in
  either polarity.
- It is **not** a D-One / Qoder / MCP / external-service review. The
  same V14 gate refuses claims that any of these were used.
- It is **not** upstream parity. The only signal taken from upstream
  work is the high-level idea that a per-slide rubric is useful.

## 7. Verification

```bash
# Schema validation (subset-based stdlib validator):
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_artifacts.py \
    --schema schemas/visual_review.schema.json \
    examples/synthetic_visual_review.json

# Validator self-test (positive sweeps + negative probes):
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_visual_review.py \
    --self-test

# Validator help:
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_visual_review.py \
    --help

# Validator against the committed example:
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_visual_review.py \
    --review examples/synthetic_visual_review.json
```
