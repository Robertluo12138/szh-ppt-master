#!/usr/bin/env python3
"""Local validator for the generated-image provenance handoff record.

Read-only, stdlib-only validator for the committed-safe JSON record
contract documented at ``schemas/generated_image_provenance.schema.json``.
A reviewer copies the canonical template at
``examples/generated_image_provenance_template.json`` as a starting
point and fills in the per-run values that survived the in-tempdir
mock pipeline; this validator re-checks the committed-safe shape
against the schema PLUS the documented semantic gates.

This script is the **committed-safe** half of the generated-image
provenance contract. The **runtime** half is
``scripts/mock_generated_image_provenance_smoke.py --self-test``: it
writes a TEMP-ONLY provenance object under a per-run tempdir that the
tempdir cleanup removes on exit, never commits, and records absolute
on-disk paths the validator's path-safety gate would intentionally
refuse. The deliberate narrowed mapping between the two shapes — the
runtime smoke's absolute tempdir paths vs the committed-safe / package-
safe placeholder paths the schema and this validator gate — is
documented in ``references/quality-gates.md``.

The validator is **read-only**: it never writes, mutates, or removes
any file, and never calls D-One / MCP / a public network / any model
API / image search / Qoder / telemetry. A schema-PASS plus every-gate-
PASS result certifies the record is internally consistent and self-
honest about the MOCK / STUB nature of the chain that produced it. It
does NOT certify a real D-One run happened — by contract, no such run
is performed by this skill today.

Gates applied (every failed gate is reported; the script exits
non-zero on any failure):

  G1  ``readable_json_object``
    - the input file must exist as a regular non-symlink file;
    - the bytes must parse as JSON;
    - the parsed JSON must be a top-level object.

  G2  ``schema_subset_valid``
    - the record validates against
      ``schemas/generated_image_provenance.schema.json`` under the
      same draft-07 subset ``scripts/validate_artifacts.py``
      implements (``additionalProperties:false`` at every declared
      object level; ``schema_version`` enum-locked to ``"1"``;
      ``evidence_id`` enum-locked to ``"generated_image_provenance"``).

  G3  ``real_d_one_status_phrasing``
    - ``real_d_one_status`` MUST contain the literal ``UNVERIFIED``
      substring (case-insensitive) AND at least one negation token
      paired with a forbidden service noun, so a tampered status
      string cannot smuggle a positive claim past the schema's
      length-only bounds.

  G4  ``summary_ok_consistency``
    - ``summary.ok == true`` requires every documented sub-condition:
        * ``len(rows) == summary.row_count`` AND ``len(rows) >= 1``;
        * ``summary.failures == []``;
        * sorted ``placement_role`` values across rows equal exactly
          ``["hero_page", "local_region"]`` AND
          ``summary.placement_role_coverage`` agrees;
        * sorted ``text_policy`` values across rows carry at least
          ``MIN_TEXT_POLICIES`` (today: 2) distinct entries AND
          ``summary.text_policy_coverage`` agrees;
        * every row's ``asset.error`` is the empty string;
        * every row's ``asset.exists`` is True.

  G5  ``per_row_well_formed``
    - every row carries every required string field as a non-empty
      string; the schema's per-field types + ``minLength`` already
      enforce this — G5 surfaces a clear diagnostic when a field
      mismatch sneaks past a future schema relaxation.

  G6  ``request_id_unique``
    - no duplicate ``rows[*].id`` values; identifier collisions
      across rows are refused.

  G7  ``placement_role_coverage``
    - the set of ``rows[*].placement_role`` equals exactly
      ``{"hero_page", "local_region"}``; ``summary.placement_role_coverage``
      cross-checked for agreement.

  G8  ``text_policy_diversity``
    - the set of ``rows[*].text_policy`` carries at least
      ``MIN_TEXT_POLICIES`` distinct entries; a record where every
      row collapsed to one value (typically all ``no_text``) is
      refused. ``summary.text_policy_coverage`` cross-checked for
      agreement.

  G9  ``spec_sidecar_row_parity``
    - for each row, ``row.placement_role`` /
      ``row.text_policy`` / ``row.subject_domain`` /
      ``row.manifest_local_path`` MUST equal ``spec.<field>`` AND
      ``sidecar.<field>`` byte-identically — drift here would mean
      the bundle / sidecar / row record disagreed on the per-id
      taxonomy.

  G10 ``asset_shape_valid``
    - every row's ``asset`` block MUST carry: ``sha256`` matching
      ``^[0-9a-f]{64}$``; ``byte_count >= 1``; ``extension`` in
      ``{png, jpg, jpeg}``; ``media_type`` projection consistent
      with extension (``png -> image/png``, ``jpg``/``jpeg ->
      image/jpeg``); ``error`` is empty when ``summary.ok`` is True.

  G11 ``pptx_media_sha_match``
    - every row's ``pptx_media.sha256`` MUST equal ``asset.sha256``
      byte-for-byte; ``pptx_media.part`` MUST start with
      ``ppt/media/`` AND carry no URI / traversal / leading-slash
      shape; ``pptx_media.content_type`` MUST be one of
      ``image/png`` / ``image/jpeg``.

  G12 ``path_safety_committed_safe``
    - every path-typed field (``bundle_path``, ``workspace_path``,
      ``report_dir``, ``pptx_path``, ``sidecar.path``,
      ``inventory.path``, ``rows[*].manifest_local_path``,
      ``rows[*].sidecar.manifest_local_path``, ``rows[*].asset.path``,
      ``rows[*].pptx_media.part``) MUST be a committed-safe value:
      no URI scheme prefix; no ``..`` traversal segment; no leading
      ``/`` (absolute-output escape) — the runtime smoke's absolute
      tempdir paths are intentionally NOT what this validator gates
      (see module docstring + references/quality-gates.md for the
      deliberate narrowed mapping).

  G13 ``string_safety_scan``
    - every string scalar in the record is scanned for credential /
      token / API-key / ``sk-`` / ``ghp_`` / JWT / AWS-key / PEM /
      long-hex blob / bearer / bearer-token wording /
      ``password:`` / ``api_key:`` / ``token:`` / ``secret:``
      literals AND assignment shapes such as ``token=value`` /
      ``secret=value`` / ``password=value`` / ``api_key = value``;
      public-upload / public-share / public-hosting / image-hosting
      wording; AND raw-source / confidential / customer markers. The
      64-char sha256 fields are excluded from the long-hex scan (they
      have their own pattern lock at the schema layer; including them
      would force a false positive).

  G14 ``real_d_one_claim_refusal``
    - the validator walks the full record and refuses any string
      scalar OR boolean True that asserts a real / live / MCP /
      public-network / model-API / image-search / Qoder success.
      A claim is positive iff a forbidden noun is in scope (in the
      value OR in the enclosing dict key) AND a forbidden success
      verb (``verified`` / ``passed`` / ``succeeded`` / ``called``
      / ``reached`` / ``fetched`` / ``received`` / ``online`` /
      ``live`` / ``enabled``) appears at a word boundary AND is NOT
      preceded by a negation token in a local 15-char window. The
      canonical UNVERIFIED status sentence pairs ``real D-One`` with
      ``called`` but the verb is preceded by ``is NOT`` inside the
      window, so it does NOT trip the gate.

  G15 ``inventory_external_zero``
    - ``inventory.relationships_external_count`` MUST be 0; any
      external relationship in the produced PPTX is refused.

  G16 ``sidecar_schema_version_locked``
    - ``sidecar.schema_version`` MUST equal 4
      (``LOCKED_PLAN_SCHEMA_VERSION``). A future paired bump moves
      both the runtime smoke and this validator forward in lockstep.

  G17 ``internal_consistency``
    - cross-field invariants that hold ALWAYS (regardless of
      ``summary.ok``) so a tampered record cannot smuggle a self-
      contradictory shape past the per-field schema layer + the
      ok-conditional G4 gate:
        * ``summary.row_count == len(rows)``;
        * ``sidecar.request_count == len(rows)`` (the rows mirror
          the sidecar's requests 1:1; a request count that
          disagrees with the actual row tally is contradictory);
        * ``(summary.ok == true) iff (summary.failures == [])`` —
          a record claiming ``ok=true`` with non-empty failures, or
          claiming ``ok=false`` with empty failures, is refused;
        * ``inventory.ok == true`` implies
          ``inventory.findings_empty == true`` — a record asserting
          the inventory passed while also recording non-empty
          findings is contradictory;
        * per row: ``asset.exists == true`` (the schema's per-row
          ``byte_count >= 1`` + ``sha256`` pattern lock + extension
          enum already require the asset to be materialized; a
          row recording ``exists == false`` alongside those values
          is contradictory and refused);
        * per row: ``asset.error == ""`` (a row carrying any error
          diagnostic alongside a positive ``byte_count`` + valid
          ``sha256`` is contradictory);
        * per row: every ``pptx_media.referencing_slides[i]`` value
          falls within ``[1, inventory.slide_count]`` — referencing
          a slide index that does not exist in the produced PPTX is
          contradictory.

Exit codes:
  0  every gate passed.
  1  one or more gates failed.
  2  invocation / file / parse error.

CLI:
  python3 scripts/validate_generated_image_provenance.py \\
      --evidence <path/to/generated_image_provenance.json>
  python3 scripts/validate_generated_image_provenance.py --self-test

Stdlib-only. NETWORK-FREE. NO real D-One. NO MCP. NO Qoder. NO model
API. NO image search. NO telemetry. The validator never produces or
modifies any artifact; the committed-safe schema is the only artifact
this contract names.
"""
from __future__ import annotations

