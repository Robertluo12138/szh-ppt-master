#!/usr/bin/env python3
"""operator_supplied_metadata_smoke.py

Tempdir-only **supplied-operator-metadata acceptance smoke** for the
local image-folder -> editable-PPT review-package lane.

The wrapper ``scripts/operator_images_to_review_package.py`` accepts two
optional flags — ``--manifest`` and ``--generated-provenance`` — that let
an operator hand in REVIEWED metadata (custom per-slide ``slide_title`` /
``alt_text`` / ``intended_use`` in the manifest; per-image
``generator_source`` / ``intent_summary`` / ``placement_role`` /
``text_policy`` / ``subject_domain`` / optional ``custom_descriptor`` in
the generated-provenance sidecar) in place of the default templates, so
the produced ``approved_plan.json`` and review-package ``summary.json``
reflect the operator's text rather than the generated defaults.

This smoke makes that supplied-metadata workflow visible at the top-level
acceptance surface (``core_editable_ppt_acceptance.py`` runs it as a
delegated ``--self-test`` subprocess). The wrapper's OWN self-test already
touches the metadata flags (T21 one-command, T25 plan/resume), but it
asserts only by raw-text substring presence and does NOT re-invoke the
read-only validator on the produced packages. This smoke is the additive
end-to-end gate:

  S1 — ONE-COMMAND mode with ``--manifest`` + ``--generated-provenance``:
       drive the wrapper into a per-run tempdir, then
         * re-validate the produced ``<out-dir>/review_package`` with
           ``scripts/validate_operator_review_package.py --out-dir`` (rc 0);
         * confirm every canonical review-package file/dir is present;
         * assert, KEYED BY FILENAME, that the custom ``slide_title`` and
           ``intent_summary`` plus every supplied provenance field
           (``generator_source`` / ``placement_role`` / ``text_policy`` /
           ``subject_domain`` / ``custom_descriptor``) landed in
           ``approved_plan.json`` (per-slide ``images[]`` rows + the
           ``generated_provenance`` evidence block) AND in
           ``review_package/summary.json`` (per-image ``image_provenance[]``
           rows, where the manifest title surfaces as
           ``operator_slide_title``, + the ``generated_provenance`` block).

  S2 — TWO-STEP reviewed mode with the SAME metadata: ``--plan`` (stages
       the bundle + reviewed plan and STOPS — no ``review_package`` yet,
       but ``approved_plan.json`` already carries the custom fields) then
       ``--resume`` (builds + internally validates the package). The
       resumed ``<out-dir>/review_package`` is then re-validated with
       ``validate_operator_review_package.py`` and asserted with the same
       keyed checks as S1.

  S3 — TEMPLATES-ONLY ROUND-TRIP: run ``--templates-only`` to GENERATE
       the two editable starter files (asserting it writes EXACTLY
       ``manifest.json`` + ``generated_provenance.json`` and nothing
       else), programmatically EDIT their safe custom fields in place,
       then feed the EDITED templates through ``--plan`` (still no
       ``review_package`` yet) and ``--resume`` (re-validated package),
       asserting the edited values surface in ``approved_plan.json`` +
       ``review_package/summary.json``. Unlike S1 / S2 — which hand-author
       the reviewed metadata — S3 proves the helper's OWN
       ``--templates-only`` output is editable and consumable end-to-end
       (the metadata-authoring shortcut closes the loop with the build).

The two custom titles / intents / provenance value sets are deliberately
DISTINCT from the helper's generated defaults, so a green run proves the
SUPPLIED metadata flowed end-to-end (not a default that happens to match).

Stdlib only. TEMP-ONLY — every artifact is written under
``tempfile.TemporaryDirectory()`` and removed on exit; nothing is written
under the repo tree (the smoke snapshots ``REPO_ROOT/examples`` +
``REPO_ROOT/scripts`` and refuses any mutation). LOCAL-ONLY — never calls
D-One, MCP, Qoder, a public network, a model API, an image search, or
telemetry; never generates images; never claims real-D-One success.

The script has only a ``--self-test`` invocation surface. It exits 0 on
full pass, 1 on any scenario failure or repo mutation, 2 on a missing
flag.

Usage:
  python3 scripts/operator_supplied_metadata_smoke.py --self-test
"""
from __future__ import annotations

