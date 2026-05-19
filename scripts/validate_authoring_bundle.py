#!/usr/bin/env python3
"""Pre-pipeline authoring quality gate for explicit-input spec bundles.

**This is a narrow bridge contract, NOT a full prompt/report/Markdown-to-PPTX
automation.** It validates an authoring bundle the caller has already
written (brief metadata + ``--plan-spec`` deck_plan + design_system input
+ ``--slide-specs-dir`` slide_plans + ``--image-manifest-spec`` image_manifest)
against the structural rules every Stage-2-through-6 ``init_*.py`` helper
would re-apply at runtime. The bundle's content comes from the caller; the
gate never invents brief fields, deck_plan slides, design tokens, slide
bodies, or image manifest entries from raw source text. The bridge it
provides is *authoring-time → Stage-1 workspace*: confirm the bundle is
structurally consistent so a six-stage prep run is not wasted.

Takes the same explicit caller-supplied inputs ``scripts/run_explicit_pipeline.py``
accepts (``--source`` plus ``--title`` / ``--audience`` / ``--objective``
plus ``--plan-spec`` plus ``--design-system-spec`` OR ``--theme-from-template``
plus ``--template-root`` plus ``--slide-specs-dir`` plus ``--image-manifest-spec``)
and validates them **structurally** before any workspace is created. The goal
is to let an agent-authored bundle fail at authoring time rather than after a
six-stage prep run.

This is **a validation gate, not generation**. The script NEVER:

  - creates or modifies a workspace, ``deck_brief.json``, ``deck_plan.json``,
    ``design_system.json``, ``slide_plans/*.json``, ``image_manifest.json``,
    ``render_models/*.json``, ``svg_previews/*.svg``, or any ``.pptx``;
  - extracts business content from ``--source`` — it reads source bytes only
    for byte-level integrity (UTF-8 decode + non-empty) AND for a narrow
    "raw-source-leakage into image_manifest prompt-like fields" scan;
  - calls D-One / Qoder / any public network / image generation / telemetry /
    external service / model API. The script is stdlib-only and offline;
  - implements full prompt/report/Markdown-to-PPTX automation. The bridge
    contract is intentionally narrow: it cross-checks bundle parts the
    caller already wrote, including the `source_refs` chain linking
    slide.source_refs back to the single-element brief.source_refs the
    Stage-1 ``source_manifest.source.id`` will write. Bundles that
    overclaim prompt-to-PPTX automation (``ai-generated``, ``model-generated``,
    ``prompt-to-pptx``, ``automatic prompt-to-`` markers, etc. in any spec
    field) fail closed alongside the network / model-API token scan below.

Gate behavior
-------------
Each check emits one or more *findings*. A finding has a severity:

  - ``ERROR`` — bundle would fail the runtime pipeline, OR violates a
    privacy / clean-room rule the agent owns. The gate exits non-zero.
  - ``WARN``  — agent should review before running, but the bundle is not
    structurally invalid (e.g. a ``chart_ref`` block that the current
    render-model generator cannot project). The gate exits 0 unless
    ``--strict`` is passed (which promotes every WARN to ERROR).

Exit codes:

  - ``0`` — bundle passed (no ERROR findings; WARN allowed).
  - ``1`` — at least one ERROR finding (or any WARN under ``--strict``).
  - ``2`` — invocation error (missing required argument, both/neither mode
    flags, ``--self-test`` mixed with orchestration flags, ...).

What this gate does NOT do
--------------------------
This is a structural pre-flight only. It does **not** stand in for:

  - source fidelity (every slide title / kpi / table cell traces to its
    declared ``source_refs``);
  - sensitive-data handling (no real customer / account / employee names
    unless the user explicitly approved);
  - clean-room discipline (no content from ``ppt-master`` or any similarly
    named prior implementation).

Those remain agent-managed per ``references/authoring-workflow.md``. The
machine-checked gates downstream (``init_*.py`` helpers, ``validate_workspace``,
``validate_pptx_contract``) re-enforce every structural rule this gate
checks; running this gate first just saves a six-stage retry.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "schemas"

sys.path.insert(0, str(SCRIPTS_DIR))

from validate_artifacts import _validate  # noqa: E402
from validate_scaffold import (  # noqa: E402
    local_path_is_safe,
    _resolves_within,
    _slide_plan_against_layout,
)

# Lazy-import the render-model generator's supported-layout tuple so the
# authoring gate and the generator stay in sync (mirrors the lazy import
# in scripts/validate_workspace.py::check_generator_render_model_coverage).
from generate_render_models import SUPPORTED_LAYOUTS as _RENDER_SUPPORTED_LAYOUTS  # noqa: E402

DECK_PLAN_SCHEMA = SCHEMAS_DIR / "deck_plan.schema.json"
DESIGN_SYSTEM_SCHEMA = SCHEMAS_DIR / "design_system.schema.json"
SLIDE_PLAN_SCHEMA = SCHEMAS_DIR / "slide_plan.schema.json"
IMAGE_MANIFEST_SCHEMA = SCHEMAS_DIR / "image_manifest.schema.json"
TEMPLATE_SCHEMA = SCHEMAS_DIR / "template.schema.json"
LAYOUT_SCHEMA = SCHEMAS_DIR / "layout.schema.json"

# Source id pattern — mirrors init_workspace._SOURCE_ID_PATTERN exactly so a
# bundle this gate passes can use the same id at Stage 1 without surprise.
_SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Forbidden-content tokens we scan every spec JSON body for. These are the
# clean-room / privacy / no-network policy markers from CLAUDE.md +
# references/authoring-workflow.md. The list is intentionally narrow: it
# catches the obvious "the agent leaked a model/api/network claim into a
# spec" failure mode, not every possible bad string. Each entry is a tuple
# (needle, severity, why) so the diagnostic explains the rule.
_FORBIDDEN_TOKENS: tuple[tuple[str, str, str], ...] = (
    ("http://",   "ERROR", "URL scheme in spec (no public network is allowed)"),
    ("https://",  "ERROR", "URL scheme in spec (no public network is allowed)"),
    ("file://",   "ERROR", "URL scheme in spec (no file:// references allowed)"),
    ("s3://",     "ERROR", "URL scheme in spec (no S3 references allowed)"),
    ("ftp://",    "ERROR", "URL scheme in spec (no FTP references allowed)"),
    ("data:",     "ERROR", "data: URI in spec (no embedded data URIs allowed)"),
    ("mailto:",   "ERROR", "mailto: URI in spec (no email references allowed)"),
    ("d-one",     "ERROR", "D-One image generation is not implemented in this repo"),
    ("d_one",     "ERROR", "D-One image generation is not implemented in this repo"),
    ("qoder",     "ERROR", "Qoder runtime is not implemented in this repo"),
    ("openai",    "ERROR", "no model-API references allowed in specs"),
    ("anthropic", "ERROR", "no model-API references allowed in specs"),
    ("api_key",   "ERROR", "no credential-shaped strings allowed in specs"),
    ("telemetry", "ERROR", "no telemetry references allowed in specs"),
    # Overclaim-of-automation tokens. The repo's bridge contract turns an
    # explicit authoring bundle into a workspace; it is NOT a prompt/report/
    # Markdown-to-PPTX automation. Specs that claim AI-generated, model-
    # generated, or prompt-to-PPTX automation contradict the contract and
    # fail closed here so the agent fixes the claim before invoking the
    # runtime pipeline. Substrings are intentionally specific (hyphenated
    # / phrase-shaped) so they do not collide with the legitimate word
    # "generate" used in helper / pipeline / stage descriptions.
    ("ai-generated",        "ERROR", "overclaim: this repo is a bridge contract, not an AI generator"),
    ("model-generated",     "ERROR", "overclaim: this repo is a bridge contract, not a model-driven generator"),
    ("prompt-to-pptx",      "ERROR", "overclaim: this repo is a bridge contract, not a prompt-to-PPTX automation"),
    ("prompt-to-ppt",       "ERROR", "overclaim: this repo is a bridge contract, not a prompt-to-PPT automation"),
    ("prompt-to-deck",      "ERROR", "overclaim: this repo is a bridge contract, not a prompt-to-deck automation"),
    ("automatic prompt-to", "ERROR", "overclaim: this repo is a bridge contract, not a prompt-to-* automation"),
)

# Phrases that indicate a full-slide raster / background-image intent. Only
# scanned in image_manifest narrative fields (alt_text / intended_use) and
# in slide_plan notes — these are the fields where such an intent is
# expressible (and forbidden by SECURITY.md + references/d-one-image-policy.md).
_FULL_SLIDE_PHRASES: tuple[str, ...] = (
    "full-slide background",
    "full slide background",
    "full-slide raster",
    "full slide raster",
    "fullslide background",
    "background image",
    "background-image",
    "screenshot of slide",
    "screenshot of the slide",
    "image as background",
)


@dataclass
class Finding:
    severity: str  # "ERROR" or "WARN"
    name: str
    detail: str = ""


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: str, name: str, detail: str = "") -> None:
        self.findings.append(Finding(severity=severity, name=name, detail=detail))

    def err(self, name: str, detail: str = "") -> None:
        self.add("ERROR", name, detail)

    def warn(self, name: str, detail: str = "") -> None:
        self.add("WARN", name, detail)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "ERROR"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "WARN"]

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Loaders. Each returns either the parsed JSON object OR appends one or more
# findings and returns None. A finding here is fatal for downstream checks
# that need the parsed value — those checks bail out cleanly rather than
# tracebacking on a None.
# ---------------------------------------------------------------------------


def _has_uri_scheme(s: str) -> bool:
    return bool(_URI_SCHEME_PREFIX.match(s))


def _load_json_file(
    path: Path, label: str, report: Report, *, require_object: bool = True,
) -> object | None:
    """Read + parse a JSON file. Returns the parsed value on success, None
    on any failure (with one or more findings already added). Refuses
    URI-shaped paths, missing files, non-regular files, and symlinks —
    every guard the downstream init_* helpers apply to their inputs."""
    if _has_uri_scheme(str(path)):
        report.err(
            f"{label}: path looks like a URI",
            f"{path} — only local file paths are accepted",
        )
        return None
    if path.is_symlink():
        try:
            target = str(path.readlink())
        except OSError:
            target = "<unreadable>"
        report.err(
            f"{label}: path is a symlink",
            f"{path} -> {target}; refusing to follow it (broken or not)",
        )
        return None
    if not path.exists():
        report.err(f"{label}: file does not exist", str(path))
        return None
    if not path.is_file():
        report.err(f"{label}: not a regular file", str(path))
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        report.err(f"{label}: cannot read as UTF-8", f"{path}: {exc}")
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        report.err(f"{label}: malformed JSON", f"{path}: {exc}")
        return None
    if require_object and not isinstance(value, dict):
        report.err(
            f"{label}: top-level value is not a JSON object",
            f"{path}: got {type(value).__name__}",
        )
        return None
    return value


def _schema_validate(
    value: object, schema_path: Path, label: str, report: Report,
) -> bool:
    """Schema-validate in memory. Adds one ERROR finding per schema error.
    Returns True iff the value validated."""
    try:
        schema = json.loads(schema_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        report.err(
            f"{label}: cannot load schema {schema_path.name}",
            str(exc),
        )
        return False
    errors: list[str] = []
    _validate(value, schema, "<root>", errors)
    if errors:
        for e in errors:
            report.err(f"{label}: schema {schema_path.name}", e)
        return False
    return True


# ---------------------------------------------------------------------------
# Source + brief metadata. Mirror init_workspace._validate_source_file and
# init_deck_brief's required-flag checks without writing anything.
# ---------------------------------------------------------------------------


def _check_source(source: Path, report: Report) -> bytes | None:
    """Return the source bytes when accepted; None when a fatal finding
    was added. Mirrors init_workspace._validate_source_file."""
    if _has_uri_scheme(str(source)):
        report.err("source: path looks like a URI", str(source))
        return None
    if source.is_symlink():
        report.err("source: path is a symlink", str(source))
        return None
    if not source.exists():
        report.err("source: file does not exist", str(source))
        return None
    if not source.is_file():
        report.err("source: not a regular file", str(source))
        return None
    suffix = source.suffix.lower()
    if suffix not in {".md", ".txt"}:
        report.err(
            "source: unsupported extension",
            f"{source}: only .md and .txt are accepted (got {suffix!r})",
        )
        return None
    try:
        raw = source.read_bytes()
    except OSError as exc:
        report.err("source: cannot read bytes", f"{source}: {exc}")
        return None
    if not raw:
        report.err(
            "source: file is empty",
            f"{source}: init_workspace requires at least one line",
        )
        return None
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        report.err("source: not valid UTF-8", f"{source}: {exc}")
        return None
    return raw


def _resolve_source_id(source_id: str | None, source: Path, report: Report) -> str | None:
    """Return a derived source_id matching init_workspace._resolve_source_id.
    Validates against the schema pattern AND local_path_is_safe."""
    candidate = source_id if source_id is not None else source.stem
    if not candidate:
        report.err(
            "source_id: empty",
            f"--source-id is empty and could not be derived from {source} stem",
        )
        return None
    if not _SOURCE_ID_PATTERN.match(candidate):
        report.err(
            "source_id: does not match schema pattern",
            f"{candidate!r} fails ^[A-Za-z0-9][A-Za-z0-9_.\\-]*$",
        )
        return None
    if not local_path_is_safe(candidate):
        report.err(
            "source_id: fails path-safety",
            f"{candidate!r} would be rejected by local_path_is_safe",
        )
        return None
    return candidate


def _check_brief_metadata(
    title: str, audience: str, objective: str,
    tone: str | None, language: str | None,
    approximate_slide_count: int | None,
    report: Report,
) -> None:
    """Mirror init_deck_brief._validate_single_line_string verbatim: each
    required flag must be a string, non-empty after .strip() (so a
    whitespace-only value like ' ' / '\\t' / '\\n' is refused — the schema
    layer's minLength:1 would silently accept those), and free of embedded
    newlines / carriage returns."""
    for name, value in (("title", title), ("audience", audience), ("objective", objective)):
        if not isinstance(value, str):
            report.err(
                f"brief.{name}: not a string",
                f"--{name} must be a string (got {type(value).__name__})",
            )
            continue
        if not value.strip():
            report.err(
                f"brief.{name}: empty after stripping whitespace",
                f"--{name} must be non-empty after .strip(); got {value!r}",
            )
            continue
        if "\n" in value or "\r" in value:
            report.err(
                f"brief.{name}: contains newline",
                f"--{name} must be a single line; got {value!r}",
            )
    # Optional flags: same .strip()-empty + newline rules when supplied.
    # init_deck_brief routes tone / language through the same validator.
    for name, value in (("tone", tone), ("language", language)):
        if value is None:
            continue
        if not isinstance(value, str):
            report.err(
                f"brief.{name}: not a string",
                f"--{name} must be a string (got {type(value).__name__})",
            )
            continue
        if not value.strip():
            report.err(
                f"brief.{name}: empty after stripping whitespace",
                f"--{name} must be non-empty after .strip() (or omit it); "
                f"got {value!r}",
            )
            continue
        if "\n" in value or "\r" in value:
            report.err(
                f"brief.{name}: contains newline",
                f"--{name} must be a single line; got {value!r}",
            )
    if approximate_slide_count is not None and approximate_slide_count < 1:
        report.err(
            "brief.approximate_slide_count: not positive",
            f"got {approximate_slide_count}; minimum is 1",
        )


# ---------------------------------------------------------------------------
# Plan-shape preflight. Runs after deck_plan schema validation. Schema
# errors may be generic ("expected array, got string"); this preflight
# names the downstream consequence (which semantic checks will skip) and
# returns flags so the caller can SKIP every dependent semantic check
# rather than letting it traceback on a wrong-shape field.
# ---------------------------------------------------------------------------


def _preflight_plan_shape(plan: dict, report: Report) -> dict[str, bool]:
    """Return {'slides_ok', 'sections_ok', 'planning_ok'} after verifying
    ``plan['slides']`` is a list of JSON objects, ``plan['sections']`` is a
    list of JSON objects, and ``plan['planning']`` is a JSON object. Adds
    one ERROR finding per shape problem so the agent sees what to fix and
    knows which downstream semantic check was skipped because of it."""
    flags = {"slides_ok": False, "sections_ok": False, "planning_ok": False}

    slides = plan.get("slides")
    if slides is None:
        report.err(
            "plan_spec.slides: missing",
            "deck_plan must declare a slides[] array",
        )
    elif not isinstance(slides, list):
        report.err(
            "plan_spec.slides: not a list",
            f"got {type(slides).__name__}; downstream slide semantic "
            f"checks will be skipped",
        )
    else:
        bad = [
            (i, type(s).__name__)
            for i, s in enumerate(slides) if not isinstance(s, dict)
        ]
        if bad:
            report.err(
                "plan_spec.slides: non-object entries",
                f"slides at positions {[i for i, _ in bad]} are not JSON "
                f"objects (got types {[t for _, t in bad]}); downstream "
                f"slide semantic checks will be skipped",
            )
        else:
            flags["slides_ok"] = True

    sections = plan.get("sections")
    if sections is None:
        report.err(
            "plan_spec.sections: missing",
            "deck_plan must declare a sections[] array",
        )
    elif not isinstance(sections, list):
        report.err(
            "plan_spec.sections: not a list",
            f"got {type(sections).__name__}; downstream section semantic "
            f"checks will be skipped",
        )
    else:
        bad = [
            (i, type(s).__name__)
            for i, s in enumerate(sections) if not isinstance(s, dict)
        ]
        if bad:
            report.err(
                "plan_spec.sections: non-object entries",
                f"sections at positions {[i for i, _ in bad]} are not JSON "
                f"objects (got types {[t for _, t in bad]}); downstream "
                f"section semantic checks will be skipped",
            )
        else:
            flags["sections_ok"] = True

    planning = plan.get("planning")
    if planning is None:
        report.err(
            "plan_spec.planning: missing",
            "deck_plan must declare a planning object",
        )
    elif not isinstance(planning, dict):
        report.err(
            "plan_spec.planning: not an object",
            f"got {type(planning).__name__}; downstream planning semantic "
            f"checks will be skipped",
        )
    else:
        flags["planning_ok"] = True

    return flags


# ---------------------------------------------------------------------------
# Planner-semantics cross-check (ported from init_deck_plan).
# The brief_source_refs we cross-check against is the SINGLE-element list
# init_deck_brief.py writes: [source_manifest.source.id]. The gate uses the
# derived source_id (from _resolve_source_id) for that comparison.
# ---------------------------------------------------------------------------


def _cross_check_planner_semantics(
    plan: dict, brief_source_refs: list[str],
) -> list[str]:
    """Verbatim cross-check from init_deck_plan._cross_check_planner_semantics
    — re-implemented here so this gate has no hard dependency on whether
    init_deck_plan can be safely imported from this script's location. The
    rule set must stay in lockstep with init_deck_plan; the self-test runs
    the same scenarios init_deck_plan does.

    Callers MUST first verify the top-level shape of ``plan`` via
    ``_preflight_plan_shape`` (slides is a list of dicts, sections is a
    list of dicts, planning is a dict). The function additionally guards
    every nested field a malformed schema could leave wrong-shape so
    none of the set / sort / membership operations below can traceback:

      - ``section.slide_indices`` / ``slide.source_refs`` must be lists
        before iteration; non-list values produce one error string and
        the iteration is skipped;
      - ``slide.index`` / ``slide.section_id`` / individual
        ``slide_indices`` items / individual ``source_refs`` items that
        are unhashable (list/dict) produce an error string and are
        omitted from the relevant set / membership check;
      - every ``sorted(...)`` call falls back to an unsorted listing
        when its inputs would mix unorderable types (e.g. ``int``
        alongside ``str`` or ``None`` after a schema violation)."""
    errors: list[str] = []
    slides = plan.get("slides") or []
    sections = plan.get("sections") or []
    planning = plan.get("planning") or {}

    def _hashable(value: object) -> bool:
        try:
            hash(value)
        except TypeError:
            return False
        return True

    def _safe_sorted(values):
        try:
            return sorted(values)
        except TypeError:
            return list(values)

    planned = planning.get("planned_slide_count")
    if planned != len(slides):
        errors.append(
            f"planning.planned_slide_count ({planned}) must equal "
            f"len(slides) ({len(slides)})"
        )

    indices_raw = [s.get("index") for s in slides]
    indices: list = []
    unhashable_index_positions: list[int] = []
    for i, idx in enumerate(indices_raw):
        if _hashable(idx):
            indices.append(idx)
        else:
            unhashable_index_positions.append(i)
    if unhashable_index_positions:
        errors.append(
            f"slides[].index has unhashable value(s) at position(s) "
            f"{unhashable_index_positions} (types "
            f"{[type(indices_raw[i]).__name__ for i in unhashable_index_positions]}); "
            f"index must be a positive integer — affected slides are "
            f"skipped from uniqueness / coverage checks"
        )
    if len(set(indices)) != len(indices):
        dup_set = {i for i in indices if indices.count(i) > 1}
        errors.append(f"slides[].index has duplicates: {_safe_sorted(dup_set)}")
    expected = list(range(1, len(slides) + 1))
    sorted_indices = _safe_sorted(indices)
    if sorted_indices != expected:
        errors.append(
            f"slides[].index must be contiguous 1..{len(slides)}; "
            f"got {sorted_indices}"
        )

    slide_index_set = set(indices)
    section_index_union: set = set()
    section_problems: list[str] = []
    section_by_id: dict[str, dict] = {}
    for sec in sections:
        sid = sec.get("id")
        if isinstance(sid, str):
            if sid in section_by_id:
                section_problems.append(f"section id {sid!r} appears more than once")
            else:
                section_by_id[sid] = sec
        seen_local: set = set()
        sec_slide_indices = sec.get("slide_indices")
        if sec_slide_indices is None:
            sec_slide_indices = []
        elif not isinstance(sec_slide_indices, list):
            section_problems.append(
                f"section {sid!r}: slide_indices is not a list (got "
                f"{type(sec_slide_indices).__name__}); skipping "
                f"coverage check for this section"
            )
            sec_slide_indices = []
        for idx in sec_slide_indices:
            if not _hashable(idx):
                section_problems.append(
                    f"section {sid!r}: slide_indices contains an "
                    f"unhashable value (got {type(idx).__name__}); "
                    f"skipping this entry"
                )
                continue
            if idx in seen_local:
                section_problems.append(
                    f"section {sid!r}: slide_indices has duplicate {idx}"
                )
            seen_local.add(idx)
            if idx in section_index_union:
                section_problems.append(
                    f"slide index {idx} appears in more than one section"
                )
            section_index_union.add(idx)
    if section_problems:
        errors.extend(section_problems)
    missing_from_sections = _safe_sorted(slide_index_set - section_index_union)
    if missing_from_sections:
        errors.append(
            f"sections do not cover deck_plan slides: missing {missing_from_sections}"
        )
    orphan_section_indices = _safe_sorted(section_index_union - slide_index_set)
    if orphan_section_indices:
        errors.append(
            f"sections list slide indices the deck_plan does not declare: "
            f"{orphan_section_indices}"
        )

    brief_refs_set = set(brief_source_refs)
    for s in slides:
        idx = s.get("index")
        sid = s.get("section_id")
        if not _hashable(sid):
            errors.append(
                f"slide index {idx}: section_id is not hashable (got "
                f"{type(sid).__name__}); skipping section-id resolution check"
            )
        elif sid not in section_by_id:
            errors.append(
                f"slide index {idx}: section_id {sid!r} not declared in sections "
                f"(known: {_safe_sorted(section_by_id)})"
            )
        else:
            sec_indices = section_by_id[sid].get("slide_indices")
            if not isinstance(sec_indices, list):
                # Already reported in the section loop above; treat as empty
                # so the per-slide membership check cannot traceback.
                sec_indices = []
            if idx not in sec_indices:
                errors.append(
                    f"slide index {idx}: not listed in section "
                    f"{sid!r}.slide_indices ({sec_indices})"
                )
        slide_source_refs = s.get("source_refs")
        if slide_source_refs is None:
            slide_source_refs = []
        elif not isinstance(slide_source_refs, list):
            errors.append(
                f"slide index {idx}: source_refs is not a list (got "
                f"{type(slide_source_refs).__name__}); skipping "
                f"source-ref coverage for this slide"
            )
            slide_source_refs = []
        for ref in slide_source_refs:
            if not _hashable(ref):
                errors.append(
                    f"slide index {idx}: source_refs contains an unhashable "
                    f"value (got {type(ref).__name__}); skipping this entry"
                )
                continue
            if ref not in brief_refs_set:
                errors.append(
                    f"slide index {idx}: source_ref {ref!r} not declared in "
                    f"deck_brief.source_refs (known: {_safe_sorted(brief_refs_set)})"
                )
    return errors


# ---------------------------------------------------------------------------
# Template / layout cross-checks.
# ---------------------------------------------------------------------------


def _check_template_root(template_root: Path, report: Report) -> bool:
    if _has_uri_scheme(str(template_root)):
        report.err("template_root: looks like a URI", str(template_root))
        return False
    if template_root.is_symlink():
        report.err("template_root: is a symlink", str(template_root))
        return False
    if not template_root.exists():
        report.err("template_root: does not exist", str(template_root))
        return False
    if not template_root.is_dir():
        report.err("template_root: not a directory", str(template_root))
        return False
    return True


def _check_plan_template_chain(
    plan: dict, template_root: Path, report: Report,
) -> tuple[dict | None, dict[str, dict] | None]:
    """Resolve plan.template under template_root. Schema-validates the
    template manifest AND every layout under templates/<name>/layouts/.
    Returns (template_manifest, layouts_by_name) or (None, None) on
    failure. layouts_by_name only contains schema-valid layouts."""
    name = plan.get("template")
    if not isinstance(name, str) or not name:
        # The schema check would already have surfaced this; bail out
        # silently here to avoid double-reporting.
        return None, None
    if not local_path_is_safe(name):
        report.err(
            "plan.template: fails path-safety",
            f"{name!r} would be rejected by local_path_is_safe",
        )
        return None, None
    if not _resolves_within(template_root, name):
        report.err(
            "plan.template: escapes --template-root",
            f"{name!r} does not resolve inside {template_root}",
        )
        return None, None
    template_dir = template_root / name
    if template_dir.is_symlink():
        report.err(
            "plan.template: target is a symlink",
            f"{template_dir}; refusing to follow it",
        )
        return None, None
    if not template_dir.is_dir():
        report.err(
            "plan.template: directory missing",
            f"no template at {template_dir}",
        )
        return None, None
    manifest_path = template_dir / "template.json"
    manifest = _load_json_file(manifest_path, f"template.{name}", report)
    if not isinstance(manifest, dict):
        return None, None
    if not _schema_validate(manifest, TEMPLATE_SCHEMA, f"template.{name}", report):
        return None, None
    layouts_dir = template_dir / "layouts"
    if layouts_dir.is_symlink():
        report.err(
            "plan.template: layouts/ is a symlink",
            f"{layouts_dir}; refusing to follow it",
        )
        return None, None
    if not layouts_dir.is_dir():
        report.err(
            "plan.template: layouts/ missing",
            f"no layouts directory at {layouts_dir}",
        )
        return None, None
    declared = manifest.get("layouts") or []
    used_layouts = {s.get("layout") for s in (plan.get("slides") or [])}
    layouts_by_name: dict[str, dict] = {}
    for layout_name in sorted({n for n in used_layouts if isinstance(n, str) and n}):
        if layout_name not in declared:
            report.err(
                f"plan.layout: {layout_name!r} not declared by template "
                f"{name!r}",
                f"template.layouts = {sorted(declared)}",
            )
            continue
        if not local_path_is_safe(layout_name) or not _resolves_within(layouts_dir, f"{layout_name}.json"):
            report.err(
                f"plan.layout: {layout_name!r} unsafe layout name",
                "refusing to resolve outside the template's layouts/ directory",
            )
            continue
        layout_file = layouts_dir / f"{layout_name}.json"
        if layout_file.is_symlink():
            report.err(
                f"plan.layout: {layout_name!r} layout file is a symlink",
                f"{layout_file}; refusing to follow it",
            )
            continue
        if not layout_file.is_file():
            report.err(
                f"plan.layout: {layout_name!r} layout file missing",
                f"no file at {layout_file}",
            )
            continue
        layout = _load_json_file(layout_file, f"layout.{layout_name}", report)
        if not isinstance(layout, dict):
            continue
        if not _schema_validate(
            layout, LAYOUT_SCHEMA, f"layout.{layout_name}", report,
        ):
            continue
        layouts_by_name[layout_name] = layout
        if layout_name not in _RENDER_SUPPORTED_LAYOUTS:
            # Render-model generator can't project this layout into a
            # render_model today; the pipeline would report
            # [SKIP] slide N: layout 'X' not implemented and the PPTX
            # exporter would then fail closed at its 1:1 coverage gate.
            # Surface as ERROR so the agent picks a supported layout
            # before invoking the pipeline.
            report.err(
                f"plan.layout: {layout_name!r} not in render-model generator's "
                f"SUPPORTED_LAYOUTS",
                f"runtime would [SKIP] this slide and the PPTX exporter "
                f"would then fail closed on the missing render_model. "
                f"Supported: {list(_RENDER_SUPPORTED_LAYOUTS)}",
            )
    return manifest, layouts_by_name


# ---------------------------------------------------------------------------
# Slide-specs coverage (mirrors init_slide_plans 1:1 coverage gate plus the
# per-layout slot-coverage gate via _slide_plan_against_layout).
# ---------------------------------------------------------------------------


def _check_slide_specs(
    slide_specs_dir: Path,
    plan: dict,
    layouts_by_name: dict[str, dict] | None,
    report: Report,
) -> dict[int, dict]:
    """Return {plan_index: parsed_spec} for every accepted spec. Adds
    findings for every coverage / schema / per-layout problem."""
    if _has_uri_scheme(str(slide_specs_dir)):
        report.err("slide_specs_dir: looks like a URI", str(slide_specs_dir))
        return {}
    if slide_specs_dir.is_symlink():
        report.err("slide_specs_dir: is a symlink", str(slide_specs_dir))
        return {}
    if not slide_specs_dir.exists():
        report.err("slide_specs_dir: does not exist", str(slide_specs_dir))
        return {}
    if not slide_specs_dir.is_dir():
        report.err("slide_specs_dir: not a directory", str(slide_specs_dir))
        return {}
    plan_slides = plan.get("slides") or []
    plan_by_index = {
        s.get("index"): s for s in plan_slides if isinstance(s.get("index"), int)
    }
    accepted: dict[int, dict] = {}
    seen_indices: dict[int, str] = {}
    for spec_file in sorted(slide_specs_dir.glob("*.json")):
        rel = spec_file.name
        spec = _load_json_file(spec_file, f"slide_spec.{rel}", report)
        if not isinstance(spec, dict):
            continue
        if not _schema_validate(
            spec, SLIDE_PLAN_SCHEMA, f"slide_spec.{rel}", report,
        ):
            continue
        idx = spec.get("index")
        layout = spec.get("layout")
        if not isinstance(idx, int) or isinstance(idx, bool):
            # Schema gate already reported; skip cross-checks.
            continue
        if not isinstance(layout, str) or not layout:
            continue
        # 1:1 coverage: deck_plan must declare this index.
        plan_slide = plan_by_index.get(idx)
        if plan_slide is None:
            report.err(
                f"slide_spec.{rel}: index {idx} is orphan",
                f"deck_plan does not declare a slide with index={idx}",
            )
            continue
        if idx in seen_indices:
            report.err(
                f"slide_spec.{rel}: duplicate index",
                f"slide index {idx} also declared by {seen_indices[idx]!r}",
            )
            continue
        seen_indices[idx] = rel
        # Layout / title agreement with the deck_plan slide.
        if plan_slide.get("layout") != layout:
            report.err(
                f"slide_spec.{rel}: layout disagrees with deck_plan",
                f"spec.layout={layout!r} vs deck_plan.slides[{idx}].layout="
                f"{plan_slide.get('layout')!r}",
            )
        title = spec.get("title")
        if plan_slide.get("title") != title:
            report.err(
                f"slide_spec.{rel}: title disagrees with deck_plan",
                f"spec.title={title!r} vs deck_plan.slides[{idx}].title="
                f"{plan_slide.get('title')!r}",
            )
        # Canonical filename advisory (init_slide_plans writes
        # <idx:02d>_<layout>.json on the producer side; flag drift here
        # so the agent can rename before invoking the pipeline if they
        # want their specs dir to mirror the canonical names).
        canonical = f"{idx:02d}_{layout}.json"
        if rel != canonical:
            report.warn(
                f"slide_spec.{rel}: filename does not match canonical "
                f"<index:02d>_<layout>.json",
                f"init_slide_plans will rename this to {canonical!r}; "
                f"renaming the spec to match avoids the drift later",
            )
        # Per-layout required-slot coverage (uses the shared validator).
        if layouts_by_name is not None and layout in layouts_by_name:
            problems = _slide_plan_against_layout(spec, layouts_by_name[layout])
            for p in problems:
                report.err(
                    f"slide_spec.{rel}: layout {layout!r} required-slot coverage",
                    p,
                )
        # Block-kind advisory: chart_ref blocks cannot be projected to a
        # render_model by the current generator (no SUPPORTED layout uses
        # the chart_placeholder primitive); flag at authoring time.
        for i, block in enumerate(spec.get("blocks") or []):
            if isinstance(block, dict) and block.get("kind") == "chart_ref":
                report.err(
                    f"slide_spec.{rel}: blocks[{i}] uses kind 'chart_ref'",
                    "the render-model generator has no SUPPORTED layout that "
                    "maps to the chart_placeholder primitive today; the "
                    "PPTX exporter would fail closed on this slide",
                )
        accepted[idx] = spec
    # Final coverage: every plan slide must have one spec.
    declared_indices = sorted(plan_by_index.keys())
    for idx in declared_indices:
        if idx not in accepted:
            plan_slide = plan_by_index[idx]
            report.err(
                f"slide_spec coverage: deck_plan slide index {idx} has no spec",
                f"expected one *.json in {slide_specs_dir} with index={idx}, "
                f"layout={plan_slide.get('layout')!r}, "
                f"title={plan_slide.get('title')!r}",
            )
    return accepted


# ---------------------------------------------------------------------------
# Image manifest spec checks.
# ---------------------------------------------------------------------------


def _check_image_manifest_spec(
    image_manifest_spec: Path,
    slide_specs: dict[int, dict],
    source_bytes: bytes | None,
    report: Report,
) -> dict | None:
    spec = _load_json_file(image_manifest_spec, "image_manifest_spec", report)
    if not isinstance(spec, dict):
        return None
    if not _schema_validate(
        spec, IMAGE_MANIFEST_SCHEMA, "image_manifest_spec", report,
    ):
        return None
    images = spec.get("images") or []
    ids_seen: set[str] = set()
    declared_ids: set[str] = set()
    for i, img in enumerate(images):
        if not isinstance(img, dict):
            continue  # schema gate already reported
        img_id = img.get("id")
        local_path = img.get("local_path")
        if isinstance(img_id, str):
            if img_id in ids_seen:
                report.err(
                    f"image_manifest_spec: duplicate images[{i}].id",
                    f"{img_id!r} already declared",
                )
            else:
                ids_seen.add(img_id)
                declared_ids.add(img_id)
        if isinstance(local_path, str) and not local_path_is_safe(local_path):
            report.err(
                f"image_manifest_spec: images[{i}].local_path is unsafe",
                f"{local_path!r} fails local_path_is_safe (no URI scheme, no "
                f"absolute path, no '..', no leading backslash, no protocol-"
                f"relative)",
            )
        intended_use = img.get("intended_use")
        alt_text = img.get("alt_text")
        for field_name, value in (
            ("intended_use", intended_use), ("alt_text", alt_text),
        ):
            if not isinstance(value, str):
                continue
            lowered = value.lower()
            for phrase in _FULL_SLIDE_PHRASES:
                if phrase in lowered:
                    report.err(
                        f"image_manifest_spec: images[{i}].{field_name} "
                        f"contains full-slide raster intent",
                        f"phrase {phrase!r} in {value!r}; "
                        f"references/d-one-image-policy.md forbids full-slide "
                        f"raster output",
                    )
                    break
    # Cross-check slide_plan image_refs.
    referenced_ids: set[tuple[int, str]] = set()
    for idx, spec_obj in slide_specs.items():
        for ref in spec_obj.get("image_refs") or []:
            if isinstance(ref, str):
                referenced_ids.add((idx, ref))
        for i, block in enumerate(spec_obj.get("blocks") or []):
            if (
                isinstance(block, dict)
                and block.get("kind") == "image_ref"
                and isinstance(block.get("content"), str)
            ):
                referenced_ids.add((idx, block["content"]))
    undeclared = sorted({
        (idx, rid) for idx, rid in referenced_ids if rid not in declared_ids
    })
    for idx, rid in undeclared:
        report.err(
            f"image_manifest_spec: slide_plan index {idx} references id "
            f"{rid!r} not declared in images[]",
            f"declared ids: {sorted(declared_ids)}",
        )
    if not images and referenced_ids:
        # Already covered by the per-id check above, but state the rule
        # once more so the diagnostic is unambiguous.
        report.err(
            "image_manifest_spec: empty images[] with non-empty slide_plan image_refs",
            f"empty images[] is accepted only when no slide_plan references an "
            f"image; got {sorted({rid for _, rid in referenced_ids})}",
        )
    # Source-leakage scan: look for verbatim source phrases (>= 16 chars
    # after collapsing whitespace) inside alt_text / intended_use. The
    # scan is best-effort — it catches obvious copy/paste from the
    # source body into a prompt-like field, not every possible leakage.
    if source_bytes is not None and images:
        leakage_needles = _source_leakage_needles(source_bytes)
        for i, img in enumerate(images):
            if not isinstance(img, dict):
                continue
            for field_name in ("alt_text", "intended_use"):
                value = img.get(field_name)
                if not isinstance(value, str):
                    continue
                collapsed = _collapse_ws(value)
                for needle in leakage_needles:
                    if needle and needle in collapsed:
                        report.err(
                            f"image_manifest_spec: images[{i}].{field_name} "
                            f"contains a verbatim source phrase",
                            f"matched needle {needle[:60]!r}; "
                            f"references/authoring-workflow.md forbids raw "
                            f"source text in image manifest fields",
                        )
                        break
    return spec


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _source_leakage_needles(source_bytes: bytes) -> list[str]:
    """Return up to a handful of long phrases from the source body that the
    leakage scan looks for. Skips obvious heading lines (start with '#')
    and short lines so we don't false-positive on a one-word title."""
    try:
        text = source_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return []
    needles: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        collapsed = _collapse_ws(stripped)
        if len(collapsed) >= 32:
            needles.append(collapsed)
        if len(needles) >= 8:
            break
    return needles


# ---------------------------------------------------------------------------
# Forbidden-token scan: applied to every spec JSON body as a single string
# so we catch tokens regardless of which field they ended up in.
# ---------------------------------------------------------------------------


def _scan_forbidden_tokens(
    label: str, value: object, report: Report, *, exclude_paths: tuple[str, ...] = (),
) -> None:
    """Walk every string in the JSON tree (keys + values) and look for
    every needle in _FORBIDDEN_TOKENS. exclude_paths is a tuple of fully
    qualified dotted paths to skip (e.g. 'template' for plan.template,
    which would otherwise hit "data:" if the template name contained
    that substring; in practice none of the legitimate names do)."""
    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str):
            if path in exclude_paths:
                return
            lowered = node.lower()
            for needle, severity, why in _FORBIDDEN_TOKENS:
                if needle in lowered:
                    if severity == "ERROR":
                        report.err(
                            f"{label}: forbidden token at {path}",
                            f"matched {needle!r} — {why}",
                        )
                    else:
                        report.warn(
                            f"{label}: forbidden token at {path}",
                            f"matched {needle!r} — {why}",
                        )
                    return
    walk(value, "")


