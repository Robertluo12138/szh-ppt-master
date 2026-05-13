#!/usr/bin/env python3
"""Stage-1 (Intake) workspace initializer.

Seeds a brand-new workspace from a single local Markdown or text source
file. Writes only the two artifacts every downstream stage needs *before*
planning can start:

    <workspace>/input/source.md
    <workspace>/source_manifest.json

The manifest is schema-validated against
``schemas/source_manifest.schema.json`` before this script exits. The
source text itself is never copied into the manifest — only its
workspace-relative path, kind, byte / line counts, and sha256.

What this script does NOT do (intentionally — stages 2-6 stay
agent-driven):

  - it does NOT generate ``deck_brief.json``, ``deck_plan.json``,
    ``design_system.json``, ``slide_plans/*.json``, or
    ``image_manifest.json``;
  - it does NOT call any public network, D-One, Qoder, image
    generation, or external service;
  - it does NOT mutate or inspect any existing file outside
    ``--workspace``;
  - it does NOT log or duplicate the source body text anywhere
    except the verbatim copy at ``<workspace>/input/source.md``.

After this script finishes, the agent must still produce stages 2-6
(deck_brief / deck_plan / design_system / slide_plans / image_manifest)
according to the schemas under ``schemas/`` before
``scripts/run_pipeline.py`` can take over for stages 7-10.

Stdlib-only. Deterministic — the manifest does not embed timestamps or
absolute paths; running ``init_workspace`` twice on the same source +
workspace pair produces byte-identical artifacts (modulo the fact that
the second run is refused because the workspace is non-empty).

Fail-closed gates (every gate aborts the run and writes nothing):

  --source
    * must be a regular file (a symlink is refused — same anti-pattern
      run_pipeline.py rejects at --output / --report-dir);
    * extension must be ``.md`` or ``.txt`` (case-insensitive);
    * must be valid UTF-8 (binary content is refused — we cannot copy
      arbitrary bytes into a ``.md`` file claimed as markdown);
    * must be non-empty (a 0-byte source has no signal for planning);
    * the *string* form of the path must not start with a URI-like
      scheme matching ``^[A-Za-z][A-Za-z0-9+.\-]*:`` — covers
      ``http://``, ``https://``, ``file://``, ``s3://``, ``ftp://``,
      ``data:``, ``mailto:``, ``javascript:``, and every other
      scheme of that shape regardless of whether ``//`` follows the
      ``:``. Path's filesystem checks would already fail for most of
      these, but the explicit string-level guard fires BEFORE
      Path.is_file()/is_symlink() so a URI-shaped string never
      reaches the filesystem layer, and mirrors the rule the rest
      of the repo applies to manifest reference fields.

  --workspace
    * must not be a symlink;
    * its *string* form must not start with a URI-like scheme
      matching ``^[A-Za-z][A-Za-z0-9+.\-]*:`` (same regex as
      ``--source``) — without this guard a URI-shaped argument
      (e.g. ``data:foo`` / ``s3:bucket/key`` / ``https://attacker/ws``)
      would be silently resolved into the CWD and ``mkdir`` would
      happily create a directory whose name carries the scheme
      prefix. The guard runs BEFORE ``Path.resolve()`` so the
      unsafe string never reaches the filesystem layer;
    * if it already exists, must be a directory AND empty (we do not
      overwrite an existing populated workspace);
    * must not resolve to the filesystem root ``/``;
    * must not resolve to the user's HOME directory itself (a workspace
      AT $HOME would shadow ~/Desktop, ~/Documents, ...);
    * must not resolve to or under the repo root (the repo is
      clean-room scaffolding, not a place for generated workspaces);
    * must not resolve to or under a known system directory tree
      (``/etc``, ``/bin``, ``/sbin``, ``/usr``, ``/dev``, ``/proc``,
      ``/sys``, ``/System``, ``/Library/System``). ``/tmp`` and
      ``/var/folders/...`` (macOS tempdir root) are allowed because
      they are legitimate workspace locations.

  --source-id
    * defaults to the source filename stem when not supplied;
    * must match the schema id pattern (``^[A-Za-z0-9][A-Za-z0-9_.\\-]*$``)
      AND pass ``local_path_is_safe`` — rejecting URI schemes, leading
      slash, ``..`` segments, etc. so the id can never carry a path
      payload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "schemas"

sys.path.insert(0, str(SCRIPTS_DIR))

from validate_artifacts import validate_artifact  # noqa: E402
from validate_scaffold import local_path_is_safe  # noqa: E402

SOURCE_MANIFEST_SCHEMA = SCHEMAS_DIR / "source_manifest.schema.json"
SOURCE_MANIFEST_FILENAME = "source_manifest.json"
INPUT_SUBDIR = "input"
INPUT_FILENAME = "source.md"

# URI-scheme guard for --source and --workspace string values. CLI
# args may legitimately be POSIX-absolute paths (e.g. /Users/me/foo.md
# or /tmp/my_workspace), so this guard does NOT apply
# local_path_is_safe's leading-slash rule. The URI-scheme regex
# itself mirrors local_path_is_safe's — no trailing slash required —
# so http://, https://, file://, s3://, ftp://, data:, mailto:,
# javascript:, and anything else of the form ALPHA *( ALPHA / DIGIT /
# "+" / "-" / "." ) ":" are all rejected. A narrower regex that
# required ":[/\\]" after the scheme would miss data: / mailto: /
# javascript: — exactly the schemes the public docs claim are rejected.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Workspace path must not resolve into these system trees. Tempdir
# roots (/tmp, /var/folders/... on macOS) are NOT in this list because
# they are legitimate workspace locations. The list is conservative:
# /usr is refused as a whole rather than carving out /usr/local/share
# etc., because users who want a workspace there can pick an explicit
# subdir like /usr/local/share/decks/<name> — refusing the parent root
# is the simpler, safer default.
_UNSAFE_SYSTEM_ROOTS = (
    "/etc", "/bin", "/sbin", "/usr",
    "/dev", "/proc", "/sys",
    "/System", "/Library/System",
)

_SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


def _has_uri_scheme(s: str) -> bool:
    return bool(_URI_SCHEME_PREFIX.match(s))


def _resolves_under(p: Path, root: Path) -> bool:
    """True iff p (resolved) is `root` itself or under it (resolved)."""
    try:
        p_r = p.resolve()
        root_r = root.resolve()
    except OSError:
        return False
    if p_r == root_r:
        return True
    try:
        p_r.relative_to(root_r)
    except ValueError:
        return False
    return True


def _workspace_location_is_safe(workspace: Path) -> tuple[bool, str]:
    """Refuse a --workspace that resolves to a location we will not
    write into. Returns (ok, reason). Reason is "" when ok is True.

    These checks are intentionally string/path-shape only; we do NOT
    open or stat anything under the candidate location."""
    # A URI-shaped workspace string (e.g. `data:foo`, `mailto:x`,
    # `s3:bucket/key`, `https://example.com/ws`) would otherwise be
    # treated as a relative path and resolved into the current working
    # directory — `mkdir` would then create a literal directory whose
    # name carries a scheme prefix. Reject it at the same string level
    # we reject URI-shaped --source values. The check runs BEFORE
    # resolve()/exists() so the unsafe string never reaches the
    # filesystem.
    if _has_uri_scheme(str(workspace)):
        return False, (
            f"workspace path {workspace} looks like a URI; init_workspace "
            f"only accepts local directory paths"
        )
    try:
        ws_resolved = workspace.resolve()
    except OSError as exc:
        return False, f"workspace path cannot be resolved: {exc}"

    if str(ws_resolved) == os.sep:
        return False, "workspace resolves to the filesystem root"

    home = Path(os.path.expanduser("~")).resolve()
    if ws_resolved == home:
        return False, (
            f"workspace resolves to the user's HOME directory ({home}); "
            f"pick a subdirectory like ~/Desktop/<name>"
        )

    if _resolves_under(workspace, REPO_ROOT):
        return False, (
            f"workspace resolves inside the repo root ({REPO_ROOT}); "
            f"pick a path outside this repository so generated workspaces "
            f"don't pollute the source tree"
        )

    for sysroot in _UNSAFE_SYSTEM_ROOTS:
        sysroot_path = Path(sysroot)
        if not sysroot_path.exists():
            # Skip system roots that aren't present on this OS (e.g.
            # /System on Linux). Refusal is purely defensive; absence
            # means there's nothing here to protect.
            continue
        if _resolves_under(workspace, sysroot_path):
            return False, (
                f"workspace resolves inside system directory "
                f"{sysroot_path} ({ws_resolved})"
            )

    return True, ""


def _validate_source_file(source: Path) -> tuple[bool, str, bytes, str]:
    """Validate a --source path and return (ok, reason, raw_bytes, kind).

    kind is "markdown" for .md and "text" for .txt; both are
    case-insensitive."""
    if _has_uri_scheme(str(source)):
        return False, (
            f"--source {source} looks like a URI; init_workspace only "
            f"accepts local file paths"
        ), b"", ""

    if source.is_symlink():
        return False, (
            f"--source {source} is a symlink; refusing to follow it. "
            f"Pass a regular file path."
        ), b"", ""

    if not source.exists():
        return False, f"--source {source} does not exist", b"", ""

    if not source.is_file():
        return False, (
            f"--source {source} is not a regular file"
        ), b"", ""

    suffix = source.suffix.lower()
    if suffix == ".md":
        kind = "markdown"
    elif suffix == ".txt":
        kind = "text"
    else:
        return False, (
            f"--source {source} has unsupported extension {suffix!r}; "
            f"only .md and .txt are accepted"
        ), b"", ""

    try:
        raw = source.read_bytes()
    except OSError as exc:
        return False, f"--source {source} could not be read: {exc}", b"", ""

    if not raw:
        return False, (
            f"--source {source} is empty; planning needs at least one "
            f"line of source text"
        ), b"", ""

    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return False, (
            f"--source {source} is not valid UTF-8 ({exc}); refusing to "
            f"copy binary content into input/source.md"
        ), b"", ""

    return True, "", raw, kind


def _line_count(raw: bytes) -> int:
    """Count lines: number of '\\n' bytes, plus one if the file does
    not end in '\\n'. Treats an all-empty file as 0 lines, but we've
    already rejected empty sources upstream."""
    if not raw:
        return 0
    n = raw.count(b"\n")
    if not raw.endswith(b"\n"):
        n += 1
    return n


def _resolve_source_id(arg: str | None, source: Path) -> tuple[str | None, str]:
    """Return (id, reason). When arg is None, derive id from the source
    filename stem. Validate against the schema pattern AND the repo's
    local_path_is_safe rule."""
    if arg is not None:
        candidate = arg
    else:
        candidate = source.stem
    if not candidate:
        return None, (
            "--source-id is empty (and could not be derived from "
            f"--source {source} filename stem)"
        )
    if not _SOURCE_ID_PATTERN.match(candidate):
        return None, (
            f"--source-id {candidate!r} does not match "
            f"^[A-Za-z0-9][A-Za-z0-9_.\\-]*$ (ASCII letters / digits / "
            f"underscore / dot / hyphen; must not start with a separator)"
        )
    if not local_path_is_safe(candidate):
        return None, (
            f"--source-id {candidate!r} fails local_path_is_safe (URI "
            f"scheme, leading slash, '..' segment, or empty)"
        )
    return candidate, ""


def _build_manifest(
    source_id: str,
    raw: bytes,
    kind: str,
) -> dict:
    # Defense-in-depth: the manifest's local_path is hardcoded
    # to f"{INPUT_SUBDIR}/{INPUT_FILENAME}" today, and the schema
    # enum-locks it to "input/source.md". If a future code change
    # drifts either constant to something unsafe (a leading slash,
    # a '..' segment, a URI scheme, ...) we want the build to fail
    # CLOSED here — before any filesystem write — rather than rely
    # solely on the schema gate. local_path_is_safe is the same
    # rule applied to image_manifest.local_path and template.theme_ref
    # elsewhere in the repo.
    local_path = f"{INPUT_SUBDIR}/{INPUT_FILENAME}"
    if not local_path_is_safe(local_path):
        raise ValueError(
            f"internal contract violation: built source_manifest "
            f"local_path {local_path!r} fails local_path_is_safe; "
            f"a code change must have drifted INPUT_SUBDIR / "
            f"INPUT_FILENAME away from a safe workspace-relative "
            f"path. Refusing to build a manifest that the schema "
            f"would (correctly) reject."
        )
    return {
        "schema_version": "1",
        "source": {
            "id": source_id,
            "local_path": local_path,
            "kind": kind,
            "byte_count": len(raw),
            "line_count": _line_count(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "tool": {
            "name": "init_workspace",
            "version": "1",
        },
    }


def _rollback_partial_writes(
    workspace: Path,
    workspace_pre_existed: bool,
) -> list[str]:
    """Best-effort cleanup of files this run wrote inside the
    workspace. Returns human-readable notes describing what was
    removed (or what could not be removed) so the caller can surface
    them in the FAIL message.

    Cleanup targets, in reverse order of creation:

      1. ``<workspace>/source_manifest.json``
      2. ``<workspace>/input/source.md``
      3. ``<workspace>/input/``     (only if empty after step 2)
      4. ``<workspace>/``            (only if this run created the
                                      directory; the workspace-must-be-
                                      empty preflight gate guarantees we
                                      never had unrelated content to
                                      preserve)

    Errors during cleanup are swallowed (and recorded in the notes
    list). The caller has already decided to fail; the original
    error must reach the user, so rollback never raises."""
    notes: list[str] = []
    manifest_path = workspace / SOURCE_MANIFEST_FILENAME
    input_dir = workspace / INPUT_SUBDIR
    source_copy_path = input_dir / INPUT_FILENAME

    for p in (manifest_path, source_copy_path):
        try:
            if p.is_file():
                p.unlink()
                notes.append(f"removed {p}")
        except OSError as exc:
            notes.append(f"could not remove {p}: {exc}")

    try:
        if input_dir.is_dir() and not any(input_dir.iterdir()):
            input_dir.rmdir()
            notes.append(f"removed empty {input_dir}/")
    except OSError as exc:
        notes.append(f"could not remove {input_dir}/: {exc}")

    if not workspace_pre_existed:
        try:
            if workspace.is_dir() and not any(workspace.iterdir()):
                workspace.rmdir()
                notes.append(f"removed empty {workspace}/")
        except OSError as exc:
            notes.append(f"could not remove {workspace}/: {exc}")

    return notes


def init_workspace(
    source: Path,
    workspace: Path,
    source_id: str | None,
) -> tuple[int, str]:
    """Run the full intake. Returns (exit_code, message).

    Filesystem contract: preflight failures (bad ``--source`` / bad
    ``--workspace`` / bad ``--source-id`` / in-memory schema mismatch
    / pre-write schema-walker exception) leave the filesystem
    untouched — we have not yet called ``mkdir`` or ``write_*``.

    A post-preflight failure triggers a best-effort rollback via
    ``_rollback_partial_writes``: the manifest, ``input/source.md``,
    the ``input/`` subdir, and (only if this run created it) the
    workspace directory itself are removed in reverse order. The
    rollback's notes are appended to the FAIL message so the caller
    can see exactly what state was left, even on a partial-cleanup
    edge case. Post-preflight failures that trigger rollback include:

      - any ``Exception`` or ``SystemExit`` raised mid-write —
        ``OSError`` from a filesystem failure, ``TypeError`` from
        ``json.dumps`` on a non-serializable manifest, etc.;
      - the post-write re-validator returning a non-empty errors
        list (the on-disk manifest is schema-invalid);
      - the post-write re-validator RAISING — ``validate_artifact``
        raises ``SystemExit`` on its own read-error branch
        (``OSError`` / ``json.JSONDecodeError``), and ``SystemExit``
        does not inherit from ``Exception``, so the catch clause is
        explicitly ``(Exception, SystemExit)``. A bare
        ``except Exception:`` would let ``SystemExit`` bypass
        rollback entirely and leave the half-written workspace on
        disk — exactly the contract violation this docstring
        forbids.

    ``KeyboardInterrupt`` and ``GeneratorExit`` (other
    ``BaseException`` subclasses) are deliberately NOT caught so
    Ctrl-C and generator-cleanup semantics remain intact."""
    ok, reason, raw, kind = _validate_source_file(source)
    if not ok:
        return 2, f"FAIL: {reason}"

    resolved_id, id_reason = _resolve_source_id(source_id, source)
    if resolved_id is None:
        return 2, f"FAIL: {id_reason}"

    if workspace.is_symlink():
        return 2, (
            f"FAIL: --workspace {workspace} is a symlink; refusing to "
            f"follow it. Pass a regular directory path."
        )
    if workspace.exists() and not workspace.is_dir():
        return 2, (
            f"FAIL: --workspace {workspace} exists and is not a "
            f"directory; refusing to overwrite."
        )

    ws_ok, ws_reason = _workspace_location_is_safe(workspace)
    if not ws_ok:
        return 2, f"FAIL: --workspace rejected: {ws_reason}"

    if workspace.exists():
        try:
            existing = list(workspace.iterdir())
        except OSError as exc:
            return 2, (
                f"FAIL: --workspace {workspace} exists but cannot be "
                f"listed: {exc}"
            )
        if existing:
            sample = ", ".join(sorted(p.name for p in existing)[:5])
            return 2, (
                f"FAIL: --workspace {workspace} already exists and is "
                f"non-empty (found: {sample}); refusing to overwrite. "
                f"Pick a fresh path or empty the directory first."
            )

    # All preflight gates passed. Build the manifest in memory and
    # validate it against the schema BEFORE touching the filesystem,
    # so a mid-write crash cannot leave a half-written workspace.
    # _validate_manifest_in_memory reads the schema and walks the
    # manifest; both can raise (OSError on schema read, JSONDecodeError
    # on a malformed schema, RecursionError, etc.). Wrap it so any
    # such exception surfaces as a clean FAIL instead of a traceback.
    # No rollback is needed here — nothing has been written.
    manifest = _build_manifest(resolved_id, raw, kind)
    try:
        schema_errors = _validate_manifest_in_memory(manifest)
    except (Exception, SystemExit) as exc:
        return 1, (
            f"FAIL: pre-write schema validation of the in-memory "
            f"manifest raised {type(exc).__name__}: {exc}"
        )
    if schema_errors:
        # Unreachable in practice — the manifest is built by this
        # script from validated inputs — but if the schema ever drifts
        # from the builder, we want a fail-closed report, not a
        # silently-broken workspace on disk.
        return 1, (
            "FAIL: the manifest this script just built does not match "
            f"schemas/{SOURCE_MANIFEST_SCHEMA.name}: "
            + "; ".join(schema_errors)
        )

    # Filesystem mutations from here on. We create the workspace dir
    # (idempotent if it already existed as an empty directory) and
    # write both artifacts. Track whether the workspace pre-existed so
    # the rollback path knows whether to also remove the workspace
    # directory itself (only if this run created it).
    #
    # The except clause is intentionally broad (Exception + SystemExit):
    # OSError covers filesystem failures, but json.dumps could raise
    # TypeError if anything ever feeds a non-serializable value into
    # _build_manifest, a sub-process could in theory raise SystemExit,
    # and the contract is "no half-written workspace ever survives a
    # failure". A bare `except OSError` would let those bypass rollback.
    # KeyboardInterrupt / GeneratorExit (BaseException-but-not-
    # SystemExit) are deliberately NOT caught so Ctrl-C still works.
    workspace_pre_existed = workspace.exists()
    manifest_path = workspace / SOURCE_MANIFEST_FILENAME
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / INPUT_SUBDIR).mkdir(parents=True, exist_ok=True)
        (workspace / INPUT_SUBDIR / INPUT_FILENAME).write_bytes(raw)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
    except (Exception, SystemExit) as exc:
        notes = _rollback_partial_writes(workspace, workspace_pre_existed)
        return 2, (
            f"FAIL: writing workspace {workspace} raised "
            f"{type(exc).__name__}: {exc}\n"
            f"rolled back: {'; '.join(notes) if notes else 'nothing to remove'}"
        )

    # Re-validate the on-disk manifest with the live schema-checker
    # one more time as a defense-in-depth gate. The gate can fail two
    # ways:
    #
    #   1. validate_artifact returns a non-empty list of errors — the
    #      on-disk manifest is schema-invalid.
    #   2. validate_artifact RAISES — it raises SystemExit from its
    #      own read-error branch (OSError / json.JSONDecodeError
    #      reading the schema or the just-written manifest), and the
    #      internal _validate walker could in theory raise on
    #      adversarial input (RecursionError) or on a malformed
    #      schema field (re.error). SystemExit does NOT inherit from
    #      Exception, so a bare `except Exception:` would let it
    #      bypass rollback entirely and leave the half-written
    #      workspace on disk — exactly the contract violation the
    #      docstring forbids.
    #
    # Both paths roll back the partial writes before returning so the
    # caller's filesystem never reflects a half-broken workspace.
    try:
        errors = validate_artifact(manifest_path, SOURCE_MANIFEST_SCHEMA)
    except (Exception, SystemExit) as exc:
        notes = _rollback_partial_writes(workspace, workspace_pre_existed)
        return 1, (
            f"FAIL: post-write re-validation of {manifest_path} "
            f"raised {type(exc).__name__}: {exc}\n"
            f"rolled back: {'; '.join(notes) if notes else 'nothing to remove'}"
        )
    if errors:
        notes = _rollback_partial_writes(workspace, workspace_pre_existed)
        return 1, (
            f"FAIL: on-disk manifest at {manifest_path} did not "
            f"re-validate: {errors}\n"
            f"rolled back: {'; '.join(notes) if notes else 'nothing to remove'}"
        )

    return 0, (
        f"OK: workspace seeded at {workspace}.\n"
        f"  source: {workspace / INPUT_SUBDIR / INPUT_FILENAME} "
        f"({len(raw)} bytes, {manifest['source']['line_count']} lines, "
        f"sha256={manifest['source']['sha256']})\n"
        f"  manifest: {manifest_path}\n"
        f"  source_id: {resolved_id}\n"
        f"Next stages (agent-driven; init_workspace.py does not "
        f"automate them):\n"
        f"  2. deck_brief.json  (declare {resolved_id!r} in source_refs)\n"
        f"  3. deck_plan.json\n"
        f"  4. design_system.json\n"
        f"  5. slide_plans/*.json\n"
        f"  6. image_manifest.json\n"
        f"Once those exist, scripts/run_pipeline.py can take over for "
        f"stages 7-10."
    )


def _validate_manifest_in_memory(manifest: dict) -> list[str]:
    """Schema-validate without touching disk. Uses validate_artifacts'
    internal _validate() against the cached schema."""
    schema = json.loads(SOURCE_MANIFEST_SCHEMA.read_text())
    # validate_artifacts._validate writes into the errors list it is
    # given; import it lazily so the top-of-file import block stays
    # focused on the public validate_artifact entrypoint.
    from validate_artifacts import _validate  # noqa: WPS433
    errors: list[str] = []
    _validate(manifest, schema, "<root>", errors)
    return errors


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs under tempfile.TemporaryDirectory()
# with a synthetic source file written inline; no fixture leaks into the repo
# and no real source content is ever embedded in this script.
# ---------------------------------------------------------------------------


_SYNTH_MD = (
    "# Synthetic Source\n\n"
    "This is a synthetic .md source used only by the self-test.\n"
    "Line three.\n"
)
_SYNTH_TXT = "Synthetic text source.\nSecond line.\nThird line.\n"


def _invoke_self(extra: list[str]) -> tuple[int, str, str]:
    cmd = [sys.executable, str(Path(__file__).resolve())] + extra
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _expect(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


def _run_self_tests() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)

        # 1. happy path: .md source
        md_src = td / "synthetic_brief.md"
        md_src.write_text(_SYNTH_MD)
        ws_md = td / "ws_md"
        rc, sout, _serr = _invoke_self([
            "--source", str(md_src),
            "--workspace", str(ws_md),
        ])
        manifest_path = ws_md / SOURCE_MANIFEST_FILENAME
        copy_path = ws_md / INPUT_SUBDIR / INPUT_FILENAME
        ok = (
            rc == 0
            and copy_path.is_file()
            and copy_path.read_bytes() == _SYNTH_MD.encode("utf-8")
            and manifest_path.is_file()
        )
        if ok:
            m = json.loads(manifest_path.read_text())
            ok = (
                m["schema_version"] == "1"
                and m["source"]["kind"] == "markdown"
                and m["source"]["id"] == "synthetic_brief"
                and m["source"]["local_path"] == "input/source.md"
                and m["source"]["byte_count"] == len(_SYNTH_MD)
                and m["source"]["line_count"] == 4
                and m["source"]["sha256"]
                == hashlib.sha256(_SYNTH_MD.encode("utf-8")).hexdigest()
                and m["tool"]["name"] == "init_workspace"
                and "OK: workspace seeded" in sout
            )
        results.append(_expect(
            "happy path: .md source -> input/source.md + manifest with "
            "correct kind / id / counts / sha256",
            ok,
            f"rc={rc}, manifest={manifest_path.is_file()}, "
            f"copy={copy_path.is_file()}",
        ))

        # 2. happy path: .txt source -> kind=text
        txt_src = td / "another_brief.txt"
        txt_src.write_text(_SYNTH_TXT)
        ws_txt = td / "ws_txt"
        rc, _sout, _serr = _invoke_self([
            "--source", str(txt_src),
            "--workspace", str(ws_txt),
        ])
        ok = rc == 0 and (ws_txt / SOURCE_MANIFEST_FILENAME).is_file()
        if ok:
            m = json.loads((ws_txt / SOURCE_MANIFEST_FILENAME).read_text())
            ok = m["source"]["kind"] == "text" and m["source"]["id"] == "another_brief"
        results.append(_expect(
            "happy path: .txt source -> kind=text and id derived from stem",
            ok, f"rc={rc}",
        ))

        # 3. determinism: two runs from identical source produce
        # byte-identical manifests + source.md (modulo the workspace
        # path itself).
        det_src = td / "determinism.md"
        det_src.write_text(_SYNTH_MD)
        ws_a = td / "ws_det_a"
        ws_b = td / "ws_det_b"
        rc_a, _, _ = _invoke_self([
            "--source", str(det_src),
            "--workspace", str(ws_a),
        ])
        rc_b, _, _ = _invoke_self([
            "--source", str(det_src),
            "--workspace", str(ws_b),
        ])
        bytes_a = (ws_a / SOURCE_MANIFEST_FILENAME).read_bytes() \
            if (ws_a / SOURCE_MANIFEST_FILENAME).is_file() else b""
        bytes_b = (ws_b / SOURCE_MANIFEST_FILENAME).read_bytes() \
            if (ws_b / SOURCE_MANIFEST_FILENAME).is_file() else b""
        ok = (
            rc_a == 0 and rc_b == 0
            and bytes_a == bytes_b
            and bytes_a != b""
        )
        results.append(_expect(
            "determinism: two independent runs produce byte-identical "
            "manifests (no timestamp / absolute path / random id in the "
            "manifest)",
            ok, f"rc_a={rc_a}, rc_b={rc_b}, bytes_equal={bytes_a == bytes_b}",
        ))

        # 4. missing source
        rc, _, serr = _invoke_self([
            "--source", str(td / "does_not_exist.md"),
            "--workspace", str(td / "ws_missing"),
        ])
        ok = rc == 2 and "does not exist" in serr
        results.append(_expect(
            "missing source file fails closed before any workspace is "
            "created",
            ok, f"rc={rc}",
        ))
        # Side-effect check: no workspace dir created on fail.
        results.append(_expect(
            "no workspace directory created when source is missing",
            not (td / "ws_missing").exists(),
            "",
        ))

        # 5. symlink at --source
        real_src = td / "real_source.md"
        real_src.write_text(_SYNTH_MD)
        sym_src = td / "sym_source.md"
        sym_src.symlink_to(real_src)
        rc, _, serr = _invoke_self([
            "--source", str(sym_src),
            "--workspace", str(td / "ws_symsrc"),
        ])
        ok = rc == 2 and "symlink" in serr
        results.append(_expect(
            "symlink at --source is refused", ok, f"rc={rc}",
        ))

        # 6. wrong extension
        bad_ext = td / "report.pdf"
        bad_ext.write_text("not really a pdf")
        rc, _, serr = _invoke_self([
            "--source", str(bad_ext),
            "--workspace", str(td / "ws_badext"),
        ])
        ok = rc == 2 and "unsupported extension" in serr
        results.append(_expect(
            "wrong extension (.pdf) refused; only .md and .txt accepted",
            ok, f"rc={rc}",
        ))

        # 7. binary content
        bin_src = td / "binary.md"
        bin_src.write_bytes(b"\x00\x01\x02\xffnot utf8 \xfe")
        rc, _, serr = _invoke_self([
            "--source", str(bin_src),
            "--workspace", str(td / "ws_binary"),
        ])
        ok = rc == 2 and "not valid UTF-8" in serr
        results.append(_expect(
            "binary (non-UTF-8) content refused", ok, f"rc={rc}",
        ))

        # 8. empty source
        empty_src = td / "empty.md"
        empty_src.write_bytes(b"")
        rc, _, serr = _invoke_self([
            "--source", str(empty_src),
            "--workspace", str(td / "ws_empty"),
        ])
        ok = rc == 2 and "empty" in serr
        results.append(_expect(
            "empty source file refused", ok, f"rc={rc}",
        ))

        # 9. URI-scheme --source string
        rc, _, serr = _invoke_self([
            "--source", "https://example.com/source.md",
            "--workspace", str(td / "ws_urisrc"),
        ])
        ok = rc == 2 and "URI" in serr
        results.append(_expect(
            "--source as https URL refused at the string level",
            ok, f"rc={rc}",
        ))

        rc, _, serr = _invoke_self([
            "--source", "file:///etc/passwd",
            "--workspace", str(td / "ws_fileuri"),
        ])
        ok = rc == 2 and "URI" in serr
        results.append(_expect(
            "--source as file:// URI refused at the string level",
            ok, f"rc={rc}",
        ))

        # 9b. URI schemes that don't carry a "://" prefix must also be
        # refused — the narrower form ALPHA "+" "-" "." * ":" anything
        # is what catches data:, mailto:, javascript:, and s3:bucket/key.
        # The previous narrower regex (":[/\\]") false-passed these:
        # the path then went to Path.is_file() and was reported as
        # "does not exist" instead of the documented "looks like a URI"
        # — that was the false-pass the docstring promised against.
        for uri_src in (
            "data:text/html;base64,abc",
            "mailto:user@example.invalid",
            "javascript:alert(1)",
            "s3:bucket/key.md",
        ):
            rc, _, serr = _invoke_self([
                "--source", uri_src,
                "--workspace", str(td / f"ws_uri_{abs(hash(uri_src))}"),
            ])
            ok_uri = rc == 2 and "URI" in serr
            results.append(_expect(
                f"--source with URI scheme {uri_src!r} refused at the "
                f"string level (covers the schemes that don't carry "
                f"'://')",
                ok_uri, f"rc={rc}, stderr_tail={serr.strip().splitlines()[-1] if serr.strip() else ''!r}",
            ))

        # 9c. The same URI-scheme guard must apply to --workspace, not
        # just --source. Without it, a URI-shaped workspace string
        # (e.g. data:foo or s3:bucket/key) would be silently resolved
        # into the CWD and mkdir would happily create a directory
        # whose name carries the scheme prefix.
        ws_uri_src = td / "ws_uri_src.md"
        ws_uri_src.write_text(_SYNTH_MD)
        for uri_ws in (
            "https://attacker.example/ws",
            "data:text/html;base64,deadbeef",
            "s3:bucket/workspace",
            "javascript:alert(1)",
        ):
            rc, _, serr = _invoke_self([
                "--source", str(ws_uri_src),
                "--workspace", uri_ws,
            ])
            ok_uri = rc == 2 and "URI" in serr
            results.append(_expect(
                f"--workspace with URI scheme {uri_ws!r} refused at the "
                f"string level (BEFORE Path.resolve / mkdir)",
                ok_uri, f"rc={rc}, stderr_tail={serr.strip().splitlines()[-1] if serr.strip() else ''!r}",
            ))

        # 10. workspace already non-empty
        nonempty = td / "ws_nonempty"
        nonempty.mkdir()
        (nonempty / "preexisting.txt").write_text("hi")
        good_src = td / "good.md"
        good_src.write_text(_SYNTH_MD)
        rc, _, serr = _invoke_self([
            "--source", str(good_src),
            "--workspace", str(nonempty),
        ])
        ok = (
            rc == 2
            and "non-empty" in serr
            and (nonempty / "preexisting.txt").read_text() == "hi"
            and not (nonempty / SOURCE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "pre-existing non-empty workspace refused; prior contents "
            "preserved",
            ok, f"rc={rc}",
        ))

        # 11. workspace is a symlink
        real_dir = td / "real_ws_target"
        real_dir.mkdir()
        ws_sym = td / "ws_sym"
        ws_sym.symlink_to(real_dir)
        rc, _, serr = _invoke_self([
            "--source", str(good_src),
            "--workspace", str(ws_sym),
        ])
        ok = (
            rc == 2 and "symlink" in serr
            and not (real_dir / SOURCE_MANIFEST_FILENAME).exists()
        )
        results.append(_expect(
            "symlink at --workspace refused; target directory untouched",
            ok, f"rc={rc}",
        ))

        # 12. workspace is an existing regular file
        ws_file = td / "ws_is_file"
        ws_file.write_text("not a directory")
        rc, _, serr = _invoke_self([
            "--source", str(good_src),
            "--workspace", str(ws_file),
        ])
        ok = (
            rc == 2 and "not a directory" in serr
            and ws_file.read_text() == "not a directory"
        )
        results.append(_expect(
            "regular file at --workspace refused; prior file preserved",
            ok, f"rc={rc}",
        ))

        # 13. workspace inside the repo root
        rc, _, serr = _invoke_self([
            "--source", str(good_src),
            "--workspace", str(REPO_ROOT / "examples" / "leak_workspace"),
        ])
        ok = (
            rc == 2 and "inside the repo root" in serr
            and not (REPO_ROOT / "examples" / "leak_workspace").exists()
        )
        results.append(_expect(
            "workspace inside the repo root refused (no leak into the "
            "source tree)",
            ok, f"rc={rc}",
        ))

        # 14. workspace at the filesystem root
        rc, _, serr = _invoke_self([
            "--source", str(good_src),
            "--workspace", "/",
        ])
        ok = rc == 2 and "filesystem root" in serr
        results.append(_expect(
            "workspace at '/' (filesystem root) refused",
            ok, f"rc={rc}",
        ))

        # 15. workspace at $HOME itself
        rc, _, serr = _invoke_self([
            "--source", str(good_src),
            "--workspace", os.path.expanduser("~"),
        ])
        ok = rc == 2 and "HOME directory" in serr
        results.append(_expect(
            "workspace at $HOME root refused", ok, f"rc={rc}",
        ))

        # 16. workspace under /etc (present on every realistic OS we
        # care about; the gate iterates _UNSAFE_SYSTEM_ROOTS).
        rc, _, serr = _invoke_self([
            "--source", str(good_src),
            "--workspace", "/etc/my_workspace_attempt",
        ])
        ok = (
            rc == 2 and "system directory" in serr
            and not Path("/etc/my_workspace_attempt").exists()
        )
        results.append(_expect(
            "workspace under /etc refused as system directory",
            ok, f"rc={rc}",
        ))

        # 17. --source-id with URI scheme
        rc, _, serr = _invoke_self([
            "--source", str(good_src),
            "--workspace", str(td / "ws_id_scheme"),
            "--source-id", "http://evil",
        ])
        ok = rc == 2 and "--source-id" in serr
        results.append(_expect(
            "--source-id with URI scheme refused",
            ok, f"rc={rc}",
        ))

        # 18. --source-id with traversal
        rc, _, serr = _invoke_self([
            "--source", str(good_src),
            "--workspace", str(td / "ws_id_trav"),
            "--source-id", "../escape",
        ])
        ok = rc == 2 and "--source-id" in serr
        results.append(_expect(
            "--source-id containing '..' refused",
            ok, f"rc={rc}",
        ))

        # 19. --source-id with leading slash
        rc, _, serr = _invoke_self([
            "--source", str(good_src),
            "--workspace", str(td / "ws_id_abs"),
            "--source-id", "/abs/id",
        ])
        ok = rc == 2 and "--source-id" in serr
        results.append(_expect(
            "--source-id with absolute-looking path refused",
            ok, f"rc={rc}",
        ))

        # 20. explicit --source-id that is valid is used verbatim
        rc, sout, _serr = _invoke_self([
            "--source", str(good_src),
            "--workspace", str(td / "ws_id_ok"),
            "--source-id", "custom_id.v2",
        ])
        manifest = json.loads(
            (td / "ws_id_ok" / SOURCE_MANIFEST_FILENAME).read_text()
        ) if rc == 0 else {}
        ok = rc == 0 and manifest.get("source", {}).get("id") == "custom_id.v2"
        results.append(_expect(
            "valid --source-id is used verbatim in the manifest",
            ok, f"rc={rc}",
        ))

        # 21. workspace exists as an empty directory: allowed
        empty_ws = td / "ws_pre_empty"
        empty_ws.mkdir()
        rc, _sout, _serr = _invoke_self([
            "--source", str(good_src),
            "--workspace", str(empty_ws),
        ])
        ok = (
            rc == 0
            and (empty_ws / SOURCE_MANIFEST_FILENAME).is_file()
            and (empty_ws / INPUT_SUBDIR / INPUT_FILENAME).is_file()
        )
        results.append(_expect(
            "pre-existing EMPTY workspace directory is accepted (the "
            "non-empty gate fires only when there is content)",
            ok, f"rc={rc}",
        ))

        # 22. on-disk manifest re-validates against the live schema
        # (the validate_artifact subprocess gate inside init_workspace
        # is the final defense-in-depth check; here we run it as a
        # caller would).
        final_ws = td / "ws_final"
        rc, _, _ = _invoke_self([
            "--source", str(good_src),
            "--workspace", str(final_ws),
        ])
        ok = rc == 0
        if ok:
            errors = validate_artifact(
                final_ws / SOURCE_MANIFEST_FILENAME,
                SOURCE_MANIFEST_SCHEMA,
            )
            ok = not errors
        results.append(_expect(
            "on-disk manifest validates against "
            "schemas/source_manifest.schema.json via validate_artifact",
            ok, "",
        ))

        # 23. Direct unit-test of _rollback_partial_writes:
        # workspace dir that this run created (workspace_pre_existed=
        # False) gets fully removed, along with the two files and the
        # input/ subdir.
        rb_ws_created = td / "rb_ws_created"
        rb_ws_created.mkdir()
        (rb_ws_created / INPUT_SUBDIR).mkdir()
        (rb_ws_created / INPUT_SUBDIR / INPUT_FILENAME).write_text("x")
        (rb_ws_created / SOURCE_MANIFEST_FILENAME).write_text("{}")
        notes = _rollback_partial_writes(
            rb_ws_created, workspace_pre_existed=False,
        )
        ok = (
            not rb_ws_created.exists()
            and any(f"removed {rb_ws_created}/" in n for n in notes)
            and any("source.md" in n for n in notes)
            and any("source_manifest.json" in n for n in notes)
        )
        results.append(_expect(
            "_rollback_partial_writes removes manifest + source.md + "
            "input/ + workspace dir when this run created the workspace",
            ok, f"ws_exists={rb_ws_created.exists()}, notes={notes}",
        ))

        # 24. Direct unit-test of _rollback_partial_writes:
        # workspace dir that pre-existed empty (workspace_pre_existed=
        # True) has its files removed but the workspace directory
        # itself is preserved (we didn't create it).
        rb_ws_pre = td / "rb_ws_pre_existed"
        rb_ws_pre.mkdir()
        (rb_ws_pre / INPUT_SUBDIR).mkdir()
        (rb_ws_pre / INPUT_SUBDIR / INPUT_FILENAME).write_text("y")
        (rb_ws_pre / SOURCE_MANIFEST_FILENAME).write_text("{}")
        _rollback_partial_writes(rb_ws_pre, workspace_pre_existed=True)
        ok = (
            rb_ws_pre.is_dir()
            and not (rb_ws_pre / INPUT_SUBDIR).exists()
            and not (rb_ws_pre / SOURCE_MANIFEST_FILENAME).exists()
            and not any(rb_ws_pre.iterdir())
        )
        results.append(_expect(
            "_rollback_partial_writes preserves a pre-existing empty "
            "workspace dir while still removing the files this run "
            "wrote inside it",
            ok, f"ws_is_dir={rb_ws_pre.is_dir()}",
        ))

        # 25. _rollback_partial_writes is idempotent: calling it on a
        # workspace that already has nothing to clean must not raise
        # and must report empty notes for every target.
        rb_clean = td / "rb_clean"
        rb_clean.mkdir()
        notes = _rollback_partial_writes(rb_clean, workspace_pre_existed=True)
        ok = (notes == [] and rb_clean.is_dir())
        results.append(_expect(
            "_rollback_partial_writes is idempotent / no-op when "
            "there is nothing to clean (returns empty notes, does not "
            "remove the pre-existing empty workspace)",
            ok, f"notes={notes}",
        ))

        # 26. End-to-end: a post-write re-validation failure (forced
        # via unittest.mock so the unreachable-in-practice path is
        # actually exercised) triggers full rollback, leaves no
        # partial state, and surfaces "rolled back" in the FAIL
        # message. This is the contract the docstring promises.
        import unittest.mock
        e2e_src = td / "rb_e2e.md"
        e2e_src.write_text(_SYNTH_MD)
        e2e_ws = td / "rb_e2e_ws"
        with unittest.mock.patch(
            f"{__name__}.validate_artifact",
            return_value=["forced test failure"],
        ):
            rc, msg = init_workspace(
                source=e2e_src,
                workspace=e2e_ws,
                source_id=None,
            )
        ok = (
            rc == 1
            and "rolled back" in msg
            and not e2e_ws.exists()
        )
        results.append(_expect(
            "post-write re-validation failure (forced via mock) "
            "triggers full rollback: rc=1, FAIL message names "
            "'rolled back', workspace directory is gone",
            ok, f"rc={rc}, ws_exists={e2e_ws.exists()}",
        ))

        # 27. End-to-end rollback when workspace pre-existed empty:
        # the files we wrote are gone, the empty workspace dir we
        # did NOT create is preserved.
        e2e_pre_ws = td / "rb_e2e_pre_ws"
        e2e_pre_ws.mkdir()
        with unittest.mock.patch(
            f"{__name__}.validate_artifact",
            return_value=["forced test failure"],
        ):
            rc, msg = init_workspace(
                source=e2e_src,
                workspace=e2e_pre_ws,
                source_id=None,
            )
        ok = (
            rc == 1
            and "rolled back" in msg
            and e2e_pre_ws.is_dir()
            and not (e2e_pre_ws / INPUT_SUBDIR).exists()
            and not (e2e_pre_ws / SOURCE_MANIFEST_FILENAME).exists()
            and not any(e2e_pre_ws.iterdir())
        )
        results.append(_expect(
            "post-write re-validation failure with a PRE-EXISTING "
            "empty workspace rolls back the files but preserves the "
            "user's workspace directory (rc=1, files gone, dir kept)",
            ok, f"rc={rc}, ws_is_dir={e2e_pre_ws.is_dir()}",
        ))

        # 28. Post-write re-validation RAISING SystemExit (the
        # actual exception validate_artifact uses for its read-error
        # branch) must trigger rollback. SystemExit does NOT inherit
        # from Exception, so a bare `except Exception:` would let it
        # bypass rollback and leave the half-written workspace on
        # disk. This scenario proves the catch clause is
        # `(Exception, SystemExit)` — not just `Exception`.
        sysexit_src = td / "rb_sysexit.md"
        sysexit_src.write_text(_SYNTH_MD)
        sysexit_ws = td / "rb_sysexit_ws"
        with unittest.mock.patch(
            f"{__name__}.validate_artifact",
            side_effect=SystemExit(
                "simulated validate_artifact read-error branch"
            ),
        ):
            rc, msg = init_workspace(
                source=sysexit_src,
                workspace=sysexit_ws,
                source_id=None,
            )
        ok = (
            rc == 1
            and "rolled back" in msg
            and "SystemExit" in msg
            and not sysexit_ws.exists()
        )
        results.append(_expect(
            "post-write re-validation RAISING SystemExit (the "
            "actual exception validate_artifact uses on a read "
            "failure) triggers full rollback — SystemExit doesn't "
            "inherit from Exception, so a bare `except Exception:` "
            "would bypass rollback",
            ok, f"rc={rc}, ws_exists={sysexit_ws.exists()}, msg={msg!r}",
        ))

        # 29. Post-write re-validation RAISING a generic Exception
        # (OSError) must also trigger rollback, with the exception
        # type and message surfaced in the FAIL output.
        oserr_src = td / "rb_oserr.md"
        oserr_src.write_text(_SYNTH_MD)
        oserr_ws = td / "rb_oserr_ws"
        with unittest.mock.patch(
            f"{__name__}.validate_artifact",
            side_effect=OSError(
                "simulated permission failure during re-validation read"
            ),
        ):
            rc, msg = init_workspace(
                source=oserr_src,
                workspace=oserr_ws,
                source_id=None,
            )
        ok = (
            rc == 1
            and "rolled back" in msg
            and "OSError" in msg
            and not oserr_ws.exists()
        )
        results.append(_expect(
            "post-write re-validation RAISING OSError triggers full "
            "rollback and the FAIL message names the exception type",
            ok, f"rc={rc}, ws_exists={oserr_ws.exists()}",
        ))

        # 30. source_manifest schema rejects every unsafe local_path
        # shape. The path-safety guarantee for source_manifest.local_path
        # was previously a docstring claim only: the schema declared
        # the field as `type: string, minLength: 1`, so a hand-edited
        # manifest with `local_path: "../../etc/passwd"` or
        # `local_path: "file:///etc/passwd"` would pass
        # validate_artifacts.py with a false-green OK. The schema now
        # enum-locks local_path to "input/source.md", which catches
        # every unsafe shape at the schema layer.
        manifest_schema = json.loads(SOURCE_MANIFEST_SCHEMA.read_text())
        from validate_artifacts import _validate as _vd_validate  # noqa: WPS433

        def _check_local_path_value(value: object) -> list[str]:
            m = {
                "schema_version": "1",
                "source": {
                    "id": "synthetic_id",
                    "local_path": value,
                    "kind": "markdown",
                    "byte_count": 1,
                    "line_count": 1,
                    "sha256": "0" * 64,
                },
                "tool": {"name": "init_workspace", "version": "1"},
            }
            errs: list[str] = []
            _vd_validate(m, manifest_schema, "<root>", errs)
            return errs

        unsafe_local_paths = [
            "../../etc/passwd",            # path traversal (parent escape)
            "/etc/passwd",                 # POSIX-absolute
            "/abs/path/source.md",         # POSIX-absolute (variant)
            "\\windows\\path",             # leading backslash
            "file:///etc/passwd",          # file:// URI
            "https://attacker.example/s.md",  # https:// URI
            "data:text/plain;base64,xx",   # data: URI
            "input/../source.md",          # traversal inside the path
            "input/source.md/",            # trailing slash variant
            "INPUT/source.md",             # case mismatch (canonical is lowercase)
            "other/place.md",              # safe-but-not-canonical
            "",                            # empty
        ]
        for bad_lp in unsafe_local_paths:
            errs = _check_local_path_value(bad_lp)
            rejected = bool(errs)
            results.append(_expect(
                f"source_manifest schema rejects local_path "
                f"{bad_lp!r} (enum lock prevents schema-level "
                f"false-green)",
                rejected,
                f"no schema errors emitted; errs={errs}",
            ))

        # 31. And the canonical safe value still validates.
        errs = _check_local_path_value("input/source.md")
        results.append(_expect(
            "source_manifest schema accepts the canonical "
            "local_path 'input/source.md'",
            not errs, f"errs={errs}",
        ))

        # 32. _build_manifest's defense-in-depth guard fires if the
        # constants ever drift to an unsafe value. We monkey-patch
        # INPUT_FILENAME to simulate a future code change that
        # accidentally introduced a traversal segment; the build
        # call must raise ValueError BEFORE any disk write.
        with unittest.mock.patch(f"{__name__}.INPUT_FILENAME", "../escape.md"):
            raised = False
            try:
                _build_manifest("any_id", _SYNTH_MD.encode("utf-8"), "markdown")
            except ValueError as exc:
                raised = "internal contract violation" in str(exc)
        results.append(_expect(
            "_build_manifest's defense-in-depth assertion fires when "
            "INPUT_FILENAME drifts to a path-unsafe value (ValueError "
            "with 'internal contract violation', no manifest returned)",
            raised, "",
        ))

    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage-1 (Intake) workspace initializer. Seeds a new "
            "workspace from a local Markdown or text source by writing "
            "input/source.md + source_manifest.json. Does NOT plan a "
            "deck — stages 2-5 each have a narrow contract helper "
            "(scripts/init_deck_brief.py / init_deck_plan.py / "
            "init_design_system.py / init_slide_plans.py); Stage 6 "
            "(image_manifest.json) remains agent-driven before "
            "scripts/run_pipeline.py can take over."
        ),
    )
    parser.add_argument(
        "--source", type=Path, default=None,
        help="Path to a local .md or .txt source file (regular file; "
             "symlinks refused).",
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Workspace directory to create. The string form must not "
             "start with a URI-like scheme (http://, file://, s3://, "
             "data:, mailto:, javascript:, ...); the path must not "
             "exist as a symlink; if it exists it must be an empty "
             "directory; must resolve outside the repo root, the "
             "filesystem root, $HOME root, and a small list of system "
             "roots.",
    )
    parser.add_argument(
        "--source-id", type=str, default=None,
        help="Opaque source identifier the agent will declare in "
             "deck_brief.source_refs. Defaults to the --source filename "
             "stem. Must match ^[A-Za-z0-9][A-Za-z0-9_.-]*$ and pass "
             "the repo's local_path_is_safe rule.",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios (happy path on .md "
             "and .txt sources, determinism, missing / symlinked / "
             "wrong-extension / binary / empty source, URI-scheme "
             "--source covering http://, file://, data:, mailto:, "
             "javascript:, s3:bucket/key — both the '://' and the "
             "scheme-only forms, URI-scheme --workspace covering the "
             "same scheme shapes, pre-existing non-empty workspace, "
             "workspace symlink / regular file / repo-root / fs-root "
             "/ $HOME / system directory, --source-id URI scheme / "
             "traversal / absolute, valid custom --source-id, "
             "pre-existing empty workspace, manifest re-validates on "
             "disk, direct unit-tests of _rollback_partial_writes, "
             "end-to-end rollback tests via unittest.mock that force "
             "the post-write re-validation to (a) return errors, "
             "(b) raise SystemExit (the exception validate_artifact "
             "uses on a read failure), or (c) raise OSError — proving "
             "the catch clause (Exception, SystemExit) routes BOTH "
             "Exception subclasses AND SystemExit through rollback, "
             "twelve schema-level negative tests proving source_manifest "
             "local_path's enum lock rejects every unsafe shape "
             "(traversal, POSIX-absolute, URI schemes, ...), and a "
             "drift test for _build_manifest's defense-in-depth "
             "local_path_is_safe assertion). "
             "Exits non-zero if any scenario does not behave as "
             "expected. Mutually exclusive with --source / --workspace "
             "/ --source-id.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if any(v is not None for v in (args.source, args.workspace, args.source_id)):
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
            "OK (self-test): every fail-closed gate is caught and the "
            "happy-path workspace is seeded with input/source.md + "
            "source_manifest.json."
        )
        return 0

    missing = [
        name for name, value in (
            ("--source", args.source),
            ("--workspace", args.workspace),
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

    rc, msg = init_workspace(
        source=args.source,
        workspace=args.workspace,
        source_id=args.source_id,
    )
    if rc == 0:
        print(msg)
    else:
        print(msg, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
