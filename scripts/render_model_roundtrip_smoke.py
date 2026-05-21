#!/usr/bin/env python3
"""render_model_roundtrip_smoke.py

Clean-room, stdlib-only acceptance smoke for the render_model -> PPTX
round-trip on the basic editable-PPT core path.

Purpose
-------
Prove that an authored ``render_models/*.json`` workspace exports
through ``scripts/export_pptx.py`` into a ``.pptx`` whose OOXML
inventory still matches what was authored. The smoke deliberately does
NOT introduce any automatic prompt / report / image -> PPT inference —
it only round-trips an already-deterministic, hand-authored synthetic
fixture and asserts the produced package still carries the same
editable structure.

Reuses three existing local scripts as subprocesses:

  - ``scripts/export_pptx.py`` — workspace -> .pptx
  - ``scripts/validate_pptx_contract.py`` — container / minimal-evidence
    gates (with optional ``--expected-slide-count``)
  - ``scripts/inspect_pptx_inventory.py`` — deterministic JSON readback

Positive proof (asserted against a 4-slide synthetic fixture covering
the full text / line / shape / kpi / table / image_slot primitive
set across the ``cover`` / ``comparison_table`` / ``two_column`` /
``kpi_dashboard`` layouts — every primitive kind the exporter
supports today is exercised at least once):

  - the produced ``.pptx`` exists and opens as a ZIP;
  - ``inspect_pptx_inventory`` reports ``ok=True`` with ``findings=[]``;
  - ``inventory.slide_count`` equals ``len(deck_plan.slides)`` and the
    number of authored ``render_models/*.json`` files;
  - every slide row carries at least one ``<p:sp>`` or ``<p:cxnSp>``
    (native editable shape) and is NOT image_only / blank;
  - every authored ``text`` primitive's ``text.content`` string appears
    verbatim in the matching slide's XML;
  - every authored ``table`` primitive's column headers AND row cell
    strings appear verbatim in the matching slide's XML, and the slide
    carries at least one ``<a:tbl>`` graphic frame;
  - every authored PNG / JPG / JPEG ``image_slot`` manifest entry maps
    to an internal ``ppt/media/*`` part and a per-slide image
    relationship whose Target is internal (no scheme, no
    ``TargetMode="External"``);
  - no relationship anywhere in the package is external / file:// /
    data: / http:// / https:// / ftp://;
  - ``validate_pptx_contract.py --pptx <out> --expected-slide-count N``
    passes with rc=0.

Negative probes (each runs under its own ``tempfile.TemporaryDirectory()``;
each expects fail-closed behavior on a documented perturbation of the
same baseline):

  N1  expected text evidence removed from a slide XML — the positive
      text-presence assertion fails.

  N2  expected table cell content removed from a slide XML — the
      positive table-cell-presence assertion fails.

  N3  per-slide image relationship rewritten to an external
      ``http://...`` Target — ``inspect_pptx_inventory`` records
      ``relationships.external``.

  N4  an extra unreferenced part dropped under ``ppt/media/`` —
      ``inspect_pptx_inventory`` records ``media.orphan``.

  N5  the embedded ``ppt/media/image1.png`` part removed from the ZIP
      — ``inspect_pptx_inventory`` records ``media.missing``.

  N6  ``validate_pptx_contract.py --pptx <positive> --expected-slide-count``
      called with the WRONG N — the ``slide_count.expected`` gate fails
      closed.

  N7a a render_model carrying an unsupported ``chart_placeholder``
      primitive — ``export_pptx.py`` aborts before any .pptx is written.

  N7b an ``image_manifest.json`` entry whose ``local_path`` carries a
      ``file://`` URI scheme — ``export_pptx.py`` aborts at the manifest
      preflight before any .pptx is written.

Clean-room / scope constraints
------------------------------
- stdlib only;
- no real D-One, MCP, Qoder runtime, public network, telemetry, model
  API, image search, browser / screenshot review, animation, audio,
  video, or upstream code / assets / prompts / templates / wording
  from ``/Users/robert/ppt-master``;
- every scenario runs inside its own ``tempfile.TemporaryDirectory()``;
  no generated PPTX / report / temp artifact is written under
  ``REPO_ROOT/``;
- ``REPO_ROOT/examples/`` and ``REPO_ROOT/scripts/`` are byte-
  snapshotted before and after the run and must match.

Run with ``--self-test`` (no other CLI surface exists).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

EXPORT_PPTX = SCRIPTS_DIR / "export_pptx.py"
VALIDATE_PPTX_CONTRACT = SCRIPTS_DIR / "validate_pptx_contract.py"
INSPECT_PPTX_INVENTORY = SCRIPTS_DIR / "inspect_pptx_inventory.py"

# Must match scripts/inspect_pptx_inventory.py::EVIDENCE_BASIS verbatim.
EXPECTED_EVIDENCE_BASIS = (
    "OOXML structure only; not proof of full PowerPoint editability"
)

# Minimal valid 1x1 PNG: 8-byte signature + IHDR + IDAT + IEND. Mirrors
# the synthetic payload other smokes use; never claims to be
# photographically meaningful.
_TINY_PNG_BYTES: bytes = bytes.fromhex(
    "89504e470d0a1a0a"
    "0000000d49484452"
    "0000000100000001"
    "08060000001f15c489"
    "0000000d49444154"
    "789c6300010000000500010d0a2db4"
    "0000000049454e44ae426082"
)

# Authored text markers — each appears verbatim inside its slide's
# render_model text primitive AND must appear verbatim in the
# corresponding slide XML after export. Keeping the strings unique
# makes the text-presence assertion robust to OOXML boilerplate that
# might happen to contain a substring of a generic phrase.
SLIDE1_TITLE = "RoundTrip Cover Marker"
SLIDE1_SUBTITLE = "Editable Subtitle Marker"
SLIDE2_TITLE = "Comparison Probe Marker"
SLIDE3_TITLE = "Embedded PNG Slide Marker"
SLIDE4_TITLE = "KPI Dashboard Marker"
SLIDE4_KPI_LABEL = "kpi_label_marker"
SLIDE4_KPI_VALUE = "kpi_value_marker"
SLIDE4_KPI_DELTA = "kpi_delta_marker"

TABLE_COLUMNS = (
    "metric_alpha_col",
    "value_col",
)
TABLE_ROWS = (
    ("metric_alpha_row", "value_alpha_row"),
    ("metric_beta_row", "value_beta_row"),
)

IMAGE_REF_ID = "tiny_marker"
IMAGE_LOCAL_PATH = "assets/tiny.png"
IMAGE_ALT_TEXT = "Tiny synthetic marker PNG (smoke fixture)."

# External-target shapes the positive assertion refuses everywhere in
# the package. The first three are URI schemes; the last is the
# ``TargetMode="External"`` attribute.
_FORBIDDEN_TARGET_PREFIXES: tuple[str, ...] = (
    "http://", "https://", "file://", "data:", "ftp://",
)


# ---------------------------------------------------------------------------
# Snapshot helpers — prove the smoke writes nothing under REPO_ROOT.
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
# Subprocess + ZIP helpers.
# ---------------------------------------------------------------------------


@dataclass
class ToolOutcome:
    cmd: list[str]
    rc: int
    stdout: str
    stderr: str

    @property
    def combined(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


def _run(cmd: list[str]) -> ToolOutcome:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    return ToolOutcome(
        cmd=cmd, rc=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


def _mutate_zip_entry(
    pptx: Path,
    target_name: str,
    transform,
) -> None:
    """Rewrite the entry ``target_name`` inside ``pptx`` by passing its
    raw bytes through ``transform`` (bytes -> bytes). Used by negative
    probes that perturb a single OOXML part."""
    src_bytes: dict[str, bytes] = {}
    with zipfile.ZipFile(pptx, "r") as zin:
        for name in zin.namelist():
            src_bytes[name] = zin.read(name)
    if target_name not in src_bytes:
        raise RuntimeError(
            f"_mutate_zip_entry: {target_name!r} not in {pptx} entries"
        )
    src_bytes[target_name] = transform(src_bytes[target_name])
    tmp = pptx.with_suffix(pptx.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name, data in src_bytes.items():
            zout.writestr(name, data)
    os.replace(tmp, pptx)


def _drop_zip_entry(pptx: Path, target_name: str) -> None:
    """Rewrite ``pptx`` with ``target_name`` removed."""
    src_bytes: dict[str, bytes] = {}
    with zipfile.ZipFile(pptx, "r") as zin:
        for name in zin.namelist():
            if name == target_name:
                continue
            src_bytes[name] = zin.read(name)
    tmp = pptx.with_suffix(pptx.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name, data in src_bytes.items():
            zout.writestr(name, data)
    os.replace(tmp, pptx)


def _add_zip_entry(pptx: Path, name: str, payload: bytes) -> None:
    """Append a new entry to ``pptx``."""
    src_bytes: dict[str, bytes] = {}
    with zipfile.ZipFile(pptx, "r") as zin:
        for n in zin.namelist():
            src_bytes[n] = zin.read(n)
    src_bytes[name] = payload
    tmp = pptx.with_suffix(pptx.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for n, data in src_bytes.items():
            zout.writestr(n, data)
    os.replace(tmp, pptx)


# ---------------------------------------------------------------------------
# Synthetic fixture writer.
# ---------------------------------------------------------------------------


def _write_workspace(ws: Path) -> None:
    """Build a 4-slide synthetic workspace under ``ws``:

      slide 1  cover               text (title + subtitle) + line
      slide 2  comparison_table    text (title) + table (cols + rows)
      slide 3  two_column          text (title) + image_slot PNG
      slide 4  kpi_dashboard       text (title) + shape (rounded card)
                                   + kpi (label + value + delta)

    Together the four slides exercise every primitive kind the exporter
    supports today — text, line, shape, image_slot, kpi, and table.
    The shape mirrors what ``scripts/export_pptx.py``'s own self-test
    fixtures use, so the exporter accepts it without an upstream
    ``validate_workspace`` step. None of the strings reference real
    company / customer / financial data.
    """
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "render_models").mkdir(parents=True, exist_ok=True)
    (ws / "assets").mkdir(parents=True, exist_ok=True)
    (ws / "assets" / "tiny.png").write_bytes(_TINY_PNG_BYTES)

    deck_plan = {
        "template": "synthetic",
        "planning": {
            "planned_slide_count": 4,
            "rationale": "synthetic round-trip smoke fixture",
        },
        "sections": [{
            "id": "all",
            "title": "All",
            "summary": "synthetic",
            "slide_indices": [1, 2, 3, 4],
        }],
        "slides": [
            {
                "index": 1, "layout": "cover",
                "title": "Round-Trip Cover",
                "section_id": "all",
                "summary": "synthetic",
                "density": "low",
                "source_refs": ["synthetic_src"],
            },
            {
                "index": 2, "layout": "comparison_table",
                "title": "Comparison Probe",
                "section_id": "all",
                "summary": "synthetic",
                "density": "low",
                "source_refs": ["synthetic_src"],
            },
            {
                "index": 3, "layout": "two_column",
                "title": "Embedded PNG Slide",
                "section_id": "all",
                "summary": "synthetic",
                "density": "low",
                "source_refs": ["synthetic_src"],
            },
            {
                "index": 4, "layout": "kpi_dashboard",
                "title": "KPI Dashboard Probe",
                "section_id": "all",
                "summary": "synthetic",
                "density": "low",
                "source_refs": ["synthetic_src"],
            },
        ],
    }
    (ws / "deck_plan.json").write_text(
        json.dumps(deck_plan, indent=2, sort_keys=True) + "\n"
    )

    design = {
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
    (ws / "design_system.json").write_text(
        json.dumps(design, indent=2, sort_keys=True) + "\n"
    )

    manifest = {
        "images": [{
            "id": IMAGE_REF_ID,
            "local_path": IMAGE_LOCAL_PATH,
            "source": "synthetic",
            "alt_text": IMAGE_ALT_TEXT,
            "intended_use": "icon",
            "width_px": 1,
            "height_px": 1,
        }],
    }
    (ws / "image_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )

    (ws / "render_models" / "01_cover.json").write_text(json.dumps({
        "index": 1,
        "layout": "cover",
        "canvas": {"width_px": 1920, "height_px": 1080},
        "source_refs": ["synthetic_src"],
        "primitives": [
            {
                "id": "title_divider",
                "kind": "line",
                "bounds": {"x": 160, "y": 290, "w": 1280, "h": 4},
                "style": {
                    "stroke_token": "palette.primary",
                    "stroke_width_px": 4,
                },
                "line": {"stroke_style": "solid"},
            },
            {
                "id": "title",
                "slot_id": "title",
                "kind": "text",
                "bounds": {"x": 160, "y": 320, "w": 1280, "h": 100},
                "style": {
                    "color_token": "palette.text",
                    "typography_token": "typography.heading",
                },
                "text": {"content": SLIDE1_TITLE, "role": "heading"},
            },
            {
                "id": "subtitle",
                "slot_id": "subtitle",
                "kind": "text",
                "bounds": {"x": 160, "y": 460, "w": 1280, "h": 80},
                "style": {
                    "color_token": "palette.text",
                    "typography_token": "typography.body",
                },
                "text": {"content": SLIDE1_SUBTITLE, "role": "subheading"},
            },
        ],
    }, indent=2, sort_keys=True) + "\n")

    (ws / "render_models" / "02_comparison_table.json").write_text(json.dumps({
        "index": 2,
        "layout": "comparison_table",
        "canvas": {"width_px": 1920, "height_px": 1080},
        "source_refs": ["synthetic_src"],
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
                "text": {"content": SLIDE2_TITLE, "role": "heading"},
            },
            {
                "id": "comparison_table",
                "slot_id": "table",
                "kind": "table",
                "bounds": {"x": 64, "y": 240, "w": 1792, "h": 760},
                "style": {"color_token": "palette.text"},
                "table": {
                    "columns": list(TABLE_COLUMNS),
                    "rows": [list(r) for r in TABLE_ROWS],
                },
            },
        ],
    }, indent=2, sort_keys=True) + "\n")

    (ws / "render_models" / "03_two_column.json").write_text(json.dumps({
        "index": 3,
        "layout": "two_column",
        "canvas": {"width_px": 1920, "height_px": 1080},
        "source_refs": ["synthetic_src"],
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
                "text": {"content": SLIDE3_TITLE, "role": "heading"},
            },
            {
                "id": "marker_image",
                "kind": "image_slot",
                "bounds": {"x": 200, "y": 300, "w": 200, "h": 200},
                "image_slot": {
                    "image_ref": IMAGE_REF_ID,
                    "alt_text": IMAGE_ALT_TEXT,
                },
            },
        ],
    }, indent=2, sort_keys=True) + "\n")

    (ws / "render_models" / "04_kpi_dashboard.json").write_text(json.dumps({
        "index": 4,
        "layout": "kpi_dashboard",
        "canvas": {"width_px": 1920, "height_px": 1080},
        "source_refs": ["synthetic_src"],
        "primitives": [
            {
                "id": "title",
                "slot_id": "title",
                "kind": "text",
                "bounds": {"x": 64, "y": 80, "w": 1792, "h": 120},
                "style": {
                    "color_token": "palette.text",
                    "typography_token": "typography.heading",
                },
                "text": {"content": SLIDE4_TITLE, "role": "heading"},
            },
            {
                "id": "kpi_card",
                "kind": "shape",
                "bounds": {"x": 96, "y": 300, "w": 858, "h": 160},
                "style": {
                    "fill_token": "palette.background",
                    "stroke_token": "palette.primary",
                    "stroke_width_px": 2,
                },
                "shape": {
                    "shape_kind": "rounded_rectangle",
                    "corner_radius_px": 12,
                },
            },
            {
                "id": "kpi_tile",
                "slot_id": "kpis",
                "kind": "kpi",
                "bounds": {"x": 96, "y": 300, "w": 858, "h": 160},
                "style": {"color_token": "palette.text"},
                "kpi": {
                    "label": SLIDE4_KPI_LABEL,
                    "value": SLIDE4_KPI_VALUE,
                    "delta": SLIDE4_KPI_DELTA,
                },
            },
        ],
    }, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Export + inspect helpers.
# ---------------------------------------------------------------------------


def _export(ws: Path, out_pptx: Path) -> ToolOutcome:
    return _run([
        "python3", str(EXPORT_PPTX),
        "--workspace", str(ws),
        "--output", str(out_pptx),
    ])


def _inspect(pptx: Path, out_json: Path) -> ToolOutcome:
    return _run([
        "python3", str(INSPECT_PPTX_INVENTORY),
        "--pptx", str(pptx),
        "--out", str(out_json),
    ])


def _validate_contract(
    pptx: Path,
    *,
    expected_slide_count: int | None,
) -> ToolOutcome:
    cmd = [
        "python3", str(VALIDATE_PPTX_CONTRACT),
        "--pptx", str(pptx),
    ]
    if expected_slide_count is not None:
        cmd.extend(["--expected-slide-count", str(expected_slide_count)])
    return _run(cmd)


# ---------------------------------------------------------------------------
# Positive assertion. Returns a list of failure strings (empty == pass).
# ---------------------------------------------------------------------------


def _positive_assertions(
    *,
    pptx: Path,
    inventory: dict,
    workspace: Path,
) -> list[str]:
    errs: list[str] = []

    deck_plan = json.loads((workspace / "deck_plan.json").read_text())
    expected_n = len(deck_plan["slides"])
    rm_files = sorted((workspace / "render_models").iterdir())
    if len(rm_files) != expected_n:
        errs.append(
            f"render_model count {len(rm_files)} != deck_plan slide "
            f"count {expected_n}"
        )

    if inventory.get("evidence_basis") != EXPECTED_EVIDENCE_BASIS:
        errs.append(
            f"inventory.evidence_basis={inventory.get('evidence_basis')!r} "
            f"!= expected {EXPECTED_EVIDENCE_BASIS!r}"
        )
    if not inventory.get("ok"):
        errs.append(
            f"inventory.ok=False; findings={inventory.get('findings')!r}"
        )
    if inventory.get("slide_count") != expected_n:
        errs.append(
            f"inventory.slide_count={inventory.get('slide_count')!r} "
            f"!= deck_plan slide count {expected_n}"
        )

    # Every slide row carries native shape evidence and is not image_only.
    for srow in inventory.get("slides", []):
        idx = srow.get("index")
        counts = srow.get("native_object_counts", {})
        sps = counts.get("shapes_sp", 0)
        cxs = counts.get("connectors_cxnSp", 0)
        if (sps + cxs) < 1:
            errs.append(
                f"slide {idx}: no <p:sp> or <p:cxnSp> (sps={sps}, "
                f"cxs={cxs}); fails not-blank / native-shape evidence"
            )
        if srow.get("image_only_evidence"):
            errs.append(
                f"slide {idx}: image_only_evidence=True (all-image slide)"
            )

    # Text / table / kpi content + shape geometry + line connector +
    # image_slot picture + image rels via direct ZIP readback. Mirrors
    # the exporter's emission:
    #   text       -> <a:t> run inside <p:sp> txBox
    #   line       -> <p:cxnSp> straight connector (prstGeom prst="line")
    #   shape      -> <p:sp> with <a:prstGeom>
    #   kpi        -> <p:sp> txBox stacked <a:p> paragraphs (label / value
    #                 / optional delta), each with <a:t>
    #   table      -> <p:graphicFrame> wrapping <a:tbl> with per-cell <a:t>
    #   image_slot -> <p:pic> with <a:blipFill r:embed="rIdN"/> when the
    #                 manifest entry is a PNG / JPG / JPEG; otherwise a
    #                 placeholder <p:sp> carrying the alt_text.
    # Pre-index the inventory's per-slide rows so the image_slot
    # per-primitive check can cross-look-up the matching slide's
    # media_refs list (the inventory attributes every image rel back to
    # its OWNER slide; a `<p:pic>` whose `r:embed` references an rId
    # that is NOT in this slide's rels file would surface here as an
    # empty / non-PNG / non-internal media_refs row rather than slip
    # through the package-level "some image rel exists" check).
    inv_slides_by_idx: dict[int, dict] = {}
    for srow in inventory.get("slides") or []:
        if isinstance(srow.get("index"), int):
            inv_slides_by_idx[srow["index"]] = srow

    found_any_line = False
    found_any_table = False
    found_any_kpi = False
    found_any_shape = False
    found_any_image_slot = False
    found_any_image_rel = False
    with zipfile.ZipFile(pptx, "r") as zf:
        names = set(zf.namelist())
        for rm_file in rm_files:
            rm = json.loads(rm_file.read_text())
            idx = rm["index"]
            slide_part = f"ppt/slides/slide{idx}.xml"
            if slide_part not in names:
                errs.append(
                    f"slide {idx}: {slide_part} missing from PPTX"
                )
                continue
            slide_xml = zf.read(slide_part).decode("utf-8")
            for prim in rm.get("primitives") or []:
                kind = prim.get("kind")
                if kind == "text":
                    content = (prim.get("text") or {}).get("content")
                    if isinstance(content, str) and content:
                        if content not in slide_xml:
                            errs.append(
                                f"slide {idx}: text {content!r} not present "
                                f"in {slide_part}"
                            )
                elif kind == "table":
                    if "<a:tbl>" not in slide_xml and "tbl" not in slide_xml:
                        errs.append(
                            f"slide {idx}: <a:tbl> missing from {slide_part}"
                        )
                    found_any_table = True
                    tbl = prim.get("table") or {}
                    for col in tbl.get("columns") or []:
                        if isinstance(col, str) and col and col not in slide_xml:
                            errs.append(
                                f"slide {idx}: table column {col!r} "
                                f"missing from {slide_part}"
                            )
                    for row in tbl.get("rows") or []:
                        for cell in row or []:
                            if isinstance(cell, str) and cell and cell not in slide_xml:
                                errs.append(
                                    f"slide {idx}: table cell {cell!r} "
                                    f"missing from {slide_part}"
                                )
                elif kind == "kpi":
                    found_any_kpi = True
                    kpi = prim.get("kpi") or {}
                    for field_name in ("label", "value", "delta"):
                        v = kpi.get(field_name)
                        if isinstance(v, str) and v and v not in slide_xml:
                            errs.append(
                                f"slide {idx}: kpi {field_name} {v!r} "
                                f"missing from {slide_part}"
                            )
                elif kind == "shape":
                    found_any_shape = True
                    # Shape primitives must emit a native <p:sp> with a
                    # prstGeom. The slide-level <p:sp> count is already
                    # covered by the not-blank check above; here we just
                    # confirm the prstGeom signal is present somewhere in
                    # this slide's XML so the shape is not silently demoted.
                    if "<a:prstGeom" not in slide_xml:
                        errs.append(
                            f"slide {idx}: shape primitive present but no "
                            f"<a:prstGeom> in {slide_part}"
                        )
                elif kind == "line":
                    found_any_line = True
                    # Line primitives must emit a native <p:cxnSp>
                    # straight connector with prstGeom prst="line". A
                    # regression that silently drops the line (e.g.,
                    # emits nothing or demotes to a 1-px <p:sp>
                    # rectangle) trips this check.
                    if "<p:cxnSp" not in slide_xml:
                        errs.append(
                            f"slide {idx}: line primitive present but no "
                            f"<p:cxnSp> connector in {slide_part}"
                        )
                    if 'prst="line"' not in slide_xml:
                        errs.append(
                            f"slide {idx}: line primitive present but no "
                            f'prstGeom prst="line" in {slide_part}'
                        )
                elif kind == "image_slot":
                    found_any_image_slot = True
                    # The fixture's manifest entry is a PNG, so the
                    # image_slot must embed as a native <p:pic> AND the
                    # slide's per-slide rels file must declare a
                    # matching internal /relationships/image rel that
                    # resolves to ppt/media/* and is actually used by
                    # a <a:blip r:embed/> reference in this slide
                    # (i.e. media_refs[*].used_by_slide_blip is True).
                    # A regression that emits <p:pic> with a dangling
                    # r:embed, or routes the rel through the
                    # presentation / master rels file instead of the
                    # slide's own, would slip past a package-level
                    # "some image rel exists" check — the inventory's
                    # per-slide media_refs row is the durable line.
                    if "<p:pic" not in slide_xml:
                        errs.append(
                            f"slide {idx}: image_slot (PNG manifest) "
                            f"primitive present but no <p:pic> in "
                            f"{slide_part}; exporter may have demoted "
                            f"to a placeholder shape"
                        )
                    inv_row = inv_slides_by_idx.get(idx)
                    if inv_row is None:
                        errs.append(
                            f"slide {idx}: image_slot present but the "
                            f"inventory has no row for this slide"
                        )
                    else:
                        media_refs = inv_row.get("media_refs") or []
                        internal_blip_refs = [
                            m for m in media_refs
                            if isinstance(m, dict)
                            and isinstance(m.get("resolved"), str)
                            and m["resolved"].startswith("ppt/media/")
                            and bool(m.get("used_by_slide_blip"))
                            and isinstance(m.get("target"), str)
                            and not any(
                                m["target"].lower().startswith(p)
                                for p in _FORBIDDEN_TARGET_PREFIXES
                            )
                        ]
                        if not internal_blip_refs:
                            errs.append(
                                f"slide {idx}: image_slot present but "
                                f"inventory.slides[{idx}].media_refs has "
                                f"no entry that (a) resolves to "
                                f"ppt/media/*, (b) is used by a slide "
                                f"<a:blip r:embed/>, AND (c) has an "
                                f"internal Target — media_refs="
                                f"{media_refs!r}"
                            )

        # Media + per-slide image relationships.
        media_parts = sorted(
            n for n in names
            if n.startswith("ppt/media/") and not n.endswith("/")
        )
        if not media_parts:
            errs.append(
                "no ppt/media/* parts in PPTX; image_slot PNG never "
                "embedded as native media"
            )
        for mp in media_parts:
            ext = mp.rsplit(".", 1)[-1].lower() if "." in mp else ""
            if ext not in {"png", "jpg", "jpeg"}:
                errs.append(
                    f"unexpected media extension {ext!r} for {mp}"
                )
        # Confirm at least one image relationship points at an internal
        # ppt/media/* part — via the inventory readback (which already
        # sorts + dedups rels for us).
        for r in inventory.get("relationships") or []:
            rtype = r.get("type", "")
            target = r.get("target", "")
            tmode = (r.get("target_mode") or "").lower()
            if rtype.endswith("/relationships/image"):
                found_any_image_rel = True
                if tmode == "external":
                    errs.append(
                        f"image relationship is external: {r!r}"
                    )
                if any(
                    isinstance(target, str)
                    and target.lower().startswith(p)
                    for p in _FORBIDDEN_TARGET_PREFIXES
                ):
                    errs.append(
                        f"image relationship has external Target: {r!r}"
                    )
        if not found_any_image_rel:
            errs.append(
                "no image relationship found in PPTX relationships"
            )

    if not found_any_line:
        # Fixture invariant: slide 1 carries a line primitive
        # (the cover title divider).
        errs.append(
            "fixture lost the line primitive before the assertion; "
            "expected at least one line in render_models/"
        )
    if not found_any_table:
        # Fixture invariant: slide 2 carries a table primitive.
        errs.append(
            "fixture lost the table primitive before the assertion; "
            "expected at least one table in render_models/"
        )
    if not found_any_image_slot:
        # Fixture invariant: slide 3 carries an image_slot primitive.
        errs.append(
            "fixture lost the image_slot primitive before the assertion; "
            "expected at least one image_slot in render_models/"
        )
    if not found_any_kpi:
        # Fixture invariant: slide 4 carries a kpi primitive.
        errs.append(
            "fixture lost the kpi primitive before the assertion; "
            "expected at least one kpi in render_models/"
        )
    if not found_any_shape:
        # Fixture invariant: slide 4 carries a shape primitive.
        errs.append(
            "fixture lost the shape primitive before the assertion; "
            "expected at least one shape in render_models/"
        )

    # No external / file:// / data: / http(s) Targets anywhere in the
    # package. Mirrors the inventory's own gate at the structured-readback
    # layer.
    for r in inventory.get("relationships") or []:
        target = r.get("target", "")
        tmode = (r.get("target_mode") or "").lower()
        if tmode == "external":
            errs.append(f"relationship has TargetMode=External: {r!r}")
        if any(
            isinstance(target, str)
            and target.lower().startswith(p)
            for p in _FORBIDDEN_TARGET_PREFIXES
        ):
            errs.append(
                f"relationship has external Target prefix: {r!r}"
            )

    return errs


# ---------------------------------------------------------------------------
# Negative probe outcomes.
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    name: str
    ok: bool
    detail: str = ""


def _expect_inventory_finding(
    pptx: Path, td: Path, finding_code: str, name: str,
) -> ProbeResult:
    out_json = td / f"inv_{name}.json"
    outcome = _inspect(pptx, out_json)
    if outcome.rc == 0:
        return ProbeResult(
            name=name, ok=False,
            detail=(
                f"inspect_pptx_inventory rc=0 (expected non-zero) for "
                f"finding {finding_code!r}; combined={outcome.combined[-300:]!r}"
            ),
        )
    if not out_json.is_file():
        return ProbeResult(
            name=name, ok=False,
            detail=f"inventory JSON {out_json} not written",
        )
    try:
        inv = json.loads(out_json.read_text())
    except Exception as exc:
        return ProbeResult(
            name=name, ok=False,
            detail=f"inventory JSON not parseable: {exc}",
        )
    codes = {f.get("code") for f in (inv.get("findings") or [])}
    if finding_code not in codes:
        return ProbeResult(
            name=name, ok=False,
            detail=(
                f"finding {finding_code!r} not present; got codes={codes!r}"
            ),
        )
    if inv.get("ok"):
        return ProbeResult(
            name=name, ok=False,
            detail="inventory.ok=True despite recorded findings",
        )
    return ProbeResult(name=name, ok=True)


# ---------------------------------------------------------------------------
# Negative probes.
# ---------------------------------------------------------------------------


def _probe_text_removed(positive_pptx: Path, ws: Path, td: Path) -> ProbeResult:
    name = "N1_text_removed"
    target = td / "neg_text_removed.pptx"
    shutil.copy(positive_pptx, target)
    # Slide 1 carries SLIDE1_TITLE in its <a:t>. Replace with a placeholder
    # that does NOT match the expected marker substring.
    sentinel = SLIDE1_TITLE.encode("utf-8")
    replacement = b"REPLACED-MARKER-NEG1"
    _mutate_zip_entry(
        target,
        "ppt/slides/slide1.xml",
        lambda body: body.replace(sentinel, replacement),
    )
    with zipfile.ZipFile(target) as zf:
        if sentinel in zf.read("ppt/slides/slide1.xml"):
            return ProbeResult(
                name=name, ok=False,
                detail="mutation did not actually remove the text marker",
            )
    # Re-run inventory to feed the assertion.
    inv_path = td / "inv_n1.json"
    out = _inspect(target, inv_path)
    inv: dict = {}
    if inv_path.is_file():
        try:
            inv = json.loads(inv_path.read_text())
        except Exception:
            inv = {}
    errs = _positive_assertions(pptx=target, inventory=inv, workspace=ws)
    hits = [e for e in errs if SLIDE1_TITLE in e]
    if not hits:
        return ProbeResult(
            name=name, ok=False,
            detail=(
                f"positive_assertions did not flag the missing text "
                f"marker; errs={errs!r}; inspect_rc={out.rc}"
            ),
        )
    return ProbeResult(name=name, ok=True)


def _probe_table_missing(positive_pptx: Path, ws: Path, td: Path) -> ProbeResult:
    name = "N2_table_missing"
    target = td / "neg_table_missing.pptx"
    shutil.copy(positive_pptx, target)
    # Drop a known table cell string from slide 2.
    drop_cell = TABLE_ROWS[0][0]  # "metric_alpha_row"
    sentinel = drop_cell.encode("utf-8")
    replacement = b"REPLACED-CELL-NEG2"
    _mutate_zip_entry(
        target,
        "ppt/slides/slide2.xml",
        lambda body: body.replace(sentinel, replacement),
    )
    with zipfile.ZipFile(target) as zf:
        if sentinel in zf.read("ppt/slides/slide2.xml"):
            return ProbeResult(
                name=name, ok=False,
                detail=(
                    "mutation did not actually remove the table cell marker"
                ),
            )
    inv_path = td / "inv_n2.json"
    _inspect(target, inv_path)
    inv: dict = {}
    if inv_path.is_file():
        try:
            inv = json.loads(inv_path.read_text())
        except Exception:
            inv = {}
    errs = _positive_assertions(pptx=target, inventory=inv, workspace=ws)
    hits = [e for e in errs if drop_cell in e]
    if not hits:
        return ProbeResult(
            name=name, ok=False,
            detail=(
                f"positive_assertions did not flag the missing table "
                f"cell; errs={errs!r}"
            ),
        )
    return ProbeResult(name=name, ok=True)


def _probe_external_image_rel(positive_pptx: Path, td: Path) -> ProbeResult:
    name = "N3_external_image_rel"
    target = td / "neg_external_rel.pptx"
    shutil.copy(positive_pptx, target)
    # Slide 3 carries the per-slide image relationship.
    rels_part = "ppt/slides/_rels/slide3.xml.rels"
    with zipfile.ZipFile(target) as zf:
        if rels_part not in zf.namelist():
            return ProbeResult(
                name=name, ok=False,
                detail=f"{rels_part} not present in positive PPTX",
            )

    def _make_external(body: bytes) -> bytes:
        s = body.decode("utf-8")
        # Replace the internal Target with an external URL. The exporter
        # writes Target="../media/image1.png" — patch the value
        # in-place without disturbing any other attributes.
        s = s.replace(
            'Target="../media/image1.png"',
            'Target="http://attacker.example/img.png"',
        )
        return s.encode("utf-8")

    _mutate_zip_entry(target, rels_part, _make_external)
    return _expect_inventory_finding(
        target, td, "relationships.external", name,
    )


def _probe_orphan_media(positive_pptx: Path, td: Path) -> ProbeResult:
    name = "N4_orphan_media"
    target = td / "neg_orphan_media.pptx"
    shutil.copy(positive_pptx, target)
    # Add an unreferenced PNG part under ppt/media/. It carries no
    # matching <Relationship Type="image"/> anywhere, so the inventory
    # walker must fire media.orphan.
    _add_zip_entry(target, "ppt/media/orphan_extra.png", _TINY_PNG_BYTES)
    return _expect_inventory_finding(
        target, td, "media.orphan", name,
    )


def _probe_missing_media(positive_pptx: Path, td: Path) -> ProbeResult:
    name = "N5_missing_media"
    target = td / "neg_missing_media.pptx"
    shutil.copy(positive_pptx, target)
    with zipfile.ZipFile(target) as zf:
        names = set(zf.namelist())
    media_part = "ppt/media/image1.png"
    if media_part not in names:
        return ProbeResult(
            name=name, ok=False,
            detail=f"positive PPTX is missing {media_part}",
        )
    _drop_zip_entry(target, media_part)
    return _expect_inventory_finding(
        target, td, "media.missing", name,
    )


def _probe_slide_count_drift(positive_pptx: Path, td: Path) -> ProbeResult:
    name = "N6_slide_count_drift"
    # Run the contract validator with the WRONG expected count.
    # The positive PPTX has 4 slides; ask for 99.
    outcome = _validate_contract(positive_pptx, expected_slide_count=99)
    if outcome.rc == 0:
        return ProbeResult(
            name=name, ok=False,
            detail=(
                f"validate_pptx_contract.py rc=0 with wrong "
                f"--expected-slide-count=99; combined="
                f"{outcome.combined[-300:]!r}"
            ),
        )
    if "slide_count.expected" not in outcome.combined:
        return ProbeResult(
            name=name, ok=False,
            detail=(
                f"slide_count.expected diagnostic missing from "
                f"output; tail={outcome.combined[-300:]!r}"
            ),
        )
    return ProbeResult(name=name, ok=True)


def _probe_unsupported_primitive(td: Path) -> ProbeResult:
    name = "N7a_unsupported_primitive"
    ws = td / "n7a_workspace"
    _write_workspace(ws)
    # Replace slide 1's primitives with a single unsupported
    # `chart_placeholder` primitive. The exporter must fail closed at
    # preflight (no .pptx written).
    rm_path = ws / "render_models" / "01_cover.json"
    rm = json.loads(rm_path.read_text())
    rm["primitives"] = [{
        "id": "chart_probe",
        "kind": "chart_placeholder",
        "bounds": {"x": 100, "y": 100, "w": 400, "h": 300},
        "chart_placeholder": {"chart_kind": "bar"},
    }]
    rm_path.write_text(json.dumps(rm, indent=2, sort_keys=True) + "\n")
    out_pptx = td / "n7a.pptx"
    outcome = _export(ws, out_pptx)
    if outcome.rc == 0:
        return ProbeResult(
            name=name, ok=False,
            detail=(
                f"export_pptx.py rc=0 despite chart_placeholder primitive; "
                f"combined={outcome.combined[-300:]!r}"
            ),
        )
    if out_pptx.is_file():
        return ProbeResult(
            name=name, ok=False,
            detail=f"export wrote {out_pptx} despite the fail-closed gate",
        )
    if "chart_placeholder" not in outcome.combined:
        return ProbeResult(
            name=name, ok=False,
            detail=(
                f"chart_placeholder diagnostic missing from output; "
                f"tail={outcome.combined[-300:]!r}"
            ),
        )
    return ProbeResult(name=name, ok=True)


def _probe_unsafe_image_ref(td: Path) -> ProbeResult:
    name = "N7b_unsafe_image_ref"
    ws = td / "n7b_workspace"
    _write_workspace(ws)
    manifest_path = ws / "image_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    # Replace the safe local_path with a file:// URI. The manifest
    # preflight in export_pptx must refuse this with a clear diagnostic.
    manifest["images"][0]["local_path"] = "file:///etc/passwd"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    out_pptx = td / "n7b.pptx"
    outcome = _export(ws, out_pptx)
    if outcome.rc == 0:
        return ProbeResult(
            name=name, ok=False,
            detail=(
                f"export_pptx.py rc=0 despite file:// local_path; "
                f"combined={outcome.combined[-300:]!r}"
            ),
        )
    if out_pptx.is_file():
        return ProbeResult(
            name=name, ok=False,
            detail=f"export wrote {out_pptx} despite the unsafe path gate",
        )
    return ProbeResult(name=name, ok=True)


# ---------------------------------------------------------------------------
# Self-test orchestration.
# ---------------------------------------------------------------------------


def _run_positive(td: Path) -> tuple[int, Path | None, Path | None]:
    """Run the positive path under ``td``. Returns
    ``(rc, pptx_path, workspace_path)`` so negative probes can re-use
    the produced .pptx without re-running export."""
    ws = td / "positive_workspace"
    _write_workspace(ws)
    pptx = td / "positive.pptx"
    print("  [..] export_pptx.py against synthetic 4-slide workspace")
    out = _export(ws, pptx)
    if out.rc != 0:
        print(
            f"\nFAIL: positive export rc={out.rc}; stdout={out.stdout!r}; "
            f"stderr={out.stderr!r}",
            file=sys.stderr,
        )
        return 1, None, None
    if not pptx.is_file():
        print(
            f"\nFAIL: positive export rc=0 but {pptx} not on disk",
            file=sys.stderr,
        )
        return 1, None, None
    print("  [OK] export produced .pptx")

    inv_path = td / "positive_inventory.json"
    print("  [..] inspect_pptx_inventory.py against produced .pptx")
    out_inv = _inspect(pptx, inv_path)
    if out_inv.rc != 0:
        print(
            f"\nFAIL: positive inventory rc={out_inv.rc}; combined="
            f"{out_inv.combined!r}",
            file=sys.stderr,
        )
        return 1, None, None
    try:
        inv = json.loads(inv_path.read_text())
    except Exception as exc:
        print(
            f"\nFAIL: inventory JSON not parseable: {exc}",
            file=sys.stderr,
        )
        return 1, None, None
    print("  [OK] inventory parses + ok=True")

    print("  [..] cross-validate every positive assertion against PPTX")
    errs = _positive_assertions(
        pptx=pptx, inventory=inv, workspace=ws,
    )
    if errs:
        print(
            f"\nFAIL: positive assertions did not hold:",
            file=sys.stderr,
        )
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1, None, None
    print(
        "  [OK] slide_count matches deck_plan; every slide carries "
        "native shape evidence; text + table cell + kpi field content "
        "present; line primitive emits <p:cxnSp> + prst=\"line\"; "
        "shape primitive emits <a:prstGeom>; image_slot PNG embeds as "
        "native <p:pic> AND the image-slot slide's own media_refs row "
        "carries an internal ppt/media/* target used by a <a:blip "
        "r:embed/> in that same slide; no external/file:// "
        "relationships"
    )

    print(
        "  [..] validate_pptx_contract.py --expected-slide-count=4"
    )
    out_val = _validate_contract(pptx, expected_slide_count=4)
    if out_val.rc != 0:
        print(
            f"\nFAIL: validate_pptx_contract rc={out_val.rc}; combined="
            f"{out_val.combined!r}",
            file=sys.stderr,
        )
        return 1, None, None
    print("  [OK] container + minimal-evidence + slide_count.expected pass")
    return 0, pptx, ws


def _run_negatives(positive_pptx: Path, positive_ws: Path, td: Path) -> int:
    probes: list[ProbeResult] = []
    print("  [..] N1 expected text evidence removed")
    probes.append(_probe_text_removed(positive_pptx, positive_ws, td))
    print("  [..] N2 expected table cell evidence missing")
    probes.append(_probe_table_missing(positive_pptx, positive_ws, td))
    print("  [..] N3 image relationship rewritten as external http://")
    probes.append(_probe_external_image_rel(positive_pptx, td))
    print("  [..] N4 unreferenced ppt/media/ part (orphan)")
    probes.append(_probe_orphan_media(positive_pptx, td))
    print("  [..] N5 referenced ppt/media/image1.png removed (missing)")
    probes.append(_probe_missing_media(positive_pptx, td))
    print("  [..] N6 validate_pptx_contract slide_count.expected mismatch")
    probes.append(_probe_slide_count_drift(positive_pptx, td))
    print("  [..] N7a render_model with chart_placeholder primitive")
    probes.append(_probe_unsupported_primitive(td))
    print("  [..] N7b image_manifest local_path = file:// URI")
    probes.append(_probe_unsafe_image_ref(td))

    rc = 0
    for p in probes:
        marker = "[OK]" if p.ok else "[FAIL]"
        line = f"  {marker} {p.name}"
        if p.detail:
            line = f"{line}  ({p.detail})"
        print(line, file=sys.stderr if not p.ok else sys.stdout)
        if not p.ok:
            rc = 1
    return rc


def _run_self_test() -> int:
    print(
        "=== render_model_roundtrip_smoke "
        "(synthetic 4-slide fixture, fail-closed probes) ==="
    )
    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    scripts_before = _snapshot_dir(REPO_ROOT / "scripts")

    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        rc, pptx, ws = _run_positive(td)
        if rc != 0:
            return _check_repo_unchanged(
                examples_before, scripts_before,
            ) or rc
        assert pptx is not None and ws is not None  # narrowed by rc==0
        rc = _run_negatives(pptx, ws, td)

    repo_rc = _check_repo_unchanged(examples_before, scripts_before)
    if rc == 0 and repo_rc == 0:
        print()
        print(
            "OK (self-test): synthetic workspace exports cleanly; the "
            "produced PPTX passes validate_pptx_contract + inspect_pptx_"
            "inventory; every authored text primitive, line <p:cxnSp>, "
            "table cell, kpi label/value/delta, shape <a:prstGeom>, and "
            "PNG image_slot <p:pic> manifests in the package as native "
            "editable OOXML across the cover / comparison_table / "
            "two_column / kpi_dashboard layouts; every documented "
            "fail-closed gate (text / table / external-rel / orphan-"
            "media / missing-media / slide-count / chart_placeholder / "
            "unsafe image local_path) fires on its perturbation. The "
            "smoke is not proof of full PowerPoint editability — see "
            "references for the open TODO surface."
        )
    return rc or repo_rc


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stdlib-only, local-only render_model -> PPTX round-trip "
            "acceptance smoke. Reuses scripts/export_pptx.py + "
            "scripts/validate_pptx_contract.py + "
            "scripts/inspect_pptx_inventory.py against a synthetic "
            "4-slide workspace generated under "
            "tempfile.TemporaryDirectory(). No D-One, no MCP, no Qoder, "
            "no public network, no telemetry, no model API, no image "
            "search, no browser screenshot, no animation, no audio, "
            "no video, and no upstream assets / wording / prompts / "
            "templates from /Users/robert/ppt-master."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run the synthetic-workspace round-trip positives plus the "
            "documented fail-closed negative probes (N1..N7b) under "
            "tempfile.TemporaryDirectory(). The smoke has no other "
            "CLI surface today; --self-test is required."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: render_model_roundtrip_smoke.py requires --self-test "
            "(no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
