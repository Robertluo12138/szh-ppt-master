#!/usr/bin/env python3
"""Local validator for the runner-written mock_d_one_adapter_plan.json
evidence sidecar.

Stdlib-only. NETWORK-FREE. NO-D-ONE. NO-Qoder. NO-MCP. NO model API.
NO image generation. NO telemetry. NO PPTX export.
MOCK / STUB ONLY — NOT real D-One integration.

Given three explicit caller-supplied inputs:

  --plan                <path to mock_d_one_adapter_plan.json>
  --d-one-spec          <path to d_one_spec.json>
  --image-manifest-spec <path to image_manifest_spec.json>

and an OPTIONAL fourth input:

  --descriptor-vocabulary <path to d_one_descriptor_vocabulary.json>

this script asserts every documented invariant on the sidecar bytes
without ever mutating any input file. It mirrors a narrow subset of
``scripts/done_image_adapter.py --validate-plan`` semantics, scoped to
what can be checked from the bundle's caller-authored ``d_one_spec.json``
+ ``image_manifest_spec.json`` ALONE (no workspace dependency, no
``input/source.md`` access). When ``--descriptor-vocabulary`` is
supplied, the validator additionally cross-checks every per-request
taxonomy / ``custom_descriptor`` / ``placement_role`` value present on
the sidecar against the matching allow-list projected from the
vocabulary; the flag stays OPTIONAL so single-use sidecars without
taxonomy can still be checked against spec + manifest alone. The
exit-code convention matches ``done_image_adapter --validate-plan``:

  0 — every gate passed.
  1 — at least one gate failed (sidecar contents do not match the
      committed spec / manifest, or carry forbidden substrings).
  2 — invocation / file / parse error (missing file, symlink, bad
      JSON, non-object root, ...).

Gates (each prefixed in diagnostics so a regression points at the
exact rule):

  G1 inputs_are_regular_non_symlink_files
    - ``--plan`` / ``--d-one-spec`` / ``--image-manifest-spec`` each
      exist, are regular files, and are not symlinks (broken or
      resolvable). Mirrors the symlink refusals every other helper
      in this repo applies.
  G2 inputs_parse_as_top_level_json_objects
    - bytes are readable as UTF-8;
    - bytes parse as JSON;
    - the parsed JSON root is a dict.
  G3 sidecar_schema_validates
    - the sidecar validates against
      ``schemas/d_one_adapter_plan.schema.json`` under the same stdlib
      subset ``scripts/validate_artifacts.py`` applies. The schema
      pattern lock + ``additionalProperties: false`` + required-fields
      enforcement already covers ``schema_version == 4``, ``mode ==
      "dry_run"``, ``note`` containing the dry-run sentinel,
      ``manifest_source == "d_one_local"``, and the lowercase-identifier
      + forbidden-token pattern lock on every taxonomy /
      ``custom_descriptor`` / ``placement_role`` value.
  G4 sidecar_schema_version_locked_to_4
    - belt-and-braces re-check on top of the schema's enum lock; the
      diagnostic surfaces the exact value when it drifted.
  G5 sidecar_request_count_matches_len_requests
    - ``request_count == len(requests)``. Catches a sidecar whose
      counter desynced from the array length (e.g. a hand-edit that
      removed a request without re-counting).
  G6 sidecar_request_ids_are_unique
    - no id appears twice in the requests array.
  G7 sidecar_request_ids_match_d_one_spec_ids
    - the set of ids on the sidecar's requests equals the set of ids
      on ``d_one_spec.json``'s requests. Catches missing requests
      (e.g. the local_region request silently dropped) and unexpected
      requests (e.g. a request injected after the spec was committed).
  G8 sidecar_placement_role_matches_d_one_spec_per_id
    - for every id present in BOTH inputs, the sidecar's
      ``placement_role`` equals the spec's ``placement_role``
      byte-for-byte. An omitted role on one side and a populated role
      on the other side counts as a mismatch.
  G9 sidecar_covers_both_placement_roles (when
      ``--require-both-placement-roles`` is supplied)
    - the set of ``placement_role`` values across the sidecar's
      requests equals ``{"hero_page", "local_region"}``. This is the
      ``examples/synthetic_mock_image_trial`` invariant: both
      generated-image roles must remain auditable from the sidecar
      bytes alone. The flag is opt-in so the validator stays usable
      against single-role bundles.
  G10 sidecar_manifest_local_path_matches_image_manifest_spec_per_id
    - for every id, ``manifest_local_path`` equals
      ``image_manifest_spec.images[id].local_path`` byte-for-byte.
  G11 sidecar_manifest_local_path_is_safe
    - every ``manifest_local_path`` passes ``local_path_is_safe``
      (no URI scheme, no leading ``/`` / ``\\`` / ``//``, no ``..``
      segment, no surrounding whitespace, non-empty). Belt-and-braces:
      G10 already requires byte-identity with the committed manifest,
      but a manifest whose own local_path was already unsafe (rejected
      by upstream stages) is still refused here so the sidecar gate
      never "agrees" on an unsafe value.
  G12 sidecar_carries_no_forbidden_substrings
    - recursive scan of every string scalar in the sidecar refuses:
      external URLs / URI scheme prefixes (``http://``, ``https://``,
      ``ftp://``, ``file://``, ``data:``, and any other RFC-3986-shaped
      scheme), path-traversal cues (``../``, ``..\\``), credential-
      shaped tokens (``password``, ``secret``, ``credential``,
      ``api_key``, ``api-key``, ``apikey``), public-upload /
      public-hosting wording (``upload to public``, ``public upload``,
      ``share publicly``, ``public hosting``, ``publish to web``,
      ``public url``, ``public link``, ``public cdn``, ``host
      publicly``), confidential markers (``confidential``, ``internal
      use only``, ``do not share``), and raw-source phrasing (``raw
      source``, ``raw_source``, ``raw-source``, ``source text``). This
      is now the canonical sidecar-leakage scan; callers such as
      ``mock_image_bundle_acceptance_smoke`` invoke this validator
      rather than keeping a second in-script deny list.
  G13 sidecar_taxonomy_values_in_descriptor_vocabulary (only when
      ``--descriptor-vocabulary <path>`` is supplied)
    - the vocabulary path itself passes the same file gates as
      ``--plan`` (regular file, no symlink, no URI shape), parses as
      UTF-8 JSON whose root is an object, and validates against
      ``schemas/d_one_descriptor_vocabulary.schema.json`` (a missing /
      symlinked / URI-shaped vocabulary aborts with rc=2; a malformed
      or schema-invalid vocabulary aborts with rc=1).
    - every per-request taxonomy value the sidecar carries
      (``rendering_style`` / ``palette_family`` / ``image_role`` /
      ``layout_pattern`` / ``modifier`` / ``text_policy`` /
      ``subject_domain``) must be a member of the matching
      ``image_taxonomy.<dim>.allowed_values`` set projected from the
      vocabulary; missing fields are skipped (the vocabulary gate only
      checks values that are actually present on the request).
    - every per-request ``custom_descriptor`` value (when present)
      must be a member of the vocabulary's ``custom_descriptors[*].
      value`` set; an absent / empty ``custom_descriptors`` list
      refuses any request that carries the field at all.
    - every per-request ``placement_role`` value (when present) must
      be a member of the vocabulary's ``image_taxonomy.placement_
      role.allowed_values`` set; an absent placement_role block on
      the vocabulary refuses any request that carries the field.
    - the gate is opt-in: omitting ``--descriptor-vocabulary`` keeps
      the validator usable against any sidecar whose vocabulary
      paperwork lives elsewhere.

Post-condition: every input file's bytes are byte-identical before and
after the run. The validator is read-only — it never writes any of the
three inputs (or the optional ``--descriptor-vocabulary``), never
creates new files, and never mutates any other workspace state.
"""
from __future__ import annotations

import sys

# Refuse to write `.pyc` files for any first-party module the validator
# imports (validate_artifacts._validate, validate_scaffold.local_path_
# is_safe). Mirrors the same flip every other read-only validator in
# this repo applies so a clean checkout never gains a
# scripts/__pycache__/<mod>.cpython-*.pyc file from running this script.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "schemas"
PLAN_SCHEMA = SCHEMAS_DIR / "d_one_adapter_plan.schema.json"
DESCRIPTOR_VOCAB_SCHEMA = (
    SCHEMAS_DIR / "d_one_descriptor_vocabulary.schema.json"
)

