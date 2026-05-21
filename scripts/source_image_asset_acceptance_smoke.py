#!/usr/bin/env python3
"""source_image_asset_acceptance_smoke.py

Clean-room, stdlib-only acceptance smoke for the source-attached
image-asset chain — the read-only registry side of the local
PNG / JPG / JPEG embed surface ``scripts/export_pptx.py`` supports
today.

The smoke proves that a caller-provided synthetic PNG **and** JPG
source-image-asset pair can:

  - be authored under ``<workspace>/input/assets/<id>.<ext>`` as
    regular non-symlink files with valid magic bytes;
  - be declared in ``<workspace>/source_image_assets.json`` with the
    correct ``id`` / ``source_ref`` / ``local_path`` /
    ``destination_path`` / ``media_type`` / ``byte_count`` / ``sha256``
    such that the dedicated read-only registry validator
    ``scripts/validate_source_image_assets.py`` returns rc=0 with
    every G1–G13 gate passing;
  - align byte-for-byte against the sibling ``source_manifest.json``
    body intake (registry ``source_ref`` == ``source_manifest.source.id``);
  - align with the sibling ``image_manifest.json`` whose
    ``images[*].id`` matches the registry ``assets[*].id``,
    ``images[*].local_path`` equals the registry
    ``assets[*].destination_path``, and ``images[*].source`` equals
    ``"local_asset"`` (registry G10 alignment + G13 completeness);
  - be referenced by ``<workspace>/slide_plans/<idx:02d>_<layout>.json``
    files whose ``image_refs`` field is a subset of
    ``image_manifest.images[*].id``;
  - be materialized into the workspace image surface
    ``<workspace>/assets/<id>.<ext>`` by
    ``scripts/materialize_image_assets.py --assets-dir
    <workspace>/input/assets`` (the documented "input/assets/ as the
    assets-dir" workflow per ``references/source-image-asset-policy.md``);
  - be embedded into the produced ``.pptx`` by
    ``scripts/export_pptx.py --workspace <ws> --output <out>`` as a
    native ``<p:pic>`` referencing an internal ``ppt/media/imageN.<ext>``
    part, never via an external / file:// / data: / scheme-shaped
    relationship;
  - re-validate against ``scripts/validate_pptx_contract.py --pptx
    <out> --expected-slide-count N`` with rc=0 (every container +
    package + minimal-evidence + relationships + slide_count gate
    passes);
  - inspect through ``scripts/inspect_pptx_inventory.py --pptx <out>
    --out <inv.json>`` with ``ok=true`` / ``findings=[]`` /
    ``slide_count == len(deck_plan.slides)`` / ``len(media_parts) >
    0`` / ``evidence_basis ==
    "OOXML structure only; not proof of full PowerPoint editability"``;
  - preserve editable / native PPTX evidence: ``validate_pptx_contract``'s
    ``minimal_evidence.every_slide_has_native_shape`` +
    ``minimal_evidence.not_all_image_slide`` +
    ``minimal_evidence.editable_text`` all pass, so the deck still
    carries native editable structure and is NOT an all-image / all-
    raster fallback.

**MOCK / STUB ACCEPTANCE ONLY — NOT real D-One integration.** Real
D-One / MCP / model-API / image-search / Qoder / public-network
integration is intentionally TODO; nothing in this script calls D-One,
MCP, Qoder, a public network, telemetry, any model API, an image
search, a browser, or any external service. The PNG / JPG bytes are
minimal magic-byte-valid local payloads inlined in this script (one
8-byte PNG signature + IHDR + IDAT + IEND for a 1x1 PNG, and a
``\\xff\\xd8\\xff\\xe0`` + JFIF + EOI byte string for the JPG); neither
claims to be photographically meaningful. The final summary states
explicitly that real D-One remains UNVERIFIED and uncalled.

Negative probes (each runs under its own
``tempfile.TemporaryDirectory()``; each expects fail-closed behavior
on a documented perturbation of the same baseline):

  N1   missing source image bytes
        ``scripts/validate_source_image_assets.py`` G7 fires when
        the file at ``<workspace>/<local_path>`` is absent.

  N2   byte_count mismatch
        G8 fires when the declared ``byte_count`` does not match the
        on-disk length of the source file.

  N3   sha256 mismatch
        G8 fires when the declared lowercase-hex ``sha256`` does not
        match the on-disk sha256 of the source file.

  N4   wrong magic bytes
        G9 fires when the file extension says ``.png`` but the bytes
        are JPEG-shaped (or vice versa).

  N5   source_ref mismatch with source_manifest.source.id
        G4 fires when the registry's ``source_ref`` does not equal
        the sibling ``source_manifest.json``'s ``source.id``.

  N6   image_manifest missing declared id
        G13 fires when the sibling ``image_manifest.json`` is present
        and well-formed but does not name the registry asset's id.

  N7   slide_plan declares an undeclared image_ref
        smoke-level cross-check: the positive proof asserts every
        ``slide_plan.image_refs`` entry is a subset of
        ``image_manifest.images[*].id``; the probe perturbs the
        slide_plan to declare an id the manifest never lists and the
        smoke-level cross-check fails closed.

  N8   unsafe local_path / destination_path shapes
        schema patterns + G5 refuse ``http://``, ``https://``,
        ``file://``, ``data:``, protocol-relative ``//``, parent
        traversal ``..``, POSIX absolute ``/...``, and Windows
        absolute ``C:\\...`` shapes.

  N9   symlinked source file
        G6 fires when ``<workspace>/<local_path>`` is itself a
        symlink (broken or resolvable).

  N10  symlinked source parent
        G6 fires when any intermediate segment between
        ``<workspace>`` and the source-asset leaf is a symlink.

  N11  symlinked destination parent
        G6 fires when any intermediate segment of the
        ``destination_path`` chain inside the workspace is a symlink.

  N12  unsupported media type / extension
        schema enum + G9 refuse ``image/svg+xml`` / ``image/gif`` /
        ``image/webp`` etc., AND the schema-locked path patterns
        refuse ``.svg`` / ``.gif`` / ``.webp`` / ``.tiff`` / ``.bmp`` /
        ``.ico`` / mixed-case ``.PNG``.

  N13  public upload / share / hosting wording
        G12 fires on the canonical form combination of ``public`` +
        any of ``upload`` / ``share`` / ``sharing`` / ``url`` /
        ``link`` / ``post`` / ``publish`` / ``distribut``, across
        separator / word-order / morphology variants.

  N14  credential-shaped strings
        the schema id / source_ref pattern refuses every credential
        shape covered here (``password:`` / ``secret:`` / ``api_key:``
        contain ``:``, ``Bearer abc`` contains a space, ``-----BEGIN
        PRIVATE KEY-----`` starts with ``-``); the G11 URI-scheme
        runtime gate fires only on the SUBSET whose scheme prefix
        matches RFC 3986's ``^[A-Za-z][A-Za-z0-9+.\\-]*:`` — namely
        ``password:`` and ``secret:`` (pure-letter prefix before
        ``:``). ``api_key:`` contains ``_``, which is OUTSIDE RFC
        3986's scheme charset, so G11 does NOT fire on it — the
        schema id pattern alone refuses ``api_key:``. ``Bearer abc``
        and ``-----BEGIN`` carry no ``:``-terminated scheme prefix
        and likewise never reach G11. These are the credential
        subsets the registry validator owns today; shapes the
        validator does not own (e.g. cloud access-key-looking values
        made only of letters/digits, which contain only
        ``[A-Za-z0-9]`` and pass every gate today) are intentionally
        NOT included.

Snapshot check: every scenario runs under
``tempfile.TemporaryDirectory()``; flat-bytes snapshots of
``REPO_ROOT/examples/`` AND ``REPO_ROOT/scripts/`` taken before and
after the run must match — proves no generated artifact (PNG / JPG /
PPTX / render_models / svg_previews / reports / dist / temp /
``__pycache__``) lands under any committed repo surface.

Fail-closed: any chain step exiting non-zero on the positive path,
any documented post-condition failing, or any negative probe whose
gate does NOT fire as documented aborts the smoke immediately and the
script exits non-zero with a clear per-assertion / per-probe
diagnostic.

Stdlib-only.
"""
from __future__ import annotations

import sys

# Refuse to write `.pyc` files for any module imported by this script.
# The repo-immutability snapshot below baselines `REPO_ROOT/scripts/`
# AFTER `main()` starts, so without this gate a downstream import
# could silently land `scripts/__pycache__/<module>.cpython-*.pyc` on
# a clean checkout BEFORE the snapshot fires, and the gate would miss
# the write entirely. ``PYTHONDONTWRITEBYTECODE=1`` in the env
# achieves the same thing for callers that remember the prefix, but
# the in-script flip closes the hole unconditionally. Must come BEFORE
# any first-party import; the interpreter checks the flag at
# bytecode-write time.
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
from xml.etree import ElementTree as ET  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

VALIDATE_SOURCE_IMAGE_ASSETS = SCRIPTS_DIR / "validate_source_image_assets.py"
MATERIALIZE_IMAGE_ASSETS = SCRIPTS_DIR / "materialize_image_assets.py"
EXPORT_PPTX = SCRIPTS_DIR / "export_pptx.py"
VALIDATE_PPTX_CONTRACT = SCRIPTS_DIR / "validate_pptx_contract.py"
INSPECT_PPTX_INVENTORY = SCRIPTS_DIR / "inspect_pptx_inventory.py"

