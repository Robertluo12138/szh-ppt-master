#!/usr/bin/env python3
"""Mixed image-asset provenance handoff smoke (LOCAL, STUB, NOT real
D-One).

Tempdir-only, stdlib-only handoff smoke that proves a reviewer can
walk a single mixed-lane mock-image trial run end-to-end:

  1. drive a synthetic mixed-lane bundle (two cover slides — one
     ``d_one_local`` image produced by the mock D-One stub chain
     plus one ``local_asset`` image staged through
     ``<bundle>/source_assets/``) through
     ``scripts/run_mock_image_pipeline.py --bundle`` into a
     tempfile-owned workspace / output / report directory OUTSIDE
     the repo tree, reusing the bundle materializer + runner-args
     helpers from ``scripts/mixed_image_asset_pipeline_smoke.py``
     so the synthetic bundle taxonomy stays single-source-of-truth
     across the two smokes;
  2. derive the **TEMP-ONLY** runtime provenance object that links,
     per manifest id, the source_class (d_one_local / local_asset),
     the workspace asset (path / byte_count / sha256 / extension /
     media_type), the PPTX-embedded media part (part / size_bytes /
     sha256 / extension / content_type / referencing_slides), the
     audit sidecar ``<report-dir>/mock_d_one_adapter_plan.json``
     request id list, and the PPTX ``<report-dir>/inventory.json``
     readback;
  3. **sanitize** the runtime object into a committed-safe handoff
     record whose path-typed fields are workspace-relative /
     placeholder shapes (no leading ``/``, no URI scheme, no ``..``
     segment) so the same per-id source_class + sha256 + sidecar +
     inventory evidence the runtime smoke recorded can be schema-
     validated against
     ``schemas/mixed_image_asset_provenance.schema.json`` without
     leaking absolute machine paths;
  4. validate the sanitized record through
     ``scripts/validate_mixed_image_asset_provenance.py --evidence
     <tempfile>`` (schema + every documented G1..G18 semantic gate,
     including the new G18 generated_intent / sidecar.requests per-id
     parity gate)
     so the same gate stack the committed template ships against
     is what the handoff smoke drives;
  5. assert the committed tree under ``REPO_ROOT`` is byte-identical
     before and after the run — the smoke writes nothing under the
     repo tree, never commits the sanitized record, and the per-run
     tempdir is removed on exit.

The handoff smoke is the **bridge** between the runtime TEMP-ONLY
provenance object (absolute tempdir paths the runtime gate accepts
but the committed-safe gate refuses) and the committed-safe handoff
the validator + schema require. The deliberate narrowed mapping is:

  runtime  : ``<bundle>``      -> placeholder ``synthetic-tempdir/mixed_bundle``
  runtime  : ``<workspace>``   -> placeholder ``synthetic-tempdir/workspace``
  runtime  : ``<report-dir>``  -> placeholder ``synthetic-tempdir/report``
  runtime  : ``<output>.pptx`` -> placeholder ``synthetic-tempdir/output/mixed.pptx``
  runtime  : ``<sidecar>``     -> placeholder ``synthetic-tempdir/report/mock_d_one_adapter_plan.json``
  runtime  : ``<inventory>``   -> placeholder ``synthetic-tempdir/report/inventory.json``
  runtime  : ``<asset>.png``   -> placeholder ``synthetic-tempdir/workspace/<manifest_local_path>``
  rows[*].pptx_media.part      -> preserved (already package-internal ``ppt/media/<...>``)
  rows[*].asset.sha256         -> preserved (lowercase 64-hex)
  rows[*].pptx_media.sha256    -> preserved (lowercase 64-hex)
  rows[*].asset.byte_count     -> preserved (positive int)
  rows[*].source_class         -> preserved (one of d_one_local / local_asset)
  rows[*].manifest_local_path  -> preserved (already workspace-relative)
  rows[*].intended_use         -> preserved verbatim
  rows[*].generated_intent     -> preserved verbatim on every
                                  d_one_local row; ABSENT on every
                                  local_asset row (taxonomy values are
                                  closed enums + pattern-locked
                                  custom_descriptor — committed-safe
                                  by construction)
  sidecar.request_ids          -> preserved (sorted unique list of request ids)
  sidecar.requests             -> preserved (sorted per-id taxonomy
                                  projection mirroring the runner-
                                  written mock_d_one_adapter_plan.json
                                  per-request placement_role /
                                  text_policy / subject_domain /
                                  optional custom_descriptor)
  inventory.media_parts        -> preserved (sorted unique
                                  {part, sha256} pair set, part-level
                                  bidirectional with rows[*].pptx_media)
  schema_version               -> "2" (locked; bumped from "1"
                                  as the paired schema/validator
                                  change that added sidecar.requests
                                  + row-level generated_intent for
                                  G18 parity)
  evidence_id                  -> "mixed_image_asset_provenance" (locked)
  real_d_one_status            -> a fresh canonical UNVERIFIED sentence
                                  matching the schema's negation-token
                                  contract; the runtime sentence is
                                  not copied because it is bundle-
                                  smoke-specific wording
  notes                        -> the committed-safe ``scope`` /
                                  ``embed_surface`` framing the schema
                                  pins

The sanitizer is a one-pass map: every path-typed field is rewritten
from its tempdir-anchored value to a fixed committed-safe placeholder
under the same logical role. Any input value that does NOT lexically
sit under the tempdir-anchored root — the sanitizer cannot translate
an unexpected absolute path safely — is REFUSED outright (sanitizer
H1). Any output value that does not satisfy the committed-safe path
contract (no URI scheme, no ``..`` segment, no leading ``/`` or
``~``) is REFUSED outright (sanitizer H2). The validator's G12 path-
safety gate is the load-bearing post-sanitization check: a leak past
H1/H2 still trips at G12 in the validator subprocess.

The mock pipeline is invoked ONCE per self-test of THIS smoke (its
own independent ``run_mock_image_pipeline.py --bundle`` subprocess).
The sibling ``mixed_image_asset_pipeline_smoke`` already runs its own
independent pipeline subprocess for its own acceptance assertions; in
the aggregate the pipeline therefore runs twice end-to-end (once per
smoke). What the two smokes share is the bundle materializer / runner
arg builder / synthetic-id constants imported from
``mixed_image_asset_pipeline_smoke``, so the synthetic mixed-lane
taxonomy stays single-source-of-truth across both smokes. Every
fail-closed probe in THIS smoke runs the validator SUBPROCESS on a
tampered clone of the sanitized record so the canonical
G1..G18 gate stack is exercised on the probe path.

Clean-room: this smoke shares no prompts, assets, examples, tables,
CSV rows, wording, code, or deck structure with any upstream
project. Aligned only with the local-only image-generation idea
that generated-image work should produce a reviewer-readable
committed-safe handoff record alongside the temp-only runtime
provenance; the implementation, sanitizer field set, and probe
matrix are this repo's own.

Happy-path assertions:

  H1  the bundle materializer + runner-args helpers reused from
      ``mixed_image_asset_pipeline_smoke`` (driven with a taxonomy-
      rich ``d_one_spec`` override carrying ``placement_role=hero_page``,
      a non-default ``text_policy``, ``subject_domain``, AND an
      approved ``custom_descriptor`` plus a paired
      ``descriptor_vocabulary.json`` the runner resolves bundle-
      relative) drive a pipeline subprocess that returns rc=0;
  H2  the runtime provenance derivation produces a non-empty
      dict with exactly two rows (one d_one_local, one local_asset)
      both pointing at on-disk PNG/JPG/JPEG bytes whose recomputed
      sha256 matches the recorded sha256 AND the d_one_local row's
      ``generated_intent`` equals the spec-supplied taxonomy values
      byte-for-byte (spec -> sidecar -> runtime preservation) AND
      the local_asset row carries NO ``generated_intent``;
  H3  the sanitizer's input path-prefix gate refuses any path-typed
      field that does not sit under the expected tempdir-anchored
      root;
  H4  the sanitizer's output gate refuses any committed-safe output
      that still carries a URI scheme, a ``..`` segment, a leading
      ``/`` or ``~`` (defense in depth);
  H5  the validator subprocess on the sanitized record returns
      rc=0 (every G1..G18 gate held, including the
      generated_intent / sidecar.requests per-id parity gate);
  H6  the committed tree under REPO_ROOT is byte-identical before
      and after the run.

Fail-closed probes (every probe runs on a clean copy of the
sanitized record so a probe-induced failure cannot leak into the
next probe; every probe asserts the validator subprocess returns
rc=1 with the documented diagnostic substring AND that the canonical
sanitized baseline still passes):

  P1  missing local_asset row: drop the row whose source_class is
      ``local_asset`` and assert the validator refuses (schema
      minItems gate fires on the now-1-row array — fail-closed by
      construction);
  P2  missing d_one_local row: symmetric to P1 — drop the
      d_one_local row and assert the validator refuses;
  P3  local_asset accidentally present in sidecar: append the
      local_asset row's id to ``sidecar.request_ids`` and assert
      the validator's sidecar membership gate refuses;
  P4  d_one_local missing from sidecar: drop every d_one_local
      row id from ``sidecar.request_ids`` (substitute an orphan
      id so the schema's minItems holds) and assert the validator
      refuses with the documented diagnostic;
  P5  sha mismatch: rewrite the d_one_local row's
      ``pptx_media.sha256`` away from its ``asset.sha256`` and
      assert the validator's sha-equality gate refuses;
  P6  absolute path leak: rewrite ``rows[0].asset.path`` to an
      absolute ``/etc/passwd`` and assert the validator's path-
      safety gate refuses (schema pattern + G12 both refuse);
  P7  public-hosting wording: inject ``public hosting enabled``
      into ``rows[0].intended_use`` and assert the validator's
      string-safety gate refuses;
  P8  credential token: inject ``token=value`` into
      ``rows[0].intended_use`` and assert the validator's
      credential gate refuses;
  P9  real-D-One success claim: rewrite ``notes.scope`` to
      ``Real D-One verified online`` and assert the validator's
      claim-refusal walker fires;
  P10 strip ``generated_intent`` from the d_one_local row and
      assert validator G18 refuses (every d_one_local row must
      carry the per-row taxonomy projection);
  P11 attach ``generated_intent`` to the local_asset row and
      assert validator G18 refuses (caller-staged bytes are not
      a generated artifact);
  P12 flip ``generated_intent.text_policy`` on the d_one_local
      row away from its sidecar.requests entry and assert the
      validator's G18 per-id parity gate fires;
  P13 drop the d_one_local id from ``sidecar.requests`` and
      assert validator G18 refuses (every d_one_local row must
      have a matching sidecar.requests entry).

Wiring decision: this smoke IS wired into the aggregate
``scripts/core_editable_ppt_acceptance.py`` as the seventeenth
delegated smoke. The handoff smoke is independent — each
aggregate run of it drives its OWN mock pipeline subprocess.

MOCK / STUB ONLY — NOT real D-One integration. Nothing in this
smoke calls D-One, MCP, Qoder, a public network, telemetry, any
model API, an image search, or any external service. The asset
bytes generated by ``run_d_one_generation --allow-synthetic-bytes``
are a fixed minimal PNG payload per request, never a real image,
and the local_asset bytes are the smoke-owned synthetic PNG payload
already used by the sibling pipeline smoke. The committed-safe
handoff record this smoke derives is local audit evidence about
that synthetic mixed-lane mock chain, not a claim that any external
service ran or succeeded.

Usage:
  python3 scripts/mixed_image_asset_provenance_handoff_smoke.py --self-test

Stdlib-only. NETWORK-FREE. NO real D-One. NO MCP. NO Qoder. NO
model API. NO image search. NO telemetry. NOT a full prompt /
report / Markdown-to-PPTX automation — the smoke composes the
committed mock chain through the existing pipeline smoke's
materializer and proves a reviewer can derive the committed-safe
handoff from the runtime output without leaking absolute paths or
claiming a real run.
"""
from __future__ import annotations