import sys

# Refuse to write `.pyc` files for any module imported by this script.
# The validator's contract is read-only; without this gate the first-
# party import below would silently leak
# ``scripts/__pycache__/validate_artifacts.cpython-*.pyc`` on a clean
# checkout. Must come BEFORE any first-party import — the interpreter
# checks the flag at bytecode-write time.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "schemas"
EXAMPLES_DIR = REPO_ROOT / "examples"

sys.path.insert(0, str(SCRIPTS_DIR))

from validate_artifacts import _validate  # noqa: E402

SCHEMA_PATH = (
    SCHEMAS_DIR / "generated_image_provenance.schema.json"
)
COMMITTED_TEMPLATE = (
    EXAMPLES_DIR / "generated_image_provenance_template.json"
)

EXPECTED_SCHEMA_VERSION = "1"
EXPECTED_EVIDENCE_ID = "generated_image_provenance"
EXPECTED_SIDECAR_SCHEMA_VERSION = 4
EXPECTED_PLACEMENT_ROLES: frozenset[str] = frozenset({
    "hero_page", "local_region",
})
MIN_TEXT_POLICIES = 2
_ALLOWED_EXTS: frozenset[str] = frozenset({"png", "jpg", "jpeg"})
_ALLOWED_MEDIA_TYPES: frozenset[str] = frozenset({
    "image/png", "image/jpeg",
})
_EXT_TO_MEDIA_TYPE: dict[str, str] = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_ROW_STRING_FIELDS: tuple[str, ...] = (
    "id", "placement_role", "text_policy", "subject_domain",
    "manifest_local_path",
)
_PARITY_FIELDS: tuple[str, ...] = (
    "placement_role", "text_policy", "subject_domain",
    "manifest_local_path",
)

# ---------------------------------------------------------------------------
# Path-safety scan — committed-safe shape only.
# ---------------------------------------------------------------------------

_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _path_safety_failures(label: str, value: str) -> list[str]:
    out: list[str] = []
    if _URI_SCHEME_PREFIX.match(value):
        out.append(
            f"{label}: refused — value {value!r} carries a URI "
            f"scheme prefix"
        )
    parts = value.replace("\\", "/").split("/")
    if ".." in parts:
        out.append(
            f"{label}: refused — value {value!r} contains a '..' "
            f"traversal segment"
        )
    if value.startswith("/") or value.startswith("~"):
        out.append(
            f"{label}: refused — value {value!r} is absolute / home-"
            f"relative (committed-safe contract requires workspace-"
            f"relative or placeholder shapes; absolute-output escape)"
        )
    return out


