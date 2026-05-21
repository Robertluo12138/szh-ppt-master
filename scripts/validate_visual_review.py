#!/usr/bin/env python3
"""Local validator for synthetic per-slide visual-review rubric files.

Stdlib-only. NETWORK-FREE. NO-D-ONE. NO-Qoder. NO model API. NO MCP.
NO browser. NO screenshot. NO image generation. NO PPTX export.
NO telemetry.

This validator gates a candidate visual-review JSON against
``schemas/visual_review.schema.json`` plus a small set of content gates
documented in ``references/visual-review-contract.md``. The review is a
per-slide rubric assessment whose ``evidence_basis`` is pinned to the
single literal ``"local_artifact_metadata_only"`` — the only evidence
basis this contract recognises today. A review SHOULD be derivable from
inspecting committed local pipeline artifacts (deck_plan, slide_plan,
render_model, conversion_trace) and MUST NOT claim that a screenshot,
browser, model API, image generator, D-One, Qoder, MCP, or external
service was used.

Given an explicit ``--review <path>``, this script schema-validates the
file AND enforces:

  V1 readable_json_object (load-time precheck — exit 2 if it fires)
    - review path must exist as a regular non-symlink file;
    - bytes must be readable as UTF-8;
    - bytes must parse as JSON;
    - the parsed JSON must be a top-level OBJECT.

  V2 schema_subset_valid
    - validates against ``schemas/visual_review.schema.json`` under the
      same stdlib subset that ``scripts/validate_artifacts.py`` applies
      (no ``$ref`` / ``oneOf`` / ``format``).

  V3 evidence_basis_pinned
    - both the root ``evidence_basis`` AND every
      ``records[].evidence_basis`` MUST equal the literal
      ``"local_artifact_metadata_only"``. The schema enum already
      enforces this on the happy path; V3 mirrors it so a future
      schema relaxation does not silently let a second basis through,
      and so the runtime diagnostic names the specific basis at fault.

  V4 ids_are_synthetic
    - ``review_id`` / ``deck.deck_id`` / ``generated_by.name`` MUST
      each match the literal ``^synthetic_...`` shape.

  V5 closed_enums_runtime_recheck
    - every ``records[].status`` / ``issue_type`` / ``severity`` /
      ``recommended_action`` MUST be in its closed enum. The schema
      enum already enforces this; V5 mirrors it so the diagnostic
      names the specific record + field if a future schema relaxation
      slips a value through.

  V6 per_slide_coverage
    - ``records`` MUST cover EXACTLY ``deck.slide_count`` slides:
      slide_index 1..deck.slide_count appears once each, no missing
      slide, no extra slide. A review that skips slide 2 in a 3-slide
      deck OR carries a record at slide 4 of a 3-slide deck is refused.

  V7 unique_slide_index
    - every ``records[].slide_index`` MUST be unique across the whole
      records array. V6 already detects a duplicate AS a missing slot;
      V7 is the surgical diagnostic that names the duplicate index.

  V8 summary_counts_match_records
    - ``summary.{pass,warn,fail}_count`` MUST equal the per-status
      totals computed from ``records``. A review whose summary
      disagrees with its own records is refused.

  V9 no_url_or_uri_scheme
    - no string field may carry an RFC 3986 URI-scheme prefix
      (``http:``, ``https:``, ``file:``, ``data:``, ``s3:``, ``ftp:``,
      ``mailto:``, ``javascript:``) NOR an embedded URL.

  V10 no_unsafe_path_shape
    - no string field may start with ``/``, ``\\``, or ``//``, and no
      string field may contain a ``..`` path segment when split on
      ``/`` or ``\\``.

  V11 no_public_upload_wording
    - no string field, once canonicalised (lower-case AND non-alphanum
      stripped), may contain the marker ``public`` AND ALSO any
      propagation-verb marker ``upload`` / ``share`` / ``sharing`` /
      ``url`` / ``link`` / ``post`` / ``publish`` / ``distribut`` /
      ``host``.

  V12 no_credential_shaped_wording
    - no string field may contain a credential-shape token
      (``apikey``, ``apitoken``, ``accesstoken``, ``authtoken``,
      ``csrftoken``, ``idtoken``, ``jwttoken``, ``oauthtoken``,
      ``refreshtoken``, ``sessiontoken``, ``secret``, ``bearer``,
      ``password``, ``token``) once canonicalised; AND no string
      field's raw form may match the ``\\bsk-[A-Za-z0-9_\\-]{16,}``
      regex (the ``sk-``-prefixed OpenAI / Anthropic API-key shape).

  V13 no_raw_source_or_confidential_wording
    - no string field, once canonicalised, may contain
      ``confidential``, ``proprietary``, ``internalonly``,
      ``ndaprotected``, ``customername``, ``accountid``, ``ssn``,
      ``creditcard``, OR the marker ``raw`` together with any of
      ``source`` / ``content`` / ``paragraph`` / ``excerpt``.

  V14 no_out_of_scope_tool_claim_wording
    - no string field, once canonicalised, may contain any of the
      bare out-of-scope tool tokens (``screenshot``,
      ``headlessbrowser``, ``browserautomation``, ``selenium``,
      ``playwright``, ``puppeteer``, ``chromium``, ``webdriver``,
      ``qoder``, ``telemetry``, ``midjourney``, ``stablediffusion``,
      ``dalle``, ``firefly``, ``imagen``, ``imagegen``,
      ``imagegeneration``, ``generateimage``, ``texttoimage``,
      ``promptimage``, ``aiimage``, ``aiimagery``, ``aimodel``,
      ``languagemodel``); OR may carry any of the marker+qualifier
      shapes:
        - ``done`` + (``image`` / ``asset`` / ``render`` /
          ``generated`` / ``imagegen`` / ``used`` / ``called`` /
          ``invok`` / ``queried``);
        - ``mcp`` + (``call`` / ``server`` / ``invoc`` /
          ``request`` / ``endpoint`` / ``used`` / ``queried``);
        - ``model`` + (``api`` / ``inferenc`` / ``judg`` /
          ``llm`` / ``gpt`` / ``queried``) (canonical-form
          substring check);
        - bare ``model`` word (regex ``\\bmodel\\b`` against the
          ORIGINAL string, so underscored compounds like
          ``render_model`` / ``design_model`` are excluded
          because ``_`` is a regex word character) +
          (``used`` / ``called`` / ``invok`` / ``prompted``);
        - ``external`` + (``service`` / ``api`` / ``endpoint`` /
          ``host``);
        - ``browser`` + (``captur`` / ``open`` / ``snapshot`` /
          ``render`` / ``automat`` / ``used`` / ``invok`` /
          ``launched``).
      The ``done`` / ``mcp`` / ``browser`` qualifier lists span
      both action verbs (``image`` / ``call`` / ``captur`` /
      ``automat``) AND usage verbs (``used`` / ``called`` /
      ``invok`` / ``queried`` / ``launched``) because those three
      markers ("done" is the canonical of ``D-One``, ``MCP``, and
      ``browser``) effectively never appear in static-metadata
      review prose outside an out-of-scope tool-claim — so the wider
      usage-verb set carries no false-positive risk. The ``model``
      canonical-form qualifier list is kept narrow to AI-tool-
      specific verbs because the canonical form drops non-alphanum
      chars and so cannot distinguish ``render_model used`` from
      ``model used``; the contract-required generic ``used`` /
      ``called`` / ``invok`` / ``prompted`` claims about a bare
      ``model`` are caught by a separate ``\\bmodel\\b`` word-
      boundary check against the ORIGINAL string, which excludes
      underscored compounds because ``_`` is a regex word
      character. The ``external`` qualifier list is kept narrow to
      ``service`` / ``api`` / ``endpoint`` / ``host`` so legitimate
      layout-terminology wording like ``"external border used in
      this layout"`` still passes. The gate refuses both positive
      ("screenshot captured by browser", "model API was queried",
      "model was used to grade contrast") AND negative ("no
      screenshot was captured", "no model API was used", "no model
      was queried") wording for any phrasing that IS in scope,
      because either polarity implies the review is in scope for an
      out-of-scope tool.

Out of scope for THIS validator (and explicitly refused here):

  - calling D-One / Qoder / MCP / any image generator / model API /
    image search / public network / external service;
  - capturing a screenshot, opening a browser, rendering a slide,
    invoking a headless renderer;
  - mutating the review or any pipeline artifact (read-only);
  - any chart rendering / PPTX export / SVG generation behavior.

Exit codes:
  0  every gate passed (or --self-test scenarios all behaved as expected).
  1  one or more structural / content gates failed (V2..V14).
  2  invocation / file / parse error. Covers: missing or incompatible
     CLI flags; schema file missing on disk; AND every V1 precheck
     failure.

CLI:
  python3 scripts/validate_visual_review.py --review <path-to-review.json>
  python3 scripts/validate_visual_review.py --self-test
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "schemas"

sys.path.insert(0, str(SCRIPTS_DIR))

from validate_artifacts import _validate  # noqa: E402

REVIEW_SCHEMA = SCHEMAS_DIR / "visual_review.schema.json"

# Closed enums mirrored from the schema. Kept here so the validator
# can run V3 / V5 / V8 without re-parsing the schema for those specific
# enums.
_EVIDENCE_BASIS_LITERAL = "local_artifact_metadata_only"

_STATUS_ENUM: frozenset[str] = frozenset({"pass", "warn", "fail"})
_ISSUE_TYPE_ENUM: frozenset[str] = frozenset({
    "text_density",
    "overflow_risk",
    "contrast_risk",
    "image_only_risk",
    "editability_risk",
    "layout_mismatch",
    "media_risk",
    "trace_mismatch",
    "other_synthetic_probe",
})
_SEVERITY_ENUM: frozenset[str] = frozenset({
    "info", "low", "medium", "high",
})
_RECOMMENDED_ACTION_ENUM: frozenset[str] = frozenset({
    "inspect_source",
    "adjust_copy",
    "adjust_layout",
    "rerun_export",
    "inspect_trace",
    "no_action",
})

# RFC 3986 scheme: ALPHA *( ALPHA / DIGIT / "+" / "-" / "." ) ":"
# Two shapes, mirroring validate_brand_preset / validate_conversion_trace:
#   - anchored at start: refuses ``file:thing`` / ``mailto:a@b`` whole-field URIs;
#   - embedded URL pattern: refuses ``... see https://x ...`` style content.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_EMBEDDED_URL = re.compile(
    r"\b(?:https?|s3|ftp|file|mailto|javascript)://[^\s\"'<>]+|"
    r"\b(?:data|mailto|javascript):[A-Za-z0-9+\-/.,;@%_]+",
    flags=re.IGNORECASE,
)

_NON_ALPHANUM = re.compile(r"[^a-z0-9]")

_PUBLIC_MARKER = "public"
_PROPAGATION_VERB_MARKERS: tuple[str, ...] = (
    "upload",
    "share",
    "sharing",
    "url",
    "link",
    "post",
    "publish",
    "distribut",
    "host",
)

# Credential-shape compound tokens; qualifier-prefixed compounds first
# so the diagnostic on ``access_token`` names the specific compound
# (``accesstoken``) rather than the bare ``token``.
_CREDENTIAL_COMPOUND_TOKENS: tuple[str, ...] = (
    "apikey",
    "apitoken",
    "accesstoken",
    "authtoken",
    "csrftoken",
    "idtoken",
    "jwttoken",
    "oauthtoken",
    "refreshtoken",
    "sessiontoken",
    "secret",
    "bearer",
    "password",
    "token",
)
_SK_PREFIX_KEY = re.compile(
    r"\bsk-[A-Za-z0-9_\-]{16,}",
    flags=re.IGNORECASE,
)

_CONFIDENTIAL_COMPOUND_TOKENS: tuple[str, ...] = (
    "confidential",
    "proprietary",
    "internalonly",
    "ndaprotected",
    "customername",
    "accountid",
    "ssn",
    "creditcard",
)
_RAW_MARKER = "raw"
_RAW_SOURCE_MARKERS: tuple[str, ...] = (
    "source",
    "content",
    "paragraph",
    "excerpt",
)

# V14 — claims that an out-of-scope tool/service was used. Two shapes:
#
# (a) Bare canonical tokens: single tokens whose presence in a static
#     metadata review note is itself out of scope (no contract reason
#     to mention them, positive or negative).
#
# (b) Marker + qualifier pairs: fire only when BOTH occur in the same
#     canonical-form string. Bare ``browser`` / ``model`` / ``external``
#     on their own do NOT trip the gate — only their use alongside a
#     usage verb does. This keeps the gate narrow enough to not refuse
#     a legitimate ``model template`` mention if one ever needed to
#     appear, while still refusing ``model api called`` /
#     ``browser captured`` / ``external service queried``.
_V14_BARE_TOKENS: tuple[str, ...] = (
    "screenshot",
    "headlessbrowser",
    "browserautomation",
    "selenium",
    "playwright",
    "puppeteer",
    "chromium",
    "webdriver",
    "qoder",
    "telemetry",
    "midjourney",
    "stablediffusion",
    "dalle",
    "firefly",
    "imagen",
    "imagegen",
    "imagegeneration",
    "generateimage",
    "texttoimage",
    "promptimage",
    "aiimage",
    "aiimagery",
    # Unambiguous AI-model compounds. These fire on phrasings like
    # "AI model was used" / "language model was queried" without
    # tripping legitimate ``render_model`` evidence wording (canonical
    # form of ``render_model`` is ``rendermodel`` — does NOT contain
    # ``aimodel`` or ``languagemodel`` as a substring).
    "aimodel",
    "languagemodel",
)

_V14_DONE_MARKER = "done"
_V14_DONE_QUALIFIERS: tuple[str, ...] = (
    "image", "asset", "render", "generated", "imagegen",
    "used", "called", "invok", "queried",
)

_V14_MCP_MARKER = "mcp"
_V14_MCP_QUALIFIERS: tuple[str, ...] = (
    "call", "server", "invoc", "request", "endpoint",
    "used", "queried",
)

_V14_MODEL_MARKER = "model"
# Canonical-form qualifier list kept narrow to AI-tool-specific verbs
# because the canonical form drops non-alphanum chars and so cannot
# distinguish "render_model used" from "model used". The contract-
# required generic usage verbs (used / called / invok / prompted) for
# the bare "model" subject are handled instead by the
# _V14_MODEL_BARE_RE word-boundary check below, which uses the
# ORIGINAL string and excludes underscored compounds (\b does not
# match between "_" and "m" because both are word chars). The
# canonical-form check still catches "model api was queried" and
# similar AI-tool-specific qualifier wording.
_V14_MODEL_QUALIFIERS: tuple[str, ...] = (
    "api", "inferenc", "judg", "llm", "gpt", "queried",
)

# Bare-word "model" detection. \b is a regex word boundary and "_" is
# a regex word character — so \bmodel\b matches the standalone "model"
# noun in "the model was used" but does NOT match the underscored
# compounds "render_model" / "design_model" / etc. (no boundary
# between "_" and "m"). Combined with _V14_MODEL_QUALIFIERS above, V14
# refuses BOTH "model API was used" (via the canonical-form check)
# AND "model was used" (via this bare-word check) while still passing
# legitimate render_model evidence wording.
_V14_MODEL_BARE_RE = re.compile(r"\bmodel\b", flags=re.IGNORECASE)
_V14_MODEL_BARE_USAGE_QUALIFIERS: tuple[str, ...] = (
    "used", "called", "invok", "prompted",
)

_V14_EXTERNAL_MARKER = "external"
# Qualifier list kept narrow so legitimate layout-terminology wording
# like "external border used in this layout" does not false-positive
# (canonical "externalborderused" contains "external" + "used" but
# "used" is intentionally NOT in this list). The contract's primary
# claim "external service was used" still fires via the original
# ``service`` qualifier; "external API was called" via ``api``;
# "external endpoint was invoked" via ``endpoint``.
_V14_EXTERNAL_QUALIFIERS: tuple[str, ...] = (
    "service", "api", "endpoint", "host",
)

_V14_BROWSER_MARKER = "browser"
_V14_BROWSER_QUALIFIERS: tuple[str, ...] = (
    "captur", "open", "snapshot", "render", "automat",
    "used", "invok", "launched",
)

_SYNTHETIC_PREFIX_RE = re.compile(r"^synthetic_[a-z0-9][a-z0-9_]*$")


def _canonical(value: str) -> str:
    """Lower-case ``value`` and drop every non-alphanumeric character."""
    return _NON_ALPHANUM.sub("", value.lower())


def _has_uri_scheme(s: str) -> bool:
    if _URI_SCHEME_PREFIX.match(s):
        return True
    if _EMBEDDED_URL.search(s):
        return True
    return False


def _starts_with_unsafe_path_prefix(s: str) -> bool:
    if s.startswith("//"):
        return True
    if s.startswith("/"):
        return True
    if s.startswith("\\"):
        return True
    return False


def _contains_parent_segment(s: str) -> bool:
    segments = s.replace("\\", "/").split("/")
    return any(seg == ".." for seg in segments)


def _walk_strings(obj: Any, path: str = "<root>") -> Iterable[tuple[str, str]]:
    """Yield (json-path, string-value) for every string in ``obj``."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


