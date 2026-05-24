#!/usr/bin/env python3
"""Local validator for the mock-image bundle trial evidence record.

This script reads ONE caller-supplied JSON evidence file (the structured
JSON object emitted by ``scripts/mock_image_bundle_trial_evidence.py``),
schema-validates it against
``schemas/mock_image_bundle_trial_evidence.schema.json`` under the same
stdlib-only JSON-Schema subset that ``scripts/validate_artifacts.py``
applies, and runs the documented semantic + string-safety + real-D-One
claim-refusal gates. The validator is **read-only**: it never writes,
mutates, or removes any file, and never calls D-One / MCP / a public
network / any model API / image search / Qoder / telemetry.

A schema-PASS plus every-gate-PASS result certifies the evidence record
is internally consistent and self-honest about the MOCK / STUB nature of
the chain that produced it. It does NOT certify a real D-One run
happened — by contract, no such run is performed by this skill today.

Gates applied (every failed gate is reported; the script exits non-zero
on any failure):

  G1 ``readable_json_object``
    - the input file must exist as a regular non-symlink file;
    - the bytes must parse as JSON;
    - the parsed JSON must be a top-level object (a list, string,
      number, bool, or null at the root is refused — every required
      field below assumes an object root).

  G2 ``schema_subset_valid``
    - the record validates against
      ``schemas/mock_image_bundle_trial_evidence.schema.json`` under
      the same draft-07 subset ``scripts/validate_artifacts.py``
      implements (``additionalProperties:false`` at every declared
      object level; ``schema_version`` enum-locked to ``"1"`` and
      ``evidence_id`` enum-locked to
      ``"mock_image_bundle_trial_evidence"`` are surfaced here).

  G3 ``real_d_one_status_phrasing``
    - ``real_d_one_status`` MUST contain the literal substring
      ``UNVERIFIED`` (case-insensitive) AND at least one explicit
      negation of a forbidden service ("is NOT called", "NOT MCP",
      "no public network", etc.) so a tampered status string cannot
      smuggle a positive claim past the schema's length-only bounds.

  G4 ``summary_ok_consistency``
    - ``summary.ok == true`` requires every documented sub-condition
      to hold simultaneously:
        * ``pptx.exists == true`` AND ``pptx.size_bytes > 0``;
        * ``inventory.ok == true``, ``inventory.findings == []``
          (``findings_empty == true``),
          ``inventory.slide_count == 2``
          (``slide_count_matches_plan == true``),
          ``inventory.media_parts_count >= 2``
          (``media_parts_count_min_met == true``),
          ``inventory.evidence_basis`` matches the canonical
          ``"OOXML structure only; not proof of full PowerPoint
          editability"`` line (``evidence_basis_matches == true``),
          ``inventory.no_external_relationships == true``;
        * every validator's ``rc == 0`` AND ``ok == true``
          (``validate_pptx_contract``, ``inspect_pptx_inventory``,
          ``validate_mock_d_one_adapter_plan``);
        * ``validators.validate_mock_d_one_adapter_plan
          .vocabulary_gate_used == true`` AND
          ``require_both_placement_roles_used == true``;
        * ``sidecar.exists == true``, ``sidecar.parses_as_json ==
          true``, ``sidecar.schema_version == 4``
          (``schema_version_locked == true``);
        * ``sidecar.request_count == len(sidecar.requests)``
          (``request_count_matches_requests == true``);
        * ``sidecar.all_requests_well_formed == true`` AND
          ``sidecar.malformed_request_indices == []``;
        * ``sidecar.placement_role_coverage`` equals exactly
          ``["hero_page", "local_region"]``
          (``covers_both_placement_roles == true``).
      An inconsistent record — e.g. ``summary.ok == true`` paired
      with a failed validator or a missing placement role — is
      refused regardless of how the underlying gates were observed.

  G5 ``per_request_well_formed``
    - every entry under ``sidecar.requests[]`` MUST carry
      ``id`` / ``placement_role`` / ``text_policy`` /
      ``subject_domain`` / ``manifest_local_path`` as non-empty
      strings; the optional ``custom_descriptor``, when present,
      MUST itself be a non-empty string. The schema also enforces
      these via per-field types + ``minLength``; this gate re-asserts
      them as a belt-and-braces gate (and catches any future schema
      relaxation that would silently let nulls through).

  G6 ``placement_role_coverage``
    - the set of ``sidecar.requests[*].placement_role`` values MUST
      equal exactly ``{"hero_page", "local_region"}`` — both halves
      of the goal-pinned coverage. Records[] alone is the source of
      truth here; the derived ``sidecar.placement_role_coverage``
      field is cross-checked for agreement.

  G10 ``text_policy_diversity``
    - the set of ``sidecar.requests[*].text_policy`` values MUST
      carry at least ``EXPECTED_MIN_DISTINCT_TEXT_POLICIES`` (today:
      2) distinct entries. A sidecar in which every per-request
      text_policy collapsed to the same value — typically all
      ``no_text`` — is refused. The committed mock bundle path
      must exercise mixed per-request text_policy end-to-end, not
      only the adapter-only smoke. Records[] alone is the source
      of truth; the derived ``sidecar.text_policy_coverage`` array
      AND ``sidecar.covers_multiple_text_policies`` boolean are
      cross-checked against the raw requests[] values for
      agreement, so a tampered record that hand-edits the derived
      fields without updating the per-request values is refused.
    - when ``bundle_path`` points at a local bundle that contains a
      regular ``d_one_spec.json``, the sidecar request id ->
      text_policy mapping MUST byte-match that spec. This keeps the
      standalone evidence validator from accepting a record whose
      derived coverage is internally consistent but drifted away from
      the committed bundle's source of truth.

  G7 ``string_safety_scan``
    - every free-form string scalar (path / note / status / report
      / bundle / request id / manifest_local_path / custom_descriptor)
      is scanned for forbidden shapes:
        * URL/URI schemes (http/https/file/data/ftp/etc, including
          tel:/sms:/mailto:/magnet: + bare ``data:``);
        * traversal segments (`..`);
        * credential / token / API-key shapes (JWT, AWS access key,
          PEM marker, long-hex blob, bearer token, ``password:`` /
          ``api_key:`` / ``token:`` / ``secret:`` / ``access_key:`` /
          ``client_secret:`` / ``private_key:`` literals, OpenAI
          ``sk-`` prefix, GitHub ``ghp_`` prefix);
        * public-upload / public-sharing / public-hosting wording
          (``upload to public`` / ``public upload`` / ``share
          publicly`` / ``public hosting`` / ``publish to web`` /
          ``public URL`` / ``public link``);
        * confidential / customer / raw-source markers
          (``confidential`` / ``customer_id`` / ``account_id`` /
          ``<source>`` / ``raw source`` / ``source document:`` /
          ``begin source`` / ``end source`` / ``from the source``).
      The 64-character sha256 fields are NOT in this record so the
      long-hex check applies without the live-run validator's
      sha256-field exclusion.

  G8 ``real_d_one_claim_refusal``
    - the validator walks the full evidence dict and refuses any
      string scalar OR boolean True that asserts a real / live /
      MCP / public-network / model-API / image-search / Qoder
      success. A claim is positive iff a forbidden noun is in
      scope (in the value OR contributed by the enclosing dict key)
      AND a forbidden success verb (``verified`` / ``passed`` /
      ``succeeded`` / ``called`` / ``reached`` / ``fetched`` /
      ``received`` / ``online`` / ``live`` / ``enabled``) appears
      at a word boundary AND is NOT preceded by a negation token
      in a local 15-char window. The canonical UNVERIFIED status
      sentence pairs ``real D-One`` with ``called`` but the verb is
      preceded by ``is NOT`` inside the local window, so it does
      NOT trip the gate. A tampered string like
      ``"real D-One verified online: production run succeeded"``
      does trip — every verb is individually un-negated.

  G9 ``require_files`` (only when ``--require-files`` is passed)
    - evidence / PPTX / inventory / sidecar paths MUST be regular
      non-symlink files; URI-shaped paths refused at the string
      layer; traversal paths refused; symlinks refused at the leaf
      AND at every lexical-absolute ancestor (the three macOS
      standard top-level aliases ``/tmp -> private/tmp``,
      ``/var -> private/var``, ``/etc -> private/etc`` are
      exempted so a normal macOS per-user tempdir under
      ``/var/folders/.../T/...`` is accepted; any other symlinked
      ancestor is refused); the evidence path MUST NOT live under
      ``REPO_ROOT``; the 4 paths MUST share a common ancestor
      strictly under the system tempdir so a tampered record
      cannot smuggle a real-bundle PPTX past the in-tempdir
      contract.

Exit codes:
  0  every gate passed.
  1  one or more gates failed.
  2  invocation / file / parse error.

CLI:
  python3 scripts/validate_mock_image_bundle_trial_evidence.py \\
      --evidence <path/to/mock_image_bundle_trial_evidence.json>
  python3 scripts/validate_mock_image_bundle_trial_evidence.py \\
      --evidence <path> --require-files
  python3 scripts/validate_mock_image_bundle_trial_evidence.py --self-test

Stdlib-only. NETWORK-FREE. NO real D-One. NO MCP. NO Qoder. NO model
API. NO image search. NO telemetry. The validator is also wired into
``scripts/core_editable_ppt_acceptance.py`` so the aggregate
self-test exercises its ``--self-test`` matrix alongside the existing
delegated smokes.
"""
from __future__ import annotations

import sys

# Refuse to write `.pyc` files for any module imported by this script.
# The validator's contract is read-only AND tempdir-only; without this
# gate the first-party import below would silently leak
# ``scripts/__pycache__/validate_artifacts.cpython-*.pyc`` on a clean
# checkout. The env-var prefix `PYTHONDONTWRITEBYTECODE=1` achieves the
# same thing for callers that remember it; the in-script flip closes
# the hole unconditionally. Must come BEFORE any first-party import.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "schemas"
EXAMPLES_DIR = REPO_ROOT / "examples"

sys.path.insert(0, str(SCRIPTS_DIR))

from validate_artifacts import _validate  # noqa: E402

EVIDENCE_SCHEMA = (
    SCHEMAS_DIR / "mock_image_bundle_trial_evidence.schema.json"
)
COMMITTED_TEMPLATE = (
    EXAMPLES_DIR / "mock_image_bundle_trial_evidence_template.json"
)

