# D-One Live-Run Trial Packet (First Company-Machine Trial)

This document is the **trial packet** an operator follows the first time
a real D-One live run is attempted on the company machine. It does not
add runtime behavior, does not modify any script, and does not relax
any gate. It exists so the first live attempt has a single concrete
checklist instead of a re-read of every reference file in this repo.

The wording in `references/d-one-live-run-readiness.md` §1 still holds:

- Mock / local path: **VERIFIED.**
- Real D-One path: **UNVERIFIED.** There has never been a real live
  run. Adopting this packet does not change that. The status only
  flips after the packet has actually been walked on the company
  machine AND every PASS gate in `d-one-live-run-readiness.md` §8
  carries quoted evidence.

A copy of this packet on disk is not evidence of a trial. Only a live
run that produced an audit record passing
`scripts/validate_d_one_live_run_evidence.py` AND the §8 PASS gates is.

## 1. Scope

One live run against one sandbox-scoped endpoint, consuming exactly one
schema-valid `d_one_adapter_plan.json` and producing exactly one
`<audit-out>` evidence record plus its image bytes under `--assets-dir`.
This is the same scope `d-one-live-run-readiness.md` §2 defines; this
packet does not widen it. Multi-run campaigns, production endpoints,
re-runs after a FAIL, and caching across runs are all out of scope for
the first trial.

## 2. Top-line outcomes

Every walk of this packet resolves into one of four operator-facing
states. They are the top-line vocabulary an operator uses when
reporting the trial result. `Real D-One path: UNVERIFIED` in §1
(and in `d-one-live-run-readiness.md` §1) moves to `VERIFIED` only
on **PASS**; **FAIL**, **BLOCKED**, and any walk that completes
§4 mechanically but cannot quote every E1-E10 item from
`d-one-live-run-readiness.md` §8 all leave that status at
**UNVERIFIED**.

