#!/usr/bin/env python3
"""Mock generated-image provenance smoke (LOCAL, STUB, NOT real D-One).

Tempdir-only, stdlib-only provenance smoke over the committed
``examples/synthetic_mock_image_trial/`` bundle. Drives the bundle
through ``scripts/run_mock_image_pipeline.py --bundle`` into a
tempfile-owned workspace / output / report directory OUTSIDE the repo
tree, then derives a **TEMP-ONLY** provenance/analysis object linking
each generated-image request id from the bundle's ``d_one_spec.json``
to:

  * caller-facing prompt/request metadata already allowed by the
    in-repo schemas — ``placement_role`` / ``text_policy`` /
    ``subject_domain`` / ``manifest_local_path``;
  * runner sidecar metadata observed on the
    ``<report-dir>/mock_d_one_adapter_plan.json`` file the runner
    writes byte-identical to the staging adapter plan;
  * the generated mock asset on disk under the tempdir-owned
    workspace (``<workspace>/<manifest_local_path>``), recording the
    asset's absolute path, ``byte_count``, ``sha256``, ``extension``,
    and conservative ``media_type``;
  * PPTX inventory evidence (``inspect_pptx_inventory`` /
    ``inventory.json`` already written by ``run_explicit_pipeline``)
    matching the workspace asset by ``sha256`` byte-for-byte and
    sitting under ``ppt/media/*`` with no external relationship in
    the produced ``.pptx``.

The derived object is emitted to stdout AND to a per-run tempfile.
NEITHER is ever committed; nothing is written under ``REPO_ROOT``;
``REPO_ROOT/dist`` is left untouched. The committed-tree snapshot is
delegated to
``scripts/core_editable_ppt_acceptance._snapshot_committed_tree`` so
the snapshot scope is the SAME broad set of top-level paths the
aggregate quality gate already protects (``.gitignore`` /
``AGENTS.md`` / ``CLAUDE.md`` / ``README.md`` / ``SECURITY.md`` /
``SKILL.md`` / ``examples`` / ``references`` / ``schemas`` /
``scripts`` / ``templates``); a leak under any of those — including
root-level committed files and the ``references`` / ``schemas`` /
``templates`` trees — is caught here too.

Clean-room: this smoke shares no prompts, assets, examples, tables,
CSV rows, wording, code, or deck structure with any upstream
project. Aligned only with the local-only image-generation idea
that generated-image work should carry auditable prompt/request
metadata AND provenance/analysis records — the implementation,
field set, and assertion stack are this repo's own.

Happy-path assertions (every one is an assertion that flips the
emitter's ``summary.ok`` to False; the script exits non-zero on any
failure):

  H1  every ``requests[]`` entry on the committed ``d_one_spec.json``
      has a 1:1 row in the derived provenance object;
  H2  at least ``MIN_REQUESTS`` (today: 2) request rows;
  H3  every committed ``placement_role`` value
      (``EXPECTED_PLACEMENT_ROLES`` = ``hero_page`` + ``local_region``)
      appears across the rows;
  H4  at least ``MIN_TEXT_POLICIES`` (today: 2) distinct
      ``text_policy`` values across the rows;
  H5  for every row: spec / sidecar / manifest carry byte-identical
      ``placement_role`` / ``text_policy`` / ``subject_domain`` /
      ``manifest_local_path`` values per id (drift here would mean
      the runner's taxonomy preservation marker lied);
  H6  every generated asset file exists as a regular non-symlink
      file with a ``.png`` / ``.jpg`` / ``.jpeg`` extension; the
      file's recomputed ``byte_count`` matches the recorded value
      AND is > 0; the file's recomputed ``sha256`` matches the
      recorded value AND is a lowercase 64-char hex string;
  H7  the produced ``.pptx`` carries a ``ppt/media/*`` part whose
      ``sha256`` matches the workspace asset's ``sha256``
      byte-for-byte (no transcode silently happened during embed);
  H8  no path-typed field on any row carries a URI scheme prefix,
      a ``..`` traversal segment, an absolute output-escape path,
      or anything outside the workspace / PPTX-internal namespace;
  H9  no field anywhere in the derived object carries credential /
      token / API-key / sk- shapes;
  H10 no field anywhere in the derived object carries public-upload
      / public-share / public-hosting / image-hosting wording;
  H11 no field anywhere in the derived object carries raw-source /
      confidential / customer markers;
  H12 the derived object's ``real_d_one_status`` carries the fixed
      ``UNVERIFIED`` sentence AND no positive real-D-One / MCP /
      public-network / model-API / image-search / Qoder success
      claim appears anywhere in the object;
  H13 the produced PPTX ``inventory.json`` reports zero external
      relationships — every ``relationships[].Target`` is
      package-internal AND no ``TargetMode == "External"`` appears.

Fail-closed probes (every probe runs on a clean copy of the
happy-path provenance object so a probe-induced failure cannot leak
into the next probe; every probe asserts the documented gate
**actually fires** AND that the happy-path baseline still passes):

  P1  missing row for a committed request id — drop the
      ``cover_accent`` row from the provenance and assert
      ``_check_request_id_coverage`` flags the regression;
  P2  mismatched ``text_policy`` vs the committed ``d_one_spec.json``
      — flip one row's ``text_policy`` away from the spec value and
      assert ``_check_per_id_parity`` flags the regression;
  P3  collapsed ``text_policy`` coverage — flatten every row's
      ``text_policy`` to a single value (typically ``no_text``) and
      assert ``_check_text_policy_diversity`` flags the regression;
  P4  tampered ``sha256`` / ``byte_count`` — alter one row's recorded
      ``asset.sha256`` and ``asset.byte_count`` and assert
      ``_check_asset_bytes_integrity`` flags the regression (the
      gate re-reads the file from disk and refuses any row whose
      recorded values do not match the file's actual bytes);
  P5  unsafe path / URI-shaped asset path — inject ``http://...``
      and ``../escape.png`` shapes into the row's path-typed fields
      and assert ``_check_path_safety`` flags both;
  P6  public-hosting wording — inject public-upload / public-share /
      public-hosting / image-hosting phrasing into a free-text field
      and assert ``_check_string_safety`` flags every variant;
  P7  raw-source / confidential / customer markers — inject every
      forbidden marker and assert ``_check_string_safety`` flags it;
  P8  positive real-D-One / MCP / model-API success claim — inject
      every forbidden shape into the object and assert
      ``_check_real_d_one_refusal`` flags each; also confirm the
      canonical happy-path object stays clean under the same gate.

MOCK / STUB ONLY — NOT real D-One integration. Nothing in this smoke
calls D-One, MCP, Qoder, a public network, telemetry, any model
API, an image search, or any external service. The asset bytes
generated by ``run_d_one_generation --allow-synthetic-bytes`` are a
fixed minimal PNG payload per request, never a real image. The
provenance record this smoke emits is local audit evidence about
that synthetic mock chain, not a claim that any external service
ran or succeeded.

Wired into ``scripts/core_editable_ppt_acceptance.py`` because the
end-to-end pipeline run plus the in-process probes complete well
within the existing aggregate's per-smoke budget (the runner is
already the slowest step in the surrounding smokes, and we reuse
its single happy-path invocation here).

Usage:
  python3 scripts/mock_generated_image_provenance_smoke.py --self-test

Stdlib-only. NETWORK-FREE. NO real D-One. NO MCP. NO Qoder. NO model
API. NO image search. NO telemetry. NOT a full prompt/report/
Markdown-to-PPTX automation — the smoke composes the committed mock
chain and records what it produced; it does not extend any pipeline
stage and does not extract source content.
"""
from __future__ import annotations

import sys

# Refuse to write `.pyc` files for any module imported by this smoke.
# The smoke contract says it writes nothing under the repo tree; this
# flip closes a regression where a first-party import would silently
# leak `scripts/__pycache__/<mod>.cpython-*.pyc` on a clean checkout.
# Must come BEFORE any first-party import — the interpreter checks
# the flag at bytecode-write time.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
TEMPLATE_ROOT = REPO_ROOT / "templates" / "layouts"
COMMITTED_BUNDLE = REPO_ROOT / "examples" / "synthetic_mock_image_trial"