sys.path.insert(0, str(SCRIPTS_DIR))
from validate_artifacts import _validate  # noqa: E402
from validate_scaffold import local_path_is_safe  # noqa: E402

# Locked plan-schema version. Mirrors
# ``run_mock_image_pipeline.LOCKED_PLAN_SCHEMA_VERSION``; the
# committed-bundle smoke delegates this check to this validator.
EXPECTED_SCHEMA_VERSION = 4

# Closed placement_role enumeration. Mirrors
# ``done_image_adapter.PLACEMENT_ROLE_ALLOWED`` and the smoke's
# ``EXPECTED_PLACEMENT_ROLES``. When ``--require-both-placement-roles``
# is supplied, the validator refuses any sidecar whose placement_role
# coverage is a proper subset of this pair.
REQUIRED_PLACEMENT_ROLES: frozenset[str] = frozenset(
    {"hero_page", "local_region"},
)

# Seven per-request taxonomy field names. Mirrors
# ``done_image_adapter.TAXONOMY_FIELDS`` in spec/plan field order so the
# vocabulary-gate diagnostic surfaces fields in the same order the writer
# emits them. Every member is OPTIONAL on a per-request basis (the plan
# schema's additionalProperties:false lock makes the field set closed but
# the requireds do not include any taxonomy field); when present, the
# vocabulary gate (G13) requires the value to be a member of the matching
# ``image_taxonomy.<dim>.allowed_values`` set.
TAXONOMY_FIELDS: tuple[str, ...] = (
    "rendering_style",
    "palette_family",
    "image_role",
    "layout_pattern",
    "modifier",
    "text_policy",
    "subject_domain",
)

# Optional per-request *custom-descriptor escape hatch*. Mirrors
# ``done_image_adapter.CUSTOM_DESCRIPTOR_FIELD``. When present on a
# sidecar request AND ``--descriptor-vocabulary`` is supplied, the
# value MUST be a member of the vocabulary's
# ``custom_descriptors[*].value`` allow-list (an absent / empty
# ``custom_descriptors`` list refuses any request carrying the field).
CUSTOM_DESCRIPTOR_FIELD = "custom_descriptor"

# Optional per-request placement_role field. Mirrors
# ``done_image_adapter.PLACEMENT_ROLE_FIELD``. When present AND
# ``--descriptor-vocabulary`` is supplied, the value MUST be a member of
# the vocabulary's ``image_taxonomy.placement_role.allowed_values`` set
# (an absent placement_role block on the vocabulary refuses any request
# carrying the field — same "no allow-list, no permission" gate the
# custom_descriptor escape hatch uses).
PLACEMENT_ROLE_FIELD = "placement_role"

# Forbidden-substring allow-list for the recursive leakage scan.
# Mirrors ``mock_image_bundle_acceptance_smoke._SIDECAR_FORBIDDEN_
# SUBSTRINGS`` PLUS the two path-traversal cues the validator owns
# directly. A leak here is a leak regardless of which field carries it;
# the recursive walk surfaces the exact value when the gate fails.
_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    # URI schemes.
    "http://", "https://", "ftp://", "file://", "data:",
    "://",  # any other RFC-3986-shaped scheme
    # Path traversal cues. Defense-in-depth on top of G11 (the
    # local_path_is_safe gate); strings buried in `prompt` /
    # `intended_use` / `note` etc. would otherwise slip past G11
    # which only inspects `manifest_local_path`.
    "../", "..\\",
    # Credentials.
    "password", "secret", "credential", "api_key", "api-key", "apikey",
    # Public-upload / public-hosting wording.
    "upload to public", "public upload", "share publicly",
    "public hosting", "publish to web", "public url",
    "public link", "public cdn", "host publicly",
    # Confidential markers.
    "confidential", "internal use only", "do not share",
    # Raw-source phrasing.
    "raw source", "raw_source", "raw-source", "source text",
)

# RFC-3986-shaped scheme detector. Used by the leakage scan AND by the
# input-path gate (G1) — a CLI path that looks like a URI is refused
# before any disk I/O.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


# ---------------------------------------------------------------------------
# Loader helpers. Every helper returns ``(value | None, message)`` so the
# caller produces a single diagnostic per gate failure.
# ---------------------------------------------------------------------------


def _has_uri_scheme(s: str) -> bool:
    return bool(_URI_SCHEME_PREFIX.match(s))


def _refuse_input_path(path: Path, label: str) -> str:
    """Return a non-empty failure message if ``path`` fails G1 (URI
    shape, symlink, missing, or not a regular file). Returns ``""``
    when the path passes every G1 sub-check."""
    if _has_uri_scheme(str(path)):
        return (
            f"G1: {label} {path} looks like a URI; "
            f"validate_mock_d_one_adapter_plan accepts local file "
            f"paths only."
        )
    if path.is_symlink():
        try:
            target = str(path.readlink())
        except OSError:
            target = "<unreadable>"
        return (
            f"G1: {label} {path} is a symlink (-> {target}); "
            f"refusing to follow (broken or resolvable)."
        )
    if not path.exists():
        return f"G1: {label} {path} does not exist."
    if not path.is_file():
        return f"G1: {label} {path} is not a regular file."
    return ""


