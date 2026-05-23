#!/usr/bin/env python3
"""Mockable local D-One generation runner (NOT real D-One integration).

This script is the narrow boundary where a future real local D-One asset
generator will be wired in. Today it only operates in mock mode — it
consumes a schema-valid ``d_one_adapter_plan.json`` (the dry-run plan
that ``scripts/done_image_adapter.py`` wrote) and emits local PNG / JPG
/ JPEG bytes named ``<id>.<ext>`` into a caller-supplied output assets
directory whose flat layout exactly matches what
``scripts/materialize_image_assets.py`` consumes (``<id>.<ext>`` files
at the assets-dir root, keyed by ``images[].id`` plus the lower-cased
extension of ``images[].local_path``).

There are two mock providers — both purely local, no network, no model
API, no external service:

  * ``--fixtures-dir <dir>``: every plan request id must have a matching
    ``<id>.<ext>`` file inside this directory. The runner copies the
    fixture bytes verbatim into ``<assets-dir>/<id>.<ext>``.
  * ``--allow-synthetic-bytes``: the runner emits a minimal
    valid-magic PNG / JPEG payload (a fixed constant per extension)
    for every plan request. Intended for self-tests and pipeline smoke
    runs where the bytes only need to satisfy the magic-byte gate
    downstream (the materialize gate and the PPTX exporter both check
    only the magic header today).

The two flags are mutually exclusive. Exactly one is required.

**This is a mockable local runner boundary, NOT real D-One integration.**
Real D-One / MCP / model-API integration is intentionally NOT wired
today and is documented as TODO. The script deliberately does NOT:

  - call D-One / Qoder / any image-generation model / any public network
    / any external service / image search / telemetry endpoint;
  - copy any business content from ``input/source.md`` into any
    output — every output is either a verbatim fixture-byte copy or
    a fixed synthetic payload, neither of which carries any source-
    derived data. (The validator pass the runner invokes — see
    ``done_image_adapter.validate_plan_file`` below — does read
    ``input/source.md`` if it exists, but only for the 40-character
    raw-byte shingle scan against each plan prompt; the decoded
    string is discarded after the scan and never reaches a runner
    output.);
  - mutate ``<workspace>/image_manifest.json`` or
    ``<workspace>/d_one_adapter_plan.json`` (both byte-identical
    pre/post a successful run) or the optional
    ``--descriptor-vocabulary`` file (also byte-identical pre/post a
    successful run);
  - generate ``render_models/*``, ``svg_previews/*``, or any ``.pptx``;
  - change PPTX export behavior in any way;
  - emit SVG / GIF / WebP / TIFF bytes — the embed surface
    ``scripts/export_pptx.py`` supports today is PNG / JPG / JPEG, so
    those are the only extensions the runner will materialize (any
    other ``manifest_local_path`` extension on a plan request fails
    closed before any write);
  - generate full-slide screenshots or any whole-slide imagery — the
    plan's per-request safety scan already refused such prompts at
    write time, and the runner re-runs the same scan via
    ``done_image_adapter.validate_plan_file`` before any write.

Stdlib-only. Deterministic — given the same workspace + plan + output
dir + provider mode, the resulting bytes at each ``<assets-dir>/
<id>.<ext>`` are byte-identical across runs (fixture mode copies raw
bytes; synthetic mode emits a fixed payload).

Fail-closed gates (every gate aborts the run; copies that completed
BEFORE the failing gate fired during the apply loop are rolled back so
the assets-dir returns to its pre-call state):

  --workspace
    * must be an existing directory; URI-shaped values refused; the
      workspace itself must not be a symlink (broken or resolvable);
    * must ship ``image_manifest.json`` AND the plan file (default
      ``<workspace>/d_one_adapter_plan.json``) as regular non-symlink
      JSON files that pass ``done_image_adapter.validate_plan_file``
      (which applies the full plan-schema + manifest cross-checks +
      prompt safety re-scan — see the validator's docstring).

  --plan (optional; defaults to ``<workspace>/d_one_adapter_plan.json``)
    * must pass the same gate the validator applies internally
      (existing regular non-symlink file; URI-shape refused).

  --descriptor-vocabulary (optional; required iff the plan carries any
  of the five taxonomy fields: ``rendering_style`` / ``palette_family``
  / ``image_role`` / ``layout_pattern`` / ``modifier``)
    * when supplied, must be an existing regular non-symlink file whose
      bytes parse as JSON, decode to an object, and validate against
      ``schemas/d_one_descriptor_vocabulary.schema.json``; the runner
      hands the path through to ``done_image_adapter.validate_plan_file``
      so the same image_taxonomy.allowed_values check the writer ran is
      re-run at the runner boundary;
    * when omitted, a plan that carries taxonomy fields is refused by
      the validator (the runner cannot certify a taxonomy plan whose
      values it cannot re-check). A taxonomy-free plan accepts the
      omitted flag without complaint.

  --assets-dir
    * must be an existing directory; URI-shaped values refused; the
      directory itself must not be a symlink (broken or resolvable);
    * for each plan request, the target ``<assets-dir>/<id>.<ext>``
      must NOT pre-exist (no overwrite — the caller must remove any
      prior bytes), must not be a symlink, and must resolve inside
      ``--assets-dir`` (defense-in-depth, since ``id`` is in principle
      attacker-controllable; ``local_path_is_safe`` + ``_resolves_within``
      both have to pass);
    * ``<id>.<ext>`` filename is computed as the manifest's id plus
      the lower-cased extension of ``manifest_local_path`` — the same
      naming convention ``materialize_image_assets.py`` uses, so the
      runner's output can be fed directly to materialize.

  --fixtures-dir (when used)
    * must be an existing directory; URI-shaped values refused; the
      directory itself must not be a symlink;
    * for every plan request, ``<fixtures-dir>/<id>.<ext>`` must exist
      as a regular non-symlink file whose first bytes match the magic
      signature for the declared extension. Missing fixtures, wrong
      magic bytes, symlinked fixtures, and undeclared fixtures are all
      refused before any write.

  --allow-synthetic-bytes (when used)
    * the runner emits a fixed minimal PNG or JPEG payload (one
      constant per extension) for every plan request. Mutually
      exclusive with ``--fixtures-dir``.

  per-request
    * the plan request's ``manifest_local_path`` lower-cased extension
      must be one of ``.png`` / ``.jpg`` / ``.jpeg`` — the embed
      surface ``scripts/export_pptx.py`` supports today. Any other
      extension is refused (SVG / GIF / WebP / TIFF / ... fall back to
      the placeholder shape in the exporter, so emitting them here
      would be misleading);
    * the plan request's ``manifest_source`` must equal
      ``"d_one_local"`` — the same gate ``done_image_adapter`` applies
      at write time. Defense in depth.

  apply
    * each scheduled output is added to the rollback set BEFORE its
      ``open('wb')`` call so a half-written file at the failing path
      is still cleaned up on a mid-loop raise;
    * raw binary copy in fixture mode, fixed-payload write in
      synthetic mode — no re-encode, no metadata stamp;
    * post-write magic-byte re-check against the bytes actually on
      disk catches a TOCTOU swap or a disk-level corruption.

  post-condition
    * every scheduled output exists as a regular non-symlink PNG / JPG
      / JPEG file whose first bytes match the declared-extension magic
      signature;
    * ``<workspace>/image_manifest.json`` and the plan file are
      byte-identical to the pre-call state;
    * no other file under ``--assets-dir`` is created (the runner
      only writes ``<id>.<ext>`` files keyed by plan requests).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

from validate_scaffold import (  # noqa: E402
    local_path_is_safe,
    _resolves_within,
)
import done_image_adapter as _adapter  # noqa: E402
import materialize_image_assets as _mat  # noqa: E402

DEFAULT_PLAN_FILENAME = _adapter.DEFAULT_PLAN_FILENAME
IMAGE_MANIFEST_FILENAME = _adapter.IMAGE_MANIFEST_FILENAME

# Embed surface that scripts/export_pptx.py natively supports today.
# Mirrors materialize_image_assets.SUPPORTED_EXTENSIONS so the runner's
# output and the materialize gate agree on what is materializable.
SUPPORTED_EXTENSIONS: tuple[str, ...] = _mat.SUPPORTED_EXTENSIONS

# Fixed synthetic payloads for --allow-synthetic-bytes. The only
# requirement is that the bytes pass the magic-byte gate in
# materialize_image_assets and export_pptx; they do NOT need to decode
# as a real image (downstream tests use the same synthetic payloads).
_SYNTHETIC_PNG_BYTES = _mat._SYNTHETIC_PNG_BYTES
_SYNTHETIC_JPEG_BYTES = _mat._SYNTHETIC_JPEG_BYTES

_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _has_uri_scheme(s: str) -> bool:
    return bool(_URI_SCHEME_PREFIX.match(s))


def _refuse_symlink(path: Path, label: str) -> tuple[bool, str]:
    if not path.is_symlink():
        return False, ""
    try:
        target = str(path.readlink())
    except OSError:
        target = "<unreadable>"
    return True, (
        f"FAIL: {path} ({label}) is a symlink (-> {target}); "
        f"run_d_one_generation refuses to follow it (broken or not). "
        f"Remove or rename the symlink and re-run."
    )


def _synthetic_payload_for(ext: str) -> bytes | None:
    if ext == "png":
        return _SYNTHETIC_PNG_BYTES
    if ext in ("jpg", "jpeg"):
        return _SYNTHETIC_JPEG_BYTES
    return None


def run_d_one_generation(
    *,
    workspace: Path,
    assets_dir: Path,
    plan: Path | None = None,
    fixtures_dir: Path | None = None,
    allow_synthetic_bytes: bool = False,
    descriptor_vocabulary: Path | None = None,
) -> tuple[int, str]:
    """Run the mockable local D-One generator. Returns (exit_code, message).

    Preflight failures leave the assets-dir untouched. A mid-apply or
    post-condition failure rolls back every output file the runner
    wrote during this run."""
    # Provider-mode invariant: exactly one of --fixtures-dir /
    # --allow-synthetic-bytes is required. Mutually exclusive.
    if fixtures_dir is not None and allow_synthetic_bytes:
        return 2, (
            "FAIL: --fixtures-dir and --allow-synthetic-bytes are mutually "
            "exclusive; pick one. (Real D-One integration is intentionally "
            "TODO; this runner only operates in mock mode today.)"
        )
    if fixtures_dir is None and not allow_synthetic_bytes:
        return 2, (
            "FAIL: one of --fixtures-dir or --allow-synthetic-bytes is "
            "required. (Real D-One integration is intentionally TODO; this "
            "runner only operates in mock mode today.)"
        )

    # String-level URI-shape gates BEFORE any filesystem call. Mirrors
    # done_image_adapter / materialize_image_assets so a URI-shaped
    # argument is refused even when another input would have failed an
    # earlier filesystem gate.
    if _has_uri_scheme(str(workspace)):
        return 2, (
            f"FAIL: --workspace {workspace} looks like a URI; "
            f"run_d_one_generation only accepts local directory paths"
        )
    if _has_uri_scheme(str(assets_dir)):
        return 2, (
            f"FAIL: --assets-dir {assets_dir} looks like a URI; "
            f"run_d_one_generation only accepts local directory paths"
        )
    if plan is not None and _has_uri_scheme(str(plan)):
        return 2, (
            f"FAIL: --plan {plan} looks like a URI; "
            f"run_d_one_generation only accepts local file paths"
        )
    if fixtures_dir is not None and _has_uri_scheme(str(fixtures_dir)):
        return 2, (
            f"FAIL: --fixtures-dir {fixtures_dir} looks like a URI; "
            f"run_d_one_generation only accepts local directory paths"
        )
    if descriptor_vocabulary is not None and _has_uri_scheme(
        str(descriptor_vocabulary)
    ):
        return 2, (
            f"FAIL: --descriptor-vocabulary {descriptor_vocabulary} "
            f"looks like a URI; run_d_one_generation only accepts "
            f"local file paths"
        )

    # --workspace filesystem gates.
    if workspace.is_symlink():
        return 2, (
            f"FAIL: --workspace {workspace} is a symlink; refusing to "
            f"follow it. Pass a regular directory path."
        )
    if not workspace.exists():
        return 2, f"FAIL: --workspace {workspace} does not exist"
    if not workspace.is_dir():
        return 2, f"FAIL: --workspace {workspace} is not a directory"

    # --assets-dir filesystem gates.
    if assets_dir.is_symlink():
        return 2, (
            f"FAIL: --assets-dir {assets_dir} is a symlink; refusing to "
            f"follow it. Pass a regular directory path."
        )
    if not assets_dir.exists():
        return 2, f"FAIL: --assets-dir {assets_dir} does not exist"
    if not assets_dir.is_dir():
        return 2, f"FAIL: --assets-dir {assets_dir} is not a directory"

    # --fixtures-dir filesystem gates (when given).
    if fixtures_dir is not None:
        if fixtures_dir.is_symlink():
            return 2, (
                f"FAIL: --fixtures-dir {fixtures_dir} is a symlink; "
                f"refusing to follow it. Pass a regular directory path."
            )
        if not fixtures_dir.exists():
            return 2, f"FAIL: --fixtures-dir {fixtures_dir} does not exist"
        if not fixtures_dir.is_dir():
            return 2, (
                f"FAIL: --fixtures-dir {fixtures_dir} is not a directory"
            )

    # Plan path resolution. Defaults to <workspace>/d_one_adapter_plan.json.
    if plan is None:
        plan = workspace / DEFAULT_PLAN_FILENAME
    # Defense in depth: the validator below applies the same gates, but
    # surfacing a clean diagnostic here when the plan is obviously
    # absent helps the caller. The validator owns the schema +
    # cross-check layer.
    is_symlink, msg = _refuse_symlink(plan, "--plan")
    if is_symlink:
        return 2, msg
    if not plan.exists():
        return 2, f"FAIL: --plan {plan} does not exist"
    if not plan.is_file():
        return 2, f"FAIL: --plan {plan} is not a regular file"

    # Full plan validation via done_image_adapter.validate_plan_file —
    # this applies the plan schema, the manifest preflight, every
    # cross-check the schema cannot express, AND the full per-request
    # safety re-scan (URIs, file paths, raw-source markers, 40-char
    # input/source.md shingles, credentials, PII, full-slide wording).
    # When the caller passed --descriptor-vocabulary, the validator
    # additionally schema-checks the vocab and re-runs the
    # image_taxonomy.allowed_values membership check against every
    # taxonomy-bearing plan request — closing the dead-end where a
    # taxonomy plan could not pass through the mock runner. Re-using
    # the validator keeps the runner from drifting away from the same
    # gates done_image_adapter applied at write time.
    rc, msg = _adapter.validate_plan_file(
        workspace=workspace,
        plan=plan,
        descriptor_vocabulary=descriptor_vocabulary,
    )
    if rc != 0:
        return rc, msg

    # Re-parse the plan now that we know it validates. Manifest bytes
    # are captured here so the post-condition can confirm they did not
    # drift while we wrote outputs.
    try:
        plan_bytes_before = plan.read_bytes()
        plan_doc = json.loads(plan_bytes_before.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # The validator just confirmed the plan parses; this branch
        # should not fire in normal operation but is kept for
        # robustness.
        return 1, f"FAIL: cannot re-read {plan}: {exc}"
    manifest_path = workspace / IMAGE_MANIFEST_FILENAME
    try:
        manifest_bytes_before = manifest_path.read_bytes()
    except OSError as exc:
        return 1, f"FAIL: cannot re-read {manifest_path}: {exc}"
    # When --descriptor-vocabulary was supplied, capture its bytes so the
    # post-condition can confirm the runner did not mutate it. The
    # validator already schema-validated the file and rejected symlinks
    # / URIs, so a successful read here is expected.
    vocab_bytes_before: bytes | None = None
    if descriptor_vocabulary is not None:
        try:
            vocab_bytes_before = descriptor_vocabulary.read_bytes()
        except OSError as exc:
            return 1, (
                f"FAIL: cannot re-read --descriptor-vocabulary "
                f"{descriptor_vocabulary}: {exc}"
            )

    # Build the per-request schedule. Each scheduled entry resolves to
    # a target inside --assets-dir; the schedule is built fully before
    # any write so a preflight failure leaves the assets-dir untouched.
    schedule: list[tuple[str, str, Path, bytes]] = []
    expected_source_names: set[str] = set()
    for i, req in enumerate(plan_doc["requests"]):
        req_id: str = req["id"]
        manifest_local_path: str = req["manifest_local_path"]
        manifest_source: str = req["manifest_source"]

        # Defense in depth: the plan schema already locks
        # manifest_source to 'd_one_local'; re-check anyway so the
        # runner refuses to emit bytes for any other source.
        if manifest_source != _adapter.ELIGIBLE_MANIFEST_SOURCE:
            return 1, (
                f"FAIL: requests[{i}] (id {req_id!r}): manifest_source="
                f"{manifest_source!r}; run_d_one_generation only emits "
                f"bytes for source={_adapter.ELIGIBLE_MANIFEST_SOURCE!r}"
            )

        # Defense in depth: the validator already ran
        # local_path_is_safe + _resolves_within against
        # manifest_local_path; rerunning here means a future change to
        # the validator that loosens its check would still be caught
        # by the runner.
        if not local_path_is_safe(manifest_local_path):
            return 1, (
                f"FAIL: requests[{i}] (id {req_id!r}): manifest_local_path "
                f"{manifest_local_path!r} is not a safe workspace-relative "
                f"path"
            )
        if not _resolves_within(workspace, manifest_local_path):
            return 1, (
                f"FAIL: requests[{i}] (id {req_id!r}): manifest_local_path "
                f"{manifest_local_path!r} escapes --workspace after "
                f"resolution"
            )

        ext = _mat._extension_of(manifest_local_path)
        if ext not in SUPPORTED_EXTENSIONS:
            return 1, (
                f"FAIL: requests[{i}] (id {req_id!r}): manifest_local_path "
                f"{manifest_local_path!r} has unsupported extension "
                f"{ext or '<none>'!r}; run_d_one_generation only emits "
                + "/".join("." + e for e in SUPPORTED_EXTENSIONS)
                + " (the embed surface scripts/export_pptx.py supports)"
            )

        # The output filename inside --assets-dir is exactly the name
        # materialize_image_assets expects: <id>.<ext> where <ext> is
        # the lower-cased extension of manifest_local_path. Re-running
        # local_path_is_safe + _resolves_within on the source name
        # catches an id that contains '/', '..', or other path-shaped
        # characters that would let us write outside --assets-dir.
        source_name = f"{req_id}.{ext}"
        if not local_path_is_safe(source_name):
            return 1, (
                f"FAIL: requests[{i}] (id {req_id!r}): computed output "
                f"filename {source_name!r} is not a safe assets-dir name "
                f"(id contains '..', a URI scheme, leading slash, or "
                f"other path-shaped characters)"
            )
        # local_path_is_safe rejects leading slashes / URI schemes /
        # '..' segments but DOES allow internal '/' or '\\' — a path-
        # shaped id like 'a/b' would pass that check, slip through
        # _resolves_within (the resolved path is still inside
        # --assets-dir), and end up at '<assets-dir>/a/b.png'. The
        # runner would then create the subdirectory 'a/' via
        # target.parent.mkdir(parents=True, ...) and the downstream
        # materialize_image_assets gate would refuse the whole
        # --assets-dir with "contains a subdirectory" — a confusing
        # diagnostic far from the actual cause. Fail fast here with a
        # clear message instead. The flat-layout contract
        # materialize_image_assets enforces is: every output file is
        # at the assets-dir root, keyed by '<id>.<ext>'. An id with
        # '/' or '\\' cannot satisfy that.
        if "/" in source_name or "\\" in source_name:
            return 1, (
                f"FAIL: requests[{i}] (id {req_id!r}): computed output "
                f"filename {source_name!r} contains a path separator; "
                f"run_d_one_generation writes only flat <id>.<ext> "
                f"files at --assets-dir root (the layout "
                f"scripts/materialize_image_assets.py consumes), so an "
                f"id with '/' or '\\' is refused. Rename the manifest "
                f"entry's id to a flat token and re-author the plan."
            )
        target = assets_dir / source_name
        is_symlink, msg = _refuse_symlink(
            target, f"output target for {req_id}"
        )
        if is_symlink:
            return 1, msg
        if not _resolves_within(assets_dir, source_name):
            return 1, (
                f"FAIL: requests[{i}] (id {req_id!r}): computed output "
                f"path {target} escapes --assets-dir after resolution"
            )
        if target.exists():
            return 1, (
                f"FAIL: requests[{i}] (id {req_id!r}): output target "
                f"{target} already exists; run_d_one_generation refuses "
                f"to overwrite a prior asset. Remove it and re-run."
            )
        if source_name in expected_source_names:
            # The plan validator already rejected duplicate ids in
            # requests[], so this duplicate-source-name branch is
            # defense in depth — a plan that drifted between
            # validate_plan_file and this loop would still be caught.
            return 1, (
                f"FAIL: requests[{i}] (id {req_id!r}): output filename "
                f"{source_name!r} already scheduled by an earlier request "
                f"(duplicate id in plan)"
            )
        expected_source_names.add(source_name)

        # Resolve the payload bytes for this request based on the
        # provider mode.
        if fixtures_dir is not None:
            fixture = fixtures_dir / source_name
            if not local_path_is_safe(source_name):
                # Already checked above, but keeps the branch
                # self-contained for fixture-mode reasoning.
                return 1, (
                    f"FAIL: requests[{i}] (id {req_id!r}): computed "
                    f"fixture filename {source_name!r} is not safe"
                )
            is_symlink, msg = _refuse_symlink(
                fixture, f"fixture for {req_id}"
            )
            if is_symlink:
                return 1, msg
            if not _resolves_within(fixtures_dir, source_name):
                return 1, (
                    f"FAIL: requests[{i}] (id {req_id!r}): fixture path "
                    f"{fixture} escapes --fixtures-dir after resolution"
                )
            if not fixture.exists():
                return 1, (
                    f"FAIL: requests[{i}] (id {req_id!r}): fixture "
                    f"{fixture} does not exist under --fixtures-dir. "
                    f"Place {source_name!r} in {fixtures_dir} and re-run."
                )
            if not fixture.is_file():
                return 1, (
                    f"FAIL: requests[{i}] (id {req_id!r}): fixture "
                    f"{fixture} is not a regular file"
                )
            try:
                payload = fixture.read_bytes()
            except OSError as exc:
                return 1, (
                    f"FAIL: requests[{i}] (id {req_id!r}): cannot read "
                    f"fixture {fixture}: {exc}"
                )
            if not _mat._matches_image_signature(ext, payload):
                return 1, (
                    f"FAIL: requests[{i}] (id {req_id!r}): fixture "
                    f"{fixture} does not start with the magic bytes for "
                    f"{ext.upper()}; refusing to materialize a "
                    f"mis-extension fixture"
                )
        else:
            # --allow-synthetic-bytes: fixed payload per extension.
            synthetic = _synthetic_payload_for(ext)
            if synthetic is None:
                # Should never fire given the SUPPORTED_EXTENSIONS gate
                # above, but kept for symmetry.
                return 1, (
                    f"FAIL: requests[{i}] (id {req_id!r}): no synthetic "
                    f"payload is defined for extension {ext!r}"
                )
            payload = synthetic

        schedule.append((req_id, ext, target, payload))

    # Apply loop. Each target is added to the rollback set BEFORE its
    # open('wb') call so a half-written file at the failing path is
    # still cleaned up on a mid-loop raise. Mirrors the rollback
    # pattern in materialize_image_assets so the two helpers behave
    # consistently on a partial failure.
    rollback: list[Path] = []
    try:
        for req_id, ext, target, payload in schedule:
            target.parent.mkdir(parents=True, exist_ok=True)
            rollback.append(target)
            try:
                target.write_bytes(payload)
            except OSError as exc:
                raise RuntimeError(
                    f"writing {target} (id {req_id!r}) failed: {exc}"
                ) from exc
    except (Exception, SystemExit) as exc:
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

    # Post-condition. Every scheduled output must exist as a regular
    # non-symlink file whose first bytes match the declared magic
    # signature. The manifest bytes AND the plan bytes must be
    # byte-identical to the pre-call state (the runner never opens
    # either for writing — defense in depth).
    try:
        manifest_bytes_after = manifest_path.read_bytes()
        plan_bytes_after = plan.read_bytes()
    except OSError as exc:
        for t in rollback:
            try:
                if t.exists() or t.is_symlink():
                    t.unlink()
            except OSError:
                pass
        return 1, (
            f"FAIL: cannot re-read workspace state after apply: {exc}\n"
            f"rolled back outputs."
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
            f"(expected byte-identical). Rolled back outputs."
        )
    if plan_bytes_after != plan_bytes_before:
        for t in rollback:
            try:
                if t.exists() or t.is_symlink():
                    t.unlink()
            except OSError:
                pass
        return 1, (
            f"FAIL: {plan} bytes changed during apply "
            f"(expected byte-identical). Rolled back outputs."
        )
    if descriptor_vocabulary is not None and vocab_bytes_before is not None:
        try:
            vocab_bytes_after = descriptor_vocabulary.read_bytes()
        except OSError as exc:
            for t in rollback:
                try:
                    if t.exists() or t.is_symlink():
                        t.unlink()
                except OSError:
                    pass
            return 1, (
                f"FAIL: cannot re-read --descriptor-vocabulary "
                f"{descriptor_vocabulary} after apply: {exc}. Rolled "
                f"back outputs."
            )
        if vocab_bytes_after != vocab_bytes_before:
            for t in rollback:
                try:
                    if t.exists() or t.is_symlink():
                        t.unlink()
                except OSError:
                    pass
            return 1, (
                f"FAIL: {descriptor_vocabulary} bytes changed during "
                f"apply (expected byte-identical). Rolled back outputs."
            )
    post_errors: list[str] = []
    for req_id, ext, target, _payload in schedule:
        if target.is_symlink():
            post_errors.append(
                f"{target} (id {req_id!r}) is a symlink after apply"
            )
            continue
        if not target.is_file():
            post_errors.append(
                f"{target} (id {req_id!r}) is not a regular file after "
                f"apply"
            )
            continue
        try:
            head = target.open("rb").read(16)
        except OSError as exc:
            post_errors.append(
                f"{target} (id {req_id!r}) cannot be re-read: {exc}"
            )
            continue
        if not _mat._matches_image_signature(ext, head):
            post_errors.append(
                f"{target} (id {req_id!r}) post-apply bytes do not match "
                f"{ext.upper()} magic signature"
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
            + "\nrolled back outputs."
        )

    mode = "fixture" if fixtures_dir is not None else "synthetic"
    return 0, (
        f"OK: mockable local D-One generation runner wrote "
        f"{len(schedule)} output(s) to {assets_dir}\n"
        f"  workspace: {workspace}\n"
        f"  plan:      {plan}\n"
        f"  provider:  mock ({mode}; no D-One call; no network)\n"
        f"  outputs:   "
        + ", ".join(
            f"{req_id} -> {target.name}"
            for req_id, _ext, target, _payload in schedule
        )
    )


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs under
# tempfile.TemporaryDirectory(); no fixture leaks into the repo.
# ---------------------------------------------------------------------------


def _seed_workspace_with_plan(
    td: Path,
    *,
    images: list[dict],
    requests: list[dict],
    descriptor_vocabulary: Path | None = None,
) -> tuple[Path, Path]:
    """Seed a workspace with an image_manifest.json AND a valid
    d_one_adapter_plan.json by running done_image_adapter against a
    matching spec. Returns (workspace, plan_path).

    Building the plan through the writer (rather than handcrafting it)
    keeps the self-test honest: the runner consumes plans the same way
    a downstream caller would receive them — straight off the writer.

    When ``descriptor_vocabulary`` is supplied, it is forwarded to the
    writer so a taxonomy-bearing spec lands in the produced plan."""
    ws = td / "ws"
    _adapter._seed_workspace(ws, images=images)
    spec_path = td / "spec.json"
    _adapter._write_spec(spec_path, {"requests": requests})
    rc, msg = _adapter.done_image_adapter(
        workspace=ws, spec=spec_path,
        descriptor_vocabulary=descriptor_vocabulary,
    )
    if rc != 0:
        raise AssertionError(
            f"self-test fixture: done_image_adapter failed unexpectedly: "
            f"rc={rc} msg={msg!r}"
        )
    return ws, ws / DEFAULT_PLAN_FILENAME


def _seed_descriptor_vocab(td: Path) -> Path:
    """Write a synthetic, schema-valid descriptor vocabulary to the
    given tempdir and return the path. Mirrors the canonical taxonomy
    in examples/d_one_descriptor_vocabulary_template.json but kept
    in-script so the runner's self-tests do not depend on on-disk
    template bytes (the schema/template pair is re-validated separately
    via `python3 scripts/validate_artifacts.py ...`)."""
    vocab_path = td / "vocab.json"
    body = {
        "schema_version": 1,
        "note": (
            "Synthetic D-One descriptor vocabulary for runner taxonomy "
            "probes."
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
            "rendering_style": {
                "allowed_values": [
                    "flat_vector", "line_diagram", "isometric_lite",
                    "low_poly", "solid_shape",
                ],
            },
            "palette_family": {
                "allowed_values": [
                    "neutral_grey", "accent_only", "dual_tone",
                    "mono_brand", "palette_default",
                ],
            },
            "image_role": {
                "allowed_values": [
                    "decorative_accent", "metaphor_icon", "divider_motif",
                    "kpi_emblem", "cover_motif",
                ],
            },
            "layout_pattern": {
                "allowed_values": [
                    "single_center", "left_anchor", "right_anchor",
                    "top_band", "bottom_band",
                ],
            },
            "modifier": {
                "allowed_values": [
                    "low_contrast", "soft_edges", "grid_aligned",
                    "negative_space",
                ],
            },
        },
    }
    vocab_path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
    return vocab_path


def _expect(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


def _list_dir_files(p: Path) -> set[str]:
    if not p.exists():
        return set()
    out: set[str] = set()
    for entry in p.rglob("*"):
        if entry.is_file():
            out.add(str(entry.relative_to(p)))
    return out


def _run_self_tests() -> list[tuple[str, bool, str]]:  # noqa: C901
    import tempfile

    results: list[tuple[str, bool, str]] = []

    # ---- 1. happy path: synthetic provider produces PNG+JPG outputs
    # whose bytes pass the magic-byte gate. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "cover_accent", "local_path": "media/cover_accent.png", "source": "d_one_local"},
                {"id": "section_hero", "local_path": "media/section_hero.jpg", "source": "d_one_local"},
            ],
            requests=[
                {"id": "cover_accent", "prompt": "an abstract geometric pattern, no text"},
                {"id": "section_hero", "prompt": "a calm gradient texture, no text"},
            ],
        )
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
        )
        png = out / "cover_accent.png"
        jpg = out / "section_hero.jpg"
        ok = (
            rc == 0
            and png.is_file() and not png.is_symlink()
            and jpg.is_file() and not jpg.is_symlink()
            and png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            and jpg.read_bytes().startswith(b"\xff\xd8\xff")
        )
        results.append(_expect(
            "synthetic mode: writes <id>.<ext> files into --assets-dir "
            "with PNG/JPEG magic-byte-valid bytes",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 2. happy path end-to-end with materialize_image_assets:
    # synthetic outputs flow through the materialize gate and land at
    # the manifest's local_path. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _plan_path = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "alpha", "local_path": "media/alpha.png", "source": "d_one_local"},
                {"id": "beta", "local_path": "media/beta.jpg", "source": "d_one_local"},
            ],
            requests=[
                {"id": "alpha", "prompt": "abstract pattern, no text"},
                {"id": "beta", "prompt": "soft gradient, no text"},
            ],
        )
        out = td / "out"
        out.mkdir()
        rc_run, msg_run = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
        )
        rc_mat, msg_mat = _mat.materialize_image_assets(
            workspace=ws, assets_dir=out,
        )
        alpha_target = ws / "media" / "alpha.png"
        beta_target = ws / "media" / "beta.jpg"
        ok = (
            rc_run == 0
            and rc_mat == 0
            and alpha_target.is_file()
            and beta_target.is_file()
            and alpha_target.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            and beta_target.read_bytes().startswith(b"\xff\xd8\xff")
        )
        results.append(_expect(
            "end-to-end: synthetic outputs flow through "
            "materialize_image_assets and land at the manifest's "
            "local_path with magic-byte-valid bytes",
            ok, f"rc_run={rc_run}, rc_mat={rc_mat}, msg_mat={msg_mat!r}",
        ))

    # ---- 3. fixture mode happy path: caller-supplied PNG/JPEG bytes
    # are copied verbatim into --assets-dir. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _plan_path = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "spot", "local_path": "media/spot.png", "source": "d_one_local"},
            ],
            requests=[
                {"id": "spot", "prompt": "a calm pattern, no text"},
            ],
        )
        fixtures = td / "fixtures"
        fixtures.mkdir()
        fixture_bytes = (
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\rIHDR"
            + b"\xAB" * 64
        )
        (fixtures / "spot.png").write_bytes(fixture_bytes)
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, fixtures_dir=fixtures,
        )
        target = out / "spot.png"
        ok = (
            rc == 0
            and target.is_file()
            and target.read_bytes() == fixture_bytes
        )
        results.append(_expect(
            "fixture mode: caller-supplied PNG bytes copied verbatim "
            "into --assets-dir/<id>.<ext>",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 4. determinism: two independent runs from identical inputs
    # produce byte-identical outputs (synthetic mode). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws_a, _ = _seed_workspace_with_plan(
            td / "a",
            images=[
                {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
            ],
            requests=[{"id": "x", "prompt": "abstract pattern, no text"}],
        )
        ws_b, _ = _seed_workspace_with_plan(
            td / "b",
            images=[
                {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
            ],
            requests=[{"id": "x", "prompt": "abstract pattern, no text"}],
        )
        out_a = (td / "a") / "out"
        out_b = (td / "b") / "out"
        out_a.mkdir()
        out_b.mkdir()
        rc_a, _ = run_d_one_generation(
            workspace=ws_a, assets_dir=out_a, allow_synthetic_bytes=True,
        )
        rc_b, _ = run_d_one_generation(
            workspace=ws_b, assets_dir=out_b, allow_synthetic_bytes=True,
        )
        ok = (
            rc_a == 0 and rc_b == 0
            and (out_a / "x.png").read_bytes() == (out_b / "x.png").read_bytes()
        )
        results.append(_expect(
            "determinism: synthetic outputs are byte-identical across "
            "two independent runs from identical inputs",
            ok, f"rc_a={rc_a}, rc_b={rc_b}",
        ))

    # ---- 5. provider-mode invariant: neither flag refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _ = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
            ],
            requests=[{"id": "x", "prompt": "abstract pattern, no text"}],
        )
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(workspace=ws, assets_dir=out)
        ok = rc == 2 and "one of --fixtures-dir" in msg and not (out / "x.png").exists()
        results.append(_expect(
            "provider-mode invariant: neither --fixtures-dir nor "
            "--allow-synthetic-bytes refused (real D-One is TODO)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 6. provider-mode invariant: both flags refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _ = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
            ],
            requests=[{"id": "x", "prompt": "abstract pattern, no text"}],
        )
        fixtures = td / "fixtures"
        fixtures.mkdir()
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out,
            fixtures_dir=fixtures, allow_synthetic_bytes=True,
        )
        ok = (
            rc == 2
            and "mutually exclusive" in msg
            and not (out / "x.png").exists()
        )
        results.append(_expect(
            "provider-mode invariant: --fixtures-dir AND "
            "--allow-synthetic-bytes refused as mutually exclusive",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 7. missing fixture refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _ = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "missing", "local_path": "media/missing.png", "source": "d_one_local"},
            ],
            requests=[{"id": "missing", "prompt": "abstract pattern, no text"}],
        )
        fixtures = td / "fixtures"
        fixtures.mkdir()
        # fixtures-dir intentionally empty; the requested id has no
        # matching fixture file.
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, fixtures_dir=fixtures,
        )
        ok = (
            rc == 1
            and "fixture" in msg
            and "does not exist" in msg
            and not (out / "missing.png").exists()
        )
        results.append(_expect(
            "fixture mode: missing fixture for a declared id refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 8. fixture with wrong magic bytes refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _ = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "wrong", "local_path": "media/wrong.png", "source": "d_one_local"},
            ],
            requests=[{"id": "wrong", "prompt": "abstract pattern, no text"}],
        )
        fixtures = td / "fixtures"
        fixtures.mkdir()
        # .png extension but JPEG magic header.
        (fixtures / "wrong.png").write_bytes(b"\xff\xd8\xff\xe0not a png")
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, fixtures_dir=fixtures,
        )
        ok = (
            rc == 1
            and "magic bytes" in msg
            and not (out / "wrong.png").exists()
        )
        results.append(_expect(
            "fixture mode: fixture whose bytes do not match the declared "
            "extension's magic signature refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 9. symlinked fixture refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _ = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "lnk", "local_path": "media/lnk.png", "source": "d_one_local"},
            ],
            requests=[{"id": "lnk", "prompt": "abstract pattern, no text"}],
        )
        fixtures = td / "fixtures"
        fixtures.mkdir()
        real_fixture = td / "real_fixture.png"
        real_fixture.write_bytes(_SYNTHETIC_PNG_BYTES)
        (fixtures / "lnk.png").symlink_to(real_fixture)
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, fixtures_dir=fixtures,
        )
        ok = (
            rc == 1
            and "symlink" in msg
            and not (out / "lnk.png").exists()
        )
        results.append(_expect(
            "fixture mode: symlinked fixture refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 10. pre-existing output target refused (no overwrite). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _ = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
            ],
            requests=[{"id": "x", "prompt": "abstract pattern, no text"}],
        )
        out = td / "out"
        out.mkdir()
        prior_bytes = b"do-not-overwrite"
        (out / "x.png").write_bytes(prior_bytes)
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
        )
        ok = (
            rc == 1
            and "already exists" in msg
            and (out / "x.png").read_bytes() == prior_bytes
        )
        results.append(_expect(
            "pre-existing output target refused; prior bytes preserved",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 11. symlink at --assets-dir refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _ = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
            ],
            requests=[{"id": "x", "prompt": "abstract pattern, no text"}],
        )
        real_out = td / "real_out"
        real_out.mkdir()
        link_out = td / "link_out"
        link_out.symlink_to(real_out)
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=link_out, allow_synthetic_bytes=True,
        )
        ok = (
            rc == 2
            and "symlink" in msg
            and not (real_out / "x.png").exists()
        )
        results.append(_expect(
            "symlink at --assets-dir refused; nothing written through it",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 12. symlink at --fixtures-dir refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _ = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
            ],
            requests=[{"id": "x", "prompt": "abstract pattern, no text"}],
        )
        real_fix = td / "real_fix"
        real_fix.mkdir()
        link_fix = td / "link_fix"
        link_fix.symlink_to(real_fix)
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, fixtures_dir=link_fix,
        )
        ok = (
            rc == 2
            and "symlink" in msg
            and not (out / "x.png").exists()
        )
        results.append(_expect(
            "symlink at --fixtures-dir refused; nothing written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 13. symlink at --workspace refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        real_ws, _ = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
            ],
            requests=[{"id": "x", "prompt": "abstract pattern, no text"}],
        )
        link_ws = td / "link_ws"
        link_ws.symlink_to(real_ws)
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=link_ws, assets_dir=out, allow_synthetic_bytes=True,
        )
        ok = rc == 2 and "symlink" in msg and not (out / "x.png").exists()
        results.append(_expect(
            "symlink at --workspace refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 14. URI-shaped arguments refused at the string layer. ----
    rc, msg = run_d_one_generation(
        workspace=Path("https://attacker.example/ws"),
        assets_dir=Path("/tmp/out"),
        allow_synthetic_bytes=True,
    )
    ok = rc == 2 and "URI" in msg
    results.append(_expect(
        "URI-shaped --workspace refused at the string layer",
        ok, f"rc={rc}, msg={msg!r}",
    ))
    rc, msg = run_d_one_generation(
        workspace=Path("/tmp/ws"),
        assets_dir=Path("data:application/json,{}"),
        allow_synthetic_bytes=True,
    )
    ok = rc == 2 and "URI" in msg
    results.append(_expect(
        "URI-shaped --assets-dir refused at the string layer",
        ok, f"rc={rc}, msg={msg!r}",
    ))
    rc, msg = run_d_one_generation(
        workspace=Path("/tmp/ws"),
        assets_dir=Path("/tmp/out"),
        plan=Path("https://attacker.example/plan.json"),
        allow_synthetic_bytes=True,
    )
    ok = rc == 2 and "URI" in msg
    results.append(_expect(
        "URI-shaped --plan refused at the string layer",
        ok, f"rc={rc}, msg={msg!r}",
    ))
    rc, msg = run_d_one_generation(
        workspace=Path("/tmp/ws"),
        assets_dir=Path("/tmp/out"),
        fixtures_dir=Path("s3://bucket/key"),
    )
    ok = rc == 2 and "URI" in msg
    results.append(_expect(
        "URI-shaped --fixtures-dir refused at the string layer",
        ok, f"rc={rc}, msg={msg!r}",
    ))

    # ---- 15. plan with unsupported extension refused. The plan
    # writer (done_image_adapter) does not gate on extension because
    # the manifest schema does not restrict it; the runner therefore
    # has to own that gate so a manifest whose local_path is
    # foo.svg / foo.gif / foo.webp fails closed here. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _ = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "vector", "local_path": "media/vector.svg", "source": "d_one_local"},
            ],
            requests=[{"id": "vector", "prompt": "abstract pattern, no text"}],
        )
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
        )
        ok = (
            rc == 1
            and "unsupported extension" in msg
            and not (out / "vector.svg").exists()
        )
        results.append(_expect(
            "plan request with unsupported extension (e.g. .svg) refused; "
            "no output written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 16. path-shaped manifest id refused at the flat-layout gate
    # before any write. local_path_is_safe rejects '..' segments and
    # URI schemes but DOES allow internal '/', so an id like 'a/b'
    # would otherwise slip through, create a subdirectory under
    # --assets-dir, and break the handoff to
    # scripts/materialize_image_assets.py (whose iterdir-based
    # undeclared-asset gate refuses any subdirectory at the
    # assets-dir root). Regression: keep this case failing at the
    # runner with a clear flat-layout diagnostic instead of
    # cascading into materialize's "subdirectory" error. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _ = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "a/b", "local_path": "media/a_b.png", "source": "d_one_local"},
            ],
            requests=[{"id": "a/b", "prompt": "abstract pattern, no text"}],
        )
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
        )
        # No file should have been written, AND no subdirectory should
        # have been created. The latter is the key regression — earlier
        # code would have done target.parent.mkdir(parents=True, ...)
        # before the rollback unlinked the leaf, leaving 'out/a/'
        # behind to confuse the next run.
        ok = (
            rc == 1
            and "path separator" in msg
            and not (out / "a" / "b.png").exists()
            and not (out / "a").exists()
        )
        results.append(_expect(
            "path-shaped id (e.g. 'a/b') refused at the flat-layout gate "
            "before any write; no subdirectory created under --assets-dir",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 17. plan-validator gate fires before any output is written:
    # a plan whose prompt was hand-tampered to inject a URL is refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
            ],
            requests=[{"id": "x", "prompt": "abstract pattern, no text"}],
        )
        # Hand-tamper the just-written plan.
        body = json.loads(plan_path.read_text())
        body["requests"][0]["prompt"] = "see https://attacker.example/x"
        plan_path.write_text(
            json.dumps(body, indent=2, sort_keys=True) + "\n"
        )
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
        )
        ok = (
            rc == 1
            and "URI scheme" in msg
            and not (out / "x.png").exists()
        )
        results.append(_expect(
            "plan-validator gate fires before any output is written "
            "(tampered prompt with URL refused)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 18. workspace + plan + manifest byte-identical post-success. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
            ],
            requests=[{"id": "x", "prompt": "abstract pattern, no text"}],
        )
        manifest_path = ws / IMAGE_MANIFEST_FILENAME
        before_manifest = manifest_path.read_bytes()
        before_plan = plan_path.read_bytes()
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
        )
        ok = (
            rc == 0
            and manifest_path.read_bytes() == before_manifest
            and plan_path.read_bytes() == before_plan
        )
        results.append(_expect(
            "workspace post-condition: image_manifest.json and plan "
            "bytes byte-identical pre/post a successful run",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 19. mid-write rollback: a monkey-patched write_bytes raises;
    # both scheduled outputs return to the pre-call state. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _ = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "a", "local_path": "media/a.png", "source": "d_one_local"},
                {"id": "b", "local_path": "media/b.png", "source": "d_one_local"},
            ],
            requests=[
                {"id": "a", "prompt": "first abstract pattern, no text"},
                {"id": "b", "prompt": "second abstract pattern, no text"},
            ],
        )
        out = td / "out"
        out.mkdir()
        before = _list_dir_files(out)
        original_write_bytes = Path.write_bytes

        def fake_write_bytes(self: Path, payload: bytes) -> int:
            if self.name == "b.png":
                raise OSError("simulated disk-full")
            return original_write_bytes(self, payload)

        Path.write_bytes = fake_write_bytes  # type: ignore[assignment]
        try:
            rc, msg = run_d_one_generation(
                workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
            )
        finally:
            Path.write_bytes = original_write_bytes  # type: ignore[assignment]
        after = _list_dir_files(out)
        ok = rc == 1 and "rolled back" in msg and before == after
        results.append(_expect(
            "mid-write failure rolls back every output written so far "
            "(no half-materialized assets-dir)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 20. workspace missing image_manifest.json refused (the
    # validator owns this gate). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws"
        ws.mkdir()
        # Plan file written by hand against a schema-valid shape but
        # with no manifest present in the workspace.
        plan_body = {
            "schema_version": 1,
            "mode": "dry_run",
            "note": "D-One adapter contract stub: synthetic test plan",
            "request_count": 1,
            "requests": [
                {
                    "id": "x",
                    "prompt": "abstract pattern, no text",
                    "manifest_local_path": "media/x.png",
                    "manifest_source": "d_one_local",
                },
            ],
        }
        (ws / DEFAULT_PLAN_FILENAME).write_text(
            json.dumps(plan_body, indent=2, sort_keys=True) + "\n"
        )
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
        )
        ok = (
            rc == 2
            and "image_manifest.json" in msg
            and not (out / "x.png").exists()
        )
        results.append(_expect(
            "workspace missing image_manifest.json refused (validator "
            "preflight)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 21. plan file missing refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws"
        _adapter._seed_workspace(ws, images=[
            {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
        ])
        # No plan written.
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
        )
        ok = (
            rc == 2
            and "does not exist" in msg
            and not (out / "x.png").exists()
        )
        results.append(_expect(
            "plan file missing refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 22. plan + materialize end-to-end with fixtures: the runner's
    # output flows through materialize_image_assets with --assets-dir
    # equal to the runner's output dir. Catches a regression where the
    # runner's <id>.<ext> naming convention drifts from the one
    # materialize expects (the contract that lets a downstream caller
    # chain the two helpers without reshuffling files). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _ = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "gamma", "local_path": "art/gamma.jpeg", "source": "d_one_local"},
            ],
            requests=[{"id": "gamma", "prompt": "abstract texture, no text"}],
        )
        fixtures = td / "fixtures"
        fixtures.mkdir()
        # The runner lower-cases the extension; the fixture filename
        # uses the lower-cased extension to match.
        gamma_bytes = (
            b"\xff\xd8\xff\xe0"
            + b"\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            + b"abcdefghijklmnop"
            + b"\xff\xd9"
        )
        (fixtures / "gamma.jpeg").write_bytes(gamma_bytes)
        out = td / "out"
        out.mkdir()
        rc_run, msg_run = run_d_one_generation(
            workspace=ws, assets_dir=out, fixtures_dir=fixtures,
        )
        rc_mat, msg_mat = _mat.materialize_image_assets(
            workspace=ws, assets_dir=out,
        )
        gamma_target = ws / "art" / "gamma.jpeg"
        ok = (
            rc_run == 0
            and rc_mat == 0
            and gamma_target.is_file()
            and gamma_target.read_bytes() == gamma_bytes
        )
        results.append(_expect(
            "end-to-end fixture mode: runner output (gamma.jpeg) flows "
            "through materialize_image_assets and lands at the manifest's "
            "local_path with byte-identical fixture bytes",
            ok, f"rc_run={rc_run}, rc_mat={rc_mat}, msg_mat={msg_mat!r}",
        ))

    # ---- 23. no extraneous files: a successful synthetic run produces
    # ONLY the <id>.<ext> outputs (no metadata files, no plan copies). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, _ = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
                {"id": "y", "local_path": "media/y.jpg", "source": "d_one_local"},
            ],
            requests=[
                {"id": "x", "prompt": "abstract pattern, no text"},
                {"id": "y", "prompt": "calm gradient, no text"},
            ],
        )
        out = td / "out"
        out.mkdir()
        before = _list_dir_files(out)
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
        )
        after = _list_dir_files(out)
        ok = (
            rc == 0
            and after - before == {"x.png", "y.jpg"}
        )
        results.append(_expect(
            "no extraneous files: a successful synthetic run produces "
            "ONLY the <id>.<ext> outputs (no metadata, no plan copies)",
            ok, f"rc={rc}, msg={msg!r}, only_new={after-before}",
        ))

    # =========================================================================
    # --descriptor-vocabulary taxonomy scenarios.
    #
    # The mock runner must accept taxonomy-bearing plans so the writer
    # → mock chain is not a dead end. The validator (delegated via
    # done_image_adapter.validate_plan_file) requires the same vocab the
    # writer used; the runner forwards --descriptor-vocabulary verbatim.
    # Byte-identical post-condition on the vocab file is also asserted.
    # =========================================================================

    # ---- TAX1. taxonomy-bearing plan + matching --descriptor-vocabulary
    # round-trips through the mock runner end-to-end. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        vocab = _seed_descriptor_vocab(td)
        ws, plan_path = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "spot", "local_path": "media/spot.png", "source": "d_one_local"},
            ],
            requests=[
                {
                    "id": "spot",
                    "prompt": "an abstract calm geometric pattern, no text",
                    "rendering_style": "flat_vector",
                    "palette_family": "neutral_grey",
                    "image_role": "decorative_accent",
                    "layout_pattern": "single_center",
                    "modifier": "negative_space",
                },
            ],
            descriptor_vocabulary=vocab,
        )
        out = td / "out"
        out.mkdir()
        vocab_bytes_before = vocab.read_bytes()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
            descriptor_vocabulary=vocab,
        )
        png = out / "spot.png"
        ok = (
            rc == 0
            and png.is_file() and not png.is_symlink()
            and png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            and vocab.read_bytes() == vocab_bytes_before
        )
        results.append(_expect(
            "taxonomy: a taxonomy-bearing plan + matching "
            "--descriptor-vocabulary round-trips through the synthetic "
            "runner; vocab bytes byte-identical post-run",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- TAX2. taxonomy-bearing plan WITHOUT --descriptor-vocabulary
    # is refused by the runner (the delegated validator surfaces the
    # 'plan carries taxonomy field(s) but --descriptor-vocabulary was
    # not supplied' diagnostic; no output bytes land). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        vocab = _seed_descriptor_vocab(td)
        ws, plan_path = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "spot", "local_path": "media/spot.png", "source": "d_one_local"},
            ],
            requests=[
                {
                    "id": "spot",
                    "prompt": "an abstract pattern, no text",
                    "rendering_style": "flat_vector",
                },
            ],
            descriptor_vocabulary=vocab,
        )
        out = td / "out"
        out.mkdir()
        before = _list_dir_files(out)
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
        )
        after = _list_dir_files(out)
        ok = (
            rc == 1
            and "--descriptor-vocabulary" in msg
            and "rendering_style" in msg
            and after == before
        )
        results.append(_expect(
            "taxonomy: a taxonomy-bearing plan WITHOUT "
            "--descriptor-vocabulary is refused; assets-dir untouched",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- TAX3. plan drift on the runner boundary: a plan whose
    # taxonomy value is regex-shape valid but not in the vocab's
    # allowed_values is refused by the runner. Mirrors the
    # validate-plan-side drift scenario but verifies the dead-end is
    # closed at the runner side too. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        vocab = _seed_descriptor_vocab(td)
        ws, plan_path = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "spot", "local_path": "media/spot.png", "source": "d_one_local"},
            ],
            requests=[
                {
                    "id": "spot",
                    "prompt": "an abstract pattern, no text",
                    "rendering_style": "flat_vector",
                },
            ],
            descriptor_vocabulary=vocab,
        )
        # Drift: rewrite the plan to use a regex-shape valid value that
        # is not in image_taxonomy.rendering_style.allowed_values.
        body = json.loads(plan_path.read_text())
        body["requests"][0]["rendering_style"] = "blueprint_style"
        plan_path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
        out = td / "out"
        out.mkdir()
        before = _list_dir_files(out)
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
            descriptor_vocabulary=vocab,
        )
        after = _list_dir_files(out)
        ok = (
            rc == 1
            and "blueprint_style" in msg
            and "drifted" in msg
            and after == before
        )
        results.append(_expect(
            "taxonomy: plan drift refused at the runner boundary; "
            "assets-dir untouched",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- TAX4. URI-shaped --descriptor-vocabulary refused at the
    # string layer before any filesystem syscall on the runner side. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        vocab = _seed_descriptor_vocab(td)
        ws, plan_path = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "spot", "local_path": "media/spot.png", "source": "d_one_local"},
            ],
            requests=[
                {
                    "id": "spot",
                    "prompt": "an abstract pattern, no text",
                    "rendering_style": "flat_vector",
                },
            ],
            descriptor_vocabulary=vocab,
        )
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
            descriptor_vocabulary=Path("https://attacker.example/v.json"),
        )
        ok = rc == 2 and "URI" in msg
        results.append(_expect(
            "taxonomy: URI-shaped --descriptor-vocabulary refused at "
            "the runner string layer",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- TAX5. symlinked --descriptor-vocabulary refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        real_vocab = _seed_descriptor_vocab(td)
        link_vocab = td / "vocab_link.json"
        link_vocab.symlink_to(real_vocab)
        ws, plan_path = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "spot", "local_path": "media/spot.png", "source": "d_one_local"},
            ],
            requests=[
                {
                    "id": "spot",
                    "prompt": "an abstract pattern, no text",
                    "rendering_style": "flat_vector",
                },
            ],
            descriptor_vocabulary=real_vocab,
        )
        out = td / "out"
        out.mkdir()
        before = _list_dir_files(out)
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
            descriptor_vocabulary=link_vocab,
        )
        after = _list_dir_files(out)
        ok = rc != 0 and "symlink" in msg and after == before
        results.append(_expect(
            "taxonomy: symlinked --descriptor-vocabulary refused; "
            "assets-dir untouched",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- TAX6. taxonomy-free plan with --descriptor-vocabulary
    # supplied still runs (the optional vocab is benign for a plan
    # that does not reference taxonomy). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        vocab = _seed_descriptor_vocab(td)
        ws, plan_path = _seed_workspace_with_plan(
            td,
            images=[
                {"id": "spot", "local_path": "media/spot.png", "source": "d_one_local"},
            ],
            requests=[
                {"id": "spot", "prompt": "abstract pattern, no text"},
            ],
        )
        out = td / "out"
        out.mkdir()
        rc, msg = run_d_one_generation(
            workspace=ws, assets_dir=out, allow_synthetic_bytes=True,
            descriptor_vocabulary=vocab,
        )
        png = out / "spot.png"
        ok = rc == 0 and png.is_file() and not png.is_symlink()
        results.append(_expect(
            "taxonomy: taxonomy-free plan accepts an optional "
            "--descriptor-vocabulary without complaint",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mockable local D-One generation runner (NOT real D-One "
            "integration). Consumes a schema-valid d_one_adapter_plan.json "
            "(written by scripts/done_image_adapter.py) and emits local "
            "PNG / JPG / JPEG bytes named <id>.<ext> into a caller-"
            "supplied output assets directory, matching what "
            "scripts/materialize_image_assets.py consumes. Two mock "
            "providers (mutually exclusive, both purely local): "
            "--fixtures-dir copies caller-supplied PNG/JPG/JPEG bytes "
            "verbatim; --allow-synthetic-bytes emits a fixed "
            "magic-byte-valid payload per extension. Optional "
            "--descriptor-vocabulary <path-to-d_one_descriptor_vocabulary.json>"
            " is forwarded verbatim to done_image_adapter.validate_plan_file"
            " and is REQUIRED iff the plan carries one or more of the "
            "five taxonomy fields (rendering_style / palette_family / "
            "image_role / layout_pattern / modifier); the runner refuses "
            "to certify a taxonomy-bearing plan whose values cannot be "
            "re-checked against image_taxonomy.<dim>.allowed_values, and "
            "the vocab bytes are byte-identical pre/post a successful "
            "run. Real D-One / MCP / model-API integration is "
            "intentionally TODO; this runner does NOT call D-One / "
            "Qoder / any public network / any image-generation model / "
            "any external service. Does NOT mutate image_manifest.json "
            "or the plan file. Does NOT generate render_models / "
            "svg_previews / any .pptx. Does NOT change PPTX export "
            "behavior."
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Workspace directory containing image_manifest.json and "
             "(by default) d_one_adapter_plan.json.",
    )
    parser.add_argument(
        "--plan", type=Path, default=None,
        help="Path to the d_one_adapter_plan.json to consume. Defaults "
             "to <workspace>/" + DEFAULT_PLAN_FILENAME + ". Must resolve "
             "to a regular non-symlink JSON file and pass "
             "done_image_adapter --validate-plan — which additionally "
             "requires --descriptor-vocabulary when the plan carries "
             "taxonomy fields.",
    )
    parser.add_argument(
        "--assets-dir", type=Path, default=None,
        help="Output directory; the runner writes <id>.<ext> files at "
             "this location (the flat layout materialize_image_assets "
             "consumes). Must exist as a non-symlink directory; targets "
             "are refused on overwrite / symlink / out-of-dir resolution.",
    )
    parser.add_argument(
        "--fixtures-dir", type=Path, default=None,
        help="Directory of caller-supplied PNG/JPG/JPEG fixture files "
             "named <id>.<ext>. Mutually exclusive with "
             "--allow-synthetic-bytes; exactly one is required.",
    )
    parser.add_argument(
        "--allow-synthetic-bytes", action="store_true",
        help="Emit a fixed minimal PNG or JPEG payload per declared "
             "extension. Intended for self-tests and pipeline smoke "
             "runs. Mutually exclusive with --fixtures-dir; exactly "
             "one is required.",
    )
    parser.add_argument(
        "--descriptor-vocabulary", type=Path, default=None,
        dest="descriptor_vocabulary",
        help="Optional. Path to a d_one_descriptor_vocabulary JSON "
             "file (see schemas/d_one_descriptor_vocabulary.schema.json). "
             "Forwarded verbatim to done_image_adapter.validate_plan_file, "
             "which requires it iff the plan carries any of the five "
             "taxonomy fields (rendering_style / palette_family / "
             "image_role / layout_pattern / modifier) and refuses any "
             "taxonomy value not in image_taxonomy.<dim>.allowed_values. "
             "Refused if URI-shaped, symlinked, missing, or "
             "schema-invalid; byte-identical pre/post a successful run.",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios covering the synthetic "
             "and fixture happy paths, end-to-end materialize hand-off, "
             "determinism, provider-mode invariants, missing / wrong-magic "
             "/ symlinked fixtures, pre-existing output, symlinks at "
             "workspace / assets-dir / fixtures-dir / "
             "descriptor-vocabulary, URI-shaped arguments (including "
             "URI-shaped --descriptor-vocabulary), unsupported "
             "extensions, plan-validator gate, manifest + plan "
             "byte-identical post-success, mid-write rollback, missing "
             "manifest, missing plan, no-extraneous-files guarantee, "
             "AND the --descriptor-vocabulary taxonomy round-trip "
             "(taxonomy-bearing plan + matching vocab succeeds; "
             "taxonomy-bearing plan without vocab refused; plan drift "
             "against vocab refused at the runner boundary; vocab "
             "bytes byte-identical pre/post a successful run; "
             "taxonomy-free plan accepts an optional vocab without "
             "complaint). Exits non-zero if any scenario does not "
             "behave as expected. Mutually exclusive with the other "
             "arguments (--workspace / --plan / --assets-dir / "
             "--fixtures-dir / --allow-synthetic-bytes / "
             "--descriptor-vocabulary).",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if any(
            v is not None for v in (
                args.workspace, args.plan, args.assets_dir,
                args.fixtures_dir, args.descriptor_vocabulary,
            )
        ) or args.allow_synthetic_bytes:
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
                f"FAIL: {fails} self-test scenario(s) did not behave "
                f"as expected."
            )
            return 1
        print(
            "OK (self-test): mockable local D-One generation runner "
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
            f"FAIL: missing required argument(s): "
            f"{', '.join(missing)} (use --self-test for the in-script "
            f"scenarios)",
            file=sys.stderr,
        )
        return 2

    rc, msg = run_d_one_generation(
        workspace=args.workspace,
        assets_dir=args.assets_dir,
        plan=args.plan,
        fixtures_dir=args.fixtures_dir,
        allow_synthetic_bytes=args.allow_synthetic_bytes,
        descriptor_vocabulary=args.descriptor_vocabulary,
    )
    if rc == 0:
        print(msg)
    else:
        print(msg, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
