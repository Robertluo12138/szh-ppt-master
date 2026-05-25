#!/usr/bin/env python3
"""source_image_asset_pipeline_smoke.py

Clean-room, stdlib-only, tempdir-only acceptance smoke that proves the
local source-image asset path carries a caller-supplied PNG byte-for-
byte through ``scripts/run_explicit_pipeline.py`` into the editable
``.pptx`` as an internal ``ppt/media/*`` part, while the produced deck
still carries native editable text (i.e. the slide is NOT an all-image
fallback).

This smoke complements ``scripts/source_image_asset_acceptance_smoke.py``
(which exercises the read-only ``source_image_assets.json`` registry
surface end-to-end against a hand-built workspace plus a direct
``scripts/export_pptx.py`` invocation): the new smoke drives the
**explicit-input end-to-end orchestrator** instead — Stage 1-10 — so the
positive proof exercises the real prepare-then-pipeline chain a live
caller would run, plus the cross-stage materialize step. The byte-
identity claim (``sha256(workspace asset) == sha256(ppt/media/imageN)``)
is the load-bearing post-condition that proves no re-encode / metadata-
stamp / TOCTOU swap happened between disk and the embedded media part.

What the positive chain does (single ``tempfile.TemporaryDirectory()``):

  1. Build a synthetic 1-image fixture:
       * a tiny magic-byte-valid PNG payload inlined in this script;
       * a synthetic Markdown source body;
       * caller specs: ``plan_spec.json`` (2 slides: one cover that
         references the image, one key_message that does not — so the
         deck has at least one non-image slide and the cover itself
         still carries native editable text, keeping the
         ``not_all_image_slide`` + ``every_slide_has_native_shape``
         gates honest);
       * ``image_manifest_spec.json`` declaring one image whose
         ``local_path`` equals ``assets/<id>.png`` and whose ``source``
         is ``local_asset``;
       * a staging ``--assets-dir`` whose layout mirrors the workspace
         tree (``<staging>/assets/<id>.png`` carries the PNG bytes the
         pipeline must copy into ``<workspace>/assets/<id>.png``).
  2. Invoke ``scripts/run_explicit_pipeline.py`` once with the fixture
     plus ``--assets-dir <staging>``. The orchestrator runs Stage 1-6
     prep (including the Stage-5.5 materialize step the
     ``--assets-dir`` flag activates) and then Stage 7-10 (validate
     workspace, generate render_models, generate SVG previews, export
     PPTX, validate PPTX contract). The expected outcome is rc=0.
  3. Author the source-attached registry **after** the pipeline runs:
     copy the same PNG bytes to ``<workspace>/input/assets/<id>.png``
     (the canonical ``input/assets/<id>.<ext>`` propagation location
     declared in ``references/source-image-asset-policy.md``), then
     write ``<workspace>/source_image_assets.json`` whose single asset
     carries
       * ``id``               = image_manifest.images[].id;
       * ``source_ref``       = source_manifest.source.id (G4);
       * ``local_path``       = ``input/assets/<id>.png`` (G5/G7/G8/G9);
       * ``destination_path`` = ``assets/<id>.png`` = image_manifest
                                local_path (G10);
       * ``media_type``       = ``image/png`` (G9);
       * ``byte_count``       = actual on-disk length (G8);
       * ``sha256``           = lowercase hex sha256 of the bytes (G8).
     Run ``scripts/validate_source_image_assets.py --workspace
     <workspace>`` and expect rc=0 — every G1..G13 gate passes against
     a workspace that already ships ``source_manifest.json`` +
     ``image_manifest.json`` from the pipeline run.
  4. Open the produced ``.pptx`` as a ZIP and assert:
       * at least one part exists under ``ppt/media/`` whose extension
         is ``.png`` (the PPTX embed surface the exporter supports for
         the synthetic PNG asset);
       * the sha256 of those bytes equals the sha256 of the source
         asset (the load-bearing byte-identity proof — proves the
         materialize step copied byte-for-byte AND the exporter
         embedded byte-for-byte, with no re-encode / metadata-stamp
         / TOCTOU swap);
       * every ``.rels`` Relationship Target is internal (no URI
         scheme, no ``TargetMode="External"``).
  5. Re-validate the PPTX with ``scripts/validate_pptx_contract.py
     --pptx <out> --expected-slide-count 2``; assert rc=0 AND every
     listed ``minimal_evidence.editable_text`` /
     ``minimal_evidence.not_all_image_slide`` /
     ``minimal_evidence.every_slide_has_native_shape`` /
     ``minimal_evidence.no_blank_slide`` line appears as ``[PASS]``.
  6. Run ``scripts/inspect_pptx_inventory.py --pptx <out> --out
     <inventory.json>``; assert rc=0 AND the inventory body carries
     ``ok=true`` / ``findings=[]`` / ``slide_count==2`` /
     ``media_parts`` non-empty / the documented ``evidence_basis``
     framing line / per-media-part sha256 matching the source asset
     sha256 / no relationship with an external ``TargetMode`` or
     URI-scheme ``Target``.

Negative probes (each runs in its own ``tempfile.TemporaryDirectory()``;
each expects fail-closed behavior on a documented perturbation):

  N1   source sha256 mismatch in registry
        ``validate_source_image_assets`` G8 fires when the declared
        ``sha256`` does not match the on-disk bytes.

  N2   source file is a symlink
        G6 fires when ``<workspace>/<local_path>`` is itself a
        symlink (broken or resolvable).

  N3   source parent is a symlink
        G6 fires when an intermediate segment between ``<workspace>``
        and the source-asset leaf is a symlink.

  N4a  unsafe registry local_path (parent traversal)
        schema pattern + G5 refuse ``../escape.png`` shapes.

  N4b  unsafe registry local_path (URI scheme)
        schema pattern + G5 + G11 refuse ``http://attacker/x.png``.

  N5   image_manifest is present but missing the registry id
        G13 fires (every registry id must be declared in
        image_manifest.images[].id).

  N6   unsupported media type / extension
        schema enum + G9 refuse ``image/svg+xml`` / ``image/gif`` /
        ``image/webp`` / ``image/tiff`` / ``image/bmp`` / etc.

  N7   public-upload wording in the registry id
        G12 fires on the canonical form combination of ``public`` +
        any of ``upload`` / ``share`` / ``url`` / ``publish`` etc.

  N8   PPTX media sha256 mismatch
        Inject by repacking the positive-path PPTX with one byte
        flipped inside the embedded ``ppt/media/imageN.png`` part.
        The smoke's own
        ``_assert_pptx_media_matches_source_sha`` post-condition must
        detect the drift — that's the regression gate for a
        production exporter that silently re-encodes / re-strips /
        metadata-stamps media bytes between the workspace and the
        package.

Snapshot check: every scenario runs under
``tempfile.TemporaryDirectory()``; flat-bytes snapshots of
``REPO_ROOT/examples/`` AND ``REPO_ROOT/scripts/`` taken before and
after the run must match — proves no generated artifact (PNG / PPTX /
render_models / svg_previews / reports / ``__pycache__``) lands under
any committed repo surface.

Fail-closed: any chain step exiting non-zero on the positive path, any
documented post-condition failing, or any negative probe whose gate
does NOT fire as documented aborts the smoke immediately and the
script exits non-zero with a clear per-assertion / per-probe
diagnostic.

**MOCK / STUB ONLY — NOT real D-One integration.** Nothing in this
script calls D-One, MCP, Qoder, a public network, telemetry, any model
API, an image search, a browser, or any external service. The PNG
bytes are a minimal magic-byte-valid local payload inlined in this
script; it is not a photographically meaningful image. The final
summary states explicitly that real D-One remains UNVERIFIED.

Stdlib-only.
"""
from __future__ import annotations

