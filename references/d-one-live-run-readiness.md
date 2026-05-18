# D-One Live-Run Readiness Checklist

This document is the **readiness checklist** that gates any future real
D-One run. It is a companion to `references/d-one-live-integration-design.md`
(which states *how* a real generator would plug into the existing local
pipeline) and to `references/d-one-image-policy.md` (which states the
broader policy). This file does not relax either of those; it makes the
evidence requirements explicit and enumerable, so a reviewer can answer
"is this live run PASS?" by walking a single list.

Nothing in this repo today calls D-One, MCP, a model API, an image-search
endpoint, or any external service. This checklist does not change that.
Adopting it is **not** a green-light for live work; it is the gate that
live work must pass when, and only when, the prerequisite TODOs in
`references/d-one-live-integration-design.md` §13 are resolved under
separate explicit user requests.

## 1. Status

- **Mock / local path: VERIFIED.** `scripts/done_image_adapter.py`
  (dry-run plan), `scripts/run_d_one_generation.py` (mock providers via
  `--fixtures-dir` or `--allow-synthetic-bytes`),
  `scripts/materialize_image_assets.py` (magic-byte + path-safety gate),
  and `scripts/export_pptx.py` (native `<p:pic>` embed for PNG / JPG /
  JPEG) all ship with `--self-test` coverage. The end-to-end mock path
  is exercised by `scripts/image_asset_acceptance_smoke.py --self-test`.
- **Real D-One path: UNVERIFIED.** There is no live flag, no MCP wiring,
  no model-API client, no network call. No endpoint allow-list exists.
  No descriptor vocabulary exists. No audit-record schema is wired into
  any runtime script. No live run has occurred. A reviewer who reads
  this file and asks "has a real D-One run been PASS'd?" must answer
  "no — there has never been a real D-One run."

The wording above is load-bearing. Any change to it (e.g. flipping a
gate from UNVERIFIED to VERIFIED) requires the corresponding evidence
listed in §8 of this checklist.

## 2. Scope of this checklist

This checklist covers **one live run at a time**: a single invocation of
the future `scripts/run_d_one_generation.py` live mode against an
approved endpoint, consuming exactly one schema-valid
`d_one_adapter_plan.json` and producing exactly one `<audit-out>` record
plus its image bytes under `--assets-dir`. A multi-run campaign (caching,
retries across days, batched approvals) is out of scope and would need
its own readiness review.

