#!/usr/bin/env python3
"""Operator-facing local readiness preflight for a future real-D-One trial.

This is a PREFLIGHT / READINESS command, not a live D-One runner. It tells a
company-machine operator whether a real D-One trial MAY start
(``PREFLIGHT_READY_FOR_MANUAL_TRIAL``) or exactly why it is BLOCKED
(``LIVE_D_ONE_BLOCKED``) WITHOUT calling D-One, MCP, network, model
APIs, Qoder runtime, image search, browsers, or telemetry.

CLI:
  python3 scripts/d_one_live_readiness_preflight.py \\
      --d-one-spec <path-to-spec.json> \\
      --descriptor-vocabulary <path-to-vocab.json> \\
      --endpoint-allowlist <path-to-allowlist.json> \\
      --preflight-audit <path-to-preflight.json> \\
      [--audit-out <path-to-readiness-audit.json>]

  python3 scripts/d_one_live_readiness_preflight.py --self-test

Inputs (every file is read once and never mutated):
  --d-one-spec            A schemas/d_one_adapter_plan.schema.json file
                          listing the D-One generation requests the operator
                          would put on the wire.
  --descriptor-vocabulary A schemas/d_one_descriptor_vocabulary.schema.json
                          file (V1/V2/V3/V6 contract sketch).
  --endpoint-allowlist    A schemas/d_one_endpoint_allowlist.schema.json
                          file (R1/R2/R3/R5/R6 contract sketch).
  --preflight-audit       A schemas/d_one_preflight_audit.schema.json
                          file (M1-M4 + R1 + V1 + audit-out path
                          placement contract sketch).
  --audit-out             OPTIONAL local path. When supplied, the same
                          readiness audit JSON written to stdout is ALSO
                          written verbatim to this path (must not be a
                          symlink, must not pre-exist, must not resolve
                          inside the repo source tree, parent must exist).

Local prerequisites validated. Every failure produces a blocker; any
blocker forces ``LIVE_D_ONE_BLOCKED``. ``PREFLIGHT_READY_FOR_MANUAL_TRIAL``
is reported only when every prerequisite below passes. PREFLIGHT_READY is
NOT a PASS for live D-One — the readiness file's
``Real D-One path: UNVERIFIED`` wording remains load-bearing; only an
actual trial whose audit record passes
``scripts/validate_d_one_live_run_evidence.py`` AND the §8 readiness
gates may flip that status to VERIFIED.

  P1 inputs_are_regular_non_symlink_files
  P2 inputs_parse_to_json_objects
  P3 schemas_valid (each input validates against its schema above)
  P4 vocabulary_synthetic_safe — the vocab's ``note`` carries the
     ``synthetic`` marker so the file admits it is a placeholder, not
     a real-customer-derived vocab. The schema's forbidden-token deny
     clause already refuses public/upload/raw/customer/confidential/
     screenshot/credential/password/secret + five compound phrases on
     every descriptor / taxonomy value, so the synthetic-marker check
     is the only residual contract this script enforces at the vocab
     layer.
  P5 allowlist_default_deny_active_when_empty — when ``entries`` is
     empty, R3 default-deny is the resting state and no endpoint may
     run; BLOCKED. URL / IP / internal-host / token / credential
     wording on every path-label / opaque-ref field IS refused at the
     schema layer by the positive-whitelist pattern locks (those
     patterns refuse ``:`` / ``@`` / ``#`` / ``/`` / ``\\``, so a
     URL / email / fragment / authority shape cannot pass at the
     schema layer). Multi-word PUBLIC-UPLOAD wording (the literal
     phrase ``public upload`` and its variants) is NOT refused at the
     schema layer on the four ``note`` fields — their whitelist
     admits letters / digits / spaces / `., ; ! ? ( ) -`, so the
     bare phrase ``public upload`` passes — nor on the spec request
     ``prompt`` field, which has no pattern at all; P13 covers that
     gap explicitly.
  P6 preflight_paths_local_safe_not_repo_output — every path label in
     the preflight (workspace / assets-dir / audit-out / allow-list /
     vocabulary path labels) passes local_path_is_safe AND does NOT
     start with a repo source-tree directory root (``scripts/``,
     ``schemas/``, ``templates/``, ``examples/``, ``references/``,
     ``dist/``). A workspace that overlaps the repo source tree would
     route audit bytes into the repo source.
  P7 spec_request_ids_synthetic_safe — every ``spec.requests[*].id``
     conforms to the synthetic identifier shape used by the descriptor
     vocab's ``synthetic_requests[*].id`` slot: lowercase identifier,
     leading letter, NO forbidden token (public / upload / raw /
     customer / confidential / screenshot / credential / password /
     secret as bounded tokens, plus compound full_slide / image_search
     / web_generation / page_generation / slide_generation across
     separator stacking). The d_one_adapter_plan schema does NOT
     pattern-lock the id (only non-empty string); this readiness gate
     brings the request id up to the same shape as the documented
     synthetic request example.
  P8 every_request_has_required_intent_dimensions — every request
     carries ``placement_role``, ``text_policy``, and
     ``subject_domain``, and every value is a member of the matching
     ``image_taxonomy.<dim>.allowed_values``. The adapter-plan schema
     makes those three optional; the readiness gate makes them
     mandatory because a live trial that omits intent dimensions
     cannot prove its prompts were intent-classified before going
     live. ``placement_role`` requires the vocab to declare its
     ``image_taxonomy.placement_role`` block — a vocab that omits the
     optional block forces BLOCKED.
  P9 no_local_asset_in_request_set — every ``spec.requests[*]
     .manifest_source`` equals ``d_one_local``. The schema enum lock
     already enforces this; the readiness gate re-checks as
     belt-and-braces so a tampered spec that drifts after schema
     validation still fails.
  P10 preflight_endpoint_label_in_allowlist — the preflight's
     ``endpoint_label`` matches some ``entries[*].endpoint_label`` in
     the allow-list. P5 catches the empty-allow-list resting state;
     this gate catches the residual case where a non-empty allow-list
     does not name the endpoint the preflight is pinned to.
  P11 no_positive_d_one_pass_claim — the preflight's ``note`` (the
     only free-form field whose pattern allows enough characters for
     a multi-word claim) does NOT contain a positive real-D-One PASS
     claim. Today ``Real D-One path: UNVERIFIED`` is load-bearing; a
     preflight that positively claims PASS would itself be evidence
     of a contract violation.
  P12 audit_out_path_safe_not_pre_existing_not_repo_output — when
     supplied, ``--audit-out`` (a) is not a symlink (broken or
     resolvable); (b) does not pre-exist; (c) does not resolve inside
     any repo source-tree directory (``scripts/`` / ``schemas/`` /
     ``templates/`` / ``examples/`` / ``references/`` / ``dist/``);
     (d) its parent dir exists.
  P13 free_form_field_public_upload_scan — scan every free-form field
     whose schema pattern admits a multi-word phrase (the four
     ``note`` fields plus the spec request ``prompt`` / ``intended_use``)
     for public-upload / public-sharing / public-hosting wording. The
     schema layer alone is not sufficient on these fields — the
     ``note`` whitelist admits letters / digits / spaces / basic
     sentence punctuation, and the spec request ``prompt`` has no
     pattern at all (only ``minLength: 1``). Honors the same
     strict-adjacency negation exemption as
     ``validate_d_one_live_run_evidence.py`` G11: on the BEFORE side
     one of ``no`` / ``not`` / ``never`` / ``without`` immediately
     preceding the deny phrase; on the AFTER side an optional
     ``is`` / ``are`` / ``was`` / ``were`` copula followed by
     ``forbidden`` / ``prohibited`` / ``denied`` / ``disabled`` /
     ``blocked`` / ``refused`` / ``banned`` / ``not used`` /
     ``not allowed`` / ``not permitted`` / ``not enabled``. So
     ``no public upload`` and ``public upload is forbidden`` are
     accepted as boundary wording; ``public upload of artifacts`` and
     ``share publicly`` fire.
  P14 free_form_field_credential_scan — scan every free-form field AND
     every identifier / label / ref / path-label slot the schema can
     admit credential / token-shaped wording into for credential
     WORDS (``token`` / ``api_key`` / ``api key`` / ``password`` /
     ``passwd`` / ``secret`` / ``client_secret`` / ``private_key`` /
     ``access_key`` / ``bearer`` / ``credential``) AND credential
     SHAPES (Stripe-style ``sk-test-...`` / ``sk-live-...`` key,
     JWT ``eyJ...`` three-part dot-separated blob, AWS access key
     ``AKIA...``, PEM marker ``-----BEGIN ``, 32+ contiguous hex
     blob, ``bearer <opaque>``). Scope: the six free-form fields
     P13 also walks (``d_one_spec.note`` /
     ``descriptor_vocabulary.note`` / ``endpoint_allowlist.note`` /
     ``preflight_audit.note`` plus the spec request ``prompt`` /
     ``intended_use``) AND the identifier slots whose schema pattern
     admits ``_`` / ``-`` / ``.`` separators —
     ``spec.requests[*].id`` /
     ``spec.requests[*].manifest_local_path`` /
     ``endpoint_allowlist.entries[*].{endpoint_label,
     destination_label, approval_reviewer_ref, security_review_ref}``
     and the preflight's ``endpoint_label`` / ``operator_label`` /
     ``allow_list_path_label`` / ``vocabulary_path_label`` /
     ``workspace_label`` / ``assets_dir_label`` /
     ``audit_out_path_label`` plus every ``approvals.*_ref``. The
     schema layer's ``note`` whitelist refuses ``:`` outright so the
     ``password:`` / ``api_key:`` / ``token:`` literal scan in
     ``validate_d_one_live_run_evidence.py`` is NOT sufficient on
     these surfaces — the bare phrase ``token placeholder`` slips
     past the schema pattern locks but is exactly the credential /
     token wording this scan catches; the spec request ``prompt`` /
     ``intended_use`` fields have no schema pattern at all; and the
     opaque-ref / label / path-label slots admit ``_`` / ``-``
     separators so a hand-authored value like ``api_key_v2`` or
     ``private_key.ref`` passes the schema lock. Custom word
     boundaries (``(?<![A-Za-z0-9])`` / ``(?![A-Za-z0-9])``) replace
     the vanilla ``\\b`` for the bare-word patterns so a credential
     word embedded between identifier separators (``sandbox_token``,
     ``api_key.endpoint``) still fires. NO negation-context
     exemption applies (unlike P13): a reviewer who needs to discuss
     credentials should phrase the description without naming
     specific credential words.

Exit codes:
  0  PREFLIGHT_READY_FOR_MANUAL_TRIAL.
  1  LIVE_D_ONE_BLOCKED.
  2  invocation / file / parse error.

Self-test mode (``--self-test``) runs in-script tempfixture scenarios
covering the committed templates (which resolve to BLOCKED because the
shipped allow-list is empty / default-deny), a temp synthetic READY
fixture, and one fail-closed probe per failure mode above.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "schemas"
EXAMPLES_DIR = REPO_ROOT / "examples"

sys.path.insert(0, str(SCRIPTS_DIR))

from validate_artifacts import _validate  # noqa: E402
from validate_scaffold import local_path_is_safe  # noqa: E402
from validate_d_one_live_run_evidence import (  # noqa: E402
    _CREDENTIAL_PATTERNS,
    _PUBLIC_UPLOAD_PATTERNS,
    _public_upload_match_is_negated,
)

SPEC_SCHEMA = SCHEMAS_DIR / "d_one_adapter_plan.schema.json"
VOCAB_SCHEMA = SCHEMAS_DIR / "d_one_descriptor_vocabulary.schema.json"
ALLOWLIST_SCHEMA = SCHEMAS_DIR / "d_one_endpoint_allowlist.schema.json"
PREFLIGHT_SCHEMA = SCHEMAS_DIR / "d_one_preflight_audit.schema.json"

OUTCOME_BLOCKED = "LIVE_D_ONE_BLOCKED"
OUTCOME_READY = "PREFLIGHT_READY_FOR_MANUAL_TRIAL"

# Repo source-tree directories. An audit-out path or a preflight path
# label that resolves inside any of these would route artifact bytes
# into the repo source, which is forbidden — generated artifacts must
# never be committed (CLAUDE.md "no committed generated PPTX/report/
# zip/image/audit artifacts").
REPO_OUTPUT_DIRS: tuple[str, ...] = (
    "scripts",
    "schemas",
    "templates",
    "examples",
    "references",
    "dist",
)

# Required intent dimensions on every live-generation request. The
# d_one_adapter_plan schema makes all three optional; the readiness
# gate makes them mandatory so a live trial cannot ship without
# intent classification.
REQUIRED_INTENT_DIMENSIONS: tuple[str, ...] = (
    "placement_role",
    "text_policy",
    "subject_domain",
)

# Synthetic identifier shape borrowed verbatim from the descriptor
# vocabulary schema's ``synthetic_requests[*].id`` slot. Leading char
# locked to a letter; lowercase, underscores / dots / hyphens
# permitted; bounded forbidden-token deny clause; compound deny
# clause across separator stacking. We bring the d_one_adapter_plan
# request id up to the same shape because the plan schema does NOT
# pattern-lock it (only non-empty string).
_SYNTHETIC_ID_PATTERN: re.Pattern[str] = re.compile(
    r"^(?!.*(?:^|[._\-])"
    r"(?:public|upload|raw|customer|confidential|screenshot"
    r"|credential|password|secret)"
    r"(?:[._\-]|$))"
    r"(?!.*(?:full[._\-]*slide|image[._\-]*search"
    r"|web[._\-]*generation|page[._\-]*generation"
    r"|slide[._\-]*generation))"
    r"[a-z][a-z0-9_.\-]*$"
)

# Positive real-D-One PASS / success claim patterns. The readiness
# contract pins ``Real D-One path: UNVERIFIED``; a preflight that
# positively claims PASS would itself be evidence of a contract
# violation. The patterns are tight on purpose — generic "ok",
# "ready", "synthetic" do NOT fire; only language that asserts a
# verified live-D-One result does.
_POSITIVE_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "verified live D-One",
        re.compile(
            r"(?i)\bverified\s+(?:real\s+|live\s+)?d[-_]?one\b"
        ),
    ),
    (
        "real D-One passed",
        re.compile(
            r"(?i)\breal\s+d[-_]?one\s+"
            r"(?:pass|passes|passed|verified|complete|completed|succeeds)\b"
        ),
    ),
    (
        "D-One PASS",
        re.compile(r"(?i)\bd[-_]?one\s+pass\b"),
    ),
    (
        "live D-One success",
        re.compile(
            r"(?i)\blive\s+d[-_]?one\s+"
            r"(?:success|succeeded|certified|approved)\b"
        ),
    ),
)

# Custom word boundary for credential / token scans. The vanilla \b
# regex boundary treats ``_`` as a word character, so ``\btoken\b`` does
# NOT match ``sandbox_token`` (no boundary between ``_`` and ``t``).
# This pair treats every non-ASCII-ALNUM char — including ``_``, ``-``,
# ``.``, ``+``, whitespace, punctuation, and string edges — as a
# boundary so a credential word embedded between identifier separators
# in a label / ref slot still fires.
_NOT_ALNUM_BEFORE = r"(?<![A-Za-z0-9])"
_NOT_ALNUM_AFTER = r"(?![A-Za-z0-9])"

# Bare credential / token WORDS. Complements the imported
# _CREDENTIAL_PATTERNS table (JWT / AWS / PEM / long-hex / "bearer +
# blob"), which catches credential SHAPES, AND complements
# validate_d_one_live_run_evidence._CREDENTIAL_LITERALS (``password:``,
# ``api_key:``, ``token:``, ...), which requires the trailing ``:`` the
# schema's ``note`` whitelist refuses outright — leaving the bare
# multi-word phrase ``token placeholder`` / ``api_key abcdef`` (the
# Codex-flagged regressions) un-caught at every layer. Each pattern is
# case-insensitive and anchored with custom boundaries so embedded
# matches (``sandbox_token`` / ``api_key.endpoint``) fire too.
_CREDENTIAL_WORD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("token", re.compile(
        rf"(?i){_NOT_ALNUM_BEFORE}tokens?{_NOT_ALNUM_AFTER}"
    )),
    ("api_key", re.compile(
        rf"(?i){_NOT_ALNUM_BEFORE}api[_\-\s]?keys?{_NOT_ALNUM_AFTER}"
    )),
    ("bearer", re.compile(
        rf"(?i){_NOT_ALNUM_BEFORE}bearer{_NOT_ALNUM_AFTER}"
    )),
    ("password", re.compile(
        rf"(?i){_NOT_ALNUM_BEFORE}pass(?:word|wd)s?{_NOT_ALNUM_AFTER}"
    )),
    ("secret", re.compile(
        rf"(?i){_NOT_ALNUM_BEFORE}secrets?{_NOT_ALNUM_AFTER}"
    )),
    ("client_secret", re.compile(
        rf"(?i){_NOT_ALNUM_BEFORE}client[_\-\s]?secret{_NOT_ALNUM_AFTER}"
    )),
    ("private_key", re.compile(
        rf"(?i){_NOT_ALNUM_BEFORE}private[_\-\s]?key{_NOT_ALNUM_AFTER}"
    )),
    ("access_key", re.compile(
        rf"(?i){_NOT_ALNUM_BEFORE}access[_\-\s]?key{_NOT_ALNUM_AFTER}"
    )),
    ("credential", re.compile(
        rf"(?i){_NOT_ALNUM_BEFORE}credentials?{_NOT_ALNUM_AFTER}"
    )),
    # Stripe-style ephemeral API key shape. The leading ``sk-test-`` /
    # ``sk-live-`` marker plus 8+ trailing alphanumerics is the canonical
    # Stripe restricted-key prefix; treat both environments as suspect.
    ("Stripe-shape key", re.compile(
        r"\bsk-(?:test|live)-[A-Za-z0-9]{8,}\b"
    )),
)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _is_repo_output_label(value: str) -> bool:
    """True iff ``value`` (a workspace-relative path label) starts with
    one of the repo source-tree dir roots in REPO_OUTPUT_DIRS. The
    schema's leading-char lock means an empty / leading-slash value
    cannot reach this function — only path-safe labels do."""
    head = value.replace("\\", "/").split("/", 1)[0]
    return head in REPO_OUTPUT_DIRS


def _audit_out_resolves_inside_repo_output(path: Path) -> bool:
    """True iff ``path`` (already resolved) sits under any
    ``REPO_ROOT / <repo-output-dir>``. Used by P12 — we never want a
    readiness audit JSON to land inside the repo source tree."""
    resolved = path.resolve()
    for name in REPO_OUTPUT_DIRS:
        try:
            resolved.relative_to((REPO_ROOT / name).resolve())
            return True
        except ValueError:
            continue
    return False


def _load_file(label: str, path: Path) -> tuple[Any | None, str]:
    """Return (parsed_object, error). ``error`` is non-empty on failure.
    Applies P1 (regular non-symlink file) + P2 (parses to JSON object).
    The string fields in errors are deterministic so the audit blob is
    stable across runs."""
    if path.is_symlink():
        try:
            tgt = str(path.readlink())
        except OSError:
            tgt = "<unreadable>"
        return None, f"{label}: {path} is a symlink (-> {tgt}); refused"
    if not path.is_file():
        return None, f"{label}: {path} is not a regular file"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{label}: cannot read {path}: {exc}"
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"{label}: {path} is not valid JSON: {exc}"
    if not isinstance(value, dict):
        return None, (
            f"{label}: {path} root is not a JSON object "
            f"(got {type(value).__name__})"
        )
    return value, ""


def _schema_check(label: str, value: Any, schema_path: Path) -> list[str]:
    """Return a list of schema errors (each prefixed with ``label``).
    Empty list means the value validates against the schema."""
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [
            f"{label}: cannot load schema {schema_path}: {exc}"
        ]
    errs: list[str] = []
    _validate(value, schema, "<root>", errs)
    return [f"{label} schema: {e}" for e in errs]


# ---------------------------------------------------------------------------
# Cross-checks (P4..P11). Each returns a list of blocker strings.
# ---------------------------------------------------------------------------


def _check_vocab_synthetic_safe(vocab: dict) -> list[str]:
    """P4. The vocab's ``note`` must carry the substring ``synthetic``
    (case-insensitive). The forbidden-token deny clause on every
    descriptor / taxonomy value is already enforced at the schema
    layer."""
    note = vocab.get("note", "")
    if not isinstance(note, str):
        # Schema would have caught this already; defensive guard.
        return ["descriptor_vocabulary: 'note' is not a string"]
    if "synthetic" not in note.lower():
        return [
            "descriptor_vocabulary: 'note' does not carry the "
            "'synthetic' marker — vocabulary files used by a real "
            "trial must admit they are placeholders (P4)"
        ]
    return []


def _check_allowlist_default_deny(allowlist: dict) -> list[str]:
    """P5. An empty ``entries`` array is R3 default-deny resting state —
    no endpoint may run. The runtime gate would refuse every call; the
    readiness gate reports BLOCKED so the operator does not start a
    trial against a default-deny list."""
    entries = allowlist.get("entries", [])
    if not isinstance(entries, list):
        # Schema would have caught this; defensive guard.
        return ["endpoint_allowlist: 'entries' is not a list"]
    if len(entries) == 0:
        return [
            "endpoint_allowlist: 'entries' is empty — R3 default-deny "
            "resting state means no endpoint may run; a real trial "
            "requires at least one approved entry (P5)"
        ]
    return []


def _check_preflight_paths_repo_output_safe(preflight: dict) -> list[str]:
    """P6. Every path label in the preflight passes local_path_is_safe
    (belt-and-braces — the schema layer already does this) AND does
    NOT start with a repo source-tree dir root."""
    blockers: list[str] = []
    label_fields = (
        "workspace_label",
        "assets_dir_label",
        "audit_out_path_label",
        "allow_list_path_label",
        "vocabulary_path_label",
    )
    for field in label_fields:
        value = preflight.get(field)
        if not isinstance(value, str):
            # Schema would have caught this; defensive guard.
            continue
        if not local_path_is_safe(value):
            blockers.append(
                f"preflight_audit.{field}={value!r}: not local-path-"
                f"safe (P6)"
            )
            continue
        if _is_repo_output_label(value):
            blockers.append(
                f"preflight_audit.{field}={value!r}: starts with a "
                f"repo source-tree dir root in {REPO_OUTPUT_DIRS}; "
                f"a workspace that overlaps the repo source would "
                f"route audit bytes into the repo source (P6)"
            )
    return blockers


def _check_spec_request_id_synthetic_safe(spec: dict) -> list[str]:
    """P7. Every ``spec.requests[*].id`` conforms to the synthetic id
    shape. Returns blockers per offending row."""
    blockers: list[str] = []
    requests = spec.get("requests", [])
    if not isinstance(requests, list):
        return blockers
    for i, r in enumerate(requests):
        if not isinstance(r, dict):
            continue
        rid = r.get("id")
        if not isinstance(rid, str):
            continue
        if not _SYNTHETIC_ID_PATTERN.match(rid):
            blockers.append(
                f"d_one_spec.requests[{i}].id={rid!r}: not "
                f"synthetic-safe identifier shape (uppercase / "
                f"whitespace / leading non-letter / bounded "
                f"forbidden token public/upload/raw/customer/"
                f"confidential/screenshot/credential/password/"
                f"secret / compound full_slide/image_search/"
                f"web_generation/page_generation/slide_generation "
                f"across separators) (P7)"
            )
    return blockers


def _check_required_intent_dimensions(
    spec: dict, vocab: dict,
) -> tuple[list[str], dict[str, int]]:
    """P8. Every request carries ``placement_role`` + ``text_policy``
    + ``subject_domain``, every value is in the matching
    ``image_taxonomy.<dim>.allowed_values``, and the vocab declares
    every required dim (``placement_role`` is optional in the vocab
    schema; the readiness gate fires when it is absent).

    Returns (blockers, coverage). ``coverage[dim]`` is the count of
    requests in the spec whose value for ``dim`` is present AND in
    the matching vocab allow-list. This is reported in the audit
    JSON regardless of outcome — a BLOCKED audit still surfaces the
    partial coverage the operator already met."""
    blockers: list[str] = []
    coverage: dict[str, int] = {dim: 0 for dim in REQUIRED_INTENT_DIMENSIONS}

    image_taxonomy = vocab.get("image_taxonomy", {})
    if not isinstance(image_taxonomy, dict):
        return (
            [
                "descriptor_vocabulary.image_taxonomy is missing or "
                "not an object (P8)"
            ],
            coverage,
        )

    # Vocab must declare every required dim (placement_role is
    # optional in the vocab schema; a vocab that omits it BLOCKS).
    allowed_by_dim: dict[str, set[str]] = {}
    for dim in REQUIRED_INTENT_DIMENSIONS:
        block = image_taxonomy.get(dim)
        if not isinstance(block, dict):
            blockers.append(
                f"descriptor_vocabulary.image_taxonomy.{dim} is "
                f"absent — the readiness gate requires the vocab to "
                f"declare every intent dimension {REQUIRED_INTENT_DIMENSIONS} "
                f"(P8)"
            )
            allowed_by_dim[dim] = set()
            continue
        values = block.get("allowed_values", [])
        if not isinstance(values, list):
            blockers.append(
                f"descriptor_vocabulary.image_taxonomy.{dim}"
                f".allowed_values is not a list (P8)"
            )
            allowed_by_dim[dim] = set()
            continue
        allowed_by_dim[dim] = {
            v for v in values if isinstance(v, str)
        }

    requests = spec.get("requests", [])
    if not isinstance(requests, list):
        return blockers, coverage

    for i, r in enumerate(requests):
        if not isinstance(r, dict):
            continue
        for dim in REQUIRED_INTENT_DIMENSIONS:
            if dim not in r:
                blockers.append(
                    f"d_one_spec.requests[{i}]: missing required "
                    f"intent dimension {dim!r} — a real trial may "
                    f"not ship a request without intent "
                    f"classification (P8)"
                )
                continue
            value = r[dim]
            if not isinstance(value, str):
                blockers.append(
                    f"d_one_spec.requests[{i}].{dim}={value!r}: "
                    f"not a string (P8)"
                )
                continue
            if value not in allowed_by_dim.get(dim, set()):
                blockers.append(
                    f"d_one_spec.requests[{i}].{dim}={value!r}: not "
                    f"in vocab image_taxonomy.{dim}.allowed_values"
                    f"={sorted(allowed_by_dim.get(dim, set()))!r} "
                    f"(P8)"
                )
                continue
            coverage[dim] += 1
    return blockers, coverage


def _check_no_local_asset_in_request_set(spec: dict) -> list[str]:
    """P9. Every ``spec.requests[*].manifest_source`` equals
    ``d_one_local``. The schema enum lock already enforces this; the
    readiness gate re-checks as belt-and-braces."""
    blockers: list[str] = []
    requests = spec.get("requests", [])
    if not isinstance(requests, list):
        return blockers
    for i, r in enumerate(requests):
        if not isinstance(r, dict):
            continue
        src = r.get("manifest_source")
        if src != "d_one_local":
            blockers.append(
                f"d_one_spec.requests[{i}].manifest_source={src!r}: "
                f"only 'd_one_local' is eligible for the live "
                f"generation channel — local_asset / synthetic / "
                f"any other source must NOT appear in the request "
                f"set (P9)"
            )
    return blockers


def _check_preflight_endpoint_in_allowlist(
    preflight: dict, allowlist: dict,
) -> list[str]:
    """P10. preflight.endpoint_label must match some allowlist entry."""
    label = preflight.get("endpoint_label")
    if not isinstance(label, str):
        return []
    entries = allowlist.get("entries", [])
    if not isinstance(entries, list):
        return []
    seen: set[str] = set()
    for e in entries:
        if isinstance(e, dict):
            v = e.get("endpoint_label")
            if isinstance(v, str):
                seen.add(v)
    if label not in seen:
        return [
            f"preflight_audit.endpoint_label={label!r} does NOT "
            f"appear in endpoint_allowlist.entries[].endpoint_label "
            f"{sorted(seen)!r} — R1 requires the runner to refuse "
            f"any endpoint not on the list (P10)"
        ]
    return []


def _check_no_positive_d_one_pass_claim(preflight: dict) -> list[str]:
    """P11. The preflight's ``note`` does NOT positively claim live
    D-One PASS. Today ``Real D-One path: UNVERIFIED`` is load-bearing
    in the readiness contract."""
    note = preflight.get("note", "")
    if not isinstance(note, str):
        return []
    blockers: list[str] = []
    for label, pat in _POSITIVE_CLAIM_PATTERNS:
        if pat.search(note):
            blockers.append(
                f"preflight_audit.note: contains positive "
                f"real-D-One PASS claim {label!r} — the readiness "
                f"contract pins 'Real D-One path: UNVERIFIED', so a "
                f"preflight that positively claims PASS is itself "
                f"evidence of a contract violation (P11)"
            )
    return blockers


def _scan_for_public_upload(text: str, where: str) -> list[str]:
    """Return a list of public-upload blockers for ``text``. Reuses
    ``_PUBLIC_UPLOAD_PATTERNS`` and the strict-adjacency negation
    function from ``validate_d_one_live_run_evidence.py`` so the rules
    stay synchronised across the pre-call (this preflight) and
    post-call (evidence) records — a reviewer can write
    ``no public upload``, ``public upload is forbidden``, ``public
    hosting is not used`` and similar boundary phrases without
    tripping the gate, but a directive that asks the artifact to be
    uploaded / published / hosted / shared publicly fires."""
    out: list[str] = []
    for label, pattern in _PUBLIC_UPLOAD_PATTERNS:
        for m in pattern.finditer(text):
            if _public_upload_match_is_negated(text, m.start(), m.end()):
                continue
            out.append(
                f"{where}: contains public-upload-shaped phrase "
                f"{label!r} — every artifact described by this "
                f"preflight is local-only and may not be uploaded, "
                f"published, hosted, or shared publicly (P13)"
            )
    return out


def _check_public_upload_in_free_form(
    spec: dict, vocab: dict, allowlist: dict, preflight: dict,
) -> list[str]:
    """P13. Scan every free-form field whose schema pattern admits a
    multi-word phrase (the four ``note`` fields plus the spec request
    ``prompt`` / ``intended_use``) for public-upload / public-sharing /
    public-hosting wording.

    The schema layer ALONE is not sufficient to catch the multi-word
    case: the ``note`` whitelist on every contract file admits letters
    / digits / spaces / basic sentence punctuation (`., ; ! ? ( ) -`),
    so the literal phrase ``public upload`` passes the schema; the
    spec request ``prompt`` field has no schema pattern at all (only
    ``minLength: 1``). Without this scan a hand-authored preflight or
    spec could carry a public-distribution directive into a future
    live trial. Honors the same strict-adjacency negation exemption
    as ``validate_d_one_live_run_evidence.py`` G11 so a reviewer can
    document the boundary (`no public upload`, `public upload is
    forbidden`) without tripping the gate."""
    blockers: list[str] = []
    for label, value in (
        ("d_one_spec.note", spec.get("note", "")),
        ("descriptor_vocabulary.note", vocab.get("note", "")),
        ("endpoint_allowlist.note", allowlist.get("note", "")),
        ("preflight_audit.note", preflight.get("note", "")),
    ):
        if isinstance(value, str):
            blockers.extend(_scan_for_public_upload(value, label))
    requests = spec.get("requests", [])
    if isinstance(requests, list):
        for i, r in enumerate(requests):
            if not isinstance(r, dict):
                continue
            prompt = r.get("prompt", "")
            if isinstance(prompt, str):
                blockers.extend(
                    _scan_for_public_upload(
                        prompt, f"d_one_spec.requests[{i}].prompt"
                    )
                )
            iu = r.get("intended_use")
            if isinstance(iu, str):
                blockers.extend(
                    _scan_for_public_upload(
                        iu, f"d_one_spec.requests[{i}].intended_use"
                    )
                )
    return blockers


def _scan_for_credentials(text: str, where: str) -> list[str]:
    """Return a list of credential / token blockers for ``text``. Runs
    the bare-word table (``_CREDENTIAL_WORD_PATTERNS`` — token /
    api_key / password / secret / client_secret / private_key /
    access_key / bearer / credential / Stripe-shape key) AND the
    reused-shape table (``_CREDENTIAL_PATTERNS`` from
    ``validate_d_one_live_run_evidence.py`` — JWT / AWS / PEM / long
    hex / ``bearer + opaque``). Unlike ``_scan_for_public_upload``,
    NO negation-context exemption applies: a reviewer who writes
    ``no password used`` should pick a different phrasing because the
    schema's ``note`` whitelist deliberately keeps the surface narrow
    and the bare credential word still indicates the operator was
    thinking in credential terms."""
    out: list[str] = []
    for label, pattern in _CREDENTIAL_WORD_PATTERNS:
        if pattern.search(text):
            out.append(
                f"{where}: contains credential/token-shaped wording "
                f"{label!r} — every free-form / opaque-ref / label / "
                f"path-label field in this preflight is a local "
                f"placeholder and may not carry credential wording "
                f"(P14)"
            )
    for label, pattern in _CREDENTIAL_PATTERNS:
        if pattern.search(text):
            out.append(
                f"{where}: contains {label}-shaped substring — "
                f"credential / token shapes are refused in every "
                f"free-form / opaque-ref / label / path-label field "
                f"of this preflight (P14)"
            )
    return out


def _check_credentials_in_free_form(
    spec: dict, vocab: dict, allowlist: dict, preflight: dict,
) -> list[str]:
    """P14. Scan every free-form field AND every identifier / label /
    ref / path-label slot whose schema admits credential / token-shaped
    wording. The schema layer alone is not sufficient: the ``note``
    whitelist on every contract file admits letters / digits / spaces /
    basic sentence punctuation, so the bare phrase ``token placeholder``
    passes the schema; the spec request ``prompt`` / ``intended_use``
    fields have no schema pattern at all (only ``minLength: 1``); and
    the opaque-ref / label / path-label slots admit ``_`` / ``-``
    separators so a value like ``api_key_v2`` or ``sk-test-abc12345``
    also passes the schema lock. Without this scan a hand-authored
    preflight or spec could carry a credential placeholder into a
    future live trial."""
    blockers: list[str] = []

    # Free-form / multi-word fields (the same six P13 walks).
    for label, value in (
        ("d_one_spec.note", spec.get("note", "")),
        ("descriptor_vocabulary.note", vocab.get("note", "")),
        ("endpoint_allowlist.note", allowlist.get("note", "")),
        ("preflight_audit.note", preflight.get("note", "")),
    ):
        if isinstance(value, str):
            blockers.extend(_scan_for_credentials(value, label))

    # spec.requests[*].id / prompt / intended_use / manifest_local_path.
    requests = spec.get("requests", [])
    if isinstance(requests, list):
        for i, r in enumerate(requests):
            if not isinstance(r, dict):
                continue
            for field in ("id", "prompt", "intended_use",
                          "manifest_local_path"):
                val = r.get(field)
                if isinstance(val, str):
                    blockers.extend(_scan_for_credentials(
                        val, f"d_one_spec.requests[{i}].{field}"
                    ))

    # allowlist.entries[*].{endpoint_label, destination_label,
    # approval_reviewer_ref, security_review_ref}.
    entries = allowlist.get("entries", [])
    if isinstance(entries, list):
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                continue
            for field in (
                "endpoint_label", "destination_label",
                "approval_reviewer_ref", "security_review_ref",
            ):
                val = e.get(field)
                if isinstance(val, str):
                    blockers.extend(_scan_for_credentials(
                        val,
                        f"endpoint_allowlist.entries[{i}].{field}",
                    ))

    # preflight identifier / label / path-label slots.
    for field in (
        "endpoint_label", "operator_label",
        "allow_list_path_label", "vocabulary_path_label",
        "workspace_label", "assets_dir_label",
        "audit_out_path_label",
    ):
        val = preflight.get(field)
        if isinstance(val, str):
            blockers.extend(_scan_for_credentials(
                val, f"preflight_audit.{field}"
            ))

    # preflight.approvals.{endpoint_approval_ref, vocabulary_approval_ref,
    # deck_approval_ref, operator_ref, cleanup_ref}. The schema names
    # the M6 cleanup channel ``cleanup_ref`` (not ``cleanup_approval_ref``
    # — a wrong name here would silently skip the slot under
    # additionalProperties:false because no value ever lands at the
    # mis-spelt key).
    approvals = preflight.get("approvals", {})
    if isinstance(approvals, dict):
        for field in (
            "endpoint_approval_ref", "vocabulary_approval_ref",
            "deck_approval_ref", "operator_ref",
            "cleanup_ref",
        ):
            val = approvals.get(field)
            if isinstance(val, str):
                blockers.extend(_scan_for_credentials(
                    val, f"preflight_audit.approvals.{field}"
                ))

    return blockers


def _check_audit_out_path(audit_out: Path) -> list[str]:
    """P12. ``--audit-out`` not a symlink, not pre-existing, not under
    any REPO_OUTPUT_DIRS, parent dir exists."""
    blockers: list[str] = []
    if audit_out.is_symlink():
        try:
            tgt = str(audit_out.readlink())
        except OSError:
            tgt = "<unreadable>"
        blockers.append(
            f"--audit-out {audit_out!s}: is a symlink (-> {tgt}); "
            f"refused (P12)"
        )
        return blockers
    if audit_out.exists():
        blockers.append(
            f"--audit-out {audit_out!s}: pre-existing file refused "
            f"(no overwrite) (P12)"
        )
        return blockers
    if not audit_out.parent.exists():
        blockers.append(
            f"--audit-out {audit_out!s}: parent dir "
            f"{audit_out.parent!s} does not exist (P12)"
        )
        return blockers
    if _audit_out_resolves_inside_repo_output(audit_out):
        blockers.append(
            f"--audit-out {audit_out!s}: resolves inside a repo "
            f"source-tree dir ({REPO_OUTPUT_DIRS}) — the readiness "
            f"audit must not be written into the repo source (P12)"
        )
    return blockers


# ---------------------------------------------------------------------------
# Top-level readiness audit.
# ---------------------------------------------------------------------------


def _emit_audit(
    blockers: list[str],
    checked_files: list[str],
    request_count: int,
    taxonomy_coverage: dict[str, int],
) -> dict:
    """Build the readiness audit JSON dict. Deterministic key order
    courtesy of ``json.dumps(..., sort_keys=True)`` at the caller."""
    return {
        "blockers": list(blockers),
        "checked_files": list(checked_files),
        "no_mcp_called": True,
        "no_model_api_called": True,
        "no_network_called": True,
        "real_d_one_status": "UNVERIFIED",
        "request_count": int(request_count),
        "taxonomy_coverage": {
            dim: int(taxonomy_coverage.get(dim, 0))
            for dim in REQUIRED_INTENT_DIMENSIONS
        },
        "top_line_outcome": (
            OUTCOME_BLOCKED if blockers else OUTCOME_READY
        ),
    }


def evaluate(
    spec_path: Path,
    vocab_path: Path,
    allowlist_path: Path,
    preflight_path: Path,
    audit_out: Path | None,
) -> dict:
    """Run every prerequisite gate and return the readiness audit dict.
    No file system mutation is performed by this function — even
    ``--audit-out`` is checked but not yet written; the caller writes
    the audit only when the audit-out gate itself passes."""
    blockers: list[str] = []
    checked_files: list[str] = [
        str(spec_path),
        str(vocab_path),
        str(allowlist_path),
        str(preflight_path),
    ]
    if audit_out is not None:
        checked_files.append(str(audit_out))

    # P1 + P2 — load all four inputs.
    spec, e1 = _load_file("d_one_spec", spec_path)
    if e1:
        blockers.append(e1)
    vocab, e2 = _load_file("descriptor_vocabulary", vocab_path)
    if e2:
        blockers.append(e2)
    allowlist, e3 = _load_file("endpoint_allowlist", allowlist_path)
    if e3:
        blockers.append(e3)
    preflight, e4 = _load_file("preflight_audit", preflight_path)
    if e4:
        blockers.append(e4)

    # P3 — schema-validate every input that loaded successfully.
    if spec is not None:
        blockers.extend(_schema_check("d_one_spec", spec, SPEC_SCHEMA))
    if vocab is not None:
        blockers.extend(
            _schema_check("descriptor_vocabulary", vocab, VOCAB_SCHEMA)
        )
    if allowlist is not None:
        blockers.extend(
            _schema_check("endpoint_allowlist", allowlist, ALLOWLIST_SCHEMA)
        )
    if preflight is not None:
        blockers.extend(
            _schema_check("preflight_audit", preflight, PREFLIGHT_SCHEMA)
        )

    request_count = 0
    coverage: dict[str, int] = {dim: 0 for dim in REQUIRED_INTENT_DIMENSIONS}

    # P4..P11 cross-checks only run when the relevant schemas passed.
    # Each check is defensive about missing / wrong-typed fields so
    # the failure mode is always "blocker emitted", never traceback.
    if not blockers:
        # By this point every input is schema-valid; the cross-checks
        # below assume schema-conformant input.
        if isinstance(vocab, dict):
            blockers.extend(_check_vocab_synthetic_safe(vocab))
        if isinstance(allowlist, dict):
            blockers.extend(_check_allowlist_default_deny(allowlist))
        if isinstance(preflight, dict):
            blockers.extend(
                _check_preflight_paths_repo_output_safe(preflight)
            )
        if isinstance(spec, dict):
            blockers.extend(_check_spec_request_id_synthetic_safe(spec))
            requests = spec.get("requests", [])
            if isinstance(requests, list):
                request_count = len(requests)
        if isinstance(spec, dict) and isinstance(vocab, dict):
            intent_blockers, coverage = _check_required_intent_dimensions(
                spec, vocab,
            )
            blockers.extend(intent_blockers)
        if isinstance(spec, dict):
            blockers.extend(_check_no_local_asset_in_request_set(spec))
        if isinstance(preflight, dict) and isinstance(allowlist, dict):
            blockers.extend(
                _check_preflight_endpoint_in_allowlist(preflight, allowlist)
            )
        if isinstance(preflight, dict):
            blockers.extend(_check_no_positive_d_one_pass_claim(preflight))
        if (
            isinstance(spec, dict)
            and isinstance(vocab, dict)
            and isinstance(allowlist, dict)
            and isinstance(preflight, dict)
        ):
            blockers.extend(
                _check_public_upload_in_free_form(
                    spec, vocab, allowlist, preflight,
                )
            )
            blockers.extend(
                _check_credentials_in_free_form(
                    spec, vocab, allowlist, preflight,
                )
            )

    # P12 — audit-out path. Runs regardless of earlier blockers so the
    # operator sees every gate at once; an unsafe audit-out path is
    # itself a BLOCKED condition even if every other gate passed.
    if audit_out is not None:
        blockers.extend(_check_audit_out_path(audit_out))

    return _emit_audit(blockers, checked_files, request_count, coverage)


# ---------------------------------------------------------------------------
# Self-test fixtures.
# ---------------------------------------------------------------------------


def _canonical_vocab() -> dict:
    """Return a canonical in-script descriptor vocabulary the self-test
    can drop in a tempfile. Mirrors examples/d_one_descriptor_vocabulary_
    template.json so a probe never depends on on-disk template bytes."""
    return {
        "schema_version": 1,
        "note": (
            "Synthetic placeholder D-One descriptor vocabulary "
            "for the readiness preflight self-test."
        ),
        "kind_enum": [
            "color_token",
            "geometric_noun",
            "mood_adjective",
            "composition_adjective",
        ],
        "descriptors": [
            {"kind": "color_token", "value": "palette.accent"},
            {"kind": "geometric_noun", "value": "circle"},
            {"kind": "mood_adjective", "value": "calm"},
            {"kind": "composition_adjective", "value": "centered"},
        ],
        "image_taxonomy": {
            "rendering_style": {
                "allowed_values": [
                    "flat_vector", "line_diagram", "isometric_lite",
                    "low_poly", "solid_shape",
                ],
            },
            "palette_family": {
                "allowed_values": [
                    "neutral_grey", "accent_only", "dual_tone",
                    "mono_brand", "palette_default",
                ],
            },
            "image_role": {
                "allowed_values": [
                    "decorative_accent", "metaphor_icon",
                    "divider_motif", "kpi_emblem", "cover_motif",
                ],
            },
            "layout_pattern": {
                "allowed_values": [
                    "single_center", "left_anchor", "right_anchor",
                    "top_band", "bottom_band",
                ],
            },
            "modifier": {
                "allowed_values": [
                    "low_contrast", "soft_edges", "grid_aligned",
                    "negative_space",
                ],
            },
            "text_policy": {
                "allowed_values": [
                    "no_text", "decorative_glyphs", "caption_safe",
                ],
            },
            "subject_domain": {
                "allowed_values": [
                    "abstract_geometry", "process_motif",
                    "metric_emblem", "concept_diagram",
                ],
            },
            "placement_role": {
                "allowed_values": ["hero_page", "local_region"],
            },
        },
    }


def _canonical_allowlist_with_entry() -> dict:
    """Allowlist with one approved entry — passes P5 and lets the
    preflight's endpoint_label resolve via P10."""
    return {
        "schema_version": 1,
        "note": (
            "Synthetic D-One endpoint allow-list for the readiness "
            "preflight self-test."
        ),
        "default_policy": "deny",
        "entries": [
            {
                "endpoint_label": "sandbox_alpha",
                "destination_label": "destLabel",
                "approval_reviewer_ref": "rev_001",
                "approval_date": "2026-05-01T00:00:00Z",
                "security_review_ref": "sec_001",
                "scope": {
                    "environment": "sandbox",
                    "request_types": ["image_generation"],
                    "byte_cap_max_bytes": 1048576,
                },
            },
        ],
    }


