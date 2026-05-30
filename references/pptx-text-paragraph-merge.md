# PPTX Text Paragraph Merge — Opt-In Contract (Clean-Room)

This document defines the **opt-in** text-paragraph-merge contract for
`scripts/export_pptx.py` in szh-ppt-master. It is **clean-room** — no
file, schema, flag, validator, example, or wording from
`hugohe3/ppt-master`, a local `ppt-master` checkout, or any other
external project was copied, paraphrased, or summarised while
preparing it. The opt-in path is local-only, fail-closed, and does NOT
call D-One, MCP, model APIs, image generation, image search, telemetry,
the Qoder runtime, or any other external service.

## 1. Status

- **Opt-in only.** The exporter recognises a single CLI flag,
  `--text-paragraph-merge`. Without it (the default) the exporter is
  byte-identical to a build that predates the flag: every `text`
  primitive emits exactly one `<a:p>` paragraph carrying one `<a:r>`
  run, whose `<a:t>` body is the literal `text.content` after XML
  escape — newlines and all.
- **No schema change.** The opt-in does not alter
  `schemas/render_model.schema.json`. The `text.content` field stays a
  non-empty string with no pattern. The opt-in changes how the
  exporter **interprets** that string, not what is allowed.
- **No new public-network behavior.** The flag does not enable any
  network call, telemetry, image generation, or model invocation.

## 2. Default vs. opt-in

| `text.content` | flag off (default)                                   | flag on (`--text-paragraph-merge`)                                                                                       |
| -------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `"Hello"`      | `<a:p><a:r>{rPr}<a:t>Hello</a:t></a:r></a:p>`        | byte-identical to flag-off (no `\n`, one paragraph)                                                                      |
| `"A\nB"`       | one `<a:p>` with one `<a:r>` whose `<a:t>` is `A\nB` | two `<a:p>`: `<a:p><a:r>{rPr}<a:t>A</a:t></a:r></a:p><a:p><a:r>{rPr}<a:t>B</a:t></a:r></a:p>`                             |
| `"A\n\nB"`     | one `<a:p>` with one `<a:r>` whose `<a:t>` is `A\n\nB` | three `<a:p>`: A, an `endParaRPr`-only blank, B                                                                        |
| `"\n"`         | one `<a:p>` with one `<a:r>` whose `<a:t>` is `\n`   | **fail closed** — no `.pptx` is written (no non-empty line after split)                                                  |

## 3. Behavioural invariants (flag on)

1. **One paragraph per `\n`-separated line.** The exporter splits the
   content on the literal `\n` character via `str.split("\n")`. No
   `\r\n` normalization, no tab handling, no whitespace trimming. The
   number of `<a:p>` elements equals `content.count("\n") + 1`.

2. **Run properties are uniform across every paragraph.** Each
   non-empty line gets one `<a:r>` whose `<a:rPr>` is the same block
   the flag-off path produces (resolved colour token, typography
   token, bold-iff-heading, latin typeface). Rich runs within a
   paragraph are out of scope.

3. **Empty lines emit a controlled blank paragraph.** An empty line
   produces `<a:p><a:endParaRPr lang="en-US"/></a:p>` — no `<a:r>`, no
   `<a:t>`, so the contract validator's `minimal_evidence.editable_text`
   gate is satisfied by the surrounding non-empty paragraphs and the
   visual line break is preserved. This mirrors the existing empty
   paragraph emission inside `_render_shape_sp` so the slide-body
   emitter is internally consistent.

4. **No text loss.** Joining every paragraph's text (treating an
   `endParaRPr`-only paragraph as `""`) with `"\n"` separators
   reconstructs the original `text.content` exactly. The self-test
   for the opt-in path asserts this round trip.

5. **No raster / image fallback.** The opt-in path never writes a
   `<p:pic>`, never emits a media-folder asset, never rasterises a
   slide. It is purely a paragraph-axis transformation on the
   existing `<p:sp>` textbox shape.

