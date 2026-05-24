#!/usr/bin/env python3
"""Mock D-One image-to-editable-PPT runner (LOCAL, STUB, NOT real D-One).

Packages the existing local mock image chain into a single explicit-input
command:

  1. seed a temporary staging workspace via ``scripts/init_workspace.py``
     and hand-write the d_one_local ``image_manifest.json`` from the
     caller-supplied ``--image-manifest-spec`` (the direct-author workflow
     documented at ``scripts/materialize_image_assets.py``);
  2. ``scripts/done_image_adapter.py --workspace <staging> --spec
     <d-one-spec> [--descriptor-vocabulary <vocab>]`` — writes the
     deterministic ``<staging>/d_one_adapter_plan.json``;
  3. ``scripts/run_d_one_generation.py --workspace <staging> --assets-dir
     <staging-assets> --allow-synthetic-bytes [--descriptor-vocabulary
     <vocab>]`` — emits a fixed minimal PNG / JPEG payload per declared
     extension into the staging assets directory; NEVER calls D-One /
     MCP / a public network / any model API / image search / Qoder /
     telemetry / any external service;
  4. ``scripts/materialize_image_assets.py --workspace <staging>
     --assets-dir <staging-assets>`` — copies the synthetic bytes to
     ``<staging>/<local_path>`` for every declared d_one_local image;
  5. ``scripts/run_explicit_pipeline.py --assets-dir <staging>`` against
     the caller's production workspace + bundle. The staging workspace
     carries the materialized bytes at ``<staging>/<local_path>``, so
     ``prepare_workspace.py``'s materialize_image_assets step inside the
     orchestrator copies those bytes into the production workspace
     between Stage 5 (init_slide_plans) and Stage 6 (init_image_manifest)
     and the cascade completes Stages 1-10.

This is an **explicit-input runner**, NOT prompt-to-PPTX automation. The
runner does not read ``input/source.md`` for content, does not invent
any spec / plan / slide body, does not generate any real image bytes,
and does not call any network. ``--allow-synthetic-bytes`` is the
explicit dry-run gate; omitting it fails closed rather than implying a
real-D-One / provider mode that does not exist in this repo today.

Taxonomy contract preservation: when the ``--d-one-spec`` carries any
of the seven taxonomy fields (``rendering_style`` / ``palette_family``
/ ``image_role`` / ``layout_pattern`` / ``modifier`` / ``text_policy``
/ ``subject_domain``) OR the optional ``custom_descriptor`` escape-hatch
field OR the optional ``placement_role`` field (closed enumeration
``hero_page`` / ``local_region``), the runner requires
``--descriptor-vocabulary``, forwards it to BOTH ``done_image_adapter``
and ``run_d_one_generation``, and — before invoking
``run_explicit_pipeline.py`` — re-parses the produced
``<staging>/d_one_adapter_plan.json`` and asserts:

  * ``schema_version == 4`` (the value the plan schema's enum locks);
  * every taxonomy field / value supplied on the spec request appears
    byte-identical on the corresponding plan request (no value drift,
    no silent re-ordering, no field dropped);
  * the ``custom_descriptor`` value, when supplied on the spec request,
    appears byte-identical on the corresponding plan request;
  * the ``placement_role`` value, when supplied on the spec request,
    appears byte-identical on the corresponding plan request.

A taxonomy- OR custom_descriptor- OR placement_role-bearing spec
without ``--descriptor-vocabulary`` is refused at the runner boundary
BEFORE any subprocess fires.

Output behavior:

  * writes the production workspace at ``--workspace`` (created by
    ``init_workspace.py`` inside ``run_explicit_pipeline.py``);
  * writes the ``.pptx`` at ``--output``;
  * writes ``pipeline_report.{json,txt}`` and ``inventory.json`` under
    ``--report-dir`` when supplied;
  * uses ``tempfile.TemporaryDirectory()`` for the staging workspace +
    staging assets directory — both are removed when the runner returns;
  * writes nothing under the repo, nothing under ``examples/`` /
    ``scripts/`` / any committed directory.

Fail-closed safety gates (every gate aborts the run; the subprocess
chain is short-circuited and any partially-produced staging bytes go
away with the ``tempfile.TemporaryDirectory()``):

  --allow-synthetic-bytes
    MUST be supplied. Omitting it is the explicit gate against silently
    implying a real-D-One / provider mode this repo does not support.

  --d-one-spec
    must be an existing regular non-symlink JSON file; URI-shaped values
    refused. Taxonomy-bearing requests force --descriptor-vocabulary.

  --descriptor-vocabulary
    optional; required iff the spec carries any taxonomy field. When
    supplied, must be an existing regular non-symlink JSON file;
    URI-shaped values refused.

  --workspace / --output / --report-dir
    URI-shaped values refused at the runner boundary; symlinks (broken
    or resolvable) at the named path refused; everything else is
    deferred to ``run_explicit_pipeline.py`` / ``run_pipeline.py``,
    which apply the canonical inside-workspace / extension / pre-
    existing-non-regular-file / parent-symlink gates.

  --image-manifest-spec
    must be an existing regular non-symlink JSON file that decodes to
    an object with a non-empty ``images`` list; every entry must be
    ``source == "d_one_local"`` (the runner only knows how to drive the
    d_one_local chain — local_asset / synthetic entries belong to a
    different lifecycle and would never get synthetic bytes generated).

Stdlib-only. The runner itself is small — it shells out to the existing
chain steps so their own argparse + fail-closed gates + stdout/stderr
cascade are exercised verbatim, no logic is duplicated.
"""
from __future__ import annotations

import sys

# Refuse to write `.pyc` files for any module imported by this runner.
# The runner's contract says it writes only the requested
# workspace/output/report paths plus staging under
# tempfile.TemporaryDirectory(); without this gate the first-party
# import below (validate_scaffold) silently lands
# `scripts/__pycache__/validate_scaffold.cpython-*.pyc` on a clean
# checkout, violating the no-generated-repo-artifacts contract.
# ``PYTHONDONTWRITEBYTECODE=1`` in the env achieves the same thing for
# callers that remember the prefix, but the in-script flip closes the
# hole unconditionally. Must come BEFORE any first-party import — the
# interpreter checks the flag at bytecode-write time.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
TEMPLATE_ROOT = REPO_ROOT / "templates" / "layouts"

sys.path.insert(0, str(SCRIPTS_DIR))

from validate_scaffold import _URI_SCHEME_PREFIX  # noqa: E402

# Mirror the seven dimensions the descriptor-vocabulary schema locks.
# Any spec request carrying one or more of these fields forces
# --descriptor-vocabulary to have been supplied AND the value must be a
# member of the matching image_taxonomy.<dim>.allowed_values list. The
# tuple order is the spec/plan field order in the on-disk artifact
# (deterministic projection matters because the plan file is reread
# byte-for-byte across runs).
TAXONOMY_FIELDS: tuple[str, ...] = (
    "rendering_style",
    "palette_family",
    "image_role",
    "layout_pattern",
    "modifier",
    "text_policy",
    "subject_domain",
)

# Optional custom-descriptor escape-hatch field. Same vocab-required
# semantic as the taxonomy fields — present => --descriptor-vocabulary
# is required AND the adapter refuses any value not in the vocab's
# custom_descriptors[] allow-list.
CUSTOM_DESCRIPTOR_FIELD = "custom_descriptor"

# Optional placement_role field. Same vocab-required semantic as the
# taxonomy fields — present => --descriptor-vocabulary is required AND
# the adapter refuses any value not in the vocab's
# image_taxonomy.placement_role.allowed_values list (closed two-token
# enumeration ``hero_page`` / ``local_region``).
PLACEMENT_ROLE_FIELD = "placement_role"

# Vocab-gated request fields: TAXONOMY_FIELDS + CUSTOM_DESCRIPTOR_FIELD
# + PLACEMENT_ROLE_FIELD. Used by the runner-boundary check that
# refuses a vocab-bearing spec without --descriptor-vocabulary BEFORE
# any subprocess fires.
VOCAB_GATED_FIELDS: tuple[str, ...] = (
    *TAXONOMY_FIELDS,
    CUSTOM_DESCRIPTOR_FIELD,
    PLACEMENT_ROLE_FIELD,
)

# Locked plan-file schema version. The 1 -> 2 bump was the paired
# change for the optional per-request taxonomy fields. The 2 -> 3 bump
# was the paired change for the optional per-request custom_descriptor
# escape-hatch field. The 3 -> 4 bump is the paired change for the
# optional per-request placement_role field. An older reader with
# schema_version=3 would reject the new property under the per-request
# additionalProperties: false lock, so the shape change is not
# backward-compatible and gets a new version. The runner re-asserts
# this value AFTER done_image_adapter writes the plan AND BEFORE
# run_explicit_pipeline is invoked, so a regression that downgrades
# the plan shape is caught even if the plan validator itself drifts.
LOCKED_PLAN_SCHEMA_VERSION = 4

# Embed surface scripts/export_pptx.py supports today. The self-test
# walks `ppt/media/` looking for any of these extensions; finding none
# means the mock D-One bytes never made it into the package as media.
_EMBEDDABLE_MEDIA_EXTS: tuple[str, ...] = (".png", ".jpg", ".jpeg")


# ---------------------------------------------------------------------------
# Helpers shared with main() and the self-test.
# ---------------------------------------------------------------------------


def _has_uri_scheme(s: str) -> bool:
    return bool(_URI_SCHEME_PREFIX.match(s))


def _refuse_symlink(path: Path, label: str) -> tuple[bool, str]:
    """Refuse both broken and resolvable symlinks (same anti-pattern as
    the other helpers — ``Path.exists()`` returns False for a dangling
    link and ``is_file()`` / ``is_dir()`` follow links, so an explicit
    ``is_symlink()`` check is the only way to reject both shapes)."""
    if not path.is_symlink():
        return False, ""
    try:
        target = str(path.readlink())
    except OSError:
        target = "<unreadable>"
    return True, (
        f"FAIL: {path} ({label}) is a symlink (-> {target}); "
        f"run_mock_image_pipeline refuses to follow it (broken or not)."
    )


def _gate_uri_and_symlink(path: Path, label: str) -> tuple[int, str]:
    """Return (rc, msg). rc == 0 means the path passed both gates."""
    if _has_uri_scheme(str(path)):
        return 2, (
            f"FAIL: {label} {path} looks like a URI; "
            f"run_mock_image_pipeline only accepts local file paths."
        )
    is_symlink, msg = _refuse_symlink(path, label)
    if is_symlink:
        return 2, msg
    return 0, ""


def _load_json_object(path: Path, label: str) -> tuple[dict | None, str]:
    """Return (doc, msg). ``doc`` is None when ``msg`` is non-empty."""
    rc, msg = _gate_uri_and_symlink(path, label)
    if rc != 0:
        return None, msg
    if not path.exists():
        return None, f"FAIL: {label} {path} does not exist."
    if not path.is_file():
        return None, f"FAIL: {label} {path} is not a regular file."
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return None, (
            f"FAIL: cannot read {label} {path}: "
            f"{type(exc).__name__}: {exc}"
        )
    if not isinstance(doc, dict):
        return None, (
            f"FAIL: {label} {path} did not decode to a JSON object "
            f"(got {type(doc).__name__})."
        )
    return doc, ""


def _spec_taxonomy_fields_used(spec_doc: dict) -> set[str]:
    """Return the set of vocab-gated field names (taxonomy fields plus
    the ``custom_descriptor`` escape hatch) appearing on any request in
    ``spec_doc``. Empty set means none used — vocabulary is not
    required. The runner uses this BEFORE shelling out to gate
    --descriptor-vocabulary at the runner boundary so the failure
    diagnostic is the runner's own (clear context: "your spec uses
    taxonomy / custom_descriptor, pass --descriptor-vocabulary")
    rather than the chained diagnostic emitted by done_image_adapter."""
    requests = spec_doc.get("requests")
    if not isinstance(requests, list):
        return set()
    seen: set[str] = set()
    for req in requests:
        if not isinstance(req, dict):
            continue
        for f in VOCAB_GATED_FIELDS:
            if f in req:
                seen.add(f)
    return seen


def _image_manifest_is_d_one_local(spec_doc: dict) -> tuple[bool, str]:
    """The runner only drives the d_one_local chain — refuse a manifest
    that mixes local_asset / synthetic entries. The same gate is
    applied (per-request) by done_image_adapter when matching request
    ids against manifest entries; this early refusal makes the error
    clearer when the entire manifest is the wrong shape."""
    images = spec_doc.get("images")
    if not isinstance(images, list) or not images:
        return False, (
            "FAIL: --image-manifest-spec is missing a non-empty "
            "'images' list."
        )
    for i, entry in enumerate(images):
        if not isinstance(entry, dict):
            return False, (
                f"FAIL: --image-manifest-spec images[{i}] is not a JSON "
                f"object."
            )
        src = entry.get("source")
        if src != "d_one_local":
            return False, (
                f"FAIL: --image-manifest-spec images[{i}].source = "
                f"{src!r}; run_mock_image_pipeline only drives the "
                f"'d_one_local' chain. local_asset / synthetic entries "
                f"belong to a different lifecycle."
            )
    return True, ""


def _write_json(path: Path, body: dict) -> None:
    """Same deterministic shape used by every other helper in this
    repo: sorted keys, 2-space indent, trailing newline."""
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# --bundle resolver. Canonical layout mirrors
# scripts/validate_authoring_bundle.py so the same trial directory shape
# is portable between the two tools, plus two mock-image-only entries
# (d_one_spec.json, optional descriptor_vocabulary.json).
# ---------------------------------------------------------------------------


_BUNDLE_SOURCE_CANDIDATES = ("source.md", "source.txt")
_BUNDLE_BRIEF_NAME = "brief.json"
_BUNDLE_PLAN_SPEC_NAME = "plan_spec.json"
_BUNDLE_DESIGN_SYSTEM_SPEC_NAME = "design_system_spec.json"
_BUNDLE_SLIDE_SPECS_NAME = "slide_specs"
_BUNDLE_IMAGE_MANIFEST_SPEC_NAME = "image_manifest_spec.json"
_BUNDLE_D_ONE_SPEC_NAME = "d_one_spec.json"
_BUNDLE_DESCRIPTOR_VOCABULARY_NAME = "descriptor_vocabulary.json"
_BUNDLE_BRIEF_ALLOWED_FIELDS = frozenset((
    "title", "audience", "objective",
    "tone", "language", "approximate_slide_count", "source_id",
))
_BUNDLE_BRIEF_REQUIRED_FIELDS = ("title", "audience", "objective")


