#!/usr/bin/env python3
"""Local validator for the mixed image-asset provenance handoff record.

Read-only, stdlib-only validator for the committed-safe JSON record
contract documented at
``schemas/mixed_image_asset_provenance.schema.json``. A reviewer copies
the canonical template at
``examples/mixed_image_asset_provenance_template.json`` as a starting
point and fills in the per-run values that survived the in-tempdir
mixed-lane mock pipeline (``scripts/run_mock_image_pipeline.py --bundle``
driven by ``scripts/mixed_image_asset_pipeline_smoke.py`` /
``scripts/mixed_image_asset_provenance_handoff_smoke.py``); this validator
re-checks the committed-safe shape against the schema PLUS the documented
semantic gates.

This script is the **committed-safe** half of the mixed image-asset
provenance contract. The **runtime** half is
``scripts/mixed_image_asset_provenance_handoff_smoke.py --self-test``:
it writes a TEMP-ONLY provenance object under a per-run tempdir that
the tempdir cleanup removes on exit, never commits, and records absolute
on-disk paths the validator's path-safety gate would intentionally
refuse. The deliberate narrowed mapping between the two shapes — the
runtime smoke's absolute tempdir paths vs the committed-safe / package-
safe placeholder paths the schema and this validator gate — is
documented in ``references/quality-gates.md``.

The validator is **read-only**: it never writes, mutates, or removes
any file, and never calls D-One / MCP / a public network / any model
API / image search / Qoder / telemetry. A schema-PASS plus every-gate-
PASS result certifies the record is internally consistent and self-
honest about the MIXED MOCK / STUB nature of the chain that produced
it (d_one_local stub bytes from the mock D-One adapter chain plus
local_asset caller-staged bytes). It does NOT certify a real D-One
run happened — by contract, no such run is performed by this skill
today.

Gates applied (every failed gate is reported; the script exits
non-zero on any failure):

  G1  ``readable_json_object``
    - the input file must exist as a regular non-symlink file;
    - the bytes must parse as JSON;
    - the parsed JSON must be a top-level object.

  G2  ``schema_subset_valid``
    - the record validates against
      ``schemas/mixed_image_asset_provenance.schema.json`` under the
      same draft-07 subset ``scripts/validate_artifacts.py``
      implements (``additionalProperties:false`` at every declared
      object level; ``schema_version`` enum-locked to ``"2"``
      (bumped from ``"1"`` as the paired schema / validator change
      that added the required ``sidecar.requests`` per-id taxonomy
      projection + the optional row-level ``generated_intent``
      block — earlier ``"1"`` records do not carry those fields
      and are intentionally refused at the schema layer);
      ``evidence_id`` enum-locked to
      ``"mixed_image_asset_provenance"``).

  G3  ``real_d_one_status_phrasing``
    - ``real_d_one_status`` MUST contain the literal ``UNVERIFIED``
      substring (case-insensitive) AND at least one negation token
      paired with a forbidden service noun, so a tampered status
      string cannot smuggle a positive claim past the schema's
      length-only bounds.

  G4  ``summary_ok_consistency``
    - ``summary.ok == true`` requires every documented sub-condition:
        * ``len(rows) == summary.row_count`` AND ``len(rows) >= 2``;
        * ``summary.failures == []``;
        * sorted ``source_class`` values across rows equal exactly
          ``["d_one_local", "local_asset"]`` AND
          ``summary.source_class_coverage`` agrees;
        * ``summary.d_one_local_id_count`` equals the actual number
          of d_one_local rows;
        * ``summary.local_asset_id_count`` equals the actual number
          of local_asset rows;
        * every row's ``asset.error`` is the empty string;
        * every row's ``asset.exists`` is True.

  G5  ``per_row_well_formed``
    - every row carries every required string field as a non-empty
      string.

  G6  ``request_id_unique``
    - no duplicate ``rows[*].id`` values; identifier collisions
      across rows are refused.

  G7  ``source_class_coverage``
    - exactly two source classes are represented across rows:
      ``{"d_one_local", "local_asset"}``; both members must appear
      and no others are allowed (the enum at the schema layer
      already restricts to that set, but the gate runs again at
      runtime to surface a clear coverage diagnostic when one of
      the two collapses to zero rows).
      ``summary.source_class_coverage`` cross-checked for agreement.

  G8  ``sidecar_membership_rules``
    - every row whose ``source_class == "d_one_local"`` MUST have
      its ``id`` present in ``sidecar.request_ids`` (the runner-
      written ``mock_d_one_adapter_plan.json`` sidecar is the audit
      surface for what the mock D-One adapter generated; a d_one_local
      id missing from the sidecar would mean the runner did not
      actually generate that asset);
    - every row whose ``source_class == "local_asset"`` MUST NOT
      appear in ``sidecar.request_ids`` (caller-staged bytes are
      not a generated artifact; a local_asset id leaking into the
      sidecar would falsely claim the caller-supplied PNG was
      produced by the mock adapter);
    - every entry in ``sidecar.request_ids`` MUST correspond to a
      d_one_local row in ``rows[]`` (no orphan ids and no
      cross-class drift).

  G9  ``asset_pptx_sha_match``
    - every row's ``pptx_media.sha256`` MUST equal
      ``asset.sha256`` byte-for-byte; ``pptx_media.part`` MUST
      start with ``ppt/media/`` AND carry no URI / traversal /
      leading-slash shape; ``pptx_media.content_type`` MUST be
      one of ``image/png`` / ``image/jpeg``; ``asset.extension``
      MUST be in ``{png, jpg, jpeg}`` and ``asset.media_type``
      MUST be the conservative projection of the extension.

  G10 ``inventory_media_membership``
    - PART-LEVEL bidirectional equality between the set of row
      ``pptx_media.{part, sha256}`` pairs and the set of
      ``inventory.media_parts[*].{part, sha256}`` pairs:
        (a) every row's ``(pptx_media.part, pptx_media.sha256)``
            pair MUST appear in ``inventory.media_parts`` (the
            row claims a PPTX (part, sha) pair that does not
            actually live inside the produced PPTX otherwise);
        (b) every entry in ``inventory.media_parts`` MUST be
            referenced by some row's
            ``(pptx_media.part, pptx_media.sha256)`` pair (an
            unreferenced media part inside the produced PPTX
            means the provenance record is incomplete OR the
            mixed-lane bundle leaked an extra asset the record
            does not account for — both fail closed).
      The pairing is part-level (not just sha-level) so a part
      rename without a corresponding row update, AND two parts
      that happen to share the same sha (a defensive case),
      are both caught. The inventory walk is the byte-level
      surface that proves what landed where; the validator
      requires the provenance record to cover it exactly.

  G11 ``lane_byte_distinct``
    - the union of d_one_local-row ``asset.sha256`` values and the
      union of local_asset-row ``asset.sha256`` values MUST be
      disjoint (the two lanes carry independent bytes end-to-end;
      a sha256 shared across both lanes would mean one lane's
      bytes collapsed onto the other or a row mis-classified its
      source_class).

  G12 ``path_safety_committed_safe``
    - every path-typed field (``bundle_path``, ``workspace_path``,
      ``report_dir``, ``pptx_path``, ``sidecar.path``,
      ``inventory.path``, ``rows[*].manifest_local_path``,
      ``rows[*].asset.path``, ``rows[*].pptx_media.part``) MUST be
      a committed-safe value: no URI scheme prefix; no ``..``
      traversal segment; no leading ``/`` (absolute-output escape).

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
      have their own pattern lock at the schema layer; including
      them would force a false positive).

  G14 ``real_d_one_claim_refusal``
    - the validator walks the full record and refuses any string
      scalar OR boolean True that asserts a real / live / MCP /
      public-network / model-API / image-search / Qoder success.
      A claim is positive iff a forbidden noun is in scope (in the
      value OR in the enclosing dict key) AND a forbidden success
      verb (``verified`` / ``passed`` / ``succeeded`` / ``called``
      / ``reached`` / ``fetched`` / ``received`` / ``online`` /
      ``live`` / ``enabled``) appears at a word boundary AND is NOT
      preceded by a negation token in a local 15-char window.

  G15 ``inventory_external_zero``
    - ``inventory.relationships_external_count`` MUST be 0; any
      external relationship in the produced PPTX is refused.

  G16 ``sidecar_schema_version_locked``
    - ``sidecar.schema_version`` MUST equal 4
      (``LOCKED_PLAN_SCHEMA_VERSION``).

  G17 ``internal_consistency``
    - cross-field invariants that hold ALWAYS (regardless of
      ``summary.ok``):
        * ``summary.row_count == len(rows)``;
        * ``summary.d_one_local_id_count`` equals the count of
          ``rows[*].source_class == "d_one_local"``;
        * ``summary.local_asset_id_count`` equals the count of
          ``rows[*].source_class == "local_asset"``;
        * ``(summary.ok == true) iff (summary.failures == [])``;
        * ``inventory.ok == true`` implies
          ``inventory.findings_empty == true``;
        * per row: ``asset.exists == true``;
        * per row: ``asset.error == ""``;
        * per row: every ``pptx_media.referencing_slides[i]`` value
          falls within ``[1, inventory.slide_count]``.

  G18 ``generated_intent_parity``
    - every d_one_local row MUST carry a ``generated_intent`` block
      whose ``placement_role`` / ``text_policy`` / ``subject_domain``
      values lie in the canonical closed allow-lists (the same
      ``image_taxonomy.<dim>.allowed_values`` sets the upstream
      ``schemas/d_one_descriptor_vocabulary.schema.json`` declares);
      the optional ``custom_descriptor`` value, when present, must
      additionally re-pass the same forbidden-token deny clause
      ``custom_descriptors[*].value`` uses (no ``public`` / ``upload``
      / ``raw`` / ``customer`` / ``confidential`` / ``screenshot`` /
      ``credential`` / ``password`` / ``secret`` token; no ``full
      slide`` / ``image search`` / ``web generation`` / ``page
      generation`` / ``slide generation`` compound; lowercase-
      identifier shape only);
    - every local_asset row MUST NOT carry ``generated_intent``
      (caller-staged bytes are not a generated artifact and have no
      D-One intent);
    - ``sidecar.requests[]`` MUST cover every d_one_local row id 1:1
      (no missing, no orphan, no local_asset id leak) AND each
      sidecar.requests[] entry's ``(placement_role, text_policy,
      subject_domain, custom_descriptor)`` MUST equal the matching
      d_one_local row's ``generated_intent`` byte-for-byte (so a
      reviewer cannot smuggle a row-only intent past the sidecar
      audit surface, AND a sidecar-only intent without a row counterpart
      cannot pretend the row carried the same projection);
    - ``sidecar.request_ids`` MUST equal the set of
      ``sidecar.requests[*].id`` (the two sidecar projections agree on
      which ids the runner generated).

Exit codes:
  0  every gate passed.
  1  one or more gates failed.
  2  invocation / file / parse error.

CLI:
  python3 scripts/validate_mixed_image_asset_provenance.py \\
      --evidence <path/to/mixed_image_asset_provenance.json>
  python3 scripts/validate_mixed_image_asset_provenance.py --self-test

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
    SCHEMAS_DIR / "mixed_image_asset_provenance.schema.json"
)
COMMITTED_TEMPLATE = (
    EXAMPLES_DIR / "mixed_image_asset_provenance_template.json"
)

EXPECTED_SCHEMA_VERSION = "2"
EXPECTED_EVIDENCE_ID = "mixed_image_asset_provenance"
EXPECTED_SIDECAR_SCHEMA_VERSION = 4
EXPECTED_SOURCE_CLASSES: frozenset[str] = frozenset({
    "d_one_local", "local_asset",
})
MIN_ROWS = 2
_ALLOWED_EXTS: frozenset[str] = frozenset({"png", "jpg", "jpeg"})
_ALLOWED_MEDIA_TYPES: frozenset[str] = frozenset({
    "image/png", "image/jpeg",
})
_EXT_TO_MEDIA_TYPE: dict[str, str] = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_ROW_STRING_FIELDS: tuple[str, ...] = (
    "id", "source_class", "manifest_local_path", "intended_use",
)

# Canonical generated_intent / sidecar.requests taxonomy allow-lists.
# These mirror schemas/d_one_descriptor_vocabulary.schema.json's
# image_taxonomy.<dim>.allowed_values blocks for the dimensions the
# committed-safe handoff carries (placement_role / text_policy /
# subject_domain). The schema layer already enum-locks every field; the
# gate re-asserts membership at runtime so a future schema relaxation
# cannot silently widen what counts as a valid intent value, AND so the
# missing / mismatched / unknown / collapsed diagnostics are crisp.
_PLACEMENT_ROLE_ALLOWED: frozenset[str] = frozenset({
    "hero_page", "local_region",
})
_TEXT_POLICY_ALLOWED: frozenset[str] = frozenset({
    "no_text", "decorative_glyphs", "caption_safe",
})
_SUBJECT_DOMAIN_ALLOWED: frozenset[str] = frozenset({
    "abstract_geometry", "process_motif",
    "metric_emblem", "concept_diagram",
})
_GENERATED_INTENT_REQUIRED_FIELDS: tuple[str, ...] = (
    "placement_role", "text_policy", "subject_domain",
)
_GENERATED_INTENT_OPTIONAL_FIELDS: tuple[str, ...] = (
    "custom_descriptor",
)
# custom_descriptor pattern — matches the schema's pattern + the
# upstream d_one_descriptor_vocabulary.schema.json custom_descriptors[*]
# .value rule. The gate re-applies it at runtime so a tampered record
# whose schema-layer pattern check was skipped (defense in depth) still
# fails closed.
_CUSTOM_DESCRIPTOR_RE = re.compile(
    r"^(?!.*(?:^|[._\-])"
    r"(?:public|upload|raw|customer|confidential|screenshot|"
    r"credential|password|secret)(?:[._\-]|$))"
    r"(?!.*(?:full[._\-]*slide|image[._\-]*search|"
    r"web[._\-]*generation|page[._\-]*generation|"
    r"slide[._\-]*generation))"
    r"[a-z][a-z0-9_.\-]*$"
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
        media_parts = inv.get("media_parts")
        if isinstance(media_parts, list):
            for j, entry in enumerate(media_parts):
                if not isinstance(entry, dict):
                    continue
                p = entry.get("part")
                if isinstance(p, str):
                    failures.extend(_path_safety_failures(
                        f"inventory.media_parts[{j}].part", p,
                    ))
    for idx, row in enumerate(record.get("rows") or []):
        if not isinstance(row, dict):
            continue
        v = row.get("manifest_local_path")
        if isinstance(v, str):
            failures.extend(_path_safety_failures(
                f"rows[{idx}].manifest_local_path", v,
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
# ``inventory.media_parts[i].sha256`` is also a 64-hex sha256 string
# (the schema pattern-locks every entry to ``^[0-9a-f]{64}$``), so it
# matches the ``.sha256`` suffix below.
_SHA256_EXCLUDED_PATHS_SUFFIX: tuple[str, ...] = (
    ".sha256",
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


def _row_source_classes(record: dict) -> set[str]:
    out: set[str] = set()
    for row in (record.get("rows") or []):
        if isinstance(row, dict):
            v = row.get("source_class")
            if isinstance(v, str):
                out.add(v)
    return out


def _rows_by_source_class(record: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"d_one_local": [], "local_asset": []}
    for row in (record.get("rows") or []):
        if not isinstance(row, dict):
            continue
        sc = row.get("source_class")
        if isinstance(sc, str) and sc in out:
            out[sc].append(row)
    return out


def _check_source_class_coverage(record: dict) -> list[str]:
    errors: list[str] = []
    seen = _row_source_classes(record)
    if seen != EXPECTED_SOURCE_CLASSES:
        errors.append(
            f"rows[*].source_class coverage: expected exactly "
            f"{sorted(EXPECTED_SOURCE_CLASSES)!r}, got "
            f"{sorted(seen)!r}"
        )
    summary = record.get("summary")
    if isinstance(summary, dict):
        cov = summary.get("source_class_coverage")
        if isinstance(cov, list):
            if sorted(set(cov)) != sorted(seen):
                errors.append(
                    f"summary.source_class_coverage ({cov!r}) "
                    f"disagrees with rows[*].source_class "
                    f"({sorted(seen)!r})"
                )
    return errors


def _check_sidecar_membership(record: dict) -> list[str]:
    """G8 — sidecar membership rules: d_one_local ids must appear in
    the sidecar, local_asset ids must NOT appear, and every sidecar id
    must correspond to a d_one_local row."""
    errors: list[str] = []
    sidecar = record.get("sidecar")
    if not isinstance(sidecar, dict):
        return errors
    request_ids = sidecar.get("request_ids")
    if not isinstance(request_ids, list):
        return errors
    sidecar_ids = set()
    for entry in request_ids:
        if isinstance(entry, str):
            sidecar_ids.add(entry)
    by_class = _rows_by_source_class(record)
    d_one_ids = {
        r["id"] for r in by_class["d_one_local"]
        if isinstance(r.get("id"), str)
    }
    local_ids = {
        r["id"] for r in by_class["local_asset"]
        if isinstance(r.get("id"), str)
    }
    # Every d_one_local id MUST appear in the sidecar.
    missing_d_one = sorted(d_one_ids - sidecar_ids)
    for mid in missing_d_one:
        errors.append(
            f"sidecar.request_ids: d_one_local row id {mid!r} is "
            f"NOT in the sidecar (the runner-written mock D-One "
            f"adapter plan must cover every generated request)"
        )
    # Every local_asset id MUST NOT appear in the sidecar.
    leaked_local = sorted(local_ids & sidecar_ids)
    for lid in leaked_local:
        errors.append(
            f"sidecar.request_ids: local_asset row id {lid!r} "
            f"leaked into the sidecar (caller-staged bytes are not "
            f"a generated artifact; a local_asset id in the sidecar "
            f"would falsely claim the local PNG was produced by the "
            f"mock adapter)"
        )
    # Every sidecar id MUST correspond to a d_one_local row.
    orphan = sorted(sidecar_ids - d_one_ids)
    for oid in orphan:
        errors.append(
            f"sidecar.request_ids: id {oid!r} does not match any "
            f"d_one_local row (no orphan ids allowed; the sidecar's "
            f"requests[] mirrors d_one_local rows 1:1)"
        )
    return errors


def _check_asset_pptx_sha_match(record: dict) -> list[str]:
    errors: list[str] = []
    for i, row in enumerate(record.get("rows") or []):
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        asset = row.get("asset")
        media = row.get("pptx_media")
        if isinstance(asset, dict):
            sha = asset.get("sha256")
            if not (isinstance(sha, str) and _SHA256_RE.match(sha)):
                errors.append(
                    f"rows[{i}] id={rid!r} asset.sha256={sha!r} is "
                    f"not a lowercase 64-char hex string"
                )
            bc = asset.get("byte_count")
            if not (isinstance(bc, int) and not isinstance(bc, bool)
                    and bc >= 1):
                errors.append(
                    f"rows[{i}] id={rid!r} asset.byte_count={bc!r} "
                    f"is not a positive integer"
                )
            ext = asset.get("extension")
            if not (isinstance(ext, str)
                    and ext.lower() in _ALLOWED_EXTS):
                errors.append(
                    f"rows[{i}] id={rid!r} asset.extension={ext!r} "
                    f"is not one of {sorted(_ALLOWED_EXTS)!r}"
                )
            else:
                expected_media = _EXT_TO_MEDIA_TYPE.get(ext.lower())
                actual_media = asset.get("media_type")
                if actual_media != expected_media:
                    errors.append(
                        f"rows[{i}] id={rid!r} asset.media_type="
                        f"{actual_media!r} does not match "
                        f"extension={ext!r} (expected "
                        f"{expected_media!r})"
                    )
        if not isinstance(media, dict):
            errors.append(
                f"rows[{i}] id={rid!r} pptx_media: expected object"
            )
            continue
        part = media.get("part")
        if not (isinstance(part, str) and part.startswith("ppt/media/")):
            errors.append(
                f"rows[{i}] id={rid!r} pptx_media.part={part!r} is "
                f"not under 'ppt/media/'"
            )
        asset_sha = (asset.get("sha256")
                     if isinstance(asset, dict) else None)
        media_sha = media.get("sha256")
        if asset_sha != media_sha:
            errors.append(
                f"rows[{i}] id={rid!r} sha256 drift between asset "
                f"and pptx_media: asset={asset_sha!r} "
                f"pptx_media={media_sha!r}"
            )
        ct = media.get("content_type")
        if ct not in _ALLOWED_MEDIA_TYPES:
            errors.append(
                f"rows[{i}] id={rid!r} pptx_media.content_type="
                f"{ct!r} is not one of "
                f"{sorted(_ALLOWED_MEDIA_TYPES)!r}"
            )
    return errors


def _check_inventory_media_membership(record: dict) -> list[str]:
    """G10 — PART-LEVEL bidirectional equality between row
    pptx_media (part, sha256) pairs and inventory.media_parts
    (part, sha256) entries. Both halves are load-bearing:

      * an unreferenced inventory entry means the provenance record
        left a PPTX media part unaccounted for;
      * a row pair missing from the inventory means the row claims
        a (part, sha) combination that is not in the produced PPTX.

    The pairing is part-level — not just sha-level — so a part
    rename without a corresponding row update, AND two parts that
    happen to share the same sha (a defensive case), are both
    caught."""
    errors: list[str] = []
    inv = record.get("inventory")
    if not isinstance(inv, dict):
        return errors
    media_parts = inv.get("media_parts")
    if not isinstance(media_parts, list):
        return errors
    inv_pairs: set[tuple[str, str]] = set()
    for entry in media_parts:
        if not isinstance(entry, dict):
            continue
        p = entry.get("part")
        s = entry.get("sha256")
        if isinstance(p, str) and isinstance(s, str):
            inv_pairs.add((p, s))
    row_pairs: set[tuple[str, str]] = set()
    for i, row in enumerate(record.get("rows") or []):
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        media = row.get("pptx_media")
        if not isinstance(media, dict):
            continue
        p = media.get("part")
        s = media.get("sha256")
        if not (isinstance(p, str) and isinstance(s, str)):
            continue
        row_pairs.add((p, s))
        if (p, s) not in inv_pairs:
            errors.append(
                f"rows[{i}] id={rid!r} pptx_media (part={p!r}, "
                f"sha256={s!r}) is NOT in inventory.media_parts "
                f"(the row claims a PPTX (part, sha) pair that "
                f"does not actually live inside the produced PPTX)"
            )
    orphan_pairs = sorted(inv_pairs - row_pairs)
    for p, s in orphan_pairs:
        errors.append(
            f"inventory.media_parts: (part={p!r}, sha256={s!r}) "
            f"appears in the PPTX media set but is NOT referenced "
            f"by any row's pptx_media.(part, sha256) pair (the "
            f"provenance record must cover every embedded media "
            f"part; an unreferenced media part means the record "
            f"is incomplete or the mixed-lane bundle leaked an "
            f"extra asset)"
        )
    return errors


def _check_lane_byte_distinct(record: dict) -> list[str]:
    """G11 — d_one_local-row asset sha set and local_asset-row asset
    sha set must be disjoint."""
    errors: list[str] = []
    by_class = _rows_by_source_class(record)
    d_one_shas: set[str] = set()
    local_shas: set[str] = set()
    for r in by_class["d_one_local"]:
        asset = r.get("asset") or {}
        sha = asset.get("sha256")
        if isinstance(sha, str):
            d_one_shas.add(sha)
    for r in by_class["local_asset"]:
        asset = r.get("asset") or {}
        sha = asset.get("sha256")
        if isinstance(sha, str):
            local_shas.add(sha)
    overlap = sorted(d_one_shas & local_shas)
    for sha in overlap:
        errors.append(
            f"lane byte-distinctness drift: sha256 {sha!r} appears "
            f"on BOTH a d_one_local row AND a local_asset row (the "
            f"two lanes must carry independent bytes end-to-end; a "
            f"sha shared across lanes means one lane's bytes "
            f"collapsed onto the other or a row mis-classified its "
            f"source_class)"
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
    ``summary.ok``."""
    errors: list[str] = []
    rows = record.get("rows")
    rows_len = len(rows) if isinstance(rows, list) else None
    by_class = _rows_by_source_class(record)
    d_one_count = len(by_class["d_one_local"])
    local_count = len(by_class["local_asset"])

    summary = record.get("summary")
    if isinstance(summary, dict):
        rc = summary.get("row_count")
        if rows_len is not None and rc != rows_len:
            errors.append(
                f"summary.row_count={rc!r} disagrees with len(rows)="
                f"{rows_len} (always-true invariant)"
            )
        dc = summary.get("d_one_local_id_count")
        if (isinstance(dc, int) and not isinstance(dc, bool)
                and dc != d_one_count):
            errors.append(
                f"summary.d_one_local_id_count={dc!r} disagrees "
                f"with the actual count of d_one_local rows "
                f"({d_one_count})"
            )
        lc = summary.get("local_asset_id_count")
        if (isinstance(lc, int) and not isinstance(lc, bool)
                and lc != local_count):
            errors.append(
                f"summary.local_asset_id_count={lc!r} disagrees "
                f"with the actual count of local_asset rows "
                f"({local_count})"
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

    inv = record.get("inventory")
    inv_slide_count: int | None = None
    if isinstance(inv, dict):
        inv_ok = inv.get("ok")
        inv_findings_empty = inv.get("findings_empty")
        if (inv_ok is True
                and inv_findings_empty is not True):
            errors.append(
                f"inventory.ok=true is contradictory with "
                f"inventory.findings_empty={inv_findings_empty!r}"
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
                    f"{asset.get('exists')!r} is contradictory "
                    f"with the schema's required byte_count >= 1 + "
                    f"sha256 + extension fields"
                )
            err = asset.get("error")
            if isinstance(err, str) and err:
                errors.append(
                    f"rows[{i}] id={rid!r} asset.error={err!r} is "
                    f"contradictory with a positive byte_count + "
                    f"valid sha256 in the same block"
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


def _check_generated_intent_parity(record: dict) -> list[str]:
    """G18 — generated_intent / sidecar.requests parity.

    The handoff record's d_one_local lane must carry a
    ``generated_intent`` block on every row AND that block must equal
    the matching ``sidecar.requests[]`` entry for the same id byte-
    for-byte across ``placement_role`` / ``text_policy`` /
    ``subject_domain`` / ``custom_descriptor``. The local_asset lane
    must NOT carry ``generated_intent`` (caller-staged bytes are not a
    generated artifact and have no D-One intent), and no local_asset
    id may appear in ``sidecar.requests[]``. Every taxonomy value is
    additionally re-asserted against the canonical closed allow-list
    so a future schema relaxation cannot silently widen the surface
    AND the ``custom_descriptor`` value re-passes the same forbidden-
    token deny clause schemas/d_one_descriptor_vocabulary.schema.json
    ``custom_descriptors[*].value`` enforces (defense in depth)."""
    errors: list[str] = []
    rows = record.get("rows") or []
    sidecar = record.get("sidecar")
    sidecar_requests = (
        sidecar.get("requests") if isinstance(sidecar, dict) else None
    )
    if not isinstance(sidecar_requests, list):
        sidecar_requests = []

    # Index the sidecar requests by id. A duplicate id at the schema
    # layer is already refused by the items.required.id contract, but
    # the gate handles the dict collapse defensively.
    sidecar_by_id: dict[str, dict] = {}
    duplicate_ids: list[str] = []
    for entry in sidecar_requests:
        if not isinstance(entry, dict):
            continue
        rid = entry.get("id")
        if not isinstance(rid, str) or not rid:
            continue
        if rid in sidecar_by_id:
            duplicate_ids.append(rid)
        else:
            sidecar_by_id[rid] = entry
    for rid in sorted(set(duplicate_ids)):
        errors.append(
            f"sidecar.requests: duplicate id {rid!r} (every sidecar "
            f"request id must be unique so the per-id taxonomy "
            f"cross-check is unambiguous)"
        )

    by_class = _rows_by_source_class(record)
    d_one_ids: set[str] = {
        r["id"] for r in by_class["d_one_local"]
        if isinstance(r.get("id"), str)
    }
    local_ids: set[str] = {
        r["id"] for r in by_class["local_asset"]
        if isinstance(r.get("id"), str)
    }

    # 1:1 coverage between sidecar.requests and d_one_local rows.
    missing_in_sidecar = sorted(d_one_ids - set(sidecar_by_id))
    for mid in missing_in_sidecar:
        errors.append(
            f"sidecar.requests: d_one_local row id {mid!r} has NO "
            f"matching sidecar.requests entry (every d_one_local row "
            f"must carry a per-id taxonomy projection; missing "
            f"generated_intent metadata)"
        )
    orphan_in_sidecar = sorted(set(sidecar_by_id) - d_one_ids)
    for oid in orphan_in_sidecar:
        errors.append(
            f"sidecar.requests: id {oid!r} does not match any "
            f"d_one_local row (no orphan sidecar entries; "
            f"sidecar.requests[] mirrors d_one_local rows 1:1)"
        )
    leaked_local = sorted(local_ids & set(sidecar_by_id))
    for lid in leaked_local:
        errors.append(
            f"sidecar.requests: local_asset row id {lid!r} leaked "
            f"into the per-id taxonomy projection (caller-staged "
            f"bytes are not a generated artifact and have no D-One "
            f"intent — local_asset ids must not appear in "
            f"sidecar.requests)"
        )

    # Per-row checks.
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        sc = row.get("source_class")
        gi = row.get("generated_intent")
        if sc == "local_asset":
            if gi is not None:
                errors.append(
                    f"rows[{i}] id={rid!r} source_class='local_asset' "
                    f"carries generated_intent (forbidden — caller-"
                    f"staged bytes are not a generated artifact and "
                    f"have no D-One intent)"
                )
            continue
        if sc != "d_one_local":
            # Unknown source_class — the source_class enum / coverage
            # gates handle that elsewhere; skip generated_intent check.
            continue
        # d_one_local row.
        if gi is None:
            errors.append(
                f"rows[{i}] id={rid!r} source_class='d_one_local' "
                f"is missing required generated_intent block (every "
                f"d_one_local row must carry the per-row taxonomy "
                f"projection)"
            )
            continue
        if not isinstance(gi, dict):
            errors.append(
                f"rows[{i}] id={rid!r} generated_intent must be a "
                f"JSON object (got {type(gi).__name__})"
            )
            continue
        # Required fields + canonical allow-list re-check.
        pr = gi.get("placement_role")
        if pr not in _PLACEMENT_ROLE_ALLOWED:
            errors.append(
                f"rows[{i}] id={rid!r} generated_intent.placement_role"
                f"={pr!r} is not in canonical allow-list "
                f"{sorted(_PLACEMENT_ROLE_ALLOWED)!r}"
            )
        tp = gi.get("text_policy")
        if tp not in _TEXT_POLICY_ALLOWED:
            errors.append(
                f"rows[{i}] id={rid!r} generated_intent.text_policy="
                f"{tp!r} is not in canonical allow-list "
                f"{sorted(_TEXT_POLICY_ALLOWED)!r}"
            )
        sd = gi.get("subject_domain")
        if sd not in _SUBJECT_DOMAIN_ALLOWED:
            errors.append(
                f"rows[{i}] id={rid!r} generated_intent.subject_domain"
                f"={sd!r} is not in canonical allow-list "
                f"{sorted(_SUBJECT_DOMAIN_ALLOWED)!r}"
            )
        cd = gi.get("custom_descriptor")
        if cd is not None:
            if not (isinstance(cd, str) and _CUSTOM_DESCRIPTOR_RE.match(cd)):
                errors.append(
                    f"rows[{i}] id={rid!r} generated_intent."
                    f"custom_descriptor={cd!r} does not match the "
                    f"approved custom-descriptor pattern (lowercase "
                    f"identifier; no public / upload / raw / customer "
                    f"/ confidential / screenshot / credential / "
                    f"password / secret tokens; no full-slide / "
                    f"image-search / web/page/slide-generation "
                    f"compounds)"
                )

        # Per-id parity with sidecar.requests.
        if not isinstance(rid, str) or not rid:
            continue
        sidecar_entry = sidecar_by_id.get(rid)
        if sidecar_entry is None:
            # Missing-in-sidecar diagnostic already emitted above; the
            # parity check has nothing to compare against.
            continue
        for field in _GENERATED_INTENT_REQUIRED_FIELDS:
            row_val = gi.get(field)
            sc_val = sidecar_entry.get(field)
            if row_val != sc_val:
                errors.append(
                    f"rows[{i}] id={rid!r} generated_intent.{field}="
                    f"{row_val!r} drifted from sidecar.requests entry "
                    f"value {sc_val!r} (per-id taxonomy must match "
                    f"byte-for-byte across the row + sidecar so a "
                    f"reviewer cannot smuggle a row-only intent past "
                    f"the audit surface)"
                )
        # custom_descriptor parity — both must be absent, OR both
        # present and equal. An asymmetric pair (row has it, sidecar
        # does not, or vice versa) is mismatched.
        row_cd = gi.get("custom_descriptor")
        sc_cd = sidecar_entry.get("custom_descriptor")
        if row_cd != sc_cd:
            errors.append(
                f"rows[{i}] id={rid!r} generated_intent."
                f"custom_descriptor={row_cd!r} drifted from "
                f"sidecar.requests entry value {sc_cd!r} (per-id "
                f"custom_descriptor must match byte-for-byte across "
                f"the row + sidecar)"
            )

    # Sidecar.requests entry — re-validate its taxonomy values against
    # the canonical allow-lists too (defense in depth alongside the
    # schema's enum locks).
    for j, entry in enumerate(sidecar_requests):
        if not isinstance(entry, dict):
            continue
        rid = entry.get("id")
        for field, allowed in (
            ("placement_role", _PLACEMENT_ROLE_ALLOWED),
            ("text_policy", _TEXT_POLICY_ALLOWED),
            ("subject_domain", _SUBJECT_DOMAIN_ALLOWED),
        ):
            val = entry.get(field)
            if val not in allowed:
                errors.append(
                    f"sidecar.requests[{j}] id={rid!r} {field}={val!r}"
                    f" is not in canonical allow-list "
                    f"{sorted(allowed)!r}"
                )
        cd = entry.get("custom_descriptor")
        if cd is not None:
            if not (isinstance(cd, str) and _CUSTOM_DESCRIPTOR_RE.match(cd)):
                errors.append(
                    f"sidecar.requests[{j}] id={rid!r} "
                    f"custom_descriptor={cd!r} does not match the "
                    f"approved custom-descriptor pattern"
                )

    # sidecar.request_ids must equal the set of sidecar.requests[].id
    # — a drift here would mean the request_ids audit surface and the
    # per-id taxonomy projection disagree about which ids the runner
    # generated.
    if isinstance(sidecar, dict):
        ids_list = sidecar.get("request_ids")
        if isinstance(ids_list, list):
            request_ids_set: set[str] = {
                s for s in ids_list if isinstance(s, str)
            }
            requests_id_set: set[str] = set(sidecar_by_id)
            in_ids_not_in_requests = sorted(
                request_ids_set - requests_id_set,
            )
            for mid in in_ids_not_in_requests:
                errors.append(
                    f"sidecar.request_ids: id {mid!r} is present but "
                    f"has no matching sidecar.requests entry (the two "
                    f"sidecar projections must agree on which ids the "
                    f"runner generated)"
                )
            in_requests_not_in_ids = sorted(
                requests_id_set - request_ids_set,
            )
            for mid in in_requests_not_in_ids:
                errors.append(
                    f"sidecar.requests: id {mid!r} has a per-id "
                    f"taxonomy entry but is missing from "
                    f"sidecar.request_ids (the two sidecar "
                    f"projections must agree on which ids the runner "
                    f"generated)"
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
    if not isinstance(rows, list) or len(rows) < MIN_ROWS:
        sub.append(
            f"rows must be a list of length >= {MIN_ROWS}"
        )
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
        if _row_source_classes(record) != EXPECTED_SOURCE_CLASSES:
            sub.append(
                "rows[*].source_class coverage missing one of "
                "{'d_one_local', 'local_asset'}"
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
        + _check_source_class_coverage(record)
        + _check_sidecar_membership(record)
        + _check_asset_pptx_sha_match(record)
        + _check_inventory_media_membership(record)
        + _check_lane_byte_distinct(record)
        + _check_path_safety(record)
        + _check_string_safety(record)
        + _check_real_d_one_claim_refusal_wrapper(record)
        + _check_inventory_external_zero(record)
        + _check_sidecar_schema_version(record)
        + _check_internal_consistency(record)
        + _check_generated_intent_parity(record)
        + _check_summary_ok_consistency(record)
    )


def _check_real_d_one_claim_refusal_wrapper(record) -> list[str]:
    return _check_real_d_one_refusal(record)


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
        return None, (
            f"cannot parse {path}: {type(exc).__name__}: {exc}"
        )
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
    print(
        "  [PASS] committed template validates against schema + "
        "every gate"
    )
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


def _drop_local_asset_row(record):
    rows = record.get("rows") or []
    record["rows"] = [
        r for r in rows
        if r.get("source_class") != "local_asset"
    ]


def _drop_d_one_local_row(record):
    rows = record.get("rows") or []
    record["rows"] = [
        r for r in rows
        if r.get("source_class") != "d_one_local"
    ]


def _local_asset_id_in_sidecar(record):
    rows = record.get("rows") or []
    local_ids = [
        r["id"] for r in rows
        if r.get("source_class") == "local_asset"
        and isinstance(r.get("id"), str)
    ]
    if local_ids:
        sc = record.get("sidecar") or {}
        existing = list(sc.get("request_ids") or [])
        sc["request_ids"] = sorted(set(existing + local_ids))


def _drop_d_one_id_from_sidecar(record):
    rows = record.get("rows") or []
    d_one_ids = {
        r["id"] for r in rows
        if r.get("source_class") == "d_one_local"
        and isinstance(r.get("id"), str)
    }
    sc = record.get("sidecar") or {}
    request_ids = list(sc.get("request_ids") or [])
    sc["request_ids"] = [
        i for i in request_ids if i not in d_one_ids
    ] or ["zzz_orphan_request_id"]


def _orphan_sidecar_id(record):
    sc = record.get("sidecar") or {}
    existing = list(sc.get("request_ids") or [])
    sc["request_ids"] = sorted(
        set(existing + ["unrelated_orphan_id"])
    )


def _sha_mismatch_pptx_vs_asset(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["pptx_media"]["sha256"] = "c" * 64


def _unreferenced_inventory_media(record):
    """Append an extra (part, sha) entry to inventory.media_parts
    that no row's pptx_media references — proves the bidirectional
    gate fires the orphan-direction diagnostic."""
    inv = record.get("inventory") or {}
    media_parts = list(inv.get("media_parts") or [])
    orphan_entry = {
        "part": "ppt/media/orphan99.png",
        "sha256": "d" * 64,
    }
    media_parts.append(orphan_entry)
    inv["media_parts"] = sorted(
        media_parts,
        key=lambda e: (e.get("part") or "", e.get("sha256") or ""),
    )


def _sha_missing_from_inventory(record):
    """Strip the first row's (part, sha) entry from inventory.media_
    parts and inject two unrelated entries so the schema's minItems
    still holds but the row's pair becomes missing from the inventory
    — proves the row-side bidirectional gate fires."""
    inv = record.get("inventory") or {}
    media_parts = list(inv.get("media_parts") or [])
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("pptx_media"), dict):
        target_part = rows[0]["pptx_media"].get("part")
        target_sha = rows[0]["pptx_media"].get("sha256")
        kept = [
            e for e in media_parts
            if not (
                isinstance(e, dict)
                and e.get("part") == target_part
                and e.get("sha256") == target_sha
            )
        ]
        # Pad with a synthetic entry so minItems:2 still holds; the
        # row's pair is what's intentionally missing.
        if len(kept) < 2:
            kept.append({
                "part": "ppt/media/synthetic_pad.png",
                "sha256": "f" * 64,
            })
        inv["media_parts"] = sorted(
            kept,
            key=lambda e: (e.get("part") or "", e.get("sha256") or ""),
        )


def _absolute_path_leak_bundle(record):
    record["bundle_path"] = "/etc/passwd"


def _absolute_path_leak_asset(record):
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("asset"), dict):
        rows[0]["asset"]["path"] = "/etc/passwd"


def _uri_manifest_local_path(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["manifest_local_path"] = "http://attacker/x.png"


def _public_hosting_in_intended_use(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["intended_use"] = (
            "spot illustration; public hosting enabled"
        )


def _credential_token_in_intended_use(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["intended_use"] = (
            "spot illustration; token=value; api_key = value"
        )


def _confidential_marker_in_intended_use(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["intended_use"] = (
            "spot illustration; confidential customer_id"
        )


def _real_d_one_claim_in_notes(record):
    notes = record.get("notes")
    if isinstance(notes, dict):
        notes["scope"] = (
            "Real D-One verified online: production run succeeded."
        )


def _lane_byte_collapse(record):
    """Force the d_one_local row's asset sha to match the local_asset
    row's asset sha — proves the lane-byte-distinct gate fires."""
    rows = record.get("rows") or []
    if len(rows) >= 2:
        # Find the local_asset row's sha and put it on the
        # d_one_local row.
        local_sha = None
        for r in rows:
            if r.get("source_class") == "local_asset":
                local_sha = r.get("asset", {}).get("sha256")
                break
        if isinstance(local_sha, str):
            for r in rows:
                if r.get("source_class") == "d_one_local":
                    r["asset"]["sha256"] = local_sha
                    r["pptx_media"]["sha256"] = local_sha
                    break


def _sidecar_schema_version_drift(record):
    sc = record.get("sidecar")
    if isinstance(sc, dict):
        sc["schema_version"] = 3


def _missing_unverified(record):
    record["real_d_one_status"] = (
        "Real D-One was NOT called by this provenance handoff."
    )


def _missing_negation_in_status(record):
    record["real_d_one_status"] = (
        "UNVERIFIED real D-One status; clarifying language has been "
        "redacted from this placeholder."
    )


def _schema_version_wrong(record):
    # "2" is the current locked version; pick a future unknown so
    # the schema enum + validator gate both refuse.
    record["schema_version"] = "3"


def _evidence_id_wrong(record):
    record["evidence_id"] = "some_other_evidence"


def _additional_property(record):
    record["smuggled_field"] = "value"


def _external_relationships_nonzero(record):
    inv = record.get("inventory")
    if isinstance(inv, dict):
        inv["relationships_external_count"] = 1


def _summary_ok_with_failures(record):
    summary = record.get("summary") or {}
    summary["failures"] = ["fake failure carried while ok=true"]


def _summary_ok_false_with_empty_failures(record):
    summary = record.get("summary") or {}
    summary["ok"] = False
    summary["failures"] = []


def _summary_row_count_drift(record):
    summary = record.get("summary") or {}
    summary["ok"] = False
    summary["failures"] = ["forced failure to disable G4"]
    summary["row_count"] = 99


def _inventory_ok_with_nonempty_findings(record):
    inv = record.get("inventory") or {}
    inv["ok"] = True
    inv["findings_empty"] = False


def _asset_exists_false_with_positive_bytes(record):
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("asset"), dict):
        rows[0]["asset"]["exists"] = False


def _asset_error_nonempty_alongside_bytes(record):
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("asset"), dict):
        rows[0]["asset"]["error"] = "sha256 read failed"


def _pptx_media_ref_slide_out_of_range(record):
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("pptx_media"), dict):
        rows[0]["pptx_media"]["referencing_slides"] = [99]


def _pptx_media_part_outside(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["pptx_media"]["part"] = "media/image1.png"


def _ext_media_mismatch(record):
    rows = record.get("rows") or []
    if rows:
        rows[0]["asset"]["extension"] = "jpg"
        rows[0]["asset"]["media_type"] = "image/png"


def _duplicate_row_id(record):
    rows = record.get("rows") or []
    if len(rows) >= 2:
        rows[1]["id"] = rows[0]["id"]


def _collapse_source_class_to_d_one_local(record):
    """Keep both rows but flip every source_class to d_one_local —
    the schema's minItems:2 is satisfied, the source_class coverage
    gate fires. The sidecar also gets the local-row-id added so the
    membership rules do not short-circuit the coverage diagnostic."""
    rows = record.get("rows") or []
    for r in rows:
        if isinstance(r, dict):
            r["source_class"] = "d_one_local"
    sc = record.get("sidecar") or {}
    request_ids = list(sc.get("request_ids") or [])
    for r in rows:
        if isinstance(r, dict) and isinstance(r.get("id"), str):
            request_ids.append(r["id"])
    sc["request_ids"] = sorted(set(request_ids))


def _collapse_source_class_to_local_asset(record):
    """Symmetric to the above — every row becomes local_asset. The
    sidecar is also emptied because none of the rows are d_one_local
    any more."""
    rows = record.get("rows") or []
    for r in rows:
        if isinstance(r, dict):
            r["source_class"] = "local_asset"
    sc = record.get("sidecar") or {}
    # Keep at least one entry so the schema's minItems:1 holds,
    # then expect the membership gate to refuse it as orphan.
    sc["request_ids"] = ["orphan_sidecar_id"]


def _drop_generated_intent_from_d_one_row(record):
    """Strip ``generated_intent`` from the d_one_local row. G18 fires
    because every d_one_local row must carry the per-row taxonomy
    projection."""
    rows = record.get("rows") or []
    for r in rows:
        if r.get("source_class") == "d_one_local" and "generated_intent" in r:
            del r["generated_intent"]


def _attach_generated_intent_to_local_asset_row(record):
    """Attach generated_intent to a local_asset row. G18 fires because
    caller-staged bytes are not a generated artifact and have no
    D-One intent."""
    rows = record.get("rows") or []
    for r in rows:
        if r.get("source_class") == "local_asset":
            r["generated_intent"] = {
                "placement_role": "local_region",
                "text_policy": "no_text",
                "subject_domain": "abstract_geometry",
            }
            break


def _mismatch_generated_intent_text_policy(record):
    """Flip the d_one_local row's text_policy so it diverges from the
    sidecar.requests entry for the same id. G18 fires on per-id
    parity mismatch."""
    rows = record.get("rows") or []
    for r in rows:
        if r.get("source_class") == "d_one_local":
            gi = r.get("generated_intent") or {}
            if gi.get("text_policy") == "decorative_glyphs":
                gi["text_policy"] = "caption_safe"
            else:
                gi["text_policy"] = "decorative_glyphs"
            r["generated_intent"] = gi
            break


def _mismatch_generated_intent_placement_role(record):
    """Flip the d_one_local row's placement_role so it diverges from
    the sidecar.requests entry. G18 fires on per-id parity mismatch."""
    rows = record.get("rows") or []
    for r in rows:
        if r.get("source_class") == "d_one_local":
            gi = r.get("generated_intent") or {}
            if gi.get("placement_role") == "hero_page":
                gi["placement_role"] = "local_region"
            else:
                gi["placement_role"] = "hero_page"
            r["generated_intent"] = gi
            break


def _mismatch_generated_intent_custom_descriptor(record):
    """Drop the row's custom_descriptor while sidecar.requests retains
    it. G18 fires on per-id parity mismatch (asymmetric custom_descriptor
    pair)."""
    rows = record.get("rows") or []
    for r in rows:
        if r.get("source_class") == "d_one_local":
            gi = r.get("generated_intent") or {}
            if "custom_descriptor" in gi:
                del gi["custom_descriptor"]
                r["generated_intent"] = gi
            break


def _drop_sidecar_requests_entry_for_d_one_row(record):
    """Drop the d_one_local id from sidecar.requests. G18 fires because
    every d_one_local row must have a matching sidecar.requests entry."""
    rows = record.get("rows") or []
    d_one_ids = {
        r["id"] for r in rows
        if r.get("source_class") == "d_one_local"
        and isinstance(r.get("id"), str)
    }
    sc = record.get("sidecar") or {}
    sc["requests"] = [
        e for e in (sc.get("requests") or [])
        if not (isinstance(e, dict) and e.get("id") in d_one_ids)
    ] or [
        {
            "id": "zzz_orphan_request_id",
            "placement_role": "local_region",
            "text_policy": "no_text",
            "subject_domain": "abstract_geometry",
        }
    ]


def _leak_local_asset_into_sidecar_requests(record):
    """Insert a sidecar.requests entry for a local_asset id. G18 fires
    because caller-staged bytes are not a generated artifact."""
    rows = record.get("rows") or []
    local_ids = [
        r["id"] for r in rows
        if r.get("source_class") == "local_asset"
        and isinstance(r.get("id"), str)
    ]
    if not local_ids:
        return
    sc = record.get("sidecar") or {}
    existing = list(sc.get("requests") or [])
    existing.append({
        "id": local_ids[0],
        "placement_role": "local_region",
        "text_policy": "no_text",
        "subject_domain": "abstract_geometry",
    })
    sc["requests"] = existing
    # Also leak into request_ids so the request_ids/requests gate
    # cannot mask the parity gate diagnostic.
    rid_list = list(sc.get("request_ids") or [])
    if local_ids[0] not in rid_list:
        sc["request_ids"] = sorted(set(rid_list + local_ids[:1]))


def _unknown_placement_role_in_generated_intent(record):
    """Set generated_intent.placement_role to an out-of-vocab token
    that bypasses the enum at the schema layer via direct mutation. G18
    re-asserts the canonical allow-list."""
    rows = record.get("rows") or []
    for r in rows:
        if r.get("source_class") == "d_one_local":
            gi = r.get("generated_intent") or {}
            gi["placement_role"] = "rogue_placement"
            r["generated_intent"] = gi
            break


def _credential_shape_custom_descriptor(record):
    """Force a credential-shape value into generated_intent.custom_
    descriptor. The custom_descriptor pattern + the G13 string-safety
    scan both fail closed."""
    rows = record.get("rows") or []
    for r in rows:
        if r.get("source_class") == "d_one_local":
            gi = r.get("generated_intent") or {}
            gi["custom_descriptor"] = "token=value"
            r["generated_intent"] = gi
            break


def _run_probes() -> int:
    print("--- self-test fail-closed probes ---")
    probes: list[tuple[str, callable, str]] = [
        ("P1 wrong schema_version", _schema_version_wrong,
         "schema_version"),
        ("P2 wrong evidence_id", _evidence_id_wrong, "evidence_id"),
        ("P3 additionalProperties refused",
         _additional_property,
         "additional property 'smuggled_field' not allowed"),
        ("P4 missing UNVERIFIED substring",
         _missing_unverified, "UNVERIFIED"),
        ("P5 missing negation in status",
         _missing_negation_in_status, "no-call wording"),
        ("P6 missing local_asset row collapses coverage "
         "(schema minItems gate fires first; semantic "
         "source_class coverage gate would fire if minItems "
         "relaxed)",
         _drop_local_asset_row, "minItems is 2"),
        ("P7 missing d_one_local row collapses coverage "
         "(schema minItems gate fires first; semantic "
         "source_class coverage gate would fire if minItems "
         "relaxed)",
         _drop_d_one_local_row, "minItems is 2"),
        ("P8 local_asset id leaks into sidecar.request_ids",
         _local_asset_id_in_sidecar, "leaked into the sidecar"),
        ("P9 d_one_local id missing from sidecar.request_ids",
         _drop_d_one_id_from_sidecar, "NOT in the sidecar"),
        ("P10 orphan sidecar request id refused",
         _orphan_sidecar_id,
         "does not match any d_one_local row"),
        ("P11 asset.sha256 vs pptx_media.sha256 mismatch",
         _sha_mismatch_pptx_vs_asset, "sha256 drift"),
        ("P12 row pptx_media (part, sha) pair missing from "
         "inventory.media_parts (part-level bidirectional, row "
         "direction)",
         _sha_missing_from_inventory,
         "is NOT in inventory.media_parts"),
        ("P12b unreferenced inventory.media_parts entry refused "
         "(part-level bidirectional, orphan direction)",
         _unreferenced_inventory_media,
         "NOT referenced by any row"),
        ("P13 absolute path leak on bundle_path",
         _absolute_path_leak_bundle, "does not match pattern"),
        ("P14 absolute path leak on asset.path",
         _absolute_path_leak_asset, "does not match pattern"),
        ("P15 URI-shaped manifest_local_path refused",
         _uri_manifest_local_path, "does not match pattern"),
        ("P16 public-hosting wording in intended_use refused",
         _public_hosting_in_intended_use,
         "public-distribution"),
        ("P17 credential token in intended_use refused",
         _credential_token_in_intended_use,
         "credential"),
        ("P18 confidential marker in intended_use refused",
         _confidential_marker_in_intended_use,
         "confidential / customer"),
        ("P19 real-D-One success claim in notes refused",
         _real_d_one_claim_in_notes,
         "real-D-One / MCP / network / model / image-search / Qoder"),
        ("P20 lane byte collapse refused",
         _lane_byte_collapse,
         "lane byte-distinctness"),
        ("P21 sidecar.schema_version drift refused",
         _sidecar_schema_version_drift,
         "sidecar.schema_version"),
        ("P22 inventory.relationships_external_count > 0 refused",
         _external_relationships_nonzero,
         "relationships_external_count"),
        ("P23 summary.ok=true with non-empty failures refused",
         _summary_ok_with_failures, "contradictory"),
        ("P24 summary.ok=false with empty failures refused",
         _summary_ok_false_with_empty_failures,
         "summary.ok=false is contradictory with empty"),
        ("P25 summary.row_count drift when ok=false refused",
         _summary_row_count_drift, "summary.row_count"),
        ("P26 inventory.ok=true with findings_empty=false refused",
         _inventory_ok_with_nonempty_findings,
         "inventory.ok=true is contradictory"),
        ("P27 asset.exists=false alongside positive bytes refused",
         _asset_exists_false_with_positive_bytes,
         "asset.exists"),
        ("P28 asset.error non-empty alongside bytes refused",
         _asset_error_nonempty_alongside_bytes,
         "asset.error"),
        ("P29 pptx_media.referencing_slides out of range refused",
         _pptx_media_ref_slide_out_of_range,
         "out of inventory.slide_count"),
        ("P30 pptx_media.part outside ppt/media/ refused",
         _pptx_media_part_outside, "does not match pattern"),
        ("P31 extension/media_type mismatch refused",
         _ext_media_mismatch, "does not match extension"),
        ("P32 duplicate row id refused",
         _duplicate_row_id, "duplicate id"),
        ("P33 both rows collapsed to d_one_local (semantic "
         "source_class coverage gate fires)",
         _collapse_source_class_to_d_one_local,
         "source_class coverage"),
        ("P34 both rows collapsed to local_asset (semantic "
         "source_class coverage gate fires)",
         _collapse_source_class_to_local_asset,
         "source_class coverage"),
        ("P35 d_one_local row missing generated_intent refused "
         "(G18 generated_intent parity)",
         _drop_generated_intent_from_d_one_row,
         "missing required generated_intent"),
        ("P36 local_asset row carrying generated_intent refused "
         "(G18 generated_intent parity)",
         _attach_generated_intent_to_local_asset_row,
         "carries generated_intent (forbidden"),
        ("P37 generated_intent.text_policy drift from "
         "sidecar.requests entry refused (G18 per-id parity)",
         _mismatch_generated_intent_text_policy,
         "generated_intent.text_policy"),
        ("P38 generated_intent.placement_role drift from "
         "sidecar.requests entry refused (G18 per-id parity)",
         _mismatch_generated_intent_placement_role,
         "generated_intent.placement_role"),
        ("P39 generated_intent.custom_descriptor asymmetric pair "
         "vs sidecar.requests refused (G18 per-id parity)",
         _mismatch_generated_intent_custom_descriptor,
         "custom_descriptor"),
        ("P40 d_one_local row id missing from sidecar.requests "
         "refused (G18 1:1 coverage)",
         _drop_sidecar_requests_entry_for_d_one_row,
         "has NO matching sidecar.requests entry"),
        ("P41 local_asset id leaks into sidecar.requests refused "
         "(G18 lane separation)",
         _leak_local_asset_into_sidecar_requests,
         "leaked into the per-id taxonomy projection"),
        ("P42 generated_intent.placement_role out-of-vocab token "
         "refused (schema enum + G18 canonical allow-list re-check)",
         _unknown_placement_role_in_generated_intent,
         "not in enum"),
        ("P43 generated_intent.custom_descriptor credential-shape "
         "refused (G18 pattern + G13 string-safety)",
         _credential_shape_custom_descriptor,
         "custom_descriptor"),
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
    print(
        "=== validate_mixed_image_asset_provenance (--self-test) ==="
    )
    rc, _ = _self_test_baseline()
    if rc != 0:
        return rc
    fails = _run_probes()
    if fails:
        print(
            f"FAIL: {fails} probe(s) did not raise the documented "
            f"gate"
        )
        return 1
    print(
        "OK: committed-safe template passes every gate AND every "
        "negative probe raises the documented gate"
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only validator for committed-safe mixed image-"
            "asset provenance handoff records "
            "(schemas/mixed_image_asset_provenance.schema.json). "
            "NETWORK-FREE; stdlib-only; never mutates any file; "
            "never calls real D-One / MCP / Qoder / a public "
            "network / any model API / image search / telemetry."
        ),
    )
    parser.add_argument(
        "--evidence", type=Path,
        help=(
            "Path to a mixed image-asset provenance record to "
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