def _check_path_safety(record: dict) -> list[str]:
    failures: list[str] = []
    for key in (
        "bundle_path", "workspace_path", "report_dir", "pptx_path",
    ):
        val = record.get(key)
        if isinstance(val, str):
            failures.extend(_path_safety_failures(key, val))
    sidecar = record.get("sidecar")
    if isinstance(sidecar, dict):
        v = sidecar.get("path")
        if isinstance(v, str):
            failures.extend(_path_safety_failures("sidecar.path", v))
    inv = record.get("inventory")
    if isinstance(inv, dict):
        v = inv.get("path")
        if isinstance(v, str):
            failures.extend(_path_safety_failures("inventory.path", v))
    for idx, row in enumerate(record.get("rows") or []):
        if not isinstance(row, dict):
            continue
        for k in ("manifest_local_path",):
            v = row.get(k)
            if isinstance(v, str):
                failures.extend(_path_safety_failures(
                    f"rows[{idx}].{k}", v,
                ))
        sc = row.get("sidecar")
        if isinstance(sc, dict):
            v = sc.get("manifest_local_path")
            if isinstance(v, str):
                failures.extend(_path_safety_failures(
                    f"rows[{idx}].sidecar.manifest_local_path", v,
                ))
        asset = row.get("asset")
        if isinstance(asset, dict):
            v = asset.get("path")
            if isinstance(v, str):
                failures.extend(_path_safety_failures(
                    f"rows[{idx}].asset.path", v,
                ))
        media = row.get("pptx_media")
        if isinstance(media, dict):
            v = media.get("part")
            if isinstance(v, str):
                failures.extend(_path_safety_failures(
                    f"rows[{idx}].pptx_media.part", v,
                ))
    return failures


# ---------------------------------------------------------------------------
# String-safety scan — credential / public-hosting / confidential.
# ---------------------------------------------------------------------------

_FORBIDDEN_URI_SCHEMES: tuple[str, ...] = (
    "http", "https", "ftp", "ftps", "file", "data",
    "javascript", "vbscript", "mailto", "tel", "sms",
    "gopher", "magnet", "ws", "wss",
)
_URI_SCHEME_RE = re.compile(
    r"(?i)\b(?:" + "|".join(_FORBIDDEN_URI_SCHEMES) + r"):",
)
_TRAVERSAL_RE = re.compile(r"\.\.")

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
    ("sk- prefix", re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")),
    ("ghp_ prefix", re.compile(r"\bghp_[A-Za-z0-9]{16,}\b")),
    ("credential assignment", re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|apikey|"
        r"api-key|token|access[_-]?key|client[_-]?secret|"
        r"private[_-]?key)\s*[:=]\s*[^\s,;]+"
    )),
    ("bearer token wording", re.compile(
        r"(?i)\bbearer\s+token\b"
    )),
)
_CREDENTIAL_LITERALS: tuple[str, ...] = (
    "password:", "passwd:", "secret:",
    "api_key:", "apikey:", "api-key:",
    "token:", "access_key:", "client_secret:", "private_key:",
    "token placeholder",
)

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
    ("image hosting", re.compile(
        r"\bimage\s+hosting\b", re.IGNORECASE
    )),
)

_CONFIDENTIAL_LITERALS: tuple[str, ...] = (
    "confidential",
    "customer_id", "customer id:",
    "account_id", "account id:",
    "internal use only", "do not distribute", "do_not_distribute",
)
_SOURCE_MARKER_LITERALS: tuple[str, ...] = (
    "<source>", "</source>", "[source]", "[/source]",
    "raw source", "begin source", "end source",
    "source document:", "source text:", "from the source",
)

# Paths-shaped fields whose values are 64-char hex by design. Exclude
# them from the long-hex credential pattern so the sha256 fields do
# not false-green the gate. The exclusion is by ``json_path`` only;
# any other 64-char-hex value still trips.
_SHA256_EXCLUDED_PATHS_SUFFIX: tuple[str, ...] = (
    ".asset.sha256", ".pptx_media.sha256",
)


def _iter_strings(node, path: str = ""):
    if isinstance(node, dict):
        for k, v in node.items():
            sub = f"{path}.{k}" if path else str(k)
            yield from _iter_strings(v, sub)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _iter_strings(item, f"{path}[{i}]")
    elif isinstance(node, str):
        yield (path, node)


def _scan_unsafe_string(jpath: str, value: str) -> list[str]:
    hits: list[str] = []
    low = value.lower()
    if _URI_SCHEME_RE.search(value):
        hits.append("URI/URL scheme")
    if _TRAVERSAL_RE.search(value):
        hits.append("path-traversal '..'")
    sha_excluded = any(
        jpath.endswith(suf) for suf in _SHA256_EXCLUDED_PATHS_SUFFIX
    )
    for label, pattern in _CREDENTIAL_PATTERNS:
        if label == "long hex blob" and sha_excluded:
            continue
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


def _check_string_safety(record: dict) -> list[str]:
    errors: list[str] = []
    for jpath, value in _iter_strings(record):
        if jpath in {"schema_version", "evidence_id"}:
            continue
        hits = _scan_unsafe_string(jpath, value)
        for hit in hits:
            errors.append(
                f"{jpath}: refused — {hit} in value {value!r}"
            )
    return errors


# ---------------------------------------------------------------------------
# Real-D-One claim refusal walker.
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
    if start > 0 and text_low[start - 1].isalnum():
        return False
    if end < len(text_low) and text_low[end].isalnum():
        return False
    return True


def _verb_is_negated(text_low: str, verb_start: int) -> bool:
    window_start = max(0, verb_start - _NEGATION_WINDOW_CHARS)
    raw = text_low[window_start:verb_start]
    normalized = raw.replace("_", " ").replace("-", " ")
    window = " " + normalized + " "
    return any(token in window for token in _NEGATION_TOKENS)


def _string_asserts_success(
    value: str, *, key_provides_noun: bool = False,
) -> bool:
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
            if (_is_word_boundary(low, pos, end)
                    and not _verb_is_negated(low, pos)):
                return True
            idx = pos + 1
    return False