def _refuse_path_with_parent_traversal(
    bundle_dir: Path,
) -> tuple[bool, str]:
    """Refuse any ``--bundle`` path that contains a ``..`` segment.

    ``os.path.abspath`` (used by ``_refuse_symlinked_bundle_ancestor``)
    collapses ``..`` LEXICALLY without following symlinks, but
    ``Path.exists()`` / ``is_dir()`` / ``is_symlink()`` resolve ``..``
    POSIX-ly (after each preceding symlink is followed). A path like
    ``/safe/link/../bundle`` where ``link`` is a symlink to an
    attacker-controlled directory therefore:

      * LEXICALLY collapses to ``/safe/bundle`` — no symlink anywhere
        in the lexical ancestor chain, so the symlinked-ancestor walk
        passes;
      * POSIX-resolves to ``<attacker-parent>/bundle`` because ``..``
        after the symlink steps up to the SYMLINK TARGET's parent, not
        to ``/safe/``.

    The runner reads from the POSIX-resolved location, so without this
    gate the symlinked-ancestor walk silently passes while every
    subsequent ``Path`` operation reads attacker-controlled bytes.
    Refusing every ``..`` segment outright closes the bypass — bundle
    paths are meant to be direct, unambiguous references to a
    canonical bundle directory, and a legitimate caller can always
    pass a pre-resolved path. Single-dot ``.`` segments are normalized
    away by ``pathlib`` itself and are not a concern; ``..`` is the
    only segment that diverges between lexical and POSIX resolution.
    """
    for part in bundle_dir.parts:
        if part == "..":
            return True, (
                f"--bundle path {bundle_dir} contains a `..` segment; "
                f"refusing — bundle paths must not include parent-"
                f"traversal segments because `..` after a symlink "
                f"follows the symlink target's parent on POSIX while "
                f"lexical absolute-path normalization collapses it "
                f"in place, bypassing the symlinked-ancestor gate."
            )
    return False, ""


def _refuse_symlinked_bundle_ancestor(
    bundle_dir: Path,
) -> tuple[bool, str]:
    """Walk every lexical-absolute parent of ``bundle_dir`` and refuse
    if any is a symlink.

    Closes the Codex-review gap where a real bundle copy placed under a
    real parent directory, then reached through a symlink to that
    parent (``/tmp/<probe>/link_parent/synthetic_mock_image_trial``
    where ``link_parent -> real_parent``), passed every per-entry
    ``is_symlink()`` check (the bundle dir itself and every named entry
    inside it were each non-symlink files / directories — only the
    PARENT segment was the symlink). Without this gate an attacker who
    controls a directory the user is asked to point ``--bundle`` at can
    redirect reads to a different bundle copy, silently swapping every
    stage-input spec the runner reads.

    Allowance: the macOS ``/tmp -> private/tmp`` (and ``/tmp ->
    /private/tmp``) convention is the one symlink we accept, because
    refusing it would break every ``TMPDIR=/tmp`` invocation on macOS
    (including the goal's own verification commands and the runner's
    self-test). Any other symlinked ancestor — at any depth between the
    leaf and root — is refused. The root and the immediate bundle dir
    itself are not inspected here; the bundle leaf gets its own
    ``is_symlink()`` check in ``_resolve_bundle`` immediately after."""
    abs_lexical = Path(os.path.abspath(str(bundle_dir)))
    # ``parents`` yields the immediate parent first and the root last.
    for ancestor in abs_lexical.parents:
        if ancestor == ancestor.parent:
            # Reached the filesystem root; nothing meaningful to check.
            break
        if not ancestor.is_symlink():
            continue
        try:
            target = str(ancestor.readlink())
        except OSError:
            target = "<unreadable>"
        # macOS aliases /tmp to /private/tmp; allow that specific pair.
        if (str(ancestor) == "/tmp"
                and target in ("private/tmp", "/private/tmp")):
            continue
        return True, (
            f"--bundle parent {ancestor} is a symlink (-> {target}); "
            f"run_mock_image_pipeline refuses to follow symlinked "
            f"bundle ancestors."
        )
    return False, ""


def _resolve_bundle(
    bundle_dir: Path, *, theme_from_template: bool,
) -> tuple[dict | None, str | None]:
    """Resolve the canonical bundle layout into a kwargs dict that
    matches ``run_mock_image_pipeline``'s keyword arguments.

    Returns ``(kwargs, None)`` on success, ``(None, message)`` on any
    failure — symlinked bundle, symlinked bundle ancestor, missing
    required entry, brief.json malformed or missing required fields,
    design-system mode conflict.

    The helper is read-only; it never writes to the bundle. Brief
    metadata is read from ``<dir>/brief.json``; every other input maps
    1:1 to the explicit ``--*-spec`` flags. The optional
    ``descriptor_vocabulary.json`` resolves to
    ``--descriptor-vocabulary``; the caller can still pass that flag
    explicitly when the bundle omits the file.

    Path safety: the bundle directory itself must be a real directory
    (URI-shaped paths, symlinks, symlinked lexical-absolute ancestors,
    and non-directories are refused), every required entry must be a
    non-symlink regular file / directory, and the slide_specs/ entries
    are each individually refused for being symlinks BEFORE any
    subprocess fires. Symlinks anywhere in the canonical layout — at
    the bundle path, in any ancestor of the bundle path, or on any
    canonical entry — would let an attacker who controls the bundle
    redirect reads outside it; downstream init_* helpers refuse
    symlinks for the same reason, so the bundle-resolver gate is
    belt-and-braces."""
    if _has_uri_scheme(str(bundle_dir)):
        return None, (
            f"--bundle looks like a URI: {bundle_dir} — only local "
            f"directory paths are accepted"
        )
    # The `..` refusal MUST run before the symlinked-ancestor walk:
    # the walk uses `os.path.abspath`, which collapses `..` lexically
    # without following symlinks. A `..` segment paired with an
    # earlier symlink lets the lexical-absolute path "look safe"
    # while POSIX resolution reads attacker-controlled bytes through
    # the symlink target's parent.
    bad, msg = _refuse_path_with_parent_traversal(bundle_dir)
    if bad:
        return None, msg
    bad, msg = _refuse_symlinked_bundle_ancestor(bundle_dir)
    if bad:
        return None, msg
    if bundle_dir.is_symlink():
        return None, f"--bundle is a symlink (refused): {bundle_dir}"
    if not bundle_dir.exists():
        return None, f"--bundle does not exist: {bundle_dir}"
    if not bundle_dir.is_dir():
        return None, f"--bundle is not a directory: {bundle_dir}"

    def _check_regular_file(name: str) -> tuple[Path | None, str | None]:
        path = bundle_dir / name
        if path.is_symlink():
            return None, (
                f"--bundle entry {name} is a symlink (refused): {path}"
            )
        if not path.exists():
            return None, f"--bundle is missing required entry {name}: {path}"
        if not path.is_file():
            return None, (
                f"--bundle entry {name} is not a regular file: {path}"
            )
        return path, None

    def _check_directory(name: str) -> tuple[Path | None, str | None]:
        path = bundle_dir / name
        if path.is_symlink():
            return None, (
                f"--bundle entry {name}/ is a symlink (refused): {path}"
            )
        if not path.exists():
            return None, (
                f"--bundle is missing required entry {name}/: {path}"
            )
        if not path.is_dir():
            return None, (
                f"--bundle entry {name}/ is not a directory: {path}"
            )
        return path, None

    # Source: exactly one of source.md / source.txt; symlinks refused.
    present_sources: list[Path] = []
    for cand in _BUNDLE_SOURCE_CANDIDATES:
        cand_path = bundle_dir / cand
        if cand_path.is_symlink():
            return None, (
                f"--bundle entry {cand} is a symlink (refused): {cand_path}"
            )
        if cand_path.exists():
            if not cand_path.is_file():
                return None, (
                    f"--bundle entry {cand} is not a regular file: "
                    f"{cand_path}"
                )
            present_sources.append(cand_path)
    if not present_sources:
        return None, (
            f"--bundle is missing a source body: expected one of "
            f"{list(_BUNDLE_SOURCE_CANDIDATES)} under {bundle_dir}"
        )
    if len(present_sources) > 1:
        return None, (
            f"--bundle declares more than one source body "
            f"({[p.name for p in present_sources]}); keep exactly one of "
            f"{list(_BUNDLE_SOURCE_CANDIDATES)} under {bundle_dir}"
        )
    source = present_sources[0]

    brief_path, err = _check_regular_file(_BUNDLE_BRIEF_NAME)
    if err is not None:
        return None, err
    plan_spec, err = _check_regular_file(_BUNDLE_PLAN_SPEC_NAME)
    if err is not None:
        return None, err
    slide_specs_dir, err = _check_directory(_BUNDLE_SLIDE_SPECS_NAME)
    if err is not None:
        return None, err
    # Refuse symlinked entries INSIDE slide_specs/ before any subprocess
    # fires. init_slide_plans applies the same per-file refusal
    # downstream, but resolving it here keeps the diagnostic at the
    # runner boundary and prevents a partially-staged workspace from
    # ever being created. The check covers every .json file in
    # slide_specs/ (the only files init_slide_plans reads) AND refuses
    # any nested entry that is itself a symlink (so an attacker cannot
    # plant a symlink at a non-.json path that init_slide_plans would
    # still follow when globbing). Iteration order is sorted so the
    # diagnostic is deterministic across filesystems.
    try:
        nested = sorted(slide_specs_dir.iterdir())
    except OSError as exc:
        return None, (
            f"--bundle slide_specs/ at {slide_specs_dir} could not be "
            f"listed: {type(exc).__name__}: {exc}"
        )
    for entry in nested:
        if entry.is_symlink():
            try:
                target = str(entry.readlink())
            except OSError:
                target = "<unreadable>"
            return None, (
                f"--bundle slide_specs/{entry.name} is a symlink "
                f"(-> {target}); refusing"
            )
    image_manifest_spec, err = _check_regular_file(
        _BUNDLE_IMAGE_MANIFEST_SPEC_NAME,
    )
    if err is not None:
        return None, err
    d_one_spec, err = _check_regular_file(_BUNDLE_D_ONE_SPEC_NAME)
    if err is not None:
        return None, err

    # Design-system mode resolution. The bundle's design_system_spec.json
    # selects --design-system-spec mode; --theme-from-template lets the
    # caller opt out, but mixing both is ambiguous so we refuse.
    ds_path = bundle_dir / _BUNDLE_DESIGN_SYSTEM_SPEC_NAME
    if ds_path.is_symlink():
        return None, (
            f"--bundle entry {_BUNDLE_DESIGN_SYSTEM_SPEC_NAME} is a "
            f"symlink (refused): {ds_path}"
        )
    ds_present = ds_path.exists()
    if ds_present and not ds_path.is_file():
        return None, (
            f"--bundle entry {_BUNDLE_DESIGN_SYSTEM_SPEC_NAME} is not a "
            f"regular file: {ds_path}"
        )
    if theme_from_template and ds_present:
        return None, (
            f"--bundle includes {_BUNDLE_DESIGN_SYSTEM_SPEC_NAME} but "
            f"--theme-from-template was also passed; pick exactly one "
            f"design-system mode"
        )
    if not theme_from_template and not ds_present:
        return None, (
            f"--bundle is missing {_BUNDLE_DESIGN_SYSTEM_SPEC_NAME} and "
            f"--theme-from-template was not passed: {ds_path}"
        )
    design_system_spec = ds_path if ds_present else None

    # Optional descriptor_vocabulary.json. Bundle-resolved when present;
    # otherwise the caller may still pass --descriptor-vocabulary
    # explicitly. Symlinks refused either way.
    vocab_path = bundle_dir / _BUNDLE_DESCRIPTOR_VOCABULARY_NAME
    if vocab_path.is_symlink():
        return None, (
            f"--bundle entry {_BUNDLE_DESCRIPTOR_VOCABULARY_NAME} is a "
            f"symlink (refused): {vocab_path}"
        )
    if vocab_path.exists() and not vocab_path.is_file():
        return None, (
            f"--bundle entry {_BUNDLE_DESCRIPTOR_VOCABULARY_NAME} is "
            f"not a regular file: {vocab_path}"
        )
    descriptor_vocabulary = vocab_path if vocab_path.is_file() else None

    # Read brief.json.
    try:
        raw_brief = brief_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, (
            f"--bundle entry {_BUNDLE_BRIEF_NAME} is not UTF-8 readable: "
            f"{brief_path}: {type(exc).__name__}: {exc}"
        )
    try:
        brief = json.loads(raw_brief)
    except json.JSONDecodeError as exc:
        return None, (
            f"--bundle entry {_BUNDLE_BRIEF_NAME} is malformed JSON: "
            f"{brief_path}: {exc}"
        )
    if not isinstance(brief, dict):
        return None, (
            f"--bundle entry {_BUNDLE_BRIEF_NAME} top-level value is not "
            f"a JSON object; got {type(brief).__name__} at {brief_path}"
        )
    missing = [k for k in _BUNDLE_BRIEF_REQUIRED_FIELDS if k not in brief]
    if missing:
        return None, (
            f"--bundle entry {_BUNDLE_BRIEF_NAME} is missing required "
            f"field(s): {', '.join(missing)} at {brief_path}"
        )
    unknown = sorted(set(brief.keys()) - _BUNDLE_BRIEF_ALLOWED_FIELDS)
    if unknown:
        return None, (
            f"--bundle entry {_BUNDLE_BRIEF_NAME} contains unknown "
            f"field(s): {', '.join(unknown)} at {brief_path}; allowed: "
            f"{sorted(_BUNDLE_BRIEF_ALLOWED_FIELDS)}"
        )

    # Type-validate brief fields the bundle forwards verbatim. The
    # explicit-flag path is type-coerced by argparse (--source-id
    # type=str, --approximate-slide-count type=int); the bundle path
    # reads brief.json untyped, so without this gate a malformed value
    # would surface as a downstream TypeError / schema crash rather
    # than a clean CLI diagnostic. bool is rejected for
    # approximate_slide_count even though isinstance(True, int) is True
    # — a literal JSON true is not a slide count.
    for str_field in (
        "title", "audience", "objective", "tone", "language", "source_id",
    ):
        if str_field in brief and not isinstance(brief[str_field], str):
            return None, (
                f"--bundle entry {_BUNDLE_BRIEF_NAME} field {str_field} "
                f"must be a string if present; got "
                f"{type(brief[str_field]).__name__} at {brief_path}"
            )
    if "approximate_slide_count" in brief:
        value = brief["approximate_slide_count"]
        if isinstance(value, bool) or not isinstance(value, int):
            return None, (
                f"--bundle entry {_BUNDLE_BRIEF_NAME} field "
                f"approximate_slide_count must be an integer if present; "
                f"got {type(value).__name__} at {brief_path}"
            )

    return {
        "source": source,
        "source_id": brief.get("source_id"),
        "title": brief["title"],
        "audience": brief["audience"],
        "objective": brief["objective"],
        "tone": brief.get("tone"),
        "language": brief.get("language"),
        "approximate_slide_count": brief.get("approximate_slide_count"),
        "plan_spec": plan_spec,
        "design_system_spec": design_system_spec,
        "slide_specs_dir": slide_specs_dir,
        "image_manifest_spec": image_manifest_spec,
        "d_one_spec": d_one_spec,
        "descriptor_vocabulary": descriptor_vocabulary,
    }, None


