#!/usr/bin/env python3
"""validate_scaffold.py

Stdlib-only scaffold check. Runs:
  - positive: every synthetic fixture validates against its schema
  - negative: removing a required field makes validation fail
  - image_manifest path-safety: rejects http://, https://, file://,
    absolute paths, and '..' segments
  - layout-aware slide_plan: every required layout slot is covered by
    a matching block id and kind (and dropping one is caught)
  - template / theme / layout cross-check: schemas validate, the
    template's declared layout list matches the files on disk.

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
EXAMPLE_DIR = EXAMPLES / "synthetic_20_page_business_review"
SLIDE_PLANS_DIR = EXAMPLE_DIR / "slide_plans"


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


def positive_checks() -> list[CheckResult]:
    cases: list[tuple[str, Path]] = [
        ("deck_brief.schema.json", EXAMPLE_DIR / "deck_brief.json"),
        ("deck_plan.schema.json", EXAMPLE_DIR / "deck_plan.json"),
        ("design_system.schema.json", EXAMPLE_DIR / "design_system.json"),
        ("image_manifest.schema.json", EXAMPLE_DIR / "image_manifest.json"),
    ]
    for sp in sorted(SLIDE_PLANS_DIR.glob("*.json")):
        cases.append(("slide_plan.schema.json", sp))
    out: list[CheckResult] = []
    for schema_name, fixture in cases:
        errors = _schema_validate(_load(fixture), SCHEMAS / schema_name)
        out.append(CheckResult(
            f"{fixture.relative_to(REPO_ROOT)} validates against {schema_name}",
            not errors,
            "; ".join(errors),
        ))
    return out


def negative_required_field_checks() -> list[CheckResult]:
    cases = [
        ("deck_brief.schema.json", EXAMPLE_DIR / "deck_brief.json", "title"),
        ("deck_plan.schema.json", EXAMPLE_DIR / "deck_plan.json", "template"),
        ("design_system.schema.json", EXAMPLE_DIR / "design_system.json", "palette"),
        ("slide_plan.schema.json", SLIDE_PLANS_DIR / "01_cover.json", "layout"),
        ("image_manifest.schema.json", EXAMPLE_DIR / "image_manifest.json", "images"),
    ]
    out: list[CheckResult] = []
    for schema_name, fixture, field in cases:
        artifact = _load(fixture)
        del artifact[field]
        errors = _schema_validate(artifact, SCHEMAS / schema_name)
        triggered = any(f"missing required property '{field}'" in e for e in errors)
        out.append(CheckResult(
            f"removing '{field}' from {fixture.name} must fail",
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
      - POSIX-absolute ('/...'), leading backslash ('\\...'), and
        protocol-relative ('//host/...');
      - ANY URI-like scheme prefix matching ^[A-Za-z][A-Za-z0-9+.-]*:
        — covers http, https, file, s3, ftp, data, mailto, javascript,
        and anything else of that shape. This also subsumes Windows
        drive prefixes (C:, D:\\, c:/foo, etc.) since a single letter
        followed by ':' matches the same shape;
      - any path containing a '..' segment.

    Reused for both image_manifest.local_path and template.theme_ref."""
    if not p:
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


