#!/usr/bin/env python3
"""validate_pptx_contract.py

Stdlib-only **contract / skeleton** validator for the editable-ppt
pipeline's PPTX output stage. The PPTX exporter (`scripts/export_pptx.py`)
now produces an expanded native editable subset — the `cover`,
`kpi_dashboard`, `agenda`, `section_divider`, `executive_summary`,
`key_message`, `two_column`, `timeline`, `conclusion`, and
`comparison_table` layouts; primitives `text` / `line` / `shape` /
`image_slot` / `kpi` / `table` (the `table` primitive emits a native
`<p:graphicFrame>` wrapping `<a:tbl>` with editable `<a:tc>` cells) —
and this validator gates that output with both the original container
checks and a set of MINIMAL-EVIDENCE checks (see below), including a
relationship `Type` allow-list and the embedded-media gates
`media.targets_internal`, `media.inventory`, and `media.embedded_only`
(the per-`<a:blip>` "no remote link" check that walks every content
XML part under `ppt/` and refuses any `<a:blip r:link="…"/>` element).
The `chart_placeholder` primitive, full editability inventory, theme
palette mapping, determinism, and layout/primitive-scope inspection
of the produced PPTX all remain TODO and are explicitly named that
way in every run.

USAGE
    # Skeleton mode (no .pptx supplied). Reports the contract /
    # TODO surface only; does not fabricate or open any file.
    python3 scripts/validate_pptx_contract.py

    # Container + minimal-evidence mode. Runs the basic OOXML
    # container checks against a real .pptx, plus the minimal-evidence
    # checks listed below.
    python3 scripts/validate_pptx_contract.py --pptx path/to/deck.pptx

    # Self-test. Exercises every fail-closed gate against tempfixture
    # negatives plus a minimal-valid-container positive and a
    # minimal-editable-PPTX positive.
    python3 scripts/validate_pptx_contract.py --self-test

CHECKS TODAY (all fail-closed; exit 1 on any failure)
    container.exists      — the supplied --pptx path exists on disk.
    container.extension   — extension is '.pptx' (case-insensitive).
    container.zip         — the file opens as a readable ZIP container.
    container.parts       — the ZIP contains the basic OOXML entries:
                            '[Content_Types].xml',
                            '_rels/.rels',
                            and at least one 'ppt/presentation.xml'.
    slide_count.inspectable
                          — informational PASS that reports how many
                            ppt/slides/slide{N}.xml parts exist. A run
                            with zero slide parts is a FAIL (the
                            exporter requires at least one exported
                            slide).
    slide_count.expected  — caller-driven gate. When --expected-slide-
                            count N is passed, the validator fails
                            closed if the number of slide parts is not
                            exactly N. Optional; only active when the
                            flag is supplied.
    relationships.no_external
                          — no Relationship element has
                            TargetMode="External", and no Target
                            value carries a URI scheme prefix
                            (^[A-Za-z][A-Za-z0-9+.-]*:).
    relationships.no_file_uri
                          — no Relationship Target begins with
                            'file://'. (Subset of the above, but
                            called out separately so a file:// regression
                            is unmistakable in the report.)
    relationships.allow_list
                          — every Relationship Type is one of the six
                            URLs the minimal exporter is allowed to
                            emit today: officeDocument, slide,
                            slideMaster, slideLayout, theme, image
                            (the `image` URL covers per-slide
                            embedded-media relationships). An
                            unexpected Type (hyperlink, comments,
                            chart, embedding, ...) fails the gate.
    media.targets_internal
                          — every `image`-typed Relationship Target is
                            an internal package path under
                            `ppt/media/`, not an external URL or
                            `file://` reference. (Subset of
                            relationships.no_external + .no_file_uri,
                            but called out separately so a media-only
                            regression is unmistakable in the report.)
    media.inventory       — every `image`-typed Relationship Target
                            resolves to an actual `ppt/media/<name>`
                            part inside the ZIP, no dangling refs;
                            every `ppt/media/` part is referenced by
                            at least one `image` relationship (no
                            orphan media files); each part's extension
                            is in the {png, jpg, jpeg} embed allow-list
                            and matches a `<Default Extension="..."/>`
                            entry whose ContentType is one of
                            {image/png, image/jpeg}.
    media.embedded_only   — no `<a:blip>` element anywhere in the
                            package's content XML carries an
                            `r:link="..."` attribute. Scope is every
                            `*.xml` part under `ppt/` that is not a
                            `_rels/` file (slides, slideMasters,
                            slideLayouts, theme, presentation). The
                            `r:link` form is OOXML's external-linked
                            image reference; the exporter only emits
                            `r:embed`. This is the deeper guarantee
                            that complements relationships.no_external
                            + relationships.allow_list +
                            media.targets_internal on the rels side.
                            Read + parse handling is fail-closed:
                            ANY exception during `ZipFile.read()` or
                            `ET.fromstring()` against an in-scope
                            part is itself reported as an offender —
                            including `zipfile.BadZipFile` (CRC
                            mismatch; base is `Exception`, NOT
                            `OSError`) and `RuntimeError` (archive-
                            internal failures) — so a corrupted or
                            malformed XML part cannot silently bypass
                            the gate. The exception type name is
                            included in the offender string for
                            debuggability.
    package.no_macros     — no vbaProject.bin part; no
                            'vbaProject' content type override.
    package.no_ole        — no part under ppt/embeddings/ and no
                            'oleObject' content type override.
    package.no_activex    — no part under ppt/activeX/ and no
                            'activeX' content type override.
    minimal_evidence.editable_text
                          — at least one slide carries a <p:txBody>
                            with a non-empty <a:t> run. Minimal
                            evidence only: this does NOT prove every
                            text on every slide is editable.
    minimal_evidence.not_all_image_slide
                          — every slide that carries a <p:pic> also
                            carries at least one <p:sp> or <p:cxnSp>.
                            Minimal evidence only: this rules out the
                            obvious "one big PNG" failure mode but
                            does not enforce a full editability
                            inventory. (Paired with no_blank_slide
                            below — the two together close the loophole
                            where a slide carries zero native shapes
                            AND zero pictures.)
    minimal_evidence.no_blank_slide
                          — every slide carries at least one
                            structural element (<p:sp>, <p:cxnSp>, or
                            <p:pic>); a slide whose spTree is
                            literally empty fails closed. Minimal
                            evidence only: this rules out a deck where
                            slide 1 has editable text but slide 2 is
                            empty (which would otherwise satisfy
                            editable_text and not_all_image_slide
                            individually).
    minimal_evidence.every_slide_has_native_shape
                          — every slide carries at least one native
                            editable structure (<p:sp> or <p:cxnSp>).
                            This is the single positive statement of
                            "every slide has at least one native
                            editable structure"; the combination of
                            not_all_image_slide + no_blank_slide
                            already covers the same surface as failure-
                            mode disambiguation, but this gate spells
                            the contract out as one explicit positive
                            check so a regression is unmistakable.
                            Still minimal evidence — it counts
                            structures, not per-shape editability.

TODO (explicitly NOT implemented; reported as TODO every run)
    editability.full_inventory — every text frame on every slide is
        a real text frame (no outlined-to-path text, no
        rasterized-shape art). The minimal_evidence.editable_text
        check above is a positive-existence proof on one slide; a
        full inventory needs per-shape introspection.
    no_image_only_slides.full_inventory — every slide has been
        positively confirmed to contain at least one editable shape.
        The minimal_evidence.not_all_image_slide +
        minimal_evidence.every_slide_has_native_shape pair rules out
        the obvious failure modes; a full per-shape inventory still
        needs per-shape introspection.
    theme.palette_mapping — design_system palette resolves to the
        matching PPTX theme slots.
    determinism — stable IDs, relationship order, and media filenames
        across runs.
    layouts.scope — exported slides use only the expanded
        SUPPORTED_LAYOUTS allow-list in scripts/export_pptx.py (the
        exporter enforces this today; this validator does not yet
        read the layout slot back out of the PPTX).
    primitives.scope — exported shapes map only to the supported six
        primitive kinds (text, line, shape, image_slot, kpi, table; the
        exporter enforces this today; this validator does not yet
        inspect every shape's mapped primitive).

OUT OF SCOPE FOR THIS SCRIPT
    Generating PPTX (that is `scripts/export_pptx.py`). Full
    editability inventory, theme palette mapping, determinism
    inventory, and layout/primitive-scope inspection of the produced
    PPTX. Any network behavior. (The relationship `Type` allow-list
    is now in scope as relationships.allow_list, and embedded-media
    inventory, targets-internal, and the per-`<a:blip>` "no remote
    link" gates are implemented as media.inventory,
    media.targets_internal, and media.embedded_only — see the CHECKS
    TODAY block above.)

EXIT
    0  every executed check passed and all skeleton/TODO entries were
       reported (skeleton mode also exits 0 — the run is informational,
       not a claim of export readiness).
    1  any executed check failed.
    2  invocation error (e.g. unreadable --pptx argument shape).
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

# Basic OOXML / PresentationML package entries that any valid PPTX
# must carry. The deeper full-inventory native-object inspection is
# still TODO (see references/pptx-conversion-rules.md). Keep this list
# narrow — it is the minimum container shape, not the full contract.
REQUIRED_OOXML_PARTS: tuple[str, ...] = (
    "[Content_Types].xml",
    "_rels/.rels",
    "ppt/presentation.xml",
)

# RFC 3986 scheme prefix: ALPHA *( ALPHA / DIGIT / "+" / "-" / "." ) ":"
# Mirrors validate_scaffold._URI_SCHEME_PREFIX. Re-implemented locally so
# this contract validator stays stdlib-only and free of cross-script
# imports.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Relationship XML namespace.
_NS_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_NS_DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS_PRES = "http://schemas.openxmlformats.org/presentationml/2006/main"
# DrawingML `r:` prefix — used by `<a:blip r:embed="..."/>` (embedded,
# allowed) and `<a:blip r:link="..."/>` (external linked image, BANNED).
# Different from `_NS_RELS` (which is the package-level rels namespace).
_NS_OFFICE_RELS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)

# Forbidden / risky package shapes, as a tuple of
# (label, prefix_path, content_type_substring). A part whose name
# starts with prefix_path OR whose registered content type contains
# content_type_substring trips the matching gate.
_FORBIDDEN_PARTS: tuple[tuple[str, str, str], ...] = (
    ("package.no_macros",   "ppt/vbaProject",     "vbaProject"),
    ("package.no_ole",      "ppt/embeddings/",    "oleObject"),
    ("package.no_activex",  "ppt/activeX/",       "activeX"),
)

# Relationship type URLs the minimal exporter is allowed to emit
# today. Anything outside this allow-list fails relationships.allow_list.
# The set is intentionally narrow: it covers exactly the relationships
# scripts/export_pptx.py emits (officeDocument under the root, slide /
# slideMaster / theme under presentation, slideLayout / theme under
# slideMaster, slideMaster under slideLayout, slideLayout under each
# slide, and `image` per slide for every embedded PNG / JPG / JPEG
# asset). Widening the exporter beyond these must also widen this set.
_ALLOWED_RELATIONSHIP_TYPES: frozenset[str] = frozenset({
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
})

# Embedded-media relationship type URL — separately bound for the
# media.* gates below.
_REL_TYPE_IMAGE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)

# Allowed embedded-media file extensions (lower-cased, no leading dot).
# A media relationship pointing at an extension outside this set fails
# the media inventory gate. Today the exporter only embeds these.
_ALLOWED_MEDIA_EXTENSIONS: frozenset[str] = frozenset({"png", "jpg", "jpeg"})

# Pretty-printed TODO surface. Reported every run so callers cannot
# mistake a passing container check for a passing export contract.
# The entries narrow as the validator grows: items the validator now
# at least covers as MINIMAL EVIDENCE are still listed so the gap
# between "this check exists" and "this check is comprehensive" stays
# visible.
TODO_CHECKS: tuple[tuple[str, str], ...] = (
    ("editability.full_inventory",
     "every text body on every slide is a real text frame; "
     "minimal_evidence.editable_text is a positive-existence check only"),
    ("no_image_only_slides.full_inventory",
     "every slide is positively confirmed to contain editable shapes; "
     "minimal_evidence.not_all_image_slide + minimal_evidence.no_blank_slide "
     "+ minimal_evidence.every_slide_has_native_shape rule out the "
     "all-image and blank-slide failure modes only"),
    ("theme.palette_mapping",
     "design_system palette resolves to the matching PPTX theme slots"),
    ("determinism",
     "stable IDs, relationship order, and media filenames across runs"),
    ("layouts.scope",
     "validate that exported slides use only layouts on the "
     "scripts/export_pptx.py SUPPORTED_LAYOUTS allow-list (the "
     "exporter enforces this; the validator does not yet read layout "
     "slot info back out of the PPTX)"),
    ("primitives.scope",
     "validate that exported shapes map only to the supported six "
     "primitive kinds — text, line, shape, image_slot, kpi, table "
     "(the exporter enforces this; the validator does not yet inspect "
     "every shape's primitive mapping)"),
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def _has_pptx_extension(pptx_path: Path) -> bool:
    return pptx_path.suffix.lower() == ".pptx"


def check_container(pptx_path: Path) -> list[CheckResult]:
    """Run the four basic OOXML container checks against a real path.

    Fail-closed: every helper that could touch the filesystem against
    an unsafe / non-PPTX target short-circuits to a [FAIL] line
    instead of attempting deeper inspection."""
    out: list[CheckResult] = []

    exists = pptx_path.is_file()
    out.append(CheckResult(
        f"container.exists: {pptx_path}",
        exists,
        "" if exists else f"no file at {pptx_path}",
    ))
    if not exists:
        return out

    ext_ok = _has_pptx_extension(pptx_path)
    out.append(CheckResult(
        f"container.extension: {pptx_path.name}",
        ext_ok,
        "" if ext_ok else f"extension is {pptx_path.suffix!r}, expected '.pptx'",
    ))
    if not ext_ok:
        # Fail-closed: do not try to open a non-pptx file as a ZIP.
        return out

    try:
        zf = zipfile.ZipFile(pptx_path, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        out.append(CheckResult(
            f"container.zip: {pptx_path.name}",
            False,
            f"not a readable ZIP container: {exc}",
        ))
        return out

    try:
        names = set(zf.namelist())
    finally:
        zf.close()
    out.append(CheckResult(
        f"container.zip: {pptx_path.name}",
        True,
    ))

    missing = [p for p in REQUIRED_OOXML_PARTS if p not in names]
    out.append(CheckResult(
        f"container.parts: {pptx_path.name} carries required OOXML entries "
        f"({', '.join(REQUIRED_OOXML_PARTS)})",
        not missing,
        f"missing entries: {missing}" if missing else "",
    ))
    return out


def _iter_slide_parts(names: set[str]) -> list[str]:
    """Return ppt/slides/slide{N}.xml entries (NOT their rels) in
    sorted order. The exporter writes slides as slide1.xml..slideN.xml;
    we trust the file naming rather than parsing presentation.xml so the
    check works against any conforming OOXML PPTX."""
    out: list[str] = []
    for n in names:
        if not n.startswith("ppt/slides/slide"):
            continue
        if "_rels" in n:
            continue
        if not n.endswith(".xml"):
            continue
        out.append(n)
    out.sort()
    return out


def _iter_rels_parts(names: set[str]) -> list[str]:
    """Return every *.rels member name. Each one is the relationships
    file for some part of the package."""
    return sorted(n for n in names if n.endswith(".rels"))


def _content_type_overrides(names: set[str], zf: zipfile.ZipFile) -> list[str]:
    """Read [Content_Types].xml and return the list of declared
    ContentType strings (both Default and Override). Returns an empty
    list if the file is missing or unparseable — the caller treats that
    as 'no overrides declared' and the package.no_* checks still inspect
    member names directly."""
    if "[Content_Types].xml" not in names:
        return []
    try:
        text = zf.read("[Content_Types].xml")
        root = ET.fromstring(text)
    except (ET.ParseError, KeyError, OSError):
        return []
    cts: list[str] = []
    for el in root:
        ct = el.attrib.get("ContentType")
        if isinstance(ct, str):
            cts.append(ct)
    return cts


def _content_type_defaults(
    names: set[str], zf: zipfile.ZipFile,
) -> dict[str, str]:
    """Read [Content_Types].xml and return {extension_lower: ContentType}
    for every `<Default>` entry. Used by the media.inventory gate to
    confirm each shipped extension is registered with the expected
    ContentType. Empty dict if the file is missing or unparseable."""
    if "[Content_Types].xml" not in names:
        return {}
    try:
        text = zf.read("[Content_Types].xml")
        root = ET.fromstring(text)
    except (ET.ParseError, KeyError, OSError):
        return {}
    out: dict[str, str] = {}
    default_tag = f"{{{_NS_CT}}}Default"
    for el in root:
        if el.tag != default_tag:
            continue
        ext = el.attrib.get("Extension")
        ct = el.attrib.get("ContentType")
        if isinstance(ext, str) and isinstance(ct, str):
            out[ext.lower()] = ct
    return out


def _posix_resolve(base_dir: str, relative: str) -> str | None:
    """Resolve a POSIX `relative` reference against `base_dir`.

    `base_dir` is a forward-slash path (e.g. `ppt/slides`); a
    `relative` like `../media/image1.png` resolves to
    `ppt/media/image1.png`. Returns None if the resolution would
    escape the package root (a leading `/` or too many `..`).

    Used by the media.inventory gate to confirm an `image`-typed
    relationship Target lands at an on-disk part of the package."""
    if relative.startswith("/"):
        return None
    parts: list[str] = []
    if base_dir:
        parts.extend(p for p in base_dir.split("/") if p)
    for seg in relative.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


def _rels_part_owner_dir(rels_part: str) -> str:
    """Return the directory of the OOXML part that the `.rels` file
    describes. OOXML relationship Targets are resolved against the
    PART, not against the `.rels` file itself.

    Conventions:
      - `_rels/.rels`                              -> package root, ""
      - `ppt/_rels/presentation.xml.rels`          -> `ppt`
      - `ppt/slides/_rels/slide1.xml.rels`         -> `ppt/slides`

    The general rule: drop the trailing `_rels/<name>.rels` segments
    and return the parent directory of the owning part."""
    segs = rels_part.split("/")
    if "_rels" not in segs:
        # Defensive: not actually a rels file — treat its directory as
        # the owner so the caller still gets a sensible path.
        return rels_part.rsplit("/", 1)[0] if "/" in rels_part else ""
    rels_index = segs.index("_rels")
    # The owner part lives in segs[:rels_index] + the trailing
    # `<name>.rels` becomes `<name>` (e.g. `slide1.xml`); the owner
    # directory is the parent of that part.
    return "/".join(segs[:rels_index])


def _all_relationships(names: list[str], zf: zipfile.ZipFile) -> list[tuple[str, dict]]:
    """Return [(rels_part_name, attrib_dict_for_each_relationship), ...]
    so the relationships.* gates can report which file tripped the
    fail-closed rule."""
    out: list[tuple[str, dict]] = []
    for part in names:
        try:
            text = zf.read(part)
            root = ET.fromstring(text)
        except (ET.ParseError, KeyError, OSError):
            continue
        if root.tag != f"{{{_NS_RELS}}}Relationships":
            continue
        for child in root:
            if child.tag != f"{{{_NS_RELS}}}Relationship":
                continue
            out.append((part, dict(child.attrib)))
    return out


def _iter_ppt_xml_parts(names: set[str]) -> list[str]:
    """Return every `*.xml` part under `ppt/` that is NOT a relationships
    file. Used by the media.embedded_only gate to scan every part that
    could legitimately carry an `<a:blip>` element (slides, slide
    masters, slide layouts, theme, presentation). The `_rels/` files
    are intentionally skipped — they hold `<Relationship>` elements,
    not DrawingML, and the relationships.* gates already inspect
    them."""
    out: list[str] = []
    for n in names:
        if not n.startswith("ppt/"):
            continue
        if not n.endswith(".xml"):
            continue
        if "_rels/" in n:
            continue
        out.append(n)
    out.sort()
    return out


def _blip_link_offenders(
    zf: zipfile.ZipFile, parts: list[str],
) -> list[str]:
    """Return one offender string per `<a:blip>` element whose `r:link`
    attribute is set, across the supplied list of XML parts.

    The OOXML DrawingML `<a:blip>` element carries either `r:embed`
    (the rId of an EMBEDDED media part — the only form the exporter
    emits today) or `r:link` (the rId of a LINKED relationship — the
    form whose Target can legally be a remote URL, `file://` path, or
    any other reference outside the package). A blip MAY carry both;
    the presence of `r:link` is what makes the slide a remote-image
    consumer at open time, regardless of whether `r:embed` is also
    present.

    The `relationships.no_external` + `relationships.no_file_uri` +
    `relationships.allow_list` + `media.targets_internal` gates already
    catch most of the "external media" failure surface from the rels
    side; this helper closes the deeper guarantee from the BLIP side:
    even if the rels file were tampered with to point an `image` rel
    at an internal Target, a slide that USES that rel through
    `r:link` is asking PowerPoint to treat the part as a linked image
    instead of an embedded one. The contract is no `r:link` anywhere
    in the package's content XML.

    Fail-closed read + parse handling: an XML part that the caller
    listed in `parts` but that cannot be READ or PARSED is recorded
    as its own offender — the gate cannot rule out a buried
    `<a:blip r:link/>` in malformed XML or in a corrupted ZIP entry
    and must not silently pass. Both except clauses are deliberately
    broad (`except Exception`) so the security-relevant set is
    closed: `zipfile.BadZipFile` is raised on CRC mismatch and is
    NOT an `OSError` subclass in Python 3, `RuntimeError` is raised
    by `ZipFile.read()` on certain archive-internal failures, and
    `zlib.error` may surface from deflate decoding — none of which
    are caught by a narrow `(KeyError, OSError)` tuple. The other
    minimal-evidence gates already react to malformed slide XML (a
    slide whose XML fails to parse counts as zero shapes for the
    every_slide_has_native_shape / editable_text gates), but they do
    not run against slideMasters / slideLayouts / theme / presentation,
    so a fail-open `continue` here would have hidden a linked blip in
    those parts entirely. The exception TYPE NAME is included in the
    offender string so a malformed-package regression is debuggable
    from the validator output alone."""
    out: list[str] = []
    blip_tag = f"{{{_NS_DRAWING}}}blip"
    link_attr = f"{{{_NS_OFFICE_RELS}}}link"
    for part in parts:
        try:
            text = zf.read(part)
        except Exception as exc:
            out.append(
                f"{part}: unreadable XML part — cannot rule out "
                f"<a:blip r:link/> "
                f"({type(exc).__name__}: {exc})"
            )
            continue
        try:
            root = ET.fromstring(text)
        except Exception as exc:
            out.append(
                f"{part}: unparseable XML — cannot rule out "
                f"<a:blip r:link/> "
                f"({type(exc).__name__}: {exc})"
            )
            continue
        for blip in root.iter(blip_tag):
            link_val = blip.attrib.get(link_attr)
            if link_val is None:
                continue
            out.append(f"{part}: <a:blip r:link={link_val!r}/>")
    return out


def _slide_shape_counts(zf: zipfile.ZipFile, slide_part: str) -> tuple[int, int, int, int]:
    """Return (n_sp, n_cxnSp, n_txBody_with_text, n_pic) for a slide
    part. We use ElementTree iter() so the count is namespace-aware.
    n_txBody_with_text counts only <p:txBody> elements that contain at
    least one non-empty <a:t> run, so an empty placeholder textbox
    does not satisfy editable_text on its own."""
    try:
        text = zf.read(slide_part)
        root = ET.fromstring(text)
    except (ET.ParseError, KeyError, OSError):
        return (0, 0, 0, 0)
    sp_tag = f"{{{_NS_PRES}}}sp"
    cxn_tag = f"{{{_NS_PRES}}}cxnSp"
    pic_tag = f"{{{_NS_PRES}}}pic"
    txbody_tag = f"{{{_NS_PRES}}}txBody"
    t_tag = f"{{{_NS_DRAWING}}}t"
    n_sp = sum(1 for _ in root.iter(sp_tag))
    n_cxn = sum(1 for _ in root.iter(cxn_tag))
    n_pic = sum(1 for _ in root.iter(pic_tag))
    n_tx = 0
    for tb in root.iter(txbody_tag):
        for t in tb.iter(t_tag):
            if isinstance(t.text, str) and t.text:
                n_tx += 1
                break
    return (n_sp, n_cxn, n_tx, n_pic)


def check_generated_pptx(
    pptx_path: Path,
    expected_slide_count: int | None = None,
) -> list[CheckResult]:
    """Run the minimal-evidence + safety checks against a generated
    PPTX. Returns one CheckResult per gate. Every gate here is in
    addition to (not a replacement for) check_container.

    When `expected_slide_count` is supplied, an additional fail-closed
    `slide_count.expected` gate compares the number of
    `ppt/slides/slide{N}.xml` parts against the caller's claim. This
    is what makes a 19-slide PPTX claiming "20 slides" fail at the
    validator level even though the container looks well-formed.

    Every check is fail-closed: a check that cannot read its target
    returns FAIL with the read reason. The function is itself
    defensive — it does NOT raise on a malformed PPTX, so the caller
    can aggregate failures without a traceback."""
    out: list[CheckResult] = []
    try:
        zf = zipfile.ZipFile(pptx_path, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        # check_container would have already failed on this path; we
        # report a FAIL here for symmetry rather than silently skip.
        out.append(CheckResult(
            f"generated.zip_readable: {pptx_path.name}",
            False,
            f"not a readable ZIP container: {exc}",
        ))
        return out
    try:
        names_set = set(zf.namelist())
        names_list = sorted(names_set)

        # 1. slide_count.inspectable
        slide_parts = _iter_slide_parts(names_set)
        ok_count = len(slide_parts) > 0
        out.append(CheckResult(
            f"slide_count.inspectable: {pptx_path.name}",
            ok_count,
            (f"counted {len(slide_parts)} slide part(s): "
             f"{', '.join(slide_parts) if slide_parts else '(none)'}"),
        ))

        # 1b. slide_count.expected (optional, caller-driven)
        # A caller that knows how many slides the deck SHOULD have can
        # ask the validator to fail closed on a mismatch. This is the
        # validator-side complement to the deck_plan/render_models 1:1
        # coverage gate in scripts/export_pptx.py: it catches the case
        # where a 20-slide deck_plan exports as a 19-slide `.pptx` and
        # the container shape looks otherwise correct.
        if expected_slide_count is not None:
            actual = len(slide_parts)
            out.append(CheckResult(
                f"slide_count.expected: {pptx_path.name}",
                actual == expected_slide_count,
                (f"expected {expected_slide_count} slide(s), "
                 f"found {actual}"),
            ))

        # 2 + 3 + 4. relationships.no_external +
        # relationships.no_file_uri + relationships.allow_list.
        # All three iterate every <Relationship> element in every
        # *.rels member, but each gate is reported separately so a
        # caller can see which contract dimension a fixture trips.
        # (A relationship with an external https:// Target and an
        # unknown Type trips both relationships.no_external AND
        # relationships.allow_list — that is the intended overlap.)
        rels_parts = _iter_rels_parts(names_set)
        rels = _all_relationships(rels_parts, zf)
        external_offenders: list[str] = []
        file_uri_offenders: list[str] = []
        allow_list_offenders: list[str] = []
        for part, attrs in rels:
            target = attrs.get("Target", "")
            target_mode = attrs.get("TargetMode", "")
            rtype = attrs.get("Type", "")
            if target_mode and target_mode.lower() == "external":
                external_offenders.append(f"{part}: {attrs}")
            if isinstance(target, str) and _URI_SCHEME_PREFIX.match(target):
                external_offenders.append(f"{part}: Target={target!r}")
            if isinstance(target, str) and target.lower().startswith("file://"):
                file_uri_offenders.append(f"{part}: Target={target!r}")
            if not isinstance(rtype, str) or rtype not in _ALLOWED_RELATIONSHIP_TYPES:
                allow_list_offenders.append(f"{part}: Type={rtype!r}")
        out.append(CheckResult(
            f"relationships.no_external: {pptx_path.name}",
            not external_offenders,
            ("; ".join(external_offenders) if external_offenders else ""),
        ))
        out.append(CheckResult(
            f"relationships.no_file_uri: {pptx_path.name}",
            not file_uri_offenders,
            ("; ".join(file_uri_offenders) if file_uri_offenders else ""),
        ))
        out.append(CheckResult(
            f"relationships.allow_list: {pptx_path.name}",
            not allow_list_offenders,
            ("; ".join(allow_list_offenders) if allow_list_offenders else ""),
        ))

        # 4b. media.targets_internal + media.inventory.
        # Both gates iterate the `image`-typed relationships. The
        # `targets_internal` gate is a media-only restatement of
        # `relationships.no_external` + `relationships.no_file_uri` so
        # a media regression is unmistakable in the report (an image
        # rel pointing at https://attacker/x.png trips both
        # `no_external` AND `media.targets_internal`). The
        # `inventory` gate goes further: it confirms every image
        # rel's Target resolves to an actual `ppt/media/...` ZIP
        # entry, every `ppt/media/<name>` part is referenced by at
        # least one image rel (no orphan media bytes), each part's
        # extension is in the embed allow-list, and there is a
        # matching `<Default Extension="..."/>` for each extension we
        # ship.
        image_rels: list[tuple[str, str]] = []  # (rels_part, target)
        media_target_offenders: list[str] = []
        for part, attrs in rels:
            rtype = attrs.get("Type", "")
            target = attrs.get("Target", "")
            if rtype != _REL_TYPE_IMAGE:
                continue
            if not isinstance(target, str) or not target:
                media_target_offenders.append(
                    f"{part}: image rel missing Target"
                )
                continue
            target_mode = attrs.get("TargetMode", "")
            if target_mode and target_mode.lower() == "external":
                media_target_offenders.append(
                    f"{part}: image rel has TargetMode={target_mode!r}"
                )
                continue
            if _URI_SCHEME_PREFIX.match(target):
                media_target_offenders.append(
                    f"{part}: image rel Target={target!r} carries a URI scheme"
                )
                continue
            if target.lower().startswith("file://"):
                media_target_offenders.append(
                    f"{part}: image rel Target={target!r} is a file:// reference"
                )
                continue
            image_rels.append((part, target))
        out.append(CheckResult(
            f"media.targets_internal: {pptx_path.name}",
            not media_target_offenders,
            ("; ".join(media_target_offenders)
             if media_target_offenders else ""),
        ))

        # Resolve each image rel Target against the OWNER PART's
        # directory (NOT the .rels file's directory). The OOXML
        # convention is that a relationship Target is relative to the
        # part it relates: a slide rels file at
        # `ppt/slides/_rels/slide1.xml.rels` describes `ppt/slides/slide1.xml`,
        # so a Target like `../media/image1.png` resolves to
        # `ppt/media/image1.png` (one `..` out of `ppt/slides/` lands in
        # `ppt/`, then `media/image1.png`).
        media_inventory_offenders: list[str] = []
        referenced_media_parts: set[str] = set()
        for part, target in image_rels:
            owner_dir = _rels_part_owner_dir(part)
            resolved = _posix_resolve(owner_dir, target)
            if resolved is None:
                media_inventory_offenders.append(
                    f"{part}: image rel Target={target!r} escapes the package"
                )
                continue
            if not resolved.startswith("ppt/media/"):
                media_inventory_offenders.append(
                    f"{part}: image rel Target={target!r} resolves to "
                    f"{resolved!r} (must live under ppt/media/)"
                )
                continue
            if resolved not in names_set:
                media_inventory_offenders.append(
                    f"{part}: image rel Target={target!r} resolves to "
                    f"{resolved!r} which is missing from the package"
                )
                continue
            ext = resolved.rsplit(".", 1)[-1].lower() if "." in resolved else ""
            if ext not in _ALLOWED_MEDIA_EXTENSIONS:
                media_inventory_offenders.append(
                    f"{part}: image rel Target={target!r} resolves to "
                    f"{resolved!r} whose extension {ext!r} is not in the "
                    f"embed allow-list {sorted(_ALLOWED_MEDIA_EXTENSIONS)}"
                )
                continue
            referenced_media_parts.add(resolved)

        # Every ppt/media/* part must be referenced by an image rel
        # (no orphan media files). Mirrors the deck_plan/render_models
        # 1:1 coverage gate the exporter applies.
        on_disk_media = {
            n for n in names_set
            if n.startswith("ppt/media/") and not n.endswith("/")
        }
        orphan_media = sorted(on_disk_media - referenced_media_parts)
        if orphan_media:
            media_inventory_offenders.append(
                f"orphan media parts not referenced by any image rel: "
                f"{orphan_media}"
            )

        # Every shipped media extension must have a matching
        # `<Default Extension="..."/>` declared in [Content_Types].xml.
        # Without it, PowerPoint cannot dispatch the part type at open.
        ct_defaults = _content_type_defaults(names_set, zf)
        shipped_extensions = sorted({
            n.rsplit(".", 1)[-1].lower()
            for n in on_disk_media
            if "." in n
        })
        for ext in shipped_extensions:
            if ext not in _ALLOWED_MEDIA_EXTENSIONS:
                # Already reported by the per-rel gate above.
                continue
            expected_ct = (
                "image/png" if ext == "png" else "image/jpeg"
            )
            declared_ct = ct_defaults.get(ext)
            if declared_ct != expected_ct:
                media_inventory_offenders.append(
                    f"[Content_Types].xml: extension {ext!r} not "
                    f"registered with ContentType={expected_ct!r} "
                    f"(found {declared_ct!r})"
                )

        out.append(CheckResult(
            f"media.inventory: {pptx_path.name}",
            not media_inventory_offenders,
            ("; ".join(media_inventory_offenders)
             if media_inventory_offenders else ""),
        ))

        # 4c. media.embedded_only — every `<a:blip>` in the package's
        # content XML carries `r:embed` (or no rId at all, for an
        # empty placeholder), never `r:link`. This is the deeper
        # guarantee that no slide / master / layout / theme part is
        # asking PowerPoint to fetch a linked image. Scope is every
        # `*.xml` part under `ppt/` that is not a `_rels/` file —
        # i.e. slides, slideMasters, slideLayouts, theme,
        # presentation; the `_rels/` parts are inspected separately
        # by the relationships.* gates above.
        ppt_xml_parts = _iter_ppt_xml_parts(names_set)
        blip_link_offenders = _blip_link_offenders(zf, ppt_xml_parts)
        out.append(CheckResult(
            f"media.embedded_only: {pptx_path.name}",
            not blip_link_offenders,
            ("; ".join(blip_link_offenders)
             if blip_link_offenders else ""),
        ))

        # 4 + 5 + 6. package.no_macros, package.no_ole, package.no_activex
        content_types = _content_type_overrides(names_set, zf)
        for label, prefix, ct_substr in _FORBIDDEN_PARTS:
            offenders: list[str] = []
            for n in names_list:
                if n.startswith(prefix):
                    offenders.append(f"part {n!r}")
            for ct in content_types:
                if ct_substr.lower() in ct.lower():
                    offenders.append(f"content-type {ct!r}")
            out.append(CheckResult(
                f"{label}: {pptx_path.name}",
                not offenders,
                ("; ".join(offenders) if offenders else ""),
            ))

        # 7 + 8 + 9. minimal_evidence.editable_text +
        #            minimal_evidence.not_all_image_slide +
        #            minimal_evidence.no_blank_slide.
        # All three walk slide XML directly. Stay defensive: a slide
        # that fails to parse counts as "no editable text", "no native
        # shape", and "blank", so a malformed slide cannot pass these
        # gates.
        #
        # not_all_image_slide and no_blank_slide are intentionally
        # sibling gates rather than one combined check: both flag
        # slides that carry zero `<p:sp>` and zero `<p:cxnSp>`, but
        # they disambiguate the failure mode for the report —
        # "all-image" means there is at least one `<p:pic>` (the
        # editor sees a single rasterized box), "blank" means the
        # spTree is structurally empty (the editor sees a literally
        # empty page). An earlier version of the validator only ran
        # not_all_image_slide and false-greened the blank-slide case,
        # because that condition required `n_pic > 0`.
        if not slide_parts:
            # If there are zero slides, every per-slide check is
            # meaningless; the slide_count.inspectable FAIL above
            # already tells the caller why. Emit informative FAILs
            # for all four so the report stays consistent.
            for gate in (
                "minimal_evidence.editable_text",
                "minimal_evidence.not_all_image_slide",
                "minimal_evidence.no_blank_slide",
                "minimal_evidence.every_slide_has_native_shape",
            ):
                out.append(CheckResult(
                    f"{gate}: {pptx_path.name}",
                    False,
                    "no slide parts found",
                ))
        else:
            editable_slides: list[str] = []
            offending_image_slides: list[str] = []
            blank_slides: list[str] = []
            no_native_shape_slides: list[str] = []
            for part in slide_parts:
                n_sp, n_cxn, n_tx, n_pic = _slide_shape_counts(zf, part)
                if n_tx > 0:
                    editable_slides.append(part)
                if n_sp + n_cxn == 0:
                    # Single positive statement of "every slide has at
                    # least one native editable structure". The
                    # not_all_image_slide / no_blank_slide split below
                    # disambiguates the failure mode for the report.
                    no_native_shape_slides.append(part)
                    if n_pic > 0:
                        offending_image_slides.append(part)
                    else:
                        blank_slides.append(part)
            out.append(CheckResult(
                f"minimal_evidence.editable_text: {pptx_path.name}",
                bool(editable_slides),
                (f"at least one <p:txBody> with a non-empty <a:t> run "
                 f"on slide(s): {editable_slides}"
                 if editable_slides else
                 "no slide carried a non-empty <a:t> run"),
            ))
            out.append(CheckResult(
                f"minimal_evidence.not_all_image_slide: {pptx_path.name}",
                not offending_image_slides,
                (f"all-image slides (only <p:pic>, no <p:sp>/<p:cxnSp>): "
                 f"{offending_image_slides}"
                 if offending_image_slides else ""),
            ))
            out.append(CheckResult(
                f"minimal_evidence.no_blank_slide: {pptx_path.name}",
                not blank_slides,
                (f"blank slides (zero <p:sp>, <p:cxnSp>, and <p:pic>): "
                 f"{blank_slides}"
                 if blank_slides else ""),
            ))
            out.append(CheckResult(
                f"minimal_evidence.every_slide_has_native_shape: "
                f"{pptx_path.name}",
                not no_native_shape_slides,
                (f"slides with zero <p:sp>/<p:cxnSp> "
                 f"(all-image and blank slides combined): "
                 f"{no_native_shape_slides}"
                 if no_native_shape_slides else ""),
            ))
    finally:
        zf.close()
    return out


def todo_results() -> list[CheckResult]:
    """Skeleton TODO entries that are reported every run. They are
    informational — neither a PASS nor a FAIL — and are surfaced so
    a caller cannot mistake the container checks for export readiness.
    They are encoded as CheckResult with `ok=True` and a 'TODO' prefix
    in the detail; the printer renders them as `[TODO]` lines so the
    skeleton/TODO surface is visible in every run, including --help."""
    return [
        CheckResult(name, True, f"TODO — {desc}")
        for name, desc in TODO_CHECKS
    ]


def _print_results(section: str, results: list[CheckResult]) -> int:
    print(f"\n== {section} ==")
    fails = 0
    for r in results:
        if r.detail.startswith("TODO"):
            mark = "TODO"
        else:
            mark = "PASS" if r.ok else "FAIL"
        suffix = f" — {r.detail}" if r.detail else ""
        print(f"  [{mark}] {r.name}{suffix}")
        if mark == "FAIL":
            fails += 1
    return fails


_TODO_SECTION_TITLE = (
    "TODO surface (these checks are NOT yet gated by this script; "
    "they remain TODO until the deeper validators land — see "
    "references/pptx-conversion-rules.md)"
)


def run(
    pptx_path: Path | None,
    expected_slide_count: int | None = None,
) -> int:
    """Entry point for skeleton / container modes. Returns the
    process exit code.

    `expected_slide_count`, when supplied alongside `pptx_path`,
    activates the `slide_count.expected` gate in
    `check_generated_pptx`.

    Print order is deliberate: the TODO surface is emitted BEFORE any
    failable build step (`check_container` /
    `check_generated_pptx`) so the doc contract
    (references/pptx-conversion-rules.md — "TODO surface is reported in
    every run") still holds even if a later step raises mid-build."""
    if pptx_path is None:
        print(
            "skeleton mode: no --pptx supplied. Reporting contract / TODO "
            "surface only; deeper validation runs when --pptx is given. "
            "See references/pptx-conversion-rules.md."
        )
    fails = _print_results(_TODO_SECTION_TITLE, todo_results())
    container_failed = False
    if pptx_path is not None:
        container_results = check_container(pptx_path)
        fails += _print_results(
            f"container checks ({pptx_path})",
            container_results,
        )
        container_failed = any(not r.ok for r in container_results)

        # Only run the minimal-evidence checks if the container shape is
        # at least readable enough. The check_generated_pptx function is
        # itself defensive, but if the container failed early (no .pptx
        # extension, missing file, ...) then re-attempting yields no
        # additional signal and just confuses the report.
        if not container_failed:
            fails += _print_results(
                f"minimal-evidence checks ({pptx_path})",
                check_generated_pptx(
                    pptx_path,
                    expected_slide_count=expected_slide_count,
                ),
            )
    elif expected_slide_count is not None:
        # Caller asked for an expected slide count but did not supply
        # --pptx; there is nothing to compare against.
        print(
            "FAIL: --expected-slide-count requires --pptx",
            file=sys.stderr,
        )
        return 2
    print()
    if fails:
        print(f"FAIL: {fails} check(s) did not pass.")
        return 1
    if pptx_path is None:
        print(
            "OK (skeleton): contract / TODO surface reported. "
            "This is NOT proof that PPTX export works."
        )
    else:
        print(
            "OK (container + minimal-evidence): basic OOXML container "
            "checks passed AND minimal-evidence safety / editability "
            "gates passed (including relationships.allow_list, "
            "media.targets_internal, media.inventory, "
            "media.embedded_only, and "
            "minimal_evidence.every_slide_has_native_shape). Deeper "
            "full-inventory editability, theme palette mapping, "
            "determinism, layout-scope, and primitive-scope checks "
            "remain TODO."
        )
    return 0


def _write_minimal_editable_pptx(path: Path, *, slides: list[str]) -> None:
    """Write a minimal valid editable PPTX to `path` for use as a
    self-test fixture. Each entry in `slides` is the inner XML for the
    slide's <p:spTree> (the part inside the <p:spTree> tag, NOT the
    full slide document). The fixture is intentionally hand-rolled
    here — building it via scripts/export_pptx.py would make the
    self-test depend on the exporter's correctness, which is the very
    thing we want to catch regressions in."""
    pres = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<p:sldIdLst>'
        + "".join(
            f'<p:sldId id="{256 + i}" r:id="rId{i + 1}"/>'
            for i in range(len(slides))
        )
        + '</p:sldIdLst>'
        '</p:presentation>'
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                    '<Default Extension="xml" ContentType="application/xml"/>'
                    '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
                    + "".join(
                        f'<Override PartName="/ppt/slides/slide{i + 1}.xml" '
                        f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
                        for i in range(len(slides))
                    )
                    + '</Types>')
        zf.writestr("_rels/.rels",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                    'Target="ppt/presentation.xml"/>'
                    '</Relationships>')
        zf.writestr("ppt/presentation.xml", pres)
        for i, body in enumerate(slides, start=1):
            slide_doc = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<p:cSld><p:spTree>'
                '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                '<p:grpSpPr/>'
                f'{body}'
                '</p:spTree></p:cSld>'
                '</p:sld>'
            )
            zf.writestr(f"ppt/slides/slide{i}.xml", slide_doc)


