#!/usr/bin/env python3
"""image_placement_readback_smoke.py

Tempdir-only, stdlib-only **slide-level image placement / readback
smoke** for the core image-to-editable-PPT loop. Drives the existing
mixed-lane mock pipeline once into a per-run tempdir, walks the
produced PPTX + report ``inventory.json`` + workspace ``render_models``
+ runner sidecar to assemble a placement-readback object, asserts
slide-level placement truth (each image lane lands on its intended
slide AND the PPTX picture xfrm matches the render_model image_slot
bounds within a 1-pixel EMU tolerance), and refuses every documented
regression class via direct fail-closed probes on the readback.

Where ``core_image_to_editable_ppt_demo.py`` proves the embed surface
(two slides, >= 2 media parts, editable text evidence, sanitized
provenance), this smoke is the **next milestone** — proves the
embedded bytes are not only present but attached to the intended
slide/slot while every editability gate the demo pins still holds.

Aligned only with upstream ppt-master image-lane ideas: image assets
+ hero_page overlay reservation + per-row ``text_policy`` +
generated-image provenance. No upstream code / prompts / examples /
assets / wording copied — implementation, readback shape, probe
matrix are this repo's own.

The smoke does NOT introduce a new schema, a new validator, or a new
runtime contract. It reuses the existing helpers verbatim:

  * ``scripts/mixed_image_asset_pipeline_smoke.py`` — synthetic
    mixed-lane bundle materializer + runner-args helper +
    per-lane id / local_path / slide-title constants;
  * ``scripts/mixed_image_asset_provenance_handoff_smoke.py`` —
    taxonomy-rich ``d_one_spec`` body + descriptor vocabulary body
    + canonical hero_page placement_role / text_policy /
    subject_domain / custom_descriptor constants;
  * ``scripts/inspect_pptx_inventory.py`` — produced PPTX -> JSON
    inventory readback (slide rows + media_parts + relationships +
    findings) invoked as a subprocess on the per-run output;
  * ``scripts/validate_pptx_contract.py`` — minimal-evidence +
    relationships gates against the produced PPTX
    (``--expected-slide-count 2``);
  * ``scripts/core_editable_ppt_acceptance.py`` —
    ``_snapshot_committed_tree`` (no-repo-mutation gate, same broad
    surface the aggregate quality gate already protects).

Happy path (one mock pipeline subprocess; one contract validator
subprocess; one inventory subprocess; in-process render_model +
slide XML walks):

  H1   the bundle materializer + runner-args helper drive a
       pipeline subprocess that returns rc=0 with a taxonomy-rich
       ``d_one_spec`` carrying ``placement_role=hero_page`` +
       non-default ``text_policy`` + ``subject_domain`` + approved
       ``custom_descriptor`` and a paired
       ``descriptor_vocabulary.json``;
  H2   ``validate_pptx_contract --pptx <out> --expected-slide-count
       2`` returns rc=0 AND emits ``[PASS]`` for every
       ``minimal_evidence.*`` + ``relationships.{no_external,
       no_file_uri, allow_list}`` marker;
  H3   ``inspect_pptx_inventory --pptx <out>`` returns rc=0 with
       ``ok=true`` / ``findings=[]`` / ``slide_count=2``;
  H4   per-lane sha256 attribution proves the d_one_local
       workspace asset bytes land in EXACTLY one
       ``ppt/media/*.{png,jpg,jpeg}`` part referenced ONLY by
       slide 1 (the d_one cover) AND the local_asset workspace
       asset bytes land in EXACTLY one ``ppt/media/*`` part
       referenced ONLY by slide 2 (the local_asset cover);
  H4b  each lane's intended slide's first ``<p:pic>`` blip
       embed ``r:embed="rIdN"`` resolves through the slide's
       ``_rels/slideN.xml.rels`` file to EXACTLY the lane's
       expected media part. Closes the "rel declared but blip
       embeds something else" gap: per-part
       ``referencing_slides`` only says the slide owns A rel to
       the part, not that the slide's body shows the part —
       a regression that planted an extra rel on the slide
       while the blip embedded a different part would have
       passed H4 silently. The blip-embed walk is what proves
       the picture body actually shows the lane;
  H5   every produced media part lives under ``ppt/media/`` (no
       external relationship; no ``file://`` / ``data:`` / URI-
       scheme target; no orphan part; no part referenced by
       zero slides);
  H6   every slide carries native editable text / shape evidence
       (``image_only_evidence == False`` for both slides; both
       have ``text_run_count > 0`` AND
       ``native_object_counts.shapes_sp > 0``) — the deck is NOT
       a full-slide raster fallback;
  H7   the workspace ``render_models/01_cover.json`` +
       ``render_models/02_cover.json`` each carry exactly one
       ``image_slot`` primitive whose ``bounds`` (in canvas
       pixels) map via ``EMU_PER_PX = 9525`` to the matching
       slide's ``<p:pic>`` ``<a:off>`` + ``<a:ext>`` values
       within a 1-pixel EMU tolerance (``EMU_PER_PX`` either side);
  H8   the runner-written sidecar ``mock_d_one_adapter_plan.json``
       has the d_one_local request carrying the spec-supplied
       ``placement_role`` / ``text_policy`` / ``subject_domain``
       / ``custom_descriptor`` byte-for-byte AND the local_asset
       id MUST NOT appear in the sidecar's requests[] (caller-
       staged bytes are not a generated artifact);
  H9   the assembled readback passes the in-script truth-checker
       (every documented field carries the documented value)
       AND echoes verbatim to stdout;
  H10  committed tree under REPO_ROOT is byte-identical before
       and after the run.

Fail-closed probes (direct, no pipeline re-run — every probe takes
a clone of the happy-path baseline, mutates one field, asserts the
truth-checker refuses):

  P1   missing d_one_local media reference: drop the media-part
       row whose sha256 equals the d_one_local workspace sha — the
       truth-checker refuses (the d_one lane is no longer
       referenced anywhere in the deck);
  P2   missing local_asset media reference: symmetric to P1 — drop
       the matching media-part row and assert refusal;
  P3   swapped slide references: swap the ``referencing_slides``
       lists between the d_one_local row and the local_asset row
       so the d_one lane lands on slide 2 instead of slide 1 —
       the truth-checker refuses (per-lane intended-slide
       attribution is broken);
  P4   orphan embedded media: inject a synthetic
       ``ppt/media/orphan.png`` media-part row whose
       ``referencing_slides == []`` AND no slide row references
       it — the truth-checker refuses (every embedded part must
       carry at least one referencing slide);
  P5   external relationship: append a synthetic
       ``TargetMode=External`` relationship to the relationships
       list — the truth-checker refuses;
  P5b  ``file://`` relationship: append a synthetic relationship
       whose Target starts with ``file://`` — the truth-checker
       refuses;
  P5c  ``data:`` relationship: append a synthetic relationship
       whose Target carries a ``data:`` URI scheme prefix — the
       truth-checker refuses;
  P6   full-slide / all-image slide evidence: flip
       ``slides[0].image_only_evidence`` to True (or zero out the
       slide's text_run_count + shapes_sp) — the truth-checker
       refuses (full-slide raster fallback is fail-closed by the
       milestone);
  P7   positive real-D-One / MCP / public network / model API /
       image search / Qoder success claim in ``notes.scope`` or
       ``real_d_one_status`` — the truth-checker refuses (the
       committed-safe UNVERIFIED sentence is the only allowed
       shape);
  P8   d_one_local generated_intent stripped: drop the d_one_local
       row's ``generated_intent`` block — the truth-checker
       refuses (every d_one_local lane must carry per-row
       taxonomy projection);
  P9   local_asset attached to generated_intent: attach a
       ``generated_intent`` block to the local_asset row — the
       truth-checker refuses (caller-staged bytes are not a
       generated artifact);
  P10  bounds drift: shift the slide-1 picture xfrm offset by 10
       EMU (an order of magnitude above the 1-px tolerance) —
       the truth-checker refuses; symmetric P10b for the size
       (``<a:ext>``) drifted by 10 EMU;
  P11  slide ``<p:pic>`` blip embed cross-swap: rewrite
       ``lanes.d_one_local.intended_slide_blip_embed_part`` to
       the local_asset's media part AND symmetric for
       local_asset — the truth-checker refuses (the per-part
       ``referencing_slides`` field is untouched, so the
       refusal is load-bearing: it proves the new gate, not
       a pre-existing gate, fires);
  P11b slide ``<p:pic>`` blip embed unresolved: rewrite
       ``intended_slide_blip_embed_part`` to ``None`` so the
       truth-checker sees a slide whose blip rId did not
       resolve to any media part in the slide's rels file —
       refused.

The bounds readback (H7 + P10 / P10b) is the next milestone after
``core_image_to_editable_ppt_demo``: an image is not enough — the
image must land at the intended ``image_slot`` bounds, otherwise
the editable PPTX is wrong even though every legacy gate passed.
Today the render_model carries deterministic pixel bounds from the
template ``cover.json`` and the exporter converts via
``EMU_PER_PX = 9525``; the smoke walks both sides and the tolerance
is 1 px so a per-px round-trip is exact.

Clean-room: this smoke shares no prompts, assets, examples, tables,
CSV rows, wording, code, or deck structure with any upstream
project. Aligned only with upstream image-lane ideas (image assets,
hero_page overlay reservation, per-row text_policy, provenance);
the implementation, readback shape, probe matrix, and refusal walker
are this repo's own.

MOCK / STUB ONLY — NOT real D-One integration. Nothing in this
smoke calls D-One, MCP, Qoder, a public network, telemetry, any
model API, an image search, a browser, a screenshot service, or any
external service. The asset bytes are the same minimal magic-byte-
valid local payloads the existing pipeline smokes already use. The
readback record is local audit evidence about that synthetic mock
chain, not a claim that any external service ran or succeeded.

Usage:
  python3 scripts/image_placement_readback_smoke.py --self-test

Stdlib only. NETWORK-FREE. NO real D-One. NO MCP. NO Qoder. NO model
API. NO image search. NO telemetry. NOT a full prompt /
report / Markdown-to-PPTX automation — the smoke composes the
existing mock chain through the existing pipeline smoke's
materializer and proves the image-to-editable-PPT loop attaches
each generated/staged image to its intended slide and slot.
"""
from __future__ import annotations