# Must match scripts/inspect_pptx_inventory.py::EVIDENCE_BASIS verbatim.
EXPECTED_EVIDENCE_BASIS = (
    "OOXML structure only; not proof of full PowerPoint editability"
)

# OOXML namespace for the Relationships parts the smoke walks. The
# parts under ``_rels/*.rels`` all use this XML namespace.
_NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

# Any string with a leading RFC-3986 scheme followed by ':' counts as
# an external Target. Internal package targets (``../media/image1.png``,
# ``slides/slide1.xml``) carry no scheme prefix and survive this check.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Embed surface scripts/export_pptx.py supports today. Anything else
# falls back to a placeholder native shape (no media part), so the
# positive proof refuses to see no PNG/JPG/JPEG entries under
# ``ppt/media/``.
_EMBEDDABLE_MEDIA_EXTS: tuple[str, ...] = (".png", ".jpg", ".jpeg")

# Synthetic PNG / JPG payloads. Both pass the magic-byte gates
# materialize_image_assets and export_pptx enforce. Neither claims to
# be photographically meaningful — the smoke proves the contract chain
# holds, not the visual fidelity of any generator.

# Minimal valid 1x1 PNG: 8-byte signature + IHDR + IDAT + IEND. Mirrors
# the synthetic payload other smokes use.
_TINY_PNG_BYTES: bytes = bytes.fromhex(
    "89504e470d0a1a0a"
    "0000000d49484452"
    "0000000100000001"
    "08060000001f15c489"
    "0000000d49444154"
    "789c6300010000000500010d0a2db4"
    "0000000049454e44ae426082"
)

# Minimal magic-byte-valid JPEG: SOI + APP0 (JFIF) + EOI. Matches the
# byte prefix scripts/materialize_image_assets.py and
# scripts/export_pptx.py both gate on.
_TINY_JPEG_BYTES: bytes = (
    b"\xff\xd8\xff\xe0"
    + b"\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    + b"\xff\xd9"
)

# Synthetic asset / source identifiers. Each id MUST collapse to a
# canonical form (lower-cased + non-alphanumeric stripped) that does
# NOT contain the ``public`` marker combined with a propagation verb —
# otherwise G12 would refuse the positive registry. ``source_alpha`` /
# ``source_beta`` / ``synthetic_source_for_smoke`` all pass.
SYNTHETIC_SOURCE_ID = "synthetic_source_for_smoke"
SYNTHETIC_PNG_ASSET_ID = "source_alpha"
SYNTHETIC_JPG_ASSET_ID = "source_beta"
SYNTHETIC_PNG_LOCAL_PATH = f"input/assets/{SYNTHETIC_PNG_ASSET_ID}.png"
SYNTHETIC_PNG_DEST_PATH = f"assets/{SYNTHETIC_PNG_ASSET_ID}.png"
SYNTHETIC_JPG_LOCAL_PATH = f"input/assets/{SYNTHETIC_JPG_ASSET_ID}.jpg"
SYNTHETIC_JPG_DEST_PATH = f"assets/{SYNTHETIC_JPG_ASSET_ID}.jpg"


REAL_D_ONE_STATUS = (
    "UNVERIFIED — real D-One is NOT called by this smoke. The synthetic "
    "PNG and JPG bytes are minimal magic-byte-valid local payloads "
    "inlined in this script; nothing here calls D-One, MCP, Qoder, a "
    "public network, telemetry, any model API, an image search, a "
    "browser, or any external service."
)


# ---------------------------------------------------------------------------
# Snapshot helpers — prove the smoke writes nothing under REPO_ROOT.
# ---------------------------------------------------------------------------


def _snapshot_dir(d: Path) -> dict[str, bytes]:
    """Flat path -> bytes map of every regular file under ``d``. Same
    shape as scripts/acceptance_smoke.py::_snapshot_dir so the
    no-mutation invariant is asserted with the same gate the existing
    smokes use."""
    out: dict[str, bytes] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        out[str(p.relative_to(d))] = p.read_bytes()
    return out


def _check_repo_unchanged(
    examples_before: dict[str, bytes],
    scripts_before: dict[str, bytes],
) -> int:
    rc = 0
    examples_after = _snapshot_dir(REPO_ROOT / "examples")
    if examples_before != examples_after:
        changed = [
            k for k in sorted(set(examples_before) | set(examples_after))
            if examples_before.get(k) != examples_after.get(k)
        ]
        print(
            f"FAIL: examples/ was mutated by the smoke "
            f"(changed paths: {changed!r}). Every scenario must run "
            f"inside tempfile.TemporaryDirectory().",
            file=sys.stderr,
        )
        rc = 1
    scripts_after = _snapshot_dir(REPO_ROOT / "scripts")
    if scripts_before != scripts_after:
        changed = [
            k for k in sorted(set(scripts_before) | set(scripts_after))
            if scripts_before.get(k) != scripts_after.get(k)
        ]
        print(
            f"FAIL: scripts/ was mutated by the smoke "
            f"(changed paths: {changed!r}). Every scenario must run "
            f"inside tempfile.TemporaryDirectory().",
            file=sys.stderr,
        )
        rc = 1
    return rc


# ---------------------------------------------------------------------------
# Subprocess runner.
# ---------------------------------------------------------------------------


@dataclass
class ToolOutcome:
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