# Locked constants the validator enforces in addition to the schema's
# enum locks. Mirrors the emitter's pinned values.
EXPECTED_SCHEMA_VERSION = "1"
EXPECTED_EVIDENCE_ID = "mock_image_bundle_trial_evidence"
EXPECTED_SLIDE_COUNT = 2
EXPECTED_MEDIA_PARTS_MIN = 2
EXPECTED_SIDECAR_SCHEMA_VERSION = 4
EXPECTED_EVIDENCE_BASIS = (
    "OOXML structure only; not proof of full PowerPoint editability"
)
EXPECTED_PLACEMENT_ROLES: frozenset[str] = frozenset(
    {"hero_page", "local_region"}
)
# Goal-pinned minimum number of distinct text_policy values that must
# appear across the sidecar's requests[]. The committed bundle path
# must exercise mixed per-request text_policy end-to-end (not only the
# adapter-only smoke); a sidecar in which every request collapsed to
# the same value — typically all 'no_text' — is refused.
EXPECTED_MIN_DISTINCT_TEXT_POLICIES = 2
_REQUIRED_REQUEST_FIELDS: tuple[str, ...] = (
    "id",
    "placement_role",
    "text_policy",
    "subject_domain",
    "manifest_local_path",
)

# ---------------------------------------------------------------------------
# String-safety scan patterns. Stdlib regexes only; every pattern is
# compiled once at module load.
# ---------------------------------------------------------------------------

# Closed list of URI schemes the validator refuses. A scheme is matched
# at a word boundary so legitimate identifiers like
# ``"d_one_local"`` are not falsely flagged (no ``:`` follows the
# alphanumeric prefix). The match position is followed by ``:`` so a
# pattern like ``"http:"`` / ``"file:"`` trips while a bare path
# component like ``"http_or_https"`` does not.
_FORBIDDEN_URI_SCHEMES: tuple[str, ...] = (
    "http", "https", "ftp", "ftps", "file", "data",
    "javascript", "vbscript", "mailto", "tel", "sms",
    "gopher", "magnet", "ws", "wss",
)
_URI_SCHEME_RE = re.compile(
    r"(?i)\b(?:" + "|".join(_FORBIDDEN_URI_SCHEMES) + r"):",
)

# Traversal segments. A literal ``..`` substring is refused — the
# validator does not need to allow ``...`` ellipsis since the evidence
# never carries prose with three-dot sentences (the notes block uses
# regular sentence-terminal punctuation). Lexical-only check; the
# filesystem-side gate runs in --require-files.
_TRAVERSAL_RE = re.compile(r"\.\.")

# Credential / token / API-key shapes. The long-hex pattern catches
# 32+ contiguous hex chars (sha256, AWS secret keys, etc.); this
# record carries no legitimate sha256 fields so the pattern has no
# false-positive surface here (unlike the live-run evidence
# validator, which excludes sha256 fields explicitly).
_CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("JWT", re.compile(
        r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\."
        r"[A-Za-z0-9_\-]{8,}"
    )),
    ("AWS access key", re.compile(r"\bAKIA[A-Z0-9]{12,20}\b")),
    ("PEM marker", re.compile(r"-----BEGIN\s")),
    ("long hex blob", re.compile(r"\b[a-fA-F0-9]{32,}\b")),
    ("bearer token", re.compile(
        r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"
    )),
    # Stripe / OpenAI-style sk- prefix and GitHub ghp_ prefix.
    ("sk- prefix", re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")),
    ("ghp_ prefix", re.compile(r"\bghp_[A-Za-z0-9]{16,}\b")),
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

# Public-upload / public-sharing / public-hosting deny patterns.
# Evidence records must never direct an artifact to a public
# destination — that would breach the privacy rule. The negated-
# adjacency exception used by ``validate_d_one_live_run_evidence`` is
# NOT honored here: the mock-image evidence record never legitimately
# carries any public-distribution wording (the canonical emitter
# writes no such tokens), so a strict refusal is the cleaner gate.
_PUBLIC_UPLOAD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("upload to public", re.compile(
        r"\bupload(?:ing|s|ed)?\s+to\s+(?:a\s+|the\s+)?public\b",
        re.IGNORECASE,
    )),
    ("public upload", re.compile(
        r"\bpublic\s+upload(?:ing|s|ed)?\b", re.IGNORECASE
    )),
    ("share publicly", re.compile(
        r"\bshar(?:e|es|ed|ing)\s+publicly\b", re.IGNORECASE
    )),
    ("share to public", re.compile(
        r"\bshar(?:e|es|ed|ing)\s+to\s+(?:a\s+|the\s+)?public\b",
        re.IGNORECASE,
    )),
    ("public hosting", re.compile(
        r"\bpublic(?:ly)?\s+host(?:ing|ed|s)?\b", re.IGNORECASE
    )),
    ("publish to web", re.compile(
        r"\bpublish(?:ing|es|ed)?\s+to\s+(?:the\s+)?web\b",
        re.IGNORECASE,
    )),
    ("public URL", re.compile(r"\bpublic\s+url\b", re.IGNORECASE)),
    ("public link", re.compile(r"\bpublic\s+link\b", re.IGNORECASE)),
)

# Confidential / customer / raw-source markers. Mirrors the live-run
# validator's literal set; bounded substring matches only (lower-cased
# on both sides). The literals are deliberately specific so legitimate
# words like ``customer_motif_neutral`` (hypothetical request id) would
# only trip on the explicit substring ``customer_id`` / ``customer id:``
# — not on the bare token ``customer``.
_CONFIDENTIAL_LITERALS: tuple[str, ...] = (
    "confidential",
    "customer_id",
    "customer id:",
    "account_id",
    "account id:",
    "internal use only",
    "do not distribute",
    "do_not_distribute",
)
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

# ---------------------------------------------------------------------------
# Real-D-One claim refusal tables. Mirrors the design of the emitter's
# ``_evidence_refuses_real_d_one_claims`` helper but kept local so a
# future emitter rename / shape change does not silently break the
# validator. The two helpers must apply the SAME contract: refuse any
# positive success claim about real D-One / MCP / public network /
# model API / image search / Qoder.
# ---------------------------------------------------------------------------

_FORBIDDEN_CLAIM_VERBS: tuple[str, ...] = (
    "verified", "passed", "succeeded", "succeeds", "succeed",
    "online", "live", "enabled",
    "called", "reached", "fetched", "received",
)
_FORBIDDEN_CLAIM_NOUNS: tuple[str, ...] = (
    "real d-one", "real_d_one", "real-d-one",
    "live d-one", "live_d_one", "live-d-one",
    "production d-one", "production_d_one", "production-d-one",
    "d_one", "d-one",
    "mcp", "model context protocol",
    "public network", "public_network", "public-network",
    "model api", "model_api", "model-api",
    "image search", "image_search", "image-search",
    "qoder",
)
_NEGATION_TOKENS: tuple[str, ...] = (
    " not ", " no ", " never ", " without ", " none ",
    "n't",
    "is not", "are not", "was not", "were not",
    "do not", "does not", "did not",
    "will not", "would not", "cannot",
)
_NEGATION_WINDOW_CHARS = 15


def _is_word_boundary(text_low: str, start: int, end: int) -> bool:
    """True iff ``text_low[start:end]`` is bracketed by non-alphanumeric
    chars (or string boundaries) on both sides — i.e. the substring is a
    standalone word, not buried inside a longer token. Without this gate
    the verb ``verified`` inside the negation ``unverified`` would
    falsely register as a positive claim."""
    if start > 0 and text_low[start - 1].isalnum():
        return False
    if end < len(text_low) and text_low[end].isalnum():
        return False
    return True


def _verb_is_negated(text_low: str, verb_start: int) -> bool:
    """True iff the ``_NEGATION_WINDOW_CHARS``-char window immediately
    BEFORE ``verb_start`` contains a negation token. Identifier-style
    negations (``is_not_called`` / ``was-not-reached``) are normalised
    to spaces so the same space-padded tokens match against keys exactly
    as they do against prose strings."""
    window_start = max(0, verb_start - _NEGATION_WINDOW_CHARS)
    raw = text_low[window_start:verb_start]
    normalized = raw.replace("_", " ").replace("-", " ")
    window = " " + normalized + " "
    return any(token in window for token in _NEGATION_TOKENS)


def _key_carries_positive_verb(key_low: str) -> bool:
    """True iff the lower-cased ``key_low`` contains a forbidden verb at
    a word boundary AND that verb is not negated by an in-key negation
    token."""
    for verb in _FORBIDDEN_CLAIM_VERBS:
        idx = 0
        while True:
            pos = key_low.find(verb, idx)
            if pos < 0:
                break
            end = pos + len(verb)
            if (
                _is_word_boundary(key_low, pos, end)
                and not _verb_is_negated(key_low, pos)
            ):
                return True
            idx = pos + 1
    return False


def _string_asserts_d_one_success(
    value: str, *, key_provides_noun: bool = False,
) -> bool:
    """True when ``value`` makes a POSITIVE success claim about a
    real / live / MCP / network / model / image-search / Qoder
    integration. See module docstring G8 for the full contract."""
    low = value.lower()
    has_noun = key_provides_noun or any(
        noun in low for noun in _FORBIDDEN_CLAIM_NOUNS
    )
    if not has_noun:
        return False
    for verb in _FORBIDDEN_CLAIM_VERBS:
        idx = 0
        while True:
            pos = low.find(verb, idx)
            if pos < 0:
                break
            end = pos + len(verb)
            if (
                _is_word_boundary(low, pos, end)
                and not _verb_is_negated(low, pos)
            ):
                return True
            idx = pos + 1
    return False


def _walk_evidence_for_claims(
    evidence: dict | list,
) -> list[tuple[str, str]]:
    """Walk ``evidence`` recursively. Return ``(json_path, value)``
    pairs flagging any forbidden claim of real-D-One / MCP / public
    network / model API / image search / Qoder success.

    The walker mirrors the emitter's helper: noun-in-scope propagates
    through dict descendants; boolean True at a key that contributes a
    positive claim (direct noun OR un-negated verb under a noun-bearing
    ancestor) trips shape B; string scalars trip shape A whenever they
    contain a forbidden noun AND an un-negated forbidden verb at a
    word boundary."""
    findings: list[tuple[str, str]] = []

    def _walk(
        node, path: str, *, key_provides_noun: bool = False,
    ) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                key_low = str(k).lower()
                sub_path = f"{path}.{k}" if path else str(k)
                child_key_has_noun = any(
                    noun in key_low for noun in _FORBIDDEN_CLAIM_NOUNS
                )
                child_key_has_verb = _key_carries_positive_verb(key_low)
                effective_provides_noun = (
                    key_provides_noun or child_key_has_noun
                )
                if (
                    v is True
                    and effective_provides_noun
                    and (child_key_has_noun or child_key_has_verb)
                ):
                    findings.append((sub_path, "True"))
                _walk(
                    v, sub_path,
                    key_provides_noun=effective_provides_noun,
                )
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _walk(
                    item, f"{path}[{i}]",
                    key_provides_noun=key_provides_noun,
                )
        elif isinstance(node, str):
            if _string_asserts_d_one_success(
                node, key_provides_noun=key_provides_noun,
            ):
                findings.append((path, node))

    _walk(evidence, "")
    return findings