def _check_plan_taxonomy_preserved(
    plan_path: Path, *, expected_per_request: list[dict[str, str]],
) -> tuple[bool, str]:
    """Re-parse ``<staging>/d_one_adapter_plan.json`` and verify:
      * the file exists as a regular non-symlink JSON file;
      * ``schema_version == LOCKED_PLAN_SCHEMA_VERSION``;
      * every taxonomy field / value AND the optional
        ``custom_descriptor`` value AND the optional
        ``placement_role`` value supplied on the spec request appears
        byte-identical on the matching plan request (matched by
        ``id``).
    Returns (ok, msg). msg names the first violation when ok=False."""
    if not (plan_path.is_file() and not plan_path.is_symlink()):
        return False, (
            f"FAIL: produced plan {plan_path} is not a regular non-"
            f"symlink file after the d_one chain ran."
        )
    try:
        plan_doc = json.loads(plan_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return False, (
            f"FAIL: cannot re-parse produced plan {plan_path}: "
            f"{type(exc).__name__}: {exc}"
        )
    if plan_doc.get("schema_version") != LOCKED_PLAN_SCHEMA_VERSION:
        return False, (
            f"FAIL: produced plan schema_version = "
            f"{plan_doc.get('schema_version')!r}; expected "
            f"{LOCKED_PLAN_SCHEMA_VERSION}. The runner refuses to hand "
            f"a downgraded plan to run_explicit_pipeline."
        )
    plan_requests = plan_doc.get("requests")
    if not isinstance(plan_requests, list):
        return False, (
            f"FAIL: produced plan {plan_path} carries no 'requests' "
            f"list."
        )
    by_id: dict[str, dict] = {}
    for r in plan_requests:
        if isinstance(r, dict) and isinstance(r.get("id"), str):
            by_id[r["id"]] = r
    for expected in expected_per_request:
        rid = expected.get("id")
        if not isinstance(rid, str):
            continue
        if rid not in by_id:
            return False, (
                f"FAIL: produced plan is missing request id {rid!r}."
            )
        plan_req = by_id[rid]
        for f in VOCAB_GATED_FIELDS:
            if f not in expected:
                continue
            if plan_req.get(f) != expected[f]:
                return False, (
                    f"FAIL: produced plan request {rid!r} carries "
                    f"{f} = {plan_req.get(f)!r}; expected "
                    f"{expected[f]!r} (byte-identical to the spec)."
                )
    return True, ""


# ---------------------------------------------------------------------------
# Subprocess invocation. We shell out to the existing chain so each
# step's argparse + fail-closed gates + stdout/stderr cascade are
# exercised verbatim.
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


def _format_stage(stage: StageOutcome) -> str:
    mark = "PASS" if stage.ok else "FAIL"
    out = [f"  [{mark}] {stage.name} (rc={stage.exit_code})"]
    if not stage.ok:
        for label, text in (("stdout", stage.stdout), ("stderr", stage.stderr)):
            tail = (text or "").splitlines()[-15:]
            if tail:
                out.append(f"    {label} tail:")
                for line in tail:
                    out.append(f"      {line}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


@dataclass
class MockImagePipelineResult:
    stages: list[StageOutcome] = field(default_factory=list)
    plan_check_ok: bool = False
    plan_check_msg: str = ""
    aborted_reason: str = ""

    @property
    def ok(self) -> bool:
        return (
            not self.aborted_reason
            and bool(self.stages)
            and all(s.ok for s in self.stages)
            and self.plan_check_ok
        )


def run_mock_image_pipeline(
    *,
    workspace: Path,
    source: Path,
    title: str,
    audience: str,
    objective: str,
    plan_spec: Path,
    slide_specs_dir: Path,
    image_manifest_spec: Path,
    d_one_spec: Path,
    template_root: Path,
    output: Path,
    allow_synthetic_bytes: bool,
    descriptor_vocabulary: Path | None = None,
    report_dir: Path | None = None,
    design_system_spec: Path | None = None,
    theme_from_template: bool = False,
    source_id: str | None = None,
    tone: str | None = None,
    language: str | None = None,
    approximate_slide_count: int | None = None,
) -> MockImagePipelineResult:
    """Drive the full local mock D-One chain end-to-end."""
    result = MockImagePipelineResult()

    if not allow_synthetic_bytes:
        result.aborted_reason = (
            "FAIL: --allow-synthetic-bytes is required. This runner is a "
            "MOCK / STUB only — real D-One / provider integration does "
            "not exist in this repo today, so the synthetic-bytes mode "
            "must be opted into explicitly."
        )
        return result

    manifest_doc, msg = _load_json_object(
        image_manifest_spec, "--image-manifest-spec",
    )
    if manifest_doc is None:
        result.aborted_reason = msg
        return result
    ok, msg = _image_manifest_is_d_one_local(manifest_doc)
    if not ok:
        result.aborted_reason = msg
        return result

    spec_doc, msg = _load_json_object(d_one_spec, "--d-one-spec")
    if spec_doc is None:
        result.aborted_reason = msg
        return result
    taxonomy_used = _spec_taxonomy_fields_used(spec_doc)
    if taxonomy_used and descriptor_vocabulary is None:
        result.aborted_reason = (
            f"FAIL: --d-one-spec carries the taxonomy field(s) "
            f"{sorted(taxonomy_used)} but --descriptor-vocabulary was "
            f"not supplied; done_image_adapter requires the vocabulary "
            f"to certify every taxonomy value against the matching "
            f"image_taxonomy.<dim>.allowed_values list."
        )
        return result
    if descriptor_vocabulary is not None:
        rc, msg = _gate_uri_and_symlink(
            descriptor_vocabulary, "--descriptor-vocabulary",
        )
        if rc != 0:
            result.aborted_reason = msg
            return result
        if not (descriptor_vocabulary.is_file()
                and not descriptor_vocabulary.is_symlink()):
            result.aborted_reason = (
                f"FAIL: --descriptor-vocabulary {descriptor_vocabulary} "
                f"is not a regular non-symlink file."
            )
            return result

    for label, p in (
        ("--workspace", workspace),
        ("--output", output),
    ):
        rc, msg = _gate_uri_and_symlink(p, label)
        if rc != 0:
            result.aborted_reason = msg
            return result
    if report_dir is not None:
        rc, msg = _gate_uri_and_symlink(report_dir, "--report-dir")
        if rc != 0:
            result.aborted_reason = msg
            return result

    # Compute the per-request expected-taxonomy snapshot now so we can
    # cross-check the plan AFTER done_image_adapter writes it. Snapshot
    # covers TAXONOMY_FIELDS plus the optional custom_descriptor
    # escape-hatch field — every vocab-gated field is held to the same
    # byte-identical-from-spec contract.
    expected_per_request: list[dict[str, str]] = []
    for req in spec_doc.get("requests", []):
        if not isinstance(req, dict):
            continue
        snap: dict[str, str] = {}
        rid = req.get("id")
        if isinstance(rid, str):
            snap["id"] = rid
        for f in VOCAB_GATED_FIELDS:
            if f in req and isinstance(req[f], str):
                snap[f] = req[f]
        if snap:
            expected_per_request.append(snap)

    py = sys.executable
    with tempfile.TemporaryDirectory(
        prefix="szh_run_mock_image_pipeline_",
    ) as raw_td:
        td = Path(raw_td)
        staging = td / "staging"
        staging_assets = td / "staging_assets"
        staging_assets.mkdir()

        effective_source_id = source_id or source.stem

        # 1. Init the staging workspace so source_manifest.json +
        #    input/source.md exist (done_image_adapter's optional
        #    40-char shingle scan reads input/source.md when present).
        init_cmd = [
            py, str(SCRIPTS_DIR / "init_workspace.py"),
            "--workspace", str(staging),
            "--source", str(source),
            "--source-id", effective_source_id,
        ]
        outcome = _run_stage("init_workspace (staging)", init_cmd)
        result.stages.append(outcome)
        if not outcome.ok:
            return result

        # 2. Hand-write the d_one_local image_manifest.json into the
        #    staging workspace (the direct-author workflow documented
        #    at scripts/materialize_image_assets.py). The spec body IS
        #    the manifest body — we copy it verbatim, bytes-deterministic.
        try:
            _write_json(staging / "image_manifest.json", manifest_doc)
        except OSError as exc:
            result.aborted_reason = (
                f"FAIL: cannot hand-write staging image_manifest.json: "
                f"{type(exc).__name__}: {exc}"
            )
            return result

        # 3. done_image_adapter writes d_one_adapter_plan.json.
        adapter_cmd = [
            py, str(SCRIPTS_DIR / "done_image_adapter.py"),
            "--workspace", str(staging),
            "--spec", str(d_one_spec),
        ]
        if descriptor_vocabulary is not None:
            adapter_cmd += [
                "--descriptor-vocabulary", str(descriptor_vocabulary),
            ]
        outcome = _run_stage("done_image_adapter", adapter_cmd)
        result.stages.append(outcome)
        if not outcome.ok:
            return result

        # 4. Plan taxonomy preservation gate. Re-parse the plan and
        #    refuse before we shell out to run_d_one_generation if the
        #    plan drifted on schema_version or any taxonomy value.
        plan_path = staging / "d_one_adapter_plan.json"
        ok, msg = _check_plan_taxonomy_preserved(
            plan_path,
            expected_per_request=expected_per_request,
        )
        result.plan_check_ok = ok
        result.plan_check_msg = msg
        if not ok:
            result.aborted_reason = msg
            return result

        # 5. run_d_one_generation emits the synthetic PNG/JPEG bytes
        #    into the staging assets dir.
        gen_cmd = [
            py, str(SCRIPTS_DIR / "run_d_one_generation.py"),
            "--workspace", str(staging),
            "--assets-dir", str(staging_assets),
            "--allow-synthetic-bytes",
        ]
        if descriptor_vocabulary is not None:
            gen_cmd += [
                "--descriptor-vocabulary", str(descriptor_vocabulary),
            ]
        outcome = _run_stage("run_d_one_generation", gen_cmd)
        result.stages.append(outcome)
        if not outcome.ok:
            return result

        # 6. materialize_image_assets copies the bytes into
        #    <staging>/<local_path> so the staging workspace can serve
        #    as --assets-dir to run_explicit_pipeline.
        mat_cmd = [
            py, str(SCRIPTS_DIR / "materialize_image_assets.py"),
            "--workspace", str(staging),
            "--assets-dir", str(staging_assets),
        ]
        outcome = _run_stage("materialize_image_assets", mat_cmd)
        result.stages.append(outcome)
        if not outcome.ok:
            return result

        # 7. run_explicit_pipeline against the caller's production
        #    workspace with --assets-dir <staging>. The orchestrator
        #    re-runs materialize_image_assets between Stage 5 and
        #    Stage 6 so init_image_manifest finds the bytes on disk.
        rxp_cmd = [
            py, str(SCRIPTS_DIR / "run_explicit_pipeline.py"),
            "--workspace", str(workspace),
            "--source", str(source),
            "--title", title,
            "--audience", audience,
            "--objective", objective,
            "--plan-spec", str(plan_spec),
            "--slide-specs-dir", str(slide_specs_dir),
            "--image-manifest-spec", str(image_manifest_spec),
            "--template-root", str(template_root),
            "--assets-dir", str(staging),
            "--output", str(output),
        ]
        if source_id is not None:
            rxp_cmd += ["--source-id", source_id]
        if tone is not None:
            rxp_cmd += ["--tone", tone]
        if language is not None:
            rxp_cmd += ["--language", language]
        if approximate_slide_count is not None:
            rxp_cmd += [
                "--approximate-slide-count", str(approximate_slide_count),
            ]
        if design_system_spec is not None:
            rxp_cmd += ["--design-system-spec", str(design_system_spec)]
        if theme_from_template:
            rxp_cmd += ["--theme-from-template"]
        if report_dir is not None:
            rxp_cmd += ["--report-dir", str(report_dir)]
        outcome = _run_stage("run_explicit_pipeline", rxp_cmd)
        result.stages.append(outcome)
    return result


# ---------------------------------------------------------------------------
# CLI surface.
# ---------------------------------------------------------------------------


def _format_result(result: MockImagePipelineResult) -> str:
    lines = ["=== run_mock_image_pipeline ==="]
    if result.aborted_reason and not result.stages:
        lines.append(f"  {result.aborted_reason}")
        return "\n".join(lines)
    for s in result.stages:
        lines.append(_format_stage(s))
    if result.plan_check_msg and not result.plan_check_ok:
        lines.append(f"  [FAIL] taxonomy preservation check")
        lines.append(f"    {result.plan_check_msg}")
    elif result.plan_check_ok:
        lines.append(
            "  [PASS] taxonomy preservation check "
            f"(plan.schema_version=={LOCKED_PLAN_SCHEMA_VERSION}; "
            "taxonomy + custom_descriptor fields byte-identical)"
        )
    if result.aborted_reason and result.stages:
        lines.append(f"  ABORT: {result.aborted_reason}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mock D-One image-to-editable-PPT runner. Packages the "
            "local image chain (done_image_adapter -> "
            "run_d_one_generation --allow-synthetic-bytes -> "
            "materialize_image_assets -> run_explicit_pipeline) into "
            "one command. MOCK / STUB only: NEVER calls D-One, MCP, "
            "Qoder, a public network, telemetry, any model API, an "
            "image search, or any external service. "
            "--allow-synthetic-bytes is REQUIRED — omitting it fails "
            "closed rather than implying a real provider mode that "
            "does not exist in this repo today."
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Production workspace directory to create (forwarded to "
             "init_workspace via run_explicit_pipeline).",
    )
    parser.add_argument(
        "--source", type=Path, default=None,
        help="Local .md or .txt source file (forwarded to "
             "init_workspace; also used to seed the staging workspace "
             "so done_image_adapter's optional input/source.md shingle "
             "scan has a body to check).",
    )
    parser.add_argument(
        "--source-id", type=str, default=None,
        help="Opaque source identifier (forwarded to init_workspace; "
             "defaults to --source filename stem).",
    )
    parser.add_argument(
        "--title", type=str, default=None,
        help="Deck title (forwarded to init_deck_brief).",
    )
    parser.add_argument(
        "--audience", type=str, default=None,
        help="Audience (forwarded to init_deck_brief).",
    )
    parser.add_argument(
        "--objective", type=str, default=None,
        help="Objective (forwarded to init_deck_brief).",
    )
    parser.add_argument(
        "--tone", type=str, default=None,
        help="Optional tone (forwarded to init_deck_brief).",
    )
    parser.add_argument(
        "--language", type=str, default=None,
        help="Optional language (forwarded to init_deck_brief).",
    )
    parser.add_argument(
        "--approximate-slide-count", type=int, default=None,
        help="Optional planning hint (forwarded to init_deck_brief).",
    )
    parser.add_argument(
        "--plan-spec", type=Path, default=None,
        help="Deck-plan JSON candidate (forwarded to init_deck_plan).",
    )
    parser.add_argument(
        "--design-system-spec", type=Path, default=None,
        help="Design-system JSON candidate. Mutually exclusive with "
             "--theme-from-template; exactly one is required.",
    )
    parser.add_argument(
        "--theme-from-template", action="store_true",
        help="Project palette/typography/grid from deck_plan.template's "
             "theme. Mutually exclusive with --design-system-spec.",
    )
    parser.add_argument(
        "--template-root", type=Path, default=None,
        help="Template root directory (e.g. templates/layouts/).",
    )
    parser.add_argument(
        "--slide-specs-dir", type=Path, default=None,
        help="Directory of slide_plan JSON candidates (forwarded to "
             "init_slide_plans).",
    )
    parser.add_argument(
        "--image-manifest-spec", type=Path, default=None,
        help="Image-manifest JSON candidate. Every entry's source MUST "
             "be 'd_one_local' — the runner only drives that chain.",
    )
    parser.add_argument(
        "--d-one-spec", type=Path, default=None, dest="d_one_spec",
        help="Caller-authored D-One request spec (forwarded to "
             "done_image_adapter --spec). Top-level object with a "
             "non-empty 'requests' list. Any request carrying a "
             "taxonomy field (rendering_style / palette_family / "
             "image_role / layout_pattern / modifier / text_policy / "
             "subject_domain) OR the optional custom_descriptor "
             "escape-hatch field OR the optional placement_role field "
             "(closed enumeration hero_page / local_region) forces "
             "--descriptor-vocabulary.",
    )
    parser.add_argument(
        "--descriptor-vocabulary", type=Path, default=None,
        dest="descriptor_vocabulary",
        help="Optional. Forwarded verbatim to BOTH done_image_adapter "
             "and run_d_one_generation. Required iff --d-one-spec "
             "carries any of the seven taxonomy fields, the optional "
             "custom_descriptor escape-hatch field, or the optional "
             "placement_role field. The placement_role gate also fires "
             "the fail-closed overlay-reservation safety scan against "
             "every prompt / intended_use / custom_descriptor: cues "
             "that ask to reserve calm / empty / right / lower-third / "
             "center space, SVG / PPT / native / editable text overlay, "
             "or title overlay are accepted only with "
             "placement_role='hero_page'.",
    )
    parser.add_argument(
        "--allow-synthetic-bytes", action="store_true",
        dest="allow_synthetic_bytes",
        help="REQUIRED. Explicit opt-in to the synthetic-bytes (mock) "
             "D-One mode. Omitting this flag fails closed instead of "
             "implying a real-D-One / provider mode this repo does "
             "NOT support today.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Path to write the .pptx output. Must end in .pptx; must "
             "live outside --workspace; symlinks refused.",
    )
    parser.add_argument(
        "--report-dir", type=Path, default=None,
        help="Optional directory under which run_explicit_pipeline "
             "(via run_pipeline) writes pipeline_report.{json,txt} + "
             "inventory.json. Must live outside --workspace; symlinks "
             "refused.",
    )
    parser.add_argument(
        "--bundle", type=Path, default=None,
        help="Resolve every stage-input spec from a single bundle "
             "directory. Canonical layout: <dir>/source.md (or "
             "source.txt), <dir>/brief.json (JSON object with title / "
             "audience / objective and optional tone / language / "
             "approximate_slide_count / source_id), "
             "<dir>/plan_spec.json, <dir>/design_system_spec.json "
             "(omit when --theme-from-template is passed), "
             "<dir>/slide_specs/, <dir>/image_manifest_spec.json, "
             "<dir>/d_one_spec.json, and optional "
             "<dir>/descriptor_vocabulary.json (forwarded to "
             "--descriptor-vocabulary when present; otherwise pass "
             "--descriptor-vocabulary explicitly when d_one_spec.json "
             "carries any of the seven taxonomy fields, the optional "
             "custom_descriptor escape-hatch field, or the optional "
             "placement_role field). Mutually exclusive with the "
             "explicit per-input flags; --workspace, --output, "
             "--report-dir, --template-root, --theme-from-template, "
             "and --allow-synthetic-bytes remain explicit.",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run 37 in-script tempfixture scenarios covering: the "
             "happy-path mock chain (2-slide bundle with one "
             "d_one_local image carrying all 7 taxonomy dimensions; "
             "proves PPTX embeds an internal ppt/media PNG/JPG/JPEG "
             "part with no external/file/data/scheme relationships AND "
             "the [PASS] taxonomy preservation check marker fires); "
             "negative probes for missing --allow-synthetic-bytes, "
             "missing --descriptor-vocabulary with taxonomy fields, "
             "invalid text_policy / subject_domain values, "
             "editable-text wording in the prompt ('slide title') "
             "refused before any production workspace or PPTX is "
             "created, in-image-text wording in the prompt under "
             "text_policy='no_text' refused before any production "
             "workspace or PPTX is created, boundary-safe phrases "
             "('image texture' / 'textured paper' / 'context "
             "lighting' / 'texture pattern') under "
             "text_policy='no_text' still pass the chain end-to-end "
             "and produce a PPTX with internal PNG/JPG/JPEG media, "
             "schema_version=4 invariant on the produced plan "
             "(downgrade refused indirectly via plan re-parse), "
             "an APPROVED custom_descriptor escape-hatch value matching "
             "the supplied vocab's custom_descriptors[] allow-list "
             "passes the chain end-to-end and the value lands on the "
             "produced plan byte-identical to the spec, an UNAPPROVED "
             "custom_descriptor value is refused by done_image_adapter "
             "before any production workspace or PPTX is created, "
             "placement_role='hero_page' + overlay-reservation cue "
             "(calm space / title overlay) passes the chain end-to-end "
             "and the value lands on the produced plan byte-identical "
             "to the spec, placement_role='local_region' + overlay-"
             "reservation cue is REFUSED before any production "
             "workspace or PPTX is created (SVG/PPT text-overlay "
             "reservation belongs to hero-page images, not local "
             "region-block images), placement_role omitted + overlay-"
             "reservation cue is also REFUSED (default-deny so "
             "dropping the field does not bypass the gate), "
             "placement_role='local_region' + ORDINARY schematic "
             "prompt without overlay-reservation cues passes the chain "
             "end-to-end (the gate is narrow, not a blanket ban on "
             "local_region), missing fixture/request image id "
             "mismatch, unsafe local_path/URL in the image-manifest "
             "spec, symlinked --output / --workspace / --report-dir "
             "targets; a no-repo-write snapshot probe that strips "
             "PYTHONDONTWRITEBYTECODE from the subprocess env and "
             "asserts scripts/__pycache__/ is byte-identical before "
             "and after the run (proves the in-script "
             "sys.dont_write_bytecode=True flip closes the .pyc-leak "
             "hole even when the caller forgets the env prefix); a "
             "--bundle happy-path probe asserting the canonical bundle "
             "layout (source.md / brief.json / plan_spec.json / "
             "design_system_spec.json / slide_specs/ / "
             "image_manifest_spec.json / d_one_spec.json / optional "
             "descriptor_vocabulary.json) drives the same mock chain "
             "to a validated PPTX; --bundle fail-closed probes for "
             "URI-shaped bundle paths, symlinked bundle dir, symlinked "
             "brief.json inside the bundle, symlinked PARENT directory "
             "of the bundle (the Codex review repro: a real bundle "
             "copy reached through link_parent -> real_parent), "
             "parent-traversal `..` bypass of the symlinked-ancestor "
             "gate (the second Codex review finding: a path like "
             "<td>/parent_dir/link/../atk_bundle collapses to "
             "<td>/parent_dir/atk_bundle lexically but POSIX-resolves "
             "through link to <td>/atk_bundle — the runner refuses "
             "any `..` segment outright), "
             "symlinked slide_specs/<name>.json inside the bundle, "
             "symlinked optional descriptor_vocabulary.json inside the "
             "bundle, brief.json with a "
             "non-integer approximate_slide_count, brief.json with an "
             "unknown field, missing descriptor_vocabulary.json with "
             "taxonomy fields and no explicit --descriptor-vocabulary, "
             "--bundle mixed with an explicit per-input flag, unsafe "
             "local_path inside the bundle's image_manifest_spec, "
             "d_one_spec request id not present in the bundle's "
             "image_manifest_spec, and a --bundle no-repo-write probe "
             "mirroring the explicit-flag one; and "
             "a failure-cleanup probe asserting no .pptx lands at "
             "--output when the run aborts (the staging tempdir is "
             "auto-cleaned by tempfile.TemporaryDirectory). Mutually "
             "exclusive with the orchestration flags.",
    )

    args = parser.parse_args(argv)

    if args.self_test:
        orchestration = (
            args.workspace, args.source, args.source_id, args.title,
            args.audience, args.objective, args.tone, args.language,
            args.approximate_slide_count, args.plan_spec,
            args.design_system_spec, args.template_root,
            args.slide_specs_dir, args.image_manifest_spec,
            args.d_one_spec, args.descriptor_vocabulary,
            args.output, args.report_dir, args.bundle,
        )
        if any(v is not None for v in orchestration) or \
                args.theme_from_template or args.allow_synthetic_bytes:
            print(
                "FAIL: --self-test does not take any other argument",
                file=sys.stderr,
            )
            return 2
        return _run_self_test()

    if args.bundle is not None:
        # --bundle is a shortcut: every explicit per-input flag the
        # bundle resolves must be absent so precedence is unambiguous.
        # --workspace, --output, --report-dir, --template-root,
        # --theme-from-template, and --allow-synthetic-bytes are the
        # only flags that compose with --bundle. --descriptor-vocabulary
        # composes ONLY when the bundle omits the optional
        # descriptor_vocabulary.json (verified below).
        conflicting = [
            name for name, value in (
                ("--source", args.source),
                ("--source-id", args.source_id),
                ("--title", args.title),
                ("--audience", args.audience),
                ("--objective", args.objective),
                ("--tone", args.tone),
                ("--language", args.language),
                ("--approximate-slide-count", args.approximate_slide_count),
                ("--plan-spec", args.plan_spec),
                ("--design-system-spec", args.design_system_spec),
                ("--slide-specs-dir", args.slide_specs_dir),
                ("--image-manifest-spec", args.image_manifest_spec),
                ("--d-one-spec", args.d_one_spec),
            )
            if value is not None
        ]
        if conflicting:
            print(
                f"FAIL: --bundle is mutually exclusive with the explicit "
                f"per-input flags ({', '.join(conflicting)}); pass one "
                f"or the other, not both",
                file=sys.stderr,
            )
            return 2
        resolved, err = _resolve_bundle(
            args.bundle, theme_from_template=args.theme_from_template,
        )
        if err is not None:
            print(f"FAIL: {err}", file=sys.stderr)
            return 2
        args.source = resolved["source"]
        args.source_id = resolved["source_id"]
        args.title = resolved["title"]
        args.audience = resolved["audience"]
        args.objective = resolved["objective"]
        args.tone = resolved["tone"]
        args.language = resolved["language"]
        args.approximate_slide_count = resolved["approximate_slide_count"]
        args.plan_spec = resolved["plan_spec"]
        args.design_system_spec = resolved["design_system_spec"]
        args.slide_specs_dir = resolved["slide_specs_dir"]
        args.image_manifest_spec = resolved["image_manifest_spec"]
        args.d_one_spec = resolved["d_one_spec"]
        # Bundle-supplied vocab wins; otherwise leave whatever the
        # caller passed explicitly. Refuse mixing both so the source of
        # truth is unambiguous.
        if resolved["descriptor_vocabulary"] is not None:
            if args.descriptor_vocabulary is not None:
                print(
                    f"FAIL: --bundle includes "
                    f"{_BUNDLE_DESCRIPTOR_VOCABULARY_NAME} but "
                    f"--descriptor-vocabulary was also passed; pass "
                    f"exactly one source of the descriptor vocabulary",
                    file=sys.stderr,
                )
                return 2
            args.descriptor_vocabulary = resolved["descriptor_vocabulary"]

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
            ("--d-one-spec", args.d_one_spec),
            ("--template-root", args.template_root),
            ("--output", args.output),
        )
        if value is None
    ]
    if missing:
        print(
            f"FAIL: missing required argument(s): {', '.join(missing)} "
            f"(use --self-test for the in-script scenarios).",
            file=sys.stderr,
        )
        return 2

    if args.design_system_spec is None and not args.theme_from_template:
        print(
            "FAIL: must pass either --design-system-spec <path> or "
            "--theme-from-template",
            file=sys.stderr,
        )
        return 2
    if args.design_system_spec is not None and args.theme_from_template:
        print(
            "FAIL: --design-system-spec and --theme-from-template are "
            "mutually exclusive; pick exactly one.",
            file=sys.stderr,
        )
        return 2

    if not args.allow_synthetic_bytes:
        print(
            "FAIL: --allow-synthetic-bytes is REQUIRED. This runner is "
            "a MOCK / STUB only — real D-One / provider integration "
            "does not exist in this repo today, so the synthetic-bytes "
            "mode must be opted into explicitly.",
            file=sys.stderr,
        )
        return 2

    if args.output.suffix.lower() != ".pptx":
        print(
            f"FAIL: --output must end in .pptx; got {args.output}",
            file=sys.stderr,
        )
        return 2

    result = run_mock_image_pipeline(
        workspace=args.workspace,
        source=args.source,
        title=args.title,
        audience=args.audience,
        objective=args.objective,
        plan_spec=args.plan_spec,
        slide_specs_dir=args.slide_specs_dir,
        image_manifest_spec=args.image_manifest_spec,
        d_one_spec=args.d_one_spec,
        template_root=args.template_root,
        output=args.output,
        allow_synthetic_bytes=args.allow_synthetic_bytes,
        descriptor_vocabulary=args.descriptor_vocabulary,
        report_dir=args.report_dir,
        design_system_spec=args.design_system_spec,
        theme_from_template=args.theme_from_template,
        source_id=args.source_id,
        tone=args.tone,
        language=args.language,
        approximate_slide_count=args.approximate_slide_count,
    )
    print(_format_result(result))
    if result.ok:
        print(
            f"OK: mock D-One image-to-editable-PPT run succeeded; PPTX "
            f"written to {args.output}."
        )
        return 0
    if result.aborted_reason and not result.stages:
        print(f"FAIL: aborted before any subprocess fired.", file=sys.stderr)
        return 2
    return 1


# ===========================================================================
# Self-test. Each scenario runs under tempfile.TemporaryDirectory() and
# invokes the runner via the live argparse entry point as a subprocess
# so the documented diagnostics actually surface.
# ===========================================================================


_SYNTHETIC_SOURCE_ID = "synthetic_mock_image_pipeline_source"
_SYNTHETIC_TITLE = "Mock Image Pipeline Self-Test"
_SYNTHETIC_AUDIENCE = "Internal pipeline reviewers"
_SYNTHETIC_OBJECTIVE = (
    "Exercise the local mock D-One chain end-to-end on a synthetic, "
    "non-sensitive narrative."
)
_SYNTHETIC_TONE = "neutral-professional"
_SYNTHETIC_LANGUAGE = "en"
_SYNTHETIC_APPROXIMATE_SLIDE_COUNT = 2
_SYNTHETIC_TEMPLATE = "business_review"
_SYNTHETIC_IMAGE_ID = "cover_accent"
_SYNTHETIC_IMAGE_LOCAL_PATH = "media/cover_accent.png"
_SYNTHETIC_IMAGE_ALT_TEXT = (
    "Synthetic abstract pattern (mock D-One output)."
)
_SYNTHETIC_IMAGE_PROMPT = (
    "abstract geometric pattern in a calm neutral gradient, "
    "no text, no logo"
)

# One canonical value per dimension. Mirrors the canonical enums the
# descriptor-vocabulary schema locks.
_TAXONOMY_REQUEST: dict[str, str] = {
    "rendering_style": "flat_vector",
    "palette_family": "neutral_grey",
    "image_role": "decorative_accent",
    "layout_pattern": "single_center",
    "modifier": "soft_edges",
    "text_policy": "no_text",
    "subject_domain": "abstract_geometry",
}

# RFC-3986 scheme prefix for the relationship-Target walk.
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_REL_URI_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _source_md_text() -> str:
    return (
        "# Synthetic Mock Image Pipeline Source\n\n"
        "This document is synthetic. It contains no real company, "
        "product, customer, or financial data.\n\n"
        "It exists only to exercise the local mock D-One chain.\n"
    )


def _plan_spec_body() -> dict:
    return {
        "template": _SYNTHETIC_TEMPLATE,
        "planning": {
            "planned_slide_count": 2,
            "rationale": (
                "Two-slide synthetic deck: cover with a taxonomy-"
                "tagged accent image plus a conclusion."
            ),
        },
        "sections": [
            {
                "id": "open", "title": "Open",
                "summary": "Cover with accent image.",
                "slide_indices": [1],
            },
            {
                "id": "close", "title": "Close",
                "summary": "Conclusion.",
                "slide_indices": [2],
            },
        ],
        "slides": [
            {
                "index": 1, "layout": "cover",
                "title": _SYNTHETIC_TITLE,
                "section_id": "open",
                "summary": "Cover with a taxonomy-tagged accent image.",
                "density": "low",
                "source_refs": [_SYNTHETIC_SOURCE_ID],
            },
            {
                "index": 2, "layout": "conclusion",
                "title": "Self-Test Outcome",
                "section_id": "close",
                "summary": "Synthetic self-test outcome.",
                "density": "low",
                "source_refs": [_SYNTHETIC_SOURCE_ID],
            },
        ],
    }


def _design_system_body() -> dict:
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


def _slide_cover_body() -> dict:
    return {
        "index": 1, "layout": "cover", "title": _SYNTHETIC_TITLE,
        "subtitle": "Mock D-One chain end-to-end",
        "blocks": [
            {"id": "title", "kind": "text", "content": _SYNTHETIC_TITLE},
            {"id": "subtitle", "kind": "text",
             "content": "Mock D-One chain end-to-end"},
            {"id": "presenter", "kind": "text",
             "content": "Synthetic Reviewer"},
            {"id": "date", "kind": "text",
             "content": "Synthetic window"},
            {"id": "accent", "kind": "image_ref",
             "content": _SYNTHETIC_IMAGE_ID},
        ],
        "image_refs": [_SYNTHETIC_IMAGE_ID],
        "notes": "Synthetic.",
    }


def _slide_conclusion_body() -> dict:
    return {
        "index": 2, "layout": "conclusion", "title": "Self-Test Outcome",
        "blocks": [
            {"id": "title", "kind": "text",
             "content": "Self-Test Outcome"},
            {"id": "summary", "kind": "text",
             "content": (
                 "Synthetic mock D-One chain succeeded; mock bytes "
                 "are embedded under ppt/media/."
             )},
        ],
    }


def _image_manifest_body() -> dict:
    return {
        "images": [
            {
                "id": _SYNTHETIC_IMAGE_ID,
                "local_path": _SYNTHETIC_IMAGE_LOCAL_PATH,
                "source": "d_one_local",
                "alt_text": _SYNTHETIC_IMAGE_ALT_TEXT,
                "intended_use": "spot illustration",
            },
        ],
    }


def _d_one_spec_body_with_taxonomy() -> dict:
    req: dict = {
        "id": _SYNTHETIC_IMAGE_ID,
        "prompt": _SYNTHETIC_IMAGE_PROMPT,
        "intended_use": "spot illustration",
        "width_px": 320, "height_px": 320,
    }
    req.update(_TAXONOMY_REQUEST)
    return {"requests": [req]}


def _d_one_spec_body_without_taxonomy() -> dict:
    return {
        "requests": [
            {
                "id": _SYNTHETIC_IMAGE_ID,
                "prompt": _SYNTHETIC_IMAGE_PROMPT,
                "intended_use": "spot illustration",
                "width_px": 320, "height_px": 320,
            },
        ],
    }


def _descriptor_vocabulary_body() -> dict:
    return {
        "schema_version": 1,
        "note": (
            "Synthetic D-One descriptor vocabulary for the mock image "
            "pipeline self-test."
        ),
        "kind_enum": [
            "color_token", "geometric_noun",
            "mood_adjective", "composition_adjective",
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
                "decorative_accent", "metaphor_icon",
                "divider_motif", "kpi_emblem", "cover_motif",
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
            # Optional placement_role allow-list (8th dimension).
            "placement_role": {"allowed_values": [
                "hero_page", "local_region",
            ]},
        },
        # Approved custom-descriptor allow-list (escape-hatch). Same
        # shape as descriptors[]; the adapter projects the value
        # strings into a set and refuses any request whose
        # custom_descriptor field is not a member.
        "custom_descriptors": [
            {
                "kind": "composition_adjective",
                "value": "hero_centered_motif",
                "approved_in_review_ref": "synthetic_review.001",
            },
            {
                "kind": "color_token",
                "value": "palette.accent_pair",
                "approved_in_review_ref": "synthetic_review.002",
            },
        ],
    }


def _materialize_bundle(td: Path, *, d_one_spec_body: dict) -> dict:
    """Write the synthetic bundle (source + every spec file) under
    ``td/bundle/`` and return a dict of resolved paths."""
    bundle = td / "bundle"
    bundle.mkdir(parents=True)
    source = bundle / "source.md"
    source.write_text(_source_md_text())

    plan_spec = bundle / "plan_spec.json"
    _write_json(plan_spec, _plan_spec_body())

    design_system_spec = bundle / "design_system_spec.json"
    _write_json(design_system_spec, _design_system_body())

    slide_specs_dir = bundle / "slide_specs"
    slide_specs_dir.mkdir()
    _write_json(slide_specs_dir / "01_cover.json", _slide_cover_body())
    _write_json(
        slide_specs_dir / "02_conclusion.json", _slide_conclusion_body(),
    )

    image_manifest_spec = bundle / "image_manifest_spec.json"
    _write_json(image_manifest_spec, _image_manifest_body())

    d_one_spec = bundle / "d_one_spec.json"
    _write_json(d_one_spec, d_one_spec_body)

    descriptor_vocabulary = bundle / "descriptor_vocabulary.json"
    _write_json(descriptor_vocabulary, _descriptor_vocabulary_body())

    return {
        "bundle": bundle,
        "source": source,
        "plan_spec": plan_spec,
        "design_system_spec": design_system_spec,
        "slide_specs_dir": slide_specs_dir,
        "image_manifest_spec": image_manifest_spec,
        "d_one_spec": d_one_spec,
        "descriptor_vocabulary": descriptor_vocabulary,
    }


def _invoke_runner(extra_args: list[str]) -> StageOutcome:
    """Spawn this script as a subprocess so the live argparse + main()
    flow is exercised."""
    cmd = [sys.executable, str(Path(__file__).resolve())] + extra_args
    return _run_stage("run_mock_image_pipeline", cmd)


def _baseline_runner_args(
    *, bundle: dict, workspace: Path, output: Path,
    report_dir: Path | None = None,
    with_vocab: bool = True,
) -> list[str]:
    args = [
        "--workspace", str(workspace),
        "--source", str(bundle["source"]),
        "--source-id", _SYNTHETIC_SOURCE_ID,
        "--title", _SYNTHETIC_TITLE,
        "--audience", _SYNTHETIC_AUDIENCE,
        "--objective", _SYNTHETIC_OBJECTIVE,
        "--tone", _SYNTHETIC_TONE,
        "--language", _SYNTHETIC_LANGUAGE,
        "--approximate-slide-count",
        str(_SYNTHETIC_APPROXIMATE_SLIDE_COUNT),
        "--plan-spec", str(bundle["plan_spec"]),
        "--design-system-spec", str(bundle["design_system_spec"]),
        "--template-root", str(TEMPLATE_ROOT),
        "--slide-specs-dir", str(bundle["slide_specs_dir"]),
        "--image-manifest-spec", str(bundle["image_manifest_spec"]),
        "--d-one-spec", str(bundle["d_one_spec"]),
        "--allow-synthetic-bytes",
        "--output", str(output),
    ]
    if with_vocab:
        args += [
            "--descriptor-vocabulary", str(bundle["descriptor_vocabulary"]),
        ]
    if report_dir is not None:
        args += ["--report-dir", str(report_dir)]
    return args


@dataclass
class _Scenario:
    name: str
    ok: bool
    detail: str = ""


def _pptx_embeds_internal_media_only(pptx: Path) -> tuple[bool, str]:
    """Open PPTX as ZIP and assert at least one ``ppt/media/<file>``
    part exists with an embeddable extension AND no .rels Relationship
    Target carries a URI scheme / external TargetMode."""
    import zipfile
    from xml.etree import ElementTree as ET

    if not (pptx.is_file() and not pptx.is_symlink()):
        return False, f"PPTX is not a regular non-symlink file: {pptx}"
    try:
        zf = zipfile.ZipFile(pptx, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        return False, f"PPTX cannot be opened as ZIP: {exc!r}"
    try:
        names = zf.namelist()
        media_files = [
            n for n in names
            if n.startswith("ppt/media/")
            and Path(n).suffix.lower() in _EMBEDDABLE_MEDIA_EXTS
        ]
        if not media_files:
            return False, (
                "PPTX has no ppt/media/ part with an embeddable "
                "extension; mock D-One bytes did not embed as media."
            )
        rel_tag = f"{{{_REL_NS}}}Relationship"
        external: list[str] = []
        for n in names:
            if not n.endswith(".rels"):
                continue
            try:
                body = zf.read(n)
                root = ET.fromstring(body)
            except (KeyError, OSError, ET.ParseError) as exc:
                external.append(f"{n}: cannot parse: {exc!r}")
                continue
            for el in root:
                if el.tag != rel_tag:
                    continue
                target = el.attrib.get("Target", "")
                mode = el.attrib.get("TargetMode", "")
                if mode and mode != "Internal":
                    external.append(
                        f"{n}: TargetMode={mode!r} Target={target!r}"
                    )
                elif _REL_URI_PREFIX.match(target):
                    external.append(
                        f"{n}: Target={target!r} (URI scheme)"
                    )
        if external:
            return False, (
                "PPTX has external / scheme-shaped relationships: "
                + "; ".join(external)
            )
    finally:
        zf.close()
    return True, ""


def _scenario_happy_path(td: Path) -> _Scenario:
    bundle = _materialize_bundle(
        td / "happy", d_one_spec_body=_d_one_spec_body_with_taxonomy(),
    )
    ws = td / "happy_ws"
    out = td / "happy.pptx"
    report = td / "happy_report"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out, report_dir=report,
    ))
    if outcome.exit_code != 0:
        return _Scenario(
            "happy path: 2-slide bundle with all 7 taxonomy fields "
            "produces a validated PPTX",
            False,
            f"rc={outcome.exit_code}; "
            f"stderr tail: {outcome.stderr.splitlines()[-10:]!r}; "
            f"stdout tail: {outcome.stdout.splitlines()[-10:]!r}",
        )
    if not out.is_file() or out.is_symlink():
        return _Scenario(
            "happy path PPTX exists as regular non-symlink file",
            False, f"out={out}, is_file={out.is_file()}",
        )
    ok, msg = _pptx_embeds_internal_media_only(out)
    if not ok:
        return _Scenario(
            "happy-path PPTX embeds at least one internal "
            "ppt/media/<name>.<png|jpg|jpeg> part with no external/"
            "file/data/scheme relationships",
            False, msg,
        )
    # Check the taxonomy preservation marker line.
    if "[PASS] taxonomy preservation check" not in outcome.stdout:
        return _Scenario(
            "happy-path stdout includes the [PASS] taxonomy "
            "preservation marker",
            False,
            f"stdout tail: {outcome.stdout.splitlines()[-10:]!r}",
        )
    return _Scenario(
        "happy path: 2-slide taxonomy bundle produces a validated "
        "PPTX whose ppt/media/ carries a native PNG/JPG/JPEG, no "
        "external relationships, and the taxonomy preservation gate "
        "fires",
        True,
    )