def _load_json_object(
    path: Path, label: str,
) -> tuple[dict | None, str]:
    """Read ``path`` as UTF-8 JSON and confirm the root is a dict.
    Returns ``(doc, "")`` on success; ``(None, msg)`` on failure
    (G2 diagnostic with the ``label``)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, (
            f"G2: cannot read {label} {path}: "
            f"{type(exc).__name__}: {exc}"
        )
    except UnicodeDecodeError as exc:
        return None, (
            f"G2: {label} {path} is not valid UTF-8: "
            f"{type(exc).__name__}: {exc}"
        )
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, (
            f"G2: {label} {path} does not parse as JSON: "
            f"{type(exc).__name__}: {exc}"
        )
    if not isinstance(doc, dict):
        return None, (
            f"G2: {label} {path} root is {type(doc).__name__}, expected "
            f"a JSON object."
        )
    return doc, ""


def _index_by_id(
    requests: Any, source_label: str,
) -> tuple[dict[str, dict], str]:
    """Project a ``requests`` array into ``{id -> entry}`` with a
    diagnostic when the shape is wrong. Used for both the sidecar
    requests array AND the d_one_spec.json requests array."""
    if not isinstance(requests, list):
        return {}, (
            f"{source_label}.requests is not a list "
            f"(got {type(requests).__name__})."
        )
    out: dict[str, dict] = {}
    for i, entry in enumerate(requests):
        if not isinstance(entry, dict):
            return {}, (
                f"{source_label}.requests[{i}] is "
                f"{type(entry).__name__}, expected a JSON object."
            )
        rid = entry.get("id")
        if not isinstance(rid, str) or not rid:
            return {}, (
                f"{source_label}.requests[{i}].id is missing or empty."
            )
        if rid in out:
            return {}, (
                f"{source_label}.requests[{i}].id {rid!r} duplicates an "
                f"earlier entry."
            )
        out[rid] = entry
    return out, ""


def _index_manifest_local_paths(
    manifest_doc: dict,
) -> tuple[dict[str, str], str]:
    """Project ``image_manifest_spec.json``'s ``images[]`` into
    ``{id -> local_path}`` with the same shape gate ``_index_by_id``
    applies. Empty local_path values are kept as-is so the manifest
    parity gate (G10) can surface them."""
    images = manifest_doc.get("images")
    if not isinstance(images, list):
        return {}, (
            f"image_manifest_spec.images is not a list "
            f"(got {type(images).__name__})."
        )
    out: dict[str, str] = {}
    for i, img in enumerate(images):
        if not isinstance(img, dict):
            return {}, (
                f"image_manifest_spec.images[{i}] is "
                f"{type(img).__name__}, expected a JSON object."
            )
        iid = img.get("id")
        if not isinstance(iid, str) or not iid:
            return {}, (
                f"image_manifest_spec.images[{i}].id is missing or empty."
            )
        if iid in out:
            return {}, (
                f"image_manifest_spec.images[{i}].id {iid!r} duplicates "
                f"an earlier entry."
            )
        lp = img.get("local_path")
        if not isinstance(lp, str):
            return {}, (
                f"image_manifest_spec.images[{i}].local_path is missing "
                f"or non-string (got {type(lp).__name__})."
            )
        out[iid] = lp
    return out, ""


def _walk_strings(value: Any):
    """Yield every string scalar reachable from ``value`` (recursive).
    Used by G12's recursive leakage scan. Mirrors
    ``mock_image_bundle_acceptance_smoke._walk_strings`` so a
    tightening on one side maps cleanly onto the other."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _walk_strings(k)
            yield from _walk_strings(v)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _load_descriptor_vocabulary(
    vocab_path: Path,
) -> tuple[
    dict[str, set[str]] | None,
    set[str] | None,
    set[str] | None,
    int,
    str,
]:
    """Validate ``vocab_path`` and project the membership sets G13
    needs. Mirrors a narrow subset of ``done_image_adapter._load_
    descriptor_vocabulary`` (no caching, no bytes return — the caller
    snapshots vocab bytes for the read-only post-condition separately).

    Returns ``(allowed_per_dim, allowed_custom, allowed_placement_role,
    rc, msg)``:

      * ``rc == 0`` and ``msg == ""`` on success. ``allowed_per_dim``
        is keyed by every member of ``TAXONOMY_FIELDS`` (each value a
        set of approved taxonomy tokens for that dimension);
        ``allowed_custom`` is the set of approved ``custom_descriptors
        [*].value`` strings (EMPTY when the vocabulary omits or
        declares an empty list); ``allowed_placement_role`` is the
        set of approved ``image_taxonomy.placement_role.allowed_values``
        strings (EMPTY when the vocabulary omits the optional
        placement_role block).
      * ``rc == 2`` and ``msg`` non-empty on file-level failure
        (URI-shaped path, symlink, missing, or not a regular file).
      * ``rc == 1`` and ``msg`` non-empty on JSON / schema / shape
        failure.
      * All three projections are ``None`` on any failure.
    """
    if _has_uri_scheme(str(vocab_path)):
        return None, None, None, 2, (
            f"G13: --descriptor-vocabulary {vocab_path} looks like a "
            f"URI; validate_mock_d_one_adapter_plan accepts local file "
            f"paths only."
        )
    if vocab_path.is_symlink():
        try:
            target = str(vocab_path.readlink())
        except OSError:
            target = "<unreadable>"
        return None, None, None, 2, (
            f"G13: --descriptor-vocabulary {vocab_path} is a symlink "
            f"(-> {target}); refusing to follow (broken or resolvable)."
        )
    if not vocab_path.exists():
        return None, None, None, 2, (
            f"G13: --descriptor-vocabulary {vocab_path} does not exist."
        )
    if not vocab_path.is_file():
        return None, None, None, 2, (
            f"G13: --descriptor-vocabulary {vocab_path} is not a "
            f"regular file."
        )
    try:
        raw = vocab_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, None, None, 1, (
            f"G13: cannot read --descriptor-vocabulary {vocab_path}: "
            f"{type(exc).__name__}: {exc}"
        )
    try:
        vocab_doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, None, None, 1, (
            f"G13: --descriptor-vocabulary {vocab_path} does not parse "
            f"as JSON: {type(exc).__name__}: {exc}"
        )
    if not isinstance(vocab_doc, dict):
        return None, None, None, 1, (
            f"G13: --descriptor-vocabulary {vocab_path} root is "
            f"{type(vocab_doc).__name__}, expected a JSON object."
        )
    if not DESCRIPTOR_VOCAB_SCHEMA.is_file():
        return None, None, None, 2, (
            f"G13: descriptor-vocabulary schema not found at "
            f"{DESCRIPTOR_VOCAB_SCHEMA}; the validator cannot run the "
            f"vocabulary gate without it."
        )
    try:
        schema = json.loads(
            DESCRIPTOR_VOCAB_SCHEMA.read_text(encoding="utf-8"),
        )
    except (OSError, json.JSONDecodeError) as exc:
        return None, None, None, 2, (
            f"G13: cannot load descriptor-vocabulary schema "
            f"{DESCRIPTOR_VOCAB_SCHEMA}: {type(exc).__name__}: {exc}"
        )
    schema_errors: list[str] = []
    _validate(vocab_doc, schema, "<root>", schema_errors)
    if schema_errors:
        return None, None, None, 1, (
            f"G13: --descriptor-vocabulary {vocab_path} does not "
            f"validate against {DESCRIPTOR_VOCAB_SCHEMA.name}: "
            + "; ".join(schema_errors)
        )
    # By this point the schema guarantees image_taxonomy is a dict with
    # each of the seven required dimensions, each carrying an
    # allowed_values list pinned to the canonical count and enum-locked
    # to canonical tokens. Project to per-dimension sets for cheap
    # membership checks at the request layer.
    allowed_per_dim: dict[str, set[str]] = {}
    image_taxonomy = vocab_doc["image_taxonomy"]
    for dim in TAXONOMY_FIELDS:
        dim_block = image_taxonomy[dim]
        allowed_per_dim[dim] = set(dim_block["allowed_values"])
    # custom_descriptors is OPTIONAL on the vocab file. When absent or
    # empty, the resulting allow-list is the empty set; the gate then
    # refuses any request that carries the custom_descriptor field.
    allowed_custom: set[str] = set()
    for entry in vocab_doc.get("custom_descriptors", []) or []:
        if isinstance(entry, dict):
            value = entry.get("value")
            if isinstance(value, str) and value:
                allowed_custom.add(value)
    # placement_role is OPTIONAL on the vocab. When absent, the
    # resulting allow-list is the empty set; the gate then refuses any
    # request that carries the placement_role field, mirroring the
    # "no allow-list, no permission" gate the custom_descriptor escape
    # hatch uses.
    allowed_placement_role: set[str] = set()
    placement_block = image_taxonomy.get(PLACEMENT_ROLE_FIELD)
    if isinstance(placement_block, dict):
        for v in placement_block.get("allowed_values", []) or []:
            if isinstance(v, str) and v:
                allowed_placement_role.add(v)
    return allowed_per_dim, allowed_custom, allowed_placement_role, 0, ""


# ---------------------------------------------------------------------------
# Core validator. Returns (exit_code, message). Caller prints the
# message and uses the exit code directly.
# ---------------------------------------------------------------------------


