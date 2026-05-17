#!/usr/bin/env python3
"""package_skill.py

Stdlib-only deterministic builder for the internal skill package zip.

The repo is intended to ship as an internal skill bundle. This script
takes an EXPLICIT allow-listed subset of the tracked package surface
(see "Package-surface contract" below — NOT all of ``git ls-files``)
and writes ONE deterministic zip file, then re-inspects the produced
archive against the same fail-closed gates
`scripts/verify_skill_package.py` enforces against the working tree
PLUS an extra allow-list gate on the archive itself. The build
refuses to write a zip unless the pre-flight verification passes,
and refuses to leave the partial zip in place unless the post-write
archive inspection passes too.

What this script is:
  - A narrow zip builder: ``git ls-files`` -> explicit package
    allow-list filter -> sort -> deterministic zip -> archive
    inspection. Pure Python stdlib (``zipfile`` / ``subprocess`` /
    ``tempfile``).
  - Determinism-oriented: per-member timestamp, file mode, and
    create_system are pinned so two builds of the same tree produce
    byte-identical archives (the same input bytes through the same
    deflate codec is reproducible across Python builds on the same
    platform).
  - Reuses ``scripts/verify_skill_package.py`` directly — the
    pre-flight runs ``verify()`` on the (tracked + untracked-not-
    ignored) surface enumerator that script already implements, and
    the post-write archive inspection re-runs the same G1 / G2 / G3
    checks against the archive member set so a downstream consumer
    can rely on the archive alone (the working-tree gate would not
    survive distribution).

What this script is NOT:
  - A live Qoder runtime, MCP, public network, telemetry, model API,
    image search, or external service caller. It only writes a local
    zip and inspects it.
  - A PPTX exporter / runtime pipeline. It does not change PPTX
    export behavior or any other runtime stage.
  - An automatic prompt / report / Markdown-to-PPTX generator. The
    package surface is an EXPLICIT allow-list of top-level package
    roots/files intersected with ``git ls-files`` (tracked only); see
    "Package-surface contract" below for the exact allow-list and the
    rationale. No content is extracted from any source body, no slide
    artifact is planned, generated, or rendered here.
  - A live skill-install verifier. Live Qoder runtime import is
    explicitly UNVERIFIED here (and remains TODO across the wider
    repo; see ``references/quality-gates.md``).

Package-surface contract:
  The shipped surface is an EXPLICIT allow-list of top-level package
  roots/files, intersected with ``git ls-files`` (tracked only) rooted
  at ``--root`` (defaulting to the script's parent's parent). The
  allow-list is the only thing that ships:

    root files: ``SKILL.md`` / ``README.md`` / ``SECURITY.md``
    root dirs : ``references`` / ``schemas`` / ``scripts`` /
                ``templates`` / ``examples``

  Anything else — VCS/control metadata (``.gitignore``, ``.gitattributes``,
  ``.gitmodules``, any other root-level ``.git*`` control file), local-
  development docs intended only for in-repo AI agents (``CLAUDE.md`` /
  ``AGENTS.md``), editor / OS junk (``.DS_Store``), etc. — is excluded
  from the archive even when ``git ls-files`` would report it. The
  rationale: only intentional docs, references, schemas, scripts,
  templates, and synthetic examples should reach a downstream consumer
  of the shipped skill. A tracked file under any other top-level path
  is treated as repo-internal and is intentionally not shipped.

  Untracked-not-ignored files are also NOT shipped: they would not
  survive a clean checkout / git archive so shipping them would
  silently break the package on re-derive. The pre-flight does still
  scan the wider (tracked + untracked-not-ignored) surface so a stray
  untracked credential / external URL / forbidden artifact in the
  working tree is flagged before packaging proceeds.

Deterministic archive layout:
  - members written in sorted POSIX-string order;
  - per-member ``date_time`` pinned to ``(1980, 1, 1, 0, 0, 0)``
    (the zip-format minimum) instead of the on-disk mtime, so a
    rebuild on the same tree produces identical bytes regardless of
    file modification times;
  - per-member ``create_system`` pinned to 3 (UNIX) so the host OS
    does not vary the recorded system identifier;
  - per-member ``external_attr`` pinned to ``0o100644 << 16`` (regular
    file, rw-r--r--) so executable bits and umask do not leak;
  - ``ZIP_DEFLATED`` at compresslevel 6 (Python stdlib default; the
    same input bytes through the same deflate codec are byte-equal
    across runs);
  - no extra fields, no archive comment, no per-member comment.

Gates (every gate fail-closed; any failure aborts the build without
leaving the final zip on disk):

  Pre-flight P1 ``verify_skill_package``:
    Run ``verify_skill_package.verify()`` over the
    (tracked + untracked-not-ignored) surface. Every G1..G5 gate must
    pass.

  Build B1 ``tracked_surface_nonempty``:
    ``git ls-files`` must report at least one tracked file. An empty
    surface is a packaging FAIL — there is nothing to ship.

  Build B2 ``allow_listed_surface_nonempty``:
    After intersecting ``git ls-files`` with the explicit package
    allow-list (``PACKAGE_ALLOWED_ROOT_FILES`` /
    ``PACKAGE_ALLOWED_ROOT_DIRS``), the resulting member set must be
    non-empty. A repo whose tracked surface contains no allow-listed
    member is a packaging FAIL — the same "nothing to ship" condition
    as B1, surfaced after the allow-list is applied.

  Post-write A1 ``archive_no_forbidden`` (re-runs G1 against the
    archive member name list — defense-in-depth against an
    enumerator drift or a bypass of pre-flight).

  Post-write A2 ``archive_doc_references_present``:
    Every ``scripts/<name>.py`` or ``schemas/<name>.schema.json``
    referenced by any shipped doc file (``SKILL.md`` / ``README.md``
    / ``CLAUDE.md`` / ``AGENTS.md`` / ``references/*.md``) must also
    be a member of the archive. The pre-flight already enforces this
    against ``git ls-files``, but A2 makes the property hold on the
    archive's own member set so a downstream consumer who only sees
    the zip can rely on it.

  Post-write A3 ``archive_members_allow_listed``:
    Every archive member's top-level path component must be in
    ``PACKAGE_ALLOWED_ROOT_FILES`` (for a root-level file) or
    ``PACKAGE_ALLOWED_ROOT_DIRS`` (for anything under a directory).
    Belt-and-braces against the writer's filter — ensures
    ``.gitignore``, any future root-level ``.git*`` control file,
    ``CLAUDE.md``, ``AGENTS.md``, or any other non-allow-listed
    tracked file CANNOT silently ship even if a future ``select_
    package_members`` refactor drifts.

Exit codes:
  0  build succeeded, every pre-flight / post-write gate passed
  1  a gate failed (pre-flight or post-write)
  2  invocation error (bad CLI shape, git missing, unreadable file)

CLI:
  python3 scripts/package_skill.py
      # build dist/szh-ppt-skill.zip from this repo

  python3 scripts/package_skill.py --output /tmp/skill.zip
      # build into a caller-supplied path (any extension is fine but
      # ``.zip`` is conventional)

  python3 scripts/package_skill.py --root /path/to/checkout
      # package a different checkout

  python3 scripts/package_skill.py --self-test
      # run in-script tempfixture scenarios under TMPDIR only
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

REPO_ROOT_DEFAULT = Path(__file__).resolve().parent.parent

# Import the verifier directly — single source of truth for the gates.
sys.path.insert(0, str(REPO_ROOT_DEFAULT / "scripts"))
from verify_skill_package import (  # noqa: E402
    SCHEMA_REF_RE,
    SCRIPT_REF_RE,
    Finding,
    GateResult,
    _discover_doc_files,
    _read_text_safely,
    enumerate_package_surface_via_git,
    gate_no_generated_artifacts,
    verify,
)


# ----------------------------------------------------------------------
# Deterministic archive constants.
# ----------------------------------------------------------------------

# Zip-format minimum date_time (year >= 1980). Pinned so two builds of
# the same tree produce byte-identical archives regardless of file
# mtimes.
FIXED_DATE_TIME: tuple[int, int, int, int, int, int] = (1980, 1, 1, 0, 0, 0)

# Regular file, rw-r--r--, no executable bit. Pinned so umask / chmod
# differences across host filesystems do not vary the recorded mode.
FIXED_EXTERNAL_ATTR: int = 0o100644 << 16

# create_system 3 is UNIX. Pinned so the host OS does not vary the
# recorded system identifier (the default would record 0 on Windows).
FIXED_CREATE_SYSTEM: int = 3

# Default output path (under the gitignored dist/ directory).
DEFAULT_OUTPUT_RELATIVE = Path("dist") / "szh-ppt-skill.zip"


# ----------------------------------------------------------------------
# Explicit package allow-list. Only these top-level files and directory
# names ship inside the archive. Everything else under ``git ls-files``
# is treated as repo-internal and intentionally excluded — including
# VCS / control metadata (``.gitignore``, ``.gitattributes``,
# ``.gitmodules``, any future root-level ``.git*`` control file), local-
# development docs whose audience is in-repo AI agents (``CLAUDE.md`` /
# ``AGENTS.md``), and editor / OS junk. Preferring an explicit allow-
# list over "all tracked files" means a future stray root-level
# tracked file does not silently ship in the next build — it has to be
# named here, and named in the docs, before it reaches the archive.
# ----------------------------------------------------------------------

PACKAGE_ALLOWED_ROOT_FILES: frozenset[str] = frozenset({
    "SKILL.md",
    "README.md",
    "SECURITY.md",
})
PACKAGE_ALLOWED_ROOT_DIRS: frozenset[str] = frozenset({
    "references",
    "schemas",
    "scripts",
    "templates",
    "examples",
})


# ----------------------------------------------------------------------
# Tracked-surface enumeration (the shipped subset).
# ----------------------------------------------------------------------


def _run_git(root: Path, *args: str) -> list[str]:
    """Call ``git`` at ``root``. Raise SystemExit(2) on git failure —
    packaging from a non-repo is an invocation error, not a gate
    finding."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"error: 'git' executable not found: {exc}")
    if completed.returncode != 0:
        raise SystemExit(
            f"error: git {' '.join(args)} (cwd={root}) failed rc="
            f"{completed.returncode}: {completed.stderr.strip()}"
        )
    return [line for line in completed.stdout.splitlines() if line]