_EDITABLE_SP_XML = (
    '<p:sp>'
    '<p:nvSpPr>'
    '<p:cNvPr id="2" name="hello"/>'
    '<p:cNvSpPr txBox="1"/>'
    '<p:nvPr/>'
    '</p:nvSpPr>'
    '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
    '<p:txBody><a:bodyPr/><a:lstStyle/>'
    '<a:p><a:r><a:rPr lang="en-US"/><a:t>hello</a:t></a:r></a:p>'
    '</p:txBody>'
    '</p:sp>'
)


_PIC_ONLY_XML = (
    '<p:pic>'
    '<p:nvPicPr>'
    '<p:cNvPr id="2" name="full"/>'
    '<p:cNvPicPr/>'
    '<p:nvPr/>'
    '</p:nvPicPr>'
    '<p:blipFill><a:blip/></p:blipFill>'
    '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
    '</p:pic>'
)


# <p:pic> whose <a:blip> carries an `r:link` attribute — the OOXML
# external-linked-image reference form. media.embedded_only must fail
# closed on any slide carrying this shape, regardless of whether the
# rels file backs the rId with an internal Target. The fixture
# intentionally omits an `r:embed` attribute so the offender is
# unambiguously the linked form.
_PIC_LINK_XML = (
    '<p:pic>'
    '<p:nvPicPr>'
    '<p:cNvPr id="3" name="linked"/>'
    '<p:cNvPicPr/>'
    '<p:nvPr/>'
    '</p:nvPicPr>'
    '<p:blipFill><a:blip r:link="rIdL"/></p:blipFill>'
    '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
    '</p:pic>'
)


