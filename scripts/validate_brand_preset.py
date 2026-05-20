#!/usr/bin/env python3
"""Local validator for synthetic brand/design preset files.

Stdlib-only. NETWORK-FREE. NO-D-ONE. NO-Qoder. NO model API.
NO PPTX export. NO image generation. NO telemetry.

Given an explicit ``--preset <path>``, this script schema-validates the
file against ``schemas/brand_preset.schema.json`` AND enforces a small
set of content gates documented in
``references/brand-preset-contract.md`` under "Validator":

  P1 readable_json_object (load-time precheck — exit 2 if it fires)
    - preset file must exist as a regular non-symlink file;
    - bytes must be readable as UTF-8;
    - bytes must parse as JSON;
    - the parsed JSON must be a top-level OBJECT (a list / scalar root
      is refused up front so the diagnostic is unambiguous).
    Because this precheck has to succeed before any structural or
    content gate can even run, a P1 failure exits 2 (invocation /
    file / parse error), not 1 (gate failure). The diagnostic line is
    still prefixed ``P1:`` so the rule cited in the docstring matches
    the diagnostic the operator sees.

  P2 schema_subset_valid
    - validates against ``schemas/brand_preset.schema.json`` under the
      same stdlib subset that ``scripts/validate_artifacts.py`` applies.

  P3 runtime_status_is_non_runtime_contract
    - ``runtime_status`` MUST equal the literal
      ``"non_runtime_contract"``. The schema enum already enforces
      this; the runtime gate mirrors it so the diagnostic is the same
      regardless of which side detects the divergence. The contract is
      shape-only today (no script reads a preset as runtime state) —
      a future runtime path MUST flip this literal in a paired contract
      change, not silently re-interpret the existing one.

  P4 no_real_brand_wording
    - no string field, once lower-cased and stripped of non-alphanumeric
      characters, may CONTAIN any token from the small real-brand
      denylist. The denylist is intentionally narrow — it names the
      brands the contract explicitly forbids in its scope (Google /
      Anthropic) plus a handful of other commonly-recognised brand
      tokens, so an authoring slip like ``display_name = "Google
      Refresh"`` or ``preset_id = "synthetic_anthropic_v1"`` fails
      closed. The denylist is a defense-in-depth gate, NOT a complete
      trademark check; the real protection is the
      ``preset_id`` pattern (``^synthetic_...``) and the
      ``display_name`` pattern (no trademark glyphs / dot / ampersand)
      at the schema layer.

  P5 no_url_or_uri_scheme
    - no string field may carry an RFC 3986 URI-scheme prefix
      (``http:``, ``https:``, ``file:``, ``data:``, ``s3:``, ``ftp:``,
      ``mailto:``, ``javascript:``, ...). The check is the same shape
      ``scripts/validate_scaffold.local_path_is_safe`` uses, so a
      single tightening of either consumer closes the corresponding
      gap in the other. The schema patterns already refuse this for
      structured fields; this gate is the belt-and-braces against a
      future schema relaxation.

  P6 no_unsafe_path_shape
    - no string field may start with ``/`` (POSIX absolute), ``\\``
      (leading backslash), or ``//`` (protocol-relative), AND no
      string field may contain a ``..`` path segment when split on
      ``/`` or ``\\``. Mirrors ``local_path_is_safe`` directly.

  P7 no_public_upload_wording
    - no string field, once lower-cased AND stripped of every
      non-alphanumeric character, may contain the marker ``public`` AND
      ALSO contain any of the propagation-verb / surface markers
      ``upload``, ``share``, ``sharing``, ``url``, ``link``, ``post``,
      ``publish``, ``distribut``, or ``host``. Same canonical-form
      match shape as ``scripts/validate_source_image_assets.py`` G12 —
      the marker + verb combination catches every separator / word-
      order / morphology / intervening-token permutation in one rule.
      The brand-preset list is a SUPERSET of G12 because preset notes
      may carry public-hosting wording (``public hosting enabled`` /
      ``host publicly`` / ``public hosted asset``) that source-image
      assets G12 does not see; the ``host`` substring catches
      ``host`` / ``hosted`` / ``hosting`` / ``hosts`` in one entry.

  P8 no_image_generation_prompt_wording
    - no string field, once lower-cased AND stripped of every
      non-alphanumeric character, may contain ANY of the image-
      generation verb markers ``imagegen``, ``imagegeneration``,
      ``generateimage``, ``texttoimage``, ``promptimage``,
      ``aiimage``, ``aiimagery``, ``midjourney``, ``stable``,
      ``stablediffusion``, ``dalle``, ``firefly``, ``imagen``, OR
      ``done`` together with any of ``image`` / ``asset`` /
      ``render`` (catches ``d_one_image`` / ``done_image`` /
      ``d_one_render_asset`` etc.). A preset is a SHAPE document; it
      MUST NOT carry an image-generation prompt fragment.

  P9 no_raw_source_or_confidential_wording
    - no string field, once lower-cased AND stripped of every
      non-alphanumeric character, may contain ANY of the confidential-
      content markers ``confidential``, ``proprietary``,
      ``internalonly``, ``ndaprotected``, ``customername``,
      ``accountid``, ``ssn``, ``creditcard``, OR the marker ``raw``
      together with any of ``source`` / ``content`` / ``paragraph`` /
      ``excerpt`` (catches ``raw_source`` / ``raw_source_paragraph`` /
      ``raw_content`` etc.). A preset is a SHAPE document and MUST NOT
      carry raw source body text or business-confidential wording.

  P10 string_field_shapes_runtime
    - every string field MUST be byte-identical to itself after a
      ``str.strip()`` round-trip (no surrounding whitespace). The
      schema patterns refuse most whitespace shapes already; this is
      defense-in-depth against a future schema relaxation.

  P11 no_credential_shaped_wording
    - no string field, once lower-cased AND stripped of every
      non-alphanumeric character, may contain ANY of the credential-
      shape compound tokens ``apikey``, ``apitoken``, ``accesstoken``,
      ``authtoken``, ``csrftoken``, ``idtoken``, ``jwttoken``,
      ``oauthtoken``, ``refreshtoken``, ``sessiontoken``, ``secret``,
      ``bearer``, ``password``, OR the bare marker ``token``
      (catches ``api_key`` / ``API-Key`` / ``access_token`` /
      ``Authorization: Bearer`` / ``client_secret`` / ``PASSWORD`` /
      ``token=value`` / ``token placeholder`` etc.); AND no string
      field's raw form may match the regex
      ``\bsk-[A-Za-z0-9_\-]{16,}`` (case-insensitive — the
      ``sk-``-prefixed OpenAI / Anthropic API-key shape, where the
      16-char minimum after ``sk-`` excludes short font / family
      names like ``Sk-Modernist`` while catching ``sk-``-prefixed
      keys in the OpenAI / Anthropic format (40+ char alphanumeric
      tail). Other-provider key prefixes (e.g. Stripe ``sk_test_``
      with an underscore, GitHub ``ghp_``, Slack ``xoxb-``) are NOT
      covered by this regex). Bare ``token`` is a marker on its own
      — the design-system vocabulary that legitimately uses ``token``
      (``palette_tokens`` / ``typography_tokens``) appears as schema
      KEYS, which the validator does not walk; preset string VALUES
      have no contract reason to carry the word ``token`` outside a
      credential context, so the bare substring is refused. The
      qualifier-prefixed compounds above are kept first in the
      iteration order for diagnostic specificity (``api_token`` ->
      diagnostic names ``apitoken`` rather than the bare ``token``).
      A preset is a SHAPE document and MUST NOT carry credential
      material.

Out of scope (and explicitly refused, not implemented):

  - calling D-One / Qoder / MCP / any image generator / model API /
    image search / public network / external service;
  - mutating the preset or any workspace file (read-only validator);
  - any runtime application of preset values onto a deck (no
    projection helper ships; no script in this repo reads a preset);
  - any chart rendering / PPTX export / SVG generation behavior.

Exit codes:
  0  every gate passed (or --self-test scenarios all behaved as expected).
  1  one or more structural / content gates failed (P2..P11).
  2  invocation / file / parse error. Covers: missing or incompatible
     CLI flags; schema file missing on disk; AND every P1 precheck
     failure (preset path missing / is a symlink / is not a regular
     file / unreadable / not valid UTF-8 / not valid JSON / not a
     top-level object).

CLI:
  python3 scripts/validate_brand_preset.py --preset <path-to-preset.json>
  python3 scripts/validate_brand_preset.py --self-test
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

PRESET_SCHEMA = SCHEMAS_DIR / "brand_preset.schema.json"

# RFC 3986 scheme: ALPHA *( ALPHA / DIGIT / "+" / "-" / "." ) ":"
# Used in two shapes:
#   - anchored at start: refuses ``file:something`` / ``mailto:a@b``
#     style values where the URI is the WHOLE field;
#   - embedded URL pattern: refuses ``... see https://x ...`` style
#     wording embedded inside a freeform string like ``notes``.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_EMBEDDED_URL = re.compile(
    r"\b(?:https?|s3|ftp|file|mailto|javascript)://[^\s\"'<>]+|"
    r"\b(?:data|mailto|javascript):[A-Za-z0-9+\-/.,;@%_]+",
    flags=re.IGNORECASE,
)

# Strips every char that is not [a-z0-9] AFTER lower-casing — so
# ``_``, ``.``, ``-``, ``/``, ``\``, and any future separator
# collapse to the empty string. Mirrors validate_source_image_assets
# G12 to keep the canonical form consistent across validators.
_NON_ALPHANUM = re.compile(r"[^a-z0-9]")


# Real-brand denylist. Intentionally narrow: the two brands the
# contract explicitly names as out-of-scope (Google, Anthropic) plus a
# small handful of commonly-recognised brand tokens so a slip in
# preset_id / display_name / notes fails closed. NOT a complete
# trademark check — the real protection is the schema patterns.
_REAL_BRAND_TOKENS: tuple[str, ...] = (
    "google",
    "anthropic",
    "claude",
    "openai",
    "chatgpt",
    "microsoft",
    "powerpoint",
    "apple",
    "keynote",
    "adobe",
    "figma",
)

# Public-upload markers — SUPERSET of
# validate_source_image_assets._PUBLIC_MARKER + _PROPAGATION_VERB_MARKERS.
# The brand-preset list adds ``host`` as an 8th propagation marker so
# preset notes that say ``public hosting enabled`` / ``host publicly`` /
# ``public hosted asset`` all fail closed. The ``host`` substring catches
# ``host`` / ``hosted`` / ``hosting`` / ``hosts`` in one entry; the
# ``public`` marker still has to co-occur for P7 to fire, so a bare
# ``hostname`` reference without ``public`` does not trip the gate. The
# divergence from G12 is intentional: source-image-assets G12 does not
# see preset-style author notes about public hosting.
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

# Image-generation prompt wording. The first group is full compound
# tokens (no second marker required); the second group is the
# combination of a tool-shape root and an asset noun.
_IMAGE_GEN_COMPOUND_TOKENS: tuple[str, ...] = (
    "imagegen",
    "imagegeneration",
    "generateimage",
    "texttoimage",
    "promptimage",
    "aiimage",
    "aiimagery",
    "midjourney",
    "stable",
    "stablediffusion",
    "dalle",
    "firefly",
    "imagen",
)
_DONE_MARKER = "done"
_IMAGE_GEN_ASSET_NOUNS: tuple[str, ...] = (
    "image",
    "asset",
    "render",
)

# Credential-shaped tokens (canonical-form match). Each entry, after
# canonicalizing the candidate string to lower-case ASCII alphanumeric,
# is a stable substring that survives every separator-and-case variant:
#   "api_key" / "API-Key" / "API Key" / "apiKey" -> "apikey"
#   "access_token" / "Access-Token" / "Access Token" -> "accesstoken"
#   "Authorization: Bearer" / "BEARER " / "bearer-" -> "bearer"
#   "client_secret" / "Secret-Value" / "SECRET" -> "secret"
#   "Password:" / "PASSWORD " / "pass-word" -> "password"
#   "token=value" / "token placeholder" / "TOKEN" -> "token"
# The canonical form only handles separator-stripping and lowercasing —
# NOT morphology / stemming / lemmatisation. Pluralised forms (e.g.
# "api_tokens" -> "apitokens") still match by substring against
# "apitoken", which is incidental coverage, not a designed feature.
# Bare ``token`` IS in this list — preset string values have no
# contract reason to carry the word ``token`` outside a credential
# context. The design-system vocabulary that legitimately uses the
# word (``palette_tokens`` / ``typography_tokens``) appears only as
# schema KEYS, and ``_walk_strings`` walks VALUES only, so dict-key
# usage cannot trip this gate. The qualifier-prefixed compounds
# (``apitoken`` / ``accesstoken`` / ``authtoken`` / ``csrftoken`` /
# ``idtoken`` / ``jwttoken`` / ``oauthtoken`` / ``refreshtoken`` /
# ``sessiontoken``) are KEPT FIRST in iteration order so the
# diagnostic on a value like ``access_token`` names the specific
# compound (``accesstoken``) rather than the bare ``token`` —
# diagnostic specificity only; both shapes would fire either way.
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

# Shape-only match for ``sk-``-prefixed API keys in the OpenAI /
# Anthropic format. The RAW string is searched (not canonical form)
# because the literal ``sk-`` prefix and its long alphanumeric tail
# are the diagnostic shape; canonicalising would strip the hyphen and
# collapse the prefix into surrounding text. The 16-char minimum
# after ``sk-`` excludes short font / family names like
# ``Sk-Modernist`` (9 chars after ``sk-``) while matching the OpenAI
# (``sk-`` + ~48 char tail) and Anthropic (``sk-ant-api03-`` + ~93
# char tail) shapes. Other-provider credential prefixes are NOT
# covered by this regex — Stripe ``sk_test_`` / ``sk_live_`` use an
# underscore not a hyphen, GitHub ``ghp_`` / ``gho_`` / Slack
# ``xoxb-`` / ``xoxp-`` etc. use entirely different prefixes — so
# this gate is intentionally narrow to the user-prompt-scoped
# ``sk-...`` shape.
_SK_PREFIX_KEY = re.compile(
    r"\bsk-[A-Za-z0-9_\-]{16,}",
    flags=re.IGNORECASE,
)

# Confidential / raw-source markers.
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


def _canonical(value: str) -> str:
    """Lower-case ``value`` and drop every non-alphanumeric character."""
    return _NON_ALPHANUM.sub("", value.lower())


def _has_uri_scheme(s: str) -> bool:
    """True if ``s`` starts with a URI scheme OR contains an embedded
    URL (https://, http://, file://, s3://, ftp://, data:, mailto:,
    javascript:). Catches both ``file:thing`` style whole-value URIs
    and ``see https://x for context`` style embedded URLs."""
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