sys.path.insert(0, str(SCRIPTS_DIR))

from core_editable_ppt_acceptance import (  # noqa: E402
    _snapshot_committed_tree,
)

# Goal-pinned invariants. Today: at least two requests, both
# placement_role values, and at least two distinct text_policy values.
MIN_REQUESTS = 2
EXPECTED_PLACEMENT_ROLES: frozenset[str] = frozenset({
    "hero_page", "local_region",
})
MIN_TEXT_POLICIES = 2

EVIDENCE_SIDECAR_FILENAME = "mock_d_one_adapter_plan.json"
INVENTORY_FILENAME = "inventory.json"
PROVENANCE_FILENAME = "mock_generated_image_provenance.json"

# Locked sidecar plan schema version (mirrors
# run_mock_image_pipeline.LOCKED_PLAN_SCHEMA_VERSION); used as a
# belt-and-braces gate on the runner-written audit copy.
LOCKED_SIDECAR_SCHEMA_VERSION = 4

# Embed surface scripts/export_pptx.py supports today. Mirrors the
# constant in the sibling smokes — the gate is a presence check on the
# workspace asset's lower-cased extension being one of these. Anything
# else is a regression in the runner / exporter, not a permissive
# extension list the provenance smoke should tolerate.
_ALLOWED_EXTS: tuple[str, ...] = (".png", ".jpg", ".jpeg")

# Conservative media-type projection. The exporter writes one of these
# Content-Types into ``[Content_Types].xml`` for each embed surface
# extension; the provenance row records the projected value (NOT the
# observed inventory content_type — that is recorded separately under
# pptx_media.content_type so a future drift between the two would
# surface).
_EXT_TO_MEDIA_TYPE: dict[str, str] = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
}

# RFC-3986-shaped scheme detector. Anchored at start; rejects
# ``http://...``, ``https://...``, ``file://...``, ``data:...``,
# ``ftp://...``, etc. Internal package paths and workspace-relative
# paths carry no scheme prefix.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Lowercase 64-char hex. Mirrors the format ``hashlib.sha256().hexdigest()``
# emits — uppercase or non-hex characters in a row's ``sha256`` are
# refused even if the value coincidentally matches a real digest.
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Credential / token / API-key shapes. The recorded provenance object
# never has a legitimate reason to carry any of these; finding one
# means a downstream change leaked an external integration's secret
# into the local audit evidence.
_FORBIDDEN_CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"bearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    re.compile(r"token\s*[:=]\s*[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    re.compile(r"password\s*[:=]", re.IGNORECASE),
    re.compile(r"secret\s*[:=]", re.IGNORECASE),
    re.compile(r"authorization\s*:\s*[A-Za-z]", re.IGNORECASE),
)

# Public-upload / public-share / public-hosting wording. The mock chain
# never uploads anywhere; any wording suggesting otherwise belongs in
# the forbidden set so a downstream evidence template that drifted
# toward implying a public upload is refused.
_FORBIDDEN_PUBLIC_HOSTING_TOKENS: tuple[str, ...] = (
    "uploaded to", "upload to", "uploading to",
    "public upload", "public-upload", "public_upload",
    "publicly upload", "publicly uploaded",
    "public share", "public-share", "public_share",
    "publicly share", "publicly shared", "public sharing",
    "public hosting", "public-hosting", "public_hosting",
    "publicly hosted", "image hosting", "image-hosting",
    "image_hosting", "hosted image",
    "imgur", "drive.google.com", "dropbox.com",
    "s3.amazonaws.com", "googleusercontent.com",
    "cdn.discordapp.com", "cdn.openai.com",
)

# Raw-source / confidential / customer markers. The local mock chain
# only ever sees synthetic redacted bundles; the provenance object must
# not carry any of these markers — finding one means a downstream
# change leaked actual customer text into the local audit evidence.
_FORBIDDEN_CONFIDENTIAL_TOKENS: tuple[str, ...] = (
    "confidential", "internal use only",
    "customer ", "customer_", "customer-",
    "customer_id", "customer-id", "customerid",
    "raw source", "raw_source", "raw-source",
    "rawsource",
    "proprietary", "company secret",
)

# Real-D-One claim refusal. Mirrors the shape used by
# mock_image_bundle_trial_evidence._evidence_refuses_real_d_one_claims
# so the same gate fires here. We deliberately use a tightly scoped
# version (no full walker over arbitrary structures — every walk in
# this smoke knows whether the noun is in scope from the row schema)
# but the noun / verb sets and negation tokens are aligned.
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

# Fixed sentence pinned to the emitted provenance object. Every verb
# in this sentence is individually preceded by a negation token inside
# the local 15-char window so the real-D-One claim-refusal walker
# stays clean against the canonical happy-path object.
REAL_D_ONE_STATUS = (
    "UNVERIFIED — real D-One is NOT called by this provenance smoke. "
    "The PNG bytes embedded in the produced PPTX come from the "
    "in-script mock provider in scripts/run_d_one_generation.py "
    "(--allow-synthetic-bytes), not from any external service. No "
    "MCP, no public network, no model API, no image search, no "
    "Qoder, no telemetry."
)


# ---------------------------------------------------------------------------
# Provenance dataclass + helpers.
# ---------------------------------------------------------------------------


@dataclass
class _ProvenanceRow:
    """Single per-request row in the derived provenance object. Carries
    the spec / sidecar / manifest fields the goal pins PLUS the
    asset-on-disk evidence and the PPTX-media inventory match. Every
    field is recorded verbatim so a reviewer can audit the row without
    re-reading the workspace bytes."""
    id: str
    placement_role: str
    text_policy: str
    subject_domain: str
    manifest_local_path: str
    spec: dict
    sidecar: dict
    asset: dict
    pptx_media: dict | None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "placement_role": self.placement_role,
            "text_policy": self.text_policy,
            "subject_domain": self.subject_domain,
            "manifest_local_path": self.manifest_local_path,
            "spec": self.spec,
            "sidecar": self.sidecar,
            "asset": self.asset,
            "pptx_media": self.pptx_media,
        }


# ---------------------------------------------------------------------------
# Subprocess driver. The smoke shells out to the existing runner so
# every stage's argparse + fail-closed gates + stdout/stderr cascade is
# exercised verbatim.
# ---------------------------------------------------------------------------