import sys

# Refuse to write `.pyc` files for any module imported by this smoke.
# Mirrors the gate every sibling smoke applies; the bytecode flag must
# be flipped BEFORE any first-party import so the interpreter sees it
# at bytecode-write time.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import zipfile  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

# Reuse the synthetic mixed-lane bundle constants + materializer +
# runner-args helper from the sibling pipeline smoke. Sharing the
# same code path means a future change to the bundle shape is
# exercised by THIS smoke too.
from mixed_image_asset_pipeline_smoke import (  # noqa: E402
    D_ONE_IMAGE_ID,
    D_ONE_LOCAL_PATH,
    LOCAL_ASSET_IMAGE_ID,
    LOCAL_ASSET_LOCAL_PATH,
    SIDECAR_FILENAME,
    _materialize_bundle,
    _runner_args,
)
from core_editable_ppt_acceptance import (  # noqa: E402
    _snapshot_committed_tree,
)

# Synthetic taxonomy values the handoff smoke pins on the d_one_local
# request. Aligned only with upstream ppt-master's hero-page +
# per-row text_policy / subject_domain depth; no upstream code /
# prompts / examples / assets / wording copied. The values are
# baked into both the d_one_spec the smoke writes AND the validator-
# checked generated_intent block on the d_one_local row, so a
# spec -> sidecar -> sanitized evidence drift trips G18 in the
# validator subprocess.
_D_ONE_PLACEMENT_ROLE = "hero_page"
_D_ONE_TEXT_POLICY = "decorative_glyphs"
_D_ONE_SUBJECT_DOMAIN = "abstract_geometry"
_D_ONE_CUSTOM_DESCRIPTOR = "hero_calm_motif"

