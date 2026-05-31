#!/usr/bin/env python3
"""Local source-file -> Markdown ingestion bridge (MOCK / LOCAL only).

This is the smallest front door that lets an operator START from a local
report file instead of having to hand-prepare a Markdown file. It accepts
a local ``.md`` or ``.txt`` source, normalises it into Markdown with ATX
(``# Title``) headings, and feeds the result into the EXISTING
``source_to_image_requests.py`` bridge (its ``--mock-handoff`` lane) which
parses one image request per heading and drives the operator
image-to-editable-PPT lane to a validated review package.

It does NOT invent document structure. ``source_to_image_requests.py``
already accepts any UTF-8 file and derives requests from its ATX
headings; this wrapper only adds a gated local-file front door in front
of that lane (extension allow-list, DOCX/PDF TODO, repo-generated-artifact
refusal, a convert-only ``--md-out`` mode). It stays inside the current
first-stage scope (local/generated images -> review package): it is a
mock/local bridge that feeds the EXISTING image lane, NOT report-to-deck
automation and NOT report understanding.

Markdown normalisation (``_to_markdown``):

  The source must ALREADY carry ATX (``# Title``) headings — in a ``.md``
  or in a ``.txt`` that uses ``# `` markers. When it does, the text is
  passed through to the bridge VERBATIM. When it does not, the run fails
  CLOSED with guidance to add ``# `` headings. The wrapper never promotes
  body lines to headings or guesses structure out of prose, so no body
  text can ever become a deck title.

What this is NOT:

  * NOT real image generation. The downstream ``--mock-handoff`` writes
    tiny locally-synthesised placeholder PNGs; no D-One, model API, image
    search, MCP, Qoder, public network, or telemetry is ever called.
  * NOT full report understanding. It derives nothing from the report
    body and invents no structure: it requires operator-supplied ``# ``
    headings and NEVER promotes body prose into the plan or the deck.
  * NOT a new parser/exporter. DOCX / PDF are NOT supported — the repo
    has no safe local extractor for them, so they are refused with an
    explicit TODO message rather than parsed with a fragile shim.
  * NOT a new safety contract. The whole source is scanned for
    credential / public-network / file-URI / absolute-path wording by
    REUSING ``source_to_image_requests._scan_source_safety``, and the
    downstream bridge re-runs every emitted-value gate, so this wrapper
    is provably no weaker than the bridge it feeds.

Fail-closed gates, BEFORE any conversion or downstream call:

  * URI-shaped ``--report`` (``file://`` / ``http://`` / any scheme);
  * ``--report`` is a symlink (or has a symlink ancestor);
  * ``--report`` resolves under the committed repo tree AND inside a
    generated-output directory (``out/`` / ``dist/`` / ``projects/`` /
    ``build/`` / ``previews/`` / ``renders/`` / ``exports/`` / ``tmp/`` /
    ``__pycache__/``) — a repo-resident generated artifact must not be
    fed back in as a source;
  * ``--report`` is not a regular file;
  * unsupported extension (only ``.md`` / ``.txt`` accepted; ``.docx`` /
    ``.pdf`` refused as TODO; everything else refused generically);
  * non-identifier-safe basename (mirrors the downstream bridge so the
    derived Markdown filename is safe);
  * empty / oversized / non-UTF-8 bytes;
  * any credential / public-network / file-URI / absolute-path wording.

CLI shape::

    # Convert only: local report -> Markdown on disk
    python3 scripts/ingest_local_source_file.py \\
        --report REPORT.txt --md-out SOURCE.md   # SOURCE.md outside repo

    # Mock/local handoff: convert -> existing bridge -> review package
    python3 scripts/ingest_local_source_file.py \\
        --report REPORT.txt --mock-handoff --out-dir OUT   # OUT outside repo

    # Self-test (every scenario under TMPDIR; nothing leaks under repo)
    python3 scripts/ingest_local_source_file.py --self-test

``--out-dir`` validation is delegated entirely to
``source_to_image_requests.py`` (which routes it through
``core_image_to_editable_ppt_demo._validate_out_dir_arg``), so the same
URI / symlink / symlink-ancestor / repo-tree / non-empty refusals apply.
The intermediate Markdown for ``--mock-handoff`` is written to a per-run
temporary directory and discarded; it never lands under the repo tree.

Stdlib-only. Local-only — does NOT call D-One, MCP, Qoder, a public
network, telemetry, a model API, an image search, or any external
service.
"""