# <p:pic> whose <a:blip> uses `r:embed` only — the allowed embedded
# form. media.embedded_only must accept this even when paired with an
# editable text shape, so the positive PNG-embed fixture below uses
# this shape to actually exercise the gate's accept path.
_PIC_EMBED_XML = (
    '<p:pic>'
    '<p:nvPicPr>'
    '<p:cNvPr id="3" name="embed"/>'
    '<p:cNvPicPr/>'
    '<p:nvPr/>'
    '</p:nvPicPr>'
    '<p:blipFill><a:blip r:embed="rId1"/></p:blipFill>'
    '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
    '</p:pic>'
)


def _run_tempfixture_negatives() -> list[CheckResult]:
    """Build a handful of bad fixtures under a temporary directory and
    confirm the container + generated-pptx checks reject each one. These
    are self-contained (they never touch the repo) and exist so a
    regression in the container or minimal-evidence helpers is caught
    without needing a real PPTX checked into the tree.

    Container negatives:
      - missing file (path that does not exist);
      - wrong extension (.zip, .txt);
      - non-zip content with a .pptx extension;
      - empty ZIP with a .pptx extension (no required parts);
      - ZIP missing the required ppt/presentation.xml part.

    Container positive:
      - .pptx ZIP with all required parts — passes container.*.

    Generated-pptx negatives (each is a structurally valid container
    that nevertheless trips one of the new gates):
      - relationship with TargetMode="External" — fails
        relationships.no_external;
      - relationship Target starting with file:// — fails both
        relationships.no_external (URI scheme) and
        relationships.no_file_uri;
      - ppt/vbaProject.bin macro container — fails package.no_macros;
      - ppt/embeddings/oleObject1.bin — fails package.no_ole;
      - ppt/activeX/activeX1.xml — fails package.no_activex;
      - slide with only a <p:pic> (no <p:sp>/<p:cxnSp>) — fails
        minimal_evidence.not_all_image_slide AND
        minimal_evidence.every_slide_has_native_shape;
      - slide with no <p:txBody> anywhere — fails
        minimal_evidence.editable_text;
      - relationship with an unexpected Type URL (comments) — fails
        relationships.allow_list even though Target is local;
      - 2-slide PPTX with expected_slide_count=3 — fails
        slide_count.expected;
      - `image`-typed rel pointing at https://attacker/x.png — fails
        media.targets_internal (and relationships.no_external);
      - `image`-typed rel pointing at ../media/missing.png with no
        on-disk media part behind it — fails media.inventory;
      - orphan ppt/media/<name> part not referenced by any image
        rel — fails media.inventory;
      - ppt/media/image1.gif (extension outside the embed allow-list)
        with a matching image rel — fails media.inventory;
      - slide carrying <a:blip r:link="rIdL"/> alongside an editable
        text shape — fails media.embedded_only (and only that gate;
        the rels file is left untouched so every other media.* /
        relationships.* gate stays green, which is the point — the
        per-<a:blip> inspection is the only gate that catches the
        linked-image form);
      - unparseable XML at ppt/theme/theme1.xml — fails closed on
        media.embedded_only (the gate cannot rule out a buried
        <a:blip r:link/> in malformed XML, so a fail-open `continue`
        would have hidden the offender);
      - direct unit-test on _blip_link_offenders: a stub ZipFile
        whose read() raises zipfile.BadZipFile (CRC mismatch — base
        is Exception, NOT OSError) and RuntimeError (archive-
        internal failure) — both MUST be recorded as offenders,
        otherwise a corrupted .pptx entry could silently bypass the
        gate. The offender string must also include the exception
        type name so a regression in the report is visible.

    Generated-pptx positives:
      - minimal editable PPTX (one <p:sp> with a non-empty <a:t>) —
        passes every container + generated-pptx gate;
      - 2-slide editable PPTX with expected_slide_count=2 — passes
        slide_count.expected;
      - minimal PNG-embed PPTX (one slide carrying both an editable
        text shape AND a <p:pic> with <a:blip r:embed="rId1"/>, plus
        one image rel + ppt/media/image1.png + matching
        `<Default Extension="png"/>`) — passes
        media.targets_internal + media.inventory +
        media.embedded_only."""
    import tempfile

    out: list[CheckResult] = []
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)

        # 1. missing file
        missing = td / "absent.pptx"
        results = check_container(missing)
        out.append(CheckResult(
            "tempfixture: missing .pptx fails container.exists",
            any(r.name.startswith("container.exists") and not r.ok for r in results),
            "; ".join(r.detail for r in results if not r.ok),
        ))

        # 2. wrong extension (.zip)
        wrong_ext = td / "deck.zip"
        wrong_ext.write_bytes(b"PK\x03\x04")  # ZIP magic, doesn't matter — extension gate first
        results = check_container(wrong_ext)
        out.append(CheckResult(
            "tempfixture: wrong extension fails container.extension",
            any(r.name.startswith("container.extension") and not r.ok for r in results),
            "; ".join(r.detail for r in results if not r.ok),
        ))

        # 3. non-zip content with .pptx extension
        not_zip = td / "fake.pptx"
        not_zip.write_text("this is plain text, not a zip archive")
        results = check_container(not_zip)
        out.append(CheckResult(
            "tempfixture: non-zip content fails container.zip",
            any(r.name.startswith("container.zip") and not r.ok for r in results),
            "; ".join(r.detail for r in results if not r.ok),
        ))

        # 4. empty .pptx ZIP (no required parts)
        empty_zip = td / "empty.pptx"
        with zipfile.ZipFile(empty_zip, "w") as zf:
            pass
        results = check_container(empty_zip)
        out.append(CheckResult(
            "tempfixture: empty .pptx ZIP fails container.parts",
            any(r.name.startswith("container.parts") and not r.ok for r in results),
            "; ".join(r.detail for r in results if not r.ok),
        ))

        # 5. .pptx ZIP missing ppt/presentation.xml
        partial_zip = td / "partial.pptx"
        with zipfile.ZipFile(partial_zip, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
            zf.writestr("_rels/.rels", "<Relationships/>")
            # ppt/presentation.xml intentionally omitted
        results = check_container(partial_zip)
        parts_failed = any(
            r.name.startswith("container.parts") and not r.ok for r in results
        )
        out.append(CheckResult(
            "tempfixture: .pptx ZIP missing ppt/presentation.xml fails container.parts",
            parts_failed,
            "; ".join(r.detail for r in results if not r.ok),
        ))

        # 6. .pptx ZIP with all required parts — must PASS container checks.
        good_zip = td / "minimal.pptx"
        with zipfile.ZipFile(good_zip, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
            zf.writestr("_rels/.rels", "<Relationships/>")
            zf.writestr("ppt/presentation.xml", "<presentation/>")
        results = check_container(good_zip)
        out.append(CheckResult(
            "tempfixture: minimal valid .pptx container passes all container.* checks",
            all(r.ok for r in results),
            "; ".join(f"{r.name}: {r.detail}" for r in results if not r.ok),
        ))

        # 7. POSITIVE: minimal editable PPTX with one <p:sp> + <a:t>.
        # Must pass every container and minimal-evidence gate.
        editable_path = td / "editable.pptx"
        _write_minimal_editable_pptx(editable_path, slides=[_EDITABLE_SP_XML])
        c_res = check_container(editable_path)
        g_res = check_generated_pptx(editable_path)
        all_ok = all(r.ok for r in c_res) and all(r.ok for r in g_res)
        out.append(CheckResult(
            "tempfixture: minimal editable .pptx passes all container.* + generated.*",
            all_ok,
            "; ".join(
                f"{r.name}: {r.detail}"
                for r in (c_res + g_res)
                if not r.ok
            ),
        ))

        # 8. relationships.no_external — external TargetMode.
        external_rel = td / "external_rel.pptx"
        _write_minimal_editable_pptx(external_rel, slides=[_EDITABLE_SP_XML])
        with zipfile.ZipFile(external_rel, "a") as zf:
            zf.writestr(
                "ppt/_rels/presentation.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rIdX" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                'Target="https://example.invalid/" TargetMode="External"/>'
                '</Relationships>'
            )
        g_res = check_generated_pptx(external_rel)
        out.append(CheckResult(
            "tempfixture: external TargetMode rel fails relationships.no_external",
            any(r.name.startswith("relationships.no_external") and not r.ok for r in g_res),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 9. relationships.no_file_uri — file:// Target.
        file_rel = td / "file_rel.pptx"
        _write_minimal_editable_pptx(file_rel, slides=[_EDITABLE_SP_XML])
        with zipfile.ZipFile(file_rel, "a") as zf:
            zf.writestr(
                "ppt/_rels/presentation.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rIdF" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                'Target="file:///tmp/leaks-out.jpg"/>'
                '</Relationships>'
            )
        g_res = check_generated_pptx(file_rel)
        out.append(CheckResult(
            "tempfixture: file:// Target fails relationships.no_file_uri",
            any(r.name.startswith("relationships.no_file_uri") and not r.ok for r in g_res),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 10. package.no_macros — ppt/vbaProject.bin
        macro_pptx = td / "macro.pptx"
        _write_minimal_editable_pptx(macro_pptx, slides=[_EDITABLE_SP_XML])
        with zipfile.ZipFile(macro_pptx, "a") as zf:
            zf.writestr("ppt/vbaProject.bin", b"NOT-A-REAL-MACRO")
        g_res = check_generated_pptx(macro_pptx)
        out.append(CheckResult(
            "tempfixture: ppt/vbaProject.bin fails package.no_macros",
            any(r.name.startswith("package.no_macros") and not r.ok for r in g_res),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 11. package.no_ole — ppt/embeddings/oleObject1.bin
        ole_pptx = td / "ole.pptx"
        _write_minimal_editable_pptx(ole_pptx, slides=[_EDITABLE_SP_XML])
        with zipfile.ZipFile(ole_pptx, "a") as zf:
            zf.writestr("ppt/embeddings/oleObject1.bin", b"NOT-A-REAL-OLE-OBJECT")
        g_res = check_generated_pptx(ole_pptx)
        out.append(CheckResult(
            "tempfixture: ppt/embeddings/oleObject1.bin fails package.no_ole",
            any(r.name.startswith("package.no_ole") and not r.ok for r in g_res),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 12. package.no_activex — ppt/activeX/activeX1.xml
        ax_pptx = td / "activex.pptx"
        _write_minimal_editable_pptx(ax_pptx, slides=[_EDITABLE_SP_XML])
        with zipfile.ZipFile(ax_pptx, "a") as zf:
            zf.writestr("ppt/activeX/activeX1.xml", "<ax/>")
        g_res = check_generated_pptx(ax_pptx)
        out.append(CheckResult(
            "tempfixture: ppt/activeX/activeX1.xml fails package.no_activex",
            any(r.name.startswith("package.no_activex") and not r.ok for r in g_res),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 13. minimal_evidence.not_all_image_slide — slide is one <p:pic>.
        pic_only = td / "pic_only.pptx"
        _write_minimal_editable_pptx(pic_only, slides=[_PIC_ONLY_XML])
        g_res = check_generated_pptx(pic_only)
        out.append(CheckResult(
            "tempfixture: all-image slide fails minimal_evidence.not_all_image_slide",
            any(
                r.name.startswith("minimal_evidence.not_all_image_slide")
                and not r.ok
                for r in g_res
            ),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 14. minimal_evidence.editable_text — slide has no <p:txBody>.
        no_text_pptx = td / "no_text.pptx"
        _write_minimal_editable_pptx(no_text_pptx, slides=[_PIC_ONLY_XML])
        g_res = check_generated_pptx(no_text_pptx)
        out.append(CheckResult(
            "tempfixture: slide with no <a:t> fails minimal_evidence.editable_text",
            any(
                r.name.startswith("minimal_evidence.editable_text")
                and not r.ok
                for r in g_res
            ),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 15. minimal_evidence.no_blank_slide — a deck where slide 1
        # is editable but slide 2 is structurally empty must fail.
        # This is the loophole an earlier version of the validator
        # let through: editable_text was satisfied by slide 1, and
        # not_all_image_slide only fired on slides that carried a
        # `<p:pic>`, so the blank slide 2 false-greened.
        mixed_blank_pptx = td / "mixed_blank.pptx"
        _write_minimal_editable_pptx(
            mixed_blank_pptx,
            slides=[_EDITABLE_SP_XML, ""],
        )
        g_res = check_generated_pptx(mixed_blank_pptx)
        out.append(CheckResult(
            "tempfixture: editable+blank deck fails minimal_evidence.no_blank_slide",
            any(
                r.name.startswith("minimal_evidence.no_blank_slide")
                and not r.ok
                for r in g_res
            ),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 16. minimal_evidence.every_slide_has_native_shape — both an
        # all-image slide AND a blank slide fail the single positive
        # gate. We reuse the all-image fixture (slide carries only a
        # <p:pic>) and confirm the new gate fires.
        all_image_native_check = td / "all_image_native_check.pptx"
        _write_minimal_editable_pptx(
            all_image_native_check,
            slides=[_PIC_ONLY_XML],
        )
        g_res = check_generated_pptx(all_image_native_check)
        out.append(CheckResult(
            "tempfixture: all-image slide fails "
            "minimal_evidence.every_slide_has_native_shape",
            any(
                r.name.startswith(
                    "minimal_evidence.every_slide_has_native_shape"
                )
                and not r.ok
                for r in g_res
            ),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 17a. slide_count.expected — positive: a 2-slide PPTX
        # validates cleanly against expected_slide_count=2.
        two_slide_pos = td / "two_slide_pos.pptx"
        _write_minimal_editable_pptx(
            two_slide_pos,
            slides=[_EDITABLE_SP_XML, _EDITABLE_SP_XML],
        )
        g_res = check_generated_pptx(two_slide_pos, expected_slide_count=2)
        out.append(CheckResult(
            "tempfixture: 2-slide PPTX passes slide_count.expected=2",
            all(r.ok for r in g_res),
            "; ".join(f"{r.name}: {r.detail}" for r in g_res if not r.ok),
        ))

        # 17b. slide_count.expected — negative: a 2-slide PPTX fails
        # closed when the caller claims expected_slide_count=3.
        g_res = check_generated_pptx(two_slide_pos, expected_slide_count=3)
        out.append(CheckResult(
            "tempfixture: 2-slide PPTX fails slide_count.expected=3",
            any(
                r.name.startswith("slide_count.expected")
                and not r.ok
                for r in g_res
            ),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 17. relationships.allow_list — a relationship with an
        # unexpected Type URL (e.g. comments) fails the allow-list
        # gate even when its Target is local and lacks a URI scheme.
        # This is what distinguishes allow_list from no_external:
        # both fail under an https:// Target, but only allow_list
        # fires on an unknown internal Type.
        bad_rel_type_pptx = td / "bad_rel_type.pptx"
        _write_minimal_editable_pptx(bad_rel_type_pptx, slides=[_EDITABLE_SP_XML])
        with zipfile.ZipFile(bad_rel_type_pptx, "a") as zf:
            zf.writestr(
                "ppt/_rels/presentation.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rIdC" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" '
                'Target="comments/comment1.xml"/>'
                '</Relationships>'
            )
        g_res = check_generated_pptx(bad_rel_type_pptx)
        out.append(CheckResult(
            "tempfixture: unexpected relationship Type fails "
            "relationships.allow_list",
            any(
                r.name.startswith("relationships.allow_list")
                and not r.ok
                for r in g_res
            ),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 18. media.targets_internal — an `image` rel pointing at an
        # external https:// URL fails BOTH `relationships.no_external`
        # (URI-scheme prefix) and the new media-only restatement
        # `media.targets_internal`. The double-fail is intentional so a
        # caller can see at a glance which contract dimension fired.
        external_image_rel = td / "external_image_rel.pptx"
        _write_minimal_editable_pptx(
            external_image_rel, slides=[_EDITABLE_SP_XML],
        )
        with zipfile.ZipFile(external_image_rel, "a") as zf:
            zf.writestr(
                "ppt/slides/_rels/slide1.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rIdImg" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                'Target="https://attacker.invalid/x.png"/>'
                '</Relationships>'
            )
        g_res = check_generated_pptx(external_image_rel)
        out.append(CheckResult(
            "tempfixture: external https:// image rel fails "
            "media.targets_internal",
            any(
                r.name.startswith("media.targets_internal")
                and not r.ok
                for r in g_res
            ),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 19. media.inventory — image rel that points at a missing
        # ppt/media/<name> part fails the inventory gate. The container
        # has the rel but no actual media file behind it.
        dangling_media_rel = td / "dangling_media_rel.pptx"
        _write_minimal_editable_pptx(
            dangling_media_rel, slides=[_EDITABLE_SP_XML],
        )
        with zipfile.ZipFile(dangling_media_rel, "a") as zf:
            zf.writestr(
                "ppt/slides/_rels/slide1.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rIdImg" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                'Target="../media/missing.png"/>'
                '</Relationships>'
            )
        g_res = check_generated_pptx(dangling_media_rel)
        out.append(CheckResult(
            "tempfixture: image rel pointing at missing "
            "ppt/media/<name> part fails media.inventory",
            any(
                r.name.startswith("media.inventory")
                and not r.ok
                for r in g_res
            ),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 20. media.inventory — an orphan ppt/media/<name> part with
        # no image rel referencing it also fails the inventory gate.
        # This catches the "embedded bytes nobody can render" failure
        # mode where the exporter copied a file into the package but
        # never wired up the relationship.
        orphan_media_pptx = td / "orphan_media.pptx"
        _write_minimal_editable_pptx(
            orphan_media_pptx, slides=[_EDITABLE_SP_XML],
        )
        with zipfile.ZipFile(orphan_media_pptx, "a") as zf:
            zf.writestr("ppt/media/orphan.png", b"\x89PNG\r\n\x1a\n")
        g_res = check_generated_pptx(orphan_media_pptx)
        out.append(CheckResult(
            "tempfixture: orphan ppt/media/<name> part fails "
            "media.inventory",
            any(
                r.name.startswith("media.inventory")
                and not r.ok
                for r in g_res
            ),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 21. media.inventory — a ppt/media/<name>.gif part (extension
        # outside the embed allow-list) fails closed even when an
        # image rel references it correctly. The exporter only embeds
        # PNG / JPG / JPEG today; widening that surface must widen the
        # validator at the same time.
        bad_ext_pptx = td / "bad_media_ext.pptx"
        _write_minimal_editable_pptx(
            bad_ext_pptx, slides=[_EDITABLE_SP_XML],
        )
        with zipfile.ZipFile(bad_ext_pptx, "a") as zf:
            zf.writestr("ppt/media/image1.gif", b"GIF89a;")
            zf.writestr(
                "ppt/slides/_rels/slide1.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rIdImg" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                'Target="../media/image1.gif"/>'
                '</Relationships>'
            )
        g_res = check_generated_pptx(bad_ext_pptx)
        out.append(CheckResult(
            "tempfixture: ppt/media/image1.gif (extension outside the "
            "embed allow-list) fails media.inventory",
            any(
                r.name.startswith("media.inventory")
                and not r.ok
                for r in g_res
            ),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 22. POSITIVE: a minimal-editable PPTX with one PNG embed +
        # matching `<Default Extension="png" ContentType="image/png"/>`
        # + slide rel + on-disk part passes media.inventory and
        # media.targets_internal cleanly. This is the validator-side
        # complement to the exporter's PNG-embed self-test.
        good_media_pptx = td / "good_media.pptx"
        # Hand-roll the package directly — we want this fixture to
        # cover the validator independent of the exporter's
        # correctness, so we bypass `_write_minimal_editable_pptx`'s
        # fixed [Content_Types].xml shape and emit a custom one here.
        with zipfile.ZipFile(good_media_pptx, "w") as zf:
            zf.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Default Extension="png" ContentType="image/png"/>'
                '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
                '<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
                '</Types>'
            )
            zf.writestr(
                "_rels/.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                'Target="ppt/presentation.xml"/>'
                '</Relationships>'
            )
            zf.writestr(
                "ppt/presentation.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst>'
                '</p:presentation>'
            )
            zf.writestr(
                "ppt/slides/slide1.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<p:cSld><p:spTree>'
                '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                '<p:grpSpPr/>'
                + _EDITABLE_SP_XML
                # Adding the r:embed picture next to the editable shape
                # so the positive actually exercises
                # media.embedded_only's accept path; without it the
                # gate would pass trivially (zero blips in the slide).
                + _PIC_EMBED_XML +
                '</p:spTree></p:cSld>'
                '</p:sld>'
            )
            zf.writestr(
                "ppt/slides/_rels/slide1.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                'Target="../media/image1.png"/>'
                '</Relationships>'
            )
            zf.writestr(
                "ppt/media/image1.png",
                bytes([
                    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
                ]),
            )
        g_res = check_generated_pptx(good_media_pptx)
        # The minimal fixture intentionally skips the slideMaster /
        # slideLayout / theme parts; the only gates we care about
        # here are media.targets_internal + media.inventory +
        # media.embedded_only passing, not every container check. We
        # assert specifically that no `media.*` gate failed. Because
        # the slide body now carries _PIC_EMBED_XML alongside the
        # editable text shape, media.embedded_only is actually
        # exercised (not just vacuously passed on a zero-blip slide).
        media_failures = [
            r for r in g_res
            if r.name.startswith("media.") and not r.ok
        ]
        out.append(CheckResult(
            "tempfixture: minimal PNG-embed PPTX passes "
            "media.targets_internal + media.inventory + "
            "media.embedded_only",
            not media_failures,
            "; ".join(
                f"{r.name}: {r.detail}" for r in media_failures
            ),
        ))

        # 23. media.embedded_only — a slide that carries
        # <a:blip r:link="rIdL"/> fails closed even though the slide
        # ALSO carries an editable text shape (so editable_text /
        # not_all_image_slide / no_blank_slide /
        # every_slide_has_native_shape all PASS — the only gate that
        # fires is media.embedded_only itself). This is what
        # distinguishes media.embedded_only from the rels-side
        # gates: the rels file is left untouched, so
        # relationships.no_external / relationships.no_file_uri /
        # relationships.allow_list / media.targets_internal /
        # media.inventory do NOT trip — only the per-<a:blip>
        # inspection catches the linked-image form.
        linked_blip_pptx = td / "linked_blip.pptx"
        _write_minimal_editable_pptx(
            linked_blip_pptx,
            slides=[_EDITABLE_SP_XML + _PIC_LINK_XML],
        )
        g_res = check_generated_pptx(linked_blip_pptx)
        out.append(CheckResult(
            "tempfixture: <a:blip r:link='...'/> fails "
            "media.embedded_only",
            any(
                r.name.startswith("media.embedded_only")
                and not r.ok
                for r in g_res
            ),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 24. media.embedded_only — an unparseable XML part anywhere
        # under ppt/ (here a malformed ppt/theme/theme1.xml) fails
        # closed on media.embedded_only. The gate cannot rule out a
        # buried <a:blip r:link/> in malformed XML, so a fail-open
        # `continue` would have hidden the offender. The fixture puts
        # the malformed XML in a part the slide-level gates don't
        # scan (theme1.xml is not a slide), so this specifically
        # exercises media.embedded_only's parse path — the other
        # minimal-evidence gates stay green.
        unparseable_xml_pptx = td / "unparseable_xml.pptx"
        _write_minimal_editable_pptx(
            unparseable_xml_pptx, slides=[_EDITABLE_SP_XML],
        )
        with zipfile.ZipFile(unparseable_xml_pptx, "a") as zf:
            zf.writestr("ppt/theme/theme1.xml", "<not-xml")
        g_res = check_generated_pptx(unparseable_xml_pptx)
        out.append(CheckResult(
            "tempfixture: unparseable XML part under ppt/ fails "
            "closed on media.embedded_only (no fail-open parse path)",
            any(
                r.name.startswith("media.embedded_only")
                and not r.ok
                for r in g_res
            ),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

        # 25. Direct unit-test on _blip_link_offenders' READ-side
        # exception handling. zipfile.ZipFile.read() can raise
        # exceptions outside the (KeyError, OSError) tuple:
        # zipfile.BadZipFile on CRC mismatch (its base is Exception,
        # NOT OSError), and RuntimeError on certain archive-internal
        # failures. Both must land in the offender list — otherwise
        # a corrupted .pptx entry would silently bypass the gate.
        # The stub raises the exception in place of a real ZipFile
        # so the test does not depend on Python's zipfile internals
        # producing the right error for a hand-corrupted archive
        # (which is brittle across CPython versions). The same stub
        # also covers the parse-side broadening, since a Unicode
        # decode failure surfaces as a non-ParseError exception in
        # some XML parsers.
        class _ReadRaisesZipFile:
            def __init__(self, exc: Exception) -> None:
                self._exc = exc

            def read(self, _part: str) -> bytes:
                raise self._exc

        read_side_failures: list[str] = []
        for exc in (
            zipfile.BadZipFile("simulated CRC failure on read"),
            RuntimeError("simulated read on closed archive"),
        ):
            fake_zf = _ReadRaisesZipFile(exc)
            offenders = _blip_link_offenders(
                fake_zf,  # type: ignore[arg-type]
                ["ppt/theme/theme1.xml"],
            )
            if not offenders:
                read_side_failures.append(
                    f"{type(exc).__name__} did not produce an offender"
                )
                continue
            # The offender string MUST name the exception type so a
            # regression in the message format is visible too.
            joined = "; ".join(offenders)
            if type(exc).__name__ not in joined:
                read_side_failures.append(
                    f"{type(exc).__name__} offender did not include "
                    f"the exception type name: {joined!r}"
                )
        out.append(CheckResult(
            "tempfixture: read-side zipfile.BadZipFile + RuntimeError "
            "are reported as media.embedded_only offenders "
            "(fail-closed read path)",
            not read_side_failures,
            "; ".join(read_side_failures),
        ))

        # 26. media.targets_internal — an `image`-typed rel
        # placed at the PACKAGE-level rels file
        # (`ppt/_rels/presentation.xml.rels`) pointing at an
        # external https:// URL must fail closed on both
        # `relationships.no_external` and `media.targets_internal`.
        # Existing scenario #18 exercises the same gate at slide
        # rels level; this scenario proves the rels walker covers
        # every rels part in the package (defense in depth for
        # the embedded-only contract). The fixture also sets
        # TargetMode="External" so the no_external gate fires on
        # the TargetMode dimension AND on the URI-scheme prefix.
        pkg_external_image_rel = td / "pkg_external_image_rel.pptx"
        _write_minimal_editable_pptx(
            pkg_external_image_rel, slides=[_EDITABLE_SP_XML],
        )
        with zipfile.ZipFile(pkg_external_image_rel, "a") as zf:
            zf.writestr(
                "ppt/_rels/presentation.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rIdExtImg" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                'Target="https://attacker.invalid/leaked.png" '
                'TargetMode="External"/>'
                '</Relationships>'
            )
        g_res = check_generated_pptx(pkg_external_image_rel)
        out.append(CheckResult(
            "tempfixture: external image rel at the package-level "
            "rels (ppt/_rels/presentation.xml.rels) fails closed on "
            "media.targets_internal (rels walker covers every rels "
            "part, not just slide rels)",
            any(
                r.name.startswith("media.targets_internal")
                and not r.ok
                for r in g_res
            ),
            "; ".join(r.detail for r in g_res if not r.ok),
        ))

    return out


def _todo_epilog() -> str:
    """Render the TODO_CHECKS list as an argparse epilog so the deeper
    checks the future exporter must satisfy are visible in --help, not
    only in the per-run output. The doc contract
    (references/pptx-conversion-rules.md, README.md) commits to
    surfacing the TODO list in --help."""
    lines = [
        "TODO surface (these checks remain TODO and are not gated by",
        "this script today; see references/pptx-conversion-rules.md for",
        "the contract):",
    ]
    width = max(len(name) for name, _ in TODO_CHECKS)
    for name, desc in TODO_CHECKS:
        lines.append(f"  {name.ljust(width)}  {desc}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "PPTX export contract / minimal-evidence validator "
            "(stdlib-only, fail-closed). The PPTX exporter "
            "(scripts/export_pptx.py) produces a native editable "
            "subset — the cover / kpi_dashboard / agenda / "
            "section_divider / executive_summary / key_message / "
            "two_column / timeline / conclusion / comparison_table "
            "layouts; text / line / shape / image_slot / kpi / table "
            "primitives; embedded PNG / JPG / JPEG media for "
            "image_slot — and this validator gates that output. With "
            "--pptx, runs the basic OOXML container checks AND the "
            "minimal-evidence safety/editability checks (slide count, "
            "no external rels, no file:// rels, relationship Type "
            "allow-list including the `image` URL, media.targets_internal "
            "+ media.inventory + media.embedded_only for embedded "
            "PNG / JPG / JPEG assets (the last refuses any "
            "<a:blip r:link='...'/> linked-image reference anywhere in "
            "the package's content XML), no macros / OLE / ActiveX "
            "parts, at least one editable "
            "text run, no all-image slide, no blank slide, every "
            "slide carries at least one <p:sp> or <p:cxnSp>). Add "
            "--expected-slide-count N to also fail closed if the "
            "number of ppt/slides/slide{N}.xml parts != N. "
            "Without --pptx, runs in skeleton mode and only reports "
            "the contract / TODO surface. --self-test runs the "
            "in-script tempfixture negatives + positives. The TODO "
            "surface is reported in every run and is also listed below "
            "in --help."
        ),
        epilog=_todo_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pptx",
        type=Path,
        default=None,
        help=(
            "Path to a .pptx file to inspect at the container + "
            "minimal-evidence level. If omitted, the validator runs "
            "in skeleton mode and does not open or fabricate any file."
        ),
    )
    parser.add_argument(
        "--expected-slide-count",
        type=int,
        default=None,
        help=(
            "Optional positive integer. When supplied alongside "
            "--pptx, activates the slide_count.expected gate: the "
            "number of ppt/slides/slide{N}.xml parts in the package "
            "must equal this value, otherwise the run fails closed. "
            "Use this from CI to catch a deck that the exporter "
            "silently truncated."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run the in-script tempfixture negatives (missing file, "
            "wrong extension, non-zip content, empty ZIP, ZIP missing "
            "ppt/presentation.xml, external rel, file:// rel, "
            "unexpected relationship Type, vba / OLE / ActiveX parts, "
            "all-image slide [fails both not_all_image_slide and "
            "every_slide_has_native_shape], no editable text, blank "
            "slide alongside an editable one, slide_count.expected "
            "mismatch, external image rel, dangling image-rel Target, "
            "orphan ppt/media part, ppt/media/<name>.gif outside the "
            "embed allow-list, slide carrying <a:blip r:link='...'/>, "
            "unparseable XML at ppt/theme/theme1.xml [fails closed on "
            "media.embedded_only — no fail-open parse path], direct "
            "unit-test that stub-injected zipfile.BadZipFile + "
            "RuntimeError on read are recorded as media.embedded_only "
            "offenders [no fail-open read path], external image rel "
            "at package-level rels [ppt/_rels/presentation.xml.rels] "
            "fails closed on media.targets_internal — rels walker "
            "covers every rels part, not just slide rels) "
            "plus positives (minimal valid container, minimal "
            "editable PPTX, 2-slide PPTX passing "
            "slide_count.expected=2, minimal PNG-embed PPTX passing "
            "media.targets_internal + media.inventory + "
            "media.embedded_only). Exits non-zero if any negative is "
            "not caught or any positive is not accepted."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        # Print the TODO surface FIRST so the doc contract (README.md,
        # references/pptx-conversion-rules.md — "TODO surface is
        # reported in every run") still holds even if the tempfixture
        # step below raises or records failures. The tempfixture
        # builder writes files and creates zip containers; we never
        # want a failure there to swallow the contract surface.
        fails = _print_results(_TODO_SECTION_TITLE, todo_results())
        fails += _print_results(
            "self-test: tempfixture negatives + positive",
            _run_tempfixture_negatives(),
        )
        print()
        if fails:
            print(f"FAIL: {fails} self-test check(s) did not pass.")
            return 1
        print(
            "OK (self-test): every tempfixture negative is caught and "
            "the minimal-valid-container + minimal-editable PPTX "
            "positives pass. The TODO surface above lists the deeper "
            "validators that still need to come online; a passing "
            "self-test is NOT proof of full PPTX export correctness."
        )
        return 0

    if (
        args.expected_slide_count is not None
        and args.expected_slide_count < 1
    ):
        print(
            f"FAIL: --expected-slide-count must be a positive integer; "
            f"got {args.expected_slide_count}",
            file=sys.stderr,
        )
        return 2
    return run(
        args.pptx,
        expected_slide_count=args.expected_slide_count,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