The checklist does **not** cover: real D-One implementation work itself
(that is the design doc), the broader D-One image policy (that is
`references/d-one-image-policy.md`), per-image manual review aesthetic
judgment (that is the reviewer's call recorded inside the audit record),
or the deck-level approval business process upstream of any live run.

## 3. Endpoint allow-list requirements

A live run is PASS-eligible only if the endpoint it calls satisfies all
of:

- **R1 — Maintained allow-list file.** The repo carries a single
  allow-list file naming every approved live-D-One endpoint. Until that
  file exists, every endpoint is unapproved and the live path stays
  unwired. The file's location, format, and validator are themselves a
  separate proposal (see `references/d-one-live-integration-design.md`
  §13); this checklist does not invent them.
- **R2 — Per-endpoint entry shape.** Each allow-list entry MUST record:
  an opaque endpoint identifier (the label that appears in audit
  records — see §6 below), the endpoint's network destination, the
  approving reviewer, the approval date (ISO-8601 UTC), the security-
  review sign-off reference, and the explicit scope (sandbox vs.
  production, request types permitted, image-byte size cap if tighter
  than the global 10 MiB embed cap `scripts/export_pptx.py` enforces
  today).
- **R3 — Default deny.** The runner MUST refuse any endpoint not on the
  allow-list at its own boundary. A missing or empty allow-list is
  equivalent to "every endpoint denied" — the runner does not silently
  fall back to a hard-coded default.
- **R4 — Sandbox before production.** The first live run against any
  endpoint MUST occur on a sandbox entry. A production-scoped entry is
  only PASS-eligible after at least one sandbox run on the same endpoint
  shape has produced a PASS audit record (per §8).
- **R5 — No URL ever leaves the allow-list.** Audit records, logs, and
  any other on-disk artifact MUST carry only the opaque endpoint
  identifier (R2), never the network destination. The mapping from
  identifier to destination lives in the allow-list file and nowhere
  else. This keeps the no-external-URL gate
  (`scripts/verify_skill_package.py`) honest across the audit surface.
- **R6 — No network call outside the allow-list.** Telemetry, analytics,
  crash reporting, public scraping, public image search, model-API
  calls beyond the approved endpoint, third-party SDK callbacks, and
  CDN fetches for prompts / fixtures / fonts are all forbidden. The
  runner makes the one approved call and nothing else.

## 4. Descriptor vocabulary

Prompts are assembled UPSTREAM from an approved descriptor vocabulary
(see `references/d-one-live-integration-design.md` §5). A live run is
PASS-eligible only if the vocabulary in force satisfies all of:

- **V1 — Vocabulary file in repo.** The repo carries the approved
  descriptor vocabulary as a tracked file. Until that file exists, every
  descriptor is unapproved and the live path stays unwired. Location,
  format, and validator are a separate proposal.
- **V2 — Abstract descriptors only.** Each entry is one of: a design-
  system color token (referenced by name, never by hex literal pulled
  from a customer palette), a geometric noun (e.g. "circle", "wedge",
  "isometric stack"), a mood adjective (e.g. "calm", "energetic",
  "minimal"), or a composition adjective (e.g. "centered", "off-axis").
  No proper nouns, no product names, no customer names, no quoted
  source text, no source-derived sentences, no dates, no numbers
  pulled from the source body.
- **V3 — Closed enumeration.** The vocabulary is a closed set. The
  prompt assembler MUST refuse a descriptor not in the set; the live
  runner MUST re-check this at its own boundary (defense in depth).
- **V4 — Re-scanned post-assembly.** Every assembled prompt re-passes
  the full adapter deny list (URIs, file paths, raw-source markers,
  40-char source shingles, credential shapes, PII shapes, full-slide /
  page-generation / screenshot wording) AFTER assembly, BEFORE the plan
  is written. The live runner re-runs the same scan one more time
  before the network call (per `d-one-live-integration-design.md` §5).
- **V5 — Vocabulary changes are paired.** Adding, removing, or
  modifying a descriptor requires a paired change to the vocabulary
  file's validator (or, if no validator yet exists, the corresponding
  TODO is still open and the live path stays unwired).

## 5. Audit evidence fields

`scripts/d_one_live_run_evidence.schema.json` does NOT exist as runtime
behavior today. `schemas/d_one_live_run_evidence.schema.json` ships a
**contract sketch** for a future audit record so this checklist can
point at concrete field names. The schema is **not wired** into any
script — no helper today reads or writes a record in this shape, and
`scripts/run_d_one_generation.py` has no `--audit-out` flag. A live run
is PASS-eligible only if its audit record satisfies all of:

- **A1 — Record exists.** Every live run — success OR failure — produces
  exactly one audit record on local disk at the caller-supplied
  `--audit-out` path (per `d-one-live-integration-design.md` §8). A run
  with no audit record is automatically FAIL.
- **A2 — Record validates.** The record validates against
  `schemas/d_one_live_run_evidence.schema.json` (once that schema is
  wired into a runtime validator — see `d-one-live-integration-design.md`
  §13). A schema-invalid record is FAIL.
- **A3 — Plan binding.** The record records the input
  `d_one_adapter_plan.json`'s sha256, so a reviewer can re-run
  `scripts/done_image_adapter.py --validate-plan` against the same plan
  and confirm the live provider consumed what the adapter approved.
