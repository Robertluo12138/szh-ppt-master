# Security and Privacy Policy

This skill processes user-supplied source material (prompts, reports, Markdown) into editable PowerPoint decks. It is internal and runs locally. The rules below are durable.

## Network

- Default to **no public network access**.
- No public scraping, public image search, or "fetch any URL" behavior.
- No telemetry. No outbound calls for usage reporting.
- Any future remote dependency (model API, asset store) must be declared explicitly, opt-in, and documented in a reference file before code is added.

## Source material handling

- Do not send raw source documents or sensitive report text to image-generation prompts. Image prompts must be derived, abstracted, and reviewed.
- Do not commit real customer data, credentials, endpoints, account IDs, customer names, or sensitive report text to this repo. Examples must be synthetic or thoroughly redacted.
- Do not log full source content. Logs must redact or reference by identifier only.

## Fail-closed checks

When the security scan or any per-stage validator encounters one of the following, it **must** fail (not warn, not "best-effort"):

- External URLs in slide content, images, or PPTX relationships.
- `file://` URIs anywhere in artifacts or generated PPTX.
- Absolute filesystem paths in artifacts intended to be portable.
- Unsafe PPTX relationship types (OLE objects, external links, remote media).
- Missing or unresolved media references.
- Any artifact whose schema validation status is "unknown" or "errored".

If a check cannot decide safety, treat it as unsafe.

## Image policy (summary)

See `references/d-one-image-policy.md` for detail.

- Image generators (D-One or otherwise) may only produce **local image assets** consumed inside SVG/PPTX. Never full-slide backgrounds, never slide screenshots.
- The image manifest must record every image's local path, source, and intended use.

## Editability

- Final PPTX must be editable: real text frames, real shapes, real tables — not a single rasterized image per slide. Visual fidelity does not justify shipping image-only slides.

## Reporting

A scan / validation report must record:

- which checks ran;
- their pass/fail status;
- the artifact identifiers checked;
- any unresolved TODOs.

A passing scan with unresolved TODOs is not a passing scan.
