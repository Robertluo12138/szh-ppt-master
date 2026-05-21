#!/usr/bin/env python3
"""Trace acceptance smoke for the opt-in conversion-trace sidecar.

Focused, ``$TMPDIR``-only acceptance smoke that proves the opt-in
``scripts/export_pptx.py --trace-out`` export path produces a valid
``conversion_trace`` sidecar end-to-end, AND that the default
acceptance pipeline (``scripts/run_explicit_pipeline.py`` ->
``scripts/run_pipeline.py`` -> ``scripts/export_pptx.py``, no
``--trace-out``) continues to emit NO trace sidecar anywhere in its
output tree.

This smoke is intentionally **separate** from
``scripts/acceptance_smoke.py``. The default acceptance smoke must
NOT start emitting a trace sidecar — the trace is opt-in by contract
(``references/conversion-trace-contract.md``). Plumbing
``--trace-out`` through ``run_explicit_pipeline.py`` /
``run_pipeline.py`` would mean changing the default export behavior;
this script keeps the default code path untouched and instead
re-invokes ``export_pptx.py --trace-out`` directly against the
prepared workspace produced by Stage 1-10.

What the smoke proves (every assertion runs under one
``tempfile.TemporaryDirectory()`` so no artifact lands in the repo):

  1. ``scripts/run_explicit_pipeline.py`` against the synthetic
     authoring trial (``examples/synthetic_authoring_trial/``) with
     ``--report-dir`` returns rc=0; Stage 1-10 all pass.
  2. The default pipeline writes a non-empty ``.pptx`` to the
     caller-supplied ``--output`` path.
  3. The default pipeline emits NO conversion_trace sidecar
     anywhere in the temp output tree — every ``*.json`` file under
     the temp root is parsed and any object carrying the
     ``pipeline_status`` literal from the closed two-element enum
     (``future_contract_only`` / ``runtime_emitted_by_export_pptx``)
     is reported as an offender.
  4. A second, explicit ``scripts/export_pptx.py --trace-out``
     invocation against the SAME prepared workspace returns rc=0 and
     produces both a separate ``.pptx`` and a non-empty trace JSON
     sidecar.
  5. The produced trace passes
     ``scripts/validate_conversion_trace.py --trace <path>`` (full
     schema + content gates T1-T15).
  6. The produced trace passes
     ``scripts/validate_artifacts.py --schema
     schemas/conversion_trace.schema.json`` (independent schema-
     only re-validation).
  7. The trace-positive PPTX passes
     ``scripts/validate_pptx_contract.py --pptx <path>
     --expected-slide-count N`` (container + minimal-evidence +
     slide-count gates).
  8. ``scripts/inspect_pptx_inventory.py --pptx <path> --out <inv>``
     on the trace-positive PPTX reports ``ok == True``, no findings,
     the documented ``evidence_basis`` line, and
     ``slide_count == N``.
  9. ``REPO_ROOT/examples/`` and ``REPO_ROOT/scripts/`` are
     byte-identical before and after the smoke (snapshot-diff
     proves no generated artifact landed in the committed tree).

Stdlib-only. NETWORK-FREE. NO-D-ONE. NO-Qoder. NO-MCP. NO model API.
NO image generation. NO telemetry. NOT a full prompt/report/
Markdown-to-PPTX automation — every Stage-1-to-6 artifact the
pipeline consumes is the synthetic trial's already-authored JSON;
asset bytes are NEVER generated, fetched, or otherwise invented.

The smoke has only a ``--self-test`` invocation surface. It exits 0
on full pass, 1 on any scenario failure, 2 on a missing flag.

Usage:
  python3 scripts/trace_acceptance_smoke.py --self-test
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
TRACE_SCHEMA = REPO_ROOT / "schemas" / "conversion_trace.schema.json"
DEFAULT_BUNDLE = REPO_ROOT / "examples" / "synthetic_authoring_trial"
TEMPLATE_ROOT = REPO_ROOT / "templates" / "layouts"

# Same string scripts/inspect_pptx_inventory.py and
# scripts/acceptance_smoke.py expect on a clean run. Kept literal so a
# future basis-line change has to update both smokes together.
EXPECTED_EVIDENCE_BASIS = (
    "OOXML structure only; not proof of full PowerPoint editability"
)

# Closed two-literal enum from schemas/conversion_trace.schema.json.
# Detecting either literal in any JSON file under the default output
# tree proves the default path is silently emitting a trace sidecar.
_TRACE_PIPELINE_STATUS_LITERALS = frozenset({
    "future_contract_only",
    "runtime_emitted_by_export_pptx",
})

# Trial bundle metadata. Mirrors scripts/acceptance_smoke.py:_bundle_spec
# so both smokes describe the synthetic trial the same way.
_BUNDLE_TITLE = "Synthetic Authoring Trial"
_BUNDLE_AUDIENCE = "Internal pipeline smoke-test reviewers"
_BUNDLE_OBJECTIVE = (
    "Exercise the explicit-input authoring bundle gate end-to-end "
    "on a synthetic, non-sensitive narrative."
)
_BUNDLE_SOURCE_ID = "synthetic_trial_source"
_BUNDLE_TONE = "neutral-professional"
_BUNDLE_LANGUAGE = "en"
_BUNDLE_APPROX_SLIDE_COUNT = 7


@dataclass
class _Outcome:
    name: str
    ok: bool
    detail: str = ""


def _run(cmd: list[str]) -> tuple[int, str, str]:
    """Spawn ``cmd`` from REPO_ROOT with PYTHONDONTWRITEBYTECODE=1 so
    a __pycache__ side-effect cannot dirty the repo. Returns
    ``(returncode, stdout, stderr)``."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _walk_trace_sidecars(root: Path) -> list[Path]:
    """Return every regular ``*.json`` file under ``root`` whose
    top-level JSON object carries the conversion_trace schema's
    ``pipeline_status`` field set to one of the closed enum literals.

    The walker is deliberately permissive about non-JSON / unreadable
    files (a render_model.json that fails to parse is not a trace
    leak — it's a render_model bug, caught by other gates); the only
    files flagged are those that look like a conversion_trace
    sidecar."""
    offenders: list[Path] = []
    for p in sorted(root.rglob("*.json")):
        if p.is_symlink() or not p.is_file():
            continue
        try:
            obj = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        if (
            isinstance(obj, dict)
            and obj.get("pipeline_status") in _TRACE_PIPELINE_STATUS_LITERALS
        ):
            offenders.append(p)
    return offenders