- **A4 — Per-request rows.** One row per plan request, carrying: `id`,
  `prompt_sha256`, optional `intended_use_sha256`, declared
  `width_px` / `height_px`, declared `manifest_local_path`, declared
  `manifest_source` (always `"d_one_local"`).
- **A5 — Per-request outcome.** Each row records `outcome` ∈
  {`ok`, `rejected`, `error`}, the rejection reason if any (closed
  vocabulary — see §7), the opaque endpoint identifier from R2 (never
  the URL), the elapsed time in milliseconds, the output byte length,
  the output magic-byte signature label (`png` / `jpg` / `jpeg`), and
  the output sha256.
- **A6 — Materialized binding.** For every `outcome == "ok"` row, the
  record records the resulting `<assets-dir>/<id>.<ext>` sha256, so a
  later `scripts/materialize_image_assets.py` run can prove the bytes
  it copied are the bytes the live provider produced.
- **A7 — No raw payloads.** The record carries NO raw prompt text, NO
  raw source text, NO raw output bytes, NO customer identifiers, NO
  credentials, NO absolute paths, NO URLs, NO `file://` references.
  Bytes are recorded as sha256 + length only.
- **A8 — Local-only.** The record stays on the host that produced it.
  Uploading, posting, or emailing it is a separate explicit human
  action — not part of the runner.
- **A9 — Determinism.** Given byte-identical inputs and byte-identical
  live outcomes, the record bytes MUST be byte-identical across runs.
  (Live outcomes include timestamps; the schema therefore allows ONE
  caller-supplied `clock_label` field per record and forbids wall-clock
  noise everywhere else — see the schema for the exact field set. The
  `clock_label` itself is structurally locked to an ISO-8601 timestamp
  shape, so it cannot smuggle a URI-scheme bypass like `http:something`
  past the determinism field.)
- **A10 — Schema gate runs (NECESSARY, not sufficient).** Before a live
  run can be called PASS,
  `python3 scripts/validate_artifacts.py --schema schemas/d_one_live_run_evidence.schema.json <audit-out-path>`
  MUST exit zero against the produced record. Schema PASS is a
  necessary precondition, **not a sufficient one**: the in-repo
  validator implements only a subset of JSON Schema draft-07
  (`type`, `required`, `enum`, `pattern`, `minLength` / `maxLength`,
  `minimum` / `maximum`, `exclusiveMinimum` / `exclusiveMaximum`,
  `minItems` / `maxItems`, `additionalProperties`, `properties`,
  `items`), so a record can satisfy the schema and still violate the
  contract — e.g. claim `outcome == "ok"` with no `output_sha256`,
  claim `run_outcome == "ok"` with a `gate_fired` value set,
  declare `plan_request_count = 1` with two `requests[]` rows, smuggle
  a JWT-shaped token through a free-form field (the schema's positive-
  whitelist patterns refuse URLs / paths / file-scheme shapes but not
  long-hex or `eyJ`-prefixed shapes — those would false-positive the
  `sha256` fields if banned at the schema layer). A future audit-record
  validator MUST therefore apply the cross-checks in §5.1 on top of the
  schema gate, mirroring how `scripts/done_image_adapter.py --validate-plan`
  layers cross-checks on top of `schemas/d_one_adapter_plan.schema.json`
  today.

## 5.1. Cross-checks beyond the schema gate (A11–A19)

The cross-checks below are NOT expressible in the JSON Schema subset the
in-repo `scripts/validate_artifacts.py` implements (no `if` / `then` /
`else`, no `allOf` / `anyOf` / `oneOf`, no `not`, no `contains`). A
future audit-record validator MUST run them in addition to A10. Until
that validator exists, the live path stays unwired — schema PASS alone
does not flip the §1 status from UNVERIFIED to VERIFIED.