def _check_real_d_one_refusal(record) -> list[str]:
    failures: list[str] = []

    def _walk(node, path: str, *, key_provides_noun: bool = False):
        if isinstance(node, dict):
            for k, v in node.items():
                key_low = str(k).lower()
                sub = f"{path}.{k}" if path else str(k)
                child_key_has_noun = any(
                    noun in key_low for noun in _FORBIDDEN_CLAIM_NOUNS
                )
                effective_provides_noun = (
                    key_provides_noun or child_key_has_noun
                )
                if (
                    v is True
                    and effective_provides_noun
                    and child_key_has_noun
                ):
                    failures.append(
                        f"{sub}: refused real-D-One / MCP / network /"
                        f" model / image-search / Qoder boolean claim"
                    )
                _walk(
                    v, sub,
                    key_provides_noun=effective_provides_noun,
                )
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _walk(
                    item, f"{path}[{i}]",
                    key_provides_noun=key_provides_noun,
                )
        elif isinstance(node, str):
            if _string_asserts_success(
                node, key_provides_noun=key_provides_noun,
            ):
                failures.append(
                    f"{path}: refused real-D-One / MCP / network / "
                    f"model / image-search / Qoder success claim "
                    f"({node!r})"
                )

    _walk(record, "")
    return failures


# ---------------------------------------------------------------------------
# Semantic gate helpers.
# ---------------------------------------------------------------------------


def _check_schema_version(record: dict) -> list[str]:
    v = record.get("schema_version")
    if v != EXPECTED_SCHEMA_VERSION:
        return [
            f"schema_version: expected {EXPECTED_SCHEMA_VERSION!r}, "
            f"got {v!r}"
        ]
    return []


def _check_evidence_id(record: dict) -> list[str]:
    v = record.get("evidence_id")
    if v != EXPECTED_EVIDENCE_ID:
        return [
            f"evidence_id: expected {EXPECTED_EVIDENCE_ID!r}, "
            f"got {v!r}"
        ]
    return []


def _check_real_d_one_status_phrasing(record: dict) -> list[str]:
    errors: list[str] = []
    status = record.get("real_d_one_status")
    if not isinstance(status, str):
        return ["real_d_one_status: expected non-empty string"]
    low = status.lower()
    if "unverified" not in low:
        errors.append(
            "real_d_one_status: missing required 'UNVERIFIED' "
            "substring (the canonical sentence must keep its self-"
            "describing UNVERIFIED marker)"
        )
    padded = " " + low + " "
    has_negation = (
        " not " in padded
        or " no " in padded
        or " never " in padded
        or " without " in padded
        or "n't" in low
    )
    has_noun = any(
        noun in low for noun in _FORBIDDEN_CLAIM_NOUNS
    )
    if not (has_negation and has_noun):
        errors.append(
            "real_d_one_status: missing required negated / no-call "
            "wording for a forbidden service (the sentence must "
            "explicitly state that real D-One / MCP / public network "
            "/ model API / image search / Qoder was NOT called)"
        )
    return errors


def _check_per_row_well_formed(record: dict) -> list[str]:
    errors: list[str] = []
    rows = record.get("rows")
    if not isinstance(rows, list):
        return errors
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(
                f"rows[{i}]: expected object, got {type(row).__name__}"
            )
            continue
        for field in _REQUIRED_ROW_STRING_FIELDS:
            v = row.get(field)
            if not (isinstance(v, str) and v):
                errors.append(
                    f"rows[{i}].{field}: expected non-empty string, "
                    f"got {v!r}"
                )
    return errors


def _check_request_id_unique(record: dict) -> list[str]:
    errors: list[str] = []
    rows = record.get("rows")
    if not isinstance(rows, list):
        return errors
    seen: dict[str, int] = {}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        if not isinstance(rid, str) or not rid:
            continue
        if rid in seen:
            errors.append(
                f"rows[{i}].id: duplicate id {rid!r} (already at "
                f"rows[{seen[rid]}]); refused"
            )
        else:
            seen[rid] = i
    return errors


def _row_placement_roles(record: dict) -> set[str]:
    out: set[str] = set()
    for row in (record.get("rows") or []):
        if isinstance(row, dict):
            v = row.get("placement_role")
            if isinstance(v, str):
                out.add(v)
    return out


def _row_text_policies(record: dict) -> set[str]:
    out: set[str] = set()
    for row in (record.get("rows") or []):
        if isinstance(row, dict):
            v = row.get("text_policy")
            if isinstance(v, str):
                out.add(v)
    return out


def _check_placement_role_coverage(record: dict) -> list[str]:
    errors: list[str] = []
    seen = _row_placement_roles(record)
    if seen != EXPECTED_PLACEMENT_ROLES:
        errors.append(
            f"rows[*].placement_role coverage: expected "
            f"{sorted(EXPECTED_PLACEMENT_ROLES)!r}, got "
            f"{sorted(seen)!r}"
        )
    summary = record.get("summary")
    if isinstance(summary, dict):
        cov = summary.get("placement_role_coverage")
        if isinstance(cov, list):
            if sorted(set(cov)) != sorted(seen):
                errors.append(
                    f"summary.placement_role_coverage ({cov!r}) "
                    f"disagrees with rows[*].placement_role "
                    f"({sorted(seen)!r})"
                )
    return errors


def _check_text_policy_diversity(record: dict) -> list[str]:
    errors: list[str] = []
    seen = _row_text_policies(record)
    if len(seen) < MIN_TEXT_POLICIES:
        errors.append(
            f"rows[*].text_policy diversity: expected at least "
            f"{MIN_TEXT_POLICIES} distinct values, got "
            f"{sorted(seen)!r}"
        )
    summary = record.get("summary")
    if isinstance(summary, dict):
        cov = summary.get("text_policy_coverage")
        if isinstance(cov, list):
            if sorted(set(cov)) != sorted(seen):
                errors.append(
                    f"summary.text_policy_coverage ({cov!r}) "
                    f"disagrees with rows[*].text_policy "
                    f"({sorted(seen)!r})"
                )
    return errors


