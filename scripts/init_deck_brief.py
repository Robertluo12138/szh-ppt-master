#!/usr/bin/env python3
"""Stage-2 (Brief) workspace bridge: produce a minimal deck_brief.json.

Bridges an already-stage-1-initialized workspace (the one
``scripts/init_workspace.py`` produces — ``source_manifest.json`` plus a
verbatim copy of the source at ``input/source.md``) into a minimal,
schema-valid ``deck_brief.json`` that always declares the manifest's
``source.id`` in ``source_refs``.

This is **Stage-2 contract support only**. It is NOT a full
prompt/report/Markdown to-PPTX automation. The helper deliberately does
NOT:

  - read or parse any business content out of ``input/source.md``
    (the bytes are counter-checked against the manifest, but never
    inspected for headings, bullets, key messages, or constraints);
  - invent ``key_messages`` / ``constraints`` / ``tone`` / ``language``
    / ``approximate_slide_count`` when the user does not pass them;
  - emit any artifact other than ``<workspace>/deck_brief.json``;
  - generate ``deck_plan.json``, ``design_system.json``,
    ``slide_plans/*.json``, ``image_manifest.json``, ``render_models/*``,
    ``svg_previews/*``, or any ``.pptx``;
  - call any public network, D-One, Qoder, image generation, or
    external service;
  - mutate or inspect any file outside ``--workspace``.

After this script succeeds, the agent must still produce stages 3-6
(``deck_plan.json``, ``design_system.json``, ``slide_plans/*.json``,
``image_manifest.json``) per the schemas under ``schemas/`` before
``scripts/run_pipeline.py`` can take over for stages 7-10.

Stdlib-only. Deterministic — given the same workspace + metadata, the
produced ``deck_brief.json`` is byte-identical. The brief carries only
user-supplied metadata and the manifest's ``source.id``; nothing
derived from clock, environment, or file order ends up in the artifact.

Fail-closed gates (every gate aborts the run and writes nothing):

  --workspace
    * must be an existing directory;
    * the string form must not start with a URI-like scheme matching
      ``^[A-Za-z][A-Za-z0-9+.\\-]*:`` (same rule init_workspace.py
      applies to its --workspace and --source values);
    * must contain ``source_manifest.json`` as a **regular in-
      workspace file**: a symlink at that path (broken or
      resolvable) is refused outright by a preflight gate that runs
      BEFORE the is_file check and BEFORE
      ``check_source_manifest_bridge`` / ``read_text`` so neither
      gate can follow a dangling target (legacy no-op masquerade) or
      read manifest bytes from outside the workspace;
    * the manifest must be loadable and validate against
      ``schemas/source_manifest.schema.json``;
    * must contain ``input/source.md`` (the path the manifest's
      ``source.local_path`` enum-locks to) whose byte_count /
      line_count / sha256 match the manifest;
    * must NOT already contain ``deck_brief.json`` as a symlink —
      a symlink (broken or resolvable) is refused outright, BEFORE
      the regular file-existence check, so ``write_text()`` cannot
      silently follow a dangling link and clobber the symlink target.
      ``Path.exists()`` returns False for a broken symlink, so a bare
      existence check would otherwise let that happen. Mirrors the same
      anti-pattern ``run_pipeline.py`` rejects at ``--output`` /
      ``--report-dir``;
    * must NOT already contain ``deck_brief.json`` as a regular file
      either (the helper refuses to overwrite a prior brief; rename or
      remove the existing brief first).

  --title / --audience / --objective (all required)
    * must each be non-empty after ``.strip()``;
    * must each be single-line — a value containing a newline is
      refused. The helper is a contract bridge, not a content-
      extraction tool; multi-line copy from the source body belongs
      in stage-3+ artifacts, not the brief.

  --tone / --language (optional)
    * when supplied, must each be non-empty after ``.strip()`` and
      single-line.

  --approximate-slide-count (optional)
    * when supplied, must parse as a positive integer.

The deck_brief is validated against ``schemas/deck_brief.schema.json``
**in memory** before any write, and **re-validated on disk** after
the write completes — the same defense-in-depth contract
``init_workspace.py`` follows. A post-write failure rolls the brief
back so the workspace is never left in a half-written state.
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
from validate_workspace import (  # noqa: E402
    check_source_manifest_bridge,
    SOURCE_MANIFEST_FILENAME,
    SOURCE_MANIFEST_LOCAL_PATH,
)

DECK_BRIEF_SCHEMA = SCHEMAS_DIR / "deck_brief.schema.json"
SOURCE_MANIFEST_SCHEMA = SCHEMAS_DIR / "source_manifest.schema.json"
DECK_BRIEF_FILENAME = "deck_brief.json"

# Same URI-scheme guard init_workspace.py uses for --workspace / --source.
# Catches http://, https://, file://, s3://, ftp://, data:, mailto:,
# javascript:, and any other ALPHA *( ALPHA / DIGIT / "+" / "-" / "." )
# ":" prefix regardless of whether "//" follows.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _has_uri_scheme(s: str) -> bool:
    return bool(_URI_SCHEME_PREFIX.match(s))


def _validate_single_line_string(name: str, value: str) -> tuple[bool, str]:
    """Return (ok, reason). A valid value is non-empty after .strip()
    AND does not contain a newline. Multi-line copy is a content-
    extraction signal we explicitly reject (the brief is a contract,
    not a place for source body text)."""
    if not isinstance(value, str):
        return False, f"{name} must be a string (got {type(value).__name__})"
    if not value.strip():
        return False, f"{name} must be non-empty after stripping whitespace"
    if "\n" in value or "\r" in value:
        return False, (
            f"{name} must be a single line (no embedded newline / "
            f"carriage return); pass a short label, not source body text"
        )
    return True, ""


def _build_brief(
    *,
    source_id: str,
    title: str,
    audience: str,
    objective: str,
    tone: str | None,
    language: str | None,
    approximate_slide_count: int | None,
) -> dict:
    """Build the minimal skeleton. Only schema-required fields are
    always written; optional fields appear ONLY when the caller passed
    them. ``source_refs`` always carries exactly the manifest's
    ``source.id`` (no extra ids invented, no business content from the
    source body)."""
    brief: dict = {
        "title": title.strip(),
        "audience": audience.strip(),
        "objective": objective.strip(),
        "source_refs": [source_id],
    }
    if tone is not None:
        brief["tone"] = tone.strip()
    if language is not None:
        brief["language"] = language.strip()
    if approximate_slide_count is not None:
        brief["approximate_slide_count"] = approximate_slide_count
    return brief


def _validate_brief_in_memory(brief: dict) -> list[str]:
    schema = json.loads(DECK_BRIEF_SCHEMA.read_text())
    from validate_artifacts import _validate  # noqa: WPS433
    errors: list[str] = []
    _validate(brief, schema, "<root>", errors)
    return errors


def init_deck_brief(
    *,
    workspace: Path,
    title: str,
    audience: str,
    objective: str,
    tone: str | None = None,
    language: str | None = None,
    approximate_slide_count: int | None = None,
) -> tuple[int, str]:
    """Run the full Stage-2 bridge. Returns (exit_code, message).

    Filesystem contract: preflight failures (bad ``--workspace``, bad
    metadata, missing or schema-invalid ``source_manifest.json``,
    missing / mismatched ``input/source.md``, pre-existing
    ``deck_brief.json``) leave the workspace untouched.

    A post-write re-validation failure rolls back ``deck_brief.json``
    so the workspace returns to its pre-call state."""
    # --workspace shape gates (string-level FIRST, then filesystem).
    if _has_uri_scheme(str(workspace)):
        return 2, (
            f"FAIL: --workspace {workspace} looks like a URI; "
            f"init_deck_brief only accepts local directory paths"
        )
    if workspace.is_symlink():
        return 2, (
            f"FAIL: --workspace {workspace} is a symlink; refusing to "
            f"follow it. Pass a regular directory path."
        )
    if not workspace.exists():
        return 2, f"FAIL: --workspace {workspace} does not exist"
    if not workspace.is_dir():
        return 2, (
            f"FAIL: --workspace {workspace} is not a directory"
        )

    # --title / --audience / --objective gates.
    for name, value in (
        ("--title", title),
        ("--audience", audience),
        ("--objective", objective),
    ):
        ok, reason = _validate_single_line_string(name, value)
        if not ok:
            return 2, f"FAIL: {reason}"

    # Optional --tone / --language gates.
    if tone is not None:
        ok, reason = _validate_single_line_string("--tone", tone)
        if not ok:
            return 2, f"FAIL: {reason}"
    if language is not None:
        ok, reason = _validate_single_line_string("--language", language)
        if not ok:
            return 2, f"FAIL: {reason}"

    if approximate_slide_count is not None:
        if (
            not isinstance(approximate_slide_count, int)
            or isinstance(approximate_slide_count, bool)
            or approximate_slide_count < 1
        ):
            return 2, (
                f"FAIL: --approximate-slide-count must be a positive "
                f"integer (got {approximate_slide_count!r})"
            )

    # Stage-2 contract gate: refuse to overwrite a pre-existing brief.
    # The symlink check runs FIRST and is independent of
    # ``brief_path.exists()``: ``exists()`` returns False for a broken
    # symlink (one whose target is missing), so a bare ``exists()`` gate
    # would let ``write_text()`` follow the symlink and silently clobber
    # whatever the dangling link names. This mirrors the same anti-pattern
    # ``run_pipeline.py`` forbids at ``--output`` / ``--report-dir``:
    # symlinks are never silently followed. We refuse both broken and
    # resolvable symlinks here.
    brief_path = workspace / DECK_BRIEF_FILENAME
    if brief_path.is_symlink():
        try:
            target = str(brief_path.readlink())
        except OSError:
            target = "<unreadable>"
        return 2, (
            f"FAIL: {brief_path} is a symlink (-> {target}); "
            f"init_deck_brief refuses to follow it (broken or not). "
            f"Remove or rename the symlink and re-run."
        )
    if brief_path.exists():
        return 2, (
            f"FAIL: {brief_path} already exists; init_deck_brief refuses "
            f"to overwrite a prior brief. Rename or remove it and re-run."
        )

    # Stage-1 (Intake) prerequisite: source_manifest.json must exist and
    # validate, and its on-disk source.md must match. Reuse the existing
    # bridge so the same gates that validate_workspace.py enforces are
    # the gates that gate the helper. No re-implementation, no skew.
    manifest_path = workspace / SOURCE_MANIFEST_FILENAME
    # Symlink preflight: a symlink at source_manifest.json — broken
    # OR resolvable — is refused BEFORE the is_file gate and BEFORE
    # check_source_manifest_bridge / read_text run. Path.is_file()
    # follows symlinks and returns False for a dangling target, so a
    # broken-link manifest would be mis-reported as the legacy
    # missing-manifest case; a resolvable symlink would let the
    # bridge's read_text() follow the link and validate manifest
    # bytes from outside the workspace, then the helper would re-read
    # the same off-workspace bytes when extracting source.id. The
    # preflight closes both holes. A missing manifest (no path entry
    # at all) still falls through to the explicit FAIL below.
    if manifest_path.is_symlink():
        try:
            target = str(manifest_path.readlink())
        except OSError:
            target = "<unreadable>"
        return 2, (
            f"FAIL: {manifest_path} is a symlink (-> {target}); "
            f"init_deck_brief refuses to follow it (broken or not). "
            f"source_manifest.json must be a regular in-workspace "
            f"file. Remove or rename the symlink and re-run."
        )
    if not manifest_path.is_file():
        return 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{SOURCE_MANIFEST_FILENAME}; run scripts/init_workspace.py "
            f"first to seed Stage-1 intake (input/source.md + "
            f"source_manifest.json)."
        )

    bridge_results = check_source_manifest_bridge(workspace)
    # The bridge returns an empty list when the manifest is absent, which
    # we already ruled out above. Any failed row here is a Stage-1
    # contract violation we must surface BEFORE writing the brief.
    bridge_failures = [r for r in bridge_results if not r.ok]
    if bridge_failures:
        detail = "; ".join(
            f"{r.name}{(': ' + r.detail) if r.detail else ''}"
            for r in bridge_failures
        )
        return 2, (
            f"FAIL: Stage-1 (Intake) bridge does not pass for "
            f"{workspace}: {detail}"
        )

    # Pull the manifest's source.id directly (the bridge above already
    # confirmed the manifest is schema-valid and matches the on-disk
    # source). We deliberately re-read instead of trusting bridge state
    # so the dependency on the bridge stays narrow (boolean pass/fail).
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return 2, (
            f"FAIL: cannot re-read {manifest_path} after the bridge "
            f"reported pass: {exc}"
        )
    source = manifest.get("source") or {}
    source_id = source.get("id")
    if not isinstance(source_id, str) or not source_id:
        # The bridge would have caught this — defense in depth.
        return 1, (
            f"FAIL: source_manifest.source.id is missing or not a "
            f"string ({source_id!r}); the bridge should have flagged "
            f"this earlier"
        )

    brief = _build_brief(
        source_id=source_id,
        title=title,
        audience=audience,
        objective=objective,
        tone=tone,
        language=language,
        approximate_slide_count=approximate_slide_count,
    )

    # Pre-write schema validation. Same defense-in-depth pattern as
    # init_workspace.py: validate IN MEMORY against the on-disk schema
    # before any filesystem mutation, so a mid-write crash cannot leave
    # a half-written workspace.
    try:
        schema_errors = _validate_brief_in_memory(brief)
    except (Exception, SystemExit) as exc:
        return 1, (
            f"FAIL: pre-write schema validation of the in-memory "
            f"deck_brief raised {type(exc).__name__}: {exc}"
        )
    if schema_errors:
        return 1, (
            "FAIL: the deck_brief this helper just built does not match "
            f"schemas/{DECK_BRIEF_SCHEMA.name}: " + "; ".join(schema_errors)
        )

    # Write. The brief is small enough that we do not need a temp-file
    # rename dance — but we DO want to roll back on a post-write
    # re-validation failure. The catch clause is explicitly
    # (Exception, SystemExit) so validate_artifact's SystemExit branch
    # (raised on its own OSError / JSONDecodeError) still routes
    # through the rollback path. KeyboardInterrupt is intentionally
    # NOT caught so Ctrl-C stays responsive.
    try:
        brief_path.write_text(
            json.dumps(brief, indent=2, sort_keys=True) + "\n"
        )
    except (Exception, SystemExit) as exc:
        # No partial state to clean up — write_text either wrote the
        # file or it didn't. Defensively remove if it appeared.
        if brief_path.exists():
            try:
                brief_path.unlink()
            except OSError:
                pass
        return 2, (
            f"FAIL: writing {brief_path} raised {type(exc).__name__}: "
            f"{exc}"
        )

    try:
        errors = validate_artifact(brief_path, DECK_BRIEF_SCHEMA)
    except (Exception, SystemExit) as exc:
        try:
            brief_path.unlink()
            rb_note = f"removed {brief_path}"
        except OSError as unlink_exc:
            rb_note = f"could not remove {brief_path}: {unlink_exc}"
        return 1, (
            f"FAIL: post-write re-validation of {brief_path} raised "
            f"{type(exc).__name__}: {exc}\n"
            f"rolled back: {rb_note}"
        )
    if errors:
        try:
            brief_path.unlink()
            rb_note = f"removed {brief_path}"
        except OSError as unlink_exc:
            rb_note = f"could not remove {brief_path}: {unlink_exc}"
        return 1, (
            f"FAIL: on-disk deck_brief at {brief_path} did not "
            f"re-validate: {errors}\n"
            f"rolled back: {rb_note}"
        )

    optional_summary = []
    if tone is not None:
        optional_summary.append(f"tone={tone.strip()!r}")
    if language is not None:
        optional_summary.append(f"language={language.strip()!r}")
    if approximate_slide_count is not None:
        optional_summary.append(
            f"approximate_slide_count={approximate_slide_count}"
        )
    optional_line = (
        f"  optional metadata: {', '.join(optional_summary)}\n"
        if optional_summary
        else "  optional metadata: (none)\n"
    )
    return 0, (
        f"OK: Stage-2 deck_brief seeded at {brief_path}.\n"
        f"  source_refs: [{source_id!r}] (from "
        f"{SOURCE_MANIFEST_FILENAME})\n"
        f"  title: {title.strip()!r}\n"
        f"  audience: {audience.strip()!r}\n"
        f"  objective: {objective.strip()!r}\n"
        f"{optional_line}"
        f"Next stages (agent-driven; init_deck_brief.py does not "
        f"automate them):\n"
        f"  3. deck_plan.json\n"
        f"  4. design_system.json\n"
        f"  5. slide_plans/*.json\n"
        f"  6. image_manifest.json\n"
        f"Once those exist, scripts/run_pipeline.py can take over for "
        f"stages 7-10."
    )


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs under
# tempfile.TemporaryDirectory(); no fixture leaks into the repo.
# ---------------------------------------------------------------------------

_SYNTH_SOURCE_MD = (
    "# Synthetic Source\n\n"
    "Synthetic .md body — never inspected by init_deck_brief.\n"
    "Line three.\n"
)


def _seed_stage1_workspace(
    ws: Path,
    *,
    source_id: str = "synthetic_src",
    body: bytes | None = None,
    kind: str = "markdown",
    write_source_file: bool = True,
    local_path: str = SOURCE_MANIFEST_LOCAL_PATH,
    sha256_override: str | None = None,
) -> None:
    """Mimic what scripts/init_workspace.py would have written into a
    fresh workspace. Stays in sync with init_workspace.py's
    _build_manifest contract but does not invoke it as a subprocess
    so the self-test can apply targeted negative mutations."""
    import hashlib
    if body is None:
        body = _SYNTH_SOURCE_MD.encode("utf-8")
    ws.mkdir(parents=True, exist_ok=True)
    if write_source_file:
        (ws / "input").mkdir(parents=True, exist_ok=True)
        (ws / "input" / "source.md").write_bytes(body)
    line_count = (
        body.count(b"\n") + (0 if body.endswith(b"\n") else 1)
        if body else 0
    )
    sha = sha256_override or hashlib.sha256(body).hexdigest()
    manifest = {
        "schema_version": "1",
        "source": {
            "id": source_id,
            "local_path": local_path,
            "kind": kind,
            "byte_count": len(body),
            "line_count": line_count,
            "sha256": sha,
        },
        "tool": {"name": "init_workspace", "version": "1"},
    }
    (ws / SOURCE_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )


def _expect(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


def _run_self_tests() -> list[tuple[str, bool, str]]:
    import tempfile

    results: list[tuple[str, bool, str]] = []

    # 1. happy path: minimal required metadata yields a schema-valid
    # brief whose source_refs is exactly [source.id] and which carries
    # NO invented optional fields.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_happy"
        _seed_stage1_workspace(ws, source_id="synthetic_a")
        rc, msg = init_deck_brief(
            workspace=ws,
            title="Synthetic Title",
            audience="Synthetic Audience",
            objective="Synthetic Objective",
        )
        brief_path = ws / DECK_BRIEF_FILENAME
        ok = rc == 0 and brief_path.is_file()
        if ok:
            brief = json.loads(brief_path.read_text())
            ok = (
                brief.get("title") == "Synthetic Title"
                and brief.get("audience") == "Synthetic Audience"
                and brief.get("objective") == "Synthetic Objective"
                and brief.get("source_refs") == ["synthetic_a"]
                and "key_messages" not in brief
                and "constraints" not in brief
                and "tone" not in brief
                and "language" not in brief
                and "approximate_slide_count" not in brief
            )
        results.append(_expect(
            "happy path: minimal required metadata emits a schema-valid "
            "deck_brief whose source_refs=[source.id] and no optional "
            "fields are invented",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 2. happy path: optional fields are propagated verbatim when the
    # caller passes them, and only when the caller passes them.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_opt"
        _seed_stage1_workspace(ws, source_id="synthetic_b")
        rc, _msg = init_deck_brief(
            workspace=ws,
            title="T",
            audience="A",
            objective="O",
            tone="neutral",
            language="en",
            approximate_slide_count=8,
        )
        brief_path = ws / DECK_BRIEF_FILENAME
        ok = rc == 0 and brief_path.is_file()
        if ok:
            brief = json.loads(brief_path.read_text())
            ok = (
                brief.get("tone") == "neutral"
                and brief.get("language") == "en"
                and brief.get("approximate_slide_count") == 8
                and brief.get("source_refs") == ["synthetic_b"]
            )
        results.append(_expect(
            "optional metadata (--tone, --language, "
            "--approximate-slide-count) is included only when supplied",
            ok, f"rc={rc}",
        ))

    # 3. determinism: two independent runs from the same workspace +
    # metadata produce byte-identical briefs.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws_a = td / "ws_det_a"
        ws_b = td / "ws_det_b"
        _seed_stage1_workspace(ws_a, source_id="det_src")
        _seed_stage1_workspace(ws_b, source_id="det_src")
        rc_a, _ = init_deck_brief(
            workspace=ws_a, title="T", audience="A", objective="O",
        )
        rc_b, _ = init_deck_brief(
            workspace=ws_b, title="T", audience="A", objective="O",
        )
        bytes_a = (ws_a / DECK_BRIEF_FILENAME).read_bytes() if rc_a == 0 else b""
        bytes_b = (ws_b / DECK_BRIEF_FILENAME).read_bytes() if rc_b == 0 else b""
        ok = rc_a == 0 and rc_b == 0 and bytes_a == bytes_b and bytes_a
        results.append(_expect(
            "determinism: two independent runs produce byte-identical "
            "briefs (no timestamps, no environment leak, sorted keys)",
            ok, f"rc_a={rc_a}, rc_b={rc_b}, equal={bytes_a == bytes_b}",
        ))

    # 4. missing source_manifest.json (legacy / not-yet-initialized
    # workspace) is refused with a clear message — the helper does NOT
    # silently fall back to inventing a source id.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_manifest"
        ws.mkdir()
        rc, msg = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
        )
        ok = (
            rc == 2
            and "source_manifest.json" in msg
            and not (ws / DECK_BRIEF_FILENAME).exists()
        )
        results.append(_expect(
            "missing source_manifest.json refused (no silent fallback)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # 4b. BROKEN symlink at source_manifest.json must fail at the
    # symlink preflight BEFORE the is_file check and BEFORE the
    # bridge runs. Without the preflight, Path.is_file() (which
    # follows symlinks and returns False for a dangling target)
    # would mis-report the broken-link workspace as the legacy
    # missing-manifest case. The dangling target must remain absent
    # afterwards (read_text never followed the link) AND no
    # deck_brief.json may be written.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_manifest_broken_symlink"
        _seed_stage1_workspace(ws, source_id="synthetic_bs")
        manifest_path = ws / SOURCE_MANIFEST_FILENAME
        manifest_path.unlink()
        dangling = td / "no_such_manifest.json"
        assert not dangling.exists()
        manifest_path.symlink_to(dangling)
        rc, msg = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
        )
        still_symlink = manifest_path.is_symlink()
        target_absent = not dangling.exists()
        brief_absent = not (ws / DECK_BRIEF_FILENAME).exists()
        ok = (
            rc == 2
            and "symlink" in msg
            and "source_manifest.json" in msg
            and still_symlink
            and target_absent
            and brief_absent
        )
        results.append(_expect(
            "broken symlink at source_manifest.json refused at the "
            "symlink preflight BEFORE is_file / bridge / read_text; "
            "dangling target is never created and no deck_brief.json "
            "is written",
            ok,
            f"rc={rc}, still_symlink={still_symlink}, "
            f"target_absent={target_absent}, brief_absent={brief_absent}, "
            f"msg={msg!r}",
        ))

    # 4c. RESOLVABLE symlink at source_manifest.json (link points at
    # a real manifest-shaped file outside the workspace) must ALSO
    # fail at the same preflight. Without it, the bridge's
    # read_text() would follow the link and validate manifest bytes
    # from outside the workspace, then the helper would re-read the
    # same off-workspace bytes when extracting source.id — both
    # cross-workspace reads from a path init_deck_brief never
    # vetted. The outside file's bytes must be preserved byte-
    # identical AND no deck_brief.json may be written.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_manifest_live_symlink"
        ws.mkdir()
        outside_manifest = td / "outside_manifest.json"
        outside_bytes = (
            b'{"schema_version": "1", '
            b'"source": {"id": "outside_src", '
            b'"local_path": "input/source.md", "kind": "markdown", '
            b'"byte_count": 1, "line_count": 1, '
            b'"sha256": "' + b"0" * 64 + b'"}, '
            b'"tool": {"name": "init_workspace", "version": "1"}}\n'
        )
        outside_manifest.write_bytes(outside_bytes)
        (ws / SOURCE_MANIFEST_FILENAME).symlink_to(outside_manifest)
        rc, msg = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
        )
        outside_preserved = outside_manifest.read_bytes() == outside_bytes
        brief_absent = not (ws / DECK_BRIEF_FILENAME).exists()
        ok = (
            rc == 2
            and "symlink" in msg
            and "source_manifest.json" in msg
            and outside_preserved
            and brief_absent
        )
        results.append(_expect(
            "resolvable symlink at source_manifest.json refused at "
            "the same preflight; the outside target's bytes are "
            "preserved byte-identical and no deck_brief.json is "
            "written",
            ok,
            f"rc={rc}, outside_preserved={outside_preserved}, "
            f"brief_absent={brief_absent}",
        ))

    # 5. missing input/source.md (manifest present, on-disk source
    # absent) is refused via the bridge.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_source"
        _seed_stage1_workspace(ws, write_source_file=False)
        rc, msg = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
        )
        ok = (
            rc == 2
            and "Stage-1" in msg
            and not (ws / DECK_BRIEF_FILENAME).exists()
        )
        results.append(_expect(
            "missing input/source.md refused (Stage-1 bridge fails closed)",
            ok, f"rc={rc}",
        ))

    # 6. malformed source_manifest (not valid JSON) is refused at the
    # bridge layer, BEFORE the brief is written.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_bad_json"
        _seed_stage1_workspace(ws)
        (ws / SOURCE_MANIFEST_FILENAME).write_text("{ not valid json")
        rc, msg = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
        )
        ok = (
            rc == 2
            and "Stage-1" in msg
            and not (ws / DECK_BRIEF_FILENAME).exists()
        )
        results.append(_expect(
            "malformed source_manifest.json (non-JSON) refused before "
            "any deck_brief is written",
            ok, f"rc={rc}",
        ))

    # 7. malformed source_manifest (schema-invalid: missing source.id)
    # is refused at the schema layer.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_bad_schema"
        _seed_stage1_workspace(ws)
        broken = {"schema_version": "1", "tool": {
            "name": "init_workspace", "version": "1",
        }}
        (ws / SOURCE_MANIFEST_FILENAME).write_text(json.dumps(broken))
        rc, msg = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
        )
        ok = (
            rc == 2
            and "Stage-1" in msg
            and not (ws / DECK_BRIEF_FILENAME).exists()
        )
        results.append(_expect(
            "schema-invalid source_manifest.json (missing required key) "
            "refused at the bridge layer",
            ok, f"rc={rc}",
        ))

    # 8. sha256 mismatch between manifest and on-disk source is refused
    # at the bridge layer.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_sha_mismatch"
        _seed_stage1_workspace(ws, sha256_override="0" * 64)
        rc, msg = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
        )
        ok = (
            rc == 2
            and "Stage-1" in msg
            and not (ws / DECK_BRIEF_FILENAME).exists()
        )
        results.append(_expect(
            "sha256 mismatch between manifest and on-disk source is "
            "refused (Stage-1 bridge fails closed)",
            ok, f"rc={rc}",
        ))

    # 9. deck_brief.json already exists -> refuse to overwrite.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_exists"
        _seed_stage1_workspace(ws, source_id="synthetic_c")
        prior = json.dumps({"prior": True})
        (ws / DECK_BRIEF_FILENAME).write_text(prior)
        rc, msg = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
        )
        # Prior contents must be preserved byte-identical.
        preserved = (ws / DECK_BRIEF_FILENAME).read_text() == prior
        ok = rc == 2 and "already exists" in msg and preserved
        results.append(_expect(
            "pre-existing deck_brief.json refused (no overwrite); "
            "prior contents preserved byte-identical",
            ok, f"rc={rc}, preserved={preserved}",
        ))

    # 9b. deck_brief.json present as a BROKEN symlink (target does not
    # exist) must be refused, BEFORE write_text() runs. Path.exists()
    # returns False for a broken symlink, so a bare exists() gate would
    # let write_text() follow the dangling link and silently clobber
    # whatever the link names. The symlink-first guard closes that hole.
    # The "target" path on the filesystem must remain absent after the
    # refused run — write_text() must NEVER have been called.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_broken_symlink"
        _seed_stage1_workspace(ws, source_id="synthetic_d")
        target = td / "outside_target_must_not_be_written.json"
        # Sanity: target does not exist yet.
        assert not target.exists()
        (ws / DECK_BRIEF_FILENAME).symlink_to(target)
        rc, msg = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
        )
        # The symlink must still be a symlink (not replaced by a
        # regular file), the target must STILL be absent (proving
        # write_text never followed the dangling link), and the FAIL
        # message must name the symlink path.
        still_symlink = (ws / DECK_BRIEF_FILENAME).is_symlink()
        target_absent = not target.exists()
        ok = (
            rc == 2
            and "symlink" in msg
            and still_symlink
            and target_absent
        )
        results.append(_expect(
            "broken symlink at deck_brief.json is refused BEFORE "
            "write_text could follow it; the dangling target is never "
            "created (proves Path.exists()'s false-False for broken "
            "symlinks does not bypass the no-overwrite gate)",
            ok,
            f"rc={rc}, still_symlink={still_symlink}, "
            f"target_absent={target_absent}, msg={msg!r}",
        ))

    # 9c. deck_brief.json present as a RESOLVABLE symlink pointing at
    # a real file outside the workspace must ALSO be refused. The
    # symlink-first guard is independent of whether the symlink
    # target exists — both broken and resolvable links are rejected.
    # The outside file's bytes must be preserved byte-identical.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_live_symlink"
        _seed_stage1_workspace(ws, source_id="synthetic_e")
        outside = td / "unrelated_file.json"
        outside_bytes = b'{"unrelated": "must not be clobbered"}\n'
        outside.write_bytes(outside_bytes)
        (ws / DECK_BRIEF_FILENAME).symlink_to(outside)
        rc, msg = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
        )
        still_symlink = (ws / DECK_BRIEF_FILENAME).is_symlink()
        outside_preserved = outside.read_bytes() == outside_bytes
        ok = (
            rc == 2
            and "symlink" in msg
            and still_symlink
            and outside_preserved
        )
        results.append(_expect(
            "resolvable symlink at deck_brief.json is refused (same "
            "rule as the broken-link case); the symlink target's bytes "
            "are preserved byte-identical (write_text never followed)",
            ok,
            f"rc={rc}, still_symlink={still_symlink}, "
            f"outside_preserved={outside_preserved}",
        ))

    # 10. workspace does not exist -> refuse cleanly.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rc, msg = init_deck_brief(
            workspace=td / "no_such_dir",
            title="T", audience="A", objective="O",
        )
        ok = rc == 2 and "does not exist" in msg
        results.append(_expect(
            "missing --workspace refused", ok, f"rc={rc}",
        ))

    # 11. --workspace is a regular file (not a directory).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        f = td / "ws_file"
        f.write_text("hi")
        rc, msg = init_deck_brief(
            workspace=f, title="T", audience="A", objective="O",
        )
        ok = rc == 2 and "not a directory" in msg
        results.append(_expect(
            "--workspace pointing at a regular file refused",
            ok, f"rc={rc}",
        ))

    # 12. --workspace as URI is refused at the string level (BEFORE
    # filesystem access).
    rc, msg = init_deck_brief(
        workspace=Path("https://attacker.example/ws"),
        title="T", audience="A", objective="O",
    )
    ok = rc == 2 and "URI" in msg
    results.append(_expect(
        "--workspace with URI scheme refused at the string level",
        ok, f"rc={rc}",
    ))

    # 13. --title empty (after strip) -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_empty_title"
        _seed_stage1_workspace(ws)
        rc, msg = init_deck_brief(
            workspace=ws, title="   ", audience="A", objective="O",
        )
        ok = rc == 2 and "--title" in msg
        results.append(_expect(
            "empty --title (after strip) refused",
            ok, f"rc={rc}",
        ))

    # 14. --title contains a newline -> refused (no content extraction).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_multiline_title"
        _seed_stage1_workspace(ws)
        rc, msg = init_deck_brief(
            workspace=ws,
            title="Line one\nLine two",
            audience="A", objective="O",
        )
        ok = rc == 2 and "--title" in msg and "single line" in msg
        results.append(_expect(
            "--title with embedded newline refused (no multi-line "
            "copy from source body)",
            ok, f"rc={rc}",
        ))

    # 15. --audience empty -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_empty_aud"
        _seed_stage1_workspace(ws)
        rc, msg = init_deck_brief(
            workspace=ws, title="T", audience="", objective="O",
        )
        ok = rc == 2 and "--audience" in msg
        results.append(_expect(
            "empty --audience refused", ok, f"rc={rc}",
        ))

    # 16. --objective with embedded carriage return -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_cr_obj"
        _seed_stage1_workspace(ws)
        rc, msg = init_deck_brief(
            workspace=ws,
            title="T", audience="A",
            objective="line one\rline two",
        )
        ok = rc == 2 and "--objective" in msg
        results.append(_expect(
            "--objective with embedded carriage return refused",
            ok, f"rc={rc}",
        ))

    # 17. --tone empty when supplied -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_empty_tone"
        _seed_stage1_workspace(ws)
        rc, msg = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
            tone="   ",
        )
        ok = rc == 2 and "--tone" in msg
        results.append(_expect(
            "empty --tone (after strip) refused when supplied",
            ok, f"rc={rc}",
        ))

    # 18. --approximate-slide-count of 0 -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_zero_count"
        _seed_stage1_workspace(ws)
        rc, msg = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
            approximate_slide_count=0,
        )
        ok = rc == 2 and "--approximate-slide-count" in msg
        results.append(_expect(
            "non-positive --approximate-slide-count refused",
            ok, f"rc={rc}",
        ))

    # 19. --approximate-slide-count negative -> refused.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_neg_count"
        _seed_stage1_workspace(ws)
        rc, msg = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
            approximate_slide_count=-3,
        )
        ok = rc == 2 and "--approximate-slide-count" in msg
        results.append(_expect(
            "negative --approximate-slide-count refused",
            ok, f"rc={rc}",
        ))

    # 20. On-disk brief re-validates via validate_artifact.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_revalidate"
        _seed_stage1_workspace(ws, source_id="rev_src")
        rc, _ = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
        )
        ok = rc == 0
        if ok:
            errors = validate_artifact(
                ws / DECK_BRIEF_FILENAME, DECK_BRIEF_SCHEMA,
            )
            ok = not errors
        results.append(_expect(
            "on-disk deck_brief.json re-validates against "
            "schemas/deck_brief.schema.json via validate_artifact",
            ok, "",
        ))

    # 21. post-write re-validation FAILURE (forced via mock) rolls back
    # the just-written brief. The brief must not exist on disk after.
    import unittest.mock
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_rb"
        _seed_stage1_workspace(ws)
        with unittest.mock.patch(
            f"{__name__}.validate_artifact",
            return_value=["forced test failure"],
        ):
            rc, msg = init_deck_brief(
                workspace=ws, title="T", audience="A", objective="O",
            )
        ok = (
            rc == 1
            and "rolled back" in msg
            and not (ws / DECK_BRIEF_FILENAME).exists()
        )
        results.append(_expect(
            "post-write re-validation failure (forced via mock) rolls "
            "back the brief so the workspace is never left half-written",
            ok, f"rc={rc}, exists={(ws / DECK_BRIEF_FILENAME).exists()}",
        ))

    # 22. post-write re-validation RAISING SystemExit (the exception
    # validate_artifact uses on its own read-error branch) also rolls
    # back. Without the (Exception, SystemExit) catch clause, the
    # half-written brief would survive on disk.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_rb_sysexit"
        _seed_stage1_workspace(ws)
        with unittest.mock.patch(
            f"{__name__}.validate_artifact",
            side_effect=SystemExit("simulated read-error branch"),
        ):
            rc, msg = init_deck_brief(
                workspace=ws, title="T", audience="A", objective="O",
            )
        ok = (
            rc == 1
            and "rolled back" in msg
            and "SystemExit" in msg
            and not (ws / DECK_BRIEF_FILENAME).exists()
        )
        results.append(_expect(
            "post-write re-validation RAISING SystemExit rolls back "
            "(proves catch clause is (Exception, SystemExit), not just "
            "Exception)",
            ok, f"rc={rc}",
        ))

    # 23. Source body bytes never appear in the brief. This is the
    # cardinal contract — the helper is a contract bridge, not a
    # content-extraction tool. Use a marker phrase in the body and
    # confirm it does not surface in the written brief.
    marker = "MARKER_NEVER_EXTRACT_b4be6b"
    body = (
        f"# Title\n\nBody with {marker} in it.\n"
    ).encode("utf-8")
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_extract"
        _seed_stage1_workspace(ws, body=body, source_id="extract_src")
        rc, _msg = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
        )
        ok = rc == 0
        if ok:
            written = (ws / DECK_BRIEF_FILENAME).read_text()
            ok = marker not in written
        results.append(_expect(
            "source body marker phrase is NEVER copied into "
            "deck_brief.json (helper does not extract content)",
            ok, f"rc={rc}",
        ))

    # 24. ``source_refs`` always contains exactly the manifest's
    # source.id — not the user's title, not the audience, not the
    # objective. This is the (3) contract gate from the goal.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_source_refs"
        _seed_stage1_workspace(ws, source_id="unique_src_id_42")
        rc, _msg = init_deck_brief(
            workspace=ws,
            title="Title that should NOT leak into source_refs",
            audience="A", objective="O",
        )
        ok = rc == 0
        if ok:
            brief = json.loads((ws / DECK_BRIEF_FILENAME).read_text())
            ok = brief.get("source_refs") == ["unique_src_id_42"]
        results.append(_expect(
            "deck_brief.source_refs is exactly [source_manifest.source.id]",
            ok, f"rc={rc}",
        ))

    # 25. The bridge-validator gate that fails closed when deck_brief
    # omits source.id IS the gate the goal calls out as (4). Build a
    # workspace where the helper produced a correct brief, then
    # manually mutate the brief to drop source_id from source_refs and
    # confirm check_source_manifest_bridge reports a FAIL row.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_mutate_brief"
        _seed_stage1_workspace(ws, source_id="mut_src")
        rc, _ = init_deck_brief(
            workspace=ws, title="T", audience="A", objective="O",
        )
        ok = rc == 0
        if ok:
            # Drop the source.id from source_refs (substitute another
            # synthetic id) and re-run the bridge. The contract is the
            # bridge MUST flag this case.
            brief_path = ws / DECK_BRIEF_FILENAME
            brief = json.loads(brief_path.read_text())
            brief["source_refs"] = ["some_other_id"]
            brief_path.write_text(json.dumps(brief))
            rows = check_source_manifest_bridge(ws)
            ok = any(
                "deck_brief.source_refs declares" in r.name and not r.ok
                for r in rows
            )
        results.append(_expect(
            "after a brief is mutated to drop source.id from source_refs, "
            "check_source_manifest_bridge fails closed on the "
            "deck_brief.source_refs cross-check",
            ok, "",
        ))

    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage-2 (Brief) deck_brief.json helper. Bridges a stage-1-"
            "initialized workspace (source_manifest.json + "
            "input/source.md) into a minimal, schema-valid deck_brief.json "
            "whose source_refs declares the manifest's source.id. Does "
            "NOT plan a deck and does NOT extract business content from "
            "the source body — stages 3-6 remain agent-driven."
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Workspace directory (must already contain "
             "source_manifest.json + input/source.md, e.g. seeded by "
             "scripts/init_workspace.py).",
    )
    parser.add_argument(
        "--title", type=str, default=None,
        help="Deck title. Required. Must be non-empty after strip() "
             "and single-line (no embedded newline / carriage return).",
    )
    parser.add_argument(
        "--audience", type=str, default=None,
        help="Audience label. Required. Same single-line constraint as "
             "--title.",
    )
    parser.add_argument(
        "--objective", type=str, default=None,
        help="Deck objective. Required. Same single-line constraint as "
             "--title.",
    )
    parser.add_argument(
        "--tone", type=str, default=None,
        help="Optional tone tag. When supplied must be non-empty and "
             "single-line.",
    )
    parser.add_argument(
        "--language", type=str, default=None,
        help="Optional BCP-47 language tag. When supplied must be "
             "non-empty and single-line.",
    )
    parser.add_argument(
        "--approximate-slide-count", type=int, default=None,
        help="Optional positive integer slide-count target. Stage-3 "
             "planning is free to deviate from this.",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios (happy path, optional-"
             "fields propagation, determinism, missing source_manifest, "
             "BROKEN symlink at source_manifest.json (refused at the "
             "preflight BEFORE is_file / bridge / read_text; dangling "
             "target never created; no deck_brief.json written), "
             "RESOLVABLE symlink at source_manifest.json (refused at "
             "the same preflight; outside target bytes preserved; no "
             "deck_brief.json written), missing input/source.md, "
             "malformed (non-JSON) source_manifest, schema-invalid "
             "source_manifest, sha256 mismatch, pre-existing "
             "deck_brief.json (regular file), BROKEN symlink at "
             "deck_brief.json (dangling target never created; proves "
             "write_text() cannot silently follow a dangling link), "
             "RESOLVABLE symlink at deck_brief.json (target file's "
             "bytes preserved), missing / regular-file / URI-scheme "
             "--workspace, empty / multi-line --title / --audience / "
             "--objective, empty --tone, non-positive "
             "--approximate-slide-count, on-disk re-validation, mocked "
             "post-write rollback (return errors / raise SystemExit), "
             "source-body content never copied into the brief, "
             "source_refs always equals [source.id], and the bridge "
             "validator catches a mutated brief that drops source.id "
             "from source_refs). "
             "Exits non-zero if any scenario does not behave as "
             "expected. Mutually exclusive with the metadata args.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if any(v is not None for v in (
            args.workspace, args.title, args.audience, args.objective,
            args.tone, args.language, args.approximate_slide_count,
        )):
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
            "happy-path brief is written from the Stage-1 manifest."
        )
        return 0

    missing = [
        name for name, value in (
            ("--workspace", args.workspace),
            ("--title", args.title),
            ("--audience", args.audience),
            ("--objective", args.objective),
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

    rc, msg = init_deck_brief(
        workspace=args.workspace,
        title=args.title,
        audience=args.audience,
        objective=args.objective,
        tone=args.tone,
        language=args.language,
        approximate_slide_count=args.approximate_slide_count,
    )
    if rc == 0:
        print(msg)
    else:
        print(msg, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
