#!/usr/bin/env python3
"""text_policy_decision_smoke.py

Per-request ``text_policy`` decision smoke for the mockable D-One stub
chain. Proves the in-repo invariant that every ``d_one_local`` image
request decides its OWN ``text_policy`` value (``no_text`` /
``decorative_glyphs`` / ``caption_safe``) and that those per-request
decisions survive byte-identical through ``scripts/done_image_adapter.py``
into the deterministic plan file — there is NO global default, no
silent collapse of the three policy values into a single one, and no
adapter shortcut that tags every request the same regardless of what
the spec asked for.

Clean-room: no upstream wording / tables / examples / prompts / code /
assets are copied from any external project. This smoke is aligned with
the local-only image-generation lesson that text policy is a
per-request decision, not a globally-defaulted one.

What the happy path exercises:

  * One ``image_manifest.json`` listing three ``d_one_local`` images.
  * One spec listing three matching requests whose ``text_policy``
    values are intentionally distinct (one ``no_text``, one
    ``decorative_glyphs``, one ``caption_safe``).
  * ``scripts/done_image_adapter.py`` is driven once via its Python
    API with ``--descriptor-vocabulary`` pointing at a synthetic vocab
    whose ``image_taxonomy.text_policy.allowed_values`` carries the
    canonical three-element set.
  * The produced ``d_one_adapter_plan.json`` is re-parsed and each
    request's ``text_policy`` is asserted EQUAL to the value the spec
    supplied for that ``id`` — byte-identical preservation, no policy
    drift, no silent flattening, no field dropped, no field renamed.
  * ``scripts/done_image_adapter.py --validate-plan`` (Python API) is
    re-run against the just-written plan to prove the plan re-validates
    clean at the runner boundary with the same vocab.

Fail-closed probes (each runs under its own tempdir so a failure cannot
leak state into the next probe):

  P1  flattened-to-no_text regression: a spec whose three requests all
      carry ``text_policy='no_text'`` produces a plan whose per-request
      assertion (against the BASELINE mixed expectation) MUST fire —
      proves the assertion is not vacuously green and would catch a
      refactor that started defaulting every request to ``no_text``.

  P2  unknown / out-of-vocabulary ``text_policy`` value must still be
      refused at the adapter's taxonomy gate — even when the value is
      regex-shape valid (lowercase identifier, no forbidden token) it
      must not appear on the plan.

  P3  in-image text wording under ``text_policy='no_text'`` must still
      be refused by the policy-aware prompt safety scan — the request
      asks for ``include text`` which the ``no_text`` policy forbids.

  P4  decorative glyph wording under ``text_policy='decorative_glyphs'``
      must remain ACCEPTED — the literal ``calligraphy`` is in the
      ``no_text`` deny set but the rule deliberately does not fire
      under ``decorative_glyphs`` (the policy permits stylised artwork
      text).

  P5  ``text_policy='caption_safe'`` must NOT unlock slide-text
      rasterization: a prompt asking for ``slide title`` must still be
      refused by the universal editable-text rule. ``caption_safe``
      means the image is safe to caption on the slide side; it never
      permits the slide title / body copy / data labels to be baked
      into the raster.

  P6  ``text_policy='caption_safe'`` plus a decorative artwork prompt
      that contains no universal editable-text wording and no
      ``no_text`` deny literal must remain ACCEPTED — proves
      ``caption_safe`` is a usable policy in its own right, not a
      shorthand for ``no_text``.

The smoke is stdlib-only, tempdir-only, in-process (no subprocess
shells per probe), and writes nothing inside the committed repo tree.
The committed-tree snapshot is delegated to
``scripts/core_editable_ppt_acceptance._snapshot_committed_tree`` so
the snapshot scope is the SAME broad set of top-level paths the
aggregate quality gate already protects (``.gitignore`` /
``AGENTS.md`` / ``CLAUDE.md`` / ``README.md`` / ``SECURITY.md`` /
``SKILL.md`` / ``examples`` / ``references`` / ``schemas`` /
``scripts`` / ``templates``); a leak under any of those — including
root-level committed files and the ``references`` / ``schemas`` /
``templates`` trees the earlier narrower snapshot did not cover — is
caught here too. A fail-closed preflight refuses an empty snapshot
scope or an empty ``before`` snapshot so a future refactor that
emptied the scope (or typo'd every top-level path) cannot tautologically
green this gate. MOCK / STUB only — NOT real D-One integration. The
smoke never calls D-One, MCP, Qoder, a public network, telemetry,
any model API, an image search, or any external service.

Usage:
  python3 scripts/text_policy_decision_smoke.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

import done_image_adapter as _adapter  # noqa: E402
import core_editable_ppt_acceptance as _aggregate  # noqa: E402

# The three canonical text_policy values the descriptor-vocabulary
# schema locks. The smoke deliberately uses one request per value so a
# flatten-to-one regression cannot pass undetected.
_NO_TEXT = "no_text"
_DECORATIVE_GLYPHS = "decorative_glyphs"
_CAPTION_SAFE = "caption_safe"
_TEXT_POLICY_VALUES: tuple[str, ...] = (
    _NO_TEXT,
    _DECORATIVE_GLYPHS,
    _CAPTION_SAFE,
)

# Synthetic image ids; chosen so the plan's id-sorted order is stable.
_REQ_NO_TEXT = "req_a_no_text"
_REQ_DECORATIVE = "req_b_decorative"
_REQ_CAPTION_SAFE = "req_c_caption_safe"

_BASELINE_EXPECTED: dict[str, str] = {
    _REQ_NO_TEXT: _NO_TEXT,
    _REQ_DECORATIVE: _DECORATIVE_GLYPHS,
    _REQ_CAPTION_SAFE: _CAPTION_SAFE,
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def _write_json(path: Path, body: dict) -> None:
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")


def _descriptor_vocabulary_body() -> dict:
    """Minimal schema-valid descriptor vocabulary. The only block this
    smoke really cares about is ``image_taxonomy.text_policy.allowed_values``,
    but the schema requires every dimension's canonical-set membership
    so we include the full block. The lists mirror the canonical
    allowed values the descriptor-vocabulary schema enforces."""
    return {
        "schema_version": 1,
        "note": (
            "Synthetic D-One descriptor vocabulary for the per-request "
            "text policy decision smoke."
        ),
        "kind_enum": [
            "color_token",
            "geometric_noun",
            "mood_adjective",
            "composition_adjective",
        ],
        "descriptors": [
            {"kind": "color_token", "value": "palette.primary"},
            {"kind": "geometric_noun", "value": "triangle"},
            {"kind": "mood_adjective", "value": "neutral"},
            {"kind": "composition_adjective", "value": "balanced"},
        ],
        "image_taxonomy": {
            "rendering_style": {"allowed_values": [
                "flat_vector", "line_diagram", "isometric_lite",
                "low_poly", "solid_shape",
            ]},
            "palette_family": {"allowed_values": [
                "neutral_grey", "accent_only", "dual_tone",
                "mono_brand", "palette_default",
            ]},
            "image_role": {"allowed_values": [
                "decorative_accent", "metaphor_icon", "divider_motif",
                "kpi_emblem", "cover_motif",
            ]},
            "layout_pattern": {"allowed_values": [
                "single_center", "left_anchor", "right_anchor",
                "top_band", "bottom_band",
            ]},
            "modifier": {"allowed_values": [
                "low_contrast", "soft_edges", "grid_aligned",
                "negative_space",
            ]},
            "text_policy": {"allowed_values": list(_TEXT_POLICY_VALUES)},
            "subject_domain": {"allowed_values": [
                "abstract_geometry", "process_motif",
                "metric_emblem", "concept_diagram",
            ]},
        },
    }


def _manifest_body() -> dict:
    """Three d_one_local entries — one per request id."""
    return {
        "images": [
            {
                "id": _REQ_NO_TEXT,
                "local_path": "media/req_a_no_text.png",
                "source": "d_one_local",
            },
            {
                "id": _REQ_DECORATIVE,
                "local_path": "media/req_b_decorative.png",
                "source": "d_one_local",
            },
            {
                "id": _REQ_CAPTION_SAFE,
                "local_path": "media/req_c_caption_safe.png",
                "source": "d_one_local",
            },
        ],
    }


def _baseline_spec_body() -> dict:
    """Three requests whose text_policy values are intentionally
    distinct. Prompts are deliberately benign across ALL three policies
    — none of them reference any in-image-text deny literal — so the
    flatten-to-no_text probe (P1) exercises text_policy preservation,
    not a safety-scan regression. P4 / P6 substitute their own
    policy-specific prompts."""
    return {
        "requests": [
            {
                "id": _REQ_NO_TEXT,
                "prompt": (
                    "abstract neutral pattern, soft gradient, no logo"
                ),
                "text_policy": _NO_TEXT,
            },
            {
                "id": _REQ_DECORATIVE,
                "prompt": (
                    "stylised decorative mark, balanced composition, "
                    "soft strokes"
                ),
                "text_policy": _DECORATIVE_GLYPHS,
            },
            {
                "id": _REQ_CAPTION_SAFE,
                "prompt": (
                    "soft neutral gradient, balanced composition, "
                    "no logo"
                ),
                "text_policy": _CAPTION_SAFE,
            },
        ],
    }


def _seed_workspace(td: Path, name: str) -> Path:
    ws = td / name
    ws.mkdir(parents=True)
    _write_json(ws / _adapter.IMAGE_MANIFEST_FILENAME, _manifest_body())
    return ws


def _write_vocab(td: Path) -> Path:
    vocab = td / "descriptor_vocabulary.json"
    _write_json(vocab, _descriptor_vocabulary_body())
    return vocab


def _assert_per_request_text_policy(
    plan_path: Path, expected_by_id: dict[str, str],
) -> Check:
    """Re-parse the plan and assert each request's text_policy equals
    the EXPECTED value for that id. Returns a failing Check if any
    request's policy drifted, was dropped, or was silently flattened.
    Coverage of all three canonical policies is asserted separately by
    the happy-path scenario (so per-policy probes can reuse this
    helper with a single-request expectation)."""
    try:
        plan = json.loads(plan_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return Check(
            "plan re-parses as JSON",
            False, f"{type(exc).__name__}: {exc}",
        )
    requests = plan.get("requests")
    if not isinstance(requests, list):
        return Check(
            "plan.requests is a list",
            False, f"got: type={type(requests).__name__}",
        )
    seen: dict[str, str] = {}
    for i, req in enumerate(requests):
        if not isinstance(req, dict):
            return Check(
                f"plan.requests[{i}] is an object",
                False, f"got: type={type(req).__name__}",
            )
        rid = req.get("id")
        if not isinstance(rid, str):
            return Check(
                f"plan.requests[{i}].id is a string",
                False, f"got: {rid!r}",
            )
        tp = req.get("text_policy")
        if not isinstance(tp, str):
            return Check(
                f"plan.requests[{i}] (id {rid!r}) carries text_policy",
                False, f"got: {tp!r}",
            )
        seen[rid] = tp
    if set(seen) != set(expected_by_id):
        return Check(
            "plan covers exactly the expected request ids",
            False,
            f"plan ids={sorted(seen)}, expected ids={sorted(expected_by_id)}",
        )
    mismatches = [
        (rid, seen[rid], expected_by_id[rid])
        for rid in sorted(expected_by_id)
        if seen[rid] != expected_by_id[rid]
    ]
    if mismatches:
        return Check(
            "every plan request's text_policy equals its spec text_policy",
            False,
            "mismatches (id, plan, expected): "
            + "; ".join(f"({a!r},{b!r},{c!r})" for a, b, c in mismatches),
        )
    return Check(
        "every plan request's text_policy equals its spec text_policy "
        f"({len(seen)} request(s))",
        True,
    )


def _run_adapter(
    *, ws: Path, spec_body: dict, vocab: Path, td: Path, label: str,
) -> tuple[int, str, Path]:
    spec = td / f"spec_{label}.json"
    _write_json(spec, spec_body)
    rc, msg = _adapter.done_image_adapter(
        workspace=ws, spec=spec, descriptor_vocabulary=vocab,
    )
    return rc, msg, ws / _adapter.DEFAULT_PLAN_FILENAME


def _scenario_happy_path(td: Path) -> list[Check]:
    """Baseline: three requests with distinct text_policy values land on
    the plan byte-identical, and validate_plan_file accepts the result.
    """
    checks: list[Check] = []
    ws = _seed_workspace(td, "ws_happy")
    vocab = _write_vocab(td)
    rc, msg, plan_path = _run_adapter(
        ws=ws, spec_body=_baseline_spec_body(), vocab=vocab, td=td,
        label="happy",
    )
    checks.append(Check(
        "happy: done_image_adapter writes a plan for three mixed-policy "
        "requests",
        rc == 0 and plan_path.is_file() and not plan_path.is_symlink(),
        f"rc={rc}, msg={msg!r}",
    ))
    if rc != 0:
        return checks
    checks.append(_assert_per_request_text_policy(
        plan_path, _BASELINE_EXPECTED,
    ))
    distinct = set(_BASELINE_EXPECTED.values())
    checks.append(Check(
        "happy: baseline expectation covers all three canonical "
        f"text_policy values ({sorted(_TEXT_POLICY_VALUES)})",
        distinct == set(_TEXT_POLICY_VALUES),
        f"baseline distinct policies={sorted(distinct)}",
    ))
    vrc, vmsg = _adapter.validate_plan_file(
        workspace=ws, plan=plan_path, descriptor_vocabulary=vocab,
    )
    checks.append(Check(
        "happy: validate_plan_file accepts the produced plan "
        "(round-trip; per-request text_policy survives the validator)",
        vrc == 0,
        f"rc={vrc}, msg={vmsg!r}",
    ))
    return checks


def _scenario_flattened_to_no_text(td: Path) -> list[Check]:
    """P1: a spec that flattens every text_policy to ``no_text`` MUST
    produce a plan whose per-request assertion against the BASELINE
    mixed expectation fires. Proves the assertion is not vacuously
    green; a future regression that started defaulting every request
    to ``no_text`` would be caught."""
    checks: list[Check] = []
    ws = _seed_workspace(td, "ws_flat")
    vocab = _write_vocab(td)
    flat = json.loads(json.dumps(_baseline_spec_body()))
    for req in flat["requests"]:
        req["text_policy"] = _NO_TEXT
    rc, msg, plan_path = _run_adapter(
        ws=ws, spec_body=flat, vocab=vocab, td=td, label="flat",
    )
    if rc != 0 or not plan_path.is_file():
        checks.append(Check(
            "P1: adapter accepts the flattened-to-no_text spec "
            "(prerequisite for the regression probe)",
            False, f"rc={rc}, msg={msg!r}",
        ))
        return checks
    result = _assert_per_request_text_policy(plan_path, _BASELINE_EXPECTED)
    checks.append(Check(
        "P1: per-request assertion against the mixed baseline FIRES on "
        "a flattened-to-no_text plan (proves the gate is not vacuous; "
        "a global-default regression would be caught)",
        not result.ok,
        f"assertion check returned ok={result.ok}, detail={result.detail!r}",
    ))
    return checks


def _scenario_unknown_policy(td: Path) -> list[Check]:
    """P2: text_policy outside the canonical three is refused by the
    adapter's taxonomy gate; no plan file is written."""
    ws = _seed_workspace(td, "ws_unknown")
    vocab = _write_vocab(td)
    body = json.loads(json.dumps(_baseline_spec_body()))
    body["requests"][0]["text_policy"] = "global_default_policy"
    rc, msg, plan_path = _run_adapter(
        ws=ws, spec_body=body, vocab=vocab, td=td, label="unknown",
    )
    ok = (
        rc == 1
        and "image_taxonomy.text_policy.allowed_values" in msg
        and not plan_path.exists()
    )
    return [Check(
        "P2: unknown text_policy value refused; no plan written",
        ok, f"rc={rc}, msg={msg!r}",
    )]


