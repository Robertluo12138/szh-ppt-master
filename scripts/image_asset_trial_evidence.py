#!/usr/bin/env python3
"""Image-asset trial evidence emitter for the mock/local image -> PPTX path.

Single-purpose, tempdir-only evidence layer over the already-passing
``scripts/image_asset_acceptance_smoke.py`` chain. Runs the same chain
end-to-end (``done_image_adapter`` -> ``run_d_one_generation`` (mock,
synthetic bytes) -> ``materialize_image_assets`` -> staging workspace
fed as ``--assets-dir`` to ``run_explicit_pipeline.py``) and, instead
of asserting against post-conditions only, also captures the evidence
into a small structured JSON file under the tempdir's report
directory. The goal is to make the current mock image-asset capability
reviewable by a human without reading many self-test logs.

NOT real D-One integration. The synthetic PNG bytes come from the
in-script mock provider in ``scripts/run_d_one_generation.py
--allow-synthetic-bytes`` — no MCP, no public network, no model API,
no image search, no Qoder. The emitted evidence JSON states this
explicitly under ``notes.real_d_one_status``.

What the JSON evidence records (every value is observed under
``tempfile.TemporaryDirectory()``, never read from / written to the
repo):

  - ``pptx.path`` / ``pptx.exists`` / ``pptx.size_bytes`` — the final
    deck path under the tempdir, its existence as a regular non-
    symlink file, and its size in bytes;
  - ``pptx.media_parts`` — sorted list of ``ppt/media/*`` ZIP entries
    whose lower-cased extension is one of ``.png`` / ``.jpg`` /
    ``.jpeg`` (the embed surface ``scripts/export_pptx.py`` supports
    today);
  - ``pptx.has_internal_image_relationship`` — True iff at least one
    ``*.rels`` Relationship in the package has
    ``Type=...relationships/image`` and a Target that resolves inside
    the package (no URI scheme, no ``TargetMode="External"``);
  - ``pptx.external_relationships`` — list of any external / file:// /
    data: / URI-scheme relationships found (must be empty);
  - ``validators.validate_pptx_contract`` / ``validators.inspect_pptx
    _inventory`` — ``{"rc": <int>, "ok": <bool>}`` for the belt-and-
    braces validators (PPTX contract validator with ``--expected-
    slide-count``, inventory inspector against the produced deck);
  - ``inventory.ok`` / ``inventory.findings`` / ``inventory.slide_
    count`` / ``inventory.media_parts_count`` /
    ``inventory.evidence_basis`` — selected fields from
    ``<report-dir>/inventory.json``;
  - ``editability.every_slide_has_native_shape`` / ``editability.not_
    all_image`` / ``editability.editable_text`` — derived from
    ``validate_pptx_contract.py``'s ``minimal_evidence.*`` checks
    (proves the deck still carries native editable structure and is
    not all-image);
  - ``visual_quality.path`` / ``visual_quality.exists`` /
    ``visual_quality.parses_as_json`` — proof
    ``<report-dir>/visual_quality.json`` (written by the pipeline's
    own non-mutating visual-quality validator) landed on disk and
    parses;
  - ``notes.real_d_one_status`` — fixed sentence stating real D-One
    remains UNVERIFIED and uncalled;
  - ``summary.ok`` — True iff every observed gate above held.

The PASS print at the end carries the evidence JSON path; the JSON
contents are also dumped to stdout so a reviewer can read them
without recovering the tempdir.

Snapshot check: ``REPO_ROOT/examples/`` and ``REPO_ROOT/scripts/`` are
byte-snapshotted before the run and re-snapshotted after; either tree
mutating aborts the script non-zero. Mirrors
``scripts/image_asset_negative_probes_smoke.py``'s repo-immutability
gate.

Stdlib-only. NETWORK-FREE. NO real D-One. NO MCP. NO Qoder. NO model
API. NO image search. NO telemetry. NOT a full prompt/report/
Markdown-to-PPTX automation — this script composes the existing mock
chain and records what it produced; it does not extend any pipeline
stage and does not extract source content.

Usage:
  python3 scripts/image_asset_trial_evidence.py --self-test
"""
from __future__ import annotations

import sys