def _run(name: str, cmd: list[str]) -> ToolOutcome:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    return ToolOutcome(
        name=name, cmd=cmd, rc=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


def _print_outcome(o: ToolOutcome) -> None:
    print(f"  [{'PASS' if o.ok else 'FAIL'}] {o.name} (rc={o.rc})")
    if not o.ok:
        for stream_name, body in (("stdout", o.stdout), ("stderr", o.stderr)):
            tail = (body or "").splitlines()[-12:]
            if tail:
                print(f"    {stream_name} tail:")
                for line in tail:
                    print(f"      {line}")


# ---------------------------------------------------------------------------
# Fixture writers.
# ---------------------------------------------------------------------------


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")


def _write_source_manifest(workspace: Path) -> bytes:
    """Author a schema-valid source_manifest.json describing a synthetic
    ``input/source.md`` body. Returns the body bytes so the caller can
    re-derive byte_count / sha256 if needed."""
    body = (
        b"# Synthetic source body\n\n"
        b"This is a synthetic, non-sensitive Markdown body authored "
        b"by the source-image-asset acceptance smoke. It exists only "
        b"to satisfy the Stage-1 source-manifest contract; no slide "
        b"field copies a single byte of this file.\n"
    )
    (workspace / "input").mkdir(parents=True, exist_ok=True)
    (workspace / "input" / "source.md").write_bytes(body)
    line_count = body.count(b"\n") + (0 if body.endswith(b"\n") else 1)
    manifest = {
        "schema_version": "1",
        "source": {
            "id": SYNTHETIC_SOURCE_ID,
            "local_path": "input/source.md",
            "kind": "markdown",
            "byte_count": len(body),
            "line_count": line_count,
            "sha256": _sha256(body),
        },
        "tool": {"name": "init_workspace", "version": "1"},
    }
    _write_json(workspace / "source_manifest.json", manifest)
    return body


def _write_source_image_assets(
    workspace: Path,
    *,
    png_bytes: bytes,
    jpg_bytes: bytes,
) -> dict:
    """Author the registry. Returns the registry dict the caller can
    cross-check against image_manifest / slide_plans."""
    registry = {
        "schema_version": "1",
        "assets": [
            {
                "id": SYNTHETIC_PNG_ASSET_ID,
                "source_ref": SYNTHETIC_SOURCE_ID,
                "local_path": SYNTHETIC_PNG_LOCAL_PATH,
                "destination_path": SYNTHETIC_PNG_DEST_PATH,
                "media_type": "image/png",
                "byte_count": len(png_bytes),
                "sha256": _sha256(png_bytes),
            },
            {
                "id": SYNTHETIC_JPG_ASSET_ID,
                "source_ref": SYNTHETIC_SOURCE_ID,
                "local_path": SYNTHETIC_JPG_LOCAL_PATH,
                "destination_path": SYNTHETIC_JPG_DEST_PATH,
                "media_type": "image/jpeg",
                "byte_count": len(jpg_bytes),
                "sha256": _sha256(jpg_bytes),
            },
        ],
    }
    _write_json(workspace / "source_image_assets.json", registry)
    return registry


def _write_image_manifest(workspace: Path) -> dict:
    """Author the image_manifest aligned with the registry: id matches,
    local_path == registry destination_path, source == 'local_asset'."""
    manifest = {
        "images": [
            {
                "id": SYNTHETIC_PNG_ASSET_ID,
                "local_path": SYNTHETIC_PNG_DEST_PATH,
                "source": "local_asset",
                "alt_text": (
                    "Synthetic source-attached marker PNG "
                    "(smoke fixture)."
                ),
                "intended_use": "spot illustration",
            },
            {
                "id": SYNTHETIC_JPG_ASSET_ID,
                "local_path": SYNTHETIC_JPG_DEST_PATH,
                "source": "local_asset",
                "alt_text": (
                    "Synthetic source-attached marker JPG "
                    "(smoke fixture)."
                ),
                "intended_use": "spot illustration",
            },
        ],
    }
    _write_json(workspace / "image_manifest.json", manifest)
    return manifest


def _write_deck_plan(workspace: Path) -> dict:
    """Two-slide deck — one ``two_column`` slide referencing the PNG,
    one ``two_column`` slide referencing the JPG. Both slides carry an
    ``image_slot`` primitive in their render_model so the export embeds
    both assets as native PPTX media. Layout / primitive scope sits
    inside the per-stage allow-list documented in CLAUDE.md."""
    plan = {
        "template": "synthetic",
        "planning": {
            "planned_slide_count": 2,
            "rationale": (
                "Two-slide synthetic deck: one slide per source-"
                "attached image asset (PNG + JPG). Exercises the "
                "embed surface end-to-end while keeping the deck "
                "short enough to validate exhaustively."
            ),
        },
        "sections": [
            {
                "id": "all",
                "title": "All",
                "summary": "Both source-attached images.",
                "slide_indices": [1, 2],
            },
        ],
        "slides": [
            {
                "index": 1,
                "layout": "two_column",
                "title": "Source-Attached PNG",
                "section_id": "all",
                "summary": "Synthetic source-attached PNG marker.",
                "density": "low",
                "source_refs": [SYNTHETIC_SOURCE_ID],
            },
            {
                "index": 2,
                "layout": "two_column",
                "title": "Source-Attached JPG",
                "section_id": "all",
                "summary": "Synthetic source-attached JPG marker.",
                "density": "low",
                "source_refs": [SYNTHETIC_SOURCE_ID],
            },
        ],
    }
    _write_json(workspace / "deck_plan.json", plan)
    return plan


def _write_design_system(workspace: Path) -> None:
    ds = {
        "palette": {
            "primary": "#1F3A5F",
            "background": "#FFFFFF",
            "text": "#1A1A1A",
        },
        "typography": {
            "heading": {
                "font_family":
                    "Calibri, Helvetica Neue, Arial, sans-serif",
                "size_pt": 28,
            },
            "body": {
                "font_family":
                    "Calibri, Helvetica Neue, Arial, sans-serif",
                "size_pt": 14,
            },
        },
        "grid": {"width_px": 1920, "height_px": 1080, "margin_px": 64},
    }
    _write_json(workspace / "design_system.json", ds)


def _write_slide_plans(workspace: Path) -> list[dict]:
    """Author the two slide_plans referenced by deck_plan.slides[]. Each
    declares an ``image_refs`` field that names the corresponding
    image_manifest id. The smoke-level positive cross-check asserts
    every image_refs entry is a subset of image_manifest.images[*].id."""
    plans_dir = workspace / "slide_plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    sp1 = {
        "index": 1,
        "layout": "two_column",
        "title": "Source-Attached PNG",
        "blocks": [
            {"id": "title", "kind": "text",
             "content": "Source-Attached PNG"},
            {"id": "marker_image", "kind": "image_ref",
             "content": SYNTHETIC_PNG_ASSET_ID},
        ],
        "image_refs": [SYNTHETIC_PNG_ASSET_ID],
        "notes": "Synthetic.",
    }
    sp2 = {
        "index": 2,
        "layout": "two_column",
        "title": "Source-Attached JPG",
        "blocks": [
            {"id": "title", "kind": "text",
             "content": "Source-Attached JPG"},
            {"id": "marker_image", "kind": "image_ref",
             "content": SYNTHETIC_JPG_ASSET_ID},
        ],
        "image_refs": [SYNTHETIC_JPG_ASSET_ID],
        "notes": "Synthetic.",
    }
    _write_json(plans_dir / "01_two_column.json", sp1)
    _write_json(plans_dir / "02_two_column.json", sp2)
    return [sp1, sp2]


def _write_render_models(workspace: Path) -> None:
    """Author two two_column render_models, each carrying an
    ``image_slot`` primitive whose ``image_ref`` is one of the
    declared image_manifest ids. The exporter walks ``primitives`` and
    embeds each ``image_slot`` whose manifest entry resolves to a PNG /
    JPG / JPEG file as a native ``<p:pic>``."""
    rm_dir = workspace / "render_models"
    rm_dir.mkdir(parents=True, exist_ok=True)
    rm1 = {
        "index": 1,
        "layout": "two_column",
        "canvas": {"width_px": 1920, "height_px": 1080},
        "source_refs": [SYNTHETIC_SOURCE_ID],
        "primitives": [
            {
                "id": "title",
                "slot_id": "title",
                "kind": "text",
                "bounds": {"x": 64, "y": 80, "w": 1792, "h": 100},
                "style": {
                    "color_token": "palette.text",
                    "typography_token": "typography.heading",
                },
                "text": {
                    "content": "Source-Attached PNG",
                    "role": "heading",
                },
            },
            {
                "id": "marker_image",
                "kind": "image_slot",
                "bounds": {"x": 200, "y": 300, "w": 200, "h": 200},
                "image_slot": {
                    "image_ref": SYNTHETIC_PNG_ASSET_ID,
                    "alt_text": (
                        "Synthetic source-attached marker PNG "
                        "(smoke fixture)."
                    ),
                },
            },
        ],
    }
    rm2 = {
        "index": 2,
        "layout": "two_column",
        "canvas": {"width_px": 1920, "height_px": 1080},
        "source_refs": [SYNTHETIC_SOURCE_ID],
        "primitives": [
            {
                "id": "title",
                "slot_id": "title",
                "kind": "text",
                "bounds": {"x": 64, "y": 80, "w": 1792, "h": 100},
                "style": {
                    "color_token": "palette.text",
                    "typography_token": "typography.heading",
                },
                "text": {
                    "content": "Source-Attached JPG",
                    "role": "heading",
                },
            },
            {
                "id": "marker_image",
                "kind": "image_slot",
                "bounds": {"x": 200, "y": 300, "w": 200, "h": 200},
                "image_slot": {
                    "image_ref": SYNTHETIC_JPG_ASSET_ID,
                    "alt_text": (
                        "Synthetic source-attached marker JPG "
                        "(smoke fixture)."
                    ),
                },
            },
        ],
    }
    _write_json(rm_dir / "01_two_column.json", rm1)
    _write_json(rm_dir / "02_two_column.json", rm2)


def _build_positive_workspace(workspace: Path) -> dict:
    """Write every artifact the positive chain needs into ``workspace``.
    Returns a dict carrying the registry / manifest / deck_plan /
    slide_plans bodies the caller can cross-check at the smoke level."""
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "input" / "assets").mkdir(parents=True, exist_ok=True)
    (workspace / "input" / "assets"
     / f"{SYNTHETIC_PNG_ASSET_ID}.png").write_bytes(_TINY_PNG_BYTES)
    (workspace / "input" / "assets"
     / f"{SYNTHETIC_JPG_ASSET_ID}.jpg").write_bytes(_TINY_JPEG_BYTES)

    _write_source_manifest(workspace)
    registry = _write_source_image_assets(
        workspace, png_bytes=_TINY_PNG_BYTES, jpg_bytes=_TINY_JPEG_BYTES,
    )
    manifest = _write_image_manifest(workspace)
    plan = _write_deck_plan(workspace)
    _write_design_system(workspace)
    slide_plans = _write_slide_plans(workspace)
    _write_render_models(workspace)
    return {
        "registry": registry,
        "image_manifest": manifest,
        "deck_plan": plan,
        "slide_plans": slide_plans,
    }


# ---------------------------------------------------------------------------
# Positive-proof assertions.
# ---------------------------------------------------------------------------


@dataclass
class Assertion:
    name: str
    ok: bool
    detail: str = ""