def _scenario_no_text_in_image_text_refused(td: Path) -> list[Check]:
    """P3: under text_policy='no_text', a prompt that asks for visible
    text must still be refused by the policy-aware in-image-text rule
    (proves the no_text policy actively gates prompt content; not a
    label that does nothing)."""
    ws = _seed_workspace(td, "ws_no_text_text")
    vocab = _write_vocab(td)
    body = json.loads(json.dumps(_baseline_spec_body()))
    body["requests"][0]["prompt"] = (
        "abstract neutral pattern, include text along the lower edge"
    )
    rc, msg, plan_path = _run_adapter(
        ws=ws, spec_body=body, vocab=vocab, td=td, label="no_text_text",
    )
    ok = (
        rc == 1
        and "no_text" in msg
        and "include text" in msg
        and not plan_path.exists()
    )
    return [Check(
        "P3: in-image-text wording refused under text_policy='no_text'; "
        "no plan written",
        ok, f"rc={rc}, msg={msg!r}",
    )]


def _scenario_decorative_glyphs_accepts_glyph(td: Path) -> list[Check]:
    """P4: decorative artwork text (e.g. ``calligraphy``) is in the
    no_text deny list but the rule deliberately does NOT fire under
    text_policy='decorative_glyphs'; the request must land on the plan
    with its per-request policy preserved."""
    ws = _seed_workspace(td, "ws_decorative_glyph")
    vocab = _write_vocab(td)
    body = json.loads(json.dumps(_baseline_spec_body()))
    # Send only the decorative request so the assertion is unambiguous.
    body["requests"] = [
        r for r in body["requests"] if r["id"] == _REQ_DECORATIVE
    ]
    body["requests"][0]["prompt"] = (
        "stylised decorative wordmark in calligraphy with soft strokes"
    )
    rc, msg, plan_path = _run_adapter(
        ws=ws, spec_body=body, vocab=vocab, td=td, label="decorative_glyph",
    )
    if rc != 0 or not plan_path.is_file():
        return [Check(
            "P4: decorative-glyphs request accepted",
            False, f"rc={rc}, msg={msg!r}",
        )]
    result = _assert_per_request_text_policy(
        plan_path, {_REQ_DECORATIVE: _DECORATIVE_GLYPHS},
    )
    return [Check(
        "P4: text_policy='decorative_glyphs' accepts a prompt carrying "
        "the no_text deny literal 'calligraphy' AND the request's own "
        "policy survives byte-identical",
        result.ok, f"detail={result.detail!r}",
    )]


