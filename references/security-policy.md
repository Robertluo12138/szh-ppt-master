# Security Policy (detail)

Companion to `SECURITY.md`. This file is the contract for what the security scan must check; `SECURITY.md` is the public-facing summary.

## Fail-closed checks

The security scan **must fail** the artifact (not warn) when any of the following is true:

1. An artifact references an external URL (`http://`, `https://`, protocol-relative `//`, or any non-local scheme other than the explicitly allowed set, currently empty).
2. An artifact references `file://`.
3. An artifact references an absolute filesystem path (`/...` on POSIX, `X:\...` on Windows). Paths must be relative to the workspace.
4. A PPTX (when conversion is implemented) contains a relationship type outside the allowed set. The allowed set is **TODO**; until then, all relationship types must be enumerated and confirmed safe before being added.
5. A PPTX (when conversion is implemented) contains OLE objects, ActiveX controls, embedded macros, or remote-loaded media.
6. An `image_manifest` entry references a `local_path` that does not exist or escapes the workspace (`..`).
7. Any stage produced an artifact that failed schema validation, or whose validation status is "unknown".
8. Any image prompt sent to an image generator contains material that was not pre-approved as derived/abstracted text (see `d-one-image-policy.md`).

If the scanner cannot decide whether a check passed, the result is **fail**.

## Out of scope for the security scan

The security scan is not responsible for:

- factual correctness of slide content (that is a writing-quality concern);
- aesthetic quality (that is `quality-gates.md`).

## Reporting

The scan output must include:

- list of checks executed (by name);
- per-check pass/fail/error status;
- the artifact path or identifier each check ran against;
- a final overall status (`pass` only if every check passed and no check errored).

A run with errored checks is **not** a pass, even if every executed check passed.

## TODOs

- Enumerate the allowed PPTX relationship types once PPTX conversion is in scope.
- Define a canonical list of check names so reports are diffable across runs.
- Decide whether the scan should also reject embedded base64 image data above a size threshold (likely yes).