class ReviewLoadError(Exception):
    """Raised by ``_load_review`` when the V1 precheck fails. Carries a
    single ``V1: ...`` diagnostic line. ``main()`` maps this to exit 2."""


def _load_review(review_path: Path) -> dict:
    if review_path.is_symlink():
        raise ReviewLoadError(
            f"V1: review path is a symlink (refused): {review_path}"
        )
    if not review_path.exists():
        raise ReviewLoadError(
            f"V1: review path does not exist: {review_path}"
        )
    if not review_path.is_file():
        raise ReviewLoadError(
            f"V1: review path is not a regular file: {review_path}"
        )
    try:
        raw = review_path.read_bytes()
    except OSError as exc:
        raise ReviewLoadError(
            f"V1: cannot read review {review_path}: {exc}"
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewLoadError(
            f"V1: review is not valid UTF-8: {exc}"
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReviewLoadError(
            f"V1: review is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ReviewLoadError(
            f"V1: top-level JSON value is {type(data).__name__}, "
            f"expected object"
        )
    return data


def _gate_schema_subset_valid(data: dict) -> list[str]:
    """V2 — schema validation under the stdlib subset."""
    errors: list[str] = []
    try:
        schema = json.loads(REVIEW_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"V2: cannot read schema {REVIEW_SCHEMA}: {exc}"]
    _validate(data, schema, "<root>", errors)
    return [f"V2: {e}" for e in errors]


def _gate_evidence_basis_pinned(data: dict) -> list[str]:
    """V3 — root + per-record evidence_basis MUST equal the single
    literal ``local_artifact_metadata_only``."""
    errors: list[str] = []
    root_value = data.get("evidence_basis")
    if root_value != _EVIDENCE_BASIS_LITERAL:
        errors.append(
            f"V3: evidence_basis must equal "
            f"{_EVIDENCE_BASIS_LITERAL!r} (got {root_value!r}); a "
            f"second basis requires a paired contract change in the "
            f"schema, validator, and contract doc"
        )
    records = data.get("records")
    if isinstance(records, list):
        for i, rec in enumerate(records):
            if not isinstance(rec, dict):
                continue
            value = rec.get("evidence_basis")
            if value != _EVIDENCE_BASIS_LITERAL:
                errors.append(
                    f"V3: records[{i}].evidence_basis must equal "
                    f"{_EVIDENCE_BASIS_LITERAL!r} (got {value!r})"
                )
    return errors


def _gate_ids_are_synthetic(data: dict) -> list[str]:
    """V4 — review_id / deck.deck_id / generated_by.name MUST each be a
    synthetic_-prefixed id."""
    errors: list[str] = []
    fields = (
        ("review_id", data.get("review_id")),
        ("deck.deck_id", (data.get("deck") or {}).get("deck_id")
            if isinstance(data.get("deck"), dict) else None),
        ("generated_by.name", (data.get("generated_by") or {}).get("name")
            if isinstance(data.get("generated_by"), dict) else None),
    )
    for label, value in fields:
        if not isinstance(value, str):
            errors.append(
                f"V4: {label}: value must be a string carrying the "
                f"'synthetic_' prefix (got {type(value).__name__})"
            )
            continue
        if not _SYNTHETIC_PREFIX_RE.match(value):
            errors.append(
                f"V4: {label}: value {value!r} does not match the "
                f"required synthetic_-prefix id shape"
            )
    return errors


def _gate_closed_enums_runtime_recheck(data: dict) -> list[str]:
    """V5 — closed-enum re-check at runtime so the diagnostic names the
    specific record + field at fault even if a future schema relaxation
    slipped a value through."""
    errors: list[str] = []
    records = data.get("records")
    if not isinstance(records, list):
        return errors
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        path = f"records[{i}]"
        status = rec.get("status")
        if status not in _STATUS_ENUM:
            errors.append(
                f"V5: {path}.status: value {status!r} not in closed "
                f"enum {sorted(_STATUS_ENUM)!r}"
            )
        issue = rec.get("issue_type")
        if issue not in _ISSUE_TYPE_ENUM:
            errors.append(
                f"V5: {path}.issue_type: value {issue!r} not in closed "
                f"enum {sorted(_ISSUE_TYPE_ENUM)!r}"
            )
        severity = rec.get("severity")
        if severity not in _SEVERITY_ENUM:
            errors.append(
                f"V5: {path}.severity: value {severity!r} not in closed "
                f"enum {sorted(_SEVERITY_ENUM)!r}"
            )
        action = rec.get("recommended_action")
        if action not in _RECOMMENDED_ACTION_ENUM:
            errors.append(
                f"V5: {path}.recommended_action: value {action!r} not in "
                f"closed enum {sorted(_RECOMMENDED_ACTION_ENUM)!r}"
            )
    return errors


def _gate_per_slide_coverage(data: dict) -> list[str]:
    """V6 — records MUST cover slide_index 1..deck.slide_count exactly."""
    errors: list[str] = []
    deck = data.get("deck")
    records = data.get("records")
    if not isinstance(deck, dict) or not isinstance(records, list):
        return errors
    declared = deck.get("slide_count")
    if not isinstance(declared, int) or isinstance(declared, bool):
        return errors
    if declared < 1:
        return errors
    expected: set[int] = set(range(1, declared + 1))
    seen: set[int] = set()
    extras: list[int] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        idx = rec.get("slide_index")
        if not isinstance(idx, int) or isinstance(idx, bool):
            continue
        if idx in expected:
            seen.add(idx)
        else:
            extras.append(idx)
    missing = sorted(expected - seen)
    if missing:
        errors.append(
            f"V6: records miss slide_index(es) {missing!r}; deck."
            f"slide_count={declared} requires a record at every slot in "
            f"1..{declared}"
        )
    if extras:
        errors.append(
            f"V6: records carry extra slide_index(es) {sorted(set(extras))!r} "
            f"outside 1..{declared}"
        )
    return errors


def _gate_unique_slide_index(data: dict) -> list[str]:
    """V7 — slide_index MUST be unique across records."""
    errors: list[str] = []
    records = data.get("records")
    if not isinstance(records, list):
        return errors
    seen: dict[int, int] = {}
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        idx = rec.get("slide_index")
        if not isinstance(idx, int) or isinstance(idx, bool):
            continue
        if idx in seen:
            errors.append(
                f"V7: records[{i}].slide_index={idx} duplicates "
                f"records[{seen[idx]}].slide_index"
            )
        else:
            seen[idx] = i
    return errors


def _gate_summary_counts_match_records(data: dict) -> list[str]:
    """V8 — summary totals MUST equal per-status counts in records."""
    errors: list[str] = []
    records = data.get("records")
    summary = data.get("summary")
    if not isinstance(records, list) or not isinstance(summary, dict):
        return errors
    counts = {
        "pass_count": 0,
        "warn_count": 0,
        "fail_count": 0,
    }
    status_to_key = {
        "pass": "pass_count",
        "warn": "warn_count",
        "fail": "fail_count",
    }
    for rec in records:
        if not isinstance(rec, dict):
            continue
        key = status_to_key.get(rec.get("status"))
        if key is not None:
            counts[key] += 1
    for k, expected in counts.items():
        actual = summary.get(k)
        if actual != expected:
            errors.append(
                f"V8: summary.{k} = {actual!r}, but records imply "
                f"{expected}"
            )
    return errors


def _gate_no_url_or_uri_scheme(data: dict) -> list[str]:
    errors: list[str] = []
    for path, value in _walk_strings(data):
        if _has_uri_scheme(value):
            errors.append(
                f"V9: {path}: value {value!r} carries a URI-scheme prefix"
            )
    return errors


def _gate_no_unsafe_path_shape(data: dict) -> list[str]:
    errors: list[str] = []
    for path, value in _walk_strings(data):
        if _starts_with_unsafe_path_prefix(value):
            errors.append(
                f"V10: {path}: value {value!r} starts with an unsafe "
                f"path prefix ('/', '\\\\', or '//')"
            )
            continue
        if _contains_parent_segment(value):
            errors.append(
                f"V10: {path}: value {value!r} contains a '..' segment"
            )
    return errors


def _gate_no_public_upload_wording(data: dict) -> list[str]:
    errors: list[str] = []
    for path, value in _walk_strings(data):
        canon = _canonical(value)
        if _PUBLIC_MARKER in canon and any(
            verb in canon for verb in _PROPAGATION_VERB_MARKERS
        ):
            errors.append(
                f"V11: {path}: value {value!r} combines 'public' with a "
                f"propagation verb (canonical form: {canon!r})"
            )
    return errors


def _gate_no_credential_shaped_wording(data: dict) -> list[str]:
    errors: list[str] = []
    for path, value in _walk_strings(data):
        canon = _canonical(value)
        matched: str | None = None
        for token in _CREDENTIAL_COMPOUND_TOKENS:
            if token in canon:
                matched = token
                break
        if matched is not None:
            errors.append(
                f"V12: {path}: value {value!r} carries credential-"
                f"shaped wording ({matched!r}; canonical form: "
                f"{canon!r})"
            )
            continue
        if _SK_PREFIX_KEY.search(value):
            errors.append(
                f"V12: {path}: value {value!r} carries an sk- prefixed "
                f"API-key shape"
            )
    return errors


def _gate_no_raw_source_or_confidential_wording(data: dict) -> list[str]:
    errors: list[str] = []
    for path, value in _walk_strings(data):
        canon = _canonical(value)
        matched: str | None = None
        for token in _CONFIDENTIAL_COMPOUND_TOKENS:
            if token in canon:
                matched = token
                break
        if matched is None and _RAW_MARKER in canon and any(
            noun in canon for noun in _RAW_SOURCE_MARKERS
        ):
            matched = "raw + source/content/paragraph/excerpt"
        if matched is not None:
            errors.append(
                f"V13: {path}: value {value!r} carries confidential / "
                f"raw-source wording ({matched}; canonical form: "
                f"{canon!r})"
            )
    return errors


def _gate_no_out_of_scope_tool_claim(data: dict) -> list[str]:
    """V14 — claims that a screenshot, browser, model, D-One, MCP,
    Qoder, or external service was used. Three shapes: bare tokens,
    marker+qualifier pairs against the canonical form, and a separate
    ``\\bmodel\\b`` word-boundary check against the ORIGINAL string
    paired with a generic usage verb so passive-voice "model was used
    / called / invoked / prompted" claims fire without false-
    positiving on underscored compounds like ``render_model``. The
    negation form ("no screenshot was captured") is intentionally also
    refused — either side implies the review is in scope for an
    out-of-scope tool, and the contract refuses that scope expansion
    regardless of polarity."""
    errors: list[str] = []
    marker_qualifier_pairs: tuple[tuple[str, tuple[str, ...]], ...] = (
        (_V14_DONE_MARKER, _V14_DONE_QUALIFIERS),
        (_V14_MCP_MARKER, _V14_MCP_QUALIFIERS),
        (_V14_MODEL_MARKER, _V14_MODEL_QUALIFIERS),
        (_V14_EXTERNAL_MARKER, _V14_EXTERNAL_QUALIFIERS),
        (_V14_BROWSER_MARKER, _V14_BROWSER_QUALIFIERS),
    )
    for path, value in _walk_strings(data):
        canon = _canonical(value)
        matched: str | None = None
        for token in _V14_BARE_TOKENS:
            if token in canon:
                matched = token
                break
        if matched is None:
            for marker, quals in marker_qualifier_pairs:
                if marker in canon and any(q in canon for q in quals):
                    matched = f"{marker} + {{{','.join(quals)}}}"
                    break
        if matched is None and _V14_MODEL_BARE_RE.search(value):
            for qual in _V14_MODEL_BARE_USAGE_QUALIFIERS:
                if qual in canon:
                    matched = (
                        f"bare 'model' + "
                        f"{{{','.join(_V14_MODEL_BARE_USAGE_QUALIFIERS)}}}"
                    )
                    break
        if matched is not None:
            errors.append(
                f"V14: {path}: value {value!r} carries out-of-scope "
                f"tool-claim wording ({matched}; canonical form: "
                f"{canon!r})"
            )
    return errors


GATES = (
    ("V3", _gate_evidence_basis_pinned),
    ("V4", _gate_ids_are_synthetic),
    ("V5", _gate_closed_enums_runtime_recheck),
    ("V6", _gate_per_slide_coverage),
    ("V7", _gate_unique_slide_index),
    ("V8", _gate_summary_counts_match_records),
    ("V9", _gate_no_url_or_uri_scheme),
    ("V10", _gate_no_unsafe_path_shape),
    ("V11", _gate_no_public_upload_wording),
    ("V12", _gate_no_credential_shaped_wording),
    ("V13", _gate_no_raw_source_or_confidential_wording),
    ("V14", _gate_no_out_of_scope_tool_claim),
)


def validate_review(review_path: Path) -> list[str]:
    """Run V2..V14 against the review. Raises ``ReviewLoadError`` for
    V1 precheck failures (caller maps those to exit 2)."""
    data = _load_review(review_path)
    errors: list[str] = []
    errors.extend(_gate_schema_subset_valid(data))
    for _name, gate in GATES:
        errors.extend(gate(data))
    return errors


# ----------------------------------------------------------------------
# --self-test
# ----------------------------------------------------------------------

_GOOD_REVIEW: dict[str, Any] = {
    "schema_version": "1",
    "review_id": "synthetic_self_test",
    "evidence_basis": "local_artifact_metadata_only",
    "generated_by": {
        "name": "synthetic_self_test",
        "mode": "self_test_fixture",
    },
    "deck": {
        "deck_id": "synthetic_demo_deck",
        "slide_count": 3,
    },
    "records": [
        {
            "slide_index": 1,
            "slide_layout": "cover",
            "status": "pass",
            "issue_type": "other_synthetic_probe",
            "severity": "info",
            "evidence_basis": "local_artifact_metadata_only",
            "recommended_action": "no_action",
        },
        {
            "slide_index": 2,
            "slide_layout": "kpi_dashboard",
            "status": "warn",
            "issue_type": "text_density",
            "severity": "low",
            "evidence_basis": "local_artifact_metadata_only",
            "recommended_action": "adjust_copy",
        },
        {
            "slide_index": 3,
            "slide_layout": "comparison_table",
            "status": "fail",
            "issue_type": "overflow_risk",
            "severity": "high",
            "evidence_basis": "local_artifact_metadata_only",
            "recommended_action": "adjust_layout",
        },
    ],
    "summary": {
        "pass_count": 1,
        "warn_count": 1,
        "fail_count": 1,
    },
}


def _write_tmp(data: Any, tmp: Path, name: str) -> Path:
    p = tmp / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _scenario(
    label: str,
    mutate,
    expected_gates: str | tuple[str, ...],
) -> tuple[bool, str]:
    """Run one self-test scenario. ``mutate`` takes a fresh copy of
    _GOOD_REVIEW and returns the candidate. ``expected_gates`` is either
    ``""`` (the scenario MUST pass), a single gate prefix like ``"V5"``,
    or a tuple of gate prefixes the scenario MUST fire at least one of."""
    candidate = json.loads(json.dumps(_GOOD_REVIEW))
    candidate = mutate(candidate)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        path = _write_tmp(candidate, tmp, "review.json")
        errors = validate_review(path)
    if not expected_gates:
        if errors:
            return False, f"{label}: expected PASS but got errors: {errors}"
        return True, f"{label}: PASS"
    if isinstance(expected_gates, str):
        expected = (expected_gates,)
    else:
        expected = expected_gates
    if not errors:
        return False, (
            f"{label}: expected gate(s) {expected} to fire but "
            f"validator returned OK"
        )
    fired = {e.split(":", 1)[0] for e in errors}
    if not fired.intersection(expected):
        return False, (
            f"{label}: expected one of {expected} to fire; got {errors}"
        )
    extra = fired - set(expected)
    if extra:
        return True, (
            f"{label}: refused under {sorted(fired & set(expected))} "
            f"(also fired: {sorted(extra)})"
        )
    return True, f"{label}: refused under {sorted(fired)}"


def _self_test() -> int:
    results: list[tuple[bool, str]] = []

    # Positive baseline against the in-script fixture.
    results.append(_scenario("baseline-good", lambda d: d, ""))

    # Positive sweep across every closed status / issue_type / severity /
    # recommended_action value. Each enum's full set must pass the
    # validator when applied to a fresh single-slide candidate. Catches
    # the failure mode where a future content gate canonicalises a
    # legitimate enum value into a banned substring (the same regression
    # guard validate_conversion_trace.py runs over its reason_code enum).
    def _single_slide(d):
        d["deck"]["slide_count"] = 1
        d["records"] = [d["records"][0]]
        d["summary"] = {
            "pass_count": 1, "warn_count": 0, "fail_count": 0,
        }
        return d

    for _s in sorted(_STATUS_ENUM):
        def _mut(d, status=_s):
            _single_slide(d)
            d["records"][0]["status"] = status
            d["summary"] = {
                "pass_count": 0, "warn_count": 0, "fail_count": 0,
            }
            d["summary"][f"{status}_count"] = 1
            return d
        results.append(_scenario(f"status-sweep-{_s}", _mut, ""))

    for _it in sorted(_ISSUE_TYPE_ENUM):
        def _mut(d, issue=_it):
            _single_slide(d)
            d["records"][0]["issue_type"] = issue
            return d
        results.append(_scenario(f"issue-type-sweep-{_it}", _mut, ""))

    for _sv in sorted(_SEVERITY_ENUM):
        def _mut(d, sev=_sv):
            _single_slide(d)
            d["records"][0]["severity"] = sev
            return d
        results.append(_scenario(f"severity-sweep-{_sv}", _mut, ""))

    for _ac in sorted(_RECOMMENDED_ACTION_ENUM):
        def _mut(d, act=_ac):
            _single_slide(d)
            d["records"][0]["recommended_action"] = act
            return d
        results.append(_scenario(f"action-sweep-{_ac}", _mut, ""))

    # Positive baseline against the committed example fixture, so a
    # regression that breaks the example is caught here.
    committed = REPO_ROOT / "examples" / "synthetic_visual_review.json"
    if committed.is_file():
        errors = validate_review(committed)
        ok = not errors
        results.append((
            ok,
            (
                "committed-example: PASS"
                if ok
                else f"committed-example: expected PASS, got {errors}"
            ),
        ))

    # V2 — schema violation (missing required field).
    def m_v2(d):
        d.pop("summary")
        return d
    results.append(_scenario("v2-missing-required", m_v2, "V2"))

    # V2 — unknown status (closed enum); schema enum fires.
    def m_v2_status(d):
        _single_slide(d)
        d["records"][0]["status"] = "maybe_pass"
        return d
    results.append(_scenario(
        "v2-unknown-status", m_v2_status, ("V2", "V5", "V8"),
    ))

    # V2 — unknown issue_type.
    def m_v2_issue(d):
        _single_slide(d)
        d["records"][0]["issue_type"] = "made_up_category"
        return d
    results.append(_scenario(
        "v2-unknown-issue-type", m_v2_issue, ("V2", "V5"),
    ))

    # V2 — unknown severity.
    def m_v2_severity(d):
        _single_slide(d)
        d["records"][0]["severity"] = "critical"
        return d
    results.append(_scenario(
        "v2-unknown-severity", m_v2_severity, ("V2", "V5"),
    ))

    # V2 — unknown recommended_action.
    def m_v2_action(d):
        _single_slide(d)
        d["records"][0]["recommended_action"] = "ask_model"
        return d
    results.append(_scenario(
        "v2-unknown-action", m_v2_action, ("V2", "V5"),
    ))

    # V3 — root evidence_basis flipped to something out of scope.
    def m_v3_root(d):
        d["evidence_basis"] = "screenshot_diff"
        return d
    results.append(_scenario(
        "v3-root-evidence-flipped", m_v3_root, ("V2", "V3", "V14"),
    ))

    # V3 — per-record evidence_basis flipped.
    def m_v3_record(d):
        d["records"][0]["evidence_basis"] = "model_judgment"
        return d
    results.append(_scenario(
        "v3-record-evidence-flipped", m_v3_record, ("V2", "V3"),
    ))

    # V4 — non-synthetic review_id.
    def m_v4(d):
        d["review_id"] = "real_company_q4"
        return d
    results.append(_scenario("v4-non-synthetic-id", m_v4, ("V2", "V4")))

    # V4 — non-synthetic deck.deck_id.
    def m_v4_deck(d):
        d["deck"]["deck_id"] = "real_internal_deck"
        return d
    results.append(_scenario(
        "v4-non-synthetic-deck-id", m_v4_deck, ("V2", "V4"),
    ))

    # V6 — missing slide coverage (records skip slide 2 in a 3-slide deck).
    def m_v6_missing(d):
        del d["records"][1]
        d["summary"]["warn_count"] = 0
        return d
    results.append(_scenario("v6-missing-slide", m_v6_missing, "V6"))

    # V6 — extra slide_index beyond deck.slide_count.
    def m_v6_extra(d):
        d["records"][1]["slide_index"] = 99
        return d
    results.append(_scenario("v6-extra-slide", m_v6_extra, "V6"))

    # V7 — duplicate slide_index. Also re-uses slot 1, so V6 sees slot 2
    # as missing — both V6 and V7 are valid diagnostics here.
    def m_v7_dup(d):
        d["records"][1]["slide_index"] = 1
        return d
    results.append(_scenario(
        "v7-duplicate-slide-index", m_v7_dup, ("V6", "V7"),
    ))

    # V8 — summary disagrees with records.
    def m_v8_drift(d):
        d["summary"]["pass_count"] = 99
        return d
    results.append(_scenario("v8-summary-drift", m_v8_drift, "V8"))

    # V9 — URL in trace-level notes.
    def m_v9(d):
        d["notes"] = "see https://example/notes for context"
        return d
    results.append(_scenario("v9-url", m_v9, "V9"))

    # V9 — file:// URI scheme in a record note.
    def m_v9_file(d):
        d["records"][0]["note"] = "file:///etc/passwd"
        return d
    results.append(_scenario("v9-file-uri", m_v9_file, "V9"))

    # V9 — data: URI in a note.
    def m_v9_data(d):
        d["records"][0]["note"] = "data:image/png;base64,AAAA"
        return d
    results.append(_scenario("v9-data-uri", m_v9_data, "V9"))

    # V10 — absolute path in a record note.
    def m_v10_abs(d):
        d["records"][0]["note"] = "/etc/passwd should not appear"
        return d
    results.append(_scenario("v10-absolute-path", m_v10_abs, "V10"))

    # V10 — parent traversal in a record note.
    def m_v10_parent(d):
        d["records"][0]["note"] = "uses ../../secrets path"
        return d
    results.append(_scenario("v10-parent-segment", m_v10_parent, "V10"))

    # V11 — public-upload wording.
    def m_v11_public_upload(d):
        d["notes"] = "auto public upload after build"
        return d
    results.append(_scenario(
        "v11-public-upload", m_v11_public_upload, "V11",
    ))

    # V11 — public + host.
    def m_v11_public_hosting(d):
        d["notes"] = "public hosting enabled"
        return d
    results.append(_scenario(
        "v11-public-hosting", m_v11_public_hosting, "V11",
    ))

    # V12 — credential family probes.
    def m_v12_api_key(d):
        d["notes"] = "store api_key here"
        return d
    results.append(_scenario("v12-api-key", m_v12_api_key, "V12"))

    def m_v12_secret(d):
        d["notes"] = "client secret value"
        return d
    results.append(_scenario("v12-secret", m_v12_secret, "V12"))

    def m_v12_token(d):
        d["notes"] = "token placeholder"
        return d
    results.append(_scenario("v12-token", m_v12_token, "V12"))

    def m_v12_sk_prefix(d):
        d["notes"] = "key is sk-abcdef0123456789xyz"
        return d
    results.append(_scenario("v12-sk-prefix", m_v12_sk_prefix, "V12"))

    # V13 — confidential marker.
    def m_v13_confidential(d):
        d["notes"] = "marked confidential, internal"
        return d
    results.append(_scenario(
        "v13-confidential", m_v13_confidential, "V13",
    ))

    # V13 — raw + source.
    def m_v13_raw_source(d):
        d["notes"] = "carries raw source excerpt verbatim"
        return d
    results.append(_scenario(
        "v13-raw-source", m_v13_raw_source, "V13",
    ))

    # V14 — every bare token must fire.
    for _t in sorted(_V14_BARE_TOKENS):
        def _mut(d, token=_t):
            d["notes"] = f"this review {token} run"
            return d
        results.append(_scenario(
            f"v14-bare-{_t}", _mut, "V14",
        ))

    # V14 — marker+qualifier shapes.
    def m_v14_done_image(d):
        d["notes"] = "done image generated locally"
        return d
    results.append(_scenario(
        "v14-done-image", m_v14_done_image, "V14",
    ))

    def m_v14_mcp_call(d):
        d["notes"] = "an mcp call was invoked"
        return d
    results.append(_scenario("v14-mcp-call", m_v14_mcp_call, "V14"))

    def m_v14_model_api(d):
        d["notes"] = "no model api was queried"
        return d
    results.append(_scenario(
        "v14-model-api-negation", m_v14_model_api, "V14",
    ))

    def m_v14_external_service(d):
        d["notes"] = "external service called"
        return d
    results.append(_scenario(
        "v14-external-service", m_v14_external_service, "V14",
    ))

    def m_v14_browser_captured(d):
        d["notes"] = "browser captured the slide"
        return d
    results.append(_scenario(
        "v14-browser-captured", m_v14_browser_captured, "V14",
    ))

    # V14 — negation form ("no screenshot was taken") still trips,
    # because the contract refuses out-of-scope tool wording in either
    # polarity.
    def m_v14_screenshot_negation(d):
        d["notes"] = "no screenshot was taken"
        return d
    results.append(_scenario(
        "v14-screenshot-negation", m_v14_screenshot_negation, "V14",
    ))

    # V14 — passive-voice "X was used / called / invoked / queried /
    # launched" tool-claim phrasings for the markers whose canonical
    # form is rare in legitimate static-metadata review prose
    # (``done`` is the canonical of ``D-One``; ``mcp`` and ``browser``
    # rarely appear outside an out-of-scope tool claim). Each MUST
    # fire V14.
    def m_v14_browser_was_used(d):
        d["notes"] = "browser was used to inspect overflow"
        return d
    results.append(_scenario(
        "v14-browser-was-used", m_v14_browser_was_used, "V14",
    ))

    def m_v14_done_was_used(d):
        d["notes"] = "D-One was used for asset generation"
        return d
    results.append(_scenario(
        "v14-done-was-used", m_v14_done_was_used, "V14",
    ))

    def m_v14_mcp_was_used(d):
        d["notes"] = "an MCP server was used at review time"
        return d
    results.append(_scenario(
        "v14-mcp-was-used", m_v14_mcp_was_used, "V14",
    ))

    def m_v14_done_called(d):
        d["notes"] = "D-One was called from the review step"
        return d
    results.append(_scenario(
        "v14-done-called", m_v14_done_called, "V14",
    ))

    def m_v14_done_invoked(d):
        d["notes"] = "D-One was invoked locally"
        return d
    results.append(_scenario(
        "v14-done-invoked", m_v14_done_invoked, "V14",
    ))

    def m_v14_mcp_queried(d):
        d["notes"] = "an MCP was queried for slide layout hints"
        return d
    results.append(_scenario(
        "v14-mcp-queried", m_v14_mcp_queried, "V14",
    ))

    def m_v14_browser_launched(d):
        d["notes"] = "headless browser was launched for the slide"
        return d
    results.append(_scenario(
        "v14-browser-launched", m_v14_browser_launched, "V14",
    ))

    # V14 — "external X was used / called / invoked" phrasings still
    # fire via the original ``service`` / ``api`` / ``endpoint`` /
    # ``host`` qualifiers; the marker+qualifier shape catches both
    # subject-and-verb constructions where the qualifier appears
    # somewhere in the canonical form.
    def m_v14_external_was_used(d):
        d["notes"] = "external host was used for the render"
        return d
    results.append(_scenario(
        "v14-external-was-used", m_v14_external_was_used, "V14",
    ))

    def m_v14_external_called(d):
        d["notes"] = "external API was called during review"
        return d
    results.append(_scenario(
        "v14-external-called", m_v14_external_called, "V14",
    ))

    def m_v14_external_invoked(d):
        d["notes"] = "external endpoint was invoked"
        return d
    results.append(_scenario(
        "v14-external-invoked", m_v14_external_invoked, "V14",
    ))

    # V14 — AI-model claims fire via the bare compound tokens
    # ``aimodel`` / ``languagemodel`` (these compounds do NOT match
    # the canonical form of ``render_model``, so they avoid the
    # false-positive that bare ``model`` + ``used`` would have).
    def m_v14_ai_model(d):
        d["notes"] = "AI model was used to grade contrast"
        return d
    results.append(_scenario(
        "v14-ai-model-was-used", m_v14_ai_model, "V14",
    ))

    def m_v14_language_model(d):
        d["notes"] = "language model was queried for tone"
        return d
    results.append(_scenario(
        "v14-language-model-was-queried", m_v14_language_model, "V14",
    ))

    # V14 — specific AI infra claims still fire via ``model`` +
    # (``api`` / ``inferenc`` / ``llm`` / ``gpt`` / ``judg`` /
    # ``queried``). These probes confirm the AI-tool-specific
    # qualifiers still catch the obvious "model API / LLM / GPT was
    # used" wording.
    def m_v14_model_api_was_used(d):
        d["notes"] = "model API was used during review"
        return d
    results.append(_scenario(
        "v14-model-api-was-used", m_v14_model_api_was_used, "V14",
    ))

    def m_v14_model_llm_called(d):
        d["notes"] = "an LLM and the model api were called"
        return d
    results.append(_scenario(
        "v14-model-llm-called", m_v14_model_llm_called, "V14",
    ))

    # V14 — bare-word "model" plus a generic usage verb. The contract
    # refuses passive-voice "model was used / called / invoked /
    # prompted" tool-claim wording; the \bmodel\b word-boundary check
    # catches the bare "model" noun without matching the underscored
    # render_model compound. These four scenarios are the explicit
    # contract probes from the V14 drift fix.
    def m_v14_bare_model_used(d):
        d["notes"] = "model was used to grade contrast"
        return d
    results.append(_scenario(
        "v14-bare-model-used", m_v14_bare_model_used, "V14",
    ))

    def m_v14_bare_model_called(d):
        d["notes"] = "called the model for a second opinion"
        return d
    results.append(_scenario(
        "v14-bare-model-called", m_v14_bare_model_called, "V14",
    ))

    def m_v14_bare_model_invoked(d):
        d["notes"] = "model was invoked once per slide"
        return d
    results.append(_scenario(
        "v14-bare-model-invoked", m_v14_bare_model_invoked, "V14",
    ))

    def m_v14_bare_model_prompted(d):
        d["notes"] = "the model was prompted with the source body"
        return d
    results.append(_scenario(
        "v14-bare-model-prompted", m_v14_bare_model_prompted, "V14",
    ))

    # Negative-positive: legitimate render_model evidence wording
    # MUST PASS. These are the exact shapes that triggered the
    # over-broad V14 regression: "render_model used by slide X" and
    # passive-voice "render_model was invoked / called / prompted".
    # The bare-word ``\bmodel\b`` check excludes underscored
    # compounds (``_`` is a regex word char, so there is no boundary
    # between ``_`` and ``m`` in ``render_model``), so every one of
    # these passes the gate even though V14 now refuses bare "model
    # was used / called / invoked / prompted" wording.
    def m_safe_render_model_used(d):
        d["notes"] = "render_model used by slide 3 has overflow"
        return d
    results.append(_scenario(
        "safe-render-model-used", m_safe_render_model_used, "",
    ))

    def m_safe_render_model_invoked(d):
        d["notes"] = "render_model was invoked by export_pptx"
        return d
    results.append(_scenario(
        "safe-render-model-invoked", m_safe_render_model_invoked, "",
    ))

    def m_safe_render_model_called(d):
        d["notes"] = "the render_model was called from the export step"
        return d
    results.append(_scenario(
        "safe-render-model-called", m_safe_render_model_called, "",
    ))

    def m_safe_render_model_prompted(d):
        d["notes"] = "the render_model prompted a layout retry"
        return d
    results.append(_scenario(
        "safe-render-model-prompted", m_safe_render_model_prompted, "",
    ))

    # Negative-positive: legitimate layout-terminology wording with
    # ``external`` MUST PASS. The narrowed external qualifier list
    # keeps "external border used in layout" out of the gate.
    def m_safe_external_border(d):
        d["notes"] = "external border used in this layout grid"
        return d
    results.append(_scenario(
        "safe-external-border", m_safe_external_border, "",
    ))

    def m_safe_external_alignment(d):
        d["notes"] = "external alignment guide invoked at top edge"
        return d
    results.append(_scenario(
        "safe-external-alignment", m_safe_external_alignment, "",
    ))

    # Negative-positive: bare 'browser' WITHOUT a qualifier verb does
    # NOT fire V14. Catches a regression that widened the gate to
    # refuse legitimate vocabulary.
    def m_safe_browser_alone(d):
        d["notes"] = "browser font fallback note"
        return d
    results.append(_scenario(
        "safe-browser-alone", m_safe_browser_alone, "",
    ))

    # Negative-positive: bare 'model' alone without any usage verb
    # does NOT fire V14. \bmodel\b matches the bare "model" noun
    # here, but the canonical form carries no
    # used/called/invok/prompted/api/judg/llm/gpt/inferenc/queried
    # qualifier, so neither the canonical-form nor the bare-word
    # branch of V14 fires.
    def m_safe_model_alone(d):
        d["notes"] = "design model layout reference"
        return d
    results.append(_scenario(
        "safe-model-alone", m_safe_model_alone, "",
    ))

    # Negative-positive: bare 'external' alone does NOT fire V14.
    def m_safe_external_alone(d):
        d["notes"] = "external border alignment"
        return d
    results.append(_scenario(
        "safe-external-alone", m_safe_external_alone, "",
    ))

    # Negative-positive: short Sk-Modernist-style font name does NOT
    # trip V12.
    def m_safe_short_sk(d):
        d["notes"] = "uses Sk Modernist family"
        return d
    results.append(_scenario(
        "safe-short-sk-family", m_safe_short_sk, "",
    ))

    # Negative-positive: bare 'public' without a propagation verb does
    # NOT trip V11.
    def m_safe_public_alone(d):
        d["notes"] = "public domain marker note"
        return d
    results.append(_scenario(
        "safe-public-alone", m_safe_public_alone, "",
    ))

    # V1 — load-time refusals exit 2 via ReviewLoadError.
    def _expect_load_error(label: str, path: Path) -> tuple[bool, str]:
        try:
            errors = validate_review(path)
        except ReviewLoadError as exc:
            msg = str(exc)
            if msg.startswith("V1:"):
                return True, f"{label}: refused under V1 (load-time)"
            return False, (
                f"{label}: expected V1 load-time refusal, got {msg!r}"
            )
        return False, (
            f"{label}: expected ReviewLoadError; got errors {errors}"
        )

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        path = tmp / "review.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        results.append(_expect_load_error("v1-non-object", path))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        real = tmp / "real.json"
        real.write_text(json.dumps(_GOOD_REVIEW), encoding="utf-8")
        link = tmp / "link.json"
        link.symlink_to(real)
        results.append(_expect_load_error("v1-symlink", link))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        path = tmp / "missing.json"
        results.append(_expect_load_error("v1-missing-file", path))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        path = tmp / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        results.append(_expect_load_error("v1-bad-json", path))

    failed = [msg for ok, msg in results if not ok]
    for ok, msg in results:
        print(("PASS " if ok else "FAIL ") + msg)
    if failed:
        print(f"\n{len(failed)} self-test scenario(s) failed.")
        return 1
    print(f"\nself-test OK ({len(results)} scenarios)")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only validator for synthetic per-slide visual-review "
            "rubric files. Stdlib-only; no network, no D-One, no Qoder, "
            "no MCP, no model API, no browser, no screenshot."
        )
    )
    parser.add_argument(
        "--review",
        type=Path,
        help="Path to a visual_review JSON file to validate.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run built-in positive + negative scenarios and exit.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if args.review is not None:
            print(
                "error: --review is not compatible with --self-test",
                file=sys.stderr,
            )
            return 2
        return _self_test()

    if args.review is None:
        print(
            "error: --review is required (or pass --self-test)",
            file=sys.stderr,
        )
        return 2

    if not REVIEW_SCHEMA.is_file():
        print(
            f"error: review schema not found at {REVIEW_SCHEMA}",
            file=sys.stderr,
        )
        return 2

    try:
        errors = validate_review(args.review)
    except ReviewLoadError as exc:
        print(f"FAIL: {args.review}", file=sys.stderr)
        print(f"  - {exc}", file=sys.stderr)
        return 2
    if errors:
        print(f"FAIL: {args.review}")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: {args.review} (schema + content gates)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
