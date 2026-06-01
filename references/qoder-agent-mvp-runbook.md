# Qoder-agent MVP runbook: local source → internal images → editable PPT

Internal-only, clean-room. This is the runbook a **Qoder agent** follows to
drive the MVP flow once the `editable-ppt` skill is loaded on a company
machine and an operator opens a business folder. It is written to be run
**without chat history**: everything the agent needs is here plus the
documented commands it cites.

It complements, and does not duplicate, [`qoder-import-checklist.md`](qoder-import-checklist.md),
which covers *installing / registering the packaged skill archive* on a Qoder
machine. This runbook starts **after** the skill is available.

This doc documents existing behavior. It does **not** add or change any
runtime behavior, and it wires **no** Python D-One client, MCP runtime, model
API, or network call.

## The one boundary an agent must internalize

- The repo's Python scripts **never call D-One, never auto-detect an MCP
  server, and never make a public-network / model-API call.**
  `scripts/run_mvp_image_to_ppt.py` only (a) writes an image-generation
  *packet* from a local source and (b) later *resumes* from returned local
  image files. Nothing in the repo synthesises pixels.
- **The agent never prompts D-One (or any image generator) from this packet /
  resume path.** That path has **no prompt-audit gate**, and
  [`d-one-image-policy.md`](d-one-image-policy.md) requires every prompt sent to
  a generator to be deny-list-validated **and** logged for audit. So image
  creation here is a **human / approved-internal-generator handoff**: a person
  or an internal tool (operated under its own controls) produces the images and
  returns the files; the agent only writes the packet and resumes from those
  files. The repo gains no D-One client.
- **Agent-driven automated generation is a separate entrypoint** — the repo's
  audited workspace pipeline (`scripts/done_image_adapter.py` →
  `scripts/run_d_one_generation.py` → `scripts/materialize_image_assets.py`),
  where `done_image_adapter` validates every prompt against the deny-list and
  logs it. It builds its **own** deck and does **not** fill this packet or feed
  `--resume`; choose it *instead of* this MVP flow, never from this packet path.
  Real D-One remains **UNVERIFIED / out of scope**.
- If no human / internal generator is available to fill the packet, the agent
  **stops at the packet and reports the packet path.** It must **not**
  substitute a public image generator, a public-network call, an unapproved
  model API, public image search, or telemetry. Manual / internal image return
  is always a valid path.

## Workflow

Preconditions: the `editable-ppt` skill is loaded; `python3` is available
(standard library only — no `pip install`); the operator has pointed the
agent at a business folder. Run every command from the repo root.

### 1. Find the source

Look for exactly one local `.docx` / `.md` / `.markdown` / `.txt` file in the
business folder.

- Zero candidates, or more than one and the intended file is ambiguous →
  **ask the operator** which file to use (or to add one) before proceeding.
- A `.pdf` is a documented TODO — refuse it with that note rather than trying
  to parse it.
- Do not fetch a remote document or pull anything off the network; the source
  must already be a local file.

### 2. Choose an output directory `OUT`

Pick an output directory **outside the repo tree** (e.g. under `/tmp`). It
must be **missing or empty**, not URI-shaped, and not a symlink; its parent
must exist. This is the same `--out-dir` gate the wrapper enforces, so a stale
non-empty directory is refused — remove it first if you are re-running.

### 3. First run — source → generation packet

```bash
python3 scripts/run_mvp_image_to_ppt.py --source SOURCE --out-dir OUT
```

This writes the packet under `OUT/generation_packet/` and prints the exact
next steps (where to drop returned images and the `--resume OUT` command).
`.md` / `.markdown` feed the bridge directly; `.docx` / `.txt` are normalised
to `OUT/normalized_source.md` first.

### 4. Read the packet

Open `OUT/generation_packet/image_generation_requests.md`. It lists **one
image request per source heading**, each carrying the **exact return
filename**, `slide_title`, `alt_text`, `intended_use`, `image_descriptor`, and
`placement_role`. `OUT/generation_packet/expected_images/README.md` names
every required return filename.

### 5. Fill the images — a human / internal handoff (the agent never prompts a generator here)

**The agent must never send a prompt to D-One (or any image generator) from
the generation-packet path.** That path runs **no prompt-audit gate**, so
prompting a model from it would bypass the mandatory deny-list + audit log that
[`d-one-image-policy.md`](d-one-image-policy.md) requires for **every** prompt
sent to a generator.

`OUT/generation_packet/expected_images/` is therefore filled by a **human /
approved-internal-generator handoff**: hand `image_generation_requests.md` to a
person, or to an approved internal image generator operated under its own
controls, who creates each image and returns the files. The agent's automated
role is **packet production + resume only** — it does **not** programmatically
prompt a model, so there is no audit gate to bypass. A human reading the
heading-bearing brief is fine; they already hold the source. This is the **only**
way to fill `expected_images/` for the resume step.