def _scenario_missing_allow_synthetic(td: Path) -> _Scenario:
    bundle = _materialize_bundle(
        td / "no_synth",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
    )
    ws = td / "no_synth_ws"
    out = td / "no_synth.pptx"
    args = _baseline_runner_args(
        bundle=bundle, workspace=ws, output=out, with_vocab=False,
    )
    # Remove --allow-synthetic-bytes to probe the explicit gate.
    args = [a for a in args if a != "--allow-synthetic-bytes"]
    outcome = _invoke_runner(args)
    ok = (
        outcome.exit_code != 0
        and "--allow-synthetic-bytes is REQUIRED" in outcome.stderr
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "negative: missing --allow-synthetic-bytes fails closed at the "
        "runner boundary; no workspace, no PPTX",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"stderr_tail={outcome.stderr.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_taxonomy_without_vocab(td: Path) -> _Scenario:
    bundle = _materialize_bundle(
        td / "tax_no_vocab",
        d_one_spec_body=_d_one_spec_body_with_taxonomy(),
    )
    ws = td / "tax_no_vocab_ws"
    out = td / "tax_no_vocab.pptx"
    args = _baseline_runner_args(
        bundle=bundle, workspace=ws, output=out, with_vocab=False,
    )
    outcome = _invoke_runner(args)
    ok = (
        outcome.exit_code != 0
        and "--descriptor-vocabulary" in outcome.stdout
                + outcome.stderr
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "negative: taxonomy-bearing --d-one-spec without "
        "--descriptor-vocabulary refused at the runner boundary "
        "before any subprocess fires",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"stderr_tail={outcome.stderr.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_invalid_text_policy(td: Path) -> _Scenario:
    spec_body = _d_one_spec_body_with_taxonomy()
    # Regex-shape valid but not in image_taxonomy.text_policy.allowed_values.
    spec_body["requests"][0]["text_policy"] = "loud_text"
    bundle = _materialize_bundle(
        td / "bad_text_policy", d_one_spec_body=spec_body,
    )
    ws = td / "bad_text_policy_ws"
    out = td / "bad_text_policy.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "text_policy" in combined
        and not out.exists()
    )
    return _Scenario(
        "negative: --d-one-spec carries a text_policy value outside "
        "image_taxonomy.text_policy.allowed_values; done_image_adapter "
        "rejects and the runner aborts",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"text_policy_in_output="
         f"{'text_policy' in combined}, "
         f"tail={combined.splitlines()[-10:]!r}")
        if not ok else "",
    )