def _assert_alignment(
    *, workspace: Path, fixtures: dict,
) -> list[Assertion]:
    """Smoke-level alignment cross-checks. The validator's G4 / G10 /
    G13 already cover these, but re-asserting at the smoke level keeps
    the diagnostic close to the failing fact and makes the positive
    proof self-describing.

      * registry source_ref == source_manifest.source.id (mirrors G4);
      * registry id set == image_manifest id set (mirrors G10 + G13
        on the matched ids);
      * registry destination_path == image_manifest local_path for
        every matched id (mirrors G10);
      * slide_plan.image_refs ⊆ image_manifest.images[].id (cross-check
        the smoke owns end-to-end);
      * every registry path passes a local containment + non-symlink
        sanity check (mirrors G5 + G6);
      * on-disk byte_count and sha256 for every registry asset match
        the registry declaration (mirrors G7 + G8)."""
    results: list[Assertion] = []
    manifest_path = workspace / "source_manifest.json"
    sm = json.loads(manifest_path.read_text())
    sm_source_id = sm["source"]["id"]
    registry = fixtures["registry"]
    image_manifest = fixtures["image_manifest"]
    slide_plans = fixtures["slide_plans"]

    # source_ref alignment.
    bad_refs = [
        a["id"] for a in registry["assets"]
        if a["source_ref"] != sm_source_id
    ]
    results.append(Assertion(
        "registry source_ref aligns with source_manifest.source.id",
        not bad_refs,
        f"assets with mismatched source_ref: {bad_refs!r}, "
        f"expected {sm_source_id!r}",
    ))

    # id alignment.
    registry_ids = {a["id"] for a in registry["assets"]}
    manifest_ids = {img["id"] for img in image_manifest["images"]}
    results.append(Assertion(
        "registry asset id set matches image_manifest id set",
        registry_ids == manifest_ids,
        f"registry-only: {sorted(registry_ids - manifest_ids)!r}; "
        f"manifest-only: {sorted(manifest_ids - registry_ids)!r}",
    ))

    # destination_path alignment + every image_manifest entry uses
    # source == "local_asset".
    manifest_by_id = {img["id"]: img for img in image_manifest["images"]}
    dest_mismatches: list[str] = []
    source_mismatches: list[str] = []
    for a in registry["assets"]:
        m = manifest_by_id.get(a["id"])
        if m is None:
            continue
        if m.get("local_path") != a["destination_path"]:
            dest_mismatches.append(
                f"{a['id']!r}: manifest local_path={m.get('local_path')!r}, "
                f"registry destination_path={a['destination_path']!r}"
            )
        if m.get("source") != "local_asset":
            source_mismatches.append(
                f"{a['id']!r}: manifest source={m.get('source')!r}"
            )
    results.append(Assertion(
        "image_manifest.local_path == registry destination_path "
        "for every matched id",
        not dest_mismatches,
        "; ".join(dest_mismatches),
    ))
    results.append(Assertion(
        "image_manifest.source == 'local_asset' for every matched id",
        not source_mismatches,
        "; ".join(source_mismatches),
    ))

    # slide_plan.image_refs ⊆ image_manifest ids.
    undeclared: list[str] = []
    for sp in slide_plans:
        for ref in sp.get("image_refs") or []:
            if ref not in manifest_ids:
                undeclared.append(
                    f"slide_plan index {sp.get('index')} declares "
                    f"image_ref {ref!r} not present in image_manifest"
                )
    results.append(Assertion(
        "slide_plan.image_refs is a subset of image_manifest.images[].id",
        not undeclared,
        "; ".join(undeclared),
    ))

    # Path safety + non-symlink + containment (smoke-level mirror of
    # G5 / G6).
    bad_paths: list[str] = []
    for a in registry["assets"]:
        for field, rel in (
            ("local_path", a["local_path"]),
            ("destination_path", a["destination_path"]),
        ):
            if rel.startswith("/") or rel.startswith("\\"):
                bad_paths.append(f"{a['id']}.{field}: absolute {rel!r}")
                continue
            if ".." in Path(rel).parts:
                bad_paths.append(f"{a['id']}.{field}: traversal {rel!r}")
                continue
            if _URI_SCHEME_PREFIX.match(rel):
                bad_paths.append(f"{a['id']}.{field}: URI {rel!r}")
                continue
            leaf = workspace / rel
            if leaf.is_symlink():
                bad_paths.append(f"{a['id']}.{field}: leaf is symlink")
                continue
            current = workspace
            symlink_parent = False
            for seg in Path(rel).parts[:-1]:
                current = current / seg
                if current.is_symlink():
                    bad_paths.append(
                        f"{a['id']}.{field}: parent segment {current} "
                        f"is symlink"
                    )
                    symlink_parent = True
                    break
            if symlink_parent:
                continue
    results.append(Assertion(
        "every registry path is workspace-contained and non-symlinked",
        not bad_paths,
        "; ".join(bad_paths),
    ))

    # byte_count + sha256 on-disk integrity (smoke-level mirror of
    # G7 + G8).
    integrity_errors: list[str] = []
    for a in registry["assets"]:
        leaf = workspace / a["local_path"]
        if not (leaf.is_file() and not leaf.is_symlink()):
            integrity_errors.append(
                f"{a['id']}: source file {leaf} is not a regular file"
            )
            continue
        data = leaf.read_bytes()
        if len(data) != a["byte_count"]:
            integrity_errors.append(
                f"{a['id']}: on-disk byte length {len(data)} != "
                f"declared {a['byte_count']}"
            )
        if _sha256(data) != a["sha256"]:
            integrity_errors.append(
                f"{a['id']}: on-disk sha256 != declared"
            )
    results.append(Assertion(
        "every registry asset's byte_count + sha256 match on-disk bytes",
        not integrity_errors,
        "; ".join(integrity_errors),
    ))
    return results