import sys

# Set BEFORE the first-party import below so importing the wrapper module
# (and its transitive helper imports) never drops .pyc files under
# ``scripts/`` and trips the committed-tree snapshot.
sys.dont_write_bytecode = True

import argparse
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Reuse the wrapper's synthetic-image fixture writer (single source of
# truth for byte-valid PNG / JPEG fixtures the helper accepts) and the
# canonical review-package file/dir names. Importing the wrapper has no
# side effect beyond sys.path setup + its own stdlib-only helper imports.
from operator_images_to_review_package import (  # noqa: E402
    _REVIEW_PACKAGE_DIRS,
    _REVIEW_PACKAGE_FILES,
    _write_synthetic_images,
)

WRAPPER_PATH = SCRIPTS_DIR / "operator_images_to_review_package.py"
VALIDATOR_PATH = SCRIPTS_DIR / "validate_operator_review_package.py"


@dataclass
class _ToolOutcome:
    name: str
    rc: int
    stdout: str
    stderr: str


@dataclass
class _ProbeResult:
    name: str
    ok: bool
    detail: str


def _run(name: str, cmd: list[str]) -> _ToolOutcome:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env,
    )
    return _ToolOutcome(
        name=name, rc=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


def _tail(outcome: _ToolOutcome, *, lines: int = 20) -> str:
    combined = (outcome.stdout or "") + (outcome.stderr or "")
    parts = [ln for ln in combined.strip().splitlines() if ln.strip()]
    return " | ".join(parts[-lines:]) if parts else "(no output)"


# --------------------------------------------------------------------------
# Fixture metadata. Custom values are DISTINCT from the helper's generated
# defaults so a passing assertion proves the supplied text actually flowed.
# Keyed by image filename so assertions are order-independent.
# --------------------------------------------------------------------------
def _expected_metadata(
    png_name: str, jpg_name: str,
) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, str]]]:
    titles = {
        png_name: "Alpha accent intro",
        jpg_name: "Beta accent divider",
    }
    intents = {
        png_name: "Alpha accent marker, operator declared, local only",
        jpg_name: "Beta accent marker, operator declared, local only",
    }
    provenance = {
        png_name: {
            "generator_source": "mock_generated",
            "placement_role": "hero_page",
            "text_policy": "decorative_glyphs",
            "subject_domain": "background_pattern",
            "custom_descriptor": "alpha_accent",
        },
        jpg_name: {
            "generator_source": "operator_declared_generated",
            "placement_role": "local_region",
            "text_policy": "caption_safe",
            "subject_domain": "icon_concept",
        },
    }
    return titles, intents, provenance


def _write_reviewed_manifest(
    path: Path, png_name: str, jpg_name: str, titles: dict[str, str],
) -> None:
    body = {
        "schema_version": "1",
        "images": [
            {
                "filename": png_name,
                "slide_title": titles[png_name],
                "alt_text": "Operator alpha accent for the intro slide",
                "intended_use": "spot illustration",
            },
            {
                "filename": jpg_name,
                "slide_title": titles[jpg_name],
                "alt_text": "Operator beta accent for the divider slide",
                "intended_use": "decorative pattern",
            },
        ],
    }
    path.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )


def _write_reviewed_provenance(
    path: Path,
    png_name: str,
    jpg_name: str,
    intents: dict[str, str],
    provenance: dict[str, dict[str, str]],
) -> None:
    def entry(name: str) -> dict[str, str]:
        prov = provenance[name]
        row = {
            "filename": name,
            "generator_source": prov["generator_source"],
            "intent_summary": intents[name],
            "placement_role": prov["placement_role"],
            "subject_domain": prov["subject_domain"],
            "text_policy": prov["text_policy"],
        }
        if "custom_descriptor" in prov:
            row["custom_descriptor"] = prov["custom_descriptor"]
        return row

    body = {
        "schema_version": "1",
        "entries": [entry(png_name), entry(jpg_name)],
    }
    path.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )


