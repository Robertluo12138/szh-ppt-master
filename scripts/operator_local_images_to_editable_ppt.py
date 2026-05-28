#!/usr/bin/env python3
"""operator_local_images_to_editable_ppt.py

Operator-facing **local-image intake** helper for the core image-to-
editable-PPT lane. The next operator step after
``scripts/core_image_to_editable_ppt_demo.py --out-dir DIR`` for a
reviewer who has a folder of their OWN local PNG / JPG / JPEG bytes and
wants to prove those bytes can flow through the existing local image
asset pipeline into a native editable PPTX with inventory + provenance
evidence.

Four modes share one helper:

  * ``--images-dir DIR --out-dir OUT [--manifest PATH]`` — **operator
    mode**: takes a caller-supplied flat directory of PNG / JPG / JPEG
    image files plus a caller-supplied output directory that lives
    **outside the repo tree**, plus the OPTIONAL ``--manifest PATH``
    naming per-image slide intent. Discovers the image files
    deterministically (filename-sorted when ``--manifest`` is omitted;
    reordered to manifest array order when supplied), generates the
    smallest viable pipeline fixture (one cover slide per image, native
    title + image_slot accent — with the operator-typed slide_title /
    alt_text / intended_use flowing through verbatim when
    ``--manifest`` is supplied), invokes
    ``scripts/run_explicit_pipeline.py`` with ``--theme-from-template``
    + ``--assets-dir <staged>`` so the existing Stage-5.5 materialize
    step copies the bytes into the workspace, then runs every existing
    validator (``validate_source_image_assets``,
    ``validate_pptx_contract --expected-slide-count N``,
    ``inspect_pptx_inventory``, ``validate_visual_quality``) against
    the produced workspace + PPTX and writes a compact ``summary.json``
    + a per-image provenance map
    naming the operator filename, the workspace path the bytes landed
    at, the sha256, the embedded ``ppt/media/*`` part, and (when
    ``--manifest`` was supplied) the operator-typed slide_title /
    alt_text / intended_use. On a truth-checked happy run the helper
    additionally writes a concise operator-facing ``README.md`` to
    ``<out-dir>`` that names the produced artifacts, points reviewers
    at ``summary.image_provenance[]`` for filename -> sha256 -> ppt/media
    part -> intended/readback slide evidence, and echoes the fixed
    local-only boundary statement. Leaves every intermediate artifact
    on disk under OUT for a reviewer to inspect.

  * ``--images-dir DIR --write-manifest-template PATH`` — **manifest-
    template writer mode**: discovers the same flat PNG / JPG / JPEG
    folder operator mode uses (reuses the IG1..IG9 gate verbatim),
    then writes a starter JSON manifest at PATH whose ``images[]``
    array carries one entry per discovered image, sorted by filename,
    using the same deterministic default ``slide_title`` /
    ``alt_text`` / ``intended_use`` values the helper would apply if
    ``--manifest`` were omitted. The template writer does NOT run the
    pipeline, does NOT produce a PPTX, does NOT produce a
    ``visual_quality.json`` report (the visual-quality validator only
    runs in normal operator mode against a produced workspace), does
    NOT write anywhere under ``REPO_ROOT`` (MT4 refuses the argument
    outright), and does NOT call D-One / MCP / Qoder / a public
    network / a model API / an image search / telemetry. The
    generated file is byte-compatible
    with operator-mode ``--manifest`` input: a re-run such as
    ``--images-dir DIR --out-dir OUT --manifest <this-path>`` accepts
    the template verbatim and the produced summary echoes the
    template's slide_title / alt_text / intended_use under
    ``image_provenance[]`` exactly as for a hand-authored manifest.

  * ``--images-dir DIR --plan-out PATH [--manifest PATH]`` — **plan-
    only preflight writer mode**: discovers the same flat PNG / JPG /
    JPEG folder operator mode uses (reuses the IG1..IG9 gate
    verbatim), validates the optional ``--manifest`` against
    MAN1..MAN12 when supplied, then writes a compact deterministic
    JSON plan at PATH whose ``images[]`` rows carry per-image
    filename / asset_id / media_type / byte_count / sha256 / intended
    1-based slide index / slide_title / alt_text / intended_use, in
    manifest-array order when ``--manifest`` is supplied or filename-
    sorted order otherwise. The plan-only mode does NOT run
    ``run_explicit_pipeline.py``, does NOT produce a PPTX, does NOT
    produce a workspace / inventory / visual_quality / summary /
    ``_pipeline_fixture`` artifact, does NOT write anywhere under
    ``REPO_ROOT`` (PO4 refuses the argument outright), and does NOT
    call D-One / MCP / Qoder / a public network / a model API / an
    image search / telemetry. The plan path gate (PO1..PO6) mirrors
    the manifest-template gate (MT1..MT6): URI, symlink, symlink
    ancestor, REPO_ROOT anchor, missing / non-directory parent, and
    pre-existing target are all refused; stale bytes on a
    pre-existing target are preserved.

  * ``--self-test`` — drives the same happy paths inside per-run
    ``tempfile.TemporaryDirectory()`` instances using two tiny
    generated PNG / JPEG fixtures (no committed bytes; nothing leaks
    under REPO_ROOT) and exercises every documented fail-closed probe.

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
  * ``scripts/validate_visual_quality.py`` — inspection-only
    post-pipeline review over the produced workspace's
    ``render_models/`` + ``svg_previews/`` pair; the helper invokes
    it with ``--output <out-dir>/visual_quality.json`` and the JSON
    report's ``totals.errors`` / ``totals.warnings`` flow into
    ``summary.visual_quality`` (warnings allowed; errors / non-zero
    rc / missing-or-malformed report refuse via the truth-check);
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

  MAN1..MAN12 (only when ``--manifest`` is supplied)
        the manifest path is not URI-shaped (MAN1), is not a symlink
        (MAN2), has no symlink ancestor (MAN3), exists as a regular
        file (MAN4), parses as a single UTF-8 JSON object (MAN5),
        carries exactly the required root keys (MAN6) with
        ``schema_version == "1"`` (MAN7), names a non-empty
        ``images`` array (MAN8) of objects with EXACTLY the four
        required fields filename / slide_title / alt_text /
        intended_use (MAN9), each field passes the safe-string gates
        (MAN10 — type, length, whitespace, control char, URL / URI,
        path separator, credential / token / API-key shape, public
        upload / share / hosting wording, raw-source / confidential /
        customer marker, positive D-One / MCP / Qoder / model API /
        image search / network / telemetry success claim), no
        filename appears twice (MAN11), and the manifest filename
        set equals the discovered filename set (MAN12).

  MT1..MT6 (only when ``--write-manifest-template`` is supplied)
        the template path is not URI-shaped (MT1), is not a symlink
        (MT2), has no symlink ancestor (MT3), does not lexically
        anchor under ``REPO_ROOT`` (MT4), has an existing directory
        parent (MT5), and does not already exist (MT6 — the writer
        never overwrites operator files).

After the pipeline run, the helper additionally runs the existing
``validate_source_image_assets`` validator against a freshly-authored
``<workspace>/source_image_assets.json`` registry (PNG / JPG / JPEG
classes only, every entry source-class ``local_asset``, source_ref =
``operator_local_images_source``), then ``validate_pptx_contract
--expected-slide-count N`` and ``inspect_pptx_inventory`` against the
produced ``.pptx``, and finally ``validate_visual_quality`` against the
produced workspace's ``render_models/`` + ``svg_previews/`` pair with
``--output <out-dir>/visual_quality.json``. The first three abort with
a clear diagnostic on non-zero exit; ``validate_visual_quality`` runs
to completion (so the JSON report it writes before a per-slide ERROR
return is preserved for inspection) and the summary truth-check
refuses on non-zero rc / missing or malformed report / error_count > 0.
Warning findings do NOT refuse the run. Partial artifacts stay on disk
for the operator to inspect on every failure path.

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
    "media_type", "byte_count", "embedded_media_parts",
    "intended_slide_index", "embedded_referencing_slides",
    "placement_verified" }``, plus (only when ``--manifest`` was
    supplied) ``operator_slide_title``, ``operator_alt_text``,
    ``operator_intended_use``. The ``embedded_media_parts`` field is
    the sorted list of ``ppt/media/*`` parts whose sha256 equals the
    operator file's sha256, so a reviewer can trace each operator
    filename straight to its embedded PPTX part.
    ``intended_slide_index`` is the 1-based deck position the helper
    assigned to this operator filename (manifest array order when
    ``--manifest`` was supplied, filename-sorted order otherwise);
    ``embedded_referencing_slides`` is the sorted union of the
    1-based slide indices whose ``<a:blip r:embed>`` resolves to one
    of the operator's ``ppt/media/*`` parts according to
    ``inspect_pptx_inventory.slides[*].media_refs[*]`` filtered to
    entries whose ``used_by_slide_blip`` is True (deliberately
    blip-confirmed, NOT the inventory's rels-only
    ``media_parts[*].referencing_slides`` — a slide whose rels file
    declares an image rel but whose ``<p:pic>`` body does not embed
    it would false-green a placement check otherwise; this mirrors
    the sibling ``image_placement_readback_smoke`` H4b blip-embed
    gate); ``placement_verified`` is True iff ``intended_slide_index``
    is in ``embedded_referencing_slides`` (the truth-checker refuses
    on a False so a misplaced operator image fails closed).
  * ``manifest_path`` — absolute (or caller-typed) path to the
    operator manifest when ``--manifest`` was supplied; ``null``
    otherwise.
  * ``pptx_path`` — absolute path inside ``--out-dir``.
  * ``workspace_path`` / ``report_dir`` / ``inventory_path`` /
    ``registry_path`` — absolute paths inside ``--out-dir``.
  * ``validators`` — ``{validate_source_image_assets.rc,
    validate_pptx_contract.rc, inspect_pptx_inventory.rc,
    validate_visual_quality.rc}``.
  * ``visual_quality`` — small stable block surfacing the
    ``validate_visual_quality`` outcome and parsed report: ``rc`` is
    the validator's exit code, ``path`` is the JSON report path
    (``<out-dir>/visual_quality.json``), ``report_parsed`` is True iff
    the report file exists, parses as a JSON object, and carries
    integer ``totals.errors`` / ``totals.warnings`` (False routes
    through the truth-checker as a refusal), ``error_count`` /
    ``warning_count`` are the projected totals (``null`` when
    ``report_parsed`` is False). The truth-checker refuses the run on
    any of: non-zero ``rc``, ``report_parsed`` False, ``error_count``
    not zero. Warnings (``warning_count > 0``) are allowed.
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
      --images-dir DIR --out-dir OUT [--manifest PATH]

  python3 scripts/operator_local_images_to_editable_ppt.py \\
      --images-dir DIR --write-manifest-template PATH

  python3 scripts/operator_local_images_to_editable_ppt.py \\
      --images-dir DIR --plan-out PATH [--manifest PATH]

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
from dataclasses import dataclass, replace  # noqa: E402
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
VALIDATE_VISUAL_QUALITY = SCRIPTS_DIR / "validate_visual_quality.py"

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

# Fixed single-sentence boundary statement embedded verbatim in the
# operator-facing README written under --out-dir. Concentrates the same
# negation-pinned wording the locked _EXPLICIT_BOUNDARIES tuple already
# carries so a reviewer who reads only the README sees the same scope
# the summary truth-checker enforces.
_README_BOUNDARY_STATEMENT = (
    "Local-only — real D-One is UNVERIFIED; this helper does NOT call "
    "MCP, Qoder, a public network, a model API, an image search, or "
    "telemetry, and is NOT a prompt or report-to-PPT automation."
)

_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Known-dangerous single-colon URI schemes (no ``//`` required). The
# ``://`` substring check + ``_URI_SCHEME_PREFIX`` (anchored to string
# start) miss these when they appear mid-text — ``"generated, see
# data:image/png;base64,..."`` / ``"contact: mailto:ops@example"`` /
# ``"file:/etc/passwd reference"`` / ``"javascript:alert(1) payload"``
# would all slip past the safe-string scan and only land in the
# produced summary.json, where the review-package validator's text
# scan would catch them belatedly. The boundary should refuse at the
# operator entry point, not just on re-validation. Each scheme must
# be followed by a non-whitespace / non-quote / non-bracket char so
# ordinary prose like ``"Time is 10:30"`` / ``"Note: foo"`` does not
# false-positive. Mirrors the validator-side
# ``_DANGEROUS_URI_SCHEMES`` tuple verbatim so the entry-side gate
# and the re-validation gate refuse the same shapes.
_DANGEROUS_URI_SCHEMES: tuple[str, ...] = (
    "data",
    "file",
    "javascript",
    "vbscript",
    "mailto",
    "tel",
    "urn",
    "gopher",
    "ssh",
    "git",
    "ftp",
    "sftp",
    "ws",
    "wss",
    "view-source",
    "chrome-extension",
    "intent",
    "jdbc",
    "dict",
    "ldap",
    "ldaps",
    "imap",
    "pop",
    "smtp",
    "telnet",
    "rsync",
    "feed",
    "afp",
    "smb",
    "nfs",
)
_DANGEROUS_URI_SCHEME_REGEX = re.compile(
    r"\b(?P<scheme>"
    + "|".join(re.escape(s) for s in _DANGEROUS_URI_SCHEMES)
    + r"):[^\s\"'<>)\]}]",
    re.IGNORECASE,
)

# Lowercase-hex 64-character sha256 pattern, used by the truth-checker
# to validate the approved_plan evidence block so reviewers can pipe
# the recorded digest to ``sha256sum`` without parsing variations.
_SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}")

# Sentinel object distinct from ``None`` so the truth-checker can tell
# a missing summary key (refused — a tampered summary cannot silently
# erase the lock) from an explicit null value (accepted — the run was
# not approved-plan-locked).
_MISSING = object()


# ---------------------------------------------------------------------------
# Optional --manifest validation.
# ---------------------------------------------------------------------------

# Optional caller-supplied local JSON manifest that names per-image
# slide intent (order, slide_title, alt_text, intended_use). When the
# operator omits --manifest the helper preserves its deterministic
# filename-sort ordering AND its built-in default strings verbatim;
# when the operator supplies --manifest the helper uses the manifest's
# array order as the deck slide order and routes the per-entry strings
# into the native editable slide title (slide_title) and the generated
# image_manifest's alt_text / intended_use fields. The manifest itself
# is NEVER written to the produced deck; only the per-entry strings
# flow through, and the summary echoes them under image_provenance for
# a reviewer to trace each embedded ppt/media part back to the
# manifest entry that ordered + labelled it.
_MANIFEST_SCHEMA_VERSION = "1"
_MANIFEST_REQUIRED_ROOT_KEYS: tuple[str, ...] = (
    "images", "schema_version",
)
_MANIFEST_IMAGE_REQUIRED_KEYS: tuple[str, ...] = (
    "alt_text", "filename", "intended_use", "slide_title",
)

_MAX_FILENAME_LEN = 128
_MAX_SLIDE_TITLE_LEN = 120
_MAX_ALT_TEXT_LEN = 300
_MAX_INTENDED_USE_LEN = 120

# Denied substrings for every manifest free-text field. All checks
# are case-insensitive against the stripped lower-cased string. The
# fields are local-only operator deck metadata — they must not carry
# credentials, network identifiers / public hosting wording, raw
# confidential or customer markers, or positive success claims for
# upstream services this lane does NOT call. Each category emits a
# distinct diagnostic so the operator can rename / re-phrase the
# offending field without guessing which gate fired.
_DENY_CREDENTIAL: tuple[str, ...] = (
    "api_key", "api-key", "apikey",
    "secret_key", "secret-key", "client_secret",
    "private_key", "access_key", "access-key",
    "x-api-key", "password", "passwd",
    "bearer ", "authorization:",
    "auth_token", "auth-token",
    "access_token", "access-token",
)

# OpenAI-style API key prefix (sk-XXXX...). The bounded
# {16,} length avoids collisions with short benign tokens that
# happen to begin with "sk-" (e.g. "sk-1" embedded in a phrase).
_OPENAI_KEY_REGEX = re.compile(r"\bsk-[A-Za-z0-9]{16,}\b")

_DENY_UPLOAD: tuple[str, ...] = (
    "upload to", "uploaded to", "share to", "shared to",
    "publish to", "published to", "hosted on", "host on",
    "s3://", "gs://", "azure blob",
    "google drive", "dropbox", "onedrive",
    "public url", "amazonaws", "googleusercontent",
    "githubusercontent", "imgur", "flickr",
    # Distribution-channel phrases. The regex below catches most
    # public-share / public-hosting shapes; these substrings
    # additionally lock specific well-known phrases the regex would
    # otherwise have to enumerate as alternations.
    "public domain", "on social media",
    # Social-media platform names. Their presence in operator
    # metadata reveals a public-distribution channel for the deck's
    # image bytes — refused regardless of surrounding wording so
    # "posted on twitter" / "instagram-style export" / "share on
    # linkedin" all trip without alt 14/15 having to enumerate every
    # provider name. Marginal benign uses ("instagram-style filter")
    # are refused by design; the operator can rephrase the metadata.
    "twitter", "instagram", "facebook", "linkedin",
    "reddit", "tiktok", "youtube", "mastodon",
    "threads.net", "bluesky", "tumblr", "pinterest",
    "snapchat",
)

# Public-share / public-hosting wording that the substring list above
# does NOT catch on its own. The substring tokens lock specific
# provider-named phrasings ("upload to <provider>", "share to <name>"),
# a couple of high-signal noun phrases ("public domain",
# "on social media"), AND the bare social-media platform names
# (twitter, instagram, facebook, linkedin, reddit, tiktok, youtube,
# mastodon, threads.net, bluesky, tumblr, pinterest, snapchat) so
# "posted on twitter" / "shared on linkedin" / "youtube post" all
# trip without the regex enumerating each platform; this regex
# closes the broader no-provider gap with the following 22 bounded
# shapes (case-insensitive, word-boundary anchored, separator class
# ``[\s-]+`` applied uniformly to every shape so BOTH space- and
# hyphen-joined variants trip — "internet hosted" / "internet-
# hosted", "cloud hosted" / "cloud-hosted", "make public" /
# "make-public", "anyone can download" / "anyone-can-download",
# "upload to s3" / "upload-to-s3", "hosted on aws" /
# "hosted-on-aws", "stored on cloud" / "stored-on-cloud",
# "cloud-stored" / "cdn-served" — while concatenations without ANY
# separator — "publichosting", "uploadtos3" — do not):
#
# IMPORTANT — the regex is DELIBERATELY NARROW around storage verbs.
# Alt 14 ("verb to") only fires for unambiguous distribution verbs
# {post, upload, share, sharing, publish, distribute, broadcast,
# stream, mirror}; save / store / sync / backup / deliver / serve /
# send / forward / host are NOT in alt 14 because phrases like
# "save to file", "send to printer", "stored to disk", "forwarded
# to inbox" are ordinary local-action wording an operator might
# legitimately use in alt_text / intended_use. The same verbs ARE
# refused — but only when paired with a recognised cloud channel —
# via alt 16 ("verb + (on|to|via|from|across|over|through) +
# <channel>") and alts 7 / 7b ("<channel> + verb"). So "saved to
# project" passes but "saved to cloud" / "synced-to-cloud" /
# "cloud-stored" refuse.
#
#   1. ``public(ly)? / freely / openly`` + sharing / hosting /
#      distribution / disclosure / display / view verb or noun
#      (``host``, ``share``, ``upload``, ``publish``, ``release``,
#      ``distribut(e/ion)``, ``broadcast``, ``stream``, ``mirror``,
#      ``disclos(e)``, ``display``, ``view(able/ing)``, ``url``,
#      ``link``, ``access(ible)``, ``available``, ``visible``).
#   2. the same verbs followed by ``public(ly) / freely / openly``.
#   3. ``make / made (it / this / them) public``.
#   4. sharing / distribution verb followed by ``online``.
#   5. ``online`` followed by the same verb.
#   6. ``on the internet`` / ``on the web``.
#   7. ``<channel> + distribution verb`` where channel ∈ {internet,
#      web, cloud, cdn, aws, azure, gcp, s3} (NO "remote",
#      NO "external") and verb ∈ {host(ed/ing), share(d)/sharing,
#      upload(ed/ing), publish(ed/ing), distribute(d/ing),
#      broadcast(ed/ing/s), stream(ed/ing/s), mirror(ed/ing)}.
#      "remote" and "external(ly)" are deliberately NOT in the
#      channel list — they are ambiguous on their own ("remote
#      backup icon", "external hard drive", "remote server
#      diagram" describe local hardware / LAN devices, NOT
#      public-cloud channels). alt 18 still catches the
#      distribution-y "remotely-hosted" / "externally-distributed"
#      via the distance-modifier path where they are paired with
#      a distribution verb. Noun forms like "distribution" /
#      "storage" are NOT in the verb list (so "cdn distribution
#      diagram" / "cloud storage diagram" pass as benign
#      architecture references).
#   7b. ``<cloud-provider channel> + storage/delivery verb`` where
#       channel ∈ {cloud, cdn, aws, azure, gcp, s3} (NARROWER than
#       alt 7) and verb ∈ {store(d)/storing, save(d)/saving,
#       serve(d)/serving, sync(ed/ing), backup, backed,
#       deliver(ed/ing/s)}. Catches "cloud-stored", "cdn-served",
#       "aws-saved", "s3-backed", "cdn-delivered". The narrower
#       channel vocab is what lets "internet save dialog" /
#       "remote backup icon" stay benign — internet/remote are
#       NOT in this list.
#   8. ``anyone / everyone`` + ``can / has`` + reach verb (``access``,
#      ``download``, ``see``, ``view``, ``read``, ``reach``, ``find``,
#      ``get``, ``obtain``, ``share``).
#   9. ``open access`` / ``open to (the) (public|anyone|world|everyone)``.
#   10. ``for / to (the) public`` (catches ``for the public``,
#       ``to the public``, ``released to the public``, etc. — bare
#       ``public`` as a content noun like ``image of a public square``
#       stays clean because it lacks the ``for/to`` lead-in).
#   11. ``wide(ly) / global(ly) / world(wide)`` + ``distribut /
#       broadcast / share / circulat`` verbs.
#   12. the same verbs + ``wide(ly) / global(ly) / world(wide)``.
#   13. ``live (stream / broadcast)`` / ``livestream``.
#   14. ``<distribution verb> to`` — verb vocab DELIBERATELY
#       NARROW: only post / upload / share(d/s) / sharing /
#       publish(ed/ing) / distribute(d/ing) / broadcast(ed/ing/s)
#       / stream(ed/ing/s) / mirror(ed/ing). save / store / sync /
#       backup / deliver / serve / send / forward / host are NOT
#       here because phrases like ``save to file``, ``send to
#       printer``, ``stored to disk``, ``delivered to mailbox``,
#       ``forwarded to inbox`` are ordinary local-action wording.
#       Catches ``post to twitter``, ``upload-to-s3``,
#       ``share-to-dropbox``, ``publish-to-web``,
#       ``shared-to-linkedin``, ``uploaded-to-server``.
#       ``sync to cloud`` / ``saved to s3`` / ``backup to cloud``
#       still refuse via alt 16 (which requires a channel suffix).
#   15. ``<host/broadcast/publish/stream verb> on`` — catches
#       ``hosted-on-aws``, ``host-on-cloud``, ``broadcast-on-air``,
#       ``published-on-blog``. ``post`` is NOT here because
#       ``post on canvas`` / ``post on Monday`` are benign local
#       wording; ``post on twitter`` / ``posted on linkedin`` trip
#       via the social-media platform substring denylist instead.
#   16. ``<sharing/storage/delivery verb> + (on|to|via|from|across|
#       over|through) + <cloud channel>`` — channel ∈ {internet,
#       web, cloud, cdn, aws, azure, gcp, s3} (NO "remote", NO
#       "external"). Catches ``stored on cloud``, ``served via
#       cdn``, ``delivered via web``, ``synced to cloud``,
#       ``available via web``, ``served from cdn``, ``backup to
#       cloud`` and their hyphen-joined forms. Ordinary local-
#       network / local-hardware wording like ``saved to remote
#       drive``, ``synced to remote backup``, ``stored on remote
#       server``, ``saved to external drive``, ``stored on
#       external HDD``, ``backed up to remote server`` PASSES
#       because "remote" / "external" are NOT in the channel
#       vocab here. Closes the gap left by alt 14 (which only
#       takes ``to``) and alt 15 (which only takes ``on``).
#   17. ``<content-class noun> + host(ed|ing)`` — content nouns are
#       {image, file, video, content, media, static, photo,
#       document, page}. Catches ``image-hosting``,
#       ``file-hosting``, ``video-hosting``, ``content-hosting``,
#       ``static-hosting``, ``image hosting service``.
#   18. ``<distance modifier> + distribution verb`` — modifiers are
#       {external(ly), remote(ly), third-party, 3rd-party}; verbs
#       cover host(ed/ing) / distribut(e/ed/ing) / shar(e/ed/ing)
#       / broadcast(ed/ing/s) / publish(ed/ing) / stream(ed/ing/s).
#       Catches ``externally-hosted``, ``externally-distributed``,
#       ``externally-shared``, ``remotely-hosted``,
#       ``third-party-hosted``, ``3rd-party-shared``. Excludes
#       ``self-hosted`` and ``privately-hosted`` (benign local
#       hosting) — both are intentionally NOT in the modifier list.
#   19. ``download(able)? from <cloud/public destination>`` — the
#       destination must be a cloud channel ({internet, web, cloud,
#       cdn, aws, azure, gcp, s3} — NO "remote") OR a public-reach
#       token ({anywhere, everywhere, anyone, everyone, public}).
#       Catches ``downloadable from anywhere``, ``download from
#       web``, ``downloadable-from-anywhere``. Local UI wording like
#       ``download from menu`` / ``download from app`` /
#       ``download from cache`` / ``download from external drive``
#       / ``downloaded from remote disk`` PASSES (the suffix is
#       not in channel-or-public-reach vocab).
#   20. ``back(ed|ing)? up to <cloud channel>`` — destination must
#       be a cloud channel ({internet, web, cloud, cdn, aws, azure,
#       gcp, s3} — NO "remote"). Catches ``back up to cloud``,
#       ``backed-up-to-s3``, ``backing up to aws``. Local backup
#       wording like ``back up to file`` / ``backed up to local
#       disk`` / ``back up to backup drive`` / ``back up to remote
#       folder`` / ``backed up to remote server`` PASSES.
#   21. ``<share|shared|sharing> + (link|url)`` — catches
#       ``share link``, ``share-link``, ``sharing url``. Benign UI
#       references like ``share button mockup`` still pass because
#       ``button`` is not in the link/url alternation.
#
# Benign uses stay clean by design: "public square", "public service
# announcement", "publication date", "make a public statement",
# "open book", "online tutorial illustration", "internet of things
# diagram", "live action photograph", "on-the-fly diagram",
# "to-do list", "user-to-user flow", "go-to action", "host icon",
# "host server icon", "hosting industry chart", "cdn architecture
# diagram", "cloud architecture diagram", "cdn icon", "file icon",
# "video icon", "media playback icon", "saved icon", "backup icon",
# "sync icon", "share button mockup", "share price chart",
# "shareholder report chart", "self-hosted server icon",
# "post-modern style", and "blog post illustration" all lack the
# verb / channel / reach modifier or the specific noun adjacency
# that any alternation requires next to its trigger token.
_DENY_PUBLIC_SHARE_REGEX = re.compile(
    # 1. public(ly) / freely / openly + sharing/distribution/disclosure verb
    r"\b(?:public(?:ly)?|freely|openly)[\s-]+"
    r"(?:host(?:ed|ing)?|shar(?:e|ed|ing)|upload(?:ed|ing)?|"
    r"publish(?:ed|ing)?|releas(?:e|ed|ing)|"
    r"distribut(?:e|ed|ing|ion)|broadcast(?:ed|ing|s)?|"
    r"stream(?:ed|ing|s)?|mirror(?:ed|ing)?|disclos(?:e|ed|ing)|"
    r"display(?:ed|ing|s)?|view(?:able|ing)?|"
    r"url|link|access(?:ible)?|available|visible)\b"

    # 2. sharing/distribution/disclosure verb + public(ly) / freely / openly
    r"|\b(?:host(?:ed|ing)?|shar(?:e|ed|ing)|upload(?:ed|ing)?|"
    r"publish(?:ed|ing)?|releas(?:e|ed|ing)|"
    r"distribut(?:e|ed|ing)|broadcast(?:ed|ing|s)?|"
    r"stream(?:ed|ing|s)?|mirror(?:ed|ing)?|disclos(?:e|ed|ing)|"
    r"display(?:ed|ing|s)?)[\s-]+(?:public(?:ly)?|freely|openly)\b"

    # 3. make / made (it / this / them) public
    #    (separator class [\s-]+ so "make-public" / "make-it-public"
    #    also trip)
    r"|\b(?:make|made)[\s-]+(?:it[\s-]+|this[\s-]+|them[\s-]+)?public\b"

    # 4. sharing/distribution verb + online
    r"|\b(?:host(?:ed|ing)?|shar(?:e|ed|ing)|upload(?:ed|ing)?|"
    r"publish(?:ed|ing)?|distribut(?:e|ed|ing|ion)|"
    r"broadcast(?:ed|ing|s)?|stream(?:ed|ing|s)?|"
    r"mirror(?:ed|ing)?)[\s-]+online\b"

    # 5. online + sharing/distribution verb
    r"|\bonline[\s-]+(?:host(?:ing)?|hosted|shar(?:e|ing|ed)|"
    r"upload(?:ing|ed)?|publish(?:ing|ed)?|"
    r"distribut(?:ion|ing|ed|e)?|broadcast(?:ing|ed|s)?|"
    r"stream(?:ing|ed|s)?|mirror(?:ed|ing)?)\b"

    # 6. on the internet / on the web
    #    (separator class [\s-]+ so "on-the-internet" also trips)
    r"|\bon[\s-]+the[\s-]+(?:internet|web)\b"

    # 7. channel noun + sharing/distribution verb
    #    Channel vocab is restricted to UNAMBIGUOUS public channels:
    #    internet / web AND cloud-provider nouns (cloud, cdn, aws,
    #    azure, gcp, s3). "remote" and "external(ly)?" are
    #    deliberately NOT in the channel list — they are too benign
    #    on their own ("external hard drive", "remote backup icon",
    #    "remote server diagram"); alt 18 still catches
    #    "remotely-hosted" / "externally-hosted" /
    #    "externally-distributed" via the distance-modifier path
    #    where they are paired with a distribution verb.
    #    Verb vocab uses verb-forms ONLY (no nouns like "distribution"
    #    or "storage"), so benign architecture descriptions like
    #    "cdn distribution diagram" / "cloud storage diagram" pass.
    r"|\b(?:internet|web|cloud|cdn|aws|azure|gcp|s3)[\s-]+"
    r"(?:host(?:ed|ing)?|shar(?:e|ed|ing)|upload(?:ed|ing)?|"
    r"publish(?:ed|ing)?|distribut(?:e|ed|ing)|"
    r"broadcast(?:ed|ing|s)?|stream(?:ed|ing|s)?|"
    r"mirror(?:ed|ing)?)\b"

    # 7b. cloud-provider channel + storage/delivery verb. Narrower
    #     than alt 7 — the channel vocab here is restricted to
    #     unambiguous cloud-provider nouns (cloud, cdn, aws, azure,
    #     gcp, s3) so storage-style verbs (store/save/serve/sync/
    #     backup/deliver) only trip when paired with a clear cloud
    #     channel. "internet save dialog" / "remote backup icon"
    #     stay benign because internet/remote are not in this
    #     narrower channel vocab. "cloud-stored" / "cdn-served" /
    #     "aws-saved" / "s3-backed" / "cdn-delivered" trip.
    r"|\b(?:cloud|cdn|aws|azure|gcp|s3)[\s-]+"
    r"(?:stor(?:e|ed|ing)|sav(?:e|ed|ing)|"
    r"serv(?:e|ed|ing)|sync(?:ed|ing)?|"
    r"backup|backed|deliver(?:ed|ing|s)?)\b"

    # 8. anyone / everyone + can / has + reach verb
    #    (separator class [\s-]+ so "anyone-can-download" also trips)
    r"|\b(?:anyone|everyone)[\s-]+(?:can|has)[\s-]+"
    r"(?:access(?:es)?|download(?:s)?|see(?:s)?|view(?:s)?|"
    r"read(?:s)?|reach(?:es)?|find(?:s)?|get(?:s)?|"
    r"obtain(?:s)?|share(?:s)?)\b"

    # 9. open access / open to (the) (public|anyone|world|everyone)
    #    (separator class [\s-]+ so "open-access" / "open-to-public"
    #    / "open-to-the-public" also trip)
    r"|\bopen[\s-]+access\b"
    r"|\bopen[\s-]+to[\s-]+(?:the[\s-]+)?"
    r"(?:public|anyone|world|everyone)\b"

    # 10. for / to (the) public
    #     (separator class [\s-]+ so "for-the-public" /
    #     "to-the-public" / "for-public" / "to-public" also trip)
    r"|\b(?:for|to)[\s-]+(?:the[\s-]+)?public\b"

    # 11. wide(ly) / global(ly) / world(wide) + distribut/share/broadcast/circulat
    r"|\b(?:wide(?:ly)?|global(?:ly)?|world(?:wide)?)[\s-]+"
    r"(?:distribut(?:e|ed|ing|ion)|broadcast(?:ed|ing|s)?|"
    r"shar(?:e|ed|ing)|circulat(?:e|ed|ing))\b"

    # 12. distribut/share/broadcast/circulat + wide(ly) / global(ly) / worldwide
    r"|\b(?:distribut(?:e|ed|ing|ion)|broadcast(?:ed|ing|s)?|"
    r"shar(?:e|ed|ing)|circulat(?:e|ed|ing))[\s-]+"
    r"(?:wide(?:ly)?|global(?:ly)?|world(?:wide)?)\b"

    # 13. live stream / live broadcast / livestream
    r"|\blive[\s-]+(?:stream(?:ed|ing|s)?|broadcast(?:ed|ing|s)?)\b"
    r"|\blivestream(?:ed|ing|s)?\b"

    # 14. sharing / distribution verb [\s-]+ to
    #     Verb vocab is INTENTIONALLY narrow — only verbs that
    #     unambiguously imply public distribution regardless of
    #     what follows: post / upload / share / publish / distribute
    #     / broadcast / stream / mirror. Verbs like save / store /
    #     sync / backup / deliver / serve / send / forward are NOT
    #     here because they are typical local-action wording ("save
    #     to file", "send to printer", "stored to disk") — those
    #     verbs are only refused when alt 16 sees them paired with
    #     a recognised cloud channel ("saved to cloud" /
    #     "synced to s3"). Generalises the social-media-post shape
    #     ("post to twitter") AND catches the hyphen-joined forms
    #     of the substring tokens ("upload-to-s3" /
    #     "share-to-dropbox" / "publish-to-web" /
    #     "shared-to-linkedin").
    r"|\b(?:post(?:ed|ing)?|upload(?:ed|ing)?|"
    r"share(?:d|s)?|sharing|"
    r"publish(?:ed|ing)?|distribut(?:e|ed|ing)|"
    r"broadcast(?:ed|ing|s)?|stream(?:ed|ing|s)?|"
    r"mirror(?:ed|ing)?)[\s-]+to\b"

    # 15. host / broadcast / publish / stream verb [\s-]+ on
    #     Catches the hyphen-joined forms of "hosted on" / "host on"
    #     ("hosted-on-aws", "host-on-cloud") plus equivalents
    #     ("broadcast-on-air", "published-on-blog"). "post" is NOT
    #     here because "post on canvas" / "post on Monday" are
    #     benign local wording; "post on twitter" / "posted on
    #     linkedin" trip via the social-media substring denylist
    #     entries instead.
    r"|\b(?:host(?:ed|ing)?|broadcast(?:ed|ing|s)?|"
    r"publish(?:ed|ing)?|stream(?:ed|ing|s)?)[\s-]+on\b"

    # 16. sharing / distribution / storage / delivery verb [\s-]+
    #     preposition [\s-]+ channel noun. Catches "stored on cloud",
    #     "served via cdn", "delivered via web", "saved to cloud",
    #     "synced to cloud", "backup to cloud", "served from cdn"
    #     and their hyphenated variants. Channel vocab is restricted
    #     to UNAMBIGUOUS public channels (internet / web / cloud /
    #     cdn / aws / azure / gcp / s3); "remote" and "external(ly)"
    #     are deliberately NOT here because phrases like
    #     "saved to remote drive", "synced to remote backup",
    #     "stored on remote server", "saved to external drive" are
    #     ordinary local-storage wording (LAN, NAS, external HDD)
    #     that operators legitimately use to describe local
    #     backup / storage workflows. The distance-modifier path
    #     (alt 18) still catches "remotely-hosted" / "externally-
    #     distributed" when paired with an unambiguous distribution
    #     verb. The verb vocab here is broader than alt 14 because
    #     some of these verbs ("stored", "served", "delivered")
    #     naturally take "on/via/from" rather than "to".
    r"|\b(?:host(?:ed|ing)?|shar(?:e|ed|ing)|upload(?:ed|ing)?|"
    r"publish(?:ed|ing)?|distribut(?:e|ed|ing|ion)|"
    r"broadcast(?:ed|ing|s)?|stream(?:ed|ing|s)?|"
    r"mirror(?:ed|ing)?|deliver(?:ed|ing|s)?|"
    r"serv(?:e|ed|ing)|sav(?:e|ed|ing)|"
    r"stor(?:e|ed|ing)|sync(?:ed|ing)?|backup|backed|"
    r"post(?:ed|ing)?|available)[\s-]+"
    r"(?:on|to|via|from|across|over|through)[\s-]+"
    r"(?:internet|web|cloud|cdn|aws|azure|gcp|s3)\b"

    # 17. content-class noun [\s-]+ host(ed|ing).
    #     Catches "image-hosting", "file-hosting", "video-hosting",
    #     "content-hosting", "media-hosting", "static-hosting",
    #     "photo-hosting", "document-hosting", "page-hosting" and
    #     their space-separated forms. Content vocab is restricted
    #     to high-signal nouns so benign phrases like "host icon"
    #     / "hosting industry chart" (no content prefix) still pass.
    r"|\b(?:image|file|video|content|media|static|photo|"
    r"document|page)[\s-]+host(?:ed|ing)\b"

    # 18. distance modifier [\s-]+ distribution verb.
    #     Distance modifiers are external(ly) / remote(ly) /
    #     third-party / 3rd-party. Verb vocab covers
    #     host(ed|ing) / distribut(e|ed|ing) / shar(e|ed|ing) /
    #     broadcast(ed|ing|s) / publish(ed|ing) / stream(ed|ing|s)
    #     so "externally-hosted" / "externally-distributed" /
    #     "externally-shared" / "third-party-hosted" /
    #     "remotely-broadcasted" all trip. Excludes "self-hosted"
    #     and "privately-hosted" — those describe local hosting and
    #     are benign. (Alt 7 no longer covers "external(ly)?" as
    #     a channel, so this alt is the load-bearing path for
    #     externally- / remotely- / third-party- prefixes.)
    r"|\b(?:external(?:ly)?|remote(?:ly)?|"
    r"third[\s-]+party|3rd[\s-]+party)[\s-]+"
    r"(?:host(?:ed|ing)|distribut(?:e|ed|ing)|"
    r"shar(?:e|ed|ing)|broadcast(?:ed|ing|s)?|"
    r"publish(?:ed|ing)|stream(?:ed|ing|s)?)\b"

    # 19. download(able) from <cloud/public destination>.
    #     Requires the destination to be a known cloud channel
    #     (internet / web / cloud / cdn / aws / azure / gcp / s3)
    #     OR a public-reach modifier (anywhere / everywhere /
    #     anyone / everyone / public). "remote" is NOT in this list
    #     because "download from remote disk" / "downloadable from
    #     remote storage" describe local-network downloads.
    #     Benign local wording like "download from menu" /
    #     "download from app" / "downloadable from cache" /
    #     "download from external drive" passes because their
    #     destinations are not in the channel vocab.
    r"|\bdownload(?:able)?[\s-]+from[\s-]+"
    r"(?:internet|web|cloud|cdn|aws|azure|gcp|s3|"
    r"anywhere|everywhere|anyone|everyone|public)\b"

    # 20. back(ed/ing)? up to <cloud channel>. Requires the
    #     destination to be a known cloud channel so benign local
    #     wording like "back up to file" / "backed up to local disk"
    #     / "back up to backup drive" / "back up to remote disk"
    #     passes. "backup to cloud" / "backed-up-to-s3" still trip.
    #     "remote" is NOT in this channel list because "back up to
    #     remote disk" / "backed up to remote server" describe
    #     legitimate local-network or external-device backup
    #     workflows.
    r"|\bback(?:ed|ing)?[\s-]+up[\s-]+to[\s-]+"
    r"(?:internet|web|cloud|cdn|aws|azure|gcp|s3)\b"

    # 21. share/shared/sharing + link/url. Catches "share link",
    #     "share-link", "sharing url". Benign UI references like
    #     "share button mockup" still pass because "button" is not
    #     in the link/url alternation.
    r"|\b(?:share|shared|sharing)[\s-]+(?:link|url)\b",
    re.IGNORECASE,
)

_DENY_CONFIDENTIAL: tuple[str, ...] = (
    "confidential", "internal use only", "internal only",
    "do not share", "raw source", "customer name",
    "customer pii", "customer data", "nda only",
    "trade secret", "personal data", "sensitive data",
    "proprietary data", "non-public", "classified",
)

# Brand / service tokens for the upstream services this lane does
# NOT call AND the public-network success claim shapes that an
# operator manifest might use to inject the appearance of a real
# upstream call into the deck or summary. Refusing ANY mention of
# the lane-specific brands (D-One, MCP, Qoder) keeps the boundary
# statements concentrated in ``_EXPLICIT_BOUNDARIES``; refusing
# generic network-operation success vocab ("API call succeeded",
# "HTTP request returned", "successfully invoked the model",
# "generated by stable diffusion") keeps tampered manifests from
# claiming a successful network / model / image-gen touchpoint
# that the lane has not made.
#
# Shape categories:
#   A. Lane-specific brands (d-one / mcp / qoder).
#   B. Upstream service indicators (model api / image search /
#      telemetry).
#   C. Network / API / HTTP operation success vocab.
#   D. Network protocol mentions (rest api / graphql / webhook /
#      websocket / grpc).
#   E. "real / live / production / real-time" + upstream service.
#   F. "successful(ly) / actually" + action verb.
#   G. Action verb + (preposition + article)* + upstream target.
#   H. AI / ML / model / machine "generated" claims.
#   I. "<production-verb> + <prep> + <AI brand>" — production
#      verb covers generated / created / made / produced / drawn
#      / painted / rendered / synthesized / crafted / composed /
#      written / prompted / powered / output; prep covers by /
#      via / with / through / from / using; brand list covers
#      every AI upstream the helper does NOT call. Benign
#      authorship like "drawn by hand" / "painted by Monet" /
#      "composed by Bach" / "written by John" / "produced by
#      company" PASSES because the brand token must be one of
#      the AI-product names.
#   J. Image-gen model brand mentions (mid[\s-]*journey,
#      dall-e, stable diffusion, imagen, leonardo ai). The
#      ``[\s-]*`` separator class on ``mid[\s-]*journey`` makes
#      ``Mid Journey`` / ``Mid-Journey`` / ``Midjourney`` all
#      trip; ``[\s-]*-?[\s-]*`` on ``dall[\s-]*-?[\s-]*e``
#      handles ``DALL E`` / ``DALL-E`` / ``DALLE`` / ``dalle``.
#   J+. Unambiguous LLM-product brand mentions standalone:
#       chatgpt, open[\s-]*ai (single AND multi-word: catches
#       "openai" / "open ai" / "open-ai" alike — the helper
#       USED to keep two-word "Open AI" benign for benign uses
#       like "Open AI architecture book", but Codex flagged
#       that as a fake-success vector; the trade-off cost is
#       that "Open AI architecture book" / "Open AI initiative"
#       type phrases now refuse and the operator must rephrase
#       to "AI architecture book" or "open-source AI initiative"
#       — see also the alt I brand list which mirrors the same
#       open[\s-]*ai expansion), anthropic, gpt(-N(.N))?.
#       Catches "ChatGPT illustration" / "OpenAI image" /
#       "Open AI illustration" / "open-ai render" /
#       "Anthropic creation" / "GPT-4 output" while keeping
#       "GPS map" / "Egyptian art" benign (the ``\b`` boundary
#       keeps "gpt" out of "Egypt" / "GPS"; "open" followed by
#       a non-"ai" word like "book", "source", "API",
#       "license", "standard", "SSL" still passes).
#   K. ``claude`` / ``gemini`` + (model version | distribution-
#      style noun). Refuses "Claude 3 illustration" /
#      "Claude opus render" / "Claude renderings" / "Claude
#      paintings" / "Gemini Pro output" / "Gemini-generated"
#      while keeping "Claude Monet painting" / "Claude Debussy
#      biography" / "Claude Shannon information theory" /
#      "Gemini constellation" / "Gemini horoscope reading" /
#      "Gemini spacecraft" benign because the closed suffix
#      vocab requires a model version OR a distribution-style
#      noun.
_FAKE_SUCCESS_REGEX = re.compile(
    # A. Lane-specific brands.
    r"\bd-?one\b"
    r"|\bmcp\b"
    r"|\bqoder\b"

    # B. Upstream service indicators.
    r"|\bmodel[\s-]+(?:api|call|request|response|endpoint|"
    r"service|invocation)\b"
    r"|\bimage[\s-]+search\b"
    r"|\btelemetry\b"

    # C. Network / API / HTTP operation success vocab.
    r"|\bnetwork[\s-]+(?:call|reached|hit|success|response|"
    r"connection|request|connected|established|"
    r"succeeded|returned|completed|received)\b"
    r"|\bapi[\s-]+(?:call|request|response|hit|success|"
    r"endpoint|succeeded|returned|completed|invocation|"
    r"received|integration)\b"
    r"|\bhttps?[\s-]+(?:call|request|response|hit|success|"
    r"connection|succeeded|returned|completed|received|"
    r"endpoint)\b"

    # D. Network protocol mentions.
    r"|\brest[\s-]+(?:api|call|endpoint|request)\b"
    r"|\bgraphql\b"
    r"|\bwebhook(?:s)?\b"
    r"|\bwebsocket(?:s)?\b"
    r"|\bgrpc\b"

    # E. "real / live / production / real-time" + upstream service.
    r"|\b(?:real|live|production|real[\s-]*time)[\s-]+"
    r"(?:d-?one|mcp|qoder|network|model|api|call|"
    r"integration|endpoint|service|backend|host(?:ing|ed)?|"
    r"invocation|response|request)\b"

    # F. "successful(ly) / actually" + action verb.
    r"|\b(?:successful(?:ly)?|actually)[\s-]+"
    r"(?:called|invoked|queried|fetched|reached|"
    r"contacted|connected|integrated|hit|posted|"
    r"published|received|sent)\b"

    # G. Action verb + (preposition + article)* + upstream target.
    #    Allows zero or more intermediate filler words drawn from
    #    a small closed set {from, the, to, with, on, for, at, via,
    #    through, by} so phrases like "called the model" /
    #    "fetched from the api" / "integrated with the endpoint"
    #    all trip while keeping benign "called for review" /
    #    "fetched from local source" PASS (because "review" /
    #    "source" are not in the target list).
    r"|\b(?:called|invoked|queried|hit|reached|contacted|"
    r"integrated|fetched|retrieved|received|downloaded|got)"
    r"[\s-]+(?:(?:from|the|to|with|on|via|through|by)[\s-]+)*"
    r"(?:model|api|endpoint|network|service|server|"
    r"d-?one|mcp|qoder|backend|llm)\b"

    # H. AI / ML / machine / model "generated" claims.
    r"|\b(?:ai|ml|machine|model)[\s-]+generated\b"
    r"|\bai[\s-]*-?[\s-]*gen(?:erated)?\b"

    # I. "<production verb> + <prep> + <AI brand>". Production
    #    verbs cover the full generation / authorship vocabulary
    #    (generated / created / made / produced / drawn / painted /
    #    rendered / synthesized / crafted / composed / written /
    #    prompted / powered / output). Preps cover by / via / with
    #    / through / from / using. Brand list covers every AI
    #    upstream the helper does NOT call. So "made by Claude",
    #    "powered by OpenAI" / "powered by Open AI" (two-word),
    #    "rendered by GPT-4", "drawn by Midjourney" / "drawn by
    #    Mid Journey" (two-word), "created with Anthropic",
    #    "composed by Claude" all refuse. Benign authorship
    #    ("drawn by hand", "painted by Monet", "composed by Bach",
    #    "written by John", "produced by company") passes because
    #    the brand token must be one of the specific AI-product
    #    names below — and bare prepositions ("by hand", "by
    #    Monet") don't match any brand token.
    r"|\b(?:generated|created|made|produced|drawn|painted|"
    r"rendered|synthesized|crafted|composed|written|"
    r"prompted|powered|output)[\s-]+"
    r"(?:by|via|with|through|from|using)[\s-]+"
    r"(?:ai|ml|machine|model|api|"
    r"d-?one|mcp|qoder|"
    r"mid[\s-]*journey|dall[\s-]*-?[\s-]*e|"
    r"stable[\s-]+diffusion|imagen|firefly|"
    r"leonardo[\s-]+ai|gpt|chatgpt|open[\s-]*ai|"
    r"anthropic|claude|gemini|llama|mistral)\b"

    # J. Image-gen model brand mentions (high-signal standalone).
    #    Multi-word / hyphenated variants are covered via
    #    ``[\s-]*`` between the brand tokens so "Mid Journey" /
    #    "Mid-Journey" / "Midjourney" all trip; same for the
    #    "DALL E" / "DALL-E" / "DALLE" / "Open AI" / "Open-AI" /
    #    "OpenAI" forms below.
    r"|\bmid[\s-]*journey\b"
    r"|\bdall[\s-]*-?[\s-]*e\b"
    r"|\bstable[\s-]+diffusion\b"
    r"|\bimagen\b"
    r"|\bleonardo[\s-]+ai\b"

    # J+. Standalone LLM-product brand mentions where the brand
    #     name is unambiguous: ``chatgpt`` (the chatbot product),
    #     ``open[\s-]*ai`` (catches "openai" / "open ai" /
    #     "open-ai" — the helper used to keep "Open AI" two-word
    #     benign, but Codex flagged that as a fake-success vector;
    #     the trade-off cost is that benign "Open AI architecture
    #     book" / "Open AI initiative" type phrases now refuse and
    #     the operator must rephrase to "AI architecture book" or
    #     similar), ``anthropic`` (rarely used outside the
    #     company — "anthropic principle" is an accepted marginal
    #     false-positive), ``gpt`` with optional
    #     ``-<digit>(.<digit>)`` version suffix (catches ``GPT``,
    #     ``GPT-3``, ``GPT-4``, ``GPT-3.5``, ``gpt4``; does NOT
    #     match substrings inside ``GPS`` / ``Egyptian`` because
    #     of the ``\b`` boundary). The "chat gpt" / "chat-gpt"
    #     two-word forms ALSO trip via the standalone ``\bgpt\b``
    #     match.
    r"|\bchatgpt\b"
    r"|\bopen[\s-]*ai\b"
    r"|\banthropic\b"
    r"|\bgpt(?:[\s-]*-?[\s-]*[0-9](?:\.[0-9])?)?\b"

    # K. ``claude`` / ``gemini`` + (model version | distribution
    #    context) — refuses ``Claude 3 illustration``,
    #    ``Claude API documentation``, ``Claude opus render``,
    #    ``Gemini Pro output``, ``Gemini-generated`` while
    #    leaving benign ``Claude Monet painting``, ``Claude
    #    Debussy biography``, ``Gemini constellation``, ``Gemini
    #    spacecraft`` clean because the suffix must come from a
    #    closed vocab of AI model versions or distribution-style
    #    nouns.
    r"|\bclaude[\s-]+"
    r"(?:[2-9](?:\.[0-9])?|opus|sonnet|haiku|instant|chat|"
    r"api|model(?:s)?|call(?:s)?|response(?:s)?|"
    r"completion(?:s)?|"
    r"generat(?:e|ed|ing|es|ion(?:s)?)|"
    r"creat(?:e|ed|ing|es|ion(?:s)?)|"
    r"render(?:ed|ings?|s)?|"
    r"draw(?:n|ings?|s)?|"
    r"illustrat(?:e|ed|ing|es|ion(?:s)?)|"
    r"paint(?:ed|ings?|s)?|"
    r"portrait(?:s)?|image(?:s)?|art|"
    r"output(?:s)?|export(?:s)?)\b"
    r"|\bgemini[\s-]+"
    r"(?:pro|ultra|flash|nano|[0-9](?:\.[0-9])?|"
    r"api|model(?:s)?|call(?:s)?|response(?:s)?|"
    r"completion(?:s)?|"
    r"generat(?:e|ed|ing|es|ion(?:s)?)|"
    r"creat(?:e|ed|ing|es|ion(?:s)?)|"
    r"render(?:ed|ings?|s)?|"
    r"draw(?:n|ings?|s)?|"
    r"illustrat(?:e|ed|ing|es|ion(?:s)?)|"
    r"paint(?:ed|ings?|s)?|"
    r"portrait(?:s)?|image(?:s)?|art|"
    r"output(?:s)?|export(?:s)?)\b",
    re.IGNORECASE,
)


def _safe_manifest_string(
    *,
    field: str,
    value: object,
    max_len: int,
    entry_idx: int,
) -> tuple[str | None, str | None]:
    """Validate one manifest free-text field. Returns
    ``(cleaned_or_None, failure_or_None)``.

    All four manifest string fields share these gates:

      * type — must be a Python ``str``;
      * length — 1..``max_len`` bytes inclusive;
      * whitespace — no leading / trailing space (operator trims);
      * control character — refused (avoids embedding LF / CR / NUL
        into the deck's editable text);
      * URL / URI shape — ``://`` substring or leading ``<scheme>:``;
      * path separator — ``/`` or ``\\`` is refused; the field is a
        name / phrase, never a path;
      * credential / token / API-key shape — substring denylist plus
        the OpenAI-style ``sk-XXXX`` regex;
      * public upload / share / hosting wording — substring denylist
        for provider-named phrasings (``upload to <provider>``,
        ``share to <name>``), high-signal phrases (``public domain``,
        ``on social media``), and social-media platform names
        (twitter / instagram / facebook / linkedin / reddit /
        tiktok / youtube / mastodon / threads.net / bluesky /
        tumblr / pinterest / snapchat) so ``posted on twitter`` /
        ``shared on linkedin`` / ``youtube post`` trip without the
        regex enumerating each provider; AND a 22-shape bounded
        regex (separator class ``[\\s-]+`` applied uniformly so
        BOTH space- and hyphen-joined variants of every shape trip
        — ``make-public``, ``on-the-internet``,
        ``anyone-can-download``, ``cloud-hosted``,
        ``cdn-distributed``, ``aws-hosted``, ``image-hosting``,
        ``third-party-hosted``, ``upload-to-s3``,
        ``hosted-on-aws``, ``stored-on-cloud``, ``cloud-stored``,
        ``cdn-served``, ``synced-to-cloud``, ``backup-to-cloud``,
        ``downloadable-from-anywhere``, ``share-link``,
        ``for-the-public`` all refuse alongside their space-
        separated forms). The regex is DELIBERATELY NARROW around
        storage verbs: alt 14 (``<verb> to``) only fires for
        unambiguous distribution verbs (post / upload / share /
        publish / distribute / broadcast / stream / mirror), so
        ``save to file`` / ``send to printer`` / ``stored to disk``
        / ``forwarded to inbox`` / ``delivered to mailbox`` PASS.
        The same verbs refuse only when paired with a cloud channel
        via alt 16 (``verb + (on|to|via|from|across|over|through) +
        <channel>``) or alt 7/7b (``<channel> + verb``); so ``saved
        to project`` passes but ``saved to cloud`` /
        ``synced-to-cloud`` refuse. Alt 19 (``download(able)?
        from``) and alt 20 (``back(ed|ing)? up to``) require their
        suffix to be a cloud channel or public-reach token, so
        ``download from menu`` / ``back up to file`` PASS but
        ``downloadable from anywhere`` / ``backup-to-cloud`` refuse.
        Excluded benign hosting modifiers: ``self-hosted`` /
        ``privately-hosted`` (intentionally NOT in alt 18's
        distance-modifier vocab). No-provider phrasings such as
        ``cloud-hosted``, ``cdn-distributed``, ``image-hosting``,
        ``third-party-hosted``, ``stored-on-cloud``,
        ``cloud-stored``, ``cdn-served``, ``downloadable from
        anywhere``, ``backup to cloud``, ``share-link``,
        ``posted on twitter`` are refused;
      * raw-source / confidential / customer marker — substring
        denylist;
      * positive real-D-One / MCP / Qoder / model API / image search /
        network / telemetry claim — regex denylist.

    The diagnostic names the entry index, the field, and the
    offending token / shape so the operator can fix the manifest
    without re-running to discover which gate fired."""
    if not isinstance(value, str):
        return None, (
            f"--manifest images[{entry_idx}].{field} is "
            f"{type(value).__name__}, expected string (MAN10)."
        )
    if not value:
        return None, (
            f"--manifest images[{entry_idx}].{field} is empty; expected "
            f"a non-empty string (MAN10)."
        )
    if len(value) > max_len:
        return None, (
            f"--manifest images[{entry_idx}].{field} is {len(value)} "
            f"chars; expected <= {max_len} (MAN10)."
        )
    if value != value.strip():
        return None, (
            f"--manifest images[{entry_idx}].{field}={value!r} has "
            f"leading or trailing whitespace; trim and retry (MAN10)."
        )
    if any(ord(ch) < 0x20 for ch in value):
        return None, (
            f"--manifest images[{entry_idx}].{field} contains a "
            f"control character (MAN10); refused so the deck's "
            f"editable text never carries a non-printable byte."
        )
    if "://" in value:
        return None, (
            f"--manifest images[{entry_idx}].{field}={value!r} "
            f"contains '://' (URL-shaped); refused — the manifest is "
            f"local-only metadata (MAN10)."
        )
    if _has_uri_scheme(value):
        return None, (
            f"--manifest images[{entry_idx}].{field}={value!r} starts "
            f"with a URI scheme; refused — the manifest is local-only "
            f"metadata (MAN10)."
        )
    if "/" in value or "\\" in value:
        return None, (
            f"--manifest images[{entry_idx}].{field}={value!r} "
            f"contains a path separator; refused — the field is a "
            f"name / phrase, not a path (MAN10)."
        )
    lower = value.lower()
    for token in _DENY_CREDENTIAL:
        if token in lower:
            return None, (
                f"--manifest images[{entry_idx}].{field} contains "
                f"credential-shaped substring {token!r}; refused — "
                f"the helper does NOT receive credentials (MAN10)."
            )
    if _OPENAI_KEY_REGEX.search(value):
        return None, (
            f"--manifest images[{entry_idx}].{field} contains an "
            f"API-key-shaped token (sk-XXXX...); refused (MAN10)."
        )
    for token in _DENY_UPLOAD:
        if token in lower:
            return None, (
                f"--manifest images[{entry_idx}].{field} contains "
                f"upload / share / hosting substring {token!r}; "
                f"refused — the helper is local-only and does NOT "
                f"publish outputs (MAN10)."
            )
    public_share_hit = _DENY_PUBLIC_SHARE_REGEX.search(value)
    if public_share_hit is not None:
        return None, (
            f"--manifest images[{entry_idx}].{field}={value!r} "
            f"matches public-share / public-hosting wording "
            f"{public_share_hit.group(0)!r}; refused — the helper "
            f"is local-only and does NOT publish outputs (MAN10)."
        )
    for token in _DENY_CONFIDENTIAL:
        if token in lower:
            return None, (
                f"--manifest images[{entry_idx}].{field} contains "
                f"confidential / customer marker {token!r}; refused "
                f"— the helper does NOT receive raw confidential or "
                f"customer text (MAN10)."
            )
    if _FAKE_SUCCESS_REGEX.search(value):
        return None, (
            f"--manifest images[{entry_idx}].{field}={value!r} "
            f"mentions an upstream service this lane does NOT call "
            f"(D-One, MCP, Qoder, model API, image search, network, "
            f"telemetry); refused (MAN10)."
        )
    return value, None


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
    # Optional operator-supplied metadata from --manifest. None means
    # the helper applies its built-in default; a non-None value flows
    # verbatim into the native editable slide title (slide_title), the
    # image_manifest alt_text (alt_text), and the image_manifest
    # intended_use (intended_use). The provenance entry in summary.json
    # echoes whichever values were operator-supplied so a reviewer can
    # trace each embedded ppt/media part back to the manifest entry
    # that ordered + labelled it.
    slide_title: str | None = None
    alt_text: str | None = None
    intended_use: str | None = None


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


# ---------------------------------------------------------------------------
# --bundle shortcut gate.
# ---------------------------------------------------------------------------


def _validate_bundle_arg(
    bundle_str: str,
) -> tuple[str | None, str | None, str | None, list[str]]:
    """Validate the ``--bundle`` operator-handoff directory and resolve
    it to ``(images_dir_str, manifest_path_str_or_None,
    generated_provenance_path_str_or_None, failures)``.

    A bundle is a flat operator-handoff folder with the shape::

        <bundle>/
            images/                       # required, PNG / JPG / JPEG flat
            manifest.json                 # optional caller-supplied manifest
            generated_provenance.json     # optional generated-image sidecar

    On success the resolver returns the path strings the existing
    ``--images-dir`` / ``--manifest`` / sidecar gates accept, so all
    downstream image discovery, manifest validation, plan-only,
    approved-plan, out-dir, summary, README, visual-quality, inventory,
    and PPTX gates keep firing unchanged. The bundle layer adds NO new
    content rules on top — it only checks the wrapping directory's
    shape and refuses cleanly BEFORE delegating.

    Gates fire in order, BEFORE any pipeline subprocess:

      BUN1   URI-shaped argument (``file://`` / ``http://`` / any
             RFC-3986 scheme prefix). Only local directory paths are
             accepted.
      BUN2   ``--bundle`` is itself a symlink (broken or resolvable).
             Silently following a symlink would let an attacker who
             controls the link target redirect what bytes the helper
             ingests.
      BUN3   any ancestor up to the filesystem root is a symlink (closed
             system aliases like ``/tmp -> /private/tmp`` remain
             accepted via ``_forbidden_symlink_ancestor``).
      BUN4   the bundle path exists.
      BUN5   the bundle path is a directory.
      BUN6   the bundle carries an ``images`` entry (the required
             flat-image subfolder).
      BUN7   ``<bundle>/images`` is NOT a symlink (broken or
             resolvable) — same attack surface one level down.
      BUN8   ``<bundle>/images`` is a directory (not a regular file,
             device, FIFO, socket, etc.).

    The optional ``<bundle>/manifest.json`` is only forwarded as a path
    string when it exists; its content (JSON shape, schema_version,
    every per-image field) is then validated by the existing
    ``_validate_manifest_arg`` MAN1..MAN12 gates, which already produce
    clean per-failure diagnostics for malformed bytes / missing fields
    / URL / credential / public-hosting wording / fake-success claims.
    The same forwarding pattern applies to the optional
    ``<bundle>/generated_provenance.json`` sidecar: present-or-absent is
    checked here; content gates GP1..GP13 run later in
    ``_validate_generated_provenance_sidecar`` once image discovery has
    produced the filename set the sidecar must cover.
    The bundle resolver does NOT crack open either optional file;
    it only refuses obviously unsafe wrappers (BUN1..BUN8).
    """
    if _has_uri_scheme(bundle_str):
        return None, None, None, [
            f"--bundle argument {bundle_str!r} looks URI-shaped (BUN1); "
            f"only local directory paths are accepted."
        ]

    bundle = Path(bundle_str)

    if bundle.is_symlink():
        try:
            tgt = os.readlink(bundle)
        except OSError:
            tgt = "<unreadable>"
        return None, None, None, [
            f"--bundle {bundle} is a symlink (-> {tgt}) (BUN2); refused "
            f"so a symlink target cannot redirect what bytes the helper "
            f"ingests."
        ]

    forbidden_ancestor = _forbidden_symlink_ancestor(bundle)
    if forbidden_ancestor is not None:
        ancestor, tgt = forbidden_ancestor
        return None, None, None, [
            f"--bundle {bundle} has a symlink ancestor {ancestor} "
            f"(-> {tgt}) (BUN3); refused so a symlink in the operator's "
            f"typed path cannot redirect what bytes the helper ingests."
        ]

    if not bundle.exists():
        return None, None, None, [
            f"--bundle {bundle} does not exist (BUN4)."
        ]
    if not bundle.is_dir():
        return None, None, None, [
            f"--bundle {bundle} is not a directory (BUN5); the bundle "
            f"shortcut expects an operator-handoff folder containing "
            f"images/ and an optional manifest.json."
        ]

    images_dir = bundle / "images"
    if not images_dir.exists() and not images_dir.is_symlink():
        return None, None, None, [
            f"--bundle {bundle} is missing the required images/ "
            f"subdirectory (BUN6); create <bundle>/images/ containing "
            f"the PNG / JPG / JPEG files for this deck."
        ]
    if images_dir.is_symlink():
        try:
            tgt = os.readlink(images_dir)
        except OSError:
            tgt = "<unreadable>"
        return None, None, None, [
            f"--bundle images path {images_dir} is a symlink "
            f"(-> {tgt}) (BUN7); refused so a symlink target cannot "
            f"redirect what bytes the helper ingests."
        ]
    if not images_dir.is_dir():
        return None, None, None, [
            f"--bundle images path {images_dir} exists but is not a "
            f"directory (BUN8); refused."
        ]

    manifest_path = bundle / "manifest.json"
    manifest_str: str | None = None
    if manifest_path.exists() or manifest_path.is_symlink():
        # Forward the path verbatim — the existing MAN1..MAN12 gates
        # surface malformed JSON, missing fields, URI shapes, symlinks
        # on the manifest itself, and every other content failure with
        # the same diagnostics the explicit --manifest flag produces.
        manifest_str = str(manifest_path)

    sidecar_path = bundle / "generated_provenance.json"
    sidecar_str: str | None = None
    if sidecar_path.exists() or sidecar_path.is_symlink():
        # Same forward-the-path pattern as the manifest. The sidecar
        # content gates GP1..GP13 run later in
        # ``_validate_generated_provenance_sidecar`` once image
        # discovery has produced the filename set the sidecar must
        # cover.
        sidecar_str = str(sidecar_path)

    return str(images_dir), manifest_str, sidecar_str, []


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


def _validate_manifest_arg(
    manifest_path_str: str,
    discovered_filenames: list[str] | None,
) -> tuple[list[dict] | None, Path | None, list[str]]:
    """Validate the optional ``--manifest`` argument and return the
    per-image metadata in manifest order.

    Returns ``(ordered_entries_or_None, resolved_path_or_None,
    failures)``. The caller MUST treat the argument as refused
    whenever ``failures`` is non-empty OR ``ordered_entries`` is
    ``None``.

    Gates fire in order, BEFORE any pipeline subprocess:

      MAN1   URI-shaped argument.
      MAN2   ``--manifest`` is itself a symlink (broken or resolvable).
      MAN3   any ancestor up to the filesystem root is a symlink
             (closed system aliases like ``/tmp -> /private/tmp``
             remain accepted via ``_forbidden_symlink_ancestor``).
      MAN4   path exists and is a regular non-symlink file.
      MAN5   the file parses as a single UTF-8 JSON document AND the
             root is a JSON object (not an array / scalar / null).
      MAN6   the root carries exactly the required keys (no extras,
             no missing — the manifest has a single locked shape).
      MAN7   ``schema_version`` equals ``_MANIFEST_SCHEMA_VERSION``
             ("1") verbatim.
      MAN8   ``images`` is a non-empty JSON array.
      MAN9   each entry is a JSON object with EXACTLY the four
             required fields ``filename``, ``slide_title``,
             ``alt_text``, ``intended_use`` — no extras, no missing.
      MAN10  each field passes ``_safe_manifest_string`` (type,
             length, whitespace, control char, URL / URI, path
             separator, credential / token / API-key shape, public
             upload / share / hosting wording — the substring
             denylist locks provider-named phrasings,
             ``public domain`` / ``on social media``, AND the bare
             social-media platform names (twitter, instagram,
             facebook, linkedin, reddit, tiktok, youtube, mastodon,
             threads.net, bluesky, tumblr, pinterest, snapchat);
             a 22-shape bounded regex with ``[\\s-]+`` separator
             class applied uniformly so BOTH space- and
             hyphen-joined variants of every shape trip catches
             no-provider variants. The 22 shapes (in order):
             1 ``public(ly)/freely/openly <verb>``;
             2 ``<verb> public(ly)/freely/openly``;
             3 ``make/made (it/this/them) public``;
             4 ``<verb> online``; 5 ``online <verb>``;
             6 ``on the internet/web``;
             7 ``<channel> <distribution-verb>`` (channel ∈
             {internet, web, cloud, cdn, aws, azure, gcp, s3} —
             NO "remote", NO "external" so ``remote server
             diagram`` / ``external hard drive`` stay benign;
             verb-forms only — no nouns like "distribution" /
             "storage", so benign architecture diagrams pass);
             7b ``<cloud-provider channel> <storage/delivery
             verb>`` (channel ∈ {cloud, cdn, aws, azure, gcp, s3}
             — narrower than alt 7 so ``internet save dialog`` /
             ``remote backup icon`` stay benign);
             8 ``anyone/everyone (can|has) <reach-verb>``;
             9 ``open access`` / ``open to (the) (public/anyone/
             world/everyone)``;
             10 ``for/to (the) public``;
             11 ``wide(ly)/global(ly)/world(wide)
             <distribution-verb>``;
             12 the reverse;
             13 ``live (stream/broadcast)`` / ``livestream``;
             14 ``<distribution-verb> to`` (DELIBERATELY NARROW:
             only post/upload/share/publish/distribute/broadcast/
             stream/mirror — save/store/sync/backup/deliver/serve/
             send/forward/host are NOT here so ``save to file`` /
             ``send to printer`` / ``stored to disk`` PASS);
             15 ``<host/broadcast/publish/stream verb> on``
             (``post on`` is NOT here so ``post on canvas`` /
             ``post on Monday`` pass; ``post on twitter`` trips
             via the social-media platform substring);
             16 ``<sharing/storage/delivery verb> +
             (on|to|via|from|across|over|through) + <cloud
             channel>`` (channel ∈ {internet, web, cloud, cdn,
             aws, azure, gcp, s3} — NO "remote", NO "external" so
             ``saved to remote drive`` / ``stored on external
             disk`` / ``synced to remote backup`` PASS as
             ordinary local-network or external-device wording);
             17 ``<image|file|video|content|media|static|photo|
             document|page> host(ed|ing)``;
             18 ``<external(ly)|remote(ly)|third-party|3rd-party>
             <distribution-verb>`` (catches externally-distributed/
             shared/broadcast too; excludes self-hosted and
             privately-hosted);
             19 ``download(able)? from <cloud/public destination>``
             (suffix must be a cloud channel or public-reach
             token, so ``download from menu`` PASSES);
             20 ``back(ed|ing)? up to <cloud channel>`` (suffix
             must be a cloud channel, so ``back up to file``
             PASSES);
             21 ``<share|shared|sharing> (link|url)``.
             Phrasings such as ``cloud-hosted``,
             ``cdn-distributed``, ``image-hosting``,
             ``third-party-hosted``, ``stored-on-cloud``,
             ``cloud-stored``, ``cdn-served``,
             ``synced-to-cloud``, ``backup-to-cloud``,
             ``downloadable from anywhere``, ``share-link``,
             ``anyone can download``, ``on the internet``,
             ``globally distributed``, ``live stream``,
             ``posted on twitter``, ``freely available``,
             ``open access archive``, ``upload-to-s3``,
             ``hosted-on-aws``, ``make-it-public`` refuse while
             ordinary local wording (``save to file``,
             ``send to printer``, ``forward to inbox``,
             ``stored to disk``, ``cdn distribution diagram``,
             ``external hard drive``, ``share button mockup``,
             ``download from menu``, ``internet save dialog``)
             passes; raw-source / confidential / customer marker;
             positive real-D-One / MCP / Qoder / model API /
             image search / network / telemetry / public-network
             / LLM-brand success claim — the fake-success regex
             covers twelve shape categories: lane-specific brand
             mentions (d-one / mcp / qoder); upstream service
             indicators (``model api`` / ``image search`` /
             ``telemetry``); network / API / HTTP operation
             success vocab (``network connection succeeded`` /
             ``API request returned`` / ``HTTP response
             received`` / ``API endpoint hit``); network
             protocol mentions (``REST API endpoint hit``,
             ``graphql query``, ``webhook delivered``,
             ``websocket connection``, ``grpc call succeeded``);
             ``real / live / production / real-time`` +
             upstream service (``real network call`` / ``live
             D-One call`` / ``production MCP integration``);
             ``successful(ly) / actually`` + action verb
             (``successfully called the model``); action verb +
             ``(prep|article)* + upstream target``
             (``called the model``, ``fetched from API``,
             ``integrated with the endpoint``);
             ``ai / ml / machine / model + generated``
             (``AI-generated illustration``);
             ``<production-verb> + <prep> + <AI brand>`` —
             production verb covers generated / created / made /
             produced / drawn / painted / rendered / synthesized
             / crafted / composed / written / prompted / powered
             / output; prep covers by / via / with / through /
             from / using; so ``made by Claude`` / ``created
             with Midjourney`` / ``powered by OpenAI`` /
             ``drawn by GPT`` / ``rendered by Claude`` all
             refuse (benign ``drawn by hand`` / ``painted by
             Monet`` / ``composed by Bach`` PASSES); image-gen
             model brand mentions (``mid[\\s-]*journey`` —
             catches ``Midjourney`` / ``Mid Journey`` /
             ``Mid-Journey`` — / ``dall-e`` / ``stable
             diffusion`` / ``imagen`` / ``leonardo ai``);
             unambiguous LLM-product brand
             mentions standalone (``chatgpt`` /
             ``open[\\s-]*ai`` — catches ``openai`` (single
             word) AND ``Open AI`` (two words) AND ``open-ai``
             (hyphen); Codex flagged the previous two-word
             benign exception as a fake-success vector, so
             ``Open AI architecture book`` / ``Open AI
             initiative`` now REFUSE and the operator must
             rephrase — / ``anthropic`` / ``gpt(-N(.N))?``) —
             refuses ``ChatGPT illustration`` / ``OpenAI
             image`` / ``Open AI illustration`` / ``open-ai
             render`` / ``Anthropic creation`` / ``GPT-4
             output`` while keeping ``GPS map`` / ``Egyptian
             art`` / ``open book`` / ``open source code`` /
             ``open API documentation`` / ``Open SSL diagram``
             benign (the ``\\b`` boundary keeps ``gpt`` out of
             ``Egypt`` / ``GPS``; ``open`` followed by a
             non-``ai`` word still passes); ``claude`` /
             ``gemini`` + (model version OR distribution-style
             noun) — refuses ``Claude 3 illustration`` /
             ``Claude opus render`` / ``Claude renderings`` /
             ``Gemini Pro output`` while keeping
             ``Claude Monet painting`` / ``Claude Shannon
             information theory`` / ``Gemini constellation`` /
             ``Gemini horoscope reading`` benign).
      MAN11  no two manifest entries share a filename
             (case-sensitive; the basenames must match what the
             discovery pass on disk found).
      MAN12  (cross-check, only runs when image discovery succeeded)
             the manifest filename set equals the discovered set —
             no orphan, no missing.
    """
    if _has_uri_scheme(manifest_path_str):
        return None, None, [
            f"--manifest argument {manifest_path_str!r} looks "
            f"URI-shaped (MAN1); only local file paths are accepted."
        ]

    manifest_path = Path(manifest_path_str)

    if manifest_path.is_symlink():
        try:
            tgt = os.readlink(manifest_path)
        except OSError:
            tgt = "<unreadable>"
        return None, None, [
            f"--manifest {manifest_path} is a symlink (-> {tgt}) "
            f"(MAN2); refused so a symlink target cannot redirect "
            f"what bytes the helper ingests."
        ]

    forbidden_ancestor = _forbidden_symlink_ancestor(manifest_path)
    if forbidden_ancestor is not None:
        ancestor, tgt = forbidden_ancestor
        return None, None, [
            f"--manifest {manifest_path} has a symlink ancestor "
            f"{ancestor} (-> {tgt}) (MAN3); refused so a symlink "
            f"in the operator's typed path cannot redirect what "
            f"bytes the helper ingests."
        ]

    if not manifest_path.exists():
        return None, None, [
            f"--manifest {manifest_path} does not exist (MAN4)."
        ]
    if not manifest_path.is_file():
        return None, None, [
            f"--manifest {manifest_path} is not a regular file "
            f"(MAN4)."
        ]

    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, None, [
            f"--manifest {manifest_path} cannot be read as UTF-8: "
            f"{type(exc).__name__}: {exc} (MAN5)."
        ]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, None, [
            f"--manifest {manifest_path} is not valid JSON: "
            f"{exc} (MAN5)."
        ]

    if not isinstance(data, dict):
        return None, None, [
            f"--manifest {manifest_path} root is "
            f"{type(data).__name__}; expected a JSON object (MAN5)."
        ]

    failures: list[str] = []

    required_root = set(_MANIFEST_REQUIRED_ROOT_KEYS)
    present_root = set(data.keys())
    missing_root = required_root - present_root
    extras_root = present_root - required_root
    if missing_root:
        failures.append(
            f"--manifest {manifest_path} root missing key(s) "
            f"{sorted(missing_root)!r} (MAN6); required: "
            f"{sorted(required_root)!r}."
        )
    if extras_root:
        failures.append(
            f"--manifest {manifest_path} root has unknown key(s) "
            f"{sorted(extras_root)!r} (MAN6); allowed: "
            f"{sorted(required_root)!r}."
        )
    if failures:
        return None, None, failures

    if data.get("schema_version") != _MANIFEST_SCHEMA_VERSION:
        return None, None, [
            f"--manifest {manifest_path} schema_version="
            f"{data.get('schema_version')!r}; expected "
            f"{_MANIFEST_SCHEMA_VERSION!r} (MAN7)."
        ]

    images = data.get("images")
    if not isinstance(images, list):
        return None, None, [
            f"--manifest {manifest_path} images field is "
            f"{type(images).__name__}; expected a JSON array (MAN8)."
        ]
    if not images:
        return None, None, [
            f"--manifest {manifest_path} images array is empty; the "
            f"helper refuses to stage a zero-image deck (MAN8)."
        ]

    entry_required = set(_MANIFEST_IMAGE_REQUIRED_KEYS)
    seen_filenames: dict[str, int] = {}
    ordered_entries: list[dict] = []

    for idx, entry in enumerate(images):
        if not isinstance(entry, dict):
            failures.append(
                f"--manifest images[{idx}] is "
                f"{type(entry).__name__}; expected a JSON object "
                f"(MAN9)."
            )
            continue
        entry_present = set(entry.keys())
        entry_missing = entry_required - entry_present
        entry_extras = entry_present - entry_required
        if entry_missing:
            failures.append(
                f"--manifest images[{idx}] missing field(s) "
                f"{sorted(entry_missing)!r} (MAN9); required: "
                f"{sorted(entry_required)!r}."
            )
        if entry_extras:
            failures.append(
                f"--manifest images[{idx}] has unknown field(s) "
                f"{sorted(entry_extras)!r} (MAN9); allowed: "
                f"{sorted(entry_required)!r}."
            )
        if entry_missing or entry_extras:
            continue

        field_failed = False
        cleaned: dict[str, str] = {}
        for field, max_len in (
            ("filename", _MAX_FILENAME_LEN),
            ("slide_title", _MAX_SLIDE_TITLE_LEN),
            ("alt_text", _MAX_ALT_TEXT_LEN),
            ("intended_use", _MAX_INTENDED_USE_LEN),
        ):
            value, fail = _safe_manifest_string(
                field=field, value=entry[field],
                max_len=max_len, entry_idx=idx,
            )
            if fail:
                failures.append(fail)
                field_failed = True
            else:
                cleaned[field] = value
        if field_failed:
            continue

        fname = cleaned["filename"]
        if fname in seen_filenames:
            failures.append(
                f"--manifest images[{idx}].filename={fname!r} is a "
                f"duplicate of images[{seen_filenames[fname]}] "
                f"(MAN11); each operator image must appear in the "
                f"manifest exactly once."
            )
            continue
        seen_filenames[fname] = idx
        ordered_entries.append(cleaned)

    if failures:
        return None, None, failures

    # MAN12 — coverage cross-check. Only runs when image discovery
    # succeeded; otherwise the helper already reported image failures
    # at the IG-gate layer, and reporting a "coverage mismatch" on
    # top would be redundant noise the operator has to wade through.
    if discovered_filenames is not None:
        discovered_set = set(discovered_filenames)
        manifest_set = set(seen_filenames.keys())
        orphan = manifest_set - discovered_set
        missing = discovered_set - manifest_set
        if orphan:
            failures.append(
                f"--manifest {manifest_path} names filename(s) "
                f"{sorted(orphan)!r} not present under --images-dir "
                f"(MAN12); the manifest must cover only discovered "
                f"images."
            )
        if missing:
            failures.append(
                f"--manifest {manifest_path} does not name "
                f"discovered filename(s) {sorted(missing)!r} "
                f"(MAN12); the manifest must cover every discovered "
                f"image exactly once."
            )
        if failures:
            return None, None, failures

    return ordered_entries, manifest_path, []


# ---------------------------------------------------------------------------
# Optional <bundle>/generated_provenance.json sidecar validation.
# ---------------------------------------------------------------------------

# Closed enums for the optional generated-image provenance sidecar. The
# sidecar is a synthetic / mock-safe local metadata file that describes
# operator intent for generated image bytes already listed under
# <bundle>/images/. It is local-only — the helper does NOT call D-One,
# MCP, Qoder, a network, a model API, an image search, or telemetry to
# materialise the bytes; the sidecar only records the operator's
# declared intent for review.
_SIDECAR_SCHEMA_VERSION = "1"
_SIDECAR_REQUIRED_ROOT_KEYS: tuple[str, ...] = ("entries", "schema_version")
_SIDECAR_ENTRY_REQUIRED_KEYS: tuple[str, ...] = (
    "filename", "generator_source", "intent_summary",
    "placement_role", "subject_domain", "text_policy",
)
_SIDECAR_ENTRY_OPTIONAL_KEYS: tuple[str, ...] = ("custom_descriptor",)
# Generator source enum stays a single-value closed set today. The
# sidecar exists to describe synthetic / mock bytes the operator
# already staged under <bundle>/images/. Adding values later would
# require the operator to opt in via a new enum, but the helper itself
# does NOT call any generator — the enum names the operator's
# declared source, not a runtime touchpoint.
_SIDECAR_ALLOWED_GENERATOR_SOURCES: frozenset[str] = frozenset({
    "mock_generated",
})
# Closed enums mirror the repo's existing taxonomy in
# schemas/generated_image_provenance.schema.json (placement_role) and
# the mock-image taxonomy values exercised by the sibling smokes (the
# text_policy / subject_domain vocabularies). Kept small + closed so a
# typo refuses with a clean diagnostic instead of slipping in
# free-form prose.
_SIDECAR_ALLOWED_PLACEMENT_ROLES: frozenset[str] = frozenset({
    "hero_page", "local_region",
})
_SIDECAR_ALLOWED_TEXT_POLICIES: frozenset[str] = frozenset({
    "no_text", "decorative_glyphs", "caption_safe",
})
_SIDECAR_ALLOWED_SUBJECT_DOMAINS: frozenset[str] = frozenset({
    "abstract_marker", "background_pattern", "data_visual_concept",
    "icon_concept", "process_concept",
})
_SIDECAR_INTENT_SUMMARY_MAX_LEN = 200
# Pattern-locked optional descriptor. Lowercase identifier with
# underscores / digits — same shape the repo's other taxonomy fields
# use. Bounded length keeps a tampered sidecar from smuggling a long
# prose paragraph into the review-package README via the descriptor.
_SIDECAR_CUSTOM_DESCRIPTOR_REGEX = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# Sidecar-only field set that the absent-sidecar enforcement refuses
# to find on any ``image_provenance`` row when
# ``summary.generated_provenance`` is null. Shared by the helper
# truth-checker, the review-package validator's mirror gate, and the
# self-test GP-ABSENT shape gate so one source of truth covers every
# leak surface.
_ABSENT_SIDECAR_LEAK_FIELDS: frozenset[str] = frozenset({
    "generator_source", "intent_summary", "placement_role",
    "text_policy", "subject_domain", "custom_descriptor",
})


def _safe_sidecar_intent_summary(
    *,
    value: object,
    entry_idx: int,
) -> tuple[str | None, str | None]:
    """Validate the sidecar ``intent_summary`` free-text field. Reuses
    the same safe-string deny vocabularies the manifest gate applies
    (URL/URI, path separator, credential / token / API-key shape,
    public upload / share / hosting wording, raw-source / confidential
    / customer marker, positive D-One / MCP / Qoder / model API /
    image search / network / telemetry success claim). Returns
    ``(cleaned_or_None, failure_or_None)``."""
    if not isinstance(value, str):
        return None, (
            f"generated_provenance.entries[{entry_idx}].intent_summary "
            f"is {type(value).__name__}, expected string (GP10)."
        )
    if not value:
        return None, (
            f"generated_provenance.entries[{entry_idx}].intent_summary "
            f"is empty; expected a non-empty string (GP10)."
        )
    if len(value) > _SIDECAR_INTENT_SUMMARY_MAX_LEN:
        return None, (
            f"generated_provenance.entries[{entry_idx}].intent_summary "
            f"is {len(value)} chars; expected <= "
            f"{_SIDECAR_INTENT_SUMMARY_MAX_LEN} (GP10)."
        )
    if value != value.strip():
        return None, (
            f"generated_provenance.entries[{entry_idx}].intent_summary="
            f"{value!r} has leading or trailing whitespace; trim and "
            f"retry (GP10)."
        )
    if any(ord(ch) < 0x20 for ch in value):
        return None, (
            f"generated_provenance.entries[{entry_idx}].intent_summary "
            f"contains a control character (GP10); refused so the "
            f"review-package text never carries a non-printable byte."
        )
    if "://" in value:
        return None, (
            f"generated_provenance.entries[{entry_idx}].intent_summary="
            f"{value!r} contains '://' (URL-shaped); refused — the "
            f"sidecar is local-only metadata (GP10)."
        )
    if _has_uri_scheme(value):
        return None, (
            f"generated_provenance.entries[{entry_idx}].intent_summary="
            f"{value!r} starts with a URI scheme; refused — the "
            f"sidecar is local-only metadata (GP10)."
        )
    # Mid-text dangerous single-colon URI schemes
    # (``data:image/png;base64,...`` / ``mailto:ops@example`` /
    # ``javascript:alert(1)`` / ``file:/etc/passwd`` etc.) are missed
    # by the ``://`` substring check AND by the start-anchored
    # ``_URI_SCHEME_PREFIX``. The validator catches them on a final
    # text scan of the produced summary.json, but the boundary
    # should refuse at the operator entry point so a sidecar
    # carrying an embedded ``data:`` blob is never written into the
    # review package in the first place.
    dangerous_hit = _DANGEROUS_URI_SCHEME_REGEX.search(value)
    if dangerous_hit is not None:
        return None, (
            f"generated_provenance.entries[{entry_idx}].intent_summary="
            f"{value!r} contains a dangerous single-colon URI scheme "
            f"({dangerous_hit.group('scheme').lower()!r}); refused — "
            f"data: / file: / javascript: / mailto: / etc. embedded "
            f"in operator metadata leak local-FS / browser / contact "
            f"shapes the lane refuses to surface (GP10)."
        )
    if "/" in value or "\\" in value:
        return None, (
            f"generated_provenance.entries[{entry_idx}].intent_summary="
            f"{value!r} contains a path separator; refused — the field "
            f"is a phrase, not a path (GP10)."
        )
    lower = value.lower()
    for token in _DENY_CREDENTIAL:
        if token in lower:
            return None, (
                f"generated_provenance.entries[{entry_idx}]."
                f"intent_summary contains credential-shaped substring "
                f"{token!r}; refused — the sidecar does NOT receive "
                f"credentials (GP10)."
            )
    if _OPENAI_KEY_REGEX.search(value):
        return None, (
            f"generated_provenance.entries[{entry_idx}].intent_summary "
            f"contains an API-key-shaped token (sk-XXXX...); refused "
            f"(GP10)."
        )
    for token in _DENY_UPLOAD:
        if token in lower:
            return None, (
                f"generated_provenance.entries[{entry_idx}]."
                f"intent_summary contains upload / share / hosting "
                f"substring {token!r}; refused — the sidecar is "
                f"local-only and does NOT publish outputs (GP10)."
            )
    public_share_hit = _DENY_PUBLIC_SHARE_REGEX.search(value)
    if public_share_hit is not None:
        return None, (
            f"generated_provenance.entries[{entry_idx}]."
            f"intent_summary={value!r} matches public-share / "
            f"public-hosting wording {public_share_hit.group(0)!r}; "
            f"refused — the sidecar is local-only and does NOT "
            f"publish outputs (GP10)."
        )
    for token in _DENY_CONFIDENTIAL:
        if token in lower:
            return None, (
                f"generated_provenance.entries[{entry_idx}]."
                f"intent_summary contains confidential / customer "
                f"marker {token!r}; refused — the sidecar does NOT "
                f"receive raw confidential or customer text (GP10)."
            )
    if _FAKE_SUCCESS_REGEX.search(value):
        return None, (
            f"generated_provenance.entries[{entry_idx}]."
            f"intent_summary={value!r} mentions an upstream service "
            f"this lane does NOT call (D-One, MCP, Qoder, model API, "
            f"image search, network, telemetry) or claims a "
            f"production / real / successful generation by an AI "
            f"brand the helper has not invoked; refused (GP10)."
        )
    return value, None


def _validate_generated_provenance_sidecar(
    sidecar_path_str: str,
    discovered_filenames: list[str] | None,
) -> tuple[list[dict] | None, Path | None, list[str]]:
    """Validate the optional ``<bundle>/generated_provenance.json``
    sidecar.

    Returns ``(entries_or_None, resolved_path_or_None, failures)``.
    The caller MUST treat the sidecar as refused whenever ``failures``
    is non-empty OR ``entries`` is ``None``. The sidecar is local-only
    metadata describing the operator's declared intent for the
    generated / mock image bytes already staged under
    ``<bundle>/images/``. The helper itself does NOT call D-One, MCP,
    Qoder, a network, a model API, an image search, or telemetry to
    materialise those bytes.

    Gates fire in order, BEFORE any pipeline subprocess:

      GP1   URI-shaped argument.
      GP2   sidecar path is itself a symlink (broken or resolvable).
      GP3   any ancestor up to the filesystem root is a symlink
            (closed system aliases like ``/tmp -> /private/tmp``
            remain accepted via ``_forbidden_symlink_ancestor``).
      GP4   path exists and is a regular non-symlink file.
      GP5   the file parses as a single UTF-8 JSON document AND the
            root is a JSON object (not an array / scalar / null).
      GP6   the root carries exactly the required keys (no extras,
            no missing — schema_version + entries).
      GP7   ``schema_version`` equals ``_SIDECAR_SCHEMA_VERSION``
            ("1") verbatim.
      GP8   ``entries`` is a non-empty JSON array of objects whose
            top-level keys are a subset of the required + optional
            sets (no extras), with EVERY required key present.
      GP9   per-entry enum gates: ``generator_source`` in
            ``_SIDECAR_ALLOWED_GENERATOR_SOURCES``; ``placement_role``
            in ``_SIDECAR_ALLOWED_PLACEMENT_ROLES``; ``text_policy``
            in ``_SIDECAR_ALLOWED_TEXT_POLICIES``; ``subject_domain``
            in ``_SIDECAR_ALLOWED_SUBJECT_DOMAINS``.
      GP10  ``intent_summary`` passes the same safe-string gates
            ``--manifest`` free-text fields apply (URL / URI, path
            separator, credential / token / API-key shape, public
            upload / share / hosting wording, raw-source / confidential
            / customer marker, positive D-One / MCP / Qoder / model
            API / image search / network / telemetry / AI-brand
            success claim).
      GP11  optional ``custom_descriptor``, when present, matches
            ``^[a-z][a-z0-9_]{0,63}$``. The pattern-lock keeps a
            tampered sidecar from smuggling free-form prose through
            an "optional" slot.
      GP12  ``filename`` is a string equal to one of the discovered
            image filenames; no two sidecar entries share the same
            filename.
      GP13  (cross-check, only runs when image discovery succeeded)
            the sidecar filename set equals the discovered set —
            no orphan, no missing.
    """
    if _has_uri_scheme(sidecar_path_str):
        return None, None, [
            f"--generated-provenance argument {sidecar_path_str!r} "
            f"looks URI-shaped (GP1); only local file paths are "
            f"accepted."
        ]

    sidecar_path = Path(sidecar_path_str)

    if sidecar_path.is_symlink():
        try:
            tgt = os.readlink(sidecar_path)
        except OSError:
            tgt = "<unreadable>"
        return None, None, [
            f"generated_provenance sidecar {sidecar_path} is a "
            f"symlink (-> {tgt}) (GP2); refused so a symlink target "
            f"cannot redirect what bytes the helper ingests."
        ]

    forbidden_ancestor = _forbidden_symlink_ancestor(sidecar_path)
    if forbidden_ancestor is not None:
        ancestor, tgt = forbidden_ancestor
        return None, None, [
            f"generated_provenance sidecar {sidecar_path} has a "
            f"symlink ancestor {ancestor} (-> {tgt}) (GP3); refused "
            f"so a symlink in the operator's typed path cannot "
            f"redirect what bytes the helper ingests."
        ]

    if not sidecar_path.exists() or not sidecar_path.is_file():
        return None, None, [
            f"generated_provenance sidecar {sidecar_path} is not a "
            f"regular file (GP4)."
        ]

    try:
        raw_text = sidecar_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, None, [
            f"generated_provenance sidecar {sidecar_path} cannot be "
            f"read as UTF-8 (GP5): {type(exc).__name__}: {exc}."
        ]
    try:
        root = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return None, None, [
            f"generated_provenance sidecar {sidecar_path} does not "
            f"parse as JSON (GP5): {exc}."
        ]
    if not isinstance(root, dict):
        return None, None, [
            f"generated_provenance sidecar {sidecar_path} root is "
            f"{type(root).__name__}, expected JSON object (GP5)."
        ]

    failures: list[str] = []

    root_keys = set(root.keys())
    expected_root = set(_SIDECAR_REQUIRED_ROOT_KEYS)
    missing_root = expected_root - root_keys
    extra_root = root_keys - expected_root
    if missing_root or extra_root:
        return None, None, [
            f"generated_provenance sidecar {sidecar_path} root keys "
            f"{sorted(root_keys)!r} do not equal exactly "
            f"{sorted(expected_root)!r} (GP6); missing="
            f"{sorted(missing_root)!r}, extra={sorted(extra_root)!r}."
        ]

    schema_version = root.get("schema_version")
    if schema_version != _SIDECAR_SCHEMA_VERSION:
        return None, None, [
            f"generated_provenance sidecar {sidecar_path}."
            f"schema_version={schema_version!r}; expected "
            f"{_SIDECAR_SCHEMA_VERSION!r} verbatim (GP7)."
        ]

    entries_raw = root.get("entries")
    if not isinstance(entries_raw, list) or not entries_raw:
        return None, None, [
            f"generated_provenance sidecar {sidecar_path}.entries is "
            f"{type(entries_raw).__name__ if not isinstance(entries_raw, list) else 'empty list'}"
            f"; expected non-empty array (GP8)."
        ]

    required = set(_SIDECAR_ENTRY_REQUIRED_KEYS)
    optional = set(_SIDECAR_ENTRY_OPTIONAL_KEYS)
    ordered_entries: list[dict] = []
    seen_filenames: dict[str, int] = {}
    discovered_set = (
        set(discovered_filenames)
        if discovered_filenames is not None
        else None
    )
    for idx, entry in enumerate(entries_raw):
        if not isinstance(entry, dict):
            failures.append(
                f"generated_provenance sidecar entries[{idx}] is "
                f"{type(entry).__name__}, expected object (GP8)."
            )
            continue
        entry_keys = set(entry.keys())
        missing = required - entry_keys
        extra = entry_keys - (required | optional)
        if missing or extra:
            failures.append(
                f"generated_provenance sidecar entries[{idx}] keys "
                f"{sorted(entry_keys)!r} do not match required "
                f"{sorted(required)!r} (optional "
                f"{sorted(optional)!r}); missing={sorted(missing)!r}, "
                f"extra={sorted(extra)!r} (GP8)."
            )
            continue

        cleaned: dict = {}
        entry_failed = False

        filename = entry.get("filename")
        if not isinstance(filename, str) or not filename:
            failures.append(
                f"generated_provenance sidecar entries[{idx}]."
                f"filename={filename!r}; expected non-empty string "
                f"(GP12)."
            )
            entry_failed = True
        elif (
            discovered_set is not None
            and filename not in discovered_set
        ):
            failures.append(
                f"generated_provenance sidecar entries[{idx}]."
                f"filename={filename!r} is not present under "
                f"<bundle>/images/ (GP12)."
            )
            entry_failed = True
        else:
            cleaned["filename"] = filename

        generator_source = entry.get("generator_source")
        if generator_source not in _SIDECAR_ALLOWED_GENERATOR_SOURCES:
            failures.append(
                f"generated_provenance sidecar entries[{idx}]."
                f"generator_source={generator_source!r}; expected one "
                f"of {sorted(_SIDECAR_ALLOWED_GENERATOR_SOURCES)!r} "
                f"(GP9)."
            )
            entry_failed = True
        else:
            cleaned["generator_source"] = generator_source

        placement_role = entry.get("placement_role")
        if placement_role not in _SIDECAR_ALLOWED_PLACEMENT_ROLES:
            failures.append(
                f"generated_provenance sidecar entries[{idx}]."
                f"placement_role={placement_role!r}; expected one of "
                f"{sorted(_SIDECAR_ALLOWED_PLACEMENT_ROLES)!r} (GP9)."
            )
            entry_failed = True
        else:
            cleaned["placement_role"] = placement_role

        text_policy = entry.get("text_policy")
        if text_policy not in _SIDECAR_ALLOWED_TEXT_POLICIES:
            failures.append(
                f"generated_provenance sidecar entries[{idx}]."
                f"text_policy={text_policy!r}; expected one of "
                f"{sorted(_SIDECAR_ALLOWED_TEXT_POLICIES)!r} (GP9)."
            )
            entry_failed = True
        else:
            cleaned["text_policy"] = text_policy

        subject_domain = entry.get("subject_domain")
        if subject_domain not in _SIDECAR_ALLOWED_SUBJECT_DOMAINS:
            failures.append(
                f"generated_provenance sidecar entries[{idx}]."
                f"subject_domain={subject_domain!r}; expected one of "
                f"{sorted(_SIDECAR_ALLOWED_SUBJECT_DOMAINS)!r} (GP9)."
            )
            entry_failed = True
        else:
            cleaned["subject_domain"] = subject_domain

        intent_cleaned, intent_fail = _safe_sidecar_intent_summary(
            value=entry.get("intent_summary"),
            entry_idx=idx,
        )
        if intent_fail:
            failures.append(intent_fail)
            entry_failed = True
        else:
            cleaned["intent_summary"] = intent_cleaned

        if "custom_descriptor" in entry:
            cd = entry["custom_descriptor"]
            if (
                not isinstance(cd, str)
                or not _SIDECAR_CUSTOM_DESCRIPTOR_REGEX.fullmatch(cd)
            ):
                failures.append(
                    f"generated_provenance sidecar entries[{idx}]."
                    f"custom_descriptor={cd!r}; expected string "
                    f"matching ^[a-z][a-z0-9_]{{0,63}}$ (GP11)."
                )
                entry_failed = True
            else:
                cleaned["custom_descriptor"] = cd

        if entry_failed:
            continue

        fname = cleaned["filename"]
        if fname in seen_filenames:
            failures.append(
                f"generated_provenance sidecar entries[{idx}]."
                f"filename={fname!r} is a duplicate of entries["
                f"{seen_filenames[fname]}] (GP12); each operator "
                f"image must appear in the sidecar exactly once."
            )
            continue
        seen_filenames[fname] = idx
        ordered_entries.append(cleaned)

    if failures:
        return None, None, failures

    if discovered_set is not None:
        sidecar_set = set(seen_filenames.keys())
        orphan = sidecar_set - discovered_set
        missing = discovered_set - sidecar_set
        if orphan:
            failures.append(
                f"generated_provenance sidecar {sidecar_path} names "
                f"filename(s) {sorted(orphan)!r} not present under "
                f"<bundle>/images/ (GP13); the sidecar must cover "
                f"only discovered images."
            )
        if missing:
            failures.append(
                f"generated_provenance sidecar {sidecar_path} does "
                f"not name discovered filename(s) "
                f"{sorted(missing)!r} (GP13); the sidecar must cover "
                f"every discovered image exactly once."
            )
        if failures:
            return None, None, failures

    return ordered_entries, sidecar_path, []


# ---------------------------------------------------------------------------
# --write-manifest-template path gate.
# ---------------------------------------------------------------------------


def _validate_manifest_template_arg(
    template_path_str: str,
) -> tuple[Path | None, list[str]]:
    """Validate the ``--write-manifest-template`` argument and return the
    resolved path. The caller MUST treat the argument as refused whenever
    ``failures`` is non-empty OR ``path`` is ``None``, and MUST NOT write
    to the path in that case.

    Refuses, in order, BEFORE any filesystem mutation:

      MT1   URI-shaped argument (``file://`` / ``http://`` / ``data:`` /
            any RFC-3986 scheme prefix). The template writer accepts
            local paths only.
      MT2   the path itself is a symlink (broken or resolvable).
            Silently following a symlink would let an attacker who
            controls the link target redirect operator writes.
      MT3   any ancestor up to the filesystem root is a symlink. Same
            attack surface one level up — closed system aliases like
            ``/tmp -> /private/tmp`` remain accepted via
            ``_forbidden_symlink_ancestor``.
      MT4   the resolved path lexically anchors under ``REPO_ROOT``,
            compared BOTH case-sensitively (Linux semantics) AND on
            case-folded strings so a case-variant of the repo root
            (e.g. ``/Users/ROBERT/...`` vs ``/Users/robert/...`` on a
            case-insensitive APFS / HFS+ / NTFS volume) still trips
            the gate. ``Path.resolve()`` does NOT canonicalise the
            on-disk case, so a strict ``relative_to`` would otherwise
            miss the variant and let the writer land bytes under the
            committed tree on a case-insensitive filesystem.
      MT5   the path's parent either does not exist or is not a
            directory. Refusing to ``mkdir -p`` avoids masking a typo
            in the operator's argument.
      MT6   the path already exists (regular file, directory, or any
            other entry). The helper does not overwrite operator files;
            the operator must pass a fresh path.
    """
    if _has_uri_scheme(template_path_str):
        return None, [
            f"--write-manifest-template argument "
            f"{template_path_str!r} looks URI-shaped (MT1); only local "
            f"file paths are accepted."
        ]

    template_path = Path(template_path_str)

    if template_path.is_symlink():
        try:
            tgt = os.readlink(template_path)
        except OSError:
            tgt = "<unreadable>"
        return None, [
            f"--write-manifest-template {template_path} is a symlink "
            f"(-> {tgt}) (MT2); refused so a symlink target cannot "
            f"redirect operator writes."
        ]

    forbidden_ancestor = _forbidden_symlink_ancestor(template_path)
    if forbidden_ancestor is not None:
        ancestor, tgt = forbidden_ancestor
        return None, [
            f"--write-manifest-template {template_path} has a symlink "
            f"ancestor {ancestor} (-> {tgt}) (MT3); refused so a "
            f"symlink in the operator's typed path cannot redirect "
            f"operator writes."
        ]

    try:
        resolved = template_path.resolve(strict=False)
    except OSError as exc:
        return None, [
            f"--write-manifest-template {template_path} could not be "
            f"resolved: {type(exc).__name__}: {exc} (MT3)."
        ]

    repo_root = REPO_ROOT.resolve(strict=False)
    # Compare case-sensitively first (Linux / case-sensitive FS
    # semantics). If that misses, fall through to a case-folded
    # comparison so a case-variant of REPO_ROOT (e.g.
    # ``/Users/ROBERT/Desktop/...`` vs ``/Users/robert/Desktop/...``)
    # still refuses on case-insensitive APFS / HFS+ / NTFS volumes,
    # where ``Path.resolve()`` preserves the typed case rather than
    # canonicalising it. The case-folded check is anchored with the
    # platform separator so ``/repo`` and ``/repo-foo`` don't collide.
    under_root = False
    try:
        resolved.relative_to(repo_root)
        under_root = True
    except ValueError:
        resolved_folded = str(resolved).casefold()
        repo_root_folded = str(repo_root).casefold()
        if (
            resolved_folded == repo_root_folded
            or resolved_folded.startswith(repo_root_folded + os.sep)
        ):
            under_root = True
    if under_root:
        return None, [
            f"--write-manifest-template {resolved} lexically anchors "
            f"under REPO_ROOT={repo_root} (MT4); refused — manifest "
            f"templates must land outside the committed repo tree."
        ]

    if not template_path.parent.exists():
        return None, [
            f"--write-manifest-template {template_path} parent "
            f"{template_path.parent} does not exist (MT5); create the "
            f"parent explicitly before re-running so a typo cannot be "
            f"masked by an implicit mkdir -p."
        ]
    if not template_path.parent.is_dir():
        return None, [
            f"--write-manifest-template {template_path} parent "
            f"{template_path.parent} is not a directory (MT5); refused."
        ]

    if template_path.exists():
        return None, [
            f"--write-manifest-template {template_path} already exists "
            f"(MT6); refused to avoid overwriting an operator file. "
            f"Pass a fresh path."
        ]

    return template_path, []


# ---------------------------------------------------------------------------
# --plan-out path gate.
# ---------------------------------------------------------------------------


def _validate_plan_out_arg(
    plan_out_str: str,
) -> tuple[Path | None, list[str]]:
    """Validate the ``--plan-out`` argument and return the resolved path.
    The caller MUST treat the argument as refused whenever ``failures``
    is non-empty OR ``path`` is ``None``, and MUST NOT write to the path
    in that case (stale bytes on a pre-existing target are preserved).

    Mirrors the ``--write-manifest-template`` gate (MT1..MT6) so the two
    plan-only writers carry one consistent contract.

      PO1   URI-shaped argument (``file://`` / ``http://`` / ``data:`` /
            any RFC-3986 scheme prefix). The plan writer accepts local
            paths only.
      PO2   the path itself is a symlink (broken or resolvable).
            Silently following a symlink would let an attacker who
            controls the link target redirect operator writes.
      PO3   any ancestor up to the filesystem root is a symlink. Same
            attack surface one level up — closed system aliases like
            ``/tmp -> /private/tmp`` remain accepted via
            ``_forbidden_symlink_ancestor``.
      PO4   the resolved path lexically anchors under ``REPO_ROOT``,
            compared BOTH case-sensitively AND on case-folded strings so
            a case-variant of the repo root still trips the gate on
            case-insensitive APFS / HFS+ / NTFS volumes (matches the
            MT4 reasoning).
      PO5   the path's parent either does not exist or is not a
            directory. Refusing to ``mkdir -p`` avoids masking a typo in
            the operator's argument.
      PO6   the path already exists (regular file, directory, or any
            other entry). The plan writer does not overwrite operator
            files; stale bytes on a pre-existing target are preserved.
    """
    if _has_uri_scheme(plan_out_str):
        return None, [
            f"--plan-out argument {plan_out_str!r} looks URI-shaped "
            f"(PO1); only local file paths are accepted."
        ]

    plan_out = Path(plan_out_str)

    if plan_out.is_symlink():
        try:
            tgt = os.readlink(plan_out)
        except OSError:
            tgt = "<unreadable>"
        return None, [
            f"--plan-out {plan_out} is a symlink (-> {tgt}) (PO2); "
            f"refused so a symlink target cannot redirect operator "
            f"writes."
        ]

    forbidden_ancestor = _forbidden_symlink_ancestor(plan_out)
    if forbidden_ancestor is not None:
        ancestor, tgt = forbidden_ancestor
        return None, [
            f"--plan-out {plan_out} has a symlink ancestor "
            f"{ancestor} (-> {tgt}) (PO3); refused so a symlink in the "
            f"operator's typed path cannot redirect operator writes."
        ]

    try:
        resolved = plan_out.resolve(strict=False)
    except OSError as exc:
        return None, [
            f"--plan-out {plan_out} could not be resolved: "
            f"{type(exc).__name__}: {exc} (PO3)."
        ]

    repo_root = REPO_ROOT.resolve(strict=False)
    under_root = False
    try:
        resolved.relative_to(repo_root)
        under_root = True
    except ValueError:
        resolved_folded = str(resolved).casefold()
        repo_root_folded = str(repo_root).casefold()
        if (
            resolved_folded == repo_root_folded
            or resolved_folded.startswith(repo_root_folded + os.sep)
        ):
            under_root = True
    if under_root:
        return None, [
            f"--plan-out {resolved} lexically anchors under "
            f"REPO_ROOT={repo_root} (PO4); refused — plan files must "
            f"land outside the committed repo tree."
        ]

    if not plan_out.parent.exists():
        return None, [
            f"--plan-out {plan_out} parent {plan_out.parent} does not "
            f"exist (PO5); create the parent explicitly before "
            f"re-running so a typo cannot be masked by an implicit "
            f"mkdir -p."
        ]
    if not plan_out.parent.is_dir():
        return None, [
            f"--plan-out {plan_out} parent {plan_out.parent} is not a "
            f"directory (PO5); refused."
        ]

    if plan_out.exists():
        return None, [
            f"--plan-out {plan_out} already exists (PO6); refused to "
            f"avoid overwriting an operator file (stale bytes are "
            f"preserved). Pass a fresh path."
        ]

    return plan_out, []


# ---------------------------------------------------------------------------
# --approved-plan path gate (operator-mode reviewer-approved run lock).
# ---------------------------------------------------------------------------


def _validate_approved_plan_arg(
    approved_plan_str: str,
) -> tuple[Path | None, list[str]]:
    """Validate the ``--approved-plan`` argument and return the path.

    The argument is an OPERATOR-INPUT path (a previously-written
    ``--plan-out`` plan a reviewer has signed off on); it is READ, never
    written. The gate refuses every shape that would let an attacker
    substitute the bytes the helper compares against:

      AP1   URI-shaped argument (``file://`` / ``http://`` / any RFC-3986
            scheme prefix). The compare reads local files only.
      AP2   the path itself is a symlink (broken or resolvable). Silently
            following a symlink would let an attacker who controls the
            link target swap the approved bytes between approval time
            and run time.
      AP3   any ancestor up to the filesystem root is a symlink. Same
            attack surface one level up — closed system aliases like
            ``/tmp -> /private/tmp`` remain accepted via
            ``_forbidden_symlink_ancestor``.
      AP4   the path exists AND is a regular non-symlink file (a
            directory, FIFO, device, socket, or missing entry is
            refused).
    """
    if _has_uri_scheme(approved_plan_str):
        return None, [
            f"--approved-plan argument {approved_plan_str!r} looks "
            f"URI-shaped (AP1); only local file paths are accepted."
        ]

    approved_plan = Path(approved_plan_str)

    if approved_plan.is_symlink():
        try:
            tgt = os.readlink(approved_plan)
        except OSError:
            tgt = "<unreadable>"
        return None, [
            f"--approved-plan {approved_plan} is a symlink (-> {tgt}) "
            f"(AP2); refused so a symlink target cannot redirect which "
            f"bytes the helper compares against."
        ]

    forbidden_ancestor = _forbidden_symlink_ancestor(approved_plan)
    if forbidden_ancestor is not None:
        ancestor, tgt = forbidden_ancestor
        return None, [
            f"--approved-plan {approved_plan} has a symlink ancestor "
            f"{ancestor} (-> {tgt}) (AP3); refused so a symlink in the "
            f"operator's typed path cannot redirect which bytes the "
            f"helper compares against."
        ]

    if not approved_plan.exists():
        return None, [
            f"--approved-plan {approved_plan} does not exist (AP4); "
            f"the approved plan must be a regular local file produced "
            f"by a prior --plan-out run."
        ]
    if not approved_plan.is_file():
        return None, [
            f"--approved-plan {approved_plan} is not a regular file "
            f"(AP4); refused — directories, FIFOs, devices, and sockets "
            f"cannot be compared."
        ]

    return approved_plan, []


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


# Built-in default per-image manifest field values. Centralised so the
# pipeline-fixture composer (used by operator mode when --manifest is
# omitted) AND the manifest-template writer (--write-manifest-template
# mode) share one source of truth — a hand-edited template that the
# operator re-runs through normal operator mode produces byte-identical
# defaults to the no-manifest run.
_DEFAULT_INTENDED_USE = "spot illustration"


def _default_slide_title(image: _DiscoveredImage) -> str:
    return _cover_title_for(image)


def _default_alt_text(image: _DiscoveredImage) -> str:
    return (
        f"Operator-supplied local image "
        f"{image.operator_filename!r}."
    )


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
        # When --manifest is supplied, the operator-typed slide_title /
        # alt_text / intended_use flow through verbatim. When --manifest
        # is omitted, the helper's deterministic defaults (filename-
        # derived title, generic alt_text, fixed "spot illustration"
        # intended_use) are used — preserving the pre-manifest behaviour
        # byte-for-byte. The same defaults are written by the
        # --write-manifest-template mode so a hand-edited template that
        # the operator re-runs through normal operator mode produces
        # byte-identical defaults to the no-manifest run.
        title = image.slide_title or _default_slide_title(image)
        alt_text = image.alt_text or _default_alt_text(image)
        intended_use = image.intended_use or _DEFAULT_INTENDED_USE
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
            "alt_text": alt_text,
            "intended_use": intended_use,
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
    intended_slide_index: int,
    pptx_media_shas: dict[str, list[str]],
    part_to_referencing_slides: dict[str, list[int]],
    sidecar_entry: dict | None = None,
) -> dict:
    """Per-image provenance record. ``pptx_media_shas`` maps each
    operator sha256 to the sorted list of ``ppt/media/*`` parts that
    carry the same bytes; the empty list means the operator file did
    not embed (regression — the truth-checker refuses).
    ``part_to_referencing_slides`` projects
    ``inspect_pptx_inventory.slides[*].media_refs[*]`` (filtered to
    entries whose ``used_by_slide_blip`` is True) onto a
    ``{part_name: [slide_idx, ...]}`` map; the row's
    ``embedded_referencing_slides`` is the sorted union of those slide
    indices across the operator file's embedded media parts. The
    inventory's rels-only ``media_parts[*].referencing_slides`` is
    deliberately NOT used: a slide that declares an image rel without
    a matching ``<p:pic>`` in the slide body would false-green the
    placement check otherwise, mirroring the sibling
    ``image_placement_readback_smoke`` H4b blip-embed gate.
    ``intended_slide_index`` is the 1-based deck position the helper
    assigned to this operator filename (manifest array order when
    ``--manifest`` is supplied, filename-sorted order otherwise); it
    must appear in ``embedded_referencing_slides`` for the row to pass
    the truth-checker — ``placement_verified`` is the precomputed
    boolean a reviewer can read off the JSON without redoing the set
    membership test.

    The ``operator_slide_title`` / ``operator_alt_text`` /
    ``operator_intended_use`` keys are present iff the operator
    supplied them via ``--manifest`` (each one may flow through
    independently in principle, though in practice all four manifest
    string fields are checked together). When ``--manifest`` is
    omitted the keys are absent and the helper's deterministic
    defaults remain implicit (no operator-supplied override to echo)."""
    embedded_media_parts = sorted(
        pptx_media_shas.get(image.sha256, [])
    )
    ref_slides: set[int] = set()
    for part in embedded_media_parts:
        for slide_idx in part_to_referencing_slides.get(part, []):
            ref_slides.add(slide_idx)
    embedded_referencing_slides = sorted(ref_slides)
    entry = {
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
        "embedded_media_parts": embedded_media_parts,
        "intended_slide_index": intended_slide_index,
        "embedded_referencing_slides": embedded_referencing_slides,
        "placement_verified": (
            intended_slide_index in ref_slides
        ),
    }
    if image.slide_title is not None:
        entry["operator_slide_title"] = image.slide_title
    if image.alt_text is not None:
        entry["operator_alt_text"] = image.alt_text
    if image.intended_use is not None:
        entry["operator_intended_use"] = image.intended_use
    if sidecar_entry is not None:
        # The sidecar has already been validated (GP1..GP13); each
        # field flows through verbatim so the summary reviewer can
        # trace what intent the operator declared for the bytes that
        # embedded on this slide. Keys are present only when the
        # sidecar carried them — ``custom_descriptor`` stays optional.
        entry["generator_source"] = sidecar_entry["generator_source"]
        entry["intent_summary"] = sidecar_entry["intent_summary"]
        entry["placement_role"] = sidecar_entry["placement_role"]
        entry["text_policy"] = sidecar_entry["text_policy"]
        entry["subject_domain"] = sidecar_entry["subject_domain"]
        if "custom_descriptor" in sidecar_entry:
            entry["custom_descriptor"] = (
                sidecar_entry["custom_descriptor"]
            )
    return entry


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


def _part_to_blip_referencing_slides_from_inventory(
    inv: dict,
) -> dict[str, list[int]]:
    """Project ``inspect_pptx_inventory``'s
    ``slides[*].media_refs[*]`` onto a ``{part_name: [slide_idx, ...]}``
    map for the per-image provenance builder, using the **blip-
    confirmed** signal — ``used_by_slide_blip`` is True iff the slide's
    ``<a:blip r:embed>`` actually embeds the part. We deliberately do
    NOT use ``inv.media_parts[*].referencing_slides`` here because that
    field counts every slide whose ``_rels/slideN.xml.rels`` declares
    an image rel for the part, regardless of whether any ``<p:pic>``
    on the slide body actually embeds that rId — a rel declared but
    not used in the slide body would false-green a placement check
    that read ``media_parts[*].referencing_slides`` only. The
    sibling ``image_placement_readback_smoke`` closes the same gap
    via its blip-embed walker (H4b). We use the inventory output
    verbatim — the helper adds no new XML walker. Malformed entries
    are skipped silently; the truth-checker refuses on empty /
    missing referencing slides per operator filename in the consumer.
    """
    out: dict[str, set[int]] = {}
    for slide in inv.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        idx = slide.get("index")
        if not isinstance(idx, int) or isinstance(idx, bool):
            continue
        for ref in slide.get("media_refs") or []:
            if not isinstance(ref, dict):
                continue
            if ref.get("used_by_slide_blip") is not True:
                continue
            resolved = ref.get("resolved")
            if (
                not isinstance(resolved, str)
                or not resolved.startswith("ppt/media/")
            ):
                continue
            out.setdefault(resolved, set()).add(idx)
    return {part: sorted(slides) for part, slides in out.items()}


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


# ---------------------------------------------------------------------------
# Visual-quality review (post-pipeline, pre-summary).
# ---------------------------------------------------------------------------


def _read_visual_quality_report(path: Path) -> dict | None:
    """Return the parsed JSON report at ``path`` or ``None`` when the file
    is missing, is a symlink, is unreadable, is not UTF-8, is not valid
    JSON, or does not decode to a JSON object. ``None`` routes through the
    truth-checker as ``visual_quality.report_parsed=False`` so a missing
    or malformed report fails closed without a separate raise site."""
    if not path.is_file() or path.is_symlink():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _project_visual_quality(
    *,
    outcome: _ToolOutcome,
    path: Path,
    report: dict | None,
) -> dict:
    """Project the validator's outcome + parsed report into the small
    stable ``visual_quality`` block surfaced in ``summary.json``. Reads
    ``totals.errors`` / ``totals.warnings`` from the report when both are
    integers; otherwise records ``report_parsed=False`` so the
    truth-checker refuses the run (the validator emits both keys on every
    happy or error-bearing run, so a missing / non-int value means the
    report shape is broken)."""
    error_count: int | None = None
    warning_count: int | None = None
    report_parsed = False
    if isinstance(report, dict):
        totals = report.get("totals")
        if isinstance(totals, dict):
            errs = totals.get("errors")
            warns = totals.get("warnings")
            if (
                isinstance(errs, int) and not isinstance(errs, bool)
                and isinstance(warns, int) and not isinstance(warns, bool)
            ):
                error_count = errs
                warning_count = warns
                report_parsed = True
    return {
        "rc": outcome.rc,
        "path": str(path),
        "report_parsed": report_parsed,
        "error_count": error_count,
        "warning_count": warning_count,
    }


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
    visual_quality_outcome: _ToolOutcome,
    visual_quality_path: Path,
    visual_quality_report: dict | None,
    pptx_media_shas: dict[str, list[str]],
    manifest_path: Path | None,
    approved_plan_evidence: dict | None,
    sidecar_entries: list[dict] | None = None,
    sidecar_path: Path | None = None,
) -> dict:
    contract_pass = _project_contract_gates(contract.stdout or "")
    part_to_referencing_slides = (
        _part_to_blip_referencing_slides_from_inventory(inventory)
    )
    sidecar_by_filename: dict[str, dict] = {}
    if sidecar_entries is not None:
        for entry in sidecar_entries:
            sidecar_by_filename[entry["filename"]] = entry
    generated_provenance_block: dict | None = None
    if sidecar_entries is not None:
        generated_provenance_block = {
            "path": (
                str(sidecar_path) if sidecar_path is not None else None
            ),
            "entry_count": len(sidecar_entries),
        }
    return {
        "schema_version": "1",
        "helper_id": "operator_local_images_to_editable_ppt",
        "real_d_one_status": _REAL_D_ONE_STATUS,
        "manifest_path": (
            str(manifest_path) if manifest_path is not None else None
        ),
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
            _provenance_for(
                image=img,
                intended_slide_index=idx,
                pptx_media_shas=pptx_media_shas,
                part_to_referencing_slides=part_to_referencing_slides,
                sidecar_entry=sidecar_by_filename.get(
                    img.operator_filename,
                ),
            )
            for idx, img in enumerate(images, start=1)
        ],
        # Sidecar evidence block. ``None`` when no
        # ``<bundle>/generated_provenance.json`` was supplied so the
        # summary's image_provenance rows carry no generator_source /
        # intent_summary / placement_role / text_policy /
        # subject_domain / custom_descriptor; a {path, entry_count}
        # dict otherwise so a reviewer can trace which local file
        # authored the per-image generated-image metadata.
        "generated_provenance": generated_provenance_block,
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
            "validate_visual_quality": {"rc": visual_quality_outcome.rc},
        },
        "visual_quality": _project_visual_quality(
            outcome=visual_quality_outcome,
            path=visual_quality_path,
            report=visual_quality_report,
        ),
        "notes": {
            "scope": _HELPER_SCOPE_NOTE,
            "embed_surface": _HELPER_EMBED_SURFACE_NOTE,
        },
        "explicit_boundaries": list(_EXPLICIT_BOUNDARIES),
        # Reviewer-approved run lock evidence. None when the operator
        # did not pass --approved-plan; a {path, sha256, matched=True}
        # dict when they did. The summary itself is written ONLY after
        # the approved-plan compare passed AND the summary truth-check
        # passed, so matched=True is the only valid value here — a
        # tampered matched=False fails the truth-check and refuses the
        # run. Reviewers can confirm the lock by running
        # ``sha256sum <approved_plan.path>`` against the recorded
        # sha256 and verifying both numbers agree.
        "approved_plan": approved_plan_evidence,
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
        "validate_visual_quality",
    ):
        rc = (val.get(k) or {}).get("rc")
        if rc != 0:
            failures.append(
                f"summary.validators.{k}.rc={rc!r}; expected 0"
            )

    # visual_quality block — defense in depth over validators.rc above. The
    # validator writes its JSON report BEFORE returning 1 on per-slide
    # ERROR findings, so a missing or malformed report file (report_parsed
    # is False) means something more fundamental went wrong than a per-
    # slide finding — fail closed. Warnings (warning_count > 0) are
    # allowed; only error_count > 0 refuses.
    vq = summary.get("visual_quality") or {}
    vq_rc = vq.get("rc")
    if vq_rc != 0:
        failures.append(
            f"summary.visual_quality.rc={vq_rc!r}; expected 0"
        )
    if vq.get("report_parsed") is not True:
        failures.append(
            f"summary.visual_quality.report_parsed="
            f"{vq.get('report_parsed')!r}; expected True (the JSON "
            f"report at {vq.get('path')!r} must exist, parse as a JSON "
            f"object, and carry totals.errors / totals.warnings as ints)"
        )
    err_count = vq.get("error_count")
    if not isinstance(err_count, int) or err_count != 0:
        failures.append(
            f"summary.visual_quality.error_count={err_count!r}; "
            f"expected 0 (per-slide ERROR findings refuse the run; "
            f"warnings are allowed)"
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
            intended = entry.get("intended_slide_index")
            intended_valid = (
                isinstance(intended, int)
                and not isinstance(intended, bool)
                and intended >= 1
            )
            if not intended_valid:
                failures.append(
                    f"summary.image_provenance[{i}] for "
                    f"{entry.get('operator_filename')!r} has "
                    f"intended_slide_index={intended!r}; expected the "
                    f"1-based slide index the helper assigned to this "
                    f"operator filename"
                )
            ref_slides = entry.get("embedded_referencing_slides")
            ref_slides_valid = (
                isinstance(ref_slides, list)
                and ref_slides
                and all(
                    isinstance(s, int) and not isinstance(s, bool)
                    for s in ref_slides
                )
            )
            if not ref_slides_valid:
                failures.append(
                    f"summary.image_provenance[{i}] for "
                    f"{entry.get('operator_filename')!r} has "
                    f"embedded_referencing_slides={ref_slides!r}; "
                    f"expected a non-empty list of 1-based slide "
                    f"indices whose <a:blip r:embed> resolves to the "
                    f"operator's ppt/media part(s) per "
                    f"inspect_pptx_inventory.slides[*].media_refs[*] "
                    f"with used_by_slide_blip=True (the embedded "
                    f"ppt/media part must actually appear in some "
                    f"slide body, not just be declared as a rel)"
                )
            elif intended_valid and intended not in ref_slides:
                failures.append(
                    f"summary.image_provenance[{i}] for "
                    f"{entry.get('operator_filename')!r} has "
                    f"intended_slide_index={intended!r} not in "
                    f"embedded_referencing_slides={ref_slides!r}; the "
                    f"operator file must embed on its intended slide"
                )
            placement_verified = entry.get("placement_verified")
            expected_placement = (
                intended_valid
                and ref_slides_valid
                and intended in ref_slides
            )
            if placement_verified is not expected_placement:
                failures.append(
                    f"summary.image_provenance[{i}] for "
                    f"{entry.get('operator_filename')!r} has "
                    f"placement_verified={placement_verified!r}; "
                    f"expected {expected_placement!r} (must equal "
                    f"intended_slide_index in "
                    f"embedded_referencing_slides)"
                )

    # manifest_path is required to be present in the summary record
    # (either a non-empty string when --manifest was supplied, or None
    # when it was not). When set to a string, every provenance entry
    # MUST echo the operator-supplied slide_title / alt_text /
    # intended_use so a reviewer can read the manifest's intent out of
    # the summary without opening the source manifest file.
    manifest_in_summary = summary.get("manifest_path")
    if (
        manifest_in_summary is not None
        and not isinstance(manifest_in_summary, str)
    ):
        failures.append(
            f"summary.manifest_path={manifest_in_summary!r}; expected "
            f"either null (no --manifest supplied) or a non-empty "
            f"string path"
        )
    if isinstance(manifest_in_summary, str):
        if not manifest_in_summary:
            failures.append(
                f"summary.manifest_path is an empty string; expected "
                f"either null or a non-empty path"
            )
        if isinstance(prov, list):
            for i, entry in enumerate(prov):
                if not isinstance(entry, dict):
                    continue
                for field in (
                    "operator_slide_title",
                    "operator_alt_text",
                    "operator_intended_use",
                ):
                    val = entry.get(field)
                    if not isinstance(val, str) or not val:
                        failures.append(
                            f"summary.image_provenance[{i}].{field}="
                            f"{val!r}; expected non-empty string when "
                            f"--manifest is supplied"
                        )

    boundaries = summary.get("explicit_boundaries")
    if boundaries != list(_EXPLICIT_BOUNDARIES):
        failures.append(
            f"summary.explicit_boundaries={boundaries!r}; expected "
            f"the locked tuple {list(_EXPLICIT_BOUNDARIES)!r} verbatim"
        )

    # approved_plan is REQUIRED to be present: ``null`` when the run
    # was not locked against a reviewer-approved plan, an object
    # carrying exactly {path, sha256, matched=True} when it was. A
    # missing key is refused so a tampered summary cannot silently
    # erase the lock. A matched=False value is refused because the
    # approved-plan compare refuses the run with rc 2 BEFORE summary
    # creation on mismatch — by the time the summary exists, the only
    # valid recorded outcome is matched=True. The sha256 must be
    # 64-char lowercase hex so reviewers can pipe it to ``sha256sum``
    # without parsing.
    ap = summary.get("approved_plan", _MISSING)
    if ap is _MISSING:
        failures.append(
            "summary.approved_plan missing; expected null (no "
            "--approved-plan supplied) or {path, sha256, matched: True}"
        )
    elif ap is not None:
        if not isinstance(ap, dict):
            failures.append(
                f"summary.approved_plan={ap!r}; expected null or an "
                f"object"
            )
        else:
            unknown = sorted(
                set(ap.keys()) - {"path", "sha256", "matched"}
            )
            if unknown:
                failures.append(
                    f"summary.approved_plan has unknown key(s) "
                    f"{unknown!r}; expected exactly "
                    f"{{path, sha256, matched}}"
                )
            ap_path = ap.get("path")
            if not isinstance(ap_path, str) or not ap_path:
                failures.append(
                    f"summary.approved_plan.path={ap_path!r}; "
                    f"expected non-empty string (the --approved-plan "
                    f"path as the helper resolved it)"
                )
            ap_sha = ap.get("sha256")
            if (
                not isinstance(ap_sha, str)
                or not _SHA256_HEX_PATTERN.fullmatch(ap_sha)
            ):
                failures.append(
                    f"summary.approved_plan.sha256={ap_sha!r}; "
                    f"expected 64-character lowercase hex string "
                    f"(reviewers must be able to confirm via "
                    f"sha256sum on the approved-plan file)"
                )
            ap_matched = ap.get("matched")
            if ap_matched is not True:
                failures.append(
                    f"summary.approved_plan.matched={ap_matched!r}; "
                    f"expected True (the approved-plan compare refuses "
                    f"with rc 2 BEFORE summary creation on mismatch; "
                    f"only matched=True can reach the summary)"
                )

    # generated_provenance is REQUIRED to be present: ``null`` when no
    # ``<bundle>/generated_provenance.json`` sidecar was supplied, an
    # object carrying exactly ``{path, entry_count}`` when one was.
    # When non-null, every image_provenance row must additionally
    # carry generator_source / intent_summary / placement_role /
    # text_policy / subject_domain (optional custom_descriptor) — all
    # already enum-validated by GP9..GP11 before reaching the summary,
    # so the truth-checker just re-asserts the closed sets to refuse
    # a post-helper edit that downgrades a value off the allow-list.
    gp = summary.get("generated_provenance", _MISSING)
    if gp is _MISSING:
        failures.append(
            "summary.generated_provenance missing; expected null (no "
            "<bundle>/generated_provenance.json supplied) or "
            "{path, entry_count}"
        )
    elif gp is None:
        # Absent-sidecar enforcement. With ``generated_provenance``
        # set to null, no image_provenance row may carry any sidecar
        # field. Without this gate a tampered summary could set
        # generated_provenance to null AND inject generator_source /
        # placement_role / etc. onto rows, smuggling generated-image
        # claims into a deck where no sidecar was supplied. The
        # leak-field set is shared with the GP-ABSENT shape gate via
        # ``_ABSENT_SIDECAR_LEAK_FIELDS`` so one source of truth
        # covers both the in-helper truth-check and the self-test
        # negative proof.
        if isinstance(prov, list):
            for i, entry in enumerate(prov):
                if not isinstance(entry, dict):
                    continue
                leaked = sorted(
                    _ABSENT_SIDECAR_LEAK_FIELDS & set(entry.keys())
                )
                if leaked:
                    failures.append(
                        f"summary.image_provenance[{i}] carries "
                        f"sidecar field(s) {leaked!r} despite "
                        f"summary.generated_provenance=null; refused "
                        f"so a tampered summary cannot smuggle "
                        f"generated-image claims into an "
                        f"absent-sidecar run"
                    )
    elif gp is not None:
        if not isinstance(gp, dict):
            failures.append(
                f"summary.generated_provenance={gp!r}; expected null "
                f"or an object"
            )
        else:
            unknown = sorted(set(gp.keys()) - {"path", "entry_count"})
            if unknown:
                failures.append(
                    f"summary.generated_provenance has unknown key(s) "
                    f"{unknown!r}; expected exactly {{path, entry_count}}"
                )
            gp_path = gp.get("path")
            if not isinstance(gp_path, str) or not gp_path:
                failures.append(
                    f"summary.generated_provenance.path={gp_path!r}; "
                    f"expected non-empty string (the sidecar path as "
                    f"the helper resolved it)"
                )
            gp_count = gp.get("entry_count")
            if (
                not isinstance(gp_count, int)
                or isinstance(gp_count, bool)
                or gp_count != (image_count or -1)
            ):
                failures.append(
                    f"summary.generated_provenance.entry_count="
                    f"{gp_count!r}; expected {image_count!r} (one "
                    f"sidecar entry per operator image)"
                )
            if isinstance(prov, list):
                for i, entry in enumerate(prov):
                    if not isinstance(entry, dict):
                        continue
                    gs = entry.get("generator_source")
                    if gs not in _SIDECAR_ALLOWED_GENERATOR_SOURCES:
                        failures.append(
                            f"summary.image_provenance[{i}]."
                            f"generator_source={gs!r}; expected one "
                            f"of "
                            f"{sorted(_SIDECAR_ALLOWED_GENERATOR_SOURCES)!r} "
                            f"(sidecar supplied)"
                        )
                    intent = entry.get("intent_summary")
                    if not isinstance(intent, str) or not intent:
                        failures.append(
                            f"summary.image_provenance[{i}]."
                            f"intent_summary={intent!r}; expected "
                            f"non-empty string (sidecar supplied)"
                        )
                    pr = entry.get("placement_role")
                    if pr not in _SIDECAR_ALLOWED_PLACEMENT_ROLES:
                        failures.append(
                            f"summary.image_provenance[{i}]."
                            f"placement_role={pr!r}; expected one of "
                            f"{sorted(_SIDECAR_ALLOWED_PLACEMENT_ROLES)!r} "
                            f"(sidecar supplied)"
                        )
                    tp = entry.get("text_policy")
                    if tp not in _SIDECAR_ALLOWED_TEXT_POLICIES:
                        failures.append(
                            f"summary.image_provenance[{i}]."
                            f"text_policy={tp!r}; expected one of "
                            f"{sorted(_SIDECAR_ALLOWED_TEXT_POLICIES)!r} "
                            f"(sidecar supplied)"
                        )
                    sd = entry.get("subject_domain")
                    if sd not in _SIDECAR_ALLOWED_SUBJECT_DOMAINS:
                        failures.append(
                            f"summary.image_provenance[{i}]."
                            f"subject_domain={sd!r}; expected one of "
                            f"{sorted(_SIDECAR_ALLOWED_SUBJECT_DOMAINS)!r} "
                            f"(sidecar supplied)"
                        )
                    if "custom_descriptor" in entry:
                        cd = entry["custom_descriptor"]
                        if (
                            not isinstance(cd, str)
                            or not
                            _SIDECAR_CUSTOM_DESCRIPTOR_REGEX.fullmatch(
                                cd,
                            )
                        ):
                            failures.append(
                                f"summary.image_provenance[{i}]."
                                f"custom_descriptor={cd!r}; expected "
                                f"string matching "
                                f"^[a-z][a-z0-9_]{{0,63}}$ "
                                f"(sidecar supplied)"
                            )

    return failures


# ---------------------------------------------------------------------------
# Operator-facing README emission.
# ---------------------------------------------------------------------------


def _render_review_readme(summary: dict) -> str:
    """Render the operator-facing review README from the truth-checked
    summary. Concise Markdown — names the produced artifacts, the
    editable-PPT evidence, the provenance pointer, and the fixed
    local-only boundary statement. Derived ONLY from the summary the
    helper just wrote; no new schema, no extra filesystem reads."""
    slide_count = summary.get("slide_count")
    image_count = summary.get("image_count")
    embedded = summary.get("embedded_media_count")
    manifest_path = summary.get("manifest_path")
    manifest_line = (
        f"- Authored from operator manifest: `{manifest_path}`."
        if isinstance(manifest_path, str) and manifest_path
        else "- No operator manifest supplied; filename-sorted order "
             "and default per-image strings were applied."
    )
    # Generated-image provenance sidecar block. Included ONLY when a
    # ``<bundle>/generated_provenance.json`` was supplied AND validated
    # cleanly. The block names the sidecar path and lists the per-image
    # generator_source / intent_summary so a reviewer can read the
    # declared intent without opening summary.json. Omitted entirely
    # on absent-sidecar runs so the README does NOT imply generated-
    # image metadata that the operator did not actually supply.
    gp = summary.get("generated_provenance")
    prov = summary.get("image_provenance") or []
    generated_provenance_block: list[str] = []
    if isinstance(gp, dict) and isinstance(gp.get("path"), str):
        generated_provenance_block.append("## Generated image provenance")
        generated_provenance_block.append("")
        # The boundary sentence below is byte-identical to one of the
        # locked phrases in the review-package validator's
        # ``_BOUNDARY_NEGATION_PHRASES`` so the positive-claim scan
        # whitelists it. Don't reword without paired-updating that
        # tuple.
        generated_provenance_block.append(
            "This bundle included a local-only "
            "`generated_provenance.json` sidecar describing operator-"
            "declared intent for the embedded image bytes. "
            + _README_BOUNDARY_STATEMENT
        )
        generated_provenance_block.append("")
        generated_provenance_block.append(
            f"- sidecar path: `{gp.get('path')}`"
        )
        generated_provenance_block.append(
            f"- entry_count: `{gp.get('entry_count')}`"
        )
        generated_provenance_block.append("")
        generated_provenance_block.append(
            "Per-image rows surface under `summary.image_provenance[]` "
            "(`generator_source` / `intent_summary` / `placement_role` "
            "/ `text_policy` / `subject_domain` / optional "
            "`custom_descriptor`). Concise per-entry view:"
        )
        generated_provenance_block.append("")
        for entry in prov:
            if not isinstance(entry, dict):
                continue
            if entry.get("generator_source") is None:
                continue
            generated_provenance_block.append(
                f"- `{entry.get('operator_filename')}` — "
                f"{entry.get('generator_source')}; "
                f"placement_role={entry.get('placement_role')}; "
                f"text_policy={entry.get('text_policy')}; "
                f"subject_domain={entry.get('subject_domain')}; "
                f"intent_summary: {entry.get('intent_summary')!r}"
            )
        generated_provenance_block.append("")
    # Approved-plan lock evidence is included ONLY when the run was
    # locked against a reviewer-approved plan. Omitted entirely on
    # plain runs so the README does NOT imply approval that did not
    # happen (the operator goal explicitly forbids any approval claim
    # in the unlocked README).
    ap = summary.get("approved_plan")
    approved_plan_block: list[str] = []
    if isinstance(ap, dict) and ap.get("matched") is True:
        approved_plan_block = [
            "## Approved-plan lock",
            "",
            "This run was locked against a reviewer-approved plan. "
            "The helper built the same in-memory plan `--plan-out` "
            "would have written for the current `--images-dir` (and "
            "`--manifest`, when supplied) and verified — BEFORE any "
            "pipeline subprocess fired — that every per-image "
            "`filename` / `asset_id` / `media_type` / `byte_count` / "
            "`sha256` / `intended_slide_index` / `slide_title` / "
            "`alt_text` / `intended_use` matched the approved plan.",
            "",
            f"- approved plan path: `{ap.get('path')}`",
            f"- approved plan sha256: `{ap.get('sha256')}`",
            "",
            "Reviewers can confirm the lock by running "
            "`sha256sum <approved-plan-path>` and matching the "
            "result against the recorded sha256, or by reading "
            "`summary.json` field `approved_plan` (which carries the "
            "same `path`, `sha256`, and `matched: true` evidence).",
            "",
        ]
    lines = [
        "# Operator local-images review package",
        "",
        f"{image_count} operator image(s) embedded into a "
        f"{slide_count}-slide native editable `.pptx` from local "
        "PNG / JPG / JPEG bytes; `embedded_media_count="
        f"{embedded}` `ppt/media/*` part(s) carry the operator bytes "
        "byte-for-byte.",
        "",
        manifest_line,
        "",
        *generated_provenance_block,
        *approved_plan_block,
        "## Files in this review package",
        "",
        "- `deck.pptx` — native editable PPTX (one cover slide per "
        "operator image; editable title text + image_slot accent).",
        "- `summary.json` — truth-checked summary record (slide / "
        "image / embedded-media counts, minimal-evidence booleans, "
        "validator rc values, per-image provenance, visual-quality "
        "block, locked boundary statement).",
        "- `inventory.json` — `inspect_pptx_inventory` readback over "
        "`deck.pptx` (internal-only relationships, every embedded "
        "`ppt/media/*` part, per-slide media refs).",
        "- `visual_quality.json` — `validate_visual_quality` JSON "
        "report over the produced workspace's `render_models/` + "
        "`svg_previews/` pair (per-slide `totals.errors` / "
        "`totals.warnings`).",
        "- `workspace/source_image_assets.json` — source-attached "
        "registry the post-run `validate_source_image_assets` "
        "(G1..G13) validator ran against.",
        "- `reports/` — `pipeline_report.{json,txt}` and the "
        "runner-written inventory from the underlying "
        "`run_pipeline.py`.",
        "",
        "## Trace operator bytes through the deck",
        "",
        "See `summary.image_provenance[]` for the per-image evidence "
        "chain: each row maps `operator_filename` -> `sha256` -> "
        "embedded `ppt/media/*` part(s) (`embedded_media_parts`) -> "
        "`intended_slide_index` -> readback "
        "`embedded_referencing_slides` (the blip-confirmed slides "
        "whose `<a:blip r:embed>` resolves to the part) -> "
        "`placement_verified` (True iff the intended slide is in the "
        "readback set; the truth-checker refuses on False).",
        "",
        "## Boundary",
        "",
        _README_BOUNDARY_STATEMENT,
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Happy path.
# ---------------------------------------------------------------------------


def _run_happy_path(
    *,
    out_dir: Path,
    images: list[_DiscoveredImage],
    manifest_path: Path | None = None,
    approved_plan_evidence: dict | None = None,
    sidecar_entries: list[dict] | None = None,
    sidecar_path: Path | None = None,
) -> tuple[int, dict | None, Path | None]:
    """Build the fixture under ``out_dir``, drive the pipeline, run the
    validators, and write the summary. Returns ``(rc, summary,
    summary_path)``. Leaves every artifact on disk for inspection on
    failure too.

    ``manifest_path`` is the (already-validated) path to the optional
    ``--manifest`` JSON file, or ``None`` when the operator did not
    supply one. The path is echoed verbatim into ``summary.manifest_path``
    so a reviewer can trace which manifest authored the per-image
    operator_* strings in the provenance block.

    ``approved_plan_evidence`` is the (already-computed) {path, sha256,
    matched=True} dict when the operator passed ``--approved-plan`` and
    the compare passed, or ``None`` otherwise. Echoed verbatim into
    ``summary.approved_plan`` and rendered as the README's
    ``Approved-plan lock`` section when non-None.

    ``sidecar_entries`` is the (already-validated) list of per-filename
    sidecar entries from ``<bundle>/generated_provenance.json``, or
    ``None`` when the sidecar was absent. Each entry's
    generator_source / intent_summary / placement_role / text_policy /
    subject_domain / optional custom_descriptor flows verbatim into
    the matching ``summary.image_provenance[]`` row. ``sidecar_path``
    is the resolved path of the sidecar (echoed into
    ``summary.generated_provenance.path`` so reviewers can trace which
    file authored the rows)."""
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
    visual_quality_path = out_dir / "visual_quality.json"

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

    # Stage F — visual-quality review against the produced workspace's
    # render_models/ + svg_previews/ pair. Inspection-only; the validator
    # never mutates the workspace, never re-renders, never calls any
    # external service. The JSON report is written even on rc==1 (per-
    # slide ERROR findings), so a missing report file means something
    # more fundamental went wrong than a finding. Warnings do NOT fail
    # this stage; the truth-checker routes errors / nonzero rc / missing
    # or malformed report through summary.visual_quality.
    visual_quality_outcome = _run(
        "validate_visual_quality",
        [
            sys.executable, str(VALIDATE_VISUAL_QUALITY),
            "--workspace", str(workspace),
            "--output", str(visual_quality_path),
        ],
    )
    if visual_quality_outcome.ok:
        print(f"  [PASS] validate_visual_quality rc=0")
    else:
        print(
            f"  [WARN] validate_visual_quality "
            f"rc={visual_quality_outcome.rc} "
            f"(truth-checker will refuse)"
        )
        _print_outcome_tail(visual_quality_outcome)
    visual_quality_report = _read_visual_quality_report(visual_quality_path)

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
        visual_quality_outcome=visual_quality_outcome,
        visual_quality_path=visual_quality_path,
        visual_quality_report=visual_quality_report,
        pptx_media_shas=pptx_media_shas,
        manifest_path=manifest_path,
        approved_plan_evidence=approved_plan_evidence,
        sidecar_entries=sidecar_entries,
        sidecar_path=sidecar_path,
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

    # Stage G — operator-facing review README. Written AFTER the summary
    # truth-check passes so a tampered run cannot leave a positive-
    # looking README on disk; a write failure refuses the run rather
    # than letting a partial review package masquerade as complete.
    readme_path = out_dir / "README.md"
    try:
        readme_path.write_text(
            _render_review_readme(summary), encoding="utf-8",
        )
    except OSError as exc:
        print(
            f"  [FAIL] cannot write README at {readme_path}: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1, summary, None
    if not readme_path.is_file() or readme_path.is_symlink():
        print(
            f"  [FAIL] expected README at {readme_path} as a regular "
            f"non-symlink file"
        )
        return 1, summary, None
    print(f"  [PASS] review README written to {readme_path}")

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


def _run_operator_mode(
    *,
    images_dir_str: str,
    out_dir_str: str,
    manifest_path_str: str | None = None,
    approved_plan_path_str: str | None = None,
    generated_provenance_path_str: str | None = None,
) -> int:
    """Validate every operator argument, create ``--out-dir`` if
    needed, and drive the happy path. Returns 0 on success, 1 on any
    failure (with partial artifacts left under ``--out-dir`` for
    inspection), 2 on operator-input refusal (no filesystem mutation).

    When ``manifest_path_str`` is provided, the manifest is validated
    against the discovered images, the slide order is reordered to
    match the manifest's array order, and each discovered image is
    enriched with its operator-supplied slide_title / alt_text /
    intended_use. When omitted, the helper preserves its deterministic
    filename-sort behaviour and built-in default strings verbatim.

    When ``approved_plan_path_str`` is provided, the helper builds the
    SAME in-memory plan ``--plan-out`` would have written for the
    current ``--images-dir`` + ``--manifest`` combination, loads the
    operator-supplied approved plan, and refuses the run with rc 2
    BEFORE any pipeline subprocess fires or any out-dir artifact is
    created if the approved plan is malformed, carries a wrong
    schema_version / helper_id / mode, has boundary drift, or differs
    from the current inputs on image_count, slide_count, manifest_path,
    image order, or any per-image filename / asset_id / media_type /
    byte_count / sha256 / intended_slide_index / slide_title /
    alt_text / intended_use. On a clean match, normal mode behaves
    exactly as it does without ``--approved-plan``.

    When ``generated_provenance_path_str`` is provided (today only via
    a ``<bundle>/generated_provenance.json`` sidecar — the helper does
    not surface an explicit operator-typed flag), the sidecar is
    validated against the discovered image filenames (GP1..GP13) and
    each accepted per-filename entry flows through verbatim into the
    summary's ``image_provenance[]`` rows. The sidecar is local-only
    metadata: the helper does NOT call D-One, MCP, Qoder, a network,
    a model API, an image search, or telemetry to materialise any of
    the bytes it describes."""
    images, _images_dir, image_failures = _validate_images_dir_arg(
        images_dir_str,
    )
    out_dir, out_failures = _validate_out_dir_arg(out_dir_str)

    approved_plan_path: Path | None = None
    approved_plan_failures: list[str] = []
    if approved_plan_path_str is not None:
        approved_plan_path, approved_plan_failures = (
            _validate_approved_plan_arg(approved_plan_path_str)
        )

    manifest_failures: list[str] = []
    manifest_path: Path | None = None
    if manifest_path_str is not None:
        # Pass the discovered filenames in iff image discovery
        # succeeded. When it failed, the helper already has IG-gate
        # diagnostics to surface; piling a "manifest coverage
        # mismatch" MAN12 diagnostic on top would be redundant noise.
        # The MAN1..MAN11 structural gates still run so the operator
        # sees every manifest-side problem in the same pass.
        discovered_filenames = (
            [img.operator_filename for img in images]
            if images is not None
            else None
        )
        ordered_entries, manifest_path, manifest_failures = (
            _validate_manifest_arg(
                manifest_path_str, discovered_filenames,
            )
        )
        if (
            not image_failures
            and not manifest_failures
            and images is not None
            and ordered_entries is not None
        ):
            by_filename = {
                img.operator_filename: img for img in images
            }
            images = [
                replace(
                    by_filename[entry["filename"]],
                    slide_title=entry["slide_title"],
                    alt_text=entry["alt_text"],
                    intended_use=entry["intended_use"],
                )
                for entry in ordered_entries
            ]

    sidecar_failures: list[str] = []
    sidecar_entries: list[dict] | None = None
    sidecar_path: Path | None = None
    if generated_provenance_path_str is not None:
        # Reuses the post-manifest image ordering when --manifest was
        # also supplied: ``images`` already reflects manifest array
        # order at this point. The sidecar must cover exactly the
        # discovered filename set; it does NOT itself reorder slides.
        discovered_for_sidecar = (
            [img.operator_filename for img in images]
            if images is not None
            else None
        )
        sidecar_entries, sidecar_path, sidecar_failures = (
            _validate_generated_provenance_sidecar(
                generated_provenance_path_str,
                discovered_for_sidecar,
            )
        )

    # Report every argument refusal so the operator does not have to
    # re-run twice to find every input problem.
    if (
        image_failures
        or out_failures
        or manifest_failures
        or approved_plan_failures
        or sidecar_failures
        or images is None
        or out_dir is None
    ):
        for line in image_failures or []:
            print(f"FAIL: {line}", file=sys.stderr)
        for line in out_failures or []:
            print(f"FAIL: {line}", file=sys.stderr)
        for line in manifest_failures or []:
            print(f"FAIL: {line}", file=sys.stderr)
        for line in approved_plan_failures or []:
            print(f"FAIL: {line}", file=sys.stderr)
        for line in sidecar_failures or []:
            print(f"FAIL: {line}", file=sys.stderr)
        return 2

    # Reviewer-approved run lock. Runs AFTER every argument-shape gate
    # passes (so discovery + manifest semantics are already known good)
    # but BEFORE any out-dir mkdir / pipeline subprocess / out-dir
    # artifact write. A drift between the approved plan and the
    # current inputs refuses the run with rc 2 and leaves the out-dir
    # untouched (pre-existing bytes preserved; never mkdir'd if the
    # operator passed a fresh path).
    approved_plan_evidence: dict | None = None
    if approved_plan_path is not None:
        current_plan = _build_plan_body(
            images=images, manifest_path=manifest_path,
        )
        # _load_approved_plan returns (plan, sha256_of_loaded_bytes,
        # failures) — the digest is captured at read time so a later
        # re-read cannot hash different bytes than were compared
        # (TOCTOU race). Use the returned digest verbatim for the
        # summary evidence; do NOT re-read approved_plan_path here.
        approved_plan, approved_plan_sha256, load_failures = (
            _load_approved_plan(approved_plan_path)
        )
        if load_failures or approved_plan is None:
            for line in load_failures:
                print(f"FAIL: {line}", file=sys.stderr)
            return 2
        compare_failures = _compare_to_approved_plan(
            current=current_plan,
            approved=approved_plan,
            approved_plan_path=approved_plan_path,
        )
        if compare_failures:
            for line in compare_failures:
                print(f"FAIL: {line}", file=sys.stderr)
            print(
                "FAIL: --approved-plan does not match current inputs; "
                "refusing the run before any pipeline subprocess fires "
                "or any out-dir artifact is written. Re-run --plan-out "
                "against the current --images-dir (and --manifest, if "
                "supplied) and have a reviewer re-approve the resulting "
                "plan.",
                file=sys.stderr,
            )
            return 2
        approved_plan_evidence = {
            "path": str(approved_plan_path),
            "sha256": approved_plan_sha256,
            "matched": True,
        }

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

    manifest_arg_display = (
        f", --manifest {manifest_path}"
        if manifest_path is not None
        else ""
    )
    approved_plan_arg_display = (
        f", --approved-plan {approved_plan_path}"
        if approved_plan_path is not None
        else ""
    )
    sidecar_arg_display = (
        f", generated_provenance.json {sidecar_path}"
        if sidecar_path is not None
        else ""
    )
    print(
        f"=== operator_local_images_to_editable_ppt "
        f"(--images-dir {images_dir_str}, --out-dir {out_dir}"
        f"{manifest_arg_display}{approved_plan_arg_display}"
        f"{sidecar_arg_display}) ==="
    )
    rc, summary, summary_path = _run_happy_path(
        out_dir=out_dir, images=images, manifest_path=manifest_path,
        approved_plan_evidence=approved_plan_evidence,
        sidecar_entries=sidecar_entries,
        sidecar_path=sidecar_path,
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
# Manifest-template writer entrypoint.
# ---------------------------------------------------------------------------


def _run_template_write_mode(
    *,
    images_dir_str: str,
    template_path_str: str,
) -> int:
    """Validate every operator argument, discover the images, and write a
    starter manifest template. Returns 0 on success, 2 on operator-input
    refusal (no filesystem mutation), 1 on write failure.

    The template writer does NOT run the pipeline, does NOT produce a
    PPTX, does NOT produce a ``visual_quality.json`` report (the
    visual-quality validator only runs in normal operator mode against
    a produced workspace), does NOT touch any file under ``REPO_ROOT``,
    and does NOT call D-One / MCP / Qoder / a public network / a model
    API / an image search / telemetry. It composes the same
    image-discovery gate
    (IG1..IG9) the normal operator mode applies plus the
    ``--write-manifest-template`` path gate (MT1..MT6), then writes a
    deterministic JSON manifest whose ``images[]`` array carries one
    entry per discovered image, sorted by filename, with the same
    default ``slide_title`` / ``alt_text`` / ``intended_use`` values the
    helper would apply if the operator re-ran with no ``--manifest`` at
    all.

    The generated file is byte-compatible with the normal operator-mode
    ``--manifest`` input: a re-run such as
    ``--images-dir DIR --out-dir OUT --manifest <this-path>`` accepts
    the template verbatim, and the produced ``summary.json`` echoes
    each entry's ``slide_title`` / ``alt_text`` / ``intended_use`` under
    ``image_provenance[]`` exactly as for a hand-authored manifest.
    """
    images, _images_dir, image_failures = _validate_images_dir_arg(
        images_dir_str,
    )
    template_path, template_failures = _validate_manifest_template_arg(
        template_path_str,
    )

    if (
        image_failures
        or template_failures
        or images is None
        or template_path is None
    ):
        for line in image_failures or []:
            print(f"FAIL: {line}", file=sys.stderr)
        for line in template_failures or []:
            print(f"FAIL: {line}", file=sys.stderr)
        return 2

    body = {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "images": [
            {
                "filename": img.operator_filename,
                "slide_title": _default_slide_title(img),
                "alt_text": _default_alt_text(img),
                "intended_use": _DEFAULT_INTENDED_USE,
            }
            for img in images
        ],
    }

    print(
        f"=== operator_local_images_to_editable_ppt "
        f"(--images-dir {images_dir_str}, "
        f"--write-manifest-template {template_path}) ==="
    )
    for img in images:
        print(
            f"  image:     {img.operator_filename!r} "
            f"(id={img.asset_id!r}, {img.media_type}, "
            f"{img.byte_count} bytes, sha256={img.sha256[:12]}...)"
        )

    try:
        template_path.write_text(
            json.dumps(body, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(
            f"FAIL: cannot write --write-manifest-template "
            f"{template_path}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    if not template_path.is_file() or template_path.is_symlink():
        print(
            f"FAIL: expected --write-manifest-template "
            f"{template_path} as a regular non-symlink file after write",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK (manifest template): wrote {len(images)} image entr"
        f"{'y' if len(images) == 1 else 'ies'} to {template_path}. "
        f"Edit the slide_title / alt_text / intended_use fields as "
        f"needed, then re-run with --images-dir + --out-dir + "
        f"--manifest <this-path>. Local-only — does NOT call D-One, "
        f"MCP, Qoder, a public network, a model API, an image search, "
        f"or telemetry."
    )
    return 0


# ---------------------------------------------------------------------------
# Plan-only preflight entrypoint.
# ---------------------------------------------------------------------------


# Schema version locked alongside the manifest's; bump in lockstep if the
# plan-only output shape ever needs to evolve.
_PLAN_SCHEMA_VERSION = "1"
_PLAN_MODE = "plan_only"

# Fields the operator-mode --approved-plan compare walks per image row.
# Drift in any of these refuses the run with rc 2 BEFORE any pipeline
# subprocess fires or any out-dir artifact is written. Order is the
# compare order (first-mismatch wins per row).
_PLAN_ROW_COMPARE_FIELDS: tuple[str, ...] = (
    "filename",
    "asset_id",
    "media_type",
    "byte_count",
    "sha256",
    "intended_slide_index",
    "slide_title",
    "alt_text",
    "intended_use",
)


def _build_plan_body(
    *,
    images: list[_DiscoveredImage],
    manifest_path: Path | None,
) -> dict:
    """Build the in-memory plan body for the supplied (already
    discovered + manifest-enriched) image list.

    Shared between ``--plan-out`` (writes this body to disk) and the
    operator-mode ``--approved-plan`` compare (builds the same body
    in memory and compares it to the approved bytes BEFORE any pipeline
    subprocess fires). One source of truth means a reviewer who runs
    ``--plan-out`` and then re-runs operator mode with
    ``--approved-plan <that plan>`` against byte-identical inputs sees
    a clean match."""
    rows: list[dict] = []
    for idx, image in enumerate(images, start=1):
        title = image.slide_title or _default_slide_title(image)
        alt_text = image.alt_text or _default_alt_text(image)
        intended_use = image.intended_use or _DEFAULT_INTENDED_USE
        rows.append({
            "filename": image.operator_filename,
            "asset_id": image.asset_id,
            "media_type": image.media_type,
            "byte_count": image.byte_count,
            "sha256": image.sha256,
            "intended_slide_index": idx,
            "slide_title": title,
            "alt_text": alt_text,
            "intended_use": intended_use,
        })
    return {
        "schema_version": _PLAN_SCHEMA_VERSION,
        "helper_id": "operator_local_images_to_editable_ppt",
        "mode": _PLAN_MODE,
        "image_count": len(images),
        "slide_count": len(images),
        "manifest_path": (
            str(manifest_path) if manifest_path is not None else None
        ),
        "explicit_boundaries": list(_EXPLICIT_BOUNDARIES),
        "images": rows,
    }


def _is_strict_int(value: object) -> bool:
    """True iff ``value`` is a Python int AND NOT a bool. JSON
    ``true`` / ``false`` deserialises to ``True`` / ``False``, which
    ``isinstance(_, int)`` accepts (bool is an int subclass). Without
    this guard, an approved plan with a boolean in any int field would
    pass type validation AND compare-match the current 1 / 0 integer
    via Python's ``True == 1`` / ``False == 0`` equality, silently
    defeating the run lock."""
    return isinstance(value, int) and not isinstance(value, bool)


def _load_approved_plan(
    approved_plan: Path,
) -> tuple[dict | None, str | None, list[str]]:
    """Read + parse the operator's ``--approved-plan`` file and validate
    the top-level shape (schema_version, helper_id, mode, explicit_
    boundaries, image_count, slide_count, manifest_path, images array).

    Returns ``(plan_or_None, bytes_sha256_hex_or_None, failures)``.
    The caller MUST treat the plan as refused whenever ``failures`` is
    non-empty OR ``plan`` is ``None`` and refuse the run with rc 2
    BEFORE any pipeline subprocess fires.

    ``bytes_sha256_hex`` is the sha256 over the EXACT bytes the helper
    just read and parsed. The caller MUST use this digest when
    surfacing approved-plan evidence in the summary — re-reading the
    file later opens a TOCTOU window where a concurrent process could
    swap the bytes between compare-time and evidence-time, making the
    recorded digest hash bytes that were never actually compared. The
    digest is returned whenever the bytes were captured (even on
    subsequent structural failures), and ``None`` only when the
    initial ``read_bytes()`` call itself raised ``OSError``.

    The structural failures surfaced here cover everything the
    operator could trip on BEFORE the per-image compare runs: missing
    file bytes, unparseable JSON, non-object root, wrong/missing
    schema_version / helper_id / mode, boundary drift (the eight
    locked sentences), non-integer counts, non-string manifest_path,
    or a malformed images array."""
    try:
        raw_bytes = approved_plan.read_bytes()
    except OSError as exc:
        return None, None, [
            f"--approved-plan {approved_plan} could not be read: "
            f"{type(exc).__name__}: {exc}"
        ]
    # Capture the digest IMMEDIATELY after the read so every later
    # return path threads back the sha256 of exactly the bytes that
    # produced the parsed plan. No second read_bytes() anywhere in
    # this module — the digest is the only thing flowing forward.
    bytes_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    # Decode + JSON-parse separately so non-UTF-8 bytes (e.g. a binary
    # file the operator typed by mistake) fail closed with a clear
    # diagnostic instead of crashing on the read_text UnicodeDecodeError
    # path. Both failure modes return the same rc 2 contract.
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, bytes_sha256, [
            f"--approved-plan {approved_plan} is not valid UTF-8: "
            f"{type(exc).__name__}: {exc}"
        ]
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, bytes_sha256, [
            f"--approved-plan {approved_plan} is not valid JSON: "
            f"{type(exc).__name__}: {exc}"
        ]
    if not isinstance(plan, dict):
        return None, bytes_sha256, [
            f"--approved-plan {approved_plan} root is not a JSON object "
            f"(got {type(plan).__name__})."
        ]

    failures: list[str] = []

    if plan.get("schema_version") != _PLAN_SCHEMA_VERSION:
        failures.append(
            f"--approved-plan {approved_plan} schema_version="
            f"{plan.get('schema_version')!r}; expected "
            f"{_PLAN_SCHEMA_VERSION!r}."
        )
    expected_helper = "operator_local_images_to_editable_ppt"
    if plan.get("helper_id") != expected_helper:
        failures.append(
            f"--approved-plan {approved_plan} helper_id="
            f"{plan.get('helper_id')!r}; expected {expected_helper!r}."
        )
    if plan.get("mode") != _PLAN_MODE:
        failures.append(
            f"--approved-plan {approved_plan} mode={plan.get('mode')!r}; "
            f"expected {_PLAN_MODE!r}."
        )
    boundaries = plan.get("explicit_boundaries")
    if (
        not isinstance(boundaries, list)
        or tuple(boundaries) != _EXPLICIT_BOUNDARIES
    ):
        failures.append(
            f"--approved-plan {approved_plan} explicit_boundaries "
            f"differs from the helper's locked boundary statement "
            f"(boundary drift): approved={boundaries!r}, "
            f"current={list(_EXPLICIT_BOUNDARIES)!r}."
        )
    # Python's bool is a subclass of int (isinstance(True, int) is True
    # AND True == 1). Without the bool guard, an approved plan with
    # "image_count": true / "byte_count": true / "intended_slide_index":
    # false would (a) pass the int type check AND (b) compare-match the
    # current 1 / 0 integer value via equality, letting a tampered
    # approval bypass the run lock. _is_strict_int closes both holes.
    if not _is_strict_int(plan.get("image_count")):
        failures.append(
            f"--approved-plan {approved_plan} image_count="
            f"{plan.get('image_count')!r}; expected non-boolean "
            f"integer."
        )
    if not _is_strict_int(plan.get("slide_count")):
        failures.append(
            f"--approved-plan {approved_plan} slide_count="
            f"{plan.get('slide_count')!r}; expected non-boolean "
            f"integer."
        )
    mp = plan.get("manifest_path", "__MISSING__")
    if mp == "__MISSING__":
        failures.append(
            f"--approved-plan {approved_plan} missing manifest_path "
            f"key (expected string or null)."
        )
    elif mp is not None and not isinstance(mp, str):
        failures.append(
            f"--approved-plan {approved_plan} manifest_path={mp!r}; "
            f"expected string or null."
        )
    images = plan.get("images")
    if not isinstance(images, list):
        failures.append(
            f"--approved-plan {approved_plan} images is not a JSON "
            f"array (got {type(images).__name__})."
        )
    else:
        for i, row in enumerate(images):
            if not isinstance(row, dict):
                failures.append(
                    f"--approved-plan {approved_plan} images[{i}] is "
                    f"not a JSON object (got {type(row).__name__})."
                )
                continue
            for field in _PLAN_ROW_COMPARE_FIELDS:
                if field not in row:
                    failures.append(
                        f"--approved-plan {approved_plan} images[{i}] "
                        f"missing required field {field!r}."
                    )
            # Reject bool for the per-row int fields too. byte_count
            # and intended_slide_index would otherwise compare-match
            # the current integers 0 / 1 via True == 1 / False == 0.
            for int_field in ("byte_count", "intended_slide_index"):
                if int_field in row and not _is_strict_int(
                    row.get(int_field),
                ):
                    failures.append(
                        f"--approved-plan {approved_plan} images[{i}]."
                        f"{int_field}={row.get(int_field)!r}; "
                        f"expected non-boolean integer."
                    )

    if failures:
        return None, bytes_sha256, failures
    return plan, bytes_sha256, []


def _compare_to_approved_plan(
    *,
    current: dict,
    approved: dict,
    approved_plan_path: Path,
) -> list[str]:
    """Compare the in-memory ``current`` plan body to the (already
    structurally-validated) ``approved`` plan body and return a list of
    drift diagnostics. Empty list means a clean match.

    Top-level fields compared: image_count, slide_count, manifest_path
    (schema_version / helper_id / mode / explicit_boundaries already
    matched by ``_load_approved_plan``). Per-image fields compared
    (in order): filename, asset_id, media_type, byte_count, sha256,
    intended_slide_index, slide_title, alt_text, intended_use. Image
    array length mismatch is reported once, before per-row drift, so
    the operator does not see N spurious row-missing diagnostics on
    top of the real ``image_count`` mismatch."""
    failures: list[str] = []
    for top in ("image_count", "slide_count", "manifest_path"):
        if approved.get(top) != current.get(top):
            failures.append(
                f"--approved-plan {approved_plan_path} {top}="
                f"{approved.get(top)!r}; current inputs produce "
                f"{current.get(top)!r}."
            )
    approved_rows = approved.get("images") or []
    current_rows = current.get("images") or []
    if len(approved_rows) != len(current_rows):
        failures.append(
            f"--approved-plan {approved_plan_path} images length="
            f"{len(approved_rows)}; current inputs produce "
            f"{len(current_rows)} image row(s)."
        )
        return failures
    for i, (a_row, c_row) in enumerate(zip(approved_rows, current_rows)):
        for field in _PLAN_ROW_COMPARE_FIELDS:
            a_val = a_row.get(field)
            c_val = c_row.get(field)
            if a_val != c_val:
                failures.append(
                    f"--approved-plan {approved_plan_path} images[{i}]."
                    f"{field}={a_val!r}; current inputs produce "
                    f"{c_val!r}."
                )
    return failures


def _run_plan_only_mode(
    *,
    images_dir_str: str,
    plan_out_str: str,
    manifest_path_str: str | None = None,
) -> int:
    """Validate every operator argument, discover the images (and the
    optional manifest), and write a compact deterministic JSON
    preflight plan to ``--plan-out``. Returns 0 on success, 2 on
    operator-input refusal (no filesystem mutation), 1 on write
    failure.

    The plan-only mode does NOT run the pipeline, does NOT produce a
    PPTX, does NOT produce a workspace / inventory / visual_quality /
    summary / _pipeline_fixture artifact, does NOT touch any file
    under ``REPO_ROOT``, and does NOT call D-One / MCP / Qoder / a
    public network / a model API / an image search / telemetry. It
    composes the same image-discovery gate (IG1..IG9) the normal
    operator mode applies plus — only when ``--manifest`` was supplied
    — the manifest gate (MAN1..MAN12), plus the ``--plan-out`` path
    gate (PO1..PO6). The plan it writes carries one row per
    discovered image with filename / asset_id / media_type /
    byte_count / sha256 / intended 1-based slide index / slide_title /
    alt_text / intended_use, in manifest-array order when
    ``--manifest`` is supplied or filename-sorted order otherwise.
    """
    images, _images_dir, image_failures = _validate_images_dir_arg(
        images_dir_str,
    )
    plan_out, plan_failures = _validate_plan_out_arg(plan_out_str)

    manifest_failures: list[str] = []
    manifest_path: Path | None = None
    if manifest_path_str is not None:
        discovered_filenames = (
            [img.operator_filename for img in images]
            if images is not None
            else None
        )
        ordered_entries, manifest_path, manifest_failures = (
            _validate_manifest_arg(
                manifest_path_str, discovered_filenames,
            )
        )
        if (
            not image_failures
            and not manifest_failures
            and images is not None
            and ordered_entries is not None
        ):
            by_filename = {
                img.operator_filename: img for img in images
            }
            images = [
                replace(
                    by_filename[entry["filename"]],
                    slide_title=entry["slide_title"],
                    alt_text=entry["alt_text"],
                    intended_use=entry["intended_use"],
                )
                for entry in ordered_entries
            ]

    if (
        image_failures
        or plan_failures
        or manifest_failures
        or images is None
        or plan_out is None
    ):
        for line in image_failures or []:
            print(f"FAIL: {line}", file=sys.stderr)
        for line in plan_failures or []:
            print(f"FAIL: {line}", file=sys.stderr)
        for line in manifest_failures or []:
            print(f"FAIL: {line}", file=sys.stderr)
        return 2

    body = _build_plan_body(images=images, manifest_path=manifest_path)
    rows = body["images"]

    manifest_arg_display = (
        f", --manifest {manifest_path}"
        if manifest_path is not None
        else ""
    )
    print(
        f"=== operator_local_images_to_editable_ppt "
        f"(--images-dir {images_dir_str}, --plan-out {plan_out}"
        f"{manifest_arg_display}) ==="
    )
    for row in rows:
        print(
            f"  image:     {row['filename']!r} "
            f"(id={row['asset_id']!r}, {row['media_type']}, "
            f"{row['byte_count']} bytes, "
            f"sha256={row['sha256'][:12]}..., "
            f"intended_slide={row['intended_slide_index']})"
        )

    try:
        plan_out.write_text(
            json.dumps(body, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(
            f"FAIL: cannot write --plan-out {plan_out}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    if not plan_out.is_file() or plan_out.is_symlink():
        print(
            f"FAIL: expected --plan-out {plan_out} as a regular "
            f"non-symlink file after write",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK (plan-only): wrote {len(rows)} image plan row"
        f"{'' if len(rows) == 1 else 's'} to {plan_out}. Pipeline NOT "
        f"run; no PPTX, workspace, inventory, visual_quality, summary, "
        f"or _pipeline_fixture produced. Local-only — does NOT call "
        f"D-One, MCP, Qoder, a public network, a model API, an image "
        f"search, or telemetry."
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


def _absent_sidecar_summary_gate(summary: dict) -> str | None:
    """Gate-only helper for GP-ABSENT. Returns a failure diagnostic
    string for a summary that should reflect an absent-sidecar run,
    or ``None`` when the summary passes. Used inline by the GP-ABSENT
    probe AND fed mutated synthetic inputs by GP-ABSENT-NEG so a
    refactor that weakens the gate (e.g., reverts the key-present
    check to ``summary.get(...) is not None``) fails the negative
    proof at run time.

    Three perturbations the gate must refuse on an absent-sidecar
    summary:

      * the ``generated_provenance`` key is missing from the dict
        (``dict.get(...) is not None`` would false-green here —
        ``None is not None`` evaluates False);
      * the ``generated_provenance`` value is non-null (an absent-
        sidecar run produces exactly ``null``);
      * any ``image_provenance`` row carries a sidecar field
        (``_ABSENT_SIDECAR_LEAK_FIELDS``).
    """
    if "generated_provenance" not in summary:
        return (
            "summary.generated_provenance key MISSING from the "
            "dict; expected explicit null on an absent-sidecar run "
            "(dict.get(...) None false-positives both missing and "
            "explicit-null; the gate uses 'in' to catch a "
            "forgotten-key regression)"
        )
    if summary["generated_provenance"] is not None:
        return (
            f"generated_provenance="
            f"{summary['generated_provenance']!r}; expected "
            f"explicit null on absent-sidecar run"
        )
    for i, p in enumerate(summary.get("image_provenance") or []):
        if not isinstance(p, dict):
            continue
        leaked = _ABSENT_SIDECAR_LEAK_FIELDS & set(p.keys())
        if leaked:
            return (
                f"image_provenance[{i}] carries sidecar fields "
                f"{sorted(leaked)!r} despite absent sidecar"
            )
    return None


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
                    vq = summary.get("visual_quality") or {}
                    val = summary.get("validators") or {}
                    vq_path = out_dir / "visual_quality.json"
                    if not all(
                        p.get("embedded_media_parts")
                        for p in prov
                    ):
                        ok = False
                        detail = (
                            f"image_provenance missing media parts: "
                            f"{prov!r}"
                        )
                    elif (
                        [p.get("operator_filename") for p in prov]
                        != ["alpha_marker.png", "beta_marker.jpg"]
                    ):
                        ok = False
                        detail = (
                            f"image_provenance filenames "
                            f"{[p.get('operator_filename') for p in prov]!r}; "
                            f"expected filename-sorted order "
                            f"['alpha_marker.png', 'beta_marker.jpg']"
                        )
                    elif (
                        [p.get("intended_slide_index") for p in prov]
                        != [1, 2]
                    ):
                        ok = False
                        detail = (
                            f"image_provenance intended_slide_index "
                            f"sequence "
                            f"{[p.get('intended_slide_index') for p in prov]!r}; "
                            f"expected [1, 2] (filename-sorted order "
                            f"maps to intended slides 1, 2)"
                        )
                    elif not all(
                        isinstance(
                            p.get("embedded_referencing_slides"),
                            list,
                        )
                        and p["embedded_referencing_slides"]
                        and p.get("intended_slide_index")
                        in p["embedded_referencing_slides"]
                        for p in prov
                    ):
                        ok = False
                        detail = (
                            f"image_provenance missing or wrong "
                            f"embedded_referencing_slides: "
                            f"{[(p.get('operator_filename'), p.get('intended_slide_index'), p.get('embedded_referencing_slides')) for p in prov]!r}"
                        )
                    elif not all(
                        p.get("placement_verified") is True
                        for p in prov
                    ):
                        ok = False
                        detail = (
                            f"image_provenance placement_verified not "
                            f"True for every row: "
                            f"{[(p.get('operator_filename'), p.get('placement_verified')) for p in prov]!r}"
                        )
                    elif not vq_path.is_file() or vq_path.is_symlink():
                        ok = False
                        detail = (
                            f"visual_quality.json not written as a "
                            f"regular non-symlink file at {vq_path}"
                        )
                    elif vq.get("rc") != 0:
                        ok = False
                        detail = (
                            f"visual_quality.rc={vq.get('rc')!r}, "
                            f"expected 0"
                        )
                    elif vq.get("report_parsed") is not True:
                        ok = False
                        detail = (
                            f"visual_quality.report_parsed="
                            f"{vq.get('report_parsed')!r}, expected True"
                        )
                    elif vq.get("error_count") != 0:
                        ok = False
                        detail = (
                            f"visual_quality.error_count="
                            f"{vq.get('error_count')!r}, expected 0"
                        )
                    elif not isinstance(vq.get("warning_count"), int):
                        ok = False
                        detail = (
                            f"visual_quality.warning_count="
                            f"{vq.get('warning_count')!r}, expected int"
                        )
                    elif (
                        (val.get("validate_visual_quality") or {}).get("rc")
                        != 0
                    ):
                        ok = False
                        detail = (
                            f"validators.validate_visual_quality.rc="
                            f"{(val.get('validate_visual_quality') or {}).get('rc')!r}, "
                            f"expected 0"
                        )
                    else:
                        readme_path = out_dir / "README.md"
                        if (
                            not readme_path.is_file()
                            or readme_path.is_symlink()
                        ):
                            ok = False
                            detail = (
                                f"README.md not written as a regular "
                                f"non-symlink file at {readme_path}"
                            )
                        else:
                            readme_text = readme_path.read_text(
                                encoding="utf-8",
                            )
                            required = (
                                "deck.pptx", "summary.json",
                                "inventory.json", "visual_quality.json",
                                "workspace/source_image_assets.json",
                                "reports/", "image_provenance",
                                _README_BOUNDARY_STATEMENT,
                            )
                            missing = [
                                m for m in required
                                if m not in readme_text
                            ]
                            if missing:
                                ok = False
                                detail = (
                                    f"README.md missing required "
                                    f"reference(s) {missing!r} (path: "
                                    f"{readme_path})"
                                )
        if not ok and not detail:
            detail = f"rc={rc}"
        results.append(_ProbeResult(
            "T1 happy path: synthetic PNG + JPEG into a fresh --out-dir "
            "-> 2-slide editable PPTX with provenance + visual_quality "
            "report + operator README naming the core artifacts and "
            "boundary statement",
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

    # ----- T19..T42: --manifest gates -----

    # T19 happy path: operator supplies a manifest that reorders the
    # two synthetic images (beta first, alpha second) and supplies
    # custom slide_title / alt_text / intended_use; the produced
    # summary echoes both the new order AND the new strings under
    # image_provenance, AND the deck still embeds both images.
    with tempfile.TemporaryDirectory(prefix="op-helper-T19-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        manifest = td / "manifest.json"
        _write_synthetic_images(images_dir)
        manifest.write_text(json.dumps({
            "schema_version": "1",
            "images": [
                {
                    "filename": "beta_marker.jpg",
                    "slide_title": "Beta accent first",
                    "alt_text": "Operator beta marker (reordered)",
                    "intended_use": "decorative pattern",
                },
                {
                    "filename": "alpha_marker.png",
                    "slide_title": "Alpha accent second",
                    "alt_text": "Operator alpha marker (reordered)",
                    "intended_use": "icon",
                },
            ],
        }) + "\n", encoding="utf-8")
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
            manifest_path_str=str(manifest),
        )
        ok = rc == 0
        detail = ""
        if ok:
            try:
                summary = json.loads((out_dir / "summary.json").read_text())
            except (OSError, json.JSONDecodeError) as exc:
                ok = False
                detail = f"cannot parse summary.json: {exc}"
            else:
                prov = summary.get("image_provenance") or []
                if summary.get("image_count") != 2:
                    ok = False
                    detail = (
                        f"image_count={summary.get('image_count')!r}, "
                        f"expected 2"
                    )
                elif summary.get("manifest_path") != str(manifest):
                    ok = False
                    detail = (
                        f"manifest_path={summary.get('manifest_path')!r}, "
                        f"expected {str(manifest)!r}"
                    )
                elif len(prov) != 2:
                    ok = False
                    detail = f"image_provenance has {len(prov)} entries"
                elif prov[0].get("operator_filename") != "beta_marker.jpg":
                    ok = False
                    detail = (
                        f"provenance[0] is "
                        f"{prov[0].get('operator_filename')!r}; "
                        f"expected beta_marker.jpg (manifest order)"
                    )
                elif prov[1].get("operator_filename") != "alpha_marker.png":
                    ok = False
                    detail = (
                        f"provenance[1] is "
                        f"{prov[1].get('operator_filename')!r}; "
                        f"expected alpha_marker.png (manifest order)"
                    )
                else:
                    expected_titles = (
                        "Beta accent first", "Alpha accent second",
                    )
                    expected_intended = (
                        "decorative pattern", "icon",
                    )
                    for i, (ttl, intent) in enumerate(zip(
                        expected_titles, expected_intended,
                    )):
                        if prov[i].get("operator_slide_title") != ttl:
                            ok = False
                            detail = (
                                f"provenance[{i}].operator_slide_title="
                                f"{prov[i].get('operator_slide_title')!r}; "
                                f"expected {ttl!r}"
                            )
                            break
                        if prov[i].get("operator_intended_use") != intent:
                            ok = False
                            detail = (
                                f"provenance[{i}].operator_intended_use="
                                f"{prov[i].get('operator_intended_use')!r}; "
                                f"expected {intent!r}"
                            )
                            break
                        if prov[i].get("intended_slide_index") != i + 1:
                            ok = False
                            detail = (
                                f"provenance[{i}].intended_slide_index="
                                f"{prov[i].get('intended_slide_index')!r}; "
                                f"expected {i + 1!r} (manifest order "
                                f"maps to 1-based slide index)"
                            )
                            break
                        refs = prov[i].get(
                            "embedded_referencing_slides",
                        )
                        if (
                            not isinstance(refs, list)
                            or (i + 1) not in refs
                        ):
                            ok = False
                            detail = (
                                f"provenance[{i}]."
                                f"embedded_referencing_slides={refs!r}; "
                                f"expected non-empty list containing "
                                f"{i + 1!r} (inventory-derived slide "
                                f"references must cover the intended "
                                f"slide for the manifest-reordered "
                                f"image)"
                            )
                            break
                        if prov[i].get("placement_verified") is not True:
                            ok = False
                            detail = (
                                f"provenance[{i}].placement_verified="
                                f"{prov[i].get('placement_verified')!r}; "
                                f"expected True for the manifest-"
                                f"reordered image"
                            )
                            break
                    if ok:
                        readme_path = out_dir / "README.md"
                        if (
                            not readme_path.is_file()
                            or readme_path.is_symlink()
                        ):
                            ok = False
                            detail = (
                                f"README.md not written as a regular "
                                f"non-symlink file at {readme_path} "
                                f"on the --manifest happy path"
                            )
                        else:
                            readme_text = readme_path.read_text(
                                encoding="utf-8",
                            )
                            required = (
                                "deck.pptx", "summary.json",
                                "inventory.json", "visual_quality.json",
                                "workspace/source_image_assets.json",
                                "reports/", "image_provenance",
                                _README_BOUNDARY_STATEMENT,
                            )
                            missing = [
                                m for m in required
                                if m not in readme_text
                            ]
                            if missing:
                                ok = False
                                detail = (
                                    f"README.md missing required "
                                    f"reference(s) {missing!r} on the "
                                    f"--manifest happy path (path: "
                                    f"{readme_path})"
                                )
        if not ok and not detail:
            detail = f"rc={rc}"
        results.append(_ProbeResult(
            "T19 happy path: --manifest reorders + supplies custom "
            "slide_title/alt_text/intended_use; provenance echoes both, "
            "operator README written naming the core artifacts and "
            "boundary statement",
            ok, detail,
        ))

    # T20 MAN1 URI-shaped --manifest refused (no images discovery needed).
    entries, _p, fails = _validate_manifest_arg(
        "file:///tmp/manifest.json", None,
    )
    results.append(_ProbeResult(
        "T20 MAN1: URI-shaped --manifest refused",
        entries is None and any("MAN1" in f for f in fails),
        f"entries={entries!r}, failures={fails!r}",
    ))

    # T21 MAN2 symlink --manifest refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T21-") as raw_td:
        td = Path(raw_td)
        real = td / "real.json"
        real.write_text("{}", encoding="utf-8")
        link = td / "link.json"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            results.append(_ProbeResult(
                "T21 MAN2: skipped (symlink not supported on this OS)",
                True,
            ))
        else:
            entries, _p, fails = _validate_manifest_arg(str(link), None)
            results.append(_ProbeResult(
                "T21 MAN2: symlink --manifest refused",
                entries is None and any("MAN2" in f for f in fails),
                f"entries={entries!r}, failures={fails!r}",
            ))

    # T22 MAN3 symlink ancestor of --manifest refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T22-") as raw_td:
        td = Path(raw_td)
        real_parent = td / "real_parent"
        real_parent.mkdir()
        nested = real_parent / "nested"
        nested.mkdir()
        (nested / "manifest.json").write_text("{}", encoding="utf-8")
        symlink_parent = td / "linked_parent"
        try:
            symlink_parent.symlink_to(
                real_parent, target_is_directory=True,
            )
        except (OSError, NotImplementedError):
            results.append(_ProbeResult(
                "T22 MAN3: skipped (symlink not supported on this OS)",
                True,
            ))
        else:
            target = symlink_parent / "nested" / "manifest.json"
            entries, _p, fails = _validate_manifest_arg(str(target), None)
            results.append(_ProbeResult(
                "T22 MAN3: symlink ancestor of --manifest refused",
                entries is None and any("MAN3" in f for f in fails),
                f"entries={entries!r}, failures={fails!r}",
            ))

    # T23 MAN4 missing manifest refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T23-") as raw_td:
        entries, _p, fails = _validate_manifest_arg(
            str(Path(raw_td) / "nope.json"), None,
        )
        results.append(_ProbeResult(
            "T23 MAN4: missing --manifest refused",
            entries is None and any("MAN4" in f for f in fails),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T24 MAN4 --manifest is a directory, not a regular file.
    with tempfile.TemporaryDirectory(prefix="op-helper-T24-") as raw_td:
        td = Path(raw_td)
        (td / "manifest.json").mkdir()
        entries, _p, fails = _validate_manifest_arg(
            str(td / "manifest.json"), None,
        )
        results.append(_ProbeResult(
            "T24 MAN4: --manifest is a directory -> refused",
            entries is None and any("MAN4" in f for f in fails),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T25 MAN5 malformed JSON refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T25-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text("not json {", encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T25 MAN5: malformed JSON refused",
            entries is None and any("MAN5" in f for f in fails),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T26 MAN5 non-object root (top-level array) refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T26-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text("[]", encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T26 MAN5: top-level JSON array refused (root must be object)",
            entries is None and any("MAN5" in f for f in fails),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T27 MAN6 unknown root key refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T27-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [],
            "extra_root_key": "no",
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T27 MAN6: unknown root key refused",
            entries is None and any("MAN6" in f for f in fails),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T28 MAN6 missing root key (no schema_version) refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T28-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({"images": []}), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T28 MAN6: missing schema_version root key refused",
            entries is None and any("MAN6" in f for f in fails),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T29 MAN7 wrong schema_version refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T29-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "2", "images": [],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T29 MAN7: schema_version != '1' refused",
            entries is None and any("MAN7" in f for f in fails),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T30 MAN8 empty images array refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T30-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1", "images": [],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T30 MAN8: empty images array refused",
            entries is None and any("MAN8" in f for f in fails),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T31 MAN9 entry missing a field refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T31-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "A",
                # intended_use missing
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T31 MAN9: entry missing required field refused",
            entries is None and any("MAN9" in f for f in fails),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T32 MAN9 entry with unknown field refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T32-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "A",
                "intended_use": "icon",
                "extra_field": "no",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T32 MAN9: entry with unknown field refused",
            entries is None and any("MAN9" in f for f in fails),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T33 MAN10 empty string refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T33-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "",
                "alt_text": "A",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T33 MAN10: empty slide_title refused",
            entries is None and any("MAN10" in f and "empty" in f for f in fails),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T34 MAN10 URL-shaped slide_title refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T34-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "see https://example.com/foo",
                "alt_text": "A",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T34 MAN10: URL in slide_title refused",
            entries is None and any(
                "MAN10" in f and ("URL" in f or "://" in f) for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T35 MAN10 path separator in slide_title refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T35-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "../sneaky",
                "alt_text": "A",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T35 MAN10: path separator in slide_title refused",
            entries is None and any(
                "MAN10" in f and "path separator" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T36 MAN10 credential-shaped alt_text refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T36-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "set api_key for the upload",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T36 MAN10: credential-shaped alt_text refused",
            entries is None and any(
                "MAN10" in f and "credential" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T37 MAN10 upload/share/hosting wording in intended_use refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T37-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "A",
                "intended_use": "share to dropbox",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T37 MAN10: public upload/share wording in intended_use "
            "refused",
            entries is None and any(
                "MAN10" in f and "upload" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T38 MAN10 confidential / customer marker refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T38-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "confidential customer data preview",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T38 MAN10: confidential / customer marker in alt_text "
            "refused",
            entries is None and any(
                "MAN10" in f and "confidential" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T39 MAN10 positive D-One success claim refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T39-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "Generated by D-One",
                "alt_text": "A",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T39 MAN10: D-One success claim in slide_title refused",
            entries is None and any(
                "MAN10" in f and "upstream service" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T40 MAN11 duplicate filename in manifest refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T40-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [
                {
                    "filename": "alpha.png", "slide_title": "T1",
                    "alt_text": "A", "intended_use": "icon",
                },
                {
                    "filename": "alpha.png", "slide_title": "T2",
                    "alt_text": "A", "intended_use": "icon",
                },
            ],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T40 MAN11: duplicate filename in manifest refused",
            entries is None and any("MAN11" in f for f in fails),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T41 MAN12 orphan manifest filename (not in discovered set) refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T41-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "ghost.png",
                "slide_title": "Ghost",
                "alt_text": "A",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(
            str(path), ["real.png"],
        )
        results.append(_ProbeResult(
            "T41 MAN12: manifest names a filename not in --images-dir "
            "-> refused",
            entries is None and any("MAN12" in f for f in fails),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T42 MAN12 missing manifest entry for a discovered file refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T42-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "A",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(
            str(path), ["alpha.png", "beta.png"],
        )
        results.append(_ProbeResult(
            "T42 MAN12: manifest does not name a discovered file -> "
            "refused",
            entries is None and any("MAN12" in f for f in fails),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T43 MAN10 public-hosting wording (no provider name) refused.
    # The existing T37 probe locks the provider-named substring path
    # (`share to dropbox`); this probe locks the new bounded regex
    # path so a regression that drops `_DENY_PUBLIC_SHARE_REGEX`
    # would let `public hosting enabled` slip through (the original
    # Codex-flagged false-green).
    with tempfile.TemporaryDirectory(prefix="op-helper-T43-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "public hosting enabled",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T43 MAN10: 'public hosting enabled' in alt_text refused "
            "(no provider name; bounded regex must fire)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T44 MAN10 verb + public(ly) shape refused. Locks the SECOND
    # alternation in the public-share regex (verb-first ordering).
    with tempfile.TemporaryDirectory(prefix="op-helper-T44-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "A",
                "intended_use": "share publicly",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T44 MAN10: 'share publicly' in intended_use refused "
            "(verb + public(ly) regex path)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T45 MAN10 'make / made (it / this) public' shape refused. Locks
    # the THIRD alternation; an operator who writes 'make public' on
    # the slide title would otherwise leak a public-release intent
    # into the native editable text.
    with tempfile.TemporaryDirectory(prefix="op-helper-T45-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "Make this public",
                "alt_text": "A",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T45 MAN10: 'make this public' in slide_title refused "
            "(make / made (it / this) public regex path)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T46 MAN10 'anyone can <reach-verb>' reach-modifier shape refused.
    # Locks alt 8 — covers the common no-provider, no-"public" shape
    # where the operator names *who* gets access ("anyone can
    # download" / "everyone has access") rather than the channel.
    with tempfile.TemporaryDirectory(prefix="op-helper-T46-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "anyone can download this",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T46 MAN10: 'anyone can download' reach-modifier refused "
            "(anyone / everyone + can / has + reach verb regex path)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T47 MAN10 'on the internet' / internet-channel shape refused.
    # Locks alt 6 + alt 7 — covers wording that names a public
    # distribution channel without using the word "public".
    with tempfile.TemporaryDirectory(prefix="op-helper-T47-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "asset on the internet",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T47 MAN10: 'on the internet' channel wording refused "
            "(on the internet / web regex path)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T48 MAN10 'globally distributed' scale-modifier shape refused.
    # Locks alt 11 — covers wording that names scale ("global",
    # "worldwide", "wide(ly)") attached to a distribution verb without
    # using the word "public" or naming a provider. Uses the hyphen
    # form to also lock the [\s-]+ separator class.
    with tempfile.TemporaryDirectory(prefix="op-helper-T48-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "A",
                "intended_use": "globally-distributed asset",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T48 MAN10: 'globally-distributed' scale-modifier refused "
            "(wide/global/worldwide + distribute/broadcast/share/"
            "circulate regex path with hyphen separator)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T49 MAN10 'post to <name>' social-media post shape refused via
    # the alt 14 regex path. The test value deliberately AVOIDS
    # naming a known social-media platform (twitter / instagram /
    # facebook / linkedin / ...) so the platform substring denylist
    # does NOT fire first; the regex path is the load-bearing gate
    # for this probe. ("post to twitter" with the platform name is
    # refused TWICE — once via the substring "twitter", once via
    # alt 14 — and the substring fires first; that combined refusal
    # is regression-locked by T62's battery indirectly.)
    with tempfile.TemporaryDirectory(prefix="op-helper-T49-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "Post to my channel",
                "alt_text": "A",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T49 MAN10: 'post to <non-platform>' social-media post "
            "wording refused via the alt 14 regex path (post + to)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T50 MAN10 'freely / openly + verb' shape refused. Locks the
    # extended publicness vocab in alt 1 (public(ly) / freely /
    # openly). A regression that narrowed the vocab back to "public"
    # only would let "freely available" / "openly distributed" slip
    # through.
    with tempfile.TemporaryDirectory(prefix="op-helper-T50-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "freely available image",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T50 MAN10: 'freely available' publicness-vocab extension "
            "refused (public(ly) / freely / openly + verb regex path)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T51 MAN10 hyphenated 'make-public' shape refused. Locks the
    # [\s-]+ separator in alt 3. Earlier ``\s+`` separator would
    # have let "make-it-public" slip through; the bounded separator
    # class catches both "make public" (space) and "make-public"
    # (hyphen).
    with tempfile.TemporaryDirectory(prefix="op-helper-T51-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "Make-it-public asset",
                "alt_text": "A",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T51 MAN10: hyphenated 'make-it-public' refused "
            "(alt 3 [\\s-]+ separator class)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T52 MAN10 hyphenated 'upload-to-PROVIDER' refused. The
    # substring denylist matches "upload to" (space-separated) but
    # NOT "upload-to-s3" (hyphen). Alt 14's broader
    # <sharing-verb>[\s-]+to\b catches the hyphenated form.
    with tempfile.TemporaryDirectory(prefix="op-helper-T52-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "upload-to-s3 backup pattern",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T52 MAN10: hyphenated 'upload-to-s3' refused "
            "(alt 14 generalized <sharing-verb>[\\s-]+to regex path)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T53 MAN10 hyphenated 'hosted-on-PROVIDER' refused. The
    # substring "hosted on" misses "hosted-on-aws" (hyphen).
    # Alt 15 (<host/broadcast/publish/stream verb>[\s-]+on\b) is the
    # new shape that catches this.
    with tempfile.TemporaryDirectory(prefix="op-helper-T53-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "A",
                "intended_use": "hosted-on-aws icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T53 MAN10: hyphenated 'hosted-on-aws' refused "
            "(alt 15 <host/broadcast/publish/stream verb>[\\s-]+on "
            "regex path)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T54 MAN10 hyphenated 'anyone-can-download' refused. Locks the
    # [\s-]+ separator in alt 8. T46 covers the space-separated
    # form; this probe ensures the hyphen form is equally refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T54-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "anyone-can-download badge",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T54 MAN10: hyphenated 'anyone-can-download' refused "
            "(alt 8 [\\s-]+ separator class)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T55 MAN10 hyphenated 'for-the-public' refused. Locks the
    # [\s-]+ separator in alt 10. Important because the bare phrase
    # "to-the-public" / "for-the-public" has no `public` adjacency
    # with a verb — only the alt-10 reach-modifier path catches it.
    with tempfile.TemporaryDirectory(prefix="op-helper-T55-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "For-the-public release graphic",
                "alt_text": "A",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T55 MAN10: hyphenated 'for-the-public' refused "
            "(alt 10 [\\s-]+ separator class)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T56 MAN10 cloud-provider hosting refused. Locks alt 7's
    # EXPANDED channel vocab — earlier the channel set was just
    # {internet, web}; the expanded vocab also covers cloud / cdn /
    # aws / azure / gcp / s3 / remote / external. Without this
    # expansion, "cloud-hosted" / "cdn-hosted" / "aws-hosted" would
    # all false-green.
    with tempfile.TemporaryDirectory(prefix="op-helper-T56-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "cloud-hosted asset",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T56 MAN10: 'cloud-hosted' refused (alt 7 expanded "
            "channel vocab)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T57 MAN10 content-class hosting refused. Locks the new alt 17
    # — catches "image-hosting" / "image hosting service" /
    # "file-hosting" / "video-hosting" etc. without false-positives
    # on benign UI nouns ("host icon", "hosting industry chart").
    with tempfile.TemporaryDirectory(prefix="op-helper-T57-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "A",
                "intended_use": "image-hosting badge",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T57 MAN10: 'image-hosting' refused (alt 17 "
            "content-class noun + host(ed|ing) regex path)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T58 MAN10 distance-modifier hosting refused. Locks the new
    # alt 18 — catches "third-party-hosted" / "externally-hosted" /
    # "remotely-hosted" while leaving benign "self-hosted" /
    # "privately-hosted" alone.
    with tempfile.TemporaryDirectory(prefix="op-helper-T58-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "Third-party-hosted asset",
                "alt_text": "A",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T58 MAN10: 'third-party-hosted' refused (alt 18 "
            "distance modifier + host(ed|ing) regex path)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T59 MAN10 storage-preposition-channel triple refused. Locks
    # the new alt 16 — catches "stored on cloud", "served via cdn",
    # "synced to cloud", "saved to drive", "delivered via web" and
    # their hyphenated forms.
    with tempfile.TemporaryDirectory(prefix="op-helper-T59-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "stored-on-cloud asset",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T59 MAN10: 'stored-on-cloud' refused (alt 16 verb + "
            "preposition + channel regex path)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T60 MAN10 downloadable-from refused. Locks the new alt 19 —
    # "downloadable from anywhere" / "downloadable from web" /
    # "downloadable from cloud" with cloud / public-reach
    # destination suffix.
    with tempfile.TemporaryDirectory(prefix="op-helper-T60-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "downloadable from anywhere badge",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T60 MAN10: 'downloadable from anywhere' refused "
            "(alt 19 download(able)? from + public-destination "
            "regex path)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T61 — cloud-provider channel + storage/delivery verb refused.
    # Locks the new alt 7b — narrower channel vocab than alt 7 so
    # benign "internet save dialog" / "remote backup icon" pass,
    # but "cloud-stored asset" / "cdn-served image" / "aws-saved"
    # / "s3-backed" / "cdn-delivered" still trip.
    with tempfile.TemporaryDirectory(prefix="op-helper-T61-") as raw_td:
        td = Path(raw_td)
        path = td / "manifest.json"
        path.write_text(json.dumps({
            "schema_version": "1",
            "images": [{
                "filename": "alpha.png",
                "slide_title": "T",
                "alt_text": "cloud-stored asset",
                "intended_use": "icon",
            }],
        }), encoding="utf-8")
        entries, _p, fails = _validate_manifest_arg(str(path), None)
        results.append(_ProbeResult(
            "T61 MAN10: 'cloud-stored' refused (alt 7b cloud-provider "
            "channel + storage/delivery verb regex path)",
            entries is None and any(
                "MAN10" in f and "public-share" in f for f in fails
            ),
            f"entries={entries!r}, failures={fails!r}",
        ))

    # T62 — battery regression-lock for ordinary local-action wording
    # that MUST PASS the MAN10 safe-string gates. Earlier rounds
    # added save / store / sync / backup / deliver / serve / send /
    # forward / "back up to anything" / "download from anything"
    # patterns that false-refused common UI / file / printer / local-
    # backup phrasings; this probe locks the narrow direction in
    # place so a future re-broadening of alt 14/15/19/20 immediately
    # turns a benign sample red. Samples are checked directly through
    # the safe-string function (no full pipeline run needed; cheap).
    benign_samples: tuple[str, ...] = (
        # File / save UI references.
        "save to file", "save to disk", "save to project",
        "saved to drive", "save to backup folder",
        "saved to local folder", "save dialog", "saved icon",
        "save button mockup",
        # Send / forward / deliver — local actions.
        "send to printer", "send to email", "send to colleague",
        "send icon", "forward to inbox", "forwarded to mailbox",
        "forward button", "delivered to recipient",
        "delivered to mailbox", "delivery icon", "served to user",
        "served on plate", "serving size chart",
        # Backup / sync — local.
        "backup icon", "back up to file", "back up to backup drive",
        "backed up to local disk", "backup workflow diagram",
        "sync icon", "synced to laptop", "synced to backup",
        "syncing icon", "sync workflow",
        # Storage — local.
        "stored to disk", "stored to project", "store to memory",
        "stored on hard disk", "stored on local server",
        # External / remote storage devices (local hardware /
        # local-network references). These were false-refusing in
        # the previous round because "remote" / "external" were in
        # alts 7/16/19/20 channel lists; they are now removed so
        # only alt 18 (distance modifier + distribution verb)
        # catches the truly distribution-y "remotely-hosted" /
        # "externally-distributed" forms.
        "saved to external drive", "saved to external disk",
        "save to external HDD", "saved-to-external-drive",
        "backup to external drive", "back up to external disk",
        "backed up to external disk",
        "backed-up-to-external-drive",
        "synced to external drive", "synced to external disk",
        "stored on external drive", "stored on external disk",
        "stored on external HDD",
        "stored on remote disk", "stored on remote drive",
        "stored on remote server",
        "saved to remote drive", "saved to remote disk",
        "saved to remote server", "synced to remote backup",
        "synced to remote drive", "synced to remote folder",
        "backed up to remote disk", "backed up to remote drive",
        "backed up to remote server", "back up to remote folder",
        "back up to remote backup",
        "downloaded from external drive",
        "downloaded from remote disk",
        "downloadable from external storage",
        "download from external drive",
        "served from external", "served from remote",
        "delivered from remote", "delivered from external",
        "available from remote", "available from external",
        "external storage diagram", "external disk icon",
        "external drive backup", "remote storage diagram",
        "remote disk icon", "remote server backup",
        "remote desktop icon", "remote control icon",
        "external hard drive", "external link icon",
        "external storage workflow", "remote storage workflow",
        # Cloud architecture / distribution diagrams (noun forms).
        "cdn distribution diagram", "cloud distribution diagram",
        "cdn architecture diagram", "cloud architecture diagram",
        "cdn delivery diagram", "cdn storage diagram",
        "cloud storage diagram", "internet of things diagram",
        "internet save dialog", "remote backup icon",
        # Share UI elements.
        "share button mockup", "share price chart",
        "shareholder report chart", "share icon",
        # Download UI — local.
        "download from menu", "download from app",
        "download from cache", "downloadable from app",
        # Misc benign.
        "spot illustration", "decorative pattern", "icon",
        "host icon", "hosting industry chart",
        "make a public statement", "open book", "open source code",
        "publication date", "on-the-fly diagram", "go-to action",
        "to-do list", "blog post illustration", "post-modern style",
        "publication design", "live action photograph",
        "online tutorial illustration", "self-hosted server icon",
        "privately-hosted", "image of a public square",
        "public service announcement", "public art piece",
    )
    refused: list[tuple[str, str]] = []
    for sample in benign_samples:
        value, fail = _safe_manifest_string(
            field="alt_text", value=sample,
            max_len=300, entry_idx=0,
        )
        if fail:
            refused.append((sample, fail))
    results.append(_ProbeResult(
        f"T62 MAN10 regression lock: {len(benign_samples)} ordinary-"
        f"local wording samples (save-to / send-to / forward-to / "
        f"delivered-to / served-to / stored-to / back-up-to / "
        f"synced-to / <channel> distribution diagram / <channel> "
        f"architecture / external hard drive / remote backup / "
        f"share button / share price chart / shareholder / download "
        f"from menu / spot illustration / decorative pattern / etc.) "
        f"MUST PASS the MAN10 safe-string gates",
        not refused,
        f"refused {len(refused)} sample(s): {refused!r}"
        if refused else "",
    ))

    # T63 — battery regression-lock for fake public-network /
    # upstream-service success claims that MUST refuse the MAN10
    # safe-string gates. Locks every category in
    # ``_FAKE_SUCCESS_REGEX``: lane-specific brand mentions
    # (already covered by T39 baseline); upstream service
    # indicators (model api / image search / telemetry); network /
    # API / HTTP operation success vocab; network protocol mentions
    # (REST / GraphQL / webhook / websocket / gRPC); real-live-
    # production + service; success-action shape; action-verb +
    # upstream-target; AI / ML / model-generated claims;
    # "generated by + AI brand"; image-gen model brand mentions.
    # A future re-narrowing of the regex (or a regression that
    # drops one of the categories) will immediately turn a sample
    # green here.
    fake_success_samples: tuple[str, ...] = (
        # Network / API / HTTP success vocab.
        "network connection succeeded",
        "network connection established",
        "network request completed",
        "network connected successfully",
        "API call succeeded",
        "API request returned",
        "API endpoint hit",
        "API response received",
        "successful API call",
        "HTTP request succeeded",
        "HTTPS call returned",
        "http response received",
        "successful https request",
        "http endpoint hit",
        # Network protocol mentions.
        "REST API endpoint hit",
        "REST call succeeded",
        "graphql query returned",
        "webhook delivered",
        "websocket connection",
        "grpc call succeeded",
        # Real / live / production + service.
        "real network call",
        "live API integration",
        "production endpoint hit",
        "real-time API response",
        "live D-One call",
        "production MCP integration",
        "real model call",
        "live model invocation",
        # Successfully / actually + action verb.
        "successfully called the model",
        "successfully invoked the API",
        "successfully queried the endpoint",
        "successfully fetched from the network",
        "successfully hit the API",
        "successfully reached the model",
        "successfully integrated with the API",
        "actually called the model",
        # Action verb + upstream target.
        "called the model",
        "invoked the API",
        "queried the endpoint",
        "hit the api",
        "reached the network",
        "contacted the model",
        "fetched from API",
        "retrieved from model",
        # AI / ML / model-generated claims.
        "AI-generated illustration",
        "ML-generated image",
        "model-generated diagram",
        "generated by AI",
        "generated by ML",
        "generated by model",
        "generated by stable diffusion",
        "generated by midjourney",
        "generated by dall-e",
        "generated by GPT-4",
        "generated by chatgpt",
        "image generated via API",
        "ai-gen illustration",
        # Image-gen model brand mentions.
        "midjourney render",
        "dall-e output",
        "stable diffusion result",
        "imagen output",
        "leonardo ai render",
        # Standalone LLM-product brand mentions (alt J+ category).
        "ChatGPT illustration", "ChatGPT-style portrait",
        "ChatGPT export", "GPT illustration", "GPT-4 output",
        "GPT-3.5 image", "gpt4 render", "OpenAI image",
        "OpenAI rendering", "OpenAI-style art",
        "Anthropic creation", "Anthropic-style",
        # Two-word / hyphenated brand variants (Codex flagged
        # these as still slipping through when the brand was
        # spelled with a space or hyphen).
        "Open AI illustration", "Open AI rendering",
        "Open AI output", "Open AI-style art",
        "open-ai render", "open ai portrait",
        "Made by Open AI", "Created with Open AI",
        "Powered by Open AI", "Generated by Open AI",
        "Mid Journey render", "mid journey output",
        "Mid-Journey illustration",
        "Generated by Mid Journey", "Made by Mid Journey",
        "Made by Mid-Journey",
        # "Chat GPT" two-word variant — caught via the standalone
        # `\bgpt\b` alt regardless of the "chat" prefix; locked
        # here to surface a regression that drops gpt's standalone
        # refuse.
        "Chat GPT illustration", "Chat-GPT export",
        # Claude / Gemini in model-context (alt K category).
        "Claude generated portrait", "Claude-generated illustration",
        "Claude rendering", "Claude renderings", "Claude output",
        "Claude outputs", "Claude drawing", "Claude paintings",
        "Claude 3 illustration", "Claude 3.5 art",
        "Claude sonnet image", "Claude opus render",
        "Claude API documentation",
        "Gemini Pro output", "Gemini Ultra render",
        "Gemini paintings", "Gemini renderings",
        "Gemini API call",
        # Expanded "verb + prep + brand" coverage (alt I category).
        "Made by GPT", "Made by ChatGPT", "Made by Claude",
        "Made by OpenAI", "Created with Midjourney",
        "Created by DALL-E", "Created with Claude",
        "Powered by OpenAI", "Powered by Anthropic",
        "Powered by Gemini", "Drawn by Midjourney",
        "Drawn by stable diffusion", "Drawn by GPT",
        "Rendered by Claude", "Rendered by AI",
        "Rendered by GPT-4", "Produced by ChatGPT",
        "Synthesized by Imagen", "Composed by Claude",
        "Crafted by GPT", "Output by Midjourney",
        "Output by OpenAI",
    )
    passed: list[tuple[str, str | None]] = []
    for sample in fake_success_samples:
        value, fail = _safe_manifest_string(
            field="alt_text", value=sample,
            max_len=300, entry_idx=0,
        )
        if not fail:
            passed.append((sample, value))
    results.append(_ProbeResult(
        f"T63 MAN10 fake-success regression lock: "
        f"{len(fake_success_samples)} public-network / API / HTTP / "
        f"model success-claim samples (network call succeeded / "
        f"API endpoint hit / HTTP response received / successful "
        f"REST call / live D-One call / production MCP integration "
        f"/ successfully invoked the model / fetched from API / "
        f"AI-generated illustration / generated by midjourney / "
        f"dall-e output / etc.) MUST REFUSE the MAN10 safe-string "
        f"gates with a public-share diagnostic",
        not passed,
        f"falsely accepted {len(passed)} sample(s): {passed!r}"
        if passed else "",
    ))

    # ----- T64..T68: --write-manifest-template mode -----

    # T64 happy path: write a manifest template, then reuse it verbatim
    # in normal operator mode. Asserts the template has the documented
    # shape (schema_version="1", one images[] entry per discovered file,
    # sorted by filename, every required field populated with the same
    # default value the helper applies when --manifest is omitted) AND
    # that running the operator mode with that template echoes each
    # entry's slide_title / alt_text / intended_use back into the
    # summary's image_provenance block exactly as for a hand-authored
    # manifest. The two-step round-trip is the load-bearing assertion
    # of the spec ("the generated manifest must be immediately usable
    # by the existing normal command").
    with tempfile.TemporaryDirectory(prefix="op-helper-T64-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        template_path = td / "manifest_template.json"
        out_dir = td / "out"
        _write_synthetic_images(images_dir)
        rc_t = _run_template_write_mode(
            images_dir_str=str(images_dir),
            template_path_str=str(template_path),
        )
        ok = rc_t == 0 and template_path.is_file()
        detail = ""
        template_body: dict | None = None
        if not ok:
            detail = (
                f"rc_t={rc_t}, template_exists={template_path.is_file()}"
            )
        else:
            try:
                template_body = json.loads(template_path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                ok = False
                detail = f"cannot parse template {template_path}: {exc}"
            else:
                if template_body.get("schema_version") != "1":
                    ok = False
                    detail = (
                        f"template schema_version="
                        f"{template_body.get('schema_version')!r}; "
                        f"expected '1'"
                    )
                elif not isinstance(template_body.get("images"), list):
                    ok = False
                    detail = (
                        f"template images is "
                        f"{type(template_body.get('images')).__name__}; "
                        f"expected list"
                    )
                elif len(template_body["images"]) != 2:
                    ok = False
                    detail = (
                        f"template has {len(template_body['images'])} "
                        f"entries; expected 2"
                    )
                else:
                    expected_filenames = [
                        "alpha_marker.png", "beta_marker.jpg",
                    ]
                    actual_filenames = [
                        e.get("filename")
                        for e in template_body["images"]
                    ]
                    if actual_filenames != expected_filenames:
                        ok = False
                        detail = (
                            f"template filenames {actual_filenames!r}; "
                            f"expected sorted "
                            f"{expected_filenames!r}"
                        )
                    else:
                        for i, entry in enumerate(template_body["images"]):
                            for field in (
                                "filename", "slide_title",
                                "alt_text", "intended_use",
                            ):
                                v = entry.get(field)
                                if not isinstance(v, str) or not v:
                                    ok = False
                                    detail = (
                                        f"template images[{i}].{field}"
                                        f"={v!r}; expected non-empty "
                                        f"string"
                                    )
                                    break
                            if not ok:
                                break
                        # Spot-check the defaults match the helper's
                        # built-in defaults so a regression that drifts
                        # one source of truth is caught.
                        if ok:
                            alpha_image = _DiscoveredImage(
                                operator_filename="alpha_marker.png",
                                operator_path=Path(""),
                                asset_id="alpha_marker",
                                extension="png",
                                media_type="image/png",
                                byte_count=1,
                                sha256="x" * 64,
                            )
                            if (
                                template_body["images"][0].get(
                                    "slide_title"
                                ) != _default_slide_title(alpha_image)
                                or template_body["images"][0].get(
                                    "alt_text"
                                ) != _default_alt_text(alpha_image)
                                or template_body["images"][0].get(
                                    "intended_use"
                                ) != _DEFAULT_INTENDED_USE
                            ):
                                ok = False
                                detail = (
                                    f"template defaults drifted from "
                                    f"helper defaults for "
                                    f"alpha_marker.png entry: "
                                    f"{template_body['images'][0]!r}"
                                )
        if ok:
            rc_n = _run_operator_mode(
                images_dir_str=str(images_dir),
                out_dir_str=str(out_dir),
                manifest_path_str=str(template_path),
            )
            if rc_n != 0:
                ok = False
                detail = (
                    f"normal operator mode rc={rc_n} after using the "
                    f"template; expected 0"
                )
            else:
                try:
                    summary = json.loads(
                        (out_dir / "summary.json").read_text()
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    ok = False
                    detail = f"cannot parse summary.json: {exc}"
                else:
                    if summary.get("manifest_path") != str(template_path):
                        ok = False
                        detail = (
                            f"summary.manifest_path="
                            f"{summary.get('manifest_path')!r}; "
                            f"expected {str(template_path)!r}"
                        )
                    elif summary.get("image_count") != 2:
                        ok = False
                        detail = (
                            f"summary.image_count="
                            f"{summary.get('image_count')!r}; "
                            f"expected 2"
                        )
                    else:
                        prov = summary.get("image_provenance") or []
                        expected_by_fname = {
                            e["filename"]: e
                            for e in template_body["images"]
                        }
                        for p in prov:
                            fname = p.get("operator_filename")
                            template_entry = expected_by_fname.get(fname)
                            if template_entry is None:
                                ok = False
                                detail = (
                                    f"provenance entry for {fname!r} "
                                    f"not in template"
                                )
                                break
                            for prov_field, tpl_field in (
                                ("operator_slide_title", "slide_title"),
                                ("operator_alt_text", "alt_text"),
                                ("operator_intended_use", "intended_use"),
                            ):
                                if (
                                    p.get(prov_field)
                                    != template_entry[tpl_field]
                                ):
                                    ok = False
                                    detail = (
                                        f"provenance[{fname!r}]."
                                        f"{prov_field}="
                                        f"{p.get(prov_field)!r}; "
                                        f"expected "
                                        f"{template_entry[tpl_field]!r} "
                                        f"(template's {tpl_field})"
                                    )
                                    break
                            if not ok:
                                break
        if not ok and not detail:
            detail = f"rc_t={rc_t}"
        results.append(_ProbeResult(
            "T64 template happy path: --write-manifest-template writes "
            "the manifest, then re-running normal operator mode with "
            "--manifest <that-template> validates the PPTX/summary and "
            "echoes template fields verbatim under image_provenance",
            ok, detail,
        ))

    # T65 MT1: URI-shaped --write-manifest-template refused. The
    # assertion includes the "no filesystem entry materialised" check
    # AND a direct gate call to lock the URI-specific diagnostic — the
    # same belt-and-braces pattern T18 uses for --out-dir.
    with tempfile.TemporaryDirectory(prefix="op-helper-T65-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        _write_synthetic_images(images_dir)
        uri_template = (
            "file:///tmp/op_helper_t65_template_must_not_exist.json"
        )
        rc = _run_template_write_mode(
            images_dir_str=str(images_dir),
            template_path_str=uri_template,
        )
        _, fails_direct = _validate_manifest_template_arg(uri_template)
        leaked = Path(uri_template).exists()
        uri_specific = any(
            "MT1" in f and "URI-shaped" in f
            for f in (fails_direct or [])
        )
        results.append(_ProbeResult(
            "T65 MT1: URI-shaped --write-manifest-template refused by "
            "the URI-specific gate (rc=2 + MT1 diagnostic) with no "
            "filesystem entry materialised",
            (
                rc == 2
                and bool(fails_direct)
                and uri_specific
                and not leaked
            ),
            f"rc={rc}, uri_specific={uri_specific}, "
            f"fails_direct={fails_direct!r}, leaked={leaked}",
        ))

    # T66 MT4: --write-manifest-template inside REPO_ROOT refused with
    # no file materialised. Load-bearing for the "keep generated
    # artifacts out of the repo" contract — a regression that removes
    # the MT4 gate would let an operator typo land a template inside
    # the committed tree.
    with tempfile.TemporaryDirectory(prefix="op-helper-T66-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        _write_synthetic_images(images_dir)
        bad_template = (
            REPO_ROOT
            / "operator_manifest_template_should_not_land_here.json"
        )
        rc = _run_template_write_mode(
            images_dir_str=str(images_dir),
            template_path_str=str(bad_template),
        )
        leaked = bad_template.exists()
        results.append(_ProbeResult(
            "T66 MT4: --write-manifest-template inside REPO_ROOT "
            "refused with no file materialised under the committed "
            "tree",
            rc == 2 and not leaked,
            f"rc={rc}, leaked={leaked}",
        ))

    # T67 MT6: pre-existing target refused; stale bytes preserved
    # byte-identical. The "does not overwrite operator files" contract
    # is asserted by reading back the stale content after the refusal.
    with tempfile.TemporaryDirectory(prefix="op-helper-T67-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        _write_synthetic_images(images_dir)
        existing = td / "existing_operator_file.json"
        existing.write_text(
            "OPERATOR-PRE-EXISTING-BYTES",
            encoding="utf-8",
        )
        rc = _run_template_write_mode(
            images_dir_str=str(images_dir),
            template_path_str=str(existing),
        )
        results.append(_ProbeResult(
            "T67 MT6: pre-existing --write-manifest-template target "
            "refused; stale bytes preserved byte-identical",
            (
                rc == 2
                and existing.is_file()
                and existing.read_text(encoding="utf-8")
                == "OPERATOR-PRE-EXISTING-BYTES"
            ),
            f"rc={rc}, existing_bytes="
            f"{existing.read_text(encoding='utf-8')!r}",
        ))

    # T68 template mode: representative bad --images-dir case. Empty
    # directory trips IG4 just like in operator mode (the template
    # writer composes the same image-discovery gate verbatim); no
    # template file may be written when the images argument is refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T68-") as raw_td:
        td = Path(raw_td)
        empty_images_dir = td / "empty_images"
        empty_images_dir.mkdir()
        template_path = td / "template.json"
        rc = _run_template_write_mode(
            images_dir_str=str(empty_images_dir),
            template_path_str=str(template_path),
        )
        results.append(_ProbeResult(
            "T68 template mode: empty --images-dir refused (IG4); no "
            "template file written",
            rc == 2 and not template_path.exists(),
            f"rc={rc}, template_exists={template_path.exists()}",
        ))

    # T69 MT4 case-variant: a case-variant of REPO_ROOT must still
    # trip MT4 on case-insensitive APFS / HFS+ / NTFS volumes.
    # ``Path.resolve()`` preserves the typed case rather than
    # canonicalising it, so a strict ``relative_to`` check alone would
    # let ``/Users/ROBERT/...`` slip through when REPO_ROOT resolves
    # to ``/Users/robert/...`` even though both paths point at the
    # same on-disk directory. The case-folded comparison in the gate
    # is what closes the gap; this probe locks that behaviour against
    # a regression that drops the casefold step.
    repo_root_str = str(REPO_ROOT)
    variant_str: str | None = None
    for ch_idx, ch in enumerate(repo_root_str):
        if ch.isalpha() and ch.islower():
            variant_str = (
                repo_root_str[:ch_idx]
                + ch.upper()
                + repo_root_str[ch_idx + 1:]
            )
            break
        if ch.isalpha() and ch.isupper():
            variant_str = (
                repo_root_str[:ch_idx]
                + ch.lower()
                + repo_root_str[ch_idx + 1:]
            )
            break
    if variant_str is None or variant_str == repo_root_str:
        # REPO_ROOT has no alpha characters (extremely unusual). Skip
        # rather than emit a false-positive PASS.
        results.append(_ProbeResult(
            "T69 MT4 case-variant: skipped (REPO_ROOT has no alpha "
            "characters to flip)",
            True,
        ))
    else:
        candidate = (
            variant_str + os.sep + "case_variant_template.json"
        )
        _, t69_fails = _validate_manifest_template_arg(candidate)
        is_mt4 = any("MT4" in f for f in (t69_fails or []))
        leaked = Path(candidate).exists()
        results.append(_ProbeResult(
            "T69 MT4 case-variant: case-variant of REPO_ROOT refused "
            "with MT4 diagnostic even on case-insensitive FSes; no "
            "file materialised",
            bool(t69_fails) and is_mt4 and not leaked,
            f"variant={variant_str!r}, fails={t69_fails!r}, "
            f"leaked={leaked}",
        ))

    # T71 visual_quality.json: produced under --out-dir, parses as a JSON
    # object, and carries integer totals.errors / totals.warnings. Spot-
    # checks the file the helper hands to a reviewer is the same shape
    # the truth-checker reads.
    with tempfile.TemporaryDirectory(prefix="op-helper-T71-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        _write_synthetic_images(images_dir)
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
        )
        vq_path = out_dir / "visual_quality.json"
        parsed: object = None
        if rc == 0 and vq_path.is_file():
            try:
                parsed = json.loads(vq_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                parsed = None
        ok = (
            rc == 0
            and vq_path.is_file()
            and not vq_path.is_symlink()
            and isinstance(parsed, dict)
            and isinstance(parsed.get("totals"), dict)
            and parsed["totals"].get("errors") == 0
            and isinstance(parsed["totals"].get("warnings"), int)
            and isinstance(parsed.get("slides"), list)
            and len(parsed["slides"]) == 2
        )
        results.append(_ProbeResult(
            "T71 visual_quality.json: written under --out-dir, parses, "
            "totals.errors==0, totals.warnings is int, 2 per-slide "
            "entries match the 2-image deck",
            ok,
            f"rc={rc}, vq_exists={vq_path.is_file()}, "
            f"parsed_keys={sorted(parsed.keys()) if isinstance(parsed, dict) else parsed!r}",
        ))

    # T72 truth-check refuses a tampered summary whose
    # visual_quality.error_count is positive — proves errors flow into the
    # existing summary truth-check path (the goal's "fail closed through
    # the existing summary truth-check path"). Built from a real happy-
    # path summary so every other field stays valid; only the visual_
    # quality block is mutated.
    with tempfile.TemporaryDirectory(prefix="op-helper-T72-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        _write_synthetic_images(images_dir)
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
        )
        good_fails: list[str] = []
        tampered_fails: list[str] = []
        if rc == 0:
            summary = json.loads(
                (out_dir / "summary.json").read_text(encoding="utf-8"),
            )
            good_fails = _check_summary_truth(summary)
            tampered = json.loads(json.dumps(summary))  # deep copy
            tampered["visual_quality"]["error_count"] = 1
            tampered_fails = _check_summary_truth(tampered)
        ok = (
            rc == 0
            and good_fails == []
            and any(
                "visual_quality.error_count" in f
                for f in tampered_fails
            )
        )
        results.append(_ProbeResult(
            "T72 tampered summary visual_quality.error_count>0 fails "
            "truth-check (errors route through summary truth-check)",
            ok,
            f"rc={rc}, good_fails={good_fails!r}, "
            f"tampered_fails={tampered_fails!r}",
        ))

    # T73 truth-check refuses a tampered summary whose
    # visual_quality.report_parsed is False — proves a missing or
    # malformed report file fails closed. The validator emits both
    # totals.errors and totals.warnings on every run, so report_parsed
    # being False at runtime means the JSON couldn't be read / parsed /
    # decoded as an object — more fundamental than a per-slide finding.
    with tempfile.TemporaryDirectory(prefix="op-helper-T73-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        _write_synthetic_images(images_dir)
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
        )
        tampered_fails: list[str] = []
        if rc == 0:
            summary = json.loads(
                (out_dir / "summary.json").read_text(encoding="utf-8"),
            )
            tampered = json.loads(json.dumps(summary))
            tampered["visual_quality"]["report_parsed"] = False
            tampered["visual_quality"]["error_count"] = None
            tampered["visual_quality"]["warning_count"] = None
            tampered_fails = _check_summary_truth(tampered)
        ok = (
            rc == 0
            and any(
                "visual_quality.report_parsed" in f
                for f in tampered_fails
            )
            and any(
                "visual_quality.error_count" in f
                for f in tampered_fails
            )
        )
        results.append(_ProbeResult(
            "T73 tampered summary visual_quality.report_parsed=False "
            "fails truth-check (missing/malformed report fails closed)",
            ok, f"rc={rc}, tampered_fails={tampered_fails!r}",
        ))

    # T74 truth-check refuses a tampered summary whose visual_quality.rc
    # is non-zero AND whose validators.validate_visual_quality.rc is
    # non-zero — locks both the per-block rc gate AND the validators-block
    # rc gate so a regression that drops either fires this probe.
    with tempfile.TemporaryDirectory(prefix="op-helper-T74-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        _write_synthetic_images(images_dir)
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
        )
        tampered_fails: list[str] = []
        if rc == 0:
            summary = json.loads(
                (out_dir / "summary.json").read_text(encoding="utf-8"),
            )
            tampered = json.loads(json.dumps(summary))
            tampered["visual_quality"]["rc"] = 1
            tampered["validators"]["validate_visual_quality"]["rc"] = 1
            tampered_fails = _check_summary_truth(tampered)
        ok = (
            rc == 0
            and any(
                "validators.validate_visual_quality.rc" in f
                for f in tampered_fails
            )
            and any(
                "visual_quality.rc=" in f
                for f in tampered_fails
            )
        )
        results.append(_ProbeResult(
            "T74 tampered summary visual_quality.rc != 0 AND "
            "validators.validate_visual_quality.rc != 0 fail truth-check",
            ok, f"rc={rc}, tampered_fails={tampered_fails!r}",
        ))

    # T76 happy-path provenance rows include intended_slide_index +
    # inventory-derived embedded_referencing_slides AND every row's
    # placement_verified is True. Locks the goal's "a reviewer can
    # answer: which slide was the operator file intended for, and which
    # slide(s) reference the embedded ppt/media part(s)" assertion for
    # the no-manifest filename-sorted path; T19 covers the manifest-
    # reorder path. Cheap to re-run inside its own tempdir so a
    # regression in either projection (intended index or inventory
    # referencing slides) fires on the smallest possible probe.
    with tempfile.TemporaryDirectory(prefix="op-helper-T76-") as raw_td:
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
            try:
                summary = json.loads(
                    (out_dir / "summary.json").read_text(),
                )
            except (OSError, json.JSONDecodeError) as exc:
                ok = False
                detail = f"cannot parse summary.json: {exc}"
            else:
                prov = summary.get("image_provenance") or []
                if [
                    p.get("operator_filename") for p in prov
                ] != ["alpha_marker.png", "beta_marker.jpg"]:
                    ok = False
                    detail = (
                        f"filename-sorted order broke: "
                        f"{[p.get('operator_filename') for p in prov]!r}"
                    )
                elif [
                    p.get("intended_slide_index") for p in prov
                ] != [1, 2]:
                    ok = False
                    detail = (
                        f"intended_slide_index sequence "
                        f"{[p.get('intended_slide_index') for p in prov]!r}; "
                        f"expected [1, 2]"
                    )
                else:
                    for i, p in enumerate(prov):
                        refs = p.get("embedded_referencing_slides")
                        if (
                            not isinstance(refs, list)
                            or (i + 1) not in refs
                            or p.get("placement_verified") is not True
                        ):
                            ok = False
                            detail = (
                                f"row {i} "
                                f"intended_slide_index={p.get('intended_slide_index')!r} "
                                f"embedded_referencing_slides={refs!r} "
                                f"placement_verified="
                                f"{p.get('placement_verified')!r}"
                            )
                            break
        results.append(_ProbeResult(
            "T76 happy-path provenance rows include intended_slide_index "
            "+ inventory-derived embedded_referencing_slides; "
            "placement_verified is True for every operator filename in "
            "filename-sorted order",
            ok, detail,
        ))

    # T77 truth-check refuses a tampered summary whose
    # image_provenance[i].intended_slide_index is not in
    # embedded_referencing_slides — proves the operator-image-on-
    # intended-slide gate routes through the existing summary truth-
    # check path (the goal's "fail closed through the existing summary
    # truth-check"). Built from a real happy-path summary so every other
    # field stays valid; only the provenance row's intended index is
    # rotated out of its reference set.
    with tempfile.TemporaryDirectory(prefix="op-helper-T77-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        _write_synthetic_images(images_dir)
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
        )
        good_fails: list[str] = []
        tampered_fails: list[str] = []
        if rc == 0:
            summary = json.loads(
                (out_dir / "summary.json").read_text(encoding="utf-8"),
            )
            good_fails = _check_summary_truth(summary)
            tampered = json.loads(json.dumps(summary))  # deep copy
            row = tampered["image_provenance"][0]
            row["embedded_referencing_slides"] = [
                idx for idx in row["embedded_referencing_slides"]
                if idx != row["intended_slide_index"]
            ] or [row["intended_slide_index"] + 99]
            row["placement_verified"] = (
                row["intended_slide_index"]
                in row["embedded_referencing_slides"]
            )
            tampered_fails = _check_summary_truth(tampered)
        ok = (
            rc == 0
            and good_fails == []
            and any(
                "intended_slide_index" in f
                and "embedded_referencing_slides" in f
                for f in tampered_fails
            )
        )
        results.append(_ProbeResult(
            "T77 tampered summary image_provenance row whose "
            "intended_slide_index is not in "
            "embedded_referencing_slides fails truth-check",
            ok,
            f"rc={rc}, good_fails={good_fails!r}, "
            f"tampered_fails={tampered_fails!r}",
        ))

    # T78 truth-check refuses a tampered summary whose
    # image_provenance[i].embedded_referencing_slides is empty — proves
    # the "every embedded operator part must be referenced by at least
    # one slide" projection fails closed independently of the intended-
    # index gate above.
    with tempfile.TemporaryDirectory(prefix="op-helper-T78-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        _write_synthetic_images(images_dir)
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
        )
        tampered_fails: list[str] = []
        if rc == 0:
            summary = json.loads(
                (out_dir / "summary.json").read_text(encoding="utf-8"),
            )
            tampered = json.loads(json.dumps(summary))
            tampered["image_provenance"][0][
                "embedded_referencing_slides"
            ] = []
            tampered["image_provenance"][0]["placement_verified"] = False
            tampered_fails = _check_summary_truth(tampered)
        ok = (
            rc == 0
            and any(
                "embedded_referencing_slides" in f
                and "non-empty" in f
                for f in tampered_fails
            )
        )
        results.append(_ProbeResult(
            "T78 tampered summary image_provenance row with empty "
            "embedded_referencing_slides fails truth-check",
            ok,
            f"rc={rc}, tampered_fails={tampered_fails!r}",
        ))

    # T79 blip-confirmed projection: synthesize an inventory dict where
    # slide 1 declares an image rel to "ppt/media/image1.png" but the
    # slide body does NOT use it (used_by_slide_blip=False), while slide
    # 2 actually embeds it (used_by_slide_blip=True). The rels-only
    # signal (inv.media_parts[0].referencing_slides) deliberately lists
    # BOTH slides, but the projection MUST return only slide 2 — the
    # blip-confirmed signal. A regression that switched back to reading
    # media_parts[*].referencing_slides would false-green slide 1 as a
    # placement target even though no <p:pic> on slide 1 embeds the
    # operator's bytes. This probe is the load-bearing lock for the
    # blip-vs-rels distinction the H4b sibling smoke documents.
    fake_inv = {
        "media_parts": [
            {
                "part": "ppt/media/image1.png",
                "referencing_slides": [1, 2],  # rels-only false-green
            },
        ],
        "slides": [
            {
                "index": 1,
                "media_refs": [
                    {
                        "r_id": "rId7",
                        "target": "../media/image1.png",
                        "resolved": "ppt/media/image1.png",
                        "used_by_slide_blip": False,
                    },
                ],
            },
            {
                "index": 2,
                "media_refs": [
                    {
                        "r_id": "rId7",
                        "target": "../media/image1.png",
                        "resolved": "ppt/media/image1.png",
                        "used_by_slide_blip": True,
                    },
                ],
            },
        ],
    }
    projection = _part_to_blip_referencing_slides_from_inventory(
        fake_inv,
    )
    results.append(_ProbeResult(
        "T79 blip-confirmed projection: a slide that declares an image "
        "rel without a matching <p:pic> blip (rels-only false-green) is "
        "DROPPED from embedded_referencing_slides; only slides whose "
        "media_refs[*].used_by_slide_blip is True are kept",
        projection == {"ppt/media/image1.png": [2]},
        f"projection={projection!r}; expected "
        f"{{'ppt/media/image1.png': [2]}}",
    ))

    # T75 --write-manifest-template mode is manifest-only — produces no
    # visual_quality.json / summary.json / deck.pptx / workspace under
    # the template's parent directory. Manifest-template mode must NOT
    # run the pipeline (and therefore not the visual-quality validator).
    with tempfile.TemporaryDirectory(prefix="op-helper-T75-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        _write_synthetic_images(images_dir)
        template_path = td / "template.json"
        rc = _run_template_write_mode(
            images_dir_str=str(images_dir),
            template_path_str=str(template_path),
        )
        siblings = sorted(
            p.name for p in td.iterdir() if p != images_dir
        )
        ok = (
            rc == 0
            and template_path.is_file()
            and not (td / "visual_quality.json").exists()
            and not (td / "summary.json").exists()
            and not (td / "deck.pptx").exists()
            and not (td / "workspace").exists()
            and not (td / "reports").exists()
            and not (td / "_pipeline_fixture").exists()
            and not (td / "inventory.json").exists()
            and not (td / "README.md").exists()
            and siblings == ["template.json"]
        )
        results.append(_ProbeResult(
            "T75 --write-manifest-template mode produces ONLY the "
            "manifest — no visual_quality.json / summary.json / "
            "deck.pptx / workspace / reports / _pipeline_fixture / "
            "inventory.json / README.md under the template's parent "
            "directory",
            ok, f"rc={rc}, siblings_of_template={siblings!r}",
        ))

    # T80 --plan-out happy path (no --manifest): the helper writes the
    # plan and NOTHING else under the plan_out's parent — no
    # _pipeline_fixture, no workspace, no PPTX, no inventory, no
    # visual_quality.json, no summary.json. The plan carries the
    # locked schema_version / helper_id / mode strings, image_count ==
    # slide_count == 2, manifest_path == None, the eight EXPLICIT
    # boundary sentences verbatim, and one row per discovered image
    # with filename / asset_id / media_type / byte_count / sha256 /
    # intended_slide_index / slide_title / alt_text / intended_use in
    # filename-sorted order (alpha_marker.png -> slide 1,
    # beta_marker.jpg -> slide 2). Locks the spec's "fixed explicit
    # boundaries" + "intended 1-based slide index" + "preserve operator
    # bytes" assertions for the no-manifest path.
    with tempfile.TemporaryDirectory(prefix="op-helper-T80-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        _write_synthetic_images(images_dir)
        plan_out = td / "plan.json"
        rc = _run_plan_only_mode(
            images_dir_str=str(images_dir),
            plan_out_str=str(plan_out),
        )
        ok = rc == 0 and plan_out.is_file()
        detail = ""
        if not ok:
            detail = (
                f"rc={rc}, plan_present={plan_out.is_file()}"
            )
        if ok:
            try:
                plan = json.loads(plan_out.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                ok = False
                detail = f"cannot parse plan: {exc}"
        siblings = sorted(
            p.name for p in td.iterdir() if p != images_dir
        )
        if ok and siblings != ["plan.json"]:
            ok = False
            detail = (
                f"unexpected siblings under plan_out parent: "
                f"{siblings!r}; expected ['plan.json']"
            )
        if ok:
            for forbidden in (
                "summary.json", "deck.pptx", "inventory.json",
                "visual_quality.json", "_pipeline_fixture",
                "workspace", "reports", "README.md",
            ):
                if (td / forbidden).exists():
                    ok = False
                    detail = (
                        f"plan-only mode produced forbidden artifact "
                        f"{forbidden!r}"
                    )
                    break
        if ok:
            if plan.get("schema_version") != "1":
                ok = False
                detail = (
                    f"schema_version={plan.get('schema_version')!r}; "
                    f"expected '1'"
                )
            elif plan.get("helper_id") != (
                "operator_local_images_to_editable_ppt"
            ):
                ok = False
                detail = (
                    f"helper_id={plan.get('helper_id')!r}; "
                    f"expected 'operator_local_images_to_editable_ppt'"
                )
            elif plan.get("mode") != "plan_only":
                ok = False
                detail = (
                    f"mode={plan.get('mode')!r}; expected 'plan_only'"
                )
            elif plan.get("image_count") != 2:
                ok = False
                detail = (
                    f"image_count={plan.get('image_count')!r}; "
                    f"expected 2"
                )
            elif plan.get("slide_count") != 2:
                ok = False
                detail = (
                    f"slide_count={plan.get('slide_count')!r}; "
                    f"expected 2"
                )
            elif plan.get("manifest_path") is not None:
                ok = False
                detail = (
                    f"manifest_path={plan.get('manifest_path')!r}; "
                    f"expected None"
                )
            elif (
                tuple(plan.get("explicit_boundaries") or ())
                != _EXPLICIT_BOUNDARIES
            ):
                ok = False
                detail = (
                    f"explicit_boundaries={plan.get('explicit_boundaries')!r}; "
                    f"expected {_EXPLICIT_BOUNDARIES!r}"
                )
            else:
                rows = plan.get("images") or []
                expected_filenames = [
                    "alpha_marker.png", "beta_marker.jpg",
                ]
                if [r.get("filename") for r in rows] != expected_filenames:
                    ok = False
                    detail = (
                        f"row filenames "
                        f"{[r.get('filename') for r in rows]!r}; "
                        f"expected {expected_filenames!r} (filename-"
                        f"sorted order)"
                    )
                elif [
                    r.get("intended_slide_index") for r in rows
                ] != [1, 2]:
                    ok = False
                    detail = (
                        f"intended_slide_index sequence "
                        f"{[r.get('intended_slide_index') for r in rows]!r}; "
                        f"expected [1, 2]"
                    )
                else:
                    expected_media_types = [
                        "image/png", "image/jpeg",
                    ]
                    if [
                        r.get("media_type") for r in rows
                    ] != expected_media_types:
                        ok = False
                        detail = (
                            f"media_type sequence "
                            f"{[r.get('media_type') for r in rows]!r}; "
                            f"expected {expected_media_types!r}"
                        )
                    else:
                        expected_payloads = (
                            _TINY_PNG_BYTES, _TINY_JPEG_BYTES,
                        )
                        for i, payload in enumerate(expected_payloads):
                            expected_sha = hashlib.sha256(
                                payload,
                            ).hexdigest()
                            row = rows[i]
                            if row.get("byte_count") != len(payload):
                                ok = False
                                detail = (
                                    f"row[{i}].byte_count="
                                    f"{row.get('byte_count')!r}; "
                                    f"expected {len(payload)!r}"
                                )
                                break
                            if row.get("sha256") != expected_sha:
                                ok = False
                                detail = (
                                    f"row[{i}].sha256={row.get('sha256')!r}; "
                                    f"expected {expected_sha!r}"
                                )
                                break
                            for required_field in (
                                "asset_id", "slide_title",
                                "alt_text", "intended_use",
                            ):
                                value = row.get(required_field)
                                if (
                                    not isinstance(value, str)
                                    or not value
                                ):
                                    ok = False
                                    detail = (
                                        f"row[{i}].{required_field}="
                                        f"{value!r}; expected non-empty "
                                        f"string"
                                    )
                                    break
                            if not ok:
                                break
        results.append(_ProbeResult(
            "T80 --plan-out happy path: plan written; no pipeline / "
            "PPTX / inventory / visual_quality / summary / fixture "
            "artifact materialised; rows carry filename / asset_id / "
            "media_type / byte_count / sha256 / intended_slide_index / "
            "slide_title / alt_text / intended_use in filename-sorted "
            "order with locked schema / helper / mode / explicit "
            "boundaries",
            ok, detail,
        ))

    # T81 --plan-out happy path with --manifest: the manifest's
    # images[] array order replaces the filename sort as the deck
    # slide order, AND the operator-typed slide_title / alt_text /
    # intended_use flow through verbatim into the plan rows, AND
    # plan.manifest_path echoes the manifest path. Locks the spec's
    # "preserves manifest order and operator-authored fields"
    # assertion.
    with tempfile.TemporaryDirectory(prefix="op-helper-T81-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        _write_synthetic_images(images_dir)
        manifest = td / "manifest.json"
        plan_out = td / "plan.json"
        manifest.write_text(json.dumps({
            "schema_version": "1",
            "images": [
                {
                    "filename": "beta_marker.jpg",
                    "slide_title": "Beta plan first",
                    "alt_text": "Operator beta marker (plan order)",
                    "intended_use": "decorative pattern",
                },
                {
                    "filename": "alpha_marker.png",
                    "slide_title": "Alpha plan second",
                    "alt_text": "Operator alpha marker (plan order)",
                    "intended_use": "icon",
                },
            ],
        }) + "\n", encoding="utf-8")
        rc = _run_plan_only_mode(
            images_dir_str=str(images_dir),
            plan_out_str=str(plan_out),
            manifest_path_str=str(manifest),
        )
        ok = rc == 0 and plan_out.is_file()
        detail = ""
        if ok:
            try:
                plan = json.loads(plan_out.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                ok = False
                detail = f"cannot parse plan: {exc}"
        if ok:
            for forbidden in (
                "summary.json", "deck.pptx", "inventory.json",
                "visual_quality.json", "_pipeline_fixture",
                "workspace", "reports", "README.md",
            ):
                if (td / forbidden).exists():
                    ok = False
                    detail = (
                        f"plan-only mode with --manifest produced "
                        f"forbidden artifact {forbidden!r}"
                    )
                    break
        if ok:
            if plan.get("manifest_path") != str(manifest):
                ok = False
                detail = (
                    f"manifest_path={plan.get('manifest_path')!r}; "
                    f"expected {str(manifest)!r}"
                )
            else:
                rows = plan.get("images") or []
                if [r.get("filename") for r in rows] != [
                    "beta_marker.jpg", "alpha_marker.png",
                ]:
                    ok = False
                    detail = (
                        f"filenames {[r.get('filename') for r in rows]!r}; "
                        f"expected manifest order "
                        f"['beta_marker.jpg', 'alpha_marker.png']"
                    )
                elif [
                    r.get("intended_slide_index") for r in rows
                ] != [1, 2]:
                    ok = False
                    detail = (
                        f"intended_slide_index sequence "
                        f"{[r.get('intended_slide_index') for r in rows]!r}; "
                        f"expected [1, 2] (manifest order)"
                    )
                else:
                    expected_titles = [
                        "Beta plan first", "Alpha plan second",
                    ]
                    expected_alts = [
                        "Operator beta marker (plan order)",
                        "Operator alpha marker (plan order)",
                    ]
                    expected_uses = [
                        "decorative pattern", "icon",
                    ]
                    for i, (ttl, alt, use) in enumerate(zip(
                        expected_titles, expected_alts, expected_uses,
                    )):
                        if rows[i].get("slide_title") != ttl:
                            ok = False
                            detail = (
                                f"row[{i}].slide_title="
                                f"{rows[i].get('slide_title')!r}; "
                                f"expected {ttl!r}"
                            )
                            break
                        if rows[i].get("alt_text") != alt:
                            ok = False
                            detail = (
                                f"row[{i}].alt_text="
                                f"{rows[i].get('alt_text')!r}; "
                                f"expected {alt!r}"
                            )
                            break
                        if rows[i].get("intended_use") != use:
                            ok = False
                            detail = (
                                f"row[{i}].intended_use="
                                f"{rows[i].get('intended_use')!r}; "
                                f"expected {use!r}"
                            )
                            break
        if not ok and not detail:
            detail = f"rc={rc}"
        results.append(_ProbeResult(
            "T81 --plan-out with --manifest preserves manifest order "
            "and operator-authored slide_title / alt_text / "
            "intended_use; plan.manifest_path echoes the manifest path",
            ok, detail,
        ))

    # T82 PO4 --plan-out inside REPO_ROOT refused with no file
    # materialised under the committed repo tree.
    with tempfile.TemporaryDirectory(prefix="op-helper-T82-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        _write_synthetic_images(images_dir)
        bad_plan = REPO_ROOT / "operator_plan_should_not_land_here.json"
        rc = _run_plan_only_mode(
            images_dir_str=str(images_dir),
            plan_out_str=str(bad_plan),
        )
        leaked = bad_plan.exists()
        results.append(_ProbeResult(
            "T82 PO4: --plan-out inside REPO_ROOT refused; no file "
            "materialises under the committed tree",
            rc == 2 and not leaked,
            f"rc={rc}, leaked={leaked}",
        ))

    # T83 PO6 pre-existing --plan-out refused with stale bytes
    # preserved byte-identical. Mirrors the manifest-template MT6
    # contract: the writer never overwrites operator files.
    with tempfile.TemporaryDirectory(prefix="op-helper-T83-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        _write_synthetic_images(images_dir)
        plan_out = td / "plan.json"
        stale_bytes = b"PRE-EXISTING-PLAN-BYTES\n"
        plan_out.write_bytes(stale_bytes)
        rc = _run_plan_only_mode(
            images_dir_str=str(images_dir),
            plan_out_str=str(plan_out),
        )
        ok = (
            rc == 2
            and plan_out.is_file()
            and plan_out.read_bytes() == stale_bytes
        )
        results.append(_ProbeResult(
            "T83 PO6: pre-existing --plan-out refused; stale bytes "
            "preserved byte-identical",
            ok,
            f"rc={rc}, bytes_preserved="
            f"{plan_out.read_bytes() == stale_bytes!r}",
        ))

    # T84 --approved-plan happy path: --plan-out PATH then --approved-
    # plan PATH against byte-identical images + manifest succeeds and
    # writes the same deck.pptx / summary.json / inventory.json /
    # visual_quality.json / workspace / reports / README.md the
    # bare-normal run does. ALSO locks that summary.approved_plan
    # carries {path, sha256, matched=True} with the sha256 equal to
    # sha256(approved-plan-bytes) and that the README's
    # "Approved-plan lock" section names the same path + sha256.
    with tempfile.TemporaryDirectory(prefix="op-helper-T84-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        plan_out = td / "approved.json"
        _write_synthetic_images(images_dir)
        rc_plan = _run_plan_only_mode(
            images_dir_str=str(images_dir),
            plan_out_str=str(plan_out),
        )
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
            approved_plan_path_str=str(plan_out),
        )
        readme_path = out_dir / "README.md"
        summary_path = out_dir / "summary.json"
        deck_path = out_dir / "deck.pptx"
        ok = (
            rc_plan == 0
            and rc == 0
            and deck_path.is_file()
            and not deck_path.is_symlink()
            and summary_path.is_file()
            and not summary_path.is_symlink()
            and readme_path.is_file()
            and not readme_path.is_symlink()
        )
        detail = (
            f"rc_plan={rc_plan}, rc={rc}, "
            f"deck={deck_path.is_file()}, "
            f"summary={summary_path.is_file()}, "
            f"readme={readme_path.is_file()}"
        )
        if ok:
            try:
                summary = json.loads(summary_path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                ok = False
                detail = f"summary parse failed: {exc}"
        if ok:
            ap = summary.get("approved_plan")
            expected_sha = hashlib.sha256(
                plan_out.read_bytes(),
            ).hexdigest()
            if not isinstance(ap, dict):
                ok = False
                detail = (
                    f"summary.approved_plan={ap!r}; expected dict"
                )
            elif sorted(ap.keys()) != ["matched", "path", "sha256"]:
                ok = False
                detail = (
                    f"summary.approved_plan keys={sorted(ap.keys())!r}; "
                    f"expected ['matched', 'path', 'sha256']"
                )
            elif ap.get("matched") is not True:
                ok = False
                detail = (
                    f"summary.approved_plan.matched="
                    f"{ap.get('matched')!r}; expected True"
                )
            elif ap.get("path") != str(plan_out):
                ok = False
                detail = (
                    f"summary.approved_plan.path={ap.get('path')!r}; "
                    f"expected {str(plan_out)!r}"
                )
            elif ap.get("sha256") != expected_sha:
                ok = False
                detail = (
                    f"summary.approved_plan.sha256="
                    f"{ap.get('sha256')!r}; expected "
                    f"{expected_sha!r} (sha256sum of the approved "
                    f"plan bytes)"
                )
            else:
                readme_text = readme_path.read_text(encoding="utf-8")
                required_in_readme = (
                    "## Approved-plan lock",
                    str(plan_out),
                    expected_sha,
                    "summary.json",
                    "approved_plan",
                )
                missing = [
                    m for m in required_in_readme
                    if m not in readme_text
                ]
                if missing:
                    ok = False
                    detail = (
                        f"README missing approved-plan lock "
                        f"reference(s) {missing!r}"
                    )
        results.append(_ProbeResult(
            "T84 --approved-plan happy path: summary.approved_plan "
            "carries {path, sha256, matched=True} where sha256 equals "
            "sha256(approved-plan-bytes), and README 'Approved-plan "
            "lock' section names the same path + sha256 + points to "
            "summary.json#approved_plan",
            ok, detail,
        ))

    # T85 --approved-plan refuses on a post-approval image byte change.
    # Changing alpha_marker.png's bytes after --plan-out flips its
    # sha256 + byte_count; --approved-plan must catch the drift and
    # refuse with rc 2 BEFORE deck.pptx / summary.json / inventory /
    # visual_quality / README.md / workspace / reports materialise.
    # Locks "changing an image byte after plan-out makes
    # --approved-plan fail before deck/summary/README/workspace/reports
    # artifacts are created".
    with tempfile.TemporaryDirectory(prefix="op-helper-T85-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        plan_out = td / "approved.json"
        _write_synthetic_images(images_dir)
        rc_plan = _run_plan_only_mode(
            images_dir_str=str(images_dir),
            plan_out_str=str(plan_out),
        )
        # Re-author alpha_marker.png with a magic-byte-valid PNG body
        # that has a different trailing chunk so sha256 / byte_count
        # drift. Keeps IG8 happy so the helper reaches the
        # --approved-plan compare step rather than refusing on
        # magic-byte mismatch first.
        tampered_png = bytes.fromhex(
            "89504e470d0a1a0a"
            "0000000d49484452"
            "0000000100000001"
            "08060000001f15c489"
            "0000000d49444154"
            "789c6300010000000500010d0a2db4"
            "00000000"
            "49454e44ae426082"
            "00000000"
        )
        (images_dir / "alpha_marker.png").write_bytes(tampered_png)
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
            approved_plan_path_str=str(plan_out),
        )
        artifact_paths = [
            out_dir / "deck.pptx",
            out_dir / "summary.json",
            out_dir / "inventory.json",
            out_dir / "visual_quality.json",
            out_dir / "README.md",
            out_dir / "workspace",
            out_dir / "reports",
            out_dir / "_pipeline_fixture",
        ]
        leaked = [str(p) for p in artifact_paths if p.exists()]
        ok = rc_plan == 0 and rc == 2 and not leaked
        results.append(_ProbeResult(
            "T85 --approved-plan refuses on a post-approval image byte "
            "change; no deck.pptx / summary.json / inventory.json / "
            "visual_quality.json / README.md / workspace / reports / "
            "_pipeline_fixture artifact materialised",
            ok,
            f"rc_plan={rc_plan}, rc={rc}, leaked={leaked!r}",
        ))

    # T86 --approved-plan refuses on manifest order change. Original
    # --plan-out used filename-sorted order; a re-run with a manifest
    # that reverses the order trips the per-row filename drift on
    # row [0] and image_count / manifest_path also drift. Locks
    # "changing manifest order ... makes --approved-plan fail before
    # artifacts".
    with tempfile.TemporaryDirectory(prefix="op-helper-T86-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        plan_out = td / "approved.json"
        manifest = td / "manifest.json"
        _write_synthetic_images(images_dir)
        rc_plan = _run_plan_only_mode(
            images_dir_str=str(images_dir),
            plan_out_str=str(plan_out),
        )
        manifest.write_text(json.dumps({
            "schema_version": "1",
            "images": [
                {
                    "filename": "beta_marker.jpg",
                    "slide_title": "Beta first",
                    "alt_text": "Operator beta marker reordered.",
                    "intended_use": "spot illustration",
                },
                {
                    "filename": "alpha_marker.png",
                    "slide_title": "Alpha second",
                    "alt_text": "Operator alpha marker reordered.",
                    "intended_use": "spot illustration",
                },
            ],
        }) + "\n", encoding="utf-8")
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
            manifest_path_str=str(manifest),
            approved_plan_path_str=str(plan_out),
        )
        artifact_paths = [
            out_dir / "deck.pptx",
            out_dir / "summary.json",
            out_dir / "inventory.json",
            out_dir / "visual_quality.json",
            out_dir / "README.md",
            out_dir / "workspace",
            out_dir / "reports",
            out_dir / "_pipeline_fixture",
        ]
        leaked = [str(p) for p in artifact_paths if p.exists()]
        ok = rc_plan == 0 and rc == 2 and not leaked
        results.append(_ProbeResult(
            "T86 --approved-plan refuses on a manifest order change "
            "(filename-sorted plan vs reverse-order manifest); no "
            "deck / summary / inventory / visual_quality / README / "
            "workspace / reports / _pipeline_fixture artifact "
            "materialised",
            ok,
            f"rc_plan={rc_plan}, rc={rc}, leaked={leaked!r}",
        ))

    # T87 --approved-plan refuses on an operator-field change. Plan
    # written with manifest M1 (slide_title 'Alpha first' / 'Beta
    # second'); re-run with manifest M2 that only changes the alt_text
    # for the first row trips per-row alt_text drift. Locks "changing
    # ... an operator field after plan-out makes --approved-plan fail
    # before artifacts".
    with tempfile.TemporaryDirectory(prefix="op-helper-T87-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        plan_out = td / "approved.json"
        manifest1 = td / "manifest1.json"
        manifest2 = td / "manifest2.json"
        _write_synthetic_images(images_dir)
        manifest1.write_text(json.dumps({
            "schema_version": "1",
            "images": [
                {
                    "filename": "alpha_marker.png",
                    "slide_title": "Alpha first",
                    "alt_text": "Operator alpha marker original.",
                    "intended_use": "spot illustration",
                },
                {
                    "filename": "beta_marker.jpg",
                    "slide_title": "Beta second",
                    "alt_text": "Operator beta marker original.",
                    "intended_use": "spot illustration",
                },
            ],
        }) + "\n", encoding="utf-8")
        manifest2.write_text(json.dumps({
            "schema_version": "1",
            "images": [
                {
                    "filename": "alpha_marker.png",
                    "slide_title": "Alpha first",
                    "alt_text": "Operator alpha marker tampered.",
                    "intended_use": "spot illustration",
                },
                {
                    "filename": "beta_marker.jpg",
                    "slide_title": "Beta second",
                    "alt_text": "Operator beta marker original.",
                    "intended_use": "spot illustration",
                },
            ],
        }) + "\n", encoding="utf-8")
        rc_plan = _run_plan_only_mode(
            images_dir_str=str(images_dir),
            plan_out_str=str(plan_out),
            manifest_path_str=str(manifest1),
        )
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
            manifest_path_str=str(manifest2),
            approved_plan_path_str=str(plan_out),
        )
        artifact_paths = [
            out_dir / "deck.pptx",
            out_dir / "summary.json",
            out_dir / "inventory.json",
            out_dir / "visual_quality.json",
            out_dir / "README.md",
            out_dir / "workspace",
            out_dir / "reports",
            out_dir / "_pipeline_fixture",
        ]
        leaked = [str(p) for p in artifact_paths if p.exists()]
        ok = rc_plan == 0 and rc == 2 and not leaked
        results.append(_ProbeResult(
            "T87 --approved-plan refuses on an operator-field change "
            "(alt_text drift between approval-time manifest and run-"
            "time manifest); no deck / summary / inventory / "
            "visual_quality / README / workspace / reports / "
            "_pipeline_fixture artifact materialised",
            ok,
            f"rc_plan={rc_plan}, rc={rc}, leaked={leaked!r}",
        ))

    # T88 malformed --approved-plan refused with rc 2 and no out-dir
    # artifact. Covers (a) invalid-UTF-8 bytes, (b) non-JSON text,
    # (c) JSON-but-not-an-object, (d) wrong helper_id, (e) wrong mode,
    # (f) boundary drift. Each variant is its own out-dir so a leaked
    # artifact on one case cannot mask another. The invalid-UTF-8
    # case locks the regression where Path.read_text(encoding="utf-8")
    # would raise UnicodeDecodeError (not caught by an OSError-only
    # except) and crash the run instead of returning rc 2.
    malformed_cases: list[tuple[str, bytes]] = [
        ("invalid UTF-8 bytes", b"\xff\xfe\x00\x01malformed"),
        ("non-JSON text", b"not-json"),
        ("JSON array root", b"[1, 2, 3]"),
        (
            "wrong helper_id",
            json.dumps({
                "schema_version": "1",
                "helper_id": "some_other_helper",
                "mode": "plan_only",
                "image_count": 2, "slide_count": 2,
                "manifest_path": None,
                "explicit_boundaries": list(_EXPLICIT_BOUNDARIES),
                "images": [],
            }).encode("utf-8"),
        ),
        (
            "wrong mode",
            json.dumps({
                "schema_version": "1",
                "helper_id": "operator_local_images_to_editable_ppt",
                "mode": "operator_mode",
                "image_count": 2, "slide_count": 2,
                "manifest_path": None,
                "explicit_boundaries": list(_EXPLICIT_BOUNDARIES),
                "images": [],
            }).encode("utf-8"),
        ),
        (
            "boundary drift",
            json.dumps({
                "schema_version": "1",
                "helper_id": "operator_local_images_to_editable_ppt",
                "mode": "plan_only",
                "image_count": 2, "slide_count": 2,
                "manifest_path": None,
                "explicit_boundaries": ["dropped boundary"],
                "images": [],
            }).encode("utf-8"),
        ),
    ]
    t88_failures: list[str] = []
    for label, raw_bytes in malformed_cases:
        with tempfile.TemporaryDirectory(
            prefix=f"op-helper-T88-{label[:8]}-",
        ) as raw_td:
            td = Path(raw_td)
            images_dir = td / "images"
            out_dir = td / "out"
            plan_path = td / "approved.json"
            _write_synthetic_images(images_dir)
            plan_path.write_bytes(raw_bytes)
            try:
                rc = _run_operator_mode(
                    images_dir_str=str(images_dir),
                    out_dir_str=str(out_dir),
                    approved_plan_path_str=str(plan_path),
                )
            except BaseException as exc:
                # An uncaught exception (UnicodeDecodeError, JSONDecode
                # crash, etc.) IS the regression we are locking — capture
                # it as a probe failure rather than letting it abort the
                # whole self-test run.
                t88_failures.append(
                    f"{label}: crashed with "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            artifact_paths = [
                out_dir / "deck.pptx",
                out_dir / "summary.json",
                out_dir / "inventory.json",
                out_dir / "visual_quality.json",
                out_dir / "README.md",
                out_dir / "workspace",
                out_dir / "reports",
                out_dir / "_pipeline_fixture",
            ]
            leaked = [str(p) for p in artifact_paths if p.exists()]
            if rc != 2 or leaked:
                t88_failures.append(
                    f"{label}: rc={rc}, leaked={leaked!r}"
                )
    results.append(_ProbeResult(
        "T88 malformed --approved-plan refused with rc 2 across the "
        "six documented shapes (invalid UTF-8 bytes, non-JSON text, "
        "JSON array root, wrong helper_id, wrong mode, boundary "
        "drift); no deck / summary / inventory / visual_quality / "
        "README / workspace / reports / _pipeline_fixture artifact "
        "materialised",
        not t88_failures,
        "; ".join(t88_failures) if t88_failures else "",
    ))

    # T89 AP1..AP4 --approved-plan path gate.
    # AP1: URI-shaped path refused.
    path, fails = _validate_approved_plan_arg("file:///tmp/x.json")
    ap1_ok = path is None and any("AP1" in f for f in fails)
    # AP4 directory: directory path refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T89-dir-") as raw_td:
        td_path = Path(raw_td)
        path_dir, fails_dir = _validate_approved_plan_arg(str(td_path))
        ap4_dir_ok = path_dir is None and any(
            "AP4" in f for f in fails_dir
        )
    # AP4 missing: missing path refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-T89-mis-") as raw_td:
        missing_path = Path(raw_td) / "no-such-file.json"
        path_missing, fails_missing = _validate_approved_plan_arg(
            str(missing_path),
        )
        ap4_missing_ok = path_missing is None and any(
            "AP4" in f for f in fails_missing
        )
    # AP2 symlink path refused (skipped if symlink unsupported on this
    # OS, mirroring the IG2 / T3 self-test pattern).
    ap2_skipped = False
    ap2_ok = False
    with tempfile.TemporaryDirectory(prefix="op-helper-T89-sym-") as raw_td:
        real = Path(raw_td) / "real.json"
        real.write_text("{}", encoding="utf-8")
        link = Path(raw_td) / "link.json"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            ap2_skipped = True
            ap2_ok = True
        else:
            path_sym, fails_sym = _validate_approved_plan_arg(str(link))
            ap2_ok = path_sym is None and any(
                "AP2" in f for f in fails_sym
            )
    # Operator-mode wiring of the AP4 gate (URI-shaped): rc must be 2
    # and out-dir must NOT be mkdir'd by the helper. Locks "URI/symlink
    # approved-plan paths fail closed".
    with tempfile.TemporaryDirectory(prefix="op-helper-T89-cli-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        _write_synthetic_images(images_dir)
        rc_cli = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
            approved_plan_path_str="file:///tmp/whatever.json",
        )
        cli_leaked = out_dir.exists()
        cli_ok = rc_cli == 2 and not cli_leaked
    results.append(_ProbeResult(
        "T89 AP1..AP4 --approved-plan path gate: URI / symlink / "
        "directory / missing-file paths refused"
        + (" (AP2 symlink probe skipped)" if ap2_skipped else "")
        + " and operator-mode CLI refuses a URI-shaped --approved-plan "
        "without mkdir'ing --out-dir",
        ap1_ok and ap2_ok and ap4_dir_ok and ap4_missing_ok and cli_ok,
        f"ap1_ok={ap1_ok}, ap2_ok={ap2_ok}, ap4_dir_ok={ap4_dir_ok}, "
        f"ap4_missing_ok={ap4_missing_ok}, rc_cli={rc_cli}, "
        f"cli_leaked={cli_leaked}",
    ))

    # T90 normal run WITHOUT --approved-plan: summary.approved_plan
    # is exactly null (not missing, not a dict) AND the README has
    # no "Approved-plan lock" section / no "reviewer-approved plan"
    # claim — so an unlocked run never falsely implies approval.
    with tempfile.TemporaryDirectory(prefix="op-helper-T90-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        _write_synthetic_images(images_dir)
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
        )
        ok = rc == 0
        detail = f"rc={rc}"
        if ok:
            try:
                summary = json.loads(
                    (out_dir / "summary.json").read_text(),
                )
            except (OSError, json.JSONDecodeError) as exc:
                ok = False
                detail = f"summary parse failed: {exc}"
        if ok:
            # Use the `in` test so a missing key (which would route
            # through the same `summary.get("approved_plan")` return
            # value of None) is caught as a separate failure mode.
            if "approved_plan" not in summary:
                ok = False
                detail = (
                    "summary missing 'approved_plan' key; expected "
                    "the key to be present with value null"
                )
            elif summary.get("approved_plan") is not None:
                ok = False
                detail = (
                    f"summary.approved_plan="
                    f"{summary.get('approved_plan')!r}; expected "
                    f"null on an unlocked run"
                )
        if ok:
            readme_text = (
                out_dir / "README.md"
            ).read_text(encoding="utf-8")
            forbidden_in_readme = (
                "Approved-plan lock",
                "reviewer-approved plan",
                "approved_plan",
                "approved-plan",
            )
            leaked = [
                f for f in forbidden_in_readme
                if f.lower() in readme_text.lower()
            ]
            if leaked:
                ok = False
                detail = (
                    f"unlocked README leaked approval-related "
                    f"reference(s) {leaked!r}"
                )
        results.append(_ProbeResult(
            "T90 normal run WITHOUT --approved-plan: "
            "summary.approved_plan is exactly null AND README has no "
            "Approved-plan lock section or approval claim",
            ok, detail,
        ))

    # T91 tampered summary.approved_plan.matched=False fails the
    # truth-checker. The compare refuses with rc 2 BEFORE summary
    # creation on a real mismatch, so only matched=True can ever
    # legitimately reach the summary — a False value is hand-tampered
    # and the truth-checker must catch it.
    tampered_matched = {
        "schema_version": "1",
        "helper_id": "operator_local_images_to_editable_ppt",
        "real_d_one_status": _REAL_D_ONE_STATUS,
        "manifest_path": None,
        "slide_count": 1, "image_count": 1, "embedded_media_count": 1,
        "source_classes": ["local_asset"],
        "minimal_evidence": {
            "editable_text": True, "not_all_image_slide": True,
            "every_slide_has_native_shape": True, "no_blank_slide": True,
        },
        "no_external_relationships": True,
        "image_provenance": [{
            "operator_filename": "x.png", "asset_id": "x",
            "sha256": "0" * 64,
            "workspace_local_path": "x", "workspace_destination_path": "x",
            "media_type": "image/png", "byte_count": 1,
            "embedded_media_parts": ["ppt/media/image1.png"],
            "intended_slide_index": 1,
            "embedded_referencing_slides": [1],
            "placement_verified": True,
        }],
        "pptx_path": "x", "workspace_path": "x", "report_dir": "x",
        "inventory_path": "x", "registry_path": "x",
        "inventory": {
            "ok": True, "findings_empty": True, "evidence_basis": "x",
        },
        "validators": {
            "validate_source_image_assets": {"rc": 0},
            "validate_pptx_contract": {"rc": 0},
            "inspect_pptx_inventory": {"rc": 0},
            "validate_visual_quality": {"rc": 0},
        },
        "visual_quality": {
            "rc": 0, "path": "x", "report_parsed": True,
            "error_count": 0, "warning_count": 0,
        },
        "notes": {"scope": "x", "embed_surface": "x"},
        "explicit_boundaries": list(_EXPLICIT_BOUNDARIES),
        "approved_plan": {
            "path": "/tmp/approved.json",
            "sha256": "a" * 64,
            "matched": False,
        },
    }
    fails = _check_summary_truth(tampered_matched)
    results.append(_ProbeResult(
        "T91 tampered summary.approved_plan.matched=False fails the "
        "truth-checker (matched=True is the only value a real run "
        "can produce)",
        any("approved_plan.matched" in f for f in fails),
        f"failures={fails!r}",
    ))

    # T92 tampered summary.approved_plan.sha256 with wrong shape (not
    # 64-char lowercase hex) fails the truth-checker — a reviewer must
    # be able to confirm the lock by piping the recorded digest to
    # sha256sum, so an upper-cased or short value is refused.
    tampered_sha = json.loads(json.dumps(tampered_matched))
    tampered_sha["approved_plan"] = {
        "path": "/tmp/approved.json",
        "sha256": "NOTAHASH",
        "matched": True,
    }
    fails_sha = _check_summary_truth(tampered_sha)
    results.append(_ProbeResult(
        "T92 tampered summary.approved_plan.sha256 with non-hex / "
        "wrong-length value fails the truth-checker",
        any("approved_plan.sha256" in f for f in fails_sha),
        f"failures={fails_sha!r}",
    ))

    # T93 summary missing the approved_plan key entirely fails the
    # truth-checker — a tampered summary that erases the lock must
    # not pass.
    tampered_missing = json.loads(json.dumps(tampered_matched))
    del tampered_missing["approved_plan"]
    fails_missing = _check_summary_truth(tampered_missing)
    results.append(_ProbeResult(
        "T93 summary missing approved_plan key fails the truth-checker",
        any("approved_plan missing" in f for f in fails_missing),
        f"failures={fails_missing!r}",
    ))

    # T93b absent-sidecar leak enforcement. With
    # ``summary.generated_provenance`` set to null, no
    # image_provenance row may carry any sidecar field
    # (``_ABSENT_SIDECAR_LEAK_FIELDS``). Without this gate a
    # tampered summary could erase the sidecar block AND inject
    # generator_source / placement_role / etc. onto a row, smuggling
    # generated-image claims past the truth-checker. Probe
    # constructs a synthetic clean summary, sets a sidecar-only field
    # on one image_provenance row, and asserts the truth-checker
    # surfaces a "carries sidecar field(s)" diagnostic. Mirrors the
    # validator-side T23 probe so production code and on-disk
    # re-validation share one rule.
    tampered_leak = json.loads(json.dumps(tampered_matched))
    tampered_leak["approved_plan"] = {
        "path": "/tmp/approved.json",
        "sha256": "a" * 64,
        "matched": True,
    }
    tampered_leak["generated_provenance"] = None
    tampered_leak["image_provenance"][0]["generator_source"] = (
        "mock_generated"
    )
    fails_leak = _check_summary_truth(tampered_leak)
    results.append(_ProbeResult(
        "T93b absent-sidecar leak: image_provenance row carrying a "
        "sidecar field while summary.generated_provenance is null "
        "fails the truth-checker (a tampered summary cannot erase "
        "the sidecar block AND simultaneously inject "
        "generator_source / placement_role / etc. onto a row)",
        any(
            "carries sidecar field" in f for f in fails_leak
        ),
        f"failures={fails_leak!r}",
    ))

    # T94 boolean confusable: an approved plan with image_count=true /
    # byte_count=true / etc. (Python True == 1) is refused at load
    # time so it can never compare-match a single-image run via
    # True == 1 equality. Locks the regression Codex flagged.
    with tempfile.TemporaryDirectory(prefix="op-helper-T94-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        out_dir = td / "out"
        plan_out = td / "plan.json"
        # One-image fixture so True == 1 would silently compare-match
        # without the bool guard.
        images_dir.mkdir()
        (images_dir / "a.png").write_bytes(_TINY_PNG_BYTES)
        rc_plan = _run_plan_only_mode(
            images_dir_str=str(images_dir),
            plan_out_str=str(plan_out),
        )
        tampered = json.loads(plan_out.read_text(encoding="utf-8"))
        tampered["image_count"] = True
        tampered["slide_count"] = True
        tampered["images"][0]["byte_count"] = True
        tampered["images"][0]["intended_slide_index"] = True
        plan_out.write_text(
            json.dumps(tampered) + "\n", encoding="utf-8",
        )
        rc = _run_operator_mode(
            images_dir_str=str(images_dir),
            out_dir_str=str(out_dir),
            approved_plan_path_str=str(plan_out),
        )
        artifact_paths = [
            out_dir / "deck.pptx",
            out_dir / "summary.json",
            out_dir / "inventory.json",
            out_dir / "visual_quality.json",
            out_dir / "README.md",
            out_dir / "workspace",
            out_dir / "reports",
            out_dir / "_pipeline_fixture",
        ]
        leaked = [str(p) for p in artifact_paths if p.exists()]
        ok = rc_plan == 0 and rc == 2 and not leaked
        results.append(_ProbeResult(
            "T94 boolean confusable in approved-plan int fields "
            "(image_count / slide_count / byte_count / "
            "intended_slide_index = true) refused; no deck / summary "
            "/ inventory / visual_quality / README / workspace / "
            "reports / _pipeline_fixture artifact materialised",
            ok,
            f"rc_plan={rc_plan}, rc={rc}, leaked={leaked!r}",
        ))

    # T95 _load_approved_plan returns the sha256 of the bytes it
    # actually read, captured at read time. Locks the contract that
    # eliminates the TOCTOU race where a second read_bytes() call
    # for evidence could hash different bytes than the ones the
    # helper compared against (Codex stop-time review caught this on
    # the first iteration). The probe deliberately deletes the plan
    # file BEFORE inspecting the returned digest: if the helper had
    # been lazily re-reading, deletion would force a None / failure;
    # the captured digest must survive the file going away because
    # it was computed in memory from bytes the helper already owns.
    with tempfile.TemporaryDirectory(prefix="op-helper-T95-") as raw_td:
        td = Path(raw_td)
        plan_path = td / "plan.json"
        body = {
            "schema_version": "1",
            "helper_id": "operator_local_images_to_editable_ppt",
            "mode": "plan_only",
            "image_count": 0,
            "slide_count": 0,
            "manifest_path": None,
            "explicit_boundaries": list(_EXPLICIT_BOUNDARIES),
            "images": [],
        }
        raw_bytes = (
            json.dumps(body, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        plan_path.write_bytes(raw_bytes)
        expected_sha = hashlib.sha256(raw_bytes).hexdigest()
        plan, sha, fails_load = _load_approved_plan(plan_path)
        plan_path.unlink()
        ok = (
            plan is not None
            and not fails_load
            and sha == expected_sha
            and not plan_path.exists()
        )
        results.append(_ProbeResult(
            "T95 _load_approved_plan captures sha256 over the bytes "
            "it just read; the digest survives the source file being "
            "deleted before the caller inspects it (eliminates TOCTOU "
            "re-read race where a second read could hash different "
            "bytes than were compared)",
            ok,
            f"plan={plan!r}, sha={sha!r}, "
            f"expected_sha={expected_sha!r}, "
            f"fails={fails_load!r}",
        ))

    # ----- BUN1..BUN13: --bundle shortcut probes -----

    # BUN-HAPPY1 --bundle resolves to <bundle>/images and produces the
    # same 2-slide deck the explicit --images-dir flow produces from
    # the same bytes (no manifest). Locks the no-manifest happy path
    # through the shortcut.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN1-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 0
        detail = f"rc={rc}"
        if ok:
            try:
                summary = json.loads(
                    (out_dir / "summary.json").read_text(),
                )
            except (OSError, json.JSONDecodeError) as exc:
                ok = False
                detail = f"summary parse failed: {exc}"
            else:
                if summary.get("image_count") != 2:
                    ok = False
                    detail = (
                        f"image_count={summary.get('image_count')!r}, "
                        f"expected 2"
                    )
                elif summary.get("manifest_path") is not None:
                    ok = False
                    detail = (
                        f"manifest_path="
                        f"{summary.get('manifest_path')!r}; expected "
                        f"None (no manifest in bundle)"
                    )
                elif not (out_dir / "deck.pptx").is_file():
                    ok = False
                    detail = "deck.pptx missing"
        results.append(_ProbeResult(
            "BUN-HAPPY1 --bundle DIR --out-dir OUT (no manifest in "
            "bundle) produces the same 2-slide editable deck the "
            "explicit --images-dir flow produces and records "
            "manifest_path=None",
            ok, detail,
        ))

    # BUN-HAPPY2 --bundle resolves to <bundle>/images + forwards
    # <bundle>/manifest.json. The manifest reorders the synthetic
    # images so the produced summary echoes manifest order and
    # records the resolved manifest path. Locks the manifest-present
    # happy path through the shortcut.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN2-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        manifest = bundle / "manifest.json"
        manifest.write_text(json.dumps({
            "schema_version": "1",
            "images": [
                {
                    "filename": "beta_marker.jpg",
                    "slide_title": "Beta first",
                    "alt_text": "Beta first",
                    "intended_use": "decorative",
                },
                {
                    "filename": "alpha_marker.png",
                    "slide_title": "Alpha second",
                    "alt_text": "Alpha second",
                    "intended_use": "icon",
                },
            ],
        }) + "\n", encoding="utf-8")
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 0
        detail = f"rc={rc}"
        if ok:
            try:
                summary = json.loads(
                    (out_dir / "summary.json").read_text(),
                )
            except (OSError, json.JSONDecodeError) as exc:
                ok = False
                detail = f"summary parse failed: {exc}"
            else:
                prov = summary.get("image_provenance") or []
                if summary.get("manifest_path") != str(manifest):
                    ok = False
                    detail = (
                        f"manifest_path="
                        f"{summary.get('manifest_path')!r}; expected "
                        f"{str(manifest)!r}"
                    )
                elif (
                    [p.get("operator_filename") for p in prov]
                    != ["beta_marker.jpg", "alpha_marker.png"]
                ):
                    ok = False
                    detail = (
                        f"provenance order "
                        f"{[p.get('operator_filename') for p in prov]!r}; "
                        f"expected manifest order [beta, alpha]"
                    )
        results.append(_ProbeResult(
            "BUN-HAPPY2 --bundle DIR --out-dir OUT (bundle carries "
            "manifest.json) forwards the manifest unchanged: "
            "summary.manifest_path equals <bundle>/manifest.json and "
            "provenance follows manifest order",
            ok, detail,
        ))

    # BUN-HAPPY3 --bundle DIR --plan-out PATH writes the SAME plan
    # bytes the explicit --images-dir / --manifest pair would have
    # produced. Locks plan-only mode through the shortcut.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN3-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        plan_via_bundle = td / "plan_bundle.json"
        plan_via_explicit = td / "plan_explicit.json"
        rc_bundle = main([
            "--bundle", str(bundle),
            "--plan-out", str(plan_via_bundle),
        ])
        rc_explicit = main([
            "--images-dir", str(bundle / "images"),
            "--plan-out", str(plan_via_explicit),
        ])
        ok = rc_bundle == 0 and rc_explicit == 0
        detail = f"rc_bundle={rc_bundle}, rc_explicit={rc_explicit}"
        if ok:
            bundle_bytes = plan_via_bundle.read_bytes()
            explicit_bytes = plan_via_explicit.read_bytes()
            if bundle_bytes != explicit_bytes:
                ok = False
                detail = (
                    "plan bytes differ between --bundle and explicit "
                    "--images-dir paths (shortcut must produce byte-"
                    "identical plans)"
                )
        results.append(_ProbeResult(
            "BUN-HAPPY3 --bundle DIR --plan-out PATH produces the "
            "byte-identical plan an explicit --images-dir "
            "<bundle>/images --plan-out PATH run produces",
            ok, detail,
        ))

    # BUN-HAPPY4 --bundle DIR --out-dir OUT --approved-plan PATH
    # accepts a plan generated by --bundle DIR --plan-out PATH on the
    # same bytes. Locks the approved-plan lock through the shortcut.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN4-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        plan_out = td / "approved.json"
        out_dir = td / "out"
        rc_plan = main([
            "--bundle", str(bundle), "--plan-out", str(plan_out),
        ])
        rc_run = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
            "--approved-plan", str(plan_out),
        ])
        ok = (
            rc_plan == 0
            and rc_run == 0
            and (out_dir / "deck.pptx").is_file()
            and (out_dir / "summary.json").is_file()
        )
        detail = (
            f"rc_plan={rc_plan}, rc_run={rc_run}, "
            f"deck={(out_dir / 'deck.pptx').is_file()}"
        )
        if ok:
            try:
                summary = json.loads(
                    (out_dir / "summary.json").read_text(),
                )
            except (OSError, json.JSONDecodeError) as exc:
                ok = False
                detail = f"summary parse failed: {exc}"
            else:
                ap = summary.get("approved_plan") or {}
                if ap.get("matched") is not True:
                    ok = False
                    detail = (
                        f"approved_plan.matched={ap.get('matched')!r}; "
                        f"expected True"
                    )
        results.append(_ProbeResult(
            "BUN-HAPPY4 --bundle DIR --out-dir OUT --approved-plan "
            "PATH (plan generated via --bundle --plan-out) accepts "
            "the lock and records summary.approved_plan.matched=True",
            ok, detail,
        ))

    # BUN-DRIFT --bundle approved-plan drift: --plan-out then a byte
    # change to one image flips its sha256 + byte_count; the helper
    # must refuse with rc 2 BEFORE deck.pptx / summary / inventory /
    # visual_quality / README / workspace / reports materialise.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN-D-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        plan_out = td / "approved.json"
        out_dir = td / "out"
        rc_plan = main([
            "--bundle", str(bundle), "--plan-out", str(plan_out),
        ])
        # Append a benign trailing byte to one image to force a
        # sha256 / byte_count change while keeping the PNG signature.
        target = bundle / "images" / "alpha_marker.png"
        target.write_bytes(target.read_bytes() + b"\x00")
        rc_run = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
            "--approved-plan", str(plan_out),
        ])
        leaked = [
            p for p in (
                out_dir / "deck.pptx",
                out_dir / "summary.json",
                out_dir / "inventory.json",
                out_dir / "visual_quality.json",
                out_dir / "README.md",
                out_dir / "workspace",
                out_dir / "reports",
                out_dir / "_pipeline_fixture",
            ) if p.exists()
        ]
        ok = rc_plan == 0 and rc_run == 2 and not leaked
        results.append(_ProbeResult(
            "BUN-DRIFT --bundle --approved-plan refuses a "
            "post-approval image byte change with rc 2 and writes no "
            "deck / summary / inventory / visual_quality / README / "
            "workspace / reports artifact under --out-dir",
            ok,
            f"rc_plan={rc_plan}, rc_run={rc_run}, "
            f"leaked={[str(p) for p in leaked]!r}",
        ))

    # BUN1 URI-shaped --bundle refused.
    _img, _man, _sc, fails = _validate_bundle_arg(
        "file:///tmp/bundle",
    )
    results.append(_ProbeResult(
        "BUN1 URI-shaped --bundle refused with a clean diagnostic "
        "naming BUN1",
        any("BUN1" in f for f in fails),
        f"fails={fails!r}",
    ))

    # BUN2 --bundle itself is a symlink — refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN-S-") as raw_td:
        td = Path(raw_td)
        real = td / "real"
        real.mkdir()
        (real / "images").mkdir()
        link = td / "linked_bundle"
        os.symlink(real, link)
        _img, _man, _sc, fails = _validate_bundle_arg(str(link))
        results.append(_ProbeResult(
            "BUN2 symlink --bundle refused with a clean diagnostic "
            "naming BUN2",
            any("BUN2" in f for f in fails),
            f"fails={fails!r}",
        ))

    # BUN3 --bundle ancestor is a symlink — refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN-A-") as raw_td:
        td = Path(raw_td)
        real = td / "real"
        real.mkdir()
        bundle = real / "bundle"
        bundle.mkdir()
        (bundle / "images").mkdir()
        link = td / "linked_real"
        os.symlink(real, link)
        bundle_via_link = link / "bundle"
        _img, _man, _sc, fails = _validate_bundle_arg(str(bundle_via_link))
        results.append(_ProbeResult(
            "BUN3 symlink ancestor of --bundle refused with a clean "
            "diagnostic naming BUN3",
            any("BUN3" in f for f in fails),
            f"fails={fails!r}",
        ))

    # BUN4 missing --bundle refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN-M-") as raw_td:
        td = Path(raw_td)
        missing = td / "no_such_bundle"
        _img, _man, _sc, fails = _validate_bundle_arg(str(missing))
        results.append(_ProbeResult(
            "BUN4 missing --bundle refused with a clean diagnostic "
            "naming BUN4",
            any("BUN4" in f for f in fails),
            f"fails={fails!r}",
        ))

    # BUN5 --bundle is a regular file (not a directory) — refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN-F-") as raw_td:
        td = Path(raw_td)
        not_dir = td / "bundle.txt"
        not_dir.write_text("not a bundle", encoding="utf-8")
        _img, _man, _sc, fails = _validate_bundle_arg(str(not_dir))
        results.append(_ProbeResult(
            "BUN5 --bundle that points at a regular file refused with "
            "a clean diagnostic naming BUN5",
            any("BUN5" in f for f in fails),
            f"fails={fails!r}",
        ))

    # BUN6 --bundle without images/ subdir — refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN-I-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        # Deliberately do NOT create bundle/images/
        _img, _man, _sc, fails = _validate_bundle_arg(str(bundle))
        results.append(_ProbeResult(
            "BUN6 --bundle without an images/ subdir refused with a "
            "clean diagnostic naming BUN6",
            any("BUN6" in f for f in fails),
            f"fails={fails!r}",
        ))

    # BUN7 <bundle>/images is itself a symlink — refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN-IS-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        real_images = td / "real_images"
        real_images.mkdir()
        os.symlink(real_images, bundle / "images")
        _img, _man, _sc, fails = _validate_bundle_arg(str(bundle))
        results.append(_ProbeResult(
            "BUN7 symlinked <bundle>/images refused with a clean "
            "diagnostic naming BUN7",
            any("BUN7" in f for f in fails),
            f"fails={fails!r}",
        ))

    # BUN8 <bundle>/images is a regular file — refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN-IN-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        (bundle / "images").write_text(
            "not a directory", encoding="utf-8",
        )
        _img, _man, _sc, fails = _validate_bundle_arg(str(bundle))
        results.append(_ProbeResult(
            "BUN8 non-directory <bundle>/images refused with a clean "
            "diagnostic naming BUN8",
            any("BUN8" in f for f in fails),
            f"fails={fails!r}",
        ))

    # BUN-MAN-MALFORMED bundle resolution forwards <bundle>/manifest.json
    # verbatim; malformed JSON is caught by the existing MAN5 gate so
    # the operator sees a clean per-failure diagnostic before any
    # pipeline subprocess fires.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN-MM-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        # Write bytes that aren't valid JSON.
        (bundle / "manifest.json").write_text(
            "{not valid json}", encoding="utf-8",
        )
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 2 and not out_dir.exists()
        results.append(_ProbeResult(
            "BUN-MAN-MALFORMED malformed <bundle>/manifest.json "
            "refused via the existing MAN5 gate (rc 2, no --out-dir "
            "artifact materialised)",
            ok,
            f"rc={rc}, out_dir_exists={out_dir.exists()}",
        ))

    # BUN-MIX1 --bundle + --images-dir is ambiguous and refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN-X1-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        other_images = td / "other_images"
        _write_synthetic_images(other_images)
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle),
            "--images-dir", str(other_images),
            "--out-dir", str(out_dir),
        ])
        ok = rc == 2 and not out_dir.exists()
        results.append(_ProbeResult(
            "BUN-MIX1 --bundle + --images-dir refused (mixed input "
            "styles are ambiguous; the helper requires a single "
            "source for the image directory) with rc 2 and no "
            "--out-dir artifact materialised",
            ok,
            f"rc={rc}, out_dir_exists={out_dir.exists()}",
        ))

    # BUN-MIX2 --bundle + --manifest is ambiguous and refused.
    with tempfile.TemporaryDirectory(prefix="op-helper-BUN-X2-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        external_manifest = td / "external_manifest.json"
        external_manifest.write_text(json.dumps({
            "schema_version": "1",
            "images": [
                {
                    "filename": "alpha_marker.png",
                    "slide_title": "Alpha",
                    "alt_text": "Alpha",
                    "intended_use": "icon",
                },
                {
                    "filename": "beta_marker.jpg",
                    "slide_title": "Beta",
                    "alt_text": "Beta",
                    "intended_use": "icon",
                },
            ],
        }) + "\n", encoding="utf-8")
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle),
            "--manifest", str(external_manifest),
            "--out-dir", str(out_dir),
        ])
        ok = rc == 2 and not out_dir.exists()
        results.append(_ProbeResult(
            "BUN-MIX2 --bundle + --manifest refused (mixed input "
            "styles are ambiguous; the helper requires a single "
            "source for the manifest path) with rc 2 and no "
            "--out-dir artifact materialised",
            ok,
            f"rc={rc}, out_dir_exists={out_dir.exists()}",
        ))

    # BUN-MIX3 --self-test + --bundle refused.
    rc_st = main(["--self-test", "--bundle", "/tmp/anywhere"])
    results.append(_ProbeResult(
        "BUN-MIX3 --self-test + --bundle refused with rc 2",
        rc_st == 2,
        f"rc={rc_st}",
    ))

    # ----- GP-* generated-image provenance sidecar probes -----

    def _make_sidecar_body(filenames: tuple[str, ...]) -> dict:
        """Synthesize a minimum-viable sidecar covering the two
        synthetic operator images _write_synthetic_images produces."""
        roles = ["hero_page", "local_region"]
        policies = ["no_text", "decorative_glyphs"]
        domains = ["abstract_marker", "background_pattern"]
        return {
            "schema_version": "1",
            "entries": [
                {
                    "filename": fn,
                    "generator_source": "mock_generated",
                    "intent_summary": (
                        f"Synthetic accent for {fn} (mock; "
                        f"local-only)"
                    ),
                    "placement_role": roles[i % len(roles)],
                    "text_policy": policies[i % len(policies)],
                    "subject_domain": domains[i % len(domains)],
                }
                for i, fn in enumerate(filenames)
            ],
        }

    # GP-HAPPY1 sidecar present in the bundle: the produced summary
    # carries summary.generated_provenance.{path, entry_count} and
    # every image_provenance row echoes the per-entry generator_source
    # / intent_summary / placement_role / text_policy /
    # subject_domain. README has a "Generated image provenance"
    # section. The produced PPTX + review-package keep validating.
    with tempfile.TemporaryDirectory(prefix="op-helper-GP-H1-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        sidecar_path = bundle / "generated_provenance.json"
        sidecar_path.write_text(
            json.dumps(_make_sidecar_body(
                ("alpha_marker.png", "beta_marker.jpg"),
            )) + "\n",
            encoding="utf-8",
        )
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 0
        detail = f"rc={rc}"
        if ok:
            try:
                summary = json.loads(
                    (out_dir / "summary.json").read_text(),
                )
            except (OSError, json.JSONDecodeError) as exc:
                ok = False
                detail = f"summary parse failed: {exc}"
            else:
                # Key-present + non-null dict gate FIRST so a
                # regression that omits the key entirely or sets it
                # to null (instead of a {path, entry_count} dict)
                # fails this probe with a precise diagnostic, not as
                # a downstream "path mismatch" that obscures the
                # actual regression. Mirrors the GP-ABSENT
                # missing-key gate one branch over.
                if "generated_provenance" not in summary:
                    gp_block: dict = {}
                    detail_for_gp_block = (
                        "summary.generated_provenance key MISSING "
                        "from the dict; expected "
                        "{path, entry_count}"
                    )
                elif not isinstance(
                    summary["generated_provenance"], dict
                ):
                    gp_block = {}
                    detail_for_gp_block = (
                        f"generated_provenance="
                        f"{summary['generated_provenance']!r}; "
                        f"expected dict {{path, entry_count}}"
                    )
                else:
                    gp_block = summary["generated_provenance"]
                    detail_for_gp_block = ""
                prov = summary.get("image_provenance") or []
                if detail_for_gp_block:
                    ok = False
                    detail = detail_for_gp_block
                elif gp_block.get("path") != str(sidecar_path):
                    ok = False
                    detail = (
                        f"generated_provenance.path="
                        f"{gp_block.get('path')!r}; expected "
                        f"{str(sidecar_path)!r}"
                    )
                elif gp_block.get("entry_count") != 2:
                    ok = False
                    detail = (
                        f"generated_provenance.entry_count="
                        f"{gp_block.get('entry_count')!r}; expected 2"
                    )
                elif not all(
                    p.get("generator_source") == "mock_generated"
                    and isinstance(p.get("intent_summary"), str)
                    and p.get("placement_role")
                        in _SIDECAR_ALLOWED_PLACEMENT_ROLES
                    and p.get("text_policy")
                        in _SIDECAR_ALLOWED_TEXT_POLICIES
                    and p.get("subject_domain")
                        in _SIDECAR_ALLOWED_SUBJECT_DOMAINS
                    for p in prov
                ):
                    ok = False
                    detail = (
                        "image_provenance rows missing one or more "
                        "sidecar fields"
                    )
                else:
                    readme_text = (
                        out_dir / "README.md"
                    ).read_text(encoding="utf-8")
                    if "Generated image provenance" not in readme_text:
                        ok = False
                        detail = (
                            "README is missing the 'Generated image "
                            "provenance' section"
                        )
        results.append(_ProbeResult(
            "GP-HAPPY1 <bundle>/generated_provenance.json: summary "
            "carries generated_provenance + every image_provenance "
            "row echoes the sidecar enums + README names the "
            "section",
            ok, detail,
        ))

    # GP-ABSENT bundle without sidecar: the produced PPTX / workspace
    # / reports / inventory / visual_quality and the README section
    # list are unchanged versus the pre-sidecar bundle path, but
    # summary.json always carries the new top-level
    # ``generated_provenance`` key (``null`` here) — mirroring the
    # ``approved_plan: null`` key every run carries when no
    # ``--approved-plan`` is supplied. This locks the absent-sidecar
    # compatibility invariant the goal calls out: the key addition is
    # a forward-only summary-shape evolution, NOT a byte-for-byte
    # equality with the pre-sidecar summary.
    with tempfile.TemporaryDirectory(prefix="op-helper-GP-A-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        # Deliberately omit <bundle>/generated_provenance.json.
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 0
        detail = f"rc={rc}"
        if ok:
            try:
                summary = json.loads(
                    (out_dir / "summary.json").read_text(),
                )
            except (OSError, json.JSONDecodeError) as exc:
                ok = False
                detail = f"summary parse failed: {exc}"
            else:
                # The summary-shape gate lives in the module-level
                # ``_absent_sidecar_summary_gate`` helper so the
                # GP-ABSENT-NEG negative proof below can exercise the
                # SAME function on mutated synthetic inputs. A
                # refactor that weakens the gate (e.g., reverts the
                # key-present check to ``summary.get(...) is not
                # None`` and so false-greens a forgotten-key
                # regression) fails GP-ABSENT-NEG at run time.
                gate_failure = _absent_sidecar_summary_gate(summary)
                if gate_failure is not None:
                    ok = False
                    detail = gate_failure
                else:
                    readme_text = (
                        out_dir / "README.md"
                    ).read_text(encoding="utf-8")
                    if "Generated image provenance" in readme_text:
                        ok = False
                        detail = (
                            "README has 'Generated image provenance' "
                            "section despite absent sidecar"
                        )
        results.append(_ProbeResult(
            "GP-ABSENT bundle without "
            "generated_provenance.json: summary.generated_provenance "
            "is null (the only summary-shape addition versus the "
            "pre-sidecar bundle path; parallels approved_plan=null), "
            "no image_provenance row carries sidecar fields, README "
            "omits the section",
            ok, detail,
        ))

    # GP-ABSENT-NEG explicit proof that the GP-ABSENT shape gate
    # (``_absent_sidecar_summary_gate``) fires on each of the three
    # regressions an absent-sidecar summary must refuse: forgotten
    # key, explicit non-null value, leaked sidecar field on any
    # image_provenance row. Plus one positive control to confirm
    # the gate returns None (pass) for a clean absent-sidecar
    # summary shape, so the probe is not just asserting "the gate
    # always fails".
    #
    # This calls the SAME function GP-ABSENT calls; a refactor that
    # weakens the gate (e.g., reverts the key-present check to
    # ``summary.get(...) is not None`` so a missing key
    # false-greens) is caught here at run time. Earlier this probe
    # asserted Python ``in``/``get`` semantics directly — a
    # tautology that would still pass even if the GP-ABSENT probe
    # itself stopped exercising the ``in`` check. The function-
    # level call binds the proof to the production gate code.
    _clean_summary: dict = {
        "generated_provenance": None,
        "image_provenance": [
            {"operator_filename": "alpha_marker.png"},
            {"operator_filename": "beta_marker.jpg"},
        ],
    }
    _missing_key_summary = {
        k: v for k, v in _clean_summary.items()
        if k != "generated_provenance"
    }
    _non_null_value_summary = dict(_clean_summary)
    _non_null_value_summary["generated_provenance"] = {
        "path": "/tmp/forged.json", "entry_count": 2,
    }
    _leaked_field_summary: dict = {
        "generated_provenance": None,
        "image_provenance": [
            {
                "operator_filename": "alpha_marker.png",
                # The leak — a sidecar-only field on an
                # image_provenance row of an absent-sidecar run.
                "generator_source": "mock_generated",
            },
        ],
    }
    _clean_diag = _absent_sidecar_summary_gate(_clean_summary)
    _missing_diag = _absent_sidecar_summary_gate(_missing_key_summary)
    _non_null_diag = _absent_sidecar_summary_gate(
        _non_null_value_summary,
    )
    _leaked_diag = _absent_sidecar_summary_gate(_leaked_field_summary)
    results.append(_ProbeResult(
        "GP-ABSENT-NEG _absent_sidecar_summary_gate returns None "
        "on a clean absent-sidecar summary, and a non-None "
        "diagnostic on each of the three documented regressions "
        "(missing key, non-null value, leaked sidecar field on an "
        "image_provenance row) — locks the gate's behaviour "
        "against a refactor that weakens it (e.g., reverts the "
        "key-present check to ``summary.get(...) is not None`` and "
        "false-greens a forgotten-key regression)",
        (
            _clean_diag is None
            and _missing_diag is not None
            and "MISSING" in _missing_diag
            and _non_null_diag is not None
            and "expected explicit null" in _non_null_diag
            and _leaked_diag is not None
            and "carries sidecar fields" in _leaked_diag
        ),
        (
            f"clean={_clean_diag!r}; "
            f"missing={_missing_diag!r}; "
            f"non_null={_non_null_diag!r}; "
            f"leaked={_leaked_diag!r}"
        ),
    ))

    # GP-MISMATCH-MISSING sidecar omits a discovered filename. GP13
    # refuses with rc 2 and no --out-dir artifact materialises.
    with tempfile.TemporaryDirectory(prefix="op-helper-GP-MM-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        sidecar = bundle / "generated_provenance.json"
        body = _make_sidecar_body(("alpha_marker.png",))
        sidecar.write_text(
            json.dumps(body) + "\n", encoding="utf-8",
        )
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 2 and not out_dir.exists()
        results.append(_ProbeResult(
            "GP-MISMATCH-MISSING sidecar that omits a discovered "
            "filename is refused (GP13) with rc 2 and no --out-dir "
            "artifact materialised",
            ok,
            f"rc={rc}, out_dir_exists={out_dir.exists()}",
        ))

    # GP-MISMATCH-EXTRA sidecar names an extra (unknown) filename.
    # GP12 refuses with rc 2 and no --out-dir artifact materialises.
    with tempfile.TemporaryDirectory(prefix="op-helper-GP-MX-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        sidecar = bundle / "generated_provenance.json"
        body = _make_sidecar_body((
            "alpha_marker.png", "beta_marker.jpg", "ghost.png",
        ))
        sidecar.write_text(
            json.dumps(body) + "\n", encoding="utf-8",
        )
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 2 and not out_dir.exists()
        results.append(_ProbeResult(
            "GP-MISMATCH-EXTRA sidecar that names an unknown "
            "filename is refused (GP12) with rc 2 and no --out-dir "
            "artifact materialised",
            ok,
            f"rc={rc}, out_dir_exists={out_dir.exists()}",
        ))

    # GP-MISMATCH-DUPE sidecar names the same filename twice. GP12
    # refuses with rc 2 and no --out-dir artifact materialises.
    with tempfile.TemporaryDirectory(prefix="op-helper-GP-MD-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        sidecar = bundle / "generated_provenance.json"
        body = _make_sidecar_body(("alpha_marker.png", "beta_marker.jpg"))
        # Duplicate the first entry's filename onto the second slot.
        body["entries"][1]["filename"] = "alpha_marker.png"
        sidecar.write_text(
            json.dumps(body) + "\n", encoding="utf-8",
        )
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 2 and not out_dir.exists()
        results.append(_ProbeResult(
            "GP-MISMATCH-DUPE sidecar that names a filename twice "
            "is refused (GP12) with rc 2 and no --out-dir artifact "
            "materialised",
            ok,
            f"rc={rc}, out_dir_exists={out_dir.exists()}",
        ))

    # GP-UNSAFE-URL sidecar carries a URL in intent_summary. The
    # safe-string scan GP10 refuses with rc 2.
    with tempfile.TemporaryDirectory(prefix="op-helper-GP-U-U-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        sidecar = bundle / "generated_provenance.json"
        body = _make_sidecar_body(("alpha_marker.png", "beta_marker.jpg"))
        body["entries"][0]["intent_summary"] = (
            "Download from https://example.invalid/image.png"
        )
        sidecar.write_text(
            json.dumps(body) + "\n", encoding="utf-8",
        )
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 2 and not out_dir.exists()
        results.append(_ProbeResult(
            "GP-UNSAFE-URL sidecar intent_summary carrying a URL is "
            "refused (GP10) with rc 2 and no --out-dir artifact "
            "materialised",
            ok,
            f"rc={rc}, out_dir_exists={out_dir.exists()}",
        ))

    # GP-UNSAFE-DATA-URI sidecar intent_summary embeds a dangerous
    # single-colon URI scheme (data: / mailto: / javascript: /
    # file:) mid-text. The ``://`` substring + start-anchored
    # ``_has_uri_scheme`` checks miss these; the new
    # ``_DANGEROUS_URI_SCHEME_REGEX`` refuses them at the operator
    # boundary (before the validator's defense-in-depth text scan
    # on the produced summary.json fires).
    #
    # Naive ``rc == 2`` + ``not out_dir.exists()`` is NOT enough:
    # ``data:image/png;base64,...`` and ``file:/etc/passwd`` both
    # contain ``/`` so the older path-separator gate already
    # refuses them — the probe would false-green for those two
    # shapes by piggybacking on a gate the new regex was supposed
    # to replace. Call ``_safe_sidecar_intent_summary`` directly
    # and assert the failure diagnostic mentions the new
    # "dangerous single-colon URI scheme" wording, so the proof
    # is bound to ``_DANGEROUS_URI_SCHEME_REGEX`` specifically.
    # Use slash-free no-path variants for data:/file: alongside
    # the inherently slash-free mailto:/javascript: shapes so the
    # path-separator gate cannot fire on any payload — every
    # refusal must come from the new gate.
    _data_uri_shapes = (
        # data:base64 with NO content-type slash so the
        # path-separator gate cannot pre-empt the new gate.
        ("data", "Accent based on data:dGVzdA=="),
        ("mailto", "Contact ops via mailto:operator@example.invalid"),
        ("javascript", "Trigger via javascript:alert(1) not run"),
        # file: shape with NO slash so the path-separator gate
        # cannot pre-empt the new gate.
        ("file", "Reference file:passwd context"),
    )
    _data_uri_failures: list[str] = []
    for scheme, payload in _data_uri_shapes:
        # Cheap pre-flight: a payload that contains "/" or "\\"
        # would let the path-separator gate refuse it before the
        # new regex runs, so the probe would not be a proof about
        # ``_DANGEROUS_URI_SCHEME_REGEX``. Refuse such shapes from
        # the probe payload set at construction time.
        if "/" in payload or "\\" in payload or "://" in payload:
            _data_uri_failures.append(
                f"{scheme}: probe payload {payload!r} contains a "
                f"path separator / '://' — would false-green via "
                f"the older gate; rewrite the payload so only the "
                f"new gate can refuse it"
            )
            continue
        cleaned, fail = _safe_sidecar_intent_summary(
            value=payload, entry_idx=0,
        )
        if cleaned is not None or fail is None:
            _data_uri_failures.append(
                f"{scheme}: payload {payload!r} not refused "
                f"(cleaned={cleaned!r}, fail={fail!r})"
            )
            continue
        if "dangerous single-colon URI scheme" not in fail:
            _data_uri_failures.append(
                f"{scheme}: payload {payload!r} refused by a "
                f"different gate than _DANGEROUS_URI_SCHEME_REGEX "
                f"(diagnostic: {fail!r}); the probe must bind to "
                f"the new gate, not piggyback on another gate"
            )
            continue
        if f"{scheme!r}" not in fail and scheme not in fail:
            _data_uri_failures.append(
                f"{scheme}: refusal diagnostic does not name the "
                f"matched scheme (got: {fail!r})"
            )
    results.append(_ProbeResult(
        "GP-UNSAFE-DATA-URI sidecar intent_summary embedding a "
        "dangerous single-colon URI scheme (data: / mailto: / "
        "javascript: / file:) mid-text is refused by "
        "_DANGEROUS_URI_SCHEME_REGEX specifically (probe calls "
        "_safe_sidecar_intent_summary directly and asserts the "
        "'dangerous single-colon URI scheme' wording in the "
        "diagnostic, so a path-separator-gate piggyback cannot "
        "false-green any shape). Uses slash-free payloads for "
        "data: and file: alongside the inherently slash-free "
        "mailto: and javascript: shapes",
        not _data_uri_failures,
        (
            "all four dangerous schemes refused by the new gate "
            "with the expected diagnostic"
            if not _data_uri_failures
            else f"failures: {_data_uri_failures!r}"
        ),
    ))

    # GP-UNSAFE-DONE sidecar claims real D-One success. The
    # fake-success scan GP10 refuses with rc 2.
    with tempfile.TemporaryDirectory(prefix="op-helper-GP-U-D-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        sidecar = bundle / "generated_provenance.json"
        body = _make_sidecar_body(("alpha_marker.png", "beta_marker.jpg"))
        body["entries"][0]["intent_summary"] = (
            "Real D-One generated this asset"
        )
        sidecar.write_text(
            json.dumps(body) + "\n", encoding="utf-8",
        )
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 2 and not out_dir.exists()
        results.append(_ProbeResult(
            "GP-UNSAFE-DONE sidecar intent_summary that claims real "
            "D-One success is refused (GP10) with rc 2 and no "
            "--out-dir artifact materialised",
            ok,
            f"rc={rc}, out_dir_exists={out_dir.exists()}",
        ))

    # GP-UNSAFE-CRED sidecar intent_summary carries an API-key shape.
    with tempfile.TemporaryDirectory(prefix="op-helper-GP-U-C-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        sidecar = bundle / "generated_provenance.json"
        body = _make_sidecar_body(("alpha_marker.png", "beta_marker.jpg"))
        body["entries"][0]["intent_summary"] = (
            "Generated with API_KEY abc123def456"
        )
        sidecar.write_text(
            json.dumps(body) + "\n", encoding="utf-8",
        )
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 2 and not out_dir.exists()
        results.append(_ProbeResult(
            "GP-UNSAFE-CRED sidecar intent_summary that carries a "
            "credential token is refused (GP10) with rc 2 and no "
            "--out-dir artifact materialised",
            ok,
            f"rc={rc}, out_dir_exists={out_dir.exists()}",
        ))

    # GP-UNSAFE-CONF sidecar intent_summary names confidential /
    # customer markers.
    with tempfile.TemporaryDirectory(prefix="op-helper-GP-U-F-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        sidecar = bundle / "generated_provenance.json"
        body = _make_sidecar_body(("alpha_marker.png", "beta_marker.jpg"))
        body["entries"][0]["intent_summary"] = (
            "Marker referencing confidential customer data row"
        )
        sidecar.write_text(
            json.dumps(body) + "\n", encoding="utf-8",
        )
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 2 and not out_dir.exists()
        results.append(_ProbeResult(
            "GP-UNSAFE-CONF sidecar intent_summary that names "
            "confidential / customer markers is refused (GP10) with "
            "rc 2 and no --out-dir artifact materialised",
            ok,
            f"rc={rc}, out_dir_exists={out_dir.exists()}",
        ))

    # GP-UNSAFE-ENUM sidecar entry carries an out-of-vocab
    # placement_role. GP9 refuses with rc 2.
    with tempfile.TemporaryDirectory(prefix="op-helper-GP-U-E-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        sidecar = bundle / "generated_provenance.json"
        body = _make_sidecar_body(("alpha_marker.png", "beta_marker.jpg"))
        body["entries"][0]["placement_role"] = "billboard"
        sidecar.write_text(
            json.dumps(body) + "\n", encoding="utf-8",
        )
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 2 and not out_dir.exists()
        results.append(_ProbeResult(
            "GP-UNSAFE-ENUM sidecar entry with an out-of-vocab "
            "placement_role is refused (GP9) with rc 2 and no "
            "--out-dir artifact materialised",
            ok,
            f"rc={rc}, out_dir_exists={out_dir.exists()}",
        ))

    # GP-UNSAFE-CD sidecar carries an unsafe custom_descriptor (mixed
    # case + dash). GP11 refuses with rc 2.
    with tempfile.TemporaryDirectory(prefix="op-helper-GP-U-D2-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        sidecar = bundle / "generated_provenance.json"
        body = _make_sidecar_body(("alpha_marker.png", "beta_marker.jpg"))
        body["entries"][0]["custom_descriptor"] = "Bad-Pattern!"
        sidecar.write_text(
            json.dumps(body) + "\n", encoding="utf-8",
        )
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 2 and not out_dir.exists()
        results.append(_ProbeResult(
            "GP-UNSAFE-CD sidecar entry with an out-of-pattern "
            "custom_descriptor is refused (GP11) with rc 2 and no "
            "--out-dir artifact materialised",
            ok,
            f"rc={rc}, out_dir_exists={out_dir.exists()}",
        ))

    # GP-SYMLINK sidecar at <bundle>/generated_provenance.json is a
    # symlink — refused (GP2).
    with tempfile.TemporaryDirectory(prefix="op-helper-GP-S-") as raw_td:
        td = Path(raw_td)
        bundle = td / "bundle"
        bundle.mkdir()
        _write_synthetic_images(bundle / "images")
        # Place a real sidecar file outside the bundle, then symlink
        # <bundle>/generated_provenance.json at it. The symlink is
        # what the helper sees first.
        real_sidecar = td / "real_sidecar.json"
        real_sidecar.write_text(
            json.dumps(_make_sidecar_body((
                "alpha_marker.png", "beta_marker.jpg",
            ))) + "\n",
            encoding="utf-8",
        )
        os.symlink(real_sidecar, bundle / "generated_provenance.json")
        out_dir = td / "out"
        rc = main([
            "--bundle", str(bundle), "--out-dir", str(out_dir),
        ])
        ok = rc == 2 and not out_dir.exists()
        results.append(_ProbeResult(
            "GP-SYMLINK symlinked <bundle>/generated_provenance.json "
            "is refused (GP2) with rc 2 and no --out-dir artifact "
            "materialised",
            ok,
            f"rc={rc}, out_dir_exists={out_dir.exists()}",
        ))

    # T70 — committed-tree snapshot. The whole self-test must not have
    # mutated any byte under REPO_ROOT/scripts/ or REPO_ROOT/examples/.
    # Kept as the LAST probe so every manifest scenario above runs
    # against the same pre-snapshot baseline.
    snapshot_rc = _check_repo_unchanged(
        examples_before=examples_before,
        scripts_before=scripts_before,
    )
    results.append(_ProbeResult(
        "T70 snapshot: REPO_ROOT/scripts/ + REPO_ROOT/examples/ "
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
            "inspect_pptx_inventory, validate_visual_quality) once, and "
            "writes a compact summary + per-image provenance record + a "
            "visual_quality.json report alongside the produced editable "
            "PPTX. Local-only — does NOT call D-One, MCP, "
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
            "pre-existing directory. On a truth-checked happy run the "
            "helper writes deck.pptx, summary.json, inventory.json, "
            "visual_quality.json, workspace/, reports/, and a concise "
            "operator-facing README.md under this directory."
        ),
    )
    parser.add_argument(
        "--manifest", type=str, default=None,
        help=(
            "Optional caller-supplied local JSON file naming per-image "
            "slide intent (order, slide_title, alt_text, intended_use). "
            "When omitted, the helper preserves its deterministic "
            "filename-sort order and built-in default strings. When "
            "supplied, the file must be a regular non-symlink local "
            "file with no symlink ancestor (closed system aliases "
            "still allowed), must declare schema_version='1', and must "
            "cover every discovered image exactly once by basename in "
            "slide order. Each entry must carry exactly the four "
            "fields filename / slide_title / alt_text / intended_use; "
            "URL/URI/path-shaped strings, credentials, public "
            "upload/share/hosting wording, raw-source / confidential / "
            "customer markers, and positive success claims for the "
            "upstream services this lane does NOT call (D-One, MCP, "
            "Qoder, model API, image search, network, telemetry) are "
            "refused before any subprocess fires."
        ),
    )
    parser.add_argument(
        "--write-manifest-template", type=str, default=None,
        help=(
            "Manifest-template writer mode. When supplied, the helper "
            "discovers --images-dir using the same IG1..IG9 gates the "
            "normal mode applies, then writes a starter JSON manifest "
            "at the supplied PATH whose images[] array carries one "
            "entry per discovered image (sorted by filename) with the "
            "same default slide_title / alt_text / intended_use values "
            "the helper applies when --manifest is omitted. The "
            "template path must not be URI-shaped, a symlink, have a "
            "symlink ancestor, anchor under the repo, point at a "
            "missing or non-directory parent, or already exist. The "
            "template writer does NOT run the pipeline, does NOT "
            "produce a PPTX, does NOT produce a visual_quality.json "
            "report, and does NOT call any external service. "
            "Mutually exclusive with --out-dir / --manifest / "
            "--self-test / --plan-out."
        ),
    )
    parser.add_argument(
        "--plan-out", type=str, default=None,
        help=(
            "Plan-only preflight writer mode. When supplied, the "
            "helper discovers --images-dir using the same IG1..IG9 "
            "gates the normal mode applies (and validates the optional "
            "--manifest against MAN1..MAN12 when supplied), then writes "
            "a compact deterministic JSON plan to PATH whose images[] "
            "rows carry filename / asset_id / media_type / byte_count "
            "/ sha256 / intended 1-based slide index / slide_title / "
            "alt_text / intended_use in manifest-array order (when "
            "--manifest is supplied) or filename-sorted order "
            "otherwise. The plan path must not be URI-shaped, a "
            "symlink, have a symlink ancestor, anchor under the repo, "
            "point at a missing or non-directory parent, or already "
            "exist. Plan-only mode does NOT run the pipeline, does NOT "
            "produce a PPTX, does NOT produce a workspace, inventory, "
            "visual_quality, summary, or _pipeline_fixture artifact, "
            "and does NOT call any external service. Mutually "
            "exclusive with --out-dir / --write-manifest-template / "
            "--self-test; may combine with --images-dir (required) and "
            "optional --manifest."
        ),
    )
    parser.add_argument(
        "--approved-plan", type=str, default=None,
        help=(
            "Optional reviewer-approved run lock. When supplied, the "
            "helper builds the SAME in-memory plan --plan-out would "
            "have written for the current --images-dir (and --manifest, "
            "if supplied), loads the operator-supplied approved plan, "
            "and refuses the run with rc 2 BEFORE any pipeline "
            "subprocess fires or any out-dir artifact is created if "
            "the approved plan is malformed, carries a wrong "
            "schema_version / helper_id / mode, has boundary drift, or "
            "differs from current inputs on image_count, slide_count, "
            "manifest_path, image order, or any per-image filename / "
            "asset_id / media_type / byte_count / sha256 / "
            "intended_slide_index / slide_title / alt_text / "
            "intended_use. The path must be a regular local "
            "non-symlink file, not URI-shaped, with no symlink "
            "ancestor. On a clean match, normal operator mode proceeds "
            "exactly as it does without --approved-plan and writes "
            "deck.pptx, summary.json, inventory.json, visual_quality."
            "json, workspace/, reports/, and README.md under --out-dir. "
            "Mutually exclusive with --plan-out / "
            "--write-manifest-template / --self-test."
        ),
    )
    parser.add_argument(
        "--bundle", type=str, default=None,
        help=(
            "Operator-handoff folder shortcut. Resolves to "
            "--images-dir <bundle>/images and (when present) --manifest "
            "<bundle>/manifest.json, then delegates to the same image "
            "discovery + manifest + plan-only + approved-plan + out-dir "
            "+ summary + README + visual-quality + inventory + PPTX "
            "gates the explicit-flag flow runs. Required shape: "
            "<bundle>/images/ is a flat non-symlink directory of "
            "PNG / JPG / JPEG files; <bundle>/manifest.json is optional. "
            "The bundle path must not be URI-shaped, a symlink, have a "
            "symlink ancestor, be missing, or be a regular file. "
            "Mutually exclusive with --images-dir / --manifest / "
            "--write-manifest-template / --self-test."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run the in-script tempfixture scenarios (happy path + "
            "every documented fail-closed probe). Mutually exclusive "
            "with --images-dir / --out-dir / --manifest / "
            "--write-manifest-template / --plan-out / --approved-plan / "
            "--bundle."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if (
            args.images_dir is not None
            or args.out_dir is not None
            or args.manifest is not None
            or args.write_manifest_template is not None
            or args.plan_out is not None
            or args.approved_plan is not None
            or args.bundle is not None
        ):
            print(
                "FAIL: --self-test does not take --images-dir / "
                "--out-dir / --manifest / --write-manifest-template / "
                "--plan-out / --approved-plan / --bundle.",
                file=sys.stderr,
            )
            return 2
        return _run_self_tests()

    if args.bundle is not None:
        if args.images_dir is not None or args.manifest is not None:
            print(
                "FAIL: --bundle is a shortcut for --images-dir "
                "<bundle>/images and --manifest <bundle>/manifest.json; "
                "pass either --bundle DIR or the explicit "
                "--images-dir/--manifest pair, not both (mixed input "
                "styles are refused so the source of each path is "
                "unambiguous).",
                file=sys.stderr,
            )
            return 2
        if args.write_manifest_template is not None:
            print(
                "FAIL: --bundle does not take "
                "--write-manifest-template (the template writer expects "
                "an explicit --images-dir and writes a starter "
                "manifest, separate from the bundle handoff shape).",
                file=sys.stderr,
            )
            return 2
        (
            resolved_images_dir,
            resolved_manifest,
            resolved_sidecar,
            bundle_failures,
        ) = _validate_bundle_arg(args.bundle)
        if bundle_failures or resolved_images_dir is None:
            for line in bundle_failures or []:
                print(f"FAIL: {line}", file=sys.stderr)
            return 2
        # Substitute the resolved paths so the existing routing keeps
        # firing every downstream gate unchanged. The sidecar path
        # (when present) lands on a private attribute the bundle
        # routing carries into _run_operator_mode; there is no
        # explicit operator-typed flag for it — the sidecar is
        # bundle-only by design.
        args.images_dir = resolved_images_dir
        args.manifest = resolved_manifest
        args._generated_provenance_path = resolved_sidecar

    if args.write_manifest_template is not None:
        if args.images_dir is None:
            print(
                "FAIL: --write-manifest-template requires --images-dir.",
                file=sys.stderr,
            )
            return 2
        if (
            args.out_dir is not None
            or args.manifest is not None
            or args.plan_out is not None
            or args.approved_plan is not None
        ):
            print(
                "FAIL: --write-manifest-template does not take "
                "--out-dir / --manifest / --plan-out / --approved-plan "
                "(the template writer does not run the pipeline).",
                file=sys.stderr,
            )
            return 2
        return _run_template_write_mode(
            images_dir_str=args.images_dir,
            template_path_str=args.write_manifest_template,
        )

    if args.plan_out is not None:
        if args.images_dir is None:
            print(
                "FAIL: --plan-out requires --images-dir (or --bundle).",
                file=sys.stderr,
            )
            return 2
        if args.out_dir is not None:
            print(
                "FAIL: --plan-out does not take --out-dir (plan-only "
                "mode does not run the pipeline).",
                file=sys.stderr,
            )
            return 2
        if args.approved_plan is not None:
            print(
                "FAIL: --plan-out does not take --approved-plan "
                "(--plan-out writes a plan; --approved-plan compares "
                "an existing plan against current inputs in normal "
                "operator mode).",
                file=sys.stderr,
            )
            return 2
        return _run_plan_only_mode(
            images_dir_str=args.images_dir,
            plan_out_str=args.plan_out,
            manifest_path_str=args.manifest,
        )

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
            f"(use --self-test for the in-script scenarios, "
            f"--write-manifest-template PATH to write a starter "
            f"manifest without running the pipeline, --plan-out "
            f"PATH to write a preflight plan without running the "
            f"pipeline, or --bundle DIR as the operator-handoff "
            f"shortcut for --images-dir / --manifest).",
            file=sys.stderr,
        )
        return 2

    return _run_operator_mode(
        images_dir_str=args.images_dir,
        out_dir_str=args.out_dir,
        manifest_path_str=args.manifest,
        approved_plan_path_str=args.approved_plan,
        generated_provenance_path_str=getattr(
            args, "_generated_provenance_path", None,
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