6. **No changes to other primitive kinds.** `kpi`, `table`, `shape`,
   `line`, and `image_slot` are untouched by the flag. A regression
   that started splitting their content on `\n` would be caught by
   the existing text-editability probes in `scripts/export_pptx.py
   --self-test`.

## 4. Fail-closed gate (flag on)

The opt-in path refuses content that has no non-empty line after
splitting (e.g. `"\n"`, `"\n\n"`, `"\n\n\n"`). The exporter raises
`ExportError` with a per-primitive message, the run aborts with a
non-zero exit code, and **no `.pptx` is written**. Rationale: a
text-box with zero editable paragraphs would trip the contract
validator's `minimal_evidence.editable_text` gate, and silently
producing a no-text textbox would erase the user's content.

The flag-off path keeps the pre-flag behaviour for the same content
(a single `<a:p>/<a:r>/<a:t>` carrying the literal newlines), so the
opt-in is the only gate that adds a fail-closed semantic on
content that is `\n` only.

## 5. Byte stability of the default path

The default exporter behaviour is preserved bit-for-bit. The exporter
threads a keyword-only parameter (`text_paragraph_merge: bool = False`)
through `main` → `export_workspace` / `export_single_render_model` →
`_slide_xml` → `_render_primitive` → `_render_text_sp`. Every default
is `False`, so any caller that does not opt in walks the same code
path as before. The self-test scenario *"workspace with `\n`-free text
exports BYTE-IDENTICAL output whether the opt-in is on or off"* asserts
this directly by byte-comparing the two `.pptx` outputs.

## 6. Verification

The opt-in is exercised entirely by the in-process self-test runner:

```
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/export_pptx.py --self-test
```

Six scenarios cover the contract:

1. **Byte-stability**: a single-line text fixture exports identical
   bytes whether the flag is on or off.
2. **Default with `\n`**: a multi-line text fixture exported WITHOUT
   the flag emits one `<a:p>` / one `<a:r>` / one `<a:t>` whose body
   contains the literal `\n`.
3. **Opt-in with `\n`**: the same fixture exported WITH the flag
   emits one `<a:p>` per line (3 with runs, 1 `endParaRPr`-only
   blank); the joined paragraph text reconstructs the original
   content; no `<p:pic>` appears; `validate_pptx_contract`'s
   container + minimal-evidence checks still pass.
4. **Fail-closed**: a fixture whose `text.content` is `"\n\n"`
   exported WITH the flag returns non-zero and writes no `.pptx`.
5. **Combined opt-in with `--trace-out`**: the same `\n`-bearing
   fixture exported WITH BOTH `--text-paragraph-merge` AND
   `--trace-out <path>` produces a contract-valid PPTX whose slide
   XML carries the paragraph-merge split (4 `<a:p>`, 3 `<a:r>`, no
   literal `\n` inside any `<a:t>`, blank line via `<a:endParaRPr>`)
   AND a schema-valid conversion-trace sidecar that
   `validate_conversion_trace.validate_trace` accepts; the trace's
   records still cover the same `(slide_index, slide_layout,
   primitive_id)` triple set as the exported render_model, the
   summary tally matches the records, and the output directory
   contains no `.tmp` residue and no unexpected sidecar file.
6. **Combined opt-in control**: the same `\n`-bearing fixture
   exported with NEITHER opt-in writes no `trace.json` sidecar and
   keeps the single-paragraph default text behaviour, proving the
   two opt-ins are the only drivers of the visible behaviour
   change.

## 7. Out of scope

- Rich run-level formatting (bold spans, italic spans, colour spans)
  inside a single paragraph.
- `\r\n` normalization. The exporter accepts `\n` only.
- Tab-based indentation, bullet markers, numbered lists. PPTX
  paragraph properties (`<a:pPr>`) beyond `<a:endParaRPr>` are not
  emitted by the opt-in path.
- Changes to `kpi`, `table`, `shape`, `line`, or `image_slot`
  primitives.
- Schema evolution. If a future render-model schema exposes an
  explicit `paragraphs` array, that is a separate paired contract
  change.
