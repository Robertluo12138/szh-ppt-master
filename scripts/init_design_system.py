#!/usr/bin/env python3
"""Stage-4 (Design System) workspace bridge: produce a minimal design_system.json.

Bridges an already-stage-3-initialized workspace (the one
``scripts/init_workspace.py`` + ``scripts/init_deck_brief.py`` +
``scripts/init_deck_plan.py`` produce — i.e. the workspace ships
``source_manifest.json`` + ``input/source.md`` + ``deck_brief.json`` +
``deck_plan.json``) into a minimal, schema-valid
``design_system.json`` whose palette / typography / grid tokens come
from EXACTLY ONE explicit caller input:

  --spec <path>
    A caller-supplied JSON file whose shape is exactly the
    design_system candidate to be written. The helper validates it
    against ``schemas/design_system.schema.json`` and writes it
    verbatim (modulo deterministic re-serialization).

  --theme-from-template + --template-root <dir>
    The helper resolves ``deck_plan.template`` against the supplied
    template root, loads ``<template-root>/<deck_plan.template>/
    template.json`` (schema-validated), follows its ``theme_ref``
    inside the template directory, loads the theme file (schema-
    validated against ``schemas/theme.schema.json``), and projects
    the theme's palette / typography / grid into a design_system
    skeleton. Template resolution is anchored on
    ``deck_plan.template``; there is NO product-level default —
    ``business_review`` is just the name of the template that the
    current repo ships, not a fallback.

This is **Stage-4 contract support only**. It is NOT a full
prompt/report/Markdown-to-PPTX automation. The helper deliberately
does NOT:

  - read or parse any business content out of ``input/source.md``
    — the helper invokes the Stage-1/Stage-2 bridge
    (``check_source_manifest_bridge``), which reads the file's
    bytes ONLY for byte-level integrity checks (UTF-8 decode
    validity; ``source.byte_count`` / ``source.line_count`` /
    ``source.sha256`` match against the manifest); the decoded
    string is discarded inside the bridge, and the helper itself
    never opens the source body at all — no heading / bullet /
    paragraph / sentence parsing, no token inference, no copy of
    any source bytes into the design_system;
  - infer palette / typography / grid from raw source text — the
    caller must supply tokens explicitly via ``--spec`` or
    indirectly via a template theme they explicitly nominated;
  - invent ``slide_plans/*.json``, ``image_manifest.json``,
    ``render_models/*``, ``svg_previews/*``, or any ``.pptx``;
  - emit any artifact other than ``<workspace>/design_system.json``;
  - call any public network, D-One, Qoder, image generation, or
    external service;
  - mutate or inspect any file outside ``--workspace`` (in
    ``--spec`` mode the spec file itself is the only file outside
    the workspace the helper opens; in ``--theme-from-template``
    mode the template-root tree is the only file tree outside the
    workspace the helper reads, and only the resolved
    ``template.json`` / theme file inside it).

After this script succeeds, stages 5-6 (``slide_plans/*.json``,
``image_manifest.json``) remain agent-driven per the schemas under
``schemas/`` before ``scripts/run_pipeline.py`` can take over for
stages 7-10.

Stdlib-only. Deterministic — given the same workspace + (spec or
theme), the produced ``design_system.json`` is byte-identical. The
design content is exactly what the caller provided / what the theme
declared; nothing derived from clock, environment, or file order
ends up in the artifact.

Fail-closed gates (every gate aborts the run and writes nothing):

  --workspace
    * must be an existing directory;
    * the string form must not start with a URI-like scheme matching
      ``^[A-Za-z][A-Za-z0-9+.\\-]*:``;
    * must not itself be a symlink;
    * must contain ``source_manifest.json`` as a **regular in-
      workspace file** (Stage-1; symlink refused outright);
    * must contain ``deck_brief.json`` as a regular in-workspace file
      that validates against ``schemas/deck_brief.schema.json``;
    * must contain ``deck_plan.json`` as a regular in-workspace file
      that validates against ``schemas/deck_plan.schema.json`` AND
      passes EXACTLY the planner-semantics cross-checks
      ``init_deck_plan.py`` applies before it writes a Stage-3
      artifact — re-using ``init_deck_plan._cross_check_planner_semantics``
      so Stage-4 cannot advance from a deck_plan that
      ``init_deck_plan.py`` itself would have refused. Coverage:
      ``planning.planned_slide_count`` == ``len(slides)``; slide
      indices unique AND contiguous 1..N (the schema only requires
      ``index >= 1``, and ``validate_workspace.check_planner_semantics``
      stops at section coverage — neither catches a duplicate or
      ``[1, 2, 4]`` index sequence); sections partition
      ``slides[].index`` 1:1 with no duplicates / missing / orphans;
      every ``slide.section_id`` resolves AND the section's
      ``slide_indices`` lists the slide's index; every
      ``slide.source_refs`` value is declared in
      ``deck_brief.source_refs``. A schema-valid-but-semantically-
      broken deck_plan (e.g. one whose indices are ``[1, 1, 2]`` or
      ``[1, 2, 4]``, or one whose ``slide.section_id`` names a
      section the deck_plan never declares) is refused at this gate;
    * the Stage-1/Stage-2 bridge (manifest <-> on-disk source <->
      deck_brief.source_refs) must pass;
    * must NOT already contain ``design_system.json`` as a symlink
      (broken or resolvable) OR a regular file — the helper refuses
      to overwrite a prior design system.

  --spec (when supplied; mutually exclusive with --theme-from-template)
    * must be an existing **regular file** (symlink refused);
    * the string form must not start with a URI-like scheme;
    * must parse as JSON and decode to an object (``dict``);
    * must validate against ``schemas/design_system.schema.json``
      (which enforces hex-coded palette colors, CSS-style font
      fallback chains, positive numeric font sizes, positive integer
      grid dimensions, and a non-negative integer margin).

  --theme-from-template (when supplied; mutually exclusive with --spec)
    * requires ``--template-root`` (a regular directory; URI refused;
      symlink refused);
    * ``deck_plan.template`` must be a non-empty string AND pass the
      shared ``local_path_is_safe`` rule (no ``..``, no leading slash,
      no URI scheme) — a deck_plan whose template name carries a path
      payload is refused at this gate;
    * ``<template-root>/<deck_plan.template>/`` must resolve inside
      ``--template-root`` (symlink-escape rejected);
    * ``<template-root>/<deck_plan.template>/template.json`` must be a
      regular file (symlink refused), parse as JSON, validate against
      ``schemas/template.schema.json``;
    * ``template.theme_ref`` must pass ``local_path_is_safe`` and
      resolve inside the template directory; the referenced theme
      file must be a regular file (symlink refused), parse as JSON,
      and validate against ``schemas/theme.schema.json``;
    * the projected design_system ({palette, typography, grid}) must
      validate against ``schemas/design_system.schema.json``.

The design_system is validated against
``schemas/design_system.schema.json`` **in memory** before any write,
and **re-validated on disk** after the write completes — the same
defense-in-depth contract ``init_workspace.py`` /
``init_deck_brief.py`` / ``init_deck_plan.py`` follow. A post-write
failure rolls the design_system back so the workspace is never left
in a half-written state.
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
# Re-use Stage-3's own planner-semantics gate (the function
# init_deck_plan.py applies to a candidate plan-spec before it
# writes deck_plan.json). Stage-4 must prove the on-disk
# deck_plan.json is exactly what init_deck_plan would have accepted
# — schema validity alone is not enough, and check_planner_semantics
# in validate_workspace.py covers section/source_refs cross-checks
# but not slide-index uniqueness + contiguous 1..N. Using the
# Stage-3 helper's own gate gives exact parity.
from init_deck_plan import _cross_check_planner_semantics  # noqa: E402

DESIGN_SYSTEM_SCHEMA = SCHEMAS_DIR / "design_system.schema.json"
DECK_BRIEF_SCHEMA = SCHEMAS_DIR / "deck_brief.schema.json"
DECK_PLAN_SCHEMA = SCHEMAS_DIR / "deck_plan.schema.json"
TEMPLATE_SCHEMA = SCHEMAS_DIR / "template.schema.json"
THEME_SCHEMA = SCHEMAS_DIR / "theme.schema.json"

DECK_BRIEF_FILENAME = "deck_brief.json"
DECK_PLAN_FILENAME = "deck_plan.json"
DESIGN_SYSTEM_FILENAME = "design_system.json"

# Same URI-scheme guard the other init_* helpers use.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _has_uri_scheme(s: str) -> bool:
    return bool(_URI_SCHEME_PREFIX.match(s))


def _refuse_symlink(path: Path, label: str) -> tuple[bool, str]:
    """Return (is_symlink, fail_message). A symlink — broken or
    resolvable — is the same anti-pattern init_deck_brief /
    init_deck_plan reject everywhere. Path.exists() returns False for
    a dangling link, so a bare exists() gate would silently follow
    the link; Path.is_file() follows symlinks too. The explicit
    is_symlink() check closes both holes."""
    if not path.is_symlink():
        return False, ""
    try:
        target = str(path.readlink())
    except OSError:
        target = "<unreadable>"
    return True, (
        f"FAIL: {path} ({label}) is a symlink (-> {target}); "
        f"init_design_system refuses to follow it (broken or not). "
        f"Remove or rename the symlink and re-run."
    )


def _schema_validate(value: dict, schema_path: Path) -> list[str]:
    """In-memory schema validation reusing validate_artifacts._validate."""
    schema = json.loads(schema_path.read_text())
    from validate_artifacts import _validate  # noqa: WPS433
    errors: list[str] = []
    _validate(value, schema, "<root>", errors)
    return errors


def _project_theme_to_design_system(theme: dict) -> dict:
    """Map a theme.json into a design_system.json. The two schemas
    intentionally share the palette / typography / grid sub-shapes,
    so the projection is a verbatim carry of those three subtrees
    (no derived fields, no defaults invented here)."""
    return {
        "palette": theme["palette"],
        "typography": theme["typography"],
        "grid": theme["grid"],
    }


def init_design_system(
    *,
    workspace: Path,
    spec: Path | None = None,
    theme_from_template: bool = False,
    template_root: Path | None = None,
) -> tuple[int, str]:
    """Run the full Stage-4 bridge. Returns (exit_code, message).

    Filesystem contract: preflight failures (bad ``--workspace``, bad
    mode arguments, missing / schema-invalid stage-1 / stage-2 /
    stage-3 artifacts, pre-existing ``design_system.json``) leave the
    workspace untouched.

    A post-write re-validation failure rolls back
    ``design_system.json`` so the workspace returns to its pre-call
    state."""
    # --workspace shape gates (string-level FIRST, then filesystem).
    if _has_uri_scheme(str(workspace)):
        return 2, (
            f"FAIL: --workspace {workspace} looks like a URI; "
            f"init_design_system only accepts local directory paths"
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

    # Mode-selection gates: exactly one of --spec / --theme-from-template.
    if spec is None and not theme_from_template:
        return 2, (
            "FAIL: must pass either --spec <path> or "
            "--theme-from-template (with --template-root <dir>); "
            "init_design_system never infers design from raw source text"
        )
    if spec is not None and theme_from_template:
        return 2, (
            "FAIL: --spec and --theme-from-template are mutually "
            "exclusive; pick exactly one input"
        )
    if theme_from_template and template_root is None:
        return 2, (
            "FAIL: --theme-from-template requires --template-root <dir>"
        )
    if not theme_from_template and template_root is not None:
        return 2, (
            "FAIL: --template-root is only meaningful with "
            "--theme-from-template"
        )

    # Stage-4 contract gate: refuse to overwrite a pre-existing design
    # system. Symlink first (broken OR resolvable) — same reason
    # init_deck_brief / init_deck_plan refuse symlinks at their writes.
    ds_path = workspace / DESIGN_SYSTEM_FILENAME
    is_symlink, msg = _refuse_symlink(ds_path, DESIGN_SYSTEM_FILENAME)
    if is_symlink:
        return 2, msg
    if ds_path.exists():
        return 2, (
            f"FAIL: {ds_path} already exists; init_design_system refuses "
            f"to overwrite a prior design system. Rename or remove it "
            f"and re-run."
        )

    # Stage-1 prerequisite: source_manifest.json must exist as a
    # regular file. The bridge below validates its contents.
    manifest_path = workspace / SOURCE_MANIFEST_FILENAME
    is_symlink, msg = _refuse_symlink(manifest_path, SOURCE_MANIFEST_FILENAME)
    if is_symlink:
        return 2, msg
    if not manifest_path.is_file():
        return 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{SOURCE_MANIFEST_FILENAME}; run scripts/init_workspace.py "
            f"first to seed Stage-1 intake."
        )

    # Stage-2 prerequisite: deck_brief.json must exist as a regular file.
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

    # Stage-3 prerequisite: deck_plan.json must exist as a regular file.
    plan_path = workspace / DECK_PLAN_FILENAME
    is_symlink, msg = _refuse_symlink(plan_path, DECK_PLAN_FILENAME)
    if is_symlink:
        return 2, msg
    if not plan_path.is_file():
        return 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{DECK_PLAN_FILENAME}; run scripts/init_deck_plan.py "
            f"first to seed Stage-3."
        )

    # Stage-1/Stage-2 bridge must pass (manifest <-> source.md <->
    # deck_brief.source_refs). Surfaces tampering or stage skew before
    # we honor the prior stages' artifacts.
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

    # Schema-validate deck_brief.json (defense-in-depth: someone may
    # have hand-edited it after init_deck_brief wrote it).
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

    # Schema-validate deck_plan.json.
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

    # Planner-semantics cross-checks the schema cannot express.
    # We re-use init_deck_plan.py's own gate (the function that
    # Stage-3 applies to a candidate plan-spec before it writes
    # deck_plan.json) so Stage-4 enforces EXACTLY the set Stage-3
    # would have. Coverage: planning.planned_slide_count ==
    # len(slides), slide-index uniqueness AND contiguous 1..N (the
    # schema only requires index >= 1, so contiguity is enforced at
    # the helper layer), section coverage 1:1 (every slide.index
    # listed by exactly one section, no duplicates, no missing, no
    # orphans), every slide.section_id resolves AND that section's
    # slide_indices lists the slide's index, every slide.source_refs
    # value is in deck_brief.source_refs. Without this gate
    # Stage-4 would advance from a schema-valid-but-semantically-
    # broken deck_plan (e.g. one whose slide indices are [1, 1, 2]
    # or [1, 2, 4] — both refused by Stage-3, both accepted by the
    # schema alone, both accepted by validate_workspace's narrower
    # section-coverage check).
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

    template_name = plan.get("template")
    if not isinstance(template_name, str) or not template_name:
        # The schema layer already rejects this; defense in depth.
        return 1, (
            f"FAIL: {plan_path}.template must be a non-empty string "
            f"(got {template_name!r})"
        )

    # Build the candidate design_system per mode.
    if spec is not None:
        # --spec mode.
        if _has_uri_scheme(str(spec)):
            return 2, (
                f"FAIL: --spec {spec} looks like a URI; init_design_system "
                f"only accepts local file paths"
            )
        is_symlink, msg = _refuse_symlink(spec, "--spec")
        if is_symlink:
            return 2, msg
        if not spec.exists():
            return 2, f"FAIL: --spec {spec} does not exist"
        if not spec.is_file():
            return 2, f"FAIL: --spec {spec} is not a regular file"
        try:
            ds = json.loads(spec.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return 2, (
                f"FAIL: --spec {spec} did not parse as JSON: {exc}"
            )
        if not isinstance(ds, dict):
            return 2, (
                f"FAIL: --spec {spec} did not decode to an object "
                f"(got {type(ds).__name__})"
            )
        source_label = f"--spec {spec}"
    else:
        # --theme-from-template mode.
        if _has_uri_scheme(str(template_root)):
            return 2, (
                f"FAIL: --template-root {template_root} looks like a URI; "
                f"init_design_system only accepts local directory paths"
            )
        if template_root.is_symlink():
            return 2, (
                f"FAIL: --template-root {template_root} is a symlink; "
                f"refusing to follow it."
            )
        if not template_root.exists():
            return 2, (
                f"FAIL: --template-root {template_root} does not exist"
            )
        if not template_root.is_dir():
            return 2, (
                f"FAIL: --template-root {template_root} is not a directory"
            )

        # deck_plan.template is the only resolver anchor — never default
        # to "business_review" or any other hardcoded name. Path-safety
        # first (rejects URIs, '..', leading slash); then symlink-escape
        # check via _resolves_within.
        if not local_path_is_safe(template_name):
            return 2, (
                f"FAIL: deck_plan.template {template_name!r} is not a "
                f"safe local path (no URI scheme, no '..', no leading "
                f"slash / backslash, non-empty). Refusing to resolve."
            )
        if not _resolves_within(template_root, template_name):
            return 2, (
                f"FAIL: deck_plan.template {template_name!r} escapes "
                f"--template-root {template_root} after resolution; "
                f"refusing."
            )
        template_dir = template_root / template_name
        if template_dir.is_symlink():
            return 2, (
                f"FAIL: template directory {template_dir} is a symlink; "
                f"refusing to follow it."
            )
        if not template_dir.is_dir():
            return 2, (
                f"FAIL: template {template_name!r} not found under "
                f"--template-root (expected directory {template_dir})"
            )

        template_json_path = template_dir / "template.json"
        is_symlink, msg = _refuse_symlink(template_json_path, "template.json")
        if is_symlink:
            return 2, msg
        if not template_json_path.is_file():
            return 2, (
                f"FAIL: template {template_name!r} has no template.json "
                f"(expected {template_json_path})"
            )
        try:
            template = json.loads(template_json_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return 2, (
                f"FAIL: {template_json_path} did not parse as JSON: {exc}"
            )
        if not isinstance(template, dict):
            return 2, (
                f"FAIL: {template_json_path} did not decode to an object "
                f"(got {type(template).__name__})"
            )
        template_errors = _schema_validate(template, TEMPLATE_SCHEMA)
        if template_errors:
            return 1, (
                f"FAIL: {template_json_path} does not validate against "
                f"template.schema.json: {template_errors}"
            )

        theme_ref = template.get("theme_ref")
        if not isinstance(theme_ref, str) or not theme_ref:
            return 1, (
                f"FAIL: {template_json_path}.theme_ref must be a "
                f"non-empty string (got {theme_ref!r})"
            )
        if not local_path_is_safe(theme_ref):
            return 2, (
                f"FAIL: template.theme_ref {theme_ref!r} is not a safe "
                f"local path; refusing to resolve."
            )
        # Symlink refusal on the unresolved path fires BEFORE
        # _resolves_within (which calls .resolve() and would follow the
        # link) so a symlink-redirected theme file fails with a clear
        # "symlink" diagnostic rather than the generic "escapes
        # template directory" message.
        theme_path = template_dir / theme_ref
        is_symlink, msg = _refuse_symlink(theme_path, "theme file")
        if is_symlink:
            return 2, msg
        if not _resolves_within(template_dir, theme_ref):
            return 2, (
                f"FAIL: template.theme_ref {theme_ref!r} escapes the "
                f"template directory after resolution; refusing."
            )
        if not theme_path.is_file():
            return 2, (
                f"FAIL: theme file {theme_path} (referenced by "
                f"{template_json_path}.theme_ref) does not exist"
            )
        try:
            theme = json.loads(theme_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return 2, (
                f"FAIL: {theme_path} did not parse as JSON: {exc}"
            )
        if not isinstance(theme, dict):
            return 2, (
                f"FAIL: {theme_path} did not decode to an object "
                f"(got {type(theme).__name__})"
            )
        theme_errors = _schema_validate(theme, THEME_SCHEMA)
        if theme_errors:
            return 1, (
                f"FAIL: {theme_path} does not validate against "
                f"theme.schema.json: {theme_errors}"
            )

        ds = _project_theme_to_design_system(theme)
        source_label = f"theme {theme_path} (via deck_plan.template={template_name!r})"

    # Pre-write schema validation of the candidate design_system.
    try:
        ds_errors = _schema_validate(ds, DESIGN_SYSTEM_SCHEMA)
    except (Exception, SystemExit) as exc:
        return 1, (
            f"FAIL: pre-write schema validation raised "
            f"{type(exc).__name__}: {exc}"
        )
    if ds_errors:
        return 1, (
            f"FAIL: candidate design_system (from {source_label}) does "
            f"not validate against design_system.schema.json: " +
            "; ".join(ds_errors)
        )

    # Write. Same rollback contract as init_deck_brief / init_deck_plan:
    # the catch clause is explicitly (Exception, SystemExit) so
    # validate_artifact's SystemExit branch on read-errors still routes
    # through rollback. KeyboardInterrupt is intentionally NOT caught.
    try:
        ds_path.write_text(
            json.dumps(ds, indent=2, sort_keys=True) + "\n"
        )
    except (Exception, SystemExit) as exc:
        if ds_path.exists():
            try:
                ds_path.unlink()
            except OSError:
                pass
        return 2, (
            f"FAIL: writing {ds_path} raised {type(exc).__name__}: {exc}"
        )

    try:
        errors = validate_artifact(ds_path, DESIGN_SYSTEM_SCHEMA)
    except (Exception, SystemExit) as exc:
        try:
            ds_path.unlink()
            rb_note = f"removed {ds_path}"
        except OSError as unlink_exc:
            rb_note = f"could not remove {ds_path}: {unlink_exc}"
        return 1, (
            f"FAIL: post-write re-validation of {ds_path} raised "
            f"{type(exc).__name__}: {exc}\n"
            f"rolled back: {rb_note}"
        )
    if errors:
        try:
            ds_path.unlink()
            rb_note = f"removed {ds_path}"
        except OSError as unlink_exc:
            rb_note = f"could not remove {ds_path}: {unlink_exc}"
        return 1, (
            f"FAIL: on-disk design_system at {ds_path} did not "
            f"re-validate: {errors}\n"
            f"rolled back: {rb_note}"
        )

    palette_keys = sorted(ds.get("palette", {}).keys())
    return 0, (
        f"OK: Stage-4 design_system seeded at {ds_path}.\n"
        f"  source: {source_label}\n"
        f"  template (from deck_plan.template): {template_name!r}\n"
        f"  palette keys: {palette_keys}\n"
        f"  typography: heading={ds['typography']['heading']['size_pt']}pt, "
        f"body={ds['typography']['body']['size_pt']}pt\n"
        f"  grid: {ds['grid']['width_px']}x{ds['grid']['height_px']} "
        f"margin={ds['grid']['margin_px']}\n"
        f"Next stages (agent-driven; init_design_system.py does not "
        f"automate them):\n"
        f"  5. slide_plans/*.json\n"
        f"  6. image_manifest.json\n"
        f"Once those exist, scripts/run_pipeline.py can take over "
        f"for stages 7-10."
    )


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs under
# tempfile.TemporaryDirectory(); no fixture leaks into the repo.
# ---------------------------------------------------------------------------

_SYNTH_SOURCE_MD = (
    "# Synthetic Source\n\n"
    "Synthetic .md body — never inspected by init_design_system.\n"
    "Line three.\n"
)

_SAMPLE_THEME = {
    "name": "synthetic_template",
    "version": "0.1.0",
    "status": "scaffold",
    "palette": {
        "primary": "#112233",
        "secondary": "#445566",
        "accent": "#AABBCC",
        "background": "#FFFFFF",
        "text": "#101010",
    },
    "typography": {
        "heading": {"font_family": "Arial, sans-serif", "size_pt": 24},
        "body": {"font_family": "Arial, sans-serif", "size_pt": 12},
    },
    "grid": {"width_px": 1280, "height_px": 720, "margin_px": 32},
}


def _seed_stage123_workspace(
    ws: Path,
    *,
    template_name: str = "synthetic_template",
    source_id: str = "synthetic_src",
    body: bytes | None = None,
    write_source_manifest: bool = True,
    write_deck_brief: bool = True,
    write_deck_plan: bool = True,
    plan_override: dict | None = None,
    plan_raw_text: str | None = None,
    brief_override: dict | None = None,
    brief_raw_text: str | None = None,
) -> None:
    """Mimic what init_workspace + init_deck_brief + init_deck_plan
    would have written. Synthetic only; does not invoke them as
    subprocesses so targeted negative mutations stay simple."""
    import hashlib
    if body is None:
        body = _SYNTH_SOURCE_MD.encode("utf-8")
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "input").mkdir(parents=True, exist_ok=True)
    (ws / "input" / "source.md").write_bytes(body)
    if write_source_manifest:
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
    if write_deck_brief:
        if brief_raw_text is not None:
            (ws / DECK_BRIEF_FILENAME).write_text(brief_raw_text)
        else:
            brief = brief_override if brief_override is not None else {
                "title": "Synthetic Title",
                "audience": "Synthetic Audience",
                "objective": "Synthetic Objective",
                "source_refs": [source_id],
            }
            (ws / DECK_BRIEF_FILENAME).write_text(
                json.dumps(brief, indent=2, sort_keys=True) + "\n"
            )
    if write_deck_plan:
        if plan_raw_text is not None:
            (ws / DECK_PLAN_FILENAME).write_text(plan_raw_text)
        else:
            plan = plan_override if plan_override is not None else {
                "template": template_name,
                "planning": {
                    "planned_slide_count": 1,
                    "rationale": "Synthetic single-slide plan for self-test.",
                },
                "sections": [
                    {
                        "id": "main", "title": "Main",
                        "summary": "Synthetic section.",
                        "slide_indices": [1],
                    },
                ],
                "slides": [
                    {
                        "index": 1, "layout": "cover",
                        "title": "Synthetic Cover", "section_id": "main",
                        "summary": "Synthetic cover slide.",
                        "density": "low", "source_refs": [source_id],
                    },
                ],
            }
            (ws / DECK_PLAN_FILENAME).write_text(
                json.dumps(plan, indent=2, sort_keys=True) + "\n"
            )


def _seed_template_root(
    template_root: Path,
    *,
    template_name: str = "synthetic_template",
    theme: dict | None = None,
    theme_ref: str = "theme.json",
    omit_theme_file: bool = False,
) -> Path:
    """Write a minimal template.json + theme.json under
    <template-root>/<template_name>/. Returns the template directory."""
    template_root.mkdir(parents=True, exist_ok=True)
    tdir = template_root / template_name
    tdir.mkdir(parents=True, exist_ok=True)
    template_manifest = {
        "name": template_name,
        "version": "0.1.0",
        "status": "scaffold",
        "theme_ref": theme_ref,
        "layouts": ["cover"],
    }
    (tdir / "template.json").write_text(
        json.dumps(template_manifest, indent=2, sort_keys=True) + "\n"
    )
    if not omit_theme_file:
        theme_obj = theme if theme is not None else dict(_SAMPLE_THEME)
        theme_obj.setdefault("name", template_name)
        (tdir / theme_ref).write_text(
            json.dumps(theme_obj, indent=2, sort_keys=True) + "\n"
        )
    return tdir


def _write_spec(td: Path, spec: dict, name: str = "spec.json") -> Path:
    path = td / name
    path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    return path


def _minimal_design_spec() -> dict:
    return {
        "palette": {
            "primary": "#102030",
            "background": "#FFFFFF",
            "text": "#202020",
        },
        "typography": {
            "heading": {"font_family": "Inter, sans-serif", "size_pt": 30},
            "body": {"font_family": "Inter, sans-serif", "size_pt": 14},
        },
        "grid": {"width_px": 1920, "height_px": 1080, "margin_px": 48},
    }


def _expect(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


def _run_self_tests() -> list[tuple[str, bool, str]]:
    import tempfile

    results: list[tuple[str, bool, str]] = []

    # 1. happy path (--spec): minimal valid spec produces a schema-valid
    # design_system.json byte-identical to what we serialized.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_happy_spec"
        _seed_stage123_workspace(ws)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ds_path = ws / DESIGN_SYSTEM_FILENAME
        ok = rc == 0 and ds_path.is_file()
        if ok:
            written = json.loads(ds_path.read_text())
            ok = (
                written.get("palette", {}).get("primary") == "#102030"
                and written.get("grid", {}).get("width_px") == 1920
            )
        results.append(_expect(
            "happy path (--spec): minimal spec yields a schema-valid "
            "design_system.json carrying spec tokens verbatim",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 2. happy path (--theme-from-template): theme.json projection
    # produces a schema-valid design_system.json.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_happy_theme"
        troot = td / "tpl_root"
        _seed_stage123_workspace(ws, template_name="synthetic_template")
        _seed_template_root(troot, template_name="synthetic_template")
        rc, msg = init_design_system(
            workspace=ws,
            theme_from_template=True,
            template_root=troot,
        )
        ds_path = ws / DESIGN_SYSTEM_FILENAME
        ok = rc == 0 and ds_path.is_file()
        if ok:
            written = json.loads(ds_path.read_text())
            ok = (
                written.get("palette", {}).get("primary") == "#112233"
                and written.get("typography", {}).get("body", {}).get("size_pt") == 12
                and written.get("grid", {}).get("width_px") == 1280
            )
        results.append(_expect(
            "happy path (--theme-from-template): theme projection yields "
            "a schema-valid design_system.json with palette/typography/grid "
            "carried verbatim from the resolved theme",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 3. determinism (--spec): two runs from same workspace + spec
    # produce byte-identical design_systems.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws_a = td / "ws_det_a"
        ws_b = td / "ws_det_b"
        _seed_stage123_workspace(ws_a)
        _seed_stage123_workspace(ws_b)
        spec_a = _write_spec(td, _minimal_design_spec(), "a.json")
        spec_b = _write_spec(td, _minimal_design_spec(), "b.json")
        rc_a, _ = init_design_system(workspace=ws_a, spec=spec_a)
        rc_b, _ = init_design_system(workspace=ws_b, spec=spec_b)
        bytes_a = (ws_a / DESIGN_SYSTEM_FILENAME).read_bytes() if rc_a == 0 else b""
        bytes_b = (ws_b / DESIGN_SYSTEM_FILENAME).read_bytes() if rc_b == 0 else b""
        ok = rc_a == 0 and rc_b == 0 and bytes_a == bytes_b and bytes_a
        results.append(_expect(
            "determinism (--spec): two independent runs produce byte-"
            "identical design_systems",
            ok, f"rc_a={rc_a}, rc_b={rc_b}, equal={bytes_a == bytes_b}",
        ))

    # 4. determinism (--theme-from-template): two runs from same
    # workspace + template-root produce byte-identical design_systems.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws_a = td / "ws_dt_a"
        ws_b = td / "ws_dt_b"
        troot = td / "tpl_root"
        _seed_stage123_workspace(ws_a)
        _seed_stage123_workspace(ws_b)
        _seed_template_root(troot)
        rc_a, _ = init_design_system(
            workspace=ws_a, theme_from_template=True, template_root=troot,
        )
        rc_b, _ = init_design_system(
            workspace=ws_b, theme_from_template=True, template_root=troot,
        )
        bytes_a = (ws_a / DESIGN_SYSTEM_FILENAME).read_bytes() if rc_a == 0 else b""
        bytes_b = (ws_b / DESIGN_SYSTEM_FILENAME).read_bytes() if rc_b == 0 else b""
        ok = rc_a == 0 and rc_b == 0 and bytes_a == bytes_b and bytes_a
        results.append(_expect(
            "determinism (--theme-from-template): two independent runs "
            "produce byte-identical design_systems",
            ok, f"rc_a={rc_a}, rc_b={rc_b}, equal={bytes_a == bytes_b}",
        ))

    # 5. missing deck_plan -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_plan"
        _seed_stage123_workspace(ws, write_deck_plan=False)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 2
            and DECK_PLAN_FILENAME in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "missing deck_plan.json refused (no silent fallback)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 6. malformed deck_plan (non-JSON) -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_bad_plan"
        _seed_stage123_workspace(ws, plan_raw_text="{ not valid json")
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc in (1, 2)
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "malformed deck_plan.json (non-JSON) refused before any "
            "design_system is written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 7. schema-invalid deck_plan -> refused at the schema layer.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_plan_schema_bad"
        broken_plan = {
            "template": "synthetic_template",
            # Missing 'planning' / 'sections' / 'slides'.
        }
        _seed_stage123_workspace(ws, plan_override=broken_plan)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "deck_plan" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "schema-invalid deck_plan.json refused at the schema layer",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 7b. schema-valid but semantically invalid deck_plan with a
    # planned_slide_count that does not match len(slides) -> refused
    # at the planner-semantics cross-check. Without this gate the
    # helper would advance Stage-4 from a broken prior stage.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_plan_count_mismatch"
        bad_plan = {
            "template": "synthetic_template",
            "planning": {
                "planned_slide_count": 5,  # disagrees with len(slides) == 1
                "rationale": "Synthetic plan with deliberate count mismatch.",
            },
            "sections": [
                {
                    "id": "main", "title": "Main",
                    "summary": "Synthetic section.",
                    "slide_indices": [1],
                },
            ],
            "slides": [
                {
                    "index": 1, "layout": "cover",
                    "title": "Cover", "section_id": "main",
                    "summary": "Synthetic cover.",
                    "density": "low",
                    "source_refs": ["synthetic_src"],
                },
            ],
        }
        _seed_stage123_workspace(ws, plan_override=bad_plan)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "planner-semantics" in msg
            and "planned_slide_count" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "schema-valid deck_plan with planned_slide_count != len(slides) "
            "refused at the planner-semantics cross-check (Stage-4 cannot "
            "advance from a semantically invalid prior stage)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 7c. deck_plan that schema-validates but whose sections omit a
    # slide_index (broken section coverage) -> refused at the
    # planner-semantics cross-check.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_plan_section_miss"
        bad_plan = {
            "template": "synthetic_template",
            "planning": {
                "planned_slide_count": 2,
                "rationale": "Synthetic 2-slide plan with broken section coverage.",
            },
            "sections": [
                {
                    "id": "main", "title": "Main",
                    "summary": "Synthetic section that omits slide 2.",
                    "slide_indices": [1],  # missing slide 2
                },
            ],
            "slides": [
                {
                    "index": 1, "layout": "cover",
                    "title": "Cover", "section_id": "main",
                    "summary": "Synthetic cover.",
                    "density": "low",
                    "source_refs": ["synthetic_src"],
                },
                {
                    "index": 2, "layout": "conclusion",
                    "title": "Close", "section_id": "main",
                    "summary": "Synthetic close.",
                    "density": "low",
                    "source_refs": ["synthetic_src"],
                },
            ],
        }
        _seed_stage123_workspace(ws, plan_override=bad_plan)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "planner-semantics" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "schema-valid deck_plan with broken section coverage (a slide "
            "no section lists) refused at the planner-semantics cross-check",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 7d. deck_plan that schema-validates but whose slide.source_refs
    # cites an id NOT declared in deck_brief.source_refs -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_plan_ref_undeclared"
        bad_plan = {
            "template": "synthetic_template",
            "planning": {
                "planned_slide_count": 1,
                "rationale": "Synthetic plan with undeclared slide source ref.",
            },
            "sections": [
                {
                    "id": "main", "title": "Main",
                    "summary": "Synthetic section.",
                    "slide_indices": [1],
                },
            ],
            "slides": [
                {
                    "index": 1, "layout": "cover",
                    "title": "Cover", "section_id": "main",
                    "summary": "Synthetic cover.",
                    "density": "low",
                    "source_refs": ["__never_declared_in_brief__"],
                },
            ],
        }
        _seed_stage123_workspace(ws, plan_override=bad_plan)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "planner-semantics" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "schema-valid deck_plan with slide.source_refs not in "
            "deck_brief.source_refs refused at the planner-semantics "
            "cross-check",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 7e. schema-valid deck_plan with DUPLICATE slide indices (e.g.
    # [1, 1]). The deck_plan schema permits any integer >= 1, so a
    # plan with duplicate indices is schema-valid. init_deck_plan.py
    # refuses it at the planner-semantics cross-check; Stage-4 must
    # do the same, otherwise it would advance from a deck_plan that
    # init_deck_plan.py would never have written.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_plan_dup_idx"
        bad_plan = {
            "template": "synthetic_template",
            "planning": {
                "planned_slide_count": 2,
                "rationale": "Synthetic plan with duplicate slide indices.",
            },
            "sections": [
                {
                    "id": "main", "title": "Main",
                    "summary": "Synthetic section.",
                    "slide_indices": [1, 1],
                },
            ],
            "slides": [
                {
                    "index": 1, "layout": "cover",
                    "title": "Cover A", "section_id": "main",
                    "summary": "Synthetic cover.",
                    "density": "low",
                    "source_refs": ["synthetic_src"],
                },
                {
                    "index": 1, "layout": "conclusion",
                    "title": "Cover B", "section_id": "main",
                    "summary": "Synthetic close (duplicate index).",
                    "density": "low",
                    "source_refs": ["synthetic_src"],
                },
            ],
        }
        _seed_stage123_workspace(ws, plan_override=bad_plan)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "planner-semantics" in msg
            and "duplicates" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "schema-valid deck_plan with duplicate slide indices "
            "([1, 1]) refused at the planner-semantics cross-check "
            "(parity with init_deck_plan.py — the section-coverage "
            "check alone would dedup the index set and miss this)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 7f. schema-valid deck_plan with NON-CONTIGUOUS slide indices
    # (e.g. [1, 2, 4]). Schema permits each index >= 1; sections can
    # cover [1, 2, 4] cleanly; the only check that fails this is
    # init_deck_plan.py's contiguous-1..N rule. Stage-4 must enforce
    # it too, or it would advance from a deck_plan that
    # init_deck_plan.py would never have written.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_plan_noncontig"
        bad_plan = {
            "template": "synthetic_template",
            "planning": {
                "planned_slide_count": 3,
                "rationale": "Synthetic plan with non-contiguous indices.",
            },
            "sections": [
                {
                    "id": "main", "title": "Main",
                    "summary": "Synthetic section covering 1/2/4.",
                    "slide_indices": [1, 2, 4],
                },
            ],
            "slides": [
                {
                    "index": 1, "layout": "cover",
                    "title": "Cover", "section_id": "main",
                    "summary": "Synthetic cover.",
                    "density": "low",
                    "source_refs": ["synthetic_src"],
                },
                {
                    "index": 2, "layout": "executive_summary",
                    "title": "Summary", "section_id": "main",
                    "summary": "Synthetic summary.",
                    "density": "medium",
                    "source_refs": ["synthetic_src"],
                },
                {
                    "index": 4, "layout": "conclusion",
                    "title": "Close", "section_id": "main",
                    "summary": "Synthetic close — index 4 with no index 3.",
                    "density": "low",
                    "source_refs": ["synthetic_src"],
                },
            ],
        }
        _seed_stage123_workspace(ws, plan_override=bad_plan)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "planner-semantics" in msg
            and "contiguous" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "schema-valid deck_plan with non-contiguous slide indices "
            "([1, 2, 4]) refused at the planner-semantics cross-check "
            "(parity with init_deck_plan.py — the schema and the "
            "section-coverage check both accept this)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 7g. schema-valid deck_plan whose slide.section_id names an
    # unknown section -> refused. Section coverage alone may not
    # surface this if the section's slide_indices happen to align;
    # init_deck_plan.py refuses it explicitly.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_plan_unknown_section"
        bad_plan = {
            "template": "synthetic_template",
            "planning": {
                "planned_slide_count": 1,
                "rationale": "Synthetic plan with unknown slide.section_id.",
            },
            "sections": [
                {
                    "id": "main", "title": "Main",
                    "summary": "Synthetic section.",
                    "slide_indices": [1],
                },
            ],
            "slides": [
                {
                    "index": 1, "layout": "cover",
                    "title": "Cover",
                    "section_id": "ghost_section_id",  # not declared
                    "summary": "Synthetic cover.",
                    "density": "low",
                    "source_refs": ["synthetic_src"],
                },
            ],
        }
        _seed_stage123_workspace(ws, plan_override=bad_plan)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "planner-semantics" in msg
            and "section_id" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "schema-valid deck_plan with slide.section_id naming an "
            "unknown section refused at the planner-semantics "
            "cross-check (parity with init_deck_plan.py)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 8. missing deck_brief -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_brief"
        _seed_stage123_workspace(ws, write_deck_brief=False)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 2
            and DECK_BRIEF_FILENAME in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "missing deck_brief.json refused (Stage-2 prerequisite)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 9. unknown template (--theme-from-template): template name resolved
    # against template-root but the directory does not exist -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_unknown_template"
        troot = td / "tpl_root"
        _seed_stage123_workspace(ws, template_name="not_a_real_template")
        _seed_template_root(troot, template_name="synthetic_template")
        rc, msg = init_design_system(
            workspace=ws,
            theme_from_template=True,
            template_root=troot,
        )
        ok = (
            rc == 2
            and "not_a_real_template" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "unknown template (deck_plan.template not under "
            "--template-root) refused; no business_review fallback",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 10. unsafe template path: deck_plan.template = '..' -> refused at
    # the path-safety gate before any filesystem read.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_unsafe_template"
        troot = td / "tpl_root"
        _seed_stage123_workspace(ws, template_name="..")
        _seed_template_root(troot)
        rc, msg = init_design_system(
            workspace=ws,
            theme_from_template=True,
            template_root=troot,
        )
        ok = (
            rc == 2
            and "safe local path" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "unsafe template path (deck_plan.template='..') refused at "
            "the path-safety gate",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 10b. template name with URI scheme -> refused at path-safety.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_uri_template"
        troot = td / "tpl_root"
        _seed_stage123_workspace(ws, template_name="https://attacker/x")
        _seed_template_root(troot)
        rc, msg = init_design_system(
            workspace=ws,
            theme_from_template=True,
            template_root=troot,
        )
        ok = (
            rc == 2
            and "safe local path" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "URI-scheme template name (deck_plan.template='https://...') "
            "refused at the path-safety gate",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 11. missing theme file (--theme-from-template): template.json's
    # theme_ref points at a file that does not exist -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_theme_file"
        troot = td / "tpl_root"
        _seed_stage123_workspace(ws, template_name="synthetic_template")
        _seed_template_root(troot, omit_theme_file=True)
        rc, msg = init_design_system(
            workspace=ws,
            theme_from_template=True,
            template_root=troot,
        )
        ok = (
            rc == 2
            and "theme" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "missing theme file (template.theme_ref dangling) refused; "
            "no design_system written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 12. missing --spec path -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_spec"
        _seed_stage123_workspace(ws)
        rc, msg = init_design_system(
            workspace=ws, spec=td / "no_such_spec.json",
        )
        ok = (
            rc == 2
            and "does not exist" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "missing --spec path refused (no silent fallback)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 13. malformed --spec (non-JSON) -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_bad_spec"
        _seed_stage123_workspace(ws)
        bad = td / "bad.json"
        bad.write_text("{ not valid json")
        rc, msg = init_design_system(workspace=ws, spec=bad)
        ok = (
            rc == 2
            and "JSON" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "malformed (non-JSON) --spec refused at parse layer",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 14. spec is a list (not object) -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_spec_list"
        _seed_stage123_workspace(ws)
        list_spec = td / "list.json"
        list_spec.write_text("[1, 2, 3]")
        rc, msg = init_design_system(workspace=ws, spec=list_spec)
        ok = (
            rc == 2
            and "object" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "list-rooted --spec refused (must decode to an object)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 15. schema-invalid --spec: bad hex color -> refused at schema.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_bad_color"
        _seed_stage123_workspace(ws)
        bad_spec = _minimal_design_spec()
        bad_spec["palette"]["primary"] = "not-a-hex"
        spec_path = _write_spec(td, bad_spec)
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "pattern" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "schema-invalid --spec (bad hex color) refused at schema layer",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 15b. schema-invalid --spec: bad font_family (empty) -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_bad_font"
        _seed_stage123_workspace(ws)
        bad_spec = _minimal_design_spec()
        bad_spec["typography"]["heading"]["font_family"] = ""
        spec_path = _write_spec(td, bad_spec)
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and ("font_family" in msg or "minLength" in msg)
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "schema-invalid --spec (empty font_family) refused at schema "
            "layer",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 15c. schema-invalid --spec: non-positive grid width -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_bad_grid"
        _seed_stage123_workspace(ws)
        bad_spec = _minimal_design_spec()
        bad_spec["grid"]["width_px"] = 0
        spec_path = _write_spec(td, bad_spec)
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and ("exclusiveMinimum" in msg or "width_px" in msg)
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "schema-invalid --spec (grid width_px <= 0) refused at "
            "schema layer",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 15d. schema-invalid --spec: negative grid margin -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_neg_margin"
        _seed_stage123_workspace(ws)
        bad_spec = _minimal_design_spec()
        bad_spec["grid"]["margin_px"] = -10
        spec_path = _write_spec(td, bad_spec)
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and ("minimum" in msg or "margin_px" in msg)
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "schema-invalid --spec (grid margin_px < 0) refused at "
            "schema layer",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 16. pre-existing design_system.json refused; prior bytes preserved.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_existing"
        _seed_stage123_workspace(ws)
        prior = json.dumps({"prior": True}, indent=2)
        (ws / DESIGN_SYSTEM_FILENAME).write_text(prior)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        preserved = (ws / DESIGN_SYSTEM_FILENAME).read_text() == prior
        ok = rc == 2 and "already exists" in msg and preserved
        results.append(_expect(
            "pre-existing design_system.json refused (no overwrite); "
            "prior bytes preserved byte-identical",
            ok, f"rc={rc}, preserved={preserved}",
        ))

    # 17. broken symlink at design_system.json refused BEFORE write_text;
    # dangling target never created.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_broken_ds_link"
        _seed_stage123_workspace(ws)
        target = td / "outside_must_not_be_written.json"
        assert not target.exists()
        (ws / DESIGN_SYSTEM_FILENAME).symlink_to(target)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        still_symlink = (ws / DESIGN_SYSTEM_FILENAME).is_symlink()
        target_absent = not target.exists()
        ok = (
            rc == 2
            and "symlink" in msg
            and still_symlink
            and target_absent
        )
        results.append(_expect(
            "broken symlink at design_system.json refused BEFORE "
            "write_text could follow it",
            ok,
            f"rc={rc}, still_symlink={still_symlink}, "
            f"target_absent={target_absent}",
        ))

    # 17b. resolvable symlink at design_system.json refused; outside
    # target bytes preserved.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_live_ds_link"
        _seed_stage123_workspace(ws)
        outside = td / "unrelated.json"
        outside_bytes = b'{"unrelated": "must not be clobbered"}\n'
        outside.write_bytes(outside_bytes)
        (ws / DESIGN_SYSTEM_FILENAME).symlink_to(outside)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws, spec=spec_path)
        outside_preserved = outside.read_bytes() == outside_bytes
        ok = rc == 2 and "symlink" in msg and outside_preserved
        results.append(_expect(
            "resolvable symlink at design_system.json refused; outside "
            "target bytes preserved byte-identical",
            ok, f"rc={rc}, outside_preserved={outside_preserved}",
        ))

    # 18. symlink at --spec refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_spec_link"
        _seed_stage123_workspace(ws)
        spec_target = td / "no_such_spec.json"
        spec_link = td / "link.json"
        spec_link.symlink_to(spec_target)
        rc, msg = init_design_system(workspace=ws, spec=spec_link)
        ok = (
            rc == 2
            and "symlink" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "symlink at --spec refused at the preflight",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 19. symlink at theme file (--theme-from-template) refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_theme_link"
        troot = td / "tpl_root"
        _seed_stage123_workspace(ws)
        tdir = _seed_template_root(troot, omit_theme_file=True)
        elsewhere = td / "outside_theme.json"
        elsewhere.write_text(json.dumps(_SAMPLE_THEME))
        (tdir / "theme.json").symlink_to(elsewhere)
        rc, msg = init_design_system(
            workspace=ws,
            theme_from_template=True,
            template_root=troot,
        )
        ok = (
            rc == 2
            and "symlink" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "symlink at the theme file refused (no off-template-tree "
            "redirection of theme bytes)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 20. symlink at workspace refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws_real = td / "ws_real"
        ws_real.mkdir()
        _seed_stage123_workspace(ws_real)
        ws_link = td / "ws_link"
        ws_link.symlink_to(ws_real)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(workspace=ws_link, spec=spec_path)
        ok = (
            rc == 2
            and "symlink" in msg
            and not (ws_real / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "--workspace pointing at a symlink refused at the preflight",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 21. URI-scheme --workspace refused at string layer.
    rc, msg = init_design_system(
        workspace=Path("https://attacker.example/ws"),
        spec=Path("/tmp/no.json"),
    )
    ok = rc == 2 and "URI" in msg
    results.append(_expect(
        "--workspace with URI scheme refused at the string level",
        ok, f"rc={rc}",
    ))

    # 22. --spec and --theme-from-template both supplied -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_both_modes"
        troot = td / "tpl_root"
        _seed_stage123_workspace(ws)
        _seed_template_root(troot)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(
            workspace=ws,
            spec=spec_path,
            theme_from_template=True,
            template_root=troot,
        )
        ok = (
            rc == 2
            and "mutually exclusive" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "--spec and --theme-from-template are mutually exclusive",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 23. neither --spec nor --theme-from-template -> refused (no
    # silent fallback that infers design from source text).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_mode"
        _seed_stage123_workspace(ws)
        rc, msg = init_design_system(workspace=ws)
        ok = (
            rc == 2
            and "must pass either" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "neither --spec nor --theme-from-template supplied -> refused "
            "(no silent inference from source text)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 24. --theme-from-template without --template-root -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_root"
        _seed_stage123_workspace(ws)
        rc, msg = init_design_system(
            workspace=ws, theme_from_template=True,
        )
        ok = (
            rc == 2
            and "--template-root" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "--theme-from-template without --template-root refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 25. raw source body marker phrase is NEVER copied into
    # design_system.json (helper never opens input/source.md).
    marker = "MARKER_NEVER_EXTRACT_4d1a8f"
    body = (f"# Title\n\nBody with {marker} in it.\n").encode("utf-8")
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_marker"
        _seed_stage123_workspace(ws, body=body)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, _ = init_design_system(workspace=ws, spec=spec_path)
        ok = rc == 0
        if ok:
            written_bytes = (ws / DESIGN_SYSTEM_FILENAME).read_bytes()
            ok = marker.encode("utf-8") not in written_bytes
        results.append(_expect(
            "raw source body marker phrase is NEVER copied into "
            "design_system.json (helper does not extract content)",
            ok, f"rc={rc}",
        ))

    # 26. post-write re-validation forced failure (via mock) rolls back.
    import unittest.mock
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_rb"
        _seed_stage123_workspace(ws)
        spec_path = _write_spec(td, _minimal_design_spec())
        with unittest.mock.patch(
            f"{__name__}.validate_artifact",
            return_value=["forced test failure"],
        ):
            rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "rolled back" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "post-write re-validation failure (forced via mock) rolls "
            "back the design_system",
            ok, f"rc={rc}",
        ))

    # 27. post-write re-validation raising SystemExit also rolls back
    # (proves the catch clause is (Exception, SystemExit)).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_rb_sysexit"
        _seed_stage123_workspace(ws)
        spec_path = _write_spec(td, _minimal_design_spec())
        with unittest.mock.patch(
            f"{__name__}.validate_artifact",
            side_effect=SystemExit("simulated read-error branch"),
        ):
            rc, msg = init_design_system(workspace=ws, spec=spec_path)
        ok = (
            rc == 1
            and "rolled back" in msg
            and "SystemExit" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "post-write re-validation raising SystemExit rolls back",
            ok, f"rc={rc}",
        ))

    # 28. on-disk design_system re-validates via validate_artifact.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_revalidate"
        _seed_stage123_workspace(ws)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, _ = init_design_system(workspace=ws, spec=spec_path)
        ok = rc == 0
        if ok:
            errors = validate_artifact(
                ws / DESIGN_SYSTEM_FILENAME, DESIGN_SYSTEM_SCHEMA,
            )
            ok = not errors
        results.append(_expect(
            "on-disk design_system.json re-validates against "
            "schemas/design_system.schema.json",
            ok, f"rc={rc}",
        ))

    # 29. custom template name resolves correctly (no business_review
    # default): deck_plan.template = "custom_light" picks up
    # <template-root>/custom_light/theme.json.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_custom_template"
        troot = td / "tpl_root"
        custom_theme = {
            "name": "custom_light",
            "version": "0.2.0",
            "status": "scaffold",
            "palette": {
                "primary": "#FF0000",
                "background": "#FFFFFF",
                "text": "#000000",
            },
            "typography": {
                "heading": {"font_family": "Georgia, serif", "size_pt": 36},
                "body": {"font_family": "Georgia, serif", "size_pt": 16},
            },
            "grid": {"width_px": 1024, "height_px": 768, "margin_px": 24},
        }
        _seed_stage123_workspace(ws, template_name="custom_light")
        _seed_template_root(
            troot, template_name="custom_light", theme=custom_theme,
        )
        rc, msg = init_design_system(
            workspace=ws,
            theme_from_template=True,
            template_root=troot,
        )
        ok = rc == 0 and (ws / DESIGN_SYSTEM_FILENAME).is_file()
        if ok:
            written = json.loads((ws / DESIGN_SYSTEM_FILENAME).read_text())
            ok = (
                written["palette"]["primary"] == "#FF0000"
                and written["typography"]["heading"]["size_pt"] == 36
            )
        results.append(_expect(
            "custom (non-business_review) deck_plan.template resolved "
            "via --template-root; helper has no hardcoded template default",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 30. --template-root supplied without --theme-from-template -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_root_no_flag"
        troot = td / "tpl_root"
        _seed_stage123_workspace(ws)
        _seed_template_root(troot)
        spec_path = _write_spec(td, _minimal_design_spec())
        rc, msg = init_design_system(
            workspace=ws, spec=spec_path, template_root=troot,
        )
        ok = (
            rc == 2
            and "--template-root" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "--template-root supplied without --theme-from-template "
            "refused (no silent mode switch)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 31. template-root not a directory -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_root_file"
        _seed_stage123_workspace(ws)
        not_a_dir = td / "not_a_dir.txt"
        not_a_dir.write_text("hi")
        rc, msg = init_design_system(
            workspace=ws,
            theme_from_template=True,
            template_root=not_a_dir,
        )
        ok = (
            rc == 2
            and "not a directory" in msg
            and not (ws / DESIGN_SYSTEM_FILENAME).exists()
        )
        results.append(_expect(
            "--template-root pointing at a regular file refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage-4 (Design System) design_system.json helper. Bridges "
            "a stage-3-initialized workspace (source_manifest.json + "
            "input/source.md + deck_brief.json + deck_plan.json) into a "
            "minimal, schema-valid design_system.json. Tokens come from "
            "EXACTLY ONE explicit caller input: either --spec (a complete "
            "design_system.json the caller wants validated and written) "
            "or --theme-from-template (project palette/typography/grid "
            "from the theme of the template named in deck_plan.template, "
            "resolved against --template-root). The helper does NOT "
            "extract business content from input/source.md and does NOT "
            "infer design tokens from raw source text. Template "
            "resolution is anchored on deck_plan.template; there is no "
            "product-level default."
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Workspace directory (must already contain "
             "source_manifest.json + input/source.md + deck_brief.json + "
             "deck_plan.json, e.g. seeded by scripts/init_workspace.py + "
             "scripts/init_deck_brief.py + scripts/init_deck_plan.py).",
    )
    parser.add_argument(
        "--spec", type=Path, default=None,
        help="Path to a JSON file whose shape is exactly the "
             "design_system candidate to be written: "
             "{ palette, typography, grid }. The helper validates this "
             "against schemas/design_system.schema.json and writes the "
             "result verbatim. Mutually exclusive with "
             "--theme-from-template.",
    )
    parser.add_argument(
        "--theme-from-template", action="store_true",
        help="Project palette / typography / grid from the theme of the "
             "template named in deck_plan.template, resolved against "
             "--template-root. The helper has no hardcoded template "
             "default; whatever name deck_plan.template carries is "
             "looked up under --template-root. Mutually exclusive with "
             "--spec; requires --template-root.",
    )
    parser.add_argument(
        "--template-root", type=Path, default=None,
        help="Directory under which templates live, e.g. "
             "templates/layouts/. Used only with --theme-from-template. "
             "The directory itself must be a regular directory (no "
             "symlinks); deck_plan.template must be a path-safe local "
             "name that resolves inside this directory.",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios covering: happy path "
             "(--spec), happy path (--theme-from-template), determinism "
             "(both modes), missing / malformed / schema-invalid "
             "deck_plan.json, schema-valid-but-semantically-invalid "
             "deck_plan (planned_slide_count mismatch, broken section "
             "coverage, undeclared slide.source_refs, duplicate slide "
             "indices, non-contiguous slide indices, unknown "
             "slide.section_id) refused at the planner-semantics "
             "cross-check (the same gate init_deck_plan.py applies "
             "before writing a Stage-3 artifact), missing "
             "deck_brief.json, unknown template, "
             "unsafe template path (.. / URI scheme), missing theme "
             "file, missing / malformed / list-rooted / schema-invalid "
             "--spec (bad color / empty font / non-positive grid / "
             "negative margin), pre-existing design_system.json "
             "preservation, broken / resolvable symlink at "
             "design_system.json, symlink at --spec, symlink at theme "
             "file, symlink at --workspace, URI-scheme --workspace, "
             "--spec + --theme-from-template (mutually exclusive), "
             "neither mode supplied, --theme-from-template without "
             "--template-root, --template-root without "
             "--theme-from-template, --template-root not a directory, "
             "source-body marker never copied into design_system, mocked "
             "post-write rollback (return errors / raise SystemExit), "
             "on-disk re-validation, and a custom (non-business_review) "
             "template name resolved correctly. Exits non-zero if any "
             "scenario does not behave as expected. Mutually exclusive "
             "with --workspace / --spec / --theme-from-template / "
             "--template-root.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if any(v is not None for v in (
            args.workspace, args.spec, args.template_root,
        )) or args.theme_from_template:
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
            "happy-path design_system is written from the caller's "
            "explicit input."
        )
        return 0

    if args.workspace is None:
        print(
            "FAIL: missing required argument: --workspace "
            "(use --self-test for the in-script scenarios)",
            file=sys.stderr,
        )
        return 2

    rc, msg = init_design_system(
        workspace=args.workspace,
        spec=args.spec,
        theme_from_template=args.theme_from_template,
        template_root=args.template_root,
    )
    if rc == 0:
        print(msg)
    else:
        print(msg, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