- **A11 — No credential / PII shape in any free-form field.** Re-run
  the same credential and PII scans `scripts/done_image_adapter.py`
  applies to plan prompts (JWT, AWS access key, PEM marker, long-hex
  bearer, `password:` / `secret:` / `api_key:` / `token:` /
  `client_secret:` literals; email / phone / SSN / UUID /
  `customer_id` / `account_id` literals) against `gate_detail`,
  `evidence_notes`, every `*_approval_ref`, and every `review_ref`.
  The schema's positive-whitelist `pattern` lock catches URLs, paths,
  AND every URI scheme via character-class exclusion (the narrative
  whitelist on `gate_detail` / `evidence_notes` refuses `:`, so
  `http:`, `data:`, `file:`, `mailto:`, `javascript:`, `urn:` cannot
  pass; the structural ISO-8601 lock on `clock_label` refuses URI
  schemes there too; the surrounding-text whitelist on `note` refuses
  trailing URLs past the sentinel). It still cannot catch long-hex or
  `eyJ`-prefixed shapes without false-positiving the legitimate
  `sha256` fields — that gap is what this A11 runtime scan covers.
- **A12 — Per-request outcome consistency.** For every row in
  `requests[]`: if `outcome == "ok"`, `output_magic_label` AND
  `output_sha256` MUST be present, `output_length_bytes` MUST be `> 0`,
  and `rejection_reason` MUST be absent; if `outcome != "ok"`,
  `rejection_reason` MUST be present and `output_magic_label` /
  `output_sha256` / `materialized_sha256` MUST be absent.
- **A13 — Top-level run_outcome consistency.** If
  `run_outcome == "ok"`, `gate_fired` AND `gate_detail` MUST be
  absent. If `run_outcome != "ok"`, `gate_fired` MUST be present
  (`gate_detail` remains optional but recommended).
- **A14 — Cleanup-ref consistency.** If any
  `approvals.per_image_review_refs[*].decision == "fail"`,
  `approvals.cleanup_ref` MUST be present. Otherwise it MUST be
  absent.
- **A15 — Plan-count equality.** `plan_request_count` MUST equal
  `len(requests)`, AND MUST equal the `request_count` recorded in
  the input plan whose sha256 is pinned by `plan_sha256` (A3).
- **A16 — Per-image-review coverage.** The set of
  `approvals.per_image_review_refs[*].id` values MUST exactly equal
  the set of `requests[*].id` values whose `outcome == "ok"` —
  no missing review row, no orphan review row.
- **A17 — Materialized hash matches output hash.** For every request
  where both `output_sha256` and `materialized_sha256` are present,
  they MUST be byte-identical. A mismatch is itself a F12 / F13
  condition for the downstream `materialize_image_assets.py` run.
- **A18 — Request order matches plan order.** `requests[]` MUST be
  in the same order as the input plan's `requests[]` (which
  `scripts/done_image_adapter.py` sorts by `id`). Order is part of
  the A9 determinism contract.
- **A19 — Plan-sha256 binds the actual plan.** The on-disk
  `d_one_adapter_plan.json` whose sha256 matches `plan_sha256` MUST
  re-validate via `scripts/done_image_adapter.py --validate-plan`
  against the same workspace. A pinned-but-missing or
  pinned-but-drifted plan is FAIL.

## 6. Manual approval boundaries

A live run is PASS-eligible only if every approval below is recorded in
writing by a named human reviewer BEFORE the run executes:

- **M1 — Endpoint approval.** The endpoint appears on the allow-list
  (R1, R2) with a reviewer name, date, and security-review reference.
- **M2 — Vocabulary approval.** The descriptor vocabulary in force is
  the approved one (V1).
- **M3 — Per-deck approval.** The specific deck whose images this run
  generates is approved at the deck level. A standing "this team may
  always use D-One" approval is not sufficient; each deck is an
  explicit decision.
- **M4 — Disable-switch off-by-default.** The runtime disable switch
  (per `d-one-live-integration-design.md` §9.6) ships disabled by
  default. The reviewer that enabled it for this run is recorded in
  the audit record (A5 carries the endpoint identifier; the disable
  state and the operator who flipped it are recorded as a separate
  evidence row — see the schema).