import sys

# Refuse to write `.pyc` files for any module imported by this script.
# The repo-immutability snapshot below baselines `REPO_ROOT/scripts/`
# AFTER `main()` starts; without this gate, a downstream import could
# silently land `scripts/__pycache__/<module>.cpython-*.pyc` before the
# snapshot fires, and the gate would miss the write entirely. Must come
# BEFORE any first-party import; the interpreter checks the flag at
# bytecode-write time. ``PYTHONDONTWRITEBYTECODE=1`` in the env achieves
# the same thing for callers that remember it; the in-script flip closes
# the hole unconditionally.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import zipfile  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402
from xml.etree import ElementTree as ET  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
TEMPLATES_DIR = REPO_ROOT / "templates" / "layouts"

RUN_EXPLICIT_PIPELINE = SCRIPTS_DIR / "run_explicit_pipeline.py"
VALIDATE_SOURCE_IMAGE_ASSETS = SCRIPTS_DIR / "validate_source_image_assets.py"
VALIDATE_PPTX_CONTRACT = SCRIPTS_DIR / "validate_pptx_contract.py"
INSPECT_PPTX_INVENTORY = SCRIPTS_DIR / "inspect_pptx_inventory.py"

# Must match scripts/inspect_pptx_inventory.py::EVIDENCE_BASIS verbatim.
EXPECTED_EVIDENCE_BASIS = (
    "OOXML structure only; not proof of full PowerPoint editability"
)

# OOXML namespace for the Relationships parts the smoke walks.
_NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

# Any string with a leading RFC-3986 scheme followed by ':' counts as an
# external Target. Internal package targets (``../media/image1.png``,
# ``slides/slide1.xml``) carry no scheme prefix.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Synthetic, magic-byte-valid 1x1 PNG: 8-byte signature + IHDR + IDAT +
# IEND. Same shape other smokes in this repo use for synthetic test
# payloads. Not claimed to be photographically meaningful — only the
# byte-identity / magic-byte / sha256 properties are load-bearing.
_TINY_PNG_BYTES: bytes = bytes.fromhex(
    "89504e470d0a1a0a"
    "0000000d49484452"
    "0000000100000001"
    "08060000001f15c489"
    "0000000d49444154"
    "789c6300010000000500010d0a2db4"
    "0000000049454e44ae426082"
)

# Synthetic identifiers. Each id collapses under the G12 canonical-form
# rule to a marker-free shape (``synthetic_*`` contains neither
# ``public`` nor a propagation-verb marker).
SYNTHETIC_SOURCE_ID = "synthetic_pipeline_source"
SYNTHETIC_IMAGE_ID = "pipeline_image_alpha"
SYNTHETIC_TITLE = "Pipeline Smoke Cover"
SYNTHETIC_AUDIENCE = "Internal smoke audience"
SYNTHETIC_OBJECTIVE = (
    "Exercise the source-image asset path end-to-end through "
    "run_explicit_pipeline."
)
SYNTHETIC_KEY_MESSAGE_TITLE = "Pipeline Smoke Key Message"


REAL_D_ONE_STATUS = (
    "UNVERIFIED — real D-One is NOT called by this smoke. The synthetic "
    "PNG bytes are a minimal magic-byte-valid local payload inlined in "
    "this script; nothing here calls D-One, MCP, Qoder, a public "
    "network, telemetry, any model API, an image search, a browser, or "
    "any external service."
)


# ---------------------------------------------------------------------------
# Snapshot helpers — prove the smoke writes nothing under REPO_ROOT.
# ---------------------------------------------------------------------------


def _snapshot_dir(d: Path) -> dict[str, bytes]:
    """Flat path -> bytes map of every regular file under ``d``. Mirrors
    the same gate ``scripts/acceptance_smoke.py`` and
    ``scripts/source_image_asset_acceptance_smoke.py`` use."""
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