def _canonical_preflight() -> dict:
    """Synthetic preflight whose endpoint_label resolves in the
    canonical allow-list (``sandbox_alpha``) and whose path labels
    sit outside the repo source tree."""
    return {
        "schema_version": 1,
        "mode": "preflight",
        "note": "D-One live-run preflight record",
        "endpoint_label": "sandbox_alpha",
        "disable_switch_state": "off",
        "operator_label": "op_alpha",
        "allow_list_path_label": "config/d_one_endpoint_allowlist.json",
        "vocabulary_path_label": "config/d_one_descriptor_vocabulary.json",
        "workspace_label": "workspace",
        "assets_dir_label": "assets",
        "audit_out_path_label": "audit/preflight_run.audit.json",
        "approvals": {
            "endpoint_approval_ref": "ep_appr_001",
            "vocabulary_approval_ref": "vocab_appr_001",
            "deck_approval_ref": "deck_appr_001",
            "operator_ref": "op_ref_001",
        },
    }


def _canonical_spec() -> dict:
    """Synthetic d_one_adapter_plan with one request that meets every
    P7 + P8 + P9 readiness gate. Uses the same prompt shape the
    canonical mock pipeline produces."""
    return {
        "schema_version": 4,
        "mode": "dry_run",
        "note": "D-One adapter contract stub",
        "request_count": 1,
        "requests": [
            {
                "id": "cover_motif",
                "prompt": (
                    "calm centered geometric motif rendered in muted "
                    "tones; abstract; no language"
                ),
                "manifest_local_path": "media/cover_motif.png",
                "manifest_source": "d_one_local",
                "rendering_style": "flat_vector",
                "palette_family": "neutral_grey",
                "image_role": "cover_motif",
                "layout_pattern": "single_center",
                "text_policy": "no_text",
                "subject_domain": "abstract_geometry",
                "placement_role": "local_region",
            },
        ],
    }


