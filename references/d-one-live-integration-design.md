# D-One Live Integration Design

This document is the **design** for a future real D-One integration. It is
**not** an implementation, an approval, or a green-light. Nothing in this
repo today calls D-One, MCP, a model API, an image-search endpoint, or any
external service; the live path remains intentionally unwired.

This file is a companion to `references/d-one-image-policy.md`. The policy
file states the rules; this file states **how** a future real generator
must plug into the existing local pipeline if and when it ships. It does
not relax any policy gate.

## 1. Current status

- **Mock / local path:** verified. `scripts/done_image_adapter.py` writes
  a deterministic dry-run plan; `scripts/run_d_one_generation.py` emits
  local PNG / JPG / JPEG bytes from `--fixtures-dir` or
  `--allow-synthetic-bytes`; `scripts/materialize_image_assets.py`
  enforces magic-byte and path-safety gates; `scripts/export_pptx.py`
  embeds the resulting bytes as native `<p:pic>` shapes. Self-tests and
  acceptance smokes cover this path.
- **Real D-One path:** NOT verified, NOT implemented. There is no live
  flag on `run_d_one_generation.py`, no MCP wiring, no model-API client,
  no network call. This document does not change that.

Anyone reading this file should treat real D-One integration as a future
phase that requires: (a) explicit written approval, (b) a separate
security review, and (c) updated references / status text in `SKILL.md`
and `README.md`. None of those exist today.

## 2. Pipeline anchor

A real D-One integration MUST plug into the existing three-script local
boundary without changing any other stage. The data flow is fixed:

```
image_manifest.json (Stage 6 artifact)
         │
         ▼
scripts/done_image_adapter.py        (writes d_one_adapter_plan.json — dry-run plan;
   --workspace WS --spec spec.json    no D-One call; deterministic; schema-locked)
         │
         ▼
d_one_adapter_plan.json              (schemas/d_one_adapter_plan.schema.json)
         │
         ▼
scripts/run_d_one_generation.py      (CURRENT: mockable runner; emits <id>.<ext> bytes
   --workspace WS --plan PLAN          from --fixtures-dir or --allow-synthetic-bytes.
   --assets-dir DIR                    FUTURE: a real-D-One provider would replace the
   (mock provider)                     mock providers and produce the same <id>.<ext>
                                       bytes into the same --assets-dir, with NO
                                       changes to the upstream plan or downstream gate.)
         │
         ▼
scripts/materialize_image_assets.py  (copies the <id>.<ext> bytes into the workspace at
   --workspace WS --assets-dir DIR     <workspace>/<images[].local_path>, OR verifies
                                       them in place; magic-byte gate, path-safety gate,
                                       symlink refusal, undeclared-file refusal.)
         │
         ▼
scripts/export_pptx.py               (embeds PNG / JPG / JPEG bytes as native <p:pic>;
   --workspace WS --output OUT.pptx    every other extension still falls back to the
                                       placeholder shape today.)
```

Design constraints for the live integration:

- The plan file format does NOT change. `schemas/d_one_adapter_plan.schema.json`
  remains the contract. A real generator consumes the same plan a mock
  generator consumes today.
- The output naming convention does NOT change. The live provider writes
  flat `<id>.<ext>` files at the root of `--assets-dir`, exactly the layout
  `materialize_image_assets.py` consumes.
- The downstream materialize and export gates are NOT relaxed. Real
  generator bytes are subject to the same magic-byte, path-safety,
  symlink, undeclared-file, and embed-cap gates that gate any other local
  asset today.
- The adapter stub (`done_image_adapter.py`) is NOT bypassed. Even a real
  generator MUST consume a plan the adapter produced, so every prompt has
  already been through the safety scan and the post-write schema gate.

A live provider that wants to short-circuit any of these boundaries is
out of scope for this design and would require a fresh policy review.

## 3. Allowed inputs

The adapter plan is the live provider's complete view of the world. A
live D-One call may receive ONLY:

