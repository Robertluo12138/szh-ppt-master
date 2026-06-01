#!/usr/bin/env python3
"""validate_strategy_layer.py
=============================

Focused, stdlib-only validator for the two NEW strategy-layer contracts:

  * ``style_profile``  (schemas/style_profile.schema.json) -- the clean-room
    brand / style intake (palette, background mode, typography scale, page
    motifs, layout archetypes, image-usage policy);
  * ``strategy_plan``  (schemas/strategy_plan.schema.json) -- one strategy
    record per slide (core_message, page_type, visual_structure,
    key_metrics, image_need).

It is the validation surface for the quality layer that sits ABOVE the
company-machine MVP: brand style profile + per-slide strategy plan +
editable visual structures, with generated images treated as auxiliary.

WHAT THIS ADDS OVER ``validate_artifacts.py``
---------------------------------------------
``validate_artifacts.py`` already covers the JSON-Schema-subset structure;
this script REUSES it (``validate_artifacts._validate``) for that and adds
only the checks the subset cannot express:

  strategy_plan semantics (cannot be written as schema keywords):
    - ``slide_count`` equals ``len(slides)``;
    - ``slide_index`` values are unique AND contiguous ``1..N``.

  clean-room content gate (BOTH contracts):
    - a recursive scan of EVERY free-form string value (style_profile.notes,
      strategy_plan.boundary / deck_title / slide_title / core_message /
      key_metrics.label / key_metrics.value, and any other string) that fails
      closed on high-risk shapes: URL / URI / scheme / protocol-relative
      values, path traversal / absolute-Unix / home (~/) / Windows-drive /
      UNC paths (matched ANYWHERE in the string, not only at start),
      credential wording (api_key / secret / token / bearer / password /
      sk-...), public-sharing wording (public upload / upload publicly /
      public URL / public link / hosted publicly / public hosting), and
      confidential / raw-source wording (confidential / raw source / source
      body). The schema patterns already exclude URI / path shapes from
      ``display_name`` / ``font_family`` and lock ``image_usage_policy`` (no
      image-first ``mode``; ``editable_structures_first`` is ``true``); this
      gate adds the free-form-string coverage the schema subset cannot
      express.

Scope is intentionally narrow: this validator does NOT re-implement JSON
Schema, does NOT cross-check a strategy_plan against a deck_plan / source,
and does NOT render or export anything. It is local-only and calls no
network.

USAGE
-----
    python3 scripts/validate_strategy_layer.py --style-profile path/to.json
    python3 scripts/validate_strategy_layer.py --strategy-plan path/to.json
    python3 scripts/validate_strategy_layer.py --self-test

Exit codes:
    0  artifact validated (or every self-test probe passed).
    1  artifact failed validation (or a self-test probe failed).
    2  invocation / file / parse error.
"""

from __future__ import annotations

import sys

# Refuse `.pyc` writes from any imported module; mirrors every sibling helper.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "schemas"
EXAMPLES_DIR = REPO_ROOT / "examples"

sys.path.insert(0, str(SCRIPTS_DIR))

# Reuse the repo's own JSON-Schema-subset checker so structural validation
# cannot drift from validate_artifacts.py / validate_scaffold.py.
from validate_artifacts import _validate  # noqa: E402

STYLE_PROFILE_SCHEMA = SCHEMAS_DIR / "style_profile.schema.json"
STRATEGY_PLAN_SCHEMA = SCHEMAS_DIR / "strategy_plan.schema.json"