def _check_spec_sidecar_row_parity(record: dict) -> list[str]:
    errors: list[str] = []
    for i, row in enumerate(record.get("rows") or []):
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        spec = row.get("spec") or {}
        sidecar = row.get("sidecar") or {}
        for field in _PARITY_FIELDS:
            # spec block does NOT carry manifest_local_path; skip it
            # on the spec-side comparison.
            row_v = row.get(field)
            sidecar_v = sidecar.get(field) if isinstance(
                sidecar, dict,
            ) else None
            if field == "manifest_local_path":
                if row_v != sidecar_v:
                    errors.append(
                        f"rows[{i}] id={rid!r} manifest_local_path "
                        f"drift: row={row_v!r} sidecar={sidecar_v!r}"
                    )
                continue
            spec_v = spec.get(field) if isinstance(spec, dict) else None
            if not (row_v == spec_v == sidecar_v):
                errors.append(
                    f"rows[{i}] id={rid!r} {field} parity drift: "
                    f"row={row_v!r} spec={spec_v!r} "
                    f"sidecar={sidecar_v!r}"
                )
    return errors


def _check_asset_shape(record: dict) -> list[str]:
    errors: list[str] = []
    for i, row in enumerate(record.get("rows") or []):
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        asset = row.get("asset")
        if not isinstance(asset, dict):
            errors.append(f"rows[{i}].asset: expected object")
            continue
        sha = asset.get("sha256")
        if not (isinstance(sha, str) and _SHA256_RE.match(sha)):
            errors.append(
                f"rows[{i}] id={rid!r} asset.sha256={sha!r} is not "
                f"a lowercase 64-char hex string"
            )
        bc = asset.get("byte_count")
        if not (isinstance(bc, int) and not isinstance(bc, bool)
                and bc >= 1):
            errors.append(
                f"rows[{i}] id={rid!r} asset.byte_count={bc!r} is "
                f"not a positive integer"
            )
        ext = asset.get("extension")
        if not (isinstance(ext, str) and ext.lower() in _ALLOWED_EXTS):
            errors.append(
                f"rows[{i}] id={rid!r} asset.extension={ext!r} is "
                f"not one of {sorted(_ALLOWED_EXTS)!r}"
            )
        else:
            expected_media = _EXT_TO_MEDIA_TYPE.get(ext.lower())
            actual_media = asset.get("media_type")
            if actual_media != expected_media:
                errors.append(
                    f"rows[{i}] id={rid!r} asset.media_type="
                    f"{actual_media!r} does not match extension="
                    f"{ext!r} (expected {expected_media!r})"
                )
    return errors


def _check_pptx_media_match(record: dict) -> list[str]:
    errors: list[str] = []
    for i, row in enumerate(record.get("rows") or []):
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        media = row.get("pptx_media")
        if not isinstance(media, dict):
            errors.append(
                f"rows[{i}] id={rid!r} pptx_media: expected object, "
                f"got {type(media).__name__}"
            )
            continue
        part = media.get("part")
        if not (isinstance(part, str) and part.startswith("ppt/media/")):
            errors.append(
                f"rows[{i}] id={rid!r} pptx_media.part={part!r} is "
                f"not under 'ppt/media/'"
            )
        asset_sha = (row.get("asset") or {}).get("sha256") if isinstance(
            row.get("asset"), dict,
        ) else None
        media_sha = media.get("sha256")
        if asset_sha != media_sha:
            errors.append(
                f"rows[{i}] id={rid!r} sha256 drift between asset and"
                f" pptx_media: asset={asset_sha!r} pptx_media="
                f"{media_sha!r}"
            )
        ct = media.get("content_type")
        if ct not in _ALLOWED_MEDIA_TYPES:
            errors.append(
                f"rows[{i}] id={rid!r} pptx_media.content_type="
                f"{ct!r} is not one of {sorted(_ALLOWED_MEDIA_TYPES)!r}"
            )
    return errors


def _check_inventory_external_zero(record: dict) -> list[str]:
    inv = record.get("inventory")
    if not isinstance(inv, dict):
        return []
    n = inv.get("relationships_external_count")
    if isinstance(n, int) and n == 0:
        return []
    return [
        f"inventory.relationships_external_count={n!r} (expected 0)"
    ]


def _check_sidecar_schema_version(record: dict) -> list[str]:
    sc = record.get("sidecar")
    if not isinstance(sc, dict):
        return []
    v = sc.get("schema_version")
    if v != EXPECTED_SIDECAR_SCHEMA_VERSION:
        return [
            f"sidecar.schema_version={v!r} (expected "
            f"{EXPECTED_SIDECAR_SCHEMA_VERSION})"
        ]
    return []


def _check_internal_consistency(record: dict) -> list[str]:
    """G17 — cross-field invariants that hold regardless of
    ``summary.ok``. Catches the false-green class where a tampered
    record carries internally contradictory sibling fields the
    per-field schema cannot express on its own."""
    errors: list[str] = []
    rows = record.get("rows")
    rows_len = len(rows) if isinstance(rows, list) else None

    summary = record.get("summary")
    if isinstance(summary, dict):
        rc = summary.get("row_count")
        if rows_len is not None and rc != rows_len:
            errors.append(
                f"summary.row_count={rc!r} disagrees with len(rows)="
                f"{rows_len} (always-true invariant; the runtime "
                f"smoke writes row_count = len(rows))"
            )
        ok = summary.get("ok")
        failures = summary.get("failures")
        if isinstance(ok, bool) and isinstance(failures, list):
            empty = (failures == [])
            if ok and not empty:
                errors.append(
                    f"summary.ok=true is contradictory with non-"
                    f"empty summary.failures={failures!r}"
                )
            if (not ok) and empty:
                errors.append(
                    "summary.ok=false is contradictory with empty "
                    "summary.failures; a failed record MUST list "
                    "at least one failure"
                )

    sidecar = record.get("sidecar")
    if isinstance(sidecar, dict):
        sc_rc = sidecar.get("request_count")
        if (rows_len is not None
                and isinstance(sc_rc, int)
                and not isinstance(sc_rc, bool)
                and sc_rc != rows_len):
            errors.append(
                f"sidecar.request_count={sc_rc!r} disagrees with "
                f"len(rows)={rows_len}; the rows mirror the "
                f"sidecar's requests 1:1"
            )

    inv = record.get("inventory")
    inv_slide_count: int | None = None
    if isinstance(inv, dict):
        inv_ok = inv.get("ok")
        inv_findings_empty = inv.get("findings_empty")
        if (inv_ok is True
                and inv_findings_empty is not True):
            errors.append(
                f"inventory.ok=true is contradictory with "
                f"inventory.findings_empty={inv_findings_empty!r}; "
                f"an inventory walker that reported findings cannot "
                f"also be ok"
            )
        sc = inv.get("slide_count")
        if isinstance(sc, int) and not isinstance(sc, bool):
            inv_slide_count = sc

    for i, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        asset = row.get("asset")
        if isinstance(asset, dict):
            if asset.get("exists") is not True:
                errors.append(
                    f"rows[{i}] id={rid!r} asset.exists="
                    f"{asset.get('exists')!r} is contradictory with "
                    f"the schema's required byte_count >= 1 + "
                    f"sha256 + extension fields; a row recording "
                    f"exists=false alongside positive bytes is "
                    f"internally inconsistent"
                )
            err = asset.get("error")
            if isinstance(err, str) and err:
                errors.append(
                    f"rows[{i}] id={rid!r} asset.error={err!r} is "
                    f"contradictory with a positive byte_count + "
                    f"valid sha256 in the same block; a row "
                    f"recording an error MUST also record an empty "
                    f"asset (exists=false) — and the schema then "
                    f"refuses the byte_count/sha256 fields"
                )
        media = row.get("pptx_media")
        if isinstance(media, dict) and inv_slide_count is not None:
            refs = media.get("referencing_slides")
            if isinstance(refs, list):
                for j, ref in enumerate(refs):
                    if not (isinstance(ref, int)
                            and not isinstance(ref, bool)):
                        continue
                    if ref < 1 or ref > inv_slide_count:
                        errors.append(
                            f"rows[{i}] id={rid!r} pptx_media."
                            f"referencing_slides[{j}]={ref!r} is "
                            f"out of inventory.slide_count="
                            f"{inv_slide_count} range [1, "
                            f"{inv_slide_count}]"
                        )
    return errors