- One `d_one_adapter_plan.json` request entry at a time. The request
  carries: `id` (string), `prompt` (string already scrubbed by the
  adapter's deny list), optional `intended_use` (string, scrubbed),
  optional `width_px` / `height_px` (positive integers),
  `manifest_local_path` (workspace-relative path, safe), and
  `manifest_source` locked to `"d_one_local"`.

That is the full input surface. Any design-system token, palette swatch,
font-family name, slot dimension, or aspect-ratio hint the model needs
must already be encoded inside the plan request — either folded into the
`prompt` string at spec-authoring time (by the upstream assembly logic
described in §5) or carried verbatim by the existing `width_px` /
`height_px` / `intended_use` fields. The live provider MUST NOT receive
any additional field, sidecar, context object, environment variable
carrying business data, or runtime lookup.

In particular the live provider MUST NOT open `input/source.md`,
`deck_brief.json`, `deck_plan.json`, `design_system.json`, any
slide_plan, any render_model, any SVG preview, or any other repo
artifact at call time. If the model needs information that is not
already in the plan request, the answer is that the upstream spec
author must fold it into the prompt (and re-pass the adapter's deny-list
scan) — not that the live provider reaches into another file.

## 4. Forbidden inputs

The live provider MUST refuse — at its own input boundary, defense in
depth — any prompt or context that contains:

- raw `input/source.md` text, in whole or in part (the adapter already
  refuses 40-char shingles of the source body, but the live provider
  re-applies the same scan on the bytes it is about to send);
- any URI scheme (`http://`, `https://`, `file://`, `data:`, `mailto:`,
  `s3:`, `ftp:`, `javascript:`, `magnet:`, `tel:`, `sms:`, single-char
  schemes, or any other RFC 3986 scheme shape);
- any filesystem path (absolute POSIX, Windows drive letter, UNC,
  `~/` home shortcut, `..` traversal);
- credential shapes (JWT, AWS access keys, PEM markers, long hex blobs,
  bearer tokens, `password:` / `secret:` / `api_key:` / `token:` /
  `client_secret:` / `private_key:` literals);
- personal / customer / account identifiers (email addresses, phone
  numbers, SSN-like strings, UUIDs, `customer_id` / `account_id` /
  `cust_id` / `user_id` literals);
- full-slide / page-generation / screenshot wording (`full slide`,
  `whole slide`, `slide background`, `page background`, `screenshot`,
  `render the slide`, `generate the slide`, and the rest of the existing
  full-slide deny list in `scripts/done_image_adapter.py`);
- public upload / share / hosting wording (`upload to public`,
  `public upload`, `share publicly`, `public hosting`, `publish to web`,
  `public url`, `public link`, `public cdn`, `host on a public`,
  `host publicly`, and the rest of the existing public-distribution
  deny list in `scripts/done_image_adapter.py`);
- any reference to an external customer name, internal product
  codename, partner name, deal name, account name, or unreleased
  feature codename;
- any file attachment, binary blob, or non-text payload.

The live provider's input boundary is the second line of defense. The
adapter already refused these shapes at the plan-write stage; a live
provider that finds them on its input must treat that as evidence of a
contract drift, log the rejection to the audit channel (see §8), and
abort the run.

## 5. Prompt redaction rules

Every prompt sent to a live D-One call MUST satisfy all of the following:

- assembled UPSTREAM, at spec-authoring time (before the adapter scans
  it), from the slide_plan + design_system + approved descriptor
  vocabulary, and folded into the `prompt` string of the spec request
  the adapter consumes (TODO — vocabulary not yet defined; the adapter
  ships no vocabulary today, the live provider MUST NOT invent one, and
  the live provider MUST NOT pull descriptors out of any repo artifact
  at call time — see §3);
- composed of abstracted descriptors only — colors named by token,
  shapes named by geometric noun, moods named by adjective. No proper
  nouns, no quoted source text, no source-derived sentences;
- passes the adapter's full deny list (§4) AND a re-scan immediately
  before the live call (defense in depth — the adapter's scan ran at
  plan-write time; the live provider re-runs the same scan against the
  prompt bytes it is about to ship);
- recorded verbatim in the `d_one_adapter_plan.json` request entry that
  the adapter produced. The live provider MUST NOT mutate the prompt
  between plan and call. A live call whose prompt does not byte-match
  the plan entry is a fail-closed condition (see §7).

The redaction discipline is symmetric to what `done_image_adapter.py`
already enforces on the caller. The live provider does not relax it; it
re-applies it.

## 6. Output directory rules (live provider image bytes)

The rules in this section govern the **live provider's image-byte
outputs**. The audit record is the runner's responsibility, on a
separate channel; see §8.

The live provider's image-byte outputs MUST land in `--assets-dir` only,
with the following discipline:

- one regular non-symlink file per request, named `<id>.<ext>` where
  `<id>` matches the plan request's `id` and `<ext>` is the lower-cased
  extension of the plan request's `manifest_local_path`;
- `<ext>` is restricted to `.png` / `.jpg` / `.jpeg` — the embed surface
  `scripts/export_pptx.py` supports today. SVG / GIF / WebP / TIFF /
  any other extension MUST be refused at the provider boundary because
  the downstream exporter would fall back to the placeholder shape;
- the file's first bytes match the magic-byte signature for the declared
  extension (PNG header `89 50 4E 47 0D 0A 1A 0A`; JPEG header
  `FF D8 FF`). A magic mismatch is a fail-closed condition (`materialize`
  re-checks this anyway, but the live provider catches the corruption
  one hop earlier);
- no subdirectories under `--assets-dir`; the contract is flat;
- no symlinks anywhere on the output path (workspace, assets-dir, target,
  parent segments);
- no live-provider writes outside `--assets-dir`. The live provider MUST
  NOT write into `<workspace>`, `<workspace>/ppt/media/`, `/tmp`, the
  home directory, or any other location. `scripts/materialize_image_assets.py`
  is the only path through which image bytes enter the workspace.

The runner's audit-record write (§8) is a separate, runner-owned channel
governed by its own safety gates. It is NOT a live-provider output and
is NOT covered by the rules above. There is no other scratch-directory
escape hatch today — every byte the live provider writes lands inside
`--assets-dir` and nowhere else. Adding any future intermediate live-
provider write path requires a separate design proposal (see §13).

## 7. Fail-closed conditions

The live D-One integration MUST abort the run, leave the workspace
and the assets-dir byte-identical to their pre-call state, write an
audit record at `--audit-out` documenting the failure (per §8), and
exit non-zero on any of the following:

- the plan file does not pass `done_image_adapter.validate_plan_file`
  (re-run defense in depth — `run_d_one_generation.py` already does
  this);
- any prompt fails the live re-scan (§5);
- the live provider's network or service call fails (timeout, transport
  error, authentication failure, quota exhausted, model unavailable);