def _scenario_invalid_subject_domain(td: Path) -> _Scenario:
    spec_body = _d_one_spec_body_with_taxonomy()
    spec_body["requests"][0]["subject_domain"] = "consumer_faces"
    bundle = _materialize_bundle(
        td / "bad_subject_domain", d_one_spec_body=spec_body,
    )
    ws = td / "bad_subject_domain_ws"
    out = td / "bad_subject_domain.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "subject_domain" in combined
        and not out.exists()
    )
    return _Scenario(
        "negative: --d-one-spec carries a subject_domain value outside "
        "image_taxonomy.subject_domain.allowed_values; "
        "done_image_adapter rejects and the runner aborts",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"subject_domain_in_output="
         f"{'subject_domain' in combined}, "
         f"tail={combined.splitlines()[-10:]!r}")
        if not ok else "",
    )


def _scenario_editable_text_in_prompt_refused(td: Path) -> _Scenario:
    """Editable-text wording (`slide title` / `body copy` / `exact
    text`) embedded in a prompt is refused by ``done_image_adapter``
    regardless of ``text_policy`` — such copy must live in the native
    SVG / PPT text layer, never baked into the raster. The runner
    must abort before any production workspace or PPTX is created.
    Uses a no-taxonomy spec so the rule fires on its universal path,
    not via the policy-aware gate."""
    spec_body = _d_one_spec_body_without_taxonomy()
    spec_body["requests"][0]["prompt"] = (
        "abstract geometric pattern that embeds the slide title text"
    )
    bundle = _materialize_bundle(
        td / "editable_text", d_one_spec_body=spec_body,
    )
    ws = td / "editable_text_ws"
    out = td / "editable_text.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out, with_vocab=False,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "editable-text wording" in combined
        and "'slide title'" in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "negative: prompt with editable-text wording ('slide title') "
        "is refused by done_image_adapter before any production "
        "workspace or PPTX is created",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-10:]!r}")
        if not ok else "",
    )