def _check_summary_ok_consistency(record: dict) -> list[str]:
    summary = record.get("summary")
    if not isinstance(summary, dict):
        return ["summary: not an object"]
    ok = summary.get("ok")
    if ok is not True:
        return []
    sub: list[str] = []
    rows = record.get("rows")
    if not isinstance(rows, list) or len(rows) < 1:
        sub.append("rows must be a non-empty list")
    else:
        rc = summary.get("row_count")
        if rc != len(rows):
            sub.append(
                f"summary.row_count={rc!r} disagrees with len(rows)="
                f"{len(rows)}"
            )
        failures = summary.get("failures")
        if failures != []:
            sub.append(
                f"summary.failures must be empty when ok=true (got "
                f"{failures!r})"
            )
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            asset = row.get("asset") or {}
            err = asset.get("error")
            if err != "":
                sub.append(
                    f"rows[{i}].asset.error must be empty when "
                    f"summary.ok=true (got {err!r})"
                )
            if asset.get("exists") is not True:
                sub.append(
                    f"rows[{i}].asset.exists must be true when "
                    f"summary.ok=true"
                )
        if _row_placement_roles(record) != EXPECTED_PLACEMENT_ROLES:
            sub.append(
                "rows[*].placement_role coverage missing one of "
                "{'hero_page', 'local_region'}"
            )
        if len(_row_text_policies(record)) < MIN_TEXT_POLICIES:
            sub.append(
                f"rows[*].text_policy diversity below "
                f"{MIN_TEXT_POLICIES}"
            )
    if sub:
        return [
            "summary.ok=true is inconsistent with the gates that did "
            "NOT hold: " + "; ".join(sub)
        ]
    return []


def _all_gates(record: dict) -> list[str]:
    return (
        _check_schema_version(record)
        + _check_evidence_id(record)
        + _check_real_d_one_status_phrasing(record)
        + _check_per_row_well_formed(record)
        + _check_request_id_unique(record)
        + _check_placement_role_coverage(record)
        + _check_text_policy_diversity(record)
        + _check_spec_sidecar_row_parity(record)
        + _check_asset_shape(record)
        + _check_pptx_media_match(record)
        + _check_path_safety(record)
        + _check_string_safety(record)
        + _check_real_d_one_refusal(record)
        + _check_inventory_external_zero(record)
        + _check_sidecar_schema_version(record)
        + _check_internal_consistency(record)
        + _check_summary_ok_consistency(record)
    )


# ---------------------------------------------------------------------------
# Top-level validation.
# ---------------------------------------------------------------------------


def _load_record(path: Path) -> tuple[dict | None, str]:
    if path.is_symlink():
        return None, f"refused symlink at {path}"
    if not path.is_file():
        return None, f"missing or non-regular file at {path}"
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"cannot parse {path}: {type(exc).__name__}: {exc}"
    if not isinstance(doc, dict):
        return None, (
            f"top-level value at {path} is not a JSON object "
            f"(got {type(doc).__name__})"
        )
    return doc, ""


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _validate_record(record: dict) -> list[str]:
    schema = _load_schema()
    errors: list[str] = []
    _validate(record, schema, "<root>", errors)
    if errors:
        return errors
    return _all_gates(record)


# ---------------------------------------------------------------------------
# Self-test probes. Each probe mutates a clone of the committed
# template and asserts the documented gate flags the regression.
# ---------------------------------------------------------------------------


def _clone(record: dict) -> dict:
    return json.loads(json.dumps(record))


def _self_test_baseline() -> tuple[int, dict]:
    print("--- baseline: committed template should PASS ---")
    record, msg = _load_record(COMMITTED_TEMPLATE)
    if record is None:
        print(f"  [FAIL] could not load committed template: {msg}")
        return 1, {}
    errors = _validate_record(record)
    if errors:
        print(
            f"  [FAIL] committed template failed validation "
            f"({len(errors)} error(s)):"
        )
        for e in errors:
            print(f"    - {e}")
        return 1, record
    print("  [PASS] committed template validates against schema + all gates")
    return 0, record


def _probe(
    name: str, mutator, *, expect_substring: str,
) -> tuple[bool, str]:
    record, _ = _load_record(COMMITTED_TEMPLATE)
    if record is None:
        return False, "could not load template for probe"
    clone = _clone(record)
    mutator(clone)
    errors = _validate_record(clone)
    if not errors:
        return False, f"{name}: no errors raised on tampered clone"
    if not any(expect_substring in e for e in errors):
        return False, (
            f"{name}: expected an error containing "
            f"{expect_substring!r}; got {errors!r}"
        )
    return True, ""


