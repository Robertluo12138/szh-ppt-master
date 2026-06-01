# Qoder import handoff checklist

Internal-only, clean-room. This document is the handoff for testing the locally
packaged skill archive on a separate company machine that has Qoder installed.
This repo's local development environment does **not** have Qoder, so the live
Qoder import path is **UNVERIFIED here**.

## Verification status — read first

- **VERIFIED locally (static archive only)**: `scripts/verify_skill_package.py`
  (five fail-closed gates over the package surface) and
  `scripts/package_skill.py` (deterministic builder + post-write archive gates)
  both pass against the current repo. The archive at `dist/szh-ppt-skill.zip`
  was produced by the deterministic builder and re-inspected against the
  archive-level `archive_no_forbidden`, `archive_doc_references_present`, and
  `archive_members_allow_listed` gates.
- **UNVERIFIED here (live Qoder)**: nothing in this repo proves that Qoder can
  load, install, register, list, or invoke the skill from this archive. The
  exact Qoder CLI command, package directory layout, runtime entry point, and
  permission surface are not exercised on this machine. Treat every Qoder step
  below as a **placeholder** to confirm on the target machine.

Do not claim end-to-end "Qoder import succeeded" in any artifact (PR, status
update, doc, follow-up checklist) until the target machine produces the
evidence enumerated in [Pass / fail evidence to collect](#pass--fail-evidence-to-collect).

## Package under test

- Path (relative to the repo root): `dist/szh-ppt-skill.zip`
- SHA-256 (current archive on the build machine, recorded against a build
  that does NOT yet include this checklist):
  `ab0d9a9430a555bbb73345229b5fb390e7be7376b06146b431e36124fb5a412e`.
  The current archive bytes pre-date this doc's existence; if you re-run
  `scripts/package_skill.py` after this doc has been committed, the
  rebuilt archive WILL include `references/qoder-import-checklist.md` as a
  member (because `references/` is in the builder's explicit allow-list),
  the bytes will change, and the SHA-256 above will no longer match.
- SHA-256 recording protocol for any rebuild: do NOT update the literal
  value above for a rebuilt archive — embedding a rebuilt archive's hash
  inside a doc that itself ships in that rebuilt archive has no
  fixed-point (each update to the embedded hash changes the archive's
  bytes again). Instead, on the source / build machine, run
  `shasum -a 256 dist/szh-ppt-skill.zip` immediately before transfer and
  record the value in BOTH the handoff transmission record AND the
  gitignored sidecar `dist/szh-ppt-skill.zip.sha256`. The sidecar lives
  outside the archive (`dist/` is gitignored, so the sidecar is not in
  the tracked tree, is not in `git ls-files`, and is therefore excluded
  from any archive `scripts/package_skill.py` produces).
- Doc location in the source tree: `references/qoder-import-checklist.md`.
  This is a maintainer / handoff-operator reference. It is NOT linked from
  any package-facing doc (`SKILL.md` / `README.md` / `SECURITY.md`) so the
  shipped archive cannot carry a dangling link to it regardless of whether
  the checklist itself ends up inside a future rebuilt archive.
- Builder: `scripts/package_skill.py` (deterministic; fixed timestamp
  `1980-01-01`, fixed `create_system`, fixed `external_attr`, sorted POSIX
  member order, no archive comment). Two clean builds against the same
  tracked tree produce byte-identical archives, so a recorded hash is
  reproducible from the same source state.
- Pre-flight: `scripts/verify_skill_package.py` (five fail-closed gates over
  the tracked + untracked-not-ignored surface).
- Re-inspection: `scripts/package_skill.py` re-opens the produced archive and
  runs `archive_no_forbidden` (G1 re-run over the member list),
  `archive_doc_references_present` (every `scripts/<name>.py` and
  `schemas/<name>.schema.json` referenced by a shipped doc is also an archive
  member), and `archive_members_allow_listed` (every member's top-level path
  component is in the explicit allow-list).

If the archive is rebuilt, re-record the SHA-256 in the handoff transmission
record and in `dist/szh-ppt-skill.zip.sha256` (not in this document) and
re-run the pre-import checks below.

## Pre-import checks (on the source / build machine)

Run these from the repo root **before** copying the archive to the target
machine. All five must pass.

```
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/verify_skill_package.py
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/package_skill.py --self-test
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/acceptance_smoke.py --self-test
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/image_asset_acceptance_smoke.py --self-test
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_scaffold.py
```

Then compute and record the archive hash for this build, both in the
handoff transmission record and in the gitignored sidecar `dist/szh-ppt-skill.zip.sha256`:

```
shasum -a 256 dist/szh-ppt-skill.zip
shasum -a 256 dist/szh-ppt-skill.zip > dist/szh-ppt-skill.zip.sha256
```

(`dist/` is gitignored, so the sidecar file does not enter the archive and
is therefore safe to record the archive's own hash in.)

If any pre-import check fails, **do not** copy the archive to the target
machine; fix the underlying issue and rebuild, then re-compute and re-record
the hash.

## Transfer to the target machine

- Transfer via the company-approved internal channel only. Do not upload the
  archive to a public service (no public file-sharing site, no public
  pastebin, no public gist, no public chat upload). Do not transfer through
  any service that may cache, log, or index the bytes.
- Transfer the `dist/szh-ppt-skill.zip.sha256` sidecar alongside the `.zip`
  through the same channel.
- On arrival, re-confirm the SHA-256 on the target machine matches the
  sidecar value (and the value in the handoff transmission record). Refuse
  to import an archive whose hash disagrees.
- Keep the archive on local disk only; do not extract it into a network share
  or a cloud-synced folder.

## Import / install steps (PLACEHOLDERS — confirm on target)

The exact Qoder CLI surface is **not exercised on this machine**. Treat the
commands below as schematic placeholders. The operator on the target machine
should:

1. Locate the Qoder CLI on the target machine and capture its exact name and
   help output (e.g. `qoder --help`, `qoder skill --help`,
   `qoder plugin --help`). Record both the discovered command name and its
   declared subcommand surface in the handoff report.
2. Identify the canonical import / install / register subcommand for a local
   skill archive (likely shapes: `qoder skill install <path>.zip`,
   `qoder skill import <path>.zip`, `qoder plugin install <path>.zip`, or an
   equivalent). Do **not** guess; the operator must confirm against the
   running CLI's help text and record the exact command used.
3. Run the confirmed install command against `dist/szh-ppt-skill.zip` (local
   path on the target machine). Capture stdout, stderr, and exit code.
4. If Qoder prompts for elevated permissions, network access, telemetry, or
   credentials, **stop** and refer to [Stop conditions](#stop-conditions)
   before proceeding.

If the Qoder CLI is not on the target machine, or the install subcommand
cannot be confirmed against the CLI's own help text, abort the handoff and
report `LIVE_IMPORT_UNVERIFIED — CLI surface not confirmable on target`.

## Post-import checks (on the target machine)

After a confirmed install command exits 0, run the post-import surface
without leaving the local machine:

1. **Registration**: list installed skills (e.g. `qoder skill list` or the
   confirmed equivalent). Confirm the skill name `editable-ppt` (from
   `SKILL.md` frontmatter) appears and that its declared description matches
   the SKILL.md `description` field. Capture stdout verbatim.
2. **Inspection**: show the skill's metadata / description / commands through
   the Qoder CLI's own inspection subcommand if one exists. Capture stdout
   verbatim. Compare against the shipped `SKILL.md`.
3. **Static-surface re-check**: confirm the installed package on disk (if
   Qoder exposes the install path) carries the same files the archive shipped
   and that no extra root files appeared. If Qoder unpacks elsewhere, record
   the install path in the report.
4. **No-op invocation**: invoke the skill through Qoder with a no-op /
   help-only request that does NOT load any source document, does NOT trigger
   any generation, and does NOT make any external call. Capture stdout
   verbatim. The expected behavior is for the skill to respond with its
   declared usage surface; any prompt for credentials / network / telemetry
   is a stop condition.

If Qoder does not expose a `list` / `inspect` / no-op-invoke surface, record
the gap in the handoff report and stop after the install step.

## Synthetic-only runtime smoke guidance

If — and only if — the operator on the target machine has explicit clearance
to exercise the runtime pipeline through Qoder, the smoke MUST be synthetic:

- Use **only** the in-repo synthetic fixtures (e.g.
  `examples/synthetic_authoring_trial/`). Do not author or paste any new
  source document on the target machine. Do not load any real company report,
  customer name, account id, internal screenshot, or sensitive prompt.
- Run the smoke through the same fail-closed scripts the local build already
  exercises (`scripts/acceptance_smoke.py`,
  `scripts/image_asset_acceptance_smoke.py`). These scripts default to
  `tempfile.TemporaryDirectory()` outside the repo and outside Qoder's state
  directory; do not redirect output into Qoder-managed paths.
- The runtime contract for **this import-verification smoke** is mock-only:
  D-One stays local and mock-only; no MCP call; no public network; no model
  API; no image search; no full-slide screenshot; no raw source text sent to
  any image prompt. If Qoder offers to wire any of those into the
  *verification smoke*, **stop** — you are confirming the archive loads, not
  producing a deck. The separate *operational* MVP run is governed by
  [`qoder-agent-mvp-runbook.md`](qoder-agent-mvp-runbook.md), where the
  packet / resume path issues no generator prompts and agent-driven generation
  is confined to the repo's audited (deny-list-validated, logged) pipeline;
  none of that applies to this import-verification smoke.

Document any deviation from the synthetic-only path as a handoff failure.

## Pass / fail evidence to collect

For every step above, capture the following back into the handoff report
(plain text, no screenshots of real data; redact any incidental absolute
paths that identify the target operator):

- The exact command line invoked, verbatim.
- Exit code.
- stdout and stderr (truncate only with an explicit `... [N lines elided]`
  marker; never silently shorten).
- Any prompt Qoder displayed before / during / after execution, with the
  operator's literal response.
- For the install step: the canonical Qoder command name and subcommand
  discovered in step 1 of [Import / install steps](#import--install-steps-placeholders--confirm-on-target).
- For the list / inspect steps: the registered skill name and description
  Qoder reports, side-by-side with the values from this repo's `SKILL.md`
  frontmatter.
- For any synthetic smoke: the temp directory the smoke wrote into, the exit
  code of each script, and the per-stage `[PASS] / [FAIL]` lines.
- The archive SHA-256 re-confirmed on the target machine, the value from
  the `dist/szh-ppt-skill.zip.sha256` sidecar transferred alongside, and a
  one-line note that they matched.

A handoff is **PASS** only when every step above produced the expected
evidence AND no stop condition fired. Anything else is **FAIL**; report it as
FAIL with the specific gate that did not produce the expected evidence.

## Stop conditions

Halt the handoff immediately, leave the install partially complete, and
return to Codex review with the captured evidence if any of the following
appears at any point:

- Qoder prompts for, requires, or implicitly attaches credentials of any
  kind (API key, OAuth token, JWT, bearer, password, certificate, SSH key,
  cloud profile).
- Qoder attempts public network egress: any outbound HTTPS / HTTP / S3 / FTP
  request, any DNS lookup for a non-loopback host, any background telemetry,
  any update check, any "send anonymous usage data" prompt.
- Qoder attempts to call D-One, any image-generation model, any MCP server,
  any external service, any model API, any image search, or any voice / video
  generator **during this import handoff**. None of these should fire while
  you are merely verifying that the archive imports. (Automated image
  generation belongs to the operational MVP run, where it is confined to the
  repo's audited, deny-list-validated, logged pipeline per
  [`qoder-agent-mvp-runbook.md`](qoder-agent-mvp-runbook.md); this import
  handoff itself never invokes any generator.)
- Any prompt or workflow asks for real company data, real customer names,
  real account ids, internal screenshots, raw report text, or sensitive
  prompt content.
- Qoder uploads, syncs, or copies the archive bytes, the install state, or
  any runtime output to an external destination without an explicit operator
  confirmation step that the operator can refuse.
- Qoder writes files outside the install directory it declared in step 1 of
  the install flow, into the user's home directory, into shared
  network / cloud-synced locations, or into the repo working tree.
- The archive SHA-256 on the target machine disagrees with the
  `dist/szh-ppt-skill.zip.sha256` sidecar transferred alongside (or with the
  value in the handoff transmission record).

In every stop case, do **not** retry under elevated permissions, do **not**
attempt to bypass the prompt, and do **not** edit Qoder configuration to
"unblock" the failure. Capture the evidence and report.

## Reporting results back for Codex review

Open a follow-up review request against Codex with:

1. The exact archive path, the SHA-256 from the
   `dist/szh-ppt-skill.zip.sha256` sidecar (computed on the source machine
   immediately before transfer), and the re-confirmed-on-target SHA-256
   (one-line note that they matched).
2. The discovered Qoder CLI surface (command name + help excerpt for the
   install / list / inspect subcommands actually used).
3. Per step, the captured evidence from
   [Pass / fail evidence to collect](#pass--fail-evidence-to-collect).
4. One of the following overall outcomes, in the report's top line, verbatim:
   - `LIVE_IMPORT_PASS — install + registration + no-op invoke + (optional)
     synthetic smoke all passed; no stop condition fired.`
   - `LIVE_IMPORT_FAIL — <step name>: <one-sentence summary of which gate
     produced unexpected evidence>.`
   - `LIVE_IMPORT_BLOCKED — <stop condition that fired>: <one-sentence summary
     including the exact prompt / network attempt / unexpected upload>.`
   - `LIVE_IMPORT_UNVERIFIED — <reason the handoff could not be completed,
     e.g. CLI surface not confirmable on target>.`
5. Any deviation from the synthetic-only smoke guidance, called out in its
   own paragraph. Absence of this paragraph implies "no deviation".

Codex review will treat anything other than `LIVE_IMPORT_PASS` as
non-shippable for Qoder. The locally verified static archive remains valid
for local-only use regardless of the live-import outcome; do not delete it on
a `FAIL` / `BLOCKED` / `UNVERIFIED` outcome.

## Out of scope for this checklist

- Live Qoder integration code in this repo. The repo continues to document
  Qoder CLI integration as **not implemented**; this checklist is a handoff
  contract, not an integration.
- Real D-One image generation, MCP calls, public network, telemetry, model
  APIs, image search, or any external service. These remain refused by the
  shipped scripts. The operational MVP run's audited image-generation pipeline
  (every prompt deny-list-validated and logged) is documented in
  [`qoder-agent-mvp-runbook.md`](qoder-agent-mvp-runbook.md), not here, and does
  not change what the shipped scripts do.
- Changes to PPTX export behavior, the render-model contract, the per-stage
  helpers, or the validator surface.
- Real or confidential data of any kind.