def _write(td: Path, name: str, payload: Any) -> Path:
    p = td / name
    if isinstance(payload, (bytes, bytearray)):
        p.write_bytes(payload)
    elif isinstance(payload, str):
        p.write_text(payload, encoding="utf-8")
    else:
        p.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return p


def _expect(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


def _silent_main(argv: list[str]) -> int:
    """Invoke main() with stdout/stderr suppressed. Used by the
    self-test probes that exercise the CLI entry point — the inner
    audit-JSON write to stdout would otherwise leak into the
    self-test's own [PASS]/[FAIL] log."""
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(
        buf_err
    ):
        return main(argv)


def _run_self_tests() -> list[tuple[str, bool, str]]:  # noqa: C901
    """In-script tempfixture probes covering the committed templates
    plus a temp synthetic READY fixture plus one probe per failure
    mode in the docstring."""
    results: list[tuple[str, bool, str]] = []

    # ---- 1. Committed-template baseline. The shipped endpoint
    # allow-list has empty entries (R3 default-deny resting state), so
    # the readiness gate fires BLOCKED via P5 even though every other
    # gate passes. We supply a temp synthetic spec because no shipped
    # adapter-plan template exists.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec_p = _write(td, "spec.json", _canonical_spec())
        committed_vocab = EXAMPLES_DIR / "d_one_descriptor_vocabulary_template.json"
        committed_allow = EXAMPLES_DIR / "d_one_endpoint_allowlist_template.json"
        committed_preflight = EXAMPLES_DIR / "d_one_preflight_audit_template.json"
        audit = evaluate(
            spec_p, committed_vocab, committed_allow, committed_preflight,
            audit_out=None,
        )
        results.append(_expect(
            "committed templates resolve to LIVE_D_ONE_BLOCKED via P5 "
            "empty-allow-list default-deny",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any("entries' is empty" in b for b in audit["blockers"])
            and audit["real_d_one_status"] == "UNVERIFIED"
            and audit["no_network_called"] is True
            and audit["no_mcp_called"] is True
            and audit["no_model_api_called"] is True,
            f"audit={audit!r}",
        ))

    # ---- 2. Temp synthetic READY fixture. Every gate passes, so the
    # readiness gate reports PREFLIGHT_READY_FOR_MANUAL_TRIAL. This is
    # NOT a PASS for live D-One — the audit JSON still records
    # real_d_one_status=UNVERIFIED.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "temp synthetic READY fixture resolves to "
            "PREFLIGHT_READY_FOR_MANUAL_TRIAL (still UNVERIFIED, not PASS)",
            audit["top_line_outcome"] == OUTCOME_READY
            and audit["blockers"] == []
            and audit["request_count"] == 1
            and audit["taxonomy_coverage"] == {
                "placement_role": 1,
                "text_policy": 1,
                "subject_domain": 1,
            }
            and audit["real_d_one_status"] == "UNVERIFIED"
            and audit["no_network_called"] is True
            and audit["no_mcp_called"] is True
            and audit["no_model_api_called"] is True,
            f"audit={audit!r}",
        ))

    # ---- 3. Missing file (P1). One input path does not exist.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        # preflight not written — file missing.
        pre_p = td / "missing.json"
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "missing preflight file refused (P1)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "preflight_audit" in b and "not a regular file" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 4. Symlink file (P1). One input path is a symlink.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec_real = _write(td, "spec_real.json", _canonical_spec())
        spec_link = td / "spec.json"
        spec_link.symlink_to(spec_real)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_link, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "symlink input file refused (P1)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "d_one_spec" in b and "is a symlink" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 5. Malformed JSON (P2).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec_p = _write(td, "spec.json", "{not-valid-json")
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "malformed JSON refused (P2)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "not valid JSON" in b for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 6. Unsafe endpoint string. The allowlist schema's
    # endpoint_label pattern refuses URLs at the schema layer; we
    # inject a URL into the destination_label slot to force a schema
    # failure (P3).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        allow = _canonical_allowlist_with_entry()
        allow["entries"][0]["destination_label"] = "https://attacker.example"
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", allow)
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "URL-shaped destination_label refused at schema layer (P3)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "endpoint_allowlist schema" in b
                and "destination_label" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 7. Credential/token in a free-form field. The vocab note's
    # positive whitelist refuses `:` outright at the schema layer, so a
    # `password:` literal is refused at the schema layer (P3).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        vocab = _canonical_vocab()
        vocab["note"] = (
            "D-One descriptor vocabulary password: hunter2 sneaky"
        )
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", vocab)
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "credential 'password:' literal in vocab note refused at "
            "schema layer (P3 — schema pattern refuses ':' outright)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "descriptor_vocabulary schema" in b
                and "does not match pattern" in b
                and "note" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 8. URL-shape in preflight note refused at the schema layer.
    # The whitelist on every `note` field refuses ':' / '/' / '\' / '@'
    # / '#' / '?' / '%', so any URL / email / fragment / authority
    # shape can never reach the runtime scan. (The bare phrase
    # `public upload` WITHOUT a URL passes the schema — that case is
    # covered by the P13 probes further below.)
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pre = _canonical_preflight()
        pre["note"] = (
            "D-One live-run preflight record upload https://attacker"
        )
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", pre)
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "URL-shape in preflight note refused at schema layer (P3)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "preflight_audit schema" in b
                and "note" in b
                and "does not match pattern" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 9. Positive real-D-One success claim refused (P11).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pre = _canonical_preflight()
        pre["note"] = (
            "D-One live-run preflight record real D-One passed already"
        )
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", pre)
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "positive real-D-One PASS claim in preflight note refused (P11)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P11" in b and "real D-One passed" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 10. Non-synthetic spec request id refused (P7).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["id"] = "customer_acme_logo"
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "non-synthetic 'customer_acme_logo' request id refused (P7)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P7" in b and "customer_acme_logo" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 11. Spec request missing a required intent dimension (P8).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        del spec["requests"][0]["placement_role"]
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "spec request missing 'placement_role' refused (P8)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P8" in b and "placement_role" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 12. Vocab omits placement_role block — readiness blocks (P8).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        vocab = _canonical_vocab()
        del vocab["image_taxonomy"]["placement_role"]
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", vocab)
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "vocab missing image_taxonomy.placement_role refused (P8)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "image_taxonomy.placement_role is absent" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 13. Preflight path label points inside repo source (P6).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pre = _canonical_preflight()
        pre["audit_out_path_label"] = "scripts/preflight.audit.json"
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", pre)
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "preflight audit_out_path_label inside repo source (scripts/) "
            "refused (P6)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P6" in b and "scripts/preflight.audit.json" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 14. preflight endpoint_label not in allowlist (P10).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pre = _canonical_preflight()
        pre["endpoint_label"] = "ghost_endpoint"
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", pre)
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "preflight endpoint_label not in allow-list entries refused (P10)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P10" in b and "ghost_endpoint" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 15. allowlist empty entries refused (P5).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", {
            "schema_version": 1,
            "note": "D-One endpoint allow-list synthetic empty placeholder",
            "default_policy": "deny",
            "entries": [],
        })
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "empty allow-list entries refused (P5 default-deny resting)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P5" in b and "entries' is empty" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 16. vocabulary note missing 'synthetic' marker refused (P4).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        vocab = _canonical_vocab()
        vocab["note"] = "D-One descriptor vocabulary placeholder"
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", vocab)
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "vocab note missing 'synthetic' marker refused (P4)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P4" in b and "synthetic" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 17. Unsafe --audit-out (symlink) refused (P12).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        real_target = td / "real.json"
        real_target.write_text("{}", encoding="utf-8")
        link = td / "link_out.json"
        link.symlink_to(real_target)
        audit = evaluate(
            spec_p, vocab_p, allow_p, pre_p, audit_out=link,
        )
        results.append(_expect(
            "symlinked --audit-out refused (P12)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P12" in b and "is a symlink" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 18. --audit-out pre-existing refused (P12).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        existing = td / "existing.audit.json"
        existing.write_text("{}\n", encoding="utf-8")
        audit = evaluate(
            spec_p, vocab_p, allow_p, pre_p, audit_out=existing,
        )
        results.append(_expect(
            "pre-existing --audit-out refused (P12 no overwrite)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P12" in b and "pre-existing" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 19. --audit-out inside repo source-tree refused (P12).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        bad_out = REPO_ROOT / "scripts" / "_unwanted_readiness.json"
        # Confirm it does NOT pre-exist before invoking — this is a
        # tempfixture probe, no artifact may be left in the repo.
        assert not bad_out.exists(), (
            "repo-output probe pre-existed; bailing to avoid masking"
        )
        audit = evaluate(
            spec_p, vocab_p, allow_p, pre_p, audit_out=bad_out,
        )
        # And nothing should have been written by evaluate() — only
        # main() writes; evaluate() only computes the audit.
        results.append(_expect(
            "--audit-out inside repo scripts/ refused (P12); evaluate() "
            "does NOT write the file",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P12" in b and "resolves inside a repo" in b
                for b in audit["blockers"]
            )
            and not bad_out.exists(),
            f"audit={audit!r}, leaked={bad_out.exists()}",
        ))

    # ---- 20. local_asset manifest_source rejected at schema layer.
    # The d_one_adapter_plan schema's manifest_source enum already
    # locks to 'd_one_local'. A request that sets manifest_source to
    # 'local_asset' is refused via P3 (schema).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["manifest_source"] = "local_asset"
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "local_asset manifest_source in spec request refused at "
            "schema layer (P3 — enum lock 'd_one_local')",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "d_one_spec schema" in b
                and "manifest_source" in b
                and "not in enum" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 21. main() actually writes the audit-out file when the gate
    # passes, and writes determinism is sort_keys + indent=2 + trailing
    # newline. Probe via the audit-out happy path.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit_out = td / "out.json"
        rc = _silent_main([
            "--d-one-spec", str(spec_p),
            "--descriptor-vocabulary", str(vocab_p),
            "--endpoint-allowlist", str(allow_p),
            "--preflight-audit", str(pre_p),
            "--audit-out", str(audit_out),
        ])
        contents = audit_out.read_text(encoding="utf-8") if audit_out.exists() else ""
        parsed = json.loads(contents) if contents else {}
        results.append(_expect(
            "main() writes audit-out happy-path PREFLIGHT_READY (exit "
            "code 0; deterministic sorted JSON; trailing newline)",
            rc == 0
            and audit_out.is_file()
            and parsed.get("top_line_outcome") == OUTCOME_READY
            and parsed.get("real_d_one_status") == "UNVERIFIED"
            and parsed.get("no_network_called") is True
            and contents.endswith("\n")
            and contents.startswith("{"),
            f"rc={rc}, exists={audit_out.exists()}, "
            f"contents_len={len(contents)}",
        ))

    # ---- 22. main() exits 1 when BLOCKED (committed empty-allow-list
    # baseline).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec_p = _write(td, "spec.json", _canonical_spec())
        committed_vocab = EXAMPLES_DIR / "d_one_descriptor_vocabulary_template.json"
        committed_allow = EXAMPLES_DIR / "d_one_endpoint_allowlist_template.json"
        committed_preflight = EXAMPLES_DIR / "d_one_preflight_audit_template.json"
        rc = _silent_main([
            "--d-one-spec", str(spec_p),
            "--descriptor-vocabulary", str(committed_vocab),
            "--endpoint-allowlist", str(committed_allow),
            "--preflight-audit", str(committed_preflight),
        ])
        results.append(_expect(
            "main() exits 1 on LIVE_D_ONE_BLOCKED (committed empty "
            "allow-list baseline)",
            rc == 1,
            f"rc={rc}",
        ))

    # ---- 23. main() exits 2 on missing required arg (invocation error).
    rc = _silent_main([
        "--d-one-spec", "spec.json",
        # missing --descriptor-vocabulary
    ])
    results.append(_expect(
        "main() exits 2 on missing required CLI flag",
        rc == 2,
        f"rc={rc}",
    ))

    # ---- P13 public-upload free-form scan probes. The schema's `note`
    # whitelist allows letters / digits / spaces / `., ; ! ? ( ) -`, so
    # the bare multi-word phrase `public upload` (without any URL /
    # `:` / `@` / etc.) passes the schema layer. The spec request
    # `prompt` field has no schema pattern at all (only minLength: 1).
    # P13 closes both gaps; the negation-context probes prove a
    # reviewer can still describe the boundary.

    # P13a. `public upload` in preflight.note refused (BLOCKED via P13).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pre = _canonical_preflight()
        pre["note"] = (
            "D-One live-run preflight record public upload of "
            "artifacts required"
        )
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", pre)
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P13a: bare 'public upload' in preflight.note refused (P13 "
            "free-form scan; this is the Codex-flagged regression — "
            "the schema's `note` whitelist accepts 'public upload' on "
            "its own so a runtime scan must catch it)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P13" in b and "preflight_audit.note" in b
                and "public upload" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P13b. `public hosting` in vocab.note refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        vocab = _canonical_vocab()
        vocab["note"] = (
            "Synthetic placeholder D-One descriptor vocabulary "
            "routed via public hosting"
        )
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", vocab)
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P13b: 'public hosting' in vocab.note refused (P13)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P13" in b and "descriptor_vocabulary.note" in b
                and "public hosting" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P13c. `share publicly` in allowlist.note refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        allow = _canonical_allowlist_with_entry()
        allow["note"] = (
            "Synthetic D-One endpoint allow-list share publicly "
            "later if approved"
        )
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", allow)
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P13c: 'share publicly' in allowlist.note refused (P13)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P13" in b and "endpoint_allowlist.note" in b
                and "share publicly" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P13d. `public upload` in spec.requests[0].prompt refused. The
    # spec's request `prompt` field has NO schema pattern (only
    # minLength: 1), so the runtime scan is the only gate at that slot.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["prompt"] = (
            "calm centered geometric motif; public upload of result"
        )
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P13d: 'public upload' in spec.requests[0].prompt refused "
            "(P13 — the spec request `prompt` field has no schema "
            "pattern, so the runtime scan is the only gate)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P13" in b
                and "d_one_spec.requests[0].prompt" in b
                and "public upload" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P13e. `publish to web` in spec.requests[0].intended_use refused.
    # The intended_use field is optional and also has no schema pattern.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["intended_use"] = (
            "spot illustration publish to web later"
        )
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P13e: 'publish to web' in spec.requests[0].intended_use "
            "refused (P13)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P13" in b
                and "d_one_spec.requests[0].intended_use" in b
                and "publish to web" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P13f. Safe boundary wording `no public upload` in preflight.note
    # ACCEPTED. The BEFORE-side `no` immediately preceding the deny
    # phrase exempts the match — a reviewer documenting that the
    # contract refuses public upload does NOT trip the gate.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pre = _canonical_preflight()
        pre["note"] = (
            "D-One live-run preflight record no public upload occurs"
        )
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", pre)
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P13f: safe boundary wording 'no public upload' in "
            "preflight.note ACCEPTED (P13 negation context)",
            audit["top_line_outcome"] == OUTCOME_READY
            and audit["blockers"] == [],
            f"audit={audit!r}",
        ))

    # P13g. Safe boundary wording `public upload is forbidden`
    # ACCEPTED. The AFTER-side `is forbidden` refusal copula exempts
    # the match.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pre = _canonical_preflight()
        pre["note"] = (
            "D-One live-run preflight record public upload is "
            "forbidden by allow-list"
        )
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", pre)
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P13g: safe boundary wording 'public upload is forbidden' "
            "in preflight.note ACCEPTED (P13 negation context — "
            "AFTER-side refusal copula)",
            audit["top_line_outcome"] == OUTCOME_READY
            and audit["blockers"] == [],
            f"audit={audit!r}",
        ))

    # ---- P14 credential / token free-form scan probes. The schema's
    # `note` whitelist refuses `:` outright, so the existing `password:`
    # / `api_key:` / `token:` literal scan in
    # validate_d_one_live_run_evidence is not sufficient — the bare
    # phrase `token placeholder` slips past the schema layer. The spec
    # request `prompt` / `intended_use` fields have no schema pattern
    # at all (only minLength: 1), and the opaque-ref / label /
    # path-label slots admit `_` / `-` separators so a hand-authored
    # value like `api_key_v2` or `sk-test-abc12345` also passes the
    # schema lock. P14 closes every gap.

    # P14a. Codex direct regression: `token placeholder` in
    # endpoint_allowlist.note refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        allow = _canonical_allowlist_with_entry()
        allow["note"] = (
            "Synthetic D-One endpoint allow-list token placeholder"
        )
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", allow)
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14a: 'token placeholder' in endpoint_allowlist.note "
            "refused (Codex-flagged regression — schema-layer `note` "
            "whitelist accepts bare 'token placeholder' so the runtime "
            "credential scan must catch it)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "endpoint_allowlist.note" in b
                and "'token'" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14b. Codex direct regression: `token placeholder` in
    # preflight_audit.note refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pre = _canonical_preflight()
        pre["note"] = (
            "D-One live-run preflight record token placeholder"
        )
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", pre)
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14b: 'token placeholder' in preflight_audit.note refused "
            "(Codex-flagged regression)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "preflight_audit.note" in b
                and "'token'" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14c. Codex direct regression: `token placeholder` in
    # spec.requests[0].prompt refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["prompt"] = (
            "calm centered geometric motif token placeholder"
        )
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14c: 'token placeholder' in spec.requests[0].prompt "
            "refused (Codex-flagged regression — the prompt field has "
            "no schema pattern at all)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "d_one_spec.requests[0].prompt" in b
                and "'token'" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14d. Codex direct regression: `api_key abcdef` in
    # spec.requests[0].prompt refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["prompt"] = (
            "calm centered geometric motif api_key abcdef"
        )
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14d: 'api_key abcdef' in spec.requests[0].prompt refused "
            "(Codex-flagged regression — `api_key` with `_` separator "
            "passes the `\\b` word-boundary regex; custom boundary "
            "treats `_` as a boundary so the bare credential word "
            "still fires)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "d_one_spec.requests[0].prompt" in b
                and "'api_key'" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14e. Safe synthetic baseline: a preflight whose every free-form
    # field carries plain English describing the contract — but NO
    # credential word — still passes. This is the contract-positive
    # counterpart to the Codex regressions; if P14 were over-broad it
    # would false-positive here.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["prompt"] = (
            "calm centered geometric motif rendered in muted tones; "
            "abstract; local placeholder for the readiness preflight"
        )
        spec["requests"][0]["intended_use"] = (
            "spot illustration for the synthetic readiness deck"
        )
        pre = _canonical_preflight()
        pre["note"] = (
            "D-One live-run preflight record; synthetic placeholder; "
            "no live call performed"
        )
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", pre)
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14e: safe synthetic baseline with plain-English notes "
            "and prompts (no credential word) still resolves to "
            "PREFLIGHT_READY_FOR_MANUAL_TRIAL (no false positives)",
            audit["top_line_outcome"] == OUTCOME_READY
            and audit["blockers"] == [],
            f"audit={audit!r}",
        ))

    # P14f. `token=value` in spec.requests[0].prompt refused. Covers
    # the `=` boundary char — the credential word boundary treats `=`
    # as a non-alnum separator, so `token=value` fires on the bare
    # `token`.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["prompt"] = (
            "calm centered geometric motif token=value-here"
        )
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14f: 'token=value' in spec.requests[0].prompt refused "
            "(custom boundary treats `=` as a non-alnum separator)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "d_one_spec.requests[0].prompt" in b
                and "'token'" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14g. `api key` (with a space, not an underscore) in
    # preflight_audit.note refused. Covers the space variant of
    # `api[_\-\s]?keys?`.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pre = _canonical_preflight()
        pre["note"] = (
            "D-One live-run preflight record api key omitted"
        )
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", pre)
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14g: 'api key' (space-separated) in preflight.note "
            "refused (P14 — `api[_\\-\\s]?keys?` covers underscore / "
            "hyphen / space / no-separator variants)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "preflight_audit.note" in b
                and "'api_key'" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14h. `bearer token` in preflight.note refused. Both the bare
    # `bearer` and the imported `bearer + 8+ opaque` shape can fire;
    # we assert at least one of them is present.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pre = _canonical_preflight()
        pre["note"] = (
            "D-One live-run preflight record bearer abcdefgh12345"
        )
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", pre)
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14h: 'bearer + opaque blob' in preflight.note refused",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "preflight_audit.note" in b
                and ("'bearer'" in b or "bearer token" in b)
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14i. `password` in vocab.note refused. The bare credential word
    # fires; the existing `password:` literal scan needs the `:` which
    # the schema layer refuses, so the bare-word scan is the only
    # gate at this surface.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        vocab = _canonical_vocab()
        vocab["note"] = (
            "Synthetic placeholder D-One descriptor vocabulary "
            "password hunter2"
        )
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", vocab)
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14i: bare word 'password' in vocab.note refused",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "descriptor_vocabulary.note" in b
                and "'password'" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14j. `secret` and `client_secret` in
    # spec.requests[0].intended_use refused (one probe, both words).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["intended_use"] = (
            "spot illustration client_secret rotation drill"
        )
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14j: 'client_secret' in spec.requests[0].intended_use "
            "refused (the bare `client_secret` word fires on both the "
            "embedded `secret` AND the compound `client_secret` "
            "patterns; both are credential-shaped)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "d_one_spec.requests[0].intended_use" in b
                and ("'client_secret'" in b or "'secret'" in b)
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14k. `private_key` embedded in spec.requests[0].prompt refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["prompt"] = (
            "calm centered geometric motif private_key rotation icon"
        )
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14k: 'private_key' in spec.requests[0].prompt refused",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "d_one_spec.requests[0].prompt" in b
                and "'private_key'" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14l. Stripe-style `sk-test-...` in spec.requests[0].prompt
    # refused. The leading `sk-test-` plus 8+ alphanumerics is the
    # canonical Stripe restricted-key prefix.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["prompt"] = (
            "calm centered motif sk-test-1234567890abcdef sample"
        )
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14l: Stripe-shape 'sk-test-1234567890abcdef' in "
            "spec.requests[0].prompt refused",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "d_one_spec.requests[0].prompt" in b
                and "Stripe-shape key" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14m. JWT-shape `eyJ...` in spec.requests[0].prompt refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["prompt"] = (
            "calm motif eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ."
            "abcdef12345 sample"
        )
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14m: JWT-shape 'eyJ...' in spec.requests[0].prompt "
            "refused (reuses _CREDENTIAL_PATTERNS JWT pattern)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "d_one_spec.requests[0].prompt" in b
                and "JWT-shaped" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14n. AWS access key `AKIA...` in spec.requests[0].prompt
    # refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["prompt"] = (
            "calm motif AKIAIOSFODNN7EXAMPLE icon"
        )
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14n: AWS access key 'AKIA...' in spec.requests[0]."
            "prompt refused (reuses _CREDENTIAL_PATTERNS AWS pattern)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "d_one_spec.requests[0].prompt" in b
                and "AWS access key" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14o. PEM marker `-----BEGIN ` in spec.requests[0].prompt
    # refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["prompt"] = (
            "calm motif -----BEGIN RSA PRIVATE marker"
        )
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14o: PEM marker '-----BEGIN ' in spec.requests[0]."
            "prompt refused (reuses _CREDENTIAL_PATTERNS PEM pattern)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "d_one_spec.requests[0].prompt" in b
                and "PEM marker" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14p. Long-hex blob (32+ contiguous hex chars) in
    # spec.requests[0].prompt refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec = _canonical_spec()
        spec["requests"][0]["prompt"] = (
            "calm motif "
            + "deadbeef" * 5  # 40 hex chars
            + " trailing"
        )
        spec_p = _write(td, "spec.json", spec)
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14p: 40-char hex blob in spec.requests[0].prompt "
            "refused (reuses _CREDENTIAL_PATTERNS long-hex pattern; "
            "no preflight field legitimately carries a 32+ hex blob)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "d_one_spec.requests[0].prompt" in b
                and "long hex blob" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14q. Credential word embedded in an opaque-label slot — this
    # surface admits `_` / `-` separators at the schema layer, so the
    # custom boundary scan is the only gate that catches credential
    # wording when it sneaks into a label like `sandbox_token` or
    # `api_key.endpoint`. The allowlist destination_label admits
    # `[A-Za-z][A-Za-z0-9_\\-]*` so `sandbox_token` passes the schema
    # lock; P14 must catch it.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        allow = _canonical_allowlist_with_entry()
        allow["entries"][0]["destination_label"] = "sandbox_token"
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", allow)
        pre_p = _write(td, "pre.json", _canonical_preflight())
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14q: credential word embedded in opaque-label slot "
            "(destination_label='sandbox_token') refused (custom "
            "boundary treats `_` as non-alnum so the bare `token` "
            "word still fires inside an identifier)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "endpoint_allowlist.entries[0]"
                ".destination_label" in b
                and "'token'" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14r. Negation context does NOT exempt P14. The reviewer who
    # writes "no password" should still pick a different phrasing
    # because the bare credential word indicates the operator was
    # thinking in credential terms. Unlike P13's public-upload scan,
    # P14 has no negation exemption.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pre = _canonical_preflight()
        pre["note"] = (
            "D-One live-run preflight record no password used"
        )
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", pre)
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14r: 'no password used' in preflight.note STILL refused "
            "(P14 has no negation-context exemption — unlike P13)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "preflight_audit.note" in b
                and "'password'" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # P14s. Credential value placed at the OPTIONAL
    # `preflight_audit.approvals.cleanup_ref` slot is refused. The
    # schema names this slot `cleanup_ref` (NOT `cleanup_approval_ref`
    # — an earlier draft of this helper mis-named it and the slot was
    # silently skipped under additionalProperties:false because no
    # value ever landed at the mis-spelt key); this probe pins the
    # correct field name so any future rename / typo regresses to a
    # red probe instead of a quiet false-green.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pre = _canonical_preflight()
        pre["approvals"]["cleanup_ref"] = "private_key_v2"
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", pre)
        audit = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        results.append(_expect(
            "P14s: 'private_key_v2' at preflight_audit.approvals."
            "cleanup_ref refused (pins the actual schema slot name; "
            "an earlier draft mis-named it `cleanup_approval_ref` and "
            "the slot was silently skipped)",
            audit["top_line_outcome"] == OUTCOME_BLOCKED
            and any(
                "P14" in b
                and "preflight_audit.approvals.cleanup_ref" in b
                and "'private_key'" in b
                for b in audit["blockers"]
            ),
            f"audit={audit!r}",
        ))

    # ---- 24. Audit blob keys / shape are deterministic across runs
    # (load-bearing — operator scripts may diff the audit JSON).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        spec_p = _write(td, "spec.json", _canonical_spec())
        vocab_p = _write(td, "vocab.json", _canonical_vocab())
        allow_p = _write(td, "allow.json", _canonical_allowlist_with_entry())
        pre_p = _write(td, "pre.json", _canonical_preflight())
        a = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        b = evaluate(spec_p, vocab_p, allow_p, pre_p, audit_out=None)
        # JSON-canonicalize both blobs and compare bytes — the audit
        # is meant to be byte-identical across two identical-input runs.
        a_bytes = json.dumps(a, sort_keys=True, indent=2)
        b_bytes = json.dumps(b, sort_keys=True, indent=2)
        results.append(_expect(
            "two evaluate() calls on identical inputs produce "
            "byte-identical audit JSON (determinism)",
            a_bytes == b_bytes,
            "audit blobs diverged",
        ))

    return results


