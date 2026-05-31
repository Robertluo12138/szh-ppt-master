# MVP DDL Sprint Plan

Purpose: keep every next goal focused on the company-computer MVP for `szh-ppt-master`, not broad `ppt-master` parity.

## North Star

Run on a company machine:

1. Local DOCX / MD / TXT source.
2. Produce an image-generation handoff packet.
3. Human or internal image generator creates the requested images and puts them in the expected folder/names.
4. Resume from that packet and image folder.
5. Produce `review_package/deck.pptx` with editable PowerPoint objects and embedded local images.
6. Validate the review package.

This is the MVP. It is not full `ppt-master`, not full report understanding, and not fully automatic real image generation.

## Hard Non-Goals Until MVP Runs

Do not spend goals on these unless they directly unblock the MVP run:

- Animation.
- SVG editor / visual editor parity.
- Audio / narration / video export.
- Broad template/layout expansion.
- Full PDF support.
- Public web ingestion.
- Real D-One / model API wiring.
- New future-only contracts that do not make the operator flow runnable.
- Large validator/schema expansions for edge cases that can be TODOs.

## DDL Review Standard

In DDL mode, block only for issues that can break the MVP or create real risk:

- The documented command does not run.
- The generated PPTX/review package is missing or invalid.
- Images cannot be handed back into the pipeline.
- Output pollutes the repo or stages generated artifacts.
- A path/symlink/overwrite issue could damage local files.
- Credentials, raw source, public URLs, or sensitive material leak into committed surfaces.
- The change calls D-One, public network, model APIs, MCP, Qoder, telemetry, or image search without explicit approval.
- The operator cannot tell what to do next.

Non-blocking until after MVP:

- Cosmetic wording issues.
- Extra polish in docs.
- Rare format edge cases.
- General upstream parity gaps unrelated to the image-generation path.
- More exhaustive validators when the current happy path is already protected.

## Remaining Goal Sequence

Target: no more than 5 to 6 goal cycles from this point.

### Goal 1: Finish Generation Packet

Status: currently in progress when this file was created.

Acceptance:
- Source/image request plan can produce a packet for image generation.
- Packet contains required filenames, slide titles, alt text, intended use, descriptors, and placement roles.
- Packet is safe to give to a human/internal image generator.
- No real D-One call yet.

### Goal 2: Real Image Return / Resume

Build the smallest command that consumes a filled generation packet plus returned images and produces a validated `review_package/deck.pptx`.

Acceptance:
- Missing image fails with an actionable message.
- Filename mismatch fails with an actionable message.
- A folder with all expected images succeeds.
- Review package validates.

### Goal 3: One MVP Command Surface

Add a single MVP entrypoint (planned — NOT yet implemented), e.g. a
`run_mvp_image_to_ppt` wrapper that fronts the existing lower-level scripts:

```bash
run_mvp_image_to_ppt --source report.docx --out-dir /tmp/szh-mvp
run_mvp_image_to_ppt --resume /tmp/szh-mvp
```

Acceptance:
- First command creates the generation packet and tells the operator where to place images.
- Second command validates returned images and creates the review package.
- Existing lower-level scripts still work.

### Goal 4: Visible Quickstart + Tiny Demo Input

Add a short MVP quickstart and one tiny synthetic demo source.

Acceptance:
- A new user can follow the quickstart without reading old chat history.
- Commands are copy-pasteable.
- It clearly says local/mock/manual image generation only.

### Goal 5: Company-Machine Dry Run Gate

Run or simulate the exact company-machine flow with a real local temp output directory and manually supplied/generated images.

Acceptance:
- Final `review_package/deck.pptx` exists.
- `validate_operator_review_package.py` passes.
- `verify_skill_package.py` and `package_skill.py --self-test` pass.
- No repo pollution.

### Goal 6: Only Fix Real Run Blockers

Use this only if the dry run exposes a practical blocker.

Do not add new feature scope. Fix only what prevents the company-machine MVP run.

## Prompt Rule For Future Agents

Before proposing the next goal, read this file and ask:

1. Does the next goal directly move the MVP command/run forward?
2. Would an operator on a company machine be closer to producing `review_package/deck.pptx`?
3. Is this avoiding broad `ppt-master` parity work?

If the answer is no, do not propose that goal.