def _build_pipeline_fixture(td: Path) -> dict:
    """Author the smallest viable explicit-input fixture: synthetic
    Markdown body, a 2-slide deck plan (cover with one image_ref +
    key_message with no image), slide_plans, image_manifest_spec, and
    a staging ``--assets-dir`` mirroring the workspace tree.

    Two slides — not one — keep ``not_all_image_slide`` honest: the
    cover carries an ``image_slot`` AND a title (so it has at least one
    text run), and the key_message slide carries native text only.
    Single-slide variants risk the gate counting a one-image cover as
    the only slide and conflating "this deck carries no images" with
    "this deck has no non-image slide", which would mask a regression
    in the editable-text gate."""
    td.mkdir(parents=True, exist_ok=True)
    source = td / "fixture_source.md"
    source.write_text(
        "# Pipeline Smoke Fixture Source\n\n"
        "Synthetic source body authored by the source-image asset "
        "pipeline smoke. No image bytes are extracted from this body; "
        "the asset bytes live separately in the caller-staged "
        "--assets-dir.\n",
        encoding="utf-8",
    )

    plan_spec = td / "plan_spec.json"
    _write_json(plan_spec, {
        "template": "business_review",
        "planning": {
            "planned_slide_count": 2,
            "rationale": (
                "Cover slide references one source-attached image; "
                "key_message slide carries native text only — keeps "
                "not_all_image_slide + every_slide_has_native_shape "
                "honest while still exercising the image-embed path."
            ),
        },
        "sections": [
            {
                "id": "intro",
                "title": "Intro",
                "summary": "Cover + key_message.",
                "slide_indices": [1, 2],
            },
        ],
        "slides": [
            {
                "index": 1,
                "layout": "cover",
                "title": SYNTHETIC_TITLE,
                "section_id": "intro",
                "summary": "Cover slide with source-attached image.",
                "density": "low",
                "source_refs": [SYNTHETIC_SOURCE_ID],
            },
            {
                "index": 2,
                "layout": "key_message",
                "title": SYNTHETIC_KEY_MESSAGE_TITLE,
                "section_id": "intro",
                "summary": "Single key-message slide; native text only.",
                "density": "low",
                "source_refs": [SYNTHETIC_SOURCE_ID],
            },
        ],
    })

    specs_dir = td / "specs"
    specs_dir.mkdir()
    _write_json(specs_dir / "01_cover.json", {
        "index": 1,
        "layout": "cover",
        "title": SYNTHETIC_TITLE,
        "blocks": [
            {"id": "title", "kind": "text", "content": SYNTHETIC_TITLE},
            {"id": "accent", "kind": "image_ref",
             "content": SYNTHETIC_IMAGE_ID},
        ],
        "image_refs": [SYNTHETIC_IMAGE_ID],
    })
    _write_json(specs_dir / "02_key_message.json", {
        "index": 2,
        "layout": "key_message",
        "title": SYNTHETIC_KEY_MESSAGE_TITLE,
        "blocks": [
            {
                "id": "message",
                "kind": "callout",
                "content": "Native editable text only; no image_ref.",
            },
        ],
    })

    image_manifest_spec = td / "image_manifest_spec.json"
    _write_json(image_manifest_spec, {
        "images": [
            {
                "id": SYNTHETIC_IMAGE_ID,
                "local_path": f"assets/{SYNTHETIC_IMAGE_ID}.png",
                "source": "local_asset",
                "alt_text": "Synthetic source-attached PNG marker.",
                "intended_use": "spot illustration",
            },
        ],
    })

    # Staging --assets-dir whose layout mirrors the workspace tree
    # relative to image_manifest_spec.images[].local_path. The
    # orchestrator's Stage-5.5 materialize step copies
    # <staging>/<local_path> -> <workspace>/<local_path>.
    staging = td / "staging"
    staging.mkdir()
    staged_leaf = staging / "assets" / f"{SYNTHETIC_IMAGE_ID}.png"
    staged_leaf.parent.mkdir(parents=True, exist_ok=True)
    staged_leaf.write_bytes(_TINY_PNG_BYTES)

    return {
        "source": source,
        "plan_spec": plan_spec,
        "specs_dir": specs_dir,
        "image_manifest_spec": image_manifest_spec,
        "assets_dir": staging,
        "asset_bytes": _TINY_PNG_BYTES,
        "asset_sha256": _sha256(_TINY_PNG_BYTES),
        "image_local_path": f"assets/{SYNTHETIC_IMAGE_ID}.png",
        "registry_local_path": f"input/assets/{SYNTHETIC_IMAGE_ID}.png",
        "registry_destination_path": f"assets/{SYNTHETIC_IMAGE_ID}.png",
    }


def _pipeline_args(
    fixture: dict, *, workspace: Path, output: Path,
) -> list[str]:
    return [
        sys.executable, str(RUN_EXPLICIT_PIPELINE),
        "--workspace", str(workspace),
        "--source", str(fixture["source"]),
        "--source-id", SYNTHETIC_SOURCE_ID,
        "--title", SYNTHETIC_TITLE,
        "--audience", SYNTHETIC_AUDIENCE,
        "--objective", SYNTHETIC_OBJECTIVE,
        "--plan-spec", str(fixture["plan_spec"]),
        "--slide-specs-dir", str(fixture["specs_dir"]),
        "--image-manifest-spec", str(fixture["image_manifest_spec"]),
        "--template-root", str(TEMPLATES_DIR),
        "--theme-from-template",
        "--assets-dir", str(fixture["assets_dir"]),
        "--output", str(output),
    ]


def _write_source_registry(workspace: Path, fixture: dict) -> dict:
    """Write ``<workspace>/source_image_assets.json`` AND place the
    asset bytes at ``<workspace>/input/assets/<id>.png`` so the
    read-only registry validator can run every G1..G13 gate against a
    workspace that already ships source_manifest.json (Stage 1) +
    image_manifest.json (Stage 6) from the pipeline run.

    The registry destination_path matches image_manifest local_path
    (G10); the registry local_path is the canonical
    ``input/assets/<id>.<ext>`` propagation location declared in
    references/source-image-asset-policy.md."""
    asset_bytes = fixture["asset_bytes"]
    source_local = workspace / fixture["registry_local_path"]
    source_local.parent.mkdir(parents=True, exist_ok=True)
    source_local.write_bytes(asset_bytes)
    registry = {
        "schema_version": "1",
        "assets": [
            {
                "id": SYNTHETIC_IMAGE_ID,
                "source_ref": SYNTHETIC_SOURCE_ID,
                "local_path": fixture["registry_local_path"],
                "destination_path": fixture["registry_destination_path"],
                "media_type": "image/png",
                "byte_count": len(asset_bytes),
                "sha256": fixture["asset_sha256"],
            },
        ],
    }
    _write_json(workspace / "source_image_assets.json", registry)
    return registry


