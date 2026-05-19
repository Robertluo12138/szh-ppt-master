#!/usr/bin/env python3
"""Local validator for a future D-One live-run evidence record.

This script reads ONE caller-supplied JSON evidence file, schema-validates
it against ``schemas/d_one_live_run_evidence.schema.json``, and applies the
A11-A18 semantic cross-checks plus the readiness-contract gates listed in
``references/d-one-live-run-readiness.md`` §5 and §5.1.

THIS VALIDATOR DOES NOT RUN D-ONE. It performs no network call, opens no
model API, contacts no MCP server, reads no live endpoint, and writes no
PPTX. It is a local contract check on a single record file the caller has
already produced (or hand-authored for review). A schema-PASS result here
is a **necessary, not sufficient**, precondition for flipping
``Real D-One path: UNVERIFIED`` to ``VERIFIED`` in the readiness file —
A19 (re-binding the pinned ``plan_sha256`` to the actual plan on disk
via ``scripts/done_image_adapter.py --validate-plan``) and the §11 live
verification matrix still have to be exercised separately.

Gates applied to the record (every failed gate is reported; the script
exits non-zero if any gate fails):

  G1 ``readable_json_object``
    - the input file must exist as a regular non-symlink file;
    - the bytes must parse as JSON;
    - the parsed JSON must be a top-level object (a list, string, number,
      bool, or null at the root is refused — every required field below
      assumes an object root).

  G2 ``schema_subset_valid`` (A10)
    - the record validates against
      ``schemas/d_one_live_run_evidence.schema.json`` under the same
      stdlib-only JSON-Schema subset that ``scripts/validate_artifacts.py``
      applies.

  G3 ``per_request_outcome_consistency`` (A12)
    - if a row's ``outcome == "ok"``: ``output_magic_label`` AND
      ``output_sha256`` MUST be present; ``output_length_bytes`` MUST be
      > 0; ``rejection_reason`` MUST be absent.
    - if a row's ``outcome != "ok"``: ``rejection_reason`` MUST be
      present; ``output_magic_label`` / ``output_sha256`` /
      ``materialized_sha256`` MUST be absent.

  G4 ``run_outcome_consistency`` (A13 + stop-condition recording)
    - if ``run_outcome == "ok"``: ``gate_fired`` AND ``gate_detail``
      MUST be absent.
    - if ``run_outcome != "ok"``: ``gate_fired`` MUST be present (one
      of F1_allow_list_miss .. F17_approval_missing — the schema's enum
      already locks the value set; this gate enforces that the field is
      present at all when the run reports a stop condition).

  G5 ``cleanup_ref_consistency`` (A14)
    - if any ``per_image_review_refs[*].decision == "fail"``,
      ``approvals.cleanup_ref`` MUST be present.
    - otherwise ``approvals.cleanup_ref`` MUST be absent.

  G6 ``plan_count_equality`` (A15 — local half)
    - ``plan_request_count`` MUST equal ``len(requests)``.
    - The other half of A15 (``plan_request_count`` MUST equal the
      ``request_count`` recorded in the input plan whose sha256 is
      pinned by ``plan_sha256``) requires re-reading the plan and is
      explicitly OUT OF SCOPE for this single-file validator; A19
      covers the same plan-binding via
      ``scripts/done_image_adapter.py --validate-plan``.

  G7 ``per_image_review_coverage`` (A16)
    - the set of ``approvals.per_image_review_refs[*].id`` MUST equal
      the set of ``requests[*].id`` whose ``outcome == "ok"`` — no
      missing review row, no orphan review row, no duplicate review row.
    - For fully-failed runs where no request reached
      ``outcome == "ok"`` (e.g. F1 allow-list miss before any live
      call; F4 vocabulary miss; F6 transport error on every request),
      both sides of the set-equality are empty and the record MUST
      carry ``approvals.per_image_review_refs: []``. The schema's
      ``minItems`` on that array is ``0`` for exactly this case (an
      earlier draft had ``minItems: 1`` which made A16 unsatisfiable
      for fully-failed runs; paired schema + validator change brought
      them back into alignment).

  G8 ``materialized_hash_matches`` (A17)
    - for every request where both ``output_sha256`` and
      ``materialized_sha256`` are present, they MUST be byte-identical.

  G9 ``request_order_sorted_by_id`` (A18 — local half)
    - ``requests[]`` MUST be in lexicographic ascending order of ``id``.
      The full A18 check (order matches the input plan's order) requires
      the plan and is out of scope here; the plan itself is sorted by
      ``id`` (see ``scripts/done_image_adapter.py``), so checking sorted
      order in the record is the local-only equivalent.

  G10 ``ok_run_coherence`` (readiness §8 — PASS overclaim guard)
    - if ``run_outcome == "ok"``: every ``requests[*].outcome`` MUST be
      ``"ok"`` AND every ``approvals.per_image_review_refs[*].decision``
      MUST be ``"pass"``. A record that claims top-level PASS while a
      request rejected or a reviewer marked an image FAIL is internally
      inconsistent (per-image FAIL forces the §7 rollback path).

  G11 ``free_form_field_scan`` (A11 + readiness §6 + privacy rules)
    - free-form fields (``note``, ``gate_detail``, ``evidence_notes``,
      ``endpoint_label``, ``operator_label``, ``runner_version``,
      ``assets_dir_label``, every ``approvals.*_approval_ref``,
      ``operator_ref``, ``cleanup_ref``, every ``review_ref``) are
      re-scanned at runtime for credential shapes (JWT, AWS access key,
      PEM marker, long-hex blob, bearer token, ``password:`` /
      ``api_key:`` / ``token:`` / ``secret:`` / ``client_secret:`` /
      ``private_key:`` literals), PII shapes (email, phone-like,
      SSN-like, UUID, ``customer_id`` / ``account_id`` / ``user_id``
      literals), employee-id literals (``employee_id`` / ``emp_id`` /
      ``staff_id`` / ``badge_id``), internal-endpoint shapes (private
      IPv4 ranges, ``*.internal`` / ``*.local`` / ``*.corp`` / ``*.lan``
      / ``*.intranet`` TLDs), raw-source markers (``<source>`` /
      ``[source]`` / ``raw source`` / ``begin source`` / ``end source``
      / ``source document:`` / ``source text:`` / ``from the source``),
      and public-upload / public-sharing / public-hosting instructions
      (``upload to public ...`` / ``public upload`` / ``share publicly``
      / ``public hosting`` / ``publish to web`` / ``public URL``).
      The public-upload scan exempts safe negated boundary wording
      such as ``no public upload``, ``public upload is forbidden``,
      and ``public hosting is not used`` so a reviewer can document
      what the contract refuses without tripping the gate (privacy
      rules — evidence records must not direct an artifact to a
      public destination). Negation is recognised only when it sits
      IMMEDIATELY adjacent to the deny phrase: on the BEFORE side
      one of ``no`` / ``not`` / ``never`` / ``without`` followed by
      whitespace and nothing else; on the AFTER side an optional
      ``is/are/was/were`` copula followed by ``forbidden`` /
      ``prohibited`` / ``denied`` / ``disabled`` / ``blocked`` /
      ``refused`` / ``banned`` / ``not used`` / ``not allowed`` /
      ``not permitted`` / ``not enabled``. Intervening words on the
      BEFORE side are NOT honored — ``no operator approval public
      upload`` fires because the ``no`` applies to ``operator
      approval``, not to ``public upload`` — and strong verbs in
      ambiguous surface forms (``forbid public upload``, ``refused
      to share publicly``) are NOT honored as BEFORE-side refusal
      anchors, only as AFTER-side ones.
      The schema's positive-whitelist patterns already block most URL /
      path / URI-scheme shapes via character-class exclusion; this
      runtime scan covers the gap A11 names — long-hex and
      ``eyJ``-prefixed shapes can pass the schema's pattern lock
      because they would false-positive the legitimate ``sha256``
      fields if banned at the schema layer.

Out of scope for this validator (cross-references only):

  - calling D-One / Qoder / any image-generation model / any network;
  - mutating any file (this validator only reads the supplied evidence
    file);
  - validating the input plan whose sha256 is pinned by ``plan_sha256``
    — that is A19 territory; run
    ``scripts/done_image_adapter.py --validate-plan`` separately;
  - exercising the §11 live verification matrix — that requires a real
    live run;
  - confirming the endpoint label resolves to an entry in the
    (not-yet-written) endpoint allow-list file (R1);
  - confirming the descriptor vocabulary in force is the approved one
    (V1).

Exit codes:
  0  every gate passed.
  1  one or more gates failed.
  2  invocation / file / parse error.

CLI:
  python3 scripts/validate_d_one_live_run_evidence.py <path/to/record.json>
  python3 scripts/validate_d_one_live_run_evidence.py --self-test
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "schemas"

sys.path.insert(0, str(SCRIPTS_DIR))

from validate_artifacts import _validate  # noqa: E402

EVIDENCE_SCHEMA = SCHEMAS_DIR / "d_one_live_run_evidence.schema.json"
DESCRIPTOR_VOCAB_SCHEMA = SCHEMAS_DIR / "d_one_descriptor_vocabulary.schema.json"

# ---------------------------------------------------------------------------
# Free-form field scan tables (A11 + readiness §6 + privacy rules).
#
# These are the patterns the schema's positive-whitelist `pattern` locks
# cannot catch without false-positiving the legitimate sha256 fields.
# Every pattern is compiled once at module load.
# ---------------------------------------------------------------------------

_CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("AWS access key", re.compile(r"\bAKIA[A-Z0-9]{12,20}\b")),
    ("PEM marker", re.compile(r"-----BEGIN\s")),
    # long hex blob: 32+ contiguous hex chars. sha256 (64) and
    # intended_use_sha256 (64) are STRUCTURED fields validated by their
    # own schema pattern; the runtime scan deliberately skips those
    # field paths so the legitimate hashes don't false-positive.
    ("long hex blob", re.compile(r"\b[a-fA-F0-9]{32,}\b")),
    ("bearer token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}")),
)
_CREDENTIAL_LITERALS: tuple[str, ...] = (
    "password:",
    "passwd:",
    "secret:",
    "api_key:",
    "apikey:",
    "api-key:",
    "token:",
    "access_key:",
    "client_secret:",
    "private_key:",
)

_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("phone-like", re.compile(r"\+?\d{1,3}[-.\s]?\(?\d{3,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b")),
    ("SSN-like", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("UUID", re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
)
_PII_LITERALS: tuple[str, ...] = (
    "customer_id",
    "customer id:",
    "account_id",
    "account id:",
    "acct_id",
    "acct id:",
    "cust_id",
    "user_id",
    "user id:",
)

_EMPLOYEE_ID_LITERALS: tuple[str, ...] = (
    "employee_id",
    "employee id:",
    "emp_id",
    "emp id:",
    "staff_id",
    "staff id:",
    "badge_id",
    "badge id:",
)

# Private / internal endpoint shapes. The schema's positive-whitelist
# patterns already refuse `:` in most free-form positions, so a literal
# URL like `https://10.0.0.1` is refused at the schema layer; this scan
# catches the residual case of a bare host shape ("server1.internal",
# "10.0.0.1") slipped through fields that allow `.` (every approval-ref
# slot is `[A-Za-z0-9_.+\-]*` — bare host shapes can pass that).
_INTERNAL_ENDPOINT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # private IPv4: 10.0.0.0/8, 127.0.0.0/8, 192.168.0.0/16, 172.16.0.0/12.
    ("private IPv4", re.compile(
        r"\b(?:"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|127\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r")\b"
    )),
    ("internal TLD", re.compile(
        r"\b[A-Za-z0-9][A-Za-z0-9\-]*\.(?:internal|local|corp|lan|intranet)\b"
    )),
)

# Raw-source markers. Mirrors the same set scripts/done_image_adapter.py
# refuses in prompt bodies; here it covers evidence_notes / gate_detail /
# note, the only three free-form fields with enough character-class room
# to fit a marker phrase.
_SOURCE_MARKER_LITERALS: tuple[str, ...] = (
    "<source>",
    "</source>",
    "[source]",
    "[/source]",
    "raw source",
    "begin source",
    "end source",
    "source document:",
    "source text:",
    "from the source",
)

# Public-upload / public-sharing / public-hosting deny patterns. Evidence
# records must never direct an artifact to a public destination — that
# would breach the privacy rule "Outputs and manifests must not contain
# external URLs, file:// links, absolute paths, undeclared remote media".
# A reviewer can still DESCRIBE the boundary ("no public upload",
# "public upload is forbidden") without tripping the gate; see the
# _NEGATION_BEFORE_RE / _NEGATION_AFTER_RE check below.
#
# Only `note`, `gate_detail`, and `evidence_notes` allow spaces under
# their schema pattern locks, so these multi-word phrases can only land
# in those three free-form fields in practice. The scan runs over every
# free-form field anyway so a future schema relaxation cannot silently
# open a hole.
_PUBLIC_UPLOAD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "upload to public",
        re.compile(
            r"\bupload(?:ing|s|ed)?\s+to\s+(?:a\s+|the\s+)?public\b",
            re.IGNORECASE,
        ),
    ),
    (
        "public upload",
        re.compile(r"\bpublic\s+upload(?:ing|s|ed)?\b", re.IGNORECASE),
    ),
    (
        "share publicly",
        re.compile(
            r"\bshar(?:e|es|ed|ing)\s+publicly\b", re.IGNORECASE
        ),
    ),
    (
        "share to public",
        re.compile(
            r"\bshar(?:e|es|ed|ing)\s+to\s+(?:a\s+|the\s+)?public\b",
            re.IGNORECASE,
        ),
    ),
    (
        "public hosting",
        re.compile(
            r"\bpublic(?:ly)?\s+host(?:ing|ed|s)?\b", re.IGNORECASE
        ),
    ),
    (
        "publish to web",
        re.compile(
            r"\bpublish(?:ing|es|ed)?\s+to\s+(?:the\s+)?web\b",
            re.IGNORECASE,
        ),
    ),
    (
        "public URL",
        re.compile(r"\bpublic\s+url\b", re.IGNORECASE),
    ),
)

# Negation context. A public-upload pattern hit is treated as safe
# boundary wording (not a violation) when the match is either:
#   (a) IMMEDIATELY preceded — only ASCII whitespace between them, NO
#       intervening words — by one of the four unambiguous negation
#       determiners: `no`, `not`, `never`, `without`; OR
#   (b) IMMEDIATELY followed — only ASCII whitespace between them, an
#       optional `is/are/was/were` copula, NO intervening words — by a
#       refusal phrase (`forbidden`, `prohibited`, `denied`, `disabled`,
#       `blocked`, `refused`, `banned`, `not used`, `not allowed`,
#       `not permitted`, `not enabled`).
# Intervening words and strong-verb tokens (forbid/prohibit/deny/
# disable/block/refuse/ban as VERBS) are deliberately NOT honored on
# the BEFORE side: they create real bypasses. For example, with a 2-
# word intervening window the prose `"no operator approval public
# upload of secrets"` would falsely exempt the deny phrase (`no`
# applies to `operator approval`, NOT to `public upload`); with strong-
# verb tokens the imperative `"forbid public upload to bucket"` or the
# infinitival `"refused to share publicly"` would falsely exempt the
# directive in the same line. Strong-verb tokens are honored only as
# REFUSAL ANCHORS on the AFTER side (where they tail the deny phrase
# unambiguously), e.g. `"public upload is forbidden"`. A reviewer who
# wants to document a boundary should use one of the supported forms:
# `"no public upload"`, `"never public upload"`, `"without public
# upload"`, or `"public upload is forbidden/prohibited/denied/..."`.
_NEGATION_BEFORE_RE: re.Pattern[str] = re.compile(
    r"\b(?:no|not|never|without)\s+$",
    re.IGNORECASE,
)
_NEGATION_AFTER_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:(?:is|are|was|were)\s+)?"
    r"(?:not\s+(?:used|allowed|permitted|enabled|done)"
    r"|forbidden|prohibited|denied|disabled|blocked|refused|banned)\b",
    re.IGNORECASE,
)


def _public_upload_match_is_negated(
    text: str, start: int, end: int
) -> bool:
    """Return True iff the public-upload hit at ``text[start:end]`` sits
    in a safe negated/refused context (see _NEGATION_BEFORE_RE /
    _NEGATION_AFTER_RE)."""
    before = text[max(0, start - 64):start]
    if _NEGATION_BEFORE_RE.search(before):
        return True
    after = text[end:end + 64]
    if _NEGATION_AFTER_RE.search(after):
        return True
    return False


# Field paths where a sha256 hex value is legitimate (and must not be
# false-positived by the "long hex blob" credential check above). Each
# entry is a (top-level key, optional per-request key) tuple.
_SHA256_FIELD_PATHS: frozenset[tuple[str, ...]] = frozenset({
    ("plan_sha256",),
    ("requests[].prompt_sha256",),
    ("requests[].intended_use_sha256",),
    ("requests[].output_sha256",),
    ("requests[].materialized_sha256",),
})


def _scan_free_form(text: str, where: str) -> list[str]:
    """Return a list of credential / PII / employee-id / internal-endpoint
    / raw-source-marker violations for ``text``. Empty list -> safe."""
    violations: list[str] = []
    lower = text.lower()

    for label, pattern in _CREDENTIAL_PATTERNS:
        if pattern.search(text):
            violations.append(
                f"{where}: contains {label}-shaped substring"
            )
    for literal in _CREDENTIAL_LITERALS:
        if literal in lower:
            violations.append(
                f"{where}: contains credential literal {literal!r}"
            )
    for label, pattern in _PII_PATTERNS:
        if pattern.search(text):
            violations.append(
                f"{where}: contains {label}-shaped substring"
            )
    for literal in _PII_LITERALS:
        if literal in lower:
            violations.append(
                f"{where}: contains personal-id literal {literal!r}"
            )
    for literal in _EMPLOYEE_ID_LITERALS:
        if literal in lower:
            violations.append(
                f"{where}: contains employee-id literal {literal!r}"
            )
    for label, pattern in _INTERNAL_ENDPOINT_PATTERNS:
        if pattern.search(text):
            violations.append(
                f"{where}: contains {label}-shaped substring "
                f"(internal endpoint suspected; the allow-list maps "
                f"labels to destinations and nowhere else — R5)"
            )
    for literal in _SOURCE_MARKER_LITERALS:
        if literal in lower:
            violations.append(
                f"{where}: contains raw-source marker {literal!r} "
                f"(evidence records carry no raw source text — A7)"
            )
    for label, pattern in _PUBLIC_UPLOAD_PATTERNS:
        for m in pattern.finditer(text):
            if _public_upload_match_is_negated(
                text, m.start(), m.end()
            ):
                continue
            violations.append(
                f"{where}: contains public-upload-shaped phrase "
                f"{label!r} (evidence records must not direct any "
                f"artifact to public hosting / public sharing / "
                f"public upload — privacy rules)"
            )

    return violations


# ---------------------------------------------------------------------------
# Free-form-field enumeration. Every field listed here goes through
# _scan_free_form. Hash fields (sha256, prompt_sha256, ...) are
# DELIBERATELY excluded so the long-hex check does not false-positive.
# ---------------------------------------------------------------------------


def _free_form_field_paths(record: dict) -> list[tuple[str, str]]:
    """Return [(field_path, value), ...] for every free-form string in
    the record that the runtime scan covers. Skips sha256 / integer /
    enum-locked fields whose schema pattern already eliminates the
    credential / PII surface."""
    out: list[tuple[str, str]] = []

    for key in (
        "note",
        "runner_version",
        "endpoint_label",
        "operator_label",
        "assets_dir_label",
        "gate_detail",
        "evidence_notes",
    ):
        v = record.get(key)
        if isinstance(v, str):
            out.append((key, v))

    approvals = record.get("approvals")
    if isinstance(approvals, dict):
        for key in (
            "endpoint_approval_ref",
            "vocabulary_approval_ref",
            "deck_approval_ref",
            "operator_ref",
            "cleanup_ref",
        ):
            v = approvals.get(key)
            if isinstance(v, str):
                out.append((f"approvals.{key}", v))

        rows = approvals.get("per_image_review_refs")
        if isinstance(rows, list):
            for i, row in enumerate(rows):
                if isinstance(row, dict):
                    review_ref = row.get("review_ref")
                    if isinstance(review_ref, str):
                        out.append(
                            (
                                f"approvals.per_image_review_refs[{i}]"
                                f".review_ref",
                                review_ref,
                            )
                        )

    # Per-request id and manifest_local_path can hold short opaque
    # strings; intended_use is not in this record (only the hash is). The
    # schema's `id` pattern already refuses URI / path shapes; we run the
    # runtime scan anyway because the schema cannot catch JWT / AWS-key
    # shaped ids.
    requests = record.get("requests")
    if isinstance(requests, list):
        for i, row in enumerate(requests):
            if isinstance(row, dict):
                rid = row.get("id")
                if isinstance(rid, str):
                    out.append((f"requests[{i}].id", rid))
                mpath = row.get("manifest_local_path")
                if isinstance(mpath, str):
                    out.append(
                        (f"requests[{i}].manifest_local_path", mpath)
                    )
                # endpoint_label per request (optional override).
                ep = row.get("endpoint_label")
                if isinstance(ep, str):
                    out.append((f"requests[{i}].endpoint_label", ep))

    return out


# ---------------------------------------------------------------------------
# Cross-checks A11-A18 + readiness §8 PASS overclaim guard.
# ---------------------------------------------------------------------------


def _check_per_request_outcome(record: dict) -> list[str]:
    """G3 — A12."""
    errors: list[str] = []
    requests = record.get("requests")
    if not isinstance(requests, list):
        return errors
    for i, row in enumerate(requests):
        if not isinstance(row, dict):
            continue
        outcome = row.get("outcome")
        magic = row.get("output_magic_label")
        out_sha = row.get("output_sha256")
        mat_sha = row.get("materialized_sha256")
        rej = row.get("rejection_reason")
        length = row.get("output_length_bytes")
        if outcome == "ok":
            if magic is None:
                errors.append(
                    f"requests[{i}]: outcome == 'ok' but "
                    f"output_magic_label is absent (A12)"
                )
            if out_sha is None:
                errors.append(
                    f"requests[{i}]: outcome == 'ok' but "
                    f"output_sha256 is absent (A12)"
                )
            if isinstance(length, int) and length <= 0:
                errors.append(
                    f"requests[{i}]: outcome == 'ok' but "
                    f"output_length_bytes ({length}) is not > 0 (A12)"
                )
            if rej is not None:
                errors.append(
                    f"requests[{i}]: outcome == 'ok' but "
                    f"rejection_reason is present (A12)"
                )
        else:
            if rej is None:
                errors.append(
                    f"requests[{i}]: outcome != 'ok' but "
                    f"rejection_reason is absent (A12)"
                )
            for field, value in (
                ("output_magic_label", magic),
                ("output_sha256", out_sha),
                ("materialized_sha256", mat_sha),
            ):
                if value is not None:
                    errors.append(
                        f"requests[{i}]: outcome != 'ok' but "
                        f"{field} is present (A12)"
                    )
    return errors


def _check_run_outcome(record: dict) -> list[str]:
    """G4 — A13 + stop-condition recording."""
    errors: list[str] = []
    outcome = record.get("run_outcome")
    gate = record.get("gate_fired")
    detail = record.get("gate_detail")
    if outcome == "ok":
        if gate is not None:
            errors.append(
                "run_outcome == 'ok' but gate_fired is present (A13)"
            )
        if detail is not None:
            errors.append(
                "run_outcome == 'ok' but gate_detail is present (A13)"
            )
    else:
        if gate is None:
            errors.append(
                f"run_outcome == {outcome!r} but gate_fired is absent "
                f"(A13 — stop condition must be recorded as one of "
                f"F1_allow_list_miss .. F17_approval_missing)"
            )
    return errors


def _check_cleanup_ref(record: dict) -> list[str]:
    """G5 — A14."""
    errors: list[str] = []
    approvals = record.get("approvals")
    if not isinstance(approvals, dict):
        return errors
    reviews = approvals.get("per_image_review_refs")
    if not isinstance(reviews, list):
        return errors
    any_fail = any(
        isinstance(r, dict) and r.get("decision") == "fail"
        for r in reviews
    )
    cleanup = approvals.get("cleanup_ref")
    if any_fail and cleanup is None:
        errors.append(
            "approvals.per_image_review_refs has at least one "
            "decision == 'fail' but approvals.cleanup_ref is absent "
            "(A14)"
        )
    if not any_fail and cleanup is not None:
        errors.append(
            "approvals.per_image_review_refs has no 'fail' decision "
            "but approvals.cleanup_ref is present (A14)"
        )
    return errors


def _check_plan_count(record: dict) -> list[str]:
    """G6 — A15 (local half)."""
    errors: list[str] = []
    plan_count = record.get("plan_request_count")
    requests = record.get("requests")
    if not isinstance(plan_count, int):
        return errors
    if not isinstance(requests, list):
        return errors
    if plan_count != len(requests):
        errors.append(
            f"plan_request_count ({plan_count}) != len(requests) "
            f"({len(requests)}) (A15). "
            f"The other half of A15 (== request_count recorded in the "
            f"input plan whose sha256 is pinned by plan_sha256) is "
            f"out of scope for this single-file validator; run "
            f"scripts/done_image_adapter.py --validate-plan separately."
        )
    return errors


def _check_review_coverage(record: dict) -> list[str]:
    """G7 — A16."""
    errors: list[str] = []
    requests = record.get("requests")
    approvals = record.get("approvals")
    if not isinstance(requests, list) or not isinstance(approvals, dict):
        return errors
    reviews = approvals.get("per_image_review_refs")
    if not isinstance(reviews, list):
        return errors

    ok_ids: set[str] = set()
    for r in requests:
        if isinstance(r, dict) and r.get("outcome") == "ok":
            rid = r.get("id")
            if isinstance(rid, str):
                ok_ids.add(rid)

    review_ids: list[str] = []
    for r in reviews:
        if isinstance(r, dict):
            rid = r.get("id")
            if isinstance(rid, str):
                review_ids.append(rid)
    review_id_set = set(review_ids)

    if len(review_ids) != len(review_id_set):
        # The schema does not forbid duplicates within
        # per_image_review_refs; reject them here so a duplicate review
        # row cannot fake coverage.
        seen: set[str] = set()
        dupes: list[str] = []
        for rid in review_ids:
            if rid in seen and rid not in dupes:
                dupes.append(rid)
            seen.add(rid)
        errors.append(
            f"approvals.per_image_review_refs has duplicate id(s): "
            f"{sorted(dupes)} (A16 — one review row per ok image)"
        )

    missing = sorted(ok_ids - review_id_set)
    orphan = sorted(review_id_set - ok_ids)
    if missing:
        errors.append(
            f"approvals.per_image_review_refs missing review rows for "
            f"ok requests: {missing} (A16)"
        )
    if orphan:
        errors.append(
            f"approvals.per_image_review_refs has orphan review rows "
            f"with no matching ok request: {orphan} (A16)"
        )
    return errors


def _check_materialized_hash(record: dict) -> list[str]:
    """G8 — A17."""
    errors: list[str] = []
    requests = record.get("requests")
    if not isinstance(requests, list):
        return errors
    for i, row in enumerate(requests):
        if not isinstance(row, dict):
            continue
        out_sha = row.get("output_sha256")
        mat_sha = row.get("materialized_sha256")
        if (
            isinstance(out_sha, str)
            and isinstance(mat_sha, str)
            and out_sha != mat_sha
        ):
            errors.append(
                f"requests[{i}]: output_sha256 ({out_sha!r}) != "
                f"materialized_sha256 ({mat_sha!r}) (A17 — a mismatch "
                f"is itself a F12 / F13 condition for the materialize "
                f"run)"
            )
    return errors


def _check_request_order(record: dict) -> list[str]:
    """G9 — A18 (local half)."""
    errors: list[str] = []
    requests = record.get("requests")
    if not isinstance(requests, list):
        return errors
    ids: list[str] = []
    for r in requests:
        if isinstance(r, dict):
            rid = r.get("id")
            if isinstance(rid, str):
                ids.append(rid)
    if ids != sorted(ids):
        errors.append(
            f"requests[] is not sorted by id (A18 — the input plan is "
            f"written sorted by id by scripts/done_image_adapter.py; "
            f"got order={ids!r}, expected={sorted(ids)!r})"
        )
    return errors


def _check_ok_run_coherence(record: dict) -> list[str]:
    """G10 — readiness §8 PASS overclaim guard.

    A record claiming top-level PASS (``run_outcome == "ok"``) while a
    request rejected or a reviewer marked an image FAIL is internally
    inconsistent: the §7 contract says per-image FAIL forces the
    rollback path and the run_outcome would be ``rolled_back``."""
    errors: list[str] = []
    if record.get("run_outcome") != "ok":
        return errors

    requests = record.get("requests")
    if isinstance(requests, list):
        bad = []
        for i, r in enumerate(requests):
            if isinstance(r, dict) and r.get("outcome") != "ok":
                bad.append((i, r.get("outcome")))
        if bad:
            errors.append(
                f"run_outcome == 'ok' but per-request outcome(s) "
                f"are not 'ok': {bad} (readiness §8 overclaim — "
                f"top-level PASS requires every request 'ok')"
            )

    approvals = record.get("approvals")
    if isinstance(approvals, dict):
        reviews = approvals.get("per_image_review_refs")
        if isinstance(reviews, list):
            bad_reviews = []
            for i, r in enumerate(reviews):
                if isinstance(r, dict) and r.get("decision") != "pass":
                    bad_reviews.append((i, r.get("decision")))
            if bad_reviews:
                errors.append(
                    f"run_outcome == 'ok' but per-image-review "
                    f"decision(s) are not 'pass': {bad_reviews} "
                    f"(readiness §8 overclaim — M5 FAIL forces the §7 "
                    f"rollback path so run_outcome should be "
                    f"'rolled_back')"
                )
    return errors


def _check_free_form_scan(record: dict) -> list[str]:
    """G11 — A11 + readiness §6 + privacy rules."""
    errors: list[str] = []
    for where, value in _free_form_field_paths(record):
        errors.extend(_scan_free_form(value, where))
    return errors


# ---------------------------------------------------------------------------
# Top-level validation.
# ---------------------------------------------------------------------------


def validate_record(record: Any, schema: dict) -> list[str]:
    """Return a list of validation errors for ``record``. Empty list ->
    PASS (necessary, not sufficient — A19 + §11 live verification matrix
    are still required separately).

    Layered: schema errors are surfaced first; semantic cross-checks
    run only if the schema check passes (cross-checks assume schema-
    conformant input)."""
    if not isinstance(record, dict):
        return [
            f"<root>: expected JSON object, got "
            f"{type(record).__name__}"
        ]

    schema_errors: list[str] = []
    _validate(record, schema, "<root>", schema_errors)
    if schema_errors:
        return schema_errors

    errors: list[str] = []
    errors.extend(_check_per_request_outcome(record))
    errors.extend(_check_run_outcome(record))
    errors.extend(_check_cleanup_ref(record))
    errors.extend(_check_plan_count(record))
    errors.extend(_check_review_coverage(record))
    errors.extend(_check_materialized_hash(record))
    errors.extend(_check_request_order(record))
    errors.extend(_check_ok_run_coherence(record))
    errors.extend(_check_free_form_scan(record))
    return errors


def _load_evidence(path: Path) -> tuple[Any | None, str]:
    """Return (record, error). On error, record is None and error is
    a non-empty diagnostic. The two preflight gates (G1) — file exists
    as a regular non-symlink, JSON parses — are applied here."""
    if path.is_symlink():
        try:
            target = str(path.readlink())
        except OSError:
            target = "<unreadable>"
        return None, (
            f"FAIL: {path} is a symlink (-> {target}); refuses "
            f"to follow it (broken or not)"
        )
    if not path.is_file():
        return None, f"FAIL: {path} is not a regular file"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"FAIL: cannot read {path}: {exc}"
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, (
            f"FAIL: {path} is not valid JSON: {exc}"
        )
    return record, ""


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs under
# tempfile.TemporaryDirectory(); no fixture leaks into the repo.
# ---------------------------------------------------------------------------


def _expect(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


def _minimal_ok_record() -> dict:
    """Return a minimal schema-valid AND cross-check-valid record. Used
    as the baseline for every "tweak one field" scenario."""
    return {
        "schema_version": 1,
        "mode": "live",
        "note": "D-One live-run evidence record",
        "runner_version": "v0.1.0",
        "endpoint_label": "sandbox_alpha",
        "disable_switch_state": "off",
        "operator_label": "op7",
        "clock_label": "2026-05-18T12:34:56Z",
        "plan_sha256": _HASH_A,
        "plan_request_count": 1,
        "assets_dir_label": "assets",
        "run_outcome": "ok",
        "requests": [
            {
                "id": "cover_accent",
                "prompt_sha256": _HASH_B,
                "manifest_local_path": "media/cover_accent.png",
                "manifest_source": "d_one_local",
                "outcome": "ok",
                "elapsed_ms": 100,
                "output_length_bytes": 1024,
                "output_magic_label": "png",
                "output_sha256": _HASH_C,
                "materialized_sha256": _HASH_C,
            },
        ],
        "approvals": {
            "endpoint_approval_ref": "ep_appr_001",
            "vocabulary_approval_ref": "vocab_appr_001",
            "deck_approval_ref": "deck_appr_001",
            "operator_ref": "op_ref_001",
            "per_image_review_refs": [
                {"id": "cover_accent", "decision": "pass"},
            ],
        },
    }


def _canonical_descriptor_vocab() -> dict:
    """Return a canonical, schema-valid descriptor vocabulary payload that
    the in-script taxonomy probes can mutate. Mirrors the synthetic
    template at examples/d_one_descriptor_vocabulary_template.json but is
    kept in-script so the probes do not depend on on-disk template bytes
    (a probe that loaded the on-disk template would silently mask a
    drift between schema and template — the schema/template pair is
    intentionally re-validated by the
    `python3 scripts/validate_artifacts.py --schema ... <template>`
    command separately)."""
    return {
        "schema_version": 1,
        "note": (
            "Synthetic placeholder D-One descriptor vocabulary for "
            "in-script taxonomy probes."
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
                    "flat_vector",
                    "line_diagram",
                    "isometric_lite",
                    "low_poly",
                    "solid_shape",
                ],
            },
            "palette_family": {
                "allowed_values": [
                    "neutral_grey",
                    "accent_only",
                    "dual_tone",
                    "mono_brand",
                    "palette_default",
                ],
            },
            "image_role": {
                "allowed_values": [
                    "decorative_accent",
                    "metaphor_icon",
                    "divider_motif",
                    "kpi_emblem",
                    "cover_motif",
                ],
            },
            "layout_pattern": {
                "allowed_values": [
                    "single_center",
                    "left_anchor",
                    "right_anchor",
                    "top_band",
                    "bottom_band",
                ],
            },
            "modifier": {
                "allowed_values": [
                    "low_contrast",
                    "soft_edges",
                    "grid_aligned",
                    "negative_space",
                ],
            },
        },
        "synthetic_requests": [
            {
                "id": "cover_motif_neutral",
                "rendering_style": "flat_vector",
                "palette_family": "neutral_grey",
                "image_role": "cover_motif",
                "layout_pattern": "single_center",
                "modifier": "negative_space",
            },
        ],
    }


def _write(td: Path, name: str, payload: Any | bytes) -> Path:
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


def _validate_path(path: Path, schema: dict) -> tuple[int, list[str]]:
    record, err = _load_evidence(path)
    if err:
        return 1, [err]
    errors = validate_record(record, schema)
    return (0 if not errors else 1), errors


def _run_self_tests() -> list[tuple[str, bool, str]]:  # noqa: C901
    import tempfile

    schema = json.loads(EVIDENCE_SCHEMA.read_text(encoding="utf-8"))
    results: list[tuple[str, bool, str]] = []

    # ---- 1. minimal happy path passes every gate. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        p = _write(td, "rec.json", _minimal_ok_record())
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "minimal valid evidence record passes every gate",
            rc == 0 and not errs,
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 2. malformed JSON refused (G1). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        p = _write(td, "rec.json", "{not-valid-json")
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "malformed JSON refused (G1)",
            rc == 1 and any("not valid JSON" in e for e in errs),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 3. list-rooted JSON refused (G1). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        p = _write(td, "rec.json", [_minimal_ok_record()])
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "list-rooted JSON refused (G1)",
            rc == 1 and any(
                "expected JSON object" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 4. string-rooted JSON refused (G1). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        # json.dumps("...") produces a quoted JSON string value at the
        # root — parses successfully but is NOT a JSON object.
        p = _write(td, "rec.json", json.dumps("just a string"))
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "string-rooted JSON refused (G1)",
            rc == 1 and any(
                "expected JSON object" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 5. missing required top-level field refused (G2). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        del rec["plan_sha256"]
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "missing required field 'plan_sha256' refused (G2)",
            rc == 1 and any(
                "missing required property 'plan_sha256'" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 6. wrong mode ('dry_run') refused (G2 schema enum). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["mode"] = "dry_run"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "mode != 'live' refused at schema layer (G2)",
            rc == 1 and any(
                "not in enum" in e and "mode" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 7. additional property at root refused (G2). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["extra_field"] = "smuggle"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "additional property at root refused (G2)",
            rc == 1 and any(
                "additional property 'extra_field' not allowed" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 8. per-request outcome='ok' missing output_sha256 (G3). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        del rec["requests"][0]["output_sha256"]
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "outcome=='ok' but output_sha256 absent refused (G3/A12)",
            rc == 1 and any(
                "output_sha256 is absent" in e and "A12" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 9. per-request outcome='ok' with rejection_reason (G3). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["requests"][0]["rejection_reason"] = "other"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "outcome=='ok' with rejection_reason refused (G3/A12)",
            rc == 1 and any(
                "rejection_reason is present" in e and "A12" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 10. per-request outcome='rejected' missing rejection_reason. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        # Rejected at the request level. run_outcome must move off 'ok'.
        rec["run_outcome"] = "rejected"
        rec["gate_fired"] = "F4_vocabulary_miss"
        req = rec["requests"][0]
        req["outcome"] = "rejected"
        req["output_length_bytes"] = 0
        for k in ("output_magic_label", "output_sha256",
                  "materialized_sha256"):
            req.pop(k, None)
        # Remove the now-orphan review row to keep A16 clean.
        rec["approvals"]["per_image_review_refs"] = [
            {"id": "x_dummy", "decision": "pass"},
        ]
        # But that orphan trips A16. The schema's minItems on
        # per_image_review_refs is 0, so an empty array would also
        # satisfy the schema; we keep an orphan here so the assertion
        # focuses on A12: rejected row missing rejection_reason still
        # fires A12 even when A16 also fires.
        rec["approvals"]["per_image_review_refs"] = [
            {"id": "cover_accent", "decision": "pass"},
        ]
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "outcome!='ok' with no rejection_reason refused (G3/A12)",
            rc == 1 and any(
                "rejection_reason is absent" in e and "A12" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 11. run_outcome='ok' with gate_fired refused (G4/A13). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["gate_fired"] = "F4_vocabulary_miss"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "run_outcome=='ok' with gate_fired refused (G4/A13)",
            rc == 1 and any(
                "gate_fired is present" in e and "A13" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 12. run_outcome='rolled_back' but gate_fired absent (G4). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["run_outcome"] = "rolled_back"
        # Make per-request consistency hold for the stop-condition path:
        # the row was rolled back too.
        req = rec["requests"][0]
        req["outcome"] = "error"
        req["rejection_reason"] = "transport_error"
        req["output_length_bytes"] = 0
        for k in ("output_magic_label", "output_sha256",
                  "materialized_sha256"):
            req.pop(k, None)
        # Keep a review for the now-failed request: the schema's
        # minItems on per_image_review_refs is 0, so an empty array
        # would satisfy the schema; we reuse the id to leave A16
        # firing alongside the target gate. The row outcome != 'ok'
        # so A16 sees ok_ids=empty AND review_ids={cover_accent} ->
        # orphan. To keep the test minimal we accept that and expect
        # BOTH gate_fired and the orphan-review errors; the test
        # asserts the gate_fired one is present.
        rec["approvals"]["per_image_review_refs"] = [
            {"id": "cover_accent", "decision": "pass"},
        ]
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "run_outcome=='rolled_back' but gate_fired absent "
            "refused (G4/A13)",
            rc == 1 and any(
                "gate_fired is absent" in e and "A13" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 13. per_image_review decision='fail' without cleanup_ref. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        # Rolled-back run with a failed review. Per-request outcome was
        # 'ok' (the live call succeeded) but the reviewer flagged FAIL,
        # forcing the §7 rollback path.
        rec["run_outcome"] = "rolled_back"
        rec["gate_fired"] = "F14_per_image_review_fail"
        rec["approvals"]["per_image_review_refs"] = [
            {"id": "cover_accent", "decision": "fail"},
        ]
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "review decision=='fail' with no cleanup_ref refused "
            "(G5/A14)",
            rc == 1 and any(
                "cleanup_ref is absent" in e and "A14" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 14. cleanup_ref present but no failed review refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["approvals"]["cleanup_ref"] = "cleanup_ref_001"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "cleanup_ref present without failed review refused "
            "(G5/A14)",
            rc == 1 and any(
                "cleanup_ref is present" in e and "A14" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 15. plan_request_count mismatch refused (G6/A15). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["plan_request_count"] = 5
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "plan_request_count != len(requests) refused (G6/A15)",
            rc == 1 and any(
                "plan_request_count" in e and "len(requests)" in e
                and "A15" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 16. per_image_review missing for ok request (G7/A16). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        # Two ok requests but only one review.
        rec["requests"].append({
            "id": "section_hero",
            "prompt_sha256": _HASH_B,
            "manifest_local_path": "media/section_hero.jpg",
            "manifest_source": "d_one_local",
            "outcome": "ok",
            "elapsed_ms": 50,
            "output_length_bytes": 2048,
            "output_magic_label": "jpg",
            "output_sha256": _HASH_C,
            "materialized_sha256": _HASH_C,
        })
        rec["plan_request_count"] = 2
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "ok request without matching review row refused "
            "(G7/A16)",
            rc == 1 and any(
                "missing review rows" in e and "section_hero" in e
                and "A16" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 17. orphan review row refused (G7/A16). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["approvals"]["per_image_review_refs"].append(
            {"id": "ghost_image", "decision": "pass"},
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "orphan per_image_review row refused (G7/A16)",
            rc == 1 and any(
                "orphan review rows" in e and "ghost_image" in e
                and "A16" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 18. duplicate per_image_review row refused (G7/A16). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["approvals"]["per_image_review_refs"].append(
            {"id": "cover_accent", "decision": "pass"},
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "duplicate per_image_review id refused (G7/A16)",
            rc == 1 and any(
                "duplicate id(s)" in e and "cover_accent" in e
                and "A16" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 19. materialized_sha256 != output_sha256 refused (G8/A17). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["requests"][0]["materialized_sha256"] = "d" * 64
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "materialized_sha256 != output_sha256 refused (G8/A17)",
            rc == 1 and any(
                "A17" in e and "materialized_sha256" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 20. unsorted requests refused (G9/A18). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["requests"][0]["id"] = "zebra"
        rec["requests"].append({
            "id": "alpha",
            "prompt_sha256": _HASH_B,
            "manifest_local_path": "media/alpha.png",
            "manifest_source": "d_one_local",
            "outcome": "ok",
            "elapsed_ms": 50,
            "output_length_bytes": 100,
            "output_magic_label": "png",
            "output_sha256": _HASH_C,
            "materialized_sha256": _HASH_C,
        })
        rec["plan_request_count"] = 2
        rec["approvals"]["per_image_review_refs"] = [
            {"id": "alpha", "decision": "pass"},
            {"id": "zebra", "decision": "pass"},
        ]
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "requests not sorted by id refused (G9/A18)",
            rc == 1 and any(
                "not sorted by id" in e and "A18" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 21. PASS overclaim: run_outcome='ok' but one request is. ----
    # rejected — refused (G10).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        # The first request is still ok (so its A12 fields are
        # consistent); add a second rejected request. run_outcome is
        # still 'ok' — that's the overclaim we want to catch.
        rec["plan_request_count"] = 2
        rec["requests"].append({
            "id": "section_hero",
            "prompt_sha256": _HASH_B,
            "manifest_local_path": "media/section_hero.jpg",
            "manifest_source": "d_one_local",
            "outcome": "rejected",
            "rejection_reason": "vocabulary_miss",
            "elapsed_ms": 5,
            "output_length_bytes": 0,
        })
        # Reviews still cover the ok request (cover_accent) only —
        # section_hero never produced bytes.
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "run_outcome=='ok' with a rejected request refused "
            "(G10 overclaim)",
            rc == 1 and any(
                "overclaim" in e and "per-request outcome" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 22. PASS overclaim: run_outcome='ok' with a 'fail' review. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["approvals"]["per_image_review_refs"][0]["decision"] = "fail"
        rec["approvals"]["cleanup_ref"] = "cleanup_001"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "run_outcome=='ok' with a fail review refused "
            "(G10 overclaim)",
            rc == 1 and any(
                "overclaim" in e and "per-image-review" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 23. JWT in evidence_notes refused (G11/A11). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        # A realistic-shape JWT: three dot-separated runs of base64-url
        # chars, each >= 8 chars after the eyJ prefix.
        rec["evidence_notes"] = (
            "context eyJhbGciOiJIUzI1NiJ9"
            ".eyJzdWIiOiIxMjM0NTY3OD"
            ".SflKxwRJSMeKKF2QT4fwp end"
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "JWT-shaped substring in evidence_notes refused (G11)",
            rc == 1 and any(
                "JWT-shaped" in e and "evidence_notes" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 24. AWS access key in gate_detail refused (G11). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["run_outcome"] = "error"
        rec["gate_fired"] = "F6_transport_error"
        rec["gate_detail"] = "key AKIAABCDEFGHIJKLMNOP failed"
        # Per-request must move off ok to match A13's run_outcome.
        req = rec["requests"][0]
        req["outcome"] = "error"
        req["rejection_reason"] = "transport_error"
        req["output_length_bytes"] = 0
        for k in ("output_magic_label", "output_sha256",
                  "materialized_sha256"):
            req.pop(k, None)
        # Drop the now-orphan review.
        rec["approvals"]["per_image_review_refs"] = [
            {"id": "cover_accent", "decision": "pass"},
        ]
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "AWS access key in gate_detail refused (G11)",
            rc == 1 and any(
                "AWS access key-shaped" in e and "gate_detail" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 25. employee_id literal in evidence_notes refused (G11). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = "reviewer employee_id 12345 signed off"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "employee_id literal in evidence_notes refused (G11)",
            rc == 1 and any(
                "employee-id literal" in e and "evidence_notes" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 26. internal TLD in approval ref refused (G11). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["approvals"]["endpoint_approval_ref"] = "host1.internal"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "internal TLD in endpoint_approval_ref refused (G11)",
            rc == 1 and any(
                "internal TLD-shaped" in e
                and "endpoint_approval_ref" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 27. private IPv4 substring in evidence_notes refused (G11). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = "ran against host 10.0.0.7 (rejected)"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "private IPv4 in evidence_notes refused (G11)",
            rc == 1 and any(
                "private IPv4-shaped" in e and "evidence_notes" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 28. raw-source marker in evidence_notes refused (G11). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = "drift note from the source body"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "raw-source marker 'from the source' refused (G11)",
            rc == 1 and any(
                "raw-source marker" in e and "from the source" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 29. customer_id literal in evidence_notes refused (G11). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = "filed against customer_id 7-XYZ for review"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "customer_id literal in evidence_notes refused (G11)",
            rc == 1 and any(
                "personal-id literal" in e and "customer_id" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 30. legitimate sha256 hashes do not false-positive (G11). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        # plan_sha256, prompt_sha256, output_sha256,
        # materialized_sha256 are all 64-char hex. They are NOT
        # free-form fields and the runtime scan must not flag them.
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "legitimate sha256 fields do not trip the long-hex "
            "credential scan",
            rc == 0 and not errs,
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 31. missing file returns rc=1 with clear diagnostic. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        missing = td / "does_not_exist.json"
        rc, errs = _validate_path(missing, schema)
        results.append(_expect(
            "missing file refused with clear diagnostic",
            rc == 1 and any(
                "not a regular file" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 32. symlink at evidence path refused (G1). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        real = _write(td, "real.json", _minimal_ok_record())
        link = td / "link.json"
        link.symlink_to(real)
        rc, errs = _validate_path(link, schema)
        results.append(_expect(
            "symlink at evidence path refused (G1)",
            rc == 1 and any(
                "is a symlink" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 33. unknown gate_fired enum refused (G2 schema). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["run_outcome"] = "error"
        rec["gate_fired"] = "F99_unknown_gate"
        req = rec["requests"][0]
        req["outcome"] = "error"
        req["rejection_reason"] = "transport_error"
        req["output_length_bytes"] = 0
        for k in ("output_magic_label", "output_sha256",
                  "materialized_sha256"):
            req.pop(k, None)
        rec["approvals"]["per_image_review_refs"] = [
            {"id": "cover_accent", "decision": "pass"},
        ]
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "unknown gate_fired enum value refused (G2)",
            rc == 1 and any(
                "not in enum" in e and "gate_fired" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 34. URI scheme in evidence_notes refused at schema layer. ----
    # The schema's pattern lock on evidence_notes refuses ':' outright,
    # so a URI-shape never reaches the runtime scan.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = "see https://attacker.example for details"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "URI-shape in evidence_notes refused at schema layer (G2)",
            rc == 1 and any(
                "does not match pattern" in e and "evidence_notes" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 35. URI-scheme in note refused at schema layer (G2). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["note"] = (
            "D-One live-run evidence record http://attacker.example"
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "URI in 'note' refused at schema layer (G2)",
            rc == 1 and any(
                "does not match pattern" in e and "note" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 36. 'password:' credential literal in gate_detail refused. ----
    # The schema's positive-whitelist pattern on gate_detail refuses
    # ':' outright, so credential literals like 'password:' / 'token:' /
    # 'secret:' / 'api_key:' / 'access_key:' / 'client_secret:' /
    # 'private_key:' are refused at the schema layer (G2) before the
    # runtime credential-literal scan (G11) gets a chance to fire. This
    # test confirms the schema-layer interception so the contract is
    # honest about which gate caught the value.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["run_outcome"] = "error"
        rec["gate_fired"] = "F6_transport_error"
        rec["gate_detail"] = "auth failed password: hunter2"
        req = rec["requests"][0]
        req["outcome"] = "error"
        req["rejection_reason"] = "transport_error"
        req["output_length_bytes"] = 0
        for k in ("output_magic_label", "output_sha256",
                  "materialized_sha256"):
            req.pop(k, None)
        rec["approvals"]["per_image_review_refs"] = [
            {"id": "cover_accent", "decision": "pass"},
        ]
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "'password:' literal in gate_detail refused at schema "
            "layer (G2 — pattern lock refuses ':' outright)",
            rc == 1 and any(
                "does not match pattern" in e and "gate_detail" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 37. SSN-like substring in evidence_notes refused (G11). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = "reviewer 123-45-6789 signed off"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "SSN-like substring in evidence_notes refused (G11)",
            rc == 1 and any(
                "SSN-like-shaped" in e and "evidence_notes" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 38a. valid fully-failed run (F1 allow-list miss before any
    # live call) is ACCEPTED with empty per_image_review_refs. Every
    # request rejected, ok-id set is empty; A16 strict set-equality
    # holds (empty == empty); schema's minItems on
    # per_image_review_refs is 0 so the empty array passes the
    # schema gate. Per A1 (every live run, success OR failure,
    # produces exactly one audit record), failed-run records like
    # this MUST be accepted. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["run_outcome"] = "rejected"
        rec["gate_fired"] = "F1_allow_list_miss"
        req = rec["requests"][0]
        req["outcome"] = "rejected"
        req["rejection_reason"] = "vocabulary_miss"
        req["output_length_bytes"] = 0
        for k in ("output_magic_label", "output_sha256",
                  "materialized_sha256"):
            req.pop(k, None)
        rec["approvals"]["per_image_review_refs"] = []
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "valid fully-failed run (F1 allow-list miss; every request "
            "rejected; per_image_review_refs == []) is accepted "
            "(strict A16 holds: empty == empty)",
            rc == 0 and not errs,
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 38b. valid fully-failed run (F6 transport error on every
    # request; run_outcome == "error") is ACCEPTED with empty
    # per_image_review_refs. Different gate / outcome, same A16
    # set-equality path. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["run_outcome"] = "error"
        rec["gate_fired"] = "F6_transport_error"
        req = rec["requests"][0]
        req["outcome"] = "error"
        req["rejection_reason"] = "transport_error"
        req["output_length_bytes"] = 0
        for k in ("output_magic_label", "output_sha256",
                  "materialized_sha256"):
            req.pop(k, None)
        rec["approvals"]["per_image_review_refs"] = []
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "valid fully-failed run (F6 transport error; every request "
            "error; per_image_review_refs == []) is accepted "
            "(strict A16 holds: empty == empty)",
            rc == 0 and not errs,
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 38c. fully-failed run with a NON-EMPTY per_image_review_refs
    # is REFUSED — strict A16 calls every row an orphan (no request
    # reached outcome=='ok' so no id can match). This is the strict
    # A16 working as documented; a record like this would have been
    # written by a buggy producer that didn't follow the canonical
    # contract. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["run_outcome"] = "rejected"
        rec["gate_fired"] = "F4_vocabulary_miss"
        req = rec["requests"][0]
        req["outcome"] = "rejected"
        req["rejection_reason"] = "vocabulary_miss"
        req["output_length_bytes"] = 0
        for k in ("output_magic_label", "output_sha256",
                  "materialized_sha256"):
            req.pop(k, None)
        rec["approvals"]["per_image_review_refs"] = [
            {"id": "cover_accent", "decision": "pass"},
        ]
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "fully-failed run with non-empty per_image_review_refs "
            "refused (strict A16: every row is an orphan when no "
            "request reached ok)",
            rc == 1 and any(
                "orphan review rows" in e and "cover_accent" in e
                and "A16" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 38d. PARTIALLY-failed run (one request ok, one rejected)
    # still applies strict A16: the ok request MUST have a matching
    # review row, and a missing one is refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["run_outcome"] = "rolled_back"
        rec["gate_fired"] = "F4_vocabulary_miss"
        rec["plan_request_count"] = 2
        # Keep the original cover_accent request as outcome="ok"; add
        # a second request that was rejected.
        rec["requests"].append({
            "id": "section_hero",
            "prompt_sha256": _HASH_B,
            "manifest_local_path": "media/section_hero.jpg",
            "manifest_source": "d_one_local",
            "outcome": "rejected",
            "rejection_reason": "vocabulary_miss",
            "elapsed_ms": 5,
            "output_length_bytes": 0,
        })
        # Drop the review row for cover_accent to trigger A16 missing.
        rec["approvals"]["per_image_review_refs"] = [
            {"id": "section_hero", "decision": "pass"},
        ]
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "partially-failed run (mixed ok / rejected) still applies "
            "strict A16: missing review for the ok request is refused",
            rc == 1 and any(
                "missing review rows" in e and "cover_accent" in e
                and "A16" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 38. happy path with rolled-back run + cleanup_ref passes. ----
    # Verifies the fail-side branch of every cross-check is internally
    # consistent (no false positives when the record is honest about a
    # failed live call).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["run_outcome"] = "rolled_back"
        rec["gate_fired"] = "F14_per_image_review_fail"
        rec["gate_detail"] = "per-image review flagged a fail decision"
        # The request itself was ok (live call produced bytes); the
        # reviewer marked the image FAIL, forcing rollback.
        rec["approvals"]["per_image_review_refs"] = [
            {"id": "cover_accent", "decision": "fail"},
        ]
        rec["approvals"]["cleanup_ref"] = "cleanup_001"
        # Per the contract: even though the run rolled back, the
        # per-image review row still references the request that DID
        # reach outcome=='ok' — A16 expects coverage over ok requests,
        # and the live call succeeded before review. So the ok request
        # set is {cover_accent} and the review id set is {cover_accent}.
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "honest rolled-back run with cleanup_ref passes every "
            "cross-check",
            rc == 0 and not errs,
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 39. 'upload to public bucket' in evidence_notes refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = (
            "operator asked to upload to public bucket for review"
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "'upload to public bucket' in evidence_notes refused (G11)",
            rc == 1 and any(
                "public-upload-shaped phrase" in e
                and "upload to public" in e
                and "evidence_notes" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 40. 'public upload' in evidence_notes refused (G11). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = "queued a public upload of the asset"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "'public upload' in evidence_notes refused (G11)",
            rc == 1 and any(
                "public-upload-shaped phrase" in e
                and "'public upload'" in e
                and "evidence_notes" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 41. 'share publicly' in gate_detail refused (G11). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["run_outcome"] = "error"
        rec["gate_fired"] = "F6_transport_error"
        rec["gate_detail"] = "operator tried to share publicly mid-run"
        req = rec["requests"][0]
        req["outcome"] = "error"
        req["rejection_reason"] = "transport_error"
        req["output_length_bytes"] = 0
        for k in ("output_magic_label", "output_sha256",
                  "materialized_sha256"):
            req.pop(k, None)
        rec["approvals"]["per_image_review_refs"] = []
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "'share publicly' in gate_detail refused (G11)",
            rc == 1 and any(
                "public-upload-shaped phrase" in e
                and "share publicly" in e
                and "gate_detail" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 42. safe boundary wording 'no public upload' accepted. ----
    # The reviewer is documenting what the contract refuses; the deny
    # gate must not fire on the negated/boundary form.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = (
            "boundary note no public upload occurred during the run"
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "safe boundary wording 'no public upload' accepted (G11 "
            "negation context)",
            rc == 0 and not errs,
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 43. safe boundary wording 'public upload is forbidden'
    # accepted. The deny phrase is immediately followed by the refusal
    # copula 'is forbidden' so the gate treats the clause as a boundary
    # note rather than an instruction. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = (
            "policy reminder public upload is forbidden by the "
            "endpoint allow-list"
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "safe boundary wording 'public upload is forbidden' "
            "accepted (G11 negation context)",
            rc == 0 and not errs,
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 44. 'public hosting' refused; 'public hosting is not used'
    # accepted. Covers the second deny phrase from the readiness rule
    # plus its safe boundary form. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = "routed via public hosting for preview"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "'public hosting' in evidence_notes refused (G11)",
            rc == 1 and any(
                "public-upload-shaped phrase" in e
                and "public hosting" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = (
            "compliance note public hosting is not used by this runner"
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "safe boundary wording 'public hosting is not used' "
            "accepted (G11 negation context)",
            rc == 0 and not errs,
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 45. 'publish to web' and 'public URL' refused (G11). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = "operator wanted to publish to web later"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "'publish to web' in evidence_notes refused (G11)",
            rc == 1 and any(
                "public-upload-shaped phrase" in e
                and "publish to web" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = "requested a public URL for the assets"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "'public URL' in evidence_notes refused (G11)",
            rc == 1 and any(
                "public-upload-shaped phrase" in e
                and "'public URL'" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 46. negation-bypass regressions (G11). Three forms a prior
    # draft of _NEGATION_BEFORE_RE incorrectly exempted; each MUST now
    # fire. (a) `no` + intervening words: the negation applies to the
    # intervening noun phrase, NOT to the deny phrase. (b) bare
    # imperative `forbid` prepended: a strong verb's surface form can
    # be read as either a refusal OR a directive, so it is no longer
    # honored as a refusal anchor on the BEFORE side. (c) infinitival
    # `refused to`: same ambiguity. The fix is immediate adjacency on
    # the BEFORE side (only `no`/`not`/`never`/`without`, no
    # intervening words); strong-verb tokens are honored only on the
    # AFTER side where they unambiguously tail the deny phrase. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = (
            "no operator approval public upload of the secrets"
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "negation-bypass regression: 'no' + 2 intervening words "
            "before a deny phrase no longer exempts the deny (the "
            "negation applies to the intervening noun phrase, not the "
            "deny phrase) — fires (G11)",
            rc == 1 and any(
                "public-upload-shaped phrase" in e
                and "'public upload'" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = "forbid public upload to a bucket"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "negation-bypass regression: bare imperative strong verb "
            "('forbid') prepended to a deny phrase no longer exempts "
            "the deny (the surface form is ambiguous between refusal "
            "and directive) — fires (G11)",
            rc == 1 and any(
                "public-upload-shaped phrase" in e
                and "'public upload'" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _minimal_ok_record()
        rec["evidence_notes"] = "operator refused to share publicly"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "negation-bypass regression: 'refused to' + deny phrase "
            "no longer exempts the deny (infinitival construction is "
            "ambiguous; honored only via the AFTER side where the "
            "refusal unambiguously tails the deny phrase) — fires "
            "(G11)",
            rc == 1 and any(
                "public-upload-shaped phrase" in e
                and "share publicly" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 47. immediate-adjacency negation acceptance is preserved
    # for the remaining three determiners (`not` / `never` / `without`)
    # plus `no upload to public bucket` (showing the exemption works
    # across all deny patterns, not only `public upload`). ----
    for note in (
        "boundary not public upload here",
        "policy says never public upload assets",
        "ran without public upload during the trial",
        "no upload to public bucket happened in this run",
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            rec = _minimal_ok_record()
            rec["evidence_notes"] = note
            p = _write(td, "rec.json", rec)
            rc, errs = _validate_path(p, schema)
            results.append(_expect(
                f"safe boundary wording accepted (immediate adjacency "
                f"negation): {note!r}",
                rc == 0 and not errs,
                f"rc={rc}, errs={errs!r}",
            ))

    # ---- Taxonomy probes (image-request taxonomy contract). ----
    # Defense-in-depth probes for the image_taxonomy + synthetic_requests
    # extension to schemas/d_one_descriptor_vocabulary.schema.json. The
    # five dimensions (rendering_style, palette_family, image_role,
    # layout_pattern, modifier) are closed enumerations. The probes
    # confirm: (a) the canonical synthetic vocabulary validates clean;
    # (b) each documented forbidden token shape is refused at the schema
    # layer when injected into a descriptor value, an allowed_values
    # slot, or a synthetic_requests slot; (c) a shape-valid but
    # out-of-taxonomy value is refused by the enum lock; (d) a tampered
    # allowed_values length is refused by the maxItems lock. The probes
    # do NOT call D-One / Qoder / any image-generation model / any
    # network — they only validate in-memory JSON payloads written to a
    # tempfile against the on-disk schema.
    vocab_schema = json.loads(
        DESCRIPTOR_VOCAB_SCHEMA.read_text(encoding="utf-8")
    )
    taxonomy_dims = (
        "rendering_style",
        "palette_family",
        "image_role",
        "layout_pattern",
        "modifier",
    )
    forbidden_descriptor_values = (
        "public_upload",
        "raw_source",
        "full_slide",
        "image_search",
        "web_generation",
        "customer_acme",
        "confidential_report",
        "https://example.com",
        "file:///etc/passwd",
        "https://cdn.public.example.com/asset.png",
        "Acme reported revenue of $4.2M in Q3",
    )

    # T1: canonical descriptor vocabulary (descriptors + image_taxonomy
    # + synthetic_requests) validates clean.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        p = _write(td, "vocab.json", _canonical_descriptor_vocab())
        errs: list[str] = []
        _validate(json.loads(p.read_text()), vocab_schema, "<root>", errs)
        results.append(_expect(
            "T1: canonical descriptor vocabulary "
            "(taxonomy + synthetic_requests) validates clean",
            errs == [],
            f"errs={errs!r}",
        ))

    # T2: each documented forbidden value is refused when injected as a
    # descriptors[*].value. The descriptor value pattern is the only
    # gate at that slot (no enum), so a pattern-error confirms the
    # deny-clause is doing the work.
    for forbidden in forbidden_descriptor_values:
        rec = _canonical_descriptor_vocab()
        rec["descriptors"].append(
            {"kind": "geometric_noun", "value": forbidden}
        )
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            p = _write(td, "vocab.json", rec)
            errs = []
            _validate(json.loads(p.read_text()), vocab_schema, "<root>", errs)
            results.append(_expect(
                f"T2: forbidden descriptor value refused at "
                f"schema layer: {forbidden!r}",
                any("does not match pattern" in e for e in errs),
                f"errs={errs!r}",
            ))

    # T3: each documented forbidden value is refused when injected into
    # any image_taxonomy.<dim>.allowed_values slot. At that slot the
    # closed enum AND the deny pattern both apply; either failure mode
    # is acceptable evidence that the gate held.
    for dim in taxonomy_dims:
        for forbidden in forbidden_descriptor_values:
            rec = _canonical_descriptor_vocab()
            rec["image_taxonomy"][dim]["allowed_values"][0] = forbidden
            with tempfile.TemporaryDirectory() as raw_td:
                td = Path(raw_td)
                p = _write(td, "vocab.json", rec)
                errs = []
                _validate(
                    json.loads(p.read_text()), vocab_schema, "<root>", errs
                )
                results.append(_expect(
                    f"T3: forbidden value refused in "
                    f"image_taxonomy.{dim}.allowed_values: {forbidden!r}",
                    any(
                        "not in enum" in e or "does not match pattern" in e
                        for e in errs
                    ),
                    f"errs={errs!r}",
                ))

    # T4: each documented forbidden value is refused when injected into
    # a synthetic_requests[*].<dim> slot. Same closed-enum + deny-pattern
    # surface; either failure is acceptable evidence.
    for dim in taxonomy_dims:
        for forbidden in forbidden_descriptor_values:
            rec = _canonical_descriptor_vocab()
            rec["synthetic_requests"][0][dim] = forbidden
            with tempfile.TemporaryDirectory() as raw_td:
                td = Path(raw_td)
                p = _write(td, "vocab.json", rec)
                errs = []
                _validate(
                    json.loads(p.read_text()), vocab_schema, "<root>", errs
                )
                results.append(_expect(
                    f"T4: forbidden value refused in "
                    f"synthetic_requests[0].{dim}: {forbidden!r}",
                    any(
                        "not in enum" in e or "does not match pattern" in e
                        for e in errs
                    ),
                    f"errs={errs!r}",
                ))

    # T5: a shape-valid but out-of-taxonomy value (e.g. "drawing") is
    # refused by the per-dimension closed enum. This isolates the enum
    # lock so a future loosening of the descriptor pattern would still
    # be caught by the enum.
    out_of_taxonomy_value = "drawing"
    for dim in taxonomy_dims:
        rec = _canonical_descriptor_vocab()
        rec["synthetic_requests"][0][dim] = out_of_taxonomy_value
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            p = _write(td, "vocab.json", rec)
            errs = []
            _validate(
                json.loads(p.read_text()), vocab_schema, "<root>", errs
            )
            results.append(_expect(
                f"T5: shape-valid but out-of-taxonomy value refused in "
                f"synthetic_requests[0].{dim}: {out_of_taxonomy_value!r}",
                any("not in enum" in e for e in errs),
                f"errs={errs!r}",
            ))

    # T6: omitting the optional 'modifier' in a synthetic_request still
    # validates clean (modifier is the only optional dimension).
    rec = _canonical_descriptor_vocab()
    rec["synthetic_requests"][0].pop("modifier")
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        p = _write(td, "vocab.json", rec)
        errs = []
        _validate(json.loads(p.read_text()), vocab_schema, "<root>", errs)
        results.append(_expect(
            "T6: synthetic_request with optional 'modifier' omitted "
            "validates clean",
            errs == [],
            f"errs={errs!r}",
        ))

    # T7: appending a duplicate to allowed_values overflows the
    # fixed-length lock (maxItems). Proves a tampered file cannot widen
    # the surface even with otherwise-legal tokens.
    expected_lengths = {
        "rendering_style": 5,
        "palette_family": 5,
        "image_role": 5,
        "layout_pattern": 5,
        "modifier": 4,
    }
    for dim, want_len in expected_lengths.items():
        rec = _canonical_descriptor_vocab()
        rec["image_taxonomy"][dim]["allowed_values"].append(
            rec["image_taxonomy"][dim]["allowed_values"][0]
        )
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            p = _write(td, "vocab.json", rec)
            errs = []
            _validate(
                json.loads(p.read_text()), vocab_schema, "<root>", errs
            )
            results.append(_expect(
                f"T7: image_taxonomy.{dim}.allowed_values overflow "
                f"refused (maxItems={want_len})",
                any(f"maxItems is {want_len}" in e for e in errs),
                f"errs={errs!r}",
            ))

    # T8: removing a required dimension from image_taxonomy is refused.
    for dim in taxonomy_dims:
        rec = _canonical_descriptor_vocab()
        rec["image_taxonomy"].pop(dim)
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            p = _write(td, "vocab.json", rec)
            errs = []
            _validate(
                json.loads(p.read_text()), vocab_schema, "<root>", errs
            )
            results.append(_expect(
                f"T8: missing image_taxonomy.{dim} refused (required lock)",
                any(
                    f"missing required property '{dim}'" in e for e in errs
                ),
                f"errs={errs!r}",
            ))

    # T9: an additional property on synthetic_requests[0] is refused
    # (additionalProperties: false at the request shape).
    rec = _canonical_descriptor_vocab()
    rec["synthetic_requests"][0]["smuggled"] = "anything"
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        p = _write(td, "vocab.json", rec)
        errs = []
        _validate(json.loads(p.read_text()), vocab_schema, "<root>", errs)
        results.append(_expect(
            "T9: extra property in synthetic_requests[0] refused "
            "(additionalProperties: false)",
            any(
                "additional property 'smuggled' not allowed" in e
                for e in errs
            ),
            f"errs={errs!r}",
        ))

    # T10: a noncanonical allowed_values array that ships duplicates is
    # refused by the uniqueItems lock. Without uniqueItems, the schema
    # would false-green an array like ["flat_vector"] * 5 — the items
    # all match items.enum and the array satisfies minItems == maxItems,
    # but the canonical set is gone. uniqueItems combined with
    # items.enum of length N and minItems == maxItems == N forces the
    # array to be a permutation of the canonical set, closing the gap
    # Codex stop-time review flagged.
    for dim in taxonomy_dims:
        rec = _canonical_descriptor_vocab()
        canonical_first = rec["image_taxonomy"][dim]["allowed_values"][0]
        # Overwrite the second slot with a duplicate of the first; the
        # array still satisfies length + items.enum + items.pattern
        # individually, but uniqueItems must refuse the duplicate.
        rec["image_taxonomy"][dim]["allowed_values"][1] = canonical_first
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            p = _write(td, "vocab.json", rec)
            errs = []
            _validate(
                json.loads(p.read_text()), vocab_schema, "<root>", errs
            )
            results.append(_expect(
                f"T10: duplicate in image_taxonomy.{dim}.allowed_values "
                f"refused by uniqueItems "
                f"(noncanonical-allowed_values false-green closed)",
                any(
                    "duplicate element refused under uniqueItems" in e
                    for e in errs
                ),
                f"errs={errs!r}",
            ))

    # T10b: the noncanonical extreme case — an allowed_values array
    # that ships the SAME canonical value N times (e.g. ["flat_vector",
    # "flat_vector", "flat_vector", "flat_vector", "flat_vector"]).
    # This is the exact shape the Codex review named: every element is
    # in items.enum, length is exact, but uniqueItems must refuse it.
    for dim in taxonomy_dims:
        rec = _canonical_descriptor_vocab()
        first = rec["image_taxonomy"][dim]["allowed_values"][0]
        rec["image_taxonomy"][dim]["allowed_values"] = [
            first for _ in rec["image_taxonomy"][dim]["allowed_values"]
        ]
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            p = _write(td, "vocab.json", rec)
            errs = []
            _validate(
                json.loads(p.read_text()), vocab_schema, "<root>", errs
            )
            results.append(_expect(
                f"T10b: image_taxonomy.{dim}.allowed_values ship the "
                f"same canonical value N times refused by uniqueItems",
                any(
                    "duplicate element refused under uniqueItems" in e
                    for e in errs
                ),
                f"errs={errs!r}",
            ))

    return results


# ---------------------------------------------------------------------------
# CLI entry point.
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stdlib-only validator for a future D-One live-run evidence "
            "record. Schema-validates the supplied JSON file against "
            "schemas/d_one_live_run_evidence.schema.json and applies the "
            "A11-A18 semantic cross-checks plus the readiness contract "
            "gates in references/d-one-live-run-readiness.md. This "
            "validator DOES NOT call D-One / Qoder / any image-"
            "generation model / any public network / any external "
            "service; it does not run a live call; it does not mutate "
            "any file. PASS here is a necessary, not sufficient, "
            "precondition — A19 (re-binding plan_sha256 to the actual "
            "plan via scripts/done_image_adapter.py --validate-plan) "
            "and the §11 live verification matrix still have to be "
            "exercised separately."
        ),
    )
    parser.add_argument(
        "evidence", type=Path, nargs="?", default=None,
        help=(
            "Path to a JSON evidence record produced by a future "
            "live D-One run (or hand-authored for review). Must be a "
            "regular non-symlink file containing a JSON OBJECT at the "
            "root."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run in-script tempfixture scenarios covering every gate "
            "G1-G11 plus the happy paths. Exits non-zero if any "
            "scenario does not behave as expected. Mutually exclusive "
            "with the positional evidence argument."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if args.evidence is not None:
            print(
                "FAIL: --self-test does not take a positional "
                "evidence argument",
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
            "OK (self-test): D-One live-run evidence validator behaves "
            "as expected on every fail-closed scenario plus the happy "
            "paths. This validator does NOT run D-One; PASS here is "
            "necessary, not sufficient."
        )
        return 0

    if args.evidence is None:
        print(
            "FAIL: missing positional evidence argument (use "
            "--self-test for the in-script scenarios)",
            file=sys.stderr,
        )
        return 2

    if not EVIDENCE_SCHEMA.is_file():
        print(
            f"FAIL: evidence schema not found at {EVIDENCE_SCHEMA}",
            file=sys.stderr,
        )
        return 2

    try:
        schema = json.loads(EVIDENCE_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"FAIL: cannot load evidence schema {EVIDENCE_SCHEMA}: "
            f"{exc}",
            file=sys.stderr,
        )
        return 2

    rc, errs = _validate_path(args.evidence, schema)
    if rc != 0:
        print(f"FAIL: {args.evidence}")
        for e in errs:
            print(f"  - {e}")
        print(
            "\nNote: this validator does NOT run D-One. Even when "
            "every gate PASSes, that is a necessary, not sufficient, "
            "precondition — A19 (re-binding plan_sha256 to the actual "
            "plan on disk) and the references/d-one-live-integration-"
            "design.md §11 live verification matrix still have to be "
            "exercised separately before the readiness file's status "
            "can move from UNVERIFIED to VERIFIED."
        )
        return 1

    print(f"OK: {args.evidence} validates against the readiness contract.")
    print(
        "Note: this validator does NOT run D-One. PASS here is a "
        "necessary, not sufficient, precondition — A19 (re-binding "
        "plan_sha256 to the actual plan on disk via "
        "scripts/done_image_adapter.py --validate-plan) and the "
        "references/d-one-live-integration-design.md §11 live "
        "verification matrix still have to be exercised separately "
        "before the readiness file's status can move from UNVERIFIED "
        "to VERIFIED."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