def _assert_pptx_embeds_internal_media_only(
    pptx: Path,
) -> list[Assertion]:
    """Open the PPTX as a ZIP and assert two things:

    1. The package carries at least one PNG AND at least one JPG/JPEG
       part under ``ppt/media/`` — proof both synthetic source-attached
       assets embedded as native PowerPoint media, not as a placeholder
       shape;
    2. Every ``.rels`` part's relationship Target is internal
       (no URI scheme; no ``TargetMode="External"``)."""
    results: list[Assertion] = []
    try:
        zf = zipfile.ZipFile(pptx, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        results.append(Assertion(
            "PPTX opens as a ZIP",
            False,
            f"{type(exc).__name__}: {exc}",
        ))
        return results
    try:
        names = zf.namelist()
        png_parts = sorted(
            n for n in names
            if n.startswith("ppt/media/") and n.lower().endswith(".png")
        )
        jpg_parts = sorted(
            n for n in names
            if n.startswith("ppt/media/")
            and (n.lower().endswith(".jpg") or n.lower().endswith(".jpeg"))
        )
        results.append(Assertion(
            "PPTX embeds at least one ppt/media/ PNG part",
            len(png_parts) > 0,
            f"found media: {sorted(n for n in names if n.startswith('ppt/media/'))!r}"
            if not png_parts else "",
        ))
        results.append(Assertion(
            "PPTX embeds at least one ppt/media/ JPG/JPEG part",
            len(jpg_parts) > 0,
            f"found media: {sorted(n for n in names if n.startswith('ppt/media/'))!r}"
            if not jpg_parts else "",
        ))
        external: list[str] = []
        rel_tag = f"{{{_NS_REL}}}Relationship"
        for n in names:
            if not n.endswith(".rels"):
                continue
            try:
                root = ET.fromstring(zf.read(n))
            except (KeyError, OSError, ET.ParseError) as exc:
                external.append(
                    f"{n}: cannot parse: {type(exc).__name__}: {exc}"
                )
                continue
            for el in root:
                if el.tag != rel_tag:
                    continue
                target = el.attrib.get("Target", "")
                mode = el.attrib.get("TargetMode", "")
                if mode and mode != "Internal":
                    external.append(
                        f"{n}: id={el.attrib.get('Id')!r} "
                        f"TargetMode={mode!r} Target={target!r}"
                    )
                    continue
                if _URI_SCHEME_PREFIX.match(target):
                    external.append(
                        f"{n}: id={el.attrib.get('Id')!r} "
                        f"Target={target!r} (URI scheme)"
                    )
        results.append(Assertion(
            "PPTX has no external / file:// / data: / scheme-shaped "
            "relationships",
            not external,
            "; ".join(external),
        ))
    finally:
        zf.close()
    return results


def _assert_inventory_contract(
    *, inventory_path: Path, expected_slide_count: int,
) -> list[Assertion]:
    results: list[Assertion] = []
    inv_is_file = (
        inventory_path.is_file() and not inventory_path.is_symlink()
    )
    results.append(Assertion(
        "inventory.json exists as a regular non-symlink file",
        inv_is_file,
        f"path={inventory_path}",
    ))
    if not inv_is_file:
        return results
    try:
        inv = json.loads(inventory_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        results.append(Assertion(
            "inventory.json parses as JSON",
            False,
            f"{type(exc).__name__}: {exc}",
        ))
        return results
    results.append(Assertion(
        "inventory.ok is True",
        inv.get("ok") is True,
        f"got {inv.get('ok')!r}",
    ))
    results.append(Assertion(
        "inventory.findings is []",
        inv.get("findings") == [],
        f"got {inv.get('findings')!r}",
    ))
    results.append(Assertion(
        f"inventory.slide_count == {expected_slide_count}",
        inv.get("slide_count") == expected_slide_count,
        f"got {inv.get('slide_count')!r}",
    ))
    mp = inv.get("media_parts")
    results.append(Assertion(
        "inventory.media_parts is a non-empty list",
        isinstance(mp, list) and len(mp) > 0,
        f"got {mp!r}",
    ))
    results.append(Assertion(
        "inventory.evidence_basis matches the documented line",
        inv.get("evidence_basis") == EXPECTED_EVIDENCE_BASIS,
        f"got {inv.get('evidence_basis')!r}",
    ))
    return results


# ---------------------------------------------------------------------------
# Positive chain.
# ---------------------------------------------------------------------------


def _run_positive_chain(td: Path) -> tuple[bool, list[Assertion]]:
    """Build the positive workspace, drive every script in the chain,
    and return ``(ok, assertions)``. ``ok`` is True iff every script
    returned rc=0 AND every assertion held."""
    print("--- positive proof ---")
    workspace = td / "workspace"
    fixtures = _build_positive_workspace(workspace)
    print(f"  workspace: {workspace}")

    # Stage A — validate_source_image_assets.
    out_validate = _run(
        "validate_source_image_assets",
        [
            sys.executable, str(VALIDATE_SOURCE_IMAGE_ASSETS),
            "--workspace", str(workspace),
        ],
    )
    _print_outcome(out_validate)
    if not out_validate.ok:
        return False, [Assertion(
            "validate_source_image_assets returned rc=0",
            False,
            f"rc={out_validate.rc}; tail={out_validate.combined.splitlines()[-8:]!r}",
        )]

    # Stage B — smoke-level alignment + integrity assertions.
    alignment = _assert_alignment(workspace=workspace, fixtures=fixtures)

    # Stage C — materialize.
    out_materialize = _run(
        "materialize_image_assets",
        [
            sys.executable, str(MATERIALIZE_IMAGE_ASSETS),
            "--workspace", str(workspace),
            "--assets-dir", str(workspace / "input" / "assets"),
        ],
    )
    _print_outcome(out_materialize)
    if not out_materialize.ok:
        return False, alignment + [Assertion(
            "materialize_image_assets returned rc=0",
            False,
            f"rc={out_materialize.rc}; "
            f"tail={out_materialize.combined.splitlines()[-8:]!r}",
        )]

    # The materialized targets must now exist at the destination_path
    # leaves, byte-identical to the source assets.
    materialize_assertions: list[Assertion] = []
    for asset_id, src_path, dest_path, expected_bytes in (
        (SYNTHETIC_PNG_ASSET_ID, SYNTHETIC_PNG_LOCAL_PATH,
         SYNTHETIC_PNG_DEST_PATH, _TINY_PNG_BYTES),
        (SYNTHETIC_JPG_ASSET_ID, SYNTHETIC_JPG_LOCAL_PATH,
         SYNTHETIC_JPG_DEST_PATH, _TINY_JPEG_BYTES),
    ):
        leaf = workspace / dest_path
        ok = (
            leaf.is_file()
            and not leaf.is_symlink()
            and leaf.read_bytes() == expected_bytes
        )
        materialize_assertions.append(Assertion(
            f"materialize copied {asset_id!r} into "
            f"<workspace>/{dest_path} byte-identical to "
            f"<workspace>/{src_path}",
            ok,
            f"leaf={leaf}, is_file={leaf.is_file()}, "
            f"is_symlink={leaf.is_symlink()}",
        ))

    # Stage D — export_pptx.
    out_pptx = td / "deck.pptx"
    out_export = _run(
        "export_pptx",
        [
            sys.executable, str(EXPORT_PPTX),
            "--workspace", str(workspace),
            "--output", str(out_pptx),
        ],
    )
    _print_outcome(out_export)
    if not out_export.ok:
        return False, alignment + materialize_assertions + [Assertion(
            "export_pptx returned rc=0",
            False,
            f"rc={out_export.rc}; "
            f"tail={out_export.combined.splitlines()[-12:]!r}",
        )]

    pptx_assertions: list[Assertion] = []
    pptx_is_file = out_pptx.is_file() and not out_pptx.is_symlink()
    pptx_assertions.append(Assertion(
        "final PPTX exists as a regular non-symlink file",
        pptx_is_file,
        f"path={out_pptx}, is_file={out_pptx.is_file()}, "
        f"is_symlink={out_pptx.is_symlink()}",
    ))
    if pptx_is_file:
        size = out_pptx.stat().st_size
        pptx_assertions.append(Assertion(
            "final PPTX is non-empty",
            size > 0, f"size={size}",
        ))
        pptx_assertions.extend(
            _assert_pptx_embeds_internal_media_only(out_pptx)
        )

    # Stage E — validate_pptx_contract --expected-slide-count.
    expected_slide_count = len(fixtures["deck_plan"]["slides"])
    out_contract = _run(
        "validate_pptx_contract",
        [
            sys.executable, str(VALIDATE_PPTX_CONTRACT),
            "--pptx", str(out_pptx),
            "--expected-slide-count", str(expected_slide_count),
        ],
    )
    _print_outcome(out_contract)

    # Stage F — inspect_pptx_inventory.
    inventory_out = td / "inventory.json"
    out_inspect = _run(
        "inspect_pptx_inventory",
        [
            sys.executable, str(INSPECT_PPTX_INVENTORY),
            "--pptx", str(out_pptx),
            "--out", str(inventory_out),
        ],
    )
    _print_outcome(out_inspect)

    contract_assertion = Assertion(
        f"validate_pptx_contract passes with "
        f"--expected-slide-count {expected_slide_count} (every "
        f"container + relationships allow-list + "
        f"minimal_evidence.every_slide_has_native_shape + "
        f"minimal_evidence.not_all_image_slide + "
        f"minimal_evidence.editable_text + slide_count.expected gate)",
        out_contract.ok,
        f"rc={out_contract.rc}; "
        f"tail={out_contract.combined.splitlines()[-12:]!r}",
    )
    inspect_assertion = Assertion(
        "inspect_pptx_inventory returned rc=0",
        out_inspect.ok,
        f"rc={out_inspect.rc}; "
        f"tail={out_inspect.combined.splitlines()[-12:]!r}",
    )
    inventory_assertions = _assert_inventory_contract(
        inventory_path=inventory_out,
        expected_slide_count=expected_slide_count,
    )

    final = (
        alignment
        + materialize_assertions
        + pptx_assertions
        + [contract_assertion, inspect_assertion]
        + inventory_assertions
    )
    ok = all(a.ok for a in final)
    return ok, final


# ---------------------------------------------------------------------------
# Negative probes. Each probe builds its own tempdir workspace as a
# minimal perturbation of the positive baseline and asserts the
# documented gate fires with the documented diagnostic.
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    name: str
    ok: bool
    detail: str = ""


def _seed_minimal_registry_workspace(
    td: Path, *, registry_overrides: dict | None = None,
    place_source_bytes: bool = True,
    image_manifest_overrides: dict | None = None,
    source_manifest_overrides: dict | None = None,
) -> Path:
    """Build a minimal positive workspace and apply targeted overrides.
    Returns the workspace path. The caller is expected to perturb the
    workspace AFTER this function returns when a probe needs a more
    invasive change (symlinks, missing files, etc.)."""
    workspace = td / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "input" / "assets").mkdir(parents=True, exist_ok=True)
    if place_source_bytes:
        (workspace / "input" / "assets"
         / f"{SYNTHETIC_PNG_ASSET_ID}.png").write_bytes(_TINY_PNG_BYTES)
    _write_source_manifest(workspace)
    if source_manifest_overrides:
        sm = json.loads(
            (workspace / "source_manifest.json").read_text()
        )
        sm.update(source_manifest_overrides)
        _write_json(workspace / "source_manifest.json", sm)
    # One-asset registry (PNG only) — simpler perturbations.
    registry = {
        "schema_version": "1",
        "assets": [
            {
                "id": SYNTHETIC_PNG_ASSET_ID,
                "source_ref": SYNTHETIC_SOURCE_ID,
                "local_path": SYNTHETIC_PNG_LOCAL_PATH,
                "destination_path": SYNTHETIC_PNG_DEST_PATH,
                "media_type": "image/png",
                "byte_count": len(_TINY_PNG_BYTES),
                "sha256": _sha256(_TINY_PNG_BYTES),
            },
        ],
    }
    if registry_overrides:
        # Apply overrides at the assets[0] level (the common case).
        if "assets[0]" in registry_overrides:
            registry["assets"][0].update(registry_overrides["assets[0]"])
        # Top-level overrides.
        for k, v in registry_overrides.items():
            if k == "assets[0]":
                continue
            registry[k] = v
    _write_json(workspace / "source_image_assets.json", registry)
    image_manifest = {
        "images": [
            {
                "id": SYNTHETIC_PNG_ASSET_ID,
                "local_path": SYNTHETIC_PNG_DEST_PATH,
                "source": "local_asset",
                "alt_text": "Synthetic.",
                "intended_use": "spot illustration",
            },
        ],
    }
    if image_manifest_overrides:
        if "images[0]" in image_manifest_overrides:
            image_manifest["images"][0].update(
                image_manifest_overrides["images[0]"]
            )
        if image_manifest_overrides.get("drop_images_entry"):
            image_manifest["images"] = []
        if "extra_image" in image_manifest_overrides:
            image_manifest["images"].append(
                image_manifest_overrides["extra_image"]
            )
    _write_json(workspace / "image_manifest.json", image_manifest)
    return workspace


def _expect_validator_fail(
    name: str, *, workspace: Path, expected_substrings: list[str],
) -> ProbeResult:
    """Run ``validate_source_image_assets.py`` against ``workspace`` and
    assert rc != 0 AND every expected diagnostic substring appears in
    the combined output."""
    outcome = _run(
        "validate_source_image_assets",
        [
            sys.executable, str(VALIDATE_SOURCE_IMAGE_ASSETS),
            "--workspace", str(workspace),
        ],
    )
    detail_lines: list[str] = []
    if outcome.ok:
        detail_lines.append(
            f"rc=0 (expected non-zero); cmd={outcome.cmd!r}"
        )
    missing = [s for s in expected_substrings if s not in outcome.combined]
    if missing:
        detail_lines.append(
            f"expected diagnostic substring(s) {missing!r} not found "
            f"in output; tail={outcome.combined.splitlines()[-12:]!r}"
        )
    return ProbeResult(
        name=name, ok=not detail_lines,
        detail="; ".join(detail_lines),
    )


def _probe_missing_source_image() -> ProbeResult:
    """N1: validate_source_image_assets G7 fires when the file at
    ``<workspace>/<local_path>`` is absent."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n1_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, place_source_bytes=False,
        )
        return _expect_validator_fail(
            "N1: missing source image file -> G7 refuses",
            workspace=workspace,
            expected_substrings=["G7", "file not present"],
        )


def _probe_byte_count_mismatch() -> ProbeResult:
    """N2: G8 fires when declared byte_count != on-disk length."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n2_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, registry_overrides={
                "assets[0]": {
                    "byte_count": len(_TINY_PNG_BYTES) + 1,
                },
            },
        )
        return _expect_validator_fail(
            "N2: byte_count mismatch -> G8 refuses",
            workspace=workspace,
            expected_substrings=["G8", "byte_count"],
        )


