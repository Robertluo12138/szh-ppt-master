# PPTX Conversion Trace Contract (Clean-Room)

This document defines the SHAPE contract for the per-primitive PPTX
**conversion trace report** in szh-ppt-master. It is **clean-room** — no
file, schema, prompt, validator, example, or wording from
`hugohe3/ppt-master`, a local `ppt-master` checkout, or any other
external project was copied, paraphrased, or summarised while
preparing it.

## 1. Status

- **The contract recognises exactly two writers today.** The
  `pipeline_status` field is a closed two-literal enum:
  - `future_contract_only` — the SHAPE-only baseline; the committed
    example fixture (`examples/synthetic_conversion_trace.json`) and
    any hand-authored shape probe carry this literal. No runtime
    script writes a trace under this literal.
  - `runtime_emitted_by_export_pptx` — the paired-contract runtime
    path. `scripts/export_pptx.py` writes a trace under this literal
    when the caller passes `--trace-out <path>`. The exporter's PPTX
    bytes are unchanged whether or not `--trace-out` is set; the
    sidecar is opt-in and atomic-written (tmp + rename) so a
    validation or write failure leaves no partial trace.
- Adding a third writer (or extending the enum at all) requires
  another paired contract change in the schema, in
  `scripts/validate_conversion_trace.py` (T3), and in this document.
  A silent reuse of an existing literal by a new writer is precisely
  what T3 refuses.
- **This is not upstream parity.** The general idea that a PPT-export
  pipeline could one day persist a per-primitive trace for debugging
  is the only thing reflected here; the specific field names, value
  enums, validator gates, and example fixture were re-derived from
  `schemas/render_model.schema.json`, `scripts/export_pptx.py`'s
  supported layout/primitive surface, `scripts/validate_pptx_contract.py`'s
  relationship allow-list, and the content-gate vocabulary already
  shared across `scripts/validate_brand_preset.py` and
  `scripts/validate_source_image_assets.py` — not from any upstream file.
- **No new public-network behavior.** This contract does not call
  D-One, MCP, image search, telemetry, model APIs, the Qoder runtime,
  or any external service. It does not generate images. It does not
  read raw source body text. The runtime writer in
  `scripts/export_pptx.py` derives the trace entirely from local
  in-memory render-model / media-plan state and never opens the
  source body. See `references/security-policy.md` and `SECURITY.md`.

## 2. What the contract covers

A trace is a single JSON object describing one attempted run of the
PPTX exporter over a render-model deck. Every record describes one
primitive's attempted conversion.

| Field                                | Shape                                                                          | Notes                                                                                                                    |
| ------------------------------------ | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `schema_version`                     | string enum `["1"]`                                                            | Bump only with a paired contract change.                                                                                 |
| `trace_id`                           | string `^synthetic_[a-z0-9][a-z0-9_]*$`                                        | Forced `synthetic_` prefix; refuses any real-document id at the schema layer.                                            |
| `pipeline_status`                    | string enum `["future_contract_only", "runtime_emitted_by_export_pptx"]`        | Closed two-literal enum. `future_contract_only` marks the SHAPE-only baseline; `runtime_emitted_by_export_pptx` is the paired runtime path. |
| `generated_by.name`                  | string `^synthetic_[a-z0-9][a-z0-9_]*$`                                        | Identifier of the synthetic writer.                                                                                      |
| `generated_by.mode`                  | string enum `["simulated", "self_test_fixture"]`                               | Closed enum.                                                                                                             |
| `deck.deck_id`                       | string `^synthetic_[a-z0-9][a-z0-9_]*$`                                        | Forced `synthetic_` prefix.                                                                                              |
| `deck.slide_count`                   | integer `>= 1`                                                                 | Validator cross-checks `>= max(record.slide_index)`.                                                                     |
| `deck.layouts_attempted`             | array of unique strings from the exporter's supported layout enum              | Allowlist mirrors `scripts/export_pptx.py`'s ten supported layouts.                                                       |
| `records[].slide_index`              | integer `>= 1`                                                                 | Ties to `render_models/<idx:02d>_<layout>.json`.                                                                          |
| `records[].slide_layout`             | string `^[a-z][a-z0-9_]*$`                                                     | Must appear in `deck.layouts_attempted` (validator).                                                                      |
| `records[].primitive_id`             | string `^[a-z][a-z0-9_]*$`                                                     | Ties to `render_model.primitives[].id`. Unique per (`slide_index`, `primitive_id`).                                       |
| `records[].primitive_kind`           | string from the render-model primitive enum                                    | Mirrors `schemas/render_model.schema.json`.                                                                              |
| `records[].expected_pptx_kind`       | string from a closed PPTX-surface enum                                         | `native_text_shape` / `native_shape` / `native_line` / `native_image_placeholder` / `native_kpi_group` / `native_table_graphic_frame` / `raster_fallback` / `none`. |
| `records[].status`                   | string enum `["editable", "rejected", "degraded", "skipped"]`                  | Closed.                                                                                                                  |
| `records[].reason_code`              | `null` OR a string from a closed reason-code enum                              | Validator T5 enforces null iff `status == editable`; non-null + closed enum otherwise.                                   |
| `records[].evidence`                 | closed object of booleans / small integer counts / nullable relationship type  | All evidence fields are obtainable by reading OOXML XML; no PowerPoint open required.                                    |
| `records[].note`                     | optional string `maxLength 280`                                                | Validator scans all the same content-gate denylists as the rest of the trace.                                            |
| `summary.{editable,rejected,degraded,skipped}_count` | integer `>= 0`                                                | Must equal per-status totals computed from `records` (validator T7).                                                     |
| `notes`                              | optional string `maxLength 280`                                                | Trace-level note. Same content gates apply.                                                                              |