# ---------------------------------------------------------------------------
# Positive-proof assertions.
# ---------------------------------------------------------------------------


@dataclass
class Assertion:
    name: str
    ok: bool
    detail: str = ""


def _open_pptx_zip(pptx: Path) -> zipfile.ZipFile:
    return zipfile.ZipFile(pptx, "r")


def _assert_pptx_media_matches_source_sha(
    pptx: Path, source_sha: str,
) -> list[Assertion]:
    """Open the PPTX as a ZIP and assert:

      * at least one PNG part exists under ``ppt/media/``;
      * every PNG part under ``ppt/media/`` has sha256 == ``source_sha``
        (the load-bearing byte-identity proof — proves the source
        bytes flowed verbatim through materialize AND export, with no
        re-encode / metadata-stamp / TOCTOU swap)."""
    results: list[Assertion] = []
    try:
        zf = _open_pptx_zip(pptx)
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
        results.append(Assertion(
            "PPTX embeds at least one ppt/media/ PNG part",
            len(png_parts) > 0,
            (f"found media: "
             f"{sorted(n for n in names if n.startswith('ppt/media/'))!r}"
             if not png_parts else ""),
        ))
        sha_mismatches: list[str] = []
        for n in png_parts:
            try:
                payload = zf.read(n)
            except (KeyError, OSError) as exc:
                sha_mismatches.append(
                    f"{n}: cannot read: {type(exc).__name__}: {exc}"
                )
                continue
            actual = _sha256(payload)
            if actual != source_sha:
                sha_mismatches.append(
                    f"{n}: sha256={actual!r}, expected={source_sha!r} "
                    f"(byte length={len(payload)})"
                )
        results.append(Assertion(
            "every ppt/media/ PNG sha256 equals the source asset sha256",
            not sha_mismatches,
            "; ".join(sha_mismatches),
        ))
    finally:
        zf.close()
    return results


def _assert_pptx_relationships_internal_only(
    pptx: Path,
) -> list[Assertion]:
    """Every ``.rels`` part's Target must carry no URI scheme AND no
    ``TargetMode="External"``."""
    results: list[Assertion] = []
    try:
        zf = _open_pptx_zip(pptx)
    except (zipfile.BadZipFile, OSError) as exc:
        results.append(Assertion(
            "PPTX opens as a ZIP for relationships walk",
            False, f"{type(exc).__name__}: {exc}",
        ))
        return results
    try:
        external: list[str] = []
        rel_tag = f"{{{_NS_REL}}}Relationship"
        for n in zf.namelist():
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
            "PPTX has no external / file:// / data: / URI-scheme "
            "relationships",
            not external,
            "; ".join(external),
        ))
    finally:
        zf.close()
    return results


def _assert_inventory_contract(
    *, inventory_path: Path, expected_slide_count: int,
    source_sha: str,
) -> list[Assertion]:
    """Assert inspect_pptx_inventory.json carries the documented gates
    + at least one media_parts entry whose sha256 equals the source
    asset sha256 (so the inventory readback corroborates the smoke's
    own zipfile sha check)."""
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
            False, f"{type(exc).__name__}: {exc}",
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
    is_list = isinstance(mp, list) and len(mp) > 0
    results.append(Assertion(
        "inventory.media_parts is a non-empty list",
        is_list, f"got {mp!r}",
    ))
    results.append(Assertion(
        "inventory.evidence_basis matches the documented line",
        inv.get("evidence_basis") == EXPECTED_EVIDENCE_BASIS,
        f"got {inv.get('evidence_basis')!r}",
    ))
    if is_list:
        matched = [
            entry for entry in mp
            if isinstance(entry, dict)
            and entry.get("sha256") == source_sha
            and isinstance(entry.get("part"), str)
            and entry["part"].startswith("ppt/media/")
        ]
        results.append(Assertion(
            "inventory has at least one ppt/media/ part whose sha256 "
            "matches the source asset sha256",
            len(matched) > 0,
            f"media_parts shas={[e.get('sha256') for e in mp]!r}, "
            f"source_sha={source_sha!r}",
        ))
    # The inventory does not expose a top-level external-rel counter;
    # ``findings == []`` already guarantees no rel was flagged with
    # ``relationships.external`` / ``relationships.file_uri`` /
    # ``relationships.absolute``, and the smoke's own zipfile walk gates
    # externality independently against the produced .rels XML.
    rels = inv.get("relationships")
    results.append(Assertion(
        "inventory.relationships is a list (presence gate; "
        "externality is enforced by inventory.findings == [] AND the "
        "smoke's own zipfile relationships walk)",
        isinstance(rels, list),
        f"got {type(rels).__name__}",
    ))
    return results


def _assert_contract_minimal_evidence_pass(
    outcome: ToolOutcome,
) -> list[Assertion]:
    """The contract validator emits one ``[PASS] <gate>: <file>`` line
    per gate. Anchor on the four ``minimal_evidence.*`` gates the goal
    pins (editable_text, not_all_image_slide, no_blank_slide,
    every_slide_has_native_shape) so a regression that silently demotes
    any one of them surfaces with a clear per-gate diagnostic instead
    of being masked by an overall rc=0."""
    results: list[Assertion] = []
    out = outcome.combined
    for gate in (
        "minimal_evidence.editable_text",
        "minimal_evidence.not_all_image_slide",
        "minimal_evidence.no_blank_slide",
        "minimal_evidence.every_slide_has_native_shape",
    ):
        marker = f"[PASS] {gate}"
        results.append(Assertion(
            f"validate_pptx_contract emits [PASS] for {gate}",
            marker in out,
            f"marker {marker!r} not in validator output; "
            f"tail={out.splitlines()[-12:]!r}",
        ))
    return results


