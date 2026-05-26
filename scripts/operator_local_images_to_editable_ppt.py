#!/usr/bin/env python3
"""operator_local_images_to_editable_ppt.py

Operator-facing **local-image intake** helper for the core image-to-
editable-PPT lane. The next operator step after
``scripts/core_image_to_editable_ppt_demo.py --out-dir DIR`` for a
reviewer who has a folder of their OWN local PNG / JPG / JPEG bytes and
wants to prove those bytes can flow through the existing local image
asset pipeline into a native editable PPTX with inventory + provenance
evidence.

Two modes share one happy path:

  * ``--images-dir DIR --out-dir OUT`` — **operator mode**: takes a
    caller-supplied flat directory of PNG / JPG / JPEG image files plus
    a caller-supplied output directory that lives **outside the repo
    tree**. Discovers the image files deterministically (sorted by
    filename), generates the smallest viable pipeline fixture (one
    cover slide per image, native title + image_slot accent), invokes
    ``scripts/run_explicit_pipeline.py`` with ``--theme-from-template``
    + ``--assets-dir <staged>`` so the existing Stage-5.5 materialize
    step copies the bytes into the workspace, then runs every existing
    validator (``validate_source_image_assets``,
    ``validate_pptx_contract --expected-slide-count N``,
    ``inspect_pptx_inventory``) against the produced workspace + PPTX
    and writes a compact ``summary.json`` + a per-image provenance map
    naming the operator filename, the workspace path the bytes landed
    at, the sha256, and the embedded ``ppt/media/*`` part. Leaves every
    intermediate artifact on disk under OUT for a reviewer to inspect.

  * ``--self-test`` — drives the same happy path inside a per-run
    ``tempfile.TemporaryDirectory()`` using two tiny generated PNG /
    JPEG fixtures (no committed bytes; nothing leaks under REPO_ROOT)
    and exercises every documented fail-closed probe.

The helper itself adds NO new schema, NO new validator, and NO new
runtime contract. It composes existing helpers:

  * ``scripts/validate_source_image_assets.py`` —
    ``_PNG_SIGNATURE`` / ``_JPEG_SIGNATURE_PREFIX`` magic-byte gate
    + G1..G13 cross-checks against the produced workspace;
  * ``scripts/materialize_image_assets.py`` —
    ``SUPPORTED_EXTENSIONS`` allow-list (PNG / JPG / JPEG only — the
    embed surface ``scripts/export_pptx.py`` supports today);
  * ``scripts/run_explicit_pipeline.py`` — Stage-1-to-10
    explicit-input orchestration including the Stage-5.5
    ``materialize_image_assets`` step the ``--assets-dir`` flag
    activates;
  * ``scripts/validate_pptx_contract.py`` /
    ``scripts/inspect_pptx_inventory.py`` — the same editable-PPTX
    contract gates the demo + smokes use;
  * ``scripts/core_image_to_editable_ppt_demo._validate_out_dir_arg``
    — operator ``--out-dir`` gate (URI / symlink / symlink-ancestor /
    inside-REPO_ROOT / missing-parent / non-directory / non-empty
    pre-existing). Imported verbatim so the two operator entry points
    enforce a single ``--out-dir`` contract.

Fail-closed gates the helper itself enforces on operator input
(everything BELOW runs BEFORE any subprocess fires; refusals print a
per-failure diagnostic and return rc=2 — no workspace, fixture,
or PPTX is created):

  IG1   ``--images-dir`` is not URI-shaped.
  IG2   ``--images-dir`` is not itself a symlink (broken or
        resolvable). Silently following a symlink would let an attacker
        who controls the link target redirect what bytes the helper
        ingests.
  IG3   no ancestor of ``--images-dir`` up to the filesystem root is a
        symlink. Same attack surface one level up; the walk stops at
        the filesystem root, except for the closed allow-list of
        macOS system aliases such as ``/tmp -> /private/tmp``.
  IG4   ``--images-dir`` exists, is a directory, and is non-empty
        (refusing to stage a zero-image deck — there would be no
        ``ppt/media/`` to inspect on the other side).
  IG5   every entry at the directory ROOT is a regular non-symlink file
        with a lower-cased extension in
        ``materialize_image_assets.SUPPORTED_EXTENSIONS``. Subdirectories
        and non-regular files (symlinks, devices, FIFOs, sockets) are
        refused outright — the helper does NOT recurse, the existing
        materialize step does NOT recurse either, and an unsupported
        extension can never be embedded by the exporter.
  IG6   every operator filename stem (the basename minus the extension)
        matches the ``source_image_asset`` ``id`` pattern
        ``^[A-Za-z0-9][A-Za-z0-9_.\\-]*$`` and is at most 128 bytes —
        the same pattern the schema already locks. A non-conforming
        stem (e.g. ``My Photo.png`` with a space, or ``-leading.jpg``
        with a leading separator) is refused with a diagnostic asking
        the operator to rename the file. The helper does NOT silently
        sanitise — that would hide a contract change from the operator.
  IG7   no two operator filenames share a stem (case-sensitive).
        ``alpha.png`` + ``alpha.jpg`` would collide on the workspace
        ``assets/<id>.<ext>`` slot AND on the registry ``id`` — refused.
  IG8   each file's first bytes match the magic-byte signature for its
        declared extension. ``foo.png`` whose body is actually JPEG
        bytes (or a renamed text file) is refused BEFORE any pipeline
        run — same magic-byte gate ``materialize_image_assets`` would
        fire later, but at the operator boundary so the diagnostic
        names the operator file, not a derived workspace path.
  IG9   the deck is capped at ``MAX_IMAGES`` (= 12) images. Above the
        cap the helper refuses with a diagnostic asking the operator
        to pre-filter; the cap keeps deck assembly + validation runtime
        bounded and matches the small-deck-only contract the rest of
        the local lane is built around.

  OUT   ``--out-dir`` passes ``core_image_to_editable_ppt_demo.
        _validate_out_dir_arg`` (URI, symlink, symlink-ancestor,
        inside-REPO_ROOT, missing-parent, non-directory, non-empty
        pre-existing — one contract for every operator helper that
        writes outside the repo).

After the pipeline run, the helper additionally runs the existing
``validate_source_image_assets`` validator against a freshly-authored
``<workspace>/source_image_assets.json`` registry (PNG / JPG / JPEG
classes only, every entry source-class ``local_asset``, source_ref =
``operator_local_images_source``), then ``validate_pptx_contract
--expected-slide-count N`` and ``inspect_pptx_inventory`` against the
produced ``.pptx``. Any non-zero exit aborts with a clear diagnostic
and leaves the partial artifacts on disk for the operator to inspect.

Summary record written to ``<out-dir>/summary.json`` (echoed to stdout
verbatim — the helper's load-bearing operator-facing output):

  * ``schema_version`` — locked to ``"1"``.
  * ``helper_id`` — ``"operator_local_images_to_editable_ppt"``.
  * ``slide_count`` — count from the produced PPTX inventory.
  * ``image_count`` — count of operator images embedded.
  * ``embedded_media_count`` — number of ``ppt/media/*.{png,jpg,jpeg}``
    parts the produced PPTX carries (must equal ``image_count``).
  * ``source_classes`` — sorted list, expected exactly ``["local_asset"]``
    (no D-One, no synthetic).
  * ``no_external_relationships`` — True iff every contract validator
    ``relationships.{no_external,no_file_uri,allow_list}`` gate
    passed AND the inventory carries no external / file:// / URI-scheme
    relationship.
  * ``minimal_evidence`` — booleans projected from the contract
    validator's ``[PASS] minimal_evidence.*`` markers (editable_text,
    not_all_image_slide, every_slide_has_native_shape, no_blank_slide).
  * ``image_provenance`` — one entry per operator image: ``{
    "operator_filename", "asset_id", "sha256",
    "workspace_local_path", "workspace_destination_path",
    "media_type", "byte_count", "embedded_media_parts" }``. The last
    field is the sorted list of ``ppt/media/*`` parts whose sha256
    equals the operator file's sha256, so a reviewer can trace each
    operator filename straight to its embedded PPTX part.
  * ``pptx_path`` — absolute path inside ``--out-dir``.
  * ``workspace_path`` / ``report_dir`` / ``inventory_path`` /
    ``registry_path`` — absolute paths inside ``--out-dir``.
  * ``validators`` — ``{validate_source_image_assets.rc,
    validate_pptx_contract.rc, inspect_pptx_inventory.rc}``.
  * ``real_d_one_status`` — fixed sentence ``"UNVERIFIED"``. Real
    D-One is NOT called. Public network / MCP / model API / image
    search / Qoder / telemetry are NOT called either; the helper is
    local-only by construction.
  * ``notes`` — fixed scope / embed-surface framing copied from the
    same wording the sibling demo uses.
  * ``explicit_boundaries`` — locked tuple of negation-pinned
    sentences naming what the helper does NOT do (real D-One, MCP,
    Qoder, model API, image search, public network, telemetry, raw
    prompt-or-report-to-PPT automation). Identical wording to the
    sibling core demo so the two operator-facing helpers carry a
    consistent boundary statement.

MOCK / STUB / LOCAL-ONLY — NOT real D-One integration. Nothing in
this helper calls D-One, MCP, Qoder, a public network, a model API,
an image search, a browser, telemetry, or any external service. The
operator bytes flow through the existing local pipeline ONLY.

Usage:
  python3 scripts/operator_local_images_to_editable_ppt.py \\
      --images-dir DIR --out-dir OUT

  python3 scripts/operator_local_images_to_editable_ppt.py --self-test

Stdlib only.
"""
from __future__ import annotations

