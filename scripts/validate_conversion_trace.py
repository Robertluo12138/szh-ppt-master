#!/usr/bin/env python3
"""Local validator for synthetic PPTX conversion-trace report files.

Stdlib-only. NETWORK-FREE. NO-D-ONE. NO-Qoder. NO model API.
NO PPTX export. NO image generation. NO telemetry.

The conversion-trace contract recognises exactly two writers today:
the SHAPE-only baseline (``pipeline_status="future_contract_only"`` —
committed example fixtures and hand-authored shape probes) AND the
paired-contract runtime path that ``scripts/export_pptx.py`` follows
when invoked with ``--trace-out`` (``pipeline_status=
"runtime_emitted_by_export_pptx"``). No other writer / reader is
allowed without another paired contract change in the schema, here,
and in ``references/conversion-trace-contract.md``. This validator
gates a candidate trace JSON against
``schemas/conversion_trace.schema.json`` plus a small set of content
gates documented in ``references/conversion-trace-contract.md``.

Given an explicit ``--trace <path>``, this script schema-validates the
file AND enforces the following gates:

  T1 readable_json_object (load-time precheck — exit 2 if it fires)
    - trace file must exist as a regular non-symlink file;
    - bytes must be readable as UTF-8;
    - bytes must parse as JSON;
    - the parsed JSON must be a top-level OBJECT.

  T2 schema_subset_valid
    - validates against ``schemas/conversion_trace.schema.json`` under
      the same stdlib subset that ``scripts/validate_artifacts.py``
      applies (no ``$ref`` / ``oneOf`` / ``format``).

  T3 pipeline_status_is_in_closed_enum
    - ``pipeline_status`` MUST be one of the closed two-literal set
      ``{"future_contract_only", "runtime_emitted_by_export_pptx"}``.
      The schema enum already enforces this; the runtime gate mirrors
      it so the diagnostic is the same regardless of which side detects
      the divergence. Adding a third writer requires another paired
      contract change in the schema, here, and in
      ``references/conversion-trace-contract.md``.

  T4 ids_are_synthetic
    - ``trace_id`` / ``deck.deck_id`` / ``generated_by.name`` MUST each
      match the literal ``^synthetic_...`` prefix shape. The schema
      patterns already enforce this; the runtime gate re-asserts it so
      a future schema relaxation does not silently let a non-synthetic
      id through.

  T5 reason_code_consistency
    - For every record: when ``status == "editable"`` the ``reason_code``
      MUST be ``null``; when ``status in {"rejected", "degraded",
      "skipped"}`` the ``reason_code`` MUST be a non-null string drawn
      from the closed enum in the schema. The schema's enum allows
      ``null`` OR any of the reason-code strings; T5 enforces the
      pairing.

  T6 records_unique_primitive_per_slide
    - Every (``slide_index``, ``primitive_id``) tuple MUST be unique
      across all records. A duplicate would mean the same primitive
      was traced twice for the same slide.

  T7 summary_counts_match_records
    - ``summary.editable_count`` / ``rejected_count`` / ``degraded_count``
      / ``skipped_count`` MUST equal the actual per-status totals
      computed from ``records``. A trace whose summary disagrees with
      its own records is refused.

  T8 deck_slide_count_envelope
    - ``deck.slide_count`` MUST be greater than or equal to the maximum
      ``record.slide_index`` (i.e. the deck contains at least as many
      slides as the trace touches). A trace that names slide 5 but
      declares ``slide_count = 3`` is refused.

  T9 deck_layouts_envelope
    - Every ``record.slide_layout`` MUST appear in
      ``deck.layouts_attempted``. The deck-level allow-list is the
      authoritative set of layouts this trace describes; a record that
      names a layout not in that set is refused.

  T10 no_url_or_uri_scheme
    - No string field may carry an RFC 3986 URI-scheme prefix
      (``http:``, ``https:``, ``file:``, ``data:``, ``s3:``, ``ftp:``,
      ``mailto:``, ``javascript:``) NOR an embedded URL. Mirrors the
      ``_has_uri_scheme`` shape used by ``scripts/validate_brand_preset.py``.

  T11 no_unsafe_path_shape
    - No string field may start with ``/``, ``\\``, or ``//``, and no
      string field may contain a ``..`` path segment when split on
      ``/`` or ``\\``. Mirrors ``local_path_is_safe``.

  T12 no_public_upload_wording
    - No string field, once lower-cased AND stripped of every
      non-alphanumeric character, may contain the marker ``public`` AND
      ALSO contain any of the propagation-verb markers ``upload``,
      ``share``, ``sharing``, ``url``, ``link``, ``post``, ``publish``,
      ``distribut``, or ``host``. Same canonical-form match shape as
      ``scripts/validate_brand_preset.py`` P7.

  T13 no_credential_shaped_wording
    - No string field, once lower-cased AND stripped of every
      non-alphanumeric character, may contain any of the credential-
      shape compound tokens ``apikey``, ``apitoken``, ``accesstoken``,
      ``authtoken``, ``csrftoken``, ``idtoken``, ``jwttoken``,
      ``oauthtoken``, ``refreshtoken``, ``sessiontoken``, ``secret``,
      ``bearer``, ``password``, or the bare marker ``token``; AND no
      string field's raw form may match the regex
      ``\\bsk-[A-Za-z0-9_\\-]{16,}`` (the ``sk-``-prefixed OpenAI /
      Anthropic API-key shape). Same shape as P11 in
      ``validate_brand_preset.py``.

  T14 no_raw_source_or_confidential_wording
    - No string field, once lower-cased AND stripped of every
      non-alphanumeric character, may contain ``confidential``,
      ``proprietary``, ``internalonly``, ``ndaprotected``,
      ``customername``, ``accountid``, ``ssn``, ``creditcard``, or
      ``raw`` together with any of ``source`` / ``content`` /
      ``paragraph`` / ``excerpt``. Same shape as P9 in
      ``validate_brand_preset.py``.

Out of scope for THIS validator (and explicitly refused here):

  - calling D-One / Qoder / MCP / any image generator / model API /
    image search / public network / external service;
  - mutating the trace or any pipeline artifact (read-only validator);
  - emitting a trace from this script (trace emission lives in
    ``scripts/export_pptx.py`` and is OPT-IN via ``--trace-out``;
    omitting ``--trace-out`` leaves the default PPTX export behavior
    unchanged and writes no sidecar — this validator validates the
    resulting trace JSON regardless of which of the two writers
    produced it);
  - any chart rendering / PPTX export / SVG generation behavior.

Exit codes:
  0  every gate passed (or --self-test scenarios all behaved as expected).
  1  one or more structural / content gates failed (T2..T14).
  2  invocation / file / parse error. Covers: missing or incompatible
     CLI flags; schema file missing on disk; AND every T1 precheck
     failure.

CLI:
  python3 scripts/validate_conversion_trace.py --trace <path-to-trace.json>
  python3 scripts/validate_conversion_trace.py --self-test
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

TRACE_SCHEMA = SCHEMAS_DIR / "conversion_trace.schema.json"

# Closed enums mirrored from the schema. Kept here so the validator
# can run T5 (reason_code_consistency) and T9 (deck_layouts_envelope)
# without re-parsing the schema for those specific enums.
_EDITABLE_STATUS = "editable"
_NON_EDITABLE_STATUSES: frozenset[str] = frozenset(
    {"rejected", "degraded", "skipped"}
)
_REASON_CODE_ENUM: frozenset[str] = frozenset({
    "primitive_kind_unsupported",
    "layout_unsupported",
    "bounds_out_of_canvas",
    "image_ref_undeclared",
    "table_row_width_mismatch",
    "style_ref_unresolved",
    "chart_renderer_todo",
    "media_embedding_todo",
    "font_overflow_todo",
    "other_synthetic_probe",
})

# RFC 3986 scheme: ALPHA *( ALPHA / DIGIT / "+" / "-" / "." ) ":"
# Two shapes, mirroring validate_brand_preset:
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


class TraceLoadError(Exception):
    """Raised by ``_load_trace`` when the T1 precheck fails. Carries a
    single ``T1: ...`` diagnostic line. ``main()`` maps this to exit 2."""


def _load_trace(trace_path: Path) -> dict:
    if trace_path.is_symlink():
        raise TraceLoadError(
            f"T1: trace path is a symlink (refused): {trace_path}"
        )
    if not trace_path.exists():
        raise TraceLoadError(
            f"T1: trace path does not exist: {trace_path}"
        )
    if not trace_path.is_file():
        raise TraceLoadError(
            f"T1: trace path is not a regular file: {trace_path}"
        )
    try:
        raw = trace_path.read_bytes()
    except OSError as exc:
        raise TraceLoadError(
            f"T1: cannot read trace {trace_path}: {exc}"
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TraceLoadError(
            f"T1: trace is not valid UTF-8: {exc}"
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TraceLoadError(
            f"T1: trace is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise TraceLoadError(
            f"T1: top-level JSON value is {type(data).__name__}, "
            f"expected object"
        )
    return data


def _gate_schema_subset_valid(data: dict) -> list[str]:
    """T2 — schema validation under the stdlib subset."""
    errors: list[str] = []
    try:
        schema = json.loads(TRACE_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"T2: cannot read schema {TRACE_SCHEMA}: {exc}"]
    _validate(data, schema, "<root>", errors)
    return [f"T2: {e}" for e in errors]


_PIPELINE_STATUS_ENUM: frozenset[str] = frozenset({
    "future_contract_only",
    "runtime_emitted_by_export_pptx",
})


def _gate_pipeline_status(data: dict) -> list[str]:
    """T3 — pipeline_status MUST be one of the closed two-literal set.

    'future_contract_only' marks the SHAPE-only baseline (committed
    example fixtures and hand-authored shape probes). 'runtime_emitted_
    by_export_pptx' marks the paired-contract runtime path that
    scripts/export_pptx.py uses when invoked with --trace-out. Any other
    literal is refused; adding a third writer requires another paired
    contract change in the schema, here, and in
    references/conversion-trace-contract.md."""
    value = data.get("pipeline_status")
    if value not in _PIPELINE_STATUS_ENUM:
        return [
            f"T3: pipeline_status must be one of "
            f"{sorted(_PIPELINE_STATUS_ENUM)!r} "
            f"(got {value!r}); a new literal requires a paired contract "
            f"change in the schema, validator, and contract doc"
        ]
    return []


def _gate_ids_are_synthetic(data: dict) -> list[str]:
    """T4 — trace_id / deck.deck_id / generated_by.name MUST each be
    a synthetic_-prefixed id. The schema patterns already enforce this
    on the happy path; T4 is defense-in-depth against a future schema
    relaxation, and also reports a clean per-field diagnostic when the
    value is missing or wrong-typed (the schema would also fire, under
    T2; T4 names the specific id field at fault)."""
    errors: list[str] = []
    fields = (
        ("trace_id", data.get("trace_id")),
        ("deck.deck_id", (data.get("deck") or {}).get("deck_id")
            if isinstance(data.get("deck"), dict) else None),
        ("generated_by.name", (data.get("generated_by") or {}).get("name")
            if isinstance(data.get("generated_by"), dict) else None),
    )
    for label, value in fields:
        if not isinstance(value, str):
            errors.append(
                f"T4: {label}: value must be a string carrying the "
                f"'synthetic_' prefix (got {type(value).__name__})"
            )
            continue
        if not _SYNTHETIC_PREFIX_RE.match(value):
            errors.append(
                f"T4: {label}: value {value!r} does not match the "
                f"required synthetic_-prefix id shape"
            )
    return errors


def _gate_reason_code_consistency(data: dict) -> list[str]:
    """T5 — when status=editable the reason_code MUST be null; when
    status in {rejected, degraded, skipped} the reason_code MUST be a
    non-null string from the closed enum."""
    errors: list[str] = []
    records = data.get("records")
    if not isinstance(records, list):
        # T2 will already complain; nothing for T5 to walk.
        return errors
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        status = rec.get("status")
        reason = rec.get("reason_code")
        path = f"records[{i}]"
        if status == _EDITABLE_STATUS:
            if reason is not None:
                errors.append(
                    f"T5: {path}: status=editable requires reason_code "
                    f"null; got {reason!r}"
                )
        elif status in _NON_EDITABLE_STATUSES:
            if reason is None:
                errors.append(
                    f"T5: {path}: status={status!r} requires a non-null "
                    f"reason_code drawn from the closed enum"
                )
            elif reason not in _REASON_CODE_ENUM:
                errors.append(
                    f"T5: {path}: reason_code {reason!r} not in closed "
                    f"enum (status={status!r})"
                )
        else:
            # An unknown status is already T2's job to report. Skip here
            # to avoid double-reporting.
            continue
    return errors


def _gate_records_unique_primitive_per_slide(data: dict) -> list[str]:
    """T6 — (slide_index, primitive_id) tuples MUST be unique."""
    errors: list[str] = []
    records = data.get("records")
    if not isinstance(records, list):
        return errors
    seen: set[tuple[Any, Any]] = set()
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        key = (rec.get("slide_index"), rec.get("primitive_id"))
        # Skip unhashable / wrong-type ids; T2 will already flag those.
        try:
            if key in seen:
                errors.append(
                    f"T6: records[{i}]: duplicate (slide_index, "
                    f"primitive_id)={key!r}"
                )
            else:
                seen.add(key)
        except TypeError:
            continue
    return errors


def _gate_summary_counts_match_records(data: dict) -> list[str]:
    """T7 — summary totals MUST equal per-status counts in records."""
    errors: list[str] = []
    records = data.get("records")
    summary = data.get("summary")
    if not isinstance(records, list) or not isinstance(summary, dict):
        return errors
    counts = {
        "editable_count": 0,
        "rejected_count": 0,
        "degraded_count": 0,
        "skipped_count": 0,
    }
    status_to_key = {
        "editable": "editable_count",
        "rejected": "rejected_count",
        "degraded": "degraded_count",
        "skipped": "skipped_count",
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
                f"T7: summary.{k} = {actual!r}, but records imply "
                f"{expected}"
            )
    return errors


def _gate_deck_slide_count_envelope(data: dict) -> list[str]:
    """T8 — deck.slide_count MUST be >= max(record.slide_index)."""
    errors: list[str] = []
    deck = data.get("deck")
    records = data.get("records")
    if not isinstance(deck, dict) or not isinstance(records, list):
        return errors
    declared = deck.get("slide_count")
    if not isinstance(declared, int) or isinstance(declared, bool):
        return errors
    max_idx = 0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        idx = rec.get("slide_index")
        if isinstance(idx, int) and not isinstance(idx, bool):
            if idx > max_idx:
                max_idx = idx
    if max_idx > declared:
        errors.append(
            f"T8: deck.slide_count={declared} but a record names "
            f"slide_index={max_idx}; envelope violated"
        )
    return errors


def _gate_deck_layouts_envelope(data: dict) -> list[str]:
    """T9 — every record.slide_layout MUST be in deck.layouts_attempted."""
    errors: list[str] = []
    deck = data.get("deck")
    records = data.get("records")
    if not isinstance(deck, dict) or not isinstance(records, list):
        return errors
    declared = deck.get("layouts_attempted")
    if not isinstance(declared, list):
        return errors
    declared_set = {x for x in declared if isinstance(x, str)}
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        layout = rec.get("slide_layout")
        if isinstance(layout, str) and layout not in declared_set:
            errors.append(
                f"T9: records[{i}].slide_layout {layout!r} not in "
                f"deck.layouts_attempted {sorted(declared_set)!r}"
            )
    return errors


def _gate_no_url_or_uri_scheme(data: dict) -> list[str]:
    """T10 — URI scheme prefix or embedded URL in any string field."""
    errors: list[str] = []
    for path, value in _walk_strings(data):
        if _has_uri_scheme(value):
            errors.append(
                f"T10: {path}: value {value!r} carries a URI-scheme prefix"
            )
    return errors


def _gate_no_unsafe_path_shape(data: dict) -> list[str]:
    errors: list[str] = []
    for path, value in _walk_strings(data):
        if _starts_with_unsafe_path_prefix(value):
            errors.append(
                f"T11: {path}: value {value!r} starts with an unsafe "
                f"path prefix ('/', '\\\\', or '//')"
            )
            continue
        if _contains_parent_segment(value):
            errors.append(
                f"T11: {path}: value {value!r} contains a '..' segment"
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
                f"T12: {path}: value {value!r} combines 'public' with a "
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
                f"T13: {path}: value {value!r} carries credential-"
                f"shaped wording ({matched!r}; canonical form: "
                f"{canon!r})"
            )
            continue
        if _SK_PREFIX_KEY.search(value):
            errors.append(
                f"T13: {path}: value {value!r} carries an sk- "
                f"prefixed API-key shape"
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
                f"T14: {path}: value {value!r} carries confidential / "
                f"raw-source wording ({matched}; canonical form: "
                f"{canon!r})"
            )
    return errors


GATES = (
    ("T3", _gate_pipeline_status),
    ("T4", _gate_ids_are_synthetic),
    ("T5", _gate_reason_code_consistency),
    ("T6", _gate_records_unique_primitive_per_slide),
    ("T7", _gate_summary_counts_match_records),
    ("T8", _gate_deck_slide_count_envelope),
    ("T9", _gate_deck_layouts_envelope),
    ("T10", _gate_no_url_or_uri_scheme),
    ("T11", _gate_no_unsafe_path_shape),
    ("T12", _gate_no_public_upload_wording),
    ("T13", _gate_no_credential_shaped_wording),
    ("T14", _gate_no_raw_source_or_confidential_wording),
)


def validate_trace(trace_path: Path) -> list[str]:
    """Run T2..T14 against the trace. Raises ``TraceLoadError`` for
    T1 precheck failures (caller maps those to exit 2)."""
    data = _load_trace(trace_path)
    errors: list[str] = []
    errors.extend(_gate_schema_subset_valid(data))
    for _name, gate in GATES:
        errors.extend(gate(data))
    return errors


# ----------------------------------------------------------------------
# --self-test
# ----------------------------------------------------------------------

_GOOD_TRACE: dict[str, Any] = {
    "schema_version": "1",
    "trace_id": "synthetic_self_test",
    "pipeline_status": "future_contract_only",
    "generated_by": {
        "name": "synthetic_self_test",
        "mode": "self_test_fixture",
    },
    "deck": {
        "deck_id": "synthetic_demo_deck",
        "slide_count": 2,
        "layouts_attempted": ["cover", "kpi_dashboard"],
    },
    "records": [
        {
            "slide_index": 1,
            "slide_layout": "cover",
            "primitive_id": "title",
            "primitive_kind": "text",
            "expected_pptx_kind": "native_text_shape",
            "status": "editable",
            "reason_code": None,
            "evidence": {
                "primitive_kind_supported": True,
                "layout_supported": True,
                "bounds_within_canvas": True,
                "shape_count_delta": 1,
                "text_run_count": 1,
                "table_row_count": None,
                "image_alt_text_present": None,
                "relationship_type": None,
            },
        },
        {
            "slide_index": 2,
            "slide_layout": "kpi_dashboard",
            "primitive_id": "trend_chart",
            "primitive_kind": "chart_placeholder",
            "expected_pptx_kind": "none",
            "status": "rejected",
            "reason_code": "chart_renderer_todo",
            "evidence": {
                "primitive_kind_supported": False,
                "layout_supported": True,
                "bounds_within_canvas": True,
                "shape_count_delta": 0,
                "text_run_count": None,
                "table_row_count": None,
                "image_alt_text_present": None,
                "relationship_type": None,
            },
        },
    ],
    "summary": {
        "editable_count": 1,
        "rejected_count": 1,
        "degraded_count": 0,
        "skipped_count": 0,
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
    _GOOD_TRACE and returns the candidate. ``expected_gates`` is either
    ``""`` (the scenario MUST pass), a single gate prefix like ``"T5"``,
    or a tuple of gate prefixes the scenario MUST fire at least one of."""
    candidate = json.loads(json.dumps(_GOOD_TRACE))
    candidate = mutate(candidate)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        path = _write_tmp(candidate, tmp, "trace.json")
        errors = validate_trace(path)
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

    # Positive sweep across every closed reason_code value — paired
    # with status='rejected' so T5 is satisfied. Regression guard: a
    # future content gate that canonicalises strings and bans a
    # substring shared by a legitimate reason_code (e.g. T13 once
    # refused 'style_token_unresolved' because its canonical form
    # contained 'token') must NOT slip through unnoticed. The schema
    # enum is authoritative — anything in it must pass the validator.
    for _code in sorted(_REASON_CODE_ENUM):
        def _mut(d, code=_code):
            d["records"][1]["reason_code"] = code
            return d
        results.append(_scenario(
            f"reason-code-sweep-{_code}", _mut, ""
        ))

    # Positive baseline against the committed example fixture, so a
    # regression that breaks the example is caught here.
    committed = REPO_ROOT / "examples" / "synthetic_conversion_trace.json"
    if committed.is_file():
        errors = validate_trace(committed)
        ok = not errors
        results.append((
            ok,
            (
                f"committed-example: PASS"
                if ok
                else f"committed-example: expected PASS, got {errors}"
            ),
        ))

    # T2 — schema violation (missing required field).
    def m_t2(d):
        d.pop("summary")
        return d
    results.append(_scenario("t2-missing-required", m_t2, "T2"))

    # T2 — unknown status (closed enum); the schema enum fires.
    def m_t2_status(d):
        d["records"][0]["status"] = "maybe_editable"
        # Keep summary in sync so T7 does not also fire (we want a clean
        # T2 read on the unknown-status case).
        d["summary"]["editable_count"] = 0
        return d
    results.append(_scenario("t2-unknown-status", m_t2_status, "T2"))

    # T2 — unknown reason_code (closed enum); the schema enum fires.
    def m_t2_reason(d):
        d["records"][1]["reason_code"] = "made_up_reason"
        return d
    results.append(_scenario("t2-unknown-reason-code", m_t2_reason, "T2"))

    # T3 — pipeline_status flipped to a literal outside the closed
    # two-element enum. Schema enum (T2) AND the runtime gate (T3) both
    # fire; either is evidence of fail-closed behavior. The literal
    # 'runtime_emitted' (the obvious typo for the paired
    # 'runtime_emitted_by_export_pptx' writer) is intentionally NOT
    # accepted — a writer that picked the wrong name must trip the gate.
    def m_t3(d):
        d["pipeline_status"] = "runtime_emitted"
        return d
    results.append(_scenario("t3-pipeline-flipped", m_t3, ("T2", "T3")))

    # T3 — positive sweep across every accepted literal. The schema
    # enum and the validator's T3 gate must accept BOTH literals — the
    # SHAPE-only baseline ('future_contract_only') AND the paired
    # runtime path ('runtime_emitted_by_export_pptx'). A regression
    # that narrows the enum back to a single literal would fire here.
    for _ok in (
        "future_contract_only",
        "runtime_emitted_by_export_pptx",
    ):
        def _mut(d, lit=_ok):
            d["pipeline_status"] = lit
            return d
        results.append(_scenario(
            f"t3-pipeline-accepted-{_ok}", _mut, "",
        ))

    # T4 — non-synthetic trace_id.
    def m_t4(d):
        d["trace_id"] = "real_company_q4"
        return d
    results.append(_scenario("t4-non-synthetic-id", m_t4, ("T2", "T4")))

    # T5 — editable record carrying a non-null reason_code.
    def m_t5_editable_with_reason(d):
        d["records"][0]["reason_code"] = "other_synthetic_probe"
        return d
    results.append(_scenario(
        "t5-editable-with-reason", m_t5_editable_with_reason, "T5"
    ))

    # T5 — rejected record carrying a null reason_code.
    def m_t5_rejected_null(d):
        d["records"][1]["reason_code"] = None
        return d
    results.append(_scenario(
        "t5-rejected-null-reason", m_t5_rejected_null, "T5"
    ))

    # T6 — duplicate (slide_index, primitive_id) tuple.
    def m_t6_duplicate(d):
        dup = json.loads(json.dumps(d["records"][0]))
        d["records"].append(dup)
        d["summary"]["editable_count"] = 2
        d["deck"]["slide_count"] = 2
        return d
    results.append(_scenario(
        "t6-duplicate-primitive", m_t6_duplicate, "T6"
    ))

    # T7 — summary disagrees with records.
    def m_t7_summary_drift(d):
        d["summary"]["editable_count"] = 99
        return d
    results.append(_scenario(
        "t7-summary-drift", m_t7_summary_drift, "T7"
    ))

    # T8 — record slide_index exceeds deck.slide_count.
    def m_t8_index_overflow(d):
        d["records"][1]["slide_index"] = 99
        return d
    results.append(_scenario(
        "t8-slide-index-overflow", m_t8_index_overflow, "T8"
    ))

    # T9 — record layout missing from deck.layouts_attempted.
    def m_t9_orphan_layout(d):
        d["records"][0]["slide_layout"] = "section_divider"
        return d
    results.append(_scenario(
        "t9-orphan-layout", m_t9_orphan_layout, "T9"
    ))

    # T10 — URL wording in trace-level notes.
    def m_t10(d):
        d["notes"] = "see https://example/notes for context"
        return d
    results.append(_scenario("t10-url", m_t10, "T10"))

    # T10 — file:// URI scheme in a record note.
    def m_t10_file(d):
        d["records"][0]["note"] = "file:///etc/passwd"
        return d
    results.append(_scenario("t10-file-uri", m_t10_file, "T10"))

    # T11 — absolute path in a record note.
    def m_t11_abs(d):
        d["records"][0]["note"] = "/etc/passwd should not appear"
        return d
    results.append(_scenario("t11-absolute-path", m_t11_abs, "T11"))

    # T11 — parent traversal in a record note.
    def m_t11_parent(d):
        d["records"][0]["note"] = "uses ../../secrets path"
        return d
    results.append(_scenario("t11-parent-segment", m_t11_parent, "T11"))

    # T12 — public-upload wording in trace-level notes.
    def m_t12_public_upload(d):
        d["notes"] = "auto public upload after build"
        return d
    results.append(_scenario(
        "t12-public-upload", m_t12_public_upload, "T12"
    ))

    # T12 — public + host (the host marker extension).
    def m_t12_public_hosting(d):
        d["notes"] = "public hosting enabled"
        return d
    results.append(_scenario(
        "t12-public-hosting", m_t12_public_hosting, "T12"
    ))

    # T13 — credential family probes.
    def m_t13_api_key(d):
        d["notes"] = "store api_key here"
        return d
    results.append(_scenario("t13-api-key", m_t13_api_key, "T13"))

    def m_t13_secret(d):
        d["notes"] = "client secret value"
        return d
    results.append(_scenario("t13-secret", m_t13_secret, "T13"))

    def m_t13_token(d):
        d["notes"] = "token placeholder"
        return d
    results.append(_scenario("t13-token", m_t13_token, "T13"))

    def m_t13_sk_prefix(d):
        d["notes"] = "key is sk-abcdef0123456789xyz"
        return d
    results.append(_scenario("t13-sk-prefix", m_t13_sk_prefix, "T13"))

    # T14 — confidential marker in notes.
    def m_t14_confidential(d):
        d["notes"] = "marked confidential, internal"
        return d
    results.append(_scenario(
        "t14-confidential", m_t14_confidential, "T14"
    ))

    # T14 — raw + source combination in notes.
    def m_t14_raw_source(d):
        d["notes"] = "carries raw source excerpt verbatim"
        return d
    results.append(_scenario(
        "t14-raw-source", m_t14_raw_source, "T14"
    ))

    # Negative-positive: short Sk-Modernist-style font wording must NOT
    # fire T13 — the sk-pattern threshold is 16+ chars after sk-.
    def m_safe_short_sk(d):
        d["notes"] = "uses Sk Modernist family"
        return d
    results.append(_scenario("safe-short-sk-family", m_safe_short_sk, ""))

    # Negative-positive: bare 'host' without 'public' must NOT fire T12.
    def m_safe_host_alone(d):
        d["notes"] = "hostname reference for layout"
        return d
    results.append(_scenario("safe-host-alone", m_safe_host_alone, ""))

    # Negative-positive: bare 'public' without a propagation verb must
    # NOT fire T12.
    def m_safe_public_alone(d):
        d["notes"] = "public domain marker note"
        return d
    results.append(_scenario(
        "safe-public-alone", m_safe_public_alone, ""
    ))

    # T1 — load-time refusals exit 2 via TraceLoadError.
    def _expect_load_error(label: str, path: Path) -> tuple[bool, str]:
        try:
            errors = validate_trace(path)
        except TraceLoadError as exc:
            msg = str(exc)
            if msg.startswith("T1:"):
                return True, f"{label}: refused under T1 (load-time)"
            return False, (
                f"{label}: expected T1 load-time refusal, got {msg!r}"
            )
        return False, (
            f"{label}: expected TraceLoadError; got errors {errors}"
        )

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        path = tmp / "trace.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        results.append(_expect_load_error("t1-non-object", path))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        real = tmp / "real.json"
        real.write_text(json.dumps(_GOOD_TRACE), encoding="utf-8")
        link = tmp / "link.json"
        link.symlink_to(real)
        results.append(_expect_load_error("t1-symlink", link))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        path = tmp / "missing.json"
        results.append(_expect_load_error("t1-missing-file", path))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        path = tmp / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        results.append(_expect_load_error("t1-bad-json", path))

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
            "Read-only validator for synthetic PPTX conversion-trace "
            "report files. Stdlib-only; no network, no D-One, no model "
            "API."
        )
    )
    parser.add_argument(
        "--trace",
        type=Path,
        help="Path to a conversion_trace JSON file to validate.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run built-in positive + negative scenarios and exit.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if args.trace is not None:
            print(
                "error: --trace is not compatible with --self-test",
                file=sys.stderr,
            )
            return 2
        return _self_test()

    if args.trace is None:
        print("error: --trace is required (or pass --self-test)",
              file=sys.stderr)
        return 2

    if not TRACE_SCHEMA.is_file():
        print(
            f"error: trace schema not found at {TRACE_SCHEMA}",
            file=sys.stderr,
        )
        return 2

    try:
        errors = validate_trace(args.trace)
    except TraceLoadError as exc:
        print(f"FAIL: {args.trace}", file=sys.stderr)
        print(f"  - {exc}", file=sys.stderr)
        return 2
    if errors:
        print(f"FAIL: {args.trace}")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: {args.trace} (schema + content gates)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