def image_manifest_path_safety_checks() -> list[CheckResult]:
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
    manifest = _load(EXAMPLE_DIR / "image_manifest.json")
    unsafe_entries = [
        img for img in manifest["images"]
        if not local_path_is_safe(img["local_path"])
    ]
    out.append(CheckResult(
        "shipped image_manifest fixture contains only safe local_paths",
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
    for img in manifest["images"]:
        asset = workspace / img["local_path"]
        out.append(CheckResult(
            f"manifest entry '{img['id']}' resolves to {img['local_path']}",
            asset.is_file(),
            f"missing file at {asset}",
        ))
    for plan_file in sorted(SLIDE_PLANS_DIR.glob("*.json")):
        plan = _load(plan_file)
        for ref in plan.get("image_refs", []):
            out.append(CheckResult(
                f"slide_plan {plan_file.name} image_ref '{ref}' declared in manifest",
                ref in declared_ids,
                f"unknown image id '{ref}'",
            ))
    # Negative: a fabricated missing path must be flagged.
    fake = workspace / "assets" / "does_not_exist.svg"
    out.append(CheckResult(
        "fabricated missing media path is detected as missing",
        not fake.is_file(),
    ))
    # Negative: an undeclared image_ref id must be flagged.
    out.append(CheckResult(
        "fabricated undeclared image_ref is detected as unknown",
        "no_such_id_xyz" not in declared_ids,
    ))
    return out


def _load_layouts(template_dir: Path) -> dict[str, dict]:
    layouts: dict[str, dict] = {}
    for f in (template_dir / "layouts").glob("*.json"):
        layouts[f.stem] = _load(f)
    return layouts


def _slide_plan_against_layout(plan: dict, layout: dict) -> list[str]:
    blocks_by_id = {b.get("id"): b for b in plan.get("blocks", []) if b.get("id")}
    problems: list[str] = []
    for slot in layout["slots"]:
        if not slot["required"]:
            continue
        block = blocks_by_id.get(slot["id"])
        if block is None:
            problems.append(f"missing required slot '{slot['id']}'")
            continue
        if block["kind"] != slot["type"]:
            problems.append(
                f"slot '{slot['id']}' expected kind '{slot['type']}', "
                f"got '{block['kind']}'"
            )
    return problems


def layout_aware_slide_plan_checks(template_dir: Path) -> list[CheckResult]:
    layouts = _load_layouts(template_dir)
    out: list[CheckResult] = []
    plan_files = sorted(SLIDE_PLANS_DIR.glob("*.json"))
    for plan_file in plan_files:
        plan = _load(plan_file)
        layout_name = plan["layout"]
        if layout_name not in layouts:
            out.append(CheckResult(
                f"layout-aware: {plan_file.name} references unknown layout {layout_name!r}",
                False,
            ))
            continue
        problems = _slide_plan_against_layout(plan, layouts[layout_name])
        out.append(CheckResult(
            f"layout-aware: {plan_file.name} covers required slots of {layout_name}",
            not problems,
            "; ".join(problems),
        ))
    # Negative: remove a required block and confirm the check catches it.
    cover_plan = _load(SLIDE_PLANS_DIR / "01_cover.json")
    cover_plan["blocks"] = [b for b in cover_plan["blocks"] if b.get("id") != "title"]
    problems = _slide_plan_against_layout(cover_plan, layouts["cover"])
    out.append(CheckResult(
        "layout-aware: dropping cover.title from slide_plan must be detected",
        any("missing required slot 'title'" in p for p in problems),
        "" if problems else "no problems reported",
    ))
    # Negative: wrong block kind for a required slot.
    bad_kpi_plan = _load(SLIDE_PLANS_DIR / "08_kpi_dashboard.json")
    for b in bad_kpi_plan["blocks"]:
        if b.get("id") == "kpis":
            b["kind"] = "text"
    problems = _slide_plan_against_layout(bad_kpi_plan, layouts["kpi_dashboard"])
    out.append(CheckResult(
        "layout-aware: wrong kind on kpi_dashboard.kpis must be detected",
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
    sections: list[tuple[str, list[CheckResult]]] = [
        ("positive: synthetic fixtures validate", positive_checks()),
        ("negative: missing required fields must fail", negative_required_field_checks()),
        ("image_manifest path-safety", image_manifest_path_safety_checks()),
        ("image_manifest media resolution", media_resolution_checks(EXAMPLE_DIR)),
        (
            "layout-aware slide_plan coverage",
            layout_aware_slide_plan_checks(TEMPLATES / "business_review"),
        ),
        ("template / theme / layout cross-check", template_consistency_checks()),
        ("negative: template guards reject bad inputs", template_negative_checks()),
    ]
    fails = 0
    for title, results in sections:
        fails += _print(title, results)
    print()
    if fails:
        print(f"FAIL: {fails} check(s) did not pass.")
        return 1
    print("OK: all scaffold checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
