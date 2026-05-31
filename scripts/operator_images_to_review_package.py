"""Operator-facing one-command **workflow** for the core local
image-to-editable-PPT lane that starts from a caller-supplied folder
of generated images and ends with a validated editable-PPTX review
package.

This script does not re-implement any contract logic. It only
sequences the existing helpers:

  1. copies every regular non-symlink file from ``--images-dir`` into
     ``<out-dir>/bundle/images/`` (the operator's source folder is
     never mutated; symlinks, subdirectories, and non-regular entries
     are refused before any byte is copied so a follow-symlink-on-read
     cannot redirect bytes into the bundle);
  2. invokes
     ``scripts/operator_local_images_to_editable_ppt.py --images-dir
     <bundle>/images --write-manifest-template
     <bundle>/manifest.json`` to write the starter manifest;
  3. invokes
     ``scripts/operator_local_images_to_editable_ppt.py --bundle
     <bundle> --write-generated-provenance-template
     <bundle>/generated_provenance.json`` to write the starter
     generated-provenance sidecar (``generator_source`` defaults to
     ``operator_declared_generated``);
  4. invokes
     ``scripts/operator_local_images_to_editable_ppt.py --bundle
     <bundle> --plan-out <out-dir>/approved_plan.json`` to write the
     reviewer-approved plan without running the pipeline;
  5. invokes
     ``scripts/operator_local_images_to_editable_ppt.py --bundle
     <bundle> --approved-plan <out-dir>/approved_plan.json --out-dir
     <out-dir>/review_package`` so the produced review package is
     gated behind the approved plan and the resulting
     ``summary.approved_plan.matched`` is ``true``;
  6. invokes
     ``scripts/validate_operator_review_package.py --out-dir
     <out-dir>/review_package`` as a read-only on-disk re-check;
  7. writes a concise top-level ``<out-dir>/README.md`` carrying the
     EXACT manual commands this run executed so the workflow is
     inspectable and repeatable.

The same seven stages can run as ONE command or split at a human-review
checkpoint into a ``--plan`` step (stages 1-4: stage the bundle + write
the templates + reviewable plan, then STOP) and a ``--resume`` step
(stages 5-7: build the review package from the operator-reviewed plan).
The split is the first practical human-review checkpoint in this lane —
nothing downstream is built until a person inspects ``approved_plan
.json`` and runs ``--resume``.

CLI shape::

    # One-command mode (auto-approves its own plan; leaves the produced
    # review package on disk):
    python3 scripts/operator_images_to_review_package.py \
        --images-dir DIR_OF_IMAGES \
        --out-dir FRESH_OUT_DIR

    # Two-step reviewed mode:
    #   1. plan: stage the bundle + reviewable plan, then stop.
    python3 scripts/operator_images_to_review_package.py --plan \
        --images-dir DIR_OF_IMAGES \
        --out-dir FRESH_OUT_DIR
    #   2. a human inspects <out-dir>/approved_plan.json (and the
    #      manifest / generated_provenance templates).
    #   3. resume: build the review package from the reviewed plan.
    python3 scripts/operator_images_to_review_package.py --resume \
        --out-dir SAME_OUT_DIR

    # Optional operator-supplied metadata (either / both flags; valid in
    # one-command AND --plan mode, refused with --resume). The supplied
    # file is staged into the bundle IN PLACE OF the default template, so
    # the produced approved_plan.json + review_package summary reflect it:
    python3 scripts/operator_images_to_review_package.py \
        --images-dir DIR_OF_IMAGES \
        --out-dir FRESH_OUT_DIR \
        --manifest REVIEWED_MANIFEST.json \
        --generated-provenance REVIEWED_PROVENANCE.json

    # Template-only convenience (write JUST the two editable starter
    # metadata files into a fresh --out-dir; builds nothing else —
    # no bundle/, no approved_plan.json, no review_package/, no PPTX):
    python3 scripts/operator_images_to_review_package.py --templates-only \
        --images-dir DIR_OF_IMAGES \
        --out-dir FRESH_OUT_DIR

    # Prepare-images convenience (copy a folder whose filenames carry
    # spaces / uppercase / parentheses / CJK characters into
    # <out-dir>/images/ under stable safe names + write
    # filename_mapping.json; builds nothing heavier). Feed the prepared
    # images/ into a --templates-only / --plan / one-command run:
    python3 scripts/operator_images_to_review_package.py --prepare-images-only \
        --images-dir DIR_OF_MESSY_IMAGES \
        --out-dir FRESH_OUT_DIR

    # Templates-only seeded from the prepared images' ORIGINAL filenames
    # (pass the prepare step's filename_mapping.json so the manifest's
    # slide_title / alt_text keep the human-readable original names that
    # were normalized away for safe local storage):
    python3 scripts/operator_images_to_review_package.py --templates-only \
        --images-dir PREPARED_OUT_DIR/images \
        --filename-mapping PREPARED_OUT_DIR/filename_mapping.json \
        --out-dir FRESH_OUT_DIR

    # Self-test (every scenario under TMPDIR; no caller-visible
    # artifacts retained):
    python3 scripts/operator_images_to_review_package.py --self-test

``--out-dir`` is validated through
``core_image_to_editable_ppt_demo._validate_out_dir_arg`` so the same
URI / symlink / symlink-ancestor / repo-tree / non-empty refusals the
sibling helpers already enforce apply here too. ``--images-dir`` is
gated separately for URI / symlink / symlink-ancestor / missing /
non-directory before any copy; cross-containment between the two
arguments is refused so the operator cannot accidentally point one
inside the other. In ``--resume`` mode ``--out-dir`` instead points at
a directory a prior ``--plan`` run staged, so it is validated through
``_validate_resume_out_dir_arg`` (same URI / symlink / symlink-ancestor
/ repo-tree refusals, but it REQUIRES the pre-existing ``bundle/`` +
``approved_plan.json`` and refuses an already-built ``review_package/``)
and ``--images-dir`` is refused.

The optional ``--manifest`` / ``--generated-provenance`` flags let the
operator supply a reviewed ``manifest.json`` / ``generated_provenance
.json`` instead of the default generated templates. Each path is gated
at the CLI for URI / symlink / symlink-ancestor / missing / non-file
(rc 2 before any staging); its CONTENT is then validated by the helper's
own ``_validate_manifest_arg`` / ``_validate_generated_provenance_
sidecar`` gates against the copied image basenames (JSON / schema /
closed field set / unsafe public-network-credential-raw-source wording /
filename-set match) and copied into the bundle in place of the template.
The downstream plan-out / approved-plan / resume drift-lock then build
the plan from the supplied metadata, so ``approved_plan.json`` and the
review-package summary reflect it; the wrapper re-implements no contract
logic. The flags are refused with ``--resume`` (which rebuilds from the
already-staged bundle).

``--templates-only`` is the metadata-authoring shortcut: point
``--images-dir`` at a local PNG / JPG / JPEG folder and the wrapper writes
JUST two editable starter files into a fresh ``--out-dir`` —
``manifest.json`` and ``generated_provenance.json`` (the helper's safe
default templates) — and builds NOTHING else (no ``bundle/``, no
``approved_plan.json``, no ``review_package/``, no ``deck.pptx``, no
``workspace`` / ``reports`` / ``inventory`` / ``visual_quality``). Each
file is written by the helper's existing
``--write-manifest-template`` / ``--write-generated-provenance-template``
writers against a single stable snapshot of the images (copied once into
a private temp dir so the two files always agree on the filename set), so
the wrapper re-implements no contract logic. Edit the two
files, then feed them back via ``--manifest`` / ``--generated-provenance``
to a ``--plan`` or one-command run. ``--templates-only`` is mutually
exclusive with ``--plan`` / ``--resume`` / ``--manifest`` /
``--generated-provenance`` / ``--self-test``.

The optional ``--filename-mapping`` flag (valid ONLY with
``--templates-only``) points at the ``filename_mapping.json`` a prior
``--prepare-images-only`` run wrote next to the prepared ``images/``. When
supplied, the manifest's per-image ``slide_title`` / ``alt_text`` are
seeded from each image's ORIGINAL filename — preserving the spaces /
punctuation / CJK characters ``--prepare-images-only`` normalized away for
safe local storage — instead of the normalized safe basename, so a deck
prepared from messy real-world names keeps human-readable titles. The path
is gated for URI / symlink / symlink-ancestor / missing / non-file (rc 2)
at the CLI; the mapping is then bound to the prepared image BYTES — its
``safe_filename`` set must equal the prepared images exactly AND each
record's recorded ``sha256`` / ``byte_count`` must match the prepared
bytes (else the run fails closed, so a stale mapping that reuses the same
safe names for different images is refused rather than mislabelling the
deck) — and the re-seeded manifest is re-validated through the helper's
``_validate_manifest_arg`` gate so an over-long / unsafe seeded title fails
closed rather than producing a manifest that only breaks at build time. Only the manifest is seeded — the
generated-provenance sidecar carries no filename-derived title. With no
``--filename-mapping`` the manifest is exactly the helper's default
template (prior behavior). The flag is refused outside ``--templates-only``
(build modes consume a reviewed manifest via ``--manifest``;
``--prepare-images-only`` produces the mapping rather than consuming it).

``--prepare-images-only`` is the messy-filename prepare shortcut: real
generated-image folders routinely carry names with spaces, uppercase
letters, parentheses, dots, hyphens, or CJK characters. The operator lane
uses each filename stem VERBATIM as the asset_id that becomes a slide's
render_model ``image_ref`` (constrained to ``^[a-z][a-z0-9_]*$``), so such
names build a broken deck even though they pass the looser IG6
``--images-dir`` gate — and an operator should not have to hand-rename
every file first. Point ``--images-dir`` at such a folder and the wrapper
copies each PNG / JPG / JPEG into ``<out-dir>/images/`` under a stable
safe filename (lowercased, every character outside ``[a-z0-9_]`` mapped to
``_`` and collapsed; a name with no usable ``[a-z0-9]`` content — a
CJK-only name — falls back to the base ``img``, a name that would not
otherwise start with a lowercase letter is prefixed ``img_``, and the
result is truncated to the byte cap — so the stem matches the
``image_ref`` contract, which implies IG6)
and writes ``filename_mapping.json`` (one record per image carrying
``original_filename`` / ``safe_filename`` / ``byte_count`` / ``sha256`` /
``media_type`` / ``extension``; the recorded ``original_filename`` is what
``--templates-only --filename-mapping`` later seeds slide titles from) plus
a short ``README.md``. It builds
NOTHING heavier — no ``bundle/``, ``approved_plan.json``,
``review_package/``, ``deck.pptx``, ``workspace`` / ``reports``. The same
``_preflight_image_entries`` gate the bundle-staging path uses still fires
(symlink / subdirectory / non-image / hidden-dotfile / size + count caps),
and two names that normalise to the same base stem are given distinct names
with a deterministic numeric suffix (``img`` / ``img_2`` …, ``my_file`` /
``my_file_2``) so a CJK-heavy folder prepares without hand-renaming; only a
stem that still violates the ``image_ref`` contract (a truly unsafe input)
is refused BEFORE any byte is copied, so a refused run leaves no half-written
``images/``. Feed the prepared ``images/`` into a
``--templates-only`` / ``--plan`` / one-command run. ``--prepare-images-only``
is mutually exclusive with ``--plan`` / ``--resume`` / ``--templates-only``
/ ``--manifest`` / ``--generated-provenance`` / ``--self-test``.

Local-only — does NOT call D-One, MCP, Qoder, a public network,
telemetry, a model API, an image search, or any external service. NOT
a full prompt / report / Markdown-to-PPTX automation. Real D-One
remains UNVERIFIED.
"""

from __future__ import annotations

import sys

# Refuse `.pyc` writes from any imported module. Mirrors the gate every
# sibling smoke / helper applies; the bytecode flag must be flipped
# BEFORE any first-party import so the interpreter sees it at
# bytecode-write time.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402
import shutil  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

# Reuse the sibling demo's URI / symlink ancestor / out-dir gates and
# the helper's synthetic-image writer + locked boundary tuple so this
# script cannot diverge from the contract the helpers already enforce.
from core_image_to_editable_ppt_demo import (  # noqa: E402
    _URI_SCHEME_PREFIX,
    _forbidden_symlink_ancestor,
    _validate_out_dir_arg,
)
from operator_local_images_to_editable_ppt import (  # noqa: E402
    MAX_IMAGES,
    _EXPLICIT_BOUNDARIES,
    _ID_MAX_LEN,
    _TINY_JPEG_BYTES,
    _TINY_PNG_BYTES,
    _alt_text_for_name,
    _slide_title_for_name,
    _validate_generated_provenance_sidecar,
    _validate_manifest_arg,
    _write_synthetic_images,
)

HELPER_PATH = SCRIPTS_DIR / "operator_local_images_to_editable_ppt.py"
VALIDATOR_PATH = SCRIPTS_DIR / "validate_operator_review_package.py"

# Per-file byte cap applied BEFORE the wrapper copies any operator
# byte into ``<out-dir>/bundle/images/``. The underlying helper does
# not cap per-file size today (it sha256s every file regardless of
# bytes), so the copy step itself has to bound the worst case — a
# folder containing a single multi-GB file would otherwise be
# duplicated verbatim into the bundle before any helper gate could
# fire and potentially exhaust the operator's ``--out-dir`` disk. 64
# MiB is generous for an AI-generated-image folder (typical outputs
# are 1-10 MiB each) but bounded enough that the worst-case
# ``MAX_IMAGES * MAX_BYTES_PER_FILE`` total disk write (768 MiB) is
# easily recoverable.
MAX_BYTES_PER_FILE = 64 * 1024 * 1024

# Closed set of accepted file extensions, parallel to the helper's
# IG5 refusal (line ~3744 of operator_local_images_to_editable_ppt.py
# rejects ``ext.lower() not in {"png", "jpg", "jpeg"}``). Pre-filtered
# in the wrapper so a non-image file in ``--images-dir`` (a README, a
# stray ``.DS_Store``, a ``.txt`` note) refuses the run BEFORE its
# bytes are copied into the bundle — otherwise the wrapper would do
# disk work the helper would immediately reject. Stem pattern
# (``^[A-Za-z0-9][A-Za-z0-9_.\\-]*$``) is left to the helper so a
# malformed stem surfaces with the helper's precise per-file
# diagnostic.
_ACCEPTED_EXTENSIONS: frozenset[str] = frozenset({"png", "jpg", "jpeg"})

# Media type recorded per prepared image in --prepare-images-only's
# filename_mapping.json. Keyed by the lowercased extension (parallel to
# _ACCEPTED_EXTENSIONS); jpg / jpeg both map to image/jpeg, matching the
# PPTX exporter's content-type handling for embedded raster media.
_MEDIA_TYPE_BY_EXT: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}

# The STRICT downstream image-reference contract that --prepare-images-only
# must normalise filenames to. The operator lane uses an image's filename
# stem VERBATIM as its asset_id (operator_local_images_to_editable_ppt.py:
# ``asset_id=stem``), and that asset_id becomes the slide's render_model
# ``image_ref`` / image_manifest ``id``, which schemas/render_model.schema
# .json constrains to ``^[a-z][a-z0-9_]*$``. That pattern is STRICTER than
# the helper's IG6 ``--images-dir`` basename gate (``_ID_PATTERN`` =
# ``^[A-Za-z0-9][A-Za-z0-9_.\-]*$``): it forbids a leading digit, dots,
# hyphens, and uppercase. A stem that passes IG6 (so the bundle / manifest
# stage accepts it) can still fail this gate downstream when the deck is
# built, so the prepare step normalises to THIS pattern — which implies IG6.
_IMAGE_REF_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# Files / dirs the helper writes under --out-dir on a happy
# normal-mode run. Verifying these exist after the helper subprocess
# returns 0 is the workflow's only post-run readback — the helper's
# own truth-checker already pinned every byte-level invariant.
_REVIEW_PACKAGE_FILES: tuple[str, ...] = (
    "deck.pptx",
    "summary.json",
    "README.md",
    "inventory.json",
    "visual_quality.json",
)
_REVIEW_PACKAGE_DIRS: tuple[str, ...] = (
    "workspace",
    "reports",
)


# ---------------------------------------------------------------------------
# Subprocess runner.
# ---------------------------------------------------------------------------


@dataclass
class _ToolOutcome:
    name: str
    rc: int
    stdout: str
    stderr: str