def _probe_sha256_mismatch() -> ProbeResult:
    """N3: G8 fires when declared sha256 != on-disk sha256."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n3_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, registry_overrides={
                "assets[0]": {"sha256": "0" * 64},
            },
        )
        return _expect_validator_fail(
            "N3: sha256 mismatch -> G8 refuses",
            workspace=workspace,
            expected_substrings=["G8", "sha256"],
        )


def _probe_wrong_magic_bytes() -> ProbeResult:
    """N4: G9 fires when the file at .png path has JPEG bytes (i.e.,
    file extension says PNG but magic-byte signature is JPEG)."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n4_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, place_source_bytes=False,
        )
        # Put JPEG bytes at the .png path. Re-derive byte_count + sha256
        # so the G8 gate does not fire first (we want G9 to be the
        # named diagnostic).
        (workspace / "input" / "assets"
         / f"{SYNTHETIC_PNG_ASSET_ID}.png").write_bytes(_TINY_JPEG_BYTES)
        registry = json.loads(
            (workspace / "source_image_assets.json").read_text()
        )
        registry["assets"][0]["byte_count"] = len(_TINY_JPEG_BYTES)
        registry["assets"][0]["sha256"] = _sha256(_TINY_JPEG_BYTES)
        _write_json(workspace / "source_image_assets.json", registry)
        return _expect_validator_fail(
            "N4: wrong magic bytes (PNG path with JPEG bytes) -> "
            "G9 refuses",
            workspace=workspace,
            expected_substrings=["G9", "magic-byte signature"],
        )


def _probe_source_ref_mismatch() -> ProbeResult:
    """N5: G4 fires when source_ref != source_manifest.source.id."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n5_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, registry_overrides={
                "assets[0]": {"source_ref": "different_source_id"},
            },
        )
        return _expect_validator_fail(
            "N5: source_ref mismatch -> G4 refuses",
            workspace=workspace,
            expected_substrings=[
                "G4",
                "does not equal source_manifest.source.id",
            ],
        )


def _probe_image_manifest_missing_declared_id() -> ProbeResult:
    """N6: G13 fires when image_manifest does not declare the registry
    id."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n6_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, image_manifest_overrides={
                "images[0]": {
                    "id": "some_other_id",
                    "local_path": "assets/some_other_id.png",
                },
            },
        )
        return _expect_validator_fail(
            "N6: image_manifest missing declared id -> G13 refuses",
            workspace=workspace,
            expected_substrings=[
                "G13",
                "every registry asset must be declared",
            ],
        )


def _probe_slide_plan_undeclared_image_ref() -> ProbeResult:
    """N7: smoke-level cross-check refuses a slide_plan whose
    image_refs entry is not present in image_manifest.images[].id.

    The positive proof's _assert_alignment helper enforces
    ``slide_plan.image_refs ⊆ image_manifest.images[].id``; this probe
    perturbs the slide_plan to declare an id the manifest never names
    and re-runs the assertion against the perturbed workspace."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n7_") as raw_td:
        td = Path(raw_td)
        workspace = td / "workspace"
        fixtures = _build_positive_workspace(workspace)
        # Perturb slide_plan 01_two_column.json so its image_refs lists
        # an id the manifest does not declare.
        bad_id = "an_undeclared_image_ref_id"
        sp_path = workspace / "slide_plans" / "01_two_column.json"
        sp = json.loads(sp_path.read_text())
        sp["image_refs"] = [bad_id]
        _write_json(sp_path, sp)
        # Update the fixtures dict so the smoke-level cross-check sees
        # the perturbed slide_plan.
        fixtures["slide_plans"][0] = sp
        assertions = _assert_alignment(
            workspace=workspace, fixtures=fixtures,
        )
        # Find the slide_plan-image_refs assertion specifically.
        ar = next(
            (a for a in assertions
             if a.name.startswith(
                 "slide_plan.image_refs is a subset of image_manifest"
             )), None,
        )
        if ar is None:
            return ProbeResult(
                "N7: slide_plan undeclared image_ref -> "
                "smoke-level cross-check refuses",
                False, "alignment assertion not found",
            )
        ok = not ar.ok and bad_id in ar.detail
        return ProbeResult(
            "N7: slide_plan undeclared image_ref -> "
            "smoke-level cross-check refuses",
            ok,
            f"assertion.ok={ar.ok}, detail={ar.detail!r}",
        )


def _displayed(value: str) -> str:
    """Return the substring as it appears in the validator's stdout
    after the validator prints the value via ``f"{value!r}"``. Python's
    ``repr()`` doubles every backslash, so a Windows-drive-shaped value
    ``C:\\Windows\\System32\\config.png`` (single backslashes in the
    JSON-decoded string) shows up in stdout as
    ``C:\\\\Windows\\\\System32\\\\config.png`` (each ``\\`` doubled by
    repr). Stripping the outer single-quotes ``repr`` adds gives the
    exact character sequence to substring-search for. For values that
    contain no backslashes (``http://...``, ``file:///etc/passwd``,
    ``../escape.png``, etc.) this is a no-op and returns the original
    string."""
    return repr(value)[1:-1]


def _path_gate_markers(*, field: str, is_uri_scheme: bool) -> list[str]:
    """Return the gate-specific diagnostic phrases an unsafe ``field``
    path MUST trip beyond the schema pattern. The smoke asserts each
    independently so a regression that silences ONE gate (while
    leaving the others wired) is still caught.

      * schema pattern (universal): ``does not match pattern``
      * G5 path-safety (universal for paths): ``local_path_is_safe``
        AND ``(G5)`` — the runtime-side mirror of the schema regex
        that runs even when the schema is relaxed;
      * G11 URI-scheme runtime gate (URI-scheme cases only):
        ``URI scheme`` AND ``(G11`` — fires for ``http://`` /
        ``https://`` / ``file://`` / ``data:`` / ``C:`` (Windows-drive
        prefix that matches the RFC-3986 scheme regex).

    Without these gate-specific markers the smoke would over-claim:
    every unsafe path happens to trip the schema today, so anchoring
    on ``does not match pattern`` alone would still pass even if G5 /
    G11 were silently demoted. Asserting each gate's phrase
    independently is what pins the contract to the documented gates,
    not to whichever one happens to fire first."""
    markers = [
        "does not match pattern",   # schema pattern (universal)
        "local_path_is_safe",       # G5 runtime
        "(G5)",                     # G5 citation
    ]
    if is_uri_scheme:
        markers.extend([
            "URI scheme",           # G11 runtime
            "(G11",                 # G11 citation (opening paren only;
                                    # the diagnostic uses "(G11 — ...)")
        ])
    # field is captured by the caller via the per-call expected list.
    return markers


def _probe_unsafe_path(
    local_path: str, label: str, *, is_uri_scheme: bool,
) -> ProbeResult:
    """N8 (parameterised): schema pattern + G5 + (G11 for URI-scheme
    cases) all refuse unsafe ``local_path`` shapes. The expected
    diagnostic must name the ``local_path`` field, the unsafe value
    verbatim (in its repr-displayed form so Windows-drive
    backslash-escaping matches), AND every per-gate phrase
    ``_path_gate_markers`` returns for this case.

    Anchoring on the schema marker alone would over-claim — G7
    (``file not present``) emits the same field + value on the
    perturbed path, so the smoke must independently prove G5 (and,
    when applicable, G11) fired to verify the actual path-safety
    contract, not just whichever gate happens to fire first."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n8_") as raw_td:
        td = Path(raw_td)
        # Override the local_path with the unsafe value. The schema
        # pattern + G5 + (G11 URI scheme) gates combine to refuse
        # every unsafe shape.
        workspace = _seed_minimal_registry_workspace(
            td, registry_overrides={
                "assets[0]": {"local_path": local_path},
            },
        )
        return _expect_validator_fail(
            f"N8: unsafe local_path {label!r} ({local_path!r}) -> "
            f"validator refuses",
            workspace=workspace,
            expected_substrings=[
                "FAIL", "local_path", _displayed(local_path),
                *_path_gate_markers(
                    field="local_path", is_uri_scheme=is_uri_scheme,
                ),
            ],
        )


