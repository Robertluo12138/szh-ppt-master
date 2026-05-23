#!/usr/bin/env python3
"""Image-request taxonomy acceptance smoke for the mockable D-One stub chain.

Proves the seven-dimensional clean-room D-One prompt-intent taxonomy
(``rendering_style`` / ``palette_family`` / ``image_role`` /
``layout_pattern`` / ``modifier`` / ``text_policy`` /
``subject_domain``) survives the existing local mock image chain
end-to-end, without adding any real D-One behavior:

  d_one_local image_manifest entry (hand-written into a staging
    workspace per the direct-author workflow documented at
    ``scripts/materialize_image_assets.py``)
      -> scripts/done_image_adapter.py --descriptor-vocabulary <vocab>
           (writes ``d_one_adapter_plan.json`` whose schema_version is
            locked to 4 and which preserves every taxonomy field /
            value supplied on the request)
      -> scripts/run_d_one_generation.py --descriptor-vocabulary <vocab>
           --allow-synthetic-bytes
           (mock provider; produces magic-byte-valid PNG bytes named
            ``<id>.png`` in the flat staging assets directory)
      -> scripts/materialize_image_assets.py
           (copies staging-asset bytes -> staging-workspace/<local_path>)

  -> scripts/run_explicit_pipeline.py --assets-dir <staging>
       against a fresh production workspace + the same d_one_local
       bundle. The staging workspace already carries the materialized
       bytes, so ``prepare_workspace.py``'s materialize_image_assets
       step copies them into the production workspace between Stage 5
       (init_slide_plans) and Stage 6 (init_image_manifest). Stage 6
       finds the bytes on disk and the cascade completes Stages 1-10.

The smoke then asserts:

  * ``d_one_adapter_plan.json`` carries ``schema_version == 4``;
  * every taxonomy field / value supplied on the spec request appears
    byte-identical on the corresponding plan request (no value drift,
    no silent re-ordering, no field dropped);
  * the plan re-validates clean via ``done_image_adapter.py
    --validate-plan --descriptor-vocabulary <vocab>`` (taxonomy
    membership rechecked against the supplied vocabulary at runner-
    boundary parity);
  * the generated local PNG asset reaches the final ``.pptx`` as a
    regular ``ppt/media/<file>.<ext>`` part whose extension is one of
    ``.png`` / ``.jpg`` / ``.jpeg`` — the embed surface
    ``scripts/export_pptx.py`` natively supports today.

Negative probes (in-process via ``done_image_adapter``):

  N1  a spec request carrying any taxonomy field is refused when
      ``--descriptor-vocabulary`` was not supplied (the runtime cannot
      certify a taxonomy value it cannot check against
      ``image_taxonomy.<dim>.allowed_values``);

  N2  a spec request whose ``text_policy`` is regex-shape valid but
      outside ``image_taxonomy.text_policy.allowed_values`` is refused;

  N3  a spec request whose ``subject_domain`` is regex-shape valid but
      outside ``image_taxonomy.subject_domain.allowed_values`` is
      refused;

  N4  a hand-written plan carrying a regex-shape valid ``rendering_style``
      value that is NOT in the supplied vocab's
      ``image_taxonomy.rendering_style.allowed_values`` is refused by
      ``--validate-plan`` (stale taxonomy drift after the vocab moved);

  N5  a plan whose ``schema_version`` is anything other than the
      locked value 4 (we probe with 1, the pre-taxonomy shape, AND 5,
      a future shape) is refused by the plan schema's enum;

  N6  a descriptor vocabulary whose ``descriptors[*].value`` carries
      any of the bounded forbidden tokens (``public``, ``upload``,
      ``raw``, ``customer``, ``confidential``, ``screenshot``,
      ``credential``, ``password``, ``secret``) is refused by the
      descriptor-vocabulary schema's pattern lock — done_image_adapter
      surfaces the failure when it loads the vocab;

  N7  a descriptor vocabulary whose ``descriptors[*].value`` carries
      any of the compound forbidden phrases (``full slide``,
      ``image search``, ``web generation``, ``page generation``,
      ``slide generation``) across any separator stacking (``_`` /
      ``-`` / ``.``) is refused by the same schema pattern lock.

MOCK / STUB ACCEPTANCE ONLY — NOT real D-One integration. The smoke
never calls D-One, MCP, Qoder, a public network, telemetry, any model
API, an image search, or any external service. The D-One generator
boundary ``scripts/run_d_one_generation.py`` operates in
``--allow-synthetic-bytes`` mode; the bytes are never derived from
``input/source.md`` and never claim to be photographically meaningful.
The smoke proves the *taxonomy contract chain* holds, not the
photographic quality of any real generator.

Snapshot check: every scenario runs under
``tempfile.TemporaryDirectory()``; a flat-bytes snapshot of
``REPO_ROOT/examples/`` taken before and after the run must match —
proves no generated artifact lands in any committed example directory.

Stdlib-only. Self-test only; no production CLI surface.
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

sys.path.insert(0, str(SCRIPTS_DIR))

import done_image_adapter as _adapter  # noqa: E402

# Embed surface scripts/export_pptx.py supports today. The smoke walks
# `ppt/media/` looking for any of these extensions; finding none means
# the D-One synthetic bytes never made it into the package as media.
_EMBEDDABLE_MEDIA_EXTS: tuple[str, ...] = (".png", ".jpg", ".jpeg")

# RFC-3986 scheme prefix; same regex other helpers use.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Locked plan-file schema version. The 1 -> 2 bump was the paired
# change for the optional per-request taxonomy fields. The 2 -> 3 bump
# was the paired change for the optional per-request custom_descriptor
# escape-hatch field. The 3 -> 4 bump is the paired change for the
# optional per-request placement_role field (closed enumeration
# `hero_page` / `local_region`); an older reader with
# schema_version=3 would reject the new property under
# additionalProperties:false.
_LOCKED_PLAN_SCHEMA_VERSION = 4


# ---------------------------------------------------------------------------
# Synthetic taxonomy-bearing bundle. All in-memory; materialized into a
# tempfile.TemporaryDirectory() at smoke time — nothing under examples/
# is read or written.
# ---------------------------------------------------------------------------

SYNTHETIC_SOURCE_ID = "synthetic_image_taxonomy_smoke_source"
SYNTHETIC_TITLE = "Image Taxonomy Acceptance Smoke"
SYNTHETIC_AUDIENCE = "Internal pipeline smoke reviewers"
SYNTHETIC_OBJECTIVE = (
    "Exercise the seven-dimensional D-One prompt-intent taxonomy "
    "through the local mock image chain on a synthetic, non-sensitive "
    "narrative."
)
SYNTHETIC_TONE = "neutral-professional"
SYNTHETIC_LANGUAGE = "en"
SYNTHETIC_APPROXIMATE_SLIDE_COUNT = 2
SYNTHETIC_TEMPLATE = "business_review"
SYNTHETIC_IMAGE_ID = "cover_accent"
SYNTHETIC_IMAGE_LOCAL_PATH = "media/cover_accent.png"
SYNTHETIC_IMAGE_ALT_TEXT = "Synthetic abstract pattern (mock D-One output)."
SYNTHETIC_IMAGE_PROMPT = (
    "abstract geometric pattern in a calm neutral gradient, "
    "no text, no logo"
)

# One canonical value per dimension. Mirrors the canonical enums the
# descriptor-vocabulary schema locks. This is the request the smoke
# expects to see preserved byte-identically on the produced plan file.
TAXONOMY_REQUEST: dict[str, str] = {
    "rendering_style": "flat_vector",
    "palette_family": "neutral_grey",
    "image_role": "decorative_accent",
    "layout_pattern": "single_center",
    "modifier": "soft_edges",
    "text_policy": "no_text",
    "subject_domain": "abstract_geometry",
}


def _source_md_text() -> str:
    return (
        "# Synthetic Image Taxonomy Smoke Source\n\n"
        "This document is synthetic. It contains no real company, "
        "product, customer, or financial data.\n\n"
        "It exists only to exercise the seven-dimensional D-One "
        "prompt-intent taxonomy through the local mock image chain.\n"
    )


def _plan_spec() -> dict:
    return {
        "template": SYNTHETIC_TEMPLATE,
        "planning": {
            "planned_slide_count": 2,
            "rationale": (
                "Two-slide synthetic deck: a cover with a taxonomy-"
                "tagged accent image plus a conclusion (exercises the "
                "non-image path)."
            ),
        },
        "sections": [
            {
                "id": "open",
                "title": "Open",
                "summary": "Cover with taxonomy-tagged accent image.",
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
                "summary": "Cover with a taxonomy-tagged accent image.",
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
        "subtitle": "Seven-dimensional taxonomy end-to-end",
        "blocks": [
            {"id": "title", "kind": "text", "content": SYNTHETIC_TITLE},
            {
                "id": "subtitle",
                "kind": "text",
                "content": "Seven-dimensional taxonomy end-to-end",
            },
            {"id": "presenter", "kind": "text", "content": "Synthetic Reviewer"},
            {"id": "date", "kind": "text", "content": "Synthetic window"},
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
                    "Synthetic taxonomy chain succeeded; mock D-One "
                    "bytes are embedded under ppt/media/."
                ),
            },
        ],
    }


def _image_manifest_body() -> dict:
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
    """Spec carrying the synthetic prompt PLUS all seven taxonomy
    fields. Each value mirrors the canonical enum in the descriptor
    vocabulary written by ``_descriptor_vocabulary_body()`` below."""
    req: dict = {
        "id": SYNTHETIC_IMAGE_ID,
        "prompt": SYNTHETIC_IMAGE_PROMPT,
        "intended_use": "spot illustration",
        "width_px": 320,
        "height_px": 320,
    }
    req.update(TAXONOMY_REQUEST)
    return {"requests": [req]}


def _descriptor_vocabulary_body() -> dict:
    """Schema-valid descriptor vocabulary covering all seven taxonomy
    dimensions with their canonical values. Kept in-script so the smoke
    does not depend on any committed example bytes."""
    return {
        "schema_version": 1,
        "note": (
            "Synthetic D-One descriptor vocabulary for taxonomy "
            "acceptance smoke."
        ),
        "kind_enum": [
            "color_token",
            "geometric_noun",
            "mood_adjective",
            "composition_adjective",
        ],
        "descriptors": [
            {"kind": "color_token", "value": "palette.accent"},
            {"kind": "geometric_noun", "value": "circle"},
            {"kind": "mood_adjective", "value": "calm"},
            {"kind": "composition_adjective", "value": "centered"},
        ],
        "image_taxonomy": {
            "rendering_style": {"allowed_values": [
                "flat_vector", "line_diagram", "isometric_lite",
                "low_poly", "solid_shape",
            ]},
            "palette_family": {"allowed_values": [
                "neutral_grey", "accent_only", "dual_tone",
                "mono_brand", "palette_default",
            ]},
            "image_role": {"allowed_values": [
                "decorative_accent", "metaphor_icon", "divider_motif",
                "kpi_emblem", "cover_motif",
            ]},
            "layout_pattern": {"allowed_values": [
                "single_center", "left_anchor", "right_anchor",
                "top_band", "bottom_band",
            ]},
            "modifier": {"allowed_values": [
                "low_contrast", "soft_edges", "grid_aligned",
                "negative_space",
            ]},
            "text_policy": {"allowed_values": [
                "no_text", "decorative_glyphs", "caption_safe",
            ]},
            "subject_domain": {"allowed_values": [
                "abstract_geometry", "process_motif",
                "metric_emblem", "concept_diagram",
            ]},
            "placement_role": {"allowed_values": [
                "hero_page", "local_region",
            ]},
        },
    }


# ---------------------------------------------------------------------------
# Subprocess runner. Each chain step is a subprocess so its own argparse +
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
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    return StageOutcome(
        name=name, cmd=cmd, exit_code=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


def _print_stage(stage: StageOutcome) -> None:
    mark = "PASS" if stage.ok else "FAIL"
    print(f"  [{mark}] {stage.name} (rc={stage.exit_code})")
    if not stage.ok:
        for label, text in (("stdout", stage.stdout), ("stderr", stage.stderr)):
            tail = (text or "").splitlines()[-15:]
            if tail:
                print(f"    {label} tail:")
                for line in tail:
                    print(f"      {line}")


# ---------------------------------------------------------------------------
# Bundle materialization.
# ---------------------------------------------------------------------------


def _write_json(path: Path, body: dict) -> None:
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")


def _materialize_bundle(td: Path) -> dict:
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

    descriptor_vocabulary = bundle / "descriptor_vocabulary.json"
    _write_json(descriptor_vocabulary, _descriptor_vocabulary_body())

    return {
        "bundle": bundle,
        "source": source,
        "plan_spec": plan_spec,
        "design_system_spec": design_system_spec,
        "slide_specs_dir": slide_specs_dir,
        "image_manifest_spec": image_manifest_spec,
        "done_image_adapter_spec": done_image_adapter_spec,
        "descriptor_vocabulary": descriptor_vocabulary,
    }


# ---------------------------------------------------------------------------
# Staging phase: stub d_one chain with --descriptor-vocabulary forwarded
# through the writer AND the runner.
# ---------------------------------------------------------------------------


def _build_staging_workspace(td: Path, *, source: Path) -> Path:
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
    # This is the direct-author workflow documented at
    # scripts/materialize_image_assets.py.
    _write_json(staging / "image_manifest.json", _image_manifest_body())
    return staging


def _run_d_one_chain_in_staging(
    *, staging: Path, assets_dir: Path,
    done_image_adapter_spec: Path, descriptor_vocabulary: Path,
) -> list[StageOutcome]:
    py = sys.executable
    stages: list[tuple[str, list[str]]] = [
        (
            "done_image_adapter (--descriptor-vocabulary)",
            [
                py, str(SCRIPTS_DIR / "done_image_adapter.py"),
                "--workspace", str(staging),
                "--spec", str(done_image_adapter_spec),
                "--descriptor-vocabulary", str(descriptor_vocabulary),
            ],
        ),
        (
            "run_d_one_generation (--descriptor-vocabulary)",
            [
                py, str(SCRIPTS_DIR / "run_d_one_generation.py"),
                "--workspace", str(staging),
                "--assets-dir", str(assets_dir),
                "--allow-synthetic-bytes",
                "--descriptor-vocabulary", str(descriptor_vocabulary),
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


def _invoke_run_explicit_pipeline(
    *, workspace: Path, bundle: dict, staging: Path,
    output: Path, report_dir: Path,
) -> StageOutcome:
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


# ---------------------------------------------------------------------------
# Post-condition checks.
# ---------------------------------------------------------------------------


@dataclass
class PostCondition:
    name: str
    ok: bool
    detail: str = ""


def _check_plan_taxonomy(
    plan_path: Path, *, expected_taxonomy: dict[str, str],
) -> list[PostCondition]:
    """Re-parse the produced ``d_one_adapter_plan.json`` and assert:
      * schema_version == 4 (locked by schema enum);
      * exactly one request;
      * every taxonomy field/value supplied on the spec appears
        byte-identical on the plan request (no value drift, no field
        dropped, no field renamed)."""
    results: list[PostCondition] = []
    plan_is_file = plan_path.is_file() and not plan_path.is_symlink()
    results.append(PostCondition(
        "d_one_adapter_plan.json exists as a regular non-symlink file",
        plan_is_file,
        f"path={plan_path}, is_file={plan_path.is_file()}, "
        f"is_symlink={plan_path.is_symlink()}",
    ))
    if not plan_is_file:
        return results
    try:
        plan_doc = json.loads(plan_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        results.append(PostCondition(
            "d_one_adapter_plan.json parses as JSON",
            False, f"{type(exc).__name__}: {exc}",
        ))
        return results
    results.append(PostCondition(
        f"plan.schema_version == {_LOCKED_PLAN_SCHEMA_VERSION}",
        plan_doc.get("schema_version") == _LOCKED_PLAN_SCHEMA_VERSION,
        f"got: {plan_doc.get('schema_version')!r}",
    ))
    requests = plan_doc.get("requests")
    one_request = isinstance(requests, list) and len(requests) == 1
    results.append(PostCondition(
        "plan.requests has exactly one entry",
        one_request,
        f"got: type={type(requests).__name__}, "
        f"len={len(requests) if isinstance(requests, list) else 'n/a'}",
    ))
    if not one_request:
        return results
    req = requests[0]
    for dim, expected in sorted(expected_taxonomy.items()):
        results.append(PostCondition(
            f"plan.requests[0].{dim} == {expected!r}",
            isinstance(req, dict) and req.get(dim) == expected,
            f"got: {req.get(dim) if isinstance(req, dict) else '<not a dict>'!r}",
        ))
    return results


def _check_pptx_embeds_internal_media_only(pptx: Path) -> list[PostCondition]:
    results: list[PostCondition] = []
    try:
        zf = zipfile.ZipFile(pptx, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        results.append(PostCondition(
            "PPTX opens as a ZIP",
            False, f"{type(exc).__name__}: {exc}",
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
        ns_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
        rel_tag = f"{{{ns_rel}}}Relationship"
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
            for el in root:
                if el.tag != rel_tag:
                    continue
                target = el.attrib.get("Target", "")
                mode = el.attrib.get("TargetMode", "")
                if mode and mode != "Internal":
                    external_targets.append(
                        f"{n}: TargetMode={mode!r} Target={target!r}"
                    )
                    continue
                if _URI_SCHEME_PREFIX.match(target):
                    external_targets.append(
                        f"{n}: Target={target!r} (URI scheme)"
                    )
        results.append(PostCondition(
            "PPTX has no external / file:// / data: relationships",
            not external_targets,
            "; ".join(external_targets) if external_targets else "",
        ))
    finally:
        zf.close()
    return results


# ---------------------------------------------------------------------------
# Negative probes — exercised in-process via done_image_adapter's
# Python API so we can inspect the diagnostic without spawning a
# subprocess per probe. The same gates fire via the CLI; they share the
# implementation.
# ---------------------------------------------------------------------------


def _seed_negative_workspace(td: Path) -> Path:
    """Minimal manifest-only workspace; enough for done_image_adapter."""
    ws = td / "ws"
    _adapter._seed_workspace(ws, images=[{
        "id": SYNTHETIC_IMAGE_ID,
        "local_path": SYNTHETIC_IMAGE_LOCAL_PATH,
        "source": "d_one_local",
    }])
    return ws


def _write_vocab(path: Path, body: dict) -> None:
    _write_json(path, body)


def _negative_probes(td: Path) -> list[PostCondition]:
    """Run every negative probe. Each probe runs under its own tempdir
    so a failing gate cannot leak state into the next probe."""
    results: list[PostCondition] = []

    # ---- N1. spec carries taxonomy fields BUT --descriptor-vocabulary
    # was not supplied. The adapter cannot certify a taxonomy value it
    # cannot check, so it refuses at write time. ----
    with tempfile.TemporaryDirectory(dir=str(td)) as raw_td:
        ws = _seed_negative_workspace(Path(raw_td))
        spec = Path(raw_td) / "spec.json"
        _write_json(spec, _done_image_adapter_spec())
        rc, msg = _adapter.done_image_adapter(workspace=ws, spec=spec)
        ok = (
            rc == 1
            and "--descriptor-vocabulary" in msg
            and "taxonomy" in msg.lower()
            and not (ws / _adapter.DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(PostCondition(
            "N1: spec with taxonomy fields refused when "
            "--descriptor-vocabulary is omitted",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- N2. text_policy outside image_taxonomy.text_policy.allowed_values
    # refused. The probe value is regex-shape valid (lowercase
    # identifier, no forbidden token) so it passes the schema pattern
    # — the runtime allowed_values check is the gate that fires. ----
    with tempfile.TemporaryDirectory(dir=str(td)) as raw_td:
        ws = _seed_negative_workspace(Path(raw_td))
        spec = Path(raw_td) / "spec.json"
        bad_req = dict(_done_image_adapter_spec()["requests"][0])
        bad_req["text_policy"] = "talkative_glyph"  # not in canonical 3
        _write_json(spec, {"requests": [bad_req]})
        vocab = Path(raw_td) / "vocab.json"
        _write_vocab(vocab, _descriptor_vocabulary_body())
        rc, msg = _adapter.done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        ok = (
            rc == 1
            and "image_taxonomy.text_policy.allowed_values" in msg
            and not (ws / _adapter.DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(PostCondition(
            "N2: spec.text_policy outside allowed_values refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- N3. subject_domain outside
    # image_taxonomy.subject_domain.allowed_values refused. ----
    with tempfile.TemporaryDirectory(dir=str(td)) as raw_td:
        ws = _seed_negative_workspace(Path(raw_td))
        spec = Path(raw_td) / "spec.json"
        bad_req = dict(_done_image_adapter_spec()["requests"][0])
        # An industry / brand token would also trip the forbidden-token
        # scan; pick a regex-clean lowercase identifier so the gate
        # that fires is unambiguously the allowed_values membership
        # check (not the deny pattern).
        bad_req["subject_domain"] = "narrative_scene"
        _write_json(spec, {"requests": [bad_req]})
        vocab = Path(raw_td) / "vocab.json"
        _write_vocab(vocab, _descriptor_vocabulary_body())
        rc, msg = _adapter.done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        ok = (
            rc == 1
            and "image_taxonomy.subject_domain.allowed_values" in msg
            and not (ws / _adapter.DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(PostCondition(
            "N3: spec.subject_domain outside allowed_values refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- N4. stale taxonomy drift: hand-write a plan whose
    # rendering_style is regex-shape valid but not in the supplied
    # vocab's image_taxonomy.rendering_style.allowed_values. The
    # validator must refuse — the writer would never produce such a
    # plan (its runtime gate is tighter than the plan schema), so this
    # probe simulates the case where a plan written against an older
    # vocab is re-validated against a newer one. ----
    with tempfile.TemporaryDirectory(dir=str(td)) as raw_td:
        ws = _seed_negative_workspace(Path(raw_td))
        # Build a happy-path plan first to start from a known-good shape.
        spec = Path(raw_td) / "spec.json"
        _write_json(spec, _done_image_adapter_spec())
        vocab = Path(raw_td) / "vocab.json"
        _write_vocab(vocab, _descriptor_vocabulary_body())
        rc_write, msg_write = _adapter.done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        if rc_write != 0:
            results.append(PostCondition(
                "N4 (setup): happy-path writer produced a plan",
                False, f"rc={rc_write}, msg={msg_write!r}",
            ))
        else:
            plan_path = ws / _adapter.DEFAULT_PLAN_FILENAME
            plan_doc = json.loads(plan_path.read_text())
            # Mutate the rendering_style to a regex-shape valid token
            # that is NOT in the canonical 5-value enum locked by the
            # vocab schema (so the vocab still parses, but the plan
            # token has drifted away from the vocab's allowed_values).
            plan_doc["requests"][0]["rendering_style"] = "blueprint_style"
            plan_path.write_text(
                json.dumps(plan_doc, indent=2, sort_keys=True) + "\n"
            )
            rc, msg = _adapter.validate_plan_file(
                workspace=ws, plan=plan_path, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 1
                and "image_taxonomy.rendering_style.allowed_values" in msg
                and "drifted" in msg.lower()
            )
            results.append(PostCondition(
                "N4: stale taxonomy drift in plan refused by "
                "--validate-plan",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- N5. schema_version != 4 refused. Probe with 1 (the
    # pre-taxonomy shape an older reader would have produced) AND 5
    # (a future unknown shape). Both must trip the schema enum. ----
    for bad_version in (1, 5):
        with tempfile.TemporaryDirectory(dir=str(td)) as raw_td:
            ws = _seed_negative_workspace(Path(raw_td))
            spec = Path(raw_td) / "spec.json"
            _write_json(spec, {"requests": [{
                "id": SYNTHETIC_IMAGE_ID,
                "prompt": "an abstract pattern, no text",
            }]})
            rc_write, _ = _adapter.done_image_adapter(
                workspace=ws, spec=spec,
            )
            if rc_write != 0:
                results.append(PostCondition(
                    f"N5 (setup, version={bad_version}): writer baseline",
                    False, "happy-path writer failed",
                ))
                continue
            plan_path = ws / _adapter.DEFAULT_PLAN_FILENAME
            plan_doc = json.loads(plan_path.read_text())
            plan_doc["schema_version"] = bad_version
            plan_path.write_text(
                json.dumps(plan_doc, indent=2, sort_keys=True) + "\n"
            )
            rc, msg = _adapter.validate_plan_file(
                workspace=ws, plan=plan_path,
            )
            ok = (
                rc == 1
                and "schema_version" in msg
                and "not in enum" in msg
            )
            results.append(PostCondition(
                f"N5: plan.schema_version == {bad_version} refused by "
                f"schema enum (locked to {_LOCKED_PLAN_SCHEMA_VERSION})",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- N6. bounded forbidden token in vocab descriptor — each token
    # is matched on identifier boundaries by the descriptor pattern, so
    # the schema refuses the vocabulary at load time. The adapter
    # surfaces the failure when --descriptor-vocabulary is supplied. ----
    for token in (
        "public", "upload", "raw", "customer", "confidential",
        "screenshot", "credential", "password", "secret",
    ):
        with tempfile.TemporaryDirectory(dir=str(td)) as raw_td:
            ws = _seed_negative_workspace(Path(raw_td))
            spec = Path(raw_td) / "spec.json"
            _write_json(spec, {"requests": [{
                "id": SYNTHETIC_IMAGE_ID,
                "prompt": "an abstract pattern, no text",
                "rendering_style": "flat_vector",
            }]})
            vocab_body = _descriptor_vocabulary_body()
            vocab_body["descriptors"].append({
                "kind": "geometric_noun",
                "value": f"{token}_marker",
            })
            vocab = Path(raw_td) / "vocab.json"
            _write_vocab(vocab, vocab_body)
            rc, msg = _adapter.done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 1
                and "d_one_descriptor_vocabulary.schema.json" in msg
                and not (ws / _adapter.DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(PostCondition(
                f"N6: vocab descriptor with forbidden bounded token "
                f"{token!r} refused at the schema layer",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- N7. compound forbidden phrase in vocab descriptor across
    # every separator stacking the schema pattern locks (`_` / `-` /
    # `.` / concatenated). Each compound must trip the schema. ----
    compounds: tuple[str, ...] = (
        "full_slide", "image_search", "web_generation",
        "page_generation", "slide_generation",
    )
    for compound in compounds:
        with tempfile.TemporaryDirectory(dir=str(td)) as raw_td:
            ws = _seed_negative_workspace(Path(raw_td))
            spec = Path(raw_td) / "spec.json"
            _write_json(spec, {"requests": [{
                "id": SYNTHETIC_IMAGE_ID,
                "prompt": "an abstract pattern, no text",
                "rendering_style": "flat_vector",
            }]})
            vocab_body = _descriptor_vocabulary_body()
            vocab_body["descriptors"].append({
                "kind": "composition_adjective",
                "value": compound,
            })
            vocab = Path(raw_td) / "vocab.json"
            _write_vocab(vocab, vocab_body)
            rc, msg = _adapter.done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 1
                and "d_one_descriptor_vocabulary.schema.json" in msg
                and not (ws / _adapter.DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(PostCondition(
                f"N7: vocab descriptor with forbidden compound phrase "
                f"{compound!r} refused at the schema layer",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    return results


# ---------------------------------------------------------------------------
# Snapshot helpers (proves no committed example bytes change).
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
# Self-test entry point.
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    print("=== image-request taxonomy acceptance smoke (mock D-One chain) ===")

    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    with tempfile.TemporaryDirectory(
        prefix="szh_image_taxonomy_acceptance_smoke_",
    ) as raw_td:
        td = Path(raw_td)

        d_one_assets = td / "d_one_assets"
        d_one_assets.mkdir()
        workspace = td / "workspace"
        output = td / "deck.pptx"
        report_dir = td / "report"
        negative_root = td / "negative"
        negative_root.mkdir()

        print(f"  tempdir:         {td}")
        print(f"  workspace:       {workspace}")
        print(f"  d_one assets:    {d_one_assets}")
        print(f"  output PPTX:     {output}")
        print(f"  report dir:      {report_dir}")
        print()

        print("--- bundle materialization ---")
        bundle = _materialize_bundle(td)
        print(f"  bundle root: {bundle['bundle']}")
        print(f"  vocab:       {bundle['descriptor_vocabulary']}")
        print()

        print("--- staging phase: build staging workspace ---")
        try:
            staging = _build_staging_workspace(td, source=bundle["source"])
        except RuntimeError as exc:
            print(f"\nFAIL: staging setup failed: {exc}", file=sys.stderr)
            return _final_examples_check(examples_before, fail_already=True)
        print(f"  staging workspace: {staging}")
        print()

        print("--- staging phase: d_one chain with --descriptor-vocabulary "
              "(done_image_adapter -> run_d_one_generation -> "
              "materialize_image_assets) ---")
        d_one_outcomes = _run_d_one_chain_in_staging(
            staging=staging,
            assets_dir=d_one_assets,
            done_image_adapter_spec=bundle["done_image_adapter_spec"],
            descriptor_vocabulary=bundle["descriptor_vocabulary"],
        )
        if not all(o.ok for o in d_one_outcomes):
            print("\nFAIL: d_one chain did not all pass; aborting smoke.")
            return _final_examples_check(examples_before, fail_already=True)

        # Plan-file post-conditions — schema_version + taxonomy round-trip.
        plan_path = staging / _adapter.DEFAULT_PLAN_FILENAME
        plan_results = _check_plan_taxonomy(
            plan_path, expected_taxonomy=TAXONOMY_REQUEST,
        )
        for pc in plan_results:
            mark = "PASS" if pc.ok else "FAIL"
            suffix = f" -- {pc.detail}" if not pc.ok and pc.detail else ""
            print(f"  [{mark}] {pc.name}{suffix}")
        if not all(p.ok for p in plan_results):
            print(
                "\nFAIL: plan-file taxonomy post-conditions did not all "
                "hold; aborting smoke.",
                file=sys.stderr,
            )
            return _final_examples_check(examples_before, fail_already=True)
        rc_validate, msg_validate = _adapter.validate_plan_file(
            workspace=staging,
            plan=plan_path,
            descriptor_vocabulary=bundle["descriptor_vocabulary"],
        )
        validate_ok = rc_validate == 0
        print(
            f"  [{'PASS' if validate_ok else 'FAIL'}] "
            "done_image_adapter --validate-plan accepts the produced "
            f"taxonomy-bearing plan (rc={rc_validate})"
        )
        if not validate_ok:
            print(f"    diagnostic: {msg_validate}")
            print(
                "\nFAIL: produced plan did not re-validate with the "
                "same descriptor vocabulary; aborting smoke.",
                file=sys.stderr,
            )
            return _final_examples_check(examples_before, fail_already=True)

        # Staged asset readback.
        staged_asset = staging / SYNTHETIC_IMAGE_LOCAL_PATH
        if not (staged_asset.is_file()
                and staged_asset.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"):
            print(
                f"\nFAIL: staged asset {staged_asset} is not a "
                f"PNG-magic-valid regular file after the d_one chain.",
                file=sys.stderr,
            )
            return _final_examples_check(examples_before, fail_already=True)
        print(f"  [OK] staged asset {staged_asset.relative_to(td)} carries "
              f"PNG magic ({staged_asset.stat().st_size} bytes)")
        print()

        print("--- production phase: run_explicit_pipeline.py "
              "--assets-dir <staging> ---")
        rxp_outcome = _invoke_run_explicit_pipeline(
            workspace=workspace, bundle=bundle, staging=staging,
            output=output, report_dir=report_dir,
        )
        _print_stage(rxp_outcome)
        if not rxp_outcome.ok:
            print(
                f"\nFAIL: run_explicit_pipeline did not succeed "
                f"(rc={rxp_outcome.exit_code}); aborting smoke.",
                file=sys.stderr,
            )
            return _final_examples_check(examples_before, fail_already=True)
        prod_asset = workspace / SYNTHETIC_IMAGE_LOCAL_PATH
        if not (prod_asset.is_file()
                and prod_asset.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"):
            print(
                f"\nFAIL: production asset {prod_asset} is not a "
                f"PNG-magic-valid regular file after run_explicit_pipeline.",
                file=sys.stderr,
            )
            return _final_examples_check(examples_before, fail_already=True)
        print(f"  [OK] production asset {prod_asset.relative_to(td)} "
              f"carries PNG magic ({prod_asset.stat().st_size} bytes)")
        print()

        print("--- PPTX media post-conditions ---")
        pptx_results: list[PostCondition] = []
        pptx_is_file = output.is_file() and not output.is_symlink()
        pptx_results.append(PostCondition(
            "PPTX exists as a regular non-symlink file",
            pptx_is_file,
            f"path={output}, is_file={output.is_file()}, "
            f"is_symlink={output.is_symlink()}",
        ))
        if pptx_is_file:
            size = output.stat().st_size
            pptx_results.append(PostCondition(
                "PPTX is non-empty", size > 0, f"size={size}",
            ))
            pptx_results.extend(
                _check_pptx_embeds_internal_media_only(output)
            )
        for pc in pptx_results:
            mark = "PASS" if pc.ok else "FAIL"
            suffix = f" -- {pc.detail}" if not pc.ok and pc.detail else ""
            print(f"  [{mark}] {pc.name}{suffix}")
        if not all(p.ok for p in pptx_results):
            print(
                "\nFAIL: PPTX post-conditions did not all hold; "
                "aborting smoke.",
                file=sys.stderr,
            )
            return _final_examples_check(examples_before, fail_already=True)
        print()

        print("--- negative probes (in-process via done_image_adapter) ---")
        negative_results = _negative_probes(negative_root)
        fails = 0
        for pc in negative_results:
            mark = "PASS" if pc.ok else "FAIL"
            suffix = f" -- {pc.detail}" if not pc.ok and pc.detail else ""
            print(f"  [{mark}] {pc.name}{suffix}")
            if not pc.ok:
                fails += 1
        print()
        if fails:
            print(
                f"FAIL: {fails} negative probe(s) did not hold; the "
                f"documented fail-closed gates around the seven-"
                f"dimensional taxonomy contract are not all firing.",
                file=sys.stderr,
            )
            return _final_examples_check(examples_before, fail_already=True)

    rc_examples = _final_examples_check(examples_before, fail_already=False)
    if rc_examples != 0:
        return rc_examples
    print(
        "OK (self-test): image-request taxonomy acceptance smoke "
        "passed. MOCK D-One chain only — NOT proof of real D-One "
        "integration."
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Image-request taxonomy acceptance smoke: exercises the "
            "seven-dimensional D-One prompt-intent taxonomy "
            "(rendering_style / palette_family / image_role / "
            "layout_pattern / modifier / text_policy / subject_domain) "
            "through the mockable local D-One stub chain "
            "(done_image_adapter -> run_d_one_generation -> "
            "materialize_image_assets) and into the existing "
            "explicit-input editable-PPTX path, plus negative probes "
            "around the documented fail-closed taxonomy gates. MOCK / "
            "stub acceptance only — NOT real D-One integration; no "
            "MCP, no public network, no model API, no image search, "
            "no Qoder, no external service."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run the full chain under tempfile.TemporaryDirectory() "
            "and verify every post-condition: plan schema_version == "
            "2; every taxonomy field/value preserved byte-identical on "
            "the produced plan; final PPTX embeds at least one "
            "internal ppt/media PNG/JPG/JPEG; every documented "
            "negative gate fires. The smoke has no other mode today; "
            "--self-test is required."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: image_taxonomy_acceptance_smoke.py requires "
            "--self-test (no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