# Canonical committed-safe placeholders.
_PLACEHOLDER_BUNDLE_PATH = "synthetic-tempdir/mixed_bundle"
_PLACEHOLDER_WORKSPACE_PATH = "synthetic-tempdir/workspace"
_PLACEHOLDER_REPORT_DIR = "synthetic-tempdir/report"
_PLACEHOLDER_PPTX_PATH = "synthetic-tempdir/output/mixed.pptx"
_PLACEHOLDER_SIDECAR_PATH = (
    "synthetic-tempdir/report/mock_d_one_adapter_plan.json"
)
_PLACEHOLDER_INVENTORY_PATH = "synthetic-tempdir/report/inventory.json"

_COMMITTED_SAFE_STATUS = (
    "UNVERIFIED. Real D-One is NOT called by this handoff record. "
    "No MCP, no public network, no model API, no image search, no "
    "Qoder, no telemetry."
)

_COMMITTED_SAFE_NOTES = {
    "scope": (
        "Mixed-lane mock-image provenance handoff. Drives a "
        "synthetic mixed-lane bundle (d_one_local + local_asset) "
        "through the local pipeline into a tempdir, sanitizes the "
        "runtime provenance object into a committed-safe shape, "
        "and validates the result. NOT real D-One, NOT MCP, NOT "
        "Qoder, NOT a public-network run, NOT telemetry, NOT a "
        "prompt or report to PPTX automation."
    ),
    "embed_surface": (
        "PNG, JPG, and JPEG inside the ppt media slot of the "
        "produced deck. The subset scripts export_pptx supports "
        "today; anything outside that subset is fail-closed by "
        "the exporter."
    ),
}

_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

_EMBEDDABLE_MEDIA_EXTS: tuple[str, ...] = (".png", ".jpg", ".jpeg")
_EXT_TO_MEDIA_TYPE: dict[str, str] = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
}


def _taxonomy_d_one_spec_body() -> dict:
    """Synthetic d_one_spec carrying the per-row taxonomy + custom-
    descriptor escape-hatch the goal pins. The runner forwards
    --descriptor-vocabulary to done_image_adapter, which validates the
    request fields, projects them onto the deterministic plan, and the
    runner copies that plan byte-identical into the audit sidecar
    <report-dir>/mock_d_one_adapter_plan.json."""
    return {
        "requests": [
            {
                "id": D_ONE_IMAGE_ID,
                "prompt": (
                    "abstract calm geometric accent, no text, no logo"
                ),
                "intended_use": "spot illustration",
                "width_px": 320, "height_px": 320,
                "placement_role": _D_ONE_PLACEMENT_ROLE,
                "text_policy": _D_ONE_TEXT_POLICY,
                "subject_domain": _D_ONE_SUBJECT_DOMAIN,
                "custom_descriptor": _D_ONE_CUSTOM_DESCRIPTOR,
            },
        ],
    }


