# D-One Image Policy

"D-One" stands for the local image-generation integration that may, in a future phase, populate small image assets used inside slides. The integration is **not implemented**. This file is the policy that any such integration must satisfy before it ships.

## Allowed use

- D-One (or any image generator) produces **local image assets only**: spot illustrations, icons, decorative artwork, small textures.
- Generated images are referenced by `image_manifest.json` and embedded inside the final PPTX.

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
- Decide image format defaults (PNG vs SVG vs WebP) and size limits.