`schemas/conversion_trace.schema.json` is the source of truth for the
exact patterns, enums, and required-vs-optional flags.
`additionalProperties: false` is set at every object boundary, so
unknown fields fail closed at schema validation.

The closed `reason_code` enum today is: `primitive_kind_unsupported`,
`layout_unsupported`, `bounds_out_of_canvas`, `image_ref_undeclared`,
`table_row_width_mismatch`, `style_ref_unresolved`,
`chart_renderer_todo`, `media_embedding_todo`, `font_overflow_todo`,
`other_synthetic_probe`. Extending it requires a paired schema bump and
matching validator support.

The closed `relationship_type` enum mirrors
`scripts/validate_pptx_contract.py`'s `relationships.allow_list`:
`officeDocument` / `slide` / `slideMaster` / `slideLayout` / `theme` /
`image`. `null` is used when the primitive did not trigger any package
relationship.

## 3. Fail-closed rules

The schema patterns and enums refuse most authoring slips at the
schema layer; the read-only validator re-applies the same gates and
adds a small set of cross-checks that go beyond what JSON Schema can
express:

| Gate | Refuses                                                                                                                                              |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1   | Symlink at the trace path, non-object root, non-JSON / non-UTF-8 bytes, missing file. Exits 2 (invocation / file / parse error).                      |
| T2   | Schema-subset violation (re-uses `scripts/validate_artifacts._validate`). Unknown `status` or unknown `reason_code` values fail here via schema enums. |
| T3   | `pipeline_status` not in the closed two-literal set `{"future_contract_only", "runtime_emitted_by_export_pptx"}`.                                     |
| T4   | `trace_id` / `deck.deck_id` / `generated_by.name` missing the required `synthetic_` prefix shape.                                                     |
| T5   | `status == editable` carrying a non-null `reason_code`, OR `status in {rejected, degraded, skipped}` carrying a null / non-enum `reason_code`.        |
| T6   | Duplicate `(slide_index, primitive_id)` tuple across `records`.                                                                                       |
| T7   | `summary` totals that disagree with the per-status counts computed from `records`.                                                                    |
| T8   | A `record.slide_index` greater than `deck.slide_count` (envelope violation).                                                                          |
| T9   | A `record.slide_layout` that is not declared in `deck.layouts_attempted`.                                                                             |
| T10  | URI-scheme prefix (`http:`, `https:`, `file:`, `data:`, `s3:`, `ftp:`, `mailto:`, `javascript:`) AND embedded URLs anywhere in any string.            |
| T11  | Absolute paths (`/...`), leading backslash, protocol-relative (`//host`), and `..` path segments.                                                     |
| T12  | `public` combined with a propagation verb (`upload`, `share`, `sharing`, `url`, `link`, `post`, `publish`, `distribut...`, `host...`).                |
| T13  | Credential-shape compound tokens (`apikey`, `apitoken`, `accesstoken`, `authtoken`, `csrftoken`, `idtoken`, `jwttoken`, `oauthtoken`, `refreshtoken`, `sessiontoken`, `secret`, `bearer`, `password`, bare `token`) AND `sk-...`-prefixed API-key shapes. |
| T14  | Confidential markers (`confidential`, `proprietary`, `internalonly`, `ndaprotected`, `customername`, `accountid`, `ssn`, `creditcard`) AND `raw` + `source` / `content` / `paragraph` / `excerpt`. |

