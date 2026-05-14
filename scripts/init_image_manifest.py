#!/usr/bin/env python3
"""Stage-6 (Image Manifest) workspace bridge: produce image_manifest.json.

Bridges an already-stage-5-initialized workspace (the one
``scripts/init_workspace.py`` + ``scripts/init_deck_brief.py`` +
``scripts/init_deck_plan.py`` + ``scripts/init_design_system.py`` +
``scripts/init_slide_plans.py`` produce — i.e. the workspace ships
``source_manifest.json`` + ``input/source.md`` + ``deck_brief.json`` +
``deck_plan.json`` + ``design_system.json`` + a non-empty
``slide_plans/`` directory) into a schema-valid
``<workspace>/image_manifest.json`` whose content comes from EXACTLY
ONE explicit caller input:

  --spec <path-to-image_manifest.json>
    A JSON file whose shape is exactly the image_manifest candidate to
    be written. The helper validates the spec against
    ``schemas/image_manifest.schema.json``, refuses duplicate
    ``images[].id``, refuses unsafe ``images[].local_path``, and
    requires every referenced ``local_path`` to resolve inside the
    workspace to a real regular non-symlink file. The helper also
    cross-checks that every ``slide_plan.image_refs[*]`` value is
    declared in ``images[].id``; an empty ``images`` list is accepted
    ONLY when no slide_plan references any image.

This is **Stage-6 contract support only**. It is NOT a full
prompt/report/Markdown-to-PPTX automation. The helper deliberately
does NOT:

  - read or parse any business content out of ``input/source.md``
    — it invokes the Stage-1/Stage-2 bridge
    (``check_source_manifest_bridge``), which reads the file's
    bytes ONLY for byte-level integrity checks (UTF-8 decode
    validity; ``source.byte_count`` / ``source.line_count`` /
    ``source.sha256`` match against the manifest); the decoded
    string is discarded inside the bridge, and the helper itself
    never opens the source body at all — no heading / bullet /
    paragraph / sentence parsing, no token inference, no copy of
    any source bytes into the image_manifest;
  - generate any image asset, call D-One / Qoder / any public
    network / image-generation / external service — the caller is
    responsible for the underlying asset bytes;
  - emit any artifact other than ``<workspace>/image_manifest.json``;
  - produce ``render_models/*``, ``svg_previews/*``, or any
    ``.pptx``;
  - mutate or inspect any file outside ``--workspace`` (the only
    file tree outside the workspace the helper opens is
    ``--spec`` for the spec bytes).

After this script succeeds, ``scripts/run_pipeline.py`` can take
over for stages 7-10.

Stdlib-only. Deterministic — given the same workspace + spec, the
produced manifest is byte-identical. The manifest content is exactly
what the caller provided; nothing derived from clock, environment,
or file order ends up in the artifact.

Fail-closed gates (every gate aborts the run and writes nothing):

  --workspace
    * must be an existing directory; URI-shaped values refused; the
      workspace itself must not be a symlink;
    * must contain ``source_manifest.json`` + ``deck_brief.json`` +
      ``deck_plan.json`` + ``design_system.json`` all as **regular
      in-workspace files** (symlinks refused);
    * each artifact validates against its schema; the Stage-1/Stage-2
      bridge (manifest <-> input/source.md <-> deck_brief.source_refs)
      must pass;
    * ``deck_plan.json`` must additionally satisfy the planner-
      semantics cross-checks ``init_deck_plan.py`` applies before it
      writes a Stage-3 artifact — re-using
      ``init_deck_plan._cross_check_planner_semantics`` so a
      semantically-broken prior stage (duplicate / non-contiguous
      indices, section coverage gaps, undeclared
      ``slide.source_refs``) is refused before Stage-6 advances;
    * must contain a non-empty ``slide_plans/`` directory whose every
      ``*.json`` file is a regular file (symlinks refused) and
      validates against ``schemas/slide_plan.schema.json``;
    * Stage-5 slide-plan coverage: the union of ``slide_plan.index``
      values must exactly cover ``deck_plan.slides[].index`` — no
      duplicate indices across slide_plan files, no missing slides,
      no orphan slide_plans — and each pair's ``layout`` / ``title``
      must agree with the deck_plan slide. Re-runs the same coverage
      gate ``init_slide_plans.py`` applies before writing a Stage-5
      artifact (slot-coverage against the per-layout file is NOT
      re-run here because it needs the template root; Stage-5
      already enforced it on the producer side);
    * ``image_manifest.json`` at the output path must NOT already
      exist as a symlink (broken or resolvable) AND must NOT already
      exist as a regular file. A pre-existing regular file is
      preserved byte-identical (no overwrite).

  --spec
    * must be an existing regular file; URI-shaped values refused;
      symlinks (broken or resolvable) refused;
    * must parse as JSON and decode to an object (list-rooted JSON
      and other non-object roots refused);
    * must validate against ``schemas/image_manifest.schema.json``;
    * no two ``images[*].id`` values may be equal;
    * every ``images[*].local_path`` must pass
      ``validate_scaffold.local_path_is_safe`` AND resolve inside
      ``--workspace``; the resolved target must be an existing
      regular file that is not itself a symlink.

  cross-check
    * every ``slide_plan.image_refs[*]`` value across every
      ``<workspace>/slide_plans/*.json`` must appear in
      ``images[*].id``;
    * an empty ``images`` list is accepted ONLY when no
      ``slide_plan.image_refs[*]`` references any id (otherwise the
      missing-id cross-check fires).

The candidate manifest is schema-validated **in memory** before any
write, then written deterministically to
``<workspace>/image_manifest.json`` (sorted keys, indent=2, trailing
newline), then **re-validated on disk** via
``scripts/validate_artifacts.py``. A post-write re-validation failure
(return errors OR raise) removes the just-written manifest so the
workspace returns to its pre-call state. The catch clause is
``(Exception, SystemExit)`` so ``validate_artifact``'s SystemExit
branch on read-errors still routes through rollback.
``KeyboardInterrupt`` is intentionally not caught.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "schemas"

sys.path.insert(0, str(SCRIPTS_DIR))

from validate_artifacts import validate_artifact  # noqa: E402
from validate_scaffold import (  # noqa: E402
    local_path_is_safe,
    _resolves_within,
)
from validate_workspace import (  # noqa: E402
    check_source_manifest_bridge,
    SOURCE_MANIFEST_FILENAME,
)
from init_deck_plan import _cross_check_planner_semantics  # noqa: E402

DECK_BRIEF_SCHEMA = SCHEMAS_DIR / "deck_brief.schema.json"
DECK_PLAN_SCHEMA = SCHEMAS_DIR / "deck_plan.schema.json"
DESIGN_SYSTEM_SCHEMA = SCHEMAS_DIR / "design_system.schema.json"
SLIDE_PLAN_SCHEMA = SCHEMAS_DIR / "slide_plan.schema.json"
IMAGE_MANIFEST_SCHEMA = SCHEMAS_DIR / "image_manifest.schema.json"

DECK_BRIEF_FILENAME = "deck_brief.json"
DECK_PLAN_FILENAME = "deck_plan.json"
DESIGN_SYSTEM_FILENAME = "design_system.json"
SLIDE_PLANS_DIRNAME = "slide_plans"
IMAGE_MANIFEST_FILENAME = "image_manifest.json"

_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _has_uri_scheme(s: str) -> bool:
    return bool(_URI_SCHEME_PREFIX.match(s))


def _refuse_symlink(path: Path, label: str) -> tuple[bool, str]:
    """Return (is_symlink, fail_message). Same anti-pattern the other
    init_* helpers reject: ``Path.exists()`` returns False for a
    dangling link and ``Path.is_file()`` follows symlinks, so an
    explicit ``is_symlink()`` check is the only way to refuse both
    broken and resolvable links."""
    if not path.is_symlink():
        return False, ""
    try:
        target = str(path.readlink())
    except OSError:
        target = "<unreadable>"
    return True, (
        f"FAIL: {path} ({label}) is a symlink (-> {target}); "
        f"init_image_manifest refuses to follow it (broken or not). "
        f"Remove or rename the symlink and re-run."
    )


def _schema_validate(value: dict, schema_path: Path) -> list[str]:
    """In-memory schema validation reusing validate_artifacts._validate."""
    schema = json.loads(schema_path.read_text())
    from validate_artifacts import _validate  # noqa: WPS433
    errors: list[str] = []
    _validate(value, schema, "<root>", errors)
    return errors


def init_image_manifest(
    *,
    workspace: Path,
    spec: Path,
) -> tuple[int, str]:
    """Run the full Stage-6 bridge. Returns (exit_code, message).

    Filesystem contract: preflight failures (bad inputs, missing /
    schema-invalid prior-stage artifacts, pre-existing
    image_manifest.json, malformed spec, undeclared image_ref) leave
    the workspace untouched. A post-write re-validation failure rolls
    back the just-written manifest so the workspace returns to its
    pre-call state."""
    # --workspace shape gates (string-level FIRST, then filesystem).
    if _has_uri_scheme(str(workspace)):
        return 2, (
            f"FAIL: --workspace {workspace} looks like a URI; "
            f"init_image_manifest only accepts local directory paths"
        )
    if workspace.is_symlink():
        return 2, (
            f"FAIL: --workspace {workspace} is a symlink; refusing to "
            f"follow it. Pass a regular directory path."
        )
    if not workspace.exists():
        return 2, f"FAIL: --workspace {workspace} does not exist"
    if not workspace.is_dir():
        return 2, f"FAIL: --workspace {workspace} is not a directory"

    # --spec shape gates.
    if _has_uri_scheme(str(spec)):
        return 2, (
            f"FAIL: --spec {spec} looks like a URI; "
            f"init_image_manifest only accepts local file paths"
        )
    if spec.is_symlink():
        return 2, (
            f"FAIL: --spec {spec} is a symlink; refusing to follow it. "
            f"Pass a regular JSON file."
        )
    if not spec.exists():
        return 2, f"FAIL: --spec {spec} does not exist"
    if not spec.is_file():
        return 2, f"FAIL: --spec {spec} is not a regular file"

    # Stage-6 contract gate: refuse to overwrite a pre-existing
    # image_manifest. The symlink check runs FIRST and is independent
    # of ``manifest_out.exists()`` for the same reason init_deck_plan
    # refuses symlinks at deck_plan.json: ``exists()`` returns False
    # for a broken symlink, so a bare ``exists()`` gate would let
    # ``write_text()`` follow the symlink and silently clobber whatever
    # the dangling link names. We refuse both broken and resolvable
    # symlinks here.
    manifest_out = workspace / IMAGE_MANIFEST_FILENAME
    is_symlink, msg = _refuse_symlink(manifest_out, IMAGE_MANIFEST_FILENAME)
    if is_symlink:
        return 2, msg
    if manifest_out.exists():
        return 2, (
            f"FAIL: {manifest_out} already exists; init_image_manifest "
            f"refuses to overwrite a prior manifest. Rename or remove "
            f"it and re-run."
        )

    # Stage-1 prerequisite: source_manifest.json (regular file).
    sm_path = workspace / SOURCE_MANIFEST_FILENAME
    is_symlink, msg = _refuse_symlink(sm_path, SOURCE_MANIFEST_FILENAME)
    if is_symlink:
        return 2, msg
    if not sm_path.is_file():
        return 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{SOURCE_MANIFEST_FILENAME}; run scripts/init_workspace.py "
            f"first to seed Stage-1 intake."
        )

    # Stage-2 prerequisite: deck_brief.json (regular file).
    brief_path = workspace / DECK_BRIEF_FILENAME
    is_symlink, msg = _refuse_symlink(brief_path, DECK_BRIEF_FILENAME)
    if is_symlink:
        return 2, msg
    if not brief_path.is_file():
        return 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{DECK_BRIEF_FILENAME}; run scripts/init_deck_brief.py "
            f"first to seed Stage-2."
        )

    # Stage-3 prerequisite: deck_plan.json (regular file).
    plan_path = workspace / DECK_PLAN_FILENAME
    is_symlink, msg = _refuse_symlink(plan_path, DECK_PLAN_FILENAME)
    if is_symlink:
        return 2, msg
    if not plan_path.is_file():
        return 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{DECK_PLAN_FILENAME}; run scripts/init_deck_plan.py first "
            f"to seed Stage-3."
        )

    # Stage-4 prerequisite: design_system.json (regular file).
    ds_path = workspace / DESIGN_SYSTEM_FILENAME
    is_symlink, msg = _refuse_symlink(ds_path, DESIGN_SYSTEM_FILENAME)
    if is_symlink:
        return 2, msg
    if not ds_path.is_file():
        return 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{DESIGN_SYSTEM_FILENAME}; run scripts/init_design_system.py "
            f"first to seed Stage-4."
        )

    # Stage-5 prerequisite: slide_plans/ directory with *.json files.
    plans_dir = workspace / SLIDE_PLANS_DIRNAME
    is_symlink, msg = _refuse_symlink(plans_dir, SLIDE_PLANS_DIRNAME)
    if is_symlink:
        return 2, msg
    if not plans_dir.is_dir():
        return 2, (
            f"FAIL: --workspace {workspace} is missing a "
            f"{SLIDE_PLANS_DIRNAME}/ directory; run "
            f"scripts/init_slide_plans.py first to seed Stage-5."
        )

    # Stage-1/Stage-2 bridge (manifest <-> input/source.md <->
    # deck_brief.source_refs). This is the ONLY place input/source.md
    # is touched, and the bridge only does byte-level integrity checks
    # (UTF-8 decode, byte_count / line_count / sha256 match against the
    # manifest). The decoded string is discarded inside the bridge.
    bridge_results = check_source_manifest_bridge(workspace)
    bridge_failures = [r for r in bridge_results if not r.ok]
    if bridge_failures:
        detail = "; ".join(
            f"{r.name}{(': ' + r.detail) if r.detail else ''}"
            for r in bridge_failures
        )
        return 2, (
            f"FAIL: Stage-1/Stage-2 bridge does not pass for "
            f"{workspace}: {detail}"
        )

    # Re-parse + schema-validate the four prior-stage artifacts.
    try:
        brief = json.loads(brief_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return 2, f"FAIL: cannot read {brief_path}: {exc}"
    if not isinstance(brief, dict):
        return 2, (
            f"FAIL: {brief_path} did not decode to an object "
            f"(got {type(brief).__name__})"
        )
    brief_errors = _schema_validate(brief, DECK_BRIEF_SCHEMA)
    if brief_errors:
        return 1, (
            f"FAIL: {brief_path} does not validate against "
            f"deck_brief.schema.json: {brief_errors}"
        )

    try:
        plan = json.loads(plan_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return 2, f"FAIL: cannot read {plan_path}: {exc}"
    if not isinstance(plan, dict):
        return 2, (
            f"FAIL: {plan_path} did not decode to an object "
            f"(got {type(plan).__name__})"
        )
    plan_errors = _schema_validate(plan, DECK_PLAN_SCHEMA)
    if plan_errors:
        return 1, (
            f"FAIL: {plan_path} does not validate against "
            f"deck_plan.schema.json: {plan_errors}"
        )

    try:
        ds = json.loads(ds_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return 2, f"FAIL: cannot read {ds_path}: {exc}"
    if not isinstance(ds, dict):
        return 2, (
            f"FAIL: {ds_path} did not decode to an object "
            f"(got {type(ds).__name__})"
        )
    ds_errors = _schema_validate(ds, DESIGN_SYSTEM_SCHEMA)
    if ds_errors:
        return 1, (
            f"FAIL: {ds_path} does not validate against "
            f"design_system.schema.json: {ds_errors}"
        )

    # Planner-semantics cross-check the schema cannot express. Same
    # gate init_deck_plan.py / init_design_system.py / init_slide_plans.py
    # apply so Stage-6 enforces EXACTLY what Stage-3 would have accepted.
    brief_refs_raw = brief.get("source_refs") or []
    brief_refs = [r for r in brief_refs_raw if isinstance(r, str)]
    planner_errors = _cross_check_planner_semantics(
        plan=plan, brief_source_refs=brief_refs,
    )
    if planner_errors:
        return 1, (
            f"FAIL: {plan_path} fails planner-semantics cross-checks "
            f"(the same gate init_deck_plan.py applies before writing "
            f"a Stage-3 artifact): " + "; ".join(planner_errors)
        )

    # Stage-5 contents: every slide_plans/*.json file must be a regular
    # file (no symlinks) and schema-validate. Collect every referenced
    # image_ref id along the way for the post-spec cross-check, and
    # build a slide_plan-by-index map for the Stage-5 coverage gate.
    plan_files = sorted(plans_dir.glob("*.json"))
    if not plan_files:
        return 2, (
            f"FAIL: --workspace {workspace} has an empty "
            f"{SLIDE_PLANS_DIRNAME}/ directory; run "
            f"scripts/init_slide_plans.py first to seed Stage-5."
        )
    referenced_ids: dict[str, list[str]] = {}  # id -> [slide_plan filenames]
    slide_plans_by_index: dict[int, tuple[Path, dict]] = {}
    duplicate_indices: list[str] = []
    for pf in plan_files:
        is_symlink, msg = _refuse_symlink(pf, f"{SLIDE_PLANS_DIRNAME}/{pf.name}")
        if is_symlink:
            return 2, msg
        if not pf.is_file():
            return 2, f"FAIL: {pf} is not a regular file"
        try:
            sp = json.loads(pf.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return 2, f"FAIL: {pf} did not parse as JSON: {exc}"
        if not isinstance(sp, dict):
            return 2, (
                f"FAIL: {pf} did not decode to an object "
                f"(got {type(sp).__name__})"
            )
        sp_errors = _schema_validate(sp, SLIDE_PLAN_SCHEMA)
        if sp_errors:
            return 1, (
                f"FAIL: {pf} does not validate against "
                f"slide_plan.schema.json: {sp_errors}"
            )
        # Schema validation enforces `index` as integer >= 1; the
        # isinstance check below is defensive against future schema
        # drift and rules out `bool` (which is a subclass of int).
        idx = sp.get("index")
        if not isinstance(idx, int) or isinstance(idx, bool):
            return 1, (
                f"FAIL: {pf}.index must be an integer (got "
                f"{type(idx).__name__})"
            )
        if idx in slide_plans_by_index:
            prior_path = slide_plans_by_index[idx][0]
            duplicate_indices.append(
                f"index {idx}: {prior_path.name} and {pf.name}"
            )
        else:
            slide_plans_by_index[idx] = (pf, sp)
        refs = sp.get("image_refs") or []
        if not isinstance(refs, list):
            return 1, (
                f"FAIL: {pf}.image_refs must be a list "
                f"(got {type(refs).__name__})"
            )
        for ref in refs:
            if not isinstance(ref, str) or not ref:
                return 1, (
                    f"FAIL: {pf}.image_refs entry must be a non-empty "
                    f"string (got {ref!r})"
                )
            referenced_ids.setdefault(ref, []).append(pf.name)
    if duplicate_indices:
        return 1, (
            f"FAIL: {plans_dir} contains duplicate slide_plan indices: "
            + "; ".join(duplicate_indices)
        )

    # Stage-5 slide-plan coverage: every deck_plan.slides[].index has a
    # matching slide_plan, no orphan slide_plans, and each pair's
    # `layout` / `title` agree. Re-runs the same coverage gate
    # init_slide_plans.py applies before writing a Stage-5 artifact, so
    # a hand-edited slide_plans/ that drifts from deck_plan is refused
    # before Stage-6 advances. Slot coverage against the per-layout
    # file is deliberately NOT re-checked here — that gate needs the
    # template root, and Stage-5 already enforced it on the producer
    # side; Stage-6 only catches caller-side drift in the
    # deck_plan ↔ slide_plan pairing.
    deck_slides_by_index: dict[int, dict] = {}
    for s in plan.get("slides") or []:
        if (
            isinstance(s, dict)
            and isinstance(s.get("index"), int)
            and not isinstance(s.get("index"), bool)
        ):
            deck_slides_by_index[s["index"]] = s
    sp_indices = set(slide_plans_by_index)
    deck_indices = set(deck_slides_by_index)
    missing = sorted(deck_indices - sp_indices)
    orphans = sorted(sp_indices - deck_indices)
    if missing:
        return 1, (
            f"FAIL: {plans_dir} is missing slide_plans for deck_plan "
            f"indices {missing} (deck declares {sorted(deck_indices)})"
        )
    if orphans:
        return 1, (
            f"FAIL: {plans_dir} contains orphan slide_plan indices "
            f"{orphans} that deck_plan does not declare (deck declares "
            f"{sorted(deck_indices)})"
        )
    mismatch_errors: list[str] = []
    for idx in sorted(deck_indices):
        sp_path, sp = slide_plans_by_index[idx]
        ds = deck_slides_by_index[idx]
        if sp.get("layout") != ds.get("layout"):
            mismatch_errors.append(
                f"{sp_path.name}: layout {sp.get('layout')!r} != "
                f"deck_plan slide {idx} layout {ds.get('layout')!r}"
            )
        if sp.get("title") != ds.get("title"):
            mismatch_errors.append(
                f"{sp_path.name}: title {sp.get('title')!r} != "
                f"deck_plan slide {idx} title {ds.get('title')!r}"
            )
    if mismatch_errors:
        return 1, (
            f"FAIL: slide_plan / deck_plan layout/title mismatch: "
            + "; ".join(mismatch_errors)
        )

    # --spec content gates.
    try:
        spec_obj = json.loads(spec.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return 2, f"FAIL: --spec {spec} did not parse as JSON: {exc}"
    if not isinstance(spec_obj, dict):
        return 2, (
            f"FAIL: --spec {spec} did not decode to an object "
            f"(got {type(spec_obj).__name__}); image_manifest must be a "
            f"JSON object at the root"
        )

    spec_errors = _schema_validate(spec_obj, IMAGE_MANIFEST_SCHEMA)
    if spec_errors:
        return 1, (
            f"FAIL: --spec {spec} does not validate against "
            f"image_manifest.schema.json: " + "; ".join(spec_errors)
        )

    images = spec_obj.get("images") or []
    # Schema already enforces images is a list of objects with id /
    # local_path / source. Defensive belt-and-braces below for shape
    # we then operate on without re-checking.

    # Duplicate-id detection.
    seen: dict[str, int] = {}
    dup_errors: list[str] = []
    for i, img in enumerate(images):
        img_id = img.get("id")
        if not isinstance(img_id, str):
            # Schema already refuses non-string ids; defensive.
            return 1, (
                f"FAIL: images[{i}].id must be a string "
                f"(got {type(img_id).__name__})"
            )
        if img_id in seen:
            dup_errors.append(
                f"id {img_id!r} appears at images[{seen[img_id]}] and "
                f"images[{i}]"
            )
        else:
            seen[img_id] = i
    if dup_errors:
        return 1, (
            f"FAIL: --spec {spec} contains duplicate images[].id "
            f"values: " + "; ".join(dup_errors)
        )

    # local_path safety + within-workspace + regular-non-symlink-file.
    path_errors: list[str] = []
    for i, img in enumerate(images):
        local_path = img.get("local_path")
        img_id = img.get("id")
        if not isinstance(local_path, str):
            path_errors.append(
                f"images[{i}] (id {img_id!r}): local_path must be a "
                f"string (got {type(local_path).__name__})"
            )
            continue
        if not local_path_is_safe(local_path):
            path_errors.append(
                f"images[{i}] (id {img_id!r}): local_path "
                f"{local_path!r} is not a safe workspace-relative path "
                f"(URI / leading '/' / leading '\\' / '..' segment)"
            )
            continue
        # Leaf symlink check runs BEFORE _resolves_within so an
        # asset symlink to *outside* the workspace surfaces with the
        # clear "symlink" diagnostic rather than the generic "escapes
        # workspace" diagnostic _resolves_within (via Path.resolve())
        # would otherwise produce. A parent symlink that escapes the
        # workspace is still caught by _resolves_within below.
        candidate = workspace / local_path
        if candidate.is_symlink():
            try:
                target = str(candidate.readlink())
            except OSError:
                target = "<unreadable>"
            path_errors.append(
                f"images[{i}] (id {img_id!r}): local_path "
                f"{local_path!r} is a symlink (-> {target}); "
                f"init_image_manifest refuses to follow asset symlinks"
            )
            continue
        if not _resolves_within(workspace, local_path):
            path_errors.append(
                f"images[{i}] (id {img_id!r}): local_path "
                f"{local_path!r} escapes --workspace after resolution"
            )
            continue
        if not candidate.is_file():
            path_errors.append(
                f"images[{i}] (id {img_id!r}): local_path "
                f"{local_path!r} does not resolve to an existing "
                f"regular file (looked at {candidate})"
            )
            continue
    if path_errors:
        return 1, (
            f"FAIL: --spec {spec} has unsafe / missing image assets: "
            + "; ".join(path_errors)
        )

    # Cross-check: every slide_plan image_ref id must be declared.
    declared_ids = set(seen)
    undeclared = sorted(
        ref for ref in referenced_ids if ref not in declared_ids
    )
    if undeclared:
        bullets = "; ".join(
            f"{ref!r} (referenced by {referenced_ids[ref]})"
            for ref in undeclared
        )
        return 1, (
            f"FAIL: slide_plan image_refs reference id(s) not declared "
            f"by --spec images[]: {bullets}. Declared ids: "
            f"{sorted(declared_ids)}"
        )
    # Empty images allowed only when no slide_plan references images.
    # The undeclared-ref check above already catches the "empty images +
    # non-empty refs" case (the refs become undeclared); this branch is
    # belt-and-braces and surfaces a clearer message.
    if not images and referenced_ids:
        return 1, (
            f"FAIL: --spec {spec} declares an empty images[] list but "
            f"slide_plans reference image_refs "
            f"{sorted(referenced_ids)}; an empty manifest is only "
            f"valid when no slide_plan references any image"
        )

    # Write. Same rollback contract as the other init_* helpers: the
    # catch clause is (Exception, SystemExit) so validate_artifact's
    # SystemExit branch on read-errors still routes through rollback.
    # KeyboardInterrupt is intentionally NOT caught.
    try:
        manifest_out.write_text(
            json.dumps(spec_obj, indent=2, sort_keys=True) + "\n"
        )
    except (Exception, SystemExit) as exc:
        if manifest_out.exists():
            try:
                manifest_out.unlink()
            except OSError:
                pass
        return 2, (
            f"FAIL: writing {manifest_out} raised "
            f"{type(exc).__name__}: {exc}"
        )

    try:
        errors = validate_artifact(manifest_out, IMAGE_MANIFEST_SCHEMA)
    except (Exception, SystemExit) as exc:
        try:
            manifest_out.unlink()
            rb_note = f"removed {manifest_out}"
        except OSError as unlink_exc:
            rb_note = f"could not remove {manifest_out}: {unlink_exc}"
        return 1, (
            f"FAIL: post-write re-validation of {manifest_out} raised "
            f"{type(exc).__name__}: {exc}\n"
            f"rolled back: {rb_note}"
        )
    if errors:
        try:
            manifest_out.unlink()
            rb_note = f"removed {manifest_out}"
        except OSError as unlink_exc:
            rb_note = f"could not remove {manifest_out}: {unlink_exc}"
        return 1, (
            f"FAIL: on-disk image_manifest at {manifest_out} did not "
            f"re-validate: {errors}\n"
            f"rolled back: {rb_note}"
        )

    return 0, (
        f"OK: Stage-6 image_manifest seeded at {manifest_out}.\n"
        f"  images declared: {len(images)} "
        f"({sorted(declared_ids)})\n"
        f"  slide_plan image_refs satisfied: "
        f"{sorted(referenced_ids)}\n"
        f"Next: scripts/run_pipeline.py can now take over for "
        f"stages 7-10."
    )


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs under
# tempfile.TemporaryDirectory(); no fixture leaks into the repo.
# ---------------------------------------------------------------------------

_SYNTH_SOURCE_MD = (
    "# Synthetic Source\n\n"
    "Synthetic .md body — never inspected by init_image_manifest.\n"
    "Line three.\n"
)

_SAMPLE_DESIGN_SYSTEM = {
    "palette": {
        "primary": "#112233",
        "background": "#FFFFFF",
        "text": "#101010",
    },
    "typography": {
        "heading": {"font_family": "Arial, sans-serif", "size_pt": 24},
        "body": {"font_family": "Arial, sans-serif", "size_pt": 12},
    },
    "grid": {"width_px": 1280, "height_px": 720, "margin_px": 32},
}


def _seed_stage12345_workspace(
    ws: Path,
    *,
    template_name: str = "synthetic_template",
    source_id: str = "synthetic_src",
    body: bytes | None = None,
    slide_image_refs: dict[int, list[str]] | None = None,
    slide_count: int = 2,
) -> None:
    """Mimic what init_workspace + init_deck_brief + init_deck_plan +
    init_design_system + init_slide_plans would have written.

    ``slide_image_refs`` is an optional mapping of 1-based slide index
    to its top-level ``image_refs[]`` list (matches the slide_plan
    schema). Synthetic only; does not invoke the upstream helpers as
    subprocesses so targeted positive / negative seeds stay simple."""
    import hashlib
    if body is None:
        body = _SYNTH_SOURCE_MD.encode("utf-8")
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "input").mkdir(parents=True, exist_ok=True)
    (ws / "input" / "source.md").write_bytes(body)
    line_count = (
        body.count(b"\n") + (0 if body.endswith(b"\n") else 1)
        if body else 0
    )
    sha = hashlib.sha256(body).hexdigest()
    manifest = {
        "schema_version": "1",
        "source": {
            "id": source_id,
            "local_path": "input/source.md",
            "kind": "markdown",
            "byte_count": len(body),
            "line_count": line_count,
            "sha256": sha,
        },
        "tool": {"name": "init_workspace", "version": "1"},
    }
    (ws / SOURCE_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    brief = {
        "title": "Synthetic Title",
        "audience": "Synthetic Audience",
        "objective": "Synthetic Objective",
        "source_refs": [source_id],
    }
    (ws / DECK_BRIEF_FILENAME).write_text(
        json.dumps(brief, indent=2, sort_keys=True) + "\n"
    )
    layouts = ["cover", "kpi_dashboard"][:slide_count]
    deck_slides = [
        {
            "index": i + 1,
            "layout": layouts[i],
            "title": f"Slide {i+1}",
            "section_id": "main",
            "summary": f"Synthetic slide {i+1}.",
            "density": "low",
            "source_refs": [source_id],
        }
        for i in range(slide_count)
    ]
    plan = {
        "template": template_name,
        "planning": {
            "planned_slide_count": slide_count,
            "rationale": (
                "Synthetic plan for init_image_manifest self-test."
            ),
        },
        "sections": [
            {
                "id": "main",
                "title": "Main",
                "summary": "Synthetic section.",
                "slide_indices": [i + 1 for i in range(slide_count)],
            },
        ],
        "slides": deck_slides,
    }
    (ws / DECK_PLAN_FILENAME).write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n"
    )
    (ws / DESIGN_SYSTEM_FILENAME).write_text(
        json.dumps(_SAMPLE_DESIGN_SYSTEM, indent=2, sort_keys=True) + "\n"
    )
    plans_dir = ws / SLIDE_PLANS_DIRNAME
    plans_dir.mkdir(parents=True, exist_ok=True)
    refs_by_idx = slide_image_refs or {}
    for ds in deck_slides:
        idx = ds["index"]
        layout = ds["layout"]
        blocks = [
            {"id": "title", "kind": "text",
             "content": f"{ds['title']} title"},
        ]
        if layout == "kpi_dashboard":
            blocks.append({
                "id": "kpis", "kind": "kpi",
                "content": [{"label": "m1", "value": "v1"}],
            })
        sp = {
            "index": idx,
            "layout": layout,
            "title": ds["title"],
            "blocks": blocks,
        }
        if idx in refs_by_idx:
            sp["image_refs"] = list(refs_by_idx[idx])
        out = plans_dir / f"{idx:02d}_{layout}.json"
        out.write_text(json.dumps(sp, indent=2, sort_keys=True) + "\n")


def _expect(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


def _run_self_tests() -> list[tuple[str, bool, str]]:  # noqa: C901
    import tempfile

    results: list[tuple[str, bool, str]] = []

    # 1. happy path: one local asset declared, slide 1 references it.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_happy_one"
        _seed_stage12345_workspace(
            ws, slide_image_refs={1: ["cover_accent"]},
        )
        (ws / "assets").mkdir()
        (ws / "assets" / "accent.svg").write_text("<svg/>\n")
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({
            "images": [
                {
                    "id": "cover_accent",
                    "local_path": "assets/accent.svg",
                    "source": "synthetic",
                    "alt_text": "Synthetic accent.",
                    "intended_use": "spot illustration",
                },
            ],
        }, indent=2, sort_keys=True) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        out = ws / IMAGE_MANIFEST_FILENAME
        ok = (
            rc == 0
            and out.is_file()
            and not validate_artifact(out, IMAGE_MANIFEST_SCHEMA)
        )
        results.append(_expect(
            "happy path: one local asset referenced by slide_plan "
            "image_refs writes a schema-valid image_manifest.json",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 2. happy path: empty images, no slide_plan references images.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_happy_empty"
        _seed_stage12345_workspace(ws)
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({"images": []}, indent=2,
                                        sort_keys=True) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        out = ws / IMAGE_MANIFEST_FILENAME
        ok = rc == 0 and out.is_file()
        results.append(_expect(
            "happy path: empty images[] accepted when no slide_plan "
            "image_refs are present",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 3. determinism: two independent runs from identical inputs
    # produce byte-identical manifests.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws_a = td / "ws_a"
        ws_b = td / "ws_b"
        for ws in (ws_a, ws_b):
            _seed_stage12345_workspace(
                ws, slide_image_refs={1: ["cover_accent"]},
            )
            (ws / "assets").mkdir()
            (ws / "assets" / "accent.svg").write_text("<svg/>\n")
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({
            "images": [
                {
                    "id": "cover_accent",
                    "local_path": "assets/accent.svg",
                    "source": "synthetic",
                },
            ],
        }, indent=2, sort_keys=True) + "\n")
        rc_a, _ = init_image_manifest(workspace=ws_a, spec=spec_path)
        rc_b, _ = init_image_manifest(workspace=ws_b, spec=spec_path)
        ok = (
            rc_a == 0 and rc_b == 0
            and (ws_a / IMAGE_MANIFEST_FILENAME).read_bytes()
            == (ws_b / IMAGE_MANIFEST_FILENAME).read_bytes()
        )
        results.append(_expect(
            "determinism: two independent runs produce a byte-"
            "identical image_manifest.json (sorted keys, no timestamps)",
            ok, f"rc_a={rc_a}, rc_b={rc_b}",
        ))

    # 4. missing --spec refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_missing_spec"
        _seed_stage12345_workspace(ws)
        rc, msg = init_image_manifest(
            workspace=ws, spec=td / "does_not_exist.json",
        )
        ok = (
            rc == 2 and "does not exist" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "missing --spec refused (no silent default)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 5. symlink --spec refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_symlink_spec"
        _seed_stage12345_workspace(ws)
        real = td / "real_spec.json"
        real.write_text(json.dumps({"images": []}) + "\n")
        link = td / "link_spec.json"
        link.symlink_to(real)
        rc, msg = init_image_manifest(workspace=ws, spec=link)
        ok = (
            rc == 2 and "symlink" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "symlink at --spec refused at the preflight",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 6. malformed --spec (non-JSON) refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_malformed"
        _seed_stage12345_workspace(ws)
        bad = td / "bad.json"
        bad.write_text("{ not valid json")
        rc, msg = init_image_manifest(workspace=ws, spec=bad)
        ok = (
            rc == 2 and "did not parse as JSON" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "malformed --spec (non-JSON) refused before any write",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 7. schema-invalid --spec (missing required 'images') refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_schema_bad"
        _seed_stage12345_workspace(ws)
        bad = td / "bad.json"
        bad.write_text(json.dumps({"not_images": []}) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=bad)
        ok = (
            rc == 1 and "image_manifest.schema.json" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "schema-invalid --spec (missing required 'images') refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 8. list-rooted --spec refused (JSON root is a list, not object).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_list_root"
        _seed_stage12345_workspace(ws)
        bad = td / "bad.json"
        bad.write_text(json.dumps([{"id": "x"}]) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=bad)
        ok = (
            rc == 2 and "did not decode to an object" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "list-rooted --spec refused at the decode gate",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 9. duplicate images[].id refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_dup_id"
        _seed_stage12345_workspace(ws)
        (ws / "assets").mkdir()
        (ws / "assets" / "a.svg").write_text("<svg/>\n")
        (ws / "assets" / "b.svg").write_text("<svg/>\n")
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({
            "images": [
                {"id": "same", "local_path": "assets/a.svg",
                 "source": "synthetic"},
                {"id": "same", "local_path": "assets/b.svg",
                 "source": "synthetic"},
            ],
        }, indent=2, sort_keys=True) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        ok = (
            rc == 1 and "duplicate" in msg and "'same'" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "duplicate images[].id refused; no manifest written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 10. unsafe local_path: URI-shaped path refused.
    for unsafe_label, unsafe_path in (
        ("URI", "https://attacker.example/a.png"),
        ("absolute", "/etc/passwd"),
        ("traversal", "../outside.svg"),
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / f"ws_unsafe_{unsafe_label}"
            _seed_stage12345_workspace(ws)
            spec_path = td / "spec.json"
            spec_path.write_text(json.dumps({
                "images": [
                    {"id": "x", "local_path": unsafe_path,
                     "source": "local_asset"},
                ],
            }, indent=2, sort_keys=True) + "\n")
            rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
            ok = (
                rc == 1 and "not a safe" in msg
                and not (ws / IMAGE_MANIFEST_FILENAME).exists()
            )
            results.append(_expect(
                f"unsafe local_path ({unsafe_label}: {unsafe_path!r}) "
                f"refused at the path-safety gate",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # 11. missing asset (declared local_path file does not exist).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_missing_asset"
        _seed_stage12345_workspace(ws)
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({
            "images": [
                {"id": "ghost", "local_path": "assets/ghost.svg",
                 "source": "synthetic"},
            ],
        }, indent=2, sort_keys=True) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        ok = (
            rc == 1 and "does not resolve to an existing" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "missing image asset refused; no manifest written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 12. symlink asset (declared local_path is a symlink).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_link_asset"
        _seed_stage12345_workspace(ws)
        (ws / "assets").mkdir()
        real_asset = td / "outside_asset.svg"
        real_asset.write_text("<svg/>\n")
        link_asset = ws / "assets" / "linked.svg"
        link_asset.symlink_to(real_asset)
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({
            "images": [
                {"id": "linked", "local_path": "assets/linked.svg",
                 "source": "local_asset"},
            ],
        }, indent=2, sort_keys=True) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        ok = (
            rc == 1 and "symlink" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "image asset that is itself a symlink refused; no manifest "
            "written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 13. undeclared slide_plan image_ref refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_undeclared"
        _seed_stage12345_workspace(
            ws, slide_image_refs={1: ["not_declared"]},
        )
        (ws / "assets").mkdir()
        (ws / "assets" / "other.svg").write_text("<svg/>\n")
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({
            "images": [
                {"id": "other", "local_path": "assets/other.svg",
                 "source": "synthetic"},
            ],
        }, indent=2, sort_keys=True) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        ok = (
            rc == 1 and "not declared" in msg
            and "'not_declared'" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "undeclared slide_plan image_ref refused at the cross-"
            "check gate",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 14. pre-existing image_manifest.json refused; prior bytes preserved.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_pre_existing"
        _seed_stage12345_workspace(ws)
        prior = b'{"prior":true}\n'
        (ws / IMAGE_MANIFEST_FILENAME).write_bytes(prior)
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({"images": []}) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        preserved = (ws / IMAGE_MANIFEST_FILENAME).read_bytes() == prior
        ok = rc == 2 and "already exists" in msg and preserved
        results.append(_expect(
            "pre-existing image_manifest.json refused (no overwrite); "
            "prior bytes preserved byte-identical",
            ok, f"rc={rc}, preserved={preserved}, msg={msg!r}",
        ))

    # 15. broken symlink at image_manifest.json refused; target never
    # created.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_link_out"
        _seed_stage12345_workspace(ws)
        target = td / "outside_must_not_exist.json"
        assert not target.exists()
        (ws / IMAGE_MANIFEST_FILENAME).symlink_to(target)
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({"images": []}) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        still_symlink = (ws / IMAGE_MANIFEST_FILENAME).is_symlink()
        target_absent = not target.exists()
        ok = (
            rc == 2 and "symlink" in msg
            and still_symlink and target_absent
        )
        results.append(_expect(
            "broken symlink at image_manifest.json refused before any "
            "write; dangling target never created",
            ok,
            f"rc={rc}, still_symlink={still_symlink}, "
            f"target_absent={target_absent}, msg={msg!r}",
        ))

    # 16. resolvable symlink at image_manifest.json refused; outside
    # target bytes preserved.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_link_out_real"
        _seed_stage12345_workspace(ws)
        outside = td / "outside.json"
        outside_bytes = b'{"outside":true}\n'
        outside.write_bytes(outside_bytes)
        (ws / IMAGE_MANIFEST_FILENAME).symlink_to(outside)
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({"images": []}) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        outside_preserved = outside.read_bytes() == outside_bytes
        ok = rc == 2 and "symlink" in msg and outside_preserved
        results.append(_expect(
            "resolvable symlink at image_manifest.json refused; outside "
            "target bytes preserved byte-identical",
            ok, f"rc={rc}, outside_preserved={outside_preserved}",
        ))

    # 17. missing prior-stage artifact (slide_plans/ empty) refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_plans"
        _seed_stage12345_workspace(ws)
        # Empty out slide_plans/.
        for p in (ws / SLIDE_PLANS_DIRNAME).glob("*.json"):
            p.unlink()
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({"images": []}) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        ok = (
            rc == 2 and "Stage-5" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "empty slide_plans/ refused (Stage-5 prerequisite); no "
            "manifest written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 18. URI --workspace refused at the string layer.
    rc, msg = init_image_manifest(
        workspace=Path("https://attacker.example/ws"),
        spec=Path("/tmp/no_spec.json"),
    )
    ok = rc == 2 and "URI" in msg
    results.append(_expect(
        "--workspace with URI scheme refused at the string layer",
        ok, f"rc={rc}",
    ))

    # 19. no raw source body in manifest. Embed a unique marker phrase
    # into input/source.md and assert it never appears in the written
    # manifest.
    marker = "MARKER_NEVER_EXTRACT_imgmanifest_5fe2c9"
    body = (
        f"# Title\n\nBody with {marker} in it.\n"
    ).encode("utf-8")
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_extract"
        _seed_stage12345_workspace(ws, body=body)
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({"images": []}) + "\n")
        rc, _ = init_image_manifest(workspace=ws, spec=spec_path)
        ok = (
            rc == 0
            and marker not in (ws / IMAGE_MANIFEST_FILENAME).read_text()
        )
        results.append(_expect(
            "source body marker phrase is NEVER copied into the "
            "image_manifest (helper does not extract content)",
            ok, f"rc={rc}",
        ))

    # 20. mocked post-write re-validation failure rolls back the
    # just-written manifest so the workspace returns to its pre-call
    # state.
    import unittest.mock
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_rb"
        _seed_stage12345_workspace(ws)
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({"images": []}) + "\n")
        with unittest.mock.patch(
            f"{__name__}.validate_artifact",
            return_value=["forced test failure"],
        ):
            rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        out = ws / IMAGE_MANIFEST_FILENAME
        ok = (
            rc == 1 and "rolled back" in msg
            and not out.exists()
        )
        results.append(_expect(
            "mocked post-write re-validation failure rolls back the "
            "manifest; workspace returns to pre-call state",
            ok, f"rc={rc}, exists={out.exists()}",
        ))

    # 21. mocked post-write re-validation RAISING (SystemExit) is also
    # caught and triggers rollback — proves the catch clause is
    # (Exception, SystemExit), not bare Exception.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_rb_raise"
        _seed_stage12345_workspace(ws)
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({"images": []}) + "\n")
        with unittest.mock.patch(
            f"{__name__}.validate_artifact",
            side_effect=SystemExit("simulated read error"),
        ):
            rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        out = ws / IMAGE_MANIFEST_FILENAME
        ok = (
            rc == 1 and "rolled back" in msg
            and "SystemExit" in msg
            and not out.exists()
        )
        results.append(_expect(
            "mocked post-write re-validation raising SystemExit "
            "triggers rollback (catch clause is (Exception, SystemExit))",
            ok, f"rc={rc}, exists={out.exists()}",
        ))

    # 22. Stage-5 coverage: deck_plan declares slide 2 but slide_plans/
    # is missing it -> refused before any write.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_missing_sp"
        _seed_stage12345_workspace(ws)
        # Remove slide 2's plan file; deck_plan still declares it.
        for p in (ws / SLIDE_PLANS_DIRNAME).glob("02_*.json"):
            p.unlink()
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({"images": []}) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "missing slide_plans" in msg
            and "[2]" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "missing slide_plan (deck_plan declares slide 2 but "
            "slide_plans/ does not contain it) refused at the "
            "Stage-5 coverage gate",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 23. Stage-5 coverage: orphan slide_plan whose index deck_plan
    # does not declare -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_orphan_sp"
        _seed_stage12345_workspace(ws)
        # Plant an extra slide_plan with index=9 the deck_plan does
        # not declare.
        (ws / SLIDE_PLANS_DIRNAME / "09_cover.json").write_text(
            json.dumps({
                "index": 9,
                "layout": "cover",
                "title": "Orphan",
                "blocks": [
                    {"id": "title", "kind": "text",
                     "content": "Orphan title"},
                ],
            }, indent=2, sort_keys=True) + "\n"
        )
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({"images": []}) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "orphan slide_plan indices" in msg
            and "[9]" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "orphan slide_plan (index not declared by deck_plan) "
            "refused at the Stage-5 coverage gate",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 24. Stage-5 coverage: duplicate slide_plan indices across two
    # files (a hand-copied 01_cover.json under a different filename)
    # -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_dup_sp"
        _seed_stage12345_workspace(ws)
        plans_dir = ws / SLIDE_PLANS_DIRNAME
        original = (plans_dir / "01_cover.json").read_text()
        (plans_dir / "01_cover_copy.json").write_text(original)
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({"images": []}) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "duplicate slide_plan indices" in msg
            and "index 1" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "duplicate slide_plan indices across two files refused "
            "at the Stage-5 coverage gate",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 25. Stage-5 coverage: slide_plan layout / title disagrees with
    # deck_plan -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_mismatch_sp"
        _seed_stage12345_workspace(ws)
        sp_path = ws / SLIDE_PLANS_DIRNAME / "01_cover.json"
        sp = json.loads(sp_path.read_text())
        sp["title"] = "Different Title Than Deck Plan"
        sp_path.write_text(json.dumps(sp, indent=2, sort_keys=True) + "\n")
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({"images": []}) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "layout/title mismatch" in msg
            and "title" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "slide_plan / deck_plan title mismatch refused at the "
            "Stage-5 coverage gate; no manifest written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 26. cross-check positive: empty images + non-empty refs surfaces
    # the explicit "empty manifest + refs" diagnostic and not just the
    # generic undeclared-refs path. Proves both branches fire.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_empty_with_refs"
        _seed_stage12345_workspace(
            ws, slide_image_refs={1: ["needs_something"]},
        )
        spec_path = td / "spec.json"
        spec_path.write_text(json.dumps({"images": []}) + "\n")
        rc, msg = init_image_manifest(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "not declared" in msg
            and "needs_something" in msg
            and not (ws / IMAGE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "empty images[] with non-empty slide_plan refs refused "
            "at the cross-check (no manifest written)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage-6 (Image Manifest) image_manifest.json helper. "
            "Bridges a stage-5-initialized workspace "
            "(source_manifest.json + input/source.md + deck_brief.json "
            "+ deck_plan.json + design_system.json + slide_plans/*.json) "
            "plus a caller-supplied --spec image_manifest JSON file "
            "into a schema-valid <workspace>/image_manifest.json. "
            "Validates images[].local_path against the workspace, "
            "cross-checks every slide_plan.image_refs id against "
            "images[].id, and writes the manifest deterministically. "
            "Does NOT extract business content from the source body; "
            "does NOT generate any image asset; does NOT call D-One, "
            "Qoder, any public network, image generation, or external "
            "service; does NOT produce render_models, svg_previews, or "
            "any .pptx."
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Workspace directory (must already contain source_manifest.json "
             "+ input/source.md + deck_brief.json + deck_plan.json + "
             "design_system.json + slide_plans/*.json — e.g. seeded by "
             "scripts/init_workspace.py through scripts/init_slide_plans.py).",
    )
    parser.add_argument(
        "--spec", type=Path, default=None,
        help="Local JSON file whose shape is exactly the image_manifest "
             "candidate to be written. Validated against "
             "schemas/image_manifest.schema.json; duplicate images[].id and "
             "unsafe local_path values are refused. Every local_path must "
             "resolve inside --workspace to a regular non-symlink file.",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios (happy paths, determinism, "
             "missing / symlink / malformed / schema-invalid / list-rooted "
             "--spec, duplicate images[].id, unsafe local_path variants, "
             "missing / symlink image asset, undeclared slide_plan "
             "image_ref, pre-existing image_manifest.json refused, broken "
             "and resolvable symlink at the output path, empty slide_plans/ "
             "rejection, URI-shaped --workspace, no-source-body extraction, "
             "mocked post-write rollback (return errors and raise "
             "SystemExit), empty images + non-empty refs, Stage-5 coverage "
             "gates (missing / orphan / duplicate slide_plan indices, "
             "slide_plan / deck_plan layout-title mismatch)). Exits non-"
             "zero if any scenario does not behave as expected. Mutually "
             "exclusive with --workspace / --spec.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if any(v is not None for v in (args.workspace, args.spec)):
            print(
                "FAIL: --self-test does not take any other argument",
                file=sys.stderr,
            )
            return 2
        results = _run_self_tests()
        fails = 0
        for name, ok, detail in results:
            mark = "PASS" if ok else "FAIL"
            suffix = f" -- {detail}" if not ok and detail else ""
            print(f"  [{mark}] {name}{suffix}")
            if not ok:
                fails += 1
        print()
        if fails:
            print(
                f"FAIL: {fails} self-test scenario(s) did not behave as "
                f"expected."
            )
            return 1
        print(
            "OK (self-test): every fail-closed gate is caught and the "
            "happy-path image_manifest is written from the caller-"
            "supplied spec."
        )
        return 0

    missing = [
        name for name, value in (
            ("--workspace", args.workspace),
            ("--spec", args.spec),
        )
        if value is None
    ]
    if missing:
        print(
            f"FAIL: missing required argument(s): {', '.join(missing)} "
            f"(use --self-test for the in-script scenarios)",
            file=sys.stderr,
        )
        return 2

    rc, msg = init_image_manifest(
        workspace=args.workspace, spec=args.spec,
    )
    if rc == 0:
        print(msg)
    else:
        print(msg, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