def _scenario_caption_safe_refuses_slide_text(td: Path) -> list[Check]:
    """P5: text_policy='caption_safe' must NOT unlock slide-text
    rasterization. A prompt asking for ``slide title`` must still be
    refused by the universal editable-text rule (which fires for every
    text_policy)."""
    ws = _seed_workspace(td, "ws_caption_slide_title")
    vocab = _write_vocab(td)
    body = json.loads(json.dumps(_baseline_spec_body()))
    body["requests"] = [
        r for r in body["requests"] if r["id"] == _REQ_CAPTION_SAFE
    ]
    body["requests"][0]["prompt"] = (
        "soft neutral gradient with the slide title rendered in the lower "
        "third"
    )
    rc, msg, plan_path = _run_adapter(
        ws=ws, spec_body=body, vocab=vocab, td=td, label="caption_slide_title",
    )
    ok = (
        rc == 1
        and "slide title" in msg
        and "editable-text" in msg
        and not plan_path.exists()
    )
    return [Check(
        "P5: text_policy='caption_safe' does NOT permit 'slide title' to "
        "be baked into the raster; refused by the universal editable-"
        "text rule; no plan written",
        ok, f"rc={rc}, msg={msg!r}",
    )]


def _scenario_caption_safe_accepts_artwork(td: Path) -> list[Check]:
    """P6: text_policy='caption_safe' accepts a benign decorative
    artwork prompt and the request's own policy survives byte-identical
    on the plan — proves caption_safe is usable, not a shorthand for
    no_text that bypasses the byte-identical-preservation contract."""
    ws = _seed_workspace(td, "ws_caption_safe_artwork")
    vocab = _write_vocab(td)
    body = json.loads(json.dumps(_baseline_spec_body()))
    body["requests"] = [
        r for r in body["requests"] if r["id"] == _REQ_CAPTION_SAFE
    ]
    rc, msg, plan_path = _run_adapter(
        ws=ws, spec_body=body, vocab=vocab, td=td, label="caption_safe_artwork",
    )
    if rc != 0 or not plan_path.is_file():
        return [Check(
            "P6: caption_safe artwork request accepted",
            False, f"rc={rc}, msg={msg!r}",
        )]
    result = _assert_per_request_text_policy(
        plan_path, {_REQ_CAPTION_SAFE: _CAPTION_SAFE},
    )
    return [Check(
        "P6: text_policy='caption_safe' is accepted on a benign "
        "decorative artwork prompt AND the request's own policy "
        "survives byte-identical (caption_safe is a real per-request "
        "choice, not a no_text alias)",
        result.ok, f"detail={result.detail!r}",
    )]