# ---------------------------------------------------------------------------
# Positive chain.
# ---------------------------------------------------------------------------


def _run_positive_chain(
    td: Path,
) -> tuple[bool, list[Assertion], Path | None, str | None]:
    """Build the synthetic fixture, drive run_explicit_pipeline,
    author the source-attached registry, validate it, and assert every
    documented PPTX post-condition.

    Returns ``(ok, assertions, pptx_path, source_sha)`` so callers (the
    PPTX-tamper probe) can re-use the produced PPTX and the source
    sha. ``pptx_path`` / ``source_sha`` are None when the pipeline
    itself failed."""
    print("--- positive proof ---")
    fixture_dir = td / "fixture"
    workspace = td / "workspace"
    output = td / "pipeline.pptx"
    fixture = _build_pipeline_fixture(fixture_dir)
    print(f"  workspace:    {workspace}")
    print(f"  pptx output:  {output}")

    # Stage A — run_explicit_pipeline end-to-end (Stage 1-10 + the
    # Stage-5.5 materialize step).
    pipeline = _run(
        "run_explicit_pipeline (Stage 1-10 + materialize)",
        _pipeline_args(fixture, workspace=workspace, output=output),
    )
    _print_outcome(pipeline)
    if not pipeline.ok:
        return False, [Assertion(
            "run_explicit_pipeline returns rc=0",
            False,
            f"rc={pipeline.rc}; "
            f"tail={pipeline.combined.splitlines()[-15:]!r}",
        )], None, None

    pipeline_markers = [
        Assertion(
            "explicit pipeline emits OK success marker",
            "OK: explicit-input end-to-end run succeeded" in pipeline.stdout,
            "marker not found",
        ),
        Assertion(
            "explicit pipeline emits [PASS] materialize_image_assets",
            "[PASS] materialize_image_assets" in pipeline.stdout,
            "marker not found",
        ),
        Assertion(
            "explicit pipeline emits [PASS] init_image_manifest",
            "[PASS] init_image_manifest" in pipeline.stdout,
            "marker not found",
        ),
        Assertion(
            "explicit pipeline emits [PASS] export_pptx",
            "[PASS] export_pptx" in pipeline.stdout,
            "marker not found",
        ),
    ]

    # Stage B — workspace asset exists byte-identical to the staged
    # source. Mirrors materialize_image_assets's post-condition.
    workspace_asset = workspace / fixture["image_local_path"]
    asset_exists = (
        workspace_asset.is_file()
        and not workspace_asset.is_symlink()
        and workspace_asset.read_bytes() == fixture["asset_bytes"]
    )
    workspace_assertion = Assertion(
        "materialize copied the staged PNG into "
        "<workspace>/<image_manifest local_path> byte-identical to the "
        "--assets-dir source",
        asset_exists,
        f"workspace_asset={workspace_asset}, "
        f"is_file={workspace_asset.is_file()}, "
        f"is_symlink={workspace_asset.is_symlink()}",
    )

    # Stage C — author source-attached registry and run G1..G13.
    _write_source_registry(workspace, fixture)
    registry_validator = _run(
        "validate_source_image_assets",
        [
            sys.executable, str(VALIDATE_SOURCE_IMAGE_ASSETS),
            "--workspace", str(workspace),
        ],
    )
    _print_outcome(registry_validator)
    registry_assertion = Assertion(
        "validate_source_image_assets (G1..G13) returns rc=0 on a "
        "pipeline-produced workspace augmented with the source-"
        "attached registry",
        registry_validator.ok,
        f"rc={registry_validator.rc}; "
        f"tail={registry_validator.combined.splitlines()[-12:]!r}",
    )

    # Stage D — PPTX byte-identity assertions.
    pptx_assertions: list[Assertion] = []
    pptx_is_file = output.is_file() and not output.is_symlink()
    pptx_assertions.append(Assertion(
        "final PPTX exists as a regular non-symlink file",
        pptx_is_file,
        f"path={output}",
    ))
    if pptx_is_file:
        size = output.stat().st_size
        pptx_assertions.append(Assertion(
            "final PPTX is non-empty",
            size > 0, f"size={size}",
        ))
        pptx_assertions.extend(
            _assert_pptx_media_matches_source_sha(
                output, fixture["asset_sha256"],
            )
        )
        pptx_assertions.extend(
            _assert_pptx_relationships_internal_only(output)
        )

    # Stage E — validate_pptx_contract --expected-slide-count.
    expected_slide_count = 2
    contract = _run(
        "validate_pptx_contract --expected-slide-count",
        [
            sys.executable, str(VALIDATE_PPTX_CONTRACT),
            "--pptx", str(output),
            "--expected-slide-count", str(expected_slide_count),
        ],
    )
    _print_outcome(contract)
    contract_assertions = [
        Assertion(
            f"validate_pptx_contract --expected-slide-count "
            f"{expected_slide_count} returns rc=0",
            contract.ok,
            f"rc={contract.rc}; "
            f"tail={contract.combined.splitlines()[-15:]!r}",
        ),
    ]
    contract_assertions.extend(
        _assert_contract_minimal_evidence_pass(contract)
    )

    # Stage F — inspect_pptx_inventory.
    inventory_out = td / "inventory.json"
    inspect = _run(
        "inspect_pptx_inventory",
        [
            sys.executable, str(INSPECT_PPTX_INVENTORY),
            "--pptx", str(output),
            "--out", str(inventory_out),
        ],
    )
    _print_outcome(inspect)
    inspect_assertion = Assertion(
        "inspect_pptx_inventory returns rc=0",
        inspect.ok,
        f"rc={inspect.rc}; "
        f"tail={inspect.combined.splitlines()[-12:]!r}",
    )
    inventory_assertions = _assert_inventory_contract(
        inventory_path=inventory_out,
        expected_slide_count=expected_slide_count,
        source_sha=fixture["asset_sha256"],
    )

    final = (
        pipeline_markers
        + [workspace_assertion, registry_assertion]
        + pptx_assertions
        + contract_assertions
        + [inspect_assertion]
        + inventory_assertions
    )
    ok = all(a.ok for a in final)
    return ok, final, output, fixture["asset_sha256"]


