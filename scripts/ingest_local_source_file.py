#!/usr/bin/env python3
"""Local source-file -> Markdown ingestion bridge (MOCK / LOCAL only).

This is the smallest front door that lets an operator START from a local
report file instead of having to hand-prepare a Markdown file. It accepts
a local ``.md``, ``.txt``, or ``.docx`` source, normalises it into
Markdown with ATX (``# Title``) headings, and feeds the result into the
EXISTING ``source_to_image_requests.py`` bridge (its ``--mock-handoff``
lane) which parses one image request per heading and drives the operator
image-to-editable-PPT lane to a validated review package.

It does NOT invent document structure. ``source_to_image_requests.py``
already accepts any UTF-8 file and derives requests from its ATX
headings; this wrapper only adds a gated local-file front door in front
of that lane (extension allow-list, local DOCX heading-style extraction,
PDF TODO, repo-generated-artifact refusal, a convert-only ``--md-out``
mode). It stays inside the current first-stage scope (local/generated
images -> review package): it is a mock/local bridge that feeds the
EXISTING image lane, NOT report-to-deck automation and NOT report
understanding.

Markdown normalisation:

  For ``.md`` / ``.txt`` (``_to_markdown``): the source must ALREADY carry
  ATX (``# Title``) headings — a ``.md`` or a ``.txt`` that uses ``# ``
  markers. When it does, the text is passed through to the bridge
  VERBATIM. When it does not, the run fails CLOSED with guidance to add
  ``# `` headings.

  For ``.docx`` (``_docx_to_markdown``): the OOXML is read locally with
  stdlib zip/XML parsing; Word heading STYLES (Heading 1 / Heading 2 /
  ...) are the ONLY thing promoted to ATX ``# `` / ``## `` headings, and
  every other paragraph is preserved as body text. A body paragraph whose
  text merely starts with ``#`` or a ``` / ~~~ fence is backslash-escaped
  so it can never be re-parsed downstream as a heading (nor toggle the
  fence state that would skip a real styled heading). A ``.docx`` with no
  usable heading styles fails CLOSED. Only ``word/document.xml`` + the
  optional ``word/styles.xml`` are read, by name — nothing is extracted to
  disk.

  In neither path does the wrapper promote body lines to headings or
  guess structure out of prose, so no body text can ever become a deck
  title.

  EVERY format and BOTH modes hold the normalised Markdown to the SAME
  downstream safety contract: before ``--md-out`` writes anything (and
  before ``--mock-handoff`` runs the lane), the Markdown is staged in a
  tempdir and run through the bridge's own full plan gate. So convert-only
  ``--md-out`` can never write a file the ``--mock-handoff`` lane would
  refuse — the emitted-value scan on sanitised heading titles
  (``api*key`` -> ``apikey``, social-media / public-share wording, etc.)
  applies identically in both modes, and DOCX-extracted body text is
  scanned for credential / public-network wording exactly like ``.md``.

What this is NOT:

  * NOT real image generation. The downstream ``--mock-handoff`` writes
    tiny locally-synthesised placeholder PNGs; no D-One, model API, image
    search, MCP, Qoder, public network, or telemetry is ever called.
  * NOT full report understanding. It derives nothing from the report
    body and invents no structure: it requires operator-supplied ``# ``
    headings (or Word heading STYLES in a ``.docx``) and NEVER promotes
    body prose into the plan or the deck.
  * NOT a broad document converter. DOCX support is narrow: stdlib
    zip/XML extraction of heading styles + paragraph text only, no
    external dependency. PDF is NOT supported — the repo has no safe
    local extractor for it, so it is refused with an explicit TODO
    message rather than parsed with a fragile shim.
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
  * unsupported extension (only ``.md`` / ``.txt`` / ``.docx`` accepted;
    ``.pdf`` refused as TODO; everything else refused generically);
  * non-identifier-safe basename (mirrors the downstream bridge so the
    derived Markdown filename is safe);
  * empty / oversized bytes; non-UTF-8 (``.md`` / ``.txt``); non-OOXML /
    malformed zip, missing document part, or malformed XML (``.docx``);
  * a ``.docx`` with no usable Word heading styles;
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
import io  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import tempfile  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402
import zipfile  # noqa: E402
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

# Plain-text source extensions (case-insensitive): read + UTF-8 decoded
# and passed through verbatim (they must already carry ATX '# ' headings).
TEXT_EXTS: tuple[str, ...] = (".md", ".txt")
# The local OOXML format we can extract safely with stdlib zip/XML parsing:
# Word heading styles are promoted to ATX '# ' headings, normal paragraphs
# preserved as body text (see _docx_to_markdown).
DOCX_EXT: str = ".docx"
# All extensions the front door accepts.
ACCEPTED_EXTS: tuple[str, ...] = TEXT_EXTS + (DOCX_EXT,)
# Formats we explicitly know about but cannot safely extract locally yet.
# Refused with a TODO message rather than parsed with a fragile shim.
TODO_EXTS: tuple[str, ...] = (".pdf",)

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
# DOCX -> Markdown extraction (local OOXML, stdlib zip/XML only).
#
# A .docx is a ZIP of OOXML parts. We read ONLY two fixed members by name
# (word/document.xml + the optional word/styles.xml) — never extracting to
# disk and never iterating arbitrary entries — so a path-traversal-style
# zip entry name has nothing to write through. Word heading styles
# (Heading 1 / Heading 2 / ...) are promoted to ATX '# ' / '## ' headings;
# every other paragraph is preserved as body text. A .docx with no usable
# heading styles fails CLOSED: the wrapper invents no structure and never
# promotes body prose to a heading. The produced Markdown is then held to
# the SAME full downstream safety gate as .md / .txt (see _load_and_convert).
# ---------------------------------------------------------------------------

# WordprocessingML main namespace. Element tags below are Clark-notation
# ``{ns}local`` strings as produced by xml.etree.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DOCX_DOCUMENT_PART = "word/document.xml"
_DOCX_STYLES_PART = "word/styles.xml"
# A heading style name/id once whitespace-stripped + lowercased, e.g.
# "heading 1" -> "heading1", "Heading2" -> "heading2". Capture the level.
_HEADING_STYLE_RE = re.compile(r"^heading([1-9])$")


def _heading_level_from_style_token(token: str | None) -> int | None:
    """Map a style name OR styleId to a heading level 1..9, else None.
    Matches both 'heading 1' (style display name) and 'Heading1' (styleId)
    after whitespace strip + lowercase."""
    if not token:
        return None
    m = _HEADING_STYLE_RE.match(re.sub(r"\s+", "", token.lower()))
    return int(m.group(1)) if m else None


def _docx_style_heading_levels(styles_xml: bytes | None) -> dict[str, int]:
    """Map paragraph styleId -> heading level using word/styles.xml's
    ``<w:style><w:name w:val="heading N"/>``. Best-effort: a missing or
    malformed styles part yields an empty map and the styleId-token
    fallback in _docx_to_markdown still recognises 'Heading1'-style ids."""
    levels: dict[str, int] = {}
    if not styles_xml:
        return levels
    try:
        root = ET.fromstring(styles_xml)
    except ET.ParseError:
        return levels
    for style in root.iter(f"{_W}style"):
        # type defaults to paragraph when absent; only paragraph styles
        # can be a heading style.
        if style.get(f"{_W}type") not in (None, "paragraph"):
            continue
        style_id = style.get(f"{_W}styleId")
        if not style_id:
            continue
        name_el = style.find(f"{_W}name")
        if name_el is None:
            continue
        level = _heading_level_from_style_token(name_el.get(f"{_W}val"))
        if level is not None:
            levels[style_id] = level
    return levels


def _docx_paragraph_text(p: ET.Element) -> str:
    """Concatenate the visible text of a ``<w:p>`` in document order. Tabs
    and line breaks collapse to a single space; the result is stripped."""
    parts: list[str] = []
    for node in p.iter():
        tag = node.tag
        if tag == f"{_W}t":
            parts.append(node.text or "")
        elif tag in (f"{_W}tab", f"{_W}br", f"{_W}cr"):
            parts.append(" ")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


# A body paragraph whose collapsed text begins (after optional leading
# whitespace) with '#' or a ``` / ~~~ code fence would be re-parsed by the
# downstream heading parser as an ATX heading — or, for a fence, would
# toggle its fence state and make it SKIP real styled headings. Both turn
# body prose into deck structure. We detect and neutralise such lines.
_BODY_LEADING_MD_RE = re.compile(r"^[ \t]*(#|```|~~~)")


def _neutralise_body_line(text: str) -> str:
    """Keep a body paragraph from being parsed as a heading / fence by the
    downstream parser. The paragraph's whitespace is already collapsed to a
    single line, so a single backslash escape at the start is enough: it
    defeats both _ATX_RE and _FENCE_RE while leaving the visible text intact
    for the credential / public-network safety scan (the leading marker is
    never itself a denied token, and the rest of the line is unchanged)."""
    if _BODY_LEADING_MD_RE.match(text):
        return "\\" + text
    return text


def _docx_paragraph_level(p: ET.Element, style_levels: dict[str, int]) -> int | None:
    """Return the heading level for a ``<w:p>`` from its ``<w:pStyle>``,
    via the styles.xml name map first then the styleId-token fallback."""
    ppr = p.find(f"{_W}pPr")
    if ppr is None:
        return None
    pstyle = ppr.find(f"{_W}pStyle")
    if pstyle is None:
        return None
    val = pstyle.get(f"{_W}val")
    if val in style_levels:
        return style_levels[val]
    return _heading_level_from_style_token(val)


def _docx_to_markdown(path: Path) -> tuple[str | None, list[str]]:
    """Extract a .docx into Markdown, promoting Word heading styles to ATX
    '# ' headings and preserving other paragraphs as body text. Fails
    CLOSED on an unreadable/oversized file, a non-OOXML or malformed zip, a
    missing document part, malformed XML, or no usable heading styles."""
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
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            try:
                doc_info = zf.getinfo(_DOCX_DOCUMENT_PART)
            except KeyError:
                return None, [
                    f"--report {path} is not a DOCX: missing "
                    f"{_DOCX_DOCUMENT_PART} (not an OOXML Word document)"
                ]
            # Zip-bomb guard: refuse on the declared uncompressed size before
            # decompressing, holding the document part to the same byte cap.
            if doc_info.file_size > s2ir.MAX_SOURCE_BYTES:
                return None, [
                    f"--report {path} {_DOCX_DOCUMENT_PART} uncompressed size "
                    f"{doc_info.file_size} exceeds cap {s2ir.MAX_SOURCE_BYTES}; "
                    f"refused (zip-bomb guard)"
                ]
            document_xml = zf.read(_DOCX_DOCUMENT_PART)
            styles_xml: bytes | None = None
            try:
                styles_info = zf.getinfo(_DOCX_STYLES_PART)
                if styles_info.file_size <= s2ir.MAX_SOURCE_BYTES:
                    styles_xml = zf.read(_DOCX_STYLES_PART)
            except KeyError:
                styles_xml = None
    except (zipfile.BadZipFile, OSError) as exc:
        return None, [
            f"--report {path} is not a readable DOCX (OOXML zip): "
            f"{type(exc).__name__}: {exc}"
        ]

    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError as exc:
        return None, [
            f"--report {path} {_DOCX_DOCUMENT_PART} is not well-formed XML: {exc}"
        ]

    style_levels = _docx_style_heading_levels(styles_xml)
    blocks: list[str] = []
    heading_count = 0
    for p in root.iter(f"{_W}p"):
        text = _docx_paragraph_text(p)
        if not text:
            continue
        level = _docx_paragraph_level(p, style_levels)
        if level is not None:
            # ATX headings only run 1..6; deeper Word levels clamp to '######'.
            blocks.append(f"{'#' * min(level, 6)} {text}")
            heading_count += 1
        else:
            # Style-based promotion is the ONLY way a heading is created;
            # body prose that merely starts with '#'/a fence is neutralised
            # so it can never become a slide heading downstream.
            blocks.append(_neutralise_body_line(text))

    if heading_count == 0:
        return None, [
            f"--report {path} has no usable Word heading styles (Heading 1 / "
            f"Heading 2 / ...): nothing can be promoted to a Markdown '# ' "
            f"heading. The bridge derives one image request per heading and "
            f"invents no structure — apply Word heading styles in the .docx "
            f"(or convert it to .md / .txt with '# ' headings) and retry."
        ]
    return "\n\n".join(blocks) + "\n", []


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
    """Run the full gate -> read -> normalise -> downstream-gate pipeline.
    Returns (report_path, markdown_text, failures)."""
    path, suffix, failures = _gate_report(report_arg)
    if failures or path is None:
        return None, None, failures
    if suffix == DOCX_EXT:
        # DOCX is binary OOXML: extract + promote heading styles locally.
        markdown, failures = _docx_to_markdown(path)
        if failures or markdown is None:
            return None, None, failures
    else:
        # .md / .txt: read UTF-8 + require operator-supplied ATX headings.
        text, failures = _read_text(path)
        if failures or text is None:
            return None, None, failures
        markdown, failures = _to_markdown(text)
        if failures or markdown is None:
            return None, None, failures
    # Hold the normalised Markdown to the EXACT downstream safety contract
    # the --mock-handoff lane applies, so --md-out can never emit a file the
    # bridge would later refuse. Staging it under a tempdir (never the repo)
    # and running the bridge's own full plan gate enforces the source-safety
    # scan PLUS the emitted-value scan on sanitised heading titles (catching
    # sanitisation-assembly bypasses like 'api*key' -> 'apikey' and the
    # operator review-package gates — social-media / public-share / etc.),
    # heading caps, schema validation, and the per-deck-string operator
    # contract. Without this, convert-only --md-out would only run the raw
    # source scan and could write a heading the handoff lane rejects.
    stem = path.stem or "source"
    with tempfile.TemporaryDirectory(prefix="ingest-gate-") as raw_td:
        staged = Path(raw_td) / f"{stem}.md"
        staged.write_text(markdown, encoding="utf-8")
        _plan, failures = s2ir._plan_from_source(str(staged))
    if failures:
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


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _make_docx(
    paragraphs: list[tuple[str | None, str]],
    *,
    style_names: dict[str, str] | None = None,
    include_styles: bool = True,
    document_xml: str | None = None,
) -> bytes:
    """Synthesise a minimal valid .docx (OOXML zip) in memory for tests.

    ``paragraphs`` is a list of ``(style_id_or_None, text)``; a style id
    emits ``<w:pStyle w:val=...>``. ``style_names`` maps style id ->
    ``<w:name w:val>`` written into word/styles.xml (drives styles-name
    heading detection). ``document_xml`` overrides the body verbatim (for
    malformed-XML probes). Only the parts the reader uses plus a minimal
    OOXML skeleton are written."""
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    if document_xml is None:
        body = []
        for style_id, text in paragraphs:
            ppr = (
                f'<w:pPr><w:pStyle w:val="{_xml_escape(style_id)}"/></w:pPr>'
                if style_id is not None
                else ""
            )
            body.append(
                f"<w:p>{ppr}<w:r><w:t>{_xml_escape(text)}</w:t></w:r></w:p>"
            )
        document_xml = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{w}"><w:body>{"".join(body)}</w:body></w:document>'
        )
    style_names = style_names or {}
    style_defs = "".join(
        f'<w:style w:type="paragraph" w:styleId="{_xml_escape(sid)}">'
        f'<w:name w:val="{_xml_escape(name)}"/></w:style>'
        for sid, name in style_names.items()
    )
    styles_xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles xmlns:w="{w}">{style_defs}</w:styles>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr(_DOCX_DOCUMENT_PART, document_xml)
        if include_styles:
            zf.writestr(_DOCX_STYLES_PART, styles_xml)
    return buf.getvalue()


# A .docx with Word heading styles: 'Heading1'/'Heading2' detected by the
# styleId-token fallback, 'CustomHeadingTwo' detected via styles.xml name.
_DOCX_HEADING_PARAGRAPHS: list[tuple[str | None, str]] = [
    ("Heading1", "Quarterly Strategy Overview"),
    (None, "Some narrative body text describing the strategy."),
    ("CustomHeadingTwo", "Market Landscape"),
    (None, "Body paragraph about the market."),
    ("Heading2", "Closing Summary"),
    (None, "Final body paragraph."),
]
_DOCX_HEADING_STYLE_NAMES = {"CustomHeadingTwo": "heading 2"}


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

    # W4 unsupported / TODO extensions refused. (.docx is NOW accepted —
    # see W11..W16; malformed/non-docx .docx bytes are covered there.)
    for ext, label in ((".pdf", "pdf-todo"), (".rtf", "generic")):
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

    # W7b convert-only --md-out enforces the FULL downstream emitted-value
    # gate, not just the raw source scan. These headings pass
    # _scan_source_safety but are refused by the bridge's emitted-value /
    # operator contract — so a permissive --md-out would have written them.
    # Each must be refused with NO file written, proving --md-out is no
    # weaker than --mock-handoff.
    for label, body in (
        # Operator social-media gate (not in the raw deny-list).
        ("social-media-heading", "# Twitter rollout plan\n\nbody\n"),
        # Sanitisation-assembly bypass: raw 'api*key' carries no denied
        # substring, but the sanitised title 'apikey' is refused.
        ("sanitisation-bypass", "# api*key overview\n\nbody\n"),
    ):
        with tempfile.TemporaryDirectory(prefix=f"ilsf-W7b-{label}-") as raw_td:
            td = Path(raw_td)
            report = td / "report.md"
            report.write_text(body, encoding="utf-8")
            # Confirm the raw source scan alone would NOT have caught it,
            # so this genuinely exercises the downstream gate.
            raw_clean = not s2ir._scan_source_safety(body)
            md_out = td / "derived.md"
            rc = _run_convert_only(str(report), str(md_out))
            ok = raw_clean and rc == 1 and not md_out.exists()
            detail = "" if ok else f"raw_clean={raw_clean}; rc={rc}; md_out={md_out.exists()}"
            probes.append(_Probe(f"W7b md-out enforces downstream gate ({label})", ok, detail))

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

    # W11 .docx with Word heading styles -> --md-out: heading styles
    # promoted to ATX '# '/'## ', body paragraphs preserved, and NO body
    # line promoted to a heading (styleId fallback + styles.xml name map).
    with tempfile.TemporaryDirectory(prefix="ilsf-W11-") as raw_td:
        td = Path(raw_td)
        report = td / "report.docx"
        report.write_bytes(_make_docx(
            _DOCX_HEADING_PARAGRAPHS, style_names=_DOCX_HEADING_STYLE_NAMES,
        ))
        md_out = td / "derived.md"
        rc = _run_convert_only(str(report), str(md_out))
        ok = rc == 0 and md_out.is_file()
        detail = "" if ok else f"rc={rc}; md_out={md_out.is_file()}"
        if ok:
            got = md_out.read_text(encoding="utf-8")
            heads = s2ir._parse_headings(got)
            levels = [(h.level, h.text) for h in heads]
            if levels != [
                (1, "Quarterly Strategy Overview"),
                (2, "Market Landscape"),
                (2, "Closing Summary"),
            ]:
                ok, detail = False, f"unexpected headings: {levels!r}"
            elif "Some narrative body text describing the strategy." not in got:
                ok, detail = False, "body paragraph not preserved"
            elif "# Some narrative" in got:
                ok, detail = False, "body prose became a heading"
        probes.append(_Probe("W11 .docx heading styles -> ATX md-out", ok, detail))

    # W12 .docx with NO usable heading styles -> refused (no md written).
    with tempfile.TemporaryDirectory(prefix="ilsf-W12-") as raw_td:
        td = Path(raw_td)
        report = td / "report.docx"
        report.write_bytes(_make_docx([
            ("Normal", "A body paragraph describing the strategy."),
            (None, "Another body paragraph with no heading style."),
        ]))
        md_out = td / "derived.md"
        rc = _run_convert_only(str(report), str(md_out))
        ok = rc == 1 and not md_out.exists()
        probes.append(_Probe("W12 .docx no heading styles refused", ok, "" if ok else f"rc={rc}"))

    # W13 malformed zip with a .docx extension -> refused (no md written).
    with tempfile.TemporaryDirectory(prefix="ilsf-W13-") as raw_td:
        td = Path(raw_td)
        report = td / "report.docx"
        report.write_bytes(b"not a zip at all\n")
        md_out = td / "derived.md"
        rc = _run_convert_only(str(report), str(md_out))
        ok = rc == 1 and not md_out.exists()
        probes.append(_Probe("W13 malformed-zip .docx refused", ok, "" if ok else f"rc={rc}"))

    # W14 a valid zip that is NOT a Word doc (missing word/document.xml)
    # -> refused. Also covers an .docx whose document.xml is malformed XML.
    with tempfile.TemporaryDirectory(prefix="ilsf-W14-") as raw_td:
        td = Path(raw_td)
        non_doc = io.BytesIO()
        with zipfile.ZipFile(non_doc, "w") as zf:
            zf.writestr("hello.txt", "not a word document\n")
        report = td / "report.docx"
        report.write_bytes(non_doc.getvalue())
        md_out = td / "derived.md"
        rc = _run_convert_only(str(report), str(md_out))
        ok_missing = rc == 1 and not md_out.exists()

        report2 = td / "report2.docx"
        report2.write_bytes(_make_docx([], document_xml="<w:body><not well formed"))
        md_out2 = td / "derived2.md"
        rc2 = _run_convert_only(str(report2), str(md_out2))
        ok_malformed = rc2 == 1 and not md_out2.exists()
        ok = ok_missing and ok_malformed
        probes.append(_Probe("W14 non-docx zip / malformed XML refused", ok,
                             "" if ok else f"rc_missing={rc}; rc_malformed={rc2}"))

    # W15 .docx credential wording in a body paragraph -> refused by the
    # SAME downstream safety gate as .md/.txt (proves extracted body text
    # is scanned, not just headings).
    with tempfile.TemporaryDirectory(prefix="ilsf-W15-") as raw_td:
        td = Path(raw_td)
        report = td / "report.docx"
        report.write_bytes(_make_docx([
            ("Heading1", "Overview"),
            (None, "api_key = abc123 embedded in the body."),
        ]))
        md_out = td / "derived.md"
        rc = _run_convert_only(str(report), str(md_out))
        ok = rc == 1 and not md_out.exists()
        probes.append(_Probe("W15 .docx unsafe body wording refused", ok, "" if ok else f"rc={rc}"))

    # W16 full mock/local handoff from a heading-bearing .docx -> existing
    # bridge -> validated review package with an editable deck.pptx.
    with tempfile.TemporaryDirectory(prefix="ilsf-W16-") as raw_td:
        td = Path(raw_td)
        report = td / "report.docx"
        report.write_bytes(_make_docx(
            _DOCX_HEADING_PARAGRAPHS, style_names=_DOCX_HEADING_STYLE_NAMES,
        ))
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
        probes.append(_Probe("W16 .docx mock handoff -> review package", ok, detail))

    # W17 DOCX body prose that LOOKS like Markdown structure (a line
    # starting with '#', and a ``` code-fence line) must NEVER become a
    # heading, and the stray fence must not suppress real styled headings:
    # only the two heading-STYLED paragraphs may surface as headings.
    with tempfile.TemporaryDirectory(prefix="ilsf-W17-") as raw_td:
        td = Path(raw_td)
        report = td / "report.docx"
        report.write_bytes(_make_docx([
            ("Heading1", "Real Heading One"),
            (None, "# This looks like a heading but is body prose"),
            (None, "``` fenced-looking body line"),
            ("Heading2", "Real Heading Two"),
            (None, "Closing body paragraph."),
        ]))
        md_out = td / "derived.md"
        rc = _run_convert_only(str(report), str(md_out))
        ok = rc == 0 and md_out.is_file()
        detail = "" if ok else f"rc={rc}; md_out={md_out.is_file()}"
        if ok:
            got = md_out.read_text(encoding="utf-8")
            heads = [h.text for h in s2ir._parse_headings(got)]
            if heads != ["Real Heading One", "Real Heading Two"]:
                ok, detail = False, f"body prose leaked into headings: {heads!r}"
        probes.append(_Probe("W17 .docx body prose never becomes a heading", ok, detail))

    # W17b a neutralised body line still gets safety-scanned: a '#'-leading
    # body paragraph carrying credential wording is refused, proving the
    # escape preserves the text for the downstream scan.
    with tempfile.TemporaryDirectory(prefix="ilsf-W17b-") as raw_td:
        td = Path(raw_td)
        report = td / "report.docx"
        report.write_bytes(_make_docx([
            ("Heading1", "Overview"),
            (None, "# api_key = abc123 hidden behind a hash"),
        ]))
        md_out = td / "derived.md"
        rc = _run_convert_only(str(report), str(md_out))
        ok = rc == 1 and not md_out.exists()
        probes.append(_Probe("W17b neutralised body still safety-scanned", ok, "" if ok else f"rc={rc}"))

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
            "report that ALREADY carries ATX '# ' headings (passed through "
            "verbatim), or a local .docx whose Word heading styles (Heading "
            "1 / Heading 2 / ...) are extracted to ATX '# ' headings with "
            "stdlib zip/XML parsing, and feeds the result into the "
            "--mock-handoff lane to produce a validated review package. A "
            ".md/.txt with no headings, or a .docx with no usable heading "
            "styles, is refused (the wrapper invents no structure and never "
            "promotes body prose into a title). PDF is a documented TODO (no "
            "safe local extractor). Local-only: no D-One, MCP, Qoder, public "
            "network, telemetry, model API, or image search. NOT real image "
            "generation; NOT full report understanding."
        ),
    )
    parser.add_argument(
        "--report",
        help=(
            "Path to a local .md / .txt report that already carries ATX '# ' "
            "headings, or a local .docx with Word heading styles "
            "(identifier-safe basename, not a symlink, not URI-shaped, not a "
            "repo generated-output artifact). The derived Markdown is scanned "
            "for credential / public-network / file-URI / absolute-path "
            "wording and refused on any hit. A .md/.txt with no headings, a "
            ".docx with no usable heading styles, or a .pdf is refused (.pdf "
            "is a documented TODO)."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--md-out",
        help=(
            "Convert only: write the derived Markdown to this path (must not "
            "exist, not a symlink, not URI-shaped, not under the repo tree; "
            "parent must exist). The Markdown is held to the SAME full "
            "downstream safety gate as --mock-handoff before it is written, "
            "so it can never emit a file the handoff lane would refuse. "
            "Requires --report."
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
            "passthrough, docx heading-style extraction, docx no-heading / "
            "malformed-zip / non-docx rejection, no-heading rejection, "
            "unsupported/TODO formats, URI/symlink/repo-generated rejection, "
            "unsafe wording, md-out enforcing the full downstream "
            "emitted-value gate, md-out under repo, full mock handoff "
            "including a docx handoff, delegated out-dir gate). No "
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
