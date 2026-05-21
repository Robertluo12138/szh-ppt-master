# D-One Live-Run Prerequisite Contracts

This document lists the **contract artifacts** that gate any future
real-D-One live run. It is a companion to:

- `references/d-one-live-run-readiness.md` — the readiness checklist
  whose §3 R1, §4 V1, §5 A2 hook, and §6 M1-M6 gates the
  `references/d-one-discovery-trial-record.md` probe found unmet;
- `references/d-one-live-integration-design.md` — the §13 TODOs that
  must be resolved as separate explicit user requests before any
  live work;
- `references/d-one-live-trial-packet.md` — the §3 pre-trial
  precondition checklist whose unmet items produced the
  **BLOCKED** discovery outcome.

Nothing in this repo today calls D-One, MCP, a model API, an
image-search endpoint, or any external service. This document does
not change that. Adopting these contracts is **not** a green-light
for live work; it makes the contract surface explicit so a future
live-mode review has concrete file shapes to gate against.

## 1. Status

- **Mock / local path: VERIFIED** (`scripts/done_image_adapter.py`,
  `scripts/run_d_one_generation.py` with `--fixtures-dir` /
  `--allow-synthetic-bytes`, `scripts/materialize_image_assets.py`,
  `scripts/export_pptx.py`, and the
  `scripts/image_asset_acceptance_smoke.py --self-test` end-to-end
  smoke).
- **Real D-One path: UNVERIFIED.** No live flag exists, no MCP
  wiring, no model-API client, no network call, no live endpoint
  has been called, no audit-record runtime validator hook is wired
  into the runtime script, and no M1-M6 written approvals exist.
  This file does not change that status.

The wording above is load-bearing. The contract artifacts below add
SHAPE so a future review has something to refuse; they do not flip
the readiness §1 status.

## 2. Scope