from __future__ import annotations

import sys

# Refuse `.pyc` writes from any imported module. Mirrors the gate every
# sibling helper applies; must be flipped BEFORE any first-party import.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import tempfile  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

# Reuse the existing bridge wholesale: its source-safety scan, its ATX
# heading parser, its byte caps, and its CLI entrypoint. This wrapper adds
# ONLY a local-file front door + plain-text -> Markdown conversion; every
# safety/plan/handoff contract stays owned by source_to_image_requests.
import source_to_image_requests as s2ir  # noqa: E402

# Reuse the sibling helper's symlink-ancestor gate so this wrapper treats
# benign system aliases (macOS /tmp -> private/tmp) exactly as the operator
# out-dir gate does, instead of re-deriving that allow-list here.
from core_image_to_editable_ppt_demo import (  # noqa: E402
    _forbidden_symlink_ancestor,
)

# Accepted source extensions (case-insensitive).
ACCEPTED_EXTS: tuple[str, ...] = (".md", ".txt")
# Formats we explicitly know about but cannot safely extract locally yet.
# Refused with a TODO message rather than parsed with a fragile shim.
TODO_EXTS: tuple[str, ...] = (".docx", ".pdf")

# Generated-output directory names (mirrors .gitignore). A --report that
# resolves under the repo tree AND inside one of these is a generated
# artifact and must not be fed back in as a source.
_GENERATED_DIR_NAMES: frozenset[str] = frozenset(
    {
        "projects", "out", "output", "dist", "build",
        "previews", "renders", "exports", "tmp", "__pycache__",
    }
)

# Identifier-safe basename, matching source_to_image_requests._load_source
# so the Markdown filename derived from the report stem is safe downstream.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")


# ---------------------------------------------------------------------------
# Report-path gate.
# ---------------------------------------------------------------------------


def _is_repo_generated_path(resolved: Path) -> bool:
    """True iff ``resolved`` lexically anchors under REPO_ROOT AND has a
    path component inside a generated-output directory. Lexical only — it
    never touches the filesystem, so a non-existent path can be refused
    without creating it."""
    repo_root = REPO_ROOT.resolve(strict=False)
    try:
        rel = resolved.relative_to(repo_root)
    except ValueError:
        return False
    return any(part in _GENERATED_DIR_NAMES for part in rel.parts)


def _gate_report(report_arg: str) -> tuple[Path | None, str, list[str]]:
    """Resolve + validate the --report path WITHOUT reading it.

    Returns ``(path_or_None, suffix, failures)``. Order matters: cheap
    lexical refusals (URI / symlink / repo-generated) run before any
    ``stat``/read so a hostile path is rejected without filesystem access.
    """
    if "://" in report_arg:
        return None, "", [
            f"--report {report_arg!r} is URI-shaped; refused (local-only)"
        ]

    path = Path(report_arg)

    if path.is_symlink():
        try:
            tgt = os.readlink(path)
        except OSError:
            tgt = "<unreadable>"
        return None, "", [f"--report {path} is a symlink (-> {tgt}); refused"]

    bad_ancestor = _forbidden_symlink_ancestor(path)
    if bad_ancestor is not None:
        ancestor, tgt = bad_ancestor
        return None, "", [
            f"--report {path} has a symlink ancestor {ancestor} (-> {tgt}); "
            f"refused so a symlink in the typed path cannot redirect the read"
        ]

    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        return None, "", [
            f"--report {path} could not be resolved: {type(exc).__name__}: {exc}"
        ]

    if _is_repo_generated_path(resolved):
        return None, "", [
            f"--report {resolved} resolves inside a repo generated-output "
            f"directory; refused — a generated artifact must not be fed back "
            f"in as a source"
        ]

    if not path.is_file():
        return None, "", [f"--report {path} is not a regular file"]

    suffix = path.suffix.lower()
    if suffix in TODO_EXTS:
        return None, suffix, [
            f"--report {path} has extension {suffix!r}; {suffix} ingestion is "
            f"a TODO — the repo has no safe local {suffix.lstrip('.')} text "
            f"extractor, so it is refused rather than parsed with a fragile "
            f"shim. Convert it to .md or .txt first."
        ]
    if suffix not in ACCEPTED_EXTS:
        return None, suffix, [
            f"--report {path} has unsupported extension {suffix!r}; only "
            f"{', '.join(ACCEPTED_EXTS)} are accepted "
            f"({', '.join(TODO_EXTS)} are a documented TODO)"
        ]

    if not _SAFE_NAME_RE.match(path.name):
        return None, suffix, [
            f"--report basename {path.name!r} is not identifier-safe "
            f"(expected {_SAFE_NAME_RE.pattern})"
        ]

    return path, suffix, []