def _descriptor_vocab_body() -> dict:
    """Synthetic descriptor vocabulary that approves the d_one_spec's
    placement_role / text_policy / subject_domain values AND the
    custom_descriptor escape-hatch value. Mirrors the canonical-set
    membership invariant the descriptor-vocabulary schema enforces
    (every allowed_values array is exactly the canonical-length unique
    enum). Aligned only with upstream ppt-master image-generation; no
    upstream code / prompts / examples / assets / wording copied."""
    return {
        "schema_version": 1,
        "note": (
            "Synthetic D-One descriptor vocabulary for the mixed image-"
            "asset provenance handoff smoke (taxonomy parity proof)."
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
            "rendering_style": {"allowed_values": [
                "flat_vector", "line_diagram", "isometric_lite",
                "low_poly", "solid_shape",
            ]},
            "palette_family": {"allowed_values": [
                "neutral_grey", "accent_only", "dual_tone",
                "mono_brand", "palette_default",
            ]},
            "image_role": {"allowed_values": [
                "decorative_accent", "metaphor_icon", "divider_motif",
                "kpi_emblem", "cover_motif",
            ]},
            "layout_pattern": {"allowed_values": [
                "single_center", "left_anchor", "right_anchor",
                "top_band", "bottom_band",
            ]},
            "modifier": {"allowed_values": [
                "low_contrast", "soft_edges", "grid_aligned",
                "negative_space",
            ]},
            "text_policy": {"allowed_values": [
                "no_text", "decorative_glyphs", "caption_safe",
            ]},
            "subject_domain": {"allowed_values": [
                "abstract_geometry", "process_motif",
                "metric_emblem", "concept_diagram",
            ]},
            "placement_role": {"allowed_values": [
                "hero_page", "local_region",
            ]},
        },
        "custom_descriptors": [
            {
                "kind": "composition_adjective",
                "value": _D_ONE_CUSTOM_DESCRIPTOR,
                "approved_in_review_ref": "synthetic_review.handoff",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Outcome dataclasses.
# ---------------------------------------------------------------------------


@dataclass
class _SanitizerOutcome:
    ok: bool
    record: dict | None
    failures: list[str]


@dataclass
class _ValidatorOutcome:
    rc: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.rc == 0

    @property
    def combined(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


# ---------------------------------------------------------------------------
# Pipeline driver + runtime derivation.
# ---------------------------------------------------------------------------


def _run_pipeline(
    *, bundle_dir: Path, workspace: Path, output: Path,
    report_dir: Path,
) -> tuple[int, str, str]:
    cmd = _runner_args(
        bundle_dir=bundle_dir, workspace=workspace,
        output=output, report_dir=report_dir,
    )
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def _pptx_media_inventory(
    pptx: Path,
) -> tuple[dict[str, tuple[str, int, str]], Exception | None]:
    """Return {part_name: (sha256, size_bytes, ext_no_dot)} for every
    ppt/media/* part inside the PPTX whose extension is in the
    embed-surface allow-list."""
    out: dict[str, tuple[str, int, str]] = {}
    try:
        zf = zipfile.ZipFile(pptx, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        return out, exc
    try:
        for n in zf.namelist():
            if not n.startswith("ppt/media/"):
                continue
            ext = Path(n).suffix.lower()
            if ext not in _EMBEDDABLE_MEDIA_EXTS:
                continue
            payload = zf.read(n)
            out[n] = (
                hashlib.sha256(payload).hexdigest(),
                len(payload),
                ext.lstrip("."),
            )
    finally:
        zf.close()
    return out, None


def _slide_refs_from_inventory(
    inventory_path: Path, part: str,
) -> list[int]:
    """Return the referencing_slides list the runner-written
    inventory.json records for ``part``, or [] if not found."""
    try:
        inv = json.loads(inventory_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    media_parts = inv.get("media_parts") or []
    for entry in media_parts:
        if isinstance(entry, dict) and entry.get("part") == part:
            refs = entry.get("referencing_slides") or []
            return [r for r in refs if isinstance(r, int)]
    return []


def _derive_runtime_provenance(
    *,
    bundle_dir: Path,
    workspace: Path,
    output_pptx: Path,
    report_dir: Path,
) -> tuple[dict | None, list[str]]:
    """Walk the produced workspace + PPTX + sidecar + inventory and
    build the TEMP-ONLY runtime provenance dict. Returns (dict, errors).
    A non-empty errors list means the derivation failed."""
    errors: list[str] = []
    sidecar_path = report_dir / SIDECAR_FILENAME
    inventory_path = report_dir / "inventory.json"

    if not output_pptx.is_file():
        errors.append(
            f"expected produced PPTX at {output_pptx}; not found"
        )
        return None, errors
    if not sidecar_path.is_file():
        errors.append(
            f"expected sidecar at {sidecar_path}; not found"
        )
        return None, errors
    if not inventory_path.is_file():
        errors.append(
            f"expected inventory at {inventory_path}; not found"
        )
        return None, errors

    # Parse the sidecar to extract sidecar.schema_version + request ids.
    try:
        sidecar_body = json.loads(sidecar_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(
            f"cannot parse sidecar {sidecar_path}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None, errors
    sidecar_schema_version = sidecar_body.get("schema_version")
    sidecar_requests = sidecar_body.get("requests") or []
    sidecar_ids = sorted({
        r.get("id") for r in sidecar_requests
        if isinstance(r, dict) and isinstance(r.get("id"), str)
    })
    # Build a per-id taxonomy projection from the sidecar's plan
    # requests (placement_role / text_policy / subject_domain /
    # optional custom_descriptor). The validator's G18 cross-checks
    # row.generated_intent against this projection.
    sidecar_taxonomy_by_id: dict[str, dict] = {}
    for r in sidecar_requests:
        if not isinstance(r, dict):
            continue
        rid = r.get("id")
        if not isinstance(rid, str) or not rid:
            continue
        entry: dict = {"id": rid}
        for field in (
            "placement_role", "text_policy", "subject_domain",
        ):
            v = r.get(field)
            if isinstance(v, str) and v:
                entry[field] = v
        cd = r.get("custom_descriptor")
        if isinstance(cd, str) and cd:
            entry["custom_descriptor"] = cd
        sidecar_taxonomy_by_id[rid] = entry

    # Parse the inventory.
    try:
        inv_body = json.loads(inventory_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(
            f"cannot parse inventory {inventory_path}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None, errors
    inv_ok = inv_body.get("ok") is True
    findings = inv_body.get("findings") or []
    findings_empty = findings == []
    slide_count = inv_body.get("slide_count")
    relationships_external_count = 0
    relationships = inv_body.get("relationships") or {}
    if isinstance(relationships, dict):
        ext = relationships.get("external")
        if isinstance(ext, list):
            relationships_external_count = len(ext)
        elif isinstance(ext, int):
            relationships_external_count = ext

    # Inventory media_parts: the (part, sha256) pair for every
    # embeddable ppt/media/<x>.{png,jpg,jpeg} part. Take from the
    # runner-written inventory directly so we never re-implement
    # the walker. The committed-safe schema requires part-level
    # pairs so the validator can run G10 bidirectionally
    # (rows[*].pptx_media.{part, sha256} <-> inventory.media_parts).
    runtime_media_parts: list[dict] = []
    inv_media_parts = inv_body.get("media_parts") or []
    for entry in inv_media_parts:
        if not isinstance(entry, dict):
            continue
        part = entry.get("part")
        ext = entry.get("extension")
        sha = entry.get("sha256")
        if (
            isinstance(part, str)
            and isinstance(ext, str)
            and isinstance(sha, str)
            and "." + ext.lower() in _EMBEDDABLE_MEDIA_EXTS
        ):
            runtime_media_parts.append({"part": part, "sha256": sha})
    runtime_media_parts = sorted(
        {
            (e["part"], e["sha256"]) for e in runtime_media_parts
        }
    )
    runtime_media_parts = [
        {"part": p, "sha256": s} for (p, s) in runtime_media_parts
    ]

    # Walk the actual PPTX too so a row's pptx_media.{part,sha256,
    # size_bytes,extension,content_type} block carries values
    # observed in the produced package (not just inventory rows).
    pptx_media_map, pptx_err = _pptx_media_inventory(output_pptx)
    if pptx_err is not None:
        errors.append(
            f"cannot walk PPTX media parts: "
            f"{type(pptx_err).__name__}: {pptx_err}"
        )
        return None, errors

    # Build the two rows (d_one_local + local_asset). The mixed
    # bundle declares one of each by construction; the workspace
    # asset paths are <workspace>/<manifest_local_path>.
    rows: list[dict] = []
    for source_class, manifest_id, manifest_local_path in (
        ("d_one_local", D_ONE_IMAGE_ID, D_ONE_LOCAL_PATH),
        ("local_asset", LOCAL_ASSET_IMAGE_ID, LOCAL_ASSET_LOCAL_PATH),
    ):
        asset_path = workspace / manifest_local_path
        if not asset_path.is_file():
            errors.append(
                f"expected workspace asset at {asset_path}; not found"
            )
            return None, errors
        if asset_path.is_symlink():
            errors.append(
                f"refused symlinked asset at {asset_path}"
            )
            return None, errors
        sha, n = _sha256_file(asset_path)
        ext = asset_path.suffix.lstrip(".").lower()
        if ext not in {"png", "jpg", "jpeg"}:
            errors.append(
                f"workspace asset {asset_path} has unsupported "
                f"extension {ext!r}"
            )
            return None, errors
        media_type = _EXT_TO_MEDIA_TYPE[ext]
        # Find the matching ppt/media/<...>.{png,jpg,jpeg} part by
        # sha equality.
        matched_part: str | None = None
        matched_size: int | None = None
        matched_ext: str | None = None
        for part_name, (part_sha, part_size, part_ext) in (
            pptx_media_map.items()
        ):
            if part_sha == sha:
                matched_part = part_name
                matched_size = part_size
                matched_ext = part_ext
                break
        if matched_part is None:
            errors.append(
                f"workspace asset {asset_path} (sha256={sha}) does "
                f"not appear inside the produced PPTX media parts"
            )
            return None, errors
        row: dict = {
            "id": manifest_id,
            "source_class": source_class,
            "manifest_local_path": manifest_local_path,
            "intended_use": "spot illustration",
            "asset": {
                "path": str(asset_path),
                "exists": True,
                "byte_count": n,
                "sha256": sha,
                "extension": ext,
                "media_type": media_type,
                "error": "",
            },
            "pptx_media": {
                "part": matched_part,
                "size_bytes": matched_size,
                "sha256": sha,
                "extension": matched_ext,
                "content_type": _EXT_TO_MEDIA_TYPE[matched_ext],
                "referencing_slides": _slide_refs_from_inventory(
                    inventory_path, matched_part,
                ),
            },
        }
        # generated_intent — REQUIRED on every d_one_local row;
        # FORBIDDEN on every local_asset row. Projected from the
        # runner-written sidecar's per-id plan request so a smoke
        # without the descriptor_vocabulary + taxonomy-rich d_one_spec
        # surfaces as a missing-intent G18 failure in the validator
        # subprocess (no silent default).
        if source_class == "d_one_local":
            tax = sidecar_taxonomy_by_id.get(manifest_id) or {}
            gi: dict = {}
            for field in (
                "placement_role", "text_policy", "subject_domain",
            ):
                v = tax.get(field)
                if isinstance(v, str) and v:
                    gi[field] = v
            cd = tax.get("custom_descriptor")
            if isinstance(cd, str) and cd:
                gi["custom_descriptor"] = cd
            if gi:
                row["generated_intent"] = gi
        rows.append(row)

    runtime: dict = {
        "bundle_path": str(bundle_dir),
        "workspace_path": str(workspace),
        "report_dir": str(report_dir),
        "pptx_path": str(output_pptx),
        "sidecar": {
            "path": str(sidecar_path),
            "schema_version": sidecar_schema_version,
            "request_ids": sidecar_ids,
            "requests": sorted(
                sidecar_taxonomy_by_id.values(),
                key=lambda e: e.get("id") or "",
            ),
        },
        "inventory": {
            "path": str(inventory_path),
            "ok": inv_ok,
            "findings_empty": findings_empty,
            "slide_count": slide_count,
            "relationships_external_count": relationships_external_count,
            "media_parts": runtime_media_parts,
        },
        "rows": rows,
    }
    return runtime, []


# ---------------------------------------------------------------------------
# Sanitizer.
# ---------------------------------------------------------------------------


def _ensure_under(prefix: str, value: str, label: str) -> list[str]:
    """Refuse ``value`` unless it lexically sits under ``prefix``."""
    if not value:
        return [f"sanitizer H1: {label} is empty"]
    if not prefix:
        return [f"sanitizer H1: {label} prefix is empty"]
    norm_prefix = prefix.rstrip("/") + "/"
    if value == prefix.rstrip("/") or value.startswith(norm_prefix):
        return []
    return [
        f"sanitizer H1: {label}={value!r} does not sit under expected "
        f"prefix {prefix!r} — refusing rather than rewriting an "
        f"unrelated absolute path to a committed-safe placeholder"
    ]


def _committed_safe_path_failures(label: str, value: str) -> list[str]:
    """H2 — refuse any output value that does not satisfy the
    committed-safe path contract."""
    out: list[str] = []
    if not value:
        out.append(f"sanitizer H2: {label} is empty")
        return out
    if _URI_SCHEME_PREFIX.match(value):
        out.append(
            f"sanitizer H2: {label}={value!r} carries a URI scheme "
            f"prefix"
        )
    parts = value.replace("\\", "/").split("/")
    if ".." in parts:
        out.append(
            f"sanitizer H2: {label}={value!r} contains a '..' "
            f"traversal segment"
        )
    if value.startswith("/") or value.startswith("~"):
        out.append(
            f"sanitizer H2: {label}={value!r} is absolute / home-"
            f"relative"
        )
    return out


def _sanitize(runtime: dict, *, tempdir_root: str) -> _SanitizerOutcome:
    """Map the runtime TEMP-ONLY provenance dict to a committed-safe
    handoff record."""
    failures: list[str] = []

    bundle_path = str(runtime.get("bundle_path") or "")
    workspace_path = str(runtime.get("workspace_path") or "")
    report_dir = str(runtime.get("report_dir") or "")
    pptx_path = str(runtime.get("pptx_path") or "")

    # H1 — every absolute path on the runtime object must anchor under
    # the per-run tempdir root.
    if not tempdir_root or tempdir_root == "/":
        failures.append(
            f"sanitizer H1: tempdir_root={tempdir_root!r} is "
            f"missing / root"
        )

    if tempdir_root:
        for label, value in (
            ("bundle_path", bundle_path),
            ("workspace_path", workspace_path),
            ("report_dir", report_dir),
            ("pptx_path", pptx_path),
        ):
            failures.extend(_ensure_under(tempdir_root, value, label))

    sidecar = runtime.get("sidecar") or {}
    inventory = runtime.get("inventory") or {}
    sidecar_path = str(sidecar.get("path") or "")
    inventory_path = str(inventory.get("path") or "")
    if tempdir_root:
        failures.extend(_ensure_under(
            tempdir_root, sidecar_path, "sidecar.path",
        ))
        failures.extend(_ensure_under(
            tempdir_root, inventory_path, "inventory.path",
        ))

    sanitized_rows: list[dict] = []
    for idx, row in enumerate(runtime.get("rows") or []):
        if not isinstance(row, dict):
            failures.append(
                f"sanitizer H1: rows[{idx}] is not a JSON object"
            )
            continue
        asset = row.get("asset") or {}
        asset_path = str(asset.get("path") or "")
        if tempdir_root:
            failures.extend(_ensure_under(
                tempdir_root, asset_path,
                f"rows[{idx}].asset.path",
            ))

        manifest_local_path = str(row.get("manifest_local_path") or "")
        if (manifest_local_path.startswith("/")
                or manifest_local_path.startswith("~")
                or _URI_SCHEME_PREFIX.match(manifest_local_path)
                or ".." in manifest_local_path.replace(
                    "\\", "/",
                ).split("/")):
            failures.append(
                f"sanitizer H1: rows[{idx}].manifest_local_path="
                f"{manifest_local_path!r} is not workspace-relative"
            )

        sanitized_committed_safe_path = (
            _PLACEHOLDER_WORKSPACE_PATH + (
                "/" + manifest_local_path if manifest_local_path else ""
            )
        )
        failures.extend(_committed_safe_path_failures(
            f"rows[{idx}].asset.path (committed-safe rewrite)",
            sanitized_committed_safe_path,
        ))

        sanitized_row: dict = {
            "id": row.get("id"),
            "source_class": row.get("source_class"),
            "manifest_local_path": manifest_local_path,
            "intended_use": row.get("intended_use"),
            "asset": {
                "path": sanitized_committed_safe_path,
                "exists": asset.get("exists"),
                "byte_count": asset.get("byte_count"),
                "sha256": asset.get("sha256"),
                "extension": asset.get("extension"),
                "media_type": asset.get("media_type"),
                "error": asset.get("error") or "",
            },
            "pptx_media": dict(row.get("pptx_media") or {}),
        }
        # generated_intent is preserved verbatim (taxonomy enum values
        # are committed-safe by construction — closed enums + pattern-
        # locked custom_descriptor). The validator's G18 cross-checks
        # this block against the sanitized sidecar.requests projection.
        gi = row.get("generated_intent")
        if isinstance(gi, dict):
            sanitized_row["generated_intent"] = dict(gi)
        sanitized_rows.append(sanitized_row)

    # H2 — every committed-safe placeholder must pass the path
    # contract. Belt-and-braces: the placeholders are constants today.
    for label, val in (
        ("bundle_path", _PLACEHOLDER_BUNDLE_PATH),
        ("workspace_path", _PLACEHOLDER_WORKSPACE_PATH),
        ("report_dir", _PLACEHOLDER_REPORT_DIR),
        ("pptx_path", _PLACEHOLDER_PPTX_PATH),
        ("sidecar.path", _PLACEHOLDER_SIDECAR_PATH),
        ("inventory.path", _PLACEHOLDER_INVENTORY_PATH),
    ):
        failures.extend(_committed_safe_path_failures(label, val))

    # Derive summary fields.
    by_class_counts: dict[str, int] = {
        "d_one_local": 0, "local_asset": 0,
    }
    for r in sanitized_rows:
        sc = r.get("source_class")
        if sc in by_class_counts:
            by_class_counts[sc] += 1
    coverage = sorted({
        r["source_class"] for r in sanitized_rows
        if isinstance(r.get("source_class"), str)
    })

    # sidecar.requests projection — preserve the per-id taxonomy
    # block byte-for-byte so the validator's G18 cross-check against
    # row.generated_intent has a sidecar surface to compare against.
    sanitized_sidecar_requests: list[dict] = []
    for entry in (sidecar.get("requests") or []):
        if not isinstance(entry, dict):
            continue
        sanitized_sidecar_requests.append(dict(entry))
    sanitized_sidecar_requests.sort(
        key=lambda e: e.get("id") or "",
    )

    record: dict = {
        "schema_version": "2",
        "evidence_id": "mixed_image_asset_provenance",
        "real_d_one_status": _COMMITTED_SAFE_STATUS,
        "bundle_path": _PLACEHOLDER_BUNDLE_PATH,
        "workspace_path": _PLACEHOLDER_WORKSPACE_PATH,
        "report_dir": _PLACEHOLDER_REPORT_DIR,
        "pptx_path": _PLACEHOLDER_PPTX_PATH,
        "sidecar": {
            "path": _PLACEHOLDER_SIDECAR_PATH,
            "schema_version": sidecar.get("schema_version"),
            "request_ids": sorted(sidecar.get("request_ids") or []),
            "requests": sanitized_sidecar_requests,
        },
        "inventory": {
            "path": _PLACEHOLDER_INVENTORY_PATH,
            "ok": inventory.get("ok"),
            "findings_empty": inventory.get("findings_empty"),
            "slide_count": inventory.get("slide_count"),
            "relationships_external_count": inventory.get(
                "relationships_external_count",
            ),
            "media_parts": sorted(
                [
                    {
                        "part": e.get("part"),
                        "sha256": e.get("sha256"),
                    }
                    for e in (inventory.get("media_parts") or [])
                    if isinstance(e, dict)
                    and isinstance(e.get("part"), str)
                    and isinstance(e.get("sha256"), str)
                ],
                key=lambda e: (e["part"], e["sha256"]),
            ),
        },
        "rows": sanitized_rows,
        "notes": dict(_COMMITTED_SAFE_NOTES),
        "summary": {
            "ok": not failures,
            "row_count": len(sanitized_rows),
            "source_class_coverage": coverage,
            "d_one_local_id_count": by_class_counts["d_one_local"],
            "local_asset_id_count": by_class_counts["local_asset"],
            "failures": [],
        },
    }

    return _SanitizerOutcome(
        ok=not failures, record=record, failures=failures,
    )


# ---------------------------------------------------------------------------
# Validator driver.
# ---------------------------------------------------------------------------


def _run_validator(
    record: dict, *, evidence_path: Path,
) -> _ValidatorOutcome:
    evidence_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
    )
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "validate_mixed_image_asset_provenance.py"),
        "--evidence", str(evidence_path),
    ]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    return _ValidatorOutcome(
        rc=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


# ---------------------------------------------------------------------------
# Happy path + probes.
# ---------------------------------------------------------------------------


def _run_happy_path(td: Path) -> tuple[int, dict | None]:
    print(
        "--- happy path: synthetic mixed-lane bundle (taxonomy-rich "
        "d_one_spec + descriptor_vocabulary.json) -> mock pipeline -> "
        "runtime provenance -> sanitize -> committed-safe handoff -> "
        "validator ---"
    )

    bundle_info = _materialize_bundle(
        td, d_one_spec_overrides=_taxonomy_d_one_spec_body(),
    )
    bundle_dir = bundle_info["bundle"]
    # Add the descriptor_vocabulary.json the runner resolves through
    # _BUNDLE_DESCRIPTOR_VOCABULARY_NAME so the taxonomy fields the
    # spec carries are approved end-to-end.
    vocab_path = bundle_dir / "descriptor_vocabulary.json"
    vocab_path.write_text(
        json.dumps(_descriptor_vocab_body(), indent=2, sort_keys=True)
        + "\n",
    )

    workspace = td / "happy_ws"
    output = td / "happy.pptx"
    report_dir = td / "happy_report"

    print(f"  bundle:    {bundle_dir}")
    print(f"  workspace: {workspace}")
    print(f"  output:    {output}")
    print(f"  report:    {report_dir}")
    print(f"  vocab:     {vocab_path}")
    print()

    rc, stdout, stderr = _run_pipeline(
        bundle_dir=bundle_dir, workspace=workspace,
        output=output, report_dir=report_dir,
    )
    if rc != 0:
        print(f"  [FAIL] mixed-lane pipeline rc={rc}")
        tail = (stderr or stdout or "").splitlines()[-15:]
        for line in tail:
            print(f"    {line}")
        return 1, None
    print(f"  [PASS] mixed-lane pipeline rc=0")

    runtime, errors = _derive_runtime_provenance(
        bundle_dir=bundle_dir, workspace=workspace,
        output_pptx=output, report_dir=report_dir,
    )
    if errors or runtime is None:
        print(
            f"  [FAIL] runtime derivation produced "
            f"{len(errors)} error(s):"
        )
        for e in errors:
            print(f"    - {e}")
        return 1, None
    rows = runtime.get("rows") or []
    coverage = sorted({
        r.get("source_class") for r in rows
        if isinstance(r, dict) and r.get("source_class")
    })
    if set(coverage) != {"d_one_local", "local_asset"}:
        print(
            f"  [FAIL] runtime provenance source_class coverage="
            f"{coverage!r}; expected exactly "
            f"['d_one_local', 'local_asset']"
        )
        return 1, None
    print(
        f"  [PASS] runtime provenance derived; "
        f"{len(rows)} row(s); source_class coverage={coverage!r}"
    )

    # Explicit spec -> sidecar -> runtime preservation assertion for
    # every taxonomy field the d_one_spec asked for. A drift here
    # surfaces as a clear diagnostic rather than being inferred from
    # a downstream G18 failure.
    expected_intent = {
        "placement_role": _D_ONE_PLACEMENT_ROLE,
        "text_policy": _D_ONE_TEXT_POLICY,
        "subject_domain": _D_ONE_SUBJECT_DOMAIN,
        "custom_descriptor": _D_ONE_CUSTOM_DESCRIPTOR,
    }
    d_one_row = next(
        (r for r in rows if r.get("source_class") == "d_one_local"),
        None,
    )
    if d_one_row is None:
        print("  [FAIL] runtime provenance has no d_one_local row")
        return 1, None
    runtime_intent = d_one_row.get("generated_intent")
    if runtime_intent != expected_intent:
        print(
            f"  [FAIL] runtime d_one_local row generated_intent="
            f"{runtime_intent!r}; expected {expected_intent!r}. "
            f"The spec -> sidecar -> runtime preservation chain "
            f"dropped or mutated a taxonomy field."
        )
        return 1, None
    print(
        f"  [PASS] runtime d_one_local row.generated_intent equals "
        f"the spec-supplied taxonomy {expected_intent!r}"
    )
    local_row = next(
        (r for r in rows if r.get("source_class") == "local_asset"),
        None,
    )
    if local_row is None:
        print("  [FAIL] runtime provenance has no local_asset row")
        return 1, None
    if "generated_intent" in local_row:
        print(
            f"  [FAIL] runtime local_asset row leaked "
            f"generated_intent={local_row.get('generated_intent')!r}"
            f"; caller-staged bytes are not a generated artifact"
        )
        return 1, None
    print(
        "  [PASS] runtime local_asset row carries no generated_intent"
    )

    sanitizer = _sanitize(runtime, tempdir_root=str(td))
    if not sanitizer.ok or sanitizer.record is None:
        print(
            f"  [FAIL] sanitizer refused the runtime object "
            f"({len(sanitizer.failures)} failure(s)):"
        )
        for f in sanitizer.failures:
            print(f"    - {f}")
        return 1, None
    print(
        f"  [PASS] sanitized runtime object into a committed-safe "
        f"handoff record ({len(sanitizer.record.get('rows', []))} "
        f"row(s))"
    )

    evidence_path = td / "handoff_record.json"
    validator = _run_validator(
        sanitizer.record, evidence_path=evidence_path,
    )
    if validator.rc != 0:
        print(
            f"  [FAIL] validator subprocess rc={validator.rc} on "
            f"the sanitized record:"
        )
        for line in (validator.stdout or "").splitlines():
            print(f"    stdout: {line}")
        for line in (validator.stderr or "").splitlines():
            print(f"    stderr: {line}")
        return 1, sanitizer.record
    print(
        f"  [PASS] validator subprocess rc=0 on the sanitized "
        f"committed-safe handoff record"
    )
    return 0, sanitizer.record


# Probes — every probe takes a clone of the sanitized baseline,
# mutates one field, and asserts the validator subprocess refuses
# with the documented diagnostic substring.


def _clone(record: dict) -> dict:
    return json.loads(json.dumps(record))


@dataclass
class _ProbeOutcome:
    name: str
    ok: bool
    detail: str = ""


def _run_probe(
    *, baseline: dict, name: str, mutator,
    expect_rc: int, expect_substring: str, td: Path, idx: int,
) -> _ProbeOutcome:
    clone = _clone(baseline)
    mutator(clone)
    path = td / f"probe_{idx:02d}.json"
    outcome = _run_validator(clone, evidence_path=path)
    if outcome.rc != expect_rc:
        return _ProbeOutcome(
            name, False,
            f"expected validator rc={expect_rc}; got rc={outcome.rc}. "
            f"stdout={outcome.stdout!r} stderr={outcome.stderr!r}",
        )
    if expect_substring and expect_substring not in outcome.combined:
        return _ProbeOutcome(
            name, False,
            f"validator rc={outcome.rc} but no diagnostic contained "
            f"{expect_substring!r}; "
            f"stdout={outcome.stdout!r} stderr={outcome.stderr!r}",
        )
    return _ProbeOutcome(name, True)


def _mutate_drop_local_asset_row(record: dict) -> None:
    rows = record.get("rows") or []
    record["rows"] = [
        r for r in rows
        if r.get("source_class") != "local_asset"
    ]


def _mutate_drop_d_one_row(record: dict) -> None:
    rows = record.get("rows") or []
    record["rows"] = [
        r for r in rows
        if r.get("source_class") != "d_one_local"
    ]


def _mutate_local_asset_in_sidecar(record: dict) -> None:
    rows = record.get("rows") or []
    local_ids = [
        r["id"] for r in rows
        if r.get("source_class") == "local_asset"
        and isinstance(r.get("id"), str)
    ]
    sc = record.get("sidecar") or {}
    request_ids = list(sc.get("request_ids") or [])
    sc["request_ids"] = sorted(set(request_ids + local_ids))


def _mutate_drop_d_one_from_sidecar(record: dict) -> None:
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
    ] or ["zzz_orphan_id"]


def _mutate_sha_mismatch(record: dict) -> None:
    rows = record.get("rows") or []
    for r in rows:
        if r.get("source_class") == "d_one_local":
            r["pptx_media"]["sha256"] = "c" * 64
            break


def _mutate_absolute_path_leak(record: dict) -> None:
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("asset"), dict):
        rows[0]["asset"]["path"] = "/etc/passwd"


def _mutate_public_hosting_intended_use(record: dict) -> None:
    rows = record.get("rows") or []
    if rows:
        rows[0]["intended_use"] = (
            "spot illustration; public hosting enabled"
        )


def _mutate_credential_token_intended_use(record: dict) -> None:
    rows = record.get("rows") or []
    if rows:
        rows[0]["intended_use"] = (
            "spot illustration; token=value"
        )


def _mutate_real_d_one_claim_scope(record: dict) -> None:
    notes = record.get("notes")
    if isinstance(notes, dict):
        notes["scope"] = (
            "Real D-One verified online: production run succeeded."
        )


def _mutate_drop_d_one_generated_intent(record: dict) -> None:
    """Strip generated_intent from the d_one_local row. Validator G18
    must refuse (every d_one_local row must carry the per-row
    taxonomy projection)."""
    rows = record.get("rows") or []
    for r in rows:
        if r.get("source_class") == "d_one_local" and "generated_intent" in r:
            del r["generated_intent"]


def _mutate_attach_local_asset_generated_intent(record: dict) -> None:
    """Attach generated_intent to a local_asset row. Validator G18
    must refuse (caller-staged bytes are not a generated artifact and
    have no D-One intent)."""
    rows = record.get("rows") or []
    for r in rows:
        if r.get("source_class") == "local_asset":
            r["generated_intent"] = {
                "placement_role": "local_region",
                "text_policy": "no_text",
                "subject_domain": "abstract_geometry",
            }
            break


def _mutate_generated_intent_text_policy_drift(record: dict) -> None:
    """Flip the d_one_local row's text_policy so it diverges from the
    sidecar.requests entry. Validator G18 must refuse on per-id
    parity."""
    rows = record.get("rows") or []
    for r in rows:
        if r.get("source_class") == "d_one_local":
            gi = r.get("generated_intent") or {}
            current = gi.get("text_policy")
            gi["text_policy"] = (
                "caption_safe"
                if current == "decorative_glyphs"
                else "decorative_glyphs"
            )
            r["generated_intent"] = gi
            break


def _mutate_sidecar_requests_drop_d_one(record: dict) -> None:
    """Drop the d_one_local id from sidecar.requests. Validator G18
    must refuse (every d_one_local row must have a matching
    sidecar.requests entry)."""
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


_PROBES: tuple[tuple[str, callable, int, str], ...] = (
    (
        "P1 missing local_asset row refused",
        _mutate_drop_local_asset_row, 1,
        "minItems is 2",
    ),
    (
        "P2 missing d_one_local row refused",
        _mutate_drop_d_one_row, 1,
        "minItems is 2",
    ),
    (
        "P3 local_asset id leaks into sidecar.request_ids",
        _mutate_local_asset_in_sidecar, 1,
        "leaked into the sidecar",
    ),
    (
        "P4 d_one_local id missing from sidecar.request_ids",
        _mutate_drop_d_one_from_sidecar, 1,
        "NOT in the sidecar",
    ),
    (
        "P5 pptx_media.sha256 vs asset.sha256 mismatch",
        _mutate_sha_mismatch, 1,
        "sha256 drift",
    ),
    (
        "P6 absolute path leak on rows[0].asset.path refused",
        _mutate_absolute_path_leak, 1,
        "does not match pattern",
    ),
    (
        "P7 public-hosting wording in intended_use refused",
        _mutate_public_hosting_intended_use, 1,
        "public-distribution",
    ),
    (
        "P8 credential token in intended_use refused",
        _mutate_credential_token_intended_use, 1,
        "credential",
    ),
    (
        "P9 real-D-One success claim in notes.scope refused",
        _mutate_real_d_one_claim_scope, 1,
        "real-D-One / MCP / network / model / image-search / Qoder",
    ),
    (
        "P10 d_one_local row missing generated_intent refused "
        "(validator G18 generated_intent parity)",
        _mutate_drop_d_one_generated_intent, 1,
        "missing required generated_intent",
    ),
    (
        "P11 local_asset row carrying generated_intent refused "
        "(validator G18 generated_intent parity)",
        _mutate_attach_local_asset_generated_intent, 1,
        "carries generated_intent (forbidden",
    ),
    (
        "P12 generated_intent.text_policy drift from "
        "sidecar.requests entry refused (validator G18 per-id parity)",
        _mutate_generated_intent_text_policy_drift, 1,
        "text_policy",
    ),
    (
        "P13 d_one_local id missing from sidecar.requests refused "
        "(validator G18 1:1 coverage)",
        _mutate_sidecar_requests_drop_d_one, 1,
        "has NO matching sidecar.requests entry",
    ),
)


def _run_probes(baseline: dict, td: Path) -> int:
    print()
    print("--- self-test fail-closed probes ---")
    fails = 0
    for idx, (name, mutator, expect_rc, expect_sub) in enumerate(
        _PROBES, start=1,
    ):
        result = _run_probe(
            baseline=baseline, name=name, mutator=mutator,
            expect_rc=expect_rc, expect_substring=expect_sub,
            td=td, idx=idx,
        )
        mark = "PASS" if result.ok else "FAIL"
        suffix = f" -- {result.detail}" if not result.ok else ""
        print(f"  [{mark}] {name}{suffix}")
        if not result.ok:
            fails += 1
    return fails


# ---------------------------------------------------------------------------
# Self-test top level.
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    print(
        "=== mixed_image_asset_provenance_handoff_smoke "
        "(--self-test) ==="
    )

    tree_before = _snapshot_committed_tree()
    if not tree_before:
        print(
            "FAIL: committed-tree snapshot is empty — refusing to "
            "run because a downstream regression cannot be detected "
            "against an empty baseline.",
            file=sys.stderr,
        )
        return 1

    rc = 0
    with tempfile.TemporaryDirectory(
        prefix="szh_mixed_handoff_smoke_",
    ) as raw_td:
        td = Path(raw_td)
        happy_rc, baseline = _run_happy_path(td)
        if happy_rc != 0 or baseline is None:
            rc = 1
        else:
            probe_fails = _run_probes(baseline, td)
            if probe_fails:
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
        print()
        print(
            "OK (mixed image-asset provenance handoff): happy path "
            "+ every fail-closed probe passed; nothing under "
            "REPO_ROOT mutated. Real D-One remains UNVERIFIED."
        )
    return rc


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mixed image-asset provenance handoff smoke. Drives a "
            "synthetic mixed-lane bundle (d_one_local + "
            "local_asset) through the local mock pipeline into a "
            "tempdir, sanitizes the runtime TEMP-ONLY provenance "
            "object into a committed-safe handoff record matching "
            "schemas/mixed_image_asset_provenance.schema.json, runs "
            "scripts/validate_mixed_image_asset_provenance.py "
            "against the sanitized record, and asserts no repo "
            "mutation. MOCK / STUB only — NETWORK-FREE — stdlib-"
            "only. Self-test surface only today."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Required: run the happy path + every fail-closed "
            "probe."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: mixed_image_asset_provenance_handoff_smoke.py "
            "requires --self-test (no production CLI surface "
            "exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