# ---------------------------------------------------------------------------
# CLI entry point.
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Operator-facing local readiness preflight for a future "
            "real-D-One trial. Reads four caller-supplied local "
            "contract files (D-One spec, descriptor vocabulary, "
            "endpoint allow-list, preflight audit), validates every "
            "local prerequisite, and reports either "
            "LIVE_D_ONE_BLOCKED (with a blocker list) or "
            "PREFLIGHT_READY_FOR_MANUAL_TRIAL. This command does NOT "
            "call D-One / MCP / Qoder / any image-generation model / "
            "any public network / any external service; it does not "
            "run a live trial; it does not mutate any input file. "
            "PREFLIGHT_READY_FOR_MANUAL_TRIAL is NOT a PASS for live "
            "D-One — the readiness file's "
            "'Real D-One path: UNVERIFIED' wording remains "
            "load-bearing."
        ),
    )
    parser.add_argument(
        "--d-one-spec", type=Path,
        help=(
            "Path to a schemas/d_one_adapter_plan.schema.json file "
            "listing the D-One generation requests the operator "
            "would put on the wire."
        ),
    )
    parser.add_argument(
        "--descriptor-vocabulary", type=Path,
        help=(
            "Path to a schemas/d_one_descriptor_vocabulary.schema.json "
            "file (V1/V2/V3/V6 contract sketch)."
        ),
    )
    parser.add_argument(
        "--endpoint-allowlist", type=Path,
        help=(
            "Path to a schemas/d_one_endpoint_allowlist.schema.json "
            "file (R1/R2/R3/R5/R6 contract sketch)."
        ),
    )
    parser.add_argument(
        "--preflight-audit", type=Path,
        help=(
            "Path to a schemas/d_one_preflight_audit.schema.json "
            "file (M1-M4 + R1 + V1 + audit-out path placement "
            "contract sketch)."
        ),
    )
    parser.add_argument(
        "--audit-out", type=Path, default=None,
        help=(
            "OPTIONAL local path. When supplied, the readiness audit "
            "JSON written to stdout is also written verbatim to this "
            "path. Must not be a symlink, must not pre-exist, must "
            "not resolve inside the repo source tree, parent dir "
            "must already exist."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run in-script tempfixture scenarios covering the "
            "committed templates (which resolve to BLOCKED via the "
            "empty-allow-list default-deny resting state), a temp "
            "synthetic READY fixture, and one probe per failure "
            "mode (P1..P14) in the docstring. Exits non-zero if any "
            "scenario does not behave as expected. Mutually "
            "exclusive with the live arguments above."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        # Self-test is mutually exclusive with every live argument.
        live = (
            args.d_one_spec or args.descriptor_vocabulary
            or args.endpoint_allowlist or args.preflight_audit
            or args.audit_out
        )
        if live:
            print(
                "FAIL: --self-test does not take the live arguments "
                "(--d-one-spec / --descriptor-vocabulary / "
                "--endpoint-allowlist / --preflight-audit / --audit-out)",
                file=sys.stderr,
            )
            return 2
        results = _run_self_tests()
        fails = 0
        for name, ok, detail in results:
            mark = "PASS" if ok else "FAIL"
            suffix = f" -- {detail}" if not ok and detail else ""
            print(f"  [{mark}] {name}{suffix}")
            if not ok:
                fails += 1
        print()
        if fails:
            print(
                f"FAIL: {fails} self-test scenario(s) did not behave "
                f"as expected."
            )
            return 1
        print(
            "OK (self-test): D-One readiness preflight behaves as "
            "expected on every BLOCKED probe plus the temp synthetic "
            "READY fixture. This command does NOT run D-One; "
            "PREFLIGHT_READY_FOR_MANUAL_TRIAL is not PASS."
        )
        return 0

    # Live mode — every input flag required.
    missing = [
        f for f, v in (
            ("--d-one-spec", args.d_one_spec),
            ("--descriptor-vocabulary", args.descriptor_vocabulary),
            ("--endpoint-allowlist", args.endpoint_allowlist),
            ("--preflight-audit", args.preflight_audit),
        )
        if v is None
    ]
    if missing:
        print(
            f"FAIL: missing required argument(s): {', '.join(missing)}",
            file=sys.stderr,
        )
        return 2

    audit = evaluate(
        args.d_one_spec,
        args.descriptor_vocabulary,
        args.endpoint_allowlist,
        args.preflight_audit,
        audit_out=args.audit_out,
    )

    # Emit the audit JSON to stdout. Deterministic — sorted keys,
    # indent=2, trailing newline (matches the other helpers).
    audit_json = json.dumps(audit, sort_keys=True, indent=2) + "\n"
    sys.stdout.write(audit_json)

    # If --audit-out was supplied AND P12 passed (no P12-tagged
    # blockers), write the SAME bytes to the file. Otherwise refuse to
    # write (the path is unsafe / pre-existing / repo-output / its
    # parent is missing).
    if args.audit_out is not None:
        p12_failures = [b for b in audit["blockers"] if "(P12)" in b]
        if not p12_failures:
            args.audit_out.write_text(audit_json, encoding="utf-8")

    if audit["top_line_outcome"] == OUTCOME_READY:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