# ---------------------------------------------------------------------------
# String-safety scan. Walks every free-form string scalar in the
# evidence (paths, notes, status, request fields, etc.) and returns a
# list of (path, violation_msg) pairs.
# ---------------------------------------------------------------------------


def _collect_string_scalars(node, path: str = "") -> list[tuple[str, str]]:
    """Return ``[(json_path, string_value), ...]`` for every string
    scalar reachable from ``node``. The walker recurses through dicts
    and lists; non-string scalars (booleans, integers, None) are
    skipped."""
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            sub = f"{path}.{k}" if path else str(k)
            out.extend(_collect_string_scalars(v, sub))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            out.extend(_collect_string_scalars(item, f"{path}[{i}]"))
    elif isinstance(node, str):
        out.append((path, node))
    return out


def _scan_unsafe_string(value: str) -> list[str]:
    """Return a list of violation tags for ``value``. Empty list means
    every forbidden-shape gate passed."""
    hits: list[str] = []
    low = value.lower()

    if _URI_SCHEME_RE.search(value):
        hits.append("URI/URL scheme")
    if _TRAVERSAL_RE.search(value):
        hits.append("path-traversal '..'")
    for label, pattern in _CREDENTIAL_PATTERNS:
        if pattern.search(value):
            hits.append(f"credential shape ({label})")
    for literal in _CREDENTIAL_LITERALS:
        if literal in low:
            hits.append(f"credential literal {literal!r}")
    for label, pattern in _PUBLIC_UPLOAD_PATTERNS:
        if pattern.search(value):
            hits.append(f"public-distribution wording ({label})")
    for literal in _CONFIDENTIAL_LITERALS:
        if literal in low:
            hits.append(f"confidential / customer marker {literal!r}")
    for literal in _SOURCE_MARKER_LITERALS:
        if literal in low:
            hits.append(f"raw-source marker {literal!r}")
    return hits


# ---------------------------------------------------------------------------
# Semantic gate helpers. Each returns a list of error strings; empty list
# means the gate passed.
# ---------------------------------------------------------------------------


def _check_schema_version(evidence: dict) -> list[str]:
    """G2 belt-and-braces (the schema's enum lock already enforces
    this — surface a clear diagnostic so the failure does not require
    grepping the schema-error list for the enum miss)."""
    v = evidence.get("schema_version")
    if v != EXPECTED_SCHEMA_VERSION:
        return [
            f"schema_version: expected {EXPECTED_SCHEMA_VERSION!r}, "
            f"got {v!r}"
        ]
    return []


def _check_evidence_id(evidence: dict) -> list[str]:
    """G2 belt-and-braces for evidence_id (same shape as above)."""
    v = evidence.get("evidence_id")
    if v != EXPECTED_EVIDENCE_ID:
        return [
            f"evidence_id: expected {EXPECTED_EVIDENCE_ID!r}, got "
            f"{v!r}"
        ]
    return []


def _check_real_d_one_status_phrasing(evidence: dict) -> list[str]:
    """G3 — the status sentence MUST contain ``UNVERIFIED`` AND at
    least one negation token applied to a forbidden service. The
    sentence is the canonical UNVERIFIED stanza in the emitter; this
    gate refuses a tampered string that strips either half."""
    errors: list[str] = []
    status = evidence.get("real_d_one_status")
    if not isinstance(status, str):
        # Schema would already catch this; defensive.
        return ["real_d_one_status: expected non-empty string"]
    low = status.lower()
    if "unverified" not in low:
        errors.append(
            "real_d_one_status: missing required 'UNVERIFIED' "
            "substring (the canonical sentence must keep its "
            "self-describing UNVERIFIED marker)"
        )
    # Look for a negated form of a forbidden noun nearby. The simplest
    # gate is: at least one negation token (NOT / no / never / without
    # / n't) appears anywhere in the status, AND the lowered string
    # contains at least one of the forbidden noun substrings. Without
    # the noun check a sentence like ``UNVERIFIED but no errors`` would
    # spuriously pass.
    has_negation = (
        " not " in (" " + low + " ")
        or " no " in (" " + low + " ")
        or " never " in (" " + low + " ")
        or " without " in (" " + low + " ")
        or "n't" in low
    )
    has_noun = any(
        noun in low for noun in _FORBIDDEN_CLAIM_NOUNS
    )
    if not (has_negation and has_noun):
        errors.append(
            "real_d_one_status: missing required negated/no-call "
            "wording for a forbidden service (the sentence must "
            "explicitly state that real D-One / MCP / public network "
            "/ model API / image search / Qoder was NOT called)"
        )
    return errors


def _summary_ok_sub_conditions(evidence: dict) -> list[str]:
    """Return the list of sub-conditions that did NOT hold. Empty list
    means every sub-condition holds; a ``summary.ok == true`` record
    is only consistent when this list is empty."""
    fails: list[str] = []
    pptx = evidence.get("pptx", {})
    if not (
        isinstance(pptx, dict)
        and pptx.get("exists") is True
        and isinstance(pptx.get("size_bytes"), int)
        and pptx["size_bytes"] > 0
    ):
        fails.append(
            f"pptx: exists={pptx.get('exists')!r}, "
            f"size_bytes={pptx.get('size_bytes')!r} "
            f"(require exists=True and size_bytes>0)"
        )

    validators = evidence.get("validators", {})
    if isinstance(validators, dict):
        for key in (
            "validate_pptx_contract",
            "inspect_pptx_inventory",
            "validate_mock_d_one_adapter_plan",
        ):
            row = validators.get(key, {})
            if not (
                isinstance(row, dict)
                and row.get("ok") is True
                and row.get("rc") == 0
            ):
                fails.append(
                    f"validators.{key}: rc={row.get('rc')!r}, "
                    f"ok={row.get('ok')!r} (require rc==0 and ok==True)"
                )
        sv = validators.get("validate_mock_d_one_adapter_plan", {})
        if isinstance(sv, dict):
            if sv.get("vocabulary_gate_used") is not True:
                fails.append(
                    "validators.validate_mock_d_one_adapter_plan."
                    "vocabulary_gate_used must be True"
                )
            if sv.get("require_both_placement_roles_used") is not True:
                fails.append(
                    "validators.validate_mock_d_one_adapter_plan."
                    "require_both_placement_roles_used must be True"
                )

    inv = evidence.get("inventory", {})
    if isinstance(inv, dict):
        if inv.get("exists") is not True or inv.get(
            "parses_as_json"
        ) is not True or inv.get("ok") is not True:
            fails.append(
                f"inventory: exists={inv.get('exists')!r}, "
                f"parses_as_json={inv.get('parses_as_json')!r}, "
                f"ok={inv.get('ok')!r} (require all True)"
            )
        if inv.get("findings_empty") is not True:
            fails.append(
                f"inventory.findings_empty must be True (findings="
                f"{inv.get('findings')!r})"
            )
        if inv.get("slide_count") != EXPECTED_SLIDE_COUNT or inv.get(
            "slide_count_matches_plan"
        ) is not True:
            fails.append(
                f"inventory.slide_count must equal "
                f"{EXPECTED_SLIDE_COUNT} (got "
                f"{inv.get('slide_count')!r}, matches_plan="
                f"{inv.get('slide_count_matches_plan')!r})"
            )
        mp = inv.get("media_parts_count")
        if not (
            isinstance(mp, int) and mp >= EXPECTED_MEDIA_PARTS_MIN
            and inv.get("media_parts_count_min_met") is True
        ):
            fails.append(
                f"inventory.media_parts_count must be >= "
                f"{EXPECTED_MEDIA_PARTS_MIN} (got {mp!r}, min_met="
                f"{inv.get('media_parts_count_min_met')!r})"
            )
        if (
            inv.get("evidence_basis") != EXPECTED_EVIDENCE_BASIS
            or inv.get("evidence_basis_matches") is not True
        ):
            fails.append(
                f"inventory.evidence_basis must equal the canonical "
                f"sentence (got {inv.get('evidence_basis')!r}, "
                f"matches={inv.get('evidence_basis_matches')!r})"
            )
        if inv.get("no_external_relationships") is not True:
            fails.append(
                "inventory.no_external_relationships must be True"
            )

    sc = evidence.get("sidecar", {})
    if isinstance(sc, dict):
        if sc.get("exists") is not True or sc.get(
            "parses_as_json"
        ) is not True:
            fails.append(
                f"sidecar: exists={sc.get('exists')!r}, "
                f"parses_as_json={sc.get('parses_as_json')!r} "
                f"(require both True)"
            )
        if (
            sc.get("schema_version") != EXPECTED_SIDECAR_SCHEMA_VERSION
            or sc.get("schema_version_locked") is not True
        ):
            fails.append(
                f"sidecar.schema_version must equal "
                f"{EXPECTED_SIDECAR_SCHEMA_VERSION} (got "
                f"{sc.get('schema_version')!r}, locked="
                f"{sc.get('schema_version_locked')!r})"
            )
        requests = sc.get("requests")
        rc = sc.get("request_count")
        if (
            isinstance(requests, list)
            and (rc != len(requests)
                 or sc.get("request_count_matches_requests") is not True)
        ):
            fails.append(
                f"sidecar.request_count ({rc!r}) must equal "
                f"len(requests) ({len(requests)}) "
                f"(matches_requests="
                f"{sc.get('request_count_matches_requests')!r})"
            )
        if (
            sc.get("all_requests_well_formed") is not True
            or sc.get("malformed_request_indices") != []
        ):
            fails.append(
                f"sidecar.all_requests_well_formed must be True with "
                f"empty malformed_request_indices (got well_formed="
                f"{sc.get('all_requests_well_formed')!r}, malformed="
                f"{sc.get('malformed_request_indices')!r})"
            )
        coverage = sc.get("placement_role_coverage")
        if (
            not isinstance(coverage, list)
            or sorted(set(coverage)) != sorted(EXPECTED_PLACEMENT_ROLES)
            or sc.get("covers_both_placement_roles") is not True
        ):
            fails.append(
                f"sidecar.placement_role_coverage must equal "
                f"sorted({sorted(EXPECTED_PLACEMENT_ROLES)!r}) (got "
                f"{coverage!r}, covers_both="
                f"{sc.get('covers_both_placement_roles')!r})"
            )
        tp_coverage = sc.get("text_policy_coverage")
        if (
            not isinstance(tp_coverage, list)
            or len(set(tp_coverage)) < EXPECTED_MIN_DISTINCT_TEXT_POLICIES
            or sc.get("covers_multiple_text_policies") is not True
        ):
            fails.append(
                f"sidecar.text_policy_coverage must carry at least "
                f"{EXPECTED_MIN_DISTINCT_TEXT_POLICIES} distinct values "
                f"AND covers_multiple_text_policies must be True "
                f"(got coverage={tp_coverage!r}, covers_multiple="
                f"{sc.get('covers_multiple_text_policies')!r})"
            )

    return fails


