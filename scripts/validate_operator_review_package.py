#!/usr/bin/env python3
"""validate_operator_review_package.py

Read-only stdlib validator for the review package produced by
``scripts/operator_local_images_to_editable_ppt.py`` (the ``--out-dir``
artifact set, including the ``--bundle`` shortcut). Re-checks that the
package on disk still matches the helper's truth-checked summary so a
reviewer can confirm the bundle has not been tampered with after the
helper exited, without re-running the pipeline.

Local-only — does NOT call D-One, MCP, Qoder, a public network, a
model API, an image search, or telemetry. NOT a prompt or
report-to-PPT automation.

USAGE
    python3 scripts/validate_operator_review_package.py --out-dir DIR
    python3 scripts/validate_operator_review_package.py --self-test

WHAT GETS CHECKED
    Per ``--out-dir DIR``:
      - Required files present and regular non-symlink:
        ``deck.pptx`` / ``summary.json`` / ``inventory.json`` /
        ``visual_quality.json`` / ``README.md``.
      - Required directories present and regular non-symlink:
        ``workspace/`` / ``reports/``.
      - ``summary.helper_id == "operator_local_images_to_editable_ppt"``.
      - ``summary.real_d_one_status == "UNVERIFIED"``.
      - ``summary.explicit_boundaries`` matches the locked tuple of
        deny statements (no real D-One, MCP, Qoder, public network,
        model API, image search, telemetry, or raw prompt /
        report-to-PPT automation).
      - Summary path fields (``pptx_path`` / ``workspace_path`` /
        ``report_dir`` / ``inventory_path`` / ``registry_path`` /
        ``visual_quality.path``) resolve under ``--out-dir`` and point
        at the expected existing non-symlink artifact / type.
      - ``slide_count`` / ``image_count`` / ``embedded_media_count`` /
        ``source_classes`` / ``no_external_relationships`` / validator
        ``rc`` values / ``inventory.ok`` / ``inventory.findings_empty`` /
        ``visual_quality.error_count == 0`` / every
        ``image_provenance[*].placement_verified == True``.
      - Re-runs the existing ``validate_pptx_contract.py
        --expected-slide-count`` and ``inspect_pptx_inventory.py``
        validators against the on-disk ``deck.pptx`` and confirms the
        produced inventory still agrees with the summary's slide /
        embedded-media counts.
      - Scans every JSON file + ``README.md`` for URI / URL,
        credential / token / API-key, public upload / share / hosting
        wording, confidential / raw-source / customer markers, and
        positive real-service success claims for the upstream
        services this lane does NOT call.

EXIT CODES
    0  every gate passed.
    1  one or more gates failed (each refusal is printed to stderr).
    2  invocation error (missing ``--out-dir`` etc.).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

VALIDATE_PPTX_CONTRACT = SCRIPTS_DIR / "validate_pptx_contract.py"
INSPECT_PPTX_INVENTORY = SCRIPTS_DIR / "inspect_pptx_inventory.py"

# Mirrors the helper-side ``_EXPLICIT_BOUNDARIES`` tuple verbatim. Kept
# locally so this validator stays a standalone read-only gate that does
# not import operator_local_images_to_editable_ppt and pull in the
# whole pipeline surface.
_EXPECTED_BOUNDARIES: tuple[str, ...] = (
    "No real D-One call; image generation status is UNVERIFIED.",
    "No MCP call.",
    "No Qoder runtime invocation.",
    "No model API contact.",
    "No image search.",
    "No public network access.",
    "No telemetry emission.",
    "Raw prompt or report-to-PPT automation is NOT implemented.",
)

_EXPECTED_HELPER_ID = "operator_local_images_to_editable_ppt"
_EXPECTED_REAL_D_ONE_STATUS = "UNVERIFIED"
_EXPECTED_SOURCE_CLASSES = ["local_asset"]

# Lowercase-hex 64-character sha256 pattern; reviewers can pipe the
# recorded digest to ``sha256sum`` without parsing variations. Mirrors
# the helper-side ``_SHA256_HEX_PATTERN``.
_SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}")

# Sentinel distinct from ``None`` so missing-key (must refuse — a
# tampered summary cannot silently erase the approved-plan lock) is
# distinguishable from an explicit JSON null (accepted — the run was
# not approved-plan-locked).
_MISSING = object()

_REQUIRED_FILES = (
    "deck.pptx",
    "summary.json",
    "inventory.json",
    "visual_quality.json",
    "README.md",
)
_REQUIRED_DIRS = ("workspace", "reports")

# String safety scans. Each entry is (label, compiled-pattern). Patterns
# are evaluated on the raw text bytes of every scanned file; a single
# hit produces a failure naming the file + the matched snippet.
_URI_SCHEME_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.\-]*://")

# Known-dangerous single-colon URI schemes (no ``//`` required). The
# ``://``-anchored regex above misses these — ``data:image/png;base64,...``,
# ``file:/path/to/x``, or ``mailto:foo`` would slip through silently,
# which is exactly the kind of embedded / local-path / contact leak
# this lane is supposed to refuse. ``file`` is on the list because the
# previous ``\bfile:\b`` word-boundary check silently false-negated
# ``file://x`` and ``file:/foo`` (``\b`` between non-word ``:`` and
# non-word ``/`` is no boundary, so the trailing ``\b`` never matched).
# Each scheme must be followed by a non-whitespace / non-quote /
# non-bracket char so prose like ``"Note: foo"`` or ``"Time is 10:30"``
# does not false-positive. The list deliberately stays narrow to known
# network / embedding / local-FS / XSS schemes — generic words like
# ``"note"`` / ``"summary"`` would create false positives in operator
# metadata otherwise.
_DANGEROUS_URI_SCHEMES: tuple[str, ...] = (
    "data",
    "file",
    "javascript",
    "vbscript",
    "mailto",
    "tel",
    "urn",
    "gopher",
    "ssh",
    "git",
    "ftp",
    "sftp",
    "ws",
    "wss",
    "view-source",
    "chrome-extension",
    "intent",
    "jdbc",
    "dict",
    "ldap",
    "ldaps",
    "imap",
    "pop",
    "smtp",
    "telnet",
    "rsync",
    "feed",
    "afp",
    "smb",
    "nfs",
)
_DANGEROUS_URI_SCHEME_RE = re.compile(
    r"\b(?P<scheme>"
    + "|".join(re.escape(s) for s in _DANGEROUS_URI_SCHEMES)
    + r"):[^\s\"'<>)\]}]",
    re.IGNORECASE,
)
_CREDENTIAL_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("api_key", re.compile(r"\bapi[_\- ]?key\b", re.IGNORECASE)),
    ("bearer_token", re.compile(r"\bbearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)),
    ("token_assignment", re.compile(r"\btoken\s*=\s*[A-Za-z0-9._\-]+", re.IGNORECASE)),
    ("password_marker", re.compile(r"\bpassword\s*[:=]", re.IGNORECASE)),
    ("openai_secret", re.compile(r"\bsk-[A-Za-z0-9]{8,}\b")),
)
_PUBLIC_HOSTING_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("public_upload", re.compile(r"\bpublic\s+upload(ed|ing|s)?\b", re.IGNORECASE)),
    ("public_share", re.compile(r"\bpublic\s+shar(e|ed|ing)\b", re.IGNORECASE)),
    ("public_hosting", re.compile(r"\bpublic\s+hosting\b", re.IGNORECASE)),
    ("image_hosting", re.compile(r"\bimage\s+hosting\b", re.IGNORECASE)),
    ("cdn_hosting", re.compile(r"\bcdn\s+host(ed|ing)\b", re.IGNORECASE)),
)
_CONFIDENTIAL_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("confidential_marker", re.compile(r"\bconfidential\b", re.IGNORECASE)),
    ("raw_source_marker", re.compile(r"\braw[_\- ]source\b", re.IGNORECASE)),
    ("customer_marker", re.compile(r"\bcustomer[_\- ]?id\b", re.IGNORECASE)),
)
# Positive success claims for upstream services this lane explicitly
# does NOT call. Each tuple is (label, noun-pattern, verb-pattern). A
# match requires the noun and verb to co-occur within a 60-char window
# (in either order) so the locked "is NOT called" negation wording in
# the summary's boundary tuple does not false-positive.
_POSITIVE_SERVICE_CLAIMS: tuple[tuple[str, re.Pattern[str], re.Pattern[str]], ...] = (
    (
        "real_d_one_success",
        re.compile(r"\b(real[_\- ]?d[\-_ ]?one|d[\-_ ]?one\s+production)\b", re.IGNORECASE),
        re.compile(r"\b(verified|success(ful|fully)?|live|production\s+run|generated|completed)\b", re.IGNORECASE),
    ),
    (
        "mcp_success",
        re.compile(r"\bmcp\b", re.IGNORECASE),
        re.compile(r"\b(call(ed)?|invoked|verified|success(ful|fully)?|live)\b", re.IGNORECASE),
    ),
    (
        "qoder_success",
        re.compile(r"\bqoder\b", re.IGNORECASE),
        re.compile(r"\b(runtime|verified|success(ful|fully)?|live|launched)\b", re.IGNORECASE),
    ),
    (
        "model_api_success",
        re.compile(r"\bmodel\s+api\b", re.IGNORECASE),
        re.compile(r"\b(call(ed)?|invoked|verified|success(ful|fully)?|live)\b", re.IGNORECASE),
    ),
    (
        "image_search_success",
        re.compile(r"\bimage\s+search\b", re.IGNORECASE),
        re.compile(r"\b(invoked|verified|success(ful|fully)?|completed)\b", re.IGNORECASE),
    ),
    (
        "public_network_success",
        re.compile(r"\bpublic\s+network\b", re.IGNORECASE),
        re.compile(r"\b(access(ed)?|verified|success(ful|fully)?|live|completed)\b", re.IGNORECASE),
    ),
    (
        "telemetry_emission",
        re.compile(r"\btelemetry\b", re.IGNORECASE),
        re.compile(r"\b(emitt(ed|ing)?|sent|reported|dispatched|enabled)\b", re.IGNORECASE),
    ),
)

# Phrases the locked boundary tuple uses verbatim. Skipping any of these
# in the positive-claim scan avoids false positives on the helper's own
# negation-pinned wording without weakening the gate elsewhere.
_BOUNDARY_NEGATION_PHRASES: tuple[str, ...] = (
    "No real D-One call; image generation status is UNVERIFIED.",
    "No MCP call.",
    "No Qoder runtime invocation.",
    "No model API contact.",
    "No image search.",
    "No public network access.",
    "No telemetry emission.",
    "Raw prompt or report-to-PPT automation is NOT implemented.",
    "real D-One is UNVERIFIED; this helper does NOT call MCP, "
    "Qoder, a public network, a model API, an image search, or "
    "telemetry, and is NOT a prompt or report-to-PPT automation.",
)


@dataclass
class _ValidationResult:
    failures: list[str]

    @property
    def ok(self) -> bool:
        return not self.failures


# ---------------------------------------------------------------------------
# File-system / shape gates.
# ---------------------------------------------------------------------------


def _validate_out_dir_arg(out_dir_str: str) -> tuple[Path | None, list[str]]:
    """Resolve and shape-check ``--out-dir``. Read-only: no mkdir, no
    write. Returns the resolved path on success and an empty failure
    list, or (None, [diagnostics]) on failure."""
    failures: list[str] = []
    if not out_dir_str:
        return None, ["--out-dir is empty"]
    if re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:", out_dir_str):
        return None, [f"--out-dir {out_dir_str!r} looks URI-shaped; refused"]
    out_dir = Path(out_dir_str)
    if not out_dir.exists():
        return None, [f"--out-dir {out_dir} does not exist"]
    if out_dir.is_symlink():
        return None, [f"--out-dir {out_dir} is a symlink; refused"]
    if not out_dir.is_dir():
        return None, [f"--out-dir {out_dir} is not a directory; refused"]
    return out_dir.resolve(), failures


def _check_required_paths(out_dir: Path) -> list[str]:
    failures: list[str] = []
    for name in _REQUIRED_FILES:
        p = out_dir / name
        if not p.exists():
            failures.append(f"missing required file: {p}")
            continue
        if p.is_symlink():
            failures.append(f"required file is a symlink: {p}")
            continue
        if not p.is_file():
            failures.append(f"required path is not a regular file: {p}")
    for name in _REQUIRED_DIRS:
        p = out_dir / name
        if not p.exists():
            failures.append(f"missing required directory: {p}")
            continue
        if p.is_symlink():
            failures.append(f"required directory is a symlink: {p}")
            continue
        if not p.is_dir():
            failures.append(f"required path is not a directory: {p}")
    return failures


# ---------------------------------------------------------------------------
# Summary / inventory / visual_quality field gates.
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> tuple[Any, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{path}: cannot read ({type(exc).__name__}: {exc})"
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"{path}: invalid JSON ({exc})"


def _resolves_under(out_dir: Path, candidate: str) -> bool:
    """Return True iff ``candidate`` (a string from summary.*) resolves
    to a path under ``out_dir``. The path does NOT have to exist (the
    on-disk presence is checked separately) but it must not escape via
    symlinks or ``..`` components. ``out_dir`` is compared after
    ``.resolve()`` so closed system aliases like macOS's
    ``/tmp -> /private/tmp`` do not false-fail."""
    try:
        p = Path(candidate)
    except (TypeError, ValueError):
        return False
    if not p.is_absolute():
        p = out_dir / p
    try:
        resolved = p.resolve()
    except (OSError, RuntimeError):
        return False
    try:
        resolved.relative_to(out_dir.resolve())
    except ValueError:
        return False
    return True


def _check_summary(summary: Any, out_dir: Path) -> list[str]:
    failures: list[str] = []
    if not isinstance(summary, dict):
        return [f"summary.json must decode as a JSON object; got {type(summary).__name__}"]

    if summary.get("helper_id") != _EXPECTED_HELPER_ID:
        failures.append(
            f"summary.helper_id={summary.get('helper_id')!r}; expected {_EXPECTED_HELPER_ID!r}"
        )
    if summary.get("real_d_one_status") != _EXPECTED_REAL_D_ONE_STATUS:
        failures.append(
            f"summary.real_d_one_status={summary.get('real_d_one_status')!r}; "
            f"expected {_EXPECTED_REAL_D_ONE_STATUS!r}"
        )

    boundaries = summary.get("explicit_boundaries")
    if boundaries != list(_EXPECTED_BOUNDARIES):
        failures.append(
            f"summary.explicit_boundaries={boundaries!r}; expected the locked tuple "
            f"{list(_EXPECTED_BOUNDARIES)!r} verbatim"
        )

    image_count = summary.get("image_count")
    slide_count = summary.get("slide_count")
    embedded = summary.get("embedded_media_count")
    if not isinstance(image_count, int) or image_count < 1:
        failures.append(f"summary.image_count={image_count!r}; expected int >= 1")
    if isinstance(image_count, int) and (
        not isinstance(slide_count, int) or slide_count != image_count
    ):
        failures.append(
            f"summary.slide_count={slide_count!r}; expected {image_count!r}"
        )
    if isinstance(image_count, int) and (
        not isinstance(embedded, int) or embedded != image_count
    ):
        failures.append(
            f"summary.embedded_media_count={embedded!r}; expected {image_count!r}"
        )
    if summary.get("source_classes") != _EXPECTED_SOURCE_CLASSES:
        failures.append(
            f"summary.source_classes={summary.get('source_classes')!r}; "
            f"expected {_EXPECTED_SOURCE_CLASSES!r}"
        )
    if summary.get("no_external_relationships") is not True:
        failures.append(
            f"summary.no_external_relationships="
            f"{summary.get('no_external_relationships')!r}; expected True"
        )

    inv = summary.get("inventory") or {}
    if inv.get("ok") is not True:
        failures.append(f"summary.inventory.ok={inv.get('ok')!r}; expected True")
    if inv.get("findings_empty") is not True:
        failures.append(
            f"summary.inventory.findings_empty={inv.get('findings_empty')!r}; expected True"
        )

    val = summary.get("validators") or {}
    for k in (
        "validate_source_image_assets",
        "validate_pptx_contract",
        "inspect_pptx_inventory",
        "validate_visual_quality",
    ):
        rc = (val.get(k) or {}).get("rc")
        if rc != 0:
            failures.append(f"summary.validators.{k}.rc={rc!r}; expected 0")

    vq = summary.get("visual_quality") or {}
    if vq.get("rc") != 0:
        failures.append(f"summary.visual_quality.rc={vq.get('rc')!r}; expected 0")
    if vq.get("report_parsed") is not True:
        failures.append(
            f"summary.visual_quality.report_parsed={vq.get('report_parsed')!r}; "
            f"expected True"
        )
    err_count = vq.get("error_count")
    if not isinstance(err_count, int) or err_count != 0:
        failures.append(
            f"summary.visual_quality.error_count={err_count!r}; expected 0"
        )

    prov = summary.get("image_provenance")
    if not isinstance(prov, list) or len(prov) != (image_count or -1):
        failures.append(
            f"summary.image_provenance length="
            f"{len(prov) if isinstance(prov, list) else 'n/a'}; "
            f"expected one entry per operator image ({image_count!r})"
        )
    elif isinstance(prov, list):
        for i, entry in enumerate(prov):
            if not isinstance(entry, dict):
                failures.append(f"summary.image_provenance[{i}] is not an object")
                continue
            parts = entry.get("embedded_media_parts")
            if not isinstance(parts, list) or not parts:
                failures.append(
                    f"summary.image_provenance[{i}].embedded_media_parts={parts!r}; "
                    f"expected non-empty list"
                )
            intended = entry.get("intended_slide_index")
            if not isinstance(intended, int) or isinstance(intended, bool) or intended < 1:
                failures.append(
                    f"summary.image_provenance[{i}].intended_slide_index="
                    f"{intended!r}; expected positive int"
                )
            ref_slides = entry.get("embedded_referencing_slides")
            if (
                not isinstance(ref_slides, list)
                or not ref_slides
                or not all(
                    isinstance(s, int) and not isinstance(s, bool) for s in ref_slides
                )
            ):
                failures.append(
                    f"summary.image_provenance[{i}].embedded_referencing_slides="
                    f"{ref_slides!r}; expected non-empty list of int slide indices"
                )
            elif (
                isinstance(intended, int)
                and not isinstance(intended, bool)
                and intended not in ref_slides
            ):
                failures.append(
                    f"summary.image_provenance[{i}].intended_slide_index={intended!r} "
                    f"not in embedded_referencing_slides={ref_slides!r}"
                )
            placement = entry.get("placement_verified")
            if placement is not True:
                failures.append(
                    f"summary.image_provenance[{i}].placement_verified="
                    f"{placement!r}; expected True"
                )

    # approved_plan: the helper's truth-checker enforces this field
    # before writing summary.json, so a tampered post-helper edit
    # is the only way an invalid value can land here. Mirrors the
    # helper-side gate verbatim so this validator catches the same
    # drift on disk.
    ap = summary.get("approved_plan", _MISSING)
    if ap is _MISSING:
        failures.append(
            "summary.approved_plan missing; expected null (no "
            "--approved-plan supplied) or {path, sha256, matched: True}"
        )
    elif ap is not None:
        if not isinstance(ap, dict):
            failures.append(
                f"summary.approved_plan={ap!r}; expected null or an object"
            )
        else:
            unknown = sorted(set(ap.keys()) - {"path", "sha256", "matched"})
            if unknown:
                failures.append(
                    f"summary.approved_plan has unknown key(s) "
                    f"{unknown!r}; expected exactly {{path, sha256, matched}}"
                )
            ap_path = ap.get("path")
            if not isinstance(ap_path, str) or not ap_path:
                failures.append(
                    f"summary.approved_plan.path={ap_path!r}; expected "
                    f"non-empty string"
                )
            ap_sha = ap.get("sha256")
            if (
                not isinstance(ap_sha, str)
                or not _SHA256_HEX_PATTERN.fullmatch(ap_sha)
            ):
                failures.append(
                    f"summary.approved_plan.sha256={ap_sha!r}; expected "
                    f"64-character lowercase hex string"
                )
            ap_matched = ap.get("matched")
            if ap_matched is not True:
                failures.append(
                    f"summary.approved_plan.matched={ap_matched!r}; "
                    f"expected True (the helper refuses with rc 2 BEFORE "
                    f"summary creation on a mismatch — matched=True is "
                    f"the only value a clean run can produce)"
                )

    # Path-field cross-checks. Every path-typed field the helper writes
    # into summary.json must resolve under --out-dir to the expected
    # artifact (regular non-symlink file/dir). ``registry_path`` lives
    # inside the workspace; ``visual_quality.path`` is nested one level
    # deep under summary.visual_quality. Tampering with any of these
    # post-helper is exactly the kind of drift this validator exists to
    # refuse, so every contract field is gated here — not just the flat
    # top-level subset.
    path_checks: tuple[tuple[str, Any, Path, str], ...] = (
        ("pptx_path", summary.get("pptx_path"), out_dir / "deck.pptx", "file"),
        ("workspace_path", summary.get("workspace_path"), out_dir / "workspace", "dir"),
        ("report_dir", summary.get("report_dir"), out_dir / "reports", "dir"),
        ("inventory_path", summary.get("inventory_path"), out_dir / "inventory.json", "file"),
        (
            "registry_path",
            summary.get("registry_path"),
            out_dir / "workspace" / "source_image_assets.json",
            "file",
        ),
        (
            "visual_quality.path",
            vq.get("path"),
            out_dir / "visual_quality.json",
            "file",
        ),
    )
    for label, raw, expected, kind in path_checks:
        if not isinstance(raw, str) or not raw:
            failures.append(f"summary.{label}={raw!r}; expected non-empty string")
            continue
        if not _resolves_under(out_dir, raw):
            failures.append(
                f"summary.{label}={raw!r} does not resolve under --out-dir {out_dir}"
            )
            continue
        try:
            resolved = Path(raw).resolve()
        except (OSError, RuntimeError):
            failures.append(f"summary.{label}={raw!r}; cannot resolve")
            continue
        if resolved != expected.resolve():
            failures.append(
                f"summary.{label}={raw!r}; expected to point at {expected}"
            )
            continue
        if kind == "file" and (not expected.is_file() or expected.is_symlink()):
            failures.append(
                f"summary.{label} target {expected} is not a regular non-symlink file"
            )
        if kind == "dir" and (not expected.is_dir() or expected.is_symlink()):
            failures.append(
                f"summary.{label} target {expected} is not a regular non-symlink directory"
            )

    return failures


def _check_inventory_vs_summary(inventory: Any, summary: dict) -> list[str]:
    failures: list[str] = []
    if not isinstance(inventory, dict):
        return [f"inventory.json must decode as a JSON object; got {type(inventory).__name__}"]
    if inventory.get("ok") is not True:
        failures.append(f"inventory.ok={inventory.get('ok')!r}; expected True")
    findings = inventory.get("findings")
    if findings != []:
        failures.append(f"inventory.findings={findings!r}; expected []")
    inv_slides = inventory.get("slide_count")
    s_slides = summary.get("slide_count")
    if inv_slides != s_slides:
        failures.append(
            f"inventory.slide_count={inv_slides!r} differs from "
            f"summary.slide_count={s_slides!r}"
        )
    media = inventory.get("media_parts")
    if not isinstance(media, list):
        failures.append(f"inventory.media_parts={type(media).__name__}; expected list")
        return failures
    embedded = summary.get("embedded_media_count")
    if isinstance(embedded, int) and len(media) != embedded:
        failures.append(
            f"inventory.media_parts count={len(media)} differs from "
            f"summary.embedded_media_count={embedded!r}"
        )
    return failures


def _check_visual_quality(report: Any, summary: dict) -> list[str]:
    failures: list[str] = []
    if not isinstance(report, dict):
        return [
            f"visual_quality.json must decode as a JSON object; got "
            f"{type(report).__name__}"
        ]
    totals = report.get("totals")
    if not isinstance(totals, dict):
        return [f"visual_quality.totals={totals!r}; expected object"]
    errors = totals.get("errors")
    if not isinstance(errors, int) or errors != 0:
        failures.append(f"visual_quality.totals.errors={errors!r}; expected 0")
    summary_vq = summary.get("visual_quality") or {}
    s_err = summary_vq.get("error_count")
    if s_err != errors:
        failures.append(
            f"summary.visual_quality.error_count={s_err!r} differs from "
            f"visual_quality.totals.errors={errors!r}"
        )
    return failures


# ---------------------------------------------------------------------------
# String-safety scans across every JSON file + README.md.
# ---------------------------------------------------------------------------


def _walk_scan_files(out_dir: Path) -> list[Path]:
    """Collect every readable regular file under ``out_dir`` whose
    name ends in ``.json`` or ``.md`` or equals ``README.md``. Skips
    symlinks so a planted symlink cannot smuggle tampered bytes."""
    out: list[Path] = []
    for p in sorted(out_dir.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        name = p.name.lower()
        if name.endswith(".json") or name.endswith(".md"):
            out.append(p)
    return out


def _scan_text_for_unsafe(text: str, path: Path) -> list[str]:
    failures: list[str] = []
    # Whitelist the locked negation-pinned boundary phrases by removing
    # them before pattern scans. The remaining text is what gets
    # checked for credentials / hosting / positive-claim shapes.
    redacted = text
    for phrase in _BOUNDARY_NEGATION_PHRASES:
        redacted = redacted.replace(phrase, " ")

    for match in _URI_SCHEME_RE.finditer(redacted):
        scheme = match.group(0)
        if scheme.lower() in {"https://", "http://"} and "schemas.openxmlformats.org" in redacted[match.start():match.end() + 64]:
            # An OOXML schema URL would be a finding inside summary JSON
            # too — the helper never emits one, so allow this branch
            # only as a defensive guard; today it never fires.
            continue
        failures.append(f"{path}: URI-shaped scheme {scheme!r} found at offset {match.start()}")
    for match in _DANGEROUS_URI_SCHEME_RE.finditer(redacted):
        snippet = redacted[match.start():match.start() + 80].splitlines()[0]
        failures.append(
            f"{path}: dangerous single-colon URI scheme "
            f"{match.group('scheme').lower()!r} matched {snippet!r}"
        )

    for label, pattern in _CREDENTIAL_RES:
        m = pattern.search(redacted)
        if m:
            failures.append(f"{path}: credential marker {label!r} matched {m.group(0)!r}")
    for label, pattern in _PUBLIC_HOSTING_RES:
        m = pattern.search(redacted)
        if m:
            failures.append(f"{path}: public-hosting marker {label!r} matched {m.group(0)!r}")
    for label, pattern in _CONFIDENTIAL_RES:
        m = pattern.search(redacted)
        if m:
            failures.append(
                f"{path}: confidential/raw-source marker {label!r} matched {m.group(0)!r}"
            )

    for label, noun_re, verb_re in _POSITIVE_SERVICE_CLAIMS:
        for noun_match in noun_re.finditer(redacted):
            window_start = max(0, noun_match.start() - 60)
            window_end = min(len(redacted), noun_match.end() + 60)
            window = redacted[window_start:window_end]
            verb_match = verb_re.search(window)
            if verb_match:
                failures.append(
                    f"{path}: positive-service-claim {label!r} matched "
                    f"{window.strip()[:120]!r}"
                )
                break
    return failures


def _scan_package_strings(out_dir: Path) -> list[str]:
    failures: list[str] = []
    for path in _walk_scan_files(out_dir):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(f"{path}: cannot read ({type(exc).__name__}: {exc})")
            continue
        except UnicodeDecodeError as exc:
            failures.append(f"{path}: not UTF-8 ({exc})")
            continue
        failures.extend(_scan_text_for_unsafe(text, path))
    return failures


# ---------------------------------------------------------------------------
# Re-run the existing read-only validators.
# ---------------------------------------------------------------------------


def _run_subprocess(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, capture_output=True, text=True, check=False,
    )


def _rerun_pptx_validators(
    out_dir: Path, summary: dict
) -> list[str]:
    failures: list[str] = []
    pptx = out_dir / "deck.pptx"
    expected_slides = summary.get("slide_count")

    contract_argv = [
        sys.executable, str(VALIDATE_PPTX_CONTRACT),
        "--pptx", str(pptx),
    ]
    if isinstance(expected_slides, int) and expected_slides >= 1:
        contract_argv += ["--expected-slide-count", str(expected_slides)]
    contract = _run_subprocess(contract_argv)
    if contract.returncode != 0:
        failures.append(
            f"validate_pptx_contract.py rc={contract.returncode}: "
            f"{(contract.stdout or '').strip()[-400:]}"
        )

    with tempfile.TemporaryDirectory(prefix="op-review-inv-") as raw_td:
        td = Path(raw_td)
        inv_out = td / "inventory.json"
        inv = _run_subprocess([
            sys.executable, str(INSPECT_PPTX_INVENTORY),
            "--pptx", str(pptx),
            "--out", str(inv_out),
        ])
        if inv.returncode != 0:
            failures.append(
                f"inspect_pptx_inventory.py rc={inv.returncode}: "
                f"{(inv.stdout or '').strip()[-400:]}"
            )
        if inv_out.is_file():
            inventory, err = _load_json(inv_out)
            if err is not None:
                failures.append(err)
            elif isinstance(inventory, dict):
                # Cross-check the recomputed inventory against the
                # frozen one in the package + the summary.
                recomputed_slides = inventory.get("slide_count")
                if recomputed_slides != expected_slides:
                    failures.append(
                        f"inspect_pptx_inventory recomputed slide_count="
                        f"{recomputed_slides!r} differs from summary.slide_count="
                        f"{expected_slides!r}"
                    )
                media = inventory.get("media_parts") or []
                embedded = summary.get("embedded_media_count")
                if isinstance(embedded, int) and len(media) != embedded:
                    failures.append(
                        f"inspect_pptx_inventory recomputed media_parts count="
                        f"{len(media)} differs from summary.embedded_media_count="
                        f"{embedded!r}"
                    )
                frozen_path = out_dir / "inventory.json"
                frozen, ferr = _load_json(frozen_path)
                if ferr is None and isinstance(frozen, dict):
                    if frozen.get("slide_count") != recomputed_slides:
                        failures.append(
                            f"inventory.json slide_count={frozen.get('slide_count')!r} "
                            f"differs from re-run inspect_pptx_inventory "
                            f"slide_count={recomputed_slides!r}"
                        )
    return failures


# ---------------------------------------------------------------------------
# Top-level driver.
# ---------------------------------------------------------------------------


def _validate_package(out_dir: Path) -> _ValidationResult:
    failures: list[str] = []

    failures.extend(_check_required_paths(out_dir))

    summary_path = out_dir / "summary.json"
    summary: Any = None
    if summary_path.is_file() and not summary_path.is_symlink():
        summary, err = _load_json(summary_path)
        if err is not None:
            failures.append(err)

    inventory_path = out_dir / "inventory.json"
    inventory: Any = None
    if inventory_path.is_file() and not inventory_path.is_symlink():
        inventory, err = _load_json(inventory_path)
        if err is not None:
            failures.append(err)

    vq_path = out_dir / "visual_quality.json"
    vq_report: Any = None
    if vq_path.is_file() and not vq_path.is_symlink():
        vq_report, err = _load_json(vq_path)
        if err is not None:
            failures.append(err)

    if isinstance(summary, dict):
        failures.extend(_check_summary(summary, out_dir))
        if isinstance(inventory, dict):
            failures.extend(_check_inventory_vs_summary(inventory, summary))
        if vq_report is not None:
            failures.extend(_check_visual_quality(vq_report, summary))
        failures.extend(_rerun_pptx_validators(out_dir, summary))

    failures.extend(_scan_package_strings(out_dir))

    return _ValidationResult(failures=failures)


def _print_failures(result: _ValidationResult) -> None:
    for f in result.failures:
        print(f"FAIL: {f}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs inside a per-run tempdir.
# ---------------------------------------------------------------------------


@dataclass
class _ProbeResult:
    name: str
    ok: bool
    detail: str = ""


def _materialize_review_package(td: Path) -> tuple[bool, str, Path]:
    """Drive the operator helper against a synthetic PNG + JPG bundle
    and return ``(ok, detail, out_dir)``. The bundle lives under
    ``td/bundle`` and the produced review package under
    ``td/out``."""
    bundle = td / "bundle"
    images = bundle / "images"
    images.mkdir(parents=True, exist_ok=True)
    # Minimum-viable PNG + JPEG payloads. Byte-distinct so each sha256
    # differs and per-image provenance can attribute embedded media.
    (images / "alpha_marker.png").write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a"
            "0000000d49484452"
            "0000000100000001"
            "08060000001f15c489"
            "0000000d49444154"
            "789c6300010000000500010d0a2db4"
            "0000000049454e44ae426082"
        )
    )
    (images / "beta_marker.jpg").write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
    )
    out_dir = td / "out"
    operator_helper = SCRIPTS_DIR / "operator_local_images_to_editable_ppt.py"
    env = os.environ.copy()
    env.setdefault("TMPDIR", "/tmp")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    proc = subprocess.run(
        [
            sys.executable, str(operator_helper),
            "--bundle", str(bundle),
            "--out-dir", str(out_dir),
        ],
        capture_output=True, text=True, check=False, env=env,
    )
    if proc.returncode != 0:
        return False, (
            f"operator helper rc={proc.returncode}: "
            f"{(proc.stdout or '')[-400:]} | {(proc.stderr or '')[-200:]}"
        ), out_dir
    return True, "", out_dir


def _run_self_tests() -> int:
    print("=== validate_operator_review_package --self-test ===")
    results: list[_ProbeResult] = []

    # T1 happy path: real package produced by the operator helper.
    with tempfile.TemporaryDirectory(prefix="op-review-T1-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T1 happy path setup", False, detail))
        else:
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T1 happy path: real review package validates rc=0",
                result.ok,
                ("first failures: " + "; ".join(result.failures[:3]))
                if not result.ok else "",
            ))

    # T2 missing deck.pptx — refused.
    with tempfile.TemporaryDirectory(prefix="op-review-T2-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T2 missing deck setup", False, detail))
        else:
            (out_dir / "deck.pptx").unlink()
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T2 missing deck.pptx refused",
                (not result.ok) and any("deck.pptx" in f for f in result.failures),
                f"failures={result.failures[:3]!r}",
            ))

    # T3 stale / wrong summary path field — refused.
    with tempfile.TemporaryDirectory(prefix="op-review-T3-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T3 stale path setup", False, detail))
        else:
            summary_path = out_dir / "summary.json"
            data = json.loads(summary_path.read_text())
            data["pptx_path"] = str(out_dir / "elsewhere" / "deck.pptx")
            summary_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T3 stale summary.pptx_path refused",
                (not result.ok) and any("pptx_path" in f for f in result.failures),
                f"failures={result.failures[:3]!r}",
            ))

    # T4 positive real-D-One success claim in README — refused.
    with tempfile.TemporaryDirectory(prefix="op-review-T4-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T4 dialogue setup", False, detail))
        else:
            readme = out_dir / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8")
                + "\n\nReal D-One verified online: production run succeeded.\n",
                encoding="utf-8",
            )
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T4 positive real-D-One success claim refused",
                (not result.ok)
                and any("real_d_one_success" in f for f in result.failures),
                f"failures={result.failures[:5]!r}",
            ))

    # T5 placement_verified flipped to False — refused.
    with tempfile.TemporaryDirectory(prefix="op-review-T5-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T5 placement setup", False, detail))
        else:
            summary_path = out_dir / "summary.json"
            data = json.loads(summary_path.read_text())
            data["image_provenance"][0]["placement_verified"] = False
            summary_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T5 placement_verified=False refused",
                (not result.ok)
                and any("placement_verified" in f for f in result.failures),
                f"failures={result.failures[:3]!r}",
            ))

    # T6 visual_quality.totals.errors > 0 — refused.
    with tempfile.TemporaryDirectory(prefix="op-review-T6-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T6 vq setup", False, detail))
        else:
            vq_path = out_dir / "visual_quality.json"
            data = json.loads(vq_path.read_text())
            data.setdefault("totals", {})["errors"] = 3
            vq_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T6 visual_quality.totals.errors>0 refused",
                (not result.ok)
                and any("visual_quality" in f and "errors" in f for f in result.failures),
                f"failures={result.failures[:3]!r}",
            ))

    # T7 external URL in summary — refused.
    with tempfile.TemporaryDirectory(prefix="op-review-T7-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T7 url setup", False, detail))
        else:
            summary_path = out_dir / "summary.json"
            data = json.loads(summary_path.read_text())
            data["notes"]["scope"] = data["notes"].get("scope", "") + " see https://example.invalid/x"
            summary_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T7 external URL in summary refused",
                (not result.ok)
                and any("URI-shaped scheme" in f for f in result.failures),
                f"failures={result.failures[:3]!r}",
            ))

    # T8 credential token in README — refused.
    with tempfile.TemporaryDirectory(prefix="op-review-T8-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T8 credential setup", False, detail))
        else:
            readme = out_dir / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8")
                + "\n\ntoken=abc123def456\n",
                encoding="utf-8",
            )
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T8 credential token in README refused",
                (not result.ok)
                and any("token_assignment" in f for f in result.failures),
                f"failures={result.failures[:3]!r}",
            ))

    # T9 public-hosting wording in README — refused.
    with tempfile.TemporaryDirectory(prefix="op-review-T9-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T9 hosting setup", False, detail))
        else:
            readme = out_dir / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8")
                + "\n\nPublic hosting enabled.\n",
                encoding="utf-8",
            )
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T9 public-hosting wording refused",
                (not result.ok)
                and any("public_hosting" in f for f in result.failures),
                f"failures={result.failures[:3]!r}",
            ))

    # T10 summary.approved_plan key missing — refused (tampered summary
    # cannot silently erase the approved-plan lock).
    with tempfile.TemporaryDirectory(prefix="op-review-T10-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T10 ap-missing setup", False, detail))
        else:
            summary_path = out_dir / "summary.json"
            data = json.loads(summary_path.read_text())
            data.pop("approved_plan", None)
            summary_path.write_text(
                json.dumps(data, indent=2, sort_keys=True) + "\n",
            )
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T10 summary.approved_plan key missing refused",
                (not result.ok)
                and any(
                    "approved_plan missing" in f for f in result.failures
                ),
                f"failures={result.failures[:3]!r}",
            ))

    # T11 summary.approved_plan.matched=False — refused (a clean run can
    # only produce matched=True; the helper refuses with rc 2 before
    # summary creation on mismatch).
    with tempfile.TemporaryDirectory(prefix="op-review-T11-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T11 ap-matched setup", False, detail))
        else:
            summary_path = out_dir / "summary.json"
            data = json.loads(summary_path.read_text())
            data["approved_plan"] = {
                "path": "/tmp/fake_approved_plan.json",
                "sha256": "0" * 64,
                "matched": False,
            }
            summary_path.write_text(
                json.dumps(data, indent=2, sort_keys=True) + "\n",
            )
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T11 summary.approved_plan.matched=False refused",
                (not result.ok)
                and any(
                    "approved_plan.matched" in f for f in result.failures
                ),
                f"failures={result.failures[:3]!r}",
            ))

    # T12 summary.approved_plan.sha256 not 64-char lowercase hex —
    # refused (reviewers must be able to confirm via sha256sum).
    with tempfile.TemporaryDirectory(prefix="op-review-T12-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T12 ap-sha setup", False, detail))
        else:
            summary_path = out_dir / "summary.json"
            data = json.loads(summary_path.read_text())
            data["approved_plan"] = {
                "path": "/tmp/fake_approved_plan.json",
                "sha256": "NOT-HEX",
                "matched": True,
            }
            summary_path.write_text(
                json.dumps(data, indent=2, sort_keys=True) + "\n",
            )
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T12 summary.approved_plan.sha256 malformed refused",
                (not result.ok)
                and any(
                    "approved_plan.sha256" in f for f in result.failures
                ),
                f"failures={result.failures[:3]!r}",
            ))

    # T13 summary.approved_plan with unknown extra key — refused.
    with tempfile.TemporaryDirectory(prefix="op-review-T13-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T13 ap-extra setup", False, detail))
        else:
            summary_path = out_dir / "summary.json"
            data = json.loads(summary_path.read_text())
            data["approved_plan"] = {
                "path": "/tmp/fake_approved_plan.json",
                "sha256": "a" * 64,
                "matched": True,
                "unexpected": "value",
            }
            summary_path.write_text(
                json.dumps(data, indent=2, sort_keys=True) + "\n",
            )
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T13 summary.approved_plan unknown key refused",
                (not result.ok)
                and any(
                    "approved_plan has unknown key" in f
                    for f in result.failures
                ),
                f"failures={result.failures[:3]!r}",
            ))

    # T14 dangerous single-colon URI scheme (data: / mailto: / javascript:)
    # in README — refused. The original ``://``-anchored URI scheme regex
    # misses these (no double slash), so this probe pins the dangerous-
    # scheme detector to a real-package scenario.
    with tempfile.TemporaryDirectory(prefix="op-review-T14-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T14 data-uri setup", False, detail))
        else:
            readme = out_dir / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8")
                + "\n\nEmbedded cover: data:image/png;base64,iVBORw0KGgo=.\n"
                + "Contact: mailto:operator@example.invalid.\n"
                + "Trigger: javascript:alert(1).\n",
                encoding="utf-8",
            )
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T14 dangerous single-colon URI scheme (data:/mailto:/javascript:) refused",
                (not result.ok)
                and any("'data'" in f and "dangerous" in f for f in result.failures)
                and any("'mailto'" in f and "dangerous" in f for f in result.failures)
                and any("'javascript'" in f and "dangerous" in f for f in result.failures),
                f"failures={result.failures[:5]!r}",
            ))

    # T15 file: URI-shaped local path in README — refused. ``file:/foo``
    # (single slash) and ``file:relative.txt`` (no slash) both bypass
    # the ``://``-anchored URI scheme regex, and the older word-boundary
    # ``\bfile:\b`` check silently false-negated them (the trailing
    # ``\b`` cannot match between non-word ``:`` and non-word ``/``).
    # ``file`` is now on the dangerous-scheme deny-list so both shapes
    # are refused.
    with tempfile.TemporaryDirectory(prefix="op-review-T15-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T15 file-uri setup", False, detail))
        else:
            readme = out_dir / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8")
                + "\n\nSee file:/etc/passwd for context.\n"
                + "Also file:relative_path.txt for sibling case.\n",
                encoding="utf-8",
            )
            result = _validate_package(out_dir)
            file_hits = [
                f for f in result.failures
                if "'file'" in f and "dangerous" in f
            ]
            results.append(_ProbeResult(
                "T15 file: URI single-slash + relative shapes refused",
                (not result.ok) and len(file_hits) >= 2,
                f"failures={result.failures[:5]!r}; file_hits={file_hits!r}",
            ))

    # T16 tampered summary.registry_path points outside --out-dir —
    # refused. The path is one of the contract fields the helper writes
    # into summary.json; an attacker rerouting it to a forged
    # ``source_image_assets.json`` outside the package must not slip
    # past the validator with rc=0.
    with tempfile.TemporaryDirectory(prefix="op-review-T16-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T16 registry_path setup", False, detail))
        else:
            outside_dir = td / "elsewhere"
            outside_dir.mkdir()
            outside = outside_dir / "source_image_assets.json"
            outside.write_text("{}\n", encoding="utf-8")
            summary_path = out_dir / "summary.json"
            data = json.loads(summary_path.read_text())
            data["registry_path"] = str(outside)
            summary_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T16 tampered summary.registry_path outside --out-dir refused",
                (not result.ok)
                and any(
                    "registry_path" in f and "does not resolve under" in f
                    for f in result.failures
                ),
                f"failures={result.failures[:5]!r}",
            ))

    # T17 tampered summary.visual_quality.path points outside --out-dir —
    # refused. ``visual_quality.path`` is nested under
    # summary.visual_quality so the validator must reach into the nested
    # object; an attacker pointing it at a forged ``visual_quality.json``
    # outside the package must not slip past with rc=0.
    with tempfile.TemporaryDirectory(prefix="op-review-T17-") as raw_td:
        td = Path(raw_td)
        ok, detail, out_dir = _materialize_review_package(td)
        if not ok:
            results.append(_ProbeResult("T17 vq.path setup", False, detail))
        else:
            outside_dir = td / "elsewhere"
            outside_dir.mkdir()
            outside = outside_dir / "visual_quality.json"
            outside.write_text("{}\n", encoding="utf-8")
            summary_path = out_dir / "summary.json"
            data = json.loads(summary_path.read_text())
            data["visual_quality"]["path"] = str(outside)
            summary_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
            result = _validate_package(out_dir)
            results.append(_ProbeResult(
                "T17 tampered summary.visual_quality.path outside --out-dir refused",
                (not result.ok)
                and any(
                    "visual_quality.path" in f and "does not resolve under" in f
                    for f in result.failures
                ),
                f"failures={result.failures[:5]!r}",
            ))

    rc = 0
    for r in results:
        marker = "[PASS]" if r.ok else "[FAIL]"
        print(f"{marker} {r.name}")
        if not r.ok and r.detail:
            print(f"       {r.detail}")
            rc = 1
    if rc == 0:
        print(f"=== validate_operator_review_package --self-test: {len(results)} probes passed ===")
    else:
        print(f"=== validate_operator_review_package --self-test: {sum(1 for r in results if not r.ok)} failure(s) ===")
    return rc


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_operator_review_package.py",
        description=(
            "Read-only stdlib validator for the operator review "
            "package produced by "
            "scripts/operator_local_images_to_editable_ppt.py (the "
            "--out-dir / --bundle output). Confirms the package on "
            "disk still matches the helper's truth-checked summary; "
            "does NOT mutate the package, does NOT rebuild the "
            "pipeline, does NOT call D-One, MCP, Qoder, a public "
            "network, telemetry, a model API, or an image search."
        ),
    )
    parser.add_argument(
        "--out-dir", type=str, default=None,
        help=(
            "Operator review package directory to validate. Must be a "
            "regular non-symlink directory. The validator never writes "
            "to it."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run the in-script tempfixture scenarios: happy path "
            "against a real operator review package + every documented "
            "tamper probe. Mutually exclusive with --out-dir."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if args.out_dir is not None:
            print("FAIL: --self-test does not take --out-dir", file=sys.stderr)
            return 2
        return _run_self_tests()

    if not args.out_dir:
        print(
            "FAIL: --out-dir is required (or use --self-test).",
            file=sys.stderr,
        )
        return 2

    out_dir, shape_failures = _validate_out_dir_arg(args.out_dir)
    if out_dir is None:
        for line in shape_failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 2

    result = _validate_package(out_dir)
    if result.ok:
        print(f"OK: operator review package at {out_dir} validates.")
        return 0
    _print_failures(result)
    print(f"FAIL: {len(result.failures)} gate failure(s) in {out_dir}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