- the live provider returns an output extension outside
  `.png` / `.jpg` / `.jpeg`;
- a returned blob's magic bytes do not match the declared extension;
- a returned blob exceeds the 10 MiB embed cap `scripts/export_pptx.py`
  enforces today;
- any image-byte output target pre-exists in `--assets-dir` (no
  overwrite — the caller must remove prior bytes; the `--audit-out`
  path has its own no-overwrite gate, listed in §8);
- a symlink appears anywhere on the workspace / assets-dir / plan /
  output path;
- a mid-run failure leaves partial image bytes on disk (the rollback
  removes every image-byte output the live provider wrote in this run
  from `--assets-dir`, matching the rollback contract
  `materialize_image_assets.py` and `run_d_one_generation.py` already
  implement). The audit record at `--audit-out` is the deliberate
  exception to rollback: per §8, every live run — including a failed
  one — produces an audit record describing what was attempted, what
  was rejected or errored, and what was rolled back. The audit write
  is sequenced AFTER the image-byte rollback so it can describe the
  final state truthfully;
- the live provider attempts to call any endpoint, model, or service
  that is not on the approved live-D-One endpoint list (TODO — list
  not yet defined; until it is defined, every endpoint is unapproved
  and the live path stays unwired);
- the live provider tries to write outside `--assets-dir` (the runner's
  audit-record write described in §8 is the runner's responsibility on
  a separate caller-supplied path, not the live provider's, and does
  not count as a live-provider write).

The fail-closed contract is non-negotiable. A partial deck, a partial
asset directory, or a partial workspace is never an acceptable outcome.

## 8. Audit evidence

Every live D-One run — success OR failure — MUST produce, on local
disk only, a self-describing audit record sufficient to answer "what
was sent, what came back, what was written, what was rejected, what
was rolled back" without re-running the call. The audit record is
written by `scripts/run_d_one_generation.py` in live mode, NOT by the
live provider itself — §6 binds the live provider's image-byte outputs
to `--assets-dir`, and the audit-record write is the runner's own,
separately-flagged responsibility. On a failed run the audit is the
ONE artifact that survives the §7 rollback: image bytes in
`--assets-dir` are removed; the audit at `--audit-out` is written to
document the failure (a destroyed audit would defeat the audit's
purpose). Suggested shape (TODO — schema not yet defined):

