#!/usr/bin/env python3
"""inspect_pptx_inventory.py

Stdlib-only PPTX readback inventory. Reads a `.pptx` ZIP and emits a
**deterministic** JSON inventory of what the package's OOXML structure
declares: slide count, per-slide native object counts (text boxes,
shapes, connectors, pictures, tables, graphic frames, text bodies,
text runs), per-slide media relationships, embedded media parts with
size / sha256 / extension / content type / referencing slides, the
full relationship list sorted deterministically, and findings for
external / file:// / absolute-path / path-traversal relationship
targets, missing-or-unresolvable media, orphan media, unsupported
media extensions, image-only slides, `<a:blip r:link="..."/>`
linked-image references anywhere in slides / slideMasters /
slideLayouts / theme / presentation, and unreadable ZIP / XML parts
(slide parts plus the non-`_rels/` XML parts under `ppt/` traversed
by the linked-blip walker).

This is **inspection only**: it never modifies the package, never calls
any network, never overclaims full PowerPoint editability — every
count it reports is "evidence from the OOXML structure", not proof a
slide opens cleanly in PowerPoint. It complements
`scripts/validate_pptx_contract.py`, which gates a `.pptx` with
pass/fail lines; this script produces a structured artifact a CI or
review surface can consume.

USAGE
    # Print the inventory JSON for a .pptx to stdout.
    python3 scripts/inspect_pptx_inventory.py --pptx path/to/deck.pptx

    # Write the inventory JSON to a file (must NOT live inside the
    # PPTX path's directory tree — checked by the caller). The script
    # itself only refuses an existing symlink at --out.
    python3 scripts/inspect_pptx_inventory.py --pptx deck.pptx --out report.json

    # Self-test: 17 temp-fixture scenarios — happy path, deterministic
    # repeated inventory, image-only slide failure, missing media,
    # image rel with NO Target attribute (without the explicit check
    # the rel would fall off every downstream media gate — the
    # path-traversal block guards on `target` truthiness), orphan
    # media, external rel, file:// rel, absolute-path rel,
    # path-traversal rel, bad XML at a slide part, unsupported media
    # extension, linked-blip `<a:blip r:link/>` in slide content,
    # unparseable XML in a non-slide ppt/ part (no fail-open
    # continue), unreadable ZIP, nonexistent file, and an external
    # image rel placed at the PACKAGE-level rels file
    # (`ppt/_rels/presentation.xml.rels`) — defense in depth proving
    # the rels walker iterates every `*.rels` member, not only
    # slide-level rels.
    python3 scripts/inspect_pptx_inventory.py --self-test

FAIL-CLOSED SURFACE (each emits a finding with severity="error";
                    exit 1 if any finding is recorded)
    package.unreadable_zip       — the .pptx does not open as a ZIP.
    package.unreadable_xml       — an XML part under ppt/ cannot be
                                   read OR parsed (incl. zipfile.BadZipFile
                                   for CRC failures, RuntimeError for
                                   archive-internal failures).
    relationships.external       — a Relationship has
                                   TargetMode="External" or its Target
                                   carries a URI scheme prefix.
    relationships.file_uri       — a Relationship Target starts with
                                   file://.
    relationships.absolute       — a Relationship Target is a POSIX
                                   absolute path (leading /).
    relationships.path_traversal — a Relationship Target with ..
                                   segments resolves above the package
                                   root.
    media.missing                — an `image`-typed Relationship has a
                                   missing or empty Target, OR its
                                   Target does not resolve to a part
                                   in the package. The missing/empty
                                   sub-case mirrors
                                   validate_pptx_contract.py's
                                   media.targets_internal gate ("image
                                   rel missing Target") at the
                                   structured-readback layer — a rel
                                   that names no part at all must NOT
                                   silently pass every media check.
    media.orphan                 — a ppt/media/<name> part is not
                                   referenced by any image relationship.
    media.unsupported_extension  — a ppt/media/ part's extension is
                                   not in the {png, jpg, jpeg} embed
                                   allow-list (matches the exporter's
                                   embed surface today).
    slide.image_only             — a slide carries at least one
                                   <p:pic> but no <p:sp> and no
                                   <p:cxnSp> — the same image-only
                                   failure mode validate_pptx_contract.py
                                   refuses via
                                   minimal_evidence.not_all_image_slide.
    media.linked_blip            — a <a:blip> element anywhere in the
                                   package's content XML carries an
                                   r:link="..." attribute. Scope is
                                   every *.xml part under ppt/ that is
                                   not a _rels/ file (slides,
                                   slideMasters, slideLayouts, theme,
                                   presentation). The r:link form is
                                   OOXML's external-linked-image
                                   reference; the exporter only emits
                                   r:embed — same surface
                                   validate_pptx_contract.py's
                                   media.embedded_only gate refuses.

EXIT
    0  every check passed (no findings).
    1  one or more findings recorded (the JSON is still emitted so the
       caller can read what failed).
    2  invocation error (missing --pptx with no --self-test, etc.).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any


# OOXML namespaces we care about. Mirrored from validate_pptx_contract.py
# so this script stays stdlib-only and free of cross-script imports —
# the two scripts have different output contracts (pass/fail vs JSON
# inventory) and intentionally do not share state.
_NS_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_NS_DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS_PRES = "http://schemas.openxmlformats.org/presentationml/2006/main"

_REL_TYPE_IMAGE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)

# Allowed embedded-media extensions. Mirrors validate_pptx_contract.py's
# _ALLOWED_MEDIA_EXTENSIONS — kept local so this script is self-contained.
_ALLOWED_MEDIA_EXTENSIONS: frozenset[str] = frozenset({"png", "jpg", "jpeg"})

# Expected ContentType per extension. Mirrors the exporter's
# [Content_Types].xml emission today.
_EXPECTED_CT_PER_EXT: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}

# RFC 3986 scheme prefix.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Short, stable framing string that callers can grep for.
EVIDENCE_BASIS = (
    "OOXML structure only; not proof of full PowerPoint editability"
)


def _posix_resolve(base_dir: str, relative: str) -> str | None:
    """Resolve a POSIX `relative` reference against `base_dir`.

    Returns None if the resolution would escape the package root (a
    leading `/`, or too many `..`). Mirrors
    validate_pptx_contract.py's helper of the same name."""
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
    describes. Resolution rule: drop the trailing `_rels/<name>.rels`
    and return the parent directory of the owning part."""
    segs = rels_part.split("/")
    if "_rels" not in segs:
        return rels_part.rsplit("/", 1)[0] if "/" in rels_part else ""
    rels_index = segs.index("_rels")
    return "/".join(segs[:rels_index])


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


def _slide_index_from_part(part: str) -> int | None:
    """Extract the integer N from `ppt/slides/slide{N}.xml`. Returns
    None if the name does not match — the caller treats the index as
    'unknown' for sort purposes (using the part name as a tiebreaker
    keeps determinism)."""
    m = re.match(r"^ppt/slides/slide(\d+)\.xml$", part)
    if not m:
        return None
    return int(m.group(1))


def _content_type_defaults(
    zf: zipfile.ZipFile, names: set[str],
) -> dict[str, str]:
    """Read [Content_Types].xml and return {extension_lower: ContentType}
    for every `<Default>` entry. Empty dict if the file is missing or
    unparseable — the missing/unparseable case is surfaced as its own
    `package.unreadable_xml` finding by the caller."""
    if "[Content_Types].xml" not in names:
        return {}
    try:
        text = zf.read("[Content_Types].xml")
        root = ET.fromstring(text)
    except Exception:
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


def _iter_rels_parts(names: set[str]) -> list[str]:
    """Return every *.rels member name sorted lexicographically."""
    return sorted(n for n in names if n.endswith(".rels"))


def _read_relationships(
    zf: zipfile.ZipFile, rels_parts: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read every <Relationship> element across `rels_parts`. Return
    (relationships, parse_findings). Each relationship entry is a dict
    with rels_part / id / type / target / target_mode keys, sorted
    deterministically by the caller.

    A rels file we cannot read or parse becomes a `package.unreadable_xml`
    finding so the caller can still emit the inventory while the run
    fails closed.
    """
    rels: list[dict[str, Any]] = []
    parse_findings: list[dict[str, Any]] = []
    rel_tag = f"{{{_NS_RELS}}}Relationship"
    root_tag = f"{{{_NS_RELS}}}Relationships"
    for part in rels_parts:
        try:
            text = zf.read(part)
        except Exception as exc:
            parse_findings.append({
                "severity": "error",
                "code": "package.unreadable_xml",
                "part": part,
                "detail": f"read failed ({type(exc).__name__}: {exc})",
            })
            continue
        try:
            root = ET.fromstring(text)
        except Exception as exc:
            parse_findings.append({
                "severity": "error",
                "code": "package.unreadable_xml",
                "part": part,
                "detail": f"parse failed ({type(exc).__name__}: {exc})",
            })
            continue
        if root.tag != root_tag:
            # Not a Relationships file — silently skip (matches what
            # the contract validator does). The caller will not double-
            # flag this as a finding.
            continue
        for child in root:
            if child.tag != rel_tag:
                continue
            rels.append({
                "rels_part": part,
                "id": child.attrib.get("Id", ""),
                "type": child.attrib.get("Type", ""),
                "target": child.attrib.get("Target", ""),
                "target_mode": child.attrib.get("TargetMode") or None,
            })
    return rels, parse_findings