Exit codes:
- `0` — all gates passed.
- `1` — one or more T2..T14 gate findings.
- `2` — invocation / file / parse error (T1 plus CLI shape errors).

## 4. Out of scope (explicitly refused)

- Any writer other than the two literals listed in Section 1. A new
  writer is not allowed without another paired contract change in the
  schema, in `scripts/validate_conversion_trace.py` (T3), and in this
  document.
- Reading a trace as runtime state in any script (no consumer exists
  today; the trace is a write-only diagnostic sidecar from
  `scripts/export_pptx.py`).
- Calling D-One / Qoder / MCP / any image generator / model API /
  image search / public network / external service. The runtime
  writer in `scripts/export_pptx.py` derives the trace from local
  in-memory state only.
- Generating any PPTX / package / pipeline-report artifact beyond
  the trace itself. The trace is OPT-IN: omitting `--trace-out`
  leaves the PPTX bytes and the exporter's CLI text byte-identical
  to a no-trace run.
- Mutating the trace or any pipeline artifact (the validator is
  read-only; the runtime writer atomic-writes via a `.tmp` sibling
  and cleans up on any failure).
- Changing the default export contract. Without `--trace-out`, no
  sidecar file is written and the existing PPTX export behavior is
  unchanged.

Adding a new writer (or extending the `pipeline_status` enum at all)
MUST be a paired change across the schema, the validator's T3 gate,
and this document. A silent reuse of an existing literal by an
unauthorised new writer is precisely what T3 refuses.

## 5. Example fixture and runtime path

`examples/synthetic_conversion_trace.json` carries one synthetic
fixture under the SHAPE-only `pipeline_status =
"future_contract_only"` literal, covering all four `status` values
across the supported primitive surface:

- `editable` — `text`, `line`, `kpi`, and `table` primitives across
  the `cover`, `kpi_dashboard`, and `comparison_table` layouts.
- `skipped` — an `image_slot` primitive on the `cover` layout, with
  `reason_code = media_embedding_todo` (mirrors the exporter's
  placeholder fallback for non-embeddable image extensions).
- `rejected` — a `chart_placeholder` primitive on the `kpi_dashboard`
  layout, with `reason_code = chart_renderer_todo` (mirrors the
  exporter's fail-closed gate; a runtime trace will never carry this
  shape because the exporter aborts before reaching the trace step
  when a `chart_placeholder` is present).
- `degraded` — a `text` primitive that overflows its bounds, with
  `reason_code = font_overflow_todo` and
  `expected_pptx_kind = raster_fallback` (synthetic probe; no such
  fallback exists in the exporter today).

The fixture validates cleanly under `scripts/validate_conversion_trace.py`.

The runtime writer in `scripts/export_pptx.py` (invoked as
`--trace-out <path>`) emits a trace under
`pipeline_status = "runtime_emitted_by_export_pptx"`. Because the
trace step only runs after a successful PPTX export, every runtime
record carries `status = "editable"` (with `reason_code = null`) for
the supported primitive kinds (`text`, `line`, `shape`, `kpi`,
`table`, and embedded `image_slot` with
`relationship_type = "image"`), and `status = "skipped"` with
`reason_code = "media_embedding_todo"` for `image_slot` primitives
that fell back to the placeholder shape. Synthetic ids are hard-coded
(`trace_id = "synthetic_export_pptx_trace"`,
`deck.deck_id = "synthetic_export_pptx_deck"`,
`generated_by.name = "synthetic_export_pptx"`,
`generated_by.mode = "simulated"`) so a runtime trace can never carry
a real deck title or source identifier.

## 6. Validator usage

```bash
# Validate a single trace file.
python3 scripts/validate_conversion_trace.py \
    --trace examples/synthetic_conversion_trace.json

# Run the built-in self-test (positives + every gate's negative probe).
python3 scripts/validate_conversion_trace.py --self-test
```

The validator is stdlib-only, read-only, and does not read or modify
any other artifact in the workspace beyond the trace file passed to
`--trace`. It does NOT call any other script in this repo, NOR any
external service.
