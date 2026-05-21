#!/usr/bin/env python3
"""image_asset_negative_probes_smoke.py

Focused fail-closed acceptance smoke for the image-asset pipeline.
The companion of ``scripts/image_asset_acceptance_smoke.py``: that
smoke proves the mockable D-One-stub chain SUCCEEDS end-to-end and
emits a native editable PPTX with an internal ``ppt/media/*`` image;
this smoke proves every documented fail-closed gate FIRES on the
documented perturbations of the same baseline, so a regression that
silently demotes a gate (or accepts attacker-shaped input) is loud.

Each probe runs under its own ``tempfile.TemporaryDirectory()``. The
smoke writes nothing under ``REPO_ROOT/`` — a flat-bytes snapshot of
``REPO_ROOT/examples/`` and ``REPO_ROOT/scripts/`` (the two
git-tracked surfaces a misbehaving probe would be most likely to
clobber) taken before and after the run must match.

Probes (every probe expects rc != 0 from its target tool AND every
named expected diagnostic substring to appear in stdout/stderr; if
the gate is documented as also writing nothing, the smoke verifies
that too):

  P1  missing image file
        materialize_image_assets refuses when the manifest-declared
        target file is absent from both the workspace AND the
        assets-dir.

  P2  wrong magic bytes
        materialize_image_assets refuses when an assets-dir file
        carries the right extension but plain-text bytes (no PNG /
        JPEG magic header).

  P3  image_manifest id mismatched with slide_plan image_ref
        init_image_manifest refuses when ``--spec`` declares image
        ids that do not cover the slide_plan ``image_refs`` set.

  P4  external URL / file:// / data: / .. / absolute local_path
        materialize_image_assets refuses every unsafe local_path
        (``http://...``, ``file://...``, ``data:...``, ``../...``,
        ``/abs/...``). The same gate is also enforced by
        init_image_manifest (the schema permits a string of any
        shape; the helper's path-safety scan is the durable gate).

  P5a symlinked target file
        materialize_image_assets refuses when
        ``<workspace>/<local_path>`` is a symlink (broken or
        resolvable). The leaf symlink check fires before the
        ``_resolves_within`` gate so the diagnostic names the
        symlink reason, not the generic 'escapes workspace' reason.

  P5b symlinked parent directory
        materialize_image_assets refuses when any intermediate
        segment between ``<workspace>`` and the target is a symlink.
        Mirrors the parent-walk gate the helper applies before any
        ``mkdir(parents=True, exist_ok=True)`` call.

  P6  public upload / share / hosting wording in prompt
        done_image_adapter refuses prompts containing
        ``upload to public`` / ``public upload`` / ``share publicly``
        / ``public hosting`` / ``publish to web`` / ``public url`` /
        ``public link`` / ``public cdn`` / ``host publicly`` and the
        documented variants. A D-One asset is local-only.

  P7  credential-shaped string in prompt
        done_image_adapter refuses prompts containing AWS access-key
        / JWT / PEM marker / bearer-token / ``password:`` /
        ``api_key:`` / ``secret:`` literals.

MOCK / STUB ACCEPTANCE — NOT real D-One integration. The smoke
never calls D-One, MCP, Qoder, a public network, telemetry, any
model API, an image search, or any external service. Real D-One
integration remains intentionally TODO; this smoke proves the
fail-closed CONTRACT around the local mock chain, not photographic
quality.

Snapshot check: every scenario runs under
``tempfile.TemporaryDirectory()``; a flat-bytes snapshot of
``REPO_ROOT/examples/`` taken before and after the run must match.

Fail-closed: any probe whose gate does NOT fire as documented (rc
== 0, or rc != 0 but the expected diagnostic substring is missing,
or the documented no-write post-condition is violated) aborts the
smoke immediately and the script exits non-zero with a clear
per-probe diagnostic.

Stdlib-only.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
TEMPLATE_ROOT = REPO_ROOT / "templates" / "layouts"

SYNTHETIC_SOURCE_ID = "synthetic_image_negative_probes_source"
SYNTHETIC_TITLE = "Image Asset Negative Probes Smoke"
SYNTHETIC_AUDIENCE = "Internal pipeline smoke reviewers"
SYNTHETIC_OBJECTIVE = (
    "Exercise the fail-closed image-asset gates against documented "
    "perturbations of a synthetic, non-sensitive narrative."
)
SYNTHETIC_TONE = "neutral-professional"
SYNTHETIC_LANGUAGE = "en"
SYNTHETIC_APPROXIMATE_SLIDE_COUNT = 2
SYNTHETIC_TEMPLATE = "business_review"
SYNTHETIC_IMAGE_ID = "cover_accent"
SYNTHETIC_IMAGE_LOCAL_PATH = "media/cover_accent.png"
SYNTHETIC_IMAGE_ALT_TEXT = "Synthetic abstract pattern (mock D-One output)."

# Minimal valid PNG byte payload (8-byte signature + IHDR + IDAT + IEND
# for a 1x1 transparent image). Mirrors the run_d_one_generation stub
# output so the magic-byte gate downstream cannot tell the smoke from a
# legitimate stub-generated asset. NOT photographically meaningful.
_PNG_1X1: bytes = bytes.fromhex(
    "89504e470d0a1a0a"  # PNG signature
    "0000000d49484452"  # IHDR chunk header
    "0000000100000001"  # 1x1
    "08060000001f15c489"
    "0000000d49444154"  # IDAT chunk header
    "789c6300010000000500010d0a2db4"
    "0000000049454e44ae426082"  # IEND chunk
)


# ---------------------------------------------------------------------------
# Snapshot helpers — proves the smoke writes nothing under REPO_ROOT.
# ---------------------------------------------------------------------------


def _snapshot_dir(dir_path: Path) -> dict[str, bytes]:
    """Flat path -> bytes map of every regular file under ``dir_path``.
    Same shape as scripts/acceptance_smoke.py::_snapshot_dir so the
    no-mutation invariant is asserted with the same gate."""
    snapshot: dict[str, bytes] = {}
    if not dir_path.is_dir():
        return snapshot
    for p in sorted(dir_path.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(dir_path)
        snapshot[str(rel)] = p.read_bytes()
    return snapshot


def _check_repo_unchanged(
    examples_before: dict[str, bytes],
    scripts_before: dict[str, bytes],
) -> int:
    """Re-snapshot the two committed surfaces a misbehaving probe is
    most likely to clobber. The smoke aborts non-zero if either
    snapshot drifted (a regression that wrote under REPO_ROOT/ instead
    of under the probe's tempdir)."""
    rc = 0
    examples_after = _snapshot_dir(REPO_ROOT / "examples")
    if examples_before != examples_after:
        changed = [
            k for k in sorted(set(examples_before) | set(examples_after))
            if examples_before.get(k) != examples_after.get(k)
        ]
        print(
            f"FAIL: examples/ was mutated by the smoke "
            f"(changed paths: {changed!r}). Every probe must run under "
            f"tempfile.TemporaryDirectory().",
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
            f"(changed paths: {changed!r}). Every probe must run under "
            f"tempfile.TemporaryDirectory().",
            file=sys.stderr,
        )
        rc = 1
    return rc


# ---------------------------------------------------------------------------
# Subprocess runner. Returns (rc, combined_stdout_stderr) per call so each
# probe can grep for the expected diagnostic without re-running.
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


def _run_tool(cmd: list[str]) -> ToolOutcome:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    return ToolOutcome(
        cmd=cmd,
        rc=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


# ---------------------------------------------------------------------------
# Per-probe state.
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    name: str
    ok: bool
    detail: str = ""


def _expect_fail_closed(
    name: str,
    outcome: ToolOutcome,
    *,
    expected_substrings: list[str],
    forbidden_paths: list[Path] | None = None,
) -> ProbeResult:
    """Generic fail-closed assertion: rc != 0 AND every expected
    substring is in stdout+stderr AND every forbidden path does NOT
    exist on disk after the call returns. The smoke captures all
    failure detail so a regression report names exactly which gate
    silently demoted."""
    forbidden_paths = forbidden_paths or []
    detail_lines: list[str] = []
    if outcome.rc == 0:
        detail_lines.append(
            f"rc=0 (expected non-zero); cmd={outcome.cmd!r}"
        )
    missing = [s for s in expected_substrings if s not in outcome.combined]
    if missing:
        detail_lines.append(
            f"expected diagnostic substring(s) {missing!r} not found in "
            f"output; tail={outcome.combined.splitlines()[-12:]!r}"
        )
    leaked: list[str] = []
    for p in forbidden_paths:
        try:
            if p.exists() or p.is_symlink():
                leaked.append(str(p))
        except OSError:
            leaked.append(f"{p} (stat raised)")
    if leaked:
        detail_lines.append(
            f"forbidden post-state: paths exist that should not "
            f"({leaked!r}) — the gate did not fail-closed cleanly"
        )
    ok = not detail_lines
    return ProbeResult(name=name, ok=ok, detail="; ".join(detail_lines))


# ---------------------------------------------------------------------------
# Synthetic bundle (shared across probes that need a Stage-5 context). The
# bundle is materialized into the probe's tempdir; nothing is read from
# committed examples/.
# ---------------------------------------------------------------------------


def _source_md_text() -> str:
    return (
        "# Synthetic Image Asset Negative Probes Source\n\n"
        "This document is synthetic. It contains no real company, "
        "product, customer, or financial data.\n\n"
        "It exists only to exercise the fail-closed gates around the "
        "image-asset pipeline.\n"
    )


def _plan_spec_body() -> dict:
    return {
        "template": SYNTHETIC_TEMPLATE,
        "planning": {
            "planned_slide_count": 2,
            "rationale": (
                "Two-slide synthetic deck: a cover with an accent image "
                "ref plus a conclusion. The image_ref is the carrier the "
                "negative probes perturb."
            ),
        },
        "sections": [
            {
                "id": "open",
                "title": "Open",
                "summary": "Cover with accent image.",
                "slide_indices": [1],
            },
            {
                "id": "close",
                "title": "Close",
                "summary": "Conclusion.",
                "slide_indices": [2],
            },
        ],
        "slides": [
            {
                "index": 1,
                "layout": "cover",
                "title": SYNTHETIC_TITLE,
                "section_id": "open",
                "summary": "Cover with a synthetic accent image.",
                "density": "low",
                "source_refs": [SYNTHETIC_SOURCE_ID],
            },
            {
                "index": 2,
                "layout": "conclusion",
                "title": "Smoke Outcome",
                "section_id": "close",
                "summary": "Synthetic smoke test outcome.",
                "density": "low",
                "source_refs": [SYNTHETIC_SOURCE_ID],
            },
        ],
    }


def _design_system_spec_body() -> dict:
    return {
        "palette": {
            "primary": "#264653",
            "secondary": "#2A9D8F",
            "accent": "#E9C46A",
            "background": "#FFFFFF",
            "text": "#1A1A1A",
        },
        "typography": {
            "heading": {
                "font_family": "Calibri, Helvetica Neue, Arial, sans-serif",
                "size_pt": 28,
            },
            "body": {
                "font_family": "Calibri, Helvetica Neue, Arial, sans-serif",
                "size_pt": 14,
            },
        },
        "grid": {"width_px": 1920, "height_px": 1080, "margin_px": 64},
    }


def _slide_spec_cover_body() -> dict:
    return {
        "index": 1,
        "layout": "cover",
        "title": SYNTHETIC_TITLE,
        "subtitle": "Negative probes smoke",
        "blocks": [
            {"id": "title", "kind": "text", "content": SYNTHETIC_TITLE},
            {"id": "subtitle", "kind": "text", "content": "Negative probes smoke"},
            {"id": "presenter", "kind": "text", "content": "Synthetic Reviewer"},
            {"id": "date", "kind": "text", "content": "Synthetic window"},
            {"id": "accent", "kind": "image_ref", "content": SYNTHETIC_IMAGE_ID},
        ],
        "image_refs": [SYNTHETIC_IMAGE_ID],
        "notes": "Synthetic.",
    }


def _slide_spec_conclusion_body() -> dict:
    return {
        "index": 2,
        "layout": "conclusion",
        "title": "Smoke Outcome",
        "blocks": [
            {"id": "title", "kind": "text", "content": "Smoke Outcome"},
            {
                "id": "summary",
                "kind": "text",
                "content": (
                    "Synthetic negative-probes smoke; every gate trips on "
                    "its perturbation."
                ),
            },
        ],
    }


def _image_manifest_body(*, image_id: str = SYNTHETIC_IMAGE_ID,
                         local_path: str = SYNTHETIC_IMAGE_LOCAL_PATH) -> dict:
    return {
        "images": [
            {
                "id": image_id,
                "local_path": local_path,
                "source": "d_one_local",
                "alt_text": SYNTHETIC_IMAGE_ALT_TEXT,
                "intended_use": "spot illustration",
            },
        ],
    }


def _write_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")


def _materialize_stage5_workspace(td: Path) -> Path:
    """Run init_workspace -> init_deck_brief -> init_deck_plan ->
    init_design_system -> init_slide_plans under ``td/workspace`` and
    return the workspace path. Raises if any stage fails (a Stage-5
    setup failure is a smoke harness bug, not a probe failure)."""
    bundle = td / "bundle"
    bundle.mkdir(parents=True)
    source = bundle / "source.md"
    source.write_text(_source_md_text())
    _write_json(bundle / "plan_spec.json", _plan_spec_body())
    _write_json(bundle / "design_system_spec.json", _design_system_spec_body())
    slide_specs_dir = bundle / "slide_specs"
    slide_specs_dir.mkdir()
    _write_json(slide_specs_dir / "01_cover.json", _slide_spec_cover_body())
    _write_json(
        slide_specs_dir / "02_conclusion.json", _slide_spec_conclusion_body(),
    )

    workspace = td / "workspace"
    py = sys.executable

    init_workspace = _run_tool([
        py, str(SCRIPTS_DIR / "init_workspace.py"),
        "--workspace", str(workspace),
        "--source", str(source),
        "--source-id", SYNTHETIC_SOURCE_ID,
    ])
    if init_workspace.rc != 0:
        raise RuntimeError(
            f"init_workspace failed: rc={init_workspace.rc}\n"
            f"stderr: {init_workspace.stderr}"
        )

    init_deck_brief = _run_tool([
        py, str(SCRIPTS_DIR / "init_deck_brief.py"),
        "--workspace", str(workspace),
        "--title", SYNTHETIC_TITLE,
        "--audience", SYNTHETIC_AUDIENCE,
        "--objective", SYNTHETIC_OBJECTIVE,
        "--tone", SYNTHETIC_TONE,
        "--language", SYNTHETIC_LANGUAGE,
        "--approximate-slide-count", str(SYNTHETIC_APPROXIMATE_SLIDE_COUNT),
    ])
    if init_deck_brief.rc != 0:
        raise RuntimeError(
            f"init_deck_brief failed: rc={init_deck_brief.rc}\n"
            f"stderr: {init_deck_brief.stderr}"
        )

    init_deck_plan = _run_tool([
        py, str(SCRIPTS_DIR / "init_deck_plan.py"),
        "--workspace", str(workspace),
        "--plan-spec", str(bundle / "plan_spec.json"),
    ])
    if init_deck_plan.rc != 0:
        raise RuntimeError(
            f"init_deck_plan failed: rc={init_deck_plan.rc}\n"
            f"stderr: {init_deck_plan.stderr}"
        )

    init_design_system = _run_tool([
        py, str(SCRIPTS_DIR / "init_design_system.py"),
        "--workspace", str(workspace),
        "--spec", str(bundle / "design_system_spec.json"),
    ])
    if init_design_system.rc != 0:
        raise RuntimeError(
            f"init_design_system failed: rc={init_design_system.rc}\n"
            f"stderr: {init_design_system.stderr}"
        )

    init_slide_plans = _run_tool([
        py, str(SCRIPTS_DIR / "init_slide_plans.py"),
        "--workspace", str(workspace),
        "--template-root", str(TEMPLATE_ROOT),
        "--specs-dir", str(slide_specs_dir),
    ])
    if init_slide_plans.rc != 0:
        raise RuntimeError(
            f"init_slide_plans failed: rc={init_slide_plans.rc}\n"
            f"stderr: {init_slide_plans.stderr}"
        )
    return workspace


def _seed_minimal_workspace_for_materialize(
    td: Path, *, manifest: dict, place_target: bytes | None,
) -> tuple[Path, Path]:
    """Build a minimal materialize-target workspace under
    ``td/workspace``:

      - ``image_manifest.json`` hand-written from ``manifest`` (a dict
        already in the schema-valid shape — no schema patching here).
      - Optionally place ``place_target`` bytes at
        ``<workspace>/<images[0].local_path>`` (the verify-only branch
        of materialize); if ``place_target`` is None the target is
        intentionally left missing so the apply branch fires.
      - An empty ``assets-dir`` next to the workspace under
        ``td/assets`` — the caller is free to drop bytes into it
        before invoking materialize.

    Returns ``(workspace, assets_dir)``."""
    workspace = td / "workspace"
    workspace.mkdir(parents=True)
    _write_json(workspace / "image_manifest.json", manifest)
    if place_target is not None:
        images = manifest.get("images") or []
        if images:
            local_path = images[0]["local_path"]
            target = workspace / local_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(place_target)
    assets_dir = td / "assets"
    assets_dir.mkdir()
    return workspace, assets_dir


def _seed_minimal_workspace_for_done_adapter(
    td: Path,
) -> Path:
    """Build a minimal done_image_adapter-target workspace under
    ``td/workspace``: only ``image_manifest.json`` is required (no
    Stage-1-5 prereqs)."""
    workspace = td / "workspace"
    workspace.mkdir(parents=True)
    _write_json(workspace / "image_manifest.json", _image_manifest_body())
    return workspace


# ---------------------------------------------------------------------------
# Probes.
# ---------------------------------------------------------------------------


def _probe_missing_image_file() -> ProbeResult:
    """P1: materialize_image_assets refuses when neither
    <workspace>/<local_path> NOR <assets-dir>/<id>.<ext> exists."""
    with tempfile.TemporaryDirectory(
        prefix="szh_neg_p1_missing_",
    ) as raw_td:
        td = Path(raw_td)
        workspace, assets_dir = _seed_minimal_workspace_for_materialize(
            td, manifest=_image_manifest_body(), place_target=None,
        )
        # Workspace target is intentionally missing AND the assets-dir is
        # empty -> materialize's per-image gate ("source file under
        # --assets-dir must exist as a regular non-symlink file") fires.
        outcome = _run_tool([
            sys.executable, str(SCRIPTS_DIR / "materialize_image_assets.py"),
            "--workspace", str(workspace),
            "--assets-dir", str(assets_dir),
        ])
        return _expect_fail_closed(
            "P1: missing image file -> materialize refuses",
            outcome,
            expected_substrings=[
                "FAIL",
                "cover_accent.png",
            ],
            forbidden_paths=[workspace / SYNTHETIC_IMAGE_LOCAL_PATH],
        )


def _probe_wrong_magic_bytes() -> ProbeResult:
    """P2: materialize_image_assets refuses when the assets-dir source
    file has a .png extension but plain-text bytes."""
    with tempfile.TemporaryDirectory(
        prefix="szh_neg_p2_magic_",
    ) as raw_td:
        td = Path(raw_td)
        workspace, assets_dir = _seed_minimal_workspace_for_materialize(
            td, manifest=_image_manifest_body(), place_target=None,
        )
        # assets-dir keys are <id>.<ext> at the directory root.
        bad = assets_dir / f"{SYNTHETIC_IMAGE_ID}.png"
        bad.write_bytes(b"this is not a PNG; plain ASCII text only\n")
        outcome = _run_tool([
            sys.executable, str(SCRIPTS_DIR / "materialize_image_assets.py"),
            "--workspace", str(workspace),
            "--assets-dir", str(assets_dir),
        ])
        return _expect_fail_closed(
            "P2: wrong magic bytes -> materialize refuses",
            outcome,
            expected_substrings=[
                "FAIL",
                "magic",
            ],
            forbidden_paths=[workspace / SYNTHETIC_IMAGE_LOCAL_PATH],
        )


def _probe_id_mismatch() -> ProbeResult:
    """P3: init_image_manifest refuses when --spec declares image ids
    that do not cover the slide_plan ``image_refs`` set. The cover
    layout's slide_plan declares ``image_refs=[cover_accent]``; the
    bad spec declares only ``other_accent``."""
    with tempfile.TemporaryDirectory(
        prefix="szh_neg_p3_idmismatch_",
    ) as raw_td:
        td = Path(raw_td)
        workspace = _materialize_stage5_workspace(td)
        # Drop a target file at the slide_plan-referenced local_path so
        # init_image_manifest's "local_path must resolve to an existing
        # regular file" gate is NOT the one that fires — the cross-check
        # ("slide_plan image_ref must appear in images[].id") is what we
        # want to prove. The mismatched spec declares a DIFFERENT id and
        # a DIFFERENT local_path, so the slide_plan-referenced id never
        # appears.
        target = workspace / SYNTHETIC_IMAGE_LOCAL_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_PNG_1X1)
        other_target = workspace / "media/other_accent.png"
        other_target.parent.mkdir(parents=True, exist_ok=True)
        other_target.write_bytes(_PNG_1X1)
        bad_spec = td / "image_manifest_spec_bad.json"
        _write_json(bad_spec, _image_manifest_body(
            image_id="other_accent",
            local_path="media/other_accent.png",
        ))
        outcome = _run_tool([
            sys.executable, str(SCRIPTS_DIR / "init_image_manifest.py"),
            "--workspace", str(workspace),
            "--spec", str(bad_spec),
        ])
        return _expect_fail_closed(
            "P3: id mismatch (slide_plan image_ref vs spec id) -> "
            "init_image_manifest refuses",
            outcome,
            expected_substrings=[
                "FAIL",
                "cover_accent",
            ],
            forbidden_paths=[workspace / "image_manifest.json"],
        )


def _probe_unsafe_local_path(local_path: str, label: str) -> ProbeResult:
    """P4 (parameterised): materialize_image_assets refuses every
    documented unsafe ``local_path`` shape — ``http://...``,
    ``file://...``, ``data:...``, ``../...``, ``/abs/...``. The schema
    permits ANY non-empty string, so this is the helper's gate, not
    a schema gate. Each call uses a fresh tempdir."""
    with tempfile.TemporaryDirectory(
        prefix=f"szh_neg_p4_unsafe_",
    ) as raw_td:
        td = Path(raw_td)
        workspace, assets_dir = _seed_minimal_workspace_for_materialize(
            td,
            manifest=_image_manifest_body(local_path=local_path),
            place_target=None,
        )
        outcome = _run_tool([
            sys.executable, str(SCRIPTS_DIR / "materialize_image_assets.py"),
            "--workspace", str(workspace),
            "--assets-dir", str(assets_dir),
        ])
        # The materialize gate's diagnostic mentions either path-safety
        # or unsupported-extension depending on the perturbation. Both
        # are valid fail-closed outcomes; the smoke accepts any of the
        # documented per-image diagnostic strings as proof.
        ok_substrings = [
            "FAIL",
            local_path,
        ]
        return _expect_fail_closed(
            f"P4: unsafe local_path {label!r} ({local_path!r}) -> "
            f"materialize refuses",
            outcome,
            expected_substrings=ok_substrings,
        )


def _probe_symlinked_target() -> ProbeResult:
    """P5a: materialize_image_assets refuses when
    ``<workspace>/<local_path>`` is itself a symlink (broken or
    resolvable). The leaf symlink gate runs BEFORE the
    ``_resolves_within`` check, so the diagnostic names the symlink
    explicitly."""
    with tempfile.TemporaryDirectory(
        prefix="szh_neg_p5a_symlink_target_",
    ) as raw_td:
        td = Path(raw_td)
        workspace, assets_dir = _seed_minimal_workspace_for_materialize(
            td, manifest=_image_manifest_body(), place_target=None,
        )
        elsewhere = td / "elsewhere.png"
        elsewhere.write_bytes(_PNG_1X1)
        target = workspace / SYNTHETIC_IMAGE_LOCAL_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(elsewhere)
        outcome = _run_tool([
            sys.executable, str(SCRIPTS_DIR / "materialize_image_assets.py"),
            "--workspace", str(workspace),
            "--assets-dir", str(assets_dir),
        ])
        # The leaf is still a symlink after the helper returns — the
        # smoke does NOT assert the symlink was removed (the helper's
        # contract is fail-closed, not cleanup).
        return _expect_fail_closed(
            "P5a: symlinked target file -> materialize refuses",
            outcome,
            expected_substrings=[
                "FAIL",
                "symlink",
            ],
        )


def _probe_symlinked_parent() -> ProbeResult:
    """P5b: materialize_image_assets refuses when an intermediate
    segment between ``<workspace>`` and the target is a symlink."""
    with tempfile.TemporaryDirectory(
        prefix="szh_neg_p5b_symlink_parent_",
    ) as raw_td:
        td = Path(raw_td)
        # Manifest declares local_path = "decoy/cover_accent.png" so the
        # workspace-internal segment "decoy" can be a symlink to another
        # directory in td/ — the helper's parent-walk gate must refuse it.
        bad_local_path = "decoy/cover_accent.png"
        workspace, assets_dir = _seed_minimal_workspace_for_materialize(
            td,
            manifest=_image_manifest_body(local_path=bad_local_path),
            place_target=None,
        )
        real_decoy = td / "real_decoy"
        real_decoy.mkdir()
        (real_decoy / "cover_accent.png").write_bytes(_PNG_1X1)
        (workspace / "decoy").symlink_to(real_decoy)
        outcome = _run_tool([
            sys.executable, str(SCRIPTS_DIR / "materialize_image_assets.py"),
            "--workspace", str(workspace),
            "--assets-dir", str(assets_dir),
        ])
        return _expect_fail_closed(
            "P5b: symlinked parent directory -> materialize refuses",
            outcome,
            expected_substrings=[
                "FAIL",
                "symlink",
            ],
        )


def _probe_public_distribution_wording(phrase: str) -> ProbeResult:
    """P6 (parameterised): done_image_adapter refuses prompts
    containing public-distribution wording. Each phrase is in
    done_image_adapter._PROMPT_PUBLIC_DISTRIBUTION_LITERALS."""
    with tempfile.TemporaryDirectory(
        prefix="szh_neg_p6_public_",
    ) as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_workspace_for_done_adapter(td)
        spec = td / "spec.json"
        _write_json(spec, {
            "requests": [
                {
                    "id": SYNTHETIC_IMAGE_ID,
                    "prompt": (
                        f"abstract pattern, then {phrase} after build"
                    ),
                },
            ],
        })
        outcome = _run_tool([
            sys.executable, str(SCRIPTS_DIR / "done_image_adapter.py"),
            "--workspace", str(workspace),
            "--spec", str(spec),
        ])
        return _expect_fail_closed(
            f"P6: public-distribution wording {phrase!r} -> "
            f"done_image_adapter refuses",
            outcome,
            expected_substrings=[
                "FAIL",
                "public-distribution wording",
            ],
            forbidden_paths=[workspace / "d_one_adapter_plan.json"],
        )


def _probe_credential_in_prompt(label: str, payload: str) -> ProbeResult:
    """P7 (parameterised): done_image_adapter refuses prompts
    containing credential-shaped substrings. ``label`` is the
    human-readable name (used in the probe label only); ``payload`` is
    the substring inserted into the prompt verbatim."""
    with tempfile.TemporaryDirectory(
        prefix="szh_neg_p7_cred_",
    ) as raw_td:
        td = Path(raw_td)
        workspace = _seed_minimal_workspace_for_done_adapter(td)
        spec = td / "spec.json"
        _write_json(spec, {
            "requests": [
                {
                    "id": SYNTHETIC_IMAGE_ID,
                    "prompt": (
                        f"abstract pattern with caption {payload} embedded"
                    ),
                },
            ],
        })
        outcome = _run_tool([
            sys.executable, str(SCRIPTS_DIR / "done_image_adapter.py"),
            "--workspace", str(workspace),
            "--spec", str(spec),
        ])
        return _expect_fail_closed(
            f"P7: credential-shaped {label!r} in prompt -> "
            f"done_image_adapter refuses",
            outcome,
            expected_substrings=[
                "FAIL",
                "safety scan",
            ],
            forbidden_paths=[workspace / "d_one_adapter_plan.json"],
        )


# ---------------------------------------------------------------------------
# Self-test entry point.
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    """Run every probe under its own ``tempfile.TemporaryDirectory()``
    and return 0 iff every probe's documented gate fired as expected."""
    print("=== image-asset negative-probes smoke (mock chain only) ===")
    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    scripts_before = _snapshot_dir(REPO_ROOT / "scripts")

    results: list[ProbeResult] = []

    print("--- P1 missing image file ---")
    results.append(_probe_missing_image_file())

    print("--- P2 wrong magic bytes ---")
    results.append(_probe_wrong_magic_bytes())

    print("--- P3 image_manifest id mismatch vs slide_plan image_ref ---")
    try:
        results.append(_probe_id_mismatch())
    except RuntimeError as exc:
        results.append(ProbeResult(
            "P3: id mismatch -> init_image_manifest refuses",
            False,
            f"Stage-5 setup itself failed: {exc}",
        ))

    print("--- P4 unsafe local_path shapes ---")
    for label, path in (
        ("http URL", "http://example.com/x.png"),
        ("https URL", "https://example.com/x.png"),
        ("file URL", "file:///etc/passwd"),
        ("data URI", "data:image/png;base64,AAAA"),
        ("parent traversal", "../escape.png"),
        ("posix absolute", "/etc/passwd"),
    ):
        results.append(_probe_unsafe_local_path(path, label))

    print("--- P5a symlinked target ---")
    results.append(_probe_symlinked_target())

    print("--- P5b symlinked parent directory ---")
    results.append(_probe_symlinked_parent())

    print("--- P6 public-distribution wording ---")
    for phrase in (
        "upload to public hosting",
        "public upload",
        "share publicly",
        "publish to web",
    ):
        results.append(_probe_public_distribution_wording(phrase))

    print("--- P7 credential-shaped strings ---")
    for label, payload in (
        ("AWS access key", "AKIAABCDEFGHIJKLMNOP"),
        ("JWT", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc12345"),
        ("PEM marker", "-----BEGIN PRIVATE KEY-----"),
        ("bearer token", "Bearer abcdef0123456789"),
        ("password literal", "password: hunter2"),
    ):
        results.append(_probe_credential_in_prompt(label, payload))

    print()
    print("--- probe results ---")
    fails = 0
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        suffix = f" -- {r.detail}" if not r.ok and r.detail else ""
        print(f"  [{mark}] {r.name}{suffix}")
        if not r.ok:
            fails += 1
    print()

    rc_snapshot = _check_repo_unchanged(examples_before, scripts_before)
    if fails or rc_snapshot != 0:
        print(
            f"FAIL: {fails} probe(s) did not fire as documented; "
            f"snapshot rc={rc_snapshot}.",
            file=sys.stderr,
        )
        return 1
    print(
        "OK (self-test): image-asset negative-probes smoke passed. "
        "MOCK chain only — real D-One remains UNVERIFIED and uncalled."
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Image-asset negative-probes acceptance smoke: exercises "
            "every required fail-closed gate around the local mock "
            "D-One-stub chain (missing image file; wrong magic bytes; "
            "image_manifest id mismatched with slide_plan image_ref; "
            "external URL / file:// / data: / .. / absolute local_path; "
            "symlinked asset or symlinked parent; public upload/share/"
            "hosting wording in done_image_adapter prompt; "
            "credential-shaped string in done_image_adapter prompt). "
            "Each probe runs under its own tempfile.TemporaryDirectory() "
            "and the smoke confirms REPO_ROOT/examples/ + "
            "REPO_ROOT/scripts/ byte-snapshots are unchanged on success. "
            "MOCK / stub acceptance only — NOT real D-One integration; "
            "no MCP, no public network, no model API, no image search, "
            "no Qoder, no external service."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run every probe and verify each gate fires as documented. "
            "The smoke has no other mode today; --self-test is required."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: image_asset_negative_probes_smoke.py requires "
            "--self-test (no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