def _edit_templates_in_place(
    manifest: Path,
    sidecar: Path,
    titles: dict[str, str],
    intents: dict[str, str],
    provenance: dict[str, dict[str, str]],
) -> list[str]:
    """Overlay the DISTINCT custom fields onto the two ``--templates-only``
    starter files IN PLACE, keyed by filename: ``slide_title`` in the
    manifest; ``intent_summary`` + ``generator_source`` / ``placement_role``
    / ``text_policy`` / ``subject_domain`` (+ optional ``custom_descriptor``)
    in the sidecar. Only EXISTING keys are overwritten — plus the single
    allowed optional ``custom_descriptor`` — so the edited files still
    satisfy the helper's exact-key manifest / sidecar contracts. Returns
    failure strings if either template's shape drifted from what
    ``--templates-only`` emits, so a template-format change surfaces here
    rather than as a confusing downstream validator error."""
    fails: list[str] = []

    try:
        man = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"templates-only manifest unreadable: {exc}"]
    man_rows = man.get("images") if isinstance(man, dict) else None
    if not isinstance(man_rows, list):
        return ["templates-only manifest missing images[] list"]
    man_by_name = {
        r.get("filename"): r for r in man_rows if isinstance(r, dict)
    }
    for name in titles:
        row = man_by_name.get(name)
        if row is None:
            fails.append(f"templates-only manifest missing entry for {name!r}")
            continue
        row["slide_title"] = titles[name]
    manifest.write_text(
        json.dumps(man, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )

    try:
        gp = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return fails + [
            f"templates-only generated_provenance unreadable: {exc}"
        ]
    gp_rows = gp.get("entries") if isinstance(gp, dict) else None
    if not isinstance(gp_rows, list):
        return fails + [
            "templates-only generated_provenance missing entries[] list"
        ]
    gp_by_name = {
        e.get("filename"): e for e in gp_rows if isinstance(e, dict)
    }
    for name in titles:
        entry = gp_by_name.get(name)
        if entry is None:
            fails.append(
                f"templates-only provenance missing entry for {name!r}"
            )
            continue
        entry["intent_summary"] = intents[name]
        for key, want in provenance[name].items():
            entry[key] = want
    sidecar.write_text(
        json.dumps(gp, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return fails


# --------------------------------------------------------------------------
# Assertions over the produced artifacts.
# --------------------------------------------------------------------------
def _check_package_files(review_package: Path) -> list[str]:
    fails: list[str] = []
    for name in _REVIEW_PACKAGE_FILES:
        p = review_package / name
        if p.is_symlink() or not p.is_file():
            fails.append(f"review package missing regular file {name!r}")
    for name in _REVIEW_PACKAGE_DIRS:
        p = review_package / name
        if p.is_symlink() or not p.is_dir():
            fails.append(f"review package missing directory {name!r}")
    return fails


def _check_plan(
    plan_path: Path,
    titles: dict[str, str],
    intents: dict[str, str],
    provenance: dict[str, dict[str, str]],
) -> list[str]:
    fails: list[str] = []
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"approved_plan.json unreadable: {exc}"]
    rows = data.get("images")
    if not isinstance(rows, list) or len(rows) != len(titles):
        return [
            f"approved_plan.images is not a {len(titles)}-element list "
            f"(got {type(rows).__name__})"
        ]
    by_name = {r.get("filename"): r for r in rows if isinstance(r, dict)}
    for name in titles:
        row = by_name.get(name)
        if row is None:
            fails.append(f"approved_plan missing images row for {name!r}")
            continue
        if row.get("slide_title") != titles[name]:
            fails.append(
                f"approved_plan {name} slide_title="
                f"{row.get('slide_title')!r} != {titles[name]!r}"
            )
        if row.get("intent_summary") != intents[name]:
            fails.append(
                f"approved_plan {name} intent_summary="
                f"{row.get('intent_summary')!r} != {intents[name]!r}"
            )
        for key, want in provenance[name].items():
            if row.get(key) != want:
                fails.append(
                    f"approved_plan {name} {key}={row.get(key)!r} != "
                    f"{want!r}"
                )
    gp = data.get("generated_provenance")
    if not (isinstance(gp, dict) and gp.get("entry_count") == len(titles)):
        fails.append(
            f"approved_plan.generated_provenance block missing / wrong "
            f"entry_count (got {gp!r})"
        )
    return fails


def _check_summary(
    summary_path: Path,
    titles: dict[str, str],
    intents: dict[str, str],
    provenance: dict[str, dict[str, str]],
) -> list[str]:
    fails: list[str] = []
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"summary.json unreadable: {exc}"]
    rows = data.get("image_provenance")
    if not isinstance(rows, list) or len(rows) != len(titles):
        return [
            f"summary.image_provenance is not a {len(titles)}-element list "
            f"(got {type(rows).__name__})"
        ]
    by_name = {
        r.get("operator_filename"): r for r in rows if isinstance(r, dict)
    }
    for name in titles:
        row = by_name.get(name)
        if row is None:
            fails.append(
                f"summary missing image_provenance row for {name!r}"
            )
            continue
        # The manifest title surfaces in the summary as operator_slide_title.
        if row.get("operator_slide_title") != titles[name]:
            fails.append(
                f"summary {name} operator_slide_title="
                f"{row.get('operator_slide_title')!r} != {titles[name]!r}"
            )
        if row.get("intent_summary") != intents[name]:
            fails.append(
                f"summary {name} intent_summary="
                f"{row.get('intent_summary')!r} != {intents[name]!r}"
            )
        for key, want in provenance[name].items():
            if row.get(key) != want:
                fails.append(
                    f"summary {name} {key}={row.get(key)!r} != {want!r}"
                )
    gp = data.get("generated_provenance")
    if not (isinstance(gp, dict) and gp.get("entry_count") == len(titles)):
        fails.append(
            f"summary.generated_provenance block missing / wrong "
            f"entry_count (got {gp!r})"
        )
    return fails


def _revalidate_and_assert(
    out_dir: Path,
    titles: dict[str, str],
    intents: dict[str, str],
    provenance: dict[str, dict[str, str]],
) -> list[str]:
    """Re-validate the produced review package read-only AND assert the
    supplied metadata surfaced in both ``approved_plan.json`` and
    ``review_package/summary.json``. Returns a list of failure strings."""
    fails: list[str] = []
    review_package = out_dir / "review_package"
    fails.extend(_check_package_files(review_package))

    validator = _run(
        "validate_operator_review_package",
        [
            sys.executable, str(VALIDATOR_PATH),
            "--out-dir", str(review_package),
        ],
    )
    if validator.rc != 0:
        fails.append(
            f"validate_operator_review_package rc={validator.rc}: "
            f"{_tail(validator)}"
        )

    fails.extend(
        _check_plan(out_dir / "approved_plan.json", titles, intents, provenance)
    )
    fails.extend(
        _check_summary(
            review_package / "summary.json", titles, intents, provenance,
        )
    )
    return fails


def _stage_fixtures(
    td: Path,
) -> tuple[Path, Path, Path, dict[str, str], dict[str, str], dict[str, dict[str, str]]]:
    """Write the 2 synthetic images + reviewed manifest + reviewed sidecar
    into ``td`` and return (images_dir, manifest, sidecar, titles, intents,
    provenance)."""
    images_dir = td / "images"
    images_dir.mkdir()
    _write_synthetic_images(images_dir)
    names = sorted(p.name for p in images_dir.iterdir() if p.is_file())
    png_name = next(n for n in names if n.lower().endswith(".png"))
    jpg_name = next(
        n for n in names if n.lower().endswith((".jpg", ".jpeg"))
    )
    titles, intents, provenance = _expected_metadata(png_name, jpg_name)
    manifest = td / "manifest.json"
    sidecar = td / "generated_provenance.json"
    _write_reviewed_manifest(manifest, png_name, jpg_name, titles)
    _write_reviewed_provenance(
        sidecar, png_name, jpg_name, intents, provenance,
    )
    return images_dir, manifest, sidecar, titles, intents, provenance


# --------------------------------------------------------------------------
# Scenarios.
# --------------------------------------------------------------------------
def _scenario_one_command() -> list[_ProbeResult]:
    results: list[_ProbeResult] = []
    with tempfile.TemporaryDirectory(prefix="osm-onecmd-") as raw_td:
        td = Path(raw_td)
        images_dir, manifest, sidecar, titles, intents, provenance = (
            _stage_fixtures(td)
        )
        out_dir = td / "oneshot_out"
        run = _run(
            "wrapper one-command (--manifest + --generated-provenance)",
            [
                sys.executable, str(WRAPPER_PATH),
                "--images-dir", str(images_dir),
                "--out-dir", str(out_dir),
                "--manifest", str(manifest),
                "--generated-provenance", str(sidecar),
            ],
        )
        if run.rc != 0:
            results.append(_ProbeResult(
                "S1 one-command supplied-metadata run", False,
                f"wrapper rc={run.rc}: {_tail(run)}",
            ))
            return results
        fails = _revalidate_and_assert(out_dir, titles, intents, provenance)
        results.append(_ProbeResult(
            "S1 one-command supplied-metadata package re-validated + keyed",
            not fails, "; ".join(fails) if fails else "ok",
        ))
    return results


def _scenario_plan_then_resume() -> list[_ProbeResult]:
    results: list[_ProbeResult] = []
    with tempfile.TemporaryDirectory(prefix="osm-planresume-") as raw_td:
        td = Path(raw_td)
        images_dir, manifest, sidecar, titles, intents, provenance = (
            _stage_fixtures(td)
        )
        out_dir = td / "reviewed_out"

        plan = _run(
            "wrapper --plan (--manifest + --generated-provenance)",
            [
                sys.executable, str(WRAPPER_PATH), "--plan",
                "--images-dir", str(images_dir),
                "--out-dir", str(out_dir),
                "--manifest", str(manifest),
                "--generated-provenance", str(sidecar),
            ],
        )
        plan_fails: list[str] = []
        if plan.rc != 0:
            plan_fails.append(f"--plan rc={plan.rc}: {_tail(plan)}")
        else:
            # --plan must STOP before any review package is built.
            if (out_dir / "review_package").exists():
                plan_fails.append(
                    "review_package/ leaked at --plan time (must not "
                    "exist until --resume)"
                )
            # The reviewed plan must already carry the custom fields.
            plan_fails.extend(
                _check_plan(
                    out_dir / "approved_plan.json",
                    titles, intents, provenance,
                )
            )
        results.append(_ProbeResult(
            "S2 --plan stages reviewed metadata into approved_plan",
            not plan_fails, "; ".join(plan_fails) if plan_fails else "ok",
        ))
        if plan_fails:
            return results

        resume = _run(
            "wrapper --resume",
            [
                sys.executable, str(WRAPPER_PATH), "--resume",
                "--out-dir", str(out_dir),
            ],
        )
        resume_fails: list[str] = []
        if resume.rc != 0:
            resume_fails.append(f"--resume rc={resume.rc}: {_tail(resume)}")
        else:
            resume_fails.extend(
                _revalidate_and_assert(out_dir, titles, intents, provenance)
            )
        results.append(_ProbeResult(
            "S2 --resume builds re-validated supplied-metadata package",
            not resume_fails,
            "; ".join(resume_fails) if resume_fails else "ok",
        ))
    return results


def _scenario_templates_roundtrip() -> list[_ProbeResult]:
    """S3 — full ``--templates-only`` round-trip: GENERATE the two starter
    templates, EDIT their safe custom fields in place, then feed the EDITED
    files through ``--plan`` / ``--resume`` and assert the package validates
    and carries the edited values. This is the only scenario that proves the
    helper's OWN ``--templates-only`` output (not hand-authored JSON) is
    editable and consumable by the build workflow."""
    results: list[_ProbeResult] = []
    with tempfile.TemporaryDirectory(prefix="osm-templates-") as raw_td:
        td = Path(raw_td)
        images_dir = td / "images"
        images_dir.mkdir()
        _write_synthetic_images(images_dir)
        names = sorted(p.name for p in images_dir.iterdir() if p.is_file())
        png_name = next(n for n in names if n.lower().endswith(".png"))
        jpg_name = next(
            n for n in names if n.lower().endswith((".jpg", ".jpeg"))
        )
        titles, intents, provenance = _expected_metadata(png_name, jpg_name)

        # Step 1 — --templates-only writes EXACTLY the two editable starter
        # files (manifest.json + generated_provenance.json) and nothing
        # else: no bundle/, approved_plan.json, review_package/, or *.pptx.
        templates_out = td / "templates_out"
        tonly = _run(
            "wrapper --templates-only",
            [
                sys.executable, str(WRAPPER_PATH), "--templates-only",
                "--images-dir", str(images_dir),
                "--out-dir", str(templates_out),
            ],
        )
        tonly_fails: list[str] = []
        if tonly.rc != 0:
            tonly_fails.append(
                f"--templates-only rc={tonly.rc}: {_tail(tonly)}"
            )
        else:
            entries = sorted(p.name for p in templates_out.iterdir())
            if entries != ["generated_provenance.json", "manifest.json"]:
                tonly_fails.append(
                    f"--templates-only --out-dir is not exactly the two "
                    f"templates: {entries!r}"
                )
            decks = sorted(str(p) for p in templates_out.rglob("*.pptx"))
            if decks:
                tonly_fails.append(
                    f"--templates-only produced PPTX output: {decks!r}"
                )
        results.append(_ProbeResult(
            "S3 --templates-only writes exactly manifest.json + "
            "generated_provenance.json",
            not tonly_fails, "; ".join(tonly_fails) if tonly_fails else "ok",
        ))
        if tonly_fails:
            return results

        manifest = templates_out / "manifest.json"
        sidecar = templates_out / "generated_provenance.json"

        # Step 2 — programmatically edit the generated templates' safe
        # custom fields in place (values DISTINCT from the templates-only
        # defaults, so a green run proves the EDITED text flowed).
        edit_fails = _edit_templates_in_place(
            manifest, sidecar, titles, intents, provenance,
        )
        results.append(_ProbeResult(
            "S3 edits safe custom fields in both --templates-only files",
            not edit_fails, "; ".join(edit_fails) if edit_fails else "ok",
        ))
        if edit_fails:
            return results

        # Step 3 — --plan from the EDITED templates stages the bundle +
        # reviewed plan and STOPS (no review_package yet); the staged
        # approved_plan.json already carries the edited values.
        out_dir = td / "reviewed_out"
        plan = _run(
            "wrapper --plan (edited --templates-only metadata)",
            [
                sys.executable, str(WRAPPER_PATH), "--plan",
                "--images-dir", str(images_dir),
                "--out-dir", str(out_dir),
                "--manifest", str(manifest),
                "--generated-provenance", str(sidecar),
            ],
        )
        plan_fails: list[str] = []
        if plan.rc != 0:
            plan_fails.append(f"--plan rc={plan.rc}: {_tail(plan)}")
        else:
            if (out_dir / "review_package").exists():
                plan_fails.append(
                    "review_package/ leaked at --plan time (must not "
                    "exist until --resume)"
                )
            plan_fails.extend(
                _check_plan(
                    out_dir / "approved_plan.json",
                    titles, intents, provenance,
                )
            )
        results.append(_ProbeResult(
            "S3 --plan stages edited-template metadata into approved_plan",
            not plan_fails, "; ".join(plan_fails) if plan_fails else "ok",
        ))
        if plan_fails:
            return results

        # Step 4 — --resume builds + internally validates the package; the
        # produced review_package is re-validated read-only and the edited
        # values asserted in approved_plan.json + summary.json.
        resume = _run(
            "wrapper --resume",
            [
                sys.executable, str(WRAPPER_PATH), "--resume",
                "--out-dir", str(out_dir),
            ],
        )
        resume_fails: list[str] = []
        if resume.rc != 0:
            resume_fails.append(f"--resume rc={resume.rc}: {_tail(resume)}")
        else:
            resume_fails.extend(
                _revalidate_and_assert(out_dir, titles, intents, provenance)
            )
        results.append(_ProbeResult(
            "S3 --resume builds re-validated edited-template package",
            not resume_fails,
            "; ".join(resume_fails) if resume_fails else "ok",
        ))
    return results


# --------------------------------------------------------------------------
# Committed-tree guard.
# --------------------------------------------------------------------------
def _snapshot_dir(d: Path) -> dict[str, tuple[str, bytes]]:
    out: dict[str, tuple[str, bytes]] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.rglob("*")):
        rel = str(p.relative_to(d))
        if p.is_symlink():
            try:
                tgt = os.readlink(p).encode("utf-8", "surrogateescape")
            except OSError:
                tgt = b"<unreadable-symlink-target>"
            out[rel] = ("symlink", tgt)
        elif p.is_file():
            out[rel] = ("file", p.read_bytes())
        elif p.is_dir():
            out[rel] = ("dir", b"")
        else:
            out[rel] = ("other", b"")
    return out


