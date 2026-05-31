#!/usr/bin/env python3
"""Source-document -> image-request bridge (MOCK / LOCAL only).

This is the first front-end bridge for the report/doc-to-editable-PPT
MVP. It takes a simple Markdown source file and produces a deterministic
**image request plan** (``image_request_plan.json``): one image request
per ATX heading, each carrying SYNTHETIC-SAFE per-slide metadata
(``slide_title`` / ``alt_text`` / ``image_descriptor`` / ``placement_role``
/ ``intended_use``) plus structural traceability back to the heading
(level + ordinal). It can then perform a MOCK / LOCAL handoff that
writes a byte-distinct placeholder PNG per request PLUS a plan-derived
operator bundle (``manifest.json`` + ``generated_provenance.json``) and
feeds that bundle into the EXISTING operator image-to-editable-PPT lane
(``--bundle``), producing a validated review package with an editable
``deck.pptx`` whose slide titles / alt text / role-aware layouts
(``hero_page`` -> ``cover``, ``local_region`` -> ``section_divider``)
reflect the image request plan, plus per-image provenance.

What this is NOT:

  * NOT real image generation. No D-One, no model API, no image search,
    no public network, no telemetry. The placeholder PNGs are tiny
    locally-synthesised raster bytes; ``real_image_generation_status``
    is pinned to a NOT_PERFORMED sentence.
  * NOT full report-to-PPT automation. It does not read the source body
    for business content; it derives image requests from headings only
    and NEVER copies raw source body text into the plan or the deck.
  * NOT a new export/render engine. The handoff only drives the existing
    ``operator_local_images_to_editable_ppt.py`` + re-validates with
    ``validate_operator_review_package.py``.

Synthetic-safety: the whole source is scanned (case-insensitive) for
credential / public-network / file-URI / absolute-path wording AND for
credential VALUE shapes (AWS keys, PEM private-key blocks, bearer /
key=value secrets, via the shared verify_skill_package.CREDENTIAL_PATTERNS
detector) before any artifact is produced; any hit fails the run closed.
The values that flow downstream (the source filename and every heading
title) are re-scanned AFTER sanitisation, and that emitted-value gate is
the UNION of this bridge's deny-list, the credential-shape detector, AND
the operator lane's own _safe_manifest_string contract — so the bridge's
safety gate is provably no weaker than the operator review-package
contract (it inherits the operator's OpenAI-key / upload-share-hosting /
social-media / public-share-regex / confidential-customer / positive-
real-service-claim gates), and a crafted heading cannot assemble a denied
token past the raw scan via character stripping ("api*key" -> "apikey").

CLI shape::

    # Plan only: parse Markdown -> image_request_plan.json
    python3 scripts/source_to_image_requests.py \\
        --source REPORT.md --plan-out PLAN.json

    # Mock/local handoff: plan + placeholder images -> review package
    python3 scripts/source_to_image_requests.py \\
        --source REPORT.md --mock-handoff --out-dir OUT   # OUT outside repo

    # Self-test (every scenario under TMPDIR; nothing leaks under repo)
    python3 scripts/source_to_image_requests.py --self-test

``--out-dir`` is validated through
``core_image_to_editable_ppt_demo._validate_out_dir_arg`` so the same
URI / symlink / symlink-ancestor / repo-tree / non-empty refusals the
sibling helpers enforce apply here too.

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
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import struct  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import zlib  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMA_PATH = REPO_ROOT / "schemas" / "image_request_plan.schema.json"

sys.path.insert(0, str(SCRIPTS_DIR))

# Reuse the helper's own out-dir gate so this bridge cannot diverge from
# the contract the sibling helpers enforce, and the subset schema
# validator so the plan is validated against the committed schema.
from core_image_to_editable_ppt_demo import (  # noqa: E402
    _validate_out_dir_arg,
)
from validate_artifacts import _validate as _schema_validate  # noqa: E402
# Reuse the repo's canonical credential-VALUE shape detector (AWS keys,
# PEM private-key blocks, bearer tokens, key=value secrets) so this
# bridge's credential gate cannot drift from the package verifier's.
from verify_skill_package import CREDENTIAL_PATTERNS  # noqa: E402
# Reuse the operator lane's OWN free-text gate so this bridge's
# downstream-value safety contract is provably no weaker than the
# operator review-package contract (URL / URI / path-sep / OpenAI key /
# upload-share-hosting wording / social-media channels / public-share
# regex / confidential-customer markers / positive-real-service claims).
from operator_local_images_to_editable_ppt import (  # noqa: E402
    _MAX_ALT_TEXT_LEN,
    _MAX_INTENDED_USE_LEN,
    _MAX_SLIDE_TITLE_LEN,
    _safe_manifest_string,
)

OPERATOR_HELPER = SCRIPTS_DIR / "operator_local_images_to_editable_ppt.py"
PACKAGE_VALIDATOR = SCRIPTS_DIR / "validate_operator_review_package.py"

MAX_HEADINGS = 200
MAX_SOURCE_BYTES = 64 * 1024 * 1024

# Fixed framing strings echoed into the plan + README.
_BOUNDARY = (
    "Local-only mock bridge. Does NOT call D-One, MCP, Qoder, a public "
    "network, telemetry, a model API, an image search, or any external "
    "service. NOT full report-to-PPT automation."
)
_REAL_IMAGE_STATUS = (
    "NOT_PERFORMED: no real image generator produced these requests' "
    "pixels. The --mock-handoff placeholders are tiny locally-synthesised "
    "raster bytes; real D-One / model-API image generation remains "
    "UNVERIFIED and out of scope for this bridge."
)

# ---------------------------------------------------------------------------
# Source safety scan. High-signal, case-insensitive substring deny-list
# covering credential / public-network / file-URI / absolute-path /
# telemetry wording. A superset of the operator manifest's denied
# substrings so nothing that the downstream manifest gate would refuse
# can ride a heading into the deck.
# ---------------------------------------------------------------------------

# fmt: off
_DENIED_SOURCE_SUBSTRINGS: tuple[str, ...] = (
    # Credentials / secrets.
    "password", "passwd", "secret", "api_key", "apikey", "api key",
    "bearer ", "ssh-rsa", "-----begin", "private key", "client_secret",
    "access_key", "auth_token",
    # Public-network / URL / dangerous URI schemes.
    "http://", "https://", "ftp://", "file://", "data:", "javascript:",
    "://", "www.",
    # Public upload / sharing / hosting wording, including body text
    # that is not emitted into headings but still conflicts with the
    # bridge's local-only source boundary.
    "public upload", "upload to public", "public bucket",
    "share publicly", "public hosting", "host publicly",
    "public hosted", "cloud-hosted",
    # Positive external-service / model-call claims.
    "model api call", "called model api", "image search returned",
    "called image search", "public network call", "mcp call succeeded",
    "called mcp", "called qoder", "qoder run succeeded",
    "telemetry emitted", "telemetry sent",
    # Cloud object-store / remote-service hints.
    "s3://", "gs://", "gcs://",
    # Absolute / machine-local path shapes.
    "/users/", "/home/", "/etc/", "/var/", "/private/", "c:\\",
    # Telemetry / exfil verbs.
    "telemetry", "exfil", "beacon",
)
# fmt: on


def _scan_source_safety(text: str) -> list[str]:
    """Return a list of human-readable failures for unsafe wording. Empty
    list means the source passed. Each failure names the offending token
    and the 1-based line it first appears on."""
    failures: list[str] = []
    lowered_lines = [line.lower() for line in text.splitlines()]
    for token in _DENIED_SOURCE_SUBSTRINGS:
        for lineno, line in enumerate(lowered_lines, start=1):
            if token in line:
                failures.append(
                    f"unsafe wording {token!r} at line {lineno}; the source "
                    f"bridge is local-only and refuses credential / "
                    f"public-network / file-URI / absolute-path wording"
                )
                break  # one report per token is enough
    # Credential VALUE shapes the keyword substrings above do not cover
    # (e.g. an AWS key id or a bearer token carried verbatim in a heading
    # or body line).
    for label, pat in CREDENTIAL_PATTERNS:
        m = pat.search(text)
        if m is not None:
            lineno = text[: m.start()].count("\n") + 1
            failures.append(
                f"credential shape {label!r} at line {lineno}; the source "
                f"bridge is local-only and refuses embedded credential "
                f"material"
            )
    return failures


def _scan_emitted_value(label: str, value: str) -> list[str]:
    """Scan a value that flows downstream (filename / sanitised title) for
    unsafe content. Title sanitisation strips characters ('*', '_',
    backticks, control chars) and collapses whitespace, so it can ASSEMBLE
    a denied token that was absent from the raw bytes (e.g. 'api*key' ->
    'apikey'). This post-transformation scan closes that bypass.

    Three layers, unioned so the bridge's emitted-value gate is provably
    no weaker than the operator review-package contract:

      1. this bridge's raw-source substring deny-list (adds bare tokens
         like 'secret' that the operator list does not carry);
      2. the shared credential VALUE-shape detector (AWS / PEM / JWT /
         bearer / key=value);
      3. the operator lane's OWN ``_safe_manifest_string`` gate (OpenAI
         sk- keys, upload / share / public-hosting wording, social-media
         channels, the 22-shape public-share regex, confidential /
         customer markers, positive-real-service claims, URL / URI /
         path-separator shapes)."""
    lowered = value.lower()
    failures = [
        f"unsafe wording {token!r} in {label} ({value!r}); refused after "
        f"title sanitisation (would smuggle credential / public-network / "
        f"file-URI / absolute-path wording into the plan/deck)"
        for token in _DENIED_SOURCE_SUBSTRINGS
        if token in lowered
    ]
    # Credential VALUE shapes (AWS keys, PEM blocks, bearer / key=value
    # secrets) assembled into the emitted value by sanitisation.
    for clabel, pat in CREDENTIAL_PATTERNS:
        if pat.search(value) is not None:
            failures.append(
                f"credential shape {clabel!r} in {label} ({value!r}); "
                f"refused after title sanitisation"
            )
    # Operator review-package contract — the single source of truth for
    # what free text may ride into the deck. A high max_len is passed so
    # only the operator's CONTENT gates fire here; per-field length is
    # enforced separately by the plan schema.
    _, op_failure = _safe_manifest_string(
        field=label, value=value, max_len=4096, entry_idx=0,
    )
    if op_failure is not None:
        failures.append(
            f"operator contract refused {label} ({value!r}): {op_failure}"
        )
    return failures


# ---------------------------------------------------------------------------
# Markdown heading parsing.
# ---------------------------------------------------------------------------

_ATX_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
# Inside a fenced code block ``` / ~~~ a '#' line is a comment, not a
# heading; the parser skips fenced regions.
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")


@dataclass
class _Heading:
    level: int
    text: str
    ordinal: int  # 1-based across all discovered headings


def _parse_headings(text: str) -> list[_Heading]:
    headings: list[_Heading] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _ATX_RE.match(line)
        if not m:
            continue
        level = len(m.group(1))
        raw = m.group(2).strip()
        title = _sanitise_title(raw)
        if not title:
            continue
        headings.append(
            _Heading(level=level, text=title, ordinal=len(headings) + 1)
        )
    return headings


_MD_STRIP_RE = re.compile(r"[*_`]+")
_PATHSEP_RE = re.compile(r"[\\/]+")
_WS_RE = re.compile(r"\s+")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _sanitise_title(raw: str) -> str:
    """Collapse whitespace, drop Markdown emphasis markers + control
    chars, replace path separators with a space, and cap length.
    Non-ASCII (e.g. CJK) is preserved. The source safety scan has
    already refused credential / network / path wording; path separators
    are normalised to a space so a benign heading like 'TCP/IP overview'
    does not trip the operator gate's path-separator rule while no '/'
    or '\\' ever reaches the emitted deck text."""
    text = _MD_STRIP_RE.sub("", raw)
    text = _CTRL_RE.sub("", text)
    text = _PATHSEP_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    # Cap at the operator contract's own slide_title limit so the emitted
    # slide_title — and the alt_text / image_descriptor composed from it —
    # never exceed the lengths the operator review-package gate enforces.
    if len(text) > _MAX_SLIDE_TITLE_LEN:
        text = text[: _MAX_SLIDE_TITLE_LEN - 3].rstrip() + "..."
    return text


# ---------------------------------------------------------------------------
# Plan construction.
# ---------------------------------------------------------------------------


def _build_plan(source_path: Path, source_bytes: bytes, headings: list[_Heading]) -> dict:
    deck_title = headings[0].text if headings else source_path.stem
    requests = []
    for h in headings:
        image_ref = f"img_{h.ordinal:02d}"
        placement_role = "hero_page" if h.ordinal == 1 else "local_region"
        intended_use = (
            "hero spot illustration" if h.ordinal == 1 else "spot illustration"
        )
        requests.append(
            {
                "index": h.ordinal,
                "image_ref": image_ref,
                "filename": f"{image_ref}.png",
                "slide_title": h.text,
                "placement_role": placement_role,
                "intended_use": intended_use,
                "alt_text": (
                    f"Synthetic placeholder illustration for slide "
                    f"{h.ordinal}: {h.text}"
                ),
                "image_descriptor": (
                    f"Abstract editorial spot illustration evoking the theme "
                    f"of '{h.text}'. Flat vector style, neutral palette. "
                    f"Synthetic placeholder; no real source content embedded."
                ),
                "source_heading_level": h.level,
                "source_heading_ordinal": h.ordinal,
            }
        )
    return {
        "schema_version": "1",
        "plan_id": "image_request_plan",
        "boundary": _BOUNDARY,
        "real_image_generation_status": _REAL_IMAGE_STATUS,
        "source": {
            "filename": source_path.name,
            "byte_count": len(source_bytes),
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "heading_count": len(headings),
        },
        "deck": {
            "title": deck_title,
            "slide_count": len(headings),
        },
        "image_requests": requests,
    }


# Every free-text field the plan emits into the deck / review surface,
# mapped to the operator contract's OWN per-field length limit so the
# bridge's length gate is no weaker than the operator review-package
# contract. slide_title / alt_text / intended_use map to the operator's
# matching manifest-field constants; image_descriptor has no operator
# manifest analog, so it inherits the alt_text limit (the closest
# descriptive field); deck.title is gated as a slide_title.
_PLAN_FIELD_MAXLEN: dict[str, int] = {
    "slide_title": _MAX_SLIDE_TITLE_LEN,
    "alt_text": _MAX_ALT_TEXT_LEN,
    "image_descriptor": _MAX_ALT_TEXT_LEN,
    "intended_use": _MAX_INTENDED_USE_LEN,
}


def _scan_plan_emitted_text(plan: dict) -> list[str]:
    """Run EVERY emitted free-text string in the built plan through the
    operator lane's own _safe_manifest_string contract, AT THE OPERATOR'S
    OWN PER-FIELD LENGTH LIMITS.

    Gating the heading title + filename covers the inputs, but the plan
    also emits COMPOSED strings (alt_text / image_descriptor) and the
    deck title. The operator review-package contract is applied per final
    deck string with field-specific max lengths, so to be provably
    no-weaker the bridge gates each composed value with the SAME content
    rules AND the SAME length cap — not max_len=inf — that the operator
    would apply."""
    failures: list[str] = []
    deck_title = plan.get("deck", {}).get("title", "")
    _, fail = _safe_manifest_string(
        field="deck.title", value=deck_title,
        max_len=_MAX_SLIDE_TITLE_LEN, entry_idx=0,
    )
    if fail is not None:
        failures.append(
            f"operator contract refused deck.title ({deck_title!r}): {fail}"
        )
    for req in plan.get("image_requests", []):
        idx = req.get("index", 0)
        for field, max_len in _PLAN_FIELD_MAXLEN.items():
            value = req.get(field, "")
            _, fail = _safe_manifest_string(
                field=field, value=value, max_len=max_len, entry_idx=idx,
            )
            if fail is not None:
                failures.append(
                    f"operator contract refused image_requests[{idx}]."
                    f"{field} ({value!r}): {fail}"
                )
    return failures


def _validate_plan(plan: dict) -> list[str]:
    """Validate the plan against the committed schema using the repo's
    stdlib subset validator. Returns a list of error strings (empty on
    success)."""
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read schema {SCHEMA_PATH}: {type(exc).__name__}: {exc}"]
    errors: list[str] = []
    _schema_validate(plan, schema, "<root>", errors)
    return errors


# ---------------------------------------------------------------------------
# Source loading shared by both modes.
# ---------------------------------------------------------------------------


def _load_source(source_arg: str) -> tuple[Path | None, bytes, list[str]]:
    """Resolve + read the Markdown source. Returns (path, bytes, failures).
    On any failure path is None and bytes is empty."""
    failures: list[str] = []
    path = Path(source_arg)
    if "://" in source_arg:
        return None, b"", [f"--source {source_arg!r} is URI-shaped; refused (local-only)"]
    if path.is_symlink():
        return None, b"", [f"--source {path} is a symlink; refused"]
    if not path.is_file():
        return None, b"", [f"--source {path} is not a regular file"]
    if not re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$", path.name):
        return None, b"", [
            f"--source basename {path.name!r} is not identifier-safe "
            f"(expected ^[A-Za-z0-9_][A-Za-z0-9_.\\-]*$)"
        ]
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, b"", [f"cannot read --source {path}: {type(exc).__name__}: {exc}"]
    if not raw:
        return None, b"", [f"--source {path} is empty"]
    if len(raw) > MAX_SOURCE_BYTES:
        return None, b"", [
            f"--source {path} is {len(raw)} bytes; exceeds cap "
            f"{MAX_SOURCE_BYTES}"
        ]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, b"", [f"--source {path} is not valid UTF-8: {exc}"]

    failures.extend(_scan_source_safety(text))
    # Defense in depth: re-scan the values that actually flow downstream —
    # the source filename and every SANITISED heading title — so a crafted
    # heading cannot assemble a denied token past the raw-source scan via
    # character stripping / whitespace collapse.
    failures.extend(_scan_emitted_value("source filename", path.name))
    headings = _parse_headings(text)
    for h in headings:
        failures.extend(
            _scan_emitted_value(f"heading #{h.ordinal} title", h.text)
        )
    if not headings:
        failures.append(
            "no ATX Markdown headings ('# Title') found; the bridge derives "
            "one image request per heading and needs at least one"
        )
    elif len(headings) > MAX_HEADINGS:
        failures.append(
            f"{len(headings)} headings exceed the cap {MAX_HEADINGS}; refuse "
            f"rather than silently truncate the deck"
        )
    if failures:
        return None, b"", failures
    return path, raw, []


def _plan_from_source(source_arg: str) -> tuple[dict | None, list[str]]:
    path, raw, failures = _load_source(source_arg)
    if failures or path is None:
        return None, failures
    text = raw.decode("utf-8")
    headings = _parse_headings(text)
    plan = _build_plan(path, raw, headings)
    errors = _validate_plan(plan)
    if errors:
        return None, [f"produced plan failed schema validation: {e}" for e in errors]
    # Final gate: every emitted deck string must pass the operator
    # review-package contract, so the bridge is provably no-weaker than
    # the operator lane that consumes its output.
    emitted_failures = _scan_plan_emitted_text(plan)
    if emitted_failures:
        return None, emitted_failures
    return plan, []


# ---------------------------------------------------------------------------
# Placeholder PNG synthesis. Byte-distinct per index so each operator
# file maps to a distinct embedded ppt/media/* part and the per-image
# provenance attribution is honest. Stdlib-only (zlib + struct + crc32).
# ---------------------------------------------------------------------------


def _png_bytes(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    def _chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    raw = bytearray()
    row = bytes(rgb) * width
    for _ in range(height):
        raw.append(0)  # filter type 0 (None)
        raw += row
    idat = zlib.compress(bytes(raw), 9)
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _write_placeholder_images(images_dir: Path, plan: dict) -> None:
    images_dir.mkdir(parents=True, exist_ok=False)
    for req in plan["image_requests"]:
        idx = req["index"]
        # Vary geometry + colour by index so sha256 differs per file.
        width = 2 + idx
        rgb = ((idx * 37) % 256, (idx * 53) % 256, (idx * 71) % 256)
        (images_dir / req["filename"]).write_bytes(_png_bytes(width, 2, rgb))


# ---------------------------------------------------------------------------
# Operator-handoff sidecars derived from the plan. These reuse the
# EXISTING operator manifest + generated_provenance contracts verbatim
# (no new fields invented); the bridge only fills them from the plan so
# the produced review package reflects the source-derived image request
# plan.
# ---------------------------------------------------------------------------

# Closed-set / safe constants the operator sidecar GP9 enum gate accepts
# (mirrors operator_local_images_to_editable_ppt's
# _SIDECAR_ALLOWED_{GENERATOR_SOURCES,TEXT_POLICIES} and the
# subject_domain vocabulary). The placeholder PNGs carry no text, so
# text_policy is honestly "no_text"; subject_domain is "abstract_marker"
# (the synthetic placeholders are abstract spot illustrations, not data
# visuals / icons / backgrounds). "general" is NOT in the GP9 enum.
_GENERATOR_SOURCE = "operator_declared_generated"
_TEXT_POLICY = "no_text"
_SUBJECT_DOMAIN = "abstract_marker"


def _build_manifest(plan: dict) -> dict:
    """Build an operator ``manifest.json`` from the plan, in plan
    (heading) order. Carries each request's slide_title / alt_text /
    intended_use, which the operator lane routes into the editable slide
    title and the generated image_manifest's alt_text / intended_use."""
    return {
        "schema_version": "1",
        "images": [
            {
                "filename": req["filename"],
                "slide_title": req["slide_title"],
                "alt_text": req["alt_text"],
                "intended_use": req["intended_use"],
            }
            for req in plan["image_requests"]
        ],
    }


