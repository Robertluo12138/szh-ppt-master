# Internal Trial Record — Company-Machine Qoder Link/Runtime Smoke

Internal-only, clean-room. This file is an event record of a verification
trial that was performed **off this development machine**, on a separate
internal "company machine" that has Qoder installed. The development
machine does **not** have Qoder; the company machine is **verification-only**
and cannot push commits back. The GitHub flow into the company machine is
intentionally one-way (development → GitHub → company machine download),
so the evidence below was collected manually on the company machine and
is being recorded here on the development machine for the audit trail.

This document records what was tested and what was deliberately NOT tested.
It does not add runtime behavior, does not modify any script, and does not
rebuild any package. The trial it describes did not exercise real company
data, real D-One, MCP, public network, telemetry, a model API, image
search, or real business PPT generation; see
[What was NOT used](#what-was-not-used) below.

## Trial type

Company-machine **Qoder link/runtime smoke**. The Qoder host on the
company machine was pointed at the locally checked-out skill repo via
Qoder's "link to local repo path" mechanism (link mode), and the
already-shipped local verification scripts were run inside that linked
context. The live **zip install** path (importing the packaged
`dist/szh-ppt-skill.zip` archive on the company machine) was deliberately
out of scope for this trial; see
[What was NOT tested](#what-was-not-tested) below.

## Result

**`LIVE_QODER_RUNTIME_PASS`** — every step described under
[What the company machine ran](#what-the-company-machine-ran) passed.

This result is scoped to:

- a single trial,
- on a single internal company machine,
- in Qoder **link mode** (not zip install),
- against the synthetic authoring trial bundle that ships in this repo,
- against the explicit-input pipeline and self-tests already in this repo.

It is **not** a claim that the live Qoder zip-install path is verified,
not a claim that real D-One / real business-data generation works, and
not a substitute for the verification gates listed in
`references/qoder-import-checklist.md`.

## Package under test (built on the company machine)

- Built on the company machine from the same source tree that was
  downloaded via the one-way GitHub flow.
- Builder: `scripts/package_skill.py` (deterministic; same builder as
  on the development machine).
- Archive SHA-256 (recorded on the company machine immediately after
  the build, against the source state present on the company machine
  **at the time of the trial**):
  `d6d178c607112efa27809b9c203fa6cc414fd4f311a3bf018d021603e1367f83`.
- **The recorded hash is historical evidence of the trial build, not a
  reproduction target.** The company machine ran
  `scripts/package_skill.py` against the specific tracked tree it had
  downloaded via the one-way GitHub flow; the SHA above corresponds
  only to the archive bytes produced from that exact tracked tree.
  The builder is deterministic but **tracked-only** — it materializes
  `git ls-files` intersected with an explicit per-top-level-directory
  allow-list (`references/` is in that allow-list). Any change to the
  tracked source state therefore changes the archive bytes. The
  trial-time tracked tree did not contain
  `references/internal-trial-record.md` — this file is currently
  untracked in the development repo and has not yet been committed,
  pushed, or pulled onto the company machine. The SHA above is
  preserved as audit evidence of the archive bytes the
  company-machine trial actually exercised, not as something to
  reproduce from the current development tree.
- Per the recording protocol in
  `references/qoder-import-checklist.md`, the canonical surface for
  recording a rebuilt archive's SHA-256 is the **gitignored sidecar**
  `dist/szh-ppt-skill.zip.sha256` plus the out-of-tree handoff
  transmission record, **not** any tracked doc — embedding a rebuilt
  archive's hash inside a doc that may itself end up shipping inside
  a future rebuild has no fixed point.
- The on-company-machine path of the archive, the company machine's
  identifier, credentials, internal endpoints, account IDs, and any
  screenshots are intentionally **not** recorded in this document.

## What the company machine ran

### Qoder skill link

Qoder was pointed at the linked local repo and the editable-ppt skill
was enabled.

- Qoder reported the skill as **enabled** and **linked** to the local
  repo path on the company machine.
- The on-disk repo path on the company machine is intentionally **not**
  recorded here.

### Recognition smoke (Qoder self-reporting)

Qoder was asked to describe the skill back. The reported description
matched the source-of-truth properties this repo documents in
`SKILL.md` / `README.md` / `CLAUDE.md`:

- the pipeline is **explicit-input** (Stage-1 through Stage-10 driven
  by caller-supplied JSON specs, not by prose extraction from
  `input/source.md`);
- examples and tests are **synthetic-only**;
- **real D-One is not implemented** — D-One integration is TODO and the
  in-repo runner is a mockable local stub;
- the skill carries a **no network / no MCP / no model API / no image
  search** boundary at runtime.

No mismatch or extra capability was reported.

### Runtime smoke (local stdlib-only scripts)

The following commands were executed on the company machine, under
Qoder-mediated Python execution. All three returned success (exit 0).
The commands themselves are the same commands documented in
`README.md` / `SKILL.md` / `references/qoder-import-checklist.md`:

- `python3 scripts/acceptance_smoke.py --self-test`
- `python3 scripts/image_asset_acceptance_smoke.py --self-test`
- `python3 scripts/verify_skill_package.py`

No additional scripts were run, no script was modified, and no package
was rebuilt as part of running the smoke.

## What was NOT used

None of the following were exercised during this trial:

- real company / customer data, real internal reports, real internal
  templates, or any non-synthetic input;
- real D-One image generation (the only image-byte path exercised is
  the in-repo synthetic-PNG mock under `image_asset_acceptance_smoke.py
  --self-test`);
- any MCP server;
- any public network call;
- any telemetry endpoint;
- any model API (the recognition smoke is Qoder's self-description of
  the linked skill, not a generation call against external content);
- any image-search backend;
- any real business PPT generation against real source content.

## What was NOT tested

- **Live zip install on the company machine.** The Qoder import path
  that consumes `dist/szh-ppt-skill.zip` directly was not exercised in
  this trial; link mode was used instead. The zip-install path
  therefore remains **UNVERIFIED here**, consistent with the existing
  language in `references/qoder-import-checklist.md`.
- Any non-self-test, non-synthetic end-to-end run against real source
  content.
- Any cross-machine determinism comparison between the development
  machine and the company machine beyond the SHA-256 already recorded
  above.

## Approval boundary

Qoder-mediated Python execution on the company machine **required manual
approval** before each command was allowed to run. Approval was granted
**only** for the three commands explicitly listed under
[Runtime smoke](#runtime-smoke-local-stdlib-only-scripts) and for the
build invocation of `scripts/package_skill.py`. No blanket approval was
issued, and no command outside that list was executed.

## Final git state (company machine)

After the trial, `git status` on the company machine reported a clean
working tree (no untracked files, no modifications) against the
downloaded source state. No commits were authored on the company
machine; the company machine is verification-only and cannot push back.

## Provenance and limitations of this record

- The trial occurred on a separate internal company machine. This
  development machine did **not** observe the trial directly.
- The evidence above was collected manually on the company machine and
  recorded here as a single event record. There is no automated
  cross-machine verification log committed to this repo.
- Machine identifiers, the company-machine repo path, screenshots,
  internal endpoints, account IDs, and credentials are intentionally
  not recorded in this document, per the repo's privacy rules
  (`SECURITY.md`, `references/security-policy.md`).
- This record adds a single new file under `references/` and does
  **not** modify any existing in-repo script, schema, template,
  example, or doc. The file is currently untracked in the development
  repo. The package builder is tracked-only (it intersects
  `git ls-files` with a per-top-level-directory allow-list that
  includes `references/`), so the new file does not affect the
  archive surface unless and until it is committed and a rebuild is
  performed against the post-commit tracked tree; that is also why
  the SHA-256 in
  [Package under test](#package-under-test-built-on-the-company-machine)
  is preserved as historical evidence rather than as a reproduction
  target.
- This record does not constitute live-zip-install verification, does
  not introduce any runtime behavior, does not rebuild the package on
  the development machine, and does not supersede the gates
  enumerated in `references/qoder-import-checklist.md`.

## Next gate

Either of the following is a reasonable next step. Neither is in scope
for this record.

- **D-One integration design review.** Drive the D-One integration
  forward against `references/d-one-image-policy.md` (real local
  PNG / JPG / JPEG image-asset materialization, no full-slide
  screenshots, no raw sensitive source text in image prompts).
- **Zip-install smoke on the company machine.** If live import of
  `dist/szh-ppt-skill.zip` (rather than link mode) becomes the gating
  question, run that path on the company machine and record a
  follow-up trial entry against the rebuilt archive's SHA-256.
