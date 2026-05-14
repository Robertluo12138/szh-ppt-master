#!/usr/bin/env python3
"""validate_scaffold.py

Stdlib-only scaffold check. Runs:
  - positive: every synthetic fixture under every example workspace
    in examples/ validates against its schema (including any
    render_models/*.json the workspace ships, against
    render_model.schema.json)
  - negative: removing a required field makes validation fail
  - image_manifest path-safety: rejects ANY URI-like scheme prefix
    (http, https, file, s3, ftp, data, mailto, javascript, ...),
    POSIX-absolute paths, leading backslash, protocol-relative
    '//host/...', Windows drive prefixes, '..' segments, and empty
    strings — same rule as scripts/validate_workspace.py
  - layout-aware slide_plan: every required layout slot is covered by
    a matching block id and kind (and dropping one is caught)
  - template / theme / layout cross-check: schemas validate, the
    template's declared layout list matches the files on disk; the
    theme load is gated in two stages and is fail-closed.
  - render_model schema-level negatives: a clean baseline render_model
    validates, and every mutation in the required categories
    (unsupported kind, missing bounds, invalid token refs, external
    URL / file:// / absolute path / path traversal in image_ref,
    arbitrary SVG-like fields like transform / viewBox / href /
    foreignObject / xmlns / defs) is rejected by the schema.
  - svg_preview validation: if a workspace ships render_models, each
    render_model must have a matching svg_previews/<stem>.svg, the SVG
    must parse, the root <svg> viewBox must match the render_model
    canvas, no <foreignObject> may appear, every href / xlink:href /
    src must pass the same path-safety rule (no URI scheme, no
    absolute, no '..'), every <image> href must name an image_manifest
    local_path, and every element with explicit numeric geometry must
    stay inside the canvas. Tempfixture negatives in
    validate_workspace.py prove fail-closed on each forbidden mutation.

Example workspaces are discovered dynamically: any subdirectory of
examples/ that contains deck_plan.json and slide_plans/ is treated as
a workspace. No example name (and no fixed slide count) is hardcoded.
The shipped fixtures span a range of deck lengths to demonstrate that
the pipeline does not assume one universal deck shape.

Exit 0 if every check (including negatives) behaved as expected.
Exit 1 otherwise. Scope is intentionally narrow: SVG, PPTX, charts,
D-One, and Qoder are not exercised here because they are not built.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validate_artifacts import _validate  # noqa: E402

SCHEMAS = REPO_ROOT / "schemas"
EXAMPLES = REPO_ROOT / "examples"
TEMPLATES = REPO_ROOT / "templates" / "layouts"
DEFAULT_TEMPLATE = TEMPLATES / "business_review"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _schema_validate(artifact: dict, schema_path: Path) -> list[str]:
    errors: list[str] = []
    _validate(artifact, _load(schema_path), "<root>", errors)
    return errors


def discover_workspaces() -> list[Path]:
    """Return every example workspace under examples/ that has the
    expected pipeline artifacts on disk. The runner uses this list to
    iterate positive / per-workspace checks — no example name (and no
    fixed slide count) is hardcoded."""
    out: list[Path] = []
    if not EXAMPLES.is_dir():
        return out
    for example_dir in sorted(p for p in EXAMPLES.iterdir() if p.is_dir()):
        if (example_dir / "deck_plan.json").is_file() and (example_dir / "slide_plans").is_dir():
            out.append(example_dir)
    return out


def positive_checks(workspace: Path) -> list[CheckResult]:
    plans_dir = workspace / "slide_plans"
    cases: list[tuple[str, Path]] = [
        ("deck_brief.schema.json",     workspace / "deck_brief.json"),
        ("deck_plan.schema.json",      workspace / "deck_plan.json"),
        ("design_system.schema.json",  workspace / "design_system.json"),
        ("image_manifest.schema.json", workspace / "image_manifest.json"),
    ]
    for sp in sorted(plans_dir.glob("*.json")):
        cases.append(("slide_plan.schema.json", sp))
    rm_dir = workspace / "render_models"
    if rm_dir.is_dir():
        for rm in sorted(rm_dir.glob("*.json")):
            cases.append(("render_model.schema.json", rm))
    out: list[CheckResult] = []
    for schema_name, fixture in cases:
        errors = _schema_validate(_load(fixture), SCHEMAS / schema_name)
        out.append(CheckResult(
            f"{fixture.relative_to(REPO_ROOT)} validates against {schema_name}",
            not errors,
            "; ".join(errors),
        ))
    return out


def negative_required_field_checks(workspace: Path) -> list[CheckResult]:
    plans_dir = workspace / "slide_plans"
    plan_files = sorted(plans_dir.glob("*.json"))
    sample_plan = plan_files[0] if plan_files else None
    cases: list[tuple[str, Path, str]] = [
        ("deck_brief.schema.json",     workspace / "deck_brief.json",     "title"),
        ("deck_plan.schema.json",      workspace / "deck_plan.json",      "template"),
        ("design_system.schema.json",  workspace / "design_system.json",  "palette"),
        ("image_manifest.schema.json", workspace / "image_manifest.json", "images"),
    ]
    if sample_plan is not None:
        cases.append(("slide_plan.schema.json", sample_plan, "layout"))
    out: list[CheckResult] = []
    for schema_name, fixture, field in cases:
        artifact = _load(fixture)
        del artifact[field]
        errors = _schema_validate(artifact, SCHEMAS / schema_name)
        triggered = any(f"missing required property '{field}'" in e for e in errors)
        out.append(CheckResult(
            f"removing '{field}' from {fixture.relative_to(REPO_ROOT)} must fail",
            triggered,
            "" if triggered else "validation unexpectedly passed",
        ))
    return out


UNSAFE_IMAGE_PATHS = [
    "http://example.com/img.png",
    "https://example.com/img.png",
    "HTTPS://example.com/img.png",
    "file:///etc/passwd",
    "s3://bucket/img.png",
    "ftp://host/img.png",
    "data:image/svg+xml;base64,abc",
    "mailto:test@example.com",
    "javascript:alert(1)",
    "/etc/passwd",
    "//example.com/img.png",
    "\\windows\\system32\\img.png",
    "C:\\Windows\\system32\\img.png",
    "D:/assets/img.png",
    "c:/assets/img.png",
    "../escape/img.png",
    "assets/../../escape/img.png",
    "",
    # Whitespace-prefixed / suffixed / wrapped variants. The anchored
    # ^[A-Za-z][A-Za-z0-9+.-]*: URI-scheme regex misses these because
    # the first byte is whitespace, not a letter — and downstream
    # consumers (browser URL parsers, OS path normalizers) strip
    # surrounding whitespace before resolving the value, so a leading
    # space + 'https://attacker/x' would otherwise sneak past the
    # gate and trigger a remote fetch.
    " https://example.com/img.png",
    "\thttps://example.com/img.png",
    "\nhttps://example.com/img.png",
    "\rhttps://example.com/img.png",
    " //example.com/img.png",
    "\t//example.com/img.png",
    " /etc/passwd",
    "\t/etc/passwd",
    " \\windows\\system32\\img.png",
    "assets/cover.svg ",
    "assets/cover.svg\t",
    "assets/cover.svg\n",
    " assets/cover.svg",
    " assets/cover.svg ",
    "   ",
    "\t\t",
]
SAFE_IMAGE_PATHS = [
    "assets/cover_accent.svg",
    "assets/icons/section_risks.svg",
    "renders/slide_01.svg",
]


# RFC 3986 scheme: ALPHA *( ALPHA / DIGIT / "+" / "-" / "." ) ":"
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def local_path_is_safe(p: str) -> bool:
    """Workspace-relative path. Rejects (fail-closed):

      - empty strings;
      - ANY surrounding whitespace (leading or trailing space, tab,
        newline, carriage-return, Unicode NBSP, ...) — downstream
        consumers strip leading/trailing whitespace before resolving
        the value: browser URL parsers do this per the HTML5 / WHATWG
        URL spec, ``str.strip()``-style OS path utilities behave
        similarly. Without this gate a value like
        ``" https://attacker/x"`` (leading space) would slip past the
        URI-scheme regex below (which is anchored at the start of the
        string and expects ``[A-Za-z]``, not whitespace) and still
        get fetched / resolved by whoever consumes the path next;
      - POSIX-absolute ('/...'), leading backslash ('\\...'), and
        protocol-relative ('//host/...');
      - ANY URI-like scheme prefix matching ^[A-Za-z][A-Za-z0-9+.-]*:
        — covers http, https, file, s3, ftp, data, mailto, javascript,
        and anything else of that shape. This also subsumes Windows
        drive prefixes (C:, D:\\, c:/foo, etc.) since a single letter
        followed by ':' matches the same shape;
      - any path containing a '..' segment.

    Reused for image_manifest.local_path, template.theme_ref, every
    init_*.py spec input, the SVG-preview generator's image_ref gate,
    the workspace validator's reference-attribute walker, the visual
    quality HTML contact-sheet sanitizer, and the PPTX exporter's
    media-resolution gate. A single tightening of this helper closes
    the corresponding gap in every consumer."""
    if not p:
        return False
    # Whitespace gate runs BEFORE the rest of the checks so a leading
    # space / tab / newline cannot push the dangerous bytes outside
    # the anchored URI-scheme / leading-slash / leading-backslash
    # checks below. Trailing whitespace is refused too — both forms
    # would be stripped by downstream consumers, and the resulting
    # post-strip value would either be one of the cases below (and
    # then refused via a different code path) or would be a legitimate
    # relative path that we'd rather see authored cleanly without
    # surrounding whitespace.
    if p != p.strip():
        return False
    if p.startswith("/") or p.startswith("\\"):
        return False
    if _URI_SCHEME_PREFIX.match(p):
        return False
    segments = p.replace("\\", "/").split("/")
    if any(seg == ".." for seg in segments):
        return False
    return True


def _resolves_within(base: Path, ref: str) -> bool:
    """ref, joined onto base, must resolve to a path under base."""
    base_resolved = base.resolve()
    candidate = (base / ref).resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError:
        return False
    return True


def _template_name_matches_dir(template: dict, template_dir: Path) -> bool:
    return template.get("name") == template_dir.name


def _theme_load_results(template_dir: Path, template: dict) -> list[CheckResult]:
    """Validate template.theme_ref and, only if every guard passes, load
    and schema-validate the theme. Fail-closed in two stages:

      stage 1: local_path_is_safe (string-only, no filesystem).
               If this fails we return immediately — no Path.resolve(),
               no stat, no read against the unsafe target.
      stage 2: _resolves_within (uses Path.resolve to catch symlink
               escape from a string-safe ref). Only reached if stage 1
               passed."""
    theme_ref = template["theme_ref"]
    ref_safe = local_path_is_safe(theme_ref)
    out: list[CheckResult] = [
        CheckResult(
            f"theme_ref is path-safe: {template_dir.name}/{theme_ref}",
            ref_safe,
        ),
    ]
    if not ref_safe:
        out.append(CheckResult(
            f"theme file NOT opened (fail-closed) for unsafe theme_ref: "
            f"{template_dir.name}/{theme_ref}",
            True,
        ))
        return out

    ref_within = _resolves_within(template_dir, theme_ref)
    out.append(CheckResult(
        f"theme_ref does not escape template dir: {template_dir.name}/{theme_ref}",
        ref_within,
    ))
    if not ref_within:
        out.append(CheckResult(
            f"theme file NOT opened (fail-closed) after within-dir failure: "
            f"{template_dir.name}/{theme_ref}",
            True,
        ))
        return out

    theme_path = (template_dir / theme_ref).resolve()
    if not theme_path.is_file():
        out.append(CheckResult(
            f"theme file present: {template_dir.name}/{theme_ref}",
            False,
            f"missing {theme_path}",
        ))
        return out
    theme = _load(theme_path)
    errors = _schema_validate(theme, SCHEMAS / "theme.schema.json")
    out.append(CheckResult(
        f"theme valid: {template_dir.name}/{theme_ref}",
        not errors,
        "; ".join(errors),
    ))
    return out


def path_safety_checker_checks() -> list[CheckResult]:
    """Workspace-agnostic path-safety predicate tests. Runs the same
    unsafe / safe input vectors regardless of which examples exist."""
    out: list[CheckResult] = []
    for unsafe in UNSAFE_IMAGE_PATHS:
        out.append(CheckResult(
            f"path-safety rejects unsafe path {unsafe!r}",
            not local_path_is_safe(unsafe),
        ))
    for safe in SAFE_IMAGE_PATHS:
        out.append(CheckResult(
            f"path-safety accepts safe path {safe!r}",
            local_path_is_safe(safe),
        ))
    return out


def image_manifest_path_safety_checks(workspace: Path) -> list[CheckResult]:
    out: list[CheckResult] = []
    manifest = _load(workspace / "image_manifest.json")
    unsafe_entries = [
        img for img in manifest["images"]
        if not local_path_is_safe(img["local_path"])
    ]
    out.append(CheckResult(
        f"shipped image_manifest in {workspace.relative_to(REPO_ROOT)} "
        f"contains only safe local_paths "
        f"({len(manifest['images'])} image entries)",
        not unsafe_entries,
        ", ".join(img["local_path"] for img in unsafe_entries),
    ))
    return out


def media_resolution_checks(workspace: Path) -> list[CheckResult]:
    """security-policy.md item 6: every image_manifest local_path must resolve
    to a real file inside the workspace, and every slide_plan image_ref must
    resolve to an id declared in the manifest."""
    out: list[CheckResult] = []
    manifest = _load(workspace / "image_manifest.json")
    declared_ids = {img["id"] for img in manifest["images"]}
    label = workspace.relative_to(REPO_ROOT)
    for img in manifest["images"]:
        asset = workspace / img["local_path"]
        out.append(CheckResult(
            f"{label}: manifest entry '{img['id']}' resolves to {img['local_path']}",
            asset.is_file(),
            f"missing file at {asset}",
        ))
    plans_dir = workspace / "slide_plans"
    for plan_file in sorted(plans_dir.glob("*.json")):
        plan = _load(plan_file)
        for ref in plan.get("image_refs", []):
            out.append(CheckResult(
                f"{label}: slide_plan {plan_file.name} image_ref '{ref}' declared in manifest",
                ref in declared_ids,
                f"unknown image id '{ref}'",
            ))
    # Negative: a fabricated missing path must be flagged.
    fake = workspace / "assets" / "does_not_exist_synthetic_xyz.svg"
    out.append(CheckResult(
        f"{label}: fabricated missing media path is detected as missing",
        not fake.is_file(),
    ))
    # Negative: an undeclared image_ref id must be flagged.
    out.append(CheckResult(
        f"{label}: fabricated undeclared image_ref is detected as unknown",
        "no_such_id_xyz" not in declared_ids,
    ))
    return out


def _load_layouts(template_dir: Path) -> dict[str, dict]:
    layouts: dict[str, dict] = {}
    for f in (template_dir / "layouts").glob("*.json"):
        layouts[f.stem] = _load(f)
    return layouts


def _slide_plan_against_layout(plan: dict, layout: dict) -> list[str]:
    """Return human-readable problems describing where slide_plan
    blocks do not cover the layout's required slots. Defensive against
    malformed-but-loadable plan/layout JSON: a missing 'slots' key,
    non-dict slot entries, missing 'required'/'id'/'type' on a slot,
    or a non-dict block all surface as a clear problem string rather
    than tracebacking the validator."""
    plan_blocks = plan.get("blocks", []) if isinstance(plan, dict) else []
    if not isinstance(plan_blocks, list):
        plan_blocks = []
    blocks_by_id: dict[str, dict] = {}
    for b in plan_blocks:
        if isinstance(b, dict) and isinstance(b.get("id"), str):
            blocks_by_id[b["id"]] = b
    if not isinstance(layout, dict):
        return [f"layout is not an object: got {type(layout).__name__}"]
    slots = layout.get("slots")
    if not isinstance(slots, list):
        return [f"layout.slots is not a list: got {type(slots).__name__}"]
    problems: list[str] = []
    for i, slot in enumerate(slots):
        if not isinstance(slot, dict):
            problems.append(f"slots[{i}] is not an object: got {type(slot).__name__}")
            continue
        if not slot.get("required"):
            continue
        slot_id = slot.get("id")
        slot_type = slot.get("type")
        if not isinstance(slot_id, str) or not isinstance(slot_type, str):
            problems.append(f"slots[{i}] missing string 'id'/'type'")
            continue
        block = blocks_by_id.get(slot_id)
        if block is None:
            problems.append(f"missing required slot '{slot_id}'")
            continue
        if block.get("kind") != slot_type:
            problems.append(
                f"slot '{slot_id}' expected kind '{slot_type}', "
                f"got '{block.get('kind')}'"
            )
    return problems


def _find_plan_by_layout(workspaces: list[Path], layout: str) -> Path | None:
    """Return the first slide_plan in any provided workspace whose
    layout matches. None if no example uses that layout. Used by the
    negative-mutation checks so they don't depend on a specific
    fixture path."""
    for ws in workspaces:
        plans_dir = ws / "slide_plans"
        if not plans_dir.is_dir():
            continue
        for plan_file in sorted(plans_dir.glob("*.json")):
            plan = _load(plan_file)
            if plan.get("layout") == layout:
                return plan_file
    return None


def layout_aware_slide_plan_checks(template_dir: Path, workspace: Path) -> list[CheckResult]:
    layouts = _load_layouts(template_dir)
    out: list[CheckResult] = []
    plan_files = sorted((workspace / "slide_plans").glob("*.json"))
    label = workspace.relative_to(REPO_ROOT)
    for plan_file in plan_files:
        plan = _load(plan_file)
        layout_name = plan["layout"]
        if layout_name not in layouts:
            out.append(CheckResult(
                f"{label}: {plan_file.name} references unknown layout {layout_name!r}",
                False,
            ))
            continue
        problems = _slide_plan_against_layout(plan, layouts[layout_name])
        out.append(CheckResult(
            f"{label}: {plan_file.name} covers required slots of {layout_name}",
            not problems,
            "; ".join(problems),
        ))
    return out


def layout_aware_negative_mutation_checks(
    template_dir: Path, workspaces: list[Path],
) -> list[CheckResult]:
    """Negative-mutation checks against whichever example provides a
    slide_plan using the targeted layout. The mutations themselves
    are layout-specific (drop a required slot, change a required slot's
    block kind), but the source fixture is discovered, not hardcoded."""
    layouts = _load_layouts(template_dir)
    out: list[CheckResult] = []

    cover_plan_path = _find_plan_by_layout(workspaces, "cover")
    if cover_plan_path is None:
        out.append(CheckResult(
            "layout-aware negative: a 'cover' fixture is available in examples/",
            False,
            "no example slide_plan uses the 'cover' layout",
        ))
    else:
        cover_plan = _load(cover_plan_path)
        cover_plan["blocks"] = [b for b in cover_plan["blocks"] if b.get("id") != "title"]
        problems = _slide_plan_against_layout(cover_plan, layouts["cover"])
        out.append(CheckResult(
            f"layout-aware: dropping cover.title from "
            f"{cover_plan_path.relative_to(REPO_ROOT)} must be detected",
            any("missing required slot 'title'" in p for p in problems),
            "" if problems else "no problems reported",
        ))

    kpi_plan_path = _find_plan_by_layout(workspaces, "kpi_dashboard")
    if kpi_plan_path is None:
        out.append(CheckResult(
            "layout-aware negative: a 'kpi_dashboard' fixture is available in examples/",
            False,
            "no example slide_plan uses the 'kpi_dashboard' layout",
        ))
    else:
        bad_kpi_plan = _load(kpi_plan_path)
        for b in bad_kpi_plan["blocks"]:
            if b.get("id") == "kpis":
                b["kind"] = "text"
        problems = _slide_plan_against_layout(bad_kpi_plan, layouts["kpi_dashboard"])
        out.append(CheckResult(
            f"layout-aware: wrong kind on kpi_dashboard.kpis in "
            f"{kpi_plan_path.relative_to(REPO_ROOT)} must be detected",
            any("expected kind 'kpi'" in p for p in problems),
            "" if problems else "no problems reported",
        ))
    return out


def template_consistency_checks() -> list[CheckResult]:
    out: list[CheckResult] = []
    for template_dir in sorted(p for p in TEMPLATES.iterdir() if p.is_dir()):
        template_file = template_dir / "template.json"
        if not template_file.is_file():
            out.append(CheckResult(
                f"template.json present: {template_dir.name}",
                False,
                f"missing {template_file}",
            ))
            continue
        template = _load(template_file)
        errors = _schema_validate(template, SCHEMAS / "template.schema.json")
        out.append(CheckResult(
            f"template manifest valid: {template_dir.name}",
            not errors,
            "; ".join(errors),
        ))

        out.append(CheckResult(
            f"template name matches directory: {template_dir.name}",
            _template_name_matches_dir(template, template_dir),
            f"name={template.get('name')!r}, dir={template_dir.name!r}",
        ))

        out.extend(_theme_load_results(template_dir, template))

        layout_dir = template_dir / "layouts"
        declared = set(template.get("layouts", []))
        found: set[str] = set()
        for layout_file in sorted(layout_dir.glob("*.json")):
            layout = _load(layout_file)
            errors = _schema_validate(layout, SCHEMAS / "layout.schema.json")
            out.append(CheckResult(
                f"layout valid: {template_dir.name}/{layout_file.name}",
                not errors,
                "; ".join(errors),
            ))
            if layout["name"] != layout_file.stem:
                out.append(CheckResult(
                    f"layout name matches filename: {layout_file.name}",
                    False,
                    f"name={layout['name']}, file={layout_file.stem}",
                ))
            found.add(layout["name"])
        missing = sorted(declared - found)
        extra = sorted(found - declared)
        out.append(CheckResult(
            f"template layout list matches files on disk: {template_dir.name}",
            not missing and not extra,
            f"declared-but-missing={missing}, found-but-undeclared={extra}",
        ))
    return out


def template_negative_checks() -> list[CheckResult]:
    """Confirm theme_ref and template.name guards actually reject bad inputs."""
    template_dir = TEMPLATES / "business_review"
    template = _load(template_dir / "template.json")
    out: list[CheckResult] = []

    bad_theme_refs = [
        ("../theme.json",                       "parent-escape"),
        ("../../etc/theme.json",                "parent-escape multi"),
        ("/etc/theme.json",                     "POSIX-absolute"),
        ("C:\\Windows\\theme.json",             "Windows drive-absolute"),
        ("D:/themes/theme.json",                "Windows drive forward-slash"),
        ("http://example.com/theme.json",       "URL scheme http"),
        ("https://example.com/theme.json",      "URL scheme https"),
        ("file:///etc/theme.json",              "URL scheme file"),
        ("s3://bucket/theme.json",              "URI scheme s3"),
        ("ftp://host/theme.json",               "URI scheme ftp"),
        ("data:application/json;base64,abc",    "URI scheme data"),
        ("mailto:test@example.com",             "URI scheme mailto"),
        ("//example.com/theme.json",            "protocol-relative"),
    ]
    # Same two-stage shape as _theme_load_results: stage 2 (which calls
    # Path.resolve via _resolves_within) only runs when stage 1 passes.
    for ref, label in bad_theme_refs:
        if not local_path_is_safe(ref):
            out.append(CheckResult(
                f"theme_ref {ref!r} ({label}) rejected by stage 1 (path-safety)",
                True,
            ))
            continue
        if not _resolves_within(template_dir, ref):
            out.append(CheckResult(
                f"theme_ref {ref!r} ({label}) rejected by stage 2 (within-dir)",
                True,
            ))
            continue
        out.append(CheckResult(
            f"theme_ref {ref!r} ({label}) is rejected",
            False,
            "neither guard rejected it",
        ))

    bad_template = dict(template)
    bad_template["name"] = "not_business_review"
    out.append(CheckResult(
        "template.name mismatch with directory is detected",
        not _template_name_matches_dir(bad_template, template_dir),
    ))

    # Fail-closed gate demo: for EVERY bad theme_ref above (plus this
    # function's own predicate negatives), _theme_load_results must never
    # call _resolves_within (which would invoke Path.resolve on the unsafe
    # target) and never call _load (which would read the file). Spy on
    # both by name-binding recorders into this module, then run the helper
    # against each unsafe ref.
    import sys as _sys
    self_mod = _sys.modules[__name__]
    original_load = self_mod._load
    original_resolves_within = self_mod._resolves_within
    read_attempts: list[tuple[str, Path]] = []
    resolve_attempts: list[tuple[str, Path, str]] = []
    current_ref = {"value": ""}

    def recording_load(p: Path):
        read_attempts.append((current_ref["value"], p))
        return original_load(p)

    def recording_resolves_within(base: Path, ref: str) -> bool:
        resolve_attempts.append((current_ref["value"], base, ref))
        return original_resolves_within(base, ref)

    self_mod._load = recording_load
    self_mod._resolves_within = recording_resolves_within
    refused_for: list[str] = []
    leaked_validation_for: list[str] = []
    try:
        for ref, _label in bad_theme_refs:
            current_ref["value"] = ref
            unsafe_template = dict(template)
            unsafe_template["theme_ref"] = ref
            results = _theme_load_results(template_dir, unsafe_template)
            if any("NOT opened (fail-closed)" in r.name and r.ok for r in results):
                refused_for.append(ref)
            if any(r.name.startswith("theme valid:") for r in results):
                leaked_validation_for.append(ref)
    finally:
        self_mod._load = original_load
        self_mod._resolves_within = original_resolves_within

    no_resolve = len(resolve_attempts) == 0
    no_read = len(read_attempts) == 0
    all_refused = len(refused_for) == len(bad_theme_refs)
    no_validation_leak = not leaked_validation_for
    out.append(CheckResult(
        "fail-closed: no unsafe theme_ref reaches Path.resolve or a file read "
        f"(checked {len(bad_theme_refs)} refs)",
        all_refused and no_resolve and no_read and no_validation_leak,
        f"refused={refused_for}, _resolves_within={resolve_attempts}, "
        f"_load={read_attempts}, validation_leak={leaked_validation_for}",
    ))
    return out


# Baseline render_model used as the clean starting point for every
# negative mutation below. Anchored to the same 1920x1080 canvas the
# business_review template's theme.json declares, but the test does NOT
# couple to any specific template directory — the schema check is
# independent of the workspace's chosen template.
_BASELINE_RENDER_MODEL = {
    "index": 1,
    "layout": "cover",
    "canvas": {"width_px": 1920, "height_px": 1080},
    "source_refs": ["synthetic_src"],
    "primitives": [
        {
            "id": "title",
            "slot_id": "title",
            "kind": "text",
            "bounds": {"x": 160, "y": 320, "w": 1280, "h": 200},
            "style": {
                "color_token": "palette.text",
                "typography_token": "typography.heading",
            },
            "text": {"content": "Synthetic placeholder title", "role": "heading"},
        }
    ],
}


def _mutated_render_model(mutate) -> dict:
    """Return a fresh deep-copy of the baseline render_model with mutate(rm)
    applied. The baseline itself must remain unmutated so subsequent
    cases start from a clean copy."""
    import copy as _copy
    rm = _copy.deepcopy(_BASELINE_RENDER_MODEL)
    mutate(rm)
    return rm


def render_model_schema_checks() -> list[CheckResult]:
    """Workspace-agnostic schema checks against render_model.schema.json.
    Proves:
      - the baseline render_model validates;
      - every required negative mutation is rejected:
        unsupported kind, missing bounds, invalid token refs, external
        URL / file:// / absolute path / path traversal in image_ref, and
        a sample of arbitrary SVG-like fields (transform, viewBox, href,
        xmlns, defs, foreignObject, filter, xlink_href). The mutations
        cover the categories the task asks the scaffold to fail on; the
        full runtime cross-check surface (kind-payload mismatch, bounds
        outside canvas, slot mismatch, image_ref vs manifest, palette
        token resolution) is exercised by the workspace validator's
        tempfixtures."""
    out: list[CheckResult] = []

    # Sanity: baseline must validate. Catches regressions in either the
    # schema or the baseline writer.
    baseline_errors = _schema_validate(
        _BASELINE_RENDER_MODEL, SCHEMAS / "render_model.schema.json",
    )
    out.append(CheckResult(
        "baseline render_model validates against render_model.schema.json",
        not baseline_errors,
        "; ".join(baseline_errors),
    ))

    def m_kind_svg(rm):
        rm["primitives"][0]["kind"] = "svg"

    def m_kind_foreign_object(rm):
        rm["primitives"][0]["kind"] = "foreignObject"

    def m_missing_bounds(rm):
        rm["primitives"][0].pop("bounds")

    def m_bad_token_no_prefix(rm):
        rm["primitives"][0]["style"]["color_token"] = "raw_color"

    def m_bad_token_wrong_domain(rm):
        rm["primitives"][0]["style"]["color_token"] = "external.thing"

    def m_bad_typography_token(rm):
        rm["primitives"][0]["style"]["typography_token"] = "typography.unknown"

    def _swap_image(rm, ref):
        rm["primitives"][0] = {
            "id": "pic",
            "kind": "image_slot",
            "bounds": {"x": 100, "y": 100, "w": 200, "h": 200},
            "image_slot": {"image_ref": ref},
        }

    def m_image_ref_http(rm):
        _swap_image(rm, "http://example.com/x.png")

    def m_image_ref_https(rm):
        _swap_image(rm, "https://example.com/x.png")

    def m_image_ref_file(rm):
        _swap_image(rm, "file:///etc/passwd")

    def m_image_ref_data(rm):
        _swap_image(rm, "data:image/png;base64,abc")

    def m_image_ref_absolute(rm):
        _swap_image(rm, "/etc/passwd")

    def m_image_ref_traversal(rm):
        _swap_image(rm, "../escape")

    def m_image_ref_drive(rm):
        _swap_image(rm, "C:/img.png")

    def m_arbitrary_transform(rm):
        rm["primitives"][0]["transform"] = "translate(10,20)"

    def m_arbitrary_viewbox(rm):
        rm["primitives"][0]["viewBox"] = "0 0 100 100"

    def m_arbitrary_href(rm):
        rm["primitives"][0]["href"] = "http://example.com"

    def m_arbitrary_xlink_href(rm):
        rm["primitives"][0]["xlink_href"] = "http://example.com"

    def m_arbitrary_foreign_object_field(rm):
        rm["primitives"][0]["foreignObject"] = {"html": "<div/>"}

    def m_arbitrary_filter_field(rm):
        rm["primitives"][0]["filter"] = "url(#blur)"

    def m_arbitrary_xmlns(rm):
        rm["xmlns"] = "http://www.w3.org/2000/svg"

    def m_arbitrary_defs(rm):
        rm["defs"] = []

    def m_arbitrary_root_path(rm):
        rm["path"] = "M0 0 L100 100"

    def m_bad_id_pattern(rm):
        rm["primitives"][0]["id"] = "Has Capitals!"

    def m_bad_slot_id_pattern(rm):
        rm["primitives"][0]["slot_id"] = "../slot"

    def m_missing_source_refs(rm):
        rm.pop("source_refs")

    def m_empty_source_refs(rm):
        rm["source_refs"] = []

    cases = [
        ("unsupported kind 'svg'",                       m_kind_svg),
        ("unsupported kind 'foreignObject'",             m_kind_foreign_object),
        ("missing bounds on primitive",                  m_missing_bounds),
        ("color_token without 'palette.' prefix",        m_bad_token_no_prefix),
        ("color_token in wrong domain 'external.thing'", m_bad_token_wrong_domain),
        ("typography_token outside heading|body",        m_bad_typography_token),
        ("image_ref carrying an http:// URL",            m_image_ref_http),
        ("image_ref carrying an https:// URL",           m_image_ref_https),
        ("image_ref carrying a file:// URL",             m_image_ref_file),
        ("image_ref carrying a data: URI",               m_image_ref_data),
        ("image_ref carrying a POSIX-absolute path",     m_image_ref_absolute),
        ("image_ref carrying a path-traversal segment",  m_image_ref_traversal),
        ("image_ref carrying a Windows drive prefix",    m_image_ref_drive),
        ("arbitrary SVG-like field on primitive: transform",     m_arbitrary_transform),
        ("arbitrary SVG-like field on primitive: viewBox",       m_arbitrary_viewbox),
        ("arbitrary SVG-like field on primitive: href",          m_arbitrary_href),
        ("arbitrary SVG-like field on primitive: xlink_href",    m_arbitrary_xlink_href),
        ("arbitrary SVG-like field on primitive: foreignObject", m_arbitrary_foreign_object_field),
        ("arbitrary SVG-like field on primitive: filter",        m_arbitrary_filter_field),
        ("arbitrary SVG-like field at root: xmlns",              m_arbitrary_xmlns),
        ("arbitrary SVG-like field at root: defs",               m_arbitrary_defs),
        ("arbitrary SVG-like field at root: path",               m_arbitrary_root_path),
        ("primitive id violates pattern",                m_bad_id_pattern),
        ("slot_id with traversal characters",            m_bad_slot_id_pattern),
        ("missing source_refs (now required, fail-closed)", m_missing_source_refs),
        ("empty source_refs (minItems: 1)",              m_empty_source_refs),
    ]
    for label, mutate in cases:
        rm = _mutated_render_model(mutate)
        errors = _schema_validate(rm, SCHEMAS / "render_model.schema.json")
        out.append(CheckResult(
            f"render_model schema rejects: {label}",
            bool(errors),
            "no schema errors were reported",
        ))

    return out


def _print(section: str, results: list[CheckResult]) -> int:
    print(f"\n== {section} ==")
    fails = 0
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        suffix = f" — {r.detail}" if r.detail and not r.ok else ""
        print(f"  [{mark}] {r.name}{suffix}")
        if not r.ok:
            fails += 1
    return fails


def main() -> int:
    workspaces = discover_workspaces()
    if not workspaces:
        print(
            "error: no example workspaces found under examples/. "
            "Each workspace must contain deck_plan.json and slide_plans/.",
            file=sys.stderr,
        )
        return 1

    sections: list[tuple[str, list[CheckResult]]] = [
        # Workspace-agnostic predicate tests first so a regression in
        # local_path_is_safe surfaces independently of any example.
        ("path-safety predicate (workspace-agnostic)", path_safety_checker_checks()),
    ]

    # Lazy import to avoid the circular dependency: validate_workspace
    # already imports local_path_is_safe / _resolves_within /
    # _slide_plan_against_layout from this module at module load time.
    from validate_workspace import (
        check_planner_semantics,
        check_source_manifest_bridge,
        check_svg_previews,
    )

    # Per-workspace positive + per-workspace negatives. The label embeds the
    # workspace path so failures point at a specific example.
    for ws in workspaces:
        label = ws.relative_to(REPO_ROOT)
        sections.extend([
            (f"positive: synthetic fixtures validate ({label})",
             positive_checks(ws)),
            (f"negative: missing required fields must fail ({label})",
             negative_required_field_checks(ws)),
            (f"image_manifest path-safety: shipped manifest ({label})",
             image_manifest_path_safety_checks(ws)),
            (f"image_manifest media resolution ({label})",
             media_resolution_checks(ws)),
            (f"layout-aware slide_plan coverage ({label})",
             layout_aware_slide_plan_checks(DEFAULT_TEMPLATE, ws)),
            (f"planner semantics ({label})",
             check_planner_semantics(ws)),
            (f"stage-1 (intake) bridge ({label}): source_manifest.json "
             f"validates and matches on-disk input/source.md when "
             f"present; deck_brief.source_refs declares source.id; "
             f"absent manifest is a no-op so prepared examples without "
             f"intake stay valid",
             check_source_manifest_bridge(ws)),
            (f"svg_preview validation ({label})",
             check_svg_previews(ws, TEMPLATES)),
        ])

    # Layout-aware negative-mutation tests pick fixtures dynamically so we
    # don't depend on any single example's slide list.
    sections.append((
        "layout-aware negatives: mutations against discovered fixtures",
        layout_aware_negative_mutation_checks(DEFAULT_TEMPLATE, workspaces),
    ))

    # Template / theme / layout cross-checks are workspace-independent.
    sections.extend([
        ("template / theme / layout cross-check", template_consistency_checks()),
        ("negative: template guards reject bad inputs", template_negative_checks()),
        ("render_model schema: baseline + schema-level negatives "
         "(unsupported kind, missing bounds, invalid token refs, "
         "URL / file:// / absolute / path-traversal image_ref, "
         "arbitrary SVG-like fields)",
         render_model_schema_checks()),
    ])

    fails = 0
    for title, results in sections:
        fails += _print(title, results)
    print()
    if fails:
        print(f"FAIL: {fails} check(s) did not pass.")
        return 1
    print(
        f"OK: all scaffold checks passed across "
        f"{len(workspaces)} example workspace(s): "
        f"{[str(ws.relative_to(REPO_ROOT)) for ws in workspaces]}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