This document covers the three contract artifacts the BLOCKED
discovery record flagged as missing on the audited commit (per
`references/d-one-discovery-trial-record.md` blockers #2, #3, #4):

1. the **endpoint allow-list** schema and synthetic placeholder
   (R1, R2 in `references/d-one-live-run-readiness.md` §3);
2. the **descriptor vocabulary** schema and synthetic placeholder
   (V1, V2 in `references/d-one-live-run-readiness.md` §4);
3. the **live-run preflight** schema and synthetic placeholder —
   a local-only contract that pins the M1-M6 / R1 / V1 / audit-out
   preconditions BEFORE a future live run.

Out of scope (each gated by a separate explicit user request and
its own review):

- the live-mode flag on `scripts/run_d_one_generation.py`
  (blocker #1 — `references/d-one-live-integration-design.md` §13);
- the audit-record runtime validator hook inside
  `scripts/run_d_one_generation.py` (blocker #4 — the A2 hook;
  `scripts/validate_d_one_live_run_evidence.py` exists as a
  standalone validator but is NOT wired into any runtime script);
- written M1-M6 approvals for a specific deck and endpoint
  (blocker #5 — a process step outside this repo).

## 3. Endpoint allow-list contract (R1, R2, R3, R5, R6)

- **Schema:** `schemas/d_one_endpoint_allowlist.schema.json`.
- **Synthetic placeholder:**
  `examples/d_one_endpoint_allowlist_template.json` ships with an
  empty `entries: []`, demonstrating R3 default-deny: a file with
  no entries is equivalent to "every endpoint denied".
- **Schema-layer locks (defense in depth for R5 / R6):**
  - `endpoint_label`, `destination_label` — positive-whitelist
    `pattern` locks refuse `:` (URI schemes), `/` and `\\` (paths),
    `@` (emails), `#` (fragments), `?` (queries), `%`
    (percent-encoded shapes), AND `.` (dotted-hostname and dotted
    IPv4 shapes — so `host.internal`, `api.example.com`, and
    `10.0.0.1` / `192.168.1.1` / `127.0.0.1` / `172.16.0.1` are all
    refused at the schema layer), with leading char locked to a
    letter so leading-digit IPv4-octet shapes like `10` / `127` /
    `172` / `192` cannot pass either. No real URL, real internal
    hostname, real private-IPv4 address, or PII shape can pass at
    the schema layer;
  - `approval_reviewer_ref`, `security_review_ref` —
    positive-whitelist `pattern` locks refuse `:`, `/`, `\\`, `@`,
    `#`, `?`, `%`, and whitespace (so URLs, paths, emails, and
    multi-word real-name shapes cannot pass); `.`, `+`, `-` are
    permitted for opaque-ref conventions (e.g. `rev-2026-001`,
    `sec.q2.2026`) since these fields name internal record IDs, not
    network destinations;
  - `approval_date` — ISO-8601 UTC timestamp shape with mandatory
    timezone, fixed-position digits refuse every URI-scheme bypass;
  - `scope.environment` — closed enum `sandbox` | `production`
    (R4 sandbox-before-production ordering is a runtime gate);
  - `scope.request_types` — closed enum locked to
    `image_generation` only (full-slide / page-generation /
    screenshot request types are forbidden by
    `references/d-one-image-policy.md` and MUST NOT be added);
  - `scope.byte_cap_max_bytes` — schema ceiling of 10485760
    (10 MiB) matches `scripts/export_pptx.py`'s embed cap.
- **Validation:** schema-PASS is `python3 scripts/validate_artifacts.py
  --schema schemas/d_one_endpoint_allowlist.schema.json <file>`.
  Necessary, not sufficient — the runtime gate that R3 / R6
  demands (the runner refusing any endpoint not on the list, every
  request, defense in depth) is part of the live-mode wiring TODO
  in `references/d-one-live-integration-design.md` §13 and is NOT
  wired today.

This file never contains a real endpoint, real destination, real
reviewer identity, real security-review identifier, real customer
endpoint, or any other production value. The synthetic placeholder
ships empty; populating it for a real run is a separate explicit
user request and a paired security review.

## 4. Descriptor vocabulary contract (V1, V2, V3, V4, V5)

- **Schema:** `schemas/d_one_descriptor_vocabulary.schema.json`.
- **Synthetic placeholder:**
  `examples/d_one_descriptor_vocabulary_template.json` ships a
  small abstract V2-compliant set (palette tokens by name,
  geometric nouns, mood adjectives, composition adjectives).
- **Schema-layer locks (defense in depth for V2):**
  - `kind_enum` — fixed-length 4-element array carrying exactly
    `color_token`, `geometric_noun`, `mood_adjective`,
    `composition_adjective` so a tampered file cannot widen the
    kind set;
  - `descriptors[*].kind` — same closed enum, redundant with
    `kind_enum` so the runtime gate has two independent locks;
  - `descriptors[*].value` — lowercase-identifier `pattern` lock
    refuses uppercase letters (so proper nouns, product names,
    customer names cannot pass), whitespace (so multi-word
    sentences cannot pass), and URI / path / email / fragment /
    query / percent-encoded shapes. The same pattern carries a
    negative-lookahead deny clause that refuses forbidden-token
    shapes at the schema layer: the bounded identifier tokens
    `public`, `upload`, `raw`, `customer`, `confidential`,
    `screenshot`, `credential`, `password`, `secret` (each matched
    only when surrounded by start-of-string / end-of-string / an
    identifier-boundary char `.` / `_` / `-`, so `drawing` and
    `palette.background` still pass while the underscore forms
    `raw_source` / `customer_acme` / `confidential_report` /
    `public_upload`, the hyphen forms `raw-source` /
    `customer-acme` / `confidential-report` / `public-upload`, and
    the dotted forms `public.upload` / `raw.source` all fail), and
    the compound phrases `full slide`, `image search`,
    `web generation`, `page generation`, `slide generation` —
    each matched across ZERO OR MORE identifier-boundary chars so
    the underscore form (`full_slide`), the hyphen form
    (`full-slide`), the dotted form (`full.slide`), the
    concatenated form (`fullslide`), AND every separator-stacked
    obfuscation — multi-char runs like `full__slide` /
    `full--slide` / `full..slide` / `full___slide` /
    `full----slide`, plus mixed-separator runs like
    `full_-slide` / `full.-slide` / `full_.slide`, and the same
    families for the other four compounds — all fail. The schema-layer
    deny is a fail-closed precaution and is necessary but not
    sufficient — adding, removing, or modifying the deny list is
    a paired schema/runtime change once the runtime gate is wired;
  - `descriptors[*].approved_in_review_ref` — opaque ref pattern
    (same lock as the allow-list's `approval_reviewer_ref`).
- **Validation:** `python3 scripts/validate_artifacts.py --schema
  schemas/d_one_descriptor_vocabulary.schema.json <file>`. The
  schema-layer deny clause above refuses the documented
  forbidden-token shapes today (verified by passing the synthetic
  placeholder and refusing each of `public_upload`, `raw_source`,
  `full_slide`, `image_search`, `web_generation`, `customer_acme`,
  `confidential_report`). The V3 closed-enumeration runtime check
  (the prompt assembler refusing a descriptor not in the file; the
  live runner re-checking at its own boundary) is still part of
  the live-mode wiring TODO and is NOT wired today. V4
  post-assembly re-scan (the adapter's FULL deny list — URI
  schemes, file paths, raw-source markers, 40-char source
  shingles, credential / PII shapes, full-slide / page-generation
  / screenshot wording, public-distribution wording — `upload to
  public` / `public upload` / `share publicly` / `public hosting`
  / `publish to web` / `public url` / `public link` / `public cdn`
  / `host publicly` — re-running on every assembled prompt
  before the plan is written) is the adapter runtime's
  responsibility and remains TODO; the schema-layer deny narrows
  but does not replace it.

For `color_token` entries, the value MUST be a `palette.<name>`
token resolvable from `design_system.json` at runtime; the schema
records only the lowercase-identifier shape, the runtime validator
(when wired) handles the design-system cross-check.

### 4.1 Image-request taxonomy (V6 — clean-room dimensions)

- **Schema:** the same
  `schemas/d_one_descriptor_vocabulary.schema.json` carries an
  `image_taxonomy` block (required) and an optional
  `synthetic_requests` block.
- **Synthetic placeholder:**
  `examples/d_one_descriptor_vocabulary_template.json` ships both
  blocks with the canonical clean-room values below plus two
  composed example requests.
- **Five clean-room dimensions** — each a closed enumeration:
  - `rendering_style` (5 values): `flat_vector`, `line_diagram`,
    `isometric_lite`, `low_poly`, `solid_shape`;
  - `palette_family` (5 values): `neutral_grey`, `accent_only`,
    `dual_tone`, `mono_brand`, `palette_default`;
  - `image_role` (5 values): `decorative_accent`, `metaphor_icon`,
    `divider_motif`, `kpi_emblem`, `cover_motif`;
  - `layout_pattern` (5 values): `single_center`, `left_anchor`,
    `right_anchor`, `top_band`, `bottom_band`;
  - `modifier` (4 values, optional in a request): `low_contrast`,
    `soft_edges`, `grid_aligned`, `negative_space`.
- **Schema-layer locks (defense in depth):**
  - per-dimension `allowed_values` arrays are pinned to a fixed
    length (`minItems == maxItems`) so a tampered file cannot
    widen the surface;
  - per-value `enum` lock pins the canonical set at the schema
    layer (redundant with the file-level `allowed_values` array
    for the same defense-in-depth posture as `kind_enum` ↔
    `descriptors[*].kind`);
  - per-value `pattern` lock re-applies the descriptor-layer
    positive whitelist + forbidden-token deny clause, so a
    future schema-edit that loosened the enum would still trip
    the deny pattern on any unsafe token (`public_upload`,
    `raw_source`, `full_slide`, `image_search`, `web_generation`,
    `customer_acme`, `confidential_report`, URL-like shapes, and
    free-form raw-source text are all refused at this layer);
  - `uniqueItems: true` is set on every `allowed_values` array,
    so a noncanonical array that ships the same canonical value N
    times (e.g. `["flat_vector"] * 5`) is refused at the schema
    layer — without this lock, an array satisfying length +
    items.enum + items.pattern individually could still be
    noncanonical, false-greening the contract. Combined with
    `minItems == maxItems == N` (where N matches the length of
    `items.enum`), `uniqueItems` forces every `allowed_values`
    array to be a permutation of the canonical set — the
    canonical-set-membership invariant. `scripts/validate_artifacts.py`
    learned `uniqueItems` in the same paired change so the
    schema-PASS command actually enforces this gate;
  - `synthetic_requests[*]` is `additionalProperties: false` with
    per-dimension enum + pattern locks identical to the
    `allowed_values` lock, so a request cannot smuggle a value
    outside the canonical taxonomy.
- **Validation:** `python3 scripts/validate_artifacts.py --schema
  schemas/d_one_descriptor_vocabulary.schema.json <file>` for the
  schema-PASS check. The probe matrix lives inside
  `python3 scripts/validate_d_one_live_run_evidence.py
  --self-test` as the T1-T10 block — T1 confirms the canonical
  synthetic vocabulary validates clean; T2-T4 confirm each
  documented forbidden value (`public_upload`, `raw_source`,
  `full_slide`, `image_search`, `web_generation`, `customer_acme`,
  `confidential_report`, `https://example.com`,
  `file:///etc/passwd`, a public asset URL shape
  `https://cdn.public.example.com/asset.png`, and a free-form
  raw-source sentence) is refused at the schema layer when
  injected into the descriptor value slot, any `allowed_values`
  slot, and any `synthetic_requests` slot; T5 confirms a shape-valid but
  out-of-taxonomy value (`drawing`) is refused by the per-
  dimension `enum`; T6 confirms the optional `modifier` field can
  be omitted; T7 confirms a tampered `allowed_values` length is
  refused by the `maxItems` lock; T8 confirms a missing required
  dimension is refused; T9 confirms an extra property on a
  synthetic_request is refused; T10 confirms a single duplicate
  inside `allowed_values` is refused by the `uniqueItems` lock,
  and T10b confirms the noncanonical extreme case (an
  `allowed_values` array of length N that ships the same
  canonical value N times — e.g. `["flat_vector"] * 5`) is also
  refused by the same lock, closing the false-green Codex
  stop-time review flagged. The V3 closed-enumeration runtime
  cross-check (the prompt assembler refusing a request value not
  in `image_taxonomy.<dim>.allowed_values`; the live runner
  re-checking at its own boundary) is still part of the live-mode
  wiring TODO and is NOT wired today — real D-One remains
  **UNVERIFIED**.

## 5. Live-run preflight contract (audit-out path placement + M1-M4 + R1 / V1 pins)

- **Schema:** `schemas/d_one_preflight_audit.schema.json`.
- **Synthetic placeholder:**
  `examples/d_one_preflight_audit_template.json` ships with
  placeholder labels for every path and approval ref.
- **Purpose:** capture the R1 / V1 / M1-M4 preconditions and the
  audit-out path placement BEFORE any future live call. The
  preflight is the upstream sibling of
  `schemas/d_one_live_run_evidence.schema.json` (which captures the
  POST-call audit record): a future runner consumes a preflight,
  makes one approved call per request, then writes an evidence
  record. The preflight ITSELF is local-only; it is never
  uploaded, posted, or emailed.
- **Schema-layer locks (defense in depth for the audit-out path
  placement contract in `references/d-one-live-integration-design.md`
  §8 and `references/d-one-live-run-readiness.md` §5):**
  - `mode: "preflight"` enum lock distinguishes the file from
    `d_one_live_run_evidence.json` (`mode: "live"`) and from
    `d_one_adapter_plan.json` (`mode: "dry_run"`);
  - `disable_switch_state: "off"` enum lock — a preflight that
    records `"on"` would itself be evidence of a contract
    violation;
  - `endpoint_label` — same tightened opaque-label pattern as the
    allow-list's `endpoint_label` (no `.`, no leading digit), so a
    preflight cannot carry an `endpoint_label` shape the allow-list
    itself would refuse; cross-checking the actual value against
    the allow-list at run time is the runtime gate's responsibility;
  - `operator_label` — pattern allows `.`, `_`, `-` for opaque-id
    conventions (e.g. `op_team_alpha`, `op.q2.2026`) but refuses
    `:`, `/`, `\\`, `@`, `#`, `?`, `%`, and whitespace so emails
    and multi-word real-name shapes cannot pass at the schema
    layer. The runtime G11 free-form scan in
    `scripts/validate_d_one_live_run_evidence.py` catches the
    residual username-shaped PII cases when the audit record is
    produced;
  - `allow_list_path_label`, `vocabulary_path_label`,
    `workspace_label`, `assets_dir_label`, `audit_out_path_label`
    — workspace-relative path-safety `pattern` locks: no absolute
    path, no URI scheme, no `..` traversal (leading negative
    lookahead), and the leading character must be alphanumeric so
    `.gitignore`-shaped / dot-hidden injection cannot pass. The
    runtime gate additionally enforces `local_path_is_safe` +
    `_resolves_within` against the actual workspace and applies
    the F11 no-overwrite / symlink-refused / parent-symlink-refused
    rules to the actual `--audit-out` file when the live-mode flag
    is finally wired;
  - `approvals.endpoint_approval_ref`,
    `approvals.vocabulary_approval_ref`,
    `approvals.deck_approval_ref`, `approvals.operator_ref` —
    opaque approval-ref locks (same shape as the allow-list and
    the evidence record). M5 per-image refs are written into the
    POST-call evidence record, NOT into the preflight; M6
    `cleanup_ref` is optional here and becomes required in the
    evidence record when an M5 review fails.
- **Validation:** `python3 scripts/validate_artifacts.py --schema
  schemas/d_one_preflight_audit.schema.json <file>`. As with
  the other two contracts, schema PASS is necessary but not
  sufficient — the runtime gate that walks the M1-M6 written
  approvals, cross-checks the endpoint_label against the allow-list,
  cross-checks the vocabulary file against
  `schemas/d_one_descriptor_vocabulary.schema.json`, and enforces
  F11 on the audit-out path is part of the live-mode wiring TODO.

## 6. Local-only contract (no upload, no public network)

Every artifact described above is **local-only**. The repo
contains:

- a schema (refuses real-data shapes at the schema layer);
- a synthetic placeholder (no real value);
- this reference doc (describes the contract surface).

Populating any of the three files for a real run, sharing the
populated file, uploading any preflight or evidence record, or
making any live call is a separate explicit human action gated by
a separate review. The validators (`scripts/validate_artifacts.py`,
`scripts/validate_d_one_live_run_evidence.py`) make no network
call, open no MCP server, contact no live endpoint, and write
nothing outside an explicit caller-supplied output path. The
no-public-network gate
(`python3 scripts/verify_skill_package.py`) refuses real URLs in
any of these files.

## 7. Cross-references

- `references/d-one-live-run-readiness.md` — the §3 / §4 / §5 / §6
  R, V, A, M gates these contracts realize as concrete file shapes.
- `references/d-one-live-integration-design.md` — the §13 TODOs
  that remain open after these contracts ship (live-mode flag,
  audit-record runtime hook, M1-M6 process records, the disable
  switch, cache vs. regenerate decision).
- `references/d-one-live-trial-packet.md` — the §3 pre-trial
  precondition checklist whose unmet items resolved the discovery
  probe to BLOCKED. These contracts close blockers #2, #3, and #4
  at the SHAPE layer; the runtime-wiring half of #1 and #4, and
  the process record of #5, remain open and out of scope here.
- `references/d-one-discovery-trial-record.md` — the BLOCKED
  discovery record this work was scoped against.
- `references/d-one-image-policy.md` — the broader image-policy
  envelope these contracts sit inside (forbidden uses; full-slide
  / screenshot / chart paths are out of scope and MUST NOT be
  added to any of the three new contracts).
- `references/security-policy.md` and `SECURITY.md` — the
  fail-closed checks the security scan applies to every artifact.
- `references/clean-room-policy.md` — the clean-room constraint
  that forbids copying anything from an external reference
  implementation into these contracts.
- `schemas/d_one_endpoint_allowlist.schema.json`,
  `schemas/d_one_descriptor_vocabulary.schema.json`,
  `schemas/d_one_preflight_audit.schema.json` — the three new
  schemas.
- `examples/d_one_endpoint_allowlist_template.json`,
  `examples/d_one_descriptor_vocabulary_template.json`,
  `examples/d_one_preflight_audit_template.json` — the three
  new synthetic placeholders.
- `schemas/d_one_live_run_evidence.schema.json` and
  `scripts/validate_d_one_live_run_evidence.py` — the existing
  POST-call evidence record contract these prerequisites slot in
  ahead of. The preflight (§5) is the upstream sibling.
