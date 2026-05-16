#!/usr/bin/env python3
"""Image-asset acceptance smoke for the mockable D-One-stub chain.

Exercises the controlled D-One adapter chain end-to-end against the
intended explicit-input acceptance path, without calling real D-One.
The chain wired here is:

  d_one_local image_manifest entries (hand-written into a *staging*
    workspace per the *direct-author workflow* documented at
    scripts/materialize_image_assets.py:14–47)
      -> scripts/done_image_adapter.py   (writes d_one_adapter_plan.json
           into the staging workspace)
      -> scripts/run_d_one_generation.py (mock provider:
           --allow-synthetic-bytes; produces magic-byte-valid PNG / JPG
           / JPEG bytes named <id>.<ext> in a flat staging assets
           directory)
      -> scripts/materialize_image_assets.py (copy branch:
           flat-assets-dir bytes -> staging-workspace/<local_path>)

  -> scripts/run_explicit_pipeline.py with ``--assets-dir <staging>``
     against a *fresh* production workspace + the same d_one_local
     bundle. The staging workspace already carries the materialized
     bytes at ``<staging>/<local_path>``, so passing it as the
     ``--assets-dir`` lets ``prepare_workspace.py`` insert the
     materialize_image_assets step between Stage 5 (init_slide_plans)
     and Stage 6 (init_image_manifest) — it copies
     ``<staging>/<local_path>`` into ``<workspace>/<local_path>`` for
     every ``images[].local_path`` declared in
     ``--image-manifest-spec``. Stage 6 then finds the bytes on disk
     and the cascade continues all the way through Stage 10. The
     successful path is one ``run_explicit_pipeline.py`` invocation
     with rc=0 — no expected failure, no fallback to
     ``scripts/run_pipeline.py``.

  -> scripts/validate_pptx_contract.py --pptx <out.pptx>
       --expected-slide-count N (belt-and-braces direct re-validation)
  -> scripts/validate_visual_quality.py --workspace <workspace>
       --output <report-dir>/visual_quality.json (non-mutating visual
       review against the prepared workspace; the deterministic JSON
       report is persisted alongside the pipeline reports so the smoke
       leaves a reviewable artifact, not just stdout)
  -> inventory_post_conditions (asserted against
       ``<report-dir>/inventory.json`` written by
       ``run_explicit_pipeline.py`` via ``scripts/run_pipeline.py``'s
       own ``inspect_pptx_inventory`` stage — the smoke never invokes
       ``run_pipeline.py`` itself)

**MOCK / STUB ACCEPTANCE ONLY — NOT real D-One integration.** Real
D-One / MCP / model-API integration is intentionally TODO; nothing in
this script calls D-One, Qoder, a public network, telemetry, any model
API, an image search, or any external service. The D-One generator
boundary ``scripts/run_d_one_generation.py`` operates in synthetic-
bytes mode (a fixed minimal payload per declared extension); the bytes
are never derived from ``input/source.md`` and never claim to be
photographically meaningful. The smoke proves the *contract chain*
holds, not the photographic quality of any real generator.

Why the staging dance:

  * ``init_workspace`` (Stage 1, inside ``run_explicit_pipeline``)
    requires the production workspace to be empty or not yet exist —
    so asset bytes cannot be pre-positioned at
    ``<workspace>/<local_path>`` before Stage 1 fires;
  * ``init_image_manifest`` (Stage 6) requires every declared
    ``local_path`` to resolve to an existing regular file under the
    workspace — so the bytes must already be at
    ``<workspace>/<local_path>`` before Stage 6 fires.

  ``run_explicit_pipeline.py --assets-dir <staging>`` bridges those
  two constraints: the orchestrator inserts a deterministic
  materialize_image_assets step between Stage 5 and Stage 6 that
  copies the caller-staged bytes from
  ``<assets-dir>/<local_path>`` (= ``<staging>/<local_path>``) into
  ``<workspace>/<local_path>``. The smoke produces those bytes in a
  *separate* staging workspace via the d_one chain only so the chain
  itself (done_image_adapter -> run_d_one_generation ->
  materialize_image_assets) keeps being exercised end-to-end; the
  staging workspace itself is never fed back into
  ``run_explicit_pipeline.py``.

Post-conditions (asserted only after every chain step passes):

  - the final ``.pptx`` exists as a regular non-symlink file and is
    non-empty;
  - the same ``.pptx`` re-validates against the contract validator
    with ``--expected-slide-count = len(deck_plan.slides)``;
  - the PPTX (as a ZIP) carries at least one part under ``ppt/media/``
    whose lower-cased extension is one of ``.png`` / ``.jpg`` /
    ``.jpeg`` — proof the D-One synthetic bytes were embedded as
    native PowerPoint media (not falling back to a placeholder shape,
    and not living outside the package);
  - the PPTX has no external / file:// / data: relationships — every
    relationship's Target is either internal (no scheme prefix) and
    no ``<Relationship TargetMode='External'/>`` is emitted;
  - ``<report-dir>/inventory.json`` parses, carries ``ok == True``,
    ``findings == []``, ``slide_count == len(deck_plan.slides)``,
    ``len(media_parts) > 0``, and ``evidence_basis`` exactly equals
    the documented line
    ``"OOXML structure only; not proof of full PowerPoint editability"``;
  - ``<report-dir>/visual_quality.json`` exists as a regular
    non-symlink file under the report directory and parses as JSON.

Snapshot check: every scenario runs under
``tempfile.TemporaryDirectory()``; a flat-bytes snapshot of
``REPO_ROOT/examples/`` taken before and after the run must match —
proves no generated artifact lands in any committed example directory.

Static check: at startup the smoke confirms its own source file does
NOT mention ``run_pipeline.py`` (substring match). That static gate is
the durable proof that the successful path never invokes
``scripts/run_pipeline.py`` as a fallback / substitute — the only
pipeline runner this smoke knows about is
``scripts/run_explicit_pipeline.py``.

Fail-closed: any chain step exiting non-zero, or any post-condition
failing, aborts the smoke immediately and the script exits non-zero
with a clear per-step / per-assertion diagnostic.

Stdlib-only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
TEMPLATE_ROOT = REPO_ROOT / "templates" / "layouts"

# Must match scripts/inspect_pptx_inventory.py::EVIDENCE_BASIS verbatim.
EXPECTED_EVIDENCE_BASIS = (
    "OOXML structure only; not proof of full PowerPoint editability"
)

# Embed surface scripts/export_pptx.py supports today. The smoke walks
# `ppt/media/` looking for any of these extensions; finding none means
# the D-One synthetic bytes never made it into the package as media.
_EMBEDDABLE_MEDIA_EXTS: tuple[str, ...] = (".png", ".jpg", ".jpeg")

# OOXML namespace for the Relationships parts the smoke walks. The
# parts under `_rels/*.rels` all use this XML namespace.
_NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

# Any string with a leading RFC-3986 scheme followed by ':' counts as
# an external Target. We refuse the obvious cases (http(s)://, file://,
# data:, ftp://, gopher://, ...) because they all instruct PowerPoint
# to fetch / open something outside the package at open time. Internal
# package targets (`../media/image1.png`, `slides/slide1.xml`) carry no
# scheme prefix and survive this check.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Substrings the smoke greps for to confirm the successful path is
# driven entirely by run_explicit_pipeline.py. Failure to find any of
# them aborts the smoke.
_SUCCESS_MARKERS: tuple[str, ...] = (
    "OK: explicit-input end-to-end run succeeded",
    "[PASS] materialize_image_assets",
    "[PASS] init_image_manifest",
)

# Substrings that, if present in the success path stdout/stderr, would
# indicate the old "expected pipeline failure / manual recovery" path
# survived in some form. The smoke refuses any of them. Anchored on
# wording the prior smoke / docs used; new code must not reintroduce.
_FORBIDDEN_RECOVERY_MARKERS: tuple[str, ...] = (
    "EXPECT-FAIL",
    "expected Stage-6",
    "expected Stage 6",
    "recovery",
    "Recovery",
    "RECOVERY",
    "does not resolve to an existing",
)


# ---------------------------------------------------------------------------
# Synthetic bundle. The whole bundle lives in memory as Python dicts
# and is written into a tempfile.TemporaryDirectory at smoke time —
# nothing under examples/ is read or written.
# ---------------------------------------------------------------------------

SYNTHETIC_TITLE = "Image Asset Acceptance Smoke"
SYNTHETIC_AUDIENCE = "Internal pipeline smoke reviewers"
SYNTHETIC_OBJECTIVE = (
    "Exercise the mockable D-One-stub chain end-to-end on a synthetic, "
    "non-sensitive narrative."
)
SYNTHETIC_TONE = "neutral-professional"
SYNTHETIC_LANGUAGE = "en"
SYNTHETIC_APPROXIMATE_SLIDE_COUNT = 2
SYNTHETIC_SOURCE_ID = "synthetic_image_asset_smoke_source"
SYNTHETIC_TEMPLATE = "business_review"
SYNTHETIC_IMAGE_ID = "cover_accent"
SYNTHETIC_IMAGE_LOCAL_PATH = "media/cover_accent.png"
SYNTHETIC_IMAGE_ALT_TEXT = "Synthetic abstract pattern (mock D-One output)."
SYNTHETIC_IMAGE_PROMPT = (
    "abstract geometric pattern in a neutral gradient, no text, no logo"
)


def _source_md_text() -> str:
    """A minimal synthetic Markdown body. The bytes are read for byte-
    level integrity in Stage 1 + the done_image_adapter prompt
    shingle scan, but never copied into any slide field."""
    return (
        "# Synthetic Image Asset Smoke Source\n\n"
        "This document is synthetic. It contains no real company, "
        "product, customer, or financial data.\n\n"
        "It exists only to exercise the mockable D-One-stub chain.\n"
    )


def _plan_spec() -> dict:
    return {
        "template": SYNTHETIC_TEMPLATE,
        "planning": {
            "planned_slide_count": 2,
            "rationale": (
                "Two-slide synthetic deck: a cover with an accent image "
                "(exercises the D-One-stub embed path) plus a "
                "conclusion (exercises a non-image slide)."
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


def _design_system_spec() -> dict:
    # Same shape as the committed trial fixture's design_system_spec,
    # but rewritten as in-memory bytes here so the smoke never reads
    # any committed example file.
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


def _slide_spec_cover() -> dict:
    return {
        "index": 1,
        "layout": "cover",
        "title": SYNTHETIC_TITLE,
        "subtitle": "Mock D-One chain end-to-end",
        "blocks": [
            {"id": "title", "kind": "text", "content": SYNTHETIC_TITLE},
            {
                "id": "subtitle",
                "kind": "text",
                "content": "Mock D-One chain end-to-end",
            },
            {"id": "presenter", "kind": "text", "content": "Synthetic Reviewer"},
            {"id": "date", "kind": "text", "content": "Synthetic window"},
            # `accent` is the cover layout's image_ref slot. Its
            # content must equal an id declared in image_manifest.images.
            {
                "id": "accent",
                "kind": "image_ref",
                "content": SYNTHETIC_IMAGE_ID,
            },
        ],
        "image_refs": [SYNTHETIC_IMAGE_ID],
        "notes": "Synthetic.",
    }


def _slide_spec_conclusion() -> dict:
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
                    "Synthetic image-asset chain succeeded; mock D-One "
                    "bytes are embedded under ppt/media/."
                ),
            },
        ],
    }


def _image_manifest_body() -> dict:
    """Manifest body declaring the single d_one_local entry the chain
    produces. Used both in the staging workspace (hand-written verbatim)
    and as the ``--image-manifest-spec`` for
    ``run_explicit_pipeline.py``."""
    return {
        "images": [
            {
                "id": SYNTHETIC_IMAGE_ID,
                "local_path": SYNTHETIC_IMAGE_LOCAL_PATH,
                "source": "d_one_local",
                "alt_text": SYNTHETIC_IMAGE_ALT_TEXT,
                "intended_use": "spot illustration",
            },
        ],
    }


def _done_image_adapter_spec() -> dict:
    return {
        "requests": [
            {
                "id": SYNTHETIC_IMAGE_ID,
                "prompt": SYNTHETIC_IMAGE_PROMPT,
                "intended_use": "spot illustration",
                "width_px": 320,
                "height_px": 320,
            },
        ],
    }


# ---------------------------------------------------------------------------
# Stage runner. Each chain step is a subprocess so its own argparse +
# fail-closed gates + stdout-stderr cascade are exercised verbatim.
# ---------------------------------------------------------------------------


@dataclass
class StageOutcome:
    name: str
    cmd: list[str]
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def combined(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


def _run_stage(name: str, cmd: list[str]) -> StageOutcome:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    return StageOutcome(
        name=name,
        cmd=cmd,
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def _print_stage(stage: StageOutcome) -> None:
    mark = "PASS" if stage.ok else "FAIL"
    print(f"  [{mark}] {stage.name} (rc={stage.exit_code})")
    if not stage.ok:
        tail = stage.stdout.splitlines()[-15:]
        if tail:
            print("    stdout tail:")
            for line in tail:
                print(f"      {line}")
        tail = stage.stderr.splitlines()[-15:]
        if tail:
            print("    stderr tail:")
            for line in tail:
                print(f"      {line}")


# ---------------------------------------------------------------------------
# Bundle materialization.
# ---------------------------------------------------------------------------


def _write_json(path: Path, body: dict) -> None:
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")


def _materialize_bundle(td: Path) -> dict:
    """Write the synthetic bundle (source + every spec file) under
    ``td/bundle/`` and return a dict of resolved paths the chain steps
    consume."""
    bundle = td / "bundle"
    bundle.mkdir(parents=True)
    source = bundle / "source.md"
    source.write_text(_source_md_text())

    plan_spec = bundle / "plan_spec.json"
    _write_json(plan_spec, _plan_spec())

    design_system_spec = bundle / "design_system_spec.json"
    _write_json(design_system_spec, _design_system_spec())

    slide_specs_dir = bundle / "slide_specs"
    slide_specs_dir.mkdir()
    _write_json(slide_specs_dir / "01_cover.json", _slide_spec_cover())
    _write_json(slide_specs_dir / "02_conclusion.json", _slide_spec_conclusion())

    image_manifest_spec = bundle / "image_manifest_spec.json"
    _write_json(image_manifest_spec, _image_manifest_body())

    done_image_adapter_spec = bundle / "done_image_adapter_spec.json"
    _write_json(done_image_adapter_spec, _done_image_adapter_spec())

    return {
        "bundle": bundle,
        "source": source,
        "plan_spec": plan_spec,
        "design_system_spec": design_system_spec,
        "slide_specs_dir": slide_specs_dir,
        "image_manifest_spec": image_manifest_spec,
        "done_image_adapter_spec": done_image_adapter_spec,
    }


# ---------------------------------------------------------------------------
# Staging phase: build a minimal staging workspace and run the d_one
# chain against it. Produces materialized PNG bytes at
# ``<staging>/<local_path>``; the staging workspace itself is then
# passed as ``--assets-dir`` to ``run_explicit_pipeline.py`` so the
# orchestrator's materialize_image_assets step can copy the bytes into
# the production workspace.
# ---------------------------------------------------------------------------


def _build_staging_workspace(td: Path, *, source: Path) -> Path:
    """Create a staging workspace via ``scripts/init_workspace.py``,
    then hand-write ``image_manifest.json`` with the d_one_local entries
    the chain will materialize. The staging workspace is intentionally
    minimal — it carries only what ``done_image_adapter``,
    ``run_d_one_generation``, and ``materialize_image_assets`` need
    (source_manifest.json, input/source.md, image_manifest.json). It is
    NEVER fed back to ``run_explicit_pipeline.py`` as a workspace; the
    smoke only passes it as ``--assets-dir`` so the materialize_image_
    assets step inside the orchestrator can read
    ``<staging>/<local_path>``."""
    staging = td / "staging"
    rc = _run_stage(
        "init_workspace (staging)",
        [
            sys.executable, str(SCRIPTS_DIR / "init_workspace.py"),
            "--workspace", str(staging),
            "--source", str(source),
            "--source-id", SYNTHETIC_SOURCE_ID,
        ],
    )
    _print_stage(rc)
    if not rc.ok:
        raise RuntimeError(
            f"staging init_workspace failed; rc={rc.exit_code}"
        )
    # Hand-write the d_one_local manifest into the staging workspace.
    # This is the *direct-author workflow* documented at
    # scripts/materialize_image_assets.py:14–47 — bypasses Stage-6's
    # local_path-existence gate so done_image_adapter can run against
    # entries whose bytes have not yet been produced.
    _write_json(staging / "image_manifest.json", _image_manifest_body())
    return staging


def _run_d_one_chain_in_staging(
    *, staging: Path, assets_dir: Path, done_image_adapter_spec: Path,
) -> list[StageOutcome]:
    """Run done_image_adapter -> run_d_one_generation -> materialize on
    the staging workspace. Returns the per-stage outcomes in order."""
    py = sys.executable
    stages: list[tuple[str, list[str]]] = [
        (
            "done_image_adapter",
            [
                py, str(SCRIPTS_DIR / "done_image_adapter.py"),
                "--workspace", str(staging),
                "--spec", str(done_image_adapter_spec),
            ],
        ),
        (
            "run_d_one_generation",
            [
                py, str(SCRIPTS_DIR / "run_d_one_generation.py"),
                "--workspace", str(staging),
                "--assets-dir", str(assets_dir),
                "--allow-synthetic-bytes",
            ],
        ),
        (
            "materialize_image_assets",
            [
                py, str(SCRIPTS_DIR / "materialize_image_assets.py"),
                "--workspace", str(staging),
                "--assets-dir", str(assets_dir),
            ],
        ),
    ]
    outcomes: list[StageOutcome] = []
    for name, cmd in stages:
        outcome = _run_stage(name, cmd)
        outcomes.append(outcome)
        _print_stage(outcome)
        if not outcome.ok:
            break
    return outcomes


# ---------------------------------------------------------------------------
# Production phase: invoke ``run_explicit_pipeline.py`` with
# ``--assets-dir <staging>`` and expect rc=0. Stage 6
# (``init_image_manifest``) finds the bytes because the orchestrator's
# materialize_image_assets step (Stage 5.5, only present when
# ``--assets-dir`` is passed) copies them into the production workspace
# first.
# ---------------------------------------------------------------------------


def _invoke_run_explicit_pipeline(
    *, workspace: Path, bundle: dict, staging: Path,
    output: Path, report_dir: Path,
) -> StageOutcome:
    """Invoke ``scripts/run_explicit_pipeline.py`` against the freshly-
    created production workspace + the bundle's d_one_local specs, with
    the staging workspace passed as ``--assets-dir`` so the
    orchestrator's materialize_image_assets step can copy
    ``<staging>/<local_path>`` into ``<workspace>/<local_path>`` between
    Stage 5 and Stage 6. The successful path is one invocation with
    rc=0; the smoke does not catch any expected failure here."""
    py = sys.executable
    cmd = [
        py, str(SCRIPTS_DIR / "run_explicit_pipeline.py"),
        "--workspace", str(workspace),
        "--source", str(bundle["source"]),
        "--source-id", SYNTHETIC_SOURCE_ID,
        "--title", SYNTHETIC_TITLE,
        "--audience", SYNTHETIC_AUDIENCE,
        "--objective", SYNTHETIC_OBJECTIVE,
        "--tone", SYNTHETIC_TONE,
        "--language", SYNTHETIC_LANGUAGE,
        "--approximate-slide-count", str(SYNTHETIC_APPROXIMATE_SLIDE_COUNT),
        "--plan-spec", str(bundle["plan_spec"]),
        "--design-system-spec", str(bundle["design_system_spec"]),
        "--template-root", str(TEMPLATE_ROOT),
        "--slide-specs-dir", str(bundle["slide_specs_dir"]),
        "--image-manifest-spec", str(bundle["image_manifest_spec"]),
        "--assets-dir", str(staging),
        "--output", str(output),
        "--report-dir", str(report_dir),
    ]
    return _run_stage("run_explicit_pipeline", cmd)


def _run_belt_and_braces_validators(
    *, workspace: Path, output: Path, report_dir: Path,
    expected_slide_count: int,
) -> list[StageOutcome]:
    """Run the two non-mutating validators the explicit-input
    acceptance path runs as belt-and-braces stages: the PPTX contract
    validator (with ``--expected-slide-count`` active) and the visual
    quality validator (which writes ``<report-dir>/visual_quality.json``
    as a reviewable artifact alongside the pipeline's own
    ``pipeline_report.{json,txt}`` + ``inventory.json``)."""
    py = sys.executable
    visual_quality_out = report_dir / "visual_quality.json"
    stages: list[tuple[str, list[str]]] = [
        (
            "validate_pptx_contract",
            [
                py, str(SCRIPTS_DIR / "validate_pptx_contract.py"),
                "--pptx", str(output),
                "--expected-slide-count", str(expected_slide_count),
            ],
        ),
        (
            "validate_visual_quality",
            [
                py, str(SCRIPTS_DIR / "validate_visual_quality.py"),
                "--workspace", str(workspace),
                "--output", str(visual_quality_out),
            ],
        ),
    ]
    outcomes: list[StageOutcome] = []
    for name, cmd in stages:
        outcome = _run_stage(name, cmd)
        outcomes.append(outcome)
        _print_stage(outcome)
        if not outcome.ok:
            break
    return outcomes


# ---------------------------------------------------------------------------
# Post-condition checks.
# ---------------------------------------------------------------------------


@dataclass
class PostCondition:
    name: str
    ok: bool
    detail: str = ""


def _check_pptx_embeds_internal_media_only(pptx: Path) -> list[PostCondition]:
    """Open the PPTX as a ZIP and assert two things:

    1. At least one ``ppt/media/<file>`` part exists with an extension
       in ``_EMBEDDABLE_MEDIA_EXTS`` — proof the D-One synthetic bytes
       embedded as native PowerPoint media, not as a placeholder shape;
    2. Every ``.rels`` part's relationship Target is either internal
       (no URI scheme; resolves inside the package) or an OOXML
       internal reference — no ``http://``, ``https://``, ``file://``,
       ``data:``, etc."""
    results: list[PostCondition] = []
    try:
        zf = zipfile.ZipFile(pptx, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        results.append(PostCondition(
            "PPTX opens as a ZIP",
            False,
            f"{type(exc).__name__}: {exc}",
        ))
        return results
    try:
        names = zf.namelist()
        media_files = [
            n for n in names
            if n.startswith("ppt/media/")
            and Path(n).suffix.lower() in _EMBEDDABLE_MEDIA_EXTS
        ]
        results.append(PostCondition(
            f"PPTX embeds at least one ppt/media/ asset with extension "
            f"in {_EMBEDDABLE_MEDIA_EXTS}",
            len(media_files) > 0,
            (f"media files under ppt/media/: "
             f"{sorted(n for n in names if n.startswith('ppt/media/'))}"
             if not media_files else ""),
        ))
        external_targets: list[str] = []
        for n in names:
            if not n.endswith(".rels"):
                continue
            try:
                body = zf.read(n)
                root = ET.fromstring(body)
            except (KeyError, OSError, ET.ParseError) as exc:
                external_targets.append(
                    f"{n}: cannot parse: {type(exc).__name__}: {exc}"
                )
                continue
            rel_tag = f"{{{_NS_REL}}}Relationship"
            for el in root:
                if el.tag != rel_tag:
                    continue
                target = el.attrib.get("Target", "")
                mode = el.attrib.get("TargetMode", "")
                if mode and mode != "Internal":
                    external_targets.append(
                        f"{n}: id={el.attrib.get('Id')!r} "
                        f"TargetMode={mode!r} Target={target!r}"
                    )
                    continue
                if _URI_SCHEME_PREFIX.match(target):
                    external_targets.append(
                        f"{n}: id={el.attrib.get('Id')!r} "
                        f"Target={target!r} (URI scheme)"
                    )
        results.append(PostCondition(
            "PPTX has no external / file:// / data: / scheme-shaped "
            "relationships",
            not external_targets,
            "; ".join(external_targets) if external_targets else "",
        ))
    finally:
        zf.close()
    return results


def _check_inventory_contract(
    *, inventory_path: Path, expected_slide_count: int,
) -> list[PostCondition]:
    results: list[PostCondition] = []
    inv_is_file = inventory_path.is_file() and not inventory_path.is_symlink()
    results.append(PostCondition(
        "inventory.json exists as a regular non-symlink file",
        inv_is_file,
        f"path={inventory_path}, is_file={inventory_path.is_file()}, "
        f"is_symlink={inventory_path.is_symlink()}",
    ))
    if not inv_is_file:
        return results
    try:
        inv = json.loads(inventory_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        results.append(PostCondition(
            "inventory.json parses as JSON",
            False,
            f"{type(exc).__name__}: {exc}",
        ))
        return results
    results.append(PostCondition(
        "inventory.ok is True",
        inv.get("ok") is True,
        f"got: {inv.get('ok')!r}",
    ))
    results.append(PostCondition(
        "inventory.findings is []",
        inv.get("findings") == [],
        f"got: {inv.get('findings')!r}",
    ))
    results.append(PostCondition(
        "inventory.evidence_basis matches the documented line",
        inv.get("evidence_basis") == EXPECTED_EVIDENCE_BASIS,
        f"expected: {EXPECTED_EVIDENCE_BASIS!r}; "
        f"got: {inv.get('evidence_basis')!r}",
    ))
    results.append(PostCondition(
        f"inventory.slide_count == {expected_slide_count}",
        inv.get("slide_count") == expected_slide_count,
        f"got: {inv.get('slide_count')!r}",
    ))
    mp = inv.get("media_parts")
    results.append(PostCondition(
        "inventory.media_parts is a non-empty list",
        isinstance(mp, list) and len(mp) > 0,
        f"got: type={type(mp).__name__}, "
        f"len={len(mp) if isinstance(mp, list) else 'n/a'}",
    ))
    return results


def _check_visual_quality_report(
    *, report_dir: Path,
) -> list[PostCondition]:
    """The visual-quality report must exist as a regular non-symlink
    file under the temp ``<report-dir>`` and parse as JSON. The
    validator's own ERROR/WARN bookkeeping is captured at stage time
    (a non-zero exit aborts the smoke upstream of this check); the
    post-condition only proves the report landed on disk."""
    results: list[PostCondition] = []
    vq = report_dir / "visual_quality.json"
    vq_is_file = vq.is_file() and not vq.is_symlink()
    results.append(PostCondition(
        "visual_quality.json exists as a regular non-symlink file "
        "under the temp report directory",
        vq_is_file,
        f"path={vq}, is_file={vq.is_file()}, is_symlink={vq.is_symlink()}",
    ))
    if vq_is_file:
        try:
            json.loads(vq.read_text())
            results.append(PostCondition(
                "visual_quality.json parses as JSON",
                True,
            ))
        except (json.JSONDecodeError, OSError) as exc:
            results.append(PostCondition(
                "visual_quality.json parses as JSON",
                False,
                f"{type(exc).__name__}: {exc}",
            ))
    return results


def _check_success_path_markers(
    rxp_outcome: StageOutcome,
) -> list[PostCondition]:
    """The run_explicit_pipeline.py stdout/stderr on the successful path
    must contain every ``_SUCCESS_MARKERS`` substring (proves the
    materialize_image_assets + init_image_manifest stages both fired and
    the explicit-input run reported success) and must NOT contain any
    ``_FORBIDDEN_RECOVERY_MARKERS`` substring (proves the smoke no
    longer treats a pipeline failure as expected or describes a recovery
    flow)."""
    results: list[PostCondition] = []
    combined = rxp_outcome.combined
    for marker in _SUCCESS_MARKERS:
        results.append(PostCondition(
            f"run_explicit_pipeline output contains success marker "
            f"{marker!r}",
            marker in combined,
            (f"marker not found; output tail: "
             f"{combined.splitlines()[-10:]!r}")
            if marker not in combined else "",
        ))
    for marker in _FORBIDDEN_RECOVERY_MARKERS:
        results.append(PostCondition(
            f"run_explicit_pipeline output does NOT contain expected-"
            f"failure / recovery marker {marker!r}",
            marker not in combined,
            (f"marker present; output tail: "
             f"{combined.splitlines()[-15:]!r}")
            if marker in combined else "",
        ))
    return results


# ---------------------------------------------------------------------------
# Snapshot helpers (proves no committed example bytes change).
# ---------------------------------------------------------------------------


def _snapshot_dir(dir_path: Path) -> dict[str, bytes]:
    """Flat path -> bytes map of every regular file under ``dir_path``.
    Mirrors scripts/acceptance_smoke.py::_snapshot_dir so the no-mutation
    invariant is asserted with the same gate the existing smoke uses."""
    snapshot: dict[str, bytes] = {}
    if not dir_path.is_dir():
        return snapshot
    for p in sorted(dir_path.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(dir_path)
        snapshot[str(rel)] = p.read_bytes()
    return snapshot


def _final_examples_check(
    examples_before: dict[str, bytes], *, fail_already: bool,
) -> int:
    examples_after = _snapshot_dir(REPO_ROOT / "examples")
    if examples_before == examples_after:
        return 1 if fail_already else 0
    changed: list[str] = []
    for key in sorted(set(examples_before) | set(examples_after)):
        if examples_before.get(key) != examples_after.get(key):
            changed.append(key)
    print(
        f"FAIL: examples/ was mutated by the smoke "
        f"(changed paths: {changed!r}). The smoke must run entirely "
        f"under tempfile.TemporaryDirectory() — no generated artifact "
        f"may land in any committed example directory.",
        file=sys.stderr,
    )
    return 1


# ---------------------------------------------------------------------------
# Static source-level check: prove the smoke does NOT invoke the
# Stage-7-to-10 prepared-workspace pipeline runner directly. The
# successful path goes through the Stage-1-to-10 orchestrator; the
# Stage-7-to-10 runner is delegated to as a subprocess inside that
# orchestrator and is never spawned by this smoke.
# ---------------------------------------------------------------------------


def _assert_no_run_pipeline_invocation() -> None:
    """Read the smoke's own source bytes and refuse if they reference
    the Stage-7-to-10 prepared-workspace runner as a literal Python
    string outside the module docstring. Refusing at startup makes the
    gate durable: a future regression that brings back a fallback
    invocation of that runner is caught by the smoke's own self-test
    before any subprocess fires."""
    src_path = Path(__file__).resolve()
    body = src_path.read_text()
    # Construct the forbidden name from parts so the literal substring
    # never appears anywhere in this file's code body — it is only
    # allowed in the module docstring (which we strip before scanning).
    forbidden = "run_" + "pipeline" + ".py"
    after = body
    if body.startswith('#!'):
        after = body.split("\n", 1)[1] if "\n" in body else body
    if '"""' in after:
        _, _, rest = after.partition('"""')
        post_docstring = rest.partition('"""')[2]
    else:
        post_docstring = body
    if forbidden in post_docstring:
        raise RuntimeError(
            f"image_asset_acceptance_smoke.py code references "
            f"{forbidden!r} (the Stage-7-to-10 prepared-workspace "
            f"runner); the successful image-asset acceptance path must "
            f"be driven by the Stage-1-to-10 orchestrator only. Remove "
            f"the reference and re-run."
        )