def _check_summary_ok_consistency(evidence: dict) -> list[str]:
    """G4 — when ``summary.ok == true`` every sub-condition above
    must hold. When ``summary.ok == false`` the validator does NOT
    require any sub-condition (a legitimately failed run records what
    went wrong); however a record with ``summary.ok == true`` AND any
    failing sub-condition is internally inconsistent and refused."""
    summary = evidence.get("summary", {})
    if not isinstance(summary, dict):
        return ["summary: not an object"]
    ok = summary.get("ok")
    fails = _summary_ok_sub_conditions(evidence)
    if ok is True and fails:
        return [
            "summary.ok=True is inconsistent with the gates that did "
            "NOT hold: " + "; ".join(fails)
        ]
    return []


def _check_per_request_well_formed(evidence: dict) -> list[str]:
    """G5 — every request record carries every goal-required field as
    a non-empty string; optional custom_descriptor (if present) is also
    a non-empty string."""
    errors: list[str] = []
    sc = evidence.get("sidecar", {})
    if not isinstance(sc, dict):
        return errors
    requests = sc.get("requests")
    if not isinstance(requests, list):
        return errors
    for i, req in enumerate(requests):
        if not isinstance(req, dict):
            errors.append(
                f"sidecar.requests[{i}]: expected an object, got "
                f"{type(req).__name__}"
            )
            continue
        for field in _REQUIRED_REQUEST_FIELDS:
            v = req.get(field)
            if not (isinstance(v, str) and v):
                errors.append(
                    f"sidecar.requests[{i}].{field}: expected "
                    f"non-empty string, got {v!r}"
                )
        if "custom_descriptor" in req:
            v = req["custom_descriptor"]
            if not (isinstance(v, str) and v):
                errors.append(
                    f"sidecar.requests[{i}].custom_descriptor: "
                    f"present but not a non-empty string ({v!r})"
                )
    return errors


def _check_placement_role_coverage(evidence: dict) -> list[str]:
    """G6 — the set of placement_role values across requests[] equals
    exactly {hero_page, local_region}. Cross-checked against the
    derived coverage field for agreement."""
    errors: list[str] = []
    sc = evidence.get("sidecar", {})
    requests = sc.get("requests") if isinstance(sc, dict) else None
    if not isinstance(requests, list):
        return errors
    roles: set[str] = set()
    for req in requests:
        if isinstance(req, dict):
            r = req.get("placement_role")
            if isinstance(r, str):
                roles.add(r)
    if roles != EXPECTED_PLACEMENT_ROLES:
        errors.append(
            f"sidecar.requests[*].placement_role coverage must equal "
            f"{sorted(EXPECTED_PLACEMENT_ROLES)!r} (got "
            f"{sorted(roles)!r})"
        )
    coverage = sc.get("placement_role_coverage")
    if isinstance(coverage, list):
        if sorted(set(coverage)) != sorted(roles):
            errors.append(
                f"sidecar.placement_role_coverage ({coverage!r}) "
                f"disagrees with requests[*].placement_role "
                f"({sorted(roles)!r})"
            )
    return errors


def _check_text_policy_diversity(evidence: dict) -> list[str]:
    """G10 — the set of ``sidecar.requests[*].text_policy`` values MUST
    carry at least ``EXPECTED_MIN_DISTINCT_TEXT_POLICIES`` distinct
    entries. This gate refuses a sidecar where every per-request
    text_policy collapsed to the same value (typically all ``no_text``)
    — the goal pins per-request text_policy judgement to flow end-to-
    end through the committed mock bundle path, not only through the
    adapter-only smoke. The derived ``sidecar.text_policy_coverage``
    and ``sidecar.covers_multiple_text_policies`` fields are cross-
    checked against the raw requests[] values for agreement so a
    tampered sidecar that hand-edits the derived fields without
    updating the per-request values is refused too."""
    errors: list[str] = []
    sc = evidence.get("sidecar", {})
    requests = sc.get("requests") if isinstance(sc, dict) else None
    if not isinstance(requests, list):
        return errors
    raw_values: set[str] = set()
    for req in requests:
        if isinstance(req, dict):
            v = req.get("text_policy")
            if isinstance(v, str):
                raw_values.add(v)
    if len(raw_values) < EXPECTED_MIN_DISTINCT_TEXT_POLICIES:
        errors.append(
            f"sidecar.requests[*].text_policy must carry at least "
            f"{EXPECTED_MIN_DISTINCT_TEXT_POLICIES} distinct values "
            f"(got {sorted(raw_values)!r}); per-request text_policy "
            f"collapsed — the committed mock bundle path must exercise "
            f"mixed text_policy end-to-end"
        )
    coverage = sc.get("text_policy_coverage")
    if isinstance(coverage, list):
        if sorted(set(coverage)) != sorted(raw_values):
            errors.append(
                f"sidecar.text_policy_coverage ({coverage!r}) "
                f"disagrees with requests[*].text_policy "
                f"({sorted(raw_values)!r})"
            )
    covers_multi = sc.get("covers_multiple_text_policies")
    if isinstance(covers_multi, bool):
        expected_covers = (
            len(raw_values) >= EXPECTED_MIN_DISTINCT_TEXT_POLICIES
        )
        if covers_multi != expected_covers:
            errors.append(
                f"sidecar.covers_multiple_text_policies={covers_multi!r} "
                f"disagrees with the derived value "
                f"(len(distinct text_policy)="
                f"{len(raw_values)} >= "
                f"{EXPECTED_MIN_DISTINCT_TEXT_POLICIES} -> "
                f"{expected_covers!r})"
            )
    return errors