- **M5 — Per-image manual review.** AFTER the run produces image
  bytes, a human reviewer inspects every generated image and records
  PASS / FAIL per image, with the reason. PASS criteria: the image is
  a supporting illustration (not a full slide); it carries no text
  that should be editable; it contains no identifiable customer /
  partner / product reference; it is on-brand. A single FAIL on any
  image forces the §7 rollback path for the entire run.
- **M6 — Cleanup approval.** A live-generated image that fails M5 is
  removed from the workspace; the run is rolled back to its pre-call
  state per the §7 fail-closed contract. There is no "ship it anyway"
  path. The cleanup itself is a logged human action.

## 7. Failure / stop conditions

A live run MUST abort, leave the workspace and `--assets-dir`
byte-identical to their pre-call state (the §8 audit record is the
deliberate single exception per `d-one-live-integration-design.md` §7),
and exit non-zero on any of:

- **F1 — Allow-list miss.** The endpoint is not on the allow-list (R3).
- **F2 — Disable switch on.** The global disable switch is set; the
  runner falls back to mock-only mode (`--fixtures-dir` /
  `--allow-synthetic-bytes`) and refuses any live call.
- **F3 — Plan invalid.** `done_image_adapter.validate_plan_file` rejects
  the input plan.
- **F4 — Vocabulary miss.** A prompt contains a descriptor outside the
  approved vocabulary (V3).
- **F5 — Re-scan miss.** A prompt fails the live re-scan (V4 /
  `d-one-live-integration-design.md` §5).
- **F6 — Transport error.** The live call times out, returns an HTTP
  error, fails authentication, exhausts quota, or the model is
  unavailable.
- **F7 — Extension miss.** The live provider returns an output
  extension outside `.png` / `.jpg` / `.jpeg`.
- **F8 — Magic-byte miss.** A returned blob's first bytes do not match
  the declared extension's signature (PNG: `89 50 4E 47 0D 0A 1A 0A`;
  JPEG: `FF D8 FF`).
- **F9 — Embed-cap miss.** A returned blob exceeds the 10 MiB embed
  cap (or the per-endpoint tighter cap from R2, whichever is smaller).
- **F10 — Overwrite attempt.** Any image-byte target pre-exists under
  `--assets-dir`. The caller must remove prior bytes before re-running.
- **F11 — Audit overwrite attempt.** The `--audit-out` path
  pre-exists, is a symlink, has a symlinked parent, fails
  `local_path_is_safe`, or does not resolve inside its parent
  directory. The audit gate is its own no-overwrite contract.
- **F12 — Symlink anywhere.** A symlink appears at `--workspace`,
  `--assets-dir`, the plan path, an output path, or a parent segment
  of any of those.
- **F13 — Write outside `--assets-dir`.** The live provider attempts
  to write into `<workspace>`, `<workspace>/ppt/media/`, `/tmp`, the
  home directory, or any other path. The runner's `--audit-out` write
  is the only additional local artifact and is the runner's own
  responsibility, governed by F11.
- **F14 — Per-image review FAIL (M5).** Any image fails manual review.
- **F15 — Schema-invalid OR cross-check-invalid audit record.** The
  produced audit record fails A2 / A10 (the schema gate) OR any of the
  A11–A19 cross-checks in §5.1. Schema PASS alone is not enough — a
  schema-valid record that violates a §5.1 cross-check (e.g. claims
  `outcome == "ok"` with no `output_sha256`) still trips F15.
- **F16 — Determinism miss.** A re-run with byte-identical inputs
  produces a different audit record (other than the allowed
  `clock_label` field — see A9).
- **F17 — Approval missing.** Any approval in §6 (M1–M6) is not
  recorded.

On any of F1–F17 the run is FAIL. The audit record (written AFTER the
image-byte rollback, per `d-one-live-integration-design.md` §7)
documents which gate fired.

## 8. Evidence required for PASS