# Refuse to write `.pyc` files for any module imported by this script.
# The repo-immutability snapshot below baselines `REPO_ROOT/scripts/`
# AFTER `main()` starts, so without this gate the smoke module import
# silently lands `scripts/__pycache__/image_asset_acceptance_smoke
# .cpython-*.pyc` on a clean checkout BEFORE the snapshot fires, and
# the gate misses the write entirely. PYTHONDONTWRITEBYTECODE=1 in
# the env achieves the same thing for callers that remember the prefix,
# but the in-script flip closes the hole unconditionally. Must come
# BEFORE the smoke import — the interpreter checks the flag at
# bytecode-write time.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import zipfile  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402
from xml.etree import ElementTree as ET  # noqa: E402

# Reuse the already-passing mock chain verbatim. Importing the smoke
# module instead of duplicating bundle / staging / pipeline-invoke
# logic keeps the evidence layer surgical: any future change to the
# chain only needs to land in one place, and this script picks it up
# for free.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import image_asset_acceptance_smoke as smoke  # noqa: E402

REPO_ROOT = smoke.REPO_ROOT
SCRIPTS_DIR = smoke.SCRIPTS_DIR
TEMPLATE_ROOT = smoke.TEMPLATE_ROOT

# Same OOXML relationship namespace + URI-scheme regex the smoke uses;
# we re-derive them locally so the evidence reader stays self-contained
# if the smoke ever renames an internal.
_NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_IMAGE_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/"
    "relationships/image"
)
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_EMBEDDABLE_MEDIA_EXTS: tuple[str, ...] = (".png", ".jpg", ".jpeg")

# Exact framing string the inventory must carry — re-exported from the
# inspector via the smoke module. We pin it here so a drift in either
# script surfaces in the evidence JSON.
EXPECTED_EVIDENCE_BASIS = smoke.EXPECTED_EVIDENCE_BASIS

# Schema framing for the evidence file. Bump only when the field set
# changes. Internal to this script — no separate schema file today.
EVIDENCE_SCHEMA_VERSION = "1"
EVIDENCE_FILENAME = "image_asset_trial_evidence.json"

REAL_D_ONE_STATUS = (
    "UNVERIFIED — real D-One is NOT called by this evidence script. The "
    "PNG bytes embedded in the produced PPTX come from the in-script "
    "mock provider in scripts/run_d_one_generation.py "
    "(--allow-synthetic-bytes), not from any external service. No MCP, "
    "no public network, no model API, no image search, no Qoder."
)


# ---------------------------------------------------------------------------
# Subprocess helper.
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