# ---------------------------------------------------------------------------
# Repo-tree snapshot — proves the smoke writes nothing under the
# committed repo tree. Delegates to the aggregate quality gate's snapshot
# (single source of truth, identical scope) so a future hardening of the
# aggregator's snapshot automatically applies here too.
# ---------------------------------------------------------------------------


def _snapshot_tree() -> dict[str, tuple[str, bytes]]:
    return _aggregate._snapshot_committed_tree()


def _run_self_test() -> int:
    print("=== text_policy_decision_smoke (--self-test) ===")
    # Preflight: the aggregate snapshot's top-level scope MUST be
    # non-empty AND the produced ``before`` snapshot MUST be non-empty.
    # With an empty scope the snapshot loop would iterate nothing,
    # ``before`` and ``after`` would be ``{}``, and the byte-identical
    # gate below would tautologically pass — false-greening the
    # "writes nothing inside the committed repo tree" claim. Refuse
    # the run outright so a future refactor (typo, merge mistake) that
    # emptied the scope cannot silently mask a real mutation.
    snapshot_scope = _aggregate._COMMITTED_TOP_LEVEL
    if len(snapshot_scope) == 0:
        print(
            "FAIL: committed-tree snapshot scope is empty "
            "(_aggregate._COMMITTED_TOP_LEVEL is the empty tuple); "
            "the byte-identical gate would tautologically pass. "
            "Restore the top-level entries before running this smoke.",
            file=sys.stderr,
        )
        return 1
    before = _snapshot_tree()
    if not before:
        print(
            "FAIL: committed-tree 'before' snapshot is empty "
            "(no top-level entry under REPO_ROOT resolved to a file / "
            f"symlink / dir / other); scope was {list(snapshot_scope)!r}. "
            "The byte-identical gate cannot fail-closed on an empty "
            "baseline. Investigate whether REPO_ROOT is intact.",
            file=sys.stderr,
        )
        return 1
    all_checks: list[Check] = []
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        for scenario in (
            _scenario_happy_path,
            _scenario_flattened_to_no_text,
            _scenario_unknown_policy,
            _scenario_no_text_in_image_text_refused,
            _scenario_decorative_glyphs_accepts_glyph,
            _scenario_caption_safe_refuses_slide_text,
            _scenario_caption_safe_accepts_artwork,
        ):
            with tempfile.TemporaryDirectory(dir=str(td)) as raw_sub:
                sub = Path(raw_sub)
                all_checks.extend(scenario(sub))
    after = _snapshot_tree()
    snapshot_label = (
        "snapshot: committed REPO_ROOT tree byte-identical "
        f"(scope: {', '.join(snapshot_scope)})"
    )
    if before != after:
        changed = sorted(
            k for k in set(before) | set(after)
            if before.get(k) != after.get(k)
        )
        all_checks.append(Check(
            snapshot_label, False, f"changed: {changed!r}",
        ))
    else:
        all_checks.append(Check(snapshot_label, True))
    rc = 0
    for c in all_checks:
        mark = "PASS" if c.ok else "FAIL"
        print(f"  [{mark}] {c.name}")
        if not c.ok:
            if c.detail:
                print(f"    detail: {c.detail}")
            rc = 1
    print()
    if rc == 0:
        print(
            f"OK (text_policy_decision_smoke): {len(all_checks)} check(s) "
            f"passed; per-request text_policy decisions survive byte-"
            f"identical and every fail-closed probe fires as documented."
        )
    return rc


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Per-request text_policy decision smoke for the mockable "
            "D-One stub chain. Proves each d_one_local image request "
            "decides its OWN text_policy value (no_text / "
            "decorative_glyphs / caption_safe) and that the value "
            "survives byte-identical through done_image_adapter into "
            "the deterministic plan file. MOCK / STUB ONLY — no real "
            "D-One, MCP, Qoder, public network, telemetry, model API, "
            "image search, or external service is contacted."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Required: run the per-request text_policy decision smoke "
            "(no production CLI surface exists today)."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: text_policy_decision_smoke.py requires --self-test "
            "(no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