def _probe_unsafe_dest_path(
    dest_path: str, label: str, *, is_uri_scheme: bool,
) -> ProbeResult:
    """N8 (parameterised, destination_path side): same gates apply.
    The expected diagnostic must name the ``destination_path`` field,
    the unsafe value verbatim, AND every per-gate phrase
    ``_path_gate_markers`` returns for this case.

    Anchoring on the schema marker alone would over-claim — G10
    alignment (``does not equal image_manifest entry local_path``)
    emits the same field + value, so the smoke must independently
    prove G5 (and, when applicable, G11) fired to verify the actual
    path-safety contract, not just G10's downstream alignment gate."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n8_dest_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, registry_overrides={
                "assets[0]": {"destination_path": dest_path},
            },
        )
        return _expect_validator_fail(
            f"N8: unsafe destination_path {label!r} ({dest_path!r}) "
            f"-> validator refuses",
            workspace=workspace,
            expected_substrings=[
                "FAIL", "destination_path", _displayed(dest_path),
                *_path_gate_markers(
                    field="destination_path",
                    is_uri_scheme=is_uri_scheme,
                ),
            ],
        )


def _probe_symlinked_source_file() -> ProbeResult:
    """N9: G6 fires when ``<workspace>/<local_path>`` is itself a
    symlink. The validator runs G5 (``_resolves_within``, which uses
    ``Path.resolve()`` and follows symlinks) BEFORE G6, so the symlink
    target must live INSIDE the workspace — otherwise G5 fires with
    'resolves outside --workspace' before G6 gets a chance. The symlink
    is still a symlink and G6 owns the deny."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n9_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, place_source_bytes=False,
        )
        # Real target inside the workspace AND inside input/assets/
        # (the only directory G5's startswith('input/assets/') gate
        # permits for local_path). Sibling filename keeps the schema-
        # locked relative path shape.
        real_target = (
            workspace / "input" / "assets" / "real_inside_target.png"
        )
        real_target.parent.mkdir(parents=True, exist_ok=True)
        real_target.write_bytes(_TINY_PNG_BYTES)
        leaf = workspace / SYNTHETIC_PNG_LOCAL_PATH
        try:
            leaf.symlink_to("real_inside_target.png")
        except (OSError, NotImplementedError):
            return ProbeResult(
                "N9: symlinked source file (scenario skipped on this "
                "platform)",
                True,
            )
        # Pin the diagnostic to the local_path leaf — G6 also fires on
        # parent / destination-parent symlinks with the same "G6 ...
        # symlink" wording, so requiring both ``local_path`` and the
        # exact leaf string is what proves the leaf-symlink branch (not
        # a sibling branch) is the one that tripped.
        return _expect_validator_fail(
            "N9: symlinked source file -> G6 refuses",
            workspace=workspace,
            expected_substrings=[
                "G6", "symlink", "local_path", SYNTHETIC_PNG_LOCAL_PATH,
            ],
        )


def _probe_symlinked_source_parent() -> ProbeResult:
    """N10: G6 fires when an intermediate segment between
    ``<workspace>`` and the source-asset leaf is a symlink. The
    symlink target must resolve INSIDE the workspace so G5 passes
    first; otherwise G5's 'resolves outside --workspace' diagnostic
    pre-empts G6."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n10_") as raw_td:
        td = Path(raw_td)
        # Build the workspace WITHOUT the seed creating an empty
        # ``input/assets`` directory.
        workspace = _seed_minimal_registry_workspace(
            td, place_source_bytes=False,
        )
        # Remove the empty ``input/assets`` directory the seed created
        # and replace it with a symlink to a sibling directory INSIDE
        # the workspace that holds the asset.
        (workspace / "input" / "assets").rmdir()
        real_assets = workspace / "real_inside_assets"
        real_assets.mkdir()
        (real_assets / f"{SYNTHETIC_PNG_ASSET_ID}.png").write_bytes(
            _TINY_PNG_BYTES
        )
        try:
            (workspace / "input" / "assets").symlink_to(
                "../real_inside_assets", target_is_directory=True,
            )
        except (OSError, NotImplementedError):
            return ProbeResult(
                "N10: symlinked source parent (scenario skipped on "
                "this platform)",
                True,
            )
        # Pin the diagnostic to the local_path parent chain — the
        # G6 parent-chain diagnostic explicitly carries the
        # "parent segment" wording AND the local_path field name,
        # which separates this case from the leaf-symlink (N9) and
        # destination-parent (N11) branches that share the same gate.
        return _expect_validator_fail(
            "N10: symlinked source parent directory -> G6 refuses",
            workspace=workspace,
            expected_substrings=[
                "G6", "symlink", "local_path", "parent segment",
            ],
        )


def _probe_symlinked_destination_parent() -> ProbeResult:
    """N11: G6 fires when an intermediate segment between
    ``<workspace>`` and the destination leaf is a symlink. As with
    N9 / N10, the symlink target must resolve INSIDE the workspace so
    G5's ``_resolves_within`` check passes first."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n11_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(td)
        # Build a real sibling directory INSIDE the workspace and
        # symlink ``assets`` -> sibling, so the destination_path parent
        # chain resolves inside the workspace (G5 passes) but
        # ``workspace/assets`` itself is a symlink (G6 fires).
        real_dest = workspace / "real_inside_dest"
        real_dest.mkdir()
        try:
            (workspace / "assets").symlink_to(
                "real_inside_dest", target_is_directory=True,
            )
        except (OSError, NotImplementedError):
            return ProbeResult(
                "N11: symlinked destination parent (scenario skipped "
                "on this platform)",
                True,
            )
        # Pin the diagnostic to the destination_path side — the G6
        # parent-chain diagnostic carries the field name
        # ``destination_path`` AND the "parent segment" wording, which
        # separates this case from the local_path symlink branches
        # (N9 leaf / N10 parent).
        return _expect_validator_fail(
            "N11: symlinked destination parent directory -> G6 refuses",
            workspace=workspace,
            expected_substrings=[
                "G6", "symlink", "destination_path", "parent segment",
            ],
        )


def _probe_unsupported_media_type(
    media_type: str, ext: str, label: str,
) -> ProbeResult:
    """N12 (parameterised): schema enum + G9 refuse media types and
    extensions outside the PNG / JPG / JPEG embed surface. The
    expected diagnostic must name BOTH the ``media_type`` field AND
    the unsupported media-type value verbatim — that pins the failure
    to this probe's perturbation instead of letting a coincidental
    unrelated FAIL (e.g. a missing-file G7 hit on the .svg/.gif leaf
    we never wrote) false-pass."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n12_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, registry_overrides={
                "assets[0]": {
                    "media_type": media_type,
                    "local_path": f"input/assets/x.{ext}",
                    "destination_path": f"assets/x.{ext}",
                },
            },
        )
        return _expect_validator_fail(
            f"N12: unsupported media_type {label!r} ({media_type!r}, "
            f"ext .{ext}) -> validator refuses",
            workspace=workspace,
            expected_substrings=["FAIL", "media_type", media_type],
        )


def _probe_public_distribution_wording(bad_id: str) -> ProbeResult:
    """N13 (parameterised): G12 fires on canonical-form combinations of
    ``public`` + propagation verb. Each candidate is documented in the
    policy and validated by validate_source_image_assets G12. The
    expected diagnostic must name BOTH G12 AND the perturbed id
    verbatim — that pins the failure to this probe's perturbation
    instead of letting an unrelated G12 hit (e.g. a future bad
    fixture token in another field) false-pass."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n13_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, registry_overrides={
                "assets[0]": {"id": bad_id},
            },
        )
        return _expect_validator_fail(
            f"N13: public-distribution wording {bad_id!r} in id "
            f"-> G12 refuses",
            workspace=workspace,
            expected_substrings=["G12", bad_id],
        )