import sys

# Refuse `.pyc` writes from any imported module. Mirrors the gate every
# sibling helper applies; must run BEFORE any first-party import so the
# interpreter sees the flag at bytecode-write time.
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

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
TEMPLATES_DIR = REPO_ROOT / "templates" / "layouts"

sys.path.insert(0, str(SCRIPTS_DIR))

# Reuse the operator --out-dir gate from the sibling core demo so both
# operator-facing entry points enforce one identical contract. A future
# change to the gate is shared.
from core_image_to_editable_ppt_demo import (  # noqa: E402
    _forbidden_symlink_ancestor,
    _validate_out_dir_arg,
)
from materialize_image_assets import (  # noqa: E402
    SUPPORTED_EXTENSIONS,
    _PNG_SIGNATURE,
    _JPEG_SIGNATURE_PREFIX,
)

RUN_EXPLICIT_PIPELINE = SCRIPTS_DIR / "run_explicit_pipeline.py"
VALIDATE_SOURCE_IMAGE_ASSETS = SCRIPTS_DIR / "validate_source_image_assets.py"
VALIDATE_PPTX_CONTRACT = SCRIPTS_DIR / "validate_pptx_contract.py"
INSPECT_PPTX_INVENTORY = SCRIPTS_DIR / "inspect_pptx_inventory.py"

# Hard cap on operator image count. Keeps deck assembly + validation
# runtime bounded and matches the small-deck-only contract the rest of
# the local lane is built around. A real operator deck rarely needs
# more than a dozen accent images; above the cap the helper refuses
# with a clear diagnostic asking the operator to pre-filter.
MAX_IMAGES = 12

# Schema-locked id pattern (mirrors source_image_asset.schema.json's
# id / source_ref pattern). We refuse non-conforming stems at the
# operator boundary rather than silently sanitise — the operator
# notices the rename rather than the helper doing it for them.
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
_ID_MAX_LEN = 128

# Stable fixed identifiers + brief content. The helper is a lane
# verification tool, not a deck authoring tool — the operator gets a
# small editable PPTX with their images embedded; the deck title /
# audience / objective are fixed so the contract is one-shot operator
# input -> one-shot inspectable artifact.
_OPERATOR_SOURCE_ID = "operator_local_images_source"
_DECK_TITLE = "Operator Local-Image Intake Deck"
_DECK_AUDIENCE = "Internal local-image intake reviewer"
_DECK_OBJECTIVE = (
    "Verify operator-supplied local PNG, JPG, and JPEG bytes embed "
    "into an editable PPTX via the local image asset lane."
)
_DECK_SECTION_TITLE = "Operator Image Accents"
_DECK_SECTION_SUMMARY = (
    "One cover slide per operator-supplied local image; each cover "
    "carries the operator file as a native ppt/media accent and a "
    "native editable title text run."
)
_DECK_PLAN_RATIONALE = (
    "One cover slide per operator-supplied local image. Two-line title "
    "names the operator filename so a reviewer can match each "
    "embedded ppt/media part back to its source byte. Local-only; no "
    "D-One, MCP, Qoder, public network, telemetry, or model API."
)
_SOURCE_BODY = (
    "# Operator Local-Image Intake\n\n"
    "Synthetic placeholder body authored by "
    "operator_local_images_to_editable_ppt.py. The helper does NOT "
    "extract business content from this body; only its byte-level "
    "integrity (length / line count / sha256) is checked by "
    "init_workspace.\n"
)

_REAL_D_ONE_STATUS = "UNVERIFIED"

_HELPER_SCOPE_NOTE = (
    "Operator local-image intake helper. Takes a caller-supplied flat "
    "directory of PNG / JPG / JPEG bytes plus a caller-supplied output "
    "directory outside the repo, generates the smallest viable "
    "fixture, drives run_explicit_pipeline.py with the existing "
    "Stage-5.5 materialize step, and validates the produced workspace "
    "+ PPTX via the existing validators. NOT real D-One, NOT MCP, "
    "NOT Qoder, NOT a public network run, NOT telemetry, NOT a prompt "
    "or report to PPTX automation."
)
_HELPER_EMBED_SURFACE_NOTE = (
    "PNG, JPG, and JPEG inside the ppt/media slot of the produced "
    "deck. The subset scripts/export_pptx.py supports today; anything "
    "outside that subset is refused at the operator boundary."
)

# Negation-pinned operator boundary statements — byte-identical to the
# sibling core demo so both operator helpers carry one consistent
# boundary statement. The summary truth-checker enforces verbatim
# equality so a drift in the wording (or a deletion) is refused.
_EXPLICIT_BOUNDARIES: tuple[str, ...] = (
    "No real D-One call; image generation status is UNVERIFIED.",
    "No MCP call.",
    "No Qoder runtime invocation.",
    "No model API contact.",
    "No image search.",
    "No public network access.",
    "No telemetry emission.",
    "Raw prompt or report-to-PPT automation is NOT implemented.",
)

_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


# ---------------------------------------------------------------------------
# --images-dir gate + discovery.
# ---------------------------------------------------------------------------


@dataclass
class _DiscoveredImage:
    """One operator-supplied image. Field set drives both the pipeline
    fixture and the per-image provenance entry in the summary."""

    operator_filename: str         # basename as the operator typed it
    operator_path: Path            # absolute path under --images-dir
    asset_id: str                  # filename stem; matches id pattern
    extension: str                 # lower-cased: png | jpg | jpeg
    media_type: str                # image/png | image/jpeg
    byte_count: int
    sha256: str


def _has_uri_scheme(s: str) -> bool:
    return bool(_URI_SCHEME_PREFIX.match(s))


def _media_type_for_ext(ext: str) -> str:
    return "image/png" if ext == "png" else "image/jpeg"


def _matches_image_signature(extension: str, payload: bytes) -> bool:
    """Mirrors materialize_image_assets._matches_image_signature."""
    if extension == "png":
        return payload.startswith(_PNG_SIGNATURE)
    if extension in ("jpg", "jpeg"):
        return payload.startswith(_JPEG_SIGNATURE_PREFIX)
    return False


def _sha256_of(path: Path) -> tuple[int, str, bytes]:
    """Return (byte_count, lowercase-hex sha256, first-8-byte prefix)
    by streaming the file in chunks; only the first 8 bytes are kept
    in memory for the magic-byte gate."""
    h = hashlib.sha256()
    total = 0
    first: bytes = b""
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            if not first:
                first = chunk[:8]
            h.update(chunk)
            total += len(chunk)
    return total, h.hexdigest(), first