# ---------------------------------------------------------------------------
# Negative probes. Each registry probe writes a minimal workspace (no
# pipeline run; just source_manifest + source_image_assets + asset
# bytes + image_manifest when needed) and asserts the named G* gate
# fires with the named diagnostic substrings. The PPTX-tamper probe
# reuses the positive PPTX.
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    name: str
    ok: bool
    detail: str = ""


def _seed_minimal_registry_workspace(
    td: Path,
    *,
    place_source_bytes: bool = True,
    place_image_manifest: bool = True,
    registry_overrides: dict | None = None,
    image_manifest_overrides: dict | None = None,
) -> Path:
    """Build a minimal positive-shape workspace (source_manifest +
    optional asset bytes at the registry local_path + registry +
    optional image_manifest) and apply targeted overrides. Caller
    perturbs the workspace AFTER this returns for symlink probes."""
    workspace = td / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    # source_manifest.json — required for G4.
    body = b"# Minimal probe source\n"
    (workspace / "input").mkdir(parents=True, exist_ok=True)
    (workspace / "input" / "source.md").write_bytes(body)
    _write_json(workspace / "source_manifest.json", {
        "schema_version": "1",
        "source": {
            "id": SYNTHETIC_SOURCE_ID,
            "local_path": "input/source.md",
            "kind": "markdown",
            "byte_count": len(body),
            "line_count": body.count(b"\n") + (
                0 if body.endswith(b"\n") else 1
            ),
            "sha256": _sha256(body),
        },
        "tool": {"name": "probe", "version": "1"},
    })

    # Always create the registry's local_path parent so probes that
    # need to perturb the parent chain (symlinks, etc.) can do so even
    # when ``place_source_bytes`` is False. The leaf itself is only
    # written when source bytes are requested.
    assets_parent = workspace / "input" / "assets"
    assets_parent.mkdir(parents=True, exist_ok=True)
    if place_source_bytes:
        leaf = assets_parent / f"{SYNTHETIC_IMAGE_ID}.png"
        leaf.write_bytes(_TINY_PNG_BYTES)

    # registry.
    registry = {
        "schema_version": "1",
        "assets": [
            {
                "id": SYNTHETIC_IMAGE_ID,
                "source_ref": SYNTHETIC_SOURCE_ID,
                "local_path": f"input/assets/{SYNTHETIC_IMAGE_ID}.png",
                "destination_path": f"assets/{SYNTHETIC_IMAGE_ID}.png",
                "media_type": "image/png",
                "byte_count": len(_TINY_PNG_BYTES),
                "sha256": _sha256(_TINY_PNG_BYTES),
            },
        ],
    }
    if registry_overrides and "assets[0]" in registry_overrides:
        registry["assets"][0].update(registry_overrides["assets[0]"])
    _write_json(workspace / "source_image_assets.json", registry)

    # image_manifest.json — required for G10/G13.
    if place_image_manifest:
        image_manifest = {
            "images": [
                {
                    "id": SYNTHETIC_IMAGE_ID,
                    "local_path": f"assets/{SYNTHETIC_IMAGE_ID}.png",
                    "source": "local_asset",
                    "alt_text": "Probe.",
                    "intended_use": "spot illustration",
                },
            ],
        }
        if image_manifest_overrides:
            if "images[0]" in image_manifest_overrides:
                image_manifest["images"][0].update(
                    image_manifest_overrides["images[0]"]
                )
            if image_manifest_overrides.get("drop_only_entry"):
                image_manifest["images"] = []
        _write_json(workspace / "image_manifest.json", image_manifest)

    return workspace


def _expect_validator_fail(
    name: str, *, workspace: Path, expected_substrings: list[str],
) -> ProbeResult:
    outcome = _run(
        "validate_source_image_assets",
        [
            sys.executable, str(VALIDATE_SOURCE_IMAGE_ASSETS),
            "--workspace", str(workspace),
        ],
    )
    diagnostic: list[str] = []
    if outcome.ok:
        diagnostic.append(
            f"rc=0 (expected non-zero); cmd={outcome.cmd!r}"
        )
    missing = [s for s in expected_substrings if s not in outcome.combined]
    if missing:
        diagnostic.append(
            f"expected diagnostic substring(s) {missing!r} not found in "
            f"output; tail={outcome.combined.splitlines()[-12:]!r}"
        )
    return ProbeResult(
        name=name, ok=not diagnostic, detail="; ".join(diagnostic),
    )


def _probe_sha256_mismatch() -> ProbeResult:
    """N1: G8 fires when declared sha256 != on-disk sha256."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_n1_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, registry_overrides={
                "assets[0]": {"sha256": "0" * 64},
            },
        )
        return _expect_validator_fail(
            "N1: registry sha256 mismatch -> G8 refuses",
            workspace=workspace,
            expected_substrings=["G8", "sha256"],
        )


def _probe_source_symlink() -> ProbeResult:
    """N2: G6 fires when the source local_path leaf is a symlink. The
    symlink target lives INSIDE the workspace so G5's _resolves_within
    (which follows symlinks) passes — only then does G6 see a symlink
    at the leaf and refuse with the documented diagnostic."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_n2_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, place_source_bytes=False,
        )
        real_target = (
            workspace / "input" / "assets" / "real_inside.png"
        )
        real_target.parent.mkdir(parents=True, exist_ok=True)
        real_target.write_bytes(_TINY_PNG_BYTES)
        leaf = workspace / "input" / "assets" / f"{SYNTHETIC_IMAGE_ID}.png"
        try:
            leaf.symlink_to("real_inside.png")
        except (OSError, NotImplementedError):
            return ProbeResult(
                "N2: source symlink (scenario skipped on this platform)",
                True,
            )
        return _expect_validator_fail(
            "N2: source leaf is a symlink -> G6 refuses",
            workspace=workspace,
            expected_substrings=[
                "G6", "symlink", "local_path",
            ],
        )


