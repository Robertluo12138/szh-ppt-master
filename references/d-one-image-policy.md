# D-One Image Policy

"D-One" stands for the local image-generation integration that may, in a future phase, populate small image assets used inside slides. The integration is **not implemented**. This file is the policy that any such integration must satisfy before it ships.

Stage 6 today is covered only by the narrow contract helper `scripts/init_image_manifest.py`, which validates a caller-supplied `--spec` JSON against `schemas/image_manifest.schema.json`, cross-checks every `slide_plan.image_refs[*]` against `images[].id`, and requires every `images[].local_path` to resolve inside the workspace to a regular non-symlink file. The helper does **not** generate any image asset, does **not** call D-One, and does **not** call any public network — assets must already exist locally inside the workspace before the helper runs.

`scripts/materialize_image_assets.py` is the **pre-D-One local asset gate** (not D-One itself). Given a workspace that already ships a schema-valid `image_manifest.json` and a `--assets-dir <dir>` of local PNG / JPG / JPEG files keyed by `<id>.<ext>` (where `id` matches an `images[].id` and `<ext>` matches the lower-cased extension of `images[].local_path`), the helper either **copies** the asset bytes into the workspace paths declared by each `images[].local_path` when the target does not yet exist, or **verifies** the pre-existing target in place when it does — in both cases the post-condition is that every declared target is a regular non-symlink PNG / JPG / JPEG file whose first bytes match the magic-byte signature for the declared extension. The verify-or-copy semantics support two distinct workflows; `scripts/init_image_manifest.py` itself refuses to overwrite a pre-existing `image_manifest.json`, so the two workflows do NOT chain through it (each stands on its own, and the manifest must already be in place before materialize runs):

- **Direct-author workflow (no init helper):** the agent writes `<workspace>/image_manifest.json` directly (e.g. by copying an authored spec JSON verbatim), places PNG / JPG / JPEG asset bytes under `--assets-dir` keyed by `<id>.<ext>`, then runs materialize; every declared target hits the **copy** branch. `init_image_manifest.py` is NOT invoked in this path — it would refuse to overwrite the already-written manifest.
- **init_image_manifest workflow (assets pre-placed):** the agent places PNG / JPG / JPEG asset bytes directly at `<workspace>/<local_path>` for every declared image, then runs `scripts/init_image_manifest.py --workspace ws --spec spec.json` (which requires every declared `local_path` to already resolve to an existing regular non-symlink file before it writes the manifest); materialize is then an OPTIONAL follow-up that takes the **verify-only** branch for every target. Defense in depth — `init_image_manifest` only checks file existence at each declared `local_path` and does NOT check PNG / JPEG magic bytes.

Re-running on a fully-materialized workspace with the same `--assets-dir` is idempotent. It refuses unsafe paths (URI / `..` / leading `/` / leading `\\`), symlinks (workspace / assets-dir / manifest / source asset / target / parent path of target / sibling in assets-dir), missing source files, unsupported extensions (anything other than `.png` / `.jpg` / `.jpeg` — the embed surface `scripts/export_pptx.py` supports today; SVG / GIF / WebP fall back to the placeholder shape), duplicate `images[].id`, undeclared assets (files at the assets-dir root the manifest does not name), magic-byte mismatches (a `.png`-named file with JPEG bytes, or vice versa, on either the source under `--assets-dir` OR a pre-existing target under the workspace), and any write outside `--workspace`. The helper does **not** call D-One, image generation, image search, any public network, any model API, any external service; it does **not** open `input/source.md` or copy any business content into a prompt or image field; it does **not** generate full-slide screenshots; it does **not** mutate `image_manifest.json` (the manifest bytes must be byte-identical before and after a successful run); and it does **not** produce `render_models/*`, `svg_previews/*`, or any `.pptx`. A mid-loop or post-condition failure rolls back every target the helper wrote in this run (verify-only entries are never rolled back because the helper did not create them).

When real D-One integration ships, it will plug in upstream of this gate: D-One produces local PNG / JPG / JPEG bytes under a controlled local directory, the agent places them under `--assets-dir` (direct-author workflow) or directly at the declared target paths (init_image_manifest workflow), and `materialize_image_assets.py` then enforces every safety rule above — either copying the bytes into the workspace or verifying them in place.

