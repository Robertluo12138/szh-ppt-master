# Source Image Asset Propagation Contract

## Status

**Validator wired (read-only). Producer / propagation NOT WIRED.** A narrow stdlib-only read-only validator ships at `scripts/validate_source_image_assets.py`: it schema-validates a caller-supplied `<workspace>/source_image_assets.json` against `schemas/source_image_asset.schema.json` and enforces the wire-side cross-checks listed under "Validator" below (unique ids, `source_ref == source_manifest.source.id` when a sibling intake manifest is present, `local_path` / `destination_path` safety + within-workspace + no-symlink at the source leaf or any parent segment of either path, source asset is a regular file whose on-disk `byte_count` + `sha256` match the registry, `media_type` agrees with the lowercase extension AND with the PNG / JPEG magic-byte signature, and — when a sibling `image_manifest.json` is present — every registry id the manifest names resolves to a `local_asset` entry whose `local_path` equals the registry `destination_path`). The validator does NOT call D-One / any network / any model API, does NOT mutate any file, and does NOT perform pipeline propagation. **No producer / propagation helper ships:** the registry bytes themselves are still authored by the agent (no parser reads `input/source.md` for image references), and `scripts/materialize_image_assets.py` remains the only helper that copies bytes. The D-One descriptor taxonomy and the real-D-One UNVERIFIED status are unchanged.

This contract sits side-by-side with the existing D-One descriptor taxonomy and the real-D-One **UNVERIFIED** status — none of those gates are changed by this document. The PPTX exporter, `scripts/init_image_manifest.py`, `scripts/materialize_image_assets.py`, and `scripts/done_image_adapter.py` are unchanged.

## Purpose

`scripts/init_workspace.py` writes `<workspace>/input/source.md` + `<workspace>/source_manifest.json` from a single local Markdown or text file. It does **not** look at, record, or copy any image bytes — `source_manifest.source` only carries the body's `id` / `local_path` / `kind` / `byte_count` / `line_count` / `sha256`.

When a source ships with image assets the deck will reuse (e.g. a Markdown body whose authors also delivered the inline figures as separate PNG / JPG / JPEG files), the agent needs a clean-room way to:

1. declare those assets, with stable ids and integrity hashes;
2. tie each asset back to a declared source (so the deck never carries an image that drifted in from outside the workspace);
3. point at where the asset lives BEFORE propagation (typically under `<workspace>/input/assets/`) and where it should live AFTER propagation (typically `<workspace>/assets/...`, matching `image_manifest.images[].local_path`);
4. do all of that **without** introducing public network behavior, telemetry, image search, model API calls, image generation, full-slide screenshots, or any of the patterns the D-One image policy already forbids.

That is what `source_image_assets.json` is for. It is a registry, not a producer — it describes the propagation contract; the bytes themselves are placed by the agent (today) or by a future producer step.

## Schema

`schemas/source_image_asset.schema.json` is the authoritative shape. Top-level: `{ "schema_version": "1", "assets": [...] }`. Each entry carries:

- `id` — stable identifier. ASCII letters, digits, underscore, dot, hyphen; must not start with a separator. Pattern mirrors `source_manifest.source.id`. The same `id` is reused downstream by `image_manifest.images[].id` when a slide references the asset.
- `source_ref` — stable backlink to the source. **Must equal `source_manifest.source.id`**, the same allow-list `deck_brief.source_refs[]` declares. Cross-checking is enforced at runtime by `scripts/validate_source_image_assets.py` (G4) when a sibling `source_manifest.json` is present, and is restated below under "Validator".
- `local_path` — workspace-relative path before propagation. Pattern locks to `input/assets/<safe-filename>.<png|jpg|jpeg>`; the schema refuses any other shape (URI scheme / leading slash / leading backslash / `..` segment / surrounding whitespace / nested subdirectory / mixed-case extension / unsupported extension). The lock is the path-safety gate — a `type: string, minLength: 1` schema would give a false-green to `../../etc/passwd`, `/abs/path`, `file:///etc/passwd`, etc.
- `destination_path` — workspace-relative path after propagation, i.e. exactly the value `image_manifest.images[].local_path` is expected to carry once the agent references this asset. Pattern locks to `assets/<safe-filename>.<png|jpg|jpeg>` for the same reason `local_path` is locked.
- `media_type` — RFC 6838 media type. Enum-locked to `image/png` / `image/jpeg` — the embed surface `scripts/export_pptx.py` supports today. SVG / GIF / WebP / TIFF / BMP / ICO are intentionally outside this enum (the exporter falls back to the placeholder shape for them).
- `byte_count` — positive integer byte length. Cheap defense-in-depth integrity gate.
- `sha256` — lowercase hex sha256 of the asset bytes. Same shape as `source_manifest.source.sha256`. A downstream consumer can re-hash `<workspace>/<local_path>` and `<workspace>/<destination_path>` and compare.