def _run(name: str, cmd: list[str]) -> _ToolOutcome:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    return _ToolOutcome(
        name=name, rc=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


def _print_outcome_tail(outcome: _ToolOutcome, *, tail_lines: int = 30) -> None:
    combined = (outcome.stdout or "") + (outcome.stderr or "")
    lines = combined.splitlines()
    if not lines:
        print(f"    (no output from {outcome.name})")
        return
    print(f"    --- last {min(len(lines), tail_lines)} line(s) of "
          f"{outcome.name} output ---")
    for line in lines[-tail_lines:]:
        print(f"    {line}")


def _print_torn_run_recovery_hint(out_dir: Path) -> None:
    """After a torn workflow run, point the operator at the recovery
    path. A run that fails AFTER the bundle is staged (a helper-stage
    refusal — e.g. an image whose bytes fail the deeper IG signature
    check, or an approved-plan drift) leaves its partial output under
    ``out_dir`` by design so the operator can inspect it. The next
    thing a real operator does is fix the flagged input and re-run the
    SAME command — but the shared ``--out-dir`` gate then refuses the
    now-non-empty directory with a "pre-existing artifacts" message
    that reads as operator error even though the artifacts are this
    failed run's own partial output. Naming the cause + both recovery
    paths here closes that gap: the top-level README that documents
    the same recovery is only written on a SUCCESSFUL run, so without
    this a torn run leaves the operator with no guidance at all.
    Guarded on a non-empty ``out_dir`` so a copy-stage refusal — which
    leaves ``out_dir`` empty and whose own message already names what
    to fix — stays quiet."""
    try:
        torn = any(out_dir.iterdir())
    except OSError:
        return
    if not torn:
        return
    print(
        f"\nNOTE: this failed run left partial output under {out_dir}. "
        f"Re-running the same command against this same --out-dir will "
        f"be refused as non-empty. To retry after fixing the issue "
        f"flagged above, remove the partial output and re-run "
        f"(`rm -rf {shlex.quote(str(out_dir))}`), or pass a fresh "
        f"--out-dir."
    )


# ---------------------------------------------------------------------------
# --images-dir gate. Mirrors the cheap subset of the helper's IG1..IG9
# refusals that protect the workflow from a follow-symlink-on-read
# before any byte is copied into the bundle. The helper's per-file
# IG gates still apply once the copied bytes are read back.
# ---------------------------------------------------------------------------


def _resolves_under_casefold(path: Path, root: Path) -> bool:
    """Return True iff ``path`` resolves at-or-under ``root`` after
    case-folding both sides as Unicode strings.

    Used as a defensive ancestor check on top of the helper's
    raw-string ``relative_to`` gate so a case-variant path on a
    case-insensitive filesystem (macOS APFS / Windows NTFS in
    default mode) still triggers the refusal. The function is
    extracted so the unit-level T10 probe can exercise the
    case-fold logic directly — without it, an integration probe
    that drove ``main`` would false-green on case-sensitive Linux
    (the helper's parent-exists check fires before the case-fold
    gate ever runs)."""
    root_cf = str(root.resolve(strict=False)).casefold()
    path_cf = str(path.resolve(strict=False)).casefold()
    if path_cf == root_cf:
        return True
    return path_cf.startswith(root_cf + os.sep)


def _validate_images_dir_arg(
    images_dir_str: str,
) -> tuple[Path | None, list[str]]:
    """Validate ``--images-dir`` before any copy. Refuses URI-shaped
    arguments, the path itself being a symlink, any symlink ancestor,
    a missing path, and a non-directory path. Does NOT walk children
    — ``_copy_images_into_bundle`` refuses symlinks / subdirectories
    per entry, and the helper's IG1..IG9 gates then re-validate every
    copied byte once the bundle is materialised."""
    failures: list[str] = []

    if _URI_SCHEME_PREFIX.match(images_dir_str):
        return None, [
            f"--images-dir argument {images_dir_str!r} looks URI-shaped; "
            f"operator mode only accepts local file paths."
        ]

    images_dir = Path(images_dir_str)

    if images_dir.is_symlink():
        try:
            tgt = os.readlink(images_dir)
        except OSError:
            tgt = "<unreadable>"
        return None, [
            f"--images-dir {images_dir} is a symlink (-> {tgt}); refused "
            f"so a symlink target cannot redirect which bytes get "
            f"copied into the bundle."
        ]

    forbidden = _forbidden_symlink_ancestor(images_dir)
    if forbidden is not None:
        ancestor, tgt = forbidden
        return None, [
            f"--images-dir {images_dir} has a symlink ancestor "
            f"{ancestor} (-> {tgt}); refused so a symlink in the typed "
            f"path cannot redirect which folder the bytes are copied "
            f"from."
        ]

    if not images_dir.exists():
        return None, [
            f"--images-dir {images_dir} does not exist."
        ]
    if not images_dir.is_dir():
        return None, [
            f"--images-dir {images_dir} exists but is not a directory."
        ]

    return images_dir, failures


def _validate_metadata_arg(
    arg_str: str, flag: str,
) -> tuple[Path | None, list[str]]:
    """Validate an optional caller-supplied metadata path (``--manifest``
    or ``--generated-provenance``) at the CLI BEFORE any staging.

    Refuses URI-shaped arguments, the path itself being a symlink, any
    symlink ancestor, a missing path, and a non-regular-file path — the
    same cheap path-safety subset ``--images-dir`` gets, so an obviously
    unsafe metadata path fails closed with rc 2 without copying a single
    image. The deeper CONTENT contract (UTF-8 JSON parse, schema, the
    closed field set, unsafe public / network / credential / raw-source
    wording, and the filename-set-equals-the-copied-images cross-check)
    is NOT re-implemented here: it is delegated verbatim to the helper's
    own ``_validate_manifest_arg`` / ``_validate_generated_provenance_
    sidecar`` gates, which run in ``_stage_bundle_and_plan`` once the
    copied image basenames are known. ``flag`` only names the offending
    argument in the diagnostics."""
    failures: list[str] = []

    if _URI_SCHEME_PREFIX.match(arg_str):
        return None, [
            f"{flag} argument {arg_str!r} looks URI-shaped; operator "
            f"mode only accepts local file paths."
        ]

    path = Path(arg_str)

    if path.is_symlink():
        try:
            tgt = os.readlink(path)
        except OSError:
            tgt = "<unreadable>"
        return None, [
            f"{flag} {path} is a symlink (-> {tgt}); refused so a "
            f"symlink target cannot redirect which metadata bytes get "
            f"staged into the bundle."
        ]

    forbidden = _forbidden_symlink_ancestor(path)
    if forbidden is not None:
        ancestor, tgt = forbidden
        return None, [
            f"{flag} {path} has a symlink ancestor {ancestor} "
            f"(-> {tgt}); refused so a symlink in the typed path cannot "
            f"redirect which metadata file is staged."
        ]

    if not path.exists():
        return None, [
            f"{flag} {path} does not exist."
        ]
    if path.is_dir() or not path.is_file():
        return None, [
            f"{flag} {path} is not a regular file."
        ]

    return path, failures


def _preflight_image_entries(
    images_dir: Path,
) -> tuple[list[Path] | None, list[str]]:
    """Validate every direct child of ``images_dir`` against the cheap
    safety gates shared by every mode that reads an operator image folder
    (count cap parallel to the helper's IG9, per-entry symlink /
    regular-file / extension + hidden-dotfile / size-cap refusals) WITHOUT
    copying a byte or creating any output.

    Returns ``(entries, failures)``: ``entries`` is the sorted direct-child
    list when the directory could be listed (``None`` only when ``iterdir``
    itself failed), and ``failures`` is non-empty iff the folder is
    unusable. When ``failures`` is empty the returned ``entries`` is a real
    list a caller may safely iterate.

    Single-sourced so ``_copy_images_into_bundle`` (bundle staging) and
    ``_run_prepare_images_only`` (safe-filename prepare step) apply the
    identical safety contract — the prepare step must not drift from the
    staging path's gates."""
    failures: list[str] = []
    try:
        entries = sorted(images_dir.iterdir())
    except OSError as exc:
        return None, [
            f"--images-dir {images_dir} could not be listed: "
            f"{type(exc).__name__}: {exc}"
        ]
    if not entries:
        return entries, [
            f"--images-dir {images_dir} is empty; the helper requires "
            f"at least one PNG / JPG / JPEG file."
        ]
    # Pre-flight count cap, parallel to the helper's IG9 refusal. Run
    # BEFORE the per-entry walk so a folder with thousands of
    # entries does not even reach the size / symlink probe loop.
    if len(entries) > MAX_IMAGES:
        return entries, [
            f"--images-dir {images_dir} contains {len(entries)} "
            f"entries; refused — the helper caps the deck at "
            f"{MAX_IMAGES} images (IG9). Pre-filter the folder and "
            f"re-run."
        ]
    for child in entries:
        if child.is_symlink():
            try:
                tgt = os.readlink(child)
            except OSError:
                tgt = "<unreadable>"
            failures.append(
                f"--images-dir entry {child} is a symlink (-> {tgt}); "
                f"refused so a per-file symlink target cannot redirect "
                f"which bytes land in the bundle."
            )
            continue
        if not child.is_file():
            failures.append(
                f"--images-dir entry {child} is not a regular file "
                f"(is_dir={child.is_dir()}); refused — the helper "
                f"requires a flat folder of regular PNG / JPG / JPEG "
                f"files."
            )
            continue
        # Per-entry extension check, parallel to the helper's IG5.
        # Refused BEFORE the size stat / copy so a stray ``.txt`` /
        # ``.DS_Store`` / ``.md`` next to the images doesn't get
        # copied into the bundle just to have the helper reject it
        # one stage later. Stem-pattern enforcement is left to the
        # helper so a malformed stem surfaces with the helper's
        # precise IG6 diagnostic.
        ext = child.suffix.lstrip(".").lower()
        if ext not in _ACCEPTED_EXTENSIONS:
            if child.name.startswith("."):
                # Hidden dotfiles carry an empty extension, so the
                # generic "has extension ''" line below reads as a
                # mystery — most operators never see the file in
                # Finder. The overwhelmingly common case is macOS
                # Finder's invisible ``.DS_Store`` metadata file
                # landing in an otherwise-clean image folder. Name the
                # likely cause and give a non-destructive reveal
                # command so the operator can clean the folder and
                # re-run instead of decoding ``extension ''``.
                failures.append(
                    f"--images-dir entry {child} is a hidden file "
                    f"(its name begins with '.', most often macOS "
                    f"Finder's invisible .DS_Store metadata file); "
                    f"refused — only PNG / JPG / JPEG image files are "
                    f"accepted. Reveal hidden entries with "
                    f"`ls -a {shlex.quote(str(images_dir))}`, remove "
                    f"the non-image ones, and re-run."
                )
            else:
                failures.append(
                    f"--images-dir entry {child} has extension "
                    f"{child.suffix!r}; refused — only PNG / JPG / JPEG "
                    f"files are accepted (the helper's IG5 gate would "
                    f"reject this extension anyway; the wrapper refuses "
                    f"before copy so a non-image file is not duplicated "
                    f"into <out-dir>/bundle/images/)."
                )
            continue
        # Per-file byte cap. Stat'd BEFORE any byte is copied so a
        # multi-GB file in --images-dir is refused without ever being
        # duplicated into the bundle. ``stat()`` is cheap; the file's
        # bytes are not read.
        try:
            size = child.stat().st_size
        except OSError as exc:
            failures.append(
                f"--images-dir entry {child} could not be stat'd: "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        if size > MAX_BYTES_PER_FILE:
            failures.append(
                f"--images-dir entry {child} is {size} bytes; refused "
                f"— the wrapper caps individual files at "
                f"{MAX_BYTES_PER_FILE} bytes "
                f"({MAX_BYTES_PER_FILE // (1024 * 1024)} MiB) so a "
                f"single oversized file cannot exhaust the operator's "
                f"--out-dir disk before any helper gate can fire."
            )
    return entries, failures


def _copy_images_into_bundle(
    images_dir: Path, bundle_images: Path,
) -> list[str]:
    """Pre-flight every direct child of ``images_dir`` (via
    ``_preflight_image_entries``) and only then copy the regular
    non-symlink files into ``bundle_images`` under their ORIGINAL names.
    Any symlink, sub-directory, or non-regular entry refuses the run
    BEFORE ``bundle_images`` is created, so a refused workflow leaves no
    half-staged bundle behind. The helper's IG1..IG9 gates then
    re-validate extension / signature / stem on every copied byte — this
    path requires the operator's filenames to ALREADY satisfy the IG6 /
    IG7 basename contract (the safe-filename prepare step that normalises
    messy names is ``_run_prepare_images_only``)."""
    entries, failures = _preflight_image_entries(images_dir)
    if failures:
        return failures
    try:
        bundle_images.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        return [
            f"--out-dir bundle/images path {bundle_images} could not be "
            f"created: {type(exc).__name__}: {exc}"
        ]
    for child in entries:
        dest = bundle_images / child.name
        err = _copy_one_image_race_safe(
            child, dest, MAX_BYTES_PER_FILE,
        )
        if err is not None:
            return [err]
    return failures


def _copy_bounded(
    src_f, dst_f, max_bytes: int,
) -> str | None:
    """Stream bytes from ``src_f`` -> ``dst_f`` while refusing to
    cross the ``max_bytes`` cap. Returns ``None`` on success or a
    short failure-reason string when the source produced more than
    ``max_bytes`` bytes.

    Replaces the earlier ``shutil.copyfileobj`` call so the per-file
    cap is enforced inside the read loop and not just at the
    pre-copy ``os.fstat`` (Codex caught the bypass: a concurrent
    appender between the fstat and the copy could push the source
    past the cap, and ``copyfileobj`` would happily drain every
    appended byte). The read-budget arithmetic intentionally asks
    for ``max_bytes + 1 - total`` bytes per iteration so the loop
    can distinguish a source that ends exactly at the cap (chunk is
    empty, success) from one that has additional bytes available
    (chunk pushes ``total > max_bytes``, refused)."""
    total = 0
    chunk_size = 64 * 1024
    while True:
        budget = max_bytes + 1 - total
        if budget <= 0:
            # ``total`` already passed the cap; the next read could
            # only be 0 or fewer bytes. Refuse defensively.
            return (
                f"source produced more than {max_bytes} bytes before "
                f"EOF; refused mid-copy."
            )
        chunk = src_f.read(min(chunk_size, budget))
        if not chunk:
            return None
        if total + len(chunk) > max_bytes:
            return (
                f"source produced more than {max_bytes} bytes before "
                f"EOF; refused mid-copy."
            )
        dst_f.write(chunk)
        total += len(chunk)


def _copy_one_image_race_safe(
    src: Path, dest: Path, max_bytes: int,
    label: str = "--images-dir entry",
) -> str | None:
    """Copy ``src`` -> ``dest`` without following symlinks on either
    end, capping at ``max_bytes`` based on the opened fd's
    ``os.fstat`` (NOT the earlier pre-flight ``Path.stat``). Returns
    ``None`` on success or a single failure-line string on any
    refused / failed copy.

    ``label`` only names the source in failure diagnostics. It defaults
    to ``--images-dir entry`` so the image-copy loop's messages are
    unchanged; the operator-supplied metadata copy passes ``--manifest``
    / ``--generated-provenance`` so a refused metadata copy reads as
    such. The race-free O_NOFOLLOW / S_ISREG / bounded-read gates are
    identical regardless of label — a metadata file swapped for a
    symlink / FIFO / oversized file after the pre-flight still fails
    closed here.

    The pre-flight ``Path.is_symlink`` / ``Path.is_file`` / ``Path.
    stat`` checks earlier in ``_copy_images_into_bundle`` are racy by
    construction (Codex caught this): an attacker — or just a
    concurrent process — could swap ``src`` for a symlink between the
    check and the copy, and ``shutil.copyfile`` would then dutifully
    follow the symlink into whatever the link target names. This
    function closes the race by opening ``src`` with ``O_NOFOLLOW``
    so the open itself fails with ``ELOOP`` / ``EMLINK`` if ``src``
    is a symlink at the moment of the open, fstat'ing the resulting
    fd so the size cap is applied to the bytes we are about to read
    (not a stale stat on a now-replaced path), and opening ``dest``
    with ``O_CREAT | O_EXCL | O_NOFOLLOW`` so the destination cannot
    pre-exist as a symlink or regular file. The pre-flight checks
    remain as cheap rejections of obvious failures; this function
    is the durable, race-free gate."""
    try:
        # ``O_NONBLOCK`` is load-bearing on POSIX: ``os.open`` of a
        # FIFO with ``O_RDONLY`` blocks waiting for a writer, so a
        # FIFO in ``--images-dir`` would hang the workflow
        # indefinitely (Codex caught that the T8 probe itself would
        # hang on its own input without this flag). For regular
        # files, ``O_NONBLOCK`` is effectively a no-op — the
        # ``S_ISREG`` check below refuses every non-regular fd
        # BEFORE any read, so the non-blocking read semantics never
        # matter on the happy path. ``getattr(os, "O_NONBLOCK", 0)``
        # degrades gracefully on platforms (Windows) where the flag
        # is not defined; ``os.O_NOFOLLOW`` is also POSIX but the
        # supported repo platforms (darwin / linux) define it.
        open_flags = (
            os.O_RDONLY
            | os.O_NOFOLLOW
            | getattr(os, "O_NONBLOCK", 0)
        )
        src_fd = os.open(src, open_flags)
    except OSError as exc:
        return (
            f"{label} {src} could not be opened without "
            f"following symlinks: {type(exc).__name__}: {exc} "
            f"(O_NOFOLLOW gate fires on a mid-call swap into a "
            f"symlink even if the pre-flight is_symlink check passed)."
        )
    try:
        try:
            st = os.fstat(src_fd)
        except OSError as exc:
            return (
                f"{label} {src} could not be fstat'd: "
                f"{type(exc).__name__}: {exc}"
            )
        # ``O_NOFOLLOW`` refuses symlinks but NOT FIFOs, device
        # files, or sockets (Codex caught this gap). A FIFO at the
        # source path would open successfully and then block
        # ``copyfileobj`` waiting for a writer; a character device
        # like ``/dev/zero`` would silently feed zero bytes into the
        # bundle until the cap fires. ``stat.S_ISREG`` on the opened
        # fd (NOT a racy pre-flight ``Path.is_file``) closes that
        # gap: the check runs on the same inode the copy will read,
        # so a swap into a non-regular file between the pre-flight
        # and the open still surfaces here.
        if not stat.S_ISREG(st.st_mode):
            return (
                f"{label} {src} opened to mode "
                f"{stat.filemode(st.st_mode)} (not a regular file); "
                f"refused — only regular files are accepted, FIFOs / "
                f"device files / sockets are not."
            )
        if st.st_size > max_bytes:
            return (
                f"{label} {src} is {st.st_size} bytes (via "
                f"fstat on the opened fd); refused — over the "
                f"{max_bytes}-byte per-file cap."
            )
        try:
            dest_fd = os.open(
                dest,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o644,
            )
        except OSError as exc:
            return (
                f"copy destination {dest} could not be opened for "
                f"exclusive write: {type(exc).__name__}: {exc}"
            )
        try:
            with os.fdopen(src_fd, "rb", closefd=False) as src_f, \
                 os.fdopen(dest_fd, "wb", closefd=False) as dst_f:
                copy_err = _copy_bounded(src_f, dst_f, max_bytes)
            if copy_err is not None:
                return (
                    f"copy {src} -> {dest} refused: {copy_err} "
                    f"(the fstat size check could be bypassed by a "
                    f"concurrent appender between fstat and the "
                    f"read loop — Codex caught this gap, so the "
                    f"loop itself caps total bytes read at "
                    f"{max_bytes} regardless of what fstat reported)."
                )
        except OSError as exc:
            return (
                f"copy {src} -> {dest} failed: "
                f"{type(exc).__name__}: {exc}"
            )
        finally:
            try:
                os.close(dest_fd)
            except OSError:
                pass
    finally:
        try:
            os.close(src_fd)
        except OSError:
            pass
    return None


# ---------------------------------------------------------------------------
# Workflow body — sequences the existing helpers into the seven stages
# documented in the module docstring.
# ---------------------------------------------------------------------------


@dataclass
class _WorkflowPaths:
    """The canonical on-disk layout the workflow writes under
    ``out_dir``. Derived once so the one-command, plan-only, and resume
    entry points all agree on the same paths."""
    out_dir: Path
    bundle: Path
    bundle_images: Path
    manifest: Path
    gen_prov: Path
    approved_plan: Path
    review_package: Path


def _workflow_paths(out_dir: Path) -> _WorkflowPaths:
    bundle = out_dir / "bundle"
    return _WorkflowPaths(
        out_dir=out_dir,
        bundle=bundle,
        bundle_images=bundle / "images",
        manifest=bundle / "manifest.json",
        gen_prov=bundle / "generated_provenance.json",
        approved_plan=out_dir / "approved_plan.json",
        review_package=out_dir / "review_package",
    )


def _stage_supplied_metadata(
    *, src: Path, dest: Path, discovered: list[str], validator, flag: str,
) -> list[str]:
    """Validate an operator-supplied metadata file against the copied
    image basenames, then copy it race-safely into the bundle at
    ``dest``. Returns ``[]`` on success or a list of failure lines.

    ``validator`` is the helper's own ``_validate_manifest_arg`` /
    ``_validate_generated_provenance_sidecar``; both share the
    ``(path_str, discovered_filenames) -> (entries, resolved_path,
    failures)`` signature and OWN the full content contract — UTF-8 JSON
    parse, schema / closed field set, unsafe public / network /
    credential / raw-source wording, and the filename-set-equals-the-
    discovered-images cross-check (MAN12 / GP13). Reusing them here means
    the wrapper re-implements no contract logic: a metadata file whose
    filenames do not match the copied images, or that carries unsafe
    wording, is refused BEFORE it is copied into the bundle. The
    subsequent plan-out stage re-validates the bundle copy as belt and
    braces."""
    entries, _resolved, failures = validator(str(src), discovered)
    if failures or entries is None:
        return failures or [
            f"{flag} {src} was refused by the metadata contract gates."
        ]
    copy_err = _copy_one_image_race_safe(
        src, dest, MAX_BYTES_PER_FILE, label=flag,
    )
    if copy_err is not None:
        return [copy_err]
    if not dest.is_file() or dest.is_symlink():
        return [
            f"expected staged {flag} at {dest} as a regular non-symlink "
            f"file after copy"
        ]
    return []


def _stage_bundle_and_plan(
    *, images_dir: Path, paths: _WorkflowPaths,
    manifest_src: Path | None = None,
    gen_prov_src: Path | None = None,
) -> int:
    """Stages A–D: copy the operator images into the bundle, stage the
    manifest + generated-provenance metadata (operator-supplied when
    ``manifest_src`` / ``gen_prov_src`` is given, else the helper's
    starter templates), and write the reviewable plan
    (``approved_plan.json``). Stops short of the review package — no
    ``deck.pptx`` / ``review_package/`` is produced here. Returns 0 on
    success, 1 on any stage failure (leaving partial output under
    ``out_dir`` for inspection). Shared verbatim by the one-command and
    plan-only entry points so they stage identically.

    When the operator supplies a metadata file, it is validated against
    the copied image basenames with the helper's own contract gates and
    copied into the bundle in place of the default template; the
    downstream plan-out / approved-plan / resume drift-lock then build
    the plan from it, so ``approved_plan.json`` and the review-package
    summary reflect the supplied values without any further wiring."""
    bundle = paths.bundle
    bundle_images = paths.bundle_images
    manifest = paths.manifest
    gen_prov = paths.gen_prov
    approved_plan = paths.approved_plan

    # Stage A — stage the bundle by copying the operator images.
    copy_failures = _copy_images_into_bundle(images_dir, bundle_images)
    if copy_failures:
        for line in copy_failures:
            print(f"  [FAIL] {line}")
        return 1
    discovered = sorted(p.name for p in bundle_images.iterdir())
    print(f"  [PASS] copied {len(discovered)} image(s) into "
          f"{bundle_images}: {discovered}")

    # Stage B — manifest: stage the operator-supplied file (validated
    # against the copied basenames by the helper's MAN gates) or, by
    # default, write the helper's starter template.
    if manifest_src is not None:
        man_failures = _stage_supplied_metadata(
            src=manifest_src, dest=manifest, discovered=discovered,
            validator=_validate_manifest_arg, flag="--manifest",
        )
        if man_failures:
            for line in man_failures:
                print(f"  [FAIL] {line}")
            return 1
        print(f"  [PASS] operator-supplied manifest staged to {manifest}")
    else:
        manifest_outcome = _run(
            "operator_local_images_to_editable_ppt "
            "--write-manifest-template",
            [
                sys.executable, str(HELPER_PATH),
                "--images-dir", str(bundle_images),
                "--write-manifest-template", str(manifest),
            ],
        )
        if (manifest_outcome.rc != 0
                or not manifest.is_file()
                or manifest.is_symlink()):
            print(f"  [FAIL] manifest template helper rc="
                  f"{manifest_outcome.rc}; manifest_exists="
                  f"{manifest.exists()}")
            _print_outcome_tail(manifest_outcome)
            return 1
        print(f"  [PASS] manifest template written to {manifest}")

    # Stage C — generated-provenance: stage the operator-supplied sidecar
    # (validated against the copied basenames by the helper's GP gates)
    # or, by default, write the helper's starter template.
    if gen_prov_src is not None:
        gp_failures = _stage_supplied_metadata(
            src=gen_prov_src, dest=gen_prov, discovered=discovered,
            validator=_validate_generated_provenance_sidecar,
            flag="--generated-provenance",
        )
        if gp_failures:
            for line in gp_failures:
                print(f"  [FAIL] {line}")
            return 1
        print(f"  [PASS] operator-supplied generated-provenance staged to "
              f"{gen_prov}")
    else:
        gen_prov_outcome = _run(
            "operator_local_images_to_editable_ppt "
            "--write-generated-provenance-template",
            [
                sys.executable, str(HELPER_PATH),
                "--bundle", str(bundle),
                "--write-generated-provenance-template", str(gen_prov),
            ],
        )
        if (gen_prov_outcome.rc != 0
                or not gen_prov.is_file()
                or gen_prov.is_symlink()):
            print(f"  [FAIL] generated-provenance template helper rc="
                  f"{gen_prov_outcome.rc}; gen_prov_exists="
                  f"{gen_prov.exists()}")
            _print_outcome_tail(gen_prov_outcome)
            return 1
        print(f"  [PASS] generated-provenance template written to "
              f"{gen_prov}")

    # Stage D — plan-out preflight. Writes the approved plan that
    # Stage E will lock against.
    plan_outcome = _run(
        "operator_local_images_to_editable_ppt --plan-out",
        [
            sys.executable, str(HELPER_PATH),
            "--bundle", str(bundle),
            "--plan-out", str(approved_plan),
        ],
    )
    if (plan_outcome.rc != 0
            or not approved_plan.is_file()
            or approved_plan.is_symlink()):
        print(f"  [FAIL] plan-out helper rc={plan_outcome.rc}; "
              f"approved_plan_exists={approved_plan.exists()}")
        _print_outcome_tail(plan_outcome)
        return 1
    print(f"  [PASS] approved plan written to {approved_plan}")
    return 0


def _build_and_validate_review_package(*, paths: _WorkflowPaths) -> int:
    """Stages E–F: drive the approved-plan run lock (which fails closed
    on any drift between ``approved_plan.json`` and the current bundle
    BEFORE producing any artifact), confirm every review-package
    artifact landed, confirm the summary's approved-plan block, and run
    the read-only on-disk re-check. Returns 0 on success, 1 on any
    failure. Shared verbatim by the one-command and resume entry points
    so the produced review package and its evidence are identical."""
    bundle = paths.bundle
    approved_plan = paths.approved_plan
    review_package = paths.review_package

    # Stage E — approved-plan run lock. The helper rejects with rc 2
    # BEFORE any pipeline subprocess fires if the current bundle has
    # drifted from the approved plan (image bytes, manifest, sidecar,
    # …); on a match it writes the full review package under
    # ``review_package``.
    approved_outcome = _run(
        "operator_local_images_to_editable_ppt --approved-plan",
        [
            sys.executable, str(HELPER_PATH),
            "--bundle", str(bundle),
            "--approved-plan", str(approved_plan),
            "--out-dir", str(review_package),
        ],
    )
    if approved_outcome.rc != 0:
        print(f"  [FAIL] approved-plan helper rc={approved_outcome.rc}")
        _print_outcome_tail(approved_outcome)
        return 1
    print(f"  [PASS] approved-plan helper rc=0")

    missing_files = [
        name for name in _REVIEW_PACKAGE_FILES
        if not (review_package / name).is_file()
        or (review_package / name).is_symlink()
    ]
    missing_dirs = [
        name for name in _REVIEW_PACKAGE_DIRS
        if not (review_package / name).is_dir()
        or (review_package / name).is_symlink()
    ]
    if missing_files or missing_dirs:
        for name in missing_files:
            print(f"  [FAIL] missing review-package file: "
                  f"{review_package / name}")
        for name in missing_dirs:
            print(f"  [FAIL] missing review-package directory: "
                  f"{review_package / name}")
        return 1
    print(f"  [PASS] every review-package artifact exists "
          f"(files={list(_REVIEW_PACKAGE_FILES)}, "
          f"dirs={list(_REVIEW_PACKAGE_DIRS)})")

    # Confirm the approved-plan run lock actually fired in the helper's
    # summary — defense in depth on top of rc==0 above.
    try:
        summary = json.loads(
            (review_package / "summary.json").read_text(encoding="utf-8"),
        )
    except (OSError, ValueError) as exc:
        print(f"  [FAIL] could not parse summary.json: "
              f"{type(exc).__name__}: {exc}")
        return 1
    approved_block = summary.get("approved_plan")
    if (not isinstance(approved_block, dict)
            or approved_block.get("matched") is not True):
        print(f"  [FAIL] summary.approved_plan.matched is not True "
              f"(approved_plan={approved_block!r})")
        return 1
    print(f"  [PASS] summary.approved_plan.matched=True")

    # Stage F — read-only stdlib re-check of the produced review
    # package. Runs BEFORE the README write so a torn re-check cannot
    # leave a positive-looking README behind.
    validator_outcome = _run(
        "validate_operator_review_package --out-dir",
        [
            sys.executable, str(VALIDATOR_PATH),
            "--out-dir", str(review_package),
        ],
    )
    if validator_outcome.rc != 0:
        print(f"  [FAIL] validate_operator_review_package rc="
              f"{validator_outcome.rc}")
        _print_outcome_tail(validator_outcome)
        return 1
    print(f"  [PASS] validate_operator_review_package rc=0 "
          f"(read-only / local-only)")
    return 0


def _run_workflow(
    *, images_dir: Path, out_dir: Path,
    manifest_src: Path | None = None,
    gen_prov_src: Path | None = None,
) -> int:
    """Drive the full one-command workflow into ``out_dir``. The caller
    MUST have already passed ``images_dir`` / ``out_dir`` / any supplied
    metadata path through their respective argument gates AND confirmed
    ``out_dir`` exists.

    Returns 0 on success, 1 on any stage failure. A torn run leaves
    whatever the helper / validator produced under ``out_dir``
    untouched — an operator inspects the partial state directly."""
    paths = _workflow_paths(out_dir)
    bundle = paths.bundle
    manifest = paths.manifest
    gen_prov = paths.gen_prov
    approved_plan = paths.approved_plan
    review_package = paths.review_package

    print(f"=== operator_images_to_review_package ===")
    print(f"  images-dir:         {images_dir}")
    print(f"  out-dir:            {out_dir}")
    print(f"  bundle:             {bundle}")
    print(f"  approved-plan:      {approved_plan}")
    print(f"  review-package:     {review_package}")
    if manifest_src is not None:
        print(f"  manifest (custom):  {manifest_src}")
    if gen_prov_src is not None:
        print(f"  gen-prov (custom):  {gen_prov_src}")
    print()

    rc = _stage_bundle_and_plan(
        images_dir=images_dir, paths=paths,
        manifest_src=manifest_src, gen_prov_src=gen_prov_src,
    )
    if rc != 0:
        return rc
    rc = _build_and_validate_review_package(paths=paths)
    if rc != 0:
        return rc
    # _build_and_validate_review_package returns 0 only when Stage F's
    # validator returned rc 0, so the README's validator rc is
    # definitionally 0 on the success path here.
    validator_rc = 0

    # Stage G — concise top-level operator-facing README carrying the
    # EXACT manual commands run, so the workflow is inspectable and
    # repeatable. Written last so a torn run never leaves a
    # positive-looking README behind.
    readme = out_dir / "README.md"
    readme.write_text(
        _render_workflow_readme(
            images_dir=images_dir,
            bundle=bundle,
            manifest=manifest,
            gen_prov=gen_prov,
            approved_plan=approved_plan,
            review_package=review_package,
            validator_rc=validator_rc,
            manifest_supplied=manifest_src is not None,
            gen_prov_supplied=gen_prov_src is not None,
        ),
        encoding="utf-8",
    )
    if not readme.is_file() or readme.is_symlink():
        print(f"  [FAIL] expected workflow README at {readme} as a "
              f"regular non-symlink file")
        return 1
    print(f"  [PASS] workflow README written to {readme}")

    print()
    print(f"OK: review package under {review_package}. Open {readme} first.")
    return 0


# ---------------------------------------------------------------------------
# Two-step reviewed flow: --plan stages the bundle + reviewable plan and
# STOPS; a human inspects the plan; --resume builds the review package
# from the reviewed plan using the same approved-plan run lock,
# validators, and evidence as one-command mode. The split is the first
# practical human-review checkpoint in this lane: nothing downstream is
# built until a person runs --resume.
# ---------------------------------------------------------------------------


def _validate_resume_out_dir_arg(
    out_dir_str: str,
) -> tuple[Path | None, list[str]]:
    """Validate ``--out-dir`` for resume mode. Unlike the fresh-out-dir
    gate the one-command / plan steps use, resume REQUIRES a
    pre-existing plan-mode output: the directory must already exist and
    carry ``bundle/`` + ``approved_plan.json`` (what a ``--plan`` run
    staged). The path-safety refusals (URI / symlink / symlink-ancestor
    / repo-tree anchor) match the fresh gate so resume cannot be pointed
    at a redirected or in-repo path. The deeper bundle re-validation
    (image bytes, manifest, sidecar, drift against the approved plan)
    is left to the helper's approved-plan run lock."""
    if _URI_SCHEME_PREFIX.match(out_dir_str):
        return None, [
            f"--out-dir argument {out_dir_str!r} looks URI-shaped; "
            f"operator mode only accepts local file paths."
        ]

    out_dir = Path(out_dir_str)

    if out_dir.is_symlink():
        try:
            tgt = os.readlink(out_dir)
        except OSError:
            tgt = "<unreadable>"
        return None, [
            f"--out-dir {out_dir} is a symlink (-> {tgt}); refused so a "
            f"symlink target cannot redirect where the review package "
            f"is built."
        ]

    forbidden = _forbidden_symlink_ancestor(out_dir)
    if forbidden is not None:
        ancestor, tgt = forbidden
        return None, [
            f"--out-dir {out_dir} has a symlink ancestor {ancestor} "
            f"(-> {tgt}); refused so a symlink in the typed path cannot "
            f"redirect where the review package is built."
        ]

    try:
        resolved = out_dir.resolve(strict=False)
    except OSError as exc:
        return None, [
            f"--out-dir {out_dir} could not be resolved: "
            f"{type(exc).__name__}: {exc}"
        ]
    repo_root = REPO_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(repo_root)
        return None, [
            f"--out-dir {resolved} lexically anchors under "
            f"REPO_ROOT={repo_root}; refused — operator output must "
            f"land outside the committed repo tree."
        ]
    except ValueError:
        pass

    if not out_dir.exists():
        return None, [
            f"--out-dir {out_dir} does not exist; --resume rebuilds the "
            f"review package from a plan staged by a prior --plan run. "
            f"Run --plan against this --out-dir first."
        ]
    if not out_dir.is_dir():
        return None, [
            f"--out-dir {out_dir} exists but is not a directory."
        ]

    bundle = out_dir / "bundle"
    approved_plan = out_dir / "approved_plan.json"
    if bundle.is_symlink() or not bundle.is_dir():
        return None, [
            f"--out-dir {out_dir} has no regular bundle/ directory "
            f"(bundle={bundle}); --resume expects the bundle a prior "
            f"--plan run staged. Run --plan against this --out-dir "
            f"first."
        ]
    if approved_plan.is_symlink() or not approved_plan.is_file():
        return None, [
            f"--out-dir {out_dir} has no regular approved_plan.json "
            f"(approved_plan={approved_plan}); --resume expects the "
            f"reviewable plan a prior --plan run wrote. Run --plan "
            f"against this --out-dir first."
        ]

    review_package = out_dir / "review_package"
    if review_package.exists() or review_package.is_symlink():
        return None, [
            f"--out-dir {out_dir} already has a review_package/ "
            f"({review_package}); --resume refuses to overwrite a built "
            f"review package. Inspect it, or pass a fresh --out-dir and "
            f"re-run --plan."
        ]

    return out_dir, []


def _run_plan_mode(
    *, images_dir: Path, out_dir: Path,
    manifest_src: Path | None = None,
    gen_prov_src: Path | None = None,
) -> int:
    """Plan step of the two-step reviewed flow. Stages the bundle and
    the manifest + generated-provenance metadata (operator-supplied when
    given, else the helper's starter templates) + reviewable plan, then
    STOPS before building the review package — no ``deck.pptx`` /
    ``review_package/`` is produced. The operator inspects the staged
    plan and, when satisfied, runs ``--resume`` against the same
    ``--out-dir``. The caller MUST have already passed every arg through
    its gate and confirmed ``out_dir`` exists.

    Returns 0 on success, 1 on any stage failure."""
    paths = _workflow_paths(out_dir)

    print(f"=== operator_images_to_review_package --plan ===")
    print(f"  images-dir:         {images_dir}")
    print(f"  out-dir:            {out_dir}")
    print(f"  bundle:             {paths.bundle}")
    print(f"  reviewable-plan:    {paths.approved_plan}")
    if manifest_src is not None:
        print(f"  manifest (custom):  {manifest_src}")
    if gen_prov_src is not None:
        print(f"  gen-prov (custom):  {gen_prov_src}")
    print()

    rc = _stage_bundle_and_plan(
        images_dir=images_dir, paths=paths,
        manifest_src=manifest_src, gen_prov_src=gen_prov_src,
    )
    if rc != 0:
        return rc

    # Belt-and-braces: plan mode must NOT have produced any review
    # package or deck. _stage_bundle_and_plan never builds one, but
    # assert it here so a future change that leaks a build into the
    # stage step is caught at run time, not just in --self-test.
    leaked = [
        n for n in _REVIEW_PACKAGE_FILES + _REVIEW_PACKAGE_DIRS
        if (paths.review_package / n).exists()
    ]
    if paths.review_package.exists() or leaked:
        print(f"  [FAIL] plan mode unexpectedly produced review-package "
              f"output under {paths.review_package} (leaked={leaked!r}); "
              f"plan mode must stop before any deck.pptx / "
              f"review_package is built.")
        return 1
    print(f"  [PASS] no review_package / deck.pptx produced (plan mode "
          f"stops at the review checkpoint)")

    # Top-level README: what to review + how to resume. Written last so
    # a torn plan run never leaves a positive-looking README behind.
    readme = out_dir / "README.md"
    readme.write_text(
        _render_plan_readme(
            images_dir=images_dir, paths=paths,
            manifest_supplied=manifest_src is not None,
            gen_prov_supplied=gen_prov_src is not None,
        ),
        encoding="utf-8",
    )
    if not readme.is_file() or readme.is_symlink():
        print(f"  [FAIL] expected plan README at {readme} as a regular "
              f"non-symlink file")
        return 1
    print(f"  [PASS] plan README written to {readme}")

    print()
    print(f"OK: plan staged under {out_dir}. Review {readme}, then run "
          f"--resume --out-dir {out_dir} to build the review package.")
    return 0


def _run_resume_mode(*, out_dir: Path) -> int:
    """Resume step of the two-step reviewed flow. Builds the review
    package from the operator-reviewed plan staged by a prior ``--plan``
    run, using the SAME approved-plan run lock, validators, and evidence
    as one-command mode. The caller MUST have already passed ``out_dir``
    through ``_validate_resume_out_dir_arg`` (which confirms the
    plan-mode artifacts are present). Running ``--resume`` is the
    operator's explicit signal that the staged plan has been reviewed
    and approved.

    Returns 0 on success, 1 on any stage failure."""
    paths = _workflow_paths(out_dir)

    print(f"=== operator_images_to_review_package --resume ===")
    print(f"  out-dir:            {out_dir}")
    print(f"  bundle:             {paths.bundle}")
    print(f"  approved-plan:      {paths.approved_plan}")
    print(f"  review-package:     {paths.review_package}")
    print()

    rc = _build_and_validate_review_package(paths=paths)
    if rc != 0:
        return rc
    # _build_and_validate_review_package returns 0 only when Stage F's
    # validator returned rc 0, so the README's validator rc is
    # definitionally 0 on the success path here.
    validator_rc = 0

    # Final top-level README: overwrites the plan-step checkpoint guide
    # now that the run has progressed past review. Refuse a symlink
    # planted at the README path between the plan and resume steps so
    # the write cannot be redirected through it.
    readme = out_dir / "README.md"
    if readme.is_symlink():
        print(f"  [FAIL] {readme} is a symlink; refused so the resume "
              f"README write cannot be redirected through a symlink "
              f"planted after the plan step.")
        return 1
    readme.write_text(
        _render_resume_readme(paths=paths, validator_rc=validator_rc),
        encoding="utf-8",
    )
    if not readme.is_file() or readme.is_symlink():
        print(f"  [FAIL] expected resume README at {readme} as a regular "
              f"non-symlink file")
        return 1
    print(f"  [PASS] resume README written to {readme}")

    print()
    print(f"OK: review package under {paths.review_package}. Open "
          f"{readme} first.")
    return 0


# ---------------------------------------------------------------------------
# Prepare-images convenience: copy a flat PNG / JPG / JPEG folder into
# <out-dir>/images/ under STABLE SAFE filenames and write an inspectable
# filename_mapping.json (+ short README.md), then STOP. Real generated-image
# folders routinely carry names with spaces, uppercase, parentheses, or CJK
# characters that fail the downstream IG6 / IG7 basename contract; this step
# lets an operator feed such a folder into the existing --templates-only /
# --plan / --resume workflow WITHOUT hand-renaming every file. Builds nothing
# heavier — no bundle/, approved_plan.json, review_package/, deck.pptx,
# workspace/, or reports/.
# ---------------------------------------------------------------------------


def _safe_image_stem(stem: str) -> str:
    """Normalise an operator image filename STEM (basename minus extension)
    into a stable, downstream-safe BASE stem (the caller disambiguates
    same-base collisions; see ``_disambiguated_stem``).

    The result is guaranteed BY CONSTRUCTION to satisfy the STRICT
    downstream image-reference contract ``_IMAGE_REF_PATTERN``
    (``^[a-z][a-z0-9_]*$``) — the pattern the render_model ``image_ref`` /
    image_manifest ``id`` must match, since the operator lane uses the
    filename stem verbatim as the asset_id and that asset_id becomes the
    slide's image_ref. Because that pattern is stricter than (and implies)
    the helper's IG6 ``--images-dir`` basename gate, a prepared name that
    satisfies it is accepted at BOTH the bundle/manifest stage AND when the
    deck is built.

    Every character outside ``[a-z0-9_]`` — spaces, parentheses, dots,
    hyphens, CJK glyphs, uppercase letters, and any other shape a real
    generated-image folder produces — is mapped to ``_`` (after lowercasing,
    so uppercase survives as its lowercase form) and runs of ``_`` are
    collapsed. A stem that carried NO ``[a-z0-9]`` content at all — a
    CJK-only or punctuation-only name, the exact friction this step exists
    to absorb — has nothing left to make readable, so it falls back to the
    uniform base ``img``; the caller then turns the resulting same-base
    collisions into ``img`` / ``img_2`` / ``img_3`` … with a deterministic
    numeric suffix rather than refusing the run, so an operator with a
    CJK-heavy folder need not hand-rename anything. A stem that has content
    but does not start with a lowercase letter (a leading digit / ``_``) is
    prefixed ``img_``; the result is truncated to the byte cap.

    Pure + deterministic: the same input always yields the same output, so
    two operator files share a base stem iff they genuinely normalise to the
    same name — the caller assigns the later ones a deterministic numeric
    suffix instead of silently overwriting."""
    safe = re.sub(r"[^a-z0-9_]", "_", stem.lower())
    safe = re.sub(r"_+", "_", safe)
    if not re.search(r"[a-z0-9]", safe):
        # Degenerate: the stem carried no [a-z0-9] content at all (a
        # CJK-only / punctuation-only name). Nothing remains to make
        # readable, so fall back to a single uniform base; the caller
        # disambiguates same-base collisions with a deterministic suffix.
        return "img"
    if not re.match(r"[a-z]", safe):
        # Has content but starts with a digit / '_'; the image_ref contract
        # requires a leading lowercase LETTER, so prefix a literal and
        # re-collapse the doubled separator.
        safe = re.sub(r"_+", "_", "img_" + safe)
    return safe[:_ID_MAX_LEN]


def _disambiguated_stem(base: str, used: set[str]) -> str:
    """Return ``base`` if it is free, else the first ``base_<n>`` (n >= 2)
    not already in ``used``, truncating ``base`` so the suffixed result
    stays within ``_ID_MAX_LEN`` bytes.

    Deterministic given the same ``used`` set and call order: the caller
    walks the SORTED entry list and threads one ``used`` set through it, so
    the same folder content always yields the same assignment regardless of
    the order the filesystem listed the directory in. The output still
    matches ``_IMAGE_REF_PATTERN`` because ``base`` already does (it starts
    with a lowercase letter) and the only thing appended is ``_<digits>``.
    This is the deterministic suffix strategy that lets a folder of names
    which normalise to the same base — several CJK-only files all mapping to
    ``img``, or ``My File.png`` + ``my_file.png`` both mapping to
    ``my_file`` — prepare successfully instead of being refused."""
    if base not in used:
        return base
    n = 2
    while True:
        suffix = f"_{n}"
        cand = base[: _ID_MAX_LEN - len(suffix)] + suffix
        if cand not in used:
            return cand
        n += 1


def _render_prepare_readme(*, images_dir: Path, out_images: Path) -> str:
    """Render the short README written into a --prepare-images-only
    --out-dir. Names the three outputs and carries the shell-safe next-step
    command (feed the prepared ``images/`` into --templates-only). Every path
    that lands in a fenced command block goes through ``shlex.quote`` so a
    folder containing spaces / quotes survives copy-paste — mirrors
    ``_render_workflow_readme``'s quoting discipline."""
    images_q = shlex.quote(str(images_dir))
    out_dir_q = shlex.quote(str(out_images.parent))
    out_images_q = shlex.quote(str(out_images))
    mapping_q = shlex.quote(str(out_images.parent / "filename_mapping.json"))
    return "\n".join([
        "# operator_images_to_review_package — prepared image folder",
        "",
        "This folder was produced by `--prepare-images-only`. It copied a "
        "flat PNG / JPG / JPEG folder into `images/` under stable, "
        "downstream-safe filenames and recorded the original -> safe "
        "mapping. The operator's source folder was NOT modified, and "
        "NOTHING heavier was built (no `bundle/`, `approved_plan.json`, "
        "`review_package/`, `deck.pptx`, `workspace/`, or `reports/`).",
        "",
        "## Contents",
        "",
        "- `images/` — the copied images, renamed to safe filenames whose "
        "stems satisfy the downstream image_ref contract "
        "(`^[a-z][a-z0-9_]*$`, lowercased, unique).",
        "- `filename_mapping.json` — one record per image: "
        "`original_filename`, `safe_filename`, `byte_count`, `sha256`, "
        "`media_type`, and `extension`.",
        "- `README.md` — this file.",
        "",
        "## Producing command",
        "",
        "```",
        "python3 scripts/operator_images_to_review_package.py "
        "--prepare-images-only \\",
        f"    --images-dir {images_q} \\",
        f"    --out-dir {out_dir_q}",
        "```",
        "",
        "## Next step",
        "",
        "Author starter metadata (or run the full review-package workflow) "
        "from the prepared `images/`. Pass `--filename-mapping "
        "filename_mapping.json` so the manifest's `slide_title` / `alt_text` "
        "keep the human-readable ORIGINAL filenames instead of the "
        "normalized safe names:",
        "",
        "```",
        "python3 scripts/operator_images_to_review_package.py "
        "--templates-only \\",
        f"    --images-dir {out_images_q} \\",
        f"    --filename-mapping {mapping_q} \\",
        "    --out-dir <FRESH_OUT_DIR>",
        "```",
        "",
        "Local-only: no network, no D-One, no model API, no image search.",
        "",
    ])


def _run_prepare_images_only(*, images_dir: Path, out_dir: Path) -> int:
    """Copy a flat PNG / JPG / JPEG folder into ``<out-dir>/images/`` under
    stable, downstream-safe filenames and write an inspectable
    ``filename_mapping.json`` + short ``README.md``, then STOP. Builds
    NOTHING heavier — no bundle/, approved_plan.json, review_package/,
    deck.pptx, workspace/, or reports/. The caller MUST have already passed
    ``images_dir`` / ``out_dir`` through their gates and created ``out_dir``.

    Every entry is first run through ``_preflight_image_entries`` (the SAME
    safety gates the bundle-staging path applies — symlink / subdirectory /
    non-image / hidden-dotfile / size + count caps), then each surviving
    name is normalised with ``_safe_image_stem`` and any two names that
    normalise to the same base stem (matching the helper's IG7 "no two
    filenames share a stem" rule) are given distinct names via a
    deterministic numeric suffix (``_disambiguated_stem``) — so a CJK-heavy
    or otherwise messy folder prepares successfully without hand-renaming —
    while a stem that still violates the image_ref contract (a truly unsafe
    input) is refused BEFORE any byte is copied, so a refused run leaves no
    half-written ``images/`` behind. Surviving files are copied under their
    safe names with the same race-safe O_NOFOLLOW / S_ISREG / bounded-read
    gate the other modes use. Returns 0 on success, 1 on any refusal or copy
    failure."""
    out_images = out_dir / "images"
    mapping_path = out_dir / "filename_mapping.json"
    readme_path = out_dir / "README.md"

    print("=== operator_images_to_review_package --prepare-images-only ===")
    print(f"  images-dir:    {images_dir}")
    print(f"  out-dir:       {out_dir}")
    print(f"  images out:    {out_images}")
    print(f"  mapping:       {mapping_path}")
    print()

    # Shared safety pre-flight (identical to the bundle-staging path). No
    # output is created until every entry passes.
    entries, failures = _preflight_image_entries(images_dir)
    if failures:
        for line in failures:
            print(f"  [FAIL] {line}")
        return 1

    # Compute the safe filename for every entry BEFORE creating images/, so
    # a refused run leaves no half-written output. ``entries`` is already
    # sorted (``_preflight_image_entries`` sorts it), and ``_disambiguated_
    # stem`` threads one ``used`` set through that sorted walk, so two names
    # that normalise to the same base stem — several CJK-only files all
    # mapping to ``img``, or ``My File.png`` + ``my_file.png`` both mapping
    # to ``my_file`` — are assigned distinct names (``img`` / ``img_2`` …,
    # ``my_file`` / ``my_file_2``) deterministically instead of refusing the
    # run. Uniqueness is enforced on the safe STEM (not the full filename) to
    # match the helper's IG7 rule — ``a.png`` and ``a.jpg`` share the stem
    # ``a`` and would collide downstream even though their full names differ.
    plan: list[tuple[Path, str]] = []   # (source entry, safe filename)
    used: set[str] = set()              # safe stems already taken this run
    for child in entries:
        ext = child.suffix.lstrip(".").lower()
        safe_stem = _disambiguated_stem(_safe_image_stem(child.stem), used)
        # Belt-and-braces: the normalisation + numeric-suffix disambiguation
        # are built to satisfy the strict image_ref contract, but tie the
        # guarantee to that real downstream pattern so a future bug fails
        # closed instead of emitting a stem that would only break when the
        # deck is built. A stem that fails this is a TRULY unsafe input, so
        # the run is refused rather than disambiguated.
        if (not _IMAGE_REF_PATTERN.match(safe_stem)
                or len(safe_stem) > _ID_MAX_LEN):
            failures.append(
                f"--images-dir entry {child.name!r} normalised to stem "
                f"{safe_stem!r}, which does not satisfy the downstream "
                f"image_ref contract {_IMAGE_REF_PATTERN.pattern!r} "
                f"(<= {_ID_MAX_LEN} bytes); refused."
            )
            continue
        used.add(safe_stem)
        plan.append((child, f"{safe_stem}.{ext}"))
    if failures:
        for line in failures:
            print(f"  [FAIL] {line}")
        return 1

    # All names are safe + unique. Materialise images/ and copy each entry
    # under its safe name.
    try:
        out_images.mkdir(parents=False, exist_ok=False)
    except OSError as exc:
        print(f"  [FAIL] could not create {out_images}: "
              f"{type(exc).__name__}: {exc}")
        return 1

    mapping_images: list[dict] = []
    for child, safe_name in plan:
        dest = out_images / safe_name
        err = _copy_one_image_race_safe(child, dest, MAX_BYTES_PER_FILE)
        if err is not None:
            print(f"  [FAIL] {err}")
            return 1
        try:
            data = dest.read_bytes()
        except OSError as exc:
            print(f"  [FAIL] copied file {dest} could not be read back: "
                  f"{type(exc).__name__}: {exc}")
            return 1
        ext = safe_name.rsplit(".", 1)[1]
        mapping_images.append({
            "original_filename": child.name,
            "safe_filename": safe_name,
            "byte_count": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "media_type": _MEDIA_TYPE_BY_EXT[ext],
            "extension": ext,
        })
        print(f"  [PASS] {child.name!r} -> images/{safe_name}")

    mapping_images.sort(key=lambda e: e["safe_filename"])
    mapping = {
        "schema_version": "1",
        "prepared_image_count": len(mapping_images),
        "images": mapping_images,
    }
    try:
        mapping_path.write_text(
            json.dumps(mapping, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        readme_path.write_text(
            _render_prepare_readme(
                images_dir=images_dir, out_images=out_images,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"  [FAIL] could not write mapping / README: "
              f"{type(exc).__name__}: {exc}")
        return 1

    # Belt-and-braces leak guard: prepare mode must produce ONLY images/,
    # filename_mapping.json, and README.md — never a bundle / plan / review
    # package / deck. Mirrors _run_templates_only's leak guard.
    produced = sorted(p.name for p in out_dir.iterdir())
    if produced != ["README.md", "filename_mapping.json", "images"]:
        print(f"  [FAIL] prepare mode produced unexpected entries "
              f"{produced!r}; it must write only images/, "
              f"filename_mapping.json, and README.md.")
        return 1

    print()
    print(f"OK: prepared {len(mapping_images)} image(s) under {out_dir}:")
    print(f"  - images/                ({len(mapping_images)} "
          f"safe-named file(s))")
    print(f"  - filename_mapping.json  (original -> safe + byte_count / "
          f"sha256 / media_type)")
    print(f"  - README.md")
    print(f"Feed the prepared images into the existing workflow, e.g. "
          f"(--filename-mapping keeps the original filenames in the "
          f"manifest titles):")
    print(f"  python3 scripts/operator_images_to_review_package.py "
          f"--templates-only \\")
    print(f"      --images-dir {shlex.quote(str(out_images))} \\")
    print(f"      --filename-mapping "
          f"{shlex.quote(str(mapping_path))} \\")
    print(f"      --out-dir <FRESH_OUT_DIR>")
    return 0


# ---------------------------------------------------------------------------
# Template-only convenience: write JUST the two editable starter metadata
# files (manifest.json + generated_provenance.json) for the operator's
# image folder into --out-dir, then STOP. Builds no bundle, no plan, no
# review package, no deck — the on-disk output is exactly the two files an
# operator hand-edits and feeds back via --manifest / --generated-provenance.
# Both files are built from a single stable snapshot of the images (copied
# once into a temporary directory) so they always agree on the filename
# set. This is the metadata-authoring shortcut: it removes the manual JSON
# authoring an operator would otherwise do by hand.
# ---------------------------------------------------------------------------


def _prepared_image_digests(
    images_dir: Path,
) -> tuple[dict[str, dict] | None, list[str]]:
    """Return ``{basename: {"sha256": <hex>, "byte_count": <int>}}`` for every
    regular non-symlink file directly under ``images_dir`` — the snapshot the
    manifest was built from — so a supplied ``--filename-mapping`` can be
    bound to the ACTUAL prepared image bytes (not merely to the filename
    set). Returns ``(None, failures)`` on any read error."""
    digests: dict[str, dict] = {}
    try:
        entries = sorted(images_dir.iterdir())
    except OSError as exc:
        return None, [
            f"could not list prepared images {images_dir} for mapping "
            f"binding: {type(exc).__name__}: {exc}"
        ]
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            continue
        try:
            data = entry.read_bytes()
        except OSError as exc:
            return None, [
                f"could not read prepared image {entry} for mapping "
                f"binding: {type(exc).__name__}: {exc}"
            ]
        digests[entry.name] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "byte_count": len(data),
        }
    return digests, []


def _load_filename_mapping(
    mapping_path: Path, prepared_digests: dict[str, dict],
) -> tuple[dict[str, str] | None, list[str]]:
    """Parse ``--prepare-images-only``'s ``filename_mapping.json`` and
    return a ``{safe_filename: original_filename}`` dict, or
    ``(None, failures)``.

    ``prepared_digests`` maps each PREPARED image basename to the
    ``{"sha256", "byte_count"}`` of its actual bytes (computed by the caller
    from the snapshot the manifest was built from). The mapping is bound to
    those BYTES, not merely to the filename set: it fails closed unless

      * the mapping's ``safe_filename`` set EXACTLY equals the prepared image
        basenames, AND
      * every record's recorded ``sha256`` / ``byte_count`` matches the
        prepared bytes of that safe name.

    So a stale or unrelated mapping that happens to reuse the same safe
    filenames but describes DIFFERENT image bytes (and therefore different
    original filenames) is refused rather than mislabelling the deck.
    Structural problems (non-object root, missing / empty ``images[]``, a
    record missing a non-empty string ``original_filename`` / ``safe_filename``
    / ``sha256`` or a non-negative integer ``byte_count``, or a duplicate
    ``safe_filename``) also fail closed so a hand-edited or unrelated JSON
    file is refused rather than half-applied."""
    try:
        raw = mapping_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [
            f"--filename-mapping {mapping_path} could not be read: "
            f"{type(exc).__name__}: {exc}"
        ]
    try:
        data = json.loads(raw)
    except ValueError as exc:
        return None, [
            f"--filename-mapping {mapping_path} is not valid JSON: {exc}"
        ]
    if not isinstance(data, dict):
        return None, [
            f"--filename-mapping {mapping_path} top-level is "
            f"{type(data).__name__}; expected a JSON object (the shape "
            f"--prepare-images-only writes)."
        ]
    rows = data.get("images")
    if not isinstance(rows, list) or not rows:
        return None, [
            f"--filename-mapping {mapping_path} has no non-empty images[] "
            f"list; expected the --prepare-images-only mapping shape."
        ]
    mapping: dict[str, str] = {}
    recorded: dict[str, tuple[str, int]] = {}
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return None, [
                f"--filename-mapping {mapping_path} images[{idx}] is "
                f"{type(row).__name__}; expected a JSON object."
            ]
        original = row.get("original_filename")
        safe = row.get("safe_filename")
        sha = row.get("sha256")
        byte_count = row.get("byte_count")
        if not isinstance(original, str) or not original:
            return None, [
                f"--filename-mapping {mapping_path} images[{idx}] has no "
                f"non-empty string original_filename."
            ]
        if not isinstance(safe, str) or not safe:
            return None, [
                f"--filename-mapping {mapping_path} images[{idx}] has no "
                f"non-empty string safe_filename."
            ]
        if not isinstance(sha, str) or not sha:
            return None, [
                f"--filename-mapping {mapping_path} images[{idx}] has no "
                f"non-empty string sha256; the mapping must carry the "
                f"prepared-byte digest to bind to the images. Pass the "
                f"filename_mapping.json --prepare-images-only wrote."
            ]
        # Reject bool explicitly: ``isinstance(True, int)`` is True, so a
        # JSON ``true`` byte_count would otherwise slip past the int check.
        if (not isinstance(byte_count, int) or isinstance(byte_count, bool)
                or byte_count < 0):
            return None, [
                f"--filename-mapping {mapping_path} images[{idx}] has no "
                f"non-negative integer byte_count; the mapping must carry "
                f"the prepared byte_count to bind to the images."
            ]
        if safe in mapping:
            return None, [
                f"--filename-mapping {mapping_path} images[{idx}] repeats "
                f"safe_filename {safe!r}; refused."
            ]
        mapping[safe] = original
        recorded[safe] = (sha, byte_count)
    mapping_set = set(mapping)
    prepared_set = set(prepared_digests)
    if mapping_set != prepared_set:
        orphan = sorted(mapping_set - prepared_set)
        missing = sorted(prepared_set - mapping_set)
        return None, [
            f"--filename-mapping {mapping_path} does not correspond to the "
            f"prepared image set: safe_filename(s) {orphan!r} are not among "
            f"the images, and image(s) {missing!r} are not in the mapping. "
            f"Pass the filename_mapping.json that --prepare-images-only "
            f"wrote next to the prepared images/."
        ]
    # Byte binding — every recorded digest must match the ACTUAL prepared
    # bytes, so a mapping that reuses the same safe names but describes a
    # different image set (and so different original filenames) is refused
    # rather than silently mislabelling the deck. Walk in sorted order for a
    # deterministic first-mismatch diagnostic.
    for safe in sorted(mapping_set):
        want_sha, want_bytes = recorded[safe]
        got = prepared_digests[safe]
        if got["sha256"] != want_sha or got["byte_count"] != want_bytes:
            return None, [
                f"--filename-mapping {mapping_path} does not match the "
                f"prepared bytes for {safe!r}: the mapping records "
                f"sha256={want_sha[:12]}... / {want_bytes} bytes but the "
                f"prepared image is sha256={got['sha256'][:12]}... / "
                f"{got['byte_count']} bytes. The mapping describes a "
                f"different image set; pass the filename_mapping.json "
                f"--prepare-images-only wrote for THESE images."
            ]
    return mapping, []


def _seed_manifest_titles_from_mapping(
    *, manifest: Path, mapping_path: Path, prepared_images: Path,
) -> list[str]:
    """Rewrite each manifest entry's ``slide_title`` / ``alt_text`` from the
    operator's ORIGINAL filename (recovered from the prepare step's
    ``filename_mapping.json``) instead of the normalized safe basename, then
    re-validate the rewritten manifest with the helper's own
    ``_validate_manifest_arg``. Returns ``[]`` on success or a list of
    failure lines.

    The mapping is bound to the ACTUAL bytes of ``prepared_images`` (the
    snapshot the manifest was built from): each image's sha256 / byte_count
    is computed and the mapping's recorded digest must match, so a stale or
    unrelated mapping that reuses the same safe filenames but describes
    different image bytes is refused rather than mislabelling the deck.

    Only the two human-readable title fields are touched — the per-entry
    ``filename`` stays the prepared safe name — so the manifest still covers
    exactly the prepared image set. The seeded titles use the SAME format
    functions the helper applies to a safe name (``_slide_title_for_name`` /
    ``_alt_text_for_name``), so the only difference from the default
    template is the display name. Re-validation through the helper gate
    means a seeded title that exceeds the length cap or trips the
    safe-string scan (an unusual original filename) fails closed here rather
    than producing a manifest that only breaks when fed to a later build."""
    digests, digest_fails = _prepared_image_digests(prepared_images)
    if digest_fails or digests is None:
        return digest_fails or [
            f"could not digest prepared images {prepared_images} for "
            f"mapping binding."
        ]
    mapping, fails = _load_filename_mapping(mapping_path, digests)
    if fails or mapping is None:
        return fails or [
            f"--filename-mapping {mapping_path} was refused."
        ]
    try:
        body = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [
            f"could not read back manifest {manifest} for title seeding: "
            f"{type(exc).__name__}: {exc}"
        ]
    images = body.get("images") if isinstance(body, dict) else None
    if not isinstance(images, list):
        return [f"manifest {manifest} has no images[] list to seed."]
    for entry in images:
        if not isinstance(entry, dict):
            return [
                f"manifest {manifest} has a non-object images[] entry; "
                f"refused."
            ]
        safe = entry.get("filename")
        original = mapping.get(safe)
        if original is None:
            return [
                f"manifest {manifest} names safe filename {safe!r} that is "
                f"absent from --filename-mapping; refused."
            ]
        entry["slide_title"] = _slide_title_for_name(original)
        entry["alt_text"] = _alt_text_for_name(original)
    try:
        manifest.write_text(
            json.dumps(body, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return [
            f"could not rewrite manifest {manifest} with seeded titles: "
            f"{type(exc).__name__}: {exc}"
        ]
    entries, _resolved, man_fails = _validate_manifest_arg(
        str(manifest), sorted(digests),
    )
    if man_fails or entries is None:
        return man_fails or [
            f"seeded manifest {manifest} failed the helper manifest "
            f"validator after title seeding."
        ]
    return []


def _run_templates_only(
    *, images_dir: Path, out_dir: Path, mapping_src: Path | None = None,
) -> int:
    """Write the two editable starter metadata templates for ``images_dir``
    into ``out_dir`` and STOP. The caller MUST have already passed
    ``images_dir`` / ``out_dir`` (and any ``mapping_src``) through their
    gates and created ``out_dir``.

    Both templates are written by the existing operator helper's
    ``--write-manifest-template`` / ``--write-generated-provenance-template``
    writers against a SINGLE stable image snapshot — the operator images
    are copied once into a private, auto-removed ``TemporaryDirectory`` and
    BOTH writers enumerate that copy, so the two files can never disagree
    on the filename set even if the operator's folder changes mid-run.
    Each writer emits its own schema-valid file, so this wrapper
    re-implements no contract logic.

    When ``mapping_src`` is given (the optional ``--filename-mapping``
    pointing at a ``--prepare-images-only`` ``filename_mapping.json``), the
    manifest's per-image ``slide_title`` / ``alt_text`` are re-seeded from
    each image's ORIGINAL filename instead of the normalized safe basename
    the snapshot carries, so a deck prepared from messy real-world names
    keeps human-readable titles. The mapping is bound to the snapshot BYTES
    (each record's recorded sha256 / byte_count must match the prepared
    image), so the seeding fails closed if the mapping does not correspond
    to the prepared image set OR describes different bytes, and the
    rewritten manifest is re-validated through the helper's own contract
    gate (see ``_seed_manifest_titles_from_mapping``). With no
    ``mapping_src`` the manifest is exactly the helper's default template
    (prior behavior).

    Nothing else is produced — no ``bundle/``, ``approved_plan.json``,
    ``review_package/``, or ``deck.pptx`` — and a belt-and-braces leak
    guard asserts that. Returns 0 on success, 1 on any stage failure (a
    torn run leaves whatever was written under ``out_dir`` for the
    operator to inspect / remove)."""
    manifest = out_dir / "manifest.json"
    gen_prov = out_dir / "generated_provenance.json"

    print(f"=== operator_images_to_review_package --templates-only ===")
    print(f"  images-dir:         {images_dir}")
    print(f"  out-dir:            {out_dir}")
    print(f"  manifest template:  {manifest}")
    print(f"  gen-prov template:  {gen_prov}")
    print()

    # Copy the operator images ONCE into a private, auto-removed snapshot
    # so BOTH template writers enumerate the SAME stable set of bytes.
    # Pointing each writer at the live --images-dir would let a
    # concurrent change between the two subprocess calls (a file added,
    # removed, or swapped — e.g. an image generator still writing into
    # the folder) produce a manifest.json and a generated_provenance.json
    # whose filename sets disagree. The snapshot lives OUTSIDE --out-dir
    # (a TemporaryDirectory honouring TMPDIR), so --out-dir still receives
    # ONLY the two templates, and the same race-safe copy gates the other
    # modes apply (O_NOFOLLOW / S_ISREG / per-file + count caps /
    # extension + .DS_Store filter) run here too.
    with tempfile.TemporaryDirectory(
        prefix="o2rp-templates-snapshot-",
    ) as raw_snap:
        snapshot_images = Path(raw_snap) / "images"
        copy_failures = _copy_images_into_bundle(images_dir, snapshot_images)
        if copy_failures:
            for line in copy_failures:
                print(f"  [FAIL] {line}")
            return 1
        discovered = sorted(p.name for p in snapshot_images.iterdir())
        print(f"  [PASS] snapshotted {len(discovered)} image(s) for a "
              f"stable template build: {discovered}")

        # Stage 1 — manifest starter template (from the stable snapshot).
        manifest_outcome = _run(
            "operator_local_images_to_editable_ppt "
            "--write-manifest-template",
            [
                sys.executable, str(HELPER_PATH),
                "--images-dir", str(snapshot_images),
                "--write-manifest-template", str(manifest),
            ],
        )
        if (manifest_outcome.rc != 0
                or not manifest.is_file()
                or manifest.is_symlink()):
            print(f"  [FAIL] manifest template helper rc="
                  f"{manifest_outcome.rc}; "
                  f"manifest_exists={manifest.exists()}")
            _print_outcome_tail(manifest_outcome)
            return 1
        print(f"  [PASS] manifest template written to {manifest}")

        # Stage 2 — generated-provenance starter template (from the SAME
        # snapshot; generator_source defaults to
        # operator_declared_generated).
        gen_prov_outcome = _run(
            "operator_local_images_to_editable_ppt "
            "--write-generated-provenance-template",
            [
                sys.executable, str(HELPER_PATH),
                "--images-dir", str(snapshot_images),
                "--write-generated-provenance-template", str(gen_prov),
            ],
        )
        if (gen_prov_outcome.rc != 0
                or not gen_prov.is_file()
                or gen_prov.is_symlink()):
            print(f"  [FAIL] generated-provenance template helper rc="
                  f"{gen_prov_outcome.rc}; "
                  f"gen_prov_exists={gen_prov.exists()}")
            _print_outcome_tail(gen_prov_outcome)
            return 1
        print(f"  [PASS] generated-provenance template written to "
              f"{gen_prov}")

        # Stage 3 (optional) — re-seed the manifest's slide_title /
        # alt_text from each image's ORIGINAL filename when the operator
        # passed --filename-mapping. Runs against the SAME snapshot the
        # writers used: the mapping's safe_filename set must match the
        # snapshot basenames AND each record's recorded sha256 / byte_count
        # must match the snapshot bytes, so a stale / unrelated mapping is
        # refused rather than mislabelling the deck. The rewritten manifest
        # is re-validated through the helper gate so an unsafe / over-long
        # seeded title fails closed. Only the manifest is touched — the
        # generated-provenance sidecar carries no filename-derived title.
        if mapping_src is not None:
            seed_failures = _seed_manifest_titles_from_mapping(
                manifest=manifest, mapping_path=mapping_src,
                prepared_images=snapshot_images,
            )
            if seed_failures:
                for line in seed_failures:
                    print(f"  [FAIL] {line}")
                return 1
            print(f"  [PASS] manifest slide_title / alt_text seeded from "
                  f"original filenames in {mapping_src}")

    # Belt-and-braces: template-only mode must NOT have produced any of
    # the heavier build artifacts. Mirrors _run_plan_mode's leak guard so
    # a future change that leaks a build into this mode is caught at run
    # time, not just in --self-test.
    leaked = [
        n for n in ("bundle", "approved_plan.json", "review_package",
                    "README.md")
        if (out_dir / n).exists()
    ]
    if leaked:
        print(f"  [FAIL] template-only mode unexpectedly produced "
              f"{leaked!r}; it must write only manifest.json + "
              f"generated_provenance.json.")
        return 1
    print(f"  [PASS] no bundle / approved_plan / review_package / deck "
          f"produced (template-only mode writes just the two templates)")

    print()
    print(f"OK: editable starter metadata under {out_dir}:")
    if mapping_src is not None:
        print(f"  - manifest.json  (slide_title / alt_text seeded from "
              f"original filenames)")
    else:
        print(f"  - manifest.json")
    print(f"  - generated_provenance.json")
    print(f"Hand-edit them, then build with --manifest / "
          f"--generated-provenance, e.g.:")
    print(f"  python3 scripts/operator_images_to_review_package.py \\")
    print(f"      --images-dir {shlex.quote(str(images_dir))} \\")
    print(f"      --out-dir <FRESH_OUT_DIR> \\")
    print(f"      --manifest {shlex.quote(str(manifest))} \\")
    print(f"      --generated-provenance {shlex.quote(str(gen_prov))}")
    return 0


def _render_workflow_readme(
    *,
    images_dir: Path,
    bundle: Path,
    manifest: Path,
    gen_prov: Path,
    approved_plan: Path,
    review_package: Path,
    validator_rc: int,
    manifest_supplied: bool = False,
    gen_prov_supplied: bool = False,
) -> str:
    """Render the workflow's top-level operator-facing README. Carries
    the EXACT argv this run executed (``sys.executable`` +
    ``HELPER_PATH`` / ``VALIDATOR_PATH``, NOT a substituted
    ``python3`` + relative-path equivalent — Codex caught the earlier
    drift), so the rendered commands are a faithful audit trail of
    what subprocess.run actually saw. Every path embedded in a
    fenced shell-command block goes through ``shlex.quote`` so
    paths containing spaces / quotes / shell metacharacters
    (e.g. ``~/Pictures/Screen Shots/``) survive copy-paste without
    breaking the command or executing injected shell fragments.

    ``manifest_supplied`` / ``gen_prov_supplied`` keep the audit trail
    honest: when the operator passed ``--manifest`` /
    ``--generated-provenance``, that metadata was VALIDATED-AND-COPIED
    into the bundle, not template-generated, so the corresponding step
    is rendered as a staging note rather than a helper subprocess
    command that never ran."""
    bundle_images = bundle / "images"
    rp = review_package.name  # "review_package", relative to <out-dir>.
    # Pre-quote every path that lands inside a fenced command block.
    # ``python_q`` / ``helper_q`` / ``validator_q`` are quoted forms
    # of the EXACT argv head the subprocess saw (sys.executable +
    # the absolute HELPER_PATH / VALIDATOR_PATH). Operators on the
    # same machine can copy-paste verbatim; operators on a different
    # machine should substitute their local interpreter / path.
    python_q = shlex.quote(sys.executable)
    helper_q = shlex.quote(str(HELPER_PATH))
    validator_q = shlex.quote(str(VALIDATOR_PATH))
    images_q = shlex.quote(str(images_dir))
    bundle_q = shlex.quote(str(bundle))
    bundle_images_q = shlex.quote(str(bundle_images))
    manifest_q = shlex.quote(str(manifest))
    gen_prov_q = shlex.quote(str(gen_prov))
    approved_plan_q = shlex.quote(str(approved_plan))
    review_package_q = shlex.quote(str(review_package))
    out_dir_q = shlex.quote(str(review_package.parent))

    # Steps 1 and 2 are rendered to match what actually ran. With no
    # custom metadata, they show the helper template-write subprocesses
    # verbatim (the default audit trail). When the operator passed
    # --manifest / --generated-provenance, no template subprocess ran —
    # the supplied file was validated against the copied image basenames
    # and copied into the bundle — so the step is a staging note, never a
    # command that did not execute.
    if manifest_supplied:
        step1 = [
            "# 1. Operator-supplied manifest staged into the bundle. No "
            "template was generated: the --manifest file you passed was "
            "validated against the manifest contract gates (schema, "
            "closed field set, local-only / no-network / no-credential / "
            "no-raw-source wording, filename set == the copied images) "
            "and copied verbatim to bundle/manifest.json.",
            f"#    staged to: {manifest_q}",
        ]
    else:
        step1 = [
            "# 1. Manifest template (defaults the operator can hand-edit "
            "before plan-out):",
            f"{python_q} {helper_q} \\",
            f"    --images-dir {bundle_images_q} \\",
            f"    --write-manifest-template {manifest_q}",
        ]
    if gen_prov_supplied:
        step2 = [
            "# 2. Operator-supplied generated-provenance staged into the "
            "bundle. No template was generated: the "
            "--generated-provenance file you passed was validated "
            "against the sidecar contract gates (schema, closed enums, "
            "local-only / no-network / no-credential / no-raw-source "
            "wording, filename set == the copied images) and copied "
            "verbatim to bundle/generated_provenance.json.",
            f"#    staged to: {gen_prov_q}",
        ]
    else:
        step2 = [
            "# 2. Generated-provenance sidecar template "
            "(operator_declared_generated placeholders):",
            f"{python_q} {helper_q} \\",
            f"    --bundle {bundle_q} \\",
            f"    --write-generated-provenance-template {gen_prov_q}",
        ]

    metadata_note: list[str] = []
    if manifest_supplied or gen_prov_supplied:
        which = []
        if manifest_supplied:
            which.append("manifest.json")
        if gen_prov_supplied:
            which.append("generated_provenance.json")
        metadata_note = [
            f"**This run used operator-supplied metadata** "
            f"({' and '.join(which)}): the file(s) you passed were "
            f"validated and copied into the bundle in place of the "
            f"default template(s), so `approved_plan.json` and the "
            f"review-package `summary.json` reflect your supplied "
            f"values. Steps 1-2 below record that staging instead of a "
            f"template-write command.",
            "",
        ]

    return "\n".join([
        "# operator_images_to_review_package — review package",
        "",
        "One-command operator workflow for the core local "
        "image-to-editable-PPT lane. Starts from a caller-supplied "
        "folder of generated images and ends with a validated editable "
        "PPTX review package, written by the existing operator helper "
        "under an approved-plan run lock.",
        "",
        "## What to open first",
        "",
        f"1. `{rp}/README.md` — helper-written review-package README. "
        "Names every produced artifact and the approved-plan lock "
        "evidence.",
        f"2. `{rp}/deck.pptx` — the produced editable PPTX. "
        "Native PowerPoint shapes; one slide per source image.",
        f"3. `{rp}/summary.json` — compact summary. The "
        "`approved_plan.matched=true` block confirms the run lock and "
        "the `generated_provenance` block surfaces the sidecar this "
        "workflow staged.",
        f"4. `{rp}/inventory.json` and `{rp}/visual_quality.json` — "
        "helper-validated readbacks.",
        f"5. `{rp}/workspace/source_image_assets.json` and "
        f"`{rp}/reports/pipeline_report.{{json,txt}}` — the underlying "
        "pipeline's per-image registry + report.",
        "",
        "## Manual commands this run executed",
        "",
        *metadata_note,
        "This workflow script only sequences the existing helpers; "
        "every line below ran verbatim against your `--out-dir` so the "
        "run is inspectable. **Steps 1-4 fail closed on re-run** "
        "because the helper refuses to overwrite the manifest / "
        "generated-provenance / approved-plan / review-package "
        "artifacts they already wrote (no overwrite by design). Only "
        "Step 5 (the read-only validator) is safe to re-run directly. "
        "To repeat the full workflow against an updated source folder, "
        "see the *Re-running this workflow* section below.",
        "",
        "```",
        *step1,
        "",
        *step2,
        "",
        "# 3. Plan-out (writes the reviewer-approved plan without "
        "running the pipeline):",
        f"{python_q} {helper_q} \\",
        f"    --bundle {bundle_q} \\",
        f"    --plan-out {approved_plan_q}",
        "",
        "# 4. Approved-plan run lock (this workflow AUTO-APPROVES "
        "its own Stage-3 plan — see the 'Auto-approval' section "
        "below for what that means and what it does NOT verify):",
        f"{python_q} {helper_q} \\",
        f"    --bundle {bundle_q} \\",
        f"    --approved-plan {approved_plan_q} \\",
        f"    --out-dir {review_package_q}",
        "",
        "# 5. Read-only stdlib re-check of the produced review package:",
        f"{python_q} {validator_q} \\",
        f"    --out-dir {review_package_q}",
        "```",
        "",
        f"Step 5 returned rc={validator_rc}. Re-run it any time with "
        "the same command above — the validator is read-only and does "
        "not mutate the package.",
        "",
        "## Auto-approval — what this workflow does NOT verify",
        "",
        "Stage 4 above was driven with the same `approved_plan.json` "
        "that Stage 3 had JUST written. No human reviewer inspected "
        "the plan in between. This is an automation convenience, "
        "**not a substitute for human review**: the `--approved-plan` "
        "gate only catches drift BETWEEN Stage 3 and Stage 4 (a "
        "concurrent process modifying the bundle, the bytes under "
        "`bundle/images/` changing, an edit to `manifest.json` / "
        "`generated_provenance.json`). It does NOT verify that the "
        "plan itself is a good plan, that the slide titles read "
        "well, that the per-image `intended_use` reflects business "
        "intent, or that the generated-provenance sidecar describes "
        "the bytes honestly.",
        "",
        "If you need a true reviewer-approval loop, run Stages 1-3 "
        "of *Manual commands this run executed* above by hand, "
        "inspect `approved_plan.json` / `manifest.json` / "
        "`generated_provenance.json` directly, then run Stage 4 "
        "separately (or hand the approved plan off to another "
        "reviewer to run Stage 4). The helper's plan-out / "
        "approved-plan / out-dir contracts are designed for "
        "exactly that workflow; this script just sequences them "
        "end-to-end for convenience.",
        "",
        "## Re-running this workflow",
        "",
        "The helper refuses to overwrite the manifest / "
        "generated-provenance / approved-plan / review-package "
        "artifacts (no overwrite by design), so re-running Steps 1-4 "
        "in place fails closed. To regenerate the review package "
        "against an updated source folder, point this script at a "
        "**fresh** `--out-dir`:",
        "",
        "```",
        f"python3 scripts/operator_images_to_review_package.py \\",
        f"    --images-dir {images_q} \\",
        f"    --out-dir <FRESH_DIR_OUTSIDE_THE_REPO>",
        "```",
        "",
        "Or, if you intend to discard the current run, remove this "
        "directory first and reuse the same path:",
        "",
        "```",
        f"rm -rf {out_dir_q}",
        f"python3 scripts/operator_images_to_review_package.py \\",
        f"    --images-dir {images_q} \\",
        f"    --out-dir {out_dir_q}",
        "```",
        "",
        "## Source images",
        "",
        f"Operator folder: `{images_dir}` — copied byte-identically "
        f"into `{bundle_images}`. The original folder was not "
        "mutated. The helper's IG1..IG9 gates re-validated every "
        "copied byte; non-image content or stems outside the "
        "`^[A-Za-z0-9][A-Za-z0-9_.\\-]*$` pattern would have refused "
        "Stage 2 above. (Paths in the prose above are shown "
        "unquoted for readability; every path embedded in the fenced "
        "shell commands is `shlex.quote`d so a folder name like "
        "`Screen Shots` survives copy-paste.)",
        "",
        "## Approved-plan drift gate",
        "",
        "Editing `bundle/manifest.json`, `bundle/generated_provenance"
        ".json`, or any byte under `bundle/images/` AFTER Stage 3 will "
        "make Stage 4 fail closed (the helper recomputes the in-memory "
        "plan from the current bundle and refuses with rc 2 if it "
        "differs from the approved plan on image bytes, sidecar, "
        "manifest, or order). To approve a new plan, delete the "
        "current `approved_plan.json` + `review_package/` and re-run "
        "this workflow against the updated bundle.",
        "",
        "## Boundary statement",
        "",
        "Local-only. Does NOT call D-One, MCP, Qoder, a public "
        "network, telemetry, a model API, an image search, or any "
        "external service. Real D-One image generation remains "
        "UNVERIFIED. NOT a prompt / report / Markdown-to-PPTX "
        "automation.",
        "",
        "## Cleaning up",
        "",
        "When done inspecting, remove the workflow output directly:",
        "",
        "```",
        f"rm -rf {out_dir_q}",
        "```",
        "",
    ])


def _render_plan_readme(
    *, images_dir: Path, paths: _WorkflowPaths,
    manifest_supplied: bool = False,
    gen_prov_supplied: bool = False,
) -> str:
    """Render the plan-step top-level README: what the operator should
    review and the EXACT command to resume. Every path embedded in a
    fenced shell-command block goes through ``shlex.quote`` so a folder
    name with spaces / quotes survives copy-paste."""
    try:
        staged = sorted(p.name for p in paths.bundle_images.iterdir())
    except OSError:
        staged = []
    out_dir_q = shlex.quote(str(paths.out_dir))
    images_q = shlex.quote(str(images_dir))

    manifest_bullet = (
        "- `bundle/manifest.json` — the **operator-supplied** manifest "
        "(copied from your `--manifest` file after passing the contract "
        "gates) the plan was built from."
        if manifest_supplied else
        "- `bundle/manifest.json` — the default per-image slide_title / "
        "alt_text / intended_use the plan was built from."
    )
    gen_prov_bullet = (
        "- `bundle/generated_provenance.json` — the **operator-supplied** "
        "provenance (copied from your `--generated-provenance` file after "
        "passing the contract gates) the plan was built from."
        if gen_prov_supplied else
        "- `bundle/generated_provenance.json` — the default "
        "`operator_declared_generated` provenance the plan was built "
        "from."
    )

    return "\n".join([
        "# operator_images_to_review_package — staged plan (review me)",
        "",
        "This is the **plan step** of the two-step reviewed workflow for "
        "the local image-folder -> editable-PPT lane. The operator "
        "images have been copied into a local bundle and a reviewable "
        "plan has been written, but **no editable PPTX and no review "
        "package have been built yet**. Nothing downstream runs until a "
        "human reviews the staged plan and runs `--resume`.",
        "",
        "## What was staged",
        "",
        f"- `bundle/images/` — {len(staged)} image(s) copied "
        f"byte-identically from `{images_dir}`: {staged}. The original "
        "folder was not mutated.",
        manifest_bullet,
        gen_prov_bullet,
        "- `approved_plan.json` — the **reviewable plan**: the exact "
        "per-image filename / sha256 / intended slide / title / "
        "alt_text / intended_use the review package would be built "
        "from. Read this top to bottom.",
        "",
        "## Review is read-only — do NOT edit the staged files",
        "",
        "Resume locks against `approved_plan.json` exactly as staged "
        "here: it rebuilds the plan from the current bundle and **fails "
        "closed** if anything under `bundle/images/`, "
        "`bundle/manifest.json`, or `bundle/generated_provenance.json` "
        "changed. So review by READING, not editing — decide go / "
        "no-go on the plan as it stands:",
        "",
        "- Do the slide titles and per-image `intended_use` reflect the "
        "business intent?",
        "- Does each image map to the slide you expect (the plan is in "
        "deterministic order)?",
        "- Does `generated_provenance.json` describe the bytes "
        "honestly?",
        "",
        "If every answer is yes, resume below. If not, the plan is "
        "wrong — **discard and re-stage** (see *Start over*); do NOT "
        "edit the staged files, because that makes resume fail closed "
        "rather than rebuild the plan. To hand-author custom per-image "
        "titles / intent / provenance, re-run `--plan` with the "
        "wrapper's `--manifest <file>` and/or `--generated-provenance "
        "<file>` flags (a local reviewed `manifest.json` / "
        "`generated_provenance.json`), which are validated against the "
        "copied images and staged into the bundle in place of the "
        "default templates; or drive the lower-level "
        "`scripts/operator_local_images_to_editable_ppt.py` helper "
        "directly.",
        "",
        "## Resume — build the review package",
        "",
        "When the plan reads correctly, run the resume step. Running "
        "`--resume` is your explicit sign-off that the plan is "
        "approved (it re-runs the helper's approved-plan run lock "
        "against the current bundle and fails closed on any drift — "
        "see the read-only note above):",
        "",
        "```",
        "python3 scripts/operator_images_to_review_package.py \\",
        "    --resume \\",
        f"    --out-dir {out_dir_q}",
        "```",
        "",
        "## Start over",
        "",
        "To abandon this staged plan and re-stage from the source "
        "folder:",
        "",
        "```",
        f"rm -rf {out_dir_q}",
        "python3 scripts/operator_images_to_review_package.py \\",
        "    --plan \\",
        f"    --images-dir {images_q} \\",
        f"    --out-dir {out_dir_q}",
        "```",
        "",
        "## Boundary statement",
        "",
        "Local-only. Does NOT call D-One, MCP, Qoder, a public network, "
        "telemetry, a model API, an image search, or any external "
        "service. Real D-One image generation remains UNVERIFIED. NOT a "
        "prompt / report / Markdown-to-PPTX automation.",
        "",
    ])


def _render_resume_readme(
    *, paths: _WorkflowPaths, validator_rc: int,
) -> str:
    """Render the resume-step final top-level README. Overwrites the
    plan-step checkpoint guide. Carries the EXACT read-only re-check
    argv (``sys.executable`` + absolute ``VALIDATOR_PATH``), each path
    ``shlex.quote``d so it survives copy-paste."""
    rp = paths.review_package.name
    python_q = shlex.quote(sys.executable)
    validator_q = shlex.quote(str(VALIDATOR_PATH))
    review_package_q = shlex.quote(str(paths.review_package))
    out_dir_q = shlex.quote(str(paths.out_dir))
    return "\n".join([
        "# operator_images_to_review_package — review package (resumed)",
        "",
        "Built by the **resume step** of the two-step reviewed "
        "workflow. A human reviewed the staged plan "
        "(`approved_plan.json`) and ran `--resume`, which built this "
        "review package under the helper's approved-plan run lock — the "
        "same validators and evidence as one-command mode, with a real "
        "human-review checkpoint in front of it.",
        "",
        "## What to open first",
        "",
        f"1. `{rp}/README.md` — helper-written review-package README. "
        "Names every produced artifact and the approved-plan lock "
        "evidence.",
        f"2. `{rp}/deck.pptx` — the produced editable PPTX. Native "
        "PowerPoint shapes; one slide per source image.",
        f"3. `{rp}/summary.json` — compact summary. The "
        "`approved_plan.matched=true` block confirms the run lock; the "
        "`generated_provenance` block surfaces the reviewed sidecar.",
        f"4. `{rp}/inventory.json` and `{rp}/visual_quality.json` — "
        "helper-validated readbacks.",
        "",
        "## Re-validate on disk",
        "",
        "The read-only stdlib re-check that ran inside resume "
        f"(returned rc={validator_rc}) is safe to re-run any time; it "
        "does not mutate the package:",
        "",
        "```",
        f"{python_q} {validator_q} \\",
        f"    --out-dir {review_package_q}",
        "```",
        "",
        "## Boundary statement",
        "",
        "Local-only. Does NOT call D-One, MCP, Qoder, a public network, "
        "telemetry, a model API, an image search, or any external "
        "service. Real D-One image generation remains UNVERIFIED. NOT a "
        "prompt / report / Markdown-to-PPTX automation.",
        "",
        "## Cleaning up",
        "",
        "When done inspecting, remove the workflow output directly:",
        "",
        "```",
        f"rm -rf {out_dir_q}",
        "```",
        "",
    ])


# ---------------------------------------------------------------------------
# Self-test helpers + repo-snapshot guard.
# ---------------------------------------------------------------------------


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
    """Compare REPO_ROOT/examples + REPO_ROOT/scripts byte snapshots
    pre/post the self-test. Returns 0 when byte-identical, 1
    otherwise. Enforces the user-facing promise that --self-test does
    not write under REPO_ROOT."""
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


@dataclass
class _ProbeResult:
    name: str
    ok: bool
    detail: str = ""


def _selftest_write_custom_manifest(
    images_dir: Path, dest: Path, *, title: str,
) -> str | None:
    """Self-test only: write a VALID default manifest template for
    ``images_dir`` via the helper, then overwrite the first image's
    ``slide_title`` with ``title`` so the customisation is traceable
    through the produced plan + summary. Generating from the helper's
    own writer (rather than hand-building JSON) guarantees the rest of
    the manifest passes MAN1..MAN12 unchanged. Returns ``None`` on
    success or a short error string."""
    outcome = _run(
        "write-manifest-template (fixture)",
        [sys.executable, str(HELPER_PATH),
         "--images-dir", str(images_dir),
         "--write-manifest-template", str(dest)],
    )
    if outcome.rc != 0 or not dest.is_file():
        return (
            f"manifest template rc={outcome.rc}: "
            f"{(outcome.stderr or outcome.stdout)[-200:]!r}"
        )
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
        data["images"][0]["slide_title"] = title
        dest.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, KeyError, IndexError) as exc:
        return f"could not customise manifest: {type(exc).__name__}: {exc}"
    return None


def _selftest_write_custom_sidecar(
    images_dir: Path, dest: Path, *, intent: str,
) -> str | None:
    """Self-test only: write a VALID default generated-provenance sidecar
    template for ``images_dir`` via the helper, then overwrite the first
    entry's ``intent_summary`` with ``intent``. Returns ``None`` on
    success or a short error string."""
    outcome = _run(
        "write-generated-provenance-template (fixture)",
        [sys.executable, str(HELPER_PATH),
         "--images-dir", str(images_dir),
         "--write-generated-provenance-template", str(dest)],
    )
    if outcome.rc != 0 or not dest.is_file():
        return (
            f"sidecar template rc={outcome.rc}: "
            f"{(outcome.stderr or outcome.stdout)[-200:]!r}"
        )
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
        data["entries"][0]["intent_summary"] = intent
        dest.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, KeyError, IndexError) as exc:
        return f"could not customise sidecar: {type(exc).__name__}: {exc}"
    return None


# ---------------------------------------------------------------------------
# Self-test entrypoint. T1–T14 are detailed below; later probes (T15
# onward, including the --templates-only T27–T28 and --prepare-images-only
# T29–T35 groups) are documented at each probe's own inline comment, and
# the complete, current probe list + count live in the --self-test
# argument help. T1–T14:
#   T1 — full happy path from operator --images-dir to validated review
#        package + workflow README (including the locked README markers
#        for every stage + the validator rc + the "fail closed on
#        re-run" + "Re-running this workflow" caveat).
#   T2 — drift probe: after plan-out, mutating
#        generated_provenance.json must fail the approved-plan run
#        BEFORE any canonical review-package artifact (every entry in
#        _REVIEW_PACKAGE_FILES + _REVIEW_PACKAGE_DIRS) is produced.
#   T3 — copy-stage bounds: both the per-file byte cap
#        (MAX_BYTES_PER_FILE) AND the entry-count cap (MAX_IMAGES)
#        refuse oversized / over-count inputs BEFORE any byte is
#        copied into <out-dir>/bundle/images/.
#   T4 — README commands are shell-safe: drives the workflow under a
#        path containing whitespace + an apostrophe, then re-parses
#        the rendered Stage-4 command via shlex.split to prove every
#        path embedded in a fenced shell-command block survives
#        copy-paste as a single argv token.
#   T5 — copy-stage filesystem error returns a clean failure list: a
#        pre-existing bundle_images directory forces
#        bundle_images.mkdir(exist_ok=False) to raise FileExistsError,
#        and the OSError catch in _copy_images_into_bundle must
#        convert it into a tagged failure list rather than an
#        uncaught traceback.
#   T6 — non-image extension refused BEFORE any byte is copied: a
#        stray ``.txt`` file alongside valid PNG + JPEG inputs refuses
#        the run via the wrapper's IG5-parallel extension filter, so
#        a non-image file is never duplicated into
#        <out-dir>/bundle/images/.
#   T7 — race-safe copy refuses a symlink at open time:
#        ``_copy_one_image_race_safe`` opens the source with
#        ``O_NOFOLLOW`` so a TOCTOU swap into a symlink between the
#        pre-flight ``is_symlink`` check and the copy still fails
#        closed at open time. Locks in the Codex-flagged fix for the
#        symlink-refusal TOCTOU.
#   T8 — race-safe copy refuses a FIFO / device / socket via
#        ``stat.S_ISREG`` on the opened fd. ``O_NOFOLLOW`` only blocks
#        symlinks; without the regular-file check a FIFO at the
#        source path would open successfully and then block
#        ``copyfileobj`` waiting for a writer, and a character
#        device like ``/dev/zero`` would silently feed bytes into
#        the bundle. ``O_NONBLOCK`` is also load-bearing here so
#        the open of the FIFO does not block waiting for a writer.
#        Locks in the Codex-flagged regular-file + FIFO-hang gaps.
#   T9 — bounded copy refuses a source that produces more bytes
#        than ``MAX_BYTES_PER_FILE``. The earlier
#        ``shutil.copyfileobj`` call would drain every byte from
#        the source even after the fstat-at-open size check passed,
#        so a concurrent appender could silently push the bundle's
#        copy past the cap. ``_copy_bounded`` enforces the cap
#        inside the read loop. Locks in the Codex-flagged
#        size-cap bypass.
#   T10 — case-fold ancestor check refuses a case-variant
#         ``--out-dir`` that resolves under REPO_ROOT on a
#         case-insensitive filesystem (macOS APFS / Windows NTFS).
#         The helper's ``_validate_out_dir_arg`` compares raw
#         strings, which silently misses ``/USERS/.../szh-ppt-
#         master/leak`` even though the filesystem normalises that
#         to the same inode as REPO_ROOT/leak. Locks in the
#         Codex-flagged case-variant bypass.
#   T11 — relative ``--images-dir`` / ``--out-dir`` from a
#         non-REPO_ROOT cwd produce the review package at the
#         operator-intended path. The helper subprocesses run with
#         ``cwd=REPO_ROOT``; without main()'s ``Path.resolve``
#         call a relative ``--out-dir output`` would be interpreted
#         relative to REPO_ROOT by the helper. Locks in the
#         Codex-flagged relative-path bug.
#   T12 — cross-containment refusal between ``--images-dir`` and
#         ``--out-dir`` uses the case-fold ancestor check, so a
#         case-variant ``--out-dir /TMP/IMGS/output`` against
#         ``--images-dir /tmp/imgs`` is refused on case-insensitive
#         filesystems (parallel to T10's REPO_ROOT-ancestor gate).
#   T13 — a hidden ``.DS_Store`` dotfile (macOS Finder's invisible
#         metadata file — the most common real-world contaminant of
#         an operator image folder) is refused BEFORE any byte is
#         copied with an operator-facing macOS-aware message that
#         names the cause and offers a non-destructive ``ls -a``
#         reveal command, NOT the generic ``has extension ''`` line.
#   T14 — a torn run that fails AFTER the bundle is staged (a ``.png``
#         that passes the wrapper's cheap extension gate but fails the
#         helper's IG8 magic-byte signature check) leaves a partial
#         bundle under out_dir; main() must emit a recovery NOTE
#         naming out_dir + an ``rm -rf`` retry path so the operator is
#         not blindsided by the shared --out-dir gate's "non-empty"
#         refusal when they fix the input and re-run the same command
#         (the top-level README that documents the same recovery is
#         only written on a SUCCESSFUL run). Surfaced by a real local
#         pilot.
# Every probe runs under TemporaryDirectory; the repo snapshot
# enforces no writes under REPO_ROOT.
# ---------------------------------------------------------------------------


def _run_self_tests() -> int:
    print("=== operator_images_to_review_package --self-test ===")
    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    scripts_before = _snapshot_dir(REPO_ROOT / "scripts")

    results: list[_ProbeResult] = []

    # T1 happy path. Stage a synthetic --images-dir using the helper's
    # own _write_synthetic_images so the fixture matches the helper's
    # acceptance gates exactly.
    with tempfile.TemporaryDirectory(prefix="o2rp-T1-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        out_dir = td / "workflow_out"
        _write_synthetic_images(images_dir)
        rc = main(["--images-dir", str(images_dir),
                   "--out-dir", str(out_dir)])
        ok = rc == 0
        detail = ""
        if ok:
            review_package = out_dir / "review_package"
            for name in _REVIEW_PACKAGE_FILES:
                if (not (review_package / name).is_file()
                        or (review_package / name).is_symlink()):
                    ok = False
                    detail = (
                        f"missing review-package file: "
                        f"{review_package / name}"
                    )
                    break
            if ok:
                for name in _REVIEW_PACKAGE_DIRS:
                    if not (review_package / name).is_dir():
                        ok = False
                        detail = (
                            f"missing review-package dir: "
                            f"{review_package / name}"
                        )
                        break
            if ok and not (out_dir / "README.md").is_file():
                ok, detail = False, "missing workflow README.md"
            if ok and not (out_dir / "approved_plan.json").is_file():
                ok, detail = False, "missing approved_plan.json"
            if ok and not (out_dir / "bundle" / "manifest.json").is_file():
                ok, detail = False, "missing bundle/manifest.json"
            if ok and not (
                out_dir / "bundle" / "generated_provenance.json"
            ).is_file():
                ok, detail = False, "missing bundle/generated_provenance.json"
            if ok:
                try:
                    summary = json.loads(
                        (review_package / "summary.json").read_text(
                            encoding="utf-8",
                        )
                    )
                except (OSError, ValueError) as exc:
                    ok = False
                    detail = (
                        f"summary.json unparseable: "
                        f"{type(exc).__name__}: {exc}"
                    )
                else:
                    ap = summary.get("approved_plan")
                    if (not isinstance(ap, dict)
                            or ap.get("matched") is not True):
                        ok = False
                        detail = (
                            f"summary.approved_plan.matched is not "
                            f"True (approved_plan={ap!r})"
                        )
                    elif list(_EXPLICIT_BOUNDARIES) != summary.get(
                        "explicit_boundaries"
                    ):
                        ok = False
                        detail = (
                            f"summary.explicit_boundaries drifted from "
                            f"the locked helper tuple"
                        )
                    elif summary.get("real_d_one_status") != "UNVERIFIED":
                        ok = False
                        detail = (
                            f"summary.real_d_one_status != 'UNVERIFIED' "
                            f"(got {summary.get('real_d_one_status')!r})"
                        )
                    elif summary.get("generated_provenance") is None:
                        ok = False
                        detail = (
                            f"summary.generated_provenance is null — "
                            f"sidecar did not flow through to the "
                            f"approved-plan run"
                        )
            if ok:
                try:
                    readme_text = (out_dir / "README.md").read_text(
                        encoding="utf-8",
                    )
                except OSError as exc:
                    ok = False
                    detail = (
                        f"workflow README unreadable: "
                        f"{type(exc).__name__}: {exc}"
                    )
                else:
                    # The workflow README must carry the exact manual
                    # commands run AND record the validator rc. Locking
                    # those strings in place here surfaces a future
                    # regression that skips a stage or omits the
                    # validator wiring as a T1 FAIL rather than as
                    # silent drift.
                    required_markers = (
                        "--write-manifest-template",
                        "--write-generated-provenance-template",
                        "--plan-out",
                        "--approved-plan",
                        "rc=0",
                        # The "Steps 1-4 fail closed on re-run" caveat
                        # below was added after Codex flagged that the
                        # earlier "Copy any stage to re-run it" wording
                        # actively misled operators into running
                        # commands the helper refuses by design. Lock
                        # the corrected caveat in so a future README
                        # regression that drops it surfaces as a T1
                        # FAIL rather than as silent operator UX drift.
                        "fail closed on re-run",
                        "Re-running this workflow",
                        # The README must record the EXACT argv that
                        # subprocess.run saw — sys.executable +
                        # absolute HELPER_PATH / VALIDATOR_PATH, NOT a
                        # substituted `python3` + relative-path
                        # equivalent. Codex caught a prior version
                        # whose rendered commands silently diverged
                        # from the actual argv. ``shlex.quote`` of a
                        # path that contains no shell metacharacters
                        # returns the path unchanged, so a plain
                        # substring search is sufficient.
                        sys.executable,
                        str(HELPER_PATH),
                        str(VALIDATOR_PATH),
                        # The README must be HONEST about Stage 4
                        # auto-approving its own Stage-3 plan. Codex
                        # flagged the earlier wording for letting an
                        # operator believe the ``--approved-plan``
                        # gate represents human review. The
                        # ``AUTO-APPROVES`` marker on the Stage-4
                        # comment line and the ``Auto-approval``
                        # section header below name the limit
                        # explicitly; a future README regression that
                        # silently strips either surfaces here as a
                        # T1 FAIL rather than as silent operator-UX
                        # drift.
                        "AUTO-APPROVES",
                        "Auto-approval",
                        "not a substitute for human review",
                    )
                    for marker in required_markers:
                        if marker not in readme_text:
                            ok = False
                            detail = (
                                f"workflow README missing marker "
                                f"{marker!r}"
                            )
                            break
        else:
            detail = f"main(--images-dir, --out-dir) rc={rc}"
        results.append(_ProbeResult(
            name="T1 happy path", ok=ok, detail=detail,
        ))

    # T2 drift probe. Walks Stages A..D manually (so we can mutate the
    # sidecar AFTER plan-out is written), then runs the approved-plan
    # step and verifies it fails closed BEFORE producing any review-
    # package artifact.
    with tempfile.TemporaryDirectory(prefix="o2rp-T2-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        out_dir = td / "workflow_out"
        _write_synthetic_images(images_dir)
        out_dir.mkdir()
        bundle = out_dir / "bundle"
        bundle_images = bundle / "images"
        manifest = bundle / "manifest.json"
        gen_prov = bundle / "generated_provenance.json"
        approved_plan = out_dir / "approved_plan.json"
        review_package = out_dir / "review_package"

        ok, detail = True, ""
        copy_failures = _copy_images_into_bundle(images_dir, bundle_images)
        if copy_failures:
            ok, detail = False, f"setup copy failures: {copy_failures!r}"
        if ok:
            for stage_name, cmd in (
                ("write-manifest-template",
                 [sys.executable, str(HELPER_PATH),
                  "--images-dir", str(bundle_images),
                  "--write-manifest-template", str(manifest)]),
                ("write-generated-provenance-template",
                 [sys.executable, str(HELPER_PATH),
                  "--bundle", str(bundle),
                  "--write-generated-provenance-template", str(gen_prov)]),
                ("plan-out",
                 [sys.executable, str(HELPER_PATH),
                  "--bundle", str(bundle),
                  "--plan-out", str(approved_plan)]),
            ):
                outcome = _run(stage_name, cmd)
                if outcome.rc != 0:
                    ok = False
                    detail = (
                        f"setup stage {stage_name!r} rc={outcome.rc}: "
                        f"{(outcome.stderr or outcome.stdout)[-200:]!r}"
                    )
                    break
        if ok:
            # Mutate the sidecar so the bundle drifts from the approved
            # plan. The helper's approved-plan gate compares the
            # top-level generated_provenance block AND every per-row
            # intent_summary / placement_role / text_policy /
            # subject_domain / custom_descriptor field, so a single
            # intent_summary change is sufficient to trip the drift
            # gate.
            try:
                gp_data = json.loads(
                    gen_prov.read_text(encoding="utf-8"),
                )
            except (OSError, ValueError) as exc:
                ok, detail = False, (
                    f"could not parse generated_provenance template: "
                    f"{type(exc).__name__}: {exc}"
                )
            else:
                entries = gp_data.get("entries")
                if not isinstance(entries, list) or not entries:
                    ok, detail = False, (
                        f"generated_provenance template has no entries "
                        f"to mutate: {gp_data!r}"
                    )
                else:
                    entries[0]["intent_summary"] = (
                        "drifted-by-T2-must-fail-approved-plan-run"
                    )
                    gen_prov.write_text(
                        json.dumps(gp_data, indent=2, sort_keys=True)
                        + "\n",
                        encoding="utf-8",
                    )
        if ok:
            approved_outcome = _run(
                "approved-plan (drift expected to fail)",
                [
                    sys.executable, str(HELPER_PATH),
                    "--bundle", str(bundle),
                    "--approved-plan", str(approved_plan),
                    "--out-dir", str(review_package),
                ],
            )
            # The approved-plan gate must reject (rc != 0). The helper
            # documents that it refuses BEFORE any out-dir artifact is
            # created, so the FULL canonical review-package surface
            # (every file + every directory) must NOT exist on disk
            # after the failed run. The earlier wording checked only
            # ``deck.pptx`` / ``summary.json`` and would have
            # false-green'd a regression that materialised any other
            # artifact (workspace/, reports/, README.md, inventory
            # .json, visual_quality.json) before failing — Codex
            # caught this gap.
            leaked: list[str] = []
            for name in _REVIEW_PACKAGE_FILES:
                if (review_package / name).exists():
                    leaked.append(name)
            for name in _REVIEW_PACKAGE_DIRS:
                if (review_package / name).exists():
                    leaked.append(name + "/")
            if approved_outcome.rc == 0:
                ok, detail = False, (
                    f"drift was NOT rejected: approved_outcome.rc=0 "
                    f"(leaked review-package entries: {leaked!r})"
                )
            elif leaked:
                ok, detail = False, (
                    f"drift was rejected (rc={approved_outcome.rc}) "
                    f"but review-package artifacts were materialised "
                    f"anyway: {leaked!r}"
                )
        results.append(_ProbeResult(
            name="T2 drift probe (mutated gen_prov after plan-out)",
            ok=ok, detail=detail,
        ))

    # T3 copy-stage bounds. The wrapper must refuse oversized inputs
    # (per-file byte cap + entry-count cap) BEFORE any byte is copied
    # into ``<out-dir>/bundle/images/``. Two assertions:
    #   * a single 1-byte-over-cap file refuses the run and leaves
    #     the destination ``bundle_images`` directory uncreated;
    #   * ``MAX_IMAGES + 1`` entries refuses the run before the
    #     per-entry walk even fires.
    # Without these caps a multi-GB file or a folder of thousands of
    # entries would be duplicated into the operator's --out-dir
    # before the underlying helper gates could refuse them.
    with tempfile.TemporaryDirectory(prefix="o2rp-T3-") as raw_td:
        td = Path(raw_td)
        # Oversize-file branch.
        oversize_dir = td / "oversize_images"
        oversize_dir.mkdir()
        oversize_file = oversize_dir / "alpha.png"
        oversize_file.write_bytes(b"x" * (MAX_BYTES_PER_FILE + 1))
        oversize_bundle_images = td / "oversize_bundle_images"
        oversize_failures = _copy_images_into_bundle(
            oversize_dir, oversize_bundle_images,
        )
        oversize_ok = (
            len(oversize_failures) == 1
            and str(MAX_BYTES_PER_FILE) in oversize_failures[0]
            and not oversize_bundle_images.exists()
        )

        # Too-many-entries branch.
        crowded_dir = td / "crowded_images"
        crowded_dir.mkdir()
        for idx in range(MAX_IMAGES + 1):
            (crowded_dir / f"entry_{idx:02d}.png").write_bytes(b"\x89PNG\r\n")
        crowded_bundle_images = td / "crowded_bundle_images"
        crowded_failures = _copy_images_into_bundle(
            crowded_dir, crowded_bundle_images,
        )
        crowded_ok = (
            len(crowded_failures) == 1
            and f"{MAX_IMAGES + 1}" in crowded_failures[0]
            and not crowded_bundle_images.exists()
        )

        ok = oversize_ok and crowded_ok
        detail = "" if ok else (
            f"oversize_failures={oversize_failures!r}; "
            f"oversize_bundle_exists={oversize_bundle_images.exists()}; "
            f"crowded_failures={crowded_failures!r}; "
            f"crowded_bundle_exists={crowded_bundle_images.exists()}"
        )
        results.append(_ProbeResult(
            name=(
                "T3 copy-stage caps refuse oversized / over-count "
                "inputs before any byte is copied"
            ),
            ok=ok, detail=detail,
        ))

    # T4 shell-safe README quoting. Every path embedded in the
    # README's fenced shell-command blocks goes through
    # ``shlex.quote``, so an operator whose ``--images-dir`` /
    # ``--out-dir`` contains whitespace or shell metacharacters can
    # still copy-paste any rendered command and have the shell parse
    # it as a single argument. Drives the full workflow under an
    # ``--out-dir`` whose parent name carries a space, then verifies
    # each line in the fenced ``# 4. Approved-plan run lock`` block
    # parses back into its expected argv via ``shlex.split``.
    # Locks in the Codex-caught quoting fix.
    with tempfile.TemporaryDirectory(prefix="o2rp-T4-") as raw_td:
        td = Path(raw_td)
        # Per-run parent whose name carries a space + apostrophe — both
        # break a raw f-string command but are fine after
        # ``shlex.quote``.
        parent = td / "with space 'quote'"
        parent.mkdir()
        images_dir = parent / "operator images"
        _write_synthetic_images(images_dir)
        out_dir = parent / "fresh out"
        rc = main(["--images-dir", str(images_dir),
                   "--out-dir", str(out_dir)])
        ok = rc == 0
        detail = ""
        if not ok:
            detail = f"main(...) rc={rc} on quoted-path fixture"
        else:
            try:
                readme_text = (out_dir / "README.md").read_text(
                    encoding="utf-8",
                )
            except OSError as exc:
                ok, detail = False, (
                    f"README unreadable on quoted-path fixture: "
                    f"{type(exc).__name__}: {exc}"
                )
            else:
                # Locate the Stage-4 fenced command and re-parse it.
                # The block MUST be sliced so it ends at the next
                # `# 5.` comment line (or the closing ```), otherwise
                # Stage 5's `--out-dir <review_package>` is
                # concatenated into the parse and the per-path
                # membership check below would false-green a broken
                # Stage 4 just because the same path also appears in
                # Stage 5. Codex caught this gap.
                stage4_marker = "# 4. Approved-plan run lock"
                stage5_marker = "# 5. Read-only stdlib re-check"
                lines = readme_text.splitlines()
                start = None
                for i, line in enumerate(lines):
                    if stage4_marker in line:
                        start = i + 1
                        break
                if start is None:
                    ok, detail = False, (
                        f"README missing Stage-4 marker "
                        f"{stage4_marker!r}"
                    )
                else:
                    end = start
                    while end < len(lines):
                        stripped = lines[end].lstrip()
                        if (stage5_marker in lines[end]
                                or stripped.startswith("```")):
                            break
                        end += 1
                    raw_lines = [
                        line.rstrip(" \\")
                        for line in lines[start:end]
                        if line.strip()
                        and not line.lstrip().startswith("#")
                    ]
                    joined = " ".join(raw_lines)
                    try:
                        argv = shlex.split(joined)
                    except ValueError as exc:
                        ok, detail = False, (
                            f"shlex.split of Stage-4 command raised "
                            f"{type(exc).__name__}: {exc}; the "
                            f"rendered command is not shell-safe"
                        )
                    else:
                        # Rigorous structural check, not just
                        # "the paths appear somewhere". The Stage-4
                        # argv MUST be exactly:
                        #   python3
                        #   scripts/operator_local_images_to_editable_ppt.py
                        #   --bundle <bundle>
                        #   --approved-plan <approved_plan>
                        #   --out-dir <review_package>
                        # so any quoting drift that injects extra
                        # tokens (an unescaped space splitting one
                        # path into two), drops tokens, or rewrites
                        # the flag order surfaces here. Asserting
                        # the exact 8-element list catches the
                        # Codex-flagged false-green where Stage 5
                        # bytes leaked into the parse.
                        # main() now resolves --out-dir to an
                        # absolute path before any subprocess call
                        # (so a relative --out-dir from the caller's
                        # cwd reaches the helper as absolute), and on
                        # macOS that resolution also follows the
                        # ``/tmp`` -> ``/private/tmp`` symlink. The
                        # expected argv must mirror that resolution
                        # — without it, ``/tmp/foo`` and the actual
                        # ``/private/tmp/foo`` argv element would
                        # diverge as raw strings even though they
                        # name the same inode.
                        resolved_out_dir = out_dir.resolve(strict=False)
                        expected_argv = [
                            sys.executable,
                            str(HELPER_PATH),
                            "--bundle", str(resolved_out_dir / "bundle"),
                            "--approved-plan",
                            str(resolved_out_dir
                                / "approved_plan.json"),
                            "--out-dir",
                            str(resolved_out_dir / "review_package"),
                        ]
                        if argv != expected_argv:
                            ok, detail = False, (
                                f"Stage-4 argv did not round-trip "
                                f"to the expected 8-element list; "
                                f"expected={expected_argv!r}; "
                                f"got={argv!r}"
                            )
        results.append(_ProbeResult(
            name=(
                "T4 README commands are shell-safe for paths with "
                "spaces / quotes"
            ),
            ok=ok, detail=detail,
        ))

    # T5 copy-stage robustness. A pre-existing ``bundle_images``
    # directory forces ``bundle_images.mkdir(exist_ok=False)`` to raise
    # FileExistsError; without the OSError catch in
    # ``_copy_images_into_bundle``, the workflow would crash with an
    # uncaught traceback instead of returning a clean failure list.
    # Locks in the fix for the copy-stage robustness path.
    with tempfile.TemporaryDirectory(prefix="o2rp-T5-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        _write_synthetic_images(images_dir)
        preexisting_bundle_images = td / "preexisting_bundle_images"
        preexisting_bundle_images.mkdir()
        try:
            failures = _copy_images_into_bundle(
                images_dir, preexisting_bundle_images,
            )
        except OSError as exc:
            ok = False
            detail = (
                f"_copy_images_into_bundle raised "
                f"{type(exc).__name__}: {exc} instead of returning a "
                f"clean failure list"
            )
        else:
            ok = (
                len(failures) == 1
                and "FileExistsError" in failures[0]
            )
            detail = "" if ok else f"failures={failures!r}"
        results.append(_ProbeResult(
            name="T5 copy-stage filesystem error returns clean failure",
            ok=ok, detail=detail,
        ))

    # T6 non-image extension refused BEFORE any byte is copied. A
    # stray ``.txt`` next to two valid images would otherwise be
    # duplicated into ``<out-dir>/bundle/images/`` and only refused
    # one stage later by the helper's IG5 gate — Codex caught this
    # gap. The wrapper now mirrors IG5 (closed extension set
    # ``{png, jpg, jpeg}``) so the bad file is named in the failure
    # list and the destination ``bundle_images`` directory is never
    # created.
    with tempfile.TemporaryDirectory(prefix="o2rp-T6-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        _write_synthetic_images(images_dir)
        # Plant a non-image file alongside the valid PNG + JPEG.
        bad = images_dir / "notes.txt"
        bad.write_bytes(b"this is not an image\n")
        bundle_images = td / "bundle_images"
        try:
            failures = _copy_images_into_bundle(images_dir, bundle_images)
        except OSError as exc:
            ok, detail = False, (
                f"_copy_images_into_bundle raised "
                f"{type(exc).__name__}: {exc} instead of returning a "
                f"clean failure list"
            )
        else:
            ok = (
                len(failures) == 1
                and "notes.txt" in failures[0]
                and "'.txt'" in failures[0]
                and not bundle_images.exists()
            )
            detail = "" if ok else (
                f"failures={failures!r}; "
                f"bundle_images_exists={bundle_images.exists()}"
            )
        results.append(_ProbeResult(
            name=(
                "T6 non-image extension refused before any byte is "
                "copied"
            ),
            ok=ok, detail=detail,
        ))

    # T7 race-safe copy refuses a symlink at open time. Exercises the
    # ``O_NOFOLLOW`` path in ``_copy_one_image_race_safe`` directly
    # (bypassing the cheaper pre-flight ``is_symlink`` check in
    # ``_copy_images_into_bundle``) so a future regression that
    # drops the O_NOFOLLOW flag — leaving the symlink-refusal
    # guarantee purely in the racy pre-flight — surfaces as a T7
    # FAIL. Codex caught that the earlier copyfile-based path was
    # still TOCTOU-vulnerable.
    with tempfile.TemporaryDirectory(prefix="o2rp-T7-") as raw_td:
        td = Path(raw_td)
        real_target = td / "real_target.png"
        real_target.write_bytes(b"\x89PNG\r\n\x1a\n")
        symlink_src = td / "symlink_src.png"
        symlink_src.symlink_to(real_target)
        dest = td / "race_dest.png"
        err = _copy_one_image_race_safe(
            symlink_src, dest, MAX_BYTES_PER_FILE,
        )
        ok = (
            err is not None
            and "O_NOFOLLOW" in err
            and not dest.exists()
        )
        detail = "" if ok else (
            f"err={err!r}; dest_exists={dest.exists()}"
        )
        results.append(_ProbeResult(
            name=(
                "T7 race-safe copy refuses symlink via O_NOFOLLOW "
                "(TOCTOU defense)"
            ),
            ok=ok, detail=detail,
        ))

    # T8 race-safe copy refuses a FIFO at the source path. ``O_NOFOLLOW``
    # only blocks symlinks; a FIFO / device file / socket would open
    # successfully and then ``copyfileobj`` would block on the FIFO
    # waiting for a writer (or read garbage from a device). The
    # ``stat.S_ISREG`` check on the opened fd refuses every
    # non-regular file. Locks in the Codex-flagged regular-file
    # TOCTOU gap. ``os.mkfifo`` is POSIX-only; on platforms that
    # don't support it the probe self-reports as skipped rather than
    # asserting a behavior the platform cannot exercise.
    with tempfile.TemporaryDirectory(prefix="o2rp-T8-") as raw_td:
        td = Path(raw_td)
        fifo_src = td / "as_fifo.png"
        try:
            os.mkfifo(fifo_src)
        except (OSError, AttributeError) as exc:
            results.append(_ProbeResult(
                name=(
                    "T8 race-safe copy refuses FIFO via fstat S_ISREG "
                    "(TOCTOU defense beyond symlinks)"
                ),
                ok=True,
                detail=(
                    f"skipped: os.mkfifo unsupported on this platform "
                    f"({type(exc).__name__}: {exc})"
                ),
            ))
        else:
            dest = td / "fifo_dest.png"
            err = _copy_one_image_race_safe(
                fifo_src, dest, MAX_BYTES_PER_FILE,
            )
            ok = (
                err is not None
                and "not a regular file" in err
                and not dest.exists()
            )
            detail = "" if ok else (
                f"err={err!r}; dest_exists={dest.exists()}"
            )
            results.append(_ProbeResult(
                name=(
                    "T8 race-safe copy refuses FIFO via fstat S_ISREG "
                    "(TOCTOU defense beyond symlinks)"
                ),
                ok=ok, detail=detail,
            ))

    # T9 bounded copy refuses a source that produces more bytes than
    # the cap, even when the fstat-at-open check could not have seen
    # it (the Codex-flagged scenario: a concurrent appender pushes
    # the source past the cap between the fstat and the read loop).
    # The probe drives ``_copy_bounded`` against a BytesIO source
    # that bypasses the fstat path entirely, so the cap-check inside
    # the read loop is the only thing standing between the source
    # and the destination. Verifies both the cap-exactly-met success
    # case and the cap-exceeded refusal case.
    happy_src = io.BytesIO(b"x" * 100)
    happy_dst = io.BytesIO()
    happy_err = _copy_bounded(happy_src, happy_dst, max_bytes=100)
    happy_ok = (
        happy_err is None and happy_dst.getvalue() == b"x" * 100
    )

    over_src = io.BytesIO(b"x" * 101)
    over_dst = io.BytesIO()
    over_err = _copy_bounded(over_src, over_dst, max_bytes=100)
    over_ok = (
        over_err is not None
        and "more than 100 bytes" in over_err
        # Partial writes up to (but not exceeding) the cap are
        # tolerated; we only assert the call returned a failure
        # reason before the source's full payload reached the dest.
        and len(over_dst.getvalue()) <= 100
    )

    ok = happy_ok and over_ok
    detail = "" if ok else (
        f"happy_err={happy_err!r}; "
        f"happy_dst_len={len(happy_dst.getvalue())}; "
        f"over_err={over_err!r}; "
        f"over_dst_len={len(over_dst.getvalue())}"
    )
    results.append(_ProbeResult(
        name=(
            "T9 bounded copy refuses source that grows past cap "
            "during the read loop"
        ),
        ok=ok, detail=detail,
    ))

    # T10 case-fold ancestor helper directly returns True for paths
    # that resolve at-or-under REPO_ROOT after case-folding, False
    # for paths outside it. Unit-tests ``_resolves_under_casefold``
    # itself so the probe exercises the case-fold logic regardless
    # of the host filesystem's case sensitivity — without this,
    # an integration probe that drove ``main`` would false-green
    # on case-sensitive Linux (the helper's parent-exists check
    # fires before the case-fold gate ever runs and the probe could
    # not tell which gate caught the bypass). Codex caught the
    # earlier integration-only probe's false-green path.
    repo_root_lower = REPO_ROOT.parent / REPO_ROOT.name.lower()
    repo_root_upper = REPO_ROOT.parent / REPO_ROOT.name.upper()
    cases = [
        # (path, expected, label)
        (REPO_ROOT, True, "exact REPO_ROOT"),
        (REPO_ROOT / "leak_dir", True, "child under REPO_ROOT"),
        (repo_root_lower / "leak_dir",
         True, "lowercased leaf + child"),
        (repo_root_upper / "leak_dir",
         True, "uppercased leaf + child"),
        (REPO_ROOT.parent, False,
         "parent of REPO_ROOT (sibling, not descendant)"),
        (REPO_ROOT.parent / f"{REPO_ROOT.name}_sibling",
         False, "name-prefixed sibling (must NOT match)"),
        (Path("/tmp/unrelated_leak"), False,
         "completely unrelated path"),
    ]
    failures: list[str] = []
    for path, expected, label in cases:
        actual = _resolves_under_casefold(path, REPO_ROOT)
        if actual is not expected:
            failures.append(
                f"{label!r}: expected {expected}, got {actual} "
                f"(path={path})"
            )
    ok = not failures
    detail = "" if ok else f"failures={failures!r}"
    results.append(_ProbeResult(
        name=(
            "T10 _resolves_under_casefold returns the expected truth "
            "value for every documented case-variant scenario"
        ),
        ok=ok, detail=detail,
    ))

    # T11 relative --images-dir / --out-dir args work end-to-end
    # when the caller's cwd is NOT REPO_ROOT. The helper subprocesses
    # run with ``cwd=REPO_ROOT``; without the main()-level path
    # resolution Codex flagged, a relative ``--out-dir output`` from
    # the operator's shell would be interpreted relative to
    # REPO_ROOT by the helper (silently writing somewhere unrelated
    # to where the operator intended) or fail to find the operator's
    # ``--images-dir``. This probe drives ``main`` from a per-run
    # tempdir as cwd (so the relative args are unambiguous on disk),
    # then asserts every canonical review-package artifact landed
    # under the resolved ``out_dir`` (NOT under REPO_ROOT).
    with tempfile.TemporaryDirectory(prefix="o2rp-T11-") as raw_td:
        td = Path(raw_td)
        # Synthesize a fixture inside the tempdir.
        images_dir_abs = td / "operator_images"
        _write_synthetic_images(images_dir_abs)
        out_dir_abs = td / "workflow_out"
        original_cwd = Path.cwd()
        try:
            os.chdir(td)
            rc = main([
                "--images-dir", "operator_images",
                "--out-dir", "workflow_out",
            ])
        finally:
            try:
                os.chdir(original_cwd)
            except OSError:
                pass
        review_package = out_dir_abs / "review_package"
        deck = review_package / "deck.pptx"
        # The leak check is critical: a regression that re-introduces
        # the relative-path bug would either (a) land the review
        # package under REPO_ROOT/workflow_out (the helper's cwd) or
        # (b) fail outright. Both cases surface here.
        leaked = (REPO_ROOT / "workflow_out").exists()
        ok = (
            rc == 0
            and deck.is_file()
            and not deck.is_symlink()
            and not leaked
        )
        detail = "" if ok else (
            f"rc={rc}; deck_exists={deck.exists()}; "
            f"workflow_out_inside_REPO_ROOT_exists={leaked}"
        )
        # Defensive cleanup: if a regression DID leak the directory
        # into REPO_ROOT (so the repo-snapshot check below also
        # fires), remove the leak so a developer running --self-test
        # locally doesn't have to clean up by hand.
        if leaked:
            try:
                shutil.rmtree(REPO_ROOT / "workflow_out")
            except OSError:
                pass
    results.append(_ProbeResult(
        name=(
            "T11 relative --images-dir / --out-dir from non-REPO_ROOT "
            "cwd produce the review package at the resolved path"
        ),
        ok=ok, detail=detail,
    ))

    # T12 cross-containment refusal uses the case-fold ancestor
    # check, parallel to T10. Without the case-fold gate, an
    # ``--out-dir`` that case-variant-matches a path under
    # ``--images-dir`` would slip past the raw-string ``relative_to``
    # check on a case-insensitive filesystem and the workflow would
    # either copy bytes onto themselves or pollute the operator's
    # source folder. Directly drives the case-fold check via
    # ``_resolves_under_casefold`` so the probe is platform-
    # independent (mirrors T10's structural unit-test pattern).
    # Codex caught this parallel gap.
    cross_cases = [
        # (a, b, expected, label)
        (Path("/tmp/IMGS"), Path("/tmp/imgs/sub"),
         False, "case-variant siblings (NOT a descendant — "
                "case-fold compares the WHOLE path, not just leaves)"),
        (Path("/tmp/imgs/SUB"), Path("/tmp/imgs"),
         True, "case-variant child IS under parent after case-fold"),
        (Path("/tmp/imgs"), Path("/tmp/IMGS/sub"),
         False, "case-variant parent is NOT under child"),
        (Path("/TMP/IMGS"), Path("/tmp/imgs"),
         True, "case-variant root equality (fully case-folded)"),
    ]
    failures = []
    for a, b, expected, label in cross_cases:
        actual = _resolves_under_casefold(a, b)
        if actual is not expected:
            failures.append(
                f"{label!r}: _resolves_under_casefold({a}, {b}) "
                f"= {actual}, expected {expected}"
            )
    ok = not failures
    detail = "" if ok else f"failures={failures!r}"
    results.append(_ProbeResult(
        name=(
            "T12 cross-containment uses case-fold ancestor check "
            "(parallel to T10's --out-dir-under-REPO_ROOT gate)"
        ),
        ok=ok, detail=detail,
    ))

    # T13 hidden-dotfile refusal carries the operator-facing
    # macOS-aware message, not the generic "has extension ''" line. A
    # ``.DS_Store`` dropped into the folder by Finder is the single
    # most common real-world contaminant; the pilot hit it, so the
    # branch is pinned here. Mirrors T6's direct
    # ``_copy_images_into_bundle`` call: the bad file is named, the
    # hidden-file wording is present, and ``bundle_images`` is never
    # created.
    with tempfile.TemporaryDirectory(prefix="o2rp-T13-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        _write_synthetic_images(images_dir)
        # Plant the canonical macOS Finder metadata file alongside the
        # valid PNG + JPEG.
        (images_dir / ".DS_Store").write_bytes(b"\x00\x00\x00\x01")
        bundle_images = td / "bundle_images"
        try:
            failures = _copy_images_into_bundle(images_dir, bundle_images)
        except OSError as exc:
            ok, detail = False, (
                f"_copy_images_into_bundle raised "
                f"{type(exc).__name__}: {exc} instead of returning a "
                f"clean failure list"
            )
        else:
            ok = (
                len(failures) == 1
                and ".DS_Store" in failures[0]
                and "hidden file" in failures[0]
                and "ls -a" in failures[0]
                and "has extension ''" not in failures[0]
                and not bundle_images.exists()
            )
            detail = "" if ok else (
                f"failures={failures!r}; "
                f"bundle_images_exists={bundle_images.exists()}"
            )
        results.append(_ProbeResult(
            name=(
                "T13 hidden .DS_Store refused with operator-facing "
                "macOS-aware message before any byte is copied"
            ),
            ok=ok, detail=detail,
        ))

    # T14 torn-run recovery hint. A .png that passes the wrapper's
    # cheap extension gate but FAILS the helper's IG8 magic-byte
    # signature check fails AFTER the bundle is staged, leaving a
    # partial bundle under out_dir. The pilot hit the follow-on
    # confusion: the operator fixes the flagged image and re-runs the
    # SAME command, only to be refused by the shared --out-dir gate's
    # "non-empty" message (the partial bundle is this failed run's own
    # output, not something the operator placed). main() must emit a
    # recovery NOTE naming out_dir + an `rm -rf` retry path so a torn
    # run is not a dead end — the top-level README that documents the
    # same recovery is only written on a SUCCESSFUL run. Captures
    # stdout to assert the NOTE, and compares against the RESOLVED
    # out_dir (main resolves the arg, and on macOS the tempdir
    # resolves through /var -> /private/var) so the substring check
    # does not false-fail on the symlink-expanded path.
    with tempfile.TemporaryDirectory(prefix="o2rp-T14-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        _write_synthetic_images(images_dir)
        # One .png-named non-PNG: passes the wrapper's extension /
        # size / regular-file gates, fails the helper's IG8 signature
        # gate one stage later — exactly the "fails after staging"
        # shape that leaves a partial bundle behind.
        (images_dir / "actually_text.png").write_bytes(
            b"this file has a .png name but is not a PNG\n"
        )
        out_dir = td / "workflow_out"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--images-dir", str(images_dir),
                       "--out-dir", str(out_dir)])
        captured = buf.getvalue()
        resolved_out = out_dir.resolve(strict=False)
        try:
            torn = any(out_dir.iterdir())
        except OSError:
            torn = False
        ok = (
            rc == 1
            and torn
            and "left partial output" in captured
            and "rm -rf" in captured
            and "fresh --out-dir" in captured
            and str(resolved_out) in captured
        )
        detail = "" if ok else (
            f"rc={rc}; torn={torn}; "
            f"note_present={'left partial output' in captured}; "
            f"captured_tail={captured[-300:]!r}"
        )
        results.append(_ProbeResult(
            name=(
                "T14 torn post-copy run emits recovery hint naming "
                "out_dir + rm -rf retry path"
            ),
            ok=ok, detail=detail,
        ))

    # ----------------------------------------------------------------
    # Two-step reviewed flow (--plan then --resume). T15..T20 pin the
    # human-review checkpoint: plan stages a reviewable plan and builds
    # nothing; resume builds the same review package as one-command
    # mode for a valid reviewed plan but fails closed on mutated source
    # bytes, missing / mismatched generated provenance, path traversal,
    # and symlink inputs.
    # ----------------------------------------------------------------

    # T15 — plan mode stages the bundle + manifest + generated-
    # provenance templates + reviewable approved_plan.json + a top-level
    # README, but STOPS before building anything: no review_package/ and
    # no *.pptx anywhere under out_dir.
    with tempfile.TemporaryDirectory(prefix="o2rp-T15-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        out_dir = td / "workflow_out"
        _write_synthetic_images(images_dir)
        rc = main(["--plan",
                   "--images-dir", str(images_dir),
                   "--out-dir", str(out_dir)])
        ok = rc == 0
        detail = "" if ok else f"main(--plan ...) rc={rc}"
        if ok:
            for want in ("bundle/images", "bundle/manifest.json",
                         "bundle/generated_provenance.json",
                         "approved_plan.json", "README.md"):
                if not (out_dir / want).exists():
                    ok, detail = False, f"plan mode missing {want}"
                    break
        if ok:
            rp = out_dir / "review_package"
            if rp.exists():
                ok, detail = False, (
                    f"plan mode produced review_package: {rp} (it must "
                    f"stop before the build)"
                )
        if ok:
            decks = sorted(str(p) for p in out_dir.rglob("*.pptx"))
            if decks:
                ok, detail = False, (
                    f"plan mode produced PPTX output: {decks!r} (it must "
                    f"stop before the build)"
                )
        if ok:
            try:
                readme_text = (out_dir / "README.md").read_text(
                    encoding="utf-8",
                )
            except OSError as exc:
                ok, detail = False, (
                    f"plan README unreadable: {type(exc).__name__}: {exc}"
                )
            else:
                # The plan README must point the operator at the resume
                # command so the checkpoint is actionable, AND must tell
                # reviewers the staged files are read-only (editing them
                # makes resume fail closed). The "do NOT edit" marker
                # pins the fix for the Codex-caught contradiction where
                # an earlier draft invited reviewers to hand-edit
                # bundle/manifest.json + bundle/generated_provenance.json
                # "before resuming" — edits resume actually rejects.
                for marker in ("--resume", "review me", "do NOT edit"):
                    if marker not in readme_text:
                        ok, detail = False, (
                            f"plan README missing marker {marker!r}"
                        )
                        break
        results.append(_ProbeResult(
            name=(
                "T15 plan mode stages the reviewable plan and emits no "
                "PPTX / review_package"
            ),
            ok=ok, detail=detail,
        ))

    # T16 — resume mode builds the review package from a valid reviewed
    # plan, with the SAME canonical artifacts + approved-plan evidence
    # one-command mode produces.
    with tempfile.TemporaryDirectory(prefix="o2rp-T16-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        out_dir = td / "workflow_out"
        _write_synthetic_images(images_dir)
        plan_rc = main(["--plan",
                        "--images-dir", str(images_dir),
                        "--out-dir", str(out_dir)])
        rc = (main(["--resume", "--out-dir", str(out_dir)])
              if plan_rc == 0 else 99)
        ok = plan_rc == 0 and rc == 0
        detail = "" if ok else f"plan_rc={plan_rc}; resume_rc={rc}"
        if ok:
            review_package = out_dir / "review_package"
            for name in _REVIEW_PACKAGE_FILES:
                if (not (review_package / name).is_file()
                        or (review_package / name).is_symlink()):
                    ok, detail = False, (
                        f"missing review-package file: "
                        f"{review_package / name}"
                    )
                    break
            if ok:
                for name in _REVIEW_PACKAGE_DIRS:
                    if not (review_package / name).is_dir():
                        ok, detail = False, (
                            f"missing review-package dir: "
                            f"{review_package / name}"
                        )
                        break
            if ok:
                try:
                    summary = json.loads(
                        (review_package / "summary.json").read_text(
                            encoding="utf-8",
                        )
                    )
                except (OSError, ValueError) as exc:
                    ok, detail = False, (
                        f"summary.json unparseable: "
                        f"{type(exc).__name__}: {exc}"
                    )
                else:
                    ap = summary.get("approved_plan")
                    if (not isinstance(ap, dict)
                            or ap.get("matched") is not True):
                        ok, detail = False, (
                            f"summary.approved_plan.matched is not True "
                            f"(approved_plan={ap!r})"
                        )
            if ok:
                try:
                    readme_text = (out_dir / "README.md").read_text(
                        encoding="utf-8",
                    )
                except OSError as exc:
                    ok, detail = False, (
                        f"resume README unreadable: "
                        f"{type(exc).__name__}: {exc}"
                    )
                else:
                    # The resume README must record that a human review
                    # checkpoint preceded the build.
                    if "resumed" not in readme_text:
                        ok, detail = False, (
                            "resume README missing 'resumed' marker"
                        )
        results.append(_ProbeResult(
            name=(
                "T16 resume mode builds the review package from a valid "
                "reviewed plan"
            ),
            ok=ok, detail=detail,
        ))

    # T17 — resume refuses MUTATED SOURCE BYTES. Editing a bundle image
    # after plan-out (PNG signature intact so the helper's IG8 gate
    # still passes, but the sha256 changes) makes the rebuilt plan
    # differ from approved_plan.json, so the helper's approved-plan run
    # lock fails closed BEFORE any review-package artifact is created.
    with tempfile.TemporaryDirectory(prefix="o2rp-T17-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        out_dir = td / "workflow_out"
        _write_synthetic_images(images_dir)
        plan_rc = main(["--plan",
                        "--images-dir", str(images_dir),
                        "--out-dir", str(out_dir)])
        ok, detail = True, ""
        if plan_rc != 0:
            ok, detail = False, f"plan setup rc={plan_rc}"
        else:
            pngs = sorted(
                (out_dir / "bundle" / "images").glob("*.png")
            )
            if not pngs:
                ok, detail = False, "no staged .png to mutate"
            else:
                # Append a byte: PNG magic-byte prefix is unchanged so
                # IG8 still passes; the sha256 drifts from the plan.
                pngs[0].write_bytes(pngs[0].read_bytes() + b"\x00")
        if ok:
            rc = main(["--resume", "--out-dir", str(out_dir)])
            rp = out_dir / "review_package"
            if rc == 0:
                ok, detail = False, (
                    f"resume did NOT refuse mutated source bytes "
                    f"(rc=0); review_package_exists={rp.exists()}"
                )
            elif rp.exists():
                ok, detail = False, (
                    f"resume refused (rc={rc}) but review_package was "
                    f"materialised anyway: {rp}"
                )
        results.append(_ProbeResult(
            name="T17 resume refuses mutated source bytes",
            ok=ok, detail=detail,
        ))

    # T18 — resume refuses MISSING / MISMATCHED generated provenance.
    # Both perturbations drift the rebuilt plan from approved_plan.json,
    # so the approved-plan run lock fails closed with no review package.
    with tempfile.TemporaryDirectory(prefix="o2rp-T18-") as raw_td:
        td = Path(raw_td)
        ok, detail = True, ""
        for label, perturb in (
            ("missing", "delete"),
            ("mismatched", "edit"),
        ):
            case_td = td / label
            case_td.mkdir()
            images_dir = case_td / "operator_images"
            out_dir = case_td / "workflow_out"
            _write_synthetic_images(images_dir)
            plan_rc = main(["--plan",
                            "--images-dir", str(images_dir),
                            "--out-dir", str(out_dir)])
            if plan_rc != 0:
                ok, detail = False, f"{label}: plan setup rc={plan_rc}"
                break
            gp = out_dir / "bundle" / "generated_provenance.json"
            if perturb == "delete":
                gp.unlink()
            else:
                try:
                    data = json.loads(gp.read_text(encoding="utf-8"))
                    data["entries"][0]["intent_summary"] = (
                        "drifted-by-T18-must-fail-resume"
                    )
                    gp.write_text(
                        json.dumps(data, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                except (OSError, ValueError, KeyError, IndexError) as exc:
                    ok, detail = False, (
                        f"{label}: could not perturb sidecar: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    break
            rc = main(["--resume", "--out-dir", str(out_dir)])
            rp = out_dir / "review_package"
            if rc == 0:
                ok, detail = False, (
                    f"{label}: resume did NOT refuse (rc=0); "
                    f"review_package_exists={rp.exists()}"
                )
                break
            if rp.exists():
                ok, detail = False, (
                    f"{label}: resume refused (rc={rc}) but "
                    f"review_package was materialised anyway: {rp}"
                )
                break
        results.append(_ProbeResult(
            name=(
                "T18 resume refuses missing / mismatched generated "
                "provenance"
            ),
            ok=ok, detail=detail,
        ))

    # T19 — resume refuses PATH TRAVERSAL --out-dir (URI-shaped and a
    # path that anchors under REPO_ROOT) at the gate, returning rc 2
    # with no filesystem mutation.
    repo_anchored = REPO_ROOT / "o2rp_T19_leak_nonexistent"
    ok, detail = True, ""
    uri_rc = main(["--resume", "--out-dir", "file:///tmp/o2rp-T19"])
    if uri_rc != 2:
        ok, detail = False, f"URI-shaped --out-dir rc={uri_rc} (expected 2)"
    if ok:
        anchored_rc = main(["--resume", "--out-dir", str(repo_anchored)])
        if anchored_rc != 2:
            ok, detail = False, (
                f"repo-anchored --out-dir rc={anchored_rc} (expected 2)"
            )
        elif repo_anchored.exists():
            ok, detail = False, (
                f"repo-anchored --out-dir was created under REPO_ROOT: "
                f"{repo_anchored}"
            )
    results.append(_ProbeResult(
        name=(
            "T19 resume refuses path-traversal --out-dir (URI + "
            "under-REPO_ROOT)"
        ),
        ok=ok, detail=detail,
    ))

    # T20 — resume refuses SYMLINK INPUTS: an --out-dir that is itself a
    # symlink, an --out-dir with a symlink ancestor, and a staged plan
    # whose approved_plan.json was swapped for a symlink. Each returns
    # rc 2 (or fails closed with no review package) so a symlink target
    # cannot redirect what bytes the review package is built from.
    with tempfile.TemporaryDirectory(prefix="o2rp-T20-") as raw_td:
        td = Path(raw_td)
        ok, detail = True, ""

        # (a) --out-dir is itself a symlink to a valid plan dir.
        real_a = td / "real_a"
        images_a = td / "images_a"
        _write_synthetic_images(images_a)
        if main(["--plan", "--images-dir", str(images_a),
                 "--out-dir", str(real_a)]) != 0:
            ok, detail = False, "(a) plan setup failed"
        if ok:
            link_a = td / "link_a"
            link_a.symlink_to(real_a, target_is_directory=True)
            rc_a = main(["--resume", "--out-dir", str(link_a)])
            if rc_a != 2:
                ok, detail = False, (
                    f"(a) symlink --out-dir rc={rc_a} (expected 2)"
                )
            elif (real_a / "review_package").exists():
                ok, detail = False, (
                    "(a) review_package built through symlink --out-dir"
                )

        # (b) --out-dir has a symlink ANCESTOR.
        if ok:
            real_parent = td / "real_parent"
            real_parent.mkdir()
            images_b = td / "images_b"
            _write_synthetic_images(images_b)
            out_b = real_parent / "out_b"
            if main(["--plan", "--images-dir", str(images_b),
                     "--out-dir", str(out_b)]) != 0:
                ok, detail = False, "(b) plan setup failed"
            if ok:
                link_parent = td / "link_parent"
                link_parent.symlink_to(
                    real_parent, target_is_directory=True,
                )
                rc_b = main([
                    "--resume", "--out-dir", str(link_parent / "out_b"),
                ])
                if rc_b != 2:
                    ok, detail = False, (
                        f"(b) symlink-ancestor --out-dir rc={rc_b} "
                        f"(expected 2)"
                    )
                elif (out_b / "review_package").exists():
                    ok, detail = False, (
                        "(b) review_package built through symlink "
                        "ancestor"
                    )

        # (c) approved_plan.json swapped for a symlink in a real plan.
        if ok:
            real_c = td / "real_c"
            images_c = td / "images_c"
            _write_synthetic_images(images_c)
            if main(["--plan", "--images-dir", str(images_c),
                     "--out-dir", str(real_c)]) != 0:
                ok, detail = False, "(c) plan setup failed"
            if ok:
                plan_file = real_c / "approved_plan.json"
                real_plan = real_c / "real_plan.json"
                plan_file.replace(real_plan)
                plan_file.symlink_to(real_plan)
                rc_c = main(["--resume", "--out-dir", str(real_c)])
                if rc_c != 2:
                    ok, detail = False, (
                        f"(c) symlinked approved_plan.json rc={rc_c} "
                        f"(expected 2)"
                    )
                elif (real_c / "review_package").exists():
                    ok, detail = False, (
                        "(c) review_package built with symlinked "
                        "approved_plan.json"
                    )
        results.append(_ProbeResult(
            name=(
                "T20 resume refuses symlink inputs (--out-dir symlink / "
                "symlink ancestor / symlinked approved_plan.json)"
            ),
            ok=ok, detail=detail,
        ))

    # ----------------------------------------------------------------
    # Operator-supplied metadata (--manifest / --generated-provenance).
    # T21..T26 pin the optional wrapper-level metadata lane: a valid
    # reviewed manifest + sidecar are staged into the bundle in place of
    # the default templates and flow through to approved_plan.json +
    # summary.json; filename-set mismatch, symlink / URI paths, and
    # unsafe wording fail closed; plan/resume works with supplied
    # metadata; and the default (no-metadata) path is unchanged.
    # ----------------------------------------------------------------
    _MAN_MARKER = "Custom Operator Title Probe"
    _SIDE_MARKER = "Custom operator intent probe local only"

    # T21 — a valid custom manifest + sidecar are accepted in one-command
    # mode, the review package builds, and the custom slide_title /
    # intent_summary flow into BOTH approved_plan.json and the
    # review-package summary.json. The workflow README records the
    # staging honestly (an operator-supplied note, no template-write
    # command for the supplied files).
    with tempfile.TemporaryDirectory(prefix="o2rp-T21-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        out_dir = td / "workflow_out"
        _write_synthetic_images(images_dir)
        man = td / "custom_manifest.json"
        side = td / "custom_sidecar.json"
        ok, detail = True, ""
        err = _selftest_write_custom_manifest(
            images_dir, man, title=_MAN_MARKER,
        )
        if err:
            ok, detail = False, f"manifest fixture: {err}"
        if ok:
            err = _selftest_write_custom_sidecar(
                images_dir, side, intent=_SIDE_MARKER,
            )
            if err:
                ok, detail = False, f"sidecar fixture: {err}"
        if ok:
            rc = main(["--images-dir", str(images_dir),
                       "--out-dir", str(out_dir),
                       "--manifest", str(man),
                       "--generated-provenance", str(side)])
            if rc != 0:
                ok, detail = False, f"main rc={rc} for valid custom metadata"
        rp = out_dir / "review_package"
        if ok and not (rp / "deck.pptx").is_file():
            ok, detail = False, "review package not built with custom metadata"
        if ok:
            try:
                plan_text = (out_dir / "approved_plan.json").read_text(
                    encoding="utf-8")
                summary_text = (rp / "summary.json").read_text(
                    encoding="utf-8")
            except OSError as exc:
                ok, detail = False, (
                    f"could not read plan/summary: "
                    f"{type(exc).__name__}: {exc}"
                )
            else:
                for label, text in (
                    ("approved_plan.json", plan_text),
                    ("summary.json", summary_text),
                ):
                    if _MAN_MARKER not in text:
                        ok, detail = False, (
                            f"{label} missing custom manifest title marker"
                        )
                        break
                    if _SIDE_MARKER not in text:
                        ok, detail = False, (
                            f"{label} missing custom sidecar intent marker"
                        )
                        break
        if ok:
            try:
                readme_text = (out_dir / "README.md").read_text(
                    encoding="utf-8")
            except OSError as exc:
                ok, detail = False, (
                    f"workflow README unreadable: "
                    f"{type(exc).__name__}: {exc}"
                )
            else:
                if "operator-supplied metadata" not in readme_text:
                    ok, detail = False, (
                        "workflow README missing operator-supplied-"
                        "metadata note"
                    )
                elif ("--write-manifest-template" in readme_text
                      or "--write-generated-provenance-template"
                      in readme_text):
                    ok, detail = False, (
                        "workflow README still shows template-write "
                        "commands despite supplied metadata"
                    )
        results.append(_ProbeResult(
            name=(
                "T21 valid custom manifest + provenance accepted and "
                "reflected in plan / summary / README"
            ),
            ok=ok, detail=detail,
        ))

    # T22 — a supplied manifest whose filename set does NOT equal the
    # copied images is rejected (the helper's MAN12 cross-check runs over
    # the copied basenames before the file is staged), and no review
    # package is built.
    with tempfile.TemporaryDirectory(prefix="o2rp-T22-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        out_dir = td / "workflow_out"
        _write_synthetic_images(images_dir)
        man = td / "mismatch_manifest.json"
        ok, detail = True, ""
        err = _selftest_write_custom_manifest(images_dir, man, title="ok")
        if err:
            ok, detail = False, f"fixture: {err}"
        if ok:
            try:
                data = json.loads(man.read_text(encoding="utf-8"))
                data["images"][0]["filename"] = "nonexistent_marker.png"
                man.write_text(
                    json.dumps(data, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
            except (OSError, ValueError, KeyError, IndexError) as exc:
                ok, detail = False, (
                    f"could not perturb manifest: "
                    f"{type(exc).__name__}: {exc}"
                )
        if ok:
            rc = main(["--images-dir", str(images_dir),
                       "--out-dir", str(out_dir),
                       "--manifest", str(man)])
            rp = out_dir / "review_package"
            if rc == 0:
                ok, detail = False, "filename mismatch NOT rejected (rc=0)"
            elif rp.exists():
                ok, detail = False, (
                    f"refused (rc={rc}) but review_package built anyway"
                )
        results.append(_ProbeResult(
            name=(
                "T22 supplied manifest whose filename set != copied "
                "images is rejected"
            ),
            ok=ok, detail=detail,
        ))

    # T23 — a URI-shaped metadata path and a symlinked metadata path are
    # both refused at the CLI gate (rc 2) BEFORE --out-dir is even
    # created, so a redirected metadata path cannot stage anything.
    with tempfile.TemporaryDirectory(prefix="o2rp-T23-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        _write_synthetic_images(images_dir)
        ok, detail = True, ""
        out_a = td / "out_a"
        rc_a = main(["--images-dir", str(images_dir),
                     "--out-dir", str(out_a),
                     "--manifest", "file:///tmp/o2rp-T23-manifest.json"])
        if rc_a != 2:
            ok, detail = False, f"(a) URI --manifest rc={rc_a} (expected 2)"
        elif out_a.exists():
            ok, detail = False, "(a) URI --manifest created --out-dir"
        if ok:
            real_side = td / "real_sidecar.json"
            real_side.write_text("{}\n", encoding="utf-8")
            link_side = td / "link_sidecar.json"
            link_side.symlink_to(real_side)
            out_b = td / "out_b"
            rc_b = main(["--images-dir", str(images_dir),
                         "--out-dir", str(out_b),
                         "--generated-provenance", str(link_side)])
            if rc_b != 2:
                ok, detail = False, (
                    f"(b) symlink --generated-provenance rc={rc_b} "
                    f"(expected 2)"
                )
            elif out_b.exists():
                ok, detail = False, (
                    "(b) symlink --generated-provenance created --out-dir"
                )
        results.append(_ProbeResult(
            name=(
                "T23 URI-shaped / symlinked metadata path refused at the "
                "gate (rc 2, no staging)"
            ),
            ok=ok, detail=detail,
        ))

    # T24 — unsafe public / network / credential / raw-source wording in
    # a supplied manifest field OR sidecar field is rejected (the helper's
    # MAN10 / GP10 safe-string gates run over the staged metadata), and no
    # review package is built.
    with tempfile.TemporaryDirectory(prefix="o2rp-T24-") as raw_td:
        td = Path(raw_td)
        ok, detail = True, ""
        for label in ("manifest", "sidecar"):
            case_td = td / label
            case_td.mkdir()
            images_dir = case_td / "operator_images"
            out_dir = case_td / "workflow_out"
            _write_synthetic_images(images_dir)
            if label == "manifest":
                meta = case_td / "unsafe_manifest.json"
                err = _selftest_write_custom_manifest(
                    images_dir, meta, title="posted on twitter",
                )
                argv = ["--images-dir", str(images_dir),
                        "--out-dir", str(out_dir),
                        "--manifest", str(meta)]
            else:
                meta = case_td / "unsafe_sidecar.json"
                err = _selftest_write_custom_sidecar(
                    images_dir, meta, intent="shared on linkedin",
                )
                argv = ["--images-dir", str(images_dir),
                        "--out-dir", str(out_dir),
                        "--generated-provenance", str(meta)]
            if err:
                ok, detail = False, f"{label} fixture: {err}"
                break
            rc = main(argv)
            rp = out_dir / "review_package"
            if rc == 0:
                ok, detail = False, (
                    f"{label}: unsafe wording NOT rejected (rc=0)"
                )
                break
            if rp.exists():
                ok, detail = False, (
                    f"{label}: refused (rc={rc}) but review_package built"
                )
                break
        results.append(_ProbeResult(
            name=(
                "T24 unsafe wording in a supplied manifest / sidecar "
                "field is rejected"
            ),
            ok=ok, detail=detail,
        ))

    # T25 — the two-step reviewed flow works WITH supplied metadata:
    # --plan stages the custom manifest + sidecar (approved_plan.json
    # already carries the custom values; the plan README records the
    # operator-supplied staging), and --resume builds the review package
    # whose summary.json carries the same custom values.
    with tempfile.TemporaryDirectory(prefix="o2rp-T25-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        out_dir = td / "workflow_out"
        _write_synthetic_images(images_dir)
        man = td / "custom_manifest.json"
        side = td / "custom_sidecar.json"
        ok, detail = True, ""
        err = _selftest_write_custom_manifest(
            images_dir, man, title=_MAN_MARKER,
        )
        if err:
            ok, detail = False, f"manifest fixture: {err}"
        if ok:
            err = _selftest_write_custom_sidecar(
                images_dir, side, intent=_SIDE_MARKER,
            )
            if err:
                ok, detail = False, f"sidecar fixture: {err}"
        if ok:
            plan_rc = main(["--plan",
                            "--images-dir", str(images_dir),
                            "--out-dir", str(out_dir),
                            "--manifest", str(man),
                            "--generated-provenance", str(side)])
            if plan_rc != 0:
                ok, detail = False, f"plan rc={plan_rc} with custom metadata"
        if ok:
            try:
                plan_readme = (out_dir / "README.md").read_text(
                    encoding="utf-8")
                plan_text = (out_dir / "approved_plan.json").read_text(
                    encoding="utf-8")
            except OSError as exc:
                ok, detail = False, (
                    f"plan read: {type(exc).__name__}: {exc}"
                )
            else:
                if "operator-supplied" not in plan_readme:
                    ok, detail = False, (
                        "plan README missing operator-supplied marker"
                    )
                elif (_MAN_MARKER not in plan_text
                      or _SIDE_MARKER not in plan_text):
                    ok, detail = False, (
                        "approved_plan.json missing custom markers at "
                        "plan time"
                    )
        if ok:
            resume_rc = main(["--resume", "--out-dir", str(out_dir)])
            rp = out_dir / "review_package"
            if resume_rc != 0:
                ok, detail = False, (
                    f"resume rc={resume_rc} with custom metadata"
                )
            elif not (rp / "deck.pptx").is_file():
                ok, detail = False, "resume did not build review package"
            else:
                try:
                    summary_text = (rp / "summary.json").read_text(
                        encoding="utf-8")
                except OSError as exc:
                    ok, detail = False, (
                        f"summary read: {type(exc).__name__}: {exc}"
                    )
                else:
                    if (_MAN_MARKER not in summary_text
                            or _SIDE_MARKER not in summary_text):
                        ok, detail = False, (
                            "summary.json missing custom markers after "
                            "resume"
                        )
        results.append(_ProbeResult(
            name=(
                "T25 plan/resume works with supplied metadata "
                "(custom values flow into plan then summary)"
            ),
            ok=ok, detail=detail,
        ))

    # T26 — the default (no-metadata) path is UNCHANGED: the bundle
    # manifest is byte-identical to the helper's default template, and
    # the workflow README still shows the template-write command and does
    # NOT falsely claim operator-supplied metadata.
    with tempfile.TemporaryDirectory(prefix="o2rp-T26-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        out_dir = td / "workflow_out"
        _write_synthetic_images(images_dir)
        rc = main(["--images-dir", str(images_dir),
                   "--out-dir", str(out_dir)])
        ok = rc == 0
        detail = "" if ok else f"default-path main rc={rc}"
        if ok:
            ref = td / "ref_manifest.json"
            ref_outcome = _run(
                "ref manifest template",
                [sys.executable, str(HELPER_PATH),
                 "--images-dir", str(out_dir / "bundle" / "images"),
                 "--write-manifest-template", str(ref)],
            )
            if ref_outcome.rc != 0:
                ok, detail = False, (
                    f"ref manifest template rc={ref_outcome.rc}"
                )
            else:
                try:
                    staged = (out_dir / "bundle" / "manifest.json"
                              ).read_text(encoding="utf-8")
                    reference = ref.read_text(encoding="utf-8")
                except OSError as exc:
                    ok, detail = False, (
                        f"read: {type(exc).__name__}: {exc}"
                    )
                else:
                    if staged != reference:
                        ok, detail = False, (
                            "default bundle manifest drifted from the "
                            "helper template (default path changed)"
                        )
        if ok:
            try:
                readme_text = (out_dir / "README.md").read_text(
                    encoding="utf-8")
            except OSError as exc:
                ok, detail = False, f"README: {type(exc).__name__}: {exc}"
            else:
                if "operator-supplied metadata" in readme_text:
                    ok, detail = False, (
                        "default-path README falsely claims operator-"
                        "supplied metadata"
                    )
                elif "--write-manifest-template" not in readme_text:
                    ok, detail = False, (
                        "default-path README missing template-write "
                        "command"
                    )
        results.append(_ProbeResult(
            name=(
                "T26 default (no-metadata) path unchanged: bundle "
                "manifest == helper template, README shows template write"
            ),
            ok=ok, detail=detail,
        ))

    # ----------------------------------------------------------------
    # Template-only convenience (--templates-only). T27..T28 pin the
    # metadata-authoring shortcut: it writes ONLY the two editable
    # starter templates (which pass the helper validators) and builds
    # nothing else, and it refuses the modes / inputs it must not
    # combine with.
    # ----------------------------------------------------------------

    # T27 — --templates-only writes JUST manifest.json +
    # generated_provenance.json into a fresh --out-dir and builds NOTHING
    # else (no bundle/, approved_plan.json, review_package/, deck.pptx, or
    # README). Both files parse as JSON and pass the helper's own manifest
    # / sidecar contract validators against the image basenames — the same
    # gates --manifest / --generated-provenance enforce on supplied
    # metadata — so the operator gets schema-valid starter metadata to
    # hand-edit and feed back.
    with tempfile.TemporaryDirectory(prefix="o2rp-T27-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        out_dir = td / "templates_out"
        _write_synthetic_images(images_dir)
        rc = main(["--templates-only",
                   "--images-dir", str(images_dir),
                   "--out-dir", str(out_dir)])
        ok = rc == 0
        detail = "" if ok else f"main(--templates-only ...) rc={rc}"
        manifest = out_dir / "manifest.json"
        gen_prov = out_dir / "generated_provenance.json"
        if ok:
            for want in (manifest, gen_prov):
                if not want.is_file() or want.is_symlink():
                    ok, detail = False, f"missing template file: {want}"
                    break
        if ok:
            # --out-dir must contain EXACTLY the two templates: nothing
            # heavier (bundle/, approved_plan.json, review_package/,
            # README.md, any *.pptx) and no stray output.
            entries = sorted(p.name for p in out_dir.iterdir())
            decks = sorted(str(p) for p in out_dir.rglob("*.pptx"))
            if entries != ["generated_provenance.json", "manifest.json"]:
                ok, detail = False, (
                    f"--out-dir is not exactly the two templates: "
                    f"{entries!r}"
                )
            elif decks:
                ok, detail = False, (
                    f"template-only mode produced PPTX output: {decks!r}"
                )
        if ok:
            try:
                man_data = json.loads(manifest.read_text(encoding="utf-8"))
                gp_data = json.loads(gen_prov.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                ok, detail = False, (
                    f"template not parseable JSON: "
                    f"{type(exc).__name__}: {exc}"
                )
            else:
                if not (isinstance(man_data, dict)
                        and isinstance(man_data.get("images"), list)):
                    ok, detail = False, (
                        "manifest template missing images[] list"
                    )
                elif not (isinstance(gp_data, dict)
                          and isinstance(gp_data.get("entries"), list)):
                    ok, detail = False, (
                        "generated_provenance template missing entries[] "
                        "list"
                    )
        if ok:
            discovered = sorted(
                p.name for p in images_dir.iterdir() if p.is_file()
            )
            # Stable-snapshot guarantee: both templates must cover the
            # SAME filename set (equal to the operator's images). A
            # non-snapshotted build — each writer enumerating the live
            # folder independently — could disagree if the folder changed
            # between the two writer subprocesses.
            man_files = sorted(
                e.get("filename") for e in man_data["images"]
                if isinstance(e, dict)
            )
            gp_files = sorted(
                e.get("filename") for e in gp_data["entries"]
                if isinstance(e, dict)
            )
            if man_files != discovered or gp_files != discovered:
                ok, detail = False, (
                    f"templates disagree on the image set "
                    f"(manifest={man_files!r}, provenance={gp_files!r}, "
                    f"discovered={discovered!r})"
                )
        if ok:
            m_entries, _m_path, man_fails = _validate_manifest_arg(
                str(manifest), discovered,
            )
            g_entries, _g_path, gp_fails = (
                _validate_generated_provenance_sidecar(
                    str(gen_prov), discovered,
                )
            )
            if man_fails or m_entries is None:
                ok, detail = False, (
                    f"manifest template failed helper validator: "
                    f"{man_fails!r}"
                )
            elif gp_fails or g_entries is None:
                ok, detail = False, (
                    f"generated_provenance template failed helper "
                    f"validator: {gp_fails!r}"
                )
        results.append(_ProbeResult(
            name=(
                "T27 --templates-only writes only the two editable "
                "starter templates, they agree on the snapshotted image "
                "set, and both pass the helper validators"
            ),
            ok=ok, detail=detail,
        ))

    # T28 — --templates-only refuses the modes / inputs it must not
    # combine with: --manifest (supplying reviewed metadata while asking
    # to WRITE a template is contradictory) and --plan (a build mode)
    # each fail closed at the gate with rc 2 and no --out-dir created.
    with tempfile.TemporaryDirectory(prefix="o2rp-T28-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        _write_synthetic_images(images_dir)
        ok, detail = True, ""
        # (a) --templates-only + --manifest refused.
        real_manifest = td / "supplied_manifest.json"
        real_manifest.write_text("{}\n", encoding="utf-8")
        out_a = td / "out_a"
        rc_a = main(["--templates-only",
                     "--images-dir", str(images_dir),
                     "--out-dir", str(out_a),
                     "--manifest", str(real_manifest)])
        if rc_a != 2:
            ok, detail = False, (
                f"(a) --templates-only + --manifest rc={rc_a} (expected 2)"
            )
        elif out_a.exists():
            ok, detail = False, (
                "(a) refused combo still created --out-dir"
            )
        # (b) --templates-only + --plan refused.
        if ok:
            out_b = td / "out_b"
            rc_b = main(["--templates-only", "--plan",
                         "--images-dir", str(images_dir),
                         "--out-dir", str(out_b)])
            if rc_b != 2:
                ok, detail = False, (
                    f"(b) --templates-only + --plan rc={rc_b} (expected 2)"
                )
            elif out_b.exists():
                ok, detail = False, (
                    "(b) refused combo still created --out-dir"
                )
        results.append(_ProbeResult(
            name=(
                "T28 --templates-only refuses --manifest / --plan "
                "combinations at the gate (rc 2, no --out-dir created)"
            ),
            ok=ok, detail=detail,
        ))

    # ----------------------------------------------------------------
    # Prepare-images convenience (--prepare-images-only). T29..T35 pin
    # the messy-filename prepare step: it normalises real-world image
    # filenames into stable safe names usable by the existing
    # --templates-only / --plan / --resume flow, disambiguates base-stem
    # collisions with a deterministic numeric suffix, refuses unsafe
    # entries before any byte is copied, and refuses the modes / inputs it
    # must not combine with.
    # ----------------------------------------------------------------

    # T29 — happy path: a folder of messy real-world filenames (spaces +
    # parentheses + uppercase extension, an uppercase stem, CJK glyphs, and
    # an already-safe control) is copied into <out-dir>/images/ under stable
    # safe names; filename_mapping.json records original -> safe plus
    # byte_count / sha256 / media_type / extension for every image; only the
    # three prepare outputs are produced; and the prepared images/ feeds the
    # existing --templates-only mode (rc 0, manifest covers exactly the safe
    # names).
    with tempfile.TemporaryDirectory(prefix="o2rp-T29-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator images"   # source dir name has a space
        images_dir.mkdir()
        # Spaces / parens / uppercase -> lowercased _; interior dots and
        # hyphens (allowed by IG6 but NOT by the stricter image_ref
        # contract) -> _; a leading digit and a CJK-led run -> the img_
        # fallback (image_ref requires a leading lowercase letter); an
        # already-safe name unchanged.
        expected = {
            "My Photo (1).PNG": "my_photo_1_.png",
            "UPPER.JPEG": "upper.jpeg",
            "图1_report.png": "img_1_report.png",
            "report-v2.png": "report_v2.png",
            "photo.final.png": "photo_final.png",
            "2024shots.png": "img_2024shots.png",
            "plain.jpg": "plain.jpg",
        }
        for orig in expected:
            ext0 = orig.rsplit(".", 1)[1].lower()
            (images_dir / orig).write_bytes(
                _TINY_PNG_BYTES if ext0 == "png" else _TINY_JPEG_BYTES
            )
        out_dir = td / "prepared"
        rc = main(["--prepare-images-only",
                   "--images-dir", str(images_dir),
                   "--out-dir", str(out_dir)])
        ok = rc == 0
        detail = "" if ok else f"main(--prepare-images-only ...) rc={rc}"
        out_images = out_dir / "images"
        mapping_path = out_dir / "filename_mapping.json"
        if ok:
            produced = sorted(p.name for p in out_dir.iterdir())
            if produced != ["README.md", "filename_mapping.json", "images"]:
                ok, detail = False, (
                    f"--out-dir is not exactly the three prepare outputs: "
                    f"{produced!r}"
                )
        if ok:
            try:
                mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                ok, detail = False, (
                    f"filename_mapping.json not parseable: "
                    f"{type(exc).__name__}: {exc}"
                )
        if ok:
            rows = mapping.get("images")
            if not isinstance(rows, list) or len(rows) != len(expected):
                ok, detail = False, f"mapping images[] wrong shape: {rows!r}"
        if ok:
            by_orig = {
                r.get("original_filename"): r for r in rows
                if isinstance(r, dict)
            }
            for orig, want_safe in expected.items():
                row = by_orig.get(orig)
                if row is None:
                    ok, detail = False, f"mapping missing original {orig!r}"
                    break
                if row.get("safe_filename") != want_safe:
                    ok, detail = False, (
                        f"{orig!r} -> {row.get('safe_filename')!r} "
                        f"(expected {want_safe!r})"
                    )
                    break
                stem = want_safe.rsplit(".", 1)[0]
                if (not _IMAGE_REF_PATTERN.match(stem)
                        or len(stem) > _ID_MAX_LEN):
                    ok, detail = False, (
                        f"safe stem {stem!r} does not match the downstream "
                        f"image_ref contract {_IMAGE_REF_PATTERN.pattern!r}"
                    )
                    break
                ext = want_safe.rsplit(".", 1)[1]
                raw = _TINY_PNG_BYTES if ext == "png" else _TINY_JPEG_BYTES
                want_media = "image/png" if ext == "png" else "image/jpeg"
                if (row.get("byte_count") != len(raw)
                        or row.get("sha256")
                        != hashlib.sha256(raw).hexdigest()
                        or row.get("media_type") != want_media
                        or row.get("extension") != ext):
                    ok, detail = False, (
                        f"mapping fields wrong for {orig!r}: {row!r}"
                    )
                    break
                if not (out_images / want_safe).is_file():
                    ok, detail = False, (
                        f"safe file images/{want_safe} not on disk"
                    )
                    break
        if ok:
            # The prepared images/ must be directly usable by the existing
            # --templates-only mode (the whole point of the prepare step).
            out2 = td / "templates_from_prepared"
            rc2 = main(["--templates-only",
                        "--images-dir", str(out_images),
                        "--out-dir", str(out2)])
            if rc2 != 0:
                ok, detail = False, (
                    f"prepared images/ not usable by --templates-only "
                    f"(rc={rc2})"
                )
            else:
                try:
                    man = json.loads(
                        (out2 / "manifest.json").read_text(encoding="utf-8")
                    )
                except (OSError, ValueError) as exc:
                    ok, detail = False, (
                        f"templates-only manifest unreadable: "
                        f"{type(exc).__name__}: {exc}"
                    )
                else:
                    got = sorted(
                        e.get("filename") for e in man.get("images", [])
                        if isinstance(e, dict)
                    )
                    if got != sorted(expected.values()):
                        ok, detail = False, (
                            f"templates-only manifest set {got!r} != the "
                            f"prepared safe names"
                        )
        results.append(_ProbeResult(
            name=(
                "T29 --prepare-images-only normalises messy filenames "
                "(spaces / parens / uppercase / dots / hyphens / leading "
                "digit / CJK) into image_ref-safe names, records a complete "
                "mapping, and the prepared images/ feeds --templates-only"
            ),
            ok=ok, detail=detail,
        ))

    # T30 — two DISTINCT source names that normalise to the same base stem
    # ("My File.png" and "my_file.png" both -> 'my_file') are DISAMBIGUATED
    # with a deterministic numeric suffix instead of failing closed: in
    # sorted order the earlier name keeps 'my_file' and the later takes
    # 'my_file_2'. The two names differ by more than case, so the probe is
    # valid on a case-insensitive filesystem too. A second run on the same
    # content must yield the identical mapping (determinism), and the two
    # safe names must be distinct on disk (no silent overwrite).
    with tempfile.TemporaryDirectory(prefix="o2rp-T30-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        images_dir.mkdir()
        (images_dir / "My File.png").write_bytes(_TINY_PNG_BYTES)
        (images_dir / "my_file.png").write_bytes(_TINY_PNG_BYTES)
        # sorted(iterdir()) orders 'My File.png' (uppercase 'M' = 0x4D)
        # before 'my_file.png' (lowercase 'm' = 0x6D), so the first keeps
        # the bare stem and the second takes the _2 suffix.
        want = {"My File.png": "my_file.png", "my_file.png": "my_file_2.png"}
        out_dir = td / "prepared"
        rc = main(["--prepare-images-only",
                   "--images-dir", str(images_dir),
                   "--out-dir", str(out_dir)])
        ok = rc == 0
        detail = "" if ok else f"collision disambiguation rc={rc} (expected 0)"
        got: dict = {}
        if ok:
            try:
                mapping = json.loads(
                    (out_dir / "filename_mapping.json").read_text(
                        encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                ok, detail = False, f"mapping unreadable: {exc!r}"
            else:
                got = {
                    r.get("original_filename"): r.get("safe_filename")
                    for r in mapping.get("images", []) if isinstance(r, dict)
                }
                if got != want:
                    ok, detail = False, (
                        f"collision mapping {got!r} != expected {want!r}"
                    )
        if ok and len(set(want.values())) != 2:
            ok, detail = False, "the two safe names are not distinct"
        if ok:
            for safe in want.values():
                if not (out_dir / "images" / safe).is_file():
                    ok, detail = False, f"safe file images/{safe} missing"
                    break
        if ok:
            # Determinism: a second run on the same content -> same names.
            out_dir2 = td / "prepared2"
            rc2 = main(["--prepare-images-only",
                        "--images-dir", str(images_dir),
                        "--out-dir", str(out_dir2)])
            if rc2 != 0:
                ok, detail = False, f"second run rc={rc2} (expected 0)"
            else:
                mapping2 = json.loads(
                    (out_dir2 / "filename_mapping.json").read_text(
                        encoding="utf-8")
                )
                got2 = {
                    r.get("original_filename"): r.get("safe_filename")
                    for r in mapping2.get("images", []) if isinstance(r, dict)
                }
                if got2 != got:
                    ok, detail = False, f"non-deterministic: {got2!r} != {got!r}"
        results.append(_ProbeResult(
            name=(
                "T30 --prepare-images-only disambiguates a base-stem "
                "collision (My File.png / my_file.png) into distinct names "
                "with a deterministic numeric suffix (my_file / my_file_2), "
                "not a refusal"
            ),
            ok=ok, detail=detail,
        ))

    # T31 — unsafe entries still fail closed in prepare mode (the same
    # _preflight_image_entries gate the bundle-staging path uses): (a) a
    # per-file symlink is refused at the gate, and (b) a non-image .txt is
    # refused before any byte is copied. Neither leaves an images/ folder.
    with tempfile.TemporaryDirectory(prefix="o2rp-T31-") as raw_td:
        td = Path(raw_td)
        ok, detail = True, ""
        # (a) symlink entry.
        src_a = td / "imgs_a"
        src_a.mkdir()
        (src_a / "real.png").write_bytes(_TINY_PNG_BYTES)
        target = td / "target.png"
        target.write_bytes(_TINY_PNG_BYTES)
        (src_a / "link.png").symlink_to(target)
        out_a = td / "out_a"
        rc_a = main(["--prepare-images-only",
                     "--images-dir", str(src_a), "--out-dir", str(out_a)])
        if rc_a != 1:
            ok, detail = False, f"(a) symlink entry rc={rc_a} (expected 1)"
        elif (out_a / "images").exists():
            ok, detail = False, "(a) symlink-refused run still created images/"
        # (b) non-image .txt alongside a valid PNG.
        if ok:
            src_b = td / "imgs_b"
            src_b.mkdir()
            (src_b / "ok.png").write_bytes(_TINY_PNG_BYTES)
            (src_b / "notes.txt").write_text("x", encoding="utf-8")
            out_b = td / "out_b"
            rc_b = main(["--prepare-images-only",
                         "--images-dir", str(src_b), "--out-dir", str(out_b)])
            if rc_b != 1:
                ok, detail = False, f"(b) non-image .txt rc={rc_b} (expected 1)"
            elif (out_b / "images").exists():
                ok, detail = False, (
                    "(b) non-image-refused run still created images/"
                )
        results.append(_ProbeResult(
            name=(
                "T31 --prepare-images-only refuses unsafe entries (per-file "
                "symlink, non-image file) before any byte is copied"
            ),
            ok=ok, detail=detail,
        ))

    # T32 — --prepare-images-only refuses the modes / inputs it must not
    # combine with: --plan and --templates-only (build / write modes) and
    # --manifest (reviewed metadata for a build) each fail closed at the
    # gate with rc 2 and no --out-dir created.
    with tempfile.TemporaryDirectory(prefix="o2rp-T32-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "operator_images"
        images_dir.mkdir()
        (images_dir / "ok.png").write_bytes(_TINY_PNG_BYTES)
        real_manifest = td / "supplied_manifest.json"
        real_manifest.write_text("{}\n", encoding="utf-8")
        ok, detail = True, ""
        combos = [
            ("--plan", ["--plan"]),
            ("--templates-only", ["--templates-only"]),
            ("--manifest", ["--manifest", str(real_manifest)]),
        ]
        for label, extra in combos:
            out = td / ("out_" + label.strip("-"))
            rc = main(["--prepare-images-only", *extra,
                       "--images-dir", str(images_dir), "--out-dir", str(out)])
            if rc != 2:
                ok, detail = False, (
                    f"--prepare-images-only + {label} rc={rc} (expected 2)"
                )
                break
            if out.exists():
                ok, detail = False, (
                    f"--prepare-images-only + {label} still created --out-dir"
                )
                break
        results.append(_ProbeResult(
            name=(
                "T32 --prepare-images-only refuses --plan / --templates-only "
                "/ --manifest combinations at the gate (rc 2, no --out-dir "
                "created)"
            ),
            ok=ok, detail=detail,
        ))

    # T33 — END-TO-END downstream proof: the prepared images/ (safe names
    # derived from messy originals carrying dots / hyphens / a leading
    # digit AND a CJK-only name with no usable ASCII stem — the exact shapes
    # that pass the looser IG6 --images-dir gate but break the render_model
    # image_ref contract) builds a FULL review package via the one-command
    # workflow. The operator lane uses each stem verbatim as the asset_id
    # that becomes the slide's image_ref, so a name normalised only to IG6
    # would fail render_model validation during the build; a green deck.pptx
    # is the authoritative proof that the prepare step normalises to the real
    # downstream contract, not just IG6 — including the CJK-only 'img' stem.
    with tempfile.TemporaryDirectory(prefix="o2rp-T33-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "messy images"
        images_dir.mkdir()
        (images_dir / "report-v2.png").write_bytes(_TINY_PNG_BYTES)
        (images_dir / "photo.final.png").write_bytes(_TINY_PNG_BYTES)
        (images_dir / "2024 Shots.JPG").write_bytes(_TINY_JPEG_BYTES)
        (images_dir / "季度报告.png").write_bytes(_TINY_PNG_BYTES)
        prepared = td / "prepared"
        rc = main(["--prepare-images-only",
                   "--images-dir", str(images_dir),
                   "--out-dir", str(prepared)])
        ok = rc == 0
        detail = "" if ok else f"prepare step rc={rc}"
        if ok:
            built = td / "built"
            rc_b = main(["--images-dir", str(prepared / "images"),
                         "--out-dir", str(built)])
            if rc_b != 0:
                ok, detail = False, (
                    f"prepared images/ failed the full one-command build "
                    f"(rc={rc_b}) — a safe name did not satisfy the "
                    f"downstream image_ref contract"
                )
            elif not (built / "review_package" / "deck.pptx").is_file():
                ok, detail = False, (
                    "one-command build on prepared images/ produced no "
                    "deck.pptx"
                )
        results.append(_ProbeResult(
            name=(
                "T33 prepared images/ (safe names from messy originals with "
                "dots / hyphens / leading digit / a CJK-only name) build a "
                "full review package end-to-end (proves the image_ref "
                "contract ^[a-z][a-z0-9_]*$, not just IG6)"
            ),
            ok=ok, detail=detail,
        ))

    # T34 — multiple CJK-only (no usable ASCII stem) filenames each prepare
    # to a DISTINCT, image_ref-valid safe name instead of all collapsing onto
    # one 'img' stem and being refused. Three distinct CJK-only names map to
    # the uniform base 'img' and are disambiguated to img / img_2 / img_3 in
    # sorted-original order; a second run yields the identical mapping
    # (determinism); and every safe stem satisfies ^[a-z][a-z0-9_]*$.
    with tempfile.TemporaryDirectory(prefix="o2rp-T34-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "cjk images"
        images_dir.mkdir()
        cjk_names = ["财务.png", "报告.png", "预算.png"]
        for n in cjk_names:
            (images_dir / n).write_bytes(_TINY_PNG_BYTES)
        # The wrapper walks sorted(iterdir()); the bare base 'img' goes to
        # the first sorted original, then img_2, img_3.
        want = dict(zip(sorted(cjk_names),
                        ["img.png", "img_2.png", "img_3.png"]))
        out_dir = td / "prepared"
        rc = main(["--prepare-images-only",
                   "--images-dir", str(images_dir),
                   "--out-dir", str(out_dir)])
        ok = rc == 0
        detail = "" if ok else f"CJK-only prepare rc={rc} (expected 0)"
        got: dict = {}
        if ok:
            try:
                mapping = json.loads(
                    (out_dir / "filename_mapping.json").read_text(
                        encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                ok, detail = False, f"mapping unreadable: {exc!r}"
            else:
                got = {
                    r.get("original_filename"): r.get("safe_filename")
                    for r in mapping.get("images", []) if isinstance(r, dict)
                }
                if got != want:
                    ok, detail = False, (
                        f"CJK mapping {got!r} != expected {want!r}"
                    )
        if ok and len(set(want.values())) != len(want):
            ok, detail = False, "CJK safe names are not distinct"
        if ok:
            for orig, safe in want.items():
                stem = safe.rsplit(".", 1)[0]
                if not _IMAGE_REF_PATTERN.match(stem):
                    ok, detail = False, (
                        f"CJK safe stem {stem!r} (from {orig!r}) violates "
                        f"{_IMAGE_REF_PATTERN.pattern!r}"
                    )
                    break
                if not (out_dir / "images" / safe).is_file():
                    ok, detail = False, f"safe file images/{safe} missing"
                    break
        if ok:
            # Determinism: a second run on the same content -> same names.
            out_dir2 = td / "prepared2"
            rc2 = main(["--prepare-images-only",
                        "--images-dir", str(images_dir),
                        "--out-dir", str(out_dir2)])
            if rc2 != 0:
                ok, detail = False, f"second run rc={rc2} (expected 0)"
            else:
                mapping2 = json.loads(
                    (out_dir2 / "filename_mapping.json").read_text(
                        encoding="utf-8")
                )
                got2 = {
                    r.get("original_filename"): r.get("safe_filename")
                    for r in mapping2.get("images", []) if isinstance(r, dict)
                }
                if got2 != got:
                    ok, detail = False, f"non-deterministic: {got2!r} != {got!r}"
        results.append(_ProbeResult(
            name=(
                "T34 --prepare-images-only maps multiple CJK-only filenames "
                "to distinct image_ref-valid names (img / img_2 / img_3) "
                "deterministically, no pre-rename or refusal"
            ),
            ok=ok, detail=detail,
        ))

    # T35 — mixed CJK + ASCII filenames keep their ASCII run in the safe
    # stem (the CJK glyphs map to '_', the ASCII letters/digits survive), so
    # the prepared name stays readable rather than collapsing to a bare
    # 'img'. The three names do not collide, so no numeric suffix is applied.
    with tempfile.TemporaryDirectory(prefix="o2rp-T35-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "mixed images"
        images_dir.mkdir()
        want = {
            "数据chart.png": "img_chart.png",   # leading CJK -> img_ + chart
            "report报告.png": "report_.png",    # trailing CJK -> trailing _
            "q3财报2024.png": "q3_2024.png",     # CJK between ASCII runs
        }
        for n in want:
            (images_dir / n).write_bytes(_TINY_PNG_BYTES)
        out_dir = td / "prepared"
        rc = main(["--prepare-images-only",
                   "--images-dir", str(images_dir),
                   "--out-dir", str(out_dir)])
        ok = rc == 0
        detail = "" if ok else f"mixed prepare rc={rc} (expected 0)"
        if ok:
            try:
                mapping = json.loads(
                    (out_dir / "filename_mapping.json").read_text(
                        encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                ok, detail = False, f"mapping unreadable: {exc!r}"
            else:
                got = {
                    r.get("original_filename"): r.get("safe_filename")
                    for r in mapping.get("images", []) if isinstance(r, dict)
                }
                if got != want:
                    ok, detail = False, (
                        f"mixed mapping {got!r} != expected {want!r}"
                    )
        if ok:
            for orig, safe in want.items():
                stem = safe.rsplit(".", 1)[0]
                if not _IMAGE_REF_PATTERN.match(stem):
                    ok, detail = False, (
                        f"mixed safe stem {stem!r} (from {orig!r}) violates "
                        f"{_IMAGE_REF_PATTERN.pattern!r}"
                    )
                    break
                if not (out_dir / "images" / safe).is_file():
                    ok, detail = False, f"safe file images/{safe} missing"
                    break
        results.append(_ProbeResult(
            name=(
                "T35 --prepare-images-only preserves the ASCII run of mixed "
                "CJK + ASCII filenames (数据chart -> img_chart, report报告 "
                "-> report_, q3财报2024 -> q3_2024)"
            ),
            ok=ok, detail=detail,
        ))

    # ----------------------------------------------------------------
    # Filename-mapping title seeding (--templates-only --filename-mapping).
    # T36..T40 pin the operator-facing improvement: when a deck is prepared
    # from messy real-world filenames, --templates-only can seed the
    # manifest's slide_title / alt_text from each image's ORIGINAL filename
    # (recovered from --prepare-images-only's filename_mapping.json) instead
    # of the normalized safe basename, so human-readable titles survive
    # normalization. Without a mapping the prior safe-name behavior is kept;
    # a mapping that does not correspond to the prepared image set, a wrong
    # mode, or an unsafe path all fail closed.
    # ----------------------------------------------------------------

    # T36 — original filenames with spaces + punctuation seed readable
    # titles. Prepare a messy folder, then --templates-only
    # --filename-mapping, and assert each manifest slide_title / alt_text is
    # rebuilt from the ORIGINAL filename (so the spaces / parentheses /
    # commas survive) and differs from the safe-basename default.
    with tempfile.TemporaryDirectory(prefix="o2rp-T36-") as raw_td:
        td = Path(raw_td)
        src = td / "operator images"
        src.mkdir()
        originals = {
            "Q3 Revenue (Final).png": _TINY_PNG_BYTES,
            "Plan B, v2.jpg": _TINY_JPEG_BYTES,
        }
        for name, data in originals.items():
            (src / name).write_bytes(data)
        prepared = td / "prepared"
        rc = main(["--prepare-images-only", "--images-dir", str(src),
                   "--out-dir", str(prepared)])
        ok = rc == 0
        detail = "" if ok else f"--prepare-images-only rc={rc}"
        out_dir = td / "templates_out"
        if ok:
            rc = main(["--templates-only",
                       "--images-dir", str(prepared / "images"),
                       "--filename-mapping",
                       str(prepared / "filename_mapping.json"),
                       "--out-dir", str(out_dir)])
            if rc != 0:
                ok, detail = False, (
                    f"--templates-only --filename-mapping rc={rc}"
                )
        if ok:
            mapping = json.loads(
                (prepared / "filename_mapping.json").read_text(
                    encoding="utf-8")
            )
            safe_to_orig = {
                r["safe_filename"]: r["original_filename"]
                for r in mapping["images"]
            }
            man = json.loads(
                (out_dir / "manifest.json").read_text(encoding="utf-8")
            )
            for entry in man["images"]:
                safe = entry["filename"]
                original = safe_to_orig[safe]
                if entry["slide_title"] != _slide_title_for_name(original):
                    ok, detail = False, (
                        f"{safe} slide_title={entry['slide_title']!r} != "
                        f"seeded-from-original "
                        f"{_slide_title_for_name(original)!r}"
                    )
                    break
                if entry["alt_text"] != _alt_text_for_name(original):
                    ok, detail = False, (
                        f"{safe} alt_text not seeded from original "
                        f"{original!r}"
                    )
                    break
                # These originals normalize, so the seed must have moved the
                # title off the safe-basename default.
                if entry["slide_title"] == _slide_title_for_name(safe):
                    ok, detail = False, (
                        f"{safe} slide_title still uses the safe basename "
                        f"(seeding did not take effect)"
                    )
                    break
        results.append(_ProbeResult(
            name=(
                "T36 --templates-only --filename-mapping seeds slide_title / "
                "alt_text from original filenames with spaces + punctuation "
                "(not the normalized safe basename)"
            ),
            ok=ok, detail=detail,
        ))

    # T37 — CJK / non-ASCII original filenames seed readable titles when the
    # mapping exists. --prepare-images-only normalizes a CJK-only name to a
    # bland ASCII safe stem (img / img_2), which is unreadable; with the
    # mapping the original CJK characters are restored in the seeded title.
    with tempfile.TemporaryDirectory(prefix="o2rp-T37-") as raw_td:
        td = Path(raw_td)
        src = td / "cjk images"
        src.mkdir()
        originals = {
            "季度营收.png": _TINY_PNG_BYTES,
            "报告 2024.jpg": _TINY_JPEG_BYTES,
        }
        for name, data in originals.items():
            (src / name).write_bytes(data)
        prepared = td / "prepared"
        rc = main(["--prepare-images-only", "--images-dir", str(src),
                   "--out-dir", str(prepared)])
        ok = rc == 0
        detail = "" if ok else f"--prepare-images-only rc={rc}"
        out_dir = td / "templates_out"
        if ok:
            rc = main(["--templates-only",
                       "--images-dir", str(prepared / "images"),
                       "--filename-mapping",
                       str(prepared / "filename_mapping.json"),
                       "--out-dir", str(out_dir)])
            if rc != 0:
                ok, detail = False, (
                    f"--templates-only --filename-mapping rc={rc}"
                )
        if ok:
            mapping = json.loads(
                (prepared / "filename_mapping.json").read_text(
                    encoding="utf-8")
            )
            safe_to_orig = {
                r["safe_filename"]: r["original_filename"]
                for r in mapping["images"]
            }
            man = json.loads(
                (out_dir / "manifest.json").read_text(encoding="utf-8")
            )
            saw_non_ascii = False
            for entry in man["images"]:
                safe = entry["filename"]
                original = safe_to_orig[safe]
                if entry["slide_title"] != _slide_title_for_name(original):
                    ok, detail = False, (
                        f"{safe} slide_title not seeded from CJK original "
                        f"{original!r}"
                    )
                    break
                # The safe basename is pure ASCII; a seeded title carrying a
                # non-ASCII codepoint proves the CJK original survived.
                if any(ord(ch) > 127 for ch in entry["slide_title"]):
                    saw_non_ascii = True
                if entry["slide_title"] == _slide_title_for_name(safe):
                    ok, detail = False, (
                        f"{safe} slide_title still the ASCII safe basename"
                    )
                    break
            if ok and not saw_non_ascii:
                ok, detail = False, (
                    "no seeded slide_title carried a non-ASCII (CJK) "
                    "codepoint"
                )
        results.append(_ProbeResult(
            name=(
                "T37 --templates-only --filename-mapping seeds readable "
                "titles from CJK / non-ASCII original filenames (safe "
                "basename is bland ASCII; the mapping restores the original)"
            ),
            ok=ok, detail=detail,
        ))

    # T38 — without --filename-mapping the prior behavior is preserved: the
    # manifest slide_title / alt_text derive from the safe basename, NOT any
    # original filename. Guards that the new option is purely additive.
    with tempfile.TemporaryDirectory(prefix="o2rp-T38-") as raw_td:
        td = Path(raw_td)
        src = td / "operator images"
        src.mkdir()
        (src / "Q3 Revenue (Final).png").write_bytes(_TINY_PNG_BYTES)
        prepared = td / "prepared"
        rc = main(["--prepare-images-only", "--images-dir", str(src),
                   "--out-dir", str(prepared)])
        ok = rc == 0
        detail = "" if ok else f"--prepare-images-only rc={rc}"
        out_dir = td / "templates_out"
        if ok:
            rc = main(["--templates-only",
                       "--images-dir", str(prepared / "images"),
                       "--out-dir", str(out_dir)])
            if rc != 0:
                ok, detail = False, f"--templates-only rc={rc}"
        if ok:
            man = json.loads(
                (out_dir / "manifest.json").read_text(encoding="utf-8")
            )
            for entry in man["images"]:
                safe = entry["filename"]
                if entry["slide_title"] != _slide_title_for_name(safe):
                    ok, detail = False, (
                        f"{safe} slide_title={entry['slide_title']!r} is not "
                        f"the safe-basename default "
                        f"{_slide_title_for_name(safe)!r}"
                    )
                    break
                if entry["alt_text"] != _alt_text_for_name(safe):
                    ok, detail = False, (
                        f"{safe} alt_text is not the safe-basename default"
                    )
                    break
        results.append(_ProbeResult(
            name=(
                "T38 --templates-only WITHOUT --filename-mapping keeps the "
                "prior behavior: slide_title / alt_text derive from the safe "
                "basename, not the original filename"
            ),
            ok=ok, detail=detail,
        ))

    # T39 — fail-closed paths for --filename-mapping: (a) a mapping whose
    # safe_filename set does not correspond to the prepared images is refused
    # mid-run (rc 1, no seeded title leaks); (b) --filename-mapping outside
    # --templates-only is refused at the gate (rc 2, no --out-dir); (c) a
    # URI-shaped --filename-mapping is refused at the gate (rc 2, no
    # --out-dir); (d) a mapping whose safe names MATCH but whose recorded
    # sha256 / byte_count describe DIFFERENT bytes (a stale / unrelated
    # mapping) is refused mid-run (rc 1) — the mapping is bound to the
    # prepared bytes, not just the filename set.
    with tempfile.TemporaryDirectory(prefix="o2rp-T39-") as raw_td:
        td = Path(raw_td)
        src = td / "operator images"
        src.mkdir()
        (src / "My Photo (1).png").write_bytes(_TINY_PNG_BYTES)
        prepared = td / "prepared"
        ok = main(["--prepare-images-only", "--images-dir", str(src),
                   "--out-dir", str(prepared)]) == 0
        detail = "" if ok else "prepare failed"
        # (a) mismatched safe-name set -> rc 1. Carries valid-looking
        # sha256 / byte_count so the SET check fires (not the field check).
        if ok:
            bad = td / "bad_mapping.json"
            bad.write_text(
                json.dumps({
                    "schema_version": "1",
                    "images": [{
                        "original_filename": "Something Else.png",
                        "safe_filename": "not_a_prepared_name.png",
                        "sha256": "0" * 64,
                        "byte_count": 1,
                    }],
                }) + "\n",
                encoding="utf-8",
            )
            out_a = td / "out_a"
            rc_a = main(["--templates-only",
                         "--images-dir", str(prepared / "images"),
                         "--filename-mapping", str(bad),
                         "--out-dir", str(out_a)])
            if rc_a != 1:
                ok, detail = False, (
                    f"(a) mismatched mapping rc={rc_a} (expected 1)"
                )
            else:
                # The torn run left the un-seeded templates; no seeded title
                # from the bogus mapping may have leaked into the manifest.
                man_path = out_a / "manifest.json"
                if man_path.is_file():
                    man = json.loads(man_path.read_text(encoding="utf-8"))
                    if any("Something Else" in e.get("slide_title", "")
                           for e in man.get("images", [])):
                        ok, detail = False, (
                            "(a) bogus mapping leaked into a seeded title"
                        )
        # (b) --filename-mapping without --templates-only -> rc 2, no out.
        if ok:
            out_b = td / "out_b"
            rc_b = main(["--images-dir", str(prepared / "images"),
                         "--filename-mapping",
                         str(prepared / "filename_mapping.json"),
                         "--out-dir", str(out_b)])
            if rc_b != 2:
                ok, detail = False, (
                    f"(b) mapping without --templates-only rc={rc_b} "
                    f"(expected 2)"
                )
            elif out_b.exists():
                ok, detail = False, (
                    "(b) refused combo still created --out-dir"
                )
        # (c) URI-shaped --filename-mapping -> rc 2, no out.
        if ok:
            out_c = td / "out_c"
            rc_c = main(["--templates-only",
                         "--images-dir", str(prepared / "images"),
                         "--filename-mapping", "http://example.com/m.json",
                         "--out-dir", str(out_c)])
            if rc_c != 2:
                ok, detail = False, (
                    f"(c) URI-shaped mapping rc={rc_c} (expected 2)"
                )
            elif out_c.exists():
                ok, detail = False, (
                    "(c) refused URI path still created --out-dir"
                )
        # (d) matching safe names but WRONG bytes -> rc 1. Tamper the real
        # mapping's recorded sha256 so the safe-name set still matches but the
        # byte binding fails — proves the mapping is bound to the prepared
        # bytes, not just the filename set.
        if ok:
            real = json.loads(
                (prepared / "filename_mapping.json").read_text(
                    encoding="utf-8")
            )
            for row in real["images"]:
                row["sha256"] = "0" * 64
            tampered = td / "tampered_mapping.json"
            tampered.write_text(
                json.dumps(real, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            out_d = td / "out_d"
            rc_d = main(["--templates-only",
                         "--images-dir", str(prepared / "images"),
                         "--filename-mapping", str(tampered),
                         "--out-dir", str(out_d)])
            if rc_d != 1:
                ok, detail = False, (
                    f"(d) byte-mismatch mapping rc={rc_d} (expected 1)"
                )
        results.append(_ProbeResult(
            name=(
                "T39 --filename-mapping fails closed: mismatched safe-name "
                "set (rc 1, no seeded title), wrong mode (rc 2), URI-shaped "
                "path (rc 2), and a mapping bound to different bytes "
                "(matching names, wrong sha256 -> rc 1) are all refused"
            ),
            ok=ok, detail=detail,
        ))

    # T40 — end-to-end: mapped starter metadata flows through the build.
    # Prepare a messy folder, seed titles via --templates-only
    # --filename-mapping, then feed the seeded manifest (+ the generated
    # provenance template) through --plan and --resume. The resumed review
    # package is built AND internally re-validated (resume rc 0 implies the
    # read-only validator passed), and the seeded title surfaces in
    # summary.json's image_provenance as operator_slide_title.
    with tempfile.TemporaryDirectory(prefix="o2rp-T40-") as raw_td:
        td = Path(raw_td)
        src = td / "operator images"
        src.mkdir()
        (src / "Cover Slide A.png").write_bytes(_TINY_PNG_BYTES)
        (src / "Divider-B v2.jpg").write_bytes(_TINY_JPEG_BYTES)
        prepared = td / "prepared"
        ok = main(["--prepare-images-only", "--images-dir", str(src),
                   "--out-dir", str(prepared)]) == 0
        detail = "" if ok else "prepare failed"
        tpl = td / "templates_out"
        if ok:
            rc = main(["--templates-only",
                       "--images-dir", str(prepared / "images"),
                       "--filename-mapping",
                       str(prepared / "filename_mapping.json"),
                       "--out-dir", str(tpl)])
            if rc != 0:
                ok, detail = False, (
                    f"--templates-only --filename-mapping rc={rc}"
                )
        out_dir = td / "build"
        if ok:
            rc = main(["--plan",
                       "--images-dir", str(prepared / "images"),
                       "--out-dir", str(out_dir),
                       "--manifest", str(tpl / "manifest.json"),
                       "--generated-provenance",
                       str(tpl / "generated_provenance.json")])
            if rc != 0:
                ok, detail = False, f"--plan rc={rc}"
        if ok:
            rc = main(["--resume", "--out-dir", str(out_dir)])
            if rc != 0:
                ok, detail = False, f"--resume rc={rc}"
        review_package = out_dir / "review_package"
        if ok:
            for name in _REVIEW_PACKAGE_FILES:
                if (not (review_package / name).is_file()
                        or (review_package / name).is_symlink()):
                    ok, detail = False, (
                        f"missing review-package file: {name}"
                    )
                    break
        if ok:
            mapping = json.loads(
                (prepared / "filename_mapping.json").read_text(
                    encoding="utf-8")
            )
            safe_to_orig = {
                r["safe_filename"]: r["original_filename"]
                for r in mapping["images"]
            }
            summary = json.loads(
                (review_package / "summary.json").read_text(encoding="utf-8")
            )
            rows = {
                r.get("operator_filename"): r
                for r in summary.get("image_provenance", [])
                if isinstance(r, dict)
            }
            for safe, original in safe_to_orig.items():
                row = rows.get(safe)
                if row is None:
                    ok, detail = False, f"summary missing row for {safe}"
                    break
                want_title = _slide_title_for_name(original)
                if row.get("operator_slide_title") != want_title:
                    ok, detail = False, (
                        f"{safe} operator_slide_title="
                        f"{row.get('operator_slide_title')!r} != seeded "
                        f"{want_title!r}"
                    )
                    break
        results.append(_ProbeResult(
            name=(
                "T40 mapped starter metadata flows end-to-end: "
                "--templates-only --filename-mapping -> --plan -> --resume "
                "builds + re-validates a review package whose summary carries "
                "the original-filename slide_title"
            ),
            ok=ok, detail=detail,
        ))

    repo_rc = _check_repo_unchanged(
        examples_before=examples_before,
        scripts_before=scripts_before,
    )

    print()
    print("--- self-test results ---")
    rc = 0
    for r in results:
        marker = "PASS" if r.ok else "FAIL"
        detail = f" ({r.detail})" if r.detail else ""
        print(f"  [{marker}] {r.name}{detail}")
        if not r.ok:
            rc = 1
    if repo_rc != 0:
        rc = 1
    if rc == 0:
        print()
        print("OK: every self-test probe passed; REPO_ROOT/examples and "
              "REPO_ROOT/scripts byte-identical pre/post; local-only "
              "(no D-One, MCP, Qoder, model API, image search, public "
              "network, or telemetry).")
    return rc


# ---------------------------------------------------------------------------
# CLI entrypoint.
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Operator-facing one-command workflow for the core local "
            "image-to-editable-PPT lane. Takes a caller-supplied "
            "folder of PNG / JPG / JPEG images plus a fresh output "
            "folder outside the repo, copies the images into a local "
            "bundle, writes the manifest + generated-provenance "
            "sidecar templates via the existing operator helper, "
            "drives the helper through the plan-out + approved-plan + "
            "review-package + on-disk re-check loop, and writes a "
            "concise top-level README carrying the EXACT manual "
            "commands run. The same lane can split at a human-review "
            "checkpoint: --plan stages the bundle + reviewable plan and "
            "stops; a human inspects approved_plan.json; --resume builds "
            "the review package from the reviewed plan with the same "
            "validators and evidence. Local-only — does NOT call D-One, "
            "MCP, "
            "Qoder, a public network, telemetry, a model API, an "
            "image search, or any external service. NOT a full "
            "prompt / report / Markdown-to-PPTX automation."
        ),
    )
    parser.add_argument(
        "--images-dir", type=str, default=None,
        help=(
            "Caller-supplied flat folder of PNG / JPG / JPEG bytes. "
            "Direct children must be regular non-symlink files; "
            "subdirectories and symlinks are refused before any byte "
            "is copied. The folder is copied (not moved or linked) "
            "into <out-dir>/bundle/images/ and is never mutated. The "
            "underlying helper's IG1..IG9 gates re-validate extension "
            "/ signature / stem after the copy. Required unless "
            "--self-test is set."
        ),
    )
    parser.add_argument(
        "--out-dir", type=str, default=None,
        help=(
            "Caller-supplied output directory outside the repo tree. "
            "Must not be URI-shaped, a symlink, or have a symlink "
            "ancestor; must not anchor under the repo tree; must have "
            "an existing parent; and must either be missing or an "
            "empty pre-existing directory. On a clean run this script "
            "writes bundle/ (images/ + manifest.json + "
            "generated_provenance.json), approved_plan.json, "
            "review_package/ (deck.pptx, summary.json, inventory.json, "
            "visual_quality.json, workspace/, reports/, README.md), "
            "and a top-level README.md under this directory. In "
            "--resume mode --out-dir instead points at a directory a "
            "prior --plan run already staged."
        ),
    )
    parser.add_argument(
        "--manifest", type=str, default=None,
        help=(
            "Optional caller-supplied reviewed manifest JSON for the "
            "image-folder lane. When supplied, it is staged into the "
            "bundle as bundle/manifest.json IN PLACE OF the default "
            "template, so the produced approved_plan.json and "
            "review_package summary reflect your per-image slide_title / "
            "alt_text / intended_use (and slide order). The path must be "
            "a local, non-URI, non-symlink regular file with no symlink "
            "ancestor; its content is validated by the helper's manifest "
            "contract gates (schema_version='1', the closed four-field "
            "shape, no URL / credential / public-upload / raw-source / "
            "fake-success wording) and its filename set must equal the "
            "copied images exactly. Refused with --resume (the staged "
            "bundle is the source of record). Local file only — no "
            "network / model API / image search."
        ),
    )
    parser.add_argument(
        "--generated-provenance", type=str, default=None,
        help=(
            "Optional caller-supplied reviewed generated-provenance "
            "sidecar JSON for the image-folder lane. When supplied, it "
            "is staged into the bundle as bundle/generated_provenance."
            "json IN PLACE OF the default template, so the produced "
            "approved_plan.json and review_package summary reflect your "
            "per-image generator_source / intent_summary / "
            "placement_role / text_policy / subject_domain. The path "
            "must be a local, non-URI, non-symlink regular file with no "
            "symlink ancestor; its content is validated by the helper's "
            "sidecar contract gates (schema_version='1', the closed "
            "enums, no URL / credential / public-upload / raw-source / "
            "fake-success wording) and its filename set must equal the "
            "copied images exactly. Refused with --resume. Local file "
            "only — no network / model API / image search."
        ),
    )
    parser.add_argument(
        "--plan", action="store_true",
        help=(
            "Plan step of the two-step reviewed flow. Stage the bundle "
            "(copy --images-dir into <out-dir>/bundle/images/), write "
            "the manifest + generated-provenance templates and the "
            "reviewable approved_plan.json, then STOP — no deck.pptx / "
            "review_package/ is built. A human reviews approved_plan."
            "json and runs --resume to continue. Requires --images-dir "
            "+ a fresh --out-dir; mutually exclusive with --resume / "
            "--self-test."
        ),
    )
    parser.add_argument(
        "--resume", action="store_true",
        help=(
            "Resume step of the two-step reviewed flow. Build the "
            "review package from the operator-reviewed approved_plan."
            "json a prior --plan run staged under --out-dir, using the "
            "same approved-plan run lock, validators, and evidence as "
            "one-command mode. Running --resume is the operator's "
            "explicit sign-off that the plan was reviewed. Takes "
            "--out-dir only (the bundle + plan are already staged); "
            "--images-dir is refused. Fails closed if the bundle has "
            "drifted from the approved plan. Mutually exclusive with "
            "--plan / --self-test."
        ),
    )
    parser.add_argument(
        "--templates-only", action="store_true",
        help=(
            "Template-only convenience. Point --images-dir at a local "
            "PNG / JPG / JPEG folder and write JUST two editable starter "
            "metadata files into a fresh --out-dir — manifest.json and "
            "generated_provenance.json (the helper's safe-default "
            "templates the operator can hand-edit). Builds NOTHING else: "
            "no bundle/, no approved_plan.json, no deck.pptx, no "
            "review_package/, no workspace / reports / inventory / "
            "visual_quality. Each file is written by the existing helper's "
            "--write-manifest-template / "
            "--write-generated-provenance-template writers against a "
            "single stable snapshot of the images (copied once so the two "
            "files always agree on the filename set). Edit the two "
            "files, then feed them back via --manifest / "
            "--generated-provenance to a --plan or one-command run. "
            "Optionally pass --filename-mapping (a --prepare-images-only "
            "filename_mapping.json) to seed the manifest's slide_title / "
            "alt_text from each image's ORIGINAL filename instead of the "
            "normalized safe basename. Requires --images-dir + a fresh "
            "--out-dir; mutually exclusive with --plan / --resume / "
            "--self-test / --manifest / --generated-provenance "
            "(--filename-mapping is the only optional companion)."
        ),
    )
    parser.add_argument(
        "--prepare-images-only", action="store_true",
        help=(
            "Prepare convenience for messy real-world image filenames. "
            "Point --images-dir at a local PNG / JPG / JPEG folder whose "
            "names carry spaces / uppercase / parentheses / dots / hyphens "
            "/ CJK characters and copy them into <out-dir>/images/ under "
            "stable, downstream-safe filenames whose stems match the "
            "render_model image_ref contract ^[a-z][a-z0-9_]*$ (lowercased; "
            "a name with no usable ASCII content — a CJK-only name — falls "
            "back to the base img; unique) — the pattern the operator "
            "lane's asset_id (= filename "
            "stem) must satisfy when the deck is built, stricter than the "
            "IG6 --images-dir gate. Then write an inspectable "
            "filename_mapping.json "
            "(original -> safe filename + byte_count / sha256 / media_type "
            "/ extension) and a short README.md. Builds NOTHING heavier: no "
            "bundle/, no approved_plan.json, no review_package/, no "
            "deck.pptx, no workspace / reports. The operator's source "
            "folder is never mutated. Two names that normalise to the same "
            "base stem are disambiguated with a deterministic numeric "
            "suffix (img / img_2 …, my_file / my_file_2) rather than "
            "refused, so a CJK-heavy folder need not be hand-renamed; a "
            "symlink / subdirectory / non-image / hidden entry, an "
            "oversized / over-count folder, or a stem that still violates "
            "the image_ref contract all fail closed before any byte is "
            "copied. Feed the prepared images/ into a "
            "--templates-only / --plan / one-command run. Requires "
            "--images-dir + a fresh --out-dir; mutually exclusive with "
            "--plan / --resume / --templates-only / --self-test / "
            "--manifest / --generated-provenance."
        ),
    )
    parser.add_argument(
        "--filename-mapping", type=str, default=None,
        help=(
            "Optional, ONLY with --templates-only. Path to the "
            "filename_mapping.json a prior --prepare-images-only run wrote "
            "next to the prepared images/. When supplied, the generated "
            "manifest.json's per-image slide_title / alt_text are seeded "
            "from each image's ORIGINAL filename (preserving the spaces / "
            "punctuation / CJK characters that --prepare-images-only "
            "normalized away for safe local storage) instead of the "
            "normalized safe basename, so a deck prepared from messy "
            "real-world filenames keeps human-readable titles. The path "
            "must be a local, non-URI, non-symlink regular file with no "
            "symlink ancestor; the mapping is bound to the prepared image "
            "BYTES (its safe_filename set must equal the prepared images "
            "exactly AND each record's recorded sha256 / byte_count must "
            "match the prepared bytes, else the run fails closed — so a "
            "stale mapping that reuses the same names for different images "
            "is refused), and the re-seeded manifest is re-validated through "
            "the helper's manifest contract gates so an over-long / unsafe "
            "seeded title fails closed. Omit it to keep the prior behavior "
            "(titles derived from the safe basename). Local file only — no "
            "network / model API / image search."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run the in-script tempfixture scenarios under TMPDIR "
            "(no writes under REPO_ROOT). Forty probes: T1 full "
            "happy path from synthetic --images-dir through to a "
            "validated review package + locked README markers; T2 "
            "drift (mutating generated_provenance.json after plan-"
            "out must fail the approved-plan run before ANY canonical "
            "review-package artifact is materialised); T3 copy-stage "
            "bounds (per-file MAX_BYTES_PER_FILE cap + MAX_IMAGES "
            "count cap refuse oversized / over-count inputs before "
            "any byte is copied); T4 shell-safe README quoting (the "
            "workflow runs under a path with whitespace + apostrophe "
            "and the rendered Stage-4 command re-parses via "
            "shlex.split as a single argv); T5 copy-stage filesystem "
            "error (a pre-existing bundle_images returns a tagged "
            "failure list rather than an uncaught traceback); T6 "
            "non-image extension (a stray .txt file alongside valid "
            "PNG + JPEG refuses BEFORE any byte is copied via the "
            "wrapper's IG5-parallel extension filter); T7 race-safe "
            "copy refuses a symlink at open time via O_NOFOLLOW so a "
            "TOCTOU swap between the pre-flight is_symlink check "
            "and the copy still fails closed; T8 race-safe copy "
            "refuses a FIFO / device / socket via stat.S_ISREG on "
            "the opened fd (O_NOFOLLOW alone only blocks symlinks; "
            "O_NONBLOCK keeps the FIFO open from hanging); T9 "
            "bounded copy refuses a source that produces more "
            "bytes than MAX_BYTES_PER_FILE during the read loop "
            "(closes the fstat-bypass a concurrent appender could "
            "otherwise exploit); T10 case-fold ancestor check "
            "refuses a case-variant --out-dir that resolves under "
            "REPO_ROOT on a case-insensitive filesystem (the "
            "helper's raw-string relative_to check would miss "
            "this bypass on macOS APFS / Windows NTFS); T11 "
            "relative --images-dir / --out-dir from a non-REPO_ROOT "
            "cwd produce the review package at the operator-"
            "intended path (the helper subprocesses run with "
            "cwd=REPO_ROOT, so main() resolves both args to "
            "absolute paths first); T12 cross-containment refusal "
            "between --images-dir and --out-dir uses the case-fold "
            "ancestor check (parallel to T10) so a case-variant "
            "out-dir under images-dir is refused on case-"
            "insensitive filesystems; T13 a hidden .DS_Store dotfile "
            "(macOS Finder's invisible metadata file, the most "
            "common real-world contaminant of an operator image "
            "folder) is refused before any byte is copied with an "
            "operator-facing macOS-aware message and a non-"
            "destructive `ls -a` reveal command, not the generic "
            "`has extension ''` line; T14 a torn run that fails AFTER "
            "the bundle is staged (a .png whose bytes fail the "
            "helper's IG8 signature check) emits a recovery NOTE "
            "naming --out-dir + an `rm -rf` retry path so the operator "
            "is not blindsided by the shared --out-dir gate's "
            "non-empty refusal on re-run; T15 --plan stages the "
            "reviewable plan + templates and emits NO PPTX / "
            "review_package (it stops at the human-review checkpoint); "
            "T16 --resume builds the same canonical review package + "
            "approved-plan evidence as one-command mode from a valid "
            "reviewed plan; T17 --resume refuses mutated source bytes "
            "(a bundle image edited after plan-out drifts the rebuilt "
            "plan and the approved-plan run lock fails closed before any "
            "artifact); T18 --resume refuses missing / mismatched "
            "generated provenance (deleting or editing "
            "generated_provenance.json after plan-out drifts the plan); "
            "T19 --resume refuses a path-traversal --out-dir (URI-shaped "
            "and under-REPO_ROOT) at the gate with rc 2 and no "
            "filesystem mutation; T20 --resume refuses symlink inputs "
            "(an --out-dir that is a symlink, one with a symlink "
            "ancestor, and a staged approved_plan.json swapped for a "
            "symlink); T21 a valid operator-supplied --manifest + "
            "--generated-provenance are accepted and the custom "
            "slide_title / intent_summary flow into approved_plan.json + "
            "summary.json (and the workflow README records the staging "
            "instead of a template-write command); T22 a supplied "
            "manifest whose filename set != the copied images is rejected "
            "with no review package; T23 a URI-shaped / symlinked "
            "metadata path is refused at the CLI gate (rc 2) before any "
            "staging; T24 unsafe public / network / credential / "
            "raw-source wording in a supplied manifest OR sidecar field "
            "is rejected; T25 the two-step --plan/--resume flow works "
            "with supplied metadata (custom values flow into the plan "
            "then the summary); T26 the default no-metadata path is "
            "unchanged (the bundle manifest stays byte-identical to the "
            "helper template and the README shows the template-write "
            "command); T27 --templates-only writes ONLY the two editable "
            "starter metadata files (manifest.json + "
            "generated_provenance.json) into a fresh --out-dir from a "
            "single stable image snapshot, builds nothing else, and both "
            "files parse as JSON, agree on the filename set, and pass the "
            "helper's manifest / sidecar validators; T28 --templates-only "
            "refuses --manifest / --plan combinations at the gate (rc 2, "
            "no --out-dir created); T29 --prepare-images-only normalises a "
            "folder of messy filenames (spaces / parentheses / uppercase / "
            "CJK) into stable safe names, writes a complete "
            "filename_mapping.json (original -> safe + byte_count / sha256 / "
            "media_type / extension), produces only images/ + mapping + "
            "README, and the prepared images/ feeds --templates-only; T30 "
            "--prepare-images-only disambiguates a post-normalisation "
            "base-stem collision (two distinct names sharing a base stem, "
            "e.g. My File.png / my_file.png) into distinct names with a "
            "deterministic numeric suffix (my_file / my_file_2) rather than "
            "refusing; T31 --prepare-images-only "
            "refuses unsafe entries (per-file symlink, non-image file) "
            "before any byte is copied; T32 --prepare-images-only refuses "
            "--plan / --templates-only / --manifest combinations at the "
            "gate (rc 2, no --out-dir created); T33 the prepared images/ "
            "(safe names from messy originals with dots / hyphens / a "
            "leading digit and a CJK-only name) build a full review package "
            "end-to-end via the one-command workflow, proving the safe stems "
            "satisfy the render_model image_ref contract ^[a-z][a-z0-9_]*$ "
            "(not just the looser IG6 gate); T34 multiple CJK-only filenames "
            "map to distinct image_ref-valid names (img / img_2 / img_3) "
            "deterministically; T35 mixed CJK + ASCII filenames keep their "
            "ASCII run in the safe stem; T36 --templates-only "
            "--filename-mapping seeds slide_title / alt_text from original "
            "filenames carrying spaces + punctuation (not the safe basename); "
            "T37 the same seeding restores CJK / non-ASCII original filenames "
            "(the safe basename is bland ASCII); T38 WITHOUT --filename-mapping "
            "the prior safe-basename titles are preserved (the option is "
            "additive); T39 --filename-mapping fails closed on a mismatched "
            "safe-name set (rc 1, no seeded title), outside --templates-only "
            "(rc 2), on a URI-shaped path (rc 2), and on a mapping bound to "
            "different bytes (matching names but wrong sha256, rc 1 — the "
            "mapping is bound to the prepared bytes, not just the names); T40 "
            "mapped starter metadata flows end-to-end "
            "(--templates-only --filename-mapping -> --plan -> --resume) into "
            "a re-validated review package whose summary carries the "
            "original-filename slide_title. Mutually exclusive with "
            "--images-dir / --out-dir / --manifest / --generated-provenance "
            "/ --plan / --resume / --templates-only / --prepare-images-only / "
            "--filename-mapping."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if (args.images_dir is not None or args.out_dir is not None
                or args.manifest is not None
                or args.generated_provenance is not None
                or args.plan or args.resume or args.templates_only
                or args.prepare_images_only
                or args.filename_mapping is not None):
            print(
                "FAIL: --self-test is mutually exclusive with "
                "--images-dir / --out-dir / --manifest / "
                "--generated-provenance / --plan / --resume / "
                "--templates-only / --prepare-images-only / "
                "--filename-mapping.",
                file=sys.stderr,
            )
            return 2
        return _run_self_tests()

    if args.plan and args.resume:
        print(
            "FAIL: --plan and --resume are mutually exclusive; --plan "
            "stages the reviewable plan and stops, --resume builds the "
            "review package from an already-reviewed plan.",
            file=sys.stderr,
        )
        return 2

    # --templates-only writes ONLY the two editable starter metadata
    # files (manifest.json + generated_provenance.json) from --images-dir
    # into a fresh --out-dir and builds nothing else. It shares the
    # images-dir / out-dir gate below with plan / one-command mode, so
    # refuse the modes / inputs it must not combine with here first —
    # before the resume branch and the shared gate run.
    if args.templates_only and (
        args.plan or args.resume
        or args.manifest is not None
        or args.generated_provenance is not None
    ):
        print(
            "FAIL: --templates-only only writes starter manifest / "
            "generated_provenance templates from --images-dir into a "
            "fresh --out-dir; it is mutually exclusive with --plan / "
            "--resume / --manifest / --generated-provenance (those "
            "supply reviewed metadata to, or drive, a build run).",
            file=sys.stderr,
        )
        return 2

    # --prepare-images-only copies --images-dir into <out-dir>/images/ under
    # safe filenames + writes filename_mapping.json / README.md and builds
    # nothing else. Like --templates-only it shares the images-dir / out-dir
    # gate below, so refuse the modes / inputs it must not combine with here
    # first — before the resume branch and the shared gate run.
    if args.prepare_images_only and (
        args.plan or args.resume or args.templates_only
        or args.manifest is not None
        or args.generated_provenance is not None
    ):
        print(
            "FAIL: --prepare-images-only only copies --images-dir into "
            "<out-dir>/images/ under safe filenames and writes "
            "filename_mapping.json + README.md; it is mutually exclusive "
            "with --plan / --resume / --templates-only / --manifest / "
            "--generated-provenance (those drive, or supply metadata to, a "
            "later build run). Prepare first, then feed the prepared "
            "images/ into one of those modes.",
            file=sys.stderr,
        )
        return 2

    # --filename-mapping only makes sense for --templates-only: it re-seeds
    # the generated manifest's slide_title / alt_text from each prepared
    # image's ORIGINAL filename. The build modes (one-command / --plan /
    # --resume) consume a reviewed manifest via --manifest, not a starter
    # template, so a mapping there has nothing to seed; --prepare-images-only
    # produces the mapping rather than consuming it. Refuse the combination
    # at the gate (before the resume branch and the shared gate run).
    if args.filename_mapping is not None and not args.templates_only:
        print(
            "FAIL: --filename-mapping is only valid with --templates-only "
            "(it seeds the generated manifest's slide_title / alt_text from "
            "the prepared images' original filenames). Run --prepare-images-"
            "only to write the mapping, then pass it to a --templates-only "
            "run; build modes consume a reviewed manifest via --manifest.",
            file=sys.stderr,
        )
        return 2

    # Resume mode: build the review package from an already-staged,
    # operator-reviewed plan. Takes --out-dir only — the bundle + plan
    # were staged by a prior --plan run, and --images-dir is refused so
    # the source of record is unambiguously the staged bundle.
    if args.resume:
        if args.images_dir is not None:
            print(
                "FAIL: --resume rebuilds from the staged bundle; do not "
                "pass --images-dir. Pass only --out-dir pointing at a "
                "directory a prior --plan run staged.",
                file=sys.stderr,
            )
            return 2
        if (args.manifest is not None
                or args.generated_provenance is not None):
            print(
                "FAIL: --resume rebuilds from the already-staged bundle "
                "metadata; do not pass --manifest / "
                "--generated-provenance. Supply custom metadata at "
                "--plan time (it is staged into the bundle then); "
                "--resume only consumes what --plan staged.",
                file=sys.stderr,
            )
            return 2
        if args.out_dir is None:
            print(
                "FAIL: --resume requires --out-dir (the directory a "
                "prior --plan run staged).",
                file=sys.stderr,
            )
            return 2
        out_dir, out_failures = _validate_resume_out_dir_arg(args.out_dir)
        if out_failures or out_dir is None:
            for line in out_failures:
                print(f"FAIL: {line}", file=sys.stderr)
            return 2
        try:
            out_dir = out_dir.resolve(strict=False)
        except OSError as exc:
            print(
                f"FAIL: could not resolve --out-dir to an absolute "
                f"path: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 2
        # Same belt-and-braces case-fold REPO_ROOT refusal the fresh
        # gate applies — the raw-string relative_to check in
        # _validate_resume_out_dir_arg misses case-variant paths on a
        # case-insensitive filesystem (macOS APFS / Windows NTFS).
        if _resolves_under_casefold(out_dir, REPO_ROOT):
            print(
                f"FAIL: --out-dir {out_dir} resolves under REPO_ROOT "
                f"{REPO_ROOT} after case-folding; refused.",
                file=sys.stderr,
            )
            return 2
        return _run_resume_mode(out_dir=out_dir)

    # Plan mode and one-command mode both stage from --images-dir into a
    # fresh --out-dir, so they share the full argument gate below.
    if args.images_dir is None or args.out_dir is None:
        print(
            "FAIL: --images-dir and --out-dir are both required "
            "(use --self-test for the in-script fixture).",
            file=sys.stderr,
        )
        return 2

    images_dir, image_failures = _validate_images_dir_arg(args.images_dir)
    if image_failures or images_dir is None:
        for line in image_failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 2

    out_dir, out_failures = _validate_out_dir_arg(args.out_dir)
    if out_failures or out_dir is None:
        for line in out_failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 2

    # Resolve both args to absolute paths BEFORE any subprocess call.
    # The helper subprocesses run with ``cwd=REPO_ROOT``, so a
    # relative ``--images-dir`` / ``--out-dir`` argument would be
    # interpreted relative to REPO_ROOT (not the caller's cwd), and
    # the helper would either fail to find the operator's folder or
    # try to write outside the intended location. Codex caught this
    # gap. ``Path.resolve(strict=False)`` resolves against the
    # script's current cwd (which is the caller's cwd at invocation
    # time), so subsequent string-conversions land as absolute
    # paths regardless of the subprocess's working directory.
    try:
        images_dir = images_dir.resolve(strict=False)
        out_dir = out_dir.resolve(strict=False)
    except OSError as exc:
        print(
            f"FAIL: could not resolve --images-dir / --out-dir to "
            f"absolute paths: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    # Belt-and-braces case-fold ancestor check on top of the helper's
    # ``_validate_out_dir_arg``. The helper's gate compares
    # ``resolved.relative_to(repo_root)`` as raw strings, which is
    # correct on case-sensitive filesystems (typical Linux) but
    # silently MISSES case-variant paths on case-insensitive
    # filesystems (macOS APFS / Windows NTFS in their default modes).
    # For example, ``--out-dir /USERS/robert/Desktop/project/szh-ppt-
    # master/leak`` resolves to a path whose raw string does NOT
    # have REPO_ROOT as a prefix, so ``relative_to`` raises and the
    # helper's gate decides the path is "outside the repo" — yet
    # the bytes physically land inside the committed repo tree
    # because the filesystem normalises case at the inode lookup
    # layer. Codex caught this gap.
    if _resolves_under_casefold(out_dir, REPO_ROOT):
        print(
            f"FAIL: --out-dir {out_dir} resolves under REPO_ROOT "
            f"{REPO_ROOT} after case-folding; refused — on a "
            f"case-insensitive filesystem (macOS APFS / Windows "
            f"NTFS in default mode) the raw-string relative_to "
            f"check the helper applies could otherwise miss this "
            f"bypass.",
            file=sys.stderr,
        )
        return 2

    # Refuse cross-containment so a typo cannot point one argument
    # under the other (which would either mutate the source folder
    # mid-run or pollute the output folder with the source bytes).
    # Uses ``_resolves_under_casefold`` rather than the raw-string
    # ``relative_to`` check the earlier version applied: on a
    # case-insensitive filesystem (macOS APFS / Windows NTFS in
    # default mode) a case-variant ``--out-dir /TMP/IMGS/output``
    # against ``--images-dir /tmp/imgs`` would resolve to the same
    # subtree as the images-dir but ``Path.relative_to`` compares
    # raw strings and would miss the bypass. Codex caught this
    # parallel-to-T10 gap. The case-fold check below closes it.
    case_fold_same = (
        _resolves_under_casefold(images_dir, out_dir)
        and _resolves_under_casefold(out_dir, images_dir)
    )
    if case_fold_same:
        print(
            f"FAIL: --images-dir ({images_dir}) and --out-dir "
            f"({out_dir}) resolve to the same path (case-folded); "
            f"refused.",
            file=sys.stderr,
        )
        return 2
    if _resolves_under_casefold(images_dir, out_dir):
        print(
            f"FAIL: --images-dir ({images_dir}) is inside --out-dir "
            f"({out_dir}) after case-folding; refused so the "
            f"workflow cannot copy the source bytes back over "
            f"themselves.",
            file=sys.stderr,
        )
        return 2
    if _resolves_under_casefold(out_dir, images_dir):
        print(
            f"FAIL: --out-dir ({out_dir}) is inside --images-dir "
            f"({images_dir}) after case-folding; refused so the "
            f"workflow cannot pollute the operator's source folder "
            f"with its own output.",
            file=sys.stderr,
        )
        return 2

    # Gate any operator-supplied metadata path BEFORE creating --out-dir,
    # so an obviously unsafe --manifest / --generated-provenance fails
    # closed with rc 2 without staging a single byte. Only the cheap
    # path-safety subset runs here; the full content contract (JSON /
    # schema / unsafe-wording / filename-set match) is enforced by the
    # helper's own validators once the copied image basenames are known.
    manifest_src: Path | None = None
    gen_prov_src: Path | None = None
    for raw, flag in (
        (args.manifest, "--manifest"),
        (args.generated_provenance, "--generated-provenance"),
    ):
        if raw is None:
            continue
        meta, meta_failures = _validate_metadata_arg(raw, flag)
        if meta_failures or meta is None:
            for line in meta_failures:
                print(f"FAIL: {line}", file=sys.stderr)
            return 2
        try:
            meta = meta.resolve(strict=False)
        except OSError as exc:
            print(
                f"FAIL: could not resolve {flag} to an absolute path: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 2
        if flag == "--manifest":
            manifest_src = meta
        else:
            gen_prov_src = meta

    # Gate the optional --filename-mapping path with the same cheap
    # path-safety subset (URI / symlink / symlink-ancestor / missing /
    # non-file). It is only reachable with --templates-only (the guard
    # above refuses every other mode), so a bad mapping path fails closed
    # with rc 2 before --out-dir is created. The deeper content contract
    # (JSON parse, the prepare-mapping shape, and the safe_filename-set ==
    # prepared-images cross-check) is enforced by
    # _seed_manifest_titles_from_mapping once the snapshot basenames are
    # known.
    mapping_src: Path | None = None
    if args.filename_mapping is not None:
        mapping_meta, mapping_failures = _validate_metadata_arg(
            args.filename_mapping, "--filename-mapping",
        )
        if mapping_failures or mapping_meta is None:
            for line in mapping_failures:
                print(f"FAIL: {line}", file=sys.stderr)
            return 2
        try:
            mapping_src = mapping_meta.resolve(strict=False)
        except OSError as exc:
            print(
                f"FAIL: could not resolve --filename-mapping to an "
                f"absolute path: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
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

    if args.templates_only:
        # manifest_src / gen_prov_src are always None here (the guard
        # above refuses --templates-only + --manifest / --generated-
        # provenance), so the shared metadata gate was a no-op.
        # mapping_src is the only optional input templates-only accepts.
        rc = _run_templates_only(
            images_dir=images_dir, out_dir=out_dir, mapping_src=mapping_src,
        )
    elif args.prepare_images_only:
        # manifest_src / gen_prov_src are always None here (the guard above
        # refuses --prepare-images-only + --manifest / --generated-
        # provenance), so the shared metadata gate was a no-op.
        rc = _run_prepare_images_only(images_dir=images_dir, out_dir=out_dir)
    elif args.plan:
        rc = _run_plan_mode(
            images_dir=images_dir, out_dir=out_dir,
            manifest_src=manifest_src, gen_prov_src=gen_prov_src,
        )
    else:
        rc = _run_workflow(
            images_dir=images_dir, out_dir=out_dir,
            manifest_src=manifest_src, gen_prov_src=gen_prov_src,
        )
    if rc != 0:
        _print_torn_run_recovery_hint(out_dir)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
