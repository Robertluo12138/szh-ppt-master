#!/usr/bin/env python3
"""Pre-D-One local image-asset materialization gate.

Given a workspace that already ships a schema-valid
``image_manifest.json`` (typically authored directly or written by the
Stage-6 helper ``init_image_manifest.py``), this helper either **copies**
caller-supplied local PNG / JPG / JPEG asset bytes from ``--assets-dir``
into the workspace paths declared by each ``images[].local_path`` when
the target does not yet exist, or **verifies** the pre-existing target
in place when it does — in both cases the post-condition is that every
declared target is a regular non-symlink PNG / JPG / JPEG file whose
first bytes match the magic header for the declared extension.

The verify-or-copy semantics support two distinct workflows.
``init_image_manifest`` itself refuses to overwrite a pre-existing
``image_manifest.json``, so the two workflows do NOT chain through it —
each one stands on its own and the manifest must already be in place
(by either mechanism below) before materialize runs:

  - **Direct-author workflow (no init helper)**: the agent writes
    ``<workspace>/image_manifest.json`` directly (e.g. by copying an
    authored spec JSON verbatim into the workspace), places PNG / JPG /
    JPEG asset bytes under ``--assets-dir`` keyed by ``<id>.<ext>``,
    then runs materialize. The helper takes the **copy** branch for
    every declared target (no target exists yet), writes the bytes
    into ``<workspace>/<local_path>``, and ``init_image_manifest`` is
    NOT invoked in this path (it would refuse to overwrite the
    already-written manifest);
  - **init_image_manifest workflow (assets pre-placed)**: the agent
    places PNG / JPG / JPEG asset bytes directly at
    ``<workspace>/<local_path>`` for every declared image, then runs
    ``scripts/init_image_manifest.py --workspace ws --spec spec.json``
    (which requires every declared ``local_path`` to already resolve
    to an existing regular non-symlink file before it writes the
    manifest). materialize is then an OPTIONAL follow-up that takes
    the **verify-only** branch for every target — defense in depth,
    since ``init_image_manifest`` only checks that each declared
    ``local_path`` resolves to a regular file but does NOT check
    PNG / JPEG magic bytes. ``--assets-dir`` is typically empty in
    this workflow (or carries the same bytes the agent originally
    placed; either is fine).

Re-running the helper on a fully-materialized workspace (whichever
workflow produced it) with the same ``--assets-dir`` is idempotent:
every target hits the verify branch, nothing is copied, no manifest
field is mutated.

**This is the pre-D-One local asset gate, not D-One itself.** The helper
deliberately does NOT:

  - call D-One / Qoder / any public network / image generation / model
    API / image search / external service — the caller is responsible
    for the underlying asset bytes;
  - invent prompts or mutate any field on ``image_manifest.json`` — the
    manifest bytes must be byte-identical before and after this run;
  - open ``input/source.md`` — no business-content extraction;
  - generate ``render_models/*`` / ``svg_previews/*`` / any ``.pptx``;
  - render full-slide screenshots or embed SVG / GIF / WebP — only the
    PNG / JPG / JPEG embed surface ``scripts/export_pptx.py`` supports
    today is materialized here (anything else fails closed).

Stdlib-only. Deterministic — given the same workspace + assets-dir, the
resulting target byte set is byte-identical across runs (the helper
copies raw bytes from disk; it does not rewrite, re-encode, or stamp
metadata).

Fail-closed gates (every gate aborts the run; copies that completed
BEFORE the failing gate fired during the apply loop are rolled back so
the workspace returns to its pre-call state):

  --workspace
    * must be an existing directory; URI-shaped values refused; the
      workspace itself must not be a symlink;
    * must ship ``image_manifest.json`` as a regular non-symlink file
      that parses as JSON, decodes to an object, and validates against
      ``schemas/image_manifest.schema.json``;
    * no two ``images[*].id`` values may be equal (defense-in-depth;
      ``init_image_manifest`` already refuses this on the producer side);
    * every ``images[*].local_path`` must pass
      ``validate_scaffold.local_path_is_safe`` AND resolve inside
      ``--workspace`` (defense-in-depth; same gate the schema /
      validate_workspace / init_image_manifest already apply).

  --assets-dir
    * must be an existing directory; URI-shaped values refused; the
      directory itself must not be a symlink (broken or resolvable);
    * every file at the directory ROOT (the helper does NOT recurse —
      assets are flat, keyed by id+extension) must be matched by some
      declared ``images[].id`` whose ``local_path`` extension equals the
      file's extension. Undeclared files (filenames the manifest does
      not name) are refused outright.

  per-image (preflight, no writes)
    * declared ``local_path`` extension (lower-cased) must be one of
      ``.png`` / ``.jpg`` / ``.jpeg`` — the embed surface
      ``export_pptx.py`` supports. Any other extension is refused even
      when the file is a real image, because the exporter falls back to
      a placeholder shape for it (so embedding it would be misleading);
    * the target path ``<workspace>/<local_path>`` must NOT be a symlink
      (broken or resolvable; would otherwise let ``write_bytes`` follow
      the link and clobber an unrelated file). The leaf-symlink check
      runs BEFORE ``_resolves_within`` so a symlink at the target that
      points outside the workspace surfaces with the clear "symlink"
      diagnostic rather than the generic "escapes workspace" diagnostic;
    * the target's parent directory inside the workspace must not be a
      symlink at any segment along the path (would otherwise let
      ``mkdir(parents=True, exist_ok=True)`` silently follow the link to
      outside the workspace);
    * **if the target already exists as a regular file** (the
      post-``init_image_manifest`` state): the leaf must not be a
      symlink, must be a regular file, and its first bytes must match
      the PNG / JPEG magic-byte signature for the declared extension —
      this is the verify-only path, no copy is scheduled, and the
      corresponding ``--assets-dir`` file (if any) is left untouched;
    * **if the target does not yet exist**: the source file under
      ``--assets-dir`` for each declared id+ext pair
      (``<assets-dir>/<id>.<ext>``) must exist as a regular non-symlink
      file, and its first bytes must match the PNG / JPEG magic-byte
      signature for the declared extension. The copy is scheduled.

  apply (writes)
    * for each scheduled copy entry, the source bytes are copied from
      ``<assets-dir>/<id>.<ext>`` to ``<workspace>/<local_path>`` with
      raw binary read+write (no re-encode, no metadata stamp). Each
      written target is added to the rollback set BEFORE its
      ``open('wb')`` call so a half-written file at the failing path is
      still cleaned up on a mid-loop raise. Verify-only entries (target
      already valid) skip the apply loop entirely — nothing is written
      for them, and they are not added to the rollback set.

  post-condition
    * every declared target exists as a regular non-symlink file whose
      first bytes match the PNG / JPEG magic signature for the declared
      extension;
    * ``<workspace>/image_manifest.json`` is byte-identical to the
      pre-call state (the helper never opens it for writing).
    * a post-condition failure rolls back every target the helper
      wrote in this run.

A second run from a clean state (target files removed) produces
byte-identical bytes at each declared local_path.
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

from validate_artifacts import _validate  # noqa: E402
from validate_scaffold import (  # noqa: E402
    local_path_is_safe,
    _resolves_within,
)

IMAGE_MANIFEST_FILENAME = "image_manifest.json"
IMAGE_MANIFEST_SCHEMA = SCHEMAS_DIR / "image_manifest.schema.json"

# Embed surface that scripts/export_pptx.py natively supports today.
# Anything outside this set (SVG / GIF / WebP / TIFF / ...) is refused
# even when the file is a real image, because the exporter falls back to
# a placeholder shape for it.
SUPPORTED_EXTENSIONS: tuple[str, ...] = ("png", "jpg", "jpeg")

# Magic-byte prefixes for the supported extensions. Mirrors
# scripts/export_pptx.py so the materialize gate refuses bytes the
# exporter would later refuse to embed.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE_PREFIX = b"\xff\xd8\xff"

# RFC 3986 scheme; matches the same regex the other init_* helpers use
# so a URI-shaped --workspace / --assets-dir value is refused at the
# string layer before any filesystem syscall fires.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _has_uri_scheme(s: str) -> bool:
    return bool(_URI_SCHEME_PREFIX.match(s))


def _refuse_symlink(path: Path, label: str) -> tuple[bool, str]:
    """Return (is_symlink, fail_message). ``Path.exists()`` returns
    False for a dangling link and ``Path.is_file()`` / ``Path.is_dir()``
    follow links, so an explicit ``is_symlink()`` check is the only way
    to refuse both broken and resolvable links."""
    if not path.is_symlink():
        return False, ""
    try:
        target = str(path.readlink())
    except OSError:
        target = "<unreadable>"
    return True, (
        f"FAIL: {path} ({label}) is a symlink (-> {target}); "
        f"materialize_image_assets refuses to follow it (broken or not). "
        f"Remove or rename the symlink and re-run."
    )


def _schema_validate(value: dict, schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_text())
    errors: list[str] = []
    _validate(value, schema, "<root>", errors)
    return errors


def _matches_image_signature(extension: str, payload: bytes) -> bool:
    """True iff ``payload`` starts with the magic bytes for
    ``extension``. Mirrors scripts/export_pptx.py."""
    if extension == "png":
        return payload.startswith(_PNG_SIGNATURE)
    if extension in ("jpg", "jpeg"):
        return payload.startswith(_JPEG_SIGNATURE_PREFIX)
    return False


def _extension_of(local_path: str) -> str:
    return Path(local_path).suffix.lower().lstrip(".")


def _parent_path_has_no_symlink(workspace: Path, target: Path) -> tuple[bool, str]:
    """Walk from ``workspace`` to (but excluding) ``target`` and refuse
    if any intermediate segment is itself a symlink. ``Path.mkdir`` with
    ``parents=True`` would silently follow a symlinked parent to outside
    the workspace; refusing them here keeps the materialize contract
    "outputs only land inside --workspace" honest."""
    try:
        rel = target.relative_to(workspace)
    except ValueError:
        return False, (
            f"FAIL: target {target} is not relative to workspace {workspace}"
        )
    current = workspace
    for part in rel.parts[:-1]:
        current = current / part
        if current.is_symlink():
            try:
                link_target = str(current.readlink())
            except OSError:
                link_target = "<unreadable>"
            return False, (
                f"FAIL: parent path {current} (for target {target}) is a "
                f"symlink (-> {link_target}); materialize_image_assets "
                f"refuses to write through a symlinked parent."
            )
    return True, ""


def materialize_image_assets(
    *,
    workspace: Path,
    assets_dir: Path,
) -> tuple[int, str]:
    """Run the full pre-D-One materialize pass. Returns (exit_code, message).

    Filesystem contract: preflight failures (bad inputs, malformed /
    schema-invalid manifest, undeclared assets, unsafe / unsupported /
    pre-existing targets, missing / symlink / wrong-magic source files)
    leave the workspace untouched. A mid-apply OR post-condition
    failure rolls back every target the helper wrote in this run."""
    # --workspace shape gates (string-level FIRST, then filesystem).
    if _has_uri_scheme(str(workspace)):
        return 2, (
            f"FAIL: --workspace {workspace} looks like a URI; "
            f"materialize_image_assets only accepts local directory paths"
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

    # --assets-dir shape gates.
    if _has_uri_scheme(str(assets_dir)):
        return 2, (
            f"FAIL: --assets-dir {assets_dir} looks like a URI; "
            f"materialize_image_assets only accepts local directory paths"
        )
    if assets_dir.is_symlink():
        return 2, (
            f"FAIL: --assets-dir {assets_dir} is a symlink; refusing to "
            f"follow it. Pass a regular directory path."
        )
    if not assets_dir.exists():
        return 2, f"FAIL: --assets-dir {assets_dir} does not exist"
    if not assets_dir.is_dir():
        return 2, f"FAIL: --assets-dir {assets_dir} is not a directory"

    # image_manifest.json must be a regular non-symlink file in the
    # workspace and parse / schema-validate cleanly.
    manifest_path = workspace / IMAGE_MANIFEST_FILENAME
    is_symlink, msg = _refuse_symlink(manifest_path, IMAGE_MANIFEST_FILENAME)
    if is_symlink:
        return 2, msg
    if not manifest_path.is_file():
        return 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{IMAGE_MANIFEST_FILENAME}; run scripts/init_image_manifest.py "
            f"first to seed Stage-6 (this helper does not write the "
            f"manifest, it materializes its declared assets)."
        )
    try:
        manifest_bytes_before = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes_before.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return 2, f"FAIL: cannot read {manifest_path}: {exc}"
    if not isinstance(manifest, dict):
        return 2, (
            f"FAIL: {manifest_path} did not decode to an object "
            f"(got {type(manifest).__name__})"
        )
    manifest_errors = _schema_validate(manifest, IMAGE_MANIFEST_SCHEMA)
    if manifest_errors:
        return 1, (
            f"FAIL: {manifest_path} does not validate against "
            f"image_manifest.schema.json: " + "; ".join(manifest_errors)
        )

    images = manifest.get("images") or []

    # Duplicate-id defense (schema does not enforce uniqueness;
    # init_image_manifest does, but a hand-edited workspace might drift).
    seen_ids: dict[str, int] = {}
    dup_errors: list[str] = []
    for i, img in enumerate(images):
        if not isinstance(img, dict):
            return 1, (
                f"FAIL: images[{i}] is not an object "
                f"(got {type(img).__name__})"
            )
        img_id = img.get("id")
        if not isinstance(img_id, str) or not img_id:
            return 1, (
                f"FAIL: images[{i}].id must be a non-empty string "
                f"(got {img_id!r})"
            )
        if img_id in seen_ids:
            dup_errors.append(
                f"id {img_id!r} appears at images[{seen_ids[img_id]}] and "
                f"images[{i}]"
            )
        else:
            seen_ids[img_id] = i
    if dup_errors:
        return 1, (
            f"FAIL: {manifest_path} contains duplicate images[].id "
            f"values: " + "; ".join(dup_errors)
        )

    # Per-image preflight. Build a plan of (id, ext, source_path,
    # target_path) tuples; abort before any write if anything is off.
    # source_path is None for verify-only entries (the target already
    # exists as a regular non-symlink PNG/JPG/JPEG matching magic
    # bytes), which means no copy is scheduled and the corresponding
    # --assets-dir file (if any) is left unused but still declared.
    plan: list[tuple[str, str, Path | None, Path]] = []
    expected_source_names: set[str] = set()
    for i, img in enumerate(images):
        img_id = img["id"]
        local_path = img.get("local_path")
        if not isinstance(local_path, str) or not local_path:
            return 1, (
                f"FAIL: images[{i}] (id {img_id!r}): local_path must be a "
                f"non-empty string (got {local_path!r})"
            )
        if not local_path_is_safe(local_path):
            return 1, (
                f"FAIL: images[{i}] (id {img_id!r}): local_path "
                f"{local_path!r} is not a safe workspace-relative path "
                f"(URI / leading '/' / leading '\\' / '..' segment)"
            )
        ext = _extension_of(local_path)
        if ext not in SUPPORTED_EXTENSIONS:
            return 1, (
                f"FAIL: images[{i}] (id {img_id!r}): local_path "
                f"{local_path!r} has unsupported extension "
                f"{ext or '<none>'!r}; materialize_image_assets only "
                f"materializes "
                + "/".join("." + e for e in SUPPORTED_EXTENSIONS)
                + " (the embed surface scripts/export_pptx.py supports)"
            )
        target = workspace / local_path
        # Symlink checks run BEFORE _resolves_within so a symlink at
        # the target (or along the parent path) that points OUTSIDE the
        # workspace surfaces with the clear "symlink" diagnostic rather
        # than the generic "escapes --workspace" diagnostic
        # _resolves_within (via Path.resolve(), which follows symlinks)
        # would otherwise produce. Leaf symlink first, then parent.
        is_symlink, msg = _refuse_symlink(target, f"target for {img_id}")
        if is_symlink:
            return 1, msg
        ok, msg = _parent_path_has_no_symlink(workspace, target)
        if not ok:
            return 1, msg
        if not _resolves_within(workspace, local_path):
            return 1, (
                f"FAIL: images[{i}] (id {img_id!r}): local_path "
                f"{local_path!r} escapes --workspace after resolution"
            )

        # The source name is tracked for the undeclared-asset check
        # regardless of which branch (verify vs. copy) we take, so an
        # --assets-dir file that matches a declared id is never flagged
        # as undeclared even when the corresponding target already
        # exists and the file is unused.
        source_name = f"{img_id}.{ext}"
        if not local_path_is_safe(source_name):
            return 1, (
                f"FAIL: images[{i}] (id {img_id!r}): computed source "
                f"filename {source_name!r} is not a safe assets-dir "
                f"name (id contains '/', '..', or other path-shaped "
                f"characters)"
            )
        expected_source_names.add(source_name)

        if target.exists():
            # Verify-only branch (post-init_image_manifest state, or a
            # workspace where the agent placed bytes directly). The
            # leaf-symlink check fired above; here we re-confirm the
            # target is a regular file and matches magic bytes for the
            # declared extension. No copy is scheduled, so the
            # corresponding --assets-dir file (if any) is left unused.
            if not target.is_file():
                return 1, (
                    f"FAIL: images[{i}] (id {img_id!r}): pre-existing "
                    f"target {target} is not a regular file"
                )
            try:
                with target.open("rb") as fh:
                    head = fh.read(16)
            except OSError as exc:
                return 1, (
                    f"FAIL: images[{i}] (id {img_id!r}): cannot read "
                    f"pre-existing target {target}: {exc}"
                )
            if not _matches_image_signature(ext, head):
                return 1, (
                    f"FAIL: images[{i}] (id {img_id!r}): pre-existing "
                    f"target {target} does not start with the magic "
                    f"bytes for {ext.upper()}; refusing to certify "
                    f"a mis-extension file in place"
                )
            plan.append((img_id, ext, None, target))
            continue

        # Copy branch (pre-init_image_manifest state). The source must
        # exist under --assets-dir, must be a regular non-symlink file,
        # and must match magic bytes for the declared extension.
        source = assets_dir / source_name
        # Same anti-pattern as the target side: the leaf-symlink check
        # runs BEFORE _resolves_within so a source asset that is itself
        # a symlink pointing outside --assets-dir surfaces with the
        # clear "symlink" diagnostic rather than the generic "escapes
        # --assets-dir" one.
        is_symlink, msg = _refuse_symlink(
            source, f"source for {img_id}"
        )
        if is_symlink:
            return 1, msg
        if not _resolves_within(assets_dir, source_name):
            return 1, (
                f"FAIL: images[{i}] (id {img_id!r}): computed source "
                f"path {source} escapes --assets-dir after resolution"
            )
        if not source.exists():
            return 1, (
                f"FAIL: images[{i}] (id {img_id!r}): source asset "
                f"{source} does not exist under --assets-dir. Place "
                f"{source_name!r} in {assets_dir} and re-run."
            )
        if not source.is_file():
            return 1, (
                f"FAIL: images[{i}] (id {img_id!r}): source asset "
                f"{source} is not a regular file"
            )
        # Magic-byte gate. Reads only the first 16 bytes; the full bytes
        # are read again during the apply loop so a TOCTOU race that
        # swaps the file between the two reads still has to satisfy the
        # post-condition magic check.
        try:
            with source.open("rb") as fh:
                head = fh.read(16)
        except OSError as exc:
            return 1, (
                f"FAIL: images[{i}] (id {img_id!r}): cannot read source "
                f"asset {source}: {exc}"
            )
        if not _matches_image_signature(ext, head):
            return 1, (
                f"FAIL: images[{i}] (id {img_id!r}): source asset "
                f"{source} does not start with the magic bytes for "
                f"{ext.upper()}; refusing to materialize a mis-extension "
                f"file"
            )

        plan.append((img_id, ext, source, target))

    # Undeclared-asset gate. Enumerate files at the assets-dir ROOT (no
    # recursion; the contract is flat keyed by id+ext) and refuse any
    # file the manifest did not name. A pre-existing subdirectory at
    # the root is also refused so a caller cannot stash unrelated
    # bytes under --assets-dir hoping they'll be ignored.
    undeclared: list[str] = []
    for entry in sorted(assets_dir.iterdir()):
        if entry.is_symlink():
            try:
                link_target = str(entry.readlink())
            except OSError:
                link_target = "<unreadable>"
            return 1, (
                f"FAIL: --assets-dir entry {entry.name} is a symlink "
                f"(-> {link_target}); materialize_image_assets refuses "
                f"to follow it (broken or not). Remove or rename it and "
                f"re-run."
            )
        if entry.is_dir():
            return 1, (
                f"FAIL: --assets-dir contains a subdirectory "
                f"{entry.name}; materialize_image_assets only accepts "
                f"a flat directory of asset files keyed by id+extension"
            )
        if entry.is_file() and entry.name not in expected_source_names:
            undeclared.append(entry.name)
    if undeclared:
        return 1, (
            f"FAIL: --assets-dir contains files the image_manifest "
            f"does not declare: " + ", ".join(sorted(undeclared))
            + f". Expected file names: "
            + (", ".join(sorted(expected_source_names))
               if expected_source_names else "<none>")
        )

    # Apply loop. Each target is added to the rollback set BEFORE its
    # open('wb') call so a half-written file at the failing path is
    # still cleaned up on a mid-loop raise. write_text-style truncation
    # (mode='w' / 'wb' truncates immediately) means a raise mid-write
    # leaves zero or partial bytes on disk; the rollback set covers
    # both.
    rollback: list[Path] = []
    try:
        for img_id, ext, source, target in plan:
            if source is None:
                # Verify-only entry — target was already valid at
                # preflight time. Nothing to write; not added to the
                # rollback set (rollback only owns files this run
                # created).
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            rollback.append(target)
            try:
                payload = source.read_bytes()
            except OSError as exc:
                raise RuntimeError(
                    f"copying {source} -> {target} (id {img_id!r}) "
                    f"failed during read: {exc}"
                ) from exc
            # Defense-in-depth: re-check magic bytes against the FULL
            # payload now, after the preflight head read. Catches a
            # TOCTOU race that swapped the source between the preflight
            # and the apply.
            if not _matches_image_signature(ext, payload):
                raise RuntimeError(
                    f"source {source} (id {img_id!r}) no longer matches "
                    f"{ext.upper()} magic bytes during apply (TOCTOU?)"
                )
            try:
                target.write_bytes(payload)
            except OSError as exc:
                raise RuntimeError(
                    f"copying {source} -> {target} (id {img_id!r}) "
                    f"failed during write: {exc}"
                ) from exc
    except (Exception, SystemExit) as exc:
        # Roll back every target written so far AND the partial target
        # at the failing path (already in rollback because we appended
        # BEFORE opening the file for write).
        rolled: list[str] = []
        for t in rollback:
            try:
                if t.exists() or t.is_symlink():
                    t.unlink()
                    rolled.append(str(t))
            except OSError:
                pass
        return 1, (
            f"FAIL: apply loop raised {type(exc).__name__}: {exc}\n"
            f"rolled back: {rolled}"
        )

    # Post-condition. Every target must exist as regular non-symlink
    # PNG/JPG/JPEG matching magic bytes, AND the manifest bytes must be
    # byte-identical to the pre-call state.
    try:
        manifest_bytes_after = manifest_path.read_bytes()
    except OSError as exc:
        # Manifest mysteriously unreadable post-apply — extremely
        # unusual but worth handling. Roll back so we don't leave a
        # half-materialized workspace.
        for t in rollback:
            try:
                if t.exists() or t.is_symlink():
                    t.unlink()
            except OSError:
                pass
        return 1, (
            f"FAIL: cannot re-read {manifest_path} after apply: {exc}\n"
            f"rolled back targets."
        )
    if manifest_bytes_after != manifest_bytes_before:
        for t in rollback:
            try:
                if t.exists() or t.is_symlink():
                    t.unlink()
            except OSError:
                pass
        return 1, (
            f"FAIL: {manifest_path} bytes changed during apply "
            f"(expected byte-identical). Rolled back targets."
        )
    post_errors: list[str] = []
    for img_id, ext, _source, target in plan:
        if target.is_symlink():
            post_errors.append(
                f"{target} (id {img_id!r}) is a symlink after apply"
            )
            continue
        if not target.is_file():
            post_errors.append(
                f"{target} (id {img_id!r}) is not a regular file after "
                f"apply"
            )
            continue
        try:
            head = target.open("rb").read(16)
        except OSError as exc:
            post_errors.append(
                f"{target} (id {img_id!r}) cannot be re-read: {exc}"
            )
            continue
        if not _matches_image_signature(ext, head):
            post_errors.append(
                f"{target} (id {img_id!r}) post-apply bytes do not "
                f"match {ext.upper()} magic signature"
            )
    if post_errors:
        for t in rollback:
            try:
                if t.exists() or t.is_symlink():
                    t.unlink()
            except OSError:
                pass
        return 1, (
            f"FAIL: post-condition failed: " + "; ".join(post_errors)
            + "\nrolled back targets."
        )

    if not plan:
        return 0, (
            f"OK: pre-D-One local asset gate (no declared images; "
            f"{IMAGE_MANIFEST_FILENAME} contains an empty images[] "
            f"list, --assets-dir contains no undeclared files)."
        )
    copied = [
        (img_id, target)
        for img_id, _ext, source, target in plan if source is not None
    ]
    verified = [
        (img_id, target)
        for img_id, _ext, source, target in plan if source is None
    ]
    lines = [
        f"OK: pre-D-One local asset gate processed "
        f"{len(plan)} asset(s) for {workspace}\n"
        f"  source: {assets_dir}"
    ]
    if copied:
        lines.append(
            "  copied: "
            + ", ".join(
                f"{img_id} -> {target.relative_to(workspace)}"
                for img_id, target in copied
            )
        )
    if verified:
        lines.append(
            "  verified in place (no copy): "
            + ", ".join(
                f"{img_id} <- {target.relative_to(workspace)}"
                for img_id, target in verified
            )
        )
    return 0, "\n".join(lines)


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs under
# tempfile.TemporaryDirectory(); no fixture leaks into the repo.
# ---------------------------------------------------------------------------

# Smallest possible PNG and JPEG payloads whose first bytes pass the
# magic-byte gate. These are NOT valid decodable images — that does not
# matter for this helper, which only checks the header signature; the
# downstream exporter has its own decoders and tests. Using a synthetic
# payload keeps the self-test stdlib-only and avoids any external
# fixture.
_SYNTHETIC_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\rIHDR"
    + b"\x00" * 64
)
_SYNTHETIC_JPEG_BYTES = (
    b"\xff\xd8\xff\xe0"
    + b"\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    + b"\xff\xd9"
)


def _seed_workspace_with_manifest(
    ws: Path,
    *,
    images: list[dict] | None = None,
) -> None:
    """Write a synthetic image_manifest.json at the workspace root.

    The manifest is the only thing this helper actually reads from the
    workspace, so the self-test does NOT seed the upstream stage-1-to-5
    artifacts. ``init_image_manifest.py`` is what enforces the upstream
    chain; materialize_image_assets is downstream of that and only needs
    a schema-valid image_manifest.json."""
    ws.mkdir(parents=True, exist_ok=True)
    body = {"images": images if images is not None else []}
    (ws / IMAGE_MANIFEST_FILENAME).write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n"
    )


def _expect(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


def _run_self_tests() -> list[tuple[str, bool, str]]:  # noqa: C901
    import tempfile

    results: list[tuple[str, bool, str]] = []

    # 1. happy path: one declared PNG asset is copied into local_path.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_happy_png"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "cover_accent",
                "local_path": "assets/cover_accent.png",
                "source": "local_asset",
            },
        ])
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "cover_accent.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        target = ws / "assets" / "cover_accent.png"
        ok = (
            rc == 0
            and target.is_file()
            and not target.is_symlink()
            and target.read_bytes() == _SYNTHETIC_PNG_BYTES
        )
        results.append(_expect(
            "happy path: one PNG asset copied into declared local_path "
            "with byte-identical bytes",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 2. happy path: one declared JPG asset is copied.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_happy_jpg"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "hero",
                "local_path": "assets/hero.jpg",
                "source": "local_asset",
            },
        ])
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "hero.jpg").write_bytes(_SYNTHETIC_JPEG_BYTES)
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        target = ws / "assets" / "hero.jpg"
        ok = (
            rc == 0
            and target.is_file()
            and target.read_bytes() == _SYNTHETIC_JPEG_BYTES
        )
        results.append(_expect(
            "happy path: one JPG asset copied into declared local_path",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 3. happy path: one declared JPEG asset is copied (case-insensitive
    # extension handling).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_happy_jpeg"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "section",
                "local_path": "assets/section.JPEG",
                "source": "local_asset",
            },
        ])
        assets = td / "assets_in"
        assets.mkdir()
        # Source filename is lower-cased extension to match the
        # local_path extension (the helper lower-cases ext when computing
        # the source name).
        (assets / "section.jpeg").write_bytes(_SYNTHETIC_JPEG_BYTES)
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        target = ws / "assets" / "section.JPEG"
        ok = (
            rc == 0
            and target.is_file()
            and target.read_bytes() == _SYNTHETIC_JPEG_BYTES
        )
        results.append(_expect(
            "happy path: one JPEG asset (mixed-case extension) copied",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 4. determinism: two independent runs from identical inputs produce
    # byte-identical bytes at the target.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws_a = td / "ws_a"
        ws_b = td / "ws_b"
        assets_a = td / "assets_a"
        assets_b = td / "assets_b"
        for ws, assets in ((ws_a, assets_a), (ws_b, assets_b)):
            _seed_workspace_with_manifest(ws, images=[
                {
                    "id": "img1",
                    "local_path": "media/img1.png",
                    "source": "local_asset",
                },
            ])
            assets.mkdir()
            (assets / "img1.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        rc_a, _ = materialize_image_assets(workspace=ws_a, assets_dir=assets_a)
        rc_b, _ = materialize_image_assets(workspace=ws_b, assets_dir=assets_b)
        ok = (
            rc_a == 0 and rc_b == 0
            and (ws_a / "media" / "img1.png").read_bytes()
            == (ws_b / "media" / "img1.png").read_bytes()
        )
        results.append(_expect(
            "determinism: two independent runs from identical inputs "
            "produce byte-identical target bytes",
            ok, f"rc_a={rc_a}, rc_b={rc_b}",
        ))

    # 5. missing source asset (declared by manifest, absent from
    # assets-dir) refused. No target written.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_missing_src"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "ghost",
                "local_path": "assets/ghost.png",
                "source": "local_asset",
            },
        ])
        assets = td / "empty_assets"
        assets.mkdir()
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = (
            rc == 1
            and "does not exist under --assets-dir" in msg
            and not (ws / "assets" / "ghost.png").exists()
        )
        results.append(_expect(
            "missing source asset refused; no target written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 6. symlink source asset refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_symlink_src"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "linked",
                "local_path": "assets/linked.png",
                "source": "local_asset",
            },
        ])
        assets = td / "assets_in"
        assets.mkdir()
        real = td / "real.png"
        real.write_bytes(_SYNTHETIC_PNG_BYTES)
        (assets / "linked.png").symlink_to(real)
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = (
            rc == 1
            and "symlink" in msg
            and not (ws / "assets" / "linked.png").exists()
        )
        results.append(_expect(
            "symlink source asset refused; no target written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 7. unsafe manifest local_path (URI / absolute / ..) refused.
    for unsafe_label, unsafe_path in (
        ("URI", "https://attacker.example/a.png"),
        ("absolute", "/etc/passwd"),
        ("traversal", "../escape.png"),
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / f"ws_unsafe_{unsafe_label}"
            _seed_workspace_with_manifest(ws, images=[
                {
                    "id": "x",
                    "local_path": unsafe_path,
                    "source": "local_asset",
                },
            ])
            assets = td / "assets_in"
            assets.mkdir()
            rc, msg = materialize_image_assets(
                workspace=ws, assets_dir=assets,
            )
            ok = rc == 1 and (
                "not a safe" in msg or "escapes" in msg
            )
            results.append(_expect(
                f"unsafe manifest local_path ({unsafe_label}: "
                f"{unsafe_path!r}) refused at the path-safety gate",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # 8. unsupported extension (SVG / GIF / WebP / TIFF) refused.
    for ext in ("svg", "gif", "webp", "tiff", "bmp", "ico"):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / f"ws_ext_{ext}"
            _seed_workspace_with_manifest(ws, images=[
                {
                    "id": "x",
                    "local_path": f"assets/x.{ext}",
                    "source": "synthetic",
                },
            ])
            assets = td / "assets_in"
            assets.mkdir()
            (assets / f"x.{ext}").write_bytes(b"whatever")
            rc, msg = materialize_image_assets(
                workspace=ws, assets_dir=assets,
            )
            ok = (
                rc == 1
                and "unsupported extension" in msg
                and ext in msg
                and not (ws / "assets" / f"x.{ext}").exists()
            )
            results.append(_expect(
                f"unsupported extension .{ext} refused at the "
                f"extension gate",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # 9. undeclared asset (file in assets-dir not in manifest) refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_undeclared"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "declared",
                "local_path": "assets/declared.png",
                "source": "local_asset",
            },
        ])
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "declared.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        (assets / "rogue.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = (
            rc == 1
            and "does not declare" in msg
            and "rogue.png" in msg
            and not (ws / "assets" / "declared.png").exists()
        )
        results.append(_expect(
            "undeclared file in --assets-dir refused; no target written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 10. duplicate ids in manifest refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_dup_id"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "same",
                "local_path": "assets/a.png",
                "source": "local_asset",
            },
            {
                "id": "same",
                "local_path": "assets/b.png",
                "source": "local_asset",
            },
        ])
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "same.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = (
            rc == 1
            and "duplicate" in msg
            and "'same'" in msg
            and not (ws / "assets" / "a.png").exists()
            and not (ws / "assets" / "b.png").exists()
        )
        results.append(_expect(
            "duplicate images[].id refused; no target written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 11a. pre-existing target with VALID PNG bytes is accepted as a
    # verify-only entry (no copy, no overwrite, no mutation). This is
    # the post-init_image_manifest state — init_image_manifest requires
    # every declared local_path to already resolve to an existing
    # regular file, so the materializer must support running AFTER it.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_pre_existing_valid"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "img",
                "local_path": "assets/img.png",
                "source": "local_asset",
            },
        ])
        (ws / "assets").mkdir()
        # Pre-existing target with valid PNG bytes — typical
        # post-init_image_manifest state.
        (ws / "assets" / "img.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        prior = (ws / "assets" / "img.png").read_bytes()
        assets = td / "assets_in"
        assets.mkdir()
        # --assets-dir intentionally empty; verify-only run.
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        after = (ws / "assets" / "img.png").read_bytes()
        ok = (
            rc == 0
            and "verified in place" in msg
            and after == prior
        )
        results.append(_expect(
            "pre-existing target with valid PNG bytes is accepted as a "
            "verify-only entry; target bytes are byte-identical pre/post "
            "(post-init_image_manifest workflow)",
            ok, f"rc={rc}, equal={after == prior}, msg={msg!r}",
        ))

    # 11b. pre-existing target with INVALID bytes (wrong magic — file
    # claims to be .png but is not) is refused at the verify-in-place
    # gate. Replaces the older "no overwrite" behavior with a stricter
    # "no mis-extension certify in place" rule.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_pre_existing_invalid"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "img",
                "local_path": "assets/img.png",
                "source": "local_asset",
            },
        ])
        (ws / "assets").mkdir()
        prior = b"NOT-PNG-AT-ALL"
        (ws / "assets" / "img.png").write_bytes(prior)
        assets = td / "assets_in"
        assets.mkdir()
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        after = (ws / "assets" / "img.png").read_bytes()
        ok = (
            rc == 1
            and "does not start with the magic bytes" in msg
            and after == prior
        )
        results.append(_expect(
            "pre-existing target with invalid bytes (wrong magic) "
            "refused at the verify-in-place magic gate; prior bytes "
            "preserved byte-identical",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 11c. pre-existing target with valid bytes AND --assets-dir
    # carrying the SAME id (e.g. agent re-supplied the bytes in a
    # backup directory) succeeds as verify-only — the --assets-dir
    # file is not used, not flagged as undeclared, and the target is
    # not overwritten.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_pre_existing_with_source"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "img",
                "local_path": "assets/img.png",
                "source": "local_asset",
            },
        ])
        (ws / "assets").mkdir()
        (ws / "assets" / "img.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        prior = (ws / "assets" / "img.png").read_bytes()
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "img.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        after = (ws / "assets" / "img.png").read_bytes()
        ok = (
            rc == 0
            and "verified in place" in msg
            and after == prior
        )
        results.append(_expect(
            "pre-existing valid target alongside a matching --assets-dir "
            "entry succeeds as verify-only; the --assets-dir file is not "
            "flagged as undeclared (it matches a declared id), and the "
            "target is not overwritten",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 11d. idempotency: running the helper twice on the same workspace
    # with the same --assets-dir succeeds both times — the first run
    # copies, the second run verifies in place. The second run leaves
    # the target byte-identical.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_idempotent"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "img",
                "local_path": "assets/img.png",
                "source": "local_asset",
            },
        ])
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "img.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        rc1, msg1 = materialize_image_assets(workspace=ws, assets_dir=assets)
        bytes_after_first = (ws / "assets" / "img.png").read_bytes()
        rc2, msg2 = materialize_image_assets(workspace=ws, assets_dir=assets)
        bytes_after_second = (ws / "assets" / "img.png").read_bytes()
        ok = (
            rc1 == 0
            and rc2 == 0
            and "copied" in msg1
            and "verified in place" in msg2
            and bytes_after_first == bytes_after_second
            == _SYNTHETIC_PNG_BYTES
        )
        results.append(_expect(
            "idempotency: first run copies, second run verifies in "
            "place; target bytes byte-identical across runs",
            ok, f"rc1={rc1}, rc2={rc2}, msg2={msg2!r}",
        ))

    # 12. magic-byte mismatch (file is PNG-named but has JPEG bytes)
    # refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_magic"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "img",
                "local_path": "assets/img.png",
                "source": "local_asset",
            },
        ])
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "img.png").write_bytes(_SYNTHETIC_JPEG_BYTES)
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = (
            rc == 1
            and "magic bytes" in msg
            and not (ws / "assets" / "img.png").exists()
        )
        results.append(_expect(
            "magic-byte mismatch (PNG-named file with JPEG bytes) "
            "refused; no target written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 13. URI-shaped --workspace refused at the string layer.
    rc, msg = materialize_image_assets(
        workspace=Path("https://attacker.example/ws"),
        assets_dir=Path("/tmp/does-not-matter"),
    )
    ok = rc == 2 and "URI" in msg
    results.append(_expect(
        "--workspace with URI scheme refused at the string layer",
        ok, f"rc={rc}",
    ))

    # 14. symlink --workspace refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        real = td / "real_ws"
        real.mkdir()
        link = td / "link_ws"
        link.symlink_to(real)
        rc, msg = materialize_image_assets(
            workspace=link, assets_dir=td / "no_assets",
        )
        ok = rc == 2 and "symlink" in msg
        results.append(_expect(
            "--workspace that is itself a symlink refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 15. symlink --assets-dir refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws"
        _seed_workspace_with_manifest(ws)
        real = td / "real_assets"
        real.mkdir()
        link = td / "link_assets"
        link.symlink_to(real)
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=link)
        ok = rc == 2 and "symlink" in msg
        results.append(_expect(
            "--assets-dir that is itself a symlink refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 16. missing image_manifest.json refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_manifest"
        ws.mkdir()
        assets = td / "assets_in"
        assets.mkdir()
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = rc == 2 and "missing" in msg and IMAGE_MANIFEST_FILENAME in msg
        results.append(_expect(
            "missing image_manifest.json refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 17. malformed image_manifest.json (non-JSON) refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_bad_json"
        ws.mkdir()
        (ws / IMAGE_MANIFEST_FILENAME).write_text("{ not json")
        assets = td / "assets_in"
        assets.mkdir()
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = rc == 2 and "cannot read" in msg
        results.append(_expect(
            "malformed image_manifest.json refused at parse",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 18. symlink image_manifest.json refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_link_manifest"
        ws.mkdir()
        outside = td / "outside.json"
        outside.write_text(json.dumps({"images": []}))
        (ws / IMAGE_MANIFEST_FILENAME).symlink_to(outside)
        assets = td / "assets_in"
        assets.mkdir()
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = rc == 2 and "symlink" in msg
        results.append(_expect(
            "symlink image_manifest.json refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 19. schema-invalid image_manifest.json (missing required 'images')
    # refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_schema_bad"
        ws.mkdir()
        (ws / IMAGE_MANIFEST_FILENAME).write_text(
            json.dumps({"not_images": []}) + "\n"
        )
        assets = td / "assets_in"
        assets.mkdir()
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = rc == 1 and "image_manifest.schema.json" in msg
        results.append(_expect(
            "schema-invalid image_manifest.json refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 20. empty manifest + empty assets-dir succeeds as a no-op.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_empty"
        _seed_workspace_with_manifest(ws)
        assets = td / "assets_in"
        assets.mkdir()
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = rc == 0 and "no declared images" in msg
        results.append(_expect(
            "empty manifest + empty assets-dir is an OK no-op",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 21. empty manifest + non-empty assets-dir → undeclared-asset
    # diagnostic.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_empty_with_rogue"
        _seed_workspace_with_manifest(ws)
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "rogue.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = (
            rc == 1
            and "does not declare" in msg
            and "rogue.png" in msg
        )
        results.append(_expect(
            "empty manifest + rogue assets-dir entry refused at "
            "undeclared gate",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 22. assets-dir subdirectory refused (the contract is flat).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_assets_subdir"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "x",
                "local_path": "assets/x.png",
                "source": "local_asset",
            },
        ])
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "x.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        (assets / "nested").mkdir()
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = (
            rc == 1
            and "subdirectory" in msg
            and not (ws / "assets" / "x.png").exists()
        )
        results.append(_expect(
            "--assets-dir containing a subdirectory refused (the "
            "contract is flat keyed by id+extension)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 23. symlink in assets-dir (sibling of the declared asset, not the
    # asset itself) refused at the dir-enumeration gate.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_assets_sibling_link"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "x",
                "local_path": "assets/x.png",
                "source": "local_asset",
            },
        ])
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "x.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        outside = td / "rogue.png"
        outside.write_bytes(_SYNTHETIC_PNG_BYTES)
        (assets / "linked_sibling.png").symlink_to(outside)
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = (
            rc == 1
            and "symlink" in msg
            and "linked_sibling.png" in msg
            and not (ws / "assets" / "x.png").exists()
        )
        results.append(_expect(
            "symlink entry in --assets-dir (sibling of declared asset) "
            "refused at the dir-enumeration gate",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 24. manifest is byte-identical before and after a successful run.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_manifest_unchanged"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "img",
                "local_path": "assets/img.png",
                "source": "local_asset",
            },
        ])
        before = (ws / IMAGE_MANIFEST_FILENAME).read_bytes()
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "img.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        rc, _msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        after = (ws / IMAGE_MANIFEST_FILENAME).read_bytes()
        ok = rc == 0 and before == after
        results.append(_expect(
            "manifest bytes byte-identical pre/post a successful run "
            "(no prompt invention, no field mutation)",
            ok, f"rc={rc}, equal={before == after}",
        ))

    # 25. no source text appears in any written field or filename. Plant
    # a marker phrase in a sibling `input/source.md` (NOT read by this
    # helper) and assert the marker is not in the copied target bytes,
    # the manifest bytes, or anywhere on stdout/stderr capture.
    marker = "MARKER_NEVER_LEAKED_materialize_a7fc31"
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_leak"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "img",
                "local_path": "assets/img.png",
                "source": "local_asset",
                "alt_text": "Spot illustration.",
                "intended_use": "spot illustration",
            },
        ])
        (ws / "input").mkdir()
        (ws / "input" / "source.md").write_text(
            f"# Title\n\nBody with {marker} in it.\n"
        )
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "img.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        target = ws / "assets" / "img.png"
        ok = (
            rc == 0
            and target.is_file()
            and marker not in target.read_bytes().decode(
                "latin-1", errors="replace"
            )
            and marker not in (
                ws / IMAGE_MANIFEST_FILENAME
            ).read_text()
            and marker not in msg
        )
        results.append(_expect(
            "source body marker phrase never copied into any written "
            "field, target bytes, or stdout/stderr (helper does not "
            "read input/source.md for content)",
            ok, f"rc={rc}",
        ))

    # 26. mocked write failure mid-loop rolls back every target the
    # helper had already written (and the partial target at the failing
    # path). Uses a 2-image manifest and a monkey-patched
    # ``Path.write_bytes`` that succeeds on the first call and raises
    # OSError on the second.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_rollback"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "a",
                "local_path": "assets/a.png",
                "source": "local_asset",
            },
            {
                "id": "b",
                "local_path": "assets/b.png",
                "source": "local_asset",
            },
        ])
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "a.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        (assets / "b.png").write_bytes(_SYNTHETIC_PNG_BYTES)

        original_write_bytes = Path.write_bytes
        call_counter = {"n": 0}

        def fake_write_bytes(self: Path, data: bytes) -> int:
            call_counter["n"] += 1
            if call_counter["n"] == 2:
                raise OSError("simulated disk-full on second write")
            return original_write_bytes(self, data)

        Path.write_bytes = fake_write_bytes  # type: ignore[assignment]
        try:
            rc, msg = materialize_image_assets(
                workspace=ws, assets_dir=assets,
            )
        finally:
            Path.write_bytes = original_write_bytes  # type: ignore[assignment]
        ok = (
            rc == 1
            and "rolled back" in msg
            and not (ws / "assets" / "a.png").exists()
            and not (ws / "assets" / "b.png").exists()
        )
        results.append(_expect(
            "mocked mid-loop write failure rolls back every target "
            "(including the partial one at the failing path); workspace "
            "returns to pre-call state",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 27. source filename with path-shaped id (e.g. id='../escape')
    # refused. Defensive: schema only requires non-empty string.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_path_id"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "../escape",
                "local_path": "assets/escape.png",
                "source": "local_asset",
            },
        ])
        assets = td / "assets_in"
        assets.mkdir()
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = rc == 1 and (
            "not a safe assets-dir name" in msg
            or "escapes --assets-dir" in msg
        )
        results.append(_expect(
            "id containing path-shaped characters refused at the "
            "computed-source-name safety gate",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 28. symlink AT the declared target path refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_link_target"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "img",
                "local_path": "assets/img.png",
                "source": "local_asset",
            },
        ])
        (ws / "assets").mkdir()
        outside = td / "outside_target.png"
        # Dangling target is fine — the gate fires on is_symlink().
        (ws / "assets" / "img.png").symlink_to(outside)
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "img.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        target_still_symlink = (
            ws / "assets" / "img.png"
        ).is_symlink()
        target_absent = not outside.exists()
        ok = (
            rc == 1
            and "symlink" in msg
            and target_still_symlink
            and target_absent
        )
        results.append(_expect(
            "symlink at the declared target path refused; dangling "
            "target never created (write_bytes never followed the link)",
            ok,
            f"rc={rc}, still_link={target_still_symlink}, "
            f"absent={target_absent}",
        ))

    # 29. symlink at parent directory of target refused (would otherwise
    # write outside the workspace via mkdir(parents=True, exist_ok=True)
    # silently following the link).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_link_parent"
        _seed_workspace_with_manifest(ws, images=[
            {
                "id": "img",
                "local_path": "assets/img.png",
                "source": "local_asset",
            },
        ])
        outside = td / "outside_dir"
        outside.mkdir()
        (ws / "assets").symlink_to(outside)
        assets = td / "assets_in"
        assets.mkdir()
        (assets / "img.png").write_bytes(_SYNTHETIC_PNG_BYTES)
        rc, msg = materialize_image_assets(workspace=ws, assets_dir=assets)
        ok = (
            rc == 1
            and "symlink" in msg
            and not (outside / "img.png").exists()
        )
        results.append(_expect(
            "symlink at a parent directory of the target refused; "
            "outside directory never written to",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Pre-D-One local image-asset materialization gate. Reads a "
            "workspace that already ships a schema-valid "
            "image_manifest.json (written by scripts/init_image_manifest.py) "
            "and copies caller-supplied local PNG / JPG / JPEG asset bytes "
            "from --assets-dir into the workspace paths declared by each "
            "images[].local_path. Refuses unsafe paths, symlinks, missing "
            "files, unsupported extensions, duplicate ids, undeclared "
            "assets, and writes outside the workspace. Does NOT generate "
            "any image asset, does NOT call D-One / Qoder / any public "
            "network / image generation / image search / model API / "
            "external service, does NOT open input/source.md, does NOT "
            "mutate image_manifest.json, and does NOT produce "
            "render_models, svg_previews, or any .pptx."
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Workspace directory (must already contain image_manifest.json — "
             "e.g. seeded by scripts/init_image_manifest.py).",
    )
    parser.add_argument(
        "--assets-dir", type=Path, default=None,
        help="Local directory containing PNG / JPG / JPEG asset files. The "
             "filename of each asset must be `<id>.<ext>` where `id` matches "
             "an images[].id in image_manifest.json and `<ext>` matches the "
             "lower-cased extension of the declared images[].local_path. "
             "Files unmatched by any declared id are refused as undeclared "
             "assets.",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios (happy paths for "
             "PNG/JPG/JPEG, determinism, missing/symlink source, three "
             "unsafe local_path variants, six unsupported-extension variants, "
             "undeclared asset, duplicate ids, **pre-existing target with "
             "valid bytes accepted as verify-only**, **pre-existing target "
             "with wrong magic refused**, **pre-existing target alongside "
             "matching --assets-dir entry accepted as verify-only**, "
             "**idempotency: first run copies, second run verifies in place**, "
             "magic-byte mismatch, URI/symlink --workspace and --assets-dir, "
             "missing/malformed/symlink/schema-invalid manifest, empty "
             "manifest as no-op, empty manifest + rogue assets-dir, "
             "assets-dir subdirectory, symlink sibling in assets-dir, "
             "manifest byte-identical pre/post, no-source-leak, mocked "
             "mid-loop rollback, path-shaped id, symlink at target, symlink "
             "at parent directory). Exits non-zero if any scenario does not "
             "behave as expected. Mutually exclusive with --workspace / "
             "--assets-dir.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if any(v is not None for v in (args.workspace, args.assets_dir)):
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
            "OK (self-test): pre-D-One local asset materialization gate "
            "behaves as expected on every fail-closed scenario plus the "
            "happy paths."
        )
        return 0

    missing = [
        name for name, value in (
            ("--workspace", args.workspace),
            ("--assets-dir", args.assets_dir),
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

    rc, msg = materialize_image_assets(
        workspace=args.workspace, assets_dir=args.assets_dir,
    )
    if rc == 0:
        print(msg)
    else:
        print(msg, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