`additionalProperties: false` is set at the root and per-asset; unknown fields are refused so the contract does not accumulate silently.

## Synthetic template

`examples/source_image_asset_template.json` is a synthetic 1-asset instance that validates against the schema. The sha256 is a deterministic placeholder (`sha256(b"source-image-asset-template-placeholder")`); no real PNG bytes ship at `input/assets/synthetic_figure_alpha.png`. The template documents the field shape without claiming a wired byte-level integrity check.

Validate with the existing generic CLI:

```bash
python3 scripts/validate_artifacts.py \
  --schema schemas/source_image_asset.schema.json \
  examples/source_image_asset_template.json
```

For the full wire-side cross-check surface (schema + unique ids + source-manifest backlink + path safety + no-symlink + on-disk byte_count / sha256 + media_type / magic bytes + optional image_manifest alignment), run the dedicated validator against a workspace that ships the registry alongside the source asset bytes:

```bash
python3 scripts/validate_source_image_assets.py \
  --workspace <workspace> \
  [--registry <workspace>/source_image_assets.json]

python3 scripts/validate_source_image_assets.py --self-test
```

## Relationship to existing artifacts

### `source_manifest.json` (Stage 1 — already wired)

- Written by `scripts/init_workspace.py`. Today it records the source **body** only (`input/source.md`). It does **not** look at or copy any image bytes.
- `source_image_assets.assets[].source_ref` is intended to equal `source_manifest.source.id`. `scripts/validate_source_image_assets.py` (G4) asserts this when a sibling `source_manifest.json` is present; workspaces without an intake manifest skip the cross-check, and the agent is responsible for keeping the two in sync in that case.
- No change to `source_manifest.schema.json` is required to introduce this registry. The two artifacts are independent: a workspace with no source-attached images simply does not ship `source_image_assets.json`.

### `image_manifest.json` (Stage 6 — already wired)

- Written by `scripts/init_image_manifest.py` from a caller-supplied `--spec`. Each entry carries `id` / `local_path` / `source` / optional `alt_text` / `intended_use` / dimensions.
- The propagation rule is: when a slide references a source-attached image, the agent authors `image_manifest.images[]` with `id` = the registry `id`, `source` = `"local_asset"`, and `local_path` = the registry `destination_path`. The schema already enforces `local_path` safety on the image_manifest side; this registry adds the extra integrity fields (`byte_count`, `sha256`, `media_type`) the manifest does not carry.
- `init_image_manifest.py` is not changed by this contract. It still requires every declared `local_path` to already resolve inside the workspace to a regular non-symlink file before it writes the manifest.

### `scripts/materialize_image_assets.py` (already wired)