def _check_bundle_text_policy_parity(evidence: dict) -> list[str]:
    """G10 parity extension — if ``bundle_path`` names a local bundle
    with a regular ``d_one_spec.json``, compare the sidecar's per-id
    text_policy mapping to the spec's per-id mapping.

    The committed mock-image evidence emitter records the real
    ``examples/synthetic_mock_image_trial`` path, so this gate catches
    evidence records that remain internally consistent but no longer
    describe the committed bundle bytes. Synthetic templates may use a
    non-existent placeholder bundle path; those records still rely on
    schema + semantic consistency and are not forced through this
    filesystem parity check."""
    errors: list[str] = []
    bundle_raw = evidence.get("bundle_path")
    if not isinstance(bundle_raw, str) or not bundle_raw:
        return errors
    # URI/traversal-shaped bundle paths are handled by the recursive
    # string-safety scan. Avoid turning that into noisy filesystem
    # errors here.
    if _has_uri_scheme(bundle_raw) or ".." in Path(bundle_raw).parts:
        return errors
    bundle = Path(bundle_raw)
    if not bundle.exists():
        return errors
    spec_path = bundle / "d_one_spec.json"
    if spec_path.is_symlink() or not spec_path.is_file():
        errors.append(
            f"bundle_path points at existing local bundle {bundle}, "
            "but d_one_spec.json is missing, symlinked, or not a "
            "regular file; cannot prove evidence text_policy parity"
        )
        return errors
    try:
        spec_doc = json.loads(spec_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(
            f"cannot parse bundle d_one_spec.json at {spec_path}: "
            f"{type(exc).__name__}: {exc}"
        )
        return errors
    spec_requests = (
        spec_doc.get("requests") if isinstance(spec_doc, dict) else None
    )
    if not isinstance(spec_requests, list):
        errors.append(
            f"bundle d_one_spec.json at {spec_path} does not carry a "
            "requests[] array"
        )
        return errors

    def _mapping(rows: object) -> dict[str, str]:
        out: dict[str, str] = {}
        if not isinstance(rows, list):
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            rid = row.get("id")
            tp = row.get("text_policy")
            if isinstance(rid, str) and rid and isinstance(tp, str) and tp:
                out[rid] = tp
        return out

    spec_by_id = _mapping(spec_requests)
    sc = evidence.get("sidecar", {})
    sidecar_by_id = _mapping(
        sc.get("requests") if isinstance(sc, dict) else None
    )
    if not spec_by_id:
        errors.append(
            f"bundle d_one_spec.json at {spec_path} has no request id "
            "-> text_policy mapping"
        )
        return errors
    if sidecar_by_id != spec_by_id:
        errors.append(
            "sidecar.requests[*].text_policy disagrees with "
            f"bundle d_one_spec.json at {spec_path}: "
            f"spec={spec_by_id!r}, evidence={sidecar_by_id!r}"
        )
    return errors


def _check_string_safety(evidence: dict) -> list[str]:
    """G7 — string-safety scan over every string scalar."""
    errors: list[str] = []
    for jpath, value in _collect_string_scalars(evidence):
        # Skip the enum-locked schema_version / evidence_id values
        # (they only carry the literal "1" / "mock_image_bundle_trial_
        # evidence" tokens, which trivially pass the scan but listing
        # them in the diagnostic noise is wasteful).
        if jpath in {"schema_version", "evidence_id"}:
            continue
        hits = _scan_unsafe_string(value)
        for hit in hits:
            errors.append(
                f"{jpath}: refused — {hit} in value {value!r}"
            )
    return errors


def _check_real_d_one_claim_refusal(evidence: dict) -> list[str]:
    """G8 — walks the full evidence dict and refuses any forbidden
    real-D-One / MCP / network / model / image-search / Qoder
    success claim."""
    findings = _walk_evidence_for_claims(evidence)
    return [
        f"{p}: refused real-D-One / MCP / network / model / image-"
        f"search / Qoder success claim ({v!r})"
        for p, v in findings
    ]


# ---------------------------------------------------------------------------
# --require-files filesystem gate (G9). Only invoked when the caller
# passes ``--require-files``. The validator does not require the
# committed template to satisfy this gate (the template's path strings
# are synthetic).
# ---------------------------------------------------------------------------


def _has_uri_scheme(path_str: str) -> bool:
    """True iff ``path_str`` starts with a forbidden URI scheme. The
    full string-safety scan also covers URI schemes anywhere in the
    string, but for path arguments the scheme is anchored at the start
    to match how ``open()`` would interpret it."""
    return bool(re.match(
        r"(?i)^(?:" + "|".join(_FORBIDDEN_URI_SCHEMES) + r"):",
        path_str,
    ))


# Closed allow-list of macOS standard top-level symlinks into
# ``/private/``. macOS ships three: ``/tmp -> private/tmp``,
# ``/var -> private/var``, ``/etc -> private/etc``. Refusing any of
# these would break every normal macOS tempdir — the per-user
# ``/var/folders/.../T`` tempdir's ancestor walk traverses ``/var``
# on its way to ``/``, the system-wide ``/tmp`` tempdir's walk
# traverses ``/tmp``, and the unusual case of a tempdir under
# ``/etc`` traverses ``/etc``. The allow-list is closed (not
# parametric on the basename) so a future attacker-planted
# ``/foo -> private/foo`` style symlink at the filesystem root is
# still refused even though it follows the macOS naming convention.
_MACOS_PRIVATE_ALIASES: frozenset[str] = frozenset({
    "/tmp", "/var", "/etc",
})


def _is_macos_private_alias(ancestor: Path, target: str) -> bool:
    """True iff ``ancestor`` is one of the three macOS standard
    top-level aliases (``/tmp``, ``/var``, ``/etc``) AND its symlink
    target is ``private/<basename>`` or ``/private/<basename>``."""
    s = str(ancestor)
    if s not in _MACOS_PRIVATE_ALIASES:
        return False
    name = ancestor.name
    return target in (f"private/{name}", f"/private/{name}")


def _refuse_symlinked_ancestor(
    target: Path, label: str,
) -> tuple[bool, str]:
    """Walk every lexical-absolute parent of ``target`` and refuse if
    any is a symlink. Mirrors the runner's
    ``_refuse_symlinked_bundle_ancestor`` but extends the macOS
    private-alias exemption parametrically: any top-level alias
    ``/X -> private/X`` (or ``/private/X``) — ``/tmp``, ``/var``,
    ``/etc`` are the three standard cases shipped by macOS — is
    allowed. Without the ``/var`` half of the exemption every
    per-user macOS tempdir under ``/var/folders/.../T/...`` would
    be refused because the parent walk inevitably traverses
    ``/var`` (a system symlink to ``/private/var``). Any other
    symlink anywhere along the chain is refused. Returns
    ``(refused, message)``; ``refused`` is True iff a non-system
    symlink was found."""
    abs_lexical = Path(os.path.abspath(str(target)))
    for ancestor in abs_lexical.parents:
        if ancestor == ancestor.parent:
            break
        if not ancestor.is_symlink():
            continue
        try:
            tgt = str(ancestor.readlink())
        except OSError:
            tgt = "<unreadable>"
        if _is_macos_private_alias(ancestor, tgt):
            continue
        return True, (
            f"{label} ancestor {ancestor} is a symlink (-> {tgt}); "
            f"refused"
        )
    return False, ""


def _system_temp_dirs() -> list[Path]:
    """Return the set of allowed system temp roots (resolved).
    ``tempfile.gettempdir()`` is the primary; ``/tmp`` and
    ``/private/tmp`` are added so the macOS convention works regardless
    of which form the caller's TMPDIR took."""
    out: set[Path] = set()
    out.add(Path(os.path.abspath(tempfile.gettempdir())))
    for extra in ("/tmp", "/private/tmp"):
        if Path(extra).exists():
            out.add(Path(os.path.abspath(extra)))
    return sorted(out)


def _path_is_under(child: Path, parent: Path) -> bool:
    """Lexical descendant check. ``parent`` MUST already be absolute
    and lexically clean. Returns True iff ``child`` (lexically
    absolute) is parent itself OR sits strictly below it."""
    child_abs = Path(os.path.abspath(str(child)))
    try:
        child_abs.relative_to(parent)
    except ValueError:
        return False
    return True


def _common_ancestor(paths: list[Path]) -> Path | None:
    """Return the deepest common ancestor of ``paths`` (lexically
    absolute). Returns None if the list is empty."""
    if not paths:
        return None
    parts_lists = [
        Path(os.path.abspath(str(p))).parts for p in paths
    ]
    common: list[str] = []
    for tup in zip(*parts_lists):
        if len(set(tup)) == 1:
            common.append(tup[0])
        else:
            break
    if not common:
        return None
    return Path(*common)


def _require_files_check(
    evidence: dict, evidence_path: Path,
) -> list[str]:
    """G9 — see module docstring. Returns a list of error strings;
    empty list means every check passed."""
    errors: list[str] = []

    # Collect the four candidate paths. The evidence path is the file
    # being validated; the other three come from the record.
    pptx_path_str = evidence.get("pptx", {}).get("path") if isinstance(
        evidence.get("pptx"), dict
    ) else None
    inv_path_str = (
        evidence.get("inventory", {}).get("path") if isinstance(
            evidence.get("inventory"), dict
        ) else None
    )
    sc_path_str = evidence.get("sidecar", {}).get("path") if isinstance(
        evidence.get("sidecar"), dict
    ) else None

    candidates: list[tuple[str, str]] = [
        ("evidence", str(evidence_path)),
    ]
    for label, val in (
        ("pptx", pptx_path_str),
        ("inventory", inv_path_str),
        ("sidecar", sc_path_str),
    ):
        if not isinstance(val, str) or not val:
            errors.append(
                f"--require-files: {label}.path must be a non-empty "
                f"string (got {val!r})"
            )
            continue
        candidates.append((label, val))

    resolved_paths: list[Path] = []
    repo_root_abs = Path(os.path.abspath(str(REPO_ROOT)))
    system_temps = _system_temp_dirs()

    for label, raw in candidates:
        # 1. Refuse URI-shaped path strings at the string layer
        # (before any filesystem call).
        if _has_uri_scheme(raw):
            errors.append(
                f"--require-files: {label} path {raw!r} carries a "
                f"URI scheme; refused"
            )
            continue
        # 2. Refuse traversal segments lexically. A '..' anywhere in
        # the raw path is refused outright — the validator never
        # legitimately needs to walk above a tempdir.
        if ".." in Path(raw).parts:
            errors.append(
                f"--require-files: {label} path {raw!r} contains a "
                f"'..' segment; refused"
            )
            continue
        target = Path(raw)
        # 3. Refuse the leaf if it is a symlink (even if its target is
        # a valid file). Belt-and-braces: also refuse any symlinked
        # ancestor that is not the macOS /tmp exemption.
        if target.is_symlink():
            try:
                tgt = str(target.readlink())
            except OSError:
                tgt = "<unreadable>"
            errors.append(
                f"--require-files: {label} path {target} is a "
                f"symlink (-> {tgt}); refused"
            )
            continue
        bad, msg = _refuse_symlinked_ancestor(target, label)
        if bad:
            errors.append(f"--require-files: {msg}")
            continue
        # 4. Must exist as a regular file (not a directory, not a FIFO
        # / socket / device, not missing).
        if not target.exists():
            errors.append(
                f"--require-files: {label} path {target} does not "
                f"exist"
            )
            continue
        if target.is_dir():
            errors.append(
                f"--require-files: {label} path {target} is a "
                f"directory; expected a regular file"
            )
            continue
        if not target.is_file():
            errors.append(
                f"--require-files: {label} path {target} is not a "
                f"regular file (FIFO / socket / device?)"
            )
            continue
        # 5. Must not live under REPO_ROOT. The evidence is supposed
        # to record artifacts produced under a tempdir OUTSIDE the
        # repo tree; a path inside the repo is a misuse signal.
        if _path_is_under(target, repo_root_abs):
            errors.append(
                f"--require-files: {label} path {target} is under "
                f"REPO_ROOT ({repo_root_abs}); refused (mock-trial "
                f"artifacts must live in a tempdir OUTSIDE the repo)"
            )
            continue
        resolved_paths.append(Path(os.path.abspath(str(target))))

    # If any path failed individually, stop here (the common-ancestor
    # check would be noisy and unhelpful when paths are missing).
    if errors:
        return errors

    if len(resolved_paths) != 4:
        # Shouldn't happen given the per-path bail-outs above, but
        # belt-and-braces.
        errors.append(
            f"--require-files: expected 4 resolved paths, got "
            f"{len(resolved_paths)}"
        )
        return errors

    common = _common_ancestor(resolved_paths)
    if common is None:
        errors.append(
            "--require-files: the 4 paths share no common ancestor"
        )
        return errors
    # The common ancestor must be a strict descendant of one of the
    # system temp roots — being equal to a system temp root itself
    # (i.e. /tmp common across the 4 paths but each in a different
    # subdir) is refused so a tampered record cannot mix several
    # per-run tempdirs.
    in_temp = False
    for temp in system_temps:
        try:
            rel = common.relative_to(temp)
        except ValueError:
            continue
        if str(rel) == "." or rel.parts == ():
            # The common ancestor IS the system temp root itself.
            continue
        in_temp = True
        break
    if not in_temp:
        errors.append(
            f"--require-files: the 4 paths' common ancestor "
            f"({common}) is not strictly inside any system temp root "
            f"({[str(t) for t in system_temps]!r}); the per-run "
            f"tempdir contract is violated"
        )

    return errors


# ---------------------------------------------------------------------------
# Top-level validation.
# ---------------------------------------------------------------------------


def _load_evidence(
    path: Path,
) -> tuple[dict | None, str]:
    """G1 — read + parse + object-root check."""
    if path.is_symlink():
        try:
            tgt = str(path.readlink())
        except OSError:
            tgt = "<unreadable>"
        return None, (
            f"FAIL: {path} is a symlink (-> {tgt}); refuses to "
            f"follow it (broken or not)"
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
        return None, f"FAIL: {path} is not valid JSON: {exc}"
    if not isinstance(record, dict):
        return None, (
            f"FAIL: {path}: expected JSON object at root, got "
            f"{type(record).__name__}"
        )
    return record, ""


def validate_evidence(
    evidence: dict,
    schema: dict,
    *,
    evidence_path: Path | None = None,
    require_files: bool = False,
) -> list[str]:
    """Return a list of validation errors. Empty list means every gate
    PASSed under the documented subset."""
    # Schema validation is run first; semantic gates assume schema-
    # conformant input (the cross-checks would surface noisy False
    # positives if e.g. ``sidecar`` was missing entirely).
    schema_errors: list[str] = []
    _validate(evidence, schema, "<root>", schema_errors)
    if schema_errors:
        return schema_errors

    errors: list[str] = []
    errors.extend(_check_schema_version(evidence))
    errors.extend(_check_evidence_id(evidence))
    errors.extend(_check_real_d_one_status_phrasing(evidence))
    errors.extend(_check_summary_ok_consistency(evidence))
    errors.extend(_check_per_request_well_formed(evidence))
    errors.extend(_check_placement_role_coverage(evidence))
    errors.extend(_check_text_policy_diversity(evidence))
    errors.extend(_check_bundle_text_policy_parity(evidence))
    errors.extend(_check_string_safety(evidence))
    errors.extend(_check_real_d_one_claim_refusal(evidence))
    if require_files:
        if evidence_path is None:
            errors.append(
                "--require-files requires evidence_path to be passed "
                "to validate_evidence()"
            )
        else:
            errors.extend(
                _require_files_check(evidence, evidence_path)
            )
    return errors


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs under
# ``tempfile.TemporaryDirectory()``; no fixture leaks into the repo.
# ---------------------------------------------------------------------------


def _canonical_real_d_one_status() -> str:
    return (
        "UNVERIFIED. Real D-One is NOT called by this evidence "
        "emitter. The PNG bytes embedded in the produced PPTX come "
        "from the in-script mock provider, not from any external "
        "service. No MCP, no public network, no model API, no image "
        "search, no Qoder, no telemetry."
    )


def _baseline_record(
    *,
    pptx_path: str = "synthetic-tempdir/trial.pptx",
    inventory_path: str = (
        "synthetic-tempdir/trial_report/inventory.json"
    ),
    sidecar_path: str = (
        "synthetic-tempdir/trial_report/mock_d_one_adapter_plan.json"
    ),
) -> dict:
    return {
        "schema_version": "1",
        "evidence_id": "mock_image_bundle_trial_evidence",
        "real_d_one_status": _canonical_real_d_one_status(),
        "pptx": {
            "path": pptx_path,
            "exists": True,
            "size_bytes": 1024,
        },
        "validators": {
            "validate_pptx_contract": {"rc": 0, "ok": True},
            "inspect_pptx_inventory": {"rc": 0, "ok": True},
            "validate_mock_d_one_adapter_plan": {
                "rc": 0,
                "ok": True,
                "vocabulary_gate_used": True,
                "require_both_placement_roles_used": True,
            },
        },
        "inventory": {
            "path": inventory_path,
            "exists": True,
            "parses_as_json": True,
            "ok": True,
            "findings": [],
            "slide_count": 2,
            "media_parts_count": 2,
            "evidence_basis": EXPECTED_EVIDENCE_BASIS,
            "evidence_basis_matches": True,
            "slide_count_matches_plan": True,
            "media_parts_count_min_met": True,
            "no_external_relationships": True,
            "findings_empty": True,
        },
        "sidecar": {
            "path": sidecar_path,
            "exists": True,
            "parses_as_json": True,
            "schema_version": 4,
            "schema_version_locked": True,
            "request_count": 2,
            "request_count_matches_requests": True,
            "requests": [
                {
                    "id": "synthetic_hero",
                    "placement_role": "hero_page",
                    "text_policy": "no_text",
                    "subject_domain": "abstract_geometry",
                    "manifest_local_path": "media/synthetic_hero.png",
                },
                {
                    "id": "synthetic_local",
                    "placement_role": "local_region",
                    "text_policy": "caption_safe",
                    "subject_domain": "process_motif",
                    "manifest_local_path": "media/synthetic_local.png",
                },
            ],
            "malformed_request_indices": [],
            "all_requests_well_formed": True,
            "placement_role_coverage": ["hero_page", "local_region"],
            "covers_both_placement_roles": True,
            "text_policy_coverage": ["caption_safe", "no_text"],
            "covers_multiple_text_policies": True,
        },
        "bundle_path": "synthetic-tempdir/bundle",
        "report_dir": "synthetic-tempdir/trial_report",
        "notes": {
            "scope": (
                "Synthetic mock-image bundle trial evidence. NOT "
                "real D-One, NOT MCP, NOT Qoder, NOT a public-"
                "network run, NOT telemetry."
            ),
            "embed_surface": (
                "PNG, JPG, and JPEG inside ppt media slot."
            ),
        },
        "summary": {"ok": True},
    }


def _write(td: Path, name: str, payload) -> Path:
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


def _expect(name: str, ok: bool, detail: str = "") -> tuple[
    str, bool, str
]:
    return (name, ok, detail if not ok else "")


def _validate_path(
    path: Path, schema: dict, *, require_files: bool = False,
) -> tuple[int, list[str]]:
    record, err = _load_evidence(path)
    if err:
        return 1, [err]
    errors = validate_evidence(
        record, schema,
        evidence_path=path, require_files=require_files,
    )
    return (0 if not errors else 1), errors


def _run_self_tests() -> list[tuple[str, bool, str]]:  # noqa: C901
    schema = json.loads(EVIDENCE_SCHEMA.read_text(encoding="utf-8"))
    results: list[tuple[str, bool, str]] = []

    # ---- 1. Committed template validates. ----
    rc, errs = _validate_path(COMMITTED_TEMPLATE, schema)
    results.append(_expect(
        "committed examples/mock_image_bundle_trial_evidence_template"
        ".json validates against the schema and every semantic gate",
        rc == 0 and not errs,
        f"rc={rc}, errs={errs!r}",
    ))

    # ---- 2. Synthetic baseline record validates. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        p = _write(td, "rec.json", _baseline_record())
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "synthetic baseline record validates under tempdir",
            rc == 0 and not errs,
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 3. Symlinked evidence path refused (G1). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        real = _write(td, "real.json", _baseline_record())
        link = td / "link.json"
        link.symlink_to(real)
        rc, errs = _validate_path(link, schema)
        results.append(_expect(
            "symlinked evidence path refused (G1)",
            rc == 1 and any("is a symlink" in e for e in errs),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 4. Non-JSON evidence file refused (G1). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        p = _write(td, "rec.json", "{not-json")
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "non-JSON evidence refused (G1)",
            rc == 1 and any("not valid JSON" in e for e in errs),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 5. List-rooted JSON refused (G1). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        p = _write(td, "rec.json", [_baseline_record()])
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "list-rooted JSON refused (G1)",
            rc == 1 and any(
                "expected JSON object" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 6. Wrong schema_version refused (G2 enum + G2 belt). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["schema_version"] = "2"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "wrong schema_version refused (G2 enum)",
            rc == 1 and any(
                "schema_version" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 7. Wrong evidence_id refused (G2 enum). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["evidence_id"] = "tampered_id"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "wrong evidence_id refused (G2 enum)",
            rc == 1 and any(
                "evidence_id" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 8. Missing required top-level field refused (G2). ----
    for missing in (
        "pptx", "inventory", "validators", "sidecar", "summary",
        "real_d_one_status",
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            rec = _baseline_record()
            del rec[missing]
            p = _write(td, "rec.json", rec)
            rc, errs = _validate_path(p, schema)
            results.append(_expect(
                f"missing required top-level field {missing!r} "
                f"refused (G2)",
                rc == 1 and any(
                    f"missing required property '{missing}'" in e
                    for e in errs
                ),
                f"rc={rc}, errs={errs!r}",
            ))

    # ---- 9. Additional top-level property refused (G2). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["smuggle"] = "anything"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "additional top-level property refused (G2 additional"
            "Properties:false)",
            rc == 1 and any(
                "additional property 'smuggle' not allowed" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 10. real_d_one_status missing UNVERIFIED refused (G3). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["real_d_one_status"] = (
            "Mock chain only. No real D-One, no MCP, no public "
            "network was called."
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "real_d_one_status missing 'UNVERIFIED' refused (G3)",
            rc == 1 and any(
                "UNVERIFIED" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 11. real_d_one_status missing negation refused (G3). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["real_d_one_status"] = (
            "UNVERIFIED — mock chain produced two PNGs and a deck."
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "real_d_one_status missing negated wording refused (G3)",
            rc == 1 and any(
                "negated/no-call wording" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 12. Missing per-request field refused (G5 + summary G4). ----
    for field in _REQUIRED_REQUEST_FIELDS:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            rec = _baseline_record()
            del rec["sidecar"]["requests"][0][field]
            p = _write(td, "rec.json", rec)
            rc, errs = _validate_path(p, schema)
            results.append(_expect(
                f"missing per-request field {field!r} refused (G5/G2)",
                rc == 1 and (
                    any(f"missing required property '{field}'" in e
                        for e in errs)
                    or any(
                        f"sidecar.requests[0].{field}" in e
                        for e in errs
                    )
                ),
                f"rc={rc}, errs={errs!r}",
            ))

    # ---- 13. request_count != len(requests) refused (G4). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["sidecar"]["request_count"] = 99
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "sidecar.request_count != len(requests) refused (G4)",
            rc == 1 and any(
                "request_count" in e and "len(requests)" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 14. Missing local_region coverage refused (G6). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        # Flip the local_region request to hero_page so only one role
        # is covered.
        rec["sidecar"]["requests"][1]["placement_role"] = "hero_page"
        rec["sidecar"]["placement_role_coverage"] = ["hero_page"]
        rec["sidecar"]["covers_both_placement_roles"] = False
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "missing local_region placement_role coverage refused "
            "(G6 + G4)",
            rc == 1 and any(
                "placement_role" in e and "local_region" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 14a. text_policy collapsed to one value refused (G10). ----
    # All requests carry the same text_policy → the sidecar collapsed
    # per-request text_policy judgement, which the goal pins to flow
    # end-to-end through the committed bundle path (not only the
    # adapter-only smoke).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        for req in rec["sidecar"]["requests"]:
            req["text_policy"] = "no_text"
        rec["sidecar"]["text_policy_coverage"] = ["no_text"]
        rec["sidecar"]["covers_multiple_text_policies"] = False
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "text_policy collapsed to a single value across requests "
            "refused (G10)",
            rc == 1 and any(
                "text_policy" in e
                and "distinct" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 14b. tampered text_policy_coverage refused (G10 cross-check)
    # The derived coverage array claims 2 distinct values but the
    # per-request values are all ``no_text``. The cross-check must
    # surface the disagreement so a tampered evidence record cannot
    # hand-edit the derived field to false-green the diversity gate.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        for req in rec["sidecar"]["requests"]:
            req["text_policy"] = "no_text"
        # Leave text_policy_coverage / covers_multiple_text_policies at
        # the baseline values (which still claim 2 distinct values) so
        # the cross-check fires.
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "tampered text_policy_coverage disagreeing with requests[*]"
            ".text_policy refused (G10 cross-check)",
            rc == 1 and any(
                "text_policy_coverage" in e
                and "disagrees" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 14c. tampered covers_multiple_text_policies refused (G10). --
    # The derived boolean claims True but the per-request values are
    # all the same value. Mirrors 14b but for the boolean half of the
    # derivation; either tampering shape should be caught.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        for req in rec["sidecar"]["requests"]:
            req["text_policy"] = "no_text"
        rec["sidecar"]["text_policy_coverage"] = ["no_text"]
        # Leave covers_multiple_text_policies=True; the cross-check
        # must fire because len({no_text}) < 2.
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "tampered covers_multiple_text_policies=True with single-"
            "value coverage refused (G10 cross-check)",
            rc == 1 and any(
                "covers_multiple_text_policies" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    def _committed_bundle_evidence_record() -> dict:
        rec = json.loads(
            (REPO_ROOT / "examples/mock_image_bundle_trial_evidence_"
             "template.json").read_text()
        )
        rec["bundle_path"] = str(
            (REPO_ROOT / "examples/synthetic_mock_image_trial").resolve()
        )
        rec["sidecar"]["requests"][0].update({
            "id": "cover_accent",
            "manifest_local_path": "media/cover_accent.png",
            "placement_role": "hero_page",
            "subject_domain": "abstract_geometry",
            "text_policy": "no_text",
        })
        rec["sidecar"]["requests"][1].update({
            "id": "system_schematic",
            "manifest_local_path": "media/system_schematic.png",
            "placement_role": "local_region",
            "subject_domain": "process_motif",
            "text_policy": "caption_safe",
        })
        rec["sidecar"]["text_policy_coverage"] = [
            "caption_safe", "no_text",
        ]
        rec["sidecar"]["covers_multiple_text_policies"] = True
        rec["sidecar"]["placement_role_coverage"] = [
            "hero_page", "local_region",
        ]
        rec["sidecar"]["covers_both_placement_roles"] = True
        return rec

    # ---- 14d. local bundle d_one_spec parity happy path (G10). ----
    # The committed evidence template mirrors the committed bundle's
    # request ids / text_policy values. Point bundle_path at the real
    # committed bundle so the filesystem parity extension actually
    # opens d_one_spec.json and confirms it agrees.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _committed_bundle_evidence_record()
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "local bundle d_one_spec text_policy parity passes when "
            "evidence mirrors the committed bundle (G10 parity)",
            rc == 0,
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 14e. local bundle d_one_spec parity drift refused (G10). ----
    # Keep the evidence internally consistent (two distinct values +
    # derived fields updated), but drift one per-id value away from
    # the committed bundle's d_one_spec.json. Without the bundle
    # parity extension this shape false-greened.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _committed_bundle_evidence_record()
        rec["sidecar"]["requests"][0]["text_policy"] = (
            "decorative_glyphs"
        )
        rec["sidecar"]["text_policy_coverage"] = [
            "caption_safe", "decorative_glyphs",
        ]
        rec["sidecar"]["covers_multiple_text_policies"] = True
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "evidence text_policy drift from local bundle d_one_spec "
            "refused even when coverage is internally consistent "
            "(G10 parity)",
            rc == 1 and any(
                "d_one_spec.json" in e
                and "disagrees" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 15. vocabulary_gate_used=false with summary.ok=true. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["validators"]["validate_mock_d_one_adapter_plan"][
            "vocabulary_gate_used"
        ] = False
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "vocabulary_gate_used=False with summary.ok=True refused "
            "(G4)",
            rc == 1 and any(
                "vocabulary_gate_used" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 16. require_both_placement_roles_used=false. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["validators"]["validate_mock_d_one_adapter_plan"][
            "require_both_placement_roles_used"
        ] = False
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "require_both_placement_roles_used=False with summary.ok"
            "=True refused (G4)",
            rc == 1 and any(
                "require_both_placement_roles_used" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 17. Failed validator with summary.ok=true refused (G4). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["validators"]["validate_pptx_contract"]["ok"] = False
        rec["validators"]["validate_pptx_contract"]["rc"] = 1
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "failed validator (validate_pptx_contract) with summary"
            ".ok=True refused (G4)",
            rc == 1 and any(
                "summary.ok=True is inconsistent" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 18. summary.ok=False allowed when sub-gates fail. ----
    # The validator does NOT require summary.ok=True; a legitimately
    # failed run records summary.ok=False alongside the failed gates.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["validators"]["validate_pptx_contract"]["ok"] = False
        rec["validators"]["validate_pptx_contract"]["rc"] = 1
        rec["summary"]["ok"] = False
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "summary.ok=False with a failed validator is internally "
            "consistent and accepted (legitimate failed-run record)",
            rc == 0 and not errs,
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 19. Real-D-One verified claim in notes refused (G8). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["notes"]["scope"] = (
            "Real D-One verified online; production run succeeded."
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "real-D-One success claim in notes.scope refused (G8)",
            rc == 1 and any(
                "real-D-One" in e or "refused real-D-One" in e
                for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 20. sk- token in a string refused (G7). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["sidecar"]["requests"][0]["custom_descriptor"] = (
            "sk-abcdef0123456789xyz"
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "sk- token in custom_descriptor refused (G7)",
            rc == 1 and any("sk- prefix" in e for e in errs),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 21. api_key: literal in a string refused (G7). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        # Inject into notes.scope (free-form string).
        rec["notes"]["scope"] = (
            "Mock only. UNVERIFIED. api_key: not_a_real_key_value"
        )
        # Restore the UNVERIFIED + negation in status (the notes one
        # is independent of G3).
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "api_key: literal in notes.scope refused (G7)",
            rc == 1 and any("api_key:" in e for e in errs),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 22. token: literal refused (G7). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["notes"]["embed_surface"] = (
            "PNG only. token: synthetic_value"
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "token: literal in notes.embed_surface refused (G7)",
            rc == 1 and any("token:" in e for e in errs),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 23. External URL in any string refused (G7). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["bundle_path"] = "http://attacker.example/bundle"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "external URL (http://...) in bundle_path refused (G7)",
            rc == 1 and any(
                "URI/URL scheme" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 24. Public-upload phrase refused (G7). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["notes"]["scope"] = (
            "Mock only. The deck will upload to public bucket."
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "public-upload phrasing refused (G7)",
            rc == 1 and any(
                "public-distribution wording" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 25. Public-hosting phrase refused (G7). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["notes"]["scope"] = (
            "Mock only. Future runs may use public hosting."
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "public-hosting phrasing refused (G7)",
            rc == 1 and any(
                "public-distribution wording" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 26. Share-publicly phrase refused (G7). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["notes"]["scope"] = (
            "Mock only. Operators may share publicly later."
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "share-publicly phrasing refused (G7)",
            rc == 1 and any(
                "public-distribution wording" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 27. Confidential marker refused (G7). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["notes"]["embed_surface"] = (
            "PNG. CONFIDENTIAL — internal use only."
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "confidential marker refused (G7)",
            rc == 1 and any(
                "confidential" in e.lower() for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 28. customer_id marker refused (G7). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["sidecar"]["requests"][0]["id"] = "customer_id_42"
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "customer_id marker in request id refused (G7)",
            rc == 1 and any("customer_id" in e for e in errs),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 29. Raw-source marker refused (G7). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        rec["notes"]["scope"] = (
            "Mock only. Spliced from the raw source dump."
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "raw-source marker refused (G7)",
            rc == 1 and any(
                "raw-source marker" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 30. --require-files happy path under common tempdir. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        # Plant the four artifacts.
        pptx = td / "trial.pptx"
        pptx.write_bytes(b"PK\x03\x04stub")
        inv = td / "trial_report" / "inventory.json"
        inv.parent.mkdir()
        inv.write_text("{}")
        sc = td / "trial_report" / "mock_d_one_adapter_plan.json"
        sc.write_text("{}")
        rec = _baseline_record(
            pptx_path=str(pptx),
            inventory_path=str(inv),
            sidecar_path=str(sc),
        )
        ev = _write(td, "evidence.json", rec)
        rc, errs = _validate_path(ev, schema, require_files=True)
        results.append(_expect(
            "--require-files happy path under a single tempdir "
            "passes",
            rc == 0 and not errs,
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 31. --require-files refuses a repo path. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pptx = td / "trial.pptx"
        pptx.write_bytes(b"PK")
        inv = td / "inventory.json"
        inv.write_text("{}")
        sc = td / "sidecar.json"
        sc.write_text("{}")
        # Point evidence at a REPO file (the schema file itself
        # exists; it doesn't matter that the content is wrong because
        # the path-safety gate fires first).
        rec = _baseline_record(
            pptx_path=str(EVIDENCE_SCHEMA),
            inventory_path=str(inv),
            sidecar_path=str(sc),
        )
        ev = _write(td, "evidence.json", rec)
        rc, errs = _validate_path(ev, schema, require_files=True)
        results.append(_expect(
            "--require-files refuses a repo-resident path (pptx.path "
            "points at schemas/...)",
            rc == 1 and any(
                "under REPO_ROOT" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 32. --require-files refuses a URI path. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pptx = td / "trial.pptx"; pptx.write_bytes(b"PK")
        inv = td / "inventory.json"; inv.write_text("{}")
        sc = td / "sidecar.json"; sc.write_text("{}")
        rec = _baseline_record(
            pptx_path="http://attacker.example/x.pptx",
            inventory_path=str(inv),
            sidecar_path=str(sc),
        )
        ev = _write(td, "evidence.json", rec)
        rc, errs = _validate_path(ev, schema, require_files=True)
        # The URI also trips the G7 string scan; the --require-files
        # path-layer gate must additionally surface.
        results.append(_expect(
            "--require-files refuses a URI-shaped pptx.path",
            rc == 1 and (
                any("carries a URI scheme" in e for e in errs)
                or any("URI/URL scheme" in e for e in errs)
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 33. --require-files refuses traversal path. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pptx = td / "trial.pptx"; pptx.write_bytes(b"PK")
        inv = td / "inventory.json"; inv.write_text("{}")
        sc = td / "sidecar.json"; sc.write_text("{}")
        rec = _baseline_record(
            pptx_path=str(td / "a" / ".." / "trial.pptx"),
            inventory_path=str(inv),
            sidecar_path=str(sc),
        )
        ev = _write(td, "evidence.json", rec)
        rc, errs = _validate_path(ev, schema, require_files=True)
        results.append(_expect(
            "--require-files refuses a '..' traversal in pptx.path",
            rc == 1 and (
                any("'..' segment" in e for e in errs)
                or any("path-traversal" in e for e in errs)
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 34. --require-files refuses a missing file. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pptx = td / "trial.pptx"; pptx.write_bytes(b"PK")
        inv = td / "inventory.json"; inv.write_text("{}")
        sc = td / "sidecar.json"; sc.write_text("{}")
        rec = _baseline_record(
            pptx_path=str(td / "missing.pptx"),
            inventory_path=str(inv),
            sidecar_path=str(sc),
        )
        ev = _write(td, "evidence.json", rec)
        rc, errs = _validate_path(ev, schema, require_files=True)
        results.append(_expect(
            "--require-files refuses a missing pptx.path",
            rc == 1 and any("does not exist" in e for e in errs),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 35. --require-files refuses a directory. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pptx_dir = td / "trial_dir"; pptx_dir.mkdir()
        inv = td / "inventory.json"; inv.write_text("{}")
        sc = td / "sidecar.json"; sc.write_text("{}")
        rec = _baseline_record(
            pptx_path=str(pptx_dir),
            inventory_path=str(inv),
            sidecar_path=str(sc),
        )
        ev = _write(td, "evidence.json", rec)
        rc, errs = _validate_path(ev, schema, require_files=True)
        results.append(_expect(
            "--require-files refuses a directory at pptx.path",
            rc == 1 and any("is a directory" in e for e in errs),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 36. --require-files refuses a symlinked evidence file. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        real_ev = td / "real_evidence.json"
        pptx = td / "trial.pptx"; pptx.write_bytes(b"PK")
        inv = td / "inventory.json"; inv.write_text("{}")
        sc = td / "sidecar.json"; sc.write_text("{}")
        rec = _baseline_record(
            pptx_path=str(pptx),
            inventory_path=str(inv),
            sidecar_path=str(sc),
        )
        real_ev.write_text(
            json.dumps(rec, sort_keys=True, indent=2) + "\n"
        )
        link_ev = td / "link_evidence.json"
        link_ev.symlink_to(real_ev)
        rc, errs = _validate_path(link_ev, schema, require_files=True)
        results.append(_expect(
            "--require-files refuses a symlinked evidence file (G1)",
            rc == 1 and any("is a symlink" in e for e in errs),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 37. --require-files refuses a symlinked PPTX. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        real_pptx = td / "real.pptx"; real_pptx.write_bytes(b"PK")
        link_pptx = td / "link.pptx"; link_pptx.symlink_to(real_pptx)
        inv = td / "inventory.json"; inv.write_text("{}")
        sc = td / "sidecar.json"; sc.write_text("{}")
        rec = _baseline_record(
            pptx_path=str(link_pptx),
            inventory_path=str(inv),
            sidecar_path=str(sc),
        )
        ev = _write(td, "evidence.json", rec)
        rc, errs = _validate_path(ev, schema, require_files=True)
        results.append(_expect(
            "--require-files refuses a symlinked pptx.path",
            rc == 1 and any(
                "is a symlink" in e and "pptx" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 38. --require-files refuses a symlinked sidecar. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pptx = td / "trial.pptx"; pptx.write_bytes(b"PK")
        inv = td / "inventory.json"; inv.write_text("{}")
        real_sc = td / "real_sidecar.json"; real_sc.write_text("{}")
        link_sc = td / "link_sidecar.json"
        link_sc.symlink_to(real_sc)
        rec = _baseline_record(
            pptx_path=str(pptx),
            inventory_path=str(inv),
            sidecar_path=str(link_sc),
        )
        ev = _write(td, "evidence.json", rec)
        rc, errs = _validate_path(ev, schema, require_files=True)
        results.append(_expect(
            "--require-files refuses a symlinked sidecar.path",
            rc == 1 and any(
                "is a symlink" in e and "sidecar" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 39. --require-files refuses a symlinked inventory. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        pptx = td / "trial.pptx"; pptx.write_bytes(b"PK")
        real_inv = td / "real_inventory.json"; real_inv.write_text("{}")
        link_inv = td / "link_inventory.json"
        link_inv.symlink_to(real_inv)
        sc = td / "sidecar.json"; sc.write_text("{}")
        rec = _baseline_record(
            pptx_path=str(pptx),
            inventory_path=str(link_inv),
            sidecar_path=str(sc),
        )
        ev = _write(td, "evidence.json", rec)
        rc, errs = _validate_path(ev, schema, require_files=True)
        results.append(_expect(
            "--require-files refuses a symlinked inventory.path",
            rc == 1 and any(
                "is a symlink" in e and "inventory" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    # ---- 39b. macOS private-alias regression guard. ----
    # Codex stop-time review caught that the earlier exemption only
    # allowed ``/tmp -> private/tmp`` — on a default macOS run where
    # the per-user tempdir lives under ``/var/folders/.../T/...``,
    # the ancestor walk through ``/var`` (itself a system symlink to
    # ``/private/var``) tripped the gate and refused every otherwise-
    # valid evidence record. This guard pins the closed allow-list:
    # /tmp, /var, /etc are accepted iff the target is private/<name>
    # or /private/<name>; anything else is refused.
    macos_alias_results: list[tuple[Path, str, bool]] = [
        # (ancestor, symlink_target, expected_is_alias)
        (Path("/tmp"), "private/tmp", True),
        (Path("/tmp"), "/private/tmp", True),
        (Path("/var"), "private/var", True),
        (Path("/var"), "/private/var", True),
        (Path("/etc"), "private/etc", True),
        (Path("/etc"), "/private/etc", True),
        # Attacker-shape: wrong basename, non-allow-listed name,
        # multi-component path, non-private target.
        (Path("/tmp"), "private/var", False),
        (Path("/var"), "private/tmp", False),
        (Path("/usr"), "private/usr", False),
        (Path("/opt"), "private/opt", False),
        (Path("/var/folders"), "private/var/folders", False),
        (Path("/tmp"), "/attacker/tmp", False),
        (Path("/var"), "/some/other/var", False),
    ]
    alias_fails: list[str] = []
    for ancestor, tgt, expected in macos_alias_results:
        got = _is_macos_private_alias(ancestor, tgt)
        if got != expected:
            alias_fails.append(
                f"_is_macos_private_alias({ancestor}, {tgt!r}) "
                f"returned {got}, expected {expected}"
            )
    results.append(_expect(
        "macOS private-alias allow-list pins /tmp, /var, /etc with "
        "matching basename + private/-shaped target; refuses every "
        "other (ancestor, target) shape (regression guard for the "
        "Codex stop-time finding that /var symlinks were rejected "
        "as tempdir ancestors)",
        not alias_fails,
        "; ".join(alias_fails) if alias_fails else "",
    ))

    # ---- 40. Real-D-One bare boolean True at a noun key (G8). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rec = _baseline_record()
        # The schema's additionalProperties:false at the root catches
        # a smuggled top-level key — but the G8 walker is the deeper
        # gate: insert a tampered boolean inside the notes block (the
        # schema allows scope/embed_surface, only those, so we cannot
        # smuggle a bool there). Instead, perturb the sidecar's
        # request to claim ``custom_descriptor`` is a noun-bearing
        # success claim string. That trips G7's URI/credential check
        # first — to isolate G8, set summary.ok=False (so G4 does not
        # also fire) and insert the claim into notes.scope.
        rec["summary"]["ok"] = False
        rec["notes"]["scope"] = (
            "Mock only. Real D-One verified online."
        )
        p = _write(td, "rec.json", rec)
        rc, errs = _validate_path(p, schema)
        results.append(_expect(
            "real-D-One verified claim in notes.scope trips G8 even "
            "with summary.ok=False (the static gate is independent)",
            rc == 1 and any(
                "refused real-D-One" in e for e in errs
            ),
            f"rc={rc}, errs={errs!r}",
        ))

    return results


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Local validator for the mock-image bundle trial "
            "evidence record produced by "
            "scripts/mock_image_bundle_trial_evidence.py. "
            "Schema-validates against "
            "schemas/mock_image_bundle_trial_evidence.schema.json "
            "and applies the documented semantic + string-safety + "
            "real-D-One claim-refusal gates (and the --require-files "
            "filesystem gate when requested). Read-only. Stdlib-only. "
            "NO real D-One. NO MCP. NO Qoder. NO model API. NO "
            "public network. NO image search. NO telemetry."
        ),
    )
    parser.add_argument(
        "--evidence", type=Path,
        help="Path to the evidence JSON file to validate.",
    )
    parser.add_argument(
        "--require-files", action="store_true",
        help=(
            "Additionally require evidence / pptx / inventory / "
            "sidecar paths to be regular non-symlink files sharing a "
            "common ancestor strictly under the system tempdir. "
            "Repo paths, URI paths, traversal paths, symlinks "
            "(at the leaf or any ancestor that is not one of the "
            "three macOS standard top-level aliases /tmp -> "
            "private/tmp, /var -> private/var, /etc -> private/etc), "
            "directories, and missing files are refused."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run the in-script self-test matrix under tempdir-only "
            "fixtures (read-only against the committed schema + "
            "template). Exits 0 iff every scenario passes."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if args.evidence or args.require_files:
            print(
                "FAIL: --self-test cannot be combined with --evidence "
                "or --require-files.",
                file=sys.stderr,
            )
            return 2
        if not EVIDENCE_SCHEMA.is_file():
            print(
                f"FAIL: schema not found at {EVIDENCE_SCHEMA}",
                file=sys.stderr,
            )
            return 2
        if not COMMITTED_TEMPLATE.is_file():
            print(
                f"FAIL: committed template not found at "
                f"{COMMITTED_TEMPLATE}",
                file=sys.stderr,
            )
            return 2

        print("=== validate_mock_image_bundle_trial_evidence ===")
        print(
            "  read-only, stdlib-only, tempdir-only fixtures; NO "
            "real D-One / MCP / Qoder / network / model API / "
            "image search / telemetry."
        )
        results = _run_self_tests()
        fails = 0
        for name, ok, detail in results:
            mark = "PASS" if ok else "FAIL"
            suffix = f" -- {detail}" if not ok and detail else ""
            print(f"  [{mark}] {name}{suffix}")
            if not ok:
                fails += 1
        if fails:
            print(
                f"\nFAIL: {fails} of {len(results)} self-test "
                f"scenario(s) did not pass.",
                file=sys.stderr,
            )
            return 1
        print(
            f"\nOK (validate_mock_image_bundle_trial_evidence): "
            f"{len(results)} self-test scenarios passed; the "
            f"committed examples/mock_image_bundle_trial_evidence_"
            f"template.json validates against the schema and every "
            f"semantic gate; the synthetic baseline + every negative "
            f"probe (missing required field, count mismatch, missing "
            f"local_region, text_policy collapsed to a single value "
            f"+ tampered text_policy_coverage / "
            f"covers_multiple_text_policies cross-check + local "
            f"bundle d_one_spec parity drift (G10), vocab flag "
            f"false, role flag false, failed validator with "
            f"summary.ok=True, real-D-One verified claim, "
            f"sk-/api_key:/token: tokens, external URL, public "
            f"hosting/upload/share, confidential / customer_id / "
            f"raw-source markers, --require-files repo path / URI / "
            f"traversal / missing / directory / symlinked evidence-"
            f"PPTX-inventory-sidecar) flips a non-zero exit. "
            f"Read-only / stdlib-only / tempdir-only."
        )
        return 0

    if not args.evidence:
        print(
            "FAIL: --evidence is required (or pass --self-test).",
            file=sys.stderr,
        )
        return 2
    if not EVIDENCE_SCHEMA.is_file():
        print(
            f"FAIL: schema not found at {EVIDENCE_SCHEMA}",
            file=sys.stderr,
        )
        return 2

    schema = json.loads(EVIDENCE_SCHEMA.read_text(encoding="utf-8"))
    record, err = _load_evidence(args.evidence)
    if err:
        print(err, file=sys.stderr)
        return 1
    errors = validate_evidence(
        record, schema,
        evidence_path=args.evidence,
        require_files=args.require_files,
    )
    if errors:
        print(
            f"FAIL: {args.evidence} did not pass every gate.",
            file=sys.stderr,
        )
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    suffix = " (with --require-files)" if args.require_files else ""
    print(
        f"OK (mock_image_bundle_trial_evidence): "
        f"{args.evidence} passes schema + every semantic + string-"
        f"safety + real-D-One claim-refusal gate{suffix}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
