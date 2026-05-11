# Quality Gates

The gates a deck must pass before the skill reports success. Each gate maps to an explicit stage; if a gate is unimplemented today, that is recorded.

| Gate | Stage | Status |
|---|---|---|
| `brief.schema` — `deck_brief.json` validates | Brief | scaffold (subset validator) |
| `plan.schema` — `deck_plan.json` validates | Plan | scaffold (subset validator) |
| `design.schema` — `design_system.json` validates | Design system | scaffold (subset validator) |
| `slide.schema` — every `slide_plan.json` validates | Per-slide plan | scaffold (subset validator) |
| `images.schema` — `image_manifest.json` validates | Image manifest | scaffold (subset validator) |
| `images.exist` — every referenced image exists locally and is inside the workspace | Image manifest | TODO |
| `svg.bounds` — no element exits the canvas viewBox | SVG validate | TODO |
| `svg.refs` — no external URLs, no `file://`, no absolute paths | SVG validate | TODO |
| `svg.fonts` — fonts are declared and resolvable | SVG validate | TODO |
| `svg.density` — density is within threshold | SVG validate | TODO |
| `svg.editable` — every text run is a real text node | SVG validate | TODO |
| `pptx.editable` — every text frame is editable, no all-image slides | PPTX export | TODO |
| `pptx.relationships` — only allow-listed relationship types | PPTX export | TODO |
| `pptx.media` — every media item exists, no remote refs | PPTX export | TODO |
| `security.scan` — fail-closed scan passes | Reports | TODO |
| `visual.regression` — design diff within tolerance | Reports | TODO (not in current scope) |

## Pass criteria

The skill may only report `success` when **every** gate above has status `pass`. Gates marked TODO are blockers for end-to-end success — the skill must therefore not yet claim end-to-end success.

A gate marked `error` (the check failed to run cleanly) is **not** a `pass`.

## Reporting

The aggregated report lists, for each gate:

- name;
- status (`pass` / `fail` / `error` / `skipped`);
- artifact identifiers checked;
- repair / mitigation summary if any.

`skipped` is only allowed when the user explicitly skipped a stage; otherwise a missing gate is `error`.