def _scenario_no_text_policy_visible_text_refused(td: Path) -> _Scenario:
    """Under ``text_policy='no_text'`` an in-image-text request like
    ``include text`` is self-contradictory; ``done_image_adapter``
    refuses and the runner must abort before any production workspace
    or PPTX is created."""
    spec_body = _d_one_spec_body_with_taxonomy()
    spec_body["requests"][0]["prompt"] = (
        "abstract geometric pattern, please include text inside it"
    )
    bundle = _materialize_bundle(
        td / "no_text_visible", d_one_spec_body=spec_body,
    )
    ws = td / "no_text_visible_ws"
    out = td / "no_text_visible.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "in-image-text wording" in combined
        and "text_policy='no_text'" in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "negative: prompt with `include text` under "
        "text_policy='no_text' is refused by done_image_adapter "
        "before any production workspace or PPTX is created",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-10:]!r}")
        if not ok else "",
    )


def _scenario_boundary_safe_text_phrases_pass(td: Path) -> _Scenario:
    """Boundary-safe phrases — ``image texture``, ``textured paper``,
    ``context lighting``, ``texture pattern`` — embedded in a prompt
    under ``text_policy='no_text'`` must NOT trip the policy-aware
    in-image-text gate. The deny list's ``image text`` / ``with text``
    literals use word boundaries, so legitimate image-generation
    wording that merely contains the same character prefix slides
    past. The chain must complete and the PPTX must embed an
    internal PNG / JPG / JPEG with no external relationships."""
    spec_body = _d_one_spec_body_with_taxonomy()
    spec_body["requests"][0]["prompt"] = (
        "abstract geometric pattern with image texture, "
        "textured paper backdrop, soft context lighting, "
        "and a subtle texture pattern, no logo"
    )
    bundle = _materialize_bundle(
        td / "boundary_safe", d_one_spec_body=spec_body,
    )
    ws = td / "boundary_safe_ws"
    out = td / "boundary_safe.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    if outcome.exit_code != 0:
        return _Scenario(
            "positive: prompt with boundary-safe phrases ('image "
            "texture' / 'textured paper' / 'context lighting' / "
            "'texture pattern') under text_policy='no_text' passes "
            "the chain and produces a PPTX with internal media",
            False,
            f"rc={outcome.exit_code}; "
            f"stderr tail: {outcome.stderr.splitlines()[-10:]!r}; "
            f"stdout tail: {outcome.stdout.splitlines()[-10:]!r}",
        )
    if not out.is_file() or out.is_symlink():
        return _Scenario(
            "positive: boundary-safe PPTX exists as regular non-"
            "symlink file",
            False, f"out={out}, is_file={out.is_file()}",
        )
    ok, msg = _pptx_embeds_internal_media_only(out)
    if not ok:
        return _Scenario(
            "positive: boundary-safe PPTX embeds at least one "
            "internal ppt/media/<name>.<png|jpg|jpeg> part with no "
            "external/file/data/scheme relationships",
            False, msg,
        )
    return _Scenario(
        "positive: prompt with boundary-safe phrases ('image "
        "texture' / 'textured paper' / 'context lighting' / "
        "'texture pattern') under text_policy='no_text' passes the "
        "chain and produces a PPTX whose ppt/media/ carries a "
        "native PNG/JPG/JPEG with no external relationships",
        True,
    )


def _scenario_plan_schema_version_locked(td: Path) -> _Scenario:
    """The schema_version invariant is NOT directly probeable from the
    runner CLI — the runner always invokes done_image_adapter, which
    writes schema_version=4 (the value LOCKED_PLAN_SCHEMA_VERSION
    holds — bumped from 3 alongside the optional per-request
    placement_role field). We probe indirectly: a happy-path run must
    leave a [PASS] taxonomy preservation marker AND its stdout must
    name `plan.schema_version==4` (the assertion line in the formatted
    output)."""
    bundle = _materialize_bundle(
        td / "schema_lock",
        d_one_spec_body=_d_one_spec_body_with_taxonomy(),
    )
    ws = td / "schema_lock_ws"
    out = td / "schema_lock.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    sv_marker = f"plan.schema_version=={LOCKED_PLAN_SCHEMA_VERSION}"
    ok = (
        outcome.exit_code == 0
        and sv_marker in outcome.stdout
        and "[PASS] taxonomy preservation check" in outcome.stdout
    )
    return _Scenario(
        f"negative (indirect): produced d_one_adapter_plan.json carries "
        f"schema_version=={LOCKED_PLAN_SCHEMA_VERSION}; the runner "
        f"refuses to forward a downgrade",
        ok,
        (f"rc={outcome.exit_code}, "
         f"sv_marker={sv_marker in outcome.stdout}, "
         f"pass_marker="
         f"{'[PASS] taxonomy preservation check' in outcome.stdout}, "
         f"tail={outcome.stdout.splitlines()[-10:]!r}")
        if not ok else "",
    )


def _scenario_request_id_mismatch(td: Path) -> _Scenario:
    spec_body = _d_one_spec_body_with_taxonomy()
    spec_body["requests"][0]["id"] = "not_in_manifest"
    bundle = _materialize_bundle(
        td / "id_mismatch", d_one_spec_body=spec_body,
    )
    ws = td / "id_mismatch_ws"
    out = td / "id_mismatch.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "not_in_manifest" in combined
        and not out.exists()
    )
    return _Scenario(
        "negative: --d-one-spec request id not present in the "
        "image_manifest_spec entries; done_image_adapter rejects",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"tail={combined.splitlines()[-10:]!r}")
        if not ok else "",
    )


def _scenario_unsafe_local_path(td: Path) -> _Scenario:
    bundle = _materialize_bundle(
        td / "unsafe_lp",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
    )
    # Replace image-manifest-spec with one whose local_path uses a URI
    # scheme — the runner's d_one_local gate will accept it but the
    # downstream init_image_manifest / materialize gates will refuse.
    bad_manifest = bundle["image_manifest_spec"]
    body = json.loads(bad_manifest.read_text())
    body["images"][0]["local_path"] = "http://attacker/x.png"
    _write_json(bad_manifest, body)

    ws = td / "unsafe_lp_ws"
    out = td / "unsafe_lp.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out, with_vocab=False,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and not out.exists()
        # Either materialize OR init_image_manifest will refuse this.
        # We don't pin the wording too tightly because the diagnostic
        # comes from a downstream tool; we only require that the run
        # aborts and the unsafe value appears in the output (proves the
        # refusal cited the offending local_path).
        and ("http://attacker" in combined or "local_path" in combined)
    )
    return _Scenario(
        "negative: image_manifest_spec local_path with a URI scheme "
        "(`http://...`) is refused by the downstream chain; no PPTX "
        "is produced",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"tail={combined.splitlines()[-10:]!r}")
        if not ok else "",
    )


def _scenario_symlinked_output(td: Path) -> _Scenario:
    bundle = _materialize_bundle(
        td / "sym_out",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
    )
    ws = td / "sym_out_ws"
    out = td / "sym_out.pptx"
    # Pre-create --output as a symlink so the runner's symlink gate
    # fires before any subprocess.
    (td / "real_target.pptx").write_bytes(b"")
    out.symlink_to(td / "real_target.pptx")
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out, with_vocab=False,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "symlink" in combined
        and not ws.exists()
    )
    return _Scenario(
        "negative: symlinked --output is refused at the runner boundary "
        "before any subprocess fires",
        ok,
        (f"rc={outcome.exit_code}, ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-10:]!r}")
        if not ok else "",
    )


def _scenario_symlinked_workspace(td: Path) -> _Scenario:
    bundle = _materialize_bundle(
        td / "sym_ws_bundle",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
    )
    real_ws_target = td / "real_ws_target_dir"
    real_ws_target.mkdir()
    ws = td / "sym_ws_link"
    ws.symlink_to(real_ws_target)
    out = td / "sym_ws.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out, with_vocab=False,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "symlink" in combined
        and not out.exists()
    )
    return _Scenario(
        "negative: symlinked --workspace is refused at the runner "
        "boundary before any subprocess fires",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"tail={combined.splitlines()[-10:]!r}")
        if not ok else "",
    )


def _scenario_symlinked_report_dir(td: Path) -> _Scenario:
    bundle = _materialize_bundle(
        td / "sym_report_bundle",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
    )
    ws = td / "sym_report_ws"
    out = td / "sym_report.pptx"
    real_report_target = td / "real_report_target_dir"
    real_report_target.mkdir()
    report = td / "sym_report_link"
    report.symlink_to(real_report_target)
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out,
        report_dir=report, with_vocab=False,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "symlink" in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "negative: symlinked --report-dir is refused at the runner "
        "boundary before any subprocess fires",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-10:]!r}")
        if not ok else "",
    )


def _snapshot_pycache() -> dict[str, bytes]:
    """Flat path -> bytes map of every .pyc under
    ``REPO_ROOT/scripts/__pycache__/``. Used by the no-repo-write
    scenario to prove the runner does not silently land a .pyc on a
    caller who forgot ``PYTHONDONTWRITEBYTECODE=1`` — the in-script
    ``sys.dont_write_bytecode = True`` flip is supposed to close that
    hole unconditionally."""
    pycache = SCRIPTS_DIR / "__pycache__"
    snap: dict[str, bytes] = {}
    if not pycache.is_dir():
        return snap
    for p in sorted(pycache.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(pycache)
        try:
            snap[str(rel)] = p.read_bytes()
        except OSError:
            pass
    return snap


def _scenario_no_repo_bytecode_write(td: Path) -> _Scenario:
    """Run the runner with ``PYTHONDONTWRITEBYTECODE`` REMOVED from the
    env so the parent Python is free to write .pyc files for any module
    it imports. The runner's in-script ``sys.dont_write_bytecode = True``
    flip is supposed to close the hole BEFORE the first-party
    ``validate_scaffold`` import lands a .pyc under
    ``scripts/__pycache__/``. Take a flat-bytes snapshot of
    ``scripts/__pycache__/`` before and after; any change (new entry,
    mutated entry, deleted entry) fails the scenario."""
    bundle = _materialize_bundle(
        td / "no_pyc",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
    )
    ws = td / "no_pyc_ws"
    out = td / "no_pyc.pptx"
    before = _snapshot_pycache()
    # Strip PYTHONDONTWRITEBYTECODE from the subprocess env so the in-
    # script flip is the ONLY thing keeping bytecode off disk.
    base_env = {k: v for k, v in os.environ.items()
                if k != "PYTHONDONTWRITEBYTECODE"}
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
    ] + _baseline_runner_args(
        bundle=bundle, workspace=ws, output=out, with_vocab=False,
    )
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=base_env,
    )
    after = _snapshot_pycache()
    drift_paths = [
        k for k in sorted(set(before) | set(after))
        if before.get(k) != after.get(k)
    ]
    ok = (
        proc.returncode == 0
        and out.is_file()
        and not drift_paths
    )
    return _Scenario(
        "no-repo-write: runner invoked without PYTHONDONTWRITEBYTECODE=1 "
        "in env does NOT mutate scripts/__pycache__/ (the in-script "
        "sys.dont_write_bytecode=True flip closes the hole "
        "unconditionally)",
        ok,
        (f"rc={proc.returncode}, out_exists={out.exists()}, "
         f"drift_paths={drift_paths!r}, "
         f"stderr_tail={proc.stderr.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_approved_custom_descriptor(td: Path) -> _Scenario:
    """An APPROVED custom_descriptor — a value present in the supplied
    vocab's ``custom_descriptors[]`` allow-list — passes the chain
    end-to-end. The produced PPTX must embed an internal PNG/JPG/JPEG
    media part with no external relationships, AND the produced plan
    must carry the spec's custom_descriptor value byte-identical."""
    spec_body = _d_one_spec_body_with_taxonomy()
    spec_body["requests"][0]["custom_descriptor"] = "hero_centered_motif"
    bundle = _materialize_bundle(
        td / "cd_approved", d_one_spec_body=spec_body,
    )
    ws = td / "cd_approved_ws"
    out = td / "cd_approved.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    if outcome.exit_code != 0:
        return _Scenario(
            "custom_descriptor (mock chain): APPROVED value matching "
            "vocab.custom_descriptors[] passes end-to-end",
            False,
            f"rc={outcome.exit_code}; "
            f"stderr tail: {outcome.stderr.splitlines()[-10:]!r}; "
            f"stdout tail: {outcome.stdout.splitlines()[-10:]!r}",
        )
    if not out.is_file() or out.is_symlink():
        return _Scenario(
            "custom_descriptor: approved-value PPTX exists as regular "
            "non-symlink file",
            False, f"out={out}, is_file={out.is_file()}",
        )
    ok, msg = _pptx_embeds_internal_media_only(out)
    if not ok:
        return _Scenario(
            "custom_descriptor: approved-value PPTX embeds at least "
            "one internal ppt/media/<name>.<png|jpg|jpeg> part with "
            "no external/file/data/scheme relationships",
            False, msg,
        )
    if "[PASS] taxonomy preservation check" not in outcome.stdout:
        return _Scenario(
            "custom_descriptor: approved-value run leaves the [PASS] "
            "taxonomy preservation marker on stdout",
            False,
            f"stdout tail: {outcome.stdout.splitlines()[-10:]!r}",
        )
    return _Scenario(
        "custom_descriptor (mock chain): APPROVED value matching "
        "vocab.custom_descriptors[] passes end-to-end; PPTX embeds "
        "internal media, no external relationships, taxonomy + "
        "custom_descriptor preservation gate fires",
        True,
    )


def _scenario_unapproved_custom_descriptor(td: Path) -> _Scenario:
    """An UNAPPROVED custom_descriptor — a value NOT in the supplied
    vocab's ``custom_descriptors[]`` allow-list — must be refused by
    ``done_image_adapter`` BEFORE any production workspace or PPTX is
    created. The value is regex-shape valid (lowercase identifier, no
    forbidden tokens) so the schema regex would NOT trip; the runtime
    allow-list check is the only gate that closes it. The chosen value
    ``rogue_motif`` is deliberately not added to the vocab body."""
    spec_body = _d_one_spec_body_with_taxonomy()
    spec_body["requests"][0]["custom_descriptor"] = "rogue_motif"
    bundle = _materialize_bundle(
        td / "cd_unapproved", d_one_spec_body=spec_body,
    )
    ws = td / "cd_unapproved_ws"
    out = td / "cd_unapproved.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "custom_descriptor" in combined
        and "rogue_motif" in combined
        and "custom_descriptors[].value allow-list" in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "custom_descriptor (mock chain): UNAPPROVED value is refused "
        "by done_image_adapter before any production workspace or "
        "PPTX is created",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-10:]!r}")
        if not ok else "",
    )


_PLACEMENT_ROLE_OVERLAY_PROMPT = (
    "abstract gradient pattern that leaves calm space on the right "
    "for the title overlay; soft edges, no text"
)
_PLACEMENT_ROLE_ORDINARY_PROMPT = (
    "ordinary schematic diagram of a generic process motif; soft "
    "edges; no text"
)