def _probe_source_symlink_parent() -> ProbeResult:
    """N3: G6 fires when an intermediate parent of the source local_path
    is a symlink. The target lives INSIDE the workspace so G5's
    within-workspace resolution check passes first."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_n3_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, place_source_bytes=False,
        )
        # Remove the empty seed dir and substitute a symlink pointing at
        # a real directory ALSO inside the workspace.
        (workspace / "input" / "assets").rmdir()
        real_assets = workspace / "real_inside_assets"
        real_assets.mkdir()
        (real_assets / f"{SYNTHETIC_IMAGE_ID}.png").write_bytes(
            _TINY_PNG_BYTES,
        )
        try:
            (workspace / "input" / "assets").symlink_to(
                "../real_inside_assets", target_is_directory=True,
            )
        except (OSError, NotImplementedError):
            return ProbeResult(
                "N3: source symlink parent (scenario skipped on this "
                "platform)",
                True,
            )
        return _expect_validator_fail(
            "N3: source parent segment is a symlink -> G6 refuses",
            workspace=workspace,
            expected_substrings=[
                "G6", "symlink", "local_path", "parent segment",
            ],
        )


def _probe_unsafe_local_path_traversal() -> ProbeResult:
    """N4a: schema pattern + G5 refuse a parent-traversal local_path."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_n4a_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, registry_overrides={
                "assets[0]": {"local_path": "../escape.png"},
            },
        )
        return _expect_validator_fail(
            "N4a: registry local_path '../escape.png' -> "
            "schema pattern + G5 refuse",
            workspace=workspace,
            expected_substrings=[
                "local_path", "does not match pattern",
                "local_path_is_safe", "(G5)",
            ],
        )


def _probe_unsafe_local_path_uri() -> ProbeResult:
    """N4b: schema pattern + G5 + G11 refuse a URI-shaped local_path."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_n4b_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, registry_overrides={
                "assets[0]": {"local_path": "http://attacker/x.png"},
            },
        )
        return _expect_validator_fail(
            "N4b: registry local_path 'http://attacker/x.png' -> "
            "schema pattern + G5 + G11 refuse",
            workspace=workspace,
            expected_substrings=[
                "local_path", "does not match pattern",
                "local_path_is_safe", "(G5)",
                "URI scheme", "(G11",
            ],
        )


def _probe_image_manifest_missing_id() -> ProbeResult:
    """N5: G13 fires when image_manifest is present but does not
    declare the registry asset's id."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_n5_") as raw_td:
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
            "N5: image_manifest does not declare registry id -> "
            "G13 refuses",
            workspace=workspace,
            expected_substrings=[
                "G13", "every registry asset must be declared",
            ],
        )


def _probe_unsupported_media_type() -> ProbeResult:
    """N6: schema enum (and G9) refuse media types outside the
    PNG/JPEG embed surface. The probe perturbs media_type only and
    leaves local_path's safe shape unchanged so the FAIL is pinned to
    the media-type gate."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_n6_") as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_registry_workspace(
            td, registry_overrides={
                "assets[0]": {
                    "media_type": "image/svg+xml",
                    "local_path": "input/assets/x.svg",
                    "destination_path": "assets/x.svg",
                },
            },
        )
        return _expect_validator_fail(
            "N6: unsupported media_type 'image/svg+xml' -> "
            "schema enum / G9 refuse",
            workspace=workspace,
            expected_substrings=["media_type", "image/svg+xml"],
        )


def _probe_public_upload_wording() -> ProbeResult:
    """N7: G12 fires on a canonical-form id combining 'public' with a
    propagation verb (here: upload). The probe perturbs id only so the
    diagnostic is pinned to G12 + the bad id rather than to a
    coincidental unrelated failure."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_n7_") as raw_td:
        td = Path(raw_td)
        bad_id = "public_upload_asset"
        workspace = _seed_minimal_registry_workspace(
            td, registry_overrides={
                "assets[0]": {"id": bad_id},
            },
            image_manifest_overrides={
                "images[0]": {"id": bad_id},
            },
        )
        return _expect_validator_fail(
            f"N7: public-upload wording {bad_id!r} in id -> G12 refuses",
            workspace=workspace,
            expected_substrings=["G12", bad_id],
        )


def _tamper_pptx_media(src: Path, dst: Path) -> bool:
    """Rewrite ``src`` to ``dst`` flipping one byte inside the first
    ``ppt/media/*.png`` part. Returns True on success. Used by N8 to
    inject a media-sha drift without touching the exporter."""
    try:
        with zipfile.ZipFile(src, "r") as zin:
            members = zin.namelist()
            target = next(
                (n for n in members
                 if n.startswith("ppt/media/") and n.lower().endswith(".png")),
                None,
            )
            if target is None:
                return False
            with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
                for n in members:
                    raw = zin.read(n)
                    if n == target:
                        if not raw:
                            return False
                        # Flip the last byte. PNG decoders may reject
                        # the tampered file, but the smoke only cares
                        # about the byte-identity gate — the post-
                        # condition runs sha256 on raw bytes inside the
                        # ZIP, never asks PowerPoint to render anything.
                        raw = raw[:-1] + bytes([raw[-1] ^ 0xFF])
                    zout.writestr(n, raw)
        return True
    except (zipfile.BadZipFile, OSError):
        return False