`scripts/done_image_adapter.py` is the **D-One adapter contract stub** (not D-One integration). It sits between `init_image_manifest.py` (which writes the manifest) and the eventual real D-One generator. Given a workspace that already ships a schema-valid `image_manifest.json` and a caller-supplied `--spec <prompt-spec.json>`, the adapter (1) validates that every request `id` matches an `images[].id` whose `source == "d_one_local"` (so requests against `local_asset` / `synthetic` manifest entries are refused outright); (2) scans every request `prompt` against a defense-in-depth deny list — URI schemes (`http://`, `file://`, `data:`, `mailto:`, ...), absolute / traversal / Windows / UNC file-path shapes, raw-source marker literals (`<SOURCE>`, `BEGIN SOURCE`, ...), any 40-character substring of `input/source.md` (the shingle gate — catches a caller who copy-pasted source body into a prompt), credential shapes (JWT, AWS access key, PEM marker, long hex blobs, bearer tokens, `password:` / `secret:` / `api_key:` / `token:` literals), customer / account / contact-id shapes (emails, phone numbers, SSN-like strings, UUIDs, `customer_id` / `account_id` literals), and full-slide / page-generation / screenshot wording (`full slide`, `whole slide`, `screenshot`, `render the slide`, ...); (3) writes a deterministic dry-run plan file to `<workspace>/d_one_adapter_plan.json` (or `--plan-out`) recording the validated requests for a future generator to consume. The plan file is byte-identical across runs with the same inputs (requests are sorted by `id`). The adapter does **not** call D-One / Qoder / any image-generation model / any public network / any external service; does **not** generate any image bytes (PNG / JPG / JPEG / SVG / GIF / WebP); does **not** mutate `image_manifest.json`; does **not** open `input/source.md` for content extraction (only its raw bytes, only for the 40-character shingle check); does **not** generate full-slide screenshots; does **not** produce `render_models/*`, `svg_previews/*`, or any `.pptx`; and does **not** change PPTX export behavior. Symlinks at `--workspace` / `--spec` / `--plan-out` / `input/source.md` are refused; URI-shaped arguments are refused at the string layer before any filesystem call; a pre-existing `--plan-out` file is refused (no overwrite); a mid-write failure rolls back the plan file so the workspace returns to its pre-call state. When real D-One integration ships, the dry-run plan this adapter produces becomes the input to the generator step, whose output bytes then flow through `materialize_image_assets.py` for the same magic-byte and path-safety gates that gate any other local asset today. Real MCP / D-One generation is intentionally **not** wired today.

The PPTX exporter (`scripts/export_pptx.py`) embeds **local PNG / JPG / JPEG** manifest entries into `ppt/media/imageN.<ext>` as native `<p:pic>` shapes; SVG / GIF / WebP / any other extension still falls back to the placeholder rectangle (alt-text only) and is never embedded today. The embed slice does NOT generate any new asset — it only consumes assets the caller / `scripts/materialize_image_assets.py` / a future local generator already wrote into the workspace.

## Allowed use

- D-One (or any future image generator) produces **local image assets only**: spot illustrations, icons, decorative artwork, small textures.
- Generated images are referenced by `image_manifest.json` and embedded inside the final PPTX (PNG / JPG / JPEG only today; SVG embedding remains TODO and falls back to the placeholder shape).
- A future D-One integration that emits SVG must either also emit a PNG fallback (PowerPoint requires both for SVG embedding) or accept the placeholder-shape fallback.

## Forbidden use

- D-One must **never** produce a full-slide background or a full-slide screenshot.
- D-One must **never** produce text-bearing imagery that would replace an editable text frame. If a slide needs text, the text lives in the SVG/PPTX layer, not in the image.
- D-One must **never** receive raw source-document text as a prompt. Prompts must be derived, abstracted, and reviewed (see below).

## Prompt review

- Image prompts must be assembled from approved, abstracted descriptors (e.g. "abstract geometric pattern in the deck's primary color"), not from copy-pasted source text.
- The prompt-assembly logic must be deterministic given the slide plan and design system.
- Every prompt sent to the generator must be logged in the image manifest (or a sidecar) for audit. `scripts/done_image_adapter.py` writes a deterministic dry-run plan to `<workspace>/d_one_adapter_plan.json` recording every validated request (id, prompt, optional intended_use / width_px / height_px, manifest cross-references), and refuses prompts whose body contains URIs, file paths, source markers, raw-source-text shingles, credential shapes, customer / account / contact-id shapes, or full-slide / page-generation / screenshot wording.

## Asset handling

- Generated assets are stored under the workspace, never alongside the source code.
- The `image_manifest.json` entry must record:
  - `id`
  - `local_path` (relative to workspace, no `..`)
  - `source` = `"d_one_local"`
  - `intended_use`
  - dimensions
- An image referenced by a slide but missing from disk is a fail-closed security violation.

## Network

- D-One integration must not introduce public network behavior unless explicitly approved. If a remote model is used, that decision needs its own reference doc and a security review.

## TODOs

- Define the descriptor vocabulary for image prompts.
- Decide whether generated assets are cached across runs.
- PNG and JPG/JPEG embedding is implemented today; default size limits are enforced via the 10 MiB embed cap in `scripts/export_pptx.py`. SVG / GIF / WebP embedding remain TODO — SVG specifically requires a PNG fallback alongside the SVG blip plus an SVGBlip extension before it can land safely.
- Decide whether D-One output is allowed to overwrite a pre-existing manifest entry's `local_path`, or whether every generation produces a new sidecar file.