- the input `d_one_adapter_plan.json` byte hash (so the audit pins down
  the exact plan the live provider consumed);
- per-request: `id`, `prompt` byte hash, `intended_use` byte hash,
  declared dimensions, declared `manifest_local_path`,
  declared `manifest_source`;
- per-request live outcome: `ok` / `rejected` / `error`, the rejection
  reason if any, the live endpoint identifier (opaque label, not a
  URL — the URL goes in the approved-endpoint list, not the audit),
  the elapsed time, the output byte length, the output magic-byte
  signature, the output sha256;
- the resulting `<assets-dir>/<id>.<ext>` byte hash (so a later
  `materialize_image_assets.py` run can prove the bytes it copied are
  the bytes the live provider produced).

The audit record:

- lands at the caller-supplied `--audit-out` path on
  `scripts/run_d_one_generation.py` (TODO — flag not yet added; until
  it is added, the live run produces no audit and the live path stays
  unwired). The path is symlink-refused, parent-symlink-refused,
  passes `local_path_is_safe`, MUST NOT pre-exist (no overwrite), and
  is written deterministically AT RUN COMPLETION — whether the run
  succeeded, was partially rejected, errored mid-way, or was fully
  rolled back. It does NOT live inside `--assets-dir` (that directory
  carries flat `<id>.<ext>` image bytes only — see §6) and the live
  provider does NOT write to it;
- must NOT contain raw source text, raw prompt text, raw output bytes,
  customer identifiers, or credentials;
- must NOT contain absolute paths, URLs, or `file://` references;
- must be deterministic given the same inputs and live outcomes;
- is subject to the same schema-validation discipline every other
  artifact in this repo follows.

The audit record is local-only. It MUST NOT be uploaded, posted,
emailed, or otherwise transmitted off the host. Sharing an audit record
is a separate explicit human action, not part of the runner.

## 9. Manual approval boundaries

The live D-One integration crosses several boundaries that the
mock / local path does not. Each boundary requires an explicit, written,
human approval before the corresponding code can ship:

1. **Endpoint approval.** Every live endpoint the provider may call
   must appear on a maintained allow-list. Adding an endpoint requires
   a security-review sign-off and a corresponding update to this
   document. Until the list exists, every endpoint is unapproved.
2. **Vocabulary approval.** The descriptor vocabulary used to assemble
   prompts (§5) must be reviewed and approved before the live path
   ships. An unapproved vocabulary means an unapproved prompt surface.
3. **Per-deck approval.** Each deck whose images are generated via the
   live path must be approved at the deck level (not implicit per
   request). The mock path is unrestricted; the live path is not.
4. **Per-image manual review.** Every live-generated image must be
   reviewed by a human before it is embedded. The review confirms:
   (a) the image is a supporting illustration, not a full slide;
   (b) the image carries no text that should be editable;
   (c) the image contains no identifiable customer / partner / product
   reference; (d) the image is on-brand. The review record is part of
   the audit evidence (§8).
5. **Cleanup approval.** A live-generated image that fails review must
   be removed from the workspace; the run is rolled back to the
   pre-call state. There is no "ship it anyway" path.
6. **Disable switch.** A configuration toggle must let an operator
   disable the live path globally, in which case the runner falls back
   to mock-only mode (`--fixtures-dir` or `--allow-synthetic-bytes`).
   The default ships disabled.

No code path may bypass these boundaries. A bypass — even a debug-only
one — is itself a policy violation.

## 10. What real D-One MUST NOT change

The live integration is narrow. It MUST NOT, as a side effect:

- change `schemas/d_one_adapter_plan.schema.json`,
  `schemas/image_manifest.schema.json`, or any other repo schema;
- change `scripts/export_pptx.py` embed behavior (PNG / JPG / JPEG
  remains the embed surface; SVG / GIF / WebP remain TODO);
- introduce a full-slide raster path, a screenshot path, a chart path,
  or a text-bearing-image path;
- introduce telemetry, analytics, crash reporting, public scraping,
  public image search, or any other public-network call beyond the
  approved D-One endpoint list;
- introduce a Qoder runtime call, an MCP call beyond the approved
  D-One channel, an OpenAI / Anthropic / other model-API call, or any
  third-party SDK;