A reviewer may mark a live run PASS only if EVERY item below is true.
This is the gate the wording in §1 hangs on; flipping "Real D-One path:
UNVERIFIED" to "VERIFIED" requires walking this list and quoting the
evidence for each item.

- **E1 — Mock path still passes.** Re-running `scripts/done_image_adapter.py --self-test`,
  `scripts/run_d_one_generation.py --self-test`,
  `scripts/materialize_image_assets.py --self-test`,
  `scripts/image_asset_acceptance_smoke.py --self-test`,
  `scripts/acceptance_smoke.py --self-test`,
  `scripts/verify_skill_package.py`, and `scripts/package_skill.py --self-test`
  on the same checkout that produced the live run all exit zero. The
  live work has not regressed the mock work.
- **E2 — Live verification matrix passes.** Every gate listed in
  `references/d-one-live-integration-design.md` §11 has been exercised
  against a sandbox endpoint (per R4) and recorded as PASS.
- **E3 — Allow-list satisfied.** The endpoint identifier in the audit
  record (A5) resolves to an allow-list entry whose scope covers this
  run (R1–R5).
- **E4 — Vocabulary satisfied.** Every prompt in the plan was
  assembled from approved descriptors (V1–V5).
- **E5 — Audit record valid (schema AND cross-checks).** The record
  passes A1–A10 against `schemas/d_one_live_run_evidence.schema.json`
  AND the A11–A19 cross-checks in §5.1. Schema-only PASS is necessary
  but not sufficient; both layers MUST be green.
- **E6 — Approvals recorded.** M1–M6 each have a named reviewer and
  date, and the records are reachable from the audit record.
- **E7 — No fail-closed condition fired.** None of F1–F17 fired
  during the run.
- **E8 — Materialize gate clean.** A subsequent
  `scripts/materialize_image_assets.py` run against the produced
  `--assets-dir` exits zero, copies every declared target, and
  re-validates the magic-byte signatures (A6 is internally consistent
  with the workspace state).
- **E9 — PPTX export and contract clean.** A subsequent
  `scripts/export_pptx.py` followed by `scripts/validate_pptx_contract.py`
  exits zero against the resulting workspace, with no external rels,
  no `file://`, no macros / OLE / ActiveX, embedded media inside the
  allow-list, and every slide carrying native editable shapes.
- **E10 — No drift.** This checklist file, the design doc, and the
  policy file are all unchanged across the run, OR every change is
  named in the audit record's `evidence_notes` field along with the
  reviewer and date.

A run that misses any of E1–E10 is **not** PASS, regardless of how
"good" the generated images look. The wording in §1 stays
"Real D-One path: UNVERIFIED" until E1–E10 each carry quoted evidence.

## 9. Cross-references

- `references/d-one-live-integration-design.md` — the design this
  checklist gates. This file does not override the design; it makes
  the evidence requirements enumerable. The §13 TODOs there are the
  prerequisites; this file lists what evidence each TODO must produce
  when it is resolved.
- `references/d-one-image-policy.md` — the broader policy these
  readiness gates sit inside.
- `references/security-policy.md` — the fail-closed checks the
  security scan applies to every artifact, including the audit record.
- `references/clean-room-policy.md` — the clean-room constraint that
  forbids copying anything from an external reference implementation
  into either the live integration or this checklist's wording.
- `schemas/d_one_live_run_evidence.schema.json` — the contract sketch
  for the future audit record. **Not wired** into any runtime script
  today; ships only so this checklist can point at concrete field
  names.

## 10. Status block (re-statement)

- Mock / local path: **VERIFIED** (`--self-test` coverage across the
  three-script local boundary plus the image-asset acceptance smoke).
- Real D-One path: **UNVERIFIED.** No live flag exists, no endpoint
  allow-list exists, no descriptor vocabulary exists, no audit
  validator is wired, and no live run has occurred. Adopting this
  checklist does not change that — it defines the gate that future
  live work must pass.