def list_tracked_files(root: Path) -> list[Path]:
    """Return sorted list of tracked files at ``root``.

    Tracked-only because untracked-not-ignored files would survive the
    verifier's surface enumerator but drop out of a clean checkout /
    git archive — shipping them would silently break the re-derived
    package.
    """
    return sorted({Path(rel) for rel in _run_git(root, "ls-files")})


def select_package_members(tracked: list[Path]) -> list[Path]:
    """Filter ``tracked`` to the EXPLICIT package allow-list — the only
    files that actually ship inside the archive.

    A tracked path is kept iff its top-level component is one of:
      - a name in ``PACKAGE_ALLOWED_ROOT_FILES`` AND the path is exactly
        that name at the root (no nested file sneaks in via a path like
        ``SKILL.md/extra``); OR
      - a directory name in ``PACKAGE_ALLOWED_ROOT_DIRS`` (anything
        under that directory ships).

    Everything else is intentionally dropped — including
    ``.gitignore`` / ``.gitattributes`` / ``.gitmodules`` / any future
    ``.git*`` root-level control file, ``CLAUDE.md`` / ``AGENTS.md``
    (local-development docs whose audience is in-repo AI agents), and
    any other tracked root file outside the allow-list. The function
    preserves input order (caller passes a sorted list) and is a pure
    filter — no I/O, no git call.
    """
    out: list[Path] = []
    for rel in tracked:
        parts = rel.parts
        if not parts:
            # An empty path is nonsensical for a tracked file; skip.
            continue
        if len(parts) == 1:
            if parts[0] in PACKAGE_ALLOWED_ROOT_FILES:
                out.append(rel)
            continue
        if parts[0] in PACKAGE_ALLOWED_ROOT_DIRS:
            out.append(rel)
    return out


# ----------------------------------------------------------------------
# Deterministic zip writer.
# ----------------------------------------------------------------------


def _refuse_symlink(p: Path, what: str) -> None:
    if p.is_symlink():
        raise SystemExit(f"error: {what} is a symlink; refusing: {p}")


def _refuse_symlinked_default_parent_components(
    default_root: Path,
    output: Path,
) -> None:
    """Refuse any symlinked path component STRICTLY UNDER ``default_root``
    on the way to ``output.parent``.

    Used only on the default-path code path (the user did NOT pass
    ``--output``). A symlinked component under ``default_root`` (e.g.
    ``<default_root>/dist/`` resolving to ``/etc/``) is not canonical
    filesystem geometry — it can only have been planted by the user or
    an attacker, and if the up-front cleanup follows it,
    ``_prepare_output_path`` will unlink + overwrite a file the symlink
    resolves to before the build had even started. ``default_root``
    itself may legitimately be a symlink (a repo checkout under macOS
    ``/tmp/checkout`` -> ``/private/tmp/checkout``); only path components
    STRICTLY UNDER ``default_root`` are refused on being a symlink. An
    intermediate component that exists but is NOT a directory is also
    refused — the builder will not silently mkdir into something else.
    """
    try:
        rel = output.parent.relative_to(default_root)
    except ValueError:
        raise SystemExit(
            f"error: default output parent {output.parent} is not under "
            f"repo root {default_root}; refusing"
        )
    cursor = default_root
    for part in rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise SystemExit(
                f"error: default-path parent component is a symlink; "
                f"refusing: {cursor}"
            )
        if cursor.exists() and not cursor.is_dir():
            raise SystemExit(
                f"error: default-path parent component exists and is not "
                f"a directory; refusing: {cursor}"
            )


