# D-One Image Policy

"D-One" stands for the local image-generation integration that may, in a future phase, populate small image assets used inside slides. The integration is **not implemented**. This file is the policy that any such integration must satisfy before it ships.

Stage 6 today is covered only by the narrow contract helper `scripts/init_image_manifest.py`, which validates a caller-supplied `--spec` JSON against `schemas/image_manifest.schema.json`, cross-checks every `slide_plan.image_refs[*]` against `images[].id`, and requires every `images[].local_path` to resolve inside the workspace to a regular non-symlink file. The helper does **not** generate any image asset, does **not** call D-One, and does **not** call any public network — assets must already exist locally inside the workspace before the helper runs.

The PPTX exporter (`scripts/export_pptx.py`) embeds **local PNG / JPG / JPEG** manifest entries into `ppt/media/imageN.<ext>` as native `<p:pic>` shapes; SVG / GIF / WebP / any other extension still falls back to the placeholder rectangle (alt-text only) and is never embedded today. The embed slice does NOT generate any new asset — it only consumes assets the caller / a future local generator already wrote into the workspace.

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
- Every prompt sent to the generator must be logged in the image manifest (or a sidecar) for audit.

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