def validate_sidecar(
    *,
    plan: Path,
    d_one_spec: Path,
    image_manifest_spec: Path,
    require_both_placement_roles: bool = False,
    descriptor_vocabulary: Path | None = None,
) -> tuple[int, str]:
    """Apply every documented gate to the sidecar bytes and return
    ``(exit_code, message)``. Exit code conventions:

      * 0 — every gate passed.
      * 1 — at least one gate failed (sidecar contents do not match the
        committed spec / manifest, or carry forbidden substrings, or —
        when ``--descriptor-vocabulary`` is supplied — carry a taxonomy
        / custom_descriptor / placement_role value not in the matching
        vocabulary allow-list).
      * 2 — invocation / file / parse error (G1 / G2 failure or a
        schema file the validator could not load; also covers a URI-
        shaped / symlinked / missing / non-regular descriptor-vocabulary
        path).

    ``descriptor_vocabulary`` is OPTIONAL. When ``None``, gate G13 is
    silently skipped — the validator stays usable against any sidecar
    whose vocabulary paperwork lives elsewhere. When supplied, the
    vocabulary itself is gated by the same file / parse / schema checks
    the sidecar inputs go through, and every per-request taxonomy /
    ``custom_descriptor`` / ``placement_role`` value present on the
    sidecar must be a member of the matching vocabulary allow-list.
    """
    # ---- G1 inputs_are_regular_non_symlink_files ---------------------
    for label, path in (
        ("--plan", plan),
        ("--d-one-spec", d_one_spec),
        ("--image-manifest-spec", image_manifest_spec),
    ):
        msg = _refuse_input_path(path, label)
        if msg:
            return 2, "FAIL: " + msg

    # ---- byte snapshots for the read-only post-condition ------------
    try:
        plan_before = plan.read_bytes()
        spec_before = d_one_spec.read_bytes()
        manifest_before = image_manifest_spec.read_bytes()
    except OSError as exc:
        return 2, (
            f"FAIL: cannot read input bytes for the read-only post-"
            f"condition snapshot: {type(exc).__name__}: {exc}"
        )
    vocab_before: bytes | None = None
    if descriptor_vocabulary is not None:
        # Snapshot the vocabulary bytes BEFORE the schema-validate /
        # membership work so the read-only post-condition can re-read
        # and compare; a URI/symlink/missing path will surface from the
        # _load_descriptor_vocabulary helper below with rc=2, but we
        # still want a snapshot if the path exists and is readable.
        try:
            if (
                descriptor_vocabulary.exists()
                and descriptor_vocabulary.is_file()
                and not descriptor_vocabulary.is_symlink()
            ):
                vocab_before = descriptor_vocabulary.read_bytes()
        except OSError:
            vocab_before = None

    # ---- G2 inputs_parse_as_top_level_json_objects ------------------
    plan_doc, msg = _load_json_object(plan, "--plan")
    if plan_doc is None:
        return 2, "FAIL: " + msg
    spec_doc, msg = _load_json_object(d_one_spec, "--d-one-spec")
    if spec_doc is None:
        return 2, "FAIL: " + msg
    manifest_doc, msg = _load_json_object(
        image_manifest_spec, "--image-manifest-spec",
    )
    if manifest_doc is None:
        return 2, "FAIL: " + msg

    # ---- G3 sidecar_schema_validates --------------------------------
    if not PLAN_SCHEMA.is_file():
        return 2, (
            f"FAIL: plan schema not found at {PLAN_SCHEMA}; the "
            f"validator cannot run without it."
        )
    try:
        schema = json.loads(PLAN_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return 2, (
            f"FAIL: cannot load plan schema {PLAN_SCHEMA}: "
            f"{type(exc).__name__}: {exc}"
        )
    schema_errors: list[str] = []
    _validate(plan_doc, schema, "<root>", schema_errors)
    if schema_errors:
        return 1, (
            "FAIL: G3: --plan does not validate against "
            f"{PLAN_SCHEMA.name}: " + "; ".join(schema_errors)
        )

    # ---- G4 sidecar_schema_version_locked_to_4 ----------------------
    schema_version = plan_doc.get("schema_version")
    if schema_version != EXPECTED_SCHEMA_VERSION:
        return 1, (
            f"FAIL: G4: --plan schema_version is {schema_version!r}, "
            f"expected {EXPECTED_SCHEMA_VERSION!r}."
        )

    # ---- G5 sidecar_request_count_matches_len_requests --------------
    # The schema already guarantees ``requests`` is a non-empty list of
    # objects whose required fields are present. The cross-check below
    # only adds the ``request_count == len(requests)`` invariant.
    plan_requests = plan_doc["requests"]
    declared = plan_doc["request_count"]
    if declared != len(plan_requests):
        return 1, (
            f"FAIL: G5: --plan request_count={declared!r} disagrees "
            f"with len(requests)={len(plan_requests)}."
        )

    # ---- G6 sidecar_request_ids_are_unique --------------------------
    sidecar_by_id, msg = _index_by_id(plan_requests, "--plan")
    if msg:
        # _index_by_id surfaces the duplicate / shape diagnostic.
        return 1, "FAIL: G6: " + msg

    # ---- G7 sidecar_request_ids_match_d_one_spec_ids ----------------
    spec_by_id, msg = _index_by_id(
        spec_doc.get("requests"), "--d-one-spec",
    )
    if msg:
        return 1, "FAIL: G7: " + msg
    sidecar_ids = set(sidecar_by_id.keys())
    spec_ids = set(spec_by_id.keys())
    if sidecar_ids != spec_ids:
        missing = sorted(spec_ids - sidecar_ids)
        unexpected = sorted(sidecar_ids - spec_ids)
        return 1, (
            f"FAIL: G7: --plan request ids do not match --d-one-spec "
            f"request ids; missing on --plan: {missing!r}; unexpected "
            f"on --plan: {unexpected!r}."
        )

    # ---- G8 sidecar_placement_role_matches_d_one_spec_per_id --------
    # Empty/omitted role on one side must match empty/omitted on the
    # other side. A populated role in the spec MUST land byte-identical
    # in the sidecar; the inverse is checked too (a role that appeared
    # only in the sidecar is a drift the spec did not declare).
    for rid in sorted(spec_ids):
        spec_role = spec_by_id[rid].get("placement_role")
        plan_role = sidecar_by_id[rid].get("placement_role")
        # Treat absent and empty string as equivalent — the schema /
        # writer reject empty values upstream, so this normalisation
        # only matters for the diagnostic.
        spec_role_norm = spec_role if isinstance(spec_role, str) and spec_role else None
        plan_role_norm = plan_role if isinstance(plan_role, str) and plan_role else None
        if spec_role_norm != plan_role_norm:
            return 1, (
                f"FAIL: G8: --plan requests[id={rid!r}].placement_role="
                f"{plan_role!r} disagrees with --d-one-spec requests"
                f"[id={rid!r}].placement_role={spec_role!r}."
            )

    # ---- G9 sidecar_covers_both_placement_roles (opt-in) ------------
    if require_both_placement_roles:
        sidecar_roles: set[str] = set()
        for entry in plan_requests:
            role = entry.get("placement_role")
            if isinstance(role, str) and role:
                sidecar_roles.add(role)
        if sidecar_roles != REQUIRED_PLACEMENT_ROLES:
            missing = sorted(REQUIRED_PLACEMENT_ROLES - sidecar_roles)
            unexpected = sorted(sidecar_roles - REQUIRED_PLACEMENT_ROLES)
            return 1, (
                f"FAIL: G9: --plan placement_role coverage "
                f"{sorted(sidecar_roles)!r} does not equal "
                f"{sorted(REQUIRED_PLACEMENT_ROLES)!r}; missing: "
                f"{missing!r}; unexpected: {unexpected!r}."
            )

    # ---- G10 sidecar_manifest_local_path_matches_image_manifest_spec --
    manifest_by_id, msg = _index_manifest_local_paths(manifest_doc)
    if msg:
        return 1, "FAIL: G10: " + msg
    for rid in sorted(sidecar_by_id.keys()):
        plan_lp = sidecar_by_id[rid].get("manifest_local_path")
        if rid not in manifest_by_id:
            return 1, (
                f"FAIL: G10: --plan requests[id={rid!r}] has no matching "
                f"entry in --image-manifest-spec images[] (known ids: "
                f"{sorted(manifest_by_id.keys())!r})."
            )
        expected_lp = manifest_by_id[rid]
        if plan_lp != expected_lp:
            return 1, (
                f"FAIL: G10: --plan requests[id={rid!r}].manifest_local_"
                f"path={plan_lp!r} disagrees with --image-manifest-spec "
                f"images[id={rid!r}].local_path={expected_lp!r}."
            )

    # ---- G11 sidecar_manifest_local_path_is_safe --------------------
    for rid in sorted(sidecar_by_id.keys()):
        plan_lp = sidecar_by_id[rid]["manifest_local_path"]
        if not local_path_is_safe(plan_lp):
            return 1, (
                f"FAIL: G11: --plan requests[id={rid!r}].manifest_local_"
                f"path={plan_lp!r} is not a safe workspace-relative path "
                f"(rejects URI scheme, leading '/' / '\\' / '//', '..' "
                f"segment, surrounding whitespace, empty string)."
            )

    # ---- G12 sidecar_carries_no_forbidden_substrings ----------------
    # Two passes: (1) a raw-text substring scan over the sidecar bytes
    # catches a leak even if the structural walk missed a node; (2) the
    # structural walk surfaces the offending value when a leak occurs.
    raw_text = plan_before.decode("utf-8", errors="replace").lower()
    raw_hits: list[str] = [
        needle for needle in _FORBIDDEN_SUBSTRINGS
        if needle.lower() in raw_text
    ]
    if raw_hits:
        # Find the first matching string scalar so the diagnostic
        # points the operator at the offending field. The structural
        # walk is bounded by the file size, so this never traverses
        # more than what the schema already accepted.
        first_value = ""
        first_needle = raw_hits[0]
        for s in _walk_strings(plan_doc):
            if first_needle.lower() in s.lower():
                first_value = s
                break
        return 1, (
            f"FAIL: G12: --plan carries forbidden substring(s) "
            f"{raw_hits!r}; first offending value: {first_value!r}."
        )

    # ---- G13 sidecar_taxonomy_values_in_descriptor_vocabulary -------
    # Opt-in: only fires when --descriptor-vocabulary is supplied. The
    # vocabulary itself is loaded with the same gates the sidecar
    # inputs go through (URI / symlink / missing / non-regular / bad
    # JSON / wrong root type / schema-invalid). Membership is then
    # checked per request and per field; first failure aborts with a
    # diagnostic that names (request id, field, value, allowed set).
    if descriptor_vocabulary is not None:
        (
            allowed_per_dim, allowed_custom, allowed_placement_role,
            vocab_rc, vocab_msg,
        ) = _load_descriptor_vocabulary(descriptor_vocabulary)
        if vocab_rc != 0:
            return vocab_rc, "FAIL: " + vocab_msg
        for rid in sorted(sidecar_by_id.keys()):
            entry = sidecar_by_id[rid]
            for dim in TAXONOMY_FIELDS:
                if dim not in entry:
                    continue
                value = entry[dim]
                allowed = allowed_per_dim[dim]
                if value not in allowed:
                    return 1, (
                        f"FAIL: G13: --plan requests[id={rid!r}]."
                        f"{dim}={value!r} is not a member of the "
                        f"--descriptor-vocabulary image_taxonomy."
                        f"{dim}.allowed_values "
                        f"{sorted(allowed)!r}."
                    )
            if CUSTOM_DESCRIPTOR_FIELD in entry:
                value = entry[CUSTOM_DESCRIPTOR_FIELD]
                if value not in allowed_custom:
                    return 1, (
                        f"FAIL: G13: --plan requests[id={rid!r}]."
                        f"{CUSTOM_DESCRIPTOR_FIELD}={value!r} is not a "
                        f"member of the --descriptor-vocabulary "
                        f"custom_descriptors[*].value allow-list "
                        f"{sorted(allowed_custom)!r} (an absent / "
                        f"empty list refuses any request carrying "
                        f"this field)."
                    )
            if PLACEMENT_ROLE_FIELD in entry:
                value = entry[PLACEMENT_ROLE_FIELD]
                if value not in allowed_placement_role:
                    return 1, (
                        f"FAIL: G13: --plan requests[id={rid!r}]."
                        f"{PLACEMENT_ROLE_FIELD}={value!r} is not a "
                        f"member of the --descriptor-vocabulary "
                        f"image_taxonomy.placement_role.allowed_values "
                        f"{sorted(allowed_placement_role)!r} (an "
                        f"absent placement_role block on the "
                        f"vocabulary refuses any request carrying "
                        f"this field)."
                    )

    # ---- read-only post-condition ------------------------------------
    try:
        plan_after = plan.read_bytes()
        spec_after = d_one_spec.read_bytes()
        manifest_after = image_manifest_spec.read_bytes()
    except OSError as exc:
        return 1, (
            f"FAIL: cannot re-read input bytes for the read-only post-"
            f"condition snapshot: {type(exc).__name__}: {exc}"
        )
    if plan_after != plan_before:
        return 1, (
            f"FAIL: --plan {plan} bytes changed during validation "
            f"(expected byte-identical)."
        )
    if spec_after != spec_before:
        return 1, (
            f"FAIL: --d-one-spec {d_one_spec} bytes changed during "
            f"validation (expected byte-identical)."
        )
    if manifest_after != manifest_before:
        return 1, (
            f"FAIL: --image-manifest-spec {image_manifest_spec} bytes "
            f"changed during validation (expected byte-identical)."
        )
    if descriptor_vocabulary is not None and vocab_before is not None:
        try:
            vocab_after = descriptor_vocabulary.read_bytes()
        except OSError as exc:
            return 1, (
                f"FAIL: cannot re-read --descriptor-vocabulary "
                f"{descriptor_vocabulary} bytes for the read-only "
                f"post-condition snapshot: {type(exc).__name__}: {exc}"
            )
        if vocab_after != vocab_before:
            return 1, (
                f"FAIL: --descriptor-vocabulary {descriptor_vocabulary}"
                f" bytes changed during validation (expected "
                f"byte-identical)."
            )

    coverage_note = (
        f"; placement_role coverage == "
        f"{sorted(REQUIRED_PLACEMENT_ROLES)!r}"
        if require_both_placement_roles else ""
    )
    vocab_note = (
        f"; per-request taxonomy / custom_descriptor / placement_role "
        f"values land in --descriptor-vocabulary {descriptor_vocabulary}"
        if descriptor_vocabulary is not None else ""
    )
    return 0, (
        f"OK: {plan} validates against {PLAN_SCHEMA.name} AND matches "
        f"--d-one-spec {d_one_spec} (request ids + placement_role per "
        f"id) AND matches --image-manifest-spec {image_manifest_spec} "
        f"(manifest_local_path per id) AND carries no forbidden "
        f"substring{coverage_note}{vocab_note}."
    )


# ---------------------------------------------------------------------------
# Self-test. Builds an in-memory baseline (sidecar + spec + manifest)
# under a tempdir, asserts the baseline passes, then mutates one field
# per probe and asserts the matching gate fires. Mirrors the brand_
# preset.py / done_image_adapter.py self-test shape.
# ---------------------------------------------------------------------------


_BASELINE_SPEC = {
    "requests": [
        {
            "id": "cover_accent",
            "prompt": (
                "abstract geometric pattern in a calm neutral gradient, "
                "soft edges, leaves calm space on the right for the "
                "title overlay, no text, no logo"
            ),
            "intended_use": "hero-page accent",
            "placement_role": "hero_page",
        },
        {
            "id": "system_schematic",
            "prompt": (
                "schematic line diagram of a regional process flow with "
                "simple round nodes and arrows, grid-aligned, no logo"
            ),
            "intended_use": "local-region schematic",
            "placement_role": "local_region",
        },
    ],
}

_BASELINE_MANIFEST = {
    "images": [
        {
            "id": "cover_accent",
            "local_path": "media/cover_accent.png",
            "source": "d_one_local",
            "alt_text": "synthetic accent",
        },
        {
            "id": "system_schematic",
            "local_path": "media/system_schematic.png",
            "source": "d_one_local",
            "alt_text": "synthetic schematic",
        },
    ],
}

# Synthetic descriptor vocabulary used by the G13 probes. Mirrors the
# structure of the committed examples/synthetic_mock_image_trial/
# descriptor_vocabulary.json (canonical allow-lists for the seven
# taxonomy dimensions plus the optional placement_role block plus a
# minimal custom_descriptors[] allow-list). NOT a copy of any external
# vocabulary file. The committed-bundle probe (happy path #2) instead
# reads the committed vocabulary path directly so the same bytes the
# bundle smoke uses are exercised through the validator.
_BASELINE_VOCAB: dict = {
    "schema_version": 1,
    "note": "Synthetic D-One descriptor vocabulary for the validator self-test.",
    "kind_enum": [
        "color_token", "geometric_noun",
        "mood_adjective", "composition_adjective",
    ],
    "descriptors": [],
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
                "decorative_accent", "metaphor_icon", "divider_motif",
                "kpi_emblem", "cover_motif",
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
                "low_contrast", "soft_edges",
                "grid_aligned", "negative_space",
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
    "custom_descriptors": [
        {
            "kind": "composition_adjective",
            "value": "hero_centered_motif",
            "approved_in_review_ref": "synthetic_review.001",
        },
    ],
}

# Canonical seven-dimensional taxonomy values for cover_accent (matches
# every committed-bundle and synthetic-vocab allow-list).
_BASELINE_TAXONOMY_HERO: dict[str, str] = {
    "rendering_style": "flat_vector",
    "palette_family": "neutral_grey",
    "image_role": "decorative_accent",
    "layout_pattern": "single_center",
    "modifier": "soft_edges",
    "text_policy": "no_text",
    "subject_domain": "abstract_geometry",
    "custom_descriptor": "hero_centered_motif",
}

# Canonical seven-dimensional taxonomy values for system_schematic.
_BASELINE_TAXONOMY_LOCAL: dict[str, str] = {
    "rendering_style": "line_diagram",
    "palette_family": "dual_tone",
    "image_role": "metaphor_icon",
    "layout_pattern": "single_center",
    "modifier": "grid_aligned",
    "text_policy": "no_text",
    "subject_domain": "process_motif",
}


def _build_baseline_sidecar() -> dict:
    """Return a sidecar dict that matches ``_BASELINE_SPEC`` +
    ``_BASELINE_MANIFEST`` byte-identical. Used as the starting point
    for every self-test probe."""
    requests: list[dict] = []
    manifest_lp = {
        img["id"]: img["local_path"]
        for img in _BASELINE_MANIFEST["images"]
    }
    for req in _BASELINE_SPEC["requests"]:
        requests.append({
            "id": req["id"],
            "prompt": req["prompt"],
            "manifest_local_path": manifest_lp[req["id"]],
            "manifest_source": "d_one_local",
            "intended_use": req["intended_use"],
            "placement_role": req["placement_role"],
        })
    return {
        "schema_version": EXPECTED_SCHEMA_VERSION,
        "mode": "dry_run",
        "note": "D-One adapter contract stub: dry-run only.",
        "request_count": len(requests),
        "requests": requests,
    }


def _build_taxonomy_baseline_sidecar() -> dict:
    """Like ``_build_baseline_sidecar`` but every request additionally
    carries the seven taxonomy fields PLUS (for cover_accent only) the
    ``custom_descriptor`` escape hatch. Every value matches the
    ``_BASELINE_VOCAB`` allow-lists AND the committed examples/
    synthetic_mock_image_trial/descriptor_vocabulary.json allow-lists,
    so the same sidecar can be exercised against either vocab in the
    G13 probes."""
    sidecar = _build_baseline_sidecar()
    for req in sidecar["requests"]:
        if req["id"] == "cover_accent":
            req.update(_BASELINE_TAXONOMY_HERO)
        else:
            req.update(_BASELINE_TAXONOMY_LOCAL)
    return sidecar


def _write_vocab(td: Path, vocab: dict, *, name: str = "vocab.json") -> Path:
    """Write a vocabulary dict deterministically under ``td`` and
    return the path. Parents are created if missing so callers can
    pass a per-probe subdir without an explicit mkdir."""
    td.mkdir(parents=True, exist_ok=True)
    path = td / name
    path.write_text(
        json.dumps(vocab, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_inputs(
    td: Path,
    *,
    sidecar: dict,
    spec: dict | None = None,
    manifest: dict | None = None,
) -> tuple[Path, Path, Path]:
    """Write the three inputs deterministically (sorted keys, 2-space
    indent, trailing newline) and return the three paths. ``td`` is
    created (parents allowed) so callers can pass a per-probe subdir
    without an explicit mkdir."""
    td.mkdir(parents=True, exist_ok=True)
    plan = td / "mock_d_one_adapter_plan.json"
    d_one_spec = td / "d_one_spec.json"
    image_manifest_spec = td / "image_manifest_spec.json"
    plan.write_text(
        json.dumps(sidecar, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    d_one_spec.write_text(
        json.dumps(spec or _BASELINE_SPEC, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    image_manifest_spec.write_text(
        json.dumps(
            manifest or _BASELINE_MANIFEST, indent=2, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    return plan, d_one_spec, image_manifest_spec


def _self_test() -> int:
    print("=== validate_mock_d_one_adapter_plan self-test ===")
    results: list[tuple[bool, str]] = []

    def record(label: str, ok: bool, detail: str = "") -> None:
        suffix = f" -- {detail}" if not ok and detail else ""
        results.append((ok, f"{label}{suffix}"))

    with tempfile.TemporaryDirectory(
        prefix="szh_validate_mock_d_one_adapter_plan_",
    ) as raw_td:
        td = Path(raw_td)

        # ---- baseline passes -----------------------------------------
        plan, spec, manifest = _write_inputs(
            td / "baseline", sidecar=_build_baseline_sidecar(),
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
            require_both_placement_roles=True,
        )
        record(
            "baseline: unmodified baseline passes every gate "
            "(with --require-both-placement-roles)",
            rc == 0 and msg.startswith("OK"),
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G1: symlink --plan --------------------------------------
        td_g1 = td / "g1_symlink"
        td_g1.mkdir()
        real_plan, spec, manifest = _write_inputs(
            td_g1 / "real", sidecar=_build_baseline_sidecar(),
        )
        link_plan = td_g1 / "link.json"
        link_plan.symlink_to(real_plan)
        rc, msg = validate_sidecar(
            plan=link_plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G1: symlinked --plan is refused with rc=2",
            rc == 2 and "G1:" in msg and "symlink" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G1: URI shape --plan ------------------------------------
        rc, msg = validate_sidecar(
            plan=Path("http://attacker/x.json"),
            d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G1: URI-shaped --plan path is refused with rc=2",
            rc == 2 and "G1:" in msg and "URI" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G2: bad JSON --------------------------------------------
        td_g2 = td / "g2_bad_json"
        td_g2.mkdir()
        bad = td_g2 / "plan.json"
        bad.write_text("{not valid json", encoding="utf-8")
        good_spec = td_g2 / "spec.json"
        good_spec.write_text(json.dumps(_BASELINE_SPEC), encoding="utf-8")
        good_manifest = td_g2 / "manifest.json"
        good_manifest.write_text(
            json.dumps(_BASELINE_MANIFEST), encoding="utf-8",
        )
        rc, msg = validate_sidecar(
            plan=bad, d_one_spec=good_spec,
            image_manifest_spec=good_manifest,
        )
        record(
            "G2: malformed JSON --plan is refused with rc=2",
            rc == 2 and "G2:" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G3: schema-invalid (missing required field) -------------
        body = _build_baseline_sidecar()
        del body["mode"]
        plan, spec, manifest = _write_inputs(
            td / "g3_schema", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G3: sidecar missing required 'mode' field is refused (rc=1)",
            rc == 1 and "G3:" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G4: schema_version drift --------------------------------
        body = _build_baseline_sidecar()
        body["schema_version"] = EXPECTED_SCHEMA_VERSION + 1
        plan, spec, manifest = _write_inputs(
            td / "g4_version", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        # The schema's enum lock fires first (G3) when schema_version is
        # an out-of-range integer; G4 is the belt-and-braces gate so
        # either gate firing counts as a fail-closed refusal of a
        # drifted schema_version.
        record(
            "G4/G3: tampered schema_version is refused (rc=1)",
            rc == 1 and ("G3:" in msg or "G4:" in msg),
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G5: request_count desync --------------------------------
        body = _build_baseline_sidecar()
        body["request_count"] = len(body["requests"]) + 1
        plan, spec, manifest = _write_inputs(
            td / "g5_count", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G5: request_count != len(requests) is refused (rc=1)",
            rc == 1 and "G5:" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G6: duplicate request id -------------------------------
        # The plan schema does not declare uniqueItems on the requests
        # array (each id is independently a valid string), so a
        # duplicate id passes G3 and is caught at the cross-check
        # layer. Append a verbatim copy of the first request and
        # bump request_count so G5 still passes — G6 must be the
        # first gate to fire.
        body = _build_baseline_sidecar()
        body["requests"].append(dict(body["requests"][0]))
        body["request_count"] = len(body["requests"])
        plan, spec, manifest = _write_inputs(
            td / "g6_duplicate", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G6: duplicate request id is refused (rc=1)",
            rc == 1 and "G6:" in msg and "duplicates" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G7: missing request id ---------------------------------
        body = _build_baseline_sidecar()
        body["requests"] = [
            r for r in body["requests"]
            if r["id"] != "system_schematic"
        ]
        body["request_count"] = len(body["requests"])
        plan, spec, manifest = _write_inputs(
            td / "g7_missing", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G7: --plan missing a spec request id is refused (rc=1)",
            rc == 1 and "G7:" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G8: placement_role mismatch -----------------------------
        body = _build_baseline_sidecar()
        for r in body["requests"]:
            if r["id"] == "system_schematic":
                # Drift to the canonical-but-wrong value.
                r["placement_role"] = "hero_page"
        plan, spec, manifest = _write_inputs(
            td / "g8_role", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G8: --plan placement_role drift per id is refused (rc=1)",
            rc == 1 and "G8:" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G9: coverage gate (opt-in flag) ------------------------
        body = _build_baseline_sidecar()
        body["requests"] = [
            r for r in body["requests"] if r["placement_role"] == "hero_page"
        ]
        body["request_count"] = len(body["requests"])
        # Mirror the spec so the parity gates G7/G8 still pass; the
        # coverage gate G9 is the one we're isolating.
        single_spec = {
            "requests": [
                r for r in _BASELINE_SPEC["requests"]
                if r["placement_role"] == "hero_page"
            ],
        }
        single_manifest = {
            "images": [
                img for img in _BASELINE_MANIFEST["images"]
                if img["id"] == "cover_accent"
            ],
        }
        plan, spec, manifest = _write_inputs(
            td / "g9_coverage",
            sidecar=body, spec=single_spec, manifest=single_manifest,
        )
        rc_flag, msg_flag = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
            require_both_placement_roles=True,
        )
        record(
            "G9: single-role sidecar is refused under "
            "--require-both-placement-roles (rc=1)",
            rc_flag == 1 and "G9:" in msg_flag,
            f"rc={rc_flag}; msg={msg_flag!r}",
        )
        rc_noflag, msg_noflag = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G9: single-role sidecar is ACCEPTED without the coverage "
            "flag (rc=0) — proves the gate is opt-in",
            rc_noflag == 0 and msg_noflag.startswith("OK"),
            f"rc={rc_noflag}; msg={msg_noflag!r}",
        )

        # ---- G10: manifest_local_path parity drift -------------------
        body = _build_baseline_sidecar()
        for r in body["requests"]:
            if r["id"] == "cover_accent":
                r["manifest_local_path"] = "media/other_path.png"
        plan, spec, manifest = _write_inputs(
            td / "g10_lp_drift", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G10: --plan manifest_local_path drift from manifest is "
            "refused (rc=1)",
            rc == 1 and "G10:" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G11: unsafe manifest_local_path -------------------------
        # Build a manifest whose local_path itself is unsafe so the
        # sidecar's matching value also trips G11. G10 (parity) passes
        # because the values match; G11 (safety) fires because the
        # value itself is unsafe. (A pure URI value would also trip
        # G12's substring scan first — the ``../`` traversal value
        # below trips G11 without crossing G12's allow-list.)
        unsafe_manifest = {
            "images": [
                {
                    "id": "cover_accent",
                    "local_path": "media/cover_accent.png",
                    "source": "d_one_local",
                    "alt_text": "ok",
                },
                {
                    "id": "system_schematic",
                    "local_path": "media/system_schematic.png",
                    "source": "d_one_local",
                    "alt_text": "ok",
                },
            ],
        }
        body = _build_baseline_sidecar()
        # An absolute path is unsafe under local_path_is_safe and does
        # NOT contain any forbidden substring — isolates G11 from G12.
        for r in body["requests"]:
            if r["id"] == "cover_accent":
                r["manifest_local_path"] = "/etc/passwd_lookalike.png"
        unsafe_manifest["images"][0]["local_path"] = "/etc/passwd_lookalike.png"
        plan, spec, manifest = _write_inputs(
            td / "g11_unsafe",
            sidecar=body, manifest=unsafe_manifest,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G11: unsafe manifest_local_path (POSIX-absolute) is "
            "refused (rc=1)",
            rc == 1 and "G11:" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G12: URI substring in a prompt --------------------------
        body = _build_baseline_sidecar()
        body["requests"][0]["prompt"] = (
            body["requests"][0]["prompt"] + " http://attacker/x"
        )
        plan, spec, manifest = _write_inputs(
            td / "g12_uri", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G12: URI substring in a prompt is refused (rc=1)",
            rc == 1 and "G12:" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G12: credential substring in a note ---------------------
        body = _build_baseline_sidecar()
        body["note"] = (
            "D-One adapter contract stub: leaked password=hunter2."
        )
        plan, spec, manifest = _write_inputs(
            td / "g12_cred", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G12: credential substring (`password`) is refused (rc=1)",
            rc == 1 and "G12:" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G12: path-traversal substring in an intended_use -------
        body = _build_baseline_sidecar()
        body["requests"][0]["intended_use"] = "../escape attempt"
        plan, spec, manifest = _write_inputs(
            td / "g12_traversal", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G12: path-traversal substring (`../`) is refused (rc=1)",
            rc == 1 and "G12:" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G12: confidential marker in a prompt -------------------
        body = _build_baseline_sidecar()
        body["requests"][0]["prompt"] = (
            body["requests"][0]["prompt"] + " confidential roadmap."
        )
        plan, spec, manifest = _write_inputs(
            td / "g12_confidential", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G12: confidential marker is refused (rc=1)",
            rc == 1 and "G12:" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G12: public-hosting wording in a prompt ----------------
        body = _build_baseline_sidecar()
        body["requests"][0]["prompt"] = (
            body["requests"][0]["prompt"] + " then host publicly."
        )
        plan, spec, manifest = _write_inputs(
            td / "g12_public", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G12: public-hosting wording is refused (rc=1)",
            rc == 1 and "G12:" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G12: raw-source wording in a prompt --------------------
        body = _build_baseline_sidecar()
        body["requests"][0]["prompt"] = (
            body["requests"][0]["prompt"] + " (raw source text attached)."
        )
        plan, spec, manifest = _write_inputs(
            td / "g12_raw", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
        )
        record(
            "G12: raw-source wording is refused (rc=1)",
            rc == 1 and "G12:" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G13: happy path (synthetic vocab) -----------------------
        # Baseline taxonomy-bearing sidecar against a synthetic vocab
        # whose allow-lists cover every value the sidecar carries.
        # Confirms the gate accepts an in-vocabulary sidecar AND that
        # the optional flag does not break the gates that ran before.
        body = _build_taxonomy_baseline_sidecar()
        plan, spec, manifest = _write_inputs(
            td / "g13_happy", sidecar=body,
        )
        vocab_path = _write_vocab(td / "g13_happy", _BASELINE_VOCAB)
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
            require_both_placement_roles=True,
            descriptor_vocabulary=vocab_path,
        )
        record(
            "G13: in-vocabulary taxonomy-bearing sidecar passes "
            "against a synthetic vocab (rc=0)",
            rc == 0 and msg.startswith("OK"),
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G13: happy path (committed bundle vocab) ----------------
        # Same sidecar against the COMMITTED examples/synthetic_mock_
        # image_trial/descriptor_vocabulary.json. The committed vocab's
        # allow-lists are equivalent to _BASELINE_VOCAB so the same
        # taxonomy-bearing sidecar passes; the probe is a regression
        # gate against either vocab silently drifting away from the
        # other.
        committed_vocab = (
            REPO_ROOT / "examples" / "synthetic_mock_image_trial"
            / "descriptor_vocabulary.json"
        )
        if committed_vocab.is_file() and not committed_vocab.is_symlink():
            body = _build_taxonomy_baseline_sidecar()
            plan, spec, manifest = _write_inputs(
                td / "g13_happy_committed", sidecar=body,
            )
            rc, msg = validate_sidecar(
                plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
                require_both_placement_roles=True,
                descriptor_vocabulary=committed_vocab,
            )
            record(
                "G13: taxonomy-bearing sidecar passes against the "
                "COMMITTED examples/synthetic_mock_image_trial/"
                "descriptor_vocabulary.json (rc=0)",
                rc == 0 and msg.startswith("OK"),
                f"rc={rc}; msg={msg!r}",
            )

        # ---- G13: opt-in (no flag -> taxonomy-bearing sidecar OK) ---
        # The same taxonomy-bearing sidecar must still pass when no
        # vocabulary is supplied — proves the gate is opt-in and a
        # caller who does not pass the flag keeps the validator usable
        # against sidecars whose vocabulary paperwork lives elsewhere.
        body = _build_taxonomy_baseline_sidecar()
        plan, spec, manifest = _write_inputs(
            td / "g13_opt_in", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
            require_both_placement_roles=True,
        )
        record(
            "G13: taxonomy-bearing sidecar passes WITHOUT "
            "--descriptor-vocabulary (rc=0) — proves the gate is "
            "opt-in",
            rc == 0 and msg.startswith("OK"),
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G13: out-of-vocabulary text_policy ----------------------
        body = _build_taxonomy_baseline_sidecar()
        body["requests"][0]["text_policy"] = "custom_caption"
        plan, spec, manifest = _write_inputs(
            td / "g13_bad_text_policy", sidecar=body,
        )
        vocab_path = _write_vocab(td / "g13_bad_text_policy", _BASELINE_VOCAB)
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
            descriptor_vocabulary=vocab_path,
        )
        record(
            "G13: out-of-vocabulary text_policy is refused (rc=1)",
            rc == 1 and "G13:" in msg and "text_policy" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G13: out-of-vocabulary subject_domain -------------------
        body = _build_taxonomy_baseline_sidecar()
        body["requests"][1]["subject_domain"] = "topology_motif"
        plan, spec, manifest = _write_inputs(
            td / "g13_bad_subject_domain", sidecar=body,
        )
        vocab_path = _write_vocab(td / "g13_bad_subject_domain", _BASELINE_VOCAB)
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
            descriptor_vocabulary=vocab_path,
        )
        record(
            "G13: out-of-vocabulary subject_domain is refused (rc=1)",
            rc == 1 and "G13:" in msg and "subject_domain" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G13: out-of-vocabulary placement_role -------------------
        # The plan schema's placement_role pattern is enum-locked to
        # ['hero_page', 'local_region'], so we cannot drift the sidecar
        # value itself without tripping G3 first. Instead drop the
        # placement_role block from the vocab — allowed_placement_role
        # becomes the empty set, and the baseline sidecar's hero_page /
        # local_region values both fail closed under the same
        # "no allow-list, no permission" gate the custom_descriptor
        # escape hatch uses.
        vocab_without_placement = json.loads(json.dumps(_BASELINE_VOCAB))
        del vocab_without_placement["image_taxonomy"]["placement_role"]
        body = _build_taxonomy_baseline_sidecar()
        plan, spec, manifest = _write_inputs(
            td / "g13_bad_placement_role", sidecar=body,
        )
        vocab_path = _write_vocab(
            td / "g13_bad_placement_role", vocab_without_placement,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
            descriptor_vocabulary=vocab_path,
        )
        record(
            "G13: placement_role refused under a vocab missing the "
            "placement_role allow-list block (rc=1)",
            rc == 1 and "G13:" in msg and "placement_role" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G13: unapproved custom_descriptor -----------------------
        body = _build_taxonomy_baseline_sidecar()
        body["requests"][0]["custom_descriptor"] = "unapproved_descriptor"
        plan, spec, manifest = _write_inputs(
            td / "g13_bad_custom_descriptor", sidecar=body,
        )
        vocab_path = _write_vocab(
            td / "g13_bad_custom_descriptor", _BASELINE_VOCAB,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
            descriptor_vocabulary=vocab_path,
        )
        record(
            "G13: unapproved custom_descriptor is refused (rc=1)",
            rc == 1 and "G13:" in msg and "custom_descriptor" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G13: symlinked vocabulary path --------------------------
        td_g13_sym = td / "g13_symlink"
        td_g13_sym.mkdir()
        real_vocab = _write_vocab(td_g13_sym / "real", _BASELINE_VOCAB)
        link_vocab = td_g13_sym / "link.json"
        link_vocab.symlink_to(real_vocab)
        body = _build_taxonomy_baseline_sidecar()
        plan, spec, manifest = _write_inputs(
            td_g13_sym / "inputs", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
            descriptor_vocabulary=link_vocab,
        )
        record(
            "G13: symlinked --descriptor-vocabulary is refused (rc=2)",
            rc == 2 and "G13:" in msg and "symlink" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G13: URI-shaped vocabulary path -------------------------
        body = _build_taxonomy_baseline_sidecar()
        plan, spec, manifest = _write_inputs(
            td / "g13_uri", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
            descriptor_vocabulary=Path("http://attacker/vocab.json"),
        )
        record(
            "G13: URI-shaped --descriptor-vocabulary path is refused "
            "(rc=2)",
            rc == 2 and "G13:" in msg and "URI" in msg,
            f"rc={rc}; msg={msg!r}",
        )

        # ---- G13: malformed vocabulary JSON --------------------------
        td_g13_bad = td / "g13_bad_json"
        td_g13_bad.mkdir()
        bad_vocab = td_g13_bad / "vocab.json"
        bad_vocab.write_text("{not valid json", encoding="utf-8")
        body = _build_taxonomy_baseline_sidecar()
        plan, spec, manifest = _write_inputs(
            td_g13_bad / "inputs", sidecar=body,
        )
        rc, msg = validate_sidecar(
            plan=plan, d_one_spec=spec, image_manifest_spec=manifest,
            descriptor_vocabulary=bad_vocab,
        )
        record(
            "G13: malformed --descriptor-vocabulary JSON is refused "
            "(rc=1)",
            rc == 1 and "G13:" in msg and "JSON" in msg,
            f"rc={rc}; msg={msg!r}",
        )

    fails = [m for ok, m in results if not ok]
    for ok, m in results:
        print(("PASS " if ok else "FAIL ") + m)
    print()
    if fails:
        print(f"FAIL: {len(fails)} self-test scenario(s) did not pass.")
        return 1
    print(f"OK ({len(results)} self-test scenarios)")
    return 0


# ---------------------------------------------------------------------------
# CLI surface.
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only validator for the runner-written mock_d_one_"
            "adapter_plan.json evidence sidecar. Given --plan, "
            "--d-one-spec, and --image-manifest-spec, asserts the "
            "sidecar bytes match the committed spec + manifest and "
            "carry no forbidden substring. Stdlib-only. NETWORK-FREE. "
            "MOCK / STUB only — NOT real D-One integration; nothing "
            "calls D-One, MCP, Qoder, a public network, telemetry, "
            "any model API, or any external service."
        ),
    )
    parser.add_argument(
        "--plan", type=Path, default=None,
        help=(
            "Path to the runner-written mock_d_one_adapter_plan.json "
            "sidecar (regular non-symlink local file)."
        ),
    )
    parser.add_argument(
        "--d-one-spec", type=Path, default=None,
        help=(
            "Path to the committed d_one_spec.json (regular non-"
            "symlink local file)."
        ),
    )
    parser.add_argument(
        "--image-manifest-spec", type=Path, default=None,
        help=(
            "Path to the committed image_manifest_spec.json (regular "
            "non-symlink local file)."
        ),
    )
    parser.add_argument(
        "--require-both-placement-roles", action="store_true",
        help=(
            "Activate gate G9: refuse unless the sidecar's "
            "placement_role coverage equals "
            "{'hero_page', 'local_region'}. Required for the "
            "examples/synthetic_mock_image_trial bundle; opt-in so the "
            "validator stays usable against single-role bundles."
        ),
    )
    parser.add_argument(
        "--descriptor-vocabulary", type=Path, default=None,
        help=(
            "Optional. Path to a d_one_descriptor_vocabulary.json file "
            "(regular non-symlink local file). When supplied, activates "
            "gate G13: every per-request taxonomy field present on the "
            "sidecar (rendering_style / palette_family / image_role / "
            "layout_pattern / modifier / text_policy / subject_domain) "
            "must be a member of the matching image_taxonomy.<dim>."
            "allowed_values; every custom_descriptor value must be a "
            "member of custom_descriptors[*].value; every placement_role "
            "value must be a member of image_taxonomy.placement_role."
            "allowed_values. Omitting the flag keeps the validator "
            "usable against any sidecar whose vocabulary paperwork "
            "lives elsewhere — single-use sidecars without taxonomy "
            "can still be checked against spec + manifest alone."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run the built-in baseline + per-gate refusal probes and "
            "exit. No --plan / --d-one-spec / --image-manifest-spec / "
            "--descriptor-vocabulary are required when --self-test is "
            "supplied."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if any(
            v is not None for v in (
                args.plan, args.d_one_spec, args.image_manifest_spec,
                args.descriptor_vocabulary,
            )
        ):
            print(
                "error: --plan / --d-one-spec / --image-manifest-spec "
                "/ --descriptor-vocabulary are not compatible with "
                "--self-test.",
                file=sys.stderr,
            )
            return 2
        return _self_test()

    missing = [
        flag for flag, value in (
            ("--plan", args.plan),
            ("--d-one-spec", args.d_one_spec),
            ("--image-manifest-spec", args.image_manifest_spec),
        )
        if value is None
    ]
    if missing:
        print(
            f"error: {', '.join(missing)} required (or pass --self-test).",
            file=sys.stderr,
        )
        return 2

    rc, msg = validate_sidecar(
        plan=args.plan,
        d_one_spec=args.d_one_spec,
        image_manifest_spec=args.image_manifest_spec,
        require_both_placement_roles=args.require_both_placement_roles,
        descriptor_vocabulary=args.descriptor_vocabulary,
    )
    print(msg)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