# Free-form strings in these contracts are author/heading-derived, so a
# recursive content gate scans EVERY string value (schema-locked enum / hex /
# pattern fields can never match these high-risk shapes, so scanning them is
# harmless defense-in-depth). Case-insensitive; stdlib `re` only. The phrase
# patterns are compound on purpose (e.g. "public upload", never bare "public")
# so legitimate wording such as "public network" is not flagged.
_HIGH_RISK_PATTERNS: list[tuple[Any, str]] = [
    # URL / URI / scheme-shaped
    (re.compile(r"://"), "URL/URI scheme"),
    (re.compile(r"\bfile:", re.I), "file: URI scheme"),
    (re.compile(r"\bdata:", re.I), "data: URI scheme"),
    (re.compile(r"//[A-Za-z0-9._~-]"), "protocol-relative URL"),
    # Path forms matched ANYWHERE in the string (not only at start / after a
    # space) so embedded high-risk paths fail closed: `cfg=/etc/passwd`,
    # `(/var/secret)`, `key=C:\\win`, `\\\\host\\share`, `~/.ssh/id_rsa`,
    # `see//cdn...`. The alnum lookbehind keeps ordinary prose benign -- in
    # `revenue/cost`, `24/7`, `TCP/IP`, `P/E`, `profile:` the `/` or `:`
    # follows a word char, so those do NOT trip.
    (re.compile(r"\.\.[\\/]"), "path traversal"),
    (re.compile(r"(?<![A-Za-z0-9])/[A-Za-z0-9._~-]"), "absolute Unix path"),
    (re.compile(r"(?<![A-Za-z0-9])~/"), "home-relative path"),
    (re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"), "Windows drive path"),
    (re.compile(r"\\\\[A-Za-z0-9._-]"), "Windows UNC path"),
    # credential-shaped wording
    (re.compile(r"api[\s_-]?key", re.I), "credential wording (api_key)"),
    (re.compile(r"secret", re.I), "credential wording (secret)"),
    (re.compile(r"token", re.I), "credential wording (token)"),
    (re.compile(r"bearer", re.I), "credential wording (bearer)"),
    (re.compile(r"password", re.I), "credential wording (password)"),
    (re.compile(r"\bsk-[A-Za-z0-9]", re.I), "credential wording (sk- API key)"),
    # public-sharing wording (compound phrases only)
    (re.compile(r"public\s+upload", re.I), "public-sharing wording"),
    (re.compile(r"upload\s+publicly", re.I), "public-sharing wording"),
    (re.compile(r"public\s+url", re.I), "public-sharing wording"),
    (re.compile(r"public\s+link", re.I), "public-sharing wording"),
    (re.compile(r"hosted\s+publicly", re.I), "public-sharing wording"),
    (re.compile(r"public\s+hosting", re.I), "public-sharing wording"),
    # confidential / raw-source wording
    (re.compile(r"confidential", re.I), "confidential wording"),
    (re.compile(r"raw\s+source", re.I), "raw-source wording"),
    (re.compile(r"source\s+body", re.I), "raw-source wording"),
]


def _schema_errors(obj: Any, schema_path: Path) -> list[str]:
    """Structural errors from the shared subset validator, or a single
    read/parse error if the schema file cannot be loaded."""
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read schema {schema_path}: {type(exc).__name__}: {exc}"]
    errors: list[str] = []
    _validate(obj, schema, "<root>", errors)
    return errors


def _scan_string(label: str, value: str, errors: list[str]) -> None:
    """Append one error if a string carries any high-risk shape."""
    for pattern, reason in _HIGH_RISK_PATTERNS:
        if pattern.search(value):
            errors.append(
                f"{label} carries high-risk content ({reason}); refused "
                f"(clean-room, local-only)"
            )
            return  # one finding per string is enough to fail closed


def _scan_high_risk_strings(node: Any, path: str, errors: list[str]) -> None:
    """Recursively scan every string value in ``node`` (walking dicts and
    lists) against the high-risk content gate."""
    if isinstance(node, str):
        _scan_string(path, node, errors)
    elif isinstance(node, dict):
        for key, value in node.items():
            _scan_high_risk_strings(value, f"{path}.{key}", errors)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _scan_high_risk_strings(value, f"{path}[{i}]", errors)


def validate_style_profile_obj(obj: Any) -> list[str]:
    """Validate a style_profile: schema subset plus the recursive high-risk
    content gate over every free-form string."""
    errors = _schema_errors(obj, STYLE_PROFILE_SCHEMA)
    _scan_high_risk_strings(obj, "style_profile", errors)
    return errors


def validate_strategy_plan_obj(obj: Any) -> list[str]:
    """Validate a strategy_plan: schema subset, the recursive high-risk
    content gate over every free-form string, plus the semantic cross-checks
    the subset cannot express (``slide_count == len(slides)`` and
    ``slide_index`` unique AND contiguous ``1..N``)."""
    errors = _schema_errors(obj, STRATEGY_PLAN_SCHEMA)
    _scan_high_risk_strings(obj, "strategy_plan", errors)
    if not isinstance(obj, dict):
        return errors
    slides = obj.get("slides")
    if not (isinstance(slides, list) and slides and all(isinstance(s, dict) for s in slides)):
        # Shape is already wrong; the schema errors above are the real signal.
        return errors
    n = len(slides)
    declared = obj.get("slide_count")
    if isinstance(declared, int) and not isinstance(declared, bool) and declared != n:
        errors.append(f"slide_count {declared} != len(slides) {n}")
    indices = [s.get("slide_index") for s in slides]
    if all(isinstance(i, int) and not isinstance(i, bool) for i in indices):
        if sorted(indices) != list(range(1, n + 1)):
            errors.append(
                f"slide_index values {sorted(indices)} are not unique and "
                f"contiguous 1..{n}"
            )
    return errors


_KIND_VALIDATORS = {
    "style_profile": validate_style_profile_obj,
    "strategy_plan": validate_strategy_plan_obj,
}


def _validate_file(path: Path, kind: str) -> list[str]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read {path}: {type(exc).__name__}: {exc}"]
    return _KIND_VALIDATORS[kind](obj)


# ---------------------------------------------------------------------------
# Self-test. Positive: the two shipped example templates validate clean.
# Negative: each contract invariant the schema-subset + semantics enforce is
# proven to fail closed. Hermetic -- no temp files, no network.
# ---------------------------------------------------------------------------


def _run_self_tests() -> int:
    print("=== validate_strategy_layer --self-test ===")
    results: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    # Load the shipped examples as the positive fixtures + mutation bases.
    try:
        style = json.loads((EXAMPLES_DIR / "style_profile_template.json").read_text("utf-8"))
        plan = json.loads((EXAMPLES_DIR / "strategy_plan_template.json").read_text("utf-8"))
    except (OSError, ValueError) as exc:  # pragma: no cover - defensive
        print(f"  [FAIL] could not load shipped examples: {exc}")
        return 1

    # Positive: shipped templates validate clean.
    e = validate_style_profile_obj(style)
    record("style_profile_example_valid", e == [], "; ".join(e))
    e = validate_strategy_plan_obj(plan)
    record("strategy_plan_example_valid", e == [], "; ".join(e))

    # strategy_plan negatives -------------------------------------------------
    m = copy.deepcopy(plan)
    m["slides"][1]["slide_index"] = m["slides"][0]["slide_index"]
    record("dup_slide_index_refused", validate_strategy_plan_obj(m) != [])

    m = copy.deepcopy(plan)
    m["slide_count"] = len(m["slides"]) + 1
    record("slide_count_mismatch_refused", validate_strategy_plan_obj(m) != [])

    m = copy.deepcopy(plan)
    m["slides"][-1]["slide_index"] = len(m["slides"]) + 1  # -> 1,2,3,4,6
    record("noncontiguous_index_refused", validate_strategy_plan_obj(m) != [])

    m = copy.deepcopy(plan)
    m["slides"][0]["visual_structure"] = "bogus_archetype"
    record("bad_visual_structure_refused", validate_strategy_plan_obj(m) != [])

    # The image_need enum deliberately has no 'required' value: a generated
    # image must never be mandatory at the contract layer.
    m = copy.deepcopy(plan)
    m["slides"][0]["image_need"] = "required"
    record("image_need_required_refused", validate_strategy_plan_obj(m) != [])

    # style_profile negatives -------------------------------------------------
    m = copy.deepcopy(style)
    del m["image_usage_policy"]
    record("missing_image_policy_refused", validate_style_profile_obj(m) != [])

    # editable_structures_first is locked true.
    m = copy.deepcopy(style)
    m["image_usage_policy"]["editable_structures_first"] = False
    record("editable_first_false_refused", validate_style_profile_obj(m) != [])

    # The mode enum has no image-first option.
    m = copy.deepcopy(style)
    m["image_usage_policy"]["mode"] = "image_first"
    record("image_first_mode_refused", validate_style_profile_obj(m) != [])

    # Recursive high-risk content gate -- every free-form string is scanned.
    m = copy.deepcopy(style)
    m["notes"] = "see file:local/asset for the source"
    record("uri_in_notes_refused", validate_style_profile_obj(m) != [])

    # --- The seven exact Codex review cases that must now fail closed. ---
    # 1: style_profile.notes credential (api_key + sk- API key)
    m = copy.deepcopy(style)
    m["notes"] = "api_key = sk-test-1234567890abcdef"
    record("cred_apikey_in_notes_refused", validate_style_profile_obj(m) != [])

    # 2: style_profile.notes public-sharing wording
    m = copy.deepcopy(style)
    m["notes"] = "public upload to hosted bucket"
    record("public_share_in_notes_refused", validate_style_profile_obj(m) != [])

    # 3: style_profile.notes confidential / raw-source wording
    m = copy.deepcopy(style)
    m["notes"] = "confidential raw source marker"
    record("confidential_in_notes_refused", validate_style_profile_obj(m) != [])

    # 4: strategy_plan slides[0].core_message credential
    m = copy.deepcopy(plan)
    m["slides"][0]["core_message"] = "api_key = sk-test-1234567890abcdef"
    record("cred_apikey_in_core_message_refused", validate_strategy_plan_obj(m) != [])

    # 5: strategy_plan slides[0].core_message public-sharing wording
    m = copy.deepcopy(plan)
    m["slides"][0]["core_message"] = "public upload to hosted bucket"
    record("public_share_in_core_message_refused", validate_strategy_plan_obj(m) != [])

    # 6: strategy_plan key_metrics.value URL
    m = copy.deepcopy(plan)
    m["slides"][1]["key_metrics"][0]["value"] = "https://public.example.com"
    record("url_in_key_metric_value_refused", validate_strategy_plan_obj(m) != [])

    # 7: strategy_plan key_metrics.label confidential / raw-source wording
    m = copy.deepcopy(plan)
    m["slides"][1]["key_metrics"][0]["label"] = "confidential raw source"
    record("confidential_in_key_metric_label_refused", validate_strategy_plan_obj(m) != [])

    # Field coverage: the gate also applies to boundary / deck_title / slide_title.
    m = copy.deepcopy(plan)
    m["boundary"] = "see https://example.com for the deck source"
    record("url_in_boundary_refused", validate_strategy_plan_obj(m) != [])

    m = copy.deepcopy(plan)
    m["deck_title"] = "/etc/passwd"
    record("abs_path_in_deck_title_refused", validate_strategy_plan_obj(m) != [])

    m = copy.deepcopy(plan)
    m["slides"][0]["slide_title"] = "../templates/private"
    record("traversal_in_slide_title_refused", validate_strategy_plan_obj(m) != [])

    # Benign guard: near-miss tokens that must NOT over-block -- 'public
    # network' (not a public-sharing phrase), 'Data-driven' (no data: scheme),
    # and 'task-force' (no sk- API-key boundary) all pass clean.
    m = copy.deepcopy(style)
    m["notes"] = "Data-driven review of the task-force roadmap across the public network"
    record("benign_near_miss_passes", validate_style_profile_obj(m) == [])

    # Position-independent path/URL coverage: high-risk forms EMBEDDED
    # mid-string (after '=', '(', etc.) must fail closed, not only when they
    # start the value or follow a space.
    m = copy.deepcopy(plan)
    m["slides"][0]["core_message"] = "load config at path=/etc/passwd now"
    record("embedded_abs_path_refused", validate_strategy_plan_obj(m) != [])

    m = copy.deepcopy(style)
    m["notes"] = "open config=C:\\Windows\\system32 then continue"
    record("embedded_drive_path_refused", validate_style_profile_obj(m) != [])

    m = copy.deepcopy(style)
    m["notes"] = "copy from \\\\fileserver\\share\\data"
    record("unc_path_refused", validate_style_profile_obj(m) != [])

    m = copy.deepcopy(style)
    m["notes"] = "key lives at ~/.ssh/id_rsa locally"
    record("home_path_refused", validate_style_profile_obj(m) != [])

    m = copy.deepcopy(style)
    m["notes"] = "fetch see//cdn.example.net/asset"
    record("embedded_protocol_relative_refused", validate_style_profile_obj(m) != [])

    # Benign path-like prose must still PASS: word/word, ratios, protocol
    # acronyms, and a trailing-colon word are not paths.
    m = copy.deepcopy(style)
    m["notes"] = "P/E ratio 24/7, revenue/cost split, TCP/IP, Re: the profile summary"
    record("benign_path_like_prose_passes", validate_style_profile_obj(m) == [])

    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        tag = "PASS" if ok else "FAIL"
        suffix = f" -- {detail}" if detail and not ok else ""
        print(f"  [{tag}] {name}{suffix}")
    print(f"\n{passed}/{len(results)} probe(s) passed.")
    return 0 if passed == len(results) else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Focused validator for the strategy-layer contracts: a "
            "style_profile (clean-room brand/style intake) and a "
            "strategy_plan (one strategy record per slide). Reuses "
            "validate_artifacts.py for JSON-Schema-subset structure and adds "
            "only the checks the subset cannot express (strategy_plan "
            "slide_count == len(slides) and unique+contiguous slide_index) "
            "plus a recursive high-risk content gate over every free-form "
            "string in BOTH contracts (URL / URI / path / credential / "
            "public-sharing / confidential wording fails closed). Local-only; "
            "no network."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--style-profile", metavar="PATH",
        help="Validate a style_profile.json against schemas/style_profile.schema.json plus the recursive high-risk content gate over every free-form string.",
    )
    mode.add_argument(
        "--strategy-plan", metavar="PATH",
        help="Validate a strategy_plan.json against schemas/strategy_plan.schema.json plus the slide_count / slide_index semantics and the recursive high-risk content gate.",
    )
    mode.add_argument(
        "--self-test", action="store_true",
        help="Run hermetic probes: the two shipped example templates validate, every contract invariant (duplicate / non-contiguous slide_index, slide_count mismatch, off-enum visual_structure, image_need 'required', missing image policy, editable_structures_first false, image-first mode) fails closed, the recursive content gate refuses the seven Codex high-risk cases (credential / public-sharing / confidential / URL wording across style_profile.notes and strategy_plan core_message / key_metrics / boundary / deck_title / slide_title), embedded path/URL forms (absolute / drive / UNC / home-relative / protocol-relative, anywhere in the string) fail closed, and benign near-miss / path-like prose still passes.",
    )
    return parser


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)

    if args.self_test:
        return _run_self_tests()

    if args.style_profile is not None:
        path, kind = Path(args.style_profile), "style_profile"
    else:
        path, kind = Path(args.strategy_plan), "strategy_plan"

    if not path.is_file():
        print(f"error: {kind} artifact not found: {path}", file=sys.stderr)
        return 2

    errors = _validate_file(path, kind)
    if errors:
        print(f"FAIL: {path} ({kind})")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: {path} validates as {kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