def _build_generated_provenance(plan: dict) -> dict:
    """Build an operator ``generated_provenance.json`` sidecar from the
    plan. ``placement_role`` flows verbatim from the plan (hero_page /
    local_region), so the operator lane's role-aware layout picks cover
    for the hero request and section_divider for the rest. The other
    fields are safe closed-set / placeholder values the GP1..GP13 gates
    accept."""
    return {
        "schema_version": "1",
        "entries": [
            {
                "filename": req["filename"],
                "generator_source": _GENERATOR_SOURCE,
                "intent_summary": req["intended_use"],
                "placement_role": req["placement_role"],
                "text_policy": _TEXT_POLICY,
                "subject_domain": _SUBJECT_DOMAIN,
            }
            for req in plan["image_requests"]
        ],
    }


def _write_bundle(bundle: Path, plan: dict) -> None:
    """Materialize a complete operator handoff bundle from the plan::

        <bundle>/images/<image_ref>.png      # byte-distinct placeholders
        <bundle>/manifest.json               # slide_title / alt_text / use
        <bundle>/generated_provenance.json   # placement_role / generator ...

    The operator lane's ``--bundle`` shortcut auto-detects both sidecars
    and runs their full MAN1..MAN12 / GP1..GP13 content gates."""
    _write_placeholder_images(bundle / "images", plan)
    (bundle / "manifest.json").write_text(
        json.dumps(_build_manifest(plan), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (bundle / "generated_provenance.json").write_text(
        json.dumps(_build_generated_provenance(plan), indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Subprocess runner.
# ---------------------------------------------------------------------------


@dataclass
class _ToolOutcome:
    name: str
    rc: int
    stdout: str
    stderr: str


def _run(name: str, cmd: list[str]) -> _ToolOutcome:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    return _ToolOutcome(
        name=name, rc=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
    )


def _print_tail(outcome: _ToolOutcome, *, tail_lines: int = 25) -> None:
    combined = (outcome.stdout or "") + (outcome.stderr or "")
    lines = combined.splitlines()
    if not lines:
        print(f"    (no output from {outcome.name})")
        return
    print(f"    --- last {min(len(lines), tail_lines)} line(s) of {outcome.name} ---")
    for line in lines[-tail_lines:]:
        print(f"    {line}")


# ---------------------------------------------------------------------------
# Mode A: plan-only.
# ---------------------------------------------------------------------------


def _run_plan_only(source_arg: str, plan_out: str) -> int:
    plan_path = Path(plan_out)
    if "://" in plan_out:
        print(f"FAIL: --plan-out {plan_out!r} is URI-shaped; refused", file=sys.stderr)
        return 2
    if plan_path.is_symlink():
        print(f"FAIL: --plan-out {plan_path} is a symlink; refused", file=sys.stderr)
        return 2
    if plan_path.exists():
        print(
            f"FAIL: --plan-out {plan_path} already exists; refuse to "
            f"overwrite (stale bytes preserved)",
            file=sys.stderr,
        )
        return 2
    parent = plan_path.parent
    if not parent.is_dir():
        print(f"FAIL: --plan-out parent {parent} is not an existing directory", file=sys.stderr)
        return 2

    plan, failures = _plan_from_source(source_arg)
    if failures or plan is None:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    plan_path.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"OK: wrote image request plan with {len(plan['image_requests'])} "
        f"image request(s) to {plan_path}"
    )
    print(f"  deck title: {plan['deck']['title']!r}")
    print(f"  {_REAL_IMAGE_STATUS}")
    return 0


# ---------------------------------------------------------------------------
# Mode B: mock/local handoff.
# ---------------------------------------------------------------------------


def _run_mock_handoff(source_arg: str, out_dir_arg: str) -> int:
    out_dir, failures = _validate_out_dir_arg(out_dir_arg)
    if failures or out_dir is None:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 2

    # Parse + validate the source BEFORE creating any output dir, so an
    # unsafe / heading-less source never leaves artifacts behind.
    plan, plan_failures = _plan_from_source(source_arg)
    if plan_failures or plan is None:
        for line in plan_failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    if not out_dir.exists():
        try:
            out_dir.mkdir(parents=False, exist_ok=False)
        except OSError as exc:
            print(f"FAIL: cannot create --out-dir {out_dir}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    plan_path = out_dir / "image_request_plan.json"
    bundle = out_dir / "bundle"
    review_package = out_dir / "review_package"

    print("=== source_to_image_requests --mock-handoff ===")
    print(f"  out-dir:        {out_dir}")
    print(f"  plan:           {plan_path}")
    print(f"  bundle:         {bundle}")
    print(f"  review-package: {review_package}")
    print()

    plan_path.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _write_bundle(bundle, plan)
    n = len(plan["image_requests"])
    print(f"  [PASS] wrote plan + {n} byte-distinct placeholder PNG(s) + "
          f"manifest.json + generated_provenance.json")

    # Drive the EXISTING operator lane via its --bundle shortcut so the
    # plan-derived manifest.json + generated_provenance.json sidecars are
    # auto-detected and run through the operator's own MAN/GP content
    # gates. The manifest's slide_title / alt_text / intended_use land in
    # the editable deck + summary provenance, and the sidecar's
    # placement_role drives the operator's role-aware layout (hero_page ->
    # cover, local_region -> section_divider). No new renderer is added.
    op = _run(
        "operator_local_images_to_editable_ppt --bundle",
        [
            sys.executable, str(OPERATOR_HELPER),
            "--bundle", str(bundle),
            "--out-dir", str(review_package),
        ],
    )
    if op.rc != 0:
        print(f"  [FAIL] operator helper rc={op.rc}")
        _print_tail(op)
        return 1
    print("  [PASS] operator helper rc=0 (editable deck.pptx produced)")

    val = _run(
        "validate_operator_review_package --out-dir",
        [sys.executable, str(PACKAGE_VALIDATOR), "--out-dir", str(review_package)],
    )
    if val.rc != 0:
        print(f"  [FAIL] validate_operator_review_package rc={val.rc}")
        _print_tail(val)
        return 1
    print("  [PASS] validate_operator_review_package rc=0 (read-only re-check)")

    readme = out_dir / "README.md"
    readme.write_text(_render_handoff_readme(plan, review_package), encoding="utf-8")

    print()
    print(f"OK: mock/local handoff complete. Open {readme} first, then "
          f"{review_package / 'deck.pptx'}.")
    return 0


def _render_handoff_readme(plan: dict, review_package: Path) -> str:
    rows = "\n".join(
        f"- heading L{r['source_heading_level']} #{r['source_heading_ordinal']} "
        f"({r['slide_title']}) -> request #{r['index']} -> "
        f"`bundle/images/{r['filename']}` -> placement_role "
        f"`{r['placement_role']}` "
        f"(-> chosen_layout `{'cover' if r['placement_role'] == 'hero_page' else 'section_divider'}`)"
        for r in plan["image_requests"]
    )
    return "\n".join([
        "# source_to_image_requests - mock/local handoff",
        "",
        "A MOCK / LOCAL run of the source-document -> image-request bridge.",
        "A Markdown source was parsed into an image request plan, byte-distinct",
        "placeholder PNGs were synthesised locally (one per heading), and a",
        "plan-derived bundle (images + manifest.json + generated_provenance.json)",
        "was fed into the existing operator image-to-editable-PPT lane to produce",
        "a validated review package whose slides reflect the image request plan.",
        "",
        "## What to open first",
        "",
        "1. `image_request_plan.json` - the per-slide image request plan",
        "   (slide_title / alt_text / image_descriptor / placement_role +",
        "   structural heading traceability). Validated against",
        "   `schemas/image_request_plan.schema.json`.",
        "2. `bundle/manifest.json` + `bundle/generated_provenance.json` - the",
        "   operator sidecars derived from the plan (slide_title / alt_text /",
        "   intended_use; generator_source / placement_role / text_policy /",
        "   subject_domain / intent_summary).",
        f"3. `{review_package.name}/deck.pptx` - the editable PPTX built from the",
        "   placeholder images (native PowerPoint objects).",
        f"4. `{review_package.name}/summary.json` - `image_provenance` ties each",
        "   placeholder filename to its operator_slide_title / alt_text, its",
        "   placement_role + chosen_layout, and its embedded",
        "   `ppt/media/*` part + slides.",
        "",
        "## End-to-end traceability",
        "",
        "source heading -> image_request_plan request -> placeholder filename ->",
        "placement_role -> chosen_layout -> embedded ppt/media part:",
        "",
        rows,
        "",
        "The placement_role -> chosen_layout step is the operator lane's own",
        "role-aware layout (hero_page -> cover, local_region -> section_divider);",
        f"confirm it in `{review_package.name}/summary.json` image_provenance",
        "(`placement_role` + `chosen_layout` + `embedded_media_parts`).",
        "",
        "## Boundary statement",
        "",
        _BOUNDARY,
        "",
        _REAL_IMAGE_STATUS,
        "",
        "## Re-check the review package (read-only)",
        "",
        "```",
        f"python3 scripts/validate_operator_review_package.py --out-dir "
        f"{review_package}",
        "```",
        "",
    ])


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

Body paragraph about the market with the marker phrase ZZMARKERBODYZZ here.

## Product Direction

More body text.

### Near-term Priorities

Body.

## Closing Summary

Final body paragraph.
"""


def _run_self_tests() -> int:
    print("=== source_to_image_requests --self-test ===")
    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    scripts_before = _snapshot_dir(REPO_ROOT / "scripts")
    schemas_before = _snapshot_dir(REPO_ROOT / "schemas")
    probes: list[_Probe] = []

    # T1 valid markdown -> plan.
    with tempfile.TemporaryDirectory(prefix="s2ir-T1-") as raw_td:
        td = Path(raw_td)
        src = td / "report.md"
        src.write_text(_SAMPLE_MD, encoding="utf-8")
        plan_out = td / "plan.json"
        rc = main(["--source", str(src), "--plan-out", str(plan_out)])
        ok = rc == 0 and plan_out.is_file()
        detail = "" if ok else f"rc={rc}; plan exists={plan_out.is_file()}"
        if ok:
            plan_text = plan_out.read_text(encoding="utf-8")
            plan = json.loads(plan_text)
            # 5 headings in the sample.
            if len(plan["image_requests"]) != 5:
                ok, detail = False, f"expected 5 requests, got {len(plan['image_requests'])}"
            elif _validate_plan(plan):
                ok, detail = False, f"plan failed schema: {_validate_plan(plan)}"
            elif plan["image_requests"][0]["placement_role"] != "hero_page":
                ok, detail = False, "first request is not hero_page"
            elif "ZZMARKERBODYZZ" in plan_text:
                ok, detail = False, "raw source body leaked into the plan"
            elif plan["deck"]["title"] != "Quarterly Strategy Overview":
                ok, detail = False, f"deck title wrong: {plan['deck']['title']!r}"
        probes.append(_Probe("T1 valid markdown -> plan", ok, detail))

    # T2 unsafe source rejected (credential / URL / file-URI / abs-path).
    unsafe_cases = {
        "credential": "# Title\n\napi_key = abc123\n",
        "public-network": "# Title\n\nSee https://example.test/report\n",
        "public-upload-body": "# Title\n\nPlease upload to public bucket for sharing.\n",
        "public-hosting-body": "# Title\n\nPublic hosting enabled for this asset.\n",
        "model-success-body": "# Title\n\nThe model API call succeeded.\n",
        "file-uri": "# Title\n\nsource file://local/report\n",
        "absolute-path": "# Title\n\nstored at /Users/someone/data.md\n",
        # Sanitisation-bypass: the raw bytes carry no denied token, but
        # stripping '*' / a control char during title sanitisation would
        # ASSEMBLE one ("api*key" -> "apikey", "sec\x00ret" -> "secret").
        # These must be refused by the post-transformation emitted scan.
        "emphasis-strip-bypass": "# api*key overview\n\nbody\n",
        "ctrl-char-bypass": "# sec\x00ret plan\n\nbody\n",
        # Credential VALUE shape (AWS key id) carried verbatim in a
        # heading. No deny-list keyword substring matches it; only the
        # shared CREDENTIAL_PATTERNS detector catches it.
        "credential-shape": "# Overview AKIAIOSFODNN7EXAMPLE\n\nbody\n",
        # Public-distribution wording the bridge's own deny-list does NOT
        # carry but the operator review-package contract DOES (social-media
        # channel). Proves the emitted-value gate is no weaker than the
        # operator contract.
        "operator-stronger-social": "# Twitter rollout plan\n\nbody\n",
        # Public-hosting wording caught only by the operator contract's
        # 22-shape public-share regex (no bare substring in either list).
        "operator-stronger-hosting": "# Make this cloud-hosted\n\nbody\n",
    }
    for label, body in unsafe_cases.items():
        with tempfile.TemporaryDirectory(prefix=f"s2ir-T2-{label}-") as raw_td:
            td = Path(raw_td)
            src = td / "report.md"
            src.write_text(body, encoding="utf-8")
            plan_out = td / "plan.json"
            rc = main(["--source", str(src), "--plan-out", str(plan_out)])
            ok = rc == 1 and not plan_out.exists()
            detail = "" if ok else f"rc={rc}; plan_written={plan_out.exists()}"
            probes.append(_Probe(f"T2 unsafe rejected ({label})", ok, detail))

    # T3 no-headings rejected.
    with tempfile.TemporaryDirectory(prefix="s2ir-T3-") as raw_td:
        td = Path(raw_td)
        src = td / "report.md"
        src.write_text("Just prose, no headings at all.\n", encoding="utf-8")
        plan_out = td / "plan.json"
        rc = main(["--source", str(src), "--plan-out", str(plan_out)])
        ok = rc == 1 and not plan_out.exists()
        probes.append(_Probe("T3 no-headings rejected", ok, "" if ok else f"rc={rc}"))

    # T3b emitted-text gate is per-final-deck-string: a composed value
    # that the operator contract refuses (here a social-media channel in
    # alt_text) is caught by _scan_plan_emitted_text, AND the real
    # example plan passes it clean — proving the bridge applies the
    # operator contract per emitted deck string, not just per heading.
    bad_plan = {
        "deck": {"title": "Fine title"},
        "image_requests": [
            {"index": 1, "slide_title": "Fine", "intended_use": "spot illustration",
             "alt_text": "please share on linkedin", "image_descriptor": "fine"},
        ],
    }
    bad_fails = _scan_plan_emitted_text(bad_plan)
    try:
        example_plan = json.loads(
            (REPO_ROOT / "examples" / "source_to_image_requests"
             / "image_request_plan.json").read_text(encoding="utf-8")
        )
        good_fails = _scan_plan_emitted_text(example_plan)
    except (OSError, ValueError) as exc:
        bad_fails, good_fails = [], [f"could not read example plan: {exc}"]
    ok = len(bad_fails) >= 1 and not good_fails
    detail = "" if ok else f"bad_fails={len(bad_fails)}; good_fails={good_fails}"
    probes.append(_Probe("T3b emitted-text gate per deck string", ok, detail))

    # T3c emitted-text length gate is at operator strength: an alt_text
    # one char over the operator's alt_text limit is refused (max_len=inf
    # would have let it through), and one exactly at the limit passes.
    over = {
        "deck": {"title": "Fine title"},
        "image_requests": [
            {"index": 1, "slide_title": "Fine", "intended_use": "spot illustration",
             "alt_text": "a" * (_MAX_ALT_TEXT_LEN + 1), "image_descriptor": "fine"},
        ],
    }
    at_limit = {
        "deck": {"title": "Fine title"},
        "image_requests": [
            {"index": 1, "slide_title": "Fine", "intended_use": "spot illustration",
             "alt_text": "a" * _MAX_ALT_TEXT_LEN, "image_descriptor": "fine"},
        ],
    }
    over_fails = _scan_plan_emitted_text(over)
    at_fails = _scan_plan_emitted_text(at_limit)
    ok = len(over_fails) >= 1 and not at_fails
    detail = "" if ok else f"over_fails={len(over_fails)}; at_limit_fails={at_fails}"
    probes.append(_Probe("T3c emitted length gate at operator limit", ok, detail))

    # T3d schema maxLength for every emitted free-text field equals the
    # operator contract's OWN limit, so the schema cannot admit a value
    # the operator review-package gate would later refuse on length. Locks
    # the two limit surfaces together against future drift.
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        deck_props = schema["properties"]["deck"]["properties"]
        item_props = schema["properties"]["image_requests"]["items"]["properties"]
        expected = {
            ("deck.title", deck_props["title"]["maxLength"], _MAX_SLIDE_TITLE_LEN),
            ("slide_title", item_props["slide_title"]["maxLength"], _MAX_SLIDE_TITLE_LEN),
            ("alt_text", item_props["alt_text"]["maxLength"], _MAX_ALT_TEXT_LEN),
            ("image_descriptor", item_props["image_descriptor"]["maxLength"], _MAX_ALT_TEXT_LEN),
            ("intended_use", item_props["intended_use"]["maxLength"], _MAX_INTENDED_USE_LEN),
        }
        mism = [(f, have, want) for f, have, want in expected if have != want]
    except (OSError, ValueError, KeyError) as exc:
        mism = [("schema-read", repr(exc), "")]
    ok = not mism
    detail = "" if ok else f"schema/operator maxLength mismatch: {mism}"
    probes.append(_Probe("T3d schema maxLen == operator limits", ok, detail))

    # T4 mock/local handoff produces a review package.
    handoff_summary_text = ""
    with tempfile.TemporaryDirectory(prefix="s2ir-T4-") as raw_td:
        td = Path(raw_td)
        src = td / "report.md"
        src.write_text(_SAMPLE_MD, encoding="utf-8")
        out_dir = td / "out"
        rc = main(["--source", str(src), "--mock-handoff", "--out-dir", str(out_dir)])
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
        if ok and not (out_dir / "README.md").is_file():
            ok, detail = False, "missing handoff README"
        summary = None
        plan_obj = None
        if ok:
            summary = json.loads((review / "summary.json").read_text(encoding="utf-8"))
            handoff_summary_text = json.dumps(summary)
            plan_obj = json.loads(
                (out_dir / "image_request_plan.json").read_text(encoding="utf-8")
            )
            prov = summary.get("image_provenance")
            if not isinstance(prov, list) or len(prov) != 5:
                ok, detail = False, f"image_provenance not 5 rows: {prov!r}"
            else:
                for i, row in enumerate(prov):
                    parts = row.get("embedded_media_parts")
                    if not isinstance(parts, list) or not parts:
                        ok, detail = False, f"row {i} has no embedded_media_parts"
                        break
        probes.append(_Probe("T4 mock handoff -> review package", ok, detail))

        # T4a plan metadata flows into operator provenance: the manifest's
        # slide_title / alt_text (derived from the plan) appear verbatim on
        # each summary image_provenance row, keyed by filename.
        ok_a, detail_a = ok, ""
        if ok_a and summary is not None and plan_obj is not None:
            by_file = {r.get("operator_filename"): r
                       for r in summary["image_provenance"]}
            for req in plan_obj["image_requests"]:
                row = by_file.get(req["filename"])
                if row is None:
                    ok_a, detail_a = False, f"no provenance row for {req['filename']}"
                    break
                if row.get("operator_slide_title") != req["slide_title"]:
                    ok_a, detail_a = False, (
                        f"{req['filename']} operator_slide_title="
                        f"{row.get('operator_slide_title')!r} != plan "
                        f"{req['slide_title']!r}"
                    )
                    break
                if row.get("operator_alt_text") != req["alt_text"]:
                    ok_a, detail_a = False, f"{req['filename']} operator_alt_text mismatch"
                    break
        else:
            ok_a, detail_a = False, "T4 prerequisite failed"
        probes.append(_Probe("T4a plan slide_title/alt_text in provenance", ok_a, detail_a))

        # T4b role-aware layout: the FIRST request (hero_page) routes to a
        # cover layout; every LATER request (local_region) routes to a
        # section_divider layout — the operator lane's own placement-role
        # mapping, driven by the plan-derived generated_provenance sidecar.
        ok_b, detail_b = ok, ""
        if ok_b and summary is not None and plan_obj is not None:
            by_file = {r.get("operator_filename"): r
                       for r in summary["image_provenance"]}
            for req in plan_obj["image_requests"]:
                row = by_file[req["filename"]]
                role = row.get("placement_role")
                layout = row.get("chosen_layout")
                want_role = "hero_page" if req["index"] == 1 else "local_region"
                want_layout = "cover" if req["index"] == 1 else "section_divider"
                if role != want_role:
                    ok_b, detail_b = False, (
                        f"{req['filename']} placement_role={role!r} != {want_role!r}"
                    )
                    break
                if layout != want_layout:
                    ok_b, detail_b = False, (
                        f"{req['filename']} chosen_layout={layout!r} != {want_layout!r}"
                    )
                    break
        else:
            ok_b, detail_b = False, "T4 prerequisite failed"
        probes.append(_Probe("T4b role-aware layout (cover/section_divider)", ok_b, detail_b))

    # T5 no positive external-service claims on any produced surface.
    # Phrasings are POSITIVE success claims, not bare service names, so a
    # legitimate boundary disclaimer ("Real D-One ... remains UNVERIFIED")
    # in the operator summary does not false-trip.
    positives = (
        "real d-one verified", "real d-one online", "real d-one succeeded",
        "d-one verified", "d-one online", "mcp call succeeded",
        "called mcp", "called qoder", "qoder run succeeded",
        "model api call", "called model api", "image search returned",
        "called image search", "public network call",
        "telemetry emitted", "telemetry sent",
    )
    offenders = [p for p in positives if p in handoff_summary_text.lower()]
    ok = not offenders
    detail = "" if ok else f"claim_offenders={offenders}"
    probes.append(_Probe("T5 no external-service claims", ok, detail))

    # T6 out-dir gate wired: URI --out-dir refused.
    with tempfile.TemporaryDirectory(prefix="s2ir-T6-") as raw_td:
        td = Path(raw_td)
        src = td / "report.md"
        src.write_text(_SAMPLE_MD, encoding="utf-8")
        uri_out = "file:///" + str(td / "u").lstrip("/")
        rc = main(["--source", str(src), "--mock-handoff", "--out-dir", uri_out])
        ok = rc == 2 and not (td / "u").exists()
        probes.append(_Probe("T6 URI out-dir refused", ok, "" if ok else f"rc={rc}"))

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
            "Source-document -> image-request bridge (MOCK / LOCAL only). "
            "Parses a Markdown source into a deterministic image_request_plan "
            "(one image request per heading, synthetic-safe per-slide "
            "metadata + heading traceability) and can perform a mock/local "
            "handoff that writes byte-distinct placeholder PNGs and feeds "
            "them into the existing operator image-to-editable-PPT lane. "
            "Local-only: no D-One, MCP, Qoder, public network, telemetry, "
            "model API, or image search. NOT real image generation; NOT "
            "full report-to-PPT automation."
        ),
    )
    parser.add_argument(
        "--source",
        help=(
            "Path to a UTF-8 Markdown source file (identifier-safe basename, "
            "not a symlink, not URI-shaped). The whole file is scanned for "
            "credential / public-network / file-URI / absolute-path wording "
            "and refused on any hit; the downstream filename + heading titles "
            "are re-scanned after sanitisation to close character-stripping "
            "bypasses."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--plan-out",
        help=(
            "Write the image_request_plan JSON to this path (must not exist, "
            "not a symlink, not URI-shaped; parent must exist). Requires "
            "--source."
        ),
    )
    mode.add_argument(
        "--mock-handoff",
        action="store_true",
        help=(
            "Mock/local handoff: write the plan + a plan-derived operator "
            "bundle (placeholder PNGs + manifest.json + "
            "generated_provenance.json) under --out-dir and drive the "
            "existing operator image-to-editable-PPT lane (--bundle) to "
            "produce a validated review package whose slide titles / alt "
            "text / role-aware layouts reflect the image request plan. "
            "Requires --source and --out-dir."
        ),
    )
    mode.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run every scenario under a per-run TMPDIR (valid plan, unsafe "
            "rejection, no-headings rejection, mock handoff, no-external "
            "claims, out-dir gate). No caller-visible artifacts retained."
        ),
    )
    parser.add_argument(
        "--out-dir",
        help=(
            "Output directory outside the repo tree for --mock-handoff. Must "
            "not be URI-shaped, a symlink, or have a symlink ancestor; must "
            "not anchor under the repo tree; must be missing or empty."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return _run_self_tests()

    if not args.source:
        print("FAIL: --source is required with --plan-out / --mock-handoff", file=sys.stderr)
        return 2

    if args.plan_out:
        return _run_plan_only(args.source, args.plan_out)

    # --mock-handoff
    if not args.out_dir:
        print("FAIL: --mock-handoff requires --out-dir", file=sys.stderr)
        return 2
    return _run_mock_handoff(args.source, args.out_dir)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
