# Internal Trial Record — Company-Machine D-One Discovery (BLOCKED)

Internal-only, clean-room. This file is an event record of a
**company-machine D-One discovery probe** — an operator walked the §3
pre-trial precondition checklist in
`references/d-one-live-trial-packet.md`, found unmet preconditions,
and stopped BEFORE any §4 step was invoked. The probe is a sibling
of, not a replacement for, the prior Qoder link/runtime smoke trial
recorded in `references/internal-trial-record.md`; it is scoped to a
different question (live-D-One readiness, not Qoder runtime
recognition).

This document records what was deliberately NOT done. It does not
add runtime behavior, does not modify any script, schema, or
template, and does not rebuild the package. No real D-One was
called, no MCP server was reached, no public network was touched,
no telemetry was emitted, no model API was used, no image-search
backend was queried, no full-slide screenshot was produced.

## Trial type

Company-machine **synthetic-only D-One discovery probe**. The
operator opened `references/d-one-live-trial-packet.md` on the
company machine and read down through §3 (Pre-trial preconditions)
to determine whether the first live D-One run could proceed. The §3
checklist flagged unmet items (see [Blockers](#blockers) below), so
the operator stopped at §3 and did not enter §4. Per
`references/d-one-live-trial-packet.md` §2, that stop-point resolves
the trial to top-line outcome **BLOCKED** — declared *before* any §4
step was invoked, so no `<audit-out>` audit record was produced and
no network call was attempted.

## Top-line outcome

**BLOCKED.**

Scoped per `references/d-one-live-trial-packet.md` §2 to:

- a single discovery walk,
- on a single internal company machine,
- against the §3 precondition checklist only,
- with no §4 step invoked,
- against the source state at commit
  `0f426873caf0f1107462eb63b5840847c49a16bf` (see
  [Git state](#git-state) below).

BLOCKED is **not** a PASS and **not** a FAIL. Per
`references/d-one-live-trial-packet.md` §2, the readiness §1 status
block in `references/d-one-live-run-readiness.md` stays at
**UNVERIFIED** on this outcome.

## Real D-One status after this probe

`references/d-one-live-run-readiness.md` §1: "Real D-One path:
UNVERIFIED. There is no live flag, no MCP wiring, no model-API
client, no network call." This probe did not change that line.

- Real D-One: **UNVERIFIED**, **uncalled** during this probe.
- No live network call was issued; no sandbox endpoint was
  contacted; no production endpoint was contacted.
- No image bytes were produced; no `--assets-dir` was populated.
- No `--audit-out` evidence JSON was produced. The
  `scripts/validate_d_one_live_run_evidence.py` validator was not
  exercised against any record from this probe.

## Evidence

- **Audit record:** none. Per
  `references/d-one-live-trial-packet.md` §2, BLOCKED is declared at
  the §3 precondition checklist, before any §4 step is invoked, and
  is the only one of the four top-line outcomes that produces no
  `<audit-out>` artifact. This is by design — the only artifact that
  survives a FAIL rollback per
  `references/d-one-live-trial-packet.md` §5 is the audit record at
  `--audit-out`, but BLOCKED never enters §4 to produce one in the
  first place.
- **Image bytes:** none. No `<assets-dir>/<id>.<ext>` files were
  written.
- **Plan SHA-256:** none. No `d_one_adapter_plan.json` was adapted,
  pinned, or re-bound (A3 / A19 not exercised).
- **Per-image M5 review decisions:** none. Zero requests reached the
  network boundary.
- **This document** is the single durable record of the probe. The
  company machine's on-disk path, machine identifier, internal
  endpoints, credentials, account IDs, employee identifiers, and
  any screenshots are intentionally **not** recorded here, per
  `SECURITY.md` and `references/security-policy.md`.

## Git state

At the moment the discovery probe was walked, the source state
being inspected on both the development machine and the company
machine (downloaded via the one-way GitHub flow described in
`references/internal-trial-record.md`) was:

- Branch: `main`.
- `git status`: clean working tree (no untracked files, no
  modifications).
- HEAD commit: `0f426873caf0f1107462eb63b5840847c49a16bf`.

The git state is recorded here as a coordinate for the probe, not
as a reproduction target. A future discovery walk against a
different HEAD commit is a different probe and requires its own
record.

## Blockers

Each item below is a §3 precondition from
`references/d-one-live-trial-packet.md` that the discovery probe
found unmet on the audited commit, with the cross-reference back to
the readiness gate it satisfies. Any single unmet item is sufficient
to resolve the trial to BLOCKED per §2; all five are unmet on this
commit.

1. **`scripts/run_d_one_generation.py` has no `--live-mode` flag
   and no `--audit-out` flag.** The §4 step 4 CLI surface the trial
   packet drives (`--workspace ... --plan ... --assets-dir ...
   --audit-out ...` in live mode) does not exist on this checkout.
   `references/d-one-live-integration-design.md` §13 lists this as
   TODO and `references/d-one-live-trial-packet.md` §2 names it
   explicitly in its BLOCKED clause ("today this includes the
   live-mode flag on `scripts/run_d_one_generation.py`, which is
   not yet wired"). Without these flags there is no §4 surface to
   invoke.
2. **No endpoint allow-list file exists in the repo.** This
   violates `references/d-one-live-run-readiness.md` §3 R1
   ("Maintained allow-list file"). Per R3 the runner must refuse
   any endpoint not on the allow-list, and per R3 a missing or
   empty allow-list is equivalent to "every endpoint denied" — so
   even if §4 step 4 were wired, no endpoint would be approvable
   on this checkout.
3. **No descriptor vocabulary file exists in the repo.** This
   violates `references/d-one-live-run-readiness.md` §4 V1
   ("Vocabulary file in repo"). Per V3 the closed-enumeration
   contract cannot be enforced without the file, so no prompt is
   assemblable on this checkout and the §4 step 2 adapter has
   nothing to validate against.
4. **The audit-record runtime validator hook is not wired.** This
   violates `references/d-one-live-run-readiness.md` §5 A2
   ("audit-record runtime validator wired into the runtime
   script"). `scripts/validate_d_one_live_run_evidence.py` exists
   as a standalone validator with `--self-test`, but no runtime
   call site in `scripts/run_d_one_generation.py` invokes it as
   part of a live run, so a hypothetical live run on this
   checkout could not write an audit record that the runtime
   itself had verified.
5. **No M1-M6 approvals are recorded in writing for this deck and
   this endpoint.** Per `references/d-one-live-run-readiness.md` §6
   and `references/d-one-live-trial-packet.md` §3 / §7, M1
   (endpoint), M2 (vocabulary), M3 (per-deck), M4 (disable-switch
   operator), M5 (per-image), and M6 (cleanup) must each be
   recorded in writing with named reviewer and ISO-8601 UTC date
   BEFORE the trial starts; a standing "this team may use D-One"
   approval is not sufficient. No such write-up exists for this
   discovery probe.

## Why this is expected, not a product failure

The BLOCKED outcome is the protocol working as designed.
`references/d-one-live-run-readiness.md` §1 declares the real D-One
path UNVERIFIED, `references/d-one-live-integration-design.md` §13
lists the gating TODOs that must be resolved as separate explicit
user requests, and `references/d-one-live-trial-packet.md` §2 / §3
define a discovery walk that resolves to BLOCKED whenever those
TODOs are open. A discovery walk that returns BLOCKED on this
checkout is precisely the safety mechanism those documents
describe — it stops the operator before any network call is
attempted, before any plan is adapted, and before any image byte
is materialized.

A trial that produces BLOCKED today does not indicate a defect in
the local pipeline, the mock / local path (which stays VERIFIED
per `references/d-one-live-run-readiness.md` §1), the adapter, the
materializer, the exporter, or the PPTX contract validator. It
indicates that the live-D-One TODOs in
`references/d-one-live-integration-design.md` §13 have not yet
been requested as their own reviews, and that the corresponding
artifacts (R1, V1, A2 hook, M1-M6 approvals) have not yet been
authored — by intent, not by oversight.

## Next gate

Either of the following is a reasonable next step. Neither is in
scope for this record.

- **Resolve `references/d-one-live-integration-design.md` §13
  TODOs.** Each TODO is its own explicit user request and its own
  review. Until all are resolved, every future discovery walk
  against this commit (or a commit that does not advance the §13
  surface) will resolve to BLOCKED at §3 on the same five items
  above.
- **Author the R1 / V1 / A2 hook artifacts and the M1-M6 written
  approval template.** These are prerequisites called out in
  `references/d-one-live-run-readiness.md` §3 / §4 / §5 / §6 and
  in `references/d-one-live-trial-packet.md` §3 / §7. None of
  them is wired today.

## Cross-references

- `references/d-one-live-trial-packet.md` — defines the BLOCKED /
  FAIL / PASS / UNVERIFIED outcome contract this probe applies
  (§2), the §3 precondition checklist the probe walked, and the
  §4 run order the probe did not enter.
- `references/d-one-live-run-readiness.md` — the readiness
  checklist whose R1, V1, A2, and M1-M6 gates this probe found
  unmet.
- `references/d-one-live-integration-design.md` — the design doc
  whose §13 TODOs gate live-mode wiring on
  `scripts/run_d_one_generation.py`.
- `references/d-one-image-policy.md` — the broader image-policy
  envelope these trial rules sit inside.
- `references/internal-trial-record.md` — the earlier Qoder
  link/runtime smoke trial on the company machine. That trial
  resolved to `LIVE_QODER_RUNTIME_PASS` in link mode; this
  discovery probe is a sibling event record covering a different
  question and resolved to BLOCKED.
- `SECURITY.md` and `references/security-policy.md` — the
  fail-closed privacy rules forbidding any company-machine
  identifier, endpoint, credential, account ID, employee ID, or
  screenshot from appearing in this record.