class PresetLoadError(Exception):
    """Raised by ``_load_preset`` when the P1 precheck fails. Carries
    a single ``P1: ...`` diagnostic line. ``main()`` maps this to
    exit 2 (invocation / file / parse error); the per-gate exit-1
    path never sees it."""


def _load_preset(preset_path: Path) -> dict:
    """P1 — file exists, is a regular non-symlink file, parses as JSON,
    is a top-level object. Raises ``PresetLoadError`` with a ``P1:``
    diagnostic for any precheck failure; returns the parsed object on
    success. UTF-8 is required (the schema and the rest of the repo
    are UTF-8 throughout)."""
    if preset_path.is_symlink():
        raise PresetLoadError(
            f"P1: preset path is a symlink (refused): {preset_path}"
        )
    if not preset_path.exists():
        raise PresetLoadError(
            f"P1: preset path does not exist: {preset_path}"
        )
    if not preset_path.is_file():
        raise PresetLoadError(
            f"P1: preset path is not a regular file: {preset_path}"
        )
    try:
        raw = preset_path.read_bytes()
    except OSError as exc:
        raise PresetLoadError(
            f"P1: cannot read preset {preset_path}: {exc}"
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PresetLoadError(
            f"P1: preset is not valid UTF-8: {exc}"
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PresetLoadError(
            f"P1: preset is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise PresetLoadError(
            f"P1: top-level JSON value is {type(data).__name__}, "
            f"expected object"
        )
    return data


def _gate_schema_subset_valid(data: dict) -> list[str]:
    """P2 — schema validation under the stdlib subset."""
    errors: list[str] = []
    try:
        schema = json.loads(PRESET_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"P2: cannot read schema {PRESET_SCHEMA}: {exc}"]
    _validate(data, schema, "<root>", errors)
    return [f"P2: {e}" for e in errors]


def _gate_runtime_status(data: dict) -> list[str]:
    """P3 — runtime_status MUST equal 'non_runtime_contract'."""
    value = data.get("runtime_status")
    if value != "non_runtime_contract":
        return [
            f"P3: runtime_status must equal 'non_runtime_contract' "
            f"(got {value!r}); this contract is shape-only today"
        ]
    return []


def _gate_no_real_brand_wording(data: dict) -> list[str]:
    """P4 — real-brand denylist on canonical form of every string."""
    errors: list[str] = []
    for path, value in _walk_strings(data):
        canon = _canonical(value)
        for token in _REAL_BRAND_TOKENS:
            if token in canon:
                errors.append(
                    f"P4: {path}: value {value!r} contains real-brand "
                    f"token {token!r} (canonical form: {canon!r})"
                )
                break
    return errors


def _gate_no_url_or_uri_scheme(data: dict) -> list[str]:
    errors: list[str] = []
    for path, value in _walk_strings(data):
        if _has_uri_scheme(value):
            errors.append(
                f"P5: {path}: value {value!r} carries a URI-scheme prefix"
            )
    return errors


def _gate_no_unsafe_path_shape(data: dict) -> list[str]:
    errors: list[str] = []
    for path, value in _walk_strings(data):
        if _starts_with_unsafe_path_prefix(value):
            errors.append(
                f"P6: {path}: value {value!r} starts with an unsafe "
                f"path prefix ('/', '\\\\', or '//')"
            )
            continue
        if _contains_parent_segment(value):
            errors.append(
                f"P6: {path}: value {value!r} contains a '..' segment"
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
                f"P7: {path}: value {value!r} combines 'public' with a "
                f"propagation verb (canonical form: {canon!r})"
            )
    return errors


def _gate_no_image_generation_prompt_wording(data: dict) -> list[str]:
    errors: list[str] = []
    for path, value in _walk_strings(data):
        canon = _canonical(value)
        matched: str | None = None
        for token in _IMAGE_GEN_COMPOUND_TOKENS:
            if token in canon:
                matched = token
                break
        if matched is None and _DONE_MARKER in canon and any(
            noun in canon for noun in _IMAGE_GEN_ASSET_NOUNS
        ):
            matched = "done + image/asset/render"
        if matched is not None:
            errors.append(
                f"P8: {path}: value {value!r} carries image-generation "
                f"wording ({matched}; canonical form: {canon!r})"
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
                f"P9: {path}: value {value!r} carries confidential / "
                f"raw-source wording ({matched}; canonical form: "
                f"{canon!r})"
            )
    return errors


def _gate_string_field_shapes_runtime(data: dict) -> list[str]:
    errors: list[str] = []
    for path, value in _walk_strings(data):
        if value != value.strip():
            errors.append(
                f"P10: {path}: value {value!r} has surrounding "
                f"whitespace"
            )
    return errors


def _gate_no_credential_shaped_wording(data: dict) -> list[str]:
    """P11 — credential-shaped tokens in canonical form OR a literal
    ``sk-`` prefixed API-key shape in the raw string. The compound
    token list (canonical-form match) and the ``sk-`` pattern (raw-
    string match) are evaluated independently per-field so the
    diagnostic names which shape fired."""
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
                f"P11: {path}: value {value!r} carries credential-"
                f"shaped wording ({matched!r}; canonical form: "
                f"{canon!r})"
            )
            continue
        if _SK_PREFIX_KEY.search(value):
            errors.append(
                f"P11: {path}: value {value!r} carries an sk- "
                f"prefixed API-key shape"
            )
    return errors


GATES = (
    ("P3", _gate_runtime_status),
    ("P4", _gate_no_real_brand_wording),
    ("P5", _gate_no_url_or_uri_scheme),
    ("P6", _gate_no_unsafe_path_shape),
    ("P7", _gate_no_public_upload_wording),
    ("P8", _gate_no_image_generation_prompt_wording),
    ("P9", _gate_no_raw_source_or_confidential_wording),
    ("P10", _gate_string_field_shapes_runtime),
    ("P11", _gate_no_credential_shaped_wording),
)


def validate_preset(preset_path: Path) -> list[str]:
    """Run P2..P11 against the preset. Raises ``PresetLoadError`` for
    P1 precheck failures (the caller maps those to exit 2). Returns
    the list of gate-failure diagnostics for P2..P11 (caller maps a
    non-empty list to exit 1)."""
    data = _load_preset(preset_path)
    errors: list[str] = []
    errors.extend(_gate_schema_subset_valid(data))
    for _name, gate in GATES:
        errors.extend(gate(data))
    return errors


# ----------------------------------------------------------------------
# --self-test
# ----------------------------------------------------------------------

_GOOD_PRESET: dict[str, Any] = {
    "schema_version": "1",
    "preset_id": "synthetic_self_test",
    "display_name": "Synthetic Self Test",
    "runtime_status": "non_runtime_contract",
    "palette_tokens": {
        "primary":    "#2A2A2A",
        "secondary":  "#5A5A5A",
        "accent":     "#888888",
        "background": "#FFFFFF",
        "text":       "#1A1A1A",
    },
    "typography_tokens": {
        "heading": {"font_family": "Calibri, Arial, sans-serif", "size_pt": 28},
        "body":    {"font_family": "Calibri, Arial, sans-serif", "size_pt": 14},
    },
    "spacing_style": "balanced",
    "radius_style": "soft",
    "chart_style_hints": {
        "series_palette_role": "primary_accent",
        "emphasis": "moderate",
    },
    "allowed_layout_mood": ["minimal", "analytical"],
    "notes": "Synthetic self-test preset.",
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
    _GOOD_PRESET and returns the candidate. ``expected_gates`` is
    either ``""`` (the scenario MUST pass), a single gate prefix like
    ``"P5"``, or a tuple of gate prefixes the scenario MUST fire
    AT LEAST one of. Tuple form is for defense-in-depth scenarios
    where the schema and a runtime gate both fire (e.g. flipping
    ``runtime_status`` to a non-allowed literal trips P2 AND P3)."""
    candidate = json.loads(json.dumps(_GOOD_PRESET))
    candidate = mutate(candidate)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        path = _write_tmp(candidate, tmp, "preset.json")
        errors = validate_preset(path)
    if not expected_gates:
        if errors:
            return False, (
                f"{label}: expected PASS but got errors: {errors}"
            )
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
        # Defense-in-depth allowed; we only refuse the scenario when
        # NONE of the expected gates fired. Extra fires are noted.
        return True, (
            f"{label}: refused under {sorted(fired & set(expected))} "
            f"(also fired: {sorted(extra)})"
        )
    return True, f"{label}: refused under {sorted(fired)}"


def _self_test() -> int:
    results: list[tuple[bool, str]] = []

    # Positive baseline.
    results.append(_scenario("baseline-good", lambda d: d, ""))

    # P2 — schema violation (missing required field).
    def m_p2(d):
        d.pop("palette_tokens")
        return d
    results.append(_scenario("p2-missing-required", m_p2, "P2"))

    # P3 — runtime_status flipped to a non-allowed literal. Both the
    # schema enum (P2) AND the runtime gate (P3) fire; we accept
    # either as evidence of fail-closed behavior.
    def m_p3(d):
        d["runtime_status"] = "runtime_applied"
        return d
    results.append(_scenario("p3-runtime-applied", m_p3, ("P2", "P3")))

    # P4 — real-brand wording in display_name.
    def m_p4(d):
        d["display_name"] = "Google Refresh"
        return d
    results.append(_scenario("p4-real-brand", m_p4, "P4"))

    # P5 — URL wording in notes.
    def m_p5(d):
        d["notes"] = "see https://example/notes for context"
        return d
    results.append(_scenario("p5-url", m_p5, "P5"))

    # P6 — absolute path wording in notes.
    def m_p6_abs(d):
        d["notes"] = "/etc/passwd should not be referenced"
        return d
    results.append(_scenario("p6-absolute-path", m_p6_abs, "P6"))

    # P6 — parent traversal in notes.
    def m_p6_parent(d):
        d["notes"] = "uses ../../secrets path"
        return d
    results.append(_scenario("p6-parent-segment", m_p6_parent, "P6"))

    # P7 — public-upload wording.
    def m_p7(d):
        d["notes"] = "auto public upload after build"
        return d
    results.append(_scenario("p7-public-upload", m_p7, "P7"))

    # P8 — image-generation wording (compound token).
    def m_p8(d):
        d["notes"] = "uses midjourney sketch"
        return d
    results.append(_scenario("p8-imagegen-compound", m_p8, "P8"))

    # P8 — done + image combination.
    def m_p8b(d):
        d["notes"] = "uses done image hero"
        return d
    results.append(_scenario("p8-done-image", m_p8b, "P8"))

    # P9 — confidential marker.
    def m_p9(d):
        d["notes"] = "marked confidential, internal"
        return d
    results.append(_scenario("p9-confidential", m_p9, "P9"))

    # P9 — raw + source combination.
    def m_p9b(d):
        d["notes"] = "carries raw source excerpt verbatim"
        return d
    results.append(_scenario("p9-raw-source", m_p9b, "P9"))

    # P10 — surrounding whitespace in the freeform ``notes`` field.
    # The schema's notes only has maxLength, so the whitespace gate
    # is the only line of defense. Structured fields like preset_id /
    # display_name already refuse whitespace at the schema pattern
    # layer; testing the only field where P10 is load-bearing.
    def m_p10(d):
        d["notes"] = "  trailing whitespace  "
        return d
    results.append(_scenario("p10-whitespace", m_p10, "P10"))

    # P7 — public-hosting wording probes. ``host`` is the 8th
    # propagation-verb marker (added on top of G12's set) and combines
    # with ``public`` in three exact authoring shapes the user prompt
    # named: ``public hosting enabled``, ``host publicly``, and
    # ``public hosted asset``. Each MUST fire P7 (the marker + verb
    # rule). Bare ``host`` without ``public`` is left to safe-host-
    # alone below to confirm the gate still requires co-occurrence.
    def m_p7_public_hosting(d):
        d["notes"] = "public hosting enabled"
        return d
    results.append(_scenario("p7-public-hosting", m_p7_public_hosting, "P7"))

    def m_p7_host_publicly(d):
        d["notes"] = "host publicly"
        return d
    results.append(_scenario("p7-host-publicly", m_p7_host_publicly, "P7"))

    def m_p7_public_hosted_asset(d):
        d["notes"] = "public hosted asset"
        return d
    results.append(_scenario(
        "p7-public-hosted-asset", m_p7_public_hosted_asset, "P7"
    ))

    # P11 — one direct probe per credential family in the user-prompt
    # scope (``api_key``, ``secret``, ``token``, ``bearer``, ``sk-...``,
    # ``password``). Each probe carries credential wording in the
    # freeform ``notes`` field (the only field where structured
    # patterns leave room for free-form strings) and MUST fire P11.
    # The ``p11-auth-token`` probe exercises the ``authtoken``
    # qualifier-prefixed compound specifically (diagnostic specificity);
    # the ``p11-token-bare`` / ``p11-token-placeholder`` / ``p11-token-
    # equals`` / ``p11-api-key-equals`` probes are the exact strings
    # the user prompt named and MUST fire P11 against the bare
    # ``token`` marker (and, for the api_key probe, both the
    # ``apikey`` compound AND the ``sk-`` raw-string regex).
    def m_p11_api_key(d):
        d["notes"] = "store api_key here"
        return d
    results.append(_scenario("p11-api-key", m_p11_api_key, "P11"))

    def m_p11_secret(d):
        d["notes"] = "client secret value"
        return d
    results.append(_scenario("p11-secret", m_p11_secret, "P11"))

    def m_p11_auth_token(d):
        d["notes"] = "auth token placeholder"
        return d
    results.append(_scenario("p11-auth-token", m_p11_auth_token, "P11"))

    def m_p11_bearer(d):
        d["notes"] = "bearer credential note"
        return d
    results.append(_scenario("p11-bearer", m_p11_bearer, "P11"))

    def m_p11_sk_prefix(d):
        d["notes"] = "key is sk-abcdef0123456789xyz"
        return d
    results.append(_scenario("p11-sk-prefix", m_p11_sk_prefix, "P11"))

    def m_p11_password(d):
        d["notes"] = "password placeholder"
        return d
    results.append(_scenario("p11-password", m_p11_password, "P11"))

    def m_p11_token_bare(d):
        d["notes"] = "token"
        return d
    results.append(_scenario("p11-token-bare", m_p11_token_bare, "P11"))

    def m_p11_token_placeholder(d):
        d["notes"] = "token placeholder"
        return d
    results.append(_scenario(
        "p11-token-placeholder", m_p11_token_placeholder, "P11"
    ))

    def m_p11_token_equals(d):
        d["notes"] = "token=value"
        return d
    results.append(_scenario(
        "p11-token-equals", m_p11_token_equals, "P11"
    ))

    def m_p11_api_key_equals_sk(d):
        d["notes"] = "api_key = sk-test-1234567890abcdef"
        return d
    results.append(_scenario(
        "p11-api-key-equals-sk", m_p11_api_key_equals_sk, "P11"
    ))

    def m_p11_secret_colon(d):
        d["notes"] = "secret: value"
        return d
    # ``secret: value`` also matches the P5 URI-scheme prefix shape
    # (``secret:`` is a syntactically valid scheme prefix), so the
    # scenario accepts EITHER gate firing — both are fail-closed
    # evidence and P11 is the contract gate this probe is named for.
    results.append(_scenario(
        "p11-secret-colon", m_p11_secret_colon, ("P5", "P11")
    ))

    def m_p11_bearer_token_wording(d):
        d["notes"] = "bearer token wording"
        return d
    results.append(_scenario(
        "p11-bearer-token-wording", m_p11_bearer_token_wording, "P11"
    ))

    def m_p11_password_equals(d):
        d["notes"] = "password=value"
        return d
    results.append(_scenario(
        "p11-password-equals", m_p11_password_equals, "P11"
    ))

    # Negative-positive: a short ``Sk-Modernist``-style font-family
    # mention in notes (only 9 chars after ``sk-``) must NOT fire P11
    # — the sk-pattern threshold is 16+ chars after ``sk-`` to avoid
    # tripping on legitimate font / family naming.
    def m_safe_short_sk(d):
        d["notes"] = "uses Sk Modernist family"
        return d
    results.append(_scenario("safe-short-sk-family", m_safe_short_sk, ""))

    # Negative-positive: a value like "author note" must NOT fire P11
    # even though it canonicalises to include ``auth``; the compound
    # ``authtoken`` requires ``auth`` and ``token`` to be contiguous,
    # which "author note" violates (``or`` sits between the halves),
    # and the bare-``token`` marker is not present either ("author
    # note from team" -> "authornotefromteam" — no ``token``).
    def m_safe_author(d):
        d["notes"] = "author note from team"
        return d
    results.append(_scenario("safe-author-note", m_safe_author, ""))

    # Negative-positive: a sibling preset with display_name that
    # legitimately contains the substring "public" (e.g. "public
    # domain marker") should NOT trip P7 because no propagation-verb
    # marker (including the new ``host``) is present.
    def m_safe_public(d):
        d["notes"] = "public domain marker note"
        return d
    results.append(_scenario("safe-public-alone", m_safe_public, ""))

    # Negative-positive: a preset whose notes use the bare word
    # "share" without "public" should also pass P7.
    def m_safe_share(d):
        d["notes"] = "share team summary"
        return d
    results.append(_scenario("safe-share-alone", m_safe_share, ""))

    # Negative-positive: a bare ``hostname`` reference WITHOUT
    # ``public`` must NOT trip P7 — the marker + verb rule requires
    # co-occurrence, so the new ``host`` propagation marker still
    # only fires when ``public`` is also present.
    def m_safe_host_alone(d):
        d["notes"] = "hostname reference for layout note"
        return d
    results.append(_scenario("safe-host-alone", m_safe_host_alone, ""))

    # P1 — non-object root. P1 raises PresetLoadError now (exit 2
    # at main); the self-test treats that as the expected outcome
    # for this scenario.
    def _expect_load_error(label: str, path: Path) -> tuple[bool, str]:
        try:
            errors = validate_preset(path)
        except PresetLoadError as exc:
            msg = str(exc)
            if msg.startswith("P1:"):
                return True, f"{label}: refused under P1 (load-time)"
            return False, (
                f"{label}: expected P1 load-time refusal, got {msg!r}"
            )
        return False, (
            f"{label}: expected PresetLoadError; got errors {errors}"
        )

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        path = tmp / "preset.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        results.append(_expect_load_error("p1-non-object", path))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        real = tmp / "real.json"
        real.write_text(json.dumps(_GOOD_PRESET), encoding="utf-8")
        link = tmp / "link.json"
        link.symlink_to(real)
        results.append(_expect_load_error("p1-symlink", link))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        path = tmp / "missing.json"
        results.append(_expect_load_error("p1-missing-file", path))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        path = tmp / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        results.append(_expect_load_error("p1-bad-json", path))

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
            "Read-only validator for synthetic brand/design preset files. "
            "Stdlib-only; no network, no D-One, no model API."
        )
    )
    parser.add_argument(
        "--preset",
        type=Path,
        help="Path to a brand_preset JSON file to validate.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run built-in positive + negative scenarios and exit.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if args.preset is not None:
            print(
                "error: --preset is not compatible with --self-test",
                file=sys.stderr,
            )
            return 2
        return _self_test()

    if args.preset is None:
        print("error: --preset is required (or pass --self-test)",
              file=sys.stderr)
        return 2

    if not PRESET_SCHEMA.is_file():
        print(
            f"error: preset schema not found at {PRESET_SCHEMA}",
            file=sys.stderr,
        )
        return 2

    try:
        errors = validate_preset(args.preset)
    except PresetLoadError as exc:
        print(f"FAIL: {args.preset}", file=sys.stderr)
        print(f"  - {exc}", file=sys.stderr)
        return 2
    if errors:
        print(f"FAIL: {args.preset}")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: {args.preset} (schema + content gates)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