def _diff_snapshot(
    label: str,
    before: dict[str, tuple[str, bytes]],
    after: dict[str, tuple[str, bytes]],
) -> list[str]:
    if before == after:
        return []
    changed = sorted(
        k for k in set(before) | set(after) if before.get(k) != after.get(k)
    )
    return [f"{label} was mutated by self-test (changed: {changed!r})"]


def _run_self_test() -> int:
    print("=== operator_supplied_metadata_smoke --self-test ===")
    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    scripts_before = _snapshot_dir(REPO_ROOT / "scripts")

    results: list[_ProbeResult] = []
    results.extend(_scenario_one_command())
    results.extend(_scenario_plan_then_resume())
    results.extend(_scenario_templates_roundtrip())

    repo_fails = _diff_snapshot(
        "REPO_ROOT/examples", examples_before,
        _snapshot_dir(REPO_ROOT / "examples"),
    )
    repo_fails += _diff_snapshot(
        "REPO_ROOT/scripts", scripts_before,
        _snapshot_dir(REPO_ROOT / "scripts"),
    )
    results.append(_ProbeResult(
        "committed tree (examples + scripts) byte-identical",
        not repo_fails, "; ".join(repo_fails) if repo_fails else "ok",
    ))

    print("--- self-test results ---")
    rc = 0
    for r in results:
        flag = "[PASS]" if r.ok else "[FAIL]"
        print(f"  {flag} {r.name}: {r.detail}")
        if not r.ok:
            rc = 1
    if rc == 0:
        print(
            "OK: supplied-operator-metadata flows end-to-end through "
            "one-command, --plan/--resume, AND the --templates-only "
            "round-trip (generate templates -> edit -> --plan -> --resume); "
            "every produced review package re-validates and carries the "
            "custom slide_title / intent_summary / provenance fields; "
            "REPO_ROOT/examples and REPO_ROOT/scripts are byte-identical "
            "before and after."
        )
    else:
        print("FAIL: one or more supplied-metadata probes failed.")
    return rc


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Tempdir-only supplied-operator-metadata acceptance smoke for "
            "the local image-folder -> editable-PPT review-package lane. "
            "--manifest + --generated-provenance in one-command AND "
            "--plan/--resume modes, plus a --templates-only round-trip "
            "(generate the two starter templates, edit them, feed them "
            "back through --plan/--resume), re-validates every produced "
            "package with scripts/validate_operator_review_package.py, and "
            "asserts the custom slide_title / intent_summary / provenance "
            "fields surface in approved_plan.json and summary.json. "
            "Stdlib-only. "
            "TEMP-ONLY. LOCAL-ONLY — no D-One / MCP / Qoder / network / "
            "model API / image search / telemetry."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Required: run the supplied-metadata scenarios under per-run "
            "tempdirs. The script has no other CLI surface today."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: operator_supplied_metadata_smoke.py requires "
            "--self-test (no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
