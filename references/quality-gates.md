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
| `render.schema` — each `render_model/*.json` validates against `render_model.schema.json` (controlled primitive kinds, required bounds, token-only style refs, `additionalProperties:false` everywhere — no arbitrary SVG-like fields) | Render model | scaffold + workspace (when render models ship) |
| `render.bounds` — every primitive's bounds fit inside the canvas and (when `slot_id` is set) inside the layout slot's bounds | Render model | workspace |
| `render.kind_payload` — exactly one kind-specific payload field is present and matches `kind` | Render model | workspace |
| `render.slot` — `slot_id` resolves to a layout slot, and primitive `kind` matches `slot.primitive_kind` (or the default `slot.type` → primitive mapping) | Render model | workspace |
| `render.tokens` — `style.*_token` values resolve to a `design_system.palette` key or a supported typography role | Render model | workspace |
| `render.image_ref` — `image_slot.image_ref` is declared in `image_manifest.images[].id`; the schema also forbids URI schemes / absolute paths / `..` in this field | Render model | scaffold + workspace |
| `render.source_refs` — `source_refs` is required and non-empty, and every value is declared in `deck_brief.source_refs`; the cross-check is **fail-closed** under a missing / malformed / empty deck_brief | Render model | scaffold + workspace |
| `render.no_svg_fields` — arbitrary SVG-like fields (`transform`, `viewBox`, `href`, `xlink:href`, `xmlns`, `defs`, `foreignObject`, `filter`, …) are rejected by `additionalProperties:false`; negative tests prove this | Render model | scaffold + workspace |
| `render.generator.supported_layouts` — `scripts/generate_render_models.py` produces output **only** for `cover` and `kpi_dashboard`; every other layout is reported `[SKIP] … not implemented` and is NOT counted as success | Render model | workspace (tempfixture) |
| `render.generator.fail_closed` — generator fails closed on missing / malformed inputs, unsafe `deck_plan.template`, unknown `image_ref`, malformed kpi entries, missing required slide_plan block, schema-invalid output, or workspace cross-check failure | Render model | workspace (tempfixture) |
| `render.generator.preflight` — BEFORE the `render_models/*.json` cleanup sweep, the generator schema-validates `deck_brief.json`, `deck_plan.json`, `design_system.json`, `image_manifest.json`, proves `deck_plan.slides` is a non-empty list of objects, and runs `check_planner_semantics` (`planned_slide_count` == `len(slides)`, section coverage, `section_id` resolution, `source_refs` subset of `deck_brief.source_refs`). Any preflight failure exits non-zero and **does not delete any** pre-existing `render_models/*.json` | Render model | workspace (tempfixture) |
| `render.generator.slide_plan_alignment` — generator fails closed when a slide_plan matched by `index` carries a `layout` or `title` that disagrees with the deck_plan slide (stale / mismatched slide_plan); no render_model is emitted in that case | Render model | workspace (tempfixture) |
| `render.generator.stale_cleanup` — before generating, the script removes **every** `render_models/*.json`. The workspace validator treats every `*.json` in this directory as a render_model and schema-validates it, so the `*.json` namespace is generator-owned. A stale file from a previous run cannot survive a current-run fail-closed mismatch, a deck_plan layout change that moves the slide to an unsupported layout, **or a slide being removed from `deck_plan` entirely (orphan)**. Non-JSON files (READMEs, `.md` / `.txt` notes) are preserved | Render model | workspace (tempfixture) |
| `svg.exists` — every `render_models/<stem>.json` has a matching `svg_previews/<stem>.svg` | SVG validate | workspace (`scripts/validate_workspace.py`) |
| `svg.root` — root element is `<svg>` in the SVG namespace with a `viewBox` matching the render_model canvas (`0 0 W H`) | SVG validate | workspace (`scripts/validate_workspace.py`) |
| `svg.no_foreign_object` — no `<foreignObject>` element appears anywhere in the tree | SVG validate | workspace (`scripts/validate_workspace.py`) |
| `svg.refs` — same fail-closed rule as `images.path-safety` (any URI scheme, absolute, leading-backslash, protocol-relative, `..`) applied to `href` / `xlink:href` / `src` / any attribute ending in `href` | SVG validate | workspace (`scripts/validate_workspace.py`) |
| `svg.image_refs` — every `<image>` `href` value names an `image_manifest` `local_path` | SVG validate | workspace (`scripts/validate_workspace.py`) |
| `svg.bounds` — every `<rect>` / `<image>` / `<ellipse>` / `<circle>` / `<line>` with explicit numeric geometry stays inside the canvas (best-effort: elements without numeric geometry are not checked here) | SVG validate | workspace (`scripts/validate_workspace.py`) |
| `svg.text_anchor` — every `<text>` with numeric `x`/`y` has its anchor point inside the canvas (`x ≥ 0`, `y ≥ 0`, `x ≤ canvas.width_px`, `y ≤ canvas.height_px`) | SVG validate | workspace (`scripts/validate_workspace.py`) |
| `svg.text_overflow` — `<text>` width / height / wrapping at the glyph level is enforced (would require font metrics) | SVG validate | TODO |
| `svg.generator.supported_kinds` — `scripts/generate_svg_previews.py` renders only `text`, `line`, `shape`, `image_slot`, `kpi`; every other kind (`table`, `chart_placeholder`, future kinds) fails closed on that slide | SVG render | workspace (tempfixture) |
| `svg.generator.tokens` — generator fails closed on an unknown palette key or an unknown typography role; resolved palette values must match `^#[0-9A-Fa-f]{6}$` and `font_family` must match the CSS fallback chain pattern. The background `<rect>` routes `palette.background` through the same resolver (no direct dict bypass) | SVG render | workspace (tempfixture) |
| `svg.generator.image_safety` — generator fails closed when an `image_slot`'s manifest `local_path` does not pass `local_path_is_safe` | SVG render | workspace (tempfixture) |
| `svg.generator.preflight` — BEFORE the `svg_previews/*.svg` cleanup sweep, the generator schema-validates `design_system.json` and `image_manifest.json` and runs `local_path_is_safe` over every declared manifest `local_path`. Any preflight failure exits non-zero, prints no `OK:`, and **does not delete any** pre-existing `svg_previews/*.svg` | SVG render | workspace (tempfixture) |
| `svg.generator.stale_cleanup` — before generating, the script removes every `svg_previews/*.svg`. The `*.svg` namespace is generator-owned. Non-SVG files (READMEs, `.md` / `.txt` notes) are preserved | SVG render | workspace (tempfixture) |
| `svg.fonts` — fonts are declared and resolvable | SVG validate | TODO |
| `svg.density` — density is within threshold | SVG validate | TODO |
| `svg.editable` — every text run is a real text node | SVG validate | TODO |
| `pptx.export.scope` — `scripts/export_pptx.py` writes one native editable `.pptx` from a workspace's `render_models/*.json` for the supported subset only: layouts `cover` / `kpi_dashboard`; primitive kinds `text` / `line` / `shape` / `image_slot` / `kpi`. The contract is all-or-nothing: a render_model whose layout is outside the supported set, an unsupported primitive (`table`, `chart_placeholder`), wrong output extension, malformed render_model, undeclared image_ref, or unsafe manifest path all fail closed with a per-slide error, abort the whole run, and write no partial `.pptx` | PPTX export | implemented for the supported subset (exporter `scripts/export_pptx.py`; self-test exercises every fail-closed gate plus a positive that re-checks the produced `.pptx` against the validator) |
| `pptx.contract.skeleton` — `scripts/validate_pptx_contract.py` reports the PPTX contract / TODO surface (skeleton mode) and, when `--pptx <path>` is supplied, runs the basic OOXML container checks: file exists, `.pptx` extension, readable ZIP, and required package entries (`[Content_Types].xml`, `_rels/.rels`, `ppt/presentation.xml`) | PPTX export | implemented (container checks only — not the editability / relationship / media gates below) |
| `pptx.minimal_evidence.editable_text` — at least one slide carries a `<p:txBody>` with a non-empty `<a:t>` run. **Minimal evidence only**: not a full editability inventory | PPTX export | implemented (`scripts/validate_pptx_contract.py --pptx`) |
| `pptx.minimal_evidence.not_all_image_slide` — every slide that carries a `<p:pic>` also carries at least one `<p:sp>` or `<p:cxnSp>`. **Minimal evidence only**: rules out the obvious one-big-PNG failure mode | PPTX export | implemented (`scripts/validate_pptx_contract.py --pptx`) |
| `pptx.minimal_evidence.no_blank_slide` — every slide carries at least one structural element (`<p:sp>`, `<p:cxnSp>`, or `<p:pic>`); a slide with an empty `<p:spTree>` fails closed. **Minimal evidence only**: paired with `pptx.minimal_evidence.not_all_image_slide`, the two together close the loophole where a deck mixes an editable slide with a blank one (which would otherwise pass `editable_text` and `not_all_image_slide` individually) | PPTX export | implemented (`scripts/validate_pptx_contract.py --pptx`) |
| `pptx.slide_count.inspectable` — the validator can count `ppt/slides/slide{N}.xml` parts; zero slide parts is a FAIL | PPTX export | implemented (`scripts/validate_pptx_contract.py --pptx`) |
| `pptx.relationships.no_external` — no `Relationship` element has `TargetMode="External"`, and no `Target` matches a URI scheme | PPTX export | implemented (`scripts/validate_pptx_contract.py --pptx`) |
| `pptx.relationships.no_file_uri` — no `Relationship` `Target` starts with `file://` | PPTX export | implemented (`scripts/validate_pptx_contract.py --pptx`) |
| `pptx.package.no_macros` — no `ppt/vbaProject.bin` part and no `vbaProject` content type | PPTX export | implemented (`scripts/validate_pptx_contract.py --pptx`) |
| `pptx.package.no_ole` — no part under `ppt/embeddings/` and no `oleObject` content type | PPTX export | implemented (`scripts/validate_pptx_contract.py --pptx`) |
| `pptx.package.no_activex` — no part under `ppt/activeX/` and no `activeX` content type | PPTX export | implemented (`scripts/validate_pptx_contract.py --pptx`) |
| `pptx.editability.full_inventory` — every text body on every slide is a real text frame (full inventory; `pptx.minimal_evidence.editable_text` is a positive-existence check only) | PPTX export | TODO |
| `pptx.no_image_only_slides.full_inventory` — every slide is positively confirmed to contain editable shapes (full inventory; `pptx.minimal_evidence.not_all_image_slide` + `pptx.minimal_evidence.no_blank_slide` rule out the all-image and blank-slide failure modes only) | PPTX export | TODO |
| `pptx.relationships.allow_list` — only allow-listed relationship types appear in the package | PPTX export | TODO |
| `pptx.media.embedded_only` — every media item is embedded inside the package; no remote refs | PPTX export | TODO |
| `pptx.media.inventory` — every media item exists inside the package and no slide carries a dangling ref | PPTX export | TODO |
| `pptx.theme.palette_mapping` — `design_system` palette resolves to the matching PPTX theme slots | PPTX export | TODO |
| `pptx.determinism` — stable IDs, relationship order, and media filenames across runs | PPTX export | TODO (the exporter uses a fixed ZIP timestamp and deterministic ids today; the validator does not yet inspect them) |
| `pptx.layouts.scope` — exported slides use only `cover` / `kpi_dashboard` layouts | PPTX export | exporter-enforced today; validator-side check is TODO |
| `pptx.primitives.scope` — exported shapes map only to the supported five primitive kinds (`table` and `chart_placeholder` fail closed) | PPTX export | exporter-enforced today; validator-side check is TODO |
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