# ---------------------------------------------------------------------------
# Self-test entry point.
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    """Run the full image-asset acceptance chain under a single
    ``tempfile.TemporaryDirectory()``. Returns 0 on full pass."""
    print("=== image-asset acceptance smoke (mock D-One chain) ===")
    try:
        _assert_no_run_pipeline_invocation()
    except RuntimeError as exc:
        print(f"\nFAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "  [OK] static check: smoke source does not reference the "
        "Stage-7-to-10 prepared-workspace runner outside its "
        "docstring."
    )

    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    with tempfile.TemporaryDirectory(
        prefix="szh_image_asset_acceptance_smoke_",
    ) as raw_td:
        td = Path(raw_td)

        # Layout under td:
        #   td/bundle/                     — synthetic specs (in-memory -> disk)
        #   td/staging/                    — workspace for the d_one chain;
        #                                    also passed as --assets-dir
        #                                    to run_explicit_pipeline.py
        #   td/d_one_assets/               — flat assets-dir for
        #                                    run_d_one_generation
        #   td/workspace/                  — production workspace driven
        #                                    by run_explicit_pipeline.py
        #   td/report/                     — pipeline + visual_quality
        #                                    reports
        #   td/deck.pptx                   — final PPTX (outside any
        #                                    workspace)
        d_one_assets = td / "d_one_assets"
        d_one_assets.mkdir()
        workspace = td / "workspace"
        output = td / "deck.pptx"
        report_dir = td / "report"

        print(f"  tempdir:         {td}")
        print(f"  workspace:       {workspace}")
        print(f"  d_one assets:    {d_one_assets}")
        print(f"  output PPTX:     {output}")
        print(f"  report dir:      {report_dir}")
        print()

        print("--- bundle materialization ---")
        bundle = _materialize_bundle(td)
        print(f"  bundle root: {bundle['bundle']}")
        print()

        print("--- staging phase: build staging workspace ---")
        try:
            staging = _build_staging_workspace(td, source=bundle["source"])
        except RuntimeError as exc:
            print(f"\nFAIL: staging setup failed: {exc}", file=sys.stderr)
            return _final_examples_check(examples_before, fail_already=True)
        print(f"  staging workspace: {staging}")
        print()

        print("--- staging phase: d_one chain (done_image_adapter -> "
              "run_d_one_generation -> materialize_image_assets) ---")
        d_one_outcomes = _run_d_one_chain_in_staging(
            staging=staging,
            assets_dir=d_one_assets,
            done_image_adapter_spec=bundle["done_image_adapter_spec"],
        )
        if not all(o.ok for o in d_one_outcomes):
            print("\nFAIL: d_one chain did not all pass; aborting smoke.")
            return _final_examples_check(examples_before, fail_already=True)
        staged_asset = staging / SYNTHETIC_IMAGE_LOCAL_PATH
        if not (staged_asset.is_file()
                and staged_asset.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"):
            print(
                f"\nFAIL: staged asset {staged_asset} is not a "
                f"PNG-magic-valid regular file after the d_one chain. "
                f"Aborting.",
                file=sys.stderr,
            )
            return _final_examples_check(examples_before, fail_already=True)
        print(f"  [OK] staged asset {staged_asset.relative_to(td)} carries "
              f"PNG magic ({staged_asset.stat().st_size} bytes)")
        print()

        print("--- production phase: run_explicit_pipeline.py "
              "--assets-dir <staging> (one shot, expect rc=0) ---")
        rxp_outcome = _invoke_run_explicit_pipeline(
            workspace=workspace,
            bundle=bundle,
            staging=staging,
            output=output,
            report_dir=report_dir,
        )
        _print_stage(rxp_outcome)
        if not rxp_outcome.ok:
            print(
                f"\nFAIL: run_explicit_pipeline did not succeed "
                f"(rc={rxp_outcome.exit_code}); aborting smoke.",
                file=sys.stderr,
            )
            return _final_examples_check(examples_before, fail_already=True)
        # Confirm the orchestrator copied the bytes into the production
        # workspace. The materialize_image_assets step inside
        # prepare_workspace is the only place this can happen during a
        # run_explicit_pipeline invocation.
        prod_asset = workspace / SYNTHETIC_IMAGE_LOCAL_PATH
        if not (prod_asset.is_file()
                and prod_asset.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"):
            print(
                f"\nFAIL: production asset {prod_asset} is not a "
                f"PNG-magic-valid regular file after "
                f"run_explicit_pipeline; the materialize_image_assets "
                f"step did not copy the bytes into the workspace.",
                file=sys.stderr,
            )
            return _final_examples_check(examples_before, fail_already=True)
        print(f"  [OK] production asset {prod_asset.relative_to(td)} "
              f"carries PNG magic ({prod_asset.stat().st_size} bytes)")
        print()

        expected_slide_count = len(_plan_spec()["slides"])
        print(
            f"--- belt-and-braces validators "
            f"(expected_slide_count={expected_slide_count}) ---"
        )
        bnb_outcomes = _run_belt_and_braces_validators(
            workspace=workspace,
            output=output,
            report_dir=report_dir,
            expected_slide_count=expected_slide_count,
        )
        if not all(o.ok for o in bnb_outcomes):
            print(
                "\nFAIL: belt-and-braces validators did not all pass; "
                "aborting smoke."
            )
            return _final_examples_check(examples_before, fail_already=True)
        print()

        print("--- post-conditions ---")
        post_results: list[PostCondition] = []
        pptx_is_file = output.is_file() and not output.is_symlink()
        post_results.append(PostCondition(
            "PPTX exists as a regular non-symlink file",
            pptx_is_file,
            f"path={output}, is_file={output.is_file()}, "
            f"is_symlink={output.is_symlink()}",
        ))
        if pptx_is_file:
            size = output.stat().st_size
            post_results.append(PostCondition(
                "PPTX is non-empty", size > 0, f"size={size}",
            ))
            post_results.extend(
                _check_pptx_embeds_internal_media_only(output)
            )
        post_results.extend(_check_inventory_contract(
            inventory_path=report_dir / "inventory.json",
            expected_slide_count=expected_slide_count,
        ))
        post_results.extend(_check_visual_quality_report(
            report_dir=report_dir,
        ))
        post_results.extend(_check_success_path_markers(rxp_outcome))

        fails = 0
        for pc in post_results:
            mark = "PASS" if pc.ok else "FAIL"
            suffix = f" -- {pc.detail}" if not pc.ok and pc.detail else ""
            print(f"  [{mark}] {pc.name}{suffix}")
            if not pc.ok:
                fails += 1
        print()

        if fails:
            print(
                f"FAIL: {fails} post-condition(s) did not hold; pipeline "
                f"steps all reported PASS but the produced artifacts did "
                f"not match the image-asset acceptance contract.",
                file=sys.stderr,
            )
            return _final_examples_check(examples_before, fail_already=True)

    rc_examples = _final_examples_check(examples_before, fail_already=False)
    if rc_examples != 0:
        return rc_examples
    print(
        "OK (self-test): image-asset acceptance smoke passed. "
        "MOCK D-One chain only — NOT proof of real D-One integration."
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Image-asset acceptance smoke: exercises the mockable "
            "D-One-stub chain (done_image_adapter -> "
            "run_d_one_generation -> materialize_image_assets) against "
            "the intended explicit-input acceptance path. The "
            "successful path is one ``run_explicit_pipeline.py`` "
            "invocation with ``--assets-dir <staging>`` that returns "
            "rc=0: the staging workspace produced by the d_one chain "
            "carries the materialized PNG bytes at "
            "<staging>/<local_path>, and the orchestrator's "
            "materialize_image_assets step (inserted between Stage 5 "
            "and Stage 6 when --assets-dir is supplied) copies those "
            "bytes into the production workspace so init_image_manifest "
            "(Stage 6) finds them, the cascade completes Stages 1-10, "
            "validate_pptx_contract --expected-slide-count N + "
            "validate_visual_quality run as belt-and-braces validators, "
            "and the produced artifacts satisfy the documented PPTX + "
            "inventory + visual-quality post-conditions. MOCK / stub "
            "acceptance only — NOT real D-One integration; no MCP, no "
            "public network, no model API, no image search, no Qoder, "
            "no external service."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run the full chain under tempfile.TemporaryDirectory() and "
            "verify every post-condition: PPTX embeds at least one "
            "internal ppt/media PNG/JPG/JPEG; no external/file:// "
            "relationships; <report-dir>/inventory.json carries "
            "ok=true / findings=[] / slide_count == "
            "len(deck_plan.slides) / media_parts non-empty / exact "
            "evidence_basis line 'OOXML structure only; not proof of "
            "full PowerPoint editability'; <report-dir>/"
            "visual_quality.json exists and parses as JSON; the "
            "run_explicit_pipeline output carries every success marker "
            "('OK: explicit-input end-to-end run succeeded', "
            "'[PASS] materialize_image_assets', '[PASS] "
            "init_image_manifest') and NO expected-failure / recovery "
            "wording; REPO_ROOT/examples/ byte-snapshot unchanged. The "
            "smoke has no other mode today; --self-test is required."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: image_asset_acceptance_smoke.py requires --self-test "
            "(no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