def _scenario_placement_role_hero_overlay_passes(td: Path) -> _Scenario:
    """``placement_role='hero_page'`` plus an overlay-reservation
    prompt (calm space / title overlay) passes the chain end-to-end.
    The produced plan persists placement_role byte-identical."""
    spec_body = _d_one_spec_body_with_taxonomy()
    spec_body["requests"][0]["prompt"] = _PLACEMENT_ROLE_OVERLAY_PROMPT
    spec_body["requests"][0]["placement_role"] = "hero_page"
    bundle = _materialize_bundle(
        td / "pr_hero_ok", d_one_spec_body=spec_body,
    )
    ws = td / "pr_hero_ok_ws"
    out = td / "pr_hero_ok.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    if outcome.exit_code != 0:
        return _Scenario(
            "placement_role=hero_page + overlay-reservation prompt "
            "passes the mock chain end-to-end",
            False,
            f"rc={outcome.exit_code}; "
            f"stderr tail: {outcome.stderr.splitlines()[-10:]!r}; "
            f"stdout tail: {outcome.stdout.splitlines()[-10:]!r}",
        )
    if not out.is_file() or out.is_symlink():
        return _Scenario(
            "placement_role=hero_page PPTX exists as regular non-"
            "symlink file",
            False, f"out={out}, is_file={out.is_file()}",
        )
    ok, msg = _pptx_embeds_internal_media_only(out)
    if not ok:
        return _Scenario(
            "placement_role=hero_page PPTX embeds at least one "
            "internal ppt/media/<name>.<png|jpg|jpeg> part with no "
            "external/file/data/scheme relationships",
            False, msg,
        )
    if "[PASS] taxonomy preservation check" not in outcome.stdout:
        return _Scenario(
            "placement_role=hero_page run leaves the [PASS] taxonomy "
            "preservation marker on stdout",
            False,
            f"stdout tail: {outcome.stdout.splitlines()[-10:]!r}",
        )
    return _Scenario(
        "placement_role=hero_page + overlay-reservation cue passes "
        "end-to-end; PPTX embeds internal media, placement_role "
        "preservation gate fires",
        True,
    )


def _scenario_placement_role_local_overlay_refused(td: Path) -> _Scenario:
    """``placement_role='local_region'`` plus an overlay-reservation
    prompt MUST be refused by ``done_image_adapter`` BEFORE any
    production workspace or PPTX is created. SVG/PPT text-overlay
    reservation belongs to hero-page images, not local region-block
    images."""
    spec_body = _d_one_spec_body_with_taxonomy()
    spec_body["requests"][0]["prompt"] = _PLACEMENT_ROLE_OVERLAY_PROMPT
    spec_body["requests"][0]["placement_role"] = "local_region"
    bundle = _materialize_bundle(
        td / "pr_local_overlay", d_one_spec_body=spec_body,
    )
    ws = td / "pr_local_overlay_ws"
    out = td / "pr_local_overlay.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "overlay-reservation wording" in combined
        and "placement_role='hero_page'" in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "placement_role=local_region + overlay-reservation cue is "
        "REFUSED by done_image_adapter before any production "
        "workspace or PPTX is created (SVG/PPT text-overlay "
        "reservation belongs to hero-page images, not local region-"
        "block images)",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-10:]!r}")
        if not ok else "",
    )


def _scenario_placement_role_omitted_overlay_refused(td: Path) -> _Scenario:
    """Omitting ``placement_role`` while the prompt carries an overlay-
    reservation cue MUST also fail. Omitted role defaults to default-
    deny so a caller cannot bypass the gate by simply dropping the
    field."""
    spec_body = _d_one_spec_body_with_taxonomy()
    spec_body["requests"][0]["prompt"] = _PLACEMENT_ROLE_OVERLAY_PROMPT
    # placement_role intentionally omitted; the taxonomy block is
    # otherwise populated (so --descriptor-vocabulary is forwarded).
    bundle = _materialize_bundle(
        td / "pr_omitted_overlay", d_one_spec_body=spec_body,
    )
    ws = td / "pr_omitted_overlay_ws"
    out = td / "pr_omitted_overlay.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "overlay-reservation wording" in combined
        and "placement_role='hero_page'" in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "placement_role omitted + overlay-reservation cue is REFUSED "
        "by done_image_adapter before any production workspace or "
        "PPTX is created (default-deny so dropping the field does "
        "not bypass the gate)",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-10:]!r}")
        if not ok else "",
    )


def _scenario_placement_role_local_ordinary_passes(td: Path) -> _Scenario:
    """``placement_role='local_region'`` plus an ORDINARY schematic /
    diagram / accent / texture / scene prompt with NO overlay-
    reservation cues passes end-to-end. Proves the gate is narrow."""
    spec_body = _d_one_spec_body_with_taxonomy()
    spec_body["requests"][0]["prompt"] = _PLACEMENT_ROLE_ORDINARY_PROMPT
    spec_body["requests"][0]["placement_role"] = "local_region"
    bundle = _materialize_bundle(
        td / "pr_local_ordinary", d_one_spec_body=spec_body,
    )
    ws = td / "pr_local_ordinary_ws"
    out = td / "pr_local_ordinary.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    if outcome.exit_code != 0:
        return _Scenario(
            "placement_role=local_region + ORDINARY prompt passes "
            "end-to-end (the gate is narrow, not a blanket ban on "
            "local_region)",
            False,
            f"rc={outcome.exit_code}; "
            f"stderr tail: {outcome.stderr.splitlines()[-10:]!r}; "
            f"stdout tail: {outcome.stdout.splitlines()[-10:]!r}",
        )
    if not out.is_file() or out.is_symlink():
        return _Scenario(
            "placement_role=local_region ordinary PPTX exists as "
            "regular non-symlink file",
            False, f"out={out}, is_file={out.is_file()}",
        )
    ok, msg = _pptx_embeds_internal_media_only(out)
    if not ok:
        return _Scenario(
            "placement_role=local_region ordinary PPTX embeds at "
            "least one internal ppt/media/<name>.<png|jpg|jpeg> part "
            "with no external/file/data/scheme relationships",
            False, msg,
        )
    return _Scenario(
        "placement_role=local_region + ORDINARY schematic prompt "
        "passes end-to-end; PPTX embeds internal media, no external "
        "relationships, placement_role preservation gate fires",
        True,
    )


# ---------------------------------------------------------------------------
# --bundle path scenarios. These probe the canonical bundle layout under
# the --bundle shortcut. The helpers below materialize a bundle dir
# whose layout matches the _resolve_bundle contract (source.md /
# brief.json / plan_spec.json / design_system_spec.json /
# slide_specs/ / image_manifest_spec.json / d_one_spec.json /
# optional descriptor_vocabulary.json), then invoke the runner with
# --bundle <dir> instead of the per-input explicit flags.
# ---------------------------------------------------------------------------


def _brief_body(*, extras: dict | None = None) -> dict:
    """Default synthetic brief.json body. ``extras`` overrides /
    augments the result (used by the malformed-value-type scenarios)."""
    body = {
        "title": _SYNTHETIC_TITLE,
        "audience": _SYNTHETIC_AUDIENCE,
        "objective": _SYNTHETIC_OBJECTIVE,
        "tone": _SYNTHETIC_TONE,
        "language": _SYNTHETIC_LANGUAGE,
        "approximate_slide_count": _SYNTHETIC_APPROXIMATE_SLIDE_COUNT,
        "source_id": _SYNTHETIC_SOURCE_ID,
    }
    if extras:
        body.update(extras)
    return body


def _materialize_canonical_bundle(
    bundle_root: Path,
    *,
    d_one_spec_body: dict,
    include_vocab: bool = True,
    include_design_system_spec: bool = True,
    brief_body: dict | None = None,
    image_manifest_body: dict | None = None,
) -> Path:
    """Materialize the canonical --bundle layout under ``bundle_root``
    and return the resolved bundle path. Mirrors the per-input shapes
    the resolver expects; switches let scenarios poke specific holes
    (missing vocab, missing design_system_spec, malformed brief)."""
    bundle_root.mkdir(parents=True, exist_ok=True)
    (bundle_root / "source.md").write_text(_source_md_text())
    _write_json(
        bundle_root / "brief.json",
        brief_body if brief_body is not None else _brief_body(),
    )
    _write_json(bundle_root / "plan_spec.json", _plan_spec_body())
    if include_design_system_spec:
        _write_json(
            bundle_root / "design_system_spec.json", _design_system_body(),
        )
    (bundle_root / "slide_specs").mkdir(exist_ok=True)
    _write_json(
        bundle_root / "slide_specs" / "01_cover.json", _slide_cover_body(),
    )
    _write_json(
        bundle_root / "slide_specs" / "02_conclusion.json",
        _slide_conclusion_body(),
    )
    _write_json(
        bundle_root / "image_manifest_spec.json",
        image_manifest_body if image_manifest_body is not None
        else _image_manifest_body(),
    )
    _write_json(bundle_root / "d_one_spec.json", d_one_spec_body)
    if include_vocab:
        _write_json(
            bundle_root / "descriptor_vocabulary.json",
            _descriptor_vocabulary_body(),
        )
    return bundle_root


def _bundle_runner_args(
    *,
    bundle: Path,
    workspace: Path,
    output: Path,
    report_dir: Path | None = None,
    descriptor_vocabulary: Path | None = None,
    with_allow_synthetic: bool = True,
) -> list[str]:
    args = [
        "--bundle", str(bundle),
        "--workspace", str(workspace),
        "--template-root", str(TEMPLATE_ROOT),
        "--output", str(output),
    ]
    if with_allow_synthetic:
        args.append("--allow-synthetic-bytes")
    if descriptor_vocabulary is not None:
        args += ["--descriptor-vocabulary", str(descriptor_vocabulary)]
    if report_dir is not None:
        args += ["--report-dir", str(report_dir)]
    return args


def _scenario_bundle_happy_path(td: Path) -> _Scenario:
    """``--bundle`` happy path: the canonical layout (source.md +
    brief.json + plan_spec.json + design_system_spec.json +
    slide_specs/ + image_manifest_spec.json + d_one_spec.json +
    descriptor_vocabulary.json) drives the mock chain end-to-end and
    produces a PPTX whose ppt/media/ carries an embeddable PNG/JPG/JPEG
    with no external relationships and whose stdout fires the [PASS]
    taxonomy preservation marker."""
    bundle = _materialize_canonical_bundle(
        td / "bundle_happy",
        d_one_spec_body=_d_one_spec_body_with_taxonomy(),
    )
    ws = td / "bundle_happy_ws"
    out = td / "bundle_happy.pptx"
    report = td / "bundle_happy_report"
    outcome = _invoke_runner(_bundle_runner_args(
        bundle=bundle, workspace=ws, output=out, report_dir=report,
    ))
    if outcome.exit_code != 0:
        return _Scenario(
            "--bundle happy path: canonical layout drives the mock "
            "chain end-to-end and produces a validated PPTX",
            False,
            f"rc={outcome.exit_code}; "
            f"stderr tail: {outcome.stderr.splitlines()[-10:]!r}; "
            f"stdout tail: {outcome.stdout.splitlines()[-10:]!r}",
        )
    if not out.is_file() or out.is_symlink():
        return _Scenario(
            "--bundle happy path PPTX exists as regular non-symlink file",
            False, f"out={out}, is_file={out.is_file()}",
        )
    ok, msg = _pptx_embeds_internal_media_only(out)
    if not ok:
        return _Scenario(
            "--bundle happy-path PPTX embeds at least one internal "
            "ppt/media/<name>.<png|jpg|jpeg> part with no external/"
            "file/data/scheme relationships",
            False, msg,
        )
    if "[PASS] taxonomy preservation check" not in outcome.stdout:
        return _Scenario(
            "--bundle happy-path stdout includes the [PASS] taxonomy "
            "preservation marker",
            False,
            f"stdout tail: {outcome.stdout.splitlines()[-10:]!r}",
        )
    return _Scenario(
        "--bundle happy path: canonical bundle (source.md / brief.json "
        "/ plan_spec.json / design_system_spec.json / slide_specs/ / "
        "image_manifest_spec.json / d_one_spec.json / "
        "descriptor_vocabulary.json) produces a validated PPTX whose "
        "ppt/media/ carries a native PNG/JPG/JPEG and whose stdout "
        "fires the taxonomy preservation gate",
        True,
    )