def _run_tool(name: str, cmd: list[str]) -> ToolOutcome:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    return ToolOutcome(
        name=name,
        cmd=cmd,
        rc=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
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
# Evidence collection.
# ---------------------------------------------------------------------------


def _collect_pptx_evidence(pptx: Path) -> dict:
    """Open the PPTX as a ZIP and record media parts + relationship
    shape. The classifier mirrors
    ``image_asset_acceptance_smoke._check_pptx_embeds_internal_media_only``
    but emits structured fields instead of pass/fail booleans only."""
    is_file = pptx.is_file() and not pptx.is_symlink()
    out: dict = {
        "path": str(pptx),
        "exists": is_file,
        "size_bytes": pptx.stat().st_size if is_file else 0,
        "media_parts": [],
        "has_internal_image_relationship": False,
        "external_relationships": [],
    }
    if not is_file:
        return out
    with zipfile.ZipFile(pptx, "r") as zf:
        names = zf.namelist()
        out["media_parts"] = sorted(
            n for n in names
            if n.startswith("ppt/media/")
            and Path(n).suffix.lower() in _EMBEDDABLE_MEDIA_EXTS
        )
        has_internal_image_rel = False
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
                rtype = el.attrib.get("Type", "")
                is_external = bool(
                    (mode and mode != "Internal")
                    or _URI_SCHEME_PREFIX.match(target or "")
                )
                if is_external:
                    external.append(
                        f"{n}: id={el.attrib.get('Id')!r} "
                        f"TargetMode={mode!r} Target={target!r}"
                    )
                    continue
                if rtype == _IMAGE_REL_TYPE and target:
                    has_internal_image_rel = True
        out["has_internal_image_relationship"] = has_internal_image_rel
        out["external_relationships"] = external
    return out


def _collect_inventory_evidence(
    inventory_path: Path, *, expected_slide_count: int,
) -> dict:
    """Read ``<report-dir>/inventory.json`` and return the subset of
    fields the trial evidence reports on, plus pass/fail booleans for
    each gate so reviewers do not have to re-derive them."""
    out: dict = {
        "path": str(inventory_path),
        "exists": False,
        "parses_as_json": False,
        "ok": None,
        "findings": None,
        "slide_count": None,
        "media_parts_count": None,
        "evidence_basis": None,
        "evidence_basis_matches": False,
        "slide_count_matches_plan": False,
        "media_parts_non_empty": False,
        "findings_empty": False,
    }
    if not (inventory_path.is_file() and not inventory_path.is_symlink()):
        return out
    out["exists"] = True
    try:
        inv = json.loads(inventory_path.read_text())
    except (json.JSONDecodeError, OSError):
        return out
    out["parses_as_json"] = True
    out["ok"] = inv.get("ok")
    out["findings"] = inv.get("findings")
    out["slide_count"] = inv.get("slide_count")
    mp = inv.get("media_parts")
    out["media_parts_count"] = len(mp) if isinstance(mp, list) else None
    out["evidence_basis"] = inv.get("evidence_basis")
    out["evidence_basis_matches"] = (
        inv.get("evidence_basis") == EXPECTED_EVIDENCE_BASIS
    )
    out["slide_count_matches_plan"] = (
        inv.get("slide_count") == expected_slide_count
    )
    out["media_parts_non_empty"] = (
        isinstance(mp, list) and len(mp) > 0
    )
    out["findings_empty"] = inv.get("findings") == []
    return out


def _collect_visual_quality_evidence(report_dir: Path) -> dict:
    """Confirm ``<report-dir>/visual_quality.json`` was emitted by the
    pipeline's own visual-quality validator and parses as JSON. The
    file's deep semantics are out of scope for this evidence layer —
    we only prove it lands."""
    vq = report_dir / "visual_quality.json"
    out: dict = {
        "path": str(vq),
        "exists": vq.is_file() and not vq.is_symlink(),
        "parses_as_json": False,
    }
    if out["exists"]:
        try:
            json.loads(vq.read_text())
            out["parses_as_json"] = True
        except (json.JSONDecodeError, OSError):
            out["parses_as_json"] = False
    return out


def _editability_from_contract_output(combined: str) -> dict:
    """Walk validate_pptx_contract.py stdout for the three
    ``minimal_evidence.*`` markers that prove the deck still carries
    native editable structure and is NOT all-image. The validator
    prints one ``PASS`` / ``FAIL`` line per check; we grep them so the
    evidence reader does not have to re-parse the contract report."""
    out: dict = {
        "editable_text": None,
        "not_all_image": None,
        "no_blank_slide": None,
        "every_slide_has_native_shape": None,
    }
    for line in (combined or "").splitlines():
        for key in out:
            if f"minimal_evidence.{key}" in line:
                # validate_pptx_contract prints "[PASS] " or "[FAIL] "
                # at the start of each result line.
                if "[PASS]" in line:
                    out[key] = True
                elif "[FAIL]" in line:
                    out[key] = False
    return out


# ---------------------------------------------------------------------------
# Snapshot helpers — repo-immutability gate. Mirrors
# scripts/image_asset_negative_probes_smoke.py::_snapshot_dir.
# ---------------------------------------------------------------------------


def _snapshot_dir(dir_path: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    if not dir_path.is_dir():
        return snapshot
    for p in sorted(dir_path.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(dir_path)
        snapshot[str(rel)] = p.read_bytes()
    return snapshot


def _diff_keys(
    before: dict[str, bytes], after: dict[str, bytes],
) -> list[str]:
    return [
        k for k in sorted(set(before) | set(after))
        if before.get(k) != after.get(k)
    ]


def _check_repo_unchanged(
    examples_before: dict[str, bytes],
    scripts_before: dict[str, bytes],
) -> tuple[bool, list[str], list[str]]:
    """Return ``(unchanged, examples_changed, scripts_changed)``."""
    examples_changed = _diff_keys(
        examples_before, _snapshot_dir(REPO_ROOT / "examples"),
    )
    scripts_changed = _diff_keys(
        scripts_before, _snapshot_dir(REPO_ROOT / "scripts"),
    )
    return (
        not examples_changed and not scripts_changed,
        examples_changed,
        scripts_changed,
    )


# ---------------------------------------------------------------------------
# Trial runner.
# ---------------------------------------------------------------------------


def _summary_ok(evidence: dict) -> bool:
    """Single boolean: every observed gate held."""
    p = evidence["pptx"]
    if not (p["exists"] and p["size_bytes"] > 0):
        return False
    if not p["media_parts"]:
        return False
    if not p["has_internal_image_relationship"]:
        return False
    if p["external_relationships"]:
        return False
    if not evidence["validators"]["validate_pptx_contract"]["ok"]:
        return False
    if not evidence["validators"]["inspect_pptx_inventory"]["ok"]:
        return False
    if not evidence["validators"]["validate_visual_quality"]["ok"]:
        return False
    inv = evidence["inventory"]
    if not (inv["exists"] and inv["parses_as_json"] and inv["ok"] is True):
        return False
    if not (
        inv["findings_empty"]
        and inv["slide_count_matches_plan"]
        and inv["media_parts_non_empty"]
        and inv["evidence_basis_matches"]
    ):
        return False
    ed = evidence["editability"]
    if not (
        ed["every_slide_has_native_shape"] is True
        and ed["not_all_image"] is True
        and ed["editable_text"] is True
    ):
        return False
    vq = evidence["visual_quality"]
    if not (vq["exists"] and vq["parses_as_json"]):
        return False
    return True


def _run_trial(td: Path) -> tuple[dict, list[ToolOutcome]]:
    """Execute the mock chain inside ``td``, gather evidence, and
    return ``(evidence_dict, chain_outcomes)``. Raises ``RuntimeError``
    on any chain step exiting non-zero (so the caller can short-circuit
    and still write the partial evidence)."""
    bundle = smoke._materialize_bundle(td)

    # Staging workspace + d_one chain (mock provider).
    d_one_assets = td / "d_one_assets"
    d_one_assets.mkdir()
    staging = smoke._build_staging_workspace(td, source=bundle["source"])
    chain_outcomes = smoke._run_d_one_chain_in_staging(
        staging=staging,
        assets_dir=d_one_assets,
        done_image_adapter_spec=bundle["done_image_adapter_spec"],
    )
    if not all(o.ok for o in chain_outcomes):
        raise RuntimeError("d_one chain (mock) did not all pass")

    # Production workspace + explicit pipeline + auto inventory write.
    workspace = td / "workspace"
    output = td / "deck.pptx"
    report_dir = td / "report"
    rxp_outcome = smoke._invoke_run_explicit_pipeline(
        workspace=workspace,
        bundle=bundle,
        staging=staging,
        output=output,
        report_dir=report_dir,
    )
    smoke._print_stage(rxp_outcome)
    if not rxp_outcome.ok:
        raise RuntimeError(
            f"run_explicit_pipeline did not succeed (rc={rxp_outcome.exit_code})"
        )

    # Belt-and-braces validators. validate_pptx_contract runs with
    # --expected-slide-count so the slide_count.expected gate fires;
    # inspect_pptx_inventory is re-invoked directly (the pipeline's
    # auto-write into <report-dir>/inventory.json already happened,
    # but re-running proves the inspector CLI is exercisable as a
    # standalone gate too); validate_visual_quality writes
    # <report-dir>/visual_quality.json the same way the existing
    # image_asset_acceptance_smoke does it.
    expected_slide_count = len(smoke._plan_spec()["slides"])
    contract = _run_tool(
        "validate_pptx_contract",
        [
            sys.executable, str(SCRIPTS_DIR / "validate_pptx_contract.py"),
            "--pptx", str(output),
            "--expected-slide-count", str(expected_slide_count),
        ],
    )
    _print_outcome(contract)
    inspect = _run_tool(
        "inspect_pptx_inventory",
        [
            sys.executable, str(SCRIPTS_DIR / "inspect_pptx_inventory.py"),
            "--pptx", str(output),
        ],
    )
    _print_outcome(inspect)
    visual_quality = _run_tool(
        "validate_visual_quality",
        [
            sys.executable, str(SCRIPTS_DIR / "validate_visual_quality.py"),
            "--workspace", str(workspace),
            "--output", str(report_dir / "visual_quality.json"),
        ],
    )
    _print_outcome(visual_quality)

    inventory_path = report_dir / "inventory.json"
    evidence: dict = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_id": "image_asset_trial_evidence",
        "pptx": _collect_pptx_evidence(output),
        "validators": {
            "validate_pptx_contract": {
                "rc": contract.rc,
                "ok": contract.ok,
            },
            "inspect_pptx_inventory": {
                "rc": inspect.rc,
                "ok": inspect.ok,
            },
            "validate_visual_quality": {
                "rc": visual_quality.rc,
                "ok": visual_quality.ok,
            },
        },
        "inventory": _collect_inventory_evidence(
            inventory_path, expected_slide_count=expected_slide_count,
        ),
        "editability": _editability_from_contract_output(
            contract.stdout + contract.stderr,
        ),
        "visual_quality": _collect_visual_quality_evidence(report_dir),
        "expected_slide_count": expected_slide_count,
        "report_dir": str(report_dir),
        "notes": {
            "real_d_one_status": REAL_D_ONE_STATUS,
            "scope": (
                "Mock/local image asset -> editable PPTX evidence only. "
                "Not a new product feature, not real D-One, not Qoder, "
                "not a public-network run, not telemetry, not a "
                "prompt/report-to-PPTX automation."
            ),
            "embed_surface": (
                "PNG/JPG/JPEG inside ppt/media/* — the subset "
                "scripts/export_pptx.py supports today. Anything outside "
                "that subset is fail-closed by the exporter."
            ),
        },
    }
    evidence["summary"] = {"ok": _summary_ok(evidence)}
    return evidence, chain_outcomes


# ---------------------------------------------------------------------------
# CLI / self-test entry point.
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    print("=== image-asset trial evidence (mock D-One chain) ===")

    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    scripts_before = _snapshot_dir(REPO_ROOT / "scripts")

    with tempfile.TemporaryDirectory(
        prefix="szh_image_asset_trial_evidence_",
    ) as raw_td:
        td = Path(raw_td)
        report_dir = td / "report"
        evidence_path = report_dir / EVIDENCE_FILENAME

        print(f"  tempdir:        {td}")
        print(f"  report dir:     {report_dir}")
        print(f"  evidence path:  {evidence_path}")
        print()

        print("--- mock chain + pipeline ---")
        try:
            evidence, _chain_outcomes = _run_trial(td)
        except RuntimeError as exc:
            print(f"\nFAIL: trial chain aborted: {exc}", file=sys.stderr)
            return 1
        print()

        # Ensure the report directory exists before writing the
        # evidence JSON. run_explicit_pipeline already creates it when
        # --report-dir is supplied, so this is belt-and-braces.
        report_dir.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        )

        print("--- evidence JSON ---")
        print(f"  written: {evidence_path}")
        print(f"  bytes:   {evidence_path.stat().st_size}")
        print()
        print("--- evidence JSON contents ---")
        print(evidence_path.read_text())
        print()

        # Final repo-immutability gate. Runs INSIDE the tempdir
        # context so any artifact we forgot to redirect is still
        # caught while the tempdir is alive.
        unchanged, ex_changed, sc_changed = _check_repo_unchanged(
            examples_before, scripts_before,
        )
        if not unchanged:
            print(
                f"FAIL: repo tree mutated during trial: "
                f"examples_changed={ex_changed!r} "
                f"scripts_changed={sc_changed!r}",
                file=sys.stderr,
            )
            return 1
        print(
            "  [PASS] REPO_ROOT/examples/ and REPO_ROOT/scripts/ "
            "byte-snapshots unchanged."
        )
        print()

        if not evidence["summary"]["ok"]:
            print(
                "FAIL: evidence summary.ok is False; see the JSON dump "
                "above for the failing fields.",
                file=sys.stderr,
            )
            return 1

        print(
            f"PASS: image-asset trial evidence emitted at "
            f"{evidence_path}. MOCK / local chain only — real D-One "
            f"remains UNVERIFIED and uncalled by this evidence script."
        )
        return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Emit a small structured JSON evidence file for the "
            "current mock/local image asset -> editable PPTX path. "
            "Runs the existing image_asset_acceptance_smoke chain in a "
            "tempdir, records what the produced .pptx + report dir "
            "look like (media parts, internal-only relationships, "
            "PPTX contract result, inventory result, native editable "
            "shape evidence, visual_quality.json presence), and writes "
            "the evidence JSON under the tempdir's report directory. "
            "MOCK / local only — NOT real D-One; no MCP, no public "
            "network, no model API, no image search, no Qoder."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run the trial chain under tempfile.TemporaryDirectory(), "
            "collect evidence, write <tempdir>/report/"
            + EVIDENCE_FILENAME + ", print PASS + the evidence path, "
            "and assert REPO_ROOT/examples/ + REPO_ROOT/scripts/ are "
            "byte-snapshot unchanged. This script has no production "
            "CLI surface today; --self-test is required."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: image_asset_trial_evidence.py requires --self-test "
            "(no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