# ---------------------------------------------------------------------------
# Top-level entry.
# ---------------------------------------------------------------------------


def validate_authoring_bundle(
    *,
    source: Path,
    title: str,
    audience: str,
    objective: str,
    plan_spec: Path,
    slide_specs_dir: Path,
    image_manifest_spec: Path,
    template_root: Path,
    design_system_spec: Path | None = None,
    theme_from_template: bool = False,
    source_id: str | None = None,
    tone: str | None = None,
    language: str | None = None,
    approximate_slide_count: int | None = None,
) -> Report:
    report = Report()

    # 0. Mode-selection gate (mirrors run_explicit_pipeline + init_design_system).
    if design_system_spec is None and not theme_from_template:
        report.err(
            "mode: neither design-system input supplied",
            "must pass exactly one of --design-system-spec / --theme-from-template",
        )
    if design_system_spec is not None and theme_from_template:
        report.err(
            "mode: both design-system inputs supplied",
            "--design-system-spec and --theme-from-template are mutually exclusive",
        )

    # 1. Source + derived source_id + brief metadata.
    source_bytes = _check_source(source, report)
    resolved_id = _resolve_source_id(source_id, source, report)
    _check_brief_metadata(
        title, audience, objective, tone, language, approximate_slide_count, report,
    )

    # 2. Template root + plan.
    template_root_ok = _check_template_root(template_root, report)
    plan = _load_json_file(plan_spec, "plan_spec", report)
    if not isinstance(plan, dict):
        plan = None
    elif not _schema_validate(plan, DECK_PLAN_SCHEMA, "plan_spec", report):
        # Keep the plan around for the structural checks even when the
        # schema check failed; the planner-semantics gate still has
        # information to add for the agent.
        pass

    # Shape preflight: several downstream semantic checks iterate
    # plan['slides'] / plan['sections'] and would traceback on a
    # wrong-shape field (e.g. slides='hello'). The preflight emits an
    # explicit ERROR per problem and returns flags so dependent semantic
    # checks below SKIP rather than crash.
    plan_shape_flags = {"slides_ok": False, "sections_ok": False, "planning_ok": False}
    if plan is not None:
        plan_shape_flags = _preflight_plan_shape(plan, report)

    layouts_by_name: dict[str, dict] | None = None
    if plan is not None and template_root_ok and plan_shape_flags["slides_ok"]:
        _, layouts_by_name = _check_plan_template_chain(plan, template_root, report)

    if (
        plan is not None
        and resolved_id is not None
        and all(plan_shape_flags.values())
    ):
        brief_source_refs = [resolved_id]
        for err in _cross_check_planner_semantics(plan, brief_source_refs):
            report.err("plan: planner-semantics", err)

    # 3. Design system spec (if --design-system-spec). Theme mode is
    # validated implicitly via the template chain above.
    if design_system_spec is not None:
        ds = _load_json_file(design_system_spec, "design_system_spec", report)
        if isinstance(ds, dict):
            _schema_validate(
                ds, DESIGN_SYSTEM_SCHEMA, "design_system_spec", report,
            )

    # 4. Slide specs (1:1 coverage + per-layout slot coverage). Empty {}
    # when the plan was unloadable OR when plan['slides'] is the wrong
    # shape — _check_slide_specs iterates plan_slides and would crash on
    # e.g. slides='hello'.
    slide_specs: dict[int, dict] = {}
    if plan is not None and plan_shape_flags["slides_ok"]:
        slide_specs = _check_slide_specs(
            slide_specs_dir, plan, layouts_by_name, report,
        )

    # 5. Image manifest spec.
    _check_image_manifest_spec(
        image_manifest_spec, slide_specs, source_bytes, report,
    )

    # 6. Forbidden-token scan across each spec body. We skip the plan
    # template name from this scan even though it should never carry a
    # forbidden token — defensive against a future template name that
    # happens to include "data:" or similar. plan.template is path-
    # checked separately by _check_plan_template_chain.
    if plan is not None:
        _scan_forbidden_tokens("plan_spec", plan, report, exclude_paths=("template",))
    if design_system_spec is not None:
        # Re-load (cheap) so we have the raw value to scan; we already
        # surfaced schema errors above so this is best-effort.
        ds_value = _load_json_file(design_system_spec, "design_system_spec.scan", Report())
        if isinstance(ds_value, dict):
            _scan_forbidden_tokens("design_system_spec", ds_value, report)
    for idx, spec_obj in slide_specs.items():
        _scan_forbidden_tokens(f"slide_spec.index_{idx:02d}", spec_obj, report)
    # Re-load image manifest spec for the scan.
    img_value = _load_json_file(image_manifest_spec, "image_manifest_spec.scan", Report())
    if isinstance(img_value, dict):
        _scan_forbidden_tokens("image_manifest_spec", img_value, report)

    return report


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def _format_report(report: Report) -> str:
    lines: list[str] = []
    if not report.findings:
        lines.append("OK: no findings — bundle passed the structural gate.")
        return "\n".join(lines)
    for f in report.findings:
        mark = "ERROR" if f.severity == "ERROR" else "WARN"
        suffix = f" — {f.detail}" if f.detail else ""
        lines.append(f"  [{mark}] {f.name}{suffix}")
    n_err = len(report.errors)
    n_warn = len(report.warnings)
    if n_err:
        lines.append(
            f"FAIL: {n_err} error(s), {n_warn} warning(s). Fix every ERROR "
            f"before invoking scripts/run_explicit_pipeline.py."
        )
    else:
        lines.append(
            f"OK (with warnings): 0 errors, {n_warn} warning(s). The "
            f"runtime pipeline will still accept this bundle; review the "
            f"warnings before shipping."
        )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Pre-pipeline authoring quality gate (NARROW BRIDGE "
            "CONTRACT, not a prompt/report/Markdown-to-PPTX automation). "
            "Validates an explicit-input spec bundle (the same inputs "
            "scripts/run_explicit_pipeline.py takes) structurally, "
            "WITHOUT creating a workspace or generating any artifact. "
            "Mirrors the structural checks the per-stage init_* helpers "
            "would apply at runtime, plus a small set of authoring "
            "rules (forbidden network/model/API tokens, overclaim-of-"
            "automation tokens, full-slide raster intent, raw-source "
            "leakage into image-manifest prompt-like fields)."
        ),
    )
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--source-id", type=str, default=None)
    parser.add_argument("--title", type=str, default=None)
    parser.add_argument("--audience", type=str, default=None)
    parser.add_argument("--objective", type=str, default=None)
    parser.add_argument("--tone", type=str, default=None)
    parser.add_argument("--language", type=str, default=None)
    parser.add_argument("--approximate-slide-count", type=int, default=None)
    parser.add_argument("--plan-spec", type=Path, default=None)
    parser.add_argument("--design-system-spec", type=Path, default=None)
    parser.add_argument("--theme-from-template", action="store_true")
    parser.add_argument("--template-root", type=Path, default=None)
    parser.add_argument("--slide-specs-dir", type=Path, default=None)
    parser.add_argument("--image-manifest-spec", type=Path, default=None)
    parser.add_argument(
        "--strict", action="store_true",
        help="Promote every WARN finding to ERROR (exit 1 on any warning).",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios (happy path + every "
             "fail-closed gate, including the overclaim-of-automation "
             "scan that protects the bridge-contract framing). Mutually "
             "exclusive with the bundle flags.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        orchestration_args = (
            args.source, args.source_id, args.title, args.audience,
            args.objective, args.tone, args.language,
            args.approximate_slide_count, args.plan_spec,
            args.design_system_spec, args.template_root,
            args.slide_specs_dir, args.image_manifest_spec,
        )
        if any(v is not None for v in orchestration_args) or args.theme_from_template or args.strict:
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
            f"OK (self-test): {len(results)} scenario(s) behaved as expected; "
            f"the authoring quality gate flags exactly the failure modes "
            f"the agent should fix before invoking the runtime pipeline."
        )
        return 0

    missing = [
        name for name, value in (
            ("--source", args.source),
            ("--title", args.title),
            ("--audience", args.audience),
            ("--objective", args.objective),
            ("--plan-spec", args.plan_spec),
            ("--slide-specs-dir", args.slide_specs_dir),
            ("--image-manifest-spec", args.image_manifest_spec),
            ("--template-root", args.template_root),
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

    report = validate_authoring_bundle(
        source=args.source,
        title=args.title,
        audience=args.audience,
        objective=args.objective,
        plan_spec=args.plan_spec,
        slide_specs_dir=args.slide_specs_dir,
        image_manifest_spec=args.image_manifest_spec,
        template_root=args.template_root,
        design_system_spec=args.design_system_spec,
        theme_from_template=args.theme_from_template,
        source_id=args.source_id,
        tone=args.tone,
        language=args.language,
        approximate_slide_count=args.approximate_slide_count,
    )
    print(_format_report(report))
    if report.errors:
        return 1
    if args.strict and report.warnings:
        print(
            f"FAIL (strict): {len(report.warnings)} warning(s) promoted to "
            f"error under --strict.",
            file=sys.stderr,
        )
        return 1
    return 0


# ---------------------------------------------------------------------------
# Self-test scenarios. Each runs under tempfile.TemporaryDirectory(),
# builds a minimal bundle inline, and asserts what the gate emits. We
# call validate_authoring_bundle() directly (rather than spawning the CLI
# as a subprocess) to keep the self-test runtime low.
# ---------------------------------------------------------------------------


_MARKER_PHRASE = "This synthetic body never belongs in image-manifest prompt fields."

_FIXTURE_SOURCE = (
    "# Synthetic Fixture Source\n\n"
    f"{_MARKER_PHRASE}\n"
    "Stage 2 only takes --title / --audience / --objective from the CLI; "
    "Stage 3-6 each accept explicit --*-spec JSON files. None of the "
    "helpers ever read this file for business content.\n"
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _build_bundle(td: Path, *, source_id: str = "fixture_source") -> dict:
    """Minimal two-slide bundle (cover + key_message) against the
    business_review template — the same fixture shape the existing
    prepare_workspace / run_explicit_pipeline self-tests use."""
    td.mkdir(parents=True, exist_ok=True)
    source = td / "fixture_source.md"
    source.write_text(_FIXTURE_SOURCE)
    plan_spec = td / "plan_spec.json"
    _write_json(plan_spec, {
        "template": "business_review",
        "planning": {
            "planned_slide_count": 2,
            "rationale": "Two-slide fixture for the authoring gate self-test.",
        },
        "sections": [
            {"id": "intro", "title": "Intro", "summary": "Cover + body.",
             "slide_indices": [1, 2]},
        ],
        "slides": [
            {"index": 1, "layout": "cover", "title": "Fixture Cover Title",
             "section_id": "intro", "summary": "Cover slide.", "density": "low",
             "source_refs": [source_id]},
            {"index": 2, "layout": "key_message", "title": "Fixture Message",
             "section_id": "intro", "summary": "Single message slide.",
             "density": "low", "source_refs": [source_id]},
        ],
    })
    specs_dir = td / "specs"
    specs_dir.mkdir()
    _write_json(specs_dir / "01_cover.json", {
        "index": 1, "layout": "cover", "title": "Fixture Cover Title",
        "blocks": [
            {"id": "title", "kind": "text", "content": "Fixture Cover Title"},
        ],
    })
    _write_json(specs_dir / "02_key_message.json", {
        "index": 2, "layout": "key_message", "title": "Fixture Message",
        "blocks": [
            {"id": "message", "kind": "callout",
             "content": "Fixture key-message body."},
        ],
    })
    image_manifest_spec = td / "image_manifest_spec.json"
    _write_json(image_manifest_spec, {"images": []})
    return {
        "source": source,
        "title": "Fixture Title",
        "audience": "Internal fixture audience",
        "objective": "Exercise the authoring quality gate.",
        "plan_spec": plan_spec,
        "slide_specs_dir": specs_dir,
        "image_manifest_spec": image_manifest_spec,
        "template_root": REPO_ROOT / "templates" / "layouts",
        "theme_from_template": True,
        "source_id": source_id,
    }


def _run_gate(td: Path, mutator=None) -> Report:
    """Build a bundle, optionally mutate it, then run the gate."""
    bundle = _build_bundle(td)
    if mutator is not None:
        mutator(td, bundle)
    return validate_authoring_bundle(**bundle)


def _run_gate_no_crash(
    td: Path, mutator=None,
) -> tuple[Report, str | None]:
    """Run the gate but catch any exception so a fail-closed self-test
    can distinguish 'returned an ERROR finding' from 'tracebacked'.
    Returns (report, None) on a clean run; (empty_report, str(exc)) when
    the gate raised."""
    try:
        return _run_gate(td, mutator), None
    except Exception as exc:
        return Report(), f"{type(exc).__name__}: {exc}"


def _has_error(report: Report, substring: str) -> bool:
    return any(substring in f.name or substring in f.detail for f in report.errors)


def _has_warn(report: Report, substring: str) -> bool:
    return any(substring in f.name or substring in f.detail for f in report.warnings)


def _scenario(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


def _run_self_tests() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    template_root = REPO_ROOT / "templates" / "layouts"
    if not template_root.is_dir():
        results.append(_scenario(
            "fixture: templates/layouts/ exists",
            False,
            f"missing {template_root}",
        ))
        return results

    # 1. Happy path: no findings.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        report = _run_gate(td)
        ok = report.ok and not report.warnings
        results.append(_scenario(
            "happy path: clean bundle → 0 errors, 0 warnings",
            ok,
            f"errors={[(f.name, f.detail) for f in report.errors]}, "
            f"warnings={[(f.name, f.detail) for f in report.warnings]}",
        ))

    # 2. Plan: planned_slide_count mismatch.
    def mut_planned(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["planning"]["planned_slide_count"] = 5
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_planned)
        ok = not report.ok and _has_error(report, "planned_slide_count")
        results.append(_scenario(
            "plan: planned_slide_count != len(slides) flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 3. Plan: non-contiguous indices [1, 2, 4].
    def mut_noncontig(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][1]["index"] = 4
        plan["planning"]["planned_slide_count"] = 2  # keep planned == len
        plan["sections"][0]["slide_indices"] = [1, 4]
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_noncontig)
        ok = not report.ok and _has_error(report, "contiguous")
        results.append(_scenario(
            "plan: non-contiguous slide indices flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 4. Plan: layout not declared by the template.
    def mut_unknown_layout(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][0]["layout"] = "moon_phases"
        _write_json(bundle["plan_spec"], plan)
        # Also update the matching slide spec, otherwise that becomes a
        # second error and the scenario name is ambiguous.
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["layout"] = "moon_phases"
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_unknown_layout)
        ok = not report.ok and _has_error(report, "moon_phases")
        results.append(_scenario(
            "plan: layout not declared by template flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 5. Plan: slide.source_refs not in derived brief.source_refs.
    def mut_orphan_source_ref(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][0]["source_refs"] = ["unrelated_source"]
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_orphan_source_ref)
        ok = not report.ok and _has_error(report, "unrelated_source")
        results.append(_scenario(
            "plan: slide.source_refs not declared in deck_brief.source_refs flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 6. Slide specs: missing index 2.
    def mut_missing_spec(td, bundle):
        (bundle["slide_specs_dir"] / "02_key_message.json").unlink()
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_missing_spec)
        ok = not report.ok and _has_error(report, "deck_plan slide index 2 has no spec")
        results.append(_scenario(
            "slide specs: missing slide flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 7. Slide specs: orphan spec (index that the plan does not declare).
    def mut_orphan_spec(td, bundle):
        _write_json(bundle["slide_specs_dir"] / "99_cover.json", {
            "index": 99, "layout": "cover", "title": "Orphan",
            "blocks": [{"id": "title", "kind": "text", "content": "X"}],
        })
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_orphan_spec)
        ok = not report.ok and _has_error(report, "is orphan")
        results.append(_scenario(
            "slide specs: orphan spec flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 8. Slide specs: layout / title mismatch with the deck_plan.
    def mut_title_mismatch(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["title"] = "Different Title"
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_title_mismatch)
        ok = not report.ok and _has_error(report, "title disagrees")
        results.append(_scenario(
            "slide specs: title mismatch with deck_plan flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 9. Slide specs: missing required slot ('title' on cover).
    def mut_missing_slot(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["blocks"] = [
            {"id": "subtitle", "kind": "text", "content": "Only subtitle"},
        ]
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_missing_slot)
        ok = not report.ok and _has_error(report, "missing required slot 'title'")
        results.append(_scenario(
            "slide specs: missing required layout slot flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 10. Slide specs: chart_ref block (no SUPPORTED layout maps to it).
    def mut_chart_ref(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        spec = json.loads(spec_path.read_text())
        spec["blocks"].append(
            {"id": "trend", "kind": "chart_ref", "content": "q3_revenue"},
        )
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_chart_ref)
        ok = not report.ok and _has_error(report, "chart_ref")
        results.append(_scenario(
            "slide specs: chart_ref block flagged (no SUPPORTED layout uses it)",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 11. Image manifest: undeclared image_ref.
    def mut_undeclared_ref(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["image_refs"] = ["accent_image"]
        spec["blocks"].append(
            {"id": "accent", "kind": "image_ref", "content": "accent_image"},
        )
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_undeclared_ref)
        ok = not report.ok and _has_error(report, "accent_image")
        results.append(_scenario(
            "image manifest: undeclared image_ref flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 12. Image manifest: unsafe local_path (URL scheme).
    def mut_unsafe_path(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["image_refs"] = ["accent"]
        spec["blocks"].append(
            {"id": "accent", "kind": "image_ref", "content": "accent"},
        )
        _write_json(spec_path, spec)
        _write_json(bundle["image_manifest_spec"], {
            "images": [
                {"id": "accent",
                 "local_path": "https://example.com/x.png",
                 "source": "local_asset"},
            ],
        })
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_unsafe_path)
        # Both an unsafe-path ERROR and a forbidden-token ERROR for the
        # URL — either confirms the gate fired.
        ok = not report.ok and (
            _has_error(report, "unsafe") or _has_error(report, "URL scheme")
        )
        results.append(_scenario(
            "image manifest: unsafe local_path flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 13. Image manifest: duplicate id.
    def mut_duplicate_id(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["image_refs"] = ["accent"]
        spec["blocks"].append(
            {"id": "accent", "kind": "image_ref", "content": "accent"},
        )
        _write_json(spec_path, spec)
        _write_json(bundle["image_manifest_spec"], {
            "images": [
                {"id": "accent", "local_path": "assets/a.svg",
                 "source": "local_asset"},
                {"id": "accent", "local_path": "assets/b.svg",
                 "source": "local_asset"},
            ],
        })
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_duplicate_id)
        ok = not report.ok and _has_error(report, "duplicate")
        results.append(_scenario(
            "image manifest: duplicate id flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 14. Image manifest: full-slide raster intent.
    def mut_full_slide(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["image_refs"] = ["accent"]
        spec["blocks"].append(
            {"id": "accent", "kind": "image_ref", "content": "accent"},
        )
        _write_json(spec_path, spec)
        _write_json(bundle["image_manifest_spec"], {
            "images": [
                {"id": "accent", "local_path": "assets/accent.svg",
                 "source": "synthetic",
                 "intended_use": "full-slide background"},
            ],
        })
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_full_slide)
        ok = not report.ok and _has_error(report, "full-slide raster intent")
        results.append(_scenario(
            "image manifest: full-slide raster intent flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 15. Forbidden token in a spec body (D-One mention in alt_text).
    def mut_d_one(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["image_refs"] = ["accent"]
        spec["blocks"].append(
            {"id": "accent", "kind": "image_ref", "content": "accent"},
        )
        _write_json(spec_path, spec)
        _write_json(bundle["image_manifest_spec"], {
            "images": [
                {"id": "accent", "local_path": "assets/a.svg",
                 "source": "synthetic",
                 "alt_text": "generated via D-One local pipeline"},
            ],
        })
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_d_one)
        ok = not report.ok and _has_error(report, "d-one")
        results.append(_scenario(
            "image manifest: D-One reference flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 16. Forbidden token in a slide spec body (Qoder claim in notes).
    def mut_qoder(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        spec = json.loads(spec_path.read_text())
        spec["notes"] = "Generated by Qoder runtime."
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_qoder)
        ok = not report.ok and _has_error(report, "qoder")
        results.append(_scenario(
            "slide spec: Qoder claim flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 17. Forbidden token in a slide spec body (https URL in content).
    def mut_https(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        spec = json.loads(spec_path.read_text())
        spec["blocks"][0]["content"] = "See https://example.com/page for details."
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_https)
        ok = not report.ok and _has_error(report, "https://")
        results.append(_scenario(
            "slide spec: https:// URL flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 18. Raw-source leakage into image_manifest alt_text.
    def mut_leak(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["image_refs"] = ["accent"]
        spec["blocks"].append(
            {"id": "accent", "kind": "image_ref", "content": "accent"},
        )
        _write_json(spec_path, spec)
        _write_json(bundle["image_manifest_spec"], {
            "images": [
                {"id": "accent", "local_path": "assets/a.svg",
                 "source": "synthetic",
                 "alt_text": _MARKER_PHRASE},
            ],
        })
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_leak)
        ok = not report.ok and _has_error(report, "verbatim source phrase")
        results.append(_scenario(
            "image manifest: raw-source leakage into alt_text flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 19. Mode selection: both --design-system-spec AND --theme-from-template.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bundle = _build_bundle(td)
        ds = td / "design_system_spec.json"
        _write_json(ds, {
            "palette": {"primary": "#112233", "secondary": "#445566",
                        "accent": "#778899", "background": "#FFFFFF",
                        "text": "#000000"},
            "typography": {
                "heading": {"font_family": "Inter, sans-serif", "size_pt": 24},
                "body": {"font_family": "Inter, sans-serif", "size_pt": 12},
            },
            "grid": {"width_px": 1920, "height_px": 1080, "margin_px": 80},
        })
        bundle["design_system_spec"] = ds
        bundle["theme_from_template"] = True  # both modes on purpose
        report = validate_authoring_bundle(**bundle)
        ok = not report.ok and _has_error(report, "mutually exclusive")
        results.append(_scenario(
            "mode: both design-system inputs flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 20. Mode selection: neither input.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bundle = _build_bundle(td)
        bundle["theme_from_template"] = False
        report = validate_authoring_bundle(**bundle)
        ok = not report.ok and _has_error(report, "neither design-system input")
        results.append(_scenario(
            "mode: neither design-system input flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 21. Source: missing.
    def mut_missing_source(td, bundle):
        bundle["source"] = td / "does_not_exist.md"
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_missing_source)
        ok = not report.ok and _has_error(report, "does not exist")
        results.append(_scenario(
            "source: missing file flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 22. Source: empty.
    def mut_empty_source(td, bundle):
        empty = td / "empty.md"
        empty.write_bytes(b"")
        bundle["source"] = empty
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_empty_source)
        ok = not report.ok and _has_error(report, "empty")
        results.append(_scenario(
            "source: empty file flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 23. Brief metadata: empty title.
    def mut_empty_title(td, bundle):
        bundle["title"] = ""
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_empty_title)
        ok = not report.ok and _has_error(report, "brief.title")
        results.append(_scenario(
            "brief: empty title flagged",
            ok,
            f"errors={[f.name for f in report.errors]}",
        ))

    # 23b. Whitespace-only metadata. init_deck_brief refuses ' ' / '\t' /
    # newline-only values via _validate_single_line_string; mirror that
    # here so the preflight cannot false-pass a whitespace-only value.
    for ws_name, ws_value in (
        ("title", "   "),
        ("audience", "\t"),
        ("objective", " \t  "),
        ("tone", "  "),
        ("language", "\t\t"),
    ):
        def mut_ws(td, bundle, _ws_name=ws_name, _ws_value=ws_value):
            bundle[_ws_name] = _ws_value
        with tempfile.TemporaryDirectory() as raw_td:
            report = _run_gate(Path(raw_td), mut_ws)
            ok = (
                not report.ok
                and _has_error(report, f"brief.{ws_name}")
                and _has_error(report, "empty after stripping whitespace")
            )
            results.append(_scenario(
                f"brief: whitespace-only {ws_name} ({ws_value!r}) flagged after .strip()",
                ok,
                f"errors={[(f.name, f.detail) for f in report.errors]}",
            ))

    # 24. Filename advisory (non-canonical spec filename → WARN, no ERROR).
    def mut_noncanonical_filename(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        new_path = spec_path.parent / "slide_two.json"
        spec_path.rename(new_path)
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_noncanonical_filename)
        ok = report.ok and _has_warn(report, "canonical")
        results.append(_scenario(
            "slide specs: non-canonical filename → WARN (no ERROR)",
            ok,
            f"errors={[f.name for f in report.errors]}, "
            f"warnings={[f.name for f in report.warnings]}",
        ))

    # 25. The gate is **non-mutating**: a happy-path run leaves the
    # caller's spec files byte-identical (it only reads them).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bundle = _build_bundle(td)
        # Capture spec bytes before and after.
        captured: dict[Path, bytes] = {}
        for p in (
            bundle["plan_spec"],
            bundle["image_manifest_spec"],
            bundle["source"],
            bundle["slide_specs_dir"] / "01_cover.json",
            bundle["slide_specs_dir"] / "02_key_message.json",
        ):
            captured[p] = p.read_bytes()
        validate_authoring_bundle(**bundle)
        unchanged = all(p.read_bytes() == b for p, b in captured.items())
        # And no workspace-shaped sibling was created next to the inputs.
        siblings_unchanged = (
            not (td / "input").exists()
            and not (td / "source_manifest.json").exists()
            and not (td / "deck_brief.json").exists()
            and not (td / "deck_plan.json").exists()
            and not (td / "design_system.json").exists()
            and not (td / "image_manifest.json").exists()
            and not (td / "render_models").exists()
            and not (td / "svg_previews").exists()
        )
        ok = unchanged and siblings_unchanged
        results.append(_scenario(
            "non-mutating: caller's spec bytes unchanged and no workspace "
            "artifact is created",
            ok,
            f"unchanged={unchanged}, siblings_unchanged={siblings_unchanged}",
        ))

    # ---------------------------------------------------------------------
    # Fail-closed shape gates. Each malformed plan_spec must surface one
    # or more ERROR findings AND must NOT traceback (regression coverage
    # for the previous AttributeError on slides=str / sections=str etc).
    # ---------------------------------------------------------------------

    # 26. plan_spec root is malformed JSON.
    def mut_malformed_json(td, bundle):
        bundle["plan_spec"].write_text("{not: valid json")
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_malformed_json)
        ok = crash is None and not report.ok and _has_error(report, "malformed JSON")
        results.append(_scenario(
            "fail-closed: plan_spec root is malformed JSON → ERROR (no traceback)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
        ))

    # 27. plan_spec root is a JSON list.
    def mut_root_list(td, bundle):
        bundle["plan_spec"].write_text(json.dumps([1, 2, 3]) + "\n")
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_root_list)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "top-level value is not a JSON object")
        )
        results.append(_scenario(
            "fail-closed: plan_spec root is a list → ERROR (no traceback)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
        ))

    # 28. plan_spec.slides is a string.
    def mut_slides_string(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"] = "not-a-list"
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_slides_string)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "plan_spec.slides: not a list")
        )
        results.append(_scenario(
            "fail-closed: plan_spec.slides is a string → ERROR (no traceback)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
        ))

    # 29. plan_spec.slides contains a non-object entry.
    def mut_slides_nonobject(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"].append("not-a-dict")
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_slides_nonobject)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "plan_spec.slides: non-object entries")
        )
        results.append(_scenario(
            "fail-closed: plan_spec.slides contains a string entry → "
            "ERROR (no traceback)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
        ))

    # 30. plan_spec.sections is a string.
    def mut_sections_string(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["sections"] = "not-a-list"
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_sections_string)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "plan_spec.sections: not a list")
        )
        results.append(_scenario(
            "fail-closed: plan_spec.sections is a string → ERROR (no traceback)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
        ))

    # 31. plan_spec.sections contains a non-object entry.
    def mut_sections_nonobject(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["sections"].append("not-a-dict")
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_sections_nonobject)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "plan_spec.sections: non-object entries")
        )
        results.append(_scenario(
            "fail-closed: plan_spec.sections contains a string entry → "
            "ERROR (no traceback)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
        ))

    # 32. plan_spec.planning is a string.
    def mut_planning_string(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["planning"] = "not-an-object"
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_planning_string)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "plan_spec.planning: not an object")
        )
        results.append(_scenario(
            "fail-closed: plan_spec.planning is a string → ERROR (no traceback)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
        ))

    # 33. section.slide_indices is a string (top-level shapes still ok).
    def mut_slide_indices_string(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["sections"][0]["slide_indices"] = "not-a-list"
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_slide_indices_string)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "slide_indices is not a list")
        )
        results.append(_scenario(
            "fail-closed: section.slide_indices is a string → ERROR (no traceback)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
        ))

    # 34. slide.source_refs is a string (top-level shapes still ok).
    def mut_source_refs_string(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][0]["source_refs"] = "not-a-list"
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_source_refs_string)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "source_refs is not a list")
        )
        results.append(_scenario(
            "fail-closed: slide.source_refs is a string → ERROR (no traceback)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
        ))

    # 35. slide.index is an unhashable value (a JSON array). set()/in
    # would otherwise raise TypeError: unhashable type: 'list'.
    def mut_index_unhashable(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][0]["index"] = [1, 2]
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_index_unhashable)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "slides[].index has unhashable value(s)")
        )
        results.append(_scenario(
            "fail-closed: slide.index is unhashable (list) → ERROR (no traceback)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
        ))

    # 36. slide.section_id is an unhashable value (a JSON array). The
    # 'sid in section_by_id' membership check would otherwise crash.
    def mut_section_id_unhashable(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][0]["section_id"] = [1, 2]
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_section_id_unhashable)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "section_id is not hashable")
        )
        results.append(_scenario(
            "fail-closed: slide.section_id is unhashable (list) → ERROR (no traceback)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
        ))

    # 37. section.slide_indices contains an unhashable item. The
    # 'idx in seen_local' check / set.add() would otherwise crash.
    def mut_slide_indices_item_unhashable(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["sections"][0]["slide_indices"] = [1, [2, 3]]
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(
            Path(raw_td), mut_slide_indices_item_unhashable,
        )
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "slide_indices contains an unhashable value")
        )
        results.append(_scenario(
            "fail-closed: section.slide_indices contains an unhashable item → "
            "ERROR (no traceback)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
        ))

    # 38. slide.source_refs contains an unhashable item. The
    # 'ref in brief_refs_set' membership check would otherwise crash.
    def mut_source_refs_item_unhashable(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][0]["source_refs"] = ["fixture_source", [1, 2]]
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(
            Path(raw_td), mut_source_refs_item_unhashable,
        )
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "source_refs contains an unhashable value")
        )
        results.append(_scenario(
            "fail-closed: slide.source_refs contains an unhashable item → "
            "ERROR (no traceback)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
        ))

    # 39. slide.index values mix unorderable types (str alongside int).
    # sorted() across multiple slides would otherwise crash with
    # "TypeError: '<' not supported between instances of 'str' and 'int'".
    def mut_index_mixed_sort(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][0]["index"] = "one"
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_index_mixed_sort)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "slides[].index must be contiguous")
        )
        results.append(_scenario(
            "fail-closed: slide.index values mix str + int → ERROR (no traceback)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
        ))

    # 40. Overclaim: ai-generated label in slide_plan notes. The repo's
    # bridge contract turns an explicit authoring bundle into a workspace
    # — it does NOT generate content from prompts via AI — so an
    # ai-generated attribution in any spec field must fail closed.
    def mut_overclaim_ai_generated(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        spec = json.loads(spec_path.read_text())
        spec["notes"] = "Body copy was AI-generated from the prompt."
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_overclaim_ai_generated)
        ok = (
            not report.ok
            and _has_error(report, "ai-generated")
            and _has_error(report, "overclaim")
        )
        results.append(_scenario(
            "overclaim: slide_plan notes claiming 'AI-generated' content "
            "flagged (this repo is a bridge contract, not an AI generator)",
            ok,
            f"errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # 41. Overclaim: prompt-to-pptx claim in image_manifest alt_text. The
    # repo is not a prompt/report/Markdown-to-PPTX automation; an alt_text
    # asserting it is must fail closed.
    def mut_overclaim_prompt_to_pptx(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["image_refs"] = ["accent"]
        spec["blocks"].append(
            {"id": "accent", "kind": "image_ref", "content": "accent"},
        )
        _write_json(spec_path, spec)
        _write_json(bundle["image_manifest_spec"], {
            "images": [
                {"id": "accent", "local_path": "assets/a.svg",
                 "source": "synthetic",
                 "alt_text": "Produced by the prompt-to-pptx pipeline."},
            ],
        })
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_overclaim_prompt_to_pptx)
        ok = (
            not report.ok
            and _has_error(report, "prompt-to-pptx")
            and _has_error(report, "overclaim")
        )
        results.append(_scenario(
            "overclaim: image_manifest alt_text claiming 'prompt-to-pptx' "
            "automation flagged (this repo is a bridge contract, not a "
            "prompt-to-PPTX automation)",
            ok,
            f"errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # 42. Overclaim: model-generated label in plan_spec rationale. Any
    # spec field that claims model-driven generation must fail closed.
    def mut_overclaim_model_generated(td, bundle):
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["planning"]["rationale"] = (
            "Slide list is model-generated from the source brief."
        )
        _write_json(bundle["plan_spec"], plan)
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_overclaim_model_generated)
        ok = (
            not report.ok
            and _has_error(report, "model-generated")
            and _has_error(report, "overclaim")
        )
        results.append(_scenario(
            "overclaim: plan_spec rationale claiming 'model-generated' "
            "content flagged (this repo is a bridge contract, not a "
            "model-driven generator)",
            ok,
            f"errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # 43. Overclaim: automatic prompt-to-* assertion in slide_plan notes.
    # The suffix is intentionally NOT one of the specific "prompt-to-<x>"
    # tokens — those would trip first and the scanner returns on the
    # first match, so this scenario would otherwise verify the wrong gate.
    def mut_overclaim_automatic_prompt_to(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        spec = json.loads(spec_path.read_text())
        spec["notes"] = "Generated via an automatic prompt-to-slides workflow."
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report = _run_gate(Path(raw_td), mut_overclaim_automatic_prompt_to)
        ok = (
            not report.ok
            and _has_error(report, "automatic prompt-to")
            and _has_error(report, "overclaim")
        )
        results.append(_scenario(
            "overclaim: slide_plan notes claiming an 'automatic prompt-to-*' "
            "workflow flagged (this repo is a bridge contract, not a "
            "prompt-to-* automation)",
            ok,
            f"errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    return results


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