def _scenario_bundle_uri_path(td: Path) -> _Scenario:
    """``--bundle file://...`` (URI-shaped) is refused at the runner
    boundary before any subprocess fires."""
    ws = td / "bundle_uri_ws"
    out = td / "bundle_uri.pptx"
    outcome = _invoke_runner(_bundle_runner_args(
        bundle=Path("file:///tmp/bundle_uri_shape"),
        workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "URI" in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "--bundle URI-shaped path (file://...) is refused before any "
        "subprocess fires",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_bundle_symlinked_dir(td: Path) -> _Scenario:
    """A symlinked --bundle directory is refused even when the link
    points at a real bundle. Symlinks let an attacker who controls the
    bundle path redirect reads."""
    real = _materialize_canonical_bundle(
        td / "bundle_sym_dir_real",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
        include_vocab=False,
    )
    link = td / "bundle_sym_dir_link"
    link.symlink_to(real)
    ws = td / "bundle_sym_dir_ws"
    out = td / "bundle_sym_dir.pptx"
    outcome = _invoke_runner(_bundle_runner_args(
        bundle=link, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "symlink" in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "--bundle dir that is itself a symlink is refused at the "
        "runner boundary before any subprocess fires",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_bundle_symlinked_file(td: Path) -> _Scenario:
    """A symlinked file inside the bundle is refused even when the
    target points at a real spec file. The resolver refuses any
    symlinked canonical entry."""
    bundle = _materialize_canonical_bundle(
        td / "bundle_sym_file",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
        include_vocab=False,
    )
    # Replace brief.json with a symlink to a sibling real brief file.
    brief = bundle / "brief.json"
    real_target = td / "real_brief.json"
    _write_json(real_target, _brief_body())
    brief.unlink()
    brief.symlink_to(real_target)
    ws = td / "bundle_sym_file_ws"
    out = td / "bundle_sym_file.pptx"
    outcome = _invoke_runner(_bundle_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "symlink" in combined
        and "brief.json" in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "--bundle file entry (brief.json) that is itself a symlink is "
        "refused at the runner boundary before any subprocess fires",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_bundle_symlinked_parent(td: Path) -> _Scenario:
    """A real bundle reached through a symlinked PARENT directory is
    refused at the resolver boundary. Regression gate for the Codex
    review repro: a per-entry ``is_symlink()`` check passes (the bundle
    dir itself and every named entry inside it are non-symlink) but the
    parent segment ``link_parent`` is a symlink to the real holder."""
    real_parent = td / "bundle_sym_parent_real"
    real_parent.mkdir()
    real_bundle = _materialize_canonical_bundle(
        real_parent / "synthetic_mock_image_trial",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
        include_vocab=False,
    )
    link_parent = td / "bundle_sym_parent_link"
    link_parent.symlink_to(real_parent)
    bundle_via_link = link_parent / "synthetic_mock_image_trial"
    ws = td / "bundle_sym_parent_ws"
    out = td / "bundle_sym_parent.pptx"
    outcome = _invoke_runner(_bundle_runner_args(
        bundle=bundle_via_link, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "parent" in combined
        and "symlink" in combined
        and not out.exists()
        and not ws.exists()
        # Real bundle bytes survive the failure (no destructive cleanup).
        and (real_bundle / "brief.json").is_file()
    )
    return _Scenario(
        "--bundle reached through a symlinked PARENT directory "
        "(link_parent -> real_parent) is refused at the resolver "
        "boundary before any subprocess fires; no workspace, no PPTX",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"real_bundle_intact="
         f"{(real_bundle / 'brief.json').is_file()}, "
         f"tail={combined.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_bundle_parent_traversal_bypass(td: Path) -> _Scenario:
    """A ``--bundle`` path that uses ``..`` to ``cancel out`` a
    symlinked component is refused at the resolver boundary.

    Regression gate for the second Codex review finding: the
    lexical-absolute parent walk uses ``os.path.abspath`` which
    collapses ``..`` lexically without following symlinks, so a path
    like ``<td>/parent_dir/link/../atk_bundle`` (where ``link`` is a
    symlink to a decoy directory) collapses lexically to
    ``<td>/parent_dir/atk_bundle`` — the lexical chain shows no
    symlinks and the symlinked-ancestor walk would silently pass.
    POSIX resolution of ``link/..`` follows the link to the decoy
    and then steps up to the decoy's parent (the same ``<td>``),
    so the runner ends up reading from ``<td>/atk_bundle`` (a real
    bundle the test placed there to prove the path was actually
    followed). The ``..``-refusal closes the bypass before any
    subprocess fires."""
    attacker_bundle = _materialize_canonical_bundle(
        td / "atk_bundle",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
        include_vocab=False,
    )
    decoy = td / "dotdot_decoy"
    decoy.mkdir()
    parent_dir = td / "dotdot_parent"
    parent_dir.mkdir()
    (parent_dir / "link").symlink_to(decoy)
    # Lexical: <td>/dotdot_parent/atk_bundle (no symlink anywhere).
    # POSIX: follow link to <td>/dotdot_decoy, .. to <td>, then
    # atk_bundle → <td>/atk_bundle (the real attacker bundle).
    bundle_arg = parent_dir / "link" / ".." / "atk_bundle"
    ws = td / "dotdot_ws"
    out = td / "dotdot.pptx"
    outcome = _invoke_runner(_bundle_runner_args(
        bundle=bundle_arg, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "`..`" in combined
        and "refusing" in combined
        and not out.exists()
        and not ws.exists()
        and (attacker_bundle / "brief.json").is_file()
    )
    return _Scenario(
        "--bundle path with a `..` segment that cancels a symlinked "
        "component lexically while still following the symlink "
        "POSIX-ly is refused at the resolver boundary before any "
        "subprocess fires; no workspace, no PPTX",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"attacker_bundle_intact="
         f"{(attacker_bundle / 'brief.json').is_file()}, "
         f"tail={combined.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_bundle_symlinked_slide_spec_file(td: Path) -> _Scenario:
    """A symlinked JSON file INSIDE the bundle's ``slide_specs/`` is
    refused at the resolver boundary. Until now the resolver only
    checked the slide_specs/ directory itself; symlinked entries inside
    were only caught by init_slide_plans downstream. Failing at the
    runner boundary keeps the diagnostic local and avoids creating any
    staging workspace."""
    bundle = _materialize_canonical_bundle(
        td / "bundle_sym_slide_spec",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
        include_vocab=False,
    )
    # Replace 01_cover.json with a symlink to a real spec sibling.
    slide_path = bundle / "slide_specs" / "01_cover.json"
    real_target = td / "real_cover_spec.json"
    _write_json(real_target, _slide_cover_body())
    slide_path.unlink()
    slide_path.symlink_to(real_target)
    ws = td / "bundle_sym_slide_spec_ws"
    out = td / "bundle_sym_slide_spec.pptx"
    outcome = _invoke_runner(_bundle_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "slide_specs/01_cover.json" in combined
        and "symlink" in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "--bundle slide_specs/<name>.json that is itself a symlink is "
        "refused at the resolver boundary before any subprocess fires",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_bundle_symlinked_vocab(td: Path) -> _Scenario:
    """A symlinked optional ``descriptor_vocabulary.json`` inside the
    bundle is refused at the resolver boundary. The existing per-entry
    check on the vocab path was always present; this scenario pins it
    so a future refactor cannot regress it silently."""
    bundle = _materialize_canonical_bundle(
        td / "bundle_sym_vocab",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
        # include_vocab=True so the canonical layout writes the real
        # vocab file; we then replace it with a symlink to a sibling.
        include_vocab=True,
    )
    vocab_path = bundle / "descriptor_vocabulary.json"
    real_target = td / "real_vocab.json"
    _write_json(real_target, _descriptor_vocabulary_body())
    vocab_path.unlink()
    vocab_path.symlink_to(real_target)
    ws = td / "bundle_sym_vocab_ws"
    out = td / "bundle_sym_vocab.pptx"
    outcome = _invoke_runner(_bundle_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "descriptor_vocabulary.json" in combined
        and "symlink" in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "--bundle descriptor_vocabulary.json that is itself a symlink "
        "is refused at the resolver boundary before any subprocess "
        "fires",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_bundle_malformed_brief_value_type(td: Path) -> _Scenario:
    """``brief.json`` with a value of the wrong type fails without a
    Python traceback. Probes the integer type-guard on
    approximate_slide_count (JSON ``true`` would otherwise satisfy
    isinstance(True, int))."""
    bundle = _materialize_canonical_bundle(
        td / "bundle_bad_brief_type",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
        include_vocab=False,
        brief_body=_brief_body(extras={"approximate_slide_count": True}),
    )
    ws = td / "bundle_bad_brief_type_ws"
    out = td / "bundle_bad_brief_type.pptx"
    outcome = _invoke_runner(_bundle_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "approximate_slide_count" in combined
        and "must be an integer" in combined
        and "Traceback" not in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "--bundle brief.json with approximate_slide_count=true (JSON "
        "bool) is refused with a clean diagnostic (no Python "
        "traceback) before any subprocess fires",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"traceback_in_output={'Traceback' in combined}, "
         f"tail={combined.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_bundle_unknown_brief_field(td: Path) -> _Scenario:
    """``brief.json`` with a field not on the closed allow-list is
    refused at the resolver boundary."""
    bundle = _materialize_canonical_bundle(
        td / "bundle_unknown_brief",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
        include_vocab=False,
        brief_body=_brief_body(extras={"unexpected_field": "x"}),
    )
    ws = td / "bundle_unknown_brief_ws"
    out = td / "bundle_unknown_brief.pptx"
    outcome = _invoke_runner(_bundle_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "unknown field" in combined
        and "unexpected_field" in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "--bundle brief.json with an unknown field is refused at the "
        "resolver boundary before any subprocess fires",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_bundle_missing_vocab_with_taxonomy(td: Path) -> _Scenario:
    """A bundle WITHOUT ``descriptor_vocabulary.json`` whose
    ``d_one_spec.json`` carries taxonomy / custom_descriptor /
    placement_role fields AND no explicit ``--descriptor-vocabulary``
    flag MUST be refused at the runner boundary before any subprocess
    fires. The bundle does not paper over the vocab requirement."""
    bundle = _materialize_canonical_bundle(
        td / "bundle_no_vocab_with_tax",
        d_one_spec_body=_d_one_spec_body_with_taxonomy(),
        include_vocab=False,
    )
    ws = td / "bundle_no_vocab_with_tax_ws"
    out = td / "bundle_no_vocab_with_tax.pptx"
    outcome = _invoke_runner(_bundle_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "--descriptor-vocabulary" in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "--bundle without descriptor_vocabulary.json + d_one_spec "
        "carrying taxonomy fields + no explicit --descriptor-"
        "vocabulary flag is refused before any subprocess fires",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_bundle_mixed_explicit_flag(td: Path) -> _Scenario:
    """``--bundle`` mixed with an explicit per-input flag is refused at
    the runner boundary. The resolver's per-input outputs are the
    single source of truth; mixing modes is ambiguous."""
    bundle = _materialize_canonical_bundle(
        td / "bundle_mixed_flag",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
        include_vocab=False,
    )
    ws = td / "bundle_mixed_flag_ws"
    out = td / "bundle_mixed_flag.pptx"
    args = _bundle_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ) + ["--title", "Overridden Title"]
    outcome = _invoke_runner(args)
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "mutually exclusive" in combined
        and "--title" in combined
        and not out.exists()
        and not ws.exists()
    )
    return _Scenario(
        "--bundle mixed with an explicit per-input flag (--title) is "
        "refused at the runner boundary before any subprocess fires",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"ws_exists={ws.exists()}, "
         f"tail={combined.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_bundle_unsafe_local_path(td: Path) -> _Scenario:
    """An ``image_manifest_spec.json`` inside the bundle whose
    ``local_path`` carries a URI scheme is refused by the downstream
    chain; no PPTX is produced."""
    body = _image_manifest_body()
    body["images"][0]["local_path"] = "http://attacker/x.png"
    bundle = _materialize_canonical_bundle(
        td / "bundle_unsafe_lp",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
        include_vocab=False,
        image_manifest_body=body,
    )
    ws = td / "bundle_unsafe_lp_ws"
    out = td / "bundle_unsafe_lp.pptx"
    outcome = _invoke_runner(_bundle_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and not out.exists()
        and ("http://attacker" in combined or "local_path" in combined)
    )
    return _Scenario(
        "--bundle image_manifest_spec.local_path with a URI scheme "
        "(`http://...`) is refused by the downstream chain; no PPTX "
        "is produced",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"tail={combined.splitlines()[-10:]!r}")
        if not ok else "",
    )


def _scenario_bundle_id_mismatch(td: Path) -> _Scenario:
    """A bundle whose ``d_one_spec.json`` carries a request id that is
    not present in ``image_manifest_spec.json`` is refused by
    done_image_adapter."""
    spec_body = _d_one_spec_body_with_taxonomy()
    spec_body["requests"][0]["id"] = "not_in_manifest"
    bundle = _materialize_canonical_bundle(
        td / "bundle_id_mismatch",
        d_one_spec_body=spec_body,
    )
    ws = td / "bundle_id_mismatch_ws"
    out = td / "bundle_id_mismatch.pptx"
    outcome = _invoke_runner(_bundle_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    combined = outcome.combined
    ok = (
        outcome.exit_code != 0
        and "not_in_manifest" in combined
        and not out.exists()
    )
    return _Scenario(
        "--bundle d_one_spec request id not present in the bundle's "
        "image_manifest_spec is refused by done_image_adapter; no "
        "PPTX is produced",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}, "
         f"tail={combined.splitlines()[-10:]!r}")
        if not ok else "",
    )


def _scenario_bundle_no_repo_writes(td: Path) -> _Scenario:
    """``--bundle`` happy-path run without ``PYTHONDONTWRITEBYTECODE``
    in env does NOT mutate ``scripts/__pycache__/``. Same probe as
    ``_scenario_no_repo_bytecode_write`` but on the bundle path so the
    new code path is also covered."""
    bundle = _materialize_canonical_bundle(
        td / "bundle_no_pyc",
        d_one_spec_body=_d_one_spec_body_without_taxonomy(),
        include_vocab=False,
    )
    ws = td / "bundle_no_pyc_ws"
    out = td / "bundle_no_pyc.pptx"
    before = _snapshot_pycache()
    base_env = {k: v for k, v in os.environ.items()
                if k != "PYTHONDONTWRITEBYTECODE"}
    cmd = [
        sys.executable, str(Path(__file__).resolve()),
    ] + _bundle_runner_args(bundle=bundle, workspace=ws, output=out)
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=base_env,
    )
    after = _snapshot_pycache()
    drift = [
        k for k in sorted(set(before) | set(after))
        if before.get(k) != after.get(k)
    ]
    ok = (
        proc.returncode == 0
        and out.is_file()
        and not drift
    )
    return _Scenario(
        "--bundle no-repo-write: runner invoked without "
        "PYTHONDONTWRITEBYTECODE=1 in env on the --bundle path does "
        "NOT mutate scripts/__pycache__/",
        ok,
        (f"rc={proc.returncode}, out_exists={out.exists()}, "
         f"drift={drift!r}, "
         f"stderr_tail={proc.stderr.splitlines()[-5:]!r}")
        if not ok else "",
    )


def _scenario_failure_no_residue(td: Path) -> _Scenario:
    """After a downstream failure, no .pptx must exist at --output AND
    no staging tempdir must remain under the caller's tempdir."""
    # Drive a failure by passing a bad text_policy (already exercised
    # standalone above); here we additionally assert the no-residue
    # invariant on the same shape of failure.
    spec_body = _d_one_spec_body_with_taxonomy()
    spec_body["requests"][0]["text_policy"] = "loud_text"
    bundle = _materialize_bundle(
        td / "fail_residue", d_one_spec_body=spec_body,
    )
    ws = td / "fail_residue_ws"
    out = td / "fail_residue.pptx"
    outcome = _invoke_runner(_baseline_runner_args(
        bundle=bundle, workspace=ws, output=out,
    ))
    ok = (
        outcome.exit_code != 0
        and not out.exists()
    )
    return _Scenario(
        "failure cleanup: a downstream rejection leaves no .pptx at "
        "--output (the staging tempdir is auto-cleaned by "
        "tempfile.TemporaryDirectory even when the run aborts)",
        ok,
        (f"rc={outcome.exit_code}, out_exists={out.exists()}")
        if not ok else "",
    )


def _run_self_test() -> int:
    print("=== run_mock_image_pipeline self-test ===")
    if not TEMPLATE_ROOT.is_dir():
        print(
            f"FAIL: required template root not found: {TEMPLATE_ROOT}",
            file=sys.stderr,
        )
        return 1
    with tempfile.TemporaryDirectory(
        prefix="szh_run_mock_image_pipeline_selftest_",
    ) as raw_td:
        td = Path(raw_td)
        results: list[_Scenario] = [
            _scenario_happy_path(td),
            _scenario_missing_allow_synthetic(td),
            _scenario_taxonomy_without_vocab(td),
            _scenario_invalid_text_policy(td),
            _scenario_invalid_subject_domain(td),
            _scenario_editable_text_in_prompt_refused(td),
            _scenario_no_text_policy_visible_text_refused(td),
            _scenario_boundary_safe_text_phrases_pass(td),
            _scenario_plan_schema_version_locked(td),
            _scenario_approved_custom_descriptor(td),
            _scenario_unapproved_custom_descriptor(td),
            _scenario_placement_role_hero_overlay_passes(td),
            _scenario_placement_role_local_overlay_refused(td),
            _scenario_placement_role_omitted_overlay_refused(td),
            _scenario_placement_role_local_ordinary_passes(td),
            _scenario_request_id_mismatch(td),
            _scenario_unsafe_local_path(td),
            _scenario_symlinked_output(td),
            _scenario_symlinked_workspace(td),
            _scenario_symlinked_report_dir(td),
            _scenario_no_repo_bytecode_write(td),
            _scenario_bundle_happy_path(td),
            _scenario_bundle_uri_path(td),
            _scenario_bundle_symlinked_dir(td),
            _scenario_bundle_symlinked_file(td),
            _scenario_bundle_symlinked_parent(td),
            _scenario_bundle_parent_traversal_bypass(td),
            _scenario_bundle_symlinked_slide_spec_file(td),
            _scenario_bundle_symlinked_vocab(td),
            _scenario_bundle_malformed_brief_value_type(td),
            _scenario_bundle_unknown_brief_field(td),
            _scenario_bundle_missing_vocab_with_taxonomy(td),
            _scenario_bundle_mixed_explicit_flag(td),
            _scenario_bundle_unsafe_local_path(td),
            _scenario_bundle_id_mismatch(td),
            _scenario_bundle_no_repo_writes(td),
            _scenario_failure_no_residue(td),
        ]
        fails = 0
        for r in results:
            mark = "PASS" if r.ok else "FAIL"
            suffix = f" -- {r.detail}" if not r.ok and r.detail else ""
            print(f"  [{mark}] {r.name}{suffix}")
            if not r.ok:
                fails += 1
        print()
        if fails:
            print(
                f"FAIL: {fails} self-test scenario(s) did not behave "
                f"as expected."
            )
            return 1
    print(
        "OK (self-test): run_mock_image_pipeline behaves as expected "
        "on the happy path and every documented fail-closed probe. "
        "MOCK / STUB only — NOT real D-One integration."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