# ---------------------------------------------------------------------------
# Source loading + conversion.
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> tuple[str | None, list[str]]:
    """Read + UTF-8 decode the report, reusing the downstream bridge's byte
    cap so this wrapper cannot accept a source the bridge would refuse."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, [f"cannot read --report {path}: {type(exc).__name__}: {exc}"]
    if not raw:
        return None, [f"--report {path} is empty"]
    if len(raw) > s2ir.MAX_SOURCE_BYTES:
        return None, [
            f"--report {path} is {len(raw)} bytes; exceeds cap "
            f"{s2ir.MAX_SOURCE_BYTES}"
        ]
    try:
        return raw.decode("utf-8"), []
    except UnicodeDecodeError as exc:
        return None, [f"--report {path} is not valid UTF-8: {exc}"]


def _to_markdown(text: str) -> tuple[str | None, list[str]]:
    """Return the source as Markdown, requiring operator-supplied headings.

    The wrapper never invents structure. If the text already carries ATX
    (``# Title``) headings it is passed through VERBATIM (covers .md and
    any .txt using ``# `` markers); otherwise the run fails closed with
    guidance. No body line is ever promoted into a heading, so no report
    body text can become a deck title."""
    if s2ir._parse_headings(text):
        return text, []
    return None, [
        "source has no '# ' Markdown headings: the bridge derives one image "
        "request per heading and invents no structure. Add '# Heading' "
        "markers (a .txt may use them too) — body prose is never promoted "
        "to a title."
    ]


# ---------------------------------------------------------------------------
# md-out path gate (convert-only mode).
# ---------------------------------------------------------------------------


def _gate_md_out(md_out_arg: str) -> tuple[Path | None, list[str]]:
    """Validate a convert-only --md-out path. Refuses URI / symlink /
    symlink-ancestor / under-repo / existing / missing-parent paths so the
    wrapper never overwrites or leaks into the committed tree."""
    if "://" in md_out_arg:
        return None, [f"--md-out {md_out_arg!r} is URI-shaped; refused (local-only)"]
    path = Path(md_out_arg)
    if path.is_symlink():
        return None, [f"--md-out {path} is a symlink; refused"]
    bad_ancestor = _forbidden_symlink_ancestor(path)
    if bad_ancestor is not None:
        ancestor, tgt = bad_ancestor
        return None, [
            f"--md-out {path} has a symlink ancestor {ancestor} (-> {tgt}); refused"
        ]
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        return None, [f"--md-out {path} could not be resolved: {type(exc).__name__}: {exc}"]
    repo_root = REPO_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(repo_root)
        return None, [
            f"--md-out {resolved} lexically anchors under REPO_ROOT={repo_root}; "
            f"refused — write the derived Markdown outside the committed repo tree"
        ]
    except ValueError:
        pass
    if path.exists():
        return None, [f"--md-out {path} already exists; refused (no overwrite)"]
    if not path.parent.exists():
        return None, [
            f"--md-out {path} parent {path.parent} does not exist; create it "
            f"explicitly so a typo cannot be masked by an implicit mkdir -p"
        ]
    return path, []


# ---------------------------------------------------------------------------
# Modes.
# ---------------------------------------------------------------------------


def _load_and_convert(report_arg: str) -> tuple[Path | None, str | None, list[str]]:
    """Run the full gate -> read -> safety-scan -> convert pipeline.
    Returns (report_path, markdown_text, failures)."""
    path, _suffix, failures = _gate_report(report_arg)
    if failures or path is None:
        return None, None, failures
    text, failures = _read_text(path)
    if failures or text is None:
        return None, None, failures
    # Reuse the downstream bridge's source-safety scan up front so we fail
    # closed on credential / public-network / file-URI / absolute-path
    # wording before touching the conversion or the operator lane.
    failures = s2ir._scan_source_safety(text)
    if failures:
        return None, None, failures
    markdown, failures = _to_markdown(text)
    if failures or markdown is None:
        return None, None, failures
    return path, markdown, []


def _run_convert_only(report_arg: str, md_out_arg: str) -> int:
    md_out, failures = _gate_md_out(md_out_arg)
    if failures or md_out is None:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    _path, markdown, failures = _load_and_convert(report_arg)
    if failures or markdown is None:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    md_out.write_text(markdown, encoding="utf-8")
    print("=== ingest_local_source_file --md-out ===")
    print(f"  report:   {report_arg}")
    print(f"  markdown: {md_out}")
    print()
    print(f"OK: wrote derived Markdown to {md_out}. Feed it to "
          f"source_to_image_requests.py --source {md_out} --mock-handoff "
          f"--out-dir <dir outside repo>.")
    return 0


def _run_mock_handoff(report_arg: str, out_dir_arg: str) -> int:
    _path, markdown, failures = _load_and_convert(report_arg)
    if failures or markdown is None:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    # Stage the derived Markdown in a per-run tempdir (never under the repo
    # tree) and drive the EXISTING bridge. Naming the temp file after the
    # report stem keeps the downstream identifier-safe-basename gate happy
    # and preserves provenance in the bridge's plan.source.filename.
    stem = Path(report_arg).stem or "source"
    print("=== ingest_local_source_file --mock-handoff ===")
    print(f"  report:  {report_arg}")
    print(f"  out-dir: {out_dir_arg}")
    print()
    with tempfile.TemporaryDirectory(prefix="ingest-md-") as raw_td:
        md_path = Path(raw_td) / f"{stem}.md"
        md_path.write_text(markdown, encoding="utf-8")
        return s2ir.main(
            ["--source", str(md_path), "--mock-handoff", "--out-dir", out_dir_arg]
        )


# ---------------------------------------------------------------------------
# Self-test.
# ---------------------------------------------------------------------------


def _snapshot_dir(d: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        out[str(p.relative_to(d))] = p.read_bytes()
    return out


@dataclass
class _Probe:
    name: str
    ok: bool
    detail: str = ""


_SAMPLE_MD = """# Quarterly Strategy Overview

Some narrative body text describing the strategy in prose.

## Market Landscape

Body paragraph about the market.

## Closing Summary

Final body paragraph.
"""

# A .txt that already carries ATX '# ' headings (markdown-in-a-txt). It
# must pass through VERBATIM; body lines must never become headings.
_SAMPLE_TXT_WITH_HEADINGS = """# Quarterly Strategy Overview

This is a body paragraph describing the strategy.

# Market Landscape

ZZBODYMARKERZZ a body paragraph about the market.

# Closing Summary

Final body paragraph here.
"""

# A heading-less plain-text outline (standalone single-line titles). The
# wrapper invents no structure, so this must be REFUSED, not promoted.
_SAMPLE_TXT_NO_HEADINGS = """Quarterly Strategy Overview

A body paragraph describing the strategy.

Market Landscape

A body paragraph about the market.
"""


def _run_self_tests() -> int:
    print("=== ingest_local_source_file --self-test ===")
    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    scripts_before = _snapshot_dir(REPO_ROOT / "scripts")
    schemas_before = _snapshot_dir(REPO_ROOT / "schemas")
    probes: list[_Probe] = []

    # W1 .md report -> --md-out: headings preserved, passthrough.
    with tempfile.TemporaryDirectory(prefix="ilsf-W1-") as raw_td:
        td = Path(raw_td)
        report = td / "report.md"
        report.write_text(_SAMPLE_MD, encoding="utf-8")
        md_out = td / "derived.md"
        rc = _run_convert_only(str(report), str(md_out))
        ok = rc == 0 and md_out.is_file()
        detail = "" if ok else f"rc={rc}; md_out={md_out.is_file()}"
        if ok:
            got = md_out.read_text(encoding="utf-8")
            if got != _SAMPLE_MD:
                ok, detail = False, "markdown not passed through unchanged"
            elif len(s2ir._parse_headings(got)) != 3:
                ok, detail = False, f"expected 3 headings, got {len(s2ir._parse_headings(got))}"
        probes.append(_Probe("W1 .md passthrough -> md-out", ok, detail))

    # W2 .txt WITH '# ' headings -> --md-out: passed through VERBATIM, no
    # body line promoted to a heading.
    with tempfile.TemporaryDirectory(prefix="ilsf-W2-") as raw_td:
        td = Path(raw_td)
        report = td / "report.txt"
        report.write_text(_SAMPLE_TXT_WITH_HEADINGS, encoding="utf-8")
        md_out = td / "derived.md"
        rc = _run_convert_only(str(report), str(md_out))
        ok = rc == 0 and md_out.is_file()
        detail = "" if ok else f"rc={rc}; md_out={md_out.is_file()}"
        if ok:
            got = md_out.read_text(encoding="utf-8")
            headings = [h.text for h in s2ir._parse_headings(got)]
            if got != _SAMPLE_TXT_WITH_HEADINGS:
                ok, detail = False, "txt not passed through verbatim"
            elif headings != ["Quarterly Strategy Overview", "Market Landscape", "Closing Summary"]:
                ok, detail = False, f"unexpected headings: {headings!r}"
            elif "# ZZBODYMARKERZZ" in got:
                ok, detail = False, "body prose became a heading"
        probes.append(_Probe("W2 .txt with headings -> verbatim passthrough", ok, detail))

    # W3 .txt with NO headings (a standalone-line outline AND flowing prose)
    # -> refused. Proves the wrapper invents no structure: no body line is
    # ever promoted to a deck title.
    for label, body in (
        ("standalone-outline", _SAMPLE_TXT_NO_HEADINGS),
        ("flowing-prose", "This is line one.\nThis is line two.\nLine three.\n"),
    ):
        with tempfile.TemporaryDirectory(prefix=f"ilsf-W3-{label}-") as raw_td:
            td = Path(raw_td)
            report = td / "report.txt"
            report.write_text(body, encoding="utf-8")
            md_out = td / "derived.md"
            rc = _run_convert_only(str(report), str(md_out))
            ok = rc == 1 and not md_out.exists()
            probes.append(_Probe(f"W3 no-heading txt refused ({label})", ok,
                                 "" if ok else f"rc={rc}; md_out={md_out.exists()}"))

    # W4 unsupported / TODO extensions refused.
    for ext, label in ((".docx", "docx-todo"), (".pdf", "pdf-todo"), (".rtf", "generic")):
        with tempfile.TemporaryDirectory(prefix=f"ilsf-W4-{label}-") as raw_td:
            td = Path(raw_td)
            report = td / f"report{ext}"
            report.write_text("anything\n", encoding="utf-8")
            md_out = td / "derived.md"
            rc = _run_convert_only(str(report), str(md_out))
            ok = rc == 1 and not md_out.exists()
            probes.append(_Probe(f"W4 {ext} refused ({label})", ok, "" if ok else f"rc={rc}"))

    # W5 URI + symlink reports refused (lexical, no FS dependence for URI).
    with tempfile.TemporaryDirectory(prefix="ilsf-W5-") as raw_td:
        td = Path(raw_td)
        md_out = td / "derived.md"
        rc_uri = _run_convert_only("file:///tmp/report.md", str(md_out))
        ok_uri = rc_uri == 1 and not md_out.exists()
        probes.append(_Probe("W5a URI report refused", ok_uri, "" if ok_uri else f"rc={rc_uri}"))

        real = td / "real.md"
        real.write_text(_SAMPLE_MD, encoding="utf-8")
        link = td / "link.md"
        try:
            link.symlink_to(real)
            made_link = True
        except OSError:
            made_link = False
        md_out2 = td / "derived2.md"
        rc_sym = _run_convert_only(str(link), str(md_out2)) if made_link else 1
        ok_sym = (not made_link) or (rc_sym == 1 and not md_out2.exists())
        probes.append(_Probe("W5b symlink report refused", ok_sym, "" if ok_sym else f"rc={rc_sym}"))

    # W6 repo-resident generated artifact refused (lexical; path need not
    # exist, so nothing is written under the repo tree).
    with tempfile.TemporaryDirectory(prefix="ilsf-W6-") as raw_td:
        td = Path(raw_td)
        md_out = td / "derived.md"
        repo_generated = str(REPO_ROOT / "out" / "report.md")
        rc = _run_convert_only(repo_generated, str(md_out))
        ok = rc == 1 and not md_out.exists() and not (REPO_ROOT / "out").exists()
        probes.append(_Probe("W6 repo generated-dir source refused", ok, "" if ok else f"rc={rc}"))

    # W7 credential / public-network wording refused (reused bridge scan).
    for label, body in (
        ("credential", "# Title\n\napi_key = abc123\n"),
        ("public-network", "# Title\n\nSee https://example.test/x\n"),
    ):
        with tempfile.TemporaryDirectory(prefix=f"ilsf-W7-{label}-") as raw_td:
            td = Path(raw_td)
            report = td / "report.md"
            report.write_text(body, encoding="utf-8")
            md_out = td / "derived.md"
            rc = _run_convert_only(str(report), str(md_out))
            ok = rc == 1 and not md_out.exists()
            probes.append(_Probe(f"W7 unsafe wording refused ({label})", ok, "" if ok else f"rc={rc}"))

    # W8 md-out under repo refused.
    with tempfile.TemporaryDirectory(prefix="ilsf-W8-") as raw_td:
        td = Path(raw_td)
        report = td / "report.md"
        report.write_text(_SAMPLE_MD, encoding="utf-8")
        repo_md_out = str(REPO_ROOT / "derived_should_not_exist.md")
        rc = _run_convert_only(str(report), repo_md_out)
        ok = rc == 1 and not Path(repo_md_out).exists()
        probes.append(_Probe("W8 md-out under repo refused", ok, "" if ok else f"rc={rc}"))

    # W9 full mock/local handoff: heading-bearing .txt -> existing bridge
    # -> validated review package with an editable deck.pptx.
    with tempfile.TemporaryDirectory(prefix="ilsf-W9-") as raw_td:
        td = Path(raw_td)
        report = td / "report.txt"
        report.write_text(_SAMPLE_TXT_WITH_HEADINGS, encoding="utf-8")
        out_dir = td / "out"
        rc = _run_mock_handoff(str(report), str(out_dir))
        ok = rc == 0
        detail = "" if ok else f"rc={rc}"
        review = out_dir / "review_package"
        if ok:
            for rel in ("deck.pptx", "summary.json", "README.md"):
                if not (review / rel).is_file():
                    ok, detail = False, f"missing review_package/{rel}"
                    break
        if ok and not (out_dir / "image_request_plan.json").is_file():
            ok, detail = False, "missing image_request_plan.json"
        probes.append(_Probe("W9 mock handoff -> validated review package", ok, detail))

    # W10 URI --out-dir refused (delegated to the bridge's out-dir gate).
    with tempfile.TemporaryDirectory(prefix="ilsf-W10-") as raw_td:
        td = Path(raw_td)
        report = td / "report.md"
        report.write_text(_SAMPLE_MD, encoding="utf-8")
        uri_out = "file:///" + str(td / "u").lstrip("/")
        rc = _run_mock_handoff(str(report), uri_out)
        ok = rc == 2 and not (td / "u").exists()
        probes.append(_Probe("W10 URI out-dir refused (delegated)", ok, "" if ok else f"rc={rc}"))

    # Repo immutability.
    repo_ok = True
    for label, before in (
        ("examples", examples_before), ("scripts", scripts_before),
        ("schemas", schemas_before),
    ):
        after = _snapshot_dir(REPO_ROOT / label)
        if before != after:
            repo_ok = False
            changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
            print(f"FAIL: {label}/ mutated by self-test (changed: {changed!r})", file=sys.stderr)

    print()
    print("--- self-test results ---")
    rc = 0
    for p in probes:
        marker = "PASS" if p.ok else "FAIL"
        extra = f" ({p.detail})" if p.detail else ""
        print(f"  [{marker}] {p.name}{extra}")
        if not p.ok:
            rc = 1
    if not repo_ok:
        rc = 1
    if rc == 0:
        print()
        print("OK: every self-test probe passed; examples/ scripts/ schemas/ "
              "byte-identical pre/post; local-only (no D-One, MCP, Qoder, "
              "model API, image search, public network, or telemetry).")
    return rc


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Local source-file -> Markdown ingestion bridge (MOCK / LOCAL "
            "only). A gated local-file front door for the existing "
            "source_to_image_requests.py lane. Accepts a local .md or .txt "
            "report that ALREADY carries ATX '# ' headings, passes it "
            "through verbatim, and feeds it into the --mock-handoff lane to "
            "produce a validated review package. A source with no headings "
            "is refused (the wrapper invents no structure and never promotes "
            "body prose into a title). DOCX / PDF are a documented TODO (no "
            "safe local extractor). Local-only: no D-One, MCP, Qoder, public "
            "network, telemetry, model API, or image search. NOT real image "
            "generation; NOT full report understanding."
        ),
    )
    parser.add_argument(
        "--report",
        help=(
            "Path to a local UTF-8 .md or .txt report that already carries "
            "ATX '# ' headings (identifier-safe basename, not a symlink, not "
            "URI-shaped, not a repo generated-output artifact). The whole "
            "file is scanned for credential / public-network / file-URI / "
            "absolute-path wording and refused on any hit. A source with no "
            "headings, or a DOCX / PDF, is refused (DOCX / PDF are a TODO)."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--md-out",
        help=(
            "Convert only: write the derived Markdown to this path (must not "
            "exist, not a symlink, not URI-shaped, not under the repo tree; "
            "parent must exist). Requires --report."
        ),
    )
    mode.add_argument(
        "--mock-handoff",
        action="store_true",
        help=(
            "Convert the report to Markdown in a per-run tempdir and drive "
            "the existing source_to_image_requests.py --mock-handoff lane "
            "(plan + placeholder PNGs + operator bundle -> validated review "
            "package with an editable deck.pptx). Requires --report and "
            "--out-dir."
        ),
    )
    mode.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run every scenario under a per-run TMPDIR (md/txt verbatim "
            "passthrough, no-heading rejection, unsupported/TODO formats, "
            "URI/symlink/repo-generated rejection, unsafe wording, md-out "
            "under repo, full mock handoff, delegated out-dir gate). No "
            "caller-visible artifacts retained."
        ),
    )
    parser.add_argument(
        "--out-dir",
        help=(
            "Output directory outside the repo tree for --mock-handoff. "
            "Validation is delegated to source_to_image_requests.py (URI / "
            "symlink / symlink-ancestor / repo-tree / non-empty refusals)."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return _run_self_tests()

    if not args.report:
        print("FAIL: --report is required with --md-out / --mock-handoff", file=sys.stderr)
        return 2

    if args.md_out:
        return _run_convert_only(args.report, args.md_out)

    # --mock-handoff
    if not args.out_dir:
        print("FAIL: --mock-handoff requires --out-dir", file=sys.stderr)
        return 2
    return _run_mock_handoff(args.report, args.out_dir)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