- Consumes `<workspace>/image_manifest.json` plus a `--assets-dir <dir>` of PNG / JPG / JPEG bytes keyed by `<id>.<ext>`. For each declared target, it either verifies the pre-existing target in place or copies bytes in from `--assets-dir`, with magic-byte and symlink and path-safety gates that abort fail-closed.
- Two propagation patterns are possible today without changing the helper:
  - **input/assets/ as the assets-dir**: the agent places the source-attached image bytes at `<workspace>/input/assets/<id>.<ext>` (matching the registry's `local_path`), authors `image_manifest.images[].local_path` to the registry's `destination_path`, and runs `scripts/materialize_image_assets.py --workspace <workspace> --assets-dir <workspace>/input/assets`. The helper copies bytes from `input/assets/<id>.<ext>` to `<workspace>/<destination_path>`.
  - **destination pre-placed**: the agent places the bytes directly at `<workspace>/<destination_path>` and runs `scripts/materialize_image_assets.py` with any `--assets-dir` (typically empty). The helper takes the verify-only branch.
- Neither pattern requires a new runtime helper. The registry is documentary: it captures the same id / path / byte-count / sha256 / media_type facts the agent must already enforce in order to satisfy materialize.

### `scripts/done_image_adapter.py` (D-One stub — already wired)

- Unchanged. The D-One adapter contract stub only operates on `image_manifest.images[]` whose `source == "d_one_local"`. Source-attached assets carry `source == "local_asset"`, so they are intentionally outside the D-One adapter's scope. The descriptor taxonomy in `schemas/d_one_descriptor_vocabulary.schema.json` is untouched.

## Security policy

The schema's `local_path` / `destination_path` patterns and the `media_type` enum carry most of the safety contract. In plain language:

- **No URL.** `local_path` and `destination_path` are anchored at `input/assets/` and `assets/` respectively; the first character of the relative path is fixed by the regex, so `https://`, `http://`, `file://`, `data:`, `mailto:`, and any other URI scheme fail at schema validation.
- **No absolute path.** Leading `/` and leading `\` are excluded by the same anchor.
- **No traversal.** Path segments must match `[A-Za-z0-9][A-Za-z0-9_.\-]*`. `..` does not start with `[A-Za-z0-9]`, so a `..` segment fails the pattern.
- **No symlink.** The schema cannot inspect the filesystem. `scripts/validate_source_image_assets.py` calls `scripts/validate_scaffold._resolves_within` against the workspace AND refuses symlinks at the source-asset leaf and any parent segment of either the source or the destination — the same anti-pattern `scripts/materialize_image_assets.py` already enforces on the runtime side.
- **No public upload, no telemetry, no model API.** The registry is local-only. There is no producer in this repo that calls D-One, MCP, image generation, image search, any model API, any public network, or any external service. The PPTX exporter is unchanged — embedded image rels remain internal-only, the same gate `scripts/validate_pptx_contract.py` already enforces.
- **No raw source body in image fields.** This registry never carries source text. `source_ref` is just the source id; `id` is the asset id; the only string fields besides those are the schema-locked paths and the media type. The D-One image policy's "no raw source text in prompts" rule is preserved by construction — no prompt field exists here.
- **No full-slide raster.** This registry describes spot illustrations / icons / figures attached to the source. Full-slide rendering remains forbidden per `references/d-one-image-policy.md`; this contract does not introduce any field that could express a full-slide intent.
- **MIME restricted.** `media_type` is enum-locked to `image/png` / `image/jpeg`. The path patterns lock the extension to `.png` / `.jpg` / `.jpeg` (lowercase). A consumer that wants to accept SVG / GIF / WebP must extend both the enum and the pattern — and must independently satisfy the PPTX exporter's embed contract.

## Validator

`scripts/validate_source_image_assets.py` is the wired validator. Given `--workspace <ws>` (and an optional `--registry <path>`, default `<ws>/source_image_assets.json`), it enforces:

- `<workspace>/source_image_assets.json` is a regular non-symlink file that schema-validates (G1 + G2);
- `assets[].id` is unique within the registry (G3);
- if a sibling `source_manifest.json` is present, every `assets[].source_ref` equals `source_manifest.source.id` — single-source workspaces; multi-source extension is out of scope (G4). When no `source_manifest.json` is present the cross-check is skipped.
- every `assets[].local_path` and `assets[].destination_path` passes `local_path_is_safe` AND `_resolves_within(workspace, path)` (G5);
- no symlink at the source-asset leaf, and no symlink at any parent segment of either the source or the destination (G6);
- the file at `<workspace>/<local_path>` exists as a regular non-symlink file (G7) whose on-disk byte length equals `byte_count` and whose sha256 equals the declared `sha256` (G8);
- declared `media_type` agrees with the lower-cased extension on both paths AND with the PNG / JPEG magic-byte signature at the head of the on-disk source asset (G9);
- if a paired `image_manifest.json` is present, for every registry `assets[].id` that ALSO appears as `image_manifest.images[].id`, the manifest entry MUST have `source == "local_asset"` and `local_path == registry destination_path` (G10 — alignment of matched id pairs; registry ids the manifest does not name are silently tolerated by this gate, the same behavior G10 has always carried);
- if a paired `image_manifest.json` is present, every registry `assets[].id` MUST appear as `image_manifest.images[].id` (G13 — completeness gate, separate from G10; a registry id the manifest does not declare fails closed under G13 because once the deck has committed to an `image_manifest.json`, an undeclared registry asset is propagation drift — the asset would never reach the deck — so the author must either add the manifest entry or remove the registry entry). G13 additionally enforces a structural precondition: if `image_manifest.json` is readable but its `images` field is missing or is not a JSON list (`null`, string, number, object), G13 refuses the run fail-closed — silently skipping both G10 alignment and G13 completeness on a malformed manifest would let `{"foo": "bar"}` mask every registry asset's undeclared state fail-OPEN. An empty `images: []` is structurally valid (just incomplete) and produces the per-asset "missing declaration" diagnostic for each registry entry, not the structural-precondition diagnostic;
- belt-and-braces string-shape checks (no surrounding whitespace, no URI scheme) on every string field at runtime, mirroring what the schema patterns already enforce (G11).
- no `id` / `source_ref` / `local_path` / `destination_path` string field may, once lower-cased AND stripped of every non-alphanumeric character (`_`, `.`, `-`, `/`, etc.), contain the marker `public` AND ALSO contain any of the propagation-verb / surface markers `upload`, `share`, `sharing`, `url`, `link`, `post`, `publish`, or `distribut` (G12). The deny fires on the COMBINATION of marker + verb; either alone is allowed. Normalization plus combined-marker matching is required because the schema permits `_`, `.`, AND `-` as separators inside an id (and the locked path patterns admit the same set inside the filename portion), so a literal-substring scan — or even a canonical-form scan against a fixed list of pre-baked compound tokens like `publicupload` / `sharepublicly` — would refuse `public_upload` while letting schema-equivalent variants (separator permutations like `public-upload` / `public.upload` / `publicupload` / `Public_Upload` / `public__upload`; word-order permutations like `share_public` / `share_to_public` / `upload_to_public` / `publish_to_public` / `link_to_public` / `distribute_public`; morphology permutations like `public_sharing` / `publicly_shared` / `shared_publicly` / `share_with_public` / `public_distribution` / `publish_public` / `public_publishing` / `public_linking` / `public_posting`; intervening-token permutations like `public_share_url` / `public_chart_link`; case + separator variants like `Public-Sharing` / `Shared.Publicly`; and the five identifiers the policy explicitly enumerates — `public_upload`, `public_upload_asset`, `share_publicly`, `public_url_for_assets`, `upload_to_public_bucket`) slip past. Every one of those collapses to a canonical form containing `public` plus at least one verb marker and is refused under one rule. `public` on its own is allowed (`public_chart` / `public_domain_marker` / `publication_meta` / `republican_emblem` keep passing — the bare word is ambiguous and not propagation intent on its own), and propagation-verb markers on their own are allowed (`share_image` / `upload_chart` / `permalink_marker` / `post_meta` / `publish_run` / `shared_team_data` keep passing — internal sharing is not in scope). Safe synthetic ids (`source_hero`, `product_marker`, `local_chart_asset`, etc.) collapse to canonical forms that contain neither marker, so they pass.

The validator is read-only — it never writes the registry, the manifest, or any asset file — and never calls D-One / any network / any model API. `--self-test` runs in-script tempfixture scenarios covering every gate plus happy paths. The destination leaf at `<workspace>/<destination_path>` is intentionally NOT inspected by this validator (the bytes there are placed by `scripts/materialize_image_assets.py`, which independently enforces the magic-byte check).

## Out of scope

- Producing `source_image_assets.json` from `input/source.md` (no parser).
- Calling D-One / Qoder / MCP / any image generator / model API / public network / external service.
- Image generation, image search, telemetry, prompt assembly.
- Changing `scripts/export_pptx.py`, `scripts/validate_pptx_contract.py`, `scripts/init_image_manifest.py`, `scripts/materialize_image_assets.py`, `scripts/done_image_adapter.py`, `scripts/run_d_one_generation.py`, or any other runtime helper.
- Extending the D-One descriptor taxonomy in `schemas/d_one_descriptor_vocabulary.schema.json` or the real-D-One UNVERIFIED status documented under `references/d-one-live-prerequisites.md` and `references/d-one-live-run-readiness.md`.
- Storing real / confidential image bytes or company data anywhere in this repo. Examples and templates must remain synthetic.