def _probe_credential_shaped_string(
    label: str, payload: str, field: str, *, is_uri_scheme: bool,
) -> ProbeResult:
    """N14 (parameterised): the schema patterns and the G11 URI-scheme
    runtime gate refuse the credential shapes the registry validator
    owns today. ``field`` is one of ``id`` / ``source_ref`` —
    credentials in paths trip the path-pattern instead.

    The expected diagnostic must name the field, the credential
    payload verbatim, AND every gate-specific phrase the
    credential-rejection contract carries:

      * schema id/source_ref pattern (universal for every credential
        in this smoke): ``does not match pattern`` — the schema
        regex ``^[A-Za-z0-9][A-Za-z0-9_.\\-]*$`` refuses ``:`` /
        space / leading ``-`` shapes;
      * G11 URI-scheme runtime gate (RFC-3986 scheme-prefix
        credentials only): ``URI scheme`` AND ``(G11`` — fires for
        ``password:`` and ``secret:`` (pure-letter prefix before
        ``:``). ``api_key:`` contains ``_``, which is OUTSIDE RFC
        3986's scheme charset ``[A-Za-z][A-Za-z0-9+.\\-]*``, so G11
        does NOT fire on it — the schema id pattern alone refuses
        ``api_key:``. ``Bearer abc`` and ``-----BEGIN PRIVATE
        KEY-----`` carry no ``:``-terminated scheme prefix and
        likewise never reach G11.

    Without the gate-specific markers the probe would over-claim:
    G13 (``every registry asset must be declared``) also fires on
    the perturbed id with the same field + value, so anchoring on
    ``does not match pattern`` alone would still let a regression
    that silently demoted the schema id pattern + G11 slip past as
    long as G13 still fires. The independent markers pin the
    contract to the credential-rejection gates, not to whichever
    downstream gate happens to also fire.

    The credential probes deliberately cover only the shapes the
    validator's current gates own. Credential shapes outside that
    surface — e.g. cloud access-key-looking values made only of
    letters/digits, which therefore pass the schema id pattern + every
    runtime gate today — are intentionally NOT included; refusing them
    would require a new gate this validator does not own."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_n14_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, registry_overrides={
                "assets[0]": {field: payload},
            },
        )
        expected = ["FAIL", field, payload, "does not match pattern"]
        if is_uri_scheme:
            expected.extend(["URI scheme", "(G11"])
        return _expect_validator_fail(
            f"N14: credential-shaped {label!r} in {field} -> "
            f"validator refuses",
            workspace=workspace,
            expected_substrings=expected,
        )


# ---------------------------------------------------------------------------
# Self-test entry point.
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    """Build the positive workspace, drive the chain, and run every
    documented negative probe. Returns 0 iff every positive assertion
    held AND every negative probe's documented gate fired."""
    print("=== source-image-asset acceptance smoke "
          "(mock chain; real D-One UNVERIFIED) ===")
    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    scripts_before = _snapshot_dir(REPO_ROOT / "scripts")

    with tempfile.TemporaryDirectory(
        prefix="szh_source_image_asset_acceptance_smoke_",
    ) as raw_td:
        td = Path(raw_td)
        print(f"  tempdir: {td}")
        print()
        positive_ok, positive_results = _run_positive_chain(td)
        print()
        print("--- positive assertions ---")
        fails = 0
        for a in positive_results:
            mark = "PASS" if a.ok else "FAIL"
            suffix = f" -- {a.detail}" if not a.ok and a.detail else ""
            print(f"  [{mark}] {a.name}{suffix}")
            if not a.ok:
                fails += 1
        print()
        if not positive_ok or fails:
            print(
                f"FAIL: positive proof did not hold "
                f"({fails} assertion(s) failed).",
                file=sys.stderr,
            )
            _check_repo_unchanged(examples_before, scripts_before)
            return 1

    print("--- negative probes ---")
    probes: list[ProbeResult] = []
    probes.append(_probe_missing_source_image())
    probes.append(_probe_byte_count_mismatch())
    probes.append(_probe_sha256_mismatch())
    probes.append(_probe_wrong_magic_bytes())
    probes.append(_probe_source_ref_mismatch())
    probes.append(_probe_image_manifest_missing_declared_id())
    probes.append(_probe_slide_plan_undeclared_image_ref())
    # ``is_uri_scheme`` is true for shapes whose first character matches
    # the RFC-3986 scheme regex ``^[A-Za-z][A-Za-z0-9+.\-]*:`` —
    # ``http:`` / ``https:`` / ``file:`` / ``data:`` / ``C:`` all do;
    # ``//`` / ``..`` / ``/`` do not. The flag drives which gate
    # markers ``_path_gate_markers`` emits (G11 only fires on URI-
    # scheme cases).
    for label, path, is_uri_scheme in (
        ("http URL", "http://example.com/x.png", True),
        ("https URL", "https://example.com/x.png", True),
        ("file URL", "file:///etc/passwd", True),
        ("data URI", "data:image/png;base64,AAAA", True),
        ("protocol-relative", "//attacker.example/x.png", False),
        ("parent traversal", "../escape.png", False),
        ("POSIX absolute", "/etc/passwd", False),
        ("Windows drive", "C:\\Windows\\System32\\config.png", True),
    ):
        probes.append(_probe_unsafe_path(
            path, label, is_uri_scheme=is_uri_scheme,
        ))
    for label, path, is_uri_scheme in (
        ("http URL", "http://example.com/x.png", True),
        ("file URL", "file:///etc/passwd", True),
        ("parent traversal", "../escape.png", False),
        ("POSIX absolute", "/etc/passwd", False),
        ("Windows drive", "C:\\Windows\\System32\\config.png", True),
    ):
        probes.append(_probe_unsafe_dest_path(
            path, label, is_uri_scheme=is_uri_scheme,
        ))
    probes.append(_probe_symlinked_source_file())
    probes.append(_probe_symlinked_source_parent())
    probes.append(_probe_symlinked_destination_parent())
    for media_type, ext, label in (
        ("image/svg+xml", "svg", "SVG"),
        ("image/gif", "gif", "GIF"),
        ("image/webp", "webp", "WebP"),
        ("image/tiff", "tiff", "TIFF"),
        ("image/bmp", "bmp", "BMP"),
        ("image/x-icon", "ico", "ICO"),
    ):
        probes.append(_probe_unsupported_media_type(media_type, ext, label))
    for bad_id in (
        "public_upload",
        "public_upload_asset",
        "share_publicly",
        "public_url_for_assets",
        "upload_to_public_bucket",
        "public-share",
        "publicly_shared",
        "public_distribution",
        "Public_Upload",
        "share.publicly",
    ):
        probes.append(_probe_public_distribution_wording(bad_id))
    # ``is_uri_scheme`` is true ONLY when the credential's prefix
    # matches the RFC-3986 scheme regex ``^[A-Za-z][A-Za-z0-9+.\-]*:``
    # that G11 (and ``validate_scaffold._URI_SCHEME_PREFIX``) uses.
    # That charset does NOT include ``_``, so ``api_key:`` (which
    # contains ``_``) is refused by the schema id pattern alone — G11
    # does not fire on it because the scheme-prefix regex fails on the
    # underscore. ``password:`` / ``secret:`` (pure letters before
    # ``:``) DO match the scheme regex and G11 fires. ``Bearer abc`` /
    # ``-----BEGIN...`` carry no ``:``-terminated scheme prefix and
    # never reach G11.
    for label, payload, field, is_uri_scheme in (
        ("password: literal", "password:hunter2", "id", True),
        ("secret: literal", "secret:abc", "id", True),
        ("api_key: literal", "api_key:xyz", "id", False),
        ("Bearer with space", "Bearer abcdef0123", "id", False),
        ("PEM marker", "-----BEGIN PRIVATE KEY-----", "id", False),
        ("password: in source_ref", "password:hunter2", "source_ref", True),
    ):
        probes.append(_probe_credential_shaped_string(
            label, payload, field, is_uri_scheme=is_uri_scheme,
        ))

    fails = 0
    for r in probes:
        mark = "PASS" if r.ok else "FAIL"
        suffix = f" -- {r.detail}" if not r.ok and r.detail else ""
        print(f"  [{mark}] {r.name}{suffix}")
        if not r.ok:
            fails += 1

    rc_snapshot = _check_repo_unchanged(examples_before, scripts_before)
    if fails or rc_snapshot != 0:
        print(
            f"\nFAIL: {fails} negative probe(s) did not fire as "
            f"documented; snapshot rc={rc_snapshot}.",
            file=sys.stderr,
        )
        return 1

    print()
    print(
        "OK (self-test): source-image-asset acceptance smoke passed.\n"
        f"  Real D-One status: {REAL_D_ONE_STATUS}"
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Source-image-asset acceptance smoke: proves a caller-"
            "provided synthetic PNG + JPG source-attached image-asset "
            "pair authored under <workspace>/input/assets/<id>.<ext> "
            "passes scripts/validate_source_image_assets.py (G1-G13), "
            "aligns with source_manifest.json + image_manifest.json + "
            "slide_plans/*.json, is materialized by "
            "scripts/materialize_image_assets.py into "
            "<workspace>/assets/<id>.<ext>, is embedded by "
            "scripts/export_pptx.py into the produced .pptx as "
            "internal ppt/media/imageN.<ext> with NO external / "
            "file:// / data: / scheme-shaped relationships, "
            "re-validates against "
            "scripts/validate_pptx_contract.py with "
            "--expected-slide-count, and inspects through "
            "scripts/inspect_pptx_inventory.py with ok=true / "
            "findings=[] / non-empty media_parts / editable native "
            "shape evidence. Also runs negative probes for every "
            "documented fail-closed gate (missing source / byte_count "
            "mismatch / sha256 mismatch / wrong magic bytes / "
            "source_ref mismatch / image_manifest missing declared "
            "id / slide_plan undeclared image_ref / unsafe local_path "
            "or destination_path shapes / symlinked source / "
            "symlinked source parent / symlinked destination parent / "
            "unsupported media type or extension / public-distribution "
            "wording / credential-shaped strings). MOCK / stub "
            "acceptance only — NOT real D-One integration; no MCP, "
            "no public network, no model API, no image search, no "
            "Qoder, no browser, no external service."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run the positive proof end-to-end and every documented "
            "negative probe under tempfile.TemporaryDirectory(). The "
            "smoke has no other mode today; --self-test is required."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: source_image_asset_acceptance_smoke.py requires "
            "--self-test (no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