def _validate_images_dir_arg(
    images_dir_str: str,
) -> tuple[list[_DiscoveredImage] | None, Path | None, list[str]]:
    """Validate ``--images-dir`` and return the discovered image list.

    Returns ``(images_or_None, resolved_dir_or_None, failures)``. The
    caller MUST treat the argument as refused whenever ``failures`` is
    non-empty OR either positional return is ``None``.

    Refuses, in order, BEFORE any pipeline subprocess fires:

      * IG1 URI-shaped argument;
      * IG2 ``--images-dir`` is itself a symlink (broken or resolvable);
      * IG3 any ancestor up to the filesystem root is a symlink;
      * IG4 path exists, is a directory, and is non-empty;
      * IG5 every root entry is a regular non-symlink PNG / JPG / JPEG
        file (subdirs / symlinks / devices / FIFOs / sockets refused);
      * IG6 every filename stem matches the schema id pattern;
      * IG7 no two filenames share a stem;
      * IG8 each file's first bytes match the magic-byte signature for
        its declared extension;
      * IG9 the operator image count is at most ``MAX_IMAGES`` —
        checked AFTER the cheap structural gates (IG5..IG7) but BEFORE
        any byte-level read so an over-cap folder is refused without
        hashing or even opening a single image file.
    """
    if _has_uri_scheme(images_dir_str):
        return None, None, [
            f"--images-dir argument {images_dir_str!r} looks URI-shaped "
            f"(IG1); only local directory paths are accepted."
        ]

    images_dir = Path(images_dir_str)

    if images_dir.is_symlink():
        try:
            tgt = os.readlink(images_dir)
        except OSError:
            tgt = "<unreadable>"
        return None, None, [
            f"--images-dir {images_dir} is a symlink (-> {tgt}) (IG2); "
            f"refused so a symlink target cannot redirect what bytes "
            f"the helper ingests."
        ]

    forbidden_ancestor = _forbidden_symlink_ancestor(images_dir)
    if forbidden_ancestor is not None:
        ancestor, tgt = forbidden_ancestor
        return None, None, [
            f"--images-dir {images_dir} has a symlink ancestor "
            f"{ancestor} (-> {tgt}) (IG3); refused so a symlink in "
            f"the operator's typed path cannot redirect what bytes "
            f"the helper ingests."
        ]

    if not images_dir.exists():
        return None, None, [
            f"--images-dir {images_dir} does not exist (IG4)."
        ]
    if not images_dir.is_dir():
        return None, None, [
            f"--images-dir {images_dir} is not a directory (IG4)."
        ]

    try:
        entries = sorted(images_dir.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        return None, None, [
            f"--images-dir {images_dir} cannot be listed: "
            f"{type(exc).__name__}: {exc} (IG4)."
        ]
    if not entries:
        return None, None, [
            f"--images-dir {images_dir} is empty (IG4); the helper "
            f"refuses to stage a zero-image deck."
        ]

    # Pass 1 — cheap structural gates only (symlink / kind / extension /
    # id pattern / stem collision). No file-content I/O happens here:
    # ``is_symlink`` / ``is_dir`` / ``is_file`` rely on ``stat()`` which
    # the directory listing has already paged. A directory with 1000
    # valid PNGs whose count exceeds ``MAX_IMAGES`` MUST be refused at
    # the IG9 cap check below without opening or hashing any file —
    # delaying the cap check to after hashing would waste O(total bytes)
    # of I/O before the diagnostic fires.
    failures: list[str] = []
    candidates: list[tuple[Path, str, str]] = []  # (entry, stem, ext)
    stems_seen: dict[str, str] = {}

    for entry in entries:
        rel = entry.name
        if entry.is_symlink():
            try:
                tgt = os.readlink(entry)
            except OSError:
                tgt = "<unreadable>"
            failures.append(
                f"--images-dir entry {rel!r} is a symlink (-> {tgt}) "
                f"(IG5); refused so a symlink target cannot inject "
                f"bytes from outside the operator-controlled directory."
            )
            continue
        if entry.is_dir():
            failures.append(
                f"--images-dir entry {rel!r} is a subdirectory (IG5); "
                f"the helper does not recurse — flatten the directory "
                f"or pass a different --images-dir."
            )
            continue
        if not entry.is_file():
            failures.append(
                f"--images-dir entry {rel!r} is not a regular file "
                f"(device / FIFO / socket / etc.) (IG5); refused."
            )
            continue

        ext = entry.suffix.lower().lstrip(".")
        if ext not in SUPPORTED_EXTENSIONS:
            failures.append(
                f"--images-dir entry {rel!r} extension {ext!r} is not "
                f"in the supported set {sorted(SUPPORTED_EXTENSIONS)} "
                f"(IG5); the PPTX exporter falls back to a placeholder "
                f"shape for any other extension."
            )
            continue

        stem = entry.stem
        if not _ID_PATTERN.match(stem) or len(stem) > _ID_MAX_LEN:
            failures.append(
                f"--images-dir entry {rel!r} stem {stem!r} does not "
                f"match the schema id pattern "
                f"{_ID_PATTERN.pattern!r} (IG6); rename the file to "
                f"start with a letter or digit and use only letters, "
                f"digits, underscore, dot, or hyphen "
                f"(<= {_ID_MAX_LEN} chars)."
            )
            continue

        if stem in stems_seen:
            failures.append(
                f"--images-dir entry {rel!r} shares its stem {stem!r} "
                f"with {stems_seen[stem]!r} (IG7); two files cannot "
                f"share a stem because they would collide on the "
                f"workspace assets/<id>.<ext> slot and the registry id."
            )
            continue
        stems_seen[stem] = rel

        candidates.append((entry, stem, ext))

    if failures:
        return None, None, failures

    if not candidates:
        # All entries were rejected above. Should be unreachable when
        # ``failures`` was empty, but guard anyway.
        return None, None, [
            f"--images-dir {images_dir} carried no structurally "
            f"acceptable images."
        ]

    # IG9 cap — BEFORE any byte-level read. A directory with 1000 PNGs
    # is refused with a single diagnostic and zero file content opened.
    # T15 in --self-test plants ``MAX_IMAGES + 1`` files whose bytes
    # would fail the magic-byte gate; the probe asserts the IG9 cap
    # diagnostic fires AND no IG8 diagnostic appears, so a regression
    # that moves this check back after Pass 2 is caught.
    if len(candidates) > MAX_IMAGES:
        return None, None, [
            f"--images-dir {images_dir} carries {len(candidates)} "
            f"acceptable images; the helper caps the deck at "
            f"{MAX_IMAGES} (IG9). Pre-filter the directory and re-run."
        ]

    # Pass 2 — per-candidate byte-level gates (size, hash, magic-byte).
    # Reached only when the directory has at most MAX_IMAGES candidates,
    # so we never hash more files than the cap.
    discovered: list[_DiscoveredImage] = []
    for entry, stem, ext in candidates:
        rel = entry.name
        try:
            byte_count, sha256, first = _sha256_of(entry)
        except OSError as exc:
            failures.append(
                f"--images-dir entry {rel!r} cannot be read: "
                f"{type(exc).__name__}: {exc} (IG5)."
            )
            continue
        if byte_count == 0:
            failures.append(
                f"--images-dir entry {rel!r} is empty (0 bytes) (IG5); "
                f"the source_image_asset schema requires byte_count >= 1."
            )
            continue
        if not _matches_image_signature(ext, first):
            failures.append(
                f"--images-dir entry {rel!r} first bytes do not match "
                f"the magic-byte signature for the declared extension "
                f"{ext!r} (IG8); first 8 bytes = {first!r}."
            )
            continue

        discovered.append(_DiscoveredImage(
            operator_filename=rel,
            operator_path=entry,
            asset_id=stem,
            extension=ext,
            media_type=_media_type_for_ext(ext),
            byte_count=byte_count,
            sha256=sha256,
        ))

    if failures:
        return None, None, failures

    if not discovered:
        # Defensive — every candidate failed Pass 2 silently (should
        # not be reachable because failures would be non-empty above).
        return None, None, [
            f"--images-dir {images_dir} carried no acceptable images "
            f"after byte-level gates."
        ]

    return discovered, images_dir, []


# ---------------------------------------------------------------------------
# Pipeline fixture composition.
# ---------------------------------------------------------------------------


def _write_json(path: Path, body: dict) -> None:
    """Deterministic JSON writer (indent=2, sort_keys=True, trailing
    newline) so two runs from byte-identical inputs produce
    byte-identical fixture bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _cover_title_for(image: _DiscoveredImage) -> str:
    """Slide title naming the operator filename so a reviewer can match
    each embedded ppt/media part back to its source byte just by
    opening the deck. Title length is bounded by the operator filename
    + a fixed prefix (no derived content from the image bytes)."""
    return f"Operator image: {image.operator_filename}"


def _build_pipeline_fixture(
    *,
    fixture_root: Path,
    images: list[_DiscoveredImage],
) -> dict:
    """Author the smallest viable explicit-input fixture.

    Layout (all under ``fixture_root``):

      source.md                  caller-supplied placeholder body.
      plan_spec.json             N-cover deck plan.
      specs/<idx:02d>_cover.json one per cover.
      image_manifest_spec.json   one images[] entry per operator image.
      assets/<id>.<ext>          operator bytes copied here for the
                                 Stage-5.5 materialize step to ingest.

    Returns a dict naming the source / plan_spec / specs_dir /
    image_manifest_spec / assets_dir paths run_explicit_pipeline.py
    will receive on its CLI."""
    fixture_root.mkdir(parents=True, exist_ok=True)

    source = fixture_root / "source.md"
    source.write_text(_SOURCE_BODY, encoding="utf-8")

    slides_block: list[dict] = []
    sections_indices: list[int] = []
    specs_dir = fixture_root / "specs"
    specs_dir.mkdir()
    assets_dir = fixture_root / "assets"
    assets_dir.mkdir()

    images_block: list[dict] = []

    for idx, image in enumerate(images, start=1):
        title = _cover_title_for(image)
        slides_block.append({
            "index": idx,
            "layout": "cover",
            "title": title,
            "section_id": "operator_images",
            "summary": (
                f"Cover slide for operator image "
                f"{image.operator_filename!r} (id={image.asset_id!r})."
            ),
            "density": "low",
            "source_refs": [_OPERATOR_SOURCE_ID],
        })
        sections_indices.append(idx)
        _write_json(
            specs_dir / f"{idx:02d}_cover.json",
            {
                "index": idx,
                "layout": "cover",
                "title": title,
                "blocks": [
                    {
                        "id": "title",
                        "kind": "text",
                        "content": title,
                    },
                    {
                        "id": "accent",
                        "kind": "image_ref",
                        "content": image.asset_id,
                    },
                ],
                "image_refs": [image.asset_id],
            },
        )
        images_block.append({
            "id": image.asset_id,
            "local_path": f"assets/{image.asset_id}.{image.extension}",
            "source": "local_asset",
            "alt_text": (
                f"Operator-supplied local image "
                f"{image.operator_filename!r}."
            ),
            "intended_use": "spot illustration",
        })
        # Stage --assets-dir: bytes the Stage-5.5 materialize step
        # copies into <workspace>/<image_manifest local_path>. The
        # operator's original file is left untouched.
        shutil.copyfile(
            image.operator_path,
            assets_dir / f"{image.asset_id}.{image.extension}",
        )

    _write_json(fixture_root / "plan_spec.json", {
        "template": "business_review",
        "planning": {
            "planned_slide_count": len(images),
            "rationale": _DECK_PLAN_RATIONALE,
        },
        "sections": [
            {
                "id": "operator_images",
                "title": _DECK_SECTION_TITLE,
                "summary": _DECK_SECTION_SUMMARY,
                "slide_indices": sections_indices,
            },
        ],
        "slides": slides_block,
    })

    _write_json(
        fixture_root / "image_manifest_spec.json",
        {"images": images_block},
    )

    return {
        "source": source,
        "plan_spec": fixture_root / "plan_spec.json",
        "specs_dir": specs_dir,
        "image_manifest_spec": (
            fixture_root / "image_manifest_spec.json"
        ),
        # The Stage-5.5 materialize step copies
        # ``<assets-dir>/<image_manifest local_path>`` ->
        # ``<workspace>/<local_path>``. The image_manifest declares
        # ``local_path = assets/<id>.<ext>``, so the staging directory
        # the orchestrator receives must contain an ``assets/`` subdir;
        # the bytes themselves live one level deeper. Passing the leaf
        # ``assets/`` directly would make the orchestrator look for
        # ``<assets-dir>/assets/<id>.<ext>`` (double ``assets/``).
        "assets_dir": fixture_root,
    }


def _pipeline_args(
    *,
    fixture: dict,
    workspace: Path,
    output: Path,
    report_dir: Path,
) -> list[str]:
    return [
        sys.executable, str(RUN_EXPLICIT_PIPELINE),
        "--workspace", str(workspace),
        "--source", str(fixture["source"]),
        "--source-id", _OPERATOR_SOURCE_ID,
        "--title", _DECK_TITLE,
        "--audience", _DECK_AUDIENCE,
        "--objective", _DECK_OBJECTIVE,
        "--plan-spec", str(fixture["plan_spec"]),
        "--slide-specs-dir", str(fixture["specs_dir"]),
        "--image-manifest-spec", str(fixture["image_manifest_spec"]),
        "--template-root", str(TEMPLATES_DIR),
        "--theme-from-template",
        "--assets-dir", str(fixture["assets_dir"]),
        "--output", str(output),
        "--report-dir", str(report_dir),
    ]


# ---------------------------------------------------------------------------
# Subprocess runners.
# ---------------------------------------------------------------------------


@dataclass
class _ToolOutcome:
    name: str
    rc: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.rc == 0

    @property
    def combined(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


def _run(name: str, cmd: list[str]) -> _ToolOutcome:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    return _ToolOutcome(
        name=name, rc=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


def _print_outcome_tail(outcome: _ToolOutcome) -> None:
    for stream_name, body in (
        ("stdout", outcome.stdout),
        ("stderr", outcome.stderr),
    ):
        tail = (body or "").splitlines()[-12:]
        if tail:
            print(f"    {stream_name} tail:")
            for line in tail:
                print(f"      {line}")


# ---------------------------------------------------------------------------
# Source-attached registry + provenance.
# ---------------------------------------------------------------------------


def _author_source_registry(
    *,
    workspace: Path,
    images: list[_DiscoveredImage],
) -> Path:
    """Copy each operator file into ``<workspace>/input/assets/<id>.<ext>``
    and write ``<workspace>/source_image_assets.json`` so the
    ``validate_source_image_assets`` (G1..G13) validator can run against
    a workspace that already ships ``source_manifest.json`` (Stage 1) +
    ``image_manifest.json`` (Stage 6) from the pipeline run.

    Per asset, the registry destination_path matches the image_manifest
    local_path the orchestrator wrote (G10); the registry local_path is
    the canonical ``input/assets/<id>.<ext>`` propagation location
    declared in ``references/source-image-asset-policy.md``."""
    (workspace / "input" / "assets").mkdir(parents=True, exist_ok=True)
    registry_assets: list[dict] = []
    for image in images:
        leaf = (
            workspace / "input" / "assets"
            / f"{image.asset_id}.{image.extension}"
        )
        shutil.copyfile(image.operator_path, leaf)
        registry_assets.append({
            "id": image.asset_id,
            "source_ref": _OPERATOR_SOURCE_ID,
            "local_path": (
                f"input/assets/{image.asset_id}.{image.extension}"
            ),
            "destination_path": (
                f"assets/{image.asset_id}.{image.extension}"
            ),
            "media_type": image.media_type,
            "byte_count": image.byte_count,
            "sha256": image.sha256,
        })
    registry_path = workspace / "source_image_assets.json"
    _write_json(registry_path, {
        "schema_version": "1",
        "assets": registry_assets,
    })
    return registry_path


def _provenance_for(
    *,
    image: _DiscoveredImage,
    pptx_media_shas: dict[str, list[str]],
) -> dict:
    """Per-image provenance record. ``pptx_media_shas`` maps each
    operator sha256 to the sorted list of ``ppt/media/*`` parts that
    carry the same bytes; the empty list means the operator file did
    not embed (regression — the truth-checker refuses)."""
    return {
        "operator_filename": image.operator_filename,
        "asset_id": image.asset_id,
        "media_type": image.media_type,
        "byte_count": image.byte_count,
        "sha256": image.sha256,
        "workspace_local_path": (
            f"input/assets/{image.asset_id}.{image.extension}"
        ),
        "workspace_destination_path": (
            f"assets/{image.asset_id}.{image.extension}"
        ),
        "embedded_media_parts": sorted(
            pptx_media_shas.get(image.sha256, [])
        ),
    }


def _walk_pptx_media(pptx: Path) -> dict[str, list[str]]:
    """Open the PPTX as a ZIP and return a sha256 -> sorted list of
    ``ppt/media/*`` part names. Used to attribute every operator
    image's sha256 to its embedded media part(s) for the provenance
    record AND for the truth-checker's "every image embedded" gate."""
    out: dict[str, list[str]] = {}
    with zipfile.ZipFile(pptx, "r") as zf:
        for name in sorted(zf.namelist()):
            if not name.startswith("ppt/media/"):
                continue
            payload = zf.read(name)
            digest = hashlib.sha256(payload).hexdigest()
            out.setdefault(digest, []).append(name)
    for k in out:
        out[k] = sorted(out[k])
    return out


# ---------------------------------------------------------------------------
# Summary assembly + truth-check.
# ---------------------------------------------------------------------------


def _project_contract_gates(stdout: str) -> dict[str, bool]:
    """Project the contract validator's PASS markers onto the booleans
    the summary surfaces. Mirrors the same projection the sibling core
    demo uses; absence of a marker counts as False."""
    out: dict[str, bool] = {}
    for gate in (
        "minimal_evidence.editable_text",
        "minimal_evidence.not_all_image_slide",
        "minimal_evidence.every_slide_has_native_shape",
        "minimal_evidence.no_blank_slide",
        "relationships.no_external",
        "relationships.no_file_uri",
        "relationships.allow_list",
    ):
        out[gate] = f"[PASS] {gate}" in stdout
    return out


def _count_external_relationships_from_inventory(inv: dict) -> int:
    n = 0
    rels = inv.get("relationships") or []
    if not isinstance(rels, list):
        return 0
    for entry in rels:
        if not isinstance(entry, dict):
            continue
        tm = entry.get("target_mode")
        tg = entry.get("target")
        if isinstance(tm, str) and tm.lower() == "external":
            n += 1
            continue
        if isinstance(tg, str) and _URI_SCHEME_PREFIX.match(tg):
            n += 1
            continue
        if isinstance(tg, str) and tg.lower().startswith("file://"):
            n += 1
    return n


def _embedded_media_count_from_inventory(inv: dict) -> int:
    embeds: set[str] = set()
    for entry in inv.get("media_parts") or []:
        if not isinstance(entry, dict):
            continue
        part = entry.get("part")
        ext = entry.get("extension")
        if not isinstance(part, str) or not isinstance(ext, str):
            continue
        if ext.lower() not in {"png", "jpg", "jpeg"}:
            continue
        if not part.startswith("ppt/media/"):
            continue
        embeds.add(part)
    return len(embeds)


def _build_summary(
    *,
    images: list[_DiscoveredImage],
    pptx_path: Path,
    workspace: Path,
    report_dir: Path,
    inventory_path: Path,
    registry_path: Path,
    inventory: dict,
    contract: _ToolOutcome,
    inventory_outcome: _ToolOutcome,
    registry_outcome: _ToolOutcome,
    pptx_media_shas: dict[str, list[str]],
) -> dict:
    contract_pass = _project_contract_gates(contract.stdout or "")
    return {
        "schema_version": "1",
        "helper_id": "operator_local_images_to_editable_ppt",
        "real_d_one_status": _REAL_D_ONE_STATUS,
        "slide_count": inventory.get("slide_count"),
        "image_count": len(images),
        "embedded_media_count": _embedded_media_count_from_inventory(
            inventory,
        ),
        "source_classes": ["local_asset"],
        "minimal_evidence": {
            "editable_text": contract_pass.get(
                "minimal_evidence.editable_text", False,
            ),
            "not_all_image_slide": contract_pass.get(
                "minimal_evidence.not_all_image_slide", False,
            ),
            "every_slide_has_native_shape": contract_pass.get(
                "minimal_evidence.every_slide_has_native_shape", False,
            ),
            "no_blank_slide": contract_pass.get(
                "minimal_evidence.no_blank_slide", False,
            ),
        },
        "no_external_relationships": (
            contract_pass.get("relationships.no_external", False)
            and contract_pass.get("relationships.no_file_uri", False)
            and contract_pass.get("relationships.allow_list", False)
            and _count_external_relationships_from_inventory(inventory)
            == 0
        ),
        "image_provenance": [
            _provenance_for(image=img, pptx_media_shas=pptx_media_shas)
            for img in images
        ],
        "pptx_path": str(pptx_path),
        "workspace_path": str(workspace),
        "report_dir": str(report_dir),
        "inventory_path": str(inventory_path),
        "registry_path": str(registry_path),
        "inventory": {
            "ok": inventory.get("ok") is True,
            "findings_empty": (inventory.get("findings") or []) == [],
            "evidence_basis": inventory.get("evidence_basis"),
        },
        "validators": {
            "validate_source_image_assets": {"rc": registry_outcome.rc},
            "validate_pptx_contract": {"rc": contract.rc},
            "inspect_pptx_inventory": {"rc": inventory_outcome.rc},
        },
        "notes": {
            "scope": _HELPER_SCOPE_NOTE,
            "embed_surface": _HELPER_EMBED_SURFACE_NOTE,
        },
        "explicit_boundaries": list(_EXPLICIT_BOUNDARIES),
    }


def _check_summary_truth(summary: dict) -> list[str]:
    """In-script truth-checker. Returns a list of failure diagnostics;
    empty list means the summary describes a healthy run."""
    failures: list[str] = []

    if summary.get("helper_id") != "operator_local_images_to_editable_ppt":
        failures.append(
            f"summary.helper_id={summary.get('helper_id')!r}; expected "
            f"'operator_local_images_to_editable_ppt'"
        )
    if summary.get("schema_version") != "1":
        failures.append(
            f"summary.schema_version={summary.get('schema_version')!r}; "
            f"expected '1'"
        )
    if summary.get("real_d_one_status") != _REAL_D_ONE_STATUS:
        failures.append(
            f"summary.real_d_one_status="
            f"{summary.get('real_d_one_status')!r}; expected "
            f"{_REAL_D_ONE_STATUS!r}"
        )

    image_count = summary.get("image_count")
    slide_count = summary.get("slide_count")
    embedded = summary.get("embedded_media_count")
    if not isinstance(image_count, int) or image_count < 1:
        failures.append(
            f"summary.image_count={image_count!r}; expected int >= 1"
        )
    if (
        isinstance(image_count, int)
        and (not isinstance(slide_count, int) or slide_count != image_count)
    ):
        failures.append(
            f"summary.slide_count={slide_count!r}; expected "
            f"{image_count!r} (one cover slide per operator image)"
        )
    if (
        isinstance(image_count, int)
        and (not isinstance(embedded, int) or embedded != image_count)
    ):
        failures.append(
            f"summary.embedded_media_count={embedded!r}; expected "
            f"{image_count!r} (one ppt/media part per operator image)"
        )

    if summary.get("source_classes") != ["local_asset"]:
        failures.append(
            f"summary.source_classes={summary.get('source_classes')!r}; "
            f"expected ['local_asset'] (the helper is local-only)"
        )

    mev = summary.get("minimal_evidence") or {}
    for gate in (
        "editable_text", "not_all_image_slide",
        "every_slide_has_native_shape", "no_blank_slide",
    ):
        if mev.get(gate) is not True:
            failures.append(
                f"summary.minimal_evidence.{gate}={mev.get(gate)!r}; "
                f"expected True (validate_pptx_contract must emit "
                f"'[PASS] minimal_evidence.{gate}')"
            )

    if summary.get("no_external_relationships") is not True:
        failures.append(
            f"summary.no_external_relationships="
            f"{summary.get('no_external_relationships')!r}; expected "
            f"True (no external / file:// / URI-scheme relationship "
            f"allowed in the produced PPTX)"
        )

    inv = summary.get("inventory") or {}
    if inv.get("ok") is not True:
        failures.append(
            f"summary.inventory.ok={inv.get('ok')!r}; expected True"
        )
    if inv.get("findings_empty") is not True:
        failures.append(
            f"summary.inventory.findings_empty="
            f"{inv.get('findings_empty')!r}; expected True"
        )

    val = summary.get("validators") or {}
    for k in (
        "validate_source_image_assets",
        "validate_pptx_contract",
        "inspect_pptx_inventory",
    ):
        rc = (val.get(k) or {}).get("rc")
        if rc != 0:
            failures.append(
                f"summary.validators.{k}.rc={rc!r}; expected 0"
            )

    prov = summary.get("image_provenance")
    if not isinstance(prov, list) or len(prov) != (image_count or -1):
        failures.append(
            f"summary.image_provenance length={len(prov) if isinstance(prov, list) else 'n/a'}; "
            f"expected one entry per operator image ({image_count!r})"
        )
    elif isinstance(prov, list):
        for i, entry in enumerate(prov):
            if not isinstance(entry, dict):
                failures.append(
                    f"summary.image_provenance[{i}] is not an object"
                )
                continue
            parts = entry.get("embedded_media_parts")
            if not isinstance(parts, list) or not parts:
                failures.append(
                    f"summary.image_provenance[{i}] for "
                    f"{entry.get('operator_filename')!r} has "
                    f"embedded_media_parts={parts!r}; expected at "
                    f"least one ppt/media/* part whose sha256 equals "
                    f"the operator file's sha256 (the bytes must have "
                    f"reached the PPTX)"
                )

    boundaries = summary.get("explicit_boundaries")
    if boundaries != list(_EXPLICIT_BOUNDARIES):
        failures.append(
            f"summary.explicit_boundaries={boundaries!r}; expected "
            f"the locked tuple {list(_EXPLICIT_BOUNDARIES)!r} verbatim"
        )
    return failures


# ---------------------------------------------------------------------------
# Happy path.
# ---------------------------------------------------------------------------


def _run_happy_path(
    *,
    out_dir: Path,
    images: list[_DiscoveredImage],
) -> tuple[int, dict | None, Path | None]:
    """Build the fixture under ``out_dir``, drive the pipeline, run the
    validators, and write the summary. Returns ``(rc, summary,
    summary_path)``. Leaves every artifact on disk for inspection on
    failure too."""
    print(
        f"--- operator local-image intake: "
        f"{len(images)} image(s) -> editable PPTX ---"
    )
    for image in images:
        print(
            f"  image:     {image.operator_filename!r} "
            f"(id={image.asset_id!r}, {image.media_type}, "
            f"{image.byte_count} bytes, "
            f"sha256={image.sha256[:12]}...)"
        )

    fixture_root = out_dir / "_pipeline_fixture"
    workspace = out_dir / "workspace"
    report_dir = out_dir / "reports"
    output = out_dir / "deck.pptx"
    inventory_path = out_dir / "inventory.json"
    summary_path = out_dir / "summary.json"

    fixture = _build_pipeline_fixture(
        fixture_root=fixture_root, images=images,
    )

    print(f"  fixture:   {fixture_root}")
    print(f"  workspace: {workspace}")
    print(f"  output:    {output}")
    print(f"  report:    {report_dir}")

    # Stage A — run_explicit_pipeline.py (Stage 1-10 + Stage-5.5
    # materialize step).
    pipeline = _run(
        "run_explicit_pipeline",
        _pipeline_args(
            fixture=fixture, workspace=workspace,
            output=output, report_dir=report_dir,
        ),
    )
    if not pipeline.ok:
        print(f"  [FAIL] run_explicit_pipeline rc={pipeline.rc}")
        _print_outcome_tail(pipeline)
        return 1, None, None
    print(f"  [PASS] run_explicit_pipeline rc=0")

    if not output.is_file() or output.is_symlink():
        print(
            f"  [FAIL] expected produced PPTX as a regular non-symlink "
            f"file at {output}"
        )
        return 1, None, None
    print(f"  [PASS] produced PPTX exists as a regular non-symlink file")

    # Stage B — author the source-attached registry and run G1..G13.
    registry_path = _author_source_registry(
        workspace=workspace, images=images,
    )
    registry_outcome = _run(
        "validate_source_image_assets",
        [
            sys.executable, str(VALIDATE_SOURCE_IMAGE_ASSETS),
            "--workspace", str(workspace),
        ],
    )
    if not registry_outcome.ok:
        print(
            f"  [FAIL] validate_source_image_assets "
            f"rc={registry_outcome.rc}"
        )
        _print_outcome_tail(registry_outcome)
        return 1, None, None
    print(f"  [PASS] validate_source_image_assets rc=0")

    # Stage C — contract validator with the expected slide count.
    contract = _run(
        "validate_pptx_contract",
        [
            sys.executable, str(VALIDATE_PPTX_CONTRACT),
            "--pptx", str(output),
            "--expected-slide-count", str(len(images)),
        ],
    )
    if not contract.ok:
        print(f"  [FAIL] validate_pptx_contract rc={contract.rc}")
        _print_outcome_tail(contract)
        return 1, None, None
    print(f"  [PASS] validate_pptx_contract rc=0")

    # Stage D — inventory readback into <out-dir>/inventory.json.
    inventory_outcome = _run(
        "inspect_pptx_inventory",
        [
            sys.executable, str(INSPECT_PPTX_INVENTORY),
            "--pptx", str(output),
            "--out", str(inventory_path),
        ],
    )
    if not inventory_outcome.ok:
        print(
            f"  [FAIL] inspect_pptx_inventory rc={inventory_outcome.rc}"
        )
        _print_outcome_tail(inventory_outcome)
        return 1, None, None
    print(f"  [PASS] inspect_pptx_inventory rc=0")

    try:
        inventory = json.loads(inventory_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"  [FAIL] cannot parse {inventory_path}: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1, None, None

    # Stage E — walk the PPTX media parts and attribute each operator
    # sha256 to its embedded part(s) for the provenance record.
    try:
        pptx_media_shas = _walk_pptx_media(output)
    except (zipfile.BadZipFile, OSError) as exc:
        print(
            f"  [FAIL] cannot walk PPTX media at {output}: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1, None, None

    summary = _build_summary(
        images=images,
        pptx_path=output,
        workspace=workspace,
        report_dir=report_dir,
        inventory_path=inventory_path,
        registry_path=registry_path,
        inventory=inventory,
        contract=contract,
        inventory_outcome=inventory_outcome,
        registry_outcome=registry_outcome,
        pptx_media_shas=pptx_media_shas,
    )

    truth_failures = _check_summary_truth(summary)
    if truth_failures:
        print(
            f"  [FAIL] summary truth-check refused "
            f"({len(truth_failures)} failure(s)):"
        )
        for f in truth_failures:
            print(f"    - {f}")
        return 1, summary, None

    # The summary is written ONLY after the truth-checker passes so a
    # tampered run cannot leave a positive-looking summary on disk.
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not summary_path.is_file() or summary_path.is_symlink():
        print(
            f"  [FAIL] expected summary at {summary_path} as a regular "
            f"non-symlink file"
        )
        return 1, summary, None
    print(f"  [PASS] summary written to {summary_path}")

    # Echo a compact view to stdout so a reviewer sees the milestone
    # truth without opening the JSON file.
    print()
    print("--- summary ---")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print()
    return 0, summary, summary_path


# ---------------------------------------------------------------------------
# Operator mode entrypoint.
# ---------------------------------------------------------------------------


def _run_operator_mode(*, images_dir_str: str, out_dir_str: str) -> int:
    """Validate both operator arguments, create ``--out-dir`` if needed,
    and drive the happy path. Returns 0 on success, 1 on any failure
    (with partial artifacts left under ``--out-dir`` for inspection),
    2 on operator-input refusal (no filesystem mutation)."""
    images, _images_dir, image_failures = _validate_images_dir_arg(
        images_dir_str,
    )
    out_dir, out_failures = _validate_out_dir_arg(out_dir_str)

    # Report BOTH argument refusals so the operator does not have to
    # re-run twice to find every input problem.
    if image_failures or out_failures or images is None or out_dir is None:
        for line in image_failures or []:
            print(f"FAIL: {line}", file=sys.stderr)
        for line in out_failures or []:
            print(f"FAIL: {line}", file=sys.stderr)
        return 2

    if not out_dir.exists():
        try:
            out_dir.mkdir(parents=False, exist_ok=False)
        except OSError as exc:
            print(
                f"FAIL: cannot create --out-dir {out_dir}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 1

    print(
        f"=== operator_local_images_to_editable_ppt "
        f"(--images-dir {images_dir_str}, --out-dir {out_dir}) ==="
    )
    rc, summary, summary_path = _run_happy_path(
        out_dir=out_dir, images=images,
    )
    if rc != 0 or summary is None or summary_path is None:
        print(
            f"FAIL (operator mode): pipeline did not complete; inspect "
            f"{out_dir} for partial artifacts.",
            file=sys.stderr,
        )
        return 1
    print(
        f"OK (operator mode): inspectable artifacts under {out_dir}. "
        f"Real D-One UNVERIFIED. No public network, no MCP, no Qoder, "
        f"no model API, no image search, no telemetry. Raw prompt or "
        f"report-to-PPT automation NOT implemented."
    )
    return 0


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs inside a per-run tempdir;
# flat-bytes snapshots of REPO_ROOT/scripts/ and REPO_ROOT/examples/
# taken before and after the run must match — proves nothing leaks.
# ---------------------------------------------------------------------------


# Minimum-viable magic-byte-valid PNG / JPEG payloads. Byte-distinct so
# sha256(PNG) != sha256(JPEG) and the per-image provenance attribution
# can prove "every operator file embedded" honestly.
_TINY_PNG_BYTES: bytes = bytes.fromhex(
    "89504e470d0a1a0a"
    "0000000d49484452"
    "0000000100000001"
    "08060000001f15c489"
    "0000000d49444154"
    "789c6300010000000500010d0a2db4"
    "0000000049454e44ae426082"
)
_TINY_JPEG_BYTES: bytes = (
    b"\xff\xd8\xff\xe0"
    b"\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xd9"
)


def _snapshot_dir(d: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        out[str(p.relative_to(d))] = p.read_bytes()
    return out


def _check_repo_unchanged(
    *,
    examples_before: dict[str, bytes],
    scripts_before: dict[str, bytes],
) -> int:
    rc = 0
    examples_after = _snapshot_dir(REPO_ROOT / "examples")
    if examples_before != examples_after:
        changed = sorted(
            k for k in set(examples_before) | set(examples_after)
            if examples_before.get(k) != examples_after.get(k)
        )
        print(
            f"FAIL: examples/ was mutated by self-test (changed: "
            f"{changed!r})",
            file=sys.stderr,
        )
        rc = 1
    scripts_after = _snapshot_dir(REPO_ROOT / "scripts")
    if scripts_before != scripts_after:
        changed = sorted(
            k for k in set(scripts_before) | set(scripts_after)
            if scripts_before.get(k) != scripts_after.get(k)
        )
        print(
            f"FAIL: scripts/ was mutated by self-test (changed: "
            f"{changed!r})",
            file=sys.stderr,
        )
        rc = 1
    return rc


def _write_synthetic_images(images_dir: Path) -> None:
    """Write one PNG + one JPEG into ``images_dir``. Stem matches the
    schema id pattern so the helper accepts them without renaming."""
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / "alpha_marker.png").write_bytes(_TINY_PNG_BYTES)
    (images_dir / "beta_marker.jpg").write_bytes(_TINY_JPEG_BYTES)


@dataclass
class _ProbeResult:
    name: str
    ok: bool
    detail: str = ""


def _run_self_tests() -> int:
    print("=== operator_local_images_to_editable_ppt --self-test ===")
    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    scripts_before = _snapshot_dir(REPO_ROOT / "scripts")

    results: list[_ProbeResult] = []

    # T1 happy path: synthetic PNG + JPEG -> 2-slide editable PPTX.
    with tempfile.TemporaryDirectory(prefix="op-helper-T1-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        _write_synthetic_images(images_dir)
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
        )
        ok = rc == 0
        detail = ""
        if ok:
            # Spot-check the summary was written and lists both images
            # with embedded media parts.
            summary_path = out_dir / "summary.json"
            try:
                summary = json.loads(summary_path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                ok = False
                detail = f"cannot parse {summary_path}: {exc}"
            else:
                if summary.get("image_count") != 2:
                    ok = False
                    detail = (
                        f"image_count={summary.get('image_count')!r}, "
                        f"expected 2"
                    )
                elif summary.get("slide_count") != 2:
                    ok = False
                    detail = (
                        f"slide_count={summary.get('slide_count')!r}, "
                        f"expected 2"
                    )
                elif summary.get("embedded_media_count") != 2:
                    ok = False
                    detail = (
                        f"embedded_media_count="
                        f"{summary.get('embedded_media_count')!r}, "
                        f"expected 2"
                    )
                elif not summary.get("no_external_relationships"):
                    ok = False
                    detail = "no_external_relationships is not True"
                else:
                    prov = summary.get("image_provenance") or []
                    if not all(
                        p.get("embedded_media_parts")
                        for p in prov
                    ):
                        ok = False
                        detail = (
                            f"image_provenance missing media parts: "
                            f"{prov!r}"
                        )
        if not ok and not detail:
            detail = f"rc={rc}"
        results.append(_ProbeResult(
            "T1 happy path: synthetic PNG + JPEG into a fresh --out-dir "
            "-> 2-slide editable PPTX with provenance",
            ok, detail,
        ))

    # T2 IG1 URI-shaped --images-dir refused.
    images, _d, fails = _validate_images_dir_arg("file:///tmp/foo")
    results.append(_ProbeResult(
        "T2 IG1: URI-shaped --images-dir refused",
        images is None and any("IG1" in f for f in fails),
        f"images={images!r}, failures={fails!r}",
    ))

    # T3 IG2 symlink --images-dir refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T3-") as raw_td:
        td = Path(raw_td)
        real = td / "real_dir"
        real.mkdir()
        link = td / "link_dir"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            results.append(_ProbeResult(
                "T3 IG2: skipped (symlink not supported on this OS)",
                True,
            ))
        else:
            images, _d, fails = _validate_images_dir_arg(str(link))
            results.append(_ProbeResult(
                "T3 IG2: symlink --images-dir refused",
                images is None and any("IG2" in f for f in fails),
                f"images={images!r}, failures={fails!r}",
            ))

    # T4 IG3 symlink ancestor refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T4-") as raw_td:
        td = Path(raw_td)
        real_parent = td / "real_parent"
        real_parent.mkdir()
        nested_images = real_parent / "nested" / "images"
        nested_images.mkdir(parents=True)
        (nested_images / "alpha.png").write_bytes(_TINY_PNG_BYTES)
        symlink_parent = td / "linked_parent"
        try:
            symlink_parent.symlink_to(
                real_parent, target_is_directory=True,
            )
        except (OSError, NotImplementedError):
            results.append(_ProbeResult(
                "T4 IG3: skipped (symlink not supported on this OS)",
                True,
            ))
        else:
            target = symlink_parent / "nested" / "images"
            images, _d, fails = _validate_images_dir_arg(str(target))
            results.append(_ProbeResult(
                "T4 IG3: symlink ancestor of --images-dir refused",
                images is None and any("IG3" in f for f in fails),
                f"images={images!r}, failures={fails!r}",
            ))

    # T5 IG4 --images-dir missing.
    with tempfile.TemporaryDirectory(prefix="op-helper-T5-") as raw_td:
        td = Path(raw_td)
        images, _d, fails = _validate_images_dir_arg(str(td / "nope"))
        results.append(_ProbeResult(
            "T5 IG4: missing --images-dir refused",
            images is None and any("IG4" in f for f in fails),
            f"images={images!r}, failures={fails!r}",
        ))

    # T6 IG4 --images-dir empty.
    with tempfile.TemporaryDirectory(prefix="op-helper-T6-") as raw_td:
        td = Path(raw_td)
        empty = td / "empty"
        empty.mkdir()
        images, _d, fails = _validate_images_dir_arg(str(empty))
        results.append(_ProbeResult(
            "T6 IG4: empty --images-dir refused",
            images is None and any("IG4" in f for f in fails),
            f"images={images!r}, failures={fails!r}",
        ))

    # T7 IG4 --images-dir is a file, not a directory.
    with tempfile.TemporaryDirectory(prefix="op-helper-T7-") as raw_td:
        td = Path(raw_td)
        f = td / "not_a_dir"
        f.write_bytes(b"x")
        images, _d, fails = _validate_images_dir_arg(str(f))
        results.append(_ProbeResult(
            "T7 IG4: --images-dir is a file -> refused",
            images is None and any("IG4" in f_ for f_ in fails),
            f"images={images!r}, failures={fails!r}",
        ))

    # T8 IG5 unsupported extension refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T8-") as raw_td:
        td = Path(raw_td)
        d = td / "imgs"
        d.mkdir()
        (d / "logo.svg").write_bytes(b"<svg></svg>")
        images, _d, fails = _validate_images_dir_arg(str(d))
        results.append(_ProbeResult(
            "T8 IG5: unsupported extension (.svg) refused",
            images is None and any("IG5" in f for f in fails),
            f"images={images!r}, failures={fails!r}",
        ))

    # T9 IG5 subdirectory refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T9-") as raw_td:
        td = Path(raw_td)
        d = td / "imgs"
        (d / "nested").mkdir(parents=True)
        images, _d, fails = _validate_images_dir_arg(str(d))
        results.append(_ProbeResult(
            "T9 IG5: subdirectory inside --images-dir refused",
            images is None and any("IG5" in f for f in fails),
            f"images={images!r}, failures={fails!r}",
        ))

    # T10 IG5 symlink file refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T10-") as raw_td:
        td = Path(raw_td)
        d = td / "imgs"
        d.mkdir()
        real = td / "real.png"
        real.write_bytes(_TINY_PNG_BYTES)
        link = d / "alpha.png"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            results.append(_ProbeResult(
                "T10 IG5: skipped (symlink not supported on this OS)",
                True,
            ))
        else:
            images, _d, fails = _validate_images_dir_arg(str(d))
            results.append(_ProbeResult(
                "T10 IG5: symlink file in --images-dir refused",
                images is None and any(
                    "IG5" in f and "symlink" in f for f in fails
                ),
                f"images={images!r}, failures={fails!r}",
            ))

    # T11 IG6 stem doesn't match id pattern (space in filename).
    with tempfile.TemporaryDirectory(prefix="op-helper-T11-") as raw_td:
        td = Path(raw_td)
        d = td / "imgs"
        d.mkdir()
        (d / "my photo.png").write_bytes(_TINY_PNG_BYTES)
        images, _d, fails = _validate_images_dir_arg(str(d))
        results.append(_ProbeResult(
            "T11 IG6: filename with space -> stem refused",
            images is None and any("IG6" in f for f in fails),
            f"images={images!r}, failures={fails!r}",
        ))

    # T12 IG6 stem starts with a separator.
    with tempfile.TemporaryDirectory(prefix="op-helper-T12-") as raw_td:
        td = Path(raw_td)
        d = td / "imgs"
        d.mkdir()
        (d / "-leading.png").write_bytes(_TINY_PNG_BYTES)
        images, _d, fails = _validate_images_dir_arg(str(d))
        results.append(_ProbeResult(
            "T12 IG6: stem starting with separator refused",
            images is None and any("IG6" in f for f in fails),
            f"images={images!r}, failures={fails!r}",
        ))

    # T13 IG7 two files share a stem (alpha.png + alpha.jpg).
    with tempfile.TemporaryDirectory(prefix="op-helper-T13-") as raw_td:
        td = Path(raw_td)
        d = td / "imgs"
        d.mkdir()
        (d / "alpha.png").write_bytes(_TINY_PNG_BYTES)
        (d / "alpha.jpg").write_bytes(_TINY_JPEG_BYTES)
        images, _d, fails = _validate_images_dir_arg(str(d))
        results.append(_ProbeResult(
            "T13 IG7: two files share a stem -> refused",
            images is None and any("IG7" in f for f in fails),
            f"images={images!r}, failures={fails!r}",
        ))

    # T14 IG8 magic-byte mismatch (PNG bytes inside .jpg).
    with tempfile.TemporaryDirectory(prefix="op-helper-T14-") as raw_td:
        td = Path(raw_td)
        d = td / "imgs"
        d.mkdir()
        (d / "bad.jpg").write_bytes(_TINY_PNG_BYTES)
        images, _d, fails = _validate_images_dir_arg(str(d))
        results.append(_ProbeResult(
            "T14 IG8: PNG bytes inside .jpg refused",
            images is None and any("IG8" in f for f in fails),
            f"images={images!r}, failures={fails!r}",
        ))

    # T15 IG9 image count above cap refused — AND the cap check fires
    # BEFORE any byte-level gate. We plant MAX_IMAGES + 1 files whose
    # bytes would fail the IG8 magic-byte gate (literal ASCII "garbage"
    # has neither the PNG nor JPEG magic prefix). The structural gates
    # (regular file, .png extension, valid stem, unique stem) accept
    # every entry as a candidate, then IG9 must fire. A regression that
    # moves the cap check back after the Pass-2 hashing loop would
    # instead emit MAX_IMAGES + 1 IG8 diagnostics and zero IG9 — this
    # probe asserts BOTH "IG9 present" AND "no IG8 present" AND "exactly
    # one failure" so the regression is caught.
    with tempfile.TemporaryDirectory(prefix="op-helper-T15-") as raw_td:
        td = Path(raw_td)
        d = td / "imgs"
        d.mkdir()
        for i in range(MAX_IMAGES + 1):
            (d / f"img_{i:02d}.png").write_bytes(b"garbage-not-png")
        images, _d, fails = _validate_images_dir_arg(str(d))
        ig9_present = any("IG9" in f for f in fails)
        ig8_present = any("IG8" in f for f in fails)
        results.append(_ProbeResult(
            f"T15 IG9: more than MAX_IMAGES={MAX_IMAGES} refused at "
            f"the cap check BEFORE byte-level hashing (no IG8 emitted)",
            (
                images is None
                and ig9_present
                and not ig8_present
                and len(fails) == 1
            ),
            f"images={images!r}, IG9_present={ig9_present}, "
            f"IG8_present={ig8_present}, len(fails)={len(fails)}, "
            f"failures={fails!r}",
        ))

    # T16 OUT --out-dir inside REPO_ROOT refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T16-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "imgs"
        _write_synthetic_images(images_dir)
        # Pre-resolve to be sure the gate refuses something that
        # actually anchors under REPO_ROOT.
        bad_out = REPO_ROOT / "operator_intake_should_not_land_here"
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(bad_out),
        )
        # The output-path gate refuses rc=2 before any mkdir.
        leaked = bad_out.exists()
        results.append(_ProbeResult(
            "T16 OUT: --out-dir inside REPO_ROOT refused with no mkdir",
            rc == 2 and not leaked,
            f"rc={rc}, leaked={leaked}",
        ))

    # T17 OUT --out-dir pre-existing non-empty refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T17-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "imgs"
        _write_synthetic_images(images_dir)
        out_dir = td / "out"
        out_dir.mkdir()
        (out_dir / "stale").write_text("stale")
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
        )
        results.append(_ProbeResult(
            "T17 OUT: non-empty pre-existing --out-dir refused; stale "
            "byte preserved",
            (
                rc == 2
                and (out_dir / "stale").is_file()
                and (out_dir / "stale").read_text() == "stale"
                and not (out_dir / "summary.json").exists()
            ),
            f"rc={rc}, stale_present="
            f"{(out_dir / 'stale').exists()}",
        ))

    # T18 OUT URI-shaped --out-dir refused by the URI-SPECIFIC check —
    # uses a VALID --images-dir so the rc=2 cannot come from an
    # images-dir refusal masking a silently-permissive OUT gate, AND
    # asserts the failure diagnostic explicitly names the URI shape.
    #
    # The URI-specific assertion is load-bearing: ``rc == 2`` alone is
    # not enough, because ``Path("file:///tmp/...")`` is treated as a
    # RELATIVE path on POSIX (the components are ``('file:', 'tmp',
    # ...)``). If the dedicated URI gate at the top of
    # ``_validate_out_dir_arg`` is removed, ``Path.resolve()`` would
    # then anchor the URI string under ``cwd == REPO_ROOT``, the
    # downstream "anchors under REPO_ROOT" check would fire, and the
    # gate would STILL return ``(None, [...REPO_ROOT...])`` — making
    # ``rc == 2`` and ``bool(out_fails_direct)`` both True for a
    # NON-URI reason. The "no filesystem entry materialised" check is
    # similarly insufficient: even with the URI gate removed, the
    # downstream gate refuses before any mkdir, so the lexical leak
    # check stays clean for the wrong reason. Asserting the diagnostic
    # carries the "URI-shaped" wording is the only check that uniquely
    # identifies the dedicated URI gate; the other "out-dir"
    # diagnostics in ``_validate_out_dir_arg`` (symlink / symlink
    # ancestor / REPO_ROOT anchor / missing parent / non-directory /
    # non-empty) do not use the word "URI", so a regression that
    # removes the URI check and lets another check fire instead trips
    # this assertion.
    with tempfile.TemporaryDirectory(prefix="op-helper-T18-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        _write_synthetic_images(images_dir)
        uri_out = "file:///tmp/op_helper_t18_must_not_exist"
        rc18 = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=uri_out,
        )
        _, out_fails_direct = _validate_out_dir_arg(uri_out)
        uri_lexical_leak = Path(uri_out).exists()
        uri_specific_diagnostic = any(
            "URI-shaped" in f for f in (out_fails_direct or [])
        )
        results.append(_ProbeResult(
            "T18 OUT: URI-shaped --out-dir refused by the URI-specific "
            "gate (rc=2 + diagnostic names the URI shape) with a VALID "
            "--images-dir AND no filesystem entry materialised",
            (
                rc18 == 2
                and bool(out_fails_direct)
                and uri_specific_diagnostic
                and not uri_lexical_leak
            ),
            f"rc={rc18}, uri_specific_diagnostic="
            f"{uri_specific_diagnostic}, "
            f"out_fails_direct={out_fails_direct!r}, "
            f"uri_lexical_leak={uri_lexical_leak}",
        ))

    # T19 — committed-tree snapshot. The whole self-test must not have
    # mutated any byte under REPO_ROOT/scripts/ or REPO_ROOT/examples/.
    snapshot_rc = _check_repo_unchanged(
        examples_before=examples_before,
        scripts_before=scripts_before,
    )
    results.append(_ProbeResult(
        "T19 snapshot: REPO_ROOT/scripts/ + REPO_ROOT/examples/ "
        "byte-identical before and after self-test",
        snapshot_rc == 0,
    ))

    fails = sum(1 for r in results if not r.ok)
    print()
    print("--- self-test results ---")
    for r in results:
        flag = "PASS" if r.ok else "FAIL"
        line = f"  [{flag}] {r.name}"
        if not r.ok and r.detail:
            line += f"\n         {r.detail}"
        print(line)
    print()
    if fails:
        print(
            f"FAIL: {fails} self-test scenario(s) did not behave as "
            f"expected."
        )
        return 1
    print(
        "OK (self-test): operator_local_images_to_editable_ppt behaves "
        "as expected — happy path produces an editable PPTX with "
        "provenance, every fail-closed gate fires on the documented "
        "perturbation, and nothing was written under REPO_ROOT."
    )
    return 0


# ---------------------------------------------------------------------------
# Entrypoint.
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="operator_local_images_to_editable_ppt.py",
        description=(
            "Operator-facing local-image intake helper for the core "
            "image-to-editable-PPT lane. Takes a caller-supplied flat "
            "directory of PNG / JPG / JPEG bytes plus a caller-supplied "
            "output directory outside the repo, drives the existing "
            "local image asset pipeline (run_explicit_pipeline.py + "
            "Stage-5.5 materialize) and validators "
            "(validate_source_image_assets, validate_pptx_contract, "
            "inspect_pptx_inventory) once, and writes a compact summary "
            "+ per-image provenance record alongside the produced "
            "editable PPTX. Local-only — does NOT call D-One, MCP, "
            "Qoder, a public network, telemetry, a model API, an image "
            "search, or any external service. NOT a full prompt or "
            "report or Markdown-to-PPTX automation."
        ),
    )
    parser.add_argument(
        "--images-dir", type=str, default=None,
        help=(
            "Operator-supplied flat directory of PNG / JPG / JPEG image "
            "files. Subdirectories, symlinks, and unsupported "
            "extensions are refused. Filename stems must match "
            "^[A-Za-z0-9][A-Za-z0-9_.\\-]*$ (the source_image_asset id "
            "pattern). The deck is capped at "
            f"{MAX_IMAGES} images."
        ),
    )
    parser.add_argument(
        "--out-dir", type=str, default=None,
        help=(
            "Caller-supplied output directory outside the repo tree. "
            "Must not be URI-shaped, a symlink, or have a symlink "
            "ancestor, must not anchor under the repo, must have an "
            "existing parent, and must either be missing or an empty "
            "pre-existing directory."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run the in-script tempfixture scenarios (happy path + "
            "every documented fail-closed probe). Mutually exclusive "
            "with --images-dir / --out-dir."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if args.images_dir is not None or args.out_dir is not None:
            print(
                "FAIL: --self-test does not take --images-dir / "
                "--out-dir.",
                file=sys.stderr,
            )
            return 2
        return _run_self_tests()

    missing = [
        name for name, value in (
            ("--images-dir", args.images_dir),
            ("--out-dir", args.out_dir),
        )
        if value is None
    ]
    if missing:
        print(
            f"FAIL: missing required argument(s): {', '.join(missing)} "
            f"(use --self-test for the in-script scenarios).",
            file=sys.stderr,
        )
        return 2

    return _run_operator_mode(
        images_dir_str=args.images_dir,
        out_dir_str=args.out_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
