# Brand / Design Preset Contract (Clean-Room, Idea-Only)

This document defines a SHAPE contract for an internal brand / design preset
in szh-ppt-master. It is **clean-room** — nothing here is copied, paraphrased,
or summarised from `hugohe3/ppt-master`, a local `ppt-master` checkout, or
any other external project. No upstream commit, source file, schema, prompt,
template, image, or asset was opened while preparing this contract.

## 1. Status

- **This is not runtime brand application.** No script in this repo reads
  a brand_preset file today. The runtime resolves design tokens via
  `templates/<name>/theme.json` and `scripts/init_design_system.py` only.
- **This is not upstream parity.** The high-level idea that an upstream
  PPT-generation project might add a brand subsystem is the only thing
  reflected here; the specific shape, field names, value enums, validator
  gates, and example fixture below were re-derived from
  `schemas/design_system.schema.json`, `schemas/theme.schema.json`, and
  `references/clean-room-policy.md` — not from any upstream file.
- **The contract is idea-only.** Any future projection of a preset onto a
  `design_system.json` requires a separate, paired schema + validator +
  generator change AND a user-approved scope expansion. Today the contract
  is shape-only; the literal `runtime_status: "non_runtime_contract"` in
  every preset locks that intent at the file boundary.
- **No new public-network behavior.** This contract does not call D-One,
  MCP, image search, telemetry, model APIs, the Qoder runtime, or PPTX
  export. It does not generate images. It does not read raw source body
  text. See `references/security-policy.md` and `SECURITY.md`.

## 2. What the contract covers

A brand preset is a single JSON object whose fields are all SHAPE hints:

| Field                  | Shape                                                            | Notes                                                                 |
| ---------------------- | ---------------------------------------------------------------- | --------------------------------------------------------------------- |
| `schema_version`       | string enum `["1"]`                                              | Bump only with a paired contract change.                              |
| `preset_id`            | string `^synthetic_[a-z0-9][a-z0-9_]*$`                          | Forced `synthetic_` prefix; no real-brand id can be authored.         |
| `display_name`         | string `^[A-Za-z0-9][A-Za-z0-9 _\-]*$`                           | No trademark glyphs, dot, ampersand, slash, or colon.                 |
| `runtime_status`       | string enum `["non_runtime_contract"]`                           | Hard literal that locks the file as shape-only.                       |
| `palette_tokens`       | object `{primary, secondary?, accent?, background, text}`         | Each value is a 6-digit hex color.                                    |
| `typography_tokens`    | object `{heading: {font_family, size_pt}, body: {...}}`          | CSS-style fallback chain; positive numeric point size.                |
| `spacing_style`        | string enum `["compact", "balanced", "airy"]`                    | Visual-density hint. Not applied at runtime.                          |
| `radius_style`         | string enum `["sharp", "soft", "rounded"]`                       | Corner-radius hint. Not applied at runtime.                           |
| `chart_style_hints`    | object `{series_palette_role, emphasis}`                         | Closed enums. Charting is not implemented.                            |
| `allowed_layout_mood`  | array of 1-4 unique strings from a closed enum                   | Layout-mood subset the preset opts into.                              |
| `notes`                | string, optional, maxLength 280                                  | Terse, synthetic. Validator gates real-brand / URL / etc. wording.    |

`schemas/brand_preset.schema.json` is the source of truth for the exact
patterns, enums, and required-vs-optional flags. `additionalProperties: false`
is set at every object boundary, so unknown fields fail closed at schema
validation.

## 3. Fail-closed rules

The schema patterns and enums refuse most authoring slips at the schema layer:

- the `synthetic_` prefix on `preset_id` refuses any real-brand id;
- the `display_name` pattern refuses trademark glyphs, dot, comma, slash,
  colon, ampersand, and quotes — the punctuation real brand marks usually use;
- the hex-only palette values refuse named brand colors (`Anthropic Orange`,
  `Google Blue`, ...) and URL-shaped values;
