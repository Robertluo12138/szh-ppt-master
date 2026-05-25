#!/usr/bin/env python3
"""source_image_asset_pipeline_smoke.py

Clean-room, stdlib-only, tempdir-only acceptance smoke that proves the
local source-image asset path carries TWO caller-supplied local image
assets — one synthetic PNG AND one synthetic JPEG — byte-for-byte
through ``scripts/run_explicit_pipeline.py`` into the editable
``.pptx`` as TWO distinct internal ``ppt/media/*`` parts, each
referenced by a distinct manifest id from a distinct slide, while the
produced deck still carries native editable text (i.e. neither slide
is an all-image fallback).

This smoke complements ``scripts/source_image_asset_acceptance_smoke.py``
(which exercises the read-only ``source_image_assets.json`` registry
surface end-to-end against a hand-built workspace plus a direct
``scripts/export_pptx.py`` invocation): the multi-asset smoke drives
the **explicit-input end-to-end orchestrator** instead — Stage 1-10 —
so the positive proof exercises the real prepare-then-pipeline chain a
live caller would run, plus the cross-stage materialize step. The
per-asset byte-identity claim
(``sha256(<workspace>/<png_local_path>) ==
sha256(<some ppt/media/*.png>)`` AND
``sha256(<workspace>/<jpeg_local_path>) ==
sha256(<some ppt/media/*.jpg or *.jpeg>)``) is the load-bearing
post-condition that proves no re-encode / metadata-stamp / TOCTOU swap
happened between disk and either embedded media part — AND that the
two assets did not collapse to one media part, one slide, one id, or
one sha during embedding (multi-asset coverage extension over the
earlier one-PNG smoke).

What the positive chain does (single ``tempfile.TemporaryDirectory()``):

  1. Build a synthetic 2-image fixture:
       * a tiny magic-byte-valid PNG payload inlined in this script;
       * a tiny magic-byte-valid JPEG payload inlined in this script
         (distinct bytes -> distinct sha256);
       * a synthetic Markdown source body;
       * caller specs: ``plan_spec.json`` (2 slides: each is a cover
         slide referencing its OWN distinct ``image_ref`` accent;
         each cover also carries a native title text run so the
         per-slide ``not_all_image_slide`` /
         ``every_slide_has_native_shape`` gates stay honest);
       * ``image_manifest_spec.json`` declaring TWO images: one with
         ``local_path`` ``assets/<png_id>.png`` and one with
         ``local_path`` ``assets/<jpeg_id>.jpg``, both with
         ``source = local_asset``;
       * a staging ``--assets-dir`` whose layout mirrors the workspace
         tree (``<staging>/assets/<png_id>.png`` carries the PNG bytes
         and ``<staging>/assets/<jpeg_id>.jpg`` carries the JPEG
         bytes the pipeline must copy into the workspace).
  2. Invoke ``scripts/run_explicit_pipeline.py`` once with the fixture
     plus ``--assets-dir <staging>``. The orchestrator runs Stage 1-6
     prep (including the Stage-5.5 materialize step the
     ``--assets-dir`` flag activates) and then Stage 7-10 (validate
     workspace, generate render_models, generate SVG previews, export
     PPTX, validate PPTX contract). The expected outcome is rc=0.
  3. Author the source-attached registry **after** the pipeline runs:
     copy each source-asset bytes to
     ``<workspace>/input/assets/<id>.<ext>`` (the canonical
     ``input/assets/<id>.<ext>`` propagation location declared in
     ``references/source-image-asset-policy.md``), then write
     ``<workspace>/source_image_assets.json`` whose TWO assets each
     carry
       * ``id``               = image_manifest.images[].id;
       * ``source_ref``       = source_manifest.source.id (G4);
       * ``local_path``       = ``input/assets/<id>.<ext>`` (G5..G9);
       * ``destination_path`` = ``assets/<id>.<ext>`` = image_manifest
                                local_path (G10);
       * ``media_type``       = ``image/png`` or ``image/jpeg`` (G9);
       * ``byte_count``       = actual on-disk length (G8);
       * ``sha256``           = lowercase hex sha256 of the bytes (G8).
     Run ``scripts/validate_source_image_assets.py --workspace
     <workspace>`` and expect rc=0 — every G1..G13 gate passes against
     a workspace that already ships ``source_manifest.json`` +
     ``image_manifest.json`` from the pipeline run.
  4. Open the produced ``.pptx`` as a ZIP and assert (the load-bearing
     multi-asset post-conditions):
       * at least one part exists under ``ppt/media/`` whose extension
         is ``.png`` AND at least one part exists whose extension is
         ``.jpg`` or ``.jpeg`` (no collapse to a single format);
       * the set of media-part sha256s equals the set of source-asset
         sha256s — every PNG part's sha matches the PNG source sha,
         every JPG/JPEG part's sha matches the JPEG source sha, and
         no media part carries a sha unaccounted for by the registry;
       * the two source-asset sha256s are themselves distinct (proves
         the test fixtures carry truly different bytes);
       * the on-disk set of distinct media parts is >= 2 (no collapse
         to a single shared media part);
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
     ``media_parts`` of length >= 2 / the documented
     ``evidence_basis`` framing line / a sha-set equality between
     media_parts[].sha256 and the source-asset sha set (so the
     inventory readback corroborates the smoke's own zipfile sha
     check) / no relationship with an external ``TargetMode`` or
     URI-scheme ``Target`` / at least two distinct slide indices
     referenced across media_parts[].referencing_slides (each asset
     used on its own slide, not collapsed onto one).

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

  M1   duplicate registry id across two multi-asset entries
        G3 fires (no two ``assets[*].id`` values may be equal).

  M2   duplicate destination_path across two multi-asset entries
        The smoke's own multi-asset post-condition
        ``_assert_registry_destinations_distinct`` refuses two
        registry entries that share a destination_path (would
        collapse two source assets onto the same workspace leaf and
        the same ``ppt/media/`` slot — propagation hazard not caught
        by G1..G13, owned by the smoke).

  M3   second registry asset missing from image_manifest
        Two-asset registry + one-asset manifest: G13 fires for the
        registry id the manifest never declared, while the matched
        first id still aligns under G10 (regression gate for an
        early-return that would short-circuit after the first id).

  M4   JPEG bytes declared as media_type=image/png at .png path
        G9 magic-byte gate fires (the JPEG signature does not match
        the declared PNG media_type) — proves a JPEG-bytes-in-a-
        ``.png``-wrapper cannot slip past the registry validator.

  M5   PNG bytes declared as media_type=image/jpeg at .jpg path
        G9 magic-byte gate fires (the PNG signature does not match
        the declared JPEG media_type) — symmetric to M4.

  M6   mixed extension / media_type mismatch (.jpg path + image/png)
        G9 extension-vs-media-type gate fires (the schema permits
        either, but the validator pins the agreement at runtime).

  M7   one asset sha mismatch while the other remains valid
        Two-asset registry with the FIRST entry's declared sha256
        flipped to zero: G8 fires once with the bad id named, and
        the validator must NOT silently accept the second entry as
        a proxy for run-level success — every per-entry failure
        must surface.

  N8   PPTX media sha256 mismatch (positive PPTX, ANY media part)
        Inject by repacking the positive-path PPTX with one byte
        flipped inside the FIRST ``ppt/media/*`` part the smoke
        finds. The smoke's own
        ``_assert_pptx_media_matches_source_shas`` post-condition
        must detect the drift — regression gate for an exporter
        that silently re-encodes / re-strips / metadata-stamps
        media bytes between the workspace and the package.

  M8   PPTX media sha256 mismatch on the SECOND media part only
        Tamper exactly the second ``ppt/media/*`` part (PNG or
        JPEG, whichever appears second in the deterministic
        ZIP order). The smoke-level sha-set equality check must
        still refuse it — a regression that only validated the
        FIRST part would false-green this case. This probe is the
        load-bearing multi-asset post-condition that proves
        per-part byte-identity, not "any-part" byte-identity.

Snapshot check: every scenario runs under
``tempfile.TemporaryDirectory()``; flat-bytes snapshots of
``REPO_ROOT/examples/`` AND ``REPO_ROOT/scripts/`` taken before and
after the run must match — proves no generated artifact (PNG / JPEG /
PPTX / render_models / svg_previews / reports / ``__pycache__``)
lands under any committed repo surface.

Fail-closed: any chain step exiting non-zero on the positive path, any
documented post-condition failing, or any negative probe whose gate
does NOT fire as documented aborts the smoke immediately and the
script exits non-zero with a clear per-assertion / per-probe
diagnostic.

**MOCK / STUB ONLY — NOT real D-One integration.** Nothing in this
script calls D-One, MCP, Qoder, a public network, telemetry, any model
API, an image search, a browser, or any external service. The PNG /
JPEG bytes are minimal magic-byte-valid local payloads inlined in
this script; neither is a photographically meaningful image. The
final summary states explicitly that real D-One remains UNVERIFIED.

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

# Synthetic, magic-byte-valid JPEG payload: SOI (FF D8) + APP0 / JFIF
# marker + EOI (FF D9). Same shape ``scripts/materialize_image_assets.py``
# uses as its synthetic JPEG test payload, intentionally byte-distinct
# from ``_TINY_PNG_BYTES`` so sha256(PNG) != sha256(JPEG) and the
# multi-asset post-condition can prove "two distinct media parts" /
# "no collapse" honestly.
_TINY_JPEG_BYTES: bytes = (
    b"\xff\xd8\xff\xe0"
    b"\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xd9"
)

# Synthetic identifiers. Each id collapses under the G12 canonical-form
# rule to a marker-free shape (``synthetic_*`` / ``pipeline_image_*``
# contains neither ``public`` nor a propagation-verb marker).
SYNTHETIC_SOURCE_ID = "synthetic_pipeline_source"
# Multi-asset positive-chain ids: slide 1 carries the PNG, slide 2
# carries the JPEG. Distinct ids + distinct extensions + distinct
# media_types so the registry validator + PPTX exporter both have to
# keep the two on independent ``ppt/media/imageN.<ext>`` slots.
SYNTHETIC_PNG_IMAGE_ID = "pipeline_image_alpha"
SYNTHETIC_JPEG_IMAGE_ID = "pipeline_image_beta"
SYNTHETIC_PNG_COVER_TITLE = "Pipeline Smoke PNG Cover"
SYNTHETIC_JPEG_COVER_TITLE = "Pipeline Smoke JPEG Cover"
# Single-asset minimal-workspace probes (N1..N7) reuse one shared id;
# the alias keeps those probes' diagnostics anchored on the same
# marker the earlier one-asset smoke used.
SYNTHETIC_IMAGE_ID = SYNTHETIC_PNG_IMAGE_ID
SYNTHETIC_AUDIENCE = "Internal smoke audience"
SYNTHETIC_OBJECTIVE = (
    "Exercise the source-image multi-asset path end-to-end through "
    "run_explicit_pipeline."
)


REAL_D_ONE_STATUS = (
    "UNVERIFIED — real D-One is NOT called by this smoke. The "
    "synthetic PNG AND JPEG bytes are minimal magic-byte-valid local "
    "payloads inlined in this script; nothing here calls D-One, MCP, "
    "Qoder, a public network, telemetry, any model API, an image "
    "search, a browser, or any external service."
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
    """Author the smallest viable multi-asset explicit-input fixture:
    synthetic Markdown body, a 2-slide deck plan (TWO cover slides,
    each referencing its own distinct ``image_ref`` accent — one PNG,
    one JPEG), slide_plans, image_manifest_spec, and a staging
    ``--assets-dir`` mirroring the workspace tree.

    Two cover slides — not one cover + one key_message — keep the
    multi-asset claim honest end-to-end: each slide carries ONE
    distinct ``image_slot`` accent (so the two assets must land on two
    distinct slides, not collapse onto one), AND each carries a native
    title text run (so the per-slide
    ``minimal_evidence.not_all_image_slide`` /
    ``every_slide_has_native_shape`` gates still pass — a cover layout
    emits a ``<p:sp>`` title alongside the ``<p:pic>`` accent, so
    ``n_sp + n_cxn > 0`` for both slides). The deterministic
    ``image_manifest.images[]`` order (PNG first, JPEG second) drives
    the exporter's deterministic ``ppt/media/image1.png`` /
    ``ppt/media/image2.jpg`` naming."""
    td.mkdir(parents=True, exist_ok=True)
    source = td / "fixture_source.md"
    source.write_text(
        "# Pipeline Smoke Fixture Source\n\n"
        "Synthetic source body authored by the source-image asset "
        "multi-asset pipeline smoke. No image bytes are extracted from "
        "this body; the asset bytes live separately in the caller-"
        "staged --assets-dir.\n",
        encoding="utf-8",
    )

    plan_spec = td / "plan_spec.json"
    _write_json(plan_spec, {
        "template": "business_review",
        "planning": {
            "planned_slide_count": 2,
            "rationale": (
                "Slide 1 (cover) references a synthetic PNG accent; "
                "slide 2 (cover) references a synthetic JPEG accent. "
                "Two distinct image ids on two distinct slides — "
                "proves the pipeline does not collapse multiple "
                "caller-supplied images into one media part, one "
                "slide, one id, or one format. Each cover also "
                "carries a native title text run so the "
                "minimal_evidence.not_all_image_slide + "
                "every_slide_has_native_shape gates still hold."
            ),
        },
        "sections": [
            {
                "id": "intro",
                "title": "Intro",
                "summary": "Two cover slides, one PNG accent + one JPEG accent.",
                "slide_indices": [1, 2],
            },
        ],
        "slides": [
            {
                "index": 1,
                "layout": "cover",
                "title": SYNTHETIC_PNG_COVER_TITLE,
                "section_id": "intro",
                "summary": "Cover slide with source-attached PNG accent.",
                "density": "low",
                "source_refs": [SYNTHETIC_SOURCE_ID],
            },
            {
                "index": 2,
                "layout": "cover",
                "title": SYNTHETIC_JPEG_COVER_TITLE,
                "section_id": "intro",
                "summary": "Cover slide with source-attached JPEG accent.",
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
        "title": SYNTHETIC_PNG_COVER_TITLE,
        "blocks": [
            {"id": "title", "kind": "text",
             "content": SYNTHETIC_PNG_COVER_TITLE},
            {"id": "accent", "kind": "image_ref",
             "content": SYNTHETIC_PNG_IMAGE_ID},
        ],
        "image_refs": [SYNTHETIC_PNG_IMAGE_ID],
    })
    _write_json(specs_dir / "02_cover.json", {
        "index": 2,
        "layout": "cover",
        "title": SYNTHETIC_JPEG_COVER_TITLE,
        "blocks": [
            {"id": "title", "kind": "text",
             "content": SYNTHETIC_JPEG_COVER_TITLE},
            {"id": "accent", "kind": "image_ref",
             "content": SYNTHETIC_JPEG_IMAGE_ID},
        ],
        "image_refs": [SYNTHETIC_JPEG_IMAGE_ID],
    })

    image_manifest_spec = td / "image_manifest_spec.json"
    _write_json(image_manifest_spec, {
        "images": [
            {
                "id": SYNTHETIC_PNG_IMAGE_ID,
                "local_path": f"assets/{SYNTHETIC_PNG_IMAGE_ID}.png",
                "source": "local_asset",
                "alt_text": "Synthetic source-attached PNG marker.",
                "intended_use": "spot illustration",
            },
            {
                "id": SYNTHETIC_JPEG_IMAGE_ID,
                "local_path": f"assets/{SYNTHETIC_JPEG_IMAGE_ID}.jpg",
                "source": "local_asset",
                "alt_text": "Synthetic source-attached JPEG marker.",
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
    png_leaf = staging / "assets" / f"{SYNTHETIC_PNG_IMAGE_ID}.png"
    png_leaf.parent.mkdir(parents=True, exist_ok=True)
    png_leaf.write_bytes(_TINY_PNG_BYTES)
    jpeg_leaf = staging / "assets" / f"{SYNTHETIC_JPEG_IMAGE_ID}.jpg"
    jpeg_leaf.write_bytes(_TINY_JPEG_BYTES)

    png_sha = _sha256(_TINY_PNG_BYTES)
    jpeg_sha = _sha256(_TINY_JPEG_BYTES)
    if png_sha == jpeg_sha:
        raise RuntimeError(
            "fixture invariant: synthetic PNG and JPEG payloads must "
            "have distinct sha256s; got equal "
            f"({png_sha!r} == {jpeg_sha!r})"
        )

    return {
        "source": source,
        "plan_spec": plan_spec,
        "specs_dir": specs_dir,
        "image_manifest_spec": image_manifest_spec,
        "assets_dir": staging,
        "assets": [
            {
                "id": SYNTHETIC_PNG_IMAGE_ID,
                "bytes": _TINY_PNG_BYTES,
                "sha256": png_sha,
                "media_type": "image/png",
                "extension": "png",
                "image_local_path": (
                    f"assets/{SYNTHETIC_PNG_IMAGE_ID}.png"
                ),
                "registry_local_path": (
                    f"input/assets/{SYNTHETIC_PNG_IMAGE_ID}.png"
                ),
                "registry_destination_path": (
                    f"assets/{SYNTHETIC_PNG_IMAGE_ID}.png"
                ),
            },
            {
                "id": SYNTHETIC_JPEG_IMAGE_ID,
                "bytes": _TINY_JPEG_BYTES,
                "sha256": jpeg_sha,
                "media_type": "image/jpeg",
                "extension": "jpg",
                "image_local_path": (
                    f"assets/{SYNTHETIC_JPEG_IMAGE_ID}.jpg"
                ),
                "registry_local_path": (
                    f"input/assets/{SYNTHETIC_JPEG_IMAGE_ID}.jpg"
                ),
                "registry_destination_path": (
                    f"assets/{SYNTHETIC_JPEG_IMAGE_ID}.jpg"
                ),
            },
        ],
    }


def _pipeline_args(
    fixture: dict, *, workspace: Path, output: Path,
) -> list[str]:
    return [
        sys.executable, str(RUN_EXPLICIT_PIPELINE),
        "--workspace", str(workspace),
        "--source", str(fixture["source"]),
        "--source-id", SYNTHETIC_SOURCE_ID,
        "--title", SYNTHETIC_PNG_COVER_TITLE,
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
    """Write ``<workspace>/source_image_assets.json`` AND place each
    asset's bytes at ``<workspace>/input/assets/<id>.<ext>`` so the
    read-only registry validator can run every G1..G13 gate against a
    workspace that already ships source_manifest.json (Stage 1) +
    image_manifest.json (Stage 6) from the pipeline run.

    Per asset, the registry destination_path matches image_manifest
    local_path (G10); the registry local_path is the canonical
    ``input/assets/<id>.<ext>`` propagation location declared in
    references/source-image-asset-policy.md. The two assets carry
    distinct ids + extensions + media_types + sha256s so G3 (unique
    ids) AND the smoke-owned multi-asset distinctness invariants
    pass."""
    registry_assets: list[dict] = []
    for asset in fixture["assets"]:
        source_local = workspace / asset["registry_local_path"]
        source_local.parent.mkdir(parents=True, exist_ok=True)
        source_local.write_bytes(asset["bytes"])
        registry_assets.append({
            "id": asset["id"],
            "source_ref": SYNTHETIC_SOURCE_ID,
            "local_path": asset["registry_local_path"],
            "destination_path": asset["registry_destination_path"],
            "media_type": asset["media_type"],
            "byte_count": len(asset["bytes"]),
            "sha256": asset["sha256"],
        })
    registry = {
        "schema_version": "1",
        "assets": registry_assets,
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


_PNG_MEDIA_SUFFIXES = (".png",)
_JPEG_MEDIA_SUFFIXES = (".jpg", ".jpeg")
_EMBEDDABLE_MEDIA_SUFFIXES = _PNG_MEDIA_SUFFIXES + _JPEG_MEDIA_SUFFIXES


def _list_pptx_media_parts(pptx: Path) -> tuple[
    list[str], list[str], list[str], Exception | None,
]:
    """Return ``(all_media_parts, png_parts, jpeg_parts, error)``. Each
    list is sorted by deterministic ZIP namelist order. ``error`` is
    None on success."""
    try:
        zf = _open_pptx_zip(pptx)
    except (zipfile.BadZipFile, OSError) as exc:
        return [], [], [], exc
    try:
        names = zf.namelist()
    finally:
        zf.close()
    all_media = sorted(
        n for n in names if n.startswith("ppt/media/")
    )
    png_parts = [
        n for n in all_media if n.lower().endswith(_PNG_MEDIA_SUFFIXES)
    ]
    jpeg_parts = [
        n for n in all_media if n.lower().endswith(_JPEG_MEDIA_SUFFIXES)
    ]
    return all_media, png_parts, jpeg_parts, None


def _assert_pptx_media_matches_source_shas(
    pptx: Path, *,
    expected_png_sha: str,
    expected_jpeg_sha: str,
) -> list[Assertion]:
    """Open the PPTX as a ZIP and assert the multi-asset post-conditions:

      * at least one ``ppt/media/*.png`` part exists;
      * at least one ``ppt/media/*.jpg`` OR ``ppt/media/*.jpeg`` part
        exists;
      * every PNG media part's sha256 equals ``expected_png_sha`` (no
        re-encode / metadata-stamp / TOCTOU swap on the PNG side);
      * every JPG/JPEG media part's sha256 equals
        ``expected_jpeg_sha`` (symmetric);
      * the set of media-part sha256s contains BOTH expected shas (no
        collapse to one format);
      * the two expected shas are themselves distinct (proves the
        fixture carries truly different bytes — defense-in-depth
        against a future copy/paste that accidentally aliases the
        payloads);
      * no media part carries an extension outside the PNG / JPG /
        JPEG embed set (regression gate for an exporter that silently
        admits an unsupported format)."""
    results: list[Assertion] = []
    if expected_png_sha == expected_jpeg_sha:
        results.append(Assertion(
            "expected PNG sha and expected JPEG sha are distinct",
            False,
            f"got equal expected shas {expected_png_sha!r}; the smoke "
            f"cannot prove multi-asset distinctness with aliased "
            f"fixtures",
        ))
        return results
    all_media, png_parts, jpeg_parts, err = _list_pptx_media_parts(pptx)
    if err is not None:
        results.append(Assertion(
            "PPTX opens as a ZIP",
            False,
            f"{type(err).__name__}: {err}",
        ))
        return results
    results.append(Assertion(
        "PPTX embeds at least one ppt/media/ PNG part",
        len(png_parts) > 0,
        f"found media: {all_media!r}",
    ))
    results.append(Assertion(
        "PPTX embeds at least one ppt/media/ JPG or JPEG part",
        len(jpeg_parts) > 0,
        f"found media: {all_media!r}",
    ))
    results.append(Assertion(
        "PPTX embeds >= 2 distinct ppt/media/ parts (no collapse)",
        len({n for n in all_media}) >= 2,
        f"found media: {all_media!r}",
    ))
    unsupported = [
        n for n in all_media
        if not n.lower().endswith(_EMBEDDABLE_MEDIA_SUFFIXES)
    ]
    results.append(Assertion(
        "every ppt/media/ part has a supported extension "
        "(.png/.jpg/.jpeg)",
        not unsupported,
        f"unsupported parts: {unsupported!r}",
    ))
    try:
        zf = _open_pptx_zip(pptx)
    except (zipfile.BadZipFile, OSError) as exc:
        results.append(Assertion(
            "PPTX opens as a ZIP for per-part sha walk",
            False, f"{type(exc).__name__}: {exc}",
        ))
        return results
    try:
        png_mismatches: list[str] = []
        jpeg_mismatches: list[str] = []
        media_part_shas: set[str] = set()
        for n in png_parts:
            try:
                payload = zf.read(n)
            except (KeyError, OSError) as exc:
                png_mismatches.append(
                    f"{n}: cannot read: {type(exc).__name__}: {exc}"
                )
                continue
            actual = _sha256(payload)
            media_part_shas.add(actual)
            if actual != expected_png_sha:
                png_mismatches.append(
                    f"{n}: sha256={actual!r}, "
                    f"expected={expected_png_sha!r} "
                    f"(byte length={len(payload)})"
                )
        for n in jpeg_parts:
            try:
                payload = zf.read(n)
            except (KeyError, OSError) as exc:
                jpeg_mismatches.append(
                    f"{n}: cannot read: {type(exc).__name__}: {exc}"
                )
                continue
            actual = _sha256(payload)
            media_part_shas.add(actual)
            if actual != expected_jpeg_sha:
                jpeg_mismatches.append(
                    f"{n}: sha256={actual!r}, "
                    f"expected={expected_jpeg_sha!r} "
                    f"(byte length={len(payload)})"
                )
        results.append(Assertion(
            "every ppt/media/ PNG sha256 equals the PNG source asset "
            "sha256",
            not png_mismatches,
            "; ".join(png_mismatches),
        ))
        results.append(Assertion(
            "every ppt/media/ JPG/JPEG sha256 equals the JPEG source "
            "asset sha256",
            not jpeg_mismatches,
            "; ".join(jpeg_mismatches),
        ))
        results.append(Assertion(
            "media-part sha-set contains BOTH expected source shas "
            "(no per-format collapse)",
            ({expected_png_sha, expected_jpeg_sha} <= media_part_shas),
            f"media_part_shas={sorted(media_part_shas)!r}, "
            f"expected={sorted([expected_png_sha, expected_jpeg_sha])!r}",
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
    expected_source_shas: set[str],
) -> list[Assertion]:
    """Assert inspect_pptx_inventory.json carries the documented gates
    AND every ``expected_source_shas`` value appears in at least one
    ``media_parts[]`` entry (so the inventory readback corroborates
    the smoke's own zipfile sha check). For the multi-asset positive
    chain this means BOTH the PNG and JPEG source shas appear in the
    inventory media_parts.

    Additionally asserts at least two distinct slide indices appear
    across ``media_parts[].referencing_slides`` so the two source
    assets are proven to be referenced from two distinct slides — a
    regression that silently re-pointed both image relationships at
    one slide would otherwise pass the byte-identity check while
    breaking the "distinct slides" claim of the positive chain."""
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
    min_parts = max(2, len(expected_source_shas))
    is_list = isinstance(mp, list) and len(mp) >= min_parts
    results.append(Assertion(
        f"inventory.media_parts is a list of length >= {min_parts}",
        is_list, f"got {mp!r}",
    ))
    results.append(Assertion(
        "inventory.evidence_basis matches the documented line",
        inv.get("evidence_basis") == EXPECTED_EVIDENCE_BASIS,
        f"got {inv.get('evidence_basis')!r}",
    ))
    if isinstance(mp, list):
        inventory_shas: set[str] = set()
        slide_indices: set[int] = set()
        for entry in mp:
            if not isinstance(entry, dict):
                continue
            sha = entry.get("sha256")
            if (
                isinstance(sha, str)
                and isinstance(entry.get("part"), str)
                and entry["part"].startswith("ppt/media/")
            ):
                inventory_shas.add(sha)
            refs = entry.get("referencing_slides")
            if isinstance(refs, list):
                for r in refs:
                    if isinstance(r, int):
                        slide_indices.add(r)
        missing_shas = sorted(expected_source_shas - inventory_shas)
        results.append(Assertion(
            "inventory media_parts shas contain every expected source "
            "asset sha256 (per-asset byte-identity corroborated by the "
            "inventory readback)",
            not missing_shas,
            f"missing shas={missing_shas!r}; inventory shas="
            f"{sorted(inventory_shas)!r}; expected="
            f"{sorted(expected_source_shas)!r}",
        ))
        results.append(Assertion(
            "inventory media_parts shas contain >= 2 distinct values "
            "(no per-format collapse)",
            len(inventory_shas) >= 2,
            f"inventory shas={sorted(inventory_shas)!r}",
        ))
        results.append(Assertion(
            "inventory media_parts collectively reference >= 2 "
            "distinct slide indices (the two assets land on distinct "
            "slides)",
            len(slide_indices) >= 2,
            f"slide_indices={sorted(slide_indices)!r}; "
            f"media_parts={mp!r}",
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


def _assert_registry_destinations_distinct(
    fixture: dict,
) -> Assertion:
    """Smoke-owned multi-asset invariant: every fixture asset's
    ``registry_destination_path`` MUST be unique. The registry schema
    pins ``destination_path`` shape but does NOT enforce uniqueness
    across entries (the schema's ``uniqueItems`` is on the asset
    object, and G3 only covers ``id``). Two registry entries that
    share a destination_path would collapse two source bytes onto the
    same workspace leaf — propagation hazard. Owned by the smoke
    because it is a multi-asset concern that does not arise in the
    single-asset surface and is intentionally out of scope for the
    G1..G13 validator today."""
    destinations = [
        a["registry_destination_path"] for a in fixture["assets"]
    ]
    distinct = len(set(destinations)) == len(destinations)
    return Assertion(
        "registry assets carry distinct destination_paths "
        "(smoke-owned multi-asset invariant)",
        distinct,
        f"destinations={destinations!r}",
    )


def _run_positive_chain(
    td: Path,
) -> tuple[bool, list[Assertion], Path | None, dict | None]:
    """Build the multi-asset synthetic fixture, drive
    run_explicit_pipeline, author the source-attached registry,
    validate it, and assert every documented PPTX post-condition.

    Returns ``(ok, assertions, pptx_path, fixture)`` so callers (the
    PPTX-tamper probes) can re-use the produced PPTX and the fixture's
    expected sha set. ``pptx_path`` / ``fixture`` are None when the
    pipeline itself failed."""
    print("--- positive proof (multi-asset: PNG + JPEG) ---")
    fixture_dir = td / "fixture"
    workspace = td / "workspace"
    output = td / "pipeline.pptx"
    fixture = _build_pipeline_fixture(fixture_dir)
    print(f"  workspace:    {workspace}")
    print(f"  pptx output:  {output}")
    print(
        "  assets:       "
        + ", ".join(
            f"{a['id']} ({a['media_type']}, sha={a['sha256'][:12]}...)"
            for a in fixture["assets"]
        )
    )

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

    # Stage B — every workspace asset exists byte-identical to its
    # staged source. Mirrors materialize_image_assets's post-condition,
    # extended per-asset so a regression that copied only the FIRST
    # entry would still surface as a per-asset FAIL.
    workspace_assertions: list[Assertion] = []
    for asset in fixture["assets"]:
        workspace_leaf = workspace / asset["image_local_path"]
        leaf_is_file = (
            workspace_leaf.is_file()
            and not workspace_leaf.is_symlink()
        )
        ok = leaf_is_file and workspace_leaf.read_bytes() == asset["bytes"]
        workspace_assertions.append(Assertion(
            f"materialize copied the staged {asset['media_type']} "
            f"asset id={asset['id']!r} into "
            f"<workspace>/{asset['image_local_path']} byte-identical "
            f"to the --assets-dir source",
            ok,
            f"workspace_leaf={workspace_leaf}, is_file={leaf_is_file}",
        ))

    # Stage B.5 — smoke-owned multi-asset distinctness invariant.
    workspace_assertions.append(
        _assert_registry_destinations_distinct(fixture)
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
        "pipeline-produced workspace augmented with the multi-asset "
        "source-attached registry (PNG + JPEG)",
        registry_validator.ok,
        f"rc={registry_validator.rc}; "
        f"tail={registry_validator.combined.splitlines()[-12:]!r}",
    )

    # Stage D — PPTX byte-identity assertions (multi-asset variant).
    expected_png_sha = next(
        a["sha256"] for a in fixture["assets"]
        if a["media_type"] == "image/png"
    )
    expected_jpeg_sha = next(
        a["sha256"] for a in fixture["assets"]
        if a["media_type"] == "image/jpeg"
    )
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
            _assert_pptx_media_matches_source_shas(
                output,
                expected_png_sha=expected_png_sha,
                expected_jpeg_sha=expected_jpeg_sha,
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
        expected_source_shas={expected_png_sha, expected_jpeg_sha},
    )

    final = (
        pipeline_markers
        + workspace_assertions
        + [registry_assertion]
        + pptx_assertions
        + contract_assertions
        + [inspect_assertion]
        + inventory_assertions
    )
    ok = all(a.ok for a in final)
    return ok, final, output, fixture


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


def _seed_minimal_multi_asset_workspace(
    td: Path,
    *,
    place_image_manifest: bool = True,
    registry_asset_overrides: dict[int, dict] | None = None,
    drop_registry_asset_indices: tuple[int, ...] = (),
    drop_manifest_asset_indices: tuple[int, ...] = (),
    duplicate_registry_id_for_index: int | None = None,
    duplicate_destination_for_index: int | None = None,
    payload_overrides: dict[int, bytes] | None = None,
) -> tuple[Path, list[dict]]:
    """Build a minimal positive-shape multi-asset workspace
    (source_manifest + PNG + JPEG asset bytes at the registry
    local_paths + 2-entry registry + 2-entry image_manifest) and apply
    targeted overrides keyed by registry asset index (0 = PNG, 1 =
    JPEG).

    ``registry_asset_overrides[idx]`` is a dict of registry-entry
    fields to override on assets[idx] BEFORE the registry is written.
    ``drop_registry_asset_indices`` removes those registry entries
    AFTER overrides apply. ``drop_manifest_asset_indices`` removes
    image_manifest entries by index (using the original 0/1 mapping).
    ``duplicate_registry_id_for_index`` rewrites assets[idx].id to
    equal assets[0].id (so the registry has duplicate ids — G3
    target). ``duplicate_destination_for_index`` rewrites
    assets[idx].destination_path to equal assets[0].destination_path.
    ``payload_overrides[idx]`` replaces the on-disk bytes for
    asset[idx] AFTER seeding (used by the bytes-as-wrong-media-type
    probes); byte_count / sha256 in the registry stay anchored on
    the ORIGINAL bytes so G8 stays clean — only the MAGIC-BYTE side
    of G9 diverges, which is what these probes target.

    Returns ``(workspace, base_registry_assets)`` so callers that want
    to assert on the original asset shapes can.
    """
    workspace = td / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    # source_manifest.json — required for G4.
    body = b"# Minimal multi-asset probe source\n"
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

    assets_parent = workspace / "input" / "assets"
    assets_parent.mkdir(parents=True, exist_ok=True)

    base_specs = [
        {
            "id": SYNTHETIC_PNG_IMAGE_ID,
            "media_type": "image/png",
            "extension": "png",
            "bytes": _TINY_PNG_BYTES,
        },
        {
            "id": SYNTHETIC_JPEG_IMAGE_ID,
            "media_type": "image/jpeg",
            "extension": "jpg",
            "bytes": _TINY_JPEG_BYTES,
        },
    ]

    payload_overrides = payload_overrides or {}
    for idx, spec in enumerate(base_specs):
        leaf_bytes = payload_overrides.get(idx, spec["bytes"])
        rel_local = (
            f"input/assets/{spec['id']}.{spec['extension']}"
        )
        spec["registry_local_path"] = rel_local
        spec["registry_destination_path"] = (
            f"assets/{spec['id']}.{spec['extension']}"
        )
        # Anchor declared byte_count / sha256 on the ORIGINAL synthetic
        # payload so G8 stays clean for probes whose target is G9. Probes
        # that perturb G8 supply registry_asset_overrides explicitly.
        spec["declared_byte_count"] = len(spec["bytes"])
        spec["declared_sha256"] = _sha256(spec["bytes"])
        (workspace / rel_local).write_bytes(leaf_bytes)

    registry_assets: list[dict] = [
        {
            "id": s["id"],
            "source_ref": SYNTHETIC_SOURCE_ID,
            "local_path": s["registry_local_path"],
            "destination_path": s["registry_destination_path"],
            "media_type": s["media_type"],
            "byte_count": s["declared_byte_count"],
            "sha256": s["declared_sha256"],
        }
        for s in base_specs
    ]
    if registry_asset_overrides:
        for idx, overrides in registry_asset_overrides.items():
            registry_assets[idx].update(overrides)
    if duplicate_registry_id_for_index is not None:
        registry_assets[duplicate_registry_id_for_index]["id"] = (
            registry_assets[0]["id"]
        )
    if duplicate_destination_for_index is not None:
        registry_assets[duplicate_destination_for_index]["destination_path"] = (
            registry_assets[0]["destination_path"]
        )
    # Drop entries last (indices refer to the original 0/1 mapping).
    if drop_registry_asset_indices:
        registry_assets = [
            a for i, a in enumerate(registry_assets)
            if i not in drop_registry_asset_indices
        ]
    _write_json(workspace / "source_image_assets.json", {
        "schema_version": "1",
        "assets": registry_assets,
    })

    if place_image_manifest:
        manifest_images = [
            {
                "id": s["id"],
                "local_path": s["registry_destination_path"],
                "source": "local_asset",
                "alt_text": f"Probe ({s['media_type']}).",
                "intended_use": "spot illustration",
            }
            for s in base_specs
        ]
        if drop_manifest_asset_indices:
            manifest_images = [
                m for i, m in enumerate(manifest_images)
                if i not in drop_manifest_asset_indices
            ]
        _write_json(workspace / "image_manifest.json", {
            "images": manifest_images,
        })

    return workspace, base_specs


def _probe_duplicate_registry_id() -> ProbeResult:
    """M1: G3 fires when two registry entries share an id. Two assets
    each with valid bytes and aligned manifest entries, but
    assets[1].id is rewritten to equal assets[0].id."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_m1_") as raw_td:
        td = Path(raw_td)
        workspace, _ = _seed_minimal_multi_asset_workspace(
            td, duplicate_registry_id_for_index=1,
        )
        return _expect_validator_fail(
            "M1: registry has two assets with the same id -> G3 refuses",
            workspace=workspace,
            expected_substrings=["G3", "duplicates"],
        )


def _probe_duplicate_destination_path() -> ProbeResult:
    """M2: the smoke-owned multi-asset invariant
    ``_assert_registry_destinations_distinct`` refuses two registry
    entries that share a destination_path. The G1..G13 validator does
    NOT currently enforce destination_path uniqueness (G3 covers id
    only; G10 / G13 align id-to-id), so the smoke owns this gate as a
    propagation-hazard belt-and-braces. The probe perturbs only the
    second asset's destination_path so the workspace is otherwise
    schema-valid — the failure is pinned to the destination collision."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_m2_") as raw_td:
        td = Path(raw_td)
        workspace, _ = _seed_minimal_multi_asset_workspace(
            td, duplicate_destination_for_index=1,
        )
        # Re-build the fixture-style asset list from the workspace so the
        # smoke-owned invariant runs against the same shape it would in
        # the positive chain.
        registry = json.loads(
            (workspace / "source_image_assets.json").read_text()
        )
        synth_fixture = {
            "assets": [
                {
                    "id": a["id"],
                    "registry_destination_path": a["destination_path"],
                }
                for a in registry["assets"]
            ],
        }
        invariant = _assert_registry_destinations_distinct(synth_fixture)
        return ProbeResult(
            "M2: registry assets share destination_path -> smoke-owned "
            "multi-asset invariant refuses (propagation hazard not "
            "caught by G1..G13)",
            (not invariant.ok)
            and "destinations=" in invariant.detail,
            f"invariant.ok={invariant.ok}, detail={invariant.detail!r}",
        )


def _probe_multi_asset_second_missing_from_manifest() -> ProbeResult:
    """M3: G13 fires for the second registry asset when image_manifest
    declares only the first asset's id. Different from N5 (which uses
    a 1-registry / 1-mismatched-manifest workspace): M3 proves the
    validator surfaces a PER-asset diagnostic AND does not short-
    circuit after the first id, so the multi-asset propagation
    completeness check stays honest across the whole registry."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_m3_") as raw_td:
        td = Path(raw_td)
        workspace, _ = _seed_minimal_multi_asset_workspace(
            td, drop_manifest_asset_indices=(1,),
        )
        return _expect_validator_fail(
            "M3: registry declares two ids but image_manifest declares "
            "only the first -> G13 refuses the second id "
            f"({SYNTHETIC_JPEG_IMAGE_ID!r})",
            workspace=workspace,
            expected_substrings=[
                "G13", "every registry asset must be declared",
                SYNTHETIC_JPEG_IMAGE_ID,
            ],
        )


def _probe_jpeg_bytes_declared_as_png() -> ProbeResult:
    """M4: the second registry entry carries JPEG bytes on disk but
    declares media_type=image/png at an ``.png`` path. G9's magic-byte
    branch fires because the JPEG signature does not match the declared
    PNG media_type. byte_count / sha256 are re-anchored to the JPEG
    bytes so G8 stays clean — failure is pinned to G9."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_m4_") as raw_td:
        td = Path(raw_td)
        # Override asset[1]: pretend the JPEG asset is a PNG.
        rel_local = f"input/assets/{SYNTHETIC_JPEG_IMAGE_ID}.png"
        rel_dest = f"assets/{SYNTHETIC_JPEG_IMAGE_ID}.png"
        workspace, _ = _seed_minimal_multi_asset_workspace(
            td,
            registry_asset_overrides={
                1: {
                    "media_type": "image/png",
                    "local_path": rel_local,
                    "destination_path": rel_dest,
                    "byte_count": len(_TINY_JPEG_BYTES),
                    "sha256": _sha256(_TINY_JPEG_BYTES),
                },
            },
        )
        # Place the JPEG bytes at the .png path the registry now claims;
        # the seed helper wrote .jpg, which leaves the .png slot empty.
        (workspace / rel_local).write_bytes(_TINY_JPEG_BYTES)
        # Align the image_manifest entry so the failure pin-points G9
        # rather than G10/G13.
        manifest = json.loads(
            (workspace / "image_manifest.json").read_text()
        )
        manifest["images"][1]["local_path"] = rel_dest
        _write_json(workspace / "image_manifest.json", manifest)
        return _expect_validator_fail(
            "M4: JPEG bytes declared as media_type=image/png at .png "
            "path -> G9 magic-byte gate refuses",
            workspace=workspace,
            expected_substrings=["G9", "magic-byte signature"],
        )


def _probe_png_bytes_declared_as_jpeg() -> ProbeResult:
    """M5: the FIRST registry entry carries PNG bytes on disk but
    declares media_type=image/jpeg at a ``.jpg`` path. Symmetric to
    M4 — the PNG signature does not match the declared JPEG
    media_type. byte_count / sha256 are re-anchored on the PNG bytes
    so G8 stays clean."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_m5_") as raw_td:
        td = Path(raw_td)
        rel_local = f"input/assets/{SYNTHETIC_PNG_IMAGE_ID}.jpg"
        rel_dest = f"assets/{SYNTHETIC_PNG_IMAGE_ID}.jpg"
        workspace, _ = _seed_minimal_multi_asset_workspace(
            td,
            registry_asset_overrides={
                0: {
                    "media_type": "image/jpeg",
                    "local_path": rel_local,
                    "destination_path": rel_dest,
                    "byte_count": len(_TINY_PNG_BYTES),
                    "sha256": _sha256(_TINY_PNG_BYTES),
                },
            },
        )
        (workspace / rel_local).write_bytes(_TINY_PNG_BYTES)
        manifest = json.loads(
            (workspace / "image_manifest.json").read_text()
        )
        manifest["images"][0]["local_path"] = rel_dest
        _write_json(workspace / "image_manifest.json", manifest)
        return _expect_validator_fail(
            "M5: PNG bytes declared as media_type=image/jpeg at .jpg "
            "path -> G9 magic-byte gate refuses",
            workspace=workspace,
            expected_substrings=["G9", "magic-byte signature"],
        )


def _probe_extension_media_type_mismatch() -> ProbeResult:
    """M6: the second registry entry's path keeps the ``.jpg``
    extension but its media_type is rewritten to ``image/png`` (the
    on-disk bytes stay JPEG). The validator's G9 extension-vs-media
    branch fires because ``.jpg`` does not agree with ``image/png``
    in the ``_MEDIA_TYPE_TO_EXTS`` lock — independent of the
    magic-byte branch."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_m6_") as raw_td:
        td = Path(raw_td)
        workspace, _ = _seed_minimal_multi_asset_workspace(
            td,
            registry_asset_overrides={
                1: {"media_type": "image/png"},
            },
        )
        return _expect_validator_fail(
            "M6: registry entry with .jpg extension declared as "
            "media_type=image/png -> G9 extension/media_type gate "
            "refuses",
            workspace=workspace,
            expected_substrings=[
                "G9", "does not agree with media_type",
            ],
        )


def _probe_one_asset_sha_mismatch() -> ProbeResult:
    """M7: the FIRST registry entry's declared sha256 is flipped to
    zero while the second entry stays valid. G8 must fire with the
    bad id named AND the validator must NOT silently treat the second
    valid entry as a proxy for run-level success — every per-entry
    failure must surface."""
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_m7_") as raw_td:
        td = Path(raw_td)
        workspace, _ = _seed_minimal_multi_asset_workspace(
            td,
            registry_asset_overrides={
                0: {"sha256": "0" * 64},
            },
        )
        return _expect_validator_fail(
            f"M7: only the first registry asset "
            f"({SYNTHETIC_PNG_IMAGE_ID!r}) has a bad sha256, the "
            f"second is clean -> G8 still refuses fail-closed and the "
            f"bad id is named",
            workspace=workspace,
            expected_substrings=[
                "G8", "sha256", SYNTHETIC_PNG_IMAGE_ID,
            ],
        )


def _tamper_pptx_media(
    src: Path, dst: Path, *, target_index: int,
) -> tuple[bool, str | None]:
    """Rewrite ``src`` to ``dst`` flipping one byte inside the
    ``target_index``-th ``ppt/media/*`` part (0-based, sorted by
    namelist order). Returns ``(ok, tampered_part_name)``. The probe
    callers use this to inject a media-sha drift without touching the
    exporter — N8 tampers the first part, M8 the second."""
    try:
        with zipfile.ZipFile(src, "r") as zin:
            members = zin.namelist()
            media_parts = sorted(
                n for n in members
                if n.startswith("ppt/media/")
                and n.lower().endswith(_EMBEDDABLE_MEDIA_SUFFIXES)
            )
            if target_index < 0 or target_index >= len(media_parts):
                return False, None
            target = media_parts[target_index]
            with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
                for n in members:
                    raw = zin.read(n)
                    if n == target:
                        if not raw:
                            return False, None
                        # Flip the last byte. PNG / JPEG decoders may
                        # reject the tampered file, but the smoke only
                        # cares about the byte-identity gate — the
                        # post-condition runs sha256 on raw bytes
                        # inside the ZIP, never asks PowerPoint to
                        # render anything.
                        raw = raw[:-1] + bytes([raw[-1] ^ 0xFF])
                    zout.writestr(n, raw)
        return True, target
    except (zipfile.BadZipFile, OSError):
        return False, None


def _probe_pptx_media_sha_mismatch_for_part(
    pptx: Path,
    *,
    expected_png_sha: str,
    expected_jpeg_sha: str,
    target_index: int,
    probe_label: str,
) -> ProbeResult:
    """Shared helper for N8 + M8: tamper the ``target_index``-th
    media part inside the positive multi-asset PPTX and assert the
    smoke-level
    ``_assert_pptx_media_matches_source_shas`` post-condition flips
    to FAIL on at least one of the per-format sha checks.

    N8 (target_index=0) proves the byte-identity gate detects an
    ANY-part drift; M8 (target_index=1) proves it detects a
    SECOND-PART-ONLY drift — a regression that only validated the
    FIRST part would false-green M8."""
    if not pptx.is_file():
        return ProbeResult(
            f"{probe_label} (skipped — no positive PPTX)",
            False,
            "positive run did not produce a PPTX",
        )
    with tempfile.TemporaryDirectory(prefix="szh_sia_pipe_tamper_") as raw_td:
        td = Path(raw_td)
        tampered = td / "tampered.pptx"
        ok, target_name = _tamper_pptx_media(
            pptx, tampered, target_index=target_index,
        )
        if not ok:
            return ProbeResult(
                f"{probe_label} (skipped — tamper failed at index "
                f"{target_index})",
                False,
                f"could not flip byte in ppt/media/*[{target_index}]",
            )
        assertions = _assert_pptx_media_matches_source_shas(
            tampered,
            expected_png_sha=expected_png_sha,
            expected_jpeg_sha=expected_jpeg_sha,
        )
        per_format_checks = [
            a for a in assertions
            if a.name.startswith("every ppt/media/ PNG sha256")
            or a.name.startswith("every ppt/media/ JPG/JPEG sha256")
            or a.name.startswith("media-part sha-set contains BOTH")
        ]
        flipped_any = any(not a.ok for a in per_format_checks)
        return ProbeResult(
            f"{probe_label} (tampered {target_name!r})",
            flipped_any,
            f"per_format_results="
            f"{[(a.name, a.ok) for a in per_format_checks]!r}",
        )


def _probe_pptx_media_sha_mismatch_first_part(
    pptx: Path,
    *,
    expected_png_sha: str,
    expected_jpeg_sha: str,
) -> ProbeResult:
    """N8: tamper the FIRST media part (any extension)."""
    return _probe_pptx_media_sha_mismatch_for_part(
        pptx,
        expected_png_sha=expected_png_sha,
        expected_jpeg_sha=expected_jpeg_sha,
        target_index=0,
        probe_label=(
            "N8: tampered FIRST ppt/media/* part -> smoke-level sha "
            "check refuses (any-part byte-identity gate)"
        ),
    )


def _probe_pptx_media_sha_mismatch_second_part(
    pptx: Path,
    *,
    expected_png_sha: str,
    expected_jpeg_sha: str,
) -> ProbeResult:
    """M8: tamper the SECOND media part. Load-bearing multi-asset
    post-condition — a regression that only validated the first part
    would false-green this."""
    return _probe_pptx_media_sha_mismatch_for_part(
        pptx,
        expected_png_sha=expected_png_sha,
        expected_jpeg_sha=expected_jpeg_sha,
        target_index=1,
        probe_label=(
            "M8: tampered SECOND ppt/media/* part only -> smoke-level "
            "sha check refuses (per-part byte-identity gate; not "
            "any-part)"
        ),
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
    expected_png_sha: str | None = None
    expected_jpeg_sha: str | None = None
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
            positive_ok, positive_results, produced_pptx, fixture = (
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
            # Copy the produced PPTX out of the tempdir so the N8 / M8
            # probes can run against a stable path AFTER this
            # TemporaryDirectory is torn down.
            if produced_pptx is not None and produced_pptx.is_file():
                pptx_copy = Path(persistent_dir) / "pipeline.pptx"
                shutil.copyfile(produced_pptx, pptx_copy)
                pptx_path = pptx_copy
            if fixture is not None:
                expected_png_sha = next(
                    a["sha256"] for a in fixture["assets"]
                    if a["media_type"] == "image/png"
                )
                expected_jpeg_sha = next(
                    a["sha256"] for a in fixture["assets"]
                    if a["media_type"] == "image/jpeg"
                )

        print("--- negative probes ---")
        probes: list[ProbeResult] = []
        # Single-asset minimal-workspace probes (N1..N7) anchor on
        # specific G* gates with single-asset perturbations.
        probes.append(_probe_sha256_mismatch())
        probes.append(_probe_source_symlink())
        probes.append(_probe_source_symlink_parent())
        probes.append(_probe_unsafe_local_path_traversal())
        probes.append(_probe_unsafe_local_path_uri())
        probes.append(_probe_image_manifest_missing_id())
        probes.append(_probe_unsupported_media_type())
        probes.append(_probe_public_upload_wording())
        # Multi-asset minimal-workspace probes (M1..M7) anchor on the
        # multi-asset perturbations the goal pins. Each builds its own
        # tempdir-only 2-asset workspace; none mutate the positive
        # PPTX.
        probes.append(_probe_duplicate_registry_id())
        probes.append(_probe_duplicate_destination_path())
        probes.append(_probe_multi_asset_second_missing_from_manifest())
        probes.append(_probe_jpeg_bytes_declared_as_png())
        probes.append(_probe_png_bytes_declared_as_jpeg())
        probes.append(_probe_extension_media_type_mismatch())
        probes.append(_probe_one_asset_sha_mismatch())
        # PPTX-tamper probes (N8 + M8) reuse the positive multi-asset
        # PPTX and tamper one media part each. N8 flips the FIRST
        # part (any-part byte-identity gate); M8 flips the SECOND part
        # (per-part byte-identity gate — the multi-asset-specific
        # regression target).
        if (
            pptx_path is not None
            and expected_png_sha is not None
            and expected_jpeg_sha is not None
        ):
            probes.append(_probe_pptx_media_sha_mismatch_first_part(
                pptx_path,
                expected_png_sha=expected_png_sha,
                expected_jpeg_sha=expected_jpeg_sha,
            ))
            probes.append(_probe_pptx_media_sha_mismatch_second_part(
                pptx_path,
                expected_png_sha=expected_png_sha,
                expected_jpeg_sha=expected_jpeg_sha,
            ))
        else:
            probes.append(ProbeResult(
                "N8: PPTX media sha mismatch (skipped — no positive PPTX)",
                False,
                "positive run produced no PPTX to tamper",
            ))
            probes.append(ProbeResult(
                "M8: PPTX second-media sha mismatch (skipped — no "
                "positive PPTX)",
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
            "OK (self-test): source-image-asset multi-asset pipeline "
            "smoke passed.\n"
            f"  Real D-One status: {REAL_D_ONE_STATUS}"
        )
        return 0
    finally:
        # Remove the kept PPTX copy. ``TemporaryDirectory`` already
        # handles the per-scenario tempdirs; this cleans up the
        # persistent copy we created for the N8 / M8 probes.
        try:
            shutil.rmtree(persistent_dir, ignore_errors=True)
        except OSError:
            pass


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Source-image-asset multi-asset pipeline smoke: proves "
            "TWO synthetic local image assets (one PNG + one JPEG) "
            "flow end-to-end through "
            "scripts/run_explicit_pipeline.py into the editable .pptx "
            "as TWO distinct internal ppt/media/* parts whose per-asset "
            "sha256s equal their respective source asset sha256s, "
            "referenced from two distinct slides, while native editable "
            "text survives. Also runs single-asset fail-closed probes "
            "(N1..N7) covering source sha mismatch, source symlink "
            "(leaf + parent), unsafe registry path (traversal + URI), "
            "image_manifest missing declared id, unsupported media "
            "type, and public-upload wording, plus multi-asset "
            "fail-closed probes (M1..M7) covering duplicate registry "
            "id, duplicate destination_path, second-asset missing from "
            "manifest, JPEG-as-PNG / PNG-as-JPEG magic-byte mismatch, "
            "extension/media_type disagreement, one-asset sha "
            "mismatch, plus tampered-first-part (N8) and "
            "tampered-second-part (M8) PPTX media probes. MOCK / stub "
            "acceptance only — NOT real D-One integration; no MCP, no "
            "public network, no model API, no image search, no Qoder, "
            "no external service."
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