def _snapshot(root: Path) -> dict[str, bytes]:
    """Flat ``relative-path -> bytes`` map of every regular file under
    ``root``. Symlinks are skipped (a clean checkout of this repo has
    none). Used to prove no committed file is mutated by the smoke."""
    snap: dict[str, bytes] = {}
    if not root.is_dir():
        return snap
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(root)
        snap[str(rel)] = p.read_bytes()
    return snap


def _diff_keys(
    before: dict[str, bytes], after: dict[str, bytes],
) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [k for k in keys if before.get(k) != after.get(k)]


def _expected_slide_count(plan_spec: Path) -> int:
    """Read ``len(plan_spec.slides)`` so the expected slide count is
    derived from the bundle, not hardcoded. A malformed plan_spec
    raises here; the downstream pipeline subprocess would also fail
    closed with a clean diagnostic, but the smoke aborts up-front."""
    plan = json.loads(plan_spec.read_text())
    return len(plan["slides"])


def _run_smoke() -> list[_Outcome]:
    """Run the single positive scenario.

    Returns the per-step Outcome list. The caller prints + tallies."""
    results: list[_Outcome] = []

    examples_before = _snapshot(REPO_ROOT / "examples")
    scripts_before = _snapshot(REPO_ROOT / "scripts")

    bundle = DEFAULT_BUNDLE
    plan_spec = bundle / "plan_spec.json"
    expected = _expected_slide_count(plan_spec)
    py = sys.executable

    with tempfile.TemporaryDirectory(
        prefix="szh_trace_smoke_",
    ) as raw_td:
        td = Path(raw_td)
        ws = td / "workspace"
        pptx_a = td / "default_deck.pptx"
        report_dir = td / "report"
        pptx_b = td / "trace_deck.pptx"
        trace_out = td / "trace_deck_conversion_trace.json"
        inv_b = td / "trace_deck_inventory.json"

        # 1. Default Stage 1-10 pipeline. NO --trace-out. The
        # subprocess exercises run_explicit_pipeline.py's real
        # argparse + prepare_workspace + run_pipeline chain
        # (validate_workspace, generate_render_models,
        # generate_svg_previews, export_pptx, validate_pptx_contract,
        # inspect_pptx_inventory). --report-dir makes the inventory
        # subprocess run so we exercise the same surface
        # acceptance_smoke.py exercises.
        default_cmd = [
            py, str(SCRIPTS_DIR / "run_explicit_pipeline.py"),
            "--workspace", str(ws),
            "--source", str(bundle / "source.md"),
            "--source-id", _BUNDLE_SOURCE_ID,
            "--title", _BUNDLE_TITLE,
            "--audience", _BUNDLE_AUDIENCE,
            "--objective", _BUNDLE_OBJECTIVE,
            "--tone", _BUNDLE_TONE,
            "--language", _BUNDLE_LANGUAGE,
            "--approximate-slide-count", str(_BUNDLE_APPROX_SLIDE_COUNT),
            "--plan-spec", str(bundle / "plan_spec.json"),
            "--design-system-spec", str(bundle / "design_system_spec.json"),
            "--template-root", str(TEMPLATE_ROOT),
            "--slide-specs-dir", str(bundle / "slide_specs"),
            "--image-manifest-spec", str(bundle / "image_manifest_spec.json"),
            "--output", str(pptx_a),
            "--report-dir", str(report_dir),
        ]
        rc, stdout, stderr = _run(default_cmd)
        ok = rc == 0
        results.append(_Outcome(
            "default explicit pipeline (Stage 1-10) returns rc=0",
            ok,
            (f"rc={rc}; stdout tail={stdout.splitlines()[-3:]!r}; "
             f"stderr tail={stderr.splitlines()[-3:]!r}")
            if not ok else "",
        ))
        if not ok:
            return results

        # 2. Default pipeline produced a non-empty PPTX.
        pptx_a_ok = (
            pptx_a.is_file()
            and not pptx_a.is_symlink()
            and pptx_a.stat().st_size > 0
        )
        results.append(_Outcome(
            "default pipeline produced a non-empty PPTX at --output",
            pptx_a_ok,
            f"path={pptx_a}, exists={pptx_a.exists()}, "
            f"is_symlink={pptx_a.is_symlink()}",
        ))

        # 3. Default path emits NO trace sidecar anywhere under the
        # temp output tree. This is the load-bearing assertion that
        # protects the default acceptance contract.
        offenders = _walk_trace_sidecars(td)
        results.append(_Outcome(
            "default acceptance path emits no conversion_trace sidecar "
            "(walked every *.json under the temp output tree)",
            offenders == [],
            f"offenders={[str(p.relative_to(td)) for p in offenders]!r}",
        ))

        # 4. Trace-positive export. Re-uses the same prepared
        # workspace. The PPTX bytes here are an INDEPENDENT export —
        # not the same file as pptx_a — so the trace contract is
        # exercised by the writer that actually carries --trace-out
        # logic (scripts/export_pptx.py). The trace and PPTX siblings
        # live under <td>, which is the same parent as --output, so
        # the exporter's --trace-out parent-directory gate accepts
        # the path.
        trace_export_cmd = [
            py, str(SCRIPTS_DIR / "export_pptx.py"),
            "--workspace", str(ws),
            "--output", str(pptx_b),
            "--trace-out", str(trace_out),
        ]
        rc, stdout, stderr = _run(trace_export_cmd)
        ok = rc == 0
        results.append(_Outcome(
            "export_pptx --trace-out against the prepared workspace "
            "returns rc=0",
            ok,
            (f"rc={rc}; stdout tail={stdout.splitlines()[-5:]!r}; "
             f"stderr tail={stderr.splitlines()[-5:]!r}")
            if not ok else "",
        ))
        if not ok:
            return results

        # 5. Trace-positive PPTX exists as a non-empty regular file.
        pptx_b_ok = (
            pptx_b.is_file()
            and not pptx_b.is_symlink()
            and pptx_b.stat().st_size > 0
        )
        results.append(_Outcome(
            "trace-positive PPTX exists as a non-empty regular file",
            pptx_b_ok,
            f"path={pptx_b}, exists={pptx_b.exists()}",
        ))

        # 6. Trace sidecar exists as a non-empty regular file.
        trace_ok = (
            trace_out.is_file()
            and not trace_out.is_symlink()
            and trace_out.stat().st_size > 0
        )
        results.append(_Outcome(
            "trace sidecar exists as a non-empty regular file",
            trace_ok,
            f"path={trace_out}, exists={trace_out.exists()}",
        ))
        if not (pptx_b_ok and trace_ok):
            return results

        # 7. Trace passes the read-only validator's schema + content
        # gates (T1-T15).
        rc, stdout, stderr = _run([
            py, str(SCRIPTS_DIR / "validate_conversion_trace.py"),
            "--trace", str(trace_out),
        ])
        ok = rc == 0
        results.append(_Outcome(
            "validate_conversion_trace.py passes against the produced "
            "trace",
            ok,
            f"rc={rc}; stdout={stdout!r}; stderr={stderr!r}"
            if not ok else "",
        ))

        # 8. Independent schema-only re-validation. validate_artifacts
        # exercises the same stdlib schema subset as
        # validate_conversion_trace's T2 gate, but it is a SEPARATE
        # script — proving schema conformance from two independent
        # entry points closes a regression where T2 silently drifted
        # from the schema file.
        rc, stdout, stderr = _run([
            py, str(SCRIPTS_DIR / "validate_artifacts.py"),
            "--schema", str(TRACE_SCHEMA),
            str(trace_out),
        ])
        ok = rc == 0
        results.append(_Outcome(
            "validate_artifacts.py passes the trace against "
            "schemas/conversion_trace.schema.json",
            ok,
            f"rc={rc}; stdout={stdout!r}; stderr={stderr!r}"
            if not ok else "",
        ))

        # 9. Trace-positive PPTX passes validate_pptx_contract with
        # --expected-slide-count active.
        rc, stdout, stderr = _run([
            py, str(SCRIPTS_DIR / "validate_pptx_contract.py"),
            "--pptx", str(pptx_b),
            "--expected-slide-count", str(expected),
        ])
        ok = rc == 0
        results.append(_Outcome(
            "validate_pptx_contract.py passes the trace-positive PPTX "
            f"with --expected-slide-count={expected}",
            ok,
            f"rc={rc}; stdout={stdout!r}; stderr={stderr!r}"
            if not ok else "",
        ))

        # 10. inventory remains OK on the trace-positive PPTX. We
        # re-run inspect_pptx_inventory rather than re-using the
        # report_dir inventory because the trace-positive PPTX is a
        # different file from the default one and is the artifact the
        # trace describes.
        rc, stdout, stderr = _run([
            py, str(SCRIPTS_DIR / "inspect_pptx_inventory.py"),
            "--pptx", str(pptx_b),
            "--out", str(inv_b),
        ])
        inv_landed = inv_b.is_file() and not inv_b.is_symlink()
        results.append(_Outcome(
            "inspect_pptx_inventory.py writes inventory.json with rc=0",
            rc == 0 and inv_landed,
            f"rc={rc}; inventory_file={inv_landed}; "
            f"stderr={stderr!r}" if not (rc == 0 and inv_landed) else "",
        ))
        if rc == 0 and inv_landed:
            try:
                inv = json.loads(inv_b.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                results.append(_Outcome(
                    "inventory.json parses as JSON", False,
                    f"{type(exc).__name__}: {exc}",
                ))
            else:
                contract_ok = (
                    inv.get("ok") is True
                    and inv.get("findings") == []
                    and inv.get("evidence_basis") == EXPECTED_EVIDENCE_BASIS
                    and inv.get("slide_count") == expected
                )
                results.append(_Outcome(
                    "inventory.json on trace-positive PPTX carries "
                    "ok=True / findings=[] / expected evidence_basis "
                    "/ expected slide_count",
                    contract_ok,
                    (
                        f"ok={inv.get('ok')!r}; "
                        f"findings_len={len(inv.get('findings') or [])}; "
                        f"basis={inv.get('evidence_basis')!r}; "
                        f"slide_count={inv.get('slide_count')!r}"
                    ) if not contract_ok else "",
                ))

    examples_after = _snapshot(REPO_ROOT / "examples")
    scripts_after = _snapshot(REPO_ROOT / "scripts")
    results.append(_Outcome(
        "no file under REPO_ROOT/examples/ was mutated by the smoke",
        examples_before == examples_after,
        f"changed={_diff_keys(examples_before, examples_after)!r}",
    ))
    results.append(_Outcome(
        "no file under REPO_ROOT/scripts/ was mutated by the smoke",
        scripts_before == scripts_after,
        f"changed={_diff_keys(scripts_before, scripts_after)!r}",
    ))
    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Trace acceptance smoke for the opt-in conversion-trace "
            "sidecar. Stdlib-only; no network, no D-One, no model API. "
            "Runs the entire scenario under tempfile.TemporaryDirectory() "
            "so no artifact lands in the repo."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run the in-script positive scenario: prove the default "
            "Stage 1-10 pipeline emits no conversion_trace sidecar, "
            "then prove an explicit export_pptx --trace-out invocation "
            "against the SAME prepared workspace produces a valid PPTX "
            "+ trace and that inspect_pptx_inventory remains OK."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "error: --self-test is required (this script has no other "
            "invocation surface today)",
            file=sys.stderr,
        )
        return 2

    print("=== trace acceptance smoke ===")
    results = _run_smoke()
    fails = 0
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        suffix = f" -- {r.detail}" if not r.ok and r.detail else ""
        print(f"  [{mark}] {r.name}{suffix}")
        if not r.ok:
            fails += 1
    print()
    if fails:
        print(
            f"FAIL: {fails} scenario(s) did not behave as expected.",
            file=sys.stderr,
        )
        return 1
    print(
        f"OK (trace acceptance smoke): {len(results)} scenario(s) "
        f"passed. The opt-in --trace-out export path produces a valid "
        f"conversion_trace sidecar end-to-end, and the default "
        f"acceptance path emits no trace."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