def _slide_native_counts(
    zf: zipfile.ZipFile, slide_part: str,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Return (counts, parse_findings) for a single slide part.

    `counts` carries the per-kind native object counts from the slide's
    OOXML. `parse_findings` is non-empty when the slide XML cannot be
    read or parsed — counts default to zero in that case so the inventory
    still emits a row for the slide. This is fail-closed, not fail-open:
    the caller treats `parse_findings` as `package.unreadable_xml`
    errors and the JSON's `ok` becomes false."""
    parse_findings: list[dict[str, Any]] = []
    counts: dict[str, int] = {
        "shapes_sp": 0,
        "connectors_cxnSp": 0,
        "pictures_pic": 0,
        "graphic_frames": 0,
        "tables": 0,
        "text_bodies": 0,
        "text_runs": 0,
    }
    try:
        text = zf.read(slide_part)
    except Exception as exc:
        parse_findings.append({
            "severity": "error",
            "code": "package.unreadable_xml",
            "part": slide_part,
            "detail": f"read failed ({type(exc).__name__}: {exc})",
        })
        return counts, parse_findings
    try:
        root = ET.fromstring(text)
    except Exception as exc:
        parse_findings.append({
            "severity": "error",
            "code": "package.unreadable_xml",
            "part": slide_part,
            "detail": f"parse failed ({type(exc).__name__}: {exc})",
        })
        return counts, parse_findings

    sp_tag = f"{{{_NS_PRES}}}sp"
    cxn_tag = f"{{{_NS_PRES}}}cxnSp"
    pic_tag = f"{{{_NS_PRES}}}pic"
    gfr_tag = f"{{{_NS_PRES}}}graphicFrame"
    txbody_tag = f"{{{_NS_PRES}}}txBody"
    tbl_tag = f"{{{_NS_DRAWING}}}tbl"
    r_tag = f"{{{_NS_DRAWING}}}r"

    counts["shapes_sp"] = sum(1 for _ in root.iter(sp_tag))
    counts["connectors_cxnSp"] = sum(1 for _ in root.iter(cxn_tag))
    counts["pictures_pic"] = sum(1 for _ in root.iter(pic_tag))
    counts["graphic_frames"] = sum(1 for _ in root.iter(gfr_tag))
    counts["tables"] = sum(1 for _ in root.iter(tbl_tag))
    counts["text_bodies"] = sum(1 for _ in root.iter(txbody_tag))
    counts["text_runs"] = sum(1 for _ in root.iter(r_tag))
    return counts, parse_findings


def _slide_rids(
    zf: zipfile.ZipFile, slide_part: str,
) -> tuple[set[str], list[dict[str, Any]]]:
    """Return the set of rIds the slide references via <a:blip r:embed/>.
    Used to attribute media parts back to their referencing slides."""
    parse_findings: list[dict[str, Any]] = []
    rids: set[str] = set()
    try:
        text = zf.read(slide_part)
    except Exception as exc:
        parse_findings.append({
            "severity": "error",
            "code": "package.unreadable_xml",
            "part": slide_part,
            "detail": (
                f"read failed (referenced rId attribution skipped) "
                f"({type(exc).__name__}: {exc})"
            ),
        })
        return rids, parse_findings
    try:
        root = ET.fromstring(text)
    except Exception as exc:
        parse_findings.append({
            "severity": "error",
            "code": "package.unreadable_xml",
            "part": slide_part,
            "detail": (
                f"parse failed (referenced rId attribution skipped) "
                f"({type(exc).__name__}: {exc})"
            ),
        })
        return rids, parse_findings
    blip_tag = f"{{{_NS_DRAWING}}}blip"
    embed_attr = (
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
        "embed"
    )
    for blip in root.iter(blip_tag):
        embed_val = blip.attrib.get(embed_attr)
        if isinstance(embed_val, str) and embed_val:
            rids.add(embed_val)
    return rids, parse_findings


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _iter_ppt_xml_parts(names_set: set[str]) -> list[str]:
    """Return every `*.xml` part under `ppt/` that is NOT a `_rels/`
    file. Mirrors validate_pptx_contract.py's helper of the same name —
    the scope where `<a:blip r:link/>` references can legally appear
    (slides, slideMasters, slideLayouts, theme, presentation)."""
    out: list[str] = []
    for n in names_set:
        if not n.startswith("ppt/"):
            continue
        if not n.endswith(".xml"):
            continue
        if "_rels/" in n:
            continue
        out.append(n)
    out.sort()
    return out


def _collect_linked_blip_findings(
    zf: zipfile.ZipFile,
    names_set: set[str],
    unreadable_already_reported: set[str],
) -> list[dict[str, Any]]:
    """Scan every `ppt/*.xml` part not in `_rels/` for `<a:blip r:link="..."/>`
    elements. Mirrors validate_pptx_contract.py's `media.embedded_only`
    gate at the structured-readback layer: the `r:link` form is OOXML's
    external-linked-image reference (its Target can legally be a remote
    URL, `file://`, or any other reference outside the package), so a
    slide using it asks PowerPoint to fetch a linked image at open
    time. Each offender becomes a `media.linked_blip` finding.

    Fail-closed read + parse handling: any exception during
    `ZipFile.read()` or `ET.fromstring()` against an in-scope part is
    itself a `package.unreadable_xml` finding — the gate cannot rule
    out a buried `<a:blip r:link/>` in malformed XML, so a fail-open
    `continue` would silently bypass the contract. The exception type
    name is included in the offender string for debuggability.
    `unreadable_already_reported` deduplicates parts the slide-parse
    loop already flagged so the same slide is not double-counted as
    unreadable across the two passes."""
    out: list[dict[str, Any]] = []
    blip_tag = f"{{{_NS_DRAWING}}}blip"
    link_attr = (
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
        "link"
    )
    for part in _iter_ppt_xml_parts(names_set):
        try:
            text = zf.read(part)
        except Exception as exc:
            if part not in unreadable_already_reported:
                out.append({
                    "severity": "error",
                    "code": "package.unreadable_xml",
                    "part": part,
                    "detail": (
                        f"read failed; cannot rule out <a:blip r:link/> "
                        f"({type(exc).__name__}: {exc})"
                    ),
                })
            continue
        try:
            root = ET.fromstring(text)
        except Exception as exc:
            if part not in unreadable_already_reported:
                out.append({
                    "severity": "error",
                    "code": "package.unreadable_xml",
                    "part": part,
                    "detail": (
                        f"parse failed; cannot rule out <a:blip r:link/> "
                        f"({type(exc).__name__}: {exc})"
                    ),
                })
            continue
        for blip in root.iter(blip_tag):
            link_val = blip.attrib.get(link_attr)
            if link_val is None:
                continue
            out.append({
                "severity": "error",
                "code": "media.linked_blip",
                "part": part,
                "detail": f"<a:blip r:link={link_val!r}/>",
            })
    return out


def _make_findings_sorted(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable sort findings for determinism. Sort key:
    (code, part-or-empty, detail)."""
    return sorted(
        findings,
        key=lambda f: (
            str(f.get("code", "")),
            str(f.get("part", "")),
            str(f.get("detail", "")),
        ),
    )


def build_inventory(pptx_path: Path) -> dict[str, Any]:
    """Build the deterministic inventory dict for `pptx_path`.

    Returns a dict that is JSON-serializable. The top-level `ok` field
    is True iff every fail-closed gate passed (no findings). Callers
    decide the exit code based on `ok`."""

    findings: list[dict[str, Any]] = []

    # 1. ZIP open.
    if not pptx_path.is_file():
        return {
            "ok": False,
            "evidence_basis": EVIDENCE_BASIS,
            "container": {
                "size_bytes": None,
                "sha256": None,
                "exists": False,
            },
            "slide_count": 0,
            "slides": [],
            "media_parts": [],
            "relationships": [],
            "findings": _make_findings_sorted([{
                "severity": "error",
                "code": "package.unreadable_zip",
                "part": str(pptx_path),
                "detail": "path does not exist or is not a regular file",
            }]),
        }

    raw_bytes = pptx_path.read_bytes()
    container = {
        "size_bytes": len(raw_bytes),
        "sha256": _sha256_bytes(raw_bytes),
        "exists": True,
    }

    try:
        zf = zipfile.ZipFile(pptx_path, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        findings.append({
            "severity": "error",
            "code": "package.unreadable_zip",
            "part": str(pptx_path),
            "detail": f"{type(exc).__name__}: {exc}",
        })
        return {
            "ok": False,
            "evidence_basis": EVIDENCE_BASIS,
            "container": container,
            "slide_count": 0,
            "slides": [],
            "media_parts": [],
            "relationships": [],
            "findings": _make_findings_sorted(findings),
        }

    try:
        names_set = set(zf.namelist())
        slide_parts = _iter_slide_parts(names_set)
        ct_defaults = _content_type_defaults(zf, names_set)
        if "[Content_Types].xml" in names_set and not ct_defaults:
            # _content_type_defaults swallows the exception so the
            # downstream gates still run with an empty defaults map;
            # we surface the unreadable-XML finding here explicitly.
            try:
                zf.read("[Content_Types].xml")
                ET.fromstring(zf.read("[Content_Types].xml"))
            except Exception as exc:
                findings.append({
                    "severity": "error",
                    "code": "package.unreadable_xml",
                    "part": "[Content_Types].xml",
                    "detail": f"{type(exc).__name__}: {exc}",
                })

        # 2. Relationships.
        rels_parts = _iter_rels_parts(names_set)
        all_rels, rel_parse_findings = _read_relationships(zf, rels_parts)
        findings.extend(rel_parse_findings)

        # 3. Per-rel target-safety findings + image-rel resolution map.
        # `image_rel_resolutions` maps (rels_part, rId) -> resolved
        # part name (or None if missing / unsafe). We use it later to
        # populate per-slide media_refs.
        image_rel_resolutions: dict[tuple[str, str], str | None] = {}
        for r in all_rels:
            target = r["target"]
            target_mode = r["target_mode"]
            rtype = r["type"]
            part = r["rels_part"]
            rid = r["id"]

            # external (TargetMode OR URI scheme).
            if isinstance(target_mode, str) and target_mode.lower() == "external":
                findings.append({
                    "severity": "error",
                    "code": "relationships.external",
                    "part": part,
                    "detail": (
                        f"rId={rid} TargetMode={target_mode!r} "
                        f"Target={target!r}"
                    ),
                })
            elif isinstance(target, str) and _URI_SCHEME_PREFIX.match(target):
                # A URI-scheme prefix without an explicit TargetMode is
                # still external by definition (the scheme makes it so).
                findings.append({
                    "severity": "error",
                    "code": "relationships.external",
                    "part": part,
                    "detail": f"rId={rid} Target={target!r} carries a URI scheme",
                })

            # file://
            if isinstance(target, str) and target.lower().startswith("file://"):
                findings.append({
                    "severity": "error",
                    "code": "relationships.file_uri",
                    "part": part,
                    "detail": f"rId={rid} Target={target!r}",
                })

            # absolute (leading "/", not the URI scheme cases above).
            if isinstance(target, str) and target.startswith("/"):
                findings.append({
                    "severity": "error",
                    "code": "relationships.absolute",
                    "part": part,
                    "detail": f"rId={rid} Target={target!r}",
                })

            # Image rel with missing or empty Target — fail closed
            # before the resolution path. The path-traversal block
            # below guards on `target` truthiness, so without this
            # explicit check an image rel that declares no Target at
            # all would be silently skipped by every downstream media
            # gate (image_rel_resolutions never gets a row for it,
            # and the media.missing loop only iterates that map).
            # Mirrors validate_pptx_contract.py's media.targets_internal
            # gate ("image rel missing Target") at the structured-
            # readback layer.
            if rtype == _REL_TYPE_IMAGE and (
                not isinstance(target, str) or not target
            ):
                findings.append({
                    "severity": "error",
                    "code": "media.missing",
                    "part": part,
                    "detail": (
                        f"rId={rid} image rel has missing or empty Target"
                    ),
                })

            # path traversal — resolve relative refs and check escape.
            # Only meaningful for non-absolute, non-URI Targets.
            if (
                isinstance(target, str)
                and target
                and not target.startswith("/")
                and not _URI_SCHEME_PREFIX.match(target)
            ):
                owner_dir = _rels_part_owner_dir(part)
                resolved = _posix_resolve(owner_dir, target)
                if resolved is None:
                    findings.append({
                        "severity": "error",
                        "code": "relationships.path_traversal",
                        "part": part,
                        "detail": (
                            f"rId={rid} Target={target!r} escapes the "
                            f"package root"
                        ),
                    })
                if rtype == _REL_TYPE_IMAGE:
                    image_rel_resolutions[(part, rid)] = resolved

        # 4. Media inventory — every image rel must resolve to a real
        # part; every ppt/media part must be referenced.
        referenced_media: dict[str, set[int]] = {}
        for (part, rid), resolved in image_rel_resolutions.items():
            if resolved is None:
                # Already reported as relationships.path_traversal.
                continue
            if not resolved.startswith("ppt/media/"):
                findings.append({
                    "severity": "error",
                    "code": "media.missing",
                    "part": part,
                    "detail": (
                        f"rId={rid} resolves to {resolved!r} (outside "
                        f"ppt/media/)"
                    ),
                })
                continue
            if resolved not in names_set:
                findings.append({
                    "severity": "error",
                    "code": "media.missing",
                    "part": part,
                    "detail": (
                        f"rId={rid} resolves to {resolved!r} which is "
                        f"not in the package"
                    ),
                })
                continue
            # Attribute to the slide that OWNS the rels file.
            owner_dir = _rels_part_owner_dir(part)
            slide_idx = None
            if owner_dir == "ppt/slides":
                # rels file name is `slideN.xml.rels`. Owner part name
                # is `slideN.xml`; the slide index is its trailing N.
                rels_basename = part.rsplit("/", 1)[-1]
                m = re.match(r"^slide(\d+)\.xml\.rels$", rels_basename)
                if m:
                    slide_idx = int(m.group(1))
            if slide_idx is not None:
                referenced_media.setdefault(resolved, set()).add(slide_idx)
            else:
                # Image rel under a master / layout / theme — still
                # referenced, just not attributed to a numeric slide.
                referenced_media.setdefault(resolved, set())

        on_disk_media = sorted(
            n for n in names_set
            if n.startswith("ppt/media/") and not n.endswith("/")
        )
        # orphan media — on-disk but no image rel references it.
        for m_part in on_disk_media:
            if m_part not in referenced_media:
                findings.append({
                    "severity": "error",
                    "code": "media.orphan",
                    "part": m_part,
                    "detail": (
                        "no image relationship references this part"
                    ),
                })

        # unsupported extension — every on-disk media part's extension
        # must be in the {png, jpg, jpeg} embed allow-list. This
        # mirrors validate_pptx_contract.py's media.inventory rule and
        # surfaces a clear finding rather than a generic gate failure.
        media_parts_out: list[dict[str, Any]] = []
        for m_part in on_disk_media:
            ext = m_part.rsplit(".", 1)[-1].lower() if "." in m_part else ""
            try:
                raw = zf.read(m_part)
                part_size = len(raw)
                part_sha = _sha256_bytes(raw)
            except Exception as exc:
                findings.append({
                    "severity": "error",
                    "code": "package.unreadable_xml",
                    "part": m_part,
                    "detail": (
                        f"read failed ({type(exc).__name__}: {exc})"
                    ),
                })
                part_size = None
                part_sha = None
            if ext not in _ALLOWED_MEDIA_EXTENSIONS:
                findings.append({
                    "severity": "error",
                    "code": "media.unsupported_extension",
                    "part": m_part,
                    "detail": (
                        f"extension {ext!r} is not in the "
                        f"embed allow-list "
                        f"{sorted(_ALLOWED_MEDIA_EXTENSIONS)}"
                    ),
                })
            declared_ct = ct_defaults.get(ext)
            expected_ct = _EXPECTED_CT_PER_EXT.get(ext)
            content_type = declared_ct if declared_ct is not None else None
            if (
                ext in _ALLOWED_MEDIA_EXTENSIONS
                and expected_ct is not None
                and declared_ct != expected_ct
            ):
                findings.append({
                    "severity": "error",
                    "code": "media.unsupported_extension",
                    "part": m_part,
                    "detail": (
                        f"extension {ext!r} not registered with "
                        f"ContentType={expected_ct!r} in "
                        f"[Content_Types].xml (found {declared_ct!r})"
                    ),
                })
            media_parts_out.append({
                "part": m_part,
                "size_bytes": part_size,
                "sha256": part_sha,
                "extension": ext,
                "content_type": content_type,
                "referencing_slides": sorted(
                    referenced_media.get(m_part, set())
                ),
            })

        # 5. Per-slide rows.
        slides_out: list[dict[str, Any]] = []
        # Track slide parts the slide-parse loop already flagged as
        # unreadable so the linked-blip walker below does not
        # double-count them.
        unreadable_parts: set[str] = set()
        for slide_part in slide_parts:
            counts, parse_findings = _slide_native_counts(zf, slide_part)
            findings.extend(parse_findings)
            for f in parse_findings:
                if f.get("code") == "package.unreadable_xml":
                    p = f.get("part")
                    if isinstance(p, str):
                        unreadable_parts.add(p)
            rids, rid_parse_findings = _slide_rids(zf, slide_part)
            # _slide_rids' findings would mirror the same parse error
            # _slide_native_counts already recorded. De-duplicate by
            # part: drop any rid parse-finding whose part already has
            # a native-counts parse-finding.
            existing_unreadable_parts = {
                f.get("part") for f in parse_findings
                if f.get("code") == "package.unreadable_xml"
            }
            findings.extend(
                f for f in rid_parse_findings
                if f.get("part") not in existing_unreadable_parts
            )

            # Per-slide media_refs from rels.
            slide_rels_part = (
                f"ppt/slides/_rels/{slide_part.rsplit('/', 1)[-1]}.rels"
            )
            media_refs_for_slide: list[dict[str, Any]] = []
            for r in all_rels:
                if r["rels_part"] != slide_rels_part:
                    continue
                if r["type"] != _REL_TYPE_IMAGE:
                    continue
                resolved = image_rel_resolutions.get(
                    (r["rels_part"], r["id"]),
                )
                media_refs_for_slide.append({
                    "r_id": r["id"],
                    "target": r["target"],
                    "resolved": resolved,
                    "used_by_slide_blip": r["id"] in rids,
                })
            media_refs_for_slide.sort(key=lambda x: str(x.get("r_id") or ""))

            # image-only evidence: pictures present but zero shapes /
            # connectors. Mirrors validate_pptx_contract.py's
            # minimal_evidence.not_all_image_slide rule.
            image_only = (
                counts["pictures_pic"] > 0
                and counts["shapes_sp"] == 0
                and counts["connectors_cxnSp"] == 0
            )
            if image_only:
                findings.append({
                    "severity": "error",
                    "code": "slide.image_only",
                    "part": slide_part,
                    "detail": (
                        "slide carries <p:pic> but no <p:sp> or "
                        "<p:cxnSp>; not editable per the existing "
                        "contract"
                    ),
                })

            slide_idx = _slide_index_from_part(slide_part)
            slides_out.append({
                "index": slide_idx,
                "part": slide_part,
                "native_object_counts": counts,
                "text_run_count": counts["text_runs"],
                "media_refs": media_refs_for_slide,
                "image_only_evidence": image_only,
            })
        # deterministic slide order: by part name (already sorted).

        # 6. Linked-blip walk over every ppt/*.xml part not in _rels/.
        # Mirrors validate_pptx_contract.py's media.embedded_only gate at
        # the structured-readback layer — a <a:blip r:link/> anywhere in
        # slides / slideMasters / slideLayouts / theme / presentation
        # asks PowerPoint to fetch a linked image at open time, so the
        # contract is no r:link anywhere. `unreadable_parts` deduplicates
        # slide parts the slide-parse loop already flagged.
        findings.extend(
            _collect_linked_blip_findings(zf, names_set, unreadable_parts)
        )

        # 7. Relationships out — sorted by (rels_part, id) for determinism.
        relationships_out = sorted(
            all_rels,
            key=lambda r: (str(r["rels_part"]), str(r["id"])),
        )
    finally:
        zf.close()

    inv: dict[str, Any] = {
        "ok": not findings,
        "evidence_basis": EVIDENCE_BASIS,
        "container": container,
        "slide_count": len(slides_out),
        "slides": slides_out,
        "media_parts": media_parts_out,
        "relationships": relationships_out,
        "findings": _make_findings_sorted(findings),
    }
    return inv


def render_inventory_json(inv: dict[str, Any]) -> str:
    """Return the canonical JSON string for `inv`. Determinism rule:
    sorted keys, two-space indent, no trailing whitespace, terminating
    newline."""
    return json.dumps(inv, indent=2, sort_keys=True) + "\n"


def _run_self_test() -> int:
    """Build temp-fixture .pptx packages and confirm build_inventory
    produces the expected findings / counts.

    Coverage (17 scenarios, in execution order):
      1. happy path (one PNG, one editable slide; ok=True).
      2. deterministic repeated inventory (two runs yield byte-identical
         JSON for the same input).
      3. image-only slide fails closed on `slide.image_only`.
      4. missing media (image rel resolves to a part not on disk)
         fails closed on `media.missing`.
      5. image rel with NO `Target` attribute fails closed on
         `media.missing` — the path-traversal block guards on
         `target` truthiness, so without the explicit missing-Target
         check an image rel that declares no Target at all would
         silently pass every downstream media gate.
      6. orphan media (ppt/media part with no referencing image rel)
         fails closed on `media.orphan`.
      7. external relationship (`TargetMode="External"` + URI scheme)
         fails closed on `relationships.external`.
      8. `file://` relationship fails closed on both
         `relationships.file_uri` AND `relationships.external` (the
         scheme prefix is the external dimension).
      9. absolute-path relationship (leading `/`) fails closed on
         `relationships.absolute`.
     10. path-traversal relationship (`..` segments escape the
         package root) fails closed on `relationships.path_traversal`.
     11. bad XML at a slide part fails closed on
         `package.unreadable_xml`.
     12. unsupported media extension (`ppt/media/image1.gif`) fails
         closed on `media.unsupported_extension`.
     13. linked-blip `<a:blip r:link="rIdL"/>` in a slide fails closed
         on `media.linked_blip` (closes the same surface
         validate_pptx_contract.py's media.embedded_only gate refuses).
     14. unparseable XML in a non-slide part under `ppt/` (here
         ppt/theme/theme1.xml) fails closed on `package.unreadable_xml`
         from the linked-blip walker (the walker cannot rule out a
         buried r:link in malformed XML, so a fail-open continue would
         silently bypass the contract).
     15. unreadable ZIP (non-ZIP bytes at a `.pptx` path) fails closed
         on `package.unreadable_zip`.
     16. nonexistent file (`--pptx` path that does not exist) fails
         closed on `package.unreadable_zip` (the build_inventory entry
         emits the synthetic finding when `Path.is_file()` is False).
     17. external image rel placed at the PACKAGE-level rels file
         (`ppt/_rels/presentation.xml.rels`) surfaces a
         `relationships.external` finding pinned to that part —
         defense in depth for the embedded-only contract, proving
         the walker iterates every `*.rels` member in the package
         (not only slide-level rels). Mirrors the analogous
         validate_pptx_contract scenario.

    Each scenario asserts an expected finding code is present OR (for
    the happy path / determinism case) that no findings exist.
    """
    import tempfile

    scenarios: list[tuple[str, bool]] = []  # (name, ok)
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)

        # ---- happy path ----
        happy = td / "happy.pptx"
        _write_minimal_editable_with_png(happy)
        inv = build_inventory(happy)
        ok = inv["ok"] is True and not inv["findings"]
        scenarios.append(("happy path", ok))
        if not ok:
            failures.append(
                f"happy path: ok={inv['ok']}, findings={inv['findings']}"
            )
        else:
            # Spot-check structural fields the JSON contract commits to.
            if inv["slide_count"] != 1:
                failures.append(
                    f"happy path: expected slide_count=1, got "
                    f"{inv['slide_count']}"
                )
            if len(inv["media_parts"]) != 1:
                failures.append(
                    f"happy path: expected 1 media_part, got "
                    f"{len(inv['media_parts'])}"
                )
            mp = inv["media_parts"][0]
            if (
                mp["extension"] != "png"
                or mp["content_type"] != "image/png"
                or mp["referencing_slides"] != [1]
                or not isinstance(mp["sha256"], str)
                or len(mp["sha256"]) != 64
            ):
                failures.append(
                    f"happy path: media_part fields wrong: {mp}"
                )
            counts = inv["slides"][0]["native_object_counts"]
            if (
                counts["shapes_sp"] < 1
                or counts["pictures_pic"] != 1
                or counts["text_runs"] < 1
            ):
                failures.append(
                    f"happy path: per-slide counts unexpected: {counts}"
                )

        # ---- deterministic repeated inventory ----
        first = render_inventory_json(build_inventory(happy))
        second = render_inventory_json(build_inventory(happy))
        det_ok = first == second
        scenarios.append(("deterministic repeated inventory", det_ok))
        if not det_ok:
            # First 200 chars from each for the report.
            failures.append(
                "deterministic: outputs differ between two runs"
            )

        # ---- image-only slide failure ----
        img_only = td / "image_only.pptx"
        _write_minimal_pptx_with_slides(
            img_only,
            slide_bodies=[_PIC_ONLY_BODY],
        )
        inv = build_inventory(img_only)
        codes = [f["code"] for f in inv["findings"]]
        scn_ok = ("slide.image_only" in codes) and inv["ok"] is False
        scenarios.append(("image-only slide failure", scn_ok))
        if not scn_ok:
            failures.append(
                f"image-only: codes={codes}, ok={inv['ok']}"
            )

        # ---- missing media ----
        missing = td / "missing_media.pptx"
        _write_minimal_pptx_with_slides(
            missing,
            slide_bodies=[_EDITABLE_BODY],
            extra_entries={
                "ppt/slides/_rels/slide1.xml.rels": (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns='
                    '"http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rIdImg" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/image" '
                    'Target="../media/missing.png"/>'
                    '</Relationships>'
                ),
            },
        )
        inv = build_inventory(missing)
        codes = [f["code"] for f in inv["findings"]]
        scn_ok = ("media.missing" in codes) and inv["ok"] is False
        scenarios.append(("missing media", scn_ok))
        if not scn_ok:
            failures.append(f"missing media: codes={codes}, ok={inv['ok']}")

        # ---- image rel with NO Target attribute ----
        # Without an explicit missing-Target check the rel would fall
        # off every downstream media gate: the path-traversal block
        # guards on `target` truthiness, so image_rel_resolutions
        # never gets a row for it, and the media.missing loop only
        # iterates that map. The fix emits a media.missing finding at
        # the relationship-walk time. The rels XML below declares the
        # rel WITHOUT a Target attribute at all.
        no_target = td / "image_rel_no_target.pptx"
        _write_minimal_pptx_with_slides(
            no_target,
            slide_bodies=[_EDITABLE_BODY],
            extra_entries={
                "ppt/slides/_rels/slide1.xml.rels": (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns='
                    '"http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rIdNoTarget" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/image"/>'
                    '</Relationships>'
                ),
            },
        )
        inv = build_inventory(no_target)
        codes = [f["code"] for f in inv["findings"]]
        details = "; ".join(
            f.get("detail", "") for f in inv["findings"]
            if f.get("code") == "media.missing"
        )
        scn_ok = (
            "media.missing" in codes
            and "missing or empty Target" in details
            and inv["ok"] is False
        )
        scenarios.append(("image rel with missing Target", scn_ok))
        if not scn_ok:
            failures.append(
                f"missing Target: codes={codes}, details={details!r}, "
                f"ok={inv['ok']}"
            )

        # ---- orphan media ----
        orphan = td / "orphan_media.pptx"
        _write_minimal_pptx_with_slides(
            orphan,
            slide_bodies=[_EDITABLE_BODY],
            extra_entries={
                "ppt/media/orphan.png": _PNG_BYTES,
            },
            ct_defaults_extra={"png": "image/png"},
        )
        inv = build_inventory(orphan)
        codes = [f["code"] for f in inv["findings"]]
        scn_ok = ("media.orphan" in codes) and inv["ok"] is False
        scenarios.append(("orphan media", scn_ok))
        if not scn_ok:
            failures.append(f"orphan media: codes={codes}, ok={inv['ok']}")

        # ---- external rel ----
        external = td / "external.pptx"
        _write_minimal_pptx_with_slides(
            external,
            slide_bodies=[_EDITABLE_BODY],
            extra_entries={
                "ppt/slides/_rels/slide1.xml.rels": (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns='
                    '"http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rIdExt" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/hyperlink" '
                    'Target="https://example.invalid/" '
                    'TargetMode="External"/>'
                    '</Relationships>'
                ),
            },
        )
        inv = build_inventory(external)
        codes = [f["code"] for f in inv["findings"]]
        scn_ok = ("relationships.external" in codes) and inv["ok"] is False
        scenarios.append(("external relationship", scn_ok))
        if not scn_ok:
            failures.append(f"external rel: codes={codes}, ok={inv['ok']}")

        # ---- file:// rel ----
        file_uri = td / "file_uri.pptx"
        _write_minimal_pptx_with_slides(
            file_uri,
            slide_bodies=[_EDITABLE_BODY],
            extra_entries={
                "ppt/slides/_rels/slide1.xml.rels": (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns='
                    '"http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rIdF" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/image" '
                    'Target="file:///tmp/x.png"/>'
                    '</Relationships>'
                ),
            },
        )
        inv = build_inventory(file_uri)
        codes = [f["code"] for f in inv["findings"]]
        scn_ok = (
            "relationships.file_uri" in codes
            and "relationships.external" in codes
            and inv["ok"] is False
        )
        scenarios.append(("file:// relationship", scn_ok))
        if not scn_ok:
            failures.append(f"file:// rel: codes={codes}, ok={inv['ok']}")

        # ---- absolute path rel ----
        absolute = td / "absolute.pptx"
        _write_minimal_pptx_with_slides(
            absolute,
            slide_bodies=[_EDITABLE_BODY],
            extra_entries={
                "ppt/slides/_rels/slide1.xml.rels": (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns='
                    '"http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rIdA" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/image" '
                    'Target="/etc/passwd"/>'
                    '</Relationships>'
                ),
            },
        )
        inv = build_inventory(absolute)
        codes = [f["code"] for f in inv["findings"]]
        scn_ok = ("relationships.absolute" in codes) and inv["ok"] is False
        scenarios.append(("absolute path relationship", scn_ok))
        if not scn_ok:
            failures.append(f"absolute rel: codes={codes}, ok={inv['ok']}")

        # ---- path-traversal rel ----
        traversal = td / "traversal.pptx"
        _write_minimal_pptx_with_slides(
            traversal,
            slide_bodies=[_EDITABLE_BODY],
            extra_entries={
                "ppt/slides/_rels/slide1.xml.rels": (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns='
                    '"http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rIdT" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/image" '
                    'Target="../../../../etc/passwd"/>'
                    '</Relationships>'
                ),
            },
        )
        inv = build_inventory(traversal)
        codes = [f["code"] for f in inv["findings"]]
        scn_ok = (
            "relationships.path_traversal" in codes
            and inv["ok"] is False
        )
        scenarios.append(("path-traversal relationship", scn_ok))
        if not scn_ok:
            failures.append(
                f"path-traversal rel: codes={codes}, ok={inv['ok']}"
            )

        # ---- bad XML in slide part ----
        bad_xml = td / "bad_xml.pptx"
        _write_minimal_pptx_with_slides(
            bad_xml,
            slide_bodies=[None],  # sentinel: write raw "<not-xml" instead
        )
        inv = build_inventory(bad_xml)
        codes = [f["code"] for f in inv["findings"]]
        scn_ok = ("package.unreadable_xml" in codes) and inv["ok"] is False
        scenarios.append(("bad XML slide part", scn_ok))
        if not scn_ok:
            failures.append(f"bad XML: codes={codes}, ok={inv['ok']}")

        # ---- unsupported media extension ----
        bad_ext = td / "bad_ext.pptx"
        _write_minimal_pptx_with_slides(
            bad_ext,
            slide_bodies=[_EDITABLE_BODY],
            extra_entries={
                "ppt/media/image1.gif": b"GIF89a;",
                "ppt/slides/_rels/slide1.xml.rels": (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns='
                    '"http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rIdG" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/image" '
                    'Target="../media/image1.gif"/>'
                    '</Relationships>'
                ),
            },
        )
        inv = build_inventory(bad_ext)
        codes = [f["code"] for f in inv["findings"]]
        scn_ok = (
            "media.unsupported_extension" in codes
            and inv["ok"] is False
        )
        scenarios.append(("unsupported media extension", scn_ok))
        if not scn_ok:
            failures.append(
                f"unsupported media ext: codes={codes}, ok={inv['ok']}"
            )

        # ---- linked-blip in slide content ----
        # The slide carries an editable text shape AND a <p:pic> whose
        # <a:blip> uses `r:link` (not `r:embed`). The rels file is
        # left untouched so every relationships.* / media.* gate stays
        # green — only the per-<a:blip> inspection catches the linked
        # form. Mirrors validate_pptx_contract.py's analogous fixture.
        linked_blip = td / "linked_blip.pptx"
        pic_with_link = (
            '<p:pic>'
            '<p:nvPicPr>'
            '<p:cNvPr id="9" name="linked"/>'
            '<p:cNvPicPr/>'
            '<p:nvPr/>'
            '</p:nvPicPr>'
            '<p:blipFill><a:blip r:link="rIdL"/></p:blipFill>'
            '<p:spPr><a:xfrm><a:off x="0" y="0"/>'
            '<a:ext cx="100" cy="100"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
            '</p:pic>'
        )
        _write_minimal_pptx_with_slides(
            linked_blip,
            slide_bodies=[_EDITABLE_BODY + pic_with_link],
        )
        inv = build_inventory(linked_blip)
        codes = [f["code"] for f in inv["findings"]]
        scn_ok = ("media.linked_blip" in codes) and inv["ok"] is False
        scenarios.append(("linked-blip in slide content", scn_ok))
        if not scn_ok:
            failures.append(
                f"linked blip: codes={codes}, ok={inv['ok']}"
            )

        # ---- unparseable XML in a non-slide part ----
        # Slides parse cleanly; ppt/theme/theme1.xml is garbage. The
        # linked-blip walker must surface `package.unreadable_xml` for
        # the theme part — a fail-open continue would silently bypass
        # the contract (a buried r:link in malformed XML would be
        # invisible). The deduplication against slide-parse failures
        # only suppresses the slide path; non-slide parts MUST emerge.
        bad_theme = td / "bad_theme_xml.pptx"
        _write_minimal_pptx_with_slides(
            bad_theme,
            slide_bodies=[_EDITABLE_BODY],
            extra_entries={
                "ppt/theme/theme1.xml": "<not-xml",
            },
        )
        inv = build_inventory(bad_theme)
        theme_unreadable = any(
            f.get("code") == "package.unreadable_xml"
            and f.get("part") == "ppt/theme/theme1.xml"
            for f in inv["findings"]
        )
        scn_ok = theme_unreadable and inv["ok"] is False
        scenarios.append((
            "unparseable XML in a non-slide ppt/ part", scn_ok,
        ))
        if not scn_ok:
            failures.append(
                f"bad theme XML: codes/parts="
                f"{[(f.get('code'), f.get('part')) for f in inv['findings']]}, "
                f"ok={inv['ok']}"
            )

        # ---- unreadable ZIP (not a real ZIP file) ----
        bad_zip = td / "not_a_zip.pptx"
        bad_zip.write_text("this is plain text, not a zip")
        inv = build_inventory(bad_zip)
        codes = [f["code"] for f in inv["findings"]]
        scn_ok = ("package.unreadable_zip" in codes) and inv["ok"] is False
        scenarios.append(("unreadable ZIP", scn_ok))
        if not scn_ok:
            failures.append(f"unreadable ZIP: codes={codes}, ok={inv['ok']}")

        # ---- nonexistent file ----
        nope = td / "nope.pptx"
        inv = build_inventory(nope)
        codes = [f["code"] for f in inv["findings"]]
        scn_ok = ("package.unreadable_zip" in codes) and inv["ok"] is False
        scenarios.append(("nonexistent file", scn_ok))
        if not scn_ok:
            failures.append(
                f"nonexistent file: codes={codes}, ok={inv['ok']}"
            )

        # ---- external image rel at package-level rels ----
        # An `image`-typed rel placed at the PACKAGE-level rels
        # file (`ppt/_rels/presentation.xml.rels`) with
        # TargetMode="External" and an https:// Target must
        # surface a `relationships.external` finding. Scenario 7
        # exercises the same gate at slide rels level; this
        # scenario proves the walker iterates every `*.rels`
        # member in the package — defense in depth for the
        # embedded-only contract, mirroring the analogous
        # validate_pptx_contract scenario.
        pkg_external = td / "pkg_external_image_rel.pptx"
        _write_minimal_pptx_with_slides(
            pkg_external,
            slide_bodies=[_EDITABLE_BODY],
            extra_entries={
                "ppt/_rels/presentation.xml.rels": (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns='
                    '"http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rIdExtImg" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/image" '
                    'Target="https://attacker.invalid/leaked.png" '
                    'TargetMode="External"/>'
                    '</Relationships>'
                ),
            },
        )
        inv = build_inventory(pkg_external)
        offender_parts = [
            f.get("part") for f in inv["findings"]
            if f.get("code") == "relationships.external"
        ]
        scn_ok = (
            "ppt/_rels/presentation.xml.rels" in offender_parts
            and inv["ok"] is False
        )
        scenarios.append((
            "external image rel at package-level rels", scn_ok,
        ))
        if not scn_ok:
            failures.append(
                f"package-level external rel: "
                f"offender_parts={offender_parts}, ok={inv['ok']}"
            )

    print("self-test scenarios:")
    for name, ok in scenarios:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if failures:
        print()
        print(f"FAIL: {len(failures)} scenario(s) did not pass:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print()
    print(
        f"OK (self-test): {len(scenarios)} scenarios passed. "
        f"This inventory is evidence from the OOXML structure only; "
        f"it does NOT prove full PowerPoint editability."
    )
    return 0


# --- Self-test fixtures -----------------------------------------------------


# Minimal PNG magic bytes; the inventory does not validate image
# contents beyond size + sha + extension, so a magic-byte stub is
# enough to exercise the read path.
_PNG_BYTES = bytes([
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
])


_EDITABLE_BODY = (
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


_PIC_ONLY_BODY = (
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


def _write_minimal_pptx_with_slides(
    path: Path,
    *,
    slide_bodies: list[str | None],
    extra_entries: dict[str, str | bytes] | None = None,
    ct_defaults_extra: dict[str, str] | None = None,
) -> None:
    """Write a minimal PPTX whose slides carry the supplied spTree
    bodies. A None entry in `slide_bodies` writes raw "<not-xml" at
    that slide path (exercises the unreadable-XML fail-closed path).

    The fixture is intentionally hand-rolled — building it via the
    real exporter would make the self-test depend on exporter
    correctness, which is the very thing the readback inventory must
    cross-check."""
    extra_entries = extra_entries or {}
    ct_defaults_extra = ct_defaults_extra or {}
    n_slides = len(slide_bodies)
    pres = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<p:sldIdLst>'
        + "".join(
            f'<p:sldId id="{256 + i}" r:id="rId{i + 1}"/>'
            for i in range(n_slides)
        )
        + '</p:sldIdLst>'
        '</p:presentation>'
    )
    defaults_xml = (
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
    )
    for ext, ct in sorted(ct_defaults_extra.items()):
        defaults_xml += f'<Default Extension="{ext}" ContentType="{ct}"/>'

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            + defaults_xml
            + '<Override PartName="/ppt/presentation.xml" '
              'ContentType="application/vnd.openxmlformats-officedocument.'
              'presentationml.presentation.main+xml"/>'
            + "".join(
                f'<Override PartName="/ppt/slides/slide{i + 1}.xml" '
                f'ContentType="application/vnd.openxmlformats-officedocument.'
                f'presentationml.slide+xml"/>'
                for i in range(n_slides)
            )
            + '</Types>'
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
        zf.writestr("ppt/presentation.xml", pres)
        for i, body in enumerate(slide_bodies, start=1):
            slide_path = f"ppt/slides/slide{i}.xml"
            if body is None:
                # Write garbage so the parser fails closed.
                zf.writestr(slide_path, "<not-xml")
                continue
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
            zf.writestr(slide_path, slide_doc)
        for name, payload in extra_entries.items():
            if isinstance(payload, bytes):
                zf.writestr(name, payload)
            else:
                zf.writestr(name, payload)


def _write_minimal_editable_with_png(path: Path) -> None:
    """Write a minimal one-slide PPTX whose slide carries an editable
    text shape AND a <p:pic> referencing ppt/media/image1.png via a
    <a:blip r:embed="rId1"/>. Used by the happy-path self-test
    scenario."""
    pic_with_embed = (
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
    _write_minimal_pptx_with_slides(
        path,
        slide_bodies=[_EDITABLE_BODY + pic_with_embed],
        extra_entries={
            "ppt/media/image1.png": _PNG_BYTES,
            "ppt/slides/_rels/slide1.xml.rels": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns='
                '"http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                'relationships/image" '
                'Target="../media/image1.png"/>'
                '</Relationships>'
            ),
        },
        ct_defaults_extra={"png": "image/png"},
    )


def _validate_out_path(out: Path) -> str | None:
    """Refuse a --out path that is a symlink (we never silently follow
    one) or that already exists as a non-regular file. Returns an
    error message or None."""
    if out.is_symlink():
        return (
            f"--out path {out} is a symlink; refused so the inventory "
            f"writer never follows a link to an unrelated target"
        )
    if out.exists() and not out.is_file():
        return (
            f"--out path {out} already exists and is not a regular file"
        )
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read a .pptx ZIP and emit a deterministic JSON inventory "
            "of slide count, per-slide native object counts, media "
            "relationships, embedded media parts (size + sha256 + "
            "extension + content type + referencing slides), the full "
            "relationship list sorted by (rels_part, id), and "
            "findings for external / file:// / absolute / "
            "path-traversal relationship targets, missing-or-"
            "unresolvable media (including image rels with a missing "
            "or empty Target attribute), orphan media, unsupported "
            "media extensions, image-only slides, "
            "`<a:blip r:link=\"...\"/>` linked-image references "
            "anywhere in slides / slideMasters / slideLayouts / theme "
            "/ presentation (same surface "
            "validate_pptx_contract.py's media.embedded_only gate "
            "refuses), and unreadable ZIP / XML parts (slide parts "
            "plus the non-_rels/ XML parts under ppt/ traversed by "
            "the linked-blip walker). Inspection only: the script "
            "reports evidence from the OOXML structure, never claims "
            "full PowerPoint editability, and never calls any network."
        ),
    )
    parser.add_argument(
        "--pptx",
        type=Path,
        default=None,
        help="Path to the .pptx file to inspect.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Optional path to write the inventory JSON to. When omitted, "
            "the JSON is written to stdout. The path may not be a "
            "symlink; an existing non-regular-file at the path is "
            "refused."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run the in-script tempfixture scenarios (17 today): "
            "happy path, deterministic repeated inventory, image-only "
            "slide failure, missing media (image rel resolves to a "
            "part not on disk), image rel with NO Target attribute "
            "(without the explicit check the rel would fall off every "
            "downstream media gate — the path-traversal block guards "
            "on `target` truthiness, so a missing or empty Target "
            "would never reach the resolution map), orphan media, "
            "external relationship, file:// relationship, absolute "
            "relationship, path-traversal relationship, bad XML in a "
            "slide part, unsupported media extension, linked-blip "
            "`<a:blip r:link=\"rIdL\"/>` in slide content (the "
            "slide-side rels file is left untouched so every "
            "relationships.* / media.* gate stays green — only the "
            "per-`<a:blip>` walk fires media.linked_blip), unparseable "
            "XML in a non-slide ppt/ part (`ppt/theme/theme1.xml`) "
            "surfaced via the linked-blip walker as "
            "package.unreadable_xml (no fail-open continue — a buried "
            "r:link in malformed XML would otherwise be invisible), "
            "unreadable ZIP, nonexistent file, and an external image "
            "rel placed at the PACKAGE-level rels file "
            "(`ppt/_rels/presentation.xml.rels`) — defense in depth "
            "proving the walker iterates every `*.rels` member, not "
            "only slide-level rels."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return _run_self_test()

    if args.pptx is None:
        print(
            "FAIL: --pptx is required unless --self-test is supplied.",
            file=sys.stderr,
        )
        return 2

    if args.out is not None:
        err = _validate_out_path(args.out)
        if err is not None:
            print(f"FAIL: {err}", file=sys.stderr)
            return 2

    inv = build_inventory(args.pptx)
    rendered = render_inventory_json(inv)
    if args.out is not None:
        args.out.write_text(rendered)
    else:
        sys.stdout.write(rendered)
    return 0 if inv["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