The BLOCKED / FAIL boundary is **when** the operator stops, not
whether a network call was attempted. **BLOCKED** is declared at
the §3 precondition checklist, BEFORE the operator invokes any §4
step. **FAIL** is anything that fires once §4 has been invoked —
including the pre-network readiness §7 gates F1 (allow-list miss),
F2 (disable switch on), F3 (plan invalid), F4 (vocabulary miss),
F5 (re-scan miss), and F17 (approval missing), which fire before
the network call but are still FAIL per
`d-one-live-run-readiness.md` §7 ("On any of F1–F17 the run is
FAIL"). There is no "pre-network FAIL becomes BLOCKED" relaxation;
the readiness §7 contract is the strict failure floor for the run
order, and the audit record at `--audit-out` records which gate
fired even when the gate sits ahead of step 4's network call.

- **PASS** — every step in §4 1-8 completed end-to-end, every gate
  inside those steps held, `scripts/validate_d_one_live_run_evidence.py`
  exited zero against the produced audit record, the A19 plan
  re-bind in §4 step 7 confirmed the pinned `plan_sha256` resolves
  to the on-disk plan, every per-image M5 review decision is `pass`,
  AND every E1-E10 item in `d-one-live-run-readiness.md` §8 carries
  quoted evidence from this specific trial. PASS is the only
  outcome that flips the status block in §1 to `VERIFIED`. A green
  `validate_d_one_live_run_evidence.py` exit alone is **necessary,
  not sufficient** — the readiness §8 walk is the sufficient
  condition. No PASS claim — top-line or per-step — may be recorded
  anywhere (this packet, the readiness file, the audit record, a
  commit message, a slide, a chat message) until that full chain
  holds.

- **FAIL** — the trial entered §4 (the operator invoked the run
  order) AND a `d-one-live-run-readiness.md` §7 F1-F17 gate fired
  at any point inside §4, regardless of whether the gate sat
  before, during, or after step 4's network call. The FAIL surface
  is exactly F1-F17 — including the pre-network gates F1 / F2 / F3 /
  F4 / F5 / F17 and the network / post-network gates F6-F16. A
  non-zero exit from `scripts/validate_d_one_live_run_evidence.py`
  at §4 step 6 and an A19 plan-rebind mismatch at §4 step 7
  (pinned-but-drifted or pinned-but-missing plan) are both already
  inside F15 (the audit-record schema and cross-check gate — F15
  enumerates `A2 / A10 schema gate OR any A11-A19 cross-check`,
  and A19 is one of those cross-checks); they are not separate
  FAIL surfaces, they are F15 in practice. A
  `validate_pptx_contract.py` failure at §4 step 8 is **not**
  inside F1-F17 — it is an E9 PASS-evidence gap (see readiness §8
  E9 and the UNVERIFIED bullet below); it prevents PASS but does
  not trigger the §5 rollback contract on its own. The §5
  stop-condition contract applies on F1-F17 — the workspace and
  `--assets-dir` are rolled back per
  `d-one-live-integration-design.md` §7, and the audit record at
  `--audit-out` is the single artifact that survives rollback (it
  documents the gate that fired — A1, A13). A FAIL trial is **not**
  a PASS regardless of how many steps in §4 completed before the
  stop, and a re-run is a separate trial requiring fresh M1-M6
  approvals.

- **BLOCKED** — the operator looked at §3 BEFORE invoking any §4
  step and saw at least one precondition unmet, so the trial never
  started. **No live call has been made, no §4 step has been run,
  and no `--audit-out` audit record has been produced.** BLOCKED
  specifically covers, but is not limited to: repo not at the
  audited commit; mock / local self-tests not green on this
  checkout; any `d-one-live-integration-design.md` §13 TODO open
  (today this includes the live-mode flag on
  `scripts/run_d_one_generation.py`, which is not yet wired — so
  the §4 step 4 CLI surface does not exist on this checkout);
  endpoint allow-list file (R1), descriptor vocabulary file (V1),
  or audit-record runtime validator (A2) absent from the repo; any
  M1-M6 approval not recorded in writing with named reviewer and
  ISO-8601 UTC date BEFORE the trial; M4 disable switch on; deck
  not synthetic-only; or the CLI surface that the packet drives
  changed in a way the operator has not re-audited. BLOCKED is
  **not** a PASS and **not** a FAIL — the status block in §1 stays
  `UNVERIFIED`. A packet adopted on the current development
  checkout resolves to BLOCKED at §3, because the live-mode CLI
  flag is intentionally TODO until the §13 work is requested as a
  separate review. Once the operator invokes any §4 step the
  BLOCKED window closes; from that point on the readiness §7
  contract owns the failure boundary and any F1-F17 firing (even
  the pre-network F1 / F2 / F3 / F4 / F5 / F17 gates that overlap
  in subject matter with §3 preconditions) is FAIL, not BLOCKED.

- **UNVERIFIED** — the resting state of the Real D-One path. It
  is BOTH the static status recorded in §1 and in
  `d-one-live-run-readiness.md` §1, AND the practical operator-facing
  state after any walk that does not produce PASS. UNVERIFIED is
  the state the status block holds before any trial, between
  trials, after any FAIL walk, after any BLOCKED walk, AND after
  any walk that mechanically completes §4 1-8 but cannot quote
  every E1-E10 item from `d-one-live-run-readiness.md` §8. An
  E1-E10 item missing while no F1-F17 gate fired is "not PASS"
  per readiness §8 ("A run that misses any of E1–E10 is **not**
  PASS, regardless of how 'good' the generated images look"); the
  trial is incomplete, not FAIL. Concrete examples that resolve to
  UNVERIFIED rather than FAIL: E1 mock self-test regression on the
  same checkout, E2 live verification matrix not yet exercised, E8
  materialize gate failure post-trial, E9 PPTX export or contract
  failure, E10 drift in the readiness / design / policy files
  unrecorded in `evidence_notes`. PASS is the only transition out
  of UNVERIFIED. A copy of this packet on disk, a green self-test
  of `scripts/validate_d_one_live_run_evidence.py`, and a green
  validate against the synthetic baseline at
  `examples/d_one_live_run_evidence_template.json` are each
  individually **insufficient** to change UNVERIFIED — none of them
  describes a real live run with quoted §8 evidence.

This section is operator-facing prose. The validator's `run_outcome`
field and per-request `outcome` field already enforce the
machine-level half of these states inside the audit record. The
four words above are the human-level summary an operator writes on
top of the validator's exit code, the readiness §7 F1-F17 fail-gate
contract, and the readiness §8 PASS walk — they map to the same
evidence, never replace it.

## 3. Pre-trial preconditions

None of the steps below may proceed unless **all** of the following
already hold on the company machine. If any is missing, the trial
stops here, no live call happens, and the top-line outcome is
**BLOCKED** (§2).

- The company-machine repo is at the same commit as the development
  machine the operator audited (see `references/internal-trial-record.md`
  for the one-way GitHub flow).
- The mock / local path passes on the same checkout
  (`references/d-one-live-run-readiness.md` §8 E1):

  ```bash
  TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/done_image_adapter.py --self-test
  TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_d_one_generation.py --self-test
  TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/materialize_image_assets.py --self-test
  TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/image_asset_acceptance_smoke.py --self-test
  TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/acceptance_smoke.py --self-test
  TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/verify_skill_package.py
  TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/package_skill.py --self-test
  TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_d_one_live_run_evidence.py --self-test
  ```

- The §13 TODOs in `references/d-one-live-integration-design.md` are
  each resolved as separate explicit user requests with their own
  review. Until they are, the live path stays unwired and there is
  nothing for this packet to drive — the trial is mock-only until
  every TODO is closed.
- The endpoint allow-list file exists, the descriptor vocabulary file
  exists, and an audit-record runtime validator is wired (R1, V1, A2).
  The packet does not invent any of those; it requires them.
- M1, M2, M3, M4 approvals (`d-one-live-run-readiness.md` §6) are
  recorded **in writing, with named reviewers and ISO-8601 UTC dates,
  BEFORE the trial starts.** A standing "this team may use D-One"
  approval is not sufficient — each item must be recorded for THIS
  specific deck and THIS specific endpoint.
- The disable switch (M4) is off, flipped by the named operator
  recorded in M4. The runtime gate refuses any live call when the
  switch is on.
- The trial deck is synthetic-only. No real customer name, partner
  name, deal name, product codename, or sensitive report text appears
  anywhere in the deck, the manifest, or the prompts. A first trial
  against real-data inputs is out of scope.

## 4. Run order on the company machine

Each step gates the next. If a step fails or errors:

- A `d-one-live-run-readiness.md` §7 F1-F17 gate firing (the
  canonical surface is steps 2-7 — step 2/step 3 fire F3, step 4
  fires F1 / F2 / F4 / F5 / F6-F13, step 5 fires F14, step 6 fires
  F15, step 7 fires F15 via A19) aborts the trial under §5 stop
  conditions and produces the audit record from §6 — top-line
  outcome is **FAIL** per §2. The §5 rollback contract applies.
- An E1-E10 PASS-evidence gap that does not trigger an F1-F17 gate
  — the canonical case is `scripts/materialize_image_assets.py` /
  `scripts/export_pptx.py` / `scripts/validate_pptx_contract.py`
  at step 8 (E8 / E9), and step 1 errors that loop back to E1 mock
  self-test regression — leaves the trial mechanically incomplete
  and the readiness §1 status at UNVERIFIED per §2. The §5
  rollback contract is **not** invoked on its own when no F1-F17
  gate fired; the operator records the E-gap and the status block
  stays UNVERIFIED.

No PASS claim is allowed in either case; see §2 for the full
outcome contract.

1. **Prepare the workspace.** Stage 1-6 are agent-driven today; use
   the existing `scripts/prepare_workspace.py` orchestrator against a
   synthetic source under `examples/` (or an operator-supplied
   synthetic source). No real data.
2. **Adapt the plan.** Run `scripts/done_image_adapter.py
   --workspace WS --spec spec.json` against the prepared workspace.
   The adapter scans every prompt against its full deny list and
   writes `<workspace>/d_one_adapter_plan.json` if every gate passes.
3. **Re-validate the plan non-mutatingly.** Run
   `scripts/done_image_adapter.py --validate-plan --workspace WS
   --plan <workspace>/d_one_adapter_plan.json`. This re-runs the
   schema + cross-checks + the per-prompt safety scan against the
   on-disk plan; the audit record's `plan_sha256` (A3) will pin this
   exact byte sequence.
4. **Live call.** Run the live-mode `scripts/run_d_one_generation.py`
   (TODO — flag not added today; see `d-one-live-integration-design.md`
   §13) with `--workspace WS --plan
   <workspace>/d_one_adapter_plan.json --assets-dir DIR --audit-out
   <audit-out>.json` against the approved sandbox endpoint. The
   runner re-validates the plan one more time, makes one approved
   network call per request, writes image bytes under `--assets-dir`
   only (`d-one-live-integration-design.md` §6), and writes the
   audit record at `--audit-out` (§6 below). The trial uses ONE
   request first; multi-request runs come later.
5. **Per-image manual review (M5).** For every `requests[].outcome
   == "ok"` row, a named reviewer inspects the produced image and
   records pass / fail with the reason. A single fail forces the §7
   rollback path; record M6 cleanup in the same audit record.
6. **Validate the audit record.** Run
   `scripts/validate_d_one_live_run_evidence.py <audit-out>.json`.
   Every G1-G11 gate must pass. Schema PASS alone is not enough —
   the cross-checks A11-A18 are layered on top.
7. **Re-bind the pinned plan (A19).** Run
   `scripts/done_image_adapter.py --validate-plan --workspace WS
   --plan <the plan whose sha256 == record.plan_sha256>`. A
   pinned-but-drifted or pinned-but-missing plan is FAIL.
8. **Materialize and export.** Run
   `scripts/materialize_image_assets.py --workspace WS --assets-dir
   DIR` then `scripts/export_pptx.py --workspace WS --output
   out.pptx` then `scripts/validate_pptx_contract.py --pptx
   out.pptx`. Every gate must pass (E8, E9). A failure at step 8 is
   an E-evidence gap (E8 or E9), **not** an F1-F17 firing — it
   prevents PASS but does not trigger the §5 rollback contract on
   its own; the readiness §1 status stays UNVERIFIED per §2 and
   the operator records the gap.

If steps 1-8 all PASS, walk `d-one-live-run-readiness.md` §8 E1-E10
and quote the evidence for each item. Only then may the status in
§1 of the readiness file move from UNVERIFIED to VERIFIED. Anything
short of that — even step 8 PASS — leaves the status UNVERIFIED.

## 5. Stop conditions

If any of `references/d-one-live-run-readiness.md` §7 F1-F17 fires,
or any approval in §6 M1-M6 is missing, the trial stops immediately:

- the workspace and `--assets-dir` are rolled back to their pre-call
  state per `d-one-live-integration-design.md` §7;
- the audit record at `--audit-out` is the single artifact that
  survives the rollback (it documents the stop condition — A1, A13);
- a fail-closed trial is **not** a PASS, regardless of how many
  steps in §4 completed before the stop;
- a re-run is a separate trial and requires fresh M1-M6 approvals.

The packet does not contain a "ship it anyway" branch. F1-F17 and
M1-M6 are non-negotiable.

## 6. Evidence to collect

Exactly one audit record at `--audit-out`. The record's shape is
`schemas/d_one_live_run_evidence.schema.json`; the field-by-field
contract is `d-one-live-run-readiness.md` §5 (A1-A10) plus §5.1
(A11-A19). A synthetic, schema-valid AND cross-check-valid baseline
ships at
`examples/d_one_live_run_evidence_template.json` — copy it, replace
every placeholder field with the values produced by the actual
trial, and re-run `scripts/validate_d_one_live_run_evidence.py`
against the result. The template's `note` field is
`Synthetic template for a D-One live-run evidence record. Replace
all placeholder values before any PASS claim.` — leave that note as
template-only wording until the record genuinely describes a real
live run, then replace it (the schema requires the literal
`D-One live-run evidence record` sentinel to remain).

The record carries:

- the pinned `plan_sha256` (A3);
- one per-request row (A4-A5) with outcome, opaque endpoint label,
  output magic-byte label, output sha256, and elapsed time;
- the resulting `<assets-dir>/<id>.<ext>` sha256 (A6 — for
  later cross-check against `materialize_image_assets.py`);
- the M1-M6 approval references and per-image review decisions (§7);
- the M4 operator label and the M4 disable-switch state at run time
  (must be `off` per the schema enum).

The record carries **no** raw source text, **no** raw prompt text,
**no** raw output bytes, **no** customer identifiers, **no**
credentials, **no** absolute paths, **no** URLs (A7). The schema's
positive-whitelist `pattern` locks refuse most of those at the
schema layer; the runtime G11 scan in
`scripts/validate_d_one_live_run_evidence.py` covers the residual
credential / PII / internal-endpoint / raw-source-marker /
public-upload shapes.

A copy of the record stays on the company machine. Uploading,
posting, or emailing it is a separate explicit human action — not
part of the trial (A8).

## 7. Allowed prompts and approvals

- Prompts must be assembled from the approved descriptor vocabulary
  (V1-V5). No proper nouns, no quoted source text, no source-derived
  sentences, no dates, no numbers from the source body.
- The adapter's full deny list (`scripts/done_image_adapter.py`)
  re-runs on the plan; the live runner re-runs it again before the
  network call (V4).
- Approvals required (in writing, with named reviewer and ISO-8601
  UTC date, BEFORE the trial): M1 (endpoint), M2 (vocabulary), M3
  (per-deck), M4 (operator who flipped the disable switch),
  M5 (per-image manual review, one row per `outcome == "ok"`
  request), and M6 (cleanup decision) if any M5 row is `fail`.

## 8. When to stop adopting this packet

The packet is the gate for the **first** live trial only. After the
first live run produces a PASS audit record AND every E1-E10 item
in `d-one-live-run-readiness.md` §8 carries quoted evidence, the
status block in §1 of the readiness file moves to VERIFIED for that
specific endpoint / vocabulary / deck combination, and subsequent
runs against the same combination are gated by the readiness file
alone — not by this packet.

A second trial against a new endpoint, a new vocabulary, or a new
deck is a fresh first trial for that combination and re-uses the
checklist in §4.

## 9. Cross-references

- `references/d-one-live-run-readiness.md` — the readiness
  checklist this packet drives (R, V, A, M, F, E gates).
- `references/d-one-live-integration-design.md` — the design the
  live path follows; §13 TODOs are the prerequisites this packet
  assumes are closed.
- `references/d-one-image-policy.md` — the broader policy these
  trial rules sit inside.
- `references/security-policy.md` (`SECURITY.md`) — the fail-closed
  checks the security scan applies to every artifact, including the
  audit record.
- `references/clean-room-policy.md` — the clean-room constraint
  forbidding any copy from an external reference implementation
  into the trial wiring or this packet.
- `references/internal-trial-record.md` — the prior Qoder runtime
  smoke trial on the company machine (link mode); this packet is
  the equivalent gate for the live-D-One first trial and follows
  the same record-the-evidence discipline.
- `schemas/d_one_live_run_evidence.schema.json` — the audit record
  contract sketch the packet's §6 evidence is shaped against.
- `scripts/validate_d_one_live_run_evidence.py` — the validator
  the audit record MUST pass before any PASS claim.
- `examples/d_one_live_run_evidence_template.json` — synthetic
  schema-valid AND cross-check-valid baseline an operator copies
  and edits.
