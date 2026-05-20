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
    privacy / clean-room rule the agent owns (this includes every block
    the render-model generator would silently drop — a ``chart_ref`` of
    any kind, an anonymous block with no ``id``, or a block whose ``id``
    is not declared by the resolved layout's slots). The gate exits
    non-zero.
  - ``WARN``  — agent should review before running, but the bundle is not
    structurally invalid (e.g. a slide spec whose filename does not match
    the canonical ``<index:02d>_<layout>.json`` pattern). The gate exits
    0 unless ``--strict`` is passed (which promotes every WARN to ERROR).

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

# Lazy-import the render-model generator's supported-layout tuple plus the
# small list-of-items capacity constants so the authoring gate and the
# generator stay in lockstep (mirrors the lazy import in
# scripts/validate_workspace.py::check_generator_render_model_coverage).
from generate_render_models import (  # noqa: E402
    SUPPORTED_LAYOUTS as _RENDER_SUPPORTED_LAYOUTS,
    LAYOUT_FALLBACK_BOUNDS as _RENDER_LAYOUT_FALLBACK_BOUNDS,
    LIST_ITEM_MIN_H as _RENDER_LIST_ITEM_MIN_H,
)

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
# Generator-grounded per-kind block-structure check. Mirrors the per-kind
# block-shape guards in scripts/generate_render_models.py so an authoring
# bundle whose blocks are structurally incompatible with the render-model
# generator (chart_ref kind anywhere, duplicate / anonymous / unknown-slot-
# id blocks, kind drift on optional slots, malformed text / callout / list
# / kpi / table / image_ref payloads, and a list slot whose item count
# would overflow LIST_ITEM_MIN_H per slot height) fails closed at authoring
# time instead. The schema's `additionalProperties: false` on each block
# already covers unknown KEYS; this helper covers unknown / mis-shaped
# CONTENT and per-layout slot fit.
#
# This is NOT full generator parity. The generator additionally enforces
# integer-arithmetic gates (KPI tile-width positivity in `_kpi_tile_bounds`,
# slot-bounds presence in `_check_slot_present`, palette / typography token
# resolution against the design_system) that are layout / token concerns
# rather than per-block authoring concerns; those remain runtime-only.
# Anything not enumerated below is reported by the runtime helpers, not
# by this gate.
# ---------------------------------------------------------------------------

# Block kinds that carry a render-model-affecting payload (chart / image /
# kpi / table). When one of these appears on a layout slot the layout does
# NOT declare, the agent likely intended a chart/image/table/kpi to render
# on this slide and the generator would silently drop it — the diagnostic
# calls out the payload-smuggling intent so the agent can fix the slot id.
# Plain text/list/callout blocks with an unknown id also fail as ERROR
# (the generator would still drop them, leaving the agent's content
# invisible), but the diagnostic frames the issue as "dead content" rather
# than "smuggled payload" so the agent sees the right fix.
_SMUGGLEABLE_KINDS: frozenset[str] = frozenset({"image_ref", "table", "kpi"})


def _check_block_structure(
    rel: str,
    spec: dict,
    layout_name: str,
    layouts_by_name: dict[str, dict] | None,
    report: Report,
) -> None:
    """Walk spec.blocks once and apply the generator-grounded per-block
    rules enumerated below. Each rule mirrors a specific runtime helper
    in scripts/generate_render_models.py; rules NOT enumerated here
    (KPI tile-width arithmetic, palette / typography token resolution,
    layout slot-presence checks the generator itself hardcodes) remain
    runtime-only and are documented in the helper's banner comment.

    Rules applied (in order, per block):
      1. Block must be an object (schema gate already reports otherwise;
         we skip such entries here).
      2. block.kind == 'chart_ref' → ERROR everywhere (no SUPPORTED layout
         maps to the chart_placeholder primitive today).
      3. block.id absent / empty → ERROR (the generator builds blocks_by_id
         only from blocks with a string id; anonymous blocks are silently
         dropped at runtime, so the authoring bundle is structurally
         incompatible with the generator).
      4. block.id duplicated within this spec → ERROR (the generator's
         blocks_by_id dict would silently overwrite earlier entries with
         the last one, producing a wrong visual without warning).
      5. block.id present but the layout has no slot with that id → ERROR
         in every case (the generator silently drops blocks whose id is
         not consumed by the layout's slots). The diagnostic distinguishes
         two failure modes so the agent sees the right fix:
           - block.kind in _SMUGGLEABLE_KINDS (chart/image/table/kpi)
             frames the issue as payload smuggling — the agent likely
             expected the chart/image/table/kpi to render;
           - text/list/callout frames the issue as dead content — the
             block would have no visual effect on the slide.
      6. block.kind != slot.type for the resolved layout slot → ERROR
         (the generator's per-kind helpers — _text_block_content,
         _callout_block_content, _list_block_content — would refuse the
         drift; covers required AND optional slots, where the schema-
         layer _slide_plan_against_layout gate only fires for required).
      7. Per-kind content rules, mirroring the generator's per-helper
         assertions exactly:
           - text / callout / image_ref: content must be a non-empty string.
           - list: content must be a non-empty list of non-empty strings.
           - kpi: content must be a non-empty list of dicts; each dict
             must declare non-empty string `label` and `value`; optional
             `delta` (when present) must be a non-empty string; no other
             keys (the generator silently ignores extras — flagging here
             so the agent does not believe a smuggled chart/image
             payload on a kpi entry actually rendered).
           - table: content must be a dict with non-empty `headers`
             (list of non-empty strings) and non-empty `rows` (list of
             non-empty lists of non-empty string cells); every row's
             cell count must equal len(headers); no other keys.
      8. List capacity rule (list kind only, slot known, slot bounds
         resolvable). Mirrors `_list_item_bounds` in the render-model
         generator: `slot_height // count` must be at least
         `LIST_ITEM_MIN_H` (28 px today), otherwise the generator
         refuses with "list slot too short for N items". Slot bounds
         are resolved from `slot.bounds` when present, else from
         `LAYOUT_FALLBACK_BOUNDS[layout_name][slot_id]` (the same
         fallback table the generator's `_bounds_or_fallback` reads).
         When neither is available (no slot match, no bounds at all,
         non-integer height), the capacity check is skipped rather
         than asserted — the runtime helpers re-fire downstream and
         this gate degrades to its earlier coverage instead of
         tracebacking on missing layout metadata.

    When layouts_by_name is None or layout_name is unknown, rules 5,
    6, and 8 are skipped (we don't have the slot map or bounds to
    compare against) and rules 1-4 and 7 still apply. Earlier checks
    in the gate already reported the missing layout, so this is fail-
    closed degradation, not a false-pass."""
    blocks = spec.get("blocks")
    if not isinstance(blocks, list):
        return  # schema gate already reported

    slot_by_id: dict[str, dict] = {}
    if layouts_by_name is not None and layout_name in layouts_by_name:
        layout = layouts_by_name[layout_name]
        slots = layout.get("slots") if isinstance(layout, dict) else None
        if isinstance(slots, list):
            for s in slots:
                if isinstance(s, dict) and isinstance(s.get("id"), str):
                    slot_by_id[s["id"]] = s
    have_layout = layouts_by_name is not None and layout_name in layouts_by_name

    seen_ids: dict[str, int] = {}
    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue  # schema gate reported
        kind = block.get("kind")
        bid = block.get("id")

        # Rule 4 (duplicate id) is evaluated up front so the diagnostic
        # references the *second* occurrence's position.
        if isinstance(bid, str) and bid:
            if bid in seen_ids:
                report.err(
                    f"slide_spec.{rel}: blocks[{i}] duplicate block id",
                    f"id {bid!r} already declared by blocks[{seen_ids[bid]}]; "
                    f"the render-model generator's blocks_by_id dict would "
                    f"silently keep only the last occurrence",
                )
            else:
                seen_ids[bid] = i

        # Rule 2: chart_ref kind anywhere.
        if kind == "chart_ref":
            report.err(
                f"slide_spec.{rel}: blocks[{i}] uses kind 'chart_ref'",
                "the render-model generator has no SUPPORTED layout that "
                "maps to the chart_placeholder primitive today; the PPTX "
                "exporter would fail closed on this slide",
            )
            continue

        # Rule 3: anonymous block.
        if not isinstance(bid, str) or not bid:
            report.err(
                f"slide_spec.{rel}: blocks[{i}] has no string id",
                f"the render-model generator builds blocks_by_id only from "
                f"blocks with a string id; this block (kind={kind!r}) would "
                f"be silently dropped at runtime",
            )
            continue

        # Rules 5 / 6: slot-fit checks (only when we have the layout).
        if have_layout:
            slot = slot_by_id.get(bid)
            if slot is None:
                if kind in _SMUGGLEABLE_KINDS:
                    report.err(
                        f"slide_spec.{rel}: blocks[{i}] id {bid!r} is not "
                        f"declared by layout {layout_name!r}",
                        f"kind {kind!r} carries a chart/image/table/kpi "
                        f"payload the agent likely expected to render; the "
                        f"render-model generator silently drops blocks "
                        f"whose id is not consumed by the layout's slots "
                        f"({sorted(slot_by_id)})",
                    )
                else:
                    report.err(
                        f"slide_spec.{rel}: blocks[{i}] id {bid!r} is not "
                        f"declared by layout {layout_name!r}",
                        f"kind {kind!r} would be silently dropped by the "
                        f"render-model generator (dead content — no visual "
                        f"effect on the slide); declared layout slots are "
                        f"{sorted(slot_by_id)}",
                    )
                continue
            slot_type = slot.get("type")
            if isinstance(slot_type, str) and kind != slot_type:
                report.err(
                    f"slide_spec.{rel}: blocks[{i}] kind drift vs layout "
                    f"{layout_name!r} slot {bid!r}",
                    f"layout slot expects kind {slot_type!r}; got kind "
                    f"{kind!r}; the render-model generator's per-kind "
                    f"helper would refuse this at runtime",
                )
                continue

        # Rule 7: per-kind content rules. Schema enum already restricted
        # kind ∈ {text,list,kpi,table,image_ref,chart_ref,callout}; chart_ref
        # was handled at rule 2 so it cannot reach this branch.
        _check_block_content(rel, i, bid, kind, block.get("content"), report)

        # Rule 8: list-slot capacity (only when we have the layout AND the
        # block is a list AND its content is a non-empty list of strings —
        # rule 7 would have errored otherwise; in that case rule 8 is
        # silently skipped to avoid piling on noise).
        if have_layout and kind == "list":
            content = block.get("content")
            if isinstance(content, list) and content and all(
                isinstance(item, str) and item for item in content
            ):
                _check_list_slot_capacity(
                    rel, i, bid, layout_name, slot_by_id.get(bid),
                    len(content), report,
                )


def _check_block_content(
    rel: str,
    i: int,
    bid: str,
    kind: object,
    content: object,
    report: Report,
) -> None:
    """Apply the per-kind content-shape rules from the render-model
    generator. Each branch mirrors the generator's runtime assertions
    so an authoring bundle that would crash the per-slide generator
    fails closed here first."""
    label_prefix = f"slide_spec.{rel}: blocks[{i}] (id={bid!r}, kind={kind!r})"

    if kind in ("text", "callout", "image_ref"):
        if not isinstance(content, str) or not content:
            report.err(
                f"{label_prefix} content must be a non-empty string",
                f"got {type(content).__name__}: {content!r}; the render-model "
                f"generator's per-kind helper would refuse this at runtime",
            )
        return

    if kind == "list":
        if not isinstance(content, list) or not content:
            report.err(
                f"{label_prefix} content must be a non-empty list of strings",
                f"got {type(content).__name__}: {content!r}; the render-model "
                f"generator's _list_block_content would refuse this at runtime",
            )
            return
        for j, item in enumerate(content):
            if not isinstance(item, str) or not item:
                report.err(
                    f"{label_prefix} content[{j}] is not a non-empty string",
                    f"got {type(item).__name__}: {item!r}; every list entry "
                    f"must be a non-empty string",
                )
        return

    if kind == "kpi":
        if not isinstance(content, list) or not content:
            report.err(
                f"{label_prefix} content must be a non-empty list of "
                f"{{label, value, delta?}} objects",
                f"got {type(content).__name__}: {content!r}; the render-model "
                f"generator's kpi_dashboard helper would refuse this at runtime",
            )
            return
        for j, entry in enumerate(content):
            if not isinstance(entry, dict):
                report.err(
                    f"{label_prefix} content[{j}] is not an object",
                    f"got {type(entry).__name__}: {entry!r}; every kpi entry "
                    f"must be a {{label, value, delta?}} object",
                )
                continue
            label = entry.get("label")
            value = entry.get("value")
            delta = entry.get("delta")
            if not isinstance(label, str) or not label:
                report.err(
                    f"{label_prefix} content[{j}].label is not a non-empty string",
                    f"got {type(label).__name__}: {label!r}",
                )
            if not isinstance(value, str) or not value:
                report.err(
                    f"{label_prefix} content[{j}].value is not a non-empty string",
                    f"got {type(value).__name__}: {value!r}",
                )
            if delta is not None and (not isinstance(delta, str) or not delta):
                report.err(
                    f"{label_prefix} content[{j}].delta must be a non-empty "
                    f"string when set",
                    f"got {type(delta).__name__}: {delta!r}",
                )
            extras = sorted(set(entry.keys()) - {"label", "value", "delta"})
            if extras:
                report.err(
                    f"{label_prefix} content[{j}] declares unsupported key(s) "
                    f"{extras}",
                    "the render-model generator only reads label / value / "
                    "delta; extra keys (chart payloads, image hints, etc.) "
                    "would be silently dropped — refusing here so smuggled "
                    "payloads cannot masquerade as rendered KPI fields",
                )
        return

    if kind == "table":
        if not isinstance(content, dict):
            report.err(
                f"{label_prefix} content must be an object with "
                f"'headers' (non-empty list of strings) and 'rows' "
                f"(non-empty list of equal-length row arrays)",
                f"got {type(content).__name__}: {content!r}",
            )
            return
        headers = content.get("headers")
        rows_raw = content.get("rows")
        col_count: int | None = None
        if not isinstance(headers, list) or not headers:
            report.err(
                f"{label_prefix} content.headers must be a non-empty list "
                f"of non-empty strings",
                f"got {type(headers).__name__}: {headers!r}",
            )
        else:
            col_count = len(headers)
            for j, h in enumerate(headers):
                if not isinstance(h, str) or not h:
                    report.err(
                        f"{label_prefix} content.headers[{j}] is not a "
                        f"non-empty string",
                        f"got {type(h).__name__}: {h!r}",
                    )
        if not isinstance(rows_raw, list) or not rows_raw:
            report.err(
                f"{label_prefix} content.rows must be a non-empty list "
                f"of row arrays",
                f"got {type(rows_raw).__name__}: {rows_raw!r}",
            )
        else:
            for r_i, row in enumerate(rows_raw):
                if not isinstance(row, list) or not row:
                    report.err(
                        f"{label_prefix} content.rows[{r_i}] must be a "
                        f"non-empty list",
                        f"got {type(row).__name__}: {row!r}",
                    )
                    continue
                if col_count is not None and len(row) != col_count:
                    report.err(
                        f"{label_prefix} content.rows[{r_i}] has {len(row)} "
                        f"cell(s) but content.headers declares {col_count} "
                        f"column(s)",
                        "every row must match the column count; the render-"
                        "model generator's comparison_table helper would "
                        "refuse this at runtime",
                    )
                for c_i, cell in enumerate(row):
                    if not isinstance(cell, str) or not cell:
                        report.err(
                            f"{label_prefix} content.rows[{r_i}][{c_i}] is "
                            f"not a non-empty string",
                            f"got {type(cell).__name__}: {cell!r}; cell "
                            f"payloads must be non-empty strings — numeric "
                            f"or rich-text payloads are not yet supported",
                        )
        extras = sorted(set(content.keys()) - {"headers", "rows"})
        if extras:
            report.err(
                f"{label_prefix} content declares unsupported key(s) {extras}",
                "the render-model generator only reads headers / rows; "
                "extra keys (chart configs, formatting payloads, etc.) "
                "would be silently dropped — refusing here so smuggled "
                "payloads cannot masquerade as rendered table fields",
            )
        return

    # An unknown kind would have been caught by the schema enum; do nothing
    # here as a defensive no-op so the gate cannot traceback on an
    # unexpected kind value.


def _resolve_list_slot_height(
    slot: dict | None, layout_name: str, slot_id: str,
) -> int | None:
    """Mirror the render-model generator's `_bounds_or_fallback` for the
    height field only. Prefer `slot.bounds.h` when fully integer; else
    look up `LAYOUT_FALLBACK_BOUNDS[layout_name][slot_id]` (the same
    fallback table the generator reads). Returns None when no integer
    height can be resolved (the capacity check then degrades to a no-op
    rather than a false-pass)."""
    if isinstance(slot, dict):
        b = slot.get("bounds")
        if isinstance(b, dict):
            h = b.get("h")
            if isinstance(h, int) and not isinstance(h, bool):
                return h
    fb = _RENDER_LAYOUT_FALLBACK_BOUNDS.get(layout_name)
    if isinstance(fb, dict):
        entry = fb.get(slot_id)
        if isinstance(entry, tuple) and len(entry) == 4:
            h = entry[3]
            if isinstance(h, int) and not isinstance(h, bool):
                return h
    return None


def _check_list_slot_capacity(
    rel: str,
    i: int,
    bid: str,
    layout_name: str,
    slot: dict | None,
    count: int,
    report: Report,
) -> None:
    """Apply the render-model generator's `_list_item_bounds` capacity
    rule at authoring time. The generator distributes `count` items
    inside a slot of height `slot_h` and refuses when
    `slot_h // count < LIST_ITEM_MIN_H` ("list slot too short for N
    items"). Mirror that here so the agent sees the failure before a
    six-stage prep run."""
    if count <= 0:
        return
    slot_h = _resolve_list_slot_height(slot, layout_name, bid)
    if slot_h is None:
        return
    item_h = slot_h // count
    if item_h < _RENDER_LIST_ITEM_MIN_H:
        report.err(
            f"slide_spec.{rel}: blocks[{i}] (id={bid!r}, kind='list') "
            f"has too many items for the {layout_name!r} slot",
            f"slot height {slot_h}px / {count} item(s) = {item_h}px per "
            f"item; the render-model generator's _list_item_bounds "
            f"requires at least {_RENDER_LIST_ITEM_MIN_H}px per item "
            f"and would fail closed with 'list slot too short for "
            f"{count} items' at runtime",
        )


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
        # Generator-grounded per-kind block-structure checks. Mirrors the
        # specific per-block rules in scripts/generate_render_models.py
        # (chart_ref kind anywhere, anonymous / duplicate / unknown-slot-id
        # blocks, kind drift on optional slots, per-kind content-shape
        # rules, list-slot capacity vs LIST_ITEM_MIN_H). This is NOT full
        # generator parity — see _check_block_structure's banner comment
        # for the runtime-only rules that remain out of scope.
        _check_block_structure(rel, spec, layout, layouts_by_name, report)
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


# Canonical bundle layout under ``--bundle <dir>``. Names are fixed so the
# trial directory shape (and any other agent-authored bundle) is portable.
_BUNDLE_SOURCE_CANDIDATES = ("source.md", "source.txt")
_BUNDLE_BRIEF_NAME = "brief.json"
_BUNDLE_PLAN_SPEC_NAME = "plan_spec.json"
_BUNDLE_DESIGN_SYSTEM_SPEC_NAME = "design_system_spec.json"
_BUNDLE_SLIDE_SPECS_NAME = "slide_specs"
_BUNDLE_IMAGE_MANIFEST_SPEC_NAME = "image_manifest_spec.json"
_BUNDLE_BRIEF_ALLOWED_FIELDS = frozenset((
    "title", "audience", "objective",
    "tone", "language", "approximate_slide_count", "source_id",
))
_BUNDLE_BRIEF_REQUIRED_FIELDS = ("title", "audience", "objective")


def _resolve_bundle(
    bundle_dir: Path, *, theme_from_template: bool,
) -> tuple[dict | None, str | None]:
    """Resolve the canonical bundle layout into a kwargs dict that
    matches ``validate_authoring_bundle``'s keyword arguments.

    Returns ``(kwargs, None)`` on success, ``(None, message)`` on any
    failure — symlinked bundle, missing required entry, brief.json
    malformed or missing required fields, design-system mode conflict.

    The helper is read-only; it never writes to the bundle. Brief
    metadata is read from ``<dir>/brief.json``; every other input maps
    1:1 to the explicit ``--*-spec`` flags.

    Path safety: the bundle directory itself must be a real directory
    (URI-shaped paths, symlinks, and non-directories are refused) and
    every required entry must be a non-symlink regular file / directory.
    Symlinks anywhere in the canonical layout would let an attacker who
    controls the bundle redirect reads outside it; downstream init_*
    helpers refuse symlinks for the same reason."""
    if _has_uri_scheme(str(bundle_dir)):
        return None, (
            f"--bundle looks like a URI: {bundle_dir} — only local "
            f"directory paths are accepted"
        )
    if bundle_dir.is_symlink():
        return None, f"--bundle is a symlink (refused): {bundle_dir}"
    if not bundle_dir.exists():
        return None, f"--bundle does not exist: {bundle_dir}"
    if not bundle_dir.is_dir():
        return None, f"--bundle is not a directory: {bundle_dir}"

    def _check_regular_file(name: str) -> tuple[Path | None, str | None]:
        path = bundle_dir / name
        if path.is_symlink():
            return None, (
                f"--bundle entry {name} is a symlink (refused): {path}"
            )
        if not path.exists():
            return None, f"--bundle is missing required entry {name}: {path}"
        if not path.is_file():
            return None, (
                f"--bundle entry {name} is not a regular file: {path}"
            )
        return path, None

    def _check_directory(name: str) -> tuple[Path | None, str | None]:
        path = bundle_dir / name
        if path.is_symlink():
            return None, (
                f"--bundle entry {name}/ is a symlink (refused): {path}"
            )
        if not path.exists():
            return None, (
                f"--bundle is missing required entry {name}/: {path}"
            )
        if not path.is_dir():
            return None, (
                f"--bundle entry {name}/ is not a directory: {path}"
            )
        return path, None

    # Source: exactly one of source.md / source.txt; symlinks refused.
    present_sources: list[Path] = []
    for cand in _BUNDLE_SOURCE_CANDIDATES:
        cand_path = bundle_dir / cand
        if cand_path.is_symlink():
            return None, (
                f"--bundle entry {cand} is a symlink (refused): {cand_path}"
            )
        if cand_path.exists():
            if not cand_path.is_file():
                return None, (
                    f"--bundle entry {cand} is not a regular file: "
                    f"{cand_path}"
                )
            present_sources.append(cand_path)
    if not present_sources:
        return None, (
            f"--bundle is missing a source body: expected one of "
            f"{list(_BUNDLE_SOURCE_CANDIDATES)} under {bundle_dir}"
        )
    if len(present_sources) > 1:
        return None, (
            f"--bundle declares more than one source body "
            f"({[p.name for p in present_sources]}); keep exactly one of "
            f"{list(_BUNDLE_SOURCE_CANDIDATES)} under {bundle_dir}"
        )
    source = present_sources[0]

    brief_path, err = _check_regular_file(_BUNDLE_BRIEF_NAME)
    if err is not None:
        return None, err
    plan_spec, err = _check_regular_file(_BUNDLE_PLAN_SPEC_NAME)
    if err is not None:
        return None, err
    slide_specs_dir, err = _check_directory(_BUNDLE_SLIDE_SPECS_NAME)
    if err is not None:
        return None, err
    image_manifest_spec, err = _check_regular_file(_BUNDLE_IMAGE_MANIFEST_SPEC_NAME)
    if err is not None:
        return None, err

    # Design-system mode resolution. The bundle's design_system_spec.json
    # selects --design-system-spec mode; --theme-from-template lets the
    # caller opt out, but mixing both is ambiguous so we refuse.
    ds_path = bundle_dir / _BUNDLE_DESIGN_SYSTEM_SPEC_NAME
    if ds_path.is_symlink():
        return None, (
            f"--bundle entry {_BUNDLE_DESIGN_SYSTEM_SPEC_NAME} is a "
            f"symlink (refused): {ds_path}"
        )
    ds_present = ds_path.exists()
    if ds_present and not ds_path.is_file():
        return None, (
            f"--bundle entry {_BUNDLE_DESIGN_SYSTEM_SPEC_NAME} is not a "
            f"regular file: {ds_path}"
        )
    if theme_from_template and ds_present:
        return None, (
            f"--bundle includes {_BUNDLE_DESIGN_SYSTEM_SPEC_NAME} but "
            f"--theme-from-template was also passed; pick exactly one "
            f"design-system mode"
        )
    if not theme_from_template and not ds_present:
        return None, (
            f"--bundle is missing {_BUNDLE_DESIGN_SYSTEM_SPEC_NAME} and "
            f"--theme-from-template was not passed: {ds_path}"
        )
    design_system_spec = ds_path if ds_present else None

    # Read brief.json.
    try:
        raw_brief = brief_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, (
            f"--bundle entry {_BUNDLE_BRIEF_NAME} is not UTF-8 readable: "
            f"{brief_path}: {type(exc).__name__}: {exc}"
        )
    try:
        brief = json.loads(raw_brief)
    except json.JSONDecodeError as exc:
        return None, (
            f"--bundle entry {_BUNDLE_BRIEF_NAME} is malformed JSON: "
            f"{brief_path}: {exc}"
        )
    if not isinstance(brief, dict):
        return None, (
            f"--bundle entry {_BUNDLE_BRIEF_NAME} top-level value is not "
            f"a JSON object; got {type(brief).__name__} at {brief_path}"
        )
    missing = [k for k in _BUNDLE_BRIEF_REQUIRED_FIELDS if k not in brief]
    if missing:
        return None, (
            f"--bundle entry {_BUNDLE_BRIEF_NAME} is missing required "
            f"field(s): {', '.join(missing)} at {brief_path}"
        )
    unknown = sorted(set(brief.keys()) - _BUNDLE_BRIEF_ALLOWED_FIELDS)
    if unknown:
        return None, (
            f"--bundle entry {_BUNDLE_BRIEF_NAME} contains unknown "
            f"field(s): {', '.join(unknown)} at {brief_path}; allowed: "
            f"{sorted(_BUNDLE_BRIEF_ALLOWED_FIELDS)}"
        )

    # Type-validate the optional fields the bundle resolves verbatim into
    # explicit kwargs. The explicit-flag path is already type-coerced by
    # argparse (--source-id type=str, --approximate-slide-count type=int);
    # the --bundle shortcut reads brief.json untyped, so without this gate
    # a malformed value would surface as a downstream TypeError / schema
    # crash rather than a clean CLI diagnostic. ``bool`` is rejected for
    # approximate_slide_count even though ``isinstance(True, int)`` is
    # True — a literal JSON ``true`` is not a slide count.
    if "source_id" in brief and not isinstance(brief["source_id"], str):
        return None, (
            f"--bundle entry {_BUNDLE_BRIEF_NAME} field source_id must be "
            f"a string if present; got "
            f"{type(brief['source_id']).__name__} at {brief_path}"
        )
    if "approximate_slide_count" in brief:
        value = brief["approximate_slide_count"]
        if isinstance(value, bool) or not isinstance(value, int):
            return None, (
                f"--bundle entry {_BUNDLE_BRIEF_NAME} field "
                f"approximate_slide_count must be an integer if present; "
                f"got {type(value).__name__} at {brief_path}"
            )

    return {
        "source": source,
        "source_id": brief.get("source_id"),
        "title": brief["title"],
        "audience": brief["audience"],
        "objective": brief["objective"],
        "tone": brief.get("tone"),
        "language": brief.get("language"),
        "approximate_slide_count": brief.get("approximate_slide_count"),
        "plan_spec": plan_spec,
        "design_system_spec": design_system_spec,
        "slide_specs_dir": slide_specs_dir,
        "image_manifest_spec": image_manifest_spec,
    }, None


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
        "--bundle", type=Path, default=None,
        help="Resolve every explicit-input spec from a single bundle "
             "directory. Canonical layout: <dir>/source.md (or "
             "source.txt), <dir>/brief.json (JSON object with title / "
             "audience / objective and optional tone / language / "
             "approximate_slide_count / source_id), <dir>/plan_spec.json, "
             "<dir>/design_system_spec.json (omit when "
             "--theme-from-template is passed), <dir>/slide_specs/, "
             "<dir>/image_manifest_spec.json. Mutually exclusive with the "
             "explicit per-input flags; --template-root remains required "
             "and --theme-from-template / --strict still apply.",
    )
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
            args.bundle,
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

    if args.bundle is not None:
        # --bundle is a shortcut: every explicit per-input flag must be
        # absent so precedence is unambiguous and the caller picks one
        # mode. --template-root, --theme-from-template, and --strict are
        # the only flags that compose with --bundle.
        conflicting = [
            name for name, value in (
                ("--source", args.source),
                ("--source-id", args.source_id),
                ("--title", args.title),
                ("--audience", args.audience),
                ("--objective", args.objective),
                ("--tone", args.tone),
                ("--language", args.language),
                ("--approximate-slide-count", args.approximate_slide_count),
                ("--plan-spec", args.plan_spec),
                ("--design-system-spec", args.design_system_spec),
                ("--slide-specs-dir", args.slide_specs_dir),
                ("--image-manifest-spec", args.image_manifest_spec),
            )
            if value is not None
        ]
        if conflicting:
            print(
                f"FAIL: --bundle is mutually exclusive with the explicit "
                f"per-input flags ({', '.join(conflicting)}); pass one or "
                f"the other, not both",
                file=sys.stderr,
            )
            return 2
        resolved, err = _resolve_bundle(
            args.bundle, theme_from_template=args.theme_from_template,
        )
        if err is not None:
            print(f"FAIL: {err}", file=sys.stderr)
            return 2
        args.source = resolved["source"]
        args.source_id = resolved["source_id"]
        args.title = resolved["title"]
        args.audience = resolved["audience"]
        args.objective = resolved["objective"]
        args.tone = resolved["tone"]
        args.language = resolved["language"]
        args.approximate_slide_count = resolved["approximate_slide_count"]
        args.plan_spec = resolved["plan_spec"]
        args.design_system_spec = resolved["design_system_spec"]
        args.slide_specs_dir = resolved["slide_specs_dir"]
        args.image_manifest_spec = resolved["image_manifest_spec"]

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

    # ---------------------------------------------------------------------
    # Generator-level per-kind block-structure gates. Each scenario builds
    # the happy-path bundle and mutates one slide spec so the new gate must
    # surface a specific ERROR (or WARN) without tracebacking. The gates
    # mirror scripts/generate_render_models.py per-kind helpers so an
    # authoring bundle that would crash the generator at runtime fails
    # closed at authoring time first.
    # ---------------------------------------------------------------------

    # G1. text block content is an empty string. Generator's
    # _text_block_content refuses; the gate must flag it as ERROR.
    def mut_text_empty(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        for b in spec["blocks"]:
            if b.get("id") == "title":
                b["content"] = ""
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_text_empty)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "kind='text'")
            and _has_error(report, "non-empty string")
        )
        results.append(_scenario(
            "block-structure: text block with empty content flagged as ERROR",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G2. text block content is a non-string (a number). Generator's
    # _text_block_content refuses on the isinstance check.
    def mut_text_number(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        for b in spec["blocks"]:
            if b.get("id") == "title":
                b["content"] = 42
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_text_number)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "kind='text'")
            and _has_error(report, "non-empty string")
        )
        results.append(_scenario(
            "block-structure: text block with numeric content flagged as ERROR",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G3. callout block content is an empty string. Generator's
    # _callout_block_content refuses.
    def mut_callout_empty(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        spec = json.loads(spec_path.read_text())
        for b in spec["blocks"]:
            if b.get("id") == "message":
                b["content"] = ""
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_callout_empty)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "kind='callout'")
            and _has_error(report, "non-empty string")
        )
        results.append(_scenario(
            "block-structure: callout block with empty content flagged as ERROR",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G4. list block content with an empty-string entry. Generator's
    # _list_block_content refuses every non-string-or-empty item.
    def mut_list_empty_item(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        spec = json.loads(spec_path.read_text())
        # Add a list block via a known optional slot — supporting_text is
        # a text slot so reuse the message slot context: we'll mutate the
        # plan and the spec so the slide becomes an executive_summary.
        # Simpler: replace 02_key_message's plan/layout so it's
        # executive_summary for this scenario.
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][1]["layout"] = "executive_summary"
        plan["slides"][1]["title"] = "Trial Summary"
        _write_json(bundle["plan_spec"], plan)
        new_spec = {
            "index": 2, "layout": "executive_summary", "title": "Trial Summary",
            "blocks": [
                {"id": "title",   "kind": "text", "content": "Trial Summary"},
                {"id": "summary", "kind": "text", "content": "Summary text."},
                {"id": "key_points", "kind": "list",
                 "content": ["valid first point", ""]},  # empty entry
            ],
        }
        spec_path.unlink()
        _write_json(spec_path.parent / "02_executive_summary.json", new_spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_list_empty_item)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "kind='list'")
            and _has_error(report, "content[1] is not a non-empty string")
        )
        results.append(_scenario(
            "block-structure: list block with an empty-string entry flagged as ERROR",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G5. list block content is an empty list. Generator's
    # _list_block_content refuses.
    def mut_list_empty(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][1]["layout"] = "agenda"
        plan["slides"][1]["title"] = "Agenda"
        _write_json(bundle["plan_spec"], plan)
        new_spec = {
            "index": 2, "layout": "agenda", "title": "Agenda",
            "blocks": [
                {"id": "title", "kind": "text", "content": "Agenda"},
                {"id": "agenda_items", "kind": "list", "content": []},
            ],
        }
        spec_path.unlink()
        _write_json(spec_path.parent / "02_agenda.json", new_spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_list_empty)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "non-empty list of strings")
        )
        results.append(_scenario(
            "block-structure: list block with empty content list flagged as ERROR",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G6. kpi block content with a missing required field (value). Generator
    # refuses on the isinstance check inside the per-entry loop.
    def mut_kpi_missing_value(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][1]["layout"] = "kpi_dashboard"
        plan["slides"][1]["title"] = "Counters"
        _write_json(bundle["plan_spec"], plan)
        new_spec = {
            "index": 2, "layout": "kpi_dashboard", "title": "Counters",
            "blocks": [
                {"id": "title", "kind": "text", "content": "Counters"},
                {"id": "kpis", "kind": "kpi",
                 "content": [
                     {"label": "slides", "value": "7"},
                     {"label": "sections"},  # missing value
                 ]},
            ],
        }
        spec_path.unlink()
        _write_json(spec_path.parent / "02_kpi_dashboard.json", new_spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_kpi_missing_value)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "content[1].value is not a non-empty string")
        )
        results.append(_scenario(
            "block-structure: kpi entry missing required `value` flagged as ERROR",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G7. kpi block content with an empty-string delta. Generator's
    # kpi_dashboard refuses delta != non-empty-string-when-set.
    def mut_kpi_empty_delta(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][1]["layout"] = "kpi_dashboard"
        plan["slides"][1]["title"] = "Counters"
        _write_json(bundle["plan_spec"], plan)
        new_spec = {
            "index": 2, "layout": "kpi_dashboard", "title": "Counters",
            "blocks": [
                {"id": "title", "kind": "text", "content": "Counters"},
                {"id": "kpis", "kind": "kpi",
                 "content": [
                     {"label": "slides", "value": "7", "delta": ""},
                 ]},
            ],
        }
        spec_path.unlink()
        _write_json(spec_path.parent / "02_kpi_dashboard.json", new_spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_kpi_empty_delta)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "content[0].delta must be a non-empty string")
        )
        results.append(_scenario(
            "block-structure: kpi entry with empty `delta` string flagged as ERROR "
            "(closes the README's known quality gap)",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G8. kpi entry with an unsupported extra key (payload smuggling — e.g.
    # a chart payload glued to a kpi entry that the generator would
    # silently drop).
    def mut_kpi_extra_key(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][1]["layout"] = "kpi_dashboard"
        plan["slides"][1]["title"] = "Counters"
        _write_json(bundle["plan_spec"], plan)
        new_spec = {
            "index": 2, "layout": "kpi_dashboard", "title": "Counters",
            "blocks": [
                {"id": "title", "kind": "text", "content": "Counters"},
                {"id": "kpis", "kind": "kpi",
                 "content": [
                     {"label": "slides", "value": "7",
                      "chart_payload": {"kind": "bar", "values": [1, 2, 3]}},
                 ]},
            ],
        }
        spec_path.unlink()
        _write_json(spec_path.parent / "02_kpi_dashboard.json", new_spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_kpi_extra_key)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "unsupported key(s)")
            and _has_error(report, "chart_payload")
        )
        results.append(_scenario(
            "block-structure: kpi entry with extra `chart_payload` key flagged as "
            "ERROR (chart payload smuggling)",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G9. table block content with mismatched row column count. Generator's
    # comparison_table refuses rows whose len != len(headers).
    def mut_table_short_row(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][1]["layout"] = "comparison_table"
        plan["slides"][1]["title"] = "Compare"
        _write_json(bundle["plan_spec"], plan)
        new_spec = {
            "index": 2, "layout": "comparison_table", "title": "Compare",
            "blocks": [
                {"id": "title", "kind": "text", "content": "Compare"},
                {"id": "table", "kind": "table",
                 "content": {
                     "headers": ["A", "B", "C"],
                     "rows": [
                         ["1", "2", "3"],
                         ["x", "y"],  # short row
                     ],
                 }},
            ],
        }
        spec_path.unlink()
        _write_json(spec_path.parent / "02_comparison_table.json", new_spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_table_short_row)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "content.rows[1] has 2 cell(s)")
            and _has_error(report, "headers declares 3 column(s)")
        )
        results.append(_scenario(
            "block-structure: table row count mismatch with headers flagged as ERROR",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G10. table block content with empty-string cell. Generator's
    # comparison_table refuses empty / non-string cells.
    def mut_table_empty_cell(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][1]["layout"] = "comparison_table"
        plan["slides"][1]["title"] = "Compare"
        _write_json(bundle["plan_spec"], plan)
        new_spec = {
            "index": 2, "layout": "comparison_table", "title": "Compare",
            "blocks": [
                {"id": "title", "kind": "text", "content": "Compare"},
                {"id": "table", "kind": "table",
                 "content": {
                     "headers": ["A", "B"],
                     "rows": [["x", ""]],  # empty cell
                 }},
            ],
        }
        spec_path.unlink()
        _write_json(spec_path.parent / "02_comparison_table.json", new_spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_table_empty_cell)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "content.rows[0][1] is not a non-empty string")
        )
        results.append(_scenario(
            "block-structure: table cell with empty-string content flagged as ERROR",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G11. table content with an unsupported extra key (e.g. a chart config
    # smuggled alongside headers / rows that the generator would silently
    # drop).
    def mut_table_extra_key(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][1]["layout"] = "comparison_table"
        plan["slides"][1]["title"] = "Compare"
        _write_json(bundle["plan_spec"], plan)
        new_spec = {
            "index": 2, "layout": "comparison_table", "title": "Compare",
            "blocks": [
                {"id": "title", "kind": "text", "content": "Compare"},
                {"id": "table", "kind": "table",
                 "content": {
                     "headers": ["A", "B"],
                     "rows": [["x", "y"]],
                     "chart_config": {"kind": "bar", "values": [1, 2]},
                 }},
            ],
        }
        spec_path.unlink()
        _write_json(spec_path.parent / "02_comparison_table.json", new_spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_table_extra_key)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "unsupported key(s)")
            and _has_error(report, "chart_config")
        )
        results.append(_scenario(
            "block-structure: table content with extra `chart_config` key flagged "
            "as ERROR (chart payload smuggling)",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G12. Duplicate block id within the same spec. The render-model
    # generator's blocks_by_id dict silently keeps the last; flag at
    # authoring time so the agent sees both intended primitives, not
    # the silently-overwritten last one.
    def mut_duplicate_block_id(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["blocks"].append(
            {"id": "title", "kind": "text", "content": "Duplicate Title"},
        )
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_duplicate_block_id)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "duplicate block id")
            and _has_error(report, "'title'")
        )
        results.append(_scenario(
            "block-structure: duplicate block id within a spec flagged as ERROR",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G13. Image_ref smuggled into a layout that has no image_ref slot
    # (key_message has only title/message/supporting_text slots). The
    # generator would silently drop the block; flag at authoring time so
    # the agent doesn't believe the image rendered.
    def mut_image_ref_smuggled(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        spec = json.loads(spec_path.read_text())
        spec["blocks"].append(
            {"id": "logo", "kind": "image_ref", "content": "manifest_logo"},
        )
        spec["image_refs"] = ["manifest_logo"]
        _write_json(spec_path, spec)
        _write_json(bundle["image_manifest_spec"], {
            "images": [
                {"id": "manifest_logo", "local_path": "assets/logo.svg",
                 "source": "synthetic"},
            ],
        })
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_image_ref_smuggled)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "id 'logo' is not declared by layout 'key_message'")
        )
        results.append(_scenario(
            "block-structure: image_ref smuggled onto a layout without an image "
            "slot flagged as ERROR (payload smuggling)",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G14. Table block smuggled onto a non-comparison_table layout. Only
    # comparison_table consumes a `table` block; an agent who attached a
    # table to a key_message slide would see nothing rendered.
    def mut_table_smuggled(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        spec = json.loads(spec_path.read_text())
        spec["blocks"].append(
            {"id": "details", "kind": "table",
             "content": {"headers": ["A"], "rows": [["x"]]}},
        )
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_table_smuggled)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "id 'details' is not declared by layout 'key_message'")
        )
        results.append(_scenario(
            "block-structure: table block smuggled onto a non-comparison_table "
            "layout flagged as ERROR (payload smuggling)",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G15. Kind drift on an optional slot. cover.subtitle is an optional
    # text slot; if the agent supplies kind='list' there, the schema's
    # _slide_plan_against_layout check (required-only) silently passes,
    # but the generator's _text_block_content would refuse it.
    def mut_optional_kind_drift(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["blocks"].append(
            {"id": "subtitle", "kind": "list", "content": ["one", "two"]},
        )
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_optional_kind_drift)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "kind drift vs layout 'cover' slot 'subtitle'")
        )
        results.append(_scenario(
            "block-structure: kind drift on optional cover.subtitle slot flagged "
            "as ERROR (closes the gap left by required-only slot coverage)",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G16. Anonymous block (no id). The generator builds blocks_by_id only
    # from id-bearing blocks; anonymous blocks are silently dropped at
    # runtime, so the authoring bundle is structurally incompatible with
    # the generator and must fail closed at the preflight as ERROR.
    def mut_anonymous_block(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["blocks"].append(
            {"kind": "text", "content": "Orphan block — no id."},
        )
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_anonymous_block)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "has no string id")
        )
        results.append(_scenario(
            "block-structure: anonymous block (no id) flagged as ERROR — generator "
            "silently drops these",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G17. Unknown slot id with a non-payload kind (text on a slot the
    # layout does not declare). The generator silently drops it — ERROR
    # (dead content; the agent's text would never reach a primitive).
    def mut_unknown_text_slot(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["blocks"].append(
            {"id": "footer", "kind": "text", "content": "Footer text."},
        )
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_unknown_text_slot)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "id 'footer' is not declared by layout 'cover'")
        )
        results.append(_scenario(
            "block-structure: unknown text slot id flagged as ERROR — generator "
            "silently drops these",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G18. Image_ref content is an empty string. Generator's cover helper
    # refuses an image_ref block whose content is not a non-empty string.
    def mut_image_ref_empty(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "01_cover.json"
        spec = json.loads(spec_path.read_text())
        spec["blocks"].append(
            {"id": "accent", "kind": "image_ref", "content": ""},
        )
        _write_json(spec_path, spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_image_ref_empty)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "kind='image_ref'")
            and _has_error(report, "non-empty string")
        )
        results.append(_scenario(
            "block-structure: image_ref block with empty content flagged as ERROR",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G19a. list-slot capacity overflow on executive_summary.key_points.
    # The render-model generator's _list_item_bounds refuses when
    # slot_h // count < LIST_ITEM_MIN_H. The executive_summary.key_points
    # slot has h=580 px; 21 items → 27 px per item → 27 < 28 → fail.
    # The gate must mirror that check at authoring time so the agent
    # does not wait for a six-stage prep run to learn the list is too
    # long for the slot.
    def mut_list_overflow(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][1]["layout"] = "executive_summary"
        plan["slides"][1]["title"] = "Long Summary"
        _write_json(bundle["plan_spec"], plan)
        new_spec = {
            "index": 2, "layout": "executive_summary", "title": "Long Summary",
            "blocks": [
                {"id": "title", "kind": "text", "content": "Long Summary"},
                {"id": "summary", "kind": "text", "content": "Synthetic narrative."},
                {"id": "key_points", "kind": "list",
                 "content": [f"item {i:02d}" for i in range(21)]},
            ],
        }
        spec_path.unlink()
        _write_json(spec_path.parent / "02_executive_summary.json", new_spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_list_overflow)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "too many items for the 'executive_summary' slot")
        )
        results.append(_scenario(
            "block-structure: list-slot capacity overflow flagged as ERROR "
            "(mirrors _list_item_bounds LIST_ITEM_MIN_H gate; closes runtime "
            "false-pass on N=21 key_points)",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G19b. List-slot capacity check uses LAYOUT_FALLBACK_BOUNDS for
    # bound-less slots: agenda.agenda_items has no bounds in the layout
    # JSON, but the generator falls back to (64, 260, 1792, 700). With
    # 26 items, 700 // 26 = 26 px < 28 → fail. The gate must catch this
    # too, since the fallback table is the generator's source of truth
    # for these slots.
    def mut_list_overflow_fallback(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][1]["layout"] = "agenda"
        plan["slides"][1]["title"] = "Agenda"
        _write_json(bundle["plan_spec"], plan)
        new_spec = {
            "index": 2, "layout": "agenda", "title": "Agenda",
            "blocks": [
                {"id": "title", "kind": "text", "content": "Agenda"},
                {"id": "agenda_items", "kind": "list",
                 "content": [f"item {i:02d}" for i in range(26)]},
            ],
        }
        spec_path.unlink()
        _write_json(spec_path.parent / "02_agenda.json", new_spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_list_overflow_fallback)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "too many items for the 'agenda' slot")
        )
        results.append(_scenario(
            "block-structure: list-slot capacity check uses generator's "
            "fallback bounds for bound-less layout slots (agenda.agenda_items)",
            ok,
            f"crash={crash}, errors={[(f.name, f.detail) for f in report.errors]}",
        ))

    # G19. comparison_table without a table block — generator refuses. The
    # existing _slide_plan_against_layout (required-slot coverage) handles
    # this; the scenario confirms the new gate does not regress that.
    def mut_table_missing(td, bundle):
        spec_path = bundle["slide_specs_dir"] / "02_key_message.json"
        plan = json.loads(bundle["plan_spec"].read_text())
        plan["slides"][1]["layout"] = "comparison_table"
        plan["slides"][1]["title"] = "Compare"
        _write_json(bundle["plan_spec"], plan)
        new_spec = {
            "index": 2, "layout": "comparison_table", "title": "Compare",
            "blocks": [
                {"id": "title", "kind": "text", "content": "Compare"},
                # no `table` block — required by the layout
            ],
        }
        spec_path.unlink()
        _write_json(spec_path.parent / "02_comparison_table.json", new_spec)
    with tempfile.TemporaryDirectory() as raw_td:
        report, crash = _run_gate_no_crash(Path(raw_td), mut_table_missing)
        ok = (
            crash is None
            and not report.ok
            and _has_error(report, "missing required slot 'table'")
        )
        results.append(_scenario(
            "block-structure: comparison_table missing required `table` block "
            "still flagged as ERROR (no regression on required-slot coverage)",
            ok,
            f"crash={crash}, errors={[f.name for f in report.errors]}",
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

    # 44. The committed examples/synthetic_authoring_trial/ bundle MUST
    # still validate cleanly under the new ERROR semantics (no anonymous
    # blocks, no undeclared slot ids, no chart_ref). This is the
    # regression gate that proves the WARN→ERROR promotion did not break
    # the canonical synthetic bundle — same shape every other gate in
    # this repo exercises (acceptance_smoke, run_explicit_pipeline).
    trial_dir = REPO_ROOT / "examples" / "synthetic_authoring_trial"
    if not trial_dir.is_dir():
        results.append(_scenario(
            "regression: synthetic_authoring_trial bundle exists",
            False,
            f"missing {trial_dir}",
        ))
    else:
        report = validate_authoring_bundle(
            source=trial_dir / "source.md",
            title="Synthetic Authoring Trial",
            audience="Internal pipeline smoke-test reviewers",
            objective=(
                "Exercise the explicit-input authoring bundle gate end-to-end "
                "on a synthetic, non-sensitive narrative."
            ),
            plan_spec=trial_dir / "plan_spec.json",
            slide_specs_dir=trial_dir / "slide_specs",
            image_manifest_spec=trial_dir / "image_manifest_spec.json",
            template_root=template_root,
            design_system_spec=trial_dir / "design_system_spec.json",
            source_id="synthetic_trial_source",
            tone="neutral-professional",
            language="en",
            approximate_slide_count=7,
        )
        # No ERROR findings; only the (optional) filename advisory is
        # allowed as a WARN — and the committed bundle uses canonical
        # filenames so even that should be silent. The trial is the
        # canonical "happy path against real committed inputs".
        ok = report.ok
        results.append(_scenario(
            "regression: synthetic_authoring_trial bundle validates cleanly "
            "under the new ERROR semantics (no anonymous blocks, no "
            "undeclared slot ids, no chart_ref)",
            ok,
            f"errors={[(f.name, f.detail) for f in report.errors]}, "
            f"warnings={[(f.name, f.detail) for f in report.warnings]}",
        ))

    # ---------------------------------------------------------------------
    # --bundle <dir> shortcut coverage. The bundle mode resolves the same
    # explicit inputs from a canonical directory layout; these scenarios
    # exercise the happy path against the committed trial, then every
    # fail-closed branch (missing required entry, malformed brief.json,
    # symlinked layout, mode conflict). They invoke main() with a built
    # argv so the dispatch + _resolve_bundle wiring is covered end-to-end.
    # ---------------------------------------------------------------------

    import contextlib  # local: only the bundle scenarios need it
    import io  # local: only the bundle scenarios need it

    def _run_main(argv: list[str]) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(argv)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 2
        return code, out.getvalue(), err.getvalue()

    # B1. Happy path: --bundle on the committed trial resolves cleanly.
    if trial_dir.is_dir() and (trial_dir / _BUNDLE_BRIEF_NAME).is_file():
        code, stdout, stderr = _run_main([
            "--bundle", str(trial_dir),
            "--template-root", str(template_root),
        ])
        ok = code == 0 and "OK: no findings" in stdout
        results.append(_scenario(
            "bundle: --bundle on committed synthetic_authoring_trial "
            "resolves canonical layout and validates cleanly",
            ok,
            f"code={code}, stdout={stdout!r}, stderr={stderr!r}",
        ))
    else:
        results.append(_scenario(
            "bundle: --bundle on committed synthetic_authoring_trial "
            "(skipped — trial dir or brief.json missing)",
            False,
            f"trial_dir={trial_dir}, "
            f"brief_exists={(trial_dir / _BUNDLE_BRIEF_NAME).is_file()}",
        ))

    def _write_minimal_bundle(td: Path, *, source_id: str = "fixture_source") -> Path:
        """Build a complete --bundle layout under ``td/bundle`` using the
        same two-slide fixture _build_bundle produces, plus brief.json
        and design_system_spec.json so --bundle mode works without any
        --theme-from-template fallback."""
        bundle = _build_bundle(td, source_id=source_id)
        bdir = td / "bundle"
        bdir.mkdir()
        # Rename/copy fixture files into the canonical layout.
        (bdir / _BUNDLE_BRIEF_NAME).write_text(json.dumps({
            "title": bundle["title"],
            "audience": bundle["audience"],
            "objective": bundle["objective"],
            "source_id": source_id,
        }, indent=2, sort_keys=True) + "\n")
        (bdir / "source.md").write_text(bundle["source"].read_text())
        (bdir / "plan_spec.json").write_text(bundle["plan_spec"].read_text())
        (bdir / "image_manifest_spec.json").write_text(
            bundle["image_manifest_spec"].read_text(),
        )
        specs_dir = bdir / "slide_specs"
        specs_dir.mkdir()
        for spec_file in bundle["slide_specs_dir"].iterdir():
            (specs_dir / spec_file.name).write_text(spec_file.read_text())
        # design_system_spec.json: complete enough to schema-validate.
        _write_json(bdir / "design_system_spec.json", {
            "palette": {"primary": "#112233", "secondary": "#445566",
                        "accent": "#778899", "background": "#FFFFFF",
                        "text": "#000000"},
            "typography": {
                "heading": {"font_family": "Inter, sans-serif", "size_pt": 24},
                "body": {"font_family": "Inter, sans-serif", "size_pt": 12},
            },
            "grid": {"width_px": 1920, "height_px": 1080, "margin_px": 80},
        })
        return bdir

    # B2. --bundle pointing at a non-existent directory fails closed.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        code, stdout, stderr = _run_main([
            "--bundle", str(td / "does_not_exist"),
            "--template-root", str(template_root),
        ])
        ok = (
            code == 2
            and "--bundle does not exist" in stderr
        )
        results.append(_scenario(
            "bundle: --bundle on a missing directory fails closed (exit 2)",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B3. --bundle pointing at a regular file (not a directory) fails closed.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        not_a_dir = td / "not_a_dir.txt"
        not_a_dir.write_text("hello")
        code, stdout, stderr = _run_main([
            "--bundle", str(not_a_dir),
            "--template-root", str(template_root),
        ])
        ok = code == 2 and "is not a directory" in stderr
        results.append(_scenario(
            "bundle: --bundle pointing at a regular file fails closed",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B4. --bundle is a symlink (refused).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        real_bundle = _write_minimal_bundle(td)
        link = td / "bundle_link"
        link.symlink_to(real_bundle, target_is_directory=True)
        code, stdout, stderr = _run_main([
            "--bundle", str(link),
            "--template-root", str(template_root),
        ])
        ok = code == 2 and "symlink" in stderr
        results.append(_scenario(
            "bundle: --bundle that is itself a symlink fails closed",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B5. --bundle missing source.md / source.txt.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        (bdir / "source.md").unlink()
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = code == 2 and "missing a source body" in stderr
        results.append(_scenario(
            "bundle: --bundle missing source.md/source.txt fails closed",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B6. --bundle declares BOTH source.md AND source.txt.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        (bdir / "source.txt").write_text("alt body\n")
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = (
            code == 2
            and "more than one source body" in stderr
        )
        results.append(_scenario(
            "bundle: --bundle with both source.md and source.txt fails closed",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B7. --bundle missing brief.json.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        (bdir / _BUNDLE_BRIEF_NAME).unlink()
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = (
            code == 2
            and "missing required entry brief.json" in stderr
        )
        results.append(_scenario(
            "bundle: --bundle missing brief.json fails closed",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B8. brief.json is malformed JSON.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        (bdir / _BUNDLE_BRIEF_NAME).write_text("{not: valid")
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = code == 2 and "malformed JSON" in stderr
        results.append(_scenario(
            "bundle: brief.json malformed JSON fails closed",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B9. brief.json missing required field (objective).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        brief = json.loads((bdir / _BUNDLE_BRIEF_NAME).read_text())
        brief.pop("objective")
        (bdir / _BUNDLE_BRIEF_NAME).write_text(
            json.dumps(brief, indent=2, sort_keys=True) + "\n",
        )
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = (
            code == 2
            and "missing required field" in stderr
            and "objective" in stderr
        )
        results.append(_scenario(
            "bundle: brief.json missing required field fails closed",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B10. brief.json contains an unknown field (typo defense).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        brief = json.loads((bdir / _BUNDLE_BRIEF_NAME).read_text())
        brief["unknown_field"] = "oops"
        (bdir / _BUNDLE_BRIEF_NAME).write_text(
            json.dumps(brief, indent=2, sort_keys=True) + "\n",
        )
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = (
            code == 2
            and "unknown field" in stderr
            and "unknown_field" in stderr
        )
        results.append(_scenario(
            "bundle: brief.json with an unknown field fails closed "
            "(typo defense)",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B11. source.md is a symlink (refused).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        real_source = bdir / "real_source.md"
        (bdir / "source.md").rename(real_source)
        (bdir / "source.md").symlink_to(real_source)
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = code == 2 and "source.md is a symlink" in stderr
        results.append(_scenario(
            "bundle: source.md that is a symlink fails closed",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B12. design_system_spec.json missing AND --theme-from-template not set.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        (bdir / _BUNDLE_DESIGN_SYSTEM_SPEC_NAME).unlink()
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = (
            code == 2
            and "design_system_spec.json" in stderr
            and "--theme-from-template was not passed" in stderr
        )
        results.append(_scenario(
            "bundle: missing design_system_spec.json without "
            "--theme-from-template fails closed",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B13. Mode conflict: bundle ships design_system_spec.json AND caller
    # passes --theme-from-template.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
            "--theme-from-template",
        ])
        ok = (
            code == 2
            and "pick exactly one design-system mode" in stderr
        )
        results.append(_scenario(
            "bundle: bundle.design_system_spec.json + "
            "--theme-from-template fails closed (mode conflict)",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B14. --bundle + an explicit --title (or any per-input flag) is
    # refused so precedence is unambiguous.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
            "--title", "Override",
        ])
        ok = (
            code == 2
            and "mutually exclusive" in stderr
            and "--title" in stderr
        )
        results.append(_scenario(
            "bundle: --bundle alongside an explicit per-input flag fails "
            "closed (no mixed mode)",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B15. --bundle with --theme-from-template AND no design_system_spec.json
    # in the bundle is a valid composition (theme-mode shortcut).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        (bdir / _BUNDLE_DESIGN_SYSTEM_SPEC_NAME).unlink()
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
            "--theme-from-template",
        ])
        ok = code == 0 and "OK: no findings" in stdout
        results.append(_scenario(
            "bundle: --bundle + --theme-from-template (no "
            "design_system_spec.json in bundle) validates cleanly",
            ok,
            f"code={code}, stdout={stdout!r}, stderr={stderr!r}",
        ))

    # B16. --bundle missing plan_spec.json fails closed.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        (bdir / "plan_spec.json").unlink()
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = (
            code == 2
            and "missing required entry plan_spec.json" in stderr
        )
        results.append(_scenario(
            "bundle: --bundle missing plan_spec.json fails closed",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B17. --bundle missing slide_specs/ directory fails closed.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        for child in (bdir / "slide_specs").iterdir():
            child.unlink()
        (bdir / "slide_specs").rmdir()
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = (
            code == 2
            and "missing required entry slide_specs/" in stderr
        )
        results.append(_scenario(
            "bundle: --bundle missing slide_specs/ fails closed",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B18. --bundle missing image_manifest_spec.json fails closed.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        (bdir / "image_manifest_spec.json").unlink()
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = (
            code == 2
            and "missing required entry image_manifest_spec.json" in stderr
        )
        results.append(_scenario(
            "bundle: --bundle missing image_manifest_spec.json fails closed",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B19. --bundle uses a URI-shaped path (refused before any read).
    code, stdout, stderr = _run_main([
        "--bundle", "https://example.com/bundle",
        "--template-root", str(template_root),
    ])
    ok = code == 2 and "looks like a URI" in stderr
    results.append(_scenario(
        "bundle: --bundle that looks like a URI fails closed",
        ok,
        f"code={code}, stderr={stderr!r}",
    ))

    # B20. --bundle propagates the brief's source_id (regression: the
    # canonical trial uses source.md but source_id='synthetic_trial_source',
    # so a bundle that forgot to write source_id into brief.json would
    # otherwise silently derive 'source' from the source.md stem).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td, source_id="custom_source_id")
        # Mutate plan_spec.slides[*].source_refs to depend on the bundle's
        # source_id propagating. If brief.source_id were ignored and the
        # gate fell back to the file stem ('source'), the source_refs
        # subset check would fire.
        plan = json.loads((bdir / "plan_spec.json").read_text())
        for s in plan["slides"]:
            s["source_refs"] = ["custom_source_id"]
        (bdir / "plan_spec.json").write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n",
        )
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = code == 0 and "OK: no findings" in stdout
        results.append(_scenario(
            "bundle: brief.source_id propagates into source_refs derivation "
            "(no silent fall-back to source.md stem)",
            ok,
            f"code={code}, stdout={stdout!r}, stderr={stderr!r}",
        ))

    # B21. --self-test does not accept --bundle (regression for the
    # self-test guard).
    code, stdout, stderr = _run_main([
        "--self-test",
        "--bundle", str(trial_dir),
    ])
    ok = code == 2 and "--self-test does not take any other argument" in stderr
    results.append(_scenario(
        "bundle: --self-test rejects --bundle alongside it",
        ok,
        f"code={code}, stderr={stderr!r}",
    ))

    # B22. brief.json source_id is a non-string (regression: the explicit
    # --source-id flag is argparse type=str, but the --bundle shortcut
    # used to accept whatever JSON type the brief carried and would only
    # crash downstream with a TypeError. A clean CLI diagnostic must fire
    # before any downstream call.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        brief = json.loads((bdir / _BUNDLE_BRIEF_NAME).read_text())
        brief["source_id"] = 7
        (bdir / _BUNDLE_BRIEF_NAME).write_text(
            json.dumps(brief, indent=2, sort_keys=True) + "\n",
        )
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = (
            code == 2
            and "source_id must be a string" in stderr
            and "int" in stderr
            and "Traceback" not in stderr
        )
        results.append(_scenario(
            "bundle: brief.json non-string source_id fails closed with "
            "clean diagnostic (no traceback)",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B23. brief.json approximate_slide_count is a non-integer (regression:
    # the explicit --approximate-slide-count flag is argparse type=int, so
    # the bundle shortcut must reject "seven" before it reaches the
    # report which expects an int).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        brief = json.loads((bdir / _BUNDLE_BRIEF_NAME).read_text())
        brief["approximate_slide_count"] = "seven"
        (bdir / _BUNDLE_BRIEF_NAME).write_text(
            json.dumps(brief, indent=2, sort_keys=True) + "\n",
        )
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = (
            code == 2
            and "approximate_slide_count must be an integer" in stderr
            and "str" in stderr
            and "Traceback" not in stderr
        )
        results.append(_scenario(
            "bundle: brief.json non-integer approximate_slide_count fails "
            "closed with clean diagnostic (no traceback)",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    # B24. brief.json approximate_slide_count = true is rejected (bool is
    # an int subclass in Python; treating it as a slide count would be a
    # surprise. Belt-and-braces alongside B23.).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bdir = _write_minimal_bundle(td)
        brief = json.loads((bdir / _BUNDLE_BRIEF_NAME).read_text())
        brief["approximate_slide_count"] = True
        (bdir / _BUNDLE_BRIEF_NAME).write_text(
            json.dumps(brief, indent=2, sort_keys=True) + "\n",
        )
        code, stdout, stderr = _run_main([
            "--bundle", str(bdir),
            "--template-root", str(template_root),
        ])
        ok = (
            code == 2
            and "approximate_slide_count must be an integer" in stderr
            and "bool" in stderr
            and "Traceback" not in stderr
        )
        results.append(_scenario(
            "bundle: brief.json approximate_slide_count = JSON true fails "
            "closed with clean diagnostic (bool rejected)",
            ok,
            f"code={code}, stderr={stderr!r}",
        ))

    return results


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