def _probe_pptx_media_sha_mismatch(
    pptx: Path, source_sha: str,
) -> ProbeResult:
    """N8: tamper the positive PPTX's media bytes and assert the
    smoke-level
    ``_assert_pptx_media_matches_source_sha`` post-condition flips to
    FAIL. This is the regression gate for an exporter that silently
    re-encodes / re-strips / metadata-stamps media bytes between the
    workspace asset and the embedded media part."""
    if not pptx.is_file():
        return ProbeResult(
            "N8: PPTX media sha mismatch (skipped — no positive PPTX)",
            False,
            "positive run did not produce a PPTX",
        )
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_n8_") as raw_td:
        td = Path(raw_td)
        tampered = td / "tampered.pptx"
        if not _tamper_pptx_media(pptx, tampered):
            return ProbeResult(
                "N8: PPTX media sha mismatch (skipped — tamper failed)",
                False,
                "no ppt/media/*.png entry available to tamper",
            )
        assertions = _assert_pptx_media_matches_source_sha(
            tampered, source_sha,
        )
        sha_check = next(
            (a for a in assertions
             if a.name.startswith("every ppt/media/ PNG sha256 equals")),
            None,
        )
        if sha_check is None:
            return ProbeResult(
                "N8: PPTX media sha mismatch -> smoke-level sha check "
                "refuses",
                False,
                "sha-check assertion not produced",
            )
        ok = not sha_check.ok and source_sha in sha_check.detail
        return ProbeResult(
            "N8: tampered PPTX media bytes -> smoke-level sha check "
            "refuses (byte-identity gate detects the drift)",
            ok,
            f"sha_check.ok={sha_check.ok}, detail={sha_check.detail!r}",
        )


# ---------------------------------------------------------------------------
# Self-test entry point.
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    print(
        "=== source-image-asset pipeline smoke "
        "(mock chain; real D-One UNVERIFIED) ==="
    )
    if not TEMPLATES_DIR.is_dir():
        print(
            f"FAIL: templates root not found at {TEMPLATES_DIR}; the "
            f"smoke requires the committed business_review template.",
            file=sys.stderr,
        )
        return 1
    if not RUN_EXPLICIT_PIPELINE.is_file():
        print(
            f"FAIL: scripts/run_explicit_pipeline.py not found at "
            f"{RUN_EXPLICIT_PIPELINE}",
            file=sys.stderr,
        )
        return 1
    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    scripts_before = _snapshot_dir(REPO_ROOT / "scripts")

    pptx_path: Path | None = None
    source_sha: str | None = None
    pptx_copy: Path | None = None
    persistent_dir = tempfile.mkdtemp(
        prefix="szh_sia_pipe_pptx_keep_",
    )
    try:
        with tempfile.TemporaryDirectory(
            prefix="szh_source_image_asset_pipeline_smoke_",
        ) as raw_td:
            td = Path(raw_td)
            print(f"  tempdir: {td}")
            print()
            positive_ok, positive_results, produced_pptx, sha = (
                _run_positive_chain(td)
            )
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
            # Copy the produced PPTX out of the tempdir so the N8 probe
            # can run against a stable path AFTER this TemporaryDirectory
            # is torn down.
            if produced_pptx is not None and produced_pptx.is_file():
                pptx_copy = Path(persistent_dir) / "pipeline.pptx"
                shutil.copyfile(produced_pptx, pptx_copy)
                pptx_path = pptx_copy
            source_sha = sha

        print("--- negative probes ---")
        probes: list[ProbeResult] = []
        probes.append(_probe_sha256_mismatch())
        probes.append(_probe_source_symlink())
        probes.append(_probe_source_symlink_parent())
        probes.append(_probe_unsafe_local_path_traversal())
        probes.append(_probe_unsafe_local_path_uri())
        probes.append(_probe_image_manifest_missing_id())
        probes.append(_probe_unsupported_media_type())
        probes.append(_probe_public_upload_wording())
        if pptx_path is not None and source_sha is not None:
            probes.append(
                _probe_pptx_media_sha_mismatch(pptx_path, source_sha)
            )
        else:
            probes.append(ProbeResult(
                "N8: PPTX media sha mismatch (skipped — no positive PPTX)",
                False,
                "positive run produced no PPTX to tamper",
            ))

        fails = 0
        for r in probes:
            mark = "PASS" if r.ok else "FAIL"
            suffix = f" -- {r.detail}" if not r.ok and r.detail else ""
            print(f"  [{mark}] {r.name}{suffix}")
            if not r.ok:
                fails += 1

        rc_snapshot = _check_repo_unchanged(
            examples_before, scripts_before,
        )
        if fails or rc_snapshot != 0:
            print(
                f"\nFAIL: {fails} negative probe(s) did not fire as "
                f"documented; snapshot rc={rc_snapshot}.",
                file=sys.stderr,
            )
            return 1

        print()
        print(
            "OK (self-test): source-image-asset pipeline smoke passed.\n"
            f"  Real D-One status: {REAL_D_ONE_STATUS}"
        )
        return 0
    finally:
        # Remove the kept PPTX copy. ``TemporaryDirectory`` already
        # handles the per-scenario tempdirs; this cleans up the
        # persistent copy we created for the N8 probe.
        try:
            shutil.rmtree(persistent_dir, ignore_errors=True)
        except OSError:
            pass


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Source-image-asset pipeline smoke: proves a synthetic local "
            "PNG asset flows end-to-end through "
            "scripts/run_explicit_pipeline.py into the editable .pptx "
            "as an internal ppt/media/* part whose sha256 equals the "
            "source asset sha256, while native editable text survives. "
            "Also runs fail-closed probes for source sha mismatch, "
            "source symlink (leaf + parent), unsafe registry path "
            "(traversal + URI), image_manifest missing declared id, "
            "unsupported media type, public-upload wording, and a "
            "PPTX media sha mismatch injected by tampering the "
            "positive PPTX bytes. MOCK / stub acceptance only — NOT "
            "real D-One integration; no MCP, no public network, no "
            "model API, no image search, no Qoder, no external service."
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
            "FAIL: source_image_asset_pipeline_smoke.py requires "
            "--self-test (no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