def _drop_first_row(record):
    rows = record.get("rows") or []
    if rows:
        del rows[0]


def _duplicate_first_row_id(record):
    rows = record.get("rows") or []
    if len(rows) >= 2:
        rows[1]["id"] = rows[0]["id"]


def _collapse_placement_role(record):
    for row in record.get("rows") or []:
        row["placement_role"] = "hero_page"
        if isinstance(row.get("spec"), dict):
            row["spec"]["placement_role"] = "hero_page"
        if isinstance(row.get("sidecar"), dict):
            row["sidecar"]["placement_role"] = "hero_page"


def _collapse_text_policy(record):
    for row in record.get("rows") or []:
        row["text_policy"] = "no_text"
        if isinstance(row.get("spec"), dict):
            row["spec"]["text_policy"] = "no_text"
        if isinstance(row.get("sidecar"), dict):
            row["sidecar"]["text_policy"] = "no_text"


def _row_drift_text_policy(record):
    rows = record.get("rows") or []
    if rows:
        # Row-level value flipped away from spec / sidecar (which
        # stay caption_safe / no_text). row.text_policy stays a
        # valid value so the diversity gate doesn't fire — only the
        # parity gate.
        rows[0]["text_policy"] = "caption_safe"


def _bad_sha256(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["asset"]["sha256"] = "AAAA"


def _bad_byte_count(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["asset"]["byte_count"] = 0


def _ext_media_mismatch(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["asset"]["extension"] = "jpg"
        rows[0]["asset"]["media_type"] = "image/png"


def _absolute_manifest_local_path(record):
    rows = record.get("rows") or []
    if rows:
        # Edit the parity siblings too so spec/sidecar drift is not
        # the gate that fires first.
        rows[0]["manifest_local_path"] = "/etc/passwd"
        if isinstance(rows[0].get("sidecar"), dict):
            rows[0]["sidecar"]["manifest_local_path"] = "/etc/passwd"


def _uri_manifest_local_path(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["manifest_local_path"] = "http://attacker/x.png"
        if isinstance(rows[0].get("sidecar"), dict):
            rows[0]["sidecar"]["manifest_local_path"] = (
                "http://attacker/x.png"
            )


def _traversal_asset_path(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["asset"]["path"] = "synthetic-tempdir/../escape.png"


def _absolute_output_asset_path(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["asset"]["path"] = "/etc/passwd"


def _pptx_media_part_outside(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["pptx_media"]["part"] = "media/image1.png"


def _asset_pptx_media_sha_mismatch(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["pptx_media"]["sha256"] = (
            "c" * 64
        )


def _external_relationships_nonzero(record):
    inv = record.get("inventory")
    if isinstance(inv, dict):
        inv["relationships_external_count"] = 1


def _sidecar_schema_version_drift(record):
    sc = record.get("sidecar")
    if isinstance(sc, dict):
        sc["schema_version"] = 3


def _inject_public_hosting_wording(record):
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("spec"), dict):
        rows[0]["spec"]["intended_use"] = (
            "hero-page accent; public hosting enabled"
        )


def _inject_credential_token_placeholder(record):
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("spec"), dict):
        rows[0]["spec"]["intended_use"] = (
            "hero-page accent; token placeholder embedded; "
            "token=value; secret=value; password=value; "
            "api_key = value; bearer token wording"
        )


def _inject_confidential_marker(record):
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("spec"), dict):
        rows[0]["spec"]["intended_use"] = (
            "hero-page accent; confidential customer_id"
        )


def _inject_real_d_one_claim(record):
    record["notes"]["scope"] = (
        "Real D-One verified online: production run succeeded."
    )


def _summary_ok_with_failures(record):
    summary = record.get("summary") or {}
    summary["failures"] = ["fake failure carried while ok=true"]


def _summary_ok_false_with_empty_failures(record):
    summary = record.get("summary") or {}
    summary["ok"] = False
    summary["failures"] = []


def _summary_row_count_drift(record):
    summary = record.get("summary") or {}
    # Set ok=false so G4 short-circuits; G17 must still fire on the
    # row_count drift even without the summary.ok=true gate.
    summary["ok"] = False
    summary["failures"] = ["forced failure to disable G4"]
    summary["row_count"] = 99


def _sidecar_request_count_drift(record):
    sc = record.get("sidecar") or {}
    sc["request_count"] = 99


def _inventory_ok_with_nonempty_findings(record):
    inv = record.get("inventory") or {}
    inv["ok"] = True
    inv["findings_empty"] = False


def _asset_exists_false_with_positive_bytes(record):
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("asset"), dict):
        # Keep byte_count + sha256 + extension + media_type valid
        # (the schema requires them); flip only exists=false. The
        # combination is internally contradictory.
        rows[0]["asset"]["exists"] = False


def _asset_error_nonempty_alongside_bytes(record):
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("asset"), dict):
        rows[0]["asset"]["error"] = "sha256 read failed"


def _pptx_media_ref_slide_out_of_range(record):
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("pptx_media"), dict):
        # inventory.slide_count is 2 on the template; 99 is far past.
        rows[0]["pptx_media"]["referencing_slides"] = [99]


def _missing_unverified(record):
    record["real_d_one_status"] = (
        "Real D-One was NOT called by this provenance handoff."
    )


def _missing_negation_in_status(record):
    # UNVERIFIED substring present; noun present ('real D-One'); but
    # neither a negation token from _NEGATION_TOKENS nor an n't form
    # appears, so G3's negation half must fire.
    record["real_d_one_status"] = (
        "UNVERIFIED real D-One status; clarifying language has been "
        "redacted from this placeholder."
    )


def _schema_version_wrong(record):
    record["schema_version"] = "2"


def _evidence_id_wrong(record):
    record["evidence_id"] = "some_other_evidence"


def _additional_property(record):
    record["smuggled_field"] = "value"


def _run_probes() -> int:
    print("--- self-test fail-closed probes ---")
    probes: list[tuple[str, callable, str]] = [
        ("P1 missing required field (wrong schema_version)",
         _schema_version_wrong, "schema_version"),
        ("P2 wrong evidence_id", _evidence_id_wrong, "evidence_id"),
        ("P3 additionalProperties refused",
         _additional_property,
         "additional property 'smuggled_field' not allowed"),
        ("P4 missing UNVERIFIED substring", _missing_unverified,
         "UNVERIFIED"),
        ("P5 missing negation in status",
         _missing_negation_in_status,
         "no-call wording"),
        ("P6 dropped row collapses placement_role coverage",
         _drop_first_row,
         "placement_role coverage"),
        ("P7 duplicate row id refused",
         _duplicate_first_row_id, "duplicate id"),
        ("P8 collapsed placement_role refused",
         _collapse_placement_role, "placement_role coverage"),
        ("P9 collapsed text_policy refused",
         _collapse_text_policy, "text_policy diversity"),
        ("P10 spec/sidecar/row text_policy drift refused",
         _row_drift_text_policy, "text_policy parity drift"),
        ("P11 bad sha256 refused (asset.sha256)",
         _bad_sha256, "asset.sha256"),
        ("P12 byte_count=0 refused (asset.byte_count)",
         _bad_byte_count, "byte_count"),
        ("P13 extension/media_type mismatch refused",
         _ext_media_mismatch, "does not match extension"),
        # P14 / P15 / P17 are caught by the schema's path-pattern
        # lock at G2 (defense in depth — the runtime G12 semantic
        # gate also refuses them, but G2 runs first and short-
        # circuits the gate stack). The expected substring matches
        # the schema-layer diagnostic.
        ("P14 absolute-output escape on manifest_local_path",
         _absolute_manifest_local_path,
         "does not match pattern"),
        ("P15 URI-shaped manifest_local_path refused",
         _uri_manifest_local_path,
         "does not match pattern"),
        ("P16 traversal '..' in asset.path refused",
         _traversal_asset_path, "traversal"),
        ("P17 absolute-output escape on asset.path",
         _absolute_output_asset_path,
         "does not match pattern"),
        ("P18 pptx_media.part outside ppt/media/ refused",
         _pptx_media_part_outside, "ppt/media/"),
        ("P19 asset.sha256 mismatch vs pptx_media.sha256",
         _asset_pptx_media_sha_mismatch, "sha256 drift"),
        ("P20 inventory.relationships_external_count > 0 refused",
         _external_relationships_nonzero,
         "relationships_external_count"),
        ("P21 sidecar.schema_version drift refused",
         _sidecar_schema_version_drift, "sidecar.schema_version"),
        ("P22 public-hosting wording refused "
         "('public hosting enabled')",
         _inject_public_hosting_wording, "public-distribution"),
        ("P23 credential literal / assignment / bearer wording refused "
         "('token placeholder', token=value, secret=value, "
         "password=value, api_key = value, bearer token wording)",
         _inject_credential_token_placeholder, "credential literal"),
        ("P24 confidential / customer marker refused",
         _inject_confidential_marker, "confidential / customer"),
        ("P25 real-D-One success claim refused",
         _inject_real_d_one_claim,
         "real-D-One / MCP / network / model / image-search / Qoder"),
        ("P26 summary.ok=true with non-empty failures refused",
         _summary_ok_with_failures,
         "contradictory"),
        ("P27 summary.ok=false with empty failures refused (G17)",
         _summary_ok_false_with_empty_failures,
         "summary.ok=false is contradictory with empty"),
        ("P28 summary.row_count drift when ok=false refused (G17)",
         _summary_row_count_drift,
         "summary.row_count"),
        ("P29 sidecar.request_count drift refused (G17)",
         _sidecar_request_count_drift,
         "sidecar.request_count"),
        ("P30 inventory.ok=true with findings_empty=false refused (G17)",
         _inventory_ok_with_nonempty_findings,
         "inventory.ok=true is contradictory"),
        ("P31 asset.exists=false alongside positive bytes refused "
         "(G17)",
         _asset_exists_false_with_positive_bytes,
         "asset.exists"),
        ("P32 asset.error non-empty alongside bytes refused (G17)",
         _asset_error_nonempty_alongside_bytes,
         "asset.error"),
        ("P33 pptx_media.referencing_slides out of inventory.slide_"
         "count range refused (G17)",
         _pptx_media_ref_slide_out_of_range,
         "out of inventory.slide_count"),
    ]
    fails = 0
    for name, mutator, expect in probes:
        ok, msg = _probe(name, mutator, expect_substring=expect)
        mark = "PASS" if ok else "FAIL"
        suffix = f" -- {msg}" if not ok else ""
        print(f"  [{mark}] {name}{suffix}")
        if not ok:
            fails += 1
    return fails


def _run_self_test() -> int:
    print("=== validate_generated_image_provenance (--self-test) ===")
    rc, _ = _self_test_baseline()
    if rc != 0:
        return rc
    fails = _run_probes()
    if fails:
        print(f"FAIL: {fails} probe(s) did not raise the documented gate")
        return 1
    print(
        "OK: committed-safe template passes every gate AND every "
        "negative probe raises the documented gate"
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only validator for committed-safe generated-image "
            "provenance handoff records (schemas/generated_image_"
            "provenance.schema.json). NETWORK-FREE; stdlib-only; "
            "never mutates any file; never calls real D-One / MCP / "
            "Qoder / a public network / any model API / image "
            "search / telemetry."
        ),
    )
    parser.add_argument(
        "--evidence", type=Path,
        help=(
            "Path to a generated-image provenance record to "
            "validate (committed-safe shape)."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run the in-script baseline (committed template) + "
            "every documented fail-closed probe."
        ),
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return _run_self_test()
    if args.evidence is None:
        print(
            "FAIL: --evidence is required when --self-test is not "
            "passed",
            file=sys.stderr,
        )
        return 2
    record, msg = _load_record(args.evidence)
    if record is None:
        print(f"FAIL: {msg}", file=sys.stderr)
        return 2
    errors = _validate_record(record)
    if errors:
        print(f"FAIL: {args.evidence}")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(
        f"OK: {args.evidence} validates against "
        f"{SCHEMA_PATH.name} + every semantic gate"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