- introduce a real-data example, a real customer fixture, a real
  credential, an internal screenshot, or sensitive report text;
- read `input/source.md` for content (the adapter's 40-char shingle
  scan reads raw bytes only and discards the decoded string after
  scanning; the live provider does NOT open the file at all);
- mutate `image_manifest.json`, `deck_brief.json`, `deck_plan.json`,
  `design_system.json`, any slide_plan, any render_model, or any SVG
  preview;
- mutate the d_one_adapter_plan.json the adapter produced (the plan is
  the live provider's read-only input);
- emit live-provider bytes anywhere other than `--assets-dir`. The
  runner's audit-record write to a caller-supplied `--audit-out` path
  described in §8 is the single additional local artifact the real-
  D-One commit may introduce; it is the runner's responsibility (not
  the live provider's) and is governed by §8's own safety gates.

If a real-D-One change request touches any of the above, it is out of
scope for this design and requires a separate proposal.

## 11. Verification before going live

Before a real-D-One commit lands, the following must all pass on the
unchanged mock path AND on the proposed live path, with the live path
running against a sandboxed approved endpoint (not production):

- `python3 scripts/done_image_adapter.py --self-test`
- `python3 scripts/done_image_adapter.py --validate-plan` against the
  produced plan
- `python3 scripts/run_d_one_generation.py --self-test` (mock providers
  still pass; the new live provider has its own self-test scenarios)
- `python3 scripts/materialize_image_assets.py --self-test`
- `python3 scripts/export_pptx.py` against the resulting workspace,
  followed by `python3 scripts/validate_pptx_contract.py` (no external
  rels, no `file://`, no macros / OLE / ActiveX, embedded media inside
  the allow-list, every slide carries native editable shapes)
- `python3 scripts/verify_skill_package.py` (no credential shapes
  introduced, no external URLs introduced, every doc reference still
  resolves)
- `python3 scripts/package_skill.py --self-test`
- `python3 scripts/acceptance_smoke.py --self-test`
- `python3 scripts/image_asset_acceptance_smoke.py --self-test`
- the audit record (§8) round-trips through its own schema validator
- a human reviewer signs off on every per-image manual review (§9)

A run in which any of these gates fails is not a live-D-One run.

## 12. Cross-references

- `references/d-one-image-policy.md` — the broader policy these design
  rules sit inside (including the "Forbidden use" rules a live provider
  MUST respect at its own boundary). This file does not override that
  one.
- `references/security-policy.md` — the fail-closed checks the security
  scan applies to every artifact, including live-D-One outputs.
- `references/clean-room-policy.md` — the clean-room constraint that
  forbids copying anything from an external reference implementation
  into the live integration.
- `scripts/done_image_adapter.py` — the adapter contract STUB the live
  provider consumes.
- `scripts/run_d_one_generation.py` — the runner whose mock providers a
  live provider would replace (the script's CLI surface and downstream
  contract are the design surface, not the providers).
- `scripts/materialize_image_assets.py` — the gate every live output
  passes through before it enters the workspace.

## 13. TODOs (blockers before any live work)

These are gating: the live path stays unwired until each is resolved
under a separate explicit user request, with its own review.

- Define the approved live-D-One endpoint allow-list.
- Define the approved descriptor vocabulary used to assemble prompts.
- Define the audit-record schema (§8) and the validator that enforces
  it.
- Define the `--audit-out` flag on `scripts/run_d_one_generation.py`
  and its safety gates (symlink refusal, parent-symlink refusal,
  `local_path_is_safe`, no-overwrite, deterministic write). Until this
  exists, no audit-write code exists and the live run produces no
  audit record.
- Define the per-image manual-review record format and where it lives.
- Define the global disable switch and its default-off ergonomics.
- Decide whether live-generated bytes are cached across runs or
  regenerated each time (caching has audit and rollback implications).
- Decide whether the live path supports SVG output once SVG embedding
  is added to `scripts/export_pptx.py` (today SVG falls back to the
  placeholder shape, so SVG output from the live path would be
  misleading).
- Decide whether any intermediate scratch directory is ever needed; if
  so, define its safety rules (path-safety, symlink refusal, no writes
  outside, rollback semantics) in a separate design proposal. Today
  there is no scratch path — §6 forbids writes outside `--assets-dir`.
- Re-evaluate every section of this document before the live commit
  lands; a design written ahead of implementation is a draft, not a
  contract.