@dataclass
class _ToolOutcome:
    name: str
    cmd: list[str]
    rc: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.rc == 0

    @property
    def combined(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


def _run_runner(
    *, bundle: Path, workspace: Path, output: Path, report_dir: Path,
) -> _ToolOutcome:
    cmd = [
        sys.executable, str(SCRIPTS_DIR / "run_mock_image_pipeline.py"),
        "--bundle", str(bundle),
        "--workspace", str(workspace),
        "--template-root", str(TEMPLATE_ROOT),
        "--output", str(output),
        "--report-dir", str(report_dir),
        "--allow-synthetic-bytes",
    ]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    return _ToolOutcome(
        name="run_mock_image_pipeline --bundle "
             "examples/synthetic_mock_image_trial",
        cmd=cmd, rc=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


def _print_outcome(o: _ToolOutcome) -> None:
    mark = "PASS" if o.ok else "FAIL"
    print(f"  [{mark}] {o.name} (rc={o.rc})")
    if not o.ok:
        for label, text in (("stdout", o.stdout), ("stderr", o.stderr)):
            tail = (text or "").splitlines()[-15:]
            if tail:
                print(f"    {label} tail:")
                for line in tail:
                    print(f"      {line}")


# ---------------------------------------------------------------------------
# Provenance derivation. Reads bundle (committed, read-only), sidecar
# (runner-written, tempdir-only), inventory (run_explicit_pipeline-
# written, tempdir-only), and workspace assets (tempdir-only).
# ---------------------------------------------------------------------------


def _load_json_object(path: Path) -> tuple[dict | None, str]:
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


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect_asset_evidence(
    workspace: Path, manifest_local_path: str,
) -> dict:
    """Read the workspace asset at ``<workspace>/<manifest_local_path>``
    and return a flat dict capturing the evidence needed to certify
    the bytes downstream — absolute path, byte_count, sha256,
    extension, and conservative media_type projected from the
    extension. The workspace path is the materialized copy
    ``materialize_image_assets`` produced from the staging assets dir;
    its bytes are byte-identical to the synthetic PNG the mock
    provider emitted.

    Returns a sentinel dict on any read failure so the caller can
    surface the failure as a per-row assertion rather than crashing
    the entire derivation. The sentinel always carries the same key
    set (``path`` / ``exists`` / ``byte_count`` / ``sha256`` /
    ``extension`` / ``media_type`` / ``error``) so the row schema
    stays stable across pass/fail."""
    asset_path = workspace / manifest_local_path
    out: dict = {
        "path": str(asset_path),
        "exists": False,
        "byte_count": 0,
        "sha256": "",
        "extension": "",
        "media_type": "",
        "error": "",
    }
    if asset_path.is_symlink():
        out["error"] = "refused symlink"
        return out
    if not asset_path.is_file():
        out["error"] = "missing or non-regular file"
        return out
    out["exists"] = True
    out["byte_count"] = asset_path.stat().st_size
    try:
        out["sha256"] = _sha256_of_file(asset_path)
    except OSError as exc:
        out["error"] = f"sha256 read failed: {type(exc).__name__}: {exc}"
        return out
    ext_lower = asset_path.suffix.lower().lstrip(".")
    out["extension"] = ext_lower
    out["media_type"] = _EXT_TO_MEDIA_TYPE.get(ext_lower, "")
    return out


def _match_pptx_media(
    inventory: dict, *, sha256: str,
) -> dict | None:
    """Walk ``inventory.media_parts`` and return the first entry whose
    ``sha256`` matches the supplied hash. Returns ``None`` when no
    match is found — the caller surfaces that as a per-row failure.

    Matching by ``sha256`` (not by ``part`` path) is deliberate: the
    exporter renames bytes to ``ppt/media/imageN.<ext>`` so the
    workspace path and the embedded path do not agree, but the bytes
    are byte-identical so the digests do. A regression that transcoded
    or recompressed the bytes during embed would surface as a missing
    sha256 match here."""
    media_parts = inventory.get("media_parts")
    if not isinstance(media_parts, list):
        return None
    for m in media_parts:
        if not isinstance(m, dict):
            continue
        if m.get("sha256") == sha256:
            return {
                "part": m.get("part"),
                "size_bytes": m.get("size_bytes"),
                "sha256": m.get("sha256"),
                "extension": m.get("extension"),
                "content_type": m.get("content_type"),
                "referencing_slides": m.get("referencing_slides"),
            }
    return None


def _derive_provenance(
    *, bundle: Path, workspace: Path, report_dir: Path, pptx: Path,
) -> tuple[dict, list[str]]:
    """Drive the read-only derivation of the provenance object from
    the bundle (committed) + sidecar / inventory / workspace
    (tempdir-only). Returns ``(provenance, derivation_errors)`` —
    derivation_errors is a list of human-readable strings for any
    structural read failure (missing file, parse error, missing key).
    A row is created for every spec request id; per-row content
    failures (asset missing, sha mismatch, no pptx_media match) are
    recorded on the row itself so the assertion stack can surface
    them as goal-mapped checks rather than derivation failures."""
    errors: list[str] = []

    spec_doc, msg = _load_json_object(bundle / "d_one_spec.json")
    if spec_doc is None:
        errors.append(f"bundle/d_one_spec.json: {msg}")
        spec_requests: list = []
    else:
        spec_requests = spec_doc.get("requests")
        if not isinstance(spec_requests, list):
            errors.append(
                "bundle/d_one_spec.json: 'requests' is not a list"
            )
            spec_requests = []

    manifest_doc, msg = _load_json_object(
        bundle / "image_manifest_spec.json",
    )
    if manifest_doc is None:
        errors.append(f"bundle/image_manifest_spec.json: {msg}")
        manifest_by_id: dict[str, dict] = {}
    else:
        images = manifest_doc.get("images")
        if not isinstance(images, list):
            errors.append(
                "bundle/image_manifest_spec.json: 'images' is not a list"
            )
            manifest_by_id = {}
        else:
            manifest_by_id = {
                img["id"]: img
                for img in images
                if isinstance(img, dict) and isinstance(img.get("id"), str)
            }

    sidecar_path = report_dir / EVIDENCE_SIDECAR_FILENAME
    sidecar_doc, msg = _load_json_object(sidecar_path)
    if sidecar_doc is None:
        errors.append(f"sidecar {sidecar_path}: {msg}")
        sidecar_by_id: dict[str, dict] = {}
        sidecar_schema_version = None
        sidecar_request_count = None
    else:
        sidecar_schema_version = sidecar_doc.get("schema_version")
        sidecar_request_count = sidecar_doc.get("request_count")
        sidecar_requests = sidecar_doc.get("requests")
        if not isinstance(sidecar_requests, list):
            errors.append(
                f"sidecar {sidecar_path}: 'requests' is not a list"
            )
            sidecar_by_id = {}
        else:
            sidecar_by_id = {
                r["id"]: r
                for r in sidecar_requests
                if isinstance(r, dict) and isinstance(r.get("id"), str)
            }

    inventory_path = report_dir / INVENTORY_FILENAME
    inventory_doc, msg = _load_json_object(inventory_path)
    if inventory_doc is None:
        errors.append(f"inventory {inventory_path}: {msg}")
        inventory_doc = {}

    rows: list[_ProvenanceRow] = []
    for req in spec_requests:
        if not isinstance(req, dict):
            continue
        rid = req.get("id")
        if not isinstance(rid, str) or not rid:
            continue
        manifest_entry = manifest_by_id.get(rid) or {}
        sidecar_entry = sidecar_by_id.get(rid) or {}
        local_path = (
            sidecar_entry.get("manifest_local_path")
            or manifest_entry.get("local_path")
            or ""
        )
        asset = (
            _collect_asset_evidence(workspace, local_path)
            if isinstance(local_path, str) and local_path
            else {
                "path": "", "exists": False, "byte_count": 0,
                "sha256": "", "extension": "", "media_type": "",
                "error": "missing manifest_local_path",
            }
        )
        pptx_media = (
            _match_pptx_media(inventory_doc, sha256=asset["sha256"])
            if asset["sha256"] else None
        )
        rows.append(_ProvenanceRow(
            id=rid,
            placement_role=str(req.get("placement_role") or ""),
            text_policy=str(req.get("text_policy") or ""),
            subject_domain=str(req.get("subject_domain") or ""),
            manifest_local_path=local_path
            if isinstance(local_path, str) else "",
            spec={
                "placement_role": req.get("placement_role"),
                "text_policy": req.get("text_policy"),
                "subject_domain": req.get("subject_domain"),
                "intended_use": req.get("intended_use"),
            },
            sidecar={
                "placement_role": sidecar_entry.get("placement_role"),
                "text_policy": sidecar_entry.get("text_policy"),
                "subject_domain": sidecar_entry.get("subject_domain"),
                "manifest_local_path": sidecar_entry.get(
                    "manifest_local_path",
                ),
            },
            asset=asset,
            pptx_media=pptx_media,
        ))

    provenance: dict = {
        "schema_version": "1",
        "evidence_id": "mock_generated_image_provenance",
        "real_d_one_status": REAL_D_ONE_STATUS,
        "bundle_path": str(bundle),
        "workspace_path": str(workspace),
        "report_dir": str(report_dir),
        "pptx_path": str(pptx),
        "sidecar": {
            "path": str(sidecar_path),
            "schema_version": sidecar_schema_version,
            "request_count": sidecar_request_count,
        },
        "inventory": {
            "path": str(inventory_path),
            "ok": inventory_doc.get("ok"),
            "findings_empty": inventory_doc.get("findings") == [],
            "slide_count": inventory_doc.get("slide_count"),
            "relationships_external_count": (
                _count_external_relationships(inventory_doc)
            ),
        },
        "rows": [r.as_dict() for r in rows],
        "notes": {
            "scope": (
                "Mock-image generated-image provenance only. Drives the "
                "COMMITTED examples/synthetic_mock_image_trial bundle "
                "through run_mock_image_pipeline.py --bundle into a "
                "tempfile-owned workspace/output/report directory and "
                "records per-request provenance linking spec ids to "
                "manifest path, sidecar metadata, workspace asset "
                "bytes (byte_count + sha256), and PPTX-media inventory. "
                "NOT real D-One, NOT MCP, NOT Qoder, NOT a public-"
                "network run, NOT telemetry, NOT a prompt/report/"
                "Markdown-to-PPTX automation."
            ),
            "embed_surface": (
                "PNG/JPG/JPEG inside ppt/media/* — the subset "
                "scripts/export_pptx.py supports today. Anything "
                "outside that subset fails closed at the exporter."
            ),
        },
    }
    return provenance, errors


def _count_external_relationships(inventory: dict) -> int:
    """Return the number of relationships in ``inventory.relationships``
    whose ``Target`` carries an RFC-3986 URI scheme prefix OR whose
    ``target_mode`` is non-internal. Zero is the documented happy-path
    invariant; a non-zero count is itself the gate finding."""
    rels = inventory.get("relationships")
    if not isinstance(rels, list):
        return 0
    n = 0
    for r in rels:
        if not isinstance(r, dict):
            continue
        target = r.get("target") or ""
        mode = (r.get("target_mode") or "").lower()
        if mode and mode != "internal":
            n += 1
            continue
        if isinstance(target, str) and _URI_SCHEME_PREFIX.match(target):
            n += 1
    return n


# ---------------------------------------------------------------------------
# Assertion stack. Each helper takes the assembled provenance dict and
# returns a list of human-readable failure strings. An empty list means
# the gate held. The probes in --self-test call these helpers directly
# on tampered copies of the happy-path object so a regression in any
# one gate is surfaced individually.
# ---------------------------------------------------------------------------


def _check_request_id_coverage(
    provenance: dict, *, expected_ids: list[str],
) -> list[str]:
    rows = provenance.get("rows", [])
    have = {r.get("id") for r in rows if isinstance(r, dict)}
    missing = [rid for rid in expected_ids if rid not in have]
    if not missing:
        return []
    return [
        f"H1 missing provenance row for committed request id(s): "
        f"{missing!r}"
    ]


def _check_row_count(provenance: dict) -> list[str]:
    rows = provenance.get("rows", [])
    if len(rows) >= MIN_REQUESTS:
        return []
    return [
        f"H2 fewer than MIN_REQUESTS={MIN_REQUESTS} rows in "
        f"provenance (got {len(rows)})"
    ]


def _check_placement_role_coverage(provenance: dict) -> list[str]:
    rows = provenance.get("rows", [])
    seen = {
        r.get("placement_role") for r in rows if isinstance(r, dict)
    } - {""}
    missing = sorted(EXPECTED_PLACEMENT_ROLES - seen)
    if not missing:
        return []
    return [
        f"H3 placement_role coverage incomplete; missing "
        f"{missing!r} (saw {sorted(seen)!r})"
    ]


def _check_text_policy_diversity(provenance: dict) -> list[str]:
    rows = provenance.get("rows", [])
    seen = {
        r.get("text_policy") for r in rows if isinstance(r, dict)
    } - {""}
    if len(seen) >= MIN_TEXT_POLICIES:
        return []
    return [
        f"H4 text_policy coverage collapsed; saw {sorted(seen)!r} "
        f"(expected at least {MIN_TEXT_POLICIES} distinct values)"
    ]


def _check_per_id_parity(provenance: dict) -> list[str]:
    """For each row, assert spec / sidecar carry byte-identical
    placement_role / text_policy / subject_domain / manifest_local_path
    values per id. The runner's taxonomy preservation marker already
    certifies the sidecar values byte-match the spec values; this is
    belt-and-braces from the row level."""
    failures: list[str] = []
    for r in provenance.get("rows", []):
        if not isinstance(r, dict):
            continue
        rid = r.get("id")
        for f in (
            "placement_role", "text_policy", "subject_domain",
        ):
            spec_v = (r.get("spec") or {}).get(f)
            sidecar_v = (r.get("sidecar") or {}).get(f)
            row_v = r.get(f)
            if not (row_v == spec_v == sidecar_v):
                failures.append(
                    f"H5 per-id parity drift on id={rid!r} "
                    f"field={f!r}: row={row_v!r} spec={spec_v!r} "
                    f"sidecar={sidecar_v!r}"
                )
        mlp_row = r.get("manifest_local_path")
        mlp_sidecar = (r.get("sidecar") or {}).get(
            "manifest_local_path",
        )
        if mlp_row != mlp_sidecar:
            failures.append(
                f"H5 per-id manifest_local_path drift on id={rid!r}: "
                f"row={mlp_row!r} sidecar={mlp_sidecar!r}"
            )
    return failures


def _check_asset_bytes_integrity(provenance: dict) -> list[str]:
    """Re-read each asset's bytes from disk and compare byte_count +
    sha256 against the recorded values. Refuses any row whose recorded
    sha256 isn't lowercase 64-hex, whose byte_count isn't > 0, whose
    extension isn't in ``_ALLOWED_EXTS``, whose path is a symlink, or
    whose file does not exist as a regular non-symlink. Catches the
    'tampered sha256 / byte_count' regression class."""
    failures: list[str] = []
    for r in provenance.get("rows", []):
        if not isinstance(r, dict):
            continue
        rid = r.get("id")
        asset = r.get("asset") or {}
        path_str = asset.get("path") or ""
        if not isinstance(path_str, str) or not path_str:
            failures.append(
                f"H6 row id={rid!r} carries no asset.path"
            )
            continue
        asset_path = Path(path_str)
        if asset_path.is_symlink():
            failures.append(
                f"H6 row id={rid!r} asset.path {path_str!r} is a "
                f"symlink (refused)"
            )
            continue
        if not asset_path.is_file():
            failures.append(
                f"H6 row id={rid!r} asset.path {path_str!r} is not "
                f"a regular file"
            )
            continue
        ext = asset.get("extension")
        if (not isinstance(ext, str)
                or "." + ext.lower() not in _ALLOWED_EXTS):
            failures.append(
                f"H6 row id={rid!r} asset.extension {ext!r} is not "
                f"one of {_ALLOWED_EXTS!r}"
            )
        recorded_bc = asset.get("byte_count")
        if not isinstance(recorded_bc, int) or recorded_bc <= 0:
            failures.append(
                f"H6 row id={rid!r} asset.byte_count {recorded_bc!r} "
                f"is not a positive integer"
            )
        actual_bc = asset_path.stat().st_size
        if recorded_bc != actual_bc:
            failures.append(
                f"H6 row id={rid!r} asset.byte_count drift: "
                f"recorded={recorded_bc!r} actual={actual_bc!r}"
            )
        recorded_sha = asset.get("sha256")
        if (not isinstance(recorded_sha, str)
                or not _SHA256_RE.match(recorded_sha)):
            failures.append(
                f"H6 row id={rid!r} asset.sha256 {recorded_sha!r} "
                f"is not a lowercase 64-char hex string"
            )
            continue
        actual_sha = _sha256_of_file(asset_path)
        if recorded_sha != actual_sha:
            failures.append(
                f"H6 row id={rid!r} asset.sha256 drift: "
                f"recorded={recorded_sha!r} actual={actual_sha!r}"
            )
    return failures


def _check_pptx_media_match(provenance: dict) -> list[str]:
    """Each row must carry a non-null ``pptx_media`` block whose
    ``sha256`` byte-matches ``asset.sha256``, whose ``part`` lives
    under ``ppt/media/``, and whose ``content_type`` is one of the
    embed-surface values. Catches the 'workspace bytes never embedded'
    regression."""
    failures: list[str] = []
    for r in provenance.get("rows", []):
        if not isinstance(r, dict):
            continue
        rid = r.get("id")
        media = r.get("pptx_media")
        if not isinstance(media, dict):
            failures.append(
                f"H7 row id={rid!r} has no pptx_media match for the "
                f"workspace asset bytes"
            )
            continue
        part = media.get("part")
        if not (isinstance(part, str) and part.startswith("ppt/media/")):
            failures.append(
                f"H7 row id={rid!r} pptx_media.part {part!r} is not "
                f"under ppt/media/*"
            )
        asset_sha = (r.get("asset") or {}).get("sha256")
        media_sha = media.get("sha256")
        if asset_sha != media_sha:
            failures.append(
                f"H7 row id={rid!r} sha256 drift between workspace "
                f"asset and PPTX media: asset={asset_sha!r} "
                f"pptx_media={media_sha!r}"
            )
        ct = media.get("content_type")
        if ct not in {"image/png", "image/jpeg"}:
            failures.append(
                f"H7 row id={rid!r} pptx_media.content_type {ct!r} "
                f"is not one of image/png / image/jpeg"
            )
    return failures


def _check_path_safety(provenance: dict) -> list[str]:
    """Refuse three classes of unsafe value on every path-typed field
    of every row:

      * URI scheme prefix anywhere (``http://`` / ``file://`` / ``data:``
        / etc. — an external embed surface the local mock chain has no
        business naming);
      * ``..`` traversal segment anywhere (would let an attacker walk
        outside the workspace / package even if the path looks
        relative);
      * absolute-output escape — the previous implementation passed
        ANY absolute path on ``asset.path`` that had no URI scheme and
        no ``..`` segment, so ``/etc/passwd`` false-greened. The new
        gate pins each path-typed field to its expected shape:

          - ``manifest_local_path`` (top-level on the row) AND
            ``sidecar.manifest_local_path`` are workspace-relative;
            an absolute or home-relative value escapes the workspace
            namespace and is refused even when it has no ``..``;
          - ``asset.path`` is the on-disk absolute location of the
            workspace asset; it must be absolute AND, when
            ``workspace_path`` is recorded on the provenance, lexically
            start with the workspace_path prefix. An absolute path
            elsewhere on disk (e.g. ``/etc/passwd``) is the
            absolute-output-escape class the Codex review caught;
          - ``pptx_media.part`` is the package-internal OOXML part
            path; it must be relative AND under ``ppt/media/``."""
    failures: list[str] = []
    workspace_path = str(provenance.get("workspace_path") or "")
    # Normalise so ``/tmp/ws`` and ``/tmp/ws/`` produce the same
    # prefix. Empty workspace_path disables the prefix gate (the
    # absolute-and-non-prefix check is the strict one, so an absent
    # workspace_path still gets the absolute-vs-relative gate).
    ws_prefix = (workspace_path.rstrip("/") + "/") if workspace_path else ""
    for r in provenance.get("rows", []):
        if not isinstance(r, dict):
            continue
        rid = r.get("id")
        # manifest_local_path (top-level on row).
        mlp = r.get("manifest_local_path")
        if isinstance(mlp, str) and mlp:
            failures.extend(_workspace_relative_failures(
                rid, "manifest_local_path", mlp,
            ))
        # sidecar.manifest_local_path (defence-in-depth — the
        # per-id-parity gate already cross-checks against the row
        # value, but a tampered record could match BOTH the row and
        # the sidecar to the same unsafe value).
        sc = r.get("sidecar")
        if isinstance(sc, dict):
            sc_mlp = sc.get("manifest_local_path")
            if isinstance(sc_mlp, str) and sc_mlp:
                failures.extend(_workspace_relative_failures(
                    rid, "sidecar.manifest_local_path", sc_mlp,
                ))
        # asset.path — absolute, under workspace_path.
        asset = r.get("asset")
        if isinstance(asset, dict):
            ap = asset.get("path")
            if isinstance(ap, str) and ap:
                failures.extend(_absolute_under_workspace_failures(
                    rid, "asset.path", ap, ws_prefix, workspace_path,
                ))
        # pptx_media.part — relative, under ppt/media/.
        media = r.get("pptx_media")
        if isinstance(media, dict):
            part = media.get("part")
            if isinstance(part, str) and part:
                failures.extend(_pptx_media_part_failures(
                    rid, "pptx_media.part", part,
                ))
    return failures


def _workspace_relative_failures(
    rid, label: str, val: str,
) -> list[str]:
    """A workspace-relative path must have no URI scheme, no ``..``
    segment, no leading ``/`` (absolute), and no leading ``~`` (home-
    relative). Anything else is an absolute-output escape regardless
    of whether ``..`` appears."""
    out: list[str] = []
    if _URI_SCHEME_PREFIX.match(val):
        out.append(
            f"H8 row id={rid!r} field {label} {val!r} carries a URI "
            f"scheme prefix"
        )
    parts = val.replace("\\", "/").split("/")
    if ".." in parts:
        out.append(
            f"H8 row id={rid!r} field {label} {val!r} contains a `..` "
            f"traversal segment"
        )
    if val.startswith("/") or val.startswith("~"):
        out.append(
            f"H8 row id={rid!r} field {label} {val!r} is absolute / "
            f"home-relative (expected workspace-relative); the "
            f"previous gate let an absolute path with no `..` segment "
            f"through (absolute-output-escape false green)"
        )
    return out


def _absolute_under_workspace_failures(
    rid, label: str, val: str, ws_prefix: str, workspace_path: str,
) -> list[str]:
    """``asset.path`` is recorded as an absolute on-disk path; refuse
    URI schemes, refuse any ``..`` segment, require an absolute path,
    AND (when ``workspace_path`` is recorded) require the value to
    lexically sit under ``workspace_path``. The lexical prefix gate is
    what catches the absolute-output-escape class — ``/etc/passwd`` and
    ``/var/run/secrets.txt`` carry no URI and no ``..`` so the previous
    helper false-greened them."""
    out: list[str] = []
    if _URI_SCHEME_PREFIX.match(val):
        out.append(
            f"H8 row id={rid!r} field {label} {val!r} carries a URI "
            f"scheme prefix"
        )
    parts = val.replace("\\", "/").split("/")
    if ".." in parts:
        out.append(
            f"H8 row id={rid!r} field {label} {val!r} contains a `..` "
            f"traversal segment"
        )
    if not val.startswith("/"):
        out.append(
            f"H8 row id={rid!r} field {label} {val!r} is not absolute "
            f"(expected absolute path under workspace_path="
            f"{workspace_path!r})"
        )
    elif ws_prefix and not val.startswith(ws_prefix):
        out.append(
            f"H8 row id={rid!r} field {label} {val!r} escapes "
            f"workspace_path={workspace_path!r} (absolute-output "
            f"escape — absolute on-disk path outside the tempdir-"
            f"owned workspace)"
        )
    return out


def _pptx_media_part_failures(
    rid, label: str, val: str,
) -> list[str]:
    """``pptx_media.part`` is the OOXML part path the exporter writes.
    Refuse URI schemes, refuse ``..`` segments, refuse leading ``/``
    (an absolute path inside a zip package is itself a smell), and
    require the part to live under ``ppt/media/`` (anywhere else is
    not the embed surface the exporter / inventory walks)."""
    out: list[str] = []
    if _URI_SCHEME_PREFIX.match(val):
        out.append(
            f"H8 row id={rid!r} field {label} {val!r} carries a URI "
            f"scheme prefix"
        )
    parts = val.replace("\\", "/").split("/")
    if ".." in parts:
        out.append(
            f"H8 row id={rid!r} field {label} {val!r} contains a `..` "
            f"traversal segment"
        )
    if val.startswith("/"):
        out.append(
            f"H8 row id={rid!r} field {label} {val!r} is absolute "
            f"(expected package-relative under ppt/media/)"
        )
    elif not val.startswith("ppt/media/"):
        out.append(
            f"H8 row id={rid!r} field {label} {val!r} is not under "
            f"ppt/media/ (the only embed surface the exporter writes)"
        )
    return out


def _iter_strings(node, path: str = ""):
    """Walk every string scalar in ``node`` and yield
    ``(json_path, value)``. Lists and dicts are recursed into."""
    if isinstance(node, dict):
        for k, v in node.items():
            sub = f"{path}.{k}" if path else str(k)
            yield from _iter_strings(v, sub)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _iter_strings(item, f"{path}[{i}]")
    elif isinstance(node, str):
        yield (path, node)


def _check_string_safety(provenance: dict) -> list[str]:
    """Walk every string in the provenance object and refuse:
      * credential / token / API-key / sk- shapes;
      * public-upload / public-share / public-hosting / image-hosting
        wording;
      * raw-source / confidential / customer markers.
    Returns one failure per offending (json_path, token) pair so a
    reviewer can see every match."""
    failures: list[str] = []
    for jpath, value in _iter_strings(provenance):
        low = value.lower()
        for pat in _FORBIDDEN_CREDENTIAL_PATTERNS:
            if pat.search(value):
                failures.append(
                    f"H9 credential-shape token at {jpath}: "
                    f"pattern={pat.pattern!r} value={value!r}"
                )
        for token in _FORBIDDEN_PUBLIC_HOSTING_TOKENS:
            if token in low:
                failures.append(
                    f"H10 public-hosting wording at {jpath}: "
                    f"token={token!r} value={value!r}"
                )
        for token in _FORBIDDEN_CONFIDENTIAL_TOKENS:
            if token in low:
                failures.append(
                    f"H11 confidential / raw-source marker at "
                    f"{jpath}: token={token!r} value={value!r}"
                )
    return failures


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


def _check_real_d_one_refusal(
    provenance: dict | list,
) -> list[str]:
    """Walk the assembled provenance object recursively. Refuse any
    string scalar that asserts a real-D-One / MCP / public-network /
    model-API / image-search / Qoder success claim, OR any boolean
    True at a key naming a forbidden noun. The canonical UNVERIFIED
    sentence is allowed because every verb sits inside the local
    negation window."""
    failures: list[str] = []

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
                effective_provides_noun = (
                    key_provides_noun or child_key_has_noun
                )
                if (
                    v is True
                    and effective_provides_noun
                    and child_key_has_noun
                ):
                    failures.append(
                        f"H12 boolean real-D-One claim at {sub_path}"
                    )
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
            if _string_asserts_success(
                node, key_provides_noun=key_provides_noun,
            ):
                failures.append(
                    f"H12 real-D-One success claim at {path}: "
                    f"{node!r}"
                )

    _walk(provenance, "")
    return failures


def _check_inventory_external_relationships(
    provenance: dict,
) -> list[str]:
    inv = provenance.get("inventory") or {}
    n = inv.get("relationships_external_count")
    if isinstance(n, int) and n == 0:
        return []
    return [
        f"H13 inventory.relationships_external_count = {n!r} "
        f"(expected 0)"
    ]


def _check_sidecar_schema_version(provenance: dict) -> list[str]:
    sv = (provenance.get("sidecar") or {}).get("schema_version")
    if sv == LOCKED_SIDECAR_SCHEMA_VERSION:
        return []
    return [
        f"H14 sidecar.schema_version = {sv!r} (expected "
        f"{LOCKED_SIDECAR_SCHEMA_VERSION})"
    ]


def _all_gates(
    provenance: dict, *, committed_request_ids: list[str],
) -> list[str]:
    """Run every gate in order and return the concatenated failure
    list. Caller treats empty as ``summary.ok=True``."""
    return (
        _check_request_id_coverage(
            provenance, expected_ids=committed_request_ids,
        )
        + _check_row_count(provenance)
        + _check_placement_role_coverage(provenance)
        + _check_text_policy_diversity(provenance)
        + _check_per_id_parity(provenance)
        + _check_asset_bytes_integrity(provenance)
        + _check_pptx_media_match(provenance)
        + _check_path_safety(provenance)
        + _check_string_safety(provenance)
        + _check_real_d_one_refusal(provenance)
        + _check_inventory_external_relationships(provenance)
        + _check_sidecar_schema_version(provenance)
    )


# ---------------------------------------------------------------------------
# Happy path. Runs the full mock chain into a tempdir, derives the
# provenance object, runs every gate, and surfaces every failure.
# ---------------------------------------------------------------------------


def _committed_request_ids(bundle: Path) -> list[str]:
    doc, _ = _load_json_object(bundle / "d_one_spec.json")
    if not doc:
        return []
    requests = doc.get("requests")
    if not isinstance(requests, list):
        return []
    return [
        r["id"] for r in requests
        if isinstance(r, dict) and isinstance(r.get("id"), str)
    ]


def _run_happy_path(td: Path) -> tuple[int, dict]:
    workspace = td / "happy_ws"
    output = td / "happy.pptx"
    report_dir = td / "happy_report"

    print("--- happy path: committed bundle through mock pipeline ---")
    print(f"  bundle:    {COMMITTED_BUNDLE.relative_to(REPO_ROOT)}")
    print(f"  workspace: {workspace}")
    print(f"  output:    {output}")
    print(f"  report:    {report_dir}")
    print()

    outcome = _run_runner(
        bundle=COMMITTED_BUNDLE, workspace=workspace,
        output=output, report_dir=report_dir,
    )
    _print_outcome(outcome)
    if not outcome.ok:
        return 1, {}

    provenance, derivation_errors = _derive_provenance(
        bundle=COMMITTED_BUNDLE, workspace=workspace,
        report_dir=report_dir, pptx=output,
    )
    if derivation_errors:
        for e in derivation_errors:
            print(f"  [FAIL] derivation: {e}")
        return 1, provenance

    failures = _all_gates(
        provenance,
        committed_request_ids=_committed_request_ids(COMMITTED_BUNDLE),
    )
    provenance["summary"] = {
        "ok": not failures,
        "row_count": len(provenance.get("rows", [])),
        "placement_role_coverage": sorted(
            {
                r.get("placement_role")
                for r in provenance.get("rows", [])
                if isinstance(r, dict) and r.get("placement_role")
            }
        ),
        "text_policy_coverage": sorted(
            {
                r.get("text_policy")
                for r in provenance.get("rows", [])
                if isinstance(r, dict) and r.get("text_policy")
            }
        ),
        "failures": failures,
    }

    # Stdout AND tempfile emission. The docstring + downstream docs
    # (README / SKILL / references/quality-gates) all promise that the
    # derived provenance object is "emitted to stdout AND to a per-run
    # tempfile". A previous revision only wrote the tempfile and
    # printed a one-line pointer at it — the Codex stop-time review
    # flagged that as a false stdout contract (a reviewer who captures
    # the smoke's stdout has only the pointer; the tempfile is gone
    # once the per-run tempdir is cleaned up, so the audit trail
    # vanishes). The fix is to emit the full JSON body to stdout in
    # the canonical deterministic shape (indent=2, sort_keys=True)
    # AND write the byte-identical bytes to the tempfile, framed by
    # explicit BEGIN / END markers so the JSON object can be sliced
    # out of a longer log capture without ambiguity.
    emitted = json.dumps(provenance, indent=2, sort_keys=True)
    prov_path = td / PROVENANCE_FILENAME
    prov_path.write_text(emitted + "\n")
    print()
    print("--- BEGIN mock_generated_image_provenance.json (stdout copy) ---")
    print(emitted)
    print("--- END mock_generated_image_provenance.json (stdout copy) ---")
    print()
    print(
        f"  provenance JSON also written to tempfile {prov_path} "
        f"(removed on exit; the stdout copy above is the durable "
        f"audit artifact)"
    )
    if failures:
        print(f"  [FAIL] {len(failures)} happy-path gate(s) flagged:")
        for f in failures:
            print(f"    - {f}")
        return 1, provenance
    print(
        f"  [PASS] all {len(provenance['rows'])} provenance row(s) "
        f"passed every gate"
    )
    return 0, provenance


# ---------------------------------------------------------------------------
# Self-test probes. Each probe takes a clean copy of the happy-path
# provenance dict, mutates it according to the documented regression
# class, calls the affected gate helper, and asserts the gate flags
# the regression. Direct (no subprocess) so the probes complete in
# < 1 sec collectively after the happy path's pipeline run.
# ---------------------------------------------------------------------------


def _clone(provenance: dict) -> dict:
    """Deep-clone via JSON round-trip. The provenance dict is built
    from JSON-decoded inputs, so a JSON round-trip is exact AND
    keeps every probe self-contained — mutations on the clone cannot
    leak back into the source object."""
    return json.loads(json.dumps(provenance))


@dataclass
class _ProbeOutcome:
    name: str
    ok: bool
    detail: str = ""


def _probe_missing_request_id(provenance: dict) -> _ProbeOutcome:
    clone = _clone(provenance)
    rows = clone.get("rows", [])
    if not rows:
        return _ProbeOutcome(
            "P1 missing row probe (no rows to drop)", False,
            "happy-path provenance carries no rows",
        )
    dropped = rows[0].get("id")
    clone["rows"] = rows[1:]
    failures = _check_request_id_coverage(
        clone,
        expected_ids=_committed_request_ids(COMMITTED_BUNDLE),
    )
    ok = bool(failures) and any(
        isinstance(dropped, str) and dropped in f for f in failures
    )
    return _ProbeOutcome(
        "P1 missing row for committed request id flips "
        "_check_request_id_coverage",
        ok,
        ("expected a failure naming the dropped id "
         f"({dropped!r}); got {failures!r}") if not ok else "",
    )


def _probe_mismatched_text_policy(provenance: dict) -> _ProbeOutcome:
    clone = _clone(provenance)
    rows = clone.get("rows", [])
    if not rows:
        return _ProbeOutcome(
            "P2 mismatched text_policy probe (no rows)", False,
            "happy-path provenance carries no rows",
        )
    # Flip the first row's text_policy AWAY from the spec value.
    row = rows[0]
    spec_tp = (row.get("spec") or {}).get("text_policy")
    flipped = (
        "caption_safe" if spec_tp != "caption_safe" else "no_text"
    )
    row["text_policy"] = flipped
    failures = _check_per_id_parity(clone)
    ok = bool(failures) and any("H5" in f for f in failures)
    return _ProbeOutcome(
        "P2 mismatched text_policy vs spec flips "
        "_check_per_id_parity",
        ok,
        f"expected an H5 failure; got {failures!r}" if not ok else "",
    )


def _probe_collapsed_text_policy(provenance: dict) -> _ProbeOutcome:
    clone = _clone(provenance)
    for r in clone.get("rows", []):
        if isinstance(r, dict):
            r["text_policy"] = "no_text"
    failures = _check_text_policy_diversity(clone)
    ok = bool(failures) and any("H4" in f for f in failures)
    return _ProbeOutcome(
        "P3 collapsed text_policy coverage flips "
        "_check_text_policy_diversity",
        ok,
        f"expected an H4 failure; got {failures!r}" if not ok else "",
    )


def _probe_tampered_sha256(provenance: dict) -> _ProbeOutcome:
    """Tamper the recorded sha256 AND byte_count on one row WITHOUT
    touching the underlying asset bytes. The integrity gate re-reads
    the file from disk and flags the drift on BOTH fields."""
    clone = _clone(provenance)
    rows = clone.get("rows", [])
    if not rows:
        return _ProbeOutcome(
            "P4 tampered sha256 probe (no rows)", False,
            "happy-path provenance carries no rows",
        )
    row = rows[0]
    asset = row.get("asset") or {}
    asset["sha256"] = "0" * 64
    asset["byte_count"] = (asset.get("byte_count") or 1) + 7
    row["asset"] = asset
    failures = _check_asset_bytes_integrity(clone)
    saw_sha = any("sha256 drift" in f for f in failures)
    saw_bc = any("byte_count drift" in f for f in failures)
    ok = saw_sha and saw_bc
    return _ProbeOutcome(
        "P4 tampered sha256 / byte_count flips "
        "_check_asset_bytes_integrity (both gates fire)",
        ok,
        (f"expected sha256 AND byte_count drift; got "
         f"saw_sha={saw_sha} saw_bc={saw_bc} failures={failures!r}")
        if not ok else "",
    )


def _probe_unsafe_path(provenance: dict) -> _ProbeOutcome:
    """Inject every documented unsafe-path shape and assert each
    gate fires. The Codex stop-time review caught that the previous
    helper false-greened any absolute path on ``asset.path`` that
    had no URI scheme and no ``..`` segment (e.g. ``/etc/passwd``),
    so the absolute-output-escape sub-case is explicitly exercised
    here as its own gate alongside URI and traversal.

    Three sub-probes run on independent clones of the happy-path
    provenance dict so a regression in any one gate is surfaced
    individually:

      a. URI-shaped ``manifest_local_path`` AND ``..``-traversal
         ``asset.path`` on the same row — both gates fire on the
         same clone (the original probe shape);
      b. Absolute-but-outside-workspace ``asset.path`` (e.g.
         ``/etc/passwd``) with NO URI scheme and NO ``..`` segment
         — this is the false-green class the Codex review caught;
         the new gate refuses it via the lexical workspace_path
         prefix check;
      c. Absolute ``manifest_local_path`` (e.g. ``/etc/shadow``) —
         the previous gate only refused URI and `..` shapes on this
         field, so an absolute escape would have passed. The new
         gate refuses any leading ``/`` or ``~`` on workspace-
         relative fields."""
    fails: list[str] = []

    # Sub-probe (a): URI scheme + traversal on the same row.
    clone_a = _clone(provenance)
    rows_a = clone_a.get("rows", [])
    if not rows_a:
        return _ProbeOutcome(
            "P5 unsafe-path probe (no rows)", False,
            "happy-path provenance carries no rows",
        )
    row_a = rows_a[0]
    row_a["manifest_local_path"] = "http://attacker/x.png"
    asset_a = row_a.get("asset") or {}
    asset_a["path"] = (
        (provenance.get("workspace_path") or "/tmp/x")
        + "/sub/../../escape.png"
    )
    row_a["asset"] = asset_a
    fa = _check_path_safety(clone_a)
    if not any("URI scheme prefix" in f for f in fa):
        fails.append(
            f"sub-probe (a) did not flag URI scheme; got {fa!r}"
        )
    if not any("`..` traversal segment" in f for f in fa):
        fails.append(
            f"sub-probe (a) did not flag `..` traversal; got {fa!r}"
        )

    # Sub-probe (b): absolute-output-escape on asset.path. NO URI
    # scheme, NO `..` segment — this is the false-green class the
    # Codex review caught.
    clone_b = _clone(provenance)
    rows_b = clone_b.get("rows", [])
    row_b = rows_b[0]
    asset_b = row_b.get("asset") or {}
    asset_b["path"] = "/etc/passwd"
    row_b["asset"] = asset_b
    fb = _check_path_safety(clone_b)
    if any("URI scheme prefix" in f for f in fb):
        fails.append(
            f"sub-probe (b) unexpectedly flagged URI on the bare "
            f"/etc/passwd value; got {fb!r}"
        )
    if any("`..` traversal segment" in f for f in fb):
        fails.append(
            f"sub-probe (b) unexpectedly flagged `..` on the bare "
            f"/etc/passwd value; got {fb!r}"
        )
    if not any(
        "absolute-output" in f or "escapes workspace_path" in f
        for f in fb
    ):
        fails.append(
            f"sub-probe (b) did not flag /etc/passwd as an absolute-"
            f"output escape; got {fb!r}"
        )

    # Sub-probe (c): absolute-output-escape on manifest_local_path.
    # A workspace-relative field must refuse leading `/` even when
    # the value has no URI scheme and no `..` segment.
    clone_c = _clone(provenance)
    rows_c = clone_c.get("rows", [])
    row_c = rows_c[0]
    row_c["manifest_local_path"] = "/etc/shadow"
    fc = _check_path_safety(clone_c)
    if not any(
        "absolute / home-relative" in f or "expected workspace-relative" in f
        for f in fc
    ):
        fails.append(
            f"sub-probe (c) did not flag /etc/shadow as an absolute "
            f"workspace-relative escape; got {fc!r}"
        )

    return _ProbeOutcome(
        "P5 every unsafe-path shape flips _check_path_safety "
        "(URI scheme, `..` traversal, absolute-output escape on "
        "asset.path, absolute escape on manifest_local_path)",
        not fails,
        "; ".join(fails),
    )


def _probe_public_hosting_wording(provenance: dict) -> _ProbeOutcome:
    """Inject every variant of public-upload / public-share /
    public-hosting / image-hosting wording into a free-text field
    and assert the gate flags each."""
    failures: list[str] = []
    for token in (
        "uploaded to imgur.com",
        "public sharing link",
        "publicly hosted CDN",
        "image hosting service",
    ):
        clone = _clone(provenance)
        rows = clone.get("rows", [])
        if rows:
            rows[0]["spec"] = rows[0].get("spec") or {}
            rows[0]["spec"]["intended_use"] = (
                f"hero-page accent; {token}"
            )
        gate = _check_string_safety(clone)
        if not any("H10" in f for f in gate):
            failures.append(
                f"public-hosting token {token!r} did not trip H10; "
                f"got {gate!r}"
            )
    return _ProbeOutcome(
        "P6 public-hosting wording variants flip "
        "_check_string_safety (every variant)",
        not failures,
        "; ".join(failures),
    )


def _probe_confidential_marker(provenance: dict) -> _ProbeOutcome:
    """Inject confidential / customer / raw-source markers into a
    free-text field and assert the gate flags each."""
    failures: list[str] = []
    for token in (
        "confidential",
        "customer_id=12345",
        "raw source document",
        "INTERNAL USE ONLY",
    ):
        clone = _clone(provenance)
        rows = clone.get("rows", [])
        if rows:
            rows[0]["spec"] = rows[0].get("spec") or {}
            rows[0]["spec"]["intended_use"] = (
                f"hero-page accent; {token}"
            )
        gate = _check_string_safety(clone)
        if not any("H11" in f for f in gate):
            failures.append(
                f"confidential token {token!r} did not trip H11; "
                f"got {gate!r}"
            )
    return _ProbeOutcome(
        "P7 confidential / customer / raw-source markers flip "
        "_check_string_safety (every variant)",
        not failures,
        "; ".join(failures),
    )


def _probe_real_d_one_claim(provenance: dict) -> _ProbeOutcome:
    """The canonical happy-path object must STAY clean under
    _check_real_d_one_refusal — the fixed UNVERIFIED sentence is
    permitted because every verb sits inside the local negation
    window. A tampered object that asserts real-D-One / MCP /
    public-network / model-API / image-search / Qoder success MUST
    trip the gate on every variant."""
    failures: list[str] = []

    # Baseline: clean object must NOT trip the gate.
    base = _check_real_d_one_refusal(provenance)
    if base:
        failures.append(
            f"baseline provenance falsely tripped H12: {base!r}"
        )

    tampered_variants: tuple[dict, ...] = (
        {"summary": {"text": "real D-One verified online."}},
        {"mcp": True},
        {"qoder": True},
        {"public_network": True},
        {"image_search": True},
        {"model_api": True},
        {"results": [
            {"status": (
                "live MCP enabled: called the model API and "
                "received bytes"
            )},
        ]},
        {"notes": {"detail": "real_d_one succeeded"}},
        {"messages": ["real D-One verified online."]},
    )
    for v in tampered_variants:
        gate = _check_real_d_one_refusal(v)
        if not gate:
            failures.append(
                f"tampered variant did not trip H12: {v!r}"
            )

    return _ProbeOutcome(
        "P8 real-D-One success claim (every shape) flips "
        "_check_real_d_one_refusal; baseline stays clean",
        not failures,
        "; ".join(failures),
    )


def _run_probes(provenance: dict) -> tuple[int, list[_ProbeOutcome]]:
    print("--- self-test fail-closed probes ---")
    probes: list[_ProbeOutcome] = [
        _probe_missing_request_id(provenance),
        _probe_mismatched_text_policy(provenance),
        _probe_collapsed_text_policy(provenance),
        _probe_tampered_sha256(provenance),
        _probe_unsafe_path(provenance),
        _probe_public_hosting_wording(provenance),
        _probe_confidential_marker(provenance),
        _probe_real_d_one_claim(provenance),
    ]
    fails = 0
    for p in probes:
        mark = "PASS" if p.ok else "FAIL"
        suffix = f" -- {p.detail}" if not p.ok and p.detail else ""
        print(f"  [{mark}] {p.name}{suffix}")
        if not p.ok:
            fails += 1
    print()
    return fails, probes


# ---------------------------------------------------------------------------
# Self-test top level.
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    print(
        "=== mock_generated_image_provenance_smoke (--self-test) ==="
    )

    # Snapshot the committed tree BEFORE the run; re-snapshot at the
    # end and refuse any mutation under REPO_ROOT. Mirrors the
    # snapshot scope every other acceptance smoke applies.
    tree_before = _snapshot_committed_tree()
    if not tree_before:
        print(
            "FAIL: committed-tree snapshot is empty — "
            "_snapshot_committed_tree returned no entries. Refusing to "
            "run because a downstream regression cannot be detected "
            "against an empty baseline.",
            file=sys.stderr,
        )
        return 1

    rc = 0
    with tempfile.TemporaryDirectory(
        prefix="szh_mock_image_provenance_",
    ) as raw_td:
        td = Path(raw_td)
        happy_rc, provenance = _run_happy_path(td)
        if happy_rc != 0:
            rc = 1
        if provenance:
            probe_fails, _ = _run_probes(provenance)
            if probe_fails:
                rc = 1
        else:
            print(
                "  [SKIP] probes (no provenance produced by "
                "happy path)"
            )
            rc = 1

    tree_after = _snapshot_committed_tree()
    if tree_before != tree_after:
        changed = sorted(
            k for k in set(tree_before) | set(tree_after)
            if tree_before.get(k) != tree_after.get(k)
        )
        print(
            f"FAIL: committed tree under REPO_ROOT mutated during "
            f"the self-test (changed: {changed!r})",
            file=sys.stderr,
        )
        rc = 1

    if rc == 0:
        print(
            "OK (mock generated-image provenance): happy path + every "
            "fail-closed probe passed; nothing under REPO_ROOT mutated."
        )
    return rc


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mock generated-image provenance smoke. Drives the "
            "committed examples/synthetic_mock_image_trial bundle "
            "through run_mock_image_pipeline.py --bundle into a "
            "tempdir, derives a per-request provenance object linking "
            "spec ids to manifest path / sidecar metadata / workspace "
            "asset bytes (byte_count + sha256) / PPTX-media inventory, "
            "and asserts every documented invariant. MOCK / STUB only "
            "— NETWORK-FREE — stdlib-only. Self-test surface only "
            "today."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Required: run the happy path + every fail-closed probe. "
            "The script has no other CLI surface."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: mock_generated_image_provenance_smoke.py requires "
            "--self-test (no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
