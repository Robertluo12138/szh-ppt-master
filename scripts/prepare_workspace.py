#!/usr/bin/env python3
"""Stage-1-to-6 local orchestration helper.

Chains the six existing per-stage contract helpers in a single
deterministic command, driven entirely by explicit caller-supplied
inputs:

    1. scripts/init_workspace.py        (Intake)
    2. scripts/init_deck_brief.py       (Brief)
    3. scripts/init_deck_plan.py        (Plan)
    4. scripts/init_design_system.py    (Design system)
    5. scripts/init_slide_plans.py      (Per-slide plans)
    6. scripts/init_image_manifest.py   (Image manifest)

After every stage succeeds, the workspace contains the Stage-1-through-6
artifacts ``scripts/run_pipeline.py`` consumes: ``input/source.md``,
``source_manifest.json``, ``deck_brief.json``, ``deck_plan.json``,
``design_system.json``, ``slide_plans/<idx:02d>_<layout>.json``, and
``image_manifest.json``.

**This is explicit-input orchestration only — it is NOT a full
prompt/report/Markdown-to-PPTX automation.** Every stage's content
comes from the caller via flags or JSON spec files:

  - the deck title / audience / objective come from ``--title`` /
    ``--audience`` / ``--objective`` (passed straight through to
    ``init_deck_brief``);
  - the plan body comes from ``--plan-spec`` (a JSON file whose shape is
    exactly the ``deck_plan`` candidate);
  - the design system comes from EXACTLY ONE of ``--design-system-spec``
    (a ``design_system.json`` candidate) or ``--theme-from-template``
    (project palette / typography / grid from the template named in
    ``deck_plan.template`` resolved through ``--template-root``);
  - the slide bodies come from ``--slide-specs-dir`` (a directory of
    ``slide_plan`` JSON candidates);
  - the image manifest comes from ``--image-manifest-spec`` (an
    ``image_manifest`` JSON candidate);
  - asset bytes (optional) come from ``--assets-dir <dir>``. When
    supplied, the orchestrator inserts a deterministic copy step
    between Stage 5 (``init_slide_plans``) and Stage 6
    (``init_image_manifest``) that copies
    ``<assets-dir>/<local_path>`` bytes into
    ``<workspace>/<local_path>`` for every ``images[].local_path``
    declared in ``--image-manifest-spec``. Asset bytes are caller-
    supplied; the orchestrator does NOT generate, fetch, or otherwise
    invent them. Refuses symlinks at source and refuses to overwrite
    any pre-existing file at destination. The materialize step is the
    one stage whose writes the orchestrator unwinds on a downstream
    failure (defense in depth above each helper's per-stage rollback):
    if it succeeded but a later stage failed, every file + directory
    it created is removed so the workspace does not retain orphaned
    asset bytes from a failed prep run. A within-stage failure
    (missing source for image N, symlink at destination, copy error,
    ...) is rolled back by the materialize helper itself before it
    returns. Without ``--assets-dir`` the cascade runs the original
    six stages unchanged.

The orchestrator NEVER:

  - parses ``input/source.md`` for business content (Stage-2 through
    Stage-6 each delegate to the same Stage-1/Stage-2 bridge that reads
    the source bytes only for byte-level integrity checks and discards
    the decoded string);
  - invents ``deck_brief`` / ``deck_plan`` / ``design_system`` /
    ``slide_plans`` / ``image_manifest`` content;
  - generates any image asset, ``render_models/``, ``svg_previews/``,
    ``.pptx``, or pipeline report;
  - calls D-One, Qoder, any public network, image generation,
    telemetry, or external service;
  - modifies files outside ``--workspace``.

Fail-closed semantics: the first stage that returns a non-zero exit
code halts the orchestration; every downstream stage is marked SKIPPED
and is NOT run. Each Stage-1-through-6 init_* helper owns its own
rollback contract — the orchestrator does not roll back earlier-stage
artifacts when a later stage fails (the same as running the helpers
manually one at a time). The one exception is the optional
materialize_image_assets step (only present when ``--assets-dir`` is
supplied): it is an orchestration intermediate rather than a public
CLI helper, so the orchestrator additionally unwinds its writes when
ANY later stage fails — see the asset-bytes bullet above. A caller
who needs a clean retry should delete the workspace directory (or
fix the failing input and rerun from the failing stage manually).

Stdlib-only. Deterministic — every stage helper is deterministic, so
two runs from byte-identical inputs into two different empty
workspaces produce byte-identical artifacts inside each workspace.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

from init_workspace import init_workspace  # noqa: E402
from init_deck_brief import init_deck_brief  # noqa: E402
from init_deck_plan import init_deck_plan  # noqa: E402
from init_design_system import init_design_system  # noqa: E402
from init_slide_plans import init_slide_plans  # noqa: E402
from init_image_manifest import init_image_manifest  # noqa: E402
from validate_scaffold import local_path_is_safe, _resolves_within  # noqa: E402

_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _new_dirs_to_create(workspace: Path, dst: Path) -> list[Path]:
    """Return parents of ``dst`` inside ``workspace`` that do not yet
    exist on disk, top-down (closest-to-workspace first). Caller
    ``mkdir``s each entry in order; rollback removes them in reverse so
    children are unwound before parents.

    Stops at ``workspace`` so the workspace itself is never returned
    (workspace must already exist — ``init_workspace`` created it) and
    so a rollback cannot ``rmdir`` it."""
    to_create: list[Path] = []
    cur = dst.parent
    while cur != workspace and not cur.exists():
        to_create.insert(0, cur)
        next_parent = cur.parent
        if next_parent == cur:
            # Defensive: we've hit the filesystem root without finding
            # the workspace. Stop walking — this scenario should never
            # arise because dst is inside workspace by construction.
            break
        cur = next_parent
    return to_create


def _walk_for_symlinks(base: Path, rel_parts: tuple[str, ...]) -> Path | None:
    """Walk each component from ``base`` (exclusive) down through
    ``rel_parts`` (inclusive). Return the first symlink encountered,
    or ``None`` if no component on the path is a symlink. The caller
    must have already gated ``base`` itself with ``is_symlink``.

    Uses ``Path.is_symlink()`` per component without resolving — so a
    symlink at depth N is caught DIRECTLY rather than only indirectly
    via the resolved final-path containment check. This catches the
    case where ``<assets-dir>/<parent>`` is a symlink (e.g.
    ``<assets-dir>/media -> /tmp/outside``): the leaf
    ``<assets-dir>/media/<id>.png`` is not itself a symlink, so a
    leaf-only ``is_symlink()`` check would miss it. A non-existent
    component reports ``is_symlink()`` as False, so the walk
    tolerates missing leaves — the downstream ``is_file()`` check
    handles those."""
    cur = base
    for part in rel_parts:
        cur = cur / part
        if cur.is_symlink():
            return cur
    return None


def _undo_materialize_writes(
    paths: list[tuple[str, Path]],
) -> None:
    """Best-effort rollback of paths the materialize_image_assets step
    created (in reverse order so children are removed before parents).
    Files are ``unlink``-ed; directories are ``rmdir``-ed (succeeds only
    if empty, which is the invariant — we only ever ``mkdir`` dirs that
    did not exist before this run). Symlinks at either kind are skipped
    so a malicious mid-run swap cannot trick rollback into following
    them. ``OSError`` during rollback is swallowed so it cannot mask
    the original failure diagnostic."""
    for kind, p in reversed(paths):
        try:
            if kind == "file":
                if p.is_file() and not p.is_symlink():
                    p.unlink()
            elif kind == "dir":
                if p.is_dir() and not p.is_symlink():
                    p.rmdir()
        except OSError:
            pass


def _stage_image_assets(
    *,
    workspace: Path,
    image_manifest_spec: Path,
    assets_dir: Path,
    created_paths_out: list[tuple[str, Path]] | None = None,
) -> tuple[int, str]:
    """Copy caller-staged asset bytes from ``<assets_dir>/<local_path>``
    into ``<workspace>/<local_path>`` for every ``images[].local_path``
    declared in ``--image-manifest-spec``.

    Inserted between Stage 5 (``init_slide_plans``) and Stage 6
    (``init_image_manifest``) when ``--assets-dir`` is supplied: Stage 1
    (``init_workspace``) refuses a non-empty workspace, so asset bytes
    cannot be pre-positioned before Stage 1 fires; this prep step is the
    deterministic place where caller-supplied bytes are dropped into the
    workspace before ``init_image_manifest``'s ``local_path``-existence
    gate runs.

    Refuses symlinks at source, refuses to overwrite a pre-existing file
    at destination, applies ``local_path_is_safe`` + ``_resolves_within``
    to every declared ``local_path`` (defense in depth — the same gate
    ``init_image_manifest`` re-applies to the manifest it actually
    writes), creates any parent directories the destination needs.

    Rollback contract:

      - **Within-stage**: a mid-iteration failure (missing source for
        image N, symlink at destination, copy ``OSError``, ...) rolls
        back every file the helper has copied AND every parent
        directory it created so far in this call. On a non-zero return
        the workspace is byte-identical to its pre-call state.
      - **Cross-stage**: when the helper succeeds it appends every
        ``(kind, path)`` it created to ``created_paths_out`` (when
        supplied). The caller (``prepare_workspace``) walks that list
        in reverse and unwinds it if any later stage fails, so a
        failed prep run never leaves orphaned asset bytes in the
        workspace.

    Does NOT generate image bytes, call any network, invoke D-One /
    Qoder, or modify files outside ``--workspace``."""
    if _URI_SCHEME_PREFIX.match(str(assets_dir)):
        return 2, (
            f"FAIL: --assets-dir {assets_dir} looks like a URI; "
            f"prepare_workspace only accepts local directory paths"
        )
    if assets_dir.is_symlink():
        return 2, (
            f"FAIL: --assets-dir {assets_dir} is a symlink; refusing to "
            f"follow it. Pass a regular directory path."
        )
    if not assets_dir.is_dir():
        return 2, (
            f"FAIL: --assets-dir {assets_dir} is not a directory"
        )

    if image_manifest_spec.is_symlink():
        return 2, (
            f"FAIL: --image-manifest-spec {image_manifest_spec} is a "
            f"symlink; refusing to follow it."
        )
    if not image_manifest_spec.is_file():
        return 2, (
            f"FAIL: --image-manifest-spec {image_manifest_spec} is not "
            f"a regular file"
        )
    try:
        spec = json.loads(image_manifest_spec.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return 2, (
            f"FAIL: --image-manifest-spec {image_manifest_spec} did not "
            f"parse as JSON: {exc}"
        )
    if not isinstance(spec, dict):
        return 2, (
            f"FAIL: --image-manifest-spec {image_manifest_spec} did not "
            f"decode to an object (got {type(spec).__name__})"
        )
    images = spec.get("images") or []
    if not isinstance(images, list):
        return 2, (
            f"FAIL: --image-manifest-spec.images must be a list "
            f"(got {type(images).__name__})"
        )

    # Track every file + directory this call creates. On any failure
    # path below, we roll back this list in reverse before returning
    # rc != 0 so the workspace is byte-identical to its pre-call state.
    # On success, the caller (prepare_workspace) gets this list via
    # ``created_paths_out`` so it can unwind us if a later stage fails.
    local_created: list[tuple[str, Path]] = []

    for i, img in enumerate(images):
        if not isinstance(img, dict):
            _undo_materialize_writes(local_created)
            return 1, (
                f"FAIL: --image-manifest-spec.images[{i}] is not an "
                f"object (got {type(img).__name__})"
            )
        local_path = img.get("local_path")
        img_id = img.get("id")
        if not isinstance(local_path, str) or not local_path:
            _undo_materialize_writes(local_created)
            return 1, (
                f"FAIL: --image-manifest-spec.images[{i}] (id "
                f"{img_id!r}): local_path must be a non-empty string "
                f"(got {type(local_path).__name__})"
            )
        if not local_path_is_safe(local_path):
            _undo_materialize_writes(local_created)
            return 1, (
                f"FAIL: --image-manifest-spec.images[{i}] (id "
                f"{img_id!r}): local_path {local_path!r} is not a safe "
                f"workspace-relative path"
            )
        if not _resolves_within(workspace, local_path):
            _undo_materialize_writes(local_created)
            return 1, (
                f"FAIL: --image-manifest-spec.images[{i}] (id "
                f"{img_id!r}): local_path {local_path!r} escapes "
                f"--workspace after resolution"
            )
        src = assets_dir / local_path
        # Per-component symlink walk from assets_dir (already gated
        # above) down through every part of local_path INCLUDING the
        # leaf. A leaf-only ``src.is_symlink()`` check would miss the
        # case where a PARENT component inside assets_dir is a symlink
        # pointing outside (e.g. ``<assets-dir>/media -> /tmp/outside``)
        # — the leaf is not a symlink, only its parent is — so the
        # bytes copied would not actually live under --assets-dir.
        # Refuse any symlink at any depth.
        offender = _walk_for_symlinks(assets_dir, Path(local_path).parts)
        if offender is not None:
            try:
                target = str(offender.readlink())
            except OSError:
                target = "<unreadable>"
            _undo_materialize_writes(local_created)
            return 2, (
                f"FAIL: source asset path component {offender} is a "
                f"symlink (-> {target}); refusing to follow it"
            )
        # Belt-and-braces resolution check: after the per-component
        # walk passes, ``src.resolve()`` must still land under
        # ``assets_dir.resolve()``. Catches odd path shapes that
        # escape after ``Path.resolve()`` even when no component
        # looked like a symlink during the walk above.
        if not _resolves_within(assets_dir, local_path):
            _undo_materialize_writes(local_created)
            return 2, (
                f"FAIL: source asset {src} escapes --assets-dir "
                f"({assets_dir}) after resolution"
            )
        if not src.is_file():
            _undo_materialize_writes(local_created)
            return 2, (
                f"FAIL: source asset {src} for image id {img_id!r} is "
                f"missing or not a regular file"
            )
        dst = workspace / local_path
        if dst.is_symlink():
            _undo_materialize_writes(local_created)
            return 2, (
                f"FAIL: destination {dst} is a symlink; refusing to "
                f"follow it"
            )
        if dst.exists():
            _undo_materialize_writes(local_created)
            return 2, (
                f"FAIL: destination {dst} already exists; refusing to "
                f"overwrite"
            )
        # Materialize parent dirs THIS call creates so they can be
        # rolled back. Pre-existing dirs are untouched.
        new_dirs = _new_dirs_to_create(workspace, dst)
        try:
            for new_dir in new_dirs:
                new_dir.mkdir()
                local_created.append(("dir", new_dir))
        except OSError as exc:
            _undo_materialize_writes(local_created)
            return 2, (
                f"FAIL: creating parent directory for {dst} raised "
                f"{type(exc).__name__}: {exc}"
            )
        # Track the destination BEFORE attempting the copy so a copy
        # that raises mid-stream — after shutil.copy2 has already
        # opened dst for writing and possibly streamed bytes into it —
        # is still cleaned up. _undo_materialize_writes guards on
        # is_file() + not is_symlink(), so when copy2 raises before
        # creating dst (e.g. EACCES on open) the unlink is a no-op.
        local_created.append(("file", dst))
        try:
            shutil.copy2(src, dst)
        except OSError as exc:
            _undo_materialize_writes(local_created)
            return 2, (
                f"FAIL: copying {src} -> {dst} raised "
                f"{type(exc).__name__}: {exc}"
            )

    # Expose the created paths so the caller can unwind us on a later
    # stage failure (cross-stage rollback). On rc != 0 above we returned
    # before reaching here, so this only fires on full success.
    if created_paths_out is not None:
        created_paths_out.extend(local_created)

    copied_files = [p for kind, p in local_created if kind == "file"]
    return 0, (
        f"OK: staged {len(copied_files)} image asset(s) into "
        f"{workspace}: "
        f"{[p.relative_to(workspace).as_posix() for p in copied_files]}"
    )


# Artifacts the orchestrator promises a successful run leaves behind.
# Used by the self-test only; the orchestrator itself never inspects
# the workspace beyond delegating to each stage helper.
_STAGE_OUTPUT_FILES = (
    "input/source.md",
    "source_manifest.json",
    "deck_brief.json",
    "deck_plan.json",
    "design_system.json",
    "image_manifest.json",
)

_STAGE_NAMES = (
    "init_workspace",
    "init_deck_brief",
    "init_deck_plan",
    "init_design_system",
    "init_slide_plans",
    "init_image_manifest",
)


@dataclass
class StageOutcome:
    name: str
    skipped: bool
    exit_code: int
    message: str

    @property
    def ok(self) -> bool:
        return (not self.skipped) and self.exit_code == 0


@dataclass
class PrepareResult:
    workspace: Path
    stages: list[StageOutcome] = field(default_factory=list)

    @property
    def overall_ok(self) -> bool:
        return bool(self.stages) and all(s.ok for s in self.stages)

    @property
    def first_failure(self) -> StageOutcome | None:
        for s in self.stages:
            if not s.ok and not s.skipped:
                return s
        return None


def prepare_workspace(
    *,
    workspace: Path,
    source: Path,
    title: str,
    audience: str,
    objective: str,
    plan_spec: Path,
    slide_specs_dir: Path,
    image_manifest_spec: Path,
    template_root: Path,
    design_system_spec: Path | None = None,
    theme_from_template: bool = False,
    source_id: str | None = None,
    tone: str | None = None,
    language: str | None = None,
    approximate_slide_count: int | None = None,
    assets_dir: Path | None = None,
) -> PrepareResult:
    """Run stages 1-6 in order, halting on the first non-zero exit code.

    Returns a ``PrepareResult`` listing every stage that ran (with its
    rc and message) and every downstream stage that was skipped because
    an earlier stage failed.

    Mode-selection gate: exactly one of ``design_system_spec`` or
    ``theme_from_template`` must be supplied. The orchestrator does not
    silently pick a mode; ambiguous or empty mode arguments halt the
    run at Stage 4 (the design system helper's own gate) with a clear
    message.

    The helpers themselves own their rollback contracts. A failing
    stage rolls back its own writes; earlier-stage artifacts are
    preserved on disk so the caller can inspect them. The orchestrator
    does not delete earlier-stage artifacts on failure — it stops the
    cascade so no half-baked workspace is advanced into a later stage."""
    result = PrepareResult(workspace=workspace)

    # Stage list captured lazily so that downstream stages whose
    # arguments would otherwise raise (e.g. design_system_spec=None
    # passed to a strict signature) are never invoked once an earlier
    # stage has failed.
    stage_fns: list[tuple[str, Callable[[], tuple[int, str]]]] = [
        (
            "init_workspace",
            lambda: init_workspace(
                source=source,
                workspace=workspace,
                source_id=source_id,
            ),
        ),
        (
            "init_deck_brief",
            lambda: init_deck_brief(
                workspace=workspace,
                title=title,
                audience=audience,
                objective=objective,
                tone=tone,
                language=language,
                approximate_slide_count=approximate_slide_count,
            ),
        ),
        (
            "init_deck_plan",
            lambda: init_deck_plan(
                workspace=workspace,
                plan_spec=plan_spec,
            ),
        ),
        (
            "init_design_system",
            # init_design_system refuses --template-root unless
            # --theme-from-template is also supplied; route the path
            # only on the theme-mode branch so the --spec branch passes
            # template_root=None.
            lambda: init_design_system(
                workspace=workspace,
                spec=design_system_spec,
                theme_from_template=theme_from_template,
                template_root=template_root if theme_from_template else None,
            ),
        ),
        (
            "init_slide_plans",
            lambda: init_slide_plans(
                workspace=workspace,
                template_root=template_root,
                specs_dir=slide_specs_dir,
            ),
        ),
    ]

    # Optional asset-staging step: only present in the cascade when the
    # caller supplied --assets-dir. Sits between Stage 5 (init_slide_plans)
    # and Stage 6 (init_image_manifest) because init_workspace must have
    # already created the workspace tree, and init_image_manifest's
    # local_path-existence gate must run AFTER the bytes are on disk.
    #
    # ``materialize_paths`` collects every file + directory the helper
    # creates on a successful run, so we can unwind those writes if a
    # later stage (init_image_manifest) fails. Each init_* helper already
    # owns its own rollback contract, but the materialize step's outputs
    # are orchestration intermediates (no separate CLI helper writes
    # them) — leaving them on disk after a failed prep run would orphan
    # asset bytes the caller never asked to keep. The within-stage
    # rollback inside ``_stage_image_assets`` handles a failure inside
    # the materialize step itself; this list-based rollback handles a
    # failure in a later stage AFTER materialize succeeded.
    materialize_paths: list[tuple[str, Path]] = []

    if assets_dir is not None:
        stage_fns.append((
            "materialize_image_assets",
            lambda: _stage_image_assets(
                workspace=workspace,
                image_manifest_spec=image_manifest_spec,
                assets_dir=assets_dir,
                created_paths_out=materialize_paths,
            ),
        ))

    stage_fns.append((
        "init_image_manifest",
        lambda: init_image_manifest(
            workspace=workspace,
            spec=image_manifest_spec,
        ),
    ))

    failed_at: str | None = None
    for name, fn in stage_fns:
        if failed_at is not None:
            result.stages.append(StageOutcome(
                name=name,
                skipped=True,
                exit_code=-1,
                message=f"SKIPPED: prior stage {failed_at!r} failed",
            ))
            continue
        rc, msg = fn()
        result.stages.append(StageOutcome(
            name=name,
            skipped=False,
            exit_code=rc,
            message=msg,
        ))
        if rc != 0:
            failed_at = name

    # Cross-stage rollback for the materialize_image_assets step. If
    # materialize succeeded but a later stage failed, unwind the asset
    # bytes the helper wrote so the workspace does not retain orphaned
    # files from a failed prep run. When materialize itself fails it
    # already rolled back its own writes (within-stage), so
    # ``materialize_paths`` is empty in that case and this block is a
    # no-op. When the whole cascade succeeds we also skip the unwind so
    # the caller actually receives the materialized bytes.
    if failed_at is not None and materialize_paths:
        _undo_materialize_writes(materialize_paths)

    return result


def _format_result(result: PrepareResult) -> str:
    lines: list[str] = []
    for s in result.stages:
        if s.skipped:
            mark = "SKIP"
        elif s.ok:
            mark = "PASS"
        else:
            mark = "FAIL"
        lines.append(f"  [{mark}] {s.name} (rc={s.exit_code})")
    if result.overall_ok:
        lines.append(
            f"OK: prepared Stage-1-through-6 workspace at {result.workspace}. "
            f"scripts/run_pipeline.py can take over for stages 7-10."
        )
    else:
        fail = result.first_failure
        if fail is not None:
            lines.append(
                f"FAIL: stopped at {fail.name} (rc={fail.exit_code}).\n"
                f"--- {fail.name} message ---\n{fail.message}"
            )
        else:
            lines.append("FAIL: orchestration did not complete (no failure recorded).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs under tempfile.TemporaryDirectory()
# with synthetic fixtures written inline; no fixture leaks into the repo and
# no real source content is ever embedded in this script.
# ---------------------------------------------------------------------------


_MARKER_PHRASE = "FIXTURE-MARKER-7c2f6e91"

_FIXTURE_SOURCE = (
    "# Synthetic Fixture Source\n\n"
    f"{_MARKER_PHRASE}\n"
    "This synthetic body is the secret the orchestrator must never copy "
    "into any generated artifact beyond input/source.md. Stage 2 only "
    "takes --title / --audience / --objective from the CLI; Stage 3-6 "
    "each accept explicit --*-spec JSON files. None of the helpers ever "
    "read this file for business content.\n"
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _build_fixture(td: Path, *, source_id: str = "fixture_source") -> dict:
    """Create a minimal Stage-1-through-6 fixture under ``td``.

    Returns a kwargs dict ready for ``prepare_workspace(**fixture)``
    (excluding ``--workspace``, which the caller picks per scenario).

    The fixture targets the ``business_review`` template (the template
    the current repo ships) with two slides covering its simplest
    required slots: ``cover`` (title only) and ``key_message`` (a single
    callout message). Both slide_plan candidates therefore satisfy
    ``_slide_plan_against_layout``'s required-slot coverage gate.
    """
    td.mkdir(parents=True, exist_ok=True)
    source = td / "fixture_source.md"
    source.write_text(_FIXTURE_SOURCE)

    plan_spec = td / "plan_spec.json"
    _write_json(plan_spec, {
        "template": "business_review",
        "planning": {
            "planned_slide_count": 2,
            "rationale": (
                "Two-slide fixture exercising the orchestrator only — no "
                "business content."
            ),
        },
        "sections": [
            {
                "id": "intro",
                "title": "Intro",
                "summary": "Cover plus one body slide.",
                "slide_indices": [1, 2],
            },
        ],
        "slides": [
            {
                "index": 1,
                "layout": "cover",
                "title": "Fixture Cover Title",
                "section_id": "intro",
                "summary": "Cover slide.",
                "density": "low",
                "source_refs": [source_id],
            },
            {
                "index": 2,
                "layout": "key_message",
                "title": "Fixture Message",
                "section_id": "intro",
                "summary": "Single key-message slide.",
                "density": "low",
                "source_refs": [source_id],
            },
        ],
    })

    specs_dir = td / "specs"
    specs_dir.mkdir()
    _write_json(specs_dir / "01_cover.json", {
        "index": 1,
        "layout": "cover",
        "title": "Fixture Cover Title",
        "blocks": [
            {"id": "title", "kind": "text", "content": "Fixture Cover Title"},
        ],
    })
    _write_json(specs_dir / "02_key_message.json", {
        "index": 2,
        "layout": "key_message",
        "title": "Fixture Message",
        "blocks": [
            {
                "id": "message",
                "kind": "callout",
                "content": "Fixture key-message body.",
            },
        ],
    })

    image_manifest_spec = td / "image_manifest_spec.json"
    _write_json(image_manifest_spec, {"images": []})

    return {
        "source": source,
        "title": "Fixture Title",
        "audience": "Internal fixture audience",
        "objective": "Exercise the prepare_workspace orchestrator.",
        "plan_spec": plan_spec,
        "slide_specs_dir": specs_dir,
        "image_manifest_spec": image_manifest_spec,
        "template_root": REPO_ROOT / "templates" / "layouts",
        "design_system_spec": None,
        "theme_from_template": True,
        "source_id": source_id,
    }


def _expect(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


def _all_stage_files_present(workspace: Path) -> bool:
    for rel in _STAGE_OUTPUT_FILES:
        if not (workspace / rel).is_file():
            return False
    # Slide plans land under slide_plans/ with canonical filenames; we
    # check both fixture entries (deck_plan declares slides 1 and 2).
    if not (workspace / "slide_plans" / "01_cover.json").is_file():
        return False
    if not (workspace / "slide_plans" / "02_key_message.json").is_file():
        return False
    return True


def _read_artifact_text(workspace: Path) -> str:
    """Concatenate every stage-2-through-6 artifact's text (plus the
    source_manifest) so the marker-phrase test can scan in one sweep.
    The verbatim source copy at input/source.md is excluded by design —
    the marker is allowed there."""
    parts: list[str] = []
    for rel in (
        "source_manifest.json",
        "deck_brief.json",
        "deck_plan.json",
        "design_system.json",
        "image_manifest.json",
    ):
        p = workspace / rel
        if p.is_file():
            parts.append(p.read_text())
    for plan_file in sorted((workspace / "slide_plans").glob("*.json")):
        parts.append(plan_file.read_text())
    return "\n".join(parts)


def _run_self_tests() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    # 1. Happy path: every stage runs successfully and the workspace
    # carries Stage-1-through-6 artifacts.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        fixture = _build_fixture(td)
        ws = td / "happy_ws"
        result = prepare_workspace(workspace=ws, **fixture)
        ok = (
            result.overall_ok
            and _all_stage_files_present(ws)
            and len(result.stages) == len(_STAGE_NAMES)
            and all(s.name == n for s, n in zip(result.stages, _STAGE_NAMES))
        )
        results.append(_expect(
            "happy path: all six stages run, every Stage-1-through-6 "
            "artifact lands on disk, stage order matches the canonical "
            "init_workspace → init_image_manifest sequence",
            ok,
            f"overall_ok={result.overall_ok}, "
            f"files_present={_all_stage_files_present(ws)}, "
            f"stage_count={len(result.stages)}",
        ))

    # 2. Per-stage failure stops downstream stages. We force each stage
    # to fail with a minimal targeted-bad input and confirm every later
    # stage is marked SKIPPED.
    failure_cases = [
        (
            "init_workspace",
            # init_workspace rejects an empty source file.
            lambda td, fx: fx.__setitem__("source", _write_empty(td / "empty.md")),
        ),
        (
            "init_deck_brief",
            # init_deck_brief rejects an empty title.
            lambda td, fx: fx.__setitem__("title", ""),
        ),
        (
            "init_deck_plan",
            # init_deck_plan rejects a malformed plan_spec.
            lambda td, fx: fx.__setitem__(
                "plan_spec", _write_garbage(td / "bad_plan.json")
            ),
        ),
        (
            "init_design_system",
            # init_design_system refuses both modes simultaneously
            # (--spec + --theme-from-template). Switching from
            # theme_from_template=True to also pass a design_system_spec
            # forces the mode-selection gate to fire.
            lambda td, fx: fx.update({
                "design_system_spec": _write_garbage(td / "bad_ds.json"),
                "theme_from_template": True,
            }),
        ),
        (
            "init_slide_plans",
            # init_slide_plans rejects a non-existent specs directory.
            lambda td, fx: fx.__setitem__(
                "slide_specs_dir", td / "missing_specs",
            ),
        ),
        (
            "init_image_manifest",
            # init_image_manifest rejects a malformed spec.
            lambda td, fx: fx.__setitem__(
                "image_manifest_spec", _write_garbage(td / "bad_img.json"),
            ),
        ),
    ]
    for stage_name, mutator in failure_cases:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            fixture = _build_fixture(td)
            mutator(td, fixture)
            ws = td / f"fail_at_{stage_name}_ws"
            result = prepare_workspace(workspace=ws, **fixture)

            # Identify the index of the failing stage in canonical order.
            stage_index = _STAGE_NAMES.index(stage_name)
            ok = (
                not result.overall_ok
                and result.first_failure is not None
                and result.first_failure.name == stage_name
            )
            # Every stage at or before stage_index should have RUN
            # (skipped=False); the failing stage's exit_code must be
            # non-zero. Every stage AFTER stage_index must be SKIPPED.
            for i, outcome in enumerate(result.stages):
                if i < stage_index:
                    if outcome.skipped or outcome.exit_code != 0:
                        ok = False
                elif i == stage_index:
                    if outcome.skipped or outcome.exit_code == 0:
                        ok = False
                else:
                    if not outcome.skipped:
                        ok = False
            results.append(_expect(
                f"per-stage failure: {stage_name} fails -> every later "
                f"stage is SKIPPED, no half-baked workspace advances",
                ok,
                f"first_failure={result.first_failure.name if result.first_failure else None}, "
                f"stages={[(s.name, s.skipped, s.exit_code) for s in result.stages]}",
            ))

    # 3. Pre-existing unsafe workspace: a symlink at --workspace is
    # refused by init_workspace itself; the orchestrator inherits the
    # gate and never advances past Stage 1.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        fixture = _build_fixture(td)
        real_dir = td / "real_target"
        real_dir.mkdir()
        ws_sym = td / "ws_sym"
        ws_sym.symlink_to(real_dir)
        result = prepare_workspace(workspace=ws_sym, **fixture)
        ok = (
            not result.overall_ok
            and result.first_failure is not None
            and result.first_failure.name == "init_workspace"
            and "symlink" in result.first_failure.message
            # Confirm no artifacts leaked into the symlink target.
            and not (real_dir / "source_manifest.json").exists()
            and not (real_dir / "deck_brief.json").exists()
        )
        results.append(_expect(
            "pre-existing unsafe workspace (symlink) is refused at Stage 1; "
            "symlink target directory is untouched and every downstream "
            "stage is SKIPPED",
            ok,
            f"first_failure={result.first_failure.name if result.first_failure else None}",
        ))

    # 4. Pre-existing non-empty workspace: init_workspace refuses it.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        fixture = _build_fixture(td)
        ws = td / "ws_preexist"
        ws.mkdir()
        (ws / "pre.txt").write_text("prior content")
        result = prepare_workspace(workspace=ws, **fixture)
        ok = (
            not result.overall_ok
            and result.first_failure is not None
            and result.first_failure.name == "init_workspace"
            and (ws / "pre.txt").read_text() == "prior content"
            and not (ws / "deck_brief.json").exists()
        )
        results.append(_expect(
            "pre-existing non-empty workspace is refused at Stage 1; "
            "prior contents preserved byte-identical",
            ok,
            f"first_failure={result.first_failure.name if result.first_failure else None}",
        ))

    # 5. Marker-phrase test: the source body must never appear in any
    # generated artifact except the verbatim copy at input/source.md.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        fixture = _build_fixture(td)
        ws = td / "marker_ws"
        result = prepare_workspace(workspace=ws, **fixture)
        if not result.overall_ok:
            results.append(_expect(
                "marker-phrase test: orchestrator completed all stages "
                "before scanning artifacts",
                False,
                f"orchestration failed: {result.first_failure.message if result.first_failure else 'unknown'}",
            ))
        else:
            source_copy = (ws / "input" / "source.md").read_text()
            artifact_text = _read_artifact_text(ws)
            ok = (
                _MARKER_PHRASE in source_copy
                and _MARKER_PHRASE not in artifact_text
            )
            results.append(_expect(
                "marker phrase appears in input/source.md only — never "
                "copied into source_manifest / deck_brief / deck_plan / "
                "design_system / slide_plans / image_manifest",
                ok,
                f"in_source={_MARKER_PHRASE in source_copy}, "
                f"in_artifacts={_MARKER_PHRASE in artifact_text}",
            ))

    # 6. Determinism: two independent happy-path runs into different
    # empty workspaces produce byte-identical artifacts (each stage
    # helper is deterministic, so the orchestrator is too).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        # Build two fixture dirs whose inputs are byte-identical
        # despite living at different absolute paths. Each stage
        # helper reads the JSON body, never the input file's absolute
        # path, so two runs from byte-identical INPUTS into two
        # different empty workspaces should produce byte-identical
        # OUTPUTS.
        fixture_a = _build_fixture(td / "fixture_a_dir")
        fixture_b = _build_fixture(td / "fixture_b_dir")
        ws_a = td / "det_a"
        ws_b = td / "det_b"
        result_a = prepare_workspace(workspace=ws_a, **fixture_a)
        result_b = prepare_workspace(workspace=ws_b, **fixture_b)
        ok = result_a.overall_ok and result_b.overall_ok
        diffs: list[str] = []
        if ok:
            compared = list(_STAGE_OUTPUT_FILES) + [
                "slide_plans/01_cover.json",
                "slide_plans/02_key_message.json",
            ]
            for rel in compared:
                a_bytes = (ws_a / rel).read_bytes()
                b_bytes = (ws_b / rel).read_bytes()
                if a_bytes != b_bytes:
                    diffs.append(rel)
                    ok = False
        results.append(_expect(
            "determinism: two independent happy-path runs from "
            "byte-identical inputs produce byte-identical artifacts in "
            "every Stage-1-through-6 file (input/source.md, source_manifest, "
            "deck_brief, deck_plan, design_system, slide_plans, "
            "image_manifest)",
            ok,
            f"diffs={diffs}, a_ok={result_a.overall_ok}, b_ok={result_b.overall_ok}",
        ))

    # 7. Run_pipeline.py can consume the resulting workspace: validate
    # via the same workspace gate run_pipeline uses up front. We do not
    # call run_pipeline itself (it would generate render_models / SVG /
    # PPTX, which the orchestrator is intentionally NOT in scope for) —
    # we only confirm that validate_workspace.py against our prepared
    # workspace passes, which is exactly the gate run_pipeline applies.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        fixture = _build_fixture(td)
        ws = td / "validate_ws"
        result = prepare_workspace(workspace=ws, **fixture)
        if not result.overall_ok:
            results.append(_expect(
                "prepared workspace passes validate_workspace.py "
                "(the gate run_pipeline.py applies up front)",
                False,
                f"orchestration failed: {result.first_failure.message if result.first_failure else 'unknown'}",
            ))
        else:
            import subprocess
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "validate_workspace.py"),
                    "--workspace", str(ws),
                    "--template-root", str(REPO_ROOT / "templates" / "layouts"),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            ok = proc.returncode == 0
            results.append(_expect(
                "prepared workspace passes validate_workspace.py against "
                "the business_review template (the gate run_pipeline.py "
                "applies up front)",
                ok,
                f"rc={proc.returncode}, stderr_tail={proc.stderr.strip().splitlines()[-3:] if proc.stderr.strip() else []}",
            ))

    # 8. Copy-failure rollback. shutil.copy2 may have opened dst for
    # writing and streamed bytes into it before raising. The materialize
    # step's local_created list adds dst BEFORE the copy attempt so the
    # rollback removes any partial file. Monkey-patch shutil.copy2 to
    # simulate a mid-stream failure (write partial bytes, then raise)
    # and verify the partial file does NOT survive the rollback.
    original_copy2 = shutil.copy2

    def _broken_copy2(src, dst, *args, **kwargs):
        Path(dst).write_bytes(b"PARTIAL_FROM_FAILED_COPY")
        raise OSError(28, "simulated mid-stream copy failure")

    shutil.copy2 = _broken_copy2  # type: ignore[assignment]
    try:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            fixture = _build_fixture(td / "fx_partial_copy")
            # Add one image to the manifest spec so materialize has
            # work to do. (Slide plans don't reference it; that's
            # allowed by init_image_manifest — declared images may go
            # un-referenced.)
            _write_json(fixture["image_manifest_spec"], {
                "images": [
                    {
                        "id": "partial_test_img",
                        "local_path": "media/partial_test_img.png",
                        "source": "d_one_local",
                        "alt_text": "Synthetic test image.",
                        "intended_use": "spot illustration",
                    },
                ],
            })
            # Stage a source for the (patched, broken) copy to read.
            assets_dir = td / "partial_assets"
            (assets_dir / "media").mkdir(parents=True)
            (assets_dir / "media" / "partial_test_img.png").write_bytes(
                b"PNG_SOURCE_BYTES"
            )
            ws = td / "ws_partial"
            result = prepare_workspace(
                workspace=ws,
                assets_dir=assets_dir,
                **fixture,
            )
            partial_dst = ws / "media" / "partial_test_img.png"
            media_dir = ws / "media"
            materialize_outcome = next(
                (s for s in result.stages
                 if s.name == "materialize_image_assets"),
                None,
            )
            ok = (
                materialize_outcome is not None
                and not materialize_outcome.ok
                and "simulated mid-stream" in materialize_outcome.message
                and not partial_dst.exists()
                and not media_dir.exists()
                and result.first_failure is not None
                and result.first_failure.name == "materialize_image_assets"
            )
            results.append(_expect(
                "copy-failure rollback: shutil.copy2 raising after "
                "partially writing dst triggers rollback of the partial "
                "file AND the parent dir the materialize step created; "
                "no orphaned bytes remain in the workspace",
                ok,
                (f"materialize_msg={materialize_outcome.message if materialize_outcome else None}, "
                 f"partial_dst_left={partial_dst.exists()}, "
                 f"media_dir_left={media_dir.exists()}, "
                 f"first_failure={result.first_failure.name if result.first_failure else None}"
                 if not ok else ""),
            ))
    finally:
        shutil.copy2 = original_copy2  # type: ignore[assignment]

    # 9. Symlinked-parent containment. When a PARENT component inside
    # --assets-dir is a symlink pointing OUTSIDE the assets directory
    # (e.g. <assets-dir>/media -> /tmp/outside), the materialize step
    # must refuse before reading any bytes. We stage a regular file at
    # the symlink target so the leaf would otherwise be readable —
    # only the per-component symlink walk gates the run. The outside
    # payload must never land in the workspace.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        fixture = _build_fixture(td / "fx_symlinked_parent")
        _write_json(fixture["image_manifest_spec"], {
            "images": [
                {
                    "id": "symlinked_parent_img",
                    "local_path": "media/symlinked_parent_img.png",
                    "source": "d_one_local",
                    "alt_text": "Synthetic test image.",
                    "intended_use": "spot illustration",
                },
            ],
        })
        outside = td / "outside_target"
        outside.mkdir()
        outside_payload = b"OUTSIDE_PAYLOAD_MUST_NOT_BE_COPIED"
        (outside / "symlinked_parent_img.png").write_bytes(outside_payload)
        assets_dir = td / "assets_with_symlinked_parent"
        assets_dir.mkdir()
        # <assets-dir>/media -> /tmp/.../outside_target. The leaf
        # <assets-dir>/media/symlinked_parent_img.png is NOT itself a
        # symlink — only its parent "media" is. A leaf-only
        # is_symlink() check would miss this case; the per-component
        # walk must catch it.
        (assets_dir / "media").symlink_to(outside)
        ws = td / "ws_symlinked_parent"
        result = prepare_workspace(
            workspace=ws,
            assets_dir=assets_dir,
            **fixture,
        )
        materialize_outcome = next(
            (s for s in result.stages
             if s.name == "materialize_image_assets"),
            None,
        )
        dst = ws / "media" / "symlinked_parent_img.png"
        media_dir = ws / "media"
        # After the refusal, no bytes from the outside payload may
        # appear anywhere in the workspace, and the workspace's
        # media/ directory must not exist (the materialize step is
        # the only thing that could have created it).
        outside_payload_in_ws = False
        if ws.exists():
            for p in ws.rglob("*"):
                if p.is_file() and not p.is_symlink():
                    try:
                        if outside_payload in p.read_bytes():
                            outside_payload_in_ws = True
                            break
                    except OSError:
                        pass
        ok = (
            materialize_outcome is not None
            and not materialize_outcome.ok
            and "symlink" in materialize_outcome.message.lower()
            and not dst.exists()
            and not media_dir.exists()
            and not outside_payload_in_ws
            and result.first_failure is not None
            and result.first_failure.name == "materialize_image_assets"
        )
        results.append(_expect(
            "symlinked-parent containment: <assets-dir>/media -> "
            "/tmp/outside is refused before any bytes are read; the "
            "outside payload never lands in the workspace; "
            "init_image_manifest is SKIPPED",
            ok,
            (f"materialize_msg={materialize_outcome.message if materialize_outcome else None}, "
             f"dst_exists={dst.exists()}, "
             f"media_dir_exists={media_dir.exists()}, "
             f"outside_payload_in_ws={outside_payload_in_ws}, "
             f"first_failure={result.first_failure.name if result.first_failure else None}"
             if not ok else ""),
        ))

    return results


def _write_empty(path: Path) -> Path:
    path.write_bytes(b"")
    return path


def _write_garbage(path: Path) -> Path:
    path.write_text("this is not valid JSON {{{")
    return path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage-1-to-6 local orchestration helper. Chains "
            "scripts/init_workspace.py through scripts/init_image_manifest.py "
            "from explicit caller-supplied inputs into a workspace that "
            "scripts/run_pipeline.py can later consume. Orchestration only "
            "— does not plan a deck, does not extract source content, does "
            "not generate render_models / SVG / PPTX / reports, and does "
            "not call any public network or external service."
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Workspace directory to create. Same gate as "
             "scripts/init_workspace.py (no symlinks, must be empty if it "
             "exists, no URI scheme, outside the repo / fs root / $HOME / "
             "system trees).",
    )
    parser.add_argument(
        "--source", type=Path, default=None,
        help="Local .md or .txt source file (forwarded to init_workspace).",
    )
    parser.add_argument(
        "--source-id", type=str, default=None,
        help="Opaque source identifier the orchestrator passes to "
             "init_workspace. Defaults to the --source filename stem.",
    )
    parser.add_argument(
        "--title", type=str, default=None,
        help="Deck title forwarded to init_deck_brief.",
    )
    parser.add_argument(
        "--audience", type=str, default=None,
        help="Audience forwarded to init_deck_brief.",
    )
    parser.add_argument(
        "--objective", type=str, default=None,
        help="Deck objective forwarded to init_deck_brief.",
    )
    parser.add_argument(
        "--tone", type=str, default=None,
        help="Optional tone forwarded to init_deck_brief.",
    )
    parser.add_argument(
        "--language", type=str, default=None,
        help="Optional language forwarded to init_deck_brief.",
    )
    parser.add_argument(
        "--approximate-slide-count", type=int, default=None,
        help="Optional planning hint forwarded to init_deck_brief.",
    )
    parser.add_argument(
        "--plan-spec", type=Path, default=None,
        help="Deck-plan JSON candidate forwarded to init_deck_plan.",
    )
    parser.add_argument(
        "--design-system-spec", type=Path, default=None,
        help="Design-system JSON candidate forwarded to "
             "init_design_system. Mutually exclusive with "
             "--theme-from-template.",
    )
    parser.add_argument(
        "--theme-from-template", action="store_true",
        help="Project palette / typography / grid from the theme of "
             "deck_plan.template (resolved against --template-root). "
             "Mutually exclusive with --design-system-spec.",
    )
    parser.add_argument(
        "--template-root", type=Path, default=None,
        help="Template root directory (e.g. templates/layouts/). Required "
             "by init_slide_plans, and additionally by init_design_system "
             "in --theme-from-template mode.",
    )
    parser.add_argument(
        "--slide-specs-dir", type=Path, default=None,
        help="Directory of slide_plan JSON candidates forwarded to "
             "init_slide_plans.",
    )
    parser.add_argument(
        "--image-manifest-spec", type=Path, default=None,
        help="Image-manifest JSON candidate forwarded to "
             "init_image_manifest.",
    )
    parser.add_argument(
        "--assets-dir", type=Path, default=None,
        help="Optional directory of caller-staged image asset bytes "
             "keyed by the relative paths declared in "
             "--image-manifest-spec's images[].local_path. When passed, "
             "the orchestrator inserts a materialize_image_assets step "
             "between init_slide_plans (Stage 5) and init_image_manifest "
             "(Stage 6) that copies <assets-dir>/<local_path> bytes into "
             "<workspace>/<local_path> before init_image_manifest's "
             "local_path-existence gate runs. Refuses symlinks at source, "
             "refuses to overwrite at destination, generates nothing.",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios (happy path through "
             "Stage 6, per-stage failure short-circuits downstream "
             "stages, pre-existing unsafe workspace refused, pre-existing "
             "non-empty workspace refused, source-body marker phrase "
             "never copied beyond input/source.md, deterministic repeat "
             "runs produce byte-identical artifacts, prepared workspace "
             "passes validate_workspace.py, copy-failure rollback: "
             "shutil.copy2 raising after partially writing dst removes "
             "the partial file + parent dir so no orphaned bytes "
             "remain, and symlinked-parent containment: a parent "
             "component inside --assets-dir that is a symlink pointing "
             "outside the assets directory is refused before any bytes "
             "are read, so an outside payload at the resolved target "
             "never lands in the workspace). Exits non-zero if any "
             "scenario does not behave as expected. Mutually exclusive "
             "with the orchestration flags.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        orchestration_args = (
            args.workspace, args.source, args.source_id,
            args.title, args.audience, args.objective,
            args.tone, args.language, args.approximate_slide_count,
            args.plan_spec, args.design_system_spec,
            args.template_root, args.slide_specs_dir,
            args.image_manifest_spec, args.assets_dir,
        )
        if any(v is not None for v in orchestration_args) or args.theme_from_template:
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
            print(f"FAIL: {fails} self-test scenario(s) did not behave as expected.")
            return 1
        print(
            "OK (self-test): every orchestration short-circuit fires "
            "correctly and the happy-path workspace is prepared through "
            "Stage 6 from explicit caller-supplied inputs."
        )
        return 0

    missing = [
        name for name, value in (
            ("--workspace", args.workspace),
            ("--source", args.source),
            ("--title", args.title),
            ("--audience", args.audience),
            ("--objective", args.objective),
            ("--plan-spec", args.plan_spec),
            ("--slide-specs-dir", args.slide_specs_dir),
            ("--image-manifest-spec", args.image_manifest_spec),
            ("--template-root", args.template_root),
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

    # Mode-selection gate: exactly one of --design-system-spec /
    # --theme-from-template must be supplied. init_design_system would
    # also catch this at Stage 4, but surfacing the failure up-front
    # gives a clearer error before Stage 1 runs.
    if args.design_system_spec is None and not args.theme_from_template:
        print(
            "FAIL: must pass either --design-system-spec <path> or "
            "--theme-from-template (with --template-root <dir>)",
            file=sys.stderr,
        )
        return 2
    if args.design_system_spec is not None and args.theme_from_template:
        print(
            "FAIL: --design-system-spec and --theme-from-template are "
            "mutually exclusive; pick exactly one design-system input",
            file=sys.stderr,
        )
        return 2

    result = prepare_workspace(
        workspace=args.workspace,
        source=args.source,
        title=args.title,
        audience=args.audience,
        objective=args.objective,
        plan_spec=args.plan_spec,
        slide_specs_dir=args.slide_specs_dir,
        image_manifest_spec=args.image_manifest_spec,
        template_root=args.template_root,
        design_system_spec=args.design_system_spec,
        theme_from_template=args.theme_from_template,
        source_id=args.source_id,
        tone=args.tone,
        language=args.language,
        approximate_slide_count=args.approximate_slide_count,
        assets_dir=args.assets_dir,
    )

    text = _format_result(result)
    if result.overall_ok:
        print(text)
        return 0
    print(text, file=sys.stderr)
    fail = result.first_failure
    return fail.exit_code if fail is not None else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