Every image must be a **TEXT-FREE abstract spot illustration** (no text /
lettering / numbers / logos / watermarks) — a local decorative asset, never a
full-slide background and never a substitute for editable text. No prompt may
ever carry the packet's heading-bearing `slide_title` / `alt_text` /
`image_descriptor` (they embed the raw source heading), source body, customer /
account names, or credentials.

Save each returned image as a **real PNG** under its **exact** requested
filename into `OUT/generation_packet/expected_images/` — every requested
filename ends in `.png`, the resume step (step 6) verifies the bytes against the
extension with a magic-byte gate, and you must not rename a file or change its
extension. (The packet's own `expected_images/README.md` states this same PNG
contract.)

> **Want the agent to drive image generation automatically instead?** That is a
> **separate entrypoint — not this packet / resume flow, and not a way to fill
> `expected_images/`.** Use the repo's audited workspace pipeline
> (`scripts/done_image_adapter.py` → `scripts/run_d_one_generation.py` →
> `scripts/materialize_image_assets.py`), where `done_image_adapter`
> deny-list-validates and logs every prompt and `run_d_one_generation` produces
> the pixels (mock today — real D-One remains **UNVERIFIED / out of scope**). It
> builds its **own** deck and does **not** feed this packet or `--resume`, so
> choose it *instead of* this MVP flow, never as a step within it.

**If no human / internal generator is available to fill the packet:**

- **Stop.** Report the packet path (`OUT/generation_packet/`) and that a human
  or an approved internal generator must fill `expected_images/` before the
  resume step.
- Do **not** use a public image generator, public-network call, unapproved
  model API, public image search, or telemetry to synthesise the images.

### 6. Resume run — packet + returned images → editable deck

```bash
python3 scripts/run_mvp_image_to_ppt.py --resume OUT
```

Pass `OUT` as the value of `--resume`; do **not** also pass `--out-dir`. The
resume run checks the returned images against the plan **1:1** (exact
filenames, valid PNG bytes matching each requested `.png` name via a magic-byte
gate, no symlinks / extras / missing — failing closed with an actionable
message), builds the editable deck, and re-validates it. The deck lands at
`OUT/review/review_package/deck.pptx`.

### 7. Validate the review package

```bash
python3 scripts/validate_operator_review_package.py --out-dir OUT/review/review_package
```

This is a read-only re-check of the produced package.

### 8. Report

Tell the operator:

- the editable deck: `OUT/review/review_package/deck.pptx`
- the summary: `OUT/review/review_package/summary.json`
- one line on the validation result (pass / fail).

## Local-only boundaries (always)

No public network. No public image generation. No unapproved model API. No
public image search. No telemetry. No raw source / customer / account /
credential content in any image prompt. No full-slide screenshots. No broad
`ppt-master` parity. Images are local files only.

## When to stop or ask

- Missing or ambiguous source → ask the operator (step 1).
- No human / internal generator available to fill the packet → stop at the
  packet and report the path (step 5); manual / internal image return is still
  valid.
- A returned image missing / misnamed / non-image / unsafe → the resume step
  fails closed; relay the message and fix the filenames in
  `expected_images/`. Do not bypass the check.
- Any prompt to send data to a public service, attach credentials, enable
  telemetry, or make a public-network / public-model-API / public-image-search
  call → **stop**. The agent never prompts a generator from this packet path;
  the *only* agent-driven generation permitted is the separate audited
  workspace pipeline (every prompt deny-list-validated and logged — see the
  note at the end of step 5), which does not fill this packet. Everything else
  stays a hard stop.

The stop conditions in [`qoder-import-checklist.md`](qoder-import-checklist.md)
govern *archive import / registration verification*, where the runtime smoke is
mock-only by design, so **any** D-One / MCP / model-API call there is a stop —
you are confirming the package loads, not producing a deck. This runbook governs
the *operational MVP run*, where the packet / resume path likewise issues **no**
generator prompts and agent-driven generation is confined to the audited
pipeline. Every stop the checklist lists — public network, credentials,
telemetry, public model API, public image search, public upload, writing
outside the declared output directory — applies to operational runs too.

## Optional proof with no generator

To prove the whole documented flow end to end on one machine without any image
generator, run the dry-run gate. It drives the documented commands as
subprocesses, writes placeholder pixels for you, and fails if the deck is
missing, if validation refuses the result, or if the run leaves any artifact
in the repo:

```bash
python3 scripts/mvp_company_machine_dry_run.py --self-test
```

## Pointers

- Operator copy-paste walkthrough (bundled demo source): [`mvp-quickstart.md`](mvp-quickstart.md)
- MVP scope and non-goals: [`mvp-ddl-sprint-plan.md`](mvp-ddl-sprint-plan.md)
- D-One image policy (prompt safety, local-asset-only): [`d-one-image-policy.md`](d-one-image-policy.md)
- Installing the packaged skill on a Qoder machine: [`qoder-import-checklist.md`](qoder-import-checklist.md)
- Lower-level flags behind the wrapper: [`source-to-image-request-bridge.md`](source-to-image-request-bridge.md), [`core-image-to-editable-ppt-quickstart.md`](core-image-to-editable-ppt-quickstart.md)
