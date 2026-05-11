# Quality Gates

The gates a deck must pass before the skill reports success. Each gate maps to an explicit stage; if a gate is unimplemented today, that is recorded.

| Gate | Stage | Status |
|---|---|---|
| `brief.schema` — `deck_brief.json` validates | Brief | scaffold + workspace (subset validator) |
| `plan.schema` — `deck_plan.json` validates | Plan | scaffold + workspace (subset validator) |
| `design.schema` — `design_system.json` validates | Design system | scaffold + workspace (subset validator) |
| `slide.schema` — every `slide_plan.json` validates | Per-slide plan | scaffold + workspace (subset validator) |
| `images.schema` — `image_manifest.json` validates | Image manifest | scaffold + workspace (subset validator) |
| `images.path-safety` — every `local_path` rejects any URI scheme (`^[A-Za-z][A-Za-z0-9+.\-]*:`), absolute paths, leading backslash, protocol-relative, and `..` segments | Image manifest | scaffold + workspace |
| `images.exist` — every referenced image exists locally and resolves inside the workspace | Image manifest | workspace (`scripts/validate_workspace.py`) |
| `images.refs` — every `slide_plan.image_refs` id is declared in `image_manifest` | Per-slide plan | workspace (`scripts/validate_workspace.py`) |
| `plan.template` — `deck_plan.template` resolves to a real template under the template-root | Plan | workspace (`scripts/validate_workspace.py`) |
| `plan.layouts` — every `deck_plan` slide layout is declared by the chosen template | Plan | workspace (`scripts/validate_workspace.py`) |
| `plan.coverage` — every `deck_plan` slide has a matching `slide_plan` file (and every `slide_plan` matches its deck_plan entry on index/layout/title) | Per-slide plan | workspace (`scripts/validate_workspace.py`) |
| `brief.source_refs` — `deck_brief.source_refs` is present and non-empty | Brief | scaffold + workspace |
| `plan.count` — `deck_plan.planning.planned_slide_count` equals `len(deck_plan.slides)` | Plan | scaffold + workspace |
| `plan.sections` — `deck_plan.sections[].slide_indices` partition the set of `slides[].index` (no duplicates across sections, no missing deck indices, no orphan section indices) | Plan | scaffold + workspace |
| `plan.section_id` — every `deck_plan.slides[].section_id` resolves to an existing section, and the slide's index is listed in that section's `slide_indices` | Plan | scaffold + workspace |
| `plan.slide_source_refs` — every `deck_plan.slides[].source_refs` value is declared in `deck_brief.source_refs` | Plan | scaffold + workspace |
| `slide.slots` — every required layout slot is covered by a matching slide_plan block id+kind | Per-slide plan | scaffold + workspace |
| `svg.bounds` — no element exits the canvas viewBox | SVG validate | TODO |
| `svg.refs` — same fail-closed rule as `images.path-safety` (any URI scheme, absolute, leading-backslash, protocol-relative, `..`) | SVG validate | TODO |
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