def _prepare_output_path(
    output: Path,
    *,
    default_root: Path | None = None,
) -> None:
    """Up-front output-path hygiene that runs BEFORE pre-flight verify.

    Removes any pre-existing regular file at ``output`` and at
    ``<output>.partial`` so a pre-flight (or write / post-write) failure
    does not leave a stale archive at the final path masquerading as
    "the current package". A package is a deliverable: a prior
    successful build's bytes surviving a later failing attempt would
    mislead the caller.

    Symlinks and non-regular-file paths at the output itself are
    refused outright — never followed, never removed — so a malicious
    symlink at the output path cannot trick the cleanup into deleting
    an unrelated target, and a directory at the output path is treated
    as a configuration error rather than something to silently destroy.

    When ``default_root`` is supplied (the caller did NOT pass
    ``--output`` and so the output path was derived from the repo root
    via ``DEFAULT_OUTPUT_RELATIVE``), every path component STRICTLY
    UNDER ``default_root`` on the way to ``output.parent`` is
    additionally checked for symlinks and refused on finding one.
    Reason: a symlinked component under the repo root (e.g.
    ``<root>/dist/`` resolving to ``/etc/``) is not canonical filesystem
    geometry; it can only have been planted by the user or an attacker,
    and silently following it would let the cleanup below unlink +
    overwrite a file the symlink resolves to before the build had even
    started. This pins the `_resolve_output` docstring's commitment
    that a symlinked default ``dist/`` is refused rather than silently
    redirected to the symlink's target.

    Symlinks at the parent directory of a USER-SUPPLIED ``--output`` are
    intentionally NOT refused (i.e. when ``default_root`` is None):
    legitimate OS layouts use symlinked path components (e.g. on macOS
    ``/tmp`` is a symlink to ``/private/tmp``), and a build tool that
    refused those would be unusable with the canonical ``TMPDIR=/tmp``
    invocation. In the user-supplied case the output-FILE symlink check
    below is the actual attack surface (it prevents the writer from
    following a planted symlink and overwriting an unrelated file); the
    user opted into the path explicitly and accepts whatever filesystem
    geometry they pointed at.
    """
    if default_root is not None:
        _refuse_symlinked_default_parent_components(default_root, output)
    candidates = [output, output.with_name(output.name + ".partial")]
    for c in candidates:
        if c.is_symlink():
            raise SystemExit(f"error: output path is a symlink; refusing: {c}")
        if c.exists() and not c.is_file():
            raise SystemExit(
                f"error: output path exists and is not a regular file; "
                f"refusing: {c}"
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    for c in candidates:
        if c.is_file():
            try:
                c.unlink()
            except OSError as exc:
                raise SystemExit(
                    f"error: could not remove stale archive at {c}: {exc}"
                )


def write_deterministic_zip(
    root: Path,
    files: list[Path],
    out_path: Path,
) -> None:
    """Write ``files`` (paths relative to ``root``) to ``out_path`` as a
    deterministic zip.

    Caller MUST have run ``_prepare_output_path(out_path)`` first; this
    function trusts that ``out_path`` is a non-existent regular path
    inside an existing real directory, and that no stale partial
    survives at ``<out_path>.partial``. The function writes to
    ``<out_path>.partial`` first and renames on success so a crash
    mid-write does not leave a half-written archive at the final path.

    Atomicity contract: this function either writes the final archive
    at ``out_path``, or leaves NOTHING at either ``out_path`` or
    ``<out_path>.partial``. If anything raises mid-write (a source
    file is a symlink, a source file is missing, an OS error during
    read / write / replace), the leftover ``<out_path>.partial`` is
    unlinked defensively before the exception propagates so the caller
    never sees a stale half-written archive on disk. The cleanup is
    symlink-safe (a symlink at the partial path is left alone — the
    unlink never follows a symlink to a target outside this builder's
    scope) and best-effort (a failing unlink does not mask the
    original exception, which is always re-raised).
    """
    if not files:
        raise SystemExit("error: refusing to write an empty archive (no files)")
    tmp_path = out_path.with_name(out_path.name + ".partial")
    try:
        with zipfile.ZipFile(
            tmp_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as zf:
            for rel in files:
                src = root / rel
                _refuse_symlink(src, f"source file '{rel.as_posix()}'")
                if not src.is_file():
                    raise SystemExit(
                        f"error: source file is missing or not a regular file: {rel.as_posix()}"
                    )
                arcname = rel.as_posix()
                zi = zipfile.ZipInfo(filename=arcname, date_time=FIXED_DATE_TIME)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = FIXED_EXTERNAL_ATTR
                zi.create_system = FIXED_CREATE_SYSTEM
                with src.open("rb") as fh:
                    data = fh.read()
                zf.writestr(zi, data)
        tmp_path.replace(out_path)
    except (Exception, SystemExit):
        # Atomicity guarantee: do not leave a stale half-written
        # .partial archive behind for the caller. Symlink-safe (never
        # follow a planted symlink during cleanup; matches
        # _cleanup_partial's pattern) and best-effort (a failing
        # unlink does not mask the original exception). `except` lists
        # `SystemExit` explicitly because it inherits from
        # BaseException, not Exception, so a bare `except Exception:`
        # would let the inner SystemExit (symlink-refusal, missing
        # source) bypass cleanup. `KeyboardInterrupt` / `GeneratorExit`
        # are deliberately NOT caught so Ctrl-C remains responsive.
        if not tmp_path.is_symlink() and tmp_path.is_file():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


# ----------------------------------------------------------------------
# Archive inspection (post-write gates).
# ----------------------------------------------------------------------


def archive_member_names(archive_path: Path) -> list[str]:
    """Return sorted member name list of ``archive_path``."""
    _refuse_symlink(archive_path, "archive path")
    if not archive_path.is_file():
        raise SystemExit(f"error: archive missing or not a regular file: {archive_path}")
    with zipfile.ZipFile(archive_path, "r") as zf:
        return sorted(zi.filename for zi in zf.infolist())


def gate_archive_no_forbidden(members: Iterable[str]) -> GateResult:
    """Re-run G1 (no generated artifacts) on the archive member list."""
    res = gate_no_generated_artifacts([Path(m) for m in members])
    # Re-tag the gate so error output is clearly post-write.
    res.name = "archive_no_forbidden"
    for f in res.findings:
        f.gate = "archive_no_forbidden"
    return res


def gate_archive_members_allow_listed(members: Iterable[str]) -> GateResult:
    """Every archive member's top-level path component must be in the
    package allow-list. Belt-and-braces: the writer already filters via
    ``select_package_members`` BEFORE any member is written, but this
    post-write gate makes the property observable in the archive itself.
    A future drift in the writer (or a manual archive built outside this
    script) that ships ``.gitignore`` / ``CLAUDE.md`` / any other non-
    allow-listed file will fire this gate."""
    gate = GateResult(name="archive_members_allow_listed")
    for arc in members:
        rel = Path(arc)
        parts = rel.parts
        if not parts:
            gate.findings.append(Finding(
                gate=gate.name,
                detail="archive contains an empty member name",
                path=arc,
            ))
            continue
        if len(parts) == 1:
            if parts[0] not in PACKAGE_ALLOWED_ROOT_FILES:
                gate.findings.append(Finding(
                    gate=gate.name,
                    detail=(
                        f"root-level file '{parts[0]}' is not in the "
                        f"package allow-list "
                        f"(allowed: {sorted(PACKAGE_ALLOWED_ROOT_FILES)})"
                    ),
                    path=arc,
                ))
            continue
        if parts[0] not in PACKAGE_ALLOWED_ROOT_DIRS:
            gate.findings.append(Finding(
                gate=gate.name,
                detail=(
                    f"top-level component '{parts[0]}' is not in the "
                    f"package allow-list "
                    f"(allowed: {sorted(PACKAGE_ALLOWED_ROOT_DIRS)})"
                ),
                path=arc,
            ))
    return gate


def gate_archive_doc_references_present(
    root: Path,
    members: set[str],
) -> GateResult:
    """Every doc-referenced ``scripts/<name>.py`` or
    ``schemas/<name>.schema.json`` must be a member of the archive."""
    gate = GateResult(name="archive_doc_references_present")
    for rel in _discover_doc_files(root):
        text = _read_text_safely(root / rel)
        if text is None:
            continue
        script_refs = {m.group(1) for m in SCRIPT_REF_RE.finditer(text)}
        schema_refs = {m.group(1) for m in SCHEMA_REF_RE.finditer(text)}
        for stem in sorted(script_refs):
            target = f"scripts/{stem}.py"
            if target not in members:
                gate.findings.append(Finding(
                    gate=gate.name,
                    detail=(
                        f"doc {rel.as_posix()} references {target} but the "
                        f"archive does not contain that member"
                    ),
                    path=target,
                ))
        for stem in sorted(schema_refs):
            target = f"schemas/{stem}.schema.json"
            if target not in members:
                gate.findings.append(Finding(
                    gate=gate.name,
                    detail=(
                        f"doc {rel.as_posix()} references {target} but the "
                        f"archive does not contain that member"
                    ),
                    path=target,
                ))
    return gate


# ----------------------------------------------------------------------
# Composite build report.
# ----------------------------------------------------------------------


@dataclass
class BuildReport:
    root: Path
    output: Path
    surface_size: int
    member_count: int
    archive_sha256: str
    gates: list[GateResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(g.ok for g in self.gates)

    def render(self) -> str:
        lines: list[str] = []
        for g in self.gates:
            tag = "PASS" if g.ok else "FAIL"
            lines.append(f"[{tag}] {g.name}")
            for f in g.findings:
                lines.append(f.render())
        return "\n".join(lines)


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------
# Top-level build.
# ----------------------------------------------------------------------


def _cleanup_partial(output: Path) -> None:
    """Remove any leftover ``<output>.partial`` defensively. Called
    after a post-write failure so a half-written partial cannot
    survive alongside the deleted final archive."""
    partial = output.with_name(output.name + ".partial")
    if partial.is_symlink():
        return
    if partial.is_file():
        try:
            partial.unlink()
        except OSError:
            pass


def build_package(
    root: Path,
    output: Path,
    *,
    default_root: Path | None = None,
) -> BuildReport:
    """End-to-end build: prepare output path, pre-flight verify, write
    archive, inspect.

    Stale-archive hygiene: ``_prepare_output_path`` runs BEFORE
    pre-flight, so a pre-flight failure does not leave a prior
    successful build's zip at ``output`` masquerading as the current
    package. A symlink or non-regular-file at ``output`` is refused
    outright by that helper (SystemExit) — never followed, never
    silently removed — so the cleanup itself cannot be tricked into
    deleting an unrelated target.

    When ``default_root`` is non-None, the caller signals that ``output``
    was derived from the default path under ``default_root`` (i.e. the
    user did not pass ``--output``). The up-front cleanup then
    additionally refuses any symlinked path component STRICTLY UNDER
    ``default_root`` on the way to ``output.parent``. A symlinked
    ``<root>/dist/`` is not canonical filesystem geometry and silently
    following it would let the cleanup unlink + overwrite a file the
    symlink resolves to. The self-test caller (and any other caller that
    supplies an explicit output path) passes ``default_root=None`` to
    keep the existing parent-symlink policy intact for those scenarios.

    On any gate failure the (partial and final) archive files are
    removed and the build report is returned with ``ok == False`` so
    the caller can decide whether to surface a non-zero exit. The
    final ``output`` path is never left in a stale / partial state on
    any failure path (pre-flight, write, or post-write).
    """
    # --- Output-path hygiene FIRST. A pre-existing regular file at
    # output (a prior successful build's zip) is removed here so a
    # subsequent pre-flight failure does not leave it on disk.
    _prepare_output_path(output, default_root=default_root)

    # --- Pre-flight: full verifier on the (tracked + untracked) surface.
    full_surface = enumerate_package_surface_via_git(root)
    if not full_surface:
        raise SystemExit(f"error: empty package surface under {root}")
    pre_report = verify(root, full_surface)
    if not pre_report.ok:
        # Surface the pre-flight failures as the build report so the
        # caller sees exactly which gate refused the build. The stale
        # archive (if any) was already removed by _prepare_output_path
        # above, so no zip survives at ``output``.
        return BuildReport(
            root=root,
            output=output,
            surface_size=len(full_surface),
            member_count=0,
            archive_sha256="",
            gates=pre_report.gates,
        )

    # --- Tracked-only surface for the actual zip.
    tracked = list_tracked_files(root)
    if not tracked:
        raise SystemExit(f"error: no tracked files under {root}")

    # --- Apply the explicit package allow-list. VCS/control metadata
    # (.gitignore, .gitattributes, ...), local-development docs
    # (CLAUDE.md / AGENTS.md), and any other tracked root file outside
    # the allow-list are intentionally dropped here. The allow-list
    # narrows what reaches the archive — pre-flight still ran over the
    # wider tracked + untracked-not-ignored surface above.
    package_members = select_package_members(tracked)
    if not package_members:
        raise SystemExit(
            f"error: tracked surface under {root} contains no allow-listed "
            f"package member (root files: "
            f"{sorted(PACKAGE_ALLOWED_ROOT_FILES)}; root dirs: "
            f"{sorted(PACKAGE_ALLOWED_ROOT_DIRS)})"
        )

    # --- Build, then inspect. A post-write failure removes the file.
    write_deterministic_zip(root, package_members, output)
    members = archive_member_names(output)
    members_set = set(members)
    a1 = gate_archive_no_forbidden(members)
    a2 = gate_archive_doc_references_present(root, members_set)
    a3 = gate_archive_members_allow_listed(members)
    gates = list(pre_report.gates) + [a1, a2, a3]
    sha = _sha256_file(output)
    report = BuildReport(
        root=root,
        output=output,
        surface_size=len(full_surface),
        member_count=len(members),
        archive_sha256=sha,
        gates=gates,
    )
    if not report.ok:
        # Refuse to leave a broken archive (or its partial) at the
        # final path.
        try:
            output.unlink()
        except OSError:
            pass
        _cleanup_partial(output)
    return report


# ----------------------------------------------------------------------
# Real-repo entry point.
# ----------------------------------------------------------------------


def _resolve_root(arg_root: Path | None) -> Path:
    candidate = arg_root.resolve() if arg_root is not None else REPO_ROOT_DEFAULT
    if not candidate.is_dir():
        raise SystemExit(f"error: --root is not a directory: {candidate}")
    return candidate


def _resolve_output(arg_output: Path | None, root: Path) -> Path:
    """Resolve the output path for the CLI WITHOUT following symlinks.

    ``Path.resolve()`` FOLLOWS symlinks — calling it on an
    ``--output=/path/to/symlink`` argument rewrites the path to the
    symlink's target before ``_prepare_output_path`` ever sees it,
    silently bypassing the output-symlink refusal and letting the
    builder unlink + overwrite an unrelated file the symlink pointed
    at. ``Path.absolute()`` makes the path absolute without resolving
    symlinks, which is exactly what we want here: keep the user's
    argument structurally intact so ``_prepare_output_path`` can refuse
    a symlink at the output FILE the same way it does on a direct
    ``build_package()`` call.

    Default-path mode (``arg_output is None``) returns
    ``root / DEFAULT_OUTPUT_RELATIVE`` UNRESOLVED so the caller can
    pass ``default_root=root`` into ``_prepare_output_path``; that
    helper then refuses any symlinked path component STRICTLY UNDER
    ``root`` on the way to the output's parent (e.g. a symlinked
    ``<root>/dist/``). User-supplied ``--output`` keeps the
    "parent symlinks allowed" policy (TMPDIR=/tmp etc.) — see
    ``_prepare_output_path``.
    """
    if arg_output is None:
        return root / DEFAULT_OUTPUT_RELATIVE
    return arg_output.expanduser().absolute()


def _run_real(
    root: Path,
    output: Path,
    *,
    default_root: Path | None,
) -> int:
    report = build_package(root, output, default_root=default_root)
    if not report.ok:
        print(report.render())
        fails = sum(1 for g in report.gates if not g.ok)
        print(f"\nFAIL: {fails} packaging gate(s) failed; no archive emitted at {output}",
              file=sys.stderr)
        return 1
    print(report.render())
    print()
    print(f"Wrote: {output}")
    print(f"Members: {report.member_count} (from {report.surface_size} surface files)")
    print(f"SHA-256: {report.archive_sha256}")
    print(
        "Note: live Qoder runtime import / runtime packaging is UNVERIFIED here "
        "(and remains TODO across the wider repo). This builder only writes and "
        "inspects the static package archive."
    )
    return 0


# ----------------------------------------------------------------------
# Self-test scenarios.
# ----------------------------------------------------------------------


@dataclass
class ScenarioResult:
    name: str
    ok: bool
    detail: str = ""


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _git_init_quiet(root: Path) -> None:
    _run_git(root, "init", "--quiet", "--initial-branch=main")
    _run_git(root, "config", "user.email", "selftest@example.invalid")
    _run_git(root, "config", "user.name", "package_skill self-test")


def _baseline_fixture(root: Path) -> None:
    """Mirror verify_skill_package's baseline so the verifier's gates
    pass on the same fixture used here. The fixture is intentionally
    minimal: one script, one schema, one template JSON, one example
    SVG/JSON, four docs files (SKILL.md / README.md / SECURITY.md /
    CLAUDE.md), and one references/*.md naming both — PLUS a tracked
    ``.gitignore`` and ``AGENTS.md`` so the allow-list filter has
    concrete excluded inputs to drop. The shipped subset (allow-listed)
    excludes ``.gitignore`` / ``CLAUDE.md`` / ``AGENTS.md`` even though
    they are tracked."""
    _write(root / "scripts" / "real_helper.py", "# stdlib only\n")
    _write(root / "schemas" / "fake.schema.json",
        '{\n  "$schema": "http://json-schema.org/draft-07/schema#",\n'
        '  "type": "object"\n}\n')
    _write(root / "templates" / "layouts" / "demo" / "template.json",
        '{\n  "name": "demo",\n  "layouts": ["cover"]\n}\n')
    _write(root / "examples" / "demo_workspace" / "svg_previews" / "01_cover.svg",
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"></svg>\n')
    _write(root / "examples" / "demo_workspace" / "deck_brief.json",
        '{\n  "title": "Demo",\n  "audience": "internal",\n'
        '  "objective": "demo",\n  "source_refs": ["demo_id"]\n}\n')
    _write(root / "SKILL.md",
        "# SKILL\nUses scripts/real_helper.py and schemas/fake.schema.json.\n")
    _write(root / "README.md", "# README\n")
    _write(root / "SECURITY.md", "# SECURITY\n")
    _write(root / "CLAUDE.md", "# CLAUDE\n")
    _write(root / "AGENTS.md", "# AGENTS\n")
    _write(root / ".gitignore", "dist/\nbuild/\n*.pyc\n")
    _write(root / "references" / "verify.md",
        "References scripts/real_helper.py.\n")
    _git_init_quiet(root)
    _run_git(root, "add", "-A")
    # Commit so ``git ls-files`` and a clean checkout would agree. The
    # baseline is staged-and-committed to mimic a clean repo state.
    _run_git(root, "commit", "--quiet", "-m", "baseline")


def _scenario_baseline_pass() -> ScenarioResult:
    # Two tempdirs: outputs land OUTSIDE the fixture root so the
    # verifier's untracked-not-ignored surface enumeration never sees
    # the freshly-written zip and re-trips G1 on the dist/ component
    # of the output path.
    with tempfile.TemporaryDirectory() as td_root, tempfile.TemporaryDirectory() as td_out:
        root = Path(td_root)
        _baseline_fixture(root)
        output = Path(td_out) / "out.zip"
        report = build_package(root, output)
        if not report.ok:
            return ScenarioResult(
                name="baseline_builds",
                ok=False,
                detail="; ".join(
                    f"{f.gate}: {f.path}: {f.detail}"
                    for g in report.gates if not g.ok for f in g.findings),
            )
        if not output.is_file():
            return ScenarioResult(
                name="baseline_builds", ok=False,
                detail="archive missing after successful build",
            )
        # The archive members must equal the ALLOW-LISTED subset of
        # the tracked surface, in sorted POSIX order — proving the
        # surface-to-archive mapping is 1:1 AFTER the filter. The
        # tracked set is intentionally a strict superset of the
        # shipped set (the fixture includes .gitignore / CLAUDE.md /
        # AGENTS.md, which are NOT shipped).
        tracked = list_tracked_files(root)
        expected = [p.as_posix() for p in select_package_members(tracked)]
        members = archive_member_names(output)
        if members != expected:
            return ScenarioResult(
                name="baseline_builds", ok=False,
                detail=(
                    f"members != allow-listed selection; "
                    f"members={members}; expected={expected}"
                ),
            )
        # The filter must actually drop something in this fixture —
        # otherwise the test does not really exercise the allow-list.
        tracked_posix = [p.as_posix() for p in tracked]
        dropped = sorted(set(tracked_posix) - set(expected))
        if not dropped:
            return ScenarioResult(
                name="baseline_builds", ok=False,
                detail=(
                    "baseline fixture did not exercise the allow-list "
                    "(no tracked file was filtered out)"
                ),
            )
        # Spot-check the explicit excluded names — these MUST be
        # tracked AND MUST NOT be shipped.
        members_set = set(members)
        for excluded in (".gitignore", "CLAUDE.md", "AGENTS.md"):
            if excluded not in tracked_posix:
                return ScenarioResult(
                    name="baseline_builds", ok=False,
                    detail=f"fixture is missing tracked '{excluded}'",
                )
            if excluded in members_set:
                return ScenarioResult(
                    name="baseline_builds", ok=False,
                    detail=f"'{excluded}' leaked into the archive",
                )
        # And the explicit allow-listed root files MUST be shipped.
        for kept in ("SKILL.md", "README.md", "SECURITY.md"):
            if kept not in members_set:
                return ScenarioResult(
                    name="baseline_builds", ok=False,
                    detail=f"allow-listed root file '{kept}' missing from archive",
                )
        # Fixed timestamp / external_attr / create_system must round-trip.
        with zipfile.ZipFile(output, "r") as zf:
            for zi in zf.infolist():
                if zi.date_time != FIXED_DATE_TIME:
                    return ScenarioResult(
                        name="baseline_builds", ok=False,
                        detail=f"member {zi.filename} date_time={zi.date_time}",
                    )
                if zi.external_attr != FIXED_EXTERNAL_ATTR:
                    return ScenarioResult(
                        name="baseline_builds", ok=False,
                        detail=f"member {zi.filename} external_attr={zi.external_attr:#x}",
                    )
                if zi.create_system != FIXED_CREATE_SYSTEM:
                    return ScenarioResult(
                        name="baseline_builds", ok=False,
                        detail=f"member {zi.filename} create_system={zi.create_system}",
                    )
        return ScenarioResult(name="baseline_builds", ok=True)


def _scenario_determinism() -> ScenarioResult:
    """Build twice on the same fixture -> byte-identical archives."""
    with tempfile.TemporaryDirectory() as td_root, tempfile.TemporaryDirectory() as td_out:
        root = Path(td_root)
        _baseline_fixture(root)
        out1 = Path(td_out) / "a.zip"
        out2 = Path(td_out) / "b.zip"
        r1 = build_package(root, out1)
        r2 = build_package(root, out2)
        if not (r1.ok and r2.ok):
            return ScenarioResult(
                name="determinism_two_builds_equal", ok=False,
                detail="one or both builds failed",
            )
        if out1.read_bytes() != out2.read_bytes():
            return ScenarioResult(
                name="determinism_two_builds_equal", ok=False,
                detail=(
                    f"archive bytes differ; sha1={r1.archive_sha256}, "
                    f"sha2={r2.archive_sha256}"
                ),
            )
        return ScenarioResult(name="determinism_two_builds_equal", ok=True)


def _scenario_preflight_blocks_forbidden() -> ScenarioResult:
    """Stage a forbidden tracked file -> pre-flight blocks the build,
    no archive is emitted."""
    with tempfile.TemporaryDirectory() as td_root, tempfile.TemporaryDirectory() as td_out:
        root = Path(td_root)
        _baseline_fixture(root)
        # Add a forbidden filename (a tracked .pptx in examples/).
        bad = root / "examples" / "demo_workspace" / "deck.pptx"
        _write(bad, "PK fake\n")
        _run_git(root, "add", "examples/demo_workspace/deck.pptx")
        output = Path(td_out) / "out.zip"
        report = build_package(root, output)
        if report.ok:
            return ScenarioResult(
                name="preflight_blocks_forbidden_tracked_pptx", ok=False,
                detail="expected build to fail but it succeeded",
            )
        if output.exists():
            return ScenarioResult(
                name="preflight_blocks_forbidden_tracked_pptx", ok=False,
                detail=f"archive should not exist on failure: {output}",
            )
        bad_gate_names = {g.name for g in report.gates if not g.ok}
        if "no_generated_artifacts" not in bad_gate_names:
            return ScenarioResult(
                name="preflight_blocks_forbidden_tracked_pptx", ok=False,
                detail=f"expected 'no_generated_artifacts' to fail; got {bad_gate_names}",
            )
        return ScenarioResult(name="preflight_blocks_forbidden_tracked_pptx", ok=True)


def _scenario_archive_forbidden_direct() -> ScenarioResult:
    """Belt-and-braces: the archive-level G1 fires on a synthetic
    forbidden member name. Real builds shouldn't reach this point
    (pre-flight already gated forbidden tracked files), but the
    post-write check exists so a future enumerator drift cannot
    silently ship a forbidden file."""
    synthetic = ["scripts/__pycache__/x.cpython-313.pyc", "SKILL.md"]
    res = gate_archive_no_forbidden(synthetic)
    if res.ok:
        return ScenarioResult(
            name="archive_forbidden_member_caught", ok=False,
            detail="gate_archive_no_forbidden missed __pycache__ member",
        )
    return ScenarioResult(name="archive_forbidden_member_caught", ok=True)


def _scenario_archive_gitignore_member_caught() -> ScenarioResult:
    """Belt-and-braces: the archive-level A3 fires on a synthetic
    ``.gitignore`` member. Real builds shouldn't reach this point —
    ``select_package_members`` already filters it before any write —
    but the post-write check exists so a future writer drift cannot
    silently ship VCS metadata."""
    synthetic = [".gitignore", "SKILL.md"]
    res = gate_archive_members_allow_listed(synthetic)
    if res.ok:
        return ScenarioResult(
            name="archive_gitignore_member_caught", ok=False,
            detail="gate_archive_members_allow_listed missed '.gitignore'",
        )
    if not any(f.path == ".gitignore" for f in res.findings):
        return ScenarioResult(
            name="archive_gitignore_member_caught", ok=False,
            detail=(
                f"expected a finding naming '.gitignore'; got "
                f"{[(f.path, f.detail) for f in res.findings]}"
            ),
        )
    return ScenarioResult(name="archive_gitignore_member_caught", ok=True)


def _scenario_archive_git_dotfiles_member_caught() -> ScenarioResult:
    """Same shape as the .gitignore scenario but for the wider
    ``.git*`` family of root-level control files (``.gitattributes``,
    ``.gitmodules``). Every such file must fire A3."""
    bad_names = [".gitattributes", ".gitmodules", ".git-blame-ignore-revs"]
    for name in bad_names:
        synthetic = [name, "SKILL.md"]
        res = gate_archive_members_allow_listed(synthetic)
        if res.ok:
            return ScenarioResult(
                name="archive_git_dotfiles_member_caught", ok=False,
                detail=f"A3 missed root-level '{name}'",
            )
        if not any(f.path == name for f in res.findings):
            return ScenarioResult(
                name="archive_git_dotfiles_member_caught", ok=False,
                detail=(
                    f"expected a finding naming '{name}'; got "
                    f"{[(f.path, f.detail) for f in res.findings]}"
                ),
            )
    return ScenarioResult(name="archive_git_dotfiles_member_caught", ok=True)


def _scenario_archive_local_dev_doc_member_caught() -> ScenarioResult:
    """``CLAUDE.md`` / ``AGENTS.md`` are local-development docs whose
    audience is in-repo AI agents — not the shipped skill. They are
    tracked but must not ship. If either leaked into an archive, A3
    must fire."""
    for name in ("CLAUDE.md", "AGENTS.md"):
        synthetic = [name, "SKILL.md"]
        res = gate_archive_members_allow_listed(synthetic)
        if res.ok:
            return ScenarioResult(
                name="archive_local_dev_doc_member_caught", ok=False,
                detail=f"A3 missed root-level '{name}'",
            )
        if not any(f.path == name for f in res.findings):
            return ScenarioResult(
                name="archive_local_dev_doc_member_caught", ok=False,
                detail=(
                    f"expected a finding naming '{name}'; got "
                    f"{[(f.path, f.detail) for f in res.findings]}"
                ),
            )
    return ScenarioResult(name="archive_local_dev_doc_member_caught", ok=True)


def _scenario_archive_unknown_root_dir_member_caught() -> ScenarioResult:
    """A future stray tracked root-level directory (e.g. ``dist/`` /
    ``build/`` / ``projects/`` / a brand-new ``tools/``) is not in the
    allow-list. Even if some other gate did not catch it (the verifier's
    G1 already forbids the generated-workspace dirs), A3 must fire on
    a member rooted at an unknown top-level dir."""
    synthetic = ["tools/probe.py", "SKILL.md"]
    res = gate_archive_members_allow_listed(synthetic)
    if res.ok:
        return ScenarioResult(
            name="archive_unknown_root_dir_member_caught", ok=False,
            detail="A3 missed an unknown root dir 'tools/'",
        )
    if not any(f.path == "tools/probe.py" for f in res.findings):
        return ScenarioResult(
            name="archive_unknown_root_dir_member_caught", ok=False,
            detail=(
                f"expected a finding naming 'tools/probe.py'; got "
                f"{[(f.path, f.detail) for f in res.findings]}"
            ),
        )
    return ScenarioResult(
        name="archive_unknown_root_dir_member_caught", ok=True)


def _scenario_select_package_members_filters() -> ScenarioResult:
    """Unit test of the filter itself. A synthetic tracked list mixes
    allow-listed and excluded paths; the filter must keep exactly the
    allow-listed subset, in input order."""
    tracked = [
        Path(".gitignore"),
        Path(".gitattributes"),
        Path("AGENTS.md"),
        Path("CLAUDE.md"),
        Path("README.md"),
        Path("SECURITY.md"),
        Path("SKILL.md"),
        Path("examples/demo/deck_brief.json"),
        Path("references/policy.md"),
        Path("schemas/x.schema.json"),
        Path("scripts/run.py"),
        Path("templates/layouts/demo/template.json"),
        # Non-allow-listed root dirs (should be dropped):
        Path("dist/skill.zip"),
        Path("projects/leak/deck_plan.json"),
        Path("tools/probe.py"),
    ]
    expected = [
        Path("README.md"),
        Path("SECURITY.md"),
        Path("SKILL.md"),
        Path("examples/demo/deck_brief.json"),
        Path("references/policy.md"),
        Path("schemas/x.schema.json"),
        Path("scripts/run.py"),
        Path("templates/layouts/demo/template.json"),
    ]
    got = select_package_members(tracked)
    if got != expected:
        return ScenarioResult(
            name="select_package_members_filters_correctly", ok=False,
            detail=(
                f"filter output mismatch; got={[p.as_posix() for p in got]}; "
                f"expected={[p.as_posix() for p in expected]}"
            ),
        )
    return ScenarioResult(
        name="select_package_members_filters_correctly", ok=True)


def _scenario_archive_doc_reference_missing() -> ScenarioResult:
    """Belt-and-braces: the archive-level A2 fires when a docs file
    references a member that is not in the archive set."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root / "SKILL.md",
               "# SKILL\nUses scripts/never_packaged.py.\n")
        # No scripts/never_packaged.py shipped in the (empty) members set.
        res = gate_archive_doc_references_present(root, members=set())
        if res.ok:
            return ScenarioResult(
                name="archive_doc_reference_missing_caught", ok=False,
                detail="gate_archive_doc_references_present missed missing member",
            )
        # Only that one finding expected, naming the script.
        if not any("scripts/never_packaged.py" in f.detail for f in res.findings):
            return ScenarioResult(
                name="archive_doc_reference_missing_caught", ok=False,
                detail=f"unexpected findings: {[f.detail for f in res.findings]}",
            )
        return ScenarioResult(name="archive_doc_reference_missing_caught", ok=True)


def _scenario_custom_output_path() -> ScenarioResult:
    """A caller-supplied --output path must place the archive at PATH,
    the parent directory is created if missing, and the produced
    archive equals a parallel build at a different path byte-for-byte
    (the output path must not influence archive contents)."""
    with tempfile.TemporaryDirectory() as td_root, tempfile.TemporaryDirectory() as td_out:
        root = Path(td_root)
        _baseline_fixture(root)
        out1 = Path(td_out) / "a.zip"
        out2 = Path(td_out) / "nested" / "deeper" / "b.zip"
        r1 = build_package(root, out1)
        r2 = build_package(root, out2)
        if not (r1.ok and r2.ok):
            return ScenarioResult(
                name="custom_output_path_works", ok=False,
                detail="one or both builds failed",
            )
        if not out2.is_file():
            return ScenarioResult(
                name="custom_output_path_works", ok=False,
                detail=f"nested custom output not written: {out2}",
            )
        if out1.read_bytes() != out2.read_bytes():
            return ScenarioResult(
                name="custom_output_path_works", ok=False,
                detail="archive contents differ between output paths",
            )
        return ScenarioResult(name="custom_output_path_works", ok=True)


def _scenario_output_symlink_refused() -> ScenarioResult:
    """A symlink at the output path must be refused outright — we will
    never follow a symlink and overwrite something else. The symlink
    lives in a sibling tempdir so it is not part of the fixture's
    package surface (otherwise pre-flight, not write_deterministic_zip,
    would be what refuses it, and we would not be testing the writer's
    own symlink defense)."""
    with tempfile.TemporaryDirectory() as td_root, tempfile.TemporaryDirectory() as td_out:
        root = Path(td_root)
        _baseline_fixture(root)
        decoy = Path(td_out) / "decoy.txt"
        decoy.write_text("decoy\n")
        link = Path(td_out) / "out.zip"
        link.symlink_to(decoy)
        try:
            report = build_package(root, link)
        except SystemExit as exc:
            msg = str(exc)
            if "symlink" not in msg:
                return ScenarioResult(
                    name="output_symlink_refused", ok=False,
                    detail=f"wrong exit message: {msg!r}",
                )
            if decoy.read_text() != "decoy\n":
                return ScenarioResult(
                    name="output_symlink_refused", ok=False,
                    detail="decoy file was overwritten through the symlink",
                )
            return ScenarioResult(name="output_symlink_refused", ok=True)
        else:
            return ScenarioResult(
                name="output_symlink_refused", ok=False,
                detail=f"expected SystemExit; got report ok={report.ok}",
            )


def _scenario_stale_zip_removed_on_preflight_failure() -> ScenarioResult:
    """Pins the fix for the stale-archive bug: a prior successful
    build's zip at ``output`` MUST be removed by a later run that
    fails pre-flight, so the caller is never left with a stale package
    masquerading as the current package.

    Steps:
      1. Build the baseline successfully -> zip exists at ``output``.
      2. Inject a forbidden tracked file (``examples/.../deck.pptx``)
         so the next pre-flight fails on ``no_generated_artifacts``.
      3. Rebuild -> pre-flight fails -> ``output`` MUST NOT exist.
    """
    with tempfile.TemporaryDirectory() as td_root, tempfile.TemporaryDirectory() as td_out:
        root = Path(td_root)
        _baseline_fixture(root)
        output = Path(td_out) / "out.zip"
        # 1. Baseline build succeeds and writes a zip at ``output``.
        r1 = build_package(root, output)
        if not r1.ok or not output.is_file():
            return ScenarioResult(
                name="stale_zip_removed_on_preflight_failure", ok=False,
                detail="baseline build did not produce the expected zip",
            )
        baseline_bytes = output.read_bytes()
        # 2. Inject a forbidden tracked file (a .pptx in examples/) so
        # pre-flight refuses the next build.
        bad = root / "examples" / "demo_workspace" / "deck.pptx"
        _write(bad, "PK fake\n")
        _run_git(root, "add", "examples/demo_workspace/deck.pptx")
        # 3. Rerun. Pre-flight must fail AND the prior zip must be gone.
        r2 = build_package(root, output)
        if r2.ok:
            return ScenarioResult(
                name="stale_zip_removed_on_preflight_failure", ok=False,
                detail="second build was expected to fail pre-flight but passed",
            )
        if output.exists():
            return ScenarioResult(
                name="stale_zip_removed_on_preflight_failure", ok=False,
                detail=(
                    f"stale zip survived pre-flight failure: {output} "
                    f"(bytes identical to baseline: "
                    f"{output.read_bytes() == baseline_bytes})"
                ),
            )
        partial = output.with_name(output.name + ".partial")
        if partial.exists():
            return ScenarioResult(
                name="stale_zip_removed_on_preflight_failure", ok=False,
                detail=f"stale .partial survived pre-flight failure: {partial}",
            )
        return ScenarioResult(
            name="stale_zip_removed_on_preflight_failure", ok=True)


def _scenario_cli_output_symlink_refused() -> ScenarioResult:
    """End-to-end CLI invocation: ``--output`` pointing at a symlink
    must be refused. This pins the fix for the prior CLI-path bypass
    where ``_resolve_output`` called ``Path.resolve()`` — which
    FOLLOWS symlinks — so by the time ``_prepare_output_path`` saw
    the path, the symlink had already been rewritten to its target
    and the decoy file would be silently unlinked + overwritten with
    the zip.

    The earlier ``_scenario_output_symlink_refused`` did NOT catch
    this: it called ``build_package()`` directly with a symlink Path,
    bypassing ``_resolve_output``. Exercising ``main()`` end-to-end
    here keeps the CLI path under test.
    """
    with tempfile.TemporaryDirectory() as td_root, tempfile.TemporaryDirectory() as td_out:
        root = Path(td_root)
        _baseline_fixture(root)
        decoy = Path(td_out) / "decoy.txt"
        decoy.write_text("decoy\n")
        link = Path(td_out) / "out.zip"
        link.symlink_to(decoy)
        argv = ["--root", str(root), "--output", str(link)]
        try:
            rc = main(argv)
        except SystemExit as exc:
            # _prepare_output_path raises SystemExit on a symlinked
            # output path. Verify the decoy survived.
            if not decoy.is_file() or decoy.read_text() != "decoy\n":
                return ScenarioResult(
                    name="cli_output_symlink_refused", ok=False,
                    detail=(
                        f"decoy file was clobbered through the symlink; "
                        f"exit message={str(exc)!r}"
                    ),
                )
            msg = str(exc)
            if "symlink" not in msg.lower():
                return ScenarioResult(
                    name="cli_output_symlink_refused", ok=False,
                    detail=f"wrong exit message: {msg!r}",
                )
            # The symlink itself must also be left untouched.
            if not link.is_symlink():
                return ScenarioResult(
                    name="cli_output_symlink_refused", ok=False,
                    detail="symlink at the output path was removed",
                )
            return ScenarioResult(name="cli_output_symlink_refused", ok=True)
        else:
            decoy_preserved = (
                decoy.is_file() and decoy.read_text() == "decoy\n"
            )
            return ScenarioResult(
                name="cli_output_symlink_refused", ok=False,
                detail=(
                    f"expected SystemExit; main returned rc={rc} "
                    f"(decoy preserved={decoy_preserved})"
                ),
            )


def _scenario_default_path_symlinked_parent_refused() -> ScenarioResult:
    """Pins the fix for a prior default-path cleanup bug: if the user
    runs ``package_skill.py`` without ``--output``, the default is
    ``<root>/dist/szh-ppt-skill.zip``. If a symlink is planted at
    ``<root>/dist/`` (pointing at, say, a sibling decoy directory or
    ``/etc/`` in the real world), the cleanup in
    ``_prepare_output_path`` would otherwise follow that symlink and
    unlink a regular file the symlink resolves to BEFORE the build had
    even started — overwriting an unrelated file via the symlinked
    parent. The fix refuses any symlinked path component STRICTLY UNDER
    the repo root in default-path mode; the cleanup never follows the
    symlink, never unlinks the decoy target, and the symlinked dir
    itself is left in place untouched.

    Exercising ``main()`` end-to-end keeps the CLI path under test —
    the default-root signal is wired through `_resolve_output` /
    `main` / `_run_real` / `build_package` / `_prepare_output_path`.
    """
    with tempfile.TemporaryDirectory() as td_root, tempfile.TemporaryDirectory() as td_decoy:
        root = Path(td_root)
        _baseline_fixture(root)
        decoy_dir = Path(td_decoy) / "decoy"
        decoy_dir.mkdir()
        decoy_file = decoy_dir / "szh-ppt-skill.zip"
        decoy_file.write_text("decoy zip content\n")
        # Plant <root>/dist as a symlink to the decoy directory; the
        # fixture's .gitignore already ignores dist/ so this does not
        # alter the verifier's surface.
        symlink_parent = root / "dist"
        symlink_parent.symlink_to(decoy_dir)
        argv = ["--root", str(root)]  # No --output -> default-path mode.
        try:
            rc = main(argv)
        except SystemExit as exc:
            msg = str(exc).lower()
            if "symlink" not in msg:
                return ScenarioResult(
                    name="default_path_symlinked_parent_refused", ok=False,
                    detail=f"wrong exit message: {str(exc)!r}",
                )
            # Decoy file at the symlink target MUST be untouched —
            # neither unlinked nor overwritten.
            if not decoy_file.is_file() or decoy_file.read_text() != "decoy zip content\n":
                return ScenarioResult(
                    name="default_path_symlinked_parent_refused", ok=False,
                    detail=(
                        f"decoy file at the symlink target was clobbered; "
                        f"exit message={str(exc)!r}"
                    ),
                )
            # The symlinked parent dir itself MUST be left in place.
            if not symlink_parent.is_symlink():
                return ScenarioResult(
                    name="default_path_symlinked_parent_refused", ok=False,
                    detail="symlinked parent dir was removed",
                )
            return ScenarioResult(
                name="default_path_symlinked_parent_refused", ok=True)
        else:
            decoy_preserved = (
                decoy_file.is_file()
                and decoy_file.read_text() == "decoy zip content\n"
            )
            return ScenarioResult(
                name="default_path_symlinked_parent_refused", ok=False,
                detail=(
                    f"expected SystemExit; main returned rc={rc} "
                    f"(decoy preserved={decoy_preserved})"
                ),
            )


def _scenario_write_failure_cleans_up_partial() -> ScenarioResult:
    """Pins the fix for a prior write-failure cleanup bug:
    ``write_deterministic_zip`` opens ``<out_path>.partial`` via
    ``zipfile.ZipFile(tmp_path, mode="w")``, writes members one at a
    time, and only renames the partial to ``out_path`` after the whole
    member list is written. If anything raises mid-write — a tracked
    source file that turned out to be a symlink, a source file that
    vanished between pre-flight and write, an OSError during read /
    write / replace — the ``with`` block closes the zipfile (flushing
    whatever was buffered) and the exception propagates out BEFORE
    ``tmp_path.replace(out_path)`` runs, so the half-written
    ``<out_path>.partial`` would otherwise be left on disk
    indefinitely. The fix wraps the entire write + replace in
    ``try/except (Exception, SystemExit)`` inside
    ``write_deterministic_zip``; on any failure it unlinks the
    leftover partial (symlink-safe; best-effort) and re-raises the
    original exception so the caller still sees the actual error.

    Test setup: call ``write_deterministic_zip`` directly with a curated
    file list whose FIRST entry is a regular source file (so the
    partial accumulates real bytes before the failure fires) and whose
    SECOND entry is a symlinked source file (so the per-source-file
    ``_refuse_symlink`` check fires mid-write). We bypass
    ``build_package`` to keep the test focused on the function's own
    atomicity contract — no git fixture, no pre-flight, no post-write
    inspection. We assert: the SystemExit message names the symlink,
    the leftover ``<out_path>.partial`` does NOT exist after the
    cleanup, and the final ``out_path`` also does not exist (the
    rename never ran because the write itself failed).
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "root"
        (root / "scripts").mkdir(parents=True)
        good = root / "scripts" / "ok.py"
        good.write_text("# good source\n", encoding="utf-8")
        target = root / "scripts" / "target.py"
        target.write_text("# real target the symlink points at\n", encoding="utf-8")
        bad = root / "scripts" / "bad.py"
        bad.symlink_to(target.name)  # Relative symlink within scripts/.
        output = Path(td) / "out.zip"
        partial = output.with_name(output.name + ".partial")
        files = [Path("scripts/ok.py"), Path("scripts/bad.py")]
        try:
            write_deterministic_zip(root, files, output)
        except SystemExit as exc:
            msg = str(exc).lower()
            if "symlink" not in msg:
                return ScenarioResult(
                    name="write_failure_cleans_up_partial", ok=False,
                    detail=f"wrong exit message: {str(exc)!r}",
                )
            if partial.exists():
                size = (
                    partial.stat().st_size
                    if (partial.is_file() and not partial.is_symlink())
                    else "non-regular-file"
                )
                return ScenarioResult(
                    name="write_failure_cleans_up_partial", ok=False,
                    detail=(
                        f"stale <output>.partial survived a mid-write "
                        f"failure: {partial} ({size} bytes); "
                        f"original error={str(exc)!r}"
                    ),
                )
            if output.exists():
                return ScenarioResult(
                    name="write_failure_cleans_up_partial", ok=False,
                    detail=(
                        f"final <output> exists after write failure "
                        f"(replace should never have run): {output}"
                    ),
                )
            return ScenarioResult(
                name="write_failure_cleans_up_partial", ok=True)
        else:
            partial_state = (
                f"partial-exists={partial.exists()}; "
                f"output-exists={output.exists()}"
            )
            return ScenarioResult(
                name="write_failure_cleans_up_partial", ok=False,
                detail=(
                    f"expected SystemExit; write_deterministic_zip "
                    f"returned normally ({partial_state})"
                ),
            )


def _scenarios() -> list[ScenarioResult]:
    return [
        _scenario_baseline_pass(),
        _scenario_determinism(),
        _scenario_preflight_blocks_forbidden(),
        _scenario_archive_forbidden_direct(),
        _scenario_archive_gitignore_member_caught(),
        _scenario_archive_git_dotfiles_member_caught(),
        _scenario_archive_local_dev_doc_member_caught(),
        _scenario_archive_unknown_root_dir_member_caught(),
        _scenario_select_package_members_filters(),
        _scenario_archive_doc_reference_missing(),
        _scenario_custom_output_path(),
        _scenario_output_symlink_refused(),
        _scenario_stale_zip_removed_on_preflight_failure(),
        _scenario_cli_output_symlink_refused(),
        _scenario_default_path_symlinked_parent_refused(),
        _scenario_write_failure_cleans_up_partial(),
    ]


def _print_scenarios(results: list[ScenarioResult]) -> int:
    width = max((len(r.name) for r in results), default=0)
    fails = 0
    for r in results:
        tag = "PASS" if r.ok else "FAIL"
        print(f"  [{tag}] {r.name.ljust(width)}  {r.detail}".rstrip())
        if not r.ok:
            fails += 1
    print()
    if fails:
        print(f"FAIL: {fails} self-test scenario(s) did not behave as expected.",
              file=sys.stderr)
        return 1
    print(f"OK: {len(results)} self-test scenario(s) passed.")
    print(
        "Note: live Qoder runtime import / runtime packaging is UNVERIFIED here "
        "(and remains TODO across the wider repo). The self-test only exercises "
        "the static package surface and the deterministic zip writer."
    )
    return 0


# ----------------------------------------------------------------------
# CLI.
# ----------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stdlib-only deterministic builder for the internal skill "
            "package zip. The shipped surface is an EXPLICIT allow-list "
            "of top-level package roots/files intersected with `git "
            "ls-files` (tracked only) — not all tracked files. Pre-flight "
            "reuses scripts/verify_skill_package.py; post-write archive "
            "inspection re-runs the forbidden-member, doc-reference, and "
            "allow-list gates against the archive itself. Does not import "
            "or call Qoder, MCP, public network, telemetry, model APIs, "
            "image search, or any external service. Does not change PPTX "
            "export behavior."
        ),
    )
    parser.add_argument(
        "--root", type=Path, default=None,
        help="Repo root to package (default: this script's parent's parent).",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help=(
            "Output archive path (default: <root>/dist/szh-ppt-skill.zip). "
            "Parent directory is created if missing. A symlink at the "
            "output path is refused outright. In default-path mode (no "
            "--output), any symlinked path component under <root> on the "
            "way to the output's parent (e.g. a symlinked <root>/dist/) "
            "is ALSO refused — that path is not canonical filesystem "
            "geometry and silently following it would let the cleanup "
            "unlink + overwrite a file the symlink points at. User-"
            "supplied --output keeps the standard policy (parent symlinks "
            "such as macOS /tmp -> /private/tmp are allowed so TMPDIR=/tmp "
            "invocations stay usable)."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios under TMPDIR only.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if args.root is not None or args.output is not None:
            print(
                "FAIL: --self-test does not take --root / --output. Run them "
                "as separate invocations.",
                file=sys.stderr,
            )
            return 2
        return _print_scenarios(_scenarios())

    root = _resolve_root(args.root)
    output = _resolve_output(args.output, root)
    # Default-path mode requires stricter parent-symlink hygiene under
    # ``root``; a user-supplied --output keeps the existing
    # parent-symlinks-allowed policy (TMPDIR=/tmp etc.). See
    # ``_prepare_output_path``.
    default_root = root if args.output is None else None
    return _run_real(root, output, default_root=default_root)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