import sys

# Refuse to write `.pyc` files for any module imported by this script.
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
from xml.etree import ElementTree as ET  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

# Reuse the synthetic bundle / runner-args / per-lane id constants
# from the existing mixed-lane smoke. Sharing the same materializer
# means a future change to the bundle shape is exercised by THIS
# smoke too.
from mixed_image_asset_pipeline_smoke import (  # noqa: E402
    D_ONE_IMAGE_ID,
    D_ONE_LOCAL_PATH,
    LOCAL_ASSET_IMAGE_ID,
    LOCAL_ASSET_LOCAL_PATH,
    SIDECAR_FILENAME,
    _materialize_bundle,
    _runner_args,
)
from mixed_image_asset_provenance_handoff_smoke import (  # noqa: E402
    _D_ONE_CUSTOM_DESCRIPTOR,
    _D_ONE_PLACEMENT_ROLE,
    _D_ONE_SUBJECT_DOMAIN,
    _D_ONE_TEXT_POLICY,
    _descriptor_vocab_body,
    _taxonomy_d_one_spec_body,
)
from core_editable_ppt_acceptance import (  # noqa: E402
    _snapshot_committed_tree,
)

VALIDATE_PPTX_CONTRACT = SCRIPTS_DIR / "validate_pptx_contract.py"
INSPECT_PPTX_INVENTORY = SCRIPTS_DIR / "inspect_pptx_inventory.py"

# Must match scripts/export_pptx.py::EMU_PER_PX verbatim. A drift here
# would silently invalidate the bounds-readback comparison; if the
# exporter ever moves off 9525 EMU/px the smoke must move with it
# (this is a hard-coded constant in both files today).
EMU_PER_PX = 9525

# 1-pixel EMU tolerance for the bounds-readback comparison. The
# exporter's px -> EMU mapping is pure integer arithmetic
# (px * 9525), so the round-trip is bit-exact today. We accept ±1 px
# to leave one pixel of slack for any future rounding the exporter
# might introduce; anything beyond that is a real drift.
BOUNDS_TOLERANCE_EMU = EMU_PER_PX

# PPTX namespaces the slide-XML walker needs to read <p:pic> + xfrm.
_NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
# Package-relationships ns is what the `_rels/*.rels` parts use on
# their root `<Relationships>` + `<Relationship>` elements.
_NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
# Office-document relationships ns is the `r:` namespace used INSIDE
# slide XML for `<a:blip r:embed="rIdN"/>` attributes (different
# namespace than the package-rels one — easy to confuse but they are
# distinct in the OOXML spec).
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# Same UNVERIFIED sentence shape the committed-safe demo pins.
_REAL_D_ONE_STATUS = "UNVERIFIED"

_READBACK_SCOPE_NOTE = (
    "Slide-level image placement / readback smoke. Drives the "
    "synthetic mixed-lane mock bundle (d_one_local + local_asset, "
    "two cover slides) through the local pipeline once into a "
    "tempdir, walks the produced PPTX + inventory + workspace "
    "render_models + sidecar, and proves each image lane lands on "
    "its intended slide AND inside the intended image_slot bounds. "
    "NOT real D-One, NOT MCP, NOT Qoder, NOT a public-network run, "
    "NOT telemetry, NOT a prompt or report to PPTX automation."
)
_READBACK_EMBED_SURFACE_NOTE = (
    "PNG, JPG, and JPEG inside the ppt/media slot of the produced "
    "deck. The subset scripts/export_pptx.py supports today; "
    "anything outside that subset is fail-closed by the exporter."
)

# Word-boundary refusal walker for positive real-D-One success
# claims anywhere in a summary text field. Mirrors the demo's
# walker shape so the canonical UNVERIFIED sentence still passes.
_REAL_D_ONE_CLAIM_VERBS: tuple[str, ...] = (
    "verified", "succeeded", "successful", "ran successfully",
    "ran live", "called successfully", "returned successfully",
    "online", "live",
)
_REAL_D_ONE_CLAIM_NOUNS: tuple[str, ...] = (
    "real d-one", "real d_one", "d-one online", "d_one online",
    "mcp", "model api", "image search", "qoder", "public network",
)
_NEGATION_WINDOW = 15
_NEGATION_TOKENS: tuple[str, ...] = (
    "no ", "not ", "never ", "without ", "is not ", "are not ",
    "was not ", "were not ", "do not ", "does not ", "did not ",
    "unverified",
)

_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Embed surface the exporter supports today.
_EMBEDDABLE_MEDIA_EXTS: tuple[str, ...] = (".png", ".jpg", ".jpeg")


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


def _run_pipeline(
    *, bundle_dir: Path, workspace: Path, output: Path, report_dir: Path,
) -> _ToolOutcome:
    cmd = _runner_args(
        bundle_dir=bundle_dir, workspace=workspace,
        output=output, report_dir=report_dir,
    )
    return _run("run_mock_image_pipeline --bundle", cmd)


def _run_contract_validator(
    *, pptx: Path, expected_slide_count: int,
) -> _ToolOutcome:
    return _run(
        "validate_pptx_contract",
        [
            sys.executable, str(VALIDATE_PPTX_CONTRACT),
            "--pptx", str(pptx),
            "--expected-slide-count", str(expected_slide_count),
        ],
    )


def _run_inventory(*, pptx: Path, out: Path) -> _ToolOutcome:
    return _run(
        "inspect_pptx_inventory",
        [
            sys.executable, str(INSPECT_PPTX_INVENTORY),
            "--pptx", str(pptx), "--out", str(out),
        ],
    )


# ---------------------------------------------------------------------------
# Filesystem helpers.
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Slide XML walker — extract <p:pic> xfrm off/ext per slide.
# ---------------------------------------------------------------------------