- the typography `font_family` pattern excludes URL punctuation (`:`, `/`,
  `?`, `#`) and path separators (`\`);
- `runtime_status` is a single-value enum, so a preset cannot be authored as
  `"applied"` / `"live"` / etc.

The read-only validator (`scripts/validate_brand_preset.py`) re-applies the
schema gate AND adds belt-and-braces content gates that scan EVERY string
field, including the freeform `notes`:

| Gate | Refuses                                                                                                  |
| ---- | -------------------------------------------------------------------------------------------------------- |
| P1   | Symlink at the preset path, non-object root, non-JSON / non-UTF-8 bytes.                                 |
| P2   | Schema-subset violation (re-uses `scripts/validate_artifacts._validate`).                                |
| P3   | `runtime_status` not equal to the literal `"non_runtime_contract"`.                                       |
| P4   | Real-brand wording denylist (Google / Anthropic / Claude / OpenAI / ChatGPT / Microsoft / PowerPoint / Apple / Keynote / Adobe / Figma). |
| P5   | URI-scheme prefix (`http:`, `https:`, `file:`, `data:`, `s3:`, `ftp:`, `mailto:`, `javascript:`) AND embedded URLs anywhere in any string. |
| P6   | Absolute paths (`/...`), leading backslash, protocol-relative (`//host`), and `..` path segments.        |
| P7   | `public` combined with a propagation verb (`upload`, `share`, `sharing`, `url`, `link`, `post`, `publish`, `distribut...`, `host...`). The brand-preset list is a SUPERSET of `scripts/validate_source_image_assets.py` G12 — the `host` substring catches `host` / `hosted` / `hosting` / `hosts` in one entry, so authoring slips like `public hosting enabled`, `host publicly`, and `public hosted asset` all fail closed. |
| P8   | Image-generation prompt wording (`midjourney`, `stable diffusion`, `dalle`, `firefly`, `imagen`, `imagegen`, `texttoimage`, ..., plus `done` + `image/asset/render`). |
| P9   | Confidential / raw-source wording (`confidential`, `proprietary`, `internal_only`, `nda_protected`, `customer_name`, `account_id`, `ssn`, `credit_card`, plus `raw` + `source/content/paragraph/excerpt`). |
| P10  | Surrounding whitespace on any string field.                                                              |
| P11  | Credential-shaped wording: qualifier-prefixed token compounds (`api_key`, `api_token`, `access_token`, `auth_token`, `csrf_token`, `id_token`, `jwt_token`, `oauth_token`, `refresh_token`, `session_token`), plus `secret`, `bearer`, `password`, plus the bare marker `token` (catches `token`, `token=value`, `token placeholder`, `TOKEN`), plus `sk-...`-prefixed API keys matching ``\bsk-[A-Za-z0-9_\-]{16,}`` (the OpenAI / Anthropic shape; other-provider prefixes like Stripe `sk_test_` or GitHub `ghp_` are NOT covered). Bare `token` IS a marker on its own — preset string values have no contract reason to carry the word outside a credential context, and the design-system vocabulary that legitimately uses `token` (`palette_tokens`, `typography_tokens`) appears only as schema KEYS, which the validator does not walk. The qualifier-prefixed compounds are kept first in iteration order so the diagnostic on `access_token` names the specific compound (`accesstoken`) rather than the bare `token`; both shapes would fire either way. P11 is enforced by the validator only — the schema has no field-shape pattern for credential wording. |

P4 / P7 / P8 / P9 normalise each candidate string to a canonical form
(lower-case, non-alphanumeric stripped) before matching so every separator,
word-order, and morphology permutation collapses to the same form. Same
canonical-form shape as `scripts/validate_source_image_assets.py` G12 —
P7's propagation-marker set is a SUPERSET of G12 (adds `host` so preset-
style public-hosting wording fails closed; G12 does not see preset author
notes). P11 re-uses the same canonicalisation helper for its compound-
token check, but only the separator-stripping and lowercasing are
designed coverage — word-order and morphology (e.g. pluralised forms
like `api_tokens` matching `apitoken` by substring) are incidental
side-effects of substring matching, not promises the gate makes. P11
additionally runs a raw-string regex for the ``sk-`` API-key shape
because the literal ``sk-`` prefix plus its 16+ char alphanumeric tail
is the diagnostic signature — canonicalising would collapse the prefix;
the regex scopes to the OpenAI / Anthropic shape only and does not claim
to cover other-provider credential prefixes.

P4's denylist is intentionally narrow — it names the brands the user prompt
explicitly forbids plus a handful of commonly-recognised brand tokens. It
is NOT a complete trademark check; the real protection is the schema
patterns above.

## 4. Synthetic example fixture

A single synthetic preset ships at `examples/brand_preset_template.json`. Its
fields are placeholders: a neutral grey palette, a generic CSS font fallback
chain, an `allowed_layout_mood` of `["minimal", "analytical"]`, and a
synthetic `preset_id` of `synthetic_neutral_minimal`. It carries no real
brand wording, no URL, no external asset reference, no public-upload
language, no image-generation prompt, and no raw-source / confidential text.

The fixture validates under both the subset schema validator and the
brand-preset validator:

```
python3 scripts/validate_artifacts.py \
    --schema schemas/brand_preset.schema.json \
    examples/brand_preset_template.json

python3 scripts/validate_brand_preset.py \
    --preset examples/brand_preset_template.json
```

## 5. Usage

Read-only validation:

```
python3 scripts/validate_brand_preset.py --preset <path-to-preset.json>
```

Built-in self-test (positive baseline + negative probes for every gate):

```
python3 scripts/validate_brand_preset.py --self-test
```

The validator NEVER writes to disk, NEVER calls any network, NEVER invokes
D-One / Qoder / MCP / model APIs / image search / image generation, and
NEVER mutates the preset file or any workspace artifact.

## 6. Out of scope

The following are NOT implemented and are NOT covered by this contract:

- runtime projection of a preset onto `design_system.json` (no generator,
  no init helper, no pipeline stage reads a preset);
- multi-preset deck composition;
- preset inheritance or overrides;
- chart rendering whose colors are driven by the chart-style hints;
- any PPTX exporter coupling — the exporter resolves design tokens via
  `design_system.json` only;
- any D-One / MCP / Qoder integration that consumes a preset;
- any image-generation prompt assembly from preset fields;
- any public network / telemetry / model API behavior.

If any of these is later picked up as work, the corresponding design must
be drafted FIRST under `references/` and reviewed against
`references/clean-room-policy.md` before any code lands. The literal
`runtime_status: "non_runtime_contract"` in every preset is the gate that
must be flipped — in a paired schema + validator + runtime change — when
runtime application is approved.

## 7. Cross-references

- `references/clean-room-policy.md` — the clean-room constraint this
  contract lives inside.
- `references/security-policy.md`, `SECURITY.md` — the privacy /
  network gates this contract must satisfy.
- `references/upstream-ppt-master-radar.md` — idea-only radar that
  notes the upstream brand-subsystem topic without importing any
  upstream shape.
- `schemas/brand_preset.schema.json` — the schema this contract
  describes.
- `schemas/design_system.schema.json`, `schemas/theme.schema.json` —
  the runtime design-token contracts a future projection would target.
- `examples/brand_preset_template.json` — the single synthetic fixture.
- `scripts/validate_brand_preset.py` — the read-only validator.