def _slide_pic_xfrms(pptx: Path) -> tuple[dict[int, list[dict]], list[str]]:
    """Open ``pptx`` as a ZIP, walk every ``ppt/slides/slideN.xml`` part,
    and extract each ``<p:pic>`` block's ``<a:off x= y=>`` +
    ``<a:ext cx= cy=>`` integers. Returns ``({slide_idx: [pics]}, errors)``
    where each pic dict carries ``{"off_x", "off_y", "ext_cx", "ext_cy",
    "name", "embed_rid"}`` for the picture's xfrm and its blip embed
    relationship Id.

    The xfrm extraction is deliberately conservative: it walks the
    direct children of each ``<p:pic>/<p:spPr>`` and reads the
    ``<a:xfrm>`` block's ``<a:off>`` + ``<a:ext>`` attributes. Anything
    that fails to parse as an integer is dropped from the dict and
    reported in the errors list — the truth-checker requires a
    non-empty dict per slide so a silently-skipped pic still fails
    closed at the readback layer."""
    errors: list[str] = []
    out: dict[int, list[dict]] = {}
    try:
        zf = zipfile.ZipFile(pptx, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        errors.append(
            f"cannot open {pptx} as ZIP: {type(exc).__name__}: {exc}"
        )
        return out, errors
    try:
        for n in zf.namelist():
            m = re.match(r"^ppt/slides/slide(\d+)\.xml$", n)
            if not m:
                continue
            idx = int(m.group(1))
            try:
                payload = zf.read(n)
            except (KeyError, OSError) as exc:
                errors.append(
                    f"cannot read {n}: {type(exc).__name__}: {exc}"
                )
                continue
            try:
                root = ET.fromstring(payload)
            except ET.ParseError as exc:
                errors.append(
                    f"cannot parse {n}: {type(exc).__name__}: {exc}"
                )
                continue
            pics: list[dict] = []
            for pic in root.iter(f"{{{_NS_P}}}pic"):
                name = ""
                nv_pr = pic.find(f"{{{_NS_P}}}nvPicPr")
                if nv_pr is not None:
                    c_nv = nv_pr.find(f"{{{_NS_P}}}cNvPr")
                    if c_nv is not None:
                        name = c_nv.attrib.get("name", "") or ""
                embed_rid = ""
                blip_fill = pic.find(f"{{{_NS_P}}}blipFill")
                if blip_fill is not None:
                    blip = blip_fill.find(f"{{{_NS_A}}}blip")
                    if blip is not None:
                        embed_rid = blip.attrib.get(
                            f"{{{_NS_R}}}embed", "",
                        ) or ""
                sp_pr = pic.find(f"{{{_NS_P}}}spPr")
                if sp_pr is None:
                    continue
                xfrm = sp_pr.find(f"{{{_NS_A}}}xfrm")
                if xfrm is None:
                    continue
                off = xfrm.find(f"{{{_NS_A}}}off")
                ext = xfrm.find(f"{{{_NS_A}}}ext")
                if off is None or ext is None:
                    continue
                try:
                    off_x = int(off.attrib.get("x", "0"))
                    off_y = int(off.attrib.get("y", "0"))
                    ext_cx = int(ext.attrib.get("cx", "0"))
                    ext_cy = int(ext.attrib.get("cy", "0"))
                except (TypeError, ValueError) as exc:
                    errors.append(
                        f"cannot parse xfrm ints on slide {idx}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    continue
                pics.append({
                    "name": name,
                    "embed_rid": embed_rid,
                    "off_x": off_x, "off_y": off_y,
                    "ext_cx": ext_cx, "ext_cy": ext_cy,
                })
            if pics:
                out[idx] = pics
    finally:
        zf.close()
    return out, errors


def _slide_rels_resolution(
    pptx: Path,
) -> tuple[dict[int, dict[str, str]], list[str]]:
    """Open ``pptx`` as a ZIP, walk every
    ``ppt/slides/_rels/slideN.xml.rels`` part, and return
    ``{slide_idx: {r_id: resolved_part_name}}``.

    ``resolved_part_name`` is the rel target normalized to its package-
    relative path (``ppt/media/imageN.png``). The smoke uses this map
    to cross-check that the ``<p:pic>`` blip's ``r:embed="rIdN"`` on
    each slide actually points at the lane's expected media part —
    without this hop, a slide that merely DECLARES a rel to the lane's
    part (but whose blip embeds a different rel) would still pass the
    media-part ``referencing_slides`` gate (the inventory's per-part
    referencing-slides set includes every slide that owns the rels
    file, not just the slides whose blip embeds the target). So this
    walker is what closes the "rel declared but blip embeds something
    else" gap.

    A rel whose Target carries a URI scheme prefix, a leading ``/``,
    or ``..`` traversal that escapes the package is dropped from the
    map (the contract validator's relationships gates fail closed on
    them separately; here we just refuse to translate them into a
    resolved part so the truth-checker's "blip must embed lane part"
    gate fails closed too)."""
    errors: list[str] = []
    out: dict[int, dict[str, str]] = {}
    try:
        zf = zipfile.ZipFile(pptx, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        errors.append(
            f"cannot open {pptx} as ZIP for slide rels walk: "
            f"{type(exc).__name__}: {exc}"
        )
        return out, errors
    try:
        for n in zf.namelist():
            m = re.match(
                r"^ppt/slides/_rels/slide(\d+)\.xml\.rels$", n,
            )
            if not m:
                continue
            idx = int(m.group(1))
            try:
                payload = zf.read(n)
            except (KeyError, OSError) as exc:
                errors.append(
                    f"cannot read {n}: {type(exc).__name__}: {exc}"
                )
                continue
            try:
                root = ET.fromstring(payload)
            except ET.ParseError as exc:
                errors.append(
                    f"cannot parse {n}: {type(exc).__name__}: {exc}"
                )
                continue
            rid_to_part: dict[str, str] = {}
            for rel in root:
                if rel.tag != f"{{{_NS_REL}}}Relationship":
                    continue
                rid = rel.attrib.get("Id", "") or ""
                target = rel.attrib.get("Target", "") or ""
                if not rid or not target:
                    continue
                # Refuse to translate anything that does not look like
                # a package-internal relative target; the truth-checker
                # then sees the missing translation and fails closed.
                if _URI_SCHEME_PREFIX.match(target):
                    continue
                if target.startswith("/"):
                    continue
                # Resolve relative target against the owner-dir
                # ppt/slides/ — strip leading "../" segments and
                # collapse onto the package root. Any "../" past the
                # package root is dropped (the rel target escaped the
                # package; we refuse to translate it).
                segs = target.replace("\\", "/").split("/")
                base = ["ppt", "slides"]
                escaped = False
                for seg in segs:
                    if seg == "" or seg == ".":
                        continue
                    if seg == "..":
                        if base:
                            base.pop()
                        else:
                            escaped = True
                            break
                    else:
                        base.append(seg)
                if escaped or not base:
                    continue
                rid_to_part[rid] = "/".join(base)
            out[idx] = rid_to_part
    finally:
        zf.close()
    return out, errors


# ---------------------------------------------------------------------------
# Render-model walker — extract per-slide image_slot bounds.
# ---------------------------------------------------------------------------


def _render_model_image_slot_bounds(
    workspace: Path,
) -> tuple[dict[int, dict], list[str]]:
    """Walk ``<workspace>/render_models/*.json`` and return
    ``{slide_idx: bounds_dict}`` for every render_model that carries
    exactly one ``image_slot`` primitive. ``bounds_dict`` is the
    ``{x, y, w, h}`` dict in canvas pixels — the exporter converts via
    ``EMU_PER_PX`` so the slide pic xfrm is ``(px * EMU_PER_PX)`` for
    each axis."""
    errors: list[str] = []
    out: dict[int, dict] = {}
    rm_dir = workspace / "render_models"
    if not rm_dir.is_dir():
        errors.append(f"render_models dir not found at {rm_dir}")
        return out, errors
    for entry in sorted(rm_dir.iterdir()):
        if not entry.is_file() or entry.suffix != ".json":
            continue
        try:
            body = json.loads(entry.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(
                f"cannot parse {entry}: {type(exc).__name__}: {exc}"
            )
            continue
        idx = body.get("index")
        primitives = body.get("primitives") or []
        if not isinstance(idx, int) or not isinstance(primitives, list):
            errors.append(
                f"{entry} missing index / primitives shape"
            )
            continue
        image_slots = [
            p for p in primitives
            if isinstance(p, dict) and p.get("kind") == "image_slot"
        ]
        if len(image_slots) != 1:
            # Slides without an image_slot are skipped — the truth-
            # checker requires bounds rows for the two slides the
            # bundle authored an accent image_ref on.
            continue
        bounds = image_slots[0].get("bounds")
        if not isinstance(bounds, dict):
            errors.append(
                f"{entry} image_slot primitive missing bounds dict"
            )
            continue
        for axis in ("x", "y", "w", "h"):
            if not isinstance(bounds.get(axis), int):
                errors.append(
                    f"{entry} image_slot bounds.{axis} is not int "
                    f"({bounds.get(axis)!r})"
                )
                break
        else:
            out[idx] = {a: bounds[a] for a in ("x", "y", "w", "h")}
    return out, errors


# ---------------------------------------------------------------------------
# Sidecar walker — extract per-id taxonomy projection.
# ---------------------------------------------------------------------------


def _sidecar_taxonomy(report_dir: Path) -> tuple[dict, dict, list[str]]:
    """Read the runner-written ``mock_d_one_adapter_plan.json`` sidecar
    and project each request to its taxonomy dict. Returns
    ``(per_id_taxonomy, request_id_set, errors)``."""
    errors: list[str] = []
    sidecar_path = report_dir / SIDECAR_FILENAME
    if not sidecar_path.is_file() or sidecar_path.is_symlink():
        errors.append(
            f"sidecar not found / symlinked at {sidecar_path}"
        )
        return {}, {}, errors
    try:
        body = json.loads(sidecar_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(
            f"cannot parse sidecar at {sidecar_path}: "
            f"{type(exc).__name__}: {exc}"
        )
        return {}, {}, errors
    requests = body.get("requests") or []
    by_id: dict[str, dict] = {}
    ids: set[str] = set()
    for r in requests:
        if not isinstance(r, dict):
            continue
        rid = r.get("id")
        if not isinstance(rid, str) or not rid:
            continue
        ids.add(rid)
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
        by_id[rid] = entry
    return by_id, {"ids": sorted(ids)}, errors


# ---------------------------------------------------------------------------
# Readback assembly.
# ---------------------------------------------------------------------------


@dataclass
class _ReadbackContext:
    pptx_path: Path
    workspace: Path
    report_dir: Path
    inventory: dict
    inventory_outcome: _ToolOutcome
    contract: _ToolOutcome
    d_one_sha: str
    local_asset_sha: str
    slide_pics: dict[int, list[dict]]
    slide_rels: dict[int, dict[str, str]]
    bounds_by_slide: dict[int, dict]
    taxonomy_by_id: dict
    sidecar_ids: dict


def _build_readback(ctx: _ReadbackContext) -> dict:
    """Compose the placement-readback dict from inventory + slide-XML
    walk + render_models + sidecar. No new contract — every field is a
    projection of an existing artifact."""
    inv = ctx.inventory
    media_parts = inv.get("media_parts") or []
    relationships = inv.get("relationships") or []
    slides = inv.get("slides") or []

    # Per-lane media-part attribution by sha256 equality.
    d_one_part: dict = {}
    local_asset_part: dict = {}
    for entry in media_parts:
        if not isinstance(entry, dict):
            continue
        sha = entry.get("sha256")
        if sha == ctx.d_one_sha:
            d_one_part = entry
        elif sha == ctx.local_asset_sha:
            local_asset_part = entry

    # Per-slide native-shape evidence row (mirror inspect_pptx_inventory
    # output — image_only_evidence comes from there directly).
    slide_rows: list[dict] = []
    for s in slides:
        if not isinstance(s, dict):
            continue
        counts = s.get("native_object_counts") or {}
        slide_rows.append({
            "index": s.get("index"),
            "image_only_evidence": s.get("image_only_evidence"),
            "text_run_count": s.get("text_run_count"),
            "shapes_sp": counts.get("shapes_sp"),
            "pictures_pic": counts.get("pictures_pic"),
            "media_refs": [
                {
                    "r_id": r.get("r_id"),
                    "resolved": r.get("resolved"),
                    "used_by_slide_blip": r.get("used_by_slide_blip"),
                }
                for r in (s.get("media_refs") or [])
                if isinstance(r, dict)
            ],
        })
    slide_rows.sort(key=lambda r: r.get("index") or 0)

    # Resolve each slide's first <p:pic> blip embed rid against the
    # per-slide rels map. This is what closes the "rel declared but
    # blip embeds something else" gap: a slide that owns a rel to a
    # media part isn't proof the slide's body actually shows it. The
    # blip embed is.
    def _resolve_blip_embed(slide_idx: int) -> tuple[str, str | None]:
        pics = ctx.slide_pics.get(slide_idx) or []
        if not pics:
            return "", None
        rid = pics[0].get("embed_rid")
        if not isinstance(rid, str) or not rid:
            return "", None
        return rid, (ctx.slide_rels.get(slide_idx) or {}).get(rid)

    # Bounds comparison per intended slide (slide 1 = d_one; slide 2 =
    # local_asset). The picture xfrm is the first <p:pic> on the slide;
    # by construction both cover slides carry EXACTLY one image_slot.
    bounds_rows: list[dict] = []
    for slide_idx in sorted(ctx.bounds_by_slide):
        bounds = ctx.bounds_by_slide[slide_idx]
        pics = ctx.slide_pics.get(slide_idx) or []
        first_pic = pics[0] if pics else {}
        embed_rid, embed_part = _resolve_blip_embed(slide_idx)
        bounds_rows.append({
            "slide_index": slide_idx,
            "render_model_bounds_px": dict(bounds),
            "expected_emu": {
                "off_x": bounds["x"] * EMU_PER_PX,
                "off_y": bounds["y"] * EMU_PER_PX,
                "ext_cx": bounds["w"] * EMU_PER_PX,
                "ext_cy": bounds["h"] * EMU_PER_PX,
            },
            "actual_emu": {
                "off_x": first_pic.get("off_x"),
                "off_y": first_pic.get("off_y"),
                "ext_cx": first_pic.get("ext_cx"),
                "ext_cy": first_pic.get("ext_cy"),
            },
            "pic_count": len(pics),
            "pic_name": first_pic.get("name"),
            "embed_rid": embed_rid,
            "slide_blip_embed_part": embed_part,
        })

    return {
        "smoke_id": "image_placement_readback_smoke",
        "schema_version": "1",
        "real_d_one_status": _REAL_D_ONE_STATUS,
        "pptx_path": str(ctx.pptx_path),
        "report_dir": str(ctx.report_dir),
        "workspace": str(ctx.workspace),
        "slide_count": inv.get("slide_count"),
        "inventory": {
            "ok": inv.get("ok") is True,
            "findings_empty": (inv.get("findings") or []) == [],
            "evidence_basis": inv.get("evidence_basis"),
        },
        "validators": {
            "validate_pptx_contract": {"rc": ctx.contract.rc},
            "inspect_pptx_inventory": {"rc": ctx.inventory_outcome.rc},
        },
        "lanes": {
            "d_one_local": {
                "expected_sha256": ctx.d_one_sha,
                "media_part": d_one_part.get("part"),
                "media_sha256": d_one_part.get("sha256"),
                "referencing_slides": list(
                    d_one_part.get("referencing_slides") or [],
                ),
                "expected_referencing_slides": [1],
                "intended_slide": 1,
                "intended_slide_blip_embed_part": _resolve_blip_embed(1)[1],
                "generated_intent": (
                    ctx.taxonomy_by_id.get(D_ONE_IMAGE_ID) or {}
                ),
            },
            "local_asset": {
                "expected_sha256": ctx.local_asset_sha,
                "media_part": local_asset_part.get("part"),
                "media_sha256": local_asset_part.get("sha256"),
                "referencing_slides": list(
                    local_asset_part.get("referencing_slides") or [],
                ),
                "expected_referencing_slides": [2],
                "intended_slide": 2,
                "intended_slide_blip_embed_part": _resolve_blip_embed(2)[1],
                "generated_intent": None,
            },
        },
        "media_parts": [
            {
                "part": e.get("part"),
                "sha256": e.get("sha256"),
                "extension": e.get("extension"),
                "referencing_slides": list(
                    e.get("referencing_slides") or [],
                ),
            }
            for e in media_parts
            if isinstance(e, dict)
        ],
        "relationships": [
            {
                "rels_part": r.get("rels_part"),
                "id": r.get("id"),
                "target": r.get("target"),
                "target_mode": r.get("target_mode"),
                "type": r.get("type"),
            }
            for r in relationships
            if isinstance(r, dict)
        ],
        "slides": slide_rows,
        "bounds_readback": bounds_rows,
        "sidecar_request_ids": sorted(ctx.sidecar_ids.get("ids") or []),
        "minimal_evidence": _project_contract_minimal_evidence(
            ctx.contract.stdout or "",
        ),
        "notes": {
            "scope": _READBACK_SCOPE_NOTE,
            "embed_surface": _READBACK_EMBED_SURFACE_NOTE,
            "bounds_readback_todo": (
                "Bounds tolerance is one px (EMU_PER_PX). Tightening "
                "to bit-exact equality is safe today because the "
                "exporter is pure integer arithmetic, but the smoke "
                "intentionally leaves one px of slack."
            ),
        },
    }


def _project_contract_minimal_evidence(stdout: str) -> dict[str, bool]:
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


# ---------------------------------------------------------------------------
# Truth checker — refuses every documented regression class.
# ---------------------------------------------------------------------------


def _scan_for_positive_real_d_one_claim(record: dict) -> list[str]:
    """Walk every string-valued field in ``record`` and refuse any
    positive real-D-One / MCP / public network / model API / image
    search / Qoder success claim. Returns offending field-paths;
    empty list means clean."""
    offenders: list[str] = []

    def _scan(value: object, label: str) -> None:
        if isinstance(value, str):
            lowered = value.lower()
            for noun in _REAL_D_ONE_CLAIM_NOUNS:
                idx = 0
                while True:
                    found = lowered.find(noun, idx)
                    if found == -1:
                        break
                    window = lowered[
                        max(0, found - _NEGATION_WINDOW):found
                    ]
                    if any(n in window for n in _NEGATION_TOKENS):
                        idx = found + len(noun)
                        continue
                    offenders.append(
                        f"{label}: positive noun {noun!r} at offset "
                        f"{found}"
                    )
                    idx = found + len(noun)
            for verb in _REAL_D_ONE_CLAIM_VERBS:
                idx = 0
                while True:
                    found = lowered.find(verb, idx)
                    if found == -1:
                        break
                    window = lowered[
                        max(0, found - _NEGATION_WINDOW):found
                    ]
                    if any(n in window for n in _NEGATION_TOKENS):
                        idx = found + len(verb)
                        continue
                    if "unverified" in lowered:
                        idx = found + len(verb)
                        continue
                    offenders.append(
                        f"{label}: positive verb {verb!r} at offset "
                        f"{found}"
                    )
                    idx = found + len(verb)
        elif isinstance(value, dict):
            for k, v in value.items():
                _scan(v, f"{label}.{k}" if label else str(k))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                _scan(v, f"{label}[{i}]")

    _scan(record, "readback")
    return offenders


def _bounds_within_tolerance(row: dict) -> list[str]:
    """Compare expected vs. actual EMU for one bounds row. Returns
    a list of diagnostics (empty list = within tolerance)."""
    failures: list[str] = []
    expected = row.get("expected_emu") or {}
    actual = row.get("actual_emu") or {}
    for axis in ("off_x", "off_y", "ext_cx", "ext_cy"):
        e = expected.get(axis)
        a = actual.get(axis)
        if not isinstance(e, int) or not isinstance(a, int):
            failures.append(
                f"bounds_readback[{row.get('slide_index')!r}].{axis}: "
                f"expected={e!r} actual={a!r} (both must be int)"
            )
            continue
        if abs(e - a) > BOUNDS_TOLERANCE_EMU:
            failures.append(
                f"bounds_readback[{row.get('slide_index')!r}].{axis}: "
                f"expected={e} actual={a} drift={abs(e - a)} "
                f"> tolerance={BOUNDS_TOLERANCE_EMU}"
            )
    return failures


def _check_readback_truth(record: dict) -> list[str]:
    """In-script truth-checker for the placement readback. Returns a
    list of failure diagnostics; empty list means the readback
    describes a healthy run."""
    failures: list[str] = []

    if record.get("smoke_id") != "image_placement_readback_smoke":
        failures.append(
            f"smoke_id={record.get('smoke_id')!r}; expected "
            f"'image_placement_readback_smoke'"
        )
    if record.get("schema_version") != "1":
        failures.append(
            f"schema_version={record.get('schema_version')!r}; "
            f"expected '1'"
        )
    if record.get("real_d_one_status") != _REAL_D_ONE_STATUS:
        failures.append(
            f"real_d_one_status={record.get('real_d_one_status')!r}; "
            f"expected {_REAL_D_ONE_STATUS!r}"
        )

    if record.get("slide_count") != 2:
        failures.append(
            f"slide_count={record.get('slide_count')!r}; expected 2"
        )

    inv = record.get("inventory") or {}
    if inv.get("ok") is not True:
        failures.append(
            f"inventory.ok={inv.get('ok')!r}; expected True"
        )
    if inv.get("findings_empty") is not True:
        failures.append(
            f"inventory.findings_empty={inv.get('findings_empty')!r}; "
            f"expected True"
        )

    val = record.get("validators") or {}
    for k in ("validate_pptx_contract", "inspect_pptx_inventory"):
        entry = val.get(k) or {}
        if entry.get("rc") != 0:
            failures.append(
                f"validators.{k}.rc={entry.get('rc')!r}; expected 0"
            )

    mev = record.get("minimal_evidence") or {}
    for gate in (
        "minimal_evidence.editable_text",
        "minimal_evidence.not_all_image_slide",
        "minimal_evidence.every_slide_has_native_shape",
        "minimal_evidence.no_blank_slide",
        "relationships.no_external",
        "relationships.no_file_uri",
        "relationships.allow_list",
    ):
        if mev.get(gate) is not True:
            failures.append(
                f"minimal_evidence.{gate}={mev.get(gate)!r}; "
                f"expected True"
            )

    lanes = record.get("lanes") or {}
    d_one = lanes.get("d_one_local") or {}
    local_asset = lanes.get("local_asset") or {}

    # Each lane must reference one and only one media part.
    for label, lane in (("d_one_local", d_one), ("local_asset", local_asset)):
        part = lane.get("media_part")
        sha = lane.get("media_sha256")
        expected_sha = lane.get("expected_sha256")
        if not isinstance(part, str) or not part.startswith("ppt/media/"):
            failures.append(
                f"lanes.{label}.media_part={part!r}; expected an "
                f"internal ppt/media/* part"
            )
        if sha != expected_sha:
            failures.append(
                f"lanes.{label}.media_sha256={sha!r}; expected "
                f"{expected_sha!r} (lane bytes must land byte-identical)"
            )
        refs = lane.get("referencing_slides") or []
        exp_refs = lane.get("expected_referencing_slides") or []
        if list(refs) != list(exp_refs):
            failures.append(
                f"lanes.{label}.referencing_slides={list(refs)!r}; "
                f"expected {list(exp_refs)!r} (image must land on "
                f"its intended slide)"
            )
        # The intended slide's <p:pic> blip embed must resolve to this
        # lane's media part — proves the slide BODY shows the lane,
        # not just that a rel exists on the slide. Without this, a
        # regression that planted an extra rel on the slide (the slide
        # then appears in the part's referencing_slides set) would
        # silently pass the previous gate even if the slide's actual
        # <p:pic> embedded a different part.
        intended = lane.get("intended_slide")
        embedded_part = lane.get("intended_slide_blip_embed_part")
        if intended != (exp_refs[0] if exp_refs else None):
            failures.append(
                f"lanes.{label}.intended_slide={intended!r}; expected "
                f"{exp_refs[0] if exp_refs else None!r} (the lane's "
                f"intended slide must match its expected referencing "
                f"slide)"
            )
        if not isinstance(embedded_part, str) or not embedded_part:
            failures.append(
                f"lanes.{label}.intended_slide_blip_embed_part="
                f"{embedded_part!r}; expected the slide's <p:pic> "
                f"blip embed to resolve to a non-empty ppt/media/* "
                f"part name"
            )
        elif embedded_part != part:
            failures.append(
                f"lanes.{label}.intended_slide_blip_embed_part="
                f"{embedded_part!r}; expected {part!r} (the lane's "
                f"intended slide's <p:pic> blip must embed the lane's "
                f"own media part, not merely declare a rel to it)"
            )

    # d_one_local lane must carry generated_intent with placement_role
    # AND text_policy (subject_domain optional but checked because the
    # canonical synthetic spec supplies it).
    gi = d_one.get("generated_intent") or {}
    for field in ("placement_role", "text_policy", "subject_domain"):
        if not isinstance(gi.get(field), str) or not gi.get(field):
            failures.append(
                f"lanes.d_one_local.generated_intent.{field}="
                f"{gi.get(field)!r}; expected non-empty string "
                f"(d_one_local lane must preserve per-row taxonomy)"
            )
    if gi.get("placement_role") != _D_ONE_PLACEMENT_ROLE:
        failures.append(
            f"lanes.d_one_local.generated_intent.placement_role="
            f"{gi.get('placement_role')!r}; expected "
            f"{_D_ONE_PLACEMENT_ROLE!r} (hero_page overlay reservation)"
        )
    if gi.get("text_policy") != _D_ONE_TEXT_POLICY:
        failures.append(
            f"lanes.d_one_local.generated_intent.text_policy="
            f"{gi.get('text_policy')!r}; expected "
            f"{_D_ONE_TEXT_POLICY!r}"
        )
    if gi.get("subject_domain") != _D_ONE_SUBJECT_DOMAIN:
        failures.append(
            f"lanes.d_one_local.generated_intent.subject_domain="
            f"{gi.get('subject_domain')!r}; expected "
            f"{_D_ONE_SUBJECT_DOMAIN!r}"
        )
    if gi.get("custom_descriptor") != _D_ONE_CUSTOM_DESCRIPTOR:
        failures.append(
            f"lanes.d_one_local.generated_intent.custom_descriptor="
            f"{gi.get('custom_descriptor')!r}; expected "
            f"{_D_ONE_CUSTOM_DESCRIPTOR!r}"
        )

    # local_asset lane must NOT carry generated_intent.
    if local_asset.get("generated_intent") is not None:
        failures.append(
            f"lanes.local_asset.generated_intent="
            f"{local_asset.get('generated_intent')!r}; expected null "
            f"(caller-staged bytes are not a generated artifact)"
        )

    # Sidecar request_ids must cover ONLY the d_one_local id.
    sidecar_ids = record.get("sidecar_request_ids") or []
    if sidecar_ids != [D_ONE_IMAGE_ID]:
        failures.append(
            f"sidecar_request_ids={sidecar_ids!r}; expected "
            f"[{D_ONE_IMAGE_ID!r}]"
        )

    # Every media-part row must live under ppt/media/ AND carry at
    # least one referencing slide (no orphan).
    seen_parts: set[str] = set()
    for entry in record.get("media_parts") or []:
        if not isinstance(entry, dict):
            failures.append(
                f"media_parts contains a non-dict entry: {entry!r}"
            )
            continue
        part = entry.get("part")
        if not isinstance(part, str) or not part.startswith("ppt/media/"):
            failures.append(
                f"media_parts entry part={part!r}; expected an "
                f"internal ppt/media/* part"
            )
            continue
        ext = entry.get("extension")
        if (
            not isinstance(ext, str)
            or "." + ext.lower() not in _EMBEDDABLE_MEDIA_EXTS
        ):
            failures.append(
                f"media_parts entry {part!r} extension={ext!r}; "
                f"expected one of "
                f"{sorted(_EMBEDDABLE_MEDIA_EXTS)!r}"
            )
        refs = entry.get("referencing_slides") or []
        if not isinstance(refs, list) or not refs:
            failures.append(
                f"media_parts entry {part!r} referencing_slides="
                f"{refs!r}; expected a non-empty list (no orphan "
                f"embedded media)"
            )
        seen_parts.add(part)

    # Every relationship must be internal (no External / file:// /
    # URI-scheme target).
    for rel in record.get("relationships") or []:
        if not isinstance(rel, dict):
            failures.append(
                f"relationships contains a non-dict entry: {rel!r}"
            )
            continue
        tm = rel.get("target_mode")
        tg = rel.get("target")
        if isinstance(tm, str) and tm.lower() == "external":
            failures.append(
                f"relationships entry {rel.get('id')!r} target_mode="
                f"{tm!r}; expected Internal"
            )
            continue
        if isinstance(tg, str) and tg.lower().startswith("file://"):
            failures.append(
                f"relationships entry {rel.get('id')!r} target="
                f"{tg!r}; file:// URI is fail-closed"
            )
            continue
        if (
            isinstance(tg, str)
            and _URI_SCHEME_PREFIX.match(tg)
        ):
            failures.append(
                f"relationships entry {rel.get('id')!r} target="
                f"{tg!r}; carries a URI scheme prefix"
            )

    # Every slide row must carry native editable text + shape AND
    # NOT be a full-slide raster fallback (image_only_evidence).
    slides_seen = 0
    for srow in record.get("slides") or []:
        if not isinstance(srow, dict):
            failures.append(
                f"slides contains a non-dict entry: {srow!r}"
            )
            continue
        slides_seen += 1
        idx = srow.get("index")
        if srow.get("image_only_evidence") is True:
            failures.append(
                f"slides[{idx!r}].image_only_evidence=True; "
                f"full-slide raster fallback is fail-closed by the "
                f"milestone"
            )
        trc = srow.get("text_run_count")
        if not isinstance(trc, int) or trc <= 0:
            failures.append(
                f"slides[{idx!r}].text_run_count={trc!r}; expected "
                f"positive int (deck must carry native editable text)"
            )
        sp = srow.get("shapes_sp")
        if not isinstance(sp, int) or sp <= 0:
            failures.append(
                f"slides[{idx!r}].shapes_sp={sp!r}; expected "
                f"positive int (deck must carry native editable shapes)"
            )
    if slides_seen != 2:
        failures.append(
            f"slides count={slides_seen}; expected exactly 2 slide rows"
        )

    # Bounds readback: every bounds row must be within tolerance AND
    # there must be exactly two bounds rows (one per cover slide).
    bounds_rows = record.get("bounds_readback") or []
    if len(bounds_rows) != 2:
        failures.append(
            f"bounds_readback length={len(bounds_rows)}; expected "
            f"exactly 2 rows (one per cover slide)"
        )
    for row in bounds_rows:
        if not isinstance(row, dict):
            failures.append(
                f"bounds_readback contains a non-dict entry: {row!r}"
            )
            continue
        if row.get("pic_count") != 1:
            failures.append(
                f"bounds_readback[{row.get('slide_index')!r}]."
                f"pic_count={row.get('pic_count')!r}; expected "
                f"exactly 1 picture on each cover slide"
            )
        failures.extend(_bounds_within_tolerance(row))

    # Refuse any positive real-D-One success claim anywhere in the
    # readback record.
    failures.extend(_scan_for_positive_real_d_one_claim(record))

    return failures


# ---------------------------------------------------------------------------
# Happy path.
# ---------------------------------------------------------------------------


def _run_happy_path(
    td: Path,
) -> tuple[int, dict | None]:
    print(
        "--- happy path: synthetic mixed-lane bundle -> mock pipeline "
        "-> contract + inventory -> placement readback ---"
    )

    bundle_info = _materialize_bundle(
        td, d_one_spec_overrides=_taxonomy_d_one_spec_body(),
    )
    bundle_dir = bundle_info["bundle"]
    # Same paired descriptor_vocabulary.json the handoff smoke uses.
    vocab_path = bundle_dir / "descriptor_vocabulary.json"
    vocab_path.write_text(
        json.dumps(_descriptor_vocab_body(), indent=2, sort_keys=True)
        + "\n",
    )

    workspace = td / "ws"
    output = td / "out.pptx"
    report_dir = td / "report"

    print(f"  bundle:    {bundle_dir}")
    print(f"  workspace: {workspace}")
    print(f"  output:    {output}")
    print(f"  report:    {report_dir}")

    pipeline = _run_pipeline(
        bundle_dir=bundle_dir, workspace=workspace,
        output=output, report_dir=report_dir,
    )
    if not pipeline.ok:
        print(f"  [FAIL] pipeline rc={pipeline.rc}")
        for line in (
            pipeline.stderr or pipeline.stdout or ""
        ).splitlines()[-15:]:
            print(f"    {line}")
        return 1, None
    print("  [PASS] pipeline rc=0")

    if not output.is_file() or output.is_symlink():
        print(
            f"  [FAIL] expected PPTX as a regular non-symlink file at "
            f"{output}"
        )
        return 1, None
    print("  [PASS] produced PPTX exists as a regular non-symlink file")

    contract = _run_contract_validator(pptx=output, expected_slide_count=2)
    if not contract.ok:
        print(f"  [FAIL] validate_pptx_contract rc={contract.rc}")
        for line in (
            contract.stderr or contract.stdout or ""
        ).splitlines()[-20:]:
            print(f"    {line}")
        return 1, None
    print("  [PASS] validate_pptx_contract rc=0")

    inventory_path = td / "inventory.json"
    inventory_outcome = _run_inventory(
        pptx=output, out=inventory_path,
    )
    if not inventory_outcome.ok:
        print(
            f"  [FAIL] inspect_pptx_inventory rc={inventory_outcome.rc}"
        )
        for line in (
            inventory_outcome.stderr or inventory_outcome.stdout or ""
        ).splitlines()[-20:]:
            print(f"    {line}")
        return 1, None
    print("  [PASS] inspect_pptx_inventory rc=0")
    try:
        inventory = json.loads(inventory_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"  [FAIL] cannot parse {inventory_path}: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1, None

    # Per-lane workspace sha256.
    d_one_asset = workspace / D_ONE_LOCAL_PATH
    local_asset = workspace / LOCAL_ASSET_LOCAL_PATH
    for label, p in (
        ("d_one_local", d_one_asset),
        ("local_asset", local_asset),
    ):
        if not p.is_file() or p.is_symlink():
            print(
                f"  [FAIL] expected {label} workspace asset as a "
                f"regular non-symlink file at {p}"
            )
            return 1, None
    d_one_sha = _sha256_file(d_one_asset)
    local_asset_sha = _sha256_file(local_asset)
    if d_one_sha == local_asset_sha:
        print(
            f"  [FAIL] d_one_local and local_asset workspace assets "
            f"share the same sha256 ({d_one_sha!r}) — the two lanes "
            f"must carry independent bytes"
        )
        return 1, None
    print(
        f"  [PASS] per-lane workspace sha256 distinct "
        f"(d_one={d_one_sha[:16]}..., local_asset={local_asset_sha[:16]}...)"
    )

    # Slide-XML walk for <p:pic> xfrm.
    slide_pics, slide_pic_errors = _slide_pic_xfrms(output)
    if slide_pic_errors:
        for err in slide_pic_errors:
            print(f"  [WARN] slide-pic walk: {err}")
    if set(slide_pics) != {1, 2}:
        print(
            f"  [FAIL] expected <p:pic> on slides {{1, 2}}; got "
            f"{sorted(slide_pics)!r}"
        )
        return 1, None
    print(
        f"  [PASS] slide-XML walk found <p:pic> on slides "
        f"{sorted(slide_pics)!r}"
    )

    # Per-slide rels resolution (r_id -> resolved part). Drives the
    # blip-embed lane proof in the truth-checker.
    slide_rels, slide_rels_errors = _slide_rels_resolution(output)
    if slide_rels_errors:
        for err in slide_rels_errors:
            print(f"  [WARN] slide rels walk: {err}")
    if not {1, 2} <= set(slide_rels):
        print(
            f"  [FAIL] expected slide rels for {{1, 2}}; got "
            f"{sorted(slide_rels)!r}"
        )
        return 1, None
    print(
        f"  [PASS] slide rels walk resolved r_id -> part on slides "
        f"{sorted(slide_rels)!r}"
    )

    # render_models walk for image_slot bounds.
    bounds_by_slide, bounds_errors = _render_model_image_slot_bounds(
        workspace,
    )
    if bounds_errors:
        for err in bounds_errors:
            print(f"  [WARN] render_model walk: {err}")
    if set(bounds_by_slide) != {1, 2}:
        print(
            f"  [FAIL] expected image_slot bounds for slides {{1, 2}}; "
            f"got {sorted(bounds_by_slide)!r}"
        )
        return 1, None
    print(
        f"  [PASS] render_model image_slot bounds covered slides "
        f"{sorted(bounds_by_slide)!r}"
    )

    # Sidecar walk for taxonomy projection.
    taxonomy_by_id, sidecar_ids, sidecar_errors = _sidecar_taxonomy(
        report_dir,
    )
    if sidecar_errors:
        for err in sidecar_errors:
            print(f"  [WARN] sidecar walk: {err}")
            return 1, None

    ctx = _ReadbackContext(
        pptx_path=output, workspace=workspace, report_dir=report_dir,
        inventory=inventory,
        inventory_outcome=inventory_outcome,
        contract=contract,
        d_one_sha=d_one_sha,
        local_asset_sha=local_asset_sha,
        slide_pics=slide_pics,
        slide_rels=slide_rels,
        bounds_by_slide=bounds_by_slide,
        taxonomy_by_id=taxonomy_by_id,
        sidecar_ids=sidecar_ids,
    )
    readback = _build_readback(ctx)

    truth_failures = _check_readback_truth(readback)
    if truth_failures:
        print(
            f"  [FAIL] placement readback truth-checker refused "
            f"({len(truth_failures)} failure(s)):"
        )
        for f in truth_failures:
            print(f"    - {f}")
        return 1, readback
    print("  [PASS] placement readback truth-checker accepted")

    print()
    print("--- placement readback ---")
    print(json.dumps(readback, indent=2, sort_keys=True))
    print()
    return 0, readback


# ---------------------------------------------------------------------------
# Direct probes (no pipeline re-run).
# ---------------------------------------------------------------------------


@dataclass
class _ProbeOutcome:
    name: str
    ok: bool
    detail: str = ""


def _clone(record: dict) -> dict:
    return json.loads(json.dumps(record))


def _expect_refusal(
    name: str, record: dict, expect_substr: list[str] | None = None,
) -> _ProbeOutcome:
    """Run the truth-checker on ``record`` and assert it refuses.
    If ``expect_substr`` is supplied, every substring must appear in
    at least one failure diagnostic."""
    failures = _check_readback_truth(record)
    if not failures:
        return _ProbeOutcome(
            name, False,
            f"expected truth-checker refusal; got an empty failure "
            f"list",
        )
    if expect_substr:
        missing = [
            s for s in expect_substr
            if not any(s in f for f in failures)
        ]
        if missing:
            return _ProbeOutcome(
                name, False,
                f"expected diagnostic substring(s) {missing!r} not "
                f"present in failures {failures!r}",
            )
    return _ProbeOutcome(name, True)


def _drop_media_part_by_sha(record: dict, sha: str) -> None:
    """Remove every media-part row whose sha256 == ``sha`` and clear
    that sha from every lane row that pointed at it."""
    record["media_parts"] = [
        e for e in (record.get("media_parts") or [])
        if not (isinstance(e, dict) and e.get("sha256") == sha)
    ]
    for label, lane in (record.get("lanes") or {}).items():
        if isinstance(lane, dict) and lane.get("media_sha256") == sha:
            lane["media_part"] = None
            lane["media_sha256"] = None
            lane["referencing_slides"] = []


def _swap_referencing_slides(record: dict) -> None:
    """Swap the referencing_slides between the d_one_local and
    local_asset media parts (and the matching lane rows). After the
    swap, slide 1 carries the local_asset and slide 2 carries the
    d_one_local — exactly the bug the milestone wants caught."""
    lanes = record.get("lanes") or {}
    d_one = lanes.get("d_one_local") or {}
    local = lanes.get("local_asset") or {}
    d_one_refs = list(d_one.get("referencing_slides") or [])
    local_refs = list(local.get("referencing_slides") or [])
    d_one["referencing_slides"] = local_refs
    local["referencing_slides"] = d_one_refs

    d_one_sha = d_one.get("media_sha256")
    local_sha = local.get("media_sha256")
    for entry in record.get("media_parts") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("sha256") == d_one_sha:
            entry["referencing_slides"] = local_refs
        elif entry.get("sha256") == local_sha:
            entry["referencing_slides"] = d_one_refs


def _add_orphan_media(record: dict) -> None:
    record.setdefault("media_parts", []).append({
        "part": "ppt/media/orphan_synthetic.png",
        "sha256": "0" * 64,
        "extension": "png",
        "referencing_slides": [],
    })


def _add_external_relationship(record: dict) -> None:
    record.setdefault("relationships", []).append({
        "rels_part": "ppt/slides/_rels/slide1.xml.rels",
        "id": "rId_external_synth",
        "type": (
            "http://schemas.openxmlformats.org/officeDocument/2006/"
            "relationships/image"
        ),
        "target": "https://example.invalid/synth.png",
        "target_mode": "External",
    })


def _add_file_uri_relationship(record: dict) -> None:
    record.setdefault("relationships", []).append({
        "rels_part": "ppt/slides/_rels/slide1.xml.rels",
        "id": "rId_file_synth",
        "type": (
            "http://schemas.openxmlformats.org/officeDocument/2006/"
            "relationships/image"
        ),
        "target": "file:///etc/passwd",
        "target_mode": "Internal",
    })


def _add_data_uri_relationship(record: dict) -> None:
    record.setdefault("relationships", []).append({
        "rels_part": "ppt/slides/_rels/slide1.xml.rels",
        "id": "rId_data_synth",
        "type": (
            "http://schemas.openxmlformats.org/officeDocument/2006/"
            "relationships/image"
        ),
        "target": "data:image/png;base64,AAA",
        "target_mode": "Internal",
    })


def _flip_slide_image_only(record: dict, slide_idx: int) -> None:
    """Mutate the slide row at ``slide_idx`` to flip
    image_only_evidence True AND zero its native text/shape counts so
    the truth-checker's full-slide raster gate fires."""
    for srow in record.get("slides") or []:
        if isinstance(srow, dict) and srow.get("index") == slide_idx:
            srow["image_only_evidence"] = True
            srow["text_run_count"] = 0
            srow["shapes_sp"] = 0


def _strip_d_one_generated_intent(record: dict) -> None:
    lane = (record.get("lanes") or {}).get("d_one_local") or {}
    lane["generated_intent"] = {}


def _attach_local_asset_generated_intent(record: dict) -> None:
    lane = (record.get("lanes") or {}).get("local_asset") or {}
    lane["generated_intent"] = {
        "placement_role": "local_region",
        "text_policy": "no_text",
        "subject_domain": "abstract_geometry",
    }


def _drift_bounds_off(record: dict, slide_idx: int, delta: int) -> None:
    """Shift the slide_idx bounds row's actual_emu.off_x by ``delta``
    EMU. Anything beyond BOUNDS_TOLERANCE_EMU fails the bounds gate."""
    for row in record.get("bounds_readback") or []:
        if isinstance(row, dict) and row.get("slide_index") == slide_idx:
            actual = row.get("actual_emu") or {}
            cur = actual.get("off_x")
            if isinstance(cur, int):
                actual["off_x"] = cur + delta


def _drift_bounds_ext(record: dict, slide_idx: int, delta: int) -> None:
    for row in record.get("bounds_readback") or []:
        if isinstance(row, dict) and row.get("slide_index") == slide_idx:
            actual = row.get("actual_emu") or {}
            cur = actual.get("ext_cx")
            if isinstance(cur, int):
                actual["ext_cx"] = cur + delta


def _inject_positive_claim(record: dict, marker: str) -> None:
    record.setdefault("notes", {})["scope"] = marker


def _run_probes(baseline: dict) -> int:
    print()
    print("--- fail-closed probes (direct; no pipeline re-run) ---")

    # Sanity: the baseline must STILL pass the truth-checker
    # unmodified — a probe regression that secretly carried over
    # mutations from a prior call would silently invalidate every
    # subsequent probe.
    if _check_readback_truth(_clone(baseline)):
        print(
            "  [FAIL] baseline truth-check no longer holds — refusing "
            "to run probes against a poisoned baseline"
        )
        return 1

    probes: list[_ProbeOutcome] = []

    # P1: missing d_one_local media reference.
    p1 = _clone(baseline)
    _drop_media_part_by_sha(
        p1,
        (p1["lanes"]["d_one_local"]["media_sha256"]
         or p1["lanes"]["d_one_local"]["expected_sha256"]),
    )
    probes.append(_expect_refusal(
        "P1 missing d_one_local media reference refused",
        p1, expect_substr=["lanes.d_one_local"],
    ))

    # P2: missing local_asset media reference.
    p2 = _clone(baseline)
    _drop_media_part_by_sha(
        p2,
        (p2["lanes"]["local_asset"]["media_sha256"]
         or p2["lanes"]["local_asset"]["expected_sha256"]),
    )
    probes.append(_expect_refusal(
        "P2 missing local_asset media reference refused",
        p2, expect_substr=["lanes.local_asset"],
    ))

    # P3: swapped slide references.
    p3 = _clone(baseline)
    _swap_referencing_slides(p3)
    probes.append(_expect_refusal(
        "P3 swapped d_one_local / local_asset slide references refused",
        p3, expect_substr=["referencing_slides"],
    ))

    # P4: orphan embedded media (extra part with no referencing slides).
    p4 = _clone(baseline)
    _add_orphan_media(p4)
    probes.append(_expect_refusal(
        "P4 orphan embedded media refused",
        p4, expect_substr=["referencing_slides"],
    ))

    # P5: External relationship.
    p5 = _clone(baseline)
    _add_external_relationship(p5)
    probes.append(_expect_refusal(
        "P5 External relationship refused",
        p5, expect_substr=["target_mode"],
    ))

    # P5b: file:// relationship.
    p5b = _clone(baseline)
    _add_file_uri_relationship(p5b)
    probes.append(_expect_refusal(
        "P5b file:// relationship refused",
        p5b, expect_substr=["file://"],
    ))

    # P5c: data: relationship.
    p5c = _clone(baseline)
    _add_data_uri_relationship(p5c)
    probes.append(_expect_refusal(
        "P5c data: URI relationship refused",
        p5c, expect_substr=["URI scheme prefix"],
    ))

    # P6: full-slide / all-image slide evidence.
    p6 = _clone(baseline)
    _flip_slide_image_only(p6, slide_idx=1)
    probes.append(_expect_refusal(
        "P6 full-slide / all-image slide evidence refused",
        p6, expect_substr=["image_only_evidence"],
    ))

    # P7: positive real-D-One / MCP / network / model / image-search /
    # Qoder success claim.
    for marker in (
        "Real D-One verified online",
        "called MCP successfully",
        "model API returned successfully",
        "image search succeeded",
        "Qoder runtime succeeded",
        "public network ran live",
    ):
        p7 = _clone(baseline)
        _inject_positive_claim(p7, marker)
        probes.append(_expect_refusal(
            f"P7 positive claim refused [{marker}]",
            p7,
        ))

    # P7b: real_d_one_status drift.
    p7b = _clone(baseline)
    p7b["real_d_one_status"] = "VERIFIED"
    probes.append(_expect_refusal(
        "P7b real_d_one_status drift refused",
        p7b, expect_substr=["real_d_one_status"],
    ))

    # P8: d_one_local generated_intent stripped.
    p8 = _clone(baseline)
    _strip_d_one_generated_intent(p8)
    probes.append(_expect_refusal(
        "P8 d_one_local generated_intent stripped refused",
        p8, expect_substr=["generated_intent"],
    ))

    # P9: local_asset attached to generated_intent.
    p9 = _clone(baseline)
    _attach_local_asset_generated_intent(p9)
    probes.append(_expect_refusal(
        "P9 local_asset attached to generated_intent refused",
        p9, expect_substr=["lanes.local_asset.generated_intent"],
    ))

    # P10: bounds drift on slide 1 offset.
    p10 = _clone(baseline)
    _drift_bounds_off(p10, slide_idx=1, delta=10 * EMU_PER_PX)
    probes.append(_expect_refusal(
        "P10 bounds drift on slide 1 offset refused",
        p10, expect_substr=["bounds_readback"],
    ))

    # P10b: bounds drift on slide 1 size.
    p10b = _clone(baseline)
    _drift_bounds_ext(p10b, slide_idx=1, delta=10 * EMU_PER_PX)
    probes.append(_expect_refusal(
        "P10b bounds drift on slide 1 size refused",
        p10b, expect_substr=["bounds_readback"],
    ))

    # P11: slide <p:pic> blip embeds the wrong lane's media part.
    # This is the regression the rels-only gate would have missed: a
    # slide that owns a rel to lane A's part but whose <p:pic> blip
    # actually embeds lane B's part. The blip-embed gate refuses
    # because lanes.<lane>.intended_slide_blip_embed_part no longer
    # equals lanes.<lane>.media_part.
    p11 = _clone(baseline)
    d_one_part = p11["lanes"]["d_one_local"]["media_part"]
    local_part = p11["lanes"]["local_asset"]["media_part"]
    p11["lanes"]["d_one_local"]["intended_slide_blip_embed_part"] = (
        local_part
    )
    p11["lanes"]["local_asset"]["intended_slide_blip_embed_part"] = (
        d_one_part
    )
    probes.append(_expect_refusal(
        "P11 slide <p:pic> blip embed cross-swap refused",
        p11, expect_substr=["intended_slide_blip_embed_part"],
    ))

    # P11b: slide <p:pic> blip embed missing entirely (rels declares
    # part but no rel translates the blip's rId, e.g. attacker added a
    # picture whose rId resolves to nothing in the slide's rels file).
    p11b = _clone(baseline)
    p11b["lanes"]["d_one_local"]["intended_slide_blip_embed_part"] = None
    probes.append(_expect_refusal(
        "P11b slide <p:pic> blip embed unresolved refused",
        p11b, expect_substr=["intended_slide_blip_embed_part"],
    ))

    # Confirm the baseline still passes — defense-in-depth, in case a
    # probe accidentally mutated the baseline (deep-copy regression).
    if _check_readback_truth(_clone(baseline)):
        probes.append(_ProbeOutcome(
            "baseline truth-check still passes after every probe",
            False,
            "baseline truth-checker now refuses — a probe may have "
            "mutated the shared baseline",
        ))
    else:
        probes.append(_ProbeOutcome(
            "baseline truth-check still passes after every probe",
            True,
        ))

    fails = 0
    for p in probes:
        mark = "PASS" if p.ok else "FAIL"
        print(f"  [{mark}] {p.name}")
        if not p.ok:
            if p.detail:
                print(f"    detail: {p.detail}")
            fails += 1
    return fails


# ---------------------------------------------------------------------------
# Self-test top level.
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    print("=== image_placement_readback_smoke (--self-test) ===")

    tree_before = _snapshot_committed_tree()
    if not tree_before:
        print(
            "FAIL: committed-tree snapshot is empty — refusing to run "
            "because a downstream regression cannot be detected against "
            "an empty baseline.",
            file=sys.stderr,
        )
        return 1

    rc = 0
    with tempfile.TemporaryDirectory(
        prefix="szh_image_placement_readback_smoke_",
    ) as raw_td:
        td = Path(raw_td)
        happy_rc, baseline = _run_happy_path(td)
        if happy_rc != 0 or baseline is None:
            rc = 1
        else:
            probe_fails = _run_probes(baseline)
            if probe_fails:
                rc = 1

    tree_after = _snapshot_committed_tree()
    if tree_before != tree_after:
        changed = sorted(
            k for k in set(tree_before) | set(tree_after)
            if tree_before.get(k) != tree_after.get(k)
        )
        print(
            f"FAIL: committed tree under REPO_ROOT mutated during the "
            f"placement-readback smoke (changed: {changed!r})",
            file=sys.stderr,
        )
        rc = 1

    if rc == 0:
        print()
        print(
            "OK (image placement readback): happy path + every fail-"
            "closed probe passed; nothing under REPO_ROOT mutated. "
            "Real D-One remains UNVERIFIED — one local/mock readback "
            "command proves image placement and editability evidence."
        )
    return rc


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Slide-level image placement / readback smoke for the "
            "core image-to-editable-PPT loop. Drives the existing "
            "mixed-lane mock pipeline once into a per-run tempdir, "
            "walks the produced PPTX + inventory + workspace "
            "render_models + sidecar, and asserts each image lane "
            "lands on its intended slide AND inside the intended "
            "image_slot bounds while every editability gate the "
            "core demo pins still holds. Stdlib-only. NETWORK-FREE. "
            "NO real D-One. NO MCP. NO Qoder. NO model API. NO image "
            "search. NO telemetry. Self-test surface only today."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Required: run the happy path + every fail-closed probe."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: image_placement_readback_smoke.py requires "
            "--self-test (no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
